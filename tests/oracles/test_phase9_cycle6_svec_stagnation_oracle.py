"""Independent F9 oracle audit for Phase 9 Cycle 6 (ADR-015: svec Schur Isometry & HSDE Stagnation 1b').

Must pass with ZERO skips in both `core_no_sdp` and `sdp_available` CI profiles.
When `clarabel` is installed, performs strict independent parity verification against
`clarabel_direct` without any tolerance relaxation.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

import numpy as np

from control_lab.core.tensors import tensor_to_array
from control_lab.optimization import (
    CanonicalSDPProblem,
    SDPBlock,
    continuous_stabilization_lmi,
    recover_controller,
    solve,
    verify,
)
from control_lab.optimization.backends.native_core import (
    _InternalConeBlock,
    _fill_f3_scaled_cols,
    _mat_to_svec,
    _svec_to_mat_into,
    solve_native_raw,
)


def _clarabel_available() -> bool:
    return importlib.util.find_spec("clarabel") is not None


def _sym(mat: np.ndarray) -> np.ndarray:
    return 0.5 * (mat + mat.T)


def _independent_svec(mat: np.ndarray) -> np.ndarray:
    """Independent reference implementation of Todd-Toh-Tutuncu (1998) svec(M) isometry."""
    dim = mat.shape[0]
    sqrt2 = float(np.sqrt(2.0))
    out: list[float] = []
    for i in range(dim):
        for j in range(i, dim):
            val = float(mat[i, j])
            out.append(val if i == j else sqrt2 * val)
    return np.asarray(out, dtype=np.float64)


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


def _build_stiff_blkdiag_24x8_oracle(*, seed: int = 20260624) -> CanonicalSDPProblem:
    """Independent stiff 24x8 block-diagonal SDP with multi-scale conditioning (1..16x)."""
    rng = np.random.default_rng(seed)
    n_blocks = 24
    blk_dim = 8
    n_local = 4
    n_vars = n_blocks * n_local
    c = np.zeros((n_vars,), dtype=np.float64)
    blocks: list[SDPBlock] = []

    for b in range(n_blocks):
        scale = 2.0 ** (b % 5)  # 1.0 .. 16.0 multi-scale stiffness across 24 blocks
        A = rng.standard_normal((blk_dim, blk_dim)) * 0.22
        F0 = scale * (_sym(A) + 4.2 * np.eye(blk_dim, dtype=np.float64))
        f_terms: dict[int, np.ndarray] = {}
        base = b * n_local
        for k in range(n_local):
            M = np.zeros((blk_dim, blk_dim), dtype=np.float64)
            i0 = (2 * k) % blk_dim
            i1 = (2 * k + 1) % blk_dim
            M[i0, i0] = scale
            M[i1, i1] = 0.85 * scale
            M[i0, i1] = M[i1, i0] = 0.28 * scale
            f_terms[base + k] = M
            c[base + k] = scale * (1.0 + 0.12 * k)
        blocks.append(SDPBlock(name=f"f9_blkdiag_{b}", F0=F0, F_k=f_terms, n_vars=n_vars))

    return CanonicalSDPProblem(name="f9_oracle_BlkDiag_24x8_stiff", c=c, c0=0.0, blocks=tuple(blocks))


def _build_dense_a_stabilization_n40(*, alpha: float = 0.20, seed: int = 40860) -> tuple[np.ndarray, np.ndarray, CanonicalSDPProblem]:
    """Build a dense-A continuous stabilization LMI of order n=40 (m = 40*41//2 + 40 = 860)."""
    rng = np.random.default_rng(seed)
    n = 40
    # Dense Hurwitz base matrix + controlled unstable rank-1 perturbation in the last mode
    Q, _ = np.linalg.qr(rng.standard_normal((n, n)))
    eigs = np.linspace(-3.0, -0.6, n, dtype=np.float64)
    eigs[-1] = 0.35  # single unstable mode to stabilize
    A = Q @ np.diag(eigs) @ Q.T
    # Input matrix aligned with the unstable eigenvector + dense coupling
    B = (Q[:, -1:] * 1.5 + 0.08 * rng.standard_normal((n, 1))).astype(np.float64)
    prob = continuous_stabilization_lmi(A, B, alpha=alpha)
    return A, B, prob


# ---------------------------------------------------------------------------
# 1. svec Isometry + Aliasing-Free F2 / F3_blas Schur Assembly (atol=1e-12)
# ---------------------------------------------------------------------------


def test_f9_cycle6_svec_isometry_and_f2_f3_aliasing_free_oracle() -> None:
    """Independent verification of svec isometry and F2/F3_blas Schur assembly against explicit tr(W F_i W F_j)."""
    rng = np.random.default_rng(60606)

    # 1a. Independent svec isometry check across multiple dimensions
    for dim in (1, 3, 8, 19):
        A = _sym(rng.standard_normal((dim, dim)))
        B = _sym(rng.standard_normal((dim, dim)))
        va = _mat_to_svec(A)
        vb = _mat_to_svec(B)
        va_ref = _independent_svec(A)
        vb_ref = _independent_svec(B)

        assert va.shape == (dim * (dim + 1) // 2,)
        np.testing.assert_allclose(va, va_ref, rtol=1e-13, atol=1e-13)
        np.testing.assert_allclose(vb, vb_ref, rtol=1e-13, atol=1e-13)

        frob_ip = float(np.sum(A * B))
        assert abs(float(np.dot(va, vb)) - frob_ip) <= 1e-12 * max(1.0, abs(frob_ip))

        A_rec = np.empty_like(A)
        _svec_to_mat_into(va, A_rec)
        np.testing.assert_allclose(A_rec, A, rtol=1e-14, atol=1e-14)

    # 1b. Independent tr(W F_i W F_j) oracle vs F2 (svec CSR) and F3_blas (chunked congruence)
    dim = 12
    n_svec = dim * (dim + 1) // 2
    n_act = 68  # exceeds both _F2_CHUNK_SIZE (32) and _F3_CHUNK_SIZE (64)
    terms: dict[int, np.ndarray] = {}
    for j in range(n_act):
        mat = np.zeros((dim, dim), dtype=np.float64)
        idx = rng.choice(dim, size=4, replace=False)
        sub = rng.standard_normal((4, 4))
        mat[np.ix_(idx, idx)] = _sym(sub)
        terms[j] = mat

    blk_f2 = _InternalConeBlock(name="f9_f2_svec", dim=dim, F0=np.eye(dim), F_terms=terms)
    blk_f3 = _InternalConeBlock(
        name="f9_f3_svec", dim=dim, F0=np.eye(dim), F_terms=terms, force_schur_mode="F3_blas"
    )
    assert blk_f2.schur_mode == "F2"
    assert blk_f2._F_svec_csr is not None
    assert blk_f2._F_svec_csr.shape == (n_act, n_svec)
    assert blk_f3.schur_mode == "F3_blas"
    assert blk_f3._F_cols is not None

    # Deliberately asymmetric scaling factor G_invT so in-place swapaxes aliasing would corrupt off-diagonals
    G_invT = rng.standard_normal((dim, dim)) * 0.35 + 1.8 * np.eye(dim, dtype=np.float64)
    G_invT[0, -1] += 2.1
    G_invT[-1, 0] -= 1.3
    W = G_invT @ G_invT.T

    # Independent Frobenius-trace reference H_ref[i, j] = tr(W F_i W F_j)
    WF = [W @ terms[j] for j in range(n_act)]
    H_ref = np.empty((n_act, n_act), dtype=np.float64)
    for i in range(n_act):
        for j in range(i, n_act):
            val = float(np.sum(WF[i] * WF[j].T))
            H_ref[i, j] = val
            H_ref[j, i] = val

    # Verify _fill_f3_scaled_cols columns against independent svec(sym(G_invT^T F_j G_invT))
    cols_svec = np.empty((n_svec, n_act), dtype=np.float64)
    _fill_f3_scaled_cols(blk_f3._F_cols, G_invT, dim, cols_svec)
    for j in range(n_act):
        ref_col = _independent_svec(_sym(G_invT.T @ terms[j] @ G_invT))
        np.testing.assert_allclose(cols_svec[:, j], ref_col, rtol=1e-12, atol=1e-12)

    H_f2 = np.empty((n_act, n_act), dtype=np.float64)
    H_f3 = np.empty((n_act, n_act), dtype=np.float64)
    blk_f2.assemble_schur_block(W, H_f2)
    blk_f3.assemble_schur_block(W, H_f3)

    np.testing.assert_allclose(H_f2, H_ref, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(H_f3, H_ref, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(cols_svec.T @ cols_svec, H_ref, rtol=1e-12, atol=1e-12)

    # 1c. Independent AST guard on native_core.py (zero linalg.inv and zero in-place += .swapaxes)
    native_core_path = Path(__file__).resolve().parents[2] / "control_lab" / "optimization" / "backends" / "native_core.py"
    tree = ast.parse(native_core_path.read_text(encoding="utf-8"), filename=str(native_core_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "inv":
            assert not (
                isinstance(node.value, ast.Attribute) and node.value.attr == "linalg"
            ), "Forbidden linalg.inv detected in native_core.py"
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                assert node.value.func.attr != "swapaxes", (
                    "Forbidden in-place '+=' with .swapaxes() aliasing detected in native_core.py"
                )


# ---------------------------------------------------------------------------
# 2. Early Stagnation Safeguard 1b' on Stiff BlkDiag_24x8 (No 80-Iter Spin)
# ---------------------------------------------------------------------------


def test_f9_cycle6_blkdiag_24x8_early_stagnation_oracle() -> None:
    """Stiff BlkDiag_24x8 converges early without 80-iter spin, passes 5D verify(), and matches Clarabel < 1e-6."""
    prob = _build_stiff_blkdiag_24x8_oracle()
    assert prob.n_vars == 96
    assert len(prob.blocks) == 24

    raw = solve_native_raw(prob)
    assert raw["solver_status"] == "optimal"
    assert raw["iterations"] < 40, (
        f"Expected early convergence well below 80-iter spin, got {raw['iterations']} iterations"
    )

    res_nat = solve(prob, backend="native_primal_dual")
    assert res_nat.status in ("success", "warning"), res_nat.error
    assert res_nat.data is not None
    assert res_nat.data["solver_status"] == "optimal"
    assert res_nat.data["certificate_status"] == "validated_dual"

    # Independent 5D verification on original problem
    audited = verify(prob, _extract_solution_for_verify(res_nat.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"
    assert audited.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    # Independent Clarabel parity when installed (zero skips in core_no_sdp)
    if _clarabel_available():
        res_cl = solve(prob, backend="clarabel_direct")
        assert res_cl.data is not None
        assert res_cl.data["certificate_status"] == "validated_dual"
        obj_nat = float(res_nat.data["objective"])
        obj_cl = float(res_cl.data["objective"])
        assert abs(obj_nat - obj_cl) < 1e-6, (
            f"BlkDiag_24x8 objective mismatch: native={obj_nat:.10f} vs clarabel={obj_cl:.10f}"
        )


# ---------------------------------------------------------------------------
# 3. Dense-A Stabilization (n=40, m=860, F2 svec path) + 5D Verify & Clarabel
# ---------------------------------------------------------------------------


def test_f9_cycle6_dense_a_stabilization_n40_m860_f2_svec_oracle() -> None:
    """Dense-A continuous stabilization (n=40, m=860) exercises F2 svec, validates 5D dual, and matches Clarabel."""
    alpha = 0.20
    A, B, prob = _build_dense_a_stabilization_n40(alpha=alpha)
    assert prob.n_vars == 860

    # Confirm at least one PSD block engages the F2 svec path
    f2_blocks = 0
    for blk in prob.blocks:
        f_terms = {k: mat for k, mat in enumerate(blk.F_k) if np.any(mat != 0.0)}
        ib = _InternalConeBlock(name=blk.name, dim=blk.dim, F0=blk.F0, F_terms=f_terms)
        if ib.schur_mode == "F2":
            assert ib._F_svec_csr is not None
            assert ib._F_svec_csr.shape[1] == blk.dim * (blk.dim + 1) // 2
            f2_blocks += 1
    assert f2_blocks >= 1, "Expected n=40 dense-A stabilization to engage F2 svec path"

    res_nat = solve(prob, backend="native_primal_dual")
    assert res_nat.status in ("success", "warning"), res_nat.error
    assert res_nat.data is not None
    assert res_nat.data["solver_status"] == "optimal"
    assert res_nat.data["certificate_status"] == "validated_dual"

    # Independent 5D verification
    audited = verify(prob, _extract_solution_for_verify(res_nat.data))
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"
    assert audited.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    # Closed-loop pole placement verification
    ctrl = recover_controller(prob, res_nat)
    assert ctrl.data is not None
    assert ctrl.data["controller_validity"] == "verified_under_assumptions"
    K = tensor_to_array(ctrl.data["K"], expected_ndim=2, dtype="float64")
    max_real_eig = float(np.max(np.linalg.eigvals(A + B @ K).real))
    assert max_real_eig < -alpha, f"Closed-loop max Re(eig) = {max_real_eig:.6f} >= -{alpha}"

    # Independent Clarabel parity when installed (zero skips in core_no_sdp)
    if _clarabel_available():
        res_cl = solve(prob, backend="clarabel_direct")
        assert res_cl.data is not None
        assert res_cl.data["certificate_status"] == "validated_dual"
        obj_nat = float(res_nat.data["objective"])
        obj_cl = float(res_cl.data["objective"])
        assert abs(obj_nat - obj_cl) < 1e-6, (
            f"denseA n=40 (m=860) mismatch: native={obj_nat:.10f} vs clarabel={obj_cl:.10f}"
        )
