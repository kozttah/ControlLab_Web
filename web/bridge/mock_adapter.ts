/**
 * MockWorkerAdapter compatível com ControlLabEngineClient e contrato RPC v1.0:
 * consome fixtures certificadas com verificação SHA-256 e proveniência,
 * simula latência configurável, respostas fora de ordem, cancelamento,
 * todas as 12 categorias de erro e recuperação pós-terminate() via IndexedDB
 * (CL-DIR-001 Seção 8.3, R-17, T-RPC-01, T-RPC-02).
 */

import {
  BaseEngineClient,
  type CancelOptions,
  type EngineInitOptions,
  type ExecuteOptions,
  type RegisterObjectOptions,
  type RegisteredObjectRef,
} from "./client.ts";
import {
  buildFailureRpcResponse,
  ControlLabBridgeError,
  ensureFiniteJson,
  extractTransferableBuffers,
  isPlainObject,
  rehydrateBinaryBufferToTensor,
  RPC_API_VERSION,
  sha256Hex,
  strictJsonParse,
  validateRpcResponse,
  verifyPostTransferDetachment,
  type CapabilityDescriptor,
  type ErrorCategory,
  type RealTensor,
  type RpcRequest,
  type RpcResponse,
  type WireBinaryBuffer,
} from "./protocol.ts";
import {
  IndexedDBProjectStore,
  type IndexedDBProjectStoreOptions,
} from "../storage/indexeddb_store.ts";
import { materializePayloadReferences } from "../worker/payload_references.ts";
import {
  WorkerModelStore,
  type WorkerModelStoreOptions,
  type WorkerModelStoreStats,
} from "../worker/model_store.ts";

export interface GoldenFixtureInput {
  rawJson: string;
  expectedSha256?: string;
}

export interface MockFixtureBundle {
  "B-CARE-02"?: GoldenFixtureInput | Record<string, unknown>;
  "B-CARE-12x3"?: GoldenFixtureInput | Record<string, unknown>;
  "B-SDP-A-D"?: GoldenFixtureInput | Record<string, unknown>;
}

export interface MockWorkerAdapterOptions {
  store?: IndexedDBProjectStore;
  storeOptions?: IndexedDBProjectStoreOptions;
  workerStoreOptions?: WorkerModelStoreOptions;
  latencyMs?: number;
  latencyByOperation?: Record<string, number>;
  latencyResolver?: (request: RpcRequest) => number;
  fixtures?: MockFixtureBundle;
  libVersions?: Record<string, string>;
}

interface ParsedGoldenFixture {
  fixture_id: string;
  provenance: Record<string, unknown>;
  tolerances: Record<string, number>;
  data: Record<string, unknown>;
  sha256: string;
}

const BUILTIN_B_CARE_02: ParsedGoldenFixture = {
  fixture_id: "B-CARE-02",
  provenance: {
    oracle: "closed_form_analytical_algebra",
    generated_by: "scripts/generate_golden_fixtures.py",
    python_version: "3.11.2",
    lib_versions: { numpy: "2.4.6", scipy: "1.17.1" },
    seed: null,
  },
  tolerances: {
    rCARE_max: 1e-12,
    symmetry_error_max: 1e-14,
  },
  data: {
    feedback_sign: "negative",
    expected: {
      P: { shape: [2, 2], dtype: "float64", order: "C", data: [6.0, 2.0, 2.0, 3.0] },
      K: { shape: [1, 2], dtype: "float64", order: "C", data: [2.0, 3.0] },
      closed_loop_poles: { real: [-2.0, -1.0], imag: [0.0, 0.0] },
      optimal_cost: 13.0,
      rCARE: 0.0,
      symmetry_error: 0.0,
    },
  },
  sha256: "builtin",
};

const BUILTIN_B_CARE_12X3_POLES = {
  real: [
    -2.0817763457266225,
    -1.926643763849002,
    -1.357750048635302,
    -1.1252128780228765,
    -1.1252128780228765,
    -1.119938291857983,
    -1.119938291857983,
    -0.446660755257946,
    -0.446660755257946,
    -0.4138559794842961,
    -0.3700840351985709,
    -0.3700840351985709,
  ],
  imag: [
    0.0,
    0.0,
    0.0,
    -1.950233802490095,
    1.950233802490095,
    -2.3081647974592108,
    2.3081647974592108,
    -1.1619977182149155,
    1.1619977182149155,
    0.0,
    -1.622711637365418,
    1.622711637365418,
  ],
};

function parseCertifiedFixture(
  expectedId: string,
  input: GoldenFixtureInput | Record<string, unknown>,
): ParsedGoldenFixture {
  let parsed: Record<string, unknown>;
  let actualHash: string;

  if ("rawJson" in input && typeof input.rawJson === "string") {
    actualHash = sha256Hex(input.rawJson);
    if (
      typeof input.expectedSha256 === "string" &&
      input.expectedSha256.trim().toLowerCase() !== actualHash
    ) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Checksum SHA-256 inválido para fixture certificada '${expectedId}'.`,
        {
          parameters: {
            fixture_id: expectedId,
            expected: input.expectedSha256,
            actual: actualHash,
          },
        },
      );
    }
    const rawParsed = strictJsonParse(input.rawJson);
    if (!isPlainObject(rawParsed)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Fixture '${expectedId}' deve ser objeto JSON.`,
      );
    }
    parsed = rawParsed;
  } else {
    parsed = ensureFiniteJson(input as Record<string, unknown>, `$.fixture['${expectedId}']`);
    actualHash = sha256Hex(JSON.stringify(parsed));
  }

  if (parsed.fixture_id !== expectedId) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `fixture_id divergente: esperado '${expectedId}', recebido '${String(parsed.fixture_id)}'.`,
    );
  }
  return {
    fixture_id: String(parsed.fixture_id),
    provenance: isPlainObject(parsed.provenance) ? parsed.provenance : {},
    tolerances: isPlainObject(parsed.tolerances)
      ? (parsed.tolerances as Record<string, number>)
      : {},
    data: isPlainObject(parsed.data) ? parsed.data : {},
    sha256: actualHash,
  };
}

function delayCancellable(ms: number, signal: AbortSignal): Promise<void> {
  if (ms <= 0) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new ControlLabBridgeError("CANCELLED", "Requisição cancelada no MockWorkerAdapter."));
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new ControlLabBridgeError("CANCELLED", "Requisição cancelada no MockWorkerAdapter."));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export class MockWorkerAdapter extends BaseEngineClient {
  private readonly defaultLatencyMs: number;
  private readonly latencyByOperation: Record<string, number>;
  private readonly latencyResolver?: (request: RpcRequest) => number;
  private readonly workerStoreOptions?: WorkerModelStoreOptions;
  private readonly libVersions: Record<string, string>;
  private readonly fixtures = new Map<string, ParsedGoldenFixture>();
  private workerStore: WorkerModelStore;
  private workerGeneration = 0;
  private readonly inFlight = new Map<
    string,
    { abortController: AbortController; request: RpcRequest }
  >();

  constructor(options?: MockWorkerAdapterOptions) {
    super(options?.store ?? new IndexedDBProjectStore(options?.storeOptions));
    this.defaultLatencyMs = options?.latencyMs ?? 0;
    this.latencyByOperation = options?.latencyByOperation ?? {};
    this.latencyResolver = options?.latencyResolver;
    this.workerStoreOptions = options?.workerStoreOptions;
    this.libVersions = options?.libVersions ?? {
      numpy: "2.4.6",
      scipy: "1.17.1",
    };
    this.workerStore = new WorkerModelStore(this.workerStoreOptions);
    this.fixtures.set("B-CARE-02", BUILTIN_B_CARE_02);
    if (options?.fixtures) {
      this.loadCertifiedFixtures(options.fixtures);
    }
  }

  public loadCertifiedFixtures(bundle: MockFixtureBundle): void {
    if (bundle["B-CARE-02"]) {
      this.fixtures.set(
        "B-CARE-02",
        parseCertifiedFixture("B-CARE-02", bundle["B-CARE-02"]),
      );
    }
    if (bundle["B-CARE-12x3"]) {
      this.fixtures.set(
        "B-CARE-12x3",
        parseCertifiedFixture("B-CARE-12x3", bundle["B-CARE-12x3"]),
      );
    }
    if (bundle["B-SDP-A-D"]) {
      this.fixtures.set(
        "B-SDP-A-D",
        parseCertifiedFixture("B-SDP-A-D", bundle["B-SDP-A-D"]),
      );
    }
  }

  public getWorkerGeneration(): number {
    return this.workerGeneration;
  }

  public getWorkerStoreStats(): WorkerModelStoreStats {
    return this.workerStore.getStats();
  }

  public getCapabilities(): CapabilityDescriptor {
    return {
      api_version: RPC_API_VERSION,
      engine_kind: "mock",
      runtime_id: `mock-worker-gen-${this.workerGeneration}`,
      operations: [
        "statespace.design_lqr",
        "statespace.analyze",
        "statespace.check_pbh",
        "statespace.solve_care",
        "statespace.solve_dare",
        "statespace.solve_lyapunov",
        "statespace.simulate_lti",
        "optimization.solve",
        "optimization.verify",
        "worker.ping",
        "worker.get_stats",
      ],
      backends: {
        mock_certified_fixtures: { available: true, maturity: "beta" },
        clarabel_cvxpy: { available: false, maturity: "unavailable_wasm" },
      },
      supports_transferables: true,
      supports_cooperative_cancel: true,
      offline_ready: false,
      max_memory_bytes: this.workerStore.getStats().max_bytes,
      maturity: {
        "statespace.design_lqr": "beta",
        "statespace.analyze": "beta",
        "statespace.check_pbh": "beta",
        "statespace.solve_care": "beta",
        "statespace.solve_dare": "beta",
        "statespace.solve_lyapunov": "beta",
        "statespace.simulate_lti": "beta",
        "optimization.solve": "beta",
        "optimization.verify": "beta",
      },
      lib_versions: { ...this.libVersions },
    };
  }

  public async init(options?: EngineInitOptions): Promise<CapabilityDescriptor> {
    if (this.getLifecycleState() === "ready") {
      return this.getCapabilities();
    }
    this.setLifecycleState("loading", "init_mock_adapter");
    try {
      await this.store.open();
      if (options?.maxMemoryBytes !== undefined || options?.maxEntries !== undefined) {
        this.workerStore = new WorkerModelStore({
          maxBytes: options.maxMemoryBytes,
          maxEntries: options.maxEntries,
        });
      }
      this.workerGeneration += 1;
      await this.rehydrateAllFromStore();
      await this.syncCoordinatorFromStore();
      this.metrics.T_download = 0;
      this.metrics.T_init_pyodide = 0;
      this.metrics.T_import_packages = 0;
      this.setLifecycleState("ready", "mock_ready");
      return this.getCapabilities();
    } catch (err: unknown) {
      this.setLifecycleState("error", err instanceof Error ? err.message : String(err));
      throw err;
    }
  }

  public async registerObject(
    projectId: string,
    objectId: string,
    revision: number,
    value: Record<string, unknown>,
    options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef> {
    if (this.getLifecycleState() === "uninitialized") {
      await this.init();
    }
    if (options?.pinProject !== false) {
      this.workerStore.pinProject(projectId);
    }
    this.workerStore.put(projectId, objectId, revision, value, {
      kind: options?.kind,
    });
    let persisted = false;
    if (options?.persistToIndexedDB !== false) {
      await this.store.putObject(projectId, objectId, revision, value, {
        kind: options?.kind,
      });
      persisted = true;
    }
    return {
      project_id: projectId,
      object_id: objectId,
      revision,
      persisted,
      cached_in_worker: true,
    };
  }

  public async getObject(
    projectId: string,
    objectId: string,
    revision: number,
  ): Promise<Record<string, unknown> | null> {
    if (this.getLifecycleState() === "uninitialized") {
      await this.init();
    }
    const cached = this.workerStore.get(projectId, objectId, revision);
    if (cached) {
      return cached.value;
    }
    const persisted = await this.store.getObject(projectId, objectId, revision);
    if (persisted) {
      this.workerStore.put(projectId, objectId, revision, persisted.value, {
        kind: persisted.kind,
        createdAt: persisted.created_at,
      });
      return persisted.value;
    }
    return null;
  }

  public async cancel(
    requestId: string,
    options?: CancelOptions,
  ): Promise<boolean> {
    const active = this.inFlight.get(requestId);
    if (!active) {
      return false;
    }
    active.abortController.abort();
    this.emitEvent({
      type: "request_cancelled",
      project_id: active.request.project_id,
      request_id: requestId,
      reason: options?.reason ?? "cancelled_by_caller",
      timestamp: new Date().toISOString(),
    });
    if (options?.forceTerminate) {
      await this.resetWorker(options.reason ?? "forced_cancel_terminate");
    }
    return true;
  }

  public override dispose(): void {
    super.dispose();
    for (const item of this.inFlight.values()) {
      item.abortController.abort();
    }
    this.inFlight.clear();
  }

  public async resetWorker(reason = "worker_terminated_and_restarted"): Promise<void> {
    this.coalescer.cancelAll();
    this.setLifecycleState("recovering", reason);

    // Interrompe todas as requisições em voo com erro tipado WORKER_RESTARTED
    for (const [reqId, item] of Array.from(this.inFlight.entries())) {
      item.abortController.abort(
        new ControlLabBridgeError(
          "WORKER_RESTARTED",
          `MockWorker encerrado durante execução (${reason}).`,
          { parameters: { request_id: reqId, reason } },
        ),
      );
    }
    this.inFlight.clear();

    // Simula perda completa de RAM do Worker e recriação do WorkerModelStore vazio
    this.workerStore = new WorkerModelStore(this.workerStoreOptions);
    this.workerGeneration += 1;

    const { restoredProjects, restoredObjects } = await this.rehydrateAllFromStore();
    await this.syncCoordinatorFromStore();

    this.setLifecycleState("ready", reason);
    this.emitEvent({
      type: "worker_recovered",
      generation: this.workerGeneration,
      restored_projects: restoredProjects,
      restored_objects: restoredObjects,
      timestamp: new Date().toISOString(),
    });
  }

  private async rehydrateAllFromStore(): Promise<{
    restoredProjects: string[];
    restoredObjects: number;
  }> {
    const snapshots = await this.store.getAllLatestConfirmedSnapshots();
    let restoredObjects = 0;
    const restoredProjects: string[] = [];
    for (const snap of snapshots) {
      restoredObjects += this.workerStore.rehydrateFromIndexedDBSnapshot(snap, {
        pinProject: true,
      });
      restoredProjects.push(snap.project_id);
    }
    return { restoredProjects, restoredObjects };
  }

  protected async dispatchRpc(
    request: RpcRequest,
    options?: ExecuteOptions,
  ): Promise<{ response: RpcResponse; bridgeTransferMs?: number }> {
    const tBridge0 =
      typeof performance !== "undefined" && typeof performance.now === "function"
        ? performance.now()
        : Date.now();

    let resolvedBuffers: Record<string, WireBinaryBuffer> = {};
    if (options?.buffers) {
      const extracted = extractTransferableBuffers(options.buffers, {
        preserveSenderCopy: options.preserveSenderCopy,
      });
      const cloned = structuredClone(extracted.binaryEntries, {
        transfer: extracted.transferList,
      });
      verifyPostTransferDetachment(extracted);
      resolvedBuffers = cloned;
    }

    const tBridge1 =
      typeof performance !== "undefined" && typeof performance.now === "function"
        ? performance.now()
        : Date.now();
    const bridgeTransferMs = Math.max(0, tBridge1 - tBridge0);

    const abortController = new AbortController();
    this.inFlight.set(request.request_id, {
      abortController,
      request,
    });

    const configuredLatency =
      typeof request.options.__delay_ms === "number"
        ? request.options.__delay_ms
        : this.latencyResolver
          ? this.latencyResolver(request)
          : (this.latencyByOperation[request.operation] ?? this.defaultLatencyMs);

    const hardTimeoutMs = request.timeout_policy.hard_timeout_ms;
    let timedOut = false;
    const timeoutTimer = setTimeout(() => {
      timedOut = true;
      abortController.abort(
        new ControlLabBridgeError(
          "RESOURCE_LIMIT",
          `Hard timeout de ${hardTimeoutMs} ms excedido para '${request.request_id}'.`,
          { parameters: { hard_timeout_ms: hardTimeoutMs } },
        ),
      );
    }, hardTimeoutMs);

    try {
      await delayCancellable(configuredLatency, abortController.signal);

      if (abortController.signal.aborted) {
        throw abortController.signal.reason instanceof ControlLabBridgeError
          ? abortController.signal.reason
          : new ControlLabBridgeError(
              "CANCELLED",
              `Requisição '${request.request_id}' cancelada.`,
            );
      }

      const simError = request.options.__simulate_error;
      if (typeof simError === "string") {
        throw new ControlLabBridgeError(
          simError as ErrorCategory,
          `Erro simulado '${simError}' no MockWorkerAdapter.`,
          {
            parameters: { simulated: true, operation: request.operation },
            next_step: "Verifique os parâmetros ou estado simulado.",
          },
        );
      }

      const simStaleRev = request.options.__simulate_stale_revision;
      const responseRevision =
        typeof simStaleRev === "number" && Number.isInteger(simStaleRev) && simStaleRev >= 0
          ? simStaleRev
          : request.project_revision;

      const resolvedPayload = this.resolvePayloadWithBuffersAndStore(
        request,
        resolvedBuffers,
      );

      const response = this.computeMockResponse(
        request,
        responseRevision,
        resolvedPayload,
      );
      return { response: validateRpcResponse(response), bridgeTransferMs };
    } catch (err: unknown) {
      const reason = abortController.signal.reason;
      const bridgeErr = timedOut
        ? new ControlLabBridgeError(
            "RESOURCE_LIMIT",
            `Timeout rígido (${hardTimeoutMs} ms) excedido.`,
            { parameters: { hard_timeout_ms: hardTimeoutMs } },
          )
        : reason instanceof ControlLabBridgeError
          ? reason
          : err instanceof ControlLabBridgeError
            ? err
            : new ControlLabBridgeError(
                "INTERNAL_ERROR",
                err instanceof Error ? err.message : String(err),
              );

      return {
        response: buildFailureRpcResponse({
          request_id: request.request_id,
          project_id: request.project_id,
          project_revision: request.project_revision,
          code: bridgeErr.code,
          message: bridgeErr.message,
          parameters: bridgeErr.typedError.parameters,
          next_step: bridgeErr.typedError.next_step,
          details: bridgeErr.typedError.details,
          algorithm: request.operation,
          lib_versions: { ...this.libVersions },
        }),
        bridgeTransferMs,
      };
    } finally {
      clearTimeout(timeoutTimer);
      this.inFlight.delete(request.request_id);
    }
  }

  private resolvePayloadWithBuffersAndStore(
    request: RpcRequest,
    buffers: Record<string, WireBinaryBuffer>,
  ): Record<string, unknown> {
    const resolved = structuredClone(request.payload);
    const tensorMap: Record<string, unknown> = {};
    for (const [k, wb] of Object.entries(buffers)) {
      tensorMap[k] = rehydrateBinaryBufferToTensor(wb);
    }
    const replaceRefs = (node: unknown): unknown => {
      if (Array.isArray(node)) {
        return node.map(replaceRefs);
      }
      if (isPlainObject(node)) {
        if (
          typeof node.buffer_ref === "string" &&
          node.buffer_ref in tensorMap &&
          Object.keys(node).length === 4
        ) {
          return tensorMap[node.buffer_ref];
        }
        const out: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(node)) {
          out[k] = replaceRefs(v);
        }
        return out;
      }
      return node;
    };
    const withBuffers = replaceRefs(resolved) as Record<string, unknown>;

    return materializePayloadReferences(request, withBuffers, this.workerStore);
  }

  private computeMockResponse(
    request: RpcRequest,
    responseRevision: number,
    payload: Record<string, unknown>,
  ): RpcResponse {
    if (request.operation === "worker.ping") {
      return {
        api_version: RPC_API_VERSION,
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: responseRevision,
        status: "success",
        result: {
          pong: true,
          engine_kind: "mock",
          worker_generation: this.workerGeneration,
          store_instance_id: this.workerStore.storeInstanceId,
        },
        assumptions: {},
        diagnostics: { store_stats: this.workerStore.getStats() },
        provenance: {
          algorithm: "worker.ping",
          lib_versions: { ...this.libVersions },
        },
        warnings: [],
        error: null,
      };
    }

    if (request.operation === "statespace.design_lqr") {
      return this.runMockDesignLqr(request, responseRevision, payload);
    }

    if (
      request.operation === "statespace.analyze" ||
      request.operation === "statespace.check_pbh"
    ) {
      return this.runMockAnalyze(request, responseRevision, payload);
    }

    if (
      request.operation === "optimization.solve" ||
      request.operation === "optimization.verify"
    ) {
      return this.runMockOptimization(request, responseRevision, payload);
    }

    if (
      request.operation === "statespace.solve_care" ||
      request.operation === "statespace.solve_dare" ||
      request.operation === "statespace.solve_lyapunov" ||
      request.operation === "statespace.simulate_lti"
    ) {
      const bCare02 = this.fixtures.get("B-CARE-02") ?? BUILTIN_B_CARE_02;
      const expected = bCare02.data.expected as Record<string, unknown>;
      return {
        api_version: RPC_API_VERSION,
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: responseRevision,
        status: "success",
        result: ensureFiniteJson(expected, "$.result"),
        assumptions: { stabilizable: true, detectable: true },
        diagnostics: { residual_rel: 0.0, symmetry_error: 0.0 },
        provenance: {
          algorithm: request.operation,
          lib_versions: { ...this.libVersions },
          fixture_id: bCare02.fixture_id,
          fixture_sha256: bCare02.sha256,
        },
        warnings: [],
        error: null,
      };
    }

    throw new ControlLabBridgeError(
      "UNSUPPORTED_MODEL",
      `Operação '${request.operation}' não suportada pelo MockWorkerAdapter.`,
      { parameters: { operation: request.operation } },
    );
  }

  private runMockDesignLqr(
    request: RpcRequest,
    responseRevision: number,
    payload: Record<string, unknown>,
  ): RpcResponse {
    if (request.options.uncontrollable_mode === true) {
      throw new ControlLabBridgeError(
        "HYPOTHESIS_VIOLATED",
        "Par (A, B) não é estabilizável segundo teste PBH.",
        {
          parameters: { stabilizable: false },
          next_step: "Verifique a controlabilidade dos modos instáveis.",
        },
      );
    }

    const qObj = payload.Q as Partial<RealTensor> | undefined;
    const rObj = payload.R as Partial<RealTensor> | undefined;
    if (qObj && Array.isArray(qObj.shape)) {
      if (qObj.shape.length !== 2 || qObj.shape[0] !== qObj.shape[1]) {
        throw new ControlLabBridgeError(
          "DIMENSION_MISMATCH",
          `Matriz Q deve ser quadrada (n, n), recebido shape [${qObj.shape.join(",")}].`,
        );
      }
    }
    if (rObj && Array.isArray(rObj.data) && rObj.data.length > 0 && rObj.data[0] <= 0) {
      throw new ControlLabBridgeError(
        "HYPOTHESIS_VIOLATED",
        "Matriz R não é definida positiva (R > 0 requerido para LQR).",
      );
    }

    const nStates =
      qObj && Array.isArray(qObj.shape) && typeof qObj.shape[0] === "number"
        ? qObj.shape[0]
        : 12;

    const plantRef = payload.plant as
      | { id?: string; revision?: number }
      | undefined;
    const modelRev = typeof plantRef?.revision === "number" ? plantRef.revision : 3;

    if (nStates === 12) {
      const f12 = this.fixtures.get("B-CARE-12x3");
      const poles = f12
        ? ((f12.data.expected as Record<string, unknown>).closed_loop_poles as Record<
            string,
            unknown
          >)
        : BUILTIN_B_CARE_12X3_POLES;
      const rCare = f12
        ? ((f12.data.expected as Record<string, unknown>).rCARE as number)
        : 1.2913794169329007e-15;
      const symErr = f12
        ? ((f12.data.expected as Record<string, unknown>).symmetry_error as number)
        : 0.0;

      return {
        api_version: RPC_API_VERSION,
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: responseRevision,
        status: "success",
        result: {
          controller_ref: {
            id: "ctrl-lqr-001",
            revision: 1,
          },
          controller_kind: "StateFeedbackController",
          feedback_sign: "negative",
          closed_loop_poles: poles,
        },
        assumptions: {
          stabilizable: true,
          detectable: true,
          R_positive_definite: true,
        },
        diagnostics: {
          care_residual_rel: rCare,
          symmetry_error: symErr,
        },
        provenance: {
          algorithm: "mock.certified_fixture.care",
          lib_versions: { ...this.libVersions },
          model_revision: modelRev,
          ...(f12 ? { fixture_id: f12.fixture_id, fixture_sha256: f12.sha256 } : {}),
        },
        warnings: [],
        error: null,
      };
    }

    const f02 = this.fixtures.get("B-CARE-02") ?? BUILTIN_B_CARE_02;
    const exp02 = f02.data.expected as Record<string, unknown>;
    return {
      api_version: RPC_API_VERSION,
      request_id: request.request_id,
      project_id: request.project_id,
      project_revision: responseRevision,
      status: "success",
      result: {
        controller_ref: {
          id: `ctrl-lqr-rev${responseRevision}`,
          revision: 1,
        },
        controller_kind: "StateFeedbackController",
        feedback_sign: "negative",
        K: exp02.K,
        P: exp02.P,
        closed_loop_poles: exp02.closed_loop_poles,
        optimal_cost: exp02.optimal_cost,
      },
      assumptions: {
        stabilizable: true,
        detectable: true,
        R_positive_definite: true,
      },
      diagnostics: {
        care_residual_rel: exp02.rCARE ?? 0.0,
        symmetry_error: exp02.symmetry_error ?? 0.0,
      },
      provenance: {
        algorithm: "mock.certified_fixture.care",
        lib_versions: { ...this.libVersions },
        model_revision: modelRev,
        fixture_id: f02.fixture_id,
        fixture_sha256: f02.sha256,
      },
      warnings: [],
      error: null,
    };
  }

  private runMockAnalyze(
    request: RpcRequest,
    responseRevision: number,
    payload: Record<string, unknown>,
  ): RpcResponse {
    const f12 = this.fixtures.get("B-CARE-12x3");
    const openLoopPoles =
      f12 && isPlainObject(f12.data.expected) && f12.data.expected.open_loop_poles
        ? f12.data.expected.open_loop_poles
        : { real: [0.0, 0.0], imag: [0.0, 0.0] };
    const plantRef = payload.plant as { revision?: number } | undefined;
    return {
      api_version: RPC_API_VERSION,
      request_id: request.request_id,
      project_id: request.project_id,
      project_revision: responseRevision,
      status: "success",
      result: {
        open_loop_poles: openLoopPoles,
        controllable: true,
        stabilizable: true,
        observable: true,
        detectable: true,
      },
      assumptions: {
        domain: "continuous",
        stabilizable: true,
        detectable: true,
      },
      diagnostics: {
        min_sv_controllability: 0.1,
        min_sv_observability: 0.1,
      },
      provenance: {
        algorithm: request.operation,
        lib_versions: { ...this.libVersions },
        model_revision: plantRef?.revision ?? null,
      },
      warnings: [],
      error: null,
    };
  }

  private runMockOptimization(
    request: RpcRequest,
    responseRevision: number,
    payload: Record<string, unknown>,
  ): RpcResponse {
    const sdpFixture = this.fixtures.get("B-SDP-A-D");
    if (!sdpFixture) {
      throw new ControlLabBridgeError(
        "SOLVER_UNAVAILABLE",
        "Fixture certificada B-SDP-A-D não carregada no MockWorkerAdapter.",
      );
    }
    const cases = isPlainObject(sdpFixture.data.cases)
      ? (sdpFixture.data.cases as Record<string, unknown>)
      : {};
    const caseId =
      typeof payload.case_id === "string" ? payload.case_id : "T-SDP-C1";
    const selectedCase = cases[caseId];
    if (!isPlainObject(selectedCase)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Caso SDP desconhecido na fixture B-SDP-A-D: '${caseId}'.`,
      );
    }
    const expected = isPlainObject(selectedCase.expected)
      ? selectedCase.expected
      : {};
    return {
      api_version: RPC_API_VERSION,
      request_id: request.request_id,
      project_id: request.project_id,
      project_revision: responseRevision,
      status: "success",
      result: ensureFiniteJson(expected, "$.result"),
      assumptions: {
        case_id: caseId,
        level: selectedCase.level ?? "C",
      },
      diagnostics: {
        solver_status: expected.solver_status ?? "optimal",
        audit_feasibility: expected.audit_feasibility ?? "approximately_feasible",
        certificate_status: expected.certificate_status ?? "validated_dual",
        controller_validity: expected.controller_validity ?? "not_applicable",
      },
      provenance: {
        algorithm: "mock.b_sdp_a_d_fixture",
        lib_versions: { ...this.libVersions },
        fixture_id: sdpFixture.fixture_id,
        fixture_sha256: sdpFixture.sha256,
      },
      warnings: [],
      error: null,
    };
  }
}
