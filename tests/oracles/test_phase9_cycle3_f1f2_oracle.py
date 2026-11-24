"""Independent F9 oracle audit for Phase 9 Cycle 3 (ADR-015: Fujisawa F1/F2 Sparse Schur + Symbolic Preprocessing).

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
    sdpvar,
    solve,
    trace,
    verify,
)
from control_lab.optimization.backends.native_core import solve_native_raw


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


def _build_stabilization_min_trace_problem(n: int) -> tuple[CanonicalSDPProblem, np.ndarray, np.ndarray]:
    """Build a non-trivial tridiagonal stabilization LMI (min trace(Q)) with 1 unstable mode."""
    A = np.diag([-1.4 - 0.06 * i for i in range(n - 1)] + [0.45]).astype(np.float64)
    for i in range(n - 1):
        A[i, i + 1] = 0.16
        A[i + 1, i] = -0.11
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    Q = sdpvar((n, n), name="Q", symmetric=True)
    Y = sdpvar((1, n), name="Y")
    lmi_stab = -(A @ Q + Q @ A.T + B @ Y + Y.T @ B.T + 0.5 * Q)
    prob = compile(
        trace(Q),
        [Q >= np.eye(n, dtype=np.float64), lmi_stab >= 0.05 * np.eye(n, dtype=np.float64)],
        name=f"f9_cycle3_stab_n{n}",
    )
    return prob, A, B


# ---------------------------------------------------------------------------
# 1. Fujisawa F1/F2 Sparse Schur Assembly Parity (n = 12, 16, 20)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [12, 16, 20])
def test_f9_cycle3_f1f2_sparse_schur_matches_f3_and_clarabel(n: int) -> None:
    """F1/F2 sparse Schur assembly on n=12, 16, 20 stabilization LMIs matches F3_blas and Clarabel (< 1e-6)."""
    prob, A, B = _build_stabilization_min_trace_problem(n)

    # Auto mode (Fujisawa F1/F2 active)
    res_auto = solve(prob, backend="native_primal_dual")
    assert res_auto.status in ("success", "warning"), res_auto.error
    assert res_auto.data["solver_status"] == "optimal"
    assert res_auto.data["certificate_status"] == "validated_dual"
    assert res_auto.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    modes_auto = res_auto.diagnostics["schur_assembly_modes"]
    assert modes_auto["F1"] >= 1, f"Expected F1 active for n={n}, got {modes_auto}"
    assert modes_auto["F2"] >= 1, f"Expected F2 active for n={n}, got {modes_auto}"
    assert modes_auto["F3_blas"] == 0, f"Expected F3_blas=0 in auto mode for n={n}, got {modes_auto}"

    # Independent 5D verification on original problem
    audited_auto = verify(prob, _extract_solution_for_verify(res_auto.data))
    assert audited_auto.status in ("success", "warning"), audited_auto.error
    assert audited_auto.data["certificate_status"] == "validated_dual"
    assert audited_auto.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    # Independent closed-loop stability proof from recovered Q, Y
    x_auto = tensor_to_array(res_auto.data["x"], expected_ndim=1, dtype="float64")
    Q_val = prob.reconstruct_variable("Q", x_auto)
    Y_val = prob.reconstruct_variable("Y", x_auto)
    K_val = np.linalg.solve(Q_val.T, Y_val.T).T
    max_eig = float(np.max(np.linalg.eigvals(A + B @ K_val).real))
    assert max_eig < -0.20, f"Closed-loop unstable or insufficient decay for n={n}: max_eig={max_eig}"

    # Dense F3_blas reference parity (< 1e-6)
    raw_f3 = solve_native_raw(prob, options={"schur_mode": "F3_blas"})
    assert raw_f3["solver_status"] == "optimal"
    assert raw_f3["schur_assembly_modes"]["F3_blas"] >= 2
    assert raw_f3["schur_assembly_modes"]["F1"] == 0
    assert raw_f3["schur_assembly_modes"]["F2"] == 0

    obj_auto = float(res_auto.data["objective"])
    obj_f3 = float(raw_f3["objective"])
    assert abs(obj_auto - obj_f3) < 1e-6, (
        f"n={n}: F1/F2 objective ({obj_auto:.10f}) diverged from F3_blas ({obj_f3:.10f})"
    )

    # Independent Clarabel oracle parity when installed (< 1e-6)
    if _clarabel_available():
        res_cl = solve(prob, backend="clarabel_direct")
        assert res_cl.status in ("success", "warning"), res_cl.error
        assert res_cl.data["certificate_status"] == "validated_dual"
        obj_cl = float(res_cl.data["objective"])
        assert abs(obj_auto - obj_cl) < 1e-6, (
            f"n={n}: F1/F2 objective ({obj_auto:.10f}) diverged from Clarabel ({obj_cl:.10f})"
        )


# ---------------------------------------------------------------------------
# 2. Symbolic Column Redundancy Preprocessing (Zero & Duplicate Columns)
# ---------------------------------------------------------------------------


def test_f9_cycle3_symbolic_preprocessing_unreduced_verify_and_clarabel_parity() -> None:
    """Symbolic preprocessing (eliminated_zero_vars >= 3, merged_duplicate_vars >= 2) validates on ORIGINAL problem."""
    base_prob, _, _ = _build_stabilization_min_trace_problem(6)
    m_base = base_prob.n_vars

    n_zero = 4
    dup_specs = [
        (0, 1.75),
        (2, -2.25),
        (m_base - 1, 0.5),
    ]
    n_dup = len(dup_specs)
    m_aug = m_base + n_zero + n_dup

    c_aug = np.zeros((m_aug,), dtype=np.float64)
    c_aug[:m_base] = base_prob.c
    for d_i, (src_k, alpha) in enumerate(dup_specs):
        c_aug[m_base + n_zero + d_i] = alpha * base_prob.c[src_k]

    aug_blocks: list[SDPBlock] = []
    for blk in base_prob.blocks:
        f_terms = dict(blk.F_terms)
        for d_i, (src_k, alpha) in enumerate(dup_specs):
            if src_k in blk.F_terms:
                f_terms[m_base + n_zero + d_i] = alpha * blk.F_terms[src_k]
        aug_blocks.append(SDPBlock(name=blk.name, F0=blk.F0, F_k=f_terms, n_vars=m_aug))

    aug_prob = CanonicalSDPProblem(
        c=c_aug,
        blocks=aug_blocks,
        c0=base_prob.c0,
        name="f9_cycle3_symbolic_preproc_aug",
    )

    res_base = solve(base_prob, backend="native_primal_dual")
    res_aug = solve(aug_prob, backend="native_primal_dual")

    assert res_base.status in ("success", "warning"), res_base.error
    assert res_aug.status in ("success", "warning"), res_aug.error
    assert res_aug.data["solver_status"] == "optimal"
    assert res_aug.data["certificate_status"] == "validated_dual"
    assert res_aug.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    pre = res_aug.diagnostics["preprocessing_summary"]
    assert pre["original_n_vars"] == m_aug
    assert pre["reduced_n_vars"] == m_base
    assert pre["eliminated_zero_vars"] >= 3
    assert pre["eliminated_zero_vars"] == n_zero
    assert pre["merged_duplicate_vars"] >= 2
    assert pre["merged_duplicate_vars"] == n_dup

    # Independent 5D verification directly on the ORIGINAL unreduced augmented problem
    audited_aug = verify(aug_prob, _extract_solution_for_verify(res_aug.data))
    assert audited_aug.status in ("success", "warning"), audited_aug.error
    assert audited_aug.data["certificate_status"] == "validated_dual"
    assert audited_aug.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    x_aug = tensor_to_array(res_aug.data["x"], expected_ndim=1, dtype="float64")
    assert x_aug.shape == (m_aug,)
    assert np.all(x_aug[m_base:] == 0.0)

    obj_base = float(res_base.data["objective"])
    obj_aug = float(res_aug.data["objective"])
    assert abs(obj_aug - obj_base) < 1e-6, (
        f"Preprocessed objective ({obj_aug:.10f}) diverged from unaugmented baseline ({obj_base:.10f})"
    )

    # Independent Clarabel parity on the ORIGINAL unreduced problem when installed
    if _clarabel_available():
        res_cl = solve(aug_prob, backend="clarabel_direct")
        assert res_cl.status in ("success", "warning"), res_cl.error
        assert res_cl.data["certificate_status"] == "validated_dual"
        obj_cl = float(res_cl.data["objective"])
        assert abs(obj_aug - obj_cl) < 1e-6, (
            f"Preprocessed objective ({obj_aug:.10f}) diverged from Clarabel ({obj_cl:.10f})"
        )
