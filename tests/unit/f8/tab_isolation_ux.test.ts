/**
 * Testes unitários de WP-AUDIT-FIX-F8-TAB-ISOLATION-UX (F8: f8-ui-charts)
 *
 * Verificam:
 * - Isolamento visual estrito por aba (`hidden` em blocos exclusivos de Aba 1, Aba 2, Aba 3 e gráficos)
 * - Posicionamento de `#typed-workspace-panel` abaixo dos painéis específicos da aba ativa
 * - Persistência da aba ativa via `location.hash` (`#tab=<tabId>`)
 * - Editor matricial interativo LQR (`#lqr-matrix-editor`), presets e sincronização com JSON
 * - Anotações explícitas de formato JSON e entrada simplificada em `#lqr-plant-json` / `#lqr-weights-json`
 * - Construtor guiado de `TransferFunction` (`#typed-tf-builder`)
 */

import test from "node:test";
import assert from "node:assert/strict";

import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";

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

  public dispatchEvent(type: string | { type: string; target?: unknown }): boolean {
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
  if (s.startsWith("#")) {
    return el.id === s.slice(1);
  }
  if (s.startsWith(".")) {
    const cls = s.slice(1);
    return el.className.split(/\s+/).includes(cls);
  }
  // Support compound attribute selectors like input[data-matrix="A"][data-row="0"][data-col="0"]
  const tagMatch = /^([a-zA-Z0-9_-]+)/.exec(s);
  if (tagMatch && el.tagName !== tagMatch[1].toUpperCase()) {
    return false;
  }
  const attrRe = /\[([^\]=]+)(?:="([^"]*)")?\]/g;
  let m: RegExpExecArray | null;
  let matchedAnyAttr = false;
  while ((m = attrRe.exec(s)) !== null) {
    matchedAnyAttr = true;
    const attrName = m[1];
    const attrVal = m[2];
    const actual = el.getAttribute(attrName);
    if (attrVal === undefined) {
      if (actual === null) return false;
    } else if (actual !== attrVal) {
      return false;
    }
  }
  if (matchedAnyAttr || tagMatch) {
    return true;
  }
  return false;
}

class FakeDocument {
  public activeElement: FakeElement | null = null;
  public body: FakeElement;

  constructor() {
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
  let match: RegExpExecArray | null;
  while ((match = tokenRe.exec(html)) !== null) {
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
    if (parent === rootParent) {
      topNodes.push(el);
    } else {
      parent.children.push(el);
    }
    if (!selfClose) {
      stack.push(el);
    }
  }
  return topNodes;
}

test("WP-AUDIT-FIX-F8-TAB-ISOLATION-UX: isolamento estrito por aba e ordem de #typed-workspace-panel", () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-tab-isolation",
  });

  const lqrBar = root.querySelector(".lqr-interactive-bar")!;
  const matrixEditor = root.querySelector("#lqr-matrix-editor")!;
  const jsonAdvanced = root.querySelector("#lqr-json-advanced")!;
  const pvmOptions = root.querySelector("#pvm-export-options")!;
  const kDisplay = root.querySelector("#lqr-k-display")!;
  const lqrDiag = root.querySelector("#lqr-diagnostics-panel")!;
  const timeChart = root.querySelector("#time-chart-slot")!;
  const timeTableDetails = root.querySelector("#time-table-details")!;
  const expCompare = root.querySelector("#experiments-compare-panel")!;
  const pzChart = root.querySelector("#pz-chart-slot")!;
  const pzTableDetails = root.querySelector("#pz-table-details")!;
  const chartsPanel = root.querySelector("#controllab-charts-panel")!;
  const idPanel = root.querySelector("#identification-workspace-panel")!;
  const sisoPanel = root.querySelector("#siso-workspace-panel")!;
  const typedPanel = root.querySelector("#typed-workspace-panel")!;

  // 1. Default tab: statespace
  assert.equal(app.shell.getActiveTab(), "statespace");
  for (const el of [
    lqrBar,
    matrixEditor,
    jsonAdvanced,
    pvmOptions,
    kDisplay,
    lqrDiag,
    timeChart,
    timeTableDetails,
    expCompare,
    pzChart,
    pzTableDetails,
    chartsPanel,
    typedPanel,
  ]) {
    assert.equal(el.hasAttribute("hidden"), false, `${el.id || el.className} deve estar visível em statespace`);
  }
  assert.equal(idPanel.hasAttribute("hidden"), true);
  assert.equal(sisoPanel.hasAttribute("hidden"), true);

  // 2. Switch to identification
  app.shell.switchTab("identification");
  assert.equal(idPanel.hasAttribute("hidden"), false);
  assert.equal(pzChart.hasAttribute("hidden"), false);
  assert.equal(pzTableDetails.hasAttribute("hidden"), false);
  assert.equal(chartsPanel.hasAttribute("hidden"), false);
  assert.equal(typedPanel.hasAttribute("hidden"), false);
  for (const el of [
    lqrBar,
    matrixEditor,
    jsonAdvanced,
    pvmOptions,
    kDisplay,
    lqrDiag,
    timeChart,
    timeTableDetails,
    expCompare,
    sisoPanel,
  ]) {
    assert.equal(el.hasAttribute("hidden"), true, `${el.id || el.className} deve estar oculto em identification`);
  }

  // 3. Switch to siso_frequency
  app.shell.switchTab("siso_frequency");
  assert.equal(sisoPanel.hasAttribute("hidden"), false);
  assert.equal(typedPanel.hasAttribute("hidden"), false);
  for (const el of [
    lqrBar,
    matrixEditor,
    jsonAdvanced,
    pvmOptions,
    kDisplay,
    lqrDiag,
    timeChart,
    timeTableDetails,
    expCompare,
    pzChart,
    pzTableDetails,
    chartsPanel,
    idPanel,
  ]) {
    assert.equal(el.hasAttribute("hidden"), true, `${el.id || el.className} deve estar oculto em siso_frequency`);
  }

  // 4. Switch to optimization_lmi -> no charts panel, no LQR, no ID, no SISO
  app.shell.switchTab("optimization_lmi");
  assert.equal(chartsPanel.hasAttribute("hidden"), true);
  assert.equal(idPanel.hasAttribute("hidden"), true);
  assert.equal(sisoPanel.hasAttribute("hidden"), true);
  assert.equal(lqrBar.hasAttribute("hidden"), true);
  assert.equal(typedPanel.hasAttribute("hidden"), false);

  // 5. Verify DOM order: #typed-workspace-panel appears AFTER tab-specific panels
  const leftCard = root.querySelector("#controllab-main")!.children[0];
  const sectionIds = leftCard.children.map((c) => c.id).filter(Boolean);
  assert.ok(
    sectionIds.indexOf("identification-workspace-panel") < sectionIds.indexOf("typed-workspace-panel"),
    "identification-workspace-panel deve vir antes de typed-workspace-panel",
  );
  assert.ok(
    sectionIds.indexOf("siso-workspace-panel") < sectionIds.indexOf("typed-workspace-panel"),
    "siso-workspace-panel deve vir antes de typed-workspace-panel",
  );
  assert.ok(
    sectionIds.indexOf("statespace-workspace-panel") < sectionIds.indexOf("typed-workspace-panel"),
    "statespace-workspace-panel deve vir antes de typed-workspace-panel",
  );

  app.destroy();
});

test("WP-AUDIT-FIX-F8-TAB-ISOLATION-UX: persistência da aba ativa via location.hash (#tab=...)", () => {
  const prevLocation = (globalThis as Record<string, unknown>).location;
  const prevHistory = (globalThis as Record<string, unknown>).history;
  const replacedUrls: string[] = [];

  try {
    (globalThis as Record<string, unknown>).location = { hash: "#tab=identification" };
    (globalThis as Record<string, unknown>).history = {
      replaceState: (_state: unknown, _title: string, url: string) => {
        replacedUrls.push(url);
      },
    };

    const doc = new FakeDocument();
    const root = doc.createElement("div");
    const app = mountControlLabApp(root as unknown as HTMLElement, {
      client: new MockWorkerAdapter(),
      project_id: "proj-hash-persist",
    });

    assert.equal(app.shell.getActiveTab(), "identification");
    assert.equal(root.querySelector("#identification-workspace-panel")!.hasAttribute("hidden"), false);

    app.shell.switchTab("siso_frequency");
    assert.ok(replacedUrls.includes("#tab=siso_frequency"));
    app.destroy();

    // Invalid hash falls back to statespace
    (globalThis as Record<string, unknown>).location = { hash: "#tab=nao_existe" };
    const root2 = doc.createElement("div");
    const app2 = mountControlLabApp(root2 as unknown as HTMLElement, {
      client: new MockWorkerAdapter(),
      project_id: "proj-hash-fallback",
    });
    assert.equal(app2.shell.getActiveTab(), "statespace");
    app2.destroy();
  } finally {
    if (prevLocation === undefined) delete (globalThis as Record<string, unknown>).location;
    else (globalThis as Record<string, unknown>).location = prevLocation;
    if (prevHistory === undefined) delete (globalThis as Record<string, unknown>).history;
    else (globalThis as Record<string, unknown>).history = prevHistory;
  }
});

test("WP-AUDIT-FIX-F8-TAB-ISOLATION-UX: editor matricial LQR, presets, hints JSON e construtor TransferFunction", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-matrix-tf-ux",
  });

  // 1. Preset Massa-Mola-Amortecedor
  const presetSelect = root.querySelector<FakeElement>("#lqr-preset-select")!;
  presetSelect.value = "mass_spring_damper";
  root.querySelector("#btn-lqr-apply-preset")!.dispatchEvent("click");

  const plantAfterPreset = app.shell.getLqrWorkspace().getPlant();
  assert.deepEqual(plantAfterPreset.matrices.A.data, [0, 1, -2, -0.5]);
  assert.deepEqual(app.shell.getLqrWorkspace().getWeights().Q.data, [4, 0, 0, 1]);
  assert.ok(root.querySelector<FakeElement>("#lqr-plant-json")!.value.includes("-0.5"));

  // 2. Edit matrix cell directly and apply
  const a00 = root.querySelector<FakeElement>('input[data-matrix="A"][data-row="0"][data-col="0"]')!;
  a00.value = "-0.25";
  root.querySelector("#btn-lqr-apply-matrices")!.dispatchEvent("click");
  assert.equal(app.shell.getLqrWorkspace().getPlant().matrices.A.data[0], -0.25);

  // 3. Resize dimension n -> 3
  const dimN = root.querySelector<FakeElement>("#lqr-dim-n")!;
  dimN.value = "3";
  dimN.dispatchEvent("change");
  assert.ok(root.querySelector('input[data-matrix="A"][data-row="2"][data-col="2"]') !== null);

  // 4. Simplified JSON input in #lqr-plant-json and #lqr-weights-json
  const plantJsonEl = root.querySelector<FakeElement>("#lqr-plant-json")!;
  plantJsonEl.value = JSON.stringify({
    A: [[0, 1], [-1, -1]],
    B: [[0], [1]],
    C: [[1, 0]],
    D: [[0]],
    dt: null,
  });
  root.querySelector("#btn-apply-plant")!.dispatchEvent("click");
  assert.deepEqual(app.shell.getLqrWorkspace().getPlant().matrices.A.data, [0, 1, -1, -1]);

  const weightsJsonEl = root.querySelector<FakeElement>("#lqr-weights-json")!;
  weightsJsonEl.value = JSON.stringify({ Q: [[5, 0], [0, 2]], R: [[0.5]], x0: [2, 0] });
  root.querySelector("#btn-apply-weights")!.dispatchEvent("click");
  assert.deepEqual(app.shell.getLqrWorkspace().getWeights().Q.data, [5, 0, 0, 2]);

  // 5. Guided TransferFunction builder
  root.querySelector<FakeElement>("#typed-tf-id")!.value = "tf-second-order";
  root.querySelector<FakeElement>("#typed-tf-num")!.value = "2, 1";
  root.querySelector<FakeElement>("#typed-tf-den")!.value = "1, 3, 2";
  root.querySelector<FakeElement>("#typed-tf-dt")!.value = "";
  root.querySelector("#btn-register-tf-builder")!.dispatchEvent("click");

  await new Promise((r) => setTimeout(r, 30));

  const registered = app.shell.getTypedWorkspace().listRegisteredObjects();
  const tfObj = registered.find((o) => o.id === "tf-second-order");
  assert.ok(tfObj !== undefined, "TransferFunction criada pelo construtor guiado deve estar registrada");
  assert.equal(tfObj.kind, "TransferFunction");
  assert.ok(root.querySelector<FakeElement>("#typed-object-json")!.value.includes("tf-second-order"));

  // 6. Verify JSON format hints exist
  assert.ok(root.querySelectorAll(".json-format-hint").length >= 3);
  assert.ok(root.innerHTML.includes("Formato esperado"));
  assert.ok(root.innerHTML.includes("Exemplos de JSON canônico"));

  app.destroy();
});
