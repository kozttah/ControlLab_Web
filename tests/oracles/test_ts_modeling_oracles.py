"""Independent F9 analytical and structural oracles for Phase 10 (CL-TS-MOD-DIR-001 v1.3.0).

Covers all 8 normative tests T-TSMOD-01 through T-TSMOD-08 without circularity:
- T-TSMOD-01: AST security (R-21), sinc_rad C^inf Taylor continuity, zero linalg.inv/eval/exec AST gate
- T-TSMOD-02: Hybrid 3-stage global extrema on multimodal analytical functions with interior optima
- T-TSMOD-03: Exact 16-rule Sector Nonlinearity on 4-state inverted pendulum vs independent analytical S(x3, x4)
- T-TSMOD-04: TPMT v1.3.0 tensor invariants, De Lathauwer bound, HOOI monotonicity, modal centering & bitwise constants
- T-TSMOD-05 & T-TSMOD-06: Convex hulls (SN-NN, RNO-INO, CNO, MGK) & CNO vs SN-NN simplicial volume tightness
- T-TSMOD-07: Full Workspace -> TSStateSpace schema -> PDC LMI (5D spectral check) -> PathSim -> .ctrlab round-trip
- T-TSMOD-08: FEMT v1.2.0 varying-subspace bitwise constants, centered Eckart-Young, rule reduction & P1 O(h^2)
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import jsonschema
import numpy as np
import pytest
from referencing import Registry, Resource
from scipy.stats import qmc

from control_lab.core.controllers import PDCController
from control_lab.core.models import TSStateSpace
from control_lab.diagnostics import ValidationError
from control_lab.fuzzy import (
    cno_matrix,
    derive_ts_femt,
    derive_ts_sector,
    derive_ts_tpmt,
    evaluate_ts_premise_weights,
    femt_svd_decompose,
    find_global_extrema,
    fold_mode,
    hooi_sampled_func,
    hosvd_sampled_func,
    mgk_matrix,
    parse_expression,
    reconstruct_tensor,
    rno_ino_matrix,
    sinc_rad,
    sn_nn_matrix,
    unfold_mode,
)
from control_lab.io import export_ctrlab_bytes, generate_pathsim_script, load_ctrlab_objects
from control_lab.optimization import recover_controller, solve_and_verify, ts_pdc_stabilization_lmi

ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DIR = ROOT / "contracts/schemas"
TS_SCHEMA = json.loads((_SCHEMA_DIR / "ts_state_space.schema.json").read_text(encoding="utf-8"))
_SCHEMA_REGISTRY = Registry().with_resources(
    [
        (
            schema["$id"],
            Resource.from_contents(schema),
        )
        for p in sorted(_SCHEMA_DIR.glob("*.json"))
        for schema in [json.loads(p.read_text(encoding="utf-8"))]
        if "$id" in schema
    ]
)
TS_VALIDATOR = jsonschema.Draft202012Validator(TS_SCHEMA, registry=_SCHEMA_REGISTRY)


# ---------------------------------------------------------------------------
# Independent analytical helpers (never derived from code under test)
# ---------------------------------------------------------------------------


def _pendulum_4state_direct_spec() -> dict[str, object]:
    """4-state inverted pendulum qLPV specification (M=30, M_var=6, M_const=24)."""
    z1 = "(1 / (1.0 + 0.2 * sin(x3)^2))"
    z2 = "cos(x3)"
    z3 = "sinc_rad(x3)"
    z4 = "(x4 * sin(x3))"
    return {
        "state_bounds": {
            "x1": [-2.0, 2.0],
            "x2": [-3.0, 3.0],
            "x3": [-0.6, 0.6],
            "x4": [-2.0, 2.0],
        },
        "A_expr": [
            ["0", "1", "0", "0"],
            ["0", "0", f"-1.962 * {z1} * {z2} * {z3}", f"0.1 * {z1} * {z4}"],
            ["0", "0", "0", "1"],
            ["0", "0", f"23.544 * {z1} * {z3}", f"-0.2 * {z1} * {z2} * {z4}"],
        ],
        "B_expr": [["0"], [z1], ["0"], [f"-2.0 * {z1} * {z2}"]],
        "C_expr": [["1", "0", "0", "0"], ["0", "0", "1", "0"]],
        "D_expr": [["0"], ["0"]],
    }


def _pendulum_4state_sector_spec() -> dict[str, object]:
    """Affine-in-z sector specification of the same 4-state inverted pendulum (16 rules)."""
    return {
        "premises": [
            {"name": "z1", "expression": "1 / (1.0 + 0.2 * sin(x3)^2)", "measured": True},
            {"name": "z2", "expression": "cos(x3)", "measured": True},
            {"name": "z3", "expression": "sinc_rad(x3)", "measured": True},
            {"name": "z4", "expression": "x4 * sin(x3)", "measured": True},
        ],
        "state_bounds": {
            "x1": [-2.0, 2.0],
            "x2": [-3.0, 3.0],
            "x3": [-0.6, 0.6],
            "x4": [-2.0, 2.0],
        },
        "A_expr": [
            ["0", "1", "0", "0"],
            ["0", "0", "-1.962 * z1 * z2 * z3", "0.1 * z1 * z4"],
            ["0", "0", "0", "1"],
            ["0", "0", "23.544 * z1 * z3", "-0.2 * z1 * z2 * z4"],
        ],
        "B_expr": [["0"], ["z1"], ["0"], ["-2.0 * z1 * z2"]],
        "C_expr": [["1", "0", "0", "0"], ["0", "0", "1", "0"]],
        "D_expr": [["0"], ["0"]],
    }


def _exact_pendulum_S_analytical(x3: float, x4: float) -> np.ndarray:
    """Independent analytical evaluator of S(x3, x4) = [[A, B], [C, D]] using Python math."""
    s3 = math.sin(x3)
    c3 = math.cos(x3)
    sinc3 = 1.0 - (x3 * x3) / 6.0 + (x3 ** 4) / 120.0 if abs(x3) < 1e-4 else s3 / x3
    z1 = 1.0 / (1.0 + 0.2 * s3 * s3)
    z4 = x4 * s3
    A = np.array(
        [
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, -1.962 * z1 * c3 * sinc3, 0.1 * z1 * z4],
            [0.0, 0.0, 0.0, 1.0],
            [0.0, 0.0, 23.544 * z1 * sinc3, -0.2 * z1 * c3 * z4],
        ],
        dtype=np.float64,
    )
    B = np.array([[0.0], [z1], [0.0], [-2.0 * z1 * c3]], dtype=np.float64)
    C = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]], dtype=np.float64)
    D = np.zeros((2, 1), dtype=np.float64)
    return np.block([[A, B], [C, D]])


def _as_ts_model(res) -> TSStateSpace:
    raw = res.data["ts_state_space"]
    return raw if isinstance(raw, TSStateSpace) else TSStateSpace.from_dict(raw)


def _vertex_to_S(vertex: dict[str, object]) -> np.ndarray:
    return np.block(
        [
            [np.asarray(vertex["A"], dtype=np.float64), np.asarray(vertex["B"], dtype=np.float64)],
            [np.asarray(vertex["C"], dtype=np.float64), np.asarray(vertex["D"], dtype=np.float64)],
        ]
    )


def _assert_pendulum_24_constants_bitwise(ts_model: TSStateSpace, *, label: str) -> None:
    """Verifies max_r |(S_r)_{ij} - S_{ij}| == 0.0 for all 24 constant entries of pendulum_16."""
    S0 = _exact_pendulum_S_analytical(0.0, 0.0)
    varying_positions = {(1, 2), (1, 3), (3, 2), (3, 3), (1, 4), (3, 4)}
    const_positions = [
        (i, j) for i in range(6) for j in range(5) if (i, j) not in varying_positions
    ]
    assert len(const_positions) == 24
    for r, v in enumerate(ts_model.vertices):
        Sr = _vertex_to_S(v)
        for i, j in const_positions:
            assert Sr[i, j] == S0[i, j], (
                f"[{label}] rule {r} constant entry ({i},{j}) drifted: {Sr[i, j]} != {S0[i, j]}"
            )


# ---------------------------------------------------------------------------
# T-TSMOD-01: AST security (R-21), sinc_rad C^inf continuity, zero linalg.inv
# ---------------------------------------------------------------------------


def test_t_tsmod_01_ast_security_sinc_rad_and_no_inv_gate() -> None:
    """T-TSMOD-01: Malicious AST rejection, sinc_rad Taylor precision < 1e-15, and static AST gate."""
    malicious_payloads = [
        "__import__('os').system('id')",
        "().__class__.__base__.__subclasses__()",
        "eval('1 + 1')",
        "exec('x = 1')",
        "open('/etc/passwd')",
        "x1.__class__",
        "(lambda x: x)(1)",
        "[x1 for x1 in [1, 2]]",
    ]
    for expr in malicious_payloads:
        with pytest.raises((ValidationError, ValueError, SyntaxError)):
            parse_expression(expr)

    # Independent Taylor series oracle for sinc_rad(u) = 1 - u^2/6 + u^4/120
    assert float(sinc_rad(0.0)) == 1.0
    for u in (1e-8, -1e-8, 1e-6, -1e-6, 1e-5, -1e-5):
        taylor_exact = 1.0 - (u * u) / 6.0 + (u ** 4) / 120.0
        assert abs(float(sinc_rad(u)) - taylor_exact) < 1e-15
    for u in (1e-4, -1e-4, 0.25, -0.6, math.pi / 2.0, -2.5):
        exact = math.sin(u) / u
        assert abs(float(sinc_rad(u)) - exact) < 1e-15

    # Static AST gate across all 4 TS modeling core modules: 0 eval/exec/linalg.inv
    target_files = [
        ROOT / "control_lab/fuzzy/symbolic_qlpv.py",
        ROOT / "control_lab/fuzzy/sector_nonlinearity.py",
        ROOT / "control_lab/fuzzy/tpmt.py",
        ROOT / "control_lab/fuzzy/femt.py",
    ]
    forbidden_builtins = {"eval", "exec", "compile", "__import__"}
    for path in target_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in forbidden_builtins, (
                        f"Forbidden call {node.func.id} in {path.name}:{node.lineno}"
                    )
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr != "inv", (
                        f"Forbidden matrix inverse .inv() in {path.name}:{node.lineno}"
                    )


# ---------------------------------------------------------------------------
# T-TSMOD-02: Hybrid global extrema with interior multimodal optima
# ---------------------------------------------------------------------------


def test_t_tsmod_02_hybrid_global_extrema_multimodal_interior() -> None:
    """T-TSMOD-02: Recover analytical interior global extrema to <= 1e-12."""
    # 1D interior extrema: x^3 - 3x on [-1.5, 1.5] has exact min=-2 at x=1, max=2 at x=-1
    res_1d = find_global_extrema("x1^3 - 3 * x1", {"x1": [-1.5, 1.5]})
    assert abs(res_1d["min"] - (-2.0)) <= 1e-12
    assert abs(res_1d["max"] - 2.0) <= 1e-12

    # 2D multimodal with exact closed-form interior global maximum = 1.0 at (pi/6, 0)
    res_2d_max = find_global_extrema(
        "sin(3 * x1) * cos(2 * x2) - 0.1 * (x1 - pi / 6)^2 - 0.1 * x2^2",
        {"x1": [-1.5, 1.5], "x2": [-1.5, 1.5]},
    )
    assert abs(res_2d_max["max"] - 1.0) <= 1e-12

    # 2D multimodal with exact closed-form interior global minimum = -1.0 at (-pi/6, 0)
    res_2d_min = find_global_extrema(
        "sin(3 * x1) * cos(2 * x2) + 0.1 * (x1 + pi / 6)^2 + 0.1 * x2^2",
        {"x1": [-1.5, 1.5], "x2": [-1.5, 1.5]},
    )
    assert abs(res_2d_min["min"] - (-1.0)) <= 1e-12

    # Multimodal g(x1, x2) = sin(3*x1)*cos(2*x2) + 0.1*x1^2 on [-1.2, 1.2]^2
    # Independent analytical Newton solution of d/dx1 [sin(3*x1) + 0.1*x1^2] = 0 (at x2 = 0)
    # and d/dx1 [-sin(3*x1) + 0.1*x1^2] = 0 (at x2 = +-pi/2, which lies outside [-1.2, 1.2],
    # so cos(2*x2) attains its minimum cos(2.4) at x2 = +-1.2 and maximum 1.0 at x2 = 0).
    def _newton_root(f, df, x0: float) -> float:
        x = x0
        for _ in range(30):
            x -= f(x) / df(x)
        return x

    # Global max candidate: x2 = 0 (cos(2*x2)=1), interior peak near x1 = pi/6
    x1_max_1 = _newton_root(
        lambda x: 3.0 * math.cos(3.0 * x) + 0.2 * x,
        lambda x: -9.0 * math.sin(3.0 * x) + 0.2,
        math.pi / 6.0,
    )
    # Also check x2 = +-1.2 (cos(2.4) < 0) near x1 = -pi/6 or boundaries
    c2_edge = math.cos(2.4)
    x1_max_2 = _newton_root(
        lambda x: 3.0 * c2_edge * math.cos(3.0 * x) + 0.2 * x,
        lambda x: -9.0 * c2_edge * math.sin(3.0 * x) + 0.2,
        -math.pi / 6.0,
    )
    x1_min_1 = _newton_root(
        lambda x: 3.0 * math.cos(3.0 * x) + 0.2 * x,
        lambda x: -9.0 * math.sin(3.0 * x) + 0.2,
        -math.pi / 6.0,
    )
    g = lambda a, b: math.sin(3.0 * a) * math.cos(2.0 * b) + 0.1 * a * a
    exact_max = max(g(x1_max_1, 0.0), g(x1_max_2, 1.2), g(1.2, 0.0), g(-1.2, 0.0), g(1.2, 1.2), g(-1.2, 1.2))
    exact_min = min(g(x1_min_1, 0.0), g(1.2, 0.0), g(-1.2, 0.0), g(1.2, 1.2), g(-1.2, 1.2))

    res_multimodal = find_global_extrema(
        "sin(3 * x1) * cos(2 * x2) + 0.1 * x1^2",
        {"x1": [-1.2, 1.2], "x2": [-1.2, 1.2]},
    )
    assert abs(res_multimodal["max"] - exact_max) <= 1e-12
    assert abs(res_multimodal["min"] - exact_min) <= 1e-12


# ---------------------------------------------------------------------------
# T-TSMOD-03: Exact 16-rule Sector Nonlinearity on 4-state inverted pendulum
# ---------------------------------------------------------------------------


def test_t_tsmod_03_sector_pendulum_16_rules_exact_oracle() -> None:
    """T-TSMOD-03: 4-state / 16-rule inverted pendulum vs independent analytical S(x3, x4) on 512+ points."""
    spec = _pendulum_4state_sector_spec()
    res = derive_ts_sector(
        premises=spec["premises"],
        state_bounds=spec["state_bounds"],
        A_expr=spec["A_expr"],
        B_expr=spec["B_expr"],
        C_expr=spec["C_expr"],
        D_expr=spec["D_expr"],
        n_val_points=256,
    )
    assert res.status == "success", res.error
    ts_model: TSStateSpace = _as_ts_model(res)
    assert len(ts_model.vertices) == 16
    S_vertices = [_vertex_to_S(v) for v in ts_model.vertices]

    # 512 Sobol interior points + origin + box corners
    sampler = qmc.Sobol(d=2, scramble=False)
    unit_pts = sampler.random_base2(m=9)  # 512 points
    test_pts = [
        (float(-0.6 + 1.2 * u0), float(-2.0 + 4.0 * u1)) for u0, u1 in unit_pts
    ] + [(0.0, 0.0), (-0.6, -2.0), (-0.6, 2.0), (0.6, -2.0), (0.6, 2.0)]

    max_err = 0.0
    min_h = float("inf")
    max_sum_err = 0.0
    for x3, x4 in test_pts:
        w_res = evaluate_ts_premise_weights(ts_model, {"x1": 0.0, "x2": 0.0, "x3": x3, "x4": x4})
        assert w_res.status == "success", w_res.error
        h = np.asarray(w_res.data["weights"], dtype=np.float64)
        min_h = min(min_h, float(np.min(h)))
        max_sum_err = max(max_sum_err, abs(float(np.sum(h)) - 1.0))
        S_ts = sum(float(h[r]) * S_vertices[r] for r in range(16))
        S_exact = _exact_pendulum_S_analytical(x3, x4)
        max_err = max(max_err, float(np.linalg.norm(S_ts - S_exact, ord="fro")))

    assert min_h >= -1e-15
    assert max_sum_err <= 1e-14
    assert max_err <= 1e-13


# ---------------------------------------------------------------------------
# T-TSMOD-04: TPMT v1.3.0 tensor invariants, modal centering & bitwise constants
# ---------------------------------------------------------------------------


def test_t_tsmod_04_tpmt_tensor_invariants_modal_centering_and_pendulum_constants() -> None:
    """T-TSMOD-04: fold/unfold, HOSVD De Lathauwer bound, HOOI monotonicity, and TPMT v1.3.0 invariants."""
    rng = np.random.default_rng(20261126)
    tensor = rng.standard_normal((7, 6, 5, 2, 2))

    # 1. Exact fold(unfold(A, d), d) == A
    for d in range(tensor.ndim):
        unfolded = unfold_mode(tensor, d)
        refolded = fold_mode(unfolded, d, tensor.shape)
        assert np.array_equal(refolded, tensor)

    # 2. HOSVD orthonormality and De Lathauwer truncation bound (standard and centered)
    ranks = [3, 3, 2]
    for center_modes in (False, True):
        hosvd = hosvd_sampled_func(tensor, ranks=ranks, ord_func=2, center_modes=center_modes)
        for d, U_d in enumerate(hosvd.U_list):
            orth_err = float(np.linalg.norm(U_d.T @ U_d - np.eye(U_d.shape[1]), ord="fro"))
            assert orth_err <= 1e-13
            if center_modes:
                ones = np.ones((U_d.shape[0], 1), dtype=np.float64)
                ones /= np.linalg.norm(ones)
                proj_err = float(np.linalg.norm(ones - U_d @ (U_d.T @ ones)))
                assert proj_err <= 1e-12

        recon = reconstruct_tensor(hosvd.core, hosvd.U_list)
        frob_err_sq = float(np.linalg.norm(tensor - recon) ** 2)
        if not center_modes:
            tail_sq = sum(
                float(np.sum(sv[r:] ** 2))
                for sv, r in zip(hosvd.singular_values, ranks, strict=True)
            )
            assert frob_err_sq <= tail_sq + 1e-12
            assert abs(hosvd.truncation_bound - math.sqrt(tail_sq)) <= 1e-12

        # 3. HOOI monotonic convergence
        hooi = hooi_sampled_func(tensor, ranks=ranks, ord_func=2, max_iter=30, center_modes=center_modes)
        assert len(hooi.error_history) >= 1
        for prev, curr in zip(hooi.error_history[:-1], hooi.error_history[1:], strict=True):
            assert curr <= prev + 1e-12
        for U_d in hooi.U_list:
            assert float(np.linalg.norm(U_d.T @ U_d - np.eye(U_d.shape[1]), ord="fro")) <= 1e-13

    # 4. TPMT v1.3.0 on 4-state inverted pendulum (15x15, CNO, auto and ranks=[2, 2])
    pspec = _pendulum_4state_direct_spec()
    res_auto = derive_ts_tpmt(
        state_bounds=pspec["state_bounds"],
        A_expr=pspec["A_expr"],
        B_expr=pspec["B_expr"],
        C_expr=pspec["C_expr"],
        D_expr=pspec["D_expr"],
        grid_points=15,
        hull_type="CNO",
        n_val_points=128,
    )
    assert res_auto.status in ("success", "warning"), res_auto.error
    _assert_pendulum_24_constants_bitwise(_as_ts_model(res_auto), label="TPMT-auto")
    assert [ax["rank_augmented"] for ax in res_auto.data["hull_diagnostics"]] == [False, False]

    res_r22 = derive_ts_tpmt(
        state_bounds=pspec["state_bounds"],
        A_expr=pspec["A_expr"],
        B_expr=pspec["B_expr"],
        C_expr=pspec["C_expr"],
        D_expr=pspec["D_expr"],
        grid_points=15,
        ranks=[2, 2],
        hull_type="CNO",
        n_val_points=128,
    )
    assert res_r22.status in ("success", "warning"), res_r22.error
    ts_r22: TSStateSpace = _as_ts_model(res_r22)
    assert len(ts_r22.vertices) == 4
    _assert_pendulum_24_constants_bitwise(ts_r22, label="TPMT-ranks22")
    assert [ax["rank_augmented"] for ax in res_r22.data["hull_diagnostics"]] == [False, False]


# ---------------------------------------------------------------------------
# T-TSMOD-05 & T-TSMOD-06: Convex hulls (SN-NN, RNO-INO, CNO, MGK) & tightness
# ---------------------------------------------------------------------------


def test_t_tsmod_05_06_convex_hulls_and_cno_geometric_tightness() -> None:
    """T-TSMOD-05 & T-TSMOD-06: SN/NN invariants, exact nodal reconstruction, and CNO volume tightness."""
    p = np.linspace(-1.0, 1.0, 61, dtype=np.float64)
    # Analytical 3-column basis spanning 1, p, sin(2p)
    raw = np.column_stack([np.ones_like(p), p, np.sin(2.0 * p)])
    U, _ = np.linalg.qr(raw)
    core = np.array([[1.5, -0.4, 0.8], [0.2, 1.1, -0.7], [-0.5, 0.3, 1.2]], dtype=np.float64)
    original_nodal = U @ core  # shape (61, 3)

    W_sn, _T_sn, info_sn = sn_nn_matrix(U, core=core, mode=0)
    core_sn = np.asarray(info_sn["core"], dtype=np.float64)
    assert info_sn["rank_augmented"] is False
    assert float(np.max(np.abs(np.sum(W_sn, axis=1) - 1.0))) <= 1e-11
    assert float(np.min(W_sn)) >= -1e-11
    assert float(np.linalg.norm(W_sn @ core_sn - original_nodal, ord="fro")) <= 1e-11

    W_rno, _T_rno, info_rno = rno_ino_matrix(W_sn, core=core_sn, mode=0)
    core_rno = np.asarray(info_rno["core"], dtype=np.float64)
    assert float(np.max(np.abs(np.sum(W_rno, axis=1) - 1.0))) <= 1e-11
    assert float(np.min(W_rno)) >= -1e-11
    assert float(np.linalg.norm(W_rno @ core_rno - original_nodal, ord="fro")) <= 1e-11

    W_cno, T_cno, info_cno = cno_matrix(W_sn, core=core_sn, mode=0)
    core_cno = np.asarray(info_cno["core"], dtype=np.float64)
    assert float(np.max(np.abs(np.sum(W_cno, axis=1) - 1.0))) <= 1e-11
    assert float(np.min(W_cno)) >= -1e-11
    assert float(np.linalg.norm(W_cno @ core_cno - original_nodal, ord="fro")) <= 1e-11

    # MGK: exact nodal reconstruction + honest NN reporting
    W_mgk, _T_mgk, info_mgk = mgk_matrix(W_sn, core=core_sn, mode=0)
    core_mgk = np.asarray(info_mgk["core"], dtype=np.float64)
    assert float(np.max(np.abs(np.sum(W_mgk, axis=1) - 1.0))) <= 1e-10
    assert float(np.linalg.norm(W_mgk @ core_mgk - original_nodal, ord="fro")) <= 1e-10
    assert info_mgk["nn_violated"] == (float(np.min(W_mgk)) < -1e-9)

    # T-TSMOD-06: Simplicial volume under CNO <= volume under SN-NN
    # Since W_cno = W_sn @ T_cno, relative volume is |det(T_cno)|^{-1} <= |det(I)|^{-1} = 1
    det_cno = abs(float(np.linalg.det(np.asarray(T_cno, dtype=np.float64))))
    assert det_cno > 0.0
    vol_cno_rel = 1.0 / det_cno
    vol_sn_rel = 1.0
    assert vol_cno_rel <= vol_sn_rel + 1e-9
    # And CNO actually tightens this curved trajectory strictly compared to SN-NN
    assert vol_cno_rel < 0.99


# ---------------------------------------------------------------------------
# T-TSMOD-07: Full cycle Workspace -> LMI PDC -> PathSim -> .ctrlab
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("via", ["sector", "tpmt", "femt"])
def test_t_tsmod_07_full_cycle_schema_pdc_lmi_pathsim_and_ctrlab(via: str) -> None:
    """T-TSMOD-07: All 3 pathways validate schema, solve PDC LMI (5D check), export PathSim & round-trip .ctrlab."""
    state_bounds = {"x1": [-0.8, 0.8], "x2": [-1.0, 1.0]}
    if via == "sector":
        res = derive_ts_sector(
            premises=[
                {"name": "z1", "expression": "sin(x1)", "measured": True},
                {"name": "z2", "expression": "cos(x1)", "measured": True},
            ],
            state_bounds=state_bounds,
            A_expr=[["0", "1"], ["1.0 + 0.4 * z1", "-0.5 - 0.2 * z2"]],
            B_expr=[["0"], ["1.0 + 0.2 * z2"]],
            C_expr=[["1", "0"]],
            D_expr=[["0"]],
            n_val_points=64,
        )
    elif via == "tpmt":
        res = derive_ts_tpmt(
            state_bounds=state_bounds,
            A_expr=[["0", "1"], ["1.0 + 0.4 * sin(x1)", "-0.5 - 0.2 * cos(x1)"]],
            B_expr=[["0"], ["1.0 + 0.2 * cos(x1)"]],
            C_expr=[["1", "0"]],
            D_expr=[["0"]],
            grid_points=15,
            hull_type="CNO",
            n_val_points=64,
        )
    else:
        res = derive_ts_femt(
            state_bounds=state_bounds,
            A_expr=[["0", "1"], ["1.0 + 0.4 * sin(x1)", "-0.5 - 0.2 * cos(x1)"]],
            B_expr=[["0"], ["1.0 + 0.2 * cos(x1)"]],
            C_expr=[["1", "0"]],
            D_expr=[["0"]],
            grid_points=15,
            hull_type="CNO",
            mesh_kind="kuhn_delaunay",
            n_val_points=64,
        )

    assert res.status in ("success", "warning"), res.error
    ts_model: TSStateSpace = _as_ts_model(res)

    # 1. Validate canonical JSON Schema (offline local $ref registry)
    ts_dict = ts_model.to_dict()
    TS_VALIDATOR.validate(ts_dict)

    # 2. Premise weight evaluation via ts_bridge
    w_res = evaluate_ts_premise_weights(ts_model, {"x1": 0.35, "x2": -0.2})
    assert w_res.status == "success", w_res.error
    h = np.asarray(w_res.data["weights"], dtype=np.float64)
    assert len(h) == len(ts_model.vertices)
    assert float(np.min(h)) >= -1e-12
    assert abs(float(np.sum(h)) - 1.0) <= 1e-12

    # 3. PDC LMI synthesis + independent 5D spectral check
    alpha = 0.2
    prob = ts_pdc_stabilization_lmi(ts_model, alpha=alpha, feedback_sign="negative")
    sol = solve_and_verify(prob, backend="native_primal_dual")
    assert sol.status in ("success", "warning"), sol.error
    assert sol.data["certificate_status"] == "validated_dual"
    rec = recover_controller(prob, sol, plant=ts_model)
    assert rec.status in ("success", "warning"), rec.error
    raw_pdc = rec.data["controller"]
    pdc = raw_pdc if isinstance(raw_pdc, PDCController) else PDCController.from_dict(raw_pdc)
    assert len(pdc.K_i) == len(ts_model.vertices)

    # Independent closed-loop spectral check at every vertex (u = -K_r x)
    sign = -1.0 if pdc.feedback_sign == "negative" else 1.0
    for r, (v, K_r) in enumerate(zip(ts_model.vertices, pdc.K_i, strict=True)):
        A_r = np.asarray(v["A"], dtype=np.float64)
        B_r = np.asarray(v["B"], dtype=np.float64)
        A_cl = A_r + sign * (B_r @ np.asarray(K_r, dtype=np.float64))
        max_real = float(np.max(np.linalg.eigvals(A_cl).real))
        assert max_real < -alpha + 1e-4, f"[{via}] vertex {r} closed-loop unstable: max_real={max_real}"

    # 4. PathSim script export with real default_h_fn(x) (no uniform 1/N stub)
    ps_res = generate_pathsim_script(ts_model, pdc)
    assert ps_res.status in ("success", "warning"), ps_res.error
    script_text = ps_res.data["script"]
    code_obj = compile(script_text, f"<pathsim_{via}>", "exec")
    assert "def default_h_fn(" in script_text
    assert "1.0 / N_VERTICES" not in script_text
    ns: dict[str, object] = {}
    exec(code_obj, ns)
    h_script = np.asarray(ns["default_h_fn"](np.array([0.35, -0.2], dtype=np.float64)), dtype=np.float64)
    assert float(np.max(np.abs(h_script - h))) <= 1e-12

    # 5. .ctrlab round-trip preservation
    blob = export_ctrlab_bytes(
        project_id=f"oracle-tsmod-{via}",
        project_revision=1,
        models=[ts_model],
        controllers=[pdc],
    )
    loaded = load_ctrlab_objects(blob)
    rehydrated_ts = next(obj for obj in loaded["models"] if isinstance(obj, TSStateSpace))
    assert rehydrated_ts.id == ts_model.id
    assert len(rehydrated_ts.vertices) == len(ts_model.vertices)
    assert rehydrated_ts.membership_spec["representation_kind"] == ts_model.membership_spec["representation_kind"]
    assert "ts_derivation" in rehydrated_ts.provenance


# ---------------------------------------------------------------------------
# T-TSMOD-08: FEMT v1.2.0 varying subspace, centered SVD, Eckart-Young, P1 O(h^2)
# ---------------------------------------------------------------------------


def test_t_tsmod_08_femt_v120_constants_eckart_young_rule_reduction_and_p1_convergence() -> None:
    """T-TSMOD-08: FEMT v1.2.0 bitwise constants, Eckart-Young exactness, N_r^FEMT < N_r^TPMT, and P1 O(h^2)."""
    # (a) 4-state inverted pendulum (15x15, CNO): bitwise 24 constants, rank_augmented=False, fallback_used=False
    pspec = _pendulum_4state_direct_spec()
    res_pend = derive_ts_femt(
        state_bounds=pspec["state_bounds"],
        A_expr=pspec["A_expr"],
        B_expr=pspec["B_expr"],
        C_expr=pspec["C_expr"],
        D_expr=pspec["D_expr"],
        grid_points=15,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=128,
    )
    assert res_pend.status in ("success", "warning"), res_pend.error
    ts_pend: TSStateSpace = _as_ts_model(res_pend)
    _assert_pendulum_24_constants_bitwise(ts_pend, label="FEMT-pendulum")
    hull_diag = res_pend.data["hull_diagnostics"]
    assert hull_diag["rank_augmented"] is False
    assert hull_diag["fallback_used"] is False
    # Physical well-conditioned vertices (no null-vertex explosion)
    max_vertex_norm = max(float(np.linalg.norm(_vertex_to_S(v), ord="fro")) for v in ts_pend.vertices)
    assert max_vertex_norm < 500.0, f"Ill-conditioned FEMT vertex norm: {max_vertex_norm}"

    # (b) Centered Eckart-Young exact nodal error on synthetic varying+constant S_nodes
    rng = np.random.default_rng(777)
    N_g = 40
    S_nodes = np.zeros((N_g, 2, 2), dtype=np.float64)
    S_nodes[:, 0, 0] = 3.5  # constant entry
    S_nodes[:, 1, 1] = -1.25  # constant entry
    t = np.linspace(-1.0, 1.0, N_g)
    S_nodes[:, 0, 1] = np.sin(2.0 * t) + 0.3 * rng.standard_normal(N_g)
    S_nodes[:, 1, 0] = np.cos(3.0 * t) + 0.2 * rng.standard_normal(N_g)

    # Independent centered SVD oracle on varying entries only
    X_var = np.column_stack([S_nodes[:, 0, 1], S_nodes[:, 1, 0]])  # (N_g, 2)
    Delta_X = X_var - np.mean(X_var, axis=0, keepdims=True)
    _, sv_oracle, _ = np.linalg.svd(Delta_X, full_matrices=False)
    expected_ey_frob = float(math.sqrt(float(np.sum(sv_oracle[1:] ** 2))))

    femt_svd = femt_svd_decompose(S_nodes, rank=1)
    X_T = S_nodes.reshape(N_g, 4)
    recon_err = float(np.linalg.norm(X_T - femt_svd.U_raw @ femt_svd.C_raw, ord="fro"))
    assert abs(recon_err - expected_ey_frob) <= 1e-12
    assert abs(femt_svd.eckart_young_frobenius_error - expected_ey_frob) <= 1e-12

    # (c) Strict rule reduction N_r^FEMT < N_r^TPMT under coupled nonlinearities sin(x1+x2), cos(x1-x2)
    coupled_bounds = {"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]}
    coupled_A = [
        ["-1.0 + 0.5 * sin(x1 + x2)", "0.4 * cos(x1 - x2)"],
        ["0.3 * sin(x1 + x2)", "-2.0 + 0.5 * cos(x1 - x2)"],
    ]
    coupled_B = [["0"], ["1"]]
    coupled_C = [["1", "0"]]
    coupled_D = [["0"]]

    femt_coupled = derive_ts_femt(
        state_bounds=coupled_bounds,
        A_expr=coupled_A,
        B_expr=coupled_B,
        C_expr=coupled_C,
        D_expr=coupled_D,
        grid_points=15,
        svd_tol=1e-6,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=128,
    )
    tpmt_coupled = derive_ts_tpmt(
        state_bounds=coupled_bounds,
        A_expr=coupled_A,
        B_expr=coupled_B,
        C_expr=coupled_C,
        D_expr=coupled_D,
        grid_points=15,
        svd_tol=1e-6,
        hull_type="CNO",
        n_val_points=128,
    )
    assert femt_coupled.status in ("success", "warning")
    assert tpmt_coupled.status in ("success", "warning")
    n_rules_femt = len(_as_ts_model(femt_coupled).vertices)
    n_rules_tpmt = len(_as_ts_model(tpmt_coupled).vertices)
    assert n_rules_femt < n_rules_tpmt, (
        f"Expected N_r^FEMT ({n_rules_femt}) < N_r^TPMT ({n_rules_tpmt}) under coupling"
    )

    # (d) P1 barycentric interpolation (kuhn_delaunay & delaunay): Ruspini + O(h^2) convergence
    sampler = qmc.Sobol(d=2, scramble=False)
    eval_pts = [(-1.0 + 2.0 * float(u0), -1.0 + 2.0 * float(u1)) for u0, u1 in sampler.random_base2(m=7)]

    for mesh_kind in ("kuhn_delaunay", "delaunay"):
        errors_by_G: list[float] = []
        for G in (9, 17, 33):
            res_g = derive_ts_femt(
                state_bounds=coupled_bounds,
                A_expr=[["-1.0 + cos(x1) * sin(x2)", "1.0"], ["0.0", "-2.0"]],
                B_expr=[["0"], ["1"]],
                C_expr=[["1", "0"]],
                D_expr=[["0"]],
                grid_points=G,
                svd_tol=1e-12,
                hull_type="CNO",
                mesh_kind=mesh_kind,
                n_val_points=64,
            )
            assert res_g.status in ("success", "warning"), res_g.error
            ts_g: TSStateSpace = _as_ts_model(res_g)
            a00_verts = [float(np.asarray(v["A"], dtype=np.float64)[0, 0]) for v in ts_g.vertices]
            max_err_g = 0.0
            for x1, x2 in eval_pts:
                w_res = evaluate_ts_premise_weights(ts_g, {"x1": x1, "x2": x2})
                assert w_res.status == "success", w_res.error
                h = np.asarray(w_res.data["weights"], dtype=np.float64)
                assert float(np.min(h)) >= -1e-14
                assert abs(float(np.sum(h)) - 1.0) <= 1e-13
                approx_a00 = float(np.dot(h, a00_verts))
                exact_a00 = -1.0 + math.cos(x1) * math.sin(x2)
                max_err_g = max(max_err_g, abs(approx_a00 - exact_a00))
            errors_by_G.append(max_err_g)

        # Doubling mesh resolution halves h -> O(h^2) reduces error by ~4x
        assert errors_by_G[0] / max(errors_by_G[1], 1e-15) >= 3.0, (mesh_kind, errors_by_G)
        assert errors_by_G[1] / max(errors_by_G[2], 1e-15) >= 3.0, (mesh_kind, errors_by_G)
