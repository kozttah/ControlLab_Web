/**
 * Bancada da Aba 5 — Controle Fuzzy, Takagi-Sugeno e FML (IEEE 1855-2016)
 * seguindo CL-UX-DIR-001 v1.0.0 Seção 4.5 (`WP-UX-REFACTOR-03-MIMO-FUZZY-LMI`)
 * e inspirada em `docs/references/legacy_fuzzy_lab/`.
 *
 * Responsabilidades estritas de UI/Apresentação (F8):
 * - Sistema Fuzzy canônico inicial pré-populado (2 entradas, 3 funções de pertinência
 *   por entrada, matriz completa 3×3 de regras) pronto para registro no Workspace.
 * - Editor visual de funções de pertinência (`#fuzzy-mf-svg`) sincronizado com
 *   parâmetros numéricos `(a, b, c, d)` / `(c, σ)`.
 * - Editor matricial 2D de regras (`#fuzzy-rules-matrix`) + cobertura.
 * - Interoperabilidade IEEE 1855-2016 FML (`fuzzy.import_fml`, `fuzzy.export_fml`)
 *   e banner científico explícito distinguindo aproximador estático de `TSStateSpace`.
 * - Superfície de controle (`fuzzy.evaluate_surface`) com barra `[SVG]`/`[PNG]` +
 *   tabela acessível WCAG 2.2 AA (`#fuzzy-surface-table-slot`) e avaliador pontual (`fuzzy.evaluate`).
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
  type RpcResponse,
} from "../../bridge/protocol.ts";
import {
  escapeHtml,
  formatNumericDisplay,
  getThemeTokens,
} from "../../app/accessibility.ts";
import type { ControlLabShell } from "../../app/shell.ts";
import {
  buildAccessibleChartTable,
  buildFuzzySurfaceChartModel,
  renderAccessibleTableHtml,
  renderFuzzySurfaceSvg,
  type FuzzySurfaceChartModel,
} from "../../charts/scientific_chart.ts";

export interface FuzzyExportModalPayload {
  title: string;
  filename: string;
  mimeType: string;
  content: string;
  offlineDesign?: boolean;
}

export interface FuzzyViewOptions {
  shell: ControlLabShell;
  client: ControlLabEngineClient;
  container: HTMLElement;
  onRequestRender?: () => void;
  onOpenExportModal?: (payload: FuzzyExportModalPayload, trigger: HTMLElement | null) => void;
}

export interface FuzzyTermSpec {
  name: string;
  mf?: string;
  type?: string;
  params: number[];
  coefficients?: number[];
}

export interface FuzzyVariableSpec {
  name: string;
  universe: [number, number];
  terms: FuzzyTermSpec[];
}

export interface FuzzyRuleSpec {
  name: string;
  connector: "and" | "or";
  antecedents: Record<string, string>;
  consequents: Record<string, string>;
  weight: number;
}

export interface CanonicalFuzzySystemDraft {
  schema_version: "1.0.0";
  id: string;
  revision: number;
  kind: "FuzzySystem";
  inference_type: "mamdani" | "ts";
  fml_profile: string;
  is_dynamic_model: false;
  input_variables: FuzzyVariableSpec[];
  output_variables: FuzzyVariableSpec[];
  rules: FuzzyRuleSpec[];
  operators: Record<string, string>;
  provenance: Record<string, unknown>;
}

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function renderFuzzyExportBarHtml(slotId: string, label: string): string {
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

export function buildStarterFuzzySystemDto(
  inferenceType: "mamdani" | "ts" = "mamdani",
): CanonicalFuzzySystemDraft {
  const inputVariables: FuzzyVariableSpec[] = [
    {
      name: "erro",
      universe: [-10, 10],
      terms: [
        { name: "N", mf: "triangular", params: [-10, -10, 0] },
        { name: "Z", mf: "triangular", params: [-5, 0, 5] },
        { name: "P", mf: "triangular", params: [0, 10, 10] },
      ],
    },
    {
      name: "derivada",
      universe: [-5, 5],
      terms: [
        { name: "N", mf: "triangular", params: [-5, -5, 0] },
        { name: "Z", mf: "triangular", params: [-2.5, 0, 2.5] },
        { name: "P", mf: "triangular", params: [0, 5, 5] },
      ],
    },
  ];

  const outputVariables: FuzzyVariableSpec[] =
    inferenceType === "mamdani"
      ? [
          {
            name: "controle",
            universe: [-10, 10],
            terms: [
              { name: "NB", mf: "triangular", params: [-10, -10, -5] },
              { name: "NM", mf: "triangular", params: [-10, -5, 0] },
              { name: "Z", mf: "triangular", params: [-5, 0, 5] },
              { name: "PM", mf: "triangular", params: [0, 5, 10] },
              { name: "PB", mf: "triangular", params: [5, 10, 10] },
            ],
          },
        ]
      : [
          {
            name: "controle",
            universe: [-10, 10],
            terms: [
              { name: "NB", type: "constant", params: [-9], coefficients: [-9] },
              { name: "NM", type: "constant", params: [-4.5], coefficients: [-4.5] },
              { name: "Z", type: "linear", params: [0.6, 0.4, 0], coefficients: [0.6, 0.4, 0] },
              { name: "PM", type: "constant", params: [4.5], coefficients: [4.5] },
              { name: "PB", type: "constant", params: [9], coefficients: [9] },
            ],
          },
        ];

  const ruleMap: Array<[string, string, string]> = [
    ["N", "N", "NB"],
    ["N", "Z", "NM"],
    ["N", "P", "Z"],
    ["Z", "N", "NM"],
    ["Z", "Z", "Z"],
    ["Z", "P", "PM"],
    ["P", "N", "Z"],
    ["P", "Z", "PM"],
    ["P", "P", "PB"],
  ];

  const rules: FuzzyRuleSpec[] = ruleMap.map(([eTerm, dTerm, outTerm], idx) => ({
    name: `R${idx + 1}`,
    connector: "and",
    antecedents: { erro: eTerm, derivada: dTerm },
    consequents: { controle: outTerm },
    weight: 1.0,
  }));

  return {
    schema_version: "1.0.0",
    id: "fuzzy-pd-starter",
    revision: 1,
    kind: "FuzzySystem",
    inference_type: inferenceType,
    fml_profile: "IEEE-1855-2016",
    is_dynamic_model: false,
    input_variables: inputVariables,
    output_variables: outputVariables,
    rules,
    operators:
      inferenceType === "mamdani"
        ? {
            and: "min",
            or: "max",
            implication: "min",
            aggregation: "max",
            defuzzification: "centroid",
          }
        : {
            and: "prod",
            or: "probor",
            defuzzification: "wtaver",
          },
    provenance: {
      source: "fuzzy_workbench_starter",
      description: "Controlador PD Fuzzy 2 entradas canônico",
    },
  };
}

function evalVisualMembership(mfType: string, params: readonly number[], x: number): number {
  const kind = mfType.toLowerCase();
  if (kind === "triangular" || kind === "tri" || kind === "trimf") {
    const [a = 0, b = 0, c = 0] = params;
    if (x < a || x > c) return 0;
    if (Math.abs(x - b) <= 1e-12) return 1;
    if (x < b) return Math.abs(b - a) <= 1e-12 ? 1 : Math.max(0, Math.min(1, (x - a) / (b - a)));
    return Math.abs(c - b) <= 1e-12 ? 1 : Math.max(0, Math.min(1, (c - x) / (c - b)));
  }
  if (kind === "trapezoidal" || kind === "trap" || kind === "trapmf") {
    const [a = 0, b = 0, c = 0, d = 0] = params;
    if (x < a || x > d) return 0;
    if (x >= b && x <= c) return 1;
    if (x < b) return Math.abs(b - a) <= 1e-12 ? 1 : Math.max(0, Math.min(1, (x - a) / (b - a)));
    return Math.abs(d - c) <= 1e-12 ? 1 : Math.max(0, Math.min(1, (d - x) / (d - c)));
  }
  if (kind === "gaussian" || kind === "gauss" || kind === "gaussmf") {
    const [c = 0, sigma = 1] = params;
    const s = Math.max(1e-6, Math.abs(sigma));
    const q = (x - c) / s;
    return Math.exp(-0.5 * q * q);
  }
  if (kind === "singleton") {
    const [c = 0] = params;
    return Math.abs(x - c) <= 1e-6 ? 1 : 0;
  }
  return 0;
}

export function renderFuzzyViewHtml(): string {
  return [
    `<section id="fuzzy-workspace-panel" class="panel-card workspace-section" aria-label="Controle Fuzzy e Takagi-Sugeno" hidden>`,
    `<h3>Controle Fuzzy, Takagi-Sugeno e FML (IEEE 1855-2016)</h3>`,
    `<div id="fuzzy-scientific-banner" class="warning-callout" role="note">`,
    `<strong>Aproximador Estático Fuzzy vs. Modelo Dinâmico TS:</strong> Um objeto <code>FuzzySystem</code> (Mamdani ou TS) mapeia entradas instantâneas em saídas de controle e <strong>não</strong> equivale a um <code>TSStateSpace</code> dinâmico com vértices (A_i, B_i) para síntese LMI/PDC.`,
    `</div>`,
    `<div class="fuzzy-toolbar subcard panel-actions">`,
    `<label for="fuzzy-inference-type">Tipo de Inferência</label>`,
    `<select id="fuzzy-inference-type" class="touch-control" aria-label="Tipo de inferência Fuzzy">`,
    `<option value="mamdani">Mamdani (Defuzzificação Centroide)</option>`,
    `<option value="ts">Takagi-Sugeno (TS 0ª/1ª ordem)</option>`,
    `</select>`,
    `<button type="button" id="btn-fuzzy-register" class="touch-control btn-secondary" data-action="fuzzy-register">Sincronizar no Workspace</button>`,
    `<button type="button" id="btn-fuzzy-export-fml" class="touch-control btn-secondary" data-action="fuzzy-export-fml">Exportar FML (IEEE 1855-2016)</button>`,
    `<button type="button" id="btn-fuzzy-import-fml" class="touch-control btn-secondary" data-action="fuzzy-import-fml">Importar FML (XML)</button>`,
    `</div>`,
    `<div class="fuzzy-main-grid">`,
    `<div class="subcard fuzzy-mf-panel">`,
    `<h4>Funções de Pertinência &amp; Parâmetros Numéricos</h4>`,
    `<div class="panel-actions">`,
    `<label for="fuzzy-var-select">Variável</label>`,
    `<select id="fuzzy-var-select" class="touch-control" aria-label="Variável fuzzy selecionada"></select>`,
    `<span id="fuzzy-var-universe" class="dock-item-summary"></span>`,
    `<button type="button" id="btn-fuzzy-add-term" class="touch-control btn-secondary btn-small" data-action="fuzzy-add-term">+ Novo Termo</button>`,
    `</div>`,
    `<div id="fuzzy-mf-svg" class="fuzzy-mf-svg-slot chart-container" aria-label="Gráfico das funções de pertinência"></div>`,
    `<div id="fuzzy-mf-params-list" class="fuzzy-mf-params-list"></div>`,
    `</div>`,
    `<div class="chart-card fuzzy-surface-panel">`,
    `<h4>Superfície de Controle &amp; Avaliação Pontual</h4>`,
    `<div class="panel-actions">`,
    `<label for="fuzzy-surface-n-points">Resolução da Grade</label>`,
    `<input type="number" id="fuzzy-surface-n-points" class="touch-control id-param-input" min="5" max="60" step="5" value="15" aria-label="Resolução da superfície fuzzy" />`,
    `<button type="button" id="btn-fuzzy-eval-surface" class="touch-control btn-primary" data-action="fuzzy-eval-surface">Calcular Superfície Fuzzy</button>`,
    `</div>`,
    `<div id="fuzzy-surface-chart-slot" class="chart-container"></div>`,
    renderFuzzyExportBarHtml("fuzzy-surface-chart-slot", "Superfície de Controle Fuzzy"),
    `<div class="fuzzy-point-eval subcard">`,
    `<div class="panel-actions" id="fuzzy-point-inputs-row">`,
    `<label for="fuzzy-point-x0">Entrada 1</label>`,
    `<input type="number" id="fuzzy-point-x0" class="touch-control id-param-input" step="0.5" value="2.5" aria-label="Valor de entrada 1" />`,
    `<label for="fuzzy-point-x1">Entrada 2</label>`,
    `<input type="number" id="fuzzy-point-x1" class="touch-control id-param-input" step="0.5" value="-1.0" aria-label="Valor de entrada 2" />`,
    `<button type="button" id="btn-fuzzy-eval-point" class="touch-control btn-secondary" data-action="fuzzy-eval-point">Avaliar Ponto</button>`,
    `</div>`,
    `<div id="fuzzy-point-result" aria-live="polite"><p>Informe os valores e clique em <strong>Avaliar Ponto</strong>.</p></div>`,
    `</div>`,
    `<details><summary>Tabela acessível da superfície de controle fuzzy (WCAG 2.2 AA)</summary><div id="fuzzy-surface-table-slot"><p>Nenhuma superfície calculada ainda.</p></div></details>`,
    `</div>`,
    `</div>`,
    `<div class="subcard fuzzy-rules-panel">`,
    `<div class="fuzzy-rules-head panel-actions">`,
    `<h4>Matriz de Regras Fuzzy</h4>`,
    `<span id="fuzzy-coverage-status" class="badge badge-stable"></span>`,
    `<button type="button" id="btn-fuzzy-add-rule" class="touch-control btn-secondary btn-small" data-action="fuzzy-add-rule">+ Regra</button>`,
    `</div>`,
    `<div id="fuzzy-rules-matrix" class="fuzzy-rules-matrix-wrap"></div>`,
    `</div>`,
    `<details class="subcard fuzzy-fml-details">`,
    `<summary>Editor / Intercâmbio FML XML (IEEE 1855-2016)</summary>`,
    `<div class="tool-field">`,
    `<label for="fuzzy-fml-xml">Conteúdo XML FML (importação passiva anti-XXE)</label>`,
    `<textarea id="fuzzy-fml-xml" class="touch-control" rows="5" aria-label="Conteúdo XML FML"></textarea>`,
    `<div class="panel-actions">`,
    `<input type="file" id="fuzzy-fml-file-input" accept=".fml,.xml" class="touch-control" aria-label="Carregar arquivo FML XML" />`,
    `</div>`,
    `</div>`,
    `</details>`,
    `</section>`,
  ].join("\n");
}

export class FuzzyView {
  private readonly shell: ControlLabShell;
  private readonly client: ControlLabEngineClient;
  private readonly container: HTMLElement;
  private readonly onRequestRender?: () => void;
  private readonly onOpenExportModal?: (
    payload: FuzzyExportModalPayload,
    trigger: HTMLElement | null,
  ) => void;

  private readonly panelEl: HTMLElement | null;
  private readonly inferenceSelectEl: HTMLSelectElement | null;
  private readonly varSelectEl: HTMLSelectElement | null;
  private readonly varUniverseEl: HTMLElement | null;
  private readonly mfSvgEl: HTMLElement | null;
  private readonly mfParamsListEl: HTMLElement | null;
  private readonly rulesMatrixEl: HTMLElement | null;
  private readonly coverageStatusEl: HTMLElement | null;
  private readonly surfaceNPointsEl: HTMLInputElement | null;
  private readonly surfaceChartSlotEl: HTMLElement | null;
  private readonly surfaceTableSlotEl: HTMLElement | null;
  private readonly pointX0El: HTMLInputElement | null;
  private readonly pointX1El: HTMLInputElement | null;
  private readonly pointResultEl: HTMLElement | null;
  private readonly fmlXmlEl: HTMLTextAreaElement | null;
  private readonly fmlFileInputEl: HTMLInputElement | null;

  private draft: CanonicalFuzzySystemDraft;
  private selectedVarName = "erro";
  private surfaceModel: FuzzySurfaceChartModel | null = null;
  private mfParamError: string | null = null;

  constructor(options: FuzzyViewOptions) {
    this.shell = options.shell;
    this.client = options.client;
    this.container = options.container;
    this.onRequestRender = options.onRequestRender;
    this.onOpenExportModal = options.onOpenExportModal;

    this.draft = buildStarterFuzzySystemDto("mamdani");

    this.panelEl = this.container.querySelector<HTMLElement>("#fuzzy-workspace-panel");
    this.inferenceSelectEl = this.container.querySelector<HTMLSelectElement>("#fuzzy-inference-type");
    this.varSelectEl = this.container.querySelector<HTMLSelectElement>("#fuzzy-var-select");
    this.varUniverseEl = this.container.querySelector<HTMLElement>("#fuzzy-var-universe");
    this.mfSvgEl = this.container.querySelector<HTMLElement>("#fuzzy-mf-svg");
    this.mfParamsListEl = this.container.querySelector<HTMLElement>("#fuzzy-mf-params-list");
    this.rulesMatrixEl = this.container.querySelector<HTMLElement>("#fuzzy-rules-matrix");
    this.coverageStatusEl = this.container.querySelector<HTMLElement>("#fuzzy-coverage-status");
    this.surfaceNPointsEl = this.container.querySelector<HTMLInputElement>("#fuzzy-surface-n-points");
    this.surfaceChartSlotEl = this.container.querySelector<HTMLElement>("#fuzzy-surface-chart-slot");
    this.surfaceTableSlotEl = this.container.querySelector<HTMLElement>("#fuzzy-surface-table-slot");
    this.pointX0El = this.container.querySelector<HTMLInputElement>("#fuzzy-point-x0");
    this.pointX1El = this.container.querySelector<HTMLInputElement>("#fuzzy-point-x1");
    this.pointResultEl = this.container.querySelector<HTMLElement>("#fuzzy-point-result");
    this.fmlXmlEl = this.container.querySelector<HTMLTextAreaElement>("#fuzzy-fml-xml");
    this.fmlFileInputEl = this.container.querySelector<HTMLInputElement>("#fuzzy-fml-file-input");

    this.bindEvents();
  }

  private bindEvents(): void {
    this.inferenceSelectEl?.addEventListener("change", () => {
      const nextType = this.inferenceSelectEl?.value === "ts" ? "ts" : "mamdani";
      this.switchInferenceType(nextType);
    });

    this.varSelectEl?.addEventListener("change", () => {
      this.selectedVarName = this.varSelectEl?.value ?? this.draft.input_variables[0].name;
      this.renderMfSection();
    });

    this.container
      .querySelector<HTMLElement>('[data-action="fuzzy-register"]')
      ?.addEventListener("click", () => {
        void this.registerInWorkspace();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="fuzzy-add-term"]')
      ?.addEventListener("click", () => {
        this.addTermToSelectedVar();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="fuzzy-add-rule"]')
      ?.addEventListener("click", () => {
        this.addRuleFallback();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="fuzzy-eval-surface"]')
      ?.addEventListener("click", () => {
        void this.evaluateSurface();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="fuzzy-eval-point"]')
      ?.addEventListener("click", () => {
        void this.evaluatePoint();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="fuzzy-export-fml"]')
      ?.addEventListener("click", (ev) => {
        void this.exportFml(ev.currentTarget as HTMLElement | null);
      });

    this.container
      .querySelector<HTMLElement>('[data-action="fuzzy-import-fml"]')
      ?.addEventListener("click", () => {
        void this.importFml();
      });

    this.fmlFileInputEl?.addEventListener("change", () => {
      const files = (this.fmlFileInputEl as unknown as { files?: FileList })?.files;
      const file = files?.[0];
      if (!file || typeof file.text !== "function") return;
      void file
        .text()
        .then((txt) => {
          if (this.fmlXmlEl) this.fmlXmlEl.value = txt;
          return this.importFml();
        })
        .catch((err: unknown) => this.shell.presentError(err));
    });

    const handleParamEdit = (ev: Event): void => {
      const target = ev.target as HTMLElement | null;
      if (!target) return;
      const termIdxAttr = target.getAttribute("data-fuzzy-term-idx");
      const paramIdxAttr = target.getAttribute("data-fuzzy-param-idx");
      const mfTypeAttr = target.getAttribute("data-fuzzy-mf-select");
      if (termIdxAttr === null) return;
      const termIdx = Number(termIdxAttr);
      const selectedVar = this.findSelectedVariable();
      if (!selectedVar || !selectedVar.terms[termIdx]) return;

      if (mfTypeAttr === "true") {
        const nextMf = (target as HTMLSelectElement).value;
        const term = selectedVar.terms[termIdx];
        const [lo, hi] = selectedVar.universe;
        const mid = 0.5 * (lo + hi);
        if (selectedVar.role === "output" && this.draft.inference_type === "ts") {
          term.type = nextMf === "linear" ? "linear" : "constant";
          delete term.mf;
          term.params = nextMf === "linear" ? [0.5, 0.2, 0] : [0];
          term.coefficients = [...term.params];
        } else {
          term.mf = nextMf;
          delete term.type;
          if (nextMf === "gaussian") {
            term.params = [mid, Math.max(0.5, (hi - lo) * 0.15)];
          } else if (nextMf === "trapezoidal") {
            const q = (hi - lo) * 0.2;
            term.params = [mid - 1.5 * q, mid - 0.5 * q, mid + 0.5 * q, mid + 1.5 * q];
          } else {
            const q = (hi - lo) * 0.25;
            term.params = [mid - q, mid, mid + q];
          }
        }
        this.mfParamError = null;
        this.renderMfSection();
        return;
      }

      if (paramIdxAttr !== null) {
        const paramIdx = Number(paramIdxAttr);
        const val = Number((target as HTMLInputElement).value);
        if (!Number.isFinite(val)) {
          this.mfParamError = "Parâmetro deve ser um número finito.";
          return;
        }
        const term = selectedVar.terms[termIdx];
        const nextParams = [...term.params];
        nextParams[paramIdx] = val;
        const mfKind = (term.mf ?? term.type ?? "triangular").toLowerCase();
        if ((mfKind === "triangular" || mfKind === "trapezoidal") && nextParams.some((v, idx) => idx > 0 && v < nextParams[idx - 1])) {
          this.mfParamError = `Ordem inválida em '${term.name}': parâmetros devem satisfazer a ≤ b ≤ c${mfKind === "trapezoidal" ? " ≤ d" : ""}.`;
          // Still update UI value only on valid or allow user to finish typing next parameter
          term.params = nextParams;
          this.renderMfSvgOnly();
          return;
        }
        if (mfKind === "gaussian" && paramIdx === 1 && val <= 0) {
          this.mfParamError = `Parâmetro σ da gaussiana '${term.name}' deve ser > 0.`;
          return;
        }
        this.mfParamError = null;
        term.params = nextParams;
        if (term.coefficients) {
          term.coefficients = [...nextParams];
        }
        this.renderMfSvgOnly();
      }
    };

    this.mfParamsListEl?.addEventListener("change", handleParamEdit);

    this.rulesMatrixEl?.addEventListener("change", (ev: Event) => {
      const target = ev.target as HTMLSelectElement | null;
      if (!target) return;
      const t0 = target.getAttribute("data-rule-t0");
      const t1 = target.getAttribute("data-rule-t1");
      if (!t0 || !t1) return;
      const in0 = this.draft.input_variables[0]?.name;
      const in1 = this.draft.input_variables[1]?.name;
      const outName = this.draft.output_variables[0]?.name;
      if (!in0 || !in1 || !outName) return;

      const chosen = target.value;
      const idx = this.draft.rules.findIndex(
        (r) => r.antecedents[in0] === t0 && r.antecedents[in1] === t1,
      );
      if (chosen === "") {
        if (idx >= 0) this.draft.rules.splice(idx, 1);
      } else if (idx >= 0) {
        this.draft.rules[idx].consequents[outName] = chosen;
      } else {
        this.draft.rules.push({
          name: `R${this.draft.rules.length + 1}`,
          connector: "and",
          antecedents: { [in0]: t0, [in1]: t1 },
          consequents: { [outName]: chosen },
          weight: 1.0,
        });
      }
      this.renderRulesSection();
    });
  }

  public getSystemDraft(): CanonicalFuzzySystemDraft {
    return structuredClone(this.draft);
  }

  private findSelectedVariable():
    | (FuzzyVariableSpec & { role: "input" | "output" })
    | null {
    for (const v of this.draft.input_variables) {
      if (v.name === this.selectedVarName) return Object.assign(v, { role: "input" as const });
    }
    for (const v of this.draft.output_variables) {
      if (v.name === this.selectedVarName) return Object.assign(v, { role: "output" as const });
    }
    const first = this.draft.input_variables[0];
    return first ? Object.assign(first, { role: "input" as const }) : null;
  }

  private switchInferenceType(nextType: "mamdani" | "ts"): void {
    if (this.draft.inference_type === nextType) return;
    this.draft.inference_type = nextType;
    if (nextType === "ts") {
      this.draft.operators = { and: "prod", or: "probor", defuzzification: "wtaver" };
      for (const outVar of this.draft.output_variables) {
        const [lo, hi] = outVar.universe;
        const nTerms = Math.max(1, outVar.terms.length);
        outVar.terms = outVar.terms.map((t, i) => {
          const val = nTerms === 1 ? 0 : lo + (i / (nTerms - 1)) * (hi - lo);
          return { name: t.name, type: "constant", params: [Number(val.toFixed(3))], coefficients: [Number(val.toFixed(3))] };
        });
      }
    } else {
      this.draft.operators = {
        and: "min",
        or: "max",
        implication: "min",
        aggregation: "max",
        defuzzification: "centroid",
      };
      for (const outVar of this.draft.output_variables) {
        const [lo, hi] = outVar.universe;
        const nTerms = Math.max(2, outVar.terms.length);
        const step = (hi - lo) / (nTerms - 1);
        outVar.terms = outVar.terms.map((t, i) => {
          const center = lo + i * step;
          return {
            name: t.name,
            mf: "triangular",
            params: [Math.max(lo, center - step), center, Math.min(hi, center + step)],
          };
        });
      }
    }
    this.render();
  }

  private addTermToSelectedVar(): void {
    const selectedVar = this.findSelectedVariable();
    if (!selectedVar) return;
    const idx = selectedVar.terms.length + 1;
    const [lo, hi] = selectedVar.universe;
    const mid = 0.5 * (lo + hi);
    const span = (hi - lo) * 0.2;
    const name = `T${idx}`;
    if (selectedVar.role === "output" && this.draft.inference_type === "ts") {
      selectedVar.terms.push({ name, type: "constant", params: [mid], coefficients: [mid] });
    } else {
      selectedVar.terms.push({
        name,
        mf: "triangular",
        params: [mid - span, mid, mid + span],
      });
    }
    this.renderMfSection();
    this.renderRulesSection();
  }

  private addRuleFallback(): void {
    const outVar = this.draft.output_variables[0];
    if (!outVar || outVar.terms.length === 0) return;
    const antecedents: Record<string, string> = {};
    for (const iv of this.draft.input_variables) {
      if (iv.terms[0]) antecedents[iv.name] = iv.terms[0].name;
    }
    this.draft.rules.push({
      name: `R${this.draft.rules.length + 1}`,
      connector: "and",
      antecedents,
      consequents: { [outVar.name]: outVar.terms[0].name },
      weight: 1.0,
    });
    this.renderRulesSection();
  }

  public async registerInWorkspace(): Promise<void> {
    try {
      const typed = this.shell.getTypedWorkspace();
      const existing = typed.listRegisteredObjects(["FuzzySystem"]).filter((o) => o.id === this.draft.id);
      const maxRev = existing.reduce((acc, o) => Math.max(acc, o.revision), 0);
      this.draft.revision = Math.max(this.draft.revision, maxRev + (existing.length > 0 ? 1 : 0));
      await typed.registerTypedObject(this.draft, {
        selectRole: "fuzzySystem",
        source: "manual",
      });
      this.shell
        .getAnnouncer()
        .announce(`Sistema Fuzzy '${this.draft.id}#r${this.draft.revision}' sincronizado no Workspace.`, "polite", "status");
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  private async executeRpc(operation: string, payload: Record<string, unknown>): Promise<RpcResponse> {
    const lqr = this.shell.getLqrWorkspace();
    const projectId = lqr.getProjectId();
    const rev = Math.max(lqr.getProjectRevision(), this.client.getCommittedRevision(projectId));
    return this.client.execute(
      {
        api_version: RPC_API_VERSION,
        request_id: `fuzzy-${generateUuid()}`,
        project_id: projectId,
        project_revision: rev,
        operation,
        payload,
        options: {},
        timeout_policy: { hard_timeout_ms: 20000 },
      },
      { commitOnSuccess: false },
    );
  }

  public async evaluateSurface(): Promise<void> {
    try {
      if (this.mfParamError) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", this.mfParamError);
      }
      const nPoints = Math.round(Number(this.surfaceNPointsEl?.value ?? 15));
      if (!Number.isInteger(nPoints) || nPoints < 2 || nPoints > 200) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Resolução da grade deve ser inteiro entre 2 e 200.",
        );
      }
      const resp = await this.executeRpc("fuzzy.evaluate_surface", {
        system: this.draft,
        n_points: nPoints,
      });
      if (resp.status === "failure" || !resp.result) {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao avaliar superfície Fuzzy.",
        );
      }
      const res = resp.result as Record<string, unknown>;
      const axes = Array.isArray(res.axes) ? (res.axes as string[]) : [];
      const grids = isPlainObject(res.grids) ? (res.grids as Record<string, number[]>) : {};
      const surfaces = isPlainObject(res.surfaces) ? (res.surfaces as Record<string, unknown>) : {};
      const outName = this.draft.output_variables[0]?.name ?? Object.keys(surfaces)[0] ?? "controle";
      const x0Grid = Array.isArray(grids[axes[0]]) ? grids[axes[0]] : [];
      const x1Grid = axes.length >= 2 && Array.isArray(grids[axes[1]]) ? grids[axes[1]] : null;
      const rawSurface = surfaces[outName];
      const zMatrix =
        axes.length >= 2 && Array.isArray(rawSurface) ? (rawSurface as number[][]) : null;
      const zLine =
        axes.length === 1 && Array.isArray(rawSurface) ? (rawSurface as number[]) : null;

      this.surfaceModel = buildFuzzySurfaceChartModel({
        axes,
        output_name: outName,
        x0_grid: x0Grid,
        x1_grid: x1Grid,
        z_matrix: zMatrix,
        z_line: zLine,
        model_revision: this.draft.revision,
        project_revision: this.shell.getLqrWorkspace().getProjectRevision(),
        provenance: resp.provenance as Provenance,
        theme_mode: this.shell.getThemeMode(),
      });

      this.shell
        .getAnnouncer()
        .announce("Superfície de controle fuzzy calculada.", "polite", "status");
      this.renderSurfaceSection();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async evaluatePoint(): Promise<void> {
    try {
      const in0 = this.draft.input_variables[0];
      const in1 = this.draft.input_variables[1];
      const inputsMap: Record<string, number> = {};
      if (in0) inputsMap[in0.name] = Number(this.pointX0El?.value ?? 0);
      if (in1) inputsMap[in1.name] = Number(this.pointX1El?.value ?? 0);
      for (const [k, v] of Object.entries(inputsMap)) {
        if (!Number.isFinite(v)) {
          throw new ControlLabBridgeError("VALIDATION_ERROR", `Entrada '${k}' deve ser finita.`);
        }
      }
      const resp = await this.executeRpc("fuzzy.evaluate", {
        system: this.draft,
        inputs: inputsMap,
      });
      if (resp.status === "failure" || !resp.result) {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha na inferência pontual fuzzy.",
        );
      }
      const res = resp.result as Record<string, unknown>;
      const decimals = this.shell.getDisplayDecimals();
      const outputs = isPlainObject(res.outputs) ? res.outputs : {};
      const outPairs = Object.entries(outputs)
        .map(([k, v]) => `${escapeHtml(k)} = <strong>${formatNumericDisplay(Number(v), decimals)}</strong>`)
        .join(" | ");
      const diag = isPlainObject(resp.diagnostics) ? resp.diagnostics : {};
      const activeCount = typeof diag.active_rules_count === "number" ? diag.active_rules_count : 0;
      const zeroAct = Boolean(diag.zero_activation);

      if (this.pointResultEl) {
        this.pointResultEl.innerHTML = [
          `<p>Saída: ${outPairs} (Regras ativas: <code>${activeCount}</code>)</p>`,
          zeroAct
            ? `<p class="warning-callout">Ativação nula (denominador zero): valor neutro padrão aplicado.</p>`
            : "",
        ].join("");
      }
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async exportFml(trigger: HTMLElement | null): Promise<void> {
    try {
      const resp = await this.executeRpc("fuzzy.export_fml", {
        system: this.draft,
      });
      if (resp.status === "failure" || !resp.result) {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "INTERNAL_ERROR",
          resp.error?.message ?? "Falha ao exportar FML IEEE 1855-2016.",
        );
      }
      const xml = String((resp.result as Record<string, unknown>).fml_xml ?? "");
      if (this.fmlXmlEl) {
        this.fmlXmlEl.value = xml;
      }
      this.onOpenExportModal?.(
        {
          title: `Exportação FML IEEE 1855-2016 (${this.draft.id})`,
          filename: `${this.draft.id}.fml`,
          mimeType: "application/xml;charset=utf-8",
          content: xml,
          offlineDesign: true,
        },
        trigger,
      );
      this.shell.getAnnouncer().announce("FML IEEE 1855-2016 exportado.", "polite", "status");
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async importFml(): Promise<void> {
    try {
      const xml = this.fmlXmlEl?.value?.trim() ?? "";
      if (xml.length === 0) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Cole um documento XML FML (IEEE 1855-2016) no campo de intercâmbio ou selecione um arquivo .fml.",
        );
      }
      const resp = await this.executeRpc("fuzzy.import_fml", {
        xml_content: xml,
      });
      if (resp.status === "failure" || !resp.result) {
        throw new ControlLabBridgeError(
          resp.error?.code ?? "VALIDATION_ERROR",
          resp.error?.message ?? "Falha ao importar FML XML.",
        );
      }
      const sys = (resp.result as Record<string, unknown>).fuzzy_system;
      if (!isPlainObject(sys)) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", "Resposta FML não retornou FuzzySystem.");
      }
      this.draft = structuredClone(sys) as unknown as CanonicalFuzzySystemDraft;
      this.selectedVarName = this.draft.input_variables[0]?.name ?? "erro";
      await this.shell.getTypedWorkspace().registerTypedObject(this.draft, {
        selectRole: "fuzzySystem",
        source: "imported",
      });
      this.shell
        .getAnnouncer()
        .announce(`Sistema Fuzzy '${this.draft.id}' importado de FML IEEE 1855-2016.`, "polite", "status");
      this.render();
      this.onRequestRender?.();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  private renderMfSvgOnly(): void {
    if (!this.mfSvgEl) return;
    const selectedVar = this.findSelectedVariable();
    if (!selectedVar) {
      this.mfSvgEl.innerHTML = "";
      return;
    }
    const theme = getThemeTokens(this.shell.getThemeMode());
    const decimals = this.shell.getDisplayDecimals();
    const widthPx = 560;
    const heightPx = 210;
    const padLeft = 48;
    const padRight = 20;
    const padTop = 30;
    const padBottom = 38;
    const plotW = widthPx - padLeft - padRight;
    const plotH = heightPx - padTop - padBottom;

    const [lo, hi] = selectedVar.universe;
    const span = Math.max(1e-6, hi - lo);
    const toPxX = (x: number) => padLeft + ((x - lo) / span) * plotW;
    const toPxY = (mu: number) => padTop + (1 - Math.max(0, Math.min(1, mu))) * plotH;

    const palette = [
      theme.chartClosedLoop,
      theme.chartOpenLoop,
      theme.chartOverlayExact,
      theme.chartPreview,
      theme.accent,
    ];
    const dashes = ["", "6 3", "2 2", "8 3 2 3", "4 2"];

    const isTsOutput = selectedVar.role === "output" && this.draft.inference_type === "ts";
    const curvesSvg: string[] = [];
    const legendSvg: string[] = [];

    if (isTsOutput) {
      selectedVar.terms.forEach((term, idx) => {
        const col = palette[idx % palette.length];
        const yPx = padTop + ((idx + 1) / (selectedVar.terms.length + 1)) * plotH;
        const label = `${term.name}: ${term.type ?? "constant"}(${term.params.join(", ")})`;
        curvesSvg.push(
          `<line x1="${padLeft}" y1="${yPx.toFixed(1)}" x2="${padLeft + plotW}" y2="${yPx.toFixed(1)}" stroke="${col}" stroke-width="2" stroke-dasharray="${dashes[idx % dashes.length]}" />`,
          `<text x="${padLeft + 8}" y="${(yPx - 4).toFixed(1)}" font-size="10" fill="${col}">${escapeHtml(label)}</text>`,
        );
      });
    } else {
      const nSamples = 80;
      selectedVar.terms.forEach((term, idx) => {
        const col = palette[idx % palette.length];
        const dash = dashes[idx % dashes.length];
        const mfType = term.mf ?? term.type ?? "triangular";
        const pts: string[] = [];
        for (let k = 0; k <= nSamples; k += 1) {
          const xv = lo + (k / nSamples) * span;
          const mu = evalVisualMembership(mfType, term.params, xv);
          pts.push(`${toPxX(xv).toFixed(1)},${toPxY(mu).toFixed(1)}`);
        }
        curvesSvg.push(
          `<polyline fill="none" stroke="${col}" stroke-width="2.2" stroke-dasharray="${dash}" points="${pts.join(" ")}" data-mf-term="${escapeHtml(term.name)}"><title>${escapeHtml(term.name)} (${escapeHtml(mfType)})</title></polyline>`,
        );
        // Vertex markers for triangular / trapezoidal
        if (mfType === "triangular" || mfType === "trapezoidal") {
          term.params.forEach((pxVal, pIdx) => {
            const peak =
              (mfType === "triangular" && pIdx === 1) ||
              (mfType === "trapezoidal" && (pIdx === 1 || pIdx === 2));
            curvesSvg.push(
              `<circle cx="${toPxX(pxVal).toFixed(1)}" cy="${toPxY(peak ? 1 : 0).toFixed(1)}" r="3.5" fill="${col}" stroke="${theme.surface}" stroke-width="1" />`,
            );
          });
        }
        legendSvg.push(
          `<text x="${padLeft + 8 + idx * 82}" y="18" font-size="10" font-weight="bold" fill="${col}">${dash ? "--" : "—"} ${escapeHtml(term.name)}</text>`,
        );
      });
    }

    const ticks = [lo, 0.5 * (lo + hi), hi]
      .map((v) => {
        const px = toPxX(v).toFixed(1);
        return `<text x="${px}" y="${padTop + plotH + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatNumericDisplay(v, decimals))}</text>`;
      })
      .join("");

    this.mfSvgEl.innerHTML = [
      `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Funções de pertinência de ${escapeHtml(selectedVar.name)}" class="scientific-chart-svg fuzzy-mf-svg" viewBox="0 0 ${widthPx} ${heightPx}" width="${widthPx}" height="${heightPx}">`,
      `<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="${theme.surface}" />`,
      `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
      `<g data-layer="mf-curves">${curvesSvg.join("")}</g>`,
      `<g data-layer="legend">${legendSvg.join("")}</g>`,
      `<g class="axis-ticks">${ticks}</g>`,
      `<text x="16" y="${(padTop + plotH / 2).toFixed(1)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(1)})" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">μ(x)</text>`,
      `<text x="${(padLeft + plotW / 2).toFixed(1)}" y="${heightPx - 6}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(selectedVar.name)}</text>`,
      `</svg>`,
    ].join("");
  }

  private renderMfSection(): void {
    const allVars = [
      ...this.draft.input_variables.map((v) => ({ name: v.name, role: "Entrada" })),
      ...this.draft.output_variables.map((v) => ({ name: v.name, role: "Saída" })),
    ];
    if (this.varSelectEl) {
      this.varSelectEl.innerHTML = allVars
        .map(
          (v) =>
            `<option value="${escapeHtml(v.name)}"${v.name === this.selectedVarName ? " selected" : ""}>${escapeHtml(v.name)} (${v.role})</option>`,
        )
        .join("");
    }
    const selectedVar = this.findSelectedVariable();
    if (this.varUniverseEl && selectedVar) {
      this.varUniverseEl.textContent = `Universo: [${selectedVar.universe[0]}, ${selectedVar.universe[1]}]`;
    }

    this.renderMfSvgOnly();

    if (this.mfParamsListEl && selectedVar) {
      const isTsOutput = selectedVar.role === "output" && this.draft.inference_type === "ts";
      const rowsHtml = selectedVar.terms
        .map((term, tIdx) => {
          const curType = isTsOutput
            ? (term.type ?? "constant")
            : (term.mf ?? term.type ?? "triangular");
          const typeOptions = isTsOutput
            ? [
                `<option value="constant"${curType === "constant" ? " selected" : ""}>Constante (TS 0ª)</option>`,
                `<option value="linear"${curType === "linear" ? " selected" : ""}>Linear (TS 1ª)</option>`,
              ].join("")
            : [
                `<option value="triangular"${curType === "triangular" ? " selected" : ""}>Triangular (a,b,c)</option>`,
                `<option value="trapezoidal"${curType === "trapezoidal" ? " selected" : ""}>Trapezoidal (a,b,c,d)</option>`,
                `<option value="gaussian"${curType === "gaussian" ? " selected" : ""}>Gaussiana (c,σ)</option>`,
              ].join("");

          const paramNames =
            curType === "gaussian"
              ? ["c", "σ"]
              : curType === "constant"
                ? ["c₀"]
                : curType === "linear"
                  ? ["p₁", "p₂", "p₀"]
                  : ["a", "b", "c", "d"];

          const paramInputs = term.params
            .map((pVal, pIdx) => {
              const pLabel = paramNames[pIdx] ?? `p${pIdx + 1}`;
              return `<label class="fuzzy-param-cell"><span>${escapeHtml(pLabel)}</span><input type="number" step="0.5" class="touch-control id-param-input" value="${pVal}" data-fuzzy-term-idx="${tIdx}" data-fuzzy-param-idx="${pIdx}" aria-label="${escapeHtml(term.name)} parâmetro ${escapeHtml(pLabel)}" /></label>`;
            })
            .join("");

          return [
            `<div class="fuzzy-param-row" data-term-row="${escapeHtml(term.name)}">`,
            `<strong class="fuzzy-term-name">${escapeHtml(term.name)}</strong>`,
            `<select class="touch-control" data-fuzzy-term-idx="${tIdx}" data-fuzzy-mf-select="true" aria-label="Tipo de pertinência para ${escapeHtml(term.name)}">${typeOptions}</select>`,
            `<div class="fuzzy-param-inputs">${paramInputs}</div>`,
            `</div>`,
          ].join("");
        })
        .join("");

      const errBanner = this.mfParamError
        ? `<p class="field-error" role="alert">${escapeHtml(this.mfParamError)}</p>`
        : "";
      this.mfParamsListEl.innerHTML = errBanner + rowsHtml;
    }
  }

  private renderRulesSection(): void {
    const in0 = this.draft.input_variables[0];
    const in1 = this.draft.input_variables[1];
    const out0 = this.draft.output_variables[0];

    if (this.coverageStatusEl) {
      const expectedGridCount =
        in0 && in1 ? in0.terms.length * in1.terms.length : this.draft.rules.length;
      const fullCoverage = this.draft.rules.length >= expectedGridCount && expectedGridCount > 0;
      this.coverageStatusEl.textContent = `${this.draft.rules.length} regras | ${fullCoverage ? "Cobertura 100%" : "Cobertura parcial"}`;
    }

    if (!this.rulesMatrixEl || !in0 || !out0) return;

    if (!in1) {
      // 1D rules list fallback
      const rows = this.draft.rules
        .map(
          (r) =>
            `<tr><td>${escapeHtml(r.name)}</td><td>${escapeHtml(JSON.stringify(r.antecedents))}</td><td>${escapeHtml(JSON.stringify(r.consequents))}</td></tr>`,
        )
        .join("");
      this.rulesMatrixEl.innerHTML = `<table class="accessible-data-table"><thead><tr><th>Regra</th><th>Antecedente</th><th>Consequente</th></tr></thead><tbody>${rows}</tbody></table>`;
      return;
    }

    const headCols = in1.terms
      .map((t1) => `<th scope="col">${escapeHtml(in1.name)}: ${escapeHtml(t1.name)}</th>`)
      .join("");

    const bodyRows = in0.terms
      .map((t0) => {
        const cells = in1.terms
          .map((t1) => {
            const matched = this.draft.rules.find(
              (r) => r.antecedents[in0.name] === t0.name && r.antecedents[in1.name] === t1.name,
            );
            const curOut = matched?.consequents[out0.name] ?? "";
            const opts = [
              `<option value="">—</option>`,
              ...out0.terms.map(
                (ot) =>
                  `<option value="${escapeHtml(ot.name)}"${ot.name === curOut ? " selected" : ""}>${escapeHtml(ot.name)}</option>`,
              ),
            ].join("");
            return `<td><select class="touch-control" data-rule-t0="${escapeHtml(t0.name)}" data-rule-t1="${escapeHtml(t1.name)}" aria-label="Regra ${escapeHtml(in0.name)}=${escapeHtml(t0.name)} e ${escapeHtml(in1.name)}=${escapeHtml(t1.name)}">${opts}</select></td>`;
          })
          .join("");
        return `<tr><th scope="row">${escapeHtml(in0.name)}: ${escapeHtml(t0.name)}</th>${cells}</tr>`;
      })
      .join("");

    this.rulesMatrixEl.innerHTML = `<table class="accessible-data-table fuzzy-rule-table" aria-label="Matriz de regras 2D"><thead><tr><th scope="col">${escapeHtml(in0.name)} \\ ${escapeHtml(in1.name)}</th>${headCols}</tr></thead><tbody>${bodyRows}</tbody></table>`;
  }

  private renderSurfaceSection(): void {
    const decimals = this.shell.getDisplayDecimals();
    if (!this.surfaceModel) {
      if (this.surfaceChartSlotEl) this.surfaceChartSlotEl.innerHTML = "";
      if (this.surfaceTableSlotEl) {
        this.surfaceTableSlotEl.innerHTML = `<p>Nenhuma superfície calculada ainda.</p>`;
      }
      return;
    }
    const model: FuzzySurfaceChartModel = {
      ...this.surfaceModel,
      theme_mode: this.shell.getThemeMode(),
    };
    if (this.surfaceChartSlotEl) {
      this.surfaceChartSlotEl.innerHTML = renderFuzzySurfaceSvg(model, { decimals });
    }
    if (this.surfaceTableSlotEl) {
      const table = buildAccessibleChartTable(model, decimals);
      this.surfaceTableSlotEl.innerHTML = renderAccessibleTableHtml(table);
    }
  }

  public render(): void {
    const isFuzzy = this.shell.getActiveTab() === "fuzzy_ts";
    setElHidden(this.panelEl, !isFuzzy);
    if (!isFuzzy) return;

    if (this.inferenceSelectEl && this.inferenceSelectEl.value !== this.draft.inference_type) {
      this.inferenceSelectEl.value = this.draft.inference_type;
    }
    this.renderMfSection();
    this.renderRulesSection();
    this.renderSurfaceSection();
  }
}
