"""Bateria de validação didática Níveis A–D para o solver primal-dual experimental (CL-DIR-001 Seção 6.5 / R-13)."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import scipy.linalg

from control_lab.core import StateFeedbackController, StateSpace, TSStateSpace, get_closed_loop_matrix
from control_lab.diagnostics import Provenance, Result, WarningItem, build_provenance, ensure_json_finite
from control_lab.optimization import (
    bmat,
    compile,
    continuous_stabilization_lmi,
    hinf_brl_lmi,
    recover_controller,
    regional_pole_placement_lmi,
    sdpvar,
    trace,
    ts_pdc_stabilization_lmi,
)

from .solver import solve_sdp_educational


def _extract_case_summary(
    name: str,
    level: str,
    res: Result,
    *,
    passed: bool,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    d = res.data or {}
    cond = d.get("conditioning") or {}
    return {
        "case": name,
        "level": level,
        "passed": bool(passed),
        "result_status": res.status,
        "solver_status": d.get("solver_status"),
        "audit_feasibility": d.get("audit_feasibility"),
        "certificate_status": d.get("certificate_status"),
        "controller_validity": d.get("controller_validity"),
        "iterations": d.get("iterations"),
        "objective": d.get("objective"),
        "scaling_warning": cond.get("scaling_warning"),
        "near_boundary": cond.get("near_boundary"),
        "detail": dict(detail or {}),
    }


def run_educational_levels_a_to_d_suite(
    options: Mapping[str, Any] | None = None,
) -> Result:
    """Executa a bateria escalonada Níveis A–D da Seção 6.5 e devolve `Result` experimental auditado."""
    prov: Provenance = build_provenance(
        "experimental.sdp_educational.levels_a_to_d_suite",
        maturity="experimental",
    )
    cases_summary: list[dict[str, Any]] = []
    x = sdpvar((1, 1), name="x")

    # ---------------- Nível A: LP / escalares ----------------
    # A1: caixa 1 <= x <= 2, min x -> x* = 1
    p_a_box = compile(x, [x >= 1.0, 2.0 - x >= 0.0], name="levelA_box")
    r_a_box = solve_sdp_educational(p_a_box, options=options)
    ok_a_box = (
        r_a_box.data is not None
        and r_a_box.data["solver_status"] == "optimal"
        and r_a_box.data["certificate_status"] == "validated_dual"
        and abs(float(r_a_box.data["objective"]) - 1.0) <= 1e-6
    )
    cases_summary.append(_extract_case_summary("A_box", "A", r_a_box, passed=ok_a_box))

    # A2: infactível forte x >= 2, x <= 1
    p_a2 = compile(x, [x >= 2.0, 1.0 - x >= 0.0], name="T-SDP-A2")
    r_a2 = solve_sdp_educational(p_a2, options=options)
    ok_a2 = (
        r_a2.data is not None
        and r_a2.data["solver_status"] == "primal_infeasible"
        and r_a2.data["audit_feasibility"] == "violated"
        and r_a2.data["certificate_status"] == "validated_infeasibility"
    )
    cases_summary.append(_extract_case_summary("T-SDP-A2", "A", r_a2, passed=ok_a2))

    # A3: ilimitado min x, x <= 2
    p_a3 = compile(x, [2.0 - x >= 0.0], name="T-SDP-A3")
    r_a3 = solve_sdp_educational(p_a3, options=options)
    ok_a3 = (
        r_a3.data is not None
        and r_a3.data["solver_status"] == "dual_infeasible"
        and r_a3.data["certificate_status"] == "validated_unboundedness"
    )
    cases_summary.append(_extract_case_summary("T-SDP-A3", "A", r_a3, passed=ok_a3))

    # ---------------- Nível B: PSD analítico ----------------
    # B1: [[1, x], [x, 1]] >= 0, min x -> x* = -1
    p_b1 = compile(x, [bmat([[np.ones((1, 1)), x], [x, np.ones((1, 1))]]) >= np.zeros((2, 2))], name="T-SDP-B1")
    r_b1 = solve_sdp_educational(p_b1, options=options)
    ok_b1 = (
        r_b1.data is not None
        and r_b1.data["solver_status"] == "optimal"
        and r_b1.data["certificate_status"] == "validated_dual"
        and abs(float(r_b1.data["objective"]) + 1.0) <= 1e-6
    )
    cases_summary.append(_extract_case_summary("T-SDP-B1", "B", r_b1, passed=ok_b1))

    # B_singular: [[0, 0], [0, x]] >= 0 (sem interior de Slater -> jamais declara optimal/strict sem prova)
    p_bsing = compile(x, [bmat([[np.zeros((1, 1)), np.zeros((1, 1))], [np.zeros((1, 1)), x]]) >= np.zeros((2, 2))], name="B_singular")
    r_bsing = solve_sdp_educational(p_bsing, options=options)
    ok_bsing = (
        r_bsing.data is not None
        and r_bsing.data["audit_feasibility"] != "strictly_feasible"
        and r_bsing.data["certificate_status"] != "failed_validation"
    )
    cases_summary.append(_extract_case_summary("B_singular_no_slater", "B", r_bsing, passed=ok_bsing))

    # ---------------- Nível C: SDPs construídos ----------------
    # C1: Lyapunov min Tr(P) comparado à solução analítica solve_continuous_lyapunov
    A_ly = np.array([[-2.0, 1.0], [0.0, -3.0]], dtype=np.float64)
    Q_ly = np.eye(2, dtype=np.float64)
    P_exact = scipy.linalg.solve_continuous_lyapunov(A_ly.T, -Q_ly)
    P_var = sdpvar((2, 2), name="P", symmetric=True)
    p_lyap = compile(
        trace(P_var),
        [P_var >= 1e-4 * np.eye(2), -(A_ly.T @ P_var + P_var @ A_ly + Q_ly) >= np.zeros((2, 2))],
        name="C_lyapunov",
    )
    r_lyap = solve_sdp_educational(p_lyap, options=options)
    ok_lyap = (
        r_lyap.data is not None
        and r_lyap.data["solver_status"] == "optimal"
        and r_lyap.data["certificate_status"] == "validated_dual"
        and abs(float(r_lyap.data["objective"]) - float(np.trace(P_exact))) <= 1e-6
    )
    cases_summary.append(
        _extract_case_summary(
            "C_lyapunov_analytical",
            "C",
            r_lyap,
            passed=ok_lyap,
            detail={"exact_trace": float(np.trace(P_exact))},
        )
    )

    # C_weak: [[x, 1], [1, 0]] >= 0 (weak infeasibility -> inconclusive, zero falsa certificação)
    p_weak = compile(
        x,
        [bmat([[x, np.ones((1, 1))], [np.ones((1, 1)), np.zeros((1, 1))]]) >= np.zeros((2, 2))],
        name="C_weak_infeasible",
    )
    r_weak = solve_sdp_educational(p_weak, options=options)
    ok_weak = (
        r_weak.status == "inconclusive"
        and r_weak.data is not None
        and r_weak.data["audit_feasibility"] == "inconclusive"
        and r_weak.data["certificate_status"] == "not_available"
    )
    cases_summary.append(_extract_case_summary("C_weak_infeasible", "C", r_weak, passed=ok_weak))

    # ---------------- Nível D: Síntese de Controle ----------------
    # D1: Estabilização contínua com taxa de decaimento alpha = 1.0
    plant_d1 = StateSpace(
        np.array([[0.0, 1.0], [2.0, -1.0]]),
        np.array([[0.0], [1.0]]),
        np.eye(2),
        np.zeros((2, 1)),
        dt=None,
    )
    p_d1 = continuous_stabilization_lmi(plant_d1, alpha=1.0, feedback_sign="positive")
    r_d1 = solve_sdp_educational(p_d1, options=options)
    rec_d1 = recover_controller(p_d1, r_d1, plant=plant_d1)
    ok_d1 = False
    if rec_d1.data is not None and rec_d1.data.get("controller_validity") == "verified_under_assumptions":
        ctrl_d1 = StateFeedbackController.from_dict(rec_d1.data["controller"])
        acl = get_closed_loop_matrix(plant_d1, ctrl_d1)
        ok_d1 = float(np.max(np.real(np.linalg.eigvals(acl)))) < -1.0
    cases_summary.append(_extract_case_summary("T-SDP-D1", "D", r_d1, passed=ok_d1))

    # D2: H-infinito BRL generalizado (minimização de gamma)
    p_d2 = hinf_brl_lmi(
        np.array([[0.0, 1.0], [-1.0, 0.0]]),
        np.array([[0.0], [1.0]]),
        np.array([[0.0], [1.0]]),
        np.array([[1.0, 0.0], [0.0, 0.0]]),
        np.array([[0.0], [0.0]]),
        np.array([[0.0], [0.5]]),
        gamma=None,
        feedback_sign="positive",
    )
    r_d2 = solve_sdp_educational(p_d2, options=options)
    rec_d2 = recover_controller(p_d2, r_d2)
    ok_d2 = (
        rec_d2.data is not None
        and rec_d2.data.get("controller_validity") == "verified_under_assumptions"
        and float(rec_d2.data["sampled_hinf_norm_max"]) < float(rec_d2.data["gamma"])
    )
    cases_summary.append(_extract_case_summary("T-SDP-D2", "D", r_d2, passed=ok_d2))

    # D3: D-estabilidade (disco + semiplano)
    plant_ds = StateSpace(
        np.array([[0.0, 1.0], [-2.0, 0.5]]),
        np.array([[0.0], [1.0]]),
        np.eye(2),
        np.zeros((2, 1)),
        dt=None,
    )
    p_ds = regional_pole_placement_lmi(plant_ds, radius=5.0, alpha=1.0, feedback_sign="negative")
    r_ds = solve_sdp_educational(p_ds, options=options)
    rec_ds = recover_controller(p_ds, r_ds, plant=plant_ds)
    ok_ds = rec_ds.data is not None and rec_ds.data.get("controller_validity") == "verified_under_assumptions"
    cases_summary.append(_extract_case_summary("D_regional_pole_placement", "D", r_ds, passed=ok_ds))

    # D4: TS/PDC 2 regras
    ts = TSStateSpace(
        [
            {"vertex_id": "rule_1", "A": np.array([[1.0, 2.0], [-1.0, -2.0]]), "B": np.array([[1.0], [0.0]]), "C": np.eye(2), "D": np.zeros((2, 1))},
            {"vertex_id": "rule_2", "A": np.array([[1.0, 2.0], [-1.0, -2.0]]), "B": np.array([[0.5], [1.0]]), "C": np.eye(2), "D": np.zeros((2, 1))},
        ],
        kind="ts_measured",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["x1"], "sum_to_one_domain": True},
        premise_availability={"mode": "all_measured", "measured_premises": ["x1"], "unmeasured_premises": [], "estimator_required_for_pdc": False},
        domain={"bounds": {"x1": [-2.0, 2.0]}},
        id="suite-ts-pdc",
        revision=0,
    )
    p_ts = ts_pdc_stabilization_lmi(ts, alpha=0.2, feedback_sign="positive")
    r_ts = solve_sdp_educational(p_ts, options=options)
    rec_ts = recover_controller(p_ts, r_ts, plant=ts)
    ok_ts = rec_ts.data is not None and rec_ts.data.get("controller_validity") == "verified_under_assumptions"
    cases_summary.append(_extract_case_summary("D_ts_pdc_2_rules", "D", r_ts, passed=ok_ts))

    overall_passed = all(c["passed"] for c in cases_summary)
    return Result(
        status="warning" if overall_passed else "inconclusive",
        data=ensure_json_finite(
            {
                "suite": "educational_sdp_levels_a_to_d",
                "backend": "educational_primal_dual",
                "maturity": "experimental",
                "experimental": True,
                "overall_passed": overall_passed,
                "total_cases": len(cases_summary),
                "passed_cases": sum(1 for c in cases_summary if c["passed"]),
                "cases": cases_summary,
            }
        ),
        assumptions={
            "experimental": True,
            "maturity": "experimental",
            "production_backend_eligible": False,
        },
        diagnostics=ensure_json_finite(
            {
                "overall_passed": overall_passed,
                "passed_cases": sum(1 for c in cases_summary if c["passed"]),
                "total_cases": len(cases_summary),
            }
        ),
        provenance=prov,
        warnings=(
            WarningItem(
                code="EXPERIMENTAL_EDUCATIONAL_SOLVER",
                message=(
                    "Bateria A–D executada no solver didático experimental (R-13 / ADR-008); "
                    "aprovação em A–D não promove automaticamente o solver para produção."
                ),
            ),
        ),
        error=None,
    )
