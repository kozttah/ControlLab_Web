"""Unit tests for WP-PHASE5-01-F6-SCALABLE-NATIVE-SDP.

Validates:
- Cross-validation of native_primal_dual vs clarabel_direct on LTI stabilization (n=10, 16).
- Block-level Frobenius equilibration (Yurtsever et al., SIMAX 2021) on multi-scale plants
  with exact dual unscaling audited by the independent verifier.
- Interior-point warm-start (Ding et al., arXiv:2312.11801) bypassing Phase 1 on both
  feasibility sweeps and H-infinity BRL minimization, plus graceful fallback and validation.
- Factor-once Mehrotra Schur factorization and sparsity-exploiting NT congruence
  (Fujisawa et al., IEEE IPDPS 2014).
"""
from __future__ import annotations

import numpy as np
import pytest

from control_lab.core import tensor_to_array
from control_lab.optimization import (
    CanonicalSDPProblem,
    SDPBlock,
    continuous_stabilization_lmi,
    recover_controller,
    solve,
)
from control_lab.optimization.backends.native import NativePrimalDualBackend
from control_lab.optimization.backends.native_core import (
    _InternalConeBlock,
    _factor_symmetric_system,
    _solve_factored_symmetric,
    _sym,
    solve_native_raw,
)
from control_lab.optimization.verification.gate0b import _build_gate_0b_suite


@pytest.mark.parametrize("n", [10, 16])
def test_native_vs_clarabel_lti_stabilization_scalable(n: int) -> None:
    """Cross-validate upgraded native_primal_dual against clarabel_direct on n=10, 16."""
    alpha = 0.2
    A = np.diag([-1.0 - 0.1 * i for i in range(n - 1)] + [0.5])
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    problem = continuous_stabilization_lmi(A, B, alpha=alpha)

    res_nat = solve(problem, backend="native_primal_dual")
    res_cl = solve(problem, backend="clarabel_direct")

    assert res_nat.status != "failure", res_nat.error
    assert res_cl.status != "failure", res_cl.error
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_cl.data["certificate_status"] == "validated_dual"

    ctrl_nat = recover_controller(problem, res_nat)
    ctrl_cl = recover_controller(problem, res_cl)
    assert ctrl_nat.data["controller_validity"] == "verified_under_assumptions"
    assert ctrl_cl.data["controller_validity"] == "verified_under_assumptions"

    K_nat = tensor_to_array(ctrl_nat.data["K"])
    K_cl = tensor_to_array(ctrl_cl.data["K"])
    assert float(np.max(np.linalg.eigvals(A + B @ K_nat).real)) < -alpha
    assert float(np.max(np.linalg.eigvals(A + B @ K_cl).real)) < -alpha


def test_block_equilibration_multi_scale_ill_conditioned_lmi() -> None:
    """Block-level Frobenius equilibration handles 1e-3..1e3 plant scales with exact dual unscaling."""
    A_ill = np.array(
        [
            [-1e3, 1.0, 0.0],
            [0.0, -1.0, 1e-3],
            [0.0, 0.0, 0.5],
        ],
        dtype=np.float64,
    )
    B_ill = np.array([[1e-2], [1.0], [1e2]], dtype=np.float64)
    problem = continuous_stabilization_lmi(A_ill, B_ill, alpha=0.1)

    res_nat = solve(problem, backend="native_primal_dual")
    res_cl = solve(problem, backend="clarabel_direct")

    assert res_nat.status != "failure", res_nat.error
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_cl.data["certificate_status"] == "validated_dual"
    assert res_nat.assumptions["independent_audit"] is True

    ctrl = recover_controller(problem, res_nat)
    assert ctrl.data["controller_validity"] == "verified_under_assumptions"
    K = tensor_to_array(ctrl.data["K"])
    assert float(np.max(np.linalg.eigvals(A_ill + B_ill @ K).real)) < -0.1


def test_block_equilibration_unscales_duals_on_nonzero_objective() -> None:
    """Verify dual objective and stationarity match original unscaled problem when block norms differ by 1e6."""
    # min x  s.t.  1e6 * (x - 2) >= 0  and  1e-3 * (10 - x) >= 0  -> x* = 2, obj* = 2
    problem = CanonicalSDPProblem(
        c=[1.0],
        blocks=[
            SDPBlock("huge_block", np.array([[-2e6]]), [np.array([[1e6]])]),
            SDPBlock("tiny_block", np.array([[1e-2]]), [np.array([[-1e-3]])]),
        ],
    )
    res_nat = solve(problem, backend="native_primal_dual")
    res_cl = solve(problem, backend="clarabel_direct")

    assert res_nat.status != "failure", res_nat.error
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_nat.data["objective"] == pytest.approx(2.0, abs=1e-6)
    assert res_nat.data["objective"] == pytest.approx(res_cl.data["objective"], abs=1e-6)


def test_warm_start_capability_and_decay_rate_sweep() -> None:
    """Warm-start bypasses Phase 1 during decay-rate sweep while preserving validated_dual."""
    caps = NativePrimalDualBackend().capabilities()
    assert caps["warm_start"] is True

    n = 12
    A = np.diag([-1.0 - 0.1 * i for i in range(n - 1)] + [0.5])
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0

    prob_prev = continuous_stabilization_lmi(A, B, alpha=0.25)
    res_prev = solve(prob_prev, backend="native_primal_dual")
    assert res_prev.data["certificate_status"] == "validated_dual"
    x_prev = tensor_to_array(res_prev.data["x"])

    prob_next = continuous_stabilization_lmi(A, B, alpha=0.15)
    raw_cold = solve_native_raw(prob_next)
    raw_warm = solve_native_raw(prob_next, options={"warm_start_x": x_prev})

    assert raw_cold["phase1_summary"]["executed"] is True
    assert raw_warm["phase1_summary"]["executed"] is False
    assert raw_warm["phase1_summary"]["warm_start_used"] is True
    assert raw_warm["iterations"] < raw_cold["iterations"]

    res_warm = solve(prob_next, backend="native_primal_dual", options={"warm_start_x": x_prev})
    assert res_warm.status != "failure", res_warm.error
    assert res_warm.data["certificate_status"] == "validated_dual"
    assert recover_controller(prob_next, res_warm).data["controller_validity"] == "verified_under_assumptions"


def test_warm_start_hinf_brl_minimization_and_fallback() -> None:
    """Warm-start reduces Phase-1/total iterations on H-inf BRL minimization and falls back cleanly if infeasible."""
    suite = _build_gate_0b_suite()
    prob_fixed = suite["CTRL_BRL_D2_FIXED"]["problem"]
    prob_min = suite["CTRL_BRL_D2_MIN"]["problem"]

    raw_fixed = solve_native_raw(prob_fixed)
    x_ws_interior = np.concatenate([raw_fixed["x"], [5.0]])

    raw_cold = solve_native_raw(prob_min)
    raw_warm = solve_native_raw(prob_min, options={"warm_start_x": x_ws_interior})

    assert raw_cold["phase1_summary"]["iterations"] > 0
    assert raw_warm["phase1_summary"]["iterations"] == 0
    assert raw_warm["phase1_summary"]["warm_start_used"] is True
    assert raw_warm["iterations"] < raw_cold["iterations"]

    res_cold = solve(prob_min, backend="native_primal_dual")
    res_warm = solve(prob_min, backend="native_primal_dual", options={"warm_start_x": x_ws_interior})
    assert res_warm.data["certificate_status"] == "validated_dual"
    assert res_warm.data["objective"] == pytest.approx(res_cold.data["objective"], abs=1e-6)

    # Infeasible warm-start must fall back to Phase 1 gracefully without failing
    x_infeasible = np.zeros((prob_min.n_vars,), dtype=np.float64)
    raw_fb = solve_native_raw(prob_min, options={"warm_start_x": x_infeasible})
    assert raw_fb["phase1_summary"]["warm_start_used"] is False
    assert raw_fb["phase1_summary"]["executed"] is True
    res_fb = solve(prob_min, backend="native_primal_dual", options={"warm_start_x": x_infeasible})
    assert res_fb.data["certificate_status"] == "validated_dual"

    # Invalid warm_start_x dimensions or NaNs raise VALIDATION_ERROR
    bad_len = solve(prob_min, backend="native_primal_dual", options={"warm_start_x": [1.0]})
    assert bad_len.status == "failure" and bad_len.error.code == "VALIDATION_ERROR"
    bad_nan = solve(prob_min, backend="native_primal_dual", options={"warm_start_x": [float("nan")] * prob_min.n_vars})
    assert bad_nan.status == "failure" and bad_nan.error.code == "VALIDATION_ERROR"


def test_factor_once_schur_and_sparse_nt_congruence_accuracy() -> None:
    """Verify factor-once Schur solve and sparse NT congruence match dense reference."""
    rng = np.random.default_rng(42)
    M = rng.standard_normal((12, 12))
    H = _sym(M.T @ M + 1e-4 * np.eye(12))
    rhs1 = rng.standard_normal(12)
    rhs2 = rng.standard_normal(12)

    fac = _factor_symmetric_system(H)
    assert fac.cho is not None
    assert not fac.regularized
    assert np.isfinite(fac.cond) and fac.cond >= 1.0

    sol1 = _solve_factored_symmetric(fac, rhs1)
    sol2 = _solve_factored_symmetric(fac, rhs2)
    assert np.linalg.norm(H @ sol1 - rhs1) <= 1e-11 * np.linalg.norm(rhs1)
    assert np.linalg.norm(H @ sol2 - rhs2) <= 1e-11 * np.linalg.norm(rhs2)

    # Sparse NT congruence vs dense G_invT.T @ F_j @ G_invT
    dim = 10
    F_sparse = np.zeros((dim, dim), dtype=np.float64)
    F_sparse[2, 7] = 1.5
    F_sparse[7, 2] = 1.5
    blk = _InternalConeBlock(name="sp", dim=dim, F0=np.eye(dim), F_terms={0: F_sparse})
    assert 0 in blk._sparse_terms

    G_invT = rng.standard_normal((dim, dim))
    rows, c_idx, vals = blk._sparse_terms[0]
    fhat_sparse = _sym(G_invT[rows, :].T @ (vals[:, None] * G_invT[c_idx, :]))
    fhat_dense = _sym(G_invT.T @ F_sparse @ G_invT)
    assert np.allclose(fhat_sparse, fhat_dense, atol=1e-13, rtol=1e-13)
