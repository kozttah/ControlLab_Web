"""Independent F9 oracle audit for Phase 9 Cycle 1 (ADR-015: F_k_packed zero-copy, 1D LP cone, in-place workspace).

Must run with ZERO skips in both `core_no_sdp` and `sdp_available` CI profiles.
When `clarabel` is installed, performs strict independent parity verification against
`clarabel_direct` without any tolerance relaxation.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np
import pytest

from control_lab.core.rpc import RPC_API_VERSION, dispatch_rpc
from control_lab.core.tensors import tensor_to_array
from control_lab.optimization import (
    CanonicalSDPProblem,
    SDPBlock,
    continuous_stabilization_lmi,
    recover_controller,
    solve,
    verify,
)


def _clarabel_available() -> bool:
    return importlib.util.find_spec("clarabel") is not None


def _build_stabilization_problem(n: int, alpha: float = 0.25) -> tuple[CanonicalSDPProblem, np.ndarray, np.ndarray]:
    """Build a deterministic controllable n-state stabilization LMI problem."""
    # Stable modes plus one unstable mode coupled to a single input
    diag_vals = [-1.0 - 0.15 * i for i in range(n - 1)] + [0.45]
    A = np.diag(diag_vals).astype(np.float64)
    for i in range(n - 1):
        A[i, i + 1] = 0.2
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    B[-2, 0] = 0.25
    prob = continuous_stabilization_lmi(A, B, alpha=alpha)
    return prob, A, B


def _build_mixed_psd_and_24_lp_problem() -> CanonicalSDPProblem:
    """Build a mixed problem with 2 coupled 4x4 PSD blocks and 24 scalar 1x1 LP blocks."""
    rng = np.random.default_rng(9015)
    m = 10
    blocks: list[SDPBlock] = []

    # 2 coupled 4x4 PSD blocks: F_b(x) = F0_b + x_0 * I_4 + sum_{k=1}^{m-1} x_k * A_{b,k} >= 0
    for b in range(2):
        Q = rng.standard_normal((4, 4))
        F0 = 0.5 * (Q @ Q.T) * 0.15 - (1.6 + 0.25 * b) * np.eye(4, dtype=np.float64)
        F_terms: dict[int, np.ndarray] = {0: np.eye(4, dtype=np.float64)}
        for k in range(1, m):
            M = rng.standard_normal((4, 4)) * 0.12
            F_terms[k] = 0.5 * (M + M.T)
        blocks.append(SDPBlock(f"psd_{b}", F0, F_terms, n_vars=m))

    # 18 box-bound 1x1 scalar blocks: -1.5 <= x_k <= 1.5 for k = 1..9
    for k in range(1, m):
        blocks.append(
            SDPBlock(f"lp_lo_{k}", np.array([[1.5]], dtype=np.float64), {k: np.array([[1.0]])}, n_vars=m)
        )
        blocks.append(
            SDPBlock(f"lp_hi_{k}", np.array([[1.5]], dtype=np.float64), {k: np.array([[-1.0]])}, n_vars=m)
        )

    # 6 additional scalar coupling 1x1 LP blocks -> 24 total 1x1 scalar blocks
    for s in range(6):
        coeffs = rng.standard_normal(m) * 0.08
        coeffs[0] = 1.0
        rhs = -1.1 + 0.08 * s
        blocks.append(
            SDPBlock(
                f"lp_coupling_{s}",
                np.array([[rhs]], dtype=np.float64),
                {k: np.array([[float(coeffs[k])]]) for k in range(m)},
                n_vars=m,
            )
        )

    c = np.zeros((m,), dtype=np.float64)
    c[0] = 1.0
    c[1] = 0.3
    c[2] = -0.2
    c[3] = 0.15
    return CanonicalSDPProblem(c=c, blocks=blocks, name="f9_mixed_2psd_24lp")


def _problem_to_worker_packed_envelope(
    problem: CanonicalSDPProblem,
    *,
    operation: str = "optimization.solve",
    request_id: str = "f9-packed-req",
    extra_payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[np.ndarray]]:
    """Construct Worker RPC envelope {request, payload, buffers} using zero-copy memoryviews for F_k_packed."""
    base = problem.to_dict()
    packed_blocks: list[dict[str, Any]] = []
    buffers: dict[str, memoryview] = {}
    pinned_arrays: list[np.ndarray] = []

    for b_idx, (blk, blk_dict) in enumerate(zip(problem.blocks, base["blocks"], strict=True)):
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

        if k_parts:
            k_arr = np.ascontiguousarray(np.concatenate(k_parts), dtype=np.int32)
            r_arr = np.ascontiguousarray(np.concatenate(r_parts), dtype=np.int32)
            c_arr = np.ascontiguousarray(np.concatenate(c_parts), dtype=np.int32)
            v_arr = np.ascontiguousarray(np.concatenate(v_parts), dtype=np.float64)
        else:
            k_arr = np.empty((0,), dtype=np.int32)
            r_arr = np.empty((0,), dtype=np.int32)
            c_arr = np.empty((0,), dtype=np.int32)
            v_arr = np.empty((0,), dtype=np.float64)

        pinned_arrays.extend([k_arr, r_arr, c_arr, v_arr])
        nnz = int(k_arr.shape[0])

        k_ref = f"blk{b_idx}_k_idx"
        r_ref = f"blk{b_idx}_rows"
        c_ref = f"blk{b_idx}_cols"
        v_ref = f"blk{b_idx}_vals"
        buffers[k_ref] = memoryview(k_arr)
        buffers[r_ref] = memoryview(r_arr)
        buffers[c_ref] = memoryview(c_arr)
        buffers[v_ref] = memoryview(v_arr)

        packed_blocks.append(
            {
                "name": blk_dict["name"],
                "F0": blk_dict["F0"],
                "n_vars": problem.n_vars,
                "F_k_packed": {
                    "k_idx": {"shape": [nnz], "dtype": "int32", "order": "C", "buffer_ref": k_ref},
                    "rows": {"shape": [nnz], "dtype": "int32", "order": "C", "buffer_ref": r_ref},
                    "cols": {"shape": [nnz], "dtype": "int32", "order": "C", "buffer_ref": c_ref},
                    "vals": {"shape": [nnz], "dtype": "float64", "order": "C", "buffer_ref": v_ref},
                },
            }
        )

    problem_payload = dict(base)
    problem_payload["blocks"] = packed_blocks

    payload: dict[str, Any] = {
        "problem": problem_payload,
        "backend": "native_primal_dual",
    }
    if extra_payload:
        payload.update(extra_payload)

    envelope = {
        "request": {
            "api_version": RPC_API_VERSION,
            "request_id": request_id,
            "project_id": "f9-phase9-cycle1-oracle",
            "project_revision": 1,
            "operation": operation,
            "payload": {},
            "options": {},
            "timeout_policy": {"hard_timeout_ms": 60000},
        },
        "payload": payload,
        "buffers": buffers,
    }
    return envelope, pinned_arrays


def _problem_to_sparse_dict(problem: CanonicalSDPProblem) -> dict[str, Any]:
    """Serialize problem using legacy JSON COO F_k_sparse."""
    base = problem.to_dict()
    sparse_blocks: list[dict[str, Any]] = []
    for blk, blk_dict in zip(problem.blocks, base["blocks"], strict=True):
        fk_sparse: dict[str, list[list[float | int]]] = {}
        for k, fk in blk.F_terms.items():
            rows, cols = np.nonzero(np.abs(fk) > 0.0)
            fk_sparse[str(k)] = [[int(r), int(c), float(fk[r, c])] for r, c in zip(rows, cols, strict=True)]
        sparse_blocks.append({"name": blk_dict["name"], "F0": blk_dict["F0"], "F_k_sparse": fk_sparse})
    out = dict(base)
    out["blocks"] = sparse_blocks
    return out


def _extract_solution_for_verify(rpc_result: dict[str, Any]) -> dict[str, Any]:
    sol: dict[str, Any] = {"x": tensor_to_array(rpc_result["x"], expected_ndim=1, dtype="float64")}
    if rpc_result.get("dual_Z") is not None:
        sol["dual_Z"] = [
            tensor_to_array(z, expected_ndim=2, dtype="float64")
            for z in rpc_result["dual_Z"]
        ]
    if rpc_result.get("dual_eq") is not None:
        sol["dual_eq"] = tensor_to_array(rpc_result["dual_eq"], expected_ndim=1, dtype="float64")
    if rpc_result.get("dual_ineq") is not None:
        sol["dual_ineq"] = tensor_to_array(rpc_result["dual_ineq"], expected_ndim=1, dtype="float64")
    if rpc_result.get("objective") is not None:
        sol["objective"] = float(rpc_result["objective"])
    sol["solver_status"] = rpc_result.get("solver_status", "optimal")
    return sol


@pytest.mark.parametrize("n", [12, 16])
def test_f9_cycle1_packed_rpc_stabilization_lmi_parity_and_oracle(n: int) -> None:
    """Zero-copy F_k_packed via Worker dispatch_rpc matches dense/sparse (<1e-8), passes 5D verify, and matches Clarabel."""
    alpha = 0.25
    prob_dense, A, B = _build_stabilization_problem(n=n, alpha=alpha)
    prob_sparse = CanonicalSDPProblem.from_dict(_problem_to_sparse_dict(prob_dense))

    # 1. Solve via Worker RPC envelope {request, payload, buffers} with zero-copy memoryview F_k_packed
    envelope, _pinned = _problem_to_worker_packed_envelope(
        prob_dense,
        operation="optimization.solve",
        request_id=f"f9-stab-n{n}",
    )
    resp_packed = dispatch_rpc(envelope)
    assert resp_packed["status"] in ("success", "warning"), resp_packed
    res_packed = resp_packed["result"]
    assert res_packed is not None
    assert res_packed["backend"] == "native_primal_dual"
    assert res_packed["certificate_status"] == "validated_dual"
    assert res_packed["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    # 2. Solve dense F_k and sparse F_k_sparse directly with native_primal_dual
    res_dense = solve(prob_dense, backend="native_primal_dual")
    res_sparse = solve(prob_sparse, backend="native_primal_dual")
    assert res_dense.status in ("success", "warning"), res_dense.error
    assert res_sparse.status in ("success", "warning"), res_sparse.error
    assert res_dense.data["certificate_status"] == "validated_dual"
    assert res_sparse.data["certificate_status"] == "validated_dual"

    x_packed = tensor_to_array(res_packed["x"], expected_ndim=1, dtype="float64")
    x_dense = tensor_to_array(res_dense.data["x"], expected_ndim=1, dtype="float64")
    x_sparse = tensor_to_array(res_sparse.data["x"], expected_ndim=1, dtype="float64")

    # Strict bit-close primal parity (< 1e-8)
    assert float(np.max(np.abs(x_packed - x_dense))) < 1e-8
    assert float(np.max(np.abs(x_packed - x_sparse))) < 1e-8

    obj_packed = float(res_packed["objective"])
    obj_dense = float(res_dense.data["objective"])
    assert abs(obj_packed - obj_dense) < 1e-8

    # 3. Independent 5D verification directly on original dense problem AND via packed RPC verify
    sol_dict = _extract_solution_for_verify(res_packed)
    audited_direct = verify(prob_dense, sol_dict)
    assert audited_direct.status in ("success", "warning"), audited_direct.error
    assert audited_direct.data["certificate_status"] == "validated_dual"
    assert audited_direct.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    verify_envelope, _pinned_v = _problem_to_worker_packed_envelope(
        prob_dense,
        operation="optimization.verify",
        request_id=f"f9-stab-verify-n{n}",
        extra_payload={
            "solution": {
                "x": res_packed["x"],
                "dual_Z": res_packed["dual_Z"],
                "objective": res_packed["objective"],
            },
            "claimed_status": res_packed["solver_status"],
        },
    )
    resp_verify = dispatch_rpc(verify_envelope)
    assert resp_verify["status"] in ("success", "warning"), resp_verify
    assert resp_verify["result"]["certificate_status"] == "validated_dual"
    assert resp_verify["result"]["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    # 4. Closed-loop stabilization verification (independent eigenvalue proof)
    ctrl = recover_controller(prob_dense, {"x": x_packed, "certificate_status": "validated_dual"})
    assert ctrl.data["controller_validity"] == "verified_under_assumptions"
    K = tensor_to_array(ctrl.data["K"], expected_ndim=2, dtype="float64")
    assert float(np.max(np.linalg.eigvals(A + B @ K).real)) < -alpha

    # 5. Independent Clarabel oracle parity when clarabel is installed (zero skips in core_no_sdp)
    if _clarabel_available():
        res_clarabel = solve(prob_dense, backend="clarabel_direct")
        assert res_clarabel.status in ("success", "warning"), res_clarabel.error
        assert res_clarabel.data["certificate_status"] == "validated_dual"
        assert res_clarabel.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
        obj_clarabel = float(res_clarabel.data["objective"])
        assert abs(obj_packed - obj_clarabel) < 1e-5, (
            f"Objective mismatch vs clarabel_direct for n={n}: "
            f"native={obj_packed}, clarabel={obj_clarabel}"
        )


def test_f9_cycle1_packed_rpc_mixed_psd_and_24_lp_blocks_oracle() -> None:
    """Mixed 2x(4x4) PSD + 24 scalar 1x1 LP blocks via F_k_packed Worker RPC matches dense/sparse and Clarabel."""
    prob_dense = _build_mixed_psd_and_24_lp_problem()
    assert sum(1 for b in prob_dense.blocks if b.dim == 1) == 24
    assert sum(1 for b in prob_dense.blocks if b.dim > 1) == 2

    prob_sparse = CanonicalSDPProblem.from_dict(_problem_to_sparse_dict(prob_dense))

    # 1. Zero-copy Worker RPC dispatch with memoryview F_k_packed
    envelope, _pinned = _problem_to_worker_packed_envelope(
        prob_dense,
        operation="optimization.solve",
        request_id="f9-mixed-24lp",
    )
    resp_packed = dispatch_rpc(envelope)
    assert resp_packed["status"] in ("success", "warning"), resp_packed
    res_packed = resp_packed["result"]
    assert res_packed is not None
    assert res_packed["backend"] == "native_primal_dual"
    assert res_packed["certificate_status"] == "validated_dual"
    assert res_packed["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    # 2. Dense and sparse native parity (< 1e-8)
    res_dense = solve(prob_dense, backend="native_primal_dual")
    res_sparse = solve(prob_sparse, backend="native_primal_dual")
    assert res_dense.status in ("success", "warning"), res_dense.error
    assert res_sparse.status in ("success", "warning"), res_sparse.error

    x_packed = tensor_to_array(res_packed["x"], expected_ndim=1, dtype="float64")
    x_dense = tensor_to_array(res_dense.data["x"], expected_ndim=1, dtype="float64")
    x_sparse = tensor_to_array(res_sparse.data["x"], expected_ndim=1, dtype="float64")
    assert float(np.max(np.abs(x_packed - x_dense))) < 1e-8
    assert float(np.max(np.abs(x_packed - x_sparse))) < 1e-8

    obj_packed = float(res_packed["objective"])
    obj_dense = float(res_dense.data["objective"])
    assert abs(obj_packed - obj_dense) < 1e-8

    # 3. Independent 5D verification directly on original dense problem
    sol_dict = _extract_solution_for_verify(res_packed)
    audited = verify(prob_dense, sol_dict)
    assert audited.status in ("success", "warning"), audited.error
    assert audited.data["certificate_status"] == "validated_dual"
    assert audited.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
    assert audited.data["residuals"]["duality_gap_rel"] < 1e-6
    assert audited.data["residuals"]["dual_stationarity_rel"] < 1e-6

    # Verify all 24 scalar 1x1 constraints directly in independent NumPy arithmetic
    for blk in prob_dense.blocks:
        mat = blk.evaluate(x_packed)
        min_eig = float(np.min(np.linalg.eigvalsh(mat)))
        assert min_eig >= -1e-7, f"Block {blk.name} violated: min_eig={min_eig}"

    # 4. Independent Clarabel oracle parity when clarabel is installed (zero skips in core_no_sdp)
    if _clarabel_available():
        res_clarabel = solve(prob_dense, backend="clarabel_direct")
        assert res_clarabel.status in ("success", "warning"), res_clarabel.error
        assert res_clarabel.data["certificate_status"] == "validated_dual"
        assert res_clarabel.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
        obj_clarabel = float(res_clarabel.data["objective"])
        assert abs(obj_packed - obj_clarabel) < 1e-5, (
            f"Mixed 24-LP objective mismatch vs clarabel_direct: "
            f"native={obj_packed}, clarabel={obj_clarabel}"
        )
