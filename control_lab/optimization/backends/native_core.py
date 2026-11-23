"""Native NumPy/SciPy NT/Mehrotra primal-dual kernel promoted under ADR-010.

Canonical primal/dual signs and certificates are checked by the separate verifier.
The educational API delegates to this same numerical kernel.

Algorithmic enhancements incorporated for scalable control LMIs:
- Sparsity-exploiting Nesterov-Todd congruence, vectorized Schur Complement Matrix
  (SCM) assembly, and regularized Cholesky factorization (Fujisawa et al., IEEE IPDPS
  2014, doi:10.1109/IPDPS.2014.121).
- Aggregate-sparsity connected-component & chordal block decomposition with exact dual
  reassembly for decoupled/block-diagonal PSD constraints (Garstka, Cannon & Goulart,
  IFAC 2020, doi:10.1016/j.ifacol.2020.12.1255; Goulart & Chen, 2024, arXiv:2405.12762).
- Multi-sweep clipped Ruiz data equilibration (up to 5 sweeps, factors clipped to
  [1e-4, 1e4]) with exact primal and dual unscaling so the independent verifier audits
  the original unscaled problem (Goulart & Chen, 2024, arXiv:2405.12762, §2.4 & §2.6;
  Yurtsever, Tropp, Fercoq, Udell, Cevher, SIAM J. Matrix Anal. Appl. 2021, §7.1.1).
- Interior-point warm-start support (`warm_start_x`) allowing Phase 1 to be bypassed
  when a strictly feasible interior point is supplied (Ding et al., arXiv:2312.11801,
  SpecBM).
"""
from __future__ import annotations
import contextvars
from dataclasses import dataclass, field
import math
import time
from typing import Any, Callable, Mapping, Sequence
import numpy as np
import scipy.linalg
import scipy.sparse
from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import ValidationError, WarningItem
from ..modeling.canonical import CanonicalSDPProblem

_ACTIVE_PROGRESS_CALLBACK: contextvars.ContextVar[Callable[[dict[str, Any]], Any] | None] = (
    contextvars.ContextVar("_ACTIVE_PROGRESS_CALLBACK", default=None)
)


def set_progress_callback(cb: Callable[[dict[str, Any]], Any] | None) -> None:
    """Registra callback de progresso por iteração no contexto atual."""
    _ACTIVE_PROGRESS_CALLBACK.set(cb)


def get_progress_callback() -> Callable[[dict[str, Any]], Any] | None:
    """Retorna o callback de progresso ativo no contexto atual."""
    return _ACTIVE_PROGRESS_CALLBACK.get()


def clear_progress_callback() -> None:
    """Remove o callback de progresso ativo no contexto atual."""
    _ACTIVE_PROGRESS_CALLBACK.set(None)

@dataclass(frozen=True)
class IterationRecord:
    """Registro didático de uma iteração do caminho central primal-dual."""

    iteration: int
    phase: str
    mu: float
    primal_obj: float
    dual_obj: float
    duality_gap: float
    dual_residual_rel: float
    eq_residual_rel: float
    min_eig_primal: float
    min_eig_dual: float
    alpha_primal: float
    alpha_dual: float
    kkt_condition_number: float
    sigma: float
    step_norm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": int(self.iteration),
            "phase": str(self.phase),
            "mu": float(self.mu),
            "primal_obj": float(self.primal_obj),
            "dual_obj": float(self.dual_obj),
            "duality_gap": float(self.duality_gap),
            "dual_residual_rel": float(self.dual_residual_rel),
            "eq_residual_rel": float(self.eq_residual_rel),
            "min_eig_primal": float(self.min_eig_primal),
            "min_eig_dual": float(self.min_eig_dual),
            "alpha_primal": float(self.alpha_primal),
            "alpha_dual": float(self.alpha_dual),
            "kkt_condition_number": float(self.kkt_condition_number),
            "sigma": float(self.sigma),
            "step_norm": float(self.step_norm),
        }


@dataclass(frozen=True)
class NativeSolverConfig:
    """Parâmetros numéricos configuráveis do solver primal-dual educacional."""

    max_iter: int = 80
    phase1_max_iter: int = 60
    tol_gap: float = 1e-12
    tol_feas: float = 1e-11
    tol_psd: float = 1e-9
    strict_margin: float = 1e-3
    step_fraction: float = 0.98
    sigma_min: float = 1e-4
    sigma_max: float = 0.90
    unbounded_norm_threshold: float = 1e7
    record_history: bool = True
    warm_start_x: tuple[float, ...] | None = None

    @classmethod
    def from_options(cls, options: Mapping[str, Any] | None = None) -> NativeSolverConfig:
        if options is None:
            return cls()
        if not isinstance(options, Mapping):
            raise ValidationError("options deve ser um dicionário Mapping.")
        allowed = {
            "max_iter",
            "phase1_max_iter",
            "tol_gap",
            "tol_feas",
            "tol_psd",
            "strict_margin",
            "step_fraction",
            "sigma_min",
            "sigma_max",
            "unbounded_norm_threshold",
            "record_history",
            "warm_start_x",
        }
        kwargs: dict[str, Any] = {}
        for k, v in options.items():
            if k == "progress_callback":
                continue
            if k not in allowed:
                raise ValidationError(f"Opção desconhecida para solver SDP educacional: {k!r}.")
            if k == "warm_start_x" and v is not None:
                if isinstance(v, (str, bytes, bool)):
                    raise ValidationError("warm_start_x deve ser um vetor numérico 1D finito.")
                try:
                    ws_arr = np.asarray(v, dtype=np.float64)
                except (TypeError, ValueError) as exc:
                    raise ValidationError("warm_start_x deve ser um vetor numérico 1D finito.") from exc
                if ws_arr.ndim != 1 or not np.all(np.isfinite(ws_arr)):
                    raise ValidationError("warm_start_x deve ser um vetor numérico 1D finito.")
                kwargs[k] = tuple(float(val) for val in ws_arr)
            else:
                kwargs[k] = v
        cfg = cls(**kwargs)
        for key in ("max_iter", "phase1_max_iter"):
            value = getattr(cfg, key)
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
                raise ValidationError(f"{key} must be a positive integer.")
        for key in ("tol_gap", "tol_feas", "tol_psd", "strict_margin", "step_fraction", "sigma_min", "sigma_max", "unbounded_norm_threshold"):
            value = getattr(cfg, key)
            if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)) or not math.isfinite(value) or value <= 0:
                raise ValidationError(f"{key} must be a finite positive scalar.")
        if not 0 < cfg.sigma_min <= cfg.sigma_max < 1:
            raise ValidationError("Require 0 < sigma_min <= sigma_max < 1.")
        if not isinstance(cfg.record_history, bool):
            raise ValidationError("record_history must be boolean.")
        if cfg.max_iter < 1 or cfg.phase1_max_iter < 1:
            raise ValidationError("max_iter e phase1_max_iter devem ser >= 1.")
        if cfg.tol_gap <= 0.0 or cfg.tol_feas <= 0.0 or cfg.tol_psd <= 0.0:
            raise ValidationError("Tolerâncias tol_gap, tol_feas e tol_psd devem ser > 0.")
        if not (0.1 <= cfg.step_fraction < 1.0):
            raise ValidationError("step_fraction deve estar em [0.1, 1.0).")
        return cfg


@dataclass(frozen=True)
class _InternalConeBlock:
    """Bloco simétrico interno (bloco PSD original ou desigualdade escalar 1x1).

    Pré-computa metadados esparsos `(rows, cols, vals)` para matrizes `F_k` com baixa
    densidade (Fujisawa et al., IEEE IPDPS 2014) e colunas vetorizadas `_F_cols` para
    avaliações BLAS sem laços Python.
    """

    name: str
    dim: int
    F0: np.ndarray
    F_terms: dict[int, np.ndarray]
    is_ineq_slack: bool = False
    ineq_index: int | None = None
    _active_keys: np.ndarray = field(init=False, repr=False, compare=False)
    _F_cols: np.ndarray = field(init=False, repr=False, compare=False)
    _f_norm_sum: float = field(init=False, repr=False, compare=False)
    _sparse_terms: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        keys = sorted(self.F_terms.keys())
        active_keys = np.asarray(keys, dtype=np.intp)
        n2 = self.dim * self.dim
        if keys:
            f_cols = np.empty((n2, len(keys)), dtype=np.float64)
            f_norm_sum = 0.0
            sparse_terms: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
            # Sparse congruence G^{-T} F_k G^{-1} via G_invT[rows].T @ (vals[:,None]*G_invT[cols])
            # costs nnz * n^2 flops vs 2 * n^3 dense; strictly faster when nnz <= min(0.25*n^2, n).
            nnz_limit = min(int(0.25 * n2), self.dim) if self.dim >= 4 else 0
            for idx, j in enumerate(keys):
                fj = self.F_terms[j]
                f_cols[:, idx] = fj.ravel()
                f_norm_sum += float(np.linalg.norm(fj, "fro"))
                if nnz_limit > 0:
                    rows, cols = np.nonzero(np.abs(fj) > 0.0)
                    if 0 < rows.size <= nnz_limit:
                        sparse_terms[j] = (rows, cols, fj[rows, cols])
        else:
            f_cols = np.zeros((n2, 0), dtype=np.float64)
            f_norm_sum = 0.0
            sparse_terms = {}
        object.__setattr__(self, "_active_keys", active_keys)
        object.__setattr__(self, "_F_cols", f_cols)
        object.__setattr__(self, "_f_norm_sum", f_norm_sum)
        object.__setattr__(self, "_sparse_terms", sparse_terms)

    def evaluate(self, z: np.ndarray) -> np.ndarray:
        if self._active_keys.size == 0:
            return 0.5 * (self.F0 + self.F0.T)
        lin = (self._F_cols @ z[self._active_keys]).reshape((self.dim, self.dim))
        res = self.F0 + lin
        return 0.5 * (res + res.T)

    def evaluate_linear(self, dz: np.ndarray) -> np.ndarray:
        if self._active_keys.size == 0:
            return np.zeros((self.dim, self.dim), dtype=np.float64)
        res = (self._F_cols @ dz[self._active_keys]).reshape((self.dim, self.dim))
        return 0.5 * (res + res.T)

    def evaluate_into(self, z: np.ndarray, out: np.ndarray, tmp: np.ndarray) -> np.ndarray:
        """Avalia F0 + sum_k z_k F_k simetrizada em `out` reutilizando buffer `tmp` (out is not tmp)."""
        if self._active_keys.size == 0:
            return _sym_into(self.F0, out)
        n_act = self._active_keys.size
        if n_act == z.shape[0] and int(self._active_keys[0]) == 0 and int(self._active_keys[-1]) == n_act - 1:
            z_act = z
        else:
            z_act = z[self._active_keys]
        np.matmul(self._F_cols, z_act, out=tmp.ravel())
        tmp += self.F0
        return _sym_into(tmp, out)


# ---------------------------------------------------------------------------
# Utilitários de Álgebra Linear Numérica (Zero uso de np.linalg.inv!)
# ---------------------------------------------------------------------------


def _sym(M: np.ndarray) -> np.ndarray:
    return 0.5 * (M + M.T)


def _sym_into(src: np.ndarray, out: np.ndarray) -> np.ndarray:
    """Simetriza `src` no buffer distinto `out` (`src is not out`) sem alocar temporários."""
    np.add(src, src.T, out=out)
    out *= 0.5
    return out


def _min_eig_sym(M: np.ndarray) -> float:
    """Menor autovalor de matriz simétrica (caminho escalar O(1) para blocos 1x1)."""
    if M.shape[0] == 1:
        return float(M[0, 0])
    return float(np.min(np.linalg.eigvalsh(M)))


def _safe_cholesky(M: np.ndarray) -> tuple[np.ndarray, bool] | None:
    """Retorna fatoração de Cholesky (L, True) se M for estritamente SPD, ou None."""
    Ms = _sym(M)
    if not np.all(np.isfinite(Ms)):
        return None
    try:
        return scipy.linalg.cho_factor(Ms, lower=True, check_finite=True)
    except np.linalg.LinAlgError:
        return None


def _safe_cholesky_buf(M_sym: np.ndarray, work: np.ndarray) -> tuple[np.ndarray, bool] | None:
    """Fatoração de Cholesky in-place sobre buffer Fortran pré-alocado `work`."""
    if not np.all(np.isfinite(M_sym)):
        return None
    np.copyto(work, M_sym)
    try:
        return scipy.linalg.cho_factor(work, lower=True, overwrite_a=True, check_finite=False)
    except np.linalg.LinAlgError:
        return None


def _cho_solve_mat(cho_fac: tuple[np.ndarray, bool], B: np.ndarray) -> np.ndarray:
    """Resolve M X = B usando fatoração de Cholesky pré-calculada (sem linalg.inv)."""
    return scipy.linalg.cho_solve(cho_fac, B, check_finite=True)


def _max_step_to_psd_boundary(cho_M: tuple[np.ndarray, bool], dM: np.ndarray) -> float:
    """Calcula o maior passo alpha_max > 0 tal que M + alpha * dM >= 0.

    Usa a transformação congruente L^{-1} dM L^{-T} via `scipy.linalg.solve_triangular`
    (sem jamais inverter L explicitamente) e autovalores simétricos `eigvalsh`.
    """
    L, lower = cho_M
    dM_sym = _sym(dM)
    if not np.all(np.isfinite(dM_sym)):
        return 0.0
    if float(np.linalg.norm(dM_sym, "fro")) <= 1e-16:
        return float("inf")

    W = scipy.linalg.solve_triangular(L, dM_sym, lower=lower, check_finite=True)
    Y = scipy.linalg.solve_triangular(L, W.T, lower=lower, check_finite=True)
    congruent = _sym(Y)
    min_eig = float(np.min(np.linalg.eigvalsh(congruent)))
    if min_eig >= -1e-15:
        return float("inf")
    return float(-1.0 / min_eig)


@dataclass(frozen=True)
class _FactoredSymmetricSystem:
    """Fatoração em cache do sistema de Schur simétrico pré-condicionado por Jacobi."""

    n: int
    H_scaled: np.ndarray
    inv_d: np.ndarray
    cho: tuple[np.ndarray, bool] | None
    cond: float
    regularized: bool


def _factor_symmetric_system(
    H: np.ndarray,
    *,
    H_scaled_buf: np.ndarray | None = None,
    H_work_buf: np.ndarray | None = None,
    inv_d_buf: np.ndarray | None = None,
) -> _FactoredSymmetricSystem:
    """Fatora H uma única vez por iteração com Jacobi + Cholesky regularizado (Fujisawa et al., IPDPS 2014).

    Estima o condicionamento em O(m) pela razão dos elementos diagonais do fator de Cholesky
    `(max(diag(L)) / max(min(diag(L)), 1e-15)) ** 2`, evitando SVD O(m^3) a cada iteração.
    Suporta buffers pré-alocados (`H_scaled_buf`, `H_work_buf`, `inv_d_buf`) para execução in-place.
    """
    n = int(H.shape[0])
    if n == 0:
        return _FactoredSymmetricSystem(
            n=0,
            H_scaled=np.zeros((0, 0), dtype=np.float64),
            inv_d=np.zeros((0,), dtype=np.float64),
            cho=None,
            cond=1.0,
            regularized=False,
        )

    H_scaled = H_scaled_buf if H_scaled_buf is not None else np.empty((n, n), dtype=np.float64)
    H_work = H_work_buf if H_work_buf is not None else np.empty((n, n), dtype=np.float64, order="F")
    inv_d = inv_d_buf if inv_d_buf is not None else np.empty((n,), dtype=np.float64)

    # Escalonamento simétrico de Jacobi D^{-1} H D^{-1} in-place sobre H_scaled
    _sym_into(H, H_scaled)
    np.abs(np.diag(H_scaled), out=inv_d)
    np.maximum(inv_d, 1e-30, out=inv_d)
    np.sqrt(inv_d, out=inv_d)
    np.reciprocal(inv_d, out=inv_d)
    H_scaled *= inv_d[:, None]
    H_scaled *= inv_d[None, :]
    _sym_into(H_scaled, H_work)
    np.copyto(H_scaled, H_work)

    def _cond_from_cho(cho_fac: tuple[np.ndarray, bool]) -> float:
        diag_l = np.abs(np.diag(cho_fac[0]))
        if diag_l.size == 0:
            return 1.0
        l_max = float(np.max(diag_l))
        l_min = float(np.min(diag_l))
        if l_max <= 0.0:
            return 1e16
        ratio = l_max / max(l_min, 1e-15)
        return float(min(1e16, ratio * ratio))

    finite_ok = bool(np.all(np.isfinite(H_scaled)))
    if finite_ok:
        try:
            cho: tuple[np.ndarray, bool] | None = scipy.linalg.cho_factor(
                H_work, lower=True, overwrite_a=True, check_finite=False
            )
        except np.linalg.LinAlgError:
            cho = None
        if cho is not None:
            return _FactoredSymmetricSystem(
                n=n,
                H_scaled=H_scaled,
                inv_d=inv_d,
                cho=cho,
                cond=_cond_from_cho(cho),
                regularized=False,
            )

        # Regularização diagonal adaptativa no espaço escalonado sem alocar eye(n)
        h_scale = max(1.0, float(np.max(np.abs(H_scaled))))
        diag_idx = np.arange(n, dtype=np.intp)
        for reg_exp in (1e-13, 1e-11, 1e-9, 1e-7):
            np.copyto(H_work, H_scaled)
            H_work[diag_idx, diag_idx] += reg_exp * h_scale
            try:
                cho_reg = scipy.linalg.cho_factor(
                    H_work, lower=True, overwrite_a=True, check_finite=False
                )
            except np.linalg.LinAlgError:
                cho_reg = None
            if cho_reg is not None:
                return _FactoredSymmetricSystem(
                    n=n,
                    H_scaled=H_scaled,
                    inv_d=inv_d,
                    cho=cho_reg,
                    cond=_cond_from_cho(cho_reg),
                    regularized=True,
                )

    return _FactoredSymmetricSystem(
        n=n,
        H_scaled=H_scaled,
        inv_d=inv_d,
        cho=None,
        cond=1e16,
        regularized=True,
    )


def _solve_factored_symmetric(
    fac: _FactoredSymmetricSystem,
    rhs: np.ndarray,
    *,
    out: np.ndarray | None = None,
    rhs_scaled_buf: np.ndarray | None = None,
    res_s_buf: np.ndarray | None = None,
    mv_buf: np.ndarray | None = None,
) -> np.ndarray:
    """Resolve H dx = rhs usando a fatoração em cache + até 2 passos de refino iterativo."""
    if fac.n == 0:
        if out is not None:
            return out
        return np.zeros((0,), dtype=np.float64)

    rhs_scaled = np.multiply(fac.inv_d, rhs, out=rhs_scaled_buf) if rhs_scaled_buf is not None else fac.inv_d * rhs
    if fac.cho is not None:
        sol_s = scipy.linalg.cho_solve(fac.cho, rhs_scaled, check_finite=True)
        if mv_buf is not None and res_s_buf is not None:
            np.matmul(fac.H_scaled, sol_s, out=mv_buf)
            np.subtract(rhs_scaled, mv_buf, out=res_s_buf)
            res_s = res_s_buf
        else:
            res_s = rhs_scaled - fac.H_scaled @ sol_s
        res_norm = float(np.linalg.norm(res_s))
        rhs_norm = float(np.linalg.norm(rhs_scaled))
        for _ in range(2):
            if res_norm <= 1e-15 * (1.0 + rhs_norm):
                break
            corr_s = scipy.linalg.cho_solve(fac.cho, res_s, check_finite=True)
            if not np.all(np.isfinite(corr_s)):
                break
            cand_s = sol_s + corr_s
            if mv_buf is not None:
                np.matmul(fac.H_scaled, cand_s, out=mv_buf)
                new_res_s = rhs_scaled - mv_buf
            else:
                new_res_s = rhs_scaled - fac.H_scaled @ cand_s
            new_res_norm = float(np.linalg.norm(new_res_s))
            if new_res_norm < res_norm:
                sol_s = cand_s
                if res_s_buf is not None:
                    np.copyto(res_s_buf, new_res_s)
                    res_s = res_s_buf
                else:
                    res_s = new_res_s
                res_norm = new_res_norm
            else:
                break
        if out is not None:
            return np.multiply(fac.inv_d, sol_s, out=out)
        return np.asarray(fac.inv_d * sol_s, dtype=np.float64)

    sol_s, _, _, _ = scipy.linalg.lstsq(fac.H_scaled, rhs_scaled, cond=1e-13, check_finite=True)
    if out is not None:
        return np.multiply(fac.inv_d, sol_s, out=out)
    return np.asarray(fac.inv_d * sol_s, dtype=np.float64)


def _solve_symmetric_system(H: np.ndarray, rhs: np.ndarray) -> tuple[np.ndarray, float]:
    """Resolve H dx = rhs com precondicionamento diagonal de Jacobi + Cholesky + refino iterativo."""
    fac = _factor_symmetric_system(H)
    return _solve_factored_symmetric(fac, rhs), fac.cond


def _project_dual_onto_subspace(
    blocks: Sequence[_InternalConeBlock],
    m_vars: int,
    Z_list: Sequence[np.ndarray],
    target_c: np.ndarray,
    weight_mats: Sequence[np.ndarray] | None = None,
) -> list[np.ndarray] | None:
    """Projeta (Z_b) no subespaço afim sum_b <F_{b,j}, Z_b> = target_c[j] mantendo Z_b >= 0 se possível.

    Usa correção ponderada dZ_b = sum_j y_j (W_b F_{b,j} W_b) resolvida via lstsq/Cholesky.
    """
    if m_vars == 0:
        return [_sym(Z) for Z in Z_list]

    adj = np.zeros((m_vars,), dtype=np.float64)
    for blk, Z_b in zip(blocks, Z_list, strict=True):
        for j, fj in blk.F_terms.items():
            adj[j] += float(np.sum(fj * Z_b))
    res = target_c - adj
    if float(np.linalg.norm(res)) <= 1e-14 * (1.0 + float(np.linalg.norm(target_c))):
        return [_sym(Z) for Z in Z_list]

    W_list: list[np.ndarray] = []
    if weight_mats is not None:
        W_list = [_sym(W) for W in weight_mats]
    else:
        for Z_b in Z_list:
            W_list.append(_sym(Z_b) + 1e-6 * np.eye(Z_b.shape[0], dtype=np.float64))

    # Construir base ponderada B_{b,j} = W_b F_{b,j} W_b e matriz de Gram G_{i,j} = sum_b <F_{b,i}, B_{b,j}>
    G = np.zeros((m_vars, m_vars), dtype=np.float64)
    basis_terms: list[dict[int, np.ndarray]] = []
    for blk, W_b in zip(blocks, W_list, strict=True):
        b_dict: dict[int, np.ndarray] = {}
        for j, fj in blk.F_terms.items():
            b_dict[j] = _sym(W_b @ fj @ W_b)
        basis_terms.append(b_dict)
        for i, fi in blk.F_terms.items():
            for j, bj in b_dict.items():
                if j >= i:
                    val = float(np.sum(fi * bj))
                    G[i, j] += val
                    if i != j:
                        G[j, i] += val

    y_corr, _ = _solve_symmetric_system(G, res)
    Z_new: list[np.ndarray] = []
    for Z_b, b_dict in zip(Z_list, basis_terms, strict=True):
        dZ = np.zeros_like(Z_b)
        for j, bj in b_dict.items():
            yj = float(y_corr[j])
            if yj != 0.0:
                dZ = dZ + yj * bj
        Z_cand = _sym(Z_b + dZ)
        min_e = _min_eig_sym(Z_cand)
        z_norm = 1.0 + float(np.linalg.norm(Z_cand, "fro"))
        if min_e < -1e-9 * z_norm:
            return None
        Z_new.append(Z_cand)

    # Verificar que a projeção satisfaz estritamente a equação de subespaço
    adj_new = np.zeros((m_vars,), dtype=np.float64)
    adj_scale = 1.0 + float(np.linalg.norm(target_c))
    for blk, Z_b in zip(blocks, Z_new, strict=True):
        zb_norm = float(np.linalg.norm(Z_b, "fro"))
        for j, fj in blk.F_terms.items():
            adj_new[j] += float(np.sum(fj * Z_b))
            adj_scale += float(np.linalg.norm(fj, "fro")) * zb_norm
    if float(np.linalg.norm(target_c - adj_new)) / adj_scale > 1e-8:
        return None

    return Z_new


def _validate_strict_farkas_certificate(
    blocks: Sequence[_InternalConeBlock],
    m_vars: int,
    Z_cand: Sequence[np.ndarray],
) -> list[np.ndarray] | None:
    """Garante que o candidato de Farkas seja estritamente PSD após zerar autovalores negativos.

    Previne falsos certificados em casos de *weak infeasibility* (ex.: [[x, 1], [1, 0]] >= 0),
    nos quais um pequeno autovalor negativo -1e-10 permite satisfazer <F_k, Z> = 0 e <F_0, Z> < 0
    espúrios apesar de não existir nenhum Z >= 0 exato separando o cone: pela desigualdade de
    Cauchy-Schwarz no cone PSD, qualquer artefato espúrio satisfaz |f_rel| <= O(sqrt(adj_rel)).
    """
    Z_psd: list[np.ndarray] = []
    z_norm_sum = 0.0
    neg_pert_sum = 0.0
    for Z_b in Z_cand:
        evals, evecs = np.linalg.eigh(_sym(Z_b))
        max_e = float(np.max(evals)) if evals.size > 0 else 0.0
        min_e = float(np.min(evals)) if evals.size > 0 else 0.0
        # Permite apenas ruído residual O(mu) ou arredondamento numérico minúsculo (<= 1e-10)
        if min_e < -1e-10 * max(1.0, max_e):
            return None
        neg_pert_sum += float(np.sum(np.maximum(0.0, -evals)))
        evals_pos = np.maximum(evals, 0.0)
        Zp = _sym((evecs * evals_pos[None, :]) @ evecs.T)
        Z_psd.append(Zp)
        z_norm_sum += float(np.linalg.norm(Zp, "fro"))

    if z_norm_sum <= 1e-10:
        return None
    max_neg_ratio = neg_pert_sum / z_norm_sum

    # Normalizar e checar novamente a equação adjunta e a contradição estrita após o clamping PSD
    Z_unit = [Zp / z_norm_sum for Zp in Z_psd]
    adj = np.zeros((m_vars,), dtype=np.float64)
    adj_scale = 1e-12
    f_val = 0.0
    f_scale = 0.0
    for blk, Zu in zip(blocks, Z_unit, strict=True):
        zn = float(np.linalg.norm(Zu, "fro"))
        f_val += float(np.sum(blk.F0 * Zu))
        f_scale += float(np.linalg.norm(blk.F0, "fro")) * zn
        for j, fj in blk.F_terms.items():
            adj[j] += float(np.sum(fj * Zu))
            adj_scale += float(np.linalg.norm(fj, "fro")) * zn

    adj_rel = float(np.linalg.norm(adj)) / max(1e-12, adj_scale)
    if adj_rel > 1e-10:
        return None
    f_rel_abs_floor = f_val / max(1.0, f_scale)
    f_rel_scale_inv = f_val / max(1e-12, f_scale)
    cs_floor = max(1e-8, 100.0 * math.sqrt(max(adj_rel, max_neg_ratio, 1e-16)))
    if f_val >= -1e-8 or f_rel_abs_floor >= -1e-8 or f_rel_scale_inv >= -cs_floor:
        return None
    return Z_unit


# ---------------------------------------------------------------------------
# Núcleo Primal-Dual de Seguimento de Caminho (Fase I e Fase II)
# ---------------------------------------------------------------------------


def _nt_scaling_factors(
    cho_S: tuple[np.ndarray, bool],
    cho_Z: tuple[np.ndarray, bool],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calcula fatores de escalonamento de Nesterov-Todd (G, G_invT, lam) sem inv().

    Satisfaz:
        G_invT.T @ S @ G_invT == diag(lam)
        G.T @ Z @ G == diag(lam)
        G.T @ G_invT == I
    """
    LS_raw, lower_s = cho_S
    LZ_raw, lower_z = cho_Z
    LS = np.tril(LS_raw) if lower_s else np.triu(LS_raw).T
    LZ = np.tril(LZ_raw) if lower_z else np.triu(LZ_raw).T

    U, lam, Vt = scipy.linalg.svd(LZ.T @ LS, full_matrices=True, check_finite=True)
    lam_safe = np.maximum(lam, 1e-30)
    inv_sqrt = 1.0 / np.sqrt(lam_safe)
    G = (LS @ Vt.T) * inv_sqrt[None, :]
    G_invT = (LZ @ U) * inv_sqrt[None, :]
    return G, G_invT, lam_safe


def _max_step_scaled_identity(
    lam: np.ndarray,
    dM_tilde: np.ndarray,
    *,
    work1: np.ndarray | None = None,
    work2: np.ndarray | None = None,
) -> float:
    """Maior alpha > 0 tal que diag(lam) + alpha * dM_tilde >= 0 sem inversão."""
    if not np.all(np.isfinite(dM_tilde)):
        return 0.0
    if float(np.linalg.norm(dM_tilde, "fro")) <= 1e-16:
        return float("inf")
    inv_sqrt = 1.0 / np.sqrt(np.maximum(lam, 1e-30))
    if work1 is not None and work2 is not None:
        _sym_into(dM_tilde, work1)
        work1 *= inv_sqrt[:, None]
        work1 *= inv_sqrt[None, :]
        _sym_into(work1, work2)
        min_eig = float(np.min(np.linalg.eigvalsh(work2)))
    else:
        dM_sym = _sym(dM_tilde)
        scaled = _sym((inv_sqrt[:, None] * dM_sym) * inv_sqrt[None, :])
        min_eig = float(np.min(np.linalg.eigvalsh(scaled)))
    if min_eig >= -1e-15:
        return float("inf")
    return float(-1.0 / min_eig)


def _run_primal_dual_cone_loop(
    blocks: Sequence[_InternalConeBlock],
    c_vec: np.ndarray,
    c0: float,
    z_init: np.ndarray,
    *,
    phase_label: str,
    max_iter: int,
    tol_gap: float,
    tol_feas: float,
    step_fraction: float,
    sigma_min: float,
    sigma_max: float,
    stop_on_negative_obj_margin: float | None = None,
    check_farkas_on_blocks: int | None = None,
    unbounded_norm_threshold: float = 1e7,
    t_start: float | None = None,
    iteration_log: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Executa Pontos Interiores Primal-Dual (Nesterov-Todd + Mehrotra Preditor-Corretor).

    Resolve:
        min_{z in R^m}   c_vec^T z + c0
        sujeito a        S_b(z) = F_{b,0} + sum_{j=0}^{m-1} z_j F_{b,j} >= 0   (b = 0..B_int-1)

    Otimizações ADR-015 (Ciclo 1):
    - Agrupa todos os blocos PSD escalares `1x1` em um único cone LP vetorial 1D
      (`s_lp`, `z_lp`, `F0_lp`, `F_lp`), eliminando chamadas matriciais `eigh`/`cholesky`/`svd`.
    - Pré-aloca buffers de trabalho in-place (`H`, `H_scaled_buf`, `H_work_buf`, vetores RHS/direção
      e matrizes temporárias por bloco PSD) para conter fragmentação de heap em `wasm32`,
      liberando explicitamente as referências antes do retorno.
    """
    m = int(c_vec.shape[0])
    n_blocks = len(blocks)
    total_order = sum(b.dim for b in blocks)
    z = np.array(z_init, dtype=np.float64, copy=True)
    z0_initial = z.copy()
    c_scale = max(1.0, float(np.linalg.norm(c_vec)))
    c_norm = float(np.linalg.norm(c_vec))

    # -----------------------------------------------------------------------
    # Particionar blocos 1x1 (cone LP 1D unificado) vs blocos PSD (dim >= 2)
    # -----------------------------------------------------------------------
    lp_indices: list[int] = [i for i, b in enumerate(blocks) if b.dim == 1]
    psd_indices: list[int] = [i for i, b in enumerate(blocks) if b.dim > 1]
    psd_blocks: list[_InternalConeBlock] = [blocks[i] for i in psd_indices]
    q_lp = len(lp_indices)
    n_psd_blocks = len(psd_blocks)

    # -----------------------------------------------------------------------
    # Pré-alocar workspace do cone LP 1D (quando q_lp > 0)
    # -----------------------------------------------------------------------
    F0_lp: np.ndarray | None = None
    f_lp_row_norms: np.ndarray | None = None
    F_lp_dense: np.ndarray | None = None
    F_lp_scaled: np.ndarray | None = None
    F_lp_csr: scipy.sparse.csr_matrix | None = None
    F_lp_csc: scipy.sparse.csc_matrix | None = None
    use_sparse_lp = False

    s_lp: np.ndarray | None = None
    z_lp: np.ndarray | None = None
    s_lp_eval: np.ndarray | None = None
    s_lp_trial: np.ndarray | None = None
    z_lp_trial: np.ndarray | None = None
    rp_lp: np.ndarray | None = None
    s_lp_safe: np.ndarray | None = None
    w_lp: np.ndarray | None = None
    ds_lp_aff: np.ndarray | None = None
    dz_lp_aff: np.ndarray | None = None
    rc_lp: np.ndarray | None = None
    ds_lp: np.ndarray | None = None
    dz_lp: np.ndarray | None = None
    lp_vec_buf: np.ndarray | None = None
    lp_vec_buf2: np.ndarray | None = None

    if q_lp > 0:
        F0_lp = np.empty((q_lp,), dtype=np.float64)
        f_lp_row_norms = np.empty((q_lp,), dtype=np.float64)
        nnz_lp = 0
        for pos, orig_i in enumerate(lp_indices):
            blk = blocks[orig_i]
            F0_lp[pos] = float(blk.F0[0, 0])
            f_lp_row_norms[pos] = blk._f_norm_sum
            nnz_lp += int(blk._active_keys.size)

        use_sparse_lp = (q_lp * m > 16384) and (nnz_lp < int(0.15 * q_lp * m))
        if use_sparse_lp:
            lp_rows_parts: list[np.ndarray] = []
            lp_cols_parts: list[np.ndarray] = []
            lp_vals_parts: list[np.ndarray] = []
            for pos, orig_i in enumerate(lp_indices):
                blk = blocks[orig_i]
                ak = blk._active_keys
                if ak.size > 0:
                    lp_rows_parts.append(np.full((ak.size,), pos, dtype=np.int32))
                    lp_cols_parts.append(ak.astype(np.int32, copy=False))
                    lp_vals_parts.append(blk._F_cols[0, :])
            if lp_rows_parts:
                F_lp_csr = scipy.sparse.csr_matrix(
                    (
                        np.concatenate(lp_vals_parts),
                        (np.concatenate(lp_rows_parts), np.concatenate(lp_cols_parts)),
                    ),
                    shape=(q_lp, m),
                    dtype=np.float64,
                )
            else:
                F_lp_csr = scipy.sparse.csr_matrix((q_lp, m), dtype=np.float64)
            F_lp_csc = F_lp_csr.tocsc()
        else:
            F_lp_dense = np.zeros((q_lp, m), dtype=np.float64)
            for pos, orig_i in enumerate(lp_indices):
                blk = blocks[orig_i]
                if blk._active_keys.size > 0:
                    F_lp_dense[pos, blk._active_keys] = blk._F_cols[0, :]
            F_lp_scaled = np.empty((q_lp, m), dtype=np.float64)

        s_lp = np.empty((q_lp,), dtype=np.float64)
        s_lp_eval = np.empty((q_lp,), dtype=np.float64)
        s_lp_trial = np.empty((q_lp,), dtype=np.float64)
        z_lp_trial = np.empty((q_lp,), dtype=np.float64)
        rp_lp = np.empty((q_lp,), dtype=np.float64)
        s_lp_safe = np.empty((q_lp,), dtype=np.float64)
        w_lp = np.empty((q_lp,), dtype=np.float64)
        ds_lp_aff = np.empty((q_lp,), dtype=np.float64)
        dz_lp_aff = np.empty((q_lp,), dtype=np.float64)
        rc_lp = np.empty((q_lp,), dtype=np.float64)
        ds_lp = np.empty((q_lp,), dtype=np.float64)
        dz_lp = np.empty((q_lp,), dtype=np.float64)
        lp_vec_buf = np.empty((q_lp,), dtype=np.float64)
        lp_vec_buf2 = np.empty((q_lp,), dtype=np.float64)

        if use_sparse_lp:
            assert F_lp_csr is not None
            s_lp[:] = F_lp_csr @ z
        else:
            assert F_lp_dense is not None
            np.matmul(F_lp_dense, z, out=s_lp)
        s_lp += F0_lp
        bad_lp = s_lp <= 0.0
        if np.any(bad_lp):
            s_lp[bad_lp] = s_lp[bad_lp] + np.maximum(1e-3, -s_lp[bad_lp] + 1e-2)
        z_lp = np.full((q_lp,), c_scale, dtype=np.float64)

    # -----------------------------------------------------------------------
    # Pré-alocar workspace de Schur e vetores de direção (tamanho m)
    # -----------------------------------------------------------------------
    H = np.empty((m, m), dtype=np.float64)
    H_scaled_buf = np.empty((m, m), dtype=np.float64)
    H_work_buf = np.empty((m, m), dtype=np.float64, order="F")
    inv_d_buf = np.empty((m,), dtype=np.float64)
    adj = np.empty((m,), dtype=np.float64)
    r_d = np.empty((m,), dtype=np.float64)
    rhs_aff = np.empty((m,), dtype=np.float64)
    rhs_cor = np.empty((m,), dtype=np.float64)
    dz_aff = np.empty((m,), dtype=np.float64)
    dz = np.empty((m,), dtype=np.float64)
    z_trial = np.empty((m,), dtype=np.float64)
    rhs_scaled_buf = np.empty((m,), dtype=np.float64)
    res_s_buf = np.empty((m,), dtype=np.float64)
    m_scratch = np.empty((m,), dtype=np.float64)

    # -----------------------------------------------------------------------
    # Pré-alocar workspace por bloco PSD (dim >= 2)
    # -----------------------------------------------------------------------
    eye_psd: list[np.ndarray] = []
    diag_psd: list[np.ndarray] = []
    S_psd_list: list[np.ndarray] = []
    Z_psd_list: list[np.ndarray] = []
    S_eval_bufs: list[np.ndarray] = []
    S_trial_bufs: list[np.ndarray] = []
    Z_trial_bufs: list[np.ndarray] = []
    cho_S_bufs: list[np.ndarray] = []
    cho_S_trial_bufs: list[np.ndarray] = []
    cho_Z_bufs: list[np.ndarray] = []
    cho_Z_trial_bufs: list[np.ndarray] = []
    cho_S_psd: list[tuple[np.ndarray, bool]] = []
    cho_Z_psd: list[tuple[np.ndarray, bool]] = []
    R_p_psd_bufs: list[np.ndarray] = []
    R_p_hat_bufs: list[np.ndarray] = []
    cols_bufs: list[np.ndarray] = []
    gram_bufs: list[np.ndarray | None] = []
    dS_tilde_aff_bufs: list[np.ndarray] = []
    dZ_tilde_aff_bufs: list[np.ndarray] = []
    M_cor_bufs: list[np.ndarray] = []
    dZ_psd_bufs: list[np.ndarray] = []
    tmp1_bufs: list[np.ndarray] = []
    tmp2_bufs: list[np.ndarray] = []
    act_vec_bufs: list[np.ndarray | None] = []
    is_full_m: list[bool] = []
    G_invT_psd: list[np.ndarray] = [np.empty((0, 0), dtype=np.float64)] * n_psd_blocks
    lam_psd: list[np.ndarray] = [np.empty((0,), dtype=np.float64)] * n_psd_blocks

    for blk in psd_blocks:
        dim = blk.dim
        n_act = int(blk._active_keys.size)
        eye_b = np.eye(dim, dtype=np.float64)
        diag_b = np.arange(dim, dtype=np.intp)
        eye_psd.append(eye_b)
        diag_psd.append(diag_b)

        S_b = np.empty((dim, dim), dtype=np.float64)
        tmp1_b = np.empty((dim, dim), dtype=np.float64)
        tmp2_b = np.empty((dim, dim), dtype=np.float64)
        cho_s_work = np.empty((dim, dim), dtype=np.float64, order="F")
        cho_s_trial = np.empty((dim, dim), dtype=np.float64, order="F")
        cho_z_work = np.empty((dim, dim), dtype=np.float64, order="F")
        cho_z_trial = np.empty((dim, dim), dtype=np.float64, order="F")

        blk.evaluate_into(z, S_b, tmp1_b)
        cho_s = _safe_cholesky_buf(S_b, cho_s_work)
        if cho_s is None:
            eigs = np.linalg.eigvalsh(S_b)
            shift = max(1e-3, -float(np.min(eigs)) + 1e-2)
            S_b[diag_b, diag_b] += shift
            _sym_into(S_b, tmp1_b)
            np.copyto(S_b, tmp1_b)
            cho_s = _safe_cholesky_buf(S_b, cho_s_work)
            assert cho_s is not None

        Z_b = c_scale * eye_b.copy()
        cho_z = _safe_cholesky_buf(Z_b, cho_z_work)
        assert cho_z is not None

        S_psd_list.append(S_b)
        Z_psd_list.append(Z_b)
        S_eval_bufs.append(np.empty((dim, dim), dtype=np.float64))
        S_trial_bufs.append(np.empty((dim, dim), dtype=np.float64))
        Z_trial_bufs.append(np.empty((dim, dim), dtype=np.float64))
        cho_S_bufs.append(cho_s_work)
        cho_S_trial_bufs.append(cho_s_trial)
        cho_Z_bufs.append(cho_z_work)
        cho_Z_trial_bufs.append(cho_z_trial)
        cho_S_psd.append(cho_s)
        cho_Z_psd.append(cho_z)
        R_p_psd_bufs.append(np.empty((dim, dim), dtype=np.float64))
        R_p_hat_bufs.append(np.empty((dim, dim), dtype=np.float64))
        cols_bufs.append(np.empty((dim * dim, n_act), dtype=np.float64))
        gram_bufs.append(np.empty((n_act, n_act), dtype=np.float64) if n_act > 0 else None)
        dS_tilde_aff_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dZ_tilde_aff_bufs.append(np.empty((dim, dim), dtype=np.float64))
        M_cor_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dZ_psd_bufs.append(np.empty((dim, dim), dtype=np.float64))
        tmp1_bufs.append(tmp1_b)
        tmp2_bufs.append(tmp2_b)
        act_vec_bufs.append(np.empty((n_act,), dtype=np.float64) if n_act > 0 else None)
        is_full_m.append(
            n_act == m and n_act > 0 and int(blk._active_keys[0]) == 0 and int(blk._active_keys[-1]) == m - 1
        )

    # Pré-computar metadados de Fase I (sub-blocos de Farkas e índices originais) fora do laço
    n_check_p1 = check_farkas_on_blocks if check_farkas_on_blocks is not None else n_blocks
    lp_check_pos = np.asarray(
        [pos for pos, orig_i in enumerate(lp_indices) if orig_i < n_check_p1], dtype=np.intp
    )
    psd_check_pos = [pos for pos, orig_i in enumerate(psd_indices) if orig_i < n_check_p1]
    sub_blocks_farkas: list[_InternalConeBlock] | None = None
    if check_farkas_on_blocks is not None:
        m_orig_f = m - 1
        sub_blocks_farkas = [
            _InternalConeBlock(
                name=b.name,
                dim=b.dim,
                F0=b.F0,
                F_terms={j: fj for j, fj in b.F_terms.items() if j < m_orig_f},
            )
            for b in blocks[:check_farkas_on_blocks]
        ]

    history: list[IterationRecord] = []
    iter_log: list[dict[str, Any]] = iteration_log if iteration_log is not None else []
    t0 = t_start if t_start is not None else time.perf_counter()
    solver_status = "max_iterations"
    farkas_candidate: list[np.ndarray] | None = None
    recession_candidate: np.ndarray | None = None

    for it in range(max_iter):
        # 1. Avaliar folgas primais exatas, gap de complementaridade e resíduo dual
        lp_eval_pos = True
        if q_lp > 0:
            assert s_lp_eval is not None and F0_lp is not None and s_lp is not None and z_lp is not None
            assert rp_lp is not None and f_lp_row_norms is not None
            if use_sparse_lp:
                assert F_lp_csr is not None
                s_lp_eval[:] = F_lp_csr @ z
            else:
                assert F_lp_dense is not None
                np.matmul(F_lp_dense, z, out=s_lp_eval)
            s_lp_eval += F0_lp
            lp_eval_pos = bool(np.all(np.isfinite(s_lp_eval)) and np.all(s_lp_eval > 0.0))

        psd_eval_pos = True
        cho_eval_psd: list[tuple[np.ndarray, bool]] = []
        for pos, blk in enumerate(psd_blocks):
            blk.evaluate_into(z, S_eval_bufs[pos], tmp1_bufs[pos])
            if psd_eval_pos and lp_eval_pos:
                c_ev = _safe_cholesky_buf(S_eval_bufs[pos], cho_S_trial_bufs[pos])
                if c_ev is None:
                    psd_eval_pos = False
                else:
                    cho_eval_psd.append(c_ev)

        if lp_eval_pos and psd_eval_pos:
            if q_lp > 0:
                assert s_lp is not None and s_lp_eval is not None
                np.copyto(s_lp, s_lp_eval)
            for pos in range(n_psd_blocks):
                np.copyto(S_psd_list[pos], S_eval_bufs[pos])
                if cho_eval_psd[pos][0] is cho_S_trial_bufs[pos]:
                    cho_S_bufs[pos], cho_S_trial_bufs[pos] = cho_S_trial_bufs[pos], cho_S_bufs[pos]
                cho_S_psd[pos] = cho_eval_psd[pos]

        rp_norm = 0.0
        gap = 0.0
        adj.fill(0.0)
        dual_scale = 1.0 + c_norm
        dual_f0_dot = 0.0
        comp_scale = 1.0
        min_eig_p = float("inf")
        min_eig_d = float("inf")

        if q_lp > 0:
            assert s_lp is not None and s_lp_eval is not None and z_lp is not None
            assert rp_lp is not None and F0_lp is not None and f_lp_row_norms is not None
            np.subtract(s_lp, s_lp_eval, out=rp_lp)
            rp_norm = max(rp_norm, float(np.max(np.abs(rp_lp))))
            gap += float(np.dot(s_lp, z_lp))
            if use_sparse_lp:
                assert F_lp_csc is not None
                adj += F_lp_csc.T @ z_lp
            else:
                assert F_lp_dense is not None
                np.matmul(F_lp_dense.T, z_lp, out=adj)
            dual_scale += float(np.dot(f_lp_row_norms, np.abs(z_lp)))
            dual_f0_dot += float(np.dot(F0_lp, z_lp))
            comp_scale += float(np.dot(np.abs(s_lp), np.abs(z_lp)))
            min_eig_p = min(min_eig_p, float(np.min(s_lp_eval)))
            min_eig_d = min(min_eig_d, float(np.min(z_lp)))

        for pos, blk in enumerate(psd_blocks):
            S_b = S_psd_list[pos]
            S_ev = S_eval_bufs[pos]
            Z_b = Z_psd_list[pos]
            np.subtract(S_b, S_ev, out=R_p_psd_bufs[pos])
            rp_norm = max(rp_norm, float(np.linalg.norm(R_p_psd_bufs[pos], "fro")))
            gap += float(np.sum(S_b * Z_b))
            z_norm_b = float(np.linalg.norm(Z_b, "fro"))
            if blk._active_keys.size > 0:
                act_buf = act_vec_bufs[pos]
                assert act_buf is not None
                np.matmul(blk._F_cols.T, Z_b.ravel(), out=act_buf)
                if is_full_m[pos]:
                    adj += act_buf
                else:
                    adj[blk._active_keys] += act_buf
                dual_scale += blk._f_norm_sum * z_norm_b
            dual_f0_dot += float(np.sum(blk.F0 * Z_b))
            comp_scale += float(np.linalg.norm(S_b, "fro")) * z_norm_b
            min_eig_p = min(min_eig_p, float(np.min(np.linalg.eigvalsh(S_ev))))
            min_eig_d = min(min_eig_d, float(np.min(np.linalg.eigvalsh(Z_b))))

        mu = gap / max(1, total_order)
        np.subtract(c_vec, adj, out=r_d)
        r_d_rel = float(np.linalg.norm(r_d) / dual_scale)

        primal_obj = float(np.dot(c_vec, z) + c0)
        dual_obj = float(c0 - dual_f0_dot)
        rel_gap = abs(primal_obj - dual_obj) / (1.0 + abs(primal_obj) + abs(dual_obj))
        comp_rel = abs(gap) / comp_scale

        def _record_iter_log(alpha_step: float) -> None:
            entry = {
                "iter": int(it + 1),
                "max_iters": int(max_iter),
                "gap": float(gap),
                "primal_res": float(rp_norm),
                "dual_res": float(r_d_rel),
                "min_eig": float(min_eig_p),
                "alpha": float(alpha_step),
                "elapsed_ms": float((time.perf_counter() - t0) * 1000.0),
            }
            iter_log.append(entry)
            if callable(progress_callback):
                try:
                    progress_callback(entry)
                except Exception:
                    pass

        # Parada antecipada de Fase I assim que atingirmos ponto estritamente interior
        if stop_on_negative_obj_margin is not None and primal_obj < -stop_on_negative_obj_margin:
            np.copyto(m_scratch, z)
            m_scratch[m - 1] = 0.0
            orig_min_eig = float("inf")
            if lp_check_pos.size > 0:
                assert F0_lp is not None and lp_vec_buf is not None
                if use_sparse_lp:
                    assert F_lp_csr is not None
                    lp_vec_buf[:] = F_lp_csr @ m_scratch
                else:
                    assert F_lp_dense is not None
                    np.matmul(F_lp_dense, m_scratch, out=lp_vec_buf)
                lp_vec_buf += F0_lp
                orig_min_eig = min(orig_min_eig, float(np.min(lp_vec_buf[lp_check_pos])))
            for pos in psd_check_pos:
                psd_blocks[pos].evaluate_into(m_scratch, tmp2_bufs[pos], tmp1_bufs[pos])
                orig_min_eig = min(orig_min_eig, float(np.min(np.linalg.eigvalsh(tmp2_bufs[pos]))))
            if orig_min_eig > 0.5 * stop_on_negative_obj_margin:
                history.append(
                    IterationRecord(
                        iteration=it,
                        phase=phase_label,
                        mu=mu,
                        primal_obj=primal_obj,
                        dual_obj=dual_obj,
                        duality_gap=gap,
                        dual_residual_rel=r_d_rel,
                        eq_residual_rel=0.0,
                        min_eig_primal=min_eig_p,
                        min_eig_dual=min_eig_d,
                        alpha_primal=0.0,
                        alpha_dual=0.0,
                        kkt_condition_number=1.0,
                        sigma=0.0,
                        step_norm=0.0,
                    )
                )
                _record_iter_log(0.0)
                solver_status = "optimal"
                break

        # Em Fase I, checar se o dual atual já projeta para um certificado de Farkas estrito
        if check_farkas_on_blocks is not None and primal_obj > 0.0:
            assert sub_blocks_farkas is not None
            orig_Z: list[np.ndarray] = [None] * check_farkas_on_blocks  # type: ignore[list-item]
            orig_W: list[np.ndarray] = [None] * check_farkas_on_blocks  # type: ignore[list-item]
            if q_lp > 0:
                assert s_lp is not None and z_lp is not None
                for pos, orig_i in enumerate(lp_indices):
                    if orig_i < check_farkas_on_blocks:
                        orig_Z[orig_i] = np.array([[float(z_lp[pos])]], dtype=np.float64)
                        orig_W[orig_i] = np.array([[1.0 / max(float(s_lp[pos]), 1e-30)]], dtype=np.float64)
            for pos, orig_i in enumerate(psd_indices):
                if orig_i < check_farkas_on_blocks:
                    orig_Z[orig_i] = Z_psd_list[pos]
                    orig_W[orig_i] = _cho_solve_mat(cho_S_psd[pos], eye_psd[pos])
            m_orig = m - 1
            Z_proj = _project_dual_onto_subspace(
                sub_blocks_farkas,
                m_orig,
                orig_Z,
                np.zeros((m_orig,), dtype=np.float64),
                weight_mats=orig_W,
            )
            if Z_proj is not None:
                Z_strict = _validate_strict_farkas_certificate(sub_blocks_farkas, m_orig, Z_proj)
                if Z_strict is not None:
                    farkas_candidate = Z_strict
                    if it >= 3 or (comp_rel <= 1e-3 and r_d_rel <= 1e-4):
                        history.append(
                            IterationRecord(
                                iteration=it,
                                phase=phase_label,
                                mu=mu,
                                primal_obj=primal_obj,
                                dual_obj=dual_obj,
                                duality_gap=gap,
                                dual_residual_rel=r_d_rel,
                                eq_residual_rel=0.0,
                                min_eig_primal=min_eig_p,
                                min_eig_dual=min_eig_d,
                                alpha_primal=0.0,
                                alpha_dual=0.0,
                                kkt_condition_number=1.0,
                                sigma=0.0,
                                step_norm=0.0,
                            )
                        )
                        _record_iter_log(0.0)
                        solver_status = "primal_infeasible"
                        break

        # Critério de convergência primal-dual (alinhado ao verificador independente)
        primal_slack_err = rp_norm
        if (
            min_eig_p >= -1e-9
            and r_d_rel <= tol_feas
            and max(rel_gap, comp_rel) <= tol_gap
            and primal_slack_err <= tol_feas
        ):
            history.append(
                IterationRecord(
                    iteration=it,
                    phase=phase_label,
                    mu=mu,
                    primal_obj=primal_obj,
                    dual_obj=dual_obj,
                    duality_gap=gap,
                    dual_residual_rel=r_d_rel,
                    eq_residual_rel=0.0,
                    min_eig_primal=min_eig_p,
                    min_eig_dual=min_eig_d,
                    alpha_primal=0.0,
                    alpha_dual=0.0,
                    kkt_condition_number=1.0,
                    sigma=0.0,
                    step_norm=0.0,
                )
            )
            _record_iter_log(0.0)
            solver_status = "optimal"
            break

        # 2. Escalonamento de Nesterov-Todd (NT) e montagem in-place da matriz de Schur H
        # 2a. Cone LP 1D unificado (blocos 1x1): w_lp = z_lp / s_lp, H = F_lp.T @ (w_lp[:, None] * F_lp)
        if q_lp > 0:
            assert s_lp is not None and z_lp is not None and s_lp_safe is not None and w_lp is not None
            np.maximum(s_lp, 1e-30, out=s_lp_safe)
            np.divide(z_lp, s_lp_safe, out=w_lp)
            if use_sparse_lp:
                assert F_lp_csc is not None and F_lp_csr is not None
                H.fill(0.0)
                H += (F_lp_csc.T @ F_lp_csr.multiply(w_lp[:, None])).toarray()
            else:
                assert F_lp_dense is not None and F_lp_scaled is not None
                np.multiply(F_lp_dense, w_lp[:, None], out=F_lp_scaled)
                np.matmul(F_lp_dense.T, F_lp_scaled, out=H)
        else:
            H.fill(0.0)

        # 2b. Blocos PSD (dim >= 2): congruência NT esparsa + montagem BLAS in-place em H
        for pos, blk in enumerate(psd_blocks):
            _, G_invT_b, lam_b = _nt_scaling_factors(cho_S_psd[pos], cho_Z_psd[pos])
            G_invT_psd[pos] = G_invT_b
            lam_psd[pos] = lam_b
            active_keys = blk._active_keys
            n_act = int(active_keys.size)
            cols = cols_bufs[pos]
            tmp1 = tmp1_bufs[pos]
            tmp2 = tmp2_bufs[pos]
            sparse_terms = blk._sparse_terms
            for idx, j_raw in enumerate(active_keys):
                j = int(j_raw)
                sp = sparse_terms.get(j)
                if sp is not None:
                    r_sp, c_sp, v_sp = sp
                    np.matmul(G_invT_b[r_sp, :].T, v_sp[:, None] * G_invT_b[c_sp, :], out=tmp1)
                else:
                    np.matmul(G_invT_b.T, blk.F_terms[j], out=tmp2)
                    np.matmul(tmp2, G_invT_b, out=tmp1)
                _sym_into(tmp1, tmp2)
                cols[:, idx] = tmp2.ravel()
            np.matmul(G_invT_b.T, R_p_psd_bufs[pos], out=tmp1)
            np.matmul(tmp1, G_invT_b, out=tmp2)
            _sym_into(tmp2, R_p_hat_bufs[pos])

            if n_act > 0:
                gram = gram_bufs[pos]
                assert gram is not None
                np.matmul(cols.T, cols, out=gram)
                if is_full_m[pos]:
                    H += gram
                else:
                    H[np.ix_(active_keys, active_keys)] += gram

        # Fatorar o sistema de Schur uma única vez por iteração usando buffers pré-alocados
        fac_H = _factor_symmetric_system(
            H, H_scaled_buf=H_scaled_buf, H_work_buf=H_work_buf, inv_d_buf=inv_d_buf
        )
        cond_H = fac_H.cond

        # 3. Passo Preditor Afim de Mehrotra (sigma = 0)
        np.negative(r_d, out=rhs_aff)
        if q_lp > 0:
            assert w_lp is not None and rp_lp is not None and z_lp is not None and lp_vec_buf is not None
            np.multiply(w_lp, rp_lp, out=lp_vec_buf)
            lp_vec_buf -= z_lp
            if use_sparse_lp:
                assert F_lp_csc is not None
                rhs_aff += F_lp_csc.T @ lp_vec_buf
            else:
                assert F_lp_dense is not None
                np.matmul(F_lp_dense.T, lp_vec_buf, out=m_scratch)
                rhs_aff += m_scratch

        for pos, blk in enumerate(psd_blocks):
            active_keys = blk._active_keys
            if active_keys.size > 0:
                tmp1 = tmp1_bufs[pos]
                np.copyto(tmp1, R_p_hat_bufs[pos])
                tmp1[diag_psd[pos], diag_psd[pos]] -= lam_psd[pos]
                act_buf = act_vec_bufs[pos]
                assert act_buf is not None
                np.matmul(cols_bufs[pos].T, tmp1.ravel(), out=act_buf)
                if is_full_m[pos]:
                    rhs_aff += act_buf
                else:
                    rhs_aff[active_keys] += act_buf

        _solve_factored_symmetric(
            fac_H,
            rhs_aff,
            out=dz_aff,
            rhs_scaled_buf=rhs_scaled_buf,
            res_s_buf=res_s_buf,
            mv_buf=m_scratch,
        )

        # Checar se dz_aff revela direção recessiva ilimitada (c^T dz_aff < 0 e F_lin >= 0)
        dz_aff_norm = float(np.linalg.norm(dz_aff))
        if check_farkas_on_blocks is None and float(np.dot(c_vec, dz_aff)) < -1e-7 * c_scale * dz_aff_norm:
            min_lin_eig = float("inf")
            if q_lp > 0:
                assert lp_vec_buf is not None
                if use_sparse_lp:
                    assert F_lp_csr is not None
                    lp_vec_buf[:] = F_lp_csr @ dz_aff
                else:
                    assert F_lp_dense is not None
                    np.matmul(F_lp_dense, dz_aff, out=lp_vec_buf)
                min_lin_eig = min(min_lin_eig, float(np.min(lp_vec_buf)))
            for blk in psd_blocks:
                min_lin_eig = min(min_lin_eig, float(np.min(np.linalg.eigvalsh(blk.evaluate_linear(dz_aff)))))
            if dz_aff_norm > 1e-12 and min_lin_eig >= -1e-10 * dz_aff_norm:
                recession_candidate = dz_aff / dz_aff_norm
                history.append(
                    IterationRecord(
                        iteration=it,
                        phase=phase_label,
                        mu=mu,
                        primal_obj=primal_obj,
                        dual_obj=dual_obj,
                        duality_gap=gap,
                        dual_residual_rel=r_d_rel,
                        eq_residual_rel=0.0,
                        min_eig_primal=min_eig_p,
                        min_eig_dual=min_eig_d,
                        alpha_primal=1.0,
                        alpha_dual=0.0,
                        kkt_condition_number=cond_H,
                        sigma=0.0,
                        step_norm=dz_aff_norm,
                    )
                )
                _record_iter_log(1.0)
                solver_status = "dual_infeasible"
                break

        alpha_p_aff = 1.0
        alpha_d_aff = 1.0

        if q_lp > 0:
            assert s_lp is not None and z_lp is not None and s_lp_safe is not None
            assert rp_lp is not None and w_lp is not None and ds_lp_aff is not None and dz_lp_aff is not None
            if use_sparse_lp:
                assert F_lp_csr is not None
                ds_lp_aff[:] = F_lp_csr @ dz_aff
            else:
                assert F_lp_dense is not None
                np.matmul(F_lp_dense, dz_aff, out=ds_lp_aff)
            ds_lp_aff -= rp_lp
            np.multiply(w_lp, ds_lp_aff, out=dz_lp_aff)
            dz_lp_aff += z_lp
            np.negative(dz_lp_aff, out=dz_lp_aff)

            if not np.all(np.isfinite(ds_lp_aff)):
                alpha_p_aff = 0.0
            else:
                neg_p = ds_lp_aff < -1e-15 * s_lp_safe
                if np.any(neg_p):
                    alpha_p_aff = min(alpha_p_aff, step_fraction * float(np.min(-s_lp[neg_p] / ds_lp_aff[neg_p])))
            if not np.all(np.isfinite(dz_lp_aff)):
                alpha_d_aff = 0.0
            else:
                neg_d = dz_lp_aff < -1e-15 * np.maximum(z_lp, 1e-30)
                if np.any(neg_d):
                    alpha_d_aff = min(alpha_d_aff, step_fraction * float(np.min(-z_lp[neg_d] / dz_lp_aff[neg_d])))

        for pos, blk in enumerate(psd_blocks):
            active_keys = blk._active_keys
            tmp1 = tmp1_bufs[pos]
            tmp2 = tmp2_bufs[pos]
            ds_t = dS_tilde_aff_bufs[pos]
            dz_t = dZ_tilde_aff_bufs[pos]
            if active_keys.size > 0:
                dz_act = dz_aff if is_full_m[pos] else dz_aff[active_keys]
                np.matmul(cols_bufs[pos], dz_act, out=tmp1.ravel())
                tmp1 -= R_p_hat_bufs[pos]
                _sym_into(tmp1, ds_t)
            else:
                np.negative(R_p_hat_bufs[pos], out=tmp1)
                _sym_into(tmp1, ds_t)
            np.negative(ds_t, out=dz_t)
            dz_t[diag_psd[pos], diag_psd[pos]] -= lam_psd[pos]
            alpha_p_aff = min(
                alpha_p_aff, step_fraction * _max_step_scaled_identity(lam_psd[pos], ds_t, work1=tmp1, work2=tmp2)
            )
            alpha_d_aff = min(
                alpha_d_aff, step_fraction * _max_step_scaled_identity(lam_psd[pos], dz_t, work1=tmp1, work2=tmp2)
            )

        gap_aff = 0.0
        if q_lp > 0:
            assert s_lp is not None and z_lp is not None and ds_lp_aff is not None and dz_lp_aff is not None
            assert lp_vec_buf is not None and lp_vec_buf2 is not None
            np.multiply(ds_lp_aff, alpha_p_aff, out=lp_vec_buf)
            lp_vec_buf += s_lp
            np.multiply(dz_lp_aff, alpha_d_aff, out=lp_vec_buf2)
            lp_vec_buf2 += z_lp
            gap_aff += float(np.dot(lp_vec_buf, lp_vec_buf2))

        for pos in range(n_psd_blocks):
            tmp1 = tmp1_bufs[pos]
            tmp2 = tmp2_bufs[pos]
            np.multiply(dS_tilde_aff_bufs[pos], alpha_p_aff, out=tmp1)
            tmp1[diag_psd[pos], diag_psd[pos]] += lam_psd[pos]
            np.multiply(dZ_tilde_aff_bufs[pos], alpha_d_aff, out=tmp2)
            tmp2[diag_psd[pos], diag_psd[pos]] += lam_psd[pos]
            gap_aff += float(np.sum(tmp1 * tmp2))

        mu_aff = max(0.0, gap_aff / max(1, total_order))
        if r_d_rel > 1e-6:
            sigma_dyn_min = max(sigma_min, 0.12)
        elif r_d_rel > 1e-8:
            sigma_dyn_min = max(sigma_min, 0.05)
        else:
            sigma_dyn_min = sigma_min
        sigma = float(np.clip((mu_aff / max(mu, 1e-16)) ** 3, sigma_dyn_min, sigma_max))

        # 4. Passo Corretor-Centrador de Mehrotra (com termo de segunda ordem simetrizado no espaço NT)
        eta_meh = 1.0 if min(alpha_p_aff, alpha_d_aff) >= 0.05 else 0.0
        np.negative(r_d, out=rhs_cor)

        if q_lp > 0:
            assert s_lp is not None and z_lp is not None and s_lp_safe is not None and w_lp is not None
            assert rp_lp is not None and rc_lp is not None and ds_lp_aff is not None and dz_lp_aff is not None
            assert lp_vec_buf is not None and lp_vec_buf2 is not None
            np.multiply(s_lp, z_lp, out=rc_lp)
            np.subtract(sigma * mu, rc_lp, out=rc_lp)
            if eta_meh != 0.0:
                np.multiply(ds_lp_aff, dz_lp_aff, out=lp_vec_buf)
                rc_lp -= lp_vec_buf
            np.divide(rc_lp, s_lp_safe, out=lp_vec_buf)
            np.multiply(w_lp, rp_lp, out=lp_vec_buf2)
            lp_vec_buf += lp_vec_buf2
            if use_sparse_lp:
                assert F_lp_csc is not None
                rhs_cor += F_lp_csc.T @ lp_vec_buf
            else:
                assert F_lp_dense is not None
                np.matmul(F_lp_dense.T, lp_vec_buf, out=m_scratch)
                rhs_cor += m_scratch

        for pos, blk in enumerate(psd_blocks):
            lam_b = lam_psd[pos]
            tmp1 = tmp1_bufs[pos]
            tmp2 = tmp2_bufs[pos]
            M_cor_b = M_cor_bufs[pos]
            if eta_meh != 0.0:
                np.matmul(dS_tilde_aff_bufs[pos], dZ_tilde_aff_bufs[pos], out=tmp1)
                _sym_into(tmp1, tmp2)
                np.negative(tmp2, out=tmp1)
                tmp1[diag_psd[pos], diag_psd[pos]] += sigma * mu - lam_b * lam_b
            else:
                tmp1.fill(0.0)
                tmp1[diag_psd[pos], diag_psd[pos]] = sigma * mu - lam_b * lam_b
            np.add.outer(lam_b, lam_b, out=tmp2)
            np.maximum(tmp2, 1e-30, out=tmp2)
            tmp1 *= 2.0
            np.divide(tmp1, tmp2, out=tmp1)
            _sym_into(tmp1, M_cor_b)
            active_keys = blk._active_keys
            if active_keys.size > 0:
                np.add(M_cor_b, R_p_hat_bufs[pos], out=tmp1)
                act_buf = act_vec_bufs[pos]
                assert act_buf is not None
                np.matmul(cols_bufs[pos].T, tmp1.ravel(), out=act_buf)
                if is_full_m[pos]:
                    rhs_cor += act_buf
                else:
                    rhs_cor[active_keys] += act_buf

        _solve_factored_symmetric(
            fac_H,
            rhs_cor,
            out=dz,
            rhs_scaled_buf=rhs_scaled_buf,
            res_s_buf=res_s_buf,
            mv_buf=m_scratch,
        )

        alpha_p_max = float("inf")
        alpha_d_max = float("inf")

        if q_lp > 0:
            assert s_lp is not None and z_lp is not None and s_lp_safe is not None and w_lp is not None
            assert rp_lp is not None and rc_lp is not None and ds_lp is not None and dz_lp is not None
            assert lp_vec_buf is not None
            if use_sparse_lp:
                assert F_lp_csr is not None
                ds_lp[:] = F_lp_csr @ dz
            else:
                assert F_lp_dense is not None
                np.matmul(F_lp_dense, dz, out=ds_lp)
            ds_lp -= rp_lp
            np.divide(rc_lp, s_lp_safe, out=dz_lp)
            np.multiply(w_lp, ds_lp, out=lp_vec_buf)
            dz_lp -= lp_vec_buf

            if not np.all(np.isfinite(ds_lp)):
                alpha_p_max = 0.0
            else:
                neg_p = ds_lp < -1e-15 * s_lp_safe
                if np.any(neg_p):
                    alpha_p_max = min(alpha_p_max, float(np.min(-s_lp[neg_p] / ds_lp[neg_p])))
            if not np.all(np.isfinite(dz_lp)):
                alpha_d_max = 0.0
            else:
                neg_d = dz_lp < -1e-15 * np.maximum(z_lp, 1e-30)
                if np.any(neg_d):
                    alpha_d_max = min(alpha_d_max, float(np.min(-z_lp[neg_d] / dz_lp[neg_d])))

        for pos, blk in enumerate(psd_blocks):
            active_keys = blk._active_keys
            tmp1 = tmp1_bufs[pos]
            tmp2 = tmp2_bufs[pos]
            ds_t = dS_tilde_aff_bufs[pos]
            dz_t = dZ_tilde_aff_bufs[pos]
            if active_keys.size > 0:
                dz_act = dz if is_full_m[pos] else dz[active_keys]
                np.matmul(cols_bufs[pos], dz_act, out=tmp1.ravel())
                tmp1 -= R_p_hat_bufs[pos]
                _sym_into(tmp1, ds_t)
            else:
                np.negative(R_p_hat_bufs[pos], out=tmp1)
                _sym_into(tmp1, ds_t)
            np.subtract(M_cor_bufs[pos], ds_t, out=tmp1)
            _sym_into(tmp1, dz_t)
            G_invT_b = G_invT_psd[pos]
            np.matmul(G_invT_b, dz_t, out=tmp1)
            np.matmul(tmp1, G_invT_b.T, out=tmp2)
            _sym_into(tmp2, dZ_psd_bufs[pos])

            alpha_p_max = min(alpha_p_max, _max_step_scaled_identity(lam_psd[pos], ds_t, work1=tmp1, work2=tmp2))
            alpha_d_max = min(alpha_d_max, _max_step_scaled_identity(lam_psd[pos], dz_t, work1=tmp1, work2=tmp2))

        alpha_p = min(1.0, step_fraction * alpha_p_max)
        alpha_d = min(1.0, step_fraction * alpha_d_max)

        # Backtracking para garantir estrita positividade via vetor 1D (LP) e Cholesky exata (PSD)
        while alpha_p > 1e-12:
            np.multiply(dz, alpha_p, out=z_trial)
            z_trial += z
            lp_ok = True
            if q_lp > 0:
                assert s_lp_trial is not None and F0_lp is not None
                if use_sparse_lp:
                    assert F_lp_csr is not None
                    s_lp_trial[:] = F_lp_csr @ z_trial
                else:
                    assert F_lp_dense is not None
                    np.matmul(F_lp_dense, z_trial, out=s_lp_trial)
                s_lp_trial += F0_lp
                lp_ok = bool(np.all(np.isfinite(s_lp_trial)) and np.all(s_lp_trial > 0.0))
            if lp_ok:
                psd_ok = True
                cho_p_trial: list[tuple[np.ndarray, bool]] = []
                for pos, blk in enumerate(psd_blocks):
                    blk.evaluate_into(z_trial, S_trial_bufs[pos], tmp1_bufs[pos])
                    c_p = _safe_cholesky_buf(S_trial_bufs[pos], cho_S_trial_bufs[pos])
                    if c_p is None:
                        psd_ok = False
                        break
                    cho_p_trial.append(c_p)
                if psd_ok:
                    if q_lp > 0:
                        assert s_lp is not None and s_lp_trial is not None
                        np.copyto(s_lp, s_lp_trial)
                    for pos in range(n_psd_blocks):
                        np.copyto(S_psd_list[pos], S_trial_bufs[pos])
                        if cho_p_trial[pos][0] is cho_S_trial_bufs[pos]:
                            cho_S_bufs[pos], cho_S_trial_bufs[pos] = cho_S_trial_bufs[pos], cho_S_bufs[pos]
                        cho_S_psd[pos] = cho_p_trial[pos]
                    np.copyto(z, z_trial)
                    break
            alpha_p *= 0.5
        else:
            np.multiply(dz, alpha_p, out=m_scratch)
            z += m_scratch
            if q_lp > 0:
                assert s_lp is not None and ds_lp is not None and lp_vec_buf is not None
                np.multiply(ds_lp, alpha_p, out=lp_vec_buf)
                s_lp += lp_vec_buf
                np.maximum(s_lp, 1e-30, out=s_lp)
            for pos, blk in enumerate(psd_blocks):
                dS_b = -R_p_psd_bufs[pos] + blk.evaluate_linear(dz)
                np.multiply(dS_b, alpha_p, out=tmp1_bufs[pos])
                tmp1_bufs[pos] += S_psd_list[pos]
                _sym_into(tmp1_bufs[pos], S_psd_list[pos])
                c_fb = _safe_cholesky_buf(S_psd_list[pos], cho_S_trial_bufs[pos])
                if c_fb is not None:
                    if c_fb[0] is cho_S_trial_bufs[pos]:
                        cho_S_bufs[pos], cho_S_trial_bufs[pos] = cho_S_trial_bufs[pos], cho_S_bufs[pos]
                    cho_S_psd[pos] = c_fb

        while alpha_d > 1e-12:
            lp_d_ok = True
            if q_lp > 0:
                assert z_lp is not None and dz_lp is not None and z_lp_trial is not None
                np.multiply(dz_lp, alpha_d, out=z_lp_trial)
                z_lp_trial += z_lp
                lp_d_ok = bool(np.all(np.isfinite(z_lp_trial)) and np.all(z_lp_trial > 0.0))
            if lp_d_ok:
                psd_d_ok = True
                cho_d_trial: list[tuple[np.ndarray, bool]] = []
                for pos in range(n_psd_blocks):
                    np.multiply(dZ_psd_bufs[pos], alpha_d, out=tmp1_bufs[pos])
                    tmp1_bufs[pos] += Z_psd_list[pos]
                    _sym_into(tmp1_bufs[pos], Z_trial_bufs[pos])
                    c_d = _safe_cholesky_buf(Z_trial_bufs[pos], cho_Z_trial_bufs[pos])
                    if c_d is None:
                        psd_d_ok = False
                        break
                    cho_d_trial.append(c_d)
                if psd_d_ok:
                    if q_lp > 0:
                        assert z_lp is not None and z_lp_trial is not None
                        np.copyto(z_lp, z_lp_trial)
                    for pos in range(n_psd_blocks):
                        np.copyto(Z_psd_list[pos], Z_trial_bufs[pos])
                        if cho_d_trial[pos][0] is cho_Z_trial_bufs[pos]:
                            cho_Z_bufs[pos], cho_Z_trial_bufs[pos] = cho_Z_trial_bufs[pos], cho_Z_bufs[pos]
                        cho_Z_psd[pos] = cho_d_trial[pos]
                    break
            alpha_d *= 0.5

        step_norm = float(alpha_p * np.linalg.norm(dz))
        history.append(
            IterationRecord(
                iteration=it,
                phase=phase_label,
                mu=mu,
                primal_obj=primal_obj,
                dual_obj=dual_obj,
                duality_gap=gap,
                dual_residual_rel=r_d_rel,
                eq_residual_rel=0.0,
                min_eig_primal=min_eig_p,
                min_eig_dual=min_eig_d,
                alpha_primal=alpha_p,
                alpha_dual=alpha_d,
                kkt_condition_number=cond_H,
                sigma=sigma,
                step_norm=step_norm,
            )
        )
        _record_iter_log(alpha_p)

        # Detecção de divergência ilimitada ao longo de raio factível
        if check_farkas_on_blocks is None:
            np.subtract(z, z0_initial, out=m_scratch)
            disp_norm = float(np.linalg.norm(m_scratch))
            if disp_norm > unbounded_norm_threshold and float(np.dot(c_vec, m_scratch)) < -1e-6 * c_scale * disp_norm:
                d_cand = m_scratch / disp_norm
                min_lin = float("inf")
                if q_lp > 0:
                    assert lp_vec_buf is not None
                    if use_sparse_lp:
                        assert F_lp_csr is not None
                        lp_vec_buf[:] = F_lp_csr @ d_cand
                    else:
                        assert F_lp_dense is not None
                        np.matmul(F_lp_dense, d_cand, out=lp_vec_buf)
                    min_lin = min(min_lin, float(np.min(lp_vec_buf)))
                for blk in psd_blocks:
                    min_lin = min(min_lin, float(np.min(np.linalg.eigvalsh(blk.evaluate_linear(d_cand)))))
                if min_lin >= -1e-8:
                    recession_candidate = d_cand.copy()
                    solver_status = "dual_infeasible"
                    break

        # Em Fase I, interromper se ||z|| divergir sem encontrar interior (típico de weak infeasibility)
        if check_farkas_on_blocks is not None and m > 1:
            if float(np.linalg.norm(z[: m - 1])) > max(1e9, 100.0 * unbounded_norm_threshold):
                np.copyto(m_scratch, z)
                m_scratch[m - 1] = 0.0
                orig_min_now = float("inf")
                if lp_check_pos.size > 0:
                    assert F0_lp is not None and lp_vec_buf is not None
                    if use_sparse_lp:
                        assert F_lp_csr is not None
                        lp_vec_buf[:] = F_lp_csr @ m_scratch
                    else:
                        assert F_lp_dense is not None
                        np.matmul(F_lp_dense, m_scratch, out=lp_vec_buf)
                    lp_vec_buf += F0_lp
                    orig_min_now = min(orig_min_now, float(np.min(lp_vec_buf[lp_check_pos])))
                for pos in psd_check_pos:
                    psd_blocks[pos].evaluate_into(m_scratch, tmp2_bufs[pos], tmp1_bufs[pos])
                    orig_min_now = min(orig_min_now, float(np.min(np.linalg.eigvalsh(tmp2_bufs[pos]))))
                if orig_min_now <= 0.0:
                    solver_status = "max_iterations"
                    break

        if step_norm <= 1e-14 * (1.0 + float(np.linalg.norm(z))) and max(rel_gap, comp_rel) <= 10.0 * tol_gap:
            solver_status = "optimal" if r_d_rel <= 10.0 * tol_feas else "optimal_inaccurate"
            break

    # Desempacotar multiplicadores duais escalares 1D de volta para matrizes 1x1 na ordem original
    Z_list: list[np.ndarray] = [None] * n_blocks  # type: ignore[list-item]
    if q_lp > 0:
        assert z_lp is not None
        for pos, orig_i in enumerate(lp_indices):
            Z_list[orig_i] = np.array([[float(z_lp[pos])]], dtype=np.float64)
    for pos, orig_i in enumerate(psd_indices):
        Z_list[orig_i] = Z_psd_list[pos].copy()

    # Polimento final do certificado dual no subespaço estacionário sum_b <F_{b,j}, Z_b> = c_j
    if solver_status in ("optimal", "optimal_inaccurate", "max_iterations"):
        W_final: list[np.ndarray] = [None] * n_blocks  # type: ignore[list-item]
        if q_lp > 0:
            assert s_lp is not None
            for pos, orig_i in enumerate(lp_indices):
                W_final[orig_i] = np.array([[1.0 / max(float(s_lp[pos]), 1e-30)]], dtype=np.float64)
        for pos, orig_i in enumerate(psd_indices):
            W_final[orig_i] = _cho_solve_mat(cho_S_psd[pos], eye_psd[pos])

        Z_pol = _project_dual_onto_subspace(blocks, m, Z_list, c_vec, weight_mats=W_final)
        if Z_pol is None:
            W_damped = [_sym(Z_b + 1e-4 * np.eye(b.dim, dtype=np.float64)) for b, Z_b in zip(blocks, Z_list, strict=True)]
            Z_pol = _project_dual_onto_subspace(blocks, m, Z_list, c_vec, weight_mats=W_damped)
        if Z_pol is not None:
            Z_list = Z_pol

        S_eval_final = [b.evaluate(z) for b in blocks]
        min_eig_p = min(_min_eig_sym(S_ev) for S_ev in S_eval_final)
        primal_obj = float(np.dot(c_vec, z) + c0)
        dual_obj = float(c0 - sum(float(np.sum(blk.F0 * Z_b)) for blk, Z_b in zip(blocks, Z_list, strict=True)))
        rel_gap = abs(primal_obj - dual_obj) / (1.0 + abs(primal_obj) + abs(dual_obj))
        adj.fill(0.0)
        dual_scale = 1.0 + c_norm
        for blk, Z_b in zip(blocks, Z_list, strict=True):
            if blk._active_keys.size > 0:
                adj[blk._active_keys] += blk._F_cols.T @ Z_b.ravel()
                dual_scale += blk._f_norm_sum * float(np.linalg.norm(Z_b, "fro"))
        r_d_rel = float(np.linalg.norm(c_vec - adj) / dual_scale)
        if min_eig_p >= -1e-7 and r_d_rel <= 1e-6 and rel_gap <= 1e-6:
            solver_status = "optimal"
        elif min_eig_p >= -1e-5 and r_d_rel <= 1e-4 and rel_gap <= 1e-4:
            solver_status = "optimal_inaccurate"
    else:
        S_eval_final = [b.evaluate(z) for b in blocks]

    # Liberar explicitamente buffers temporários do workspace para coleta imediata no heap wasm32
    del (
        H,
        H_scaled_buf,
        H_work_buf,
        inv_d_buf,
        adj,
        r_d,
        rhs_aff,
        rhs_cor,
        dz_aff,
        dz,
        z_trial,
        rhs_scaled_buf,
        res_s_buf,
        m_scratch,
        F_lp_dense,
        F_lp_scaled,
        F_lp_csr,
        F_lp_csc,
        F0_lp,
        f_lp_row_norms,
        s_lp,
        z_lp,
        s_lp_eval,
        s_lp_trial,
        z_lp_trial,
        rp_lp,
        s_lp_safe,
        w_lp,
        ds_lp_aff,
        dz_lp_aff,
        rc_lp,
        ds_lp,
        dz_lp,
        lp_vec_buf,
        lp_vec_buf2,
        cols_bufs,
        gram_bufs,
        S_psd_list,
        Z_psd_list,
        S_eval_bufs,
        S_trial_bufs,
        Z_trial_bufs,
        cho_S_bufs,
        cho_S_trial_bufs,
        cho_Z_bufs,
        cho_Z_trial_bufs,
        cho_S_psd,
        cho_Z_psd,
        R_p_psd_bufs,
        R_p_hat_bufs,
        dS_tilde_aff_bufs,
        dZ_tilde_aff_bufs,
        M_cor_bufs,
        dZ_psd_bufs,
        tmp1_bufs,
        tmp2_bufs,
        act_vec_bufs,
        G_invT_psd,
        lam_psd,
        eye_psd,
        diag_psd,
    )

    return {
        "solver_status": solver_status,
        "z": z,
        "Z_list": Z_list,
        "S_list": S_eval_final,
        "farkas_candidate": farkas_candidate,
        "recession_candidate": recession_candidate,
        "history": history,
        "iteration_log": iter_log,
    }


@dataclass(frozen=True)
class _BlockDecompositionPlan:
    """Plano de decomposição exata por componentes conexas de esparsidade agregada.

    Referências:
    - Garstka, Cannon & Goulart, IFAC 2020 (doi:10.1016/j.ifacol.2020.12.1255)
    - Goulart & Chen, 2024 (arXiv:2405.12762, Clarabel)
    """

    decomposed_blocks: list[_InternalConeBlock]
    reconstruction: list[tuple[int, list[tuple[int, np.ndarray]]]]
    n_original_blocks: int
    n_decomposed_blocks: int
    decomposed_block_indices: tuple[int, ...]

    def reassemble_duals(self, sub_duals: Sequence[np.ndarray]) -> list[np.ndarray]:
        """Reconstrói matrizes duais Z_b na dimensão original a partir dos sub-blocos."""
        assembled: list[np.ndarray] = []
        for orig_dim, mapping in self.reconstruction:
            if (
                len(mapping) == 1
                and mapping[0][1].size == orig_dim
                and np.array_equal(mapping[0][1], np.arange(orig_dim, dtype=np.intp))
            ):
                assembled.append(_sym(sub_duals[mapping[0][0]]))
            else:
                Z_full = np.zeros((orig_dim, orig_dim), dtype=np.float64)
                for sub_idx, verts in mapping:
                    Z_full[np.ix_(verts, verts)] = _sym(sub_duals[sub_idx])
                assembled.append(_sym(Z_full))
        return assembled


def _decompose_sparse_psd_blocks(
    blocks: Sequence[_InternalConeBlock],
) -> _BlockDecompositionPlan:
    """Decompõe blocos PSD com dim >= 4 em componentes conexas de esparsidade agregada.

    Constrói o grafo não-direcionado de esparsidade agregada sobre {0..dim-1} a partir da
    união das entradas não-nulas fora da diagonal de F0 e de todos os F_k. Se houver C > 1
    componentes conexas V_1, ..., V_C, divide o bloco em C blocos PSD independentes sem
    introduzir variáveis extras (equivalência exata), registrando o mapa de reconstrução
    para remontar Z_b[np.ix_(V_c, V_c)] = Z_sub_c após a solução.

    Referências:
    - Garstka, Cannon & Goulart, IFAC 2020 (10.1016/j.ifacol.2020.12.1255)
    - Goulart & Chen, 2024 (arXiv:2405.12762)
    """
    decomposed_blocks: list[_InternalConeBlock] = []
    reconstruction: list[tuple[int, list[tuple[int, np.ndarray]]]] = []
    decomposed_indices: list[int] = []

    for orig_idx, blk in enumerate(blocks):
        if blk.is_ineq_slack or blk.dim < 4:
            sub_idx = len(decomposed_blocks)
            decomposed_blocks.append(blk)
            reconstruction.append((blk.dim, [(sub_idx, np.arange(blk.dim, dtype=np.intp))]))
            continue

        dim = blk.dim
        adj = np.abs(blk.F0) > 0.0
        for fk in blk.F_terms.values():
            adj |= np.abs(fk) > 0.0
        adj |= adj.T

        visited = [False] * dim
        components: list[np.ndarray] = []
        for start in range(dim):
            if visited[start]:
                continue
            comp: list[int] = []
            stack = [start]
            visited[start] = True
            while stack:
                node = stack.pop()
                comp.append(node)
                neighbors = np.flatnonzero(adj[node])
                for nb in neighbors:
                    nb_i = int(nb)
                    if not visited[nb_i]:
                        visited[nb_i] = True
                        stack.append(nb_i)
            comp.sort()
            components.append(np.asarray(comp, dtype=np.intp))

        components.sort(key=lambda arr: int(arr[0]))
        if len(components) <= 1:
            sub_idx = len(decomposed_blocks)
            decomposed_blocks.append(blk)
            reconstruction.append((dim, [(sub_idx, np.arange(dim, dtype=np.intp))]))
            continue

        decomposed_indices.append(orig_idx)
        mapping: list[tuple[int, np.ndarray]] = []
        for c_idx, verts in enumerate(components):
            sub_F0 = _sym(blk.F0[np.ix_(verts, verts)])
            sub_F_terms: dict[int, np.ndarray] = {}
            for j, fj in blk.F_terms.items():
                sub_fj = _sym(fj[np.ix_(verts, verts)])
                if np.any(sub_fj != 0.0):
                    sub_F_terms[j] = sub_fj
            sub_idx = len(decomposed_blocks)
            decomposed_blocks.append(
                _InternalConeBlock(
                    name=f"{blk.name}__cc{c_idx}",
                    dim=int(verts.size),
                    F0=sub_F0,
                    F_terms=sub_F_terms,
                    is_ineq_slack=blk.is_ineq_slack,
                    ineq_index=blk.ineq_index,
                )
            )
            mapping.append((sub_idx, verts))
        reconstruction.append((dim, mapping))

    return _BlockDecompositionPlan(
        decomposed_blocks=decomposed_blocks,
        reconstruction=reconstruction,
        n_original_blocks=len(blocks),
        n_decomposed_blocks=len(decomposed_blocks),
        decomposed_block_indices=tuple(decomposed_indices),
    )


def _ruiz_equilibrate_blocks(
    blocks: Sequence[_InternalConeBlock],
    c_y: np.ndarray,
    m_y: int,
    *,
    max_sweeps: int = 5,
    min_scale: float = 1e-4,
    max_scale: float = 1e4,
) -> tuple[list[_InternalConeBlock], np.ndarray, np.ndarray, np.ndarray]:
    """Equilibração de Ruiz multi-varredura com recorte (Clarabel §2.4 & §2.6).

    Executa até `max_sweeps` (padrão 5) varreduras equilibrando simultaneamente as normas
    de Frobenius dos blocos (`e_b`) e das colunas das variáveis de decisão (`d_j`), com
    fatores cumulativos recortados em `[min_scale, max_scale]` = `[1e-4, 1e4]`.

    Transformação exata:
        y = diag(d) y_tilde,   c_tilde = diag(d) c_y
        F_tilde_b(y_tilde) = e_b F_b(diag(d) y_tilde) >= 0
        Z_b = e_b Z_tilde_b    (preserva estacionariedade dual, gap e certificados de Farkas)

    Referências:
    - Goulart & Chen, 2024 (arXiv:2405.12762, Clarabel §2.4 & §2.6)
    - Garstka, Cannon & Goulart, IFAC 2020 (10.1016/j.ifacol.2020.12.1255)
    """
    n_blk = len(blocks)
    e = np.ones((n_blk,), dtype=np.float64)
    d = np.ones((m_y,), dtype=np.float64)

    if n_blk == 0:
        return list(blocks), c_y.copy(), e, d

    f0_norms = np.array([float(np.linalg.norm(b.F0, "fro")) for b in blocks], dtype=np.float64)
    M = np.zeros((n_blk, m_y), dtype=np.float64)
    for b_idx, b in enumerate(blocks):
        for j, fj in b.F_terms.items():
            M[b_idx, j] = float(np.linalg.norm(fj, "fro"))

    for _ in range(max_sweeps):
        M_cur = (e[:, None] * M) * d[None, :]
        f0_cur = e * f0_norms

        if m_y > 0:
            row_norms = np.maximum(f0_cur, np.max(M_cur, axis=1))
            col_norms = np.max(M_cur, axis=0)
        else:
            row_norms = f0_cur
            col_norms = np.zeros((0,), dtype=np.float64)

        delta_e = np.where(row_norms > 1e-12, 1.0 / np.sqrt(np.maximum(row_norms, 1e-30)), 1.0)
        delta_d = np.where(col_norms > 1e-12, 1.0 / np.sqrt(np.maximum(col_norms, 1e-30)), 1.0)

        e_new = np.clip(e * delta_e, min_scale, max_scale)
        d_new = np.clip(d * delta_d, min_scale, max_scale)

        rel_e = float(np.max(np.abs(e_new / e - 1.0))) if n_blk > 0 else 0.0
        rel_d = float(np.max(np.abs(d_new / d - 1.0))) if m_y > 0 else 0.0
        e, d = e_new, d_new
        if max(rel_e, rel_d) < 1e-3:
            break

    scaled_blocks: list[_InternalConeBlock] = []
    for b_idx, b in enumerate(blocks):
        eb = float(e[b_idx])
        scaled_blocks.append(
            _InternalConeBlock(
                name=b.name,
                dim=b.dim,
                F0=b.F0 * eb,
                F_terms={j: fj * (eb * float(d[j])) for j, fj in b.F_terms.items()},
                is_ineq_slack=b.is_ineq_slack,
                ineq_index=b.ineq_index,
            )
        )
    c_y_eq = d * c_y
    return scaled_blocks, c_y_eq, e, d


def solve_native_raw(
    problem: CanonicalSDPProblem,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve CanonicalSDPProblem pelo método didático de Pontos Interiores Primal-Dual.

    Retorna dicionário compatível com `SDPBackend.solve_raw` e `verify()`, enriquecido
    com o histórico completo do caminho central (`history`, `phase1_summary`, `phase2_summary`).
    """
    if not isinstance(problem, CanonicalSDPProblem):
        raise ValidationError(
            f"solve_native_raw requer CanonicalSDPProblem, recebido {type(problem).__name__}."
        )
    cfg = NativeSolverConfig.from_options(options)
    t_start = time.perf_counter()
    iteration_log: list[dict[str, Any]] = []
    opt_cb = options.get("progress_callback") if isinstance(options, Mapping) else None
    progress_cb = opt_cb if callable(opt_cb) else get_progress_callback()

    n_vars = problem.n_vars
    n_psd = problem.n_blocks
    n_eq = problem.n_eq
    n_ineq = problem.n_ineq
    c_orig = problem.c.copy()
    c0_orig = float(problem.c0)
    warnings_out: list[WarningItem] = []

    # -----------------------------------------------------------------------
    # Passo 1: Redução de igualdades lineares E x = d via SVD (sem inv!)
    # -----------------------------------------------------------------------
    if n_eq > 0:
        U_eq, s_eq, Vt_eq = scipy.linalg.svd(problem.E, full_matrices=True, check_finite=True)
        s_max_eq = float(s_eq[0]) if s_eq.size > 0 else 0.0
        rank_eq = int(np.sum(s_eq > 1e-12 * max(1.0, s_max_eq)))
        x_eq = np.zeros((n_vars,), dtype=np.float64)
        for i in range(rank_eq):
            coeff = float(np.dot(U_eq[:, i], problem.d)) / float(s_eq[i])
            x_eq = x_eq + coeff * Vt_eq[i, :]
        res_eq = problem.E @ x_eq - problem.d
        if float(np.linalg.norm(res_eq)) > 1e-8 * (1.0 + float(np.linalg.norm(problem.d))):
            nu_farkas = -res_eq
            if float(np.dot(problem.d, nu_farkas)) > 0.0:
                nu_farkas = -nu_farkas
            return {
                "backend": "native_primal_dual",
                "maturity": "beta",
                "experimental": False,
                "method": "primal_dual_nt_mehrotra_interior_point",
                "solver_status": "primal_infeasible",
                "raw_status": "algebraic_equality_infeasible",
                "iterations": 0,
                "solve_time": float(time.perf_counter() - t_start),
                "objective": None,
                "farkas_Z": [np.zeros((b.dim, b.dim), dtype=np.float64) for b in problem.blocks],
                "farkas_eq": nu_farkas,
                "farkas_ineq": np.zeros((n_ineq,), dtype=np.float64) if n_ineq > 0 else None,
                "history": [],
                "iteration_log": iteration_log,
                "warnings": warnings_out,
            }
        N_eq = Vt_eq[rank_eq:, :].T  # (n_vars, n_vars - rank_eq)
    else:
        U_eq = np.zeros((0, 0), dtype=np.float64)
        s_eq = np.zeros((0,), dtype=np.float64)
        Vt_eq = np.eye(n_vars, dtype=np.float64)
        rank_eq = 0
        x_eq = np.zeros((n_vars,), dtype=np.float64)
        N_eq = np.eye(n_vars, dtype=np.float64)

    def _recover_eq_dual(adj_full: np.ndarray, rhs_c: np.ndarray) -> np.ndarray | None:
        """Recupera multiplicador nu de E^T nu = adj_full - rhs_c via SVD de E."""
        if n_eq == 0:
            return None
        diff = adj_full - rhs_c
        nu = np.zeros((n_eq,), dtype=np.float64)
        for i in range(rank_eq):
            proj = float(np.dot(Vt_eq[i, :], diff)) / float(s_eq[i])
            nu = nu + proj * U_eq[:, i]
        return nu

    # -----------------------------------------------------------------------
    # Passo 2: Construir blocos cônicos internos no subespaço y (x = x_eq + N_eq y)
    # -----------------------------------------------------------------------
    m_y = int(N_eq.shape[1])
    c_y = N_eq.T @ c_orig
    c0_y = c0_orig + float(np.dot(c_orig, x_eq))

    y_blocks: list[_InternalConeBlock] = []
    if n_eq == 0:
        for blk in problem.blocks:
            F0_y = blk.F0.copy()
            F_terms_y = {
                j: fk.copy()
                for j, fk in blk.F_terms.items()
                if float(np.linalg.norm(fk, "fro")) > 1e-15
            }
            y_blocks.append(_InternalConeBlock(name=blk.name, dim=blk.dim, F0=F0_y, F_terms=F_terms_y))
    else:
        for blk in problem.blocks:
            F0_y = blk.evaluate(x_eq)
            F_terms_y = {}
            for j in range(m_y):
                mat_j = blk.evaluate_linear(N_eq[:, j])
                if float(np.linalg.norm(mat_j, "fro")) > 1e-15:
                    F_terms_y[j] = mat_j
            y_blocks.append(_InternalConeBlock(name=blk.name, dim=blk.dim, F0=F0_y, F_terms=F_terms_y))

    for i_idx in range(n_ineq):
        h_row = problem.H[i_idx, :]
        h_val = float(problem.h[i_idx]) if n_eq == 0 else float(problem.h[i_idx] - np.dot(h_row, x_eq))
        F0_ineq = np.array([[h_val]], dtype=np.float64)
        h_y = -h_row if n_eq == 0 else -(N_eq.T @ h_row)
        nz_cols = np.flatnonzero(np.abs(h_y) > 1e-15)
        F_terms_ineq: dict[int, np.ndarray] = {
            int(j): np.array([[float(h_y[j])]], dtype=np.float64) for j in nz_cols
        }
        y_blocks.append(
            _InternalConeBlock(
                name=f"ineq_{i_idx}",
                dim=1,
                F0=F0_ineq,
                F_terms=F_terms_ineq,
                is_ineq_slack=True,
                ineq_index=i_idx,
            )
        )

    def _split_duals(Z_all: Sequence[np.ndarray]) -> tuple[list[np.ndarray], np.ndarray | None]:
        dZ = [_sym(Z_all[i]) for i in range(n_psd)]
        d_ineq = (
            np.array([float(Z_all[n_psd + i][0, 0]) for i in range(n_ineq)], dtype=np.float64)
            if n_ineq > 0
            else None
        )
        return dZ, d_ineq

    def _full_adjoint_x(Z_all: Sequence[np.ndarray], d_ineq: np.ndarray | None) -> np.ndarray:
        adj_x = np.zeros((n_vars,), dtype=np.float64)
        for blk, Z_b in zip(problem.blocks, Z_all[:n_psd], strict=True):
            for k, fk in blk.F_terms.items():
                adj_x[k] += float(np.sum(fk * Z_b))
        if d_ineq is not None and n_ineq > 0:
            adj_x = adj_x - (problem.H.T @ d_ineq)
        return adj_x

    if len(y_blocks) == 0:
        if float(np.linalg.norm(c_y)) <= 1e-12:
            nu_opt = _recover_eq_dual(np.zeros((n_vars,), dtype=np.float64), c_orig)
            return {
                "backend": "native_primal_dual",
                "maturity": "beta",
                "experimental": False,
                "method": "primal_dual_nt_mehrotra_interior_point",
                "solver_status": "optimal",
                "raw_status": "unconstrained_nullspace_optimal",
                "iterations": 0,
                "solve_time": float(time.perf_counter() - t_start),
                "x": x_eq,
                "objective": c0_y,
                "dual_Z": [],
                "dual_eq": nu_opt,
                "dual_ineq": None,
                "history": [],
                "iteration_log": iteration_log,
                "warnings": warnings_out,
            }
        d_ray = -(N_eq @ (c_y / float(np.linalg.norm(c_y))))
        return {
            "backend": "native_primal_dual",
            "maturity": "beta",
            "experimental": False,
            "method": "primal_dual_nt_mehrotra_interior_point",
            "solver_status": "dual_infeasible",
            "raw_status": "unconstrained_nullspace_unbounded",
            "iterations": 0,
            "solve_time": float(time.perf_counter() - t_start),
            "objective": None,
            "feasible_x0": x_eq,
            "recession_direction": d_ray,
            "history": [],
            "iteration_log": iteration_log,
            "warnings": warnings_out,
        }

    if m_y == 0:
        min_eigs = [float(np.min(np.linalg.eigvalsh(b.F0))) for b in y_blocks]
        if min(min_eigs) >= -cfg.tol_psd:
            Z_zero = [np.zeros((b.dim, b.dim), dtype=np.float64) for b in y_blocks]
            dZ, d_ineq = _split_duals(Z_zero)
            nu_opt = _recover_eq_dual(np.zeros((n_vars,), dtype=np.float64), c_orig)
            return {
                "backend": "native_primal_dual",
                "maturity": "beta",
                "experimental": False,
                "method": "primal_dual_nt_mehrotra_interior_point",
                "solver_status": "optimal",
                "raw_status": "fixed_by_equalities_optimal",
                "iterations": 0,
                "solve_time": float(time.perf_counter() - t_start),
                "x": x_eq,
                "objective": c0_y,
                "dual_Z": dZ,
                "dual_eq": nu_opt,
                "dual_ineq": d_ineq,
                "history": [],
                "iteration_log": iteration_log,
                "warnings": warnings_out,
            }
        b_bad = int(np.argmin(min_eigs))
        evals, evecs = np.linalg.eigh(y_blocks[b_bad].F0)
        v_bad = evecs[:, 0:1]
        Z_farkas_all = [np.zeros((b.dim, b.dim), dtype=np.float64) for b in y_blocks]
        Z_farkas_all[b_bad] = v_bad @ v_bad.T
        fZ, f_ineq = _split_duals(Z_farkas_all)
        adj_f = _full_adjoint_x(Z_farkas_all, f_ineq)
        f_eq = _recover_eq_dual(adj_f, np.zeros((n_vars,), dtype=np.float64))
        return {
            "backend": "native_primal_dual",
            "maturity": "beta",
            "experimental": False,
            "method": "primal_dual_nt_mehrotra_interior_point",
            "solver_status": "primal_infeasible",
            "raw_status": "fixed_by_equalities_infeasible",
            "iterations": 0,
            "solve_time": float(time.perf_counter() - t_start),
            "objective": None,
            "farkas_Z": fZ,
            "farkas_eq": f_eq,
            "farkas_ineq": f_ineq,
            "history": [],
            "iteration_log": iteration_log,
            "warnings": warnings_out,
        }

    # -----------------------------------------------------------------------
    # Passo 2.4: Decomposição de blocos PSD por esparsidade agregada
    # (Garstka, Cannon & Goulart, IFAC 2020; Goulart & Chen, 2024, arXiv:2405.12762)
    # -----------------------------------------------------------------------
    decomp_plan = _decompose_sparse_psd_blocks(y_blocks)
    y_blocks_dec = decomp_plan.decomposed_blocks
    decomposition_summary = {
        "n_original_blocks": decomp_plan.n_original_blocks,
        "n_decomposed_blocks": decomp_plan.n_decomposed_blocks,
        "decomposed_block_indices": list(decomp_plan.decomposed_block_indices),
    }

    # -----------------------------------------------------------------------
    # Passo 2.5: Equilibração de Ruiz multi-varredura com recorte [1e-4, 1e4]
    # (Goulart & Chen, 2024, arXiv:2405.12762, Clarabel §2.4 & §2.6)
    # Desescala tanto primal x (via d_ruiz) quanto dual Z_b = e_b * Z'_b e
    # remonta blocos decompostos antes da auditoria independente no problema original.
    # -----------------------------------------------------------------------
    y_blocks_eq, c_y_eq, e_ruiz, d_ruiz = _ruiz_equilibrate_blocks(
        y_blocks_dec,
        c_y,
        m_y,
        max_sweeps=5,
        min_scale=1e-4,
        max_scale=1e4,
    )

    def _unscale_and_reassemble_duals(Z_sub_scaled: Sequence[np.ndarray]) -> list[np.ndarray]:
        Z_sub_unscaled = [_sym(float(eb) * Z_b) for Z_b, eb in zip(Z_sub_scaled, e_ruiz, strict=True)]
        return decomp_plan.reassemble_duals(Z_sub_unscaled)

    # -----------------------------------------------------------------------
    # Passo 3: Equilíbrio de colunas preservando esparsidade ou SVD se rank-deficiente
    # -----------------------------------------------------------------------
    total_entries = sum(b.dim * b.dim for b in y_blocks_eq)
    A_cone = np.zeros((total_entries, m_y), dtype=np.float64)
    row_ofs = 0
    for b in y_blocks_eq:
        bsz = b.dim * b.dim
        if b._active_keys.size > 0:
            A_cone[row_ofs : row_ofs + bsz, b._active_keys] = b._F_cols
        row_ofs += bsz

    col_norms = np.linalg.norm(A_cone, axis=0)
    use_sparse_col_scaling = False
    if m_y > 0 and float(np.min(col_norms)) > 1e-12:
        A_col_scaled = A_cone / col_norms[None, :]
        G_cone = _sym(A_col_scaled.T @ A_col_scaled)
        cho_cone = _safe_cholesky(G_cone)
        if cho_cone is not None:
            diag_lc = np.abs(np.diag(cho_cone[0]))
            if diag_lc.size > 0 and float(np.max(diag_lc)) / max(float(np.min(diag_lc)), 1e-15) < 1e5:
                use_sparse_col_scaling = True

    if use_sparse_col_scaling:
        col_inv = 1.0 / col_norms
        Q_R = np.diag(col_inv)
        Q_N = np.zeros((m_y, 0), dtype=np.float64)
        m_z = m_y
        c_z = col_inv * c_y_eq
        c_null = np.zeros((0,), dtype=np.float64)
        z_blocks = [
            _InternalConeBlock(
                name=b.name,
                dim=b.dim,
                F0=b.F0,
                F_terms={j: fj * col_inv[j] for j, fj in b.F_terms.items()},
                is_ineq_slack=b.is_ineq_slack,
                ineq_index=b.ineq_index,
            )
            for b in y_blocks_eq
        ]

        def _project_y_to_z(y_vec: np.ndarray) -> np.ndarray:
            return col_norms * y_vec
    else:
        _, s_cone, Vt_cone = scipy.linalg.svd(A_cone, full_matrices=(total_entries < m_y), check_finite=True)
        s_cone_max = float(s_cone[0]) if s_cone.size > 0 else 0.0
        rank_cone = int(np.sum(s_cone > 1e-12 * max(1.0, s_cone_max)))
        # Escalar pelas inversas dos valores singulares para que as matrizes base em z sejam ortonormais
        Q_R = Vt_cone[:rank_cone, :].T / s_cone[:rank_cone]  # (m_y, rank_cone)
        Q_N = Vt_cone[rank_cone:, :].T                       # (m_y, m_y - rank_cone)

        m_z = rank_cone
        c_z = Q_R.T @ c_y_eq
        c_null = Q_N.T @ c_y_eq

        z_blocks = []
        for b in y_blocks_eq:
            F_terms_z: dict[int, np.ndarray] = {}
            for j in range(m_z):
                mat_j = b.evaluate_linear(Q_R[:, j])
                if float(np.linalg.norm(mat_j, "fro")) > 1e-15:
                    F_terms_z[j] = mat_j
            z_blocks.append(
                _InternalConeBlock(
                    name=b.name,
                    dim=b.dim,
                    F0=b.F0,
                    F_terms=F_terms_z,
                    is_ineq_slack=b.is_ineq_slack,
                    ineq_index=b.ineq_index,
                )
            )

        def _project_y_to_z(y_vec: np.ndarray) -> np.ndarray:
            return s_cone[:rank_cone] * (Vt_cone[:rank_cone, :] @ y_vec)

    del A_cone

    all_history: list[IterationRecord] = []
    phase1_summary: dict[str, Any] = {"executed": False, "iterations": 0, "status": "skipped", "warm_start_used": False}
    phase2_summary: dict[str, Any] = {"executed": False, "iterations": 0, "status": "skipped"}

    # -----------------------------------------------------------------------
    # Passo 4: Warm-Start (Ding et al., arXiv:2312.11801) ou Fase I
    # -----------------------------------------------------------------------
    z0 = np.zeros((m_z,), dtype=np.float64)
    warm_start_used = False
    if cfg.warm_start_x is not None:
        if len(cfg.warm_start_x) != n_vars:
            raise ValidationError(
                f"warm_start_x deve ter comprimento {n_vars}, recebido {len(cfg.warm_start_x)}."
            )
        x_ws = np.asarray(cfg.warm_start_x, dtype=np.float64)
        eq_err_ws = (
            float(np.linalg.norm(problem.E @ x_ws - problem.d)) / (1.0 + float(np.linalg.norm(problem.d)))
            if n_eq > 0
            else 0.0
        )
        min_eig_psd_ws = min(
            (_min_eig_sym(blk.evaluate(x_ws)) for blk in problem.blocks),
            default=float("inf"),
        )
        min_slack_ineq_ws = float(np.min(problem.h - problem.H @ x_ws)) if n_ineq > 0 else float("inf")
        if eq_err_ws <= 1e-8 and min(min_eig_psd_ws, min_slack_ineq_ws) > 1e-8:
            y_ws = N_eq.T @ (x_ws - x_eq)
            z_ws = _project_y_to_z(y_ws / d_ruiz)
            min_eig_z_ws = min(_min_eig_sym(b.evaluate(z_ws)) for b in z_blocks)
            if min_eig_z_ws > 1e-8:
                z0 = z_ws
                warm_start_used = True
                phase1_summary = {
                    "executed": False,
                    "iterations": 0,
                    "status": "skipped_warm_start",
                    "warm_start_used": True,
                }

    init_min_eig = min(_min_eig_sym(b.evaluate(z0)) for b in z_blocks)
    is_pure_feasibility = float(np.linalg.norm(c_z)) <= 1e-12 and float(np.linalg.norm(c_null)) <= 1e-12

    if not warm_start_used and (init_min_eig <= cfg.strict_margin or is_pure_feasibility):
        # Construir problema auxiliar de Fase I:
        #   min_{z, t}  t   s.t.   F_b(z) + t I_{n_b} >= 0,  t_cap + t >= 0
        # Se for problema de pura factibilidade (c=0), adicionar caixa suave sobre z para centralizar bem Q
        t_cap = 1.0
        p1_blocks: list[_InternalConeBlock] = []
        for b in z_blocks:
            terms_p1 = dict(b.F_terms)
            terms_p1[m_z] = np.eye(b.dim, dtype=np.float64)
            p1_blocks.append(_InternalConeBlock(name=b.name, dim=b.dim, F0=b.F0, F_terms=terms_p1))

        # Bloco de limitante inferior de t: t_cap + t >= 0
        p1_blocks.append(
            _InternalConeBlock(
                name="phase1_t_lower_bound",
                dim=1,
                F0=np.array([[t_cap]], dtype=np.float64),
                F_terms={m_z: np.array([[1.0]], dtype=np.float64)},
            )
        )

        t_init = max(1.0, -init_min_eig + 1.0)
        z_p1_init = np.zeros((m_z + 1,), dtype=np.float64)
        z_p1_init[m_z] = t_init
        c_p1 = np.zeros((m_z + 1,), dtype=np.float64)
        c_p1[m_z] = 1.0

        stop_margin = None if is_pure_feasibility else cfg.strict_margin
        p1_out = _run_primal_dual_cone_loop(
            p1_blocks,
            c_p1,
            0.0,
            z_p1_init,
            phase_label="phase1",
            max_iter=cfg.phase1_max_iter,
            tol_gap=cfg.tol_gap,
            tol_feas=cfg.tol_feas,
            step_fraction=cfg.step_fraction,
            sigma_min=cfg.sigma_min,
            sigma_max=cfg.sigma_max,
            stop_on_negative_obj_margin=stop_margin,
            check_farkas_on_blocks=len(z_blocks),
            unbounded_norm_threshold=cfg.unbounded_norm_threshold,
            t_start=t_start,
            iteration_log=iteration_log,
            progress_callback=progress_cb,
        )
        all_history.extend(p1_out["history"])
        phase1_summary = {
            "executed": True,
            "iterations": len(p1_out["history"]),
            "status": p1_out["solver_status"],
            "final_t": float(p1_out["z"][m_z]),
            "warm_start_used": False,
        }

        z_cand = p1_out["z"][:m_z]
        cand_min_eig = min(_min_eig_sym(b.evaluate(z_cand)) for b in z_blocks)

        if cand_min_eig > 0.0:
            z0 = z_cand
        else:
            farkas_Z_internal = p1_out.get("farkas_candidate")
            if farkas_Z_internal is None:
                orig_Z = p1_out["Z_list"][: len(z_blocks)]
                proj_Z = _project_dual_onto_subspace(
                    z_blocks,
                    m_z,
                    orig_Z,
                    np.zeros((m_z,), dtype=np.float64),
                )
                if proj_Z is not None:
                    Z_strict = _validate_strict_farkas_certificate(z_blocks, m_z, proj_Z)
                    if Z_strict is not None:
                        farkas_Z_internal = Z_strict

            if farkas_Z_internal is not None:
                farkas_Z_unscaled = _unscale_and_reassemble_duals(farkas_Z_internal)
                fZ, f_ineq = _split_duals(farkas_Z_unscaled)
                adj_f = _full_adjoint_x(farkas_Z_unscaled, f_ineq)
                f_eq = _recover_eq_dual(adj_f, np.zeros((n_vars,), dtype=np.float64))
                return {
                    "backend": "native_primal_dual",
                    "maturity": "beta",
                    "experimental": False,
                    "method": "primal_dual_nt_mehrotra_interior_point",
                    "solver_status": "primal_infeasible",
                    "raw_status": "phase1_infeasible_farkas",
                    "iterations": len(all_history),
                    "solve_time": float(time.perf_counter() - t_start),
                    "objective": None,
                    "farkas_Z": fZ,
                    "farkas_eq": f_eq,
                    "farkas_ineq": f_ineq,
                    "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
                    "iteration_log": iteration_log,
                    "phase1_summary": phase1_summary,
                    "phase2_summary": phase2_summary,
                    "decomposition_summary": decomposition_summary,
                    "warnings": warnings_out,
                }

            x_cand = x_eq + N_eq @ (d_ruiz * (Q_R @ z_cand))
            cand_feasible_bound = cand_min_eig >= -1e-12 and float(np.linalg.norm(z_cand)) <= cfg.unbounded_norm_threshold
            warnings_out.append(
                WarningItem(
                    code="EDUCATIONAL_PHASE1_INCONCLUSIVE",
                    message=(
                        "Fase I encerrou sem ponto estritamente interior e sem certificado de Farkas validado; "
                        "status reportado honestamente como max_iterations (sem falsa factibilidade)."
                    ),
                )
            )
            out_inc: dict[str, Any] = {
                "backend": "native_primal_dual",
                "maturity": "beta",
                "experimental": False,
                "method": "primal_dual_nt_mehrotra_interior_point",
                "solver_status": "max_iterations",
                "raw_status": "phase1_max_iterations_no_certificate",
                "iterations": len(all_history),
                "solve_time": float(time.perf_counter() - t_start),
                "objective": float(problem.evaluate_objective(x_cand)) if cand_feasible_bound else None,
                "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
                "iteration_log": iteration_log,
                "phase1_summary": phase1_summary,
                "phase2_summary": phase2_summary,
                "warnings": warnings_out,
            }
            if cand_feasible_bound:
                out_inc["x"] = x_cand
            return out_inc

    # -----------------------------------------------------------------------
    # Passo 5: Checar direções livres no núcleo N_cone (ex.: variável livre no objetivo)
    # -----------------------------------------------------------------------
    x_feas0 = x_eq + N_eq @ (d_ruiz * (Q_R @ z0))
    if float(np.linalg.norm(c_null)) > 1e-12:
        # Variável livre sem restrições com custo não nulo -> problema ilimitado certificado!
        d_y = d_ruiz * (-(Q_N @ (c_null / float(np.linalg.norm(c_null)))))
        d_x = N_eq @ d_y
        return {
            "backend": "native_primal_dual",
            "maturity": "beta",
            "experimental": False,
            "method": "primal_dual_nt_mehrotra_interior_point",
            "solver_status": "dual_infeasible",
            "raw_status": "nullspace_recession_unbounded",
            "iterations": len(all_history),
            "solve_time": float(time.perf_counter() - t_start),
            "objective": None,
            "feasible_x0": x_feas0,
            "recession_direction": d_x,
            "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
            "iteration_log": iteration_log,
            "phase1_summary": phase1_summary,
            "phase2_summary": phase2_summary,
            "decomposition_summary": decomposition_summary,
            "warnings": warnings_out,
        }

    # Se o problema for de pura factibilidade reduzida (c_z == 0 e c_null == 0), z0 já é estritamente factível!
    if is_pure_feasibility:
        Z_zero = [np.zeros((b.dim, b.dim), dtype=np.float64) for b in y_blocks]
        dZ, d_ineq = _split_duals(Z_zero)
        nu_feas = _recover_eq_dual(np.zeros((n_vars,), dtype=np.float64), c_orig)
        return {
            "backend": "native_primal_dual",
            "maturity": "beta",
            "experimental": False,
            "method": "primal_dual_nt_mehrotra_interior_point",
            "solver_status": "optimal",
            "raw_status": "phase1_strictly_feasible_analytic_center",
            "iterations": len(all_history),
            "solve_time": float(time.perf_counter() - t_start),
            "x": x_feas0,
            "objective": float(problem.evaluate_objective(x_feas0)),
            "dual_Z": dZ,
            "dual_eq": nu_feas,
            "dual_ineq": d_ineq,
            "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
            "iteration_log": iteration_log,
            "phase1_summary": phase1_summary,
            "phase2_summary": phase2_summary,
            "decomposition_summary": decomposition_summary,
            "warnings": warnings_out,
        }

    # -----------------------------------------------------------------------
    # Passo 6: Fase II — Seguimento de Caminho Primal-Dual até a Otimalidade
    # -----------------------------------------------------------------------
    p2_out = _run_primal_dual_cone_loop(
        z_blocks,
        c_z,
        c0_y,
        z0,
        phase_label="phase2",
        max_iter=cfg.max_iter,
        tol_gap=cfg.tol_gap,
        tol_feas=cfg.tol_feas,
        step_fraction=cfg.step_fraction,
        sigma_min=cfg.sigma_min,
        sigma_max=cfg.sigma_max,
        stop_on_negative_obj_margin=None,
        check_farkas_on_blocks=None,
        unbounded_norm_threshold=cfg.unbounded_norm_threshold,
        t_start=t_start,
        iteration_log=iteration_log,
        progress_callback=progress_cb,
    )
    all_history.extend(p2_out["history"])
    p2_status = str(p2_out["solver_status"])
    phase2_summary = {
        "executed": True,
        "iterations": len(p2_out["history"]),
        "status": p2_status,
    }

    if p2_status == "dual_infeasible":
        d_z = p2_out["recession_candidate"]
        d_x = N_eq @ (d_ruiz * (Q_R @ d_z)) if d_z is not None else None
        return {
            "backend": "native_primal_dual",
            "maturity": "beta",
            "experimental": False,
            "method": "primal_dual_nt_mehrotra_interior_point",
            "solver_status": "dual_infeasible",
            "raw_status": "phase2_recession_unbounded",
            "iterations": len(all_history),
            "solve_time": float(time.perf_counter() - t_start),
            "objective": None,
            "feasible_x0": x_feas0,
            "recession_direction": d_x,
            "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
            "iteration_log": iteration_log,
            "phase1_summary": phase1_summary,
            "phase2_summary": phase2_summary,
            "decomposition_summary": decomposition_summary,
            "warnings": warnings_out,
        }

    z_final = p2_out["z"]
    x_final = x_eq + N_eq @ (d_ruiz * (Q_R @ z_final))
    Z_final_all = _unscale_and_reassemble_duals(p2_out["Z_list"])
    dZ, d_ineq = _split_duals(Z_final_all)
    adj_x = _full_adjoint_x(Z_final_all, d_ineq)
    d_eq = _recover_eq_dual(adj_x, c_orig)
    obj_final = float(problem.evaluate_objective(x_final))

    if p2_status == "optimal_inaccurate":
        warnings_out.append(
            WarningItem(
                code="EDUCATIONAL_SOLVER_INACCURATE",
                message="Solver primal-dual educacional convergiu com precisão reduzida (optimal_inaccurate).",
            )
        )

    return {
        "backend": "native_primal_dual",
        "maturity": "beta",
        "experimental": False,
        "method": "primal_dual_nt_mehrotra_interior_point",
        "solver_status": p2_status,
        "raw_status": f"phase2_{p2_status}",
        "iterations": len(all_history),
        "solve_time": float(time.perf_counter() - t_start),
        "x": x_final,
        "objective": obj_final,
        "dual_Z": dZ,
        "dual_eq": d_eq,
        "dual_ineq": d_ineq,
        "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
        "iteration_log": iteration_log,
        "phase1_summary": phase1_summary,
        "phase2_summary": phase2_summary,
        "decomposition_summary": decomposition_summary,
        "warnings": warnings_out,
    }
