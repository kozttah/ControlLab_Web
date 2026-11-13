"""Testes unitários, contratuais, metamórficos e de oráculo da Frente F2 para WP-02-F2-CARE-LQR.

Cobre obrigatoriamente:
- T-CARE-01: Benchmark analítico B-CARE-02 (duplo integrador 2x1), sinal negative/positive e schema Result/Controller
- T-CARE-02: Benchmark numérico B-CARE-12x3 (12 estados, 3 entradas, modo instável em A), oráculo e integral de custo LQR
- T-CARE-03: Violações PBH (não estabilizável, não detectável), matrizes Q/R inválidas e incompatibilidade de domínio dt
- T-CARE-04: Teste metamórfico de similaridade (x_tilde_0 = T @ x0) para T bem condicionada e mal condicionada (com aviso)
- DARE / LQR discreto, LQI contínuo/discreto, PBH/SVD/gramianos, Lyapunov/Sylvester, alocação de polos,
  observador de Luenberger, filtro de Kalman, LQG (DynamicController + princípio da separação com D != 0),
  discretize_zoh e simulate_lti (expm/FOH/solve_ivp preservando timestamps originais).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core import (
    DynamicController,
    StateFeedbackController,
    StateSpace,
    TransferFunction,
    get_closed_loop_matrix,
    interconnect,
    pair_to_complex,
    restore_model,
    tensor_to_array,
)
from control_lab.diagnostics import (
    DimensionMismatchError,
    HypothesisViolatedError,
    Result,
    UnsupportedModelError,
    ValidationError,
)
from control_lab.statespace import (
    analyze,
    check_pbh,
    design_kalman,
    design_lqg,
    design_lqi,
    design_lqr,
    design_observer,
    design_pole_placement,
    discretize_zoh,
    gramians,
    simulate_lti,
    solve_care,
    solve_dare,
    solve_lyapunov,
    solve_sylvester,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
FIXTURES_DIR = ROOT / "contracts" / "fixtures"


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


def _assert_schema_valid(
    instance: dict[str, Any],
    schema_name: str,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    registry, schemas = schema_registry
    Draft202012Validator(schemas[schema_name], registry=registry).validate(instance)


def _match_poles_max_diff(eigs_a: np.ndarray, eigs_b: np.ndarray) -> float:
    import scipy.optimize

    cost = np.abs(eigs_a[:, None] - eigs_b[None, :])
    r, c = scipy.optimize.linear_sum_assignment(cost)
    return float(np.max(cost[r, c]))


# ---------------------------------------------------------------------------
# 1. T-CARE-01: Benchmark analítico B-CARE-02
# ---------------------------------------------------------------------------


def test_t_care_01_analytical_b_care_02_and_feedback_signs(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    fx = json.loads((FIXTURES_DIR / "B-CARE-02.json").read_text(encoding="utf-8"))
    d = fx["data"]
    tol = fx["tolerances"]

    A = tensor_to_array(d["A"])
    B = tensor_to_array(d["B"])
    C = tensor_to_array(d["C"])
    D = tensor_to_array(d["D"])
    Q = tensor_to_array(d["Q"])
    R = tensor_to_array(d["R"])
    x0 = tensor_to_array(d["x0"])

    P_exp = tensor_to_array(d["expected"]["P"])
    K_exp = tensor_to_array(d["expected"]["K"])
    poles_exp = pair_to_complex(d["expected"]["closed_loop_poles"])
    cost_exp = float(d["expected"]["optimal_cost"])

    plant = StateSpace(A, B, C, D, dt=None, id="b-care-02", revision=1)

    # solve_care direto
    res_care = solve_care(plant, Q, R, x0=x0)
    assert isinstance(res_care, Result)
    assert res_care.status == "success"
    _assert_schema_valid(res_care.to_dict(), "result.schema.json", schema_registry)
    assert Result.from_json(res_care.to_json()).to_dict() == res_care.to_dict()

    P_got = tensor_to_array(res_care.data["P"])  # type: ignore[index]
    K_got = tensor_to_array(res_care.data["K"])  # type: ignore[index]
    poles_got = pair_to_complex(res_care.data["closed_loop_poles"])  # type: ignore[index]

    np.testing.assert_allclose(P_got, P_exp, atol=tol["P_atol"])
    np.testing.assert_allclose(K_got, K_exp, atol=tol["K_atol"])
    assert _match_poles_max_diff(poles_got, poles_exp) <= tol["poles_atol"]
    assert abs(float(res_care.data["optimal_cost"]) - cost_exp) <= tol["cost_atol"]  # type: ignore[index]
    assert res_care.diagnostics["care_residual_rel"] <= tol["rCARE_max"]
    assert res_care.diagnostics["symmetry_error"] <= tol["symmetry_error_max"]
    assert res_care.assumptions["stabilizable"] is True
    assert res_care.assumptions["detectable"] is True
    assert res_care.assumptions["R_positive_definite"] is True

    # design_lqr com feedback_sign="negative" e "positive"
    res_neg = design_lqr(plant, Q, R, x0=x0, feedback_sign="negative")
    assert res_neg.status == "success"
    _assert_schema_valid(res_neg.to_dict(), "result.schema.json", schema_registry)
    ctrl_neg = StateFeedbackController.from_dict(res_neg.data["controller"])  # type: ignore[index]
    _assert_schema_valid(ctrl_neg.to_dict(), "controller.schema.json", schema_registry)
    assert ctrl_neg.feedback_sign == "negative"
    np.testing.assert_allclose(ctrl_neg.K, K_exp, atol=tol["K_atol"])
    np.testing.assert_allclose(get_closed_loop_matrix(plant, ctrl_neg), A - B @ K_exp, atol=1e-12)

    res_pos = design_lqr(plant, Q, R, x0=x0, feedback_sign="positive")
    assert res_pos.status == "success"
    ctrl_pos = StateFeedbackController.from_dict(res_pos.data["controller"])  # type: ignore[index]
    _assert_schema_valid(ctrl_pos.to_dict(), "controller.schema.json", schema_registry)
    assert ctrl_pos.feedback_sign == "positive"
    np.testing.assert_allclose(ctrl_pos.K, -K_exp, atol=tol["K_atol"])
    np.testing.assert_allclose(get_closed_loop_matrix(plant, ctrl_pos), A - B @ K_exp, atol=1e-12)
    assert _match_poles_max_diff(
        pair_to_complex(res_pos.data["closed_loop_poles"]),  # type: ignore[index]
        poles_exp,
    ) <= tol["poles_atol"]


# ---------------------------------------------------------------------------
# 2. T-CARE-02: Benchmark numérico B-CARE-12x3 e verificação integral de custo
# ---------------------------------------------------------------------------


def test_t_care_02_numerical_b_care_12x3_and_trajectory_cost_oracle(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    fx = json.loads((FIXTURES_DIR / "B-CARE-12x3.json").read_text(encoding="utf-8"))
    d = fx["data"]
    tol = fx["tolerances"]

    A = tensor_to_array(d["A"])
    B = tensor_to_array(d["B"])
    C = tensor_to_array(d["C"])
    D = tensor_to_array(d["D"])
    Q = tensor_to_array(d["Q"])
    R = tensor_to_array(d["R"])
    x0 = tensor_to_array(d["x0"])

    P_exp = tensor_to_array(d["expected"]["P"])
    K_exp = tensor_to_array(d["expected"]["K"])
    poles_exp = pair_to_complex(d["expected"]["closed_loop_poles"])
    cost_exp = float(d["expected"]["optimal_cost"])

    plant = StateSpace(A, B, C, D, dt=None, id="b-care-12x3", revision=3)
    assert float(np.max(np.real(plant.poles()))) > 0.1  # modo instável confirmado

    res = design_lqr(plant, Q, R, x0=x0)
    assert res.status == "success"
    _assert_schema_valid(res.to_dict(), "result.schema.json", schema_registry)
    assert res.provenance.model_revision == 3

    P_got = tensor_to_array(res.data["P"])  # type: ignore[index]
    K_got = tensor_to_array(res.data["K"])  # type: ignore[index]
    poles_got = pair_to_complex(res.data["closed_loop_poles"])  # type: ignore[index]

    assert res.diagnostics["care_residual_rel"] <= tol["rCARE_max"]
    assert res.diagnostics["symmetry_error"] <= tol["symmetry_error_max"]
    assert res.diagnostics["min_eig_P"] > 0.0
    assert res.diagnostics["max_real_open_loop"] > 0.1
    assert res.diagnostics["max_real_closed_loop"] < -0.05

    np.testing.assert_allclose(P_got, P_exp, rtol=tol["P_rel_tol"], atol=1e-12)
    np.testing.assert_allclose(K_got, K_exp, rtol=tol["K_rel_tol"], atol=1e-12)
    assert _match_poles_max_diff(poles_got, poles_exp) <= tol["poles_atol"]
    assert abs(float(res.data["optimal_cost"]) - cost_exp) / cost_exp <= tol["cost_rel_tol"]  # type: ignore[index]

    ctrl = restore_model(res.data["controller"])  # type: ignore[index]
    assert isinstance(ctrl, StateFeedbackController)
    cl_ss = StateSpace.from_dict(res.data["closed_loop"])  # type: ignore[index]
    assert float(np.max(np.real(cl_ss.poles()))) < -0.05

    # Oráculo físico independente: integrar J = int_0^T (x^T Q x + u^T R u) dt ao longo da trajetória
    t_grid = np.linspace(0.0, 40.0, 4001)
    sim_res = simulate_lti(cl_ss, t_grid, x0=x0, method="expm")
    assert sim_res.status == "success"
    x_traj = tensor_to_array(sim_res.data["x"])  # type: ignore[index]
    u_traj = -(x_traj @ K_got.T)
    integrand = np.einsum("ki,ij,kj->k", x_traj, Q, x_traj) + np.einsum("ki,ij,kj->k", u_traj, R, u_traj)
    j_numeric = float(np.trapezoid(integrand, t_grid))
    assert abs(j_numeric - cost_exp) / cost_exp < 1e-4


# ---------------------------------------------------------------------------
# 3. T-CARE-03: Violações PBH, matrizes Q/R inválidas e incompatibilidade de domínio
# ---------------------------------------------------------------------------


def test_t_care_03_pbh_violations_invalid_qr_and_domain_rejection(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # 3a. Modo instável não controlável (lambda = +1.0)
    A_unstab = np.array([[1.0, 0.0], [0.0, -2.0]])
    B_unstab = np.array([[0.0], [1.0]])
    Q_eye = np.eye(2)
    R_eye = np.eye(1)

    res_unstab = design_lqr(A_unstab, B_unstab, Q_eye, R_eye)
    assert res_unstab.status == "failure"
    assert res_unstab.data is None
    assert res_unstab.error is not None
    assert res_unstab.error.code == "HYPOTHESIS_VIOLATED"
    _assert_schema_valid(res_unstab.to_dict(), "result.schema.json", schema_registry)
    with pytest.raises(HypothesisViolatedError):
        solve_care(A_unstab, B_unstab, Q_eye, R_eye, raise_on_error=True)

    # 3b. Modo marginal não controlável (lambda = 0.0)
    A_marg = np.array([[0.0, 0.0], [0.0, -1.0]])
    res_marg = solve_care(A_marg, B_unstab, Q_eye, R_eye)
    assert res_marg.status == "failure"
    assert res_marg.error is not None and res_marg.error.code == "HYPOTHESIS_VIOLATED"

    # 3c. Modo instável não detectável em Q^{1/2} (inclusive Q = C^T C rotacionada)
    A_det = np.array([[2.0, 0.0], [0.0, -1.0]])
    B_det = np.array([[1.0], [1.0]])
    Q_undet = np.array([[0.0, 0.0], [0.0, 1.0]])
    res_undet = design_lqr(A_det, B_det, Q_undet, R_eye)
    assert res_undet.status == "failure"
    assert res_undet.error is not None and res_undet.error.code == "HYPOTHESIS_VIOLATED"
    with pytest.raises(HypothesisViolatedError):
        design_lqr(A_det, B_det, Q_undet, R_eye, raise_on_error=True)

    # 3d. Contraste positivo: modo ESTÁVEL não controlável (lambda = -3.0) É estabilizável!
    A_stab_unctrb = np.array([[-3.0, 0.0], [0.0, 1.0]])
    B_stab_unctrb = np.array([[0.0], [1.0]])
    res_ok = design_lqr(A_stab_unctrb, B_stab_unctrb, Q_eye, R_eye)
    assert res_ok.status == "success"
    assert res_ok.assumptions["controllable"] is False
    assert res_ok.assumptions["stabilizable"] is True
    assert res_ok.diagnostics["max_real_closed_loop"] < 0.0

    # 3e. Matrizes R inválidas (singular, zero, indefinida, assimétrica) e Q inválida (indefinida, assimétrica)
    A_ok = np.array([[0.0, 1.0], [-2.0, -3.0]])
    B_ok = np.array([[0.0, 1.0], [1.0, 0.0]])
    for bad_R in (
        np.array([[1.0, 1.0], [1.0, 1.0]]),  # singular
        np.array([[0.0, 0.0], [0.0, 1.0]]),  # semidefinida singular
        np.array([[1.0, 0.0], [0.0, -0.5]]),  # indefinida
        np.array([[1.0, 2.0], [0.0, 1.0]]),  # assimétrica
    ):
        r_bad = solve_care(A_ok, B_ok, Q_eye, bad_R)
        assert r_bad.status == "failure"
        assert r_bad.error is not None and r_bad.error.code == "HYPOTHESIS_VIOLATED"
        with pytest.raises(HypothesisViolatedError):
            solve_care(A_ok, B_ok, Q_eye, bad_R, raise_on_error=True)

    for bad_Q in (
        np.array([[-1.0, 0.0], [0.0, 1.0]]),  # indefinida
        np.array([[1.0, 1.5], [0.0, 1.0]]),  # assimétrica
    ):
        q_bad = solve_care(A_ok, B_ok, bad_Q, np.eye(2))
        assert q_bad.status == "failure"
        assert q_bad.error is not None and q_bad.error.code == "HYPOTHESIS_VIOLATED"

    # NaN / Inf rejeitados
    with pytest.raises(ValidationError):
        solve_care(A_ok, B_ok, np.array([[float("nan"), 0.0], [0.0, 1.0]]), np.eye(2), raise_on_error=True)

    # 3f. Domínio contínuo vs discreto
    ss_cont = StateSpace(A_ok, B_ok, np.eye(2), np.zeros((2, 2)), dt=None)
    ss_disc = StateSpace(np.array([[0.8, 0.1], [0.0, 0.9]]), B_ok, np.eye(2), np.zeros((2, 2)), dt=0.1)

    with pytest.raises(UnsupportedModelError):
        solve_care(ss_disc, Q_eye, np.eye(2), raise_on_error=True)
    with pytest.raises(UnsupportedModelError):
        design_lqr(ss_disc, Q_eye, np.eye(2), method="care", raise_on_error=True)
    with pytest.raises(UnsupportedModelError):
        solve_dare(ss_cont, Q_eye, np.eye(2), raise_on_error=True)
    with pytest.raises(UnsupportedModelError):
        design_lqr(ss_cont, Q_eye, np.eye(2), method="dare", raise_on_error=True)

    # Tipo não StateSpace (TransferFunction) rejeitado
    tf = TransferFunction([1.0], [1.0, 2.0])
    with pytest.raises(UnsupportedModelError):
        design_lqr(tf, [[1.0]], [[1.0]], raise_on_error=True)


# ---------------------------------------------------------------------------
# 4. T-CARE-04: Teste metamórfico de similaridade (x_tilde_0 = T @ x0)
# ---------------------------------------------------------------------------


def test_t_care_04_similarity_invariance_well_and_ill_conditioned() -> None:
    fx = json.loads((FIXTURES_DIR / "B-CARE-12x3.json").read_text(encoding="utf-8"))
    d = fx["data"]
    A = tensor_to_array(d["A"])
    B = tensor_to_array(d["B"])
    C = tensor_to_array(d["C"])
    D = tensor_to_array(d["D"])
    Q = tensor_to_array(d["Q"])
    R = tensor_to_array(d["R"])
    x0 = tensor_to_array(d["x0"]).ravel()
    n = A.shape[0]

    base_res = solve_care(A, B, Q, R, x0=x0)
    assert base_res.status == "success"
    P_base = tensor_to_array(base_res.data["P"])  # type: ignore[index]
    K_base = tensor_to_array(base_res.data["K"])  # type: ignore[index]
    poles_base = pair_to_complex(base_res.data["closed_loop_poles"])  # type: ignore[index]
    cost_base = float(base_res.data["optimal_cost"])  # type: ignore[index]

    rng = np.random.default_rng(12345)
    U_t, _ = np.linalg.qr(rng.standard_normal((n, n)))
    V_t, _ = np.linalg.qr(rng.standard_normal((n, n)))

    # Caso 1: Transformação T bem condicionada (kappa(T) = 5)
    s_good = np.linspace(1.0, 5.0, n)
    T_good = U_t @ np.diag(s_good) @ V_t.T

    A_t1 = np.linalg.solve(T_good.T, (T_good @ A).T).T
    B_t1 = T_good @ B
    C_t1 = np.linalg.solve(T_good.T, C.T).T
    Z_q1 = np.linalg.solve(T_good.T, Q)
    Q_t1 = 0.5 * (np.linalg.solve(T_good.T, Z_q1.T).T + np.linalg.solve(T_good.T, Z_q1.T))
    x0_t1 = T_good @ x0  # Obrigatório: x_tilde_0 = T @ x0

    plant_t1 = StateSpace(A_t1, B_t1, C_t1, D, dt=None)
    res_t1 = design_lqr(plant_t1, Q_t1, R, x0=x0_t1)
    assert res_t1.status == "success"

    P_t1 = tensor_to_array(res_t1.data["P"])  # type: ignore[index]
    K_t1 = tensor_to_array(res_t1.data["K"])  # type: ignore[index]
    poles_t1 = pair_to_complex(res_t1.data["closed_loop_poles"])  # type: ignore[index]
    cost_t1 = float(res_t1.data["optimal_cost"])  # type: ignore[index]

    # Invariância de autovalores de malha fechada e custo ótimo x0^T P x0
    assert _match_poles_max_diff(poles_t1, poles_base) < 1e-9
    assert abs(cost_t1 - cost_base) / cost_base < 1e-10

    # Covariância algébrica P_tilde = T^{-T} P T^{-1} e K_tilde = K T^{-1}
    Z_p1 = np.linalg.solve(T_good.T, P_base)
    P_expected_t1 = np.linalg.solve(T_good.T, Z_p1.T).T
    K_expected_t1 = np.linalg.solve(T_good.T, K_base.T).T
    np.testing.assert_allclose(P_t1, P_expected_t1, rtol=1e-9, atol=1e-11)
    np.testing.assert_allclose(K_t1, K_expected_t1, rtol=1e-9, atol=1e-11)

    # Caso 2: Transformação T com condicionamento alto (kappa(T) = 5e4 => kappa(Q_tilde) ~ 2.5e9) -> aviso explícito
    s_bad = np.geomspace(1.0, 5e4, n)
    T_bad = U_t @ np.diag(s_bad) @ V_t.T

    A_t2 = np.linalg.solve(T_bad.T, (T_bad @ A).T).T
    B_t2 = T_bad @ B
    Z_q2 = np.linalg.solve(T_bad.T, Q)
    Q_t2 = np.linalg.solve(T_bad.T, Z_q2.T).T
    Q_t2 = 0.5 * (Q_t2 + Q_t2.T)
    x0_t2 = T_bad @ x0  # Obrigatório: x_tilde_0 = T @ x0

    res_t2 = solve_care(A_t2, B_t2, Q_t2, R, x0=x0_t2)
    assert res_t2.status == "warning"
    assert len(res_t2.warnings) >= 1
    assert res_t2.diagnostics["care_residual_rel"] <= 1e-7

    poles_t2 = pair_to_complex(res_t2.data["closed_loop_poles"])  # type: ignore[index]
    cost_t2 = float(res_t2.data["optimal_cost"])  # type: ignore[index]
    assert _match_poles_max_diff(poles_t2, poles_base) < 1e-5
    assert abs(cost_t2 - cost_base) / cost_base < 1e-6


# ---------------------------------------------------------------------------
# 5. DARE, LQR Discreto, LQI Contínuo/Discreto
# ---------------------------------------------------------------------------


def test_dare_discrete_lqr_and_bellman_cost(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    ss_cont = StateSpace([[0.0, 1.0], [0.0, 0.0]], [[0.0], [1.0]], [[1.0, 0.0]], [[0.0]], dt=None)
    zoh_res = discretize_zoh(ss_cont, dt=0.1)
    assert zoh_res.status == "success"
    ss_d = StateSpace.from_dict(zoh_res.data["model"])  # type: ignore[index]
    assert ss_d.dt == 0.1

    Q = np.diag([4.0, 1.0])
    R = np.array([[0.5]])
    x0 = np.array([1.5, -0.5])

    res_dare = solve_dare(ss_d, Q, R, x0=x0)
    assert res_dare.status == "success"
    _assert_schema_valid(res_dare.to_dict(), "result.schema.json", schema_registry)
    assert res_dare.diagnostics["dare_residual_rel"] <= 1e-12
    assert res_dare.diagnostics["symmetry_error"] <= 1e-14
    assert res_dare.diagnostics["spectral_radius_closed_loop"] < 1.0

    P_d = tensor_to_array(res_dare.data["P"])  # type: ignore[index]
    K_d = tensor_to_array(res_dare.data["K"])  # type: ignore[index]
    cost_d = float(res_dare.data["optimal_cost"])  # type: ignore[index]

    res_lqr_d = design_lqr(ss_d, Q, R, x0=x0, feedback_sign="positive")
    assert res_lqr_d.status == "success"
    ctrl_d = StateFeedbackController.from_dict(res_lqr_d.data["controller"])  # type: ignore[index]
    np.testing.assert_allclose(ctrl_d.K, -K_d, atol=1e-12)

    # Custo de Bellman discreto sum(x_k^T Q x_k + u_k^T R u_k) == x0^T P x0
    cl_d = StateSpace.from_dict(res_lqr_d.data["closed_loop"])  # type: ignore[index]
    t_d = np.arange(0, 300) * 0.1
    sim_d = simulate_lti(cl_d, t_d, x0=x0)
    assert sim_d.status == "success"
    x_k = tensor_to_array(sim_d.data["x"])  # type: ignore[index]
    u_k = -(x_k @ K_d.T)
    j_bellman = float(np.sum(np.einsum("ki,ij,kj->k", x_k, Q, x_k) + np.einsum("ki,ij,kj->k", u_k, R, u_k)))
    assert abs(j_bellman - cost_d) / cost_d < 1e-8


def test_design_lqi_continuous_and_discrete_zero_steady_state_error() -> None:
    # Contínuo MIMO/SISO com D != 0
    plant_c = StateSpace([[-1.0, 0.5], [0.0, -2.0]], [[0.0], [1.0]], [[1.0, 0.0]], [[0.1]], dt=None)
    res_lqi_c = design_lqi(plant_c, Q=np.diag([2.0, 1.0]), Q_i=np.array([[10.0]]), R=[[0.5]])
    assert res_lqi_c.status == "success"
    cl_c = StateSpace.from_dict(res_lqi_c.data["closed_loop"])  # type: ignore[index]
    assert float(np.max(np.real(cl_c.poles()))) < 0.0

    t_c = np.linspace(0.0, 20.0, 201)
    r_c = np.ones((t_c.size, 1)) * 2.5
    sim_c = simulate_lti(cl_c, t_c, u=r_c)
    assert sim_c.status == "success"
    y_c = tensor_to_array(sim_c.data["y"])  # type: ignore[index]
    np.testing.assert_allclose(y_c[-1, 0], 2.5, atol=1e-4)

    # Discreto LQI
    plant_d = StateSpace.from_dict(discretize_zoh(plant_c, dt=0.1).data["model"])  # type: ignore[index]
    res_lqi_d = design_lqi(plant_d, Q=np.diag([2.0, 1.0, 10.0]), R=[[0.5]])
    assert res_lqi_d.status == "success"
    cl_d = StateSpace.from_dict(res_lqi_d.data["closed_loop"])  # type: ignore[index]
    assert float(np.max(np.abs(cl_d.poles()))) < 1.0

    t_d = np.arange(0, 250) * 0.1
    r_d = np.ones((t_d.size, 1)) * (-1.5)
    sim_d = simulate_lti(cl_d, t_d, u=r_d)
    y_d = tensor_to_array(sim_d.data["y"])  # type: ignore[index]
    np.testing.assert_allclose(y_d[-1, 0], -1.5, atol=1e-4)

    # Planta com zero de transmissão na origem s=0: s / (s+1) => D=1, C=-1, A=-1, B=1 -> não estabilizável com integrador
    plant_zero0 = StateSpace([[-1.0]], [[1.0]], [[-1.0]], [[1.0]], dt=None)
    res_bad_lqi = design_lqi(plant_zero0, Q=[[1.0]], Q_i=[[1.0]], R=[[1.0]])
    assert res_bad_lqi.status == "failure"
    assert res_bad_lqi.error is not None and res_bad_lqi.error.code == "HYPOTHESIS_VIOLATED"


# ---------------------------------------------------------------------------
# 6. Análise estrutural (analyze, check_pbh, gramians) e Lyapunov / Sylvester
# ---------------------------------------------------------------------------


def test_analyze_check_pbh_and_gramians_continuous_and_discrete() -> None:
    plant = StateSpace(
        A=[[-1.0, 0.5], [0.0, -3.0]],
        B=[[0.0], [2.0]],
        C=[[1.0, 0.0]],
        D=[[0.0]],
        dt=None,
    )
    res_an = analyze(plant)
    assert res_an.status == "success"
    assert res_an.assumptions["asymptotically_stable"] is True
    assert res_an.assumptions["controllable"] is True
    assert res_an.assumptions["observable"] is True
    assert res_an.diagnostics["ctrb_rank"] == 2
    assert res_an.diagnostics["obsv_rank"] == 2

    Wc = tensor_to_array(res_an.data["Wc"])  # type: ignore[index]
    Wo = tensor_to_array(res_an.data["Wo"])  # type: ignore[index]
    np.testing.assert_allclose(plant.A @ Wc + Wc @ plant.A.T + plant.B @ plant.B.T, 0.0, atol=1e-13)
    np.testing.assert_allclose(plant.A.T @ Wo + Wo @ plant.A + plant.C.T @ plant.C, 0.0, atol=1e-13)
    assert np.all(tensor_to_array(res_an.data["hankel_singular_values"]) > 0.0)  # type: ignore[index]

    # Discreto estável: gramianos discretos
    plant_d = StateSpace.from_dict(discretize_zoh(plant, dt=0.2).data["model"])  # type: ignore[index]
    res_gd = gramians(plant_d)
    assert res_gd.status == "success"
    Wc_d = tensor_to_array(res_gd.data["Wc"])  # type: ignore[index]
    Wo_d = tensor_to_array(res_gd.data["Wo"])  # type: ignore[index]
    np.testing.assert_allclose(plant_d.A @ Wc_d @ plant_d.A.T - Wc_d + plant_d.B @ plant_d.B.T, 0.0, atol=1e-13)
    np.testing.assert_allclose(plant_d.A.T @ Wo_d @ plant_d.A - Wo_d + plant_d.C.T @ plant_d.C, 0.0, atol=1e-13)

    # Sistema instável ou marginal: gramianos devem falhar sem fabricar matriz falsa
    plant_marg = StateSpace([[0.0, 1.0], [0.0, -1.0]], [[0.0], [1.0]], [[1.0, 0.0]], [[0.0]], dt=None)
    res_gm = gramians(plant_marg)
    assert res_gm.status == "failure"
    assert res_gm.error is not None and res_gm.error.code == "HYPOTHESIS_VIOLATED"

    # check_pbh com autovalor repetido defeituoso não controlável
    pbh_rep = check_pbh(np.eye(2), B=np.array([[1.0], [0.0]]))
    assert pbh_rep.status == "success"
    assert pbh_rep.data["controllable"] is False  # type: ignore[index]
    assert pbh_rep.data["stabilizable"] is False  # type: ignore[index]

    # Planta estática n=0 em analyze
    ss_static = TransferFunction([3.0], [1.0]).to_state_space()
    res_st = analyze(ss_static)
    assert res_st.status == "success"
    assert res_st.data["asymptotically_stable"] is True  # type: ignore[index]


def test_lyapunov_and_sylvester_solvers() -> None:
    A = np.array([[-2.0, 0.5], [0.0, -3.0]])
    Q = np.array([[2.0, 0.5], [0.5, 4.0]])
    res_c = solve_lyapunov(A, Q, domain="continuous")
    assert res_c.status == "success"
    X_c = tensor_to_array(res_c.data["X"])  # type: ignore[index]
    np.testing.assert_allclose(A @ X_c + X_c @ A.T + Q, 0.0, atol=1e-13)
    assert res_c.diagnostics["residual_rel"] <= 1e-13

    Ad = np.array([[0.5, 0.2], [0.0, 0.7]])
    res_d = solve_lyapunov(Ad, Q, domain="discrete")
    assert res_d.status == "success"
    X_d = tensor_to_array(res_d.data["X"])  # type: ignore[index]
    np.testing.assert_allclose(Ad @ X_d @ Ad.T - X_d + Q, 0.0, atol=1e-13)
    assert res_d.diagnostics["residual_rel"] <= 1e-13

    # Operador de Lyapunov singular (autovalor em 0) deve falhar
    res_sing = solve_lyapunov(np.array([[0.0, 1.0], [0.0, -1.0]]), Q, domain="continuous")
    assert res_sing.status == "failure"
    assert res_sing.error is not None and res_sing.error.code == "HYPOTHESIS_VIOLATED"

    # Q não simétrica rejeitada quando require_symmetric=True
    res_asym = solve_lyapunov(A, np.array([[1.0, 2.0], [0.0, 1.0]]))
    assert res_asym.status == "failure"
    assert res_asym.error is not None and res_asym.error.code == "HYPOTHESIS_VIOLATED"

    # Sylvester retangular 2x3
    B_s = np.array([[-1.0, 0.2, 0.0], [0.0, -4.0, 0.1], [0.0, 0.0, -5.0]])
    Q_s = np.array([[1.0, -2.0, 0.5], [3.0, 0.0, -1.0]])
    res_sylv = solve_sylvester(A, B_s, Q_s)
    assert res_sylv.status == "success"
    X_s = tensor_to_array(res_sylv.data["X"])  # type: ignore[index]
    assert X_s.shape == (2, 3)
    np.testing.assert_allclose(A @ X_s + X_s @ B_s, Q_s, atol=1e-13)
    assert res_sylv.diagnostics["residual_rel"] <= 1e-13

    # Sylvester singular sigma(A) intersecciona sigma(-B)
    res_sylv_bad = solve_sylvester(np.array([[-2.0]]), np.array([[2.0]]), np.array([[1.0]]))
    assert res_sylv_bad.status == "failure"
    assert res_sylv_bad.error is not None and res_sylv_bad.error.code == "HYPOTHESIS_VIOLATED"


# ---------------------------------------------------------------------------
# 7. Alocação de polos, Observador, Kalman e LQG (DynamicController + D != 0)
# ---------------------------------------------------------------------------


def test_pole_placement_and_observer_siso_mimo_and_repeated() -> None:
    # SISO com polos repetidos (Ackermann) e conjugados
    plant = StateSpace([[0.0, 1.0], [0.0, 0.0]], [[0.0], [1.0]], [[1.0, 0.0]], [[0.0]], dt=None)
    res_rep = design_pole_placement(plant, [-2.0, -2.0])
    assert res_rep.status == "success"
    np.testing.assert_allclose(tensor_to_array(res_rep.data["K"]), [[4.0, 4.0]], atol=1e-12)  # type: ignore[index]

    res_cplx = design_pole_placement(plant, [-1.5 + 2.0j, -1.5 - 2.0j], feedback_sign="positive")
    assert res_cplx.status == "success"
    ctrl_cplx = StateFeedbackController.from_dict(res_cplx.data["controller"])  # type: ignore[index]
    Acl = get_closed_loop_matrix(plant, ctrl_cplx)
    assert _match_poles_max_diff(np.linalg.eigvals(Acl), np.array([-1.5 + 2.0j, -1.5 - 2.0j])) < 1e-11

    # Polos não conjugados -> ValidationError
    with pytest.raises(ValidationError):
        design_pole_placement(plant, [-1.0 + 1.0j, -2.0], raise_on_error=True)

    # MIMO
    A_m = np.array([[0.0, 1.0, 0.0], [-1.0, -0.5, 0.2], [0.0, 0.0, 1.0]])
    B_m = np.array([[0.0, 0.0], [1.0, 0.5], [0.0, 1.0]])
    C_m = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    plant_m = StateSpace(A_m, B_m, C_m, np.zeros((2, 2)))
    target_p = np.array([-2.0, -3.0 + 1.0j, -3.0 - 1.0j])
    res_m = design_pole_placement(plant_m, target_p)
    assert res_m.status == "success"
    assert res_m.diagnostics["pole_placement_error"] < 1e-10

    # Observador MIMO + simulação de convergência de estado estimado x_hat -> x
    obs_poles = np.array([-5.0, -6.0 + 2.0j, -6.0 - 2.0j])
    res_obs = design_observer(plant_m, obs_poles)
    assert res_obs.status == "success"
    L = tensor_to_array(res_obs.data["L"])  # type: ignore[index]
    assert _match_poles_max_diff(np.linalg.eigvals(A_m - L @ C_m), obs_poles) < 1e-10

    # 1) Observador desacoplado em grade fina (dt=0.01) para planta estabilizada
    obs_sys = StateSpace.from_dict(res_obs.data["observer_system"])  # type: ignore[index]
    assert obs_sys.n_states == 3
    K_m = tensor_to_array(res_m.data["K"])  # type: ignore[index]
    plant_stab = StateSpace(A_m - B_m @ K_m, B_m, C_m, np.zeros((2, 2)))
    t = np.linspace(0.0, 4.0, 401)
    u_in = np.column_stack([np.sin(t), np.cos(t)])
    x0_true = np.array([1.0, -0.5, 0.8])
    sim_plant = simulate_lti(plant_stab, t, u=u_in, x0=x0_true)
    y_meas = tensor_to_array(sim_plant.data["y"])  # type: ignore[index]
    x_true = tensor_to_array(sim_plant.data["x"])  # type: ignore[index]
    obs_stab = StateSpace(
        A_m - L @ C_m,
        np.hstack([B_m, L]),
        np.eye(3),
        np.zeros((3, 4)),
    )
    u_eff = u_in - x_true @ K_m.T
    sim_obs = simulate_lti(obs_stab, t, u=np.hstack([u_eff, y_meas]), x0=np.zeros(3))
    x_hat = tensor_to_array(sim_obs.data["y"])  # type: ignore[index]
    np.testing.assert_allclose(x_hat[-1], x_true[-1], atol=1e-5)

    # 2) Sistema acoplado contínuo exato [x; x_hat] mesmo para planta instável em malha aberta
    A_coupled = np.block([[A_m, np.zeros((3, 3))], [L @ C_m, A_m - L @ C_m]])
    B_coupled = np.vstack([B_m, B_m])
    sys_coupled = StateSpace(A_coupled, B_coupled, np.eye(6), np.zeros((6, 2)))
    sim_coupled = simulate_lti(
        sys_coupled,
        np.linspace(0.0, 4.0, 41),
        u=lambda tau: np.array([np.sin(tau), np.cos(tau)]),
        x0=np.concatenate([x0_true, np.zeros(3)]),
        method="dop853",
        rtol=1e-11,
        atol=1e-13,
    )
    x_c = tensor_to_array(sim_coupled.data["x"])  # type: ignore[index]
    np.testing.assert_allclose(x_c[-1, :3], x_c[-1, 3:], atol=1e-7)

    # Polos complexos conjugados repetidos em SISO (Ackermann) -> K exato, polos perturbados por O(sqrt(eps))
    A4 = np.array([[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0], [-1.0, -2.0, -3.0, -4.0]])
    B4 = np.array([[0.0], [0.0], [0.0], [1.0]])
    p4 = np.array([-2.0 + 1.0j, -2.0 - 1.0j, -2.0 + 1.0j, -2.0 - 1.0j])
    res_p4 = design_pole_placement(A4, B4, p4)
    assert res_p4.status in ("success", "warning")
    np.testing.assert_allclose(tensor_to_array(res_p4.data["K"]), [[24.0, 38.0, 23.0, 4.0]], atol=1e-12)  # type: ignore[index]
    assert res_p4.diagnostics["pole_placement_error"] < 1e-6


def test_kalman_and_lqg_separation_principle_with_nonzero_feedthrough(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # Planta MIMO contínua com D != 0
    A = np.array([[0.0, 1.0, 0.0], [0.2, -0.5, 0.4], [-0.3, 0.0, -1.2]])
    B = np.array([[0.0, 0.0], [1.0, 0.2], [0.0, 1.0]])
    C = np.array([[1.0, 0.0, 0.5], [0.0, 0.0, 1.0]])
    D = np.array([[0.15, -0.05], [0.0, 0.25]])
    plant = StateSpace(A, B, C, D, dt=None, id="mimo-dp", revision=2)

    Q = np.diag([3.0, 1.0, 2.0])
    R = np.diag([0.5, 0.8])
    G = np.array([[0.5, 0.0], [1.0, 0.0], [0.0, 1.0]])
    Qn = np.diag([1.5, 0.7])
    Rn = np.diag([0.1, 0.2])

    for sign in ("negative", "positive"):
        res_lqg = design_lqg(plant, Q, R, Qn, Rn, G=G, feedback_sign=sign)
        assert res_lqg.status == "success"
        _assert_schema_valid(res_lqg.to_dict(), "result.schema.json", schema_registry)
        ctrl = DynamicController.from_dict(res_lqg.data["controller"])  # type: ignore[index]
        _assert_schema_valid(ctrl.to_dict(), "controller.schema.json", schema_registry)
        assert ctrl.feedback_sign == sign

        cl_ss = interconnect(plant, ctrl)
        reg_poles = pair_to_complex(res_lqg.data["regulator_poles"])  # type: ignore[index]
        obs_poles = pair_to_complex(res_lqg.data["observer_poles"])  # type: ignore[index]
        expected_cl_poles = np.concatenate([reg_poles, obs_poles])
        assert _match_poles_max_diff(cl_ss.poles(), expected_cl_poles) < 1e-10
        assert res_lqg.diagnostics["separation_pole_diff"] < 1e-10
        assert float(np.max(np.real(cl_ss.poles()))) < 0.0

        # Simulação em malha fechada LQG converge para zero a partir de x0 != 0
        t_sim = np.linspace(0.0, 20.0, 201)
        sim_cl = simulate_lti(cl_ss, t_sim, x0=np.array([1.0, -0.5, 0.8, 0.0, 0.0, 0.0]))
        x_cl = tensor_to_array(sim_cl.data["x"])  # type: ignore[index]
        assert float(np.linalg.norm(x_cl[-1])) < 1e-4

    # LQG Discreto também preserva princípio da separação com D != 0
    plant_d = StateSpace.from_dict(discretize_zoh(plant, dt=0.1).data["model"])  # type: ignore[index]
    res_lqg_d = design_lqg(plant_d, Q, R, Qn, Rn, G=G)
    assert res_lqg_d.status == "success"
    assert res_lqg_d.diagnostics["separation_pole_diff"] < 1e-10
    cl_d = StateSpace.from_dict(res_lqg_d.data["closed_loop"])  # type: ignore[index]
    assert float(np.max(np.abs(cl_d.poles()))) < 1.0

    # Kalman em sistema não detectável deve falhar
    res_kf_bad = design_kalman(np.array([[1.0, 0.0], [0.0, -2.0]]), np.array([[0.0, 1.0]]), np.eye(2), np.eye(1))
    assert res_kf_bad.status == "failure"
    assert res_kf_bad.error is not None and res_kf_bad.error.code == "HYPOTHESIS_VIOLATED"


# ---------------------------------------------------------------------------
# 8. Simulação LTI: preservação de timestamps, paridade entre métodos e higiene
# ---------------------------------------------------------------------------


def test_simulate_lti_timestamps_preservation_and_method_parity(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # Sistema contínuo: x' = -2 x + u, x(0) = 1, u(t) = sin(t)
    plant = StateSpace([[-2.0]], [[1.0]], [[3.0]], [[0.5]], dt=None)
    # Grade propositalmente NÃO uniforme (Seção 5.1: timestamps originais preservados!)
    t_nonuniform = np.array([0.0, 0.03, 0.09, 0.15, 0.25, 0.4, 0.7, 1.1, 1.6, 2.0])
    u_fn = lambda tau: np.sin(tau)

    sim_ivp = simulate_lti(plant, t_nonuniform, u=u_fn, x0=[1.0], method="dop853", rtol=1e-11, atol=1e-13)
    assert sim_ivp.status == "success"
    _assert_schema_valid(sim_ivp.to_dict(), "result.schema.json", schema_registry)
    t_out = tensor_to_array(sim_ivp.data["t"])  # type: ignore[index]
    np.testing.assert_array_equal(t_out, t_nonuniform)

    # Solução analítica exata de x' + 2x = sin(t), x(0)=1:
    # x(t) = (6/5)*exp(-2t) + (2/5)*sin(t) - (1/5)*cos(t)
    x_exact = (1.2 * np.exp(-2.0 * t_nonuniform) + 0.4 * np.sin(t_nonuniform) - 0.2 * np.cos(t_nonuniform)).reshape(-1, 1)
    x_ivp = tensor_to_array(sim_ivp.data["x"])  # type: ignore[index]
    y_ivp = tensor_to_array(sim_ivp.data["y"])  # type: ignore[index]
    np.testing.assert_allclose(x_ivp, x_exact, atol=1e-10)
    np.testing.assert_allclose(y_ivp, 3.0 * x_exact + 0.5 * np.sin(t_nonuniform).reshape(-1, 1), atol=1e-10)

    # Paridade expm vs solve_ivp para entrada degrau em grade não uniforme
    u_step = np.ones((t_nonuniform.size, 1)) * 2.0
    sim_expm = simulate_lti(plant, t_nonuniform, u=u_step, x0=[1.0], method="expm")
    sim_step_ivp = simulate_lti(plant, t_nonuniform, u=u_step, x0=[1.0], method="rk45", rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(
        tensor_to_array(sim_expm.data["x"]),  # type: ignore[index]
        tensor_to_array(sim_step_ivp.data["x"]),  # type: ignore[index]
        atol=1e-9,
    )

    # Planta estática n=0: saída direta y = D u
    ss_static = TransferFunction([2.5], [1.0]).to_state_space()
    sim_st = simulate_lti(ss_static, [0.0, 0.5, 1.0], u=[1.0, 2.0, -3.0])
    assert sim_st.status == "success"
    _assert_schema_valid(sim_st.to_dict(), "result.schema.json", schema_registry)
    np.testing.assert_allclose(tensor_to_array(sim_st.data["y"]), [[2.5], [5.0], [-7.5]], atol=1e-14)  # type: ignore[index]

    # Sistema discreto rejeita grade incompatível com dt e discretize_zoh rejeita já-discreto
    plant_d = StateSpace([[0.5]], [[1.0]], [[1.0]], [[0.0]], dt=0.1)
    res_bad_t = simulate_lti(plant_d, np.array([0.0, 0.1, 0.25]))
    assert res_bad_t.status == "failure"
    assert res_bad_t.error is not None and res_bad_t.error.code == "HYPOTHESIS_VIOLATED"
    res_zoh_d = discretize_zoh(plant_d, dt=0.1)
    assert res_zoh_d.status == "failure"
    assert res_zoh_d.error is not None and res_zoh_d.error.code == "UNSUPPORTED_MODEL"

    # LQI com menos entradas (m=1) que saídas rastreadas (p=2) falha por PBH (não estabilizável)
    plant_underact = StateSpace(
        np.diag([-1.0, -2.0]),
        np.array([[1.0], [1.0]]),
        np.eye(2),
        np.zeros((2, 1)),
    )
    res_lqi_under = design_lqi(plant_underact, Q=np.eye(2), Q_i=np.eye(2), R=[[1.0]])
    assert res_lqi_under.status == "failure"
    assert res_lqi_under.error is not None and res_lqi_under.error.code == "HYPOTHESIS_VIOLATED"


def test_no_explicit_linalg_inv_in_statespace_package() -> None:
    import control_lab.statespace._utils as mod_u
    import control_lab.statespace.analysis as mod_a
    import control_lab.statespace.design as mod_d
    import control_lab.statespace.equations as mod_e
    import control_lab.statespace.simulation as mod_s

    for mod in (mod_u, mod_a, mod_d, mod_e, mod_s):
        src = inspect.getsource(mod)
        assert "linalg.inv" not in src
