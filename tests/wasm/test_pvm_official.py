"""New PVM adapter parity and passive import in the actual shipped Pyodide wheel."""

import pytest

from scripts.browser_harness import browser_harness


def probe(mode):
    return f"""import json, builtins, numpy as np
from control_lab.core import StateSpace, StateFeedbackController, DynamicController
from control_lab.io.pvm import make_pvm, export_pvm, import_pvm
plant=StateSpace([[0.,1.],[0.,0.]],[[0.],[1.]],[[1.,0.]],[[0.]],id="f9-wasm-pvm",revision=1)
if {mode!r} == "dynamic":
    controller=DynamicController([[-2.]],[[1.]],[[.8]],[[.2]],feedback_sign="negative",initial_state=[.3],ports={{"inputs":[{{"name":"y","role":"y","size":1}}],"outputs":[{{"name":"u","role":"u","size":1}}]}},interconnection_scheme="output_feedback",id="f9-wasm-controller",revision=1)
else:
    controller=StateFeedbackController([[2.,3.]],feedback_sign="negative",id="f9-wasm-controller",revision=1)
model=make_pvm(plant,controller,scenario={{"initial_state":[1.,-.3]}})
original_code=model["codeContext"]["code"]
model["codeContext"]["code"]="__import__('builtins').F9_PVM_EXECUTED=True"
imported=import_pvm(json.dumps(model))
discrete=StateSpace([[.8]],[[.2]],[[1.]],[[0.]],dt=.1,id="f9-wasm-discrete",revision=1)
refusal=export_pvm(discrete)
report={{"graph":model["graph"],"generated_code":original_code,"settings":model["simulationSettings"],"passive_status":imported.status,"code_executed":hasattr(builtins,"F9_PVM_EXECUTED"),"discrete_status":refusal.status,"discrete_error":refusal.error.code if refusal.error else None}}
json.dumps(report)"""


@pytest.mark.parametrize("mode", ["static", "dynamic"])
def test_official_pvm_adapter_matches_cpython_and_never_executes_import(browser_harness, mode):
    source = probe(mode)
    namespace = {}
    exec(source, namespace)  # Trusted test source, never imported model code.
    native = namespace["report"]
    wasm = browser_harness.python(source)
    assert native == wasm
    assert not wasm["code_executed"]
    assert wasm["passive_status"] in {"success", "warning"}
    assert wasm["discrete_status"] == "failure"
    assert wasm["discrete_error"] == "UNSUPPORTED_MODEL"
    assert all(
        node["type"] not in {"MatrixGain", "DynamicController", "Saturation"}
        for node in wasm["graph"]["nodes"]
    )
    browser_harness.record("pvm-official-" + mode, wasm)
