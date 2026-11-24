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

    assert raw_cold["hsde_summary"]["executed"] is True
    assert raw_warm["hsde_summary"]["executed"] is False
    assert raw_warm["phase1_summary"]["executed"] is False
    assert raw_warm["phase1_summary"]["warm_start_used"] is True
    assert raw_warm["iterations"] < raw_cold["iterations"]

    res_warm = solve(prob_next, backend="native_primal_dual", options={"warm_start_x": x_prev})
    assert res_warm.status != "failure", res_warm.error
    assert res_warm.data["certificate_status"] == "validated_dual"
    assert recover_controller(prob_next, res_warm).data["controller_validity"] == "verified_under_assumptions"


def test_warm_start_hinf_brl_minimization_and_fallback() -> None:
    """Warm-start bypasses Phase 1/HSDE on H-inf BRL minimization and falls back cleanly if infeasible."""
    suite = _build_gate_0b_suite()
    prob_fixed = suite["CTRL_BRL_D2_FIXED"]["problem"]
    prob_min = suite["CTRL_BRL_D2_MIN"]["problem"]

    raw_fixed = solve_native_raw(prob_fixed)
    x_ws_interior = np.concatenate([raw_fixed["x"], [5.0]])

    raw_cold_hsde = solve_native_raw(prob_min)
    raw_cold_p1p2 = solve_native_raw(prob_min, options={"use_hsde": False})
    raw_warm = solve_native_raw(prob_min, options={"warm_start_x": x_ws_interior})

    assert raw_cold_hsde["hsde_summary"]["executed"] is True
    assert raw_cold_p1p2["phase1_summary"]["iterations"] > 0
    assert raw_warm["phase1_summary"]["iterations"] == 0
    assert raw_warm["phase1_summary"]["warm_start_used"] is True
    assert raw_warm["hsde_summary"]["executed"] is False
    assert raw_warm["iterations"] <= raw_cold_p1p2["iterations"]

    res_cold = solve(prob_min, backend="native_primal_dual")
    res_warm = solve(prob_min, backend="native_primal_dual", options={"warm_start_x": x_ws_interior})
    assert res_warm.data["certificate_status"] == "validated_dual"
    assert res_warm.data["objective"] == pytest.approx(res_cold.data["objective"], abs=1e-6)

    # Infeasible warm-start must fall back to HSDE/Phase 1 gracefully without failing
    x_infeasible = np.zeros((prob_min.n_vars,), dtype=np.float64)
    raw_fb = solve_native_raw(prob_min, options={"warm_start_x": x_infeasible})
    assert raw_fb["phase1_summary"]["warm_start_used"] is False
    assert raw_fb["hsde_summary"]["executed"] is True or raw_fb["phase1_summary"]["executed"] is True
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


def test_sdp_block_from_dict_sparse_coo_equivalence_and_validation() -> None:
    """SDPBlock.from_dict with F_k_sparse COO format matches dense F_k and achieves validated_dual."""
    from control_lab.diagnostics import ValidationError

    # Construct a 4x4 LMI problem via dense CanonicalSDPProblem and convert its block to COO F_k_sparse
    A = np.array([[0.0, 1.0], [-2.0, -3.0]], dtype=np.float64)
    B = np.array([[0.0], [1.0]], dtype=np.float64)
    prob_dense = continuous_stabilization_lmi(A, B, alpha=0.3)
    dense_dict = prob_dense.to_dict()

    sparse_blocks = []
    for blk, blk_dict in zip(prob_dense.blocks, dense_dict["blocks"], strict=True):
        fk_sparse: dict[str, list[list[float | int]]] = {}
        for k, fk in blk.F_terms.items():
            rows, cols = np.nonzero(np.abs(fk) > 0.0)
            fk_sparse[str(k)] = [[int(r), int(c), float(fk[r, c])] for r, c in zip(rows, cols, strict=True)]
        sparse_blocks.append({
            "name": blk_dict["name"],
            "F0": blk_dict["F0"],
            "F_k_sparse": fk_sparse,
        })

    sparse_payload = dict(dense_dict)
    sparse_payload["blocks"] = sparse_blocks
    prob_sparse = CanonicalSDPProblem.from_dict(sparse_payload)

    assert prob_sparse.n_vars == prob_dense.n_vars
    assert prob_sparse.n_blocks == prob_dense.n_blocks
    for b_s, b_d in zip(prob_sparse.blocks, prob_dense.blocks, strict=True):
        assert np.allclose(b_s.F0, b_d.F0, atol=1e-15)
        for k in range(prob_dense.n_vars):
            assert np.allclose(b_s.get_Fk(k), b_d.get_Fk(k), atol=1e-15)

    res_dense = solve(prob_dense, backend="native_primal_dual")
    res_sparse = solve(prob_sparse, backend="native_primal_dual")
    assert res_sparse.status != "failure", res_sparse.error
    assert res_sparse.data["certificate_status"] == "validated_dual"
    assert np.allclose(
        tensor_to_array(res_sparse.data["x"]),
        tensor_to_array(res_dense.data["x"]),
        atol=1e-10,
        rtol=1e-10,
    )

    # Asymmetric COO entry is symmetrized via 0.5 * (M + M.T)
    blk_sym = SDPBlock.from_dict(
        {"name": "sym_coo", "F0": np.eye(2), "F_k_sparse": {"0": [[0, 1, 2.0]]}},
        n_vars=1,
    )
    assert np.allclose(blk_sym.get_Fk(0), np.array([[0.0, 1.0], [1.0, 0.0]]))

    # Validation checks: out-of-bounds indices, non-finite value, out-of-range var key, missing n_vars
    with pytest.raises(ValidationError):
        SDPBlock.from_dict({"name": "oob", "F0": np.eye(2), "F_k_sparse": {"0": [[0, 2, 1.0]]}}, n_vars=1)
    with pytest.raises(ValidationError):
        SDPBlock.from_dict({"name": "nan", "F0": np.eye(2), "F_k_sparse": {"0": [[0, 0, float("nan")]]}}, n_vars=1)
    with pytest.raises(ValidationError):
        SDPBlock.from_dict({"name": "badk", "F0": np.eye(2), "F_k_sparse": {"3": [[0, 0, 1.0]]}}, n_vars=2)
    with pytest.raises(ValidationError):
        SDPBlock.from_dict({"name": "nonvars", "F0": np.eye(2), "F_k_sparse": {"0": [[0, 0, 1.0]]}})


def test_aggregate_sparsity_block_decomposition_24x24_four_subsystems() -> None:
    """24x24 block-diagonal 4-subsystem LMI splits into 4x 6x6 blocks, achieves validated_dual, matches Clarabel."""
    from control_lab.optimization.backends.native_core import _decompose_sparse_psd_blocks

    # 4 independent 6x6 PSD subsystems packed into a single 24x24 PSD block:
    # For each subsystem s in 0..3:
    #   min sum_s (t_s + 0.1 * p_s)  s.t.  diag_block_s = F0_s + t_s * I_6 + p_s * E_s >= 0
    # where F0_s is symmetric with negative minimum eigenvalue and dense 6x6 structure.
    rng = np.random.default_rng(123)
    n_sub = 4
    sub_dim = 6
    total_dim = n_sub * sub_dim  # 24
    n_vars = 2 * n_sub  # 8 variables: (t_s, p_s) for each subsystem

    F0_full = np.zeros((total_dim, total_dim), dtype=np.float64)
    F_k_full = [np.zeros((total_dim, total_dim), dtype=np.float64) for _ in range(n_vars)]
    c_vec = np.zeros((n_vars,), dtype=np.float64)

    for s in range(n_sub):
        sl = slice(s * sub_dim, (s + 1) * sub_dim)
        M = rng.standard_normal((sub_dim, sub_dim))
        Q_s = _sym(M @ M.T) - (1.5 + 0.4 * s) * np.eye(sub_dim)
        F0_full[sl, sl] = Q_s

        # Variable 2*s: t_s * I_6
        F_k_full[2 * s][sl, sl] = np.eye(sub_dim)
        c_vec[2 * s] = 1.0 + 0.2 * s

        # Variable 2*s + 1: p_s * B_s (coupled within the 6x6 block only)
        R = rng.standard_normal((sub_dim, sub_dim))
        B_s = _sym(R + R.T) * 0.2
        F_k_full[2 * s + 1][sl, sl] = B_s
        c_vec[2 * s + 1] = 0.05 * (s + 1)

    # Also add a simple bound block |p_s| <= 1 via linear inequalities so p_s is bounded
    H_rows = []
    h_vals = []
    for s in range(n_sub):
        r_pos = np.zeros((n_vars,), dtype=np.float64)
        r_pos[2 * s + 1] = 1.0
        r_neg = np.zeros((n_vars,), dtype=np.float64)
        r_neg[2 * s + 1] = -1.0
        H_rows.extend([r_pos, r_neg])
        h_vals.extend([1.0, 1.0])

    problem = CanonicalSDPProblem(
        c=c_vec,
        blocks=[SDPBlock("decoupled_24x24", F0_full, F_k_full, n_vars=n_vars)],
        H=np.vstack(H_rows),
        h=np.array(h_vals, dtype=np.float64),
    )

    # Direct check of _decompose_sparse_psd_blocks on the 24x24 block
    internal_blk = _InternalConeBlock(
        name="decoupled_24x24",
        dim=total_dim,
        F0=F0_full,
        F_terms={k: F_k_full[k] for k in range(n_vars)},
    )
    plan = _decompose_sparse_psd_blocks([internal_blk])
    assert plan.n_original_blocks == 1
    assert plan.n_decomposed_blocks == 4
    assert plan.decomposed_block_indices == (0,)
    assert [b.dim for b in plan.decomposed_blocks] == [6, 6, 6, 6]

    raw = solve_native_raw(problem)
    assert raw["decomposition_summary"]["n_original_blocks"] == 1 + 2 * n_sub
    assert raw["decomposition_summary"]["n_decomposed_blocks"] == 4 + 2 * n_sub
    assert raw["decomposition_summary"]["decomposed_block_indices"] == [0]

    res_nat = solve(problem, backend="native_primal_dual")
    res_cl = solve(problem, backend="clarabel_direct")
    assert res_nat.status != "failure", res_nat.error
    assert res_cl.status != "failure", res_cl.error
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_cl.data["certificate_status"] == "validated_dual"
    assert res_nat.data["objective"] == pytest.approx(res_cl.data["objective"], rel=1e-5, abs=1e-6)


def test_ruiz_multi_sweep_equilibration_stiff_1e4_to_1e_4_lmi() -> None:
    """Multi-sweep clipped Ruiz equilibration (Clarabel §2.4 & §2.6) solves stiff 1e-4..1e4 LMI with validated_dual."""
    from control_lab.optimization.backends.native_core import _ruiz_equilibrate_blocks

    # Stiff 2-block, 2-variable SDP spanning 1e-4 to 1e4 in both block norms and variable columns:
    #   min 1e-3 * x0 + 1e3 * x1
    #   s.t.  1e4 * [[x0 - 2.0, 0.25], [0.25, x0 - 1.0]] >= 0
    #         1e-4 * [[x1 - 3.0, 0.5], [0.5, x1 - 2.0]] >= 0
    F0_fast = 1e4 * np.array([[-2.0, 0.25], [0.25, -1.0]], dtype=np.float64)
    F1_fast = 1e4 * np.eye(2, dtype=np.float64)
    F2_fast = np.zeros((2, 2), dtype=np.float64)

    F0_slow = 1e-4 * np.array([[-3.0, 0.5], [0.5, -2.0]], dtype=np.float64)
    F1_slow = np.zeros((2, 2), dtype=np.float64)
    F2_slow = 1e-4 * np.eye(2, dtype=np.float64)

    problem = CanonicalSDPProblem(
        c=[1e-3, 1e3],
        blocks=[
            SDPBlock("stiff_fast", F0_fast, [F1_fast, F2_fast]),
            SDPBlock("stiff_slow", F0_slow, [F1_slow, F2_slow]),
        ],
    )

    # Verify clipped Ruiz scaling factors respect [1e-4, 1e4] bounds
    internal_blocks = [
        _InternalConeBlock(name="stiff_fast", dim=2, F0=F0_fast, F_terms={0: F1_fast}),
        _InternalConeBlock(name="stiff_slow", dim=2, F0=F0_slow, F_terms={1: F2_slow}),
    ]
    _, _, e_ruiz, d_ruiz = _ruiz_equilibrate_blocks(
        internal_blocks,
        np.array([1e-3, 1e3], dtype=np.float64),
        2,
        max_sweeps=5,
        min_scale=1e-4,
        max_scale=1e4,
    )
    assert np.all(e_ruiz >= 1e-4) and np.all(e_ruiz <= 1e4)
    assert np.all(d_ruiz >= 1e-4) and np.all(d_ruiz <= 1e4)

    res_nat = solve(problem, backend="native_primal_dual")
    res_cl = solve(problem, backend="clarabel_direct")
    assert res_nat.status != "failure", res_nat.error
    assert res_cl.status != "failure", res_cl.error
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_cl.data["certificate_status"] == "validated_dual"
    assert res_nat.data["objective"] == pytest.approx(res_cl.data["objective"], rel=1e-5, abs=1e-6)

