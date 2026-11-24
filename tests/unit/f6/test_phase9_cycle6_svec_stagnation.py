"""Unit tests for Phase 9 Cycle 6 (WP-PHASE9-06A): svec Schur isometry & HSDE stagnation safeguard 1b'."""

from __future__ import annotations

import ast
from pathlib import Path
import numpy as np
import pytest

from control_lab.optimization import solve
from control_lab.optimization.backends.native_core import (
    _InternalConeBlock,
    _fill_f3_scaled_cols,
    _mat_to_svec,
    _svec_to_mat_into,
    solve_native_raw,
)
from control_lab.optimization.modeling.canonical import CanonicalSDPProblem, SDPBlock


def test_svec_isometry_roundtrip_and_frobenius_inner_product() -> None:
    """Verify exact Frobenius isometry <A, B>_F = svec(A)^T svec(B) and lossless roundtrip."""
    rng = np.random.default_rng(202606)
    for dim in (1, 2, 5, 16, 37):
        A_raw = rng.standard_normal((dim, dim))
        B_raw = rng.standard_normal((dim, dim))
        A = 0.5 * (A_raw + A_raw.T)
        B = 0.5 * (B_raw + B_raw.T)
        va = _mat_to_svec(A)
        vb = _mat_to_svec(B)
        assert va.shape == (dim * (dim + 1) // 2,)
        assert float(np.dot(va, vb)) == pytest.approx(float(np.sum(A * B)), rel=1e-13, abs=1e-13)

        A_rec = np.empty_like(A)
        _svec_to_mat_into(va, A_rec)
        np.testing.assert_allclose(A_rec, A, rtol=1e-14, atol=1e-14)


def test_f2_svec_csr_and_f3_aliasing_free_congruence_exactness() -> None:
    """Verify F_svec_csr shape/values, F2 lower-triangle svec assembly, and aliasing-free F3_blas."""
    rng = np.random.default_rng(906)
    dim = 14
    n_svec = dim * (dim + 1) // 2
    n_act = 70  # spans >2 _F2_CHUNK_SIZE (32) and >1 _F3_CHUNK_SIZE (64)
    terms: dict[int, np.ndarray] = {}
    for j in range(n_act):
        mat = np.zeros((dim, dim), dtype=np.float64)
        idx = rng.choice(dim, size=4, replace=False)
        sub = rng.standard_normal((4, 4))
        mat[np.ix_(idx, idx)] = 0.5 * (sub + sub.T)
        terms[j] = mat

    blk_f2 = _InternalConeBlock(name="f2_svec", dim=dim, F0=np.eye(dim), F_terms=terms)
    blk_f3 = _InternalConeBlock(
        name="f3_svec", dim=dim, F0=np.eye(dim), F_terms=terms, force_schur_mode="F3_blas"
    )
    assert blk_f2.schur_mode == "F2"
    assert blk_f2._F_svec_csr is not None
    assert blk_f2._F_svec_csr.shape == (n_act, n_svec)
    assert blk_f3.schur_mode == "F3_blas"
    assert blk_f3._F_cols is not None

    # Deliberately asymmetric G_invT to stress aliasing-free symmetrization in _fill_f3_scaled_cols
    G_invT = rng.standard_normal((dim, dim)) * 0.4 + 2.0 * np.eye(dim)
    G_invT[0, -1] += 1.75
    W = G_invT @ G_invT.T

    cols_svec = np.empty((n_svec, n_act), dtype=np.float64)
    _fill_f3_scaled_cols(blk_f3._F_cols, G_invT, dim, cols_svec)

    # Compare every column directly against explicit reference svec(sym(G_invT^T F_j G_invT))
    for j in range(n_act):
        ref_mat = G_invT.T @ terms[j] @ G_invT
        ref_svec = _mat_to_svec(0.5 * (ref_mat + ref_mat.T))
        np.testing.assert_allclose(cols_svec[:, j], ref_svec, rtol=1e-13, atol=1e-13)

    gram_ref = cols_svec.T @ cols_svec
    gram_f2 = np.empty((n_act, n_act), dtype=np.float64)
    gram_f3 = np.empty((n_act, n_act), dtype=np.float64)
    blk_f2.assemble_schur_block(W, gram_f2)
    blk_f3.assemble_schur_block(W, gram_f3)

    np.testing.assert_allclose(gram_f2, gram_ref, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(gram_f3, gram_ref, rtol=1e-12, atol=1e-12)


def test_hsde_stagnation_safeguard_stiff_block_diagonal_24x8() -> None:
    """Stiff 24x8 block-diagonal SDP converges well below max_iter=80 with validated_dual and Clarabel parity."""
    rng = np.random.default_rng(2408)
    n_blocks = 24
    blk_dim = 8
    n_local = 4
    n_vars = n_blocks * n_local
    c = np.zeros((n_vars,), dtype=np.float64)
    blocks: list[SDPBlock] = []

    for b in range(n_blocks):
        scale = 2.0 ** (b % 4)  # 1.0 .. 8.0 multi-scale conditioning across 24 blocks
        A = rng.standard_normal((blk_dim, blk_dim)) * 0.25
        F0 = scale * (0.5 * (A + A.T) + 4.0 * np.eye(blk_dim))
        f_terms: dict[int, np.ndarray] = {}
        base = b * n_local
        for k in range(n_local):
            M = np.zeros((blk_dim, blk_dim), dtype=np.float64)
            i0 = (2 * k) % blk_dim
            i1 = (2 * k + 1) % blk_dim
            M[i0, i0] = scale
            M[i1, i1] = 0.8 * scale
            M[i0, i1] = M[i1, i0] = 0.25 * scale
            f_terms[base + k] = M
            c[base + k] = scale * (1.0 + 0.1 * k)
        blocks.append(SDPBlock(name=f"blk_{b}", F0=F0, F_k=f_terms, n_vars=n_vars))

    prob = CanonicalSDPProblem(name="BlkDiag_24x8_stiff", c=c, c0=0.0, blocks=tuple(blocks))
    raw = solve_native_raw(prob)
    res_nat = solve(prob, backend="native_primal_dual")
    res_cl = solve(prob, backend="clarabel_direct")

    assert raw["solver_status"] == "optimal"
    assert raw["iterations"] < 40, f"Expected early convergence without 80-iter spin, got {raw['iterations']}"
    assert res_nat.data is not None and res_cl.data is not None
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_cl.data["certificate_status"] == "validated_dual"
    assert float(res_nat.data["objective"]) == pytest.approx(float(res_cl.data["objective"]), rel=1e-6, abs=1e-6)


def test_native_core_no_inplace_swapaxes_aliasing_or_linalg_inv() -> None:
    """AST guard: zero linalg.inv and zero in-place '+=' with .swapaxes() in native_core.py."""
    path = Path("control_lab/optimization/backends/native_core.py")
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "inv":
            assert not (
                isinstance(node.value, ast.Attribute) and node.value.attr == "linalg"
            ), f"Forbidden linalg.inv detected in {path}"
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                assert node.value.func.attr != "swapaxes", (
                    "Forbidden in-place '+=' with .swapaxes() aliasing detected in native_core.py"
                )
