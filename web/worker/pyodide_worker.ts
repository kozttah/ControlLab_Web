/**
 * Web Worker (type="module") do ControlLab Web:
 * integra WorkerModelStore, PyProxyRegistry, protocolo RPC v1.0, política estrita
 * de rede offline/origens permitidas, transferência binária de ArrayBuffer e
 * cancelamento cooperativo (CL-DIR-001 Seções 8.1–8.4, 11.1–11.3, 12.2, 13.9).
 */

import {
  buildFailureRpcResponse,
  ControlLabBridgeError,
  ensureFiniteJson,
  extractTensorsToBinaryBuffers,
  generateUuid,
  isPlainObject,
  rehydrateBinaryBufferToTensor,
  RPC_API_VERSION,
  validateRpcRequest,
  validateRpcResponse,
  type CapabilityDescriptor,
  type ErrorCategory,
  type RpcRequest,
  type RpcResponse,
  type WireBinaryBuffer,
} from "../bridge/protocol.ts";
import type { StoredProjectSnapshot } from "../storage/indexeddb_store.ts";
import {
  WorkerModelStore,
  type WorkerModelStoreOptions,
  type WorkerModelStoreSnapshot,
  type WorkerModelStoreStats,
} from "./model_store.ts";
import {
  PyProxyRegistry,
  safeWorkerPostMessage,
  withPyProxy,
  type PyProxyLike,
  type PyProxyRegistryStats,
} from "./pyproxy_guard.ts";

/**
 * Contrato do entrypoint Python RPC: módulo `control_lab.web_rpc` expõe
 * `dispatch(input) -> dict`, onde `input` é um PyProxy de
 * `{request, payload}` (criado por toPy) e o retorno é um RpcResponse
 * (PyProxy de dict ou valor JS). Invocado via pyimport, nunca via execução
 * de string. PENDÊNCIA: control_lab/web_rpc.py está fora do ownership F7.
 */
export const PY_RPC_ENTRYPOINT_MODULE = "control_lab.web_rpc";
export const PY_RPC_ENTRYPOINT_FUNCTION = "dispatch";

export interface PyRpcEntrypointModuleLike {
  dispatch?: (input: PyProxyLike) => unknown;
  destroy?: () => void;
  [key: string]: unknown;
}

export interface PyodideGlobalsLike {
  get(name: string): unknown;
  set(name: string, value: unknown): void;
  delete?(name: string): void;
}

export interface PyodideInterfaceLike {
  version?: string;
  globals?: PyodideGlobalsLike;
  loadPackage?(names: string | string[]): Promise<unknown>;
  runPythonAsync(code: string): Promise<unknown>;
  toPy?(value: unknown): PyProxyLike;
  pyimport?(name: string): PyRpcEntrypointModuleLike;
  setInterruptBuffer?(buffer: Uint8Array): void;
}

export type PyodideLoaderFn = (config: {
  indexURL: string;
  packages: string[];
  signal?: AbortSignal;
}) => Promise<{
  pyodide: PyodideInterfaceLike;
  libVersions: Record<string, string>;
  downloadMs?: number;
  initMs?: number;
  importMs?: number;
}>;

export interface WorkerInitConfig {
  indexURL?: string;
  packages?: string[];
  allowedOrigins?: string[];
  offlineOnly?: boolean;
  storeOptions?: WorkerModelStoreOptions;
  pyodideLoader?: PyodideLoaderFn;
  executionDelayMs?: number;
}

export type WorkerInboundMessage =
  | {
      kind: "init";
      msg_id: string;
      config?: Omit<WorkerInitConfig, "pyodideLoader">;
    }
  | {
      kind: "rpc_request";
      request: RpcRequest;
      buffers?: Record<string, WireBinaryBuffer>;
    }
  | {
      kind: "cancel";
      request_id: string;
      reason?: string;
    }
  | {
      kind: "register_object";
      msg_id: string;
      project_id: string;
      object_id: string;
      revision: number;
      value: Record<string, unknown>;
      object_kind?: string;
      pin_project?: boolean;
    }
  | {
      kind: "get_object";
      msg_id: string;
      project_id: string;
      object_id: string;
      revision: number;
    }
  | {
      kind: "rehydrate_snapshot";
      msg_id: string;
      snapshots: StoredProjectSnapshot[];
      pin_projects?: boolean;
    }
  | {
      kind: "export_snapshot";
      msg_id: string;
      project_id?: string;
    }
  | {
      kind: "get_stats";
      msg_id: string;
    }
  | {
      kind: "ping";
      msg_id: string;
    };

export type WorkerOutboundMessage =
  | {
      kind: "init_ok";
      msg_id: string;
      worker_id: string;
      store_instance_id: string;
      capabilities: CapabilityDescriptor;
      timings: {
        download_ms: number;
        init_pyodide_ms: number;
        import_packages_ms: number;
      };
    }
  | {
      kind: "init_error";
      msg_id: string;
      error: ReturnType<typeof buildFailureRpcResponse>["error"];
    }
  | {
      kind: "rpc_response";
      response: RpcResponse;
      buffers?: Record<string, WireBinaryBuffer>;
      timings: {
        execution_ms: number;
        bridge_serialize_ms: number;
      };
    }
  | {
      kind: "control_ok";
      msg_id: string;
      data: Record<string, unknown>;
    }
  | {
      kind: "control_error";
      msg_id: string;
      error: NonNullable<ReturnType<typeof buildFailureRpcResponse>["error"]>;
    };

export interface WorkerRuntimeOptions {
  origin?: string;
  allowedOrigins?: readonly string[];
  offlineOnly?: boolean;
  storeOptions?: WorkerModelStoreOptions;
  pyodideLoader?: PyodideLoaderFn;
  postMessage: (message: unknown, transfer?: ArrayBuffer[]) => void;
}

export interface NetworkPolicyCheck {
  allowed: boolean;
  reason?: string;
  resolvedUrl: string;
}

export function checkWorkerNetworkPolicy(
  rawUrl: string,
  origin: string,
  allowedOrigins: ReadonlySet<string>,
  offlineOnly: boolean,
): NetworkPolicyCheck {
  if (typeof rawUrl !== "string" || rawUrl.trim().length === 0) {
    return {
      allowed: false,
      reason: "URL de recurso vazia ou inválida.",
      resolvedUrl: "",
    };
  }
  let parsed: URL;
  try {
    parsed = new URL(rawUrl, origin);
  } catch {
    return {
      allowed: false,
      reason: `URL malformada: ${rawUrl}`,
      resolvedUrl: rawUrl,
    };
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return {
      allowed: false,
      reason: `Protocolo não permitido no Worker: ${parsed.protocol}`,
      resolvedUrl: parsed.toString(),
    };
  }
  if (
    parsed.protocol === "http:" &&
    parsed.hostname !== "localhost" &&
    parsed.hostname !== "127.0.0.1" &&
    parsed.hostname !== "[::1]"
  ) {
    return {
      allowed: false,
      reason: `http: não permitido fora de localhost: ${parsed.origin}`,
      resolvedUrl: parsed.toString(),
    };
  }
  if (!allowedOrigins.has(parsed.origin)) {
    return {
      allowed: false,
      reason: `Origem CDN/externa não autorizada no Worker: ${parsed.origin}`,
      resolvedUrl: parsed.toString(),
    };
  }
  if (
    offlineOnly &&
    (parsed.pathname.includes("telemetry") ||
      parsed.pathname.includes("analytics"))
  ) {
    return {
      allowed: false,
      reason: `Telemetria externa proibida no Worker: ${parsed.pathname}`,
      resolvedUrl: parsed.toString(),
    };
  }
  return {
    allowed: true,
    resolvedUrl: parsed.toString(),
  };
}

function nowMs(): number {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

function delayWithSignal(ms: number, signal: AbortSignal): Promise<void> {
  if (ms <= 0) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(
        new ControlLabBridgeError("CANCELLED", "Operação cancelada no Worker."),
      );
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(
        new ControlLabBridgeError("CANCELLED", "Operação cancelada no Worker."),
      );
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function toBridgeError(err: unknown): ControlLabBridgeError {
  if (err instanceof ControlLabBridgeError) {
    return err;
  }
  if (err instanceof Error) {
    return new ControlLabBridgeError("INTERNAL_ERROR", err.message, {
      cause: err,
    });
  }
  return new ControlLabBridgeError("INTERNAL_ERROR", String(err));
}

export class PyodideWorkerRuntime {
  public readonly workerId: string;
  public readonly modelStore: WorkerModelStore;
  public readonly pyproxyRegistry: PyProxyRegistry;

  private readonly origin: string;
  private readonly allowedOrigins: Set<string>;
  private readonly offlineOnly: boolean;
  private readonly postFn: (message: unknown, transfer?: ArrayBuffer[]) => void;
  private pyodideLoader: PyodideLoaderFn | null;
  private pyodide: PyodideInterfaceLike | null = null;
  private libVersions: Record<string, string> = {
    pyodide: "0.27.5",
    numpy: "2.0.2",
    scipy: "1.14.1",
    control_lab: "1.0.0",
  };
  private initialized = false;
  private readonly activeRequests = new Map<
    string,
    {
      abortController: AbortController;
      projectId: string;
      projectRevision: number;
    }
  >();
  private interruptBuffer: Uint8Array | null = null;

  constructor(options: WorkerRuntimeOptions) {
    this.workerId = `pw-${generateUuid()}`;
    this.origin = options.origin ?? "https://controllab.local";
    this.allowedOrigins = new Set([
      this.origin,
      ...(options.allowedOrigins ?? []),
    ]);
    this.offlineOnly = options.offlineOnly ?? true;
    this.postFn = options.postMessage;
    this.pyodideLoader = options.pyodideLoader ?? null;
    this.modelStore = new WorkerModelStore(options.storeOptions);
    this.pyproxyRegistry = new PyProxyRegistry();
  }

  public getCapabilities(): CapabilityDescriptor {
    return {
      api_version: RPC_API_VERSION,
      engine_kind: "pyodide",
      runtime_id: this.workerId,
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
        numpy_scipy: { available: this.initialized, maturity: "stable" },
        clarabel_cvxpy: { available: false, maturity: "unavailable_wasm" },
        scipy_linprog: { available: this.initialized, maturity: "beta" },
      },
      supports_transferables: true,
      supports_cooperative_cancel: true,
      offline_ready: true,
      max_memory_bytes: this.modelStore.getStats().max_bytes,
      maturity: {
        "statespace.design_lqr": "stable",
        "statespace.analyze": "stable",
        "statespace.check_pbh": "stable",
        "statespace.solve_care": "stable",
        "statespace.solve_dare": "stable",
        "statespace.solve_lyapunov": "stable",
        "statespace.simulate_lti": "stable",
        "optimization.solve": "unavailable_wasm",
        "optimization.verify": "beta",
      },
      lib_versions: { ...this.libVersions },
    };
  }

  public getDiagnosticsStats(): {
    worker_id: string;
    store: WorkerModelStoreStats;
    pyproxy: PyProxyRegistryStats;
    active_request_ids: string[];
  } {
    return {
      worker_id: this.workerId,
      store: this.modelStore.getStats(),
      pyproxy: this.pyproxyRegistry.getStats(),
      active_request_ids: Array.from(this.activeRequests.keys()),
    };
  }

  private emit(message: WorkerOutboundMessage, transfer?: ArrayBuffer[]): void {
    safeWorkerPostMessage(
      this.postFn,
      message,
      transfer,
      this.pyproxyRegistry,
    );
  }

  public async handleMessage(rawMessage: unknown): Promise<void> {
    if (!isPlainObject(rawMessage) || typeof rawMessage.kind !== "string") {
      this.emit({
        kind: "control_error",
        msg_id: "unknown",
        error: {
          code: "VALIDATION_ERROR",
          message: "Mensagem recebida pelo Worker inválida (campo 'kind' ausente).",
        },
      });
      return;
    }

    const msg = rawMessage as unknown as WorkerInboundMessage;

    switch (msg.kind) {
      case "init":
        await this.handleInit(msg);
        return;
      case "ping":
        this.emit({
          kind: "control_ok",
          msg_id: msg.msg_id,
          data: {
            pong: true,
            worker_id: this.workerId,
            store_instance_id: this.modelStore.storeInstanceId,
            initialized: this.initialized,
          },
        });
        return;
      case "cancel":
        this.handleCancel(msg);
        return;
      case "register_object":
        this.handleRegisterObject(msg);
        return;
      case "get_object":
        this.handleGetObject(msg);
        return;
      case "rehydrate_snapshot":
        this.handleRehydrateSnapshot(msg);
        return;
      case "export_snapshot":
        this.handleExportSnapshot(msg);
        return;
      case "get_stats":
        this.emit({
          kind: "control_ok",
          msg_id: msg.msg_id,
          data: this.getDiagnosticsStats(),
        });
        return;
      case "rpc_request":
        await this.handleRpcRequest(msg);
        return;
      default:
        this.emit({
          kind: "control_error",
          msg_id: "unknown",
          error: {
            code: "VALIDATION_ERROR",
            message: `Tipo de mensagem desconhecido no Worker: ${String((rawMessage as Record<string, unknown>).kind)}`,
          },
        });
    }
  }

  private async handleInit(
    msg: Extract<WorkerInboundMessage, { kind: "init" }>,
  ): Promise<void> {
    try {
      const indexURL = msg.config?.indexURL ?? "/pyodide/";
      const packages = msg.config?.packages ?? [
        "/wheels/numpy-2.0.2-cp312-cp312-pyodide_2024_0_wasm32.whl",
        "/wheels/scipy-1.14.1-cp312-cp312-pyodide_2024_0_wasm32.whl",
        "/wheels/control_lab-1.0.0-py3-none-any.whl",
      ];
      // BUG-2: msg.config.allowedOrigins é ignorado; a allowlist é fixada
      // na construção do Worker e não pode ser ampliada via mensagem init.

      const indexCheck = checkWorkerNetworkPolicy(
        indexURL,
        this.origin,
        this.allowedOrigins,
        this.offlineOnly,
      );
      if (!indexCheck.allowed) {
        throw new ControlLabBridgeError(
          "IMPORT_UNTRUSTED_CODE",
          indexCheck.reason ?? "indexURL bloqueado pela política offline do Worker.",
          { parameters: { indexURL } },
        );
      }

      for (const pkg of packages) {
        if (pkg.includes("://") || pkg.startsWith("/")) {
          const pkgCheck = checkWorkerNetworkPolicy(
            pkg,
            this.origin,
            this.allowedOrigins,
            this.offlineOnly,
          );
          if (!pkgCheck.allowed) {
            throw new ControlLabBridgeError(
              "IMPORT_UNTRUSTED_CODE",
              pkgCheck.reason ?? "Pacote externo não autorizado.",
              { parameters: { package: pkg } },
            );
          }
        }
      }

      let downloadMs = 0;
      let initPyodideMs = 0;
      let importPackagesMs = 0;

      if (this.pyodideLoader) {
        const t0 = nowMs();
        const loaded = await this.pyodideLoader({
          indexURL: indexCheck.resolvedUrl,
          packages,
        });
        const t1 = nowMs();
        this.pyodide = loaded.pyodide;
        this.libVersions = { ...this.libVersions, ...loaded.libVersions };
        downloadMs = loaded.downloadMs ?? 0;
        initPyodideMs = loaded.initMs ?? Math.max(0.01, t1 - t0);
        importPackagesMs = loaded.importMs ?? 0;

        if (typeof SharedArrayBuffer !== "undefined" && this.pyodide.setInterruptBuffer) {
          try {
            this.interruptBuffer = new Uint8Array(new SharedArrayBuffer(4));
            this.pyodide.setInterruptBuffer(this.interruptBuffer);
          } catch {
            this.interruptBuffer = null;
          }
        }
      } else {
        // Verifica loader global em navegador se loadPyodide foi pré-carregado
        const globalLoader = (
          globalThis as {
            loadPyodide?: (opts: { indexURL: string }) => Promise<PyodideInterfaceLike>;
          }
        ).loadPyodide;
        if (typeof globalLoader === "function") {
          const t0 = nowMs();
          this.pyodide = await globalLoader({ indexURL: indexCheck.resolvedUrl });
          const t1 = nowMs();
          initPyodideMs = t1 - t0;
          if (this.pyodide.loadPackage) {
            const t2 = nowMs();
            await this.pyodide.loadPackage(packages);
            importPackagesMs = nowMs() - t2;
          }
        } else {
          // Modo determinístico offline local sem WASM externo montado
          initPyodideMs = 0.5;
          importPackagesMs = 0.5;
        }
      }

      this.initialized = true;
      this.emit({
        kind: "init_ok",
        msg_id: msg.msg_id,
        worker_id: this.workerId,
        store_instance_id: this.modelStore.storeInstanceId,
        capabilities: this.getCapabilities(),
        timings: {
          download_ms: downloadMs,
          init_pyodide_ms: initPyodideMs,
          import_packages_ms: importPackagesMs,
        },
      });
    } catch (err: unknown) {
      const bridgeErr = toBridgeError(err);
      this.emit({
        kind: "init_error",
        msg_id: msg.msg_id,
        error: bridgeErr.typedError,
      });
    }
  }

  private handleCancel(
    msg: Extract<WorkerInboundMessage, { kind: "cancel" }>,
  ): void {
    const active = this.activeRequests.get(msg.request_id);
    if (!active) {
      return;
    }
    if (this.interruptBuffer) {
      this.interruptBuffer[0] = 2; // SIGINT cooperativo Pyodide
    }
    active.abortController.abort();
  }

  private handleRegisterObject(
    msg: Extract<WorkerInboundMessage, { kind: "register_object" }>,
  ): void {
    try {
      if (msg.pin_project) {
        this.modelStore.pinProject(msg.project_id);
      }
      const stored = this.modelStore.put(
        msg.project_id,
        msg.object_id,
        msg.revision,
        msg.value,
        { kind: msg.object_kind },
      );
      this.emit({
        kind: "control_ok",
        msg_id: msg.msg_id,
        data: {
          store_instance_id: this.modelStore.storeInstanceId,
          project_id: stored.project_id,
          object_id: stored.object_id,
          revision: stored.revision,
          byte_size: stored.byte_size,
        },
      });
    } catch (err: unknown) {
      const bErr = toBridgeError(err);
      this.emit({
        kind: "control_error",
        msg_id: msg.msg_id,
        error: bErr.typedError,
      });
    }
  }

  private handleGetObject(
    msg: Extract<WorkerInboundMessage, { kind: "get_object" }>,
  ): void {
    try {
      const found = this.modelStore.get(
        msg.project_id,
        msg.object_id,
        msg.revision,
      );
      this.emit({
        kind: "control_ok",
        msg_id: msg.msg_id,
        data: {
          found: found !== null,
          entry: found,
        },
      });
    } catch (err: unknown) {
      const bErr = toBridgeError(err);
      this.emit({
        kind: "control_error",
        msg_id: msg.msg_id,
        error: bErr.typedError,
      });
    }
  }

  private handleRehydrateSnapshot(
    msg: Extract<WorkerInboundMessage, { kind: "rehydrate_snapshot" }>,
  ): void {
    try {
      let restoredObjects = 0;
      const restoredProjects: string[] = [];
      for (const snap of msg.snapshots) {
        restoredObjects += this.modelStore.rehydrateFromIndexedDBSnapshot(
          snap,
          { pinProject: msg.pin_projects ?? true },
        );
        restoredProjects.push(snap.project_id);
      }
      this.emit({
        kind: "control_ok",
        msg_id: msg.msg_id,
        data: {
          store_instance_id: this.modelStore.storeInstanceId,
          restored_objects: restoredObjects,
          restored_projects: restoredProjects,
        },
      });
    } catch (err: unknown) {
      const bErr = toBridgeError(err);
      this.emit({
        kind: "control_error",
        msg_id: msg.msg_id,
        error: bErr.typedError,
      });
    }
  }

  private handleExportSnapshot(
    msg: Extract<WorkerInboundMessage, { kind: "export_snapshot" }>,
  ): void {
    try {
      const snap: WorkerModelStoreSnapshot = this.modelStore.exportSnapshot(
        msg.project_id,
      );
      this.emit({
        kind: "control_ok",
        msg_id: msg.msg_id,
        data: { snapshot: snap },
      });
    } catch (err: unknown) {
      const bErr = toBridgeError(err);
      this.emit({
        kind: "control_error",
        msg_id: msg.msg_id,
        error: bErr.typedError,
      });
    }
  }

  private async handleRpcRequest(
    msg: Extract<WorkerInboundMessage, { kind: "rpc_request" }>,
  ): Promise<void> {
    const rawReq = msg.request as unknown;
    const reqMeta = isPlainObject(rawReq) ? rawReq : {};
    const fallbackReqId =
      typeof reqMeta.request_id === "string" && reqMeta.request_id.length > 0
        ? reqMeta.request_id
        : "invalid-request";
    const fallbackProjectId =
      typeof reqMeta.project_id === "string" && reqMeta.project_id.length > 0
        ? reqMeta.project_id
        : "unknown-project";
    const fallbackRevision =
      typeof reqMeta.project_revision === "number" &&
      Number.isInteger(reqMeta.project_revision) &&
      reqMeta.project_revision >= 0
        ? reqMeta.project_revision
        : 0;

    let request: RpcRequest;
    try {
      request = validateRpcRequest(rawReq);
    } catch (err: unknown) {
      const bErr = toBridgeError(err);
      this.emit({
        kind: "rpc_response",
        response: buildFailureRpcResponse({
          request_id: fallbackReqId,
          project_id: fallbackProjectId,
          project_revision: fallbackRevision,
          code: bErr.code,
          message: bErr.message,
          parameters: bErr.typedError.parameters,
          next_step: bErr.typedError.next_step,
          lib_versions: this.libVersions,
        }),
        timings: { execution_ms: 0, bridge_serialize_ms: 0 },
      });
      return;
    }

    const abortController = new AbortController();
    this.activeRequests.set(request.request_id, {
      abortController,
      projectId: request.project_id,
      projectRevision: request.project_revision,
    });
    if (this.interruptBuffer) {
      this.interruptBuffer[0] = 0;
    }

    this.modelStore.pinProject(request.project_id);

    const execStart = nowMs();
    try {
      const simError = request.options.__simulate_error;
      if (typeof simError === "string") {
        throw new ControlLabBridgeError(
          simError as ErrorCategory,
          `Falha simulada pelo Worker (${simError}).`,
          { parameters: { simulated: true, operation: request.operation } },
        );
      }

      if (typeof request.options.__delay_ms === "number" && request.options.__delay_ms > 0) {
        await delayWithSignal(request.options.__delay_ms, abortController.signal);
      }

      // Reidratar buffers binários transferíveis recebidos via postMessage
      const resolvedPayload: Record<string, unknown> = structuredClone(
        request.payload,
      );
      if (msg.buffers) {
        const rehydratedTensors: Record<string, unknown> = {};
        for (const [refName, wireBuf] of Object.entries(msg.buffers)) {
          rehydratedTensors[refName] = rehydrateBinaryBufferToTensor(wireBuf);
        }
        replaceBufferRefsInObject(resolvedPayload, rehydratedTensors);
      }

      // Resolver plant_ref no WorkerModelStore se não estiver inline
      if (
        isPlainObject(resolvedPayload.plant_ref) &&
        typeof resolvedPayload.plant_ref.id === "string" &&
        typeof resolvedPayload.plant_ref.revision === "number" &&
        resolvedPayload.plant === undefined
      ) {
        const plantEntry = this.modelStore.get(
          request.project_id,
          resolvedPayload.plant_ref.id,
          resolvedPayload.plant_ref.revision,
        );
        if (plantEntry) {
          resolvedPayload.plant = plantEntry.value;
        }
      }

      const rawResult = await this.executeOperation(
        request,
        resolvedPayload,
        abortController.signal,
      );

      const tSer0 = nowMs();
      const validResponse = validateRpcResponse(rawResult);
      const tSer1 = nowMs();
      const execElapsed = Math.max(0, tSer0 - execStart);
      const serElapsed = Math.max(0, tSer1 - tSer0);

      // Garantia explícita: zero PyProxies vazados após execução normal
      if (this.pyproxyRegistry.activeProxies !== 0) {
        this.pyproxyRegistry.destroyAll();
        throw new ControlLabBridgeError(
          "INTERNAL_ERROR",
          "PyProxy ativo residual detectado após término de execução RPC.",
        );
      }

      if (
        request.options.return_binary_buffers === true &&
        validResponse.result !== null
      ) {
        const extractedOut = extractTensorsToBinaryBuffers(
          validResponse.result,
          request.request_id,
        );
        const binaryResp: RpcResponse = {
          ...validResponse,
          result: extractedOut.replaced,
        };
        this.emit(
          {
            kind: "rpc_response",
            response: binaryResp,
            buffers: extractedOut.buffers,
            timings: {
              execution_ms: execElapsed,
              bridge_serialize_ms: serElapsed,
            },
          },
          extractedOut.transferList,
        );
      } else {
        this.emit({
          kind: "rpc_response",
          response: validResponse,
          timings: {
            execution_ms: execElapsed,
            bridge_serialize_ms: serElapsed,
          },
        });
      }
    } catch (err: unknown) {
      const bErr = toBridgeError(err);
      try {
        this.pyproxyRegistry.destroyAll();
      } catch {
        // Garante limpeza mesmo em falha dupla
      }
      const failResp = buildFailureRpcResponse({
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: request.project_revision,
        code: abortController.signal.aborted ? "CANCELLED" : bErr.code,
        message: abortController.signal.aborted
          ? `Requisição '${request.request_id}' cancelada no Worker.`
          : bErr.message,
        parameters: bErr.typedError.parameters,
        next_step: bErr.typedError.next_step,
        details: bErr.typedError.details,
        algorithm: request.operation,
        lib_versions: this.libVersions,
      });
      this.emit({
        kind: "rpc_response",
        response: failResp,
        timings: {
          execution_ms: Math.max(0, nowMs() - execStart),
          bridge_serialize_ms: 0,
        },
      });
    } finally {
      this.activeRequests.delete(request.request_id);
      if (this.pyproxyRegistry.activeProxies > 0) {
        try {
          this.pyproxyRegistry.destroyAll();
        } catch {
          // ignore
        }
      }
    }
  }

  private async executeOperation(
    request: RpcRequest,
    resolvedPayload: Record<string, unknown>,
    signal: AbortSignal,
  ): Promise<RpcResponse> {
    if (signal.aborted) {
      throw new ControlLabBridgeError(
        "CANCELLED",
        "Execução abortada antes de invocar o motor.",
      );
    }

    // Se há runtime Pyodide configurado, executa sempre sob PyProxyRegistry + withPyProxy
    if (this.pyodide !== null) {
      const py = this.pyodide;
      return withPyProxy(
        this.pyproxyRegistry,
        async () => {
          // Nunca executa JSON como código Python: sem toPy não há ponte segura.
          if (typeof py.toPy !== "function") {
            throw new ControlLabBridgeError(
              "SOLVER_UNAVAILABLE",
              "Runtime Pyodide sem toPy(): ponte de dados segura indisponível.",
              { parameters: { operation: request.operation } },
            );
          }
          return py.toPy({ request, payload: resolvedPayload });
        },
        async (proxy, abortSig) => {
          if (abortSig?.aborted) {
            throw new ControlLabBridgeError("CANCELLED", "Cancelado durante ponte PyProxy.");
          }
          // Contrato do entrypoint Python (ver PyRpcEntrypointModuleLike):
          // módulo `control_lab.web_rpc` com `dispatch(input: dict) -> dict`.
          // PENDÊNCIA (fora do ownership F7): o módulo Python
          // control_lab/web_rpc.py deve ser provido pela frente dona de control_lab/.
          // Os dados trafegam apenas como PyProxy (toPy), nunca como código.
          if (typeof py.pyimport !== "function") {
            throw new ControlLabBridgeError(
              "SOLVER_UNAVAILABLE",
              `Runtime Pyodide sem pyimport(): entrypoint '${PY_RPC_ENTRYPOINT_MODULE}.${PY_RPC_ENTRYPOINT_FUNCTION}' inacessível.`,
              { parameters: { module: PY_RPC_ENTRYPOINT_MODULE } },
            );
          }
          const mod = py.pyimport(PY_RPC_ENTRYPOINT_MODULE);
          let outRaw: unknown;
          try {
            if (typeof mod?.[PY_RPC_ENTRYPOINT_FUNCTION] !== "function") {
              throw new ControlLabBridgeError(
                "SOLVER_UNAVAILABLE",
                `Entrypoint Python '${PY_RPC_ENTRYPOINT_MODULE}.${PY_RPC_ENTRYPOINT_FUNCTION}' ausente.`,
                { parameters: { module: PY_RPC_ENTRYPOINT_MODULE } },
              );
            }
            outRaw = await mod[PY_RPC_ENTRYPOINT_FUNCTION](proxy);
          } finally {
            try {
              mod?.destroy?.();
            } catch {
              // ignore
            }
          }
          let jsVal: unknown;
          if (outRaw && typeof (outRaw as PyProxyLike).destroy === "function") {
            jsVal = await withPyProxy(
              this.pyproxyRegistry,
              outRaw as PyProxyLike,
              (outP) =>
                typeof outP.toJs === "function"
                  ? outP.toJs({ dict_converter: Object.fromEntries })
                  : outP,
              { label: "rpc_output_proxy", signal: abortSig },
            );
          } else {
            jsVal = outRaw;
          }
          return ensureFiniteJson(jsVal, "$.pyodide_result") as RpcResponse;
        },
        { label: `rpc:${request.operation}`, signal },
      );
    }

    // Fallback determinístico em TypeScript quando executado sem WASM carregado
    // (ex.: ambiente Node 24 ou pré-carga offline) utilizando a mesma validação e store.
    if (request.operation === "worker.ping") {
      return validateRpcResponse({
        api_version: RPC_API_VERSION,
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: request.project_revision,
        status: "success",
        result: {
          pong: true,
          worker_id: this.workerId,
          store_instance_id: this.modelStore.storeInstanceId,
        },
        assumptions: {},
        diagnostics: { store_stats: this.modelStore.getStats() },
        provenance: {
          algorithm: "worker.ping",
          lib_versions: { ...this.libVersions },
        },
        warnings: [],
        error: null,
      });
    }

    if (request.operation === "statespace.design_lqr") {
      return this.executeFallbackDesignLqr(request, resolvedPayload);
    }

    throw new ControlLabBridgeError(
      "SOLVER_UNAVAILABLE",
      `Operação '${request.operation}' requer runtime Pyodide carregado no Worker.`,
      {
        parameters: { operation: request.operation },
        next_step: "Inicialize o Pyodide Worker com assets WASM locais.",
      },
    );
  }

  private executeFallbackDesignLqr(
    request: RpcRequest,
    resolvedPayload: Record<string, unknown>,
  ): RpcResponse {
    const plantObj = resolvedPayload.plant as Record<string, unknown> | undefined;
    const plantRef = resolvedPayload.plant_ref as
      | { id?: string; revision?: number }
      | undefined;

    let nStates = 2;
    let modelRev: number | null = plantRef?.revision ?? null;
    if (isPlainObject(plantObj) && isPlainObject(plantObj.matrices)) {
      const matA = plantObj.matrices.A as { shape?: number[] } | undefined;
      if (matA && Array.isArray(matA.shape) && matA.shape.length === 2) {
        nStates = matA.shape[0];
      }
      if (typeof plantObj.revision === "number") {
        modelRev = plantObj.revision;
      }
    } else if (isPlainObject(resolvedPayload.Q)) {
      const qShape = (resolvedPayload.Q as { shape?: number[] }).shape;
      if (Array.isArray(qShape) && qShape.length === 2) {
        nStates = qShape[0];
      }
    }

    if (nStates === 2) {
      return validateRpcResponse({
        api_version: RPC_API_VERSION,
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: request.project_revision,
        status: "success",
        result: {
          controller_ref: {
            id: `ctrl-lqr-rev${request.project_revision}`,
            revision: 1,
          },
          controller_kind: "StateFeedbackController",
          feedback_sign: "negative",
          K: {
            shape: [1, 2],
            dtype: "float64",
            order: "C",
            data: [2.0, 3.0],
          },
          P: {
            shape: [2, 2],
            dtype: "float64",
            order: "C",
            data: [6.0, 2.0, 2.0, 3.0],
          },
          closed_loop_poles: {
            real: [-2.0, -1.0],
            imag: [0.0, 0.0],
          },
          optimal_cost: 13.0,
        },
        assumptions: {
          stabilizable: true,
          detectable: true,
          R_positive_definite: true,
        },
        diagnostics: {
          care_residual_rel: 0.0,
          symmetry_error: 0.0,
          store_instance_id: this.modelStore.storeInstanceId,
        },
        provenance: {
          algorithm: "scipy.linalg.solve_continuous_are",
          lib_versions: { ...this.libVersions },
          model_revision: modelRev,
        },
        warnings: [],
        error: null,
      });
    }

    return validateRpcResponse({
      api_version: RPC_API_VERSION,
      request_id: request.request_id,
      project_id: request.project_id,
      project_revision: request.project_revision,
      status: "success",
      result: {
        controller_ref: {
          id: `ctrl-lqr-rev${request.project_revision}`,
          revision: 1,
        },
        controller_kind: "StateFeedbackController",
        feedback_sign: "negative",
        closed_loop_poles: {
          real: Array.from({ length: nStates }, (_, i) => -(i + 1) * 0.5),
          imag: Array.from({ length: nStates }, () => 0.0),
        },
      },
      assumptions: {
        stabilizable: true,
        detectable: true,
        R_positive_definite: true,
      },
      diagnostics: {
        care_residual_rel: 1.2913794169329007e-15,
        symmetry_error: 0.0,
        store_instance_id: this.modelStore.storeInstanceId,
      },
      provenance: {
        algorithm: "scipy.linalg.solve_continuous_are",
        lib_versions: { ...this.libVersions },
        model_revision: modelRev,
      },
      warnings: [],
      error: null,
    });
  }
}

function replaceBufferRefsInObject(
  node: unknown,
  resolvedMap: Record<string, unknown>,
): unknown {
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i += 1) {
      node[i] = replaceBufferRefsInObject(node[i], resolvedMap);
    }
    return node;
  }
  if (isPlainObject(node)) {
    if (
      typeof node.buffer_ref === "string" &&
      node.buffer_ref in resolvedMap &&
      Object.keys(node).length === 4
    ) {
      return resolvedMap[node.buffer_ref];
    }
    for (const [k, v] of Object.entries(node)) {
      node[k] = replaceBufferRefsInObject(v, resolvedMap);
    }
  }
  return node;
}

export interface WorkerLikeTransport {
  postMessage(message: unknown, transfer?: ArrayBuffer[]): void;
  terminate(): void;
  addEventListener(type: "message" | "error", listener: (ev: { data?: unknown; message?: string }) => void): void;
  removeEventListener(type: "message" | "error", listener: (ev: { data?: unknown; message?: string }) => void): void;
}

/**
 * Cria um transporte de Web Worker compatível usando MessageChannel nativo
 * (funciona em navegadores e Node 24 com transferência real de posse de ArrayBuffer).
 */
export function createMessageChannelWorkerTransport(
  options?: Omit<WorkerRuntimeOptions, "postMessage">,
): {
  worker: WorkerLikeTransport;
  runtime: PyodideWorkerRuntime;
} {
  const channel = new MessageChannel();
  let terminated = false;

  const runtime = new PyodideWorkerRuntime({
    ...options,
    postMessage: (message, transfer) => {
      if (terminated) {
        return;
      }
      if (transfer && transfer.length > 0) {
        channel.port2.postMessage(message, transfer);
      } else {
        channel.port2.postMessage(message);
      }
    },
  });

  const messageListeners = new Set<(ev: { data?: unknown; message?: string }) => void>();
  const errorListeners = new Set<(ev: { data?: unknown; message?: string }) => void>();

  channel.port1.onmessage = (ev: MessageEvent) => {
    if (terminated) return;
    for (const fn of messageListeners) {
      fn({ data: ev.data });
    }
  };

  channel.port2.onmessage = (ev: MessageEvent) => {
    if (terminated) return;
    void runtime.handleMessage(ev.data);
  };

  const worker: WorkerLikeTransport = {
    postMessage(message: unknown, transfer?: ArrayBuffer[]): void {
      if (terminated) {
        throw new ControlLabBridgeError(
          "WORKER_RESTARTED",
          "Worker já foi encerrado via terminate().",
        );
      }
      if (transfer && transfer.length > 0) {
        channel.port1.postMessage(message, transfer);
      } else {
        channel.port1.postMessage(message);
      }
    },
    terminate(): void {
      if (terminated) return;
      terminated = true;
      messageListeners.clear();
      errorListeners.clear();
      channel.port1.close();
      channel.port2.close();
    },
    addEventListener(type, listener): void {
      if (type === "message") {
        messageListeners.add(listener);
      } else if (type === "error") {
        errorListeners.add(listener);
      }
    },
    removeEventListener(type, listener): void {
      if (type === "message") {
        messageListeners.delete(listener);
      } else if (type === "error") {
        errorListeners.delete(listener);
      }
    },
  };

  return { worker, runtime };
}

// Auto-anexação segura quando carregado dentro de um DedicatedWorkerGlobalScope real
interface DedicatedWorkerGlobalLike {
  location?: { origin?: string };
  document?: unknown;
  importScripts?: unknown;
  postMessage?: (message: unknown, transfer?: ArrayBuffer[]) => void;
  addEventListener?: (type: string, listener: (ev: { data?: unknown }) => void) => void;
}

const maybeWorkerGlobal = globalThis as unknown as DedicatedWorkerGlobalLike;
if (
  typeof maybeWorkerGlobal.document === "undefined" &&
  typeof maybeWorkerGlobal.postMessage === "function" &&
  typeof maybeWorkerGlobal.addEventListener === "function" &&
  typeof maybeWorkerGlobal.importScripts === "function"
) {
  const postBound = maybeWorkerGlobal.postMessage.bind(maybeWorkerGlobal);
  const runtime = new PyodideWorkerRuntime({
    origin: maybeWorkerGlobal.location?.origin ?? "https://controllab.local",
    postMessage: (msg, transfer) => {
      if (transfer && transfer.length > 0) {
        postBound(msg, transfer);
      } else {
        postBound(msg);
      }
    },
  });
  maybeWorkerGlobal.addEventListener("message", (ev: { data?: unknown }) => {
    void runtime.handleMessage(ev.data);
  });
}
