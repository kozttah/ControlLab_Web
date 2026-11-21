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

import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import { formatDockObjectSummary } from "../../../web/app/workspace_dock.ts";

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
