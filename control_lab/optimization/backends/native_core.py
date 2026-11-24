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
import scipy.sparse.linalg
from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import CancelledError, ValidationError, WarningItem
from ..modeling.canonical import CanonicalSDPProblem

_ACTIVE_PROGRESS_CALLBACK: contextvars.ContextVar[Callable[[dict[str, Any]], Any] | None] = (
    contextvars.ContextVar("_ACTIVE_PROGRESS_CALLBACK", default=None)
)
_ACTIVE_CANCEL_CHECK: contextvars.ContextVar[Callable[[], Any] | None] = (
    contextvars.ContextVar("_ACTIVE_CANCEL_CHECK", default=None)
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


def set_cancel_check(fn: Callable[[], Any] | None) -> None:
    """Registra função de verificação cooperativa de cancelamento no contexto atual."""
    _ACTIVE_CANCEL_CHECK.set(fn)


def get_cancel_check() -> Callable[[], Any] | None:
    """Retorna a função de verificação de cancelamento ativa no contexto atual."""
    return _ACTIVE_CANCEL_CHECK.get()


def clear_cancel_check() -> None:
    """Remove a função de verificação de cancelamento ativa no contexto atual."""
    _ACTIVE_CANCEL_CHECK.set(None)


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
    """Parâmetros numéricos configuráveis do solver primal-dual nativo/educacional."""

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
    use_hsde: bool = True
    max_gondzio_correctors: int = 2
    schur_mode: str = "auto"
    sparse_schur_density_threshold: float = 0.30
    sparse_schur_min_dim: int = 48
    schur_factorization_mode: str = "auto"
    use_chordal: bool = True

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
            "use_hsde",
            "max_gondzio_correctors",
            "schur_mode",
            "sparse_schur_density_threshold",
            "sparse_schur_min_dim",
            "schur_factorization_mode",
            "use_chordal",
        }
        kwargs: dict[str, Any] = {}
        for k, v in options.items():
            if k in ("progress_callback", "cancel_check"):
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
        for key in ("max_iter", "phase1_max_iter", "sparse_schur_min_dim"):
            value = getattr(cfg, key)
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
                raise ValidationError(f"{key} must be a positive integer.")
        if (
            isinstance(cfg.max_gondzio_correctors, bool)
            or not isinstance(cfg.max_gondzio_correctors, (int, np.integer))
            or cfg.max_gondzio_correctors < 0
            or cfg.max_gondzio_correctors > 10
        ):
            raise ValidationError("max_gondzio_correctors must be an integer in [0, 10].")
        if not isinstance(cfg.use_hsde, bool):
            raise ValidationError("use_hsde must be boolean.")
        if not isinstance(cfg.use_chordal, bool):
            raise ValidationError("use_chordal must be boolean.")
        if cfg.schur_mode not in ("auto", "F3_blas"):
            raise ValidationError("schur_mode must be 'auto' or 'F3_blas'.")
        if cfg.schur_factorization_mode not in ("auto", "dense_cholesky", "sparse_splu"):
            raise ValidationError("schur_factorization_mode must be 'auto', 'dense_cholesky', or 'sparse_splu'.")
        for key in ("tol_gap", "tol_feas", "tol_psd", "strict_margin", "step_fraction", "sigma_min", "sigma_max", "unbounded_norm_threshold", "sparse_schur_density_threshold"):
            value = getattr(cfg, key)
            if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)) or not math.isfinite(value) or value <= 0:
                raise ValidationError(f"{key} must be a finite positive scalar.")
        if cfg.sparse_schur_density_threshold > 1.0:
            raise ValidationError("sparse_schur_density_threshold must be in (0, 1].")
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


_SQRT2 = math.sqrt(2.0)
_INV_SQRT2 = 1.0 / _SQRT2
_F2_CHUNK_SIZE = 32
_F3_CHUNK_SIZE = 64


@dataclass(frozen=True)
class _InternalConeBlock:
    """Bloco simétrico interno (bloco PSD original ou desigualdade escalar 1x1).

    Implementa seleção automática das fórmulas de montagem de Schur esparsa F1/F2/F3
    (Fujisawa, Kojima & Nakata, Math. Program. 79(1-3):235-253, 1997,
    doi:10.1007/BF02614319):
    - `LP_1D`: bloco escalar `1x1` agrupado no cone LP 1D unificado.
    - `F1`: bloco PSD ultra-esparso (`nnz_k <= max(4, n_b // 2)` e `nnz_upper_k <= 4`),
      avalia $H_{ij} = \\sum v_1 v_2 W_{qr} W_{sp}$ diretamente dos tripletos triangulares
      superiores sem alocar matrizes `(n_b, n_b)` intermediárias nem `cols` denso.
    - `F2`: bloco PSD moderadamente esparso (`avg_nnz < 0.25 * n_b^2`),
      avalia $B_j = F_j W$ e $H_{:, j} = \\mathcal{F}_{\\text{sparse}} (W B_j)$ em lotes
      esparsos C/BLAS sem alocar `cols` denso `(n_b^2, n_act)`.
    - `F3_blas`: fallback denso vetorizado `cols.T @ cols` (`dsyrk`/`dgemm`).
    """

    name: str
    dim: int
    F0: np.ndarray
    F_terms: dict[int, np.ndarray]
    is_ineq_slack: bool = False
    ineq_index: int | None = None
    force_schur_mode: str = "auto"
    build_schur_index: bool = True
    _active_keys: np.ndarray = field(init=False, repr=False, compare=False)
    _F_cols: np.ndarray | None = field(init=False, repr=False, compare=False)
    _f_norm_sum: float = field(init=False, repr=False, compare=False)
    _sparse_terms: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = field(
        init=False, repr=False, compare=False
    )
    schur_mode: str = field(init=False, repr=False, compare=False)
    _f1_P: np.ndarray | None = field(init=False, repr=False, compare=False)
    _f1_Q: np.ndarray | None = field(init=False, repr=False, compare=False)
    _f1_V: np.ndarray | None = field(init=False, repr=False, compare=False)
    _F_flat_csr: scipy.sparse.csr_matrix | None = field(init=False, repr=False, compare=False)
    _F_vert_chunks: tuple[
        tuple[int, int, scipy.sparse.csr_matrix, scipy.sparse.csr_matrix], ...
    ] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        keys = sorted(self.F_terms.keys())
        active_keys = np.asarray(keys, dtype=np.intp)
        n_act = len(keys)
        dim = self.dim
        n2 = dim * dim

        f_norm_sum = 0.0
        sparse_terms: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        f1_P: np.ndarray | None = None
        f1_Q: np.ndarray | None = None
        f1_V: np.ndarray | None = None
        F_flat_csr: scipy.sparse.csr_matrix | None = None
        F_vert_chunks: tuple[
            tuple[int, int, scipy.sparse.csr_matrix, scipy.sparse.csr_matrix], ...
        ] = ()
        f_cols: np.ndarray | None = None

        if dim == 1:
            schur_mode = "LP_1D"
            f_cols = np.empty((1, n_act), dtype=np.float64)
            for idx, j in enumerate(keys):
                val = float(self.F_terms[j][0, 0])
                f_cols[0, idx] = val
                f_norm_sum += abs(val)
        elif n_act == 0:
            schur_mode = "F3_blas"
            f_cols = np.zeros((n2, 0), dtype=np.float64)
        elif not self.build_schur_index:
            schur_mode = "F3_blas"
        else:
            # Coletar estatísticas de esparsidade sobre termos simetrizados
            nnz_full_list: list[int] = []
            nnz_up_list: list[int] = []
            triplets_full: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
            triplets_up: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
            nnz_limit = min(int(0.25 * n2), dim) if dim >= 4 else 0
            total_nnz = 0
            for j in keys:
                fj = self.F_terms[j]
                fj_sym = 0.5 * (fj + fj.T)
                r_all, c_all = np.nonzero(np.abs(fj_sym) > 0.0)
                v_all = fj_sym[r_all, c_all]
                nnz_j = int(r_all.size)
                total_nnz += nnz_j
                nnz_full_list.append(nnz_j)
                triplets_full.append((r_all, c_all, v_all))
                f_norm_sum += float(np.linalg.norm(v_all))
                if nnz_limit > 0 and 0 < nnz_j <= nnz_limit:
                    sparse_terms[j] = (r_all, c_all, v_all)
                up_mask = r_all <= c_all
                r_up = r_all[up_mask]
                c_up = c_all[up_mask]
                v_up = v_all[up_mask]
                nnz_up_list.append(int(r_up.size))
                triplets_up.append((r_up, c_up, v_up))

            max_nnz_full = max(nnz_full_list)
            max_nnz_up = max(nnz_up_list)

            if self.force_schur_mode == "F3_blas" or dim < 4:
                schur_mode = "F3_blas"
            elif max_nnz_full <= max(4, dim // 2) and max_nnz_up <= 4:
                schur_mode = "F1"
            elif total_nnz < int(0.25 * n2 * n_act):
                schur_mode = "F2"
            else:
                schur_mode = "F3_blas"

            if schur_mode in ("F1", "F2") and self.build_schur_index:
                # Construir CSR achatado (n_act, n2) para operações forward/adjoint/F2 sem alocar _F_cols denso
                flat_rows_parts: list[np.ndarray] = []
                flat_cols_parts: list[np.ndarray] = []
                flat_vals_parts: list[np.ndarray] = []
                for idx, (r_all, c_all, v_all) in enumerate(triplets_full):
                    if r_all.size > 0:
                        flat_rows_parts.append(np.full((r_all.size,), idx, dtype=np.int32))
                        flat_cols_parts.append((r_all * dim + c_all).astype(np.int32, copy=False))
                        flat_vals_parts.append(v_all)
                if flat_rows_parts:
                    F_flat_csr = scipy.sparse.csr_matrix(
                        (
                            np.concatenate(flat_vals_parts),
                            (np.concatenate(flat_rows_parts), np.concatenate(flat_cols_parts)),
                        ),
                        shape=(n_act, n2),
                        dtype=np.float64,
                    )
                else:
                    F_flat_csr = scipy.sparse.csr_matrix((n_act, n2), dtype=np.float64)

                if schur_mode == "F1":
                    k_up = max(1, max_nnz_up)
                    f1_P = np.zeros((n_act, k_up), dtype=np.intp)
                    f1_Q = np.zeros((n_act, k_up), dtype=np.intp)
                    f1_V = np.zeros((n_act, k_up), dtype=np.float64)
                    for idx, (r_up, c_up, v_up) in enumerate(triplets_up):
                        cnt = r_up.size
                        if cnt > 0:
                            f1_P[idx, :cnt] = r_up
                            f1_Q[idx, :cnt] = c_up
                            scales = np.where(r_up == c_up, _INV_SQRT2, _SQRT2)
                            f1_V[idx, :cnt] = v_up * scales
                else:
                    # schur_mode == "F2": pré-fatiar blocos verticais esparsos (c_len * dim, dim)
                    # e visões CSR de cauda F_flat[start:] sem duplicar vetores data/indices
                    chunks: list[
                        tuple[int, int, scipy.sparse.csr_matrix, scipy.sparse.csr_matrix]
                    ] = []
                    for start in range(0, n_act, _F2_CHUNK_SIZE):
                        end = min(start + _F2_CHUNK_SIZE, n_act)
                        c_len = end - start
                        vr_parts: list[np.ndarray] = []
                        vc_parts: list[np.ndarray] = []
                        vv_parts: list[np.ndarray] = []
                        for local_i, idx in enumerate(range(start, end)):
                            r_all, c_all, v_all = triplets_full[idx]
                            if r_all.size > 0:
                                vr_parts.append((r_all + local_i * dim).astype(np.int32, copy=False))
                                vc_parts.append(c_all.astype(np.int32, copy=False))
                                vv_parts.append(v_all)
                        if vr_parts:
                            f_vert = scipy.sparse.csr_matrix(
                                (
                                    np.concatenate(vv_parts),
                                    (np.concatenate(vr_parts), np.concatenate(vc_parts)),
                                ),
                                shape=(c_len * dim, dim),
                                dtype=np.float64,
                            )
                        else:
                            f_vert = scipy.sparse.csr_matrix((c_len * dim, dim), dtype=np.float64)
                        if start == 0:
                            f_tail = F_flat_csr
                        else:
                            p0 = int(F_flat_csr.indptr[start])
                            f_tail = scipy.sparse.csr_matrix(
                                (
                                    F_flat_csr.data[p0:],
                                    F_flat_csr.indices[p0:],
                                    F_flat_csr.indptr[start:] - p0,
                                ),
                                shape=(n_act - start, n2),
                                copy=False,
                            )
                        chunks.append((start, end, f_vert, f_tail))
                    F_vert_chunks = tuple(chunks)
            else:
                # F3_blas: manter caminho denso vetorizado + congruência esparsa opcional
                f_cols = np.empty((n2, n_act), dtype=np.float64)
                for idx, j in enumerate(keys):
                    fj = self.F_terms[j]
                    f_cols[:, idx] = fj.ravel()

        object.__setattr__(self, "_active_keys", active_keys)
        object.__setattr__(self, "_F_cols", f_cols)
        object.__setattr__(self, "_f_norm_sum", f_norm_sum)
        object.__setattr__(self, "_sparse_terms", sparse_terms)
        object.__setattr__(self, "schur_mode", schur_mode)
        object.__setattr__(self, "_f1_P", f1_P)
        object.__setattr__(self, "_f1_Q", f1_Q)
        object.__setattr__(self, "_f1_V", f1_V)
        object.__setattr__(self, "_F_flat_csr", F_flat_csr)
        object.__setattr__(self, "_F_vert_chunks", F_vert_chunks)

    def dense_F_cols(self) -> np.ndarray:
        """Retorna representação densa `(dim^2, n_act)` sob demanda."""
        if self._F_cols is not None:
            return self._F_cols
        if self._F_flat_csr is not None:
            return np.asarray(self._F_flat_csr.T.toarray(), dtype=np.float64)
        out_cols = np.empty((self.dim * self.dim, self._active_keys.size), dtype=np.float64)
        for idx, j in enumerate(self._active_keys.tolist()):
            out_cols[:, idx] = self.F_terms[j].ravel()
        return out_cols

    def forward_active(self, v_act: np.ndarray, out: np.ndarray) -> None:
        """Calcula out = sum_i v_act[i] * F_{k_i} sem alocar temporários densos."""
        if self._F_cols is not None:
            np.matmul(self._F_cols, v_act, out=out.ravel())
        elif self._F_flat_csr is not None:
            out.ravel()[:] = self._F_flat_csr.T @ v_act
        else:
            out.fill(0.0)
            for idx, j in enumerate(self._active_keys.tolist()):
                vj = float(v_act[idx])
                if vj != 0.0:
                    out += vj * self.F_terms[j]

    def adjoint_active(self, U: np.ndarray, out: np.ndarray) -> None:
        """Calcula out[i] = <F_{k_i}, U> para todas as variáveis ativas do bloco."""
        if self._F_cols is not None:
            np.matmul(self._F_cols.T, U.ravel(), out=out)
        elif self._F_flat_csr is not None:
            out[:] = self._F_flat_csr @ U.ravel()
        else:
            for idx, j in enumerate(self._active_keys.tolist()):
                out[idx] = float(np.sum(self.F_terms[j] * U))

    def assemble_schur_block(self, W: np.ndarray, out_gram: np.ndarray) -> np.ndarray:
        """Monta a contribuição de Schur H_block[i, j] = tr(F_{k_i} W F_{k_j} W) via F1, F2 ou F3_blas.

        Requer `W` simétrica positiva definida `(dim, dim)` e `out_gram` de forma `(n_act, n_act)`.
        """
        n_act = int(self._active_keys.size)
        if n_act == 0:
            return out_gram
        if self.schur_mode == "F1":
            assert self._f1_P is not None and self._f1_Q is not None and self._f1_V is not None
            P = self._f1_P
            Q = self._f1_Q
            V = self._f1_V
            k_up = P.shape[1]
            out_gram.fill(0.0)
            for a in range(k_up):
                pa = P[:, a]
                qa = Q[:, a]
                va = V[:, a]
                for b in range(a, k_up):
                    pb = P[:, b]
                    qb = Q[:, b]
                    vb = V[:, b]
                    w_term = (
                        W[np.ix_(qa, pb)] * W[np.ix_(pa, qb)]
                        + W[np.ix_(pa, pb)] * W[np.ix_(qa, qb)]
                    )
                    term = (va[:, None] * vb[None, :]) * w_term
                    out_gram += term
                    if b != a:
                        out_gram += term.T
            return out_gram
        if self.schur_mode == "F2":
            assert self._F_flat_csr is not None
            dim = self.dim
            n2 = dim * dim
            for start, end, F_vert_chunk, F_tail_csr in self._F_vert_chunks:
                c_len = end - start
                B_chunk = (F_vert_chunk @ W).reshape((c_len, dim, dim))
                M_chunk = np.matmul(W, B_chunk).reshape((c_len, n2))
                lower_blk = F_tail_csr @ M_chunk.T
                diag_blk = lower_blk[:c_len, :]
                out_gram[start:end, start:end] = 0.5 * (diag_blk + diag_blk.T)
                if end < n_act:
                    off_blk = lower_blk[c_len:, :]
                    out_gram[end:, start:end] = off_blk
                    out_gram[start:end, end:] = off_blk.T
            return out_gram
        # Caminho F3_blas em lotes 3D limitados por _F3_CHUNK_SIZE (seguro para memória Wasm)
        dim = self.dim
        n2 = dim * dim
        F_dense = self.dense_F_cols()
        for start in range(0, n_act, _F3_CHUNK_SIZE):
            end = min(start + _F3_CHUNK_SIZE, n_act)
            c_len = end - start
            F_2d = np.ascontiguousarray(F_dense[:, start:end].T).reshape((c_len * dim, dim))
            B_chunk = (F_2d @ W).reshape((c_len, dim, dim))
            M_chunk = np.matmul(W, B_chunk).reshape((c_len, n2))
            out_gram[:, start:end] = F_dense.T @ M_chunk.T
        out_gram += out_gram.T
        out_gram *= 0.5
        return out_gram

    def evaluate(self, z: np.ndarray) -> np.ndarray:
        if self._active_keys.size == 0:
            return 0.5 * (self.F0 + self.F0.T)
        if self._F_cols is not None:
            lin = (self._F_cols @ z[self._active_keys]).reshape((self.dim, self.dim))
        elif self._F_flat_csr is not None:
            lin = (self._F_flat_csr.T @ z[self._active_keys]).reshape((self.dim, self.dim))
        else:
            lin = np.zeros((self.dim, self.dim), dtype=np.float64)
            for j in self._active_keys.tolist():
                zj = float(z[j])
                if zj != 0.0:
                    lin += zj * self.F_terms[j]
        res = self.F0 + lin
        return 0.5 * (res + res.T)

    def evaluate_linear(self, dz: np.ndarray) -> np.ndarray:
        if self._active_keys.size == 0:
            return np.zeros((self.dim, self.dim), dtype=np.float64)
        if self._F_cols is not None:
            res = (self._F_cols @ dz[self._active_keys]).reshape((self.dim, self.dim))
        elif self._F_flat_csr is not None:
            res = (self._F_flat_csr.T @ dz[self._active_keys]).reshape((self.dim, self.dim))
        else:
            res = np.zeros((self.dim, self.dim), dtype=np.float64)
            for j in self._active_keys.tolist():
                dzj = float(dz[j])
                if dzj != 0.0:
                    res += dzj * self.F_terms[j]
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
        self.forward_active(z_act, tmp)
        tmp += self.F0
        return _sym_into(tmp, out)


def _fill_f3_scaled_cols(
    F_cols: np.ndarray,
    G_invT_b: np.ndarray,
    dim_b: int,
    cols_out: np.ndarray,
) -> None:
    """Preenche cols_out[:, i] = ravel(sym(G_invT_b.T @ F_i @ G_invT_b)) em lotes BLAS limitados."""
    n2 = dim_b * dim_b
    n_act = int(F_cols.shape[1])
    for start in range(0, n_act, _F3_CHUNK_SIZE):
        end = min(start + _F3_CHUNK_SIZE, n_act)
        c_len = end - start
        F_2d = np.ascontiguousarray(F_cols[:, start:end].T).reshape((c_len * dim_b, dim_b))
        B_3d = (F_2d @ G_invT_b).reshape((c_len, dim_b, dim_b))
        C_3d = np.matmul(G_invT_b.T, B_3d)
        C_3d += C_3d.swapaxes(-1, -2)
        C_3d *= 0.5
        cols_out[:, start:end] = C_3d.reshape((c_len, n2)).T


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
    """Fatoração em cache do sistema de Schur simétrico pré-condicionado por Jacobi.

    Suporta dois modos adaptativos:
    - `"dense_cholesky"`: Cholesky regularizado (`scipy.linalg.cho_factor`).
    - `"sparse_splu"`: SuperLU esparso (`scipy.sparse.linalg.splu`, permc_spec="MMD_AT_PLUS_A",
      Demmel, Eisenstat, Gilbert, Li & Liu, SIAM J. Matrix Anal. Appl. 1999,
      doi:10.1137/S0895479895291765) com refino iterativo em $O(\\mathrm{nnz})$.
    """

    n: int
    H_scaled: np.ndarray
    inv_d: np.ndarray
    cho: tuple[np.ndarray, bool] | None
    cond: float
    regularized: bool
    splu: Any | None = None
    H_scaled_csc: scipy.sparse.csc_matrix | None = None
    mode: str = "dense_cholesky"


def _factor_symmetric_system(
    H: np.ndarray,
    *,
    H_scaled_buf: np.ndarray | None = None,
    H_work_buf: np.ndarray | None = None,
    inv_d_buf: np.ndarray | None = None,
    sparse_density_threshold: float = 0.30,
    sparse_min_dim: int = 48,
    factorization_mode: str = "auto",
) -> _FactoredSymmetricSystem:
    """Fatora H uma única vez por iteração com Jacobi + SuperLU esparso ou Cholesky regularizado.

    Referências:
    - Fujisawa et al., IEEE IPDPS 2014 (doi:10.1109/IPDPS.2014.121)
    - Demmel, Eisenstat, Gilbert, Li & Liu, SIAM J. Matrix Anal. Appl. 1999
      (SuperLU, doi:10.1137/S0895479895291765)
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
            mode="dense_cholesky",
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

    def _cond_from_splu(lu_fac: Any) -> tuple[float, float, float]:
        diag_u = np.abs(lu_fac.U.diagonal())
        if diag_u.size == 0:
            return 1.0, 1.0, 1.0
        u_max = float(np.max(diag_u))
        u_min = float(np.min(diag_u))
        if u_max <= 0.0 or not math.isfinite(u_max) or not math.isfinite(u_min):
            return 1e16, 0.0, 0.0
        return float(min(1e16, u_max / max(u_min, 1e-15))), u_min, u_max

    finite_ok = bool(np.all(np.isfinite(H_scaled)))
    if finite_ok:
        # Seleção adaptativa de SuperLU esparso (scipy.sparse.linalg.splu)
        try_sparse = False
        if factorization_mode == "sparse_splu":
            try_sparse = True
        elif factorization_mode == "auto" and n >= sparse_min_dim:
            nnz_h = int(np.count_nonzero(H_scaled))
            if (nnz_h / float(n * n)) < sparse_density_threshold:
                try_sparse = True

        if try_sparse:
            H_csc = scipy.sparse.csc_matrix(H_scaled)
            cond_limit = 1e11 if factorization_mode == "auto" else 1e15
            try:
                lu = scipy.sparse.linalg.splu(
                    H_csc,
                    permc_spec="MMD_AT_PLUS_A",
                    diag_pivot_thresh=0.01,
                    options={"SymmetricMode": True},
                )
                cond_lu, u_min, u_max = _cond_from_splu(lu)
                if u_max > 0.0 and u_min > 1e-14 * max(1.0, u_max) and cond_lu < cond_limit:
                    return _FactoredSymmetricSystem(
                        n=n,
                        H_scaled=H_scaled,
                        inv_d=inv_d,
                        cho=None,
                        cond=cond_lu,
                        regularized=False,
                        splu=lu,
                        H_scaled_csc=H_csc,
                        mode="sparse_splu",
                    )
            except (RuntimeError, ValueError):
                pass

            # Se modo forçado "sparse_splu", tenta regularização diagonal antes de recuar para Cholesky
            if factorization_mode == "sparse_splu":
                h_scale_sp = max(1.0, float(np.max(np.abs(H_scaled))))
                for reg_exp in (1e-13, 1e-11, 1e-9):
                    H_csc_reg = (H_csc + scipy.sparse.diags(np.full(n, reg_exp * h_scale_sp), format="csc")).tocsc()
                    try:
                        lu_reg = scipy.sparse.linalg.splu(
                            H_csc_reg,
                            permc_spec="MMD_AT_PLUS_A",
                            diag_pivot_thresh=0.01,
                            options={"SymmetricMode": True},
                        )
                        cond_reg, u_min_r, u_max_r = _cond_from_splu(lu_reg)
                        if u_max_r > 0.0 and u_min_r > 1e-14 * max(1.0, u_max_r) and cond_reg < 1e15:
                            return _FactoredSymmetricSystem(
                                n=n,
                                H_scaled=H_scaled,
                                inv_d=inv_d,
                                cho=None,
                                cond=cond_reg,
                                regularized=True,
                                splu=lu_reg,
                                H_scaled_csc=H_csc,
                                mode="sparse_splu",
                            )
                    except (RuntimeError, ValueError):
                        continue

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
                mode="dense_cholesky",
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
                    mode="dense_cholesky",
                )

    return _FactoredSymmetricSystem(
        n=n,
        H_scaled=H_scaled,
        inv_d=inv_d,
        cho=None,
        cond=1e16,
        regularized=True,
        mode="dense_cholesky",
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
    """Resolve H dx = rhs usando a fatoração em cache (SuperLU ou Cholesky) + até 2 passos de refino iterativo."""
    if fac.n == 0:
        if out is not None:
            return out
        return np.zeros((0,), dtype=np.float64)

    rhs_scaled = np.multiply(fac.inv_d, rhs, out=rhs_scaled_buf) if rhs_scaled_buf is not None else fac.inv_d * rhs
    if fac.splu is not None:
        sol_s = np.asarray(fac.splu.solve(rhs_scaled), dtype=np.float64)
        if fac.H_scaled_csc is not None:
            res_s = rhs_scaled - (fac.H_scaled_csc @ sol_s)
        else:
            res_s = rhs_scaled - fac.H_scaled @ sol_s
        res_norm = float(np.linalg.norm(res_s))
        rhs_norm = float(np.linalg.norm(rhs_scaled))
        for _ in range(2):
            if res_norm <= 1e-15 * (1.0 + rhs_norm):
                break
            corr_s = np.asarray(fac.splu.solve(res_s), dtype=np.float64)
            if not np.all(np.isfinite(corr_s)):
                break
            cand_s = sol_s + corr_s
            if fac.H_scaled_csc is not None:
                new_res_s = rhs_scaled - (fac.H_scaled_csc @ cand_s)
            else:
                new_res_s = rhs_scaled - fac.H_scaled @ cand_s
            new_res_norm = float(np.linalg.norm(new_res_s))
            if new_res_norm < res_norm:
                sol_s = cand_s
                res_s = new_res_s
                res_norm = new_res_norm
            else:
                break
        if out is not None:
            return np.multiply(fac.inv_d, sol_s, out=out)
        return np.asarray(fac.inv_d * sol_s, dtype=np.float64)

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

    Usa correção ponderada vetorizada dZ_b = W_b (sum_j y_j F_{b,j}) W_b resolvida via Schur/Cholesky.
    """
    if m_vars == 0:
        return [_sym(Z) for Z in Z_list]

    adj = np.zeros((m_vars,), dtype=np.float64)
    for blk, Z_b in zip(blocks, Z_list, strict=True):
        ak = blk._active_keys
        if ak.size > 0:
            act_buf = np.empty((ak.size,), dtype=np.float64)
            blk.adjoint_active(Z_b, act_buf)
            adj[ak] += act_buf
    res = target_c - adj
    if float(np.linalg.norm(res)) <= 1e-14 * (1.0 + float(np.linalg.norm(target_c))):
        return [_sym(Z) for Z in Z_list]

    W_list: list[np.ndarray] = []
    if weight_mats is not None:
        W_list = [_sym(W) for W in weight_mats]
    else:
        for Z_b in Z_list:
            W_list.append(_sym(Z_b) + 1e-6 * np.eye(Z_b.shape[0], dtype=np.float64))

    # Montar matriz de Gram G_{i,j} = sum_b tr(F_{b,i} W_b F_{b,j} W_b) reutilizando assemble_schur_block
    G = np.zeros((m_vars, m_vars), dtype=np.float64)
    for blk, W_b in zip(blocks, W_list, strict=True):
        ak = blk._active_keys
        n_act = int(ak.size)
        if n_act == 0:
            continue
        if blk.dim == 1:
            w_val = float(W_b[0, 0])
            f_row = (
                blk._F_cols[0, :]
                if blk._F_cols is not None
                else np.fromiter((float(blk.F_terms[int(j)][0, 0]) for j in ak), dtype=np.float64, count=n_act)
            )
            gram = (w_val * w_val) * np.outer(f_row, f_row)
        else:
            gram = np.empty((n_act, n_act), dtype=np.float64)
            blk.assemble_schur_block(W_b, gram)
        if n_act == m_vars and int(ak[0]) == 0 and int(ak[-1]) == m_vars - 1:
            G += gram
        else:
            G[np.ix_(ak, ak)] += gram

    y_corr, _ = _solve_symmetric_system(G, res)
    Z_new: list[np.ndarray] = []
    for blk, Z_b, W_b in zip(blocks, Z_list, W_list, strict=True):
        ak = blk._active_keys
        n_act = int(ak.size)
        if n_act == 0:
            Z_cand = _sym(Z_b)
        elif blk.dim == 1:
            w_val = float(W_b[0, 0])
            f_row = (
                blk._F_cols[0, :]
                if blk._F_cols is not None
                else np.fromiter((float(blk.F_terms[int(j)][0, 0]) for j in ak), dtype=np.float64, count=n_act)
            )
            dz_val = (w_val * w_val) * float(np.dot(f_row, y_corr[ak]))
            Z_cand = np.array([[float(Z_b[0, 0]) + dz_val]], dtype=np.float64)
        else:
            lin_b = np.empty((blk.dim, blk.dim), dtype=np.float64)
            blk.forward_active(y_corr[ak], lin_b)
            dZ = _sym(W_b @ lin_b @ W_b)
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
        ak = blk._active_keys
        if ak.size > 0:
            act_buf = np.empty((ak.size,), dtype=np.float64)
            blk.adjoint_active(Z_b, act_buf)
            adj_new[ak] += act_buf
            adj_scale += blk._f_norm_sum * float(np.linalg.norm(Z_b, "fro"))
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


def _gondzio_psd_delta_M(
    lam_b: np.ndarray,
    ds_t: np.ndarray,
    dz_t: np.ndarray,
    alpha_trial: float,
    mu_target: float,
    beta_min: float,
    beta_max: float,
    out_dM: np.ndarray,
    tmp1: np.ndarray,
    tmp2: np.ndarray,
    diag_idx: np.ndarray,
) -> bool:
    """Calcula perturbação NT simetrizada delta_M_b do corretor de centralidade de Gondzio (1996).

    Retorna True se houve perturbação não-nula, False se o produto de complementaridade já
    estiver inteiramente dentro da caixa de centralidade [beta_min * mu_target, beta_max * mu_target].
    """
    np.multiply(ds_t, alpha_trial, out=tmp1)
    tmp1[diag_idx, diag_idx] += lam_b
    np.multiply(dz_t, alpha_trial, out=tmp2)
    tmp2[diag_idx, diag_idx] += lam_b
    V_prod = tmp1 @ tmp2
    _sym_into(V_prod, tmp1)
    evals, evecs = np.linalg.eigh(tmp1)
    lo = beta_min * mu_target
    hi = beta_max * mu_target
    clipped = np.clip(evals, lo, hi)
    diff = np.clip(clipped - evals, -hi, hi)
    if float(np.max(np.abs(diff))) <= 1e-16:
        out_dM.fill(0.0)
        return False
    np.multiply(evecs, diff[None, :], out=tmp2)
    np.matmul(tmp2, evecs.T, out=tmp1)
    np.add.outer(lam_b, lam_b, out=tmp2)
    np.maximum(tmp2, 1e-30, out=tmp2)
    tmp1 *= 2.0
    np.divide(tmp1, tmp2, out=tmp1)
    _sym_into(tmp1, out_dM)
    return True


def _count_schur_modes(blocks: Sequence[_InternalConeBlock]) -> dict[str, int]:
    """Conta quantos blocos usam cada fórmula de montagem de Schur (F1, F2, F3_blas, LP_1D)."""
    counts = {"F1": 0, "F2": 0, "F3_blas": 0, "LP_1D": 0}
    for blk in blocks:
        mode = blk.schur_mode
        if mode in counts:
            counts[mode] += 1
        else:
            counts["F3_blas"] += 1
    return counts


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
    max_gondzio_correctors: int = 2,
    sparse_schur_density_threshold: float = 0.30,
    sparse_schur_min_dim: int = 48,
    schur_factorization_mode: str = "auto",
    t_start: float | None = None,
    iteration_log: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[dict[str, Any]], Any] | None = None,
    cancel_check: Callable[[], Any] | None = None,
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
    cols_bufs: list[np.ndarray | None] = []
    W_psd_bufs: list[np.ndarray] = []
    gram_bufs: list[np.ndarray | None] = []
    dS_tilde_aff_bufs: list[np.ndarray] = []
    dZ_tilde_aff_bufs: list[np.ndarray] = []
    M_cor_bufs: list[np.ndarray] = []
    dZ_psd_bufs: list[np.ndarray] = []
    tmp1_bufs: list[np.ndarray] = []
    tmp2_bufs: list[np.ndarray] = []
    tmp3_bufs: list[np.ndarray] = []
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
        cols_bufs.append(
            None if blk.schur_mode in ("F1", "F2") else np.empty((dim * dim, n_act), dtype=np.float64)
        )
        W_psd_bufs.append(np.empty((dim, dim), dtype=np.float64))
        gram_bufs.append(np.empty((n_act, n_act), dtype=np.float64) if n_act > 0 else None)
        dS_tilde_aff_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dZ_tilde_aff_bufs.append(np.empty((dim, dim), dtype=np.float64))
        M_cor_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dZ_psd_bufs.append(np.empty((dim, dim), dtype=np.float64))
        tmp1_bufs.append(tmp1_b)
        tmp2_bufs.append(tmp2_b)
        tmp3_bufs.append(np.empty((dim, dim), dtype=np.float64))
        act_vec_bufs.append(np.empty((n_act,), dtype=np.float64) if n_act > 0 else None)
        is_full_m.append(
            n_act == m and n_act > 0 and int(blk._active_keys[0]) == 0 and int(blk._active_keys[-1]) == m - 1
        )

    def _psd_adjoint_hat(pos: int, T_mat: np.ndarray, act_buf: np.ndarray) -> None:
        cols_b = cols_bufs[pos]
        if cols_b is not None:
            np.matmul(cols_b.T, T_mat.ravel(), out=act_buf)
        else:
            G_invT_b = G_invT_psd[pos]
            t2 = tmp2_bufs[pos]
            t3 = tmp3_bufs[pos]
            np.matmul(G_invT_b, T_mat, out=t2)
            np.matmul(t2, G_invT_b.T, out=t3)
            psd_blocks[pos].adjoint_active(t3, act_buf)

    def _psd_forward_hat(pos: int, v_act: np.ndarray, out_mat: np.ndarray) -> None:
        cols_b = cols_bufs[pos]
        if cols_b is not None:
            np.matmul(cols_b, v_act, out=out_mat.ravel())
        else:
            G_invT_b = G_invT_psd[pos]
            t2 = tmp2_bufs[pos]
            t3 = tmp3_bufs[pos]
            psd_blocks[pos].forward_active(v_act, t2)
            np.matmul(G_invT_b.T, t2, out=t3)
            np.matmul(t3, G_invT_b, out=out_mat)

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
    factorizations = 0
    sparse_factorizations = 0
    dense_factorizations = 0
    gondzio_attempted = 0
    gondzio_accepted = 0
    best_opt_score = float("inf")
    best_opt_rp = float("inf")
    best_opt_rd = float("inf")
    best_opt_state: tuple[
        np.ndarray,
        np.ndarray | None,
        np.ndarray | None,
        list[np.ndarray],
        list[tuple[np.ndarray, bool]],
    ] | None = None

    for it in range(max_iter):
        if callable(cancel_check) and cancel_check():
            raise CancelledError("Resolução SDP cancelada cooperativamente via cancel_check.")
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
                blk.adjoint_active(Z_b, act_buf)
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

        # Salvaguarda de piso numérico float64 em Fase II (paridade com HSDE 1b'):
        # se já atingimos <= 1e-9 em primal/dual/gap e os resíduos voltam a crescer >10x
        # por condicionamento extremo de H perto de mu ~ 1e-14, restaurar melhor iterado.
        if check_farkas_on_blocks is None and min_eig_p >= -1e-8:
            cur_score_p2 = max(rel_gap, comp_rel, r_d_rel, primal_slack_err)
            if cur_score_p2 <= 1e-9 and cur_score_p2 < best_opt_score:
                best_opt_score = cur_score_p2
                best_opt_rp = primal_slack_err
                best_opt_rd = r_d_rel
                best_opt_state = (
                    z.copy(),
                    z_lp.copy() if z_lp is not None else None,
                    s_lp.copy() if s_lp is not None else None,
                    [Zb.copy() for Zb in Z_psd_list],
                    [(cho_S_psd[pos][0].copy(), cho_S_psd[pos][1]) for pos in range(n_psd_blocks)],
                )
            elif (
                best_opt_state is not None
                and best_opt_score <= 1e-9
                and (
                    primal_slack_err > 10.0 * max(best_opt_rp, 1e-12)
                    or r_d_rel > 10.0 * max(best_opt_rd, 1e-12)
                )
            ):
                np.copyto(z, best_opt_state[0])
                if q_lp > 0 and best_opt_state[1] is not None and best_opt_state[2] is not None:
                    assert z_lp is not None and s_lp is not None
                    np.copyto(z_lp, best_opt_state[1])
                    np.copyto(s_lp, best_opt_state[2])
                for pos in range(n_psd_blocks):
                    np.copyto(Z_psd_list[pos], best_opt_state[3][pos])
                    cho_S_psd[pos] = best_opt_state[4][pos]
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

        # 2b. Blocos PSD (dim >= 2): montagem de Schur F1/F2 esparsa ou F3 BLAS denso in-place em H
        for pos, blk in enumerate(psd_blocks):
            _, G_invT_b, lam_b = _nt_scaling_factors(cho_S_psd[pos], cho_Z_psd[pos])
            G_invT_psd[pos] = G_invT_b
            lam_psd[pos] = lam_b
            active_keys = blk._active_keys
            n_act = int(active_keys.size)
            cols = cols_bufs[pos]
            tmp1 = tmp1_bufs[pos]
            tmp2 = tmp2_bufs[pos]

            np.matmul(G_invT_b.T, R_p_psd_bufs[pos], out=tmp1)
            np.matmul(tmp1, G_invT_b, out=tmp2)
            _sym_into(tmp2, R_p_hat_bufs[pos])

            if n_act > 0:
                gram = gram_bufs[pos]
                assert gram is not None
                if cols is None:
                    # Fórmulas F1 / F2 (Fujisawa-Kojima-Nakata 1997): W = G_invT @ G_invT.T
                    W_b = W_psd_bufs[pos]
                    np.matmul(G_invT_b, G_invT_b.T, out=tmp1)
                    _sym_into(tmp1, W_b)
                    blk.assemble_schur_block(W_b, gram)
                else:
                    if blk._F_cols is not None and n_act >= 4:
                        _fill_f3_scaled_cols(blk._F_cols, G_invT_b, blk.dim, cols)
                    else:
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
                    np.matmul(cols.T, cols, out=gram)
                if is_full_m[pos]:
                    H += gram
                else:
                    H[np.ix_(active_keys, active_keys)] += gram

        # Fatorar o sistema de Schur uma única vez por iteração usando buffers pré-alocados
        fac_H = _factor_symmetric_system(
            H,
            H_scaled_buf=H_scaled_buf,
            H_work_buf=H_work_buf,
            inv_d_buf=inv_d_buf,
            sparse_density_threshold=sparse_schur_density_threshold,
            sparse_min_dim=sparse_schur_min_dim,
            factorization_mode=schur_factorization_mode,
        )
        factorizations += 1
        if fac_H.mode == "sparse_splu":
            sparse_factorizations += 1
        else:
            dense_factorizations += 1
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
                _psd_adjoint_hat(pos, tmp1, act_buf)
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
                _psd_forward_hat(pos, dz_act, tmp1)
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
                _psd_adjoint_hat(pos, tmp1, act_buf)
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
                _psd_forward_hat(pos, dz_act, tmp1)
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

        # 4b. Múltiplos Corretores de Centralidade de Gondzio (1996, doi:10.1007/BF00249643)
        # Reutiliza a MESMA fatoração de Cholesky `fac_H` (O(m^2)) quando 0.05 <= min(alpha_p, alpha_d) < 0.95.
        alpha_min = min(alpha_p, alpha_d)
        if max_gondzio_correctors > 0 and 0.05 <= alpha_min < 0.95 and mu > 1e-10 and fac_H.cho is not None:
            mu_target = max(sigma * mu, 1e-16)
            beta_min_g = 0.1
            beta_max_g = 10.0
            for _g_idx in range(max_gondzio_correctors):
                if alpha_min >= 0.95:
                    break
                gondzio_attempted += 1
                alpha_trial_p = min(1.0, alpha_p + max(0.08, 0.1 * (1.0 - alpha_p)))
                alpha_trial_d = min(1.0, alpha_d + max(0.08, 0.1 * (1.0 - alpha_d)))
                rhs_gon = np.zeros((m,), dtype=np.float64)
                has_pert = False

                drc_lp_g: np.ndarray | None = None
                if q_lp > 0:
                    assert s_lp is not None and z_lp is not None and ds_lp is not None and dz_lp is not None
                    assert s_lp_safe is not None and w_lp is not None
                    v_lp = (s_lp + alpha_trial_p * ds_lp) * (z_lp + alpha_trial_d * dz_lp)
                    lo_g = beta_min_g * mu_target
                    hi_g = beta_max_g * mu_target
                    t_lp = np.clip(v_lp, lo_g, hi_g)
                    drc_lp_g = np.clip(t_lp - v_lp, -hi_g, hi_g)
                    if float(np.max(np.abs(drc_lp_g))) > 1e-16:
                        has_pert = True
                        b_lp_g = drc_lp_g / s_lp_safe
                        if use_sparse_lp:
                            assert F_lp_csc is not None
                            rhs_gon += F_lp_csc.T @ b_lp_g
                        else:
                            assert F_lp_dense is not None
                            np.matmul(F_lp_dense.T, b_lp_g, out=m_scratch)
                            rhs_gon += m_scratch

                dM_psd_g: list[np.ndarray] = []
                alpha_trial_psd = min(alpha_trial_p, alpha_trial_d)
                for pos, blk in enumerate(psd_blocks):
                    dM_b = np.empty((blk.dim, blk.dim), dtype=np.float64)
                    changed = _gondzio_psd_delta_M(
                        lam_psd[pos],
                        dS_tilde_aff_bufs[pos],
                        dZ_tilde_aff_bufs[pos],
                        alpha_trial_psd,
                        mu_target,
                        beta_min_g,
                        beta_max_g,
                        dM_b,
                        tmp1_bufs[pos],
                        tmp2_bufs[pos],
                        diag_psd[pos],
                    )
                    dM_psd_g.append(dM_b)
                    if changed:
                        has_pert = True
                        active_keys = blk._active_keys
                        if active_keys.size > 0:
                            act_buf = act_vec_bufs[pos]
                            assert act_buf is not None
                            _psd_adjoint_hat(pos, dM_b, act_buf)
                            if is_full_m[pos]:
                                rhs_gon += act_buf
                            else:
                                rhs_gon[active_keys] += act_buf

                if not has_pert:
                    break

                ddz_g = _solve_factored_symmetric(
                    fac_H,
                    rhs_gon,
                    rhs_scaled_buf=rhs_scaled_buf,
                    res_s_buf=res_s_buf,
                    mv_buf=m_scratch,
                )
                if not np.all(np.isfinite(ddz_g)):
                    break

                dz_cand = dz + ddz_g
                alpha_p_max_c = float("inf")
                alpha_d_max_c = float("inf")
                ds_lp_cand: np.ndarray | None = None
                dz_lp_cand: np.ndarray | None = None
                if q_lp > 0:
                    assert s_lp is not None and z_lp is not None and s_lp_safe is not None and w_lp is not None
                    assert ds_lp is not None and dz_lp is not None and drc_lp_g is not None
                    if use_sparse_lp:
                        assert F_lp_csr is not None
                        dds_lp = F_lp_csr @ ddz_g
                    else:
                        assert F_lp_dense is not None
                        dds_lp = F_lp_dense @ ddz_g
                    ddz_lp = drc_lp_g / s_lp_safe - w_lp * dds_lp
                    ds_lp_cand = ds_lp + dds_lp
                    dz_lp_cand = dz_lp + ddz_lp
                    if not np.all(np.isfinite(ds_lp_cand)):
                        alpha_p_max_c = 0.0
                    else:
                        neg_p_c = ds_lp_cand < -1e-15 * s_lp_safe
                        if np.any(neg_p_c):
                            alpha_p_max_c = min(alpha_p_max_c, float(np.min(-s_lp[neg_p_c] / ds_lp_cand[neg_p_c])))
                    if not np.all(np.isfinite(dz_lp_cand)):
                        alpha_d_max_c = 0.0
                    else:
                        neg_d_c = dz_lp_cand < -1e-15 * np.maximum(z_lp, 1e-30)
                        if np.any(neg_d_c):
                            alpha_d_max_c = min(alpha_d_max_c, float(np.min(-z_lp[neg_d_c] / dz_lp_cand[neg_d_c])))

                ds_t_cands: list[np.ndarray] = []
                dz_t_cands: list[np.ndarray] = []
                for pos, blk in enumerate(psd_blocks):
                    active_keys = blk._active_keys
                    tmp1 = tmp1_bufs[pos]
                    tmp2 = tmp2_bufs[pos]
                    if active_keys.size > 0:
                        ddz_act = ddz_g if is_full_m[pos] else ddz_g[active_keys]
                        _psd_forward_hat(pos, ddz_act, tmp1)
                        dds_t = _sym(tmp1)
                    else:
                        dds_t = np.zeros((blk.dim, blk.dim), dtype=np.float64)
                    ddz_t = _sym(dM_psd_g[pos] - dds_t)
                    ds_tc = _sym(dS_tilde_aff_bufs[pos] + dds_t)
                    dz_tc = _sym(dZ_tilde_aff_bufs[pos] + ddz_t)
                    ds_t_cands.append(ds_tc)
                    dz_t_cands.append(dz_tc)
                    alpha_p_max_c = min(
                        alpha_p_max_c, _max_step_scaled_identity(lam_psd[pos], ds_tc, work1=tmp1, work2=tmp2)
                    )
                    alpha_d_max_c = min(
                        alpha_d_max_c, _max_step_scaled_identity(lam_psd[pos], dz_tc, work1=tmp1, work2=tmp2)
                    )

                alpha_p_c = min(1.0, step_fraction * alpha_p_max_c)
                alpha_d_c = min(1.0, step_fraction * alpha_d_max_c)
                alpha_min_c = min(alpha_p_c, alpha_d_c)

                if alpha_min_c >= alpha_min + 0.05:
                    np.copyto(dz, dz_cand)
                    if q_lp > 0:
                        assert ds_lp is not None and dz_lp is not None
                        assert ds_lp_cand is not None and dz_lp_cand is not None
                        np.copyto(ds_lp, ds_lp_cand)
                        np.copyto(dz_lp, dz_lp_cand)
                    for pos in range(n_psd_blocks):
                        np.copyto(dS_tilde_aff_bufs[pos], ds_t_cands[pos])
                        np.copyto(dZ_tilde_aff_bufs[pos], dz_t_cands[pos])
                        G_invT_b = G_invT_psd[pos]
                        np.matmul(G_invT_b, dz_t_cands[pos], out=tmp1_bufs[pos])
                        np.matmul(tmp1_bufs[pos], G_invT_b.T, out=tmp2_bufs[pos])
                        _sym_into(tmp2_bufs[pos], dZ_psd_bufs[pos])
                    alpha_p = alpha_p_c
                    alpha_d = alpha_d_c
                    alpha_min = alpha_min_c
                    gondzio_accepted += 1
                else:
                    break

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
                act_f = np.empty((blk._active_keys.size,), dtype=np.float64)
                blk.adjoint_active(Z_b, act_f)
                adj[blk._active_keys] += act_f
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
        W_psd_bufs,
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
        tmp3_bufs,
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
        "factorizations": factorizations,
        "gondzio_correctors_attempted": gondzio_attempted,
        "gondzio_correctors_accepted": gondzio_accepted,
        "schur_assembly_modes": _count_schur_modes(blocks),
        "schur_factorization_mode": (
            "sparse_splu"
            if sparse_factorizations > 0 and sparse_factorizations >= dense_factorizations
            else "dense_cholesky"
        ),
    }


def _run_hsde_cone_loop(
    blocks: Sequence[_InternalConeBlock],
    c_vec: np.ndarray,
    c0: float,
    *,
    max_iter: int,
    tol_gap: float,
    tol_feas: float,
    strict_margin: float,
    step_fraction: float,
    sigma_min: float,
    sigma_max: float,
    max_gondzio_correctors: int = 2,
    sparse_schur_density_threshold: float = 0.30,
    sparse_schur_min_dim: int = 48,
    schur_factorization_mode: str = "auto",
    t_start: float | None = None,
    iteration_log: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[dict[str, Any]], Any] | None = None,
    cancel_check: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Embedding Homogêneo Autodual (HSDE) em fase única com NT + Mehrotra + Gondzio (ADR-015 Ciclo 2).

    Resolve em passagem única (sem Fase I separada):
        min_{z in R^m}   c_vec^T z + c0
        sujeito a        S_b = F_{b,0} + sum_{j=0}^{m-1} z_j F_{b,j} >= 0

    Formulação homogênea autodual com escalares (tau > 0, kappa > 0):
        r_d = tau * c_vec - A*(Z) = 0
        r_p = S - A(z) - tau * F0 = 0
        r_g = kappa + c_vec^T z + <F0, Z> = 0
        S o Z = 0,  tau * kappa = 0,  (S, Z) in K x K,  (tau, kappa) >= 0.

    Eliminação em bloco de Delta_tau via 2 backsolves sobre o MESMO fator de Cholesky de H
    (Sturm 1999; Goulart & Chen 2024), múltiplos corretores de centralidade de Gondzio (1996),
    cone LP 1D unificado para blocos 1x1 e workspace in-place pré-alocado.
    """
    m = int(c_vec.shape[0])
    n_blocks = len(blocks)
    total_order = sum(b.dim for b in blocks)
    c_norm = float(np.linalg.norm(c_vec))
    c_scale = max(1.0, c_norm)
    is_pure_feas = c_norm <= 1e-12
    f0_scale = max(1.0, sum(float(np.linalg.norm(b.F0, "fro")) for b in blocks))

    # Particionar blocos 1x1 (cone LP 1D unificado) vs blocos PSD (dim >= 2)
    lp_indices: list[int] = [i for i, b in enumerate(blocks) if b.dim == 1]
    psd_indices: list[int] = [i for i, b in enumerate(blocks) if b.dim > 1]
    psd_blocks: list[_InternalConeBlock] = [blocks[i] for i in psd_indices]
    q_lp = len(lp_indices)
    n_psd_blocks = len(psd_blocks)

    # Workspace do cone LP 1D
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

        s_lp = np.ones((q_lp,), dtype=np.float64)
        z_lp = np.ones((q_lp,), dtype=np.float64)
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

    # Workspace de Schur e vetores de direção (tamanho m)
    z = np.zeros((m,), dtype=np.float64)
    tau = 1.0
    kappa = 1.0

    H = np.empty((m, m), dtype=np.float64)
    H_scaled_buf = np.empty((m, m), dtype=np.float64)
    H_work_buf = np.empty((m, m), dtype=np.float64, order="F")
    inv_d_buf = np.empty((m,), dtype=np.float64)
    adj = np.empty((m,), dtype=np.float64)
    r_d = np.empty((m,), dtype=np.float64)
    g0 = np.empty((m,), dtype=np.float64)
    q_z = np.empty((m,), dtype=np.float64)
    p_z = np.empty((m,), dtype=np.float64)
    c_minus_g0 = np.empty((m,), dtype=np.float64)
    rhs_buf = np.empty((m,), dtype=np.float64)
    dz_aff = np.empty((m,), dtype=np.float64)
    dz = np.empty((m,), dtype=np.float64)
    rhs_scaled_buf = np.empty((m,), dtype=np.float64)
    res_s_buf = np.empty((m,), dtype=np.float64)
    m_scratch = np.empty((m,), dtype=np.float64)

    # Workspace por bloco PSD (dim >= 2)
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
    F0_hat_bufs: list[np.ndarray] = []
    cols_bufs: list[np.ndarray | None] = []
    W_psd_bufs: list[np.ndarray] = []
    gram_bufs: list[np.ndarray | None] = []
    dS_tilde_aff_bufs: list[np.ndarray] = []
    dZ_tilde_aff_bufs: list[np.ndarray] = []
    dS_tilde_cor_bufs: list[np.ndarray] = []
    dZ_tilde_cor_bufs: list[np.ndarray] = []
    M_cor_bufs: list[np.ndarray] = []
    dM_gon_bufs: list[np.ndarray] = []
    dS_psd_bufs: list[np.ndarray] = []
    dZ_psd_bufs: list[np.ndarray] = []
    tmp1_bufs: list[np.ndarray] = []
    tmp2_bufs: list[np.ndarray] = []
    tmp3_bufs: list[np.ndarray] = []
    act_vec_bufs: list[np.ndarray | None] = []
    is_full_m: list[bool] = []
    G_psd: list[np.ndarray] = [np.empty((0, 0), dtype=np.float64)] * n_psd_blocks
    G_invT_psd: list[np.ndarray] = [np.empty((0, 0), dtype=np.float64)] * n_psd_blocks
    lam_psd: list[np.ndarray] = [np.empty((0,), dtype=np.float64)] * n_psd_blocks

    for blk in psd_blocks:
        dim = blk.dim
        n_act = int(blk._active_keys.size)
        eye_b = np.eye(dim, dtype=np.float64)
        diag_b = np.arange(dim, dtype=np.intp)
        eye_psd.append(eye_b)
        diag_psd.append(diag_b)

        S_b = eye_b.copy()
        Z_b = eye_b.copy()
        cho_s_work = np.empty((dim, dim), dtype=np.float64, order="F")
        cho_s_trial = np.empty((dim, dim), dtype=np.float64, order="F")
        cho_z_work = np.empty((dim, dim), dtype=np.float64, order="F")
        cho_z_trial = np.empty((dim, dim), dtype=np.float64, order="F")
        cho_s = _safe_cholesky_buf(S_b, cho_s_work)
        cho_z = _safe_cholesky_buf(Z_b, cho_z_work)
        assert cho_s is not None and cho_z is not None

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
        F0_hat_bufs.append(np.empty((dim, dim), dtype=np.float64))
        cols_bufs.append(
            None if blk.schur_mode in ("F1", "F2") else np.empty((dim * dim, n_act), dtype=np.float64)
        )
        W_psd_bufs.append(np.empty((dim, dim), dtype=np.float64))
        gram_bufs.append(np.empty((n_act, n_act), dtype=np.float64) if n_act > 0 else None)
        dS_tilde_aff_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dZ_tilde_aff_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dS_tilde_cor_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dZ_tilde_cor_bufs.append(np.empty((dim, dim), dtype=np.float64))
        M_cor_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dM_gon_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dS_psd_bufs.append(np.empty((dim, dim), dtype=np.float64))
        dZ_psd_bufs.append(np.empty((dim, dim), dtype=np.float64))
        tmp1_bufs.append(np.empty((dim, dim), dtype=np.float64))
        tmp2_bufs.append(np.empty((dim, dim), dtype=np.float64))
        tmp3_bufs.append(np.empty((dim, dim), dtype=np.float64))
        act_vec_bufs.append(np.empty((n_act,), dtype=np.float64) if n_act > 0 else None)
        is_full_m.append(
            n_act == m and n_act > 0 and int(blk._active_keys[0]) == 0 and int(blk._active_keys[-1]) == m - 1
        )

    def _psd_adjoint_hat(pos: int, T_mat: np.ndarray, act_buf: np.ndarray) -> None:
        cols_b = cols_bufs[pos]
        if cols_b is not None:
            np.matmul(cols_b.T, T_mat.ravel(), out=act_buf)
        else:
            G_invT_b = G_invT_psd[pos]
            t2 = tmp2_bufs[pos]
            t3 = tmp3_bufs[pos]
            np.matmul(G_invT_b, T_mat, out=t2)
            np.matmul(t2, G_invT_b.T, out=t3)
            psd_blocks[pos].adjoint_active(t3, act_buf)

    def _psd_forward_hat(pos: int, v_act: np.ndarray, out_mat: np.ndarray) -> None:
        cols_b = cols_bufs[pos]
        if cols_b is not None:
            np.matmul(cols_b, v_act, out=out_mat.ravel())
        else:
            G_invT_b = G_invT_psd[pos]
            t2 = tmp2_bufs[pos]
            t3 = tmp3_bufs[pos]
            psd_blocks[pos].forward_active(v_act, t2)
            np.matmul(G_invT_b.T, t2, out=t3)
            np.matmul(t3, G_invT_b, out=out_mat)

    history: list[IterationRecord] = []
    iter_log: list[dict[str, Any]] = iteration_log if iteration_log is not None else []
    t0 = t_start if t_start is not None else time.perf_counter()
    solver_status = "max_iterations"
    hsde_certificate = "none"
    pure_feas_zero_dual = False
    farkas_candidate: list[np.ndarray] | None = None
    farkas_dual_res_rel: float | None = None
    farkas_objective: float | None = None
    recession_candidate: np.ndarray | None = None
    factorizations = 0
    sparse_factorizations = 0
    dense_factorizations = 0
    gondzio_attempted = 0
    gondzio_accepted = 0
    best_opt_score = float("inf")
    best_opt_state: tuple[np.ndarray, float, list[np.ndarray]] | None = None
    best_opt_rp = float("inf")
    best_opt_rd = float("inf")

    def _unpack_Z_scaled(scale_factor: float = 1.0) -> list[np.ndarray]:
        out_Z: list[np.ndarray] = [None] * n_blocks  # type: ignore[list-item]
        if q_lp > 0:
            assert z_lp is not None
            for pos, orig_i in enumerate(lp_indices):
                out_Z[orig_i] = np.array([[float(z_lp[pos]) * scale_factor]], dtype=np.float64)
        for pos, orig_i in enumerate(psd_indices):
            out_Z[orig_i] = _sym(Z_psd_list[pos] * scale_factor)
        return out_Z

    try:
        for it in range(max_iter):
            if callable(cancel_check) and cancel_check():
                raise CancelledError("Resolução SDP (HSDE) cancelada cooperativamente via cancel_check.")

            # 1. Resíduos homogêneos r_p = S - A(z) - tau*F0, r_d = tau*c - A*(Z), r_g = kappa + c^T z + <F0, Z>
            rp_norm = 0.0
            gap = 0.0
            adj.fill(0.0)
            dual_scale_z = 0.0
            dual_f0_dot = 0.0
            comp_scale_sz = 0.0
            z_dual_norm = 0.0
            min_eig_p_hom = float("inf")
            min_eig_d_hom = float("inf")

            if q_lp > 0:
                assert s_lp is not None and z_lp is not None and s_lp_eval is not None
                assert rp_lp is not None and F0_lp is not None and f_lp_row_norms is not None
                if use_sparse_lp:
                    assert F_lp_csr is not None and F_lp_csc is not None
                    s_lp_eval[:] = F_lp_csr @ z
                    adj += F_lp_csc.T @ z_lp
                else:
                    assert F_lp_dense is not None
                    np.matmul(F_lp_dense, z, out=s_lp_eval)
                    np.matmul(F_lp_dense.T, z_lp, out=adj)
                s_lp_eval += tau * F0_lp
                np.subtract(s_lp, s_lp_eval, out=rp_lp)
                rp_norm = max(rp_norm, float(np.max(np.abs(rp_lp))))
                gap += float(np.dot(s_lp, z_lp))
                dual_scale_z += float(np.dot(f_lp_row_norms, np.abs(z_lp)))
                dual_f0_dot += float(np.dot(F0_lp, z_lp))
                comp_scale_sz += float(np.dot(np.abs(s_lp), np.abs(z_lp)))
                z_dual_norm += float(np.linalg.norm(z_lp))
                min_eig_p_hom = min(min_eig_p_hom, float(np.min(s_lp_eval)))
                min_eig_d_hom = min(min_eig_d_hom, float(np.min(z_lp)))

            for pos, blk in enumerate(psd_blocks):
                S_b = S_psd_list[pos]
                S_ev = S_eval_bufs[pos]
                Z_b = Z_psd_list[pos]
                tmp1 = tmp1_bufs[pos]
                if blk._active_keys.size > 0:
                    z_act = z if is_full_m[pos] else z[blk._active_keys]
                    blk.forward_active(z_act, tmp1)
                    tmp1 += tau * blk.F0
                    _sym_into(tmp1, S_ev)
                    act_buf = act_vec_bufs[pos]
                    assert act_buf is not None
                    blk.adjoint_active(Z_b, act_buf)
                    if is_full_m[pos]:
                        adj += act_buf
                    else:
                        adj[blk._active_keys] += act_buf
                else:
                    np.multiply(blk.F0, tau, out=tmp1)
                    _sym_into(tmp1, S_ev)
                np.subtract(S_b, S_ev, out=R_p_psd_bufs[pos])
                rp_norm = max(rp_norm, float(np.linalg.norm(R_p_psd_bufs[pos], "fro")))
                gap += float(np.sum(S_b * Z_b))
                z_norm_b = float(np.linalg.norm(Z_b, "fro"))
                z_dual_norm += z_norm_b
                if blk._active_keys.size > 0:
                    dual_scale_z += blk._f_norm_sum * z_norm_b
                dual_f0_dot += float(np.sum(blk.F0 * Z_b))
                comp_scale_sz += float(np.linalg.norm(S_b, "fro")) * z_norm_b
                min_eig_p_hom = min(min_eig_p_hom, float(np.min(np.linalg.eigvalsh(S_ev))))
                min_eig_d_hom = min(min_eig_d_hom, float(np.min(np.linalg.eigvalsh(Z_b))))

            tau_safe = max(tau, 1e-30)
            inv_tau = 1.0 / tau_safe
            mu = (gap + tau * kappa) / max(1, total_order + 1)
            np.multiply(c_vec, tau, out=r_d)
            r_d -= adj
            r_g = kappa + float(np.dot(c_vec, z)) + dual_f0_dot

            dual_scale = tau_safe * (1.0 + c_norm) + dual_scale_z
            r_d_rel = float(np.linalg.norm(r_d) / max(dual_scale, 1e-30))
            rp_unhom = rp_norm * inv_tau
            min_eig_p = min_eig_p_hom * inv_tau
            min_eig_d = min_eig_d_hom * inv_tau
            primal_obj = float(np.dot(c_vec, z) * inv_tau + c0)
            dual_obj = float(c0 - dual_f0_dot * inv_tau)
            rel_gap = abs(primal_obj - dual_obj) / (1.0 + abs(primal_obj) + abs(dual_obj))
            comp_rel = abs(gap) / (tau_safe * tau_safe + comp_scale_sz)

            def _record_hsde_log(alpha_step: float, cond_val: float = 1.0, sig_val: float = 0.0, s_norm: float = 0.0) -> None:
                history.append(
                    IterationRecord(
                        iteration=it,
                        phase="hsde",
                        mu=mu,
                        primal_obj=primal_obj if tau > 1e-12 else 0.0,
                        dual_obj=dual_obj if tau > 1e-12 else 0.0,
                        duality_gap=gap * inv_tau * inv_tau if tau > 1e-12 else gap,
                        dual_residual_rel=r_d_rel,
                        eq_residual_rel=0.0,
                        min_eig_primal=min_eig_p if tau > 1e-12 else min_eig_p_hom,
                        min_eig_dual=min_eig_d if tau > 1e-12 else min_eig_d_hom,
                        alpha_primal=alpha_step,
                        alpha_dual=alpha_step,
                        kkt_condition_number=cond_val,
                        sigma=sig_val,
                        step_norm=s_norm,
                    )
                )
                entry = {
                    "iter": int(it + 1),
                    "max_iters": int(max_iter),
                    "gap": float(gap * inv_tau * inv_tau if tau > 1e-12 else gap),
                    "primal_res": float(rp_unhom if tau > 1e-12 else rp_norm),
                    "dual_res": float(r_d_rel),
                    "min_eig": float(min_eig_p if tau > 1e-12 else min_eig_p_hom),
                    "alpha": float(alpha_step),
                    "tau": float(tau),
                    "kappa": float(kappa),
                    "elapsed_ms": float((time.perf_counter() - t0) * 1000.0),
                }
                iter_log.append(entry)
                if callable(progress_callback):
                    try:
                        progress_callback(entry)
                    except Exception:
                        pass

            # 1a. Parada rápida para pura factibilidade (c = 0) com ponto estritamente interior
            if (
                is_pure_feas
                and tau > 1e-12
                and min_eig_p > strict_margin
                and rp_unhom <= 1e-6 * f0_scale
            ):
                _record_hsde_log(0.0)
                solver_status = "optimal"
                hsde_certificate = "optimal"
                pure_feas_zero_dual = True
                break

            # 1b. Critério de otimalidade HSDE (tau domina kappa, resíduos desomogeneizados <= tol)
            if (
                tau > 1e-12
                and kappa <= max(1e-6, 10.0 * tol_gap) * tau
                and min_eig_p >= -1e-9
                and rp_unhom <= tol_feas * f0_scale
                and r_d_rel <= tol_feas
                and max(rel_gap, comp_rel) <= tol_gap
            ):
                _record_hsde_log(0.0)
                solver_status = "optimal"
                hsde_certificate = "optimal"
                break

            # 1b'. Salvaguarda de piso numérico float64: se já atingimos <= 1e-9 em primal/dual/gap
            # e os resíduos voltam a crescer >10x por condicionamento extremo de H, restaurar melhor iterado.
            if tau > 1e-12 and kappa <= 1e-6 * tau and min_eig_p >= -1e-8:
                cur_score = max(rel_gap, comp_rel, r_d_rel, rp_unhom / f0_scale)
                if cur_score <= 1e-9 and cur_score < best_opt_score:
                    best_opt_score = cur_score
                    best_opt_rp = rp_unhom
                    best_opt_rd = r_d_rel
                    best_opt_state = (z * inv_tau, float(tau), _unpack_Z_scaled(inv_tau))
                elif (
                    best_opt_state is not None
                    and best_opt_score <= 1e-9
                    and (rp_unhom > 10.0 * max(best_opt_rp, 1e-12) or r_d_rel > 10.0 * max(best_opt_rd, 1e-12))
                ):
                    _record_hsde_log(0.0)
                    solver_status = "optimal"
                    hsde_certificate = "optimal"
                    break

            # 1c. Detecção antecipada de infactibilidade primal (Certificado de Farkas HSDE)
            if it >= 1 and dual_f0_dot < -1e-10 * (1.0 + f0_scale * z_dual_norm):
                adj_norm = float(np.linalg.norm(adj))
                farkas_rel = adj_norm / max(1e-15, abs(dual_f0_dot))
                if (kappa > 1e2 * tau and farkas_rel < 1e-5) or (kappa > 1e4 * tau and farkas_rel < 1e-3) or farkas_rel < 1e-7:
                    Z_cand_f = _unpack_Z_scaled(1.0)
                    Z_strict = _validate_strict_farkas_certificate(blocks, m, Z_cand_f)
                    if Z_strict is None:
                        Z_proj = _project_dual_onto_subspace(blocks, m, Z_cand_f, np.zeros((m,), dtype=np.float64))
                        if Z_proj is not None:
                            Z_strict = _validate_strict_farkas_certificate(blocks, m, Z_proj)
                    if Z_strict is not None:
                        farkas_candidate = Z_strict
                        farkas_obj_s = float(sum(float(np.sum(b.F0 * Zb)) for b, Zb in zip(blocks, Z_strict, strict=True)))
                        adj_s = np.zeros((m,), dtype=np.float64)
                        for b, Zb in zip(blocks, Z_strict, strict=True):
                            if b._active_keys.size > 0:
                                act_s = np.empty((b._active_keys.size,), dtype=np.float64)
                                b.adjoint_active(Zb, act_s)
                                adj_s[b._active_keys] += act_s
                        farkas_dual_res_rel = float(np.linalg.norm(adj_s) / max(1e-15, abs(farkas_obj_s)))
                        farkas_objective = farkas_obj_s
                        _record_hsde_log(0.0)
                        solver_status = "primal_infeasible"
                        hsde_certificate = "primal_infeasible"
                        break

            # 1d. Detecção antecipada de infactibilidade dual / problema ilimitado
            if not is_pure_feas and it >= 1 and kappa > 1e3 * tau:
                z_norm = float(np.linalg.norm(z))
                cz_val = float(np.dot(c_vec, z))
                if z_norm > 1e-12 and cz_val < -1e-7 * c_scale * z_norm:
                    d_cand = z / z_norm
                    min_lin_eig = float("inf")
                    if q_lp > 0:
                        assert lp_vec_buf is not None
                        if use_sparse_lp:
                            assert F_lp_csr is not None
                            lp_vec_buf[:] = F_lp_csr @ d_cand
                        else:
                            assert F_lp_dense is not None
                            np.matmul(F_lp_dense, d_cand, out=lp_vec_buf)
                        min_lin_eig = min(min_lin_eig, float(np.min(lp_vec_buf)))
                    for blk in psd_blocks:
                        min_lin_eig = min(min_lin_eig, float(np.min(np.linalg.eigvalsh(blk.evaluate_linear(d_cand)))))
                    if min_lin_eig >= -1e-8:
                        recession_candidate = d_cand.copy()
                        _record_hsde_log(0.0)
                        solver_status = "dual_infeasible"
                        hsde_certificate = "dual_infeasible"
                        break

            # 2. Escalonamento NT e montagem in-place de H, g0, h00
            g0.fill(0.0)
            h00 = 0.0
            if q_lp > 0:
                assert s_lp is not None and z_lp is not None and s_lp_safe is not None and w_lp is not None
                assert F0_lp is not None and lp_vec_buf is not None
                np.maximum(s_lp, 1e-30, out=s_lp_safe)
                np.divide(z_lp, s_lp_safe, out=w_lp)
                np.multiply(w_lp, F0_lp, out=lp_vec_buf)
                h00 += float(np.dot(F0_lp, lp_vec_buf))
                if use_sparse_lp:
                    assert F_lp_csc is not None and F_lp_csr is not None
                    H.fill(0.0)
                    H += (F_lp_csc.T @ F_lp_csr.multiply(w_lp[:, None])).toarray()
                    g0 += F_lp_csc.T @ lp_vec_buf
                else:
                    assert F_lp_dense is not None and F_lp_scaled is not None
                    np.multiply(F_lp_dense, w_lp[:, None], out=F_lp_scaled)
                    np.matmul(F_lp_dense.T, F_lp_scaled, out=H)
                    np.matmul(F_lp_dense.T, lp_vec_buf, out=g0)
            else:
                H.fill(0.0)

            for pos, blk in enumerate(psd_blocks):
                G_b, G_invT_b, lam_b = _nt_scaling_factors(cho_S_psd[pos], cho_Z_psd[pos])
                G_psd[pos] = G_b
                G_invT_psd[pos] = G_invT_b
                lam_psd[pos] = lam_b
                active_keys = blk._active_keys
                n_act = int(active_keys.size)
                cols = cols_bufs[pos]
                tmp1 = tmp1_bufs[pos]
                tmp2 = tmp2_bufs[pos]

                np.matmul(G_invT_b.T, blk.F0, out=tmp1)
                np.matmul(tmp1, G_invT_b, out=tmp2)
                _sym_into(tmp2, F0_hat_bufs[pos])

                np.matmul(G_invT_b.T, R_p_psd_bufs[pos], out=tmp1)
                np.matmul(tmp1, G_invT_b, out=tmp2)
                _sym_into(tmp2, R_p_hat_bufs[pos])

                h00 += float(np.sum(F0_hat_bufs[pos] * F0_hat_bufs[pos]))
                if n_act > 0:
                    gram = gram_bufs[pos]
                    act_buf = act_vec_bufs[pos]
                    assert gram is not None and act_buf is not None
                    if cols is None:
                        W_b = W_psd_bufs[pos]
                        np.matmul(G_invT_b, G_invT_b.T, out=tmp1)
                        _sym_into(tmp1, W_b)
                        blk.assemble_schur_block(W_b, gram)
                        _psd_adjoint_hat(pos, F0_hat_bufs[pos], act_buf)
                    else:
                        if blk._F_cols is not None and n_act >= 4:
                            _fill_f3_scaled_cols(blk._F_cols, G_invT_b, blk.dim, cols)
                        else:
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
                        np.matmul(cols.T, cols, out=gram)
                        np.matmul(cols.T, F0_hat_bufs[pos].ravel(), out=act_buf)
                    if is_full_m[pos]:
                        H += gram
                        g0 += act_buf
                    else:
                        H[np.ix_(active_keys, active_keys)] += gram
                        g0[active_keys] += act_buf

            # Fatorar H uma única vez por iteração e resolver u0 = H^{-1} g0, uc = H^{-1} c_vec
            # para calcular d_tau = kappa/tau + ||F0_hat - A_hat(u0)||^2 + c^T uc sem cancelamento catastrófico!
            fac_H = _factor_symmetric_system(
                H,
                H_scaled_buf=H_scaled_buf,
                H_work_buf=H_work_buf,
                inv_d_buf=inv_d_buf,
                sparse_density_threshold=sparse_schur_density_threshold,
                sparse_min_dim=sparse_schur_min_dim,
                factorization_mode=schur_factorization_mode,
            )
            factorizations += 1
            if fac_H.mode == "sparse_splu":
                sparse_factorizations += 1
            else:
                dense_factorizations += 1
            cond_H = fac_H.cond

            u0_vec = _solve_factored_symmetric(
                fac_H,
                g0,
                rhs_scaled_buf=rhs_scaled_buf,
                res_s_buf=res_s_buf,
                mv_buf=rhs_buf,
            )
            if is_pure_feas:
                uc_vec = np.zeros((m,), dtype=np.float64)
            else:
                uc_vec = _solve_factored_symmetric(
                    fac_H,
                    c_vec,
                    rhs_scaled_buf=rhs_scaled_buf,
                    res_s_buf=res_s_buf,
                    mv_buf=rhs_buf,
                )
            np.add(u0_vec, uc_vec, out=q_z)

            # Resíduo ortogonal r_F0 = F0_hat - A_hat(u0) -> schur_00 = ||r_F0||^2 >= 0 sem cancelamento
            schur_00 = 0.0
            r_F0_lp: np.ndarray | None = None
            if q_lp > 0:
                assert F0_lp is not None and w_lp is not None
                if use_sparse_lp:
                    assert F_lp_csr is not None
                    r_F0_lp = F0_lp - (F_lp_csr @ u0_vec)
                else:
                    assert F_lp_dense is not None
                    r_F0_lp = F0_lp - (F_lp_dense @ u0_vec)
                schur_00 += float(np.dot(r_F0_lp * r_F0_lp, w_lp))

            r_F0_psd: list[np.ndarray] = []
            for pos, blk in enumerate(psd_blocks):
                active_keys = blk._active_keys
                tmp1 = tmp1_bufs[pos]
                if active_keys.size > 0:
                    u0_act = u0_vec if is_full_m[pos] else u0_vec[active_keys]
                    _psd_forward_hat(pos, u0_act, tmp1)
                    r_f0_b = _sym(F0_hat_bufs[pos] - tmp1)
                else:
                    r_f0_b = F0_hat_bufs[pos].copy()
                r_F0_psd.append(r_f0_b)
                schur_00 += float(np.sum(r_f0_b * r_f0_b))

            c_Hinv_c = max(0.0, float(np.dot(c_vec, uc_vec))) if not is_pure_feas else 0.0
            d_tau = (kappa * inv_tau) + schur_00 + c_Hinv_c
            if not math.isfinite(d_tau) or d_tau <= 1e-30:
                d_tau = max(kappa * inv_tau, 1e-30)

            def _compute_unified_alpha_max(
                ds_lp_v: np.ndarray | None,
                dz_lp_v: np.ndarray | None,
                ds_t_list: Sequence[np.ndarray],
                dz_t_list: Sequence[np.ndarray],
                dt_val: float,
                dk_val: float,
            ) -> float:
                a_max = float("inf")
                if not math.isfinite(dt_val) or not math.isfinite(dk_val):
                    return 0.0
                if dt_val < -1e-15 * tau_safe:
                    a_max = min(a_max, -tau / dt_val)
                if dk_val < -1e-15 * max(kappa, 1e-30):
                    a_max = min(a_max, -kappa / dk_val)
                if q_lp > 0:
                    assert s_lp is not None and z_lp is not None and s_lp_safe is not None
                    assert ds_lp_v is not None and dz_lp_v is not None
                    if not np.all(np.isfinite(ds_lp_v)) or not np.all(np.isfinite(dz_lp_v)):
                        return 0.0
                    neg_p = ds_lp_v < -1e-15 * s_lp_safe
                    if np.any(neg_p):
                        a_max = min(a_max, float(np.min(-s_lp[neg_p] / ds_lp_v[neg_p])))
                    neg_d = dz_lp_v < -1e-15 * np.maximum(z_lp, 1e-30)
                    if np.any(neg_d):
                        a_max = min(a_max, float(np.min(-z_lp[neg_d] / dz_lp_v[neg_d])))
                for pos in range(n_psd_blocks):
                    a_max = min(
                        a_max,
                        _max_step_scaled_identity(lam_psd[pos], ds_t_list[pos], work1=tmp1_bufs[pos], work2=tmp2_bufs[pos]),
                        _max_step_scaled_identity(lam_psd[pos], dz_t_list[pos], work1=tmp1_bufs[pos], work2=tmp2_bufs[pos]),
                    )
                return a_max

            # 3. Passo Preditor Afim de Mehrotra (sigma = 0, eta = 1)
            np.negative(r_d, out=rhs_buf)
            beta_orth_aff = float(np.dot(u0_vec, r_d))
            if q_lp > 0:
                assert w_lp is not None and rp_lp is not None and z_lp is not None
                assert r_F0_lp is not None and lp_vec_buf is not None
                np.multiply(w_lp, rp_lp, out=lp_vec_buf)
                lp_vec_buf -= z_lp
                beta_orth_aff += float(np.dot(r_F0_lp, lp_vec_buf))
                if use_sparse_lp:
                    assert F_lp_csc is not None
                    rhs_buf += F_lp_csc.T @ lp_vec_buf
                else:
                    assert F_lp_dense is not None
                    np.matmul(F_lp_dense.T, lp_vec_buf, out=m_scratch)
                    rhs_buf += m_scratch

            for pos, blk in enumerate(psd_blocks):
                tmp1 = tmp1_bufs[pos]
                np.copyto(tmp1, R_p_hat_bufs[pos])
                tmp1[diag_psd[pos], diag_psd[pos]] -= lam_psd[pos]
                beta_orth_aff += float(np.sum(r_F0_psd[pos] * tmp1))
                active_keys = blk._active_keys
                if active_keys.size > 0:
                    act_buf = act_vec_bufs[pos]
                    assert act_buf is not None
                    _psd_adjoint_hat(pos, tmp1, act_buf)
                    if is_full_m[pos]:
                        rhs_buf += act_buf
                    else:
                        rhs_buf[active_keys] += act_buf

            _solve_factored_symmetric(
                fac_H,
                rhs_buf,
                out=p_z,
                rhs_scaled_buf=rhs_scaled_buf,
                res_s_buf=res_s_buf,
                mv_buf=m_scratch,
            )
            r_tk_aff = -tau * kappa
            dtau_aff = (r_g + r_tk_aff * inv_tau + beta_orth_aff + float(np.dot(c_vec, p_z))) / d_tau
            np.multiply(q_z, dtau_aff, out=m_scratch)
            np.subtract(p_z, m_scratch, out=dz_aff)
            dkappa_aff = (r_tk_aff - kappa * dtau_aff) * inv_tau

            if q_lp > 0:
                assert s_lp is not None and z_lp is not None and w_lp is not None
                assert rp_lp is not None and F0_lp is not None and ds_lp_aff is not None and dz_lp_aff is not None
                if use_sparse_lp:
                    assert F_lp_csr is not None
                    ds_lp_aff[:] = F_lp_csr @ dz_aff
                else:
                    assert F_lp_dense is not None
                    np.matmul(F_lp_dense, dz_aff, out=ds_lp_aff)
                ds_lp_aff += dtau_aff * F0_lp
                ds_lp_aff -= rp_lp
                np.multiply(w_lp, ds_lp_aff, out=dz_lp_aff)
                dz_lp_aff += z_lp
                np.negative(dz_lp_aff, out=dz_lp_aff)

            for pos, blk in enumerate(psd_blocks):
                active_keys = blk._active_keys
                tmp1 = tmp1_bufs[pos]
                ds_t = dS_tilde_aff_bufs[pos]
                dz_t = dZ_tilde_aff_bufs[pos]
                if active_keys.size > 0:
                    dz_act = dz_aff if is_full_m[pos] else dz_aff[active_keys]
                    _psd_forward_hat(pos, dz_act, tmp1)
                else:
                    tmp1.fill(0.0)
                tmp1 += dtau_aff * F0_hat_bufs[pos]
                tmp1 -= R_p_hat_bufs[pos]
                _sym_into(tmp1, ds_t)
                np.negative(ds_t, out=dz_t)
                dz_t[diag_psd[pos], diag_psd[pos]] -= lam_psd[pos]

            alpha_aff_max = _compute_unified_alpha_max(
                ds_lp_aff, dz_lp_aff, dS_tilde_aff_bufs, dZ_tilde_aff_bufs, dtau_aff, dkappa_aff
            )
            alpha_aff = min(1.0, step_fraction * alpha_aff_max)

            gap_aff = (tau + alpha_aff * dtau_aff) * (kappa + alpha_aff * dkappa_aff)
            if q_lp > 0:
                assert s_lp is not None and z_lp is not None and ds_lp_aff is not None and dz_lp_aff is not None
                assert lp_vec_buf is not None and lp_vec_buf2 is not None
                np.multiply(ds_lp_aff, alpha_aff, out=lp_vec_buf)
                lp_vec_buf += s_lp
                np.multiply(dz_lp_aff, alpha_aff, out=lp_vec_buf2)
                lp_vec_buf2 += z_lp
                gap_aff += float(np.dot(lp_vec_buf, lp_vec_buf2))
            for pos in range(n_psd_blocks):
                tmp1 = tmp1_bufs[pos]
                tmp2 = tmp2_bufs[pos]
                np.multiply(dS_tilde_aff_bufs[pos], alpha_aff, out=tmp1)
                tmp1[diag_psd[pos], diag_psd[pos]] += lam_psd[pos]
                np.multiply(dZ_tilde_aff_bufs[pos], alpha_aff, out=tmp2)
                tmp2[diag_psd[pos], diag_psd[pos]] += lam_psd[pos]
                gap_aff += float(np.sum(tmp1 * tmp2))

            mu_aff = max(0.0, gap_aff / max(1, total_order + 1))
            sigma = float(np.clip((mu_aff / max(mu, 1e-16)) ** 3, sigma_min, sigma_max))
            if alpha_aff < 1e-3:
                sigma = max(sigma, 0.5)

            # 4. Passo Corretor-Centrador de Mehrotra (eta_res = 1 - sigma)
            eta_res = 1.0 - sigma
            eta_meh = 1.0 if alpha_aff >= 0.05 else 0.0
            np.multiply(r_d, -eta_res, out=rhs_buf)
            beta_orth_cor = eta_res * float(np.dot(u0_vec, r_d))

            if q_lp > 0:
                assert s_lp is not None and z_lp is not None and s_lp_safe is not None and w_lp is not None
                assert rp_lp is not None and rc_lp is not None and ds_lp_aff is not None and dz_lp_aff is not None
                assert r_F0_lp is not None and lp_vec_buf is not None and lp_vec_buf2 is not None
                np.multiply(s_lp, z_lp, out=rc_lp)
                np.subtract(sigma * mu, rc_lp, out=rc_lp)
                if eta_meh != 0.0:
                    np.multiply(ds_lp_aff, dz_lp_aff, out=lp_vec_buf)
                    rc_lp -= lp_vec_buf
                np.divide(rc_lp, s_lp_safe, out=lp_vec_buf)
                np.multiply(w_lp, rp_lp, out=lp_vec_buf2)
                lp_vec_buf += eta_res * lp_vec_buf2
                beta_orth_cor += float(np.dot(r_F0_lp, lp_vec_buf))
                if use_sparse_lp:
                    assert F_lp_csc is not None
                    rhs_buf += F_lp_csc.T @ lp_vec_buf
                else:
                    assert F_lp_dense is not None
                    np.matmul(F_lp_dense.T, lp_vec_buf, out=m_scratch)
                    rhs_buf += m_scratch

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

                np.multiply(R_p_hat_bufs[pos], eta_res, out=tmp1)
                tmp1 += M_cor_b
                beta_orth_cor += float(np.sum(r_F0_psd[pos] * tmp1))
                active_keys = blk._active_keys
                if active_keys.size > 0:
                    act_buf = act_vec_bufs[pos]
                    assert act_buf is not None
                    _psd_adjoint_hat(pos, tmp1, act_buf)
                    if is_full_m[pos]:
                        rhs_buf += act_buf
                    else:
                        rhs_buf[active_keys] += act_buf

            _solve_factored_symmetric(
                fac_H,
                rhs_buf,
                out=p_z,
                rhs_scaled_buf=rhs_scaled_buf,
                res_s_buf=res_s_buf,
                mv_buf=m_scratch,
            )
            r_tk_cor = sigma * mu - tau * kappa - eta_meh * dtau_aff * dkappa_aff
            dtau = (eta_res * r_g + r_tk_cor * inv_tau + beta_orth_cor + float(np.dot(c_vec, p_z))) / d_tau
            np.multiply(q_z, dtau, out=m_scratch)
            np.subtract(p_z, m_scratch, out=dz)
            dkappa = (r_tk_cor - kappa * dtau) * inv_tau

            if q_lp > 0:
                assert s_lp is not None and z_lp is not None and s_lp_safe is not None and w_lp is not None
                assert rp_lp is not None and rc_lp is not None and F0_lp is not None
                assert ds_lp is not None and dz_lp is not None and lp_vec_buf is not None
                if use_sparse_lp:
                    assert F_lp_csr is not None
                    ds_lp[:] = F_lp_csr @ dz
                else:
                    assert F_lp_dense is not None
                    np.matmul(F_lp_dense, dz, out=ds_lp)
                ds_lp += dtau * F0_lp
                ds_lp -= eta_res * rp_lp
                np.divide(rc_lp, s_lp_safe, out=dz_lp)
                np.multiply(w_lp, ds_lp, out=lp_vec_buf)
                dz_lp -= lp_vec_buf

            for pos, blk in enumerate(psd_blocks):
                active_keys = blk._active_keys
                tmp1 = tmp1_bufs[pos]
                ds_t = dS_tilde_cor_bufs[pos]
                dz_t = dZ_tilde_cor_bufs[pos]
                if active_keys.size > 0:
                    dz_act = dz if is_full_m[pos] else dz[active_keys]
                    _psd_forward_hat(pos, dz_act, tmp1)
                else:
                    tmp1.fill(0.0)
                tmp1 += dtau * F0_hat_bufs[pos]
                tmp1 -= eta_res * R_p_hat_bufs[pos]
                _sym_into(tmp1, ds_t)
                np.subtract(M_cor_bufs[pos], ds_t, out=tmp1)
                _sym_into(tmp1, dz_t)

            alpha_max = _compute_unified_alpha_max(
                ds_lp, dz_lp, dS_tilde_cor_bufs, dZ_tilde_cor_bufs, dtau, dkappa
            )
            alpha = min(1.0, step_fraction * alpha_max)

            # 5. Múltiplos Corretores de Centralidade de Gondzio (1996, doi:10.1007/BF00249643)
            # Reutiliza a MESMA fatoração `fac_H` e `q_z` (O(m^2)) para tentar aumentar alpha.
            if max_gondzio_correctors > 0 and 0.05 <= alpha < 0.95 and mu > 1e-10 and fac_H.cho is not None:
                mu_target = max(sigma * mu, 1e-16)
                beta_min_g = 0.1
                beta_max_g = 10.0
                lo_g = beta_min_g * mu_target
                hi_g = beta_max_g * mu_target

                for _g_idx in range(max_gondzio_correctors):
                    if alpha >= 0.95:
                        break
                    gondzio_attempted += 1
                    alpha_trial = min(1.0, alpha + max(0.08, 0.1 * (1.0 - alpha)))
                    rhs_buf.fill(0.0)
                    beta_orth_gon = 0.0
                    has_pert = False

                    # Perturbação (tau, kappa)
                    v_tk = (tau + alpha_trial * dtau) * (kappa + alpha_trial * dkappa)
                    t_tk = float(np.clip(v_tk, lo_g, hi_g))
                    dr_tk = float(np.clip(t_tk - v_tk, -hi_g, hi_g))
                    if abs(dr_tk) > 1e-16:
                        has_pert = True

                    # Perturbação cone LP 1D
                    drc_lp_g: np.ndarray | None = None
                    if q_lp > 0:
                        assert s_lp is not None and z_lp is not None and ds_lp is not None and dz_lp is not None
                        assert s_lp_safe is not None and r_F0_lp is not None and lp_vec_buf is not None
                        v_lp = (s_lp + alpha_trial * ds_lp) * (z_lp + alpha_trial * dz_lp)
                        t_lp = np.clip(v_lp, lo_g, hi_g)
                        drc_lp_g = np.clip(t_lp - v_lp, -hi_g, hi_g)
                        if float(np.max(np.abs(drc_lp_g))) > 1e-16:
                            has_pert = True
                            np.divide(drc_lp_g, s_lp_safe, out=lp_vec_buf)
                            beta_orth_gon += float(np.dot(r_F0_lp, lp_vec_buf))
                            if use_sparse_lp:
                                assert F_lp_csc is not None
                                rhs_buf += F_lp_csc.T @ lp_vec_buf
                            else:
                                assert F_lp_dense is not None
                                np.matmul(F_lp_dense.T, lp_vec_buf, out=m_scratch)
                                rhs_buf += m_scratch

                    # Perturbação blocos PSD
                    for pos, blk in enumerate(psd_blocks):
                        dM_b = dM_gon_bufs[pos]
                        changed = _gondzio_psd_delta_M(
                            lam_psd[pos],
                            dS_tilde_cor_bufs[pos],
                            dZ_tilde_cor_bufs[pos],
                            alpha_trial,
                            mu_target,
                            beta_min_g,
                            beta_max_g,
                            dM_b,
                            tmp1_bufs[pos],
                            tmp2_bufs[pos],
                            diag_psd[pos],
                        )
                        if changed:
                            has_pert = True
                            beta_orth_gon += float(np.sum(r_F0_psd[pos] * dM_b))
                            active_keys = blk._active_keys
                            if active_keys.size > 0:
                                act_buf = act_vec_bufs[pos]
                                assert act_buf is not None
                                _psd_adjoint_hat(pos, dM_b, act_buf)
                                if is_full_m[pos]:
                                    rhs_buf += act_buf
                                else:
                                    rhs_buf[active_keys] += act_buf

                    if not has_pert:
                        break

                    _solve_factored_symmetric(
                        fac_H,
                        rhs_buf,
                        out=p_z,
                        rhs_scaled_buf=rhs_scaled_buf,
                        res_s_buf=res_s_buf,
                        mv_buf=m_scratch,
                    )
                    ddtau_g = (dr_tk * inv_tau + beta_orth_gon + float(np.dot(c_vec, p_z))) / d_tau
                    ddz_g = p_z - q_z * ddtau_g
                    ddkappa_g = (dr_tk - kappa * ddtau_g) * inv_tau

                    if not (math.isfinite(ddtau_g) and math.isfinite(ddkappa_g) and np.all(np.isfinite(ddz_g))):
                        break

                    dtau_c = dtau + ddtau_g
                    dkappa_c = dkappa + ddkappa_g
                    dz_c = dz + ddz_g

                    ds_lp_c: np.ndarray | None = None
                    dz_lp_c: np.ndarray | None = None
                    if q_lp > 0:
                        assert ds_lp is not None and dz_lp is not None and F0_lp is not None
                        assert s_lp_safe is not None and w_lp is not None and drc_lp_g is not None
                        if use_sparse_lp:
                            assert F_lp_csr is not None
                            dds_lp = F_lp_csr @ ddz_g + ddtau_g * F0_lp
                        else:
                            assert F_lp_dense is not None
                            dds_lp = F_lp_dense @ ddz_g + ddtau_g * F0_lp
                        ddz_lp = drc_lp_g / s_lp_safe - w_lp * dds_lp
                        ds_lp_c = ds_lp + dds_lp
                        dz_lp_c = dz_lp + ddz_lp

                    ds_t_cands: list[np.ndarray] = []
                    dz_t_cands: list[np.ndarray] = []
                    for pos, blk in enumerate(psd_blocks):
                        active_keys = blk._active_keys
                        tmp1 = tmp1_bufs[pos]
                        if active_keys.size > 0:
                            ddz_act = ddz_g if is_full_m[pos] else ddz_g[active_keys]
                            _psd_forward_hat(pos, ddz_act, tmp1)
                        else:
                            tmp1.fill(0.0)
                        tmp1 += ddtau_g * F0_hat_bufs[pos]
                        dds_t = _sym(tmp1)
                        ddz_t = _sym(dM_gon_bufs[pos] - dds_t)
                        ds_t_cands.append(_sym(dS_tilde_cor_bufs[pos] + dds_t))
                        dz_t_cands.append(_sym(dZ_tilde_cor_bufs[pos] + ddz_t))

                    alpha_max_c = _compute_unified_alpha_max(
                        ds_lp_c, dz_lp_c, ds_t_cands, dz_t_cands, dtau_c, dkappa_c
                    )
                    alpha_c = min(1.0, step_fraction * alpha_max_c)

                    if alpha_c >= alpha + 0.05:
                        dtau = dtau_c
                        dkappa = dkappa_c
                        np.copyto(dz, dz_c)
                        if q_lp > 0:
                            assert ds_lp is not None and dz_lp is not None
                            assert ds_lp_c is not None and dz_lp_c is not None
                            np.copyto(ds_lp, ds_lp_c)
                            np.copyto(dz_lp, dz_lp_c)
                        for pos in range(n_psd_blocks):
                            np.copyto(dS_tilde_cor_bufs[pos], ds_t_cands[pos])
                            np.copyto(dZ_tilde_cor_bufs[pos], dz_t_cands[pos])
                        alpha = alpha_c
                        gondzio_accepted += 1
                    else:
                        break

            # 6. Transformar dS_tilde -> dS_psd = G @ dS_tilde @ G.T e dZ_tilde -> dZ_psd = G_invT @ dZ_tilde @ G_invT.T
            for pos in range(n_psd_blocks):
                G_b = G_psd[pos]
                G_invT_b = G_invT_psd[pos]
                tmp1 = tmp1_bufs[pos]
                tmp2 = tmp2_bufs[pos]
                np.matmul(G_b, dS_tilde_cor_bufs[pos], out=tmp1)
                np.matmul(tmp1, G_b.T, out=tmp2)
                _sym_into(tmp2, dS_psd_bufs[pos])
                np.matmul(G_invT_b, dZ_tilde_cor_bufs[pos], out=tmp1)
                np.matmul(tmp1, G_invT_b.T, out=tmp2)
                _sym_into(tmp2, dZ_psd_bufs[pos])

            # Backtracking unificado para garantir estrita positividade de (tau, kappa, S, Z)
            step_accepted = False
            while alpha > 1e-12:
                tau_t = tau + alpha * dtau
                kappa_t = kappa + alpha * dkappa
                if tau_t <= 0.0 or kappa_t <= 0.0 or not (math.isfinite(tau_t) and math.isfinite(kappa_t)):
                    alpha *= 0.5
                    continue
                lp_ok = True
                if q_lp > 0:
                    assert s_lp is not None and z_lp is not None and ds_lp is not None and dz_lp is not None
                    assert s_lp_trial is not None and z_lp_trial is not None
                    np.multiply(ds_lp, alpha, out=s_lp_trial)
                    s_lp_trial += s_lp
                    np.multiply(dz_lp, alpha, out=z_lp_trial)
                    z_lp_trial += z_lp
                    lp_ok = bool(
                        np.all(np.isfinite(s_lp_trial))
                        and np.all(np.isfinite(z_lp_trial))
                        and np.all(s_lp_trial > 0.0)
                        and np.all(z_lp_trial > 0.0)
                    )
                if not lp_ok:
                    alpha *= 0.5
                    continue
                psd_ok = True
                cho_s_t_list: list[tuple[np.ndarray, bool]] = []
                cho_z_t_list: list[tuple[np.ndarray, bool]] = []
                for pos in range(n_psd_blocks):
                    np.multiply(dS_psd_bufs[pos], alpha, out=tmp1_bufs[pos])
                    tmp1_bufs[pos] += S_psd_list[pos]
                    _sym_into(tmp1_bufs[pos], S_trial_bufs[pos])
                    c_s = _safe_cholesky_buf(S_trial_bufs[pos], cho_S_trial_bufs[pos])
                    if c_s is None:
                        psd_ok = False
                        break
                    np.multiply(dZ_psd_bufs[pos], alpha, out=tmp1_bufs[pos])
                    tmp1_bufs[pos] += Z_psd_list[pos]
                    _sym_into(tmp1_bufs[pos], Z_trial_bufs[pos])
                    c_z = _safe_cholesky_buf(Z_trial_bufs[pos], cho_Z_trial_bufs[pos])
                    if c_z is None:
                        psd_ok = False
                        break
                    cho_s_t_list.append(c_s)
                    cho_z_t_list.append(c_z)
                if psd_ok:
                    tau = tau_t
                    kappa = kappa_t
                    np.multiply(dz, alpha, out=m_scratch)
                    z += m_scratch
                    if q_lp > 0:
                        assert s_lp is not None and z_lp is not None
                        assert s_lp_trial is not None and z_lp_trial is not None
                        np.copyto(s_lp, s_lp_trial)
                        np.copyto(z_lp, z_lp_trial)
                    for pos in range(n_psd_blocks):
                        np.copyto(S_psd_list[pos], S_trial_bufs[pos])
                        np.copyto(Z_psd_list[pos], Z_trial_bufs[pos])
                        if cho_s_t_list[pos][0] is cho_S_trial_bufs[pos]:
                            cho_S_bufs[pos], cho_S_trial_bufs[pos] = cho_S_trial_bufs[pos], cho_S_bufs[pos]
                        if cho_z_t_list[pos][0] is cho_Z_trial_bufs[pos]:
                            cho_Z_bufs[pos], cho_Z_trial_bufs[pos] = cho_Z_trial_bufs[pos], cho_Z_bufs[pos]
                        cho_S_psd[pos] = cho_s_t_list[pos]
                        cho_Z_psd[pos] = cho_z_t_list[pos]
                    step_accepted = True
                    break
                alpha *= 0.5

            step_norm = float(alpha * np.linalg.norm(dz) * inv_tau) if tau > 1e-12 else float(alpha * np.linalg.norm(dz))
            _record_hsde_log(alpha, cond_val=cond_H, sig_val=sigma, s_norm=step_norm)

            if not step_accepted:
                break

            # Reescalonamento homogêneo para evitar overflow/underflow mantendo invariância exata
            tk_max = max(tau, kappa)
            if tk_max > 1e6 or tk_max < 1e-6:
                h_scale = 1.0 / max(tk_max, 1e-30)
                sqrt_h = math.sqrt(h_scale)
                z *= h_scale
                tau *= h_scale
                kappa *= h_scale
                if q_lp > 0:
                    assert s_lp is not None and z_lp is not None
                    s_lp *= h_scale
                    z_lp *= h_scale
                for pos in range(n_psd_blocks):
                    S_psd_list[pos] *= h_scale
                    Z_psd_list[pos] *= h_scale
                    cho_S_psd[pos][0][:] *= sqrt_h
                    cho_Z_psd[pos][0][:] *= sqrt_h

        # Pós-processamento: desomogeneização e polimento dual
        z_out = z / max(tau, 1e-30)
        if solver_status == "optimal" and pure_feas_zero_dual:
            Z_list = [np.zeros((b.dim, b.dim), dtype=np.float64) for b in blocks]
            S_eval_final = [b.evaluate(z_out) for b in blocks]
        elif (
            best_opt_state is not None
            and best_opt_score <= 1e-9
            and solver_status in ("optimal", "optimal_inaccurate", "max_iterations")
            and (tau <= 1e-12 or max(rel_gap, comp_rel, r_d_rel, rp_unhom / f0_scale) > best_opt_score)
        ):
            z_out = best_opt_state[0].copy()
            Z_list = [Zb.copy() for Zb in best_opt_state[2]]
            Z_pol = _project_dual_onto_subspace(blocks, m, Z_list, c_vec)
            if Z_pol is not None:
                Z_list = Z_pol
            S_eval_final = [b.evaluate(z_out) for b in blocks]
            solver_status = "optimal"
            hsde_certificate = "optimal"
        elif solver_status in ("optimal", "optimal_inaccurate", "max_iterations") and tau > 1e-12:
            Z_list = _unpack_Z_scaled(1.0 / tau)
            if is_pure_feas:
                S_eval_final = [b.evaluate(z_out) for b in blocks]
                min_eig_f = min(_min_eig_sym(S_ev) for S_ev in S_eval_final)
                if min_eig_f >= -1e-7:
                    Z_list = [np.zeros((b.dim, b.dim), dtype=np.float64) for b in blocks]
                    solver_status = "optimal"
                    hsde_certificate = "optimal"
            else:
                W_final: list[np.ndarray] = [None] * n_blocks  # type: ignore[list-item]
                if q_lp > 0:
                    assert s_lp is not None
                    for pos, orig_i in enumerate(lp_indices):
                        W_final[orig_i] = np.array([[tau / max(float(s_lp[pos]), 1e-30)]], dtype=np.float64)
                for pos, orig_i in enumerate(psd_indices):
                    W_final[orig_i] = _cho_solve_mat(cho_S_psd[pos], tau * eye_psd[pos])

                Z_pol = _project_dual_onto_subspace(blocks, m, Z_list, c_vec, weight_mats=W_final)
                if Z_pol is None:
                    W_damped = [
                        _sym(Z_b + 1e-4 * np.eye(b.dim, dtype=np.float64))
                        for b, Z_b in zip(blocks, Z_list, strict=True)
                    ]
                    Z_pol = _project_dual_onto_subspace(blocks, m, Z_list, c_vec, weight_mats=W_damped)
                if Z_pol is not None:
                    Z_list = Z_pol

                S_eval_final = [b.evaluate(z_out) for b in blocks]
                min_eig_p_f = min(_min_eig_sym(S_ev) for S_ev in S_eval_final)
                primal_obj_f = float(np.dot(c_vec, z_out) + c0)
                dual_obj_f = float(
                    c0 - sum(float(np.sum(blk.F0 * Z_b)) for blk, Z_b in zip(blocks, Z_list, strict=True))
                )
                rel_gap_f = abs(primal_obj_f - dual_obj_f) / (1.0 + abs(primal_obj_f) + abs(dual_obj_f))
                adj.fill(0.0)
                dual_scale_f = 1.0 + c_norm
                for blk, Z_b in zip(blocks, Z_list, strict=True):
                    if blk._active_keys.size > 0:
                        act_f = np.empty((blk._active_keys.size,), dtype=np.float64)
                        blk.adjoint_active(Z_b, act_f)
                        adj[blk._active_keys] += act_f
                        dual_scale_f += blk._f_norm_sum * float(np.linalg.norm(Z_b, "fro"))
                r_d_rel_f = float(np.linalg.norm(c_vec - adj) / dual_scale_f)
                if min_eig_p_f >= -1e-7 and r_d_rel_f <= 1e-6 and rel_gap_f <= 1e-6:
                    solver_status = "optimal"
                    hsde_certificate = "optimal"
                elif min_eig_p_f >= -1e-5 and r_d_rel_f <= 1e-4 and rel_gap_f <= 1e-4:
                    solver_status = "optimal_inaccurate"
                    hsde_certificate = "optimal"
        else:
            Z_list = _unpack_Z_scaled(1.0)
            S_eval_final = [b.evaluate(z_out) for b in blocks]

        return {
            "solver_status": solver_status,
            "hsde_certificate": hsde_certificate,
            "z": z_out,
            "tau": float(tau),
            "kappa": float(kappa),
            "Z_list": Z_list,
            "S_list": S_eval_final,
            "farkas_candidate": farkas_candidate,
            "farkas_dual_residual_rel": farkas_dual_res_rel,
            "farkas_objective": farkas_objective,
            "recession_candidate": recession_candidate,
            "history": history,
            "iteration_log": iter_log,
            "factorizations": factorizations,
            "gondzio_correctors_attempted": gondzio_attempted,
            "gondzio_correctors_accepted": gondzio_accepted,
            "schur_assembly_modes": _count_schur_modes(blocks),
            "schur_factorization_mode": (
                "sparse_splu"
                if sparse_factorizations > 0 and sparse_factorizations >= dense_factorizations
                else "dense_cholesky"
            ),
        }
    finally:
        del (
            H,
            H_scaled_buf,
            H_work_buf,
            inv_d_buf,
            adj,
            r_d,
            g0,
            q_z,
            p_z,
            c_minus_g0,
            rhs_buf,
            dz_aff,
            dz,
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
            W_psd_bufs,
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
            F0_hat_bufs,
            dS_tilde_aff_bufs,
            dZ_tilde_aff_bufs,
            dS_tilde_cor_bufs,
            dZ_tilde_cor_bufs,
            M_cor_bufs,
            dM_gon_bufs,
            dS_psd_bufs,
            dZ_psd_bufs,
            tmp1_bufs,
            tmp2_bufs,
            tmp3_bufs,
            act_vec_bufs,
            G_psd,
            G_invT_psd,
            lam_psd,
            eye_psd,
            diag_psd,
        )


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
                    build_schur_index=False,
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


def _min_degree_ordering(adj_bool: np.ndarray) -> tuple[list[int], list[frozenset[int]]]:
    """Calcula ordenação de eliminação Minimum Degree e cliques de eliminação cordal.

    Referência: Vandenberghe & Andersen (2015, Found. Trends Optim., doi:10.1561/2400000006).
    """
    dim = int(adj_bool.shape[0])
    adj_sets: list[set[int]] = [
        {int(j) for j in np.flatnonzero(adj_bool[i]) if int(j) != i}
        for i in range(dim)
    ]
    remaining = set(range(dim))
    ordering: list[int] = []
    elim_cliques: list[frozenset[int]] = []

    for _ in range(dim):
        v = min(remaining, key=lambda u: (len(adj_sets[u]), u))
        nbrs = adj_sets[v]
        ordering.append(v)
        elim_cliques.append(frozenset(nbrs | {v}))
        for u in nbrs:
            adj_u = adj_sets[u]
            adj_u.discard(v)
            adj_u.update(nbrs)
            adj_u.discard(u)
        adj_sets[v].clear()
        remaining.remove(v)

    return ordering, elim_cliques


def _chordal_clique_tree_and_merge(
    elim_cliques: Sequence[frozenset[int]],
) -> tuple[list[tuple[int, ...]], list[int]]:
    """Extrai cliques maximais, constrói árvore de cliques (MWST) e aplica clique-merging.

    Referências:
    - Vandenberghe & Andersen (2015, doi:10.1561/2400000006, Theorem 4.2)
    - Garstka, Cannon & Goulart (IFAC 2020, doi:10.1016/j.ifacol.2020.12.1255)
    """
    unique_cliques = sorted(set(elim_cliques), key=lambda c: (-len(c), sorted(c)))
    maximal: list[frozenset[int]] = []
    for c in unique_cliques:
        if not any(c <= m for m in maximal):
            maximal.append(c)

    if len(maximal) <= 1:
        return [tuple(sorted(maximal[0]))] if maximal else [], [-1] if maximal else []

    L = len(maximal)
    in_tree = [False] * L
    in_tree[0] = True
    parent_raw = [-1] * L
    topo_order = [0]

    for _ in range(L - 1):
        best_w = -1
        best_u = -1
        best_p = -1
        for u in range(L):
            if in_tree[u]:
                continue
            cu = maximal[u]
            for p in topo_order:
                w = len(cu & maximal[p])
                if w > best_w or (w == best_w and (u < best_u or (u == best_u and p < best_p))):
                    best_w = w
                    best_u = u
                    best_p = p
        in_tree[best_u] = True
        parent_raw[best_u] = best_p
        topo_order.append(best_u)

    old_to_new = {old: new for new, old in enumerate(topo_order)}
    cliques: list[set[int]] = [set(maximal[old]) for old in topo_order]
    parents: list[int] = [
        -1 if parent_raw[old] == -1 else old_to_new[parent_raw[old]]
        for old in topo_order
    ]
    alive = [True] * L

    # Clique-tree merging guloso (Garstka, Cannon & Goulart 2020):
    # funde (c, p) quando |C_c U C_p|^3 <= |C_c|^3 + |C_p|^3 ou sobreposição quase total.
    while True:
        best_gain: int | None = None
        best_c = -1
        for c in range(1, L):
            if not alive[c]:
                continue
            p = parents[c]
            if p < 0 or not alive[p]:
                continue
            sz_c = len(cliques[c])
            sz_p = len(cliques[p])
            union_sz = len(cliques[c] | cliques[p])
            delta_cube = union_sz ** 3 - (sz_c ** 3 + sz_p ** 3)
            if delta_cube <= 0 or (union_sz - sz_p) <= 1 or (union_sz - sz_c) <= 1:
                if best_gain is None or delta_cube < best_gain:
                    best_gain = delta_cube
                    best_c = c
        if best_c < 0:
            break
        p = parents[best_c]
        cliques[p] |= cliques[best_c]
        for k in range(L):
            if alive[k] and parents[k] == best_c:
                parents[k] = p
        alive[best_c] = False

    alive_indices = [k for k in range(L) if alive[k]]
    remap = {old: new for new, old in enumerate(alive_indices)}
    merged_cliques = [tuple(sorted(cliques[k])) for k in alive_indices]
    merged_parents = [-1 if parents[k] < 0 else remap[parents[k]] for k in alive_indices]
    return merged_cliques, merged_parents


def _chordal_psd_complete(
    dim: int,
    cliques: Sequence[tuple[int, ...]],
    parents: Sequence[int],
    clique_duals: Sequence[np.ndarray],
) -> np.ndarray:
    """Completação PSD exata de máxima entropia ao longo da árvore de cliques (sem linalg.inv).

    Dado Z_l >= 0 consistente nos separadores S_l = C_l cap C_{parent[l]}, reconstrói Z >= 0
    na dimensão original satisfazendo Z[C_l, C_l] = Z_l para todo l = 0..L-1 via complemento
    de Schur sequencial (Vandenberghe & Andersen 2015, Section 10.2 / Algorithm 10.1).
    """
    Z = np.zeros((dim, dim), dtype=np.float64)
    if not cliques:
        return Z

    verts0 = np.asarray(cliques[0], dtype=np.intp)
    Z[np.ix_(verts0, verts0)] = _sym(clique_duals[0])
    included = set(cliques[0])

    for c in range(1, len(cliques)):
        C_c = cliques[c]
        Z_c = _sym(clique_duals[c])
        loc = {v: i for i, v in enumerate(C_c)}
        B = [v for v in C_c if v in included]
        C_new = [v for v in C_c if v not in included]
        if not C_new:
            continue
        A = sorted(included - set(B))

        C_arr = np.asarray(C_new, dtype=np.intp)
        C_loc = np.asarray([loc[v] for v in C_new], dtype=np.intp)
        Z[np.ix_(C_arr, C_arr)] = Z_c[np.ix_(C_loc, C_loc)]

        if B:
            B_arr = np.asarray(B, dtype=np.intp)
            B_loc = np.asarray([loc[v] for v in B], dtype=np.intp)
            Z_BC = Z_c[np.ix_(B_loc, C_loc)]
            Z[np.ix_(B_arr, C_arr)] = Z_BC
            Z[np.ix_(C_arr, B_arr)] = Z_BC.T

            if A:
                A_arr = np.asarray(A, dtype=np.intp)
                Z_AB = Z[np.ix_(A_arr, B_arr)]
                Z_BB = _sym(Z[np.ix_(B_arr, B_arr)])
                evals_b, evecs_b = scipy.linalg.eigh(Z_BB)
                lam_max_b = float(np.max(evals_b)) if evals_b.size > 0 else 0.0
                if lam_max_b > 1e-14:
                    tol_b = max(1e-12 * max(1.0, lam_max_b), 1e-14)
                    mask_b = evals_b > tol_b
                    if np.any(mask_b):
                        Q_b = evecs_b[:, mask_b]
                        inv_l = 1.0 / evals_b[mask_b]
                        Z_AC = (Z_AB @ Q_b) @ (inv_l[:, None] * (Q_b.T @ Z_BC))
                        Z[np.ix_(A_arr, C_arr)] = Z_AC
                        Z[np.ix_(C_arr, A_arr)] = Z_AC.T

        included.update(C_new)

    return _sym(Z)


@dataclass(frozen=True)
class _ChordalBlockMapping:
    """Mapa de reconstrução de um bloco PSD (decomposto em cliques cordais ou intacto)."""

    orig_dim: int
    is_chordal: bool
    sub_indices: tuple[int, ...]
    cliques: tuple[tuple[int, ...], ...]
    parents: tuple[int, ...]


@dataclass(frozen=True)
class _ChordalDecompositionPlan:
    """Plano de decomposição cordal exata por cliques maximais (Teorema de Agler/Grone)."""

    decomposed_blocks: list[_InternalConeBlock]
    c_aug: np.ndarray
    m_orig: int
    m_aug: int
    mappings: tuple[_ChordalBlockMapping, ...]
    decomposed_blocks_count: int
    original_max_dim: int
    clique_max_dim: int
    num_cliques: int
    aux_vars_added: int

    @property
    def summary(self) -> dict[str, int]:
        return {
            "decomposed_blocks": int(self.decomposed_blocks_count),
            "original_max_dim": int(self.original_max_dim),
            "clique_max_dim": int(self.clique_max_dim),
            "num_cliques": int(self.num_cliques),
            "aux_vars_added": int(self.aux_vars_added),
        }

    def reassemble_duals(self, sub_duals: Sequence[np.ndarray]) -> list[np.ndarray]:
        """Reconstrói matrizes duais Z_b na dimensão de entrada via completação PSD cordal."""
        assembled: list[np.ndarray] = []
        for mp in self.mappings:
            if not mp.is_chordal:
                assembled.append(_sym(sub_duals[mp.sub_indices[0]]))
            else:
                clique_zs = [sub_duals[idx] for idx in mp.sub_indices]
                assembled.append(_chordal_psd_complete(mp.orig_dim, mp.cliques, mp.parents, clique_zs))
        return assembled


def _chordal_clique_decompose_psd_blocks(
    blocks: Sequence[_InternalConeBlock],
    c_y: np.ndarray,
    m_y: int,
    *,
    enabled: bool = True,
    min_dim: int = 8,
    max_density: float = 0.55,
) -> _ChordalDecompositionPlan:
    """Decompõe blocos PSD conexos esparsos em cliques maximais cordais (equivalência exata).

    Formulação dual exata via Teorema de Agler/Grone:
    Para um bloco conexo S(y) = F_0 + sum_k y_k F_k >= 0 com grafo de esparsidade cordal
    C_0, ..., C_{L-1} em árvore de cliques, atribui cada entrada (p, q) à raiz l_root(p, q)
    e introduz variáveis escalares auxiliares de sobreposição v_{c, p, q} (com custo zero)
    somando +v no clique c e -v no clique pai parent[c], de modo que:
        sum_{l=0}^{L-1} E_{C_l}^T S_l(y, v) E_{C_l} == S(y)   identicamente.
    No dual, a estacionariedade em v impõe (Z_c)_{p,q} = (Z_{parent[c]})_{p,q} em todos os
    separadores, garantindo completação PSD exata Z >= 0 no bloco original.

    Referências:
    - Vandenberghe & Andersen (2015, doi:10.1561/2400000006)
    - Garstka, Cannon & Goulart (IFAC 2020, doi:10.1016/j.ifacol.2020.12.1255)
    """
    psd_dims = [b.dim for b in blocks if not b.is_ineq_slack]
    max_psd_dim = max(psd_dims) if psd_dims else 0

    if not enabled:
        mappings_noop = tuple(
            _ChordalBlockMapping(
                orig_dim=blk.dim,
                is_chordal=False,
                sub_indices=(idx,),
                cliques=(tuple(range(blk.dim)),),
                parents=(-1,),
            )
            for idx, blk in enumerate(blocks)
        )
        return _ChordalDecompositionPlan(
            decomposed_blocks=list(blocks),
            c_aug=c_y.copy(),
            m_orig=m_y,
            m_aug=m_y,
            mappings=mappings_noop,
            decomposed_blocks_count=0,
            original_max_dim=max_psd_dim,
            clique_max_dim=max_psd_dim,
            num_cliques=0,
            aux_vars_added=0,
        )

    out_blocks: list[_InternalConeBlock] = []
    mappings: list[_ChordalBlockMapping] = []
    next_var_idx = m_y
    decomposed_count = 0
    decomp_orig_max = 0
    decomp_clique_max = 0
    total_cliques = 0

    for blk in blocks:
        if blk.is_ineq_slack or blk.dim < min_dim:
            sub_idx = len(out_blocks)
            out_blocks.append(blk)
            mappings.append(
                _ChordalBlockMapping(
                    orig_dim=blk.dim,
                    is_chordal=False,
                    sub_indices=(sub_idx,),
                    cliques=(tuple(range(blk.dim)),),
                    parents=(-1,),
                )
            )
            continue

        dim = blk.dim
        adj = np.abs(blk.F0) > 0.0
        for fk in blk.F_terms.values():
            adj |= np.abs(fk) > 0.0
        adj |= adj.T
        np.fill_diagonal(adj, False)

        nnz_off = int(np.count_nonzero(adj))
        density = (nnz_off + dim) / float(dim * dim)
        if density >= max_density:
            sub_idx = len(out_blocks)
            out_blocks.append(blk)
            mappings.append(
                _ChordalBlockMapping(
                    orig_dim=dim,
                    is_chordal=False,
                    sub_indices=(sub_idx,),
                    cliques=(tuple(range(dim)),),
                    parents=(-1,),
                )
            )
            continue

        _, elim_cliques = _min_degree_ordering(adj)
        cliques, parents = _chordal_clique_tree_and_merge(elim_cliques)
        if len(cliques) < 2:
            sub_idx = len(out_blocks)
            out_blocks.append(blk)
            mappings.append(
                _ChordalBlockMapping(
                    orig_dim=dim,
                    is_chordal=False,
                    sub_indices=(sub_idx,),
                    cliques=(tuple(range(dim)),),
                    parents=(-1,),
                )
            )
            continue

        max_c_sz = max(len(c) for c in cliques)
        separators: list[tuple[int, ...]] = [()]
        num_aux_block = 0
        for c_idx in range(1, len(cliques)):
            p_idx = parents[c_idx]
            sep = tuple(sorted(set(cliques[c_idx]) & set(cliques[p_idx])))
            separators.append(sep)
            s_len = len(sep)
            num_aux_block += (s_len * (s_len + 1)) // 2

        if max_c_sz >= dim or num_aux_block > max(64, dim * 3):
            sub_idx = len(out_blocks)
            out_blocks.append(blk)
            mappings.append(
                _ChordalBlockMapping(
                    orig_dim=dim,
                    is_chordal=False,
                    sub_indices=(sub_idx,),
                    cliques=(tuple(range(dim)),),
                    parents=(-1,),
                )
            )
            continue

        # Decomposição cordal aprovada! Construir sub-blocos de clique e variáveis auxiliares
        L = len(cliques)
        clique_locs: list[dict[int, int]] = [{v: i for i, v in enumerate(c)} for c in cliques]

        # Para cada par (u, v) com u <= v presente no grafo cordal, encontrar a raiz l_root(u, v)
        # (menor índice de clique contendo ambos u e v, válido pela ordem topológica da árvore)
        pair_owner: dict[tuple[int, int], int] = {}
        for l_idx, c_verts in enumerate(cliques):
            n_c = len(c_verts)
            for a_i in range(n_c):
                u = c_verts[a_i]
                for b_i in range(a_i, n_c):
                    v = c_verts[b_i]
                    key = (u, v)
                    if key not in pair_owner:
                        pair_owner[key] = l_idx

        clique_F0: list[np.ndarray] = [np.zeros((len(c), len(c)), dtype=np.float64) for c in cliques]
        clique_F_terms: list[dict[int, np.ndarray]] = [{} for _ in range(L)]

        # Atribuir entradas não-nulas de F0 à raiz l_root(u, v)
        nz_r0, nz_c0 = np.nonzero(blk.F0)
        for r_raw, c_raw in zip(nz_r0, nz_c0, strict=True):
            u, v = int(r_raw), int(c_raw)
            if u > v:
                continue
            val = float(blk.F0[u, v])
            if val == 0.0:
                continue
            owner = pair_owner[(u, v)]
            lu = clique_locs[owner][u]
            lv = clique_locs[owner][v]
            clique_F0[owner][lu, lv] = val
            if lu != lv:
                clique_F0[owner][lv, lu] = val

        # Atribuir entradas não-nulas de cada F_k à raiz l_root(u, v)
        for k_var, fk in blk.F_terms.items():
            nz_rk, nz_ck = np.nonzero(fk)
            for r_raw, c_raw in zip(nz_rk, nz_ck, strict=True):
                u, v = int(r_raw), int(c_raw)
                if u > v:
                    continue
                val = float(fk[u, v])
                if val == 0.0:
                    continue
                owner = pair_owner[(u, v)]
                terms_l = clique_F_terms[owner]
                mat_l = terms_l.get(k_var)
                if mat_l is None:
                    dim_l = len(cliques[owner])
                    mat_l = np.zeros((dim_l, dim_l), dtype=np.float64)
                    terms_l[k_var] = mat_l
                lu = clique_locs[owner][u]
                lv = clique_locs[owner][v]
                mat_l[lu, lv] = val
                if lu != lv:
                    mat_l[lv, lu] = val

        # Introduzir variáveis auxiliares de sobreposição ao longo das arestas (c_idx, p_idx)
        for c_idx in range(1, L):
            p_idx = parents[c_idx]
            sep = separators[c_idx]
            loc_c = clique_locs[c_idx]
            loc_p = clique_locs[p_idx]
            dim_c = len(cliques[c_idx])
            dim_p = len(cliques[p_idx])
            s_len = len(sep)
            for a_i in range(s_len):
                u = sep[a_i]
                for b_i in range(a_i, s_len):
                    v = sep[b_i]
                    aux_j = next_var_idx
                    next_var_idx += 1

                    mat_c = np.zeros((dim_c, dim_c), dtype=np.float64)
                    lcu, lcv = loc_c[u], loc_c[v]
                    mat_c[lcu, lcv] = 1.0
                    if lcu != lcv:
                        mat_c[lcv, lcu] = 1.0
                    clique_F_terms[c_idx][aux_j] = mat_c

                    mat_p = np.zeros((dim_p, dim_p), dtype=np.float64)
                    lpu, lpv = loc_p[u], loc_p[v]
                    mat_p[lpu, lpv] = -1.0
                    if lpu != lpv:
                        mat_p[lpv, lpu] = -1.0
                    clique_F_terms[p_idx][aux_j] = mat_p

        sub_indices: list[int] = []
        for l_idx, c_verts in enumerate(cliques):
            sub_idx = len(out_blocks)
            out_blocks.append(
                _InternalConeBlock(
                    name=f"{blk.name}__ch{l_idx}",
                    dim=len(c_verts),
                    F0=_sym(clique_F0[l_idx]),
                    F_terms=clique_F_terms[l_idx],
                    is_ineq_slack=blk.is_ineq_slack,
                    ineq_index=blk.ineq_index,
                    build_schur_index=False,
                )
            )
            sub_indices.append(sub_idx)

        mappings.append(
            _ChordalBlockMapping(
                orig_dim=dim,
                is_chordal=True,
                sub_indices=tuple(sub_indices),
                cliques=tuple(cliques),
                parents=tuple(parents),
            )
        )
        decomposed_count += 1
        decomp_orig_max = max(decomp_orig_max, dim)
        decomp_clique_max = max(decomp_clique_max, max_c_sz)
        total_cliques += L

    aux_added = next_var_idx - m_y
    if aux_added > 0:
        c_aug = np.concatenate([c_y, np.zeros((aux_added,), dtype=np.float64)])
    else:
        c_aug = c_y.copy()

    return _ChordalDecompositionPlan(
        decomposed_blocks=out_blocks,
        c_aug=c_aug,
        m_orig=m_y,
        m_aug=next_var_idx,
        mappings=tuple(mappings),
        decomposed_blocks_count=decomposed_count,
        original_max_dim=decomp_orig_max if decomposed_count > 0 else max_psd_dim,
        clique_max_dim=decomp_clique_max if decomposed_count > 0 else max_psd_dim,
        num_cliques=total_cliques,
        aux_vars_added=aux_added,
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
                build_schur_index=False,
            )
        )
    c_y_eq = d * c_y
    return scaled_blocks, c_y_eq, e, d


@dataclass(frozen=True)
class _SymbolicPreprocessPlan:
    """Plano de pré-processamento simbólico de colunas (eliminação de zeros e fusão de duplicatas)."""

    original_n_vars: int
    kept_vars: np.ndarray
    orig_to_red: dict[int, int]
    eliminated_zero_vars: tuple[int, ...]
    merged_duplicate_vars: tuple[tuple[int, int, float], ...]
    free_nonzero_cost_vars: tuple[tuple[int, float], ...]

    @property
    def reduced_n_vars(self) -> int:
        return int(self.kept_vars.size)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "original_n_vars": int(self.original_n_vars),
            "reduced_n_vars": int(self.kept_vars.size),
            "eliminated_zero_vars": int(len(self.eliminated_zero_vars)),
            "merged_duplicate_vars": int(len(self.merged_duplicate_vars)),
            "free_nonzero_cost_vars": int(len(self.free_nonzero_cost_vars)),
        }

    def reconstruct_x(self, x_red: np.ndarray) -> np.ndarray:
        """Reconstrói vetor primal completo x na dimensão original (zeros em colunas eliminadas/fundidas)."""
        if self.kept_vars.size == self.original_n_vars and not self.merged_duplicate_vars:
            return np.asarray(x_red, dtype=np.float64).copy()
        x_full = np.zeros((self.original_n_vars,), dtype=np.float64)
        if self.kept_vars.size > 0:
            x_full[self.kept_vars] = x_red
        return x_full

    def map_warm_start(self, x_ws_orig: np.ndarray) -> np.ndarray:
        """Projeta warm_start_x original para variáveis reduzidas preservando x_k1 + alpha * x_k2."""
        if self.kept_vars.size == 0:
            return np.zeros((0,), dtype=np.float64)
        x_ws_red = np.asarray(x_ws_orig[self.kept_vars], dtype=np.float64).copy()
        for orig_k, rep_red_idx, alpha in self.merged_duplicate_vars:
            x_ws_red[rep_red_idx] += alpha * float(x_ws_orig[orig_k])
        return x_ws_red

    def free_recession_direction(self) -> np.ndarray:
        """Constrói direção recessiva unitária a partir de variáveis livres com custo não-nulo."""
        d_free = np.zeros((self.original_n_vars,), dtype=np.float64)
        for orig_k, ck in self.free_nonzero_cost_vars:
            d_free[orig_k] = -ck
        nrm = float(np.linalg.norm(d_free))
        if nrm > 0.0:
            d_free /= nrm
        return d_free


def _preprocess_symbolic_columns(problem: CanonicalSDPProblem) -> _SymbolicPreprocessPlan:
    """Detecta e elimina colunas nulas e colunas colineares/duplicadas em O(nnz_total) via hash esparso.

    - Coluna nula (`F_{b,k} == 0`, `H[:,k] == 0`, `E[:,k] == 0`):
      - Se `c_k == 0`: eliminada (`x_k = 0.0` na reconstrução).
      - Se `c_k != 0`: registrada em `free_nonzero_cost_vars` para certificação exata de
        ilimitabilidade (caso primal factível) ou infactibilidade primal (Farkas).
    - Colunas colineares (`F_{b,k2} == alpha * F_{b,k1}`, `H[:,k2] == alpha * H[:,k1]`,
      `E[:,k2] == alpha * E[:,k1]`, `c[k2] == alpha * c[k1]` com `alpha != 0`):
      fundidas em `x_{k1}_tilde = x_{k1} + alpha * x_{k2}` (reconstrução `x_{k1} = x_{k1}_tilde`,
      `x_{k2} = 0`), preservando primalidade e dualidade exatas sem comparações densas O(m^2).
    """
    n_vars = problem.n_vars
    c_vec = problem.c
    col_keys: list[list[int]] = [[] for _ in range(n_vars)]
    col_vals: list[list[float]] = [[] for _ in range(n_vars)]

    # 1. Coletar entradas não-nulas dos blocos PSD em ordem canônica (section=0)
    for b_idx, blk in enumerate(problem.blocks):
        dim = blk.dim
        b_shift = int(b_idx) << 32
        for k, fk in blk.F_terms.items():
            fk_sym = 0.5 * (fk + fk.T)
            nz_r, nz_c = np.nonzero(np.abs(fk_sym) > 1e-15)
            if nz_r.size == 0:
                continue
            flat_idx = nz_r.astype(np.int64) * dim + nz_c.astype(np.int64)
            vals = fk_sym[nz_r, nz_c]
            ck_list = col_keys[k]
            cv_list = col_vals[k]
            for f_i, v_i in zip(flat_idx.tolist(), vals.tolist()):
                ck_list.append(b_shift | int(f_i))
                cv_list.append(float(v_i))

    # 2. Coletar entradas não-nulas de H (desigualdades lineares, section=1)
    if problem.n_ineq > 0:
        sec_h = 1 << 48
        nz_r, nz_c = np.nonzero(np.abs(problem.H) > 1e-15)
        if nz_r.size > 0:
            vals_h = problem.H[nz_r, nz_c]
            for r_i, c_i, v_i in zip(nz_r.tolist(), nz_c.tolist(), vals_h.tolist()):
                col_keys[c_i].append(sec_h | int(r_i))
                col_vals[c_i].append(float(v_i))

    # 3. Coletar entradas não-nulas de E (igualdades lineares, section=2)
    if problem.n_eq > 0:
        sec_e = 2 << 48
        nz_r, nz_c = np.nonzero(np.abs(problem.E) > 1e-15)
        if nz_r.size > 0:
            vals_e = problem.E[nz_r, nz_c]
            for r_i, c_i, v_i in zip(nz_r.tolist(), nz_c.tolist(), vals_e.tolist()):
                col_keys[c_i].append(sec_e | int(r_i))
                col_vals[c_i].append(float(v_i))

    kept_vars: list[int] = []
    eliminated_zero_vars: list[int] = []
    merged_duplicate_vars: list[tuple[int, int, float]] = []
    free_nonzero_cost_vars: list[tuple[int, float]] = []

    # Buckets de hash esparso: hash_key -> lista de (rep_red_idx, rep_orig_k, rep_keys, rep_vals, rep_pivot)
    buckets: dict[tuple[int, bytes, bytes], list[tuple[int, int, np.ndarray, np.ndarray, float]]] = {}

    for k in range(n_vars):
        ck_list = col_keys[k]
        if not ck_list:
            ck_val = float(c_vec[k])
            if abs(ck_val) <= 1e-15:
                eliminated_zero_vars.append(k)
            else:
                free_nonzero_cost_vars.append((k, ck_val))
            continue

        keys_arr = np.asarray(ck_list, dtype=np.int64)
        vals_arr = np.asarray(col_vals[k], dtype=np.float64)
        pivot_pos = int(np.argmax(np.abs(vals_arr)))
        pivot = float(vals_arr[pivot_pos])
        norm_vals = vals_arr / pivot
        h_key = (int(keys_arr.size), keys_arr.tobytes(), np.round(norm_vals, 9).tobytes())

        matched = False
        cand_list = buckets.get(h_key)
        if cand_list is not None:
            ck_val = float(c_vec[k])
            v_scale = max(1.0, float(np.max(np.abs(vals_arr))))
            for rep_red_idx, rep_orig_k, rep_keys, rep_vals, rep_pivot in cand_list:
                if not np.array_equal(keys_arr, rep_keys):
                    continue
                alpha = pivot / rep_pivot
                if not math.isfinite(alpha) or alpha == 0.0:
                    continue
                if float(np.max(np.abs(vals_arr - alpha * rep_vals))) > 1e-12 * v_scale:
                    continue
                c_rep = float(c_vec[rep_orig_k])
                c_scale_pair = max(1.0, abs(ck_val), abs(alpha * c_rep))
                if abs(ck_val - alpha * c_rep) > 1e-12 * c_scale_pair:
                    continue
                merged_duplicate_vars.append((k, rep_red_idx, float(alpha)))
                matched = True
                break

        if not matched:
            rep_red_idx = len(kept_vars)
            kept_vars.append(k)
            entry = (rep_red_idx, k, keys_arr, vals_arr, pivot)
            if cand_list is None:
                buckets[h_key] = [entry]
            else:
                cand_list.append(entry)

    kept_arr = np.asarray(kept_vars, dtype=np.intp)
    orig_to_red = {orig_k: red_i for red_i, orig_k in enumerate(kept_vars)}
    return _SymbolicPreprocessPlan(
        original_n_vars=n_vars,
        kept_vars=kept_arr,
        orig_to_red=orig_to_red,
        eliminated_zero_vars=tuple(eliminated_zero_vars),
        merged_duplicate_vars=tuple(merged_duplicate_vars),
        free_nonzero_cost_vars=tuple(free_nonzero_cost_vars),
    )


def solve_native_raw(
    problem: CanonicalSDPProblem,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve CanonicalSDPProblem pelo método didático de Pontos Interiores Primal-Dual.

    Retorna dicionário compatível com `SDPBackend.solve_raw` e `verify()`, enriquecido
    com o histórico completo do caminho central (`history`, `phase1_summary`, `phase2_summary`,
    `hsde_summary`, `schur_assembly_modes`, `preprocessing_summary`).
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
    opt_cancel = options.get("cancel_check") if isinstance(options, Mapping) else None
    cancel_cb = opt_cancel if callable(opt_cancel) else get_cancel_check()

    # -----------------------------------------------------------------------
    # Passo 0: Pré-processamento simbólico de colunas redundantes (ADR-015 Ciclo 3)
    # -----------------------------------------------------------------------
    pre_plan = _preprocess_symbolic_columns(problem)
    preprocessing_summary = pre_plan.summary
    has_free_nonzero_cost = len(pre_plan.free_nonzero_cost_vars) > 0
    zero_schur_modes = {"F1": 0, "F2": 0, "F3_blas": 0, "LP_1D": 0}

    n_vars_orig = problem.n_vars
    n_vars = pre_plan.reduced_n_vars
    n_psd = problem.n_blocks
    n_eq = problem.n_eq
    n_ineq = problem.n_ineq
    c_orig = (
        np.zeros((n_vars,), dtype=np.float64)
        if has_free_nonzero_cost
        else (problem.c[pre_plan.kept_vars].copy() if n_vars > 0 else np.zeros((0,), dtype=np.float64))
    )
    c0_orig = float(problem.c0)
    E_mat = problem.E[:, pre_plan.kept_vars] if n_eq > 0 else np.zeros((0, n_vars), dtype=np.float64)
    H_mat = problem.H[:, pre_plan.kept_vars] if n_ineq > 0 else np.zeros((0, n_vars), dtype=np.float64)
    red_psd_terms: list[dict[int, np.ndarray]] = [
        {pre_plan.orig_to_red[k]: fk for k, fk in blk.F_terms.items() if k in pre_plan.orig_to_red}
        for blk in problem.blocks
    ]
    warnings_out: list[WarningItem] = []

    def _finalize_feasible_or_unbounded_free(
        x_red_vec: np.ndarray,
        *,
        iterations_count: int,
        factorizations_count: int,
        schur_modes: dict[str, int],
        phase1_sum: dict[str, Any] | None = None,
        phase2_sum: dict[str, Any] | None = None,
        hsde_sum: dict[str, Any] | None = None,
        decomp_sum: dict[str, Any] | None = None,
        all_hist: list[IterationRecord] | None = None,
    ) -> dict[str, Any]:
        """Quando há variáveis livres com custo não-nulo, qualquer ponto factível certifica dual_infeasible."""
        x_feas_full = pre_plan.reconstruct_x(x_red_vec)
        d_free = pre_plan.free_recession_direction()
        out_free: dict[str, Any] = {
            "backend": "native_primal_dual",
            "maturity": "beta",
            "experimental": False,
            "method": "primal_dual_hsde_nt_mehrotra_gondzio",
            "solver_status": "dual_infeasible",
            "raw_status": "symbolic_free_variable_unbounded",
            "hsde_certificate": "dual_infeasible",
            "iterations": int(iterations_count),
            "factorizations": int(factorizations_count),
            "solve_time": float(time.perf_counter() - t_start),
            "objective": None,
            "feasible_x0": x_feas_full,
            "recession_direction": d_free,
            "history": [h.to_dict() for h in (all_hist or [])] if cfg.record_history else [],
            "iteration_log": iteration_log,
            "preprocessing_summary": preprocessing_summary,
            "schur_assembly_modes": schur_modes,
            "warnings": warnings_out,
        }
        if phase1_sum is not None:
            out_free["phase1_summary"] = phase1_sum
        if phase2_sum is not None:
            out_free["phase2_summary"] = phase2_sum
        if hsde_sum is not None:
            out_free["hsde_summary"] = hsde_sum
        if decomp_sum is not None:
            out_free["decomposition_summary"] = decomp_sum
        return out_free

    # -----------------------------------------------------------------------
    # Passo 1: Redução de igualdades lineares E x = d via SVD (sem inv!)
    # -----------------------------------------------------------------------
    if n_eq > 0:
        if n_vars == 0:
            res_eq = -problem.d
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
                    "preprocessing_summary": preprocessing_summary,
                    "schur_assembly_modes": zero_schur_modes,
                    "warnings": warnings_out,
                }
            U_eq = np.zeros((n_eq, 0), dtype=np.float64)
            s_eq = np.zeros((0,), dtype=np.float64)
            Vt_eq = np.zeros((0, 0), dtype=np.float64)
            rank_eq = 0
            x_eq = np.zeros((0,), dtype=np.float64)
            N_eq = np.zeros((0, 0), dtype=np.float64)
        else:
            U_eq, s_eq, Vt_eq = scipy.linalg.svd(E_mat, full_matrices=True, check_finite=True)
            s_max_eq = float(s_eq[0]) if s_eq.size > 0 else 0.0
            rank_eq = int(np.sum(s_eq > 1e-12 * max(1.0, s_max_eq)))
            x_eq = np.zeros((n_vars,), dtype=np.float64)
            for i in range(rank_eq):
                coeff = float(np.dot(U_eq[:, i], problem.d)) / float(s_eq[i])
                x_eq = x_eq + coeff * Vt_eq[i, :]
            res_eq = E_mat @ x_eq - problem.d
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
                    "preprocessing_summary": preprocessing_summary,
                    "schur_assembly_modes": zero_schur_modes,
                    "warnings": warnings_out,
                }
            N_eq: np.ndarray | None = Vt_eq[rank_eq:, :].T  # (n_vars, n_vars - rank_eq)
    else:
        U_eq = np.zeros((0, 0), dtype=np.float64)
        s_eq = np.zeros((0,), dtype=np.float64)
        Vt_eq = np.zeros((0, 0), dtype=np.float64)
        rank_eq = 0
        x_eq = np.zeros((n_vars,), dtype=np.float64)
        N_eq = None

    def _map_y_to_x_delta(y_vec: np.ndarray) -> np.ndarray:
        return y_vec if N_eq is None else (N_eq @ y_vec)

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
    m_y = n_vars if N_eq is None else int(N_eq.shape[1])
    c_y = (
        c_orig.copy()
        if N_eq is None
        else (N_eq.T @ c_orig if m_y > 0 else np.zeros((0,), dtype=np.float64))
    )
    c0_y = c0_orig + (float(np.dot(c_orig, x_eq)) if n_vars > 0 else 0.0)

    y_blocks: list[_InternalConeBlock] = []
    if n_eq == 0:
        for blk, r_terms in zip(problem.blocks, red_psd_terms, strict=True):
            F0_y = blk.F0.copy()
            F_terms_y = {
                j: fk.copy()
                for j, fk in r_terms.items()
                if float(np.linalg.norm(fk, "fro")) > 1e-15
            }
            y_blocks.append(
                _InternalConeBlock(
                    name=blk.name,
                    dim=blk.dim,
                    F0=F0_y,
                    F_terms=F_terms_y,
                    force_schur_mode=cfg.schur_mode,
                    build_schur_index=False,
                )
            )
    else:
        for blk, r_terms in zip(problem.blocks, red_psd_terms, strict=True):
            F0_y = blk.F0.copy()
            for k_r, fk in r_terms.items():
                xk = float(x_eq[k_r])
                if xk != 0.0:
                    F0_y = F0_y + xk * fk
            F0_y = _sym(F0_y)
            F_terms_y = {}
            for j in range(m_y):
                col_j = N_eq[:, j]
                mat_j = np.zeros((blk.dim, blk.dim), dtype=np.float64)
                for k_r, fk in r_terms.items():
                    vj = float(col_j[k_r])
                    if vj != 0.0:
                        mat_j = mat_j + vj * fk
                mat_j = _sym(mat_j)
                if float(np.linalg.norm(mat_j, "fro")) > 1e-15:
                    F_terms_y[j] = mat_j
            y_blocks.append(
                _InternalConeBlock(
                    name=blk.name,
                    dim=blk.dim,
                    F0=F0_y,
                    F_terms=F_terms_y,
                    force_schur_mode=cfg.schur_mode,
                    build_schur_index=False,
                )
            )

    for i_idx in range(n_ineq):
        h_row = H_mat[i_idx, :]
        h_val = float(problem.h[i_idx]) if (n_eq == 0 or n_vars == 0) else float(problem.h[i_idx] - np.dot(h_row, x_eq))
        F0_ineq = np.array([[h_val]], dtype=np.float64)
        h_y = -h_row if n_eq == 0 else (-(N_eq.T @ h_row) if m_y > 0 else np.zeros((0,), dtype=np.float64))
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
        for r_terms, Z_b in zip(red_psd_terms, Z_all[:n_psd], strict=True):
            for k, fk in r_terms.items():
                adj_x[k] += float(np.sum(fk * Z_b))
        if d_ineq is not None and n_ineq > 0 and n_vars > 0:
            adj_x = adj_x - (H_mat.T @ d_ineq)
        return adj_x

    if len(y_blocks) == 0:
        if has_free_nonzero_cost:
            return _finalize_feasible_or_unbounded_free(
                x_eq,
                iterations_count=0,
                factorizations_count=0,
                schur_modes=zero_schur_modes,
            )
        if float(np.linalg.norm(c_y)) <= 1e-12:
            nu_opt = _recover_eq_dual(np.zeros((n_vars,), dtype=np.float64), c_orig)
            x_full_0 = pre_plan.reconstruct_x(x_eq)
            return {
                "backend": "native_primal_dual",
                "maturity": "beta",
                "experimental": False,
                "method": "primal_dual_nt_mehrotra_interior_point",
                "solver_status": "optimal",
                "raw_status": "unconstrained_nullspace_optimal",
                "iterations": 0,
                "solve_time": float(time.perf_counter() - t_start),
                "x": x_full_0,
                "objective": float(problem.evaluate_objective(x_full_0)),
                "dual_Z": [],
                "dual_eq": nu_opt,
                "dual_ineq": None,
                "history": [],
                "iteration_log": iteration_log,
                "preprocessing_summary": preprocessing_summary,
                "schur_assembly_modes": zero_schur_modes,
                "warnings": warnings_out,
            }
        d_ray = pre_plan.reconstruct_x(-_map_y_to_x_delta(c_y / float(np.linalg.norm(c_y))))
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
            "feasible_x0": pre_plan.reconstruct_x(x_eq),
            "recession_direction": d_ray,
            "history": [],
            "iteration_log": iteration_log,
            "preprocessing_summary": preprocessing_summary,
            "schur_assembly_modes": zero_schur_modes,
            "warnings": warnings_out,
        }

    if m_y == 0:
        min_eigs = [float(np.min(np.linalg.eigvalsh(b.F0))) for b in y_blocks]
        if min(min_eigs) >= -cfg.tol_psd:
            if has_free_nonzero_cost:
                return _finalize_feasible_or_unbounded_free(
                    x_eq,
                    iterations_count=0,
                    factorizations_count=0,
                    schur_modes=_count_schur_modes(y_blocks),
                )
            Z_zero = [np.zeros((b.dim, b.dim), dtype=np.float64) for b in y_blocks]
            dZ, d_ineq = _split_duals(Z_zero)
            nu_opt = _recover_eq_dual(np.zeros((n_vars,), dtype=np.float64), c_orig)
            x_full_0 = pre_plan.reconstruct_x(x_eq)
            return {
                "backend": "native_primal_dual",
                "maturity": "beta",
                "experimental": False,
                "method": "primal_dual_nt_mehrotra_interior_point",
                "solver_status": "optimal",
                "raw_status": "fixed_by_equalities_optimal",
                "iterations": 0,
                "solve_time": float(time.perf_counter() - t_start),
                "x": x_full_0,
                "objective": float(problem.evaluate_objective(x_full_0)),
                "dual_Z": dZ,
                "dual_eq": nu_opt,
                "dual_ineq": d_ineq,
                "history": [],
                "iteration_log": iteration_log,
                "preprocessing_summary": preprocessing_summary,
                "schur_assembly_modes": _count_schur_modes(y_blocks),
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
            "preprocessing_summary": preprocessing_summary,
            "schur_assembly_modes": _count_schur_modes(y_blocks),
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
    # Passo 2.4b: Decomposição cordal por cliques maximais em blocos PSD conexos esparsos
    # (Vandenberghe & Andersen 2015, doi:10.1561/2400000006; Garstka et al., IFAC 2020)
    # -----------------------------------------------------------------------
    chordal_plan = _chordal_clique_decompose_psd_blocks(
        y_blocks_dec,
        c_y,
        m_y,
        enabled=(cfg.use_chordal and cfg.warm_start_x is None),
    )
    y_blocks_ch = chordal_plan.decomposed_blocks
    c_y_ch = chordal_plan.c_aug
    m_y_aug = chordal_plan.m_aug
    chordal_summary = chordal_plan.summary

    # -----------------------------------------------------------------------
    # Passo 2.5: Equilibração de Ruiz multi-varredura com recorte [1e-4, 1e4]
    # (Goulart & Chen, 2024, arXiv:2405.12762, Clarabel §2.4 & §2.6)
    # Desescala tanto primal x (via d_ruiz) quanto dual Z_b = e_b * Z'_b e
    # remonta blocos decompostos (completação PSD cordal + componentes conexas)
    # antes da auditoria independente no problema original.
    # -----------------------------------------------------------------------
    y_blocks_eq, c_y_eq, e_ruiz, d_ruiz = _ruiz_equilibrate_blocks(
        y_blocks_ch,
        c_y_ch,
        m_y_aug,
        max_sweeps=5,
        min_scale=1e-4,
        max_scale=1e4,
    )

    def _unscale_and_reassemble_duals(Z_sub_scaled: Sequence[np.ndarray]) -> list[np.ndarray]:
        Z_sub_unscaled = [_sym(float(eb) * Z_b) for Z_b, eb in zip(Z_sub_scaled, e_ruiz, strict=True)]
        Z_chordal_completed = chordal_plan.reassemble_duals(Z_sub_unscaled)
        return decomp_plan.reassemble_duals(Z_chordal_completed)

    # -----------------------------------------------------------------------
    # Passo 3: Equilíbrio esparso de colunas (CSC) ou SVD se rank-deficiente
    # -----------------------------------------------------------------------
    total_entries = sum(b.dim * b.dim for b in y_blocks_eq)
    cone_rows_parts: list[np.ndarray] = []
    cone_cols_parts: list[np.ndarray] = []
    cone_vals_parts: list[np.ndarray] = []
    lp_cone_rows: list[int] = []
    lp_cone_cols: list[int] = []
    lp_cone_vals: list[float] = []
    row_ofs = 0
    for b in y_blocks_eq:
        bsz = b.dim * b.dim
        if b.dim == 1:
            for j, fj in b.F_terms.items():
                val = float(fj[0, 0])
                if val != 0.0:
                    lp_cone_rows.append(row_ofs)
                    lp_cone_cols.append(j)
                    lp_cone_vals.append(val)
        else:
            for j, fj in b.F_terms.items():
                flat_fj = fj.ravel()
                nz_idx = np.flatnonzero(flat_fj)
                if nz_idx.size > 0:
                    cone_rows_parts.append(nz_idx + row_ofs)
                    cone_cols_parts.append(np.full(nz_idx.shape, j, dtype=np.int64))
                    cone_vals_parts.append(flat_fj[nz_idx])
        row_ofs += bsz

    if lp_cone_vals:
        cone_rows_parts.append(np.asarray(lp_cone_rows, dtype=np.int64))
        cone_cols_parts.append(np.asarray(lp_cone_cols, dtype=np.int64))
        cone_vals_parts.append(np.asarray(lp_cone_vals, dtype=np.float64))

    if cone_vals_parts:
        A_cone_csc = scipy.sparse.csc_matrix(
            (
                np.concatenate(cone_vals_parts),
                (np.concatenate(cone_rows_parts), np.concatenate(cone_cols_parts)),
            ),
            shape=(total_entries, m_y_aug),
            dtype=np.float64,
        )
    else:
        A_cone_csc = scipy.sparse.csc_matrix((total_entries, m_y_aug), dtype=np.float64)
    del cone_rows_parts, cone_cols_parts, cone_vals_parts, lp_cone_rows, lp_cone_cols, lp_cone_vals

    col_norms = np.sqrt(np.asarray(A_cone_csc.power(2).sum(axis=0)).ravel())
    use_sparse_col_scaling = False
    if m_y_aug > 0 and float(np.min(col_norms)) > 1e-12:
        col_inv_cand = 1.0 / col_norms
        A_col_scaled_csc = A_cone_csc @ scipy.sparse.diags(col_inv_cand, format="csc")
        G_cone_sp = (A_col_scaled_csc.T @ A_col_scaled_csc).tocsc()
        del A_col_scaled_csc

        if m_y_aug >= 48 and (G_cone_sp.nnz / float(m_y_aug * m_y_aug)) < 0.30:
            # 1) Condição suficiente O(nnz) de Gershgorin (dominância diagonal estrita => SPD garantido)
            g_diag = G_cone_sp.diagonal()
            g_abs_row_sum = np.asarray(np.abs(G_cone_sp).sum(axis=1)).ravel()
            if float(np.min(2.0 * g_diag - g_abs_row_sum)) > 1e-6:
                use_sparse_col_scaling = True
            else:
                # 2) Fatoração SuperLU esparsa simétrica sem materializar matriz densa (m, m)
                G_cone_sym_csc = (0.5 * (G_cone_sp + G_cone_sp.T)).tocsc()
                checked_sparse = False
                try:
                    lu_cone = scipy.sparse.linalg.splu(
                        G_cone_sym_csc,
                        permc_spec="MMD_AT_PLUS_A",
                        diag_pivot_thresh=0.01,
                        options={"SymmetricMode": True},
                    )
                    diag_u = np.abs(lu_cone.U.diagonal())
                    if diag_u.size > 0 and np.all(np.isfinite(diag_u)):
                        u_max = float(np.max(diag_u))
                        u_min = float(np.min(diag_u))
                        if u_max > 0.0 and u_min > 1e-10 and (u_max / max(u_min, 1e-15)) < 1e10:
                            use_sparse_col_scaling = True
                        checked_sparse = True
                except (RuntimeError, ValueError) as exc:
                    if "singular" in str(exc).lower():
                        checked_sparse = True
                del G_cone_sym_csc
                if not checked_sparse and not use_sparse_col_scaling:
                    cho_cone = _safe_cholesky(_sym(G_cone_sp.toarray()))
                    if cho_cone is not None:
                        diag_lc = np.abs(np.diag(cho_cone[0]))
                        if diag_lc.size > 0 and float(np.max(diag_lc)) / max(float(np.min(diag_lc)), 1e-15) < 1e5:
                            use_sparse_col_scaling = True
        else:
            cho_cone = _safe_cholesky(_sym(G_cone_sp.toarray()))
            if cho_cone is not None:
                diag_lc = np.abs(np.diag(cho_cone[0]))
                if diag_lc.size > 0 and float(np.max(diag_lc)) / max(float(np.min(diag_lc)), 1e-15) < 1e5:
                    use_sparse_col_scaling = True
        del G_cone_sp

    if use_sparse_col_scaling:
        col_inv = 1.0 / col_norms
        Q_N = np.zeros((m_y_aug, 0), dtype=np.float64)
        m_z = m_y_aug
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
                force_schur_mode=cfg.schur_mode,
            )
            for b in y_blocks_eq
        ]

        def _map_z_to_y(z_vec: np.ndarray) -> np.ndarray:
            return col_inv * z_vec

        def _project_y_to_z(y_vec: np.ndarray) -> np.ndarray:
            return col_norms * y_vec
    else:
        A_cone = A_cone_csc.toarray()
        _, s_cone, Vt_cone = scipy.linalg.svd(A_cone, full_matrices=(total_entries < m_y_aug), check_finite=True)
        del A_cone
        s_cone_max = float(s_cone[0]) if s_cone.size > 0 else 0.0
        rank_cone = int(np.sum(s_cone > 1e-12 * max(1.0, s_cone_max)))
        # Escalar pelas inversas dos valores singulares para que as matrizes base em z sejam ortonormais
        Q_R = Vt_cone[:rank_cone, :].T / s_cone[:rank_cone]  # (m_y_aug, rank_cone)
        Q_N = Vt_cone[rank_cone:, :].T                       # (m_y_aug, m_y_aug - rank_cone)

        m_z = rank_cone
        c_z = Q_R.T @ c_y_eq
        c_null = Q_N.T @ c_y_eq

        A_cone_csr = A_cone_csc.tocsr()
        z_blocks = []
        b_ofs = 0
        _SVD_PROJ_CHUNK = 128
        for b in y_blocks_eq:
            dim_b = b.dim
            bsz = dim_b * dim_b
            A_blk_csr = A_cone_csr[b_ofs : b_ofs + bsz, :]
            b_ofs += bsz
            F_terms_z: dict[int, np.ndarray] = {}
            if A_blk_csr.nnz > 0 and m_z > 0:
                for j0 in range(0, m_z, _SVD_PROJ_CHUNK):
                    j1 = min(j0 + _SVD_PROJ_CHUNK, m_z)
                    proj_chunk = np.asarray(A_blk_csr @ Q_R[:, j0:j1], dtype=np.float64)
                    if dim_b == 1:
                        nz_cols = np.flatnonzero(np.abs(proj_chunk[0, :]) > 1e-15)
                        for local_j in nz_cols.tolist():
                            F_terms_z[j0 + local_j] = np.array(
                                [[float(proj_chunk[0, local_j])]], dtype=np.float64
                            )
                    else:
                        col_nrms = np.linalg.norm(proj_chunk, axis=0)
                        for local_j in np.flatnonzero(col_nrms > 1e-15).tolist():
                            mj = proj_chunk[:, local_j].reshape((dim_b, dim_b))
                            F_terms_z[j0 + local_j] = 0.5 * (mj + mj.T)
            z_blocks.append(
                _InternalConeBlock(
                    name=b.name,
                    dim=dim_b,
                    F0=b.F0,
                    F_terms=F_terms_z,
                    is_ineq_slack=b.is_ineq_slack,
                    ineq_index=b.ineq_index,
                    force_schur_mode=cfg.schur_mode,
                )
            )
        del A_cone_csr

        def _map_z_to_y(z_vec: np.ndarray) -> np.ndarray:
            return Q_R @ z_vec

        def _project_y_to_z(y_vec: np.ndarray) -> np.ndarray:
            return s_cone[:rank_cone] * (Vt_cone[:rank_cone, :] @ y_vec)

    del A_cone_csc

    def _map_z_to_x_delta(z_vec: np.ndarray) -> np.ndarray:
        return _map_y_to_x_delta((d_ruiz * _map_z_to_y(z_vec))[:m_y])

    schur_modes_z = _count_schur_modes(z_blocks)

    all_history: list[IterationRecord] = []
    phase1_summary: dict[str, Any] = {"executed": False, "iterations": 0, "status": "skipped", "warm_start_used": False}
    phase2_summary: dict[str, Any] = {"executed": False, "iterations": 0, "status": "skipped"}
    hsde_summary: dict[str, Any] = {
        "executed": False,
        "iterations": 0,
        "status": "skipped",
        "hsde_certificate": "none",
        "factorizations": 0,
        "gondzio_correctors_attempted": 0,
        "gondzio_correctors_accepted": 0,
    }

    # -----------------------------------------------------------------------
    # Passo 4: Warm-Start (Ding et al., arXiv:2312.11801), HSDE (ADR-015) ou Fase I
    # -----------------------------------------------------------------------
    z0 = np.zeros((m_z,), dtype=np.float64)
    warm_start_used = False
    if cfg.warm_start_x is not None:
        if len(cfg.warm_start_x) != n_vars_orig:
            raise ValidationError(
                f"warm_start_x deve ter comprimento {n_vars_orig}, recebido {len(cfg.warm_start_x)}."
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
            x_ws_red = pre_plan.map_warm_start(x_ws)
            y_ws = (x_ws_red - x_eq) if N_eq is None else (N_eq.T @ (x_ws_red - x_eq))
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

    # -----------------------------------------------------------------------
    # Passo 4a: Embedding Homogêneo Autodual (HSDE) em passagem única (ADR-015 Ciclo 2)
    # -----------------------------------------------------------------------
    if cfg.use_hsde and not warm_start_used and float(np.linalg.norm(c_null)) <= 1e-12:
        hsde_out = _run_hsde_cone_loop(
            z_blocks,
            c_z,
            c0_y,
            max_iter=cfg.max_iter,
            tol_gap=cfg.tol_gap,
            tol_feas=cfg.tol_feas,
            strict_margin=cfg.strict_margin,
            step_fraction=cfg.step_fraction,
            sigma_min=cfg.sigma_min,
            sigma_max=cfg.sigma_max,
            max_gondzio_correctors=cfg.max_gondzio_correctors,
            sparse_schur_density_threshold=cfg.sparse_schur_density_threshold,
            sparse_schur_min_dim=cfg.sparse_schur_min_dim,
            schur_factorization_mode=cfg.schur_factorization_mode,
            t_start=t_start,
            iteration_log=iteration_log,
            progress_callback=progress_cb,
            cancel_check=cancel_cb,
        )
        hsde_status = str(hsde_out["solver_status"])
        hsde_cert = str(hsde_out.get("hsde_certificate", "none"))
        hsde_modes = dict(hsde_out.get("schur_assembly_modes", schur_modes_z))
        hsde_fac_mode = str(hsde_out.get("schur_factorization_mode", "dense_cholesky"))
        hsde_summary = {
            "executed": True,
            "iterations": len(hsde_out["history"]),
            "status": hsde_status,
            "hsde_certificate": hsde_cert,
            "tau": float(hsde_out["tau"]),
            "kappa": float(hsde_out["kappa"]),
            "factorizations": int(hsde_out["factorizations"]),
            "gondzio_correctors_attempted": int(hsde_out["gondzio_correctors_attempted"]),
            "gondzio_correctors_accepted": int(hsde_out["gondzio_correctors_accepted"]),
        }
        if hsde_out.get("farkas_dual_residual_rel") is not None:
            hsde_summary["farkas_dual_residual_rel"] = float(hsde_out["farkas_dual_residual_rel"])
        if hsde_out.get("farkas_objective") is not None:
            hsde_summary["farkas_objective"] = float(hsde_out["farkas_objective"])

        if hsde_status in ("optimal", "optimal_inaccurate"):
            all_history.extend(hsde_out["history"])
            z_final = hsde_out["z"]
            x_final_red = x_eq + _map_z_to_x_delta(z_final)
            if has_free_nonzero_cost:
                return _finalize_feasible_or_unbounded_free(
                    x_final_red,
                    iterations_count=len(all_history),
                    factorizations_count=int(hsde_out["factorizations"]),
                    schur_modes=hsde_modes,
                    phase1_sum=phase1_summary,
                    phase2_sum=phase2_summary,
                    hsde_sum=hsde_summary,
                    decomp_sum=decomposition_summary,
                    all_hist=all_history,
                )
            x_final = pre_plan.reconstruct_x(x_final_red)
            Z_final_all = _unscale_and_reassemble_duals(hsde_out["Z_list"])
            dZ, d_ineq = _split_duals(Z_final_all)
            adj_x = _full_adjoint_x(Z_final_all, d_ineq)
            d_eq = _recover_eq_dual(adj_x, c_orig)
            obj_final = float(problem.evaluate_objective(x_final))
            if hsde_status == "optimal_inaccurate":
                warnings_out.append(
                    WarningItem(
                        code="EDUCATIONAL_SOLVER_INACCURATE",
                        message="Solver primal-dual (HSDE) convergiu com precisão reduzida (optimal_inaccurate).",
                    )
                )
            return {
                "backend": "native_primal_dual",
                "maturity": "beta",
                "experimental": False,
                "method": "primal_dual_hsde_nt_mehrotra_gondzio",
                "solver_status": hsde_status,
                "raw_status": f"hsde_{hsde_status}",
                "hsde_certificate": hsde_cert,
                "iterations": len(all_history),
                "factorizations": int(hsde_out["factorizations"]),
                "gondzio_correctors_attempted": int(hsde_out["gondzio_correctors_attempted"]),
                "gondzio_correctors_accepted": int(hsde_out["gondzio_correctors_accepted"]),
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
                "hsde_summary": hsde_summary,
                "decomposition_summary": decomposition_summary,
                "chordal_summary": chordal_summary,
                "preprocessing_summary": preprocessing_summary,
                "schur_assembly_modes": hsde_modes,
                "schur_factorization_mode": hsde_fac_mode,
                "warnings": warnings_out,
            }

        if hsde_status == "primal_infeasible" and hsde_out.get("farkas_candidate") is not None:
            all_history.extend(hsde_out["history"])
            farkas_Z_unscaled = _unscale_and_reassemble_duals(hsde_out["farkas_candidate"])
            fZ, f_ineq = _split_duals(farkas_Z_unscaled)
            adj_f = _full_adjoint_x(farkas_Z_unscaled, f_ineq)
            f_eq = _recover_eq_dual(adj_f, np.zeros((n_vars,), dtype=np.float64))
            return {
                "backend": "native_primal_dual",
                "maturity": "beta",
                "experimental": False,
                "method": "primal_dual_hsde_nt_mehrotra_gondzio",
                "solver_status": "primal_infeasible",
                "raw_status": "hsde_primal_infeasible_farkas",
                "hsde_certificate": "primal_infeasible",
                "iterations": len(all_history),
                "factorizations": int(hsde_out["factorizations"]),
                "gondzio_correctors_attempted": int(hsde_out["gondzio_correctors_attempted"]),
                "gondzio_correctors_accepted": int(hsde_out["gondzio_correctors_accepted"]),
                "solve_time": float(time.perf_counter() - t_start),
                "objective": None,
                "farkas_Z": fZ,
                "farkas_eq": f_eq,
                "farkas_ineq": f_ineq,
                "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
                "iteration_log": iteration_log,
                "phase1_summary": phase1_summary,
                "phase2_summary": phase2_summary,
                "hsde_summary": hsde_summary,
                "decomposition_summary": decomposition_summary,
                "chordal_summary": chordal_summary,
                "preprocessing_summary": preprocessing_summary,
                "schur_assembly_modes": hsde_modes,
                "schur_factorization_mode": hsde_fac_mode,
                "warnings": warnings_out,
            }

        if hsde_status == "dual_infeasible" and hsde_out.get("recession_candidate") is not None:
            d_z = hsde_out["recession_candidate"]
            z_feas_cand: np.ndarray | None = None
            if init_min_eig >= -1e-9:
                z_feas_cand = z0
            else:
                for t_ray in (1.0, 10.0, 1e2, 1e3, 1e5, 1e7):
                    z_try = t_ray * d_z
                    if min(_min_eig_sym(b.evaluate(z_try)) for b in z_blocks) >= -1e-9:
                        z_feas_cand = z_try
                        break
            if z_feas_cand is not None:
                all_history.extend(hsde_out["history"])
                x_feas_h = pre_plan.reconstruct_x(x_eq + _map_z_to_x_delta(z_feas_cand))
                d_x = pre_plan.reconstruct_x(_map_z_to_x_delta(d_z))
                return {
                    "backend": "native_primal_dual",
                    "maturity": "beta",
                    "experimental": False,
                    "method": "primal_dual_hsde_nt_mehrotra_gondzio",
                    "solver_status": "dual_infeasible",
                    "raw_status": "hsde_dual_infeasible_unbounded",
                    "hsde_certificate": "dual_infeasible",
                    "iterations": len(all_history),
                    "factorizations": int(hsde_out["factorizations"]),
                    "gondzio_correctors_attempted": int(hsde_out["gondzio_correctors_attempted"]),
                    "gondzio_correctors_accepted": int(hsde_out["gondzio_correctors_accepted"]),
                    "solve_time": float(time.perf_counter() - t_start),
                    "objective": None,
                    "feasible_x0": x_feas_h,
                    "recession_direction": d_x,
                    "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
                    "iteration_log": iteration_log,
                    "phase1_summary": phase1_summary,
                    "phase2_summary": phase2_summary,
                    "hsde_summary": hsde_summary,
                    "decomposition_summary": decomposition_summary,
                    "chordal_summary": chordal_summary,
                    "preprocessing_summary": preprocessing_summary,
                    "schur_assembly_modes": hsde_modes,
                    "schur_factorization_mode": hsde_fac_mode,
                    "warnings": warnings_out,
                }

        # Recuo seguro para Fase I/II somente se HSDE estagnou sem certificar
        hsde_summary["fallback_to_phase1_phase2"] = True

    if not warm_start_used and (init_min_eig <= cfg.strict_margin or is_pure_feasibility):
        # Construir problema auxiliar de Fase I:
        #   min_{z, t}  t   s.t.   F_b(z) + t I_{n_b} >= 0,  t_cap + t >= 0
        t_cap = 1.0
        p1_blocks: list[_InternalConeBlock] = []
        for b in z_blocks:
            terms_p1 = dict(b.F_terms)
            terms_p1[m_z] = np.eye(b.dim, dtype=np.float64)
            p1_blocks.append(
                _InternalConeBlock(
                    name=b.name,
                    dim=b.dim,
                    F0=b.F0,
                    F_terms=terms_p1,
                    force_schur_mode=cfg.schur_mode,
                )
            )

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
            max_gondzio_correctors=cfg.max_gondzio_correctors,
            sparse_schur_density_threshold=cfg.sparse_schur_density_threshold,
            sparse_schur_min_dim=cfg.sparse_schur_min_dim,
            schur_factorization_mode=cfg.schur_factorization_mode,
            t_start=t_start,
            iteration_log=iteration_log,
            progress_callback=progress_cb,
            cancel_check=cancel_cb,
        )
        all_history.extend(p1_out["history"])
        p1_modes = dict(p1_out.get("schur_assembly_modes", schur_modes_z))
        p1_fac_mode = str(p1_out.get("schur_factorization_mode", "dense_cholesky"))
        phase1_summary = {
            "executed": True,
            "iterations": len(p1_out["history"]),
            "status": p1_out["solver_status"],
            "final_t": float(p1_out["z"][m_z]),
            "warm_start_used": False,
            "factorizations": int(p1_out.get("factorizations", 0)),
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
                    "factorizations": int(phase1_summary.get("factorizations", 0)),
                    "solve_time": float(time.perf_counter() - t_start),
                    "objective": None,
                    "farkas_Z": fZ,
                    "farkas_eq": f_eq,
                    "farkas_ineq": f_ineq,
                    "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
                    "iteration_log": iteration_log,
                    "phase1_summary": phase1_summary,
                    "phase2_summary": phase2_summary,
                    "hsde_summary": hsde_summary,
                    "decomposition_summary": decomposition_summary,
                    "chordal_summary": chordal_summary,
                    "preprocessing_summary": preprocessing_summary,
                    "schur_assembly_modes": p1_modes,
                    "schur_factorization_mode": p1_fac_mode,
                    "warnings": warnings_out,
                }

            x_cand_red = x_eq + _map_z_to_x_delta(z_cand)
            x_cand = pre_plan.reconstruct_x(x_cand_red)
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
                "preprocessing_summary": preprocessing_summary,
                "schur_assembly_modes": p1_modes,
                "warnings": warnings_out,
            }
            if cand_feasible_bound:
                out_inc["x"] = x_cand
            return out_inc

    # -----------------------------------------------------------------------
    # Passo 5: Checar direções livres no núcleo N_cone (ex.: variável livre no objetivo)
    # -----------------------------------------------------------------------
    x_feas0_red = x_eq + _map_z_to_x_delta(z0)
    if has_free_nonzero_cost:
        return _finalize_feasible_or_unbounded_free(
            x_feas0_red,
            iterations_count=len(all_history),
            factorizations_count=int(phase1_summary.get("factorizations", 0)),
            schur_modes=schur_modes_z,
            phase1_sum=phase1_summary,
            phase2_sum=phase2_summary,
            hsde_sum=hsde_summary,
            decomp_sum=decomposition_summary,
            all_hist=all_history,
        )
    x_feas0 = pre_plan.reconstruct_x(x_feas0_red)
    if float(np.linalg.norm(c_null)) > 1e-12:
        # Variável livre sem restrições com custo não nulo -> problema ilimitado certificado!
        d_y = (d_ruiz * (-(Q_N @ (c_null / float(np.linalg.norm(c_null))))))[:m_y]
        d_x = pre_plan.reconstruct_x(_map_y_to_x_delta(d_y))
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
            "chordal_summary": chordal_summary,
            "preprocessing_summary": preprocessing_summary,
            "schur_assembly_modes": schur_modes_z,
            "schur_factorization_mode": "dense_cholesky",
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
            "factorizations": int(phase1_summary.get("factorizations", 0)),
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
            "hsde_summary": hsde_summary,
            "decomposition_summary": decomposition_summary,
            "chordal_summary": chordal_summary,
            "preprocessing_summary": preprocessing_summary,
            "schur_assembly_modes": schur_modes_z,
            "schur_factorization_mode": "dense_cholesky",
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
        max_gondzio_correctors=cfg.max_gondzio_correctors,
        sparse_schur_density_threshold=cfg.sparse_schur_density_threshold,
        sparse_schur_min_dim=cfg.sparse_schur_min_dim,
        schur_factorization_mode=cfg.schur_factorization_mode,
        t_start=t_start,
        iteration_log=iteration_log,
        progress_callback=progress_cb,
        cancel_check=cancel_cb,
    )
    all_history.extend(p2_out["history"])
    p2_status = str(p2_out["solver_status"])
    p1_facs = int(phase1_summary.get("factorizations", 0))
    p2_facs = int(p2_out.get("factorizations", 0))
    p2_modes = dict(p2_out.get("schur_assembly_modes", schur_modes_z))
    p2_fac_mode = str(p2_out.get("schur_factorization_mode", "dense_cholesky"))
    phase2_summary = {
        "executed": True,
        "iterations": len(p2_out["history"]),
        "status": p2_status,
        "factorizations": p2_facs,
    }

    if p2_status == "dual_infeasible":
        d_z = p2_out["recession_candidate"]
        d_x = pre_plan.reconstruct_x(_map_z_to_x_delta(d_z)) if d_z is not None else None
        return {
            "backend": "native_primal_dual",
            "maturity": "beta",
            "experimental": False,
            "method": "primal_dual_nt_mehrotra_interior_point",
            "solver_status": "dual_infeasible",
            "raw_status": "phase2_recession_unbounded",
            "iterations": len(all_history),
            "factorizations": p1_facs + p2_facs,
            "gondzio_correctors_attempted": int(p2_out.get("gondzio_correctors_attempted", 0)),
            "gondzio_correctors_accepted": int(p2_out.get("gondzio_correctors_accepted", 0)),
            "solve_time": float(time.perf_counter() - t_start),
            "objective": None,
            "feasible_x0": x_feas0,
            "recession_direction": d_x,
            "history": [h.to_dict() for h in all_history] if cfg.record_history else [],
            "iteration_log": iteration_log,
            "phase1_summary": phase1_summary,
            "phase2_summary": phase2_summary,
            "hsde_summary": hsde_summary,
            "decomposition_summary": decomposition_summary,
            "chordal_summary": chordal_summary,
            "preprocessing_summary": preprocessing_summary,
            "schur_assembly_modes": p2_modes,
            "schur_factorization_mode": p2_fac_mode,
            "warnings": warnings_out,
        }

    z_final = p2_out["z"]
    x_final = pre_plan.reconstruct_x(x_eq + _map_z_to_x_delta(z_final))
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
        "factorizations": p1_facs + p2_facs,
        "gondzio_correctors_attempted": int(p2_out.get("gondzio_correctors_attempted", 0)),
        "gondzio_correctors_accepted": int(p2_out.get("gondzio_correctors_accepted", 0)),
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
        "hsde_summary": hsde_summary,
        "decomposition_summary": decomposition_summary,
        "chordal_summary": chordal_summary,
        "preprocessing_summary": preprocessing_summary,
        "schur_assembly_modes": p2_modes,
        "schur_factorization_mode": p2_fac_mode,
        "warnings": warnings_out,
    }
