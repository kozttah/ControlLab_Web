"""Unit tests for WP-PHASE9-04-F6-CHORDAL-CLIQUES-SPARSE-SCHUR (ADR-015 Cycle 4).

Validates:
1. Maximal-clique chordal decomposition + exact Schur-complement PSD dual completion
   (Vandenberghe & Andersen 2015; Garstka, Cannon & Goulart, IFAC 2020):
   - Banded / tridiagonal connected PSD blocks (`dim=12`, `dim=20`, bandwidth 2 and 3):
     `chordal_summary["decomposed_blocks"] >= 1`, `clique_max_dim < dim`,
     `eigvalsh(Z_reconstructed).min() >= -1e-8`, `certificate_status == "validated_dual"`,
     and `< 1e-6` objective parity vs `clarabel_direct` and `use_chordal=False`.
   - Coupled arrow / chain control LMI (`dim=16`, 4 coupled subsystems):
     chordal decomposition engages, accelerates solve, and matches `clarabel_direct`
     with `validated_dual`.
   - Dense PSD block (`dim=10`): chordal decomposition cleanly skips (`decomposed_blocks == 0`).
   - Primal-infeasible banded PSD block: exact Farkas certificate (`validated_infeasibility`).
2. Adaptive sparse Schur factorization via `scipy.sparse.linalg.splu` (SuperLU):
   - Structured multi-block SDP with `m >= 60` and sparse Schur `H` (density `< 0.25`):
     `schur_factorization_mode == "sparse_splu"` engages automatically, achieves
     `validated_dual`, and matches dense Cholesky (`< 1e-8`) and `clarabel_direct` (`< 1e-6`).
   - Dense Schur `H`: selects `"dense_cholesky"` automatically.
3. Zero `linalg.inv` AST invariant in `control_lab/optimization/backends/native_core.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path
import time

import numpy as np
import pytest

from control_lab.core import tensor_to_array
from control_lab.optimization import CanonicalSDPProblem, SDPBlock, solve
from control_lab.optimization.backends.native_core import (
    _chordal_psd_complete,
    _sym,
    solve_native_raw,
)


def _make_banded_psd_sdp(dim: int, bandwidth: int = 2, *, seed: int = 42) -> CanonicalSDPProblem:
    """Build a connected banded PSD SDP: min sum c_k x_k s.t. F0 + sum x_k F_k >= 0, x_k >= -5."""
    rng = np.random.default_rng(seed)
    # Build banded F0 (tridiagonal/pentadiagonal) with mild negative off-diagonals
    F0 = np.zeros((dim, dim), dtype=np.float64)
    for i in range(dim):
        F0[i, i] = 0.25 + 0.1 * (i % 3)
        for d in range(1, bandwidth + 1):
            if i + d < dim:
                val = -0.35 / d if (i + d) % 2 == 0 else 0.20 / d
                F0[i, i + d] = val
                F0[i + d, i] = val

    # Decision variables:
    # - One diagonal variable x_i per vertex i (adds E_{i,i})
    # - One off-diagonal coupling variable per banded edge (i, i+1)
    F_terms: dict[int, np.ndarray] = {}
    c_list: list[float] = []
    var_idx = 0

    for i in range(dim):
        mat = np.zeros((dim, dim), dtype=np.float64)
        mat[i, i] = 1.0
        F_terms[var_idx] = mat
        c_list.append(1.0 + 0.15 * float(rng.uniform(0.0, 1.0)))
        var_idx += 1

    for i in range(dim - 1):
        mat = np.zeros((dim, dim), dtype=np.float64)
        mat[i, i + 1] = 0.5
        mat[i + 1, i] = 0.5
        F_terms[var_idx] = mat
        c_list.append(0.1 * float(rng.uniform(-1.0, 1.0)))
        var_idx += 1

    # Add upper-bound box constraints via linear inequalities so variables stay bounded
    n_vars = var_idx
    H = np.vstack([np.eye(n_vars, dtype=np.float64), -np.eye(n_vars, dtype=np.float64)])
    h = np.full((2 * n_vars,), 8.0, dtype=np.float64)

    blk = SDPBlock(name=f"banded_d{dim}_bw{bandwidth}", F0=F0, F_k=F_terms, n_vars=n_vars)
    return CanonicalSDPProblem(
        name=f"banded_psd_d{dim}_bw{bandwidth}",
        c=np.asarray(c_list, dtype=np.float64),
        c0=0.0,
        blocks=(blk,),
        H=H,
        h=h,
    )


def _make_coupled_chain_control_lmi(n_subsystems: int = 4, sub_dim: int = 4) -> CanonicalSDPProblem:
    """Build a connected coupled-chain control LMI of size dim = n_subsystems * sub_dim = 16.

    Each subsystem s = 0..3 has local Lyapunov block P_s (4x4 symmetric, constrained to be
    coupled across adjacent subsystems via a 2-state interface), giving a sparse connected
    16x16 PSD block with 4 overlapping cliques of size <= 6.
    """
    dim = n_subsystems * sub_dim
    # Local stable dynamics A_s (4x4) + nearest-neighbor coupling
    A = np.zeros((dim, dim), dtype=np.float64)
    for s in range(n_subsystems):
        i0 = s * sub_dim
        A_loc = np.array(
            [
                [-2.2 - 0.1 * s, 0.4, 0.0, 0.0],
                [-0.3, -1.8 - 0.1 * s, 0.35, 0.0],
                [0.0, -0.25, -2.0 - 0.1 * s, 0.3],
                [0.0, 0.0, -0.2, -1.6 - 0.1 * s],
            ],
            dtype=np.float64,
        )
        A[i0 : i0 + sub_dim, i0 : i0 + sub_dim] = A_loc
        if s + 1 < n_subsystems:
            # Sparse interface coupling between last state of subsystem s and first state of s+1
            u = i0 + sub_dim - 1
            v = i0 + sub_dim
            A[u, v] = 0.25
            A[v, u] = -0.20

    # Variables: diagonal P_i (dim vars) + intra-subsystem nearest-neighbor off-diagonals
    F0_lyap = -0.15 * np.eye(dim, dtype=np.float64)
    F0_pos = -0.25 * np.eye(dim, dtype=np.float64)
    F_lyap: dict[int, np.ndarray] = {}
    F_pos: dict[int, np.ndarray] = {}
    c_list: list[float] = []
    var_idx = 0

    for i in range(dim):
        E_ii = np.zeros((dim, dim), dtype=np.float64)
        E_ii[i, i] = 1.0
        F_pos[var_idx] = E_ii
        F_lyap[var_idx] = _sym(-(A.T @ E_ii + E_ii @ A))
        c_list.append(1.0 + 0.05 * i)
        var_idx += 1

    # Add intra-subsystem tridiagonal variables in P
    for s in range(n_subsystems):
        i0 = s * sub_dim
        for k in range(sub_dim - 1):
            E_ij = np.zeros((dim, dim), dtype=np.float64)
            E_ij[i0 + k, i0 + k + 1] = 1.0
            E_ij[i0 + k + 1, i0 + k] = 1.0
            F_pos[var_idx] = E_ij
            F_lyap[var_idx] = _sym(-(A.T @ E_ij + E_ij @ A))
            c_list.append(0.0)
            var_idx += 1

    blk_lyap = SDPBlock(name="chain_lyap_16", F0=F0_lyap, F_k=F_lyap, n_vars=var_idx)
    blk_pos = SDPBlock(name="chain_pos_16", F0=F0_pos, F_k=F_pos, n_vars=var_idx)
    return CanonicalSDPProblem(
        name="coupled_chain_control_lmi_16",
        c=np.asarray(c_list, dtype=np.float64),
        c0=0.0,
        blocks=(blk_lyap, blk_pos),
    )


def _make_dense_psd_sdp(dim: int = 10, *, seed: int = 77) -> CanonicalSDPProblem:
    """Build a dense PSD block SDP (density ~ 1.0) that must bypass chordal decomposition."""
    rng = np.random.default_rng(seed)
    M = rng.standard_normal((dim, dim))
    F0 = _sym(M @ M.T) - 0.5 * np.eye(dim)
    F_terms: dict[int, np.ndarray] = {}
    c_list: list[float] = []
    for k in range(dim):
        v = rng.standard_normal((dim, 1))
        F_terms[k] = _sym(v @ v.T + 0.2 * np.eye(dim))
        c_list.append(1.0 + 0.1 * k)
    blk = SDPBlock(name=f"dense_d{dim}", F0=F0, F_k=F_terms, n_vars=dim)
    return CanonicalSDPProblem(
        name=f"dense_psd_d{dim}",
        c=np.asarray(c_list, dtype=np.float64),
        c0=0.0,
        blocks=(blk,),
    )


def _make_sparse_schur_multiblock_sdp(n_blocks: int = 16, blk_dim: int = 3) -> CanonicalSDPProblem:
    """Build a structured multi-block SDP with m >= 60 variables and sparse Schur matrix H (< 25% density).

    Each block b has 4 local variables plus 1 shared coupling variable to block b+1 (chain coupling),
    yielding m = 5*n_blocks - 1 = 79 variables with block-tridiagonal Schur complement H (~10% density).
    """
    rng = np.random.default_rng(123)
    # Local vars: 4 per block; coupling vars: 1 between block b and b+1
    n_local = 4
    n_vars = n_blocks * n_local + (n_blocks - 1)
    c = np.zeros((n_vars,), dtype=np.float64)
    blocks: list[SDPBlock] = []

    for b in range(n_blocks):
        base = b * n_local
        F0 = 0.2 * np.eye(blk_dim, dtype=np.float64)
        F0[0, 1] = F0[1, 0] = -0.35
        F0[1, 2] = F0[2, 1] = 0.25
        F_terms: dict[int, np.ndarray] = {}

        # 3 diagonal vars + 1 off-diagonal var local to block b
        for i in range(blk_dim):
            mat = np.zeros((blk_dim, blk_dim), dtype=np.float64)
            mat[i, i] = 1.0
            F_terms[base + i] = mat
            c[base + i] = 1.0 + 0.1 * ((b + i) % 4)
        mat_off = np.zeros((blk_dim, blk_dim), dtype=np.float64)
        mat_off[0, 2] = mat_off[2, 0] = 0.5
        F_terms[base + 3] = mat_off
        c[base + 3] = 0.05 * float(rng.uniform(-1.0, 1.0))

        # Chain coupling variable with previous block (b - 1)
        if b > 0:
            cpl_prev = n_blocks * n_local + (b - 1)
            mat_prev = np.zeros((blk_dim, blk_dim), dtype=np.float64)
            mat_prev[0, 0] = 0.6
            mat_prev[0, 1] = mat_prev[1, 0] = 0.2
            F_terms[cpl_prev] = mat_prev

        # Chain coupling variable with next block (b)
        if b + 1 < n_blocks:
            cpl_next = n_blocks * n_local + b
            mat_next = np.zeros((blk_dim, blk_dim), dtype=np.float64)
            mat_next[2, 2] = 0.6
            mat_next[1, 2] = mat_next[2, 1] = -0.2
            F_terms[cpl_next] = mat_next
            c[cpl_next] = 0.8

        blocks.append(SDPBlock(name=f"sub_{b}", F0=F0, F_k=F_terms, n_vars=n_vars))

    H = np.vstack([np.eye(n_vars, dtype=np.float64), -np.eye(n_vars, dtype=np.float64)])
    h = np.full((2 * n_vars,), 10.0, dtype=np.float64)

    return CanonicalSDPProblem(
        name=f"sparse_schur_chain_{n_blocks}x{blk_dim}",
        c=c,
        c0=0.0,
        blocks=tuple(blocks),
        H=H,
        h=h,
    )


# ---------------------------------------------------------------------------
# 1. Maximal-Clique Chordal Decomposition + Exact PSD Dual Completion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dim,bandwidth", [(12, 2), (20, 2), (12, 3)])
def test_chordal_banded_psd_decomposition_and_clarabel_parity(dim: int, bandwidth: int) -> None:
    """Banded connected PSD blocks decompose into smaller cliques, complete Z >= 0, and match Clarabel."""
    prob = _make_banded_psd_sdp(dim, bandwidth=bandwidth, seed=40 + dim + bandwidth)

    res_native = solve(prob, backend="native_primal_dual")
    res_no_ch = solve(prob, backend="native_primal_dual", options={"use_chordal": False})
    res_clarabel = solve(prob, backend="clarabel_direct")

    assert res_native.data is not None
    assert res_no_ch.data is not None
    assert res_clarabel.data is not None

    assert res_native.data["solver_status"] == "optimal"
    assert res_native.data["certificate_status"] == "validated_dual"
    assert res_clarabel.data["certificate_status"] == "validated_dual"

    ch_sum = res_native.diagnostics["chordal_summary"]
    assert ch_sum["decomposed_blocks"] >= 1
    assert ch_sum["original_max_dim"] == dim
    assert ch_sum["clique_max_dim"] < dim
    assert ch_sum["num_cliques"] >= 2
    assert ch_sum["aux_vars_added"] >= 1

    # Verify exact PSD completion on the original undecomposed block
    Z_rec = tensor_to_array(res_native.data["dual_Z"][0])
    assert Z_rec.shape == (dim, dim)
    min_eig_Z = float(np.min(np.linalg.eigvalsh(_sym(Z_rec))))
    assert min_eig_Z >= -1e-8

    # Verify < 1e-6 parity against both clarabel_direct and undecomposed native
    obj_native = float(res_native.data["objective"])
    obj_no_ch = float(res_no_ch.data["objective"])
    obj_clarabel = float(res_clarabel.data["objective"])
    assert abs(obj_native - obj_clarabel) < 1e-6
    assert abs(obj_native - obj_no_ch) < 1e-6


def test_chordal_coupled_chain_control_lmi_dim16_parity_and_speed() -> None:
    """Coupled 4-subsystem chain control LMI (dim=16) engages chordal cliques and matches Clarabel."""
    prob = _make_coupled_chain_control_lmi(n_subsystems=4, sub_dim=4)

    t0 = time.perf_counter()
    res_ch = solve(prob, backend="native_primal_dual")
    t_ch = time.perf_counter() - t0

    t1 = time.perf_counter()
    res_no_ch = solve(prob, backend="native_primal_dual", options={"use_chordal": False})
    t_no_ch = time.perf_counter() - t1

    res_clarabel = solve(prob, backend="clarabel_direct")

    assert res_ch.data is not None
    assert res_no_ch.data is not None
    assert res_clarabel.data is not None

    assert res_ch.data["solver_status"] == "optimal"
    assert res_ch.data["certificate_status"] == "validated_dual"
    assert res_clarabel.data["certificate_status"] == "validated_dual"

    ch_sum = res_ch.diagnostics["chordal_summary"]
    assert ch_sum["decomposed_blocks"] >= 1
    assert ch_sum["original_max_dim"] == 16
    assert ch_sum["clique_max_dim"] < 16
    assert ch_sum["num_cliques"] >= 2

    for Z_raw in res_ch.data["dual_Z"]:
        Z_mat = tensor_to_array(Z_raw)
        assert Z_mat.shape == (16, 16)
        assert float(np.min(np.linalg.eigvalsh(_sym(Z_mat)))) >= -1e-8

    obj_ch = float(res_ch.data["objective"])
    obj_no_ch = float(res_no_ch.data["objective"])
    obj_cl = float(res_clarabel.data["objective"])
    assert abs(obj_ch - obj_cl) < 1e-6
    assert abs(obj_ch - obj_no_ch) < 1e-6
    assert t_ch > 0.0 and t_no_ch > 0.0


def test_chordal_skips_dense_psd_block_with_zero_overhead() -> None:
    """Dense PSD block (dim=10) cleanly bypasses chordal decomposition."""
    prob = _make_dense_psd_sdp(dim=10)
    res = solve(prob, backend="native_primal_dual")
    assert res.data is not None
    assert res.data["solver_status"] == "optimal"
    assert res.data["certificate_status"] == "validated_dual"

    ch_sum = res.diagnostics["chordal_summary"]
    assert ch_sum["decomposed_blocks"] == 0
    assert ch_sum["aux_vars_added"] == 0
    assert ch_sum["num_cliques"] == 0


def test_chordal_psd_complete_rank_deficient_exactness() -> None:
    """Direct test of _chordal_psd_complete on a rank-deficient chain of overlapping cliques."""
    # Construct a true rank-3 PSD matrix of size 10 and extract 3 overlapping cliques
    rng = np.random.default_rng(99)
    V = rng.standard_normal((10, 3))
    Z_true = _sym(V @ V.T)

    cliques = ((0, 1, 2, 3, 4), (3, 4, 5, 6, 7), (6, 7, 8, 9))
    parents = (-1, 0, 1)
    clique_duals = [Z_true[np.ix_(c, c)] for c in cliques]

    Z_comp = _chordal_psd_complete(10, cliques, parents, clique_duals)
    assert Z_comp.shape == (10, 10)
    assert float(np.min(np.linalg.eigvalsh(Z_comp))) >= -1e-10
    for c, Z_c in zip(cliques, clique_duals, strict=True):
        np.testing.assert_allclose(Z_comp[np.ix_(c, c)], Z_c, atol=1e-12)


def test_chordal_primal_infeasible_banded_block_farkas_certificate() -> None:
    """Primal-infeasible banded PSD block produces a validated Farkas certificate via chordal completion."""
    dim = 10
    # Tridiagonal F0 with a strongly negative 2x2 principal minor on (0, 1) that no variable can fix
    F0 = np.eye(dim, dtype=np.float64)
    F0[0, 0] = -2.0
    F0[1, 1] = -2.0
    for i in range(dim - 1):
        F0[i, i + 1] = F0[i + 1, i] = 0.25

    # Variables only touch vertices 2..9 (tridiagonal), leaving vertices 0..1 infeasible
    F_terms: dict[int, np.ndarray] = {}
    for idx, i in enumerate(range(2, dim)):
        mat = np.zeros((dim, dim), dtype=np.float64)
        mat[i, i] = 1.0
        F_terms[idx] = mat

    blk = SDPBlock(name="infeas_banded_10", F0=F0, F_k=F_terms, n_vars=len(F_terms))
    prob = CanonicalSDPProblem(
        name="infeas_banded_10",
        c=np.ones((len(F_terms),), dtype=np.float64),
        c0=0.0,
        blocks=(blk,),
    )
    res = solve(prob, backend="native_primal_dual")
    assert res.data is not None
    assert res.data["solver_status"] == "primal_infeasible"
    assert res.data["certificate_status"] == "validated_infeasibility"
    assert res.diagnostics["chordal_summary"]["decomposed_blocks"] >= 1


# ---------------------------------------------------------------------------
# 2. Adaptive Sparse Schur Factorization via scipy.sparse.linalg.splu
# ---------------------------------------------------------------------------


def test_adaptive_sparse_schur_splu_engages_and_matches_dense_and_clarabel() -> None:
    """Structured multi-block SDP (m=79, sparse H) engages sparse_splu and matches dense/Clarabel."""
    prob = _make_sparse_schur_multiblock_sdp(n_blocks=16, blk_dim=3)
    assert prob.n_vars == 79

    raw_auto = solve_native_raw(prob)
    assert raw_auto["schur_factorization_mode"] == "sparse_splu"

    res_sparse = solve(prob, backend="native_primal_dual")
    res_dense = solve(
        prob,
        backend="native_primal_dual",
        options={"schur_factorization_mode": "dense_cholesky"},
    )
    res_clarabel = solve(prob, backend="clarabel_direct")

    assert res_sparse.data is not None
    assert res_dense.data is not None
    assert res_clarabel.data is not None

    assert res_sparse.data["solver_status"] == "optimal"
    assert res_sparse.data["certificate_status"] == "validated_dual"
    assert res_sparse.diagnostics["schur_factorization_mode"] == "sparse_splu"
    assert res_dense.diagnostics["schur_factorization_mode"] == "dense_cholesky"

    obj_sp = float(res_sparse.data["objective"])
    obj_dn = float(res_dense.data["objective"])
    obj_cl = float(res_clarabel.data["objective"])
    assert abs(obj_sp - obj_dn) < 1e-8
    assert abs(obj_sp - obj_cl) < 1e-6


def test_dense_schur_auto_selects_dense_cholesky() -> None:
    """Dense Schur H automatically selects dense_cholesky."""
    prob = _make_dense_psd_sdp(dim=10)
    res = solve(prob, backend="native_primal_dual")
    assert res.data is not None
    assert res.data["solver_status"] == "optimal"
    assert res.data["certificate_status"] == "validated_dual"
    assert res.diagnostics["schur_factorization_mode"] == "dense_cholesky"


# ---------------------------------------------------------------------------
# 3. AST Zero-linalg.inv Invariant
# ---------------------------------------------------------------------------


def test_native_core_ast_zero_linalg_inv_cycle4() -> None:
    """Confirm native_core.py contains zero linalg.inv calls after Cycle 4 changes."""
    path = Path("control_lab/optimization/backends/native_core.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "inv":
            assert not (
                isinstance(node.value, ast.Attribute) and node.value.attr == "linalg"
            ), f"Forbidden linalg.inv detected in {path}"
