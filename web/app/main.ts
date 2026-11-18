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
import { ControlLabBridgeError } from "../bridge/protocol.ts";
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
  renderAccessibleTableHtml,
  renderPoleZeroSvg,
  renderResidualCorrelationSvg,
  renderTimeResponseSvg,
} from "../charts/scientific_chart.ts";
import {
  encodeObjectRefKey,
  decodeObjectRefKey,
  TYPED_SELECTION_ROLES,
  type TypedSelectionRole,
} from "../features/typed_workspace.ts";

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

function triggerBrowserDownload(payload: ExportModalPayload, doc: Document): void {
  if (typeof Blob === "undefined" || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return;
  }
  const blob = new Blob([payload.bytes ? new Uint8Array(payload.bytes).buffer : payload.content], { type: payload.mimeType });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = doc.createElement("a");
  anchor.href = objectUrl;
  anchor.download = payload.filename;
  anchor.style.display = "none";
  doc.body?.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
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

  const shell = new ControlLabShell({
    client,
    project_id: options?.project_id ?? "proj-controllab-web",
  });
  const lqr = shell.getLqrWorkspace();
  const tabsCtrl = shell.getTabsController();
  const typedWorkspace = shell.getTypedWorkspace();
  const idWorkspace = shell.getIdentificationWorkspace();
  const doc = container.ownerDocument;

  let serviceWorkerStatus = "cache não verificado";
  let dragStartQScale = 1.0;
  let lastExportPayload: ExportModalPayload | null = null;
  let lastToolsHtmlKey = "";
  let lastTypedWorkspaceHtmlKey = "";
  let renderedPvmExportRevision = -1;

  const ROLE_LABELS: Record<TypedSelectionRole, string> = {
    statespacePlant: "Planta StateSpace (statespace.* / LMI LTI)",
    frequencyPlant: "Modelo Frequência (StateSpace / TransferFunction)",
    dataset: "Dataset de Treino (identification.fit_*)",
    valDataset: "Dataset de Validação / Holdout",
    fuzzySystem: "Sistema Fuzzy (FuzzySystem -> fuzzy.*)",
    tsModel: "Modelo Takagi-Sugeno (TSStateSpace -> LMI PDC)",
    validationModel: "Modelo para Validação (identification.validate_model)",
    reuseSource: "Modelo Origem para Reutilização (core.reuse_model)",
  };

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

  container.innerHTML = [
    `<header class="controllab-header">`,
    `<div><h1>ControlLab Web</h1><span id="engine-status-badge" class="badge"></span> <span id="revision-summary"></span></div>`,
    `<div class="panel-actions">`,
    `<label for="decimals-select">Casas decimais: </label>`,
    `<input id="decimals-select" class="touch-control" type="number" min="0" max="15" value="${shell.getDisplayDecimals()}" data-action="decimals" />`,
    `<button type="button" id="theme-toggle-btn" class="touch-control" data-action="toggle-theme"></button>`,
    `</div>`,
    `</header>`,
    `<nav aria-label="Áreas de projeto" class="controllab-tablist" role="tablist">${tabsHtml}</nav>`,
    `<main id="controllab-main" class="controllab-main" role="tabpanel" tabindex="0">`,
    `<section class="panel-card">`,
    `<h2 id="controllab-tab-heading"></h2>`,
    `<div id="controllab-error-slot"></div>`,
    `<div class="lqr-interactive-bar">`,
    `<p>Status: <strong id="lqr-status-text"></strong></p>`,
    `<div id="lqr-q-slider" class="touch-control lqr-slider" data-action="lqr-slider"></div>`,
    `<div class="tool-field">`,
    `<label for="lqr-feedback-sign">Convenção de realimentação</label>`,
    `<select id="lqr-feedback-sign" class="touch-control" data-action="feedback-sign">`,
    `<option value="negative">Negativa: u = u_ff - Kx (A - BK)</option>`,
    `<option value="positive">Positiva: u = u_ff + Kx (A + BK)</option>`,
    `</select>`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="lqr-plant-json">Planta StateSpace (JSON)</label>`,
    `<input id="lqr-plant-json" class="touch-control" type="text" data-field="plant-json" aria-label="Planta StateSpace JSON" />`,
    `<button type="button" id="btn-apply-plant" class="touch-control" data-action="apply-plant">Aplicar Planta</button>`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="lqr-weights-json">Pesos Q / R / x0 (JSON)</label>`,
    `<input id="lqr-weights-json" class="touch-control" type="text" data-field="weights-json" aria-label="Pesos Q R x0 JSON" />`,
    `<button type="button" id="btn-apply-weights" class="touch-control" data-action="apply-weights">Aplicar Pesos</button>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" class="touch-control" data-action="commit-lqr">Calcular LQR Autoritativo</button>`,
    `<button type="button" class="touch-control" data-action="analyze-open-loop">Analisar Malha Aberta (PBH)</button>`,
    `<button type="button" class="touch-control" data-action="cancel-lqr">Cancelar</button>`,
    `<button type="button" class="touch-control" data-action="undo-lqr">Desfazer</button>`,
    `<button type="button" id="btn-reset-worker" class="touch-control" data-action="reset-worker">Reiniciar Worker</button>`,
    `<button type="button" id="btn-save-experiment" class="touch-control" data-action="save-experiment">Salvar no Comparador</button>`,
    `<button type="button" id="btn-export-pvm" class="touch-control" data-action="export-pvm">Exportar .pvm</button>`,
    `<label for="ctrlab-file-input">Abrir .ctrlab</label><input id="ctrlab-file-input" type="file" accept=".ctrlab,application/zip" class="touch-control" aria-label="Abrir projeto .ctrlab" />`,
    `<button type="button" id="btn-export-ctrlab" class="touch-control" data-action="export-ctrlab">Exportar .ctrlab</button>`,
    `<button type="button" id="btn-export-gains" class="touch-control" data-action="export-gains">Exportar Ganhos JSON</button>`,
    `<button type="button" id="btn-export-csv" class="touch-control" data-action="export-csv">Exportar CSV</button>`,
    `<button type="button" id="btn-build-report" class="touch-control" data-action="build-report">Relatório R-27</button>`,
    `</div>`,
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
    `<section id="typed-workspace-panel" class="panel-card" aria-label="Insumos tipados da sessão">`,
    `<h3>Insumos Tipados da Sessão (Dataset / Modelo / Sistema)</h3>`,
    `<div class="tool-field">`,
    `<label for="typed-object-json">Registrar Objeto Canônico (JSON: Dataset, TransferFunction, StateSpace, IdentifiedModel, FuzzySystem, TS)</label>`,
    `<textarea id="typed-object-json" class="touch-control" rows="3" data-field="typed-object-json" aria-label="Registrar objeto canônico JSON"></textarea>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-register-typed-object" class="touch-control" data-action="register-typed-object">Registrar Objeto Tipado</button>`,
    `<select id="reuse-target-kind" class="touch-control" aria-label="Formato alvo de core.reuse_model">`,
    `<option value="native">Formato nativo do modelo (native)</option>`,
    `<option value="StateSpace">Converter para StateSpace (TF -> SS)</option>`,
    `</select>`,
    `<button type="button" id="btn-reuse-model" class="touch-control" data-action="reuse-model">Derivar via core.reuse_model</button>`,
    `<button type="button" id="btn-register-pending-identified" class="touch-control" data-action="register-pending-identified" disabled aria-disabled="true">Registrar IdentifiedModel Pendente</button>`,
    `<button type="button" id="btn-register-pending-derived" class="touch-control" data-action="register-pending-derived" disabled aria-disabled="true">Registrar Derivado Pendente</button>`,
    `<button type="button" id="btn-apply-selected-to-lqr" class="touch-control" data-action="apply-selected-to-lqr">Aplicar StateSpace Selecionado ao LQR</button>`,
    `</div>`,
    `</div>`,
    `<div id="typed-workspace-selectors-slot"></div>`,
    `<div id="typed-workspace-status-slot"></div>`,
    `</section>`,
    `<section id="identification-workspace-panel" class="panel-card" aria-label="Fluxo Vertical de Identificação (Aba 1)">`,
    `<h3>Fluxo Vertical de Identificação (Aba 1: Dataset Treino/Holdout, Estimação, Resíduos e Reutilização)</h3>`,
    `<div class="tool-field">`,
    `<label for="id-csv-input">Importar Dataset CSV (t, u, y) ou Carregar Benchmark PRBS / Entrada Constante (T-ID-02)</label>`,
    `<textarea id="id-csv-input" class="touch-control" rows="2" data-field="id-csv-input" aria-label="Conteúdo CSV do Dataset (t, u, y)"></textarea>`,
    `<div class="panel-actions">`,
    `<label for="id-train-fraction">Fração Treino (0.1–0.9)</label>`,
    `<input type="number" id="id-train-fraction" class="touch-control" min="0.2" max="0.85" step="0.05" value="0.7" aria-label="Fração de treino para particionamento holdout" />`,
    `<button type="button" id="btn-id-import-csv" class="touch-control" data-action="id-import-csv">Importar CSV + Particionar</button>`,
    `<button type="button" id="btn-id-load-prbs" class="touch-control" data-action="id-load-prbs">Benchmark PRBS (Treino + Holdout)</button>`,
    `<button type="button" id="btn-id-load-const-pe" class="touch-control" data-action="id-load-const-pe">Dataset Entrada Constante (T-ID-02)</button>`,
    `<button type="button" id="btn-id-split-dataset" class="touch-control" data-action="id-split-dataset">Particionar Dataset Selecionado</button>`,
    `</div>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<label for="id-chart-partition-select">Partição Visualizada nos Gráficos de Identificação</label>`,
    `<select id="id-chart-partition-select" class="touch-control" data-action="id-select-partition" aria-label="Partição visualizada nos gráficos de identificação">`,
    `<option value="validation">Validação / Holdout</option>`,
    `<option value="train">Treino</option>`,
    `</select>`,
    `<button type="button" id="btn-id-reuse-to-lqr" class="touch-control" data-action="id-reuse-to-lqr">Derivar StateSpace + Registrar + Aplicar ao LQR (Aba 3)</button>`,
    `<button type="button" id="btn-id-reuse-to-siso" class="touch-control" data-action="id-reuse-to-siso">Derivar Modelo + Registrar + Selecionar em SISO (Aba 2)</button>`,
    `</div>`,
    `<div id="id-diagnostics-panel" class="diagnostics-panel" aria-live="polite"></div>`,
    `<div id="id-response-chart-slot" class="chart-container"></div>`,
    `<div id="id-residuals-chart-slot" class="chart-container"></div>`,
    `<details><summary>Tabela acessível de comparação temporal da identificação (WCAG 2.2 AA)</summary><div id="id-response-table-slot"></div></details>`,
    `<details><summary>Tabela acessível de correlação de resíduos R_ee / R_ue (WCAG 2.2 AA)</summary><div id="id-residuals-table-slot"></div></details>`,
    `</section>`,
    `<div id="lqr-k-display"></div>`,
    `<div id="lqr-diagnostics-panel" class="diagnostics-panel"></div>`,
    `<div id="controllab-tools-slot" class="declarative-tools"></div>`,
    `</section>`,
    `<section class="panel-card">`,
    `<div id="pz-chart-slot" class="chart-container"></div>`,
    `<div id="time-chart-slot" class="chart-container"></div>`,
    `<details><summary>Tabela acessível de polos e valores (WCAG 2.2 AA)</summary><div id="pz-table-slot"></div></details>`,
    `<details><summary>Tabela acessível da resposta temporal (WCAG 2.2 AA)</summary><div id="time-table-slot"></div></details>`,
    `<section id="experiments-compare-panel" aria-label="Comparador de experimentos confirmados"><h3>Comparador de Experimentos Confirmados</h3><div id="experiments-compare-slot"></div></section>`,
    `</section>`,
    `</main>`,
    `<section id="controllab-export-modal" class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="export-modal-title" hidden>`,
    `<div class="modal-header">`,
    `<h2 id="export-modal-title">Artefato Exportado</h2>`,
    `<div class="panel-actions">`,
    `<button type="button" id="export-modal-download" class="touch-control">Baixar arquivo</button>`,
    `<button type="button" id="export-modal-copy" class="touch-control" hidden>Copiar script</button>`,
    `<button type="button" id="export-modal-close" class="touch-control">Fechar</button>`,
    `</div>`,
    `</div>`,
    `<pre id="export-modal-content" class="modal-pre"></pre>`,
    `</section>`,
    `<div id="controllab-live-polite" class="sr-only" aria-live="polite"></div>`,
    `<div id="controllab-live-assertive" class="sr-only" aria-live="assertive"></div>`,
  ].join("\n");

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

  const render = (): void => {
    const activeTab = shell.getActiveTab();
    const themeMode = shell.getThemeMode();
    const decimals = shell.getDisplayDecimals();
    const engineState = shell.getEngineState();
    const committed = lqr.getCommittedSnapshot();
    const preview = lqr.getPreviewState();
    const pendingCommit = lqr.isPendingCommit();
    const exportGuard = lqr.canExport();
    const presentedErr = shell.getPresentedLastError();

    container.setAttribute("data-theme", themeMode);

    if (engineBadgeEl) {
      engineBadgeEl.setAttribute("data-engine-state", engineState);
      const caps = client.getCapabilities();
      engineBadgeEl.textContent = `Motor: ${engineState} | ${caps.engine_kind === "mock" ? "Mock de fixtures (beta)" : "Pyodide (beta)"} | offline não verificado (${serviceWorkerStatus})`;
    }
    if (revSummaryEl) {
      revSummaryEl.textContent = `Rev. Projeto: ${lqr.getProjectRevision()} | Rev. Modelo: ${lqr.getPlant().revision}`;
    }
    if (decimalsInputEl && decimalsInputEl.value !== String(decimals)) {
      decimalsInputEl.value = String(decimals);
    }
    if (themeBtnEl) {
      themeBtnEl.textContent = `Tema: ${themeMode}`;
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
        idDiagnosticsPanelEl.innerHTML = `<p>Aguardando estimação (<code>identification.fit_arx</code> / <code>identification.fit_subspace</code>) ou validação (<code>identification.validate_model</code>) para exibir métricas 1-passo vs simulação livre, PE/posto e resíduos.</p>`;
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
          `<p><strong>Excitação &amp; Posto (T-ID-02):</strong> posto=<code>${escapeHtml(rankDisplay)}</code> | κ(Φ)=<code>${escapeHtml(condDisplay)}</code> | ${peTag}</p>`,
          `<p data-testid="id-train-metrics"><strong>Treino (${escapeHtml(activeIdReport.train_dataset_ref?.id ?? "N/D")}):</strong> Previsão 1-Passo FIT=<code>${escapeHtml(trPredFit)}%</code> (RMSE=<code>${escapeHtml(trPredRmse)}</code>) | Simulação Livre FIT=<code>${escapeHtml(trSimFit)}%</code> (RMSE=<code>${escapeHtml(trSimRmse)}</code>)</p>`,
          `<p data-testid="id-holdout-metrics"><strong>Validação / Holdout (${escapeHtml(activeIdReport.val_dataset_ref?.id ?? "N/D")}, T-ID-03):</strong> Previsão 1-Passo FIT=<code>${escapeHtml(valPredFit)}%</code> (RMSE=<code>${escapeHtml(valPredRmse)}</code>) | Simulação Livre FIT=<code>${escapeHtml(valSimFit)}%</code> (RMSE=<code>${escapeHtml(valSimRmse)}</code>)</p>`,
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
  };

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

  container.querySelector<HTMLElement>('[data-action="apply-plant"]')?.addEventListener("click", () => {
    try {
      const raw = plantJsonInputEl?.value?.trim() ?? "";
      const nextPlant = raw.length > 0 ? JSON.parse(raw) : lqr.getPlant();
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
          ? JSON.parse(raw)
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
