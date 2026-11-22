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
  type SolverProgress,
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
import {
  compileLmiDslToCanonicalSdp,
  type LmiCompileContext,
  type LmiDeltaVertexMatrices,
  type LmiVertexMatrices,
} from "./lmi_dsl_compiler.ts";
import { validateConvexMembershipFunctions } from "./lmi_ts_mf_eval.ts";

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
  min: number;
  max: number;
  measured: boolean;
}

export interface LmiTsMembershipRow {
  id: string;
  expression: string;
}

export interface LmiPolytopeVertexPreview {
  index: number;
  label: string;
  aMatrix: number[][];
  bMatrix: number[][];
  cMatrix: number[][];
  dMatrix: number[][];
  aText?: string;
  bText?: string;
  cText?: string;
  dText?: string;
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
  tsVertices: LmiPolytopeVertexPreview[];
  tsPremises: LmiPremiseVarState[];
  tsMemberships: LmiTsMembershipRow[];
  tsMfSummary: string[];
  tsObsMethod: "dmvt_nonlinearity" | "gradient_factorization";
  tsObsDaText: string;
  tsObsDcText: string;
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
  recoveredIndexedK?: Array<{ label: string; mat: { rows: number; cols: number; data: number[] } }>;
  recoveredIndexedL?: Array<{ label: string; mat: { rows: number; cols: number; data: number[] } }>;
  recoveredScalars?: Array<{ name: string; value: number }>;
  warnings: string[];
  provenance: Provenance | null;
  iterationLog: SolverProgress[];
}

export const BROWSER_ENVELOPE = {
  max_variables: 448,
  max_block_dimension: 64,
  max_cone_entries: 32768,
} as const;

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function toggleCssClass(
  el: Element | null | undefined,
  className: string,
  active: boolean,
): void {
  if (!el) return;
  const raw = el.getAttribute("class") ?? "";
  const tokens = raw.split(/\s+/).filter(Boolean);
  const idx = tokens.indexOf(className);
  if (active && idx < 0) tokens.push(className);
  else if (!active && idx >= 0) tokens.splice(idx, 1);
  el.setAttribute("class", tokens.join(" "));
}

function isValidMatrix2D(mat: number[][] | null): mat is number[][] {
  if (!mat || mat.length === 0 || mat[0].length === 0) return false;
  const cols = mat[0].length;
  return mat.every(
    (row) => row.length === cols && row.every((val) => Number.isFinite(val)),
  );
}

function cloneMatrix2D(mat: number[][]): number[][] {
  return mat.map((row) => [...row]);
}

function sanitizeMatrix2D(raw: unknown, fallback: number[][]): number[][] {
  if (!Array.isArray(raw) || raw.length === 0) return cloneMatrix2D(fallback);
  const rows: number[][] = [];
  let cols = -1;
  for (const r of raw) {
    if (!Array.isArray(r) || r.length === 0) return cloneMatrix2D(fallback);
    if (cols === -1) cols = r.length;
    else if (r.length !== cols) return cloneMatrix2D(fallback);
    const numRow: number[] = [];
    for (const v of r) {
      const n = Number(v);
      if (!Number.isFinite(n)) return cloneMatrix2D(fallback);
      numRow.push(n);
    }
    rows.push(numRow);
  }
  return rows;
}

function sanitizeVertexList(raw: unknown): LmiPolytopeVertexPreview[] {
  if (!Array.isArray(raw)) return [];
  const out: LmiPolytopeVertexPreview[] = [];
  for (let i = 0; i < raw.length; i += 1) {
    const item = raw[i];
    if (!isPlainObject(item)) continue;
    const index =
      typeof item.index === "number" && Number.isInteger(item.index) && item.index >= 1
        ? item.index
        : i + 1;
    const label = typeof item.label === "string" ? item.label : `Vértice ${index}`;
    const entry: LmiPolytopeVertexPreview = {
      index,
      label,
      aMatrix: sanitizeMatrix2D(item.aMatrix, [[0]]),
      bMatrix: sanitizeMatrix2D(item.bMatrix, [[0]]),
      cMatrix: sanitizeMatrix2D(item.cMatrix, [[1]]),
      dMatrix: sanitizeMatrix2D(item.dMatrix, [[0]]),
    };
    if (typeof item.aText === "string") entry.aText = item.aText;
    if (typeof item.bText === "string") entry.bText = item.bText;
    if (typeof item.cText === "string") entry.cText = item.cText;
    if (typeof item.dText === "string") entry.dText = item.dText;
    out.push(entry);
  }
  return out;
}

function formatSubscript(num: number): string {
  const digits = ["₀", "₁", "₂", "₃", "₄", "₅", "₆", "₇", "₈", "₉"];
  return String(num)
    .split("")
    .map((ch) => digits[Number(ch)] ?? ch)
    .join("");
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

function parseDeltaMatrixListJson(text: string): number[][][] | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    const mats: number[][][] = [];
    for (const item of parsed) {
      if (!Array.isArray(item) || item.length === 0 || !Array.isArray(item[0])) {
        return null;
      }
      mats.push((item as unknown[][]).map((row) => row.map((v) => Number(v))));
    }
    return mats;
  } catch {
    return null;
  }
}

function invertMatrix(
  mat: { rows: number; cols: number; data: number[] },
): { rows: number; cols: number; data: number[] } | null {
  const n = mat.rows;
  if (n !== mat.cols || n < 1 || n > 16) return null;
  const aug: number[][] = Array.from({ length: n }, (_, i) => {
    const row: number[] = [];
    for (let j = 0; j < n; j += 1) row.push(mat.data[i * n + j]);
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

  const invData: number[] = [];
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < n; j += 1) {
      const v = aug[i][n + j];
      if (!Number.isFinite(v)) return null;
      invData.push(v);
    }
  }
  return { rows: n, cols: n, data: invData };
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
  if (n !== qMat.cols || yMat.cols !== n || n < 1 || n > 16) return null;
  const qInv = invertMatrix(qMat);
  if (!qInv) return null;

  const kData: number[] = [];
  for (let i = 0; i < m; i += 1) {
    for (let j = 0; j < n; j += 1) {
      let sum = 0;
      for (let k = 0; k < n; k += 1) {
        sum += yMat.data[i * n + k] * qInv.data[k * n + j];
      }
      if (!Number.isFinite(sum)) return null;
      kData.push(sum);
    }
  }
  return { rows: m, cols: n, data: kData };
}

/**
 * Formata ganho do observador L = P^{-1} * N apenas para exibição visual quando `result.variables` traz `P` e `N[i]`.
 */
function formatObserverGainFromPN(
  pMat: { rows: number; cols: number; data: number[] },
  nMat: { rows: number; cols: number; data: number[] },
): { rows: number; cols: number; data: number[] } | null {
  const n = pMat.rows;
  const p = nMat.cols;
  if (n !== pMat.cols || nMat.rows !== n || n < 1 || n > 16) return null;
  const pInv = invertMatrix(pMat);
  if (!pInv) return null;

  const lData: number[] = [];
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < p; j += 1) {
      let sum = 0;
      for (let k = 0; k < n; k += 1) {
        sum += pInv.data[i * n + k] * nMat.data[k * p + j];
      }
      if (!Number.isFinite(sum)) return null;
      lData.push(sum);
    }
  }
  return { rows: n, cols: p, data: lData };
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
    `</div>`,
    `<div class="lmi-ts-premises-section">`,
    `<div class="lmi-ts-mf-header">`,
    `<strong>Premissas e Universo de Discurso (Ω)</strong>`,
    `<button type="button" id="btn-lmi-add-ts-premise" class="touch-control btn-secondary btn-small" data-action="lmi-add-ts-premise">+ Adicionar Premissa</button>`,
    `</div>`,
    `<div id="lmi-ts-premises-list" class="lmi-ts-premises-list"></div>`,
    `</div>`,
    `<div id="lmi-ts-mf-editor" class="lmi-ts-mf-editor">`,
    `<div class="lmi-ts-mf-header">`,
    `<strong>Funções de Ponderação Convexa (Setor Não Linear h_i(z))</strong>`,
    `<button type="button" id="btn-lmi-add-ts-mf" class="touch-control btn-secondary btn-small" data-action="lmi-add-ts-mf">+ Adicionar Função h_i(z)</button>`,
    `</div>`,
    `<div id="lmi-ts-mf-rows" class="lmi-ts-mf-rows"></div>`,
    `<div id="lmi-ts-mf-validation" class="lmi-ts-mf-validation" role="status" aria-live="polite"></div>`,
    `</div>`,
    `<div id="lmi-ts-mf-summary" class="lmi-ts-mf-summary"></div>`,
    `<div id="lmi-ts-vertex-editor" class="lmi-vertex-preview"></div>`,
    `<div id="lmi-ts-unmeasured-panel" class="subcard lmi-ts-unmeasured-panel" hidden>`,
    `<h5>Observador TS com Premissas Não Medidas (DMVT / Gradiente)</h5>`,
    `<div class="lmi-sys-fields">`,
    `<label>Método de Linearização <select id="lmi-ts-obs-method" class="touch-control" aria-label="Método de linearização para premissas não medidas"><option value="dmvt_nonlinearity">DMVT Direto nas Não-Linearidades (f(x), h(x))</option><option value="gradient_factorization">Fatoração Algébrica Exata do Gradiente (FSS 2020)</option></select></label>`,
    `<label>Vértices de Perturbação dA[k] <input type="text" id="lmi-ts-obs-da" class="touch-control" value="[[[0, 0.2], [0, 0]], [[0, -0.2], [0, 0]]]" aria-label="Vértices de perturbação dA" /></label>`,
    `<label>Vértices de Perturbação dC[k] (opcional) <input type="text" id="lmi-ts-obs-dc" class="touch-control" value="" placeholder="[[[0, 0]], [[0, 0]]]" aria-label="Vértices de perturbação dC" /></label>`,
    `<button type="button" id="btn-lmi-generate-ts-observer" class="touch-control btn-secondary btn-small" data-action="lmi-generate-ts-observer">Gerar DSL do Observador TS</button>`,
    `</div>`,
    `</div>`,
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
    `<div id="lmi-solver-progress-panel" class="lmi-solver-progress-panel">`,
    `<details id="lmi-solver-progress-details" open>`,
    `<summary>Progresso do Solver Primal-Dual (Iterações)</summary>`,
    `<div id="lmi-solver-progress-status" class="lmi-solver-progress-status" aria-live="polite">Aguardando execução.</div>`,
    `<div class="lmi-progress-wrap">`,
    `<table id="lmi-solver-progress-table" class="accessible-data-table lmi-progress-table">`,
    `<thead><tr><th scope="col">Iter</th><th scope="col">Gap</th><th scope="col">Res. Primal</th><th scope="col">Res. Dual</th><th scope="col">λ_min</th><th scope="col">Tempo (ms)</th></tr></thead>`,
    `<tbody id="lmi-solver-progress-tbody"></tbody>`,
    `</table>`,
    `</div>`,
    `</details>`,
    `</div>`,
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
  private readonly progressStatusEl: HTMLElement | null;
  private readonly progressTbodyEl: HTMLElement | null;
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
  private readonly tsMfEditorEl: HTMLElement | null;
  private readonly tsMfRowsEl: HTMLElement | null;
  private readonly tsMfValidationEl: HTMLElement | null;
  private readonly tsMfSummaryEl: HTMLElement | null;
  private readonly tsPremisesListEl: HTMLElement | null;
  private readonly tsVertexEditorEl: HTMLElement | null;
  private readonly tsUnmeasuredPanelEl: HTMLElement | null;
  private readonly tsObsMethodEl: HTMLSelectElement | null;
  private readonly tsObsDaEl: HTMLInputElement | null;
  private readonly tsObsDcEl: HTMLInputElement | null;
  private readonly extraIndicesEl: HTMLInputElement | null;
  private readonly sysIndicesSummaryEl: HTMLElement | null;

  private currentDsl: string;
  private parsed: LmiDslParseResult;
  private savedPresets: SavedLmiPreset[] = [];
  private lastSolve: LmiSolveSnapshot | null = null;
  private lastBuildPayload: Record<string, unknown> | null = null;
  private liveIterations: SolverProgress[] = [];
  private sysState: LmiSystemCharacterizationState;
  private mfIdCounter = 2;

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
      tsVertices: [],
      tsPremises: [
        { name: "z1", min: -1, max: 1, measured: true },
      ],
      tsMemberships: [
        {
          id: "mf-1",
          expression: "(1 + sin(z1)) / 2",
        },
        {
          id: "mf-2",
          expression: "(1 - sin(z1)) / 2",
        },
      ],
      tsMfSummary: [
        "h₁(z) = (1 + sin(z1)) / 2",
        "h₂(z) = (1 - sin(z1)) / 2",
      ],
      tsObsMethod: "dmvt_nonlinearity",
      tsObsDaText: "[[[0, 0.2], [0, 0]], [[0, -0.2], [0, 0]]]",
      tsObsDcText: "",
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
    this.progressStatusEl = this.container.querySelector<HTMLElement>("#lmi-solver-progress-status");
    this.progressTbodyEl = this.container.querySelector<HTMLElement>("#lmi-solver-progress-tbody");
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
    this.tsMfEditorEl = this.container.querySelector<HTMLElement>("#lmi-ts-mf-editor");
    this.tsMfRowsEl = this.container.querySelector<HTMLElement>("#lmi-ts-mf-rows");
    this.tsMfValidationEl = this.container.querySelector<HTMLElement>("#lmi-ts-mf-validation");
    this.tsMfSummaryEl = this.container.querySelector<HTMLElement>("#lmi-ts-mf-summary");
    this.tsPremisesListEl = this.container.querySelector<HTMLElement>("#lmi-ts-premises-list");
    this.tsVertexEditorEl = this.container.querySelector<HTMLElement>("#lmi-ts-vertex-editor");
    this.tsUnmeasuredPanelEl = this.container.querySelector<HTMLElement>("#lmi-ts-unmeasured-panel");
    this.tsObsMethodEl = this.container.querySelector<HTMLSelectElement>("#lmi-ts-obs-method");
    this.tsObsDaEl = this.container.querySelector<HTMLInputElement>("#lmi-ts-obs-da");
    this.tsObsDcEl = this.container.querySelector<HTMLInputElement>("#lmi-ts-obs-dc");
    this.extraIndicesEl = this.container.querySelector<HTMLInputElement>("#lmi-extra-indices");
    this.sysIndicesSummaryEl = this.container.querySelector<HTMLElement>("#lmi-sys-indices-summary");

    this.syncTsFromMemberships();
    this.generatePolytopeVertices();
    this.resizeTsVertices();
    this.bindEvents();
    this.shell.registerLmiPersistence(
      () => this.exportSerializableState(),
      (state) => this.restoreSerializableState(state),
    );
  }

  public exportSerializableState(): Record<string, unknown> {
    if (this.codeEditorEl && this.codeEditorEl.value !== this.currentDsl) {
      this.currentDsl = this.codeEditorEl.value;
    }
    return {
      sysState: {
        systemClass: this.sysState.systemClass,
        genEnableW: this.sysState.genEnableW,
        genEnableZ: this.sysState.genEnableZ,
        genBwText: this.sysState.genBwText,
        genCzText: this.sysState.genCzText,
        genDzuText: this.sysState.genDzuText,
        genDzwText: this.sysState.genDzwText,
        polyVerticesCount: this.sysState.polyVerticesCount,
        polyIndexName: this.sysState.polyIndexName,
        polyDeltaPct: this.sysState.polyDeltaPct,
        polyVertices: structuredClone(this.sysState.polyVertices),
        tsRulesCount: this.sysState.tsRulesCount,
        tsIndexName: this.sysState.tsIndexName,
        tsPremises: structuredClone(this.sysState.tsPremises),
        tsMemberships: structuredClone(this.sysState.tsMemberships),
        tsVertices: structuredClone(this.sysState.tsVertices),
        tsObsMethod: this.sysState.tsObsMethod,
        tsObsDaText: this.sysState.tsObsDaText,
        tsObsDcText: this.sysState.tsObsDcText,
        extraIndices: this.sysState.extraIndices,
      },
      currentDsl: this.currentDsl,
    };
  }

  public restoreSerializableState(raw: unknown): void {
    if (!isPlainObject(raw)) return;

    if (isPlainObject(raw.sysState)) {
      const s = raw.sysState;
      if (s.systemClass === "lti" || s.systemClass === "polytopic" || s.systemClass === "ts") {
        this.sysState.systemClass = s.systemClass;
      }
      if (typeof s.genEnableW === "boolean") this.sysState.genEnableW = s.genEnableW;
      if (typeof s.genEnableZ === "boolean") this.sysState.genEnableZ = s.genEnableZ;
      if (typeof s.genBwText === "string") this.sysState.genBwText = s.genBwText;
      if (typeof s.genCzText === "string") this.sysState.genCzText = s.genCzText;
      if (typeof s.genDzuText === "string") this.sysState.genDzuText = s.genDzuText;
      if (typeof s.genDzwText === "string") this.sysState.genDzwText = s.genDzwText;

      if (typeof s.polyVerticesCount === "number" && Number.isFinite(s.polyVerticesCount)) {
        this.sysState.polyVerticesCount = Math.max(2, Math.min(8, Math.round(s.polyVerticesCount)));
      }
      if (typeof s.polyIndexName === "string" && s.polyIndexName.trim()) {
        this.sysState.polyIndexName = s.polyIndexName.trim();
      }
      if (typeof s.polyDeltaPct === "number" && Number.isFinite(s.polyDeltaPct)) {
        this.sysState.polyDeltaPct = Math.max(1, Math.min(80, s.polyDeltaPct));
      }
      const restoredPolyVertices = sanitizeVertexList(s.polyVertices);
      if (restoredPolyVertices.length > 0) {
        this.sysState.polyVertices = restoredPolyVertices;
      } else {
        this.generatePolytopeVertices();
      }

      if (typeof s.tsRulesCount === "number" && Number.isFinite(s.tsRulesCount)) {
        this.sysState.tsRulesCount = Math.max(2, Math.min(6, Math.round(s.tsRulesCount)));
      }
      if (typeof s.tsIndexName === "string" && s.tsIndexName.trim()) {
        this.sysState.tsIndexName = s.tsIndexName.trim();
      }
      if (Array.isArray(s.tsPremises)) {
        const sanitizedPremises: LmiPremiseVarState[] = [];
        for (const item of s.tsPremises) {
          if (!isPlainObject(item)) continue;
          const name =
            typeof item.name === "string" && item.name.trim()
              ? item.name.trim()
              : `z${sanitizedPremises.length + 1}`;
          const min = typeof item.min === "number" && Number.isFinite(item.min) ? item.min : -1;
          const max = typeof item.max === "number" && Number.isFinite(item.max) ? item.max : 1;
          const measured = typeof item.measured === "boolean" ? item.measured : true;
          sanitizedPremises.push({ name, min, max, measured });
        }
        if (sanitizedPremises.length > 0) {
          this.sysState.tsPremises = sanitizedPremises;
        }
      }
      if (Array.isArray(s.tsMemberships)) {
        const sanitizedMfs: LmiTsMembershipRow[] = [];
        for (let i = 0; i < s.tsMemberships.length; i += 1) {
          const item = s.tsMemberships[i];
          if (!isPlainObject(item)) continue;
          const id =
            typeof item.id === "string" && item.id.trim() ? item.id.trim() : `mf-${i + 1}`;
          const expression = typeof item.expression === "string" ? item.expression : "0";
          sanitizedMfs.push({ id, expression });
        }
        this.sysState.tsMemberships = sanitizedMfs;
        this.mfIdCounter = Math.max(this.mfIdCounter, sanitizedMfs.length + 1);
      }
      const restoredTsVertices = sanitizeVertexList(s.tsVertices);
      if (restoredTsVertices.length > 0) {
        this.sysState.tsVertices = restoredTsVertices;
      } else {
        this.resizeTsVertices();
      }

      if (s.tsObsMethod === "dmvt_nonlinearity" || s.tsObsMethod === "gradient_factorization") {
        this.sysState.tsObsMethod = s.tsObsMethod;
      }
      if (typeof s.tsObsDaText === "string") this.sysState.tsObsDaText = s.tsObsDaText;
      if (typeof s.tsObsDcText === "string") this.sysState.tsObsDcText = s.tsObsDcText;
      if (typeof s.extraIndices === "string") this.sysState.extraIndices = s.extraIndices;

      this.syncTsFromMemberships();
    }

    if (typeof raw.currentDsl === "string") {
      this.currentDsl = raw.currentDsl;
    }

    if (this.codeEditorEl) {
      this.codeEditorEl.value = this.currentDsl;
    }
    if (this.genBwEl) this.genBwEl.value = this.sysState.genBwText;
    if (this.genCzEl) this.genCzEl.value = this.sysState.genCzText;
    if (this.genDzuEl) this.genDzuEl.value = this.sysState.genDzuText;
    if (this.genDzwEl) this.genDzwEl.value = this.sysState.genDzwText;
    if (this.tsObsDaEl) this.tsObsDaEl.value = this.sysState.tsObsDaText;
    if (this.tsObsDcEl) this.tsObsDcEl.value = this.sysState.tsObsDcText;

    this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
    this.renderCharacterizationCard();
    this.renderEditorAndMath();
    this.onRequestRender?.();
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
    const daList = parseDeltaMatrixListJson(this.tsObsDaEl ? this.tsObsDaEl.value : this.sysState.tsObsDaText);
    return {
      systemClass: this.sysState.systemClass,
      systemN,
      deltaCount: daList?.length,
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
      this.resizePolyVertices();
    } else if (spec.systemClass === "ts") {
      if (spec.nCount) this.sysState.tsRulesCount = spec.nCount;
      if (spec.indices[0]) this.sysState.tsIndexName = spec.indices[0];
      if (spec.indices.length > 1) this.sysState.extraIndices = spec.indices.slice(1).join(", ");
      this.resizeTsVertices();
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

  private getActivePlantMatrices2D(): {
    A: number[][];
    B: number[][];
    C: number[][];
    D: number[][];
  } {
    const lqrPlant = this.shell.getLqrWorkspace().getPlant();
    const effPlant = this.shell.getTypedWorkspace().getEffectiveSelection("statespacePlant");
    const mats =
      effPlant && isPlainObject(effPlant.object.value.matrices)
        ? (effPlant.object.value.matrices as Record<string, RealTensor>)
        : lqrPlant.matrices;
    return {
      A: tensorTo2DArray(mats.A ?? lqrPlant.matrices.A),
      B: tensorTo2DArray(mats.B ?? lqrPlant.matrices.B),
      C: tensorTo2DArray(mats.C ?? lqrPlant.matrices.C),
      D: tensorTo2DArray(mats.D ?? lqrPlant.matrices.D),
    };
  }

  private resizeVertexList(
    existing: LmiPolytopeVertexPreview[],
    count: number,
    kind: "poly" | "ts",
  ): LmiPolytopeVertexPreview[] {
    const plantMats = this.getActivePlantMatrices2D();
    const next: LmiPolytopeVertexPreview[] = [];
    for (let idx = 0; idx < count; idx += 1) {
      if (idx < existing.length) {
        const cur = existing[idx];
        next.push({
          ...cur,
          index: idx + 1,
          label: cur.label || (kind === "poly" ? `Vértice ${idx + 1}` : `Regra ${idx + 1}`),
        });
      } else {
        next.push({
          index: idx + 1,
          label: kind === "poly" ? `Vértice ${idx + 1}` : `Regra ${idx + 1}`,
          aMatrix: cloneMatrix2D(plantMats.A),
          bMatrix: cloneMatrix2D(plantMats.B),
          cMatrix: cloneMatrix2D(plantMats.C),
          dMatrix: cloneMatrix2D(plantMats.D),
        });
      }
    }
    return next;
  }

  private resizePolyVertices(): void {
    const nv = Math.max(2, Math.min(8, this.sysState.polyVerticesCount));
    this.sysState.polyVerticesCount = nv;
    this.sysState.polyVertices = this.resizeVertexList(this.sysState.polyVertices, nv, "poly");
  }

  private resizeTsVertices(): void {
    const nr = Math.max(2, Math.min(6, this.sysState.tsRulesCount));
    this.sysState.tsRulesCount = nr;
    this.sysState.tsVertices = this.resizeVertexList(this.sysState.tsVertices, nr, "ts");
  }

  private generatePolytopeVertices(): void {
    const plantMats = this.getActivePlantMatrices2D();
    const nv = Math.max(2, Math.min(8, this.sysState.polyVerticesCount));
    const delta = Math.max(1, Math.min(80, this.sysState.polyDeltaPct)) / 100;
    const vertices: LmiPolytopeVertexPreview[] = [];
    for (let idx = 0; idx < nv; idx += 1) {
      const frac = nv === 1 ? 0 : -1 + (2 * idx) / (nv - 1);
      const scale = 1 + frac * delta;
      const aVert = plantMats.A.map((row) =>
        row.map((v) => Number((v * scale).toFixed(4))),
      );
      vertices.push({
        index: idx + 1,
        label: `Vértice ${idx + 1} (escala ${(scale * 100).toFixed(0)}%)`,
        aMatrix: aVert,
        bMatrix: cloneMatrix2D(plantMats.B),
        cMatrix: cloneMatrix2D(plantMats.C),
        dMatrix: cloneMatrix2D(plantMats.D),
      });
    }
    this.sysState.polyVertices = vertices;
  }

  private syncTsFromMemberships(): void {
    this.sysState.tsMfSummary = this.sysState.tsMemberships.map(
      (row, idx) => `h${formatSubscript(idx + 1)}(z) = ${row.expression.trim() || "0"}`,
    );
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
        if (val === "polytopic") this.resizePolyVertices();
        if (val === "ts") this.resizeTsVertices();
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

    const onPolyConfigChange = (regenerate: boolean): void => {
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
      if (regenerate) {
        this.generatePolytopeVertices();
      } else {
        this.resizePolyVertices();
      }
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
    };
    this.polyVerticesCountEl?.addEventListener("change", () => onPolyConfigChange(false));
    this.polyVerticesCountEl?.addEventListener("input", () => onPolyConfigChange(false));
    this.polyIndexNameEl?.addEventListener("input", () => onPolyConfigChange(false));
    this.polyDeltaEl?.addEventListener("change", () => onPolyConfigChange(true));
    this.container
      .querySelector<HTMLElement>('[data-action="lmi-gen-polytope"]')
      ?.addEventListener("click", () => onPolyConfigChange(true));

    const onTsChange = (): void => {
      if (this.tsRulesCountEl) {
        const n = Number(this.tsRulesCountEl.value);
        if (Number.isFinite(n)) this.sysState.tsRulesCount = Math.max(2, Math.min(6, Math.round(n)));
      }
      if (this.tsIndexNameEl) {
        const idx = this.tsIndexNameEl.value.trim();
        if (idx) this.sysState.tsIndexName = idx;
      }
      this.resizeTsVertices();
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
    };
    this.tsRulesCountEl?.addEventListener("change", onTsChange);
    this.tsRulesCountEl?.addEventListener("input", onTsChange);
    this.tsIndexNameEl?.addEventListener("input", onTsChange);

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-add-ts-premise"]')
      ?.addEventListener("click", () => {
        const nextNum = this.sysState.tsPremises.length + 1;
        this.sysState.tsPremises.push({
          name: `z${nextNum}`,
          min: -1,
          max: 1,
          measured: true,
        });
        this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
        this.renderCharacterizationCard();
        this.renderEditorAndMath();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-add-ts-mf"]')
      ?.addEventListener("click", () => {
        const nextNum = this.sysState.tsMemberships.length + 1;
        const defaultPremise = this.sysState.tsPremises[0]?.name.trim() || "z1";
        this.sysState.tsMemberships.push({
          id: `mf-${++this.mfIdCounter}`,
          expression: nextNum === 1 ? `(1 + sin(${defaultPremise})) / 2` : "0",
        });
        this.syncTsFromMemberships();
        this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
        this.renderCharacterizationCard();
        this.renderEditorAndMath();
      });

    const onTsObsChange = (): void => {
      const m = this.tsObsMethodEl?.value;
      if (m === "dmvt_nonlinearity" || m === "gradient_factorization") {
        this.sysState.tsObsMethod = m;
      }
      if (this.tsObsDaEl) this.sysState.tsObsDaText = this.tsObsDaEl.value;
      if (this.tsObsDcEl) this.sysState.tsObsDcText = this.tsObsDcEl.value;
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
    };
    this.tsObsMethodEl?.addEventListener("change", onTsObsChange);
    this.tsObsDaEl?.addEventListener("input", onTsObsChange);
    this.tsObsDaEl?.addEventListener("change", onTsObsChange);
    this.tsObsDcEl?.addEventListener("input", onTsObsChange);
    this.tsObsDcEl?.addEventListener("change", onTsObsChange);

    this.container
      .querySelector<HTMLElement>("#btn-lmi-generate-ts-observer")
      ?.addEventListener("click", () => {
        if (this.tsObsDaEl) this.sysState.tsObsDaText = this.tsObsDaEl.value;
        if (this.tsObsDcEl) this.sysState.tsObsDcText = this.tsObsDcEl.value;
        const obsDsl = [
          "system ts (unmeasured_observer)",
          "index i in 1..N",
          "index k in 1..K",
          "param alpha = 0.2",
          "var P sym(n)",
          "var N[i] rect(n, p)",
          "P > 0",
          "forall i, k:",
          "  He(P * (A[i] + dA[k]) - N[i] * (C[i] + dC[k])) + 2*alpha*P < 0",
          "recover L[i] = inv(P) * N[i]",
        ].join("\n");
        this.loadDsl(obsDsl);
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

  public buildCompileContext(): LmiCompileContext {
    const tpl = this.parsed.inferredTemplate;
    const { A: A2d, B: B2d, C: C2d, D: D2d } = this.getActivePlantMatrices2D();
    const n = A2d.length;
    const m = B2d[0]?.length ?? 1;

    const bwParsed = parseCompactMatrixJson(this.sysState.genBwText);
    const czParsed = parseCompactMatrixJson(this.sysState.genCzText);
    const dzuParsed = parseCompactMatrixJson(this.sysState.genDzuText);
    const dzwParsed = parseCompactMatrixJson(this.sysState.genDzwText);

    const Bw2d =
      bwParsed && bwParsed.length === n
        ? bwParsed
        : Array.from({ length: n }, (_, i) => [i === n - 1 ? 1.0 : 0.0]);
    const nw = Bw2d[0]?.length ?? 1;
    const Cz2d = czParsed && czParsed[0]?.length === n ? czParsed : C2d;
    const nz = Cz2d.length;
    const Dzu2d =
      dzuParsed && dzuParsed.length === nz && dzuParsed[0]?.length === m
        ? dzuParsed
        : Array.from({ length: nz }, () => Array(m).fill(0));
    const Dzw2d =
      dzwParsed && dzwParsed.length === nz && dzwParsed[0]?.length === nw
        ? dzwParsed
        : Array.from({ length: nz }, () => Array(nw).fill(0));

    const weights = this.shell.getLqrWorkspace().getWeights();
    const Q_cost =
      weights.Q.shape[0] === n ? tensorTo2DArray(weights.Q) : undefined;
    const R_cost =
      weights.R.shape[0] === m ? tensorTo2DArray(weights.R) : undefined;

    let vertices: LmiVertexMatrices[] | undefined;
    const sysClass = this.parsed.systemSpec?.systemClass ?? this.sysState.systemClass;
    const effN = Math.max(1, this.parsed.effectiveSystemN);
    if (sysClass === "polytopic" || sysClass === "ts" || effN > 1) {
      if (sysClass === "polytopic") {
        if (this.sysState.polyVertices.length !== effN) {
          this.sysState.polyVerticesCount = effN;
          this.resizePolyVertices();
        }
        vertices = this.sysState.polyVertices.slice(0, effN).map((v) => ({
          A: v.aMatrix,
          B: v.bMatrix,
          C: v.cMatrix,
          D: v.dMatrix,
          Bw: Bw2d,
          Cz: Cz2d,
          Dzu: Dzu2d,
          Dzw: Dzw2d,
        }));
      } else {
        if (this.sysState.tsVertices.length !== effN) {
          this.sysState.tsRulesCount = effN;
          this.resizeTsVertices();
        }
        vertices = this.sysState.tsVertices.slice(0, effN).map((v) => ({
          A: v.aMatrix,
          B: v.bMatrix,
          C: v.cMatrix,
          D: v.dMatrix,
          Bw: Bw2d,
          Cz: Cz2d,
          Dzu: Dzu2d,
          Dzw: Dzw2d,
        }));
      }
    }

    const daRaw = this.tsObsDaEl ? this.tsObsDaEl.value : this.sysState.tsObsDaText;
    const dcRaw = this.tsObsDcEl ? this.tsObsDcEl.value : this.sysState.tsObsDcText;
    const daList = parseDeltaMatrixListJson(daRaw);
    const dcList = parseDeltaMatrixListJson(dcRaw);
    const deltaVertices: LmiDeltaVertexMatrices[] | undefined =
      daList && daList.length > 0
        ? daList.map((dA, idx) => ({
            dA,
            ...(dcList && dcList[idx] ? { dC: dcList[idx] } : {}),
          }))
        : undefined;

    return {
      A: A2d,
      B: B2d,
      C: C2d,
      D: D2d,
      Bw: Bw2d,
      Cz: Cz2d,
      Dzu: Dzu2d,
      Dzw: Dzw2d,
      Q_cost,
      R_cost,
      vertices,
      deltaVertices,
      name: `dsl_${tpl}`,
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

    const tpl = this.parsed.inferredTemplate;
    if (tpl === "canonical_sdp_json" && this.parsed.canonicalSdpOverride) {
      return { problem: this.parsed.canonicalSdpOverride };
    }

    const compileCtx = this.buildCompileContext();

    try {
      const compiled = compileLmiDslToCanonicalSdp(this.parsed, compileCtx);
      return { problem: compiled.problem };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new ControlLabBridgeError("VALIDATION_ERROR", msg);
    }
  }

  private async executeRpc(
    operation: string,
    payload: Record<string, unknown>,
    requestIdOverride?: string,
  ): Promise<RpcResponse> {
    const lqr = this.shell.getLqrWorkspace();
    const projectId = lqr.getProjectId();
    const rev = Math.max(lqr.getProjectRevision(), this.client.getCommittedRevision(projectId));
    return this.client.execute(
      {
        api_version: RPC_API_VERSION,
        request_id: requestIdOverride ?? `lmi-${generateUuid()}`,
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
    const recoveredIndexedK: Array<{ label: string; mat: { rows: number; cols: number; data: number[] } }> = [];
    const recoveredIndexedL: Array<{ label: string; mat: { rows: number; cols: number; data: number[] } }> = [];
    const recoveredScalars: Array<{ name: string; value: number }> = [];

    if (isPlainObject(res.variables)) {
      const vars = res.variables as Record<string, unknown>;
      const qMat = extractRealTensor2D(vars.Q);
      const pMat = extractRealTensor2D(vars.P);
      const yMat = extractRealTensor2D(vars.Y) ?? extractRealTensor2D(vars.Y_i);
      if (!recoveredK && qMat && yMat) {
        recoveredK = formatGainFromQY(qMat, yMat);
      }

      // Indexed gains K[i] = Y[i] * inv(Q) or Y[i] * inv(P[i]), and observer gains L[i] = inv(P) * N[i]
      for (const [varKey, varVal] of Object.entries(vars)) {
        const idxMatch = /^Y\[(\d+)\]$/.exec(varKey);
        if (idxMatch) {
          const idx = idxMatch[1];
          const yiMat = extractRealTensor2D(varVal);
          const piMat = extractRealTensor2D(vars[`P[${idx}]`]) ?? qMat;
          if (yiMat && piMat) {
            const ki = formatGainFromQY(piMat, yiMat);
            if (ki) {
              recoveredIndexedK.push({ label: `K[${idx}]`, mat: ki });
            }
          }
        }
        const nIdxMatch = /^N\[(\d+)\]$/.exec(varKey);
        if (nIdxMatch && pMat) {
          const idx = nIdxMatch[1];
          const niMat = extractRealTensor2D(varVal);
          if (niMat) {
            const li = formatObserverGainFromPN(pMat, niMat);
            if (li) {
              recoveredIndexedL.push({ label: `L[${idx}]`, mat: li });
            }
          }
        }
        const t = extractRealTensor2D(varVal);
        if (t && t.rows === 1 && t.cols === 1 && t.data.length === 1 && Number.isFinite(t.data[0])) {
          recoveredScalars.push({ name: varKey, value: t.data[0] });
        }
      }
      if (!recoveredK && recoveredIndexedK.length > 0) {
        recoveredK = recoveredIndexedK[0].mat;
      }
    }

    const rawSol: Record<string, unknown> = {};
    for (const k of ["x", "dual_Z", "dual_eq", "dual_ineq", "farkas_Z", "farkas_eq", "farkas_ineq", "objective"]) {
      if (res[k] !== undefined) rawSol[k] = res[k];
    }

    const rawLog = Array.isArray(res.iteration_log)
      ? res.iteration_log
      : Array.isArray(diag.iteration_log)
        ? diag.iteration_log
        : null;
    const parsedLog: SolverProgress[] = rawLog
      ? rawLog
          .filter((entry): entry is Record<string, unknown> => isPlainObject(entry))
          .map((entry, idx) => ({
            iter: Number(entry.iter ?? idx + 1),
            max_iters: Number(entry.max_iters ?? rawLog.length),
            gap: Number(entry.gap ?? 0),
            primal_res: Number(entry.primal_res ?? 0),
            dual_res: Number(entry.dual_res ?? 0),
            min_eig: Number(entry.min_eig ?? 0),
            alpha: Number(entry.alpha ?? 1),
            elapsed_ms: Number(entry.elapsed_ms ?? 0),
          }))
      : [...this.liveIterations];

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
      recoveredIndexedK,
      recoveredIndexedL,
      recoveredScalars,
      warnings: resp.warnings.map((w) => (typeof w === "string" ? w : w.message)),
      provenance: resp.provenance as Provenance,
      iterationLog: parsedLog,
    };
  }

  public async solveLmi(): Promise<void> {
    const requestId = `lmi-${generateUuid()}`;
    this.liveIterations = [];
    this.renderProgressRows([], "Resolvendo LMI no motor nativo...");
    const unsubscribeProgress = this.client.subscribeProgress?.((ev) => {
      if (ev.request_id !== requestId) return;
      this.liveIterations.push(ev.progress);
      const p = ev.progress;
      this.renderProgressRows(
        this.liveIterations,
        `Em execução: iteração ${p.iter}/${p.max_iters} | gap=${p.gap.toExponential(2)} | λ_min=${p.min_eig.toExponential(2)} | ${p.elapsed_ms.toFixed(1)} ms`,
      );
    });

    try {
      const payload = await this.buildBackendPayload();
      const resp = await this.executeRpc("optimization.solve", payload, requestId);
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
      this.renderProgressRows(this.liveIterations, "Execução interrompida ou com erro.");
      this.shell.presentError(err);
    } finally {
      unsubscribeProgress?.();
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
    if (this.genBwEl && this.genBwEl.value !== this.sysState.genBwText) this.genBwEl.value = this.sysState.genBwText;
    if (this.genCzEl && this.genCzEl.value !== this.sysState.genCzText) this.genCzEl.value = this.sysState.genCzText;
    if (this.genDzuEl && this.genDzuEl.value !== this.sysState.genDzuText) this.genDzuEl.value = this.sysState.genDzuText;
    if (this.genDzwEl && this.genDzwEl.value !== this.sysState.genDzwText) this.genDzwEl.value = this.sysState.genDzwText;
    setElHidden(
      this.genMatricesPanelEl,
      !(this.sysState.genEnableW || this.sysState.genEnableZ),
    );

    if (this.polyVerticesCountEl) this.polyVerticesCountEl.value = String(this.sysState.polyVerticesCount);
    if (this.polyIndexNameEl) this.polyIndexNameEl.value = this.sysState.polyIndexName;
    if (this.polyDeltaEl) this.polyDeltaEl.value = String(this.sysState.polyDeltaPct);
    this.renderVertexEditor(this.polyVertexPreviewEl, this.sysState.polyVertices, "poly");

    if (this.tsRulesCountEl) this.tsRulesCountEl.value = String(this.sysState.tsRulesCount);
    if (this.tsIndexNameEl) this.tsIndexNameEl.value = this.sysState.tsIndexName;
    this.renderTsMfEditor();
    this.renderTsMfSummaryAndPremises();
    this.renderVertexEditor(this.tsVertexEditorEl, this.sysState.tsVertices, "ts");
    if (this.tsObsMethodEl) this.tsObsMethodEl.value = this.sysState.tsObsMethod;
    if (this.tsObsDaEl && this.tsObsDaEl.value !== this.sysState.tsObsDaText) this.tsObsDaEl.value = this.sysState.tsObsDaText;
    if (this.tsObsDcEl && this.tsObsDcEl.value !== this.sysState.tsObsDcText) this.tsObsDcEl.value = this.sysState.tsObsDcText;

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

  private renderVertexEditor(
    targetEl: HTMLElement | null,
    vertices: LmiPolytopeVertexPreview[],
    kind: "poly" | "ts",
  ): void {
    if (!targetEl) return;
    const prefix = kind === "poly" ? "Vértice" : "Regra";
    const matKeys: Array<"A" | "B" | "C" | "D"> = ["A", "B", "C", "D"];

    const cards = vertices.map((v, idx) => {
      const matInputs = matKeys.map((matKey) => {
        const rawText =
          matKey === "A"
            ? (v.aText ?? JSON.stringify(v.aMatrix))
            : matKey === "B"
              ? (v.bText ?? JSON.stringify(v.bMatrix))
              : matKey === "C"
                ? (v.cText ?? JSON.stringify(v.cMatrix))
                : (v.dText ?? JSON.stringify(v.dMatrix));
        const valid = isValidMatrix2D(parseCompactMatrixJson(rawText));
        const invalidCls = valid ? "" : " lmi-input-invalid";
        const invalidAttr = valid ? "" : ' aria-invalid="true"';
        return [
          `<label class="lmi-vertex-mat-field">`,
          `<span>${matKey}[${v.index}]</span>`,
          `<input type="text" class="touch-control lmi-vertex-input${invalidCls}" data-vertex-kind="${kind}" data-vertex-idx="${idx}" data-vertex-mat="${matKey}" value="${escapeHtml(rawText)}"${invalidAttr} aria-label="${prefix} ${v.index} matriz ${matKey}" />`,
          `</label>`,
        ].join("");
      });
      return [
        `<div class="lmi-vertex-editor-card" data-vertex-kind="${kind}" data-vertex-idx="${idx}">`,
        `<div class="lmi-vertex-card-head"><strong>${prefix} ${v.index}</strong> <span class="lmi-vertex-card-sub">${escapeHtml(v.label)}</span></div>`,
        `<div class="lmi-vertex-mat-grid">${matInputs.join("")}</div>`,
        `</div>`,
      ].join("");
    });

    targetEl.innerHTML = cards.join("");

    const inputs = Array.from(
      targetEl.querySelectorAll<HTMLInputElement>(".lmi-vertex-input"),
    );
    for (const inp of inputs) {
      const handleEdit = (): void => {
        const idx = Number(inp.getAttribute("data-vertex-idx"));
        const matKey = inp.getAttribute("data-vertex-mat") as "A" | "B" | "C" | "D" | null;
        const list =
          kind === "poly" ? this.sysState.polyVertices : this.sysState.tsVertices;
        if (!Number.isInteger(idx) || idx < 0 || idx >= list.length || !matKey) {
          return;
        }
        const v = list[idx];
        const raw = inp.value;
        if (matKey === "A") v.aText = raw;
        else if (matKey === "B") v.bText = raw;
        else if (matKey === "C") v.cText = raw;
        else v.dText = raw;

        const parsedMat = parseCompactMatrixJson(raw);
        if (isValidMatrix2D(parsedMat)) {
          if (matKey === "A") v.aMatrix = parsedMat;
          else if (matKey === "B") v.bMatrix = parsedMat;
          else if (matKey === "C") v.cMatrix = parsedMat;
          else v.dMatrix = parsedMat;
          inp.removeAttribute("aria-invalid");
          toggleCssClass(inp, "lmi-input-invalid", false);
        } else {
          inp.setAttribute("aria-invalid", "true");
          toggleCssClass(inp, "lmi-input-invalid", true);
        }
      };
      inp.addEventListener("input", handleEdit);
      inp.addEventListener("change", handleEdit);
    }
  }

  private renderTsMfEditor(): void {
    if (!this.tsMfRowsEl) return;
    const rowsHtml = this.sysState.tsMemberships.map((row, idx) => {
      const sub = formatSubscript(idx + 1);
      return [
        `<div class="lmi-mf-row" data-mf-idx="${idx}">`,
        `<span class="lmi-mf-label">h${sub}(z) =</span>`,
        `<label class="lmi-mf-field lmi-mf-expr-field"><span class="sr-only">Expressão analítica de h${sub}(z)</span><input type="text" class="touch-control lmi-mf-input" data-mf-field="expression" data-mf-idx="${idx}" value="${escapeHtml(row.expression)}" aria-label="Expressão analítica de h_${idx + 1}(z)" /></label>`,
        `<button type="button" class="touch-control btn-secondary btn-small lmi-mf-remove-btn" data-action="lmi-remove-ts-mf" data-mf-idx="${idx}" aria-label="Remover função h_${idx + 1}(z)">Remover</button>`,
        `</div>`,
      ].join("");
    });
    this.tsMfRowsEl.innerHTML = rowsHtml.join("");

    const exprFields = Array.from(
      this.tsMfRowsEl.querySelectorAll<HTMLInputElement>('input[data-mf-field="expression"]'),
    );
    for (const fieldEl of exprFields) {
      const onFieldEdit = (): void => {
        const idx = Number(fieldEl.getAttribute("data-mf-idx"));
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.sysState.tsMemberships.length) {
          return;
        }
        this.sysState.tsMemberships[idx].expression = fieldEl.value;
        this.syncTsFromMemberships();
        this.renderTsMfSummaryOnly();
        this.renderTsConvexityValidation();
      };
      fieldEl.addEventListener("input", onFieldEdit);
      fieldEl.addEventListener("change", onFieldEdit);
    }

    const removeBtns = Array.from(
      this.tsMfRowsEl.querySelectorAll<HTMLElement>('[data-action="lmi-remove-ts-mf"]'),
    );
    for (const btn of removeBtns) {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-mf-idx"));
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.sysState.tsMemberships.length) {
          return;
        }
        this.sysState.tsMemberships.splice(idx, 1);
        this.syncTsFromMemberships();
        this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
        this.renderCharacterizationCard();
        this.renderEditorAndMath();
      });
    }

    this.renderTsConvexityValidation();
  }

  private renderTsMfSummaryOnly(): void {
    if (this.tsMfSummaryEl) {
      this.tsMfSummaryEl.innerHTML = this.sysState.tsMfSummary
        .map((line) => `<span class="badge">${escapeHtml(line)}</span>`)
        .join(" ");
    }
  }

  private renderTsConvexityValidation(): void {
    if (!this.tsMfValidationEl) return;
    const result = validateConvexMembershipFunctions(
      this.sysState.tsPremises.map((p) => ({
        name: p.name,
        min: p.min,
        max: p.max,
      })),
      this.sysState.tsMemberships.map((row, idx) => ({
        label: `h${formatSubscript(idx + 1)}(z)`,
        expression: row.expression,
      })),
    );
    toggleCssClass(this.tsMfValidationEl, "is-valid", result.valid);
    toggleCssClass(this.tsMfValidationEl, "is-invalid", !result.valid);
    const badgeCls = result.valid ? "badge-stable" : "badge-unstable";
    const badgeLabel = result.valid ? "Válido" : "Inválido";
    this.tsMfValidationEl.innerHTML = `<span class="badge ${badgeCls}">${badgeLabel}</span> <span>${escapeHtml(result.message)}</span>`;
  }

  private renderTsMfSummaryAndPremises(): void {
    this.renderTsMfSummaryOnly();
    this.renderTsConvexityValidation();
    if (this.tsPremisesListEl) {
      const anyUnmeasured = this.sysState.tsPremises.some((p) => !p.measured);
      const canRemove = this.sysState.tsPremises.length > 1;
      const rows = this.sysState.tsPremises.map((p, idx) => {
        const cls = p.measured ? "badge-stable" : "badge-beta";
        const label = p.measured ? "Medida" : "Não Medida (Estimada)";
        return [
          `<div class="lmi-premise-row" data-premise-idx="${idx}">`,
          `<label class="lmi-mf-field">Variável <input type="text" class="touch-control lmi-mf-input" data-premise-field="name" data-premise-idx="${idx}" value="${escapeHtml(p.name)}" aria-label="Nome da premissa ${idx + 1}" /></label>`,
          `<label class="lmi-mf-field">z_min <input type="number" step="any" class="touch-control lmi-mf-input" data-premise-field="min" data-premise-idx="${idx}" value="${escapeHtml(String(p.min))}" aria-label="Limite inferior z_min da premissa ${idx + 1}" /></label>`,
          `<label class="lmi-mf-field">z_max <input type="number" step="any" class="touch-control lmi-mf-input" data-premise-field="max" data-premise-idx="${idx}" value="${escapeHtml(String(p.max))}" aria-label="Limite superior z_max da premissa ${idx + 1}" /></label>`,
          `<div class="lmi-premise-actions">`,
          `<button type="button" class="touch-control btn-small btn-secondary ${cls}" data-action="lmi-toggle-premise" data-premise-idx="${idx}">${escapeHtml(label)}</button>`,
          `<button type="button" class="touch-control btn-small btn-secondary lmi-mf-remove-btn" data-action="lmi-remove-ts-premise" data-premise-idx="${idx}" aria-label="Remover premissa ${idx + 1}"${!canRemove ? ' disabled aria-disabled="true"' : ""}>Remover</button>`,
          `</div>`,
          `</div>`,
        ].join("");
      });
      if (anyUnmeasured) {
        rows.push(
          `<div class="warning-callout" role="status"><strong>ts_partially_observed:</strong> Há premissas não medidas (ẑ). Utilize observador TS ou termos de acoplamento Lipschitz γ_L na DSL.</div>`,
        );
      }
      this.tsPremisesListEl.innerHTML = rows.join("");

      const premiseInputs = Array.from(
        this.tsPremisesListEl.querySelectorAll<HTMLInputElement>("input[data-premise-field]"),
      );
      for (const inp of premiseInputs) {
        const onPremiseEdit = (): void => {
          const idx = Number(inp.getAttribute("data-premise-idx"));
          const field = inp.getAttribute("data-premise-field");
          if (!Number.isInteger(idx) || idx < 0 || idx >= this.sysState.tsPremises.length) return;
          const p = this.sysState.tsPremises[idx];
          if (field === "name") {
            p.name = inp.value;
          } else if (field === "min") {
            p.min = inp.value.trim() === "" ? Number.NaN : Number(inp.value);
          } else if (field === "max") {
            p.max = inp.value.trim() === "" ? Number.NaN : Number(inp.value);
          }
          this.renderTsConvexityValidation();
        };
        inp.addEventListener("input", onPremiseEdit);
        inp.addEventListener("change", onPremiseEdit);
      }

      const toggleBtns = Array.from(
        this.tsPremisesListEl.querySelectorAll<HTMLElement>('[data-action="lmi-toggle-premise"]'),
      );
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

      const removePremiseBtns = Array.from(
        this.tsPremisesListEl.querySelectorAll<HTMLElement>('[data-action="lmi-remove-ts-premise"]'),
      );
      for (const btn of removePremiseBtns) {
        btn.addEventListener("click", () => {
          if (this.sysState.tsPremises.length <= 1) return;
          const idx = Number(btn.getAttribute("data-premise-idx"));
          if (!Number.isInteger(idx) || idx < 0 || idx >= this.sysState.tsPremises.length) return;
          this.sysState.tsPremises.splice(idx, 1);
          this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
          this.renderCharacterizationCard();
          this.renderEditorAndMath();
        });
      }

      setElHidden(
        this.tsUnmeasuredPanelEl,
        !(this.sysState.systemClass === "ts" && anyUnmeasured),
      );
    }
  }

  private estimateDslVariables(dims: { n: number; m: number; p: number }): number {
    if (this.parsed.variables.length === 0) {
      return Math.round((dims.n * (dims.n + 1)) / 2);
    }
    const resolveDimToken = (tok: string): number => {
      const t = tok.trim();
      if (t === "n") return dims.n;
      if (t === "m") return dims.m;
      if (t === "p") return dims.p;
      const num = Number(t);
      return Number.isFinite(num) && num > 0 ? Math.round(num) : dims.n;
    };
    let total = 0;
    for (const v of this.parsed.variables) {
      let base = 1;
      if (v.kind === "sym") {
        const d = resolveDimToken(v.rowsExpr);
        base = Math.round((d * (d + 1)) / 2);
      } else if (v.kind === "rect") {
        const r = resolveDimToken(v.rowsExpr);
        const c = resolveDimToken(v.colsExpr);
        base = r * c;
      } else {
        base = 1;
      }
      const mult = (v.indexedBy?.length ?? 0) > 0 ? Math.max(1, this.parsed.effectiveSystemN) : 1;
      total += base * mult;
    }
    return total;
  }

  private renderEditorAndMath(): void {
    const dims = this.getActivePlantDims();
    if (this.envelopeBannerEl) {
      const tpl = this.parsed.inferredTemplate;
      const isHinf = tpl === "hinf_brl" || tpl === "hinf_generalized_brl";
      const nVars = this.estimateDslVariables(dims);
      const maxNForMode = isHinf ? 20 : 28;
      const exceedsEnvelope =
        dims.n > maxNForMode ||
        nVars > BROWSER_ENVELOPE.max_variables ||
        this.parsed.expandedBlockCount > 32;
      if (exceedsEnvelope) {
        setElHidden(this.envelopeBannerEl, false);
        this.envelopeBannerEl.innerHTML = `<strong>Limite do motor navegador (ADR-010):</strong> Planta com n=${dims.n} estados, ~${nVars} variáveis (envelope validado: n ≤ 28 geral, n ≤ 20 H∞, max_variables=${BROWSER_ENVELOPE.max_variables}, max_block_dimension=${BROWSER_ENVELOPE.max_block_dimension}, max_cone_entries=${BROWSER_ENVELOPE.max_cone_entries}) e ${this.parsed.expandedBlockCount} bloco(s) LMI. Recomenda-se usar <strong>Exportar CVXPY / YALMIP</strong> para execução offline com MOSEK/SCS.`;
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

  private renderProgressRows(rows: readonly SolverProgress[], statusText: string): void {
    if (this.progressStatusEl) {
      this.progressStatusEl.textContent = statusText;
    }
    if (!this.progressTbodyEl) return;
    if (rows.length === 0) {
      this.progressTbodyEl.innerHTML = "";
      return;
    }
    const maxDisplay = 60;
    const displayEntries: Array<{ kind: "row"; row: SolverProgress } | { kind: "gap"; skipped: number }> = [];
    if (rows.length <= maxDisplay) {
      for (const r of rows) displayEntries.push({ kind: "row", row: r });
    } else {
      for (let i = 0; i < 15; i += 1) displayEntries.push({ kind: "row", row: rows[i] });
      displayEntries.push({ kind: "gap", skipped: rows.length - 55 });
      for (let i = rows.length - 40; i < rows.length; i += 1) {
        displayEntries.push({ kind: "row", row: rows[i] });
      }
    }
    this.progressTbodyEl.innerHTML = displayEntries
      .map((entry) => {
        if (entry.kind === "gap") {
          return `<tr><td colspan="6">… ${entry.skipped} iterações intermediárias omitidas …</td></tr>`;
        }
        const r = entry.row;
        return `<tr><td>${r.iter}</td><td>${escapeHtml(r.gap.toExponential(2))}</td><td>${escapeHtml(r.primal_res.toExponential(2))}</td><td>${escapeHtml(r.dual_res.toExponential(2))}</td><td>${escapeHtml(r.min_eig.toExponential(2))}</td><td>${escapeHtml(r.elapsed_ms.toFixed(1))}</td></tr>`;
      })
      .join("");
  }

  private renderCertificateAndSpectrum(): void {
    const decimals = this.shell.getDisplayDecimals();
    if (!this.lastSolve) {
      if (this.certDimsEl) {
        this.certDimsEl.innerHTML = `<p>Execute <strong>Resolver LMI</strong> para auditar o problema e gerar o certificado em 5 dimensões, ou exporte scripts CVXPY/YALMIP diretamente.</p>`;
      }
      if (this.certAlertEl) this.certAlertEl.innerHTML = "";
      if (this.recoveredGainEl) this.recoveredGainEl.innerHTML = "";
      this.renderProgressRows([], "Aguardando execução.");
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
      let kHtml: string;
      const parts: string[] = [];
      if (s.recoveredIndexedK && s.recoveredIndexedK.length > 0) {
        parts.push(
          ...s.recoveredIndexedK.map((item) => {
            const fmt = formatMatrixDisplay(item.mat.data, item.mat.rows, item.mat.cols, decimals)
              .map((r) => `[${r.join(", ")}]`)
              .join("; ");
            return `<strong>Ganho recuperado ${escapeHtml(item.label)}:</strong> <code>${escapeHtml(fmt)}</code>`;
          }),
        );
      }
      if (s.recoveredIndexedL && s.recoveredIndexedL.length > 0) {
        parts.push(
          ...s.recoveredIndexedL.map((item) => {
            const fmt = formatMatrixDisplay(item.mat.data, item.mat.rows, item.mat.cols, decimals)
              .map((r) => `[${r.join(", ")}]`)
              .join("; ");
            return `<strong>Ganho do observador ${escapeHtml(item.label)}:</strong> <code>${escapeHtml(fmt)}</code>`;
          }),
        );
      }
      if (parts.length > 0) {
        kHtml = parts.join(" | ");
      } else {
        const kFormatted = s.recoveredK
          ? formatMatrixDisplay(s.recoveredK.data, s.recoveredK.rows, s.recoveredK.cols, decimals)
              .map((r) => `[${r.join(", ")}]`)
              .join("; ")
          : null;
        kHtml = kFormatted
          ? `<strong>Ganho recuperado K = Y Q⁻¹:</strong> <code>${escapeHtml(kFormatted)}</code>`
          : `<strong>Ganho K:</strong> N/D para esta formulação`;
      }
      const scalarHtml =
        s.recoveredScalars && s.recoveredScalars.length > 0
          ? s.recoveredScalars
              .map((sc) => ` | <strong>${escapeHtml(sc.name)}:</strong> <code>${formatNumericDisplay(sc.value, decimals)}</code>`)
              .join("")
          : "";
      const objHtml =
        s.objective !== null
          ? ` | <strong>Objetivo:</strong> <code>${formatNumericDisplay(s.objective, decimals)}</code>`
          : "";
      this.recoveredGainEl.innerHTML = `<p>${kHtml}${scalarHtml}${objHtml}</p>`;
    }

    if (s.iterationLog.length > 0) {
      const last = s.iterationLog[s.iterationLog.length - 1];
      this.renderProgressRows(
        s.iterationLog,
        `Concluído em ${s.iterationLog.length} iteração(ões) | gap=${last.gap.toExponential(2)} | λ_min=${last.min_eig.toExponential(2)} | ${last.elapsed_ms.toFixed(1)} ms`,
      );
    } else {
      this.renderProgressRows([], "Sem log de iterações nesta resposta.");
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
