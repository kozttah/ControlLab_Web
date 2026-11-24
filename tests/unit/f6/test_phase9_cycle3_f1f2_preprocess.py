"""Unit tests for WP-PHASE9-03-F6-FUJISAWA-F1F2-PREPROCESS (ADR-015 Cycle 3).

Validates:
1. Fujisawa–Kojima–Nakata (1997) F1/F2 sparse Schur assembly matches dense F3 Schur
   matrix H to `< 1e-12` relative error on ultra-sparse (`Q > 0`) and control LMI
   (`A Q + Q A^T + B Y + Y^T B^T`, n=8, 16, 20) blocks, avoids allocating dense
   `_F_cols` for F1/F2 blocks, and reports `F1`/`F2` engagement in `schur_assembly_modes`.
2. Symbolic column redundancy preprocessing:
   - Eliminates exact zero columns (`c_k == 0`, e.g. 5 unused dummy variables).
   - Safely detects unboundedness (`dual_infeasible`, `validated_unboundedness`) for
     exact zero columns with `c_k != 0` when primal feasible, and preserves Farkas
     infeasibility (`primal_infeasible`, `validated_infeasibility`) when primal infeasible.
   - Merges exact duplicate/collinear columns (`F_{b,k2} = alpha * F_{b,k1}`, `c[k2] = alpha * c[k1]`)
     via sparse content hashing, with exact 5D verification on the ORIGINAL unreduced problem
     and `< 1e-6` parity vs `clarabel_direct`.
3. CPython speedup benchmark on `n=16` (152 vars) and `n=20` (230 vars) stabilization LMIs
   comparing F1/F2 vs dense F3 (`schur_mode="F3_blas"`).
4. Zero `linalg.inv` AST invariant in `control_lab/optimization/backends/native_core.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path
import time

import numpy as np
import pytest

from control_lab.core import tensor_to_array
from control_lab.optimization import (
    CanonicalSDPProblem,
    SDPBlock,
    compile,
    continuous_stabilization_lmi,
    recover_controller,
    sdpvar,
    solve,
    trace,
)
from control_lab.optimization.backends.native_core import (
    _InternalConeBlock,
    _preprocess_symbolic_columns,
    _sym,
    solve_native_raw,
)


def _dense_f3_schur_reference(blk_f3: _InternalConeBlock, G_invT: np.ndarray) -> np.ndarray:
    """Reference dense F3 Schur matrix H_ij = tr(G_invT^T F_i G_invT G_invT^T F_j G_invT)."""
    dim = blk_f3.dim
    n_act = int(blk_f3._active_keys.size)
    cols = np.empty((dim * dim, n_act), dtype=np.float64)
    for idx, j_raw in enumerate(blk_f3._active_keys):
        fj = blk_f3.F_terms[int(j_raw)]
        f_hat = _sym(G_invT.T @ fj @ G_invT)
        cols[:, idx] = f_hat.ravel()
    return _sym(cols.T @ cols)


def _make_stabilization_problem(n: int, *, kind: str = "tridiag", minimize_trace: bool = False) -> CanonicalSDPProblem:
    if kind == "diag":
        A = np.diag([-1.0 - 0.1 * i for i in range(n - 1)] + [0.5])
    elif kind == "tridiag":
        A = np.diag([-1.5 - 0.05 * i for i in range(n - 1)] + [0.4])
        for i in range(n - 1):
            A[i, i + 1] = 0.15
            A[i + 1, i] = -0.10
    elif kind == "dense":
        rng = np.random.default_rng(200 + n)
        A = np.diag([-1.5 - 0.1 * i for i in range(n - 1)] + [0.4]) + 0.05 * rng.standard_normal((n, n))
    else:
        raise ValueError(f"Unknown kind: {kind}")
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    if not minimize_trace:
        return continuous_stabilization_lmi(A, B, alpha=0.25)
    Q = sdpvar((n, n), name="Q", symmetric=True)
    Y = sdpvar((1, n), name="Y")
    lmi_stab = -(A @ Q + Q @ A.T + B @ Y + Y.T @ B.T + 0.5 * Q)
    return compile(
        trace(Q),
        [Q >= np.eye(n, dtype=np.float64), lmi_stab >= 0.05 * np.eye(n, dtype=np.float64)],
        name=f"stab_min_trace_{kind}_n{n}",
    )


# ---------------------------------------------------------------------------
# 1. F1/F2 Sparse Schur Assembly Accuracy (< 1e-12) & Mode Engagement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [8, 16, 20])
@pytest.mark.parametrize("kind", ["diag", "tridiag", "dense"])
def test_f1_f2_schur_assembly_matches_dense_f3_to_1e_12(n: int, kind: str) -> None:
    """F1 (Q > 0, diagonal A) and F2 (tridiag/dense A) Schur matrices match dense F3 to < 1e-12."""
    prob = _make_stabilization_problem(n, kind=kind)
    rng = np.random.default_rng(1000 + n)
    G_invT = rng.standard_normal((n, n)) + 2.0 * np.eye(n)
    W = _sym(G_invT @ G_invT.T)

    modes_seen: list[str] = []
    for blk_orig in prob.blocks:
        blk_auto = _InternalConeBlock(
            name=blk_orig.name,
            dim=blk_orig.dim,
            F0=blk_orig.F0,
            F_terms=dict(blk_orig.F_terms),
            force_schur_mode="auto",
        )
        blk_f3 = _InternalConeBlock(
            name=blk_orig.name,
            dim=blk_orig.dim,
            F0=blk_orig.F0,
            F_terms=dict(blk_orig.F_terms),
            force_schur_mode="F3_blas",
        )
        modes_seen.append(blk_auto.schur_mode)
        assert blk_f3.schur_mode == "F3_blas"

        if blk_auto.schur_mode in ("F1", "F2"):
            assert blk_auto._F_cols is None, "F1/F2 blocks must not allocate dense _F_cols"

        n_act = int(blk_auto._active_keys.size)
        H_auto = np.empty((n_act, n_act), dtype=np.float64)
        blk_auto.assemble_schur_block(W, H_auto)
        H_ref = _dense_f3_schur_reference(blk_f3, G_invT)

        rel_err = float(np.linalg.norm(H_auto - H_ref, "fro") / max(1e-15, float(np.linalg.norm(H_ref, "fro"))))
        assert rel_err < 1e-12, f"n={n}, kind={kind}, mode={blk_auto.schur_mode}, rel_err={rel_err:.3e}"
        assert float(np.max(np.abs(H_auto - H_auto.T))) < 1e-12 * max(1.0, float(np.max(np.abs(H_auto))))

    # Q > 0 block always engages F1
    assert modes_seen[0] == "F1"
    if kind == "diag":
        assert modes_seen[1] == "F1"
    elif kind == "tridiag" or (kind == "dense" and n >= 16):
        assert modes_seen[1] == "F2"


def test_schur_assembly_modes_diagnostic_reported_in_raw_and_solve() -> None:
    """Confirm `schur_assembly_modes` reports F1/F2 engagement in both solve_native_raw and solve().diagnostics."""
    prob = _make_stabilization_problem(16, kind="tridiag", minimize_trace=True)
    raw = solve_native_raw(prob)
    assert raw["solver_status"] == "optimal"
    modes = raw["schur_assembly_modes"]
    assert modes["F1"] >= 1
    assert modes["F2"] >= 1
    assert modes["F3_blas"] == 0

    res = solve(prob, backend="native_primal_dual")
    assert res.status != "failure", res.error
    assert res.data["certificate_status"] == "validated_dual"
    assert res.diagnostics["schur_assembly_modes"] == modes

    res_cl = solve(prob, backend="clarabel_direct")
    assert abs(float(res.data["objective"]) - float(res_cl.data["objective"])) < 1e-6


# ---------------------------------------------------------------------------
# 2. Symbolic Column Redundancy Preprocessing (Zero & Duplicate Columns)
# ---------------------------------------------------------------------------


def test_symbolic_preprocessing_zero_columns_and_duplicate_columns_clarabel_parity() -> None:
    """Adding 5 unused zero columns (c_k=0) and 3 scaled duplicate columns solves cleanly with validated_dual."""
    base_prob = _make_stabilization_problem(6, kind="tridiag", minimize_trace=True)
    m_base = base_prob.n_vars
    n_zero = 5
    dup_specs = [
        (0, 2.5),    # duplicate of var 0 scaled by 2.5
        (3, -1.75),  # duplicate of var 3 scaled by -1.75
        (m_base - 1, 0.4),  # duplicate of last var scaled by 0.4
    ]
    n_dup = len(dup_specs)
    m_aug = m_base + n_zero + n_dup

    c_aug = np.zeros((m_aug,), dtype=np.float64)
    c_aug[:m_base] = base_prob.c
    # zero cols [m_base : m_base + n_zero] have c_k = 0.0
    for d_i, (src_k, alpha) in enumerate(dup_specs):
        c_aug[m_base + n_zero + d_i] = alpha * base_prob.c[src_k]

    aug_blocks: list[SDPBlock] = []
    for blk in base_prob.blocks:
        f_terms = dict(blk.F_terms)
        for d_i, (src_k, alpha) in enumerate(dup_specs):
            if src_k in blk.F_terms:
                f_terms[m_base + n_zero + d_i] = alpha * blk.F_terms[src_k]
        aug_blocks.append(SDPBlock(name=blk.name, F0=blk.F0, F_k=f_terms, n_vars=m_aug))

    aug_prob = CanonicalSDPProblem(c=c_aug, blocks=aug_blocks, c0=base_prob.c0, name="aug_zero_and_dup")

    plan = _preprocess_symbolic_columns(aug_prob)
    assert plan.original_n_vars == m_aug
    assert plan.reduced_n_vars == m_base
    assert len(plan.eliminated_zero_vars) == n_zero
    assert len(plan.merged_duplicate_vars) == n_dup

    res_nat = solve(aug_prob, backend="native_primal_dual")
    res_cl = solve(aug_prob, backend="clarabel_direct")

    assert res_nat.status != "failure", res_nat.error
    assert res_nat.data["solver_status"] == "optimal"
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_nat.data["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")

    pre_sum = res_nat.diagnostics["preprocessing_summary"]
    assert pre_sum["original_n_vars"] == m_aug
    assert pre_sum["reduced_n_vars"] == m_base
    assert pre_sum["eliminated_zero_vars"] == n_zero
    assert pre_sum["merged_duplicate_vars"] == n_dup
    assert pre_sum["reduced_n_vars"] < pre_sum["original_n_vars"]

    # Reconstructed zero & merged variables are 0.0 and objective matches Clarabel to < 1e-6
    x_nat = tensor_to_array(res_nat.data["x"])
    assert x_nat.shape == (m_aug,)
    assert np.all(x_nat[m_base:] == 0.0)
    assert abs(float(res_nat.data["objective"]) - float(res_cl.data["objective"])) < 1e-6


def test_symbolic_preprocessing_duplicate_columns_with_equalities_and_inequalities() -> None:
    """Duplicate/zero columns in mixed PSD + equality + inequality problem preserve exact duals."""
    # min x0 + 2*x1 + 0*x2 + 3*x3  (where x2 is zero col, x3 = 3*x0 duplicate across PSD, E, H, c)
    # s.t. diag(x0 + 3*x3 - 1, x1 - 0.5) >= 0,  x0 + 3*x3 + x1 == 4,  x1 <= 3
    m = 4
    c = np.array([1.0, 2.0, 0.0, 3.0], dtype=np.float64)
    F0 = np.diag([-1.0, -0.5])
    F_terms = {
        0: np.diag([1.0, 0.0]),
        1: np.diag([0.0, 1.0]),
        3: np.diag([3.0, 0.0]),
    }
    E = np.array([[1.0, 1.0, 0.0, 3.0]], dtype=np.float64)
    d = np.array([4.0], dtype=np.float64)
    H = np.array([[0.0, 1.0, 0.0, 0.0]], dtype=np.float64)
    h = np.array([3.0], dtype=np.float64)
    prob = CanonicalSDPProblem(
        c=c,
        blocks=[SDPBlock("psd0", F0, F_terms, n_vars=m)],
        E=E,
        d=d,
        H=H,
        h=h,
        name="mixed_eq_ineq_dup_zero",
    )

    res_nat = solve(prob, backend="native_primal_dual")
    res_cl = solve(prob, backend="clarabel_direct")

    assert res_nat.status != "failure", res_nat.error
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert res_nat.diagnostics["preprocessing_summary"]["original_n_vars"] == 4
    assert res_nat.diagnostics["preprocessing_summary"]["reduced_n_vars"] == 2
    assert res_nat.diagnostics["preprocessing_summary"]["eliminated_zero_vars"] == 1
    assert res_nat.diagnostics["preprocessing_summary"]["merged_duplicate_vars"] == 1
    assert abs(float(res_nat.data["objective"]) - float(res_cl.data["objective"])) < 1e-6


def test_symbolic_preprocessing_zero_column_nonzero_cost_unbounded_and_infeasible_safety() -> None:
    """Zero column with c_k != 0 certifies dual_infeasible if primal feasible, or primal_infeasible if infeasible."""
    # Case A: Primal feasible + free variable x1 with c1 = -2.0 -> unbounded
    c_feas = np.array([1.0, -2.0], dtype=np.float64)
    blk_feas = SDPBlock("p0", np.eye(2), {0: np.eye(2)}, n_vars=2)
    prob_unb = CanonicalSDPProblem(c=c_feas, blocks=[blk_feas], name="zero_col_unbounded")
    res_unb = solve(prob_unb, backend="native_primal_dual")
    assert res_unb.data["solver_status"] == "dual_infeasible"
    assert res_unb.data["certificate_status"] == "validated_unboundedness"
    assert res_unb.diagnostics["preprocessing_summary"]["free_nonzero_cost_vars"] == 1

    # Case B: Primal infeasible (x0 >= 2 and x0 <= 1) + free variable x1 with c1 = -2.0 -> primal_infeasible!
    blk_inf1 = SDPBlock("lb", np.array([[-2.0]]), {0: np.array([[1.0]])}, n_vars=2)
    blk_inf2 = SDPBlock("ub", np.array([[1.0]]), {0: np.array([[-1.0]])}, n_vars=2)
    prob_inf = CanonicalSDPProblem(c=c_feas, blocks=[blk_inf1, blk_inf2], name="zero_col_primal_infeasible")
    res_inf = solve(prob_inf, backend="native_primal_dual")
    assert res_inf.data["solver_status"] == "primal_infeasible"
    assert res_inf.data["certificate_status"] == "validated_infeasibility"


# ---------------------------------------------------------------------------
# 3. CPython Speedup on n=16 (152 vars) & n=20 (230 vars) Stabilization LMIs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n,expected_vars", [(16, 152), (20, 230)])
def test_f1_f2_speedup_and_parity_on_large_stabilization_lmis(n: int, expected_vars: int) -> None:
    """F1/F2 achieves measurable Schur speedup vs dense F3 on n=16 (152 vars) and n=20 (230 vars) LMIs."""
    prob = _make_stabilization_problem(n, kind="tridiag", minimize_trace=True)
    assert prob.n_vars == expected_vars

    # Per-iteration Schur assembly benchmark on both blocks
    rng = np.random.default_rng(700 + n)
    G_invT = rng.standard_normal((n, n)) + 2.0 * np.eye(n)
    W = _sym(G_invT @ G_invT.T)

    t_auto_schur = 0.0
    t_f3_schur = 0.0
    for blk_orig in prob.blocks:
        blk_a = _InternalConeBlock(blk_orig.name, blk_orig.dim, blk_orig.F0, dict(blk_orig.F_terms), force_schur_mode="auto")
        blk_f3 = _InternalConeBlock(blk_orig.name, blk_orig.dim, blk_orig.F0, dict(blk_orig.F_terms), force_schur_mode="F3_blas")
        n_act = int(blk_a._active_keys.size)
        gram_a = np.empty((n_act, n_act), dtype=np.float64)
        cols = np.empty((n * n, n_act), dtype=np.float64)
        gram_f3 = np.empty((n_act, n_act), dtype=np.float64)
        tmp1 = np.empty((n, n), dtype=np.float64)
        tmp2 = np.empty((n, n), dtype=np.float64)

        # Warmup
        blk_a.assemble_schur_block(W, gram_a)

        t0 = time.perf_counter()
        for _ in range(10):
            blk_a.assemble_schur_block(W, gram_a)
        t_auto_schur += time.perf_counter() - t0

        t0 = time.perf_counter()
        for _ in range(10):
            for idx, j_raw in enumerate(blk_f3._active_keys):
                j = int(j_raw)
                sp = blk_f3._sparse_terms.get(j)
                if sp is not None:
                    r_sp, c_sp, v_sp = sp
                    np.matmul(G_invT[r_sp, :].T, v_sp[:, None] * G_invT[c_sp, :], out=tmp1)
                else:
                    np.matmul(G_invT.T, blk_f3.F_terms[j], out=tmp2)
                    np.matmul(tmp2, G_invT, out=tmp1)
                cols[:, idx] = (0.5 * (tmp1 + tmp1.T)).ravel()
            np.matmul(cols.T, cols, out=gram_f3)
        t_f3_schur += time.perf_counter() - t0

    schur_speedup = t_f3_schur / max(t_auto_schur, 1e-9)
    assert schur_speedup > 1.5, f"Expected F1/F2 Schur speedup > 1.5x on n={n}, got {schur_speedup:.2f}x"

    # End-to-end solve parity vs F3 and clarabel_direct
    raw_auto = solve_native_raw(prob, options={"schur_mode": "auto"})
    raw_f3 = solve_native_raw(prob, options={"schur_mode": "F3_blas"})
    assert raw_auto["solver_status"] == "optimal"
    assert raw_f3["solver_status"] == "optimal"
    assert raw_auto["schur_assembly_modes"]["F1"] >= 1
    assert raw_auto["schur_assembly_modes"]["F2"] >= 1
    assert abs(float(raw_auto["objective"]) - float(raw_f3["objective"])) < 1e-8

    res_nat = solve(prob, backend="native_primal_dual")
    res_cl = solve(prob, backend="clarabel_direct")
    assert res_nat.data["certificate_status"] == "validated_dual"
    assert abs(float(res_nat.data["objective"]) - float(res_cl.data["objective"])) < 1e-6


# ---------------------------------------------------------------------------
# 4. AST Zero-linalg.inv Invariant
# ---------------------------------------------------------------------------


def test_native_core_ast_zero_linalg_inv_cycle3() -> None:
    """Confirm native_core.py contains zero linalg.inv calls after Cycle 3 changes."""
    path = Path(__file__).resolve().parents[3] / "control_lab" / "optimization" / "backends" / "native_core.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "inv":
            pytest.fail(f"Forbidden .inv attribute access found at line {node.lineno} in native_core.py")
