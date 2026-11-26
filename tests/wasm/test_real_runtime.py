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
    assert native['capabilities']['browser_envelope'] == {
        'max_variables': 3072,
        'fast_max_variables': 1792,
        'max_block_dimension': 96,
        'max_cone_entries': 131072,
    }
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


def test_wasm_phase9_cycle1_packed_zero_copy_transfer_and_solve(browser_harness):
    """ADR-015 Cycle 1 real Chromium + Pyodide Wasm proof: F_k_packed Transferable, 0 PyProxy leak, and UI Solve->Verify->Export."""
    import time
    from control_lab.core.tensors import tensor_to_array
    from control_lab.optimization import continuous_stabilization_lmi, solve as solve_sdp

    # 1. Build deterministic n=8 stabilization LMI (44 vars) and solve in CPython for cross-runtime parity
    n = 8
    alpha = 0.25
    A = np.diag([-1.0 - 0.15 * i for i in range(n - 1)] + [0.45]).astype(np.float64)
    for i in range(n - 1):
        A[i, i + 1] = 0.2
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    B[-2, 0] = 0.25
    prob = continuous_stabilization_lmi(A, B, alpha=alpha)
    cpython_res = solve_sdp(prob, backend="native_primal_dual")
    assert cpython_res.status in ("success", "warning"), cpython_res.error
    assert cpython_res.data["certificate_status"] == "validated_dual"
    x_cpython = tensor_to_array(cpython_res.data["x"], expected_ndim=1, dtype="float64")
    obj_cpython = float(cpython_res.data["objective"])

    base = prob.to_dict()
    js_blocks = []
    for blk, blk_dict in zip(prob.blocks, base["blocks"], strict=True):
        k_list, r_list, c_list, v_list = [], [], [], []
        for k, fk in blk.F_terms.items():
            rows, cols = np.nonzero(np.abs(fk) > 0.0)
            for r, c_col in zip(rows.tolist(), cols.tolist(), strict=True):
                k_list.append(int(k))
                r_list.append(int(r))
                c_list.append(int(c_col))
                v_list.append(float(fk[r, c_col]))
        js_blocks.append(
            {
                "name": blk_dict["name"],
                "F0": blk_dict["F0"],
                "n_vars": prob.n_vars,
                "k_idx": k_list,
                "rows": r_list,
                "cols": c_list,
                "vals": v_list,
            }
        )

    # 2. Execute real zero-copy F_k_packed (Int32Array / Float64Array Transferable) in Chromium + Pyodide Worker
    page = browser_harness.page
    page_errors = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    wasm_packed_report = page.evaluate(
        """async ({c, c0, name, blocks}) => {
            const buffersToCheck = [];
            const packedBlocks = blocks.map((b) => {
                const kArr = new Int32Array(b.k_idx);
                const rArr = new Int32Array(b.rows);
                const cArr = new Int32Array(b.cols);
                const vArr = new Float64Array(b.vals);
                buffersToCheck.push(kArr.buffer, rArr.buffer, cArr.buffer, vArr.buffer);
                return {
                    name: b.name,
                    F0: b.F0,
                    n_vars: b.n_vars,
                    F_k_packed: {
                        k_idx: kArr,
                        rows: rArr,
                        cols: cArr,
                        vals: vArr,
                    },
                };
            });
            const req = {
                api_version: '1.0',
                request_id: crypto.randomUUID(),
                project_id: 'f9-phase9-cycle1-wasm',
                project_revision: 1,
                operation: 'optimization.solve',
                payload: {
                    problem: { name, c, c0, blocks: packedBlocks },
                    backend: 'native_primal_dual',
                },
                options: {},
                timeout_policy: { hard_timeout_ms: 60000 },
            };
            const t0 = performance.now();
            const response = await app.client.execute(req, { commitOnSuccess: false });
            const solveMs = performance.now() - t0;
            const detachedCount = buffersToCheck.filter((buf) => buf.byteLength === 0).length;
            const workerStats = await app.client.getWorkerStats();
            return {
                response,
                solveMs,
                totalPackedBuffers: buffersToCheck.length,
                detachedCount,
                activeProxies: workerStats.pyproxy.activeProxies,
                workerStats,
            };
        }""",
        {
            "c": base["c"],
            "c0": base.get("c0", 0.0),
            "name": base.get("name", "f9_stab_n8"),
            "blocks": js_blocks,
        },
    )

    resp = wasm_packed_report["response"]
    assert resp["status"] in ("success", "warning"), resp
    assert resp["result"]["backend"] == "native_primal_dual"
    assert resp["result"]["certificate_status"] == "validated_dual"
    assert resp["result"]["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
    assert wasm_packed_report["totalPackedBuffers"] > 0
    assert wasm_packed_report["detachedCount"] == wasm_packed_report["totalPackedBuffers"], (
        f"Expected all F_k_packed ArrayBuffers transferred zero-copy (detached), "
        f"got {wasm_packed_report['detachedCount']}/{wasm_packed_report['totalPackedBuffers']}"
    )
    assert wasm_packed_report["activeProxies"] == 0, wasm_packed_report["workerStats"]

    x_wasm = tensor_to_array(resp["result"]["x"], expected_ndim=1, dtype="float64")
    obj_wasm = float(resp["result"]["objective"])
    max_x_diff = float(np.max(np.abs(x_wasm - x_cpython)))
    obj_diff = abs(obj_wasm - obj_cpython)
    assert max_x_diff < 1e-8, f"CPython vs Pyodide x parity mismatch: {max_x_diff}"
    assert obj_diff < 1e-8, f"CPython vs Pyodide objective parity mismatch: {obj_diff}"

    # 3. Real browser UI flow: Solve -> Verify -> Export CVXPY without any detached ArrayBuffer error
    page.locator('button[data-tab-id="optimization_lmi"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'optimization_lmi'")

    t_ui_solve_0 = time.perf_counter()
    page.locator('[data-action="lmi-solve"]').click()
    page.locator("#lmi-spectrum-chart-slot svg").wait_for(state="visible", timeout=60000)
    page.wait_for_function(
        "() => (document.querySelector('#lmi-certificate-panel')?.textContent || '').includes('validated_dual')",
        timeout=30000,
    )
    ui_solve_ms = (time.perf_counter() - t_ui_solve_0) * 1000.0
    stats_after_solve = page.evaluate("() => app.client.getWorkerStats()")
    assert stats_after_solve["pyproxy"]["activeProxies"] == 0, stats_after_solve

    t_ui_verify_0 = time.perf_counter()
    page.locator('[data-action="lmi-verify"]').click()
    page.wait_for_function(
        """() => {
            const polite = document.querySelector('#controllab-live-polite')?.textContent || '';
            return polite.includes('Auditoria independente concluída') && polite.includes('validated_dual');
        }""",
        timeout=30000,
    )
    ui_verify_ms = (time.perf_counter() - t_ui_verify_0) * 1000.0
    stats_after_verify = page.evaluate("() => app.client.getWorkerStats()")
    assert stats_after_verify["pyproxy"]["activeProxies"] == 0, stats_after_verify

    page.locator('[data-action="lmi-export-cvxpy"]').click()
    export_modal = page.locator("#export-modal-content")
    export_modal.wait_for(state="visible", timeout=30000)
    cvxpy_text = export_modal.inner_text()
    assert "import cvxpy" in cvxpy_text, cvxpy_text[:200]
    compile(cvxpy_text, "<ui cvxpy export>", "exec")
    page.locator("#export-modal-close").click()
    page.locator("#export-modal-content").wait_for(state="hidden")

    stats_after_export = page.evaluate("() => app.client.getWorkerStats()")
    assert stats_after_export["pyproxy"]["activeProxies"] == 0, stats_after_export

    alert_texts = [t.strip() for t in page.locator('[role="alert"]').all_inner_texts() if t.strip()]
    assert not alert_texts, f"Unexpected UI error alerts: {alert_texts}"
    assert not page_errors, f"Unexpected browser page errors: {page_errors}"

    evidence = {
        "n_states": n,
        "n_vars": prob.n_vars,
        "wasm_packed_solve_ms": round(float(wasm_packed_report["solveMs"]), 2),
        "ui_solve_ms": round(ui_solve_ms, 2),
        "ui_verify_ms": round(ui_verify_ms, 2),
        "total_packed_buffers": wasm_packed_report["totalPackedBuffers"],
        "detached_buffers": wasm_packed_report["detachedCount"],
        "active_proxies_after_packed_solve": wasm_packed_report["activeProxies"],
        "active_proxies_after_ui_export": stats_after_export["pyproxy"]["activeProxies"],
        "max_x_diff_cpython_vs_wasm": max_x_diff,
        "objective_diff_cpython_vs_wasm": obj_diff,
        "certificate_status": resp["result"]["certificate_status"],
        "audit_feasibility": resp["result"]["audit_feasibility"],
        "ui_solve_verify_export_cvxpy_passed": True,
    }
    print(f"[F9-WASM-CYCLE1] {json.dumps(evidence)}")
    browser_harness.record("phase9-cycle1-packed-wasm", evidence)


def test_wasm_phase9_05c_envelope_3072_and_n48_stabilization(browser_harness):
    """WP-PHASE9-05C real Chromium + Pyodide Wasm proof: 1792/3072 envelope, n=48 (1224 vars) solve <5s, and 3073 RESOURCE_LIMIT."""
    from control_lab.optimization import continuous_stabilization_lmi, solve as solve_sdp

    expected_envelope = {
        "fast_max_variables": 1792,
        "max_variables": 3072,
        "max_block_dimension": 96,
        "max_cone_entries": 131072,
    }

    # 1. Build deterministic n=48 stabilization LMI (1224 vars > legacy 1024 cap) and solve in CPython for parity
    n = 48
    alpha = 0.20
    A = np.diag([-1.0 - 0.08 * i for i in range(n - 1)] + [0.45]).astype(np.float64)
    for i in range(n - 1):
        A[i, i + 1] = 0.15
    B = np.zeros((n, 1), dtype=np.float64)
    B[-1, 0] = 1.0
    B[-2, 0] = 0.20
    prob_48 = continuous_stabilization_lmi(A, B, alpha=alpha)
    assert prob_48.n_vars == 1224

    cpython_res = solve_sdp(prob_48, backend="native_primal_dual")
    assert cpython_res.status in ("success", "warning"), cpython_res.error
    assert cpython_res.data["certificate_status"] == "validated_dual"
    obj_cpython = float(cpython_res.data["objective"])

    base = prob_48.to_dict()
    js_blocks = []
    for blk, blk_dict in zip(prob_48.blocks, base["blocks"], strict=True):
        k_list, r_list, c_list, v_list = [], [], [], []
        for k, fk in blk.F_terms.items():
            rows, cols = np.nonzero(np.abs(fk) > 0.0)
            for r, c_col in zip(rows.tolist(), cols.tolist(), strict=True):
                k_list.append(int(k))
                r_list.append(int(r))
                c_list.append(int(c_col))
                v_list.append(float(fk[r, c_col]))
        js_blocks.append(
            {
                "name": blk_dict["name"],
                "F0": blk_dict["F0"],
                "n_vars": prob_48.n_vars,
                "k_idx": k_list,
                "rows": r_list,
                "cols": c_list,
                "vals": v_list,
            }
        )

    page = browser_harness.page
    wasm_report = page.evaluate(
        """async ({c, c0, name, blocks}) => {
            const capReq = {
                api_version: '1.0',
                request_id: crypto.randomUUID(),
                project_id: 'f9-phase9-05c-wasm',
                project_revision: 1,
                operation: 'optimization.capabilities',
                payload: { backend: 'native_primal_dual' },
                options: {},
                timeout_policy: { hard_timeout_ms: 30000 },
            };
            const capResp = await app.client.execute(capReq, { commitOnSuccess: false });

            const packedBlocks = blocks.map((b) => ({
                name: b.name,
                F0: b.F0,
                n_vars: b.n_vars,
                F_k_packed: {
                    k_idx: new Int32Array(b.k_idx),
                    rows: new Int32Array(b.rows),
                    cols: new Int32Array(b.cols),
                    vals: new Float64Array(b.vals),
                },
            }));
            const solveReq = {
                api_version: '1.0',
                request_id: crypto.randomUUID(),
                project_id: 'f9-phase9-05c-wasm',
                project_revision: 1,
                operation: 'optimization.solve',
                payload: {
                    problem: { name, c, c0, blocks: packedBlocks },
                    backend: 'native_primal_dual',
                },
                options: {},
                timeout_policy: { hard_timeout_ms: 60000 },
            };
            const t0 = performance.now();
            const solveResp = await app.client.execute(solveReq, { commitOnSuccess: false });
            const solveMs = performance.now() - t0;

            const overReq = {
                api_version: '1.0',
                request_id: crypto.randomUUID(),
                project_id: 'f9-phase9-05c-wasm',
                project_revision: 1,
                operation: 'optimization.solve',
                payload: {
                    problem: {
                        name: 'over_3072_limit',
                        c: { data: new Array(3073).fill(1.0), shape: [3073], dtype: 'float64', order: 'C' },
                        c0: 0.0,
                        blocks: [],
                    },
                    backend: 'native_primal_dual',
                },
                options: {},
                timeout_policy: { hard_timeout_ms: 30000 },
            };
            const overResp = await app.client.execute(overReq, { commitOnSuccess: false });
            const workerStats = await app.client.getWorkerStats();
            return { capResp, solveResp, solveMs, overResp, workerStats };
        }""",
        {
            "c": base["c"],
            "c0": base.get("c0", 0.0),
            "name": base.get("name", "f9_stab_n48"),
            "blocks": js_blocks,
        },
    )

    # 1) Verify capabilities reports the calibrated 1792/3072/96/131072 envelope
    cap_resp = wasm_report["capResp"]
    assert cap_resp["status"] == "success", cap_resp
    native_caps = cap_resp["result"]["capabilities"]
    assert native_caps["browser_envelope"] == expected_envelope, native_caps["browser_envelope"]

    # 2) Verify n=48 (1,224 vars > 1,024) solves in < 5s with validated_dual in real Pyodide Wasm
    solve_resp = wasm_report["solveResp"]
    solve_ms = float(wasm_report["solveMs"])
    assert solve_resp["status"] in ("success", "warning"), solve_resp
    assert solve_resp["result"]["backend"] == "native_primal_dual"
    assert solve_resp["result"]["certificate_status"] == "validated_dual"
    assert solve_ms < 5000.0, f"Expected n=48 (1224 vars) Wasm solve < 5000ms, got {solve_ms:.2f}ms"
    obj_wasm = float(solve_resp["result"]["objective"])
    assert abs(obj_wasm - obj_cpython) < 1e-6, f"Wasm ({obj_wasm}) vs CPython ({obj_cpython})"

    # 3) Verify exceeding max_variables=3072 (3073 vars) returns RESOURCE_LIMIT with CVXPY/YALMIP guidance
    over_resp = wasm_report["overResp"]
    assert over_resp["status"] == "failure", over_resp
    assert over_resp["error"]["code"] == "RESOURCE_LIMIT", over_resp["error"]
    assert "CVXPY" in over_resp["error"]["message"] and "YALMIP" in over_resp["error"]["message"]
    assert over_resp["diagnostics"]["offline_recommended"] is True
    assert wasm_report["workerStats"]["pyproxy"]["activeProxies"] == 0, wasm_report["workerStats"]

    evidence_05c = {
        "n_states": n,
        "n_vars": prob_48.n_vars,
        "browser_envelope": native_caps["browser_envelope"],
        "wasm_n48_solve_ms": round(solve_ms, 2),
        "certificate_status": solve_resp["result"]["certificate_status"],
        "objective_diff_cpython_vs_wasm": abs(obj_wasm - obj_cpython),
        "over_3073_error_code": over_resp["error"]["code"],
        "active_proxies": wasm_report["workerStats"]["pyproxy"]["activeProxies"],
    }
    print(f"[F9-WASM-05C] {json.dumps(evidence_05c)}")
    browser_harness.record("phase9-05c-envelope-3072-wasm", evidence_05c)


def test_wasm_phase10_ts_modeling_three_pathways_and_script_export(browser_harness):
    """WP-TSMOD-05 real Chromium + Pyodide Wasm proof: Sector (16 rules), TPMT v1.3.0, FEMT v1.2.0 & script export."""
    from control_lab.core.models import TSStateSpace

    z1 = "(1 / (1.0 + 0.2 * sin(x3)^2))"
    z2 = "cos(x3)"
    z3 = "sinc_rad(x3)"
    z4 = "(x4 * sin(x3))"
    state_bounds = {"x1": [-2.0, 2.0], "x2": [-3.0, 3.0], "x3": [-0.6, 0.6], "x4": [-2.0, 2.0]}
    direct_A = [
        ["0", "1", "0", "0"],
        ["0", "0", f"-1.962 * {z1} * {z2} * {z3}", f"0.1 * {z1} * {z4}"],
        ["0", "0", "0", "1"],
        ["0", "0", f"23.544 * {z1} * {z3}", f"-0.2 * {z1} * {z2} * {z4}"],
    ]
    direct_B = [["0"], [z1], ["0"], [f"-2.0 * {z1} * {z2}"]]
    direct_C = [["1", "0", "0", "0"], ["0", "0", "1", "0"]]
    direct_D = [["0"], ["0"]]

    def _make_req(operation: str, payload: dict) -> dict:
        return {
            "api_version": "1.0",
            "request_id": f"f9-wasm-tsmod-{operation.replace('.', '-')}",
            "project_id": "f9-phase10-tsmod-wasm",
            "project_revision": 1,
            "operation": operation,
            "payload": payload,
            "options": {},
            "timeout_policy": {"hard_timeout_ms": 60000},
        }

    def _assert_24_constants_bitwise(ts_dict: dict, label: str) -> None:
        ts_obj = TSStateSpace.from_dict(ts_dict)
        expected_C = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]], dtype=np.float64)
        expected_D = np.zeros((2, 1), dtype=np.float64)
        const_A_zeros = [
            (0, 0), (0, 2), (0, 3),
            (1, 0), (1, 1),
            (2, 0), (2, 1), (2, 2),
            (3, 0), (3, 1),
        ]
        for r_idx, v in enumerate(ts_obj.vertices):
            A_r = np.asarray(v["A"], dtype=np.float64)
            B_r = np.asarray(v["B"], dtype=np.float64)
            C_r = np.asarray(v["C"], dtype=np.float64)
            D_r = np.asarray(v["D"], dtype=np.float64)
            assert A_r[0, 1] == 1.0 and A_r[2, 3] == 1.0, f"{label} rule {r_idx} integrator drifted"
            for i, j in const_A_zeros:
                assert A_r[i, j] == 0.0, f"{label} rule {r_idx} A[{i},{j}]={A_r[i, j]}"
            assert B_r[0, 0] == 0.0 and B_r[2, 0] == 0.0, f"{label} rule {r_idx} B const drifted"
            assert np.array_equal(C_r, expected_C), f"{label} rule {r_idx} C drifted"
            assert np.array_equal(D_r, expected_D), f"{label} rule {r_idx} D drifted"

    # 1. Sector Nonlinearity (16 rules on 4-state inverted pendulum) in real Pyodide Wasm
    sector_resp = browser_harness.rpc(
        _make_req(
            "fuzzy.derive_ts_sector",
            {
                "premises": [
                    {"name": "z1", "expression": "1 / (1.0 + 0.2 * sin(x3)^2)", "measured": True},
                    {"name": "z2", "expression": "cos(x3)", "measured": True},
                    {"name": "z3", "expression": "sinc_rad(x3)", "measured": True},
                    {"name": "z4", "expression": "x4 * sin(x3)", "measured": True},
                ],
                "state_bounds": state_bounds,
                "A_expr": [
                    ["0", "1", "0", "0"],
                    ["0", "0", "-1.962 * z1 * z2 * z3", "0.1 * z1 * z4"],
                    ["0", "0", "0", "1"],
                    ["0", "0", "23.544 * z1 * z3", "-0.2 * z1 * z2 * z4"],
                ],
                "B_expr": [["0"], ["z1"], ["0"], ["-2.0 * z1 * z2"]],
                "C_expr": direct_C,
                "D_expr": direct_D,
                "n_val_points": 64,
            },
        )
    )
    assert sector_resp["status"] == "success", sector_resp
    assert sector_resp["result"]["num_rules"] == 16
    sector_val_err = float(sector_resp["result"]["fidelity_certificate"]["max_abs_error"])
    assert sector_val_err < 1e-12, f"Sector Wasm error too high: {sector_val_err}"
    _assert_24_constants_bitwise(sector_resp["result"]["ts_state_space"], "wasm-sector")

    # 2. TPMT v1.3.0 (modal centering, rank_augmented == [False, False], bitwise constants)
    tpmt_resp = browser_harness.rpc(
        _make_req(
            "fuzzy.derive_ts_tpmt",
            {
                "state_bounds": state_bounds,
                "A_expr": direct_A,
                "B_expr": direct_B,
                "C_expr": direct_C,
                "D_expr": direct_D,
                "grid_points": 9,
                "ranks": [2, 2],
                "hull_type": "CNO",
                "n_val_points": 32,
            },
        )
    )
    assert tpmt_resp["status"] in ("success", "warning"), tpmt_resp
    assert tpmt_resp["result"]["num_rules"] == 4
    tpmt_aug = [ax["rank_augmented"] for ax in tpmt_resp["result"]["hull_diagnostics"]]
    assert tpmt_aug == [False, False], tpmt_resp["result"]["hull_diagnostics"]
    _assert_24_constants_bitwise(tpmt_resp["result"]["ts_state_space"], "wasm-tpmt")

    # 3. FEMT v1.2.0 (varying subspace, rank_augmented == False, bitwise constants, kuhn_delaunay)
    femt_resp = browser_harness.rpc(
        _make_req(
            "fuzzy.derive_ts_femt",
            {
                "state_bounds": state_bounds,
                "A_expr": direct_A,
                "B_expr": direct_B,
                "C_expr": direct_C,
                "D_expr": direct_D,
                "grid_points": 9,
                "hull_type": "CNO",
                "mesh_kind": "kuhn_delaunay",
                "n_val_points": 32,
            },
        )
    )
    assert femt_resp["status"] in ("success", "warning"), femt_resp
    assert femt_resp["result"]["mesh_kind"] == "kuhn_delaunay"
    assert femt_resp["result"]["hull_diagnostics"]["rank_augmented"] is False
    assert femt_resp["result"]["hull_diagnostics"]["fallback_used"] is False
    _assert_24_constants_bitwise(femt_resp["result"]["ts_state_space"], "wasm-femt")

    # 4. Export offline Python derivation script through real Wasm RPC
    export_resp = browser_harness.rpc(
        _make_req(
            "fuzzy.export_ts_derivation_script",
            {
                "model": femt_resp["result"]["ts_state_space"],
                "language": "python",
            },
        )
    )
    assert export_resp["status"] == "success", export_resp
    assert export_resp["result"]["language"] == "python"
    assert export_resp["result"]["code_executed"] is False
    compile(export_resp["result"]["script"], "<wasm ts derivation script>", "exec")

    worker_stats = browser_harness.page.evaluate("() => app.client.getWorkerStats()")
    assert worker_stats["pyproxy"]["activeProxies"] == 0, worker_stats

    evidence_tsmod = {
        "sector_rules": sector_resp["result"]["num_rules"],
        "sector_val_max_error": sector_val_err,
        "tpmt_rules": tpmt_resp["result"]["num_rules"],
        "tpmt_rank_augmented": tpmt_aug,
        "femt_rules": femt_resp["result"]["num_rules"],
        "femt_mesh_kind": femt_resp["result"]["mesh_kind"],
        "femt_rank_augmented": femt_resp["result"]["hull_diagnostics"]["rank_augmented"],
        "export_script_compiled": True,
        "active_proxies": worker_stats["pyproxy"]["activeProxies"],
    }
    print(f"[F9-WASM-PHASE10-TSMOD] {json.dumps(evidence_tsmod)}")
    browser_harness.record("phase10-ts-modeling-wasm", evidence_tsmod)



