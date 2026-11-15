"""T-CARE-02/03: actual product Worker -> Pyodide -> identical wheel -> RPC."""

import json
from pathlib import Path

import numpy as np
from control_lab.core.rpc import dispatch
from scripts.browser_harness import browser_harness, care_request

ROOT = Path(__file__).resolve().parents[2]


def test_care_12x3_cpython_pyodide_parity(browser_harness):
    fixture = json.loads((ROOT / "contracts/fixtures/B-CARE-12x3.json").read_text())
    request = care_request(fixture)
    native = dispatch(request)
    wasm = browser_harness.rpc(request)
    assert native["status"] == wasm["status"] == "success", wasm
    tolerance = fixture["tolerances"]
    comparisons = {}
    for name in ("P", "K"):
        actual = np.array(wasm["result"][name]["data"]).reshape(
            wasm["result"][name]["shape"], order=wasm["result"][name]["order"]
        )
        expected = np.array(fixture["data"]["expected"][name]["data"]).reshape(
            fixture["data"]["expected"][name]["shape"],
            order=fixture["data"]["expected"][name]["order"],
        )
        limit = tolerance[name + "_rel_tol"]
        error = float(np.linalg.norm(actual - expected) / (1 + np.linalg.norm(expected)))
        assert error <= limit
        assert (
            np.linalg.norm(
                actual
                - np.array(native["result"][name]["data"]).reshape(
                    native["result"][name]["shape"], order=native["result"][name]["order"]
                )
            )
            / (1 + np.linalg.norm(actual))
            <= limit
        )
        comparisons[name + "_relative_error"] = error
    A = np.array(fixture["data"]["A"]["data"]).reshape(12, 12)
    B = np.array(fixture["data"]["B"]["data"]).reshape(12, 3)
    Q = np.array(fixture["data"]["Q"]["data"]).reshape(12, 12)
    R = np.array(fixture["data"]["R"]["data"]).reshape(3, 3)
    P = np.array(wasm["result"]["P"]["data"]).reshape(12, 12)
    terms = [A.T @ P, P @ A, -P @ B @ np.linalg.solve(R, B.T @ P), Q]
    residual = float(
        np.linalg.norm(sum(terms), "fro") / (1 + sum(np.linalg.norm(x, "fro") for x in terms))
    )
    assert residual <= tolerance["rCARE_max"]
    assert (
        np.max(
            np.linalg.eigvals(
                A
                - B
                @ np.array(wasm["result"]["K"]["data"]).reshape(
                    3, 12, order=wasm["result"]["K"]["order"]
                )
            ).real
        )
        < 0
    )
    assert wasm["provenance"]["lib_versions"]
    browser_harness.record(
        "care-12x3",
        {
            "fixture": fixture["fixture_id"],
            **comparisons,
            "independent_rCARE": residual,
            "response": wasm,
        },
    )


def test_unstabilizable_plant_through_real_rpc(browser_harness):
    req = browser_harness.page.evaluate("() => request(0,'unstabilizable')")
    req["payload"] = {"A": [[1, 0], [0, -1]], "B": [[0], [1]], "Q": [[1, 0], [0, 1]], "R": [[1]]}
    result = browser_harness.rpc(req)
    assert result["status"] == "failure", result
    assert result["error"]["code"] == "HYPOTHESIS_VIOLATED"
    assert result["result"] is None
    browser_harness.record("unstabilizable-real-rpc", result)


def test_g0b_runtime_reports_unavailable_honestly(browser_harness):
    # The provisioned production Pyodide does not ship the optional SDP packages.
    # Record the actual assay outcome, never promote an educational solver.
    report = browser_harness.python("""import json, sys, importlib.util
from control_lab.optimization.verification.gate0b import run_gate_0b_assay
r = run_gate_0b_assay(track_memory=False)
json.dumps({"platform":sys.platform,"cvxpy_present":importlib.util.find_spec("cvxpy") is not None,"clarabel_present":importlib.util.find_spec("clarabel") is not None,"assay":r.to_dict()})""")
    assert report["platform"] == "emscripten"
    assert not report["assay"]["data"]["overall_passed"], report
    for backend in report["assay"]["data"]["backends"].values():
        assert not backend["passed"] and not backend["capabilities"]["available"], backend
    browser_harness.record(
        "g0b-unavailable",
        {"decision": "fail", "production_sdp_status": "SDP backend unavailable on WASM", **report},
    )
