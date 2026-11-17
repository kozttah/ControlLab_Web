"""Testes unitários, contratuais e matemáticos da Frente F6 para WP-03-F6-SDP-MODELING-AND-GATE0B.

Cobre obrigatoriamente:
- Vetorização isométrica svec/smat (fator sqrt(2) compatível com Clarabel PSDTriangleConeT);
- DSL afim segura (rejeição de bilinearidade, desigualdades estritas, validação de bmat);
- Bateria escalonada B-SDP-A-D: T-SDP-A1, T-SDP-A2, T-SDP-A3, T-SDP-B1, T-SDP-C1, T-SDP-D1, T-SDP-D2;
- Templates de controle: estabilização contínua, D-estabilidade (disco + semiplano), BRL H-infinito, TS/PDC;
- Verificador independente em 5 dimensões (Tabela 6.3) incluindo casos negativos/certificados quebrados;
- Backends ClarabelDirect, ClarabelCvxpy, ScipyLinprog (fallback diagonal exato), Unavailable, EducationalBarrier;
- Ensaio do Gate G-0B, exportação CPython e invariantes AST (zero linalg.inv, zero import de experimental).
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
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
from control_lab.diagnostics import (
    DimensionMismatchError,
    HypothesisViolatedError,
    Result,
    UnsupportedModelError,
    ValidationError,
)
from control_lab.optimization import (
    AUDIT_FEASIBILITY_LEVELS,
    CERTIFICATE_STATUSES,
    CONTROLLER_VALIDITY_LEVELS,
    CanonicalSDPProblem,
    ClarabelCvxpyBackend,
    ClarabelDirectBackend,
    EducationalBarrierBackend,
    SOLVER_STATUSES,
    ScipyLinprogBackend,
    UnavailableBackend,
    bmat,
    compile,
    continuous_stabilization_lmi,
    describe_solver_capabilities,
    hinf_brl_lmi,
    linear_eq,
    linear_ineq,
    pack_variables_to_x,
    psd,
    recover_controller,
    regional_pole_placement_lmi,
    run_gate_0b_assay,
    sdpvar,
    smat,
    solve,
    solve_and_verify,
    svec,
    trace,
    ts_pdc_stabilization_lmi,
    verify,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
FIXTURES_DIR = ROOT / "contracts" / "fixtures"
OPT_DIR = ROOT / "control_lab" / "optimization"


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
# 1. Vetorização svec / smat e DSL afim
# ---------------------------------------------------------------------------


def test_svec_smat_isometry_sqrt2_and_validation() -> None:
    rng = np.random.default_rng(42)
    for n in (1, 2, 3, 6):
        A = rng.standard_normal((n, n))
        B = rng.standard_normal((n, n))
        U = 0.5 * (A + A.T)
        V = 0.5 * (B + B.T)

        su = svec(U)
        sv = svec(V)
        assert su.shape == (n * (n + 1) // 2,)
        assert math.isclose(float(np.dot(su, sv)), float(np.trace(U.T @ V)), rel_tol=1e-12, abs_tol=1e-12)
        np.testing.assert_allclose(smat(su, n=n), U, atol=1e-13)
        np.testing.assert_allclose(smat(su), U, atol=1e-13)

    # Fator sqrt(2) explícito em ordem column-major do triângulo superior para 3x3
    M3 = np.array([[1.0, 2.0, 4.0], [2.0, 3.0, 5.0], [4.0, 5.0, 6.0]])
    s2 = math.sqrt(2.0)
    expected_v = np.array([1.0, 2.0 * s2, 3.0, 4.0 * s2, 5.0 * s2, 6.0])
    np.testing.assert_allclose(svec(M3), expected_v, atol=1e-14)

    with pytest.raises(ValidationError):
        svec(np.array([[1.0, 2.0], [0.0, 1.0]]))  # assimétrica
    with pytest.raises(DimensionMismatchError):
        svec(np.zeros((2, 3)))
    with pytest.raises(DimensionMismatchError):
        smat(np.zeros(4))  # 4 não é triangular


def test_dsl_rejects_bilinear_products_strict_inequalities_and_bad_bmat() -> None:
    x = sdpvar((1, 1), name="x")
    y = sdpvar((1, 1), name="y")
    Q = sdpvar((2, 2), name="Q", symmetric=True)
    Y = sdpvar((2, 2), name="Y")

    # Produtos bilineares e não-afins proibidos
    with pytest.raises(ValidationError):
        _ = x * y
    with pytest.raises(ValidationError):
        _ = x ** 2
    with pytest.raises(ValidationError):
        _ = 1.0 / x
    with pytest.raises(ValidationError):
        _ = Q @ Y
    with pytest.raises(ValidationError):
        _ = Q @ Q
    with pytest.raises(ValidationError):
        _ = Q / x

    # Desigualdades estritas proibidas
    with pytest.raises(ValidationError):
        _ = Q > np.eye(2)
    with pytest.raises(ValidationError):
        _ = x < 1.0

    # Validação de bmat (vazios e dimensões incompatíveis)
    with pytest.raises(ValidationError):
        bmat([])
    with pytest.raises(ValidationError):
        bmat([[]])
    with pytest.raises(ValidationError):
        bmat([[Q, []]])
    with pytest.raises(ValidationError):
        bmat([[Q, None]])
    with pytest.raises(DimensionMismatchError):
        bmat([[Q, np.zeros((3, 2))]])
    with pytest.raises(DimensionMismatchError):
        bmat([[Q], [np.zeros((2, 3))]])
    with pytest.raises(ValidationError):
        bmat([[0.0, 0.0]])  # linha só de zeros sem dimensão determinada

    # Expressão assimétrica rejeitada em restrição PSD
    with pytest.raises(ValidationError):
        _ = Y >= 0.0

    # Nomes duplicados de variáveis no mesmo problema rejeitados
    x_dup = sdpvar((1, 1), name="x")
    with pytest.raises(ValidationError):
        compile(x + x_dup, [x >= 0.0, x_dup >= 0.0])


def test_canonical_serialization_and_cpython_script_export() -> None:
    Q = sdpvar((2, 2), name="Q", symmetric=True)
    x = sdpvar((1, 1), name="x")
    prob = compile(
        trace(Q) + x,
        [
            Q >= 0.5 * np.eye(2),
            bmat([[Q, np.array([[1.0], [0.0]])], [np.array([[1.0, 0.0]]), x]]) >= np.zeros((3, 3)),
            linear_eq(x, 2.0, name="fix_x"),
            linear_ineq(Q[0, 0], 10.0, name="cap_q00"),
        ],
        sense="minimize",
        name="roundtrip_test",
    )
    payload = prob.to_dict()
    prob2 = CanonicalSDPProblem.from_json(prob.to_json())
    assert prob2.n_vars == prob.n_vars
    assert prob2.n_blocks == prob.n_blocks
    assert prob2.n_eq == 1
    assert prob2.n_ineq == 1
    np.testing.assert_allclose(prob2.c, prob.c)
    assert payload["name"] == "roundtrip_test"

    for bk in ("clarabel_direct", "clarabel_cvxpy"):
        script = prob.export_cpython_script(backend=bk)
        ast.parse(script)  # sintaxe Python 3 válida
        assert "PROBLEM_PAYLOAD" in script


# ---------------------------------------------------------------------------
# 2. Bateria escalonada Níveis A-D (B-SDP-A-D)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend_name", ["clarabel_direct", "clarabel_cvxpy", "scipy_linprog"])
def test_t_sdp_a1_feasible_boundary_all_backends(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
    backend_name: str,
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-A1"]
    tols = b_sdp_fixture["tolerances"]
    prob = CanonicalSDPProblem.from_fixture_case(case)

    res = solve_and_verify(prob, backend=backend_name)
    assert res.status == "success"
    _assert_schema_valid(res.to_dict(), "result.schema.json", schema_registry)
    d = res.data
    assert d is not None
    assert d["solver_status"] == "optimal"
    assert d["audit_feasibility"] == "approximately_feasible"
    assert d["certificate_status"] == "validated_dual"
    assert d["controller_validity"] == "not_applicable"

    x_got = np.asarray(d["x"]["data"], dtype=np.float64)
    np.testing.assert_allclose(x_got, np.array(case["expected"]["x_opt"]), atol=tols["primal_tol"])
    assert math.isclose(float(d["objective"]), float(case["expected"]["obj_opt"]), abs_tol=tols["gap_tol"])


@pytest.mark.parametrize("backend_name", ["clarabel_direct", "clarabel_cvxpy"])
def test_t_sdp_a2_infeasible_farkas_certified(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
    backend_name: str,
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-A2"]
    prob = CanonicalSDPProblem.from_fixture_case(case)

    res = solve(prob, backend=backend_name)
    assert res.status == "success"
    _assert_schema_valid(res.to_dict(), "result.schema.json", schema_registry)
    d = res.data
    assert d is not None
    assert d["solver_status"] == "primal_infeasible"
    assert d["audit_feasibility"] == "violated"
    assert d["certificate_status"] == "validated_infeasibility"


def test_t_sdp_a2_scipy_linprog_without_farkas_is_inconclusive(
    b_sdp_fixture: dict[str, Any],
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-A2"]
    prob = CanonicalSDPProblem.from_fixture_case(case)
    res = solve(prob, backend="scipy_linprog")
    assert res.status == "inconclusive"
    assert res.data is not None
    assert res.data["solver_status"] == "primal_infeasible"
    assert res.data["audit_feasibility"] == "inconclusive"
    assert res.data["certificate_status"] == "not_available"


def test_t_sdp_a3_unbounded_certified_and_inconclusive_handling(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-A3"]
    prob = CanonicalSDPProblem.from_fixture_case(case)

    # ClarabelDirect entrega direção recessiva + x0 factível -> validated_unboundedness
    res_dir = solve(prob, backend="clarabel_direct")
    assert res_dir.status == "success"
    _assert_schema_valid(res_dir.to_dict(), "result.schema.json", schema_registry)
    assert res_dir.data is not None
    assert res_dir.data["solver_status"] == "dual_infeasible"
    assert res_dir.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
    assert res_dir.data["certificate_status"] == "validated_unboundedness"

    # CVXPY e SciPy não expõem direção recessiva -> inconclusive
    for bk in ("clarabel_cvxpy", "scipy_linprog"):
        res_other = solve(prob, backend=bk)
        assert res_other.status == "inconclusive"
        assert res_other.data is not None
        assert res_other.data["solver_status"] == "dual_infeasible"
        assert res_other.data["certificate_status"] == "not_available"
        assert res_other.data["audit_feasibility"] == "inconclusive"

    # Caso simultaneamente primal e dual infactível nunca pode declarar validated_unboundedness
    x1 = sdpvar((1, 1), name="x1")
    x2 = sdpvar((1, 1), name="x2")
    prob_both = compile(x2, [x1 >= 2.0, x1 <= 1.0], name="primal_and_dual_infeasible")
    res_both = solve(prob_both, backend="clarabel_direct")
    assert res_both.data is not None
    assert res_both.data["certificate_status"] != "validated_unboundedness"


@pytest.mark.parametrize("backend_name", ["clarabel_direct", "clarabel_cvxpy"])
def test_t_sdp_b1_2x2_psd_boundary_and_scipy_rejection(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
    backend_name: str,
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-B1"]
    tols = b_sdp_fixture["tolerances"]
    prob = CanonicalSDPProblem.from_fixture_case(case)

    res = solve(prob, backend=backend_name)
    assert res.status == "success"
    _assert_schema_valid(res.to_dict(), "result.schema.json", schema_registry)
    d = res.data
    assert d is not None
    assert d["solver_status"] == "optimal"
    assert d["audit_feasibility"] == "approximately_feasible"
    assert d["certificate_status"] == "validated_dual"
    x_got = np.asarray(d["x"]["data"], dtype=np.float64)
    np.testing.assert_allclose(x_got, np.array(case["expected"]["x_opt"]), atol=tols["primal_tol"])
    F_opt = prob.evaluate_blocks(x_got)[0]
    np.testing.assert_allclose(
        np.sort(np.linalg.eigvalsh(F_opt)),
        np.array(case["expected"]["boundary_eigenvalues"]),
        atol=1e-6,
    )


def test_scipy_linprog_rejects_non_diagonal_psd_with_solver_unavailable(
    b_sdp_fixture: dict[str, Any],
) -> None:
    prob = CanonicalSDPProblem.from_fixture_case(b_sdp_fixture["data"]["cases"]["T-SDP-B1"])
    res = solve(prob, backend="scipy_linprog")
    assert res.status == "failure"
    assert res.data is None
    assert res.error is not None
    assert res.error.code == "SOLVER_UNAVAILABLE"
    assert res.error.parameters["reason"] == "unsupported_psd"


@pytest.mark.parametrize("backend_name", ["clarabel_direct", "clarabel_cvxpy"])
def test_t_sdp_c1_3x3_slater_and_zero_duality_gap(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
    backend_name: str,
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-C1"]
    tols = b_sdp_fixture["tolerances"]
    prob = CanonicalSDPProblem.from_fixture_case(case)

    # Auditar ponto interior de Slater da fixture
    slater_res = verify(
        prob,
        {"x": case["expected"]["slater_x"], "solver_status": "unknown"},
    )
    assert slater_res.data is not None
    assert slater_res.data["audit_feasibility"] == "strictly_feasible"

    res = solve(prob, backend=backend_name)
    assert res.status == "success"
    _assert_schema_valid(res.to_dict(), "result.schema.json", schema_registry)
    d = res.data
    assert d is not None
    assert d["solver_status"] == "optimal"
    assert d["certificate_status"] == "validated_dual"
    assert d["residuals"]["duality_gap_rel"] <= tols["gap_tol"]
    np.testing.assert_allclose(np.asarray(d["x"]["data"]), np.array(case["expected"]["x_opt"]), atol=tols["primal_tol"])
    assert math.isclose(float(d["objective"]), float(case["expected"]["obj_opt"]), abs_tol=tols["gap_tol"])


# ---------------------------------------------------------------------------
# 3. Nível D: Estabilização contínua, D-estabilidade, BRL H-infinito, TS/PDC
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("feedback_sign", ["positive", "negative"])
def test_t_sdp_d1_continuous_stabilization_and_fixture_oracle(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
    feedback_sign: str,
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-D1"]
    tols = b_sdp_fixture["tolerances"]
    A = tensor_to_array(case["A"])
    B = tensor_to_array(case["B"])
    alpha = float(case["alpha"])
    plant = StateSpace(A, B, np.eye(2), np.zeros((2, 1)), dt=None, id="d1-plant", revision=2)

    prob = continuous_stabilization_lmi(plant, alpha=alpha, feedback_sign=feedback_sign)
    res = solve(prob, backend="clarabel_direct")
    assert res.status == "success"
    rec = recover_controller(prob, res, plant=plant)
    assert rec.status in ("success", "warning")
    _assert_schema_valid(rec.to_dict(), "result.schema.json", schema_registry)
    assert rec.data is not None
    assert rec.data["controller_validity"] == "verified_under_assumptions"

    ctrl = StateFeedbackController.from_dict(rec.data["controller"])
    _assert_schema_valid(ctrl.to_dict(), "controller.schema.json", schema_registry)
    assert ctrl.feedback_sign == feedback_sign

    Acl = get_closed_loop_matrix(plant, ctrl)
    assert float(np.max(np.real(np.linalg.eigvals(Acl)))) < -alpha

    # Auditar também a solução analítica (Q_lmi, Y) registrada na fixture ouro
    if feedback_sign == "positive":
        Q_fx = tensor_to_array(case["Q_lmi"])
        Y_fx = tensor_to_array(case["Y"])
        K_fx = tensor_to_array(case["K"])
        rec_fx = recover_controller(prob, {"Q": Q_fx, "Y": Y_fx}, plant=plant)
        assert rec_fx.data is not None
        assert rec_fx.data["controller_validity"] == "verified_under_assumptions"
        np.testing.assert_allclose(tensor_to_array(rec_fx.data["K"]), K_fx, atol=tols["gain_tol"])

    # Rejeitar StateSpace discreto
    plant_disc = StateSpace(A, B, np.eye(2), np.zeros((2, 1)), dt=0.1)
    with pytest.raises(UnsupportedModelError):
        continuous_stabilization_lmi(plant_disc, alpha=alpha)


@pytest.mark.parametrize("backend_name", ["clarabel_direct", "clarabel_cvxpy"])
def test_t_sdp_d2_hinf_brl_fixed_minimize_and_fixture_oracle(
    b_sdp_fixture: dict[str, Any],
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
    backend_name: str,
) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-D2"]
    tols = b_sdp_fixture["tolerances"]
    A = tensor_to_array(case["A"])
    B1 = tensor_to_array(case["B1"])
    B2 = tensor_to_array(case["B2"])
    C1 = tensor_to_array(case["C1"])
    D11 = tensor_to_array(case["D11"])
    D12 = tensor_to_array(case["D12"])
    gamma_fx = float(case["gamma"])

    # 1. Modo gamma fixo = 3.0
    prob_fix = hinf_brl_lmi(A, B1, B2, C1, D11, D12, gamma=gamma_fx, feedback_sign="positive")
    res_fix = solve(prob_fix, backend=backend_name)
    assert res_fix.status == "success"
    rec_fix = recover_controller(prob_fix, res_fix)
    assert rec_fix.data is not None
    assert rec_fix.data["controller_validity"] == "verified_under_assumptions"
    assert rec_fix.diagnostics["sampled_hinf_is_not_rigorous_certificate"] is True
    assert float(rec_fix.data["sampled_hinf_norm_max"]) < gamma_fx

    # 2. Modo minimização de gamma
    prob_min = hinf_brl_lmi(A, B1, B2, C1, D11, D12, gamma=None, feedback_sign="positive")
    res_min = solve(prob_min, backend=backend_name)
    assert res_min.status == "success"
    rec_min = recover_controller(prob_min, res_min)
    _assert_schema_valid(rec_min.to_dict(), "result.schema.json", schema_registry)
    assert rec_min.data is not None
    assert rec_min.data["controller_validity"] == "verified_under_assumptions"
    gamma_opt = float(rec_min.data["gamma"])
    assert 0.0 < gamma_opt < gamma_fx
    assert float(rec_min.data["sampled_hinf_norm_max"]) < gamma_opt

    # 3. Auditar solução explícita (Q_lmi, Y) da fixture ouro
    if backend_name == "clarabel_direct":
        Q_fx = tensor_to_array(case["Q_lmi"])
        Y_fx = tensor_to_array(case["Y"])
        K_fx = tensor_to_array(case["K"])
        rec_fx = recover_controller(prob_fix, {"Q": Q_fx, "Y": Y_fx})
        assert rec_fx.data is not None
        assert rec_fx.data["controller_validity"] == "verified_under_assumptions"
        np.testing.assert_allclose(tensor_to_array(rec_fx.data["K"]), K_fx, atol=tols["gain_tol"])


def test_regional_pole_placement_disk_and_halfplane() -> None:
    A = np.array([[0.0, 1.0], [-2.0, 0.5]])
    B = np.array([[0.0], [1.0]])
    plant = StateSpace(A, B, np.eye(2), np.zeros((2, 1)), dt=None)

    prob = regional_pole_placement_lmi(plant, radius=5.0, alpha=1.0, feedback_sign="negative")
    res = solve(prob, backend="clarabel_direct")
    assert res.status == "success"
    rec = recover_controller(prob, res, plant=plant)
    assert rec.data is not None
    assert rec.data["controller_validity"] == "verified_under_assumptions"
    ctrl = StateFeedbackController.from_dict(rec.data["controller"])
    eigs_cl = np.linalg.eigvals(get_closed_loop_matrix(plant, ctrl))
    assert float(np.max(np.abs(eigs_cl))) < 5.0
    assert float(np.max(np.real(eigs_cl))) < -1.0

    # Região impossível: |lambda| < 1.0 e Re(lambda) < -2.0 -> infactível certificado
    prob_empty = regional_pole_placement_lmi(plant, radius=1.0, alpha=2.0)
    res_empty = solve(prob_empty, backend="clarabel_direct")
    assert res_empty.data is not None
    assert res_empty.data["solver_status"] == "primal_infeasible"
    assert res_empty.data["certificate_status"] == "validated_infeasibility"


def test_ts_pdc_synthesis_cross_terms_and_polytopic_rejection(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    # Sistema TS de 2 regras onde B_1 e B_2 possuem sinais opostos e matrizes acopladas:
    # A_1 + B_1 K_2 pode ser individualmente instável enquanto G_12 + G_21 < 0 garante estabilidade global!
    v1 = {
        "vertex_id": "rule_1",
        "A": np.array([[1.0, 2.0], [-1.0, -2.0]]),
        "B": np.array([[1.0], [0.0]]),
        "C": np.eye(2),
        "D": np.zeros((2, 1)),
    }
    v2 = {
        "vertex_id": "rule_2",
        "A": np.array([[1.0, 2.0], [-1.0, -2.0]]),
        "B": np.array([[0.5], [1.0]]),
        "C": np.eye(2),
        "D": np.zeros((2, 1)),
    }

    ts_measured = TSStateSpace(
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
        id="ts-plant-pdc",
        revision=1,
    )

    prob = ts_pdc_stabilization_lmi(ts_measured, alpha=0.2, feedback_sign="positive")
    res = solve(prob, backend="clarabel_direct")
    assert res.status == "success"
    rec = recover_controller(prob, res, plant=ts_measured)
    _assert_schema_valid(rec.to_dict(), "result.schema.json", schema_registry)
    assert rec.data is not None
    assert rec.data["controller_validity"] == "verified_under_assumptions"

    pdc_ctrl = PDCController.from_dict(rec.data["controller"])
    _assert_schema_valid(pdc_ctrl.to_dict(), "controller.schema.json", schema_registry)
    assert pdc_ctrl.n_rules == 2

    # Checar também que o verificador/recuperador aceita caso explícito em que A_1 + B_1 K_2 é instável
    # mas G_11 < 0, G_22 < 0 e G_12 + G_21 < 0 são todos estritamente negativos!
    Q_test = np.eye(2)
    v1_cross = {
        "vertex_id": "r1",
        "A": np.array([[-1.0, 0.0], [0.0, -1.0]]),
        "B": np.array([[1.0], [0.0]]),
        "C": np.eye(2),
        "D": np.zeros((2, 1)),
    }
    v2_cross = {
        "vertex_id": "r2",
        "A": np.array([[-3.0, 0.0], [0.0, -1.0]]),
        "B": np.array([[2.0], [0.0]]),
        "C": np.eye(2),
        "D": np.zeros((2, 1)),
    }
    ts_cross2 = TSStateSpace(
        [v1_cross, v2_cross],
        kind="ts_measured",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["x1"], "sum_to_one_domain": True},
        premise_availability={
            "mode": "all_measured",
            "measured_premises": ["x1"],
            "unmeasured_premises": [],
            "estimator_required_for_pdc": False,
        },
        domain={"bounds": {"x1": [-1.0, 1.0]}},
        id="ts-cross2",
        revision=0,
    )
    prob_cross2 = ts_pdc_stabilization_lmi(ts_cross2, alpha=0.0, feedback_sign="positive")
    K1_c = np.array([[-1.5, 0.0]])
    K2_c = np.array([[1.2, 0.0]])
    assert float(np.max(np.real(np.linalg.eigvals(v1_cross["A"] + v1_cross["B"] @ K2_c)))) > 0.1  # A1+B1 K2 instável!
    x_cross = pack_variables_to_x(prob_cross2, {"Q": Q_test, "Y_0": K1_c @ Q_test, "Y_1": K2_c @ Q_test})
    rec_cross = recover_controller(prob_cross2, {"x": x_cross, "solver_status": "optimal"}, plant=ts_cross2)
    assert rec_cross.data is not None
    assert rec_cross.data["controller_validity"] == "verified_under_assumptions"

    # Rejeição obrigatória de polytopic_uncertain para PDC
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

    # Rejeição obrigatória de ts_partially_observed sem estimador
    ts_part = TSStateSpace(
        [v1, v2],
        kind="ts_partially_observed",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["x1", "x2"], "sum_to_one_domain": True},
        premise_availability={
            "mode": "partially_observed",
            "measured_premises": ["x1"],
            "unmeasured_premises": ["x2"],
            "estimator_required_for_pdc": True,
        },
        domain={"bounds": {"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]}},
    )
    with pytest.raises(HypothesisViolatedError):
        ts_pdc_stabilization_lmi(ts_part)


# ---------------------------------------------------------------------------
# 4. Testes negativos do Verificador Independente (5 dimensões / Tabela 6.3)
# ---------------------------------------------------------------------------


def test_verifier_rejects_fake_optimal_broken_dual_and_fake_certificates(
    b_sdp_fixture: dict[str, Any],
) -> None:
    c_b1 = b_sdp_fixture["data"]["cases"]["T-SDP-B1"]
    prob_b1 = CanonicalSDPProblem.from_fixture_case(c_b1)

    # 1. Falso optimal com x violando PSD ([[1, -2], [-2, 1]] tem min_eig = -1)
    bad_primal = verify(prob_b1, {"x": [-2.0], "objective": -2.0}, claimed_status="optimal")
    assert bad_primal.status == "inconclusive"
    assert bad_primal.data is not None
    assert bad_primal.data["solver_status"] == "optimal"
    assert bad_primal.data["audit_feasibility"] == "violated"
    assert bad_primal.data["certificate_status"] == "failed_validation"

    # 2. Primal válido, mas sem certificado dual -> nunca declara validated_dual!
    no_dual = verify(prob_b1, {"x": [-1.0]}, claimed_status="optimal")
    assert no_dual.status == "warning"
    assert no_dual.data is not None
    assert no_dual.data["certificate_status"] == "validated_primal"

    # 3. Primal válido com dual_Z quebrado (indefinido) -> failed_validation!
    bad_dual = verify(
        prob_b1,
        {"x": [-1.0], "dual_Z": [np.array([[0.5, 2.0], [2.0, 0.5]])]},
        claimed_status="optimal",
    )
    assert bad_dual.status == "inconclusive"
    assert bad_dual.data is not None
    assert bad_dual.data["certificate_status"] == "failed_validation"

    # 4. optimal_inaccurate preservado sem promoção silenciosa para optimal
    inacc = verify(
        prob_b1,
        {"x": [-1.0], "dual_Z": [np.array([[0.5, 0.5], [0.5, 0.5]])]},
        claimed_status="optimal_inaccurate",
    )
    assert inacc.status == "warning"
    assert inacc.data is not None
    assert inacc.data["solver_status"] == "optimal_inaccurate"
    assert inacc.data["conditioning"]["loss_of_significance"] is True

    # 5. Falso primal_infeasible sem Farkas ou com Farkas inválido (Z=0 ou <F0,Z> > 0)
    c_a2 = b_sdp_fixture["data"]["cases"]["T-SDP-A2"]
    prob_a2 = CanonicalSDPProblem.from_fixture_case(c_a2)
    no_farkas = verify(prob_a2, {}, claimed_status="primal_infeasible")
    assert no_farkas.status == "inconclusive"
    assert no_farkas.data is not None
    assert no_farkas.data["audit_feasibility"] == "inconclusive"
    assert no_farkas.data["certificate_status"] == "not_available"

    bad_farkas = verify(
        prob_a2,
        {"farkas_Z": [np.array([[1.0, 0.0], [0.0, 0.0]])]},  # <F1, Z> = 1 != 0 e <F0, Z> = -2
        claimed_status="primal_infeasible",
    )
    assert bad_farkas.status == "inconclusive"
    assert bad_farkas.data is not None
    assert bad_farkas.data["certificate_status"] == "failed_validation"

    # 6. Falso dual_infeasible com direção recessiva inválida (c^T d > 0)
    c_a3 = b_sdp_fixture["data"]["cases"]["T-SDP-A3"]
    prob_a3 = CanonicalSDPProblem.from_fixture_case(c_a3)
    bad_ray = verify(
        prob_a3,
        {"recession_direction": [1.0], "feasible_x0": [0.0]},
        claimed_status="dual_infeasible",
    )
    assert bad_ray.status == "inconclusive"
    assert bad_ray.data is not None
    assert bad_ray.data["certificate_status"] == "failed_validation"

    # 7. recover_controller bloqueia solução violada
    prob_d1 = continuous_stabilization_lmi(np.array([[0.0, 1.0], [2.0, -1.0]]), np.array([[0.0], [1.0]]), alpha=1.0)
    rec_bad = recover_controller(prob_d1, {"x": np.zeros(prob_d1.n_vars), "solver_status": "optimal"})
    assert rec_bad.status == "failure"
    assert rec_bad.error is not None
    assert rec_bad.error.code == "HYPOTHESIS_VIOLATED"
    assert rec_bad.diagnostics["controller_validity"] == "violated"

    # Conferir que constantes da Tabela 6.3 cobrem o conjunto normativo completo
    assert set(SOLVER_STATUSES) == {
        "optimal",
        "optimal_inaccurate",
        "primal_infeasible",
        "dual_infeasible",
        "max_iterations",
        "numerical_error",
        "unknown",
    }
    assert set(AUDIT_FEASIBILITY_LEVELS) == {"strictly_feasible", "approximately_feasible", "violated", "inconclusive"}
    assert set(CERTIFICATE_STATUSES) == {
        "validated_primal",
        "validated_dual",
        "validated_infeasibility",
        "validated_unboundedness",
        "not_available",
        "failed_validation",
    }
    assert set(CONTROLLER_VALIDITY_LEVELS) == {
        "verified_under_assumptions",
        "violated",
        "not_applicable",
        "not_assessed",
    }


# ---------------------------------------------------------------------------
# 5. Backends, capacidades, Gate G-0B e invariantes arquiteturais
# ---------------------------------------------------------------------------


def test_capabilities_unavailable_educational_and_gate_0b(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    all_caps = describe_solver_capabilities("all")
    assert set(all_caps.keys()) == {
        "native_primal_dual",
        "clarabel_direct",
        "clarabel_cvxpy",
        "scipy_linprog",
        "educational_barrier",
        "unavailable",
    }
    assert all_caps["clarabel_direct"]["psd"] is True
    assert all_caps["clarabel_cvxpy"]["psd"] is True
    assert all_caps["scipy_linprog"]["psd"] is False
    assert all_caps["scipy_linprog"]["lp"] is True
    assert all_caps["educational_barrier"]["experimental"] is True
    assert all_caps["unavailable"]["available"] is False

    x = sdpvar((1, 1), name="x")
    prob = compile(x, [x >= 1.0])

    # UnavailableBackend retorna SOLVER_UNAVAILABLE com razão estruturada
    res_unav = solve(prob, backend=UnavailableBackend(reason="missing_wasm_wheel"))
    assert res_unav.status == "failure"
    assert res_unav.error is not None
    assert res_unav.error.code == "SOLVER_UNAVAILABLE"
    assert res_unav.error.parameters["reason"] == "missing_wasm_wheel"

    # EducationalBarrierBackend isolado sem callable retorna SOLVER_UNAVAILABLE
    res_edu_none = solve(prob, backend=EducationalBarrierBackend())
    assert res_edu_none.status == "failure"
    assert res_edu_none.error is not None
    assert res_edu_none.error.code == "SOLVER_UNAVAILABLE"
    assert res_edu_none.error.parameters["reason"] == "experimental_not_registered"

    # Quando injetado um callable experimental, ainda passa por verify() e emite warning experimental
    def _mock_edu_solver(p: CanonicalSDPProblem, opts: Any) -> dict[str, Any]:
        return {"solver_status": "optimal", "x": np.array([1.0]), "objective": 1.0}

    res_edu_ok = solve(prob, backend=EducationalBarrierBackend(solver_fn=_mock_edu_solver))
    assert res_edu_ok.status == "warning"
    assert res_edu_ok.assumptions["experimental"] is True
    assert res_edu_ok.data is not None
    assert res_edu_ok.data["certificate_status"] == "validated_primal"

    # Ensaio do Gate G-0B completo
    gate_res = run_gate_0b_assay()
    _assert_schema_valid(gate_res.to_dict(), "result.schema.json", schema_registry)
    assert gate_res.data is not None
    assert gate_res.data["gate"] == "G-0B"
    assert gate_res.data["overall_passed"] is True
    assert gate_res.data["backends"]["native_primal_dual"]["passed"] is True


def test_architectural_invariants_no_linalg_inv_and_no_experimental_import() -> None:
    """Garante por inspeção AST que control_lab/optimization/ não usa inv() nem importa experimental/."""
    py_files = sorted(OPT_DIR.rglob("*.py"))
    assert len(py_files) >= 10

    for fpath in py_files:
        src = fpath.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(fpath))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "experimental" not in alias.name, f"Import proibido de experimental em {fpath}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "experimental" not in mod, f"ImportFrom proibido de experimental em {fpath}: {mod}"
            elif isinstance(node, ast.Attribute):
                if node.attr == "inv":
                    # Proibir qualquer chamada *.inv(...) (ex.: np.linalg.inv, scipy.linalg.inv)
                    assert not (
                        isinstance(node.value, ast.Attribute) and node.value.attr == "linalg"
                    ), f"Uso proibido de linalg.inv detectado em {fpath}"


def test_scipy_linprog_vs_clarabel_with_eq_ineq_and_diagonal_blocks() -> None:
    x = sdpvar((2, 1), name="x")
    # Bloco diagonal 2x2: diag(x0 - 1, x1 - 2) >= 0, igualdade x0 + x1 == 5, desigualdade 2*x0 <= 7
    D_blk = bmat([[x[0, 0] - 1.0, 0.0], [0.0, x[1, 0] - 2.0]])
    prob = compile(
        2.0 * x[0, 0] + 3.0 * x[1, 0],
        [
            psd(D_blk, name="diag_blk"),
            linear_eq(x[0, 0] + x[1, 0], 5.0, name="sum_eq"),
            linear_ineq(2.0 * x[0, 0], 7.0, name="x0_ub"),
        ],
        scaling={"normalize_blocks": True},
        name="diag_eq_ineq",
    )
    res_sp = solve(prob, backend="scipy_linprog")
    res_cl = solve(prob, backend="clarabel_direct")
    assert res_sp.status == "success"
    assert res_cl.status == "success"
    assert res_sp.data is not None and res_cl.data is not None
    assert res_sp.data["certificate_status"] == "validated_dual"
    assert res_cl.data["certificate_status"] == "validated_dual"
    np.testing.assert_allclose(
        np.asarray(res_sp.data["x"]["data"]),
        np.asarray(res_cl.data["x"]["data"]),
        atol=1e-6,
    )
    assert math.isclose(float(res_sp.data["objective"]), float(res_cl.data["objective"]), abs_tol=1e-6)


def test_hinf_brl_optimality_vs_infeasibility_below_gamma_star(b_sdp_fixture: dict[str, Any]) -> None:
    case = b_sdp_fixture["data"]["cases"]["T-SDP-D2"]
    A = tensor_to_array(case["A"])
    B1 = tensor_to_array(case["B1"])
    B2 = tensor_to_array(case["B2"])
    C1 = tensor_to_array(case["C1"])
    D11 = tensor_to_array(case["D11"])
    D12 = tensor_to_array(case["D12"])

    p_min = hinf_brl_lmi(A, B1, B2, C1, D11, D12, gamma=None)
    r_dir = solve(p_min, backend="clarabel_direct")
    r_cvx = solve(p_min, backend="clarabel_cvxpy")
    assert r_dir.status == "success" and r_cvx.status == "success"
    assert r_dir.data is not None and r_cvx.data is not None
    g_dir = float(r_dir.data["objective"])
    g_cvx = float(r_cvx.data["objective"])
    assert math.isclose(g_dir, g_cvx, rel_tol=1e-5, abs_tol=1e-5)

    # Abaixo de gamma* (ex: 0.8 * g_dir), o problema com gamma fixo deve ser infactível certificado
    p_low = hinf_brl_lmi(A, B1, B2, C1, D11, D12, gamma=0.8 * g_dir)
    r_low = solve(p_low, backend="clarabel_direct")
    assert r_low.data is not None
    assert r_low.data["solver_status"] == "primal_infeasible"
    assert r_low.data["certificate_status"] == "validated_infeasibility"


def test_ts_pdc_negative_feedback_and_exported_script_execution(
    b_sdp_fixture: dict[str, Any],
) -> None:
    v1 = {
        "vertex_id": "rule_1",
        "A": np.array([[0.5, 1.0], [-1.0, -2.0]]),
        "B": np.array([[1.0], [0.5]]),
        "C": np.eye(2),
        "D": np.zeros((2, 1)),
    }
    v2 = {
        "vertex_id": "rule_2",
        "A": np.array([[0.2, 1.0], [-1.5, -2.0]]),
        "B": np.array([[0.8], [1.0]]),
        "C": np.eye(2),
        "D": np.zeros((2, 1)),
    }
    ts = TSStateSpace(
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
        domain={"bounds": {"x1": [-1.0, 1.0]}},
        id="ts-neg",
        revision=1,
    )
    prob = ts_pdc_stabilization_lmi(ts, alpha=0.1, feedback_sign="negative", q_bounds=(1e-3, 100.0))
    res = solve(prob, backend="clarabel_direct")
    rec = recover_controller(prob, res, plant=ts)
    assert rec.status == "success"
    assert rec.data is not None
    assert rec.data["controller_validity"] == "verified_under_assumptions"
    assert rec.data["feedback_sign"] == "negative"

    # Executar de fato o script CPython exportado para T-SDP-B1 em subprocesso isolado
    import subprocess
    import sys

    prob_b1 = CanonicalSDPProblem.from_fixture_case(b_sdp_fixture["data"]["cases"]["T-SDP-B1"])
    script = prob_b1.export_cpython_script("clarabel_direct")
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert "Solved" in proc.stdout
    obj_line = [ln for ln in proc.stdout.splitlines() if ln.startswith("obj_val:")][0]
    assert math.isclose(float(obj_line.split(":", 1)[1].strip()), -1.0, abs_tol=1e-6)


def test_verifier_incomplete_duals_mixed_and_pure_lp_bug_f6_01(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    # 1. Problema misto (PSD + Eq + Ineq) com ponto estritamente factível x = [2.0, 3.0]
    x = sdpvar((2, 1), name="x")
    D_blk = bmat([[x[0, 0] - 1.0, 0.0], [0.0, x[1, 0] - 2.0]])
    prob_mixed = compile(
        2.0 * x[0, 0] + 3.0 * x[1, 0],
        [
            psd(D_blk, name="diag_blk"),
            linear_eq(x[0, 0] + x[1, 0], 5.0, name="sum_eq"),
            linear_ineq(x[0, 0], 4.0, name="x0_ub"),
        ],
        name="mixed_psd_eq_ineq",
    )
    x_feas = np.array([2.0, 3.0])

    # Omissão de dual_eq (dual_Z e dual_ineq presentes) -> sem KeyError, status='inconclusive'
    res_no_eq = verify(
        prob_mixed,
        {
            "x": x_feas,
            "dual_Z": [np.eye(2)],
            "dual_ineq": np.array([0.0]),
        },
        claimed_status="optimal",
    )
    _assert_schema_valid(res_no_eq.to_dict(), "result.schema.json", schema_registry)
    assert res_no_eq.status == "inconclusive"
    assert res_no_eq.data is not None
    assert res_no_eq.data["certificate_status"] == "failed_validation"
    assert res_no_eq.data["audit_feasibility"] == "strictly_feasible"
    assert res_no_eq.data["dual_objective"] is None

    # Omissão de dual_ineq (dual_Z e dual_eq presentes) -> sem KeyError, status='inconclusive'
    res_no_ineq = verify(
        prob_mixed,
        {
            "x": x_feas,
            "dual_Z": [np.eye(2)],
            "dual_eq": np.array([-2.0]),
        },
        claimed_status="optimal",
    )
    _assert_schema_valid(res_no_ineq.to_dict(), "result.schema.json", schema_registry)
    assert res_no_ineq.status == "inconclusive"
    assert res_no_ineq.data is not None
    assert res_no_ineq.data["certificate_status"] == "failed_validation"
    assert res_no_ineq.data["audit_feasibility"] == "strictly_feasible"
    assert res_no_ineq.data["dual_objective"] is None

    # 2. LP puro (sem blocos PSD, apenas Eq + Ineq) com dual incompleto
    y = sdpvar((2, 1), name="y")
    prob_lp = compile(
        y[0, 0] + 2.0 * y[1, 0],
        [
            linear_eq(y[0, 0] + y[1, 0], 4.0, name="lp_eq"),
            linear_ineq(-y[0, 0], -1.0, name="y0_lb"),
            linear_ineq(-y[1, 0], -1.0, name="y1_lb"),
        ],
        name="pure_lp_eq_ineq",
    )
    y_feas = np.array([2.0, 2.0])

    res_lp_no_eq = verify(
        prob_lp,
        {"x": y_feas, "dual_ineq": np.array([0.0, 0.0])},
        claimed_status="optimal",
    )
    assert res_lp_no_eq.status == "inconclusive"
    assert res_lp_no_eq.data is not None
    assert res_lp_no_eq.data["certificate_status"] == "failed_validation"
    assert res_lp_no_eq.data["audit_feasibility"] == "strictly_feasible"

    res_lp_no_ineq = verify(
        prob_lp,
        {"x": y_feas, "dual_eq": np.array([-1.0])},
        claimed_status="optimal",
    )
    assert res_lp_no_ineq.status == "inconclusive"
    assert res_lp_no_ineq.data is not None
    assert res_lp_no_ineq.data["certificate_status"] == "failed_validation"
    assert res_lp_no_ineq.data["audit_feasibility"] == "strictly_feasible"


def test_obs_f6_01_02_03_regressions() -> None:
    # OBS-F6-01: LP puro primal_infeasible com fallback dual_eq/dual_ineq -> farkas_eq/farkas_ineq
    z = sdpvar((1, 1), name="z")
    prob_lp_inf = compile(
        z,
        [
            linear_eq(z, 1.0, name="z_eq_1"),
            linear_ineq(-z, -2.0, name="z_ge_2"),  # -z <= -2  (H=[[-1]], h=[-2])
        ],
        name="pure_lp_infeasible",
    )
    # Condição adjunta Farkas sem PSD: -(E^T nu) - (H^T lam) = 0 -> -1*nu - (-1)*lam = 0 -> nu = lam = 1
    # Contradição: d*nu + h*lam = 1*1 + (-2)*1 = -1 < 0
    res_farkas_lp = verify(
        prob_lp_inf,
        {"dual_eq": np.array([1.0]), "dual_ineq": np.array([1.0])},
        claimed_status="primal_infeasible",
    )
    assert res_farkas_lp.status == "success"
    assert res_farkas_lp.data is not None
    assert res_farkas_lp.data["certificate_status"] == "validated_infeasibility"
    assert res_farkas_lp.data["audit_feasibility"] == "violated"

    # OBS-F6-02: linear_eq com np.float64(0.0) e expressão matricial
    Q = sdpvar((2, 2), name="Q", symmetric=True)
    con_eq_r = linear_eq(Q, np.float64(0.0), name="q_zero_r")
    con_eq_l = linear_eq(np.float64(0.0), Q, name="q_zero_l")
    assert con_eq_r.expr.shape == (2, 2)
    assert con_eq_l.expr.shape == (2, 2)

    # OBS-F6-03: StateSpace puramente estático (n_states == 0) ou sem entradas rejeitado com ValidationError
    static_plant = StateSpace(
        np.empty((0, 0)),
        np.empty((0, 1)),
        np.empty((1, 0)),
        np.array([[2.0]]),
        dt=None,
    )
    with pytest.raises(ValidationError):
        continuous_stabilization_lmi(static_plant)
    with pytest.raises(ValidationError):
        regional_pole_placement_lmi(static_plant, radius=2.0)

    no_input_plant = StateSpace(
        np.array([[-1.0]]),
        np.empty((1, 0)),
        np.array([[1.0]]),
        np.empty((1, 0)),
        dt=None,
    )
    with pytest.raises(ValidationError):
        continuous_stabilization_lmi(no_input_plant)


