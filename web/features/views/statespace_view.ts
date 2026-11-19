/**
 * Bancada da Aba 3 — Espaço de Estados & Síntese LQR
 * seguindo CL-UX-DIR-001 v1.0.0 Seção 4.3 (`WP-UX-REFACTOR-02-IDENT-SISO-LQR`).
 *
 * Responsabilidades estritas de UI/Apresentação (F8):
 * - Cartões de KPIs (`#lqr-kpi-cards`: Ganho Ótimo K, Polos A ± BK, Custo Ótimo J*) e
 *   badges estruturais PBH (`#lqr-pbh-badges`: Controlável, Observável, CARE/DARE).
 * - Barra interativa LQR (`#lqr-q-slider` Fast-Preview 60 FPS -> commit autoritativo R-23).
 * - Editor matricial interativo com abas de filtro (`Todas | Planta (A,B,C,D) | Pesos (Q,R,x0)`)
 *   mantendo todas as células no DOM, além de presets clássicos e modal JSON documentado
 *   (`#btn-open-lqr-json-modal` / `#lqr-json-modal`).
 * - Preservação de `#lqr-json-advanced` e `#pvm-export-options` para compatibilidade total E2E/F9.
 *
 * 100% compatível com erasableSyntaxOnly, verbatimModuleSyntax e FakeElement/FakeDocument.
 */

import { ControlLabBridgeError, type RealTensor } from "../../bridge/protocol.ts";
import {
  escapeHtml,
  formatMatrixDisplay,
  formatNumericDisplay,
  getSliderAriaAttributes,
  type AccessibleSliderConfig,
} from "../../app/accessibility.ts";
import { DEFAULT_DYNAMIC_EXPORT_CONTROLLER, type ControlLabShell } from "../../app/shell.ts";
import type { CanonicalStateSpaceModel } from "../lqr_workspace.ts";

export interface LqrPresetSpec {
  id: string;
  label: string;
  n: number;
  m: number;
  p: number;
  dt: number | null;
  A: number[];
  B: number[];
  C: number[];
  D: number[];
  Q: number[];
  R: number[];
  x0: number[];
}

export const LQR_PRESETS: Record<string, LqrPresetSpec> = {
  double_integrator: {
    id: "double_integrator",
    label: "Integrador Duplo (2x1)",
    n: 2,
    m: 1,
    p: 1,
    dt: null,
    A: [0, 1, 0, 0],
    B: [0, 1],
    C: [1, 0],
    D: [0],
    Q: [1, 0, 0, 1],
    R: [1],
    x0: [1, 0],
  },
  mass_spring_damper: {
    id: "mass_spring_damper",
    label: "Massa-Mola-Amortecedor (2x1)",
    n: 2,
    m: 1,
    p: 1,
    dt: null,
    A: [0, 1, -2, -0.5],
    B: [0, 1],
    C: [1, 0],
    D: [0],
    Q: [4, 0, 0, 1],
    R: [1],
    x0: [1, 0],
  },
  three_state_mimo: {
    id: "three_state_mimo",
    label: "Sistema 3 estados (3x2)",
    n: 3,
    m: 2,
    p: 2,
    dt: null,
    A: [-1, 0.5, 0, 0, -2, 1, 0, 0, -0.5],
    B: [1, 0, 0, 1, 1, 1],
    C: [1, 0, 0, 0, 1, 0],
    D: [0, 0, 0, 0],
    Q: [1, 0, 0, 0, 1, 0, 0, 0, 1],
    R: [1, 0, 0, 1],
    x0: [1, 0, 0],
  },
};

export interface StatespaceExportModalRequest {
  title: string;
  filename: string;
  mimeType: string;
  content: string;
  bytes?: Uint8Array;
  offlineDesign?: boolean;
  projectRevision?: number;
  projectId?: string;
  requestId?: string;
  configurationRevision?: number;
  pvmControllerKind?: "lqr" | "dynamic";
}

export interface StatespaceViewOptions {
  shell: ControlLabShell;
  container: HTMLElement;
  onOpenExportModal: (payload: StatespaceExportModalRequest, trigger: HTMLElement | null) => void;
}

export type MatrixFilterMode = "all" | "plant" | "weights";

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function toggleElCssClass(
  el: Element | null | undefined,
  className: string,
  active: boolean,
): void {
  if (!el) return;
  const current = (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean);
  const has = current.includes(className);
  if (active && !has) {
    current.push(className);
    el.setAttribute("class", current.join(" "));
  } else if (!active && has) {
    el.setAttribute(
      "class",
      current.filter((c) => c !== className).join(" "),
    );
  }
}

function makeFloat64Tensor(shape: number[], data: number[]): RealTensor {
  return { shape, dtype: "float64", order: "C", data };
}

function isNumberMatrix2D(val: unknown): val is number[][] {
  return (
    Array.isArray(val) &&
    val.length > 0 &&
    val.every(
      (row) =>
        Array.isArray(row) &&
        row.length === (val[0] as unknown[]).length &&
        row.every((item) => typeof item === "number" && Number.isFinite(item)),
    )
  );
}

function matrix2DToTensor(mat: number[][]): RealTensor {
  const rows = mat.length;
  const cols = mat[0]?.length ?? 0;
  return makeFloat64Tensor([rows, cols], mat.flat());
}

export function normalizePlantJsonInput(
  raw: unknown,
  currentPlant: CanonicalStateSpaceModel,
): CanonicalStateSpaceModel {
  if (
    raw &&
    typeof raw === "object" &&
    !("matrices" in raw) &&
    "A" in raw &&
    "B" in raw &&
    "C" in raw &&
    "D" in raw
  ) {
    const obj = raw as Record<string, unknown>;
    if (
      isNumberMatrix2D(obj.A) &&
      isNumberMatrix2D(obj.B) &&
      isNumberMatrix2D(obj.C) &&
      isNumberMatrix2D(obj.D)
    ) {
      const n = obj.A.length;
      const m = obj.B[0]?.length ?? 1;
      const p = obj.C.length;
      const dt = obj.dt === undefined ? currentPlant.dt : (obj.dt as number | null);
      return {
        schema_version: "1.0.0",
        id: typeof obj.id === "string" && obj.id.trim() ? obj.id : currentPlant.id,
        revision: currentPlant.revision + 1,
        kind: "StateSpace",
        dt,
        state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
        input_names: Array.from({ length: m }, (_, i) => `u${i + 1}`),
        output_names: Array.from({ length: p }, (_, i) => `y${i + 1}`),
        matrices: {
          A: matrix2DToTensor(obj.A),
          B: matrix2DToTensor(obj.B),
          C: matrix2DToTensor(obj.C),
          D: matrix2DToTensor(obj.D),
        },
        units: {
          time: currentPlant.units.time,
          states: Array.from({ length: n }, () => ""),
          inputs: Array.from({ length: m }, () => ""),
          outputs: Array.from({ length: p }, () => ""),
        },
        provenance: { source: "ui_json_simple" },
      };
    }
  }
  return raw as CanonicalStateSpaceModel;
}

export function normalizeWeightsJsonInput(
  raw: unknown,
): { Q?: RealTensor; R?: RealTensor; x0?: RealTensor; feedbackSign?: "negative" | "positive" } {
  if (!raw || typeof raw !== "object") {
    return raw as { Q?: RealTensor; R?: RealTensor; x0?: RealTensor };
  }
  const obj = raw as Record<string, unknown>;
  const out: {
    Q?: RealTensor;
    R?: RealTensor;
    x0?: RealTensor;
    feedbackSign?: "negative" | "positive";
  } = {};
  if (obj.Q !== undefined) {
    out.Q = isNumberMatrix2D(obj.Q) ? matrix2DToTensor(obj.Q) : (obj.Q as RealTensor);
  }
  if (obj.R !== undefined) {
    out.R = isNumberMatrix2D(obj.R) ? matrix2DToTensor(obj.R) : (obj.R as RealTensor);
  }
  if (obj.x0 !== undefined) {
    if (
      Array.isArray(obj.x0) &&
      obj.x0.length > 0 &&
      obj.x0.every((v) => typeof v === "number" && Number.isFinite(v))
    ) {
      out.x0 = makeFloat64Tensor([obj.x0.length, 1], [...obj.x0]);
    } else if (isNumberMatrix2D(obj.x0)) {
      out.x0 = matrix2DToTensor(obj.x0);
    } else {
      out.x0 = obj.x0 as RealTensor;
    }
  }
  if (obj.feedbackSign === "positive" || obj.feedbackSign === "negative") {
    out.feedbackSign = obj.feedbackSign;
  }
  return out;
}

function renderMatrixGridBlockHtml(
  matrixName: "A" | "B" | "C" | "D" | "Q" | "R" | "x0",
  title: string,
  rows: number,
  cols: number,
  data: number[],
): string {
  const cells: string[] = [];
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const idx = r * cols + c;
      const val = Number.isFinite(data[idx]) ? data[idx] : 0;
      cells.push(
        `<input type="number" step="any" class="lqr-matrix-cell" data-matrix="${matrixName}" data-row="${r}" data-col="${c}" value="${escapeHtml(String(val))}" aria-label="${escapeHtml(matrixName)}[${r}][${c}]" />`,
      );
    }
  }
  return [
    `<div class="lqr-matrix-block" data-matrix-block="${matrixName}">`,
    `<h5>${escapeHtml(title)} (${rows}×${cols})</h5>`,
    `<div class="lqr-matrix-grid" style="grid-template-columns: repeat(${cols}, minmax(56px, 1fr));">${cells.join("")}</div>`,
    `</div>`,
  ].join("");
}

export function renderStatespaceJsonModalHtml(): string {
  return [
    `<section id="lqr-json-modal" class="modal-dialog lqr-json-modal" role="dialog" aria-modal="true" aria-labelledby="lqr-json-modal-title" hidden>`,
    `<div class="modal-header">`,
    `<h2 id="lqr-json-modal-title">Importar / Editar Planta &amp; Pesos via JSON</h2>`,
    `<button type="button" id="lqr-json-modal-close" class="touch-control btn-secondary btn-small" data-action="close-lqr-json-modal">Fechar</button>`,
    `</div>`,
    `<div id="lqr-json-modal-error" class="field-error" role="alert" hidden></div>`,
    `<div class="tool-field">`,
    `<label for="lqr-modal-plant-json">Planta StateSpace (JSON)</label>`,
    `<textarea id="lqr-modal-plant-json" class="touch-control" rows="4" aria-label="Planta StateSpace JSON no modal"></textarea>`,
    `<p class="json-format-hint">Formato simplificado ou canônico: <code>{"A": [[0,1],[0,0]], "B": [[0],[1]], "C": [[1,0]], "D": [[0]], "dt": null}</code></p>`,
    `<div class="panel-actions"><button type="button" id="btn-lqr-modal-apply-plant" class="touch-control btn-primary btn-small" data-action="lqr-modal-apply-plant">Aplicar Planta JSON</button></div>`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="lqr-modal-weights-json">Pesos LQR Q / R / x0 (JSON)</label>`,
    `<textarea id="lqr-modal-weights-json" class="touch-control" rows="3" aria-label="Pesos Q R x0 JSON no modal"></textarea>`,
    `<p class="json-format-hint">Formato esperado: <code>{"Q": [[4,0],[0,5]], "R": [[1]], "x0": [1,0]}</code></p>`,
    `<div class="panel-actions"><button type="button" id="btn-lqr-modal-apply-weights" class="touch-control btn-primary btn-small" data-action="lqr-modal-apply-weights">Aplicar Pesos JSON</button></div>`,
    `</div>`,
    `</section>`,
  ].join("\n");
}

export function renderStatespaceViewHtml(initialDims: { n: number; m: number; p: number }): string {
  const presetOptionsHtml = Object.values(LQR_PRESETS)
    .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`)
    .join("");

  return [
    `<section id="statespace-workspace-panel" aria-label="Espaço de Estados / LQR (Aba 3)">`,
    `<div id="lqr-kpi-cards" class="lqr-kpi-cards" role="region" aria-label="Indicadores LQR"></div>`,
    `<div id="lqr-pbh-badges" class="lqr-pbh-badges" role="region" aria-label="Diagnóstico estrutural PBH e método Riccati"></div>`,
    `<div class="lqr-interactive-bar lqr-action-card subcard">`,
    `<div class="lqr-status-row"><p>Status: <strong id="lqr-status-text"></strong></p></div>`,
    `<div id="lqr-q-slider" class="touch-control lqr-slider" data-action="lqr-slider"></div>`,
    `<div class="tool-field">`,
    `<label for="lqr-feedback-sign">Convenção de realimentação</label>`,
    `<select id="lqr-feedback-sign" class="touch-control" data-action="feedback-sign">`,
    `<option value="negative">Negativa: u = u_ff - Kx (A - BK)</option>`,
    `<option value="positive">Positiva: u = u_ff + Kx (A + BK)</option>`,
    `</select>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" class="touch-control btn-primary" data-action="commit-lqr">Calcular LQR Autoritativo</button>`,
    `<button type="button" class="touch-control btn-secondary" data-action="analyze-open-loop">Analisar Malha Aberta (PBH)</button>`,
    `<button type="button" class="touch-control btn-danger" data-action="cancel-lqr">Cancelar</button>`,
    `<button type="button" class="touch-control btn-secondary" data-action="undo-lqr">Desfazer</button>`,
    `<button type="button" id="btn-reset-worker" class="touch-control btn-secondary" data-action="reset-worker">Reiniciar Worker</button>`,
    `<button type="button" id="btn-save-experiment" class="touch-control btn-secondary" data-action="save-experiment">Salvar no Comparador</button>`,
    `</div>`,
    `</div>`,
    `<section class="lqr-export-card subcard" aria-label="Exportações e Persistência de Projeto">`,
    `<h4>Exportações &amp; Persistência de Projeto</h4>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-export-pvm" class="touch-control btn-secondary" data-action="export-pvm">Exportar .pvm</button>`,
    `<label for="ctrlab-file-input" class="compact-label">Abrir .ctrlab</label><input id="ctrlab-file-input" type="file" accept=".ctrlab,application/zip" class="touch-control" aria-label="Abrir projeto .ctrlab" />`,
    `<button type="button" id="btn-export-ctrlab" class="touch-control btn-secondary" data-action="export-ctrlab">Exportar .ctrlab</button>`,
    `<button type="button" id="btn-export-gains" class="touch-control btn-secondary" data-action="export-gains">Exportar Ganhos JSON</button>`,
    `<button type="button" id="btn-export-csv" class="touch-control btn-secondary" data-action="export-csv">Exportar CSV</button>`,
    `<button type="button" id="btn-build-report" class="touch-control btn-secondary" data-action="build-report">Relatório Científico (R-27)</button>`,
    `</div>`,
    `<details id="pvm-export-options"><summary>Configuração da simulação PathView</summary>`,
    `<div class="tool-field"><label for="pvm-controller-kind">Controlador exportado</label>`,
    `<select id="pvm-controller-kind" class="touch-control"><option value="lqr">LQR confirmado</option><option value="dynamic">Controlador dinâmico (JSON)</option></select></div>`,
    `<div class="tool-field"><label for="pvm-dynamic-controller-json">DynamicController canônico</label>`,
    `<textarea id="pvm-dynamic-controller-json" rows="12" disabled aria-describedby="pvm-controller-help"></textarea>`,
    `<p id="pvm-controller-help">Dimensões e boa-postura do controlador dinâmico são verificadas pelo motor Python antes do download. O estado inicial próprio deve constar de initial_state no JSON.</p></div>`,
    `<label for="pvm-saturation-enabled"><input id="pvm-saturation-enabled" type="checkbox" /> Saturação do atuador após o controlador</label>`,
    `<div class="tool-field"><label for="pvm-u-min">Limite inferior u_min (número ou vetor JSON)</label><input id="pvm-u-min" type="text" value="-1" disabled /></div>`,
    `<div class="tool-field"><label for="pvm-u-max">Limite superior u_max (número ou vetor JSON)</label><input id="pvm-u-max" type="text" value="1" disabled /></div>`,
    `</details>`,
    `</section>`,
    `<section id="lqr-matrix-editor" class="lqr-matrix-editor subcard" aria-label="Editor Matricial Interativo LQR">`,
    `<div class="lqr-matrix-editor-header">`,
    `<h3>Editor Matricial Interativo (Planta StateSpace &amp; Pesos LQR)</h3>`,
    `<button type="button" id="btn-open-lqr-json-modal" class="touch-control btn-secondary btn-small" data-action="open-lqr-json-modal">JSON…</button>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<label for="lqr-preset-select">Preset clássico:</label>`,
    `<select id="lqr-preset-select" class="touch-control" aria-label="Preset clássico StateSpace">${presetOptionsHtml}</select>`,
    `<button type="button" id="btn-lqr-apply-preset" class="touch-control btn-secondary" data-action="lqr-apply-preset">Aplicar Preset</button>`,
    `</div>`,
    `<div class="lqr-matrix-dims">`,
    `<div class="tool-field"><label for="lqr-dim-n">Estados n (1–6)</label><input id="lqr-dim-n" type="number" min="1" max="6" step="1" class="touch-control" value="${initialDims.n}" aria-label="Dimensão n de estados" /></div>`,
    `<div class="tool-field"><label for="lqr-dim-m">Entradas m (1–4)</label><input id="lqr-dim-m" type="number" min="1" max="4" step="1" class="touch-control" value="${initialDims.m}" aria-label="Dimensão m de entradas" /></div>`,
    `<div class="tool-field"><label for="lqr-dim-p">Saídas p (1–4)</label><input id="lqr-dim-p" type="number" min="1" max="4" step="1" class="touch-control" value="${initialDims.p}" aria-label="Dimensão p de saídas" /></div>`,
    `<div class="tool-field"><label for="lqr-dim-dt">dt (vazio = contínuo)</label><input id="lqr-dim-dt" type="number" min="0" step="any" placeholder="contínuo" class="touch-control" aria-label="Passo de amostragem dt" /></div>`,
    `</div>`,
    `<div class="lqr-matrix-filter-bar" role="group" aria-label="Filtro do editor matricial">`,
    `<button type="button" id="btn-lqr-filter-all" class="touch-control btn-primary btn-small" data-matrix-filter="all" aria-pressed="true">Todas</button>`,
    `<button type="button" id="btn-lqr-filter-plant" class="touch-control btn-secondary btn-small" data-matrix-filter="plant" aria-pressed="false">Planta (A,B,C,D)</button>`,
    `<button type="button" id="btn-lqr-filter-weights" class="touch-control btn-secondary btn-small" data-matrix-filter="weights" aria-pressed="false">Pesos (Q,R,x0)</button>`,
    `</div>`,
    `<div id="lqr-matrix-grids" class="lqr-matrix-grids"></div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-lqr-apply-matrices" class="touch-control btn-primary" data-action="lqr-apply-matrices">Aplicar Matrizes ao Workspace</button>`,
    `</div>`,
    `</section>`,
    `<div id="lqr-json-advanced" class="lqr-json-advanced subcard">`,
    `<h4>Entrada Avançada via JSON</h4>`,
    `<div class="tool-field">`,
    `<label for="lqr-plant-json">Planta StateSpace (JSON)</label>`,
    `<input id="lqr-plant-json" class="touch-control" type="text" data-field="plant-json" aria-label="Planta StateSpace JSON" />`,
    `<button type="button" id="btn-apply-plant" class="touch-control btn-secondary" data-action="apply-plant">Aplicar Planta</button>`,
    `<p class="json-format-hint">Formato esperado: <code>{"A": [[0,1],[0,0]], "B": [[0],[1]], "C": [[1,0]], "D": [[0]], "dt": null}</code></p>`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="lqr-weights-json">Pesos Q / R / x0 (JSON)</label>`,
    `<input id="lqr-weights-json" class="touch-control" type="text" data-field="weights-json" aria-label="Pesos Q R x0 JSON" />`,
    `<button type="button" id="btn-apply-weights" class="touch-control btn-secondary" data-action="apply-weights">Aplicar Pesos</button>`,
    `<p class="json-format-hint">Formato esperado: <code>{"Q": [[4,0],[0,5]], "R": [[1]], "x0": [1,0]}</code></p>`,
    `</div>`,
    `</div>`,
    `<div id="lqr-k-display"></div>`,
    `<div id="lqr-diagnostics-panel" class="diagnostics-panel"></div>`,
    `</section>`,
  ].join("\n");
}

export class StatespaceView {
  private readonly shell: ControlLabShell;
  private readonly container: HTMLElement;
  private readonly onOpenExportModal: (
    payload: StatespaceExportModalRequest,
    trigger: HTMLElement | null,
  ) => void;

  private readonly panelEl: HTMLElement | null;
  private readonly kpiCardsEl: HTMLElement | null;
  private readonly pbhBadgesEl: HTMLElement | null;
  private readonly interactiveBarEl: HTMLElement | null;
  private readonly statusTextEl: HTMLElement | null;
  private readonly sliderEl: HTMLElement | null;
  private readonly feedbackSelectEl: HTMLSelectElement | null;

  private readonly matrixEditorEl: HTMLElement | null;
  private readonly presetSelectEl: HTMLSelectElement | null;
  private readonly dimNEl: HTMLInputElement | null;
  private readonly dimMEl: HTMLInputElement | null;
  private readonly dimPEl: HTMLInputElement | null;
  private readonly dimDtEl: HTMLInputElement | null;
  private readonly matrixGridsEl: HTMLElement | null;

  private readonly filterAllBtnEl: HTMLElement | null;
  private readonly filterPlantBtnEl: HTMLElement | null;
  private readonly filterWeightsBtnEl: HTMLElement | null;

  private readonly jsonAdvancedEl: HTMLElement | null;
  private readonly plantJsonInputEl: HTMLInputElement | null;
  private readonly weightsJsonInputEl: HTMLInputElement | null;

  private readonly jsonModalEl: HTMLElement | null;
  private readonly jsonModalErrEl: HTMLElement | null;
  private readonly jsonModalPlantEl: HTMLTextAreaElement | null;
  private readonly jsonModalWeightsEl: HTMLTextAreaElement | null;
  private readonly jsonModalCloseBtnEl: HTMLElement | null;

  private readonly pvmExportOptionsEl: HTMLElement | null;
  private readonly pvmKindEl: HTMLSelectElement | null;
  private readonly pvmDynamicEl: HTMLTextAreaElement | null;
  private readonly pvmSaturationEl: HTMLInputElement | null;
  private readonly pvmMinEl: HTMLInputElement | null;
  private readonly pvmMaxEl: HTMLInputElement | null;

  private readonly kDisplaySlotEl: HTMLElement | null;
  private readonly diagnosticsPanelEl: HTMLElement | null;
  private readonly exportButtons: HTMLButtonElement[];

  private dragStartQScale = 1.0;
  private lastSyncedLqrEditorKey = "";
  private renderedPvmExportRevision = -1;
  private matrixFilterMode: MatrixFilterMode = "all";
  private editorDims: { n: number; m: number; p: number };
  private lastPbhAnalysis: {
    modelRevision: number;
    controllable?: boolean;
    stabilizable?: boolean;
    observable?: boolean;
    detectable?: boolean;
  } | null = null;

  constructor(options: StatespaceViewOptions) {
    this.shell = options.shell;
    this.container = options.container;
    this.onOpenExportModal = options.onOpenExportModal;

    const lqr = this.shell.getLqrWorkspace();
    const plant = lqr.getPlant();
    this.editorDims = {
      n: plant.matrices.A.shape[0],
      m: plant.matrices.B.shape[1],
      p: plant.matrices.C.shape[0],
    };

    this.panelEl = this.container.querySelector<HTMLElement>("#statespace-workspace-panel");
    this.kpiCardsEl = this.container.querySelector<HTMLElement>("#lqr-kpi-cards");
    this.pbhBadgesEl = this.container.querySelector<HTMLElement>("#lqr-pbh-badges");
    this.interactiveBarEl = this.container.querySelector<HTMLElement>(".lqr-interactive-bar");
    this.statusTextEl = this.container.querySelector<HTMLElement>("#lqr-status-text");
    this.sliderEl = this.container.querySelector<HTMLElement>("#lqr-q-slider");
    this.feedbackSelectEl = this.container.querySelector<HTMLSelectElement>("#lqr-feedback-sign");

    this.matrixEditorEl = this.container.querySelector<HTMLElement>("#lqr-matrix-editor");
    this.presetSelectEl = this.container.querySelector<HTMLSelectElement>("#lqr-preset-select");
    this.dimNEl = this.container.querySelector<HTMLInputElement>("#lqr-dim-n");
    this.dimMEl = this.container.querySelector<HTMLInputElement>("#lqr-dim-m");
    this.dimPEl = this.container.querySelector<HTMLInputElement>("#lqr-dim-p");
    this.dimDtEl = this.container.querySelector<HTMLInputElement>("#lqr-dim-dt");
    this.matrixGridsEl = this.container.querySelector<HTMLElement>("#lqr-matrix-grids");

    this.filterAllBtnEl = this.container.querySelector<HTMLElement>("#btn-lqr-filter-all");
    this.filterPlantBtnEl = this.container.querySelector<HTMLElement>("#btn-lqr-filter-plant");
    this.filterWeightsBtnEl = this.container.querySelector<HTMLElement>("#btn-lqr-filter-weights");

    this.jsonAdvancedEl = this.container.querySelector<HTMLElement>("#lqr-json-advanced");
    this.plantJsonInputEl = this.container.querySelector<HTMLInputElement>("#lqr-plant-json");
    this.weightsJsonInputEl = this.container.querySelector<HTMLInputElement>("#lqr-weights-json");

    this.jsonModalEl = this.container.querySelector<HTMLElement>("#lqr-json-modal");
    this.jsonModalErrEl = this.container.querySelector<HTMLElement>("#lqr-json-modal-error");
    this.jsonModalPlantEl = this.container.querySelector<HTMLTextAreaElement>("#lqr-modal-plant-json");
    this.jsonModalWeightsEl = this.container.querySelector<HTMLTextAreaElement>("#lqr-modal-weights-json");
    this.jsonModalCloseBtnEl = this.container.querySelector<HTMLElement>("#lqr-json-modal-close");

    this.pvmExportOptionsEl = this.container.querySelector<HTMLElement>("#pvm-export-options");
    this.pvmKindEl = this.container.querySelector<HTMLSelectElement>("#pvm-controller-kind");
    this.pvmDynamicEl = this.container.querySelector<HTMLTextAreaElement>("#pvm-dynamic-controller-json");
    this.pvmSaturationEl = this.container.querySelector<HTMLInputElement>("#pvm-saturation-enabled");
    this.pvmMinEl = this.container.querySelector<HTMLInputElement>("#pvm-u-min");
    this.pvmMaxEl = this.container.querySelector<HTMLInputElement>("#pvm-u-max");
    if (this.pvmDynamicEl) {
      this.pvmDynamicEl.value = JSON.stringify(DEFAULT_DYNAMIC_EXPORT_CONTROLLER, null, 2);
    }

    this.kDisplaySlotEl = this.container.querySelector<HTMLElement>("#lqr-k-display");
    this.diagnosticsPanelEl = this.container.querySelector<HTMLElement>("#lqr-diagnostics-panel");

    this.exportButtons = [
      this.container.querySelector<HTMLButtonElement>("#btn-save-experiment"),
      this.container.querySelector<HTMLButtonElement>("#btn-export-ctrlab"),
      this.container.querySelector<HTMLButtonElement>("#btn-export-gains"),
      this.container.querySelector<HTMLButtonElement>("#btn-export-csv"),
      this.container.querySelector<HTMLButtonElement>("#btn-build-report"),
    ].filter((b): b is HTMLButtonElement => b !== null);

    this.bindEvents();
  }

  public getMatrixFilterMode(): MatrixFilterMode {
    return this.matrixFilterMode;
  }

  public setMatrixFilterMode(mode: MatrixFilterMode): void {
    this.matrixFilterMode = mode;
    this.applyMatrixFilterVisibility();
  }

  private applyMatrixFilterVisibility(): void {
    const plantSet = new Set(["A", "B", "C", "D"]);
    const weightsSet = new Set(["Q", "R", "x0"]);
    if (this.matrixGridsEl) {
      for (const block of Array.from(this.matrixGridsEl.querySelectorAll<HTMLElement>(".lqr-matrix-block"))) {
        const name = block.getAttribute("data-matrix-block") ?? "";
        const visible =
          this.matrixFilterMode === "all" ||
          (this.matrixFilterMode === "plant" && plantSet.has(name)) ||
          (this.matrixFilterMode === "weights" && weightsSet.has(name));
        setElHidden(block, !visible);
      }
    }
    const btns: Array<[HTMLElement | null, boolean]> = [
      [this.filterAllBtnEl, this.matrixFilterMode === "all"],
      [this.filterPlantBtnEl, this.matrixFilterMode === "plant"],
      [this.filterWeightsBtnEl, this.matrixFilterMode === "weights"],
    ];
    for (const [btn, active] of btns) {
      toggleElCssClass(btn, "btn-primary", active);
      toggleElCssClass(btn, "btn-secondary", !active);
      btn?.setAttribute("aria-pressed", active ? "true" : "false");
    }
  }

  private openJsonModal(trigger: HTMLElement | null): void {
    const lqr = this.shell.getLqrWorkspace();
    const plant = lqr.getPlant();
    const weights = lqr.getWeights();
    if (this.jsonModalPlantEl) {
      this.jsonModalPlantEl.value = JSON.stringify(plant, null, 2);
    }
    if (this.jsonModalWeightsEl) {
      this.jsonModalWeightsEl.value = JSON.stringify(
        { Q: weights.Q, R: weights.R, x0: weights.x0 },
        null,
        2,
      );
    }
    if (this.jsonModalErrEl) {
      this.jsonModalErrEl.textContent = "";
      setElHidden(this.jsonModalErrEl, true);
    }
    this.shell.openModal("modal-lqr-json", trigger ?? "btn-open-lqr-json-modal");
    setElHidden(this.jsonModalEl, false);
    this.jsonModalPlantEl?.focus();
  }

  private closeJsonModal(): void {
    if (this.shell.getOpenModalId() === "modal-lqr-json") {
      this.shell.closeModal("modal-lqr-json");
    }
    setElHidden(this.jsonModalEl, true);
  }

  private renderMatrixEditorGrids(
    dims: { n: number; m: number; p: number },
    values: {
      A: number[];
      B: number[];
      C: number[];
      D: number[];
      Q: number[];
      R: number[];
      x0: number[];
    },
  ): void {
    if (!this.matrixGridsEl) return;
    this.matrixGridsEl.innerHTML = [
      renderMatrixGridBlockHtml("A", "Matriz A", dims.n, dims.n, values.A),
      renderMatrixGridBlockHtml("B", "Matriz B", dims.n, dims.m, values.B),
      renderMatrixGridBlockHtml("C", "Matriz C", dims.p, dims.n, values.C),
      renderMatrixGridBlockHtml("D", "Matriz D", dims.p, dims.m, values.D),
      renderMatrixGridBlockHtml("Q", "Peso Q", dims.n, dims.n, values.Q),
      renderMatrixGridBlockHtml("R", "Peso R", dims.m, dims.m, values.R),
      renderMatrixGridBlockHtml("x0", "Estado x0", dims.n, 1, values.x0),
    ].join("");
    this.applyMatrixFilterVisibility();
  }

  private readMatrixFromEditor(
    matrixName: "A" | "B" | "C" | "D" | "Q" | "R" | "x0",
    rows: number,
    cols: number,
  ): number[] {
    const out: number[] = [];
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const cell = this.matrixGridsEl?.querySelector<HTMLInputElement>(
          `input[data-matrix="${matrixName}"][data-row="${r}"][data-col="${c}"]`,
        );
        const val = cell ? Number(cell.value) : 0;
        if (!Number.isFinite(val)) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Valor inválido em ${matrixName}[${r}][${c}].`,
          );
        }
        out.push(val);
      }
    }
    return out;
  }

  private syncLqrInputsFromWorkspace(): void {
    const lqr = this.shell.getLqrWorkspace();
    const doc = this.container.ownerDocument;
    const plant = lqr.getPlant();
    const weights = lqr.getWeights();
    const syncKey = JSON.stringify({
      rev: plant.revision,
      A: plant.matrices.A.data,
      B: plant.matrices.B.data,
      C: plant.matrices.C.data,
      D: plant.matrices.D.data,
      dt: plant.dt,
      Q: weights.Q.data,
      R: weights.R.data,
      x0: weights.x0.data,
    });
    if (syncKey === this.lastSyncedLqrEditorKey) return;
    this.lastSyncedLqrEditorKey = syncKey;
    this.editorDims = {
      n: plant.matrices.A.shape[0],
      m: plant.matrices.B.shape[1],
      p: plant.matrices.C.shape[0],
    };
    if (this.dimNEl && doc?.activeElement !== this.dimNEl) this.dimNEl.value = String(this.editorDims.n);
    if (this.dimMEl && doc?.activeElement !== this.dimMEl) this.dimMEl.value = String(this.editorDims.m);
    if (this.dimPEl && doc?.activeElement !== this.dimPEl) this.dimPEl.value = String(this.editorDims.p);
    if (this.dimDtEl && doc?.activeElement !== this.dimDtEl) {
      this.dimDtEl.value = plant.dt === null ? "" : String(plant.dt);
    }
    this.renderMatrixEditorGrids(this.editorDims, {
      A: plant.matrices.A.data,
      B: plant.matrices.B.data,
      C: plant.matrices.C.data,
      D: plant.matrices.D.data,
      Q: weights.Q.data,
      R: weights.R.data,
      x0: weights.x0.data,
    });
    if (this.plantJsonInputEl && doc?.activeElement !== this.plantJsonInputEl) {
      this.plantJsonInputEl.value = JSON.stringify(plant);
    }
    if (this.weightsJsonInputEl && doc?.activeElement !== this.weightsJsonInputEl) {
      this.weightsJsonInputEl.value = JSON.stringify({
        Q: weights.Q,
        R: weights.R,
        x0: weights.x0,
      });
    }
  }

  private bindEvents(): void {
    const lqr = this.shell.getLqrWorkspace();

    if (this.sliderEl) {
      this.sliderEl.addEventListener("pointerdown", (ev: PointerEvent) => {
        this.dragStartQScale = lqr.getCurrentScaleFactors().qScale;
        try {
          this.sliderEl?.setPointerCapture?.(ev.pointerId);
        } catch {
          // Fallback quando mock DOM não implementa pointer capture
        }
        lqr.pointerDown("lqr-q-slider");
      });
      this.sliderEl.addEventListener("pointermove", (ev: PointerEvent) => {
        if (!lqr.getPreviewState().active || !this.sliderEl) return;
        const rect = this.sliderEl.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (ev.clientX - rect.left) / Math.max(1, rect.width)));
        const targetScale = 0.1 + ratio * (20 - 0.1);
        const relFactor = targetScale / Math.max(1e-6, this.dragStartQScale);
        lqr.pointerMove({ qScale: relFactor });
      });
      this.sliderEl.addEventListener("pointerup", (ev: PointerEvent) => {
        if (!lqr.getPreviewState().active) return;
        try {
          if (this.sliderEl?.hasPointerCapture?.(ev.pointerId)) {
            this.sliderEl.releasePointerCapture?.(ev.pointerId);
          }
        } catch {
          // ignore
        }
        void lqr.pointerUp();
      });
      this.sliderEl.addEventListener("pointercancel", () => {
        void lqr.cancelDrag();
      });
      this.sliderEl.addEventListener("blur", () => {
        lqr.handleBlur();
      });
      this.sliderEl.addEventListener("keydown", (ev: KeyboardEvent) => {
        const currentVal = lqr.getPreviewState().active
          ? Math.min(20, Math.max(0.1, this.dragStartQScale * lqr.getPreviewState().qScale))
          : lqr.getCurrentScaleFactors().qScale;
        const sliderCfg: AccessibleSliderConfig = {
          min: 0.1,
          max: 20,
          step: 0.1,
          value: currentVal,
          label: "Fator de escala Q (arraste para preview / solte para commit)",
        };
        void lqr.handleKeyboardSlider(ev.key, "q_scale", sliderCfg).then((r) => {
          if (r.handled) {
            ev.preventDefault();
          }
        });
      });
    }

    this.feedbackSelectEl?.addEventListener("change", () => {
      const val = this.feedbackSelectEl?.value === "positive" ? "positive" : "negative";
      lqr.updateWeights({ feedbackSign: val });
      void lqr.commitCurrentDesign();
    });

    this.filterAllBtnEl?.addEventListener("click", () => this.setMatrixFilterMode("all"));
    this.filterPlantBtnEl?.addEventListener("click", () => this.setMatrixFilterMode("plant"));
    this.filterWeightsBtnEl?.addEventListener("click", () => this.setMatrixFilterMode("weights"));

    this.container
      .querySelector<HTMLElement>('[data-action="open-lqr-json-modal"]')
      ?.addEventListener("click", (ev) => {
        this.openJsonModal(ev.currentTarget as HTMLElement | null);
      });
    this.jsonModalCloseBtnEl?.addEventListener("click", () => {
      this.closeJsonModal();
    });
    this.jsonModalEl?.addEventListener("keydown", (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        this.closeJsonModal();
      }
    });

    this.container
      .querySelector<HTMLElement>('[data-action="lqr-modal-apply-plant"]')
      ?.addEventListener("click", () => {
        try {
          if (this.jsonModalErrEl) {
            this.jsonModalErrEl.textContent = "";
            setElHidden(this.jsonModalErrEl, true);
          }
          const raw = this.jsonModalPlantEl?.value?.trim() ?? "";
          if (raw.length > 0) {
            lqr.updatePlant(normalizePlantJsonInput(JSON.parse(raw), lqr.getPlant()));
          }
          this.closeJsonModal();
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (this.jsonModalErrEl) {
            this.jsonModalErrEl.textContent = msg;
            setElHidden(this.jsonModalErrEl, false);
          }
          this.shell.presentError(err);
        }
      });

    this.container
      .querySelector<HTMLElement>('[data-action="lqr-modal-apply-weights"]')
      ?.addEventListener("click", () => {
        try {
          if (this.jsonModalErrEl) {
            this.jsonModalErrEl.textContent = "";
            setElHidden(this.jsonModalErrEl, true);
          }
          const raw = this.jsonModalWeightsEl?.value?.trim() ?? "";
          if (raw.length > 0) {
            lqr.updateWeights(normalizeWeightsJsonInput(JSON.parse(raw)));
          }
          this.closeJsonModal();
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (this.jsonModalErrEl) {
            this.jsonModalErrEl.textContent = msg;
            setElHidden(this.jsonModalErrEl, false);
          }
          this.shell.presentError(err);
        }
      });

    this.container
      .querySelector<HTMLElement>('[data-action="lqr-apply-preset"]')
      ?.addEventListener("click", () => {
        try {
          const presetId = this.presetSelectEl?.value ?? "double_integrator";
          const preset = LQR_PRESETS[presetId];
          if (!preset) return;
          const basePlant = lqr.getPlant();
          const nextPlant: CanonicalStateSpaceModel = {
            schema_version: "1.0.0",
            id: `plant-${preset.id}`,
            revision: basePlant.revision + 1,
            kind: "StateSpace",
            dt: preset.dt,
            state_names: Array.from({ length: preset.n }, (_, i) => `x${i + 1}`),
            input_names: Array.from({ length: preset.m }, (_, i) => `u${i + 1}`),
            output_names: Array.from({ length: preset.p }, (_, i) => `y${i + 1}`),
            matrices: {
              A: makeFloat64Tensor([preset.n, preset.n], [...preset.A]),
              B: makeFloat64Tensor([preset.n, preset.m], [...preset.B]),
              C: makeFloat64Tensor([preset.p, preset.n], [...preset.C]),
              D: makeFloat64Tensor([preset.p, preset.m], [...preset.D]),
            },
            units: {
              time: "s",
              states: Array.from({ length: preset.n }, () => ""),
              inputs: Array.from({ length: preset.m }, () => ""),
              outputs: Array.from({ length: preset.p }, () => ""),
            },
            provenance: { source: `preset:${preset.id}` },
          };
          lqr.updatePlant(nextPlant);
          lqr.updateWeights({
            Q: makeFloat64Tensor([preset.n, preset.n], [...preset.Q]),
            R: makeFloat64Tensor([preset.m, preset.m], [...preset.R]),
            x0: makeFloat64Tensor([preset.n, 1], [...preset.x0]),
          });
        } catch (err: unknown) {
          this.shell.presentError(err);
        }
      });

    const handleDimChange = (): void => {
      const clampDim = (val: number, min: number, max: number, fallback: number): number =>
        Number.isInteger(val) ? Math.min(max, Math.max(min, val)) : fallback;
      const nextN = clampDim(Number(this.dimNEl?.value ?? this.editorDims.n), 1, 6, this.editorDims.n);
      const nextM = clampDim(Number(this.dimMEl?.value ?? this.editorDims.m), 1, 4, this.editorDims.m);
      const nextP = clampDim(Number(this.dimPEl?.value ?? this.editorDims.p), 1, 4, this.editorDims.p);
      const prevN = this.editorDims.n;
      const prevM = this.editorDims.m;
      const prevP = this.editorDims.p;
      const resize2D = (
        oldData: number[],
        oldR: number,
        oldC: number,
        newR: number,
        newC: number,
        diagDefault = 0,
      ): number[] => {
        const res = new Array<number>(newR * newC).fill(0);
        for (let r = 0; r < newR; r += 1) {
          for (let c = 0; c < newC; c += 1) {
            if (r < oldR && c < oldC) {
              res[r * newC + c] = oldData[r * oldC + c] ?? 0;
            } else if (r === c && diagDefault !== 0) {
              res[r * newC + c] = diagDefault;
            }
          }
        }
        return res;
      };
      let oldA: number[] = [];
      let oldB: number[] = [];
      let oldC: number[] = [];
      let oldD: number[] = [];
      let oldQ: number[] = [];
      let oldR: number[] = [];
      let oldX0: number[] = [];
      try {
        oldA = this.readMatrixFromEditor("A", prevN, prevN);
        oldB = this.readMatrixFromEditor("B", prevN, prevM);
        oldC = this.readMatrixFromEditor("C", prevP, prevN);
        oldD = this.readMatrixFromEditor("D", prevP, prevM);
        oldQ = this.readMatrixFromEditor("Q", prevN, prevN);
        oldR = this.readMatrixFromEditor("R", prevM, prevM);
        oldX0 = this.readMatrixFromEditor("x0", prevN, 1);
      } catch {
        const plant = lqr.getPlant();
        const weights = lqr.getWeights();
        oldA = plant.matrices.A.data;
        oldB = plant.matrices.B.data;
        oldC = plant.matrices.C.data;
        oldD = plant.matrices.D.data;
        oldQ = weights.Q.data;
        oldR = weights.R.data;
        oldX0 = weights.x0.data;
      }
      this.editorDims = { n: nextN, m: nextM, p: nextP };
      this.renderMatrixEditorGrids(this.editorDims, {
        A: resize2D(oldA, prevN, prevN, nextN, nextN),
        B: resize2D(oldB, prevN, prevM, nextN, nextM),
        C: resize2D(oldC, prevP, prevN, nextP, nextN),
        D: resize2D(oldD, prevP, prevM, nextP, nextM),
        Q: resize2D(oldQ, prevN, prevN, nextN, nextN, 1),
        R: resize2D(oldR, prevM, prevM, nextM, nextM, 1),
        x0: resize2D(oldX0, prevN, 1, nextN, 1),
      });
    };
    this.dimNEl?.addEventListener("change", handleDimChange);
    this.dimMEl?.addEventListener("change", handleDimChange);
    this.dimPEl?.addEventListener("change", handleDimChange);

    this.container
      .querySelector<HTMLElement>('[data-action="lqr-apply-matrices"]')
      ?.addEventListener("click", () => {
        try {
          const { n, m, p } = this.editorDims;
          const dtRaw = this.dimDtEl?.value?.trim() ?? "";
          const dtVal = dtRaw === "" ? null : Number(dtRaw);
          if (dtVal !== null && (!Number.isFinite(dtVal) || dtVal <= 0)) {
            throw new ControlLabBridgeError(
              "VALIDATION_ERROR",
              "dt deve ser vazio (contínuo) ou um número positivo > 0.",
            );
          }
          const AData = this.readMatrixFromEditor("A", n, n);
          const BData = this.readMatrixFromEditor("B", n, m);
          const CData = this.readMatrixFromEditor("C", p, n);
          const DData = this.readMatrixFromEditor("D", p, m);
          const QData = this.readMatrixFromEditor("Q", n, n);
          const RData = this.readMatrixFromEditor("R", m, m);
          const x0Data = this.readMatrixFromEditor("x0", n, 1);

          const basePlant = lqr.getPlant();
          const nextPlant: CanonicalStateSpaceModel = {
            schema_version: "1.0.0",
            id: basePlant.id,
            revision: basePlant.revision + 1,
            kind: "StateSpace",
            dt: dtVal,
            state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
            input_names: Array.from({ length: m }, (_, i) => `u${i + 1}`),
            output_names: Array.from({ length: p }, (_, i) => `y${i + 1}`),
            matrices: {
              A: makeFloat64Tensor([n, n], AData),
              B: makeFloat64Tensor([n, m], BData),
              C: makeFloat64Tensor([p, n], CData),
              D: makeFloat64Tensor([p, m], DData),
            },
            units: {
              time: basePlant.units.time,
              states: Array.from({ length: n }, () => ""),
              inputs: Array.from({ length: m }, () => ""),
              outputs: Array.from({ length: p }, () => ""),
            },
            provenance: { source: "ui_matrix_editor" },
          };
          lqr.updatePlant(nextPlant);
          lqr.updateWeights({
            Q: makeFloat64Tensor([n, n], QData),
            R: makeFloat64Tensor([m, m], RData),
            x0: makeFloat64Tensor([n, 1], x0Data),
          });
        } catch (err: unknown) {
          this.shell.presentError(err);
        }
      });

    this.container
      .querySelector<HTMLElement>('[data-action="apply-plant"]')
      ?.addEventListener("click", () => {
        try {
          const raw = this.plantJsonInputEl?.value?.trim() ?? "";
          const nextPlant =
            raw.length > 0
              ? normalizePlantJsonInput(JSON.parse(raw), lqr.getPlant())
              : lqr.getPlant();
          lqr.updatePlant(nextPlant);
        } catch (err: unknown) {
          this.shell.presentError(err);
        }
      });

    this.container
      .querySelector<HTMLElement>('[data-action="apply-weights"]')
      ?.addEventListener("click", () => {
        try {
          const raw = this.weightsJsonInputEl?.value?.trim() ?? "";
          const nextWeights =
            raw.length > 0
              ? normalizeWeightsJsonInput(JSON.parse(raw))
              : {
                  feedbackSign:
                    this.feedbackSelectEl?.value === "positive"
                      ? ("positive" as const)
                      : lqr.getFeedbackSign(),
                };
          lqr.updateWeights(nextWeights);
        } catch (err: unknown) {
          this.shell.presentError(err);
        }
      });

    this.container
      .querySelector<HTMLElement>('[data-action="commit-lqr"]')
      ?.addEventListener("click", () => {
        void lqr.commitCurrentDesign();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="analyze-open-loop"]')
      ?.addEventListener("click", () => {
        void lqr.analyzeOpenLoop().then((resp) => {
          if (resp.status !== "failure" && resp.result) {
            const res = resp.result;
            this.lastPbhAnalysis = {
              modelRevision: lqr.getPlant().revision,
              controllable: typeof res.controllable === "boolean" ? res.controllable : undefined,
              stabilizable: typeof res.stabilizable === "boolean" ? res.stabilizable : undefined,
              observable: typeof res.observable === "boolean" ? res.observable : undefined,
              detectable: typeof res.detectable === "boolean" ? res.detectable : undefined,
            };
            this.renderKpiAndPbh();
          }
        });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="cancel-lqr"]')
      ?.addEventListener("click", () => {
        void lqr.cancelDrag();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="undo-lqr"]')
      ?.addEventListener("click", () => {
        void lqr.undo();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="save-experiment"]')
      ?.addEventListener("click", () => {
        try {
          this.shell.addCommittedExperiment();
          this.shell.getAnnouncer().announce(
            `Experimento adicionado ao comparador (${this.shell.listExperiments().length} total).`,
            "polite",
            "committed",
          );
        } catch (err: unknown) {
          this.shell.presentError(err);
        }
      });

    const updatePvmExportOptions = (): void => {
      this.shell.invalidatePvmExportOptions();
      const kind = this.pvmKindEl?.value === "dynamic" ? "dynamic" : "lqr";
      const enabled = this.pvmSaturationEl?.checked === true;
      if (this.pvmDynamicEl) this.pvmDynamicEl.disabled = kind !== "dynamic";
      if (this.pvmMinEl) this.pvmMinEl.disabled = !enabled;
      if (this.pvmMaxEl) this.pvmMaxEl.disabled = !enabled;
      try {
        let dynamicController: Record<string, unknown> | undefined;
        try {
          const candidate = JSON.parse(this.pvmDynamicEl?.value ?? "");
          if (kind === "dynamic" || candidate?.kind === "DynamicController") {
            dynamicController = candidate;
          }
        } catch (error: unknown) {
          if (kind === "dynamic") throw error;
        }
        this.shell.setPvmExportOptions({
          controller_kind: kind,
          ...(dynamicController === undefined ? {} : { dynamic_controller: dynamicController }),
          saturation: {
            enabled,
            u_min: enabled ? JSON.parse(this.pvmMinEl?.value ?? "") : -1,
            u_max: enabled ? JSON.parse(this.pvmMaxEl?.value ?? "") : 1,
          },
        });
      } catch (error: unknown) {
        this.shell.presentError(
          error instanceof SyntaxError
            ? new ControlLabBridgeError(
                "VALIDATION_ERROR",
                "JSON inválido na configuração PVM. Confira o controlador e os limites.",
              )
            : error,
        );
      }
    };
    for (const input of [
      this.pvmKindEl,
      this.pvmDynamicEl,
      this.pvmSaturationEl,
      this.pvmMinEl,
      this.pvmMaxEl,
    ]) {
      input?.addEventListener("input", updatePvmExportOptions);
      input?.addEventListener("change", updatePvmExportOptions);
    }

    const openNativeFile = async (kind: "pvm" | "ctrlab", trigger: HTMLElement | null): Promise<void> => {
      const file = kind === "pvm" ? await this.shell.exportPvm() : await this.shell.exportCtrlLab();
      this.onOpenExportModal(
        {
          title: `Exportação .${kind}`,
          filename: file.filename,
          mimeType: file.media_type,
          bytes: file.bytes,
          projectRevision: file.project_revision,
          projectId: file.project_id,
          requestId: file.request_id,
          configurationRevision: file.configuration_revision,
          pvmControllerKind: file.pvm_controller_kind,
          content: `${file.filename} · ${file.bytes.length} bytes · SHA-256 ${file.sha256}`,
        },
        trigger,
      );
    };
    for (const kind of ["pvm", "ctrlab"] as const) {
      this.container
        .querySelector<HTMLElement>(`[data-action="export-${kind}"]`)
        ?.addEventListener("click", (ev) => {
          void openNativeFile(kind, ev.currentTarget as HTMLElement | null).catch(
            (error: unknown) => this.shell.presentError(error),
          );
        });
    }

    const importFileInput = this.container.querySelector<HTMLInputElement>("#ctrlab-file-input");
    importFileInput?.addEventListener("change", () => {
      const file = importFileInput.files?.[0];
      if (!file) return;
      void this.shell
        .importCtrlLab(file.arrayBuffer().then((buffer) => new Uint8Array(buffer)))
        .catch((error: unknown) => this.shell.presentError(error))
        .finally(() => {
          importFileInput.value = "";
        });
    });

    this.container
      .querySelector<HTMLElement>('[data-action="export-gains"]')
      ?.addEventListener("click", (ev) => {
        try {
          const gains = this.shell.exportGains();
          this.onOpenExportModal(
            {
              title: "Ganhos Confirmados LQR (JSON)",
              filename: `${gains.project_id}_gains_r${gains.project_revision}.json`,
              mimeType: "application/json",
              content: JSON.stringify(gains, null, 2),
            },
            ev.currentTarget as HTMLElement | null,
          );
        } catch (err: unknown) {
          this.shell.presentError(err);
        }
      });

    this.container
      .querySelector<HTMLElement>('[data-action="export-csv"]')
      ?.addEventListener("click", (ev) => {
        try {
          const chart = lqr.buildTimeResponseChart() ?? lqr.buildPoleZeroChart();
          const csv = this.shell.exportChartCsv(chart);
          this.onOpenExportModal(
            {
              title: "Exportação Científica CSV (com proveniência)",
              filename: `${chart.chart_id}_r${String(chart.project_revision)}.csv`,
              mimeType: "text/csv;charset=utf-8",
              content: csv,
            },
            ev.currentTarget as HTMLElement | null,
          );
        } catch (err: unknown) {
          this.shell.presentError(err);
        }
      });

    this.container
      .querySelector<HTMLElement>('[data-action="build-report"]')
      ?.addEventListener("click", (ev) => {
        try {
          const report = this.shell.buildScientificReport();
          this.onOpenExportModal(
            {
              title: "Relatório Científico Rastreável (R-27)",
              filename: `${report.project_id}_report_r${report.project_revision}.json`,
              mimeType: "application/json",
              content: JSON.stringify(report, null, 2),
            },
            ev.currentTarget as HTMLElement | null,
          );
        } catch (err: unknown) {
          this.shell.presentError(err);
        }
      });
  }

  private renderKpiAndPbh(): void {
    const lqr = this.shell.getLqrWorkspace();
    const decimals = this.shell.getDisplayDecimals();
    const committed = lqr.getCommittedSnapshot();
    const plant = lqr.getPlant();
    const fbSign = committed?.feedback_sign ?? lqr.getFeedbackSign();

    if (this.kpiCardsEl) {
      const kStr = committed?.K
        ? formatMatrixDisplay(
            committed.K.data,
            committed.K.shape[0] ?? 1,
            committed.K.shape[1] ?? committed.K.data.length,
            decimals,
          )
            .map((row) => `[${row.join(", ")}]`)
            .join("; ")
        : "Aguardando síntese";

      const polesStr =
        committed?.closed_loop_poles && committed.closed_loop_poles.real.length > 0
          ? committed.closed_loop_poles.real
              .slice(0, 4)
              .map((re, idx) => {
                const im = committed.closed_loop_poles?.imag[idx] ?? 0;
                const imStr =
                  Math.abs(im) > 1e-9
                    ? ` ${im >= 0 ? "+" : "-"} j${formatNumericDisplay(Math.abs(im), Math.min(decimals, 2))}`
                    : "";
                return `${formatNumericDisplay(re, Math.min(decimals, 2))}${imStr}`;
              })
              .join(", ") + (committed.closed_loop_poles.real.length > 4 ? "…" : "")
          : "Aguardando síntese";

      const jStr =
        committed?.optimal_cost !== null && committed?.optimal_cost !== undefined
          ? formatNumericDisplay(committed.optimal_cost, decimals)
          : "—";

      const signFormula = fbSign === "positive" ? "A + BK" : "A - BK";

      this.kpiCardsEl.innerHTML = [
        `<div class="kpi-card" data-kpi="gain-k">`,
        `<span class="kpi-label">Ganho Ótimo K</span>`,
        `<strong class="kpi-value">${escapeHtml(kStr)}</strong>`,
        `</div>`,
        `<div class="kpi-card" data-kpi="closed-poles">`,
        `<span class="kpi-label">Polos ${escapeHtml(signFormula)}</span>`,
        `<strong class="kpi-value">${escapeHtml(polesStr)}</strong>`,
        `</div>`,
        `<div class="kpi-card" data-kpi="optimal-cost">`,
        `<span class="kpi-label">Custo Ótimo J*</span>`,
        `<strong class="kpi-value">${escapeHtml(jStr)}</strong>`,
        `</div>`,
      ].join("");
    }

    if (this.pbhBadgesEl) {
      const pbhForPlant =
        this.lastPbhAnalysis && this.lastPbhAnalysis.modelRevision === plant.revision
          ? this.lastPbhAnalysis
          : null;
      const stabilizable =
        pbhForPlant?.stabilizable ??
        (typeof committed?.assumptions?.stabilizable === "boolean"
          ? committed.assumptions.stabilizable
          : undefined);
      const detectable =
        pbhForPlant?.detectable ??
        (typeof committed?.assumptions?.detectable === "boolean"
          ? committed.assumptions.detectable
          : undefined);
      const controllable = pbhForPlant?.controllable;
      const observable = pbhForPlant?.observable;

      const ctrlBadge =
        controllable === true
          ? `<span class="badge badge-exact" data-pbh="controllable">Controlável (PBH) ✓</span>`
          : stabilizable === true
            ? `<span class="badge badge-exact" data-pbh="stabilizable">Estabilizável (PBH) ✓</span>`
            : stabilizable === false || controllable === false
              ? `<span class="badge badge-experimental" data-pbh="uncontrollable">Não controlável / violada</span>`
              : `<span class="badge badge-sufficient" data-pbh="pending">PBH Controlabilidade: pendente</span>`;

      const obsBadge =
        observable === true
          ? `<span class="badge badge-exact" data-pbh="observable">Observável (PBH) ✓</span>`
          : detectable === true
            ? `<span class="badge badge-exact" data-pbh="detectable">Detectável (PBH) ✓</span>`
            : detectable === false || observable === false
              ? `<span class="badge badge-experimental" data-pbh="unobservable">Não observável / violada</span>`
              : `<span class="badge badge-sufficient" data-pbh="obs-pending">PBH Observabilidade: pendente</span>`;

      const riccatiBadge =
        plant.dt === null
          ? `<span class="badge badge-stable" data-riccati-method="care">CARE (Contínuo)</span>`
          : `<span class="badge badge-stable" data-riccati-method="dare">DARE (Discreto dt=${escapeHtml(String(plant.dt))} s)</span>`;

      const riccatiVerified = committed
        ? `<span class="badge badge-numeric_verified">Solução Riccati Verificada ✓</span>`
        : "";

      this.pbhBadgesEl.innerHTML = [ctrlBadge, obsBadge, riccatiBadge, riccatiVerified]
        .filter(Boolean)
        .join(" ");
    }
  }

  public render(): void {
    const activeTab = this.shell.getActiveTab();
    const isStatespace = activeTab === "statespace";

    setElHidden(this.panelEl, !isStatespace);
    setElHidden(this.interactiveBarEl, !isStatespace);
    setElHidden(this.matrixEditorEl, !isStatespace);
    setElHidden(this.jsonAdvancedEl, !isStatespace);
    setElHidden(this.pvmExportOptionsEl, !isStatespace);
    setElHidden(this.kDisplaySlotEl, !isStatespace);
    setElHidden(this.diagnosticsPanelEl, !isStatespace);

    this.syncLqrInputsFromWorkspace();

    const lqr = this.shell.getLqrWorkspace();
    const doc = this.container.ownerDocument;
    const decimals = this.shell.getDisplayDecimals();
    const committed = lqr.getCommittedSnapshot();
    const preview = lqr.getPreviewState();
    const pendingCommit = lqr.isPendingCommit();
    const exportGuard = lqr.canExport();

    this.renderKpiAndPbh();

    if (this.statusTextEl) {
      this.statusTextEl.textContent = preview.active
        ? "Fast-Preview Transitório (não salvo)"
        : pendingCommit
          ? "pending_commit (aguardando motor Python)"
          : lqr.isControllerInvalidated()
            ? "Controlador invalidado (planta modificada)"
            : committed
              ? "Confirmado"
              : "Inicial";
    }

    const sliderValue = preview.active
      ? Math.min(20, Math.max(0.1, this.dragStartQScale * preview.qScale))
      : lqr.getCurrentScaleFactors().qScale;
    const sliderCfg: AccessibleSliderConfig = {
      min: 0.1,
      max: 20,
      step: 0.1,
      value: sliderValue,
      label: "Fator de escala Q (arraste para preview / solte para commit)",
    };

    if (this.sliderEl) {
      const sliderAttrs = getSliderAriaAttributes(sliderCfg, decimals);
      for (const [k, v] of Object.entries(sliderAttrs)) {
        this.sliderEl.setAttribute(k, v);
      }
      this.sliderEl.textContent = `Escala Q: ${formatNumericDisplay(sliderCfg.value, decimals)}`;
    }

    if (this.feedbackSelectEl) {
      this.feedbackSelectEl.value = lqr.getFeedbackSign();
    }

    for (const btn of this.exportButtons) {
      btn.disabled = !exportGuard.allowed;
      if (exportGuard.allowed) {
        btn.removeAttribute("aria-disabled");
      } else {
        btn.setAttribute("aria-disabled", "true");
      }
    }

    const pvmOptions = this.shell.getPvmExportOptions();
    if (pvmOptions && this.renderedPvmExportRevision !== this.shell.getPvmExportRevision()) {
      this.renderedPvmExportRevision = this.shell.getPvmExportRevision();
      if (this.pvmKindEl) this.pvmKindEl.value = pvmOptions.controller_kind;
      if (this.pvmDynamicEl) {
        this.pvmDynamicEl.disabled = pvmOptions.controller_kind !== "dynamic";
        if (doc?.activeElement !== this.pvmDynamicEl) {
          this.pvmDynamicEl.value = JSON.stringify(
            pvmOptions.dynamic_controller ?? DEFAULT_DYNAMIC_EXPORT_CONTROLLER,
            null,
            2,
          );
        }
      }
      if (this.pvmSaturationEl) this.pvmSaturationEl.checked = pvmOptions.saturation.enabled;
      if (this.pvmMinEl) {
        this.pvmMinEl.disabled = !pvmOptions.saturation.enabled;
        if (doc?.activeElement !== this.pvmMinEl) {
          this.pvmMinEl.value = JSON.stringify(pvmOptions.saturation.u_min);
        }
      }
      if (this.pvmMaxEl) {
        this.pvmMaxEl.disabled = !pvmOptions.saturation.enabled;
        if (doc?.activeElement !== this.pvmMaxEl) {
          this.pvmMaxEl.value = JSON.stringify(pvmOptions.saturation.u_max);
        }
      }
    }

    const pvmButton = this.container.querySelector<HTMLButtonElement>("#btn-export-pvm");
    if (pvmButton) {
      pvmButton.disabled = !this.shell.canExportPvm();
      if (pvmButton.disabled) pvmButton.setAttribute("aria-disabled", "true");
      else pvmButton.removeAttribute("aria-disabled");
    }

    if (this.kDisplaySlotEl) {
      this.kDisplaySlotEl.innerHTML = committed?.K
        ? `<pre aria-label="Matriz de ganho K">${escapeHtml(
            JSON.stringify(
              formatMatrixDisplay(
                committed.K.data,
                committed.K.shape[0] ?? 1,
                committed.K.shape[1] ?? committed.K.data.length,
                decimals,
              ),
            ),
          )}</pre>`
        : `<p>Nenhum ganho comitado ainda.</p>`;
    }

    if (this.diagnosticsPanelEl) {
      if (committed) {
        const metrics = this.shell.getExecutionMetrics();
        const rCare =
          typeof committed.diagnostics.care_residual_rel === "number"
            ? formatNumericDisplay(committed.diagnostics.care_residual_rel, decimals)
            : "N/D";
        const symErr =
          typeof committed.diagnostics.symmetry_error === "number"
            ? formatNumericDisplay(committed.diagnostics.symmetry_error, decimals)
            : "N/D";
        const jOpt =
          committed.optimal_cost !== null
            ? formatNumericDisplay(committed.optimal_cost, decimals)
            : "N/D";
        const tWarm =
          metrics.T_warm_call !== null
            ? formatNumericDisplay(metrics.T_warm_call, 2)
            : "N/D";
        diagnosticsHtml(this.diagnosticsPanelEl, [
          `<p><strong>Proveniência (R-27):</strong> algoritmo <code>${escapeHtml(committed.provenance.algorithm)}</code> | status <code>${escapeHtml(committed.status)}</code> | sinal <code>${escapeHtml(committed.feedback_sign)}</code></p>`,
          `<p><strong>Diagnósticos:</strong> J*=${escapeHtml(jOpt)} | rCARE=${escapeHtml(rCare)} | erro simetria=${escapeHtml(symErr)} | T_warm=${escapeHtml(tWarm)} ms</p>`,
        ].join(""));
      } else {
        diagnosticsHtml(
          this.diagnosticsPanelEl,
          `<p>Aguardando primeiro cálculo autoritativo Python para exibir proveniência e resíduos.</p>`,
        );
      }
    }

    if (this.jsonModalEl) {
      setElHidden(this.jsonModalEl, this.shell.getOpenModalId() !== "modal-lqr-json");
    }
  }
}

function diagnosticsHtml(el: HTMLElement, html: string): void {
  el.innerHTML = html;
}
