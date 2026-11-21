/**
 * Bancada da Aba 4 — Análise MIMO na Frequência
 * seguindo CL-UX-DIR-001 v1.0.0 Seção 4.4 (`WP-UX-REFACTOR-03-MIMO-FUZZY-LMI`).
 *
 * Responsabilidades estritas de UI/Apresentação (F8):
 * - Seleção de faixa de frequência (w_min, w_max, n_points), malha L_o = G·K vs L_i = K·G
 *   e carregamento rápido de planta MIMO 2×2 acoplada em 1 clique.
 * - Execução autoritativa no motor Python via `client.execute(...)` para:
 *   `mimo.singular_values`, `mimo.rga` e `mimo.sensitivity`.
 * - Gráfico de valores singulares σ(G, S, T, KS) com toggles de curva, barra [SVG]/[PNG]
 *   e tabela acessível WCAG 2.2 AA.
 * - Heatmap interativo RGA Λ(G(jω)) com slider de frequência ω, número de condição κ(G)
 *   e diagnóstico explícito para matriz singular ("RGA indefinida").
 *
 * 100% compatível com erasableSyntaxOnly, verbatimModuleSyntax e FakeElement/FakeDocument.
 */

import type { ControlLabEngineClient } from "../../bridge/client.ts";
import {
  ControlLabBridgeError,
  generateUuid,
  isPlainObject,
  RPC_API_VERSION,
  type Provenance,
  type RealTensor,
  type RpcResponse,
} from "../../bridge/protocol.ts";
import { escapeHtml, formatNumericDisplay } from "../../app/accessibility.ts";
import type { ControlLabShell } from "../../app/shell.ts";
import {
  buildAccessibleChartTable,
  buildSingularValuesChartModel,
  renderAccessibleTableHtml,
  renderSingularValuesSvg,
  type SingularValueCurve,
  type SingularValuesChartModel,
} from "../../charts/scientific_chart.ts";

export interface MimoViewOptions {
  shell: ControlLabShell;
  client: ControlLabEngineClient;
  container: HTMLElement;
  onRequestRender?: () => void;
}

interface ParsedRgaEntry {
  omega: number;
  status: "defined" | "undefined";
  reason?: string;
  sigmaMin: number | null;
  sigmaMax: number | null;
  conditionNumber: number | null;
  realMatrix: number[][] | null;
  imagMatrix: number[][] | null;
  magMatrix: number[][] | null;
}

interface MimoAnalysisSnapshot {
  plantId: string;
  plantRevision: number;
  loopMode: "output" | "input";
  feedbackSign: "negative" | "positive";
  omega: number[];
  svModel: SingularValuesChartModel;
  rgaStatus: string;
  rgaEntries: ParsedRgaEntry[];
  pairingAnalysis: Array<{
    output: number;
    recommended_input: number;
    rga_element_real: number;
  }>;
  identityVerified: boolean | null;
  maxIdentityResidual: number | null;
  msPeak: number | null;
  mtPeak: number | null;
  hinfPeak: number | null;
  omegaPeak: number | null;
  sensitivityNote: string | null;
  rgaNote: string | null;
}

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function makeFloat64Tensor(shape: number[], data: number[]): RealTensor {
  return { shape, dtype: "float64", order: "C", data };
}

function renderMimoExportBarHtml(slotId: string, label: string): string {
  return [
    `<div class="chart-export-bar" data-export-bar-for="${escapeHtml(slotId)}" hidden>`,
    `<span class="chart-export-label">${escapeHtml(label)}</span>`,
    `<div class="chart-export-actions">`,
    `<button type="button" class="touch-control btn-secondary btn-small" data-action="export-chart-svg" data-chart-slot="${escapeHtml(slotId)}" disabled aria-disabled="true">Exportar SVG</button>`,
    `<button type="button" class="touch-control btn-secondary btn-small" data-action="export-chart-png" data-chart-slot="${escapeHtml(slotId)}" disabled aria-disabled="true">Exportar PNG</button>`,
    `</div>`,
    `</div>`,
  ].join("");
}

function extractNumericVector(raw: unknown): number[] {
  if (Array.isArray(raw)) {
    return raw.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  }
  if (isPlainObject(raw) && Array.isArray(raw.data)) {
    return (raw.data as unknown[]).filter(
      (v): v is number => typeof v === "number" && Number.isFinite(v),
    );
  }
  return [];
}

function toDbArray(vals: readonly number[]): number[] {
  return vals.map((v) => 20 * Math.log10(Math.max(1e-15, v)));
}

function extract2DComplexMatrix(
  raw: unknown,
  p: number,
  m: number,
): { real: number[][]; imag: number[][]; mag: number[][] } | null {
  if (!isPlainObject(raw)) return null;
  const realFlat = Array.isArray(raw.real) ? (raw.real as number[]) : null;
  const imagFlat = Array.isArray(raw.imag) ? (raw.imag as number[]) : null;
  if (!realFlat || realFlat.length < p * m) return null;
  const real: number[][] = [];
  const imag: number[][] = [];
  const mag: number[][] = [];
  for (let i = 0; i < p; i += 1) {
    const rRow: number[] = [];
    const iRow: number[] = [];
    const mRow: number[] = [];
    for (let j = 0; j < m; j += 1) {
      const idx = i * m + j;
      const rVal = Number(realFlat[idx] ?? 0);
      const iVal = Number(imagFlat?.[idx] ?? 0);
      rRow.push(rVal);
      iRow.push(iVal);
      mRow.push(Math.hypot(rVal, iVal));
    }
    real.push(rRow);
    imag.push(iRow);
    mag.push(mRow);
  }
  return { real, imag, mag };
}

export function buildCoupledMimo2x2ExampleDto(): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    id: "ss-mimo-distillation-2x2",
    revision: 1,
    kind: "StateSpace",
    dt: null,
    state_names: ["x1", "x2"],
    input_names: ["u1", "u2"],
    output_names: ["y1", "y2"],
    matrices: {
      A: makeFloat64Tensor([2, 2], [-1.0, 0.4, 0.2, -2.0]),
      B: makeFloat64Tensor([2, 2], [1.0, 0.3, 0.2, 1.5]),
      C: makeFloat64Tensor([2, 2], [1.0, 0.0, 0.0, 1.0]),
      D: makeFloat64Tensor([2, 2], [0.0, 0.0, 0.0, 0.0]),
    },
    units: {
      time: "s",
      states: ["1", "1"],
      inputs: ["1", "1"],
      outputs: ["1", "1"],
    },
    provenance: {
      source: "mimo_example_2x2",
      description: "Planta MIMO 2x2 acoplada de referência",
    },
  };
}

export function renderMimoViewHtml(): string {
  return [
    `<section id="mimo-workspace-panel" class="panel-card workspace-section" aria-label="Análise MIMO na Frequência" hidden>`,
    `<h3>Análise MIMO na Frequência (σ, S, T e RGA)</h3>`,
    `<div class="mimo-toolbar subcard">`,
    `<div class="mimo-toolbar-top panel-actions">`,
    `<div id="mimo-active-plant-info" class="mimo-plant-pill">Nenhuma planta selecionada.</div>`,
    `<button type="button" id="btn-mimo-load-example" class="touch-control btn-secondary" data-action="mimo-load-example">Carregar Planta MIMO 2×2 (Exemplo)</button>`,
    `</div>`,
    `<div class="mimo-params-row panel-actions">`,
    `<label for="mimo-w-min">ω_min (rad/s)</label>`,
    `<input type="number" id="mimo-w-min" class="touch-control id-param-input" min="0.0001" max="1000" step="0.01" value="0.01" aria-label="Frequência mínima MIMO" />`,
    `<label for="mimo-w-max">ω_max (rad/s)</label>`,
    `<input type="number" id="mimo-w-max" class="touch-control id-param-input" min="0.1" max="100000" step="10" value="100" aria-label="Frequência máxima MIMO" />`,
    `<label for="mimo-n-points">Pontos</label>`,
    `<input type="number" id="mimo-n-points" class="touch-control id-param-input" min="8" max="500" step="5" value="40" aria-label="Número de pontos MIMO" />`,
    `<label for="mimo-loop-select">Malha de Abertura</label>`,
    `<select id="mimo-loop-select" class="touch-control" aria-label="Seleção de malha MIMO">`,
    `<option value="output">Saída: L_o = G · K</option>`,
    `<option value="input">Entrada: L_i = K · G</option>`,
    `</select>`,
    `<label for="mimo-feedback-sign">Sinal</label>`,
    `<select id="mimo-feedback-sign" class="touch-control" aria-label="Sinal de realimentação MIMO">`,
    `<option value="negative">Negativa (I + L)</option>`,
    `<option value="positive">Positiva (I - L)</option>`,
    `</select>`,
    `<button type="button" id="btn-mimo-analyze" class="touch-control btn-primary" data-action="mimo-analyze">Calcular Análise MIMO</button>`,
    `</div>`,
    `</div>`,
    `<div id="mimo-diagnostics-summary" class="diagnostics-panel" aria-live="polite"><p>Selecione ou carregue uma planta MIMO 2×2 e clique em <strong>Calcular Análise MIMO</strong>.</p></div>`,
    `<div class="mimo-workbench-grid">`,
    `<div class="chart-card">`,
    `<div class="mimo-curve-toggles panel-actions" role="group" aria-label="Curvas de valores singulares visíveis">`,
    `<strong>Valores Singulares σ̄ / σ̲:</strong>`,
    `<label class="mimo-toggle-label"><input type="checkbox" id="mimo-toggle-G" data-mimo-curve="G" checked /> G(jω)</label>`,
    `<label class="mimo-toggle-label"><input type="checkbox" id="mimo-toggle-S" data-mimo-curve="S" checked /> Sensibilidade S</label>`,
    `<label class="mimo-toggle-label"><input type="checkbox" id="mimo-toggle-T" data-mimo-curve="T" checked /> T</label>`,
    `<label class="mimo-toggle-label"><input type="checkbox" id="mimo-toggle-KS" data-mimo-curve="KS" /> KS</label>`,
    `</div>`,
    `<div id="mimo-sigma-chart-slot" class="chart-container"></div>`,
    renderMimoExportBarHtml("mimo-sigma-chart-slot", "Valores Singulares σ(G, S, T, KS)"),
    `<details><summary>Tabela acessível de valores singulares MIMO (WCAG 2.2 AA)</summary><div id="mimo-sigma-table-slot"><p>Sem análise MIMO calculada.</p></div></details>`,
    `</div>`,
    `<div class="subcard mimo-rga-card">`,
    `<h4>Matriz de Ganho Relativo (RGA Λ(G(jω)))</h4>`,
    `<div class="tool-field">`,
    `<label for="mimo-rga-omega-slider">Frequência de inspeção ω: <strong id="mimo-rga-omega-label">—</strong></label>`,
    `<input type="range" id="mimo-rga-omega-slider" class="touch-control" min="0" max="0" step="1" value="0" aria-label="Frequência de inspeção RGA" disabled />`,
    `</div>`,
    `<div id="mimo-rga-heatmap-slot" class="mimo-rga-heatmap-slot" aria-live="polite"><p>Aguardando cálculo da RGA para exibir pareamento e condicionamento κ(G).</p></div>`,
    `</div>`,
    `</div>`,
    `</section>`,
  ].join("\n");
}

export class MimoView {
  private readonly shell: ControlLabShell;
  private readonly client: ControlLabEngineClient;
  private readonly container: HTMLElement;
  private readonly onRequestRender?: () => void;

  private readonly panelEl: HTMLElement | null;
  private readonly activePlantInfoEl: HTMLElement | null;
  private readonly wMinEl: HTMLInputElement | null;
  private readonly wMaxEl: HTMLInputElement | null;
  private readonly nPointsEl: HTMLInputElement | null;
  private readonly loopSelectEl: HTMLSelectElement | null;
  private readonly feedbackSignEl: HTMLSelectElement | null;
  private readonly diagSummaryEl: HTMLElement | null;
  private readonly sigmaChartSlotEl: HTMLElement | null;
  private readonly sigmaTableSlotEl: HTMLElement | null;
  private readonly rgaSliderEl: HTMLInputElement | null;
  private readonly rgaOmegaLabelEl: HTMLElement | null;
  private readonly rgaHeatmapSlotEl: HTMLElement | null;

  private readonly visibleGroups = new Set<string>(["G", "S", "T"]);
  private snapshot: MimoAnalysisSnapshot | null = null;
  private selectedRgaIndex = 0;

  constructor(options: MimoViewOptions) {
    this.shell = options.shell;
    this.client = options.client;
    this.container = options.container;
    this.onRequestRender = options.onRequestRender;

    this.panelEl = this.container.querySelector<HTMLElement>("#mimo-workspace-panel");
    this.activePlantInfoEl = this.container.querySelector<HTMLElement>("#mimo-active-plant-info");
    this.wMinEl = this.container.querySelector<HTMLInputElement>("#mimo-w-min");
    this.wMaxEl = this.container.querySelector<HTMLInputElement>("#mimo-w-max");
    this.nPointsEl = this.container.querySelector<HTMLInputElement>("#mimo-n-points");
    this.loopSelectEl = this.container.querySelector<HTMLSelectElement>("#mimo-loop-select");
    this.feedbackSignEl = this.container.querySelector<HTMLSelectElement>("#mimo-feedback-sign");
    this.diagSummaryEl = this.container.querySelector<HTMLElement>("#mimo-diagnostics-summary");
    this.sigmaChartSlotEl = this.container.querySelector<HTMLElement>("#mimo-sigma-chart-slot");
    this.sigmaTableSlotEl = this.container.querySelector<HTMLElement>("#mimo-sigma-table-slot");
    this.rgaSliderEl = this.container.querySelector<HTMLInputElement>("#mimo-rga-omega-slider");
    this.rgaOmegaLabelEl = this.container.querySelector<HTMLElement>("#mimo-rga-omega-label");
    this.rgaHeatmapSlotEl = this.container.querySelector<HTMLElement>("#mimo-rga-heatmap-slot");

    this.bindEvents();
  }

  private bindEvents(): void {
    this.container
      .querySelector<HTMLElement>('[data-action="mimo-load-example"]')
      ?.addEventListener("click", () => {
        void this.loadExample2x2();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="mimo-analyze"]')
      ?.addEventListener("click", () => {
        void this.runAnalysis();
      });

    for (const cb of Array.from(
      this.container.querySelectorAll<HTMLInputElement>("[data-mimo-curve]"),
    )) {
      cb.addEventListener("change", () => {
        const grp = cb.getAttribute("data-mimo-curve");
        if (!grp) return;
        if (cb.checked) this.visibleGroups.add(grp);
        else this.visibleGroups.delete(grp);
        this.renderSigmaChart();
      });
    }

    const onSliderChange = (): void => {
      if (!this.rgaSliderEl || !this.snapshot) return;
      const idx = Math.max(
        0,
        Math.min(this.snapshot.rgaEntries.length - 1, Math.round(Number(this.rgaSliderEl.value) || 0)),
      );
      this.selectedRgaIndex = idx;
      this.renderRgaHeatmap();
    };
    this.rgaSliderEl?.addEventListener("input", onSliderChange);
    this.rgaSliderEl?.addEventListener("change", onSliderChange);
  }

  public async loadExample2x2(): Promise<void> {
    try {
      const dto = buildCoupledMimo2x2ExampleDto();
      await this.shell.getTypedWorkspace().registerTypedObject(dto, {
        selectRole: "frequencyPlant",
        source: "manual",
      });
      this.shell
        .getAnnouncer()
        .announce("Planta MIMO 2x2 acoplada carregada e selecionada para análise.", "polite", "status");
      this.render();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  private async executeRpc(
    operation: string,
    payload: Record<string, unknown>,
  ): Promise<RpcResponse> {
    const lqr = this.shell.getLqrWorkspace();
    const projectId = lqr.getProjectId();
    const rev = Math.max(lqr.getProjectRevision(), this.client.getCommittedRevision(projectId));
    return this.client.execute(
      {
        api_version: RPC_API_VERSION,
        request_id: `mimo-${generateUuid()}`,
        project_id: projectId,
        project_revision: rev,
        operation,
        payload,
        options: {},
        timeout_policy: { hard_timeout_ms: 20000 },
      },
      { commitOnSuccess: false },
    );
  }

  public async runAnalysis(): Promise<void> {
    try {
      const typed = this.shell.getTypedWorkspace();
      const eff = typed.getEffectiveSelection("frequencyPlant");
      if (!eff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Selecione uma planta StateSpace ou TransferFunction, ou clique em 'Carregar Planta MIMO 2×2 (Exemplo)'.",
        );
      }

      const wMin = Number(this.wMinEl?.value ?? 0.01);
      const wMax = Number(this.wMaxEl?.value ?? 100);
      const nPoints = Math.round(Number(this.nPointsEl?.value ?? 40));
      if (!Number.isFinite(wMin) || wMin <= 0 || !Number.isFinite(wMax) || wMax <= wMin) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Faixa de frequência inválida: exija 0 < ω_min < ω_max.",
        );
      }
      if (!Number.isInteger(nPoints) || nPoints < 2 || nPoints > 2000) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Número de pontos deve ser inteiro entre 2 e 2000.",
        );
      }

      const loopMode: "output" | "input" =
        this.loopSelectEl?.value === "input" ? "input" : "output";
      const feedbackSign: "negative" | "positive" =
        this.feedbackSignEl?.value === "positive" ? "positive" : "negative";

      const svParams = { w_min: wMin, w_max: wMax, n_points: nPoints };
      const svPlan = await typed.prepareToolExecution("mimo.singular_values", svParams, {
        extraPayload: svParams,
      });
      const svResp = await this.executeRpc("mimo.singular_values", svPlan.extraPayload);
      if (svResp.status === "failure" || !svResp.result) {
        throw new ControlLabBridgeError(
          svResp.error?.code ?? "INTERNAL_ERROR",
          svResp.error?.message ?? "Falha ao calcular valores singulares MIMO.",
        );
      }

      const svRes = svResp.result as Record<string, unknown>;
      const omegaVec = extractNumericVector(svRes.omega);
      const sigmaMaxDb = extractNumericVector(svRes.sigma_max_db);
      const sigmaMinDb = extractNumericVector(svRes.sigma_min_db);
      const nOut = typeof svRes.n_outputs === "number" ? svRes.n_outputs : 1;
      const nIn = typeof svRes.n_inputs === "number" ? svRes.n_inputs : 1;

      const curves: SingularValueCurve[] = [];
      if (sigmaMaxDb.length > 0) {
        curves.push({
          id: "sigma_max_G",
          label: "σ̄(G)",
          group: "G",
          omega: omegaVec,
          values_db: sigmaMaxDb,
          stroke_dasharray: "",
        });
      }
      if (sigmaMinDb.length > 0) {
        curves.push({
          id: "sigma_min_G",
          label: "σ̲(G)",
          group: "G",
          omega: omegaVec,
          values_db: sigmaMinDb,
          stroke_dasharray: "6 3",
        });
      }

      const omegaTensor = isPlainObject(svRes.omega)
        ? svRes.omega
        : makeFloat64Tensor([omegaVec.length], omegaVec);

      // RGA on exact frequency grid
      let rgaStatus = "undefined";
      const rgaEntries: ParsedRgaEntry[] = [];
      let pairingAnalysis: MimoAnalysisSnapshot["pairingAnalysis"] = [];
      let rgaNote: string | null = null;

      try {
        const rgaParams = { omega: omegaTensor };
        const rgaPlan = await typed.prepareToolExecution("mimo.rga", rgaParams, {
          extraPayload: rgaParams,
        });
        const rgaResp = await this.executeRpc("mimo.rga", rgaPlan.extraPayload);
        if (rgaResp.status === "failure" || !rgaResp.result) {
          rgaNote = rgaResp.error?.message ?? "RGA indisponível para esta planta.";
        } else {
          const rgaRes = rgaResp.result as Record<string, unknown>;
          rgaStatus = String(rgaRes.rga_status ?? "undefined");
          const rawEntries = Array.isArray(rgaRes.entries) ? rgaRes.entries : [];
          for (const rawE of rawEntries) {
            if (!isPlainObject(rawE)) continue;
            const status = rawE.status === "defined" ? "defined" : "undefined";
            const mat =
              status === "defined" ? extract2DComplexMatrix(rawE.rga_matrix, nOut, nIn) : null;
            rgaEntries.push({
              omega: Number(rawE.omega ?? 0),
              status,
              reason: typeof rawE.reason === "string" ? rawE.reason : undefined,
              sigmaMin: typeof rawE.sigma_min === "number" ? rawE.sigma_min : null,
              sigmaMax: typeof rawE.sigma_max === "number" ? rawE.sigma_max : null,
              conditionNumber:
                typeof rawE.condition_number === "number" ? rawE.condition_number : null,
              realMatrix: mat?.real ?? null,
              imagMatrix: mat?.imag ?? null,
              magMatrix: mat?.mag ?? null,
            });
          }
          if (Array.isArray(rgaRes.pairing_analysis)) {
            pairingAnalysis = rgaRes.pairing_analysis
              .filter(isPlainObject)
              .map((pItem) => ({
                output: Number(pItem.output ?? 0),
                recommended_input: Number(pItem.recommended_input ?? 0),
                rga_element_real: Number(pItem.rga_element_real ?? 0),
              }));
          }
        }
      } catch (err: unknown) {
        rgaNote = err instanceof Error ? err.message : String(err);
      }

      // Sensitivity S, T, KS
      let identityVerified: boolean | null = null;
      let maxIdentityResidual: number | null = null;
      let msPeak: number | null = null;
      let mtPeak: number | null = null;
      let sensitivityNote: string | null = null;

      try {
        const sensParams = { omega: omegaTensor, feedback_sign: feedbackSign };
        const sensPlan = await typed.prepareToolExecution("mimo.sensitivity", sensParams, {
          extraPayload: sensParams,
        });
        const sensResp = await this.executeRpc("mimo.sensitivity", sensPlan.extraPayload);
        if (sensResp.status === "failure" || !sensResp.result) {
          sensitivityNote = sensResp.error?.message ?? "Sensibilidade S/T indisponível.";
        } else {
          const sensRes = sensResp.result as Record<string, unknown>;
          const sKey = loopMode === "input" ? "sigma_max_S_input" : "sigma_max_S";
          const tKey = loopMode === "input" ? "sigma_max_T_input" : "sigma_max_T";
          const sDb = toDbArray(extractNumericVector(sensRes[sKey]));
          const tDb = toDbArray(extractNumericVector(sensRes[tKey]));
          const ksDb = toDbArray(extractNumericVector(sensRes.sigma_max_KS));

          if (sDb.length > 0) {
            curves.push({
              id: loopMode === "input" ? "sigma_max_Si" : "sigma_max_So",
              label: loopMode === "input" ? "σ̄(S_i)" : "σ̄(S_o)",
              group: "S",
              omega: omegaVec,
              values_db: sDb,
              stroke_dasharray: "8 3",
            });
          }
          if (tDb.length > 0) {
            curves.push({
              id: loopMode === "input" ? "sigma_max_Ti" : "sigma_max_To",
              label: loopMode === "input" ? "σ̄(T_i)" : "σ̄(T_o)",
              group: "T",
              omega: omegaVec,
              values_db: tDb,
              stroke_dasharray: "2 2",
            });
          }
          if (ksDb.length > 0) {
            curves.push({
              id: "sigma_max_KS",
              label: "σ̄(KS)",
              group: "KS",
              omega: omegaVec,
              values_db: ksDb,
              stroke_dasharray: "10 2 2 2",
            });
          }

          identityVerified =
            typeof sensRes.identity_verified === "boolean" ? sensRes.identity_verified : null;
          const diag = isPlainObject(sensRes.diagnostics)
            ? sensRes.diagnostics
            : (sensResp.diagnostics as Record<string, unknown>);
          const resKey =
            loopMode === "input" ? "max_input_identity_residual" : "max_identity_residual";
          maxIdentityResidual =
            typeof diag?.[resKey] === "number" ? (diag[resKey] as number) : null;
          msPeak = typeof sensRes.Ms_peak === "number" ? sensRes.Ms_peak : null;
          mtPeak = typeof sensRes.Mt_peak === "number" ? sensRes.Mt_peak : null;
        }
      } catch (err: unknown) {
        sensitivityNote = err instanceof Error ? err.message : String(err);
      }

      const dtVal = typeof svRes.dt === "number" ? svRes.dt : null;
      const svModel = buildSingularValuesChartModel({
        dt: dtVal,
        omega: omegaVec,
        curves,
        model_revision: eff.ref.revision,
        project_revision: this.shell.getLqrWorkspace().getProjectRevision(),
        provenance: svResp.provenance as Provenance,
        theme_mode: this.shell.getThemeMode(),
      });

      this.snapshot = {
        plantId: eff.ref.id,
        plantRevision: eff.ref.revision,
        loopMode,
        feedbackSign,
        omega: omegaVec,
        svModel,
        rgaStatus,
        rgaEntries,
        pairingAnalysis,
        identityVerified,
        maxIdentityResidual,
        msPeak,
        mtPeak,
        hinfPeak: typeof svRes.hinf_peak === "number" ? svRes.hinf_peak : null,
        omegaPeak: typeof svRes.omega_peak === "number" ? svRes.omega_peak : null,
        sensitivityNote,
        rgaNote,
      };
      this.selectedRgaIndex = Math.min(
        Math.max(0, Math.floor(rgaEntries.length / 2)),
        Math.max(0, rgaEntries.length - 1),
      );

      this.shell
        .getAnnouncer()
        .announce("Análise MIMO (valores singulares, S/T e RGA) concluída.", "polite", "status");
      this.render();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  private renderSigmaChart(): void {
    const decimals = this.shell.getDisplayDecimals();
    if (!this.snapshot) {
      if (this.sigmaChartSlotEl) this.sigmaChartSlotEl.innerHTML = "";
      if (this.sigmaTableSlotEl) {
        this.sigmaTableSlotEl.innerHTML = `<p>Sem análise MIMO calculada.</p>`;
      }
      return;
    }
    const themeMode = this.shell.getThemeMode();
    const model: SingularValuesChartModel = {
      ...this.snapshot.svModel,
      theme_mode: themeMode,
    };
    if (this.sigmaChartSlotEl) {
      this.sigmaChartSlotEl.innerHTML = renderSingularValuesSvg(model, {
        decimals,
        visibleGroups: this.visibleGroups,
        themeMode,
      });
    }
    if (this.sigmaTableSlotEl) {
      const table = buildAccessibleChartTable(model, decimals);
      this.sigmaTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
    }
  }

  private renderRgaHeatmap(): void {
    const decimals = this.shell.getDisplayDecimals();
    if (!this.snapshot) {
      if (this.rgaOmegaLabelEl) this.rgaOmegaLabelEl.textContent = "—";
      if (this.rgaSliderEl) {
        this.rgaSliderEl.disabled = true;
        this.rgaSliderEl.min = "0";
        this.rgaSliderEl.max = "0";
        this.rgaSliderEl.value = "0";
      }
      if (this.rgaHeatmapSlotEl) {
        this.rgaHeatmapSlotEl.innerHTML = `<p>Aguardando cálculo da RGA para exibir pareamento e condicionamento κ(G).</p>`;
      }
      return;
    }

    const entries = this.snapshot.rgaEntries;
    if (entries.length === 0) {
      if (this.rgaOmegaLabelEl) this.rgaOmegaLabelEl.textContent = "Indisponível";
      if (this.rgaSliderEl) {
        this.rgaSliderEl.disabled = true;
      }
      if (this.rgaHeatmapSlotEl) {
        this.rgaHeatmapSlotEl.innerHTML = `<div class="warning-callout"><strong>RGA indefinida:</strong> ${escapeHtml(this.snapshot.rgaNote ?? "Planta não quadrada ou sem entradas de frequência.")}</div>`;
      }
      return;
    }

    const idx = Math.max(0, Math.min(entries.length - 1, this.selectedRgaIndex));
    this.selectedRgaIndex = idx;
    const entry = entries[idx];

    if (this.rgaSliderEl) {
      this.rgaSliderEl.disabled = false;
      this.rgaSliderEl.min = "0";
      this.rgaSliderEl.max = String(entries.length - 1);
      this.rgaSliderEl.value = String(idx);
    }
    if (this.rgaOmegaLabelEl) {
      this.rgaOmegaLabelEl.textContent = `${formatNumericDisplay(entry.omega, decimals)} rad/s`;
    }

    if (!this.rgaHeatmapSlotEl) return;

    const kappaStr =
      entry.conditionNumber !== null
        ? formatNumericDisplay(entry.conditionNumber, decimals)
        : "∞ (singular)";
    const kappaClass =
      entry.conditionNumber === null || entry.conditionNumber > 100
        ? "badge-experimental"
        : entry.conditionNumber > 10
          ? "badge-beta"
          : "badge-stable";
    const kappaLabel =
      entry.conditionNumber === null
        ? "Singular"
        : entry.conditionNumber > 100
          ? "Mal condicionado"
          : entry.conditionNumber > 10
            ? "Moderado"
            : "Bem condicionado";

    if (entry.status === "undefined" || !entry.realMatrix || !entry.magMatrix) {
      this.rgaHeatmapSlotEl.innerHTML = [
        `<div class="mimo-rga-meta">`,
        `<span class="badge ${kappaClass}">Cond. κ(G): ${escapeHtml(kappaStr)} (${escapeHtml(kappaLabel)})</span>`,
        `</div>`,
        `<div class="warning-callout" role="alert"><strong>RGA indefinida</strong> em ω = ${escapeHtml(formatNumericDisplay(entry.omega, decimals))} rad/s (${escapeHtml(entry.reason ?? "matriz singular")}).</div>`,
      ].join("");
      return;
    }

    const p = entry.realMatrix.length;
    const m = entry.realMatrix[0]?.length ?? 0;
    const headerCols = Array.from({ length: m }, (_, j) => `<th scope="col">u${j + 1}</th>`).join("");
    const bodyRows = entry.realMatrix
      .map((row, i) => {
        const cells = row
          .map((reVal, j) => {
            const imVal = entry.imagMatrix?.[i]?.[j] ?? 0;
            const magVal = entry.magMatrix?.[i]?.[j] ?? Math.abs(reVal);
            const alpha = Math.min(0.65, Math.max(0.08, Math.min(1.5, magVal) * 0.42));
            const bgTint =
              reVal >= 0
                ? `rgba(29, 78, 216, ${alpha.toFixed(2)})`
                : `rgba(180, 83, 9, ${alpha.toFixed(2)})`;
            const complexTxt =
              Math.abs(imVal) > 1e-6
                ? `${formatNumericDisplay(reVal, decimals)} ${imVal >= 0 ? "+" : "−"} j${formatNumericDisplay(Math.abs(imVal), decimals)}`
                : formatNumericDisplay(reVal, decimals);
            return `<td class="rga-cell" style="background:${bgTint}"><strong>${escapeHtml(complexTxt)}</strong><small>|Λ|=${escapeHtml(formatNumericDisplay(magVal, decimals))}</small></td>`;
          })
          .join("");
        return `<tr><th scope="row">y${i + 1}</th>${cells}</tr>`;
      })
      .join("");

    const pairingHtml =
      this.snapshot.pairingAnalysis.length > 0
        ? `<p class="mimo-pairing-hint"><strong>Pareamento sugerido (em baixa freq.):</strong> ${this.snapshot.pairingAnalysis
            .map(
              (pr) =>
                `y${pr.output + 1} ↔ u${pr.recommended_input + 1} (Λ=${formatNumericDisplay(pr.rga_element_real, decimals)})`,
            )
            .join(" | ")}</p>`
        : "";

    this.rgaHeatmapSlotEl.innerHTML = [
      `<div class="mimo-rga-meta">`,
      `<span class="badge ${kappaClass}">Cond. κ(G): ${escapeHtml(kappaStr)} (${escapeHtml(kappaLabel)})</span>`,
      `<span class="badge badge-stable">Status RGA: ${escapeHtml(entry.status)}</span>`,
      `</div>`,
      `<table class="accessible-data-table mimo-rga-table" aria-label="Matriz RGA em ω=${formatNumericDisplay(entry.omega, decimals)} rad/s">`,
      `<thead><tr><th scope="col">Saída \\ Entrada</th>${headerCols}</tr></thead>`,
      `<tbody>${bodyRows}</tbody>`,
      `</table>`,
      pairingHtml,
    ].join("");
  }

  public render(): void {
    const isMimo = this.shell.getActiveTab() === "mimo_frequency";
    setElHidden(this.panelEl, !isMimo);
    if (!isMimo) return;

    const eff = this.shell.getTypedWorkspace().getEffectiveSelection("frequencyPlant");
    if (this.activePlantInfoEl) {
      this.activePlantInfoEl.innerHTML = eff
        ? `Planta MIMO ativa: <strong>${escapeHtml(eff.ref.id)}#r${eff.ref.revision}</strong> — ${escapeHtml(eff.object.summary)}`
        : `Nenhuma planta selecionada no Workspace.`;
    }

    const decimals = this.shell.getDisplayDecimals();
    if (this.diagSummaryEl) {
      if (!this.snapshot) {
        this.diagSummaryEl.innerHTML = `<p>Selecione ou carregue uma planta MIMO 2×2 e clique em <strong>Calcular Análise MIMO</strong>.</p>`;
      } else {
        const s = this.snapshot;
        const loopDesc = s.loopMode === "input" ? "L_i = K · G" : "L_o = G · K";
        const idStr =
          s.maxIdentityResidual !== null
            ? `||S + T − I|| = <code>${formatNumericDisplay(s.maxIdentityResidual, decimals)}</code> (${s.identityVerified ? "Verificado ✓" : "Aviso"})`
            : s.sensitivityNote ?? "N/D";
        const hinfStr =
          s.hinfPeak !== null
            ? `Pico σ̄(G) = <code>${formatNumericDisplay(s.hinfPeak, decimals)}</code> em ω = <code>${formatNumericDisplay(s.omegaPeak ?? 0, decimals)}</code> rad/s`
            : "N/D";
        this.diagSummaryEl.innerHTML = [
          `<p><strong>Malha:</strong> <code>${escapeHtml(loopDesc)}</code> (${escapeHtml(s.feedbackSign)}) | ${hinfStr} | <strong>Identidade:</strong> ${idStr}</p>`,
          s.msPeak !== null
            ? `<p><strong>Picos de Sensibilidade:</strong> M_S = <code>${formatNumericDisplay(s.msPeak, decimals)}</code> | M_T = <code>${formatNumericDisplay(s.mtPeak ?? 0, decimals)}</code></p>`
            : "",
        ].join("");
      }
    }

    this.renderSigmaChart();
    this.renderRgaHeatmap();
  }
}
