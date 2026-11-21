/**
 * PyodideEngineClient: cliente RPC v1.0 conectado a Web Worker real ou MessageChannel
 * (CL-DIR-001 Seções 8.1–8.4, 11.1, 13.9, R-01, R-16, R-28, T-RPC-01, T-RPC-02).
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
  extractTransferableBuffers,
  generateUuid,
  isPlainObject,
  rehydrateBufferRefsInRecord,
  RPC_API_VERSION,
  validateRpcResponse,
  verifyPostTransferDetachment,
  type CapabilityDescriptor,
  type RpcRequest,
  type RpcResponse,
} from "./protocol.ts";
import {
  IndexedDBProjectStore,
  type IndexedDBProjectStoreOptions,
} from "../storage/indexeddb_store.ts";
import type { WorkerModelStoreStats } from "../worker/model_store.ts";
import type {
  PyodideWorkerRuntime,
  WorkerInboundMessage,
  WorkerOutboundMessage,
  WorkerLikeTransport,
  WorkerRuntimeOptions,
} from "../worker/pyodide_worker.ts";
import type { PyProxyRegistryStats } from "../worker/pyproxy_guard.ts";

export type WorkerTransportFactory = () => {
  worker: WorkerLikeTransport;
  runtime?: PyodideWorkerRuntime;
};

export interface PyodideEngineClientOptions {
  store?: IndexedDBProjectStore;
  storeOptions?: IndexedDBProjectStoreOptions;
  workerUrl?: string | URL;
  workerFactory?: WorkerTransportFactory;
  workerRuntimeOptions?: Omit<WorkerRuntimeOptions, "postMessage">;
  initOptions?: EngineInitOptions;
  cancelGraceMs?: number;
  autoRecoverOnTimeout?: boolean;
}

interface PendingRpcEntry {
  request: RpcRequest;
  resolve: (result: { response: RpcResponse; bridgeTransferMs?: number }) => void;
  timeoutTimer: ReturnType<typeof setTimeout>;
  cancelTimer?: ReturnType<typeof setTimeout>;
  bridgeTransferMs: number;
  timedOut: boolean;
}

interface PendingControlEntry {
  resolve: (data: Record<string, unknown>) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

function wrapBrowserWorker(nativeWorker: Worker): WorkerLikeTransport {
  const listenerMap = new Map<
    (ev: { data?: unknown; message?: string }) => void,
    EventListener
  >();
  return {
    postMessage(message: unknown, transfer?: ArrayBuffer[]): void {
      if (transfer && transfer.length > 0) {
        nativeWorker.postMessage(message, transfer);
      } else {
        nativeWorker.postMessage(message);
      }
    },
    terminate(): void {
      nativeWorker.terminate();
    },
    addEventListener(type, listener): void {
      const wrapped: EventListener = (rawEv: Event) => {
        if (type === "message") {
          const mev = rawEv as MessageEvent<unknown>;
          listener({ data: mev.data });
        } else {
          const eev = rawEv as ErrorEvent;
          listener({ message: eev.message });
        }
      };
      listenerMap.set(listener, wrapped);
      nativeWorker.addEventListener(type, wrapped);
    },
    removeEventListener(type, listener): void {
      const wrapped = listenerMap.get(listener);
      if (wrapped) {
        nativeWorker.removeEventListener(type, wrapped);
        listenerMap.delete(listener);
      }
    },
  };
}

export class PyodideEngineClient extends BaseEngineClient {
  private readonly workerUrl?: string | URL;
  private readonly workerFactory?: WorkerTransportFactory;
  private readonly workerRuntimeOptions?: Omit<WorkerRuntimeOptions, "postMessage">;
  private readonly defaultInitOptions?: EngineInitOptions;
  private readonly cancelGraceMs: number;
  private readonly autoRecoverOnTimeout: boolean;

  private worker: WorkerLikeTransport | null = null;
  private activeRuntime: PyodideWorkerRuntime | null = null;
  private workerGeneration = 0;
  private workerId: string | null = null;
  private storeInstanceId: string | null = null;
  private capabilities: CapabilityDescriptor | null = null;

  private readonly pendingRpc = new Map<string, PendingRpcEntry>();
  private readonly pendingControl = new Map<string, PendingControlEntry>();
  private initPromise: Promise<CapabilityDescriptor> | null = null;
  private resetPromise: Promise<void> | null = null;

  private messageHandler = (ev: { data?: unknown }) => {
    this.handleWorkerMessage(ev.data);
  };

  private errorHandler = (ev: { message?: string }) => {
    const err = new ControlLabBridgeError(
      "INTERNAL_ERROR",
      `Erro fatal no Web Worker Pyodide: ${ev.message ?? "erro desconhecido"}`,
    );
    this.setLifecycleState("error", err.message);
    this.emitEvent({
      type: "error",
      error: err,
      timestamp: new Date().toISOString(),
    });
  };

  constructor(options?: PyodideEngineClientOptions) {
    super(options?.store ?? new IndexedDBProjectStore(options?.storeOptions));
    this.workerUrl = options?.workerUrl;
    this.workerFactory = options?.workerFactory;
    this.workerRuntimeOptions = options?.workerRuntimeOptions;
    this.defaultInitOptions = options?.initOptions;
    this.cancelGraceMs = options?.cancelGraceMs ?? 250;
    this.autoRecoverOnTimeout = options?.autoRecoverOnTimeout ?? false;
  }

  public getWorkerGeneration(): number {
    return this.workerGeneration;
  }

  public getWorkerIds(): {
    worker_id: string | null;
    store_instance_id: string | null;
  } {
    return {
      worker_id: this.workerId,
      store_instance_id: this.storeInstanceId,
    };
  }

  public getCapabilities(): CapabilityDescriptor {
    if (this.capabilities) {
      return { ...this.capabilities };
    }
    return {
      api_version: RPC_API_VERSION,
      engine_kind: "pyodide",
      runtime_id: this.workerId ?? `pyodide-gen-${this.workerGeneration}`,
      operations: ["worker.ping", "worker.get_stats"],
      backends: {},
      supports_transferables: true,
      supports_cooperative_cancel: false,
      offline_ready: false,
      max_memory_bytes: this.defaultInitOptions?.maxMemoryBytes ?? 64 * 1024 * 1024,
      maturity: {},
      lib_versions: {},
    };
  }

  private spawnWorkerTransport(): WorkerLikeTransport {
    if (this.workerFactory) {
      const created = this.workerFactory();
      this.activeRuntime = created.runtime ?? null;
      return created.worker;
    }
    if (typeof Worker !== "undefined" && this.workerUrl !== undefined) {
      const native = new Worker(this.workerUrl, { type: "module" });
      this.activeRuntime = null;
      return wrapBrowserWorker(native);
    }
    throw new ControlLabBridgeError(
      "SOLVER_UNAVAILABLE",
      "Web Worker module não configurado; a execução científica exige workerUrl e um Worker real.",
      { next_step: "Configure workerUrl após provisionar os assets; workerFactory é injeção explícita para testes." },
    );
  }

  public async init(options?: EngineInitOptions): Promise<CapabilityDescriptor> {
    if (this.getLifecycleState() === "ready" && this.worker !== null && this.capabilities) {
      return this.getCapabilities();
    }
    if (this.initPromise) {
      return this.initPromise;
    }

    const mergedOpts: EngineInitOptions = {
      ...this.defaultInitOptions,
      ...options,
    };

    this.initPromise = this.performInit(mergedOpts, false);
    try {
      return await this.initPromise;
    } finally {
      this.initPromise = null;
    }
  }

  private async verifyOfflineReadiness(options: EngineInitOptions): Promise<boolean> {
    // DedicatedWorkerNavigator does not expose serviceWorker in all browsers.
    // The window verifies the controller and configured runtime after the Python handshake.
    const controller = globalThis.navigator?.serviceWorker?.controller;
    if (this.workerFactory || !this.workerUrl || !controller) return false;
    const base = new URL("./", controller.scriptURL);
    const wheel = new URL("wheels/control_lab-1.0.0-py3-none-any.whl", base).href;
    if (new URL(this.workerUrl, base).href !== new URL("worker/pyodide_worker.js", base).href ||
        controller.scriptURL !== new URL("service_worker.js", base).href ||
        new URL(options.indexURL ?? "/pyodide/", base).href !== new URL("pyodide/", base).href ||
        !(options.packages ?? ["numpy", "scipy", "/wheels/control_lab-1.0.0-py3-none-any.whl"])
          .every((pkg) => pkg === "numpy" || pkg === "scipy" || new URL(pkg, base).href === wheel)) {
      return false;
    }
    const channel = new MessageChannel();
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      return await new Promise<boolean>((resolve) => {
        timeout = setTimeout(() => resolve(false), 8000);
        channel.port1.onmessage = ({ data }) => {
          resolve(data?.ready === true && globalThis.navigator?.serviceWorker?.controller === controller);
        };
        controller.postMessage({ type: "controllab.checkOfflineReadiness" }, [channel.port2]);
      });
    } catch { return false; } finally {
      clearTimeout(timeout);
      channel.port1.close();
      channel.port2.close();
    }
  }

  private async performInit(
    options: EngineInitOptions,
    isRecovery: boolean,
  ): Promise<CapabilityDescriptor> {
    if (!isRecovery) {
      this.setLifecycleState("loading", "init_pyodide_worker");
    }
    try {
      await this.store.open();
      this.worker = this.spawnWorkerTransport();
      this.workerGeneration += 1;
      this.worker.addEventListener("message", this.messageHandler);
      this.worker.addEventListener("error", this.errorHandler);

      const msgId = `init-${generateUuid()}`;
      const initTimeoutMs = options.initTimeoutMs ?? 120000;
      const initResult = await this.sendControlAndWait(
        {
          kind: "init",
          msg_id: msgId,
          config: {
            indexURL: options.indexURL,
            packages: options.packages,
            allowedOrigins: options.allowedOrigins,
            offlineOnly: options.offlineOnly,
            initTimeoutMs,
            storeOptions:
              options.maxMemoryBytes !== undefined || options.maxEntries !== undefined
                ? {
                    maxBytes: options.maxMemoryBytes,
                    maxEntries: options.maxEntries,
                  }
                : undefined,
          },
        },
        initTimeoutMs,
      );

      const timings = initResult.timings as
        | {
            download_ms?: number;
            init_pyodide_ms?: number;
            import_packages_ms?: number;
          }
        | undefined;
      if (!isRecovery) {
        this.metrics.T_download = timings?.download_ms ?? 0;
        this.metrics.T_init_pyodide = timings?.init_pyodide_ms ?? 0;
        this.metrics.T_import_packages = timings?.import_packages_ms ?? 0;
      }

      this.workerId = String(initResult.worker_id ?? "");
      this.storeInstanceId = String(initResult.store_instance_id ?? "");
      this.capabilities = {
        ...initResult.capabilities as CapabilityDescriptor,
        offline_ready: await this.verifyOfflineReadiness(options),
      };

      await this.rehydrateWorkerFromIndexedDB();
      await this.syncCoordinatorFromStore();

      this.setLifecycleState("ready", isRecovery ? "recovered" : "ready");
      return this.getCapabilities();
    } catch (err: unknown) {
      this.capabilities = null;
      const bridgeErr =
        err instanceof ControlLabBridgeError
          ? err
          : new ControlLabBridgeError(
              "INTERNAL_ERROR",
              err instanceof Error ? err.message : String(err),
            );
      this.setLifecycleState("error", bridgeErr.message);
      this.emitEvent({
        type: "error",
        error: bridgeErr,
        timestamp: new Date().toISOString(),
      });
      throw bridgeErr;
    }
  }

  private async rehydrateWorkerFromIndexedDB(): Promise<{
    restored_projects: string[];
    restored_objects: number;
  }> {
    const snapshots = await this.store.getAllLatestConfirmedSnapshots();
    if (snapshots.length === 0) {
      return { restored_projects: [], restored_objects: 0 };
    }
    const res = await this.sendControlAndWait(
      {
        kind: "rehydrate_snapshot",
        msg_id: `rehydrate-${generateUuid()}`,
        snapshots,
        pin_projects: true,
      },
      10000,
    );
    return {
      restored_projects: Array.isArray(res.restored_projects)
        ? (res.restored_projects as string[])
        : [],
      restored_objects:
        typeof res.restored_objects === "number" ? res.restored_objects : 0,
    };
  }

  public async getWorkerStats(): Promise<{
    worker_id: string;
    store: WorkerModelStoreStats;
    pyproxy: PyProxyRegistryStats;
    active_request_ids: string[];
  }> {
    if (!this.worker || this.getLifecycleState() === "uninitialized") {
      await this.init();
    }
    const res = await this.sendControlAndWait(
      {
        kind: "get_stats",
        msg_id: `stats-${generateUuid()}`,
      },
      5000,
    );
    return res as unknown as {
      worker_id: string;
      store: WorkerModelStoreStats;
      pyproxy: PyProxyRegistryStats;
      active_request_ids: string[];
    };
  }

  public async registerObject(
    projectId: string,
    objectId: string,
    revision: number,
    value: Record<string, unknown>,
    options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef> {
    if (!this.worker || this.getLifecycleState() === "uninitialized") {
      await this.init();
    }
    const w = this.worker;
    if (!w) {
      throw new ControlLabBridgeError(
        "WORKER_RESTARTED",
        "Worker não disponível após inicialização.",
      );
    }

    await this.sendControlAndWait(
      {
        kind: "register_object",
        msg_id: `reg-${generateUuid()}`,
        project_id: projectId,
        object_id: objectId,
        revision,
        value,
        object_kind: options?.kind,
        pin_project: options?.pinProject !== false,
      },
      10000,
    );

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
    if (!this.worker || this.getLifecycleState() === "uninitialized") {
      await this.init();
    }
    const res = await this.sendControlAndWait(
      {
        kind: "get_object",
        msg_id: `get-${generateUuid()}`,
        project_id: projectId,
        object_id: objectId,
        revision,
      },
      5000,
    );
    if (res.found === true && isPlainObject(res.entry) && isPlainObject(res.entry.value)) {
      return res.entry.value;
    }
    const persisted = await this.store.getObject(projectId, objectId, revision);
    if (persisted) {
      await this.sendControlAndWait(
        {
          kind: "register_object",
          msg_id: `hydrate-obj-${generateUuid()}`,
          project_id: projectId,
          object_id: objectId,
          revision,
          value: persisted.value,
          object_kind: persisted.kind,
          pin_project: true,
        },
        5000,
      );
      return persisted.value;
    }
    return null;
  }

  public async cancel(
    requestId: string,
    options?: CancelOptions,
  ): Promise<boolean> {
    const pending = this.pendingRpc.get(requestId);
    if (!pending) {
      return false;
    }

    this.emitEvent({
      type: "request_cancelled",
      project_id: pending.request.project_id,
      request_id: requestId,
      reason: options?.reason ?? "cancelled_by_caller",
      timestamp: new Date().toISOString(),
    });

    if (options?.forceTerminate) {
      await this.terminateAndRecover(
        options.reason ?? "forced_cancel_terminate",
        requestId,
      );
      return true;
    }

    try {
      this.worker?.postMessage({
        kind: "cancel",
        request_id: requestId,
        reason: options?.reason,
      } satisfies WorkerInboundMessage);
    } catch {
      // Se Worker já morreu, cai para recuperação
    }

    // Se o Worker estiver bloqueado em tarefa síncrona e não responder dentro de cancelGraceMs,
    // força terminate() + recuperação automática via IndexedDB.
    if (!pending.cancelTimer) {
      pending.cancelTimer = setTimeout(() => {
        if (this.pendingRpc.has(requestId)) {
          void this.terminateAndRecover(
            options?.reason ?? "cooperative_cancel_timeout_terminate",
            requestId,
          );
        }
      }, this.cancelGraceMs);
    }

    return true;
  }

  public async resetWorker(reason = "worker_terminated_and_restarted"): Promise<void> {
    await this.terminateAndRecover(reason);
  }

  private async terminateAndRecover(
    reason: string,
    cancelledRequestId?: string,
  ): Promise<void> {
    if (this.resetPromise) {
      return this.resetPromise;
    }

    this.resetPromise = (async () => {
      this.coalescer.cancelAll();
      this.setLifecycleState("recovering", reason);

      // Destrói transporte atual via terminate()
      const oldWorker = this.worker;
      this.worker = null;
      this.activeRuntime = null;
      if (oldWorker) {
        oldWorker.removeEventListener("message", this.messageHandler);
        oldWorker.removeEventListener("error", this.errorHandler);
        oldWorker.terminate();
      }

      // Resolve todas as chamadas RPC pendentes com CANCELLED (se alvo do cancel) ou WORKER_RESTARTED
      for (const [reqId, pending] of Array.from(this.pendingRpc.entries())) {
        clearTimeout(pending.timeoutTimer);
        if (pending.cancelTimer) {
          clearTimeout(pending.cancelTimer);
        }
        this.pendingRpc.delete(reqId);

        const isCancelledTarget = reqId === cancelledRequestId;
        const code = isCancelledTarget
          ? "CANCELLED"
          : pending.timedOut
            ? "RESOURCE_LIMIT"
            : "WORKER_RESTARTED";
        const message = isCancelledTarget
          ? `Requisição '${reqId}' cancelada com reinício do Worker (${reason}).`
          : `Worker encerrado (terminate) e reiniciado durante execução (${reason}).`;

        pending.resolve({
          response: buildFailureRpcResponse({
            request_id: pending.request.request_id,
            project_id: pending.request.project_id,
            project_revision: pending.request.project_revision,
            code,
            message,
            parameters: { reason, worker_generation: this.workerGeneration },
            algorithm: pending.request.operation,
            lib_versions: this.getCapabilities().lib_versions,
          }),
          bridgeTransferMs: pending.bridgeTransferMs,
        });
      }

      for (const [msgId, ctrl] of Array.from(this.pendingControl.entries())) {
        clearTimeout(ctrl.timer);
        this.pendingControl.delete(msgId);
        ctrl.reject(
          new ControlLabBridgeError(
            "WORKER_RESTARTED",
            `Operação de controle '${msgId}' interrompida por terminate().`,
          ),
        );
      }

      // Recria novo Worker e reidrata a partir do último snapshot confirmado no IndexedDB
      const mergedOpts: EngineInitOptions = { ...this.defaultInitOptions };
      await this.performInit(mergedOpts, true);

      const snapshots = await this.store.getAllLatestConfirmedSnapshots();
      const restoredObjects = snapshots.reduce(
        (acc, s) => acc + s.objects.length,
        0,
      );
      this.emitEvent({
        type: "worker_recovered",
        generation: this.workerGeneration,
        restored_projects: snapshots.map((s) => s.project_id),
        restored_objects: restoredObjects,
        timestamp: new Date().toISOString(),
      });
    })();

    try {
      await this.resetPromise;
    } finally {
      this.resetPromise = null;
    }
  }

  protected async dispatchRpc(
    request: RpcRequest,
    options?: ExecuteOptions,
  ): Promise<{ response: RpcResponse; bridgeTransferMs?: number }> {
    if (this.resetPromise) {
      await this.resetPromise;
    }
    if (!this.worker || this.getLifecycleState() === "uninitialized") {
      await this.init();
    }
    const w = this.worker;
    if (!w) {
      throw new ControlLabBridgeError(
        "WORKER_RESTARTED",
        "Worker não está disponível para despacho RPC.",
      );
    }

    const tBridge0 =
      typeof performance !== "undefined" && typeof performance.now === "function"
        ? performance.now()
        : Date.now();

    let message: WorkerInboundMessage = {
      kind: "rpc_request",
      request,
    };
    let transferList: ArrayBuffer[] = [];

    if (options?.buffers) {
      return new Promise<{ response: RpcResponse; bridgeTransferMs?: number }>(
        (resolve) => {
          let extracted: ReturnType<typeof extractTransferableBuffers>;
          try {
            extracted = extractTransferableBuffers(options.buffers!, {
              preserveSenderCopy: options.preserveSenderCopy,
            });
          } catch (err: unknown) {
            const bErr =
              err instanceof ControlLabBridgeError
                ? err
                : new ControlLabBridgeError(
                    "VALIDATION_ERROR",
                    err instanceof Error ? err.message : String(err),
                  );
            resolve({
              response: buildFailureRpcResponse({
                request_id: request.request_id,
                project_id: request.project_id,
                project_revision: request.project_revision,
                code: bErr.code,
                message: bErr.message,
                parameters: bErr.typedError.parameters,
                next_step: bErr.typedError.next_step,
                algorithm: request.operation,
                lib_versions: this.getCapabilities().lib_versions,
              }),
              bridgeTransferMs: 0,
            });
            return;
          }

          message = {
            kind: "rpc_request",
            request,
            buffers: extracted.binaryEntries,
          };
          transferList = extracted.transferList;

          const tPost0 = tBridge0;
          const timeoutTimer = this.createTimeoutTimer(request);
          this.pendingRpc.set(request.request_id, {
            request,
            resolve,
            timeoutTimer,
            bridgeTransferMs: 0,
            timedOut: false,
          });

          try {
            w.postMessage(message, transferList);
            verifyPostTransferDetachment(extracted);
            const tPost1 =
              typeof performance !== "undefined" &&
              typeof performance.now === "function"
                ? performance.now()
                : Date.now();
            const pendingEntry = this.pendingRpc.get(request.request_id);
            if (pendingEntry) {
              pendingEntry.bridgeTransferMs = Math.max(0, tPost1 - tPost0);
            }
          } catch (err: unknown) {
            clearTimeout(timeoutTimer);
            this.pendingRpc.delete(request.request_id);
            const bErr =
              err instanceof ControlLabBridgeError
                ? err
                : new ControlLabBridgeError(
                    "INTERNAL_ERROR",
                    err instanceof Error ? err.message : String(err),
                  );
            resolve({
              response: buildFailureRpcResponse({
                request_id: request.request_id,
                project_id: request.project_id,
                project_revision: request.project_revision,
                code: bErr.code,
                message: bErr.message,
                parameters: bErr.typedError.parameters,
                next_step: bErr.typedError.next_step,
                algorithm: request.operation,
                lib_versions: this.getCapabilities().lib_versions,
              }),
              bridgeTransferMs: 0,
            });
          }
        },
      );
    }

    return new Promise<{ response: RpcResponse; bridgeTransferMs?: number }>(
      (resolve) => {
        const timeoutTimer = this.createTimeoutTimer(request);
        this.pendingRpc.set(request.request_id, {
          request,
          resolve,
          timeoutTimer,
          bridgeTransferMs: 0,
          timedOut: false,
        });
        try {
          w.postMessage(message);
          const tPost1 =
            typeof performance !== "undefined" &&
            typeof performance.now === "function"
              ? performance.now()
              : Date.now();
          const pendingEntry = this.pendingRpc.get(request.request_id);
          if (pendingEntry) {
            pendingEntry.bridgeTransferMs = Math.max(0, tPost1 - tBridge0);
          }
        } catch (err: unknown) {
          clearTimeout(timeoutTimer);
          this.pendingRpc.delete(request.request_id);
          const bErr =
            err instanceof ControlLabBridgeError
              ? err
              : new ControlLabBridgeError(
                  "WORKER_RESTARTED",
                  err instanceof Error ? err.message : String(err),
                );
          resolve({
            response: buildFailureRpcResponse({
              request_id: request.request_id,
              project_id: request.project_id,
              project_revision: request.project_revision,
              code: bErr.code,
              message: bErr.message,
              algorithm: request.operation,
              lib_versions: this.getCapabilities().lib_versions,
            }),
            bridgeTransferMs: 0,
          });
        }
      },
    );
  }

  private createTimeoutTimer(request: RpcRequest): ReturnType<typeof setTimeout> {
    const hardTimeoutMs = request.timeout_policy.hard_timeout_ms;
    return setTimeout(() => {
      const entry = this.pendingRpc.get(request.request_id);
      if (!entry) {
        return;
      }
      entry.timedOut = true;
      if (this.autoRecoverOnTimeout) {
        void this.terminateAndRecover("hard_timeout_exceeded");
        return;
      }
      void this.cancel(request.request_id, {
        reason: `hard_timeout_ms (${hardTimeoutMs} ms)`,
      });
    }, hardTimeoutMs);
  }

  private sendControlAndWait(
    message: WorkerInboundMessage & { msg_id: string },
    timeoutMs: number,
  ): Promise<Record<string, unknown>> {
    const w = this.worker;
    if (!w) {
      return Promise.reject(
        new ControlLabBridgeError(
          "WORKER_RESTARTED",
          "Worker não instanciado para mensagem de controle.",
        ),
      );
    }

    return new Promise<Record<string, unknown>>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingControl.delete(message.msg_id);
        reject(
          new ControlLabBridgeError(
            "RESOURCE_LIMIT",
            `Timeout de controle no Worker (${message.kind}, ${timeoutMs} ms).`,
          ),
        );
      }, timeoutMs);

      this.pendingControl.set(message.msg_id, { resolve, reject, timer });
      try {
        w.postMessage(message);
      } catch (err: unknown) {
        clearTimeout(timer);
        this.pendingControl.delete(message.msg_id);
        reject(
          err instanceof Error
            ? err
            : new ControlLabBridgeError("INTERNAL_ERROR", String(err)),
        );
      }
    });
  }

  private handleWorkerMessage(rawData: unknown): void {
    if (!isPlainObject(rawData)) {
      return;
    }
    if (rawData.type === "progress") {
      if (
        typeof rawData.request_id === "string" &&
        rawData.request_id.length > 0 &&
        isPlainObject(rawData.progress)
      ) {
        const p = rawData.progress;
        if (
          typeof p.iter === "number" &&
          typeof p.max_iters === "number" &&
          typeof p.gap === "number" &&
          typeof p.primal_res === "number" &&
          typeof p.dual_res === "number" &&
          typeof p.min_eig === "number" &&
          typeof p.alpha === "number" &&
          typeof p.elapsed_ms === "number"
        ) {
          this.emitProgressEvent({
            request_id: rawData.request_id,
            progress: {
              iter: p.iter,
              max_iters: p.max_iters,
              gap: p.gap,
              primal_res: p.primal_res,
              dual_res: p.dual_res,
              min_eig: p.min_eig,
              alpha: p.alpha,
              elapsed_ms: p.elapsed_ms,
            },
          });
        }
      }
      return;
    }
    if (typeof rawData.kind !== "string") {
      return;
    }
    const msg = rawData as WorkerOutboundMessage;

    if (msg.kind === "init_ok") {
      const ctrl = this.pendingControl.get(msg.msg_id);
      if (ctrl) {
        clearTimeout(ctrl.timer);
        this.pendingControl.delete(msg.msg_id);
        ctrl.resolve({
          worker_id: msg.worker_id,
          store_instance_id: msg.store_instance_id,
          capabilities: msg.capabilities,
          timings: msg.timings,
        });
      }
      return;
    }

    if (msg.kind === "init_error") {
      const ctrl = this.pendingControl.get(msg.msg_id);
      if (ctrl) {
        clearTimeout(ctrl.timer);
        this.pendingControl.delete(msg.msg_id);
        ctrl.reject(
          new ControlLabBridgeError(
            msg.error?.code ?? "INTERNAL_ERROR",
            msg.error?.message ?? "Falha ao inicializar Pyodide Worker.",
            {
              parameters: msg.error?.parameters,
              next_step: msg.error?.next_step,
              details: msg.error?.details,
            },
          ),
        );
      }
      return;
    }

    if (msg.kind === "control_ok") {
      const ctrl = this.pendingControl.get(msg.msg_id);
      if (ctrl) {
        clearTimeout(ctrl.timer);
        this.pendingControl.delete(msg.msg_id);
        ctrl.resolve(msg.data);
      }
      return;
    }

    if (msg.kind === "control_error") {
      const ctrl = this.pendingControl.get(msg.msg_id);
      if (ctrl) {
        clearTimeout(ctrl.timer);
        this.pendingControl.delete(msg.msg_id);
        ctrl.reject(
          new ControlLabBridgeError(msg.error.code, msg.error.message, {
            parameters: msg.error.parameters,
            next_step: msg.error.next_step,
            details: msg.error.details,
          }),
        );
      }
      return;
    }

    if (msg.kind === "rpc_response") {
      const rawResp = msg.response;
      const reqId =
        isPlainObject(rawResp) && typeof rawResp.request_id === "string"
          ? rawResp.request_id
          : "";
      const pending = this.pendingRpc.get(reqId);
      if (!pending) {
        return;
      }
      clearTimeout(pending.timeoutTimer);
      if (pending.cancelTimer) {
        clearTimeout(pending.cancelTimer);
      }
      this.pendingRpc.delete(reqId);

      try {
        const valid = validateRpcResponse(rawResp);
        if (pending.timedOut && valid.error?.code === "CANCELLED") {
          pending.resolve({
            response: buildFailureRpcResponse({
              request_id: pending.request.request_id,
              project_id: pending.request.project_id,
              project_revision: pending.request.project_revision,
              code: "RESOURCE_LIMIT",
              message: `Timeout rígido (${pending.request.timeout_policy.hard_timeout_ms} ms) excedido.`,
              parameters: {
                hard_timeout_ms: pending.request.timeout_policy.hard_timeout_ms,
              },
              algorithm: pending.request.operation,
              lib_versions: this.getCapabilities().lib_versions,
            }),
            bridgeTransferMs:
              pending.bridgeTransferMs + (msg.timings?.bridge_serialize_ms ?? 0),
          });
          return;
        }
        let hydrated = valid;
        if (msg.buffers && valid.result !== null) {
          hydrated = validateRpcResponse({
            ...valid,
            result: rehydrateBufferRefsInRecord(valid.result, msg.buffers),
          });
        }
        pending.resolve({
          response: hydrated,
          bridgeTransferMs:
            pending.bridgeTransferMs + (msg.timings?.bridge_serialize_ms ?? 0),
        });
      } catch (err: unknown) {
        const bErr =
          err instanceof ControlLabBridgeError
            ? err
            : new ControlLabBridgeError(
                "INTERNAL_ERROR",
                err instanceof Error ? err.message : String(err),
              );
        pending.resolve({
          response: buildFailureRpcResponse({
            request_id: pending.request.request_id,
            project_id: pending.request.project_id,
            project_revision: pending.request.project_revision,
            code: bErr.code,
            message: bErr.message,
            algorithm: pending.request.operation,
            lib_versions: this.getCapabilities().lib_versions,
          }),
          bridgeTransferMs: pending.bridgeTransferMs,
        });
      }
    }
  }

  public getDebugActiveRuntime(): PyodideWorkerRuntime | null {
    return this.activeRuntime;
  }

  public override dispose(): void {
    super.dispose();
    for (const [reqId, pending] of Array.from(this.pendingRpc.entries())) {
      clearTimeout(pending.timeoutTimer);
      if (pending.cancelTimer) {
        clearTimeout(pending.cancelTimer);
      }
      this.pendingRpc.delete(reqId);
    }
    for (const [msgId, ctrl] of Array.from(this.pendingControl.entries())) {
      clearTimeout(ctrl.timer);
      this.pendingControl.delete(msgId);
    }
    if (this.worker) {
      this.worker.removeEventListener("message", this.messageHandler);
      this.worker.removeEventListener("error", this.errorHandler);
      this.worker.terminate();
      this.worker = null;
    }
    this.activeRuntime = null;
  }
}
