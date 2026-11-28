/**
 * Bancada da Aba 6 — LMIs, SDPs e Síntese Robusta
 * seguindo CL-LMI-DSL-DIR-001 v1.0.0, CL-UX-DIR-001 v1.0.0 Seção 4.6, ADR-010 e ADR-014
 * (`WP-UX-REFACTOR-03-MIMO-FUZZY-LMI` + `WP-PHASE8-01-F8-WORKSPACE-SYSTEM-EDITOR`).
 *
 * Responsabilidades estritas de UI/Apresentação (F8) — Arquitetura Workspace-First (ADR-014):
 * - Zona 1: Barra de ações, templates v1.0/v2.0, salvar/carregar presets e exportar/importar `.lmi`.
 * - Zona 2: Seletor de Sistema do Workspace (`#lmi-workspace-system-select`), atalhos
 *   `Editar Sistema no Workspace…` / `+ Novo Sistema`, resumo de engenharia somente-leitura
 *   (`#lmi-selected-system-summary`), configuração de índices da DSL (`#lmi-primary-index-name`,
 *   `#lmi-extra-indices`) e painel de observador TS para sistemas `ts_partially_observed`
 *   (`#lmi-ts-unmeasured-panel`).
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
  extractGeneralizedChannels,
  formatDockObjectDisplayName,
  type GeneralizedChannelsSpec,
  type NewObjectModalMode,
} from "../../app/workspace_dock.ts";
import {
  buildAccessibleChartTable,
  buildLmiSpectrumChartModel,
  renderAccessibleTableHtml,
  renderLmiSpectrumSvg,
  type LmiSpectrumChartModel,
} from "../../charts/scientific_chart.ts";
import {
  encodeObjectRefKey,
  isTypedObjectKind,
  type RegisteredTypedObject,
} from "../typed_workspace.ts";
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
  type LmiFusionStats,
  type LmiVertexMatrices,
} from "./lmi_dsl_compiler.ts";
import {
  evaluateAllRecoveries,
  type DenseMatrixValue,
  type EvaluatedRecoveryEntry,
} from "./lmi_recover_eval.ts";
import {
  validateConvexMembershipFunctions,
  type TsConvexityValidationResult,
} from "./lmi_ts_mf_eval.ts";

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
  onOpenNewSystemModal?: (mode?: NewObjectModalMode) => void;
  onOpenEditSystemModal?: (refKey?: string) => void;
}

export interface SavedLmiPreset {
  id: string;
  name: string;
  template: LmiBackendTemplateId;
  dsl: string;
  savedAt: string;
}

interface WorkspaceSystemVertex {
  vertex_id: string;
  A: number[][];
  B: number[][];
  C: number[][];
  D: number[][];
}

interface WorkspaceSystemDescriptor {
  refKey: string;
  id: string;
  revision: number;
  kind: "StateSpace" | "polytopic_uncertain" | "ts_measured" | "ts_partially_observed";
  systemClass: "lti" | "polytopic" | "ts";
  dt: number | null;
  n: number;
  m: number;
  p: number;
  A: number[][];
  B: number[][];
  C: number[][];
  D: number[][];
  generalized: GeneralizedChannelsSpec | null;
  vertices: WorkspaceSystemVertex[];
  measuredPremises: string[];
  unmeasuredPremises: string[];
  bounds: Record<string, [number, number]>;
  membershipFunctions: Array<{ label: string; expression: string }>;
  convexity: TsConvexityValidationResult | null;
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
  recoveredEntries: EvaluatedRecoveryEntry[];
  solvedVariables: Array<{ name: string; mat: DenseMatrixValue }>;
  fusionStats: LmiFusionStats | null;
  warnings: string[];
  provenance: Provenance | null;
  iterationLog: SolverProgress[];
}

type LastSolveProblemSource =
  | { kind: "override"; problem: Record<string, unknown> }
  | { kind: "compiled"; parsed: LmiDslParseResult; compileCtx: LmiCompileContext };

interface LastSolveContext {
  systemRefKey: string;
  dsl: string;
}

export interface SynthesizedControllerExtraction {
  controller: Record<string, unknown>;
  plant: Record<string, unknown>;
  systemKind: WorkspaceSystemDescriptor["kind"];
  feedbackSign: "negative" | "positive";
  canExportPathSim: boolean;
}

export const BROWSER_ENVELOPE = {
  fast_max_variables: 1792,
  max_variables: 3072,
  max_block_dimension: 96,
  max_cone_entries: 131072,
} as const;

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function setButtonDisabled(btn: HTMLButtonElement | null | undefined, disabled: boolean): void {
  if (!btn) return;
  btn.disabled = disabled;
  if (disabled) {
    btn.setAttribute("disabled", "true");
    btn.setAttribute("aria-disabled", "true");
  } else {
    btn.removeAttribute("disabled");
    btn.removeAttribute("aria-disabled");
  }
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

function cloneMatrix2D(mat: number[][]): number[][] {
  return mat.map((row) => [...row]);
}

function formatSubscript(num: number): string {
  const digits = ["₀", "₁", "₂", "₃", "₄", "₅", "₆", "₇", "₈", "₉"];
  return String(num)
    .split("")
    .map((ch) => digits[Number(ch)] ?? ch)
    .join("");
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

function rawTensorTo2D(raw: unknown, fallback: number[][]): number[][] {
  if (!isPlainObject(raw) || !Array.isArray(raw.shape) || !Array.isArray(raw.data)) {
    return cloneMatrix2D(fallback);
  }
  return tensorTo2DArray(raw as unknown as RealTensor);
}

export interface LmiNamedMatrix {
  label: string;
  formula?: string;
  mat: DenseMatrixValue;
  isScalar?: boolean;
}

export function formatLmiMatricesCopyText(
  items: readonly LmiNamedMatrix[],
  decimals: number,
): string {
  return items
    .map((item) => {
      const { mat, isScalar } = item;
      if ((isScalar || (mat.rows === 1 && mat.cols === 1)) && mat.data.length === 1) {
        return `${item.label} = ${formatNumericDisplay(mat.data[0], decimals)}`;
      }
      const rows = formatMatrixDisplay(mat.data, mat.rows, mat.cols, decimals);
      const body = rows.map((r) => `  [${r.join(", ")}]`).join(",\n");
      return `${item.label} = [\n${body}\n]`;
    })
    .join("\n\n");
}

function renderLmiMatrixCardHtml(
  title: string,
  plainKey: string,
  formula: string | null,
  mat: DenseMatrixValue,
  decimals: number,
  isScalar = false,
): string {
  const formulaHtml = formula ? ` <code class="lmi-matrix-formula">(${escapeHtml(formula)})</code>` : "";
  if ((isScalar || (mat.rows === 1 && mat.cols === 1)) && mat.data.length === 1) {
    const valStr = formatNumericDisplay(mat.data[0], decimals);
    return [
      `<div class="lmi-matrix-card lmi-matrix-card-scalar" data-lmi-matrix="${escapeHtml(plainKey)}">`,
      `<div class="lmi-matrix-card-head"><div><strong>${escapeHtml(title)}</strong>${formulaHtml}</div><span class="badge">escalar</span></div>`,
      `<div class="lmi-matrix-scalar-val tabular-num"><code>${escapeHtml(valStr)}</code></div>`,
      `</div>`,
    ].join("");
  }
  const formattedRows = formatMatrixDisplay(mat.data, mat.rows, mat.cols, decimals);
  const tbodyRows = formattedRows
    .map(
      (row) =>
        `<tr>${row.map((cell) => `<td class="tabular-num">${escapeHtml(cell)}</td>`).join("")}</tr>`,
    )
    .join("");
  return [
    `<div class="lmi-matrix-card" data-lmi-matrix="${escapeHtml(plainKey)}">`,
    `<div class="lmi-matrix-card-head"><div><strong>${escapeHtml(title)}</strong>${formulaHtml}</div><span class="badge">${mat.rows}×${mat.cols}</span></div>`,
    `<div class="lmi-matrix-scroll">`,
    `<table class="accessible-data-table lmi-matrix-table" aria-label="Matriz ${escapeHtml(title)} (${mat.rows} por ${mat.cols})">`,
    `<tbody>${tbodyRows}</tbody>`,
    `</table>`,
    `</div>`,
    `</div>`,
  ].join("");
}

export function renderLmiViewHtml(): string {
  const templateOptions = LMI_DSL_TEMPLATES.map(
    (tpl) =>
      `<option value="${escapeHtml(tpl.id)}">${escapeHtml(tpl.label)}</option>`,
  ).join("");
  const starterDsl = LMI_DSL_TEMPLATES[0].dsl;

  return [
    `<section id="lmi-workspace-panel" class="panel-card workspace-section" aria-label="LMIs, SDPs e Síntese Robusta" hidden>`,
    `<h3>LMIs, SDPs &amp; Síntese Robusta</h3>`,
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
    `<button type="button" id="btn-lmi-register-controller" class="touch-control btn-secondary" data-action="lmi-register-controller" disabled aria-disabled="true">Registrar Controlador no Workspace</button>`,
    `<button type="button" id="btn-lmi-export-pathsim" class="touch-control btn-secondary" data-action="lmi-export-pathsim" disabled aria-disabled="true">Exportar Simulação PathSim (.py)</button>`,
    `</div>`,
    `</div>`,

    `<div id="lmi-system-characterization-card" class="subcard lmi-sys-card" aria-label="Caracterização do Sistema e Conjuntos de Índices">`,
    `<div class="lmi-sys-head">`,
    `<h4>Caracterização do Sistema &amp; Conjuntos de Índices</h4>`,
    `<span id="lmi-expanded-blocks-badge" class="badge badge-sufficient">2 blocos LMI expandidos</span>`,
    `<span id="lmi-fusion-badge" class="badge badge-exact" hidden></span>`,
    `</div>`,
    `<div class="lmi-sys-class-row lmi-workspace-selector-row">`,
    `<label for="lmi-workspace-system-select">Sistema do Workspace</label>`,
    `<select id="lmi-workspace-system-select" class="touch-control" aria-label="Selecionar sistema do Workspace para síntese LMI"></select>`,
    `<button type="button" id="btn-lmi-edit-system-workspace" class="touch-control btn-secondary btn-small" data-action="lmi-edit-system-workspace">Editar Sistema no Workspace…</button>`,
    `<button type="button" id="btn-lmi-new-system-workspace" class="touch-control btn-primary btn-small" data-action="lmi-new-system-workspace">+ Novo Sistema</button>`,
    `</div>`,

    `<div class="lmi-sys-grid">`,
    `<div class="lmi-sys-col">`,
    `<div id="lmi-selected-system-summary" class="lmi-sys-summary lmi-selected-system-summary" role="region" aria-label="Resumo do sistema selecionado no Workspace"></div>`,
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

    `<div class="lmi-sys-col lmi-sys-indices-col">`,
    `<div class="lmi-indices-row">`,
    `<label class="lmi-index-field" for="lmi-primary-index-name">Índice principal <input type="text" id="lmi-primary-index-name" class="touch-control" value="i" aria-label="Índice principal na DSL" /></label>`,
    `<label class="lmi-index-field" for="lmi-extra-indices">Índices adicionais (ex: j, k) <input type="text" id="lmi-extra-indices" class="touch-control" value="j" aria-label="Índices adicionais na DSL" /></label>`,
    `</div>`,
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
    `<h4>Certificado de Auditoria Independente (5 Dimensões)</h4>`,
    `<div id="lmi-certificate-dims" class="lmi-cert-dims-grid"><p>Execute <strong>Resolver LMI</strong> para auditar o problema e gerar o certificado em 5 dimensões, ou exporte scripts CVXPY/YALMIP diretamente.</p></div>`,
    `<div id="lmi-certificate-alert"></div>`,
    `<div id="lmi-recovered-gain" class="lmi-recovered-gain"></div>`,
    `<div id="lmi-solver-progress-panel" class="lmi-solver-progress-panel">`,
    `<details id="lmi-solver-progress-details" open>`,
    `<summary>Progresso do Solver Primal-Dual (Iterações)</summary>`,
    `<div class="lmi-solver-progress-bar">`,
    `<div id="lmi-solver-progress-status" class="lmi-solver-progress-status" aria-live="polite">Aguardando execução.</div>`,
    `<button type="button" id="btn-lmi-cancel-solve" class="touch-control btn-secondary btn-small lmi-cancel-solve-btn" data-action="lmi-cancel-solve" hidden>Cancelar</button>`,
    `</div>`,
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
  private readonly onOpenNewSystemModal?: (mode?: NewObjectModalMode) => void;
  private readonly onOpenEditSystemModal?: (refKey?: string) => void;

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
  private readonly cancelSolveBtnEl: HTMLButtonElement | null;
  private readonly registerControllerBtnEl: HTMLButtonElement | null;
  private readonly exportPathSimBtnEl: HTMLButtonElement | null;
  private readonly spectrumChartSlotEl: HTMLElement | null;
  private readonly spectrumTableSlotEl: HTMLElement | null;

  // Zona 2 Workspace-First DOM references
  private readonly expandedBlocksBadgeEl: HTMLElement | null;
  private readonly fusionBadgeEl: HTMLElement | null;
  private readonly workspaceSystemSelectEl: HTMLSelectElement | null;
  private readonly selectedSystemSummaryEl: HTMLElement | null;
  private readonly tsUnmeasuredPanelEl: HTMLElement | null;
  private readonly tsObsMethodEl: HTMLSelectElement | null;
  private readonly tsObsDaEl: HTMLInputElement | null;
  private readonly tsObsDcEl: HTMLInputElement | null;
  private readonly primaryIndexNameEl: HTMLInputElement | null;
  private readonly extraIndicesEl: HTMLInputElement | null;
  private readonly sysIndicesSummaryEl: HTMLElement | null;

  private selectedSystemRefKey = "";
  private lastSystemSelectHtmlKey = "";
  private primaryIndexName = "i";
  private extraIndices = "j";
  private tsObsMethod: "dmvt_nonlinearity" | "gradient_factorization" = "dmvt_nonlinearity";
  private tsObsDaText = "[[[0, 0.2], [0, 0]], [[0, -0.2], [0, 0]]]";
  private tsObsDcText = "";
  private currentTemplate: LmiBackendTemplateId = LMI_DSL_TEMPLATES[0].id;
  private currentDsl: string;
  private parsed: LmiDslParseResult;
  private savedPresets: SavedLmiPreset[] = [];
  private lastSolve: LmiSolveSnapshot | null = null;
  private lastSolveProblemSource: LastSolveProblemSource | null = null;
  private lastSolveContext: LastSolveContext | null = null;
  private lastRegisteredController: Record<string, unknown> | null = null;
  private lastRegisteredControllerContext: LastSolveContext | null = null;
  private lastFusionStats: LmiFusionStats | null = null;
  private liveIterations: SolverProgress[] = [];
  private activeSolveRequestId: string | null = null;

  constructor(options: LmiViewOptions) {
    this.shell = options.shell;
    this.client = options.client;
    this.container = options.container;
    this.onRequestRender = options.onRequestRender;
    this.onOpenExportModal = options.onOpenExportModal;
    this.onOpenNewSystemModal = options.onOpenNewSystemModal;
    this.onOpenEditSystemModal = options.onOpenEditSystemModal;

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
    if (this.codeEditorEl && !this.codeEditorEl.value) {
      this.codeEditorEl.value = this.currentDsl;
    }
    this.parsedVarsEl = this.container.querySelector<HTMLElement>("#lmi-parsed-vars");
    this.parsedMathEl = this.container.querySelector<HTMLElement>("#lmi-parsed-math");
    this.parsedAlertEl = this.container.querySelector<HTMLElement>("#lmi-parsed-alert");
    this.certDimsEl = this.container.querySelector<HTMLElement>("#lmi-certificate-dims");
    this.certAlertEl = this.container.querySelector<HTMLElement>("#lmi-certificate-alert");
    this.recoveredGainEl = this.container.querySelector<HTMLElement>("#lmi-recovered-gain");
    this.progressStatusEl = this.container.querySelector<HTMLElement>("#lmi-solver-progress-status");
    this.progressTbodyEl = this.container.querySelector<HTMLElement>("#lmi-solver-progress-tbody");
    this.cancelSolveBtnEl = this.container.querySelector<HTMLButtonElement>("#btn-lmi-cancel-solve");
    this.registerControllerBtnEl = this.container.querySelector<HTMLButtonElement>("#btn-lmi-register-controller");
    this.exportPathSimBtnEl = this.container.querySelector<HTMLButtonElement>("#btn-lmi-export-pathsim");
    this.spectrumChartSlotEl = this.container.querySelector<HTMLElement>("#lmi-spectrum-chart-slot");
    this.spectrumTableSlotEl = this.container.querySelector<HTMLElement>("#lmi-spectrum-table-slot");

    this.expandedBlocksBadgeEl = this.container.querySelector<HTMLElement>("#lmi-expanded-blocks-badge");
    this.fusionBadgeEl = this.container.querySelector<HTMLElement>("#lmi-fusion-badge");
    this.workspaceSystemSelectEl = this.container.querySelector<HTMLSelectElement>("#lmi-workspace-system-select");
    this.selectedSystemSummaryEl = this.container.querySelector<HTMLElement>("#lmi-selected-system-summary");
    this.tsUnmeasuredPanelEl = this.container.querySelector<HTMLElement>("#lmi-ts-unmeasured-panel");
    this.tsObsMethodEl = this.container.querySelector<HTMLSelectElement>("#lmi-ts-obs-method");
    this.tsObsDaEl = this.container.querySelector<HTMLInputElement>("#lmi-ts-obs-da");
    this.tsObsDcEl = this.container.querySelector<HTMLInputElement>("#lmi-ts-obs-dc");
    this.primaryIndexNameEl = this.container.querySelector<HTMLInputElement>("#lmi-primary-index-name");
    this.extraIndicesEl = this.container.querySelector<HTMLInputElement>("#lmi-extra-indices");
    this.sysIndicesSummaryEl = this.container.querySelector<HTMLElement>("#lmi-sys-indices-summary");

    this.bindEvents();
    this.shell.registerLmiPersistence(
      () => this.exportState(),
      (state) => this.importState(state),
    );
  }

  public selectSystemByRefKey(refKey: string): void {
    this.selectedSystemRefKey = refKey;
    this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
    this.renderCharacterizationCard();
    this.renderEditorAndMath();
    this.updateControllerActionButtons();
  }

  public handleWorkspaceSystemRegistered(refKey: string, kind: string): void {
    if (
      kind === "StateSpace" ||
      kind === "polytopic_uncertain" ||
      kind === "ts_measured" ||
      kind === "ts_partially_observed"
    ) {
      this.selectSystemByRefKey(refKey);
    }
  }

  public listAvailableWorkspaceSystems(): RegisteredTypedObject[] {
    const typed = this.shell.getTypedWorkspace();
    const byKey = new Map<string, RegisteredTypedObject>();
    for (const role of ["statespacePlant", "tsModel"] as const) {
      for (const item of typed.listSelectableObjectsForRole(role)) {
        if (!byKey.has(item.key)) {
          byKey.set(item.key, item);
        }
      }
    }
    const lqrPlant = this.shell.getLqrWorkspace().getPlant();
    const lqrKey = encodeObjectRefKey({ id: lqrPlant.id, revision: lqrPlant.revision });
    if (!byKey.has(lqrKey)) {
      const n = lqrPlant.matrices.A.shape[0];
      const m = lqrPlant.matrices.B.shape[1];
      const p = lqrPlant.matrices.C.shape[0];
      byKey.set(lqrKey, {
        key: lqrKey,
        id: lqrPlant.id,
        revision: lqrPlant.revision,
        kind: "StateSpace",
        summary: `StateSpace (n=${n}, m=${m}, p=${p}${lqrPlant.dt !== null ? `, dt=${lqrPlant.dt}` : ", contínuo"})`,
        value: lqrPlant as unknown as Record<string, unknown>,
        persisted: false,
        registered_at: "",
        source: "lqr_plant",
      });
    }
    return Array.from(byKey.values());
  }

  private resolveSelectedWorkspaceObject(): RegisteredTypedObject {
    const available = this.listAvailableWorkspaceSystems();
    if (this.selectedSystemRefKey) {
      const exact = available.find((o) => o.key === this.selectedSystemRefKey);
      if (exact) return exact;
      // If an edited object bumped revision, auto-follow latest revision of same id
      const sep = this.selectedSystemRefKey.lastIndexOf("#");
      if (sep > 0) {
        const prevId = decodeURIComponent(this.selectedSystemRefKey.slice(0, sep));
        const sameId = available
          .filter((o) => o.id === prevId)
          .sort((a, b) => b.revision - a.revision);
        if (sameId.length > 0) {
          this.selectedSystemRefKey = sameId[0].key;
          return sameId[0];
        }
      }
    }
    const typed = this.shell.getTypedWorkspace();
    const selTs = typed.getSelectedRef("tsModel");
    if (selTs) {
      const tsKey = encodeObjectRefKey(selTs);
      const foundTs = available.find((o) => o.key === tsKey);
      if (foundTs) {
        this.selectedSystemRefKey = foundTs.key;
        return foundTs;
      }
    }
    const selSs = typed.getSelectedRef("statespacePlant");
    if (selSs) {
      const ssKey = encodeObjectRefKey(selSs);
      const foundSs = available.find((o) => o.key === ssKey);
      if (foundSs) {
        this.selectedSystemRefKey = foundSs.key;
        return foundSs;
      }
    }
    const lqrPlant = this.shell.getLqrWorkspace().getPlant();
    const lqrKey = encodeObjectRefKey({ id: lqrPlant.id, revision: lqrPlant.revision });
    const lqrEntry = available.find((o) => o.key === lqrKey) ?? available[0];
    this.selectedSystemRefKey = lqrEntry.key;
    return lqrEntry;
  }

  private getSelectedSystemDescriptor(): WorkspaceSystemDescriptor {
    const obj = this.resolveSelectedWorkspaceObject();
    const val = obj.value;
    const dt = typeof val.dt === "number" ? val.dt : null;
    const lqrPlant = this.shell.getLqrWorkspace().getPlant();
    const fallbackA = tensorTo2DArray(lqrPlant.matrices.A);
    const fallbackB = tensorTo2DArray(lqrPlant.matrices.B);
    const fallbackC = tensorTo2DArray(lqrPlant.matrices.C);
    const fallbackD = tensorTo2DArray(lqrPlant.matrices.D);

    if (
      obj.kind === "polytopic_uncertain" ||
      obj.kind === "ts_measured" ||
      obj.kind === "ts_partially_observed"
    ) {
      const rawVerts = Array.isArray(val.vertices) ? val.vertices : [];
      const vertices: WorkspaceSystemVertex[] = rawVerts.map((v, idx) => {
        const vo = isPlainObject(v) ? v : {};
        return {
          vertex_id: typeof vo.vertex_id === "string" ? vo.vertex_id : `v${idx + 1}`,
          A: rawTensorTo2D(vo.A, fallbackA),
          B: rawTensorTo2D(vo.B, fallbackB),
          C: rawTensorTo2D(vo.C, fallbackC),
          D: rawTensorTo2D(vo.D, fallbackD),
        };
      });
      const v0 = vertices[0] ?? {
        vertex_id: "v1",
        A: fallbackA,
        B: fallbackB,
        C: fallbackC,
        D: fallbackD,
      };
      const n = v0.A.length;
      const m = v0.B[0]?.length ?? 1;
      const p = v0.C.length;

      const pa = isPlainObject(val.premise_availability) ? val.premise_availability : {};
      const measuredPremises = Array.isArray(pa.measured_premises)
        ? (pa.measured_premises as unknown[]).map((x) => String(x))
        : [];
      const unmeasuredPremises = Array.isArray(pa.unmeasured_premises)
        ? (pa.unmeasured_premises as unknown[]).map((x) => String(x))
        : [];
      const dom = isPlainObject(val.domain) ? val.domain : {};
      const rawBounds = isPlainObject(dom.bounds) ? (dom.bounds as Record<string, unknown>) : {};
      const bounds: Record<string, [number, number]> = {};
      for (const [k, pair] of Object.entries(rawBounds)) {
        if (Array.isArray(pair) && pair.length >= 2) {
          bounds[k] = [Number(pair[0]), Number(pair[1])];
        }
      }

      const ms = isPlainObject(val.membership_spec) ? val.membership_spec : {};
      const rawFns = Array.isArray(ms.functions) ? ms.functions : [];
      const membershipFunctions = rawFns
        .filter((f): f is Record<string, unknown> => isPlainObject(f))
        .map((f, idx) => ({
          label: typeof f.label === "string" ? f.label : `h${formatSubscript(idx + 1)}(z)`,
          expression: typeof f.expression === "string" ? f.expression : "0",
        }));

      let convexity: TsConvexityValidationResult | null = null;
      if (obj.kind === "ts_measured" || obj.kind === "ts_partially_observed") {
        const repKind = typeof ms.representation_kind === "string" ? ms.representation_kind : "";
        if (repKind === "femt_simplicial" && isPlainObject(ms.femt_mesh) && Array.isArray(ms.femt_mesh.nodal_weights)) {
          let minW = 1.0;
          let maxErr = 0.0;
          for (const row of ms.femt_mesh.nodal_weights as unknown[]) {
            if (!Array.isArray(row)) continue;
            let rowSum = 0.0;
            for (const v of row) {
              const nv = Number(v);
              if (nv < minW) minW = nv;
              rowSum += nv;
            }
            const err = Math.abs(rowSum - 1.0);
            if (err > maxErr) maxErr = err;
          }
          const ok = minW >= -1e-9 && maxErr <= 1e-8;
          convexity = {
            valid: ok,
            message: ok
              ? `Partição simplicial P₁ verificada nos nós (min=${minW.toExponential(2)}, |∑h−1|=${maxErr.toExponential(2)}).`
              : `Violação nos pesos nodais FEMT (min=${minW.toExponential(2)}, |∑h−1|=${maxErr.toExponential(2)}).`,
            minWeight: minW,
            maxSumError: maxErr,
          };
        } else if (repKind === "tpmt_interpolated" && Array.isArray(ms.tpmt_axes)) {
          let minW = 1.0;
          let maxErr = 0.0;
          for (const ax of ms.tpmt_axes as unknown[]) {
            if (!isPlainObject(ax) || !Array.isArray(ax.weights_table)) continue;
            for (const row of ax.weights_table as unknown[]) {
              if (!Array.isArray(row)) continue;
              let rowSum = 0.0;
              for (const v of row) {
                const nv = Number(v);
                if (nv < minW) minW = nv;
                rowSum += nv;
              }
              const err = Math.abs(rowSum - 1.0);
              if (err > maxErr) maxErr = err;
            }
          }
          const ok = minW >= -1e-9 && maxErr <= 1e-8;
          convexity = {
            valid: ok,
            message: ok
              ? `Partição tensorial TPMT verificada por eixo (min=${minW.toExponential(2)}, |∑w−1|=${maxErr.toExponential(2)}).`
              : `Violação na tabela de pesos TPMT (min=${minW.toExponential(2)}, |∑w−1|=${maxErr.toExponential(2)}).`,
            minWeight: minW,
            maxSumError: maxErr,
          };
        } else {
          const premNames = Array.isArray(ms.premise_variables)
            ? (ms.premise_variables as unknown[]).map((x) => String(x)).filter(Boolean)
            : Object.keys(bounds);
          if (membershipFunctions.length > 0 && premNames.length > 0) {
            convexity = validateConvexMembershipFunctions(
              premNames.map((name) => ({
                name,
                min: bounds[name]?.[0] ?? -1,
                max: bounds[name]?.[1] ?? 1,
              })),
              membershipFunctions,
            );
          }
        }
      }

      return {
        refKey: obj.key,
        id: obj.id,
        revision: obj.revision,
        kind: obj.kind,
        systemClass: obj.kind === "polytopic_uncertain" ? "polytopic" : "ts",
        dt,
        n,
        m,
        p,
        A: v0.A,
        B: v0.B,
        C: v0.C,
        D: v0.D,
        generalized: null,
        vertices,
        measuredPremises,
        unmeasuredPremises,
        bounds,
        membershipFunctions,
        convexity,
      };
    }

    const mats = isPlainObject(val.matrices) ? (val.matrices as Record<string, unknown>) : {};
    const A = rawTensorTo2D(mats.A, fallbackA);
    const B = rawTensorTo2D(mats.B, fallbackB);
    const C = rawTensorTo2D(mats.C, fallbackC);
    const D = rawTensorTo2D(mats.D, fallbackD);
    const generalized = extractGeneralizedChannels(val.provenance);

    return {
      refKey: obj.key,
      id: obj.id,
      revision: obj.revision,
      kind: "StateSpace",
      systemClass: "lti",
      dt,
      n: A.length,
      m: B[0]?.length ?? 1,
      p: C.length,
      A,
      B,
      C,
      D,
      generalized,
      vertices: [],
      measuredPremises: [],
      unmeasuredPremises: [],
      bounds: {},
      membershipFunctions: [],
      convexity: null,
    };
  }

  public exportState(): Record<string, unknown> {
    if (this.codeEditorEl && this.codeEditorEl.value !== this.currentDsl) {
      this.currentDsl = this.codeEditorEl.value;
    }
    return {
      selectedSystemRefKey: this.selectedSystemRefKey,
      primaryIndexName: this.primaryIndexName,
      extraIndices: this.extraIndices,
      tsObsMethod: this.tsObsMethod,
      tsObsDaText: this.tsObsDaText,
      tsObsDcText: this.tsObsDcText,
      dsl: this.currentDsl,
      currentDsl: this.currentDsl,
      template: this.currentTemplate,
      savedPresets: structuredClone(this.savedPresets),
    };
  }

  public importState(raw: unknown): void {
    if (!isPlainObject(raw)) return;

    if (typeof raw.selectedSystemRefKey === "string") {
      this.selectedSystemRefKey = raw.selectedSystemRefKey;
    }
    if (typeof raw.primaryIndexName === "string" && raw.primaryIndexName.trim()) {
      this.primaryIndexName = raw.primaryIndexName.trim();
    }
    if (typeof raw.extraIndices === "string") {
      this.extraIndices = raw.extraIndices;
    }
    if (raw.tsObsMethod === "dmvt_nonlinearity" || raw.tsObsMethod === "gradient_factorization") {
      this.tsObsMethod = raw.tsObsMethod;
    }
    if (typeof raw.tsObsDaText === "string") {
      this.tsObsDaText = raw.tsObsDaText;
    }
    if (typeof raw.tsObsDcText === "string") {
      this.tsObsDcText = raw.tsObsDcText;
    }
    if (typeof raw.template === "string") {
      const found = LMI_DSL_TEMPLATES.find((t) => t.id === raw.template);
      if (found) this.currentTemplate = found.id;
    }
    if (Array.isArray(raw.savedPresets)) {
      const sanitized: SavedLmiPreset[] = [];
      for (const item of raw.savedPresets) {
        if (!isPlainObject(item) || typeof item.dsl !== "string") continue;
        sanitized.push({
          id: typeof item.id === "string" ? item.id : `lmi-preset-${sanitized.length + 1}`,
          name: typeof item.name === "string" ? item.name : `Condição ${sanitized.length + 1}`,
          template: (typeof item.template === "string" ? item.template : "decay_rate") as LmiBackendTemplateId,
          dsl: item.dsl,
          savedAt: typeof item.savedAt === "string" ? item.savedAt : new Date().toISOString(),
        });
      }
      this.savedPresets = sanitized;
      this.renderSavedSelect();
    }

    // Legacy v1 sysState compatibility (only observer & extraIndices fields)
    if (isPlainObject(raw.sysState)) {
      const s = raw.sysState;
      if (typeof s.extraIndices === "string") this.extraIndices = s.extraIndices;
      if (s.tsObsMethod === "dmvt_nonlinearity" || s.tsObsMethod === "gradient_factorization") {
        this.tsObsMethod = s.tsObsMethod;
      }
      if (typeof s.tsObsDaText === "string") this.tsObsDaText = s.tsObsDaText;
      if (typeof s.tsObsDcText === "string") this.tsObsDcText = s.tsObsDcText;
    }

    if (typeof raw.dsl === "string") {
      this.currentDsl = raw.dsl;
    } else if (typeof raw.currentDsl === "string") {
      this.currentDsl = raw.currentDsl;
    }

    if (this.codeEditorEl) this.codeEditorEl.value = this.currentDsl;
    if (this.templateSelectEl) this.templateSelectEl.value = this.currentTemplate;
    if (this.primaryIndexNameEl) this.primaryIndexNameEl.value = this.primaryIndexName;
    if (this.extraIndicesEl) this.extraIndicesEl.value = this.extraIndices;
    if (this.tsObsMethodEl) this.tsObsMethodEl.value = this.tsObsMethod;
    if (this.tsObsDaEl) this.tsObsDaEl.value = this.tsObsDaText;
    if (this.tsObsDcEl) this.tsObsDcEl.value = this.tsObsDcText;

    this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
    this.renderCharacterizationCard();
    this.renderEditorAndMath();
    this.updateControllerActionButtons();
    this.onRequestRender?.();
  }

  public exportSerializableState(): Record<string, unknown> {
    return this.exportState();
  }

  public restoreSerializableState(raw: unknown): void {
    this.importState(raw);
  }

  private buildParseOptions(): LmiDslParseOptions {
    const desc = this.getSelectedSystemDescriptor();
    const systemN = desc.vertices.length > 0 ? desc.vertices.length : 1;
    const indexName =
      desc.systemClass === "lti" ? undefined : (this.primaryIndexName.trim() || "i");
    const extraIndices = this.extraIndices
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const daList = parseDeltaMatrixListJson(
      this.tsObsDaEl ? this.tsObsDaEl.value : this.tsObsDaText,
    );
    return {
      systemClass: desc.systemClass,
      systemN,
      deltaCount: daList?.length,
      indexName,
      extraIndices,
      premisesMeasured: desc.kind !== "ts_partially_observed",
      generalized: Boolean(desc.generalized?.enable_w || desc.generalized?.enable_z),
    };
  }

  private syncSystemDirectiveToDsl(): void {
    const desc = this.getSelectedSystemDescriptor();
    const primary = this.primaryIndexName.trim() || "i";
    const extra = this.extraIndices
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const idxAll = [primary, ...extra].join(",");
    let directive = "";
    if (desc.systemClass === "lti") {
      const gen = Boolean(desc.generalized?.enable_w || desc.generalized?.enable_z);
      directive = `system lti generalized=${gen ? "true" : "false"}`;
    } else if (desc.systemClass === "polytopic") {
      directive = `system polytopic vertices=${desc.vertices.length} index=${idxAll}`;
    } else {
      const premMode = desc.kind === "ts_partially_observed" ? "unmeasured" : "measured";
      directive = `system ts rules=${desc.vertices.length} index=${idxAll} premises=${premMode}`;
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
    this.updateControllerActionButtons();
  }

  private bindEvents(): void {
    const syncFromEditor = (): void => {
      if (!this.codeEditorEl) return;
      this.currentDsl = this.codeEditorEl.value;
      this.lastFusionStats = null;
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
      this.updateControllerActionButtons();
    };
    this.codeEditorEl?.addEventListener("input", syncFromEditor);
    this.codeEditorEl?.addEventListener("change", syncFromEditor);

    this.templateSelectEl?.addEventListener("change", () => {
      const tplId = this.templateSelectEl?.value as LmiBackendTemplateId | undefined;
      const found = LMI_DSL_TEMPLATES.find((t) => t.id === tplId);
      if (!found) return;
      this.currentTemplate = found.id;
      let dsl = found.dsl;
      const desc = this.getSelectedSystemDescriptor();
      if (desc.systemClass === "polytopic" && desc.vertices.length > 0) {
        dsl = dsl.replace(/\bvertices=\d+/i, `vertices=${desc.vertices.length}`);
      } else if (desc.systemClass === "ts" && desc.vertices.length > 0) {
        dsl = dsl.replace(/\brules=\d+/i, `rules=${desc.vertices.length}`);
        if (desc.kind === "ts_partially_observed") {
          dsl = dsl.replace(/\bpremises=measured\b/i, "premises=unmeasured");
        }
      }
      this.loadDsl(dsl);
    });

    this.workspaceSystemSelectEl?.addEventListener("change", () => {
      const nextKey = this.workspaceSystemSelectEl?.value ?? "";
      if (nextKey) {
        this.selectedSystemRefKey = nextKey;
        this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
        this.renderCharacterizationCard();
        this.renderEditorAndMath();
        this.updateControllerActionButtons();
      }
    });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-edit-system-workspace"]')
      ?.addEventListener("click", () => {
        const desc = this.getSelectedSystemDescriptor();
        this.onOpenEditSystemModal?.(desc.refKey);
      });

    this.container
      .querySelector<HTMLElement>('[data-action="lmi-new-system-workspace"]')
      ?.addEventListener("click", () => {
        const desc = this.getSelectedSystemDescriptor();
        const mode: NewObjectModalMode =
          desc.systemClass === "polytopic"
            ? "polytopic"
            : desc.systemClass === "ts"
              ? "ts"
              : "ss";
        this.onOpenNewSystemModal?.(mode);
      });

    const onIndexChange = (): void => {
      if (this.primaryIndexNameEl) {
        const val = this.primaryIndexNameEl.value.trim();
        if (val) this.primaryIndexName = val;
      }
      if (this.extraIndicesEl) {
        this.extraIndices = this.extraIndicesEl.value;
      }
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
      this.updateControllerActionButtons();
    };
    this.primaryIndexNameEl?.addEventListener("input", onIndexChange);
    this.primaryIndexNameEl?.addEventListener("change", onIndexChange);
    this.extraIndicesEl?.addEventListener("input", onIndexChange);
    this.extraIndicesEl?.addEventListener("change", onIndexChange);

    const onTsObsChange = (): void => {
      const m = this.tsObsMethodEl?.value;
      if (m === "dmvt_nonlinearity" || m === "gradient_factorization") {
        this.tsObsMethod = m;
      }
      if (this.tsObsDaEl) this.tsObsDaText = this.tsObsDaEl.value;
      if (this.tsObsDcEl) this.tsObsDcText = this.tsObsDcEl.value;
      this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
      this.renderCharacterizationCard();
      this.renderEditorAndMath();
      this.updateControllerActionButtons();
    };
    this.tsObsMethodEl?.addEventListener("change", onTsObsChange);
    this.tsObsDaEl?.addEventListener("input", onTsObsChange);
    this.tsObsDaEl?.addEventListener("change", onTsObsChange);
    this.tsObsDcEl?.addEventListener("input", onTsObsChange);
    this.tsObsDcEl?.addEventListener("change", onTsObsChange);

    this.container
      .querySelector<HTMLElement>("#btn-lmi-generate-ts-observer")
      ?.addEventListener("click", () => {
        if (this.tsObsDaEl) this.tsObsDaText = this.tsObsDaEl.value;
        if (this.tsObsDcEl) this.tsObsDcText = this.tsObsDcEl.value;
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

    this.cancelSolveBtnEl?.addEventListener("click", () => {
      void this.cancelSolve();
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

    this.registerControllerBtnEl?.addEventListener("click", () => {
      void this.registerSynthesizedController();
    });

    this.exportPathSimBtnEl?.addEventListener("click", (ev) => {
      void this.exportPathSimSimulation(ev.currentTarget as HTMLElement | null);
    });
  }

  public loadDsl(dsl: string): void {
    this.currentDsl = dsl;
    this.lastFusionStats = null;
    if (this.codeEditorEl) {
      this.codeEditorEl.value = dsl;
    }
    this.parsed = parseLmiDsl(dsl, this.buildParseOptions());
    this.renderCharacterizationCard();
    this.renderEditorAndMath();
    this.updateControllerActionButtons();
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

  private buildQuantifiedExportContext(): LmiQuantifiedExportContext {
    const desc = this.getSelectedSystemDescriptor();
    const sysClass =
      desc.vertices.length > 0
        ? desc.systemClass
        : (this.parsed.systemSpec?.systemClass ?? desc.systemClass);
    const sysN =
      desc.vertices.length > 0
        ? desc.vertices.length
        : this.parsed.effectiveSystemN;
    return {
      systemClass: sysClass,
      n: desc.n,
      m: desc.m,
      p: desc.p,
      systemN: sysN,
      generalized: Boolean(desc.generalized?.enable_w || desc.generalized?.enable_z),
      premisesMeasured: desc.kind !== "ts_partially_observed",
    };
  }

  public buildCompileContext(): LmiCompileContext {
    const tpl = this.parsed.inferredTemplate;
    const desc = this.getSelectedSystemDescriptor();
    const { A: A2d, B: B2d, C: C2d, D: D2d, n, m } = desc;
    const gen = desc.generalized;

    const Bw2d =
      gen?.enable_w && gen.Bw && gen.Bw.length === n
        ? cloneMatrix2D(gen.Bw)
        : Array.from({ length: n }, (_, i) => [i === n - 1 ? 1.0 : 0.0]);
    const nw = Bw2d[0]?.length ?? 1;
    const Cz2d =
      gen?.enable_z && gen.Cz && gen.Cz[0]?.length === n
        ? cloneMatrix2D(gen.Cz)
        : cloneMatrix2D(C2d);
    const nz = Cz2d.length;
    const Dzu2d =
      gen?.enable_z && gen.Dzu && gen.Dzu.length === nz && gen.Dzu[0]?.length === m
        ? cloneMatrix2D(gen.Dzu)
        : Array.from({ length: nz }, () => Array(m).fill(0));
    const Dzw2d =
      gen?.enable_w && gen?.enable_z && gen.Dzw && gen.Dzw.length === nz && gen.Dzw[0]?.length === nw
        ? cloneMatrix2D(gen.Dzw)
        : Array.from({ length: nz }, () => Array(nw).fill(0));

    const weights = this.shell.getLqrWorkspace().getWeights();
    const Q_cost =
      weights.Q.shape[0] === n ? tensorTo2DArray(weights.Q) : undefined;
    const R_cost =
      weights.R.shape[0] === m ? tensorTo2DArray(weights.R) : undefined;

    let vertices: LmiVertexMatrices[] | undefined;
    const sysClass = this.parsed.systemSpec?.systemClass ?? desc.systemClass;
    const effN = Math.max(1, this.parsed.effectiveSystemN);

    if (desc.vertices.length > 0) {
      // Read ALL vertices directly from the selected Workspace TSStateSpace (arbitrary N_v / N_r)
      vertices = desc.vertices.map((v) => ({
        A: cloneMatrix2D(v.A),
        B: cloneMatrix2D(v.B),
        C: cloneMatrix2D(v.C),
        D: cloneMatrix2D(v.D),
        Bw: Bw2d,
        Cz: Cz2d,
        Dzu: Dzu2d,
        Dzw: Dzw2d,
      }));
    } else if (sysClass === "polytopic" || sysClass === "ts" || effN > 1) {
      // Graceful fallback when running a quantified template against an LTI StateSpace plant
      const delta = 0.15;
      vertices = Array.from({ length: effN }, (_, idx) => {
        const frac = effN === 1 ? 0 : -1 + (2 * idx) / (effN - 1);
        const scale = 1 + frac * delta;
        return {
          A: A2d.map((row) => row.map((v) => Number((v * scale).toFixed(4)))),
          B: cloneMatrix2D(B2d),
          C: cloneMatrix2D(C2d),
          D: cloneMatrix2D(D2d),
          Bw: Bw2d,
          Cz: Cz2d,
          Dzu: Dzu2d,
          Dzw: Dzw2d,
        };
      });
    }

    const daRaw = this.tsObsDaEl ? this.tsObsDaEl.value : this.tsObsDaText;
    const dcRaw = this.tsObsDcEl ? this.tsObsDcEl.value : this.tsObsDcText;
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

  private prepareProblemSource(): LastSolveProblemSource {
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
      return {
        kind: "override",
        problem: structuredClone(this.parsed.canonicalSdpOverride),
      };
    }

    return {
      kind: "compiled",
      parsed: this.parsed,
      compileCtx: this.buildCompileContext(),
    };
  }

  private renderFusionBadge(): void {
    if (!this.fusionBadgeEl) return;
    const stats = this.lastFusionStats;
    if (stats && stats.eliminatedSymmetricPairs > 0) {
      const n = stats.eliminatedSymmetricPairs;
      this.fusionBadgeEl.textContent =
        n === 1
          ? `1 par simétrico fundido (${stats.originalBlocks} → ${stats.fusedBlocks})`
          : `${n} pares simétricos fundidos (${stats.originalBlocks} → ${stats.fusedBlocks})`;
      setElHidden(this.fusionBadgeEl, false);
    } else {
      this.fusionBadgeEl.textContent = "";
      setElHidden(this.fusionBadgeEl, true);
    }
  }

  private materializePayloadFromSource(
    source: LastSolveProblemSource,
  ): Record<string, unknown> {
    if (source.kind === "override") {
      this.lastFusionStats = null;
      this.renderFusionBadge();
      return { problem: structuredClone(source.problem) };
    }
    try {
      const compiled = compileLmiDslToCanonicalSdp(source.parsed, source.compileCtx);
      this.lastFusionStats = compiled.fusionStats;
      this.renderFusionBadge();
      return { problem: compiled.problem };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new ControlLabBridgeError("VALIDATION_ERROR", msg);
    }
  }

  private async buildBackendPayload(): Promise<Record<string, unknown>> {
    const source = this.prepareProblemSource();
    return this.materializePayloadFromSource(source);
  }

  private async executeRpc(
    operation: string,
    payload: Record<string, unknown>,
    requestIdOverride?: string,
    timeoutMs = 30000,
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
        timeout_policy: { hard_timeout_ms: timeoutMs },
      },
      { commitOnSuccess: false },
    );
  }

  private ingestOptimizationResponse(
    operation: string,
    resp: RpcResponse,
    problemSource: LastSolveProblemSource,
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
    const solvedVarsMap: Record<string, DenseMatrixValue> = {};
    const solvedVariables: Array<{ name: string; mat: DenseMatrixValue }> = [];

    if (isPlainObject(res.variables)) {
      const vars = res.variables as Record<string, unknown>;
      for (const [varKey, varVal] of Object.entries(vars)) {
        const t = extractRealTensor2D(varVal);
        if (t) {
          solvedVarsMap[varKey] = t;
          solvedVariables.push({ name: varKey, mat: t });
        }
      }

      const qMat = solvedVarsMap.Q ?? null;
      const pMat = solvedVarsMap.P ?? null;
      const yMat = solvedVarsMap.Y ?? solvedVarsMap.Y_i ?? null;
      if (!recoveredK && qMat && yMat) {
        recoveredK = formatGainFromQY(qMat, yMat);
      }

      for (const [varKey, t] of Object.entries(solvedVarsMap)) {
        const idxMatch = /^Y\[(\d+)\]$/.exec(varKey);
        if (idxMatch) {
          const idx = idxMatch[1];
          const piMat = solvedVarsMap[`P[${idx}]`] ?? qMat;
          if (piMat) {
            const ki = formatGainFromQY(piMat, t);
            if (ki) {
              recoveredIndexedK.push({ label: `K[${idx}]`, mat: ki });
            }
          }
        }
        const nIdxMatch = /^N\[(\d+)\]$/.exec(varKey);
        if (nIdxMatch && pMat) {
          const idx = nIdxMatch[1];
          const li = formatObserverGainFromPN(pMat, t);
          if (li) {
            recoveredIndexedL.push({ label: `L[${idx}]`, mat: li });
          }
        }
        if (t.rows === 1 && t.cols === 1 && t.data.length === 1 && Number.isFinite(t.data[0])) {
          recoveredScalars.push({ name: varKey, value: t.data[0] });
        }
      }
      if (!recoveredK && recoveredIndexedK.length > 0) {
        recoveredK = recoveredIndexedK[0].mat;
      }
    }

    const effectiveSolvedVariables =
      solvedVariables.length > 0
        ? solvedVariables
        : operation === "optimization.verify" && this.lastSolve
          ? this.lastSolve.solvedVariables
          : solvedVariables;

    const effectiveSolvedVarsMap: Record<string, DenseMatrixValue> =
      solvedVariables.length > 0
        ? solvedVarsMap
        : Object.fromEntries(effectiveSolvedVariables.map((item) => [item.name, item.mat]));

    let recoveredEntries: EvaluatedRecoveryEntry[] = [];
    if (
      problemSource.kind === "compiled" &&
      problemSource.parsed.recoveries.length > 0 &&
      effectiveSolvedVariables.length > 0
    ) {
      recoveredEntries = evaluateAllRecoveries({
        parsed: problemSource.parsed,
        compileCtx: problemSource.compileCtx,
        solvedVariables: effectiveSolvedVarsMap,
      });
    } else if (operation === "optimization.verify" && this.lastSolve) {
      recoveredEntries = this.lastSolve.recoveredEntries;
      if (!recoveredK) recoveredK = this.lastSolve.recoveredK;
    }

    const rawSol: Record<string, unknown> = {};
    for (const k of ["x", "dual_Z", "dual_eq", "dual_ineq", "farkas_Z", "farkas_eq", "farkas_ineq", "objective"]) {
      if (res[k] !== undefined) rawSol[k] = res[k];
    }
    const effectiveRawSol =
      Object.keys(rawSol).length > 0
        ? rawSol
        : operation === "optimization.verify" && this.lastSolve
          ? this.lastSolve.rawSolutionPayload
          : rawSol;

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

    this.lastSolveProblemSource = problemSource;
    if (operation === "optimization.solve") {
      this.lastSolveContext = {
        systemRefKey: this.getSelectedSystemDescriptor().refKey,
        dsl: this.currentDsl,
      };
      this.lastRegisteredController = null;
      this.lastRegisteredControllerContext = null;
    }
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
      rawSolutionPayload: effectiveRawSol,
      recoveredK,
      recoveredIndexedK,
      recoveredIndexedL,
      recoveredScalars,
      recoveredEntries,
      solvedVariables: effectiveSolvedVariables,
      fusionStats: this.lastFusionStats ? { ...this.lastFusionStats } : null,
      warnings: resp.warnings.map((w) => (typeof w === "string" ? w : w.message)),
      provenance: resp.provenance as Provenance,
      iterationLog: parsedLog,
    };
  }

  public async cancelSolve(): Promise<void> {
    const reqId = this.activeSolveRequestId;
    if (!reqId) return;
    this.activeSolveRequestId = null;
    setElHidden(this.cancelSolveBtnEl, true);
    if (this.progressStatusEl) {
      this.progressStatusEl.textContent = "Resolução cancelada pelo usuário.";
    }
    try {
      await this.client.cancel(reqId, { reason: "user_cancelled_lmi" });
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async solveLmi(): Promise<void> {
    const requestId = `lmi-${generateUuid()}`;
    this.activeSolveRequestId = requestId;
    setElHidden(this.cancelSolveBtnEl, false);
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
      const problemSource = this.prepareProblemSource();
      const payload = this.materializePayloadFromSource(problemSource);
      const resp = await this.executeRpc("optimization.solve", payload, requestId, 300_000);
      if (this.activeSolveRequestId !== requestId) {
        this.renderProgressRows(this.liveIterations, "Resolução cancelada pelo usuário.");
        return;
      }
      if (resp.status === "failure") {
        if (resp.error?.code === "CANCELLED") {
          this.renderProgressRows(this.liveIterations, "Resolução cancelada pelo usuário.");
          return;
        }
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao resolver LMI.",
        );
      }
      this.ingestOptimizationResponse("optimization.solve", resp, problemSource);
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
      if (this.activeSolveRequestId !== requestId) {
        this.renderProgressRows(this.liveIterations, "Resolução cancelada pelo usuário.");
      } else {
        this.renderProgressRows(this.liveIterations, "Execução interrompida ou com erro.");
        this.shell.presentError(err);
      }
    } finally {
      if (this.activeSolveRequestId === requestId) {
        this.activeSolveRequestId = null;
      }
      setElHidden(this.cancelSolveBtnEl, true);
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
      const problemSource = this.lastSolveProblemSource ?? this.prepareProblemSource();
      const basePayload = this.materializePayloadFromSource(problemSource);
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
      this.ingestOptimizationResponse("optimization.verify", resp, problemSource);
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
      const desc = this.getSelectedSystemDescriptor();
      const hasQuantifiers = this.parsed.constraints.some((c) => Boolean(c.quantifier));
      if (
        hasQuantifiers ||
        desc.systemClass === "polytopic" ||
        desc.systemClass === "ts" ||
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

  public extractSynthesizedControllerGains(): SynthesizedControllerExtraction | null {
    const s = this.lastSolve;
    const ctx = this.lastSolveContext;
    if (!s || !ctx) return null;

    const activeDsl = this.codeEditorEl ? this.codeEditorEl.value : this.currentDsl;
    if (activeDsl !== ctx.dsl) return null;

    const selectedObj = this.resolveSelectedWorkspaceObject();
    const desc = this.getSelectedSystemDescriptor();
    if (desc.refKey !== ctx.systemRefKey) return null;

    if (!this.parsed.valid || this.parsed.bilinearWarnings.length > 0) return null;

    const responseOk = s.responseStatus === "success" || s.responseStatus === "warning";
    const solverFeasible =
      s.solverStatus === "optimal" || s.solverStatus === "optimal_inaccurate";
    const auditFeasible =
      s.auditFeasibility === "strictly_feasible" ||
      s.auditFeasibility === "approximately_feasible";
    if (!responseOk || !solverFeasible || !auditFeasible || s.controllerValidity === "violated") {
      return null;
    }

    const isValidGainMatrix = (mat: DenseMatrixValue | null | undefined): mat is DenseMatrixValue =>
      Boolean(
        mat &&
          mat.rows === desc.m &&
          mat.cols === desc.n &&
          mat.data.length === desc.m * desc.n &&
          mat.data.every((v) => Number.isFinite(v)),
      );

    // Reject if any K recovery directive failed evaluation
    for (const entry of s.recoveredEntries) {
      if (/^K(?:\b|\[|_)/.test(entry.label) && !entry.ok) {
        return null;
      }
    }

    const expandedConstraintsText = this.parsed.constraints.map((c) => c.lhsRaw).join("\n");
    const constraintHasNegBY =
      this.parsed.inferredFeedbackSign === "negative" ||
      /-\s*(?:B|B2|B_i|B\[[^\]]+\])\s*[*@]\s*Y/.test(expandedConstraintsText);

    const resolveSign = (recoveryFormula: string | null): "negative" | "positive" => {
      const recoveryNegated = recoveryFormula ? /^-\s*/.test(recoveryFormula.trim()) : false;
      return constraintHasNegBY !== recoveryNegated ? "negative" : "positive";
    };

    if (desc.kind === "ts_measured" || desc.kind === "ts_partially_observed") {
      const nRules = desc.vertices.length;
      if (nRules < 1) return null;

      let kMatrices: DenseMatrixValue[] | null = null;
      let recoveryFormula: string | null = null;

      const indexedFromEntries = new Map<number, EvaluatedRecoveryEntry>();
      for (const entry of s.recoveredEntries) {
        if (!entry.ok || !entry.value) continue;
        const m = /^K(?:\[\s*(\d+)\s*\]|_(\d+))$/.exec(entry.label.trim());
        if (!m) continue;
        const idx = Number(m[1] ?? m[2]);
        if (Number.isInteger(idx) && idx >= 1 && !indexedFromEntries.has(idx)) {
          indexedFromEntries.set(idx, entry);
        }
      }

      if (indexedFromEntries.size > 0) {
        const ordered: DenseMatrixValue[] = [];
        for (let i = 1; i <= nRules; i += 1) {
          const item = indexedFromEntries.get(i);
          if (!item || !isValidGainMatrix(item.value)) {
            ordered.length = 0;
            break;
          }
          if (recoveryFormula === null) recoveryFormula = item.formula;
          ordered.push(item.value);
        }
        if (ordered.length === nRules && indexedFromEntries.size === nRules) {
          kMatrices = ordered;
        }
      }

      if (!kMatrices && s.recoveredIndexedK && s.recoveredIndexedK.length === nRules) {
        const indexedFallback = new Map<number, DenseMatrixValue>();
        for (const item of s.recoveredIndexedK) {
          const m = /^K\[\s*(\d+)\s*\]$/.exec(item.label.trim());
          if (!m) continue;
          const idx = Number(m[1]);
          if (Number.isInteger(idx) && idx >= 1) {
            indexedFallback.set(idx, item.mat);
          }
        }
        const ordered: DenseMatrixValue[] = [];
        for (let i = 1; i <= nRules; i += 1) {
          const mat = indexedFallback.get(i);
          if (!isValidGainMatrix(mat)) {
            ordered.length = 0;
            break;
          }
          ordered.push(mat);
        }
        if (ordered.length === nRules) {
          kMatrices = ordered;
        }
      }

      if (!kMatrices) return null;

      const tsVal = selectedObj.value;
      const ms = isPlainObject(tsVal.membership_spec) ? tsVal.membership_spec : {};
      const rawPremVars = Array.isArray(ms.premise_variables)
        ? (ms.premise_variables as unknown[]).map((x) => String(x)).filter((v) => v.length > 0)
        : [];
      const fallbackPremVars = Array.from(
        new Set([...desc.measuredPremises, ...desc.unmeasuredPremises]),
      ).filter((v) => v.length > 0);
      const premiseVars =
        rawPremVars.length > 0 ? Array.from(new Set(rawPremVars)) : fallbackPremVars;

      const feedbackSign = resolveSign(recoveryFormula);
      const ctrlDto: Record<string, unknown> = {
        schema_version: "1.0.0",
        id: `pdc-${desc.id}`,
        revision: 1,
        kind: "PDCController",
        feedback_sign: feedbackSign,
        K_i: kMatrices.map((mat) => ({
          shape: [mat.rows, mat.cols],
          dtype: "float64",
          order: "C",
          data: [...mat.data],
        })),
        membership_ref: {
          model_id: desc.id,
          model_revision: desc.revision,
          membership_version: String(ms.version ?? "1.0.0"),
        },
        measurement_requirements: {
          required_premise_variables: premiseVars,
          requires_full_state: true,
          allowed_ts_kinds:
            desc.kind === "ts_partially_observed"
              ? ["ts_measured", "ts_partially_observed"]
              : ["ts_measured"],
        },
        dt: desc.dt ?? null,
        provenance: {
          source: "web.lmi_view.pdc_synthesis",
          template: this.currentTemplate,
        },
      };

      return {
        controller: ctrlDto,
        plant: structuredClone(tsVal),
        systemKind: desc.kind,
        feedbackSign,
        canExportPathSim: desc.kind === "ts_measured",
      };
    }

    if (desc.kind === "StateSpace") {
      let kMat: DenseMatrixValue | null = null;
      let recoveryFormula: string | null = null;

      const exactK = s.recoveredEntries.find(
        (entry) => entry.ok && entry.label.trim() === "K" && isValidGainMatrix(entry.value),
      );
      const prefixK =
        exactK ??
        s.recoveredEntries.find(
          (entry) =>
            entry.ok &&
            /^K[A-Za-z0-9_]*$/.test(entry.label.trim()) &&
            isValidGainMatrix(entry.value),
        );

      if (prefixK && prefixK.value) {
        kMat = prefixK.value;
        recoveryFormula = prefixK.formula;
      } else if (isValidGainMatrix(s.recoveredK)) {
        kMat = s.recoveredK;
      }

      if (!kMat) return null;

      const ssVal = selectedObj.value;
      const stateCoords =
        Array.isArray(ssVal.state_names) &&
        ssVal.state_names.length === desc.n &&
        ssVal.state_names.every((nm) => typeof nm === "string" && nm.trim().length > 0)
          ? (ssVal.state_names as string[])
          : Array.from({ length: desc.n }, (_, idx) => `x${idx + 1}`);
      const inputNames =
        Array.isArray(ssVal.input_names) &&
        ssVal.input_names.length === desc.m &&
        ssVal.input_names.every((nm) => typeof nm === "string")
          ? (ssVal.input_names as string[])
          : null;

      const feedbackSign = resolveSign(recoveryFormula);
      const ctrlDto: Record<string, unknown> = {
        schema_version: "1.0.0",
        id: `sf-${desc.id}`,
        revision: 1,
        kind: "StateFeedbackController",
        feedback_sign: feedbackSign,
        K: {
          shape: [kMat.rows, kMat.cols],
          dtype: "float64",
          order: "C",
          data: [...kMat.data],
        },
        state_coordinates: [...stateCoords],
        reference_map: null,
        dt: desc.dt ?? null,
        ...(inputNames ? { input_names: [...inputNames] } : {}),
        provenance: {
          source: "web.lmi_view.state_feedback_synthesis",
          template: this.currentTemplate,
        },
      };

      return {
        controller: ctrlDto,
        plant: structuredClone(ssVal),
        systemKind: "StateSpace",
        feedbackSign,
        canExportPathSim: true,
      };
    }

    return null;
  }

  public getLastRegisteredController(): Record<string, unknown> | null {
    if (
      !this.lastRegisteredController ||
      !this.lastRegisteredControllerContext ||
      !this.lastSolveContext ||
      this.lastRegisteredControllerContext.systemRefKey !== this.lastSolveContext.systemRefKey ||
      this.lastRegisteredControllerContext.dsl !== this.lastSolveContext.dsl
    ) {
      return null;
    }
    const activeDsl = this.codeEditorEl ? this.codeEditorEl.value : this.currentDsl;
    const desc = this.getSelectedSystemDescriptor();
    if (
      activeDsl !== this.lastRegisteredControllerContext.dsl ||
      desc.refKey !== this.lastRegisteredControllerContext.systemRefKey
    ) {
      return null;
    }
    return structuredClone(this.lastRegisteredController);
  }

  private updateControllerActionButtons(): void {
    const extracted = this.extractSynthesizedControllerGains();
    setButtonDisabled(this.registerControllerBtnEl, extracted === null);
    setButtonDisabled(
      this.exportPathSimBtnEl,
      extracted === null || !extracted.canExportPathSim,
    );
  }

  public async registerSynthesizedController(): Promise<Record<string, unknown> | null> {
    try {
      const extracted = this.extractSynthesizedControllerGains();
      if (!extracted) {
        return null;
      }
      const typed = this.shell.getTypedWorkspace();
      const lqr = this.shell.getLqrWorkspace();
      const projectId = lqr.getProjectId();
      const ctrlId = String(extracted.controller.id);

      let maxRev = 0;
      for (const item of typed.listRegisteredObjects()) {
        if (item.id === ctrlId) {
          maxRev = Math.max(maxRev, item.revision);
        }
      }
      if (typeof this.client.exportProject === "function") {
        try {
          const snap = await this.client.exportProject(projectId);
          if (snap && Array.isArray(snap.objects)) {
            for (const rec of snap.objects) {
              if (rec && rec.object_id === ctrlId && typeof rec.revision === "number") {
                maxRev = Math.max(maxRev, rec.revision);
              }
            }
          }
        } catch {
          // Ignore snapshot lookup failure and fall back to revision 1
        }
      }

      const nextRev = Math.max(1, maxRev + 1);
      const ctrlDto: Record<string, unknown> = {
        ...structuredClone(extracted.controller),
        revision: nextRev,
      };

      const desc = this.getSelectedSystemDescriptor();
      const valPayload: Record<string, unknown> = {
        plant: extracted.plant,
        controller: ctrlDto,
        ...(extracted.systemKind === "ts_partially_observed"
          ? {
              premise_estimator: {
                kind: "observer_reconstructed",
                unmeasured_premises: [...desc.unmeasuredPremises],
              },
            }
          : {}),
      };

      const valResp = await this.executeRpc("core.validate_interconnection", valPayload);
      if (valResp.status === "failure") {
        const isMockUnsupported =
          this.client.getCapabilities().engine_kind === "mock" &&
          valResp.error?.code === "UNSUPPORTED_MODEL" &&
          (valResp.error?.message ?? "").includes("MockWorkerAdapter");
        if (!isMockUnsupported) {
          throw new ControlLabBridgeError(
            valResp.error?.code ?? "VALIDATION_ERROR",
            valResp.error?.message ??
              "Falha ao validar compatibilidade física do controlador sintetizado.",
          );
        }
      }

      const ctrlKind = String(ctrlDto.kind);
      if (isTypedObjectKind(ctrlKind)) {
        await typed.registerTypedObject(ctrlDto, { source: "manual" });
      }
      await this.client.registerObject(projectId, ctrlId, nextRev, ctrlDto, {
        kind: ctrlKind,
        pinProject: true,
        persistToIndexedDB: true,
      });

      if (extracted.systemKind === "StateSpace") {
        const plantRef = { id: desc.id, revision: desc.revision };
        if (typed.getSelectableObject(plantRef)) {
          typed.selectRef("statespacePlant", plantRef, { allowHistoricalDowngrade: true });
        }
      }

      this.lastRegisteredController = structuredClone(ctrlDto);
      this.lastRegisteredControllerContext = this.lastSolveContext
        ? { ...this.lastSolveContext }
        : null;

      this.shell
        .getAnnouncer()
        .announce(
          `Controlador ${ctrlKind} '${ctrlId}#r${nextRev}' registrado no Workspace.`,
          "polite",
          "status",
        );
      this.renderCertificateAndSpectrum();
      this.onRequestRender?.();
      return structuredClone(ctrlDto);
    } catch (err: unknown) {
      this.shell.presentError(err);
      return null;
    }
  }

  public async exportPathSimSimulation(
    trigger: HTMLElement | null = null,
  ): Promise<string | null> {
    try {
      const extracted = this.extractSynthesizedControllerGains();
      if (!extracted || !extracted.canExportPathSim) {
        return null;
      }
      const desc = this.getSelectedSystemDescriptor();
      const safeId = desc.id.replace(/[^A-Za-z0-9_-]+/g, "_") || "plant";
      const suffix = extracted.systemKind === "ts_measured" ? "pdc" : "sf";
      const defaultFilename = `controllab_${safeId}_${suffix}_pathsim.py`;

      const activeCtrl = this.getLastRegisteredController() ?? extracted.controller;
      const resp = await this.executeRpc("io.export_pathsim_script", {
        plant: extracted.plant,
        controller: activeCtrl,
        filename: defaultFilename,
      });
      if (resp.status === "failure" || !resp.result) {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao exportar script PathSim (.py).",
        );
      }
      const res = resp.result as Record<string, unknown>;
      if (res.code_executed !== false || typeof res.script !== "string") {
        throw new ControlLabBridgeError(
          "INTERNAL_ERROR",
          "Resposta inválida de io.export_pathsim_script: esperado script Python passivo com code_executed=false.",
        );
      }
      const filename =
        typeof res.filename === "string" && res.filename.trim().length > 0
          ? res.filename.trim()
          : defaultFilename;
      this.onOpenExportModal?.(
        {
          title: "Script PathSim Offline (Execução Manual Explícita — ADR-013)",
          filename,
          mimeType: "text/x-python;charset=utf-8",
          content: res.script,
          offlineDesign: true,
        },
        trigger,
      );
      this.shell
        .getAnnouncer()
        .announce(
          `Script PathSim (.py) '${filename}' exportado em modo passivo (execução manual explícita, ADR-013).`,
          "polite",
          "status",
        );
      return res.script;
    } catch (err: unknown) {
      this.shell.presentError(err);
      return null;
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
    const available = this.listAvailableWorkspaceSystems();
    const desc = this.getSelectedSystemDescriptor();

    // Update #lmi-workspace-system-select options
    if (this.workspaceSystemSelectEl) {
      const optionsHtml = available
        .map((item) => {
          const kindLabel =
            item.kind === "polytopic_uncertain"
              ? "Politópico"
              : item.kind === "ts_measured"
                ? "TS (Medido)"
                : item.kind === "ts_partially_observed"
                  ? "TS (Não Medido)"
                  : "SS";
          const friendly = formatDockObjectDisplayName(item.id);
          const label = `${friendly} [${item.id}#r${item.revision}] (${kindLabel})`;
          const sel = item.key === desc.refKey ? " selected" : "";
          return `<option value="${escapeHtml(item.key)}"${sel}>${escapeHtml(label)}</option>`;
        })
        .join("");
      if (optionsHtml !== this.lastSystemSelectHtmlKey) {
        this.workspaceSystemSelectEl.innerHTML = optionsHtml;
        this.lastSystemSelectHtmlKey = optionsHtml;
      }
      this.workspaceSystemSelectEl.value = desc.refKey;
    }

    if (this.expandedBlocksBadgeEl) {
      const count = this.parsed.expandedBlockCount;
      this.expandedBlocksBadgeEl.textContent = `${count} bloco${count === 1 ? "" : "s"} LMI expandido${count === 1 ? "" : "s"}`;
    }
    this.renderFusionBadge();

    if (this.selectedSystemSummaryEl) {
      const domainLabel = desc.dt === null ? "Contínuo" : `Discreto (dt=${desc.dt} s)`;
      const friendlyName = formatDockObjectDisplayName(desc.id);
      const pills: string[] = [];
      let detailsLines: string[] = [];

      if (desc.kind === "StateSpace") {
        const isGen = Boolean(desc.generalized?.enable_w || desc.generalized?.enable_z);
        pills.push(
          `<span class="badge ${isGen ? "badge-exact" : "badge-stable"}">${isGen ? "Planta Generalizada (LTI)" : "Linear (LTI)"}</span>`,
        );
        pills.push(`<span class="badge">n=${desc.n}, m=${desc.m}, p=${desc.p}</span>`);
        pills.push(`<span class="badge">${escapeHtml(domainLabel)}</span>`);
        if (isGen && desc.generalized) {
          const chParts: string[] = [];
          if (desc.generalized.enable_w) {
            const nw = desc.generalized.Bw?.[0]?.length ?? 1;
            chParts.push(`w (n_w=${nw}: Bw, Dyw)`);
          }
          if (desc.generalized.enable_z) {
            const nz = desc.generalized.Cz?.length ?? desc.p;
            chParts.push(`z (n_z=${nz}: Cz, Dzu${desc.generalized.enable_w ? ", Dzw" : ""})`);
          }
          detailsLines.push(`<strong>Canais Generalizados:</strong> ${escapeHtml(chParts.join(" • "))}`);
        }
      } else if (desc.kind === "polytopic_uncertain") {
        pills.push(`<span class="badge badge-exact">Politópico Incerto</span>`);
        pills.push(`<span class="badge badge-sufficient">N_v = ${desc.vertices.length} vértices</span>`);
        pills.push(`<span class="badge">n=${desc.n}, m=${desc.m}, p=${desc.p}</span>`);
        pills.push(`<span class="badge">${escapeHtml(domainLabel)}</span>`);
        detailsLines.push(
          `<strong>Politopo 𝒫 = co{G₁..G${formatSubscript(desc.vertices.length)}}:</strong> ${desc.vertices.length} vértices carregados do Workspace.`,
        );
      } else {
        const isUnmeasured = desc.kind === "ts_partially_observed";
        pills.push(
          `<span class="badge ${isUnmeasured ? "badge-beta" : "badge-exact"}">${isUnmeasured ? "Takagi-Sugeno (ts_partially_observed)" : "Takagi-Sugeno (ts_measured)"}</span>`,
        );
        pills.push(`<span class="badge badge-sufficient">N_r = ${desc.vertices.length} regras</span>`);
        pills.push(`<span class="badge">n=${desc.n}, m=${desc.m}, p=${desc.p}</span>`);
        pills.push(`<span class="badge">${escapeHtml(domainLabel)}</span>`);

        const premParts: string[] = [];
        for (const pName of desc.measuredPremises) {
          const b = desc.bounds[pName];
          premParts.push(`${pName}${b ? ` ∈ [${b[0]}, ${b[1]}]` : ""} (Medida)`);
        }
        for (const pName of desc.unmeasuredPremises) {
          const b = desc.bounds[pName];
          premParts.push(`${pName}${b ? ` ∈ [${b[0]}, ${b[1]}]` : ""} (Não Medida)`);
        }
        if (premParts.length > 0) {
          detailsLines.push(`<strong>Premissas:</strong> ${escapeHtml(premParts.join(", "))}`);
        }
        if (desc.convexity) {
          const cvCls = desc.convexity.valid ? "badge-stable" : "badge-unstable";
          const cvLabel = desc.convexity.valid ? "∑hᵢ(z)=1 Válida" : "∑hᵢ(z)=1 Inválida";
          detailsLines.push(
            `<span class="badge ${cvCls}">${cvLabel}</span> <span>${escapeHtml(desc.convexity.message)}</span>`,
          );
        }
        if (isUnmeasured) {
          detailsLines.push(
            `<div class="warning-callout" role="status"><strong>ts_partially_observed:</strong> Há premissas não medidas (ẑ). Configure as perturbações dA[k]/dC[k] abaixo para síntese do observador TS.</div>`,
          );
        }
      }

      this.selectedSystemSummaryEl.innerHTML = [
        `<div class="lmi-sys-summary-head"><strong>${escapeHtml(friendlyName)}</strong> <code>${escapeHtml(desc.id)}#r${desc.revision}</code></div>`,
        `<div class="lmi-sys-summary-pills">${pills.join(" ")}</div>`,
        detailsLines.length > 0
          ? `<div class="lmi-sys-summary-details">${detailsLines.map((l) => `<div>${l}</div>`).join("")}</div>`
          : "",
      ].join("");
    }

    setElHidden(this.tsUnmeasuredPanelEl, desc.kind !== "ts_partially_observed");
    if (this.tsObsMethodEl) this.tsObsMethodEl.value = this.tsObsMethod;
    if (this.tsObsDaEl && this.tsObsDaEl.value !== this.tsObsDaText) {
      this.tsObsDaEl.value = this.tsObsDaText;
    }
    if (this.tsObsDcEl && this.tsObsDcEl.value !== this.tsObsDcText) {
      this.tsObsDcEl.value = this.tsObsDcText;
    }

    if (this.primaryIndexNameEl && this.primaryIndexNameEl.value !== this.primaryIndexName) {
      this.primaryIndexNameEl.value = this.primaryIndexName;
    }
    if (this.extraIndicesEl && this.extraIndicesEl.value !== this.extraIndices) {
      this.extraIndicesEl.value = this.extraIndices;
    }
    if (this.sysIndicesSummaryEl) {
      const primary = desc.systemClass === "lti" ? null : (this.primaryIndexName.trim() || "i");
      const extras = this.extraIndices
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const all = primary ? [primary, ...extras] : extras;
      const N = desc.vertices.length > 0 ? desc.vertices.length : this.parsed.effectiveSystemN;
      this.sysIndicesSummaryEl.innerHTML =
        all.length > 0
          ? `<strong>Índices na DSL:</strong> ${escapeHtml(all.join(", "))} ∈ {1..${N}}`
          : `<strong>Modo LTI:</strong> Sem índice obrigatório (adicione se necessário).`;
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
    const desc = this.getSelectedSystemDescriptor();
    const dims = { n: desc.n, m: desc.m, p: desc.p };
    if (this.envelopeBannerEl) {
      const tpl = this.parsed.inferredTemplate;
      const isHinf = tpl === "hinf_brl" || tpl === "hinf_generalized_brl";
      const nVars = this.estimateDslVariables(dims);
      const maxNForFast = isHinf ? 44 : 56;
      const estMaxBlockDim = isHinf ? dims.n + 2 : dims.n;
      const estConeEntries = this.parsed.expandedBlockCount * estMaxBlockDim * estMaxBlockDim;
      const exceedsHardLimit =
        nVars > BROWSER_ENVELOPE.max_variables ||
        estMaxBlockDim > BROWSER_ENVELOPE.max_block_dimension ||
        estConeEntries > BROWSER_ENVELOPE.max_cone_entries;
      const isExtendedTier =
        !exceedsHardLimit &&
        (nVars > BROWSER_ENVELOPE.fast_max_variables ||
          dims.n > maxNForFast ||
          this.parsed.expandedBlockCount > 64);

      if (exceedsHardLimit) {
        setElHidden(this.envelopeBannerEl, false);
        toggleCssClass(this.envelopeBannerEl, "lmi-envelope-extended", false);
        toggleCssClass(this.envelopeBannerEl, "lmi-envelope-hard-limit", true);
        this.envelopeBannerEl.innerHTML = `<strong>Limite do motor navegador (ADR-010):</strong> Planta com n=${dims.n} estados, ~${nVars} variáveis (limite máximo no navegador: max_variables=${BROWSER_ENVELOPE.max_variables}, max_block_dimension=${BROWSER_ENVELOPE.max_block_dimension}, max_cone_entries=${BROWSER_ENVELOPE.max_cone_entries}) e ${this.parsed.expandedBlockCount} bloco(s) LMI. Recomenda-se usar <strong>Exportar CVXPY / YALMIP</strong> para execução offline com MOSEK/SCS.`;
      } else if (isExtendedTier) {
        setElHidden(this.envelopeBannerEl, false);
        toggleCssClass(this.envelopeBannerEl, "lmi-envelope-extended", true);
        toggleCssClass(this.envelopeBannerEl, "lmi-envelope-hard-limit", false);
        this.envelopeBannerEl.innerHTML = `<strong>Faixa estendida no navegador (~${nVars} variáveis, n=${dims.n}):</strong> Execução longa no navegador (~10 s a ~3 min): acompanhe o log por iteração, use <strong>Cancelar</strong> se necessário ou <strong>Exportar CVXPY / YALMIP</strong> (faixa rápida ≤ ${BROWSER_ENVELOPE.fast_max_variables} variáveis; limite máximo max_variables=${BROWSER_ENVELOPE.max_variables}).`;
      } else {
        setElHidden(this.envelopeBannerEl, true);
        toggleCssClass(this.envelopeBannerEl, "lmi-envelope-extended", false);
        toggleCssClass(this.envelopeBannerEl, "lmi-envelope-hard-limit", false);
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
        : `<span class="badge">Sistema: ${escapeHtml(desc.systemClass)} (N=${this.parsed.effectiveSystemN})</span>`;
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
    this.updateControllerActionButtons();
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

    const friendlySolverLabel = (raw: string): string => {
      if (raw === "optimal") return "Ótimo";
      if (raw === "optimal_inaccurate") return "Ótimo (impreciso)";
      if (raw === "infeasible") return "Infactível";
      if (raw === "unbounded") return "Ilimitado";
      if (raw === "cancelled") return "Cancelado";
      return raw;
    };
    const friendlyAuditLabel = (raw: string): string => {
      if (raw === "strictly_feasible") return "Estritamente Factível";
      if (raw === "approximately_feasible") return "Aprox. Factível";
      if (raw === "infeasible") return "Infactível";
      if (raw === "inconclusive") return "Inconclusivo";
      return raw;
    };
    const friendlyCertLabel = (raw: string): string => {
      if (raw === "validated_dual") return "Dual Validado";
      if (raw === "validated_primal") return "Primal Validado";
      if (raw === "failed" || raw === "unvalidated") return "Não Validado";
      return raw;
    };
    const friendlyCondLabel = (raw: string): string => {
      if (raw === "well_conditioned") return "Bem Condicionado";
      if (raw === "ill_conditioned") return "Mal Condicionado";
      if (raw === "near_boundary") return "Próx. à Fronteira";
      return raw;
    };
    const friendlyCtrlLabel = (raw: string): string => {
      if (raw.startsWith("verified")) return "Verificado";
      if (raw === "not_applicable") return "Não Aplicável";
      if (raw === "violated") return "Violado";
      return raw;
    };

    if (this.certDimsEl) {
      this.certDimsEl.innerHTML = [
        `<div class="lmi-cert-dim"><span class="kpi-label">1. Solver Status</span><span class="badge ${solverCls}">${escapeHtml(friendlySolverLabel(s.solverStatus))}</span><code class="cert-token">${escapeHtml(s.solverStatus)}</code></div>`,
        `<div class="lmi-cert-dim"><span class="kpi-label">2. Auditoria Factibilidade</span><span class="badge ${auditCls}">${escapeHtml(friendlyAuditLabel(s.auditFeasibility))}</span><code class="cert-token">${escapeHtml(s.auditFeasibility)}</code></div>`,
        `<div class="lmi-cert-dim"><span class="kpi-label">3. Certificado Dual</span><span class="badge ${certCls}">${escapeHtml(friendlyCertLabel(s.certificateStatus))}</span><code class="cert-token">${escapeHtml(s.certificateStatus)}</code></div>`,
        `<div class="lmi-cert-dim"><span class="kpi-label">4. Condicionamento κ</span><span class="badge ${condCls}">${escapeHtml(friendlyCondLabel(s.conditioningStatus))} (κ=${escapeHtml(kappaStr)})</span><code class="cert-token">${escapeHtml(s.conditioningStatus)}</code></div>`,
        `<div class="lmi-cert-dim"><span class="kpi-label">5. Validade Controlador</span><span class="badge ${ctrlCls}">${escapeHtml(friendlyCtrlLabel(s.controllerValidity))}</span><code class="cert-token">${escapeHtml(s.controllerValidity)}</code></div>`,
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
      if (s.fusionStats && s.fusionStats.eliminatedSymmetricPairs > 0) {
        const n = s.fusionStats.eliminatedSymmetricPairs;
        const pairLabel = n === 1 ? "1 par simétrico fundido" : `${n} pares simétricos fundidos`;
        alerts.push(
          `<p class="json-format-hint"><strong>Fusão simétrica (ADR-015):</strong> ${escapeHtml(pairLabel)} (${s.fusionStats.originalBlocks} → ${s.fusionStats.fusedBlocks} blocos LMI).</p>`,
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
      const copyItems: LmiNamedMatrix[] = [];
      const primaryCardsHtml: string[] = [];
      const warningItemsHtml: string[] = [];

      const objHtml =
        s.objective !== null
          ? `<div class="lmi-recovered-item"><strong>Objetivo:</strong> <code class="tabular-num">${formatNumericDisplay(s.objective, decimals)}</code></div>`
          : "";

      if (s.recoveredEntries.length > 0) {
        for (const entry of s.recoveredEntries) {
          const isK = entry.label === "K" || /^K\[/.test(entry.label);
          const isL = entry.label === "L" || /^L\[/.test(entry.label);
          const displayLabel = isK
            ? `Ganho recuperado ${entry.label}`
            : isL
              ? `Ganho do observador ${entry.label}`
              : entry.label;
          if (!entry.ok || !entry.value) {
            warningItemsHtml.push(
              `<div class="lmi-recovered-item warning-callout" role="status"><strong>${escapeHtml(displayLabel)}</strong> <code>(${escapeHtml(entry.formula)})</code>: aviso na recuperação — ${escapeHtml(entry.error ?? "expressão não avaliada")}</div>`,
            );
          } else {
            copyItems.push({
              label: entry.label,
              formula: entry.formula,
              mat: entry.value,
              isScalar: Boolean(entry.isScalar),
            });
            primaryCardsHtml.push(
              renderLmiMatrixCardHtml(
                displayLabel,
                entry.label,
                entry.formula,
                entry.value,
                decimals,
                Boolean(entry.isScalar),
              ),
            );
          }
        }
      } else if (
        s.recoveredK ||
        (s.recoveredIndexedK && s.recoveredIndexedK.length > 0) ||
        (s.recoveredIndexedL && s.recoveredIndexedL.length > 0)
      ) {
        if (s.recoveredIndexedK && s.recoveredIndexedK.length > 0) {
          for (const item of s.recoveredIndexedK) {
            copyItems.push({ label: item.label, mat: item.mat });
            primaryCardsHtml.push(
              renderLmiMatrixCardHtml(
                `Ganho recuperado ${item.label}`,
                item.label,
                null,
                item.mat,
                decimals,
              ),
            );
          }
        }
        if (s.recoveredIndexedL && s.recoveredIndexedL.length > 0) {
          for (const item of s.recoveredIndexedL) {
            copyItems.push({ label: item.label, mat: item.mat });
            primaryCardsHtml.push(
              renderLmiMatrixCardHtml(
                `Ganho do observador ${item.label}`,
                item.label,
                null,
                item.mat,
                decimals,
              ),
            );
          }
        }
        if (primaryCardsHtml.length === 0 && s.recoveredK) {
          copyItems.push({ label: "K", formula: "Y * inv(Q)", mat: s.recoveredK });
          primaryCardsHtml.push(
            renderLmiMatrixCardHtml(
              "Ganho recuperado K = Y Q⁻¹",
              "K",
              null,
              s.recoveredK,
              decimals,
            ),
          );
        }
        if (s.recoveredScalars && s.recoveredScalars.length > 0) {
          for (const sc of s.recoveredScalars) {
            const scMat: DenseMatrixValue = { rows: 1, cols: 1, data: [sc.value] };
            copyItems.push({ label: sc.name, mat: scMat, isScalar: true });
            primaryCardsHtml.push(
              renderLmiMatrixCardHtml(sc.name, sc.name, null, scMat, decimals, true),
            );
          }
        }
      }

      const decisionVarCardsHtml: string[] = [];
      if (s.solvedVariables.length > 0) {
        for (const v of s.solvedVariables) {
          if (!copyItems.some((ci) => ci.label === v.name)) {
            copyItems.push({ label: v.name, mat: v.mat });
          }
          decisionVarCardsHtml.push(
            renderLmiMatrixCardHtml(v.name, v.name, null, v.mat, decimals),
          );
        }
      }

      const copyBtnHtml =
        copyItems.length > 0
          ? `<button type="button" id="btn-lmi-copy-matrices" class="touch-control btn-secondary btn-small" data-action="lmi-copy-matrices">Copiar Matrizes</button>`
          : "";

      const sectionsHtml: string[] = [];
      if (primaryCardsHtml.length > 0 || warningItemsHtml.length > 0) {
        sectionsHtml.push(
          `<div class="lmi-recovered-matrices-head"><h5>Ganhos &amp; Expressões Recuperadas</h5>${copyBtnHtml}</div>`,
        );
        if (primaryCardsHtml.length > 0) {
          sectionsHtml.push(`<div class="lmi-matrices-grid">${primaryCardsHtml.join("")}</div>`);
        }
        if (warningItemsHtml.length > 0) {
          sectionsHtml.push(`<div class="lmi-recovered-list">${warningItemsHtml.join("")}</div>`);
        }
        if (objHtml) sectionsHtml.push(objHtml);
        if (decisionVarCardsHtml.length > 0) {
          sectionsHtml.push(
            `<details class="lmi-solved-vars-details"><summary>Variáveis de decisão obtidas (${s.solvedVariables.length})</summary><div class="lmi-matrices-grid">${decisionVarCardsHtml.join("")}</div></details>`,
          );
        }
      } else if (decisionVarCardsHtml.length > 0) {
        sectionsHtml.push(
          `<div class="lmi-recovered-matrices-head"><h5>Variáveis de Decisão Obtidas (${s.solvedVariables.length})</h5>${copyBtnHtml}</div>`,
        );
        sectionsHtml.push(
          `<details class="lmi-solved-vars-details" open><summary>Variáveis de decisão obtidas (${s.solvedVariables.length})</summary><div class="lmi-matrices-grid">${decisionVarCardsHtml.join("")}</div>${objHtml}</details>`,
        );
      } else {
        const objInline =
          s.objective !== null
            ? ` | <strong>Objetivo:</strong> <code>${formatNumericDisplay(s.objective, decimals)}</code>`
            : "";
        sectionsHtml.push(`<p><strong>Ganho K:</strong> N/D para esta formulação${objInline}</p>`);
      }

      const regCtrl = this.getLastRegisteredController();
      const regBadge = regCtrl
        ? `<div class="lmi-registered-controller-status"><span class="badge badge-stable">Controlador Registrado no Workspace</span> <code>${escapeHtml(String(regCtrl.id))}#r${Number(regCtrl.revision)}</code> (${escapeHtml(String(regCtrl.kind))}, <code>feedback_sign=${escapeHtml(String(regCtrl.feedback_sign))}</code>)</div>`
        : "";

      this.recoveredGainEl.innerHTML = `<div id="lmi-recovered-matrices-display" class="lmi-recovered-matrices-display">${sectionsHtml.join("")}${regBadge}</div>`;

      if (copyItems.length > 0) {
        const copyText = formatLmiMatricesCopyText(copyItems, decimals);
        this.recoveredGainEl
          .querySelector<HTMLElement>("#btn-lmi-copy-matrices")
          ?.addEventListener("click", () => {
            try {
              const nav = typeof navigator !== "undefined" ? navigator : null;
              if (nav?.clipboard && typeof nav.clipboard.writeText === "function") {
                void nav.clipboard.writeText(copyText).catch(() => {
                  // Safe fallback in restricted/headless contexts
                });
              }
            } catch {
              // Safe fallback when clipboard API is unavailable
            }
            this.shell
              .getAnnouncer()
              .announce("Matrizes LMI recuperadas copiadas.", "polite", "status");
          });
      }
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

    this.parsed = parseLmiDsl(this.currentDsl, this.buildParseOptions());
    this.renderCharacterizationCard();
    this.renderEditorAndMath();
    this.renderCertificateAndSpectrum();
  }
}
