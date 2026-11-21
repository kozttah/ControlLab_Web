/** F7 transport tests; injected runtimes below are not Wasm/scientific evidence. */
import test from "node:test";
import assert from "node:assert/strict";
import { materializePayloadReferences } from "../../../web/worker/payload_references.ts";
import { WorkerModelStore } from "../../../web/worker/model_store.ts";
import { ControlLabBridgeError, type RpcRequest, type RpcResponse } from "../../../web/bridge/protocol.ts";
import { PyodideWorkerRuntime, type PyodideLoaderFn, type WorkerOutboundMessage } from "../../../web/worker/pyodide_worker.ts";
import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { IndexedDBProjectStore, InMemoryIDBFactory } from "../../../web/storage/indexeddb_store.ts";

const project = "refs-project";
function dto(id = "model", revision = 0, kind = "StateSpace"): Record<string, unknown> {
  return { id, revision, kind, schema_version: "1.0.0", provenance: { arbitrary_ref: { id: "never-look-up", revision: 999 } } };
}
function resolve(operation: string, payload: Record<string, unknown>, store: WorkerModelStore, project_id = project) {
  return materializePayloadReferences({ operation, project_id }, payload, store);
}
function rejected(run: () => unknown, code = "VALIDATION_ERROR") {
  assert.throws(run, (e: unknown) => e instanceof ControlLabBridgeError && e.code === code);
}
function populated(): WorkerModelStore {
  const store = new WorkerModelStore();
  store.put(project, "model", 0, dto());
  store.put(project, "model", 2, dto("model", 2));
  store.put(project, "train", 0, dto("train", 0, "Dataset"));
  store.put(project, "val", 1, dto("val", 1, "Dataset"));
  return store;
}

test("F7-REF model exact historical identity becomes canonical, no registry/result mutation", () => {
  const store = populated();
  const payload = { model_ref: { id: "model", revision: 0 }, target_kind: "StateSpace" };
  const before = structuredClone(payload);
  const count = store.getStats().entry_count;
  const canonical = resolve("core.reuse_model", payload, store);
  assert.deepEqual(canonical, { model: dto(), target_kind: "StateSpace" });
  assert.deepEqual(payload, before);
  assert.equal(store.getStats().entry_count, count);
  (canonical.model as Record<string, unknown>).id = "mutated-copy";
  assert.equal(store.peek(project, "model", 0)?.value.id, "model");
});

for (const kind of ["StateSpace", "TransferFunction", "IdentifiedModel", "ts_measured", "polytopic_uncertain", "ts_partially_observed"]) {
  test(`F7-REF core reusable type ${kind}`, () => {
    const store = new WorkerModelStore();
    store.put(project, "typed", 0, dto("typed", 0, kind));
    assert.deepEqual(resolve("core.reuse_model", { model_ref: { id: "typed", revision: 0 } }, store), { model: dto("typed", 0, kind) });
  });
}

for (const operation of ["identification.fit_arx", "identification.fit_oe", "identification.fit_subspace"]) {
  test(`F7-REF dataset and validation aliases: ${operation}`, () => {
    const store = populated();
    assert.deepEqual(resolve(operation, {
      dataset_ref: { id: "train", revision: 0 }, val_dataset_ref: { id: "val", revision: 1 }, na: 2,
    }, store), { dataset: dto("train", 0, "Dataset"), val_dataset: dto("val", 1, "Dataset"), na: 2 });
  });
}

test("F7-REF validate_model aliases are grouped by actual dispatcher destinations", () => {
  const store = populated();
  const canonical = resolve("identification.validate_model", {
    plant_ref: { id: "model", revision: 0 }, dataset_ref: { id: "val", revision: 1 }, train_dataset_ref: { id: "train", revision: 0 },
  }, store);
  assert.deepEqual(canonical, { model: dto(), val_dataset: dto("val", 1, "Dataset"), train_dataset: dto("train", 0, "Dataset") });
  assert.deepEqual(resolve("identification.validate_model", { plant: dto(), dataset: dto("val", 1, "Dataset") }, store), {
    model: dto(), val_dataset: dto("val", 1, "Dataset"),
  });
});

test("F7-REF rejects every ambiguous group before looking up any object", () => {
  const store = populated();
  const before = store.getStats().hits + store.getStats().misses;
  for (const [operation, payload] of [
    ["core.reuse_model", { model: null, model_ref: { id: "model", revision: 0 } }],
    ["identification.validate_model", { model: dto(), plant_ref: { id: "model", revision: 0 } }],
    ["identification.validate_model", { model_ref: { id: "model", revision: 0 }, dataset: dto("val", 1, "Dataset"), val_dataset_ref: { id: "val", revision: 1 } }],
    ["identification.validate_model", { model_ref: { id: "model", revision: 0 }, dataset_ref: { id: "val", revision: 1 }, val_dataset_ref: { id: "val", revision: 1 } }],
    ["identification.fit_arx", { dataset_ref: { id: "train", revision: 0 }, u: [[1]], y: [[1]] }],
    ["statespace.design_lqr", { plant_ref: { id: "model", revision: 0 }, A: [[1]] }],
  ] as Array<[string, Record<string, unknown>]>) rejected(() => resolve(operation, payload, store));
  assert.equal(store.getStats().hits + store.getStats().misses, before);
});

for (const ref of [null, [], { id: "", revision: 0 }, { id: " ", revision: 0 }, { id: "model", revision: -1 },
  { id: "model", revision: 0.5 }, { id: "model", revision: "0" }, { id: "model", revision: true },
  { id: "model" }, { id: "model", revision: 0, project_id: project }, { id: "model", revision: Number.MAX_SAFE_INTEGER + 1 }]) {
  test(`F7-REF malformed reference ${JSON.stringify(ref)} fails closed`, () => {
    rejected(() => resolve("core.reuse_model", { model_ref: ref }, populated()));
  });
}

test("F7-REF missing, absent historical revision and cross-project never fall back", () => {
  const store = populated();
  rejected(() => resolve("core.reuse_model", { model_ref: { id: "model", revision: 1 } }, store));
  rejected(() => resolve("core.reuse_model", { model_ref: { id: "model", revision: 0 } }, store, "another-project"));
  rejected(() => resolve("core.reuse_model", { model_ref: { id: "absent", revision: 0 } }, store));
});

test("F7-REF rejects wrong type and stored DTO identity/revision/kind impostors", () => {
  const store = populated();
  rejected(() => resolve("core.reuse_model", { model_ref: { id: "train", revision: 0 } }, store), "UNSUPPORTED_MODEL");
  rejected(() => resolve("identification.fit_arx", { dataset_ref: { id: "model", revision: 0 } }, store), "UNSUPPORTED_MODEL");
  for (const wrong of [dto("impostor"), dto("model", 1), dto("model", 0, "Dataset")]) {
    store.put(project, "model", 0, wrong, { kind: "StateSpace" });
    rejected(() => resolve("core.reuse_model", { model_ref: { id: "model", revision: 0 } }, store));
  }
});

test("F7-REF composite-key delimiter collisions cannot leak another project's object", () => {
  const store = new WorkerModelStore();
  store.put("p::x", "y", 0, dto("y"));
  rejected(() => resolve("core.reuse_model", { model_ref: { id: "x::y", revision: 0 } }, store, "p"));
});

test("F7-REF unknown/nested references are data; no recursive resolution or lookups", () => {
  const store = populated();
  const payload = { provenance: { model_ref: { id: "absent", revision: 42 } }, future_ref: { id: "absent", revision: 42 } };
  const before = store.getStats();
  assert.deepEqual(resolve("unrecognized.operation", { ...payload, model_ref: { id: "absent", revision: 42 } }, store), { ...payload, model_ref: { id: "absent", revision: 42 } });
  assert.deepEqual(resolve("core.reuse_model", { model: dto(), ...payload }, store), { model: dto(), ...payload });
  assert.equal(store.getStats().hits, before.hits);
  assert.equal(store.getStats().misses, before.misses);
});

test("F7-REF existing plant aliases preserve independent parameters and canonical export", () => {
  const store = populated();
  const Q = [[1]], R = [[1]], t = [0, 1];
  assert.deepEqual(resolve("statespace.simulate_lti", { model_ref: { id: "model", revision: 0 }, Q, R, t }, store), { plant: dto(), Q, R, t });
  assert.deepEqual(resolve("frequency.eval_response", { model_ref: { id: "model", revision: 0 }, omega: [0, 1] }, store), { plant: dto(), omega: [0, 1] });
  assert.deepEqual(resolve("io.export_pvm", { plant_ref: { id: "model", revision: 0 } }, store), { plant: dto() });
});

test("F7-REF preserves explicit legacy consumers: interconnection, fuzzy and SDP templates", () => {
  const store = populated();
  const fuzzy = dto("fuzzy", 0, "FuzzySystem");
  const ts = dto("ts", 0, "ts_measured");
  store.put(project, "fuzzy", 0, fuzzy);
  store.put(project, "ts", 0, ts);
  const controller = { kind: "StateFeedbackController" };
  assert.deepEqual(resolve("core.interconnect", { plant_ref: { id: "model", revision: 0 }, controller }, store), { plant: dto(), controller });
  assert.deepEqual(resolve("core.validate_interconnection", { plant_ref: { id: "ts", revision: 0 }, controller }, store), { plant: ts, controller });
  for (const operation of ["fuzzy.evaluate", "fuzzy.evaluate_surface", "fuzzy.export_fml"]) {
    assert.deepEqual(resolve(operation, { plant_ref: { id: "fuzzy", revision: 0 } }, store), { system: fuzzy });
    rejected(() => resolve(operation, { system: fuzzy, plant_ref: { id: "fuzzy", revision: 0 } }, store));
  }
  assert.deepEqual(resolve("optimization.solve", { template: "ts_pdc_stabilization", plant_ref: { id: "ts", revision: 0 } }, store), { template: "ts_pdc_stabilization", ts_model: ts });
  assert.deepEqual(resolve("optimization.export_yalmip", { template: "ts_pdc_stabilization", ts_model_ref: { id: "ts", revision: 0 } }, store), { template: "ts_pdc_stabilization", ts_model: ts });
  rejected(() => resolve("optimization.solve", { template: "ts_pdc_stabilization", ts_model: ts, plant_ref: { id: "ts", revision: 0 } }, store));
  assert.deepEqual(resolve("optimization.export_cvxpy", { template: "lqr_lmi", model_ref: { id: "model", revision: 0 } }, store), { template: "lqr_lmi", plant: dto() });
  rejected(() => resolve("optimization.solve", { template: "lqr_lmi", plant_ref: { id: "model", revision: 0 }, A: [[1]] }, store));
});

function request(operation: string, payload: Record<string, unknown>, id = "refs-rpc"): RpcRequest {
  return { api_version: "1.0", request_id: id, project_id: project, project_revision: 1, operation, payload, options: {}, timeout_policy: { hard_timeout_ms: 30000 } };
}

test("F7-REF Worker materializes before safe Python proxy, rejects ambiguity before dispatch, destroys proxies", async () => {
  const passed: Array<Record<string, unknown>> = [];
  const messages: WorkerOutboundMessage[] = [];
  let created = 0, destroyed = 0;
  const loader: PyodideLoaderFn = async () => ({
    libVersions: { transport_test_double: "1" },
    pyodide: {
      runPythonAsync: async () => { throw Error("never execute payload as source"); },
      toPy: value => { created++; return { toJs: () => value, destroy: () => { destroyed++; } }; },
      pyimport: () => ({ dispatch: proxy => {
        const input = proxy.toJs?.() as { request: RpcRequest; payload: Record<string, unknown> };
        passed.push(input.payload);
        const r = input.request;
        return { api_version: "1.0", request_id: r.request_id, project_id: r.project_id, project_revision: r.project_revision,
          status: "success", result: r.operation === "core.capabilities" ? { supported_operations: ["core.reuse_model"] } : { transport_test_double: true },
          assumptions: {}, diagnostics: {}, provenance: { algorithm: "transport_test_double", lib_versions: {} }, warnings: [], error: null } satisfies RpcResponse;
      } }),
    },
  });
  const runtime = new PyodideWorkerRuntime({ pyodideLoader: loader, postMessage: m => { messages.push(m as WorkerOutboundMessage); } });
  await runtime.handleMessage({ kind: "init", msg_id: "init", config: {} });
  await runtime.handleMessage({ kind: "register_object", msg_id: "register", project_id: project, object_id: "model", revision: 0, value: dto(), object_kind: "StateSpace" });
  await runtime.handleMessage({ kind: "rpc_request", request: request("core.reuse_model", { model_ref: { id: "model", revision: 0 } }) });
  assert.deepEqual(passed.at(-1), { model: dto() });
  const dispatched = passed.length;
  await runtime.handleMessage({ kind: "rpc_request", request: request("core.reuse_model", { model: dto(), model_ref: { id: "model", revision: 0 } }, "ambiguous") });
  assert.equal(passed.length, dispatched);
  const last = messages.at(-1);
  assert.equal(last?.kind, "rpc_response");
  if (last?.kind === "rpc_response") assert.equal(last.response.error?.code, "VALIDATION_ERROR");
  assert.equal(created, destroyed);
  assert.equal(runtime.pyproxyRegistry.activeProxies, 0);
  assert.equal(runtime.modelStore.getStats().entry_count, 1);
});

test("F7-REF Mock shares fail-closed aliases without fabricating model-reuse science", async () => {
  const mock = new MockWorkerAdapter({ store: new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() }), latencyMs: 0 });
  try {
    await mock.init();
    await mock.registerObject(project, "model", 0, dto(), { kind: "StateSpace" });
    const bad = await mock.execute(request("core.reuse_model", { model: dto(), model_ref: { id: "model", revision: 0 } }));
    assert.equal(bad.error?.code, "VALIDATION_ERROR");
    const missing = await mock.execute(request("core.reuse_model", { model_ref: { id: "model", revision: 9 } }, "missing"));
    assert.equal(missing.error?.code, "VALIDATION_ERROR");
    const unsupported = await mock.execute(request("core.reuse_model", { model_ref: { id: "model", revision: 0 } }, "supported-transport-only"));
    assert.equal(unsupported.error?.code, "UNSUPPORTED_MODEL");
    assert.equal(unsupported.result, null);
  } finally { mock.dispose(); }
});

test("F7-REF MIMO design_decoupler, simulate_closed_loop, and design_hinf resolve plant_ref/model_ref and optional decoupler_ref/controller_ref", () => {
  const store = populated();
  const decoupler = dto("decoupler", 0, "TransferFunction");
  const controller = dto("controller", 0, "DynamicController");
  store.put(project, "decoupler", 0, decoupler);
  store.put(project, "controller", 0, controller);

  assert.deepEqual(
    resolve("mimo.design_decoupler", { plant_ref: { id: "model", revision: 0 }, method: "simplified" }, store),
    { plant: dto(), method: "simplified" },
  );
  assert.deepEqual(
    resolve("mimo.design_hinf", { model_ref: { id: "model", revision: 0 }, w1_num: [1], w1_den: [1, 1] }, store),
    { plant: dto(), w1_num: [1], w1_den: [1, 1] },
  );
  assert.deepEqual(
    resolve("mimo.simulate_closed_loop", { plant_ref: { id: "model", revision: 0 }, t: [0, 1] }, store),
    { plant: dto(), t: [0, 1] },
  );
  assert.deepEqual(
    resolve("mimo.simulate_closed_loop", {
      plant_ref: { id: "model", revision: 0 },
      decoupler_ref: { id: "decoupler", revision: 0 },
      controller_ref: { id: "controller", revision: 0 },
      t: [0, 1],
    }, store),
    { plant: dto(), decoupler, controller, t: [0, 1] },
  );
  rejected(() => resolve("mimo.simulate_closed_loop", {
    plant_ref: { id: "model", revision: 0 },
    decoupler,
    decoupler_ref: { id: "decoupler", revision: 0 },
  }, store));
});

