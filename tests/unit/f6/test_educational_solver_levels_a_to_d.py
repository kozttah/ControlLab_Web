"""Testes normativos e escalonados Níveis A–D para o solver SDP educacional (WP-10 / R-13 / ADR-008 / CL-DIR-001 Seção 6.5).

Cobre obrigatoriamente:
- Nível A (LP / escalares): caixa 1 <= x <= 2, T-SDP-A1 (fronteira x >= 1), T-SDP-A2 (Farkas forte),
  T-SDP-A3 (ilimitado com direção recessiva + x0) e mistura PSD + Eq + Ineq;
- Nível B (PSD analítico): T-SDP-B1 ([[1, x], [x, 1]] >= 0, min x e max x), bloco diagonal,
  pura factibilidade Hurwitz vs não-Hurwitz, bloco PSD singular sem interior de Slater e PSD infactível;
- Nível C (SDPs construídos): T-SDP-C1 (3x3 Slater), Lyapunov analítico min Tr(P) vs solve_continuous_lyapunov,
  condicionamento extremo (scaling_warning), weak infeasibility (inconclusive, zero falsa certificação)
  e comparação cruzada contra ClarabelDirectBackend / ClarabelCvxpyBackend;
- Nível D (Controle por LMI): T-SDP-D1 (sinais positivo/negativo e fixture ouro), T-SDP-D2 (BRL H-infinito
  gamma fixo e mínimo), D-estabilidade (disco + semiplano e região vazia infactível), politópico 2 vértices
  e TS/PDC 2 regras com rejeição de polytopic_uncertain;
- Invariantes arquiteturais e contratuais: maturidade estrita `"experimental"`, não seleção em `get_backend("auto")`,
  auditoria independente em 5 dimensões via `verify()`, histórico do caminho central NT + Mehrotra,
  validação contra `result.schema.json` e zero `linalg.inv` via AST.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import scipy.linalg
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core import (
    PDCController,
    StateFeedbackController,
    StateSpace,
    TSStateSpace,
    get_closed_loop_matrix,
    tensor_to_array,
)
from control_lab.diagnostics import HypothesisViolatedError, Result, ValidationError
from control_lab.experimental.sdp_educational import (
    EducationalPrimalDualSDPBackend,
    EducationalSolverConfig,
    IterationRecord,
    make_educational_barrier_backend,
    run_educational_levels_a_to_d_suite,
    solve_sdp_educational,
    solve_sdp_educational_raw,
)
from control_lab.optimization import (
    CanonicalSDPProblem,
    bmat,
    compile,
    continuous_stabilization_lmi,
    get_backend,
    hinf_brl_lmi,
    linear_eq,
    linear_ineq,
    psd,
    recover_controller,
    regional_pole_placement_lmi,
    sdpvar,
    solve,
    trace,
    ts_pdc_stabilization_lmi,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
FIXTURES_DIR = ROOT / "contracts" / "fixtures"
EDU_DIR = ROOT / "control_lab" / "experimental" / "sdp_educational"


@pytest.fixture(scope="module")
def schema_registry() -> tuple[Registry, dict[str, dict[str, Any]]]:
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        res = Resource.from_contents(schema)
        resources.append((schema.get("$id", path.name), res))
        resources.append((path.name, res))
    return Registry().with_resources(resources), schemas


@pytest.fixture(scope="module")
def b_sdp_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / "B-SDP-A-D.json").read_text(encoding="utf-8"))


def _assert_schema_valid(
    instance: dict[str, Any],
    schema_name: str,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    registry, schemas = schema_registry
    Draft202012Validator(schemas[schema_name], registry=registry).validate(instance)


# ---------------------------------------------------------------------------
# 1. Nível A — LP / Escalares / Igualdades e Desigualdades Mistas
# ---------------------------------------------------------------------------


def test_level_a_box_t_sdp_a1_a2_a3_and_mixed_constraints(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    tols = b_sdp_fixture["tolerances"]

    # Caixa 1 <= x <= 2, min x -> x* = 1
    x = sdpvar((1, 1), name="x")
    p_box = compile(x, [x >= 1.0, 2.0 - x >= 0.0], name="level_a_box")
    r_box = solve_sdp_educational(p_box)
    _assert_schema_valid(r_box.to_dict(), "result.schema.json", schema_registry)
    assert r_box.status == "warning"  # método experimental sempre preserva aviso
    assert r_box.data is not None
    assert r_box.data["solver_status"] == "optimal"
    assert r_box.data["certificate_status"] == "validated_dual"
    assert r_box.data["maturity"] == "experimental"
    assert r_box.data["experimental"] is True
    assert math.isclose(float(r_box.data["objective"]), 1.0, abs_tol=tols["gap_tol"])
    assert len(r_box.data["history"]) >= 2

    # T-SDP-A1: min x s.t. x >= 1 (fronteira)
    c_a1 = b_sdp_fixture["data"]["cases"]["T-SDP-A1"]
    p_a1 = CanonicalSDPProblem.from_fixture_case(c_a1)
    r_a1 = solve_sdp_educational(p_a1)
    _assert_schema_valid(r_a1.to_dict(), "result.schema.json", schema_registry)
    assert r_a1.data is not None
    assert r_a1.data["solver_status"] == "optimal"
    assert r_a1.data["audit_feasibility"] == "approximately_feasible"
    assert r_a1.data["certificate_status"] == "validated_dual"
    np.testing.assert_allclose(tensor_to_array(r_a1.data["x"]), np.array(c_a1["expected"]["x_opt"]), atol=tols["primal_tol"])
    assert math.isclose(float(r_a1.data["objective"]), float(c_a1["expected"]["obj_opt"]), abs_tol=tols["gap_tol"])

    # T-SDP-A2: infactibilidade forte (x >= 2, x <= 1) com certificado de Farkas validado
    c_a2 = b_sdp_fixture["data"]["cases"]["T-SDP-A2"]
    p_a2 = CanonicalSDPProblem.from_fixture_case(c_a2)
    r_a2 = solve_sdp_educational(p_a2)
    _assert_schema_valid(r_a2.to_dict(), "result.schema.json", schema_registry)
    assert r_a2.data is not None
    assert r_a2.data["solver_status"] == "primal_infeasible"
    assert r_a2.data["audit_feasibility"] == "violated"
    assert r_a2.data["certificate_status"] == "validated_infeasibility"

    # T-SDP-A3: ilimitado (min x, x <= 2) com direção recessiva e x0 factível auditados
    c_a3 = b_sdp_fixture["data"]["cases"]["T-SDP-A3"]
    p_a3 = CanonicalSDPProblem.from_fixture_case(c_a3)
    r_a3 = solve_sdp_educational(p_a3)
    _assert_schema_valid(r_a3.to_dict(), "result.schema.json", schema_registry)
    assert r_a3.data is not None
    assert r_a3.data["solver_status"] == "dual_infeasible"
    assert r_a3.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
    assert r_a3.data["certificate_status"] == "validated_unboundedness"
    d_rec = tensor_to_array(r_a3.data["recession_direction"])
    assert float(d_rec[0]) < -0.5

    # Misto PSD diagonal + igualdade + desigualdade via EducationalBarrierBackend injetado em solve()
    y = sdpvar((2, 1), name="y")
    p_mix = compile(
        2.0 * y[0, 0] + 3.0 * y[1, 0],
        [
            psd(bmat([[y[0, 0] - 1.0, 0.0], [0.0, y[1, 0] - 2.0]]), name="diag_blk"),
            linear_eq(y[0, 0] + y[1, 0], 5.0, name="sum_eq"),
            linear_ineq(2.0 * y[0, 0], 7.0, name="y0_ub"),
        ],
        name="mixed_level_a",
    )
    edu_bk = make_educational_barrier_backend()
    r_mix_edu = solve(p_mix, backend=edu_bk)
    r_mix_ref = solve(p_mix, backend="clarabel_direct")
    assert r_mix_edu.status == "warning"
    assert r_mix_edu.assumptions["experimental"] is True
    assert r_mix_edu.data is not None and r_mix_ref.data is not None
    assert r_mix_edu.data["certificate_status"] == "validated_dual"
    assert math.isclose(float(r_mix_edu.data["objective"]), float(r_mix_ref.data["objective"]), abs_tol=1e-6)


# ---------------------------------------------------------------------------
# 2. Nível B — PSD Analítico, Diagonal, Pura Factibilidade e Singularidade
# ---------------------------------------------------------------------------


def test_level_b_psd_analytical_diagonal_singular_and_infeasible(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    tols = b_sdp_fixture["tolerances"]
    c_b1 = b_sdp_fixture["data"]["cases"]["T-SDP-B1"]
    p_b1 = CanonicalSDPProblem.from_fixture_case(c_b1)

    # T-SDP-B1: min x s.t. [[1, x], [x, 1]] >= 0 -> x* = -1
    r_b1 = solve_sdp_educational(p_b1)
    _assert_schema_valid(r_b1.to_dict(), "result.schema.json", schema_registry)
    assert r_b1.data is not None
    assert r_b1.data["solver_status"] == "optimal"
    assert r_b1.data["audit_feasibility"] == "approximately_feasible"
    assert r_b1.data["certificate_status"] == "validated_dual"
    x_b1 = tensor_to_array(r_b1.data["x"])
    np.testing.assert_allclose(x_b1, np.array(c_b1["expected"]["x_opt"]), atol=tols["primal_tol"])
    assert math.isclose(float(r_b1.data["objective"]), float(c_b1["expected"]["obj_opt"]), abs_tol=tols["gap_tol"])
    eig_b1 = np.sort(np.linalg.eigvalsh(p_b1.evaluate_blocks(x_b1)[0]))
    np.testing.assert_allclose(eig_b1, np.array(c_b1["expected"]["boundary_eigenvalues"]), atol=1e-6)

    # Extremo oposto: max x s.t. [[1, x], [x, 1]] >= 0 -> x* = +1
    x = sdpvar((1, 1), name="x")
    p_b1_max = compile(
        x,
        [bmat([[np.ones((1, 1)), x], [x, np.ones((1, 1))]]) >= np.zeros((2, 2))],
        sense="maximize",
        name="b1_max",
    )
    r_b1_max = solve_sdp_educational(p_b1_max)
    assert r_b1_max.data is not None
    assert r_b1_max.data["solver_status"] == "optimal"
    assert r_b1_max.data["certificate_status"] == "validated_dual"
    np.testing.assert_allclose(tensor_to_array(r_b1_max.data["x"]), np.array([1.0]), atol=1e-6)

    # Pura factibilidade (c = 0): Lyapunov Hurwitz vs não-Hurwitz
    Q = sdpvar((2, 2), name="Q", symmetric=True)
    A_ok = np.array([[-1.0, 0.2], [0.0, -2.0]])
    p_ok = compile(0.0 * Q[0, 0], [Q >= np.eye(2), -(A_ok @ Q + Q @ A_ok.T + np.eye(2)) >= np.zeros((2, 2))])
    r_ok = solve_sdp_educational(p_ok)
    assert r_ok.data is not None
    assert r_ok.data["solver_status"] == "optimal"
    assert r_ok.data["audit_feasibility"] == "strictly_feasible"
    assert r_ok.data["certificate_status"] == "validated_dual"

    A_bad = np.array([[1.0, 0.0], [0.0, -1.0]])
    p_bad = compile(0.0 * Q[0, 0], [Q >= np.eye(2), -(A_bad @ Q + Q @ A_bad.T + np.eye(2)) >= np.zeros((2, 2))])
    r_bad = solve_sdp_educational(p_bad)
    assert r_bad.data is not None
    assert r_bad.data["solver_status"] == "primal_infeasible"
    assert r_bad.data["audit_feasibility"] == "violated"
    assert r_bad.data["certificate_status"] == "validated_infeasibility"

    # Bloco PSD singular sem interior de Slater ([[0, 0], [0, x]] >= 0):
    # jamais deve declarar 'strictly_feasible' ou falsificar otimalidade sem certificado dual
    p_sing = compile(
        x,
        [bmat([[np.zeros((1, 1)), np.zeros((1, 1))], [np.zeros((1, 1)), x]]) >= np.zeros((2, 2))],
        name="psd_singular_no_slater",
    )
    r_sing = solve_sdp_educational(p_sing)
    assert r_sing.data is not None
    assert r_sing.data["solver_status"] == "max_iterations"
    assert r_sing.data["audit_feasibility"] != "strictly_feasible"
    assert r_sing.data["certificate_status"] in ("validated_primal", "not_available")

    # Caso PSD estritamente infactível [[-1, x], [x, -1]] >= 0 -> Farkas validado
    p_psd_inf = compile(
        x,
        [bmat([[-np.ones((1, 1)), x], [x, -np.ones((1, 1))]]) >= np.zeros((2, 2))],
        name="psd_strongly_infeasible",
    )
    r_psd_inf = solve_sdp_educational(p_psd_inf)
    assert r_psd_inf.data is not None
    assert r_psd_inf.data["solver_status"] == "primal_infeasible"
    assert r_psd_inf.data["certificate_status"] == "validated_infeasibility"


# ---------------------------------------------------------------------------
# 3. Nível C — SDPs Construídos, Oráculo Analítico, Escala Extrema e Weak Inf.
# ---------------------------------------------------------------------------


def test_level_c_slater_lyapunov_ill_conditioning_and_weak_infeasibility(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    tols = b_sdp_fixture["tolerances"]
    c_c1 = b_sdp_fixture["data"]["cases"]["T-SDP-C1"]
    p_c1 = CanonicalSDPProblem.from_fixture_case(c_c1)

    r_c1 = solve_sdp_educational(p_c1)
    r_c1_ref = solve(p_c1, backend="clarabel_direct")
    _assert_schema_valid(r_c1.to_dict(), "result.schema.json", schema_registry)
    assert r_c1.data is not None and r_c1_ref.data is not None
    assert r_c1.data["solver_status"] == "optimal"
    assert r_c1.data["certificate_status"] == "validated_dual"
    assert float(r_c1.data["residuals"]["duality_gap_rel"]) <= tols["gap_tol"]
    np.testing.assert_allclose(tensor_to_array(r_c1.data["x"]), np.array(c_c1["expected"]["x_opt"]), atol=tols["primal_tol"])
    assert math.isclose(float(r_c1.data["objective"]), float(r_c1_ref.data["objective"]), abs_tol=1e-7)

    # Lyapunov min Tr(P) comparado diretamente à equação contínua analítica
    A_ly = np.array([[-2.0, 1.0, 0.3], [0.0, -3.0, -0.5], [0.2, 0.0, -4.0]], dtype=np.float64)
    Q_ly = np.eye(3, dtype=np.float64)
    P_exact = scipy.linalg.solve_continuous_lyapunov(A_ly.T, -Q_ly)
    P_var = sdpvar((3, 3), name="P", symmetric=True)
    p_lyap = compile(
        trace(P_var),
        [P_var >= 1e-4 * np.eye(3), -(A_ly.T @ P_var + P_var @ A_ly + Q_ly) >= np.zeros((3, 3))],
        name="lyapunov_3x3",
    )
    r_lyap = solve_sdp_educational(p_lyap)
    assert r_lyap.data is not None
    assert r_lyap.data["solver_status"] == "optimal"
    assert r_lyap.data["certificate_status"] == "validated_dual"
    P_edu = tensor_to_array(r_lyap.data["variables"]["P"])
    np.testing.assert_allclose(P_edu, P_exact, atol=1e-6, rtol=1e-6)

    # Condicionamento ruim proposital (1e-4 vs 1e4): scaling_warning sinalizado honestamente
    A_ill = np.array([[-1e-4, 0.0], [0.0, -1e4]], dtype=np.float64)
    P_ill = sdpvar((2, 2), name="P", symmetric=True)
    p_ill = compile(
        trace(P_ill),
        [P_ill >= 1e-4 * np.eye(2), -(A_ill.T @ P_ill + P_ill @ A_ill + np.diag([1.0, 1e4])) >= np.zeros((2, 2))],
        name="ill_conditioned_lyap",
    )
    r_ill = solve_sdp_educational(p_ill)
    assert r_ill.data is not None
    assert r_ill.data["conditioning"]["scaling_warning"] is True
    assert any(w.code == "SDP_SCALING_WARNING" for w in r_ill.warnings)

    # Weak infeasibility: [[x, 1], [1, 0]] >= 0 e versão com igualdade y == 0
    # Não existe x factível nem certificado de Farkas estrito -> deve ser inconclusive!
    x = sdpvar((1, 1), name="x")
    y = sdpvar((1, 1), name="y")
    p_weak1 = compile(
        x,
        [bmat([[x, np.ones((1, 1))], [np.ones((1, 1)), np.zeros((1, 1))]]) >= np.zeros((2, 2))],
        name="weak_infeas_1",
    )
    p_weak2 = compile(
        x + y,
        [bmat([[x, np.ones((1, 1))], [np.ones((1, 1)), y]]) >= np.zeros((2, 2)), linear_eq(y, 0.0)],
        name="weak_infeas_eq",
    )
    for p_w in (p_weak1, p_weak2):
        r_w = solve_sdp_educational(p_w)
        _assert_schema_valid(r_w.to_dict(), "result.schema.json", schema_registry)
        assert r_w.status == "inconclusive"
        assert r_w.data is not None
        assert r_w.data["solver_status"] == "max_iterations"
        assert r_w.data["audit_feasibility"] == "inconclusive"
        assert r_w.data["certificate_status"] == "not_available"


# ---------------------------------------------------------------------------
# 4. Nível D — Estabilização, D-estabilidade, BRL H-infinito, Politópico e TS/PDC
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("feedback_sign", ["positive", "negative"])
def test_level_d_continuous_stabilization_t_sdp_d1(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
    feedback_sign: str,
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-D1"]
    plant = StateSpace(
        tensor_to_array(case["A"]),
        tensor_to_array(case["B"]),
        np.eye(2),
        np.zeros((2, 1)),
        dt=None,
        id="edu-d1",
        revision=1,
    )
    alpha = float(case["alpha"])

    prob = continuous_stabilization_lmi(plant, alpha=alpha, feedback_sign=feedback_sign)
    res = solve_sdp_educational(prob)
    _assert_schema_valid(res.to_dict(), "result.schema.json", schema_registry)
    assert res.data is not None
    assert res.data["solver_status"] == "optimal"
    assert res.data["certificate_status"] == "validated_dual"

    rec = recover_controller(prob, res, plant=plant)
    _assert_schema_valid(rec.to_dict(), "result.schema.json", schema_registry)
    assert rec.data is not None
    assert rec.data["controller_validity"] == "verified_under_assumptions"

    ctrl = StateFeedbackController.from_dict(rec.data["controller"])
    assert ctrl.feedback_sign == feedback_sign
    acl = get_closed_loop_matrix(plant, ctrl)
    assert float(np.max(np.real(np.linalg.eigvals(acl)))) < -alpha


def test_level_d_hinf_brl_t_sdp_d2_fixed_and_minimized(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-D2"]
    A = tensor_to_array(case["A"])
    B1 = tensor_to_array(case["B1"])
    B2 = tensor_to_array(case["B2"])
    C1 = tensor_to_array(case["C1"])
    D11 = tensor_to_array(case["D11"])
    D12 = tensor_to_array(case["D12"])
    gamma_fix = float(case["gamma"])

    # Modo gamma fixo = 3.0
    p_fix = hinf_brl_lmi(A, B1, B2, C1, D11, D12, gamma=gamma_fix, feedback_sign="positive")
    r_fix = solve_sdp_educational(p_fix)
    assert r_fix.data is not None
    assert r_fix.data["solver_status"] == "optimal"
    assert r_fix.data["certificate_status"] == "validated_dual"
    rec_fix = recover_controller(p_fix, r_fix)
    assert rec_fix.data is not None
    assert rec_fix.data["controller_validity"] == "verified_under_assumptions"
    assert float(rec_fix.data["sampled_hinf_norm_max"]) < gamma_fix

    # Modo minimização de gamma: comparar com ClarabelDirectBackend
    p_min = hinf_brl_lmi(A, B1, B2, C1, D11, D12, gamma=None, feedback_sign="positive")
    r_edu = solve_sdp_educational(p_min)
    r_ref = solve(p_min, backend="clarabel_direct")
    _assert_schema_valid(r_edu.to_dict(), "result.schema.json", schema_registry)
    assert r_edu.data is not None and r_ref.data is not None
    assert r_edu.data["solver_status"] == "optimal"
    assert r_edu.data["certificate_status"] == "validated_dual"
    assert math.isclose(float(r_edu.data["objective"]), float(r_ref.data["objective"]), rel_tol=1e-4, abs_tol=1e-4)

    rec_min = recover_controller(p_min, r_edu)
    assert rec_min.data is not None
    assert rec_min.data["controller_validity"] == "verified_under_assumptions"
    assert float(rec_min.data["sampled_hinf_norm_max"]) < float(rec_min.data["gamma"])


def test_level_d_regional_pole_placement_polytopic_and_ts_pdc(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    # 1. D-estabilidade: disco + semiplano factível e região vazia infactível
    plant = StateSpace(np.array([[0.0, 1.0], [-2.0, 0.5]]), np.array([[0.0], [1.0]]), np.eye(2), np.zeros((2, 1)), dt=None)
    p_ds = regional_pole_placement_lmi(plant, radius=5.0, alpha=1.0, feedback_sign="negative")
    r_ds = solve_sdp_educational(p_ds)
    rec_ds = recover_controller(p_ds, r_ds, plant=plant)
    assert r_ds.data is not None and rec_ds.data is not None
    assert r_ds.data["solver_status"] == "optimal"
    assert r_ds.data["certificate_status"] == "validated_dual"
    assert rec_ds.data["controller_validity"] == "verified_under_assumptions"
    eigs_ds = np.linalg.eigvals(get_closed_loop_matrix(plant, StateFeedbackController.from_dict(rec_ds.data["controller"])))
    assert float(np.max(np.abs(eigs_ds))) < 5.0
    assert float(np.max(np.real(eigs_ds))) < -1.0

    p_ds_empty = regional_pole_placement_lmi(plant, radius=1.0, alpha=2.0)
    r_ds_empty = solve_sdp_educational(p_ds_empty)
    assert r_ds_empty.data is not None
    assert r_ds_empty.data["solver_status"] == "primal_infeasible"
    assert r_ds_empty.data["certificate_status"] == "validated_infeasibility"

    # 2. Estabilização politópica de 2 vértices com Q comum (e limitantes razoáveis em Y para existir ótimo finito)
    A1 = np.array([[0.0, 1.0], [1.0, -1.0]])
    A2 = np.array([[0.0, 1.0], [2.0, -0.5]])
    B_p = np.array([[0.0], [1.0]])
    Q = sdpvar((2, 2), name="Q", symmetric=True)
    Y = sdpvar((1, 2), name="Y")
    p_poly = compile(
        trace(Q),
        [
            Q >= 0.1 * np.eye(2),
            Q <= 100.0 * np.eye(2),
            linear_ineq(Y[0, 0], 50.0),
            linear_ineq(-Y[0, 0], 50.0),
            linear_ineq(Y[0, 1], 50.0),
            linear_ineq(-Y[0, 1], 50.0),
            -(A1 @ Q + Q @ A1.T + B_p @ Y + Y.T @ B_p.T + 0.5 * Q) >= np.zeros((2, 2)),
            -(A2 @ Q + Q @ A2.T + B_p @ Y + Y.T @ B_p.T + 0.5 * Q) >= np.zeros((2, 2)),
        ],
        name="polytopic_2_vertices",
    )
    r_poly = solve_sdp_educational(p_poly)
    assert r_poly.data is not None
    assert r_poly.data["solver_status"] == "optimal"
    assert r_poly.data["certificate_status"] == "validated_dual"
    Q_val = tensor_to_array(r_poly.data["variables"]["Q"])
    Y_val = tensor_to_array(r_poly.data["variables"]["Y"])
    K_poly = scipy.linalg.solve(Q_val.T, Y_val.T).T
    for Av in (A1, A2):
        assert float(np.max(np.real(np.linalg.eigvals(Av + B_p @ K_poly)))) < -0.2

    # 3. TS/PDC de 2 regras e rejeição explícita de polytopic_uncertain
    v1 = {"vertex_id": "rule_1", "A": np.array([[1.0, 2.0], [-1.0, -2.0]]), "B": np.array([[1.0], [0.0]]), "C": np.eye(2), "D": np.zeros((2, 1))}
    v2 = {"vertex_id": "rule_2", "A": np.array([[1.0, 2.0], [-1.0, -2.0]]), "B": np.array([[0.5], [1.0]]), "C": np.eye(2), "D": np.zeros((2, 1))}
    ts_meas = TSStateSpace(
        [v1, v2],
        kind="ts_measured",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["x1"], "sum_to_one_domain": True},
        premise_availability={
            "mode": "all_measured",
            "measured_premises": ["x1"],
            "unmeasured_premises": [],
            "estimator_required_for_pdc": False,
        },
        domain={"bounds": {"x1": [-2.0, 2.0]}},
        id="ts-edu-pdc",
        revision=0,
    )
    p_ts = ts_pdc_stabilization_lmi(ts_meas, alpha=0.2, feedback_sign="positive")
    r_ts = solve_sdp_educational(p_ts)
    rec_ts = recover_controller(p_ts, r_ts, plant=ts_meas)
    _assert_schema_valid(rec_ts.to_dict(), "result.schema.json", schema_registry)
    assert r_ts.data is not None and rec_ts.data is not None
    assert r_ts.data["solver_status"] == "optimal"
    assert r_ts.data["certificate_status"] == "validated_dual"
    assert rec_ts.data["controller_validity"] == "verified_under_assumptions"
    assert isinstance(PDCController.from_dict(rec_ts.data["controller"]), PDCController)

    ts_poly = TSStateSpace(
        [v1, v2],
        kind="polytopic_uncertain",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["theta"], "sum_to_one_domain": True},
        premise_availability={
            "mode": "unknown_uncertain",
            "measured_premises": [],
            "unmeasured_premises": ["theta"],
            "estimator_required_for_pdc": True,
        },
        domain={"bounds": {"theta": [0.0, 1.0]}},
    )
    with pytest.raises(HypothesisViolatedError):
        ts_pdc_stabilization_lmi(ts_poly)


# ---------------------------------------------------------------------------
# 5. Invariantes de Maturidade, Rastreabilidade NT+Mehrotra, Bateria e AST
# ---------------------------------------------------------------------------


def test_experimental_maturity_isolation_history_suite_and_ast_no_inv(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    # 1. Isolamento de produção: get_backend('auto') jamais escolhe solver experimental
    p_c1 = CanonicalSDPProblem.from_fixture_case(b_sdp_fixture["data"]["cases"]["T-SDP-C1"])
    bk_auto = get_backend("auto", problem=p_c1)
    assert bk_auto.is_experimental is False
    assert bk_auto.name != "educational_primal_dual"

    # 2. Metadados de maturidade e histórico didático do caminho central NT + Mehrotra
    bk_edu = EducationalPrimalDualSDPBackend()
    caps = bk_edu.capabilities()
    assert caps["maturity"] == "experimental"
    assert caps["experimental"] is True
    assert caps["method"] == "primal_dual_nt_mehrotra_interior_point"

    res_c1 = solve_sdp_educational(p_c1)
    assert res_c1.status == "warning"
    assert res_c1.assumptions["maturity"] == "experimental"
    assert res_c1.assumptions["experimental"] is True
    assert any(w.code == "EXPERIMENTAL_EDUCATIONAL_SOLVER" for w in res_c1.warnings)
    assert res_c1.data is not None
    hist = res_c1.data["history"]
    p2_hist = [h for h in hist if h["phase"] == "phase2"]
    assert len(p2_hist) >= 3
    assert p2_hist[-1]["mu"] < p2_hist[0]["mu"]
    assert all(h["min_eig_primal"] > 0.0 for h in p2_hist)
    assert all(h["min_eig_dual"] > 0.0 for h in p2_hist)
    assert isinstance(IterationRecord(**hist[0]), IterationRecord)

    # 3. Suite consolidada A-D
    suite_res = run_educational_levels_a_to_d_suite()
    _assert_schema_valid(suite_res.to_dict(), "result.schema.json", schema_registry)
    assert suite_res.status == "warning"
    assert suite_res.data is not None
    assert suite_res.data["maturity"] == "experimental"
    assert suite_res.data["overall_passed"] is True
    assert suite_res.data["passed_cases"] == suite_res.data["total_cases"]

    # 4. Validação de entradas e opções inválidas (erros tipados, sem objeto parcial)
    with pytest.raises(ValidationError):
        EducationalSolverConfig.from_options({"unknown_opt": 123})
    res_bad_in = solve_sdp_educational("not_a_problem")  # type: ignore[arg-type]
    assert isinstance(res_bad_in, Result)
    assert res_bad_in.status == "failure"
    assert res_bad_in.error is not None
    assert res_bad_in.error.code == "VALIDATION_ERROR"
    with pytest.raises(ValidationError):
        solve_sdp_educational_raw("not_a_problem")  # type: ignore[arg-type]

    # 5. Inspeção AST: zero linalg.inv em todo control_lab/experimental/sdp_educational/
    py_files = sorted(EDU_DIR.rglob("*.py"))
    assert len(py_files) >= 3
    for fpath in py_files:
        tree = ast.parse(fpath.read_text(encoding="utf-8"), filename=str(fpath))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "inv":
                assert not (isinstance(node.value, ast.Attribute) and node.value.attr == "linalg"), (
                    f"Uso proibido de linalg.inv detectado em {fpath}"
                )
