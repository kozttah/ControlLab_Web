"""F9-WASM-PVM-001: scalar ABI and passive projection regression tests.

Reference expectations here are analytic matrices and the pinned upstream ABI,
not values regenerated from the system under test. F9 independently executes
the emitted graph through the unmodified upstream converter and PathSim.
"""

import builtins

import numpy as np
import pytest

from control_lab.core import DynamicController, StateFeedbackController, StateSpace
from control_lab.diagnostics import ControlLabError, UnsupportedModelError
from control_lab.io import extract_lti_from_pvm, import_pvm, make_pvm
from control_lab.io.pvm_official import restore_numeric_projection


def model():
    return StateSpace([[0.0, 1.0], [0.0, 0.0]], [[0.0], [1.0]], [[1.0, 0.0]], [[0.0]])


def test_official_default_has_no_fictitious_types_and_scalar_state_ports():
    pvm = make_pvm(model(), StateFeedbackController([[2.0, 3.0]], feedback_sign="negative"))
    expected_params = {
        "Source": {"func"},
        "Function": {"func"},
        "StateSpace": {"A", "B", "C", "D", "initial_value"},
        "Adder": {"operations"},
        "Scope": {"labels"},
    }
    for node in pvm["graph"]["nodes"]:
        assert node["type"] in expected_params
        assert set(node["params"]) == expected_params[node["type"]]
    assert pvm["metadata"]["pathview_target_commit"] == "4afdcc461ed63aa4231930170d20774428d51e8d"
    plant = next(n for n in pvm["graph"]["nodes"] if n["id"] == "plant_ss")
    assert len(plant["inputs"]) == 1 and len(plant["outputs"]) == 3
    assert plant["params"]["C"] == "np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=float)"
    inputs_to_k = [c for c in pvm["graph"]["connections"] if c["targetNodeId"] == "gain_K"]
    assert [c["sourcePortIndex"] for c in inputs_to_k] == [1, 2]
    np.testing.assert_allclose(extract_lti_from_pvm(pvm).A, [[0, 1], [-2, -3]], rtol=0, atol=1e-14)


@pytest.mark.parametrize(
    "tamper",
    [
        "callback",
        "matrix",
        "port",
        "drop_channel",
        "permute_channel",
        "missing_extension",
        "malformed_extension",
    ],
)
def test_passive_projection_rejects_tampered_graph_or_expressions(tamper, monkeypatch):
    pvm = make_pvm(model(), StateFeedbackController([[2.0, 3.0]], feedback_sign="negative"))
    gain = next(n for n in pvm["graph"]["nodes"] if n["id"] == "gain_K")
    plant = next(n for n in pvm["graph"]["nodes"] if n["id"] == "plant_ss")
    if tamper == "callback":
        gain["params"]["func"] = "__import__('os').system('forbidden')"
    elif tamper == "matrix":
        plant["params"]["A"] = "np.array([[99,0],[0,99]])"
    elif tamper == "port":
        gain["inputs"][0]["name"] = "counterfeit"
    elif tamper == "drop_channel":
        pvm["graph"]["connections"] = [
            c
            for c in pvm["graph"]["connections"]
            if not (c["targetNodeId"] == "gain_K" and c["targetPortIndex"] == 1)
        ]
    elif tamper == "permute_channel":
        for c in pvm["graph"]["connections"]:
            if c["targetNodeId"] == "gain_K":
                c["targetPortIndex"] = 1 - c["targetPortIndex"]
    elif tamper == "missing_extension":
        gain.pop("controlLab")
    elif tamper == "malformed_extension":
        plant["controlLab"]["legacy_node"]["params"].pop("D")

    def forbidden(*args, **kwargs):
        raise AssertionError("No imported Python execution is authorized")

    monkeypatch.setattr(builtins, "eval", forbidden)
    monkeypatch.setattr(builtins, "exec", forbidden)
    with pytest.raises(ControlLabError):
        extract_lti_from_pvm(pvm)


def test_legacy_numeric_graph_stays_passive_and_compatible():
    current = make_pvm(model(), StateFeedbackController([[2.0, 3.0]], feedback_sign="negative"))
    legacy = restore_numeric_projection(current)
    legacy["metadata"].pop("adapter_profile")
    legacy["codeContext"]["code"] = "raise RuntimeError('must not execute')"
    assert import_pvm(legacy).status == "warning"
    np.testing.assert_allclose(
        extract_lti_from_pvm(legacy).A, [[0, 1], [-2, -3]], rtol=0, atol=1e-14
    )


def test_mimo_sources_are_separate_scalar_sources_and_prefilter_is_matrix_product():
    plant = StateSpace([[-1, 0], [0, -2]], np.eye(2), [[1, 0]], [[0, 0]])
    ctrl = StateFeedbackController(
        [[0.5, 0.1], [0.2, 0.8]], feedback_sign="negative", reference_map=[[2], [1.5]]
    )
    pvm = make_pvm(plant, ctrl)
    gain = next(n for n in pvm["graph"]["nodes"] if n["id"] == "gain_N")
    assert gain["type"] == "Function" and " @ " in gain["params"]["func"]
    assert len(gain["inputs"]) == 1 and len(gain["outputs"]) == 2
    np.testing.assert_allclose(extract_lti_from_pvm(pvm).B, [[2], [1.5]], rtol=0, atol=1e-14)
    open_loop = make_pvm(plant, scenario={"reference": {"value": [1, 2]}})
    sources = [n for n in open_loop["graph"]["nodes"] if n["type"] == "Source"]
    assert len(sources) == 2 and all(len(n["outputs"]) == 1 for n in sources)
    assert [n["params"]["func"] for n in sources] == ["lambda t: 1.0", "lambda t: 2.0"]


def test_dynamic_controller_remains_dynamic_in_official_graph():
    controller = DynamicController(
        Ac=[[-2]], Bc=[[1]], Cc=[[3]], Dc=[[0.2]], initial_state=[0.25], feedback_sign="negative"
    )
    pvm = make_pvm(model(), controller)
    node = next(n for n in pvm["graph"]["nodes"] if n["id"] == "ctrl_dynamic")
    assert node["type"] == "StateSpace"
    assert node["params"]["A"] == "np.array([[-2.0]], dtype=float)"
    assert node["params"]["initial_value"] == "np.array([0.25], dtype=float)"
    assert extract_lti_from_pvm(pvm).n_states == 3


def test_discrete_default_rejects_unverified_clock_semantics_but_legacy_is_explicit():
    from control_lab.io import export_pvm

    plant = StateSpace([[0.8]], [[0.2]], [[1]], [[0]], dt=0.1)
    controller = StateFeedbackController([[0.5]], feedback_sign="negative", dt=0.1)
    with pytest.raises(UnsupportedModelError, match="scheduling"):
        make_pvm(plant, controller)
    failed = export_pvm(plant, controller)
    assert failed.status == "failure" and failed.error.code == "UNSUPPORTED_MODEL"
    assert failed.error.parameters["reason"] == "discrete_schedule_mismatch"
    legacy = make_pvm(plant, controller, runtime_profile="legacy_numeric", return_result=True)
    assert legacy.status == "warning"
    assert legacy.diagnostics["external_compatible"] is False
    assert legacy.data["pvm"]["metadata"]["external_compatible"] is False
    assert any(w.code == "LEGACY_NUMERIC_PVM_ONLY" for w in legacy.warnings)
    np.testing.assert_allclose(
        extract_lti_from_pvm(legacy.data["pvm"]).A, [[0.7]], rtol=0, atol=1e-14
    )


@pytest.mark.parametrize(
    "invalid_solver", ["UnknownSolver", "RKCK54\nimport os", "RKCK54;raise RuntimeError()"]
)
def test_official_solver_parameter_is_a_real_class_token(invalid_solver):
    from control_lab.diagnostics import ValidationError

    with pytest.raises(ValidationError, match="solver"):
        make_pvm(model(), scenario={"solver": invalid_solver})


def test_invalid_runtime_profile_is_typed():
    from control_lab.diagnostics import ValidationError

    with pytest.raises(ValidationError, match="runtime_profile"):
        make_pvm(model(), runtime_profile=[])
