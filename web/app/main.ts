/**
 * Adaptador DOM/browser para o ControlLab Web (alinhado com `/index.html` e `/app/main.js`
 * em `web/worker/service_worker.ts`).
 *
 * Mantém a árvore interativa principal (abas, slider, inputs) persistente entre
 * atualizações de estado para preservar captura de ponteiro a 60 FPS e foco de teclado,
 * atualizando seletivamente slots de gráficos, tabela acessível, ferramentas e modais.
 *
 * 100% compatível com erasableSyntaxOnly e verbatimModuleSyntax.
 */

import type { ControlLabEngineClient } from "../bridge/client.ts";
import { ControlLabBridgeError, type RealTensor } from "../bridge/protocol.ts";
import { MockWorkerAdapter } from "../bridge/mock_adapter.ts";
import { PyodideEngineClient } from "../bridge/pyodide_client.ts";
import {
  escapeHtml,
  formatMatrixDisplay,
  formatNumericDisplay,
  getSliderAriaAttributes,
  getTabAriaAttributes,
  getTabPanelAriaAttributes,
  type AccessibleSliderConfig,
} from "./accessibility.ts";
import { ControlLabShell, DEFAULT_DYNAMIC_EXPORT_CONTROLLER } from "./shell.ts";
import {
  PROJECT_TAB_IDS,
  PROJECT_TAB_METADATA,
  type ProjectTabId,
} from "./tool_descriptor.ts";
import {
  buildAccessibleChartTable,
  getChartExportFilename,
  renderAccessibleTableHtml,
  renderBodeSvg,
  renderNyquistSvg,
  renderPoleZeroSvg,
  renderResidualCorrelationSvg,
  renderRootLocusSvg,
  renderSvgMarkupToPngBlob,
  renderTimeResponseSvg,
  serializeSvgForExport,
} from "../charts/scientific_chart.ts";
import {
  encodeObjectRefKey,
  decodeObjectRefKey,
  TYPED_SELECTION_ROLES,
  type TypedSelectionRole,
} from "../features/typed_workspace.ts";
import type { CanonicalStateSpaceModel } from "../features/lqr_workspace.ts";
import {
  renderNewObjectModalHtml,
  renderWorkspaceDockHtml,
  WorkspaceDockController,
} from "./workspace_dock.ts";
import {
  InspectorDrawerController,
  renderInspectorDrawerHtml,
} from "./inspector_drawer.ts";

export interface MountControlLabOptions {
  engineMode?: "pyodide" | "mock";
  client?: ControlLabEngineClient;
  project_id?: string;
  workerUrl?: string | URL;
}

// Build F9 preserva app/main.js relativo à raiz publicada, inclusive sob prefixos.
export function resolveBrowserRuntimeAssets(moduleUrl: string) {
  const base = new URL("../", moduleUrl);
  return Object.freeze({
    workerUrl: new URL("worker/pyodide_worker.js", base).href,
    serviceWorkerUrl: new URL("service_worker.js", base).href,
    serviceWorkerScope: base.href,
    pyodideIndexUrl: new URL("pyodide/", base).href,
    controlLabWheel: new URL("wheels/control_lab-1.0.0-py3-none-any.whl", base).href,
  });
}
export const BROWSER_RUNTIME_ASSETS = resolveBrowserRuntimeAssets(import.meta.url);

/** Registro não é prova de cache completo nem de cálculo offline (G-0A/G-0C pendentes). */
export async function registerControlLabServiceWorker(
  serviceWorker: Pick<ServiceWorkerContainer, "register"> | undefined,
  assets = BROWSER_RUNTIME_ASSETS,
): Promise<ServiceWorkerRegistration | null> {
  if (!serviceWorker) return null;
  return serviceWorker.register(assets.serviceWorkerUrl, {
    type: "module", scope: assets.serviceWorkerScope, updateViaCache: "none",
  });
}

export interface MountedControlLabApp {
  shell: ControlLabShell;
  client: ControlLabEngineClient;
  destroy(): void;
}

interface ExportModalPayload {
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

function setHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function toggleCssClass(el: Element | null | undefined, className: string, active: boolean): void {
  if (!el) return;
  const current = (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean);
  const has = current.includes(className);
  if (active && !has) {
    current.push(className);
    el.setAttribute("class", current.join(" "));
  } else if (!active && has) {
    el.setAttribute("class", current.filter((c) => c !== className).join(" "));
  }
}

function readTabFromLocationHash(): ProjectTabId | null {
  try {
    const hash = globalThis.location?.hash ?? "";
    const match = /^#tab=([a-z0-9_]+)$/i.exec(hash.trim());
    if (match && (PROJECT_TAB_IDS as readonly string[]).includes(match[1])) {
      return match[1] as ProjectTabId;
    }
  } catch {
    // ignore in non-browser environments
  }
  return null;
}

function writeTabToLocationHash(tabId: ProjectTabId): void {
  try {
    globalThis.history?.replaceState?.(null, "", `#tab=${tabId}`);
  } catch {
    // ignore in non-browser / restricted environments
  }
}

interface LqrPresetSpec {
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

const LQR_PRESETS: Record<string, LqrPresetSpec> = {
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

function normalizePlantJsonInput(
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

function normalizeWeightsJsonInput(
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

function parseCommaNumberList(raw: string, fieldName: string): number[] {
  const parts = raw
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  if (parts.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${fieldName} deve conter ao menos um coeficiente numérico.`,
    );
  }
  const nums = parts.map((p) => Number(p));
  if (nums.some((v) => !Number.isFinite(v))) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${fieldName} contém valor não numérico ou não finito.`,
    );
  }
  return nums;
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

function renderChartExportBarHtml(slotId: string, label: string): string {
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

function triggerBlobDownload(blob: Blob, filename: string, doc: Document): void {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return;
  }
  const objectUrl = URL.createObjectURL(blob);
  const anchor = doc.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.style.display = "none";
  doc.body?.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

function triggerBrowserDownload(payload: ExportModalPayload, doc: Document): void {
  if (typeof Blob === "undefined" || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return;
  }
  const blob = new Blob([payload.bytes ? new Uint8Array(payload.bytes).buffer : payload.content], { type: payload.mimeType });
  triggerBlobDownload(blob, payload.filename, doc);
}

export function mountControlLabApp(
  container: HTMLElement,
  options?: MountControlLabOptions,
): MountedControlLabApp {
  const client: ControlLabEngineClient =
    options?.client ??
    (options?.engineMode === "mock"
      ? new MockWorkerAdapter()
      : new PyodideEngineClient({
          workerUrl: options?.workerUrl ?? BROWSER_RUNTIME_ASSETS.workerUrl,
          initOptions: {
            indexURL: BROWSER_RUNTIME_ASSETS.pyodideIndexUrl,
            packages: ["numpy", "scipy", BROWSER_RUNTIME_ASSETS.controlLabWheel],
          },
        }));

  const initialTabFromHash = readTabFromLocationHash();
  const shell = new ControlLabShell({
    client,
    project_id: options?.project_id ?? "proj-controllab-web",
    ...(initialTabFromHash ? { initialTab: initialTabFromHash } : {}),
  });
  const lqr = shell.getLqrWorkspace();
  const tabsCtrl = shell.getTabsController();
  const typedWorkspace = shell.getTypedWorkspace();
  const idWorkspace = shell.getIdentificationWorkspace();
  const sisoWorkspace = shell.getSisoWorkspace();
  const doc = container.ownerDocument;

  let serviceWorkerStatus = "cache não verificado";
  let dragStartQScale = 1.0;
  let lastExportPayload: ExportModalPayload | null = null;
  let lastToolsHtmlKey = "";
  let lastTypedWorkspaceHtmlKey = "";
  let renderedPvmExportRevision = -1;
  let lastSyncedHashTab: ProjectTabId = shell.getActiveTab();
  let lastSyncedLqrEditorKey = "";
  let editorDims = {
    n: lqr.getPlant().matrices.A.shape[0],
    m: lqr.getPlant().matrices.B.shape[1],
    p: lqr.getPlant().matrices.C.shape[0],
  };

  const ROLE_LABELS: Record<TypedSelectionRole, string> = {
    statespacePlant: "Planta em Espaço de Estados (StateSpace)",
    frequencyPlant: "Modelo para Análise em Frequência (SS / TF)",
    dataset: "Série Temporal de Treino (Dataset)",
    valDataset: "Série Temporal de Validação / Holdout",
    fuzzySystem: "Sistema Fuzzy",
    tsModel: "Modelo Takagi-Sugeno (TS)",
    validationModel: "Modelo para Validação Cruzada",
    reuseSource: "Modelo de Origem para Conversão",
  };

  let projectTitle = "Projeto ControlLab";

  const tabsHtml = PROJECT_TAB_IDS.map((tabId) => {
    const meta = PROJECT_TAB_METADATA[tabId];
    const attrs = getTabAriaAttributes(
      tabId,
      `panel-${tabId}`,
      tabId === shell.getActiveTab(),
    );
    const attrStr = Object.entries(attrs)
      .map(([k, v]) => `${k}="${escapeHtml(v)}"`)
      .join(" ");
    return `<button type="button" class="touch-control" data-tab-id="${escapeHtml(tabId)}" ${attrStr}>${escapeHtml(meta.label)}</button>`;
  }).join("");

  const presetOptionsHtml = Object.values(LQR_PRESETS)
    .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`)
    .join("");

  container.innerHTML = [
    `<header class="controllab-header">`,
    `<div class="brand">`,
    `<div class="brand-mark" aria-hidden="true">∿</div>`,
    `<div class="brand-text">`,
    `<div class="brand-title-row">`,
    `<h1>ControlLab Web</h1>`,
    `<input id="project-title-input" class="touch-control project-title-input" type="text" value="${escapeHtml(projectTitle)}" aria-label="Nome do projeto ativo" />`,
    `</div>`,
    `<div class="header-meta">`,
    `<span id="engine-status-badge" class="badge status-badge"></span>`,
    `<span id="revision-summary" class="revision-summary"></span>`,
    `</div>`,
    `</div>`,
    `</div>`,
    `<div class="panel-actions header-controls">`,
    `<button type="button" id="btn-toggle-workspace-dock" class="touch-control btn-secondary btn-small" data-action="toggle-workspace-dock" aria-expanded="true">Workspace</button>`,
    `<button type="button" id="btn-toggle-inspector" class="touch-control btn-secondary btn-small" data-action="toggle-inspector" aria-expanded="false">Inspetor R-27</button>`,
    `<label for="decimals-select" class="compact-label">Casas decimais</label>`,
    `<input id="decimals-select" class="touch-control decimals-input" type="number" min="0" max="15" value="${shell.getDisplayDecimals()}" data-action="decimals" />`,
    `<button type="button" id="theme-toggle-btn" class="touch-control btn-secondary" data-action="toggle-theme"></button>`,
    `</div>`,
    `</header>`,
    `<nav aria-label="Áreas de projeto" class="controllab-tablist" role="tablist">${tabsHtml}</nav>`,
    `<div class="app-workbench-shell">`,
    renderWorkspaceDockHtml(),
    `<main id="controllab-main" class="controllab-main" role="tabpanel" tabindex="0">`,
    `<section class="panel-card">`,
    `<h2 id="controllab-tab-heading"></h2>`,
    `<div id="controllab-error-slot"></div>`,
    `<section id="identification-workspace-panel" class="panel-card workspace-section" aria-label="Identificação de Sistemas">`,
    `<h3>Identificação de Sistemas (Dados → Estimação → Validação)</h3>`,
    `<div class="workspace-two-col">`,
    `<div class="workspace-controls-col">`,
    `<div class="subcard">`,
    `<div class="tool-field">`,
    `<label for="id-csv-input">Importar Dataset CSV (t, u, y) ou Carregar Benchmark PRBS / Entrada Constante</label>`,
    `<textarea id="id-csv-input" class="touch-control" rows="2" data-field="id-csv-input" aria-label="Conteúdo CSV do Dataset (t, u, y)"></textarea>`,
    `<div class="panel-actions">`,
    `<label for="id-train-fraction">Fração Treino (0.1–0.9)</label>`,
    `<input type="number" id="id-train-fraction" class="touch-control" min="0.2" max="0.85" step="0.05" value="0.7" aria-label="Fração de treino para particionamento holdout" />`,
    `<button type="button" id="btn-id-import-csv" class="touch-control btn-primary" data-action="id-import-csv">Importar CSV + Particionar</button>`,
    `<button type="button" id="btn-id-load-prbs" class="touch-control btn-primary" data-action="id-load-prbs">Benchmark PRBS (Treino + Holdout)</button>`,
    `<button type="button" id="btn-id-load-const-pe" class="touch-control btn-secondary" data-action="id-load-const-pe">Dataset Entrada Constante (Sem Excitação)</button>`,
    `<button type="button" id="btn-id-split-dataset" class="touch-control btn-secondary" data-action="id-split-dataset">Particionar Dataset Selecionado</button>`,
    `</div>`,
    `</div>`,
    `</div>`,
    `<div class="subcard">`,
    `<div class="tool-field">`,
    `<label for="id-chart-partition-select">Partição Visualizada nos Gráficos de Identificação</label>`,
    `<select id="id-chart-partition-select" class="touch-control" data-action="id-select-partition" aria-label="Partição visualizada nos gráficos de identificação">`,
    `<option value="validation">Validação / Holdout</option>`,
    `<option value="train">Treino</option>`,
    `</select>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-id-reuse-to-lqr" class="touch-control btn-secondary" data-action="id-reuse-to-lqr">Enviar para Espaço de Estados / LQR →</button>`,
    `<button type="button" id="btn-id-reuse-to-siso" class="touch-control btn-secondary" data-action="id-reuse-to-siso">Enviar para Análise SISO →</button>`,
    `</div>`,
    `</div>`,
    `</div>`,
    `<div class="workspace-results-col">`,
    `<div id="id-diagnostics-panel" class="diagnostics-panel" aria-live="polite"></div>`,
    `<div class="chart-card">`,
    `<div id="id-response-chart-slot" class="chart-container"></div>`,
    renderChartExportBarHtml("id-response-chart-slot", "Resposta Temporal"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="id-residuals-chart-slot" class="chart-container"></div>`,
    renderChartExportBarHtml("id-residuals-chart-slot", "Correlação de Resíduos"),
    `</div>`,
    `<details><summary>Tabela acessível de comparação temporal da identificação (WCAG 2.2 AA)</summary><div id="id-response-table-slot"></div></details>`,
    `<details><summary>Tabela acessível de correlação de resíduos R_ee / R_ue (WCAG 2.2 AA)</summary><div id="id-residuals-table-slot"></div></details>`,
    `</div>`,
    `</div>`,
    `</section>`,
    `<section id="siso-workspace-panel" class="panel-card workspace-section" aria-label="Análise e Projeto SISO na Frequência">`,
    `<h3>Análise &amp; Projeto SISO na Frequência</h3>`,
    `<div class="workspace-two-col">`,
    `<div class="workspace-controls-col">`,
    `<div class="subcard tool-field">`,
    `<label>Parâmetros de Resposta em Frequência (Bode / Nyquist / Margens)</label>`,
    `<div class="panel-actions">`,
    `<label for="siso-w-min">ω_min (rad/s)</label>`,
    `<input type="number" id="siso-w-min" class="touch-control" min="0.0001" max="1000" step="0.01" value="0.01" aria-label="Frequência mínima ω_min" />`,
    `<label for="siso-w-max">ω_max (rad/s)</label>`,
    `<input type="number" id="siso-w-max" class="touch-control" min="0.1" max="100000" step="10" value="100" aria-label="Frequência máxima ω_max" />`,
    `<label for="siso-n-points">Pontos</label>`,
    `<input type="number" id="siso-n-points" class="touch-control" min="16" max="5000" step="10" value="200" aria-label="Número de pontos na grade de frequência" />`,
    `</div>`,
    `<div class="panel-actions">`,
    `<label for="siso-delay">Atraso puro τ (s)</label>`,
    `<input type="number" id="siso-delay" class="touch-control" min="0" max="100" step="0.01" value="0" aria-label="Atraso de transporte em segundos" />`,
    `<label for="siso-use-pade"><input type="checkbox" id="siso-use-pade" data-action="siso-toggle-pade" /> Aproximar via Padé (opção explícita)</label>`,
    `<label for="siso-pade-order">Ordem Padé</label>`,
    `<input type="number" id="siso-pade-order" class="touch-control" min="1" max="10" step="1" value="1" aria-label="Ordem da aproximação de Padé" />`,
    `<button type="button" id="btn-siso-eval-bode" class="touch-control btn-primary" data-action="siso-eval-bode">Avaliar Bode / Nyquist / Margens</button>`,
    `</div>`,
    `</div>`,
    `<div class="subcard tool-field">`,
    `<label>Parâmetros do Lugar das Raízes &amp; Compensador (Root Locus)</label>`,
    `<div class="panel-actions">`,
    `<label for="siso-feedback-sign">Sinal da Realimentação</label>`,
    `<select id="siso-feedback-sign" class="touch-control" data-action="siso-select-feedback-sign" aria-label="Sinal da realimentação">`,
    `<option value="negative">Negativa (1 + K·G = 0)</option>`,
    `<option value="positive">Positiva (1 - K·G = 0)</option>`,
    `</select>`,
    `<label for="siso-rl-kmax">K máx</label>`,
    `<input type="number" id="siso-rl-kmax" class="touch-control" min="1" max="10000" step="10" value="100" aria-label="Ganho máximo K" />`,
    `<label for="siso-rl-zeta">Amortecimento ζ (overlay heurístico)</label>`,
    `<input type="number" id="siso-rl-zeta" class="touch-control" min="0.05" max="0.95" step="0.05" value="0.5" aria-label="Fator de amortecimento mínimo ζ" />`,
    `<button type="button" id="btn-siso-eval-rl" class="touch-control btn-primary" data-action="siso-eval-rl">Avaliar Lugar das Raízes</button>`,
    `</div>`,
    `</div>`,
    `<div class="subcard tool-field">`,
    `<label>Resposta Temporal ao Degrau (frequency.step_response)</label>`,
    `<div class="panel-actions">`,
    `<label for="siso-step-amp">Amplitude</label>`,
    `<input type="number" id="siso-step-amp" class="touch-control" min="-100" max="100" step="0.1" value="1" aria-label="Amplitude do degrau" />`,
    `<label for="siso-step-tfinal">Tempo Final (s)</label>`,
    `<input type="number" id="siso-step-tfinal" class="touch-control" min="0.1" max="1000" step="1" value="10" aria-label="Tempo final da simulação" />`,
    `<button type="button" id="btn-siso-eval-step" class="touch-control btn-primary" data-action="siso-eval-step">Avaliar Degrau SISO</button>`,
    `</div>`,
    `</div>`,
    `</div>`,
    `<div class="workspace-results-col">`,
    `<div id="siso-diagnostics-panel" class="diagnostics-panel" aria-live="polite"></div>`,
    `<div class="siso-charts-grid">`,
    `<div class="chart-card">`,
    `<div id="siso-bode-chart-slot" class="chart-container"></div>`,
    renderChartExportBarHtml("siso-bode-chart-slot", "Bode"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="siso-nyquist-chart-slot" class="chart-container"></div>`,
    renderChartExportBarHtml("siso-nyquist-chart-slot", "Nyquist"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="siso-rl-chart-slot" class="chart-container"></div>`,
    renderChartExportBarHtml("siso-rl-chart-slot", "Lugar das Raízes"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="siso-time-chart-slot" class="chart-container"></div>`,
    renderChartExportBarHtml("siso-time-chart-slot", "Resposta ao Degrau"),
    `</div>`,
    `</div>`,
    `<details><summary>Tabela acessível do diagrama de Bode (WCAG 2.2 AA)</summary><div id="siso-bode-table-slot"></div></details>`,
    `<details><summary>Tabela acessível do diagrama de Nyquist (WCAG 2.2 AA)</summary><div id="siso-nyquist-table-slot"></div></details>`,
    `<details><summary>Tabela acessível do Lugar das Raízes (WCAG 2.2 AA)</summary><div id="siso-rl-table-slot"></div></details>`,
    `<details><summary>Tabela acessível da resposta ao degrau SISO (WCAG 2.2 AA)</summary><div id="siso-time-table-slot"></div></details>`,
    `</div>`,
    `</div>`,
    `</section>`,
    `<section id="statespace-workspace-panel" aria-label="Espaço de Estados / LQR (Aba 3)">`,
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
    `<h3>Editor Matricial Interativo (Planta StateSpace &amp; Pesos LQR)</h3>`,
    `<div class="panel-actions">`,
    `<label for="lqr-preset-select">Preset clássico:</label>`,
    `<select id="lqr-preset-select" class="touch-control" aria-label="Preset clássico StateSpace">${presetOptionsHtml}</select>`,
    `<button type="button" id="btn-lqr-apply-preset" class="touch-control btn-secondary" data-action="lqr-apply-preset">Aplicar Preset</button>`,
    `</div>`,
    `<div class="lqr-matrix-dims">`,
    `<div class="tool-field"><label for="lqr-dim-n">Estados n (1–6)</label><input id="lqr-dim-n" type="number" min="1" max="6" step="1" class="touch-control" value="${editorDims.n}" aria-label="Dimensão n de estados" /></div>`,
    `<div class="tool-field"><label for="lqr-dim-m">Entradas m (1–4)</label><input id="lqr-dim-m" type="number" min="1" max="4" step="1" class="touch-control" value="${editorDims.m}" aria-label="Dimensão m de entradas" /></div>`,
    `<div class="tool-field"><label for="lqr-dim-p">Saídas p (1–4)</label><input id="lqr-dim-p" type="number" min="1" max="4" step="1" class="touch-control" value="${editorDims.p}" aria-label="Dimensão p de saídas" /></div>`,
    `<div class="tool-field"><label for="lqr-dim-dt">dt (vazio = contínuo)</label><input id="lqr-dim-dt" type="number" min="0" step="any" placeholder="contínuo" class="touch-control" aria-label="Passo de amostragem dt" /></div>`,
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
    `<div id="controllab-tools-slot" class="declarative-tools"></div>`,
    `<section id="typed-workspace-panel" class="panel-card" aria-label="Insumos tipados da sessão">`,
    `<h3>Insumos Tipados da Sessão (Dataset / Modelo / Sistema)</h3>`,
    `<div id="typed-tf-builder" class="typed-tf-builder typed-subcard" aria-label="Construtor Guiado de TransferFunction">`,
    `<h4>Construtor Guiado de TransferFunction</h4>`,
    `<div class="typed-tf-builder-grid">`,
    `<div class="tool-field"><label for="typed-tf-id">ID</label><input id="typed-tf-id" type="text" class="touch-control" value="tf-custom" aria-label="ID da TransferFunction" /></div>`,
    `<div class="tool-field"><label for="typed-tf-num">Numerador (ex: 1)</label><input id="typed-tf-num" type="text" class="touch-control" value="1" aria-label="Numerador da TransferFunction" /></div>`,
    `<div class="tool-field"><label for="typed-tf-den">Denominador (ex: 1, 1)</label><input id="typed-tf-den" type="text" class="touch-control" value="1, 1" aria-label="Denominador da TransferFunction" /></div>`,
    `<div class="tool-field"><label for="typed-tf-dt">dt (vazio = contínuo)</label><input id="typed-tf-dt" type="number" min="0" step="any" placeholder="contínuo" class="touch-control" aria-label="Passo dt da TransferFunction" /></div>`,
    `</div>`,
    `<div class="panel-actions"><button type="button" id="btn-register-tf-builder" class="touch-control btn-primary" data-action="register-tf-builder">Registrar TransferFunction</button></div>`,
    `</div>`,
    `<div class="typed-subcard">`,
    `<h4>Seletores da Sessão</h4>`,
    `<div id="typed-workspace-selectors-slot"></div>`,
    `<div id="typed-workspace-status-slot"></div>`,
    `<div class="panel-actions"><button type="button" id="btn-apply-selected-to-lqr" class="touch-control btn-secondary" data-action="apply-selected-to-lqr">Aplicar StateSpace Selecionado ao LQR</button></div>`,
    `</div>`,
    `<div class="typed-subcard tool-field">`,
    `<h4>Entrada JSON Avançada &amp; Reutilização Canônica</h4>`,
    `<label for="typed-object-json">Registrar Objeto Canônico (JSON: Dataset, TransferFunction, StateSpace, IdentifiedModel, FuzzySystem, TS)</label>`,
    `<textarea id="typed-object-json" class="touch-control" rows="3" data-field="typed-object-json" aria-label="Registrar objeto canônico JSON"></textarea>`,
    `<p class="json-format-hint">Exemplos de JSON canônico — <strong>TransferFunction:</strong> <code>{"schema_version":"1.0.0","id":"tf-1","revision":1,"kind":"TransferFunction","dt":null,"variable":"s","poly_order":"descending","num":[[{"shape":[1],"dtype":"float64","order":"C","data":[1]}]],"den":[[{"shape":[2],"dtype":"float64","order":"C","data":[1,1]}]],"units":{"time":"s","inputs":["u1"],"outputs":["y1"]}}</code> | <strong>Dataset:</strong> <code>{"schema_version":"1.0.0","id":"ds-1","revision":1,"kind":"Dataset","dt":0.05,"t":{"shape":[3],"dtype":"float64","order":"C","data":[0,0.05,0.1]},"u":{"shape":[3,1],"dtype":"float64","order":"C","data":[1,1,1]},"y":{"shape":[3,1],"dtype":"float64","order":"C","data":[0,0.05,0.1]}}</code></p>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-register-typed-object" class="touch-control btn-primary" data-action="register-typed-object">Registrar Objeto Tipado</button>`,
    `<select id="reuse-target-kind" class="touch-control" aria-label="Formato alvo de conversão de modelo">`,
    `<option value="native">Formato nativo do modelo (native)</option>`,
    `<option value="StateSpace">Converter para StateSpace (TF -> SS)</option>`,
    `</select>`,
    `<button type="button" id="btn-reuse-model" class="touch-control btn-secondary" data-action="reuse-model">Converter / Registrar Modelo</button>`,
    `<button type="button" id="btn-register-pending-identified" class="touch-control btn-secondary" data-action="register-pending-identified" disabled aria-disabled="true">Validar Modelo na Sessão</button>`,
    `<button type="button" id="btn-register-pending-derived" class="touch-control btn-secondary" data-action="register-pending-derived" disabled aria-disabled="true">Registrar Modelo Derivado</button>`,
    `</div>`,
    `</div>`,
    `</section>`,
    `</section>`,
    `<section id="controllab-charts-panel" class="panel-card">`,
    `<div class="chart-card">`,
    `<div id="pz-chart-slot" class="chart-container"></div>`,
    renderChartExportBarHtml("pz-chart-slot", "Mapa Polo-Zero"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="time-chart-slot" class="chart-container"></div>`,
    renderChartExportBarHtml("time-chart-slot", "Resposta Temporal LQR"),
    `</div>`,
    `<details id="pz-table-details"><summary>Tabela acessível de polos e valores (WCAG 2.2 AA)</summary><div id="pz-table-slot"></div></details>`,
    `<details id="time-table-details"><summary>Tabela acessível da resposta temporal (WCAG 2.2 AA)</summary><div id="time-table-slot"></div></details>`,
    `<section id="experiments-compare-panel" aria-label="Comparador de experimentos confirmados"><h3>Comparador de Experimentos Confirmados</h3><div id="experiments-compare-slot"></div></section>`,
    `</section>`,
    `</main>`,
    renderInspectorDrawerHtml(),
    `</div>`,
    `<section id="controllab-export-modal" class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="export-modal-title" hidden>`,
    `<div class="modal-header">`,
    `<h2 id="export-modal-title">Artefato Exportado</h2>`,
    `<div class="panel-actions">`,
    `<button type="button" id="export-modal-download" class="touch-control btn-primary">Baixar arquivo</button>`,
    `<button type="button" id="export-modal-copy" class="touch-control btn-secondary" hidden>Copiar script</button>`,
    `<button type="button" id="export-modal-close" class="touch-control btn-secondary">Fechar</button>`,
    `</div>`,
    `</div>`,
    `<pre id="export-modal-content" class="modal-pre"></pre>`,
    `</section>`,
    renderNewObjectModalHtml(),
    `<div id="controllab-live-polite" class="sr-only" aria-live="polite"></div>`,
    `<div id="controllab-live-assertive" class="sr-only" aria-live="assertive"></div>`,
  ].join("\n");

  const projectTitleInputEl = container.querySelector<HTMLInputElement>("#project-title-input");
  const engineBadgeEl = container.querySelector<HTMLElement>("#engine-status-badge");
  const revSummaryEl = container.querySelector<HTMLElement>("#revision-summary");
  const decimalsInputEl = container.querySelector<HTMLInputElement>("#decimals-select");
  const themeBtnEl = container.querySelector<HTMLElement>("#theme-toggle-btn");
  const mainEl = container.querySelector<HTMLElement>("#controllab-main");
  const tabHeadingEl = container.querySelector<HTMLElement>("#controllab-tab-heading");
  const errorSlotEl = container.querySelector<HTMLElement>("#controllab-error-slot");
  const statusTextEl = container.querySelector<HTMLElement>("#lqr-status-text");
  const sliderEl = container.querySelector<HTMLElement>("#lqr-q-slider");
  const feedbackSelectEl = container.querySelector<HTMLSelectElement>("#lqr-feedback-sign");
  const plantJsonInputEl = container.querySelector<HTMLInputElement>("#lqr-plant-json");
  const weightsJsonInputEl = container.querySelector<HTMLInputElement>("#lqr-weights-json");
  const typedObjectJsonEl = container.querySelector<HTMLTextAreaElement>("#typed-object-json");
  const reuseTargetKindEl = container.querySelector<HTMLSelectElement>("#reuse-target-kind");
  const btnRegisterPendingIdentifiedEl = container.querySelector<HTMLButtonElement>("#btn-register-pending-identified");
  const btnRegisterPendingDerivedEl = container.querySelector<HTMLButtonElement>("#btn-register-pending-derived");
  const typedSelectorsSlotEl = container.querySelector<HTMLElement>("#typed-workspace-selectors-slot");
  const typedStatusSlotEl = container.querySelector<HTMLElement>("#typed-workspace-status-slot");
  const idWorkspacePanelEl = container.querySelector<HTMLElement>("#identification-workspace-panel");
  const idCsvInputEl = container.querySelector<HTMLTextAreaElement>("#id-csv-input");
  const idTrainFractionEl = container.querySelector<HTMLInputElement>("#id-train-fraction");
  const idPartitionSelectEl = container.querySelector<HTMLSelectElement>("#id-chart-partition-select");
  const idDiagnosticsPanelEl = container.querySelector<HTMLElement>("#id-diagnostics-panel");
  const idResponseChartSlotEl = container.querySelector<HTMLElement>("#id-response-chart-slot");
  const idResidualsChartSlotEl = container.querySelector<HTMLElement>("#id-residuals-chart-slot");
  const idResponseTableSlotEl = container.querySelector<HTMLElement>("#id-response-table-slot");
  const idResidualsTableSlotEl = container.querySelector<HTMLElement>("#id-residuals-table-slot");
  const statespaceWorkspacePanelEl = container.querySelector<HTMLElement>("#statespace-workspace-panel");
  const lqrInteractiveBarEl = container.querySelector<HTMLElement>(".lqr-interactive-bar");
  const lqrMatrixEditorEl = container.querySelector<HTMLElement>("#lqr-matrix-editor");
  const lqrPresetSelectEl = container.querySelector<HTMLSelectElement>("#lqr-preset-select");
  const lqrDimNEl = container.querySelector<HTMLInputElement>("#lqr-dim-n");
  const lqrDimMEl = container.querySelector<HTMLInputElement>("#lqr-dim-m");
  const lqrDimPEl = container.querySelector<HTMLInputElement>("#lqr-dim-p");
  const lqrDimDtEl = container.querySelector<HTMLInputElement>("#lqr-dim-dt");
  const lqrMatrixGridsEl = container.querySelector<HTMLElement>("#lqr-matrix-grids");
  const lqrJsonAdvancedEl = container.querySelector<HTMLElement>("#lqr-json-advanced");
  const pvmExportOptionsEl = container.querySelector<HTMLElement>("#pvm-export-options");
  const typedTfIdEl = container.querySelector<HTMLInputElement>("#typed-tf-id");
  const typedTfNumEl = container.querySelector<HTMLInputElement>("#typed-tf-num");
  const typedTfDenEl = container.querySelector<HTMLInputElement>("#typed-tf-den");
  const typedTfDtEl = container.querySelector<HTMLInputElement>("#typed-tf-dt");
  const chartsPanelEl = container.querySelector<HTMLElement>("#controllab-charts-panel");
  const pzTableDetailsEl = container.querySelector<HTMLElement>("#pz-table-details");
  const timeTableDetailsEl = container.querySelector<HTMLElement>("#time-table-details");
  const experimentsComparePanelEl = container.querySelector<HTMLElement>("#experiments-compare-panel");
  const sisoWorkspacePanelEl = container.querySelector<HTMLElement>("#siso-workspace-panel");
  const sisoWMinEl = container.querySelector<HTMLInputElement>("#siso-w-min");
  const sisoWMaxEl = container.querySelector<HTMLInputElement>("#siso-w-max");
  const sisoNPointsEl = container.querySelector<HTMLInputElement>("#siso-n-points");
  const sisoDelayEl = container.querySelector<HTMLInputElement>("#siso-delay");
  const sisoUsePadeEl = container.querySelector<HTMLInputElement>("#siso-use-pade");
  const sisoPadeOrderEl = container.querySelector<HTMLInputElement>("#siso-pade-order");
  const sisoFeedbackSignEl = container.querySelector<HTMLSelectElement>("#siso-feedback-sign");
  const sisoRlKMaxEl = container.querySelector<HTMLInputElement>("#siso-rl-kmax");
  const sisoRlZetaEl = container.querySelector<HTMLInputElement>("#siso-rl-zeta");
  const sisoStepAmpEl = container.querySelector<HTMLInputElement>("#siso-step-amp");
  const sisoStepTFinalEl = container.querySelector<HTMLInputElement>("#siso-step-tfinal");
  const sisoDiagnosticsPanelEl = container.querySelector<HTMLElement>("#siso-diagnostics-panel");
  const sisoBodeChartSlotEl = container.querySelector<HTMLElement>("#siso-bode-chart-slot");
  const sisoNyquistChartSlotEl = container.querySelector<HTMLElement>("#siso-nyquist-chart-slot");
  const sisoRlChartSlotEl = container.querySelector<HTMLElement>("#siso-rl-chart-slot");
  const sisoTimeChartSlotEl = container.querySelector<HTMLElement>("#siso-time-chart-slot");
  const sisoBodeTableSlotEl = container.querySelector<HTMLElement>("#siso-bode-table-slot");
  const sisoNyquistTableSlotEl = container.querySelector<HTMLElement>("#siso-nyquist-table-slot");
  const sisoRlTableSlotEl = container.querySelector<HTMLElement>("#siso-rl-table-slot");
  const sisoTimeTableSlotEl = container.querySelector<HTMLElement>("#siso-time-table-slot");
  const kDisplaySlotEl = container.querySelector<HTMLElement>("#lqr-k-display");
  const diagnosticsPanelEl = container.querySelector<HTMLElement>("#lqr-diagnostics-panel");
  const toolsSlotEl = container.querySelector<HTMLElement>("#controllab-tools-slot");
  const pzChartSlotEl = container.querySelector<HTMLElement>("#pz-chart-slot");
  const timeChartSlotEl = container.querySelector<HTMLElement>("#time-chart-slot");
  const pzTableSlotEl = container.querySelector<HTMLElement>("#pz-table-slot");
  const timeTableSlotEl = container.querySelector<HTMLElement>("#time-table-slot");
  const experimentsCompareSlotEl = container.querySelector<HTMLElement>("#experiments-compare-slot");
  const modalEl = container.querySelector<HTMLElement>("#controllab-export-modal");
  const modalTitleEl = container.querySelector<HTMLElement>("#export-modal-title");
  const modalContentEl = container.querySelector<HTMLElement>("#export-modal-content");
  const modalCloseBtnEl = container.querySelector<HTMLElement>("#export-modal-close");
  const pvmKindEl = container.querySelector<HTMLSelectElement>("#pvm-controller-kind");
  const pvmDynamicEl = container.querySelector<HTMLTextAreaElement>("#pvm-dynamic-controller-json");
  const pvmSaturationEl = container.querySelector<HTMLInputElement>("#pvm-saturation-enabled");
  const pvmMinEl = container.querySelector<HTMLInputElement>("#pvm-u-min");
  const pvmMaxEl = container.querySelector<HTMLInputElement>("#pvm-u-max");
  if (pvmDynamicEl) pvmDynamicEl.value = JSON.stringify(DEFAULT_DYNAMIC_EXPORT_CONTROLLER, null, 2);
  const modalCopyBtnEl = container.querySelector<HTMLElement>("#export-modal-copy");
  const modalDownloadBtnEl = container.querySelector<HTMLElement>("#export-modal-download");
  const livePoliteEl = container.querySelector<HTMLElement>("#controllab-live-polite");
  const liveAssertiveEl = container.querySelector<HTMLElement>("#controllab-live-assertive");
  const tabButtons = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'));

  const exportButtons = [
    container.querySelector<HTMLButtonElement>("#btn-save-experiment"),
    container.querySelector<HTMLButtonElement>("#btn-export-ctrlab"),
    container.querySelector<HTMLButtonElement>("#btn-export-gains"),
    container.querySelector<HTMLButtonElement>("#btn-export-csv"),
    container.querySelector<HTMLButtonElement>("#btn-build-report"),
  ].filter((b): b is HTMLButtonElement => b !== null);

  const inspectorDrawer = new InspectorDrawerController({
    shell,
    container,
    initialOpen: false,
  });

  const workspaceDock = new WorkspaceDockController({
    shell,
    container,
    initialCollapsed: false,
    onInspectObject: (target) => {
      inspectorDrawer.inspectTarget(target);
    },
  });

  const openExportModal = (payload: ExportModalPayload, trigger: HTMLElement | null): void => {
    lastExportPayload = payload;
    if (trigger) {
      shell.openModal("modal-export", trigger);
    } else {
      shell.openModal("modal-export", "btn-export-pvm");
    }
    if (modalTitleEl) modalTitleEl.textContent = payload.title;
    if (modalContentEl) modalContentEl.textContent = payload.content;
    if (payload.offlineDesign) modalCopyBtnEl?.removeAttribute("hidden");
    else modalCopyBtnEl?.setAttribute("hidden", "true");
    if (modalEl) {
      modalEl.removeAttribute("hidden");
    }
    modalCloseBtnEl?.focus();
  };

  const closeExportModal = (): void => {
    if (shell.getOpenModalId() === "modal-export") {
      shell.closeModal("modal-export");
    }
    if (modalEl) {
      modalEl.setAttribute("hidden", "true");
    }
  };

  const renderMatrixEditorGrids = (
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
  ): void => {
    if (!lqrMatrixGridsEl) return;
    lqrMatrixGridsEl.innerHTML = [
      renderMatrixGridBlockHtml("A", "Matriz A", dims.n, dims.n, values.A),
      renderMatrixGridBlockHtml("B", "Matriz B", dims.n, dims.m, values.B),
      renderMatrixGridBlockHtml("C", "Matriz C", dims.p, dims.n, values.C),
      renderMatrixGridBlockHtml("D", "Matriz D", dims.p, dims.m, values.D),
      renderMatrixGridBlockHtml("Q", "Peso Q", dims.n, dims.n, values.Q),
      renderMatrixGridBlockHtml("R", "Peso R", dims.m, dims.m, values.R),
      renderMatrixGridBlockHtml("x0", "Estado x0", dims.n, 1, values.x0),
    ].join("");
  };

  const readMatrixFromEditor = (
    matrixName: "A" | "B" | "C" | "D" | "Q" | "R" | "x0",
    rows: number,
    cols: number,
  ): number[] => {
    const out: number[] = [];
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const cell = lqrMatrixGridsEl?.querySelector<HTMLInputElement>(
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
  };

  const syncLqrInputsFromWorkspace = (): void => {
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
    if (syncKey === lastSyncedLqrEditorKey) return;
    lastSyncedLqrEditorKey = syncKey;
    editorDims = {
      n: plant.matrices.A.shape[0],
      m: plant.matrices.B.shape[1],
      p: plant.matrices.C.shape[0],
    };
    if (lqrDimNEl && doc?.activeElement !== lqrDimNEl) lqrDimNEl.value = String(editorDims.n);
    if (lqrDimMEl && doc?.activeElement !== lqrDimMEl) lqrDimMEl.value = String(editorDims.m);
    if (lqrDimPEl && doc?.activeElement !== lqrDimPEl) lqrDimPEl.value = String(editorDims.p);
    if (lqrDimDtEl && doc?.activeElement !== lqrDimDtEl) {
      lqrDimDtEl.value = plant.dt === null ? "" : String(plant.dt);
    }
    renderMatrixEditorGrids(editorDims, {
      A: plant.matrices.A.data,
      B: plant.matrices.B.data,
      C: plant.matrices.C.data,
      D: plant.matrices.D.data,
      Q: weights.Q.data,
      R: weights.R.data,
      x0: weights.x0.data,
    });
    if (plantJsonInputEl && doc?.activeElement !== plantJsonInputEl) {
      plantJsonInputEl.value = JSON.stringify(plant);
    }
    if (weightsJsonInputEl && doc?.activeElement !== weightsJsonInputEl) {
      weightsJsonInputEl.value = JSON.stringify({
        Q: weights.Q,
        R: weights.R,
        x0: weights.x0,
      });
    }
  };

  const render = (): void => {
    const activeTab = shell.getActiveTab();
    if (activeTab !== lastSyncedHashTab) {
      lastSyncedHashTab = activeTab;
      writeTabToLocationHash(activeTab);
    }
    const isStatespace = activeTab === "statespace";
    const isIdentification = activeTab === "identification";
    const isSiso = activeTab === "siso_frequency";

    setHidden(statespaceWorkspacePanelEl, !isStatespace);
    setHidden(lqrInteractiveBarEl, !isStatespace);
    setHidden(lqrMatrixEditorEl, !isStatespace);
    setHidden(lqrJsonAdvancedEl, !isStatespace);
    setHidden(pvmExportOptionsEl, !isStatespace);
    setHidden(kDisplaySlotEl, !isStatespace);
    setHidden(diagnosticsPanelEl, !isStatespace);
    setHidden(idWorkspacePanelEl, !isIdentification);
    setHidden(sisoWorkspacePanelEl, !isSiso);
    setHidden(chartsPanelEl, !(isStatespace || isIdentification));
    setHidden(pzChartSlotEl, !(isStatespace || isIdentification));
    setHidden(pzTableDetailsEl, !(isStatespace || isIdentification));
    setHidden(timeChartSlotEl, !isStatespace);
    setHidden(timeTableDetailsEl, !isStatespace);
    setHidden(experimentsComparePanelEl, !isStatespace);
    toggleCssClass(mainEl, "single-main-col", !(isStatespace || isIdentification));
    toggleCssClass(mainEl, "tab-identification", isIdentification);

    syncLqrInputsFromWorkspace();

    const themeMode = shell.getThemeMode();
    const decimals = shell.getDisplayDecimals();
    const engineState = shell.getEngineState();
    const committed = lqr.getCommittedSnapshot();
    const preview = lqr.getPreviewState();
    const pendingCommit = lqr.isPendingCommit();
    const exportGuard = lqr.canExport();
    const presentedErr = shell.getPresentedLastError();

    container.setAttribute("data-theme", themeMode);

    if (projectTitleInputEl && doc?.activeElement !== projectTitleInputEl && projectTitleInputEl.value !== projectTitle) {
      projectTitleInputEl.value = projectTitle;
    }
    if (engineBadgeEl) {
      engineBadgeEl.setAttribute("data-engine-state", engineState);
      const caps = client.getCapabilities();
      const engineLabel = `Motor: ${engineState} | ${caps.engine_kind === "mock" ? "Simulador Local (beta)" : "Pyodide/Wasm (beta)"} | ${serviceWorkerStatus}`;
      engineBadgeEl.innerHTML = `<span class="status-dot" aria-hidden="true"></span>${escapeHtml(engineLabel)}`;
    }
    if (revSummaryEl) {
      revSummaryEl.textContent = `Rev. Projeto: ${lqr.getProjectRevision()} | Rev. Modelo: ${lqr.getPlant().revision}`;
    }
    if (decimalsInputEl && decimalsInputEl.value !== String(decimals)) {
      decimalsInputEl.value = String(decimals);
    }
    if (themeBtnEl) {
      themeBtnEl.textContent = themeMode === "standard_aa" ? "Tema: Claro AA" : "Tema: Alto Contraste";
    }

    for (const btn of tabButtons) {
      const tabId = btn.getAttribute("data-tab-id");
      const selected = tabId === activeTab;
      btn.setAttribute("aria-selected", selected ? "true" : "false");
      btn.setAttribute("tabindex", selected ? "0" : "-1");
    }

    if (mainEl) {
      const panelAttrs = getTabPanelAriaAttributes(`panel-${activeTab}`, activeTab, false);
      mainEl.setAttribute("aria-labelledby", panelAttrs["aria-labelledby"]);
    }

    const tabVm = tabsCtrl.getTabViewModel(activeTab);
    if (tabHeadingEl) {
      tabHeadingEl.textContent = `${tabVm.label} (${tabVm.ownerFront})`;
    }

    if (errorSlotEl) {
      errorSlotEl.innerHTML = presentedErr
        ? `<section class="panel-card" role="alert" aria-live="assertive"><strong>${escapeHtml(presentedErr.title)} (${escapeHtml(presentedErr.code)})</strong><p>${escapeHtml(presentedErr.summary)}</p><p><em>Próximo passo:</em> ${escapeHtml(presentedErr.next_step)}</p></section>`
        : "";
    }

    if (statusTextEl) {
      statusTextEl.textContent = preview.active
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
      ? Math.min(20, Math.max(0.1, dragStartQScale * preview.qScale))
      : lqr.getCurrentScaleFactors().qScale;
    const sliderCfg: AccessibleSliderConfig = {
      min: 0.1,
      max: 20,
      step: 0.1,
      value: sliderValue,
      label: "Fator de escala Q (arraste para preview / solte para commit)",
    };

    if (sliderEl) {
      const sliderAttrs = getSliderAriaAttributes(sliderCfg, decimals);
      for (const [k, v] of Object.entries(sliderAttrs)) {
        sliderEl.setAttribute(k, v);
      }
      sliderEl.textContent = `Escala Q: ${formatNumericDisplay(sliderCfg.value, decimals)}`;
    }

    if (feedbackSelectEl) {
      feedbackSelectEl.value = lqr.getFeedbackSign();
    }

    for (const btn of exportButtons) {
      btn.disabled = !exportGuard.allowed;
      if (exportGuard.allowed) {
        btn.removeAttribute("aria-disabled");
      } else {
        btn.setAttribute("aria-disabled", "true");
      }
    }

    const pvmOptions = shell.getPvmExportOptions();
    if (pvmOptions && renderedPvmExportRevision !== shell.getPvmExportRevision()) {
      renderedPvmExportRevision = shell.getPvmExportRevision();
      if (pvmKindEl) pvmKindEl.value = pvmOptions.controller_kind;
      if (pvmDynamicEl) {
        pvmDynamicEl.disabled = pvmOptions.controller_kind !== "dynamic";
        if (doc?.activeElement !== pvmDynamicEl) {
          pvmDynamicEl.value = JSON.stringify(pvmOptions.dynamic_controller ?? DEFAULT_DYNAMIC_EXPORT_CONTROLLER, null, 2);
        }
      }
      if (pvmSaturationEl) pvmSaturationEl.checked = pvmOptions.saturation.enabled;
      if (pvmMinEl) {
        pvmMinEl.disabled = !pvmOptions.saturation.enabled;
        if (doc?.activeElement !== pvmMinEl) pvmMinEl.value = JSON.stringify(pvmOptions.saturation.u_min);
      }
      if (pvmMaxEl) {
        pvmMaxEl.disabled = !pvmOptions.saturation.enabled;
        if (doc?.activeElement !== pvmMaxEl) pvmMaxEl.value = JSON.stringify(pvmOptions.saturation.u_max);
      }
    }

    const pvmButton = container.querySelector<HTMLButtonElement>("#btn-export-pvm");
    if (pvmButton) {
      pvmButton.disabled = !shell.canExportPvm();
      if (pvmButton.disabled) pvmButton.setAttribute("aria-disabled", "true");
      else pvmButton.removeAttribute("aria-disabled");
    }

    if (kDisplaySlotEl) {
      kDisplaySlotEl.innerHTML = committed?.K
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

    if (diagnosticsPanelEl) {
      if (committed) {
        const metrics = shell.getExecutionMetrics();
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
        diagnosticsPanelEl.innerHTML = [
          `<p><strong>Proveniência (R-27):</strong> algoritmo <code>${escapeHtml(committed.provenance.algorithm)}</code> | status <code>${escapeHtml(committed.status)}</code> | sinal <code>${escapeHtml(committed.feedback_sign)}</code></p>`,
          `<p><strong>Diagnósticos:</strong> J*=${escapeHtml(jOpt)} | rCARE=${escapeHtml(rCare)} | erro simetria=${escapeHtml(symErr)} | T_warm=${escapeHtml(tWarm)} ms</p>`,
        ].join("");
      } else {
        diagnosticsPanelEl.innerHTML = `<p>Aguardando primeiro cálculo autoritativo Python para exibir proveniência e resíduos.</p>`;
      }
    }

    const pzChart = lqr.buildPoleZeroChart();
    if (pzChartSlotEl) {
      pzChartSlotEl.innerHTML = renderPoleZeroSvg(pzChart, { decimals });
    }

    const timeChart = lqr.buildTimeResponseChart();
    if (timeChartSlotEl) {
      timeChartSlotEl.innerHTML = timeChart
        ? renderTimeResponseSvg(timeChart, { decimals })
        : "";
    }

    if (pzTableSlotEl) {
      const pzTable = buildAccessibleChartTable(pzChart, decimals);
      pzTableSlotEl.innerHTML = renderAccessibleTableHtml(pzTable);
    }

    if (timeTableSlotEl) {
      if (timeChart) {
        const timeTable = buildAccessibleChartTable(timeChart, decimals);
        timeTableSlotEl.innerHTML = renderAccessibleTableHtml(timeTable);
      } else {
        timeTableSlotEl.innerHTML = `<p>Sem trajetória temporal comitada.</p>`;
      }
    }

    if (experimentsCompareSlotEl) {
      const rows = shell.compareExperiments();
      if (rows.length === 0) {
        experimentsCompareSlotEl.innerHTML = `<p>Nenhum experimento confirmado salvo para comparação.</p>`;
      } else {
        const bodyRows = rows
          .map(
            (row) =>
              `<tr><th scope="row">${escapeHtml(row.label)}</th><td>${row.project_revision}</td><td>${row.model_revision}</td><td>${escapeHtml(row.feedback_sign)}</td><td>${escapeHtml(row.optimal_cost_display)}</td><td>${escapeHtml(row.care_residual_display)}</td><td>${escapeHtml(row.max_real_pole_display)}</td></tr>`,
          )
          .join("");
        experimentsCompareSlotEl.innerHTML = `<table class="accessible-data-table" aria-label="Comparação de experimentos confirmados"><thead><tr><th scope="col">Experimento</th><th scope="col">Rev. Projeto</th><th scope="col">Rev. Modelo</th><th scope="col">Sinal</th><th scope="col">J*</th><th scope="col">rCARE</th><th scope="col">max Re(λ)</th></tr></thead><tbody>${bodyRows}</tbody></table>`;
      }
    }

    if (typedSelectorsSlotEl) {
      const selectorsHtml = TYPED_SELECTION_ROLES.map((role) => {
        const items = typedWorkspace.listSelectableObjectsForRole(role);
        const eff = typedWorkspace.getEffectiveSelection(role);
        const selectedKey = eff ? encodeObjectRefKey(eff.ref) : "";
        const optionsHtml = [
          `<option value="">— Nenhum selecionado —</option>`,
          ...items.map((item) => {
            const k = encodeObjectRefKey({ id: item.id, revision: item.revision });
            const selAttr = k === selectedKey ? " selected" : "";
            const originTag = item.source === "lqr_plant" ? " [LQR ativo]" : "";
            return `<option value="${escapeHtml(k)}"${selAttr}>${escapeHtml(item.id)}#r${item.revision} — ${escapeHtml(item.summary)}${escapeHtml(originTag)}</option>`;
          }),
        ].join("");
        return [
          `<div class="tool-field" data-typed-role="${escapeHtml(role)}">`,
          `<label for="typed-select-${escapeHtml(role)}">${escapeHtml(ROLE_LABELS[role])}</label>`,
          `<select id="typed-select-${escapeHtml(role)}" class="touch-control" data-action="select-typed-ref" data-role="${escapeHtml(role)}" aria-label="${escapeHtml(ROLE_LABELS[role])}">${optionsHtml}</select>`,
          `</div>`,
        ].join("");
      }).join("\n");

      if (selectorsHtml !== lastTypedWorkspaceHtmlKey) {
        const activeId = (doc?.activeElement as HTMLElement | null)?.id ?? "";
        typedSelectorsSlotEl.innerHTML = selectorsHtml;
        lastTypedWorkspaceHtmlKey = selectorsHtml;
        if (activeId.startsWith("typed-select-")) {
          const refocused = typedSelectorsSlotEl.querySelector<HTMLElement>(`#${activeId}`);
          refocused?.focus();
        }
      }
    }

    const pendingIdentified = typedWorkspace.getPendingIdentifiedModel();
    if (btnRegisterPendingIdentifiedEl) {
      const canRegId = pendingIdentified !== null && !pendingIdentified.registered;
      btnRegisterPendingIdentifiedEl.disabled = !canRegId;
      if (canRegId) btnRegisterPendingIdentifiedEl.removeAttribute("aria-disabled");
      else btnRegisterPendingIdentifiedEl.setAttribute("aria-disabled", "true");
    }

    const pendingDerived = typedWorkspace.getPendingDerivedModel();
    if (btnRegisterPendingDerivedEl) {
      const canRegDerived = pendingDerived !== null && !pendingDerived.registered;
      btnRegisterPendingDerivedEl.disabled = !canRegDerived;
      if (canRegDerived) btnRegisterPendingDerivedEl.removeAttribute("aria-disabled");
      else btnRegisterPendingDerivedEl.setAttribute("aria-disabled", "true");
    }

    if (typedStatusSlotEl) {
      const regCount = typedWorkspace.listRegisteredObjects().length;
      const pendingParts: string[] = [
        `Objetos registrados na sessão: <strong>${regCount}</strong>`,
      ];
      if (pendingIdentified) {
        pendingParts.push(
          `IdentifiedModel: <code>${escapeHtml(pendingIdentified.model_ref.id)}#r${pendingIdentified.model_ref.revision}</code> (${pendingIdentified.registered ? "registrado" : "aguardando registro explícito"})`,
        );
      }
      if (pendingDerived) {
        pendingParts.push(
          `Derivado (${escapeHtml(pendingDerived.kind)}): <code>${escapeHtml(pendingDerived.model_ref.id)}#r${pendingDerived.model_ref.revision}</code> (${pendingDerived.registered ? "registrado" : "aguardando registro explícito"})`,
        );
      }
      typedStatusSlotEl.innerHTML = `<p>${pendingParts.join(" | ")}</p>`;
    }

    if (idWorkspacePanelEl) {
      if (activeTab === "identification") {
        idWorkspacePanelEl.removeAttribute("hidden");
      } else {
        idWorkspacePanelEl.setAttribute("hidden", "true");
      }
    }

    if (idPartitionSelectEl) {
      idPartitionSelectEl.value = idWorkspace.getActivePartitionView();
    }

    const activeIdReport = idWorkspace.getActiveReport();
    if (idDiagnosticsPanelEl) {
      if (!activeIdReport) {
        idDiagnosticsPanelEl.innerHTML = `<p>Aguardando estimação (ARX ou Subespaços) ou validação em holdout para exibir métricas 1-passo vs simulação livre, excitação e resíduos.</p>`;
      } else {
        const fmtMetric = (val: number | null) =>
          val !== null ? formatNumericDisplay(val, decimals) : "N/D";
        const trPredFit = fmtMetric(
          activeIdReport.train_metrics?.one_step_prediction.fit_percent ?? null,
        );
        const trSimFit = fmtMetric(
          activeIdReport.train_metrics?.free_simulation.fit_percent ?? null,
        );
        const trPredRmse = fmtMetric(
          activeIdReport.train_metrics?.one_step_prediction.rmse ?? null,
        );
        const trSimRmse = fmtMetric(
          activeIdReport.train_metrics?.free_simulation.rmse ?? null,
        );

        const valPredFit = fmtMetric(
          activeIdReport.validation_metrics?.one_step_prediction.fit_percent ?? null,
        );
        const valSimFit = fmtMetric(
          activeIdReport.validation_metrics?.free_simulation.fit_percent ?? null,
        );
        const valPredRmse = fmtMetric(
          activeIdReport.validation_metrics?.one_step_prediction.rmse ?? null,
        );
        const valSimRmse = fmtMetric(
          activeIdReport.validation_metrics?.free_simulation.rmse ?? null,
        );

        const condDisplay = fmtMetric(activeIdReport.excitation.condition);
        const rhoDisplay = fmtMetric(activeIdReport.spectral_radius);
        const rankDisplay =
          activeIdReport.excitation.rank !== null
            ? `${String(activeIdReport.excitation.rank)}/${String(activeIdReport.excitation.expected_rank ?? "?")}`
            : "N/D";
        const peTag =
          activeIdReport.excitation.pe_satisfied === false ||
          activeIdReport.excitation.rank_deficient
            ? `<strong data-pe-status="insufficient">Deficiente / PE Insuficiente (rank_deficient=true)</strong>`
            : `<span data-pe-status="satisfied">Posto completo / PE satisfeita</span>`;

        const warnItemsHtml =
          activeIdReport.warnings.length > 0
            ? `<ul class="id-warnings-list" data-testid="id-warnings-list">${activeIdReport.warnings
                .map((w) =>
                  typeof w === "string"
                    ? `<li><code>WARNING</code>: ${escapeHtml(w)}</li>`
                    : `<li data-warning-code="${escapeHtml(w.code)}"><code>${escapeHtml(w.code)}</code>: ${escapeHtml(w.message)}</li>`,
                )
                .join("")}</ul>`
            : "";

        idDiagnosticsPanelEl.innerHTML = [
          `<p><strong>Modelo Identificado:</strong> algoritmo <code>${escapeHtml(activeIdReport.algorithm)}</code> | status <code>${escapeHtml(activeIdReport.status)}</code> | representação <code>${escapeHtml(activeIdReport.inner_model_kind ?? "N/D")}</code> | dt=<code>${escapeHtml(String(activeIdReport.dt ?? "N/D"))}</code> | ρ(A)=<code>${escapeHtml(rhoDisplay)}</code> (${activeIdReport.is_stable === false ? "INSTÁVEL" : "estável"})</p>`,
          `<p><strong>Excitação &amp; Posto:</strong> posto=<code>${escapeHtml(rankDisplay)}</code> | κ(Φ)=<code>${escapeHtml(condDisplay)}</code> | ${peTag}</p>`,
          `<p data-testid="id-train-metrics"><strong>Treino (${escapeHtml(activeIdReport.train_dataset_ref?.id ?? "N/D")}):</strong> Previsão 1-Passo FIT=<code>${escapeHtml(trPredFit)}%</code> (RMSE=<code>${escapeHtml(trPredRmse)}</code>) | Simulação Livre FIT=<code>${escapeHtml(trSimFit)}%</code> (RMSE=<code>${escapeHtml(trSimRmse)}</code>)</p>`,
          `<p data-testid="id-holdout-metrics"><strong>Validação / Holdout (${escapeHtml(activeIdReport.val_dataset_ref?.id ?? "N/D")}):</strong> Previsão 1-Passo FIT=<code>${escapeHtml(valPredFit)}%</code> (RMSE=<code>${escapeHtml(valPredRmse)}</code>) | Simulação Livre FIT=<code>${escapeHtml(valSimFit)}%</code> (RMSE=<code>${escapeHtml(valSimRmse)}</code>)</p>`,
          `<p><strong>Critérios de Informação:</strong> AIC=<code>${escapeHtml(fmtMetric(activeIdReport.information_criteria.aic))}</code> | BIC=<code>${escapeHtml(fmtMetric(activeIdReport.information_criteria.bic))}</code> | FPE=<code>${escapeHtml(fmtMetric(activeIdReport.information_criteria.fpe))}</code></p>`,
          warnItemsHtml,
        ].join("");
      }
    }

    const idRespChart = idWorkspace.buildResponseChart();
    if (idResponseChartSlotEl) {
      idResponseChartSlotEl.innerHTML = idRespChart
        ? renderTimeResponseSvg(idRespChart, { decimals })
        : "";
    }
    if (idResponseTableSlotEl) {
      if (idRespChart) {
        const respTable = buildAccessibleChartTable(idRespChart, decimals);
        idResponseTableSlotEl.innerHTML = renderAccessibleTableHtml(respTable);
      } else {
        idResponseTableSlotEl.innerHTML = `<p>Sem séries temporais de identificação para exibir.</p>`;
      }
    }

    const idResidChart = idWorkspace.buildResidualCorrelationChart();
    if (idResidualsChartSlotEl) {
      idResidualsChartSlotEl.innerHTML = idResidChart
        ? renderResidualCorrelationSvg(idResidChart, { decimals })
        : "";
    }
    if (idResidualsTableSlotEl) {
      if (idResidChart) {
        const residTable = buildAccessibleChartTable(idResidChart, decimals);
        idResidualsTableSlotEl.innerHTML = renderAccessibleTableHtml(residTable);
      } else {
        idResidualsTableSlotEl.innerHTML = `<p>Sem diagnóstico de correlação de resíduos para exibir.</p>`;
      }
    }

    if (activeTab === "identification") {
      const idPzChart = idWorkspace.buildIdentifiedPoleZeroChart();
      if (idPzChart) {
        if (pzChartSlotEl) {
          pzChartSlotEl.innerHTML = renderPoleZeroSvg(idPzChart, { decimals });
        }
        if (pzTableSlotEl) {
          const idPzTable = buildAccessibleChartTable(idPzChart, decimals);
          pzTableSlotEl.innerHTML = renderAccessibleTableHtml(idPzTable);
        }
      } else {
        if (pzChartSlotEl) {
          pzChartSlotEl.innerHTML = "";
        }
        if (pzTableSlotEl) {
          pzTableSlotEl.innerHTML = `<p>Sem polos identificados ainda.</p>`;
        }
      }
    }

    if (activeTab === "siso_frequency") {
      const margins = sisoWorkspace.getMarginsView();
      if (sisoDiagnosticsPanelEl) {
        if (!margins) {
          sisoDiagnosticsPanelEl.innerHTML = `<p>Aguardando avaliação de resposta em frequência (Bode / Nyquist / Margens) ou Lugar das Raízes.</p>`;
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

          sisoDiagnosticsPanelEl.innerHTML = [
            `<p><strong>Margens de Estabilidade:</strong> MF=<code>${pmStr}</code> (em ω_gc=<code>${wgcStr}</code>) | MG=<code>${gmStr}</code> (em ω_pc=<code>${wpcStr}</code>) | Margem de atraso=<code>${dmStr}</code> | ${clStableStr}</p>`,
            multipleCrossingWarn,
          ].join("");
        }
      }

      const bodeChart = sisoWorkspace.getBodeChartModel();
      if (sisoBodeChartSlotEl) {
        sisoBodeChartSlotEl.innerHTML = bodeChart
          ? renderBodeSvg(bodeChart, { decimals })
          : "";
      }
      if (sisoBodeTableSlotEl) {
        if (bodeChart) {
          const table = buildAccessibleChartTable(bodeChart, decimals);
          sisoBodeTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
        } else {
          sisoBodeTableSlotEl.innerHTML = `<p>Sem dados de Bode para exibir.</p>`;
        }
      }

      const nyquistChart = sisoWorkspace.getNyquistChartModel();
      if (sisoNyquistChartSlotEl) {
        sisoNyquistChartSlotEl.innerHTML = nyquistChart
          ? renderNyquistSvg(nyquistChart, { decimals })
          : "";
      }
      if (sisoNyquistTableSlotEl) {
        if (nyquistChart) {
          const table = buildAccessibleChartTable(nyquistChart, decimals);
          sisoNyquistTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
        } else {
          sisoNyquistTableSlotEl.innerHTML = `<p>Sem dados de Nyquist para exibir.</p>`;
        }
      }

      const rlChart = sisoWorkspace.getRootLocusChartModel();
      if (sisoRlChartSlotEl) {
        sisoRlChartSlotEl.innerHTML = rlChart
          ? renderRootLocusSvg(rlChart, { decimals })
          : "";
      }
      if (sisoRlTableSlotEl) {
        if (rlChart) {
          const table = buildAccessibleChartTable(rlChart, decimals);
          sisoRlTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
        } else {
          sisoRlTableSlotEl.innerHTML = `<p>Sem dados de Lugar das Raízes para exibir.</p>`;
        }
      }

      const timeChart = sisoWorkspace.getTimeResponseChartModel();
      if (sisoTimeChartSlotEl) {
        sisoTimeChartSlotEl.innerHTML = timeChart
          ? renderTimeResponseSvg(timeChart, { decimals })
          : "";
      }
      if (sisoTimeTableSlotEl) {
        if (timeChart) {
          const table = buildAccessibleChartTable(timeChart, decimals);
          sisoTimeTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
        } else {
          sisoTimeTableSlotEl.innerHTML = `<p>Sem dados de resposta ao degrau para exibir.</p>`;
        }
      }
    }

    const chartVisibility: Record<string, boolean> = {
      "id-response-chart-slot": isIdentification,
      "id-residuals-chart-slot": isIdentification,
      "siso-bode-chart-slot": isSiso,
      "siso-nyquist-chart-slot": isSiso,
      "siso-rl-chart-slot": isSiso,
      "siso-time-chart-slot": isSiso,
      "pz-chart-slot": isStatespace || isIdentification,
      "time-chart-slot": isStatespace,
    };
    for (const [slotId, slotVisible] of Object.entries(chartVisibility)) {
      const slotEl = container.querySelector<HTMLElement>(`#${slotId}`);
      const barEl = container.querySelector<HTMLElement>(`[data-export-bar-for="${slotId}"]`);
      if (!barEl) continue;
      const hasSvg = serializeSvgForExport(slotEl) !== null;
      const barVisible = slotVisible && hasSvg;
      setHidden(barEl, !barVisible);
      const isLqrBlocked =
        isStatespace &&
        (slotId === "pz-chart-slot" || slotId === "time-chart-slot") &&
        !exportGuard.allowed;
      const canExportChart = barVisible && !isLqrBlocked;
      for (const btn of Array.from(barEl.querySelectorAll<HTMLButtonElement>("button"))) {
        btn.disabled = !canExportChart;
        if (canExportChart) btn.removeAttribute("aria-disabled");
        else btn.setAttribute("aria-disabled", "true");
      }
    }

    if (toolsSlotEl) {
      const nextToolsHtml = tabVm.tools.map((t) => t.toHtml()).join("\n");
      if (nextToolsHtml !== lastToolsHtmlKey) {
        const activeId = (doc?.activeElement as HTMLElement | null)?.id ?? "";
        toolsSlotEl.innerHTML = nextToolsHtml;
        lastToolsHtmlKey = nextToolsHtml;
        if (activeId.startsWith("tool-")) {
          const safeSelId = activeId.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
          const refocused = toolsSlotEl.querySelector<HTMLElement>(`[id="${safeSelId}"]`);
          refocused?.focus();
        }
      }
    }

    if (modalEl) {
      if (shell.getOpenModalId() === "modal-export") {
        modalEl.removeAttribute("hidden");
      } else {
        modalEl.setAttribute("hidden", "true");
      }
    }

    if (livePoliteEl) {
      livePoliteEl.textContent = shell.getAnnouncer().getCurrentText("polite");
    }
    if (liveAssertiveEl) {
      liveAssertiveEl.textContent = shell.getAnnouncer().getCurrentText("assertive");
    }

    workspaceDock.render();
    inspectorDrawer.render();
  };

  projectTitleInputEl?.addEventListener("input", () => {
    const val = projectTitleInputEl.value.trim();
    projectTitle = val || "Projeto ControlLab";
  });
  projectTitleInputEl?.addEventListener("change", () => {
    const val = projectTitleInputEl.value.trim();
    projectTitle = val || "Projeto ControlLab";
    if (projectTitleInputEl.value !== projectTitle) {
      projectTitleInputEl.value = projectTitle;
    }
  });

  for (const btn of tabButtons) {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-tab-id");
      if (id && (PROJECT_TAB_IDS as readonly string[]).includes(id)) {
        shell.switchTab(id as ProjectTabId);
      }
    });
    btn.addEventListener("keydown", (ev: KeyboardEvent) => {
      const res = shell.handleTabKeyDown(ev.key);
      if (res.handled) {
        ev.preventDefault();
        const nextEl = container.querySelector<HTMLElement>(`#tab-${res.activeTab}`);
        nextEl?.focus();
      }
    });
  }

  if (sliderEl) {
    sliderEl.addEventListener("pointerdown", (ev: PointerEvent) => {
      dragStartQScale = lqr.getCurrentScaleFactors().qScale;
      try {
        sliderEl.setPointerCapture?.(ev.pointerId);
      } catch {
        // Fallback quando mock DOM não implementa pointer capture
      }
      lqr.pointerDown("lqr-q-slider");
    });
    sliderEl.addEventListener("pointermove", (ev: PointerEvent) => {
      if (!lqr.getPreviewState().active) return;
      const rect = sliderEl.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (ev.clientX - rect.left) / Math.max(1, rect.width)));
      const targetScale = 0.1 + ratio * (20 - 0.1);
      const relFactor = targetScale / Math.max(1e-6, dragStartQScale);
      lqr.pointerMove({ qScale: relFactor });
    });
    sliderEl.addEventListener("pointerup", (ev: PointerEvent) => {
      if (!lqr.getPreviewState().active) return;
      try {
        if (sliderEl.hasPointerCapture?.(ev.pointerId)) {
          sliderEl.releasePointerCapture?.(ev.pointerId);
        }
      } catch {
        // ignore
      }
      void lqr.pointerUp();
    });
    sliderEl.addEventListener("pointercancel", () => {
      void lqr.cancelDrag();
    });
    sliderEl.addEventListener("blur", () => {
      lqr.handleBlur();
    });
    sliderEl.addEventListener("keydown", (ev: KeyboardEvent) => {
      const currentVal = lqr.getPreviewState().active
        ? Math.min(20, Math.max(0.1, dragStartQScale * lqr.getPreviewState().qScale))
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

  feedbackSelectEl?.addEventListener("change", () => {
    const val = feedbackSelectEl.value === "positive" ? "positive" : "negative";
    lqr.updateWeights({ feedbackSign: val });
    void lqr.commitCurrentDesign();
  });

  container.querySelector<HTMLElement>('[data-action="lqr-apply-preset"]')?.addEventListener("click", () => {
    try {
      const presetId = lqrPresetSelectEl?.value ?? "double_integrator";
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
      shell.presentError(err);
    }
  });

  const handleDimChange = (): void => {
    const clampDim = (val: number, min: number, max: number, fallback: number): number =>
      Number.isInteger(val) ? Math.min(max, Math.max(min, val)) : fallback;
    const nextN = clampDim(Number(lqrDimNEl?.value ?? editorDims.n), 1, 6, editorDims.n);
    const nextM = clampDim(Number(lqrDimMEl?.value ?? editorDims.m), 1, 4, editorDims.m);
    const nextP = clampDim(Number(lqrDimPEl?.value ?? editorDims.p), 1, 4, editorDims.p);
    const prevN = editorDims.n;
    const prevM = editorDims.m;
    const prevP = editorDims.p;
    const resize2D = (oldData: number[], oldR: number, oldC: number, newR: number, newC: number, diagDefault = 0): number[] => {
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
      oldA = readMatrixFromEditor("A", prevN, prevN);
      oldB = readMatrixFromEditor("B", prevN, prevM);
      oldC = readMatrixFromEditor("C", prevP, prevN);
      oldD = readMatrixFromEditor("D", prevP, prevM);
      oldQ = readMatrixFromEditor("Q", prevN, prevN);
      oldR = readMatrixFromEditor("R", prevM, prevM);
      oldX0 = readMatrixFromEditor("x0", prevN, 1);
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
    editorDims = { n: nextN, m: nextM, p: nextP };
    renderMatrixEditorGrids(editorDims, {
      A: resize2D(oldA, prevN, prevN, nextN, nextN),
      B: resize2D(oldB, prevN, prevM, nextN, nextM),
      C: resize2D(oldC, prevP, prevN, nextP, nextN),
      D: resize2D(oldD, prevP, prevM, nextP, nextM),
      Q: resize2D(oldQ, prevN, prevN, nextN, nextN, 1),
      R: resize2D(oldR, prevM, prevM, nextM, nextM, 1),
      x0: resize2D(oldX0, prevN, 1, nextN, 1),
    });
  };
  lqrDimNEl?.addEventListener("change", handleDimChange);
  lqrDimMEl?.addEventListener("change", handleDimChange);
  lqrDimPEl?.addEventListener("change", handleDimChange);

  container.querySelector<HTMLElement>('[data-action="lqr-apply-matrices"]')?.addEventListener("click", () => {
    try {
      const { n, m, p } = editorDims;
      const dtRaw = lqrDimDtEl?.value?.trim() ?? "";
      const dtVal = dtRaw === "" ? null : Number(dtRaw);
      if (dtVal !== null && (!Number.isFinite(dtVal) || dtVal <= 0)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "dt deve ser vazio (contínuo) ou um número positivo > 0.",
        );
      }
      const AData = readMatrixFromEditor("A", n, n);
      const BData = readMatrixFromEditor("B", n, m);
      const CData = readMatrixFromEditor("C", p, n);
      const DData = readMatrixFromEditor("D", p, m);
      const QData = readMatrixFromEditor("Q", n, n);
      const RData = readMatrixFromEditor("R", m, m);
      const x0Data = readMatrixFromEditor("x0", n, 1);

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
      shell.presentError(err);
    }
  });

  container.querySelector<HTMLElement>('[data-action="apply-plant"]')?.addEventListener("click", () => {
    try {
      const raw = plantJsonInputEl?.value?.trim() ?? "";
      const nextPlant =
        raw.length > 0
          ? normalizePlantJsonInput(JSON.parse(raw), lqr.getPlant())
          : lqr.getPlant();
      lqr.updatePlant(nextPlant);
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  container.querySelector<HTMLElement>('[data-action="apply-weights"]')?.addEventListener("click", () => {
    try {
      const raw = weightsJsonInputEl?.value?.trim() ?? "";
      const nextWeights =
        raw.length > 0
          ? normalizeWeightsJsonInput(JSON.parse(raw))
          : {
              feedbackSign:
                feedbackSelectEl?.value === "positive"
                  ? "positive"
                  : lqr.getFeedbackSign(),
            };
      lqr.updateWeights(nextWeights);
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  container.querySelector<HTMLElement>('[data-action="register-tf-builder"]')?.addEventListener("click", () => {
    try {
      const tfId = (typedTfIdEl?.value?.trim() ?? "") || "tf-custom";
      const numCoeffs = parseCommaNumberList(typedTfNumEl?.value ?? "", "Numerador");
      const denCoeffs = parseCommaNumberList(typedTfDenEl?.value ?? "", "Denominador");
      if (denCoeffs.every((v) => v === 0)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Denominador da TransferFunction não pode ser identicamente nulo.",
        );
      }
      const dtRaw = typedTfDtEl?.value?.trim() ?? "";
      const dtVal = dtRaw === "" ? null : Number(dtRaw);
      if (dtVal !== null && (!Number.isFinite(dtVal) || dtVal <= 0)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "dt da TransferFunction deve ser vazio (contínuo) ou número positivo > 0.",
        );
      }
      const dto = {
        schema_version: "1.0.0",
        id: tfId,
        revision: 1,
        kind: "TransferFunction",
        dt: dtVal,
        variable: dtVal === null ? "s" : "z",
        poly_order: "descending",
        num: [[makeFloat64Tensor([numCoeffs.length], numCoeffs)]],
        den: [[makeFloat64Tensor([denCoeffs.length], denCoeffs)]],
        units: { time: "s", inputs: ["u1"], outputs: ["y1"] },
        provenance: { source: "ui_tf_builder" },
      };
      if (typedObjectJsonEl) {
        typedObjectJsonEl.value = JSON.stringify(dto);
      }
      void typedWorkspace.registerTypedObject(dto).catch((err: unknown) => {
        shell.presentError(err);
      });
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  container.querySelector<HTMLElement>('[data-action="register-typed-object"]')?.addEventListener("click", () => {
    const raw = typedObjectJsonEl?.value?.trim() ?? "";
    if (raw.length === 0) {
      shell.presentError(
        new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Informe um objeto JSON canônico (Dataset, TransferFunction, StateSpace, IdentifiedModel, FuzzySystem ou TS) antes de registrar.",
        ),
      );
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      shell.presentError(
        new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "JSON inválido no campo de registro de objeto tipado.",
        ),
      );
      return;
    }
    void typedWorkspace.registerTypedObject(parsed).catch((err: unknown) => {
      shell.presentError(err);
    });
  });

  container.querySelector<HTMLElement>('[data-action="reuse-model"]')?.addEventListener("click", (ev) => {
    const targetKind = reuseTargetKindEl?.value === "StateSpace" ? "StateSpace" : "native";
    const triggerBtn = ev.currentTarget as HTMLElement | null;
    void typedWorkspace
      .reuseModel({ targetKind })
      .then((outcome) => {
        openExportModal(
          {
            title: `Derivação core.reuse_model (${outcome.derivedKind})`,
            filename: `${outcome.derivedRef.id}_r${outcome.derivedRef.revision}.json`,
            mimeType: "application/json",
            content: JSON.stringify(outcome.response, null, 2),
          },
          triggerBtn,
        );
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  btnRegisterPendingIdentifiedEl?.addEventListener("click", () => {
    void typedWorkspace.registerPendingIdentifiedModel().catch((err: unknown) => {
      shell.presentError(err);
    });
  });

  btnRegisterPendingDerivedEl?.addEventListener("click", () => {
    void typedWorkspace
      .registerPendingDerivedModel({ selectCompatible: true })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  container.querySelector<HTMLElement>('[data-action="apply-selected-to-lqr"]')?.addEventListener("click", () => {
    try {
      shell.applySelectedPlantToLqr();
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  const getConfiguredTrainFraction = (): number => {
    const raw = Number(idTrainFractionEl?.value ?? "0.7");
    return Number.isFinite(raw) ? raw : 0.7;
  };

  container.querySelector<HTMLElement>('[data-action="id-import-csv"]')?.addEventListener("click", () => {
    const csvRaw = idCsvInputEl?.value ?? "";
    void idWorkspace
      .importCsvDataset(csvRaw, {
        splitTrainHoldout: true,
        trainFraction: getConfiguredTrainFraction(),
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  container.querySelector<HTMLElement>('[data-action="id-load-prbs"]')?.addEventListener("click", () => {
    void idWorkspace
      .loadBenchmarkDataset({
        preset: "prbs",
        splitTrainHoldout: true,
        trainFraction: getConfiguredTrainFraction(),
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  container.querySelector<HTMLElement>('[data-action="id-load-const-pe"]')?.addEventListener("click", () => {
    void idWorkspace
      .loadBenchmarkDataset({
        preset: "constant_input",
        splitTrainHoldout: true,
        trainFraction: getConfiguredTrainFraction(),
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  container.querySelector<HTMLElement>('[data-action="id-split-dataset"]')?.addEventListener("click", () => {
    void idWorkspace
      .splitSelectedDatasetTrainHoldout({
        trainFraction: getConfiguredTrainFraction(),
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  idPartitionSelectEl?.addEventListener("change", () => {
    idWorkspace.setActivePartitionView(
      idPartitionSelectEl.value === "train" ? "train" : "validation",
    );
  });

  container.querySelector<HTMLElement>('[data-action="id-reuse-to-lqr"]')?.addEventListener("click", () => {
    void idWorkspace
      .reuseIdentifiedModel({
        targetKind: "StateSpace",
        registerIdentifiedIfPending: true,
        registerDerived: true,
        applyToDestination: "lqr",
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  container.querySelector<HTMLElement>('[data-action="id-reuse-to-siso"]')?.addEventListener("click", () => {
    void idWorkspace
      .reuseIdentifiedModel({
        targetKind: "native",
        registerIdentifiedIfPending: true,
        registerDerived: true,
        applyToDestination: "siso_frequency",
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  container.querySelector<HTMLElement>('[data-action="siso-eval-bode"]')?.addEventListener("click", () => {
    const wMin = sisoWMinEl ? Number(sisoWMinEl.value) : 0.01;
    const wMax = sisoWMaxEl ? Number(sisoWMaxEl.value) : 100;
    const nPts = sisoNPointsEl ? Number(sisoNPointsEl.value) : 200;
    const delay = sisoDelayEl ? Number(sisoDelayEl.value) : 0;
    const usePade = sisoUsePadeEl ? sisoUsePadeEl.checked : false;
    const padeOrder = sisoPadeOrderEl ? Number(sisoPadeOrderEl.value) : 1;

    void sisoWorkspace
      .evaluateBodeAndMargins({
        customWMin: wMin,
        customWMax: wMax,
        customNPoints: nPts,
        customDelay: delay,
        customUsePade: usePade,
        customPadeOrder: padeOrder,
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  container.querySelector<HTMLElement>('[data-action="siso-eval-rl"]')?.addEventListener("click", () => {
    const kMax = sisoRlKMaxEl ? Number(sisoRlKMaxEl.value) : 100;
    const zeta = sisoRlZetaEl ? Number(sisoRlZetaEl.value) : 0.5;

    void sisoWorkspace
      .evaluateRootLocus({
        k_max: kMax,
        damping_ratio: zeta,
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  container.querySelector<HTMLElement>('[data-action="siso-eval-step"]')?.addEventListener("click", () => {
    const amp = sisoStepAmpEl ? Number(sisoStepAmpEl.value) : 1;
    const tf = sisoStepTFinalEl ? Number(sisoStepTFinalEl.value) : 10;

    void sisoWorkspace
      .evaluateStepResponse({
        amplitude: amp,
        t_final: tf,
      })
      .catch((err: unknown) => {
        shell.presentError(err);
      });
  });

  sisoFeedbackSignEl?.addEventListener("change", () => {
    const val = sisoFeedbackSignEl.value === "positive" ? "positive" : "negative";
    sisoWorkspace.setFeedbackSign(val);
  });

  typedSelectorsSlotEl?.addEventListener("change", (ev: Event) => {
    const target = ev.target as HTMLSelectElement | null;
    if (!target || target.getAttribute("data-action") !== "select-typed-ref") return;
    const role = target.getAttribute("data-role") as TypedSelectionRole | null;
    if (!role || !(TYPED_SELECTION_ROLES as readonly string[]).includes(role)) return;
    try {
      const val = target.value.trim();
      if (val === "") {
        typedWorkspace.selectRef(role, null);
      } else {
        const decoded = decodeObjectRefKey(val);
        if (!decoded) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Chave de referência inválida: '${val}'.`,
          );
        }
        typedWorkspace.selectRef(role, decoded, { allowHistoricalDowngrade: true });
      }
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  typedSelectorsSlotEl?.addEventListener("keydown", (ev: KeyboardEvent) => {
    const target = ev.target as HTMLElement | null;
    if (!target || target.getAttribute("data-action") !== "select-typed-ref") return;
    const role = target.getAttribute("data-role") as TypedSelectionRole | null;
    if (!role || !(TYPED_SELECTION_ROLES as readonly string[]).includes(role)) return;
    try {
      const nav = typedWorkspace.handleRoleKeyNavigation(role, ev.key);
      if (nav.handled) {
        ev.preventDefault();
      }
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  container.querySelector<HTMLElement>('[data-action="commit-lqr"]')?.addEventListener("click", () => {
    void lqr.commitCurrentDesign();
  });
  container.querySelector<HTMLElement>('[data-action="analyze-open-loop"]')?.addEventListener("click", () => {
    void lqr.analyzeOpenLoop();
  });
  container.querySelector<HTMLElement>('[data-action="cancel-lqr"]')?.addEventListener("click", () => {
    void lqr.cancelDrag();
  });
  container.querySelector<HTMLElement>('[data-action="undo-lqr"]')?.addEventListener("click", () => {
    void lqr.undo();
  });
  container.querySelector<HTMLElement>('[data-action="reset-worker"]')?.addEventListener("click", () => {
    void client.resetWorker("Reiniciado manualmente pelo usuário na UI").catch((err: unknown) => {
      shell.presentError(err);
    });
  });
  container.querySelector<HTMLElement>('[data-action="save-experiment"]')?.addEventListener("click", () => {
    try {
      shell.addCommittedExperiment();
      shell.getAnnouncer().announce(
        `Experimento adicionado ao comparador (${shell.listExperiments().length} total).`,
        "polite",
        "committed",
      );
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });
  themeBtnEl?.addEventListener("click", () => {
    shell.setThemeMode(
      shell.getThemeMode() === "standard_aa" ? "high_contrast" : "standard_aa",
    );
  });
  decimalsInputEl?.addEventListener("change", () => {
    const parsed = Number(decimalsInputEl.value);
    if (Number.isInteger(parsed) && parsed >= 0 && parsed <= 15) {
      shell.setDisplayDecimals(parsed);
    }
  });

  const updatePvmExportOptions = (): void => {
    shell.invalidatePvmExportOptions();
    const kind = pvmKindEl?.value === "dynamic" ? "dynamic" : "lqr";
    const enabled = pvmSaturationEl?.checked === true;
    if (pvmDynamicEl) pvmDynamicEl.disabled = kind !== "dynamic";
    if (pvmMinEl) pvmMinEl.disabled = !enabled;
    if (pvmMaxEl) pvmMaxEl.disabled = !enabled;
    try {
      let dynamicController: Record<string, unknown> | undefined;
      try {
        const candidate = JSON.parse(pvmDynamicEl?.value ?? "");
        if (kind === "dynamic" || candidate?.kind === "DynamicController") dynamicController = candidate;
      } catch (error: unknown) {
        if (kind === "dynamic") throw error;
      }
      shell.setPvmExportOptions({
        controller_kind: kind,
        ...(dynamicController === undefined ? {} : { dynamic_controller: dynamicController }),
        saturation: {
          enabled,
          u_min: enabled ? JSON.parse(pvmMinEl?.value ?? "") : -1,
          u_max: enabled ? JSON.parse(pvmMaxEl?.value ?? "") : 1,
        },
      });
    } catch (error: unknown) {
      shell.presentError(error instanceof SyntaxError
        ? new ControlLabBridgeError("VALIDATION_ERROR", "JSON inválido na configuração PVM. Confira o controlador e os limites.")
        : error);
    }
  };
  for (const input of [pvmKindEl, pvmDynamicEl, pvmSaturationEl, pvmMinEl, pvmMaxEl]) {
    input?.addEventListener("input", updatePvmExportOptions);
    input?.addEventListener("change", updatePvmExportOptions);
  }

  const openNativeFile = async (kind: "pvm" | "ctrlab", trigger: HTMLElement | null): Promise<void> => {
    const file = kind === "pvm" ? await shell.exportPvm() : await shell.exportCtrlLab();
    openExportModal({ title: `Exportação .${kind}`, filename: file.filename,
      mimeType: file.media_type, bytes: file.bytes, projectRevision: file.project_revision,
      projectId: file.project_id, requestId: file.request_id,
      configurationRevision: file.configuration_revision, pvmControllerKind: file.pvm_controller_kind,
      content: `${file.filename} · ${file.bytes.length} bytes · SHA-256 ${file.sha256}` }, trigger);
  };
  for (const kind of ["pvm", "ctrlab"] as const) {
    container.querySelector<HTMLElement>(`[data-action="export-${kind}"]`)?.addEventListener("click", (ev) => {
      void openNativeFile(kind, ev.currentTarget as HTMLElement | null).catch((error: unknown) => shell.presentError(error));
    });
  }
  const importFileInput = container.querySelector<HTMLInputElement>("#ctrlab-file-input");
  importFileInput?.addEventListener("change", () => {
    const file = importFileInput.files?.[0];
    if (!file) return;
    void shell.importCtrlLab(file.arrayBuffer().then((buffer) => new Uint8Array(buffer)))
      .catch((error: unknown) => shell.presentError(error))
      .finally(() => { importFileInput.value = ""; });
  });

  container.querySelector<HTMLElement>('[data-action="export-gains"]')?.addEventListener("click", (ev) => {
    try {
      const gains = shell.exportGains();
      openExportModal(
        {
          title: "Ganhos Confirmados LQR (JSON)",
          filename: `${gains.project_id}_gains_r${gains.project_revision}.json`,
          mimeType: "application/json",
          content: JSON.stringify(gains, null, 2),
        },
        ev.currentTarget as HTMLElement | null,
      );
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  container.querySelector<HTMLElement>('[data-action="export-csv"]')?.addEventListener("click", (ev) => {
    try {
      const chart = lqr.buildTimeResponseChart() ?? lqr.buildPoleZeroChart();
      const csv = shell.exportChartCsv(chart);
      openExportModal(
        {
          title: "Exportação Científica CSV (com proveniência)",
          filename: `${chart.chart_id}_r${String(chart.project_revision)}.csv`,
          mimeType: "text/csv;charset=utf-8",
          content: csv,
        },
        ev.currentTarget as HTMLElement | null,
      );
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  const handleChartExport = (slotId: string, format: "svg" | "png"): void => {
    try {
      if (
        shell.getActiveTab() === "statespace" &&
        (slotId === "pz-chart-slot" || slotId === "time-chart-slot")
      ) {
        lqr.assertExportAllowed();
      }
      const slotEl = container.querySelector<HTMLElement>(`#${slotId}`);
      const svgMarkup = serializeSvgForExport(slotEl);
      if (!svgMarkup) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Nenhum gráfico SVG renderizado neste painel para exportar.",
        );
      }
      const filename = getChartExportFilename(slotId, format);
      if (format === "svg") {
        triggerBrowserDownload(
          {
            title: `Exportação SVG (${slotId})`,
            filename,
            mimeType: "image/svg+xml;charset=utf-8",
            content: svgMarkup,
          },
          doc,
        );
        if (livePoliteEl) livePoliteEl.textContent = `Gráfico exportado: ${filename}`;
        return;
      }
      void renderSvgMarkupToPngBlob(svgMarkup, {
        scale: 2,
        backgroundColor: "#ffffff",
        doc,
      })
        .then((blob) => {
          triggerBlobDownload(blob, filename, doc);
          if (livePoliteEl) livePoliteEl.textContent = `Gráfico exportado: ${filename}`;
        })
        .catch((err: unknown) => {
          shell.presentError(err);
        });
    } catch (err: unknown) {
      shell.presentError(err);
    }
  };

  for (const btn of Array.from(container.querySelectorAll<HTMLButtonElement>('[data-action="export-chart-svg"]'))) {
    btn.addEventListener("click", () => {
      const slotId = btn.getAttribute("data-chart-slot");
      if (slotId) handleChartExport(slotId, "svg");
    });
  }
  for (const btn of Array.from(container.querySelectorAll<HTMLButtonElement>('[data-action="export-chart-png"]'))) {
    btn.addEventListener("click", () => {
      const slotId = btn.getAttribute("data-chart-slot");
      if (slotId) handleChartExport(slotId, "png");
    });
  }

  container.querySelector<HTMLElement>('[data-action="build-report"]')?.addEventListener("click", (ev) => {
    try {
      const report = shell.buildScientificReport();
      openExportModal(
        {
          title: "Relatório Científico Rastreável (R-27)",
          filename: `${report.project_id}_report_r${report.project_revision}.json`,
          mimeType: "application/json",
          content: JSON.stringify(report, null, 2),
        },
        ev.currentTarget as HTMLElement | null,
      );
    } catch (err: unknown) {
      shell.presentError(err);
    }
  });

  modalCloseBtnEl?.addEventListener("click", closeExportModal);
  modalCopyBtnEl?.addEventListener("click", () => {
    if (!lastExportPayload?.offlineDesign) return;
    if (!globalThis.navigator?.clipboard) {
      shell.presentError(new Error("Cópia indisponível neste navegador. Selecione o texto ou baixe o script."));
      return;
    }
    void globalThis.navigator.clipboard.writeText(lastExportPayload.content).then(() => {
      if (livePoliteEl) livePoliteEl.textContent = "Script copiado.";
    }).catch((error: unknown) => shell.presentError(error));
  });
  modalDownloadBtnEl?.addEventListener("click", () => {
    if (lastExportPayload && doc) {
      try {
        if (lastExportPayload.pvmControllerKind === "dynamic") {
          shell.assertDynamicPvmExportAllowed(lastExportPayload.requestId, lastExportPayload.configurationRevision);
        } else if (!lastExportPayload.offlineDesign) {
          lqr.assertExportAllowed();
        }
        if (lastExportPayload.pvmControllerKind !== "dynamic" && lastExportPayload.projectRevision !== undefined &&
            (lastExportPayload.projectRevision !== lqr.getCommittedSnapshot()?.project_revision ||
             lastExportPayload.projectId !== lqr.getCommittedSnapshot()?.project_id ||
             lastExportPayload.requestId !== lqr.getCommittedSnapshot()?.request_id)) {
          throw new Error("O projeto mudou. Gere novamente o arquivo antes de baixar.");
        }
        if (lastExportPayload.configurationRevision !== undefined &&
            lastExportPayload.configurationRevision !== shell.getPvmExportRevision()) {
          throw new Error("A configuração PVM mudou. Gere novamente o arquivo antes de baixar.");
        }
        triggerBrowserDownload(lastExportPayload, doc);
      } catch (error: unknown) { shell.presentError(error); }
    }
  });
  modalEl?.addEventListener("keydown", (ev: KeyboardEvent) => {
    if (ev.key === "Escape") {
      ev.preventDefault();
      closeExportModal();
    }
  });

  if (toolsSlotEl) {
    const syncToolInput = (target: HTMLElement): void => {
      const toolId = target.getAttribute("data-tool-id");
      const paramName = target.getAttribute("data-param-name");
      const paramType = target.getAttribute("data-param-type");
      if (!toolId || !paramName) return;

      if (paramType === "boolean" && "checked" in target) {
        tabsCtrl.setToolParameters(toolId, {
          [paramName]: Boolean((target as HTMLInputElement).checked),
        });
        return;
      }
      const rawVal = "value" in target ? String((target as HTMLInputElement | HTMLSelectElement).value) : "";
      if (paramType === "number" || paramType === "integer") {
        tabsCtrl.setToolParameters(toolId, {
          [paramName]: rawVal.trim() === "" ? "" : Number(rawVal),
        });
      } else if (paramType === "json" || paramType === "matrix" || paramType === "vector") {
        if (rawVal.trim() === "") {
          tabsCtrl.setToolParameters(toolId, { [paramName]: "" });
          return;
        }
        try {
          tabsCtrl.setToolParameters(toolId, { [paramName]: JSON.parse(rawVal) });
        } catch {
          tabsCtrl.setToolParameters(toolId, { [paramName]: rawVal });
        }
      } else {
        tabsCtrl.setToolParameters(toolId, { [paramName]: rawVal });
      }
    };

    toolsSlotEl.addEventListener("change", (ev: Event) => {
      const target = ev.target as HTMLElement | null;
      if (target) {
        syncToolInput(target);
      }
    });

    toolsSlotEl.addEventListener("click", (ev: Event) => {
      const target = ev.target as HTMLElement | null;
      const btn = (target?.closest?.('[data-action="execute-tool"]') ?? target?.closest?.('[data-action="export-sdp"]')) as HTMLElement | null;
      const toolId = btn?.getAttribute("data-tool-id");
      if (!toolId) return;

      for (const fieldEl of Array.from(toolsSlotEl.querySelectorAll<HTMLElement>(`[data-tool-id="${toolId.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"]`))) {
        if (fieldEl.getAttribute("data-param-name")) {
          syncToolInput(fieldEl);
        }
      }

      if (btn?.getAttribute("data-action") === "export-sdp") {
        const format = btn.getAttribute("data-format") === "yalmip" ? "yalmip" : "cvxpy";
        const validation = tabsCtrl.getTabViewModel("optimization_lmi").tools
          .find((tool) => tool.toolId === toolId)?.validation;
        if (!validation?.valid) {
          shell.presentError(new Error("Corrija os parâmetros do problema antes de exportar."));
          return;
        }
        const feedbackSign = feedbackSelectEl?.value === "positive" ? "positive" : "negative";
        void typedWorkspace
          .prepareSdpExportSpecification(validation.sanitized, feedbackSign)
          .then((specification) => shell.exportSdpScript(format, specification))
          .then((file) => {
            openExportModal({title: `Execução offline / ${format.toUpperCase()}`,
              filename: file.filename, mimeType: file.media_type, content: file.script,
              offlineDesign: true}, btn);
          })
          .catch((error: unknown) => shell.presentError(error));
        return;
      }

      const projectId = lqr.getProjectId();
      const execRev = Math.max(
        lqr.getProjectRevision(),
        client.getCommittedRevision(projectId),
      );
      const feedbackSign = feedbackSelectEl?.value === "positive" ? "positive" : "negative";

      void tabsCtrl
        .executeTool(toolId, {
          project_id: projectId,
          project_revision: execRev,
          commitOnSuccess: false,
          feedbackSign,
        })
        .then((record) => {
          idWorkspace.ingestExecutionRecord(record);
          openExportModal(
            {
              title: `Resultado RPC: ${record.operation}`,
              filename: `${record.toolId}_r${record.project_revision}.json`,
              mimeType: "application/json",
              content: JSON.stringify(record.response, null, 2),
            },
            btn,
          );
        })
        .catch((err: unknown) => {
          shell.presentError(err);
        });
    });
  }

  const onWindowBlur = (): void => {
    lqr.handleBlur();
  };
  if (typeof globalThis.addEventListener === "function") {
    globalThis.addEventListener("blur", onWindowBlur);
  }

  const unsubShell = shell.subscribe(render);
  const unsubAnnouncer = shell.getAnnouncer().subscribe((entry) => {
    if (entry.politeness === "assertive" && liveAssertiveEl) {
      liveAssertiveEl.textContent = entry.message;
    } else if (entry.politeness === "polite" && livePoliteEl) {
      livePoliteEl.textContent = entry.message;
    }
  });

  render();
  void client.init().catch((err: unknown) => {
    shell.getAnnouncer().announce(
      `Motor indisponível: ${err instanceof Error ? err.message : String(err)}`,
      "assertive", "error",
    );
    render();
  });
  if (typeof navigator !== "undefined" && options?.engineMode !== "mock" && !options?.client) {
    void registerControlLabServiceWorker(navigator.serviceWorker).then((registration) => {
      serviceWorkerStatus = registration ? "SW registrado; cache não verificado" : "SW indisponível";
      render();
    }).catch(() => {
      serviceWorkerStatus = "falha ao registrar SW";
      shell.getAnnouncer().announce("Falha ao registrar cache offline; cálculo offline não verificado.", "polite", "status");
      render();
    });
  }

  return {
    shell,
    client,
    destroy: () => {
      if (typeof globalThis.removeEventListener === "function") {
        globalThis.removeEventListener("blur", onWindowBlur);
      }
      unsubShell();
      unsubAnnouncer();
      shell.dispose();
      client.dispose();
    },
  };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("controllab-app");
  if (root) {
    mountControlLabApp(root);
  }
}
