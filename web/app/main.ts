/**
 * Adaptador DOM/browser enxuto para o ControlLab Web (alinhado com `/index.html`,
 * `/app/main.js` em `web/worker/service_worker.ts`, CL-DIR-001 e CL-UX-DIR-001).
 *
 * Orquestra `ControlLabShell`, Top Bar, `WorkspaceDockController`, as bancadas
 * modulares (`IdentificationView`, `SisoView`, `StatespaceView`), `InspectorDrawerController`,
 * ferramentas declarativas e exportação científica com invariantes R-23/R-26/R-27.
 *
 * 100% compatível com erasableSyntaxOnly, verbatimModuleSyntax e FakeElement/FakeDocument.
 */

import type { ControlLabEngineClient } from "../bridge/client.ts";
import { ControlLabBridgeError, type RealTensor } from "../bridge/protocol.ts";
import { MockWorkerAdapter } from "../bridge/mock_adapter.ts";
import { PyodideEngineClient } from "../bridge/pyodide_client.ts";
import {
  escapeHtml,
  formatNumericDisplay,
  getTabAriaAttributes,
  getTabPanelAriaAttributes,
} from "./accessibility.ts";
import { ControlLabShell } from "./shell.ts";
import {
  PROJECT_TAB_IDS,
  PROJECT_TAB_METADATA,
  type ProjectTabId,
} from "./tool_descriptor.ts";
import {
  buildAccessibleChartTable,
  getChartExportFilename,
  renderAccessibleTableHtml,
  renderPoleZeroSvg,
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
import {
  renderNewObjectModalHtml,
  renderWorkspaceDockHtml,
  WorkspaceDockController,
} from "./workspace_dock.ts";
import {
  InspectorDrawerController,
  renderInspectorDrawerHtml,
} from "./inspector_drawer.ts";
import {
  IdentificationView,
  renderIdentificationViewHtml,
} from "../features/views/identification_view.ts";
import {
  renderSisoViewHtml,
  SisoView,
} from "../features/views/siso_view.ts";
import {
  renderStatespaceJsonModalHtml,
  renderStatespaceViewHtml,
  StatespaceView,
  type StatespaceExportModalRequest,
} from "../features/views/statespace_view.ts";

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
    type: "module",
    scope: assets.serviceWorkerScope,
    updateViaCache: "none",
  });
}

export interface MountedControlLabApp {
  shell: ControlLabShell;
  client: ControlLabEngineClient;
  destroy(): void;
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

function makeFloat64Tensor(shape: number[], data: number[]): RealTensor {
  return { shape, dtype: "float64", order: "C", data };
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

function triggerBrowserDownload(payload: StatespaceExportModalRequest, doc: Document): void {
  if (
    typeof Blob === "undefined" ||
    typeof URL === "undefined" ||
    typeof URL.createObjectURL !== "function"
  ) {
    return;
  }
  const blob = new Blob(
    [payload.bytes ? new Uint8Array(payload.bytes).buffer : payload.content],
    { type: payload.mimeType },
  );
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
  const doc = container.ownerDocument;

  let serviceWorkerStatus = "cache não verificado";
  let lastExportPayload: StatespaceExportModalRequest | null = null;
  let lastToolsHtmlKey = "";
  let lastTypedWorkspaceHtmlKey = "";
  let lastSyncedHashTab: ProjectTabId = shell.getActiveTab();
  let projectTitle = "Projeto ControlLab";

  const initialPlant = lqr.getPlant();
  const initialDims = {
    n: initialPlant.matrices.A.shape[0],
    m: initialPlant.matrices.B.shape[1],
    p: initialPlant.matrices.C.shape[0],
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
    renderIdentificationViewHtml(),
    renderSisoViewHtml(),
    renderStatespaceViewHtml(initialDims),
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
    renderStatespaceJsonModalHtml(),
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

  const typedObjectJsonEl = container.querySelector<HTMLTextAreaElement>("#typed-object-json");
  const reuseTargetKindEl = container.querySelector<HTMLSelectElement>("#reuse-target-kind");
  const btnRegisterPendingIdentifiedEl = container.querySelector<HTMLButtonElement>("#btn-register-pending-identified");
  const btnRegisterPendingDerivedEl = container.querySelector<HTMLButtonElement>("#btn-register-pending-derived");
  const typedSelectorsSlotEl = container.querySelector<HTMLElement>("#typed-workspace-selectors-slot");
  const typedStatusSlotEl = container.querySelector<HTMLElement>("#typed-workspace-status-slot");
  const typedTfIdEl = container.querySelector<HTMLInputElement>("#typed-tf-id");
  const typedTfNumEl = container.querySelector<HTMLInputElement>("#typed-tf-num");
  const typedTfDenEl = container.querySelector<HTMLInputElement>("#typed-tf-den");
  const typedTfDtEl = container.querySelector<HTMLInputElement>("#typed-tf-dt");

  const chartsPanelEl = container.querySelector<HTMLElement>("#controllab-charts-panel");
  const pzTableDetailsEl = container.querySelector<HTMLElement>("#pz-table-details");
  const timeTableDetailsEl = container.querySelector<HTMLElement>("#time-table-details");
  const experimentsComparePanelEl = container.querySelector<HTMLElement>("#experiments-compare-panel");
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
  const modalCopyBtnEl = container.querySelector<HTMLElement>("#export-modal-copy");
  const modalDownloadBtnEl = container.querySelector<HTMLElement>("#export-modal-download");
  const livePoliteEl = container.querySelector<HTMLElement>("#controllab-live-polite");
  const liveAssertiveEl = container.querySelector<HTMLElement>("#controllab-live-assertive");
  const tabButtons = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'));

  const openExportModal = (
    payload: StatespaceExportModalRequest,
    trigger: HTMLElement | null,
  ): void => {
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

  const identificationView = new IdentificationView({ shell, container });
  const sisoView = new SisoView({ shell, container });
  const statespaceView = new StatespaceView({
    shell,
    container,
    onOpenExportModal: openExportModal,
  });

  const render = (): void => {
    const activeTab = shell.getActiveTab();
    if (activeTab !== lastSyncedHashTab) {
      lastSyncedHashTab = activeTab;
      writeTabToLocationHash(activeTab);
    }
    const isStatespace = activeTab === "statespace";
    const isIdentification = activeTab === "identification";
    const isSiso = activeTab === "siso_frequency";

    setHidden(chartsPanelEl, !(isStatespace || isIdentification));
    setHidden(pzChartSlotEl, !(isStatespace || isIdentification));
    setHidden(pzTableDetailsEl, !(isStatespace || isIdentification));
    setHidden(timeChartSlotEl, !isStatespace);
    setHidden(timeTableDetailsEl, !isStatespace);
    setHidden(experimentsComparePanelEl, !isStatespace);
    toggleCssClass(mainEl, "single-main-col", !(isStatespace || isIdentification));
    toggleCssClass(mainEl, "tab-identification", isIdentification);

    const themeMode = shell.getThemeMode();
    const decimals = shell.getDisplayDecimals();
    const engineState = shell.getEngineState();
    const exportGuard = lqr.canExport();
    const presentedErr = shell.getPresentedLastError();

    container.setAttribute("data-theme", themeMode);

    if (
      projectTitleInputEl &&
      doc?.activeElement !== projectTitleInputEl &&
      projectTitleInputEl.value !== projectTitle
    ) {
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
      themeBtnEl.textContent =
        themeMode === "standard_aa" ? "Tema: Claro AA" : "Tema: Alto Contraste";
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

    identificationView.render();
    sisoView.render();
    statespaceView.render();

    if (isStatespace) {
      const pzChart = lqr.buildPoleZeroChart();
      if (pzChartSlotEl) {
        pzChartSlotEl.innerHTML = renderPoleZeroSvg(pzChart, { decimals });
      }
      if (pzTableSlotEl) {
        const pzTable = buildAccessibleChartTable(pzChart, decimals);
        pzTableSlotEl.innerHTML = renderAccessibleTableHtml(pzTable);
      }

      const timeChart = lqr.buildTimeResponseChart();
      if (timeChartSlotEl) {
        timeChartSlotEl.innerHTML = timeChart
          ? renderTimeResponseSvg(timeChart, { decimals })
          : "";
      }
      if (timeTableSlotEl) {
        if (timeChart) {
          const timeTable = buildAccessibleChartTable(timeChart, decimals);
          timeTableSlotEl.innerHTML = renderAccessibleTableHtml(timeTable);
        } else {
          timeTableSlotEl.innerHTML = `<p>Sem trajetória temporal comitada.</p>`;
        }
      }
    } else if (isIdentification) {
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
      const isSisoBlocked =
        isSiso && slotId.startsWith("siso-") && sisoView.isPreviewActive();
      const canExportChart = barVisible && !isLqrBlocked && !isSisoBlocked;
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

  container.querySelector<HTMLElement>('[data-action="reset-worker"]')?.addEventListener("click", () => {
    void client.resetWorker("Reiniciado manualmente pelo usuário na UI").catch((err: unknown) => {
      shell.presentError(err);
    });
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

  const handleChartExport = (slotId: string, format: "svg" | "png"): void => {
    try {
      if (
        shell.getActiveTab() === "statespace" &&
        (slotId === "pz-chart-slot" || slotId === "time-chart-slot")
      ) {
        lqr.assertExportAllowed();
      }
      if (
        shell.getActiveTab() === "siso_frequency" &&
        slotId.startsWith("siso-") &&
        sisoView.isPreviewActive()
      ) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Exportação bloqueada durante Fast-Preview transitório SISO (solte o slider antes de exportar).",
        );
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

  modalCloseBtnEl?.addEventListener("click", closeExportModal);
  modalCopyBtnEl?.addEventListener("click", () => {
    if (!lastExportPayload?.offlineDesign) return;
    if (!globalThis.navigator?.clipboard) {
      shell.presentError(new Error("Cópia indisponível neste navegador. Selecione o texto ou baixe o script."));
      return;
    }
    void globalThis.navigator.clipboard
      .writeText(lastExportPayload.content)
      .then(() => {
        if (livePoliteEl) livePoliteEl.textContent = "Script copiado.";
      })
      .catch((error: unknown) => shell.presentError(error));
  });
  modalDownloadBtnEl?.addEventListener("click", () => {
    if (lastExportPayload && doc) {
      try {
        if (lastExportPayload.pvmControllerKind === "dynamic") {
          shell.assertDynamicPvmExportAllowed(
            lastExportPayload.requestId,
            lastExportPayload.configurationRevision,
          );
        } else if (!lastExportPayload.offlineDesign) {
          lqr.assertExportAllowed();
        }
        if (
          lastExportPayload.pvmControllerKind !== "dynamic" &&
          lastExportPayload.projectRevision !== undefined &&
          (lastExportPayload.projectRevision !== lqr.getCommittedSnapshot()?.project_revision ||
            lastExportPayload.projectId !== lqr.getCommittedSnapshot()?.project_id ||
            lastExportPayload.requestId !== lqr.getCommittedSnapshot()?.request_id)
        ) {
          throw new Error("O projeto mudou. Gere novamente o arquivo antes de baixar.");
        }
        if (
          lastExportPayload.configurationRevision !== undefined &&
          lastExportPayload.configurationRevision !== shell.getPvmExportRevision()
        ) {
          throw new Error("A configuração PVM mudou. Gere novamente o arquivo antes de baixar.");
        }
        triggerBrowserDownload(lastExportPayload, doc);
      } catch (error: unknown) {
        shell.presentError(error);
      }
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
      const rawVal =
        "value" in target ? String((target as HTMLInputElement | HTMLSelectElement).value) : "";
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
      const btn = (target?.closest?.('[data-action="execute-tool"]') ??
        target?.closest?.('[data-action="export-sdp"]')) as HTMLElement | null;
      const toolId = btn?.getAttribute("data-tool-id");
      if (!toolId) return;

      for (const fieldEl of Array.from(
        toolsSlotEl.querySelectorAll<HTMLElement>(
          `[data-tool-id="${toolId.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"]`,
        ),
      )) {
        if (fieldEl.getAttribute("data-param-name")) {
          syncToolInput(fieldEl);
        }
      }

      if (btn?.getAttribute("data-action") === "export-sdp") {
        const format = btn.getAttribute("data-format") === "yalmip" ? "yalmip" : "cvxpy";
        const validation = tabsCtrl
          .getTabViewModel("optimization_lmi")
          .tools.find((tool) => tool.toolId === toolId)?.validation;
        if (!validation?.valid) {
          shell.presentError(new Error("Corrija os parâmetros do problema antes de exportar."));
          return;
        }
        const feedbackSelectEl = container.querySelector<HTMLSelectElement>("#lqr-feedback-sign");
        const feedbackSign = feedbackSelectEl?.value === "positive" ? "positive" : "negative";
        void typedWorkspace
          .prepareSdpExportSpecification(validation.sanitized, feedbackSign)
          .then((specification) => shell.exportSdpScript(format, specification))
          .then((file) => {
            openExportModal(
              {
                title: `Execução offline / ${format.toUpperCase()}`,
                filename: file.filename,
                mimeType: file.media_type,
                content: file.script,
                offlineDesign: true,
              },
              btn,
            );
          })
          .catch((error: unknown) => shell.presentError(error));
        return;
      }

      const projectId = lqr.getProjectId();
      const execRev = Math.max(
        lqr.getProjectRevision(),
        client.getCommittedRevision(projectId),
      );
      const feedbackSelectEl = container.querySelector<HTMLSelectElement>("#lqr-feedback-sign");
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
      "assertive",
      "error",
    );
    render();
  });
  if (typeof navigator !== "undefined" && options?.engineMode !== "mock" && !options?.client) {
    void registerControlLabServiceWorker(navigator.serviceWorker)
      .then((registration) => {
        serviceWorkerStatus = registration
          ? "SW registrado; cache não verificado"
          : "SW indisponível";
        render();
      })
      .catch(() => {
        serviceWorkerStatus = "falha ao registrar SW";
        shell
          .getAnnouncer()
          .announce(
            "Falha ao registrar cache offline; cálculo offline não verificado.",
            "polite",
            "status",
          );
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
