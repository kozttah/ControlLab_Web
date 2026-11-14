import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

import {
  assertBufferUsable,
  computeCanonicalSha256,
  ControlLabBridgeError,
  ERROR_CATEGORIES,
  extractTransferableBuffers,
  RPC_API_VERSION,
  sha256Hex,
  strictJsonParse,
  strictJsonStringify,
  tensorToBinaryBuffer,
  validateRpcRequest,
  validateRpcResponse,
  validateTensorDescriptor,
  type BinaryTensorInput,
  type RpcRequest,
  type RpcResponse,
} from "../../../web/bridge/protocol.ts";
import {
  DebouncedRequestCoalescer,
  type EngineClientEvent,
} from "../../../web/bridge/client.ts";
import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { PyodideEngineClient } from "../../../web/bridge/pyodide_client.ts";
import {
  IndexedDBProjectStore,
  InMemoryIDBFactory,
} from "../../../web/storage/indexeddb_store.ts";
import { WorkerModelStore } from "../../../web/worker/model_store.ts";
import {
  assertNoPyProxy,
  PyProxyRegistry,
  safeWorkerPostMessage,
  withPyProxy,
  type PyProxyLike,
} from "../../../web/worker/pyproxy_guard.ts";
import {
  createMessageChannelWorkerTransport,
  type PyodideInterfaceLike,
  type PyodideLoaderFn,
} from "../../../web/worker/pyodide_worker.ts";
import {
  CACHE_NAME_PREFIX,
  DEFAULT_STATIC_CACHE_NAME,
  DEFAULT_STATIC_MANIFEST,
  InMemoryCacheStorage,
  ServiceWorkerController,
} from "../../../web/worker/service_worker.ts";

import { fixturePyodideLoader, makeFixturePyodideLoader } from "./fixture_runtime.ts";
import { cpythonLoader } from "./cpython_runtime.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "../../..");
const CONTRACTS_DIR = path.join(REPO_ROOT, "contracts");
const FIXTURES_DIR = path.join(CONTRACTS_DIR, "fixtures");
const EXAMPLES_DIR = path.join(CONTRACTS_DIR, "examples");

function loadChecksums(): Record<string, string> {
  const raw = fs.readFileSync(path.join(FIXTURES_DIR, "checksums.sha256"), "utf8");
  const out: Record<string, string> = {};
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const [digest, fname] = trimmed.split(/\s+/);
    out[fname.trim()] = digest.trim().toLowerCase();
  }
  return out;
}

function makeLqrRequest(overrides?: Partial<RpcRequest>): RpcRequest {
  return {
    api_version: RPC_API_VERSION,
    request_id: overrides?.request_id ?? "req-001",
    project_id: overrides?.project_id ?? "proj-test",
    project_revision: overrides?.project_revision ?? 1,
    operation: overrides?.operation ?? "statespace.design_lqr",
    payload: overrides?.payload ?? {
      plant_ref: { id: "plant-001", revision: 1 },
      Q: {
        shape: [2, 2],
        dtype: "float64",
        order: "C",
        data: [1, 0, 0, 1],
      },
      R: {
        shape: [1, 1],
        dtype: "float64",
        order: "C",
        data: [1],
      },
    },
    options: overrides?.options ?? {},
    timeout_policy: overrides?.timeout_policy ?? {
      hard_timeout_ms: 5000,
    },
  };
}

function make2x2Plant(revision = 1): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    id: "plant-001",
    revision,
    kind: "StateSpace",
    dt: null,
    state_names: ["x1", "x2"],
    input_names: ["u"],
    output_names: ["y"],
    matrices: {
      A: { shape: [2, 2], dtype: "float64", order: "C", data: [0, 1, 0, 0] },
      B: { shape: [2, 1], dtype: "float64", order: "C", data: [0, 1] },
      C: { shape: [1, 2], dtype: "float64", order: "C", data: [1, 0] },
      D: { shape: [1, 1], dtype: "float64", order: "C", data: [0] },
    },
    units: { time: "s", inputs: ["N"], outputs: ["m"] },
    provenance: { source: "B-CARE-02" },
  };
}

// ---------------------------------------------------------------------------
// 1. Contrato RPC v1.0, SHA-256, NaN/Inf, 12 categorias de erro e exemplos
// ---------------------------------------------------------------------------

test("F7-CONTRACT-01: sha256Hex puro coincide com node:crypto e checksums.sha256 das fixtures ouro", () => {
  const checksums = loadChecksums();
  for (const [fname, expected] of Object.entries(checksums)) {
    const rawText = fs.readFileSync(path.join(FIXTURES_DIR, fname), "utf8");
    const pureTsDigest = sha256Hex(rawText);
    const nodeDigest = crypto.createHash("sha256").update(rawText).digest("hex");
    assert.equal(pureTsDigest, nodeDigest);
    assert.equal(pureTsDigest, expected, `SHA-256 divergente para ${fname}`);
  }

  const canonicalA = computeCanonicalSha256({ b: 2, a: [1, 2] });
  const canonicalB = computeCanonicalSha256({ a: [1, 2], b: 2 });
  assert.equal(canonicalA, canonicalB);
});

test("F7-CONTRACT-02: valida exemplos normativos rpc_request_lqr.json e rpc_response_lqr.json e rejeita NaN/Infinity/versão/campos extras", () => {
  const reqRaw = JSON.parse(
    fs.readFileSync(path.join(EXAMPLES_DIR, "rpc_request_lqr.json"), "utf8"),
  ) as unknown;
  const respRaw = JSON.parse(
    fs.readFileSync(path.join(EXAMPLES_DIR, "rpc_response_lqr.json"), "utf8"),
  ) as unknown;

  const validReq = validateRpcRequest(reqRaw);
  const validResp = validateRpcResponse(respRaw);
  assert.equal(validReq.api_version, "1.0");
  assert.equal(validResp.status, "success");

  // Rejeita NaN e Infinity em payloads, tensores e JSON estrito
  assert.throws(
    () =>
      validateRpcRequest({
        ...validReq,
        payload: { x: Number.NaN },
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );
  assert.throws(
    () =>
      validateRpcRequest({
        ...validReq,
        payload: { x: Number.POSITIVE_INFINITY },
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );
  assert.throws(
    () => strictJsonStringify({ a: [1, Number.NEGATIVE_INFINITY] }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );
  assert.throws(
    () => strictJsonParse('{"x": NaN}'),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );

  // Rejeita api_version não suportada com SCHEMA_UNSUPPORTED
  assert.throws(
    () =>
      validateRpcRequest({
        ...validReq,
        api_version: "2.0",
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "SCHEMA_UNSUPPORTED",
  );

  // Rejeita campo extra (additionalProperties: false) e operacao malformada
  assert.throws(
    () =>
      validateRpcRequest({
        ...validReq,
        unexpected_field: 123,
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );
  assert.throws(
    () =>
      validateRpcRequest({
        ...validReq,
        operation: "InvalidOp",
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );

  // Rejeita falha sem error ou success com error, e valida tensor descriptor
  assert.throws(
    () =>
      validateRpcResponse({
        ...validResp,
        status: "failure",
        error: null,
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );
  assert.throws(
    () =>
      validateTensorDescriptor({
        shape: [2, 2],
        dtype: "float64",
        order: "C",
        data: [1, 2, 3],
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "DIMENSION_MISMATCH",
  );
});

test("F7-CONTRACT-03: todas as 12 categorias normativas de erro funcionam e são validadas pelo contrato", async () => {
  assert.equal(ERROR_CATEGORIES.length, 12);
  const mock = new MockWorkerAdapter({
    store: new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() }),
  });
  await mock.init();

  for (const category of ERROR_CATEGORIES) {
    const resp = await mock.execute(
      makeLqrRequest({
        request_id: `err-${category}`,
        project_revision: 1,
        options: { __simulate_error: category },
      }),
    );
    const validated = validateRpcResponse(resp);
    assert.equal(validated.status, "failure");
    assert.equal(validated.result, null);
    assert.ok(validated.error !== null);
    assert.equal(validated.error.code, category);
  }
});

// ---------------------------------------------------------------------------
// 2. T-RPC-01: Sequência rápida >= 20 requisições fora de ordem e monotonicidade
// ---------------------------------------------------------------------------

test("T-RPC-01 (MockWorkerAdapter): 25 requisições rápidas fora de ordem — apenas revisão mais recente comita no IndexedDB", async () => {
  const idbFactory = new InMemoryIDBFactory();
  const store = new IndexedDBProjectStore({ idbFactory, dbName: "t_rpc_01_mock" });

  // Latências invertidas propositalmente: revisões mais novas chegam antes OU bem depois das antigas
  const mock = new MockWorkerAdapter({
    store,
    latencyResolver: (req) => {
      if (req.project_revision === 25) return 35; // última revisão termina no meio
      if (req.project_revision % 2 === 0) return 5; // pares terminam super rápido antes de 25
      return 60; // ímpares antigas terminam muito depois de 25 já ter comitado!
    },
  });
  await mock.init();

  const events: EngineClientEvent[] = [];
  mock.subscribe((ev) => events.push(ev));

  const projectId = "proj-race-mock";
  const total = 25;
  const requests: RpcRequest[] = [];
  for (let rev = 1; rev <= total; rev += 1) {
    requests.push(
      makeLqrRequest({
        request_id: `race-mock-${rev}`,
        project_id: projectId,
        project_revision: rev,
        timeout_policy: {
          hard_timeout_ms: 5000,
          cancel_on_supersede: false,
        },
      }),
    );
  }

  const responses = await Promise.all(requests.map((r) => mock.execute(r)));
  assert.equal(responses.length, total);

  for (let i = 0; i < total; i += 1) {
    const rev = i + 1;
    const resp = responses[i];
    if (rev < total) {
      assert.equal(resp.status, "failure", `rev ${rev} deveria ser descartada`);
      assert.equal(resp.error?.code, "CANCELLED");
      assert.equal(resp.diagnostics.stale_discarded, true);
      assert.equal(resp.diagnostics.committed, false);
    } else {
      assert.equal(resp.status, "success");
      assert.equal(resp.project_revision, total);
      assert.equal(resp.diagnostics.committed, true);
      assert.equal(resp.diagnostics.stale_discarded, false);
    }
  }

  // Verificar estado confirmado em memória e no IndexedDB
  assert.equal(mock.getActiveRevision(projectId), total);
  assert.equal(mock.getCommittedRevision(projectId), total);
  const persistedProj = await store.getProject(projectId);
  assert.ok(persistedProj !== null);
  assert.equal(persistedProj.committed_revision, total);
  assert.equal(persistedProj.last_request_id, `race-mock-${total}`);

  const latestSnap = await store.getLatestConfirmedSnapshot(projectId);
  assert.ok(latestSnap !== null);
  assert.equal(latestSnap.project_revision, total);

  // Eventos stale_response_discarded emitidos para todas as revisões antigas
  const discardedEvents = events.filter((e) => e.type === "stale_response_discarded");
  assert.equal(discardedEvents.length, total - 1);

  // Tentativa explícita de comitar revisão obsoleta diretamente no IndexedDB é abortada
  await assert.rejects(
    () =>
      store.commitProjectRevision({
        project_id: projectId,
        project_revision: 10,
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError &&
      err.typedError.details?.reason === "STALE_REVISION",
  );
  const afterStaleAttempt = await store.getProject(projectId);
  assert.equal(afterStaleAttempt?.committed_revision, total);
});

test("T-RPC-01 unidade (MessageChannel + fixture double; sem Wasm): 24 requisições fora de ordem e sem vazamento PyProxy", async () => {
  const idbFactory = new InMemoryIDBFactory();
  const store = new IndexedDBProjectStore({ idbFactory, dbName: "t_rpc_01_pyodide" });

  let proxiesCreated = 0;
  let proxiesDestroyed = 0;

  const pyodideLoader = makeFixturePyodideLoader({
    created: () => { proxiesCreated += 1; },
    destroyed: () => { proxiesDestroyed += 1; },
  });

  const client = new PyodideEngineClient({
    store,
    workerFactory: () =>
      createMessageChannelWorkerTransport({ pyodideLoader }),
  });
  try {
    await client.init();

    const metricsInit = client.getMetrics();
    assert.equal(metricsInit.T_download, 2);
    assert.equal(metricsInit.T_init_pyodide, 3);
    assert.equal(metricsInit.T_import_packages, 4);
    assert.equal(metricsInit.cold_completed, false);

    const projectId = "proj-race-pyodide";
    const total = 24;
    const reqs: RpcRequest[] = [];
    for (let rev = 1; rev <= total; rev += 1) {
      const delay = rev === total ? 20 : rev % 3 === 0 ? 4 : 45;
      reqs.push(
        makeLqrRequest({
          request_id: `race-py-${rev}`,
          project_id: projectId,
          project_revision: rev,
          options: { __delay_ms: delay },
          timeout_policy: { hard_timeout_ms: 5000, cancel_on_supersede: false },
        }),
      );
    }

    const responses = await Promise.all(reqs.map((r) => client.execute(r)));
    for (let i = 0; i < total; i += 1) {
      const rev = i + 1;
      if (rev < total) {
        assert.equal(responses[i].status, "failure");
        assert.equal(responses[i].error?.code, "CANCELLED");
        assert.equal(responses[i].diagnostics.stale_discarded, true);
      } else {
        assert.equal(responses[i].status, "success");
        assert.equal(responses[i].diagnostics.committed, true);
        assert.equal(responses[i].project_revision, total);
      }
    }

    const persisted = await store.getProject(projectId);
    assert.equal(persisted?.committed_revision, total);
    assert.equal(persisted?.last_request_id, `race-py-${total}`);

    // Verificar métricas separadas (cold vs warm) e zero PyProxy leaks
    const metricsAfter = client.getMetrics();
    assert.equal(metricsAfter.cold_completed, true);
    assert.equal(metricsAfter.call_count, total);
    assert.ok(metricsAfter.T_first_call !== null);
    assert.ok(metricsAfter.T_warm_call !== null);
    assert.equal(metricsAfter.warm_calls_count, total - 1);

    const stats = await client.getWorkerStats();
    assert.equal(stats.pyproxy.activeProxies, 0);
    assert.equal(proxiesCreated, total + 1); // handshake core.capabilities
    assert.equal(proxiesDestroyed, total + 1);
  } finally {
    client.dispose();
  }
});

test("F7-COALESCE-01: DebouncedRequestCoalescer consolida disparos rápidos e cancela intermediários", async () => {
  const coalescer = new DebouncedRequestCoalescer();
  let executedCount = 0;

  const mkReq = (rev: number) =>
    makeLqrRequest({
      request_id: `deb-${rev}`,
      project_id: "proj-debounce",
      project_revision: rev,
    });

  const dispatch = async (req: RpcRequest): Promise<RpcResponse> => {
    executedCount += 1;
    return {
      api_version: RPC_API_VERSION,
      request_id: req.request_id,
      project_id: req.project_id,
      project_revision: req.project_revision,
      status: "success",
      result: { rev: req.project_revision },
      assumptions: {},
      diagnostics: {},
      provenance: { algorithm: "test", lib_versions: {} },
      warnings: [],
      error: null,
    };
  };

  const p1 = coalescer.schedule("slider", mkReq(1), 25, dispatch);
  const p2 = coalescer.schedule("slider", mkReq(2), 25, dispatch);
  const p3 = coalescer.schedule("slider", mkReq(3), 25, dispatch);

  const [r1, r2, r3] = await Promise.all([p1, p2, p3]);
  assert.equal(executedCount, 1);
  assert.equal(r1.status, "failure");
  assert.equal(r1.error?.code, "CANCELLED");
  assert.equal(r2.status, "failure");
  assert.equal(r2.error?.code, "CANCELLED");
  assert.equal(r3.status, "success");
  assert.equal(r3.project_revision, 3);
});

// ---------------------------------------------------------------------------
// 3. T-RPC-02: Cancelamento, terminate() do Worker e reidratação do IndexedDB
// ---------------------------------------------------------------------------

test("T-RPC-02 (MockWorkerAdapter): cancel(), terminate()/resetWorker(), ciclo recovering->ready e reidratação fiel", async () => {
  const store = new IndexedDBProjectStore({
    idbFactory: new InMemoryIDBFactory(),
    dbName: "t_rpc_02_mock",
  });
  const mock = new MockWorkerAdapter({ store, latencyMs: 0 });
  await mock.init();

  const lifecycleTransitions: string[] = [];
  let recoveredEventCount = 0;
  mock.subscribe((ev) => {
    if (ev.type === "lifecycle") {
      lifecycleTransitions.push(`${ev.previous}->${ev.current}`);
    } else if (ev.type === "worker_recovered") {
      recoveredEventCount += 1;
    }
  });

  const projectId = "proj-rehydrate-mock";
  const plant = make2x2Plant(4);
  await mock.registerObject(projectId, "plant-001", 4, plant, {
    kind: "StateSpace",
  });
  const committed = await mock.execute(
    makeLqrRequest({
      request_id: "commit-rev4",
      project_id: projectId,
      project_revision: 4,
      payload: {
        plant_ref: { id: "plant-001", revision: 4 },
        Q: { shape: [2, 2], dtype: "float64", order: "C", data: [4, 0, 0, 2] },
        R: { shape: [1, 1], dtype: "float64", order: "C", data: [1] },
      },
    }),
  );
  assert.equal(committed.status, "success");
  await mock.commitProject(projectId, 4, {
    request_id: "commit-rev4",
    committed_result: committed,
    objects: [
      { object_id: "plant-001", revision: 4, kind: "StateSpace", value: plant },
    ],
  });

  const storeIdBefore = mock.getWorkerStoreStats().store_instance_id;

  // Inicia requisição demorada na revisão 5 e cancela com forceTerminate
  const slowPromise = mock.execute(
    makeLqrRequest({
      request_id: "slow-rev5",
      project_id: projectId,
      project_revision: 5,
      options: { __delay_ms: 500 },
    }),
  );
  await new Promise((r) => setTimeout(r, 15));
  const cancelled = await mock.cancel("slow-rev5", { forceTerminate: true });
  assert.equal(cancelled, true);

  const slowResp = await slowPromise;
  assert.equal(slowResp.status, "failure");
  assert.ok(
    slowResp.error?.code === "CANCELLED" ||
      slowResp.error?.code === "WORKER_RESTARTED",
  );
  assert.equal(mock.getLifecycleState(), "ready");
  assert.ok(lifecycleTransitions.includes("ready->recovering"));
  assert.ok(lifecycleTransitions.includes("recovering->ready"));
  assert.equal(recoveredEventCount, 1);

  // Verifica novo WorkerModelStore e reidratação fiel do snapshot rev 4
  const storeStatsAfter = mock.getWorkerStoreStats();
  assert.notEqual(storeStatsAfter.store_instance_id, storeIdBefore);
  assert.equal(storeStatsAfter.entry_count, 1);

  const rehydratedPlant = await mock.getObject(projectId, "plant-001", 4);
  assert.deepEqual(rehydratedPlant, plant);

  const snapAfter = await store.getLatestConfirmedSnapshot(projectId);
  assert.equal(snapAfter?.project_revision, 4);
});

test("T-RPC-02 unidade (MessageChannel + IDB em memória + fixture double): terminate() fecha o transporte, recria WorkerModelStore vazio e reidrata snapshot do IndexedDB", async () => {
  const store = new IndexedDBProjectStore({
    idbFactory: new InMemoryIDBFactory(),
    dbName: "t_rpc_02_pyodide",
  });

  let terminateCalls = 0;
  const workerStoreIds: string[] = [];

  const client = new PyodideEngineClient({
    store,
    cancelGraceMs: 40,
    workerFactory: () => {
      const created = createMessageChannelWorkerTransport({ pyodideLoader: fixturePyodideLoader });
      workerStoreIds.push(created.runtime.modelStore.storeInstanceId);
      const origTerminate = created.worker.terminate.bind(created.worker);
      created.worker.terminate = () => {
        terminateCalls += 1;
        origTerminate();
      };
      return created;
    },
  });

  const events: string[] = [];
  let recoveredPayload: { restored_projects: string[]; restored_objects: number } | null = null;
  client.subscribe((ev) => {
    if (ev.type === "lifecycle") {
      events.push(`${ev.previous}->${ev.current}`);
    } else if (ev.type === "worker_recovered") {
      recoveredPayload = {
        restored_projects: ev.restored_projects,
        restored_objects: ev.restored_objects,
      };
    }
  });

  try {
    await client.init();
    const projectId = "proj-rehydrate-pyodide";
    const plant = make2x2Plant(7);

    await client.registerObject(projectId, "plant-001", 7, plant, {
      kind: "StateSpace",
    });
    const lqrResp = await client.execute(
      makeLqrRequest({
        request_id: "py-rev7",
        project_id: projectId,
        project_revision: 7,
        payload: {
          plant_ref: { id: "plant-001", revision: 7 },
          Q: { shape: [2, 2], dtype: "float64", order: "C", data: [4, 0, 0, 2] },
          R: { shape: [1, 1], dtype: "float64", order: "C", data: [1] },
        },
      }),
    );
    assert.equal(lqrResp.status, "success");
    await client.commitProject(projectId, 7, {
      request_id: "py-rev7",
      committed_result: lqrResp,
      objects: [
        { object_id: "plant-001", revision: 7, kind: "StateSpace", value: plant },
      ],
    });

    const statsBefore = await client.getWorkerStats();
    assert.equal(statsBefore.store.store_instance_id, workerStoreIds[0]);
    assert.equal(statsBefore.store.entry_count, 1);

    // Dispara operação bloqueante na revisão 8 e força terminate() via cancel(..., { forceTerminate: true })
    const slowOp = client.execute(
      makeLqrRequest({
        request_id: "py-slow-rev8",
        project_id: projectId,
        project_revision: 8,
        options: { __delay_ms: 800 },
      }),
    );
    await new Promise((r) => setTimeout(r, 15));
    await client.cancel("py-slow-rev8", { forceTerminate: true });

    const slowOutcome = await slowOp;
    assert.equal(slowOutcome.status, "failure");
    assert.equal(slowOutcome.error?.code, "CANCELLED");

    assert.equal(terminateCalls, 1);
    assert.equal(client.getWorkerGeneration(), 2);
    assert.equal(client.getLifecycleState(), "ready");
    assert.ok(events.includes("ready->recovering"));
    assert.ok(events.includes("recovering->ready"));
    assert.deepEqual(recoveredPayload, {
      restored_projects: [projectId],
      restored_objects: 1,
    });

    // Novo WorkerModelStore (ID distinto) foi reidratado apenas a partir do IndexedDB
    const statsAfter = await client.getWorkerStats();
    assert.equal(statsAfter.store.store_instance_id, workerStoreIds[1]);
    assert.notEqual(statsAfter.store.store_instance_id, statsBefore.store.store_instance_id);
    assert.equal(statsAfter.store.entry_count, 1);
    assert.ok(statsAfter.store.pinned_projects.includes(projectId));

    // Novo cálculo usando apenas plant_ref reidratado funciona sem re-registrar manualmente
    const afterRecoverResp = await client.execute(
      makeLqrRequest({
        request_id: "py-after-recover-rev8",
        project_id: projectId,
        project_revision: 8,
        payload: {
          plant_ref: { id: "plant-001", revision: 7 },
          Q: { shape: [2, 2], dtype: "float64", order: "C", data: [4, 0, 0, 2] },
          R: { shape: [1, 1], dtype: "float64", order: "C", data: [1] },
        },
      }),
    );
    assert.equal(afterRecoverResp.status, "success");
    assert.equal(afterRecoverResp.diagnostics.store_instance_id, workerStoreIds[1]);
  } finally {
    client.dispose();
  }
});

test("F7-CANCEL-COOP-01: cancelamento cooperativo sem terminate retorna CANCELLED e preserva Worker/PyProxy limpos", async () => {
  const store = new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() });
  const client = new PyodideEngineClient({ store, cancelGraceMs: 2000, workerFactory: () => createMessageChannelWorkerTransport({ pyodideLoader: fixturePyodideLoader }) });
  try {
    await client.init();

    const genBefore = client.getWorkerGeneration();
    const slowPromise = client.execute(
      makeLqrRequest({
        request_id: "coop-cancel-1",
        project_id: "proj-coop",
        project_revision: 1,
        options: { __delay_ms: 1000 },
      }),
    );
    await new Promise((r) => setTimeout(r, 15));
    const ok = await client.cancel("coop-cancel-1");
    assert.equal(ok, true);

    const resp = await slowPromise;
    assert.equal(resp.status, "failure");
    assert.equal(resp.error?.code, "CANCELLED");
    assert.equal(client.getWorkerGeneration(), genBefore);
    const stats = await client.getWorkerStats();
    assert.equal(stats.pyproxy.activeProxies, 0);
  } finally {
    client.dispose();
  }
});

// ---------------------------------------------------------------------------
// 4. T-SEC-01: Service Worker versionado, política unitária de cache em memória e bloqueio CDN (T-SEC-01 real permanece pendente)
// ---------------------------------------------------------------------------

test("F7-SEC-UNIT: cache em memória e fetch stub exercitam política; não comprovam T-SEC-01 em browser", async () => {
  const cacheStorage = new InMemoryCacheStorage();
  // Simula cache legado de versão anterior e cache de usuário não relacionado
  await cacheStorage.open(`${CACHE_NAME_PREFIX}v0.9.0`);
  await cacheStorage.open("unrelated-app-cache");

  const sw = new ServiceWorkerController({
    origin: "https://controllab.local",
    version: "1.0.0",
  });
  assert.equal(sw.activeCacheName, DEFAULT_STATIC_CACHE_NAME);

  let provisionFetchCalls = 0;
  const provisionFetch = async (req: Request | string): Promise<Response> => {
    provisionFetchCalls += 1;
    const url = typeof req === "string" ? req : req.url;
    return new Response(`/* cached ${url} */`, {
      status: 200,
      headers: { "Content-Type": "application/javascript" },
    });
  };

  const installRes = await sw.install(cacheStorage, provisionFetch);
  assert.equal(installRes.atomic, true);
  assert.equal(installRes.cacheName, "controllab-static-v1.0.0");
  assert.equal(provisionFetchCalls, DEFAULT_STATIC_MANIFEST.length);

  const activateRes = await sw.activate(cacheStorage);
  assert.deepEqual(activateRes.deletedCaches, ["controllab-static-v0.9.0"]);
  assert.ok(activateRes.preservedCaches.includes("unrelated-app-cache"));
  assert.equal(await cacheStorage.has("controllab-static-v0.9.0"), false);

  const readiness = await sw.checkOfflineReadiness(cacheStorage);
  assert.equal(readiness.ready, true);
  assert.equal(readiness.missingUrls.length, 0);

  // Simulação unitária da ausência de rede; não é provisionamento offline real.
  let offlineNetworkCalls = 0;
  const offlineBlockedFetch = async (): Promise<Response> => {
    offlineNetworkCalls += 1;
    throw new Error("Rede desconectada: nenhuma requisição externa permitida!");
  };

  for (const asset of DEFAULT_STATIC_MANIFEST) {
    const resp = await sw.handleFetch(
      `https://controllab.local${asset.url}`,
      cacheStorage,
      offlineBlockedFetch,
    );
    assert.equal(resp.status, 200);
    assert.equal(resp.headers.get("X-ControlLab-Cache"), "HIT");
    assert.equal(resp.headers.get("X-ControlLab-Cache-Version"), "1.0.0");
    const text = await resp.text();
    assert.ok(text.includes(asset.url));
  }
  assert.equal(offlineNetworkCalls, 0);

  // Bloqueio explícito de CDN externa e telemetria mesmo com URL válida
  const cdnResp = await sw.handleFetch(
    "https://cdn.jsdelivr.net/pyodide/v0.27.5/full/pyodide.js",
    cacheStorage,
    offlineBlockedFetch,
  );
  assert.equal(cdnResp.status, 403);
  assert.equal(offlineNetworkCalls, 0);

  const telemetryResp = await sw.handleFetch(
    "https://controllab.local/telemetry/collect",
    cacheStorage,
    offlineBlockedFetch,
  );
  assert.equal(telemetryResp.status, 403);
  assert.equal(offlineNetworkCalls, 0);

  // Atualização atômica com falha mantém versão v1.0.0 intacta
  await assert.rejects(
    () =>
      sw.upgradeVersion(
        "1.0.1",
        [
          { url: "/index.html", kind: "html", version: "1.0.1" },
          { url: "/missing-asset.wasm", kind: "wasm", version: "1.0.1" },
        ],
        cacheStorage,
        async (req) => {
          const u = typeof req === "string" ? req : req.url;
          if (u.includes("missing-asset")) {
            return new Response("Not found", { status: 404 });
          }
          return new Response("ok", { status: 200 });
        },
      ),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "SOLVER_UNAVAILABLE",
  );
  assert.equal(sw.activeCacheName, "controllab-static-v1.0.0");
  assert.equal(await cacheStorage.has("controllab-static-v1.0.0"), true);
  assert.equal(await cacheStorage.has("controllab-static-v1.0.1"), false);
});

test("T-SEC-01 (Worker): Worker Pyodide bloqueia indexURL de CDN externo com IMPORT_UNTRUSTED_CODE", async () => {
  const client = new PyodideEngineClient({
    store: new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() }),
    workerFactory: () => createMessageChannelWorkerTransport({ pyodideLoader: fixturePyodideLoader }),
  });

  try {
    await assert.rejects(
      () =>
        client.init({
          indexURL: "https://cdn.jsdelivr.net/pyodide/v0.27.5/full/",
        }),
      (err: unknown) =>
        err instanceof ControlLabBridgeError &&
        err.code === "IMPORT_UNTRUSTED_CODE",
    );
    assert.equal(client.getLifecycleState(), "error");
  } finally {
    client.dispose();
  }
});

// ---------------------------------------------------------------------------
// 5. Transferência binária de ArrayBuffer (posse/detached vs preserveSenderCopy)
// ---------------------------------------------------------------------------

test("F7-BUFFER-01 (fixture double): transferência de ArrayBuffer via postMessage destaca original (byteLength===0), bloqueia reúso e suporta preserveSenderCopy", async () => {
  const store = new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() });
  const client = new PyodideEngineClient({ store, workerFactory: () => createMessageChannelWorkerTransport({ pyodideLoader: fixturePyodideLoader }) });
  try {
    await client.init();

    const reqExample = JSON.parse(
      fs.readFileSync(path.join(EXAMPLES_DIR, "rpc_request_lqr.json"), "utf8"),
    ) as RpcRequest;

    // Construir buffers Float64 reais para Q (12x12) e R (3x3)
    const qData = new Float64Array(12 * 12);
    for (let i = 0; i < 12; i += 1) qData[i * 12 + i] = 1.0;
    const rData = new Float64Array(3 * 3);
    for (let i = 0; i < 3; i += 1) rData[i * 3 + i] = 1.0;

    const qBuf = qData.buffer;
    const rBuf = rData.buffer;
    assert.equal(qBuf.byteLength, 12 * 12 * 8);
    assert.equal(rBuf.byteLength, 3 * 3 * 8);

    // 1) Modo padrão: move posse via postMessage(..., transferables)
    const respMove = await client.execute(reqExample, {
      buffers: {
        "Q-01": { shape: [12, 12], dtype: "float64", order: "C", buffer: qBuf },
        "R-01": { shape: [3, 3], dtype: "float64", order: "C", buffer: rBuf },
      },
    });
    assert.equal(respMove.status, "success");
    assert.equal(qBuf.byteLength, 0, "ArrayBuffer transferido deve estar destacado (byteLength===0)");
    assert.equal(rBuf.byteLength, 0);

    // Uso pós-transferência é explicitamente bloqueado
    assert.throws(
      () => assertBufferUsable(qBuf, 1, "Q-01"),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
    );
    const reuseResp = await client.execute(
      { ...reqExample, request_id: "reuse-detached", project_revision: 8 },
      {
        buffers: {
          "Q-01": { shape: [12, 12], dtype: "float64", order: "C", buffer: qBuf },
        },
      },
    );
    assert.equal(reuseResp.status, "failure");
    assert.equal(reuseResp.error?.code, "VALIDATION_ERROR");

    // 2) Modo preserveSenderCopy: true mantém buffer do remetente intacto
    const qCopySrc = new Float64Array(12 * 12).fill(2.0).buffer;
    const rCopySrc = new Float64Array(3 * 3).fill(1.0).buffer;
    const respCopy = await client.execute(
      { ...reqExample, request_id: "copy-preserve-1", project_revision: 9 },
      {
        buffers: {
          "Q-01": { shape: [12, 12], dtype: "float64", order: "C", buffer: qCopySrc },
          "R-01": { shape: [3, 3], dtype: "float64", order: "C", buffer: rCopySrc },
        },
        preserveSenderCopy: true,
      },
    );
    assert.equal(respCopy.status, "success");
    assert.equal(qCopySrc.byteLength, 12 * 12 * 8);
    assert.equal(rCopySrc.byteLength, 3 * 3 * 8);

    // Round-trip helper tensorToBinaryBuffer + extractTransferableBuffers
    const wb = tensorToBinaryBuffer("T-01", {
      shape: [2, 2],
      dtype: "float64",
      order: "C",
      data: [1.5, -2.5, 3.0, 4.0],
    });
    const inputs: Record<string, BinaryTensorInput> = {
      "T-01": {
        shape: wb.shape,
        dtype: wb.dtype,
        order: wb.order,
        buffer: wb.buffer,
      },
    };
    const extracted = extractTransferableBuffers(inputs, { preserveSenderCopy: true });
    assert.equal(extracted.transferList.length, 1);
    assert.equal(wb.buffer.byteLength, 32);
  } finally {
    client.dispose();
  }
});

// ---------------------------------------------------------------------------
// 6. Guardião de PyProxy (normal, exceção, cancelamento, anti-egresso)
// ---------------------------------------------------------------------------

test("F7-PYPROXY-01: PyProxyRegistry e withPyProxy garantem destroy() em retorno normal, exceção e cancelamento e proíbem saída por postMessage", async () => {
  const registry = new PyProxyRegistry();
  let destroyCount = 0;

  const mkProxy = (val: unknown): PyProxyLike => ({
    __isPyProxy: true,
    toJs: () => val,
    destroy: () => {
      destroyCount += 1;
    },
  });

  // Retorno normal
  const out = await withPyProxy(
    registry,
    () => mkProxy({ ok: 42 }),
    (p) => p.toJs?.(),
    { label: "normal" },
  );
  assert.deepEqual(out, { ok: 42 });
  assert.equal(destroyCount, 1);
  assert.equal(registry.activeProxies, 0);

  // Exceção
  await assert.rejects(
    () =>
      withPyProxy(
        registry,
        () => mkProxy({}),
        async () => {
          throw new Error("falha sintética Python");
        },
        { label: "exception" },
      ),
    /falha sintética Python/,
  );
  assert.equal(destroyCount, 2);
  assert.equal(registry.activeProxies, 0);

  // Cancelamento via AbortSignal
  const ac = new AbortController();
  await assert.rejects(
    () =>
      withPyProxy(
        registry,
        () => mkProxy({}),
        async () => {
          ac.abort();
          return "never";
        },
        { label: "cancel", signal: ac.signal },
      ),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "CANCELLED",
  );
  assert.equal(destroyCount, 3);
  assert.equal(registry.activeProxies, 0);

  // Bloqueio explícito de egresso de PyProxy via postMessage
  const leaked = mkProxy({});
  registry.track(leaked, "leaked");
  assert.throws(
    () => assertNoPyProxy({ nested: [leaked] }, registry),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "INTERNAL_ERROR",
  );
  let posted = false;
  assert.throws(
    () =>
      safeWorkerPostMessage(
        () => {
          posted = true;
        },
        { result: { proxy: leaked } },
        undefined,
        registry,
      ),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "INTERNAL_ERROR",
  );
  assert.equal(posted, false);
  registry.destroyAll();
  assert.equal(registry.activeProxies, 0);
});

// ---------------------------------------------------------------------------
// 7. WorkerModelStore (LRU, pinning de projeto ativo, RESOURCE_LIMIT pré-alocação)
// ---------------------------------------------------------------------------

test("F7-MODELSTORE-01: WorkerModelStore implementa LRU, pinning de projeto ativo e falha RESOURCE_LIMIT antes de alocar", () => {
  const store = new WorkerModelStore({ maxBytes: 100, maxEntries: 10 });
  store.pinProject("proj-active");

  // Cada entrada tem ~28 bytes -> soma inicial = 84 <= 100
  const objA = store.put("proj-active", "plant", 1, { p: "x".repeat(20) });
  const objB1 = store.put("proj-other", "m1", 1, { a: "a".repeat(20) });
  const objB2 = store.put("proj-other", "m2", 1, { b: "b".repeat(20) });
  assert.equal(objA.byte_size, 28);
  assert.equal(objB1.byte_size, 28);
  assert.equal(objB2.byte_size, 28);

  // Acessa m1 para torná-lo mais recente que m2
  assert.ok(store.get("proj-other", "m1", 1) !== null);

  // Inserir novo objeto de 33 bytes no projeto ativo (84 + 33 = 117 > 100):
  // proj-other/m2 (LRU não pinado) deve ser evictado antes de proj-other/m1 e nunca proj-active!
  store.put("proj-active", "ctrl", 1, { c: "c".repeat(25) });
  assert.equal(store.has("proj-active", "plant", 1), true);
  assert.equal(store.has("proj-active", "ctrl", 1), true);
  assert.equal(store.has("proj-other", "m1", 1), true);
  assert.equal(store.has("proj-other", "m2", 1), false);
  assert.equal(store.getStats().total_bytes, 89);

  // Tentar alocar objeto de 68 bytes quando projeto ativo pinado já ocupa 61 bytes (61 + 68 = 129 > 100)
  // Deve falhar honestamente com RESOURCE_LIMIT ANTES de alocar e sem evictar nem o projeto ativo nem m1!
  assert.throws(
    () =>
      store.put("proj-active", "huge", 1, {
        payload: "x".repeat(56),
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "RESOURCE_LIMIT",
  );
  assert.equal(store.has("proj-active", "plant", 1), true);
  assert.equal(store.has("proj-active", "ctrl", 1), true);
  assert.equal(store.has("proj-other", "m1", 1), true);
  assert.equal(store.has("proj-active", "huge", 1), false);

  // Entrada individual maior que maxBytes também falha antes de alocar
  assert.throws(
    () =>
      store.put("proj-other", "oversized", 1, {
        payload: "z".repeat(120),
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "RESOURCE_LIMIT",
  );

  // Snapshot e reidratação em loja nova
  const snap = store.exportSnapshot();
  const store2 = new WorkerModelStore({ maxBytes: 100, maxEntries: 10 });
  const restoredCount = store2.rehydrateFromSnapshot(snap);
  assert.equal(restoredCount, snap.entries.length);
  assert.deepEqual(store2.get("proj-active", "plant", 1)?.value, { p: "x".repeat(20) });
});

// ---------------------------------------------------------------------------
// 8. Paridade MockWorkerAdapter vs PyodideEngineClient e Snapshot Portátil IndexedDB
// ---------------------------------------------------------------------------

test("F7-PARITY-01 local: mock certificado versus dispatcher CPython real via bridge; não prova Pyodide/Wasm", async () => {
  const checksums = loadChecksums();
  const bCare02Raw = fs.readFileSync(path.join(FIXTURES_DIR, "B-CARE-02.json"), "utf8");
  const bCare12Raw = fs.readFileSync(path.join(FIXTURES_DIR, "B-CARE-12x3.json"), "utf8");
  const bSdpRaw = fs.readFileSync(path.join(FIXTURES_DIR, "B-SDP-A-D.json"), "utf8");

  // Verifica rejeição de fixture com SHA-256 adulterado
  assert.throws(
    () =>
      new MockWorkerAdapter({
        fixtures: {
          "B-CARE-02": { rawJson: bCare02Raw, expectedSha256: "0".repeat(64) },
        },
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );

  const mockStore = new IndexedDBProjectStore({
    idbFactory: new InMemoryIDBFactory(),
    dbName: "parity_mock",
  });
  const pyStore = new IndexedDBProjectStore({
    idbFactory: new InMemoryIDBFactory(),
    dbName: "parity_py",
  });

  const mockClient = new MockWorkerAdapter({
    store: mockStore,
    fixtures: {
      "B-CARE-02": {
        rawJson: bCare02Raw,
        expectedSha256: checksums["B-CARE-02.json"],
      },
      "B-CARE-12x3": {
        rawJson: bCare12Raw,
        expectedSha256: checksums["B-CARE-12x3.json"],
      },
      "B-SDP-A-D": {
        rawJson: bSdpRaw,
        expectedSha256: checksums["B-SDP-A-D.json"],
      },
    },
  });
  const pyClient = new PyodideEngineClient({ store: pyStore, workerFactory: () => createMessageChannelWorkerTransport({ pyodideLoader: cpythonLoader }) });

  try {
    await mockClient.init();
    await pyClient.init();

    const req = makeLqrRequest({
      request_id: "parity-req-1",
      project_id: "proj-parity",
      project_revision: 3,
      payload: (() => {
        const data = JSON.parse(bCare02Raw).data;
        return { A: data.A, B: data.B, Q: data.Q, R: data.R, x0: data.x0, dt: data.dt };
      })(),
    });

    const [mockResp, pyResp] = await Promise.all([
      mockClient.execute(req),
      pyClient.execute(req),
    ]);

    assert.equal(mockResp.status, "success");
    assert.equal(pyResp.status, "success");
    // Compare with F9's unchanged analytic oracle and its own tolerances.
    const oracle = JSON.parse(bCare02Raw);
    for (const name of ["K", "P"] as const) {
      const actual = pyResp.result?.[name] as { data: number[]; shape: number[] };
      const expected = oracle.data.expected[name].data as number[];
      assert.deepEqual(actual.shape, oracle.data.expected[name].shape);
      actual.data.forEach((value: number, i: number) => assert.ok(
        Math.abs(value - expected[i]) <= oracle.tolerances[`${name}_atol`], `${name}[${i}]`,
      ));
    }
    const actualPoles = pyResp.result?.closed_loop_poles as { real: number[]; imag: number[] };
    for (const part of ["real", "imag"] as const) actualPoles[part].forEach((value, i) => assert.ok(
      Math.abs(value - oracle.data.expected.closed_loop_poles[part][i]) <= oracle.tolerances.poles_atol,
    ));
    assert.ok(Math.abs(Number(pyResp.result?.optimal_cost) - Number(mockResp.result?.optimal_cost)) <= oracle.tolerances.cost_atol);

    // Fixture B-SDP-A-D via MockWorkerAdapter
    const sdpResp = await mockClient.execute({
      api_version: RPC_API_VERSION,
      request_id: "sdp-c1",
      project_id: "proj-sdp",
      project_revision: 1,
      operation: "optimization.solve",
      payload: { case_id: "T-SDP-C1" },
      options: {},
      timeout_policy: { hard_timeout_ms: 5000 },
    });
    assert.equal(sdpResp.status, "success");
    assert.equal(sdpResp.diagnostics.certificate_status, "validated_dual");

    // Exportação e reimportação de snapshot portátil no IndexedDBProjectStore
    const exported = await mockClient.exportProject("proj-parity");
    assert.equal(exported.format, "controllab_snapshot");
    assert.equal(exported.project_revision, 3);

    const freshStore = new IndexedDBProjectStore({
      idbFactory: new InMemoryIDBFactory(),
      dbName: "parity_reimport",
    });
    await freshStore.importPortableSnapshot(exported);
    const reimportedProj = await freshStore.getProject("proj-parity");
    assert.equal(reimportedProj?.committed_revision, 3);
    assert.deepEqual(
      reimportedProj?.last_committed_result?.result?.K,
      mockResp.result?.K,
    );

    // Adulteração do snapshot portátil deve falhar verificação de integridade SHA-256
    await assert.rejects(
      () =>
        freshStore.importPortableSnapshot({
          ...exported,
          project_revision: 99,
        }),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
    );
    freshStore.close();
  } finally {
    mockClient.dispose();
    pyClient.dispose();
  }
});

test("F7-PYPROXY-02: erro em runtime Pyodide dentro do Worker destrói PyProxy e mantém activeProxies===0", async () => {
  let proxyDestroyed = 0;
  const client = new PyodideEngineClient({
    store: new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() }),
    workerFactory: () =>
      createMessageChannelWorkerTransport({
        pyodideLoader: makeFixturePyodideLoader({
          destroyed: () => { proxyDestroyed += 1; },
          beforeDispatch: (request) => {
            if (request.operation === "statespace.design_lqr") throw new ControlLabBridgeError(
              "NUMERICAL_INCONCLUSIVE", "Erro numérico injetado em fixture double; não é prova Wasm.",
            );
          },
        }),
      }),
  });

  try {
    await client.init();
    const failResp = await client.execute(
      makeLqrRequest({
        request_id: "py-fail-1",
        project_id: "proj-py-fail",
        project_revision: 1,
      }),
    );
    assert.equal(failResp.status, "failure");
    assert.equal(failResp.error?.code, "NUMERICAL_INCONCLUSIVE");
    assert.equal(proxyDestroyed, 2); // init handshake + failing request

    const stats = await client.getWorkerStats();
    assert.equal(stats.pyproxy.activeProxies, 0);
    assert.equal(stats.pyproxy.totalCreated, 2);
    assert.equal(stats.pyproxy.totalDestroyed, 2);
  } finally {
    client.dispose();
  }
});

test("F7-BUFFER-02 (fixture double): transporte bidirecional Worker -> Main com return_binary_buffers=true reidrata tensores K e P fielmente", async () => {
  const client = new PyodideEngineClient({
    store: new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() }),
    workerFactory: () => createMessageChannelWorkerTransport({ pyodideLoader: fixturePyodideLoader }),
  });

  try {
    await client.init();
    const resp = await client.execute(
      makeLqrRequest({
        request_id: "bin-out-1",
        project_id: "proj-bin-out",
        project_revision: 1,
        options: { return_binary_buffers: true },
      }),
    );
    assert.equal(resp.status, "success");
    const kTensor = resp.result?.K as { data?: number[]; shape?: number[] };
    const pTensor = resp.result?.P as { data?: number[]; shape?: number[] };
    assert.deepEqual(kTensor.shape, [1, 2]);
    assert.deepEqual(kTensor.data, [2.0, 3.0]);
    assert.deepEqual(pTensor.shape, [2, 2]);
    assert.deepEqual(pTensor.data, [6.0, 2.0, 2.0, 3.0]);
  } finally {
    client.dispose();
  }
});

test("F7-SUPERSEDE-TIMEOUT-01: cancel_on_supersede=true cancela revisão anterior em voo e hard_timeout_ms retorna RESOURCE_LIMIT", async () => {
  const store = new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory() });
  const client = new PyodideEngineClient({ store, cancelGraceMs: 2000, workerFactory: () => createMessageChannelWorkerTransport({ pyodideLoader: fixturePyodideLoader }) });
  const cancelledIds: string[] = [];
  client.subscribe((ev) => {
    if (ev.type === "request_cancelled") {
      cancelledIds.push(ev.request_id);
    }
  });

  try {
    await client.init();

    // 1) cancel_on_supersede: true
    const pOld = client.execute(
      makeLqrRequest({
        request_id: "sup-rev1",
        project_id: "proj-sup",
        project_revision: 1,
        options: { __delay_ms: 400 },
        timeout_policy: { hard_timeout_ms: 5000, cancel_on_supersede: true },
      }),
    );
    const pNew = client.execute(
      makeLqrRequest({
        request_id: "sup-rev2",
        project_id: "proj-sup",
        project_revision: 2,
        options: { __delay_ms: 10 },
        timeout_policy: { hard_timeout_ms: 5000, cancel_on_supersede: true },
      }),
    );

    const [rOld, rNew] = await Promise.all([pOld, pNew]);
    assert.equal(rOld.status, "failure");
    assert.equal(rOld.error?.code, "CANCELLED");
    assert.equal(rNew.status, "success");
    assert.ok(cancelledIds.includes("sup-rev1"));
    assert.equal((await store.getProject("proj-sup"))?.committed_revision, 2);

    // 2) hard_timeout_ms expirado retorna RESOURCE_LIMIT
    const timeoutResp = await client.execute(
      makeLqrRequest({
        request_id: "timeout-rev3",
        project_id: "proj-sup",
        project_revision: 3,
        options: { __delay_ms: 500 },
        timeout_policy: { hard_timeout_ms: 25 },
      }),
    );
    assert.equal(timeoutResp.status, "failure");
    assert.equal(timeoutResp.error?.code, "RESOURCE_LIMIT");
  } finally {
    client.dispose();
  }
});

