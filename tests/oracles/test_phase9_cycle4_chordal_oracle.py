"""Independent F9 oracle audit for Phase 9 Cycle 4 (ADR-015: Chordal Cliques + Adaptive Sparse Schur).

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
    solve,
    verify,
)


def _clarabel_available() -> bool:
    return importlib.util.find_spec("clarabel") is not None


def _sym(mat: np.ndarray) -> np.ndarray:
    return 0.5 * (mat + mat.T)


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


def _build_banded_psd_oracle(dim: int, bandwidth: int = 2, *, seed: int = 2026) -> CanonicalSDPProblem:
    """Build an independent connected banded PSD SDP of size `dim` with bandwidth `bandwidth`."""
    rng = np.random.default_rng(seed)
    F0 = np.zeros((dim, dim), dtype=np.float64)
    for i in range(dim):
        F0[i, i] = 0.20 + 0.08 * (i % 4)
        for d in range(1, bandwidth + 1):
            if i + d < dim:
                val = -0.30 / d if (i + d) % 2 == 0 else 0.18 / d
                F0[i, i + d] = val
                F0[i + d, i] = val

    F_terms: dict[int, np.ndarray] = {}
    c_list: list[float] = []
    var_idx = 0

    for i in range(dim):
        mat = np.zeros((dim, dim), dtype=np.float64)
        mat[i, i] = 1.0
        F_terms[var_idx] = mat
        c_list.append(1.0 + 0.12 * float(rng.uniform(0.0, 1.0)))
        var_idx += 1

    for i in range(dim - 1):
        mat = np.zeros((dim, dim), dtype=np.float64)
        mat[i, i + 1] = 0.5
        mat[i + 1, i] = 0.5
        F_terms[var_idx] = mat
        c_list.append(0.08 * float(rng.uniform(-1.0, 1.0)))
        var_idx += 1

    n_vars = var_idx
    H = np.vstack([np.eye(n_vars, dtype=np.float64), -np.eye(n_vars, dtype=np.float64)])
    h = np.full((2 * n_vars,), 8.0, dtype=np.float64)

    blk = SDPBlock(name=f"f9_banded_d{dim}_bw{bandwidth}", F0=F0, F_k=F_terms, n_vars=n_vars)
    return CanonicalSDPProblem(
        name=f"f9_oracle_banded_d{dim}_bw{bandwidth}",
        c=np.asarray(c_list, dtype=np.float64),
        c0=0.0,
        blocks=(blk,),
        H=H,
        h=h,
    )


def _build_sparse_schur_oracle(n_blocks: int = 18, blk_dim: int = 3) -> CanonicalSDPProblem:
    """Build a structured chain-coupled multi-block SDP with m >= 60 and sparse Schur H (density < 0.25)."""
    rng = np.random.default_rng(707)
    n_local = 4
    n_vars = n_blocks * n_local + (n_blocks - 1)
    c = np.zeros((n_vars,), dtype=np.float64)
    blocks: list[SDPBlock] = []

    for b in range(n_blocks):
        base = b * n_local
        F0 = 0.25 * np.eye(blk_dim, dtype=np.float64)
        F0[0, 1] = F0[1, 0] = -0.32
        F0[1, 2] = F0[2, 1] = 0.22
        F_terms: dict[int, np.ndarray] = {}

        for i in range(blk_dim):
            mat = np.zeros((blk_dim, blk_dim), dtype=np.float64)
            mat[i, i] = 1.0
            F_terms[base + i] = mat
            c[base + i] = 1.0 + 0.09 * ((b + i) % 5)

        mat_off = np.zeros((blk_dim, blk_dim), dtype=np.float64)
        mat_off[0, 2] = mat_off[2, 0] = 0.45
        F_terms[base + 3] = mat_off
        c[base + 3] = 0.06 * float(rng.uniform(-1.0, 1.0))

        if b > 0:
            cpl_prev = n_blocks * n_local + (b - 1)
            mat_prev = np.zeros((blk_dim, blk_dim), dtype=np.float64)
            mat_prev[0, 0] = 0.55
            mat_prev[0, 1] = mat_prev[1, 0] = 0.18
            F_terms[cpl_prev] = mat_prev

        if b + 1 < n_blocks:
            cpl_next = n_blocks * n_local + b
            mat_next = np.zeros((blk_dim, blk_dim), dtype=np.float64)
            mat_next[2, 2] = 0.55
            mat_next[1, 2] = mat_next[2, 1] = -0.18
            F_terms[cpl_next] = mat_next
            c[cpl_next] = 0.75

        blocks.append(SDPBlock(name=f"f9_chain_{b}", F0=F0, F_k=F_terms, n_vars=n_vars))

    H = np.vstack([np.eye(n_vars, dtype=np.float64), -np.eye(n_vars, dtype=np.float64)])
    h = np.full((2 * n_vars,), 10.0, dtype=np.float64)

    return CanonicalSDPProblem(
        name=f"f9_oracle_sparse_schur_{n_blocks}x{blk_dim}",
        c=c,
        c0=0.0,
        blocks=tuple(blocks),
        H=H,
        h=h,
    )


def _build_dense_psd_oracle(dim: int = 10, *, seed: int = 314) -> CanonicalSDPProblem:
    """Build a dense PSD block SDP (density ~ 1.0) that must bypass chordal and sparse Schur."""
    rng = np.random.default_rng(seed)
    M = rng.standard_normal((dim, dim))
    F0 = _sym(M @ M.T) - 0.4 * np.eye(dim, dtype=np.float64)
    F_terms: dict[int, np.ndarray] = {}
    c_list: list[float] = []
    for k in range(dim):
        v = rng.standard_normal((dim, 1))
        F_terms[k] = _sym(v @ v.T + 0.25 * np.eye(dim, dtype=np.float64))
        c_list.append(1.0 + 0.1 * k)
    blk = SDPBlock(name=f"f9_dense_d{dim}", F0=F0, F_k=F_terms, n_vars=dim)
    return CanonicalSDPProblem(
        name=f"f9_oracle_dense_d{dim}",
        c=np.asarray(c_list, dtype=np.float64),
        c0=0.0,
        blocks=(blk,),
    )


# ---------------------------------------------------------------------------
# 1. Connected Banded PSD Blocks (dim=16 and dim=24, bandwidth=2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dim", [16, 24])
def test_f9_cycle4_chordal_banded_psd_oracle(dim: int) -> None:
    """Chordal decomposition on dim=16 and dim=24 banded PSD blocks validates 5D dual and matches Clarabel."""
    prob = _build_banded_psd_oracle(dim=dim, bandwidth=2, seed=2026 + dim)

    res_native = solve(prob, backend="native_primal_dual")
    assert res_native.status in ("success", "warning"), res_native.error
    assert res_native.data is not None
    assert res_native.data["solver_status"] == "optimal"
    assert res_native.data["certificate_status"] == "validated_dual"

    ch_sum = res_native.diagnostics["chordal_summary"]
    assert ch_sum["decomposed_blocks"] >= 1
    assert ch_sum["original_max_dim"] == dim
    assert ch_sum["clique_max_dim"] < dim
    assert ch_sum["num_cliques"] >= 2

    # Independent 5D verification on the ORIGINAL undecomposed block
    audited = verify(prob, _extract_solution_for_verify(res_native.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"
    assert audited.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    Z_rec = tensor_to_array(res_native.data["dual_Z"][0], expected_ndim=2, dtype="float64")
    assert Z_rec.shape == (dim, dim)
    min_eig_Z = float(np.min(np.linalg.eigvalsh(_sym(Z_rec))))
    assert min_eig_Z >= -1e-8, f"dim={dim}: reconstructed Z not PSD (min_eig={min_eig_Z})"

    # Parity against undecomposed native solve
    res_no_ch = solve(prob, backend="native_primal_dual", options={"use_chordal": False})
    assert res_no_ch.data is not None
    assert res_no_ch.data["solver_status"] == "optimal"
    obj_native = float(res_native.data["objective"])
    obj_no_ch = float(res_no_ch.data["objective"])
    assert abs(obj_native - obj_no_ch) < 1e-6

    # Independent Clarabel parity when installed (zero skips in core_no_sdp)
    if _clarabel_available():
        res_cl = solve(prob, backend="clarabel_direct")
        assert res_cl.data is not None
        assert res_cl.data["certificate_status"] == "validated_dual"
        obj_cl = float(res_cl.data["objective"])
        assert abs(obj_native - obj_cl) < 1e-6, (
            f"dim={dim}: native chordal ({obj_native:.10f}) vs Clarabel ({obj_cl:.10f})"
        )


# ---------------------------------------------------------------------------
# 2. Structured Sparse Schur SDP (m >= 60, density < 0.25)
# ---------------------------------------------------------------------------


def test_f9_cycle4_sparse_schur_splu_oracle() -> None:
    """Structured sparse-Schur SDP (m=89) engages sparse_splu, validates 5D dual, and matches dense/Clarabel."""
    prob = _build_sparse_schur_oracle(n_blocks=18, blk_dim=3)
    assert prob.n_vars == 89

    res_sparse = solve(prob, backend="native_primal_dual")
    assert res_sparse.status in ("success", "warning"), res_sparse.error
    assert res_sparse.data is not None
    assert res_sparse.data["solver_status"] == "optimal"
    assert res_sparse.data["certificate_status"] == "validated_dual"
    assert res_sparse.diagnostics["schur_factorization_mode"] == "sparse_splu"

    audited = verify(prob, _extract_solution_for_verify(res_sparse.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"

    res_dense = solve(
        prob,
        backend="native_primal_dual",
        options={"schur_factorization_mode": "dense_cholesky"},
    )
    assert res_dense.data is not None
    assert res_dense.data["solver_status"] == "optimal"
    assert res_dense.diagnostics["schur_factorization_mode"] == "dense_cholesky"

    obj_sp = float(res_sparse.data["objective"])
    obj_dn = float(res_dense.data["objective"])
    assert abs(obj_sp - obj_dn) < 1e-8, f"sparse_splu ({obj_sp:.12f}) vs dense ({obj_dn:.12f})"

    if _clarabel_available():
        res_cl = solve(prob, backend="clarabel_direct")
        assert res_cl.data is not None
        assert res_cl.data["certificate_status"] == "validated_dual"
        obj_cl = float(res_cl.data["objective"])
        assert abs(obj_sp - obj_cl) < 1e-6, f"sparse_splu ({obj_sp:.10f}) vs Clarabel ({obj_cl:.10f})"


# ---------------------------------------------------------------------------
# 3. Dense PSD Block Bypass
# ---------------------------------------------------------------------------


def test_f9_cycle4_dense_psd_bypasses_chordal_and_sparse_schur() -> None:
    """Dense PSD block cleanly skips chordal decomposition and uses dense_cholesky."""
    prob = _build_dense_psd_oracle(dim=10)
    res = solve(prob, backend="native_primal_dual")
    assert res.status in ("success", "warning"), res.error
    assert res.data is not None
    assert res.data["solver_status"] == "optimal"
    assert res.data["certificate_status"] == "validated_dual"

    ch_sum = res.diagnostics["chordal_summary"]
    assert ch_sum["decomposed_blocks"] == 0
    assert ch_sum["aux_vars_added"] == 0
    assert res.diagnostics["schur_factorization_mode"] == "dense_cholesky"

    audited = verify(prob, _extract_solution_for_verify(res.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"


# ---------------------------------------------------------------------------
# 4. Calibrated Sparse-Gram Browser Envelope (1792 / 3072 / 96 / 131072)
# ---------------------------------------------------------------------------


def test_f9_phase9_05c_sparse_gram_envelope_3072_oracle() -> None:
    """Independent F9 audit of calibrated 3072/1792/96/131072 envelope and n=48 (1224 vars) stabilization."""
    from control_lab.optimization import continuous_stabilization_lmi, recover_controller
    from control_lab.optimization.backends.native import BROWSER_ENVELOPE

    assert BROWSER_ENVELOPE == {
        "max_variables": 3072,
        "fast_max_variables": 1792,
        "max_block_dimension": 96,
        "max_cone_entries": 131072,
    }

    # n=48 has 48*49//2 + 48 = 1224 decision variables (above legacy 1024 cap, inside fast_max_variables=1792)
    n = 48
    alpha = 0.20
    A = np.diag([-1.0 - 0.08 * i for i in range(n - 1)] + [0.45]).astype(np.float64)
    for i in range(n - 1):
        A[i, i + 1] = 0.15
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    B[-2, 0] = 0.20
    prob_48 = continuous_stabilization_lmi(A, B, alpha=alpha)
    assert prob_48.n_vars == 1224

    res_nat = solve(prob_48, backend="native_primal_dual")
    assert res_nat.status in ("success", "warning"), res_nat.error
    assert res_nat.data is not None
    assert res_nat.data["certificate_status"] == "validated_dual"

    audited = verify(prob_48, _extract_solution_for_verify(res_nat.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"

    ctrl = recover_controller(prob_48, res_nat)
    assert ctrl.data is not None
    assert ctrl.data["controller_validity"] == "verified_under_assumptions"
    K = tensor_to_array(ctrl.data["K"], expected_ndim=2, dtype="float64")
    assert float(np.max(np.linalg.eigvals(A + B @ K).real)) < -alpha

    if _clarabel_available():
        res_cl = solve(prob_48, backend="clarabel_direct")
        assert res_cl.data is not None
        assert res_cl.data["certificate_status"] == "validated_dual"
        assert abs(float(res_nat.data["objective"]) - float(res_cl.data["objective"])) < 1e-6

    # Exceeding max_variables=3072 (3073 vars) returns RESOURCE_LIMIT with CVXPY/YALMIP guidance
    prob_over = CanonicalSDPProblem(c=np.ones(3073, dtype=np.float64))
    res_over = solve(prob_over, backend="native_primal_dual")
    assert res_over.status == "failure"
    assert res_over.error is not None
    assert res_over.error.code == "RESOURCE_LIMIT"
    assert "CVXPY" in res_over.error.message and "YALMIP" in res_over.error.message
    assert res_over.diagnostics["offline_recommended"] is True

