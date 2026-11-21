/**
 * Bancada da Aba 6 — LMIs, SDPs e Síntese Robusta
 * seguindo CL-LMI-DSL-DIR-001 v1.0.0, CL-UX-DIR-001 v1.0.0 Seção 4.6 e ADR-010
 * (`WP-UX-REFACTOR-03-MIMO-FUZZY-LMI` + `WP-LMI-V2-02-SYSTEM-CHARACTERIZATION-UI`).
 *
 * Responsabilidades estritas de UI/Apresentação (F8):
 * - Zona 1: Barra de ações, templates v1.0/v2.0, salvar/carregar presets e exportar/importar `.lmi`.
 * - Zona 2: Quadro de Caracterização do Sistema e Conjuntos de Índices (`#lmi-system-characterization-card`)
 *   com modos LTI / Planta Generalizada (`Bw, Cz, Dzu, Dzw`), Politópico Incerto (`N_v`, vértices ±δ%)
 *   e Takagi-Sugeno (`N_r`, importação de pertinências da Aba 5 e premissas Medidas vs. Não Medidas).
 * - Zona 3: Editor DSL estilo Monaco (`#lmi-code-editor` + `#lmi-line-gutter`) + Leitura Matemática
 *   Interpretada (`#lmi-parsed-vars`, `#lmi-parsed-math`, `#lmi-expanded-blocks-badge`) via parser puro sem `eval`.
 * - Zona 4: Certificado de Auditoria Independente em 5 Dimensões (`#lmi-certificate-panel`)
 *   + ganho recuperado `K` + Espectro de autovalores LMI (`#lmi-spectrum-chart-slot`).
 * - Exportação CVXPY/YALMIP sempre habilitada (ADR-010), com laços `for` quantificados para DSL v2.0.
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
import {
  escapeHtml,
  formatMatrixDisplay,
  formatNumericDisplay,
} from "../../app/accessibility.ts";
import type { ControlLabShell } from "../../app/shell.ts";
import {
  buildAccessibleChartTable,
  buildLmiSpectrumChartModel,
  renderAccessibleTableHtml,
  renderLmiSpectrumSvg,
  type LmiSpectrumChartModel,
} from "../../charts/scientific_chart.ts";
import {
  generateQuantifiedCvxpySnippet,
  generateQuantifiedYalmipSnippet,
  LMI_DSL_TEMPLATES,
  parseLmiDsl,
  resolveShapeLabel,
  type LmiBackendTemplateId,
  type LmiDslParseOptions,
  type LmiDslParseResult,
  type LmiQuantifiedExportContext,
} from "./lmi_dsl_parser.ts";

export interface LmiExportModalPayload {
  title: string;
  filename: string;
  mimeType: string;
  content: string;
  offlineDesign?: boolean;
}

export interface LmiViewOptions {
  shell: ControlLabShell;
  client: ControlLabEngineClient;
  container: HTMLElement;
  onRequestRender?: () => void;
  onOpenExportModal?: (payload: LmiExportModalPayload, trigger: HTMLElement | null) => void;
}

export interface SavedLmiPreset {
  id: string;
  name: string;
  template: LmiBackendTemplateId;
  dsl: string;
  savedAt: string;
}

interface LmiPremiseVarState {
  name: string;
  measured: boolean;
}

interface LmiPolytopeVertexPreview {
  index: number;
  label: string;
  aMatrix: number[][];
}

interface LmiSystemCharacterizationState {
  systemClass: "lti" | "polytopic" | "ts";
  genEnableW: boolean;
  genEnableZ: boolean;
  genBwText: string;
  genCzText: string;
  genDzuText: string;
  genDzwText: string;
  polyVerticesCount: number;
  polyIndexName: string;
  polyDeltaPct: number;
  polyVertices: LmiPolytopeVertexPreview[];
  tsRulesCount: number;
  tsIndexName: string;
  tsPremises: LmiPremiseVarState[];
  tsMfSummary: string[];
  extraIndices: string;
}

interface LmiSolveSnapshot {
  operation: string;
  responseStatus: string;
  solverStatus: string;
  auditFeasibility: string;
  certificateStatus: string;
  conditioningStatus: string;
  conditionNumber: number | null;
  nearBoundary: boolean;
  scalingWarning: boolean;
  controllerValidity: string;
  objective: number | null;
  offlineRecommended: boolean;
  blockMinEigs: number[];
  rawSolutionPayload: Record<string, unknown>;
  recoveredK: { rows: number; cols: number; data: number[] } | null;
  warnings: string[];
  provenance: Provenance | null;
}

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function makeFloat64Tensor(shape: number[], data: number[]): RealTensor {
  return { shape, dtype: "float64", order: "C", data };
}

function renderLmiExportBarHtml(slotId: string, label: string): string {
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

function extractRealTensor2D(
  raw: unknown,
): { rows: number; cols: number; data: number[] } | null {
  if (!isPlainObject(raw) || !Array.isArray(raw.data) || !Array.isArray(raw.shape)) {
    return null;
  }
  const shape = raw.shape as number[];
  const rows = Number(shape[0] ?? 1);
  const cols = Number(shape[1] ?? (raw.data as number[]).length);
  if (!Number.isInteger(rows) || !Number.isInteger(cols) || rows < 1 || cols < 1) {
    return null;
  }
  return {
    rows,
    cols,
    data: (raw.data as unknown[]).map((v) => Number(v)),
  };
}

function parseCompactMatrixJson(text: string): number[][] | null {
  try {
    const parsed = JSON.parse(text.trim()) as unknown;
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    if (Array.isArray(parsed[0])) {
      return (parsed as unknown[][]).map((r) => r.map((v) => Number(v)));
    }
    return [(parsed as unknown[]).map((v) => Number(v))];
  } catch {
    return null;
  }
}

/**
 * Formata K = Y * Q^{-1} apenas para exibição visual quando `result.variables` traz `Q` e `Y`.
 * Nunca altera `controller_validity` retornado pelo auditor Python.
 */
function formatGainFromQY(
  qMat: { rows: number; cols: number; data: number[] },
  yMat: { rows: number; cols: number; data: number[] },
): { rows: number; cols: number; data: number[] } | null {
  const n = qMat.rows;
  const m = yMat.rows;
  if (n !== qMat.cols || yMat.cols !== n || n < 1 || n > 12) return null;

  const aug: number[][] = Array.from({ length: n }, (_, i) => {
    const row: number[] = [];
    for (let j = 0; j < n; j += 1) row.push(qMat.data[i * n + j]);
    for (let j = 0; j < n; j += 1) row.push(i === j ? 1 : 0);
    return row;
  });

  for (let col = 0; col < n; col += 1) {
    let pivotRow = col;
    let maxAbs = Math.abs(aug[col][col]);
    for (let r = col + 1; r < n; r += 1) {
      const cand = Math.abs(aug[r][col]);
      if (cand > maxAbs) {
        maxAbs = cand;
        pivotRow = r;
      }
    }
    if (maxAbs <= 1e-13) return null;
    if (pivotRow !== col) {
      const tmp = aug[col];
      aug[col] = aug[pivotRow];
      aug[pivotRow] = tmp;
    }
    const pivot = aug[col][col];
    for (let j = 0; j < 2 * n; j += 1) aug[col][j] /= pivot;
    for (let r = 0; r < n; r += 1) {
      if (r === col) continue;
      const factor = aug[r][col];
      if (factor === 0) continue;
      for (let j = 0; j < 2 * n; j += 1) {
        aug[r][j] -= factor * aug[col][j];
      }
    }
  }

  const kData: number[] = [];
  for (let i = 0; i < m; i += 1) {
    for (let j = 0; j < n; j += 1) {
      let sum = 0;
      for (let k = 0; k < n; k += 1) {
        sum += yMat.data[i * n + k] * aug[k][n + j];
      }
      if (!Number.isFinite(sum)) return null;
      kData.push(sum);
    }
  }
  return { rows: m, cols: n, data: kData };
}

function tensorTo2DArray(t: RealTensor): number[][] {
  const rows = t.shape[0] ?? 1;
  const cols = t.shape[1] ?? 1;
  const out: number[][] = [];
  for (let i = 0; i < rows; i += 1) {
    const r: number[] = [];
    for (let j = 0; j < cols; j += 1) {
      r.push(t.data[i * cols + j] ?? 0);
    }
    out.push(r);
  }
  return out;
}

export function renderLmiViewHtml(): string {
  const templateOptions = LMI_DSL_TEMPLATES.map(
    (tpl) =>
      `<option value="${escapeHtml(tpl.id)}">${escapeHtml(tpl.label)}</option>`,
  ).join("");
  const starterDsl = LMI_DSL_TEMPLATES[0].dsl;

  return [
    `<section id="lmi-workspace-panel" class="panel-card workspace-section" aria-label="LMIs, SDPs e Síntese Robusta" hidden>`,
    `<h3>LMIs, SDPs &amp; Síntese Robusta (ADR-010)</h3>`,
    `<div class="lmi-toolbar subcard">`,
    `<div class="panel-actions lmi-toolbar-row">`,
    `<label for="lmi-template-select">Template</label>`,
    `<select id="lmi-template-select" class="touch-control" aria-label="Selecionar template LMI">${templateOptions}</select>`,
    `<label for="lmi-preset-name">Nome</label>`,
    `<input type="text" id="lmi-preset-name" class="touch-control" value="Condição Lab 1" aria-label="Nome da condição LMI para salvar" />`,
    `<button type="button" id="btn-lmi-save-dsl" class="touch-control btn-secondary" data-action="lmi-save-dsl">Salvar Condição</button>`,
    `<label for="lmi-saved-select">Salvas</label>`,
    `<select id="lmi-saved-select" class="touch-control" aria-label="Carregar condição LMI salva"><option value="">— Sessão vazia —</option></select>`,
    `</div>`,
    `<div class="panel-actions lmi-toolbar-row">`,
    `<button type="button" id="btn-lmi-export-dsl" class="touch-control btn-secondary btn-small" data-action="lmi-export-dsl">Exportar .lmi</button>`,
    `<label for="lmi-import-dsl-input" class="btn-secondary btn-small lmi-import-label">Importar .lmi<input type="file" id="lmi-import-dsl-input" accept=".lmi,.txt,.json" class="touch-control" aria-label="Importar arquivo .lmi passivo" /></label>`,
    `<button type="button" id="btn-lmi-solve" class="touch-control btn-primary" data-action="lmi-solve">Resolver LMI</button>`,
    `<button type="button" id="btn-lmi-verify" class="touch-control btn-secondary" data-action="lmi-verify">Auditar Certificado</button>`,
    `<button type="button" id="btn-lmi-export-cvxpy" class="touch-control btn-secondary" data-action="lmi-export-cvxpy">Exportar CVXPY (.py)</button>`,
    `<button type="button" id="btn-lmi-export-yalmip" class="touch-control btn-secondary" data-action="lmi-export-yalmip">Exportar YALMIP (.m)</button>`,
    `</div>`,
    `</div>`,

    `<div id="lmi-system-characterization-card" class="subcard lmi-sys-card" aria-label="Caracterização do Sistema e Conjuntos de Índices">`,
    `<div class="lmi-sys-head">`,
    `<h4>Caracterização do Sistema &amp; Conjuntos de Índices (Zona 2)</h4>`,
    `<span id="lmi-expanded-blocks-badge" class="badge badge-sufficient">2 blocos LMI expandidos</span>`,
    `</div>`,
    `<div class="lmi-sys-class-row">`,
    `<label for="lmi-sys-class-select">Classe do Sistema</label>`,
    `<select id="lmi-sys-class-select" class="touch-control" aria-label="Classe do sistema na bancada LMI">`,
    `<option value="lti">Linear (LTI Nominal / Planta Generalizada)</option>`,
    `<option value="polytopic">Politópico Incerto (𝒫 = co{Gᵢ})</option>`,
    `<option value="ts">Takagi-Sugeno (TS — Regras &amp; Premissas)</option>`,
    `</select>`,
    `</div>`,

    `<div class="lmi-sys-grid">`,
    `<div class="lmi-sys-col">`,
    `<div id="lmi-sys-panel-lti" class="lmi-sys-mode-panel">`,
    `<div id="lmi-lti-dims-summary" class="lmi-sys-summary"></div>`,
    `<div class="lmi-sys-checks">`,
    `<label class="lmi-check-label"><input type="checkbox" id="lmi-gen-enable-w" class="touch-control" /> Canal exógeno w: Bw, Dyw</label>`,
    `<label class="lmi-check-label"><input type="checkbox" id="lmi-gen-enable-z" class="touch-control" /> Canal desempenho z: Cz, Dzu, Dzw</label>`,
    `</div>`,
    `<div id="lmi-gen-matrices-panel" class="lmi-gen-matrices-panel" hidden>`,
    `<label>Bw <input type="text" id="lmi-gen-bw" class="touch-control" value="[[0],[1]]" aria-label="Matriz Bw" /></label>`,
    `<label>Cz <input type="text" id="lmi-gen-cz" class="touch-control" value="[[1,0],[0,1]]" aria-label="Matriz Cz" /></label>`,
    `<label>Dzu <input type="text" id="lmi-gen-dzu" class="touch-control" value="[[0],[0.1]]" aria-label="Matriz Dzu" /></label>`,
    `<label>Dzw <input type="text" id="lmi-gen-dzw" class="touch-control" value="[[0],[0]]" aria-label="Matriz Dzw" /></label>`,
    `</div>`,
    `</div>`,

    `<div id="lmi-sys-panel-polytopic" class="lmi-sys-mode-panel" hidden>`,
    `<div class="lmi-sys-fields">`,
    `<label>Nº de Vértices N_v <input type="number" id="lmi-poly-vertices-count" class="touch-control" min="2" max="8" value="2" /></label>`,
    `<label>Índice dos vértices na DSL <input type="text" id="lmi-poly-index-name" class="touch-control" value="i" /></label>`,
    `<label>Incerteza ±δ (%) <input type="number" id="lmi-poly-delta" class="touch-control" min="1" max="80" value="15" /></label>`,
    `<button type="button" id="btn-lmi-gen-polytope" class="touch-control btn-secondary btn-small" data-action="lmi-gen-polytope">Gerar Vértices ±δ%</button>`,
    `</div>`,
    `<div id="lmi-poly-vertex-preview" class="lmi-vertex-preview"></div>`,
    `</div>`,

    `<div id="lmi-sys-panel-ts" class="lmi-sys-mode-panel" hidden>`,
    `<div class="lmi-sys-fields">`,
    `<label>Nº de Regras N_r <input type="number" id="lmi-ts-rules-count" class="touch-control" min="2" max="6" value="2" /></label>`,
    `<label>Índice das regras na DSL <input type="text" id="lmi-ts-index-name" class="touch-control" value="i" /></label>`,
    `<button type="button" id="btn-lmi-import-fuzzy" class="touch-control btn-secondary btn-small" data-action="lmi-import-fuzzy">Importar Pertinências da Aba 5</button>`,
    `</div>`,
    `<div id="lmi-ts-mf-summary" class="lmi-ts-mf-summary"></div>`,
    `<div id="lmi-ts-premises-list" class="lmi-ts-premises-list"></div>`,
    `</div>`,
    `</div>`,

    `<div class="lmi-sys-col lmi-sys-indices-col">`,
    `<label for="lmi-extra-indices">Índices adicionais na DSL (ex: j, k)</label>`,
    `<input type="text" id="lmi-extra-indices" class="touch-control" value="j" aria-label="Índices adicionais na DSL" />`,
    `<div id="lmi-sys-indices-summary" class="lmi-sys-summary"></div>`,
    `<button type="button" id="btn-lmi-sync-dsl" class="touch-control btn-secondary btn-small" data-action="lmi-sync-dsl">Sincronizar Diretiva system na DSL</button>`,
    `</div>`,
    `</div>`,
    `</div>`,

    `<div id="lmi-envelope-banner" class="warning-callout" hidden></div>`,
    `<div class="lmi-editor-split">`,
    `<div class="subcard lmi-editor-card">`,
    `<div class="lmi-editor-head">`,
    `<h4>Editor de Condições LMI (Estilo Monaco)</h4>`,
    `<span id="lmi-syntax-badge" class="badge badge-stable">Sintaxe OK</span>`,
    `</div>`,
    `<div class="lmi-monaco-box">`,
    `<pre id="lmi-line-gutter" class="lmi-line-gutter" aria-hidden="true"></pre>`,
    `<textarea id="lmi-code-editor" class="lmi-code-editor touch-control" rows="10" spellcheck="false" aria-label="Editor DSL de condições LMI">${escapeHtml(starterDsl)}</textarea>`,
    `</div>`,
    `</div>`,
    `<div class="subcard lmi-math-card">`,
    `<h4>Leitura Matemática Interpretada</h4>`,
    `<div id="lmi-parsed-vars" class="lmi-parsed-vars"></div>`,
    `<div id="lmi-parsed-math" class="lmi-parsed-math"></div>`,
    `<div id="lmi-parsed-alert" class="lmi-parsed-alert" aria-live="polite"></div>`,
    `</div>`,
    `</div>`,
    `<div class="lmi-results-split">`,
    `<div id="lmi-certificate-panel" class="subcard lmi-certificate-panel" aria-live="polite">`,
    `<h4>Certificado de Auditoria Independente (5 Dimensões — ADR-010)</h4>`,
    `<div id="lmi-certificate-dims" class="lmi-cert-dims-grid"><p>Execute <strong>Resolver LMI</strong> para auditar o problema e gerar o certificado em 5 dimensões, ou exporte scripts CVXPY/YALMIP diretamente.</p></div>`,
    `<div id="lmi-certificate-alert"></div>`,
    `<div id="lmi-recovered-gain" class="lmi-recovered-gain"></div>`,
    `</div>`,
    `<div class="chart-card">`,
    `<div id="lmi-spectrum-chart-slot" class="chart-container"></div>`,
    renderLmiExportBarHtml("lmi-spectrum-chart-slot", "Espectro LMI λ_min(F_b(x*))"),
    `<details><summary>Tabela acessível do espectro de blocos LMI (WCAG 2.2 AA)</summary><div id="lmi-spectrum-table-slot"><p>Sem solução LMI auditada ainda.</p></div></details>`,
    `</div>`,
    `</div>`,
    `</section>`,
  ].join("\n");
}

export class LmiView {
  private readonly shell: ControlLabShell;
  private readonly client: ControlLabEngineClient;
  private readonly container: HTMLElement;
  private readonly onRequestRender?: () => void;
  private readonly onOpenExportModal?: (
    payload: LmiExportModalPayload,
    trigger: HTMLElement | null,
  ) => void;

  private readonly panelEl: HTMLElement | null;
  private readonly templateSelectEl: HTMLSelectElement | null;
  private readonly presetNameEl: HTMLInputElement | null;
  private readonly savedSelectEl: HTMLSelectElement | null;
  private readonly importDslInputEl: HTMLInputElement | null;
  private readonly envelopeBannerEl: HTMLElement | null;
  private readonly syntaxBadgeEl: HTMLElement | null;
  private readonly lineGutterEl: HTMLElement | null;
  private readonly codeEditorEl: HTMLTextAreaElement | null;
  private readonly parsedVarsEl: HTMLElement | null;
  private readonly parsedMathEl: HTMLElement | null;
  private readonly parsedAlertEl: HTMLElement | null;
  private readonly certDimsEl: HTMLElement | null;
  private readonly certAlertEl: HTMLElement | null;
  private readonly recoveredGainEl: HTMLElement | null;
  private readonly spectrumChartSlotEl: HTMLElement | null;
  private readonly spectrumTableSlotEl: HTMLElement | null;

  // Zona 2 DOM references
  private readonly expandedBlocksBadgeEl: HTMLElement | null;
  private readonly sysClassSelectEl: HTMLSelectElement | null;
  private readonly sysPanelLtiEl: HTMLElement | null;
  private readonly sysPanelPolyEl: HTMLElement | null;
  private readonly sysPanelTsEl: HTMLElement | null;
  private readonly ltiDimsSummaryEl: HTMLElement | null;
  private readonly genEnableWEl: HTMLInputElement | null;
  private readonly genEnableZEl: HTMLInputElement | null;
  private readonly genMatricesPanelEl: HTMLElement | null;
  private readonly genBwEl: HTMLInputElement | null;
  private readonly genCzEl: HTMLInputElement | null;
  private readonly genDzuEl: HTMLInputElement | null;
  private readonly genDzwEl: HTMLInputElement | null;
  private readonly polyVerticesCountEl: HTMLInputElement | null;
  private readonly polyIndexNameEl: HTMLInputElement | null;
  private readonly polyDeltaEl: HTMLInputElement | null;
  private readonly polyVertexPreviewEl: HTMLElement | null;
  private readonly tsRulesCountEl: HTMLInputElement | null;
  private readonly tsIndexNameEl: HTMLInputElement | null;
  private readonly tsMfSummaryEl: HTMLElement | null;
  private readonly tsPremisesListEl: HTMLElement | null;
  private readonly extraIndicesEl: HTMLInputElement | null;
  private readonly sysIndicesSummaryEl: HTMLElement | null;

  private currentDsl: string;
  private parsed: LmiDslParseResult;
  private savedPresets: SavedLmiPreset[] = [];
  private lastSolve: LmiSolveSnapshot | null = null;
  private lastBuildPayload: Record<string, unknown> | null = null;
  private sysState: LmiSystemCharacterizationState;

  constructor(options: LmiViewOptions) {
    this.shell = options.shell;
    this.client = options.client;
    this.container = options.container;
    this.onRequestRender = options.onRequestRender;
    this.onOpenExportModal = options.onOpenExportModal;

    this.sysState = {
      systemClass: "lti",
      genEnableW: false,
      genEnableZ: false,
      genBwText: "[[0],[1]]",
      genCzText: "[[1,0],[0,1]]",
      genDzuText: "[[0],[0.1]]",
      genDzwText: "[[0],[0]]",
      polyVerticesCount: 2,
      polyIndexName: "i",
      polyDeltaPct: 15,
      polyVertices: [],
      tsRulesCount: 2,
      tsIndexName: "i",
      tsPremises: [
        { name: "z1 (x1)", measured: true },
        { name: "z2 (x2)", measured: true },
      ],
      tsMfSummary: [
        "h₁(z) = (1 - tanh(z₁))/2",
        "h₂(z) = (1 + tanh(z₁))/2",
      ],
      extraIndices: "j",
    };

    this.currentDsl = LMI_DSL_TEMPLATES[0].dsl;
    this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());

    this.panelEl = this.container.querySelector<HTMLElement>("#lmi-workspace-panel");
    this.templateSelectEl = this.container.querySelector<HTMLSelectElement>("#lmi-template-select");
    this.presetNameEl = this.container.querySelector<HTMLInputElement>("#lmi-preset-name");
    this.savedSelectEl = this.container.querySelector<HTMLSelectElement>("#lmi-saved-select");
    this.importDslInputEl = this.container.querySelector<HTMLInputElement>("#lmi-import-dsl-input");
    this.envelopeBannerEl = this.container.querySelector<HTMLElement>("#lmi-envelope-banner");
    this.syntaxBadgeEl = this.container.querySelector<HTMLElement>("#lmi-syntax-badge");
    this.lineGutterEl = this.container.querySelector<HTMLElement>("#lmi-line-gutter");
    this.codeEditorEl = this.container.querySelector<HTMLTextAreaElement>("#lmi-code-editor");
    this.parsedVarsEl = this.container.querySelector<HTMLElement>("#lmi-parsed-vars");
    this.parsedMathEl = this.container.querySelector<HTMLElement>("#lmi-parsed-math");
    this.parsedAlertEl = this.container.querySelector<HTMLElement>("#lmi-parsed-alert");
    this.certDimsEl = this.container.querySelector<HTMLElement>("#lmi-certificate-dims");
    this.certAlertEl = this.container.querySelector<HTMLElement>("#lmi-certificate-alert");
    this.recoveredGainEl = this.container.querySelector<HTMLElement>("#lmi-recovered-gain");
    this.spectrumChartSlotEl = this.container.querySelector<HTMLElement>("#lmi-spectrum-chart-slot");
    this.spectrumTableSlotEl = this.container.querySelector<HTMLElement>("#lmi-spectrum-table-slot");

    this.expandedBlocksBadgeEl = this.container.querySelector<HTMLElement>("#lmi-expanded-blocks-badge");
    this.sysClassSelectEl = this.container.querySelector<HTMLSelectElement>("#lmi-sys-class-select");
    this.sysPanelLtiEl = this.container.querySelector<HTMLElement>("#lmi-sys-panel-lti");
    this.sysPanelPolyEl = this.container.querySelector<HTMLElement>("#lmi-sys-panel-polytopic");
    this.sysPanelTsEl = this.container.querySelector<HTMLElement>("#lmi-sys-panel-ts");
    this.ltiDimsSummaryEl = this.container.querySelector<HTMLElement>("#lmi-lti-dims-summary");
    this.genEnableWEl = this.container.querySelector<HTMLInputElement>("#lmi-gen-enable-w");
    this.genEnableZEl = this.container.querySelector<HTMLInputElement>("#lmi-gen-enable-z");
    this.genMatricesPanelEl = this.container.querySelector<HTMLElement>("#lmi-gen-matrices-panel");
    this.genBwEl = this.container.querySelector<HTMLInputElement>("#lmi-gen-bw");
    this.genCzEl = this.container.querySelector<HTMLInputElement>("#lmi-gen-cz");
    this.genDzuEl = this.container.querySelector<HTMLInputElement>("#lmi-gen-dzu");
    this.genDzwEl = this.container.querySelector<HTMLInputElement>("#lmi-gen-dzw");
    this.polyVerticesCountEl = this.container.querySelector<HTMLInputElement>("#lmi-poly-vertices-count");
    this.polyIndexNameEl = this.container.querySelector<HTMLInputElement>("#lmi-poly-index-name");
    this.polyDeltaEl = this.container.querySelector<HTMLInputElement>("#lmi-poly-delta");
    this.polyVertexPreviewEl = this.container.querySelector<HTMLElement>("#lmi-poly-vertex-preview");
    this.tsRulesCountEl = this.container.querySelector<HTMLInputElement>("#lmi-ts-rules-count");
    this.tsIndexNameEl = this.container.querySelector<HTMLInputElement>("#lmi-ts-index-name");
    this.tsMfSummaryEl = this.container.querySelector<HTMLElement>("#lmi-ts-mf-summary");
    this.tsPremisesListEl = this.container.querySelector<HTMLElement>("#lmi-ts-premises-list");
    this.extraIndicesEl = this.container.querySelector<HTMLInputElement>("#lmi-extra-indices");
    this.sysIndicesSummaryEl = this.container.querySelector<HTMLElement>("#lmi-sys-indices-summary");

    this.generatePolytopeVertices();
    this.bindEvents();
  }

  private buildParseOptions(): LmiDslParseOptions {
    const systemN =
      this.sysState.systemClass === "polytopic"
        ? this.sysState.polyVerticesCount
        : this.sysState.systemClass === "ts"
          ? this.sysState.tsRulesCount
          : 1;
    const indexName =
      this.sysState.systemClass === "polytopic"
        ? this.sysState.polyIndexName
        : this.sysState.systemClass === "ts"
          ? this.sysState.tsIndexName
          : undefined;
    const extraIndices = this.sysState.extraIndices
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    return {
      systemClass: this.sysState.systemClass,
      systemN,
      indexName,
      extraIndices,
      premisesMeasured: this.sysState.tsPremises.every((p) => p.measured),
      generalized: this.sysState.genEnableW || this.sysState.genEnableZ,
    };
  }

  private syncStateFromParsedSystemSpec(): void {
    const spec = this.parsed.systemSpec;
    if (!spec) return;
    this.sysState.systemClass = spec.systemClass;
    if (spec.systemClass === "polytopic") {
      if (spec.nCount) this.sysState.polyVerticesCount = spec.nCount;
      if (spec.indices[0]) this.sysState.polyIndexName = spec.indices[0];
      if (spec.indices.length > 1) this.sysState.extraIndices = spec.indices.slice(1).join(", ");
      this.generatePolytopeVertices();
    } else if (spec.systemClass === "ts") {
      if (spec.nCount) this.sysState.tsRulesCount = spec.nCount;
      if (spec.indices[0]) this.sysState.tsIndexName = spec.indices[0];
      if (spec.indices.length > 1) this.sysState.extraIndices = spec.indices.slice(1).join(", ");
      if (spec.premises === "measured") {
        this.sysState.tsPremises = this.sysState.tsPremises.map((p) => ({ ...p, measured: true }));
      } else if (spec.premises === "unmeasured") {
        this.sysState.tsPremises = this.sysState.tsPremises.map((p, idx) => ({
          ...p,
          measured: idx === 0 ? false : p.measured,
        }));
      }
    } else {
      if (spec.generalized) {
        this.sysState.genEnableW = true;
        this.sysState.genEnableZ = true;
      }
    }
  }

  private generatePolytopeVertices(): void {
    const plant = this.shell.getLqrWorkspace().getPlant();
    const a2d = tensorTo2DArray(plant.matrices.A);
    const nv = Math.max(2, Math.min(8, this.sysState.polyVerticesCount));
    const delta = Math.max(1, Math.min(80, this.sysState.polyDeltaPct)) / 100;
    const vertices: LmiPolytopeVertexPreview[] = [];
    for (let idx = 0; idx < nv; idx += 1) {
      const frac = nv === 1 ? 0 : -1 + (2 * idx) / (nv - 1);
      const scale = 1 + frac * delta;
      const aVert = a2d.map((row) => row.map((v) => Number((v * scale).toFixed(4))));
      vertices.push({
        index: idx + 1,
        label: `Vértice ${idx + 1} (escala ${(scale * 100).toFixed(0)}%)`,
        aMatrix: aVert,
      });
    }
    this.sysState.polyVertices = vertices;
  }

  private importFuzzyMembershipsFromTab5(): void {
    const typed = this.shell.getTypedWorkspace();
    const fuzzyObjs = typed.listRegisteredObjects(["FuzzySystem"]);
    if (fuzzyObjs.length > 0) {
      const latest = fuzzyObjs[fuzzyObjs.length - 1];
      const inputs = Array.isArray(latest.value.input_variables)
        ? (latest.value.input_variables as Array<{ name?: string; terms?: Array<{ name?: string }> }>)
        : [];
      if (inputs.length > 0) {
        this.sysState.tsPremises = inputs.map((inp, idx) => ({
          name: String(inp.name ?? `z${idx + 1}`),
          measured: true,
        }));
        const mfLines: string[] = [];
        for (const inp of inputs) {
          const termNames = Array.isArray(inp.terms)
            ? inp.terms.map((t) => String(t.name ?? "MF")).join(", ")
            : "N, Z, P";
          mfLines.push(`h(${String(inp.name ?? "z")}): [${termNames}]`);
        }
        this.sysState.tsMfSummary = mfLines;
        const firstTermCount = Array.isArray(inputs[0].terms) ? inputs[0].terms.length : 2;
        this.sysState.tsRulesCount = Math.max(2, Math.min(6, firstTermCount));
      }
    } else {
      this.sysState.tsPremises = [
        { name: "erro (z1)", measured: true },
        { name: "d_erro (z2)", measured: true },
      ];
      this.sysState.tsMfSummary = [
        "h₁(erro): N [-10,-10,0], Z [-5,0,5], P [0,10,10]",
        "h₂(d_erro): N [-10,-10,0], Z [-5,0,5], P [0,10,10]",
      ];
    }
    this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
    this.renderCharacterizationCard();
    this.renderEditorAndMath();
    this.shell
      .getAnnouncer()
      .announce("Pertinências e premissas Takagi-Sugeno importadas da Aba 5.", "polite", "status");
  }

  private syncSystemDirectiveToDsl(): void {
    const cls = this.sysState.systemClass;
    const extra = this.sysState.extraIndices
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    let directive = "";
    if (cls === "lti") {
      const gen = this.sysState.genEnableW || this.sysState.genEnableZ;
      directive = `system lti generalized=${gen ? "true" : "false"}`;
    } else if (cls === "polytopic") {
      const idxAll = [this.sysState.polyIndexName.trim() || "i", ...extra].join(",");
      directive = `system polytopic vertices=${this.sysState.polyVerticesCount} index=${idxAll}`;
    } else {
      const idxAll = [this.sysState.tsIndexName.trim() || "i", ...extra].join(",");
      const allMeasured = this.sysState.tsPremises.every((p) => p.measured);
      directive = `system ts rules=${this.sysState.tsRulesCount} index=${idxAll} premises=${allMeasured ? "measured" : "unmeasured"}`;
    }

    const lines = this.currentDsl.split(/\r?\n/);
    const existingIdx = lines.findIndex((l) => /^\s*system\s+(lti|polytopic|ts)\b/i.test(l));
    if (existingIdx >= 0) {
      lines[existingIdx] = directive;
    } else {
      lines.unshift(directive);
    }
    this.currentDsl = lines.join("\n");
    if (this.codeEditorEl) {
      this.codeEditorEl.value = this.currentDsl;
    }
    this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
    this.renderCharacterizationCard();
    this.renderEditorAndMath();
  }

  private bindEvents(): void {
    const syncFromEditor = (): void => {
      if (!this.codeEditorEl) return;
      this.currentDsl = this.codeEditorEl.value;
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.syncStateFromParsedSystemSpec();
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
    };
    this.codeEditorEl?.addEventListener("input", syncFromEditor);
    this.codeEditorEl?.addEventListener("change", syncFromEditor);

    this.templateSelectEl?.addEventListener("change", () => {
      const tplId = this.templateSelectEl?.value as LmiBackendTemplateId | undefined;
      const found = LMI_DSL_TEMPLATES.find((t) => t.id === tplId);
      if (!found) return;
      this.loadDsl(found.dsl);
    });

    // Zona 2 events
    this.sysClassSelectEl?.addEventListener("change", () => {
      const val = this.sysClassSelectEl?.value;
      if (val === "lti" || val === "polytopic" || val === "ts") {
        this.sysState.systemClass = val;
        if (val === "polytopic") this.generatePolytopeVertices();
        this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
        this.renderCharacterizationCard();
        this.renderEditorAndMath();
      }
    });

    const onGenToggle = (): void => {
      this.sysState.genEnableW = Boolean(this.genEnableWEl?.checked);
      this.sysState.genEnableZ = Boolean(this.genEnableZEl?.checked);
      if (this.genBwEl) this.sysState.genBwText = this.genBwEl.value;
      if (this.genCzEl) this.sysState.genCzText = this.genCzEl.value;
      if (this.genDzuEl) this.sysState.genDzuText = this.genDzuEl.value;
      if (this.genDzwEl) this.sysState.genDzwText = this.genDzwEl.value;
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
    };
    this.genEnableWEl?.addEventListener("change", onGenToggle);
    this.genEnableZEl?.addEventListener("change", onGenToggle);
    this.genBwEl?.addEventListener("change", onGenToggle);
    this.genCzEl?.addEventListener("change", onGenToggle);
    this.genDzuEl?.addEventListener("change", onGenToggle);
    this.genDzwEl?.addEventListener("change", onGenToggle);

    const onPolyChange = (): void => {
      if (this.polyVerticesCountEl) {
        const n = Number(this.polyVerticesCountEl.value);
        if (Number.isFinite(n)) this.sysState.polyVerticesCount = Math.max(2, Math.min(8, Math.round(n)));
      }
      if (this.polyIndexNameEl) {
        const idx = this.polyIndexNameEl.value.trim();
        if (idx) this.sysState.polyIndexName = idx;
      }
      if (this.polyDeltaEl) {
        const d = Number(this.polyDeltaEl.value);
        if (Number.isFinite(d)) this.sysState.polyDeltaPct = Math.max(1, Math.min(80, d));
      }
      this.generatePolytopeVertices();
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
    };
    this.polyVerticesCountEl?.addEventListener("change", onPolyChange);
    this.polyVerticesCountEl?.addEventListener("input", onPolyChange);
    this.polyIndexNameEl?.addEventListener("input", onPolyChange);
    this.polyDeltaEl?.addEventListener("change", onPolyChange);
    this.container
      .querySelector<HTMLElement>('[data-action="lmi-gen-polytope"]')
      ?.addEventListener("click", onPolyChange);

    const onTsChange = (): void => {
      if (this.tsRulesCountEl) {
        const n = Number(this.tsRulesCountEl.value);
        if (Number.isFinite(n)) this.sysState.tsRulesCount = Math.max(2, Math.min(6, Math.round(n)));
      }
      if (this.tsIndexNameEl) {
        const idx = this.tsIndexNameEl.value.trim();
        if (idx) this.sysState.tsIndexName = idx;
      }
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
    };
    this.tsRulesCountEl?.addEventListener("change", onTsChange);
    this.tsRulesCountEl?.addEventListener("input", onTsChange);
    this.tsIndexNameEl?.addEventListener("input", onTsChange);

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-import-fuzzy"]')
      ?.addEventListener("click", () => {
        this.importFuzzyMembershipsFromTab5();
      });

    this.extraIndicesEl?.addEventListener("input", () => {
      if (!this.extraIndicesEl) return;
      this.sysState.extraIndices = this.extraIndicesEl.value;
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
    });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-sync-dsl"]')
      ?.addEventListener("click", () => {
        this.syncSystemDirectiveToDsl();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-save-dsl"]')
      ?.addEventListener("click", () => {
        this.saveCurrentPreset();
      });

    this.savedSelectEl?.addEventListener("change", () => {
      const id = this.savedSelectEl?.value;
      if (!id) return;
      const found = this.savedPresets.find((p) => p.id === id);
      if (found) {
        this.loadDsl(found.dsl);
      }
    });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-export-dsl"]')
      ?.addEventListener("click", (ev) => {
        this.exportPassiveLmiFile(ev.currentTarget as HTMLElement | null);
      });

    this.importDslInputEl?.addEventListener("change", () => {
      const files = (this.importDslInputEl as unknown as { files?: FileList })?.files;
      const file = files?.[0];
      if (!file || typeof file.text !== "function") return;
      void file
        .text()
        .then((txt) => {
          this.loadDsl(txt);
          this.shell.getAnnouncer().announce(`Condição LMI importada de '${file.name}'.`, "polite", "status");
        })
        .catch((err: unknown) => this.shell.presentError(err));
    });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-solve"]')
      ?.addEventListener("click", () => {
        void this.solveLmi();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-verify"]')
      ?.addEventListener("click", () => {
        void this.verifyCertificate();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-export-cvxpy"]')
      ?.addEventListener("click", (ev) => {
        void this.exportScript("cvxpy", ev.currentTarget as HTMLElement | null);
      });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-export-yalmip"]')
      ?.addEventListener("click", (ev) => {
        void this.exportScript("yalmip", ev.currentTarget as HTMLElement | null);
      });
  }

  public loadDsl(dsl: string): void {
    this.currentDsl = dsl;
    if (this.codeEditorEl) {
      this.codeEditorEl.value = dsl;
    }
    this.parsed = parseLmiDsl(dsl, this.buildParseOptions());
    this.syncStateFromParsedSystemSpec();
    this.renderCharacterizationCard();
    this.renderEditorAndMath();
  }

  public saveCurrentPreset(customName?: string): SavedLmiPreset {
    if (this.codeEditorEl && this.codeEditorEl.value !== this.currentDsl) {
      this.currentDsl = this.codeEditorEl.value;
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
    }
    const rawName = (customName ?? this.presetNameEl?.value ?? "").trim();
    const name = rawName || `Condição LMI ${this.savedPresets.length + 1}`;
    const entry: SavedLmiPreset = {
      id: `lmi-preset-${this.savedPresets.length + 1}`,
      name,
      template: this.parsed.inferredTemplate,
      dsl: this.currentDsl,
      savedAt: new Date().toISOString(),
    };
    this.savedPresets.push(entry);
    this.renderSavedSelect(entry.id);
    this.shell.getAnnouncer().announce(`Condição LMI '${name}' salva na sessão.`, "polite", "status");
    return structuredClone(entry);
  }

  public listSavedPresets(): readonly SavedLmiPreset[] {
    return this.savedPresets.map((p) => structuredClone(p));
  }

  public exportPassiveLmiFile(trigger: HTMLElement | null): void {
    const content = [
      `# ControlLab Web — Condição LMI Passiva (.lmi)`,
      `# Template inferido: ${this.parsed.inferredTemplate}`,
      this.currentDsl,
    ].join("\n");
    this.onOpenExportModal?.(
      {
        title: "Arquivo .lmi Passivo",
        filename: `${this.parsed.inferredTemplate || "condicao"}.lmi`,
        mimeType: "text/plain;charset=utf-8",
        content,
        offlineDesign: true,
      },
      trigger,
    );
  }

  private getActivePlantDims(): { n: number; m: number; p: number } {
    const lqrPlant = this.shell.getLqrWorkspace().getPlant();
    const eff = this.shell.getTypedWorkspace().getEffectiveSelection("statespacePlant");
    if (eff && isPlainObject(eff.object.value.matrices)) {
      const mats = eff.object.value.matrices as Record<string, RealTensor>;
      return {
        n: mats.A?.shape?.[0] ?? lqrPlant.matrices.A.shape[0],
        m: mats.B?.shape?.[1] ?? lqrPlant.matrices.B.shape[1],
        p: mats.C?.shape?.[0] ?? lqrPlant.matrices.C.shape[0],
      };
    }
    return {
      n: lqrPlant.matrices.A.shape[0],
      m: lqrPlant.matrices.B.shape[1],
      p: lqrPlant.matrices.C.shape[0],
    };
  }

  private buildQuantifiedExportContext(): LmiQuantifiedExportContext {
    const dims = this.getActivePlantDims();
    return {
      systemClass: this.sysState.systemClass,
      n: dims.n,
      m: dims.m,
      p: dims.p,
      systemN: this.parsed.effectiveSystemN,
      generalized: this.sysState.genEnableW || this.sysState.genEnableZ,
      premisesMeasured: this.sysState.tsPremises.every((p) => p.measured),
    };
  }

  private async buildBackendPayload(): Promise<Record<string, unknown>> {
    if (this.codeEditorEl && this.codeEditorEl.value !== this.currentDsl) {
      this.currentDsl = this.codeEditorEl.value;
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
    }
    if (!this.parsed.valid) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        this.parsed.errors[0]?.message ?? "Corrija os erros de sintaxe na DSL LMI antes de continuar.",
      );
    }
    if (this.parsed.bilinearWarnings.length > 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `${this.parsed.bilinearWarnings[0].message} ${this.parsed.bilinearWarnings[0].suggestion}`,
      );
    }

    const typed = this.shell.getTypedWorkspace();
    const tpl = this.parsed.inferredTemplate;

    if (tpl === "canonical_sdp_json" && this.parsed.canonicalSdpOverride) {
      return { problem: this.parsed.canonicalSdpOverride };
    }

    if (tpl === "hinf_brl" || tpl === "hinf_generalized_brl") {
      const plant = this.shell.getLqrWorkspace().getPlant();
      const A2d = tensorTo2DArray(plant.matrices.A);
      const B2_2d = tensorTo2DArray(plant.matrices.B);
      const C1_default = tensorTo2DArray(plant.matrices.C);
      const n = A2d.length;
      const bwParsed = this.sysState.genEnableW ? parseCompactMatrixJson(this.sysState.genBwText) : null;
      const czParsed = this.sysState.genEnableZ ? parseCompactMatrixJson(this.sysState.genCzText) : null;
      const B1_2d = bwParsed && bwParsed.length === n
        ? bwParsed
        : Array.from({ length: n }, (_, i) => [i === n - 1 ? 1.0 : 0.0]);
      const C1_2d = czParsed && czParsed[0]?.length === n ? czParsed : C1_default;
      const basePayload: Record<string, unknown> = {
        template: "hinf_brl",
        A: makeFloat64Tensor([n, n], A2d.flat()),
        B1: makeFloat64Tensor([n, B1_2d[0].length], B1_2d.flat()),
        B2: makeFloat64Tensor([n, plant.matrices.B.shape[1]], B2_2d.flat()),
        C1: makeFloat64Tensor([C1_2d.length, n], C1_2d.flat()),
        feedback_sign: this.parsed.inferredFeedbackSign,
      };
      if (this.parsed.inferredGamma !== null && this.parsed.inferredGamma > 0) {
        basePayload.gamma = this.parsed.inferredGamma;
      }
      return basePayload;
    }

    const mappedTemplate: LmiBackendTemplateId =
      tpl === "polytopic_robust"
        ? "quadratic_stabilization"
        : tpl === "ts_pdc_relaxed"
          ? "ts_pdc_stabilization"
          : tpl;

    const rawParams: Record<string, unknown> = {
      template: mappedTemplate,
      feedback_sign: this.parsed.inferredFeedbackSign,
    };
    if (this.parsed.inferredAlpha !== null) {
      rawParams.alpha = this.parsed.inferredAlpha;
    }
    if (mappedTemplate === "regional_pole_placement") {
      rawParams.radius = this.parsed.inferredRadius ?? 5.0;
    }
    if (mappedTemplate === "lqr_lmi") {
      const weights = this.shell.getLqrWorkspace().getWeights();
      const dims = this.getActivePlantDims();
      if (weights.Q.shape[0] === dims.n && weights.R.shape[0] === dims.m) {
        rawParams.Q_cost = weights.Q;
        rawParams.R_cost = weights.R;
      }
    }

    const plan = await typed.prepareToolExecution("optimization.solve", rawParams, {
      extraPayload: rawParams,
      feedbackSign: this.parsed.inferredFeedbackSign,
    });
    return { ...rawParams, ...plan.extraPayload };
  }

  private async executeRpc(operation: string, payload: Record<string, unknown>): Promise<RpcResponse> {
    const lqr = this.shell.getLqrWorkspace();
    const projectId = lqr.getProjectId();
    const rev = Math.max(lqr.getProjectRevision(), this.client.getCommittedRevision(projectId));
    return this.client.execute(
      {
        api_version: RPC_API_VERSION,
        request_id: `lmi-${generateUuid()}`,
        project_id: projectId,
        project_revision: rev,
        operation,
        payload,
        options: {},
        timeout_policy: { hard_timeout_ms: 30000 },
      },
      { commitOnSuccess: false },
    );
  }

  private ingestOptimizationResponse(
    operation: string,
    resp: RpcResponse,
    payloadUsed: Record<string, unknown>,
  ): void {
    const res = (isPlainObject(resp.result) ? resp.result : {}) as Record<string, unknown>;
    const diag = (isPlainObject(resp.diagnostics) ? resp.diagnostics : {}) as Record<string, unknown>;
    const condObj = isPlainObject(res.conditioning)
      ? res.conditioning
      : isPlainObject(diag.conditioning)
        ? diag.conditioning
        : {};
    const residualsObj = isPlainObject(res.residuals)
      ? res.residuals
      : isPlainObject(diag.residuals)
        ? diag.residuals
        : {};

    const minEigs = Array.isArray(residualsObj.primal_block_min_eigs)
      ? (residualsObj.primal_block_min_eigs as unknown[]).map((v) => Number(v))
      : [];

    let recoveredK = extractRealTensor2D(res.K);
    if (!recoveredK && isPlainObject(res.variables)) {
      const vars = res.variables as Record<string, unknown>;
      const qMat = extractRealTensor2D(vars.Q);
      const yMat = extractRealTensor2D(vars.Y);
      if (qMat && yMat) {
        recoveredK = formatGainFromQY(qMat, yMat);
      }
    }

    const rawSol: Record<string, unknown> = {};
    for (const k of ["x", "dual_Z", "dual_eq", "dual_ineq", "farkas_Z", "farkas_eq", "farkas_ineq", "objective"]) {
      if (res[k] !== undefined) rawSol[k] = res[k];
    }

    this.lastBuildPayload = payloadUsed;
    this.lastSolve = {
      operation,
      responseStatus: resp.status,
      solverStatus: String(res.solver_status ?? diag.solver_status ?? "unknown"),
      auditFeasibility: String(res.audit_feasibility ?? diag.audit_feasibility ?? "inconclusive"),
      certificateStatus: String(res.certificate_status ?? diag.certificate_status ?? "not_available"),
      conditioningStatus: String(condObj.status ?? "unknown"),
      conditionNumber:
        typeof condObj.condition_number === "number" ? condObj.condition_number : null,
      nearBoundary: Boolean(condObj.near_boundary),
      scalingWarning: Boolean(condObj.scaling_warning),
      controllerValidity: String(res.controller_validity ?? diag.controller_validity ?? "not_assessed"),
      objective:
        typeof res.objective === "number"
          ? res.objective
          : typeof res.primal_objective === "number"
            ? res.primal_objective
            : null,
      offlineRecommended: Boolean(diag.offline_recommended),
      blockMinEigs: minEigs,
      rawSolutionPayload: rawSol,
      recoveredK,
      warnings: resp.warnings.map((w) => (typeof w === "string" ? w : w.message)),
      provenance: resp.provenance as Provenance,
    };
  }

  public async solveLmi(): Promise<void> {
    try {
      const payload = await this.buildBackendPayload();
      const resp = await this.executeRpc("optimization.solve", payload);
      if (resp.status === "failure") {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao resolver LMI.",
        );
      }
      this.ingestOptimizationResponse("optimization.solve", resp, payload);
      this.shell
        .getAnnouncer()
        .announce(
          `LMI resolvida (${this.lastSolve?.solverStatus ?? "concluído"} / ${this.lastSolve?.auditFeasibility ?? ""}).`,
          "polite",
          "status",
        );
      this.renderCertificateAndSpectrum();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async verifyCertificate(): Promise<void> {
    try {
      if (!this.lastSolve) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Resolva o problema LMI antes de auditar o certificado primal/dual.",
        );
      }
      const basePayload = this.lastBuildPayload ?? (await this.buildBackendPayload());
      const verifyPayload: Record<string, unknown> = {
        ...basePayload,
        solution: this.lastSolve.rawSolutionPayload,
        claimed_status: this.lastSolve.solverStatus,
      };
      const resp = await this.executeRpc("optimization.verify", verifyPayload);
      if (resp.status === "failure") {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao auditar certificado SDP.",
        );
      }
      this.ingestOptimizationResponse("optimization.verify", resp, basePayload);
      this.shell
        .getAnnouncer()
        .announce(
          `Auditoria independente concluída: ${this.lastSolve?.certificateStatus ?? "verificado"}.`,
          "polite",
          "status",
        );
      this.renderCertificateAndSpectrum();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async exportScript(
    format: "cvxpy" | "yalmip",
    trigger: HTMLElement | null,
  ): Promise<void> {
    try {
      const hasQuantifiers = this.parsed.constraints.some((c) => Boolean(c.quantifier));
      if (
        hasQuantifiers ||
        this.parsed.systemSpec?.systemClass === "polytopic" ||
        this.parsed.systemSpec?.systemClass === "ts"
      ) {
        const ctx = this.buildQuantifiedExportContext();
        const content =
          format === "cvxpy"
            ? generateQuantifiedCvxpySnippet(this.parsed, ctx)
            : generateQuantifiedYalmipSnippet(this.parsed, ctx);
        const ext = format === "cvxpy" ? "py" : "m";
        this.onOpenExportModal?.(
          {
            title: `Exportação Offline ${format.toUpperCase()} Quantificada (ADR-010)`,
            filename: `${this.parsed.inferredTemplate || "lmi_quantified"}.${ext}`,
            mimeType: "text/plain;charset=utf-8",
            content,
            offlineDesign: true,
          },
          trigger,
        );
        this.shell
          .getAnnouncer()
          .announce(`Script ${format.toUpperCase()} quantificado exportado.`, "polite", "status");
        return;
      }

      const payload = await this.buildBackendPayload();
      const file = await this.shell.exportSdpScript(format, payload);
      this.onOpenExportModal?.(
        {
          title: `Exportação Offline ${format.toUpperCase()} (ADR-010)`,
          filename: file.filename,
          mimeType: file.media_type,
          content: file.script,
          offlineDesign: true,
        },
        trigger,
      );
      this.shell
        .getAnnouncer()
        .announce(`Script ${format.toUpperCase()} exportado com sucesso.`, "polite", "status");
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  private renderSavedSelect(selectedId?: string): void {
    if (!this.savedSelectEl) return;
    if (this.savedPresets.length === 0) {
      this.savedSelectEl.innerHTML = `<option value="">— Sessão vazia —</option>`;
      return;
    }
    this.savedSelectEl.innerHTML = [
      `<option value="">— Carregar salva (${this.savedPresets.length}) —</option>`,
      ...this.savedPresets.map(
        (p) =>
          `<option value="${escapeHtml(p.id)}"${p.id === selectedId ? " selected" : ""}>${escapeHtml(p.name)} (${escapeHtml(p.template)})</option>`,
      ),
    ].join("");
  }

  private renderCharacterizationCard(): void {
    const dims = this.getActivePlantDims();
    if (this.sysClassSelectEl) {
      this.sysClassSelectEl.value = this.sysState.systemClass;
    }

    setElHidden(this.sysPanelLtiEl, this.sysState.systemClass !== "lti");
    setElHidden(this.sysPanelPolyEl, this.sysState.systemClass !== "polytopic");
    setElHidden(this.sysPanelTsEl, this.sysState.systemClass !== "ts");

    if (this.expandedBlocksBadgeEl) {
      const count = this.parsed.expandedBlockCount;
      this.expandedBlocksBadgeEl.textContent = `${count} bloco${count === 1 ? "" : "s"} LMI expandido${count === 1 ? "" : "s"}`;
    }

    if (this.ltiDimsSummaryEl) {
      const plant = this.shell.getLqrWorkspace().getPlant();
      const domainLabel = plant.dt === null ? "Contínuo (ẋ = Ax + Bu)" : `Discreto (dt=${plant.dt}s)`;
      this.ltiDimsSummaryEl.innerHTML = `<strong>Planta ativa (${escapeHtml(domainLabel)}):</strong> A (${dims.n}×${dims.n}), B (${dims.n}×${dims.m}), C (${dims.p}×${dims.n}), D (${dims.p}×${dims.m})`;
    }

    if (this.genEnableWEl) this.genEnableWEl.checked = this.sysState.genEnableW;
    if (this.genEnableZEl) this.genEnableZEl.checked = this.sysState.genEnableZ;
    setElHidden(
      this.genMatricesPanelEl,
      !(this.sysState.genEnableW || this.sysState.genEnableZ),
    );

    if (this.polyVerticesCountEl) this.polyVerticesCountEl.value = String(this.sysState.polyVerticesCount);
    if (this.polyIndexNameEl) this.polyIndexNameEl.value = this.sysState.polyIndexName;
    if (this.polyDeltaEl) this.polyDeltaEl.value = String(this.sysState.polyDeltaPct);
    if (this.polyVertexPreviewEl) {
      const chips = this.sysState.polyVertices.map(
        (v) =>
          `<div class="lmi-vertex-chip"><strong>A<sub>${v.index}</sub></strong> (${escapeHtml(v.label)}): <code>${escapeHtml(JSON.stringify(v.aMatrix))}</code></div>`,
      );
      this.polyVertexPreviewEl.innerHTML = chips.join("");
    }

    if (this.tsRulesCountEl) this.tsRulesCountEl.value = String(this.sysState.tsRulesCount);
    if (this.tsIndexNameEl) this.tsIndexNameEl.value = this.sysState.tsIndexName;
    if (this.tsMfSummaryEl) {
      this.tsMfSummaryEl.innerHTML = this.sysState.tsMfSummary
        .map((line) => `<span class="badge">${escapeHtml(line)}</span>`)
        .join(" ");
    }
    if (this.tsPremisesListEl) {
      const anyUnmeasured = this.sysState.tsPremises.some((p) => !p.measured);
      const rows = this.sysState.tsPremises.map((p, idx) => {
        const cls = p.measured ? "badge-stable" : "badge-beta";
        const label = p.measured ? "Medida" : "Não Medida (Estimada)";
        return `<div class="lmi-premise-row"><span>Premissa <strong>${escapeHtml(p.name)}</strong></span><button type="button" class="touch-control btn-small btn-secondary ${cls}" data-action="lmi-toggle-premise" data-premise-idx="${idx}">${escapeHtml(label)}</button></div>`;
      });
      if (anyUnmeasured) {
        rows.push(
          `<div class="warning-callout" role="status"><strong>ts_partially_observed:</strong> Há premissas não medidas (ẑ). Utilize observador TS ou termos de acoplamento Lipschitz γ_L na DSL.</div>`,
        );
      }
      this.tsPremisesListEl.innerHTML = rows.join("");
      const toggleBtns = Array.from(this.tsPremisesListEl.querySelectorAll<HTMLElement>('[data-action="lmi-toggle-premise"]'));
      for (const btn of toggleBtns) {
        btn.addEventListener("click", () => {
          const idx = Number(btn.getAttribute("data-premise-idx"));
          if (!Number.isInteger(idx) || idx < 0 || idx >= this.sysState.tsPremises.length) return;
          this.sysState.tsPremises[idx].measured = !this.sysState.tsPremises[idx].measured;
          this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
          this.renderCharacterizationCard();
          this.renderEditorAndMath();
        });
      }
    }

    if (this.extraIndicesEl && this.extraIndicesEl.value !== this.sysState.extraIndices) {
      this.extraIndicesEl.value = this.sysState.extraIndices;
    }
    if (this.sysIndicesSummaryEl) {
      const primary =
        this.sysState.systemClass === "polytopic"
          ? this.sysState.polyIndexName
          : this.sysState.systemClass === "ts"
            ? this.sysState.tsIndexName
            : null;
      const extras = this.sysState.extraIndices
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const all = primary ? [primary, ...extras] : extras;
      const N = this.parsed.effectiveSystemN;
      this.sysIndicesSummaryEl.innerHTML = all.length > 0
        ? `<strong>Índices na DSL:</strong> ${escapeHtml(all.join(", "))} ∈ {1..${N}}`
        : `<strong>Modo LTI:</strong> Sem índice obrigatório (adicione se necessário).`;
    }
  }

  private renderEditorAndMath(): void {
    const dims = this.getActivePlantDims();
    if (this.envelopeBannerEl) {
      if (dims.n > 12 || this.parsed.expandedBlockCount > 32) {
        setElHidden(this.envelopeBannerEl, false);
        this.envelopeBannerEl.innerHTML = `<strong>Limite do motor navegador (ADR-010):</strong> Planta com n=${dims.n} estados e ${this.parsed.expandedBlockCount} bloco(s) LMI. Recomenda-se usar <strong>Exportar CVXPY / YALMIP</strong> para execução offline com MOSEK/SCS.`;
      } else {
        setElHidden(this.envelopeBannerEl, true);
        this.envelopeBannerEl.innerHTML = "";
      }
    }

    if (this.lineGutterEl) {
      const lines = Array.from({ length: this.parsed.lineCount }, (_, i) => String(i + 1)).join("\n");
      this.lineGutterEl.textContent = lines;
    }

    if (this.syntaxBadgeEl) {
      if (!this.parsed.valid) {
        this.syntaxBadgeEl.className = "badge badge-experimental";
        this.syntaxBadgeEl.textContent = "Erro de Sintaxe";
      } else if (this.parsed.bilinearWarnings.length > 0) {
        this.syntaxBadgeEl.className = "badge badge-beta";
        this.syntaxBadgeEl.textContent = "Aviso Bilinear (BMI)";
      } else {
        this.syntaxBadgeEl.className = "badge badge-stable";
        this.syntaxBadgeEl.textContent = "Sintaxe OK";
      }
    }

    if (this.parsedVarsEl) {
      const sysChip = this.parsed.systemSpec
        ? `<span class="badge badge-stable">Sistema: ${escapeHtml(this.parsed.systemSpec.systemClass)} (N=${this.parsed.effectiveSystemN})</span>`
        : `<span class="badge">Sistema: ${escapeHtml(this.sysState.systemClass)} (N=${this.parsed.effectiveSystemN})</span>`;
      const varChips = this.parsed.variables.map(
        (v) =>
          `<span class="badge badge-sufficient">var ${escapeHtml(v.name)}: ${escapeHtml(resolveShapeLabel(v, dims))}</span>`,
      );
      const paramChips = this.parsed.params.map(
        (p) =>
          `<span class="badge">param ${escapeHtml(p.name === "alpha" ? "α" : p.name === "gamma" ? "γ" : p.name)} = ${p.value}</span>`,
      );
      const tplChip = `<span class="badge">Template: ${escapeHtml(this.parsed.inferredTemplate)}</span>`;
      const blkChip = `<span class="badge badge-sufficient">${this.parsed.expandedBlockCount} bloco(s) LMI</span>`;
      this.parsedVarsEl.innerHTML = [sysChip, ...varChips, ...paramChips, tplChip, blkChip].join(" ");
    }

    if (this.parsedMathEl) {
      const blocks: string[] = [];
      if (this.parsed.objective) {
        blocks.push(
          `<div class="lmi-math-row"><strong>Objetivo:</strong> <code>${escapeHtml(this.parsed.objective.mathText)}</code></div>`,
        );
      }
      for (const c of this.parsed.constraints) {
        blocks.push(
          `<div class="lmi-math-row"><span class="lmi-math-idx">(${c.index})</span> ${c.mathHtml}</div>`,
        );
      }
      for (const rec of this.parsed.recoveries) {
        blocks.push(
          `<div class="lmi-math-row lmi-math-recovery"><code>${escapeHtml(rec.mathText)}</code></div>`,
        );
      }
      this.parsedMathEl.innerHTML =
        blocks.length > 0 ? blocks.join("") : `<p>Nenhuma restrição LMI interpretada.</p>`;
    }

    if (this.parsedAlertEl) {
      const alertParts: string[] = [];
      for (const w of this.parsed.bilinearWarnings) {
        alertParts.push(
          `<div class="warning-callout" role="alert"><strong>Não-linearidade / BMI:</strong> ${escapeHtml(w.message)}<br /><em>Sugestão:</em> ${escapeHtml(w.suggestion)}</div>`,
        );
      }
      for (const err of this.parsed.errors) {
        alertParts.push(
          `<div class="maturity-banner unavailable" role="alert">Linha ${err.line}: ${escapeHtml(err.message)}</div>`,
        );
      }
      for (const note of this.parsed.strictConeNotes) {
        alertParts.push(`<p class="json-format-hint">${escapeHtml(note)}</p>`);
      }
      this.parsedAlertEl.innerHTML = alertParts.join("");
    }
  }

  private renderCertificateAndSpectrum(): void {
    const decimals = this.shell.getDisplayDecimals();
    if (!this.lastSolve) {
      if (this.certDimsEl) {
        this.certDimsEl.innerHTML = `<p>Execute <strong>Resolver LMI</strong> para auditar o problema e gerar o certificado em 5 dimensões, ou exporte scripts CVXPY/YALMIP diretamente.</p>`;
      }
      if (this.certAlertEl) this.certAlertEl.innerHTML = "";
      if (this.recoveredGainEl) this.recoveredGainEl.innerHTML = "";
      if (this.spectrumChartSlotEl) this.spectrumChartSlotEl.innerHTML = "";
      if (this.spectrumTableSlotEl) {
        this.spectrumTableSlotEl.innerHTML = `<p>Sem solução LMI auditada ainda.</p>`;
      }
      return;
    }

    const s = this.lastSolve;
    const solverCls =
      s.solverStatus === "optimal"
        ? "badge-stable"
        : s.solverStatus === "optimal_inaccurate"
          ? "badge-beta"
          : "badge-experimental";
    const auditCls =
      s.auditFeasibility === "strictly_feasible"
        ? "badge-stable"
        : s.auditFeasibility === "approximately_feasible"
          ? "badge-beta"
          : "badge-experimental";
    const certCls =
      s.certificateStatus === "validated_dual"
        ? "badge-stable"
        : s.certificateStatus === "validated_primal"
          ? "badge-beta"
          : "badge-experimental";
    const condCls =
      s.conditioningStatus === "well_conditioned" && !s.scalingWarning
        ? "badge-stable"
        : "badge-beta";
    const ctrlCls = s.controllerValidity.startsWith("verified")
      ? "badge-stable"
      : s.controllerValidity === "violated"
        ? "badge-experimental"
        : "badge-beta";

    const kappaStr =
      s.conditionNumber !== null
        ? formatNumericDisplay(s.conditionNumber, decimals)
        : "N/D";

    if (this.certDimsEl) {
      this.certDimsEl.innerHTML = [
        `<div class="lmi-cert-dim"><span class="kpi-label">1. Solver Status</span><span class="badge ${solverCls}">${escapeHtml(s.solverStatus)}</span></div>`,
        `<div class="lmi-cert-dim"><span class="kpi-label">2. Auditoria Factibilidade</span><span class="badge ${auditCls}">${escapeHtml(s.auditFeasibility)}</span></div>`,
        `<div class="lmi-cert-dim"><span class="kpi-label">3. Certificado Dual</span><span class="badge ${certCls}">${escapeHtml(s.certificateStatus)}</span></div>`,
        `<div class="lmi-cert-dim"><span class="kpi-label">4. Condicionamento κ</span><span class="badge ${condCls}">${escapeHtml(s.conditioningStatus)} (κ=${escapeHtml(kappaStr)})</span></div>`,
        `<div class="lmi-cert-dim"><span class="kpi-label">5. Validade Controlador</span><span class="badge ${ctrlCls}">${escapeHtml(s.controllerValidity)}</span></div>`,
      ].join("");
    }

    if (this.certAlertEl) {
      const alerts: string[] = [];
      const diverges =
        s.solverStatus === "optimal" &&
        s.auditFeasibility !== "strictly_feasible" &&
        s.auditFeasibility !== "approximately_feasible";
      if (diverges || s.responseStatus === "inconclusive" || s.offlineRecommended) {
        alerts.push(
          `<div class="warning-callout" role="alert"><strong>Recomendação ADR-010:</strong> ${diverges ? "O status do solver diverge da auditoria independente. " : ""}Verifique condicionamento/resíduos ou utilize <strong>Exportar CVXPY / YALMIP</strong> para rodar em solver externo (MOSEK/Clarabel/SDPT3).</div>`,
        );
      }
      if (s.warnings.length > 0) {
        alerts.push(
          `<p class="json-format-hint">${s.warnings.map((w) => escapeHtml(w)).join(" | ")}</p>`,
        );
      }
      this.certAlertEl.innerHTML = alerts.join("");
    }

    if (this.recoveredGainEl) {
      const kFormatted = s.recoveredK
        ? formatMatrixDisplay(s.recoveredK.data, s.recoveredK.rows, s.recoveredK.cols, decimals)
            .map((r) => `[${r.join(", ")}]`)
            .join("; ")
        : null;
      const kHtml = kFormatted
        ? `<strong>Ganho recuperado K = Y Q⁻¹:</strong> <code>${escapeHtml(kFormatted)}</code>`
        : `<strong>Ganho K:</strong> N/D para esta formulação`;
      const objHtml =
        s.objective !== null
          ? ` | <strong>Objetivo:</strong> <code>${formatNumericDisplay(s.objective, decimals)}</code>`
          : "";
      this.recoveredGainEl.innerHTML = `<p>${kHtml}${objHtml}</p>`;
    }

    const themeMode = this.shell.getThemeMode();
    if (s.blockMinEigs.length > 0) {
      const specModel: LmiSpectrumChartModel = buildLmiSpectrumChartModel({
        block_min_eigs: s.blockMinEigs,
        alpha: this.parsed.inferredAlpha,
        model_revision: this.shell.getLqrWorkspace().getPlant().revision,
        project_revision: this.shell.getLqrWorkspace().getProjectRevision(),
        provenance: s.provenance,
        theme_mode: themeMode,
      });
      if (this.spectrumChartSlotEl) {
        this.spectrumChartSlotEl.innerHTML = renderLmiSpectrumSvg(specModel, { decimals, themeMode });
      }
      if (this.spectrumTableSlotEl) {
        const table = buildAccessibleChartTable(specModel, decimals);
        this.spectrumTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
      }
    } else {
      if (this.spectrumChartSlotEl) this.spectrumChartSlotEl.innerHTML = "";
      if (this.spectrumTableSlotEl) {
        this.spectrumTableSlotEl.innerHTML = `<p>Sem blocos PSD auditados nesta resposta.</p>`;
      }
    }
  }

  public render(): void {
    const isLmi = this.shell.getActiveTab() === "optimization_lmi";
    setElHidden(this.panelEl, !isLmi);
    if (!isLmi) return;

    this.renderCharacterizationCard();
    this.renderEditorAndMath();
    this.renderCertificateAndSpectrum();
  }
}
