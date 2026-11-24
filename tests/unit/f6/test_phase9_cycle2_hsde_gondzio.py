"""Unit tests for WP-PHASE9-02-F6-HSDE-GONDZIO-SOLVER (ADR-015 Cycle 2).

Validates:
1. Single-pass Homogeneous Self-Dual Embedding (HSDE) on non-origin-feasible stabilization
   LMIs (n=4, 8, 12, 16), H-infinity BRL minimization, and mixed PSD + 1D LP problems:
   `validated_dual`, strict parity vs `clarabel_direct` (`|obj_native - obj_clarabel| < 1e-6`),
   and fewer total Cholesky factorizations than two-phase Phase I + Phase II.
2. Rapid infeasibility detection on contradictory PSD constraints (`P >= 2I`, `I - P >= 0`)
   and impossible bounded decay-rate LMIs with HSDE Farkas diagnostics
   (`hsde_certificate == "primal_infeasible"`, `certificate_status == "validated_infeasibility"`).
3. Clean unboundedness detection on feasible cones with unbounded linear objective
   (`solver_status == "dual_infeasible"`, `hsde_certificate == "dual_infeasible"`,
   `certificate_status == "validated_unboundedness"`).
4. Gondzio multiple centrality correctors activating on challenging/ill-conditioned SDPs
   reusing the cached Cholesky factor (`gondzio_correctors_accepted > 0`) without
   degrading 5D verification accuracy.
5. Preserved `warm_start_x`, `progress_callback`, and cooperative `cancel_check`
   (both via options and ContextVar), plus AST zero-`linalg.inv` invariant.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from control_lab.core import tensor_to_array
from control_lab.diagnostics import CancelledError, ValidationError
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
)
from control_lab.optimization.backends.native import NativePrimalDualBackend
from control_lab.optimization.backends.native_core import (
    _sym,
    clear_cancel_check,
    set_cancel_check,
    solve_native_raw,
)
from control_lab.optimization.verification.gate0b import _build_gate_0b_suite


# ---------------------------------------------------------------------------
# 1. Single-pass HSDE on Stabilization LMIs (n=4, 8, 12, 16), H-inf BRL & Mixed PSD+LP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [4, 8, 12, 16])
def test_hsde_single_pass_stabilization_lmi_fewer_factorizations_and_clarabel_parity(n: int) -> None:
    """Single-pass HSDE solves non-origin-feasible stabilization LMIs with fewer factorizations than Phase I+II."""
    A = np.diag([-1.0 - 0.1 * i for i in range(n - 1)] + [0.5])
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    prob = continuous_stabilization_lmi(A, B, alpha=0.25)

    raw_hsde = solve_native_raw(prob, options={"use_hsde": True, "max_gondzio_correctors": 2})
    raw_p1p2 = solve_native_raw(prob, options={"use_hsde": False, "max_gondzio_correctors": 0})

    assert raw_hsde["solver_status"] == "optimal"
    assert raw_hsde["hsde_summary"]["executed"] is True
    assert raw_hsde["phase1_summary"]["executed"] is False
    assert raw_hsde["hsde_certificate"] == "optimal"
    assert raw_hsde["factorizations"] < raw_p1p2["factorizations"], (
        f"Expected HSDE factorizations ({raw_hsde['factorizations']}) < Phase I+II ({raw_p1p2['factorizations']})"
    )

    res_nat = solve(prob, backend="native_primal_dual")
    res_cl = solve(prob, backend="clarabel_direct")
    assert res_nat.status != "failure", res_nat.error
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_nat.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
    assert abs(float(res_nat.data["objective"]) - float(res_cl.data["objective"])) < 1e-6
    assert res_nat.diagnostics["hsde_summary"]["executed"] is True

    rec = recover_controller(prob, res_nat)
    assert rec.data["controller_validity"] == "verified_under_assumptions"


def test_hsde_single_pass_hinf_brl_and_mixed_psd_lp_parity_vs_clarabel() -> None:
    """Single-pass HSDE solves H-inf BRL minimization and mixed PSD+1D LP with <1e-6 parity vs clarabel_direct."""
    suite = _build_gate_0b_suite()
    prob_brl = suite["CTRL_BRL_D2_MIN"]["problem"]

    raw_hsde = solve_native_raw(prob_brl, options={"use_hsde": True, "max_gondzio_correctors": 2})
    raw_p1p2 = solve_native_raw(prob_brl, options={"use_hsde": False, "max_gondzio_correctors": 0})
    assert raw_hsde["solver_status"] == "optimal"
    assert raw_hsde["hsde_summary"]["executed"] is True
    assert raw_hsde["factorizations"] < raw_p1p2["factorizations"]

    res_brl_nat = solve(prob_brl, backend="native_primal_dual")
    res_brl_cl = solve(prob_brl, backend="clarabel_direct")
    assert res_brl_nat.data["certificate_status"] == "validated_dual"
    assert abs(float(res_brl_nat.data["objective"]) - float(res_brl_cl.data["objective"])) < 1e-6

    # Mixed PSD + 1D LP problem (non-origin feasible)
    rng = np.random.default_rng(77)
    m = 6
    blocks: list[SDPBlock] = []
    for b in range(2):
        Q = rng.standard_normal((3, 3))
        F0 = _sym(Q @ Q.T) * 0.1 - (1.5 + 0.2 * b) * np.eye(3)
        F_terms = {0: np.eye(3, dtype=np.float64)}
        for k in range(1, m):
            F_terms[k] = _sym(rng.standard_normal((3, 3)) * 0.2)
        blocks.append(SDPBlock(f"psd_{b}", F0, F_terms, n_vars=m))
    for k in range(1, m):
        blocks.append(SDPBlock(f"ub_{k}", np.array([[2.0]]), {k: np.array([[-1.0]])}, n_vars=m))
        blocks.append(SDPBlock(f"lb_{k}", np.array([[2.0]]), {k: np.array([[1.0]])}, n_vars=m))
    c = np.array([1.0, 0.3, -0.2, 0.1, -0.15, 0.05], dtype=np.float64)
    prob_mix = CanonicalSDPProblem(c=c, blocks=blocks, name="hsde_mixed_psd_lp")

    raw_mix = solve_native_raw(prob_mix)
    assert raw_mix["solver_status"] == "optimal"
    assert raw_mix["hsde_summary"]["executed"] is True

    res_mix_nat = solve(prob_mix, backend="native_primal_dual")
    res_mix_cl = solve(prob_mix, backend="clarabel_direct")
    assert res_mix_nat.data["certificate_status"] == "validated_dual"
    assert abs(float(res_mix_nat.data["objective"]) - float(res_mix_cl.data["objective"])) < 1e-6


# ---------------------------------------------------------------------------
# 2. Rapid Infeasibility Detection with HSDE Farkas Certificate Diagnostics
# ---------------------------------------------------------------------------


def test_hsde_infeasibility_contradictory_psd_and_impossible_decay_rate() -> None:
    """Contradictory PSD constraints and impossible bounded decay-rate LMIs terminate rapidly with Farkas certificates."""
    # Case A: P >= 2I and I - P >= 0 (strictly contradictory PSD constraints)
    P = sdpvar((3, 3), name="P", symmetric=True)
    prob_contra = compile(
        trace(P),
        [P >= 2.0 * np.eye(3), np.eye(3) - P >= np.zeros((3, 3))],
        name="contradictory_psd",
    )
    raw_contra = solve_native_raw(prob_contra)
    assert raw_contra["solver_status"] == "primal_infeasible"
    assert raw_contra["hsde_certificate"] == "primal_infeasible"
    assert raw_contra["hsde_summary"]["executed"] is True
    assert raw_contra["hsde_summary"]["hsde_certificate"] == "primal_infeasible"
    assert raw_contra["hsde_summary"]["farkas_dual_residual_rel"] < 1e-5
    assert raw_contra["hsde_summary"]["farkas_objective"] < 0.0
    assert raw_contra["iterations"] < 20  # terminates rapidly, nowhere near max_iter=80

    res_contra = solve(prob_contra, backend="native_primal_dual")
    assert res_contra.data["solver_status"] == "primal_infeasible"
    assert res_contra.data["certificate_status"] == "validated_infeasibility"
    assert res_contra.data["audit_feasibility"] == "violated"
    assert res_contra.diagnostics["hsde_certificate"] == "primal_infeasible"

    # Case B: Impossible decay rate alpha=100 for unstable open-loop A with bounded Q, Y (zero control B=0)
    A_unst = np.array([[2.0, 0.5], [0.0, 1.5]], dtype=np.float64)
    Q = sdpvar((2, 2), name="Q", symmetric=True)
    alpha_impossible = 100.0
    prob_decay = compile(
        0.0 * Q[0, 0],
        [
            Q >= np.eye(2),
            10.0 * np.eye(2) - Q >= np.zeros((2, 2)),
            -(A_unst @ Q + Q @ A_unst.T + 2.0 * alpha_impossible * Q) >= np.zeros((2, 2)),
        ],
        name="impossible_decay_rate",
    )
    raw_decay = solve_native_raw(prob_decay)
    assert raw_decay["solver_status"] == "primal_infeasible"
    assert raw_decay["hsde_certificate"] == "primal_infeasible"
    assert raw_decay["iterations"] < 25

    res_decay = solve(prob_decay, backend="native_primal_dual")
    assert res_decay.data["solver_status"] == "primal_infeasible"
    assert res_decay.data["certificate_status"] == "validated_infeasibility"


# ---------------------------------------------------------------------------
# 3. Clean Unboundedness Detection (Dual Infeasible)
# ---------------------------------------------------------------------------


def test_hsde_unboundedness_detection_scalar_and_psd() -> None:
    """Unbounded linear objectives on feasible LP and PSD cones terminate cleanly as dual_infeasible."""
    # Case A: min x s.t. x <= 2 (unbounded below)
    x = sdpvar((1, 1), name="x")
    prob_unb_lp = compile(x, [linear_ineq(x, 2.0, name="ub")], name="unbounded_lp")
    raw_lp = solve_native_raw(prob_unb_lp)
    assert raw_lp["solver_status"] == "dual_infeasible"
    assert raw_lp["hsde_certificate"] == "dual_infeasible"
    assert raw_lp["iterations"] < 30

    res_lp = solve(prob_unb_lp, backend="native_primal_dual")
    assert res_lp.data["solver_status"] == "dual_infeasible"
    assert res_lp.data["certificate_status"] == "validated_unboundedness"

    # Case B: min -tr(P) s.t. P >= I_2 (unbounded below on PSD cone)
    P = sdpvar((2, 2), name="P", symmetric=True)
    prob_unb_psd = compile(-trace(P), [P >= np.eye(2)], name="unbounded_psd")
    raw_psd = solve_native_raw(prob_unb_psd)
    assert raw_psd["solver_status"] == "dual_infeasible"
    assert raw_psd["hsde_certificate"] == "dual_infeasible"
    assert raw_psd["iterations"] < 30

    res_psd = solve(prob_unb_psd, backend="native_primal_dual")
    assert res_psd.data["solver_status"] == "dual_infeasible"
    assert res_psd.data["certificate_status"] == "validated_unboundedness"


# ---------------------------------------------------------------------------
# 4. Gondzio Multiple Centrality Correctors
# ---------------------------------------------------------------------------


def test_gondzio_multiple_centrality_correctors_activate_and_preserve_accuracy() -> None:
    """Gondzio centrality correctors activate on challenging SDPs without degrading 5D audit accuracy."""
    suite = _build_gate_0b_suite()
    prob_brl = suite["CTRL_BRL_D2_MIN"]["problem"]

    raw_no_gon = solve_native_raw(prob_brl, options={"use_hsde": True, "max_gondzio_correctors": 0})
    raw_gon = solve_native_raw(prob_brl, options={"use_hsde": True, "max_gondzio_correctors": 2})

    assert raw_no_gon["gondzio_correctors_attempted"] == 0
    assert raw_no_gon["gondzio_correctors_accepted"] == 0
    assert raw_gon["gondzio_correctors_attempted"] > 0
    assert raw_gon["gondzio_correctors_accepted"] > 0
    assert raw_gon["iterations"] <= raw_no_gon["iterations"] + 2
    assert raw_gon["solver_status"] == "optimal"

    res_gon = solve(prob_brl, backend="native_primal_dual", options={"max_gondzio_correctors": 2})
    res_cl = solve(prob_brl, backend="clarabel_direct")
    assert res_gon.data["certificate_status"] == "validated_dual"
    assert abs(float(res_gon.data["objective"]) - float(res_cl.data["objective"])) < 1e-6

    # Invalid max_gondzio_correctors option rejected with ValidationError
    with pytest.raises(ValidationError):
        solve_native_raw(prob_brl, options={"max_gondzio_correctors": -1})
    with pytest.raises(ValidationError):
        solve_native_raw(prob_brl, options={"max_gondzio_correctors": True})


# ---------------------------------------------------------------------------
# 5. Warm-start, progress_callback, cooperative cancel_check & AST no-inv guard
# ---------------------------------------------------------------------------


def test_warm_start_progress_callback_and_cooperative_cancel_check() -> None:
    """warm_start_x, progress_callback, and cooperative cancel_check work cleanly with HSDE."""
    caps = NativePrimalDualBackend().capabilities()
    assert caps["cancellation"] is True
    assert caps["warm_start"] is True

    A = np.diag([-1.0, -1.5, -2.0, 0.4])
    B = np.array([[0.0], [0.0], [0.0], [1.0]], dtype=np.float64)
    prob = continuous_stabilization_lmi(A, B, alpha=0.2)

    # Progress callback fires every HSDE iteration with tau/kappa telemetry
    seen: list[dict] = []
    raw_ok = solve_native_raw(prob, options={"progress_callback": seen.append})
    assert raw_ok["solver_status"] == "optimal"
    assert len(seen) == raw_ok["iterations"]
    assert all("tau" in e and "kappa" in e and "iter" in e for e in seen)

    # Cooperative cancel_check via options raises CancelledError in solve_native_raw
    # and returns typed CANCELLED Result in solve()
    call_count = {"n": 0}

    def _cancel_after_2() -> bool:
        call_count["n"] += 1
        return call_count["n"] >= 2

    with pytest.raises(CancelledError):
        solve_native_raw(prob, options={"cancel_check": _cancel_after_2})

    call_count["n"] = 0
    res_cancelled = solve(prob, backend="native_primal_dual", options={"cancel_check": _cancel_after_2})
    assert res_cancelled.status == "failure"
    assert res_cancelled.error is not None
    assert res_cancelled.error.code == "CANCELLED"

    # Cooperative cancel_check via ContextVar
    set_cancel_check(lambda: True)
    try:
        res_ctx_cancel = solve(prob, backend="native_primal_dual")
        assert res_ctx_cancel.status == "failure"
        assert res_ctx_cancel.error is not None
        assert res_ctx_cancel.error.code == "CANCELLED"
    finally:
        clear_cancel_check()

    # Warm-start bypasses HSDE and achieves validated_dual
    x_ws = raw_ok["x"]
    prob_relaxed = continuous_stabilization_lmi(A, B, alpha=0.1)
    raw_ws = solve_native_raw(prob_relaxed, options={"warm_start_x": x_ws})
    assert raw_ws["hsde_summary"]["executed"] is False
    assert raw_ws["phase1_summary"]["warm_start_used"] is True
    res_ws = solve(prob_relaxed, backend="native_primal_dual", options={"warm_start_x": x_ws})
    assert res_ws.data["certificate_status"] == "validated_dual"
    np.testing.assert_allclose(tensor_to_array(res_ws.data["x"]), x_ws, atol=1e-12)


def test_native_core_ast_zero_linalg_inv() -> None:
    """AST guard ensures zero np.linalg.inv / scipy.linalg.inv calls in native_core.py."""
    core_path = Path(__file__).resolve().parents[3] / "control_lab" / "optimization" / "backends" / "native_core.py"
    tree = ast.parse(core_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "inv":
            pytest.fail(f"Forbidden .inv() call found in native_core.py at line {node.lineno}")
