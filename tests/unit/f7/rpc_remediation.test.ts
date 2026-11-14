/** AUD-001/002/010/013/014 regression evidence, local Node + CPython only. */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { PyodideEngineClient } from "../../../web/bridge/pyodide_client.ts";
import type { ControlLabEngineClient, ExecutionMetrics } from "../../../web/bridge/client.ts";
import { IndexedDBProjectStore, InMemoryIDBFactory } from "../../../web/storage/indexeddb_store.ts";
import { createMessageChannelWorkerTransport, PyodideWorkerRuntime, type PyodideInterfaceLike } from "../../../web/worker/pyodide_worker.ts";
import { type RpcRequest, type RpcResponse, validateRpcResponse } from "../../../web/bridge/protocol.ts";
import { cpythonLoader } from "./cpython_runtime.mjs";

function store(): IndexedDBProjectStore {
  return new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() });
}
function request(id = "regression", payload: Record<string, unknown> = {}): RpcRequest {
  return {
    api_version: "1.0", request_id: id, project_id: "regression-project", project_revision: 1,
    operation: "statespace.design_lqr", payload: {
      A: [[1, 0], [0, 2]], B: [[0], [0]], Q: [[1, 0], [0, 1]], R: [[1]], ...payload,
    }, options: {}, timeout_policy: { hard_timeout_ms: 30000 },
  };
}

test("test_no_python_runtime_no_scientific_success: no silent MessageChannel and no commit/provenance invented", async () => {
  const client: ControlLabEngineClient = new PyodideEngineClient({ store: store() });
  try {
    const metrics: ExecutionMetrics = client.getMetrics();
    assert.equal(metrics.T_init_pyodide, null);
    assert.equal(client.getCapabilities().offline_ready, false);
    assert.equal(client.getCapabilities().operations.includes("statespace.design_lqr"), false);
    for (const req of [request(), request("distinct", { A: [[0, 1], [-2, -3]], B: [[0], [1]] })]) {
      const response = validateRpcResponse(await client.execute(req));
      assert.equal(response.status, "failure");
      assert.equal(response.error?.code, "SOLVER_UNAVAILABLE");
      assert.equal(response.result, null);
      assert.equal(response.diagnostics.committed, false);
      assert.equal(response.provenance.algorithm, req.operation);
      assert.deepEqual(response.provenance.lib_versions, {});
      assert.equal(client.getCommittedRevision(req.project_id), -1);
    }
    const snapshot = await client.exportProject("regression-project");
    assert.equal(snapshot.committed_result, null);
  } finally { client.dispose(); }
});

test("test_no_python_runtime_no_scientific_success: explicit MessageChannel without loader fails initialization", async () => {
  const client = new PyodideEngineClient({
    store: store(), workerFactory: () => createMessageChannelWorkerTransport(),
  });
  try {
    const result = await client.execute(request());
    assert.equal(result.error?.code, "SOLVER_UNAVAILABLE");
    assert.equal(result.result, null);
    assert.equal(result.diagnostics.committed, false);
    assert.equal(client.getLifecycleState(), "error");
    assert.equal(client.getCapabilities().offline_ready, false);
    assert.equal(client.getCapabilities().maturity["statespace.design_lqr"], undefined);
  } finally { client.dispose(); }
});

test("F7-PROVISION-UNIT: local wheel is loaded before core.rpc handshake; capabilities require observed dispatcher", async () => {
  const globals = globalThis as { loadPyodide?: (config: { indexURL: string }) => Promise<PyodideInterfaceLike> };
  const saved = globals.loadPyodide;
  const calls: string[] = [];
  let moduleDestroyed = 0;
  globals.loadPyodide = async ({ indexURL }) => {
    calls.push(indexURL);
    return {
      version: "runtime-observed",
      loadPackage: async (packages) => { calls.push(...Array.isArray(packages) ? packages : [packages]); },
      runPythonAsync: async () => { throw new Error("No string evaluation"); },
      toPy: (value) => ({ __isPyProxy: true, toJs: () => value, destroy() {} }),
      pyimport: (module) => {
        calls.push(module);
        if (module === "micropip") return {
          install: { callKwargs: (urls, kwargs) => { calls.push(JSON.stringify({ urls, ...kwargs })); } },
          destroy() {},
        };
        return { dispatch: (proxy) => {
          const input = proxy.toJs?.() as { request: RpcRequest };
          return {
            api_version: "1.0", request_id: input.request.request_id,
            project_id: input.request.project_id, project_revision: input.request.project_revision,
            status: "success", result: { supported_operations: ["statespace.design_lqr"] },
            assumptions: {}, diagnostics: {}, provenance: { algorithm: "core.capabilities", lib_versions: { numpy: "observed", scipy: "observed" } }, warnings: [], error: null,
          };
        }, destroy: () => { moduleDestroyed += 1; } };
      },
    };
  };
  const messages: unknown[] = [];
  const runtime = new PyodideWorkerRuntime({ postMessage: (message) => messages.push(message) });
  try {
    await runtime.handleMessage({ kind: "init", msg_id: "provision", config: {
      indexURL: "/pyodide/", packages: ["/wheels/control_lab-1.0.0-py3-none-any.whl"],
    } });
    assert.deepEqual(calls, ["https://controllab.local/pyodide/", "micropip", "micropip", JSON.stringify({ urls: ["https://controllab.local/wheels/control_lab-1.0.0-py3-none-any.whl"], deps: false }), "control_lab.core.rpc"]);
    assert.equal((messages[0] as { kind: string }).kind, "init_ok");
    const capabilities = runtime.getCapabilities();
    assert.equal(capabilities.maturity["statespace.design_lqr"], "beta");
    assert.equal(capabilities.maturity["statespace.analyze"], undefined);
    assert.equal(capabilities.offline_ready, false);
    assert.equal((capabilities.backends.clarabel_cvxpy as { available: boolean }).available, false);
    assert.equal(capabilities.lib_versions.pyodide, "runtime-observed");
    assert.equal(moduleDestroyed, 1);
    assert.equal(runtime.pyproxyRegistry.activeProxies, 0);
  } finally {
    if (saved) globals.loadPyodide = saved; else delete globals.loadPyodide;
  }
});

test("test_unstabilizable_plant_through_real_rpc: actual CPython dispatcher through bridge returns HYPOTHESIS_VIOLATED", async () => {
  const client = new PyodideEngineClient({
    store: store(), workerFactory: () => createMessageChannelWorkerTransport({ pyodideLoader: cpythonLoader }),
  });
  try {
    const response = await client.execute(request("unstabilizable"));
    assert.equal(response.status, "failure");
    assert.equal(response.error?.code, "HYPOTHESIS_VIOLATED");
    assert.equal(response.diagnostics.committed, false);
    assert.equal(response.result, null);
    assert.equal(client.getCommittedRevision("regression-project"), -1);
    assert.ok(response.provenance.lib_versions.python);
  } finally { client.dispose(); }
});

test("F7-CPYTHON-UNIT: real dispatcher respects Q/R, x0 and revision; no fixed two-state result", async () => {
  const fixture = JSON.parse(fs.readFileSync(fileURLToPath(new URL("../../../contracts/fixtures/B-CARE-02.json", import.meta.url)), "utf8"));
  const data = fixture.data;
  const client = new PyodideEngineClient({
    store: store(), workerFactory: () => createMessageChannelWorkerTransport({ pyodideLoader: cpythonLoader }),
  });
  try {
    const payload = { A: data.A, B: data.B, Q: data.Q, R: data.R, x0: data.x0 };
    const first = await client.execute(request("baseline", payload));
    assert.equal(first.status, "success");
    const K = first.result?.K as { data: number[] };
    K.data.forEach((value, i) => assert.ok(Math.abs(value - data.expected.K.data[i]) <= fixture.tolerances.K_atol));
    assert.ok(Number(first.diagnostics.care_residual_rel) <= fixture.tolerances.rCARE_max);
    assert.ok(Math.abs(Number(first.result?.optimal_cost) - data.expected.optimal_cost) <= fixture.tolerances.cost_atol);
    const changed = await client.execute({ ...request("changed", { ...payload, Q: [[1, 0], [0, 1]], R: [[2]], x0: [[0], [1]] }), project_revision: 2 });
    assert.equal(changed.status, "success");
    assert.notDeepStrictEqual(changed.result?.K, first.result?.K);
    assert.notEqual(changed.result?.optimal_cost, first.result?.optimal_cost);
    assert.equal(client.getCommittedRevision("regression-project"), 2);
    assert.equal(client.getCapabilities().maturity["statespace.design_lqr"], "beta");
    assert.equal((await client.getWorkerStats()).pyproxy.activeProxies, 0);
  } finally { client.dispose(); }
});
