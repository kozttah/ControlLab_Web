/**
 * Bancada da Aba 6 — Obtenção de Modelos TS (Setor, TPMT & FEMT)
 * (CL-TS-MOD-DIR-001 Seções 1.2, 2, 5-7; ADR-014).
 *
 * Fluxo guiado Via 1 (Setor) / Via 2 (TPMT) / Via 3 (FEMT) com presets didáticos,
 * gráficos 1D/2D, promoção em 1 clique ao Workspace Dock e exportação passiva de
 * scripts Python/MATLAB. Consome o backend exclusivamente pela ponte tipada
 * (`TsModelingEngineClient`). ZERO `eval`/`new Function`; texto dinâmico sempre
 * escapado (R-21); a substituição de premissas é puramente textual.
 */

import {
  supportsTsModeling,
  type ControlLabEngineClient,
  type TsModelingEngineClient,
} from "../../bridge/client.ts";
import { ControlLabBridgeError, generateUuid, isPlainObject } from "../../bridge/protocol.ts";
import type {
  DerivedTsFemtResult,
  DerivedTsSectorResult,
  DerivedTsTpmtResult,
  SectorPremiseSpec,
  TsDerivationLanguage,
  TsHull,
  TsModelingContext,
  TsRpcResponse,
} from "../../bridge/ts_modeling.ts";
import { escapeHtml, formatNumericDisplay } from "../../app/accessibility.ts";
import type { ControlLabShell } from "../../app/shell.ts";
import {
  buildBasesChartModel,
  buildMembership1DChartModel,
  buildMesh2DModel,
  buildOffGridErrorHeatmap,
  buildScreeChartModel,
  renderTsHeatmapSvg,
  renderTsLineChartSvg,
  renderTsLineChartTableHtml,
  renderTsMeshSvg,
  type TsDerivationResult,
} from "../../charts/ts_modeling_charts.ts";

export type TsVia = "sector" | "tpmt" | "femt";
export type TsPresetId = "pendulum_16" | "nonseparable_benchmark";

export const TS_VIAS: readonly TsVia[] = ["sector", "tpmt", "femt"];

export interface TsModelingExportModalPayload {
  title: string;
  filename: string;
  mimeType: string;
  content: string;
  offlineDesign?: boolean;
}

export interface TsModelingViewOptions {
  shell: ControlLabShell;
  client: ControlLabEngineClient;
  container: HTMLElement;
  onRequestRender?: () => void;
  onOpenExportModal?: (payload: TsModelingExportModalPayload, trigger: HTMLElement | null) => void;
  onRouteToLmi?: (refKey: string) => void;
}

interface TsPreset {
  id: TsPresetId;
  label: string;
  description: string;
  defaultVia: TsVia;
  stateBounds: Record<string, [number, number]>;
  premises: SectorPremiseSpec[];
  /** Matrizes em função de premissas z_i (Via 1). */
  sectorExpr: { A: string[][]; B: string[][]; C: string[][]; D: string[][] };
}

const PENDULUM_PREMISES: SectorPremiseSpec[] = [
  { name: "z1", expression: "1 / (1.0 + 0.2 * sin(x3)^2)" },
  { name: "z2", expression: "cos(x3)" },
  { name: "z3", expression: "sin(x3) / x3" },
  { name: "z4", expression: "x4 * sin(x3)" },
];

export const TS_PRESETS: Readonly<Record<TsPresetId, TsPreset>> = {
  pendulum_16: {
    id: "pendulum_16",
    label: "Pêndulo invertido sobre carro — 4 premissas / 16 regras",
    description:
      "4 estados, 4 premissas setoriais z1..z4 ⇒ 2⁴ = 16 regras exatas (Via 1). TPMT/FEMT amostram o mesmo modelo.",
    defaultVia: "sector",
    stateBounds: { x1: [-2, 2], x2: [-3, 3], x3: [-0.6, 0.6], x4: [-2, 2] },
    premises: PENDULUM_PREMISES,
    sectorExpr: {
      A: [
        ["0", "1", "0", "0"],
        ["0", "0", "-1.962 * z1 * z2 * z3", "0.1 * z1 * z4"],
        ["0", "0", "0", "1"],
        ["0", "0", "23.544 * z1 * z3", "-0.2 * z1 * z2 * z4"],
      ],
      B: [["0"], ["z1"], ["0"], ["-2.0 * z1 * z2"]],
      C: [["1", "0", "0", "0"], ["0", "0", "1", "0"]],
      D: [["0"], ["0"]],
    },
  },
  nonseparable_benchmark: {
    id: "nonseparable_benchmark",
    label: "Benchmark não separável 2D — FEMT vs TPMT",
    description:
      "Acoplamento sin(x1 + x2) e cos(x1 − x2) impede separação por eixo: a FEMT usa estritamente menos regras que a TPMT.",
    defaultVia: "femt",
    stateBounds: { x1: [-1.2, 1.2], x2: [-1.2, 1.2] },
    premises: [
      { name: "z1", expression: "sin(x1 + x2)" },
      { name: "z2", expression: "cos(x1 - x2)" },
    ],
    sectorExpr: {
      A: [["-1.0 - 0.5 * z1", "0.3 * z2"], ["0.2 * z1", "-2.0 + 0.4 * z2"]],
      B: [["1.0"], ["0.5 + 0.2 * z1"]],
      C: [["1", "0"]],
      D: [["0"]],
    },
  },
};

export function isTsPresetId(value: string): value is TsPresetId {
  return Object.hasOwn(TS_PRESETS, value);
}

/** Substitui premissas z_i por `(expressão)` — troca textual pura, sem avaliação. */
export function substitutePremises(expr: string, premises: readonly SectorPremiseSpec[]): string {
  let out = expr;
  for (const p of premises) {
    const re = new RegExp(`\\b${p.name.replace(/[^A-Za-z0-9_]/g, "")}\\b`, "g");
    out = out.replace(re, `(${String(p.expression)})`);
  }
  return out;
}

function sampledMatrix(m: string[][], premises: readonly SectorPremiseSpec[]): string[][] {
  return m.map((row) => row.map((e) => substitutePremises(e, premises)));
}

export interface TsDerivationRecipe {
  via: TsVia;
  preset: string | null;
  payload: Record<string, unknown>;
}

export interface TsFormParams {
  gridPoints: number;
  rank: number | null;
  hull: TsHull;
  decomposition: "hosvd" | "hooi";
  meshKind: "delaunay" | "kuhn_delaunay";
  valPoints: number;
}

export const DEFAULT_TS_FORM_PARAMS: TsFormParams = {
  gridPoints: 9,
  rank: null,
  hull: "CNO",
  decomposition: "hosvd",
  meshKind: "kuhn_delaunay",
  valPoints: 64,
};

export function buildTsPayload(
  presetId: TsPresetId,
  via: TsVia,
  params: TsFormParams,
): Record<string, unknown> {
  const p = TS_PRESETS[presetId];
  const base: Record<string, unknown> = {
    state_bounds: structuredClone(p.stateBounds),
    model_id: `ts-${presetId}-${via}`,
    n_val_points: params.valPoints,
  };
  if (via === "sector") {
    return {
      ...base,
      premises: structuredClone(p.premises),
      A_expr: p.sectorExpr.A,
      B_expr: p.sectorExpr.B,
      C_expr: p.sectorExpr.C,
      D_expr: p.sectorExpr.D,
    };
  }
  const sampled = {
    ...base,
    A_expr: sampledMatrix(p.sectorExpr.A, p.premises),
    B_expr: sampledMatrix(p.sectorExpr.B, p.premises),
    C_expr: p.sectorExpr.C,
    D_expr: p.sectorExpr.D,
    grid_points: params.gridPoints,
    hull_type: params.hull,
  };
  if (via === "tpmt") {
    return {
      ...sampled,
      decomposition: params.decomposition,
      ...(params.rank !== null ? { ranks: params.rank } : {}),
    };
  }
  return {
    ...sampled,
    mesh_kind: params.meshKind,
    ...(params.rank !== null ? { rank: params.rank } : {}),
  };
}

function viaFromMethod(method: unknown): TsVia | null {
  if (method === "sector_nonlinearity" || method === "sector") return "sector";
  if (method === "tpmt") return "tpmt";
  if (method === "femt") return "femt";
  return null;
}

/** Recupera a receita de derivação a partir de `provenance.ts_derivation` de um TSStateSpace. */
export function extractRecipeFromProvenance(dto: Record<string, unknown>): TsDerivationRecipe | null {
  const prov = dto.provenance;
  if (!isPlainObject(prov) || !isPlainObject(prov.ts_derivation)) return null;
  const derivation = prov.ts_derivation;
  const rec = derivation.recipe;
  if (isPlainObject(rec)) {
    const via = viaFromMethod(rec.via);
    if (via && isPlainObject(rec.payload)) {
      return {
        via,
        preset: typeof rec.preset === "string" ? rec.preset : null,
        payload: structuredClone(rec.payload),
      };
    }
  }
  const via = viaFromMethod(derivation.method);
  if (!via) return null;
  return { via, preset: null, payload: {} };
}

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

const VIA_LABELS: Record<TsVia, string> = {
  sector: "Via 1 — Setor não linear (exata, 2ᵖ regras)",
  tpmt: "Via 2 — TPMT (HOSVD/HOOI + envoltória convexa)",
  femt: "Via 3 — FEMT (SVD nodal + elementos P1 simpliciais)",
};

function chartSlot(id: string, label: string, tableId: string): string {
  return [
    `<div class="chart-card ts-chart-card">`,
    `<h5>${escapeHtml(label)}</h5>`,
    `<div id="${id}" class="chart-container" aria-live="polite"><p>Nenhum resultado ainda.</p></div>`,
    `<details><summary>Tabela acessível — ${escapeHtml(label)}</summary><div id="${tableId}"></div></details>`,
    `</div>`,
  ].join("");
}

export function renderTsModelingViewHtml(): string {
  const presetOptions = (Object.values(TS_PRESETS) as TsPreset[])
    .map((p) => `<option value="${p.id}">${escapeHtml(p.label)}</option>`)
    .join("");
  const viaOptions = TS_VIAS.map((v) => `<option value="${v}">${escapeHtml(VIA_LABELS[v])}</option>`).join("");
  return [
    `<section id="ts-modeling-workspace-panel" class="panel-card workspace-section" aria-label="Obtenção de Modelos TS (Setor, TPMT e FEMT)" hidden>`,
    `<h3>Obtenção de Modelos TS — Setor, TPMT &amp; FEMT</h3>`,
    `<div id="ts-scientific-banner" class="warning-callout" role="note"><strong>Modelo TS dinâmico:</strong> o resultado é um <code>TSStateSpace</code> com vértices (A<sub>i</sub>, B<sub>i</sub>) pronto para LMIs PDC (Aba 7). Resultados aproximados (TPMT/FEMT) exibem o certificado de fidelidade; a Via 1 é exata no setor.</div>`,
    `<ol id="ts-guided-steps" class="ts-guided-steps" aria-label="Fluxo guiado">`,
    `<li id="ts-step-1" data-step="preset">Escolha um preset didático.</li>`,
    `<li id="ts-step-2" data-step="via">Escolha a via de obtenção e ajuste os parâmetros.</li>`,
    `<li id="ts-step-3" data-step="derive">Derive e inspecione os gráficos.</li>`,
    `<li id="ts-step-4" data-step="register">Registre no Workspace e abra em LMIs.</li>`,
    `</ol>`,
    `<div class="ts-toolbar subcard panel-actions">`,
    `<label for="ts-preset-select">Preset didático</label>`,
    `<select id="ts-preset-select" class="touch-control" aria-label="Preset didático TS">${presetOptions}</select>`,
    `<label for="ts-via-select">Via de obtenção</label>`,
    `<select id="ts-via-select" class="touch-control" aria-label="Via de obtenção TS">${viaOptions}</select>`,
    `</div>`,
    `<p id="ts-preset-description" class="dock-item-summary"></p>`,
    `<div id="ts-params" class="ts-params subcard panel-actions">`,
    `<div class="tool-field" data-via-only="tpmt femt"><label for="ts-grid-points">Pontos por eixo</label><input type="number" id="ts-grid-points" class="touch-control id-param-input" min="3" max="41" step="1" value="9" aria-label="Pontos de grade por eixo" /></div>`,
    `<div class="tool-field" data-via-only="tpmt femt"><label for="ts-rank">Posto (vazio = automático)</label><input type="number" id="ts-rank" class="touch-control id-param-input" min="1" max="64" step="1" placeholder="auto" aria-label="Posto de truncamento" /></div>`,
    `<div class="tool-field" data-via-only="tpmt femt"><label for="ts-hull-select">Envoltória convexa</label><select id="ts-hull-select" class="touch-control" aria-label="Tipo de envoltória"><option value="CNO">CNO</option><option value="RNO-INO">RNO-INO</option><option value="SN-NN">SN-NN</option></select></div>`,
    `<div class="tool-field" data-via-only="tpmt"><label for="ts-decomp-select">Decomposição</label><select id="ts-decomp-select" class="touch-control" aria-label="Decomposição tensorial"><option value="hosvd">HOSVD</option><option value="hooi">HOOI</option></select></div>`,
    `<div class="tool-field" data-via-only="femt"><label for="ts-mesh-select">Malha</label><select id="ts-mesh-select" class="touch-control" aria-label="Tipo de malha FEMT"><option value="kuhn_delaunay">Kuhn-Delaunay</option><option value="delaunay">Delaunay</option></select></div>`,
    `<div class="tool-field"><label for="ts-val-points">Pontos de validação</label><input type="number" id="ts-val-points" class="touch-control id-param-input" min="1" max="2048" step="1" value="64" aria-label="Pontos de validação fora da grade" /></div>`,
    `</div>`,
    `<div class="panel-actions ts-actions">`,
    `<button type="button" id="btn-ts-analyze" class="touch-control btn-secondary" data-action="ts-analyze">Analisar Premissas</button>`,
    `<button type="button" id="btn-ts-derive" class="touch-control btn-primary" data-action="ts-derive">Derivar Modelo TS</button>`,
    `<button type="button" id="btn-ts-compare" class="touch-control btn-secondary" data-action="ts-compare">Comparar FEMT vs TPMT</button>`,
    `<button type="button" id="btn-ts-register" class="touch-control btn-secondary" data-action="ts-register" disabled aria-disabled="true">Registrar no Workspace</button>`,
    `<button type="button" id="btn-ts-register-open-lmi" class="touch-control btn-primary" data-action="ts-register-open-lmi" disabled aria-disabled="true">Registrar e Abrir em LMIs</button>`,
    `</div>`,
    `<div class="panel-actions ts-actions">`,
    `<label for="ts-recipe-select">Receita registrada</label>`,
    `<select id="ts-recipe-select" class="touch-control" aria-label="Receita de derivação registrada"></select>`,
    `<button type="button" id="btn-ts-reload-recipe" class="touch-control btn-secondary" data-action="ts-reload-recipe" disabled aria-disabled="true">Recarregar Receita</button>`,
    `<button type="button" id="btn-ts-export-python" class="touch-control btn-secondary" data-action="ts-export-python" disabled aria-disabled="true">Exportar Script Python</button>`,
    `<button type="button" id="btn-ts-export-matlab" class="touch-control btn-secondary" data-action="ts-export-matlab" disabled aria-disabled="true">Exportar Script MATLAB</button>`,
    `</div>`,
    `<div id="ts-status" class="ts-status" role="status" aria-live="polite"></div>`,
    `<div id="ts-summary" class="ts-summary subcard" aria-live="polite"><p>Selecione um preset e derive um modelo.</p></div>`,
    `<div id="ts-compare-slot" class="subcard" aria-live="polite"></div>`,
    `<div class="ts-charts-grid">`,
    chartSlot("ts-hr-chart-slot", "Funções de pertinência h_r (1D)", "ts-hr-table-slot"),
    chartSlot("ts-mesh-chart-slot", "Malha simplicial 2D (Delaunay)", "ts-mesh-table-slot"),
    chartSlot("ts-bases-chart-slot", "Bases U vs W", "ts-bases-table-slot"),
    chartSlot("ts-scree-chart-slot", "Scree plot dos valores singulares", "ts-scree-table-slot"),
    chartSlot("ts-error-heatmap-slot", "Erro fora da grade (mapa de calor)", "ts-error-table-slot"),
    `</div>`,
    `</section>`,
  ].join("\n");
}

function numOrNull(raw: string | undefined): number | null {
  if (raw === undefined || raw.trim() === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : Number.NaN;
}

export class TsModelingView {
  private readonly shell: ControlLabShell;
  private readonly client: ControlLabEngineClient;
  private readonly container: HTMLElement;
  private readonly onRequestRender?: () => void;
  private readonly onOpenExportModal?: TsModelingViewOptions["onOpenExportModal"];
  private readonly onRouteToLmi?: (refKey: string) => void;

  private readonly q = <T extends HTMLElement>(sel: string): T | null =>
    this.container.querySelector<T>(sel);

  private presetId: TsPresetId = "pendulum_16";
  private via: TsVia = "sector";
  private params: TsFormParams = { ...DEFAULT_TS_FORM_PARAMS };
  private payloadOverride: Record<string, unknown> | null = null;
  private result: TsDerivationResult | null = null;
  private resultVia: TsVia | null = null;
  private resultPayload: Record<string, unknown> | null = null;
  private registeredKey: string | null = null;
  private busy = false;
  private dirty = true;
  private statusText = "";
  private compareHtml = "";
  private chartsHtmlKey = "";

  constructor(options: TsModelingViewOptions) {
    this.shell = options.shell;
    this.client = options.client;
    this.container = options.container;
    this.onRequestRender = options.onRequestRender;
    this.onOpenExportModal = options.onOpenExportModal;
    this.onRouteToLmi = options.onRouteToLmi;
    this.bindEvents();
    if (supportsTsModeling(this.client)) {
      this.client.subscribeTsModelingProgress((event) => {
        this.setStatus(`Progresso: ${event.progress.stage} (${Math.round(event.progress.elapsed_ms)} ms)`);
      });
    }
  }

  public getState(): {
    presetId: TsPresetId;
    via: TsVia;
    hasResult: boolean;
    registeredKey: string | null;
  } {
    return {
      presetId: this.presetId,
      via: this.via,
      hasResult: this.result !== null,
      registeredKey: this.registeredKey,
    };
  }

  private bindEvents(): void {
    const on = (selector: string, event: string, handler: (ev: Event) => void): void => {
      this.q<HTMLElement>(selector)?.addEventListener(event, handler);
    };
    on("#ts-preset-select", "change", () => {
      const v = this.q<HTMLSelectElement>("#ts-preset-select")?.value ?? "";
      if (isTsPresetId(v)) this.selectPreset(v);
    });
    on("#ts-via-select", "change", () => {
      const v = this.q<HTMLSelectElement>("#ts-via-select")?.value ?? "";
      if ((TS_VIAS as readonly string[]).includes(v)) {
        this.via = v as TsVia;
        this.payloadOverride = null;
        this.dirty = true;
        this.onRequestRender?.();
      }
    });
    on('[data-action="ts-analyze"]', "click", () => void this.analyze());
    on('[data-action="ts-derive"]', "click", () => void this.derive());
    on('[data-action="ts-compare"]', "click", () => void this.compare());
    on('[data-action="ts-register"]', "click", () => void this.register(false));
    on('[data-action="ts-register-open-lmi"]', "click", () => void this.register(true));
    on('[data-action="ts-reload-recipe"]', "click", () => this.reloadRecipe());
    on('[data-action="ts-export-python"]', "click", (ev) =>
      void this.exportScript("python", ev.currentTarget as HTMLElement | null));
    on('[data-action="ts-export-matlab"]', "click", (ev) =>
      void this.exportScript("matlab", ev.currentTarget as HTMLElement | null));
  }

  public selectPreset(id: TsPresetId): void {
    this.presetId = id;
    this.via = TS_PRESETS[id].defaultVia;
    this.payloadOverride = null;
    this.dirty = true;
    this.onRequestRender?.();
    this.render();
  }

  public setVia(via: TsVia): void {
    this.via = via;
    this.payloadOverride = null;
    this.dirty = true;
    this.render();
  }

  public setStatus(text: string): void {
    this.statusText = text;
    const el = this.q<HTMLElement>("#ts-status");
    if (el) el.textContent = text;
  }

  private readParams(): TsFormParams {
    const grid = Number(this.q<HTMLInputElement>("#ts-grid-points")?.value ?? "9");
    const rank = numOrNull(this.q<HTMLInputElement>("#ts-rank")?.value);
    const val = Number(this.q<HTMLInputElement>("#ts-val-points")?.value ?? "64");
    if (!Number.isInteger(grid) || grid < 3 || grid > 41) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Pontos por eixo deve ser inteiro entre 3 e 41.");
    }
    if (rank !== null && (!Number.isInteger(rank) || rank < 1 || rank > 64)) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Posto deve ser inteiro entre 1 e 64 (ou vazio).");
    }
    if (!Number.isInteger(val) || val < 1 || val > 2048) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Pontos de validação deve ser inteiro entre 1 e 2048.");
    }
    const hull = this.q<HTMLSelectElement>("#ts-hull-select")?.value;
    const decomp = this.q<HTMLSelectElement>("#ts-decomp-select")?.value;
    const mesh = this.q<HTMLSelectElement>("#ts-mesh-select")?.value;
    return {
      gridPoints: grid,
      rank,
      hull: hull === "RNO-INO" || hull === "SN-NN" ? hull : "CNO",
      decomposition: decomp === "hooi" ? "hooi" : "hosvd",
      meshKind: mesh === "delaunay" ? "delaunay" : "kuhn_delaunay",
      valPoints: val,
    };
  }

  private requireClient(): TsModelingEngineClient {
    if (!supportsTsModeling(this.client)) {
      throw new ControlLabBridgeError(
        "SOLVER_UNAVAILABLE",
        "O motor atual não expõe a ponte de modelagem TS.",
      );
    }
    return this.client;
  }

  private context(): TsModelingContext {
    const lqr = this.shell.getLqrWorkspace();
    const projectId = lqr.getProjectId();
    return {
      request_id: `ts-modeling-${generateUuid()}`,
      project_id: projectId,
      project_revision: Math.max(lqr.getProjectRevision(), this.client.getCommittedRevision(projectId)),
    };
  }

  private unwrap<T extends Record<string, unknown>>(resp: TsRpcResponse<T>, fallback: string): T {
    if (resp.status === "failure" || !resp.result) {
      throw new ControlLabBridgeError(resp.error?.code ?? "INTERNAL_ERROR", resp.error?.message ?? fallback);
    }
    return resp.result;
  }

  private async withBusy(task: () => Promise<void>): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      await task();
    } catch (err: unknown) {
      this.setStatus("Falha na operação TS; veja o alerta de erro.");
      this.shell.presentError(err);
    } finally {
      this.busy = false;
      this.onRequestRender?.();
    }
  }

  private currentPayload(): Record<string, unknown> {
    if (this.payloadOverride) return structuredClone(this.payloadOverride);
    this.params = this.readParams();
    return buildTsPayload(this.presetId, this.via, this.params);
  }

  public async analyze(): Promise<void> {
    await this.withBusy(async () => {
      const client = this.requireClient();
      const payload = buildTsPayload(this.presetId, "sector", this.params);
      const res = this.unwrap(
        await client.analyzeSectorPremises(this.context(), {
          premises: payload.premises as SectorPremiseSpec[],
          state_bounds: payload.state_bounds as Record<string, [number, number]>,
        }),
        "Falha ao analisar premissas.",
      );
      const rows = res.premises
        .map((p) => `<tr><th scope="row">${escapeHtml(p.name)}</th><td><code>${escapeHtml(p.expression)}</code></td><td>${escapeHtml(formatNumericDisplay(p.min, 4))}</td><td>${escapeHtml(formatNumericDisplay(p.max, 4))}</td></tr>`)
        .join("");
      const summary = this.q<HTMLElement>("#ts-summary");
      if (summary) {
        summary.innerHTML = `<p><strong>${res.num_premises}</strong> premissas ⇒ <strong id="ts-analysis-rules">${res.num_rules}</strong> regras (2ᵖ); modo: ${escapeHtml(res.premise_availability.mode)}.</p><table class="accessible-data-table" aria-label="Premissas setoriais"><thead><tr><th scope="col">Premissa</th><th scope="col">Expressão</th><th scope="col">Mín</th><th scope="col">Máx</th></tr></thead><tbody>${rows}</tbody></table>`;
      }
      this.setStatus(`Análise concluída: ${res.num_rules} regras.`);
    });
  }

  private async runVia(client: TsModelingEngineClient, via: TsVia, payload: Record<string, unknown>): Promise<TsDerivationResult> {
    const ctx = this.context();
    if (via === "sector") {
      return this.unwrap<DerivedTsSectorResult>(
        await client.deriveTsSector(ctx, payload as unknown as Parameters<TsModelingEngineClient["deriveTsSector"]>[1]),
        "Falha na derivação setorial.",
      );
    }
    if (via === "tpmt") {
      return this.unwrap<DerivedTsTpmtResult>(
        await client.deriveTsTpmt(ctx, payload as unknown as Parameters<TsModelingEngineClient["deriveTsTpmt"]>[1]),
        "Falha na derivação TPMT.",
      );
    }
    return this.unwrap<DerivedTsFemtResult>(
      await client.deriveTsFemt(ctx, payload as unknown as Parameters<TsModelingEngineClient["deriveTsFemt"]>[1]),
      "Falha na derivação FEMT.",
    );
  }

  public async derive(): Promise<void> {
    await this.withBusy(async () => {
      const client = this.requireClient();
      const payload = this.currentPayload();
      const via = this.via;
      this.setStatus("Derivando modelo TS…");
      const res = await this.runVia(client, via, payload);
      this.result = res;
      this.resultVia = via;
      this.resultPayload = payload;
      this.registeredKey = null;
      this.dirty = true;
      this.setStatus(`Modelo derivado (${via}): ${res.num_rules} regras.`);
      this.shell.getAnnouncer().announce(`Modelo TS derivado pela via ${via} com ${res.num_rules} regras.`, "polite", "status");
    });
  }

  public async compare(): Promise<void> {
    await this.withBusy(async () => {
      const client = this.requireClient();
      this.params = this.readParams();
      const tpmt = await this.runVia(client, "tpmt", buildTsPayload(this.presetId, "tpmt", this.params));
      const femt = await this.runVia(client, "femt", buildTsPayload(this.presetId, "femt", this.params));
      const cert = (r: TsDerivationResult): string => {
        const v = r.fidelity_certificate.val_rel_l2_error;
        return typeof v === "number" ? formatNumericDisplay(v, 4) : "—";
      };
      const reduced = femt.num_rules < tpmt.num_rules;
      this.compareHtml = [
        `<h4>Comparação FEMT vs TPMT</h4>`,
        `<table id="ts-compare-table" class="accessible-data-table" aria-label="Comparação do número de regras FEMT versus TPMT"><thead><tr><th scope="col">Via</th><th scope="col">Regras N_r</th><th scope="col">Erro de validação</th></tr></thead><tbody>`,
        `<tr><th scope="row">TPMT</th><td id="ts-compare-tpmt-rules">${tpmt.num_rules}</td><td>${escapeHtml(cert(tpmt))}</td></tr>`,
        `<tr><th scope="row">FEMT</th><td id="ts-compare-femt-rules">${femt.num_rules}</td><td>${escapeHtml(cert(femt))}</td></tr>`,
        `</tbody></table>`,
        `<p id="ts-compare-verdict">${reduced ? `Redução de regras: N_r<sup>FEMT</sup> = ${femt.num_rules} &lt; N_r<sup>TPMT</sup> = ${tpmt.num_rules}.` : `Sem redução estrita neste preset (FEMT = ${femt.num_rules}, TPMT = ${tpmt.num_rules}); use o benchmark não separável para ver o ganho.`}</p>`,
      ].join("");
      this.result = femt;
      this.resultVia = "femt";
      this.resultPayload = buildTsPayload(this.presetId, "femt", this.params);
      this.registeredKey = null;
      this.dirty = true;
      this.setStatus(`Comparação concluída: FEMT ${femt.num_rules} × TPMT ${tpmt.num_rules} regras.`);
    });
  }

  public async register(openLmi: boolean): Promise<void> {
    await this.withBusy(async () => {
      if (!this.result || !this.resultVia) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", "Derive um modelo TS antes de registrar.");
      }
      const typed = this.shell.getTypedWorkspace();
      const dto = structuredClone(this.result.ts_state_space) as Record<string, unknown>;
      const existing = typed
        .listRegisteredObjects(["ts_measured", "ts_partially_observed"])
        .filter((o) => o.id === dto.id);
      const maxRev = existing.reduce((acc, o) => Math.max(acc, o.revision), -1);
      const revNow = typeof dto.revision === "number" ? dto.revision : 0;
      dto.revision = Math.max(revNow, maxRev + 1);
      const prov = isPlainObject(dto.provenance) ? { ...dto.provenance } : {};
      const derivation = isPlainObject(prov.ts_derivation) ? { ...prov.ts_derivation } : {};
      derivation.recipe = {
        via: this.resultVia,
        preset: this.presetId,
        payload: structuredClone(this.resultPayload ?? {}),
      };
      prov.ts_derivation = derivation;
      dto.provenance = prov;
      const reg = await typed.registerTypedObject(dto, { selectRole: "tsModel", source: "manual" });
      this.registeredKey = reg.key;
      this.setStatus(`Modelo '${reg.id}#r${reg.revision}' registrado no Workspace.`);
      this.shell.getAnnouncer().announce(`Modelo TS '${reg.id}#r${reg.revision}' registrado no Workspace.`, "polite", "status");
      if (openLmi) {
        this.onRouteToLmi?.(reg.key);
        this.shell.switchTab("optimization_lmi");
      }
    });
  }

  private recipeOptions(): Array<{ key: string; label: string }> {
    const typed = this.shell.getTypedWorkspace();
    return typed
      .listRegisteredObjects(["ts_measured", "ts_partially_observed"])
      .filter((o) => extractRecipeFromProvenance(o.value) !== null)
      .map((o) => ({ key: o.key, label: `${o.id}#r${o.revision}` }));
  }

  public reloadRecipe(refKey?: string): void {
    try {
      const sel = this.q<HTMLSelectElement>("#ts-recipe-select");
      const key = refKey ?? sel?.value ?? "";
      const typed = this.shell.getTypedWorkspace();
      const obj = typed.listRegisteredObjects(["ts_measured", "ts_partially_observed"]).find((o) => o.key === key);
      if (!obj) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", "Selecione um modelo TS registrado com receita.");
      }
      const recipe = extractRecipeFromProvenance(obj.value);
      if (!recipe) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", "O modelo não possui provenance.ts_derivation.");
      }
      this.via = recipe.via;
      if (recipe.preset && isTsPresetId(recipe.preset)) this.presetId = recipe.preset;
      const p = recipe.payload;
      this.payloadOverride = Object.keys(p).length > 0 ? structuredClone(p) : null;
      const set = (sel2: string, value: unknown): void => {
        const el = this.q<HTMLInputElement>(sel2);
        if (el && (typeof value === "number" || typeof value === "string")) el.value = String(value);
      };
      set("#ts-grid-points", p.grid_points);
      set("#ts-rank", p.rank ?? p.ranks);
      set("#ts-hull-select", p.hull_type);
      set("#ts-decomp-select", p.decomposition);
      set("#ts-mesh-select", p.mesh_kind);
      set("#ts-val-points", p.n_val_points);
      this.result = null;
      this.resultVia = null;
      this.dirty = true;
      this.setStatus(`Receita de '${obj.id}#r${obj.revision}' recarregada (${recipe.via}).`);
      this.onRequestRender?.();
      this.render();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async exportScript(language: TsDerivationLanguage, trigger: HTMLElement | null): Promise<void> {
    await this.withBusy(async () => {
      if (!this.result) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", "Derive um modelo TS antes de exportar scripts.");
      }
      const client = this.requireClient();
      const res = this.unwrap(
        await client.exportTsDerivationScript(this.context(), {
          language,
          model: structuredClone(this.result.ts_state_space) as Record<string, unknown>,
        }),
        "Falha ao exportar script de derivação.",
      );
      if (res.code_executed !== false || typeof res.script !== "string") {
        throw new ControlLabBridgeError("INTERNAL_ERROR", "Resposta inválida: script deve ser passivo (code_executed=false).");
      }
      this.onOpenExportModal?.(
        {
          title: `Script ${language === "python" ? "Python" : "MATLAB"} de derivação TS (execução manual explícita)`,
          filename: res.filename,
          mimeType: `${res.media_type};charset=utf-8`,
          content: res.script,
          offlineDesign: true,
        },
        trigger,
      );
      this.setStatus(`Script ${res.filename} exportado em modo passivo.`);
    });
  }

  private renderSummary(): void {
    const el = this.q<HTMLElement>("#ts-summary");
    if (!el || !this.result) return;
    const r = this.result;
    const cert = r.fidelity_certificate;
    const badge = typeof cert.verification_badge === "string" ? cert.verification_badge : "—";
    const val = typeof cert.val_rel_l2_error === "number" ? formatNumericDisplay(cert.val_rel_l2_error, 4) : "—";
    const grid = typeof cert.grid_rel_l2_error === "number" ? formatNumericDisplay(cert.grid_rel_l2_error, 4) : "—";
    el.innerHTML = [
      `<p>Via <strong>${escapeHtml(this.resultVia ?? "")}</strong> — modelo <code>${escapeHtml(r.model_id)}</code> (${escapeHtml(r.kind)}): `,
      `<strong id="ts-result-rules">${r.num_rules}</strong> regras.</p>`,
      `<p>Certificado: selo <code>${escapeHtml(badge)}</code>; erro na grade ${escapeHtml(grid)}; erro de validação fora da grade ${escapeHtml(val)}.</p>`,
      `<p>Disponibilidade das premissas: ${escapeHtml(r.ts_state_space.premise_availability.mode)}.</p>`,
    ].join("");
  }

  private renderCharts(themeMode: "standard_aa" | "high_contrast"): void {
    const key = `${themeMode}|${this.resultVia}|${this.result ? JSON.stringify([this.result.model_id, this.result.num_rules, this.result.fidelity_certificate]) : ""}`;
    if (key === this.chartsHtmlKey && !this.dirty) return;
    this.chartsHtmlKey = key;
    const setSlot = (slotId: string, tableId: string, svg: string | null, table: string, empty: string): void => {
      const slot = this.q<HTMLElement>(`#${slotId}`);
      const tab = this.q<HTMLElement>(`#${tableId}`);
      if (slot) slot.innerHTML = svg ?? `<p>${escapeHtml(empty)}</p>`;
      if (tab) tab.innerHTML = table;
    };
    const r = this.result;
    const h = r ? buildMembership1DChartModel(r) : null;
    setSlot("ts-hr-chart-slot", "ts-hr-table-slot", h ? renderTsLineChartSvg(h, { themeMode }) : null,
      h ? renderTsLineChartTableHtml(h) : "", r ? "Gráfico 1D indisponível para este resultado." : "Nenhum resultado ainda.");
    const m = r ? buildMesh2DModel(r) : null;
    setSlot("ts-mesh-chart-slot", "ts-mesh-table-slot", m ? renderTsMeshSvg(m, { themeMode }) : null,
      m ? `<p>${m.nodes.length} nós; ${m.triangles.length} simplexos (${escapeHtml(m.kind)}).</p>` : "",
      r ? "Malha 2D requer 2 variáveis de estado ativas (TPMT/FEMT)." : "Nenhum resultado ainda.");
    const b = r ? buildBasesChartModel(r) : null;
    setSlot("ts-bases-chart-slot", "ts-bases-table-slot", b ? renderTsLineChartSvg(b, { themeMode }) : null,
      b ? renderTsLineChartTableHtml(b) : "", r ? "Bases U vs W disponíveis nas vias TPMT e FEMT." : "Nenhum resultado ainda.");
    const s = r ? buildScreeChartModel(r) : null;
    setSlot("ts-scree-chart-slot", "ts-scree-table-slot", s ? renderTsLineChartSvg(s, { themeMode }) : null,
      s ? renderTsLineChartTableHtml(s) : "", r ? "Valores singulares disponíveis nas vias TPMT e FEMT." : "Nenhum resultado ainda.");
    const e = r ? buildOffGridErrorHeatmap(r) : null;
    setSlot("ts-error-heatmap-slot", "ts-error-table-slot", e ? renderTsHeatmapSvg(e, { themeMode }) : null,
      e ? `<p>Erro máximo fora da grade (defeito de partição da unidade): ${escapeHtml(formatNumericDisplay(e.maxError, 6))}.</p>` : "",
      r ? "Mapa de erro requer exatamente 2 eixos (TPMT/FEMT)." : "Nenhum resultado ainda.");
  }

  private setDisabled(selector: string, disabled: boolean): void {
    const el = this.q<HTMLButtonElement>(selector);
    if (!el) return;
    el.disabled = disabled;
    if (disabled) el.setAttribute("aria-disabled", "true");
    else el.removeAttribute("aria-disabled");
  }

  public render(): void {
    const panel = this.q<HTMLElement>("#ts-modeling-workspace-panel");
    const active = this.shell.getActiveTab() === "ts_modeling";
    setElHidden(panel, !active);
    if (!active) return;

    const presetSel = this.q<HTMLSelectElement>("#ts-preset-select");
    if (presetSel && presetSel.value !== this.presetId) presetSel.value = this.presetId;
    const viaSel = this.q<HTMLSelectElement>("#ts-via-select");
    if (viaSel && viaSel.value !== this.via) viaSel.value = this.via;
    const desc = this.q<HTMLElement>("#ts-preset-description");
    if (desc) desc.textContent = TS_PRESETS[this.presetId].description;

    for (const field of Array.from(this.container.querySelectorAll<HTMLElement>("[data-via-only]"))) {
      const only = (field.getAttribute("data-via-only") ?? "").split(" ");
      setElHidden(field, !only.includes(this.via));
    }

    const hasResult = this.result !== null;
    this.setDisabled("#btn-ts-register", !hasResult || this.busy);
    this.setDisabled("#btn-ts-register-open-lmi", !hasResult || this.busy);
    this.setDisabled("#btn-ts-export-python", !hasResult || this.busy);
    this.setDisabled("#btn-ts-export-matlab", !hasResult || this.busy);
    this.setDisabled("#btn-ts-derive", this.busy);
    this.setDisabled("#btn-ts-compare", this.busy);
    this.setDisabled("#btn-ts-analyze", this.busy);

    const recipes = this.recipeOptions();
    const recipeSel = this.q<HTMLSelectElement>("#ts-recipe-select");
    if (recipeSel) {
      const optionsHtml = recipes.length === 0
        ? `<option value="">— nenhuma receita registrada —</option>`
        : recipes.map((o) => `<option value="${escapeHtml(o.key)}">${escapeHtml(o.label)}</option>`).join("");
      if (recipeSel.innerHTML !== optionsHtml) recipeSel.innerHTML = optionsHtml;
    }
    this.setDisabled("#btn-ts-reload-recipe", recipes.length === 0);

    const stepStates: Array<[string, boolean]> = [
      ["#ts-step-1", true],
      ["#ts-step-2", true],
      ["#ts-step-3", hasResult],
      ["#ts-step-4", this.registeredKey !== null],
    ];
    for (const [sel, done] of stepStates) {
      this.q<HTMLElement>(sel)?.setAttribute("data-step-state", done ? "done" : "pending");
    }

    const statusEl = this.q<HTMLElement>("#ts-status");
    if (statusEl && statusEl.textContent !== this.statusText) statusEl.textContent = this.statusText;
    const compareEl = this.q<HTMLElement>("#ts-compare-slot");
    if (compareEl && compareEl.innerHTML !== this.compareHtml) compareEl.innerHTML = this.compareHtml;

    if (this.dirty && hasResult) this.renderSummary();
    this.renderCharts(this.shell.getThemeMode());
    this.dirty = false;
  }
}
