/**
 * Independent F9 audit probes for WP-AUDIT-FIX-F7-RPC-BRIDGE.
 * Scope: Node runtime/bridge logic + real CPython scientific dispatcher.
 * The proxy adapter below is a transport test double, NOT Pyodide or a browser.
 * Expected mathematical values/tolerances come only from frozen B-CARE-02.
 * Run: node --test tests/oracles/rpc_bridge_cpython.test.mjs
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { PyodideWorkerRuntime } from "../../web/worker/pyodide_worker.ts";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const fixture = JSON.parse(fs.readFileSync(new URL("../../contracts/fixtures/B-CARE-02.json", import.meta.url), "utf8"));
const plantTemplate = JSON.parse(fs.readFileSync(new URL("../../contracts/examples/statespace_example.json", import.meta.url), "utf8"));
const PYTHON_DISPATCH = String.raw`
import json,sys
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
from control_lab.core.rpc import dispatch
schemas={p.name:json.loads(p.read_text()) for p in Path('contracts/schemas').glob('*.schema.json')}
registry=Registry()
for name,schema in schemas.items():
    resource=Resource.from_contents(schema)
    registry=registry.with_resource(name,resource).with_resource(schema['$id'],resource)
data=json.load(sys.stdin)
request=data.get('request',data)
Draft202012Validator(schemas['rpc_request.schema.json'],registry=registry).validate(request)
response=dispatch(data)
Draft202012Validator(schemas['rpc_response.schema.json'],registry=registry).validate(response)
json.dump(response,sys.stdout,allow_nan=False)
`;

function dispatchInCPython(value) {
  const run = spawnSync(process.env.CONTROLLAB_AUDIT_PYTHON ?? "python3", ["-c", PYTHON_DISPATCH], {
    cwd: ROOT, input: JSON.stringify(value), encoding: "utf8", timeout: 30000,
  });
  assert.equal(run.status, 0, `CPython dispatcher/schema failed: ${run.stderr || run.error}`);
  return JSON.parse(run.stdout);
}

function proxy(value) {
  let destroyed = false;
  return {
    __isPyProxy: true,
    toJs() { assert.equal(destroyed, false); return value; },
    destroy() { assert.equal(destroyed, false); destroyed = true; },
  };
}

async function createAuditedRuntime() {
  const messages = [];
  const runtime = new PyodideWorkerRuntime({
    // Explicit CPython adapter: no claim of Wasm, Pyodide, real Worker or IndexedDB.
    pyodideLoader: async () => ({
      pyodide: {
        runPythonAsync: async () => { throw new Error("Audit adapter must never execute generated Python source"); },
        toPy: proxy,
        pyimport(name) {
          assert.equal(name, "control_lab.core.rpc");
          return { dispatch(input) { return proxy(dispatchInCPython(input.toJs())); }, destroy() {} };
        },
      },
      libVersions: {},
    }),
    postMessage(message) { messages.push(message); },
  });
  await runtime.handleMessage({ kind: "init", msg_id: "f9-init", config: {} });
  const initialized = messages.find((m) => m.kind === "init_ok");
  assert.ok(initialized, JSON.stringify(messages));
  assert.equal(initialized.capabilities.offline_ready, false);
  assert.notEqual(initialized.capabilities.backends.numpy_scipy.maturity, "stable");
  assert.equal(initialized.capabilities.lib_versions.pyodide, undefined);
  assert.ok(initialized.capabilities.lib_versions.numpy);
  assert.ok(initialized.capabilities.lib_versions.scipy);
  assert.equal(runtime.getDiagnosticsStats().pyproxy.activeProxies, 0);
  return { runtime, messages };
}

function makeRequest(plant, requestId) {
  return {
    api_version: "1.0", request_id: requestId, project_id: "f9-independent", project_revision: 1,
    operation: "statespace.design_lqr",
    payload: {
      plant_ref: { id: plant.id, revision: plant.revision },
      Q: structuredClone(fixture.data.Q), R: structuredClone(fixture.data.R),
      x0: structuredClone(fixture.data.x0), feedback_sign: "negative",
    },
    options: {}, timeout_policy: { hard_timeout_ms: 30000 },
  };
}

function analyticalPlant() {
  const plant = structuredClone(plantTemplate);
  plant.id = "f9-analytical-plant";
  plant.matrices = Object.fromEntries(["A", "B", "C", "D"].map((key) => [key, structuredClone(fixture.data[key])]));
  return plant;
}

async function executeViaRegisteredReference(plant, requestId) {
  const { runtime, messages } = await createAuditedRuntime();
  await runtime.handleMessage({
    kind: "register_object", msg_id: "f9-register", project_id: "f9-independent",
    object_id: plant.id, revision: plant.revision, value: plant, object_kind: "StateSpace",
  });
  await runtime.handleMessage({ kind: "rpc_request", request: makeRequest(plant, requestId) });
  const response = messages.find((m) => m.kind === "rpc_response" && m.response.request_id === requestId)?.response;
  assert.ok(response, JSON.stringify(messages));
  assert.equal(runtime.getDiagnosticsStats().pyproxy.activeProxies, 0);
  return response;
}

test("F9 independent: registered-reference bridge calls real CPython and matches frozen analytic CARE fixture", async () => {
  const result = await executeViaRegisteredReference(analyticalPlant(), "f9-analytic-care");
  assert.equal(result.status, "success");
  assert.equal(result.error, null);
  const expected = fixture.data.expected;
  for (const [key, tolerance] of [["P", fixture.tolerances.P_atol], ["K", fixture.tolerances.K_atol]]) {
    const actual = result.result[key]?.data ?? result.result[`${key}_lqr`]?.data;
    assert.ok(actual, `Missing ${key} in ${JSON.stringify(result.result)}`);
    assert.equal(actual.length, expected[key].data.length);
    actual.forEach((value, i) => assert.ok(Math.abs(value - expected[key].data[i]) <= tolerance, `${key}[${i}] violates frozen tolerance`));
  }
  assert.match(result.provenance.algorithm, /scipy\.linalg\.solve_continuous_are/);
});

test("F9 independent: unstabilizable plant through real CPython RPC never produces a controller", async () => {
  const plant = analyticalPlant();
  plant.id = "f9-unstabilizable";
  plant.matrices.A.data = [1, 0, 0, 2];
  plant.matrices.B.data = [0, 0];
  const result = await executeViaRegisteredReference(plant, "f9-unstabilizable-care");
  assert.equal(result.status, "failure");
  assert.equal(result.error.code, "HYPOTHESIS_VIOLATED");
  assert.equal(result.result, null);
  assert.ok(result.provenance.algorithm);
  assert.ok(result.diagnostics);
});
