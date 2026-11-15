"""Analytic regressions for the synchronous official discrete adapter.

F9 separately executes the emitted graph with the official converter/PathSim.
No fixture or tolerance in the independent oracle suite is modified here.
"""

import builtins
import copy

import numpy as np
import pytest

from control_lab.core import DynamicController, StateFeedbackController, StateSpace
from control_lab.core.tensors import tensor_to_array
from control_lab.diagnostics import ControlLabError, UnsupportedModelError
from control_lab.io import extract_lti_from_pvm, import_pvm, make_pvm, simulate_pvm_graph


def scalar_graph():
    plant = StateSpace([[0.8]], [[0.2]], [[1.0]], [[0.0]], dt=0.1)
    control = StateFeedbackController(
        [[0.5]], feedback_sign="negative", dt=0.1, reference_map=[[1.0]]
    )
    return make_pvm(
        plant, control, scenario={"initial_state": [1.0], "reference": {"value": [0.3]}}
    )


def test_clock_initial_value_and_complete_recurrence_are_preserved_passively():
    graph = scalar_graph()
    assert graph["metadata"]["discrete_clock_period"] == 0.1
    hold = next(n for n in graph["graph"]["nodes"] if n["type"] == "SampleHold")
    assert hold["params"] == {"T": "0.1", "tau": "0.1"}
    assert len(hold["inputs"]) == len(hold["outputs"]) == 1
    assert not graph["events"]
    assert all(n["type"] != "DiscreteStateSpace" for n in graph["graph"]["nodes"])
    assert all(
        "sampling_period" not in n["params"]
        for n in graph["graph"]["nodes"]
        if n["type"] == "Scope"
    )
    actual = simulate_pvm_graph(graph, np.arange(6) * 0.1, r=np.full((6, 1), 0.3))
    assert actual.status in {"success", "warning"}
    np.testing.assert_allclose(
        tensor_to_array(actual.data["x"]).reshape(-1),
        [1, 0.76, 0.592, 0.4744, 0.39208, 0.334456],
        rtol=0,
        atol=1e-14,
    )


def test_dynamic_state_and_plant_share_one_register_with_exact_augmented_matrix():
    plant = StateSpace([[0.8]], [[0.2]], [[1]], [[0.1]], dt=0.1)
    control = DynamicController(
        [[0.6]],
        [[0.3]],
        [[0.4]],
        [[0.2]],
        dt=0.1,
        initial_state=[-0.2],
        feedback_sign="negative",
        ports={
            "inputs": [{"name": "y", "role": "y", "size": 1}],
            "outputs": [{"name": "u", "role": "u", "size": 1}],
        },
        interconnection_scheme="output_feedback",
    )
    graph = make_pvm(plant, control, scenario={"initial_state": [0.7]})
    holds = [n for n in graph["graph"]["nodes"] if n["type"] == "SampleHold"]
    assert len(holds) == 1 and len(holds[0]["outputs"]) == 2
    original_roles = {
        n["controlLab"].get("legacy_node", {}).get("type") for n in graph["graph"]["nodes"]
    }
    assert {"StateSpace", "DynamicController"} <= original_roles
    transitions = [
        n for n in graph["graph"]["nodes"] if n["controlLab"].get("role") == "component_transition"
    ]
    assert len(transitions) == 2
    ux, uz = -0.2 / 1.02, -0.4 / 1.02
    expected = [[0.8 + 0.2 * ux, 0.2 * uz], [0.3 + 0.03 * ux, 0.6 + 0.03 * uz]]
    np.testing.assert_allclose(extract_lti_from_pvm(graph).A, expected, rtol=0, atol=1e-14)


@pytest.mark.parametrize(
    "tamper",
    [
        "tau",
        "period",
        "transition",
        "drop_internal",
        "extra_internal",
        "clock_port",
        "drop_clock",
        "bad_metadata",
        "state_order",
        "clock_layout",
    ],
)
def test_clock_projection_rejects_adulteration_without_executing_import(tamper, monkeypatch):
    graph = scalar_graph()
    hold = next(n for n in graph["graph"]["nodes"] if n["type"] == "SampleHold")
    transition = next(
        n for n in graph["graph"]["nodes"] if n["controlLab"].get("role") == "component_transition"
    )
    if tamper == "tau":
        hold["params"]["tau"] = "0.0"
    elif tamper == "period":
        graph["metadata"]["discrete_clock_period"] = 0.2
    elif tamper == "transition":
        transition["params"]["func"] = "__import__('builtins').F1_CLOCK_EXECUTED=True"
    elif tamper == "drop_internal":
        graph["graph"]["connections"].pop(0)
    elif tamper == "extra_internal":
        graph["graph"]["connections"].append(copy.deepcopy(graph["graph"]["connections"][0]))
    elif tamper == "clock_port":
        hold["outputs"][0]["name"] = "forged"
    elif tamper == "drop_clock":
        graph["graph"]["nodes"].remove(hold)
    elif tamper == "bad_metadata":
        transition["controlLab"]["legacy_node"]["params"].pop("A")
    elif tamper == "state_order":
        transition["controlLab"]["legacy_order"] = 200
    elif tamper == "clock_layout":
        hold["controlLab"]["state_layout"][0]["size"] = 10

    def forbidden(*args, **kwargs):
        raise AssertionError("No imported code may execute")

    monkeypatch.setattr(builtins, "eval", forbidden)
    monkeypatch.setattr(builtins, "exec", forbidden)
    with pytest.raises(ControlLabError):
        extract_lti_from_pvm(graph)


def test_clock_profile_import_is_passive_and_graph_order_is_not_semantic():
    graph = scalar_graph()
    graph["graph"]["nodes"].reverse()
    graph["graph"]["connections"].reverse()
    graph["codeContext"]["code"] = "raise RuntimeError('do not execute imported code')"
    assert import_pvm(graph).status == "warning"
    np.testing.assert_allclose(extract_lti_from_pvm(graph).A, [[0.7]], rtol=0, atol=1e-14)


def test_unverified_custom_events_are_rejected_in_discrete_export():
    plant = StateSpace([[0.8]], [[0.2]], [[1]], [[0]], dt=0.1)
    with pytest.raises(UnsupportedModelError, match="events"):
        make_pvm(plant, scenario={"events": [{"type": "Schedule", "params": {}}]})
