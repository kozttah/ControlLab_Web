"""Unit tests for WP-PHASE9-01A-F6-INPLACE-WORKSPACE-PACKED-COO (ADR-015 Cycle 1).

Validates:
1. Zero-copy vectorized `F_k_packed` ingestion in `SDPBlock.from_dict` across
   `np.ndarray`, `memoryview` (typed and raw bytes), `bytes`, canonical `TensorDescriptor`,
   and Python `list`, including exact parity vs dense `F_k` / `F_k_sparse`, immutability,
   and strict `ValidationError` rejection of malformed inputs.
2. Unified 1D vectorized LP cone path for `1x1` PSD blocks in `native_core.py`
   (both dense and sparse `F_lp` paths): `validated_dual` parity vs `clarabel_direct`
   within `< 1e-6` and zero `1x1` eigendecompositions inside the IPM loop.
3. Pre-allocated in-place solver workspace on medium/large stabilization LMIs
   (`n=16`, 152 vars; `n=20`, 230 vars) ingested via `F_k_packed` with exact parity
   against dense/sparse `F_k` and `clarabel_direct`.
"""

from __future__ import annotations

import numpy as np
import pytest

from control_lab.core import array_to_tensor, tensor_to_array
from control_lab.diagnostics import ValidationError
from control_lab.optimization import (
    CanonicalSDPProblem,
    SDPBlock,
    continuous_stabilization_lmi,
    recover_controller,
    solve,
)
from control_lab.optimization.backends.native_core import (
    _factor_symmetric_system,
    _solve_factored_symmetric,
    _sym,
    solve_native_raw,
)


def _block_to_packed_arrays(blk: SDPBlock) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Extrai vetores COO empacotados (k_idx, rows, cols, vals) de um SDPBlock."""
    k_parts: list[np.ndarray] = []
    r_parts: list[np.ndarray] = []
    c_parts: list[np.ndarray] = []
    v_parts: list[np.ndarray] = []
    for k, fk in blk.F_terms.items():
        rows, cols = np.nonzero(np.abs(fk) > 0.0)
        if rows.size > 0:
            k_parts.append(np.full((rows.size,), k, dtype=np.int32))
            r_parts.append(rows.astype(np.int32))
            c_parts.append(cols.astype(np.int32))
            v_parts.append(fk[rows, cols].astype(np.float64))
    if not k_parts:
        return (
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float64),
        )
    return (
        np.concatenate(k_parts),
        np.concatenate(r_parts),
        np.concatenate(c_parts),
        np.concatenate(v_parts),
    )


def _problem_to_packed_payload(
    problem: CanonicalSDPProblem,
    *,
    mode: str = "ndarray",
) -> dict:
    """Converte CanonicalSDPProblem em payload dict usando F_k_packed no modo especificado."""
    base = problem.to_dict()
    packed_blocks = []
    for blk, blk_dict in zip(problem.blocks, base["blocks"], strict=True):
        k_idx, rows, cols, vals = _block_to_packed_arrays(blk)
        if mode == "ndarray":
            packed = {"k_idx": k_idx, "rows": rows, "cols": cols, "vals": vals}
        elif mode == "memoryview":
            packed = {
                "k_idx": memoryview(k_idx),
                "rows": memoryview(rows),
                "cols": memoryview(cols),
                "vals": memoryview(vals),
            }
        elif mode == "memoryview_bytes":
            packed = {
                "k_idx": memoryview(k_idx.tobytes()),
                "rows": memoryview(rows.tobytes()),
                "cols": memoryview(cols.tobytes()),
                "vals": memoryview(vals.tobytes()),
            }
        elif mode == "bytes":
            packed = {
                "k_idx": k_idx.tobytes(),
                "rows": rows.tobytes(),
                "cols": cols.tobytes(),
                "vals": vals.tobytes(),
            }
        elif mode == "tensor_descriptor":
            packed = {
                "k_idx": array_to_tensor(k_idx, dtype="int32", order="C"),
                "rows": array_to_tensor(rows, dtype="int32", order="C"),
                "cols": array_to_tensor(cols, dtype="int32", order="C"),
                "vals": array_to_tensor(vals, dtype="float64", order="C"),
            }
        elif mode == "list":
            packed = {
                "k_idx": k_idx.tolist(),
                "rows": rows.tolist(),
                "cols": cols.tolist(),
                "vals": vals.tolist(),
            }
        else:
            raise ValueError(f"Unknown mode: {mode}")
        packed_blocks.append({"name": blk_dict["name"], "F0": blk_dict["F0"], "F_k_packed": packed})

    payload = dict(base)
    payload["blocks"] = packed_blocks
    return payload


def _problem_to_sparse_payload(problem: CanonicalSDPProblem) -> dict:
    """Converte CanonicalSDPProblem em payload dict usando F_k_sparse (JSON COO legado)."""
    base = problem.to_dict()
    sparse_blocks = []
    for blk, blk_dict in zip(problem.blocks, base["blocks"], strict=True):
        fk_sparse: dict[str, list[list[float | int]]] = {}
        for k, fk in blk.F_terms.items():
            rows, cols = np.nonzero(np.abs(fk) > 0.0)
            fk_sparse[str(k)] = [[int(r), int(c), float(fk[r, c])] for r, c in zip(rows, cols, strict=True)]
        sparse_blocks.append({"name": blk_dict["name"], "F0": blk_dict["F0"], "F_k_sparse": fk_sparse})
    payload = dict(base)
    payload["blocks"] = sparse_blocks
    return payload


@pytest.mark.parametrize(
    "mode",
    ["ndarray", "memoryview", "memoryview_bytes", "bytes", "tensor_descriptor", "list"],
)
def test_f_k_packed_ingestion_parity_all_input_types(mode: str) -> None:
    """F_k_packed across all supported representations matches dense F_k and F_k_sparse bit-identically."""
    A = np.array([[0.0, 1.0, 0.0], [-2.0, -3.0, 0.5], [0.0, 0.0, 0.4]], dtype=np.float64)
    B = np.array([[0.0], [0.5], [1.0]], dtype=np.float64)
    prob_dense = continuous_stabilization_lmi(A, B, alpha=0.25)
    prob_sparse = CanonicalSDPProblem.from_dict(_problem_to_sparse_payload(prob_dense))
    prob_packed = CanonicalSDPProblem.from_dict(_problem_to_packed_payload(prob_dense, mode=mode))

    assert prob_packed.n_vars == prob_dense.n_vars
    assert prob_packed.n_blocks == prob_dense.n_blocks

    rng = np.random.default_rng(101)
    x_probe = rng.standard_normal(prob_dense.n_vars)
    for b_p, b_s, b_d in zip(prob_packed.blocks, prob_sparse.blocks, prob_dense.blocks, strict=True):
        np.testing.assert_array_equal(b_p.F0, b_d.F0)
        np.testing.assert_array_equal(b_p.evaluate(x_probe), b_d.evaluate(x_probe))
        np.testing.assert_array_equal(b_p.evaluate(x_probe), b_s.evaluate(x_probe))
        for k in range(prob_dense.n_vars):
            np.testing.assert_array_equal(b_p.get_Fk(k), b_d.get_Fk(k))
            np.testing.assert_array_equal(b_p.get_Fk(k), b_s.get_Fk(k))

    res_dense = solve(prob_dense, backend="native_primal_dual")
    res_packed = solve(prob_packed, backend="native_primal_dual")
    assert res_packed.status != "failure", res_packed.error
    assert res_packed.data["certificate_status"] == "validated_dual"
    np.testing.assert_array_equal(
        tensor_to_array(res_packed.data["x"]),
        tensor_to_array(res_dense.data["x"]),
    )


def test_f_k_packed_unsorted_duplicates_symmetrization_empty_and_immutability() -> None:
    """F_k_packed handles unsorted k_idx, duplicate (r,c), asymmetric entries, empty nnz, and deep immutability."""
    # Unsorted k_idx, duplicate (r, c) summed, and asymmetric upper-triangle entry symmetrized
    k_idx = np.array([2, 0, 2, 0], dtype=np.int32)
    rows = np.array([0, 0, 0, 0], dtype=np.int32)
    cols = np.array([1, 0, 1, 0], dtype=np.int32)
    vals = np.array([1.5, 2.0, 2.5, -0.5], dtype=np.float64)

    blk = SDPBlock.from_dict(
        {
            "name": "packed_edge",
            "F0": np.eye(2),
            "F_k_packed": {"k_idx": k_idx, "rows": rows, "cols": cols, "vals": vals},
        },
        n_vars=3,
    )
    # Mutating source arrays afterwards must NOT affect the immutable SDPBlock
    k_idx[...] = 0
    vals[...] = 999.0

    # k=0: (0,0) has 2.0 + (-0.5) = 1.5
    np.testing.assert_allclose(blk.get_Fk(0), np.array([[1.5, 0.0], [0.0, 0.0]]), atol=0.0)
    # k=1: inactive -> zeros
    np.testing.assert_array_equal(blk.get_Fk(1), np.zeros((2, 2)))
    # k=2: (0,1) has 1.5 + 2.5 = 4.0 -> symmetrized to [[0, 2.0], [2.0, 0]]
    np.testing.assert_allclose(blk.get_Fk(2), np.array([[0.0, 2.0], [2.0, 0.0]]), atol=0.0)

    # Empty nnz == 0 packed block
    blk_empty = SDPBlock.from_dict(
        {
            "name": "empty_packed",
            "F0": np.diag([1.0, 2.0]),
            "F_k_packed": {
                "k_idx": np.empty((0,), dtype=np.int32),
                "rows": np.empty((0,), dtype=np.int32),
                "cols": np.empty((0,), dtype=np.int32),
                "vals": np.empty((0,), dtype=np.float64),
            },
        },
        n_vars=4,
    )
    assert blk_empty.F_terms == {}
    np.testing.assert_array_equal(blk_empty.evaluate([1.0, 2.0, 3.0, 4.0]), np.diag([1.0, 2.0]))


def test_f_k_packed_validation_rejects_malformed_inputs() -> None:
    """F_k_packed rejects invalid shapes, dtypes, out-of-bounds indices, and NaN/Inf with ValidationError."""
    F0 = np.eye(2, dtype=np.float64)

    bad_cases = [
        # Missing n_vars
        ({"name": "b", "F0": F0, "F_k_packed": {"k_idx": [0], "rows": [0], "cols": [0], "vals": [1.0]}}, None),
        # Non-mapping F_k_packed
        ({"name": "b", "F0": F0, "F_k_packed": [1, 2, 3]}, 2),
        # Missing required field
        ({"name": "b", "F0": F0, "F_k_packed": {"k_idx": [0], "rows": [0], "cols": [0]}}, 2),
        # 2D shape instead of 1D
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.zeros((1, 1), dtype=np.int32),
                    "rows": np.zeros((1,), dtype=np.int32),
                    "cols": np.zeros((1,), dtype=np.int32),
                    "vals": np.ones((1,), dtype=np.float64),
                },
            },
            2,
        ),
        # 2D memoryview
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": memoryview(np.zeros((1, 1), dtype=np.int32)),
                    "rows": np.zeros((1,), dtype=np.int32),
                    "cols": np.zeros((1,), dtype=np.int32),
                    "vals": np.ones((1,), dtype=np.float64),
                },
            },
            2,
        ),
        # Mismatched lengths
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.array([0, 1], dtype=np.int32),
                    "rows": np.array([0], dtype=np.int32),
                    "cols": np.array([0, 1], dtype=np.int32),
                    "vals": np.array([1.0, 2.0], dtype=np.float64),
                },
            },
            2,
        ),
        # Float dtype for k_idx
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.array([0.0], dtype=np.float64),
                    "rows": np.array([0], dtype=np.int32),
                    "cols": np.array([0], dtype=np.int32),
                    "vals": np.array([1.0], dtype=np.float64),
                },
            },
            2,
        ),
        # Bool dtype for rows / vals
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.array([0], dtype=np.int32),
                    "rows": np.array([True], dtype=np.bool_),
                    "cols": np.array([0], dtype=np.int32),
                    "vals": np.array([1.0], dtype=np.float64),
                },
            },
            2,
        ),
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.array([0], dtype=np.int32),
                    "rows": np.array([0], dtype=np.int32),
                    "cols": np.array([0], dtype=np.int32),
                    "vals": np.array([True], dtype=np.bool_),
                },
            },
            2,
        ),
        # TensorDescriptor with wrong dtype for k_idx
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": array_to_tensor(np.array([0.0], dtype=np.float64), dtype="float64", order="C"),
                    "rows": np.array([0], dtype=np.int32),
                    "cols": np.array([0], dtype=np.int32),
                    "vals": np.array([1.0], dtype=np.float64),
                },
            },
            2,
        ),
        # Misaligned raw bytes
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": b"\x00\x01\x02",
                    "rows": b"\x00\x00\x00\x00",
                    "cols": b"\x00\x00\x00\x00",
                    "vals": np.array([1.0], dtype=np.float64).tobytes(),
                },
            },
            2,
        ),
        # Out-of-bounds k_idx (negative, >= n_vars, and int64 wraparound 2**32)
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {"k_idx": [-1], "rows": [0], "cols": [0], "vals": [1.0]},
            },
            2,
        ),
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {"k_idx": [2], "rows": [0], "cols": [0], "vals": [1.0]},
            },
            2,
        ),
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.array([1 << 32], dtype=np.int64),
                    "rows": np.array([0], dtype=np.int32),
                    "cols": np.array([0], dtype=np.int32),
                    "vals": np.array([1.0], dtype=np.float64),
                },
            },
            2,
        ),
        # Out-of-bounds rows / cols
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {"k_idx": [0], "rows": [2], "cols": [0], "vals": [1.0]},
            },
            2,
        ),
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {"k_idx": [0], "rows": [0], "cols": [-1], "vals": [1.0]},
            },
            2,
        ),
        # NaN and Inf in vals
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.array([0], dtype=np.int32),
                    "rows": np.array([0], dtype=np.int32),
                    "cols": np.array([0], dtype=np.int32),
                    "vals": np.array([np.nan], dtype=np.float64),
                },
            },
            2,
        ),
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.array([0], dtype=np.int32),
                    "rows": np.array([0], dtype=np.int32),
                    "cols": np.array([0], dtype=np.int32),
                    "vals": np.array([np.inf], dtype=np.float64),
                },
            },
            2,
        ),
        (
            {
                "name": "b",
                "F0": F0,
                "F_k_packed": {
                    "k_idx": np.array([0], dtype=np.int32),
                    "rows": np.array([0], dtype=np.int32),
                    "cols": np.array([0], dtype=np.int32),
                    "vals": np.array([-np.inf], dtype=np.float64),
                },
            },
            2,
        ),
    ]

    for payload, nv in bad_cases:
        with pytest.raises(ValidationError):
            SDPBlock.from_dict(payload, n_vars=nv)


def test_unified_1d_lp_cone_mixed_20_scalars_plus_2_psd_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mixed problem (20x 1x1 scalar blocks + 2x 4x4 PSD blocks) uses 1D LP cone with zero 1x1 eigvalsh calls."""
    rng = np.random.default_rng(2026)
    m = 8
    blocks: list[SDPBlock] = []

    # 2 coupled 4x4 PSD blocks: F_b(x) = F0_b + x_0 * I_4 + sum_{k=1}^{m-1} x_k * A_{b,k} >= 0
    for b in range(2):
        Q = rng.standard_normal((4, 4))
        F0 = _sym(Q @ Q.T) * 0.2 - (1.8 + 0.3 * b) * np.eye(4)
        F_terms: dict[int, np.ndarray] = {0: np.eye(4, dtype=np.float64)}
        for k in range(1, m):
            M = rng.standard_normal((4, 4)) * 0.15
            F_terms[k] = _sym(M)
        blocks.append(SDPBlock(f"psd_block_{b}", F0, F_terms, n_vars=m))

    # 20 scalar 1x1 blocks: box bounds on x_1..x_{m-1} plus active lower/upper bounds on x_0
    # Box bounds |x_k| <= 1.5 for k = 1..7 (14 scalar 1x1 blocks)
    for k in range(1, m):
        blocks.append(
            SDPBlock(f"box_pos_{k}", np.array([[1.5]]), {k: np.array([[1.0]])}, n_vars=m)
        )
        blocks.append(
            SDPBlock(f"box_neg_{k}", np.array([[1.5]]), {k: np.array([[-1.0]])}, n_vars=m)
        )
    # 6 additional scalar coupling inequalities (including active lower bound on x_0)
    for s in range(6):
        row = rng.standard_normal(m) * 0.1
        row[0] = 1.0
        rhs0 = -1.2 + 0.1 * s
        blocks.append(
            SDPBlock(
                f"scalar_coupling_{s}",
                np.array([[rhs0]]),
                {k: np.array([[float(row[k])]]) for k in range(m)},
                n_vars=m,
            )
        )

    c = np.zeros((m,), dtype=np.float64)
    c[0] = 1.0
    c[1] = 0.25
    c[2] = -0.15
    problem = CanonicalSDPProblem(c=c, blocks=blocks, name="mixed_2psd_20scalar")

    # Track matrix sizes passed to np.linalg.eigvalsh during solve_native_raw
    orig_eigvalsh = np.linalg.eigvalsh
    eig_dims: list[int] = []

    def _counting_eigvalsh(a, UPLO="L"):
        arr = np.asarray(a)
        eig_dims.append(int(arr.shape[-1]))
        return orig_eigvalsh(arr, UPLO=UPLO)

    monkeypatch.setattr(np.linalg, "eigvalsh", _counting_eigvalsh)
    raw = solve_native_raw(problem)
    monkeypatch.undo()

    # Zero 1x1 matrices should ever hit np.linalg.eigvalsh in native_core!
    assert len(eig_dims) > 0
    assert all(d > 1 for d in eig_dims), f"1x1 blocks must bypass eigvalsh, saw dims={set(eig_dims)}"
    assert raw["solver_status"] == "optimal"

    # Full verified solve parity against clarabel_direct within < 1e-6
    res_nat = solve(problem, backend="native_primal_dual")
    res_cl = solve(problem, backend="clarabel_direct")
    assert res_nat.status != "failure", res_nat.error
    assert res_cl.status != "failure", res_cl.error
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_cl.data["certificate_status"] == "validated_dual"
    assert res_nat.data["objective"] == pytest.approx(res_cl.data["objective"], rel=1e-6, abs=1e-6)
    assert res_nat.data["residuals"]["duality_gap_rel"] < 1e-7
    assert res_nat.data["residuals"]["dual_stationarity_rel"] < 1e-7
    # On a smooth spectrahedron boundary, O(1e-9) objective gap corresponds to O(sqrt(1e-9)) ~ 1e-4 in x
    np.testing.assert_allclose(
        tensor_to_array(res_nat.data["x"]),
        tensor_to_array(res_cl.data["x"]),
        rtol=1e-3,
        atol=1e-3,
    )


def test_unified_1d_lp_cone_pure_lp_zero_eigvalsh_and_sparse_lp_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pure 1x1 LP invokes zero eigvalsh calls; sparse LP branch (q*m > 16384, <15% nnz) matches Clarabel."""
    # Part A: Pure 1x1 LP problem -> ZERO eigvalsh calls in solve_native_raw
    m_lp = 6
    blocks_lp = []
    for k in range(m_lp):
        blocks_lp.append(SDPBlock(f"lb_{k}", np.array([[-1.0 - 0.1 * k]]), {k: np.array([[1.0]])}, n_vars=m_lp))
        blocks_lp.append(SDPBlock(f"ub_{k}", np.array([[5.0]]), {k: np.array([[-1.0]])}, n_vars=m_lp))
    prob_lp = CanonicalSDPProblem(c=np.arange(1.0, m_lp + 1.0), blocks=blocks_lp, name="pure_lp_1x1")

    orig_eigvalsh = np.linalg.eigvalsh
    eig_calls = 0

    def _counting_eigvalsh(a, UPLO="L"):
        nonlocal eig_calls
        eig_calls += 1
        return orig_eigvalsh(a, UPLO=UPLO)

    monkeypatch.setattr(np.linalg, "eigvalsh", _counting_eigvalsh)
    raw_lp = solve_native_raw(prob_lp)
    monkeypatch.undo()

    assert eig_calls == 0, f"Pure 1x1 LP should make 0 eigvalsh calls, got {eig_calls}"
    assert raw_lp["solver_status"] == "optimal"
    res_lp_nat = solve(prob_lp, backend="native_primal_dual")
    res_lp_cl = solve(prob_lp, backend="clarabel_direct")
    assert res_lp_nat.data["certificate_status"] == "validated_dual"
    assert res_lp_nat.data["objective"] == pytest.approx(res_lp_cl.data["objective"], abs=1e-6)

    # Part B: Sparse LP cone path (q_lp * m > 16384, density < 15%): m = 130, q_lp = 260 (box bounds) + 1x 2x2 PSD
    m_sp = 130
    blocks_sp: list[SDPBlock] = [
        SDPBlock(
            "psd_small",
            np.array([[-1.0, 0.25], [0.25, -1.0]]),
            {0: np.eye(2), 1: np.array([[0.1, 0.0], [0.0, -0.1]])},
            n_vars=m_sp,
        )
    ]
    for k in range(m_sp):
        blocks_sp.append(SDPBlock(f"lo_{k}", np.array([[1.0]]), {k: np.array([[1.0]])}, n_vars=m_sp))
        blocks_sp.append(SDPBlock(f"hi_{k}", np.array([[3.0]]), {k: np.array([[-1.0]])}, n_vars=m_sp))
    c_sp = np.linspace(0.5, 1.5, m_sp, dtype=np.float64)
    prob_sp = CanonicalSDPProblem(c=c_sp, blocks=blocks_sp, name="sparse_lp_cone_branch")

    res_sp_nat = solve(prob_sp, backend="native_primal_dual")
    res_sp_cl = solve(prob_sp, backend="clarabel_direct")
    assert res_sp_nat.status != "failure", res_sp_nat.error
    assert res_sp_nat.data["certificate_status"] == "validated_dual"
    assert res_sp_cl.data["certificate_status"] == "validated_dual"
    assert res_sp_nat.data["objective"] == pytest.approx(res_sp_cl.data["objective"], rel=1e-6, abs=1e-6)


def test_inplace_schur_factor_and_solve_workspace_buffers() -> None:
    """_factor_symmetric_system and _solve_factored_symmetric reuse caller-provided buffers in-place."""
    rng = np.random.default_rng(77)
    n = 24
    M = rng.standard_normal((n, n))
    H = _sym(M.T @ M + 1e-3 * np.eye(n))
    rhs = rng.standard_normal(n)

    H_scaled_buf = np.empty((n, n), dtype=np.float64)
    H_work_buf = np.empty((n, n), dtype=np.float64, order="F")
    inv_d_buf = np.empty((n,), dtype=np.float64)
    out_buf = np.empty((n,), dtype=np.float64)
    rhs_scaled_buf = np.empty((n,), dtype=np.float64)
    res_s_buf = np.empty((n,), dtype=np.float64)
    mv_buf = np.empty((n,), dtype=np.float64)

    fac = _factor_symmetric_system(
        H, H_scaled_buf=H_scaled_buf, H_work_buf=H_work_buf, inv_d_buf=inv_d_buf
    )
    assert fac.H_scaled is H_scaled_buf
    assert fac.inv_d is inv_d_buf
    assert fac.cho is not None and not fac.regularized

    sol = _solve_factored_symmetric(
        fac,
        rhs,
        out=out_buf,
        rhs_scaled_buf=rhs_scaled_buf,
        res_s_buf=res_s_buf,
        mv_buf=mv_buf,
    )
    assert sol is out_buf
    assert float(np.linalg.norm(H @ sol - rhs)) <= 1e-11 * float(np.linalg.norm(rhs))


@pytest.mark.parametrize(("n", "expected_vars"), [(16, 152), (20, 230)])
def test_large_stabilization_lmi_f_k_packed_inplace_vs_dense_sparse_and_clarabel(
    n: int,
    expected_vars: int,
) -> None:
    """Medium/large stabilization LMI (n=16/152 vars and n=20/230 vars) solves via F_k_packed + in-place workspace."""
    alpha = 0.2
    A = np.diag([-1.0 - 0.1 * i for i in range(n - 1)] + [0.5])
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0

    prob_dense = continuous_stabilization_lmi(A, B, alpha=alpha)
    assert prob_dense.n_vars == expected_vars

    prob_sparse = CanonicalSDPProblem.from_dict(_problem_to_sparse_payload(prob_dense))
    prob_packed = CanonicalSDPProblem.from_dict(_problem_to_packed_payload(prob_dense, mode="memoryview"))

    # Bit-identical evaluation parity across dense, sparse, and packed
    rng = np.random.default_rng(n)
    x_probe = rng.standard_normal(expected_vars)
    for b_p, b_s, b_d in zip(prob_packed.blocks, prob_sparse.blocks, prob_dense.blocks, strict=True):
        np.testing.assert_array_equal(b_p.evaluate(x_probe), b_d.evaluate(x_probe))
        np.testing.assert_array_equal(b_p.evaluate(x_probe), b_s.evaluate(x_probe))

    res_packed = solve(prob_packed, backend="native_primal_dual")
    res_dense = solve(prob_dense, backend="native_primal_dual")
    res_sparse = solve(prob_sparse, backend="native_primal_dual")
    res_cl = solve(prob_dense, backend="clarabel_direct")

    for res in (res_packed, res_dense, res_sparse, res_cl):
        assert res.status != "failure", res.error
        assert res.data["certificate_status"] == "validated_dual"

    # Exact parity between packed, dense, and sparse native solves
    x_packed = tensor_to_array(res_packed.data["x"])
    np.testing.assert_array_equal(x_packed, tensor_to_array(res_dense.data["x"]))
    np.testing.assert_array_equal(x_packed, tensor_to_array(res_sparse.data["x"]))

    # Controller recovery and closed-loop stability parity against Clarabel
    ctrl_packed = recover_controller(prob_packed, res_packed)
    ctrl_cl = recover_controller(prob_dense, res_cl)
    assert ctrl_packed.data["controller_validity"] == "verified_under_assumptions"
    assert ctrl_cl.data["controller_validity"] == "verified_under_assumptions"

    K_packed = tensor_to_array(ctrl_packed.data["K"])
    K_cl = tensor_to_array(ctrl_cl.data["K"])
    assert float(np.max(np.linalg.eigvals(A + B @ K_packed).real)) < -alpha
    assert float(np.max(np.linalg.eigvals(A + B @ K_cl).real)) < -alpha
