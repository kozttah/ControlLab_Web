/**
 * Testes unitários de WP-AUDIT-FIX-F8-MODERN-UI-CHART-EXPORT (F8: f8-ui-charts)
 *
 * Verificam:
 * - Presença e estado dos botões de exportação SVG e PNG nos slots de gráficos
 * - Serialização SVG válida com xmlns="http://www.w3.org/2000/svg"
 * - Bloqueio de exportação SVG/PNG no LQR durante Fast-Preview (governança R-23)
 * - Classes de layout responsivo (.single-main-col, .workspace-two-col, subcards) e hierarquia de botões
 */

import test from "node:test";
import assert from "node:assert/strict";

import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import {
  getChartExportFilename,
  serializeSvgForExport,
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
  public style: Record<string, string> = {};
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
  if (s.startsWith("#")) return el.id === s.slice(1);
  if (s.startsWith(".")) return el.className.split(/\s+/).includes(s.slice(1));
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
  return matchedAnyAttr || Boolean(tagMatch);
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
    if (parent === rootParent) topNodes.push(el);
    else parent.children.push(el);
    if (!selfClose) stack.push(el);
  }
  return topNodes;
}

test("WP-AUDIT-FIX-F8-MODERN-UI-CHART-EXPORT: layout moderno, hierarquia de botões, single-main-col e subcards", () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-modern-ui",
  });

  const mainEl = root.querySelector("#controllab-main")!;
  assert.equal(mainEl.className.split(/\s+/).includes("single-main-col"), false);

  // Header brand & theme label
  assert.ok(root.querySelector(".brand-mark") !== null);
  assert.ok(root.innerHTML.includes("∿"));
  const themeBtn = root.querySelector("#theme-toggle-btn")!;
  assert.equal(themeBtn.textContent, "Tema: Claro AA");
  themeBtn.dispatchEvent("click");
  assert.equal(themeBtn.textContent, "Tema: Alto Contraste");

  // Button hierarchy
  assert.ok(root.querySelectorAll(".btn-primary").length >= 5);
  assert.ok(root.querySelectorAll(".btn-secondary").length >= 10);
  assert.ok(root.querySelectorAll(".btn-danger").length >= 1);
  assert.ok(root.querySelectorAll(".btn-small").length >= 16);

  // Subcards & 2-col internal grids
  assert.ok(root.querySelector(".lqr-action-card") !== null);
  assert.ok(root.querySelector(".lqr-export-card") !== null);
  assert.ok(root.querySelectorAll(".typed-subcard").length === 3);
  assert.ok(root.querySelector(".ident-workbench-stack") !== null);
  assert.ok(root.querySelector(".ss-workbench-stack") !== null);
  assert.ok(root.querySelector(".siso-workbench-stack") !== null);

  // Switching to siso_frequency activates .single-main-col
  app.shell.switchTab("siso_frequency");
  assert.equal(mainEl.className.split(/\s+/).includes("single-main-col"), true);

  // Switching to identification deactivates .single-main-col (charts panel visible)
  app.shell.switchTab("identification");
  assert.equal(mainEl.className.split(/\s+/).includes("single-main-col"), false);

  app.destroy();
});

test("WP-AUDIT-FIX-F8-MODERN-UI-CHART-EXPORT: serialização SVG e bloqueio R-23 em Fast-Preview no LQR", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-chart-export",
  });

  await app.client.init();
  // Commit initial LQR so pz-chart-slot and time-chart-slot have SVGs and export is allowed
  await app.shell.getLqrWorkspace().commitCurrentDesign();

  const pzBar = root.querySelector('[data-export-bar-for="pz-chart-slot"]')!;
  const timeBar = root.querySelector('[data-export-bar-for="time-chart-slot"]')!;
  assert.equal(pzBar.hasAttribute("hidden"), false);
  const hasTimeSvg = serializeSvgForExport(root.querySelector("#time-chart-slot") as unknown as Element) !== null;
  assert.equal(timeBar.hasAttribute("hidden"), !hasTimeSvg);

  const pzSvgBtn = pzBar.querySelector('[data-action="export-chart-svg"]')!;
  const pzPngBtn = pzBar.querySelector('[data-action="export-chart-png"]')!;
  assert.equal(pzSvgBtn.disabled, false);
  assert.equal(pzPngBtn.disabled, false);

  // Verify SVG serialization from slot
  const pzSlot = root.querySelector("#pz-chart-slot")!;
  const svgMarkup = serializeSvgForExport(pzSlot as unknown as Element);
  assert.ok(svgMarkup !== null);
  assert.ok(svgMarkup.startsWith('<svg xmlns="http://www.w3.org/2000/svg"'));
  assert.equal(getChartExportFilename("pz-chart-slot", "svg"), "controllab-pole-zero.svg");
  assert.equal(getChartExportFilename("siso-bode-chart-slot", "png"), "controllab-bode.png");
  assert.equal(getChartExportFilename("id-response-chart-slot", "svg"), "controllab-id-response.svg");

  // Enter Fast-Preview -> R-23 must disable and block LQR chart SVG/PNG export
  app.shell.getLqrWorkspace().pointerDown("lqr-q-slider");
  app.shell.getLqrWorkspace().pointerMove({ qScale: 2.0 });

  assert.equal(pzSvgBtn.disabled, true);
  assert.equal(pzPngBtn.disabled, true);
  assert.equal(pzSvgBtn.getAttribute("aria-disabled"), "true");
  assert.equal(pzPngBtn.getAttribute("aria-disabled"), "true");

  // Direct click invocation during Fast-Preview must be blocked and present an error alert
  pzSvgBtn.dispatchEvent("click");
  const errorSlot = root.querySelector("#controllab-error-slot")!;
  const alertEl = errorSlot.querySelector('[role="alert"]');
  assert.ok(alertEl !== null, "Exportação SVG durante Fast-Preview deve ser bloqueada pela regra R-23");

  await app.shell.getLqrWorkspace().cancelDrag();

  // Check Identification & SISO export bars exist for all slots
  for (const slotId of [
    "id-response-chart-slot",
    "id-residuals-chart-slot",
    "siso-bode-chart-slot",
    "siso-nyquist-chart-slot",
    "siso-rl-chart-slot",
    "siso-time-chart-slot",
    "pz-chart-slot",
    "time-chart-slot",
  ]) {
    const bar = root.querySelector(`[data-export-bar-for="${slotId}"]`);
    assert.ok(bar !== null, `Barra de exportação deve existir para ${slotId}`);
    assert.ok(bar.querySelector('[data-action="export-chart-svg"]') !== null);
    assert.ok(bar.querySelector('[data-action="export-chart-png"]') !== null);
  }

  app.destroy();
});
