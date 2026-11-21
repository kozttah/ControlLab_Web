/**
 * Bancada da Aba 2 — Análise e Projeto SISO na Frequência (Estilo MATLAB `sisotool`)
 * seguindo CL-UX-DIR-001 v1.0.0 Seção 4.2 (`WP-UX-REFACTOR-02-IDENT-SISO-LQR`).
 *
 * Responsabilidades estritas de UI/Apresentação (F8):
 * - Diagrama de blocos da malha fechada (`#siso-loop-diagram-bar`) com pílulas de margens em tempo real.
 * - Sintonizador do compensador `C(s) = K` (`#siso-gain-slider`) com Fast-Preview no arraste
 *   (`pointermove`) e commit autoritativo Python no `pointerup` / teclado (R-23).
 * - Detecção de planta MIMO (`#siso-mimo-guard-callout`) com redirecionamento em 1 clique para a Aba 4.
 * - Grade 2×2 sincronizada (`.siso-charts-grid`) com datatips interativos por clique no SVG
 *   (Bode, Nyquist e Lugar das Raízes congelando todos os polos em malha fechada no ganho K).
 *
 * 100% compatível com erasableSyntaxOnly, verbatimModuleSyntax e FakeElement/FakeDocument.
 */

import {
  escapeHtml,
  formatNumericDisplay,
  getSliderAriaAttributes,
  handleSliderKeyDown,
  type AccessibleSliderConfig,
} from "../../app/accessibility.ts";
import type { ControlLabShell } from "../../app/shell.ts";
import { formatDockObjectSummary } from "../../app/workspace_dock.ts";
import {
  buildAccessibleChartTable,
  inspectBodeAtSvgPoint,
  inspectNyquistAtSvgPoint,
  inspectRootLocusAtSvgPoint,
  parseSvgDimensions,
  renderAccessibleTableHtml,
  renderBodeSvg,
  renderNyquistSvg,
  renderRootLocusSvg,
  renderTimeResponseSvg,
  type BodeChartModel,
  type BodeDatatipInspection,
  type NyquistChartModel,
  type NyquistDatatipInspection,
  type RootLocusChartModel,
  type RootLocusDatatipInspection,
} from "../../charts/scientific_chart.ts";
import type { RegisteredTypedObject } from "../typed_workspace.ts";

export interface SisoViewOptions {
  shell: ControlLabShell;
  container: HTMLElement;
}

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function renderSisoExportBarHtml(slotId: string, label: string): string {
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

function detectPlantDimensions(obj: RegisteredTypedObject | null | undefined): {
  isMimo: boolean;
  inputs: number;
  outputs: number;
} {
  if (!obj) return { isMimo: false, inputs: 1, outputs: 1 };
  const val = obj.value;
  if (obj.kind === "TransferFunction") {
    const num = val.num;
    if (Array.isArray(num)) {
      const p = num.length;
      const m = Array.isArray(num[0]) ? num[0].length : 1;
      return { isMimo: p > 1 || m > 1, inputs: m, outputs: p };
    }
  } else if (obj.kind === "StateSpace") {
    const matrices = (val.matrices as Record<string, unknown> | undefined) ?? val;
    const b = (matrices.B ?? val.B) as { shape?: number[] } | undefined;
    const c = (matrices.C ?? val.C) as { shape?: number[] } | undefined;
    const m =
      Array.isArray(b?.shape) && b.shape.length >= 2
        ? b.shape[1]
        : Array.isArray(val.input_names)
          ? (val.input_names as unknown[]).length
          : 1;
    const p =
      Array.isArray(c?.shape) && c.shape.length >= 2
        ? c.shape[0]
        : Array.isArray(val.output_names)
          ? (val.output_names as unknown[]).length
          : 1;
    return { isMimo: p > 1 || m > 1, inputs: m, outputs: p };
  }
  return { isMimo: false, inputs: 1, outputs: 1 };
}

function extractSvgClickPoint(
  slotEl: HTMLElement,
  ev: Event,
  defaultWidth: number,
  defaultHeight: number,
): { svgX: number; svgY: number } {
  const anyEv = ev as unknown as {
    svgX?: number;
    svgY?: number;
    clientX?: number;
    clientY?: number;
    offsetX?: number;
    offsetY?: number;
  };
  if (typeof anyEv.svgX === "number" && typeof anyEv.svgY === "number") {
    return { svgX: anyEv.svgX, svgY: anyEv.svgY };
  }

  const svgEl = slotEl.querySelector("svg");
  let vbWidth = defaultWidth;
  let vbHeight = defaultHeight;
  if (svgEl) {
    const vbAttr = svgEl.getAttribute("viewBox");
    if (vbAttr) {
      const parsed = parseSvgDimensions(`<svg viewBox="${vbAttr}"></svg>`);
      vbWidth = parsed.width;
      vbHeight = parsed.height;
    }
  }

  if (typeof anyEv.clientX === "number" && typeof anyEv.clientY === "number") {
    const rect =
      (svgEl as unknown as { getBoundingClientRect?: () => DOMRect })?.getBoundingClientRect?.() ??
      (slotEl as unknown as { getBoundingClientRect?: () => DOMRect })?.getBoundingClientRect?.();
    if (rect && rect.width > 0 && rect.height > 0) {
      return {
        svgX: ((anyEv.clientX - rect.left) / rect.width) * vbWidth,
        svgY: ((anyEv.clientY - rect.top) / rect.height) * vbHeight,
      };
    }
    return { svgX: anyEv.clientX, svgY: anyEv.clientY };
  }

  if (typeof anyEv.offsetX === "number") {
    return {
      svgX: anyEv.offsetX,
      svgY: typeof anyEv.offsetY === "number" ? anyEv.offsetY : vbHeight / 2,
    };
  }

  return { svgX: vbWidth / 2, svgY: vbHeight / 2 };
}

export function renderSisoViewHtml(): string {
  return [
    `<section id="siso-workspace-panel" class="panel-card workspace-section" aria-label="Análise e Projeto SISO na Frequência">`,
    `<h3>Análise &amp; Projeto SISO na Frequência</h3>`,
    `<div id="siso-loop-diagram-bar" class="siso-loop-diagram-bar" role="region" aria-label="Diagrama de blocos da malha SISO"></div>`,
    `<div id="siso-mimo-guard-callout" class="mimo-guard-callout warning-callout" role="status" hidden>`,
    `<div class="mimo-guard-text">`,
    `<strong>Modelo Multivariável (MIMO) detectado:</strong>`,
    `<span id="siso-mimo-guard-msg">A bancada SISO analisa plantas 1×1. Utilize a Aba 4 para valores singulares σ(G, S, T) e RGA.</span>`,
    `</div>`,
    `<button type="button" id="btn-siso-open-mimo" class="touch-control btn-primary" data-action="siso-open-mimo">Abrir na Aba 4 — Análise MIMO →</button>`,
    `</div>`,
    `<div class="workspace-two-col">`,
    `<div class="workspace-controls-col">`,
    `<div class="subcard tool-field" id="siso-compensator-tuner">`,
    `<div class="panel-actions"><button type="button" id="btn-siso-eval-all" class="touch-control btn-primary" data-action="siso-eval-all">Atualizar 4 Gráficos SISO (Bode / Nyquist / LR / Degrau)</button></div>`,
    `<label for="siso-gain-slider">Sintonia do Compensador C(s) = K</label>`,
    `<div id="siso-gain-slider" class="touch-control lqr-slider siso-slider" data-action="siso-gain-slider"></div>`,
    `<p id="siso-tuner-status" class="siso-tuner-status">Pré-visualiza no arraste; confirma no motor Python ao soltar.</p>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-siso-edit-compensator" class="touch-control btn-secondary" data-action="siso-open-comp-modal">Editar Compensador C(s)...</button>`,
    `<label for="siso-feedback-sign">Sinal da Realimentação</label>`,
    `<select id="siso-feedback-sign" class="touch-control" data-action="siso-select-feedback-sign" aria-label="Sinal da realimentação">`,
    `<option value="negative">Negativa (1 + K·G = 0)</option>`,
    `<option value="positive">Positiva (1 - K·G = 0)</option>`,
    `</select>`,
    `</div>`,
    `</div>`,
    `<details id="siso-advanced-params-details" class="siso-advanced-details" open>`,
    `<summary class="siso-advanced-summary">Parâmetros de Grade, Atraso Padé &amp; Degrau</summary>`,
    `<div class="subcard tool-field">`,
    `<label>Parâmetros de Resposta em Frequência (Bode / Nyquist / Margens)</label>`,
    `<div class="siso-params-compact-grid">`,
    `<div class="tool-field"><label for="siso-w-min">ω_min (rad/s)</label>`,
    `<input type="number" id="siso-w-min" class="touch-control" min="0.0001" max="1000" step="0.01" value="0.01" aria-label="Frequência mínima ω_min" /></div>`,
    `<div class="tool-field"><label for="siso-w-max">ω_max (rad/s)</label>`,
    `<input type="number" id="siso-w-max" class="touch-control" min="0.1" max="100000" step="10" value="100" aria-label="Frequência máxima ω_max" /></div>`,
    `<div class="tool-field"><label for="siso-n-points">Pontos</label>`,
    `<input type="number" id="siso-n-points" class="touch-control" min="16" max="5000" step="10" value="200" aria-label="Número de pontos na grade de frequência" /></div>`,
    `<div class="tool-field"><label for="siso-delay">Atraso puro τ (s) — Exato e^{-jωτ}</label>`,
    `<input type="number" id="siso-delay" class="touch-control" min="0" max="100" step="0.01" value="0" aria-label="Atraso de transporte em segundos" /></div>`,
    `<div class="tool-field"><label for="siso-use-pade"><input type="checkbox" id="siso-use-pade" data-action="siso-toggle-pade" /> Aproximar via Padé</label></div>`,
    `<div class="tool-field"><label for="siso-pade-order">Ordem Padé</label>`,
    `<input type="number" id="siso-pade-order" class="touch-control" min="1" max="10" step="1" value="1" aria-label="Ordem da aproximação de Padé" /></div>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-siso-eval-bode" class="touch-control btn-primary" data-action="siso-eval-bode">Avaliar Bode / Nyquist / Margens</button>`,
    `</div>`,
    `</div>`,
    `<div class="subcard tool-field">`,
    `<label>Parâmetros do Lugar das Raízes &amp; Guias <span class="badge badge-heuristic">[Heurístico]</span></label>`,
    `<div class="siso-params-compact-grid">`,
    `<div class="tool-field"><label for="siso-rl-kmax">K máx</label>`,
    `<input type="number" id="siso-rl-kmax" class="touch-control" min="1" max="10000" step="10" value="100" aria-label="Ganho máximo K" /></div>`,
    `<div class="tool-field"><label for="siso-rl-zeta">Amortecimento ζ [Heurístico 2ª ordem]</label>`,
    `<input type="number" id="siso-rl-zeta" class="touch-control" min="0.05" max="0.95" step="0.05" value="0.5" aria-label="Fator de amortecimento mínimo ζ" /></div>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-siso-eval-rl" class="touch-control btn-primary" data-action="siso-eval-rl">Avaliar Lugar das Raízes</button>`,
    `</div>`,
    `</div>`,
    `<div class="subcard tool-field">`,
    `<label>Resposta Temporal ao Degrau (frequency.step_response)</label>`,
    `<div class="siso-params-compact-grid">`,
    `<div class="tool-field"><label for="siso-step-amp">Amplitude</label>`,
    `<input type="number" id="siso-step-amp" class="touch-control" min="-100" max="100" step="0.1" value="1" aria-label="Amplitude do degrau" /></div>`,
    `<div class="tool-field"><label for="siso-step-tfinal">Tempo Final (s)</label>`,
    `<input type="number" id="siso-step-tfinal" class="touch-control" min="0.1" max="1000" step="1" value="10" aria-label="Tempo final da simulação" /></div>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-siso-eval-step" class="touch-control btn-primary" data-action="siso-eval-step">Avaliar Degrau SISO</button>`,
    `</div>`,
    `</div>`,
    `</details>`,
    `</div>`,
    `<div class="workspace-results-col">`,
    `<div id="siso-diagnostics-panel" class="diagnostics-panel" aria-live="polite"></div>`,
    `<div class="siso-charts-grid">`,
    `<div class="chart-card">`,
    `<div id="siso-bode-chart-slot" class="chart-container chart-interactive-slot" title="Clique sobre o diagrama de Bode para inspecionar ω, Magnitude e Fase"></div>`,
    `<div id="siso-bode-datatip" class="chart-datatip-bar" aria-live="polite" hidden></div>`,
    renderSisoExportBarHtml("siso-bode-chart-slot", "Bode"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="siso-nyquist-chart-slot" class="chart-container chart-interactive-slot" title="Clique sobre a curva de Nyquist para inspecionar ω e L(jω)"></div>`,
    `<div id="siso-nyquist-datatip" class="chart-datatip-bar" aria-live="polite" hidden></div>`,
    renderSisoExportBarHtml("siso-nyquist-chart-slot", "Nyquist"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="siso-rl-chart-slot" class="chart-container chart-interactive-slot" title="Clique sobre qualquer ramo para congelar os polos em malha fechada no ganho K"></div>`,
    `<div id="siso-rl-datatip" class="chart-datatip-bar" aria-live="polite" hidden></div>`,
    renderSisoExportBarHtml("siso-rl-chart-slot", "Lugar das Raízes"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="siso-time-chart-slot" class="chart-container"></div>`,
    renderSisoExportBarHtml("siso-time-chart-slot", "Resposta ao Degrau"),
    `</div>`,
    `</div>`,
    `<details><summary>Tabela acessível do diagrama de Bode (WCAG 2.2 AA)</summary><div id="siso-bode-table-slot"></div></details>`,
    `<details><summary>Tabela acessível do diagrama de Nyquist (WCAG 2.2 AA)</summary><div id="siso-nyquist-table-slot"></div></details>`,
    `<details><summary>Tabela acessível do Lugar das Raízes (WCAG 2.2 AA)</summary><div id="siso-rl-table-slot"></div></details>`,
    `<details><summary>Tabela acessível da resposta ao degrau SISO (WCAG 2.2 AA)</summary><div id="siso-time-table-slot"></div></details>`,
    `</div>`,
    `</div>`,
    `<section id="siso-compensator-modal" class="modal-dialog new-object-modal" role="dialog" aria-modal="true" aria-labelledby="siso-comp-modal-title" hidden>`,
    `<div class="modal-header">`,
    `<h2 id="siso-comp-modal-title">Editor de Compensador Dinâmico C(s)</h2>`,
    `<button type="button" id="btn-siso-close-comp" class="touch-control btn-secondary btn-small" data-action="siso-close-comp">Fechar</button>`,
    `</div>`,
    `<div class="new-object-mode-bar" role="tablist" aria-label="Modo de edição do compensador">`,
    `<button type="button" id="btn-siso-comp-mode-tf" class="touch-control btn-primary btn-small" data-siso-comp-mode="tf">Função de Transferência (num / den)</button>`,
    `<button type="button" id="btn-siso-comp-mode-zpk" class="touch-control btn-secondary btn-small" data-siso-comp-mode="zpk">Polos &amp; Zeros (K, z_i, p_i)</button>`,
    `</div>`,
    `<div id="siso-comp-modal-error" class="field-error" role="alert" hidden></div>`,
    `<div id="siso-comp-panel-tf" class="new-obj-panel">`,
    `<div class="typed-tf-builder-grid">`,
    `<div class="tool-field"><label for="siso-comp-num">Numerador N_c(s) (ordem decrescente, ex: 1, 2)</label><input id="siso-comp-num" type="text" class="touch-control" value="1" /></div>`,
    `<div class="tool-field"><label for="siso-comp-den">Denominador D_c(s) (ordem decrescente, ex: 1, 10)</label><input id="siso-comp-den" type="text" class="touch-control" value="1" /></div>`,
    `</div>`,
    `<p id="siso-comp-preview" class="dock-item-summary">C(s) = 1</p>`,
    `</div>`,
    `<div id="siso-comp-panel-zpk" class="new-obj-panel" hidden>`,
    `<div class="tool-field"><label for="siso-comp-zpk-gain">Ganho K</label><input id="siso-comp-zpk-gain" type="number" step="0.1" class="touch-control" value="1" /></div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-siso-add-zero" class="touch-control btn-secondary btn-small" data-action="siso-add-zero">+ Adicionar Zero</button>`,
    `<button type="button" id="btn-siso-add-pole" class="touch-control btn-secondary btn-small" data-action="siso-add-pole">+ Adicionar Polo</button>`,
    `</div>`,
    `<div id="siso-comp-zeros-list" class="fuzzy-mf-params-list"></div>`,
    `<div id="siso-comp-poles-list" class="fuzzy-mf-params-list"></div>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-siso-apply-comp" class="touch-control btn-primary" data-action="siso-apply-comp">Aplicar Compensador C(s)</button>`,
    `<button type="button" id="btn-siso-reset-comp" class="touch-control btn-secondary" data-action="siso-reset-comp">Resetar para C(s) = K</button>`,
    `</div>`,
    `</section>`,
    `</section>`,
  ].join("\n");
}

export class SisoView {
  private readonly shell: ControlLabShell;
  private readonly container: HTMLElement;

  private readonly panelEl: HTMLElement | null;
  private readonly loopDiagramBarEl: HTMLElement | null;
  private readonly mimoGuardCalloutEl: HTMLElement | null;
  private readonly mimoGuardMsgEl: HTMLElement | null;
  private readonly gainSliderEl: HTMLElement | null;
  private readonly tunerStatusEl: HTMLElement | null;

  private readonly wMinEl: HTMLInputElement | null;
  private readonly wMaxEl: HTMLInputElement | null;
  private readonly nPointsEl: HTMLInputElement | null;
  private readonly delayEl: HTMLInputElement | null;
  private readonly usePadeEl: HTMLInputElement | null;
  private readonly padeOrderEl: HTMLInputElement | null;
  private readonly feedbackSignEl: HTMLSelectElement | null;
  private readonly rlKMaxEl: HTMLInputElement | null;
  private readonly rlZetaEl: HTMLInputElement | null;
  private readonly stepAmpEl: HTMLInputElement | null;
  private readonly stepTFinalEl: HTMLInputElement | null;

  private readonly diagnosticsPanelEl: HTMLElement | null;
  private readonly bodeChartSlotEl: HTMLElement | null;
  private readonly bodeDatatipEl: HTMLElement | null;
  private readonly nyquistChartSlotEl: HTMLElement | null;
  private readonly nyquistDatatipEl: HTMLElement | null;
  private readonly rlChartSlotEl: HTMLElement | null;
  private readonly rlDatatipEl: HTMLElement | null;
  private readonly timeChartSlotEl: HTMLElement | null;

  private readonly bodeTableSlotEl: HTMLElement | null;
  private readonly nyquistTableSlotEl: HTMLElement | null;
  private readonly rlTableSlotEl: HTMLElement | null;
  private readonly timeTableSlotEl: HTMLElement | null;

  private readonly compModalEl: HTMLElement | null;
  private readonly compModalErrEl: HTMLElement | null;
  private readonly compModeTfBtnEl: HTMLElement | null;
  private readonly compModeZpkBtnEl: HTMLElement | null;
  private readonly compPanelTfEl: HTMLElement | null;
  private readonly compPanelZpkEl: HTMLElement | null;
  private readonly compNumEl: HTMLInputElement | null;
  private readonly compDenEl: HTMLInputElement | null;
  private readonly compPreviewEl: HTMLElement | null;
  private readonly compZpkGainEl: HTMLInputElement | null;
  private readonly compZerosListEl: HTMLElement | null;
  private readonly compPolesListEl: HTMLElement | null;

  private compEditorMode: "tf" | "zpk" = "tf";
  private draftZeros: Array<{ re: number; im: number }> = [];
  private draftPoles: Array<{ re: number; im: number }> = [];

  private isGainPreviewActive = false;
  private dragStartGain = 1.0;
  private previewInFlight = false;

  private lastBodeModelRef: BodeChartModel | null = null;
  private lastNyquistModelRef: NyquistChartModel | null = null;
  private lastRlModelRef: RootLocusChartModel | null = null;

  private selectedBodeTip: BodeDatatipInspection | null = null;
  private selectedNyquistTip: NyquistDatatipInspection | null = null;
  private frozenRlTip: RootLocusDatatipInspection | null = null;

  constructor(options: SisoViewOptions) {
    this.shell = options.shell;
    this.container = options.container;

    this.panelEl = this.container.querySelector<HTMLElement>("#siso-workspace-panel");
    this.loopDiagramBarEl = this.container.querySelector<HTMLElement>("#siso-loop-diagram-bar");
    this.mimoGuardCalloutEl = this.container.querySelector<HTMLElement>("#siso-mimo-guard-callout");
    this.mimoGuardMsgEl = this.container.querySelector<HTMLElement>("#siso-mimo-guard-msg");
    this.gainSliderEl = this.container.querySelector<HTMLElement>("#siso-gain-slider");
    this.tunerStatusEl = this.container.querySelector<HTMLElement>("#siso-tuner-status");

    this.wMinEl = this.container.querySelector<HTMLInputElement>("#siso-w-min");
    this.wMaxEl = this.container.querySelector<HTMLInputElement>("#siso-w-max");
    this.nPointsEl = this.container.querySelector<HTMLInputElement>("#siso-n-points");
    this.delayEl = this.container.querySelector<HTMLInputElement>("#siso-delay");
    this.usePadeEl = this.container.querySelector<HTMLInputElement>("#siso-use-pade");
    this.padeOrderEl = this.container.querySelector<HTMLInputElement>("#siso-pade-order");
    this.feedbackSignEl = this.container.querySelector<HTMLSelectElement>("#siso-feedback-sign");
    this.rlKMaxEl = this.container.querySelector<HTMLInputElement>("#siso-rl-kmax");
    this.rlZetaEl = this.container.querySelector<HTMLInputElement>("#siso-rl-zeta");
    this.stepAmpEl = this.container.querySelector<HTMLInputElement>("#siso-step-amp");
    this.stepTFinalEl = this.container.querySelector<HTMLInputElement>("#siso-step-tfinal");

    this.diagnosticsPanelEl = this.container.querySelector<HTMLElement>("#siso-diagnostics-panel");
    this.bodeChartSlotEl = this.container.querySelector<HTMLElement>("#siso-bode-chart-slot");
    this.bodeDatatipEl = this.container.querySelector<HTMLElement>("#siso-bode-datatip");
    this.nyquistChartSlotEl = this.container.querySelector<HTMLElement>("#siso-nyquist-chart-slot");
    this.nyquistDatatipEl = this.container.querySelector<HTMLElement>("#siso-nyquist-datatip");
    this.rlChartSlotEl = this.container.querySelector<HTMLElement>("#siso-rl-chart-slot");
    this.rlDatatipEl = this.container.querySelector<HTMLElement>("#siso-rl-datatip");
    this.timeChartSlotEl = this.container.querySelector<HTMLElement>("#siso-time-chart-slot");

    this.bodeTableSlotEl = this.container.querySelector<HTMLElement>("#siso-bode-table-slot");
    this.nyquistTableSlotEl = this.container.querySelector<HTMLElement>("#siso-nyquist-table-slot");
    this.rlTableSlotEl = this.container.querySelector<HTMLElement>("#siso-rl-table-slot");
    this.timeTableSlotEl = this.container.querySelector<HTMLElement>("#siso-time-table-slot");

    this.compModalEl = this.container.querySelector<HTMLElement>("#siso-compensator-modal");
    this.compModalErrEl = this.container.querySelector<HTMLElement>("#siso-comp-modal-error");
    this.compModeTfBtnEl = this.container.querySelector<HTMLElement>("#btn-siso-comp-mode-tf");
    this.compModeZpkBtnEl = this.container.querySelector<HTMLElement>("#btn-siso-comp-mode-zpk");
    this.compPanelTfEl = this.container.querySelector<HTMLElement>("#siso-comp-panel-tf");
    this.compPanelZpkEl = this.container.querySelector<HTMLElement>("#siso-comp-panel-zpk");
    this.compNumEl = this.container.querySelector<HTMLInputElement>("#siso-comp-num");
    this.compDenEl = this.container.querySelector<HTMLInputElement>("#siso-comp-den");
    this.compPreviewEl = this.container.querySelector<HTMLElement>("#siso-comp-preview");
    this.compZpkGainEl = this.container.querySelector<HTMLInputElement>("#siso-comp-zpk-gain");
    this.compZerosListEl = this.container.querySelector<HTMLElement>("#siso-comp-zeros-list");
    this.compPolesListEl = this.container.querySelector<HTMLElement>("#siso-comp-poles-list");

    this.bindEvents();
  }

  public isPreviewActive(): boolean {
    const bode = this.shell.getSisoWorkspace().getBodeChartModel();
    return this.isGainPreviewActive || bode?.series_semantics === "preview";
  }

  private hasValidSisoPlant(): boolean {
    const sel = this.shell.getTypedWorkspace().getEffectiveSelection("frequencyPlant");
    if (!sel) return false;
    return !detectPlantDimensions(sel.object).isMimo;
  }

  private readEvalOptions() {
    return {
      customWMin: this.wMinEl ? Number(this.wMinEl.value) : 0.01,
      customWMax: this.wMaxEl ? Number(this.wMaxEl.value) : 100,
      customNPoints: this.nPointsEl ? Number(this.nPointsEl.value) : 200,
      customDelay: this.delayEl ? Number(this.delayEl.value) : 0,
      customUsePade: this.usePadeEl ? this.usePadeEl.checked : false,
      customPadeOrder: this.padeOrderEl ? Number(this.padeOrderEl.value) : 1,
    };
  }

  private triggerPreviewEvalIfReady(): void {
    if (!this.hasValidSisoPlant() || this.previewInFlight) return;
    this.previewInFlight = true;
    void this.shell
      .getSisoWorkspace()
      .evaluateBodeAndMargins({
        previewOnly: true,
        ...this.readEvalOptions(),
      })
      .catch(() => undefined)
      .finally(() => {
        this.previewInFlight = false;
      });
  }

  private bindEvents(): void {
    const sisoWorkspace = this.shell.getSisoWorkspace();

    this.container
      .querySelector<HTMLElement>('[data-action="siso-open-mimo"]')
      ?.addEventListener("click", () => {
        this.shell.switchTab("mimo_frequency");
      });

    this.container
      .querySelector<HTMLElement>('[data-action="siso-eval-all"]')
      ?.addEventListener("click", () => {
        const kMax = this.rlKMaxEl ? Number(this.rlKMaxEl.value) : 100;
        const zeta = this.rlZetaEl ? Number(this.rlZetaEl.value) : 0.5;
        const amp = this.stepAmpEl ? Number(this.stepAmpEl.value) : 1;
        const tf = this.stepTFinalEl ? Number(this.stepTFinalEl.value) : 10;
        void (async () => {
          await sisoWorkspace.evaluateBodeAndMargins(this.readEvalOptions());
          await sisoWorkspace.evaluateRootLocus({
            k_max: kMax,
            damping_ratio: zeta,
          });
          await sisoWorkspace.evaluateStepResponse({
            amplitude: amp,
            t_final: tf,
          });
        })().catch((err: unknown) => {
          this.shell.presentError(err);
        });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="siso-eval-bode"]')
      ?.addEventListener("click", () => {
        void sisoWorkspace
          .evaluateBodeAndMargins(this.readEvalOptions())
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="siso-eval-rl"]')
      ?.addEventListener("click", () => {
        const kMax = this.rlKMaxEl ? Number(this.rlKMaxEl.value) : 100;
        const zeta = this.rlZetaEl ? Number(this.rlZetaEl.value) : 0.5;
        void sisoWorkspace
          .evaluateRootLocus({
            k_max: kMax,
            damping_ratio: zeta,
          })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="siso-eval-step"]')
      ?.addEventListener("click", () => {
        const amp = this.stepAmpEl ? Number(this.stepAmpEl.value) : 1;
        const tf = this.stepTFinalEl ? Number(this.stepTFinalEl.value) : 10;
        void sisoWorkspace
          .evaluateStepResponse({
            amplitude: amp,
            t_final: tf,
          })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.feedbackSignEl?.addEventListener("change", () => {
      const val = this.feedbackSignEl?.value === "positive" ? "positive" : "negative";
      sisoWorkspace.setFeedbackSign(val);
    });

    this.container
      .querySelector<HTMLElement>("#btn-siso-edit-compensator")
      ?.addEventListener("click", () => {
        this.openCompensatorModal();
      });

    this.container
      .querySelector<HTMLElement>("#btn-siso-close-comp")
      ?.addEventListener("click", () => {
        this.closeCompensatorModal();
      });

    this.compModeTfBtnEl?.addEventListener("click", () => {
      this.compEditorMode = "tf";
      this.syncCompensatorModal();
    });
    this.compModeZpkBtnEl?.addEventListener("click", () => {
      this.compEditorMode = "zpk";
      this.syncCompensatorModal();
    });

    const updateTfPreview = () => {
      if (this.compPreviewEl && this.compNumEl && this.compDenEl) {
        this.compPreviewEl.textContent = `C(s) = K · (${this.compNumEl.value || "1"}) / (${this.compDenEl.value || "1"})`;
      }
    };
    this.compNumEl?.addEventListener("input", updateTfPreview);
    this.compDenEl?.addEventListener("input", updateTfPreview);

    this.container
      .querySelector<HTMLElement>('[data-action="siso-add-zero"]')
      ?.addEventListener("click", () => {
        this.draftZeros.push({ re: -1, im: 0 });
        this.renderZpkLists();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="siso-add-pole"]')
      ?.addEventListener("click", () => {
        this.draftPoles.push({ re: -5, im: 0 });
        this.renderZpkLists();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="siso-apply-comp"]')
      ?.addEventListener("click", () => {
        this.applyCompensatorFromModal();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="siso-reset-comp"]')
      ?.addEventListener("click", () => {
        sisoWorkspace.resetCompensator();
        this.draftZeros = [];
        this.draftPoles = [];
        if (this.compNumEl) this.compNumEl.value = "1";
        if (this.compDenEl) this.compDenEl.value = "1";
        this.closeCompensatorModal();
        this.render();
        if (this.hasValidSisoPlant() && sisoWorkspace.getBodeChartModel() !== null) {
          void this.reEvaluateAllCharts();
        }
      });

    if (this.gainSliderEl) {
      this.gainSliderEl.addEventListener("pointerdown", (ev: PointerEvent) => {
        this.dragStartGain = sisoWorkspace.getCompensatorGain();
        this.isGainPreviewActive = true;
        try {
          this.gainSliderEl?.setPointerCapture?.(ev.pointerId);
        } catch {
          // Fallback em ambientes sem pointer capture
        }
        this.renderTunerControls();
      });

      this.gainSliderEl.addEventListener("pointermove", (ev: PointerEvent) => {
        if (!this.isGainPreviewActive || !this.gainSliderEl) return;
        const rect =
          (this.gainSliderEl as unknown as { getBoundingClientRect?: () => DOMRect })?.getBoundingClientRect?.();
        const ratio =
          rect && rect.width > 0
            ? Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width))
            : 0.5;
        const nextGain = Number((0.1 + ratio * (20 - 0.1)).toFixed(2));
        sisoWorkspace.setCompensatorGain(nextGain);
        this.triggerPreviewEvalIfReady();
      });

      this.gainSliderEl.addEventListener("pointerup", (ev: PointerEvent) => {
        if (!this.isGainPreviewActive) return;
        this.isGainPreviewActive = false;
        try {
          if (this.gainSliderEl?.hasPointerCapture?.(ev.pointerId)) {
            this.gainSliderEl.releasePointerCapture?.(ev.pointerId);
          }
        } catch {
          // ignore
        }
        if (this.hasValidSisoPlant()) {
          void sisoWorkspace
            .evaluateBodeAndMargins({
              previewOnly: false,
              ...this.readEvalOptions(),
            })
            .catch((err: unknown) => this.shell.presentError(err));
        } else {
          this.render();
        }
      });

      const cancelGainDrag = (): void => {
        if (!this.isGainPreviewActive) return;
        this.isGainPreviewActive = false;
        sisoWorkspace.setCompensatorGain(this.dragStartGain);
        this.render();
      };
      this.gainSliderEl.addEventListener("pointercancel", cancelGainDrag);
      this.gainSliderEl.addEventListener("blur", cancelGainDrag);

      this.gainSliderEl.addEventListener("keydown", (ev: KeyboardEvent) => {
        const cfg: AccessibleSliderConfig = {
          min: 0.1,
          max: 20,
          step: 0.1,
          value: sisoWorkspace.getCompensatorGain(),
          label: "Ganho do compensador C(s) = K",
        };
        const res = handleSliderKeyDown(ev.key, cfg);
        if (!res.handled) return;
        ev.preventDefault();
        if (res.cancelled) {
          cancelGainDrag();
          return;
        }
        const safeK = Math.max(0.1, Number(res.nextValue.toFixed(2)));
        sisoWorkspace.setCompensatorGain(safeK);
        if (res.committed && this.hasValidSisoPlant()) {
          void sisoWorkspace
            .evaluateBodeAndMargins({
              previewOnly: false,
              ...this.readEvalOptions(),
            })
            .catch((err: unknown) => this.shell.presentError(err));
        }
      });
    }

    this.bodeChartSlotEl?.addEventListener("click", (ev: Event) => {
      const model = sisoWorkspace.getBodeChartModel();
      if (!model || !this.bodeChartSlotEl) return;
      const { svgX } = extractSvgClickPoint(this.bodeChartSlotEl, ev, 640, 480);
      const tip = inspectBodeAtSvgPoint(model, svgX);
      if (tip) {
        this.selectedBodeTip = tip;
        this.renderBodeSlotAndTip();
      }
    });

    this.nyquistChartSlotEl?.addEventListener("click", (ev: Event) => {
      const model = sisoWorkspace.getNyquistChartModel();
      if (!model || !this.nyquistChartSlotEl) return;
      const { svgX, svgY } = extractSvgClickPoint(this.nyquistChartSlotEl, ev, 640, 400);
      const tip = inspectNyquistAtSvgPoint(model, svgX, svgY);
      if (tip) {
        this.selectedNyquistTip = tip;
        this.renderNyquistSlotAndTip();
      }
    });

    this.rlChartSlotEl?.addEventListener("click", (ev: Event) => {
      const model = sisoWorkspace.getRootLocusChartModel();
      if (!model || !this.rlChartSlotEl) return;
      const { svgX, svgY } = extractSvgClickPoint(this.rlChartSlotEl, ev, 640, 420);
      const tip = inspectRootLocusAtSvgPoint(model, svgX, svgY);
      if (tip) {
        this.frozenRlTip = tip;
        this.renderRootLocusSlotAndTip();
      }
    });
  }

  private renderTunerControls(): void {
    const sisoWorkspace = this.shell.getSisoWorkspace();
    const decimals = this.shell.getDisplayDecimals();
    const gain = sisoWorkspace.getCompensatorGain();

    if (this.gainSliderEl) {
      const cfg: AccessibleSliderConfig = {
        min: 0.1,
        max: 20,
        step: 0.1,
        value: gain,
        label: "Ganho do compensador C(s) = K",
      };
      const attrs = getSliderAriaAttributes(cfg, decimals);
      for (const [k, v] of Object.entries(attrs)) {
        this.gainSliderEl.setAttribute(k, v);
      }
      this.gainSliderEl.textContent = `Ganho K: ${formatNumericDisplay(gain, Math.min(decimals, 3))}`;
    }

    if (this.tunerStatusEl) {
      this.tunerStatusEl.textContent = this.isPreviewActive()
        ? "Pré-visualizando… (solte para confirmar no Python; exportação bloqueada R-23)"
        : "Sincronizado (pré-visualiza no arraste; confirma no motor Python ao soltar)";
    }

    if (this.feedbackSignEl) {
      this.feedbackSignEl.value = sisoWorkspace.getFeedbackSign();
    }
  }

  private renderLoopDiagramHeader(): void {
    if (!this.loopDiagramBarEl) return;
    const sisoWorkspace = this.shell.getSisoWorkspace();
    const typedWorkspace = this.shell.getTypedWorkspace();
    const decimals = this.shell.getDisplayDecimals();
    const sel = typedWorkspace.getEffectiveSelection("frequencyPlant");
    const gain = sisoWorkspace.getCompensatorGain();
    const fbSign = sisoWorkspace.getFeedbackSign();
    const margins = sisoWorkspace.getMarginsView();

    const sumLabel = fbSign === "positive" ? "Σ (r + y)" : "Σ (r - y)";
    const plantText = sel
      ? `${sel.object.id} (${formatDockObjectSummary(sel.object, Math.min(decimals, 2))})`
      : "Nenhuma planta SISO selecionada";

    const fmtM = (v: number | null | undefined, unit: string) =>
      typeof v === "number" && Number.isFinite(v)
        ? `${formatNumericDisplay(v, decimals)}${unit}`
        : margins
          ? "∞"
          : "—";

    const stablePill = !margins
      ? `<span class="badge badge-sufficient">Malha Fechada: Aguardando</span>`
      : margins.closed_loop_stable === true
        ? `<span class="badge badge-exact">Malha Fechada: Estável</span>`
        : margins.closed_loop_stable === false
          ? `<span class="badge badge-experimental">Malha Fechada: Instável</span>`
          : `<span class="badge badge-approximate">Malha Fechada: Indeterminada</span>`;

    const syncPill = this.isPreviewActive()
      ? `<span class="badge badge-preview">Pré-visualizando…</span>`
      : `<span class="badge badge-stable">Sincronizado</span>`;

    const compExpr = sisoWorkspace.formatCompensatorExpression(decimals);

    this.loopDiagramBarEl.innerHTML = [
      `<div class="block-diagram-flow" aria-label="Estrutura da malha fechada SISO">`,
      `<span class="block-node block-signal">r</span>`,
      `<span class="block-arrow" aria-hidden="true">→</span>`,
      `<span class="block-node block-sum">${escapeHtml(sumLabel)}</span>`,
      `<span class="block-arrow" aria-hidden="true">→</span>`,
      `<button type="button" class="block-node block-comp touch-control" data-action="siso-open-comp-modal" title="Clique para editar compensador C(s)">C(s) = ${escapeHtml(compExpr)}</button>`,
      `<span class="block-arrow" aria-hidden="true">→</span>`,
      `<span class="block-node block-plant" title="${escapeHtml(plantText)}">G(s): ${escapeHtml(plantText)}</span>`,
      `<span class="block-arrow" aria-hidden="true">→</span>`,
      `<span class="block-node block-signal">y</span>`,
      `</div>`,
      `<div class="loop-margins-pills">`,
      `<span class="badge badge-sufficient">MF: ${escapeHtml(fmtM(margins?.critical_phase_margin_deg, "°"))}</span>`,
      `<span class="badge badge-sufficient">MG: ${escapeHtml(fmtM(margins?.critical_gain_margin_db, " dB"))}</span>`,
      stablePill,
      syncPill,
      `</div>`,
    ].join("");

    this.loopDiagramBarEl
      .querySelector<HTMLElement>('[data-action="siso-open-comp-modal"]')
      ?.addEventListener("click", () => {
        this.openCompensatorModal();
      });
  }

  private openCompensatorModal(): void {
    const siso = this.shell.getSisoWorkspace();
    const comp = siso.getCompensatorTf();
    this.compEditorMode = comp.mode === "zpk" ? "zpk" : "tf";
    this.draftZeros = comp.zeros.map((z) => ({ ...z }));
    this.draftPoles = comp.poles.map((p) => ({ ...p }));
    if (this.compNumEl) this.compNumEl.value = comp.num.join(", ");
    if (this.compDenEl) this.compDenEl.value = comp.den.join(", ");
    if (this.compZpkGainEl) this.compZpkGainEl.value = String(comp.gain);
    if (this.compPreviewEl) {
      this.compPreviewEl.textContent = `C(s) = ${siso.formatCompensatorExpression(this.shell.getDisplayDecimals())}`;
    }
    if (this.compModalErrEl) {
      this.compModalErrEl.textContent = "";
      setElHidden(this.compModalErrEl, true);
    }
    this.syncCompensatorModal();
    this.renderZpkLists();
    setElHidden(this.compModalEl, false);
  }

  private closeCompensatorModal(): void {
    setElHidden(this.compModalEl, true);
  }

  private syncCompensatorModal(): void {
    setElHidden(this.compPanelTfEl, this.compEditorMode !== "tf");
    setElHidden(this.compPanelZpkEl, this.compEditorMode !== "zpk");
  }

  private renderZpkLists(): void {
    const renderList = (
      el: HTMLElement | null,
      items: Array<{ re: number; im: number }>,
      kind: "zero" | "pole",
      labelPrefix: string,
    ) => {
      if (!el) return;
      if (items.length === 0) {
        el.innerHTML = `<p class="dock-empty">Nenhum ${kind === "zero" ? "zero" : "polo"} adicionado.</p>`;
        return;
      }
      el.innerHTML = items
        .map(
          (item, idx) => [
            `<div class="fuzzy-param-row" data-zpk-kind="${kind}" data-zpk-idx="${idx}">`,
            `<strong>${labelPrefix}${idx + 1}</strong>`,
            `<label class="fuzzy-param-cell"><span>Re</span><input type="number" step="0.5" class="touch-control id-param-input" value="${item.re}" data-zpk-field="re" data-zpk-kind="${kind}" data-zpk-idx="${idx}" aria-label="${labelPrefix}${idx + 1} Re" /></label>`,
            `<label class="fuzzy-param-cell"><span>Im</span><input type="number" step="0.5" class="touch-control id-param-input" value="${item.im}" data-zpk-field="im" data-zpk-kind="${kind}" data-zpk-idx="${idx}" aria-label="${labelPrefix}${idx + 1} Im" /></label>`,
            `<button type="button" class="touch-control btn-secondary btn-small" data-action="siso-remove-zpk" data-zpk-kind="${kind}" data-zpk-idx="${idx}" aria-label="Remover ${labelPrefix}${idx + 1}">×</button>`,
            `</div>`,
          ].join(""),
        )
        .join("");

      for (const inp of Array.from(el.querySelectorAll<HTMLInputElement>("input[data-zpk-field]"))) {
        inp.addEventListener("change", () => {
          const idx = Number(inp.getAttribute("data-zpk-idx"));
          const field = inp.getAttribute("data-zpk-field") === "im" ? "im" : "re";
          const val = Number(inp.value);
          if (Number.isFinite(val) && items[idx]) {
            items[idx][field] = val;
          }
        });
      }
      for (const btn of Array.from(el.querySelectorAll<HTMLElement>('[data-action="siso-remove-zpk"]'))) {
        btn.addEventListener("click", () => {
          const idx = Number(btn.getAttribute("data-zpk-idx"));
          if (Number.isInteger(idx) && idx >= 0 && idx < items.length) {
            items.splice(idx, 1);
            this.renderZpkLists();
          }
        });
      }
    };
    renderList(this.compZerosListEl, this.draftZeros, "zero", "z");
    renderList(this.compPolesListEl, this.draftPoles, "pole", "p");
  }

  private async reEvaluateAllCharts(): Promise<void> {
    const siso = this.shell.getSisoWorkspace();
    const kMax = this.rlKMaxEl ? Number(this.rlKMaxEl.value) : 100;
    const zeta = this.rlZetaEl ? Number(this.rlZetaEl.value) : 0.5;
    const amp = this.stepAmpEl ? Number(this.stepAmpEl.value) : 1;
    const tf = this.stepTFinalEl ? Number(this.stepTFinalEl.value) : 10;
    try {
      await siso.evaluateBodeAndMargins(this.readEvalOptions());
      await siso.evaluateRootLocus({ k_max: kMax, damping_ratio: zeta });
      await siso.evaluateStepResponse({ amplitude: amp, t_final: tf });
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  private applyCompensatorFromModal(): void {
    const siso = this.shell.getSisoWorkspace();
    try {
      if (this.compModalErrEl) {
        this.compModalErrEl.textContent = "";
        setElHidden(this.compModalErrEl, true);
      }
      if (this.compEditorMode === "tf") {
        const parseNums = (raw: string, name: string): number[] => {
          const parts = raw
            .split(/[\s,;]+/)
            .map((s) => s.trim())
            .filter(Boolean);
          if (parts.length === 0) {
            throw new Error(`${name} deve conter ao menos um coeficiente.`);
          }
          const nums = parts.map(Number);
          if (nums.some((v) => !Number.isFinite(v))) {
            throw new Error(`${name} contém coeficiente inválido.`);
          }
          return nums;
        };
        const num = parseNums(this.compNumEl?.value ?? "1", "Numerador");
        const den = parseNums(this.compDenEl?.value ?? "1", "Denominador");
        siso.setCompensatorTf(num, den, "tf");
      } else {
        const gain = Number(this.compZpkGainEl?.value ?? "1");
        siso.setCompensatorZpk(gain, this.draftZeros, this.draftPoles);
      }
      this.closeCompensatorModal();
      this.render();
      if (this.hasValidSisoPlant()) {
        void this.reEvaluateAllCharts();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (this.compModalErrEl) {
        this.compModalErrEl.textContent = msg;
        setElHidden(this.compModalErrEl, false);
      }
      this.shell.presentError(err);
    }
  }

  private renderBodeSlotAndTip(): void {
    const model = this.shell.getSisoWorkspace().getBodeChartModel();
    const decimals = this.shell.getDisplayDecimals();
    const themeMode = this.shell.getThemeMode();
    if (this.bodeChartSlotEl) {
      this.bodeChartSlotEl.innerHTML = model
        ? renderBodeSvg(model, {
            decimals,
            selectedSampleIndex: this.selectedBodeTip?.sampleIndex ?? null,
            themeMode,
          })
        : "";
    }
    if (this.bodeDatatipEl) {
      if (model && this.selectedBodeTip) {
        const t = this.selectedBodeTip;
        this.bodeDatatipEl.innerHTML = [
          `<span class="datatip-readout"><strong>Datatip Bode:</strong> ω = <code>${escapeHtml(formatNumericDisplay(t.omega, decimals))}</code> rad/s | Mag = <code>${escapeHtml(formatNumericDisplay(t.mag_db, decimals))}</code> dB | Fase = <code>${escapeHtml(formatNumericDisplay(t.phase_deg, decimals))}</code>°</span>`,
          `<button type="button" id="btn-siso-bode-clear-tip" class="touch-control btn-secondary btn-small" data-action="siso-clear-bode-tip">Limpar</button>`,
        ].join("");
        setElHidden(this.bodeDatatipEl, false);
        this.bodeDatatipEl
          .querySelector("#btn-siso-bode-clear-tip")
          ?.addEventListener("click", () => {
            this.selectedBodeTip = null;
            this.renderBodeSlotAndTip();
          });
      } else {
        this.bodeDatatipEl.innerHTML = "";
        setElHidden(this.bodeDatatipEl, true);
      }
    }
  }

  private renderNyquistSlotAndTip(): void {
    const model = this.shell.getSisoWorkspace().getNyquistChartModel();
    const decimals = this.shell.getDisplayDecimals();
    const themeMode = this.shell.getThemeMode();
    if (this.nyquistChartSlotEl) {
      this.nyquistChartSlotEl.innerHTML = model
        ? renderNyquistSvg(model, {
            decimals,
            selectedSampleIndex: this.selectedNyquistTip?.sampleIndex ?? null,
            themeMode,
          })
        : "";
    }
    if (this.nyquistDatatipEl) {
      if (model && this.selectedNyquistTip) {
        const t = this.selectedNyquistTip;
        const imSign = t.im >= 0 ? "+" : "-";
        const imAbs = formatNumericDisplay(Math.abs(t.im), decimals);
        this.nyquistDatatipEl.innerHTML = [
          `<span class="datatip-readout"><strong>Datatip Nyquist:</strong> ω = <code>${escapeHtml(formatNumericDisplay(t.omega, decimals))}</code> rad/s | L(jω) = <code>${escapeHtml(formatNumericDisplay(t.re, decimals))} ${imSign} j·${escapeHtml(imAbs)}</code></span>`,
          `<button type="button" id="btn-siso-nyquist-clear-tip" class="touch-control btn-secondary btn-small" data-action="siso-clear-nyquist-tip">Limpar</button>`,
        ].join("");
        setElHidden(this.nyquistDatatipEl, false);
        this.nyquistDatatipEl
          .querySelector("#btn-siso-nyquist-clear-tip")
          ?.addEventListener("click", () => {
            this.selectedNyquistTip = null;
            this.renderNyquistSlotAndTip();
          });
      } else {
        this.nyquistDatatipEl.innerHTML = "";
        setElHidden(this.nyquistDatatipEl, true);
      }
    }
  }

  private renderRootLocusSlotAndTip(): void {
    const model = this.shell.getSisoWorkspace().getRootLocusChartModel();
    const decimals = this.shell.getDisplayDecimals();
    const themeMode = this.shell.getThemeMode();
    if (this.rlChartSlotEl) {
      this.rlChartSlotEl.innerHTML = model
        ? renderRootLocusSvg(model, {
            decimals,
            frozenGainIndex: this.frozenRlTip?.gainIndex ?? null,
            themeMode,
          })
        : "";
    }
    if (this.rlDatatipEl) {
      if (model && this.frozenRlTip) {
        const t = this.frozenRlTip;
        const polesText = t.poles
          .map((p) => {
            const imSign = p.imag >= 0 ? "+" : "-";
            return `Ramo ${p.branchIndex + 1}: ${formatNumericDisplay(p.real, decimals)} ${imSign} j${formatNumericDisplay(Math.abs(p.imag), decimals)}`;
          })
          .join(" | ");
        this.rlDatatipEl.innerHTML = [
          `<span class="datatip-readout"><strong>Polos congelados em K = <code>${escapeHtml(formatNumericDisplay(t.gain_K, decimals))}</code>:</strong> ${escapeHtml(polesText)}</span>`,
          `<div class="panel-actions">`,
          `<button type="button" id="btn-siso-rl-apply-k" class="touch-control btn-secondary btn-small" data-action="siso-rl-apply-k">Aplicar K</button>`,
          `<button type="button" id="btn-siso-rl-clear-tip" class="touch-control btn-secondary btn-small" data-action="siso-clear-rl-tip">Limpar</button>`,
          `</div>`,
        ].join("");
        setElHidden(this.rlDatatipEl, false);

        this.rlDatatipEl
          .querySelector("#btn-siso-rl-apply-k")
          ?.addEventListener("click", () => {
            if (Number.isFinite(t.gain_K) && t.gain_K !== 0) {
              this.shell.getSisoWorkspace().setCompensatorGain(t.gain_K);
            }
          });
        this.rlDatatipEl
          .querySelector("#btn-siso-rl-clear-tip")
          ?.addEventListener("click", () => {
            this.frozenRlTip = null;
            this.renderRootLocusSlotAndTip();
          });
      } else {
        this.rlDatatipEl.innerHTML = "";
        setElHidden(this.rlDatatipEl, true);
      }
    }
  }

  public render(): void {
    const activeTab = this.shell.getActiveTab();
    const isSiso = activeTab === "siso_frequency";
    setElHidden(this.panelEl, !isSiso);

    const sisoWorkspace = this.shell.getSisoWorkspace();
    const typedWorkspace = this.shell.getTypedWorkspace();
    const decimals = this.shell.getDisplayDecimals();

    // MIMO guard check
    const selPlant = typedWorkspace.getEffectiveSelection("frequencyPlant")?.object ?? null;
    const dims = detectPlantDimensions(selPlant);
    setElHidden(this.mimoGuardCalloutEl, !dims.isMimo);
    if (dims.isMimo && this.mimoGuardMsgEl && selPlant) {
      this.mimoGuardMsgEl.textContent = `O modelo '${selPlant.id}' possui ${dims.inputs} entrada(s) e ${dims.outputs} saída(s). Esta bancada suporta apenas plantas SISO (1×1).`;
    }

    this.renderLoopDiagramHeader();
    this.renderTunerControls();

    if (!isSiso) {
      return;
    }

    const bodeChart = sisoWorkspace.getBodeChartModel();
    if (bodeChart !== this.lastBodeModelRef) {
      this.lastBodeModelRef = bodeChart;
      this.selectedBodeTip = null;
    }

    const nyquistChart = sisoWorkspace.getNyquistChartModel();
    if (nyquistChart !== this.lastNyquistModelRef) {
      this.lastNyquistModelRef = nyquistChart;
      this.selectedNyquistTip = null;
    }

    const rlChart = sisoWorkspace.getRootLocusChartModel();
    if (rlChart !== this.lastRlModelRef) {
      this.lastRlModelRef = rlChart;
      this.frozenRlTip = null;
    }

    const margins = sisoWorkspace.getMarginsView();
    if (this.diagnosticsPanelEl) {
      if (!margins) {
        this.diagnosticsPanelEl.innerHTML = `<p>Aguardando avaliação de resposta em frequência (Bode / Nyquist / Margens) ou Lugar das Raízes.</p>`;
      } else {
        const fmtM = (v: number | null, unit: string) =>
          v !== null ? `${formatNumericDisplay(v, decimals)} ${unit}` : "∞";
        const pmStr = fmtM(margins.critical_phase_margin_deg, "°");
        const gmStr = fmtM(margins.critical_gain_margin_db, "dB");
        const wgcStr = fmtM(margins.critical_omega_gc, "rad/s");
        const wpcStr = fmtM(margins.critical_omega_pc, "rad/s");
        const dmStr = fmtM(margins.critical_delay_margin_sec, "s");
        const clStableStr =
          margins.closed_loop_stable === true
            ? `<span data-cl-status="stable">Estável em Malha Fechada</span>`
            : margins.closed_loop_stable === false
              ? `<strong data-cl-status="unstable">INSTÁVEL em Malha Fechada</strong>`
              : "Indeterminado";

        const multipleCrossingWarn = margins.has_multiple_crossings
          ? `<p class="warning-callout" data-warning-kind="multiple-crossings"><strong>Aviso:</strong> Múltiplas frequências de cruzamento detectadas (n_gc=${margins.gain_crossovers.length}, n_pc=${margins.phase_crossovers.length}). Todas as margens devem ser avaliadas antes de atestar robustez (T-FREQ-02).</p>`
          : "";

        this.diagnosticsPanelEl.innerHTML = [
          `<p><strong>Margens de Estabilidade:</strong> MF=<code>${pmStr}</code> (em ω_gc=<code>${wgcStr}</code>) | MG=<code>${gmStr}</code> (em ω_pc=<code>${wpcStr}</code>) | Margem de atraso=<code>${dmStr}</code> | ${clStableStr}</p>`,
          multipleCrossingWarn,
        ].join("");
      }
    }

    this.renderBodeSlotAndTip();
    if (this.bodeTableSlotEl) {
      if (bodeChart) {
        const table = buildAccessibleChartTable(bodeChart, decimals);
        this.bodeTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
      } else {
        this.bodeTableSlotEl.innerHTML = `<p>Sem dados de Bode para exibir.</p>`;
      }
    }

    this.renderNyquistSlotAndTip();
    if (this.nyquistTableSlotEl) {
      if (nyquistChart) {
        const table = buildAccessibleChartTable(nyquistChart, decimals);
        this.nyquistTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
      } else {
        this.nyquistTableSlotEl.innerHTML = `<p>Sem dados de Nyquist para exibir.</p>`;
      }
    }

    this.renderRootLocusSlotAndTip();
    if (this.rlTableSlotEl) {
      if (rlChart) {
        const table = buildAccessibleChartTable(rlChart, decimals);
        this.rlTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
      } else {
        this.rlTableSlotEl.innerHTML = `<p>Sem dados de Lugar das Raízes para exibir.</p>`;
      }
    }

    const timeChart = sisoWorkspace.getTimeResponseChartModel();
    if (this.timeChartSlotEl) {
      this.timeChartSlotEl.innerHTML = timeChart
        ? renderTimeResponseSvg(timeChart, { decimals, themeMode: this.shell.getThemeMode() })
        : "";
    }
    if (this.timeTableSlotEl) {
      if (timeChart) {
        const table = buildAccessibleChartTable(timeChart, decimals);
        this.timeTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
      } else {
        this.timeTableSlotEl.innerHTML = `<p>Sem dados de resposta ao degrau para exibir.</p>`;
      }
    }
  }
}
