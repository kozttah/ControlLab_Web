/** Independent F9 local Node UI probes. Controlled engine responses are not Wasm. */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { resolveEffectiveMaturity } from "../../web/app/tool_descriptor.ts";
import { DEFAULT_TOOL_DESCRIPTORS } from "../../web/features/tool_catalog.ts";
import { LqrWorkspaceController } from "../../web/features/lqr_workspace.ts";
import { buildFailureRpcResponse } from "../../web/bridge/protocol.ts";

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
