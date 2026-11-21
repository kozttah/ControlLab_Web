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
  buildTimeResponseChartModel,
  renderAccessibleTableHtml,
  renderSingularValuesSvg,
  renderTimeResponseSvg,
  type SingularValueCurve,
  type SingularValuesChartModel,
  type TimeResponseChartModel,
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

interface MimoDecouplerSnapshot {
  omegaTarget: number;
  realizationMode: "static" | "first_order";
  kappaBefore: number | null;
  kappaAfter: number | null;
  rgaOffdiagBefore: number | null;
  rgaOffdiagAfter: number | null;
  rgaAfterMatrix: number[][] | null;
  decoupler: Record<string, unknown> | null;
  decoupledPlant: Record<string, unknown> | null;
}

interface MimoClosedLoopSnapshot {
  isStable: boolean;
  maxCrossCoupling: number | null;
  poles: Array<{ re: number; im: number }>;
  timeModel: TimeResponseChartModel;
}

interface MimoHinfSnapshot {
  gammaAchieved: number | null;
  hinfNormGrid: number | null;
  isStable: boolean;
  gpSummary: {
    n_states: number;
    n_w: number;
    n_u: number;
    n_z: number;
    n_y: number;
  } | null;
  svModel: SingularValuesChartModel;
  controller: Record<string, unknown> | null;
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

function extractReal2DMatrix(raw: unknown): number[][] | null {
  if (Array.isArray(raw)) {
    const rows: number[][] = [];
    for (const row of raw) {
      if (!Array.isArray(row)) return null;
      rows.push(row.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : 0)));
    }
    return rows.length > 0 ? rows : null;
  }
  if (isPlainObject(raw) && Array.isArray(raw.shape) && Array.isArray(raw.data)) {
    const shape = raw.shape as number[];
    const data = raw.data as number[];
    if (shape.length !== 2) return null;
    const rows = Number(shape[0] ?? 0);
    const cols = Number(shape[1] ?? 0);
    if (rows <= 0 || cols <= 0 || data.length < rows * cols) return null;
    const out: number[][] = [];
    for (let i = 0; i < rows; i += 1) {
      const r: number[] = [];
      for (let j = 0; j < cols; j += 1) {
        const val = Number(data[i * cols + j] ?? 0);
        r.push(Number.isFinite(val) ? val : 0);
      }
      out.push(r);
    }
    return out;
  }
  return null;
}

function extractStepResponseMatrix(
  raw: unknown,
  nPointsFallback: number,
): { matrix: number[][]; outputNames: string[] } {
  // Backend retorna tensor 3D (p, n_points, p): step_resp[j, k, i] = resposta de y_{i+1} ao degrau em r_{j+1}
  if (isPlainObject(raw) && Array.isArray(raw.shape) && Array.isArray(raw.data)) {
    const shape = raw.shape as number[];
    const data = raw.data as number[];
    if (shape.length === 3) {
      const nIn = Number(shape[0] ?? 1);
      const nPts = Number(shape[1] ?? nPointsFallback);
      const nOut = Number(shape[2] ?? 1);
      const outputNames: string[] = [];
      for (let j = 0; j < nIn; j += 1) {
        for (let i = 0; i < nOut; i += 1) {
          outputNames.push(`r${j + 1}→y${i + 1}`);
        }
      }
      const matrix: number[][] = [];
      for (let k = 0; k < nPts; k += 1) {
        const row: number[] = [];
        for (let j = 0; j < nIn; j += 1) {
          for (let i = 0; i < nOut; i += 1) {
            const idx = j * (nPts * nOut) + k * nOut + i;
            const val = Number(data[idx] ?? 0);
            row.push(Number.isFinite(val) ? val : 0);
          }
        }
        matrix.push(row);
      }
      return { matrix, outputNames };
    }
  }
  if (Array.isArray(raw) && raw.length > 0 && Array.isArray(raw[0])) {
    const nIn = raw.length;
    const firstChannel = raw[0] as unknown[];
    const nPts = firstChannel.length;
    const nOut = Array.isArray(firstChannel[0]) ? (firstChannel[0] as unknown[]).length : 1;
    const outputNames: string[] = [];
    for (let j = 0; j < nIn; j += 1) {
      for (let i = 0; i < nOut; i += 1) {
        outputNames.push(`r${j + 1}→y${i + 1}`);
      }
    }
    const matrix: number[][] = [];
    for (let k = 0; k < nPts; k += 1) {
      const row: number[] = [];
      for (let j = 0; j < nIn; j += 1) {
        const ch = raw[j] as unknown[];
        const pt = ch?.[k];
        if (Array.isArray(pt)) {
          for (let i = 0; i < nOut; i += 1) {
            const val = Number(pt[i] ?? 0);
            row.push(Number.isFinite(val) ? val : 0);
          }
        } else {
          const val = Number(pt ?? 0);
          row.push(Number.isFinite(val) ? val : 0);
        }
      }
      matrix.push(row);
    }
    return { matrix, outputNames };
  }
  return { matrix: [], outputNames: [] };
}

function extractComplexPoles(raw: unknown): Array<{ re: number; im: number }> {
  if (Array.isArray(raw)) {
    const poles: Array<{ re: number; im: number }> = [];
    for (const item of raw) {
      if (Array.isArray(item) && item.length >= 2) {
        poles.push({ re: Number(item[0] ?? 0), im: Number(item[1] ?? 0) });
      } else if (isPlainObject(item)) {
        poles.push({
          re: Number(item.re ?? item.real ?? 0),
          im: Number(item.im ?? item.imag ?? 0),
        });
      }
    }
    return poles;
  }
  if (isPlainObject(raw) && Array.isArray(raw.real)) {
    const reArr = raw.real as number[];
    const imArr = Array.isArray(raw.imag) ? (raw.imag as number[]) : [];
    return reArr.map((re, idx) => ({ re: Number(re ?? 0), im: Number(imArr[idx] ?? 0) }));
  }
  return [];
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
    `<div id="mimo-synthesis-card" class="subcard mimo-synthesis-card">`,
    `<h4>Síntese MIMO — Desacoplador SVD &amp; Malha Fechada Descentralizada</h4>`,
    `<div class="mimo-synthesis-split">`,
    `<div class="mimo-synthesis-col">`,
    `<h5>1. Desacoplador SVD</h5>`,
    `<div class="mimo-params-row panel-actions">`,
    `<label for="mimo-decoupler-omega">Frequência alvo ω₀ (rad/s)</label>`,
    `<input type="number" id="mimo-decoupler-omega" class="touch-control id-param-input" min="0.0001" step="0.1" value="1.0" aria-label="Frequência alvo ω₀ (rad/s)" />`,
    `<label for="mimo-decoupler-mode">Modo</label>`,
    `<select id="mimo-decoupler-mode" class="touch-control" aria-label="Modo de realização do desacoplador">`,
    `<option value="static">Pré-compensador Estático W₀</option>`,
    `<option value="first_order">Aproximação Realizável 1ª Ordem W₁(s)</option>`,
    `</select>`,
    `<button type="button" id="btn-mimo-design-decoupler" class="touch-control btn-primary" data-action="mimo-design-decoupler">Projetar Desacoplador SVD</button>`,
    `<button type="button" id="btn-mimo-register-decoupler" class="touch-control btn-secondary" data-action="mimo-register-decoupler" disabled aria-disabled="true">Registrar Planta Desacoplada</button>`,
    `</div>`,
    `<div id="mimo-decoupler-summary" class="diagnostics-panel" aria-live="polite"><p>Projete o desacoplador SVD para comparar κ(G), norma off-diagonal e RGA pós-desacoplamento.</p></div>`,
    `</div>`,
    `<div class="mimo-synthesis-col">`,
    `<h5>2. Simulação em Malha Fechada (Degrau Canal-a-Canal)</h5>`,
    `<div class="mimo-params-row panel-actions">`,
    `<label for="mimo-cl-gains">Ganhos diagonais K_diag (ex: 1.0, 1.0)</label>`,
    `<input type="text" id="mimo-cl-gains" class="touch-control" value="1.0, 1.0" aria-label="Ganhos diagonais K_diag" />`,
    `<label for="mimo-cl-t-final">Tempo final (s)</label>`,
    `<input type="number" id="mimo-cl-t-final" class="touch-control id-param-input" min="0.1" step="1" value="10.0" aria-label="Tempo final da simulação MIMO" />`,
    `<label class="mimo-toggle-label"><input type="checkbox" id="mimo-cl-use-decoupler" /> Aplicar Desacoplador W₁(s) em série</label>`,
    `<button type="button" id="btn-mimo-simulate-cl" class="touch-control btn-primary" data-action="mimo-simulate-cl">Simular Malha Fechada (Degrau Canal-a-Canal)</button>`,
    `</div>`,
    `<div id="mimo-cl-summary" class="diagnostics-panel" aria-live="polite"><p>Execute a simulação canal-a-canal para verificar estabilidade, acoplamento cruzado e polos em malha fechada.</p></div>`,
    `<div id="mimo-cl-chart-slot" class="chart-container"></div>`,
    `</div>`,
    `</div>`,
    `</div>`,
    `<div id="mimo-hinf-card" class="subcard mimo-hinf-card">`,
    `<h4>Síntese Robusta ℋ∞ com Planta Generalizada P(s)</h4>`,
    `<div class="mimo-hinf-weights-grid">`,
    `<div class="tool-field"><label for="hinf-ws-dc">Ganho DC de W_S</label><input type="number" id="hinf-ws-dc" class="touch-control id-param-input" min="0.1" step="10" value="100" /></div>`,
    `<div class="tool-field"><label for="hinf-ws-wb">Banda ω_B de W_S (rad/s)</label><input type="number" id="hinf-ws-wb" class="touch-control id-param-input" min="0.001" step="0.1" value="1.0" /></div>`,
    `<div class="tool-field"><label for="hinf-ws-ms">Pico M_S de W_S</label><input type="number" id="hinf-ws-ms" class="touch-control id-param-input" min="0.1" step="0.1" value="2.0" /></div>`,
    `<div class="tool-field"><label for="hinf-wu-gain">Peso de Controle W_U</label><input type="number" id="hinf-wu-gain" class="touch-control id-param-input" min="0.0001" step="0.01" value="0.05" /></div>`,
    `<div class="tool-field"><label for="hinf-wt-wb">Corte ω_T de W_T (rad/s)</label><input type="number" id="hinf-wt-wb" class="touch-control id-param-input" min="0.01" step="1" value="10.0" /></div>`,
    `<div class="tool-field"><label for="hinf-wt-mt">Pico M_T de W_T</label><input type="number" id="hinf-wt-mt" class="touch-control id-param-input" min="0.1" step="0.1" value="1.5" /></div>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-mimo-design-hinf" class="touch-control btn-primary" data-action="mimo-design-hinf">Sintetizar Controlador H∞ (Planta Generalizada P)</button>`,
    `<button type="button" id="btn-mimo-register-hinf" class="touch-control btn-secondary" data-action="mimo-register-hinf" disabled aria-disabled="true">Registrar Controlador K∞ no Workspace</button>`,
    `</div>`,
    `<div id="mimo-hinf-summary" class="diagnostics-panel" aria-live="polite"><p>Configure os filtros W_S, W_U e W_T e sintetize o controlador ótimo/subótimo K∞.</p></div>`,
    `<div id="mimo-hinf-chart-slot" class="chart-container"></div>`,
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

  private readonly decouplerOmegaEl: HTMLInputElement | null;
  private readonly decouplerModeEl: HTMLSelectElement | null;
  private readonly btnRegisterDecouplerEl: HTMLButtonElement | null;
  private readonly decouplerSummaryEl: HTMLElement | null;

  private readonly clGainsEl: HTMLInputElement | null;
  private readonly clUseDecouplerEl: HTMLInputElement | null;
  private readonly clTFinalEl: HTMLInputElement | null;
  private readonly clSummaryEl: HTMLElement | null;
  private readonly clChartSlotEl: HTMLElement | null;

  private readonly hinfWsDcEl: HTMLInputElement | null;
  private readonly hinfWsWbEl: HTMLInputElement | null;
  private readonly hinfWsMsEl: HTMLInputElement | null;
  private readonly hinfWuGainEl: HTMLInputElement | null;
  private readonly hinfWtWbEl: HTMLInputElement | null;
  private readonly hinfWtMtEl: HTMLInputElement | null;
  private readonly btnRegisterHinfEl: HTMLButtonElement | null;
  private readonly hinfSummaryEl: HTMLElement | null;
  private readonly hinfChartSlotEl: HTMLElement | null;

  private readonly visibleGroups = new Set<string>(["G", "S", "T"]);
  private snapshot: MimoAnalysisSnapshot | null = null;
  private decouplerSnapshot: MimoDecouplerSnapshot | null = null;
  private clSnapshot: MimoClosedLoopSnapshot | null = null;
  private hinfSnapshot: MimoHinfSnapshot | null = null;
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

    this.decouplerOmegaEl = this.container.querySelector<HTMLInputElement>("#mimo-decoupler-omega");
    this.decouplerModeEl = this.container.querySelector<HTMLSelectElement>("#mimo-decoupler-mode");
    this.btnRegisterDecouplerEl = this.container.querySelector<HTMLButtonElement>("#btn-mimo-register-decoupler");
    this.decouplerSummaryEl = this.container.querySelector<HTMLElement>("#mimo-decoupler-summary");

    this.clGainsEl = this.container.querySelector<HTMLInputElement>("#mimo-cl-gains");
    this.clUseDecouplerEl = this.container.querySelector<HTMLInputElement>("#mimo-cl-use-decoupler");
    this.clTFinalEl = this.container.querySelector<HTMLInputElement>("#mimo-cl-t-final");
    this.clSummaryEl = this.container.querySelector<HTMLElement>("#mimo-cl-summary");
    this.clChartSlotEl = this.container.querySelector<HTMLElement>("#mimo-cl-chart-slot");

    this.hinfWsDcEl = this.container.querySelector<HTMLInputElement>("#hinf-ws-dc");
    this.hinfWsWbEl = this.container.querySelector<HTMLInputElement>("#hinf-ws-wb");
    this.hinfWsMsEl = this.container.querySelector<HTMLInputElement>("#hinf-ws-ms");
    this.hinfWuGainEl = this.container.querySelector<HTMLInputElement>("#hinf-wu-gain");
    this.hinfWtWbEl = this.container.querySelector<HTMLInputElement>("#hinf-wt-wb");
    this.hinfWtMtEl = this.container.querySelector<HTMLInputElement>("#hinf-wt-mt");
    this.btnRegisterHinfEl = this.container.querySelector<HTMLButtonElement>("#btn-mimo-register-hinf");
    this.hinfSummaryEl = this.container.querySelector<HTMLElement>("#mimo-hinf-summary");
    this.hinfChartSlotEl = this.container.querySelector<HTMLElement>("#mimo-hinf-chart-slot");

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

    this.container
      .querySelector<HTMLElement>('[data-action="mimo-design-decoupler"]')
      ?.addEventListener("click", () => {
        void this.runDesignDecoupler();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="mimo-register-decoupler"]')
      ?.addEventListener("click", () => {
        void this.registerDecoupledPlant();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="mimo-simulate-cl"]')
      ?.addEventListener("click", () => {
        void this.runSimulateClosedLoop();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="mimo-design-hinf"]')
      ?.addEventListener("click", () => {
        void this.runDesignHinf();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="mimo-register-hinf"]')
      ?.addEventListener("click", () => {
        void this.registerHinfController();
      });
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

  public async runDesignDecoupler(): Promise<void> {
    try {
      const typed = this.shell.getTypedWorkspace();
      const eff = typed.getEffectiveSelection("frequencyPlant");
      if (!eff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Selecione uma planta MIMO antes de projetar o desacoplador SVD.",
        );
      }

      const omegaTarget = Number(this.decouplerOmegaEl?.value ?? 1.0);
      if (!Number.isFinite(omegaTarget) || omegaTarget <= 0) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Frequência alvo ω₀ deve ser finita e > 0.",
        );
      }
      const mode: "static" | "first_order" =
        this.decouplerModeEl?.value === "first_order" ? "first_order" : "static";

      const params = { omega_target: omegaTarget, realization_mode: mode };
      const plan = await typed.prepareToolExecution("mimo.design_decoupler", params, {
        extraPayload: params,
      });
      const resp = await this.executeRpc("mimo.design_decoupler", plan.extraPayload);
      if (resp.status === "failure" || !resp.result) {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao projetar desacoplador SVD.",
        );
      }

      const res = resp.result as Record<string, unknown>;
      this.decouplerSnapshot = {
        omegaTarget: typeof res.omega_target === "number" ? res.omega_target : omegaTarget,
        realizationMode: res.realization_mode === "first_order" ? "first_order" : "static",
        kappaBefore: typeof res.kappa_before === "number" ? res.kappa_before : null,
        kappaAfter: typeof res.kappa_after === "number" ? res.kappa_after : null,
        rgaOffdiagBefore:
          typeof res.rga_offdiag_norm_before === "number" ? res.rga_offdiag_norm_before : null,
        rgaOffdiagAfter:
          typeof res.rga_offdiag_norm_after === "number" ? res.rga_offdiag_norm_after : null,
        rgaAfterMatrix: extractReal2DMatrix(res.rga_after),
        decoupler: isPlainObject(res.decoupler) ? (res.decoupler as Record<string, unknown>) : null,
        decoupledPlant: isPlainObject(res.decoupled_plant)
          ? (res.decoupled_plant as Record<string, unknown>)
          : null,
      };

      if (this.clUseDecouplerEl && this.decouplerSnapshot.decoupler) {
        this.clUseDecouplerEl.checked = true;
      }

      this.shell
        .getAnnouncer()
        .announce("Desacoplador SVD projetado com sucesso.", "polite", "status");
      this.render();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async registerDecoupledPlant(): Promise<void> {
    if (!this.decouplerSnapshot?.decoupledPlant) return;
    try {
      const reg = await this.shell
        .getTypedWorkspace()
        .registerTypedObject(this.decouplerSnapshot.decoupledPlant, { source: "manual" });
      this.shell
        .getAnnouncer()
        .announce(
          `Planta desacoplada (${reg.id} #r${reg.revision}) registrada no Workspace.`,
          "polite",
          "status",
        );
      this.render();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async runSimulateClosedLoop(): Promise<void> {
    try {
      const typed = this.shell.getTypedWorkspace();
      const eff = typed.getEffectiveSelection("frequencyPlant");
      if (!eff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Selecione uma planta MIMO antes de simular a malha fechada.",
        );
      }

      const rawGainsText = String(this.clGainsEl?.value ?? "1.0, 1.0").trim();
      const parsedGains = rawGainsText
        .split(/[\s,;]+/)
        .filter((tok) => tok.length > 0)
        .map((tok) => Number(tok));
      if (parsedGains.length === 0 || parsedGains.some((g) => !Number.isFinite(g))) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Ganhos diagonais K_diag inválidos. Informe números separados por vírgula (ex: 1.0, 1.0).",
        );
      }

      const tFinal = Number(this.clTFinalEl?.value ?? 10.0);
      if (!Number.isFinite(tFinal) || tFinal <= 0) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", "Tempo final deve ser finito e > 0.");
      }

      const feedbackSign: "negative" | "positive" =
        this.feedbackSignEl?.value === "positive" ? "positive" : "negative";
      const useDecoupler = Boolean(this.clUseDecouplerEl?.checked && this.decouplerSnapshot?.decoupler);

      const params: Record<string, unknown> = {
        controller_gains: parsedGains,
        feedback_sign: feedbackSign,
        t_final: tFinal,
        n_points: 160,
      };
      if (useDecoupler && this.decouplerSnapshot?.decoupler) {
        params.decoupler = this.decouplerSnapshot.decoupler;
      }

      const plan = await typed.prepareToolExecution("mimo.simulate_closed_loop", params, {
        extraPayload: params,
      });
      const resp = await this.executeRpc("mimo.simulate_closed_loop", plan.extraPayload);
      if (resp.status === "failure" || !resp.result) {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao simular malha fechada MIMO.",
        );
      }

      const res = resp.result as Record<string, unknown>;
      const tVec = extractNumericVector(res.t);
      const { matrix, outputNames } = extractStepResponseMatrix(res.step_responses, tVec.length);
      const poles = extractComplexPoles(res.closed_loop_poles);
      const isStable = Boolean(res.is_stable);
      const maxCrossCoupling =
        typeof res.max_cross_coupling === "number" ? res.max_cross_coupling : null;

      const timeModel = buildTimeResponseChartModel({
        chart_id: "mimo-closed-loop-step",
        title: useDecoupler
          ? "Resposta ao Degrau MIMO (Com Desacoplador)"
          : "Resposta ao Degrau MIMO (Controle Descentralizado)",
        dt: null,
        t: tVec,
        y: matrix,
        output_names: outputNames,
        units: {
          time: "s",
          outputs: outputNames.map(() => "1"),
        },
        model_revision: eff.ref.revision,
        project_revision: this.shell.getLqrWorkspace().getProjectRevision(),
        provenance: resp.provenance as Provenance,
        series_semantics: "numeric_verified",
        feedback_sign: feedbackSign,
        theme_mode: this.shell.getThemeMode(),
      });

      this.clSnapshot = {
        isStable,
        maxCrossCoupling,
        poles,
        timeModel,
      };

      this.shell
        .getAnnouncer()
        .announce("Simulação em malha fechada MIMO concluída.", "polite", "status");
      this.render();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async runDesignHinf(): Promise<void> {
    try {
      const typed = this.shell.getTypedWorkspace();
      const eff = typed.getEffectiveSelection("frequencyPlant");
      if (!eff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Selecione uma planta MIMO contínua antes de sintetizar o controlador H∞.",
        );
      }

      const wsDc = Number(this.hinfWsDcEl?.value ?? 100);
      const wsWb = Number(this.hinfWsWbEl?.value ?? 1.0);
      const wsMs = Number(this.hinfWsMsEl?.value ?? 2.0);
      const wuGain = Number(this.hinfWuGainEl?.value ?? 0.05);
      const wtWb = Number(this.hinfWtWbEl?.value ?? 10.0);
      const wtMt = Number(this.hinfWtMtEl?.value ?? 1.5);

      if (
        !Number.isFinite(wsDc) ||
        wsDc <= 0 ||
        !Number.isFinite(wsWb) ||
        wsWb <= 0 ||
        !Number.isFinite(wsMs) ||
        wsMs <= 0 ||
        !Number.isFinite(wuGain) ||
        wuGain <= 0 ||
        !Number.isFinite(wtWb) ||
        wtWb <= 0 ||
        !Number.isFinite(wtMt) ||
        wtMt <= 0
      ) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Todos os parâmetros dos filtros W_S, W_U e W_T devem ser finitos e > 0.",
        );
      }

      const params = {
        w_s: { dc_gain: wsDc, wb: wsWb, m_s: wsMs },
        w_u: { gain: wuGain },
        w_t: { wt: wtWb, m_t: wtMt },
        n_points: 120,
      };
      const plan = await typed.prepareToolExecution("mimo.design_hinf", params, {
        extraPayload: params,
      });
      const resp = await this.executeRpc("mimo.design_hinf", plan.extraPayload);
      if (resp.status === "failure" || !resp.result) {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha na síntese H∞.",
        );
      }

      const res = resp.result as Record<string, unknown>;
      const omegaVec = extractNumericVector(res.omega);
      const sigmaS = toDbArray(extractNumericVector(res.sigma_S));
      const sigmaT = toDbArray(extractNumericVector(res.sigma_T));
      const invWs = toDbArray(extractNumericVector(res.inv_ws_bound));
      const invWt = toDbArray(extractNumericVector(res.inv_wt_bound));

      const curves: SingularValueCurve[] = [];
      if (sigmaS.length > 0) {
        curves.push({
          id: "hinf_sigma_S",
          label: "σ̄(S)",
          group: "S",
          omega: omegaVec,
          values_db: sigmaS,
          stroke_dasharray: "",
        });
      }
      if (sigmaT.length > 0) {
        curves.push({
          id: "hinf_sigma_T",
          label: "σ̄(T)",
          group: "T",
          omega: omegaVec,
          values_db: sigmaT,
          stroke_dasharray: "6 3",
        });
      }
      if (invWs.length > 0) {
        curves.push({
          id: "hinf_inv_ws",
          label: "1/|W_S|",
          group: "S",
          omega: omegaVec,
          values_db: invWs,
          stroke_dasharray: "2 2",
        });
      }
      if (invWt.length > 0) {
        curves.push({
          id: "hinf_inv_wt",
          label: "1/|W_T|",
          group: "T",
          omega: omegaVec,
          values_db: invWt,
          stroke_dasharray: "8 3 2 3",
        });
      }

      const svModel = buildSingularValuesChartModel({
        chart_id: "mimo-hinf-mixed-sensitivity",
        title: "Sensibilidade Mista H∞: σ̄(S), σ̄(T) vs 1/|W_S|, 1/|W_T|",
        dt: null,
        omega: omegaVec,
        curves,
        model_revision: eff.ref.revision,
        project_revision: this.shell.getLqrWorkspace().getProjectRevision(),
        provenance: resp.provenance as Provenance,
        theme_mode: this.shell.getThemeMode(),
      });

      const rawGp = isPlainObject(res.generalized_plant_summary)
        ? (res.generalized_plant_summary as Record<string, unknown>)
        : null;

      this.hinfSnapshot = {
        gammaAchieved: typeof res.gamma_achieved === "number" ? res.gamma_achieved : null,
        hinfNormGrid: typeof res.hinf_norm_grid === "number" ? res.hinf_norm_grid : null,
        isStable: Boolean(res.is_stable),
        gpSummary: rawGp
          ? {
              n_states: Number(rawGp.n_states ?? 0),
              n_w: Number(rawGp.n_w ?? 0),
              n_u: Number(rawGp.n_u ?? 0),
              n_z: Number(rawGp.n_z ?? 0),
              n_y: Number(rawGp.n_y ?? 0),
            }
          : null,
        svModel,
        controller: isPlainObject(res.controller)
          ? (res.controller as Record<string, unknown>)
          : null,
      };

      this.shell
        .getAnnouncer()
        .announce("Síntese robusta H∞ concluída.", "polite", "status");
      this.render();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async registerHinfController(): Promise<void> {
    if (!this.hinfSnapshot?.controller) return;
    try {
      const reg = await this.shell
        .getTypedWorkspace()
        .registerTypedObject(this.hinfSnapshot.controller, { source: "manual" });
      this.shell
        .getAnnouncer()
        .announce(
          `Controlador K∞ (${reg.id} #r${reg.revision}) registrado no Workspace.`,
          "polite",
          "status",
        );
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
    this.renderDecouplerSection();
    this.renderClosedLoopSection();
    this.renderHinfSection();
  }

  private renderDecouplerSection(): void {
    const decimals = this.shell.getDisplayDecimals();
    const hasDec = Boolean(this.decouplerSnapshot?.decoupledPlant);
    if (this.btnRegisterDecouplerEl) {
      this.btnRegisterDecouplerEl.disabled = !hasDec;
      if (hasDec) this.btnRegisterDecouplerEl.removeAttribute("aria-disabled");
      else this.btnRegisterDecouplerEl.setAttribute("aria-disabled", "true");
    }
    if (!this.decouplerSummaryEl) return;
    const d = this.decouplerSnapshot;
    if (!d) {
      this.decouplerSummaryEl.innerHTML = `<p>Projete o desacoplador SVD para comparar κ(G), norma off-diagonal e RGA pós-desacoplamento.</p>`;
      return;
    }

    const kBefore = d.kappaBefore !== null ? formatNumericDisplay(d.kappaBefore, decimals) : "N/D";
    const kAfter = d.kappaAfter !== null ? formatNumericDisplay(d.kappaAfter, decimals) : "N/D";
    const offBefore =
      d.rgaOffdiagBefore !== null ? formatNumericDisplay(d.rgaOffdiagBefore, decimals) : "N/D";
    const offAfter =
      d.rgaOffdiagAfter !== null ? formatNumericDisplay(d.rgaOffdiagAfter, decimals) : "N/D";

    let rgaTableHtml = "";
    if (d.rgaAfterMatrix && d.rgaAfterMatrix.length > 0) {
      const m = d.rgaAfterMatrix[0]?.length ?? 0;
      const headerCols = Array.from({ length: m }, (_, j) => `<th scope="col">u${j + 1}</th>`).join("");
      const bodyRows = d.rgaAfterMatrix
        .map((row, i) => {
          const cells = row
            .map((val) => {
              const alpha = Math.min(0.65, Math.max(0.08, Math.min(1.5, Math.abs(val)) * 0.42));
              const bgTint =
                val >= 0
                  ? `rgba(29, 78, 216, ${alpha.toFixed(2)})`
                  : `rgba(180, 83, 9, ${alpha.toFixed(2)})`;
              return `<td class="rga-cell" style="background:${bgTint}"><strong>${escapeHtml(formatNumericDisplay(val, decimals))}</strong></td>`;
            })
            .join("");
          return `<tr><th scope="row">y${i + 1}</th>${cells}</tr>`;
        })
        .join("");
      rgaTableHtml = [
        `<table class="accessible-data-table mimo-rga-table" aria-label="RGA pós-desacoplamento">`,
        `<thead><tr><th scope="col">Saída \\ Entrada</th>${headerCols}</tr></thead>`,
        `<tbody>${bodyRows}</tbody>`,
        `</table>`,
      ].join("");
    }

    this.decouplerSummaryEl.innerHTML = [
      `<p><strong>Modo:</strong> <code>${escapeHtml(d.realizationMode)}</code> em ω₀ = <code>${formatNumericDisplay(d.omegaTarget, decimals)}</code> rad/s</p>`,
      `<p><strong>Condicionamento κ(G):</strong> <code>${escapeHtml(kBefore)}</code> → <code>${escapeHtml(kAfter)}</code> | <strong>||Λ − I|| (off-diagonal):</strong> <code>${escapeHtml(offBefore)}</code> → <code>${escapeHtml(offAfter)}</code></p>`,
      rgaTableHtml,
    ].join("");
  }

  private renderClosedLoopSection(): void {
    const decimals = this.shell.getDisplayDecimals();
    if (!this.clSnapshot) {
      if (this.clSummaryEl) {
        this.clSummaryEl.innerHTML = `<p>Execute a simulação canal-a-canal para verificar estabilidade, acoplamento cruzado e polos em malha fechada.</p>`;
      }
      if (this.clChartSlotEl) this.clChartSlotEl.innerHTML = "";
      return;
    }

    const cl = this.clSnapshot;
    if (this.clSummaryEl) {
      const badge = cl.isStable
        ? `<span class="badge badge-stable">Estável ✓</span>`
        : `<span class="badge badge-experimental">Instável ⚠</span>`;
      const ccStr =
        cl.maxCrossCoupling !== null
          ? formatNumericDisplay(cl.maxCrossCoupling, decimals)
          : "N/D";
      const polesStr =
        cl.poles.length > 0
          ? cl.poles
              .slice(0, 8)
              .map((p) =>
                Math.abs(p.im) > 1e-6
                  ? `${formatNumericDisplay(p.re, decimals)} ${p.im >= 0 ? "+" : "−"} j${formatNumericDisplay(Math.abs(p.im), decimals)}`
                  : formatNumericDisplay(p.re, decimals),
              )
              .join(", ")
          : "N/D";
      this.clSummaryEl.innerHTML = [
        `<p>${badge} <strong>Acoplamento cruzado máximo:</strong> <code>${escapeHtml(ccStr)}</code></p>`,
        `<p><strong>Polos de malha fechada:</strong> <code>${escapeHtml(polesStr)}</code></p>`,
      ].join("");
    }

    if (this.clChartSlotEl) {
      const themeMode = this.shell.getThemeMode();
      const model: TimeResponseChartModel = {
        ...cl.timeModel,
        theme_mode: themeMode,
      };
      this.clChartSlotEl.innerHTML = renderTimeResponseSvg(model, {
        decimals,
        themeMode,
      });
    }
  }

  private renderHinfSection(): void {
    const decimals = this.shell.getDisplayDecimals();
    const hasCtrl = Boolean(this.hinfSnapshot?.controller);
    if (this.btnRegisterHinfEl) {
      this.btnRegisterHinfEl.disabled = !hasCtrl;
      if (hasCtrl) this.btnRegisterHinfEl.removeAttribute("aria-disabled");
      else this.btnRegisterHinfEl.setAttribute("aria-disabled", "true");
    }

    if (!this.hinfSnapshot) {
      if (this.hinfSummaryEl) {
        this.hinfSummaryEl.innerHTML = `<p>Configure os filtros W_S, W_U e W_T e sintetize o controlador ótimo/subótimo K∞.</p>`;
      }
      if (this.hinfChartSlotEl) this.hinfChartSlotEl.innerHTML = "";
      return;
    }

    const h = this.hinfSnapshot;
    if (this.hinfSummaryEl) {
      const badge = h.isStable
        ? `<span class="badge badge-stable">Estável ✓</span>`
        : `<span class="badge badge-experimental">Instável ⚠</span>`;
      const gammaStr =
        h.gammaAchieved !== null ? formatNumericDisplay(h.gammaAchieved, decimals) : "N/D";
      const normStr =
        h.hinfNormGrid !== null ? formatNumericDisplay(h.hinfNormGrid, decimals) : "N/D";
      const gpStr = h.gpSummary
        ? `n_states=${h.gpSummary.n_states}, n_w=${h.gpSummary.n_w}, n_u=${h.gpSummary.n_u}, n_z=${h.gpSummary.n_z}, n_y=${h.gpSummary.n_y}`
        : "N/D";
      this.hinfSummaryEl.innerHTML = [
        `<p>${badge} <strong>γ atingido:</strong> <code>${escapeHtml(gammaStr)}</code> | <strong>||T_zw||∞ (grade):</strong> <code>${escapeHtml(normStr)}</code></p>`,
        `<p><strong>Planta Generalizada P(s):</strong> <code>${escapeHtml(gpStr)}</code></p>`,
      ].join("");
    }

    if (this.hinfChartSlotEl) {
      const themeMode = this.shell.getThemeMode();
      const model: SingularValuesChartModel = {
        ...h.svModel,
        theme_mode: themeMode,
      };
      this.hinfChartSlotEl.innerHTML = renderSingularValuesSvg(model, {
        decimals,
        themeMode,
      });
    }
  }
}
