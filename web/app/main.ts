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
import { ControlLabShell } from "./shell.ts";
import {
  PROJECT_TAB_IDS,
  PROJECT_TAB_METADATA,
  type ProjectTabId,
} from "./tool_descriptor.ts";
import {
  buildAccessibleChartTable,
  renderAccessibleTableHtml,
  renderPoleZeroSvg,
  renderTimeResponseSvg,
} from "../charts/scientific_chart.ts";

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
  projectRevision?: number;
  projectId?: string;
  requestId?: string;
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
  const doc = container.ownerDocument;

  let serviceWorkerStatus = "cache não verificado";
  let dragStartQScale = 1.0;
  let lastExportPayload: ExportModalPayload | null = null;
  let lastToolsHtmlKey = "";

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
  const modalDownloadBtnEl = container.querySelector<HTMLElement>("#export-modal-download");
  const livePoliteEl = container.querySelector<HTMLElement>("#controllab-live-polite");
  const liveAssertiveEl = container.querySelector<HTMLElement>("#controllab-live-assertive");
  const tabButtons = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'));

  const exportButtons = [
    container.querySelector<HTMLButtonElement>("#btn-export-pvm"),
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
      engineBadgeEl.textContent = `Motor: ${engineState} | ${caps.engine_kind === "mock" ? "Mock de fixtures (beta)" : "Pyodide (beta; gates Web pendentes)"} | offline não verificado (${serviceWorkerStatus})`;
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

  const openNativeFile = async (kind: "pvm" | "ctrlab", trigger: HTMLElement | null): Promise<void> => {
    const file = kind === "pvm" ? await shell.exportPvm() : await shell.exportCtrlLab();
    openExportModal({ title: `Exportação .${kind}`, filename: file.filename,
      mimeType: file.media_type, bytes: file.bytes, projectRevision: file.project_revision,
      projectId: file.project_id, requestId: file.request_id,
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
  modalDownloadBtnEl?.addEventListener("click", () => {
    if (lastExportPayload && doc) {
      try {
        lqr.assertExportAllowed();
        if (lastExportPayload.projectRevision !== undefined &&
            (lastExportPayload.projectRevision !== lqr.getCommittedSnapshot()?.project_revision ||
             lastExportPayload.projectId !== lqr.getCommittedSnapshot()?.project_id ||
             lastExportPayload.requestId !== lqr.getCommittedSnapshot()?.request_id)) {
          throw new Error("O projeto mudou. Gere novamente o arquivo antes de baixar.");
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
          [paramName]: rawVal.trim() === "" ? Number.NaN : Number(rawVal),
        });
      } else if (paramType === "json" || paramType === "matrix" || paramType === "vector") {
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
      const btn = target?.closest?.('[data-action="execute-tool"]') as HTMLElement | null;
      const toolId = btn?.getAttribute("data-tool-id");
      if (!toolId) return;

      for (const fieldEl of Array.from(toolsSlotEl.querySelectorAll<HTMLElement>(`[data-tool-id="${toolId.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"]`))) {
        if (fieldEl.getAttribute("data-param-name")) {
          syncToolInput(fieldEl);
        }
      }

      const plant = lqr.getPlant();
      const projectId = lqr.getProjectId();
      const execRev = Math.max(
        lqr.getProjectRevision(),
        client.getCommittedRevision(projectId),
      );

      void client
        .registerObject(
          projectId,
          plant.id,
          plant.revision,
          plant as unknown as Record<string, unknown>,
          { kind: "StateSpace", pinProject: true, persistToIndexedDB: false },
        )
        .then(() =>
          tabsCtrl.executeTool(toolId, {
            project_id: projectId,
            project_revision: execRev,
            commitOnSuccess: false,
            extraPayload: {
              plant_ref: { id: plant.id, revision: plant.revision },
            },
          }),
        )
        .then((record) => {
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
