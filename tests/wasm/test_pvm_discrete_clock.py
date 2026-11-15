"""Clocked PVM graph parity, recurrence and passive import in real Pyodide."""

import numpy as np
import pytest

from scripts.browser_harness import browser_harness as browser_harness


def probe(mode):
    return f"""import json, builtins, copy, numpy as np
from control_lab.core import StateSpace, StateFeedbackController, DynamicController
from control_lab.io.pvm import make_pvm, import_pvm, simulate_pvm_graph
T=.1
if {mode!r} == "static":
    plant=StateSpace([[.8]],[[.2]],[[1.]],[[0.]],dt=T,id="wasm_clock_plant",revision=1)
    controller=StateFeedbackController([[.5]],reference_map=[[1.]],feedback_sign="negative",dt=T,id="wasm_clock_controller",revision=1)
    x0=[1.];r=[.3]
else:
    plant=StateSpace([[.8]],[[.2]],[[1.]],[[.1]],dt=T,id="wasm_clock_plant",revision=1)
    controller=DynamicController([[.6]],[[.3]],[[.4]],[[.2]],feedback_sign="negative",dt=T,initial_state=[-.2],ports={{"inputs":[{{"name":"y","role":"y","size":1}}],"outputs":[{{"name":"u","role":"u","size":1}}]}},interconnection_scheme="output_feedback",id="wasm_clock_controller",revision=1)
    x0=[.7];r=[.15]
model=make_pvm(plant,controller,scenario={{"initial_state":x0,"reference":{{"type":"constant","value":r}}}})
model["codeContext"]["code"]="__import__('builtins').F9_CLOCK_EXECUTED=True"
loaded=import_pvm(json.dumps(model))
times=np.arange(13)*T
sim=simulate_pvm_graph(model,times,r=np.tile(r,(len(times),1)))
bad=copy.deepcopy(model)
next(node for node in bad["graph"]["nodes"] if node["type"]=="SampleHold")["params"]["tau"]="0.0"
tampered=simulate_pvm_graph(bad,times,r=np.tile(r,(len(times),1)))
def values(v):
    return np.array(v["data"]).reshape(v["shape"],order=v.get("order","C")).tolist() if isinstance(v,dict) else np.asarray(v).tolist()
report={{"graph":model["graph"],"profile":model["metadata"]["adapter_profile"],"settings":model["simulationSettings"],"import_status":loaded.status,"sim_status":sim.status,"x":values(sim.data["x"]) if sim.data else None,"u":values(sim.data["u"]) if sim.data else None,"y":values(sim.data["y"]) if sim.data else None,"tamper_status":tampered.status,"tamper_error":tampered.error.code if tampered.error else None,"code_executed":hasattr(builtins,"F9_CLOCK_EXECUTED")}}
json.dumps(report)"""


def exact_samples(mode):
    x, z = (1.0, 0.0) if mode == "static" else (0.7, -0.2)
    values = {k: [] for k in ("x", "u", "y")}
    for _ in range(13):
        if mode == "static":
            u = -0.5 * x + 0.3
            y = x
        else:
            # Solve u=.15-.4z-.2(x+.1u), then update BOTH old states.
            u = (0.15 - 0.4 * z - 0.2 * x) / 1.02
            y = x + 0.1 * u
        values["x"].append([x] if mode == "static" else [x, z])
        values["u"].append([u])
        values["y"].append([y])
        x, z = 0.8 * x + 0.2 * u, 0.6 * z + 0.3 * y
    return values


@pytest.mark.parametrize("mode", ["static", "dynamic"])
def test_clocked_graph_recurrence_passive_import_and_tau_guard_in_wasm(browser_harness, mode):  # noqa: F811
    source = probe(mode)
    namespace = {}
    exec(source, namespace)  # Trusted audit source; never executes imported model code.
    native = namespace["report"]
    wasm = browser_harness.python(source)
    for key in (
        "graph",
        "profile",
        "settings",
        "import_status",
        "sim_status",
        "tamper_status",
        "tamper_error",
        "code_executed",
    ):
        assert wasm[key] == native[key]
    assert wasm["profile"] == "controllab.pathview.clocked.v2"
    assert sum(node["type"] == "SampleHold" for node in wasm["graph"]["nodes"]) == 1
    assert not any(node["type"] == "DiscreteStateSpace" for node in wasm["graph"]["nodes"])
    assert wasm["sim_status"] in {"success", "warning"}
    assert wasm["import_status"] in {"success", "warning"}
    assert wasm["tamper_status"] == "failure" and wasm["tamper_error"] == "IMPORT_UNTRUSTED_CODE"
    assert not wasm["code_executed"]
    for key, expected in exact_samples(mode).items():
        np.testing.assert_allclose(wasm[key], expected, rtol=0, atol=1e-11)
        np.testing.assert_allclose(native[key], expected, rtol=0, atol=1e-11)
    browser_harness.record("pvm-clock-" + mode, wasm)
