/** Independent F9 local Node UI probes. Controlled engine responses are not Wasm. */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { resolveEffectiveMaturity } from "../../web/app/tool_descriptor.ts";
import { DEFAULT_TOOL_DESCRIPTORS } from "../../web/features/tool_catalog.ts";
import { LqrWorkspaceController } from "../../web/features/lqr_workspace.ts";
import { buildFailureRpcResponse } from "../../web/bridge/protocol.ts";
import { MockWorkerAdapter } from "../../web/bridge/mock_adapter.ts";
import { IndexedDBProjectStore, InMemoryIDBFactory } from "../../web/storage/indexeddb_store.ts";
import { resolveBrowserRuntimeAssets, registerControlLabServiceWorker } from "../../web/app/main.ts";

const descriptor = {
  id: "f9_probe", title: "F9 probe", description: "Independent capability probe",
  tab: "statespace", input_types: [], parameter_schema: [],
  operation: "statespace.f9_unimplemented", output_types: [], visualizations: [],
  requirements: [], interaction_mode: "batch_async", maturity: "beta",
  limits: {}, examples: [], default_indicator: "numeric_verified",
};
function capabilities(operations = [], maturity = {}) {
  return {api_version: "1.0", engine_kind: "pyodide", runtime_id: "f9-unit",
    operations, maturity, backends: {}, supports_transferables: true,
    supports_cooperative_cancel: false, offline_ready: false,
    max_memory_bytes: 1024, lib_versions: {test: "controlled-unit"}};
}

test("F9: unlisted operations stay unavailable despite catalog/runtime maturity", () => {
  for (const maturity of ["stable", "beta", "experimental"]) {
    const cap = capabilities([], {[descriptor.operation]: maturity});
    assert.equal(resolveEffectiveMaturity({...descriptor, maturity}, cap).available, false);
  }
});

test("F9: required backend must be explicitly available", () => {
  const cap = capabilities([descriptor.operation], {[descriptor.operation]: "beta"});
  const tool = {...descriptor, required_backend: "f9_missing_backend"};
  assert.equal(resolveEffectiveMaturity(tool, cap).available, false);
  cap.backends.f9_missing_backend = {available: false, maturity: "unavailable_wasm"};
  assert.equal(resolveEffectiveMaturity(tool, cap).available, false);
});

test("F9: browser catalog does not claim stable before Wasm gates", () => {
  assert.ok(DEFAULT_TOOL_DESCRIPTORS.length > 0);
  assert.ok(DEFAULT_TOOL_DESCRIPTORS.every(tool => tool.maturity !== "stable"));
});

for (const status of ["failure", "inconclusive"]) {
  test(`F9: preview/pending/${status} never authorize export or persistence`, async () => {
    const registrations = [], requests = [];
    let reply;
    const client = {
      registerObject: async (...args) => {registrations.push(args);},
      execute: request => {requests.push(request); return new Promise(resolve => {reply = resolve;});},
      getCapabilities: () => capabilities(["statespace.design_lqr"], {"statespace.design_lqr": "beta"}),
      getLifecycleState: () => "ready",
      getCommittedRevision: () => 0,
      subscribe: () => () => {},
      cancel: async () => {},
      dispose: () => {},
    };
    const workspace = new LqrWorkspaceController({client, project_id: `f9-${status}`});
    workspace.pointerDown("f9-drag");
    for (let i = 1; i <= 30; i++) workspace.pointerMove({qScale: 1 + i / 10});
    assert.equal(requests.length, 0);
    assert.equal(registrations.length, 0);
    assert.equal(workspace.getCommittedSnapshot(), null);
    assert.equal(workspace.canExport().allowed, false);
    const pending = workspace.pointerUp({computeTimeResponse: false});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(workspace.isPendingCommit(), true);
    assert.equal(workspace.canExport().allowed, false);
    assert.equal(requests.length, 1);
    const request = requests[0];
    let response = buildFailureRpcResponse({
      request_id: request.request_id, project_id: request.project_id,
      project_revision: request.project_revision, code: "NUMERICAL_INCONCLUSIVE",
      message: "F9 controlled response; no scientific result",
      lib_versions: {test: "controlled-unit"}, diagnostics: {committed: false},
    });
    if (status === "inconclusive") response = {...response, status, error: null, result: {}};
    reply(response);
    assert.equal(await pending, null);
    assert.equal(workspace.getCommittedSnapshot(), null);
    assert.equal(workspace.canExport().allowed, false);
    assert.ok(registrations.every(args => args[4].persistToIndexedDB === false));
  });
}

test("F9: root HTML entry uses distributable JS and matching stylesheet location", () => {
  const html = fs.readFileSync(new URL("../../web/app/index.html", import.meta.url), "utf8");
  const script = /<script[^>]+src="([^"]+)"/.exec(html)?.[1];
  const stylesheet = /<link[^>]+href="([^"]+)"/.exec(html)?.[1];
  assert.ok(script?.endsWith("/app/main.js"));
  assert.ok(stylesheet?.endsWith("/app/styles.css"));
  assert.ok(!html.includes('src="/app/main.ts"'));
});

test("F9: root and GitHub-prefix runtime URLs preserve module scope", async () => {
  for (const prefix of ["/", "/ControlLab_Web/"]) {
    const base = `https://example.github.io${prefix}`;
    const assets = resolveBrowserRuntimeAssets(`${base}app/main.js`);
    assert.equal(assets.workerUrl, `${base}worker/pyodide_worker.js`);
    assert.equal(assets.serviceWorkerUrl, `${base}service_worker.js`);
    assert.equal(assets.serviceWorkerScope, base);
    assert.equal(assets.pyodideIndexUrl, `${base}pyodide/`);
    assert.equal(assets.controlLabWheel, `${base}wheels/control_lab-1.0.0-py3-none-any.whl`);
    const registrations = [];
    await registerControlLabServiceWorker({ register: async (...args) => { registrations.push(args); return {}; } }, assets);
    assert.deepEqual(registrations, [[assets.serviceWorkerUrl, {
      type: "module", scope: base, updateViaCache: "none",
    }]]);
  }
});

// Exercise the production F7 commit coordinator and storage implementation.
// Only the scientific response is controlled; no Wasm/real-browser claim.
for (const status of ["failure", "inconclusive", "success", "invalid_success"]) {
  test(`F9: real F7 storage/export observes preview, pending and ${status}`, async () => {
    const store = new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() });
    const fixture = JSON.parse(fs.readFileSync(new URL("../../contracts/fixtures/B-CARE-02.json", import.meta.url), "utf8"));
    let complete;
    let dispatched = 0;
    class ControlledAdapter extends MockWorkerAdapter {
      async dispatchRpc(request) {
        dispatched++;
        return new Promise(resolve => { complete = () => resolve({ response: {
          api_version: "1.0", request_id: request.request_id, project_id: request.project_id,
          project_revision: request.project_revision, status: status === "invalid_success" ? "success" : status,
          result: status === "failure" ? null : {
            ...structuredClone(fixture.data.expected),
            ...(status === "invalid_success" ? { K: { shape: [1, 1], dtype: "float64", order: "C", data: [2] } } : {}),
            controller_ref: { id: "f9-controlled-controller", revision: request.project_revision },
            controller_kind: "StateFeedbackController", feedback_sign: "negative",
          },
          assumptions: {}, diagnostics: { f9_controlled_response: true },
          provenance: { algorithm: "f9_controlled_fixture_transport", lib_versions: { test_double: "1" }, model_revision: 1 },
          warnings: [], error: status === "failure" ? { code: "INTERNAL_ERROR", message: "F9 controlled failure" } : null,
        } }); });
      }
    }
    const client = new ControlledAdapter({ store, latencyMs: 0 });
    await client.init();
    const projectId = `f9-storage-${status}`;
    const workspace = new LqrWorkspaceController({client, project_id: projectId});
    async function assertUncommitted() {
      assert.equal(await store.getProject(projectId), null);
      assert.equal(await store.getLatestConfirmedSnapshot(projectId), null);
      assert.equal((await store.listObjects(projectId)).length, 0);
      assert.equal((await store.listExperiments(projectId)).length, 0);
      assert.equal((await client.exportProject(projectId)).committed_result, null);
      assert.equal(workspace.canExport().allowed, false);
    }
    try {
      workspace.pointerDown("f9-storage-drag");
      for (let i = 1; i <= 30; i++) workspace.pointerMove({ qScale: 1 + i / 10 });
      assert.equal(dispatched, 0);
      await assertUncommitted();
      const pending = workspace.pointerUp({ computeTimeResponse: false });
      for (let i = 0; i < 20 && !complete; i++) await new Promise(resolve => setImmediate(resolve));
      assert.equal(dispatched, 1);
      assert.equal(workspace.isPendingCommit(), true);
      await assertUncommitted();
      complete();
      const result = await pending;
      if (status === "success") {
        assert.ok(result);
        assert.equal(workspace.canExport().allowed, true);
        const stored = await store.getProject(projectId);
        assert.equal(stored.last_committed_result.status, "success");
        assert.equal(stored.committed_revision, result.project_revision);
        assert.equal((await client.exportProject(projectId)).committed_result.status, "success");
        assert.ok((await store.listObjects(projectId)).length > 0);
      } else {
        assert.equal(result, null);
        assert.equal(workspace.getCommittedSnapshot(), null);
        await assertUncommitted();
      }
    } finally { client.dispose(); }
  });
}
