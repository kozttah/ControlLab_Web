"""Independent F9 oracle audit for Phase 9 Cycle 2 (ADR-015: Single-Pass HSDE + Gondzio Correctors).

Must pass with ZERO skips in both `core_no_sdp` and `sdp_available` CI profiles.
When `clarabel` is installed, performs strict independent parity verification against
`clarabel_direct` without any tolerance relaxation.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np
import pytest

from control_lab.core.tensors import tensor_to_array
from control_lab.optimization import (
    CanonicalSDPProblem,
    SDPBlock,
    compile,
    continuous_stabilization_lmi,
    linear_ineq,
    recover_controller,
    sdpvar,
    solve,
    trace,
    verify,
)
from control_lab.optimization.backends.native_core import solve_native_raw
from control_lab.optimization.verification.gate0b import _build_gate_0b_suite


def _clarabel_available() -> bool:
    return importlib.util.find_spec("clarabel") is not None


def _extract_solution_for_verify(data: dict[str, Any]) -> dict[str, Any]:
    sol: dict[str, Any] = {"x": tensor_to_array(data["x"], expected_ndim=1, dtype="float64")}
    if data.get("dual_Z") is not None:
        sol["dual_Z"] = [
            tensor_to_array(z, expected_ndim=2, dtype="float64")
            for z in data["dual_Z"]
        ]
    if data.get("dual_eq") is not None:
        sol["dual_eq"] = tensor_to_array(data["dual_eq"], expected_ndim=1, dtype="float64")
    if data.get("dual_ineq") is not None:
        sol["dual_ineq"] = tensor_to_array(data["dual_ineq"], expected_ndim=1, dtype="float64")
    if data.get("objective") is not None:
        sol["objective"] = float(data["objective"])
    sol["solver_status"] = data.get("solver_status", "optimal")
    return sol


def _build_stabilization_problem(n: int, alpha: float = 0.25) -> tuple[CanonicalSDPProblem, np.ndarray, np.ndarray]:
    diag_vals = [-1.0 - 0.12 * i for i in range(n - 1)] + [0.45]
    A = np.diag(diag_vals).astype(np.float64)
    for i in range(n - 1):
        A[i, i + 1] = 0.18
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    B[-2, 0] = 0.25
    prob = continuous_stabilization_lmi(A, B, alpha=alpha)
    return prob, A, B


def _build_mixed_psd_and_lp_problem() -> CanonicalSDPProblem:
    rng = np.random.default_rng(9022)
    m = 8
    blocks: list[SDPBlock] = []
    for b in range(2):
        Q = rng.standard_normal((4, 4))
        F0 = 0.5 * (Q @ Q.T) * 0.12 - (1.55 + 0.2 * b) * np.eye(4, dtype=np.float64)
        F_terms: dict[int, np.ndarray] = {0: np.eye(4, dtype=np.float64)}
        for k in range(1, m):
            M = rng.standard_normal((4, 4)) * 0.14
            F_terms[k] = 0.5 * (M + M.T)
        blocks.append(SDPBlock(f"psd_{b}", F0, F_terms, n_vars=m))

    for k in range(1, m):
        blocks.append(
            SDPBlock(f"lp_lo_{k}", np.array([[1.6]], dtype=np.float64), {k: np.array([[1.0]])}, n_vars=m)
        )
        blocks.append(
            SDPBlock(f"lp_hi_{k}", np.array([[1.6]], dtype=np.float64), {k: np.array([[-1.0]])}, n_vars=m)
        )

    c = np.array([1.0, 0.25, -0.18, 0.12, -0.09, 0.07, -0.05, 0.04], dtype=np.float64)
    return CanonicalSDPProblem(c=c, blocks=blocks, name="f9_cycle2_mixed_psd_lp")


# ---------------------------------------------------------------------------
# 1. Feasible Control LMIs (Stabilization n=8/12, H-inf BRL, Mixed PSD+1D LP)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [8, 12])
def test_f9_cycle2_hsde_stabilization_lmi_oracle_and_parity(n: int) -> None:
    """Single-pass HSDE solves non-origin-feasible stabilization LMIs (n=8, 12) with 5D verify and Clarabel parity."""
    alpha = 0.25
    prob, A, B = _build_stabilization_problem(n=n, alpha=alpha)

    raw_hsde = solve_native_raw(prob, options={"use_hsde": True, "max_gondzio_correctors": 2})
    raw_p1p2 = solve_native_raw(prob, options={"use_hsde": False, "max_gondzio_correctors": 0})
    assert raw_hsde["solver_status"] == "optimal"
    assert raw_hsde["hsde_summary"]["executed"] is True
    assert raw_hsde["hsde_summary"]["hsde_certificate"] == "optimal"
    assert raw_hsde["phase1_summary"]["executed"] is False
    assert raw_hsde["factorizations"] < raw_p1p2["factorizations"]

    res = solve(prob, backend="native_primal_dual")
    assert res.status in ("success", "warning"), res.error
    assert res.diagnostics["hsde_summary"]["executed"] is True
    assert res.diagnostics["hsde_certificate"] == "optimal"
    assert res.data["certificate_status"] == "validated_dual"
    assert res.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    # Independent 5D verification on original problem
    audited = verify(prob, _extract_solution_for_verify(res.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"
    assert audited.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    # Independent closed-loop eigenvalue proof
    ctrl = recover_controller(prob, res)
    assert ctrl.data["controller_validity"] == "verified_under_assumptions"
    K = tensor_to_array(ctrl.data["K"], expected_ndim=2, dtype="float64")
    assert float(np.max(np.linalg.eigvals(A + B @ K).real)) < -alpha

    if _clarabel_available():
        res_cl = solve(prob, backend="clarabel_direct")
        assert res_cl.status in ("success", "warning"), res_cl.error
        assert res_cl.data["certificate_status"] == "validated_dual"
        assert abs(float(res.data["objective"]) - float(res_cl.data["objective"])) < 1e-5


def test_f9_cycle2_hsde_hinf_brl_and_gondzio_oracle() -> None:
    """Single-pass HSDE + Gondzio solves CTRL_BRL_D2_MIN with validated_dual, independent verify, and Clarabel parity."""
    suite = _build_gate_0b_suite()
    prob_brl = suite["CTRL_BRL_D2_MIN"]["problem"]

    res = solve(prob_brl, backend="native_primal_dual")
    assert res.status in ("success", "warning"), res.error
    hsde_summary = res.diagnostics["hsde_summary"]
    assert hsde_summary["executed"] is True
    assert hsde_summary["hsde_certificate"] == "optimal"
    assert hsde_summary["gondzio_correctors_accepted"] > 0
    assert res.data["certificate_status"] == "validated_dual"
    assert res.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    audited = verify(prob_brl, _extract_solution_for_verify(res.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"
    assert audited.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    if _clarabel_available():
        res_cl = solve(prob_brl, backend="clarabel_direct")
        assert res_cl.status in ("success", "warning"), res_cl.error
        assert res_cl.data["certificate_status"] == "validated_dual"
        assert abs(float(res.data["objective"]) - float(res_cl.data["objective"])) < 1e-5


def test_f9_cycle2_hsde_mixed_psd_and_lp_oracle() -> None:
    """Single-pass HSDE solves mixed 2x(4x4) PSD + 14x(1x1) LP cone with independent verify and Clarabel parity."""
    prob = _build_mixed_psd_and_lp_problem()

    res = solve(prob, backend="native_primal_dual")
    assert res.status in ("success", "warning"), res.error
    assert res.diagnostics["hsde_summary"]["executed"] is True
    assert res.diagnostics["hsde_certificate"] == "optimal"
    assert res.data["certificate_status"] == "validated_dual"
    assert res.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    audited = verify(prob, _extract_solution_for_verify(res.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"
    assert audited.data["residuals"]["duality_gap_rel"] < 1e-6
    assert audited.data["residuals"]["dual_stationarity_rel"] < 1e-6

    # Independent NumPy eigenvalue check on every block
    x_vec = tensor_to_array(res.data["x"], expected_ndim=1, dtype="float64")
    for blk in prob.blocks:
        min_eig = float(np.min(np.linalg.eigvalsh(blk.evaluate(x_vec))))
        assert min_eig >= -1e-7, f"Block {blk.name} violated: min_eig={min_eig}"

    if _clarabel_available():
        res_cl = solve(prob, backend="clarabel_direct")
        assert res_cl.status in ("success", "warning"), res_cl.error
        assert res_cl.data["certificate_status"] == "validated_dual"
        assert abs(float(res.data["objective"]) - float(res_cl.data["objective"])) < 1e-5


# ---------------------------------------------------------------------------
# 2. Strictly Infeasible LMIs (Rapid HSDE Farkas Termination + Clarabel Parity)
# ---------------------------------------------------------------------------


def test_f9_cycle2_hsde_strictly_infeasible_lmis_early_termination() -> None:
    """Contradictory PSD and impossible decay-rate LMIs terminate in <=15 iterations with Farkas certificate."""
    # Case 1: P >= 2I and I - P >= 0
    P = sdpvar((3, 3), name="P", symmetric=True)
    prob_contra = compile(
        trace(P),
        [P >= 2.0 * np.eye(3), np.eye(3) - P >= np.zeros((3, 3))],
        name="f9_contra_psd",
    )

    # Case 2: Impossible decay rate alpha=100 for unstable open-loop A with bounded Q
    A_unst = np.array([[2.0, 0.5], [0.0, 1.5]], dtype=np.float64)
    Q = sdpvar((2, 2), name="Q", symmetric=True)
    prob_decay = compile(
        0.0 * Q[0, 0],
        [
            Q >= np.eye(2),
            10.0 * np.eye(2) - Q >= np.zeros((2, 2)),
            -(A_unst @ Q + Q @ A_unst.T + 200.0 * Q) >= np.zeros((2, 2)),
        ],
        name="f9_impossible_decay",
    )

    for prob in (prob_contra, prob_decay):
        res = solve(prob, backend="native_primal_dual")
        hsde_summary = res.diagnostics["hsde_summary"]
        assert hsde_summary["executed"] is True
        assert hsde_summary["iterations"] <= 15
        assert res.data["solver_status"] == "primal_infeasible"
        assert res.diagnostics["hsde_certificate"] == "primal_infeasible"
        assert res.data["certificate_status"] == "validated_infeasibility"
        assert res.data["audit_feasibility"] == "violated"
        assert hsde_summary["farkas_dual_residual_rel"] < 1e-5
        assert hsde_summary["farkas_objective"] < 0.0

        if _clarabel_available():
            res_cl = solve(prob, backend="clarabel_direct")
            assert res_cl.data["solver_status"] == "primal_infeasible"
            assert res_cl.data["certificate_status"] == "validated_infeasibility"


# ---------------------------------------------------------------------------
# 3. Unbounded Objectives over Feasible Cones (Clean Dual-Infeasible Detection)
# ---------------------------------------------------------------------------


def test_f9_cycle2_hsde_unbounded_objective_clean_detection() -> None:
    """Unbounded linear objectives over feasible LP and PSD cones terminate cleanly without crash/hang."""
    x = sdpvar((1, 1), name="x")
    prob_unb_lp = compile(x, [linear_ineq(x, 2.0, name="ub")], name="f9_unb_lp")

    P = sdpvar((2, 2), name="P", symmetric=True)
    prob_unb_psd = compile(-trace(P), [P >= np.eye(2)], name="f9_unb_psd")

    for prob in (prob_unb_lp, prob_unb_psd):
        res = solve(prob, backend="native_primal_dual")
        hsde_summary = res.diagnostics["hsde_summary"]
        assert hsde_summary["executed"] is True
        assert hsde_summary["iterations"] <= 15
        assert res.data["solver_status"] == "dual_infeasible"
        assert res.diagnostics["hsde_certificate"] == "dual_infeasible"
        assert res.data["certificate_status"] == "validated_unboundedness"

        if _clarabel_available():
            res_cl = solve(prob, backend="clarabel_direct")
            assert res_cl.data["solver_status"] == "dual_infeasible"
            assert res_cl.data["certificate_status"] == "validated_unboundedness"
