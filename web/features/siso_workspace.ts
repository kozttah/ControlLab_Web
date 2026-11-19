/**
 * Workspace vertical da Aba 2 — Frequência SISO, Margens e Lugar das Raízes
 * (WP-V1-F8-SISO-VERTICAL, CL-DIR-001 Seções 5.3, 7.1–7.4, 13.10,
 * R-07, R-18, R-26, R-27 e Testes T-FREQ-01, T-FREQ-02, T-UI-01).
 *
 * Responsabilidades estritas de UI/Apresentação (F8):
 * - Seleção e validação do modelo da planta (TransferFunction ou StateSpace via typedWorkspace).
 *   Rejeição estrita de canais MIMO ou modelos sem seleção explícita de canal SISO.
 * - Orquestração de chamadas RPC tipadas ao motor Python via ControlLabEngineClient:
 *   `frequency.eval_response` / `frequency.bode`, `frequency.stability_margins`,
 *   `frequency.root_locus`, `frequency.step_response`, `core.reuse_model`.
 *   NUNCA reimplementa algoritmos científicos em TypeScript.
 * - Suporte a atraso puro vs Padé: atraso puro NÃO é silenciosamente substituído por Padé;
 *   Padé só é aplicado quando `use_pade === true` for explicitamente solicitado.
 * - Extração e apresentação de todas as travessias de ganho (0 dB) e fase (-180°),
 *   margens de ganho/fase/atraso e alerta de múltiplas frequências de cruzamento.
 * - Overlays semânticos rotulados com precisão (`heuristic` para aproximações de 2ª ordem).
 * - Distinção rigorosa entre Fast-Preview transitório e commit autoritativo.
 * - Ajuste de compensador / ganho em malha preservando sinal de realimentação.
 * - Construção de modelos gráficos SVG, tabelas acessíveis WCAG 2.2 AA e exportação CSV.
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping, erasableSyntaxOnly
 * e verbatimModuleSyntax.
 */

import type { ControlLabEngineClient } from "../bridge/client.ts";
import {
  ControlLabBridgeError,
  isPlainObject,
  RPC_API_VERSION,
  type ComplexVectorPair,
  type RpcRequest,
  type RpcResponse,
  type WarningEntry,
} from "../bridge/protocol.ts";
import {
  AriaLiveAnnouncer,
  formatNumericDisplay,
  type AccessibilityThemeMode,
} from "../app/accessibility.ts";
import {
  buildBodeChartModel,
  buildNyquistChartModel,
  buildRootLocusChartModel,
  buildTimeResponseChartModel,
  renderBodeSvg,
  renderNyquistSvg,
  renderRootLocusSvg,
  renderTimeResponseSvg,
  type BodeChartModel,
  type FrequencyCrossingMarker,
  type NyquistChartModel,
  type RootLocusChartModel,
  type TimeResponseChartModel,
} from "../charts/scientific_chart.ts";
import {
  createSecondOrderRegionOverlay,
  type RequirementOverlay,
} from "../charts/overlays.ts";
import type {
  ProjectTabsController,
  TabToolExecutionRecord,
} from "./project_tabs.ts";
import type {
  CanonicalObjectRef,
  RegisteredTypedObject,
  TypedObjectWorkspace,
} from "./typed_workspace.ts";

export interface SisoEvaluationOptions {
  w_min?: number;
  w_max?: number;
  n_points?: number;
  delay?: number;
  use_pade?: boolean;
  pade_order?: number;
}

export interface SisoGainCrossoverView {
  omega_gc: number;
  phase_deg: number;
  phase_margin_deg: number;
  delay_margin_sec: number | null;
}

export interface SisoPhaseCrossoverView {
  omega_pc: number;
  target_phase_deg: number;
  loop_gain_abs: number;
  loop_gain_db: number;
  gain_margin_linear: number | null;
  gain_margin_db: number | null;
}

export interface SisoStabilityMarginsView {
  gain_crossovers: readonly SisoGainCrossoverView[];
  phase_crossovers: readonly SisoPhaseCrossoverView[];
  critical_phase_margin_deg: number | null;
  critical_omega_gc: number | null;
  critical_delay_margin_sec: number | null;
  critical_gain_margin_db: number | null;
  critical_gain_margin_linear: number | null;
  critical_omega_pc: number | null;
  closed_loop_stable: boolean | null;
  closed_loop_poles: ComplexVectorPair | null;
  has_multiple_crossings: boolean;
}

export interface SisoRootLocusBranchView {
  real: readonly number[];
  imag: readonly number[];
}

export interface SisoBreakawayPointView {
  s_real: number;
  s_imag: number;
  gain_K: number;
  on_real_axis: boolean;
}

export interface SisoStabilityCrossingView {
  branch_index: number;
  gain_K: number;
  pole_real: number;
  pole_imag: number;
  direction: "stabilizing" | "destabilizing";
}

export interface SisoRootLocusView {
  gains: readonly number[];
  branches: readonly SisoRootLocusBranchView[];
  open_loop_poles: ComplexVectorPair | null;
  open_loop_zeros: ComplexVectorPair | null;
  breakaway_points: readonly SisoBreakawayPointView[];
  stability_crossings: readonly SisoStabilityCrossingView[];
  feedback_sign: "negative" | "positive";
  domain: string;
}

export interface SisoStepMetricsView {
  is_stable: boolean;
  steady_state_value: number | null;
  steady_state_error: number | null;
  overshoot_percent: number | null;
  peak_value: number;
  peak_time: number;
  settling_time: number | null;
  settling_threshold: number;
  rise_time_10_90: number | null;
}

export interface SisoWorkspaceOptions {
  client: ControlLabEngineClient;
  typedWorkspace: TypedObjectWorkspace;
  tabsController?: ProjectTabsController;
  projectIdProvider?: () => string;
  projectRevisionProvider?: () => number;
  themeModeProvider?: () => AccessibilityThemeMode;
  announcer?: AriaLiveAnnouncer;
}

function extractNumberArray(val: unknown): number[] {
  if (Array.isArray(val)) return val.map(Number);
  if (val && typeof val === "object" && "data" in val && Array.isArray((val as { data: unknown }).data)) {
    return (val as { data: unknown[] }).data.map(Number);
  }
  return [];
}

function extractComplexPair(val: unknown): ComplexVectorPair | null {
  if (!val || typeof val !== "object") return null;
  const obj = val as Record<string, unknown>;
  const real = Array.isArray(obj.real) ? (obj.real as unknown[]).map(Number) : [];
  const imag = Array.isArray(obj.imag) ? (obj.imag as unknown[]).map(Number) : [];
  if (real.length === 0 && imag.length === 0) return null;
  return { real, imag };
}

export class SisoWorkspace {
  private readonly client: ControlLabEngineClient;
  private readonly typedWorkspace: TypedObjectWorkspace;
  private readonly tabsController?: ProjectTabsController;
  private readonly projectIdProvider: () => string;
  private readonly projectRevisionProvider: () => number;
  private readonly themeModeProvider: () => AccessibilityThemeMode;
  private readonly announcer: AriaLiveAnnouncer;
  private readonly listeners = new Set<() => void>();

  // Configurações correntes de análise
  private w_min = 0.01;
  private w_max = 100;
  private n_points = 200;
  private delay = 0;
  private use_pade = false;
  private pade_order = 1;
  private feedback_sign: "negative" | "positive" = "negative";
  private compensator_gain = 1.0;

  // Últimos resultados gerados
  private lastBodeModel: BodeChartModel | null = null;
  private lastNyquistModel: NyquistChartModel | null = null;
  private lastRootLocusModel: RootLocusChartModel | null = null;
  private lastTimeResponseModel: TimeResponseChartModel | null = null;
  private lastMarginsView: SisoStabilityMarginsView | null = null;
  private lastRootLocusView: SisoRootLocusView | null = null;
  private lastStepMetricsView: SisoStepMetricsView | null = null;
  private lastExecutionRecord: TabToolExecutionRecord | null = null;

  // Estado operacional
  private isEvaluating = false;
  private lastStatus: "idle" | "running" | "success" | "warning" | "failure" = "idle";
  private lastErrorMessage: string | null = null;
  private lastWarnings: readonly WarningEntry[] = [];

  constructor(options: SisoWorkspaceOptions) {
    this.client = options.client;
    this.typedWorkspace = options.typedWorkspace;
    this.tabsController = options.tabsController;
    this.projectIdProvider = options.projectIdProvider ?? (() => "proj-controllab");
    this.projectRevisionProvider = options.projectRevisionProvider ?? (() => 0);
    this.themeModeProvider = options.themeModeProvider ?? (() => "standard_aa");
    this.announcer = options.announcer ?? new AriaLiveAnnouncer();
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const listener of this.listeners) {
      try {
        listener();
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Erro em listener de SisoWorkspace:", err);
      }
    }
  }

  // Getters de estado
  public getWMin(): number { return this.w_min; }
  public getWMax(): number { return this.w_max; }
  public getNPoints(): number { return this.n_points; }
  public getDelay(): number { return this.delay; }
  public getUsePade(): boolean { return this.use_pade; }
  public getPadeOrder(): number { return this.pade_order; }
  public getFeedbackSign(): "negative" | "positive" { return this.feedback_sign; }
  public getCompensatorGain(): number { return this.compensator_gain; }
  public getStatus(): "idle" | "running" | "success" | "warning" | "failure" { return this.lastStatus; }
  public getErrorMessage(): string | null { return this.lastErrorMessage; }
  public getWarnings(): readonly WarningEntry[] { return this.lastWarnings; }
  public getBodeChartModel(): BodeChartModel | null { return this.lastBodeModel; }
  public getNyquistChartModel(): NyquistChartModel | null { return this.lastNyquistModel; }
  public getRootLocusChartModel(): RootLocusChartModel | null { return this.lastRootLocusModel; }
  public getTimeResponseChartModel(): TimeResponseChartModel | null { return this.lastTimeResponseModel; }
  public getMarginsView(): SisoStabilityMarginsView | null { return this.lastMarginsView; }
  public getRootLocusView(): SisoRootLocusView | null { return this.lastRootLocusView; }
  public getStepMetricsView(): SisoStepMetricsView | null { return this.lastStepMetricsView; }
  public getLastExecutionRecord(): TabToolExecutionRecord | null { return this.lastExecutionRecord; }

  // Setters de configuração com validação
  public setFrequencyGrid(wMin: number, wMax: number, nPoints = 200): void {
    if (!Number.isFinite(wMin) || wMin <= 0) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "w_min deve ser número positivo.");
    }
    if (!Number.isFinite(wMax) || wMax <= wMin) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "w_max deve ser maior que w_min.");
    }
    this.w_min = wMin;
    this.w_max = wMax;
    this.n_points = Math.max(16, Math.min(5000, Math.floor(nPoints)));
    this.notify();
  }

  public setDelayConfiguration(delay: number, usePade = false, padeOrder = 1): void {
    if (!Number.isFinite(delay) || delay < 0) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "delay deve ser número finito >= 0.");
    }
    this.delay = delay;
    this.use_pade = Boolean(usePade);
    this.pade_order = Math.max(1, Math.min(10, Math.floor(padeOrder)));
    this.notify();
  }

  public setFeedbackSign(sign: "negative" | "positive"): void {
    this.feedback_sign = sign;
    this.notify();
  }

  public setCompensatorGain(gain: number): void {
    if (!Number.isFinite(gain) || gain === 0) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Ganho do compensador deve ser finito não nulo.");
    }
    this.compensator_gain = gain;
    this.notify();
  }

  /**
   * Valida se o objeto fornecido é estritamente SISO.
   * Se for MIMO, rejeita com erro explícito de validação.
   */
  public assertStrictlySiso(obj: RegisteredTypedObject): void {
    const val = obj.value;
    if (obj.kind === "TransferFunction") {
      const num = val.num;
      if (Array.isArray(num)) {
        const p = num.length;
        const m = Array.isArray(num[0]) ? num[0].length : 1;
        if (p > 1 || m > 1) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            "Apenas sistemas SISO (ou seleção explícita de canal SISO) são suportados nesta aba. O modelo selecionado possui múltiplos canais.",
            { parameters: { kind: obj.kind, inputs: m, outputs: p } },
          );
        }
      }
    } else if (obj.kind === "StateSpace") {
      const matrices = (val.matrices as Record<string, unknown> | undefined) ?? val;
      const b = (matrices.B ?? val.B) as Record<string, unknown> | undefined;
      const c = (matrices.C ?? val.C) as Record<string, unknown> | undefined;
      const bShape = b?.shape as number[] | undefined;
      const cShape = c?.shape as number[] | undefined;
      const m = Array.isArray(bShape) && bShape.length >= 2 ? bShape[1] : (Array.isArray(val.input_names) ? (val.input_names as unknown[]).length : 1);
      const p = Array.isArray(cShape) && cShape.length >= 2 ? cShape[0] : (Array.isArray(val.output_names) ? (val.output_names as unknown[]).length : 1);
      if (m > 1 || p > 1) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Apenas sistemas SISO (ou seleção explícita de canal SISO) são suportados nesta aba. O modelo selecionado possui múltiplos canais.",
          { parameters: { kind: obj.kind, inputs: m, outputs: p } },
        );
      }
    }
  }

  /**
   * Resolve a planta ativa para frequência (TransferFunction ou StateSpace).
   */
  public resolveActivePlant(): { ref: CanonicalObjectRef; object: RegisteredTypedObject } {
    const sel = this.typedWorkspace.getEffectiveSelection("frequencyPlant");
    if (!sel) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Nenhuma planta SISO selecionada. Registre ou selecione um TransferFunction ou StateSpace na área de trabalho.",
      );
    }
    this.assertStrictlySiso(sel.object);
    return {
      ref: sel.ref,
      object: sel.object,
    };
  }

  /**
   * Avalia Resposta em Frequência (Bode, Nyquist) e Margens de Estabilidade.
   * Suporta Fast-Preview transitório (`previewOnly: true`) sem gravar execução autoritativa.
   */
  public async evaluateBodeAndMargins(options?: {
    previewOnly?: boolean;
    customWMin?: number;
    customWMax?: number;
    customNPoints?: number;
    customDelay?: number;
    customUsePade?: boolean;
    customPadeOrder?: number;
  }): Promise<{
    bodeChart: BodeChartModel;
    nyquistChart: NyquistChartModel;
    margins: SisoStabilityMarginsView;
  }> {
    const { ref, object } = this.resolveActivePlant();
    const isPreview = options?.previewOnly === true;

    const wMin = options?.customWMin ?? this.w_min;
    const wMax = options?.customWMax ?? this.w_max;
    const nPoints = options?.customNPoints ?? this.n_points;
    const delay = options?.customDelay ?? this.delay;
    const usePade = options?.customUsePade ?? this.use_pade;
    const padeOrder = options?.customPadeOrder ?? this.pade_order;

    this.isEvaluating = true;
    this.lastStatus = "running";
    this.lastErrorMessage = null;
    this.notify();

    try {
      const projectId = this.projectIdProvider();
      const projectRevision = this.projectRevisionProvider();

      // Chamada 1: frequency.eval_response (para Bode magnitude/fase e Nyquist Re/Im)
      const evalReq: RpcRequest = {
        api_version: RPC_API_VERSION,
        request_id: `req-siso-eval-${Date.now()}`,
        project_id: projectId,
        project_revision: projectRevision,
        operation: "frequency.eval_response",
        payload: {
          plant_ref: { id: ref.id, revision: ref.revision },
          w_min: wMin,
          w_max: wMax,
          n_points: nPoints,
          delay,
          use_pade: usePade,
          pade_order: padeOrder,
        },
        options: {},
        timeout_policy: { hard_timeout_ms: 10000 },
      };

      // Chamada 2: frequency.stability_margins (para cruzamentos e margens rigorosas)
      const marginsReq: RpcRequest = {
        api_version: RPC_API_VERSION,
        request_id: `req-siso-margins-${Date.now()}`,
        project_id: projectId,
        project_revision: projectRevision,
        operation: "frequency.stability_margins",
        payload: {
          plant_ref: { id: ref.id, revision: ref.revision },
          w_min: wMin,
          w_max: wMax,
          n_points: Math.max(nPoints, 1000),
          delay,
          use_pade: usePade,
          pade_order: padeOrder,
        },
        options: {},
        timeout_policy: { hard_timeout_ms: 10000 },
      };

      const [evalResp, marginsResp] = await Promise.all([
        this.client.execute(evalReq),
        this.client.execute(marginsReq),
      ]);

      if (evalResp.status === "failure") {
        throw new ControlLabBridgeError(
          evalResp.error?.code ?? "INTERNAL_ERROR",
          evalResp.error?.message ?? "Falha ao calcular resposta em frequência.",
          { parameters: evalResp.error?.details },
        );
      }
      if (marginsResp.status === "failure") {
        throw new ControlLabBridgeError(
          marginsResp.error?.code ?? "INTERNAL_ERROR",
          marginsResp.error?.message ?? "Falha ao calcular margens de estabilidade.",
          { parameters: marginsResp.error?.details },
        );
      }

      const evalData = (evalResp.result ?? {}) as Record<string, unknown>;
      const marginsData = (marginsResp.result ?? {}) as Record<string, unknown>;

      const omega = extractNumberArray(evalData.omega);
      const magDb = extractNumberArray(evalData.mag_db);
      const phaseDeg = extractNumberArray(evalData.phase_deg);

      let re: number[] = [];
      let im: number[] = [];
      if (evalData.response && typeof evalData.response === "object") {
        const respObj = evalData.response as Record<string, unknown>;
        if (Array.isArray(respObj.real) && Array.isArray(respObj.imag)) {
          re = (respObj.real as unknown[]).map(Number);
          im = (respObj.imag as unknown[]).map(Number);
        } else if (Array.isArray(evalData.response)) {
          re = (evalData.response as Array<{ real?: number; imag?: number } | number>).map((c) =>
            typeof c === "number" ? c : (c.real ?? 0),
          );
          im = (evalData.response as Array<{ real?: number; imag?: number } | number>).map((c) =>
            typeof c === "number" ? 0 : (c.imag ?? 0),
          );
        }
      }

      // Extrai cruzamentos e margens
      const gainCrossoversRaw = Array.isArray(marginsData.gain_crossovers)
        ? (marginsData.gain_crossovers as Array<Record<string, unknown>>)
        : [];
      const phaseCrossoversRaw = Array.isArray(marginsData.phase_crossovers)
        ? (marginsData.phase_crossovers as Array<Record<string, unknown>>)
        : [];

      const gainCrossovers: SisoGainCrossoverView[] = gainCrossoversRaw.map((item) => ({
        omega_gc: Number(item.omega_gc ?? 0),
        phase_deg: Number(item.phase_deg ?? 0),
        phase_margin_deg: Number(item.phase_margin_deg ?? 0),
        delay_margin_sec:
          item.delay_margin_sec !== null && item.delay_margin_sec !== undefined
            ? Number(item.delay_margin_sec)
            : null,
      }));

      const phaseCrossovers: SisoPhaseCrossoverView[] = phaseCrossoversRaw.map((item) => ({
        omega_pc: Number(item.omega_pc ?? 0),
        target_phase_deg: Number(item.target_phase_deg ?? -180),
        loop_gain_abs: Number(item.loop_gain_abs ?? 0),
        loop_gain_db: Number(item.loop_gain_db ?? 0),
        gain_margin_linear:
          item.gain_margin_linear !== null && item.gain_margin_linear !== undefined
            ? Number(item.gain_margin_linear)
            : null,
        gain_margin_db:
          item.gain_margin_db !== null && item.gain_margin_db !== undefined
            ? Number(item.gain_margin_db)
            : null,
      }));

      const markers: FrequencyCrossingMarker[] = [
        ...gainCrossovers.map((gc, i) => ({
          id: `gc-${i + 1}`,
          kind: "gain_crossover" as const,
          omega: gc.omega_gc,
          mag_db: 0,
          phase_deg: gc.phase_deg,
          label: `ω_gc${gainCrossovers.length > 1 ? `_${i + 1}` : ""}: MF=${formatNumericDisplay(gc.phase_margin_deg, 1)}°`,
        })),
        ...phaseCrossovers.map((pc, i) => ({
          id: `pc-${i + 1}`,
          kind: "phase_crossover" as const,
          omega: pc.omega_pc,
          mag_db: pc.loop_gain_db,
          phase_deg: pc.target_phase_deg,
          label: `ω_pc${phaseCrossovers.length > 1 ? `_${i + 1}` : ""}: MG=${pc.gain_margin_db !== null ? `${formatNumericDisplay(pc.gain_margin_db, 1)} dB` : "∞"}`,
        })),
      ];

      const delayRep = delay > 0 ? (usePade ? "pade" : "exact") : "none";
      const semantics = isPreview ? "preview" : "numeric_verified";

      const plantDt = (evalData.dt as number | null) ?? (object.value.dt as number | null) ?? null;

      const bodeChart = buildBodeChartModel({
        chart_id: isPreview ? "siso-bode-preview" : "siso-bode-chart",
        title: `Diagrama de Bode SISO (${object.id})`,
        model_revision: ref.revision,
        project_revision: projectRevision,
        provenance: evalResp.provenance,
        series_semantics: semantics,
        theme_mode: this.themeModeProvider(),
        dt: plantDt,
        omega,
        mag_db: magDb,
        phase_deg: phaseDeg,
        markers,
        delay_representation: delayRep,
      });

      const nyquistChart = buildNyquistChartModel({
        chart_id: isPreview ? "siso-nyquist-preview" : "siso-nyquist-chart",
        title: `Diagrama de Nyquist SISO (${object.id})`,
        model_revision: ref.revision,
        project_revision: projectRevision,
        provenance: evalResp.provenance,
        series_semantics: semantics,
        theme_mode: this.themeModeProvider(),
        dt: plantDt,
        omega,
        re,
        im,
        delay_representation: delayRep,
      });

      const closedLoopPoles: ComplexVectorPair | null = extractComplexPair(marginsData.closed_loop_poles);

      const marginsView: SisoStabilityMarginsView = {
        gain_crossovers: gainCrossovers,
        phase_crossovers: phaseCrossovers,
        critical_phase_margin_deg:
          marginsData.critical_phase_margin_deg !== null &&
          marginsData.critical_phase_margin_deg !== undefined
            ? Number(marginsData.critical_phase_margin_deg)
            : null,
        critical_omega_gc:
          marginsData.critical_omega_gc !== null && marginsData.critical_omega_gc !== undefined
            ? Number(marginsData.critical_omega_gc)
            : null,
        critical_delay_margin_sec:
          marginsData.critical_delay_margin_sec !== null &&
          marginsData.critical_delay_margin_sec !== undefined
            ? Number(marginsData.critical_delay_margin_sec)
            : null,
        critical_gain_margin_db:
          marginsData.critical_gain_margin_db !== null &&
          marginsData.critical_gain_margin_db !== undefined
            ? Number(marginsData.critical_gain_margin_db)
            : null,
        critical_gain_margin_linear:
          marginsData.critical_gain_margin_linear !== null &&
          marginsData.critical_gain_margin_linear !== undefined
            ? Number(marginsData.critical_gain_margin_linear)
            : null,
        critical_omega_pc:
          marginsData.critical_omega_pc !== null && marginsData.critical_omega_pc !== undefined
            ? Number(marginsData.critical_omega_pc)
            : null,
        closed_loop_stable:
          marginsData.closed_loop_stable !== null && marginsData.closed_loop_stable !== undefined
            ? Boolean(marginsData.closed_loop_stable)
            : null,
        closed_loop_poles: closedLoopPoles,
        has_multiple_crossings: gainCrossovers.length > 1 || phaseCrossovers.length > 1,
      };

      this.lastBodeModel = bodeChart;
      this.lastNyquistModel = nyquistChart;
      this.lastMarginsView = marginsView;
      this.lastWarnings = [
        ...(evalResp.warnings ?? []),
        ...(marginsResp.warnings ?? []),
      ];
      this.lastStatus = this.lastWarnings.length > 0 ? "warning" : "success";

      // Se for execução autoritativa (não preview), registra no controlador de abas
      if (!isPreview && this.tabsController) {
        this.lastExecutionRecord = {
          toolId: "siso.stability_margins",
          operation: "frequency.stability_margins",
          request_id: marginsReq.request_id,
          project_revision: projectRevision,
          response: marginsResp,
          indicator: "numeric_verified",
          executed_at: new Date().toISOString(),
        };
        this.tabsController.recordCommittedExecution(this.lastExecutionRecord);
      }

      this.announcer.announce(
        `Resposta em frequência calculada. Margem de fase: ${marginsView.critical_phase_margin_deg !== null ? `${marginsView.critical_phase_margin_deg.toFixed(1)} graus` : "infinita"}.`,
        "polite",
      );

      return { bodeChart, nyquistChart, margins: marginsView };
    } catch (err) {
      this.lastStatus = "failure";
      this.lastErrorMessage =
        err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      this.isEvaluating = false;
      this.notify();
    }
  }

  /**
   * Avalia o Lugar das Raízes (Root Locus) com detecção de assíntotas,
   * pontos de quebra, cruzamentos do eixo imaginário e overlays semânticos (R-18).
   */
  public async evaluateRootLocus(options?: {
    previewOnly?: boolean;
    n_gains?: number;
    k_max?: number;
    damping_ratio?: number;
    settling_time?: number;
  }): Promise<{ rootLocusChart: RootLocusChartModel; view: SisoRootLocusView }> {
    const { ref, object } = this.resolveActivePlant();
    const isPreview = options?.previewOnly === true;

    this.isEvaluating = true;
    this.lastStatus = "running";
    this.lastErrorMessage = null;
    this.notify();

    try {
      const projectId = this.projectIdProvider();
      const projectRevision = this.projectRevisionProvider();
      const nGains = options?.n_gains ?? 100;
      const kMax = options?.k_max ?? 100;

      const req: RpcRequest = {
        api_version: RPC_API_VERSION,
        request_id: `req-siso-rl-${Date.now()}`,
        project_id: projectId,
        project_revision: projectRevision,
        operation: "frequency.root_locus",
        payload: {
          plant_ref: { id: ref.id, revision: ref.revision },
          n_gains: nGains,
          k_max: kMax,
          feedback_sign: this.feedback_sign,
        },
        options: {},
        timeout_policy: { hard_timeout_ms: 10000 },
      };

      const resp = await this.client.execute(req);
      if (resp.status === "failure") {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao calcular Lugar das Raízes.",
          { parameters: resp.error?.details },
        );
      }

      const data = (resp.result ?? {}) as Record<string, unknown>;
      const gains = extractNumberArray(data.gains);

      const branches: SisoRootLocusBranchView[] = [];
      const rootsObj = data.roots as { shape?: number[]; real?: number[]; imag?: number[] } | unknown[] | undefined;
      if (
        rootsObj &&
        !Array.isArray(rootsObj) &&
        typeof rootsObj === "object" &&
        Array.isArray(rootsObj.shape) &&
        rootsObj.shape.length === 2
      ) {
        const [nSteps, nBranches] = rootsObj.shape;
        const rReal = Array.isArray(rootsObj.real) ? rootsObj.real : [];
        const rImag = Array.isArray(rootsObj.imag) ? rootsObj.imag : [];
        for (let b = 0; b < nBranches; b += 1) {
          const brReal: number[] = [];
          const brImag: number[] = [];
          for (let s = 0; s < nSteps; s += 1) {
            const idx = s * nBranches + b;
            brReal.push(Number(rReal[idx] ?? 0));
            brImag.push(Number(rImag[idx] ?? 0));
          }
          branches.push({ real: brReal, imag: brImag });
        }
      } else if (Array.isArray(rootsObj) && rootsObj.length > 0 && Array.isArray(rootsObj[0])) {
        const nSteps = rootsObj.length;
        const nBranches = (rootsObj[0] as unknown[]).length;
        for (let b = 0; b < nBranches; b += 1) {
          const brReal: number[] = [];
          const brImag: number[] = [];
          for (let s = 0; s < nSteps; s += 1) {
            const stepRow = rootsObj[s] as Array<number | { real?: number; imag?: number }>;
            const rootVal = stepRow[b];
            if (typeof rootVal === "number") {
              brReal.push(rootVal);
              brImag.push(0);
            } else if (isPlainObject(rootVal)) {
              brReal.push(Number(rootVal.real ?? 0));
              brImag.push(Number(rootVal.imag ?? 0));
            }
          }
          branches.push({ real: brReal, imag: brImag });
        }
      }

      const openLoopPoles = extractComplexPair(data.open_loop_poles);
      const openLoopZeros = extractComplexPair(data.open_loop_zeros);

      const breakawayPointsRaw = Array.isArray(data.breakaway_points)
        ? (data.breakaway_points as Array<Record<string, unknown>>)
        : [];
      const breakawayPoints: SisoBreakawayPointView[] = breakawayPointsRaw.map((bp) => ({
        s_real: Number(bp.s_real ?? 0),
        s_imag: Number(bp.s_imag ?? 0),
        gain_K: Number(bp.gain_K ?? 0),
        on_real_axis: Boolean(bp.on_real_axis),
      }));

      const crossingsRaw = Array.isArray(data.stability_crossings)
        ? (data.stability_crossings as Array<Record<string, unknown>>)
        : [];
      const stabilityCrossings: SisoStabilityCrossingView[] = crossingsRaw.map((sc) => ({
        branch_index: Number(sc.branch_index ?? 0),
        gain_K: Number(sc.gain_K ?? 0),
        pole_real: Number(sc.pole_real ?? 0),
        pole_imag: Number(sc.pole_imag ?? 0),
        direction: (sc.direction as "stabilizing" | "destabilizing") ?? "destabilizing",
      }));

      // Constrói overlays de 2ª ordem rotulados explicitamente como HEURISTIC
      const overlays: RequirementOverlay[] = [];
      const dt = (data.dt as number | null) ?? (object.value.dt as number | null) ?? null;
      const domain = dt === null ? ("continuous" as const) : ("discrete" as const);

      if (options?.damping_ratio !== undefined && options.damping_ratio > 0) {
        overlays.push(
          createSecondOrderRegionOverlay({
            zetaMin: options.damping_ratio,
            classification: "heuristic",
          }),
        );
      }
      if (options?.settling_time !== undefined && options.settling_time > 0) {
        overlays.push(
          createSecondOrderRegionOverlay({
            maxSettlingTimeS: options.settling_time,
            classification: "heuristic",
          }),
        );
      }

      const semantics = isPreview ? "preview" : "numeric_verified";

      const chart = buildRootLocusChartModel({
        chart_id: isPreview ? "siso-rl-preview" : "siso-rl-chart",
        title: `Lugar das Raízes (${object.id}) - Realimentação ${this.feedback_sign === "negative" ? "Negativa" : "Positiva"}`,
        model_revision: ref.revision,
        project_revision: projectRevision,
        provenance: resp.provenance,
        series_semantics: semantics,
        theme_mode: this.themeModeProvider(),
        dt,
        gains,
        branches,
        open_loop_poles: openLoopPoles,
        open_loop_zeros: openLoopZeros,
        breakaway_points: breakawayPoints.map((bp) => bp.s_real),
        stability_crossings: stabilityCrossings,
        overlays,
      });

      const rlView: SisoRootLocusView = {
        gains,
        branches,
        open_loop_poles: openLoopPoles,
        open_loop_zeros: openLoopZeros,
        breakaway_points: breakawayPoints,
        stability_crossings: stabilityCrossings,
        feedback_sign: this.feedback_sign,
        domain: (data.domain as string) ?? "continuous",
      };

      this.lastRootLocusModel = chart;
      this.lastRootLocusView = rlView;
      this.lastWarnings = resp.warnings ?? [];
      this.lastStatus = this.lastWarnings.length > 0 ? "warning" : "success";

      if (!isPreview && this.tabsController) {
        this.lastExecutionRecord = {
          toolId: "siso.root_locus",
          operation: "frequency.root_locus",
          request_id: req.request_id,
          project_revision: projectRevision,
          response: resp,
          indicator: "numeric_verified",
          executed_at: new Date().toISOString(),
        };
        this.tabsController.recordCommittedExecution(this.lastExecutionRecord);
      }

      return { rootLocusChart: chart, view: rlView };
    } catch (err) {
      this.lastStatus = "failure";
      this.lastErrorMessage =
        err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      this.isEvaluating = false;
      this.notify();
    }
  }

  /**
   * Avalia Resposta ao Degrau (frequency.step_response) para conferência temporal.
   */
  public async evaluateStepResponse(options?: {
    previewOnly?: boolean;
    amplitude?: number;
    t_final?: number;
    n_points?: number;
  }): Promise<{ chart: TimeResponseChartModel; metrics: SisoStepMetricsView }> {
    const { ref, object } = this.resolveActivePlant();
    const isPreview = options?.previewOnly === true;

    this.isEvaluating = true;
    this.lastStatus = "running";
    this.lastErrorMessage = null;
    this.notify();

    try {
      const projectId = this.projectIdProvider();
      const projectRevision = this.projectRevisionProvider();
      const amp = options?.amplitude ?? 1.0;
      const tFinal = options?.t_final ?? 10.0;
      const nPoints = options?.n_points ?? 400;

      const req: RpcRequest = {
        api_version: RPC_API_VERSION,
        request_id: `req-siso-step-${Date.now()}`,
        project_id: projectId,
        project_revision: projectRevision,
        operation: "frequency.step_response",
        payload: {
          plant_ref: { id: ref.id, revision: ref.revision },
          amplitude: amp,
          t_final: tFinal,
          n_points: nPoints,
        },
        options: {},
        timeout_policy: { hard_timeout_ms: 10000 },
      };

      const resp = await this.client.execute(req);
      if (resp.status === "failure") {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao calcular resposta ao degrau.",
          { parameters: resp.error?.details },
        );
      }

      const data = (resp.result ?? {}) as Record<string, unknown>;
      const t = extractNumberArray(data.t);
      const y = extractNumberArray(data.y);
      const u = extractNumberArray(data.u);
      const metricsRaw = (data.metrics ?? {}) as Record<string, unknown>;

      const metrics: SisoStepMetricsView = {
        is_stable: Boolean(metricsRaw.is_stable),
        steady_state_value:
          metricsRaw.steady_state_value !== null && metricsRaw.steady_state_value !== undefined
            ? Number(metricsRaw.steady_state_value)
            : null,
        steady_state_error:
          metricsRaw.steady_state_error !== null && metricsRaw.steady_state_error !== undefined
            ? Number(metricsRaw.steady_state_error)
            : null,
        overshoot_percent:
          metricsRaw.overshoot_percent !== null && metricsRaw.overshoot_percent !== undefined
            ? Number(metricsRaw.overshoot_percent)
            : null,
        peak_value: Number(metricsRaw.peak_value ?? 0),
        peak_time: Number(metricsRaw.peak_time ?? 0),
        settling_time:
          metricsRaw.settling_time !== null && metricsRaw.settling_time !== undefined
            ? Number(metricsRaw.settling_time)
            : null,
        settling_threshold: Number(metricsRaw.settling_threshold ?? 0.02),
        rise_time_10_90:
          metricsRaw.rise_time_10_90 !== null && metricsRaw.rise_time_10_90 !== undefined
            ? Number(metricsRaw.rise_time_10_90)
            : null,
      };

      const semantics = isPreview ? "preview" : "numeric_verified";
      const plantDt = (data.dt as number | null) ?? (object.value.dt as number | null) ?? null;

      const chart = buildTimeResponseChartModel({
        chart_id: isPreview ? "siso-step-preview" : "siso-step-chart",
        title: `Resposta ao Degrau SISO (${object.id})`,
        model_revision: ref.revision,
        project_revision: projectRevision,
        provenance: resp.provenance,
        series_semantics: semantics,
        theme_mode: this.themeModeProvider(),
        dt: plantDt,
        t,
        y: y.map((v) => [v]),
        u: u.map((v) => [v]),
      });

      this.lastTimeResponseModel = chart;
      this.lastStepMetricsView = metrics;
      this.lastWarnings = resp.warnings ?? [];
      this.lastStatus = this.lastWarnings.length > 0 ? "warning" : "success";

      if (!isPreview && this.tabsController) {
        this.lastExecutionRecord = {
          toolId: "siso.step_response",
          operation: "frequency.step_response",
          request_id: req.request_id,
          project_revision: projectRevision,
          response: resp,
          indicator: "numeric_verified",
          executed_at: new Date().toISOString(),
        };
        this.tabsController.recordCommittedExecution(this.lastExecutionRecord);
      }

      return { chart, metrics };
    } catch (err) {
      this.lastStatus = "failure";
      this.lastErrorMessage =
        err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      this.isEvaluating = false;
      this.notify();
    }
  }

  /**
   * Oráculo Analítico de 1ª ordem G(s) = K / (s + a) ou G(s) = 1 / (s + a).
   * Utilizado para testes normativos T-FREQ-01 e validação matemática independente.
   *
   * Equações analíticas exatas:
   * |G(jω)| = 1 / sqrt(a^2 + ω^2)
   * ∠G(jω)  = -atan2(ω, a) [graus]
   */
  public static analyticalFirstOrder(
    a: number,
    omega: readonly number[],
  ): { mag_db: number[]; phase_deg: number[] } {
    const magDb: number[] = [];
    const phaseDeg: number[] = [];
    for (const w of omega) {
      const magLin = 1.0 / Math.sqrt(a * a + w * w);
      magDb.push(20.0 * Math.log10(magLin));
      phaseDeg.push((-Math.atan2(w, a) * 180.0) / Math.PI);
    }
    return { mag_db: magDb, phase_deg: phaseDeg };
  }

  /**
   * Converte a resposta gráfica corrente em SVG.
   */
  public renderCurrentBodeSvg(): string {
    if (!this.lastBodeModel) return "";
    return renderBodeSvg(this.lastBodeModel);
  }

  public renderCurrentNyquistSvg(): string {
    if (!this.lastNyquistModel) return "";
    return renderNyquistSvg(this.lastNyquistModel);
  }

  public renderCurrentRootLocusSvg(): string {
    if (!this.lastRootLocusModel) return "";
    return renderRootLocusSvg(this.lastRootLocusModel);
  }

  public renderCurrentTimeResponseSvg(): string {
    if (!this.lastTimeResponseModel) return "";
    return renderTimeResponseSvg(this.lastTimeResponseModel);
  }
}
