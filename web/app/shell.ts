/**
 * Shell principal da aplicação ControlLab Web: roteamento acessível por teclado
 * entre as 6 abas, painel de ciclo de vida do motor F7, apresentador das 12 categorias
 * de erro, relatório de proveniência (R-27), comparador de experimentos comitados,
 * modais com restauração de foco e bloqueio estrito de exportações durante Fast-Preview
 * ou pending_commit (CL-DIR-001 Seções 7.1–7.4, 8.4, 11.1, 13.10, R-26, R-27).
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping e erasableSyntaxOnly.
 */

import type {
  ControlLabEngineClient,
  EngineClientEvent,
  ExecutionMetrics,
} from "../bridge/client.ts";
import {
  ControlLabBridgeError,
  sha256Hex,
  computeCanonicalSha256,
  RPC_API_VERSION,
  generateUuid,
  isPlainObject,
  type RpcResponse,
  type EngineLifecycleState,
  type ErrorCategory,
  type Provenance,
  type RealTensor,
  type TypedError,
  type WarningItem,
} from "../bridge/protocol.ts";
import {
  AriaLiveAnnouncer,
  FocusRestorer,
  formatMatrixDisplay,
  formatNumericDisplay,
  getThemeTokens,
  handleTablistKeyDown,
  type AccessibilityThemeMode,
  type AccessibilityThemeTokens,
  type FocusTargetLike,
} from "./accessibility.ts";
import {
  PROJECT_TAB_IDS,
  PROJECT_TAB_METADATA,
  type ProjectTabId,
  type ResultVerificationIndicator,
} from "./tool_descriptor.ts";
import {
  exportChartToCsv,
  type ScientificChartModel,
} from "../charts/scientific_chart.ts";
import {
  LqrWorkspaceController,
  type CanonicalStateSpaceModel,
  type CommittedLqrSnapshot,
  type FeedbackSign,
} from "../features/lqr_workspace.ts";
import { ProjectTabsController } from "../features/project_tabs.ts";
import {
  TypedObjectWorkspace,
} from "../features/typed_workspace.ts";

export interface PresentedError {
  code: ErrorCategory;
  title: string;
  summary: string;
  next_step: string;
  parameters?: Record<string, unknown>;
  technical_details?: Record<string, unknown>;
  local_only: true;
}

const ERROR_CATEGORY_TITLES: Record<ErrorCategory, string> = {
  VALIDATION_ERROR: "Erro de validação de entrada",
  DIMENSION_MISMATCH: "Incompatibilidade dimensional de matrizes/canais",
  UNSUPPORTED_MODEL: "Modelo ou domínio não suportado",
  HYPOTHESIS_VIOLATED: "Hipótese matemática violada",
  NUMERICAL_INCONCLUSIVE: "Resultado numérico inconclusivo",
  SOLVER_UNAVAILABLE: "Solver ou runtime indisponível",
  RESOURCE_LIMIT: "Limite de memória ou tempo excedido",
  CANCELLED: "Operação cancelada pelo usuário ou superada",
  WORKER_RESTARTED: "Web Worker reiniciado",
  SCHEMA_UNSUPPORTED: "Versão de schema não suportada",
  IMPORT_UNTRUSTED_CODE: "Importação ou origem bloqueada por política de segurança",
  INTERNAL_ERROR: "Erro interno inesperado na ponte/motor",
};

const ERROR_DEFAULT_NEXT_STEP: Record<ErrorCategory, string> = {
  VALIDATION_ERROR:
    "Revise os parâmetros informados e garanta apenas valores numéricos finitos.",
  DIMENSION_MISMATCH:
    "Verifique se A é (n×n), B é (n×m), C é (p×n), Q é (n×n) e R é (m×m).",
  UNSUPPORTED_MODEL:
    "Confira se dt e o tipo do modelo correspondem ao método selecionado (contínuo vs discreto).",
  HYPOTHESIS_VIOLATED:
    "Confirme estabilizabilidade de (A,B), detectabilidade e R simétrica definida positiva (R > 0).",
  NUMERICAL_INCONCLUSIVE:
    "Reescale as matrizes ou ajuste pesos Q/R para melhorar o condicionamento numérico.",
  SOLVER_UNAVAILABLE:
    "Aguarde o provisionamento local do Worker ou exporte o modelo para execução em CPython.",
  RESOURCE_LIMIT:
    "Reduza a ordem do sistema, limite de amostras ou aumente o timeout permitido.",
  CANCELLED:
    "Dispare um novo cálculo quando desejar confirmar a configuração atual.",
  WORKER_RESTARTED:
    "A sessão foi recuperada a partir do último snapshot confirmado no IndexedDB.",
  SCHEMA_UNSUPPORTED:
    "Atualize ou migre o arquivo para o schema v1.0 suportado antes de reimportar.",
  IMPORT_UNTRUSTED_CODE:
    "Utilize apenas ativos locais autorizados e arquivos passivos sem código externo.",
  INTERNAL_ERROR:
    "Inspecione o diagnóstico técnico local (não enviado à rede) e tente novamente.",
};

export function presentTypedError(error: TypedError): PresentedError {
  return {
    code: error.code,
    title: ERROR_CATEGORY_TITLES[error.code] ?? "Erro científico/operacional",
    summary: error.message,
    next_step: error.next_step ?? ERROR_DEFAULT_NEXT_STEP[error.code],
    parameters: error.parameters ? { ...error.parameters } : undefined,
    technical_details: error.details ? { ...error.details } : undefined,
    local_only: true,
  };
}

export interface ScientificReport {
  report_version: "1.0.0";
  generated_at: string;
  project_id: string;
  project_revision: number;
  model_revision: number;
  controller_ref: { id: string; revision: number } | null;
  controller_kind: string;
  feedback_sign: FeedbackSign;
  mathematical_problem: string;
  method: "care" | "dare";
  parameters: {
    n_states: number;
    n_inputs: number;
    n_outputs: number;
    dt: number | null;
    feedback_sign: FeedbackSign;
    Q_shape: number[];
    R_shape: number[];
    x0_shape: number[];
  };
  algorithm: string;
  lib_versions: Record<string, string>;
  tolerances: Record<string, unknown>;
  status: "success" | "warning" | "inconclusive";
  series_semantics: ResultVerificationIndicator;
  residuals: Record<string, unknown>;
  assumptions: Record<string, unknown>;
  warnings: Array<string | WarningItem>;
  units: CanonicalStateSpaceModel["units"];
  provenance: Provenance;
  execution_metrics: ExecutionMetrics;
  fixture_id?: string;
  fixture_sha256?: string;
}

export interface CommittedExperimentEntry {
  experiment_id: string;
  label: string;
  snapshot: CommittedLqrSnapshot;
  added_at: string;
}

export interface ExperimentComparisonRow {
  experiment_id: string;
  label: string;
  project_revision: number;
  model_revision: number;
  feedback_sign: FeedbackSign;
  status: string;
  optimal_cost_display: string;
  care_residual_display: string;
  symmetry_error_display: string;
  max_real_pole_display: string;
  K_display: string[][] | null;
}

export interface ExportedGainsPayload {
  format: "controllab_gains";
  schema_version: "1.0.0";
  project_id: string;
  project_revision: number;
  model_revision: number;
  controller_ref: { id: string; revision: number } | null;
  controller_kind: string;
  feedback_sign: FeedbackSign;
  K: RealTensor | null;
  P: RealTensor | null;
  closed_loop_poles: CommittedLqrSnapshot["closed_loop_poles"];
  optimal_cost: number | null;
  provenance: Provenance;
  diagnostics: Record<string, unknown>;
  exported_at: string;
}

export interface NativeFileExport {
  bytes: Uint8Array;
  filename: string;
  media_type: string;
  sha256: string;
  project_revision: number;
  request_id: string;
  project_id: string;
  response: RpcResponse;
  configuration_revision?: number;
  pvm_controller_kind?: "lqr" | "dynamic";
}

export interface PvmExportOptions {
  controller_kind: "lqr" | "dynamic";
  dynamic_controller?: Record<string, unknown>;
  saturation: { enabled: boolean; u_min: number | number[]; u_max: number | number[] };
}

function validatePvmExportOptions(value: unknown): PvmExportOptions {
  const boundIsFinite = (bound: unknown): bound is number | number[] =>
    typeof bound === "number" ? Number.isFinite(bound) :
      Array.isArray(bound) && bound.length > 0 && bound.every((item) => typeof item === "number" && Number.isFinite(item));
  if (!isPlainObject(value) || !["lqr", "dynamic"].includes(String(value.controller_kind)) ||
      !isPlainObject(value.saturation) || typeof value.saturation.enabled !== "boolean" ||
      !boundIsFinite(value.saturation.u_min) || !boundIsFinite(value.saturation.u_max) ||
      (value.controller_kind === "dynamic" && value.dynamic_controller === undefined) ||
      (value.dynamic_controller !== undefined && (!isPlainObject(value.dynamic_controller) || value.dynamic_controller.kind !== "DynamicController"))) {
    throw new ControlLabBridgeError("VALIDATION_ERROR", "Configuração PVM inválida. Confira o controlador e os limites de saturação.");
  }
  return structuredClone(value) as unknown as PvmExportOptions;
}

export const DEFAULT_DYNAMIC_EXPORT_CONTROLLER: Record<string, unknown> = {
  schema_version: "1.0.0", id: "dynamic-export", revision: 1,
  kind: "DynamicController", feedback_sign: "negative", dt: null,
  Ac: { shape: [1, 1], dtype: "float64", order: "C", data: [-2] },
  Bc: { shape: [1, 1], dtype: "float64", order: "C", data: [1] },
  Cc: { shape: [1, 1], dtype: "float64", order: "C", data: [1] },
  Dc: { shape: [1, 1], dtype: "float64", order: "C", data: [0.1] },
  ports: {
    inputs: [{ name: "y", role: "y", size: 1 }],
    outputs: [{ name: "u", role: "u", size: 1 }],
  },
  initial_state: { shape: [1], dtype: "float64", order: "C", data: [0.2] },
  provenance: { source: "control_lab" }, interconnection_scheme: "output_feedback",
};

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary);
}

export interface ShellOptions {
  client: ControlLabEngineClient;
  project_id?: string;
  lqrWorkspace?: LqrWorkspaceController;
  tabsController?: ProjectTabsController;
  typedWorkspace?: TypedObjectWorkspace;
  initialTab?: ProjectTabId;
  displayDecimals?: number;
  themeMode?: AccessibilityThemeMode;
}

export class ControlLabShell {
  private readonly client: ControlLabEngineClient;
  private readonly lqr: LqrWorkspaceController;
  private readonly tabs: ProjectTabsController;
  private readonly typedWorkspace: TypedObjectWorkspace;
  private readonly announcer: AriaLiveAnnouncer;
  private readonly focusRestorer: FocusRestorer;

  private engineState: EngineLifecycleState;
  private displayDecimals: number;
  private themeMode: AccessibilityThemeMode;
  private openModalId: string | null = null;
  private pvmExportRevision = 0;
  private dynamicPvmConfirmation: {
    project_id: string; project_revision: number; model_revision: number;
    configuration_revision: number; request_id: string; input_sha256: string;
  } | null = null;
  private pvmExportOptions: PvmExportOptions | null = {
    controller_kind: "lqr", saturation: { enabled: false, u_min: -1, u_max: 1 },
  };
  private manualPresentedError: PresentedError | null = null;
  private readonly experiments: CommittedExperimentEntry[] = [];
  private readonly eventsLog: EngineClientEvent[] = [];
  private readonly listeners = new Set<() => void>();
  private readonly unsubscribeClient: () => void;

  constructor(options: ShellOptions) {
    this.client = options.client;
    this.announcer = new AriaLiveAnnouncer();
    this.focusRestorer = new FocusRestorer();
    this.themeMode = options.themeMode ?? "standard_aa";
    this.displayDecimals = this.clampDecimals(options.displayDecimals ?? 4);

    this.lqr =
      options.lqrWorkspace ??
      new LqrWorkspaceController({
        client: this.client,
        project_id: options.project_id ?? "proj-controllab",
        announcer: this.announcer,
        themeMode: this.themeMode,
      });

    this.typedWorkspace =
      options.typedWorkspace ??
      new TypedObjectWorkspace({
        client: this.client,
        projectIdProvider: () => this.lqr.getProjectId(),
        projectRevisionProvider: () => this.lqr.getProjectRevision(),
        activeLqrPlantProvider: () => this.lqr.getPlant(),
        announcer: this.announcer,
        onError: (err) => {
          this.presentError(err);
        },
      });

    this.tabs =
      options.tabsController ??
      new ProjectTabsController({
        client: this.client,
        typedWorkspace: this.typedWorkspace,
        initialTab: options.initialTab ?? "statespace",
      });
    if (options.tabsController) {
      this.tabs.setTypedWorkspace(this.typedWorkspace);
    }

    this.engineState = this.client.getLifecycleState();
    this.unsubscribeClient = this.client.subscribe((ev) => {
      this.eventsLog.push(ev);
      if (this.eventsLog.length > 200) {
        this.eventsLog.shift();
      }
      if (ev.type === "lifecycle") {
        this.engineState = ev.current;
        this.announcer.announce(
          `Estado do motor científico: ${ev.current}`,
          ev.current === "error" ? "assertive" : "polite",
          ev.current === "error" ? "error" : "status",
        );
        if (ev.current === "ready") {
          void this.typedWorkspace.rehydrateFromStorage();
        }
      } else if (ev.type === "worker_recovered") {
        this.announcer.announce(
          `Worker recuperado (geração ${ev.generation}): ${ev.restored_objects} objeto(s) reidratado(s).`,
          "polite",
          "status",
        );
        void this.typedWorkspace.rehydrateFromStorage();
      } else if (ev.type === "error") {
        this.announcer.announce(
          `Erro no motor científico: ${ev.error.message}`,
          "assertive",
          "error",
        );
      }
      this.notify();
    });

    this.lqr.subscribe(() => {
      this.typedWorkspace.syncFromActiveLqrPlant(this.lqr.getPlant());
      if (this.lqr.isPendingCommit() || this.lqr.getLastError() !== null) {
        this.manualPresentedError = null;
      }
      this.notify();
    });
    this.tabs.subscribe(() => this.notify());
    this.typedWorkspace.subscribe(() => this.notify());
  }

  private clampDecimals(decimals: number): number {
    if (!Number.isInteger(decimals)) {
      return 4;
    }
    return Math.min(15, Math.max(0, decimals));
  }

  public getLqrWorkspace(): LqrWorkspaceController {
    return this.lqr;
  }

  public getTabsController(): ProjectTabsController {
    return this.tabs;
  }

  public getTypedWorkspace(): TypedObjectWorkspace {
    return this.typedWorkspace;
  }

  public applySelectedPlantToLqr(): CanonicalStateSpaceModel {
    const eff = this.typedWorkspace.getEffectiveSelection("statespacePlant");
    if (!eff || eff.object.kind !== "StateSpace") {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Nenhum objeto StateSpace selecionado para aplicar ao workspace LQR.",
      );
    }
    this.lqr.updatePlant(eff.object.value as unknown as CanonicalStateSpaceModel);
    this.typedWorkspace.selectRef("statespacePlant", null);
    return this.lqr.getPlant();
  }

  public getAnnouncer(): AriaLiveAnnouncer {
    return this.announcer;
  }

  public getFocusRestorer(): FocusRestorer {
    return this.focusRestorer;
  }

  public getEngineState(): EngineLifecycleState {
    this.engineState = this.client.getLifecycleState();
    return this.engineState;
  }

  public getEngineEventsLog(): readonly EngineClientEvent[] {
    return [...this.eventsLog];
  }

  public getExecutionMetrics(): ExecutionMetrics {
    return this.client.getMetrics();
  }

  public getDisplayDecimals(): number {
    return this.displayDecimals;
  }

  /**
   * Ajusta a quantidade de casas decimais apenas na camada de exibição,
   * preservando intactos os valores float64 armazenados nos modelos/resultados.
   */
  public setDisplayDecimals(decimals: number): void {
    if (!Number.isInteger(decimals) || decimals < 0 || decimals > 15) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Casas decimais devem ser inteiro entre 0 e 15, recebido ${String(decimals)}.`,
      );
    }
    this.displayDecimals = decimals;
    this.announcer.announce(
      `Exibição numérica ajustada para ${decimals} casas decimais (float64 interno preservado).`,
      "polite",
      "status",
    );
    this.notify();
  }

  public getThemeMode(): AccessibilityThemeMode {
    return this.themeMode;
  }

  public getThemeTokens(): AccessibilityThemeTokens {
    return getThemeTokens(this.themeMode);
  }

  public setThemeMode(mode: AccessibilityThemeMode): void {
    this.themeMode = mode;
    this.lqr.setThemeMode(mode);
    this.notify();
  }

  public getActiveTab(): ProjectTabId {
    return this.tabs.getActiveTab();
  }

  public switchTab(tabId: ProjectTabId): void {
    if (tabId !== this.tabs.getActiveTab()) {
      this.lqr.handleTabSwitch();
      this.tabs.setActiveTab(tabId);
      const meta = PROJECT_TAB_METADATA[tabId];
      this.announcer.announce(`Aba selecionada: ${meta.label}`, "polite", "status");
      this.notify();
    }
  }

  public handleTabKeyDown(key: string): {
    handled: boolean;
    activeTab: ProjectTabId;
    escaped: boolean;
  } {
    const tabItems = PROJECT_TAB_IDS.map((id) => ({
      id,
      label: PROJECT_TAB_METADATA[id].label,
    }));
    const currentIdx = PROJECT_TAB_IDS.indexOf(this.tabs.getActiveTab());
    const res = handleTablistKeyDown(key, tabItems, currentIdx);
    if (res.handled && !res.escaped && res.activeTabId) {
      this.switchTab(res.activeTabId as ProjectTabId);
    } else if (res.escaped && this.openModalId !== null) {
      this.closeModal(this.openModalId);
    }
    return {
      handled: res.handled,
      activeTab: this.tabs.getActiveTab(),
      escaped: res.escaped,
    };
  }

  public openModal(modalId: string, trigger: FocusTargetLike | string): void {
    this.focusRestorer.pushModalTrigger(trigger, modalId);
    this.openModalId = modalId;
    this.notify();
  }

  public closeModal(modalId?: string): FocusTargetLike | null {
    const restored = this.focusRestorer.popAndRestoreFocus(modalId);
    const remaining = this.focusRestorer.peekStack();
    this.openModalId =
      remaining.length > 0 ? remaining[remaining.length - 1].modalId : null;
    this.notify();
    return restored;
  }

  public getOpenModalId(): string | null {
    return this.openModalId;
  }

  public getPresentedLastError(): PresentedError | null {
    const err = this.lqr.getLastError();
    if (err) {
      return presentTypedError(err);
    }
    return this.manualPresentedError;
  }

  public presentError(err: unknown): PresentedError {
    const typed: TypedError =
      err instanceof ControlLabBridgeError
        ? err.typedError
        : err && typeof err === "object" && "code" in err && "message" in err
          ? (err as TypedError)
          : {
              code: "INTERNAL_ERROR",
              message: err instanceof Error ? err.message : String(err),
            };
    const presented = presentTypedError(typed);
    this.manualPresentedError = presented;
    this.announcer.announce(
      `${presented.title} [${presented.code}]: ${presented.summary}`,
      "assertive",
      "error",
    );
    this.notify();
    return presented;
  }

  public buildScientificReport(): ScientificReport {
    this.lqr.assertExportAllowed();
    const committed = this.lqr.getCommittedSnapshot()!;
    const plant = this.lqr.getPlant();
    const weights = this.lqr.getWeights();
    const metrics = this.client.getMetrics();

    return {
      report_version: "1.0.0",
      generated_at: new Date().toISOString(),
      project_id: committed.project_id,
      project_revision: committed.project_revision,
      model_revision: committed.model_revision,
      controller_ref: committed.controller_ref,
      controller_kind: committed.controller_kind,
      feedback_sign: committed.feedback_sign,
      mathematical_problem:
        plant.dt === null
          ? "LQR Contínuo (CARE): min ∫(x^T Q x + u^T R u) dt"
          : `LQR Discreto (DARE, dt=${plant.dt} s): min Σ(x_k^T Q x_k + u_k^T R u_k)`,
      method: plant.dt === null ? "care" : "dare",
      parameters: {
        n_states: plant.matrices.A.shape[0],
        n_inputs: plant.matrices.B.shape[1],
        n_outputs: plant.matrices.C.shape[0],
        dt: plant.dt,
        feedback_sign: committed.feedback_sign,
        Q_shape: [...weights.Q.shape],
        R_shape: [...weights.R.shape],
        x0_shape: [...weights.x0.shape],
      },
      algorithm: committed.provenance.algorithm,
      lib_versions: { ...committed.provenance.lib_versions },
      tolerances:
        committed.provenance.tolerances &&
        typeof committed.provenance.tolerances === "object"
          ? { ...(committed.provenance.tolerances as Record<string, unknown>) }
          : {},
      status: committed.status,
      series_semantics: "numeric_verified",
      residuals: { ...committed.diagnostics },
      assumptions: { ...committed.assumptions },
      warnings: [...committed.warnings],
      units: structuredClone(plant.units),
      provenance: { ...committed.provenance },
      execution_metrics: metrics,
      fixture_id:
        typeof committed.provenance.fixture_id === "string"
          ? committed.provenance.fixture_id
          : undefined,
      fixture_sha256:
        typeof committed.provenance.fixture_sha256 === "string"
          ? committed.provenance.fixture_sha256
          : undefined,
    };
  }

  /**
   * Adiciona experimento comitado ao comparador.
   * Rejeita explicitamente previews efêmeros ou estado pendente.
   */
  public addCommittedExperiment(label?: string): CommittedExperimentEntry {
    const preview = this.lqr.getPreviewState();
    if (preview.active || this.lqr.isPendingCommit()) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Comparador de experimentos aceita apenas resultados comitados; previews transitórios são proibidos.",
      );
    }
    const committed = this.lqr.getCommittedSnapshot();
    if (!committed) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Nenhum resultado LQR comitado disponível para adicionar ao comparador.",
      );
    }
    const entry: CommittedExperimentEntry = {
      experiment_id: `exp-r${committed.project_revision}-${committed.request_id}`,
      label:
        label ??
        `Exp. Rev ${committed.project_revision} (Modelo ${committed.model_revision})`,
      snapshot: committed,
      added_at: new Date().toISOString(),
    };
    this.experiments.push(entry);
    this.notify();
    return structuredClone(entry);
  }

  public listExperiments(): readonly CommittedExperimentEntry[] {
    return this.experiments.map((e) => structuredClone(e));
  }

  public compareExperiments(): ExperimentComparisonRow[] {
    return this.experiments.map((entry) => {
      const s = entry.snapshot;
      const optCost =
        s.optimal_cost !== null
          ? formatNumericDisplay(s.optimal_cost, this.displayDecimals)
          : "N/D";
      const rCareRaw = s.diagnostics.care_residual_rel;
      const rCare =
        typeof rCareRaw === "number"
          ? formatNumericDisplay(rCareRaw, this.displayDecimals)
          : "N/D";
      const symRaw = s.diagnostics.symmetry_error;
      const symErr =
        typeof symRaw === "number"
          ? formatNumericDisplay(symRaw, this.displayDecimals)
          : "N/D";
      const maxReal =
        s.closed_loop_poles && s.closed_loop_poles.real.length > 0
          ? formatNumericDisplay(
              Math.max(...s.closed_loop_poles.real),
              this.displayDecimals,
            )
          : "N/D";
      const kFormatted = s.K
        ? formatMatrixDisplay(
            s.K.data,
            s.K.shape[0] ?? 1,
            s.K.shape[1] ?? s.K.data.length,
            this.displayDecimals,
          )
        : null;

      return {
        experiment_id: entry.experiment_id,
        label: entry.label,
        project_revision: s.project_revision,
        model_revision: s.model_revision,
        feedback_sign: s.feedback_sign,
        status: s.status,
        optimal_cost_display: optCost,
        care_residual_display: rCare,
        symmetry_error_display: symErr,
        max_real_pole_display: maxReal,
        K_display: kFormatted,
      };
    });
  }

  public exportGains(): ExportedGainsPayload {
    this.lqr.assertExportAllowed();
    const committed = this.lqr.getCommittedSnapshot()!;
    return {
      format: "controllab_gains",
      schema_version: "1.0.0",
      project_id: committed.project_id,
      project_revision: committed.project_revision,
      model_revision: committed.model_revision,
      controller_ref: committed.controller_ref,
      controller_kind: committed.controller_kind,
      feedback_sign: committed.feedback_sign,
      K: committed.K,
      P: committed.P,
      closed_loop_poles: committed.closed_loop_poles,
      optimal_cost: committed.optimal_cost,
      provenance: committed.provenance,
      diagnostics: committed.diagnostics,
      exported_at: new Date().toISOString(),
    };
  }

  private canonicalController(): Record<string, unknown> {
    const committed = this.lqr.getCommittedSnapshot()!;
    const plant = this.lqr.getPlant();
    return {
      schema_version: "1.0.0", kind: "StateFeedbackController",
      id: committed.controller_ref?.id ?? `ctrl-lqr-r${committed.project_revision}`,
      revision: committed.controller_ref?.revision ?? committed.project_revision,
      feedback_sign: committed.feedback_sign, K: committed.K,
      state_coordinates: [...plant.state_names], reference_map: null,
      dt: plant.dt, input_names: [...plant.input_names], units: structuredClone(plant.units),
      provenance: structuredClone(committed.provenance), created_at: committed.committed_at,
    };
  }

  private async fileRequest(
    operation: string, payload: Record<string, unknown>,
    context?: { project_id: string; project_revision: number },
  ): Promise<RpcResponse> {
    const committed = this.lqr.getCommittedSnapshot();
    const response = await this.client.execute({
      api_version: RPC_API_VERSION, request_id: `io-${generateUuid()}`,
      project_id: context?.project_id ?? committed?.project_id ?? "io-import",
      project_revision: context?.project_revision ?? committed?.project_revision ?? 0,
      operation, payload, options: {}, timeout_policy: { hard_timeout_ms: 30000 },
    }, { commitOnSuccess: false });
    if (response.status !== "success" && response.status !== "warning") {
      throw new ControlLabBridgeError(response.error?.code ?? "VALIDATION_ERROR",
        response.error?.message ?? "Operação de arquivo sem resultado válido.");
    }
    return response;
  }

  public async exportSdpScript(format: "cvxpy" | "yalmip", specification: Record<string, unknown>): Promise<{script: string; filename: string; media_type: string}> {
    const projectId = this.lqr.getProjectId();
    const projectRevision = Math.max(
      this.lqr.getProjectRevision(),
      this.client.getCommittedRevision(projectId),
    );
    const response = await this.fileRequest(`optimization.export_${format}`, specification, {
      project_id: projectId,
      project_revision: projectRevision,
    });
    const data = response.result;
    if (!isPlainObject(data) || typeof data.script !== "string" ||
        typeof data.filename !== "string" || typeof data.media_type !== "string") {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Exportador SDP retornou um arquivo inválido.");
    }
    return {script: data.script, filename: data.filename, media_type: data.media_type};
  }

  private async exportFile(
    operation: string, payload: Record<string, unknown>, extension: string,
    configurationRevision?: number,
  ): Promise<NativeFileExport> {
    this.lqr.assertExportAllowed();
    const committed = this.lqr.getCommittedSnapshot()!;
    const response = await this.fileRequest(operation, payload);
    this.lqr.assertExportAllowed();
    if (this.lqr.getCommittedSnapshot()?.request_id !== committed.request_id) {
      throw new ControlLabBridgeError("CANCELLED", "O projeto mudou durante a exportação. Exporte novamente.");
    }
    if (configurationRevision !== undefined) this.assertPvmExportRevision(configurationRevision);
    return this.decodeNativeFile(response, committed, extension, configurationRevision);
  }

  private decodeNativeFile(
    response: RpcResponse,
    identity: { project_id: string; project_revision: number; request_id: string },
    extension: string, configurationRevision?: number,
  ): NativeFileExport {
    const file = response.result;
    if (!isPlainObject(file) || typeof file.bytes_base64 !== "string" ||
        typeof file.sha256 !== "string" || typeof file.size_bytes !== "number" ||
        typeof file.media_type !== "string") {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Resposta de arquivo incompleta.");
    }
    const binary = atob(file.bytes_base64);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    if (bytes.length !== file.size_bytes || sha256Hex(bytes) !== file.sha256) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Integridade dos bytes exportados inválida.");
    }
    return { bytes, filename: `ControlLab_r${identity.project_revision}.${extension}`,
      media_type: file.media_type, sha256: file.sha256,
      project_revision: identity.project_revision, request_id: identity.request_id,
      project_id: identity.project_id, response, configuration_revision: configurationRevision };
  }

  public async exportCtrlLab(): Promise<NativeFileExport> {
    this.lqr.assertExportAllowed();
    const committed = this.lqr.getCommittedSnapshot()!;
    const controller = this.canonicalController();
    if (!this.pvmExportOptions) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Corrija a configuração PVM antes de salvar o projeto.");
    }
    const experiment = {
      schema_version: "1.0.0", kind: "Experiment", id: `ui-lqr-${committed.project_revision}`,
      revision: committed.project_revision, method: "statespace.design_lqr",
      model_ref: { id: this.lqr.getPlant().id, revision: committed.model_revision },
      controller_ref: committed.controller_ref,
      parameters: { workspace: this.lqr.getWeights(), snapshot: committed,
        comparisons: structuredClone(this.experiments),
        pvm_export_options: structuredClone(this.pvmExportOptions) },
      tolerances: {}, results: null, data_source: null,
      provenance: structuredClone(committed.provenance), created_at: committed.committed_at,
    };
    const project = {
      project_id: committed.project_id, project_revision: committed.project_revision,
      models: [this.lqr.getPlant()], controllers: [controller], experiments: [experiment],
      created_at: committed.committed_at, provenance: structuredClone(committed.provenance),
    };
    return this.exportFile("io.export_ctrlab", { project }, "ctrlab", this.pvmExportRevision);
  }

  public getPvmExportOptions(): PvmExportOptions | null {
    return structuredClone(this.pvmExportOptions);
  }

  public getPvmExportRevision(): number {
    return this.pvmExportRevision;
  }

  public invalidatePvmExportOptions(): void {
    this.pvmExportRevision += 1;
    this.pvmExportOptions = null;
    this.dynamicPvmConfirmation = null;
    this.notify();
  }

  public setPvmExportOptions(options: PvmExportOptions): void {
    const validated = validatePvmExportOptions(options);
    this.pvmExportRevision += 1;
    this.pvmExportOptions = validated;
    this.dynamicPvmConfirmation = null;
    this.manualPresentedError = null;
    this.notify();
  }

  public canExportPvm(): boolean {
    if (!this.pvmExportOptions) return false;
    if (this.pvmExportOptions.controller_kind === "lqr") return this.lqr.canExport().allowed;
    return this.getEngineState() === "ready" && !this.lqr.isFileImportPending() &&
      !this.lqr.isPendingCommit() && !this.lqr.getPreviewState().active;
  }

  public assertDynamicPvmExportAllowed(requestId: string | undefined, revision: number | undefined): void {
    const confirmation = this.dynamicPvmConfirmation;
    if (!this.canExportPvm() || !confirmation || confirmation.request_id !== requestId ||
        confirmation.configuration_revision !== revision || revision !== this.pvmExportRevision ||
        confirmation.project_id !== this.lqr.getProjectId() ||
        confirmation.project_revision !== this.lqr.getProjectRevision() ||
        confirmation.model_revision !== this.lqr.getPlant().revision ||
        confirmation.input_sha256 !== computeCanonicalSha256({
          plant: this.lqr.getPlant(), initial_state: this.lqr.getWeights().x0.data,
        })) {
      throw new ControlLabBridgeError("CANCELLED", "A configuração dinâmica mudou. Valide e gere novamente o PVM.");
    }
  }

  private assertPvmExportRevision(revision: number): void {
    if (revision !== this.pvmExportRevision) {
      throw new ControlLabBridgeError(
        "CANCELLED", "A configuração PVM mudou. Gere novamente o arquivo antes de baixar.",
      );
    }
  }

  public exportPvm(): Promise<NativeFileExport> {
    const options = structuredClone(this.pvmExportOptions);
    if (!options) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Corrija a configuração da exportação PVM.");
    }
    const revision = this.pvmExportRevision;
    if (options.controller_kind === "lqr") {
      this.lqr.assertExportAllowed();
      return this.exportFile("io.export_pvm", {
        plant: this.lqr.getPlant(), controller: this.canonicalController(),
        scenario: { initial_state: this.lqr.getWeights().x0.data, saturation: options.saturation },
        name: "ControlLab LQR", target_spec_version: "1.0.0",
      }, "pvm", revision);
    }
    if (!this.canExportPvm()) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Conclua a edição e aguarde o motor antes de exportar o controlador dinâmico.");
    }
    return this.exportDynamicPvm(options, revision);
  }

  private async exportDynamicPvm(options: PvmExportOptions, revision: number): Promise<NativeFileExport> {
    if (!isPlainObject(options.dynamic_controller) || options.dynamic_controller.kind !== "DynamicController") {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Forneça um DynamicController canônico no campo JSON.");
    }
    const context = { project_id: this.lqr.getProjectId(), project_revision: this.lqr.getProjectRevision() };
    const plant = this.lqr.getPlant();
    const initialState = this.lqr.getWeights().x0.data;
    const payload = { plant, controller: options.dynamic_controller };
    const validation = await this.fileRequest("core.validate_interconnection", payload, context);
    this.dynamicPvmConfirmation = {
      ...context, model_revision: plant.revision, configuration_revision: revision,
      request_id: validation.request_id,
      input_sha256: computeCanonicalSha256({ plant, initial_state: initialState }),
    };
    this.assertDynamicPvmExportAllowed(validation.request_id, revision);
    const response = await this.fileRequest("io.export_pvm", {
      ...payload,
      scenario: { initial_state: initialState, saturation: options.saturation },
      name: "ControlLab DynamicController", target_spec_version: "1.0.0",
    }, context);
    this.assertDynamicPvmExportAllowed(validation.request_id, revision);
    return { ...this.decodeNativeFile(response, this.dynamicPvmConfirmation!, "pvm", revision),
      pvm_controller_kind: "dynamic" };
  }

  public async importCtrlLab(source: Uint8Array | Promise<Uint8Array>): Promise<void> {
    this.lqr.beginFileImport();
    try {
      const bytes = await source;
      if (bytes.length > 64 * 1024 * 1024) {
        throw new ControlLabBridgeError(
          "RESOURCE_LIMIT", "Arquivo .ctrlab excede o limite de 64 MiB.",
        );
      }
      const response = await this.fileRequest("io.import_ctrlab", {
        bytes_base64: bytesToBase64(bytes),
      });
      const project = response.result;
      if (!isPlainObject(project) || project.code_executed !== false ||
          !Array.isArray(project.models) || !Array.isArray(project.experiments) ||
          !Array.isArray(project.controllers)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR", "Projeto importado sem estrutura passiva válida.",
        );
      }
      const experiment = project.experiments.find(
        (item) => isPlainObject(item) && item.method === "statespace.design_lqr",
      );
      const parameters = isPlainObject(experiment) && isPlainObject(experiment.parameters)
        ? experiment.parameters : null;
      const snapshot = parameters && isPlainObject(parameters.snapshot)
        ? parameters.snapshot as unknown as CommittedLqrSnapshot : null;
      const modelRef = isPlainObject(experiment) && isPlainObject(experiment.model_ref)
        ? experiment.model_ref : null;
      const plant = snapshot && modelRef ? project.models.find((item) =>
        isPlainObject(item) && item.kind === "StateSpace" && item.id === modelRef.id &&
        item.revision === modelRef.revision && item.revision === snapshot.model_revision,
      ) : null;
      const controller = snapshot ? project.controllers.find((item) =>
        isPlainObject(item) && item.id === snapshot.controller_ref?.id &&
        item.revision === snapshot.controller_ref?.revision,
      ) : null;
      if (!parameters || !snapshot || !isPlainObject(plant) || !isPlainObject(controller) ||
          !isPlainObject(project.manifest) ||
          project.manifest.project_id !== snapshot.project_id ||
          project.manifest.project_revision !== snapshot.project_revision ||
          computeCanonicalSha256(controller.K) !== computeCanonicalSha256(snapshot.K) ||
          controller.feedback_sign !== snapshot.feedback_sign ||
          !isPlainObject(parameters.workspace)) {
        throw new ControlLabBridgeError(
          "UNSUPPORTED_MODEL",
          "O projeto não contém um espaço LQR confirmado compatível com esta tela.",
        );
      }
      const workspace = parameters.workspace;
      const pvmOptions = parameters.pvm_export_options === undefined
        ? { controller_kind: "lqr" as const, saturation: { enabled: false, u_min: -1, u_max: 1 } }
        : validatePvmExportOptions(parameters.pvm_export_options);
      await this.lqr.restoreProject({
        plant: plant as unknown as CanonicalStateSpaceModel, snapshot,
        Q: workspace.Q as RealTensor, R: workspace.R as RealTensor, x0: workspace.x0 as RealTensor,
      });
      this.setPvmExportOptions(pvmOptions);
      this.experiments.length = 0;
      if (Array.isArray(parameters.comparisons)) {
        this.experiments.push(...structuredClone(parameters.comparisons) as CommittedExperimentEntry[]);
      }
      this.notify();
    } finally {
      this.lqr.endFileImport();
    }
  }

  public exportChartCsv(
    chart: ScientificChartModel,
    options?: { decimals?: number },
  ): string {
    this.lqr.assertExportAllowed();
    return exportChartToCsv(chart, {
      decimals: options?.decimals ?? 15,
      pendingCommit: this.lqr.isPendingCommit(),
      allowPreviewExport: false,
    });
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const fn of this.listeners) {
      try {
        fn();
      } catch {
        // Isolar falhas de assinantes
      }
    }
  }

  public dispose(): void {
    this.unsubscribeClient();
    this.listeners.clear();
  }
}
