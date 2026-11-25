"""Motor de Transformação do Produto Tensorial (TPMT) — Frente F5 (CL-TS-MOD-DIR-001 Seções 4 e 5).

Implementa em NumPy/SciPy puro (100% compatível com Pyodide `wasm32`, ZERO `linalg.inv`, ZERO `eval`/`exec`):
- Álgebra tensorial vetorizada: `unfold_mode`, `fold_mode`, `mode_product`, `mode_inverse_product`;
- Decomposições multilineares preservando modos matriciais (`ord_func=2`):
  `hosvd_sampled_func` (com cota de truncamento de De Lathauwer) e
  `hooi_sampled_func` (contrações sequenciais sem produto de Kronecker explícito);
- Reamostragem 1D opcional pós-SVD: `resample_basis_1d` (`linear` e `pchip`);
- Transformações de fecho convexo:
  `sn_nn_matrix` (via `lstsq` + identidade fechada de Sherman–Morrison),
  `rno_ino_matrix` (Várkonyi et al. 2005 com bisseção determinística até `1e-11`),
  `cno_matrix` (`ConvexHull` + `SLSQP` com gradiente analítico sem YALMIP e fallback seguro),
  `mgk_matrix` (com auditoria explícita `NN_VIOLATED`);
- Pipeline completo com envelope Wasm, extração automática de variáveis não-lineares ativas,
  certificado de fidelidade na grade e fora da grade e construção de `TSStateSpace`: `derive_ts_tpmt`.
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Mapping, NamedTuple, Sequence

import numpy as np
from scipy import linalg as scipy_linalg
from scipy.interpolate import PchipInterpolator
from scipy.optimize import minimize
from scipy.spatial import ConvexHull, QhullError
from scipy.stats import qmc

from control_lab.core.models import TSStateSpace
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    NumericalInconclusiveError,
    ResourceLimitError,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .sector_nonlinearity import (
    ALLOWED_GENERALIZED_CHANNELS,
    _eval_symbolic_matrix_batch,
    _normalize_bounds_map,
    _parse_symbolic_matrix,
    _resolve_measured_flags,
)
from .symbolic_qlpv import ParsedExpression

# Limites normativos do envelope Wasm (CL-TS-MOD-DIR-001 Seção 4.5)
MAX_TPMT_DIMS_WARN = 3
MAX_TPMT_DIMS_HARD = 5
MAX_TPMT_GRID_NODES_WARN = 50_000
MAX_TPMT_GRID_NODES_HARD = 250_000
MAX_TPMT_ELEMENTS_WARN = 2_000_000
MAX_TPMT_ELEMENTS_HARD = 10_000_000
MAX_TPMT_RULES_WARN = 32
MAX_TPMT_RULES_HARD = 256

SUPPORTED_HULL_TYPES: frozenset[str] = frozenset({"SN-NN", "RNO-INO", "CNO", "MGK"})
SUPPORTED_DECOMPOSITIONS: frozenset[str] = frozenset({"hosvd", "hooi"})
SUPPORTED_RESAMPLE_METHODS: frozenset[str] = frozenset({"linear", "pchip"})


class HOSVDResult(NamedTuple):
    """Resultado estruturado da HOSVD truncada/compacta (desempacotável em 4 elementos)."""

    core: np.ndarray
    U_list: list[np.ndarray]
    singular_values: list[np.ndarray]
    truncation_bound: float


class HOOIResult(NamedTuple):
    """Resultado estruturado da HOOI (desempacotável em 6 elementos)."""

    core: np.ndarray
    U_list: list[np.ndarray]
    singular_values: list[np.ndarray]
    error_history: list[float]
    n_iter: int
    converged: bool


# ---------------------------------------------------------------------------
# 1. Álgebra Tensorial Vetorizada (0-indexed, ZERO linalg.inv)
# ---------------------------------------------------------------------------


def _ensure_finite_tensor(tensor: np.ndarray | Sequence[Any], *, name: str = "tensor") -> np.ndarray:
    arr = np.asarray(tensor, dtype=np.float64)
    if arr.ndim < 1:
        raise ValidationError(f"{name} deve ter pelo menos 1 dimensão, recebido ndim={arr.ndim}.")
    if arr.size == 0:
        raise ValidationError(f"{name} não pode ser vazio.")
    if not np.all(np.isfinite(arr)):
        raise ValidationError(f"{name} contém valores não finitos (NaN/Inf).")
    return arr


def unfold_mode(tensor: np.ndarray, mode: int) -> np.ndarray:
    """Desdobra o tensor ao longo do modo `mode` (0-indexed) via `np.moveaxis` + `reshape`."""
    arr = _ensure_finite_tensor(tensor, name="tensor")
    if not isinstance(mode, (int, np.integer)) or isinstance(mode, bool):
        raise ValidationError(f"mode deve ser inteiro, recebido {type(mode).__name__}.")
    m = int(mode)
    if m < 0 or m >= arr.ndim:
        raise DimensionMismatchError(f"mode={m} fora do intervalo válido [0, {arr.ndim - 1}].")
    moved = np.moveaxis(arr, m, 0)
    return moved.reshape(arr.shape[m], -1)


def fold_mode(matrix: np.ndarray, mode: int, shape: Sequence[int]) -> np.ndarray:
    """Recompõe um tensor de forma `shape` a partir do desdobramento no modo `mode` (0-indexed)."""
    mat = np.asarray(matrix, dtype=np.float64)
    if mat.ndim != 2:
        raise DimensionMismatchError(f"matrix deve ser 2D, recebido ndim={mat.ndim}.")
    if not np.all(np.isfinite(mat)):
        raise ValidationError("matrix contém valores não finitos (NaN/Inf).")
    target_shape = tuple(int(s) for s in shape)
    if len(target_shape) < 1 or any(s <= 0 for s in target_shape):
        raise ValidationError(f"shape inválido para fold_mode: {target_shape}.")
    if not isinstance(mode, (int, np.integer)) or isinstance(mode, bool):
        raise ValidationError(f"mode deve ser inteiro, recebido {type(mode).__name__}.")
    m = int(mode)
    if m < 0 or m >= len(target_shape):
        raise DimensionMismatchError(f"mode={m} fora do intervalo válido [0, {len(target_shape) - 1}].")
    expected_cols = int(math.prod(target_shape[i] for i in range(len(target_shape)) if i != m))
    if mat.shape != (target_shape[m], expected_cols):
        raise DimensionMismatchError(
            f"matrix com shape {mat.shape} incompatível com mode={m} e target_shape={target_shape} "
            f"(esperado {(target_shape[m], expected_cols)})."
        )
    moved_shape = (target_shape[m],) + tuple(target_shape[i] for i in range(len(target_shape)) if i != m)
    reshaped = mat.reshape(moved_shape)
    return np.moveaxis(reshaped, 0, m)


def mode_product(tensor: np.ndarray, matrix: np.ndarray, mode: int) -> np.ndarray:
    """Calcula o produto em modo-`mode` `tensor x_mode matrix` via `np.tensordot` + `np.moveaxis`."""
    arr = _ensure_finite_tensor(tensor, name="tensor")
    mat = np.asarray(matrix, dtype=np.float64)
    if mat.ndim != 2:
        raise DimensionMismatchError(f"matrix deve ser 2D, recebido ndim={mat.ndim}.")
    if not np.all(np.isfinite(mat)):
        raise ValidationError("matrix contém valores não finitos (NaN/Inf).")
    if not isinstance(mode, (int, np.integer)) or isinstance(mode, bool):
        raise ValidationError(f"mode deve ser inteiro, recebido {type(mode).__name__}.")
    m = int(mode)
    if m < 0 or m >= arr.ndim:
        raise DimensionMismatchError(f"mode={m} fora do intervalo válido [0, {arr.ndim - 1}].")
    if mat.shape[1] != arr.shape[m]:
        raise DimensionMismatchError(
            f"Dimensão incompatível em mode_product: matrix.shape={mat.shape} vs tensor.shape[{m}]={arr.shape[m]}."
        )
    prod = np.tensordot(mat, arr, axes=([1], [m]))
    return np.moveaxis(prod, 0, m)


def mode_inverse_product(
    tensor: np.ndarray,
    matrix: np.ndarray,
    mode: int,
    *,
    cond_limit: float = 1e12,
) -> np.ndarray:
    """Aplica `tensor x_mode matrix^{-1}` via `scipy.linalg.solve` (ZERO `linalg.inv`)."""
    arr = _ensure_finite_tensor(tensor, name="tensor")
    mat = np.asarray(matrix, dtype=np.float64)
    if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
        raise DimensionMismatchError(f"matrix deve ser quadrada 2D, recebido shape={mat.shape}.")
    if not np.all(np.isfinite(mat)):
        raise ValidationError("matrix contém valores não finitos (NaN/Inf).")
    if not isinstance(mode, (int, np.integer)) or isinstance(mode, bool):
        raise ValidationError(f"mode deve ser inteiro, recebido {type(mode).__name__}.")
    m = int(mode)
    if m < 0 or m >= arr.ndim:
        raise DimensionMismatchError(f"mode={m} fora do intervalo válido [0, {arr.ndim - 1}].")
    if mat.shape[0] != arr.shape[m]:
        raise DimensionMismatchError(
            f"Dimensão incompatível em mode_inverse_product: matrix.shape={mat.shape} "
            f"vs tensor.shape[{m}]={arr.shape[m]}."
        )

    cond_val = float(np.linalg.cond(mat))
    if not math.isfinite(cond_val) or cond_val > cond_limit:
        raise NumericalInconclusiveError(
            message=(
                f"Matriz de transformação mal-condicionada ou singular no modo {m}: "
                f"cond(T) = {cond_val:.3e} > {cond_limit:.3e}."
            ),
            parameters={"mode": m, "cond": cond_val, "cond_limit": cond_limit},
        )

    unfolded = unfold_mode(arr, m)
    try:
        solved = scipy_linalg.solve(mat, unfolded, check_finite=False)
    except scipy_linalg.LinAlgError as exc:
        raise NumericalInconclusiveError(
            message=f"Falha ao resolver sistema linear no modo {m}: {exc}",
            parameters={"mode": m, "cond": cond_val},
        ) from exc
    if not np.all(np.isfinite(solved)):
        raise NumericalInconclusiveError(
            message=f"Resultado não finito ao aplicar transformação inversa no modo {m}.",
            parameters={"mode": m, "cond": cond_val},
        )
    return fold_mode(solved, m, arr.shape)


def reconstruct_tensor(core: np.ndarray, factor_matrices: Sequence[np.ndarray]) -> np.ndarray:
    """Reconstrói `core x_0 U_0 x_1 U_1 ... x_{D-1} U_{D-1}`."""
    res = np.asarray(core, dtype=np.float64)
    for d, U_d in enumerate(factor_matrices):
        res = mode_product(res, U_d, d)
    return res


# ---------------------------------------------------------------------------
# 2. Decomposições Multilineares (HOSVD & HOOI, preservando ord_func=2)
# ---------------------------------------------------------------------------


def hosvd_sampled_func(
    tensor: np.ndarray,
    tol: float = 1e-6,
    ranks: Sequence[int] | None = None,
    ord_func: int = 2,
) -> HOSVDResult:
    """HOSVD compacta/truncada preservando os `ord_func` modos finais da imagem matricial."""
    arr = _ensure_finite_tensor(tensor, name="tensor")
    if ord_func < 0 or ord_func >= arr.ndim:
        raise ValidationError(
            f"ord_func={ord_func} inválido para tensor de ordem {arr.ndim} (requer 0 <= ord_func < ndim)."
        )
    if tol < 0.0 or not math.isfinite(tol):
        raise ValidationError(f"tol deve ser finito e não negativo, recebido {tol!r}.")

    n_param_modes = arr.ndim - ord_func
    if ranks is not None:
        if len(ranks) != n_param_modes:
            raise DimensionMismatchError(
                f"ranks deve ter comprimento {n_param_modes}, recebido {len(ranks)}."
            )

    core = arr.copy()
    U_list: list[np.ndarray] = []
    singular_values: list[np.ndarray] = []
    tail_sq_sum = 0.0

    for d in range(n_param_modes):
        unfolded = unfold_mode(arr, d)
        Ua, s, _ = scipy_linalg.svd(unfolded, full_matrices=False)
        singular_values.append(np.asarray(s, dtype=np.float64))

        if ranks is not None:
            r_d = int(ranks[d])
            if r_d < 1 or r_d > Ua.shape[1]:
                raise ValidationError(
                    f"Posto solicitado ranks[{d}]={r_d} fora do intervalo válido [1, {Ua.shape[1]}]."
                )
        else:
            if s.size == 0 or s[0] <= 0.0:
                r_d = 1
            else:
                r_d = int(np.sum(s > tol * s[0]))
                r_d = max(1, min(r_d, Ua.shape[1]))

        U_d = np.asarray(Ua[:, :r_d], dtype=np.float64)
        U_list.append(U_d)
        core = mode_product(core, U_d.T, d)
        if r_d < s.size:
            tail_sq_sum += float(np.sum(s[r_d:] ** 2))

    truncation_bound = math.sqrt(max(0.0, tail_sq_sum))
    return HOSVDResult(
        core=core,
        U_list=U_list,
        singular_values=singular_values,
        truncation_bound=truncation_bound,
    )


def hooi_sampled_func(
    tensor: np.ndarray,
    ranks: Sequence[int] | None = None,
    tol: float = 1e-6,
    ord_func: int = 2,
    max_iter: int = 50,
    conv_tol: float = 1e-9,
) -> HOOIResult:
    """HOOI inicializada por HOSVD usando contrações sequenciais em modo-l (ZERO Kronecker)."""
    if max_iter < 1:
        raise ValidationError(f"max_iter deve ser >= 1, recebido {max_iter}.")
    if conv_tol <= 0.0 or not math.isfinite(conv_tol):
        raise ValidationError(f"conv_tol deve ser finito e positivo, recebido {conv_tol!r}.")

    arr = _ensure_finite_tensor(tensor, name="tensor")
    hosvd_res = hosvd_sampled_func(arr, tol=tol, ranks=ranks, ord_func=ord_func)
    core = hosvd_res.core
    U_list = [u.copy() for u in hosvd_res.U_list]
    singular_values = hosvd_res.singular_values
    n_param_modes = len(U_list)
    eff_ranks = [u.shape[1] for u in U_list]

    init_err = float(np.linalg.norm(arr - reconstruct_tensor(core, U_list)))
    error_history: list[float] = [init_err]

    if n_param_modes == 1:
        return HOOIResult(
            core=core,
            U_list=U_list,
            singular_values=singular_values,
            error_history=error_history,
            n_iter=0,
            converged=True,
        )

    converged = False
    n_iter = 0
    for it in range(1, max_iter + 1):
        n_iter = it
        max_subspace_diff = 0.0
        for d in range(n_param_modes):
            # Contração sequencial Y^(d) = S^D x_{l != d} (U^(l))^T sem produto de Kronecker
            Y = arr
            for l in range(n_param_modes):
                if l != d:
                    Y = mode_product(Y, U_list[l].T, l)
            Y_d = unfold_mode(Y, d)
            Ua, _, _ = scipy_linalg.svd(Y_d, full_matrices=False)
            U_new = np.asarray(Ua[:, : eff_ranks[d]], dtype=np.float64)

            # Métrica de projeção invariante a sinal/rotação ortogonal
            proj_old = U_list[d] @ U_list[d].T
            proj_new = U_new @ U_new.T
            diff_d = float(np.linalg.norm(proj_new - proj_old, ord="fro"))
            if diff_d > max_subspace_diff:
                max_subspace_diff = diff_d
            U_list[d] = U_new

        core = arr
        for d in range(n_param_modes):
            core = mode_product(core, U_list[d].T, d)
        err_it = float(np.linalg.norm(arr - reconstruct_tensor(core, U_list)))
        error_history.append(err_it)

        if max_subspace_diff <= conv_tol:
            converged = True
            break

    return HOOIResult(
        core=core,
        U_list=U_list,
        singular_values=singular_values,
        error_history=error_history,
        n_iter=n_iter,
        converged=converged,
    )


# ---------------------------------------------------------------------------
# 3. Reamostragem 1D Opcional Pós-SVD (Passo 3 de test_uni.m)
# ---------------------------------------------------------------------------


def resample_basis_1d(
    grid: Sequence[float] | np.ndarray,
    U: np.ndarray,
    fine_points: int | Sequence[float] | np.ndarray,
    method: str = "linear",
) -> tuple[np.ndarray, np.ndarray]:
    """Reamostra as colunas de `U` (shape `(G, R)`) sobre uma grade 1D fina (`linear` ou `pchip`)."""
    g = np.asarray(grid, dtype=np.float64)
    U_arr = np.asarray(U, dtype=np.float64)
    if g.ndim != 1 or g.size < 2:
        raise ValidationError("grid deve ser vetor 1D com pelo menos 2 pontos.")
    if not np.all(np.isfinite(g)) or not np.all(np.diff(g) > 0.0):
        raise ValidationError("grid deve ser finito e estritamente crescente.")
    if U_arr.ndim != 2 or U_arr.shape[0] != g.size:
        raise DimensionMismatchError(
            f"U deve ter shape ({g.size}, R), recebido {U_arr.shape}."
        )
    if not np.all(np.isfinite(U_arr)):
        raise ValidationError("U contém valores não finitos (NaN/Inf).")

    meth = str(method).strip().lower()
    if meth not in SUPPORTED_RESAMPLE_METHODS:
        raise ValidationError(
            f"Método de reamostragem inválido: {method!r}. Suportados: {sorted(SUPPORTED_RESAMPLE_METHODS)}."
        )

    if isinstance(fine_points, (int, np.integer)) and not isinstance(fine_points, bool):
        n_fine = int(fine_points)
        if n_fine < 2:
            raise ValidationError(f"fine_points deve ser >= 2, recebido {n_fine}.")
        fine_grid = np.linspace(float(g[0]), float(g[-1]), n_fine, dtype=np.float64)
    else:
        fine_grid = np.asarray(fine_points, dtype=np.float64)
        if fine_grid.ndim != 1 or fine_grid.size < 2:
            raise ValidationError("fine_points como sequência deve ser 1D com pelo menos 2 pontos.")
        if not np.all(np.isfinite(fine_grid)) or not np.all(np.diff(fine_grid) > 0.0):
            raise ValidationError("fine_points deve ser finito e estritamente crescente.")
        if fine_grid[0] < g[0] - 1e-12 or fine_grid[-1] > g[-1] + 1e-12:
            raise ValidationError(
                f"fine_points [{fine_grid[0]}, {fine_grid[-1]}] extrapola o domínio original [{g[0]}, {g[-1]}]."
            )

    r = U_arr.shape[1]
    U_fine = np.empty((fine_grid.size, r), dtype=np.float64)
    if meth == "linear":
        for j in range(r):
            U_fine[:, j] = np.interp(fine_grid, g, U_arr[:, j])
    else:
        for j in range(r):
            interp = PchipInterpolator(g, U_arr[:, j])
            U_fine[:, j] = interp(fine_grid)

    return fine_grid, U_fine


# ---------------------------------------------------------------------------
# 4. Transformações de Fecho Convexo (SN-NN, RNO-INO, CNO, MGK — ZERO inv)
# ---------------------------------------------------------------------------


def sn_nn_matrix(
    U: np.ndarray,
    core: np.ndarray | None = None,
    mode: int | None = None,
    sn_tol: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Converte a matriz de base `U` (G x R) em matriz SN-NN (soma 1, não-negativa).

    - Usa `scipy.linalg.lstsq(U, 1)` para verificar se `1 in span(U)`;
    - Se residual > `sn_tol`: anexa coluna `1 - sum(U, axis=1)` e fatia nula no `core` (modo `mode`);
    - Aplica `T_nn` e contra-transforma o `core` pela identidade exata de Sherman–Morrison
      `T_nn_inv = (1 - sum(gamma)) * I + 1 * gamma^T` (ZERO inversão numérica!).
    """
    U_arr = np.asarray(U, dtype=np.float64)
    if U_arr.ndim != 2 or U_arr.shape[0] < 1 or U_arr.shape[1] < 1:
        raise DimensionMismatchError(f"U deve ser matriz 2D não vazia, recebido shape={U_arr.shape}.")
    if not np.all(np.isfinite(U_arr)):
        raise ValidationError("U contém valores não finitos (NaN/Inf).")
    if (core is None) != (mode is None):
        raise ValidationError("Forneça ambos `core` e `mode` ou deixe ambos como None.")

    g_len, r_orig = U_arr.shape
    ones_g = np.ones(g_len, dtype=np.float64)

    alpha, _, _, _ = scipy_linalg.lstsq(U_arr, ones_g)
    sn_res_inf = float(np.max(np.abs(U_arr @ alpha - ones_g)))
    sn_res_l2 = float(np.linalg.norm(U_arr @ alpha - ones_g))

    core_out = None if core is None else np.asarray(core, dtype=np.float64).copy()

    if sn_res_inf <= sn_tol:
        rank_augmented = False
        r_prime = r_orig
        if r_orig == 1:
            T_sn = np.array([[float(alpha[0])]], dtype=np.float64)
        else:
            # Escolhe coluna pivô j_star = argmax |alpha| para garantir det(T_sn) = alpha[j_star] != 0
            j_star = int(np.argmax(np.abs(alpha)))
            if abs(float(alpha[j_star])) <= 1e-14:
                raise NumericalInconclusiveError("Vetor de projeção SN nulo em sn_nn_matrix.")
            T_sn = np.eye(r_orig, dtype=np.float64)
            col_star = alpha.copy()
            for j in range(r_orig):
                if j != j_star:
                    col_star[j] -= 1.0
            T_sn[:, j_star] = col_star
        U_sn = U_arr @ T_sn
        if core_out is not None and mode is not None:
            core_out = mode_inverse_product(core_out, T_sn, mode)
    else:
        rank_augmented = True
        r_prime = r_orig + 1
        extra_col = 1.0 - np.sum(U_arr, axis=1, keepdims=True)
        U_sn = np.hstack([U_arr, extra_col])
        T_sn = np.eye(r_prime, dtype=np.float64)
        if core_out is not None and mode is not None:
            zero_shape = list(core_out.shape)
            zero_shape[mode] = 1
            core_out = np.concatenate(
                [core_out, np.zeros(zero_shape, dtype=np.float64)],
                axis=mode,
            )

    # Transformação NN exata via deslocamento afim e inversa fechada de Sherman–Morrison
    gamma = np.minimum(0.0, np.min(U_sn, axis=0))
    sum_gamma = float(np.sum(gamma))
    denom = 1.0 - sum_gamma  # >= 1.0 sempre
    I_r = np.eye(r_prime, dtype=np.float64)
    ones_col = np.ones((r_prime, 1), dtype=np.float64)
    gamma_row = gamma.reshape(1, -1)

    T_nn = (I_r - ones_col @ gamma_row) / denom
    T_nn_inv = denom * I_r + ones_col @ gamma_row

    W = U_sn @ T_nn
    if core_out is not None and mode is not None:
        core_out = mode_product(core_out, T_nn_inv, mode)

    T_total = T_sn @ T_nn
    info: dict[str, Any] = {
        "hull_type": "SN-NN",
        "rank_before": r_orig,
        "rank_after": r_prime,
        "rank_augmented": rank_augmented,
        "sn_residual_inf": sn_res_inf,
        "sn_residual_l2": sn_res_l2,
        "gamma": [float(v) for v in gamma.tolist()],
        "min_weight": float(np.min(W)),
        "max_sum_deviation": float(np.max(np.abs(np.sum(W, axis=1) - 1.0))),
        "cond_T": float(np.linalg.cond(T_total)),
        "T_sn": T_sn,
        "T_nn": T_nn,
        "T_nn_inv": T_nn_inv,
        "core": core_out,
    }
    return W, T_total, info


def _rno_ino_2col(U: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Solução analítica fechada exata RNO-INO / CNO para r=2 colunas."""
    p = U[:, 0]
    p_min = float(np.min(p))
    p_max = float(np.max(p))
    span = p_max - p_min
    if span <= 1e-14:
        return U.copy(), np.eye(2, dtype=np.float64)
    T = np.array(
        [
            [(1.0 - p_min) / span, (p_max - 1.0) / span],
            [-p_min / span, p_max / span],
        ],
        dtype=np.float64,
    )
    W = U @ T
    return W, T


def _rno_ta(U: np.ndarray, a: float) -> np.ndarray:
    aux = np.sum(U, axis=1, keepdims=True) - 1.0
    return U + ((a - 1.0) / float(U.shape[1])) * aux


def _rno_tb(U: np.ndarray) -> np.ndarray:
    return U - np.min(U, axis=0, keepdims=True)


def _rno_tc(U: np.ndarray) -> np.ndarray:
    max_uc = np.max(U, axis=0, keepdims=True)
    safe_max = np.where(max_uc > 1e-15, max_uc, 1.0)
    return U / safe_max


def _rno_td(U: np.ndarray) -> np.ndarray:
    max_sum = float(np.max(np.sum(U, axis=1)))
    if max_sum <= 1e-15:
        return U.copy()
    return U / max_sum


def _rno_cost_bin(a: float, U: np.ndarray) -> float:
    U_a = _rno_td(_rno_tc(_rno_tb(_rno_ta(U, a))))
    return 1.0 - float(np.min(np.sum(U_a, axis=1))) - float(np.max(U_a[:, 0]))


def _rno_step(U: np.ndarray, *, bisect_tol: float = 1e-11) -> np.ndarray:
    left = 0.0
    fl = _rno_cost_bin(left, U)
    right = 1.0
    fr = _rno_cost_bin(right, U)

    # Expande `right` de forma determinística até cercar a raiz (fl <= 0 <= fr)
    for _ in range(60):
        if fr >= 0.0:
            break
        left = right
        fl = fr
        right *= 2.0
        fr = _rno_cost_bin(right, U)

    mid = 0.5 * (left + right)
    fm = _rno_cost_bin(mid, U)
    for _ in range(120):
        if (right - left) <= bisect_tol or abs(fm) <= bisect_tol:
            break
        if fm < 0.0:
            left = mid
            fl = fm
        elif fm > 0.0:
            right = mid
            fr = fm
        else:
            break
        mid = 0.5 * (left + right)
        fm = _rno_cost_bin(mid, U)

    # Mantém a extremidade com sinal seguro se fl e fr tiverem sinais iguais
    _ = (fl, fr)
    return _rno_td(_rno_tc(_rno_tb(_rno_ta(U, mid))))


def _tighten_nn_convex(W: np.ndarray, T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Aplica micro-encolhimento convexo exato somente se min(W) < 0 por ruído numérico."""
    gamma = np.minimum(0.0, np.min(W, axis=0))
    if float(np.min(gamma)) >= 0.0:
        return W, T
    r = T.shape[0]
    denom = 1.0 - float(np.sum(gamma))
    T_fix = (np.eye(r, dtype=np.float64) - np.ones((r, 1), dtype=np.float64) @ gamma.reshape(1, -1)) / denom
    return W @ T_fix, T @ T_fix


def rno_ino_matrix(
    U_sn_nn: np.ndarray,
    *,
    core: np.ndarray | None = None,
    mode: int | None = None,
    bisect_tol: float = 1e-11,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Transformação RNO-INO fiel a `rno_ino_matrix.m` (Várkonyi et al., 2005; ZERO `inv`)."""
    U_arr = np.asarray(U_sn_nn, dtype=np.float64)
    if U_arr.ndim != 2 or U_arr.shape[0] < 1 or U_arr.shape[1] < 1:
        raise DimensionMismatchError(f"U_sn_nn deve ser matriz 2D não vazia, recebido shape={U_arr.shape}.")
    if not np.all(np.isfinite(U_arr)):
        raise ValidationError("U_sn_nn contém valores não finitos (NaN/Inf).")
    if (core is None) != (mode is None):
        raise ValidationError("Forneça ambos `core` e `mode` ou deixe ambos como None.")

    g_len, r = U_arr.shape
    fallback_used = False

    if r == 1:
        W = np.ones((g_len, 1), dtype=np.float64)
        T_total = np.ones((1, 1), dtype=np.float64)
    elif r == 2:
        W, T_total = _rno_ino_2col(U_arr)
    else:
        U1: dict[int, np.ndarray] = {r: U_arr.copy()}
        for k in range(r, 2, -1):
            U1[k - 1] = _rno_ta(U1[k][:, : k - 1], 0.0)

        W2, _ = _rno_ino_2col(U1[2])
        U3: dict[int, np.ndarray] = {2: W2}
        for k in range(3, r + 1):
            U2bar = U3[k - 1] - U1[k - 1] + U1[k][:, : k - 1]
            U3_sub = _rno_step(U2bar, bisect_tol=bisect_tol)
            last_col = 1.0 - np.sum(U3_sub, axis=1, keepdims=True)
            U3[k] = np.hstack([U3_sub, last_col])

        W_target = U3[r]
        # Resolve U_sn_nn @ T_total = W_target via lstsq (ZERO inv)
        T_cand, _, _, _ = scipy_linalg.lstsq(U_arr, W_target)
        # Impõe SN exato nas colunas de T_cand: T[:, -1] = 1 - sum(T[:, :-1])
        T_cand[:, -1] = 1.0 - np.sum(T_cand[:, :-1], axis=1)
        W_cand = U_arr @ T_cand

        recon_err = float(np.linalg.norm(W_cand - W_target, ord="fro"))
        cond_cand = float(np.linalg.cond(T_cand))
        min_w_cand = float(np.min(W_cand))

        if (
            not math.isfinite(cond_cand)
            or cond_cand > 1e10
            or recon_err > 1e-6 * (1.0 + float(np.linalg.norm(W_target, ord="fro")))
            or min_w_cand < -1e-6
        ):
            fallback_used = True
            W = U_arr.copy()
            T_total = np.eye(r, dtype=np.float64)
        else:
            if min_w_cand < -1e-12:
                W_cand, T_cand = _tighten_nn_convex(W_cand, T_cand)
            W = U_arr @ T_cand
            T_total = T_cand

    core_out = None if core is None else mode_inverse_product(core, T_total, mode)  # type: ignore[arg-type]
    _, logabsdet = np.linalg.slogdet(T_total)
    info: dict[str, Any] = {
        "hull_type": "RNO-INO",
        "rank_before": r,
        "rank_after": r,
        "min_weight": float(np.min(W)),
        "max_sum_deviation": float(np.max(np.abs(np.sum(W, axis=1) - 1.0))),
        "cond_T": float(np.linalg.cond(T_total)),
        "log_abs_det_T": float(logabsdet),
        "fallback_used": fallback_used,
        "core": core_out,
    }
    return W, T_total, info


def _extract_hull_rows(U_sn_nn: np.ndarray) -> tuple[np.ndarray, bool]:
    """Reduz as linhas de `U_sn_nn` aos vértices do fecho convexo em R^{r-1}."""
    r = U_sn_nn.shape[1]
    if r <= 2 or U_sn_nn.shape[0] <= r + 1:
        uniq = np.unique(np.round(U_sn_nn, decimals=12), axis=0)
        return (uniq if uniq.shape[0] >= r else U_sn_nn), False
    try:
        hull = ConvexHull(U_sn_nn[:, :-1])
        idx = np.unique(hull.vertices)
        if idx.size >= r:
            return U_sn_nn[idx, :], True
    except (QhullError, ValueError):
        pass
    uniq = np.unique(np.round(U_sn_nn, decimals=12), axis=0)
    return (uniq if uniq.shape[0] >= r else U_sn_nn), False


def _unpack_cno_T(x: np.ndarray, r: int) -> np.ndarray:
    T_free = x.reshape(r, r - 1)
    T_last = 1.0 - np.sum(T_free, axis=1, keepdims=True)
    return np.hstack([T_free, T_last])


def _solve_cno_slsqp(U_hull: np.ndarray, T_init: np.ndarray) -> tuple[np.ndarray, bool, float]:
    """Minimiza `-log|det(T)|` sujeito a `U_hull @ T >= 0` e `T @ 1 == 1` via SLSQP + gradiente analítico."""
    h_count, r = U_hull.shape
    n_vars = r * (r - 1)
    I_r = np.eye(r, dtype=np.float64)

    # Pré-calcula o Jacobiano constante das restrições lineares U_hull @ T >= 0
    # Restrição (h, j) para j < r - 1: sum_i U_hull[h, i] * T[i, j]
    # Restrição (h, r - 1): 1 - sum_i sum_{k=0}^{r-2} U_hull[h, i] * T[i, k]
    jac_ineq = np.zeros((h_count * r, n_vars), dtype=np.float64)
    for h_idx in range(h_count):
        u_row = U_hull[h_idx]
        for j in range(r - 1):
            row_id = h_idx * r + j
            for i in range(r):
                jac_ineq[row_id, i * (r - 1) + j] = u_row[i]
        row_last = h_idx * r + (r - 1)
        for i in range(r):
            for k in range(r - 1):
                jac_ineq[row_last, i * (r - 1) + k] = -u_row[i]

    def objective(x: np.ndarray) -> float:
        T = _unpack_cno_T(x, r)
        sign, logabsdet = np.linalg.slogdet(T)
        if sign == 0 or not math.isfinite(logabsdet):
            return 1e6
        return float(-logabsdet)

    def grad_objective(x: np.ndarray) -> np.ndarray:
        T = _unpack_cno_T(x, r)
        try:
            # G = -T^{-T} via scipy.linalg.solve (ZERO linalg.inv)
            T_inv_T = scipy_linalg.solve(T.T, I_r, check_finite=False)
        except scipy_linalg.LinAlgError:
            return np.zeros(n_vars, dtype=np.float64)
        G = -T_inv_T
        grad_free = G[:, :-1] - G[:, -1:]
        return grad_free.ravel()

    def ineq_fun(x: np.ndarray) -> np.ndarray:
        T = _unpack_cno_T(x, r)
        return (U_hull @ T).ravel()

    def ineq_jac(_x: np.ndarray) -> np.ndarray:
        return jac_ineq

    x0 = T_init[:, :-1].ravel().copy()
    res = minimize(
        objective,
        x0,
        method="SLSQP",
        jac=grad_objective,
        constraints=[{"type": "ineq", "fun": ineq_fun, "jac": ineq_jac}],
        options={"maxiter": 250, "ftol": 1e-11, "disp": False},
    )
    T_opt = _unpack_cno_T(res.x, r)
    sign, logabsdet = np.linalg.slogdet(T_opt)
    ok = bool(sign != 0 and math.isfinite(logabsdet) and np.all(np.isfinite(T_opt)))
    return T_opt, ok, float(-logabsdet if ok else 1e6)


def cno_matrix(
    U_sn_nn: np.ndarray,
    *,
    core: np.ndarray | None = None,
    mode: int | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Transformação CNO (simplex de volume mínimo) em NumPy/SciPy puro (ZERO YALMIP, ZERO `inv`)."""
    U_arr = np.asarray(U_sn_nn, dtype=np.float64)
    if U_arr.ndim != 2 or U_arr.shape[0] < 1 or U_arr.shape[1] < 1:
        raise DimensionMismatchError(f"U_sn_nn deve ser matriz 2D não vazia, recebido shape={U_arr.shape}.")
    if not np.all(np.isfinite(U_arr)):
        raise ValidationError("U_sn_nn contém valores não finitos (NaN/Inf).")
    if (core is None) != (mode is None):
        raise ValidationError("Forneça ambos `core` e `mode` ou deixe ambos como None.")

    g_len, r = U_arr.shape
    fallback_used = False
    used_convex_hull = False
    n_hull_vertices = g_len

    if r == 1:
        W = np.ones((g_len, 1), dtype=np.float64)
        T_final = np.ones((1, 1), dtype=np.float64)
    elif r == 2:
        W, T_final = _rno_ino_2col(U_arr)
    else:
        U_hull, used_convex_hull = _extract_hull_rows(U_arr)
        n_hull_vertices = int(U_hull.shape[0])

        # Baseline RNO-INO (garante que CNO nunca piore sobre RNO-INO nem sobre SN-NN)
        W_rno, T_rno, info_rno = rno_ino_matrix(U_arr)
        _, logdet_rno = np.linalg.slogdet(T_rno)
        best_T = T_rno
        best_W = W_rno
        best_obj = float(-logdet_rno)
        best_from_cno = False

        # Tenta SLSQP a partir de T_0 = I_r e a partir de T_rno (se diferente de I_r)
        starts = [np.eye(r, dtype=np.float64)]
        if float(np.linalg.norm(T_rno - np.eye(r, dtype=np.float64))) > 1e-9:
            starts.append(T_rno)

        for T_start in starts:
            T_cand, ok, _ = _solve_cno_slsqp(U_hull, T_start)
            if not ok:
                continue
            W_cand = U_arr @ T_cand
            if float(np.min(W_cand)) < -1e-12:
                W_cand, T_cand = _tighten_nn_convex(W_cand, T_cand)
                W_cand = U_arr @ T_cand

            cond_cand = float(np.linalg.cond(T_cand))
            min_w = float(np.min(W_cand))
            sum_dev = float(np.max(np.abs(np.sum(W_cand, axis=1) - 1.0)))
            sign_c, logdet_c = np.linalg.slogdet(T_cand)

            if (
                sign_c != 0
                and math.isfinite(logdet_c)
                and math.isfinite(cond_cand)
                and cond_cand <= 1e10
                and min_w >= -1e-10
                and sum_dev <= 1e-10
            ):
                obj_c = float(-logdet_c)
                if obj_c < best_obj - 1e-12:
                    best_obj = obj_c
                    best_T = T_cand
                    best_W = W_cand
                    best_from_cno = True

        if not best_from_cno:
            fallback_used = True
        T_final = best_T
        W = best_W
        _ = info_rno

    core_out = None if core is None else mode_inverse_product(core, T_final, mode)  # type: ignore[arg-type]
    _, logabsdet = np.linalg.slogdet(T_final)
    info: dict[str, Any] = {
        "hull_type": "CNO",
        "rank_before": r,
        "rank_after": r,
        "used_convex_hull": used_convex_hull,
        "n_hull_vertices": n_hull_vertices,
        "min_weight": float(np.min(W)),
        "max_sum_deviation": float(np.max(np.abs(np.sum(W, axis=1) - 1.0))),
        "cond_T": float(np.linalg.cond(T_final)),
        "log_abs_det_T": float(logabsdet),
        "fallback_used": fallback_used,
        "core": core_out,
    }
    return W, T_final, info


def mgk_matrix(
    U_sn_nn: np.ndarray,
    *,
    core: np.ndarray | None = None,
    mode: int | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Transformação MGK fiel a `mgk_matrix.m` (minimiza sobreposição não-adjacente; ZERO `inv`).

    Sinaliza explicitamente `nn_violated=True` se `min(W) < -1e-9`.
    """
    U_arr = np.asarray(U_sn_nn, dtype=np.float64)
    if U_arr.ndim != 2 or U_arr.shape[0] < 1 or U_arr.shape[1] < 1:
        raise DimensionMismatchError(f"U_sn_nn deve ser matriz 2D não vazia, recebido shape={U_arr.shape}.")
    if not np.all(np.isfinite(U_arr)):
        raise ValidationError("U_sn_nn contém valores não finitos (NaN/Inf).")
    if (core is None) != (mode is None):
        raise ValidationError("Forneça ambos `core` e `mode` ou deixe ambos como None.")

    g_len, r = U_arr.shape
    if r <= 2:
        W = U_arr.copy()
        T_final = np.eye(r, dtype=np.float64)
    else:
        lim = min(0.1, 0.9 / float(r)) if r < 10 else (0.9 / float(r))
        col_sum_floor = lim * float(g_len)
        U_hull, _ = _extract_hull_rows(U_arr)
        col_sums_U = np.sum(U_arr, axis=0)

        def mgk_obj(x: np.ndarray) -> float:
            T = _unpack_cno_T(x, r)
            W_loc = U_arr @ T
            cost = 0.0
            for i in range(r):
                wi = W_loc[:, i]
                for j in range(i + 2, r):
                    dot_ij = float(np.dot(wi, W_loc[:, j]))
                    cost += dot_ij * dot_ij
            return cost

        def mgk_ineq_nn(x: np.ndarray) -> np.ndarray:
            T = _unpack_cno_T(x, r)
            return (U_hull @ T).ravel()

        def mgk_ineq_colsum(x: np.ndarray) -> np.ndarray:
            T = _unpack_cno_T(x, r)
            return (col_sums_U @ T) - col_sum_floor

        x0 = np.eye(r, dtype=np.float64)[:, :-1].ravel()
        res = minimize(
            mgk_obj,
            x0,
            method="SLSQP",
            constraints=[
                {"type": "ineq", "fun": mgk_ineq_nn},
                {"type": "ineq", "fun": mgk_ineq_colsum},
            ],
            options={"maxiter": 200, "ftol": 1e-10, "disp": False},
        )
        T_cand = _unpack_cno_T(res.x, r)
        cond_cand = float(np.linalg.cond(T_cand))
        if not np.all(np.isfinite(T_cand)) or not math.isfinite(cond_cand) or cond_cand > 1e10:
            T_final = np.eye(r, dtype=np.float64)
        else:
            T_final = T_cand
        W = U_arr @ T_final

    min_w = float(np.min(W))
    nn_violated = bool(min_w < -1e-9)
    core_out = None if core is None else mode_inverse_product(core, T_final, mode)  # type: ignore[arg-type]
    _, logabsdet = np.linalg.slogdet(T_final)
    info: dict[str, Any] = {
        "hull_type": "MGK",
        "rank_before": r,
        "rank_after": r,
        "min_weight": min_w,
        "max_sum_deviation": float(np.max(np.abs(np.sum(W, axis=1) - 1.0))),
        "cond_T": float(np.linalg.cond(T_final)),
        "log_abs_det_T": float(logabsdet),
        "nn_violated": nn_violated,
        "warning_code": "NN_VIOLATED" if nn_violated else None,
        "core": core_out,
    }
    return W, T_final, info


# ---------------------------------------------------------------------------
# 5. Auxiliares de Resolução de Parâmetros por Eixo e Auditoria TPMT
# ---------------------------------------------------------------------------


def _resolve_per_axis_int(
    spec: int | Mapping[str, int] | Sequence[int],
    axis_names: Sequence[str],
    *,
    field_name: str,
    min_value: int = 1,
) -> list[int]:
    d_len = len(axis_names)
    if isinstance(spec, (int, np.integer)) and not isinstance(spec, bool):
        val = int(spec)
        if val < min_value:
            raise ValidationError(f"{field_name} deve ser >= {min_value}, recebido {val}.")
        return [val] * d_len
    if isinstance(spec, Mapping):
        out: list[int] = []
        for nm in axis_names:
            if nm not in spec:
                raise ValidationError(f"{field_name} não especificou valor para a variável ativa {nm!r}.")
            v = int(spec[nm])
            if v < min_value:
                raise ValidationError(f"{field_name}[{nm!r}] deve ser >= {min_value}, recebido {v}.")
            out.append(v)
        return out
    if isinstance(spec, Sequence) and not isinstance(spec, (str, bytes)):
        if len(spec) != d_len:
            raise DimensionMismatchError(
                f"{field_name} deve ter comprimento {d_len} (variáveis ativas {list(axis_names)}), recebido {len(spec)}."
            )
        out = [int(v) for v in spec]
        for idx, v in enumerate(out):
            if v < min_value:
                raise ValidationError(f"{field_name}[{idx}] deve ser >= {min_value}, recebido {v}.")
        return out
    raise ValidationError(f"Tipo inválido para {field_name}: {type(spec).__name__}.")


def _resolve_per_axis_hull(
    hull_type: str | Mapping[str, str] | Sequence[str],
    axis_names: Sequence[str],
) -> list[str]:
    d_len = len(axis_names)
    if isinstance(hull_type, str):
        norm = hull_type.strip().upper()
        if norm not in SUPPORTED_HULL_TYPES:
            raise ValidationError(
                f"hull_type inválido: {hull_type!r}. Suportados: {sorted(SUPPORTED_HULL_TYPES)}."
            )
        return [norm] * d_len
    if isinstance(hull_type, Mapping):
        out: list[str] = []
        for nm in axis_names:
            raw = str(hull_type.get(nm, "CNO")).strip().upper()
            if raw not in SUPPORTED_HULL_TYPES:
                raise ValidationError(
                    f"hull_type[{nm!r}] inválido: {raw!r}. Suportados: {sorted(SUPPORTED_HULL_TYPES)}."
                )
            out.append(raw)
        return out
    if isinstance(hull_type, Sequence) and not isinstance(hull_type, (str, bytes)):
        if len(hull_type) != d_len:
            raise DimensionMismatchError(
                f"hull_type deve ter comprimento {d_len}, recebido {len(hull_type)}."
            )
        out = []
        for idx, item in enumerate(hull_type):
            raw = str(item).strip().upper()
            if raw not in SUPPORTED_HULL_TYPES:
                raise ValidationError(
                    f"hull_type[{idx}] inválido: {raw!r}. Suportados: {sorted(SUPPORTED_HULL_TYPES)}."
                )
            out.append(raw)
        return out
    raise ValidationError(f"Tipo inválido para hull_type: {type(hull_type).__name__}.")


def _evaluate_tpmt_weights_batch(
    pts: np.ndarray,
    axis_grids: Sequence[np.ndarray],
    W_list: Sequence[np.ndarray],
    multi_indices: Sequence[tuple[int, ...]],
) -> np.ndarray:
    """Avalia `H[q, r] = prod_d w_{d, i_{r,d}}(p_d^(q))` via interpolação linear 1D com clamping."""
    n_pts = pts.shape[0]
    d_len = len(axis_grids)
    n_rules = len(multi_indices)

    interp_axes: list[np.ndarray] = []
    for d in range(d_len):
        g_d = axis_grids[d]
        W_d = W_list[d]
        r_d = W_d.shape[1]
        p_clamped = np.clip(pts[:, d], g_d[0], g_d[-1])
        w_eval = np.empty((n_pts, r_d), dtype=np.float64)
        for j in range(r_d):
            w_eval[:, j] = np.interp(p_clamped, g_d, W_d[:, j])
        interp_axes.append(w_eval)

    H = np.ones((n_pts, n_rules), dtype=np.float64)
    for r_idx, midx in enumerate(multi_indices):
        for d in range(d_len):
            H[:, r_idx] *= interp_axes[d][:, midx[d]]
    return H


def _assemble_block_batch(
    parsed_A: list[list[ParsedExpression]],
    parsed_B: list[list[ParsedExpression]],
    parsed_C: list[list[ParsedExpression]],
    parsed_D: list[list[ParsedExpression]],
    parsed_gen: Mapping[str, list[list[ParsedExpression]]],
    env_vec: Mapping[str, np.ndarray],
    n_pts: int,
    *,
    n: int,
    m: int,
    p_out: int,
    nw: int,
    nz: int,
) -> np.ndarray:
    """Avalia de forma vetorizada a matriz empacotada `[A B (Bw); C D (Dyw); (Cz Dzu Dzw)]`."""
    A_b = _eval_symbolic_matrix_batch(parsed_A, env_vec, n_pts)
    B_b = _eval_symbolic_matrix_batch(parsed_B, env_vec, n_pts)
    C_b = _eval_symbolic_matrix_batch(parsed_C, env_vec, n_pts)
    D_b = _eval_symbolic_matrix_batch(parsed_D, env_vec, n_pts)

    top_blocks = [A_b, B_b]
    mid_blocks = [C_b, D_b]
    if nw > 0:
        Bw_b = (
            _eval_symbolic_matrix_batch(parsed_gen["Bw"], env_vec, n_pts)
            if "Bw" in parsed_gen
            else np.zeros((n_pts, n, nw), dtype=np.float64)
        )
        Dyw_b = (
            _eval_symbolic_matrix_batch(parsed_gen["Dyw"], env_vec, n_pts)
            if "Dyw" in parsed_gen
            else np.zeros((n_pts, p_out, nw), dtype=np.float64)
        )
        top_blocks.append(Bw_b)
        mid_blocks.append(Dyw_b)

    row_blocks = [
        np.concatenate(top_blocks, axis=2),
        np.concatenate(mid_blocks, axis=2),
    ]
    if nz > 0:
        Cz_b = (
            _eval_symbolic_matrix_batch(parsed_gen["Cz"], env_vec, n_pts)
            if "Cz" in parsed_gen
            else np.zeros((n_pts, nz, n), dtype=np.float64)
        )
        Dzu_b = (
            _eval_symbolic_matrix_batch(parsed_gen["Dzu"], env_vec, n_pts)
            if "Dzu" in parsed_gen
            else np.zeros((n_pts, nz, m), dtype=np.float64)
        )
        bot_blocks = [Cz_b, Dzu_b]
        if nw > 0:
            Dzw_b = (
                _eval_symbolic_matrix_batch(parsed_gen["Dzw"], env_vec, n_pts)
                if "Dzw" in parsed_gen
                else np.zeros((n_pts, nz, nw), dtype=np.float64)
            )
            bot_blocks.append(Dzw_b)
        row_blocks.append(np.concatenate(bot_blocks, axis=2))

    return np.concatenate(row_blocks, axis=1)


# ---------------------------------------------------------------------------
# 6. Pipeline Completo `derive_ts_tpmt`
# ---------------------------------------------------------------------------


def derive_ts_tpmt(
    state_bounds: Mapping[str, Sequence[float]],
    A_expr: Sequence[Sequence[str | float | int]],
    B_expr: Sequence[Sequence[str | float | int]],
    *,
    C_expr: Sequence[Sequence[str | float | int]] | None = None,
    D_expr: Sequence[Sequence[str | float | int]] | None = None,
    external_bounds: Mapping[str, Sequence[float]] | None = None,
    measured_states: Mapping[str, bool] | Sequence[str] | None = None,
    measured_externals: Mapping[str, bool] | Sequence[str] | None = None,
    generalized_channels: Mapping[str, Sequence[Sequence[str | float | int]]] | None = None,
    grid_points: int | Mapping[str, int] | Sequence[int] = 51,
    decomposition: str = "hosvd",
    svd_tol: float = 1e-6,
    ranks: Mapping[str, int] | Sequence[int] | None = None,
    hull_type: str | Mapping[str, str] | Sequence[str] = "CNO",
    resample_points: int | Mapping[str, int] | Sequence[int] | None = None,
    resample_method: str = "linear",
    hooi_max_iter: int = 50,
    hooi_conv_tol: float = 1e-9,
    sn_tol: float = 1e-6,
    dt: float | None = None,
    state_names: Sequence[str] | None = None,
    input_names: Sequence[str] | None = None,
    output_names: Sequence[str] | None = None,
    units: Mapping[str, Any] | None = None,
    model_id: str | None = None,
    n_val_points: int = 2048,
) -> Result:
    """Deriva um `TSStateSpace` canônico via Transformação do Produto Tensorial (TPMT)."""
    try:
        clean_state_bounds = _normalize_bounds_map(state_bounds, field_name="state_bounds", allow_empty=False)
        clean_ext_bounds = _normalize_bounds_map(external_bounds, field_name="external_bounds", allow_empty=True)
        overlap_vars = set(clean_state_bounds.keys()) & set(clean_ext_bounds.keys())
        if overlap_vars:
            raise ValidationError(
                f"Conflito de nomes entre state_bounds e external_bounds: {sorted(overlap_vars)}."
            )

        all_domain_bounds: dict[str, list[float]] = {**clean_state_bounds, **clean_ext_bounds}
        state_meas = _resolve_measured_flags(list(clean_state_bounds.keys()), measured_states)
        ext_meas = _resolve_measured_flags(list(clean_ext_bounds.keys()), measured_externals)
        var_measured = {**state_meas, **ext_meas}

        decomp = str(decomposition).strip().lower()
        if decomp not in SUPPORTED_DECOMPOSITIONS:
            raise ValidationError(
                f"decomposition inválida: {decomposition!r}. Suportadas: {sorted(SUPPORTED_DECOMPOSITIONS)}."
            )

        # Parse e validação dimensional das matrizes A, B, C, D e canais generalizados
        parsed_A = _parse_symbolic_matrix(A_expr, name="A")
        n = len(parsed_A)
        if len(parsed_A[0]) != n:
            raise DimensionMismatchError(
                f"Matriz simbólica A deve ser quadrada (n x n), recebido ({n}, {len(parsed_A[0])})."
            )
        parsed_B = _parse_symbolic_matrix(B_expr, name="B")
        if len(parsed_B) != n:
            raise DimensionMismatchError(
                f"Matriz simbólica B deve ter {n} linhas para coincidir com A, recebido {len(parsed_B)}."
            )
        m = len(parsed_B[0])

        if C_expr is None:
            C_raw: list[list[str | float | int]] = [
                [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)
            ]
        else:
            C_raw = [list(r) for r in C_expr]
        parsed_C = _parse_symbolic_matrix(C_raw, name="C")
        p_out = len(parsed_C)
        if len(parsed_C[0]) != n:
            raise DimensionMismatchError(
                f"Matriz simbólica C deve ter {n} colunas para coincidir com A, recebido {len(parsed_C[0])}."
            )

        if D_expr is None:
            D_raw: list[list[str | float | int]] = [[0.0 for _ in range(m)] for _ in range(p_out)]
        else:
            D_raw = [list(r) for r in D_expr]
        parsed_D = _parse_symbolic_matrix(D_raw, name="D")
        if len(parsed_D) != p_out or len(parsed_D[0]) != m:
            raise DimensionMismatchError(
                f"Matriz simbólica D deve ter shape ({p_out}, {m}), recebido ({len(parsed_D)}, {len(parsed_D[0])})."
            )

        parsed_gen: dict[str, list[list[ParsedExpression]]] = {}
        nw = 0
        nz = 0
        if generalized_channels is not None:
            if not isinstance(generalized_channels, Mapping):
                raise ValidationError("generalized_channels deve ser um mapeamento de matrizes simbólicas.")
            unknown_ch = set(generalized_channels.keys()) - ALLOWED_GENERALIZED_CHANNELS
            if unknown_ch:
                raise ValidationError(
                    f"Canais generalizados desconhecidos: {sorted(unknown_ch)}. "
                    f"Permitidos: {sorted(ALLOWED_GENERALIZED_CHANNELS)}."
                )
            nw_opt: int | None = None
            nz_opt: int | None = None
            for ch_name, ch_raw in generalized_channels.items():
                pm = _parse_symbolic_matrix(ch_raw, name=ch_name)
                cr, cc = len(pm), len(pm[0])
                if ch_name == "Bw":
                    if cr != n:
                        raise DimensionMismatchError(f"Bw deve ter {n} linhas, recebido {cr}.")
                    nw_opt = cc if nw_opt is None else nw_opt
                    if cc != nw_opt:
                        raise DimensionMismatchError(f"Dimensão nw inconsistente em Bw ({cc} vs {nw_opt}).")
                elif ch_name == "Dyw":
                    if cr != p_out:
                        raise DimensionMismatchError(f"Dyw deve ter {p_out} linhas, recebido {cr}.")
                    nw_opt = cc if nw_opt is None else nw_opt
                    if cc != nw_opt:
                        raise DimensionMismatchError(f"Dimensão nw inconsistente em Dyw ({cc} vs {nw_opt}).")
                elif ch_name == "Cz":
                    if cc != n:
                        raise DimensionMismatchError(f"Cz deve ter {n} colunas, recebido {cc}.")
                    nz_opt = cr if nz_opt is None else nz_opt
                    if cr != nz_opt:
                        raise DimensionMismatchError(f"Dimensão nz inconsistente em Cz ({cr} vs {nz_opt}).")
                elif ch_name == "Dzu":
                    if cc != m:
                        raise DimensionMismatchError(f"Dzu deve ter {m} colunas, recebido {cc}.")
                    nz_opt = cr if nz_opt is None else nz_opt
                    if cr != nz_opt:
                        raise DimensionMismatchError(f"Dimensão nz inconsistente em Dzu ({cr} vs {nz_opt}).")
                elif ch_name == "Dzw":
                    nz_opt = cr if nz_opt is None else nz_opt
                    nw_opt = cc if nw_opt is None else nw_opt
                    if cr != nz_opt or cc != nw_opt:
                        raise DimensionMismatchError(
                            f"Dzw deve ter shape ({nz_opt}, {nw_opt}), recebido ({cr}, {cc})."
                        )
                parsed_gen[ch_name] = pm
            nw = nw_opt or 0
            nz = nz_opt or 0

        # Extração automática das variáveis não-lineares ativas p = [p_1, ..., p_D]
        warnings_list: list[WarningItem] = []
        active_set: set[str] = set()
        for pm in (parsed_A, parsed_B, parsed_C, parsed_D, *parsed_gen.values()):
            for row in pm:
                for pe in row:
                    warnings_list.extend(pe.rewrites)
                    for v in pe.active_variables:
                        active_set.add(v)

        unknown_vars = sorted(v for v in active_set if v not in all_domain_bounds)
        if unknown_vars:
            raise ValidationError(
                message=(
                    f"Expressões matriciais referenciam variáveis sem limites em "
                    f"state_bounds/external_bounds: {unknown_vars}."
                ),
                parameters={"unknown_variables": unknown_vars},
            )

        # Ordem determinística seguindo a declaração em state_bounds seguido de external_bounds
        p_names = [v for v in all_domain_bounds.keys() if v in active_set]
        d_len = len(p_names)
        if d_len == 0:
            raise ValidationError(
                message=(
                    "Nenhuma variável não-linear ativa detectada nas matrizes A, B, C, D: "
                    "o sistema fornecido é LTI constante e não requer TPMT."
                ),
                next_step="Registre diretamente um StateSpace LTI ou inclua termos dependentes de estado/parâmetro.",
            )

        # Validação do envelope Wasm — Dimensão D (Seção 4.5)
        if d_len > MAX_TPMT_DIMS_HARD:
            raise ResourceLimitError(
                message=(
                    f"Número de variáveis não-lineares ativas D={d_len} excede o teto do Worker Wasm "
                    f"(D <= {MAX_TPMT_DIMS_HARD})."
                ),
                parameters={"D": d_len, "max_D": MAX_TPMT_DIMS_HARD, "active_variables": p_names},
                next_step="Reduza variáveis ativas ou exporte script Python/MATLAB offline.",
            )
        if d_len > MAX_TPMT_DIMS_WARN:
            warnings_list.append(
                WarningItem(
                    code="TPMT_HIGH_DIMENSION",
                    message=(
                        f"D={d_len} dimensões não-lineares ativas acima do limite interativo recomendado "
                        f"(D <= {MAX_TPMT_DIMS_WARN})."
                    ),
                    details={"D": d_len, "recommended_max_D": MAX_TPMT_DIMS_WARN},
                )
            )

        # Verifica intervalos não-degenerados para variáveis ativas
        for nm in p_names:
            lo, hi = all_domain_bounds[nm]
            if hi - lo <= 1e-12:
                raise ValidationError(
                    f"Variável ativa {nm!r} possui domínio degenerado [{lo}, {hi}]. "
                    "Substitua-a por uma constante escalar."
                )

        g_sizes = _resolve_per_axis_int(grid_points, p_names, field_name="grid_points", min_value=3)
        hull_types = _resolve_per_axis_hull(hull_type, p_names)
        resolved_ranks = (
            None
            if ranks is None
            else _resolve_per_axis_int(ranks, p_names, field_name="ranks", min_value=1)
        )
        resolved_resample = (
            None
            if resample_points is None
            else _resolve_per_axis_int(resample_points, p_names, field_name="resample_points", min_value=3)
        )

        # Validação do envelope Wasm ANTES de alocar np.empty (Seção 4.5)
        m1 = n + p_out + nz
        m2 = n + m + nw
        total_nodes = int(math.prod(g_sizes))
        total_elements = total_nodes * m1 * m2

        if total_nodes > MAX_TPMT_GRID_NODES_HARD:
            raise ResourceLimitError(
                message=(
                    f"Total de nós da grade ({total_nodes:,}) excede o teto Wasm ({MAX_TPMT_GRID_NODES_HARD:,})."
                ),
                parameters={"total_nodes": total_nodes, "max_nodes": MAX_TPMT_GRID_NODES_HARD, "grid_sizes": g_sizes},
                next_step="Reduza grid_points por eixo ou exporte script Python/MATLAB offline.",
            )
        if total_elements > MAX_TPMT_ELEMENTS_HARD:
            raise ResourceLimitError(
                message=(
                    f"Total de elementos do tensor S^D ({total_elements:,}) excede o teto Wasm "
                    f"({MAX_TPMT_ELEMENTS_HARD:,})."
                ),
                parameters={
                    "total_elements": total_elements,
                    "max_elements": MAX_TPMT_ELEMENTS_HARD,
                    "tensor_shape": [*g_sizes, m1, m2],
                },
                next_step="Reduza grid_points por eixo ou exporte script Python/MATLAB offline.",
            )
        if total_nodes > MAX_TPMT_GRID_NODES_WARN:
            warnings_list.append(
                WarningItem(
                    code="TPMT_LARGE_GRID",
                    message=(
                        f"Total de nós ({total_nodes:,}) acima do recomendado interativo ({MAX_TPMT_GRID_NODES_WARN:,})."
                    ),
                    details={"total_nodes": total_nodes, "recommended_max_nodes": MAX_TPMT_GRID_NODES_WARN},
                )
            )
        if total_elements > MAX_TPMT_ELEMENTS_WARN:
            warnings_list.append(
                WarningItem(
                    code="TPMT_LARGE_TENSOR",
                    message=(
                        f"Total de elementos do tensor ({total_elements:,}) acima do recomendado interativo "
                        f"({MAX_TPMT_ELEMENTS_WARN:,})."
                    ),
                    details={"total_elements": total_elements, "recommended_max_elements": MAX_TPMT_ELEMENTS_WARN},
                )
            )

        # 1. Amostragem vetorizada do tensor S^D de forma (G_1, ..., G_D, M1, M2)
        orig_grids = [
            np.linspace(all_domain_bounds[nm][0], all_domain_bounds[nm][1], g_sizes[d], dtype=np.float64)
            for d, nm in enumerate(p_names)
        ]
        mesh = np.meshgrid(*orig_grids, indexing="ij")
        env_grid = {p_names[d]: mesh[d].ravel() for d in range(d_len)}

        S_batch_grid = _assemble_block_batch(
            parsed_A,
            parsed_B,
            parsed_C,
            parsed_D,
            parsed_gen,
            env_grid,
            total_nodes,
            n=n,
            m=m,
            p_out=p_out,
            nw=nw,
            nz=nz,
        )
        S_tensor = S_batch_grid.reshape(*g_sizes, m1, m2)

        # 2. Decomposição HOSVD ou HOOI (ord_func = 2)
        hooi_meta: dict[str, Any] | None = None
        if decomp == "hosvd":
            hosvd_res = hosvd_sampled_func(S_tensor, tol=svd_tol, ranks=resolved_ranks, ord_func=2)
            core = hosvd_res.core
            U_list_pre = [u.copy() for u in hosvd_res.U_list]
            singular_values = hosvd_res.singular_values
            truncation_bound = hosvd_res.truncation_bound
        else:
            hooi_res = hooi_sampled_func(
                S_tensor,
                ranks=resolved_ranks,
                tol=svd_tol,
                ord_func=2,
                max_iter=hooi_max_iter,
                conv_tol=hooi_conv_tol,
            )
            core = hooi_res.core
            U_list_pre = [u.copy() for u in hooi_res.U_list]
            singular_values = hooi_res.singular_values
            # Cota teórica de referência da HOSVD inicial para comparação
            tail_sq = 0.0
            for d, sv in enumerate(singular_values):
                r_d = U_list_pre[d].shape[1]
                if r_d < sv.size:
                    tail_sq += float(np.sum(sv[r_d:] ** 2))
            truncation_bound = math.sqrt(max(0.0, tail_sq))
            hooi_meta = {
                "n_iter": hooi_res.n_iter,
                "converged": hooi_res.converged,
                "error_history": hooi_res.error_history,
            }

        # 3. Reamostragem 1D opcional pós-SVD + Transformações de Fecho Convexo por eixo
        axis_grids: list[np.ndarray] = []
        W_list: list[np.ndarray] = []
        hull_diagnostics: list[dict[str, Any]] = []

        for d in range(d_len):
            g_d = orig_grids[d]
            U_d = U_list_pre[d]
            if resolved_resample is not None:
                g_d, U_d = resample_basis_1d(g_d, U_d, resolved_resample[d], method=resample_method)
            axis_grids.append(g_d)

            W_sn, _, info_sn = sn_nn_matrix(U_d, core=core, mode=d, sn_tol=sn_tol)
            core = info_sn["core"]
            rank_before = int(info_sn["rank_before"])
            rank_augmented = bool(info_sn["rank_augmented"])
            target_hull = hull_types[d]

            if target_hull == "SN-NN":
                W_final = W_sn
                diag_d = {
                    "axis": p_names[d],
                    "hull_type": "SN-NN",
                    "rank_before": rank_before,
                    "rank_after": int(W_final.shape[1]),
                    "rank_augmented": rank_augmented,
                    "min_weight": float(info_sn["min_weight"]),
                    "max_sum_deviation": float(info_sn["max_sum_deviation"]),
                    "cond_T": float(info_sn["cond_T"]),
                    "log_abs_det_T": 0.0,
                    "fallback_used": False,
                    "nn_violated": False,
                }
            elif target_hull == "RNO-INO":
                W_final, _, info_h = rno_ino_matrix(W_sn, core=core, mode=d)
                core = info_h["core"]
                diag_d = {
                    "axis": p_names[d],
                    "hull_type": "RNO-INO",
                    "rank_before": rank_before,
                    "rank_after": int(W_final.shape[1]),
                    "rank_augmented": rank_augmented,
                    "min_weight": float(info_h["min_weight"]),
                    "max_sum_deviation": float(info_h["max_sum_deviation"]),
                    "cond_T": float(info_h["cond_T"]),
                    "log_abs_det_T": float(info_h["log_abs_det_T"]),
                    "fallback_used": bool(info_h["fallback_used"]),
                    "nn_violated": False,
                }
            elif target_hull == "CNO":
                W_final, _, info_h = cno_matrix(W_sn, core=core, mode=d)
                core = info_h["core"]
                diag_d = {
                    "axis": p_names[d],
                    "hull_type": "CNO",
                    "rank_before": rank_before,
                    "rank_after": int(W_final.shape[1]),
                    "rank_augmented": rank_augmented,
                    "min_weight": float(info_h["min_weight"]),
                    "max_sum_deviation": float(info_h["max_sum_deviation"]),
                    "cond_T": float(info_h["cond_T"]),
                    "log_abs_det_T": float(info_h["log_abs_det_T"]),
                    "fallback_used": bool(info_h["fallback_used"]),
                    "nn_violated": False,
                }
            else:  # MGK
                W_final, _, info_h = mgk_matrix(W_sn, core=core, mode=d)
                core = info_h["core"]
                nn_viol = bool(info_h["nn_violated"])
                if nn_viol:
                    warnings_list.append(
                        WarningItem(
                            code="NN_VIOLATED",
                            message=(
                                f"Transformação MGK no eixo {p_names[d]!r} violou não-negatividade "
                                f"(min(W)={info_h['min_weight']:.3e} < -1e-9). Recomenda-se RNO-INO ou CNO."
                            ),
                            details={"axis": p_names[d], "min_weight": float(info_h["min_weight"])},
                        )
                    )
                diag_d = {
                    "axis": p_names[d],
                    "hull_type": "MGK",
                    "rank_before": rank_before,
                    "rank_after": int(W_final.shape[1]),
                    "rank_augmented": rank_augmented,
                    "min_weight": float(info_h["min_weight"]),
                    "max_sum_deviation": float(info_h["max_sum_deviation"]),
                    "cond_T": float(info_h["cond_T"]),
                    "log_abs_det_T": float(info_h["log_abs_det_T"]),
                    "fallback_used": False,
                    "nn_violated": nn_viol,
                }

            W_list.append(W_final)
            hull_diagnostics.append(diag_d)

        # 4. Validação do número final de regras N_r = prod(R'_d)
        axis_ranks = [int(W.shape[1]) for W in W_list]
        n_rules = int(math.prod(axis_ranks))
        if n_rules > MAX_TPMT_RULES_HARD:
            raise ResourceLimitError(
                message=(
                    f"Número resultante de regras N_r={n_rules} excede o teto Wasm ({MAX_TPMT_RULES_HARD})."
                ),
                parameters={"n_rules": n_rules, "max_rules": MAX_TPMT_RULES_HARD, "axis_ranks": axis_ranks},
                next_step="Reduza os postos por eixo (ranks) ou aumente svd_tol.",
            )
        if n_rules > MAX_TPMT_RULES_WARN:
            warnings_list.append(
                WarningItem(
                    code="TPMT_HIGH_RULE_COUNT",
                    message=(
                        f"Modelo TPMT gerou N_r={n_rules} regras (acima do recomendado interativo "
                        f"N_r <= {MAX_TPMT_RULES_WARN}); síntese LMI PDC terá custo O(N_r^2)."
                    ),
                    details={"n_rules": n_rules, "recommended_max_rules": MAX_TPMT_RULES_WARN},
                )
            )

        # 5. Extração dos N_r vértices em ordem lexicográfica
        multi_indices = list(itertools.product(*[range(r_d) for r_d in axis_ranks]))
        vertices_list: list[dict[str, Any]] = []
        functions_spec: list[dict[str, Any]] = []
        vertices_S = np.empty((n_rules, m1, m2), dtype=np.float64)
        gen_vertices: list[dict[str, Any]] = []

        for r_idx, midx in enumerate(multi_indices):
            S_r = np.asarray(core[midx], dtype=np.float64)
            vertices_S[r_idx] = S_r
            A_r = S_r[:n, :n]
            B_r = S_r[:n, n : n + m]
            C_r = S_r[n : n + p_out, :n]
            D_r = S_r[n : n + p_out, n : n + m]

            vid = f"rule_{r_idx + 1}"
            vertices_list.append(
                {
                    "vertex_id": vid,
                    "A": A_r,
                    "B": B_r,
                    "C": C_r,
                    "D": D_r,
                }
            )
            if parsed_gen:
                gv: dict[str, Any] = {"vertex_id": vid}
                if "Bw" in parsed_gen:
                    gv["Bw"] = S_r[:n, n + m : n + m + nw].tolist()
                if "Dyw" in parsed_gen:
                    gv["Dyw"] = S_r[n : n + p_out, n + m : n + m + nw].tolist()
                if "Cz" in parsed_gen:
                    gv["Cz"] = S_r[n + p_out : n + p_out + nz, :n].tolist()
                if "Dzu" in parsed_gen:
                    gv["Dzu"] = S_r[n + p_out : n + p_out + nz, n : n + m].tolist()
                if "Dzw" in parsed_gen:
                    gv["Dzw"] = S_r[n + p_out : n + p_out + nz, n + m : n + m + nw].tolist()
                gen_vertices.append(gv)

            expr_str = " * ".join(
                f"w_{d + 1}_{midx[d] + 1}({p_names[d]})" for d in range(d_len)
            )
            functions_spec.append(
                {
                    "id": f"h_{r_idx + 1}",
                    "vertex_id": vid,
                    "axis_basis_indices": [int(v) for v in midx],
                    "expression": expr_str,
                }
            )

        # 6. Auditoria independente NA GRADE e FORA DA GRADE (ModelFidelityCertificate)
        # 6a. Erro nos nós da grade original
        W_on_orig_grid: list[np.ndarray] = []
        for d in range(d_len):
            if resolved_resample is None:
                W_on_orig_grid.append(W_list[d])
            else:
                W_interp = np.empty((orig_grids[d].size, axis_ranks[d]), dtype=np.float64)
                for j in range(axis_ranks[d]):
                    W_interp[:, j] = np.interp(orig_grids[d], axis_grids[d], W_list[d][:, j])
                W_on_orig_grid.append(W_interp)

        S_grid_hat = reconstruct_tensor(core, W_on_orig_grid)
        grid_diff = (S_tensor - S_grid_hat).reshape(total_nodes, -1)
        grid_err_frob = np.linalg.norm(grid_diff, axis=1)
        grid_true_frob = np.linalg.norm(S_tensor.reshape(total_nodes, -1), axis=1)
        grid_max_abs_error = float(np.max(grid_err_frob))
        grid_rel_l2_error = float(
            math.sqrt(float(np.sum(grid_err_frob**2)))
            / (math.sqrt(float(np.sum(grid_true_frob**2))) + 1e-15)
        )

        # 6b. Erro fora da grade (Sobol + pontos médios de células)
        lo_act = np.array([all_domain_bounds[nm][0] for nm in p_names], dtype=np.float64)
        hi_act = np.array([all_domain_bounds[nm][1] for nm in p_names], dtype=np.float64)

        val_blocks: list[np.ndarray] = []
        # Pontos médios determinísticos das células da grade original (até 512)
        mid_axes = [0.5 * (g[:-1] + g[1:]) for g in orig_grids]
        n_mids_total = int(math.prod(m_ax.size for m_ax in mid_axes))
        if n_mids_total <= 512:
            m_mesh = np.meshgrid(*mid_axes, indexing="ij")
            val_blocks.append(np.column_stack([mm.ravel() for mm in m_mesh]))
        else:
            # Amostragem determinística uniforme de índices de células
            rng_idx = np.linspace(0, n_mids_total - 1, 512, dtype=np.int64)
            mid_shapes = tuple(m_ax.size for m_ax in mid_axes)
            unraveled = np.unravel_index(rng_idx, mid_shapes)
            val_blocks.append(np.column_stack([mid_axes[d][unraveled[d]] for d in range(d_len)]))

        n_mids_added = int(val_blocks[0].shape[0])
        n_sobol = max(64, int(n_val_points) - n_mids_added)
        m_pow = max(6, int(math.ceil(math.log2(n_sobol))))
        sampler = qmc.Sobol(d=d_len, scramble=True, seed=20261125)
        unit_pts = sampler.random_base2(m=m_pow)[:n_sobol]
        val_blocks.append(lo_act + unit_pts * (hi_act - lo_act))

        val_pts = np.vstack(val_blocks)
        n_val_actual = int(val_pts.shape[0])
        env_val = {p_names[d]: val_pts[:, d] for d in range(d_len)}

        S_val_true = _assemble_block_batch(
            parsed_A,
            parsed_B,
            parsed_C,
            parsed_D,
            parsed_gen,
            env_val,
            n_val_actual,
            n=n,
            m=m,
            p_out=p_out,
            nw=nw,
            nz=nz,
        )
        H_val = _evaluate_tpmt_weights_batch(val_pts, axis_grids, W_list, multi_indices)
        S_val_hat = np.tensordot(H_val, vertices_S, axes=([1], [0]))

        val_diff = (S_val_true - S_val_hat).reshape(n_val_actual, -1)
        val_err_frob = np.linalg.norm(val_diff, axis=1)
        val_true_frob = np.linalg.norm(S_val_true.reshape(n_val_actual, -1), axis=1)
        val_max_abs_error = float(np.max(val_err_frob))
        val_rel_l2_error = float(
            math.sqrt(float(np.sum(val_err_frob**2)))
            / (math.sqrt(float(np.sum(val_true_frob**2))) + 1e-15)
        )
        min_weight = float(np.min(H_val))
        max_sum_deviation = float(np.max(np.abs(np.sum(H_val, axis=1) - 1.0)))

        # Classificação honesta de verificação (CL-TS-MOD-DIR-001 Seção 5.1)
        exact_on_grid = (
            grid_rel_l2_error <= 1e-9
            and val_rel_l2_error <= 1e-4
            and min_weight >= -1e-9
            and max_sum_deviation <= 1e-9
        )
        verification_badge = "EXACT_ON_GRID_TPMT" if exact_on_grid else "APPROXIMATE_REDUCED_TPMT"
        verification_tier = "numeric_verified" if exact_on_grid else "approximate"

        fidelity_cert: dict[str, Any] = {
            "n_grid_points": total_nodes,
            "n_validation_points": n_val_actual,
            "grid_max_abs_error": grid_max_abs_error,
            "grid_rel_l2_error": grid_rel_l2_error,
            "val_max_abs_error": val_max_abs_error,
            "val_rel_l2_error": val_rel_l2_error,
            "min_weight": min_weight,
            "max_sum_deviation": max_sum_deviation,
            "truncation_bound": float(truncation_bound),
            "verification_badge": verification_badge,
            "verification_tier": verification_tier,
            "verified": exact_on_grid,
        }

        # 7. Construção do TSStateSpace 100% conforme ts_state_space.schema.json
        measured_premises = [v for v in p_names if var_measured[v]]
        unmeasured_premises = [v for v in p_names if not var_measured[v]]
        if unmeasured_premises:
            inferred_kind = "ts_partially_observed"
            premise_availability = {
                "mode": "partially_observed",
                "measured_premises": measured_premises,
                "unmeasured_premises": unmeasured_premises,
                "estimator_required_for_pdc": True,
            }
        else:
            inferred_kind = "ts_measured"
            premise_availability = {
                "mode": "all_measured",
                "measured_premises": measured_premises,
                "unmeasured_premises": [],
                "estimator_required_for_pdc": False,
            }

        tpmt_axes_spec = [
            {
                "axis_index": d + 1,
                "variable": p_names[d],
                "expression": p_names[d],
                "bounds": [float(all_domain_bounds[p_names[d]][0]), float(all_domain_bounds[p_names[d]][1])],
                "hull_type": hull_types[d],
                "rank": int(axis_ranks[d]),
                "grid": [float(v) for v in axis_grids[d].tolist()],
                "weights_table": [[float(v) for v in row] for row in W_list[d].tolist()],
            }
            for d in range(d_len)
        ]

        membership_spec: dict[str, Any] = {
            "version": "1.0.0",
            "representation_kind": "tpmt_interpolated",
            "premise_variables": list(p_names),
            "sum_to_one_domain": True,
            "tpmt_axes": tpmt_axes_spec,
            "functions": functions_spec,
        }

        domain_payload: dict[str, Any] = {
            "bounds": {**clean_state_bounds, **clean_ext_bounds},
            "state_bounds": clean_state_bounds,
            "external_bounds": clean_ext_bounds,
            "active_premise_bounds": {v: all_domain_bounds[v] for v in p_names},
        }

        resolved_state_names = (
            list(state_names)
            if state_names is not None
            else (list(clean_state_bounds.keys()) if len(clean_state_bounds) == n else None)
        )

        provenance_payload: dict[str, Any] = {
            "source": "control_lab.fuzzy.derive_ts_tpmt",
            "ts_derivation": {
                "method": "tpmt",
                "decomposition": decomp,
                "svd_tol": float(svd_tol),
                "hull_types": list(hull_types),
                "active_variables": list(p_names),
                "grid_points": list(g_sizes),
                "axis_ranks": list(axis_ranks),
                "num_rules": n_rules,
                "resample_points": list(resolved_resample) if resolved_resample is not None else None,
                "resample_method": resample_method if resolved_resample is not None else None,
                "state_bounds": clean_state_bounds,
                "external_bounds": clean_ext_bounds,
                "A_expr": [[pe.source for pe in row] for row in parsed_A],
                "B_expr": [[pe.source for pe in row] for row in parsed_B],
                "C_expr": [[pe.source for pe in row] for row in parsed_C],
                "D_expr": [[pe.source for pe in row] for row in parsed_D],
                "singular_values": [[float(v) for v in sv.tolist()] for sv in singular_values],
                "truncation_bound": float(truncation_bound),
                "hull_diagnostics": hull_diagnostics,
                "fidelity_certificate": fidelity_cert,
            },
        }
        if hooi_meta is not None:
            provenance_payload["ts_derivation"]["hooi"] = hooi_meta
        if parsed_gen:
            provenance_payload["generalized_channels"] = {
                "channels": sorted(parsed_gen.keys()),
                "expressions": {
                    ch_name: [[pe.source for pe in row] for row in pm]
                    for ch_name, pm in parsed_gen.items()
                },
                "vertices": gen_vertices,
            }

        ts_ss = TSStateSpace(
            vertices=vertices_list,
            kind=inferred_kind,
            dt=dt,
            membership_spec=membership_spec,
            premise_availability=premise_availability,
            domain=domain_payload,
            id=model_id,
            state_names=resolved_state_names,
            input_names=input_names,
            output_names=output_names,
            units=units,
            provenance=provenance_payload,
        )

        status = "warning" if warnings_list else "success"
        return Result(
            status=status,
            data={
                "ts_state_space": ts_ss.to_dict(),
                "model_id": ts_ss.id,
                "kind": ts_ss.kind,
                "num_rules": n_rules,
                "active_variables": list(p_names),
                "singular_values": [[float(v) for v in sv.tolist()] for sv in singular_values],
                "truncation_bound": float(truncation_bound),
                "bases_pre_transform": [
                    [[float(v) for v in row] for row in U.tolist()] for U in U_list_pre
                ],
                "bases_post_transform": [
                    [[float(v) for v in row] for row in W.tolist()] for W in W_list
                ],
                "axis_grids": [[float(v) for v in g.tolist()] for g in axis_grids],
                "hull_diagnostics": hull_diagnostics,
                "fidelity_certificate": fidelity_cert,
                "hooi": hooi_meta,
            },
            assumptions={
                "method": "tpmt",
                "decomposition": decomp,
                "convex_sum_interpolated_everywhere": True,
                "zero_linalg_inv": True,
            },
            diagnostics={
                "D_active": d_len,
                "grid_sizes": g_sizes,
                "axis_ranks": axis_ranks,
                "num_rules": n_rules,
                "grid_max_abs_error": grid_max_abs_error,
                "grid_rel_l2_error": grid_rel_l2_error,
                "val_max_abs_error": val_max_abs_error,
                "val_rel_l2_error": val_rel_l2_error,
                "min_weight": min_weight,
                "max_sum_deviation": max_sum_deviation,
                "verification_badge": verification_badge,
                "verification_tier": verification_tier,
            },
            provenance=build_provenance("control_lab.fuzzy.derive_ts_tpmt", model_revision=ts_ss.revision),
            warnings=tuple(warnings_list),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={"method": "tpmt"},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.derive_ts_tpmt"),
            warnings=(),
            error=exc.to_typed_error(),
        )
