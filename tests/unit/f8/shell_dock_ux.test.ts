/**
 * Testes unitários de WP-UX-REFACTOR-01-SHELL-DOCK (F8: f8-ui-charts)
 *
 * Verificam:
 * - Workspace Dock esquerdo persistente (#workspace-dock-aside) dentro de .app-workbench-shell
 * - Agrupamento em 3 categorias: Séries Temporais (Dados), Plantas & Modelos, Controladores Projetados
 * - Resumos matemáticos legíveis (G(s) = ..., n×m SS, dt=...) e roteamento 1-clique (→ SISO, → SS/LQR, → Identificação)
 * - Toggle recolhível #btn-toggle-workspace-dock
 * - Modal guiado "+ Novo" (#workspace-new-object-modal) nos 3 modos (TF, StateSpace, CSV)
 * - Inspetor Técnico R-27 (#inspector-drawer) oculto por padrão, alternado via #btn-toggle-inspector, exibindo telemetria R-27 + JSON canônico
 * - Dicionário de tradução semântica (CL-UX-DIR-001 Seção 2) preservando data-action, #id e invariantes R-23
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import {
  formatDockObjectDisplayName,
  formatDockObjectSummary,
} from "../../../web/app/workspace_dock.ts";
import {
  buildTimeResponseChartModel,
  exportChartToCsv,
  renderPoleZeroSvg,
  renderTimeResponseSvg,
} from "../../../web/charts/scientific_chart.ts";

class FakeElement {
  public tagName: string;
  public id = "";
  public className = "";
  public value = "";
  public checked = false;
  public disabled = false;
  public children: FakeElement[] = [];
  public parentNode: FakeElement | null = null;
  public ownerDocument: FakeDocument;
  public attributes = new Map<string, string>();
  public listeners = new Map<string, Array<(ev: unknown) => void>>();
  private _innerHTML = "";
  private _textContent = "";

  constructor(tagName: string, doc: FakeDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = doc;
  }

  public get textContent(): string {
    if (this.children.length === 0) return this._textContent;
    return this._textContent + this.children.map((c) => c.textContent).join("");
  }

  public set textContent(v: string) {
    this._textContent = String(v);
    this.children = [];
  }

  public appendText(txt: string): void {
    this._textContent += txt
      .replaceAll("&amp;", "&")
      .replaceAll("&lt;", "<")
      .replaceAll("&gt;", ">")
      .replaceAll("&quot;", '"');
  }

  public get innerHTML(): string {
    return this._innerHTML;
  }

  public set innerHTML(html: string) {
    this._innerHTML = html;
    this.children = parseFakeHtml(html, this.ownerDocument, this);
    this._textContent = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  }

  public setAttribute(name: string, val: string): void {
    const s = String(val);
    this.attributes.set(name, s);
    if (name === "id") this.id = s;
    if (name === "class") this.className = s;
    if (name === "value") this.value = s;
    if (name === "disabled") this.disabled = true;
  }

  public getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  public hasAttribute(name: string): boolean {
    return this.attributes.has(name);
  }

  public removeAttribute(name: string): void {
    this.attributes.delete(name);
    if (name === "disabled") this.disabled = false;
  }

  public addEventListener(type: string, fn: (ev: unknown) => void): void {
    const list = this.listeners.get(type) ?? [];
    list.push(fn);
    this.listeners.set(type, list);
  }

  public dispatchEvent(type: string | { type: string; key?: string; target?: unknown }): boolean {
    const evType = typeof type === "string" ? type : type.type;
    const evObj =
      typeof type === "string"
        ? { type: evType, target: this, currentTarget: this, preventDefault() {} }
        : { ...type, target: type.target ?? this, currentTarget: this, preventDefault() {} };
    for (const fn of this.listeners.get(evType) ?? []) {
      fn(evObj);
    }
    if (this.parentNode && (evType === "change" || evType === "click")) {
      for (const fn of this.parentNode.listeners.get(evType) ?? []) {
        fn({ ...evObj, currentTarget: this.parentNode });
      }
    }
    return true;
  }

  public focus(): void {
    this.ownerDocument.activeElement = this;
  }

  public querySelector<T = FakeElement>(selector: string): T | null {
    return (this.querySelectorAll<FakeElement>(selector)[0] ?? null) as T | null;
  }

  public querySelectorAll<T = FakeElement>(selector: string): T[] {
    const results: FakeElement[] = [];
    const visit = (node: FakeElement): void => {
      for (const child of node.children) {
        if (matchesSimpleSelector(child, selector)) {
          results.push(child);
        }
        visit(child);
      }
    };
    visit(this);
    return results as T[];
  }
}

function matchesSimpleSelector(el: FakeElement, selector: string): boolean {
  const s = selector.trim();
  if (s.startsWith("#") && !s.includes("[") && !s.includes(".")) return el.id === s.slice(1);
  if (s.startsWith(".") && !s.includes("[")) return el.className.split(/\s+/).includes(s.slice(1));
  const idMatch = /^#([a-zA-Z0-9_-]+)/.exec(s);
  if (idMatch && el.id !== idMatch[1]) return false;
  const tagMatch = /^([a-zA-Z0-9_-]+)/.exec(s);
  if (tagMatch && el.tagName !== tagMatch[1].toUpperCase()) return false;
  const attrRe = /\[([^\]=]+)(?:="([^"]*)")?\]/g;
  let m: RegExpExecArray | null;
  let matchedAnyAttr = false;
  while ((m = attrRe.exec(s)) !== null) {
    matchedAnyAttr = true;
    const actual = el.getAttribute(m[1]);
    if (m[2] === undefined) {
      if (actual === null) return false;
    } else if (actual !== m[2]) {
      return false;
    }
  }
  if (!matchedAnyAttr && s.includes("[")) return false;
  return matchedAnyAttr || Boolean(tagMatch) || Boolean(idMatch);
}

class FakeDocument {
  public activeElement: FakeElement | null = null;
  public documentElement: FakeElement;
  public body: FakeElement;

  constructor() {
    this.documentElement = new FakeElement("html", this);
    this.body = new FakeElement("body", this);
  }

  public createElement(tag: string): FakeElement {
    return new FakeElement(tag, this);
  }
}

function parseFakeHtml(html: string, doc: FakeDocument, rootParent: FakeElement): FakeElement[] {
  const topNodes: FakeElement[] = [];
  const stack: FakeElement[] = [rootParent];
  const voidTags = new Set(["input", "br", "hr", "img", "meta", "link"]);
  const tokenRe = /<(\/?)([a-zA-Z0-9_-]+)([^>]*?)(\/?)>/g;
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  while ((match = tokenRe.exec(html)) !== null) {
    if (match.index > lastIdx) {
      const text = html.slice(lastIdx, match.index);
      const cur = stack[stack.length - 1];
      if (cur && cur !== rootParent) {
        cur.appendText(text);
        if (cur.tagName === "TEXTAREA") cur.value += text;
      }
    }
    lastIdx = tokenRe.lastIndex;
    const isClose = match[1] === "/";
    const tag = match[2].toLowerCase();
    const attrsRaw = match[3];
    const selfClose = match[4] === "/" || voidTags.has(tag);
    if (isClose) {
      for (let i = stack.length - 1; i >= 1; i -= 1) {
        if (stack[i].tagName === tag.toUpperCase()) {
          stack.length = i;
          break;
        }
      }
      continue;
    }
    const el = doc.createElement(tag);
    const attrRe = /([a-zA-Z0-9_-]+)(?:="([^"]*)")?/g;
    let am: RegExpExecArray | null;
    while ((am = attrRe.exec(attrsRaw)) !== null) {
      el.setAttribute(am[1], am[2] ?? "");
    }
    const parent = stack[stack.length - 1];
    el.parentNode = parent;
    if (parent === rootParent) topNodes.push(el);
    else parent.children.push(el);
    if (!selfClose) stack.push(el);
  }
  return topNodes;
}

test("WP-UX-REFACTOR-01-SHELL-DOCK: layout 3 zonas, Workspace Dock com categorias, roteamento 1-clique e toggle", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-ux-dock",
  });
  await app.client.init();

  const shellWrap = root.querySelector<FakeElement>(".app-workbench-shell")!;
  const dockAside = root.querySelector<FakeElement>("#workspace-dock-aside")!;
  const mainEl = root.querySelector<FakeElement>("#controllab-main")!;
  const inspectorAside = root.querySelector<FakeElement>("#inspector-drawer")!;

  assert.ok(shellWrap !== null);
  assert.ok(dockAside !== null);
  assert.ok(mainEl !== null);
  assert.ok(inspectorAside !== null);
  assert.deepEqual(
    shellWrap.children.map((c) => c.id),
    ["workspace-dock-aside", "controllab-main", "inspector-drawer"],
  );

  // Dock starts expanded; inspector starts hidden by default
  assert.equal(dockAside.hasAttribute("hidden"), false);
  assert.equal(inspectorAside.hasAttribute("hidden"), true);

  // Top bar editable project title + dock toggle + inspector toggle
  const titleInput = root.querySelector<FakeElement>("#project-title-input")!;
  assert.ok(titleInput !== null);
  titleInput.value = "Motor DC — Bancada Lab 03";
  titleInput.dispatchEvent("change");
  assert.equal(titleInput.value, "Motor DC — Bancada Lab 03");

  // 3 dock groups rendered
  const dockContent = dockAside.querySelector<FakeElement>("#workspace-dock-content")!;
  assert.ok(dockAside.querySelector('[data-dock-group="datasets"]') !== null);
  assert.ok(dockAside.querySelector('[data-dock-group="models"]') !== null);
  assert.ok(dockAside.querySelector('[data-dock-group="controllers"]') !== null);
  assert.ok(dockContent.innerHTML.includes("2×1 SS"));

  // Toggle dock collapse/expand
  const dockToggleBtn = root.querySelector<FakeElement>("#btn-toggle-workspace-dock")!;
  dockToggleBtn.dispatchEvent("click");
  assert.equal(dockAside.hasAttribute("hidden"), true);
  assert.equal(dockToggleBtn.getAttribute("aria-expanded"), "false");
  assert.ok(shellWrap.className.includes("dock-collapsed"));
  dockToggleBtn.dispatchEvent("click");
  assert.equal(dockAside.hasAttribute("hidden"), false);
  assert.equal(dockToggleBtn.getAttribute("aria-expanded"), "true");

  // Register a TransferFunction and verify human-readable summary & 1-click SISO routing
  const tfDto = {
    schema_version: "1.0.0",
    id: "tf-motor-dc",
    revision: 1,
    kind: "TransferFunction",
    dt: null,
    variable: "s",
    poly_order: "descending",
    num: [[{ shape: [1], dtype: "float64", order: "C", data: [2] }]],
    den: [[{ shape: [3], dtype: "float64", order: "C", data: [1, 3, 2] }]],
    units: { time: "s", inputs: ["V"], outputs: ["rad/s"] },
    provenance: { source: "test" },
  };
  const regTf = await app.shell.getTypedWorkspace().registerTypedObject(tfDto);
  assert.ok(formatDockObjectSummary(regTf, 2).includes("G(s) = 2 / (s^2 + 3·s + 2)"));
  assert.ok(dockContent.innerHTML.includes("tf-motor-dc"));
  assert.ok(dockContent.innerHTML.includes("G(s)"));

  const routeSisoBtn = dockAside.querySelector<FakeElement>(
    `[data-dock-action="route-siso"][data-object-key="${regTf.key}"]`,
  )!;
  assert.ok(routeSisoBtn !== null);
  routeSisoBtn.dispatchEvent("click");
  assert.equal(app.shell.getActiveTab(), "siso_frequency");
  assert.equal(
    app.shell.getTypedWorkspace().getEffectiveSelection("frequencyPlant")?.ref.id,
    "tf-motor-dc",
  );

  // Register a Dataset and verify 1-click Identification routing
  await app.shell.getIdentificationWorkspace().loadBenchmarkDataset({
    preset: "prbs",
    splitTrainHoldout: false,
  });
  const dsObj = app.shell.getTypedWorkspace().listRegisteredObjects(["Dataset"])[0];
  assert.ok(dsObj !== undefined);
  assert.ok(dockContent.innerHTML.includes("dt=0.05 s"));
  const routeIdBtn = dockAside.querySelector<FakeElement>(
    `[data-dock-action="route-identification"][data-object-key="${dsObj.key}"]`,
  )!;
  routeIdBtn.dispatchEvent("click");
  assert.equal(app.shell.getActiveTab(), "identification");
  assert.equal(mainEl.className.split(/\s+/).includes("tab-identification"), true);
  assert.equal(mainEl.className.split(/\s+/).includes("single-main-col"), false);

  // Commit LQR and verify controller appears under Controladores Projetados
  app.shell.switchTab("statespace");
  assert.equal(mainEl.className.split(/\s+/).includes("tab-identification"), false);
  await app.shell.getLqrWorkspace().commitCurrentDesign();
  const ctrlGroup = dockAside.querySelector<FakeElement>('[data-dock-group="controllers"]')!;
  assert.ok(ctrlGroup.textContent.includes("K = [2.0000, 3.0000]"));
  assert.ok(ctrlGroup.textContent.includes("Confirmado"));

  app.destroy();
});

test("WP-UX-REFACTOR-01-SHELL-DOCK: modal guiado + Novo cria TransferFunction, StateSpace e Dataset CSV", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-new-modal",
  });
  await app.client.init();

  const modal = root.querySelector<FakeElement>("#workspace-new-object-modal")!;
  assert.equal(modal.hasAttribute("hidden"), true);

  // Open modal -> defaults to TF mode
  root.querySelector("#btn-open-new-object-modal")!.dispatchEvent("click");
  assert.equal(modal.hasAttribute("hidden"), false);
  assert.equal(root.querySelector("#new-obj-panel-tf")!.hasAttribute("hidden"), false);
  assert.equal(root.querySelector("#new-obj-panel-ss")!.hasAttribute("hidden"), true);
  assert.equal(root.querySelector("#new-obj-panel-csv")!.hasAttribute("hidden"), true);

  // 1. Create TransferFunction
  root.querySelector<FakeElement>("#new-tf-id")!.value = "tf-modal-01";
  root.querySelector<FakeElement>("#new-tf-num")!.value = "5";
  root.querySelector<FakeElement>("#new-tf-den")!.value = "1, 4";
  root.querySelector<FakeElement>("#new-tf-dt")!.value = "";
  root.querySelector('[data-action="submit-new-tf"]')!.dispatchEvent("click");

  await new Promise((r) => setTimeout(r, 30));
  assert.equal(modal.hasAttribute("hidden"), true);
  const tfEntry = app.shell
    .getTypedWorkspace()
    .listRegisteredObjects(["TransferFunction"])
    .find((o) => o.id === "tf-modal-01");
  assert.ok(tfEntry !== undefined);

  // 2. Open modal -> switch to StateSpace mode and create StateSpace
  root.querySelector("#btn-open-new-object-modal")!.dispatchEvent("click");
  root.querySelector("#btn-new-mode-ss")!.dispatchEvent("click");
  assert.equal(root.querySelector("#new-obj-panel-ss")!.hasAttribute("hidden"), false);
  root.querySelector<FakeElement>("#new-ss-id")!.value = "ss-modal-01";
  root.querySelector<FakeElement>("#new-ss-a")!.value = "0 1; -3 -2";
  root.querySelector<FakeElement>("#new-ss-b")!.value = "0; 1";
  root.querySelector<FakeElement>("#new-ss-c")!.value = "1 0";
  root.querySelector<FakeElement>("#new-ss-d")!.value = "0";
  root.querySelector('[data-action="submit-new-ss"]')!.dispatchEvent("click");

  await new Promise((r) => setTimeout(r, 30));
  assert.equal(modal.hasAttribute("hidden"), true);
  const ssEntry = app.shell
    .getTypedWorkspace()
    .listRegisteredObjects(["StateSpace"])
    .find((o) => o.id === "ss-modal-01");
  assert.ok(ssEntry !== undefined);

  // 3. Open modal -> switch to CSV mode and import Dataset
  root.querySelector("#btn-open-new-object-modal")!.dispatchEvent("click");
  root.querySelector("#btn-new-mode-csv")!.dispatchEvent("click");
  assert.equal(root.querySelector("#new-obj-panel-csv")!.hasAttribute("hidden"), false);
  root.querySelector<FakeElement>("#new-csv-id")!.value = "ds-modal-csv";
  root.querySelector<FakeElement>("#new-csv-train-fraction")!.value = "0.6";
  root.querySelector('[data-action="submit-new-csv"]')!.dispatchEvent("click");

  await new Promise((r) => setTimeout(r, 30));
  assert.equal(modal.hasAttribute("hidden"), true);
  const dsTrain = app.shell
    .getTypedWorkspace()
    .listRegisteredObjects(["Dataset"])
    .find((o) => o.id === "ds-modal-csv-train");
  assert.ok(dsTrain !== undefined);

  app.destroy();
});

test("WP-UX-REFACTOR-01-SHELL-DOCK: Inspetor R-27 oculto por padrão, alterna telemetria + JSON canônico e dicionário semântico", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-inspector-ux",
  });
  await app.client.init();

  const shellWrap = root.querySelector<FakeElement>(".app-workbench-shell")!;
  const drawer = root.querySelector<FakeElement>("#inspector-drawer")!;
  const toggleBtn = root.querySelector<FakeElement>("#btn-toggle-inspector")!;
  const telemetrySlot = root.querySelector<FakeElement>("#inspector-telemetry-slot")!;
  const jsonPre = root.querySelector<FakeElement>("#inspector-json-pre")!;

  // Collapsed by default
  assert.equal(drawer.hasAttribute("hidden"), true);
  assert.equal(toggleBtn.getAttribute("aria-expanded"), "false");

  // Commit LQR so rCARE / seed / project_revision / model_revision are populated
  await app.shell.getLqrWorkspace().commitCurrentDesign();

  // Toggle open via Top Bar button
  toggleBtn.dispatchEvent("click");
  assert.equal(drawer.hasAttribute("hidden"), false);
  assert.equal(toggleBtn.getAttribute("aria-expanded"), "true");
  assert.ok(shellWrap.className.includes("inspector-open"));
  assert.ok(telemetrySlot.innerHTML.includes("rCARE="));
  assert.ok(telemetrySlot.innerHTML.includes("proj_rev="));
  assert.ok(telemetrySlot.innerHTML.includes("model_rev="));
  assert.ok(telemetrySlot.innerHTML.includes("Seed"));
  assert.ok(telemetrySlot.innerHTML.includes("SHA-256"));
  assert.ok(jsonPre.textContent.includes('"kind": "StateSpace"'));

  // Close via drawer Close button
  root.querySelector("#btn-close-inspector")!.dispatchEvent("click");
  assert.equal(drawer.hasAttribute("hidden"), true);
  assert.equal(toggleBtn.getAttribute("aria-expanded"), "false");

  // Verify Semantic Translation Dictionary labels (CL-UX-DIR-001 Seção 2) while keeping data-action hooks
  assert.equal(
    root.querySelector('[data-action="reuse-model"]')!.textContent,
    "Converter / Registrar Modelo",
  );
  assert.equal(
    root.querySelector('[data-action="register-pending-identified"]')!.textContent,
    "Validar Modelo na Sessão",
  );
  assert.equal(
    root.querySelector('[data-action="register-pending-derived"]')!.textContent,
    "Registrar Modelo Derivado",
  );
  assert.equal(
    root.querySelector('[data-action="id-load-const-pe"]')!.textContent,
    "Dataset Entrada Constante (Sem Excitação)",
  );
  assert.equal(
    root.querySelector('[data-action="build-report"]')!.textContent,
    "Relatório Científico (R-27)",
  );
  assert.ok(
    root.querySelector("#identification-workspace-panel")!.textContent.includes(
      "Identificação de Sistemas (Dados → Estimação → Validação)",
    ),
  );
  assert.ok(
    root.querySelector("#siso-workspace-panel")!.textContent.includes(
      "Análise & Projeto SISO na Frequência",
    ),
  );

  // R-23 status text invariant preserved
  app.shell.getLqrWorkspace().pointerDown("lqr-q-slider");
  app.shell.getLqrWorkspace().pointerMove({ qScale: 2.0 });
  assert.ok(root.querySelector("#lqr-status-text")!.textContent.startsWith("Fast-Preview"));
  await app.shell.getLqrWorkspace().cancelDrag();

  app.destroy();
});

test("WP-UX-REFACTOR-05-HIGH-CONTRAST-AND-VISUAL-CLEANUP: sincroniza high_contrast em container/documentElement/body, repassa themeMode aos gráficos SVG, avalia 4 gráficos SISO em 1 clique e alterna .advanced-rpc-drawer", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const makeSuccessResp = (
    req: { request_id: string; project_id: string; project_revision: number; operation: string },
    result: Record<string, unknown>,
  ) => ({
    api_version: "1.0" as const,
    request_id: req.request_id,
    project_id: req.project_id,
    project_revision: req.project_revision,
    status: "success" as const,
    result,
    assumptions: {},
    diagnostics: {
      numeric_status: "ok" as const,
      warnings_count: 0,
      condition_estimates: {},
      residuals: {},
      timings_ms: { total: 1.0 },
    },
    provenance: {
      operation: req.operation,
      algorithm: "mock",
      backend: "numpy_scipy",
      code_hash: "0".repeat(64),
      input_hash: "0".repeat(64),
      random_seed: null,
      deterministic: true,
      model_revision: 1,
      project_revision: req.project_revision,
      lib_versions: { python: "3.12", numpy: "2.0", scipy: "1.14", control_lab: "1.0.0" },
    },
    warnings: [],
    error: null,
  });
  const mockAdapter = new MockWorkerAdapter();
  const origExecute = mockAdapter.execute.bind(mockAdapter);
  mockAdapter.execute = async (req, opts) => {
    if (req.operation === "frequency.eval_response") {
      return makeSuccessResp(req, {
        dt: null,
        omega: [0.1, 1.0, 10.0],
        mag_db: [0, -3.01, -20.0],
        phase_deg: [-5.7, -45.0, -84.3],
        response: { real: [0.99, 0.5, 0.01], imag: [-0.1, -0.5, -0.1] },
      });
    }
    if (req.operation === "frequency.stability_margins") {
      return makeSuccessResp(req, {
        gain_crossovers: [{ omega_gc: 1.0, phase_deg: -45.0, phase_margin_deg: 135.0, delay_margin_sec: 2.35 }],
        phase_crossovers: [],
        critical_phase_margin_deg: 135.0,
        critical_omega_gc: 1.0,
        critical_delay_margin_sec: 2.35,
        critical_gain_margin_db: null,
        critical_gain_margin_linear: null,
        critical_omega_pc: null,
        closed_loop_stable: true,
        closed_loop_poles: { real: [-2.0], imag: [0.0] },
      });
    }
    if (req.operation === "frequency.root_locus") {
      return makeSuccessResp(req, {
        dt: null,
        gains: [0, 1, 5],
        branches: [{ real: [-1.0, -2.0, -6.0], imag: [0.0, 0.0, 0.0] }],
        open_loop_poles: { real: [-1.0], imag: [0.0] },
        open_loop_zeros: { real: [], imag: [] },
        breakaway_points: [],
        stability_crossings: [],
      });
    }
    if (req.operation === "frequency.step_response") {
      return makeSuccessResp(req, {
        dt: null,
        t: [0, 0.5, 1.0],
        y: [[0], [0.35], [0.5]],
        u: [[1], [0.65], [0.5]],
        metrics: {
          is_stable: true,
          steady_state_value: 0.5,
          steady_state_error: 0.5,
          overshoot_percent: 0,
          peak_value: 0.5,
          peak_time: 1.0,
          settling_time: 0.8,
          settling_threshold: 0.02,
          rise_time_10_90: 0.5,
        },
      });
    }
    return origExecute(req, opts);
  };

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: mockAdapter,
    project_id: "proj-ux-hc-cleanup",
  });
  await app.client.init();

  // Default theme is standard_aa synced across container, documentElement, and body
  assert.equal(root.getAttribute("data-theme"), "standard_aa");
  assert.equal(doc.documentElement.getAttribute("data-theme"), "standard_aa");
  assert.equal(doc.body.getAttribute("data-theme"), "standard_aa");

  // Commit LQR so StateSpace pole-zero chart is rendered
  await app.shell.getLqrWorkspace().commitCurrentDesign();
  const pzChartSlot = root.querySelector<FakeElement>("#pz-chart-slot")!;
  assert.ok(pzChartSlot.innerHTML.includes("#FFFFFF"));

  // Toggle High-Contrast mode
  const themeBtn = root.querySelector<FakeElement>("#theme-toggle-btn")!;
  themeBtn.dispatchEvent("click");
  assert.equal(root.getAttribute("data-theme"), "high_contrast");
  assert.equal(doc.documentElement.getAttribute("data-theme"), "high_contrast");
  assert.equal(doc.body.getAttribute("data-theme"), "high_contrast");

  // LQR SVG chart re-renders immediately with dark high-contrast surface (#0B0F17)
  assert.ok(pzChartSlot.innerHTML.includes("#0B0F17"));

  // Switch to SISO tab, register a TransferFunction, and click 1-click button #btn-siso-eval-all
  await app.shell.getTypedWorkspace().registerTypedObject(
    {
      schema_version: "1.0.0",
      id: "tf-siso-hc",
      revision: 1,
      kind: "TransferFunction",
      dt: null,
      variable: "s",
      poly_order: "descending",
      num: [[{ shape: [1], dtype: "float64", order: "C", data: [1] }]],
      den: [[{ shape: [2], dtype: "float64", order: "C", data: [1, 1] }]],
      units: { time: "s", inputs: ["u"], outputs: ["y"] },
      provenance: { source: "test" },
    },
    { selectRole: "frequencyPlant" },
  );
  app.shell.switchTab("siso_frequency");
  const evalAllBtn = root.querySelector<FakeElement>("#btn-siso-eval-all")!;
  assert.ok(evalAllBtn !== null);
  assert.equal(evalAllBtn.getAttribute("data-action"), "siso-eval-all");
  evalAllBtn.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 80));

  const bodeSlot = root.querySelector<FakeElement>("#siso-bode-chart-slot")!;
  const nyquistSlot = root.querySelector<FakeElement>("#siso-nyquist-chart-slot")!;
  const rlSlot = root.querySelector<FakeElement>("#siso-rl-chart-slot")!;
  const sisoTimeSlot = root.querySelector<FakeElement>("#siso-time-chart-slot")!;
  assert.ok(
    bodeSlot.innerHTML.includes("<svg"),
    `bodeSlot empty; lastError=${JSON.stringify(app.shell.getPresentedLastError())}`,
  );
  assert.ok(nyquistSlot.innerHTML.includes("<svg"));
  assert.ok(rlSlot.innerHTML.includes("<svg"));
  assert.ok(sisoTimeSlot.innerHTML.includes("<svg"));
  // All 4 SISO charts rendered in high_contrast surface (#0B0F17)
  assert.ok(bodeSlot.innerHTML.includes("#0B0F17"));
  assert.ok(nyquistSlot.innerHTML.includes("#0B0F17"));
  assert.ok(rlSlot.innerHTML.includes("#0B0F17"));
  assert.ok(sisoTimeSlot.innerHTML.includes("#0B0F17"));

  // Toggle back to standard_aa -> all 4 SISO charts re-render in light theme (#FFFFFF)
  themeBtn.dispatchEvent("click");
  assert.equal(root.getAttribute("data-theme"), "standard_aa");
  assert.ok(bodeSlot.innerHTML.includes("#FFFFFF"));
  assert.ok(nyquistSlot.innerHTML.includes("#FFFFFF"));
  assert.ok(rlSlot.innerHTML.includes("#FFFFFF"));
  assert.ok(sisoTimeSlot.innerHTML.includes("#FFFFFF"));

  // Verify compact .advanced-rpc-drawer and #btn-toggle-advanced-rpc toggle .expanded
  const rpcDrawer = root.querySelector<FakeElement>("#legacy-rpc-inspector-details")!;
  const toggleRpcBtn = root.querySelector<FakeElement>("#btn-toggle-advanced-rpc")!;
  assert.ok(rpcDrawer !== null);
  assert.ok(toggleRpcBtn !== null);
  assert.equal(rpcDrawer.className.split(/\s+/).includes("advanced-rpc-drawer"), true);
  assert.equal(rpcDrawer.className.split(/\s+/).includes("expanded"), false);
  assert.equal(toggleRpcBtn.getAttribute("aria-expanded"), "false");

  toggleRpcBtn.dispatchEvent("click");
  assert.equal(rpcDrawer.className.split(/\s+/).includes("expanded"), true);
  assert.equal(toggleRpcBtn.getAttribute("aria-expanded"), "true");

  toggleRpcBtn.dispatchEvent("click");
  assert.equal(rpcDrawer.className.split(/\s+/).includes("expanded"), false);
  assert.equal(toggleRpcBtn.getAttribute("aria-expanded"), "false");

  app.destroy();
});

test("WP-UX-REFACTOR-07-WORKBENCH-MOCKUP-FIDELITY: Topbar global project buttons (#btn-header-open-ctrlab, #btn-header-export-ctrlab, #btn-header-export-pvm) respeitam R-23 e layouts .lmi-results-split, .mimo-workbench-grid, .siso-charts-grid, #siso-advanced-params-details mantêm todos os slots filhos", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const mockAdapter = new MockWorkerAdapter();
  const origExecute = mockAdapter.execute.bind(mockAdapter);
  mockAdapter.execute = async (req, opts) => {
    if (req.operation === "io.export_pvm" || req.operation === "io.export_ctrlab") {
      const { sha256Hex } = await import("../../../web/bridge/protocol.ts");
      const bytes = new TextEncoder().encode(JSON.stringify(req.payload));
      return {
        api_version: req.api_version,
        request_id: req.request_id,
        project_id: req.project_id,
        project_revision: req.project_revision,
        status: "success" as const,
        result: {
          bytes_base64: btoa(String.fromCharCode(...bytes)),
          sha256: sha256Hex(bytes),
          size_bytes: bytes.length,
          media_type: req.operation === "io.export_ctrlab" ? "application/zip" : "application/json",
        },
        assumptions: {},
        diagnostics: {
          numeric_status: "ok" as const,
          warnings_count: 0,
          condition_estimates: {},
          residuals: {},
          timings_ms: { total: 1.0 },
        },
        provenance: {
          operation: req.operation,
          algorithm: "test.io_transport",
          backend: "numpy_scipy",
          code_hash: "0".repeat(64),
          input_hash: "0".repeat(64),
          random_seed: null,
          deterministic: true,
          model_revision: 1,
          project_revision: req.project_revision,
          lib_versions: {},
        },
        warnings: [],
        error: null,
      };
    }
    return origExecute(req, opts);
  };
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: mockAdapter,
    project_id: "proj-ux-mockup-fidelity",
  });
  await app.client.init();

  const headerOpenBtn = root.querySelector<FakeElement>("#btn-header-open-ctrlab")!;
  const headerExportCtrlabBtn = root.querySelector<FakeElement>("#btn-header-export-ctrlab")!;
  const headerExportPvmBtn = root.querySelector<FakeElement>("#btn-header-export-pvm")!;

  assert.ok(headerOpenBtn !== null);
  assert.ok(headerExportCtrlabBtn !== null);
  assert.ok(headerExportPvmBtn !== null);

  // Before LQR commit: R-23 blocks export
  assert.equal(headerExportCtrlabBtn.disabled, true);
  assert.equal(headerExportCtrlabBtn.getAttribute("aria-disabled"), "true");
  assert.equal(headerExportPvmBtn.disabled, true);
  assert.equal(headerExportPvmBtn.getAttribute("aria-disabled"), "true");

  // Single unique IDs for Tab 3 file input and export buttons
  assert.equal(root.querySelectorAll("#ctrlab-file-input").length, 1);
  assert.equal(root.querySelectorAll("#btn-export-ctrlab").length, 1);
  assert.equal(root.querySelectorAll("#btn-export-pvm").length, 1);

  // Clicking #btn-header-open-ctrlab forwards click to #ctrlab-file-input
  let fileInputClicked = false;
  root.querySelector<FakeElement>("#ctrlab-file-input")!.addEventListener("click", () => {
    fileInputClicked = true;
  });
  headerOpenBtn.dispatchEvent("click");
  assert.equal(fileInputClicked, true);

  // Commit LQR -> Topbar export buttons become enabled
  await app.shell.getLqrWorkspace().commitCurrentDesign();
  assert.equal(headerExportCtrlabBtn.disabled, false);
  assert.equal(headerExportCtrlabBtn.getAttribute("aria-disabled"), null);
  assert.equal(headerExportPvmBtn.disabled, false);
  assert.equal(headerExportPvmBtn.getAttribute("aria-disabled"), null);

  // Clicking #btn-header-export-pvm triggers .pvm export modal
  const exportModal = root.querySelector<FakeElement>("#controllab-export-modal")!;
  const exportModalTitle = root.querySelector<FakeElement>("#export-modal-title")!;
  assert.equal(exportModal.hasAttribute("hidden"), true);
  headerExportPvmBtn.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 40));
  assert.equal(exportModal.hasAttribute("hidden"), false);
  assert.equal(exportModalTitle.textContent, "Exportação .pvm");

  // Verify workbench grid containers and child slots exist in DOM
  const sisoDetails = root.querySelector<FakeElement>("#siso-advanced-params-details")!;
  assert.ok(sisoDetails !== null);
  assert.equal(sisoDetails.hasAttribute("open"), true);
  assert.ok(sisoDetails.querySelector("#btn-siso-eval-bode") !== null);
  assert.ok(sisoDetails.querySelector("#btn-siso-eval-rl") !== null);
  assert.ok(sisoDetails.querySelector("#btn-siso-eval-step") !== null);
  assert.ok(sisoDetails.querySelector("#siso-delay") !== null);
  assert.ok(sisoDetails.querySelector("#siso-rl-zeta") !== null);

  const sisoChartsGrid = root.querySelector<FakeElement>(".siso-charts-grid")!;
  assert.ok(sisoChartsGrid !== null);
  assert.ok(sisoChartsGrid.querySelector("#siso-bode-chart-slot") !== null);
  assert.ok(sisoChartsGrid.querySelector("#siso-nyquist-chart-slot") !== null);
  assert.ok(sisoChartsGrid.querySelector("#siso-rl-chart-slot") !== null);
  assert.ok(sisoChartsGrid.querySelector("#siso-time-chart-slot") !== null);

  const mimoGrid = root.querySelector<FakeElement>(".mimo-workbench-grid")!;
  assert.ok(mimoGrid !== null);
  assert.ok(mimoGrid.querySelector("#mimo-sigma-chart-slot") !== null);
  assert.ok(mimoGrid.querySelector("#mimo-rga-heatmap-slot") !== null);

  const fuzzyGrid = root.querySelector<FakeElement>(".fuzzy-workbench-grid")!;
  assert.ok(fuzzyGrid !== null);
  assert.ok(fuzzyGrid.querySelector("#fuzzy-mf-svg") !== null);
  assert.ok(fuzzyGrid.querySelector("#fuzzy-surface-chart-slot") !== null);

  const lmiResultsSplit = root.querySelector<FakeElement>(".lmi-results-split")!;
  assert.ok(lmiResultsSplit !== null);
  assert.ok(lmiResultsSplit.querySelector("#lmi-certificate-panel") !== null);
  assert.ok(lmiResultsSplit.querySelector("#lmi-certificate-dims") !== null);
  assert.ok(lmiResultsSplit.querySelector("#lmi-spectrum-chart-slot") !== null);
  assert.ok(lmiResultsSplit.querySelector("#lmi-spectrum-table-slot") !== null);

  app.destroy();
});

test("WP-PHASE6-01-F8-UX-HYGIENE-P0P1: cabeçalhos limpos, badge espaçado, Workspace Dock amigável, step pills sem duplicação, checkboxes 20px, ticks near-zero e certificado LMI bilíngue preservando tokens", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const mockAdapter = new MockWorkerAdapter();
  const origExecute = mockAdapter.execute.bind(mockAdapter);
  mockAdapter.execute = async (req, opts) => {
    if (req.operation === "optimization.solve") {
      return {
        api_version: req.api_version,
        request_id: req.request_id,
        project_id: req.project_id,
        project_revision: req.project_revision,
        status: "success" as const,
        result: {
          solver_status: "optimal",
          audit_feasibility: "strictly_feasible",
          certificate_status: "validated_dual",
          conditioning: { status: "well_conditioned", condition_number: 8.5 },
          controller_validity: "verified_closed_loop",
          objective: 1.25,
          block_min_eigs: [0.42, 0.18],
          variables: {
            Q: { shape: [2, 2], dtype: "float64", order: "C", data: [2, 0, 0, 2] },
            Y: { shape: [1, 2], dtype: "float64", order: "C", data: [-2, -4] },
          },
        },
        assumptions: {},
        diagnostics: {
          numeric_status: "ok" as const,
          warnings_count: 0,
          condition_estimates: {},
          residuals: {},
          timings_ms: { total: 2.0 },
        },
        warnings: [],
        error: null,
        provenance: { algorithm: "mock.sdp", lib_versions: {} },
      };
    }
    return origExecute(req, opts);
  };

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: mockAdapter,
    project_id: "proj-ux-hygiene",
  });
  await app.client.init();

  // 1. Engine status badge preserves 'Motor: ready' and separates dot & text cleanly
  const engineBadge = root.querySelector<FakeElement>("#engine-status-badge")!;
  assert.ok(engineBadge.textContent.includes("Motor: ready"));
  assert.ok(engineBadge.querySelector(".status-dot") !== null);
  assert.ok(engineBadge.querySelector(".status-badge-text") !== null);

  // 1b. Tab heading drops (F2)/(F3)/(F4)/(F5)/(F6) suffixes across all 6 tabs
  const tabHeading = root.querySelector<FakeElement>("#controllab-tab-heading")!;
  const expectedHeadings: Array<[Parameters<typeof app.shell.switchTab>[0], string]> = [
    ["identification", "1. Identificação de Sistemas"],
    ["siso_frequency", "2. Frequência SISO"],
    ["statespace", "3. Espaço de Estados"],
    ["mimo_frequency", "4. Frequência MIMO"],
    ["fuzzy_ts", "5. Controle Fuzzy, TS e ANFIS"],
    ["optimization_lmi", "6. LMIs, SDPs e Síntese Robusta"],
  ];
  for (const [tabId, expected] of expectedHeadings) {
    app.shell.switchTab(tabId);
    assert.equal(tabHeading.textContent, expected);
    assert.ok(!/\(F[1-9]\)/.test(tabHeading.textContent));
  }

  // 2. Workspace Dock friendly display names + technical ID caption preserved + select class
  assert.equal(formatDockObjectDisplayName("plant-double-integrator"), "Integrador Duplo 1/s²");
  assert.equal(formatDockObjectDisplayName("ctrl-sf-proj-1-r2"), "Controlador LQR");
  const dockSelect = root.querySelector<FakeElement>("#dock-example-select")!;
  assert.ok(dockSelect.className.split(/\s+/).includes("dock-preset-select"));
  const dockContent = root.querySelector<FakeElement>("#workspace-dock-content")!;
  assert.ok(dockContent.textContent.includes("Integrador Duplo 1/s²"));
  assert.ok(dockContent.textContent.includes("plant-double-integrator"));

  app.shell.switchTab("statespace");
  await app.shell.getLqrWorkspace().commitCurrentDesign();
  const ctrlGroup = root.querySelector<FakeElement>('[data-dock-group="controllers"]')!;
  assert.ok(ctrlGroup.textContent.includes("Controlador LQR"));

  // 4. Aba 1 pipeline step pills have no duplicated numbering (no '1. Dados', '2. Estimação', '3. Comparar')
  const pipelineBar = root.querySelector<FakeElement>("#id-pipeline-bar")!;
  const stepNums = pipelineBar
    .querySelectorAll<FakeElement>(".step-num")
    .map((el) => el.textContent.trim());
  const stepLabels = pipelineBar
    .querySelectorAll<FakeElement>(".step-label")
    .map((el) => el.textContent.trim());
  assert.deepEqual(stepNums, ["1", "2", "3"]);
  assert.deepEqual(stepLabels, [
    "Dados & Partição",
    "Estimação ARX / Subespaços",
    "Comparar & Promover",
  ]);

  // 5a. Chart tick clamping near zero (no 2.2204e-16) and clean SVG heading without [numeric_verified]
  const pzSvg = renderPoleZeroSvg(
    {
      kind: "pole_zero",
      chart_id: "pz-near-zero",
      title: "Mapa de Polos e Zeros",
      dt: null,
      model_revision: 1,
      project_revision: 1,
      provenance: null,
      series_semantics: "numeric_verified",
      feedback_sign: "negative",
      units: { x_axis: "Re(λ)", y_axis: "Im(λ)" },
      open_loop_poles: { real: [-1, 1 + 4.440892098500626e-16], imag: [-0.5, 0.5 + 4.440892098500626e-16] },
      committed_closed_loop_poles: null,
      preview_poles: null,
      zeros: null,
      overlays: [],
    },
    { decimals: 4 },
  );
  assert.ok(!pzSvg.includes("e-16"), `Axis tick leaked floating-point dust: ${pzSvg}`);
  assert.ok(!pzSvg.includes("[numeric_verified]"), "Raw [numeric_verified] should not appear in SVG heading");
  assert.ok(pzSvg.includes('data-series-semantics="numeric_verified"'));

  const timeModel = buildTimeResponseChartModel({
    dt: null,
    t: [0, 1],
    y: [[-1], [1 + 4.440892098500626e-16]],
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    series_semantics: "numeric_verified",
  });
  const timeSvg = renderTimeResponseSvg(timeModel, { decimals: 4 });
  assert.ok(!timeSvg.includes("e-16"));
  assert.ok(!timeSvg.includes("[numeric_verified]"));
  const csv = exportChartToCsv(timeModel);
  assert.ok(csv.includes("# series_semantics=numeric_verified"));

  // 5b. Calm button hierarchy in Aba 3
  const cancelBtn = root.querySelector<FakeElement>('#btn-lqr-cancel[data-action="cancel-lqr"]')!;
  assert.ok(cancelBtn !== null);
  assert.ok(cancelBtn.className.split(/\s+/).includes("btn-danger"));
  assert.ok(cancelBtn.className.split(/\s+/).includes("btn-danger-outline"));
  const resetWorkerBtn = root.querySelector<FakeElement>("#btn-reset-worker")!;
  assert.ok(resetWorkerBtn.className.split(/\s+/).includes("btn-subtle"));

  // 6. Aba 4 MIMO 6 checkboxes inside .mimo-toggle-label
  for (const id of [
    "#mimo-toggle-G",
    "#mimo-toggle-S",
    "#mimo-toggle-T",
    "#mimo-toggle-KS",
    "#mimo-cl-use-decoupler",
    "#mimo-cl-use-selected-ctrl",
  ]) {
    const cb = root.querySelector<FakeElement>(id);
    assert.ok(cb !== null, `Missing MIMO checkbox ${id}`);
    assert.ok(
      cb.parentNode?.className.split(/\s+/).includes("mimo-toggle-label"),
      `Checkbox ${id} should be enclosed in .mimo-toggle-label`,
    );
  }

  // 7. Aba 5 ANFIS heading free of raw RPC op name
  const anfisCard = root.querySelector<FakeElement>("#fuzzy-anfis-card")!;
  const anfisH4 = anfisCard.querySelector<FakeElement>("h4")!;
  assert.equal(anfisH4.textContent, "Treinamento Neuro-Fuzzy ANFIS");

  // 8. Aba 6 LMI headings, checkboxes without .touch-control, and certificate tokens preserved
  app.shell.switchTab("optimization_lmi");
  const lmiPanel = root.querySelector<FakeElement>("#lmi-workspace-panel")!;
  assert.equal(lmiPanel.querySelector<FakeElement>("h3")!.textContent, "LMIs, SDPs & Síntese Robusta");
  assert.equal(
    root.querySelector<FakeElement>("#lmi-system-characterization-card")!.querySelector<FakeElement>("h4")!.textContent,
    "Caracterização do Sistema & Conjuntos de Índices",
  );
  assert.equal(
    root.querySelector<FakeElement>("#lmi-certificate-panel")!.querySelector<FakeElement>("h4")!.textContent,
    "Certificado de Auditoria Independente (5 Dimensões)",
  );
  for (const id of ["#new-ss-enable-w", "#new-ss-enable-z"]) {
    const cb = root.querySelector<FakeElement>(id)!;
    assert.ok(cb !== null, `Missing generalized checkbox ${id}`);
    assert.equal(cb.className.split(/\s+/).includes("touch-control"), false);
    assert.ok(cb.parentNode?.className.split(/\s+/).includes("lmi-check-label"));
  }

  const codeEditor = root.querySelector<FakeElement>("#lmi-code-editor")!;
  codeEditor.value = [
    "var Q sym(n)",
    "var Y rect(m, n)",
    "Q >= 1e-4 * I",
    "A*Q + Q*A' + B*Y + Y'*B' <= -1e-4 * I",
  ].join("\n");
  codeEditor.dispatchEvent("input");

  root.querySelector<FakeElement>('[data-action="lmi-solve"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 80));
  const certPanel = root.querySelector<FakeElement>("#lmi-certificate-panel")!;
  assert.ok(certPanel.textContent.includes("Dual Validado"));
  assert.ok(certPanel.textContent.includes("validated_dual"));
  assert.ok(certPanel.textContent.includes("Estritamente Factível"));
  assert.ok(certPanel.textContent.includes("strictly_feasible"));

  // CSS rules verification (desktop compact header, dock select containment, collapsed RPC drawer, empty chart hide, checkbox 20px, import input 44px)
  const cssPath = fileURLToPath(new URL("../../../web/app/styles.css", import.meta.url));
  const css = readFileSync(cssPath, "utf8");
  assert.ok(css.includes("@media (min-width: 1100px)"));
  assert.ok(css.includes(".badge.status-badge"));
  assert.ok(css.includes(".dock-preset-select"));
  assert.ok(css.includes("#controllab-tools-slot.advanced-rpc-drawer:not(.expanded)"));
  assert.ok(css.includes("max-height: 44px;"));
  assert.ok(css.includes("#identification-workspace-panel .chart-container:empty"));
  assert.ok(css.includes("#siso-workspace-panel .chart-container:empty"));
  assert.ok(css.includes("#controllab-charts-panel .chart-container:empty"));
  assert.ok(!/(?:^|\n)\s*\.chart-container:empty\s*\{/.test(css));
  assert.ok(css.includes('input[type="checkbox"].touch-control'));
  assert.ok(css.includes("#lmi-import-dsl-input"));

  app.destroy();
});

test("WP-PHASE8-01-F8-WORKSPACE-SYSTEM-EDITOR: Create/Edit 5 modos (TF, SS Generalizado, Politópico 10 vértices, TS não medida), Editar/→LMIs no Dock, exemplos rápidos e atalhos Aba 3/Aba 6", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-phase8-ws-editor",
  });
  await app.client.init();

  const modal = root.querySelector<FakeElement>("#workspace-new-object-modal")!;
  const typed = app.shell.getTypedWorkspace();

  // 1. Verify all 5 mode buttons exist in modal
  for (const btnId of [
    "#btn-new-mode-tf",
    "#btn-new-mode-ss",
    "#btn-new-mode-polytopic",
    "#btn-new-mode-ts",
    "#btn-new-mode-csv",
  ]) {
    assert.ok(root.querySelector(btnId) !== null, `Missing modal mode button ${btnId}`);
  }

  // 2. Create and Edit a TransferFunction (rev 1 -> rev 2)
  root.querySelector("#btn-open-new-object-modal")!.dispatchEvent("click");
  root.querySelector<FakeElement>("#new-tf-id")!.value = "tf-edit-demo";
  root.querySelector<FakeElement>("#new-tf-num")!.value = "3";
  root.querySelector<FakeElement>("#new-tf-den")!.value = "1, 2";
  root.querySelector<FakeElement>("#new-tf-dt")!.value = "";
  root.querySelector("#btn-new-tf-submit")!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const tfRev1 = typed.listRegisteredObjects(["TransferFunction"]).find((o) => o.id === "tf-edit-demo")!;
  assert.ok(tfRev1 !== undefined);
  assert.equal(tfRev1.revision, 1);

  // Edit via Dock 'Editar' button
  const editTfBtn = root.querySelector<FakeElement>(
    `[data-action="dock-edit-plant"][data-object-key="${tfRev1.key}"]`,
  )!;
  assert.ok(editTfBtn !== null);
  editTfBtn.dispatchEvent("click");
  assert.equal(modal.hasAttribute("hidden"), false);
  assert.equal(root.querySelector<FakeElement>("#new-tf-id")!.value, "tf-edit-demo");
  assert.equal(root.querySelector<FakeElement>("#new-tf-num")!.value, "3");
  root.querySelector<FakeElement>("#new-tf-num")!.value = "7";
  root.querySelector("#btn-new-tf-submit")!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const tfRev2 = typed
    .listRegisteredObjects(["TransferFunction"])
    .find((o) => o.id === "tf-edit-demo" && o.revision === 2);
  assert.ok(tfRev2 !== undefined, "Editar TF deve registrar revisão 2 preservando ID");

  // 3. Create Generalized StateSpace with Bw, Dyw, Cz, Dzu, Dzw stored in provenance.generalized_channels
  root.querySelector("#btn-open-new-object-modal")!.dispatchEvent("click");
  root.querySelector("#btn-new-mode-ss")!.dispatchEvent("click");
  root.querySelector<FakeElement>("#new-ss-id")!.value = "ss-gen-demo";
  root.querySelector<FakeElement>("#new-ss-a")!.value = "[[0, 1], [-2, -1]]";
  root.querySelector<FakeElement>("#new-ss-b")!.value = "[[0], [1]]";
  root.querySelector<FakeElement>("#new-ss-c")!.value = "[[1, 0]]";
  root.querySelector<FakeElement>("#new-ss-d")!.value = "[[0]]";
  const cbW = root.querySelector<FakeElement>("#new-ss-enable-w")!;
  const cbZ = root.querySelector<FakeElement>("#new-ss-enable-z")!;
  cbW.checked = true;
  cbW.dispatchEvent("change");
  cbZ.checked = true;
  cbZ.dispatchEvent("change");
  assert.equal(root.querySelector("#new-ss-gen-panel")!.hasAttribute("hidden"), false);
  root.querySelector<FakeElement>("#new-ss-bw")!.value = "[[0], [2]]";
  root.querySelector<FakeElement>("#new-ss-dyw")!.value = "[[0]]";
  root.querySelector<FakeElement>("#new-ss-cz")!.value = "[[1, 0], [0, 0.5]]";
  root.querySelector<FakeElement>("#new-ss-dzu")!.value = "[[0], [0.2]]";
  root.querySelector<FakeElement>("#new-ss-dzw")!.value = "[[0], [0]]";
  root.querySelector("#btn-new-ss-submit")!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const ssGen = typed.listRegisteredObjects(["StateSpace"]).find((o) => o.id === "ss-gen-demo")!;
  assert.ok(ssGen !== undefined);
  assert.equal("Bw" in (ssGen.value.matrices as Record<string, unknown>), false, "matrices não pode conter Bw");
  const provGen = (ssGen.value.provenance as Record<string, unknown>).generalized_channels as Record<string, unknown>;
  assert.equal(provGen.enable_w, true);
  assert.equal(provGen.enable_z, true);
  assert.deepEqual(provGen.Bw, [[0], [2]]);
  assert.ok(formatDockObjectSummary(ssGen, 2).includes("Generalizada (w/z)"));

  // 4. Create Polytopic Uncertain with 10 vertices (> 8 unlimited!)
  root.querySelector("#btn-open-new-object-modal")!.dispatchEvent("click");
  root.querySelector("#btn-new-mode-polytopic")!.dispatchEvent("click");
  root.querySelector<FakeElement>("#new-poly-id")!.value = "poly-10v-demo";
  // Starts with 2 vertices -> click + Adicionar Vértice 8 times -> 10 vertices!
  for (let k = 0; k < 8; k += 1) {
    root.querySelector("#btn-new-poly-add-vertex")!.dispatchEvent("click");
  }
  assert.equal(root.querySelectorAll('[data-poly-mat="A"]').length, 10);
  root.querySelector("#btn-new-poly-gen-delta")!.dispatchEvent("click");
  root.querySelector("#btn-new-poly-submit")!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const poly10 = typed.listRegisteredObjects(["polytopic_uncertain"]).find((o) => o.id === "poly-10v-demo")!;
  assert.ok(poly10 !== undefined);
  assert.equal((poly10.value.vertices as unknown[]).length, 10);
  assert.ok(formatDockObjectSummary(poly10, 2).includes("Politópico 10 vértices"));

  // 5. Create Takagi-Sugeno with unmeasured premise & live h_i(z) convexity validation
  root.querySelector("#btn-open-new-object-modal")!.dispatchEvent("click");
  root.querySelector("#btn-new-mode-ts")!.dispatchEvent("click");
  root.querySelector<FakeElement>("#new-ts-id")!.value = "ts-unmeas-modal";
  assert.ok(root.querySelector("#new-ts-mf-validation")!.textContent.includes("Soma convexa válida"));

  // Mark premise 0 as unmeasured
  const premCb0 = root.querySelector<FakeElement>('input[data-ts-premise-field="measured"][data-ts-premise-idx="0"]')!;
  premCb0.checked = false;
  premCb0.dispatchEvent("change");
  // Add a 3rd rule (no limit) and verify
  root.querySelector("#btn-new-ts-add-rule")!.dispatchEvent("click");
  assert.equal(root.querySelectorAll('[data-ts-rule-mat="A"]').length, 3);
  // Test invalid h_1(z) -> validation flags Inválido, then restore valid
  const mf0 = root.querySelector<FakeElement>('input[data-ts-mf-field="expression"][data-ts-mf-idx="0"]')!;
  mf0.value = "z1";
  mf0.dispatchEvent("input");
  assert.ok(root.querySelector("#new-ts-mf-validation")!.textContent.includes("Inválido"));
  mf0.value = "(1 + sin(z1)) / 2";
  mf0.dispatchEvent("input");
  assert.ok(root.querySelector("#new-ts-mf-validation")!.textContent.includes("Soma convexa válida"));

  root.querySelector("#btn-new-ts-submit")!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const tsObj = typed.listRegisteredObjects(["ts_partially_observed"]).find((o) => o.id === "ts-unmeas-modal")!;
  assert.ok(tsObj !== undefined);
  assert.equal((tsObj.value.vertices as unknown[]).length, 3);
  assert.ok(formatDockObjectSummary(tsObj, 2).includes("TS 3 regras"));
  assert.ok(formatDockObjectSummary(tsObj, 2).includes("Premissa não medida"));

  // 6. Click '→ LMIs' on TS card routes to Tab 6 and selects it
  const routeLmiBtn = root.querySelector<FakeElement>(
    `[data-action="dock-route-lmi"][data-object-key="${tsObj.key}"]`,
  )!;
  assert.ok(routeLmiBtn !== null);
  routeLmiBtn.dispatchEvent("click");
  assert.equal(app.shell.getActiveTab(), "optimization_lmi");
  assert.equal(root.querySelector<FakeElement>("#lmi-workspace-system-select")!.value, tsObj.key);

  // 7. Clicking #btn-lmi-edit-system-workspace opens modal pre-populated with active TS system
  root.querySelector("#btn-lmi-edit-system-workspace")!.dispatchEvent("click");
  assert.equal(modal.hasAttribute("hidden"), false);
  assert.equal(root.querySelector<FakeElement>("#new-ts-id")!.value, "ts-unmeas-modal");
  assert.equal(root.querySelector("#new-obj-panel-ts")!.hasAttribute("hidden"), false);
  root.querySelector("#new-object-modal-close")!.dispatchEvent("click");
  assert.equal(modal.hasAttribute("hidden"), true);

  // 8. Switch to Tab 3, verify #ss-workspace-plant-bar and clicking #btn-ss-edit-plant-workspace opens modal pre-populated
  app.shell.switchTab("statespace");
  assert.ok(root.querySelector("#ss-workspace-plant-bar") !== null);
  root.querySelector("#btn-ss-edit-plant-workspace")!.dispatchEvent("click");
  assert.equal(modal.hasAttribute("hidden"), false);
  assert.equal(root.querySelector("#new-obj-panel-ss")!.hasAttribute("hidden"), false);
  assert.equal(
    root.querySelector<FakeElement>("#new-ss-id")!.value,
    app.shell.getLqrWorkspace().getPlant().id,
  );
  root.querySelector("#new-object-modal-close")!.dispatchEvent("click");

  // 9. Quick examples: polytopic_2v and ts_unmeasured_2r
  const exSelect = root.querySelector<FakeElement>("#dock-example-select")!;
  exSelect.value = "polytopic_2v";
  root.querySelector("#btn-dock-load-example")!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));
  assert.ok(typed.listRegisteredObjects(["polytopic_uncertain"]).some((o) => o.id === "poly-2v-demo"));

  exSelect.value = "ts_unmeasured_2r";
  root.querySelector("#btn-dock-load-example")!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));
  assert.ok(
    typed.listRegisteredObjects(["ts_partially_observed"]).some((o) => o.id === "ts-unmeasured-2r-demo"),
  );

  app.destroy();
});



