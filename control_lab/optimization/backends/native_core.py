"""Native NumPy/SciPy NT/Mehrotra primal-dual kernel promoted under ADR-010.

Canonical primal/dual signs and certificates are checked by the separate verifier.
The educational API delegates to this same numerical kernel.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import time
from typing import Any, Mapping, Sequence
import numpy as np
import scipy.linalg
from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import ValidationError, WarningItem
from ..modeling.canonical import CanonicalSDPProblem

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
        }
        kwargs: dict[str, Any] = {}
        for k, v in options.items():
            if k not in allowed:
                raise ValidationError(f"Opção desconhecida para solver SDP educacional: {k!r}.")
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
    """Bloco simétrico interno (bloco PSD original ou desigualdade escalar 1x1)."""

    name: str
    dim: int
    F0: np.ndarray
    F_terms: dict[int, np.ndarray]
    is_ineq_slack: bool = False
    ineq_index: int | None = None

    def evaluate(self, z: np.ndarray) -> np.ndarray:
        res = self.F0.copy()
        for j, fj in self.F_terms.items():
            zj = float(z[j])
            if zj != 0.0:
                res = res + zj * fj
        return 0.5 * (res + res.T)

    def evaluate_linear(self, dz: np.ndarray) -> np.ndarray:
        res = np.zeros((self.dim, self.dim), dtype=np.float64)
        for j, fj in self.F_terms.items():
            dzj = float(dz[j])
            if dzj != 0.0:
                res = res + dzj * fj
        return 0.5 * (res + res.T)


# ---------------------------------------------------------------------------
# Utilitários de Álgebra Linear Numérica (Zero uso de np.linalg.inv!)
# ---------------------------------------------------------------------------


def _sym(M: np.ndarray) -> np.ndarray:
    return 0.5 * (M + M.T)


def _safe_cholesky(M: np.ndarray) -> tuple[np.ndarray, bool] | None:
    """Retorna fatoração de Cholesky (L, True) se M for estritamente SPD, ou None."""
    Ms = _sym(M)
    if not np.all(np.isfinite(Ms)):
        return None
    try:
        return scipy.linalg.cho_factor(Ms, lower=True, check_finite=True)
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


def _solve_symmetric_system(H: np.ndarray, rhs: np.ndarray) -> tuple[np.ndarray, float]:
    """Resolve H dx = rhs com precondicionamento diagonal de Jacobi + Cholesky + refino iterativo."""
    H_sym = _sym(H)
    n = H_sym.shape[0]
    if n == 0:
        return np.zeros((0,), dtype=np.float64), 1.0

    # Escalonamento simétrico de Jacobi D^{-1} H D^{-1} para equilibrar blocos perto/longe da fronteira
    diag_h = np.diag(H_sym)
    d_scale = np.sqrt(np.maximum(np.abs(diag_h), 1e-30))
    inv_d = 1.0 / d_scale
    H_scaled = _sym((inv_d[:, None] * H_sym) * inv_d[None, :])
    rhs_scaled = inv_d * rhs

    svals = scipy.linalg.svd(H_scaled, compute_uv=False, check_finite=True)
    s_max = float(svals[0]) if svals.size > 0 else 0.0
    s_min = float(svals[-1]) if svals.size > 0 else 0.0
    cond = float(s_max / s_min) if s_min > 1e-16 * max(1.0, s_max) else 1e16

    cho = _safe_cholesky(H_scaled)
    if cho is not None:
        sol_s = scipy.linalg.cho_solve(cho, rhs_scaled, check_finite=True)
        # Até 2 passos de refino iterativo para restaurar dígitos perdidos perto da fronteira
        for _ in range(2):
            res_s = rhs_scaled - H_scaled @ sol_s
            corr_s = scipy.linalg.cho_solve(cho, res_s, check_finite=True)
            if not np.all(np.isfinite(corr_s)):
                break
            cand_s = sol_s + corr_s
            if float(np.linalg.norm(H_scaled @ cand_s - rhs_scaled)) < float(np.linalg.norm(res_s)):
                sol_s = cand_s
            else:
                break
        return np.asarray(inv_d * sol_s, dtype=np.float64), cond

    # Regularização modificada apenas no espaço escalonado unitário caso H seja singular/indefinida
    for reg_exp in (1e-13, 1e-11, 1e-9):
        cho_reg = _safe_cholesky(H_scaled + reg_exp * max(1.0, s_max) * np.eye(n, dtype=np.float64))
        if cho_reg is not None:
            sol_s = scipy.linalg.cho_solve(cho_reg, rhs_scaled, check_finite=True)
            return np.asarray(inv_d * sol_s, dtype=np.float64), cond

    sol_s, _, _, _ = scipy.linalg.lstsq(H_scaled, rhs_scaled, cond=1e-13, check_finite=True)
    return np.asarray(inv_d * sol_s, dtype=np.float64), cond


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
        min_e = float(np.min(np.linalg.eigvalsh(Z_cand)))
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


def _max_step_scaled_identity(lam: np.ndarray, dM_tilde: np.ndarray) -> float:
    """Maior alpha > 0 tal que diag(lam) + alpha * dM_tilde >= 0 sem inversão."""
    dM_sym = _sym(dM_tilde)
    if not np.all(np.isfinite(dM_sym)):
        return 0.0
    if float(np.linalg.norm(dM_sym, "fro")) <= 1e-16:
        return float("inf")
    inv_sqrt = 1.0 / np.sqrt(np.maximum(lam, 1e-30))
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
) -> dict[str, Any]:
    """Executa Pontos Interiores Primal-Dual (Nesterov-Todd + Mehrotra Preditor-Corretor).

    Resolve:
        min_{z in R^m}   c_vec^T z + c0
        sujeito a        S_b(z) = F_{b,0} + sum_{j=0}^{m-1} z_j F_{b,j} >= 0   (b = 0..B_int-1)
    """
    m = int(c_vec.shape[0])
    n_blocks = len(blocks)
    total_order = sum(b.dim for b in blocks)
    z = np.array(z_init, dtype=np.float64, copy=True)
    z0_initial = z.copy()

    S_list = [b.evaluate(z) for b in blocks]
    cho_S_list: list[tuple[np.ndarray, bool]] = []
    for b_idx, S_b in enumerate(S_list):
        cho = _safe_cholesky(S_b)
        if cho is None:
            eigs = np.linalg.eigvalsh(S_b)
            shift = max(1e-3, -float(np.min(eigs)) + 1e-2)
            S_b = _sym(S_b + shift * np.eye(S_b.shape[0], dtype=np.float64))
            S_list[b_idx] = S_b
            cho = _safe_cholesky(S_b)
            assert cho is not None
        cho_S_list.append(cho)

    c_scale = max(1.0, float(np.linalg.norm(c_vec)))
    Z_list = [c_scale * np.eye(b.dim, dtype=np.float64) for b in blocks]
    cho_Z_list: list[tuple[np.ndarray, bool]] = []
    for Z_b in Z_list:
        cho_z = _safe_cholesky(Z_b)
        assert cho_z is not None
        cho_Z_list.append(cho_z)

    history: list[IterationRecord] = []
    solver_status = "max_iterations"
    farkas_candidate: list[np.ndarray] | None = None
    recession_candidate: np.ndarray | None = None

    for it in range(max_iter):
        # 1. Avaliar folgas primais exatas, gap de complementaridade e resíduo dual
        S_eval = [b.evaluate(z) for b in blocks]
        cho_eval = [_safe_cholesky(S_b) for S_b in S_eval]
        if all(c is not None for c in cho_eval):
            S_list = S_eval
            cho_S_list = [c for c in cho_eval if c is not None]

        R_p_list = [S_b - S_ev for S_b, S_ev in zip(S_list, S_eval, strict=True)]
        gap = sum(float(np.sum(S_b * Z_b)) for S_b, Z_b in zip(S_list, Z_list, strict=True))
        mu = gap / max(1, total_order)

        adj = np.zeros((m,), dtype=np.float64)
        dual_scale = 1.0 + float(np.linalg.norm(c_vec))
        for blk, Z_b in zip(blocks, Z_list, strict=True):
            znorm = float(np.linalg.norm(Z_b, "fro"))
            for j, fj in blk.F_terms.items():
                adj[j] += float(np.sum(fj * Z_b))
                dual_scale += float(np.linalg.norm(fj, "fro")) * znorm

        r_d = c_vec - adj
        r_d_rel = float(np.linalg.norm(r_d) / dual_scale)

        primal_obj = float(np.dot(c_vec, z) + c0)
        dual_obj = float(c0 - sum(float(np.sum(blk.F0 * Z_b)) for blk, Z_b in zip(blocks, Z_list, strict=True)))
        rel_gap = abs(primal_obj - dual_obj) / (1.0 + abs(primal_obj) + abs(dual_obj))
        comp_scale = 1.0 + sum(
            float(np.linalg.norm(S_b, "fro") * np.linalg.norm(Z_b, "fro"))
            for S_b, Z_b in zip(S_list, Z_list, strict=True)
        )
        comp_rel = abs(gap) / comp_scale

        min_eig_p = min(float(np.min(np.linalg.eigvalsh(S_ev))) for S_ev in S_eval)
        min_eig_d = min(float(np.min(np.linalg.eigvalsh(Z_b))) for Z_b in Z_list)

        # Parada antecipada de Fase I assim que atingirmos ponto estritamente interior
        if stop_on_negative_obj_margin is not None and primal_obj < -stop_on_negative_obj_margin:
            n_check = check_farkas_on_blocks if check_farkas_on_blocks is not None else n_blocks
            orig_min_eig = min(
                float(np.min(np.linalg.eigvalsh(
                    blocks[b_i].F0 + sum(float(z[j]) * fj for j, fj in blocks[b_i].F_terms.items() if j < m - 1)
                )))
                for b_i in range(n_check)
            )
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
                solver_status = "optimal"
                break

        # Em Fase I, checar se o dual atual já projeta para um certificado de Farkas estrito
        if check_farkas_on_blocks is not None and primal_obj > 0.0:
            orig_blocks = blocks[:check_farkas_on_blocks]
            orig_Z = Z_list[:check_farkas_on_blocks]
            orig_W = [_cho_solve_mat(cho_S_list[b_i], np.eye(orig_blocks[b_i].dim)) for b_i in range(check_farkas_on_blocks)]
            m_orig = m - 1
            sub_blocks = [
                _InternalConeBlock(
                    name=b.name,
                    dim=b.dim,
                    F0=b.F0,
                    F_terms={j: fj for j, fj in b.F_terms.items() if j < m_orig},
                )
                for b in orig_blocks
            ]
            Z_proj = _project_dual_onto_subspace(
                sub_blocks,
                m_orig,
                orig_Z,
                np.zeros((m_orig,), dtype=np.float64),
                weight_mats=orig_W,
            )
            if Z_proj is not None:
                Z_strict = _validate_strict_farkas_certificate(sub_blocks, m_orig, Z_proj)
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
                        solver_status = "primal_infeasible"
                        break

        # Critério de convergência primal-dual (alinhado ao verificador independente)
        primal_slack_err = max(float(np.linalg.norm(rp, "fro")) for rp in R_p_list) if R_p_list else 0.0
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
            solver_status = "optimal"
            break

        # 2. Escalonamento de Nesterov-Todd (NT) por bloco e matriz de Schur simétrica SPD
        nt_data: list[tuple[np.ndarray, np.ndarray, np.ndarray, dict[int, np.ndarray], np.ndarray]] = []
        H = np.zeros((m, m), dtype=np.float64)

        for blk, cho_S, cho_Z, R_p in zip(blocks, cho_S_list, cho_Z_list, R_p_list, strict=True):
            G_b, G_invT_b, lam_b = _nt_scaling_factors(cho_S, cho_Z)
            F_hat_dict: dict[int, np.ndarray] = {}
            active_keys = sorted(blk.F_terms.keys())
            for j in active_keys:
                F_hat_dict[j] = _sym(G_invT_b.T @ blk.F_terms[j] @ G_invT_b)
            R_p_hat = _sym(G_invT_b.T @ R_p @ G_invT_b)
            nt_data.append((G_b, G_invT_b, lam_b, F_hat_dict, R_p_hat))

            if active_keys:
                cols = np.column_stack([F_hat_dict[j].ravel() for j in active_keys])
                gram = cols.T @ cols
                H[np.ix_(active_keys, active_keys)] += gram

        # 3. Passo Preditor Afim de Mehrotra (sigma = 0): dS_tilde + dZ_tilde = -diag(lam)
        rhs_aff = -r_d.copy()
        for blk, (_, _, lam_b, F_hat_dict, R_p_hat) in zip(blocks, nt_data, strict=True):
            M_aff_b = -np.diag(lam_b) + R_p_hat
            for j, fhat_j in F_hat_dict.items():
                rhs_aff[j] += float(np.sum(fhat_j * M_aff_b))

        dz_aff, cond_H = _solve_symmetric_system(H, rhs_aff)

        # Checar se dz_aff revela direção recessiva ilimitada (c^T dz_aff < 0 e F_lin >= 0)
        if check_farkas_on_blocks is None and float(np.dot(c_vec, dz_aff)) < -1e-7 * c_scale * float(np.linalg.norm(dz_aff)):
            lin_S_aff = [blk.evaluate_linear(dz_aff) for blk in blocks]
            min_lin_eig = min(float(np.min(np.linalg.eigvalsh(M_lin))) for M_lin in lin_S_aff)
            dz_norm = float(np.linalg.norm(dz_aff))
            if dz_norm > 1e-12 and min_lin_eig >= -1e-10 * dz_norm:
                recession_candidate = dz_aff / dz_norm
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
                        step_norm=dz_norm,
                    )
                )
                solver_status = "dual_infeasible"
                break

        dS_tilde_aff: list[np.ndarray] = []
        dZ_tilde_aff: list[np.ndarray] = []
        alpha_p_aff = 1.0
        alpha_d_aff = 1.0

        for _, _, lam_b, F_hat_dict, R_p_hat in nt_data:
            ds_t = -R_p_hat
            for j, fhat_j in F_hat_dict.items():
                dzj = float(dz_aff[j])
                if dzj != 0.0:
                    ds_t = ds_t + dzj * fhat_j
            ds_t = _sym(ds_t)
            dz_t = _sym(-np.diag(lam_b) - ds_t)
            dS_tilde_aff.append(ds_t)
            dZ_tilde_aff.append(dz_t)
            alpha_p_aff = min(alpha_p_aff, step_fraction * _max_step_scaled_identity(lam_b, ds_t))
            alpha_d_aff = min(alpha_d_aff, step_fraction * _max_step_scaled_identity(lam_b, dz_t))

        gap_aff = sum(
            float(np.sum((np.diag(lam_b) + alpha_p_aff * ds_t) * (np.diag(lam_b) + alpha_d_aff * dz_t)))
            for (_, _, lam_b, _, _), ds_t, dz_t in zip(nt_data, dS_tilde_aff, dZ_tilde_aff, strict=True)
        )
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
        rhs_cor = -r_d.copy()
        M_cor_list: list[np.ndarray] = []
        for (blk, (_, _, lam_b, F_hat_dict, R_p_hat), ds_t, dz_t) in zip(
            blocks, nt_data, dS_tilde_aff, dZ_tilde_aff, strict=True
        ):
            second_order = _sym(ds_t @ dz_t) if eta_meh != 0.0 else 0.0
            rhs_lyap = np.diag(sigma * mu - lam_b * lam_b) - eta_meh * second_order
            lam_sum = lam_b[:, None] + lam_b[None, :]
            M_cor_b = _sym((2.0 * rhs_lyap) / np.maximum(lam_sum, 1e-30))
            M_cor_list.append(M_cor_b)
            eff_b = M_cor_b + R_p_hat
            for j, fhat_j in F_hat_dict.items():
                rhs_cor[j] += float(np.sum(fhat_j * eff_b))

        dz, _ = _solve_symmetric_system(H, rhs_cor)

        dS_tilde_list: list[np.ndarray] = []
        dZ_tilde_list: list[np.ndarray] = []
        dZ_list: list[np.ndarray] = []
        alpha_p_max = float("inf")
        alpha_d_max = float("inf")

        for (G_b, G_invT_b, lam_b, F_hat_dict, R_p_hat), M_cor_b in zip(nt_data, M_cor_list, strict=True):
            ds_t = -R_p_hat
            for j, fhat_j in F_hat_dict.items():
                dzj = float(dz[j])
                if dzj != 0.0:
                    ds_t = ds_t + dzj * fhat_j
            ds_t = _sym(ds_t)
            dz_t = _sym(M_cor_b - ds_t)
            dS_tilde_list.append(ds_t)
            dZ_tilde_list.append(dz_t)
            dZ_list.append(_sym(G_invT_b @ dz_t @ G_invT_b.T))
            alpha_p_max = min(alpha_p_max, _max_step_scaled_identity(lam_b, ds_t))
            alpha_d_max = min(alpha_d_max, _max_step_scaled_identity(lam_b, dz_t))

        alpha_p = min(1.0, step_fraction * alpha_p_max)
        alpha_d = min(1.0, step_fraction * alpha_d_max)

        # Backtracking para garantir estrita positividade via Cholesky exata no espaço original
        while alpha_p > 1e-12:
            z_trial = z + alpha_p * dz
            S_trial = [b.evaluate(z_trial) for b in blocks]
            cho_p_trial = [_safe_cholesky(St) for St in S_trial]
            if all(c is not None for c in cho_p_trial):
                S_list = S_trial
                cho_S_list = [c for c in cho_p_trial if c is not None]
                z = z_trial
                break
            alpha_p *= 0.5
        else:
            z = z + alpha_p * dz
            dS_orig = [-rp + b.evaluate_linear(dz) for b, rp in zip(blocks, R_p_list, strict=True)]
            S_list = [_sym(S_b + alpha_p * dS) for S_b, dS in zip(S_list, dS_orig, strict=True)]
            cho_S_list = [_safe_cholesky(S_b) or cho_S_list[i] for i, S_b in enumerate(S_list)]

        while alpha_d > 1e-12:
            Z_trial = [_sym(Z_b + alpha_d * dZ) for Z_b, dZ in zip(Z_list, dZ_list, strict=True)]
            cho_d_trial = [_safe_cholesky(Zt) for Zt in Z_trial]
            if all(c is not None for c in cho_d_trial):
                Z_list = Z_trial
                cho_Z_list = [c for c in cho_d_trial if c is not None]
                break
            alpha_d *= 0.5

        step_norm = float(np.linalg.norm(alpha_p * dz))
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

        # Detecção de divergência ilimitada ao longo de raio factível
        if check_farkas_on_blocks is None and float(np.linalg.norm(z - z0_initial)) > unbounded_norm_threshold:
            disp = z - z0_initial
            disp_norm = float(np.linalg.norm(disp))
            if disp_norm > 0.0 and float(np.dot(c_vec, disp)) < -1e-6 * c_scale * disp_norm:
                d_cand = disp / disp_norm
                min_lin = min(float(np.min(np.linalg.eigvalsh(blk.evaluate_linear(d_cand)))) for blk in blocks)
                if min_lin >= -1e-8:
                    recession_candidate = d_cand
                    solver_status = "dual_infeasible"
                    break

        # Em Fase I, interromper se ||z|| divergir sem encontrar interior (típico de weak infeasibility)
        if check_farkas_on_blocks is not None and m > 1:
            if float(np.linalg.norm(z[: m - 1])) > max(1e9, 100.0 * unbounded_norm_threshold):
                orig_min_now = min(
                    float(
                        np.min(
                            np.linalg.eigvalsh(
                                blocks[b_i].F0
                                + sum(float(z[j]) * fj for j, fj in blocks[b_i].F_terms.items() if j < m - 1)
                            )
                        )
                    )
                    for b_i in range(check_farkas_on_blocks)
                )
                if orig_min_now <= 0.0:
                    solver_status = "max_iterations"
                    break

        if step_norm <= 1e-14 * (1.0 + float(np.linalg.norm(z))) and max(rel_gap, comp_rel) <= 10.0 * tol_gap:
            solver_status = "optimal" if r_d_rel <= 10.0 * tol_feas else "optimal_inaccurate"
            break

    # Polimento final do certificado dual no subespaço estacionário sum_b <F_{b,j}, Z_b> = c_j
    if solver_status in ("optimal", "optimal_inaccurate", "max_iterations"):
        W_final = [_cho_solve_mat(cho_S, np.eye(b.dim, dtype=np.float64)) for b, cho_S in zip(blocks, cho_S_list, strict=True)]
        Z_pol = _project_dual_onto_subspace(blocks, m, Z_list, c_vec, weight_mats=W_final)
        if Z_pol is None:
            W_damped = [_sym(Z_b + 1e-4 * np.eye(b.dim, dtype=np.float64)) for b, Z_b in zip(blocks, Z_list, strict=True)]
            Z_pol = _project_dual_onto_subspace(blocks, m, Z_list, c_vec, weight_mats=W_damped)
        if Z_pol is not None:
            Z_list = Z_pol

        S_eval = [b.evaluate(z) for b in blocks]
        min_eig_p = min(float(np.min(np.linalg.eigvalsh(S_ev))) for S_ev in S_eval)
        primal_obj = float(np.dot(c_vec, z) + c0)
        dual_obj = float(c0 - sum(float(np.sum(blk.F0 * Z_b)) for blk, Z_b in zip(blocks, Z_list, strict=True)))
        rel_gap = abs(primal_obj - dual_obj) / (1.0 + abs(primal_obj) + abs(dual_obj))
        adj = np.zeros((m,), dtype=np.float64)
        dual_scale = 1.0 + float(np.linalg.norm(c_vec))
        for blk, Z_b in zip(blocks, Z_list, strict=True):
            znorm = float(np.linalg.norm(Z_b, "fro"))
            for j, fj in blk.F_terms.items():
                adj[j] += float(np.sum(fj * Z_b))
                dual_scale += float(np.linalg.norm(fj, "fro")) * znorm
        r_d_rel = float(np.linalg.norm(c_vec - adj) / dual_scale)
        if min_eig_p >= -1e-7 and r_d_rel <= 1e-6 and rel_gap <= 1e-6:
            solver_status = "optimal"
        elif min_eig_p >= -1e-5 and r_d_rel <= 1e-4 and rel_gap <= 1e-4:
            solver_status = "optimal_inaccurate"

    return {
        "solver_status": solver_status,
        "z": z,
        "Z_list": Z_list,
        "S_list": [b.evaluate(z) for b in blocks],
        "farkas_candidate": farkas_candidate,
        "recession_candidate": recession_candidate,
        "history": history,
    }


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
    for b_idx, blk in enumerate(problem.blocks):
        F0_y = blk.evaluate(x_eq)
        F_terms_y: dict[int, np.ndarray] = {}
        for j in range(m_y):
            mat_j = blk.evaluate_linear(N_eq[:, j])
            if float(np.linalg.norm(mat_j, "fro")) > 1e-15:
                F_terms_y[j] = mat_j
        y_blocks.append(_InternalConeBlock(name=blk.name, dim=blk.dim, F0=F0_y, F_terms=F_terms_y))

    for i_idx in range(n_ineq):
        h_row = problem.H[i_idx, :]
        h_val = float(problem.h[i_idx] - np.dot(h_row, x_eq))
        F0_ineq = np.array([[h_val]], dtype=np.float64)
        h_y = -(N_eq.T @ h_row)
        F_terms_ineq: dict[int, np.ndarray] = {}
        for j in range(m_y):
            if abs(float(h_y[j])) > 1e-15:
                F_terms_ineq[j] = np.array([[float(h_y[j])]], dtype=np.float64)
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
            "warnings": warnings_out,
        }

    # -----------------------------------------------------------------------
    # Passo 3: Decompor e ortonormalizar o operador cônico via SVD
    # -----------------------------------------------------------------------
    total_entries = sum(b.dim * b.dim for b in y_blocks)
    A_cone = np.zeros((total_entries, m_y), dtype=np.float64)
    row_ofs = 0
    for b in y_blocks:
        bsz = b.dim * b.dim
        for j, fj in b.F_terms.items():
            A_cone[row_ofs : row_ofs + bsz, j] = fj.ravel()
        row_ofs += bsz

    _, s_cone, Vt_cone = scipy.linalg.svd(A_cone, full_matrices=(total_entries < m_y), check_finite=True)
    s_cone_max = float(s_cone[0]) if s_cone.size > 0 else 0.0
    rank_cone = int(np.sum(s_cone > 1e-12 * max(1.0, s_cone_max)))
    # Escalar pelas inversas dos valores singulares para que as matrizes base em z sejam ortonormais
    Q_R = Vt_cone[:rank_cone, :].T / s_cone[:rank_cone]  # (m_y, rank_cone)
    Q_N = Vt_cone[rank_cone:, :].T                       # (m_y, m_y - rank_cone)

    m_z = rank_cone
    c_z = Q_R.T @ c_y
    c_null = Q_N.T @ c_y

    z_blocks: list[_InternalConeBlock] = []
    for b in y_blocks:
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

    all_history: list[IterationRecord] = []
    phase1_summary: dict[str, Any] = {"executed": False, "iterations": 0, "status": "skipped"}
    phase2_summary: dict[str, Any] = {"executed": False, "iterations": 0, "status": "skipped"}

    # -----------------------------------------------------------------------
    # Passo 4: Fase I (encontrar ponto estritamente factível z0 ou Farkas)
    # -----------------------------------------------------------------------
    z0 = np.zeros((m_z,), dtype=np.float64)
    init_min_eig = min(float(np.min(np.linalg.eigvalsh(b.evaluate(z0)))) for b in z_blocks)
    is_pure_feasibility = float(np.linalg.norm(c_z)) <= 1e-12 and float(np.linalg.norm(c_null)) <= 1e-12

    if init_min_eig <= cfg.strict_margin or is_pure_feasibility:
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
        )
        all_history.extend(p1_out["history"])
        phase1_summary = {
            "executed": True,
            "iterations": len(p1_out["history"]),
            "status": p1_out["solver_status"],
            "final_t": float(p1_out["z"][m_z]),
        }

        z_cand = p1_out["z"][:m_z]
        cand_min_eig = min(float(np.min(np.linalg.eigvalsh(b.evaluate(z_cand)))) for b in z_blocks)

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
                fZ, f_ineq = _split_duals(farkas_Z_internal)
                adj_f = _full_adjoint_x(farkas_Z_internal, f_ineq)
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
                    "phase1_summary": phase1_summary,
                    "phase2_summary": phase2_summary,
                    "warnings": warnings_out,
                }

            x_cand = x_eq + N_eq @ (Q_R @ z_cand)
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
    x_feas0 = x_eq + N_eq @ (Q_R @ z0)
    if float(np.linalg.norm(c_null)) > 1e-12:
        # Variável livre sem restrições com custo não nulo -> problema ilimitado certificado!
        d_y = -(Q_N @ (c_null / float(np.linalg.norm(c_null))))
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
            "phase1_summary": phase1_summary,
            "phase2_summary": phase2_summary,
            "warnings": warnings_out,
        }

    # Se o problema for de pura factibilidade reduzida (c_z == 0 e c_null == 0), z0 já é estritamente factível!
    if is_pure_feasibility:
        Z_zero = [np.zeros((b.dim, b.dim), dtype=np.float64) for b in z_blocks]
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
            "phase1_summary": phase1_summary,
            "phase2_summary": phase2_summary,
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
        d_x = N_eq @ (Q_R @ d_z) if d_z is not None else None
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
            "phase1_summary": phase1_summary,
            "phase2_summary": phase2_summary,
            "warnings": warnings_out,
        }

    z_final = p2_out["z"]
    x_final = x_eq + N_eq @ (Q_R @ z_final)
    Z_final_all = p2_out["Z_list"]
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
        "phase1_summary": phase1_summary,
        "phase2_summary": phase2_summary,
        "warnings": warnings_out,
    }
