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
  type EngineLifecycleState,
  type ErrorCategory,
  type Provenance,
  type RealTensor,
  type TypedError,
  type WarningItem,
} from "../bridge/protocol.ts";
import type { PortableProjectSnapshot } from "../storage/indexeddb_store.ts";
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

export interface ExportedCtrlLabPackage {
  format: "controllab_ctrlab_export";
  schema_version: "1.0.0";
  portable_snapshot: PortableProjectSnapshot;
  archive_layout: {
    manifest: Record<string, unknown>;
    models: CanonicalStateSpaceModel[];
    controllers: Array<Record<string, unknown>>;
    experiments: Array<Record<string, unknown>>;
  };
}

export interface ShellOptions {
  client: ControlLabEngineClient;
  project_id?: string;
  lqrWorkspace?: LqrWorkspaceController;
  tabsController?: ProjectTabsController;
  initialTab?: ProjectTabId;
  displayDecimals?: number;
  themeMode?: AccessibilityThemeMode;
}

export class ControlLabShell {
  private readonly client: ControlLabEngineClient;
  private readonly lqr: LqrWorkspaceController;
  private readonly tabs: ProjectTabsController;
  private readonly announcer: AriaLiveAnnouncer;
  private readonly focusRestorer: FocusRestorer;

  private engineState: EngineLifecycleState;
  private displayDecimals: number;
  private themeMode: AccessibilityThemeMode;
  private openModalId: string | null = null;
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

    this.tabs =
      options.tabsController ??
      new ProjectTabsController({
        client: this.client,
        initialTab: options.initialTab ?? "statespace",
      });

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
      } else if (ev.type === "worker_recovered") {
        this.announcer.announce(
          `Worker recuperado (geração ${ev.generation}): ${ev.restored_objects} objeto(s) reidratado(s).`,
          "polite",
          "status",
        );
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
      if (this.lqr.isPendingCommit() || this.lqr.getLastError() !== null) {
        this.manualPresentedError = null;
      }
      this.notify();
    });
    this.tabs.subscribe(() => this.notify());
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

  public async exportCtrlLab(): Promise<ExportedCtrlLabPackage> {
    this.lqr.assertExportAllowed();
    const committed = this.lqr.getCommittedSnapshot()!;
    const plant = this.lqr.getPlant();
    const portable = await this.client.exportProject(committed.project_id);
    const now = new Date().toISOString();
    const n = plant.matrices.A.shape[0];
    const m = plant.matrices.B.shape[1];

    if (
      !committed.K ||
      committed.K.shape.length !== 2 ||
      committed.K.shape[0] !== m ||
      committed.K.shape[1] !== n ||
      committed.K.data.length !== m * n
    ) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Exportação requer matriz de ganho K válida e compatível com dimensões [m, n].",
        {
          parameters: {
            expected_shape: [m, n],
            actual_shape: committed.K?.shape ?? null,
          },
        },
      );
    }

    const controllerK: RealTensor = {
      shape: [m, n],
      dtype: "float64",
      order: committed.K.order,
      data: [...committed.K.data],
    };

    const models: CanonicalStateSpaceModel[] = [plant];
    const controllers: Array<Record<string, unknown>> = [
      {
        schema_version: "1.0.0",
        id: committed.controller_ref?.id ?? `ctrl-lqr-r${committed.project_revision}`,
        revision: committed.controller_ref?.revision ?? committed.project_revision,
        kind: "StateFeedbackController",
        feedback_sign: committed.feedback_sign,
        K: controllerK,
        state_coordinates: [...plant.state_names],
        reference_map: null,
        dt: plant.dt,
        input_names: [...plant.input_names],
        units: structuredClone(plant.units),
        provenance: { ...committed.provenance },
        created_at: committed.committed_at,
      },
    ];
    const experiments: Array<Record<string, unknown>> = this.experiments.map((e) => ({
      experiment_id: e.experiment_id,
      label: e.label,
      project_revision: e.snapshot.project_revision,
      model_revision: e.snapshot.model_revision,
      status: e.snapshot.status,
    }));

    const hashes = {
      "models.json": sha256Hex(JSON.stringify(models)),
      "controllers.json": sha256Hex(JSON.stringify(controllers)),
      "experiments.json": sha256Hex(JSON.stringify(experiments)),
    };

    return {
      format: "controllab_ctrlab_export",
      schema_version: "1.0.0",
      portable_snapshot: portable,
      archive_layout: {
        manifest: {
          format: "ctrlab",
          schema_version: "1.0.0",
          app_version: "1.0.0",
          created_at: now,
          modified_at: now,
          project_id: committed.project_id,
          project_revision: committed.project_revision,
          hashes,
          capabilities: {
            required_features: ["core.serialization", "statespace.lqr"],
            optional_features: ["io.pvm"],
            max_uncompressed_bytes: 64 * 1024 * 1024,
            max_members: 1024,
          },
          contents: {
            models: models.length,
            controllers: controllers.length,
            experiments: experiments.length,
            model_revision: committed.model_revision,
            portable_content_hash: portable.content_hash,
          },
          provenance: { ...committed.provenance },
        },
        models,
        controllers,
        experiments,
      },
    };
  }

  /** Contenção AUD-020/021 até o download consumir o serializador canônico F1. */
  public exportPvm(): never {
    this.lqr.assertExportAllowed();
    throw new ControlLabBridgeError(
      "UNSUPPORTED_MODEL",
      "Exportação .pvm temporariamente indisponível. A integração com o exportador canônico está pendente.",
      { parameters: { pending_work_package: "WP-AUDIT2-FIX-F8-NATIVE-IO" } },
    );
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
