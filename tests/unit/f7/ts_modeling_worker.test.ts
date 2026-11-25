import assert from "node:assert/strict";
import test from "node:test";

import type { RpcRequest, RpcResponse } from "../../../web/bridge/protocol.ts";
import {
  PyodideWorkerRuntime,
  type WorkerOutboundMessage,
  type WorkerTsModelingProgressMessage,
} from "../../../web/worker/pyodide_worker.ts";
import type { PyProxyLike } from "../../../web/worker/pyproxy_guard.ts";

type Message = WorkerOutboundMessage | WorkerTsModelingProgressMessage;
type DispatchPayload = { request: RpcRequest; payload: Record<string, unknown> };

function makeWorker() {
  const messages: Message[] = [];
  const dispatches: DispatchPayload[] = [];
  const changes: { dispatch?: (request: RpcRequest) => Promise<void> | void } = {};
  let currentInterrupt: Uint8Array | undefined;
  let destroyed = 0;
  function proxy(data: unknown): PyProxyLike {
    return { __isPyProxy: true, toJs: () => data, destroy: () => { destroyed++; } };
  }
  function dispatch(input: PyProxyLike) {
    const actual = input.toJs!() as DispatchPayload;
    dispatches.push(actual);
    const { request } = actual;
    const envelope: RpcResponse = {
      api_version: "1.0", request_id: request.request_id, project_id: request.project_id,
      project_revision: request.project_revision, status: "success", assumptions: {}, diagnostics: {},
      warnings: [], error: null, provenance: { algorithm: request.operation, lib_versions: {} },
      result: request.operation === "core.capabilities"
        ? { supported_operations: ["fuzzy.derive_ts_tpmt", "fuzzy.export_ts_derivation_script"] }
        : { dispatched: true },
    };
    const pending = changes.dispatch?.(request);
    return pending ? pending.then(() => proxy(envelope)) : proxy(envelope);
  }

  const runtime = new PyodideWorkerRuntime({
    postMessage: (value) => { messages.push(value as Message); },
    pyodideLoader: async () => ({
      libVersions: {},
      pyodide: {
        runPythonAsync: async () => undefined,
        toPy: proxy,
        pyimport: (module) => module === "control_lab.fuzzy.symbolic_qlpv" ? {
          extract_active_variables: () => proxy(["x"]),
        } : { dispatch },
        setInterruptBuffer: (buffer) => { currentInterrupt = buffer; },
      },
    }),
  });
  return {
    runtime, messages, dispatches, changes,
    get interrupt() { return currentInterrupt; },
    get destroyed() { return destroyed; },
  };
}

function request(requestId: string, operation = "fuzzy.derive_ts_tpmt", payload: Record<string, unknown> = {}): RpcRequest {
  return {
    api_version: "1.0", request_id: requestId, project_id: "test-project", project_revision: 1,
    operation, payload, options: {}, timeout_policy: { hard_timeout_ms: 5_000 },
  };
}

function result(messages: Message[], requestId: string): RpcResponse | undefined {
  const envelope = messages.find((message) => "kind" in message && message.kind === "rpc_response" &&
    message.response.request_id === requestId);
  return envelope && "kind" in envelope && envelope.kind === "rpc_response" ? envelope.response : undefined;
}

function stages(messages: Message[], requestId: string): string[] {
  return messages.flatMap((message) => "type" in message && message.request_id === requestId ? [message.progress.stage] : []);
}

test("TS modeling Worker emits phases and blocks over-budget memory before dispatch", async () => {
  const f = makeWorker();
  await f.runtime.handleMessage({ kind: "init", msg_id: "init" });

  await f.runtime.handleMessage({ kind: "rpc_request", request: request("huge", "fuzzy.derive_ts_femt", {
    grid_points: [230, 230], mesh_kind: "delaunay",
  }) });
  assert.equal(result(f.messages, "huge")?.error?.code, "RESOURCE_LIMIT");
  assert.deepEqual(stages(f.messages, "huge"), ["validating"]);
  assert.equal(f.dispatches.some(({ request }) => request.request_id === "huge"), false);

  await f.runtime.handleMessage({ kind: "rpc_request", request: request("validation-budget", "fuzzy.derive_ts_tpmt", {
    n_val_points: 100_000,
  }) });
  assert.equal(result(f.messages, "validation-budget")?.error?.code, "RESOURCE_LIMIT");
  assert.equal(f.dispatches.some(({ request }) => request.request_id === "validation-budget"), false);

  const base = { A_expr: [["x"]], B_expr: [[1]] };
  await f.runtime.handleMessage({ kind: "rpc_request", request: request("axis", "fuzzy.derive_ts_tpmt", {
    ...base, resample_points: { x: 250_001 },
  }) });
  assert.equal(result(f.messages, "axis")?.error?.code, "RESOURCE_LIMIT");
  assert.equal(f.dispatches.some(({ request }) => request.request_id === "axis"), false);

  await f.runtime.handleMessage({ kind: "rpc_request", request: request("valid", "fuzzy.derive_ts_tpmt", {
    ...base, resample_points: { x: 9, inactive: 250_001 },
  }) });
  assert.equal(result(f.messages, "valid")?.status, "success");
  assert.deepEqual(stages(f.messages, "valid"), ["validating", "computing", "completed"]);
  assert.equal(f.runtime.getDiagnosticsStats().pyproxy.activeProxies, 0);
});

test("TS modeling shared interrupt survives consumption of SIGINT and releases Python output", async () => {
  const f = makeWorker();
  await f.runtime.handleMessage({ kind: "init", msg_id: "init" });
  const shared = new SharedArrayBuffer(2);
  const signal = new Uint8Array(shared);
  const idleInterrupt = f.interrupt;
  const before = f.destroyed;
  let sawShared = false;
  f.changes.dispatch = () => {
    sawShared = f.interrupt?.buffer === shared;
    Atomics.store(signal, 1, 1);
    Atomics.store(signal, 0, 0);
  };
  await f.runtime.handleMessage({ kind: "rpc_request", request: request("interrupt"), interrupt_buffer: shared });
  assert.equal(sawShared, true);
  assert.equal(f.interrupt, idleInterrupt);
  assert.equal(result(f.messages, "interrupt")?.error?.code, "CANCELLED");
  assert.deepEqual(stages(f.messages, "interrupt"), ["validating", "computing"]);
  assert.equal(f.destroyed - before, 2);
  assert.equal(f.runtime.getDiagnosticsStats().pyproxy.activeProxies, 0);
});

test("canceling a queued TS request never interrupts or releases another RPC's Python proxies", async () => {
  const f = makeWorker();
  await f.runtime.handleMessage({ kind: "init", msg_id: "init" });
  let finishFirst = () => {};
  let startFirst = () => {};
  const started = new Promise<void>((resolve) => { startFirst = resolve; });
  f.changes.dispatch = ({ request_id }) => {
    if (request_id !== "first") return;
    return new Promise<void>((resolve) => { finishFirst = resolve; startFirst(); });
  };
  const first = f.runtime.handleMessage({ kind: "rpc_request", request: request("first", "core.capabilities") });
  await started;
  const second = f.runtime.handleMessage({ kind: "rpc_request", request: request("second") });
  await new Promise((resolve) => setTimeout(resolve, 10));
  await f.runtime.handleMessage({ kind: "cancel", request_id: "second" });
  assert.equal(f.interrupt?.[0], 0);
  assert.equal(f.runtime.getDiagnosticsStats().pyproxy.activeProxies, 1);
  finishFirst();
  await Promise.all([first, second]);
  assert.equal(result(f.messages, "first")?.status, "success");
  assert.equal(result(f.messages, "second")?.error?.code, "CANCELLED");
  assert.deepEqual(stages(f.messages, "second"), ["validating"]);
  assert.equal(f.runtime.getDiagnosticsStats().pyproxy.activeProxies, 0);
});

test("TS script export resolves registered model only at the exact project and revision", async () => {
  const f = makeWorker();
  await f.runtime.handleMessage({ kind: "init", msg_id: "init" });
  const model = { id: "derived", revision: 1, kind: "ts_measured" };
  f.runtime.modelStore.put("test-project", model.id, model.revision, model);
  const exportRequest = request("own", "fuzzy.export_ts_derivation_script", {
    language: "python", model_ref: { id: model.id, revision: model.revision },
  });
  await f.runtime.handleMessage({ kind: "rpc_request", request: exportRequest });
  assert.deepEqual(f.dispatches.at(-1)?.payload, { language: "python", model });
  assert.equal(result(f.messages, "own")?.status, "success");
  await f.runtime.handleMessage({ kind: "rpc_request", request: { ...exportRequest, request_id: "other", project_id: "different" } });
  assert.equal(result(f.messages, "other")?.error?.code, "VALIDATION_ERROR");
  assert.equal(f.dispatches.some(({ request }) => request.request_id === "other"), false);
});

test("TS export rejects an oversized replay grid even when loaded through a stored reference", async () => {
  const f = makeWorker();
  await f.runtime.handleMessage({ kind: "init", msg_id: "init" });
  const model = {
    id: "replay", revision: 0, kind: "ts_measured",
    membership_spec: { representation_kind: "femt_simplicial" },
    provenance: { ts_derivation: { active_variables: ["x"], grid_points: [250_001] } },
  };
  f.runtime.modelStore.put("test-project", model.id, model.revision, model);
  for (const [id, source] of [["inline", { model }], ["ref", { model_ref: { id: model.id, revision: model.revision } }]] as const) {
    await f.runtime.handleMessage({ kind: "rpc_request", request: request(id, "fuzzy.export_ts_derivation_script", {
      language: "python", ...source,
    }) });
    assert.equal(result(f.messages, id)?.error?.code, "RESOURCE_LIMIT");
    assert.deepEqual(stages(f.messages, id), ["validating"]);
    assert.equal(f.dispatches.some(({ request }) => request.request_id === id), false);
  }
});
