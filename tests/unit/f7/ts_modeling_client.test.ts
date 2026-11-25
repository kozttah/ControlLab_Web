import test from "node:test";
import assert from "node:assert/strict";

import { supportsTsModeling, type ControlLabEngineClient } from "../../../web/bridge/client.ts";
import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { PyodideEngineClient } from "../../../web/bridge/pyodide_client.ts";
import { RPC_API_VERSION, type RpcRequest, type RpcResponse } from "../../../web/bridge/protocol.ts";
import { TS_MODELING_OPERATIONS, type TsModelingContext, type TsModelingProgressEvent } from "../../../web/bridge/ts_modeling.ts";
import { InMemoryIDBFactory } from "../../../web/storage/indexeddb_store.ts";
import type { WorkerInboundMessage, WorkerLikeTransport } from "../../../web/worker/pyodide_worker.ts";

const context = (request_id: string, revision = 1): TsModelingContext => ({
  request_id,
  project_id: "ts-mod",
  project_revision: revision,
});
const inputs = {
  state_bounds: { x1: [-1, 1], x2: [-1, 1] } as const,
  A_expr: [["-2 - x1", 0], [0, "-2 - x2"]],
  B_expr: [[1], [0]],
};
const premises = [
  { name: "z1", expression: "x1" },
  { name: "z2", expression: "x2", measured: false },
];
const storeOptions = { idbFactory: new InMemoryIDBFactory(), dbName: "ts_modeling_client_test" };

test("F7 TS modeling methods return deterministic typed examples and export by exact model reference", async () => {
  const client: ControlLabEngineClient = new MockWorkerAdapter({ storeOptions });
  assert.ok(supportsTsModeling(client));
  try {
    const capabilities = await client.init();
    for (const operation of Object.values(TS_MODELING_OPERATIONS)) {
      assert.ok(capabilities.operations.includes(operation));
    }

    const analysis = await client.analyzeSectorPremises(context("analyze"), { state_bounds: inputs.state_bounds, premises });
    assert.equal(analysis.result?.inferred_kind, "ts_partially_observed");
    assert.deepEqual(analysis.result?.premise_availability.unmeasured_premises, ["z2"]);

    const sector = await client.deriveTsSector(context("sector"), { ...inputs, premises });
    const tpmt = await client.deriveTsTpmt(context("tpmt"), inputs);
    const femt = await client.deriveTsFemt(context("femt"), { ...inputs, mesh_kind: "delaunay", model_id: "derived" });
    const femtAgain = await client.deriveTsFemt(context("femt-again"), { ...inputs, mesh_kind: "delaunay", model_id: "derived" });
    assert.equal(sector.result?.ts_state_space.membership_spec.representation_kind, "sector_nonlinearity");
    assert.equal(tpmt.result?.ts_state_space.membership_spec.tpmt_axes.length, 2);
    assert.equal(tpmt.result?.bases_post_transform.length, 2);
    assert.equal(femt.result?.ts_state_space.membership_spec.femt_mesh.simplices?.length, 2);
    assert.deepEqual(femt.result, femtAgain.result);
    assert.equal(femt.provenance.mock, true);
    assert.equal(client.getCommittedRevision("ts-mod"), -1);
    const model = femt.result?.ts_state_space;
    assert.ok(model);
    assert.equal(await client.getObject("ts-mod", model.id, model.revision), null);

    await client.registerObject("ts-mod", model.id, model.revision, model);
    const payload = { model_ref: { id: model.id, revision: model.revision }, language: "matlab" as const };
    const fromRef = await client.exportTsDerivationScript(context("ref"), payload);
    const inline = await client.exportTsDerivationScript(context("inline"), { model, language: "matlab" });
    assert.deepEqual(fromRef.result, inline.result);
    assert.equal(fromRef.result?.code_executed, false);
    assert.equal(fromRef.result?.requires_explicit_user_execution, true);
    assert.match(fromRef.result?.filename ?? "", /\.m$/);
    const absent = await client.exportTsDerivationScript(context("absent"), {
      ...payload, model_ref: { id: model.id, revision: model.revision + 1 },
    });
    assert.equal(absent.error?.code, "VALIDATION_ERROR");
  } finally {
    client.dispose();
  }
});

test("F7 TS modeling progress and cancellation do not commit a superseded model", async () => {
  const client = new MockWorkerAdapter({
    storeOptions,
    latencyResolver: request => request.project_revision === 1 ? 1_000 : 0,
  });
  const stages: TsModelingProgressEvent[] = [];
  let started!: () => void;
  const slowStarted = new Promise<void>(resolve => { started = resolve; });
  client.subscribeTsModelingProgress(event => {
    stages.push(event);
    if (event.request_id === "old" && event.progress.stage === "validating") started();
  });
  try {
    await client.init();
    const old = client.deriveTsFemt(context("old"), inputs);
    await slowStarted;
    const current = await client.deriveTsFemt(context("new", 2), inputs);
    assert.equal(current.status, "success");
    assert.equal((await old).error?.code, "CANCELLED");
    assert.equal(client.getCommittedRevision("ts-mod"), -1);
    assert.deepEqual(stages.filter(event => event.request_id === "new").map(event => event.progress.stage),
      ["validating", "computing", "completed"]);
    assert.deepEqual(stages.filter(event => event.request_id === "old").map(event => event.progress.stage),
      ["validating"]);
  } finally {
    client.dispose();
  }
});

test("F7 Pyodide client ignores malformed progress and drops a result after the user cancelled", async () => {
  let listener: ((event: { data?: unknown }) => void) | undefined;
  let request: RpcRequest | undefined;
  let postedInterrupt: SharedArrayBuffer | undefined;
  let cancelAcknowledged = false;
  const previousIsolation = Object.getOwnPropertyDescriptor(globalThis, "crossOriginIsolated");
  Object.defineProperty(globalThis, "crossOriginIsolated", { value: true, configurable: true });
  const dispatch = (data: unknown) => listener?.({ data });
  const mockCapabilities = new MockWorkerAdapter({ storeOptions });
  const adapter: WorkerLikeTransport = {
    addEventListener(type, fn) { if (type === "message") listener = fn; },
    removeEventListener() {},
    terminate() {},
    postMessage(raw, transfer) {
      const message = raw as WorkerInboundMessage;
      if (message.kind === "init") {
        dispatch({
          kind: "init_ok", msg_id: message.msg_id, worker_id: "test-worker",
          store_instance_id: "test-store",
          capabilities: { ...mockCapabilities.getCapabilities(), engine_kind: "pyodide" },
          timings: {},
        });
        return;
      }
      if (message.kind === "rpc_request") {
        request = message.request;
        assert.deepEqual(transfer ?? [], []);
        postedInterrupt = message.interrupt_buffer;
        for (const progress of [
          { stage: "invalid", elapsed_ms: 0 },
          { stage: "computing", elapsed_ms: Number.POSITIVE_INFINITY },
          { stage: "validating", elapsed_ms: 0 },
        ]) dispatch({ type: "ts_modeling_progress", request_id: request.request_id, progress });
        return;
      }
      if (message.kind === "cancel") {
        assert.ok(request && postedInterrupt);
        const bits = new Uint8Array(postedInterrupt);
        assert.equal(Atomics.load(bits, 1), 1);
        assert.equal(Atomics.load(bits, 0), 2);
        cancelAcknowledged = true;
        dispatch({ type: "ts_modeling_progress", request_id: request.request_id, progress: { stage: "completed", elapsed_ms: 1 } });
        const response: RpcResponse = {
          api_version: RPC_API_VERSION,
          request_id: request.request_id,
          project_id: request.project_id,
          project_revision: request.project_revision,
          status: "success",
          result: {},
          assumptions: {},
          diagnostics: {},
          provenance: { algorithm: request.operation, lib_versions: {} },
          warnings: [],
          error: null,
        };
        queueMicrotask(() => dispatch({ kind: "rpc_response", response }));
      }
    },
  };
  const client = new PyodideEngineClient({ storeOptions, workerFactory: () => ({ worker: adapter }) });
  let started!: () => void;
  const start = new Promise<void>(resolve => { started = resolve; });
  const stages: string[] = [];
  client.subscribeTsModelingProgress(({ progress }) => {
    stages.push(progress.stage);
    started();
  });
  try {
    await client.init();
    const result = client.deriveTsFemt(context("authentic-dispatch"), inputs, { commitOnSuccess: true });
    await start;
    assert.equal(request?.operation, TS_MODELING_OPERATIONS.deriveTsFemt);
    assert.deepEqual(request?.payload, inputs);
    assert.equal(await client.cancel("authentic-dispatch"), true);
    assert.equal((await result).error?.code, "CANCELLED");
    assert.ok(cancelAcknowledged);
    assert.deepEqual(stages, ["validating"]);
    assert.equal(client.getCommittedRevision("ts-mod"), -1);
  } finally {
    client.dispose();
    mockCapabilities.dispose();
    if (previousIsolation) Object.defineProperty(globalThis, "crossOriginIsolated", previousIsolation);
    else Reflect.deleteProperty(globalThis, "crossOriginIsolated");
  }
});
