r"""Motor de Transformação por Elementos Finitos (FEMT v1.2.0) — Frente F5 (CL-TS-MOD-DIR-001 Seções 5 e 6).

Implementa em NumPy/SciPy puro (100% compatível com Pyodide `wasm32`, ZERO `linalg.inv`, ZERO `eval`/`exec`):
- Partição estrutural $\mathcal{I}_{\text{const}} \sqcup \mathcal{I}_{\text{var}}$ preservando bit-a-bit todas as
  entradas constantes da planta qLPV nos vértices;
- Extração da média amostral $\bar{x}_{\text{var}}$, SVD econômica centrada sobre as flutuações $\Delta X_{\text{var}}$
  com erro exato de Eckart–Young–Mirsky e aumento ortonormal pelo vetor de pesos uniformes $\frac{1}{N_g}\mathbf{1}_{N_g}$
  garantindo `rank_augmented == False` em `SN-NN`;
- Manipulação do fecho convexo global sobre o subespaço variante reutilizando `sn_nn_matrix`, `rno_ino_matrix`,
  `cno_matrix` (com salvaguarda direcional escalável para `N_r >= 7`) e `mgk_matrix`, atualizando
  vértices via `scipy.linalg.solve` (zero `linalg.inv`) e remontando entradas constantes exatamente;
- Interpolação linear de elementos finitos simpliciais ($P_1$ baricêntrica):
  - `evaluate_femt_kuhn_delaunay`: triangulação conformante de Kuhn–Freudenthal em $O(D \log D)$ e memória $O(1)$;
  - `evaluate_femt_delaunay`: triangulação de Delaunay explícita (`scipy.spatial.Delaunay` + `scipy.linalg.solve`);
- Pipeline completo com guarda pré-alocação de envelope Wasm, auditoria independente nos nós e fora dos nós
  e serialização 100% conforme `contracts/schemas/ts_state_space.schema.json`: `derive_ts_femt`.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, NamedTuple, Sequence

import numpy as np
from scipy import linalg as scipy_linalg
from scipy.spatial import Delaunay, QhullError
from scipy.stats import qmc

from control_lab.core.models import TSStateSpace
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    ResourceLimitError,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .sector_nonlinearity import (
    ALLOWED_GENERALIZED_CHANNELS,
    _normalize_bounds_map,
    _parse_symbolic_matrix,
    _resolve_measured_flags,
)
from .symbolic_qlpv import ParsedExpression
from .tpmt import (
    MAX_TPMT_DIMS_HARD,
    MAX_TPMT_DIMS_WARN,
    MAX_TPMT_ELEMENTS_HARD,
    MAX_TPMT_ELEMENTS_WARN,
    MAX_TPMT_GRID_NODES_HARD,
    MAX_TPMT_GRID_NODES_WARN,
    MAX_TPMT_RULES_HARD,
    MAX_TPMT_RULES_WARN,
    SUPPORTED_HULL_TYPES,
    _assemble_block_batch,
    _resolve_per_axis_int,
    cno_matrix,
    mgk_matrix,
    rno_ino_matrix,
    sn_nn_matrix,
)

# Limites normativos do envelope Wasm (CL-TS-MOD-DIR-001 Seção 4.5 e 5)
MAX_FEMT_DIMS_WARN = MAX_TPMT_DIMS_WARN
MAX_FEMT_DIMS_HARD = MAX_TPMT_DIMS_HARD
MAX_FEMT_GRID_NODES_WARN = MAX_TPMT_GRID_NODES_WARN
MAX_FEMT_GRID_NODES_HARD = MAX_TPMT_GRID_NODES_HARD
MAX_FEMT_ELEMENTS_WARN = MAX_TPMT_ELEMENTS_WARN
MAX_FEMT_ELEMENTS_HARD = MAX_TPMT_ELEMENTS_HARD
MAX_FEMT_RULES_WARN = MAX_TPMT_RULES_WARN
MAX_FEMT_RULES_HARD = MAX_TPMT_RULES_HARD

# Limites seguros específicos para triangulação Delaunay explícita (Qhull)
MAX_FEMT_DELAUNAY_DIMS_HARD = 3
MAX_FEMT_DELAUNAY_NODES_HARD = 50_000

SUPPORTED_FEMT_MESH_KINDS: frozenset[str] = frozenset({"kuhn_delaunay", "delaunay"})


class FEMTSVDResult(NamedTuple):
    """Resultado estruturado da SVD matricial econômica da FEMT (Eckart–Young–Mirsky)."""

    U_raw: np.ndarray
    C_raw: np.ndarray
    singular_values: np.ndarray
    rank: int
    eckart_young_frobenius_error: float
    eckart_young_spectral_error: float


# ---------------------------------------------------------------------------
# 1. Decomposição SVD Matricial Econômica Globalmente Ótima
# ---------------------------------------------------------------------------


def femt_svd_decompose(
    S_nodes: np.ndarray,
    *,
    tol: float = 1e-6,
    rank: int | None = None,
) -> FEMTSVDResult:
    """Particiona entradas constantes/variantes, extrai a média e executa SVD econômica centrada sobre o delta.

    - Calcula a média amostral `mean_full` e a flutuação centrada `delta_full = X_T - mean_full`.
    - Identifica o subespaço variante `varying_mask`: `max_q |delta_full[q, j]| > 1e-14 * (1 + |mean_full[j]|)`.
    - Se `M_var == 0` (sistema LTI constante): retorna `rank=0`, `U_raw = 1/sqrt(N_g)`, `C_raw = sqrt(N_g) * mean_full`.
    - Se `M_var > 0`: aplica SVD econômica somente sobre `Delta_var_T`, seleciona posto de flutuação `R_delta`
      e aumenta `U_raw = [u0, U_delta]` (ortonormal de shape `(N_g, R_delta + 1)`), garantindo erro exato
      de Eckart–Young–Mirsky centrado e preservação exata das entradas constantes em `U_raw @ C_raw`.
    """
    arr = np.asarray(S_nodes, dtype=np.float64)
    if arr.ndim not in (2, 3):
        raise DimensionMismatchError(
            f"S_nodes deve ter 2 dimensões (N_g, M) ou 3 dimensões (N_g, M1, M2), recebido shape={arr.shape}."
        )
    if arr.size == 0 or arr.shape[0] < 1:
        raise ValidationError("S_nodes não pode ser vazio.")
    if not np.all(np.isfinite(arr)):
        raise ValidationError("S_nodes contém valores não finitos (NaN/Inf).")
    if tol < 0.0 or not math.isfinite(tol):
        raise ValidationError(f"tol deve ser finito e não negativo, recebido {tol!r}.")

    n_nodes = int(arr.shape[0])
    X_T = arr.reshape(n_nodes, -1)  # (N_g, M), ordem C determinística
    mean_full = np.mean(X_T, axis=0)
    delta_full = X_T - mean_full[None, :]
    varying_mask = np.max(np.abs(delta_full), axis=0) > 1e-14 * (1.0 + np.abs(mean_full))
    m_var = int(np.sum(varying_mask))

    u0 = np.full((n_nodes, 1), 1.0 / math.sqrt(float(n_nodes)), dtype=np.float64)

    if m_var == 0:
        if rank is not None:
            if not isinstance(rank, (int, np.integer)) or isinstance(rank, bool):
                raise ValidationError(f"rank deve ser inteiro, recebido {type(rank).__name__}.")
            r_req = int(rank)
            if r_req not in (0, 1):
                raise ValidationError(
                    f"Posto de flutuação solicitado rank={r_req} fora do intervalo válido [0, 1] para sistema constante."
                )
        C_raw = (math.sqrt(float(n_nodes)) * mean_full)[None, :]
        return FEMTSVDResult(
            U_raw=u0,
            C_raw=np.asarray(C_raw, dtype=np.float64),
            singular_values=np.zeros(0, dtype=np.float64),
            rank=0,
            eckart_young_frobenius_error=0.0,
            eckart_young_spectral_error=0.0,
        )

    X_var_T = X_T[:, varying_mask]
    mean_var = mean_full[varying_mask]
    Delta_var_T = X_var_T - mean_var[None, :]

    U_d, s_d, _ = np.linalg.svd(Delta_var_T, full_matrices=False)
    s_arr = np.asarray(s_d, dtype=np.float64)
    r_max = min(max(1, n_nodes - 1), m_var, int(s_arr.size))

    if rank is not None:
        if not isinstance(rank, (int, np.integer)) or isinstance(rank, bool):
            raise ValidationError(f"rank deve ser inteiro, recebido {type(rank).__name__}.")
        r_sel = int(rank)
        if r_sel < 1 or r_sel > r_max:
            raise ValidationError(
                f"Posto de flutuação solicitado rank={r_sel} fora do intervalo válido [1, {r_max}]."
            )
    else:
        if s_arr.size == 0 or s_arr[0] <= 0.0:
            r_sel = 1
        else:
            r_sel = int(np.sum(s_arr > tol * s_arr[0]))
            r_sel = max(1, min(r_sel, r_max))

    # Reortogonalização explícita de U_delta contra 1_{N_g} e re-ortonormalização se houver drift
    U_delta = np.asarray(U_d[:, :r_sel], dtype=np.float64)
    U_delta = U_delta - np.mean(U_delta, axis=0, keepdims=True)
    gram_err = float(np.linalg.norm(U_delta.T @ U_delta - np.eye(r_sel, dtype=np.float64), ord="fro"))
    if gram_err > 1e-13:
        Q_aug, R_aug = np.linalg.qr(np.hstack([u0, U_delta]), mode="reduced")
        signs = np.where(np.diag(R_aug) < 0.0, -1.0, 1.0)
        Q_aug = Q_aug * signs[None, :]
        U_delta = Q_aug[:, 1:]
        U_delta = U_delta - np.mean(U_delta, axis=0, keepdims=True)

    U_raw = np.hstack([u0, U_delta])
    C_raw = np.asarray(U_raw.T @ X_T, dtype=np.float64)

    if r_sel < s_arr.size:
        ey_frob = math.sqrt(max(0.0, float(np.sum(s_arr[r_sel:] ** 2))))
        ey_spec = float(s_arr[r_sel])
    else:
        ey_frob = 0.0
        ey_spec = 0.0

    return FEMTSVDResult(
        U_raw=U_raw,
        C_raw=C_raw,
        singular_values=s_arr,
        rank=r_sel,
        eckart_young_frobenius_error=ey_frob,
        eckart_young_spectral_error=ey_spec,
    )


# ---------------------------------------------------------------------------
# 2. Interpolação Linear de Elementos Finitos Simpliciais (P1 Baricêntrica)
# ---------------------------------------------------------------------------


def evaluate_femt_kuhn_delaunay(
    point: Sequence[float] | np.ndarray,
    axes_grids: Sequence[Sequence[float] | np.ndarray],
    nodal_weights: np.ndarray | Sequence[Sequence[float]],
) -> np.ndarray:
    r"""Avalia `h(p)` por interpolação baricêntrica $P_1$ sobre subdivisão de Kuhn–Freudenthal.

    Opera em tempo $O(D \log D)$ e memória adicional $O(1)$ por ponto, sem materializar simplices.
    Aceita um único ponto de shape `(D,)` (retorna `(N_r,)`) ou lote `(N_pts, D)` (retorna `(N_pts, N_r)`).
    """
    d_len = len(axes_grids)
    if d_len < 1:
        raise ValidationError("axes_grids deve conter pelo menos 1 eixo.")

    grids: list[np.ndarray] = []
    g_sizes: list[int] = []
    for d, g_raw in enumerate(axes_grids):
        g = np.asarray(g_raw, dtype=np.float64)
        if g.ndim != 1 or g.size < 2:
            raise ValidationError(f"axes_grids[{d}] deve ser vetor 1D com pelo menos 2 pontos.")
        if not np.all(np.isfinite(g)) or not np.all(np.diff(g) > 0.0):
            raise ValidationError(f"axes_grids[{d}] deve ser finito e estritamente crescente.")
        grids.append(g)
        g_sizes.append(int(g.size))

    W = np.asarray(nodal_weights, dtype=np.float64)
    expected_nodes = int(math.prod(g_sizes))
    if W.ndim != 2 or W.shape[0] != expected_nodes or W.shape[1] < 1:
        raise DimensionMismatchError(
            f"nodal_weights deve ter shape ({expected_nodes}, N_r), recebido {W.shape}."
        )
    if not np.all(np.isfinite(W)):
        raise ValidationError("nodal_weights contém valores não finitos (NaN/Inf).")

    pt_arr = np.asarray(point, dtype=np.float64)
    if pt_arr.ndim == 0 and d_len == 1:
        single_point = True
        pts = pt_arr.reshape(1, 1)
    elif pt_arr.ndim == 1:
        if pt_arr.size != d_len:
            raise DimensionMismatchError(
                f"point deve ter comprimento {d_len}, recebido {pt_arr.size}."
            )
        single_point = True
        pts = pt_arr.reshape(1, d_len)
    elif pt_arr.ndim == 2:
        if pt_arr.shape[1] != d_len:
            raise DimensionMismatchError(
                f"point em lote deve ter shape (N_pts, {d_len}), recebido {pt_arr.shape}."
            )
        single_point = False
        pts = pt_arr
    else:
        raise DimensionMismatchError(f"point deve ser 1D ou 2D, recebido ndim={pt_arr.ndim}.")

    if not np.all(np.isfinite(pts)):
        raise ValidationError("point contém valores não finitos (NaN/Inf).")

    n_pts = pts.shape[0]

    # Strides em ordem C (indexing='ij')
    strides = np.empty(d_len, dtype=np.int64)
    acc = 1
    for d in range(d_len - 1, -1, -1):
        strides[d] = acc
        acc *= g_sizes[d]

    k_mat = np.empty((n_pts, d_len), dtype=np.int64)
    xi_mat = np.empty((n_pts, d_len), dtype=np.float64)

    for d in range(d_len):
        g_d = grids[d]
        p_tilde = np.clip(pts[:, d], g_d[0], g_d[-1])
        k_d = np.searchsorted(g_d, p_tilde, side="right") - 1
        k_d = np.clip(k_d, 0, g_sizes[d] - 2)
        k_mat[:, d] = k_d
        denom = g_d[k_d + 1] - g_d[k_d]
        xi_d = (p_tilde - g_d[k_d]) / denom
        xi_mat[:, d] = np.clip(xi_d, 0.0, 1.0)

    # Ordenação descendente: 1 >= xi_{pi(0)} >= xi_{pi(1)} >= ... >= xi_{pi(D-1)} >= 0
    order = np.argsort(-xi_mat, axis=1, kind="mergesort")
    xi_sorted = np.take_along_axis(xi_mat, order, axis=1)

    # Coordenadas baricêntricas fechadas do simplex ativo de Kuhn–Freudenthal
    lam = np.empty((n_pts, d_len + 1), dtype=np.float64)
    lam[:, 0] = 1.0 - xi_sorted[:, 0]
    if d_len > 1:
        lam[:, 1:d_len] = xi_sorted[:, :-1] - xi_sorted[:, 1:]
    lam[:, d_len] = xi_sorted[:, d_len - 1]
    lam = np.clip(lam, 0.0, 1.0)
    lam_sum = np.sum(lam, axis=1, keepdims=True)
    lam = lam / np.where(lam_sum > 0.0, lam_sum, 1.0)

    # Índices planos dos D+1 vértices do simplex ativo
    base_flat = np.sum(k_mat * strides[None, :], axis=1)
    q_idx = np.empty((n_pts, d_len + 1), dtype=np.int64)
    q_idx[:, 0] = base_flat
    q_idx[:, 1:] = base_flat[:, None] + np.cumsum(strides[order], axis=1)

    H = np.einsum("nm,nmr->nr", lam, W[q_idx])
    return H[0] if single_point else H


def _solve_barycentric_for_simplex(
    verts: np.ndarray,
    nodes: np.ndarray,
    pts_group: np.ndarray,
) -> np.ndarray:
    """Resolve `[p^{q1}-p^{q0}, ..., p^{qD}-p^{q0}] lam_{1:D} = p - p^{q0}` via `scipy.linalg.solve` (ZERO `inv`)."""
    p0 = nodes[verts[0]]
    M_delta = (nodes[verts[1:]] - p0).T  # (D, D)
    rhs = (pts_group - p0).T  # (D, k)
    try:
        lam_rest = scipy_linalg.solve(M_delta, rhs, check_finite=False).T  # (k, D)
    except scipy_linalg.LinAlgError:
        lam_rest_ls, _, _, _ = scipy_linalg.lstsq(M_delta, rhs)
        lam_rest = lam_rest_ls.T
    lam_0 = 1.0 - np.sum(lam_rest, axis=1, keepdims=True)
    return np.hstack([lam_0, lam_rest])


def _locate_custom_simplices(
    pts: np.ndarray,
    nodes: np.ndarray,
    simplices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Localiza simplices para triangulação fornecida fora do padrão `Delaunay(nodes)`."""
    n_pts = pts.shape[0]
    d_len = nodes.shape[1]
    simp_coords = nodes[simplices]  # (N_e, D+1, D)
    bb_min = np.min(simp_coords, axis=1) - 1e-11
    bb_max = np.max(simp_coords, axis=1) + 1e-11

    out_sidx = np.full(n_pts, -1, dtype=np.int64)
    out_lam = np.zeros((n_pts, d_len + 1), dtype=np.float64)

    for i in range(n_pts):
        pt = pts[i]
        cand = np.nonzero(np.all((pt >= bb_min) & (pt <= bb_max), axis=1))[0]
        best_s = -1
        best_viol = float("inf")
        best_lam: np.ndarray | None = None
        for s_id in cand:
            lam_vec = _solve_barycentric_for_simplex(simplices[s_id], nodes, pt.reshape(1, -1))[0]
            viol = float(max(0.0, -float(np.min(lam_vec))))
            if viol < best_viol:
                best_viol = viol
                best_s = int(s_id)
                best_lam = lam_vec
                if viol <= 1e-11:
                    break
        if best_s >= 0 and best_lam is not None:
            out_sidx[i] = best_s
            out_lam[i] = best_lam
    return out_sidx, out_lam


def evaluate_femt_delaunay(
    point: Sequence[float] | np.ndarray,
    nodes: np.ndarray | Sequence[Sequence[float]],
    simplices: np.ndarray | Sequence[Sequence[int]] | None,
    nodal_weights: np.ndarray | Sequence[Sequence[float]],
    bounds: Sequence[Sequence[float]] | None = None,
    *,
    delaunay_tri: Delaunay | None = None,
) -> np.ndarray:
    r"""Avalia `h(p)` por interpolação baricêntrica $P_1$ sobre malha de Delaunay explícita (ZERO `linalg.inv`).

    - Para $D = 1$: interpolação linear exata nos intervalos ordenados de `nodes`.
    - Para $D \ge 2$: localiza o simplex contendo $\tilde{p} = \operatorname{clip}(p, \underline{p}, \overline{p})$
      e resolve o sistema baricêntrico via `scipy.linalg.solve`.
    """
    nodes_arr = np.asarray(nodes, dtype=np.float64)
    if nodes_arr.ndim == 1:
        nodes_arr = nodes_arr.reshape(-1, 1)
    if nodes_arr.ndim != 2 or nodes_arr.shape[0] < 2 or nodes_arr.shape[1] < 1:
        raise DimensionMismatchError(
            f"nodes deve ter shape (N_g >= 2, D >= 1), recebido {nodes_arr.shape}."
        )
    if not np.all(np.isfinite(nodes_arr)):
        raise ValidationError("nodes contém valores não finitos (NaN/Inf).")

    n_nodes, d_len = nodes_arr.shape
    W = np.asarray(nodal_weights, dtype=np.float64)
    if W.ndim != 2 or W.shape[0] != n_nodes or W.shape[1] < 1:
        raise DimensionMismatchError(
            f"nodal_weights deve ter shape ({n_nodes}, N_r), recebido {W.shape}."
        )
    if not np.all(np.isfinite(W)):
        raise ValidationError("nodal_weights contém valores não finitos (NaN/Inf).")

    pt_arr = np.asarray(point, dtype=np.float64)
    if pt_arr.ndim == 0 and d_len == 1:
        single_point = True
        pts = pt_arr.reshape(1, 1)
    elif pt_arr.ndim == 1:
        if pt_arr.size != d_len:
            raise DimensionMismatchError(
                f"point deve ter comprimento {d_len}, recebido {pt_arr.size}."
            )
        single_point = True
        pts = pt_arr.reshape(1, d_len)
    elif pt_arr.ndim == 2:
        if pt_arr.shape[1] != d_len:
            raise DimensionMismatchError(
                f"point em lote deve ter shape (N_pts, {d_len}), recebido {pt_arr.shape}."
            )
        single_point = False
        pts = pt_arr
    else:
        raise DimensionMismatchError(f"point deve ser 1D ou 2D, recebido ndim={pt_arr.ndim}.")

    if not np.all(np.isfinite(pts)):
        raise ValidationError("point contém valores não finitos (NaN/Inf).")

    if bounds is not None:
        b_arr = np.asarray(bounds, dtype=np.float64)
        if b_arr.shape != (d_len, 2) or not np.all(np.isfinite(b_arr)):
            raise DimensionMismatchError(f"bounds deve ter shape ({d_len}, 2), recebido {b_arr.shape}.")
        lo = b_arr[:, 0]
        hi = b_arr[:, 1]
    else:
        lo = np.min(nodes_arr, axis=0)
        hi = np.max(nodes_arr, axis=0)

    pts_clamped = np.clip(pts, lo[None, :], hi[None, :])
    n_pts = pts_clamped.shape[0]
    n_rules = W.shape[1]

    # Caso D = 1: interpolação linear exata nos intervalos ordenados
    if d_len == 1:
        order = np.argsort(nodes_arr[:, 0], kind="mergesort")
        x_sorted = nodes_arr[order, 0]
        W_sorted = W[order]
        x_vals = np.clip(pts_clamped[:, 0], x_sorted[0], x_sorted[-1])
        idx = np.searchsorted(x_sorted, x_vals, side="right") - 1
        idx = np.clip(idx, 0, n_nodes - 2)
        dx = x_sorted[idx + 1] - x_sorted[idx]
        safe_dx = np.where(dx > 0.0, dx, 1.0)
        lam1 = np.where(dx > 0.0, (x_vals - x_sorted[idx]) / safe_dx, 0.0)
        lam1 = np.clip(lam1, 0.0, 1.0)
        lam0 = 1.0 - lam1
        H = lam0[:, None] * W_sorted[idx] + lam1[:, None] * W_sorted[idx + 1]
        return H[0] if single_point else H

    # Caso D >= 2: Delaunay explícita
    simp_arr: np.ndarray | None = None
    if simplices is not None:
        simp_arr = np.asarray(simplices, dtype=np.int64)
        if simp_arr.ndim != 2 or simp_arr.shape[1] != d_len + 1 or simp_arr.shape[0] < 1:
            raise DimensionMismatchError(
                f"simplices deve ter shape (N_e >= 1, {d_len + 1}), recebido {simp_arr.shape}."
            )

    tri = delaunay_tri
    if tri is None:
        try:
            tri = Delaunay(nodes_arr)
        except (QhullError, ValueError) as exc:
            if simp_arr is None:
                raise ValidationError(f"Falha ao construir triangulação de Delaunay: {exc}") from exc

    use_tri = tri is not None and (
        simp_arr is None or (simp_arr.shape == tri.simplices.shape and np.array_equal(simp_arr, tri.simplices))
    )
    active_simplices = np.asarray(tri.simplices, dtype=np.int64) if (use_tri and tri is not None) else simp_arr
    assert active_simplices is not None

    H = np.empty((n_pts, n_rules), dtype=np.float64)

    if use_tri and tri is not None:
        s_indices = tri.find_simplex(pts_clamped)
        # Trata pontos exatamente na fronteira que sofreram arredondamento no Qhull
        missing = np.nonzero(s_indices < 0)[0]
        if missing.size > 0:
            centroid = np.mean(nodes_arr, axis=0)
            nudged = pts_clamped[missing] + 1e-12 * (centroid[None, :] - pts_clamped[missing])
            s_retry = tri.find_simplex(nudged)
            s_indices[missing] = s_retry

        valid_mask = s_indices >= 0
        if np.any(valid_mask):
            valid_pos = np.nonzero(valid_mask)[0]
            valid_s = s_indices[valid_pos]
            for s_id in np.unique(valid_s):
                grp = valid_pos[valid_s == s_id]
                verts = active_simplices[s_id]
                lam = _solve_barycentric_for_simplex(verts, nodes_arr, pts_clamped[grp])
                lam = np.clip(lam, 0.0, 1.0)
                lsum = np.sum(lam, axis=1, keepdims=True)
                lam = lam / np.where(lsum > 0.0, lsum, 1.0)
                H[grp] = lam @ W[verts]

        still_missing = np.nonzero(s_indices < 0)[0]
        for idx_pt in still_missing:
            pt = pts_clamped[idx_pt]
            # Fallback seguro: verifica simplices incidentes ao nó mais próximo
            dists_sq = np.sum((nodes_arr - pt[None, :]) ** 2, axis=1)
            q_near = int(np.argmin(dists_sq))
            inc = np.nonzero(np.any(active_simplices == q_near, axis=1))[0]
            if inc.size == 0:
                H[idx_pt] = W[q_near]
                continue
            best_viol = float("inf")
            best_h = W[q_near]
            for s_id in inc:
                verts = active_simplices[s_id]
                lam_v = _solve_barycentric_for_simplex(verts, nodes_arr, pt.reshape(1, -1))[0]
                viol = float(max(0.0, -float(np.min(lam_v))))
                if viol < best_viol:
                    best_viol = viol
                    lam_c = np.clip(lam_v, 0.0, 1.0)
                    ls = float(np.sum(lam_c))
                    lam_c = lam_c / ls if ls > 0.0 else np.full(d_len + 1, 1.0 / (d_len + 1))
                    best_h = lam_c @ W[verts]
            H[idx_pt] = best_h
    else:
        s_indices, lam_all = _locate_custom_simplices(pts_clamped, nodes_arr, active_simplices)
        for i in range(n_pts):
            s_id = int(s_indices[i])
            if s_id >= 0:
                lam_c = np.clip(lam_all[i], 0.0, 1.0)
                ls = float(np.sum(lam_c))
                lam_c = lam_c / ls if ls > 0.0 else np.full(d_len + 1, 1.0 / (d_len + 1))
                H[i] = lam_c @ W[active_simplices[s_id]]
            else:
                q_near = int(np.argmin(np.sum((nodes_arr - pts_clamped[i][None, :]) ** 2, axis=1)))
                H[i] = W[q_near]

    return H[0] if single_point else H


# ---------------------------------------------------------------------------
# 3. Pipeline Completo `derive_ts_femt`
# ---------------------------------------------------------------------------


def _build_ast_varying_mask(
    parsed_A: list[list[ParsedExpression]],
    parsed_B: list[list[ParsedExpression]],
    parsed_C: list[list[ParsedExpression]],
    parsed_D: list[list[ParsedExpression]],
    parsed_gen: Mapping[str, list[list[ParsedExpression]]],
    *,
    n: int,
    m: int,
    p_out: int,
    nw: int,
    nz: int,
) -> np.ndarray:
    """Constrói máscara booleana `(M1, M2)` indicando entradas com variáveis ativas na AST."""
    m1 = n + p_out + nz
    m2 = n + m + nw
    mask = np.zeros((m1, m2), dtype=bool)

    def _fill(block: list[list[ParsedExpression]], r0: int, c0: int) -> None:
        for i, row in enumerate(block):
            for j, pe in enumerate(row):
                if len(pe.active_variables) > 0:
                    mask[r0 + i, c0 + j] = True

    _fill(parsed_A, 0, 0)
    _fill(parsed_B, 0, n)
    _fill(parsed_C, n, 0)
    _fill(parsed_D, n, n)
    if nw > 0:
        if "Bw" in parsed_gen:
            _fill(parsed_gen["Bw"], 0, n + m)
        if "Dyw" in parsed_gen:
            _fill(parsed_gen["Dyw"], n, n + m)
    if nz > 0:
        if "Cz" in parsed_gen:
            _fill(parsed_gen["Cz"], n + p_out, 0)
        if "Dzu" in parsed_gen:
            _fill(parsed_gen["Dzu"], n + p_out, n)
        if nw > 0 and "Dzw" in parsed_gen:
            _fill(parsed_gen["Dzw"], n + p_out, n + m)
    return mask


def derive_ts_femt(
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
    grid_points: int | Mapping[str, int] | Sequence[int] = 21,
    svd_tol: float = 1e-6,
    rank: int | None = None,
    hull_type: str = "CNO",
    mesh_kind: str = "kuhn_delaunay",
    sn_tol: float = 1e-6,
    dt: float | None = None,
    state_names: Sequence[str] | None = None,
    input_names: Sequence[str] | None = None,
    output_names: Sequence[str] | None = None,
    units: Mapping[str, Any] | None = None,
    model_id: str | None = None,
    n_val_points: int = 2048,
) -> Result:
    """Deriva um `TSStateSpace` canônico via Transformação por Elementos Finitos (FEMT)."""
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

        norm_hull = str(hull_type).strip().upper()
        if norm_hull not in SUPPORTED_HULL_TYPES:
            raise ValidationError(
                f"hull_type inválido: {hull_type!r}. Suportados: {sorted(SUPPORTED_HULL_TYPES)}."
            )

        m_kind = str(mesh_kind).strip().lower()
        if m_kind not in SUPPORTED_FEMT_MESH_KINDS:
            raise ValidationError(
                f"mesh_kind inválido: {mesh_kind!r}. Suportados: {sorted(SUPPORTED_FEMT_MESH_KINDS)}."
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

        p_names = [v for v in all_domain_bounds.keys() if v in active_set]
        d_len = len(p_names)
        if d_len == 0:
            raise ValidationError(
                message=(
                    "Nenhuma variável não-linear ativa detectada nas matrizes A, B, C, D: "
                    "o sistema fornecido é LTI constante e não requer FEMT."
                ),
                next_step="Registre diretamente um StateSpace LTI ou inclua termos dependentes de estado/parâmetro.",
            )

        # Guarda pré-alocação de envelope Wasm — Dimensão D
        if d_len > MAX_FEMT_DIMS_HARD:
            raise ResourceLimitError(
                message=(
                    f"Número de variáveis não-lineares ativas D={d_len} excede o teto do Worker Wasm "
                    f"(D <= {MAX_FEMT_DIMS_HARD})."
                ),
                parameters={"D": d_len, "max_D": MAX_FEMT_DIMS_HARD, "active_variables": p_names},
                next_step="Reduza variáveis ativas ou exporte script Python/MATLAB offline.",
            )
        if m_kind == "delaunay" and d_len > MAX_FEMT_DELAUNAY_DIMS_HARD:
            raise ResourceLimitError(
                message=(
                    f"Triangulação 'delaunay' explícita limitada a D <= {MAX_FEMT_DELAUNAY_DIMS_HARD} "
                    f"(recebido D={d_len}). Utilize mesh_kind='kuhn_delaunay' para D em [1, {MAX_FEMT_DIMS_HARD}]."
                ),
                parameters={
                    "D": d_len,
                    "max_delaunay_D": MAX_FEMT_DELAUNAY_DIMS_HARD,
                    "recommended_mesh_kind": "kuhn_delaunay",
                },
                next_step="Altere mesh_kind para 'kuhn_delaunay' (tempo O(D log D) e memória O(1)).",
            )
        if d_len > MAX_FEMT_DIMS_WARN:
            warnings_list.append(
                WarningItem(
                    code="FEMT_HIGH_DIMENSION",
                    message=(
                        f"D={d_len} dimensões não-lineares ativas acima do limite interativo recomendado "
                        f"(D <= {MAX_FEMT_DIMS_WARN})."
                    ),
                    details={"D": d_len, "recommended_max_D": MAX_FEMT_DIMS_WARN},
                )
            )

        for nm in p_names:
            lo_v, hi_v = all_domain_bounds[nm]
            if hi_v - lo_v <= 1e-12:
                raise ValidationError(
                    f"Variável ativa {nm!r} possui domínio degenerado [{lo_v}, {hi_v}]. "
                    "Substitua-a por uma constante escalar."
                )

        g_sizes = _resolve_per_axis_int(grid_points, p_names, field_name="grid_points", min_value=2)

        # Guarda pré-alocação de envelope Wasm — Nós e Elementos (N_g * M)
        m1 = n + p_out + nz
        m2 = n + m + nw
        m_vec = m1 * m2
        total_nodes = int(math.prod(g_sizes))
        total_elements = total_nodes * m_vec

        if total_nodes > MAX_FEMT_GRID_NODES_HARD:
            raise ResourceLimitError(
                message=(
                    f"Total de nós da malha ({total_nodes:,}) excede o teto Wasm ({MAX_FEMT_GRID_NODES_HARD:,})."
                ),
                parameters={"total_nodes": total_nodes, "max_nodes": MAX_FEMT_GRID_NODES_HARD, "grid_sizes": g_sizes},
                next_step="Reduza grid_points por eixo ou exporte script Python/MATLAB offline.",
            )
        if m_kind == "delaunay" and total_nodes > MAX_FEMT_DELAUNAY_NODES_HARD:
            raise ResourceLimitError(
                message=(
                    f"Triangulação 'delaunay' explícita limitada a N_g <= {MAX_FEMT_DELAUNAY_NODES_HARD:,} nós "
                    f"(recebido {total_nodes:,}). Utilize mesh_kind='kuhn_delaunay'."
                ),
                parameters={
                    "total_nodes": total_nodes,
                    "max_delaunay_nodes": MAX_FEMT_DELAUNAY_NODES_HARD,
                    "recommended_mesh_kind": "kuhn_delaunay",
                },
                next_step="Altere mesh_kind para 'kuhn_delaunay' ou reduza grid_points.",
            )
        if total_elements > MAX_FEMT_ELEMENTS_HARD:
            raise ResourceLimitError(
                message=(
                    f"Total de elementos da matriz de amostras X ({total_elements:,}) excede o teto Wasm "
                    f"({MAX_FEMT_ELEMENTS_HARD:,})."
                ),
                parameters={
                    "total_elements": total_elements,
                    "max_elements": MAX_FEMT_ELEMENTS_HARD,
                    "matrix_shape": [m_vec, total_nodes],
                },
                next_step="Reduza grid_points por eixo ou exporte script Python/MATLAB offline.",
            )
        if total_nodes > MAX_FEMT_GRID_NODES_WARN:
            warnings_list.append(
                WarningItem(
                    code="FEMT_LARGE_GRID",
                    message=(
                        f"Total de nós ({total_nodes:,}) acima do recomendado interativo ({MAX_FEMT_GRID_NODES_WARN:,})."
                    ),
                    details={"total_nodes": total_nodes, "recommended_max_nodes": MAX_FEMT_GRID_NODES_WARN},
                )
            )
        if total_elements > MAX_FEMT_ELEMENTS_WARN:
            warnings_list.append(
                WarningItem(
                    code="FEMT_LARGE_SAMPLE_MATRIX",
                    message=(
                        f"Total de elementos N_g * M ({total_elements:,}) acima do recomendado interativo "
                        f"({MAX_FEMT_ELEMENTS_WARN:,})."
                    ),
                    details={"total_elements": total_elements, "recommended_max_elements": MAX_FEMT_ELEMENTS_WARN},
                )
            )

        # 1. Amostragem vetorizada sobre a malha nodal g^(1) x ... x g^(D)
        axes_grids = [
            np.linspace(all_domain_bounds[nm][0], all_domain_bounds[nm][1], g_sizes[d], dtype=np.float64)
            for d, nm in enumerate(p_names)
        ]
        mesh = np.meshgrid(*axes_grids, indexing="ij")
        nodes = np.column_stack([m_d.ravel() for m_d in mesh])  # (N_g, D)
        env_grid = {p_names[d]: nodes[:, d] for d in range(d_len)}

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
        )  # (N_g, M1, M2)

        # 2. Partição estrutural I_const U I_var + SVD econômica centrada sobre o delta
        X_T = S_batch_grid.reshape(total_nodes, m_vec)
        mean_full = np.mean(X_T, axis=0)
        delta_full = X_T - mean_full[None, :]
        ast_varying_mask = _build_ast_varying_mask(
            parsed_A,
            parsed_B,
            parsed_C,
            parsed_D,
            parsed_gen,
            n=n,
            m=m,
            p_out=p_out,
            nw=nw,
            nz=nz,
        ).reshape(-1)
        num_varying_mask = np.max(np.abs(delta_full), axis=0) > 1e-14 * (1.0 + np.abs(mean_full))
        varying_mask = ast_varying_mask & num_varying_mask
        n_varying_entries = int(np.sum(varying_mask))
        n_constant_entries = int(m_vec - n_varying_entries)

        # Preserva bit-a-bit todas as entradas estruturalmente constantes na AST
        S_const_flat = mean_full.copy()
        S_const_flat[~ast_varying_mask] = X_T[0, ~ast_varying_mask]

        svd_res = femt_svd_decompose(S_batch_grid, tol=svd_tol, rank=rank)
        U_raw = svd_res.U_raw
        C_raw = svd_res.C_raw

        # 3. Construção do Fecho Convexo Sem Coluna Extra no Subespaço Variante (ZERO linalg.inv)
        if n_varying_entries == 0:
            W_nodal = np.ones((total_nodes, 1), dtype=np.float64)
            C_final = S_const_flat[None, :].copy()
            hull_diag: dict[str, Any] = {
                "hull_type": norm_hull,
                "rank_before": 1,
                "rank_after": 1,
                "rank_augmented": False,
                "min_weight": 1.0,
                "max_sum_deviation": 0.0,
                "cond_T": 1.0,
                "cond_W": 1.0,
                "log_abs_det_T": 0.0,
                "fallback_used": False,
                "used_directional_prefilter": False,
                "nn_violated": False,
            }
            if norm_hull == "CNO":
                hull_diag["used_convex_hull"] = False
                hull_diag["n_hull_vertices"] = 1
        else:
            mean_var = mean_full[varying_mask]
            U_delta = U_raw[:, 1:]
            C_delta_var = C_raw[1:, varying_mask]

            # Pré-condicionamento RMS invariante a N_g
            scale = math.sqrt(float(total_nodes))
            U_delta_scaled = scale * U_delta
            C_delta_scaled = C_delta_var / scale

            # Base inicial de soma unitária analítica (sem lstsq, sem coluna extra)
            U_sn = np.column_stack(
                [np.ones(total_nodes, dtype=np.float64) - np.sum(U_delta_scaled, axis=1), U_delta_scaled]
            )
            C_sn_var = np.vstack([mean_var[None, :], mean_var[None, :] + C_delta_scaled])

            W_sn, T_sn_nn, info_sn = sn_nn_matrix(U_sn, sn_tol=sn_tol)
            C_sn_nn_var = np.asarray(scipy_linalg.solve(T_sn_nn, C_sn_var), dtype=np.float64)
            rank_before = int(info_sn["rank_before"])
            rank_augmented = bool(info_sn["rank_augmented"])

            if norm_hull == "SN-NN":
                W_nodal = W_sn
                C_final_var = C_sn_nn_var
                hull_diag = {
                    "hull_type": "SN-NN",
                    "rank_before": rank_before,
                    "rank_after": int(W_nodal.shape[1]),
                    "rank_augmented": rank_augmented,
                    "min_weight": float(info_sn["min_weight"]),
                    "max_sum_deviation": float(info_sn["max_sum_deviation"]),
                    "cond_T": float(info_sn["cond_T"]),
                    "cond_W": float(np.linalg.cond(W_nodal)),
                    "log_abs_det_T": 0.0,
                    "fallback_used": False,
                    "used_directional_prefilter": False,
                    "nn_violated": False,
                }
            elif norm_hull == "RNO-INO":
                W_nodal, T_hull, info_h = rno_ino_matrix(W_sn)
                C_final_var = np.asarray(scipy_linalg.solve(T_hull, C_sn_nn_var), dtype=np.float64)
                hull_diag = {
                    "hull_type": "RNO-INO",
                    "rank_before": rank_before,
                    "rank_after": int(W_nodal.shape[1]),
                    "rank_augmented": rank_augmented,
                    "min_weight": float(info_h["min_weight"]),
                    "max_sum_deviation": float(info_h["max_sum_deviation"]),
                    "cond_T": float(info_h["cond_T"]),
                    "cond_W": float(np.linalg.cond(W_nodal)),
                    "log_abs_det_T": float(info_h["log_abs_det_T"]),
                    "fallback_used": bool(info_h["fallback_used"]),
                    "used_directional_prefilter": False,
                    "nn_violated": False,
                }
            elif norm_hull == "CNO":
                W_nodal, T_hull, info_h = cno_matrix(W_sn)
                C_final_var = np.asarray(scipy_linalg.solve(T_hull, C_sn_nn_var), dtype=np.float64)
                hull_diag = {
                    "hull_type": "CNO",
                    "rank_before": rank_before,
                    "rank_after": int(W_nodal.shape[1]),
                    "rank_augmented": rank_augmented,
                    "used_convex_hull": bool(info_h["used_convex_hull"]),
                    "used_directional_prefilter": bool(info_h.get("used_directional_prefilter", False)),
                    "n_hull_vertices": int(info_h["n_hull_vertices"]),
                    "min_weight": float(info_h["min_weight"]),
                    "max_sum_deviation": float(info_h["max_sum_deviation"]),
                    "cond_T": float(info_h["cond_T"]),
                    "cond_W": float(np.linalg.cond(W_nodal)),
                    "log_abs_det_T": float(info_h["log_abs_det_T"]),
                    "fallback_used": bool(info_h["fallback_used"]),
                    "nn_violated": False,
                }
            else:  # MGK
                W_nodal, T_hull, info_h = mgk_matrix(W_sn)
                C_final_var = np.asarray(scipy_linalg.solve(T_hull, C_sn_nn_var), dtype=np.float64)
                nn_viol = bool(info_h["nn_violated"])
                if nn_viol:
                    warnings_list.append(
                        WarningItem(
                            code="NN_VIOLATED",
                            message=(
                                f"Transformação MGK global violou não-negatividade "
                                f"(min(W)={info_h['min_weight']:.3e} < -1e-9). Recomenda-se RNO-INO ou CNO."
                            ),
                            details={"min_weight": float(info_h["min_weight"])},
                        )
                    )
                hull_diag = {
                    "hull_type": "MGK",
                    "rank_before": rank_before,
                    "rank_after": int(W_nodal.shape[1]),
                    "rank_augmented": rank_augmented,
                    "min_weight": float(info_h["min_weight"]),
                    "max_sum_deviation": float(info_h["max_sum_deviation"]),
                    "cond_T": float(info_h["cond_T"]),
                    "cond_W": float(np.linalg.cond(W_nodal)),
                    "log_abs_det_T": float(info_h["log_abs_det_T"]),
                    "fallback_used": False,
                    "used_directional_prefilter": False,
                    "nn_violated": nn_viol,
                }

            # Remontagem estrutural exata: entradas constantes bit-a-bit idênticas em todas as regras
            n_rules_tmp = int(W_nodal.shape[1])
            C_final = np.broadcast_to(S_const_flat[None, :], (n_rules_tmp, m_vec)).copy()
            C_final[:, varying_mask] = C_final_var

        # 4. Validação do número final de regras N_r
        n_rules = int(W_nodal.shape[1])
        if n_rules > MAX_FEMT_RULES_HARD:
            raise ResourceLimitError(
                message=(
                    f"Número resultante de regras N_r={n_rules} excede o teto Wasm ({MAX_FEMT_RULES_HARD})."
                ),
                parameters={"n_rules": n_rules, "max_rules": MAX_FEMT_RULES_HARD},
                next_step="Reduza o posto global (rank) ou aumente svd_tol.",
            )
        if n_rules > MAX_FEMT_RULES_WARN:
            warnings_list.append(
                WarningItem(
                    code="FEMT_HIGH_RULE_COUNT",
                    message=(
                        f"Modelo FEMT gerou N_r={n_rules} regras (acima do recomendado interativo "
                        f"N_r <= {MAX_FEMT_RULES_WARN}); síntese LMI PDC terá custo O(N_r^2)."
                    ),
                    details={"n_rules": n_rules, "recommended_max_rules": MAX_FEMT_RULES_WARN},
                )
            )

        # 5. Extração direta das N_r matrizes vértices S_r = reshape(C_final[r, :], (M1, M2))
        vertices_S = C_final.reshape(n_rules, m1, m2)
        vertices_list: list[dict[str, Any]] = []
        functions_spec: list[dict[str, Any]] = []
        gen_vertices: list[dict[str, Any]] = []
        vars_csv = ", ".join(p_names)

        for r_idx in range(n_rules):
            S_r = np.asarray(vertices_S[r_idx], dtype=np.float64)
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

            functions_spec.append(
                {
                    "id": f"h_{r_idx + 1}",
                    "vertex_id": vid,
                    "rule_index": r_idx,
                    "expression": f"fem_p1_barycentric({vars_csv}; r={r_idx + 1})",
                }
            )

        # 6. Construção da malha simplicial explícita (quando mesh_kind == "delaunay")
        delaunay_tri: Delaunay | None = None
        simplices: np.ndarray | None = None
        if m_kind == "delaunay":
            if d_len == 1:
                simplices = np.column_stack(
                    [np.arange(total_nodes - 1, dtype=np.int64), np.arange(1, total_nodes, dtype=np.int64)]
                )
            else:
                delaunay_tri = Delaunay(nodes)
                simplices = np.asarray(delaunay_tri.simplices, dtype=np.int64)

        # 7. Auditoria independente NOS NÓS e FORA DOS NÓS (ModelFidelityCertificate)
        # 7a. Nos nós da malha
        S_grid_hat = (W_nodal @ C_final).reshape(total_nodes, m1, m2)
        grid_diff = (S_batch_grid - S_grid_hat).reshape(total_nodes, -1)
        grid_err_frob = np.linalg.norm(grid_diff, axis=1)
        grid_frobenius_error = float(np.linalg.norm(grid_diff, ord="fro"))
        grid_true_frob_total = float(np.linalg.norm(S_batch_grid.reshape(total_nodes, -1), ord="fro"))
        grid_max_abs_error = float(np.max(grid_err_frob))
        grid_rel_l2_error = float(grid_frobenius_error / (grid_true_frob_total + 1e-15))

        # 7b. Fora dos nós (baricentros de simplices + Sobol)
        lo_act = np.array([all_domain_bounds[nm][0] for nm in p_names], dtype=np.float64)
        hi_act = np.array([all_domain_bounds[nm][1] for nm in p_names], dtype=np.float64)
        bounds_list = [[float(lo_act[d]), float(hi_act[d])] for d in range(d_len)]

        val_blocks: list[np.ndarray] = []
        if m_kind == "delaunay" and simplices is not None:
            n_simp = simplices.shape[0]
            if n_simp <= 512:
                bary_pts = np.mean(nodes[simplices], axis=1)
            else:
                sel_s = np.linspace(0, n_simp - 1, 512, dtype=np.int64)
                bary_pts = np.mean(nodes[simplices[sel_s]], axis=1)
            val_blocks.append(bary_pts)
        else:
            mid_axes = [0.5 * (g[:-1] + g[1:]) for g in axes_grids]
            n_mids_total = int(math.prod(m_ax.size for m_ax in mid_axes))
            if n_mids_total <= 512:
                m_mesh = np.meshgrid(*mid_axes, indexing="ij")
                val_blocks.append(np.column_stack([mm.ravel() for mm in m_mesh]))
            else:
                rng_idx = np.linspace(0, n_mids_total - 1, 512, dtype=np.int64)
                mid_shapes = tuple(m_ax.size for m_ax in mid_axes)
                unraveled = np.unravel_index(rng_idx, mid_shapes)
                val_blocks.append(np.column_stack([mid_axes[d][unraveled[d]] for d in range(d_len)]))

        n_bary_added = int(val_blocks[0].shape[0])
        n_sobol = max(64, int(n_val_points) - n_bary_added)
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
        if m_kind == "kuhn_delaunay":
            H_val = evaluate_femt_kuhn_delaunay(val_pts, axes_grids, W_nodal)
        else:
            H_val = evaluate_femt_delaunay(
                val_pts,
                nodes,
                simplices,
                W_nodal,
                bounds=bounds_list,
                delaunay_tri=delaunay_tri,
            )

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

        # Classificação honesta de verificação (CL-TS-MOD-DIR-001 Seção 6.1)
        exact_nodal = (
            grid_rel_l2_error <= 1e-9
            and val_rel_l2_error <= 1e-4
            and min_weight >= -1e-9
            and max_sum_deviation <= 1e-9
        )
        verification_badge = "EXACT_NODAL_FEMT" if exact_nodal else "APPROXIMATE_REDUCED_FEMT"
        verification_tier = "numeric_verified" if exact_nodal else "approximate"

        fidelity_cert: dict[str, Any] = {
            "n_grid_points": total_nodes,
            "n_validation_points": n_val_actual,
            "grid_max_abs_error": grid_max_abs_error,
            "grid_frobenius_error": grid_frobenius_error,
            "grid_rel_l2_error": grid_rel_l2_error,
            "eckart_young_frobenius_error": float(svd_res.eckart_young_frobenius_error),
            "eckart_young_spectral_error": float(svd_res.eckart_young_spectral_error),
            "val_max_abs_error": val_max_abs_error,
            "val_rel_l2_error": val_rel_l2_error,
            "min_weight": min_weight,
            "max_sum_deviation": max_sum_deviation,
            "verification_badge": verification_badge,
            "verification_tier": verification_tier,
            "verified": exact_nodal,
        }

        # 8. Construção do TSStateSpace 100% conforme contracts/schemas/ts_state_space.schema.json
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

        axes_grids_list = [[float(v) for v in g.tolist()] for g in axes_grids]
        nodal_weights_list = [[float(v) for v in row] for row in W_nodal.tolist()]
        nodes_list = [[float(v) for v in row] for row in nodes.tolist()] if m_kind == "delaunay" else None
        simplices_list = (
            [[int(v) for v in row] for row in simplices.tolist()]
            if (m_kind == "delaunay" and simplices is not None)
            else None
        )

        femt_mesh_spec: dict[str, Any] = {
            "mesh_kind": m_kind,
            "variables": list(p_names),
            "bounds": bounds_list,
            "hull_type": norm_hull,
            "svd_rank": int(svd_res.rank),
            "num_rules": n_rules,
            "axes_grids": axes_grids_list,
            "nodal_weights": nodal_weights_list,
            "simplices": simplices_list,
        }
        if m_kind == "delaunay":
            femt_mesh_spec["nodes"] = nodes_list

        membership_spec: dict[str, Any] = {
            "version": "1.0.0",
            "representation_kind": "femt_simplicial",
            "premise_variables": list(p_names),
            "sum_to_one_domain": True,
            "femt_mesh": femt_mesh_spec,
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

        singular_values_list = [float(v) for v in svd_res.singular_values.tolist()]
        provenance_payload: dict[str, Any] = {
            "source": "control_lab.fuzzy.derive_ts_femt",
            "ts_derivation": {
                "method": "femt",
                "mesh_kind": m_kind,
                "svd_tol": float(svd_tol),
                "svd_rank": int(svd_res.rank),
                "hull_type": norm_hull,
                "active_variables": list(p_names),
                "grid_points": list(g_sizes),
                "num_rules": n_rules,
                "n_varying_entries": n_varying_entries,
                "n_constant_entries": n_constant_entries,
                "centered_mean_augmented": True,
                "state_bounds": clean_state_bounds,
                "external_bounds": clean_ext_bounds,
                "A_expr": [[pe.source for pe in row] for row in parsed_A],
                "B_expr": [[pe.source for pe in row] for row in parsed_B],
                "C_expr": [[pe.source for pe in row] for row in parsed_C],
                "D_expr": [[pe.source for pe in row] for row in parsed_D],
                "singular_values": singular_values_list,
                "eckart_young_frobenius_error": float(svd_res.eckart_young_frobenius_error),
                "eckart_young_spectral_error": float(svd_res.eckart_young_spectral_error),
                "hull_diagnostics": hull_diag,
                "fidelity_certificate": fidelity_cert,
            },
        }
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
                "mesh_kind": m_kind,
                "svd_rank": int(svd_res.rank),
                "n_varying_entries": n_varying_entries,
                "n_constant_entries": n_constant_entries,
                "singular_values": singular_values_list,
                "eckart_young_frobenius_error": float(svd_res.eckart_young_frobenius_error),
                "eckart_young_spectral_error": float(svd_res.eckart_young_spectral_error),
                "U_raw": [[float(v) for v in row] for row in U_raw.tolist()],
                "W_nodal": nodal_weights_list,
                "axes_grids": axes_grids_list,
                "nodes": nodes_list,
                "simplices": simplices_list,
                "hull_diagnostics": hull_diag,
                "fidelity_certificate": fidelity_cert,
            },
            assumptions={
                "method": "femt",
                "mesh_kind": m_kind,
                "centered_mean_augmented": True,
                "convex_sum_interpolated_everywhere": True,
                "zero_linalg_inv": True,
            },
            diagnostics={
                "D_active": d_len,
                "grid_sizes": g_sizes,
                "total_nodes": total_nodes,
                "svd_rank": int(svd_res.rank),
                "num_rules": n_rules,
                "n_varying_entries": n_varying_entries,
                "n_constant_entries": n_constant_entries,
                "grid_max_abs_error": grid_max_abs_error,
                "grid_frobenius_error": grid_frobenius_error,
                "grid_rel_l2_error": grid_rel_l2_error,
                "eckart_young_frobenius_error": float(svd_res.eckart_young_frobenius_error),
                "eckart_young_spectral_error": float(svd_res.eckart_young_spectral_error),
                "val_max_abs_error": val_max_abs_error,
                "val_rel_l2_error": val_rel_l2_error,
                "min_weight": min_weight,
                "max_sum_deviation": max_sum_deviation,
                "verification_badge": verification_badge,
                "verification_tier": verification_tier,
            },
            provenance=build_provenance("control_lab.fuzzy.derive_ts_femt", model_revision=ts_ss.revision),
            warnings=tuple(warnings_list),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={"method": "femt"},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.derive_ts_femt"),
            warnings=(),
            error=exc.to_typed_error(),
        )
