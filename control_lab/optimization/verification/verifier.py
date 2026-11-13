"""Verificador independente e auditoria matemática em 5 dimensões (CL-DIR-001 Seção 6.3).

Regra normativa fundamental:
O verificador NUNCA confia no status reivindicado pelo solver nem executa o solver novamente;
ele reavalia o problema canônico diretamente em NumPy/SciPy a partir das matrizes de entrada
e dos certificados primal/dual/Farkas/recessivo entregues.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.core.tensors import ensure_finite_float64, tensor_to_array
from control_lab.diagnostics import (
    ControlLabError,
    NumericalInconclusiveError,
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
    ensure_json_finite,
)

from ..modeling.canonical import CanonicalSDPProblem
from ..modeling.svec import symmetry_error_rel

SOLVER_STATUSES: tuple[str, ...] = (
    "optimal",
    "optimal_inaccurate",
    "primal_infeasible",
    "dual_infeasible",
    "max_iterations",
    "numerical_error",
    "unknown",
)
_SOLVER_STATUS_SET = frozenset(SOLVER_STATUSES)

AUDIT_FEASIBILITY_LEVELS: tuple[str, ...] = (
    "strictly_feasible",
    "approximately_feasible",
    "violated",
    "inconclusive",
)

CERTIFICATE_STATUSES: tuple[str, ...] = (
    "validated_primal",
    "validated_dual",
    "validated_infeasibility",
    "validated_unboundedness",
    "not_available",
    "failed_validation",
)

CONTROLLER_VALIDITY_LEVELS: tuple[str, ...] = (
    "verified_under_assumptions",
    "violated",
    "not_applicable",
    "not_assessed",
)

DEFAULT_SDP_TOLERANCES: dict[str, float] = {
    "primal_tol": 1e-7,
    "dual_tol": 1e-7,
    "gap_tol": 1e-6,
    "psd_tol": 1e-8,
    "sym_tol": 1e-10,
    "strict_margin": 1e-4,
}


def _resolve_tolerances(tolerances: Mapping[str, Any] | None) -> dict[str, float]:
    tols = dict(DEFAULT_SDP_TOLERANCES)
    if tolerances is not None:
        if not isinstance(tolerances, Mapping):
            raise ValidationError("tolerances deve ser um dicionário Mapping.")
        for k, v in tolerances.items():
            if k not in tols:
                raise ValidationError(f"Tolerância desconhecida em verify(): {k!r}.")
            if isinstance(v, bool) or not isinstance(v, (int, float, np.integer, np.floating)):
                raise ValidationError(f"Tolerância {k!r} deve ser número real positivo.")
            fv = float(v)
            if not math.isfinite(fv) or fv <= 0.0:
                raise ValidationError(f"Tolerância {k!r} deve ser finita e > 0, recebido {fv}.")
            tols[k] = fv
    return tols


def _coerce_optional_vector(raw: Any, *, expected_len: int, name: str) -> tuple[np.ndarray | None, str | None]:
    if raw is None:
        return None, None
    try:
        if isinstance(raw, Mapping) and "shape" in raw and "data" in raw:
            arr = tensor_to_array(raw, expected_ndim=1, dtype="float64")
        else:
            arr = ensure_finite_float64(raw, name=name)
            if arr.ndim == 2 and arr.shape == (expected_len, 1):
                arr = arr.reshape((expected_len,))
            elif arr.ndim != 1:
                return None, f"{name} tem ndim={arr.ndim}, esperado 1D."
        if arr.shape != (expected_len,):
            return None, f"{name} tem shape {arr.shape}, esperado ({expected_len},)."
        if not np.all(np.isfinite(arr)):
            return None, f"{name} contém valores não finitos."
        return arr, None
    except ControlLabError as exc:
        return None, exc.message


def _coerce_optional_matrix_list(
    raw: Any,
    *,
    expected_dims: Sequence[int],
    name: str,
) -> tuple[list[np.ndarray] | None, str | None]:
    if raw is None:
        return None, None
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence):
        return None, f"{name} deve ser sequência de matrizes 2D."
    if len(raw) != len(expected_dims):
        return None, f"{name} tem {len(raw)} blocos, esperado {len(expected_dims)}."
    mats: list[np.ndarray] = []
    for idx, (item, dim) in enumerate(zip(raw, expected_dims, strict=True)):
        try:
            if isinstance(item, Mapping) and "shape" in item and "data" in item:
                arr = tensor_to_array(item, expected_ndim=2, expected_shape=(dim, dim), dtype="float64")
            else:
                arr = ensure_finite_float64(item, ndim=2, shape=(dim, dim), name=f"{name}[{idx}]")
            mats.append(arr)
        except ControlLabError as exc:
            return None, exc.message
    return mats, None


def _audit_primal_point(
    problem: CanonicalSDPProblem,
    x_vec: np.ndarray,
    tols: Mapping[str, float],
) -> dict[str, Any]:
    sym_tol = tols["sym_tol"]
    psd_tol = tols["psd_tol"]
    primal_tol = tols["primal_tol"]
    strict_margin = tols["strict_margin"]

    block_min_eigs: list[float] = []
    block_max_eigs: list[float] = []
    block_viol_abs: list[float] = []
    block_viol_rel: list[float] = []
    block_sym_errs: list[float] = []
    block_mats: list[np.ndarray] = []

    is_violated = False
    is_strict = True

    for blk in problem.blocks:
        Fb = blk.evaluate(x_vec)
        if not np.all(np.isfinite(Fb)):
            return {
                "feasibility": "violated",
                "is_violated": True,
                "is_strict": False,
                "block_min_eigs": [],
                "block_max_eigs": [],
                "block_viol_abs": [],
                "block_viol_rel": [],
                "block_sym_errs": [],
                "eq_residual_abs": 0.0,
                "eq_residual_rel": 0.0,
                "ineq_violation_abs": 0.0,
                "ineq_violation_rel": 0.0,
                "ineq_min_slack": None,
                "block_mats": [],
                "reason": "Bloco avaliado contém valores não finitos.",
            }
        sym_err = symmetry_error_rel(Fb)
        Fb_sym = 0.5 * (Fb + Fb.T)
        eigs = np.linalg.eigvalsh(Fb_sym)
        min_eig = float(np.min(eigs))
        max_eig = float(np.max(eigs))
        viol_abs = max(0.0, -min_eig)
        scale_b = 1.0 + float(np.linalg.norm(blk.F0, "fro"))
        for k, fk in blk.F_terms.items():
            scale_b += abs(float(x_vec[k])) * float(np.linalg.norm(fk, "fro"))
        viol_rel = viol_abs / scale_b

        block_min_eigs.append(min_eig)
        block_max_eigs.append(max_eig)
        block_viol_abs.append(viol_abs)
        block_viol_rel.append(viol_rel)
        block_sym_errs.append(sym_err)
        block_mats.append(Fb_sym)

        if sym_err > sym_tol or viol_rel > psd_tol:
            is_violated = True
        if min_eig <= strict_margin:
            is_strict = False

    eq_abs = 0.0
    eq_rel = 0.0
    if problem.n_eq > 0:
        eq_res = problem.evaluate_equalities(x_vec)
        eq_abs = float(np.max(np.abs(eq_res)))
        eq_scale = 1.0 + float(np.linalg.norm(problem.d)) + float(np.linalg.norm(problem.E, "fro") * np.linalg.norm(x_vec))
        eq_rel = float(np.linalg.norm(eq_res) / eq_scale)
        if eq_rel > primal_tol:
            is_violated = True

    ineq_abs = 0.0
    ineq_rel = 0.0
    ineq_min_slack: float | None = None
    if problem.n_ineq > 0:
        ineq_res = problem.evaluate_inequalities(x_vec)
        ineq_viol = np.maximum(0.0, ineq_res)
        ineq_abs = float(np.max(ineq_viol))
        ineq_scale = 1.0 + float(np.linalg.norm(problem.h)) + float(np.linalg.norm(problem.H, "fro") * np.linalg.norm(x_vec))
        ineq_rel = float(np.linalg.norm(ineq_viol) / ineq_scale)
        ineq_min_slack = float(np.min(-ineq_res))
        if ineq_rel > primal_tol:
            is_violated = True
        if ineq_min_slack <= strict_margin:
            is_strict = False

    if is_violated:
        feasibility = "violated"
        is_strict = False
    elif is_strict:
        feasibility = "strictly_feasible"
    else:
        feasibility = "approximately_feasible"

    return {
        "feasibility": feasibility,
        "is_violated": is_violated,
        "is_strict": is_strict,
        "block_min_eigs": block_min_eigs,
        "block_max_eigs": block_max_eigs,
        "block_viol_abs": block_viol_abs,
        "block_viol_rel": block_viol_rel,
        "block_sym_errs": block_sym_errs,
        "eq_residual_abs": eq_abs,
        "eq_residual_rel": eq_rel,
        "ineq_violation_abs": ineq_abs,
        "ineq_violation_rel": ineq_rel,
        "ineq_min_slack": ineq_min_slack,
        "block_mats": block_mats,
        "reason": None,
    }


def _audit_dual_optimality(
    problem: CanonicalSDPProblem,
    x_vec: np.ndarray,
    block_mats: Sequence[np.ndarray],
    Z_list: Sequence[np.ndarray],
    nu: np.ndarray | None,
    lam: np.ndarray | None,
    primal_obj: float,
    tols: Mapping[str, float],
) -> dict[str, Any]:
    sym_tol = tols["sym_tol"]
    dual_tol = tols["dual_tol"]
    gap_tol = tols["gap_tol"]

    def _incomplete_dual(reason: str) -> dict[str, Any]:
        return {
            "valid": False,
            "dual_objective": None,
            "dual_block_min_eigs": [],
            "dual_block_sym_errs": [],
            "dual_stationarity_abs": None,
            "dual_stationarity_rel": None,
            "duality_gap_abs": None,
            "duality_gap_rel": None,
            "complementarity_abs": None,
            "complementarity_rel": None,
            "reason": reason,
        }

    if problem.n_eq > 0 and nu is None:
        return _incomplete_dual("Multiplicador dual de igualdade (dual_eq) ausente.")
    if problem.n_ineq > 0 and lam is None:
        return _incomplete_dual("Multiplicador dual de desigualdade (dual_ineq) ausente.")

    Z_sym_list: list[np.ndarray] = []
    dual_block_min_eigs: list[float] = []
    dual_block_sym_errs: list[float] = []
    dual_valid = True
    reasons: list[str] = []

    for b_idx, Z_raw in enumerate(Z_list):
        sym_e = symmetry_error_rel(Z_raw)
        dual_block_sym_errs.append(sym_e)
        if sym_e > sym_tol:
            dual_valid = False
            reasons.append(f"dual_Z[{b_idx}] assimétrica (erro={sym_e:.3e}).")
        Z_sym = 0.5 * (Z_raw + Z_raw.T)
        Z_sym_list.append(Z_sym)
        min_ez = float(np.min(np.linalg.eigvalsh(Z_sym)))
        dual_block_min_eigs.append(min_ez)
        z_scale = 1.0 + float(np.linalg.norm(Z_sym, "fro"))
        if min_ez < -dual_tol * z_scale:
            dual_valid = False
            reasons.append(f"dual_Z[{b_idx}] não é PSD (min_eig={min_ez:.3e}).")

    if lam is not None and problem.n_ineq > 0:
        lam_min = float(np.min(lam))
        if lam_min < -dual_tol * (1.0 + float(np.linalg.norm(lam))):
            dual_valid = False
            reasons.append(f"Multiplicador dual_ineq negativo (min={lam_min:.3e}).")

    # Equação estacionária dual: sum_b <F_{b,k}, Z_b> - (E^T nu)_k - (H^T lam)_k == c_k
    adj = np.zeros((problem.n_vars,), dtype=np.float64)
    term_scale = 1.0 + float(np.linalg.norm(problem.c))
    for blk, Z_b in zip(problem.blocks, Z_sym_list, strict=True):
        z_norm = float(np.linalg.norm(Z_b, "fro"))
        for k, fk in blk.F_terms.items():
            adj[k] += float(np.sum(fk * Z_b))
            term_scale += float(np.linalg.norm(fk, "fro")) * z_norm
    if nu is not None and problem.n_eq > 0:
        adj = adj - (problem.E.T @ nu)
        term_scale += float(np.linalg.norm(problem.E, "fro") * np.linalg.norm(nu))
    if lam is not None and problem.n_ineq > 0:
        adj = adj - (problem.H.T @ lam)
        term_scale += float(np.linalg.norm(problem.H, "fro") * np.linalg.norm(lam))

    r_dual = adj - problem.c
    r_dual_abs = float(np.linalg.norm(r_dual))
    r_dual_rel = r_dual_abs / term_scale
    if r_dual_rel > dual_tol:
        dual_valid = False
        reasons.append(f"Estacionariedade dual violada (rel={r_dual_rel:.3e} > {dual_tol:.1e}).")

    # Objetivo dual: c0 - sum_b <F_{b,0}, Z_b> - d^T nu - h^T lam
    dual_obj = problem.c0
    for blk, Z_b in zip(problem.blocks, Z_sym_list, strict=True):
        dual_obj -= float(np.sum(blk.F0 * Z_b))
    if nu is not None and problem.n_eq > 0:
        dual_obj -= float(np.dot(problem.d, nu))
    if lam is not None and problem.n_ineq > 0:
        dual_obj -= float(np.dot(problem.h, lam))

    gap_abs = abs(primal_obj - dual_obj)
    gap_rel = gap_abs / (1.0 + abs(primal_obj) + abs(dual_obj))
    if gap_rel > gap_tol:
        dual_valid = False
        reasons.append(f"Gap primal-dual elevado (rel={gap_rel:.3e} > {gap_tol:.1e}).")

    # Complementaridade: sum_b |<F_b(x), Z_b>| + |lam^T (h - H x)|
    comp_abs = 0.0
    comp_scale = 1.0
    for Fb, Z_b in zip(block_mats, Z_sym_list, strict=True):
        comp_abs += abs(float(np.sum(Fb * Z_b)))
        comp_scale += float(np.linalg.norm(Fb, "fro") * np.linalg.norm(Z_b, "fro"))
    if lam is not None and problem.n_ineq > 0:
        slack = problem.h - (problem.H @ x_vec)
        comp_abs += abs(float(np.dot(lam, slack)))
        comp_scale += float(np.linalg.norm(lam) * np.linalg.norm(slack))
    comp_rel = comp_abs / comp_scale
    if comp_rel > gap_tol:
        dual_valid = False
        reasons.append(f"Folga complementar violada (rel={comp_rel:.3e} > {gap_tol:.1e}).")

    return {
        "valid": dual_valid,
        "dual_objective": float(dual_obj),
        "dual_block_min_eigs": dual_block_min_eigs,
        "dual_block_sym_errs": dual_block_sym_errs,
        "dual_stationarity_abs": r_dual_abs,
        "dual_stationarity_rel": r_dual_rel,
        "duality_gap_abs": gap_abs,
        "duality_gap_rel": gap_rel,
        "complementarity_abs": comp_abs,
        "complementarity_rel": comp_rel,
        "reason": "; ".join(reasons) if reasons else None,
    }


def _audit_farkas_infeasibility(
    problem: CanonicalSDPProblem,
    Z_list: Sequence[np.ndarray],
    nu: np.ndarray | None,
    lam: np.ndarray | None,
    tols: Mapping[str, float],
) -> dict[str, Any]:
    sym_tol = tols["sym_tol"]
    dual_tol = tols["dual_tol"]

    if problem.n_eq > 0 and nu is None:
        return {"valid": False, "reason": "Certificado Farkas de igualdade (farkas_eq) ausente."}
    if problem.n_ineq > 0 and lam is None:
        return {"valid": False, "reason": "Certificado Farkas de desigualdade (farkas_ineq) ausente."}

    Z_sym_list: list[np.ndarray] = []
    cert_norm = 0.0
    reasons: list[str] = []
    valid = True

    for b_idx, Z_raw in enumerate(Z_list):
        sym_e = symmetry_error_rel(Z_raw)
        if sym_e > sym_tol:
            valid = False
            reasons.append(f"farkas_Z[{b_idx}] assimétrica (erro={sym_e:.3e}).")
        Z_sym = 0.5 * (Z_raw + Z_raw.T)
        Z_sym_list.append(Z_sym)
        znorm = float(np.linalg.norm(Z_sym, "fro"))
        cert_norm += znorm
        min_ez = float(np.min(np.linalg.eigvalsh(Z_sym)))
        if min_ez < -dual_tol * (1.0 + znorm):
            valid = False
            reasons.append(f"farkas_Z[{b_idx}] não é PSD (min_eig={min_ez:.3e}).")

    if nu is not None and problem.n_eq > 0:
        cert_norm += float(np.linalg.norm(nu))
    if lam is not None and problem.n_ineq > 0:
        lnorm = float(np.linalg.norm(lam))
        cert_norm += lnorm
        if float(np.min(lam)) < -dual_tol * (1.0 + lnorm):
            valid = False
            reasons.append("farkas_ineq contém componente negativa.")

    if cert_norm <= 1e-12:
        return {
            "valid": False,
            "farkas_adjoint_rel": None,
            "farkas_value": None,
            "reason": "Certificado Farkas identicamente nulo (norma <= 1e-12).",
        }

    # Equação adjunta: sum_b <F_{b,k}, Z_b> - (E^T nu)_k - (H^T lam)_k == 0
    adj = np.zeros((problem.n_vars,), dtype=np.float64)
    adj_scale = 1e-12
    for blk, Z_b in zip(problem.blocks, Z_sym_list, strict=True):
        znorm = float(np.linalg.norm(Z_b, "fro"))
        for k, fk in blk.F_terms.items():
            adj[k] += float(np.sum(fk * Z_b))
            adj_scale += float(np.linalg.norm(fk, "fro")) * znorm
    if nu is not None and problem.n_eq > 0:
        adj = adj - (problem.E.T @ nu)
        adj_scale += float(np.linalg.norm(problem.E, "fro") * np.linalg.norm(nu))
    if lam is not None and problem.n_ineq > 0:
        adj = adj - (problem.H.T @ lam)
        adj_scale += float(np.linalg.norm(problem.H, "fro") * np.linalg.norm(lam))

    adj_abs = float(np.linalg.norm(adj))
    adj_rel = adj_abs / adj_scale
    if adj_rel > dual_tol:
        valid = False
        reasons.append(f"Condição adjunta de Farkas violada (rel={adj_rel:.3e} > {dual_tol:.1e}).")

    # Contradição estrita: sum_b <F_{b,0}, Z_b> + d^T nu + h^T lam < 0
    farkas_val = 0.0
    farkas_scale = 0.0
    for blk, Z_b in zip(problem.blocks, Z_sym_list, strict=True):
        farkas_val += float(np.sum(blk.F0 * Z_b))
        farkas_scale += float(np.linalg.norm(blk.F0, "fro") * np.linalg.norm(Z_b, "fro"))
    if nu is not None and problem.n_eq > 0:
        farkas_val += float(np.dot(problem.d, nu))
        farkas_scale += float(np.linalg.norm(problem.d) * np.linalg.norm(nu))
    if lam is not None and problem.n_ineq > 0:
        farkas_val += float(np.dot(problem.h, lam))
        farkas_scale += float(np.linalg.norm(problem.h) * np.linalg.norm(lam))

    farkas_denom = max(1.0, farkas_scale)
    if farkas_val >= -1e-9 * max(cert_norm, 1e-3) or (farkas_val / farkas_denom) >= -1e-9:
        valid = False
        reasons.append(f"Valor de Farkas não é estritamente negativo: {farkas_val:.3e}.")

    return {
        "valid": valid,
        "farkas_adjoint_abs": adj_abs,
        "farkas_adjoint_rel": adj_rel,
        "farkas_value": float(farkas_val),
        "reason": "; ".join(reasons) if reasons else None,
    }


def _audit_unboundedness(
    problem: CanonicalSDPProblem,
    d_vec: np.ndarray,
    x0_vec: np.ndarray | None,
    tols: Mapping[str, float],
) -> dict[str, Any]:
    psd_tol = tols["psd_tol"]
    primal_tol = tols["primal_tol"]

    d_norm = float(np.linalg.norm(d_vec))
    if d_norm <= 1e-12:
        return {"valid": False, "x0_audit": None, "reason": "Direção recessiva nula."}

    valid_ray = True
    reasons: list[str] = []

    for b_idx, blk in enumerate(problem.blocks):
        F_lin = blk.evaluate_linear(d_vec)
        min_eig = float(np.min(np.linalg.eigvalsh(F_lin)))
        scale_b = 1.0
        for k, fk in blk.F_terms.items():
            scale_b += abs(float(d_vec[k])) * float(np.linalg.norm(fk, "fro"))
        if min_eig < -psd_tol * scale_b:
            valid_ray = False
            reasons.append(f"Bloco {b_idx} não cresce no cone recessivo (min_eig={min_eig:.3e}).")

    if problem.n_eq > 0:
        ed = problem.E @ d_vec
        ed_rel = float(np.linalg.norm(ed) / (1.0 + np.linalg.norm(problem.E, "fro") * d_norm))
        if ed_rel > primal_tol:
            valid_ray = False
            reasons.append(f"Direção recessiva viola E d == 0 (rel={ed_rel:.3e}).")

    if problem.n_ineq > 0:
        hd = problem.H @ d_vec
        hd_viol = float(np.max(np.maximum(0.0, hd)))
        hd_scale = 1.0 + float(np.linalg.norm(problem.H, "fro") * d_norm)
        if (hd_viol / hd_scale) > primal_tol:
            valid_ray = False
            reasons.append(f"Direção recessiva viola H d <= 0 (viol={hd_viol:.3e}).")

    cd = float(np.dot(problem.c, d_vec))
    c_scale = max(1.0, float(np.linalg.norm(problem.c)) * d_norm)
    if cd >= -1e-9 * c_scale:
        valid_ray = False
        reasons.append(f"Direção recessiva não reduz estritamente o objetivo (c^T d = {cd:.3e}).")

    x0_audit = _audit_primal_point(problem, x0_vec, tols) if x0_vec is not None else None

    return {
        "valid_ray": valid_ray,
        "c_dot_d": cd,
        "x0_audit": x0_audit,
        "reason": "; ".join(reasons) if reasons else None,
    }


def _compute_conditioning(
    problem: CanonicalSDPProblem,
    x_vec: np.ndarray | None,
    audit_feasibility: str,
    solver_status: str,
    certificate_status: str,
    primal_audit: Mapping[str, Any] | None,
    tols: Mapping[str, float],
) -> dict[str, Any]:
    scale_ratio = problem.estimate_data_scale_ratio()
    cond_val: float | None = scale_ratio if math.isfinite(scale_ratio) else None
    x_norm = float(np.linalg.norm(x_vec)) if x_vec is not None else 0.0

    # Verificar condicionamento de matrizes simétricas de Lyapunov (ex: Q) se houver no variable_map
    if x_vec is not None:
        for vname, vmeta in problem.variable_map.items():
            if vmeta.get("symmetric") and int(vmeta["shape"][0]) >= 2:
                try:
                    M = problem.reconstruct_variable(vname, x_vec)
                    svals = np.linalg.svd(M, compute_uv=False)
                    s_max = float(svals[0])
                    s_min = float(svals[-1])
                    if s_min <= 1e-15 * max(1.0, s_max):
                        cond_val = None
                        break
                    c_m = s_max / s_min
                    if math.isfinite(c_m):
                        cond_val = max(cond_val or 1.0, c_m)
                    else:
                        cond_val = None
                        break
                except Exception:
                    pass

    min_eig_overall = float("inf")
    if primal_audit is not None and primal_audit.get("block_min_eigs"):
        min_eig_overall = min(float(v) for v in primal_audit["block_min_eigs"])

    near_boundary = bool(
        audit_feasibility == "approximately_feasible"
        or (math.isfinite(min_eig_overall) and min_eig_overall <= tols["strict_margin"])
    )
    scaling_warning = bool(
        scale_ratio > 1e6
        or x_norm > 1e6
        or (cond_val is not None and cond_val > 1e8)
    )
    loss_of_significance = bool(
        solver_status in ("optimal_inaccurate", "numerical_error")
        or cond_val is None
        or (cond_val > 1e10)
        or certificate_status == "failed_validation"
    )
    return {
        "condition_number": cond_val,
        "scaling_warning": scaling_warning,
        "near_boundary": near_boundary,
        "loss_of_significance": loss_of_significance,
        "data_scale_ratio": scale_ratio,
    }


def verify(
    problem: CanonicalSDPProblem,
    solution: Result | Mapping[str, Any] | None,
    claimed_status: str | None = None,
    *,
    tolerances: Mapping[str, Any] | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Audita independentemente uma solução ou certificado de CanonicalSDPProblem (5 dimensões da Tabela 6.3)."""
    prov: Provenance = build_provenance("optimization.verification.verify")
    try:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(
                f"verify() requer CanonicalSDPProblem, recebido {type(problem).__name__}."
            )
        tols = _resolve_tolerances(tolerances)

        if solution is None:
            sol_dict: dict[str, Any] = {}
        elif isinstance(solution, Result):
            if solution.data is None:
                sol_dict = {}
            else:
                sol_dict = dict(solution.data)
        elif isinstance(solution, Mapping):
            sol_dict = dict(solution)
        else:
            raise ValidationError(
                f"solution deve ser Result, Mapping ou None, recebido {type(solution).__name__}."
            )

        raw_status = claimed_status if claimed_status is not None else sol_dict.get("solver_status", sol_dict.get("status", "unknown"))
        if not isinstance(raw_status, str) or raw_status not in _SOLVER_STATUS_SET:
            raise ValidationError(
                message=f"claimed_status inválido: {raw_status!r}. Esperado um de {SOLVER_STATUSES}.",
                parameters={"claimed_status": raw_status, "allowed": list(SOLVER_STATUSES)},
            )
        solver_status = raw_status

        warnings_out: list[WarningItem] = []
        controller_validity = "not_assessed" if problem.recovery_plan else "not_applicable"

        block_dims = [blk.dim for blk in problem.blocks]
        x_vec, x_err = _coerce_optional_vector(sol_dict.get("x"), expected_len=problem.n_vars, name="x")
        Z_list, z_err = _coerce_optional_matrix_list(sol_dict.get("dual_Z"), expected_dims=block_dims, name="dual_Z")
        nu_vec, nu_err = _coerce_optional_vector(sol_dict.get("dual_eq"), expected_len=problem.n_eq, name="dual_eq")
        lam_vec, lam_err = _coerce_optional_vector(sol_dict.get("dual_ineq"), expected_len=problem.n_ineq, name="dual_ineq")

        farkas_Z_raw = sol_dict.get("farkas_Z")
        farkas_eq_raw = sol_dict.get("farkas_eq")
        farkas_ineq_raw = sol_dict.get("farkas_ineq")
        has_any_dual_fallback = (
            sol_dict.get("dual_Z") is not None
            or sol_dict.get("dual_eq") is not None
            or sol_dict.get("dual_ineq") is not None
        )
        if (
            solver_status == "primal_infeasible"
            and farkas_Z_raw is None
            and farkas_eq_raw is None
            and farkas_ineq_raw is None
            and has_any_dual_fallback
        ):
            farkas_Z_raw = sol_dict.get("dual_Z")
            farkas_eq_raw = sol_dict.get("dual_eq")
            farkas_ineq_raw = sol_dict.get("dual_ineq")

        farkas_Z, fz_err = _coerce_optional_matrix_list(farkas_Z_raw, expected_dims=block_dims, name="farkas_Z")
        farkas_eq, fe_err = _coerce_optional_vector(farkas_eq_raw, expected_len=problem.n_eq, name="farkas_eq")
        farkas_ineq, fi_err = _coerce_optional_vector(farkas_ineq_raw, expected_len=problem.n_ineq, name="farkas_ineq")

        ray_vec, ray_err = _coerce_optional_vector(
            sol_dict.get("recession_direction"), expected_len=problem.n_vars, name="recession_direction"
        )
        x0_vec, x0_err = _coerce_optional_vector(
            sol_dict.get("feasible_x0"), expected_len=problem.n_vars, name="feasible_x0"
        )

        residuals: dict[str, Any] = {}
        primal_audit: dict[str, Any] | None = None
        primal_obj: float | None = None
        dual_obj: float | None = None

        if solver_status == "primal_infeasible":
            if fz_err or fe_err or fi_err:
                audit_feasibility = "inconclusive"
                certificate_status = "failed_validation"
                warnings_out.append(
                    WarningItem(
                        code="INVALID_FARKAS_CERTIFICATE_FORMAT",
                        message=fz_err or fe_err or fi_err or "Formato inválido de certificado Farkas.",
                    )
                )
            elif farkas_Z is None and farkas_eq is None and farkas_ineq is None:
                audit_feasibility = "inconclusive"
                certificate_status = "not_available"
                warnings_out.append(
                    WarningItem(
                        code="MISSING_INFEASIBILITY_CERTIFICATE",
                        message="Solver indicou primal_infeasible sem certificado dual de Farkas; status rebaixado para inconclusive.",
                    )
                )
            else:
                if len(problem.blocks) > 0 and farkas_Z is None:
                    audit_feasibility = "inconclusive"
                    certificate_status = "failed_validation"
                    warnings_out.append(
                        WarningItem(
                            code="INCOMPLETE_FARKAS_CERTIFICATE",
                            message="Certificado Farkas omitiu blocos PSD (farkas_Z).",
                        )
                    )
                else:
                    f_res = _audit_farkas_infeasibility(problem, farkas_Z or [], farkas_eq, farkas_ineq, tols)
                    residuals.update(
                        {
                            "farkas_adjoint_abs": f_res.get("farkas_adjoint_abs"),
                            "farkas_adjoint_rel": f_res.get("farkas_adjoint_rel"),
                            "farkas_value": f_res.get("farkas_value"),
                        }
                    )
                    if f_res["valid"]:
                        audit_feasibility = "violated"
                        certificate_status = "validated_infeasibility"
                    else:
                        audit_feasibility = "inconclusive"
                        certificate_status = "failed_validation"
                        warnings_out.append(
                            WarningItem(
                                code="FARKAS_CERTIFICATE_FAILED",
                                message=str(f_res.get("reason") or "Certificado de Farkas inválido."),
                            )
                        )

        elif solver_status == "dual_infeasible":
            if ray_err or x0_err:
                audit_feasibility = "inconclusive"
                certificate_status = "failed_validation"
                warnings_out.append(
                    WarningItem(
                        code="INVALID_UNBOUNDED_CERTIFICATE_FORMAT",
                        message=ray_err or x0_err or "Formato inválido de certificado de ilimitado.",
                    )
                )
            elif ray_vec is None:
                audit_feasibility = "inconclusive"
                certificate_status = "not_available"
                warnings_out.append(
                    WarningItem(
                        code="MISSING_RECESSION_DIRECTION",
                        message="Solver indicou dual_infeasible sem direção recessiva auditável; status marcado como inconclusive.",
                    )
                )
            else:
                u_res = _audit_unboundedness(problem, ray_vec, x0_vec, tols)
                residuals["c_dot_d"] = u_res.get("c_dot_d")
                x0_audit = u_res.get("x0_audit")
                if x0_audit is not None:
                    primal_audit = x0_audit
                    residuals.update(
                        {
                            "primal_block_min_eigs": x0_audit["block_min_eigs"],
                            "primal_block_violations_abs": x0_audit["block_viol_abs"],
                            "primal_block_violations_rel": x0_audit["block_viol_rel"],
                            "primal_block_symmetry_errors": x0_audit["block_sym_errs"],
                            "eq_residual_abs": x0_audit["eq_residual_abs"],
                            "eq_residual_rel": x0_audit["eq_residual_rel"],
                            "ineq_violation_abs": x0_audit["ineq_violation_abs"],
                            "ineq_violation_rel": x0_audit["ineq_violation_rel"],
                        }
                    )
                if not u_res["valid_ray"]:
                    audit_feasibility = x0_audit["feasibility"] if x0_audit is not None else "inconclusive"
                    certificate_status = "failed_validation"
                    warnings_out.append(
                        WarningItem(
                            code="RECESSION_DIRECTION_INVALID",
                            message=str(u_res.get("reason") or "Direção recessiva inválida."),
                        )
                    )
                elif x0_audit is None:
                    audit_feasibility = "inconclusive"
                    certificate_status = "not_available"
                    warnings_out.append(
                        WarningItem(
                            code="MISSING_FEASIBLE_X0_FOR_UNBOUNDEDNESS",
                            message="Direção recessiva válida, mas falta ponto factível x0 para descartar infactibilidade primal simultânea.",
                        )
                    )
                elif x0_audit["is_violated"]:
                    audit_feasibility = "violated"
                    certificate_status = "failed_validation"
                    warnings_out.append(
                        WarningItem(
                            code="FEASIBLE_X0_VIOLATED",
                            message="Ponto x0 associado à direção recessiva viola restrições do problema.",
                        )
                    )
                else:
                    audit_feasibility = x0_audit["feasibility"]
                    certificate_status = "validated_unboundedness"

        else:
            # Casos: optimal, optimal_inaccurate, max_iterations, numerical_error, unknown
            if x_err is not None:
                audit_feasibility = "inconclusive"
                certificate_status = "failed_validation"
                warnings_out.append(WarningItem(code="INVALID_PRIMAL_VECTOR", message=x_err))
            elif x_vec is None:
                audit_feasibility = "inconclusive"
                certificate_status = "failed_validation" if solver_status in ("optimal", "optimal_inaccurate") else "not_available"
                warnings_out.append(
                    WarningItem(
                        code="MISSING_PRIMAL_SOLUTION",
                        message=f"Solução primal x ausente para solver_status={solver_status!r}.",
                    )
                )
            else:
                primal_audit = _audit_primal_point(problem, x_vec, tols)
                primal_obj = problem.evaluate_objective(x_vec)
                audit_feasibility = primal_audit["feasibility"]
                residuals.update(
                    {
                        "primal_block_min_eigs": primal_audit["block_min_eigs"],
                        "primal_block_violations_abs": primal_audit["block_viol_abs"],
                        "primal_block_violations_rel": primal_audit["block_viol_rel"],
                        "primal_block_symmetry_errors": primal_audit["block_sym_errs"],
                        "eq_residual_abs": primal_audit["eq_residual_abs"],
                        "eq_residual_rel": primal_audit["eq_residual_rel"],
                        "ineq_violation_abs": primal_audit["ineq_violation_abs"],
                        "ineq_violation_rel": primal_audit["ineq_violation_rel"],
                    }
                )

                # Verificar consistência do objetivo reivindicado se presente
                claimed_obj = sol_dict.get("objective", sol_dict.get("obj_val"))
                obj_mismatch = False
                if claimed_obj is not None and not isinstance(claimed_obj, bool):
                    try:
                        f_claimed = float(claimed_obj)
                        if not math.isfinite(f_claimed):
                            obj_mismatch = True
                        else:
                            obj_diff = abs(f_claimed - primal_obj)
                            if obj_diff / (1.0 + abs(primal_obj) + abs(f_claimed)) > tols["gap_tol"]:
                                obj_mismatch = True
                                residuals["claimed_objective_mismatch"] = obj_diff
                    except (TypeError, ValueError):
                        obj_mismatch = True

                if primal_audit["is_violated"] or obj_mismatch:
                    certificate_status = "failed_validation"
                    warnings_out.append(
                        WarningItem(
                            code="PRIMAL_AUDIT_FAILED",
                            message=(
                                "Solução primal viola restrições ou diverge do objetivo canônico avaliado."
                                if obj_mismatch
                                else "Solução primal viola restrições do problema canônico."
                            ),
                        )
                    )
                else:
                    # Primal válido; checar dual caso fornecido
                    has_any_dual = any(v is not None for v in (Z_list, nu_vec, lam_vec))
                    if z_err or nu_err or lam_err:
                        certificate_status = "failed_validation"
                        warnings_out.append(
                            WarningItem(
                                code="INVALID_DUAL_FORMAT",
                                message=z_err or nu_err or lam_err or "Formato inválido de variável dual.",
                            )
                        )
                    elif not has_any_dual:
                        certificate_status = "validated_primal"
                        if solver_status == "optimal":
                            warnings_out.append(
                                WarningItem(
                                    code="DUAL_NOT_AVAILABLE_FOR_OPTIMAL",
                                    message="Variáveis duais ausentes; factibilidade primal auditada, porém otimalidade dual não certificada.",
                                )
                            )
                    elif len(problem.blocks) > 0 and Z_list is None:
                        certificate_status = "failed_validation"
                        warnings_out.append(
                            WarningItem(
                                code="MISSING_DUAL_Z_BLOCKS",
                                message="Certificado dual incompleto: dual_Z ausente para blocos PSD.",
                            )
                        )
                    else:
                        d_res = _audit_dual_optimality(
                            problem,
                            x_vec,
                            primal_audit["block_mats"],
                            Z_list or [],
                            nu_vec,
                            lam_vec,
                            primal_obj,
                            tols,
                        )
                        dual_obj = d_res.get("dual_objective")
                        residuals.update(
                            {
                                "dual_block_min_eigs": d_res.get("dual_block_min_eigs", []),
                                "dual_block_sym_errs": d_res.get("dual_block_sym_errs", []),
                                "dual_stationarity_abs": d_res.get("dual_stationarity_abs"),
                                "dual_stationarity_rel": d_res.get("dual_stationarity_rel"),
                                "duality_gap_abs": d_res.get("duality_gap_abs"),
                                "duality_gap_rel": d_res.get("duality_gap_rel"),
                                "complementarity_abs": d_res.get("complementarity_abs"),
                                "complementarity_rel": d_res.get("complementarity_rel"),
                            }
                        )
                        if d_res["valid"]:
                            certificate_status = "validated_dual"
                        else:
                            certificate_status = "failed_validation"
                            warnings_out.append(
                                WarningItem(
                                    code="DUAL_AUDIT_FAILED",
                                    message=str(d_res.get("reason") or "Auditoria dual/gap falhou."),
                                )
                            )

        if solver_status == "optimal_inaccurate":
            warnings_out.append(
                WarningItem(
                    code="SOLVER_OPTIMAL_INACCURATE",
                    message="Solver reportou optimal_inaccurate; precisão reduzida preservada sem promoção para optimal.",
                )
            )

        conditioning = _compute_conditioning(
            problem,
            x_vec if x_vec is not None else x0_vec,
            audit_feasibility,
            solver_status,
            certificate_status,
            primal_audit,
            tols,
        )
        if conditioning["scaling_warning"]:
            warnings_out.append(
                WarningItem(
                    code="SDP_SCALING_WARNING",
                    message="Problema/solução apresenta escala numérica elevada; recomenda-se reescalonamento.",
                    details={"data_scale_ratio": conditioning["data_scale_ratio"]},
                )
            )

        # Determinar status operacional do envelope Result (Seção 4.4)
        if certificate_status in ("not_available", "failed_validation") or audit_feasibility == "inconclusive":
            result_status = "inconclusive"
        elif solver_status == "optimal_inaccurate" or conditioning["loss_of_significance"] or (
            solver_status == "optimal" and certificate_status == "validated_primal"
        ):
            result_status = "warning"
        elif conditioning["scaling_warning"]:
            result_status = "warning"
        else:
            result_status = "success"

        data: dict[str, Any] = {
            "solver_status": solver_status,
            "audit_feasibility": audit_feasibility,
            "certificate_status": certificate_status,
            "conditioning": conditioning,
            "controller_validity": controller_validity,
            "residuals": residuals,
            "primal_objective": primal_obj,
            "dual_objective": dual_obj,
        }
        if x_vec is not None:
            data["variables"] = problem.reconstruct_variables(x_vec)

        prov_ok = build_provenance("optimization.verification.verify", tolerances=tols)
        return Result(
            status=result_status,
            data=ensure_json_finite(data),
            assumptions={
                "independent_audit": True,
                "cone_order_non_strict": True,
                "claimed_status": solver_status,
            },
            diagnostics=ensure_json_finite(
                {
                    "solver_status": solver_status,
                    "audit_feasibility": audit_feasibility,
                    "certificate_status": certificate_status,
                    "conditioning": conditioning,
                    "controller_validity": controller_validity,
                    "residuals": residuals,
                }
            ),
            provenance=prov_ok,
            warnings=tuple(warnings_out),
            error=None,
        )

    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=prov,
            warnings=(),
            error=exc.to_typed_error(),
        )
    except Exception as exc:
        if raise_on_error:
            raise NumericalInconclusiveError(f"Erro interno durante verificação SDP: {exc}") from exc
        err = NumericalInconclusiveError(f"Erro interno durante verificação SDP: {exc}")
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=prov,
            warnings=(),
            error=err.to_typed_error(),
        )
