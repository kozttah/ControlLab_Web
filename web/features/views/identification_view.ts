/**
 * Bancada da Aba 1 — Identificação de Sistemas (Estilo MATLAB `ident`)
 * seguindo CL-UX-DIR-001 v1.0.0 Seção 4.1 (`WP-UX-REFACTOR-02-IDENT-SISO-LQR`).
 *
 * Responsabilidades estritas de UI/Apresentação (F8):
 * - Fluxo guiado em 3 etapas: (1) Dados & Partição -> (2) Estimação ARX / Subespaços -> (3) Comparar & Promover.
 * - Quadro de comparação de modelos da sessão (`#id-models-session-list`) com distinção explícita entre
 *   Simulação Livre (Holdout) e Previsão 1-Passo (Holdout), status de Excitação Persistente (PE) e
 *   promoção em 1 clique para SISO (`id-reuse-to-siso`) e SS/LQR (`id-reuse-to-lqr`).
 * - Delega todo cálculo científico ao motor Python via `tabsCtrl.executeTool(...)` e `IdentificationWorkspace`.
 *
 * 100% compatível com erasableSyntaxOnly, verbatimModuleSyntax e FakeElement/FakeDocument.
 */

import { ControlLabBridgeError } from "../../bridge/protocol.ts";
import { escapeHtml, formatNumericDisplay } from "../../app/accessibility.ts";
import type { ControlLabShell } from "../../app/shell.ts";
import {
  buildAccessibleChartTable,
  renderAccessibleTableHtml,
  renderResidualCorrelationSvg,
  renderTimeResponseSvg,
} from "../../charts/scientific_chart.ts";
import type { IdentificationReportView } from "../identification_workspace.ts";

export interface IdentificationViewOptions {
  shell: ControlLabShell;
  container: HTMLElement;
}

interface SessionIdentifiedModelEntry {
  entryId: string;
  label: string;
  report: IdentificationReportView;
  checkedForCompare: boolean;
}

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function renderIdExportBarHtml(slotId: string, label: string): string {
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

export function renderIdentificationViewHtml(): string {
  return [
    `<section id="identification-workspace-panel" class="panel-card workspace-section" aria-label="Identificação de Sistemas">`,
    `<h3>Identificação de Sistemas (Dados → Estimação → Validação)</h3>`,
    `<div id="id-pipeline-bar" class="id-pipeline-bar" role="region" aria-label="Fluxo guiado de identificação">`,
    `<div class="pipeline-step" data-pipeline-step="1" data-step-state="active"><span class="step-num">1</span><span class="step-label">1. Dados &amp; Partição</span></div>`,
    `<span class="pipeline-arrow" aria-hidden="true">→</span>`,
    `<div class="pipeline-step" data-pipeline-step="2" data-step-state="pending"><span class="step-num">2</span><span class="step-label">2. Estimação ARX / Subespaços</span></div>`,
    `<span class="pipeline-arrow" aria-hidden="true">→</span>`,
    `<div class="pipeline-step" data-pipeline-step="3" data-step-state="pending"><span class="step-num">3.</span><span class="step-label">3. Comparar &amp; Promover</span></div>`,
    `</div>`,
    `<div class="workspace-two-col">`,
    `<div class="workspace-controls-col">`,
    `<div class="subcard">`,
    `<h4>1. Dados &amp; Partição Treino / Holdout</h4>`,
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
    `<div class="subcard" id="id-quick-estimation-card">`,
    `<h4>2. Estimação Rápida (ARX / Subespaços)</h4>`,
    `<div class="id-estimator-grid">`,
    `<div class="id-estimator-box">`,
    `<strong>Modelo ARX (QR/SVD)</strong>`,
    `<div class="panel-actions">`,
    `<label for="id-arx-na">na</label>`,
    `<input type="number" id="id-arx-na" class="touch-control id-param-input" min="1" max="24" step="1" value="2" aria-label="Ordem autorregressiva na" />`,
    `<label for="id-arx-nb">nb</label>`,
    `<input type="number" id="id-arx-nb" class="touch-control id-param-input" min="1" max="24" step="1" value="2" aria-label="Ordem da entrada nb" />`,
    `<label for="id-arx-nk">nk</label>`,
    `<input type="number" id="id-arx-nk" class="touch-control id-param-input" min="0" max="50" step="1" value="1" aria-label="Atraso nk" />`,
    `<label for="id-arx-detrend">Pré-proc.</label>`,
    `<select id="id-arx-detrend" class="touch-control" aria-label="Remoção de tendência ARX">`,
    `<option value="none">Sem remoção</option>`,
    `<option value="mean">Remover média</option>`,
    `<option value="linear">Remover tendência linear</option>`,
    `</select>`,
    `<button type="button" id="btn-id-fit-arx" class="touch-control btn-primary" data-action="id-fit-arx">Estimar ARX</button>`,
    `</div>`,
    `</div>`,
    `<div class="id-estimator-box">`,
    `<strong>Subespaços (MOESP / N4SID)</strong>`,
    `<div class="panel-actions">`,
    `<label for="id-sub-method">Método</label>`,
    `<select id="id-sub-method" class="touch-control" aria-label="Método de subespaços">`,
    `<option value="moesp">MOESP</option>`,
    `<option value="n4sid">N4SID</option>`,
    `</select>`,
    `<label for="id-sub-order">Ordem n</label>`,
    `<input type="number" id="id-sub-order" class="touch-control id-param-input" min="1" max="24" step="1" value="2" aria-label="Ordem do sistema n" />`,
    `<label for="id-sub-horizon">Horizonte</label>`,
    `<input type="number" id="id-sub-horizon" class="touch-control id-param-input" min="2" max="60" step="1" value="8" aria-label="Horizonte de Hankel" />`,
    `<button type="button" id="btn-id-fit-subspace" class="touch-control btn-secondary" data-action="id-fit-subspace">Estimar Subespaços</button>`,
    `</div>`,
    `</div>`,
    `</div>`,
    `</div>`,
    `<div class="subcard">`,
    `<h4>3. Visualização, Validação &amp; Promoção</h4>`,
    `<div class="tool-field">`,
    `<label for="id-chart-partition-select">Partição Visualizada nos Gráficos de Identificação</label>`,
    `<select id="id-chart-partition-select" class="touch-control" data-action="id-select-partition" aria-label="Partição visualizada nos gráficos de identificação">`,
    `<option value="validation">Validação / Holdout</option>`,
    `<option value="train">Treino</option>`,
    `</select>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-id-validate-model" class="touch-control btn-secondary" data-action="id-validate-model">Validar em Holdout</button>`,
    `<button type="button" id="btn-id-reuse-to-siso" class="touch-control btn-primary" data-action="id-reuse-to-siso">Projetar Controlador SISO →</button>`,
    `<button type="button" id="btn-id-reuse-to-lqr" class="touch-control btn-secondary" data-action="id-reuse-to-lqr">Enviar para SS / LQR →</button>`,
    `</div>`,
    `</div>`,
    `<div class="subcard">`,
    `<h4>Modelos Estimados na Sessão</h4>`,
    `<div id="id-models-session-list" class="id-models-board" aria-live="polite"></div>`,
    `</div>`,
    `</div>`,
    `<div class="workspace-results-col">`,
    `<div id="id-diagnostics-panel" class="diagnostics-panel" aria-live="polite"></div>`,
    `<div class="chart-card">`,
    `<div id="id-response-chart-slot" class="chart-container"></div>`,
    renderIdExportBarHtml("id-response-chart-slot", "Resposta Temporal"),
    `</div>`,
    `<div class="chart-card">`,
    `<div id="id-residuals-chart-slot" class="chart-container"></div>`,
    renderIdExportBarHtml("id-residuals-chart-slot", "Correlação de Resíduos"),
    `</div>`,
    `<details><summary>Tabela acessível de comparação temporal da identificação (WCAG 2.2 AA)</summary><div id="id-response-table-slot"></div></details>`,
    `<details><summary>Tabela acessível de correlação de resíduos R_ee / R_ue (WCAG 2.2 AA)</summary><div id="id-residuals-table-slot"></div></details>`,
    `</div>`,
    `</div>`,
    `</section>`,
  ].join("\n");
}

function buildSessionEntryLabel(report: IdentificationReportView): string {
  const p = report.parameters_summary;
  if (report.operation === "identification.fit_arx") {
    const na = typeof p.na === "number" ? p.na : "?";
    const nb = typeof p.nb === "number" ? p.nb : "?";
    const nk = typeof p.nk === "number" ? p.nk : "?";
    return `ARX(${na},${nb},${nk})`;
  }
  if (report.operation === "identification.fit_subspace") {
    const ord = typeof p.order === "number" ? p.order : "?";
    const alg = report.algorithm.toUpperCase();
    return `${alg}(n=${ord})`;
  }
  if (report.operation === "identification.validate_model") {
    return `${report.model_ref?.id ?? "Modelo"} (Validado)`;
  }
  return `${report.algorithm} (${report.inner_model_kind ?? "ID"})`;
}

export class IdentificationView {
  private readonly shell: ControlLabShell;
  private readonly container: HTMLElement;

  private readonly panelEl: HTMLElement | null;
  private readonly pipelineBarEl: HTMLElement | null;
  private readonly csvInputEl: HTMLTextAreaElement | null;
  private readonly trainFractionEl: HTMLInputElement | null;
  private readonly partitionSelectEl: HTMLSelectElement | null;

  private readonly arxNaEl: HTMLInputElement | null;
  private readonly arxNbEl: HTMLInputElement | null;
  private readonly arxNkEl: HTMLInputElement | null;
  private readonly arxDetrendEl: HTMLSelectElement | null;
  private readonly subMethodEl: HTMLSelectElement | null;
  private readonly subOrderEl: HTMLInputElement | null;
  private readonly subHorizonEl: HTMLInputElement | null;

  private readonly modelsSessionListEl: HTMLElement | null;
  private readonly diagnosticsPanelEl: HTMLElement | null;
  private readonly responseChartSlotEl: HTMLElement | null;
  private readonly residualsChartSlotEl: HTMLElement | null;
  private readonly responseTableSlotEl: HTMLElement | null;
  private readonly residualsTableSlotEl: HTMLElement | null;

  private readonly sessionModels: SessionIdentifiedModelEntry[] = [];
  private activeFocusedEntryId: string | null = null;
  private lastIngestedKey = "";
  private lastBoardRenderKey = "";

  constructor(options: IdentificationViewOptions) {
    this.shell = options.shell;
    this.container = options.container;

    this.panelEl = this.container.querySelector<HTMLElement>("#identification-workspace-panel");
    this.pipelineBarEl = this.container.querySelector<HTMLElement>("#id-pipeline-bar");
    this.csvInputEl = this.container.querySelector<HTMLTextAreaElement>("#id-csv-input");
    this.trainFractionEl = this.container.querySelector<HTMLInputElement>("#id-train-fraction");
    this.partitionSelectEl = this.container.querySelector<HTMLSelectElement>("#id-chart-partition-select");

    this.arxNaEl = this.container.querySelector<HTMLInputElement>("#id-arx-na");
    this.arxNbEl = this.container.querySelector<HTMLInputElement>("#id-arx-nb");
    this.arxNkEl = this.container.querySelector<HTMLInputElement>("#id-arx-nk");
    this.arxDetrendEl = this.container.querySelector<HTMLSelectElement>("#id-arx-detrend");
    this.subMethodEl = this.container.querySelector<HTMLSelectElement>("#id-sub-method");
    this.subOrderEl = this.container.querySelector<HTMLInputElement>("#id-sub-order");
    this.subHorizonEl = this.container.querySelector<HTMLInputElement>("#id-sub-horizon");

    this.modelsSessionListEl = this.container.querySelector<HTMLElement>("#id-models-session-list");
    this.diagnosticsPanelEl = this.container.querySelector<HTMLElement>("#id-diagnostics-panel");
    this.responseChartSlotEl = this.container.querySelector<HTMLElement>("#id-response-chart-slot");
    this.residualsChartSlotEl = this.container.querySelector<HTMLElement>("#id-residuals-chart-slot");
    this.responseTableSlotEl = this.container.querySelector<HTMLElement>("#id-response-table-slot");
    this.residualsTableSlotEl = this.container.querySelector<HTMLElement>("#id-residuals-table-slot");

    this.bindEvents();
  }

  private getConfiguredTrainFraction(): number {
    const raw = Number(this.trainFractionEl?.value ?? "0.7");
    return Number.isFinite(raw) ? raw : 0.7;
  }

  private async executeQuickTool(
    toolId: "identification.fit_arx" | "identification.fit_subspace" | "identification.validate_model",
    params?: Record<string, unknown>,
  ): Promise<void> {
    const tabsCtrl = this.shell.getTabsController();
    const lqr = this.shell.getLqrWorkspace();
    const idWorkspace = this.shell.getIdentificationWorkspace();

    try {
      if (params && Object.keys(params).length > 0) {
        tabsCtrl.setToolParameters(toolId, params);
      }
      const projectId = lqr.getProjectId();
      const execRev = lqr.getProjectRevision();
      const record = await tabsCtrl.executeTool(toolId, {
        project_id: projectId,
        project_revision: execRev,
        commitOnSuccess: false,
      });
      if (record.response.status === "failure" || !record.response.result) {
        const err = record.response.error ?? {
          code: "VALIDATION_ERROR" as const,
          message: `Operação '${toolId}' falhou.`,
        };
        throw new ControlLabBridgeError(err.code, err.message, {
          parameters: err.parameters,
          next_step: err.next_step,
          details: err.details,
        });
      }
      idWorkspace.ingestExecutionRecord(record);
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  private bindEvents(): void {
    const idWorkspace = this.shell.getIdentificationWorkspace();

    this.container
      .querySelector<HTMLElement>('[data-action="id-import-csv"]')
      ?.addEventListener("click", () => {
        const csvRaw = this.csvInputEl?.value ?? "";
        void idWorkspace
          .importCsvDataset(csvRaw, {
            splitTrainHoldout: true,
            trainFraction: this.getConfiguredTrainFraction(),
          })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="id-load-prbs"]')
      ?.addEventListener("click", () => {
        void idWorkspace
          .loadBenchmarkDataset({
            preset: "prbs",
            splitTrainHoldout: true,
            trainFraction: this.getConfiguredTrainFraction(),
          })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="id-load-const-pe"]')
      ?.addEventListener("click", () => {
        void idWorkspace
          .loadBenchmarkDataset({
            preset: "constant_input",
            splitTrainHoldout: true,
            trainFraction: this.getConfiguredTrainFraction(),
          })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="id-split-dataset"]')
      ?.addEventListener("click", () => {
        void idWorkspace
          .splitSelectedDatasetTrainHoldout({
            trainFraction: this.getConfiguredTrainFraction(),
          })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.partitionSelectEl?.addEventListener("change", () => {
      idWorkspace.setActivePartitionView(
        this.partitionSelectEl?.value === "train" ? "train" : "validation",
      );
    });

    this.container
      .querySelector<HTMLElement>('[data-action="id-fit-arx"]')
      ?.addEventListener("click", () => {
        const na = Number(this.arxNaEl?.value ?? "2");
        const nb = Number(this.arxNbEl?.value ?? "2");
        const nk = Number(this.arxNkEl?.value ?? "1");
        const detrend = (this.arxDetrendEl?.value ?? "none") as "none" | "mean" | "linear";
        void this.executeQuickTool("identification.fit_arx", {
          na: Number.isFinite(na) ? Math.floor(na) : 2,
          nb: Number.isFinite(nb) ? Math.floor(nb) : 2,
          nk: Number.isFinite(nk) ? Math.floor(nk) : 1,
          detrend,
        });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="id-fit-subspace"]')
      ?.addEventListener("click", () => {
        const method = this.subMethodEl?.value === "n4sid" ? "n4sid" : "moesp";
        const order = Number(this.subOrderEl?.value ?? "2");
        const horizon = Number(this.subHorizonEl?.value ?? "8");
        void this.executeQuickTool("identification.fit_subspace", {
          method,
          order: Number.isFinite(order) ? Math.floor(order) : 2,
          horizon: Number.isFinite(horizon) ? Math.floor(horizon) : 8,
        });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="id-validate-model"]')
      ?.addEventListener("click", () => {
        void idWorkspace
          .validateModel({ autoRegisterPendingIfNeeded: true })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="id-reuse-to-lqr"]')
      ?.addEventListener("click", () => {
        void idWorkspace
          .reuseIdentifiedModel({
            targetKind: "StateSpace",
            registerIdentifiedIfPending: true,
            registerDerived: true,
            applyToDestination: "lqr",
          })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });

    this.container
      .querySelector<HTMLElement>('[data-action="id-reuse-to-siso"]')
      ?.addEventListener("click", () => {
        void idWorkspace
          .reuseIdentifiedModel({
            targetKind: "native",
            registerIdentifiedIfPending: true,
            registerDerived: true,
            applyToDestination: "siso_frequency",
          })
          .catch((err: unknown) => {
            this.shell.presentError(err);
          });
      });
  }

  private syncSessionModels(activeReport: IdentificationReportView | null): void {
    if (!activeReport) return;
    const key = `${activeReport.request_id}:${activeReport.recorded_at}`;
    if (key === this.lastIngestedKey) return;
    this.lastIngestedKey = key;

    if (activeReport.operation === "identification.validate_model" && activeReport.model_ref) {
      const existing = this.sessionModels.find(
        (m) =>
          m.report.model_ref?.id === activeReport.model_ref?.id &&
          m.report.model_ref?.revision === activeReport.model_ref?.revision,
      );
      if (existing) {
        existing.report = activeReport;
        this.activeFocusedEntryId = existing.entryId;
        return;
      }
    }

    const entryId = `id-model-${this.sessionModels.length + 1}-${activeReport.request_id}`;
    this.sessionModels.push({
      entryId,
      label: buildSessionEntryLabel(activeReport),
      report: activeReport,
      checkedForCompare: true,
    });
    this.activeFocusedEntryId = entryId;
  }

  private updatePipelineBar(activeReport: IdentificationReportView | null): void {
    if (!this.pipelineBarEl) return;
    const typed = this.shell.getTypedWorkspace();
    const hasDataset = typed.getEffectiveSelection("dataset") !== null;
    const hasModel = activeReport !== null || this.sessionModels.length > 0;
    const hasValidation = activeReport?.validation_metrics !== null && activeReport?.validation_metrics !== undefined;

    const states: Record<string, "pending" | "active" | "done"> = {
      "1": hasDataset ? "done" : "active",
      "2": hasModel ? "done" : hasDataset ? "active" : "pending",
      "3": hasValidation ? "active" : hasModel ? "active" : "pending",
    };

    const steps = Array.from(this.pipelineBarEl.querySelectorAll<HTMLElement>("[data-pipeline-step]"));
    for (const step of steps) {
      const num = step.getAttribute("data-pipeline-step");
      if (num && states[num]) {
        step.setAttribute("data-step-state", states[num]);
      }
    }
  }

  private renderSessionModelsBoard(decimals: number): void {
    if (!this.modelsSessionListEl) return;

    const boardKey = JSON.stringify({
      decimals,
      active: this.activeFocusedEntryId,
      items: this.sessionModels.map((m) => [
        m.entryId,
        m.checkedForCompare,
        m.report.request_id,
        m.report.validation_metrics?.free_simulation.fit_percent,
      ]),
    });
    if (boardKey === this.lastBoardRenderKey) return;
    this.lastBoardRenderKey = boardKey;

    if (this.sessionModels.length === 0) {
      this.modelsSessionListEl.innerHTML = `<p class="dock-empty">Nenhum modelo estimado nesta sessão ainda. Carregue dados na Etapa 1 e clique em "Estimar ARX" ou "Estimar Subespaços".</p>`;
      return;
    }

    const fmt = (v: number | null | undefined) =>
      typeof v === "number" && Number.isFinite(v) ? formatNumericDisplay(v, decimals) : "N/D";

    const cardsHtml = this.sessionModels
      .map((entry) => {
        const rep = entry.report;
        const valM = rep.validation_metrics;
        const trM = rep.train_metrics;
        const freeFit = fmt(valM?.free_simulation.fit_percent ?? trM?.free_simulation.fit_percent);
        const freeRmse = fmt(valM?.free_simulation.rmse ?? trM?.free_simulation.rmse);
        const oneStepFit = fmt(valM?.one_step_prediction.fit_percent ?? trM?.one_step_prediction.fit_percent);
        const oneStepRmse = fmt(valM?.one_step_prediction.rmse ?? trM?.one_step_prediction.rmse);
        const aicStr = fmt(rep.information_criteria.aic);
        const peBad = rep.excitation.pe_satisfied === false || rep.excitation.rank_deficient;
        const peBadge = peBad
          ? `<span class="badge badge-approximate" data-pe-badge="insufficient">PE Insuficiente</span>`
          : `<span class="badge badge-exact" data-pe-badge="satisfied">PE OK</span>`;
        const refText = rep.model_ref ? `${rep.model_ref.id}#r${rep.model_ref.revision}` : rep.algorithm;
        const isFocused = entry.entryId === this.activeFocusedEntryId;

        return [
          `<div class="id-model-card${isFocused ? " id-model-card-active" : ""}" data-session-model-id="${escapeHtml(entry.entryId)}">`,
          `<div class="id-model-card-head">`,
          `<label class="id-model-check-label">`,
          `<input type="checkbox" class="id-model-compare-checkbox" data-action="id-toggle-compare-model" data-entry-id="${escapeHtml(entry.entryId)}"${entry.checkedForCompare ? " checked" : ""} aria-label="Comparar ${escapeHtml(entry.label)}" />`,
          `<strong>${escapeHtml(entry.label)}</strong>`,
          `</label>`,
          `<span class="id-model-ref-code">${escapeHtml(refText)}</span>`,
          peBadge,
          `</div>`,
          `<div class="id-model-metrics-grid">`,
          `<span><strong>Simulação Livre (Holdout):</strong> FIT=${escapeHtml(freeFit)}% (RMSE=${escapeHtml(freeRmse)})</span>`,
          `<span><strong>Previsão 1-Passo (Holdout):</strong> FIT=${escapeHtml(oneStepFit)}% (RMSE=${escapeHtml(oneStepRmse)})</span>`,
          `<span><strong>AIC:</strong> ${escapeHtml(aicStr)} | <strong>dt:</strong> ${escapeHtml(String(rep.dt ?? "N/D"))} s</span>`,
          `</div>`,
          `<div class="panel-actions">`,
          `<button type="button" class="touch-control btn-secondary btn-small" data-action="id-focus-session-model" data-entry-id="${escapeHtml(entry.entryId)}">Inspecionar</button>`,
          `<button type="button" class="touch-control btn-secondary btn-small" data-action="id-card-promote-siso" data-entry-id="${escapeHtml(entry.entryId)}">Projetar SISO →</button>`,
          `<button type="button" class="touch-control btn-secondary btn-small" data-action="id-card-promote-lqr" data-entry-id="${escapeHtml(entry.entryId)}">Enviar SS/LQR →</button>`,
          `</div>`,
          `</div>`,
        ].join("");
      })
      .join("");

    const compared = this.sessionModels.filter((m) => m.checkedForCompare);
    const compareTableHtml =
      compared.length > 1
        ? [
            `<div class="id-compare-table-wrap">`,
            `<table class="accessible-data-table" aria-label="Comparação de modelos selecionados">`,
            `<thead><tr><th scope="col">Modelo</th><th scope="col">Sim. Livre (Holdout) FIT%</th><th scope="col">Previsão 1-Passo (Holdout) FIT%</th><th scope="col">AIC</th><th scope="col">Excitação (PE)</th></tr></thead>`,
            `<tbody>`,
            ...compared.map((entry) => {
              const rep = entry.report;
              const peOk = !(rep.excitation.pe_satisfied === false || rep.excitation.rank_deficient);
              return `<tr><th scope="row">${escapeHtml(entry.label)}</th><td>${escapeHtml(fmt(rep.validation_metrics?.free_simulation.fit_percent))}%</td><td>${escapeHtml(fmt(rep.validation_metrics?.one_step_prediction.fit_percent))}%</td><td>${escapeHtml(fmt(rep.information_criteria.aic))}</td><td>${peOk ? "OK" : "Insuficiente"}</td></tr>`;
            }),
            `</tbody></table></div>`,
          ].join("")
        : "";

    this.modelsSessionListEl.innerHTML = cardsHtml + compareTableHtml;

    for (const cb of Array.from(
      this.modelsSessionListEl.querySelectorAll<HTMLInputElement>('[data-action="id-toggle-compare-model"]'),
    )) {
      cb.addEventListener("change", () => {
        const id = cb.getAttribute("data-entry-id");
        const found = this.sessionModels.find((m) => m.entryId === id);
        if (found) {
          found.checkedForCompare = cb.checked;
          this.lastBoardRenderKey = "";
          this.renderSessionModelsBoard(decimals);
        }
      });
    }

    for (const btn of Array.from(
      this.modelsSessionListEl.querySelectorAll<HTMLElement>('[data-action="id-focus-session-model"]'),
    )) {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-entry-id");
        const found = this.sessionModels.find((m) => m.entryId === id);
        if (found) {
          this.activeFocusedEntryId = found.entryId;
          if (found.report.model_ref) {
            try {
              this.shell.getTypedWorkspace().selectRef("validationModel", found.report.model_ref, {
                allowHistoricalDowngrade: true,
              });
            } catch {
              // ignore if model is pending
            }
          }
          this.lastBoardRenderKey = "";
          this.render();
        }
      });
    }

    for (const btn of Array.from(
      this.modelsSessionListEl.querySelectorAll<HTMLElement>('[data-action="id-card-promote-siso"]'),
    )) {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-entry-id");
        const found = this.sessionModels.find((m) => m.entryId === id);
        const ref = found?.report.model_ref;
        if (ref) {
          try {
            this.shell.getTypedWorkspace().selectRef("reuseSource", ref, {
              allowHistoricalDowngrade: true,
            });
          } catch {
            // Model may still be pending registration; reuseIdentifiedModel handles pending
          }
        }
        void this.shell
          .getIdentificationWorkspace()
          .reuseIdentifiedModel({
            targetKind: "native",
            registerIdentifiedIfPending: true,
            registerDerived: true,
            applyToDestination: "siso_frequency",
          })
          .catch((err: unknown) => this.shell.presentError(err));
      });
    }

    for (const btn of Array.from(
      this.modelsSessionListEl.querySelectorAll<HTMLElement>('[data-action="id-card-promote-lqr"]'),
    )) {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-entry-id");
        const found = this.sessionModels.find((m) => m.entryId === id);
        const ref = found?.report.model_ref;
        if (ref) {
          try {
            this.shell.getTypedWorkspace().selectRef("reuseSource", ref, {
              allowHistoricalDowngrade: true,
            });
          } catch {
            // Model may still be pending registration; reuseIdentifiedModel handles pending
          }
        }
        void this.shell
          .getIdentificationWorkspace()
          .reuseIdentifiedModel({
            targetKind: "StateSpace",
            registerIdentifiedIfPending: true,
            registerDerived: true,
            applyToDestination: "lqr",
          })
          .catch((err: unknown) => this.shell.presentError(err));
      });
    }
  }

  public getSessionModels(): readonly SessionIdentifiedModelEntry[] {
    return this.sessionModels;
  }

  public render(): void {
    const activeTab = this.shell.getActiveTab();
    const isIdentification = activeTab === "identification";
    setElHidden(this.panelEl, !isIdentification);

    const idWorkspace = this.shell.getIdentificationWorkspace();
    const decimals = this.shell.getDisplayDecimals();

    if (this.partitionSelectEl) {
      this.partitionSelectEl.value = idWorkspace.getActivePartitionView();
    }

    const activeIdReport = idWorkspace.getActiveReport();
    this.syncSessionModels(activeIdReport);
    this.updatePipelineBar(activeIdReport);
    this.renderSessionModelsBoard(decimals);

    const focusedReport =
      this.sessionModels.find((m) => m.entryId === this.activeFocusedEntryId)?.report ??
      activeIdReport;

    if (this.diagnosticsPanelEl) {
      if (!focusedReport) {
        this.diagnosticsPanelEl.innerHTML = `<p>Aguardando estimação (ARX ou Subespaços) ou validação em holdout para exibir métricas 1-passo vs simulação livre, excitação e resíduos.</p>`;
      } else {
        const fmtMetric = (val: number | null) =>
          val !== null ? formatNumericDisplay(val, decimals) : "N/D";
        const trPredFit = fmtMetric(
          focusedReport.train_metrics?.one_step_prediction.fit_percent ?? null,
        );
        const trSimFit = fmtMetric(
          focusedReport.train_metrics?.free_simulation.fit_percent ?? null,
        );
        const trPredRmse = fmtMetric(
          focusedReport.train_metrics?.one_step_prediction.rmse ?? null,
        );
        const trSimRmse = fmtMetric(
          focusedReport.train_metrics?.free_simulation.rmse ?? null,
        );

        const valPredFit = fmtMetric(
          focusedReport.validation_metrics?.one_step_prediction.fit_percent ?? null,
        );
        const valSimFit = fmtMetric(
          focusedReport.validation_metrics?.free_simulation.fit_percent ?? null,
        );
        const valPredRmse = fmtMetric(
          focusedReport.validation_metrics?.one_step_prediction.rmse ?? null,
        );
        const valSimRmse = fmtMetric(
          focusedReport.validation_metrics?.free_simulation.rmse ?? null,
        );

        const condDisplay = fmtMetric(focusedReport.excitation.condition);
        const rhoDisplay = fmtMetric(focusedReport.spectral_radius);
        const rankDisplay =
          focusedReport.excitation.rank !== null
            ? `${String(focusedReport.excitation.rank)}/${String(focusedReport.excitation.expected_rank ?? "?")}`
            : "N/D";
        const isPeInsufficient =
          focusedReport.excitation.pe_satisfied === false ||
          focusedReport.excitation.rank_deficient;
        const peTag = isPeInsufficient
          ? `<strong data-pe-status="insufficient">Deficiente / PE Insuficiente (rank_deficient=true)</strong>`
          : `<span data-pe-status="satisfied">Posto completo / PE satisfeita</span>`;

        const peDidacticBanner = isPeInsufficient
          ? `<div class="warning-callout id-pe-didactic-banner" role="status"><strong>Excitação insuficiente (posto ${escapeHtml(rankDisplay)}):</strong> um sinal constante ou degrau simples não excita todos os modos desta ordem. Use sinal PRBS/multisseno ou reduza a ordem do modelo.</div>`
          : "";

        const warnItemsHtml =
          focusedReport.warnings.length > 0
            ? `<ul class="id-warnings-list" data-testid="id-warnings-list">${focusedReport.warnings
                .map((w) =>
                  typeof w === "string"
                    ? `<li><code>WARNING</code>: ${escapeHtml(w)}</li>`
                    : `<li data-warning-code="${escapeHtml(w.code)}"><code>${escapeHtml(w.code)}</code>: ${escapeHtml(w.message)}</li>`,
                )
                .join("")}</ul>`
            : "";

        this.diagnosticsPanelEl.innerHTML = [
          peDidacticBanner,
          `<p><strong>Modelo Identificado:</strong> algoritmo <code>${escapeHtml(focusedReport.algorithm)}</code> | status <code>${escapeHtml(focusedReport.status)}</code> | representação <code>${escapeHtml(focusedReport.inner_model_kind ?? "N/D")}</code> | dt=<code>${escapeHtml(String(focusedReport.dt ?? "N/D"))}</code> | ρ(A)=<code>${escapeHtml(rhoDisplay)}</code> (${focusedReport.is_stable === false ? "INSTÁVEL" : "estável"})</p>`,
          `<p><strong>Excitação &amp; Posto:</strong> posto=<code>${escapeHtml(rankDisplay)}</code> | κ(Φ)=<code>${escapeHtml(condDisplay)}</code> | ${peTag}</p>`,
          `<p data-testid="id-train-metrics"><strong>Treino (${escapeHtml(focusedReport.train_dataset_ref?.id ?? "N/D")}):</strong> Previsão 1-Passo FIT=<code>${escapeHtml(trPredFit)}%</code> (RMSE=<code>${escapeHtml(trPredRmse)}</code>) | Simulação Livre FIT=<code>${escapeHtml(trSimFit)}%</code> (RMSE=<code>${escapeHtml(trSimRmse)}</code>)</p>`,
          `<p data-testid="id-holdout-metrics"><strong>Validação / Holdout (${escapeHtml(focusedReport.val_dataset_ref?.id ?? "N/D")}):</strong> Previsão 1-Passo FIT=<code>${escapeHtml(valPredFit)}%</code> (RMSE=<code>${escapeHtml(valPredRmse)}</code>) | Simulação Livre FIT=<code>${escapeHtml(valSimFit)}%</code> (RMSE=<code>${escapeHtml(valSimRmse)}</code>)</p>`,
          `<p><strong>Critérios de Informação:</strong> AIC=<code>${escapeHtml(fmtMetric(focusedReport.information_criteria.aic))}</code> | BIC=<code>${escapeHtml(fmtMetric(focusedReport.information_criteria.bic))}</code> | FPE=<code>${escapeHtml(fmtMetric(focusedReport.information_criteria.fpe))}</code></p>`,
          warnItemsHtml,
        ].join("");
      }
    }

    const idRespChart = idWorkspace.buildResponseChart();
    if (this.responseChartSlotEl) {
      this.responseChartSlotEl.innerHTML = idRespChart
        ? renderTimeResponseSvg(idRespChart, { decimals })
        : "";
    }
    if (this.responseTableSlotEl) {
      if (idRespChart) {
        const respTable = buildAccessibleChartTable(idRespChart, decimals);
        this.responseTableSlotEl.innerHTML = renderAccessibleTableHtml(respTable);
      } else {
        this.responseTableSlotEl.innerHTML = `<p>Sem séries temporais de identificação para exibir.</p>`;
      }
    }

    const idResidChart = idWorkspace.buildResidualCorrelationChart();
    if (this.residualsChartSlotEl) {
      this.residualsChartSlotEl.innerHTML = idResidChart
        ? renderResidualCorrelationSvg(idResidChart, { decimals })
        : "";
    }
    if (this.residualsTableSlotEl) {
      if (idResidChart) {
        const residTable = buildAccessibleChartTable(idResidChart, decimals);
        this.residualsTableSlotEl.innerHTML = renderAccessibleTableHtml(residTable);
      } else {
        this.residualsTableSlotEl.innerHTML = `<p>Sem diagnóstico de correlação de resíduos para exibir.</p>`;
      }
    }
  }
}
