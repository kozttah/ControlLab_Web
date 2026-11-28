/**
 * Interface unificada ControlLabEngineClient, coordenador de revisões monotônicas,
 * debouncing/coalescing configurável, métricas de execução e ciclo de vida
 * (CL-DIR-001 Seções 7.2, 8.1–8.4, 11.1, 13.9, R-16, R-17, R-28, T-RPC-01).
 */

import {
  buildFailureRpcResponse,
  ControlLabBridgeError,
  RPC_API_VERSION,
  validateRpcRequest,
  validateRpcResponse,
  type BinaryTensorInput,
  type CapabilityDescriptor,
  type EngineLifecycleState,
  type ExecutionMetrics,
  type FuzzyEvaluateSurfacePayload,
  type FuzzyFitAnfisPayload,
  type FuzzySystemRef,
  type RpcRequest,
  type RpcResponse,
  type SolverProgress,
  type SolverProgressEvent,
  type TimeoutPolicy,
} from "./protocol.ts";
import {
  TS_MODELING_OPERATIONS,
  type AnalyzeSectorPremisesPayload,
  type DeriveTsFemtPayload,
  type DeriveTsSectorPayload,
  type DeriveTsTpmtPayload,
  type DerivedTsFemtResult,
  type DerivedTsSectorResult,
  type DerivedTsTpmtResult,
  type ExportTsDerivationScriptPayload,
  type SectorAnalysisResult,
  type TsDerivationScriptResult,
  type TsModelingContext,
  type TsModelingOperation,
  type TsModelingProgressEvent,
  type TsRpcResponse,
} from "./ts_modeling.ts";
import type {
  CommitProjectRevisionOutput,
  IndexedDBProjectStore,
  PortableProjectSnapshot,
} from "../storage/indexeddb_store.ts";

export interface EngineInitOptions {
  indexURL?: string;
  packages?: string[];
  allowedOrigins?: string[];
  offlineOnly?: boolean;
  maxMemoryBytes?: number;
  maxEntries?: number;
  initTimeoutMs?: number;
}

export interface ExecuteOptions {
  buffers?: Record<string, BinaryTensorInput>;
  preserveSenderCopy?: boolean;
  commitOnSuccess?: boolean;
  debounceMs?: number;
  coalesceKey?: string;
  experimentId?: string;
}

export interface CancelOptions {
  reason?: string;
  forceTerminate?: boolean;
}

export interface RegisterObjectOptions {
  kind?: string;
  pinProject?: boolean;
  persistToIndexedDB?: boolean;
}

export interface RegisteredObjectRef {
  project_id: string;
  object_id: string;
  revision: number;
  persisted: boolean;
  cached_in_worker: boolean;
}

export interface CommitProjectInput {
  request_id?: string | null;
  committed_result?: RpcResponse | null;
  objects?: Array<{
    object_id: string;
    revision: number;
    kind?: string;
    value: Record<string, unknown>;
  }>;
  experiment?: {
    experiment_id: string;
    operation: string;
    response: RpcResponse;
  };
  require_strictly_greater?: boolean;
  metadata?: Record<string, unknown>;
}

export type CommitProjectResult = CommitProjectRevisionOutput;

export type EngineClientEvent =
  | {
      type: "lifecycle";
      previous: EngineLifecycleState;
      current: EngineLifecycleState;
      reason?: string;
      timestamp: string;
    }
  | {
      type: "stale_response_discarded";
      project_id: string;
      request_id: string;
      response_revision: number;
      active_revision: number;
      timestamp: string;
    }
  | {
      type: "request_committed";
      project_id: string;
      request_id: string;
      project_revision: number;
      timestamp: string;
    }
  | {
      type: "request_cancelled";
      project_id: string;
      request_id: string;
      reason: string;
      timestamp: string;
    }
  | {
      type: "worker_recovered";
      generation: number;
      restored_projects: string[];
      restored_objects: number;
      timestamp: string;
    }
  | {
      type: "error";
      error: ControlLabBridgeError;
      timestamp: string;
    };

export type EngineEventListener = (event: EngineClientEvent) => void;
export type SolverProgressListener = (ev: SolverProgressEvent) => void;

export interface FuzzyRpcContext {
  request_id: string;
  project_id: string;
  project_revision: number;
  options?: Record<string, unknown>;
  timeout_policy?: TimeoutPolicy;
}

export interface ControlLabEngineClient {
  init(options?: EngineInitOptions): Promise<CapabilityDescriptor>;
  execute(request: RpcRequest, options?: ExecuteOptions): Promise<RpcResponse>;
  fitAnfis?(
    context: FuzzyRpcContext,
    payload: FuzzyFitAnfisPayload,
    options?: ExecuteOptions,
  ): Promise<RpcResponse>;
  evaluateFuzzySurface?(
    context: FuzzyRpcContext,
    payload: FuzzyEvaluateSurfacePayload,
    options?: ExecuteOptions,
  ): Promise<RpcResponse>;
  cancel(requestId: string, options?: CancelOptions): Promise<boolean>;
  registerObject(
    projectId: string,
    objectId: string,
    revision: number,
    value: Record<string, unknown>,
    options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef>;
  getObject(
    projectId: string,
    objectId: string,
    revision: number,
  ): Promise<Record<string, unknown> | null>;
  commitProject(
    projectId: string,
    revision: number,
    input?: CommitProjectInput,
  ): Promise<CommitProjectResult>;
  exportProject(projectId: string): Promise<PortableProjectSnapshot>;
  resetWorker(reason?: string): Promise<void>;
  getCapabilities(): CapabilityDescriptor;
  getMetrics(): ExecutionMetrics;
  getCommittedRevision(projectId: string): number;
  getLifecycleState(): EngineLifecycleState;
  subscribe(listener: EngineEventListener): () => void;
  subscribeProgress?(listener: SolverProgressListener): () => void;
  dispose(): void;
}

export type TsModelingProgressListener = (event: TsModelingProgressEvent) => void;

/** Optional engine surface for consumers of the TS modeling feature. */
export interface TsModelingEngineClient extends ControlLabEngineClient {
  analyzeSectorPremises(context: TsModelingContext, payload: AnalyzeSectorPremisesPayload, options?: ExecuteOptions): Promise<TsRpcResponse<SectorAnalysisResult>>;
  deriveTsSector(context: TsModelingContext, payload: DeriveTsSectorPayload, options?: ExecuteOptions): Promise<TsRpcResponse<DerivedTsSectorResult>>;
  deriveTsTpmt(context: TsModelingContext, payload: DeriveTsTpmtPayload, options?: ExecuteOptions): Promise<TsRpcResponse<DerivedTsTpmtResult>>;
  deriveTsFemt(context: TsModelingContext, payload: DeriveTsFemtPayload, options?: ExecuteOptions): Promise<TsRpcResponse<DerivedTsFemtResult>>;
  exportTsDerivationScript(context: TsModelingContext, payload: ExportTsDerivationScriptPayload, options?: ExecuteOptions): Promise<TsRpcResponse<TsDerivationScriptResult>>;
  subscribeTsModelingProgress(listener: TsModelingProgressListener): () => void;
}

export function supportsTsModeling(client: ControlLabEngineClient): client is TsModelingEngineClient {
  const methods: readonly (keyof TsModelingEngineClient)[] = [
    "analyzeSectorPremises", "deriveTsSector", "deriveTsTpmt", "deriveTsFemt",
    "exportTsDerivationScript", "subscribeTsModelingProgress",
  ];
  const candidate: Partial<TsModelingEngineClient> = client;
  return methods.every(method => typeof candidate[method] === "function");
}

export interface InFlightEntry {
  requestId: string;
  projectId: string;
  projectRevision: number;
  cancelOnSupersede: boolean;
  superseded: boolean;
}

/**
 * Coordenador de monotonicidade de project_revision por project_id.
 * Garante que respostas obsoletas (response.project_revision < activeRevision)
 * nunca comitam no estado confirmado nem no IndexedDB.
 */
export class RevisionCoordinator {
  private readonly activeRevisionByProject = new Map<string, number>();
  private readonly committedRevisionByProject = new Map<string, number>();
  private readonly committedResponseByProject = new Map<string, RpcResponse>();
  private readonly inFlightByRequest = new Map<string, InFlightEntry>();

  public getActiveRevision(projectId: string): number {
    return this.activeRevisionByProject.get(projectId) ?? -1;
  }

  public getCommittedRevision(projectId: string): number {
    return this.committedRevisionByProject.get(projectId) ?? -1;
  }

  public getCommittedResponse(projectId: string): RpcResponse | null {
    return this.committedResponseByProject.get(projectId) ?? null;
  }

  public getTrackedProjectIds(): string[] {
    const ids = new Set<string>([
      ...this.activeRevisionByProject.keys(),
      ...this.committedRevisionByProject.keys(),
    ]);
    return Array.from(ids).sort();
  }

  public syncFromPersistedRevision(
    projectId: string,
    committedRevision: number,
    committedResponse: RpcResponse | null = null,
  ): void {
    const curActive = this.getActiveRevision(projectId);
    if (committedRevision > curActive) {
      this.activeRevisionByProject.set(projectId, committedRevision);
    }
    const curCommitted = this.getCommittedRevision(projectId);
    if (committedRevision >= curCommitted) {
      this.committedRevisionByProject.set(projectId, committedRevision);
      if (committedResponse !== null) {
        this.committedResponseByProject.set(projectId, committedResponse);
      }
    }
  }

  public registerRequest(request: RpcRequest): {
    isAlreadyStale: boolean;
    activeRevision: number;
    toCancelIds: string[];
  } {
    const currentActive = this.getActiveRevision(request.project_id);
    if (request.project_revision < currentActive) {
      return {
        isAlreadyStale: true,
        activeRevision: currentActive,
        toCancelIds: [],
      };
    }

    const nextActive = Math.max(currentActive, request.project_revision);
    this.activeRevisionByProject.set(request.project_id, nextActive);

    const toCancelIds: string[] = [];
    for (const entry of this.inFlightByRequest.values()) {
      if (
        entry.projectId === request.project_id &&
        entry.projectRevision < nextActive
      ) {
        entry.superseded = true;
        if (entry.cancelOnSupersede) {
          toCancelIds.push(entry.requestId);
        }
      }
    }

    this.inFlightByRequest.set(request.request_id, {
      requestId: request.request_id,
      projectId: request.project_id,
      projectRevision: request.project_revision,
      cancelOnSupersede: request.timeout_policy.cancel_on_supersede === true,
      superseded: false,
    });

    return {
      isAlreadyStale: false,
      activeRevision: nextActive,
      toCancelIds,
    };
  }

  public finishRequest(requestId: string): InFlightEntry | null {
    const entry = this.inFlightByRequest.get(requestId) ?? null;
    this.inFlightByRequest.delete(requestId);
    return entry;
  }

  public isStaleRevision(projectId: string, responseRevision: number): boolean {
    return responseRevision < this.getActiveRevision(projectId);
  }

  public canCommitRevision(projectId: string, responseRevision: number): boolean {
    const active = this.getActiveRevision(projectId);
    const committed = this.getCommittedRevision(projectId);
    return responseRevision >= active && responseRevision >= committed;
  }

  public markCommitted(
    projectId: string,
    revision: number,
    response: RpcResponse | null,
  ): void {
    const currentCommitted = this.getCommittedRevision(projectId);
    if (revision < currentCommitted) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Tentativa de comitar revisão regressiva ${revision} < ${currentCommitted} para '${projectId}'.`,
      );
    }
    this.committedRevisionByProject.set(projectId, revision);
    const currentActive = this.getActiveRevision(projectId);
    if (revision > currentActive) {
      this.activeRevisionByProject.set(projectId, revision);
    }
    if (response !== null) {
      this.committedResponseByProject.set(projectId, response);
    }
  }
}

interface PendingDebounceSlot {
  timer: ReturnType<typeof setTimeout>;
  request: RpcRequest;
  resolve: (resp: RpcResponse) => void;
}

/**
 * Coalescer configurável para arraste/preview a 60 FPS:
 * apenas a última requisição na janela de debounce é despachada.
 */
export class DebouncedRequestCoalescer {
  private readonly pending = new Map<string, PendingDebounceSlot>();

  public schedule(
    coalesceKey: string,
    request: RpcRequest,
    debounceMs: number,
    dispatchFn: (req: RpcRequest) => Promise<RpcResponse>,
  ): Promise<RpcResponse> {
    const prev = this.pending.get(coalesceKey);
    if (prev) {
      clearTimeout(prev.timer);
      this.pending.delete(coalesceKey);
      prev.resolve(
        buildFailureRpcResponse({
          request_id: prev.request.request_id,
          project_id: prev.request.project_id,
          project_revision: prev.request.project_revision,
          code: "CANCELLED",
          message: `Requisição '${prev.request.request_id}' coalescida por '${request.request_id}'.`,
          parameters: {
            coalesced: true,
            superseded_by: request.request_id,
          },
          diagnostics: { coalesced: true, committed: false },
        }),
      );
    }

    return new Promise<RpcResponse>((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(coalesceKey);
        dispatchFn(request).then(resolve, (err: unknown) => {
          const code =
            err instanceof ControlLabBridgeError ? err.code : "INTERNAL_ERROR";
          const message = err instanceof Error ? err.message : String(err);
          resolve(
            buildFailureRpcResponse({
              request_id: request.request_id,
              project_id: request.project_id,
              project_revision: request.project_revision,
              code,
              message,
              diagnostics: { committed: false },
            }),
          );
        });
      }, Math.max(0, debounceMs));

      this.pending.set(coalesceKey, {
        timer,
        request,
        resolve,
      });
    });
  }

  public cancelAll(): void {
    for (const [key, slot] of Array.from(this.pending.entries())) {
      clearTimeout(slot.timer);
      this.pending.delete(key);
      slot.resolve(
        buildFailureRpcResponse({
          request_id: slot.request.request_id,
          project_id: slot.request.project_id,
          project_revision: slot.request.project_revision,
          code: "CANCELLED",
          message: "Requisição pendente em debounce cancelada.",
          diagnostics: { coalesced: true, committed: false },
        }),
      );
    }
  }
}

export function createInitialExecutionMetrics(): ExecutionMetrics {
  return {
    T_download: null,
    T_init_pyodide: null,
    T_import_packages: null,
    T_first_call: null,
    T_warm_call: null,
    T_bridge_transfer: null,
    call_count: 0,
    cold_completed: false,
    last_request_id: null,
    warm_calls_count: 0,
    warm_call_avg_ms: null,
  };
}

/**
 * Base compartilhada para MockWorkerAdapter e PyodideEngineClient:
 * implementa ciclo de vida, assinaturas, métricas, validação de contrato,
 * descarte de respostas obsoletas e persistência transacional no IndexedDBProjectStore.
 */
export abstract class BaseEngineClient implements TsModelingEngineClient {
  protected readonly store: IndexedDBProjectStore;
  protected readonly coordinator: RevisionCoordinator;
  protected readonly coalescer: DebouncedRequestCoalescer;
  private readonly listeners = new Set<EngineEventListener>();
  private readonly progressListeners = new Set<SolverProgressListener>();
  private readonly tsModelingProgressListeners = new Set<TsModelingProgressListener>();
  private lifecycleState: EngineLifecycleState = "uninitialized";
  protected metrics: ExecutionMetrics = createInitialExecutionMetrics();
  private warmTotalMs = 0;
  private readonly commitChains = new Map<string, Promise<unknown>>();

  constructor(store: IndexedDBProjectStore) {
    this.store = store;
    this.coordinator = new RevisionCoordinator();
    this.coalescer = new DebouncedRequestCoalescer();
  }

  public abstract init(options?: EngineInitOptions): Promise<CapabilityDescriptor>;
  protected abstract dispatchRpc(
    request: RpcRequest,
    options?: ExecuteOptions,
  ): Promise<{ response: RpcResponse; bridgeTransferMs?: number }>;
  public abstract cancel(
    requestId: string,
    options?: CancelOptions,
  ): Promise<boolean>;
  public abstract registerObject(
    projectId: string,
    objectId: string,
    revision: number,
    value: Record<string, unknown>,
    options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef>;
  public abstract getObject(
    projectId: string,
    objectId: string,
    revision: number,
  ): Promise<Record<string, unknown> | null>;
  public abstract resetWorker(reason?: string): Promise<void>;
  public abstract getCapabilities(): CapabilityDescriptor;

  public getLifecycleState(): EngineLifecycleState {
    return this.lifecycleState;
  }

  public getMetrics(): ExecutionMetrics {
    return { ...this.metrics };
  }

  public getActiveRevision(projectId: string): number {
    return this.coordinator.getActiveRevision(projectId);
  }

  public getCommittedRevision(projectId: string): number {
    return this.coordinator.getCommittedRevision(projectId);
  }

  public getCommittedResponse(projectId: string): RpcResponse | null {
    return this.coordinator.getCommittedResponse(projectId);
  }

  public getStore(): IndexedDBProjectStore {
    return this.store;
  }

  public subscribe(listener: EngineEventListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  public subscribeProgress(listener: SolverProgressListener): () => void {
    this.progressListeners.add(listener);
    return () => {
      this.progressListeners.delete(listener);
    };
  }

  public subscribeTsModelingProgress(listener: TsModelingProgressListener): () => void {
    this.tsModelingProgressListeners.add(listener);
    return () => {
      this.tsModelingProgressListeners.delete(listener);
    };
  }

  protected emitTsModelingProgress(event: TsModelingProgressEvent): void {
    for (const listener of this.tsModelingProgressListeners) {
      try {
        listener(event);
      } catch {
        // O progresso não deve interromper o despacho se um observador falhar.
      }
    }
  }

  protected emitEvent(event: EngineClientEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Não permitir que um assinante defeituoso quebre o cliente
      }
    }
  }

  protected emitProgressEvent(event: SolverProgressEvent): void {
    for (const listener of this.progressListeners) {
      try {
        listener(event);
      } catch {
        // Não permitir que um assinante defeituoso quebre o cliente
      }
    }
  }

  protected setLifecycleState(
    nextState: EngineLifecycleState,
    reason?: string,
  ): void {
    const previous = this.lifecycleState;
    if (previous === nextState) {
      return;
    }
    this.lifecycleState = nextState;
    this.emitEvent({
      type: "lifecycle",
      previous,
      current: nextState,
      reason,
      timestamp: new Date().toISOString(),
    });
  }

  protected recordCallMetrics(
    requestId: string,
    callElapsedMs: number,
    bridgeTransferMs: number,
  ): void {
    this.metrics.call_count += 1;
    this.metrics.last_request_id = requestId;
    this.metrics.T_bridge_transfer = bridgeTransferMs;
    if (!this.metrics.cold_completed) {
      this.metrics.T_first_call = callElapsedMs;
      this.metrics.cold_completed = true;
    } else {
      this.metrics.T_warm_call = callElapsedMs;
      this.metrics.warm_calls_count += 1;
      this.warmTotalMs += callElapsedMs;
      this.metrics.warm_call_avg_ms =
        this.warmTotalMs / this.metrics.warm_calls_count;
    }
  }

  public async execute(
    rawRequest: RpcRequest,
    options?: ExecuteOptions,
  ): Promise<RpcResponse> {
    if (
      options?.debounceMs !== undefined &&
      options.debounceMs > 0
    ) {
      const validated = validateRpcRequest(rawRequest);
      const key =
        options.coalesceKey ?? `${validated.project_id}:${validated.operation}`;
      return this.coalescer.schedule(
        key,
        validated,
        options.debounceMs,
        (req) => this.executeImmediate(req, { ...options, debounceMs: 0 }),
      );
    }
    return this.executeImmediate(rawRequest, options);
  }

  public fitAnfis(
    context: FuzzyRpcContext,
    payload: FuzzyFitAnfisPayload,
    options?: ExecuteOptions,
  ): Promise<RpcResponse> {
    return this.execute(
      {
        ...context,
        api_version: RPC_API_VERSION,
        operation: "fuzzy.fit_anfis",
        payload: { ...payload },
        options: context.options ?? {},
        timeout_policy: context.timeout_policy ?? {
          hard_timeout_ms: 60_000,
          cancel_on_supersede: true,
        },
      },
      options,
    );
  }

  public evaluateFuzzySurface(
    context: FuzzyRpcContext,
    payload: FuzzyEvaluateSurfacePayload,
    options?: ExecuteOptions,
  ): Promise<RpcResponse> {
    return this.execute(
      {
        ...context,
        api_version: RPC_API_VERSION,
        operation: "fuzzy.evaluate_surface",
        payload: { ...payload },
        options: context.options ?? {},
        timeout_policy: context.timeout_policy ?? {
          hard_timeout_ms: 30_000,
          cancel_on_supersede: true,
        },
      },
      options,
    );
  }

  public analyzeSectorPremises(
    context: TsModelingContext,
    payload: AnalyzeSectorPremisesPayload,
    options?: ExecuteOptions,
  ): Promise<TsRpcResponse<SectorAnalysisResult>> {
    return this.executeTsModeling(TS_MODELING_OPERATIONS.analyzeSectorPremises, context, payload, options);
  }

  public deriveTsSector(
    context: TsModelingContext,
    payload: DeriveTsSectorPayload,
    options?: ExecuteOptions,
  ): Promise<TsRpcResponse<DerivedTsSectorResult>> {
    return this.executeTsModeling(TS_MODELING_OPERATIONS.deriveTsSector, context, payload, options);
  }

  public deriveTsTpmt(
    context: TsModelingContext,
    payload: DeriveTsTpmtPayload,
    options?: ExecuteOptions,
  ): Promise<TsRpcResponse<DerivedTsTpmtResult>> {
    return this.executeTsModeling(TS_MODELING_OPERATIONS.deriveTsTpmt, context, payload, options);
  }

  public deriveTsFemt(
    context: TsModelingContext,
    payload: DeriveTsFemtPayload,
    options?: ExecuteOptions,
  ): Promise<TsRpcResponse<DerivedTsFemtResult>> {
    return this.executeTsModeling(TS_MODELING_OPERATIONS.deriveTsFemt, context, payload, options);
  }

  public exportTsDerivationScript(
    context: TsModelingContext,
    payload: ExportTsDerivationScriptPayload,
    options?: ExecuteOptions,
  ): Promise<TsRpcResponse<TsDerivationScriptResult>> {
    return this.executeTsModeling(TS_MODELING_OPERATIONS.exportTsDerivationScript, context, payload, options);
  }

  private async executeTsModeling<T extends Record<string, unknown>>(
    operation: TsModelingOperation,
    context: TsModelingContext,
    payload: object,
    options?: ExecuteOptions,
  ): Promise<TsRpcResponse<T>> {
    const response = await this.execute({
      ...context,
      api_version: RPC_API_VERSION,
      operation,
      payload: { ...payload },
      options: context.options ?? {},
      timeout_policy: context.timeout_policy ?? { hard_timeout_ms: 60_000, cancel_on_supersede: true },
    }, { commitOnSuccess: false, ...options });
    return response as TsRpcResponse<T>;
  }

  protected async executeImmediate(
    rawRequest: RpcRequest,
    options?: ExecuteOptions,
  ): Promise<RpcResponse> {
    const request = validateRpcRequest(rawRequest);

    if (this.lifecycleState !== "ready") {
      try {
        await this.init();
      } catch (error: unknown) {
        const bridgeError = error instanceof ControlLabBridgeError ? error :
          new ControlLabBridgeError("INTERNAL_ERROR", error instanceof Error ? error.message : String(error));
        return buildFailureRpcResponse({
          request_id: request.request_id, project_id: request.project_id,
          project_revision: request.project_revision, code: bridgeError.code,
          message: bridgeError.message, parameters: bridgeError.typedError.parameters,
          next_step: bridgeError.typedError.next_step, algorithm: request.operation,
          lib_versions: this.getCapabilities().lib_versions,
          diagnostics: { committed: false },
        });
      }
    }

    const reg = this.coordinator.registerRequest(request);
    if (reg.isAlreadyStale) {
      const discarded = this.makeStaleDiscardedResponse(
        request,
        reg.activeRevision,
      );
      this.emitEvent({
        type: "stale_response_discarded",
        project_id: request.project_id,
        request_id: request.request_id,
        response_revision: request.project_revision,
        active_revision: reg.activeRevision,
        timestamp: new Date().toISOString(),
      });
      return discarded;
    }

    for (const oldReqId of reg.toCancelIds) {
      void this.cancel(oldReqId, { reason: "superseded_by_newer_revision" });
    }

    const t0 =
      typeof performance !== "undefined" && typeof performance.now === "function"
        ? performance.now()
        : Date.now();

    let dispatched: { response: RpcResponse; bridgeTransferMs?: number };
    try {
      dispatched = await this.dispatchRpc(request, options);
    } finally {
      this.coordinator.finishRequest(request.request_id);
    }

    const t1 =
      typeof performance !== "undefined" && typeof performance.now === "function"
        ? performance.now()
        : Date.now();
    const elapsedMs = Math.max(0, t1 - t0);

    const validatedResp = validateRpcResponse(dispatched.response);
    this.recordCallMetrics(
      request.request_id,
      elapsedMs,
      dispatched.bridgeTransferMs ?? 0,
    );

    // Verifica estritamente se a resposta ficou obsoleta durante a execução
    if (
      this.coordinator.isStaleRevision(
        validatedResp.project_id,
        validatedResp.project_revision,
      )
    ) {
      const activeRev = this.coordinator.getActiveRevision(
        validatedResp.project_id,
      );
      this.emitEvent({
        type: "stale_response_discarded",
        project_id: validatedResp.project_id,
        request_id: validatedResp.request_id,
        response_revision: validatedResp.project_revision,
        active_revision: activeRev,
        timestamp: new Date().toISOString(),
      });
      return this.makeStaleDiscardedResponse(request, activeRev);
    }

    const isPreview = request.options.preview === true;
    const shouldCommit =
      options?.commitOnSuccess !== false &&
      !isPreview &&
      validatedResp.status !== "failure";

    if (shouldCommit) {
      const commitOutcome = await this.enqueueProjectCommit(
        validatedResp.project_id,
        async () => {
          // Segunda verificação após aguardar fila de commit por projeto
          if (
            !this.coordinator.canCommitRevision(
              validatedResp.project_id,
              validatedResp.project_revision,
            )
          ) {
            return { committed: false as const };
          }
          const persistedResp: RpcResponse = {
            ...validatedResp,
            diagnostics: {
              ...validatedResp.diagnostics,
              committed: true,
              stale_discarded: false,
            },
          };
          await this.store.commitProjectRevision({
            project_id: persistedResp.project_id,
            project_revision: persistedResp.project_revision,
            request_id: persistedResp.request_id,
            committed_result: persistedResp,
            experiment: options?.experimentId
              ? {
                  experiment_id: options.experimentId,
                  operation: request.operation,
                  response: persistedResp,
                }
              : undefined,
          });
          this.coordinator.markCommitted(
            persistedResp.project_id,
            persistedResp.project_revision,
            persistedResp,
          );
          return { committed: true as const, response: persistedResp };
        },
      );

      if (!commitOutcome.committed) {
        const activeRev = this.coordinator.getActiveRevision(
          validatedResp.project_id,
        );
        this.emitEvent({
          type: "stale_response_discarded",
          project_id: validatedResp.project_id,
          request_id: validatedResp.request_id,
          response_revision: validatedResp.project_revision,
          active_revision: activeRev,
          timestamp: new Date().toISOString(),
        });
        return this.makeStaleDiscardedResponse(request, activeRev);
      }

      this.emitEvent({
        type: "request_committed",
        project_id: commitOutcome.response.project_id,
        request_id: commitOutcome.response.request_id,
        project_revision: commitOutcome.response.project_revision,
        timestamp: new Date().toISOString(),
      });
      return commitOutcome.response;
    }

    return {
      ...validatedResp,
      diagnostics: {
        ...validatedResp.diagnostics,
        committed: false,
        stale_discarded: false,
      },
    };
  }

  protected enqueueProjectCommit<T>(
    projectId: string,
    task: () => Promise<T>,
  ): Promise<T> {
    const prev = this.commitChains.get(projectId) ?? Promise.resolve();
    const next = prev.then(task, task);
    const cleanup = next.then(
      () => undefined,
      () => undefined,
    );
    this.commitChains.set(projectId, cleanup);
    return next;
  }

  public async commitProject(
    projectId: string,
    revision: number,
    input?: CommitProjectInput,
  ): Promise<CommitProjectResult> {
    return this.enqueueProjectCommit(projectId, async () => {
      if (this.coordinator.isStaleRevision(projectId, revision)) {
        const active = this.coordinator.getActiveRevision(projectId);
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Commit bloqueado: revisão ${revision} é obsoleta perante revisão ativa ${active}.`,
          {
            parameters: {
              project_id: projectId,
              requested_revision: revision,
              active_revision: active,
            },
            details: { reason: "STALE_REVISION" },
          },
        );
      }

      const res = await this.store.commitProjectRevision({
        project_id: projectId,
        project_revision: revision,
        request_id: input?.request_id,
        committed_result: input?.committed_result,
        objects: input?.objects,
        experiment: input?.experiment,
        require_strictly_greater: input?.require_strictly_greater,
        metadata: input?.metadata,
      });

      this.coordinator.markCommitted(
        projectId,
        revision,
        res.project.last_committed_result,
      );
      return res;
    });
  }

  public async exportProject(
    projectId: string,
  ): Promise<PortableProjectSnapshot> {
    return this.store.exportPortableSnapshot(projectId);
  }

  private makeStaleDiscardedResponse(
    request: RpcRequest,
    activeRevision: number,
  ): RpcResponse {
    return buildFailureRpcResponse({
      request_id: request.request_id,
      project_id: request.project_id,
      project_revision: request.project_revision,
      code: "CANCELLED",
      message: `Resposta descartada por revisão obsoleta (${request.project_revision} < ${activeRevision}).`,
      parameters: {
        request_revision: request.project_revision,
        active_revision: activeRevision,
        discarded: true,
      },
      next_step: "Utilize o resultado da revisão mais recente do projeto.",
      algorithm: request.operation,
      lib_versions: this.getCapabilities().lib_versions,
      diagnostics: {
        stale_discarded: true,
        committed: false,
        active_revision: activeRevision,
      },
    });
  }

  protected async syncCoordinatorFromStore(): Promise<void> {
    const snapshots = await this.store.getAllLatestConfirmedSnapshots();
    for (const snap of snapshots) {
      this.coordinator.syncFromPersistedRevision(
        snap.project_id,
        snap.project_revision,
        snap.committed_result,
      );
    }
  }

  public dispose(): void {
    this.coalescer.cancelAll();
    this.progressListeners.clear();
    this.tsModelingProgressListeners.clear();
    this.store.close();
  }
}

export { RPC_API_VERSION };
export type {
  ExecutionMetrics,
  FuzzyEvaluateSurfacePayload,
  FuzzyFitAnfisPayload,
  FuzzySystemRef,
  SolverProgress,
  SolverProgressEvent,
};
