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


def test_g0b_native_runtime_and_offline_scripts(browser_harness):
    report = browser_harness.python("""import json, sys, ast
import numpy as np
from control_lab.optimization import solve, export_to_cvxpy_script, export_to_yalmip_script, CanonicalSDPProblem, SDPBlock
from control_lab.optimization.backends.native import BROWSER_ENVELOPE
from control_lab.optimization.verification.gate0b import run_gate_0b_assay, _build_gate_0b_suite
assay = run_gate_0b_assay(track_memory=False)
suite = _build_gate_0b_suite()
auto_lp = solve(suite['LP_A1']['problem'])
auto_psd = solve(suite['PSD_2x2_B1']['problem'])
scaled = CanonicalSDPProblem(c=[1.], blocks=[SDPBlock('scaled',np.diag([-1.,1e-8]),[np.diag([1.,0.])])])
large = CanonicalSDPProblem(c=np.ones(BROWSER_ENVELOPE['max_variables'] + 1))
exports = []
for problem in (scaled, large):
    solution = solve(problem, backend='native_primal_dual')
    py = export_to_cvxpy_script(problem)
    compile(py, '<offline export>', 'exec')
    matlab = export_to_yalmip_script(problem)
    exports.append({'offline_recommended':solution.diagnostics['offline_recommended'],
                    'python_syntax':True,'yalmip_syntax':all(t in matlab for t in ('sdpvar(', 'sdpsettings(', 'optimize(', 'check('))})
json.dumps({'platform':sys.platform,'assay':assay.to_dict(),'exports':exports, 'auto_lp':auto_lp.to_dict(), 'auto_psd':auto_psd.to_dict()})""")
    assert report['platform'] == 'emscripten'
    assert report['auto_lp']['data']['backend'] == 'scipy_linprog'
    assert report['auto_psd']['data']['backend'] == 'native_primal_dual'
    assert report['auto_psd']['data']['certificate_status'] == 'validated_dual'
    assert report['assay']['data']['overall_passed'], report
    native = report['assay']['data']['backends']['native_primal_dual']
    assert native['capabilities']['psd'] and not native['capabilities']['experimental']
    assert all(c['passed'] for c in native['cases'].values())
    assert all(e['offline_recommended'] and e['python_syntax'] and e['yalmip_syntax'] for e in report['exports'])
    browser_harness.record('g0b-native-adr010',report)


def test_offline_scripts_download_without_committed_solution(browser_harness, tmp_path):
    page = browser_harness.page
    page.locator('[data-tab-id="optimization_lmi"]').click()
    page.locator('[data-action="execute-tool"][data-tool-id="optimization.solve"]').click()
    page.wait_for_function("""() => app.shell.getTabsController().getTabViewModel('optimization_lmi')
        .lastExecutionByTool['optimization.solve'] !== undefined""")
    solved = page.evaluate("""() => app.shell.getTabsController().getTabViewModel('optimization_lmi')
        .lastExecutionByTool['optimization.solve'].response""")
    assert solved['status'] in ('success','warning'), solved
    assert solved['result']['backend'] == 'native_primal_dual'
    assert solved['result']['certificate_status'] == 'validated_dual'
    page.locator('#export-modal-close').click()
    for kind, extension in [('cvxpy','.py'), ('yalmip','.m')]:
        page.locator(f'[data-action="export-sdp"][data-format="{kind}"]').click()
        with page.expect_download() as event:
            page.locator('#export-modal-download').click()
        assert event.value.suggested_filename.endswith(extension)
        path = tmp_path / event.value.suggested_filename
        event.value.save_as(path)
        text = path.read_text()
        if kind == 'cvxpy':
            import ast
            compile(text,'<downloaded CVXPY script>','exec')
            tree = ast.parse(text)
            data_node = next(node for node in tree.body if isinstance(node, ast.Assign)
                             and any(isinstance(t, ast.Name) and t.id == 'DATA' for t in node.targets))
            payload = json.loads(ast.literal_eval(data_node.value.args[0]))
            plant = page.evaluate("() => app.shell.getLqrWorkspace().getPlant()")
            assert payload['recovery']['A'] == plant['matrices']['A']
        else:
            assert 'optimize(' in text and 'value(M) / value(P)' in text
        page.locator('#export-modal-close').click()
