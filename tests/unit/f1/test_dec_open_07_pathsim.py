"""Real PathSim 0.31.0 + PathView 0.21.0 validation tests for DEC-OPEN-07 -> ADR-013.

Verifies:
1. TSStateSpace(kind='ts_measured') + PDCController script execution in PathSim 0.31.0
   against independent scipy.integrate.solve_ivp (max error < 1e-4).
2. FuzzySystem (Mamdani & Takagi-Sugeno, single & multi-output) pure-NumPy evaluator +
   PathSim 0.31.0 runner against control_lab.fuzzy.evaluate (max error < 1e-4).
3. MIMO H-infinity DynamicController exported to native .pvm, converted via unmodified
   PathView 0.21.0 generate_python, and executed in PathSim 0.31.0 against independent
   scipy.integrate.solve_ivp (max error < 1e-4).
4. io.export_pathsim_script RPC envelope validation, passive flags, store refs, and
   security blocking for polytopic_uncertain + PDCController.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from scipy.integrate import solve_ivp

from control_lab.core.controllers import DynamicController, PDCController
from control_lab.core.interconnect import interconnect
from control_lab.core.models import FuzzySystem, StateSpace, TSStateSpace
from control_lab.core.rpc import SUPPORTED_OPERATIONS, dispatch_rpc
from control_lab.core.serialization import restore_model
from control_lab.frequency.mimo import design_hinf_mixed_sensitivity
from control_lab.fuzzy import evaluate as fuzzy_evaluate
from control_lab.io.pvm import (
    PATHVIEW_BLOCK_REGISTRY,
    generate_pathsim_script,
    make_pvm,
)

HAS_PATHSIM = importlib.util.find_spec("pathsim") is not None
HAS_PATHVIEW = importlib.util.find_spec("pathview") is not None


def _rpc_request(operation: str, payload: dict[str, Any], *, options: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "api_version": "1.0",
        "request_id": f"req-{operation}",
        "project_id": "proj-dec07",
        "project_revision": 1,
        "operation": operation,
        "payload": payload,
        "options": options or {},
        "timeout_policy": {"hard_timeout_ms": 30000},
    }


def _validate_rpc_response_schema(response: dict[str, Any]) -> None:
    schemas_dir = Path(__file__).resolve().parents[3] / "contracts/schemas"
    registry = Registry()
    for schema_file in schemas_dir.glob("*.schema.json"):
        raw = json.loads(schema_file.read_text(encoding="utf-8"))
        resource = Resource.from_contents(raw)
        registry = registry.with_resource(schema_file.name, resource)
        if "$id" in raw:
            registry = registry.with_resource(raw["$id"], resource)
    rpc_schema = json.loads((schemas_dir / "rpc_response.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(rpc_schema, registry=registry).validate(response)


def _make_ts_measured_and_pdc() -> tuple[TSStateSpace, PDCController]:
    v1 = {
        "vertex_id": "v1",
        "A": np.array([[0.0, 1.0], [-2.0, -1.0]], dtype=np.float64),
        "B": np.array([[0.0], [1.0]], dtype=np.float64),
        "C": np.array([[1.0, 0.0]], dtype=np.float64),
        "D": np.array([[0.0]], dtype=np.float64),
    }
    v2 = {
        "vertex_id": "v2",
        "A": np.array([[0.0, 1.0], [-4.0, -2.0]], dtype=np.float64),
        "B": np.array([[0.0], [1.5]], dtype=np.float64),
        "C": np.array([[1.0, 0.0]], dtype=np.float64),
        "D": np.array([[0.0]], dtype=np.float64),
    }
    ts_plant = TSStateSpace(
        vertices=[v1, v2],
        kind="ts_measured",
        dt=None,
        membership_spec={
            "version": "1.0",
            "premise_variables": ["x1"],
            "sum_to_one_domain": True,
        },
        premise_availability={
            "mode": "all_measured",
            "measured_premises": ["x1"],
            "unmeasured_premises": [],
        },
        domain={"bounds": {"x1": [-2.0, 2.0]}},
        id="ts-plant-dec07",
        revision=1,
        state_names=["x1", "x2"],
    )
    pdc = PDCController(
        K_i=[
            np.array([[1.0, 1.5]], dtype=np.float64),
            np.array([[1.5, 2.0]], dtype=np.float64),
        ],
        feedback_sign="negative",
        membership_ref={
            "model_id": ts_plant.id,
            "model_revision": ts_plant.revision,
            "membership_version": "1.0",
        },
        measurement_requirements={
            "required_premise_variables": ["x1"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_measured"],
        },
        id="pdc-dec07",
        revision=1,
    )
    return ts_plant, pdc


def _make_mamdani_fuzzy_system() -> FuzzySystem:
    return FuzzySystem(
        inference_type="mamdani",
        input_variables=[
            {
                "name": "e",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "neg", "mf": "trapezoidal", "params": [-1.0, -1.0, -0.4, 0.0]},
                    {"name": "zero", "mf": "triangular", "params": [-0.5, 0.0, 0.5]},
                    {"name": "pos", "mf": "gaussian", "params": [0.7, 0.35]},
                ],
            },
            {
                "name": "de",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "neg", "mf": "bell", "params": [0.45, 2.0, -0.6]},
                    {"name": "pos", "mf": "gaussian", "params": [0.5, 0.45]},
                ],
            },
        ],
        output_variables=[
            {
                "name": "u",
                "universe": [-10.0, 10.0],
                "terms": [
                    {"name": "low", "mf": "triangular", "params": [-10.0, -6.0, 0.0]},
                    {"name": "mid", "mf": "triangular", "params": [-4.0, 0.0, 4.0]},
                    {"name": "high", "mf": "trapezoidal", "params": [0.0, 5.0, 10.0, 10.0]},
                ],
            }
        ],
        rules=[
            {"antecedents": {"e": "neg", "de": "neg"}, "consequents": {"u": "low"}},
            {"antecedents": {"e": "neg", "de": "pos"}, "consequents": {"u": "mid"}},
            {"antecedents": {"e": "zero", "de": "neg"}, "consequents": {"u": "low"}},
            {"antecedents": {"e": "zero", "de": "pos"}, "consequents": {"u": "high"}},
            {"antecedents": {"e": "pos", "de": "neg"}, "consequents": {"u": "mid"}},
            {"antecedents": {"e": "pos", "de": "pos"}, "consequents": {"u": "high"}},
        ],
        operators={"and": "min", "or": "max", "implication": "min", "aggregation": "max", "defuzzification": "centroid"},
        id="mamdani-dec07",
        revision=1,
    )


def _make_ts_fuzzy_system() -> FuzzySystem:
    return FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "e",
                "universe": [-2.0, 2.0],
                "terms": [
                    {"name": "neg", "mf": "gaussian", "params": [-1.0, 0.8]},
                    {"name": "pos", "mf": "bell", "params": [0.9, 2.0, 1.0]},
                ],
            },
            {
                "name": "de",
                "universe": [-2.0, 2.0],
                "terms": [
                    {"name": "low", "mf": "trapezoidal", "params": [-2.0, -2.0, -0.3, 0.5]},
                    {"name": "high", "mf": "triangular", "params": [-0.5, 1.0, 2.0]},
                ],
            },
        ],
        output_variables=[
            {
                "name": "u",
                "universe": [-20.0, 20.0],
                "terms": [
                    {"name": "f1", "mf": "linear", "params": [1.5, 0.4, -1.0]},
                    {"name": "f2", "mf": "linear", "params": [0.8, 1.2, 0.2]},
                    {"name": "f3", "mf": "linear", "params": [2.0, -0.3, 0.5]},
                    {"name": "f4", "mf": "linear", "params": [1.1, 0.9, 1.5]},
                ],
            }
        ],
        rules=[
            {"antecedents": {"e": "neg", "de": "low"}, "consequents": {"u": "f1"}},
            {"antecedents": {"e": "neg", "de": "high"}, "consequents": {"u": "f2"}},
            {"antecedents": {"e": "pos", "de": "low"}, "consequents": {"u": "f3"}},
            {"antecedents": {"e": "pos", "de": "high"}, "consequents": {"u": "f4"}},
        ],
        operators={"and": "prod", "or": "max", "defuzzification": "wtaver"},
        id="ts-fuzzy-dec07",
        revision=1,
    )


def _make_mimo_hinf_plant_and_controller() -> tuple[StateSpace, DynamicController]:
    plant = StateSpace(
        A=np.array([[-1.0, 0.2], [0.1, -2.0]], dtype=np.float64),
        B=np.array([[1.0, 0.4], [0.3, 1.2]], dtype=np.float64),
        C=np.array([[1.0, 0.1], [0.2, 1.0]], dtype=np.float64),
        D=np.zeros((2, 2), dtype=np.float64),
        dt=None,
        id="mimo_hinf_plant_dec07",
        revision=1,
    )
    hinf_res = design_hinf_mixed_sensitivity(
        plant,
        w_s={"dc_gain": 20.0, "wb": 0.5, "m_s": 2.0},
        w_u={"gain": 0.2},
        w_t={"wt": 10.0, "m_t": 2.0, "at": 0.05},
        omega=np.logspace(-2, 2, 40),
        gamma_tol=1e-2,
    )
    assert hinf_res.status == "success" and hinf_res.data is not None
    assert hinf_res.data["is_stable"] is True

    ctrl_ss = restore_model(hinf_res.data["controller"])
    assert isinstance(ctrl_ss, StateSpace)
    dyn_ctrl = DynamicController(
        Ac=ctrl_ss.A,
        Bc=ctrl_ss.B,
        Cc=ctrl_ss.C,
        Dc=ctrl_ss.D,
        feedback_sign="negative",
        id="mimo_hinf_dyn_ctrl",
        revision=1,
    )
    return plant, dyn_ctrl


def test_registry_documents_adr_013_alongside_dec_open_07() -> None:
    assert PATHVIEW_BLOCK_REGISTRY["dec_open_07_decision"] == "ADR-013"
    assert "unsupported_pending_dec_open_07" in PATHVIEW_BLOCK_REGISTRY
    assert set(PATHVIEW_BLOCK_REGISTRY["unsupported_pending_dec_open_07"]) == {
        "PDCController",
        "FuzzySystem",
        "TSStateSpace",
    }


def test_1_pure_python_ts_pdc_script_generation_and_polytopic_blocking() -> None:
    ts_plant, pdc = _make_ts_measured_and_pdc()
    x0 = np.array([0.8, -0.3], dtype=np.float64)

    res1 = generate_pathsim_script(ts_plant, pdc, scenario={"duration": 4.0, "dt": 0.01, "initial_state": x0.tolist()})
    res2 = generate_pathsim_script(ts_plant, pdc, scenario={"duration": 4.0, "dt": 0.01, "initial_state": x0.tolist()})
    assert res1.status == "warning"
    assert res1.data is not None
    assert res1.data["code_executed"] is False
    assert res1.data["requires_explicit_user_execution"] is True
    assert res1.data["script"] == res2.data["script"]

    script = res1.data["script"]
    for token in ("A_vertices", "B_vertices", "K_vertices", "feedback_sign", "sign_factor", "def ts_pdc_rhs", "def run_pathsim_simulation"):
        assert token in script
    tree = ast.parse(script)
    imported_modules = {
        *(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names),
        *(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)),
    }
    assert all(not mod.startswith("control_lab") for mod in imported_modules)

    ts_poly = ts_plant.with_revision(
        kind="polytopic_uncertain",
        premise_availability={"mode": "unknown_uncertain", "measured_premises": [], "unmeasured_premises": ["x1"]},
    )
    blocked = generate_pathsim_script(ts_poly, pdc)
    assert blocked.status == "failure"
    assert blocked.error is not None
    assert blocked.error.code == "HYPOTHESIS_VIOLATED"


def test_1_ts_measured_pdc_pathsim_script_matches_scipy_solve_ivp() -> None:
    ts_plant, pdc = _make_ts_measured_and_pdc()
    x0 = np.array([0.8, -0.3], dtype=np.float64)

    res1 = generate_pathsim_script(ts_plant, pdc, scenario={"duration": 4.0, "dt": 0.01, "initial_state": x0.tolist()})
    res2 = generate_pathsim_script(ts_plant, pdc, scenario={"duration": 4.0, "dt": 0.01, "initial_state": x0.tolist()})
    assert res1.status == "warning"
    assert res1.data is not None
    assert res1.data["code_executed"] is False
    assert res1.data["requires_explicit_user_execution"] is True
    assert res1.data["script"] == res2.data["script"]  # deterministic

    script = res1.data["script"]
    for token in ("A_vertices", "B_vertices", "K_vertices", "feedback_sign", "sign_factor", "def ts_pdc_rhs", "def run_pathsim_simulation"):
        assert token in script

    ns: dict[str, Any] = {"__name__": "test_ts_pdc_isolated"}
    exec(compile(script, "<ts_pdc_pathsim_script>", "exec"), ns)

    def h_fn(x: np.ndarray, t: float) -> np.ndarray:
        del t
        z = float(np.clip(x[0], -1.0, 1.0))
        h1 = 0.5 * (1.0 + z)
        return np.array([h1, 1.0 - h1], dtype=np.float64)

    # Independent SciPy ODE reference (no call to generated code)
    A1, A2 = ts_plant.vertices[0]["A"], ts_plant.vertices[1]["A"]
    B1, B2 = ts_plant.vertices[0]["B"], ts_plant.vertices[1]["B"]
    K1, K2 = pdc.K_i[0], pdc.K_i[1]

    def ref_ode(t: float, x: np.ndarray) -> np.ndarray:
        h = h_fn(x, t)
        A_cl = (
            h[0] * A1
            + h[1] * A2
            - (h[0] * B1 + h[1] * B2) @ (h[0] * K1 + h[1] * K2)
        )
        return A_cl @ x

    t_grid = np.linspace(0.0, 4.0, 401)
    sol_script = solve_ivp(
        lambda t, x: ns["ts_pdc_rhs"](x, h_fn(x, t), np.zeros(1, dtype=np.float64)),
        (0.0, 4.0),
        x0,
        t_eval=t_grid,
        method="DOP853",
        rtol=1e-10,
        atol=1e-12,
    )
    sol_ref_grid = solve_ivp(ref_ode, (0.0, 4.0), x0, t_eval=t_grid, method="DOP853", rtol=1e-10, atol=1e-12)
    assert sol_script.success and sol_ref_grid.success
    assert float(np.max(np.abs(sol_script.y - sol_ref_grid.y))) < 1e-10

    if HAS_PATHSIM:
        assert version("pathsim") == "0.31.0"
        t_ps, x_ps = ns["run_pathsim_simulation"](duration=4.0, dt=0.01, x0=x0, h_fn=h_fn)
        assert t_ps.ndim == 1 and t_ps.size == 401
        assert x_ps.shape == (401, 2)

        sol = solve_ivp(ref_ode, (0.0, 4.0), x0, t_eval=t_ps, method="DOP853", rtol=1e-10, atol=1e-12)
        assert sol.success
        max_err = float(np.max(np.abs(x_ps - sol.y.T)))
        assert max_err < 1e-4, f"TS-PDC PathSim trajectory diverged from solve_ivp: max_err={max_err}"

    # Polytopic uncertain + PDC must remain strictly blocked
    ts_poly = ts_plant.with_revision(
        kind="polytopic_uncertain",
        premise_availability={"mode": "unknown_uncertain", "measured_premises": [], "unmeasured_premises": ["x1"]},
    )
    blocked = generate_pathsim_script(ts_poly, pdc)
    assert blocked.status == "failure"
    assert blocked.error is not None
    assert blocked.error.code == "HYPOTHESIS_VIOLATED"


@pytest.mark.parametrize("kind", ["mamdani", "ts"])
def test_2_pure_python_fuzzy_script_generation_ast_and_evaluator(kind: str) -> None:
    fz = _make_mamdani_fuzzy_system() if kind == "mamdani" else _make_ts_fuzzy_system()

    res = generate_pathsim_script(fz, scenario={"duration": 2.0, "dt": 0.1})
    assert res.status == "warning"
    assert res.data is not None
    assert res.data["code_executed"] is False
    assert res.data["requires_explicit_user_execution"] is True

    script = res.data["script"]
    assert "fuzzy_spec" in script
    assert "def eval_fuzzy_point" in script
    assert "def run_pathsim_simulation" in script
    tree = ast.parse(script)
    imported_modules = {
        *(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names),
        *(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)),
    }
    assert all(not mod.startswith("control_lab") for mod in imported_modules)

    ns: dict[str, Any] = {"__name__": f"test_fuzzy_{kind}_pure_python"}
    exec(compile(script, f"<fuzzy_{kind}_pure_python>", "exec"), ns)

    for t in (0.0, 0.5, 1.0, 1.5, 2.0):
        e_val = float(0.8 * np.sin(2.0 * t))
        de_val = float(0.7 * np.cos(1.5 * t))
        y_script = float(ns["eval_fuzzy_point"](e_val, de_val))
        ev = fuzzy_evaluate(fz, [e_val, de_val])
        assert ev.status in ("success", "warning")
        assert ev.data is not None
        assert abs(y_script - float(ev.data["outputs"]["u"])) < 1e-4


@pytest.mark.parametrize("kind", ["mamdani", "ts"])
def test_2_fuzzy_system_pathsim_script_matches_fuzzy_evaluate(kind: str) -> None:
    fz = _make_mamdani_fuzzy_system() if kind == "mamdani" else _make_ts_fuzzy_system()

    res = generate_pathsim_script(fz, scenario={"duration": 2.0, "dt": 0.1})
    assert res.status == "warning"
    assert res.data is not None
    assert res.data["code_executed"] is False
    assert res.data["requires_explicit_user_execution"] is True

    script = res.data["script"]
    assert "fuzzy_spec" in script
    assert "def eval_fuzzy_point" in script
    assert "def run_pathsim_simulation" in script
    tree = ast.parse(script)
    imported_modules = {
        *(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names),
        *(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)),
    }
    assert all(not mod.startswith("control_lab") for mod in imported_modules)

    ns: dict[str, Any] = {"__name__": f"test_fuzzy_{kind}_isolated"}
    exec(compile(script, f"<fuzzy_{kind}_pathsim_script>", "exec"), ns)

    def inputs_fn(t: float) -> list[float]:
        return [float(0.8 * np.sin(2.0 * t)), float(0.7 * np.cos(1.5 * t))]

    t_grid = np.linspace(0.0, 2.0, 21)
    y_np = np.array([[float(ns["eval_fuzzy_point"](*inputs_fn(float(tk))))] for tk in t_grid], dtype=np.float64)
    y_ref_grid = np.zeros_like(y_np)
    for idx, tk in enumerate(t_grid):
        ev = fuzzy_evaluate(fz, inputs_fn(float(tk)))
        assert ev.status in ("success", "warning")
        assert ev.data is not None
        y_ref_grid[idx, 0] = float(ev.data["outputs"]["u"])
    assert float(np.max(np.abs(y_np - y_ref_grid))) < 1e-4

    if HAS_PATHSIM:
        assert version("pathsim") == "0.31.0"
        t_ps, y_ps = ns["run_pathsim_simulation"](duration=2.0, dt=0.1, inputs_fn=inputs_fn)
        assert t_ps.ndim == 1 and t_ps.size == 21
        assert y_ps.shape == (21, 1)

        y_ref = np.zeros_like(y_ps)
        for idx, tk in enumerate(t_ps):
            ev = fuzzy_evaluate(fz, inputs_fn(float(tk)))
            assert ev.status in ("success", "warning")
            assert ev.data is not None
            y_ref[idx, 0] = float(ev.data["outputs"]["u"])

        max_err = float(np.max(np.abs(y_ps - y_ref)))
        assert max_err < 1e-4, f"Fuzzy ({kind}) PathSim output diverged from evaluate(): max_err={max_err}"


def test_2b_fuzzy_system_multi_output_pathsim_script() -> None:
    fz_multi = FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "x",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "low", "mf": "triangular", "params": [-1.0, -1.0, 1.0]},
                    {"name": "high", "mf": "triangular", "params": [-1.0, 1.0, 1.0]},
                ],
            }
        ],
        output_variables=[
            {
                "name": "u1",
                "universe": [-5.0, 5.0],
                "terms": [
                    {"name": "a", "mf": "linear", "params": [2.0, -1.0]},
                    {"name": "b", "mf": "linear", "params": [1.0, 2.0]},
                ],
            },
            {
                "name": "u2",
                "universe": [-5.0, 5.0],
                "terms": [
                    {"name": "c", "mf": "constant", "params": [-1.5]},
                    {"name": "d", "mf": "constant", "params": [2.5]},
                ],
            },
        ],
        rules=[
            {"antecedents": {"x": "low"}, "consequents": {"u1": "a", "u2": "c"}},
            {"antecedents": {"x": "high"}, "consequents": {"u1": "b", "u2": "d"}},
        ],
        id="fuzzy-multi-out",
        revision=1,
    )
    res = generate_pathsim_script(fz_multi, scenario={"duration": 1.0, "dt": 0.1})
    assert res.status == "warning" and res.data is not None
    ns: dict[str, Any] = {"__name__": "test_fuzzy_multi_out"}
    exec(compile(res.data["script"], "<fuzzy_multi_out>", "exec"), ns)

    for tk in np.linspace(0.0, 1.0, 11):
        x_val = float(2.0 * float(tk) - 1.0)
        out_u1, out_u2 = ns["eval_fuzzy_point"](x_val)
        ev = fuzzy_evaluate(fz_multi, [x_val])
        assert ev.data is not None
        assert abs(float(out_u1) - float(ev.data["outputs"]["u1"])) < 1e-10
        assert abs(float(out_u2) - float(ev.data["outputs"]["u2"])) < 1e-10

    if HAS_PATHSIM:
        t_ps, y_ps = ns["run_pathsim_simulation"](duration=1.0, dt=0.1, inputs_fn=lambda t: [float(2.0 * t - 1.0)])
        assert y_ps.shape == (11, 2)
        for idx, tk in enumerate(t_ps):
            ev = fuzzy_evaluate(fz_multi, [float(2.0 * float(tk) - 1.0)])
            assert ev.data is not None
            assert abs(y_ps[idx, 0] - float(ev.data["outputs"]["u1"])) < 1e-10
            assert abs(y_ps[idx, 1] - float(ev.data["outputs"]["u2"])) < 1e-10


def test_3_pure_python_mimo_hinf_dynamic_controller_make_pvm() -> None:
    plant, dyn_ctrl = _make_mimo_hinf_plant_and_controller()
    ref_val = [1.0, 0.5]
    pvm = make_pvm(
        plant,
        dyn_ctrl,
        scenario={
            "duration": 5.0,
            "dt": 0.005,
            "solver": "RKCK54",
            "adaptive": False,
            "reference": {"value": ref_val},
        },
    )
    assert pvm["version"] == "1.0.0"
    assert json.loads(json.dumps(pvm)) == pvm
    node_ids = {node["id"] for node in pvm["graph"]["nodes"]}
    assert "scope_y" in node_ids
    ss_nodes = [node for node in pvm["graph"]["nodes"] if node["type"] == "StateSpace"]
    assert len(ss_nodes) >= 2


def test_3_mimo_hinf_dynamic_controller_pvm_pathview_pathsim_matches_solve_ivp() -> None:
    plant, dyn_ctrl = _make_mimo_hinf_plant_and_controller()

    ref_val = [1.0, 0.5]
    pvm = make_pvm(
        plant,
        dyn_ctrl,
        scenario={
            "duration": 5.0,
            "dt": 0.005,
            "solver": "RKCK54",
            "adaptive": False,
            "reference": {"value": ref_val},
        },
    )
    assert pvm["version"] == "1.0.0"
    assert json.loads(json.dumps(pvm)) == pvm
    scope_node = next(n for n in pvm["graph"]["nodes"] if n["id"] == "scope_y")
    assert scope_node["type"] == "Scope"

    # Independent closed-loop SciPy reference
    cl = interconnect(plant, dyn_ctrl)
    r_vec = np.array(ref_val, dtype=np.float64)

    if HAS_PATHVIEW and HAS_PATHSIM:
        import pathview
        from pathview.converter import generate_python, load_registry, sanitize_name

        assert version("pathview") == "0.21.0" and version("pathsim") == "0.31.0"

        registry = load_registry(Path(pathview.__file__).parent / "data/registry.json")
        for node in pvm["graph"]["nodes"]:
            assert set(node["params"]) <= set(registry["blocks"][node["type"]]["params"])

        source = generate_python(pvm, registry, source_name="mimo_hinf_closed_loop.pvm")
        ns: dict[str, Any] = {"__name__": "test_mimo_hinf_pvm_run"}
        exec(compile(source, "<mimo_hinf_pvm>", "exec"), ns)

        sim = ns["sim"]
        sim.run(duration=5.0, adaptive=False)
        scope = ns[sanitize_name(scope_node["name"])]
        t_ps, y_raw = scope.read()
        y_ps = np.asarray(y_raw, dtype=np.float64).T
        assert y_ps.shape == (len(t_ps), 2)

        sol = solve_ivp(
            lambda t, x: cl.A @ x + cl.B @ r_vec,
            (0.0, 5.0),
            np.zeros(cl.n_states, dtype=np.float64),
            t_eval=t_ps,
            method="DOP853",
            rtol=1e-10,
            atol=1e-12,
        )
        assert sol.success
        y_ref = (sol.y.T @ cl.C.T) + (np.tile(r_vec, (len(t_ps), 1)) @ cl.D.T)

        max_err = float(np.max(np.abs(y_ps - y_ref)))
        assert max_err < 1e-4, f"MIMO Hinf PVM->PathView->PathSim trajectory diverged: max_err={max_err}"
    else:
        t_grid = np.linspace(0.0, 5.0, 101)
        sol = solve_ivp(
            lambda t, x: cl.A @ x + cl.B @ r_vec,
            (0.0, 5.0),
            np.zeros(cl.n_states, dtype=np.float64),
            t_eval=t_grid,
            method="DOP853",
            rtol=1e-10,
            atol=1e-12,
        )
        assert sol.success
        y_ref = (sol.y.T @ cl.C.T) + (np.tile(r_vec, (len(t_grid), 1)) @ cl.D.T)
        assert y_ref.shape == (len(t_grid), 2)
        assert np.all(np.isfinite(y_ref))


def test_4_rpc_io_export_pathsim_script_fuzzy_and_ts_pdc() -> None:
    assert "io.export_pathsim_script" in SUPPORTED_OPERATIONS

    cap_resp = dispatch_rpc(_rpc_request("core.capabilities", {}))
    assert cap_resp["status"] == "success"
    assert "io.export_pathsim_script" in cap_resp["result"]["supported_operations"]

    # 1) FuzzySystem inline via fuzzy_system
    fz = _make_mamdani_fuzzy_system()
    resp_fz = dispatch_rpc(
        _rpc_request(
            "io.export_pathsim_script",
            {
                "fuzzy_system": fz.to_dict(),
                "scenario": {"duration": 2.0, "dt": 0.1},
            },
        )
    )
    _validate_rpc_response_schema(resp_fz)
    assert resp_fz["status"] in ("success", "warning")
    result_fz = resp_fz["result"]
    assert result_fz["code_executed"] is False
    assert result_fz["requires_explicit_user_execution"] is True
    assert result_fz["media_type"] == "text/x-python"
    assert result_fz["language"] == "python"
    assert result_fz["filename"] == "controllab_pathsim_simulation.py"
    compile(result_fz["script"], result_fz["filename"], "exec")

    # 2) FuzzySystem via system_ref in store
    store = {("proj-dec07", fz.id, fz.revision): fz.to_dict()}
    resp_ref = dispatch_rpc(
        _rpc_request(
            "io.export_pathsim_script",
            {
                "system_ref": {"id": fz.id, "revision": fz.revision},
                "filename": "custom_fuzzy_sim",
            },
        ),
        store=store,
    )
    _validate_rpc_response_schema(resp_ref)
    assert resp_ref["status"] in ("success", "warning")
    assert resp_ref["result"]["filename"] == "custom_fuzzy_sim.py"
    assert resp_ref["result"]["code_executed"] is False
    compile(resp_ref["result"]["script"], resp_ref["result"]["filename"], "exec")

    # 3) TSStateSpace(ts_measured) + PDCController via plant + controller
    ts_plant, pdc = _make_ts_measured_and_pdc()
    resp_ts = dispatch_rpc(
        _rpc_request(
            "io.export_pathsim_script",
            {
                "plant": ts_plant.to_dict(),
                "controller": pdc.to_dict(),
                "scenario": {"duration": 3.0, "dt": 0.02},
            },
        )
    )
    _validate_rpc_response_schema(resp_ts)
    assert resp_ts["status"] in ("success", "warning")
    assert resp_ts["result"]["code_executed"] is False
    assert resp_ts["result"]["requires_explicit_user_execution"] is True
    assert "def run_pathsim_simulation" in resp_ts["result"]["script"]
    compile(resp_ts["result"]["script"], resp_ts["result"]["filename"], "exec")

    # 4) polytopic_uncertain + PDCController rejected with HYPOTHESIS_VIOLATED
    ts_poly = ts_plant.with_revision(
        kind="polytopic_uncertain",
        premise_availability={"mode": "unknown_uncertain", "measured_premises": [], "unmeasured_premises": ["x1"]},
    )
    resp_blocked = dispatch_rpc(
        _rpc_request(
            "io.export_pathsim_script",
            {"plant": ts_poly.to_dict(), "controller": pdc.to_dict()},
        )
    )
    _validate_rpc_response_schema(resp_blocked)
    assert resp_blocked["status"] == "failure"
    assert resp_blocked["error"]["code"] == "HYPOTHESIS_VIOLATED"
