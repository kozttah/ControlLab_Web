/**
 * Testes unitários de WP-TSMOD-04-F8-TS-MODELING-TAB-UI (F8: f8-ui-charts)
 *
 * Cobrem:
 * - Expansão para 7 abas (`ts_modeling` na posição 6, `optimization_lmi` na 7).
 * - Fluxo guiado Via 1 (Setor), Via 2 (TPMT) e Via 3 (FEMT) com presets didáticos.
 * - Gráficos SVG acessíveis (`role="img"`, `aria-label`): 1D h_r, malha 2D Delaunay,
 *   bases U vs W, scree de valores singulares e heatmap de erro off-grid.
 * - Promoção em 1 clique ao Workspace Dock + atalho "Registrar e Abrir em LMIs".
 * - Recarga de receita via `provenance.ts_derivation`.
 * - Exportação passiva de scripts Python e MATLAB (`code_executed === false`).
 * - Segurança R-21: ausência absoluta de `eval` / `new Function`.
 */

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import {
  PROJECT_TAB_IDS,
  PROJECT_TAB_METADATA,
} from "../../../web/app/tool_descriptor.ts";
import {
  buildTsPayload,
  DEFAULT_TS_FORM_PARAMS,
  extractRecipeFromProvenance,
  renderTsModelingViewHtml,
  substitutePremises,
  TS_PRESETS,
  TsModelingView,
} from "../../../web/features/views/ts_modeling_view.ts";

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

  public appendChild(child: FakeElement): FakeElement {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  public insertAdjacentElement(_pos: string, child: FakeElement): FakeElement {
    return this.appendChild(child);
  }

  public focus(): void {}
  public click(): void {
    this.dispatchEvent("click");
  }

  public querySelectorAll<T = FakeElement>(selector: string): T[] {
    const parts = selector.split(",").map((s) => s.trim()).filter(Boolean);
    const matches: FakeElement[] = [];
    const visit = (node: FakeElement): void => {
      for (const child of node.children) {
        if (parts.some((p) => matchesSelector(child, p))) {
          matches.push(child);
        }
        visit(child);
      }
    };
    visit(this);
    return matches as unknown as T[];
  }

  public querySelector<T = FakeElement>(selector: string): T | null {
    return this.querySelectorAll<T>(selector)[0] ?? null;
  }
}

function matchesSelector(el: FakeElement, selector: string): boolean {
  if (selector.startsWith("#")) return el.id === selector.slice(1);
  if (selector.startsWith(".")) return el.className.split(/\s+/).includes(selector.slice(1));
  if (selector.startsWith("[") && selector.endsWith("]")) {
    const inner = selector.slice(1, -1);
    const eq = inner.indexOf("=");
    if (eq === -1) return el.hasAttribute(inner);
    const k = inner.slice(0, eq);
    const v = inner.slice(eq + 1).replace(/^["']|["']$/g, "");
    return el.getAttribute(k) === v;
  }
  return el.tagName.toLowerCase() === selector.toLowerCase();
}

function parseFakeHtml(html: string, doc: FakeDocument, rootParent: FakeElement): FakeElement[] {
  const stack: FakeElement[] = [rootParent];
  const topChildren: FakeElement[] = [];
  const tokenRe = /<(\/?)([a-zA-Z0-9-]+)([^>]*)>|([^<]+)/g;
  const selfClosing = new Set(["input", "br", "hr", "img", "meta", "link"]);
  let m: RegExpExecArray | null;
  while ((m = tokenRe.exec(html)) !== null) {
    if (m[4]) {
      const parent = stack[stack.length - 1];
      if (parent && parent !== rootParent) {
        const txt = m[4].trim();
        if (txt) parent.textContent = (parent.textContent ? `${parent.textContent} ` : "") + txt;
      }
      continue;
    }
    const isClose = m[1] === "/";
    const tag = m[2].toLowerCase();
    const attrsStr = m[3] ?? "";
    if (isClose) {
      if (stack.length > 1 && stack[stack.length - 1].tagName.toLowerCase() === tag) {
        stack.pop();
      }
      continue;
    }
    const el = new FakeElement(tag, doc);
    const attrRe = /([a-zA-Z0-9_:-]+)(?:="([^"]*)")?/g;
    let am: RegExpExecArray | null;
    while ((am = attrRe.exec(attrsStr)) !== null) {
      el.setAttribute(am[1], am[2] ?? "");
    }
    const parent = stack[stack.length - 1];
    if (parent === rootParent) {
      el.parentNode = rootParent;
      topChildren.push(el);
    } else {
      parent.appendChild(el);
    }
    if (!attrsStr.endsWith("/") && !selfClosing.has(tag)) {
      stack.push(el);
    }
  }
  return topChildren;
}

class FakeDocument {
  public body: FakeElement;
  public activeElement: FakeElement | null = null;
  constructor() {
    this.body = new FakeElement("body", this);
  }
  public createElement(tag: string): FakeElement {
    return new FakeElement(tag, this);
  }
}

test("TS Modeling Tab: PROJECT_TAB_IDS expandido para 7 abas com ts_modeling na posição 6 e optimization_lmi na 7", () => {
  assert.equal(PROJECT_TAB_IDS.length, 7);
  assert.equal(PROJECT_TAB_IDS[4], "fuzzy_ts");
  assert.equal(PROJECT_TAB_IDS[5], "ts_modeling");
  assert.equal(PROJECT_TAB_IDS[6], "optimization_lmi");
  assert.equal(
    PROJECT_TAB_METADATA.ts_modeling.label,
    "6. Obtenção de Modelos TS (Setor, TPMT & FEMT)",
  );
  assert.equal(
    PROJECT_TAB_METADATA.optimization_lmi.label,
    "7. LMIs, SDPs e Síntese Robusta",
  );
});

test("TS Modeling Tab: presets, substituição textual de premissas e payload das 3 vias", () => {
  assert.equal(TS_PRESETS.pendulum_16.premises.length, 4);
  assert.equal(
    substitutePremises("2.0 * z1 * z2", TS_PRESETS.pendulum_16.premises),
    "2.0 * (1 / (1.0 + 0.2 * sin(x3)^2)) * (cos(x3))",
  );
  const pSector = buildTsPayload("pendulum_16", "sector", DEFAULT_TS_FORM_PARAMS);
  assert.equal((pSector.premises as unknown[]).length, 4);
  const pTpmt = buildTsPayload("nonseparable_benchmark", "tpmt", DEFAULT_TS_FORM_PARAMS);
  assert.equal(pTpmt.decomposition, "hosvd");
  assert.equal(pTpmt.hull_type, "CNO");
  const pFemt = buildTsPayload("nonseparable_benchmark", "femt", DEFAULT_TS_FORM_PARAMS);
  assert.equal(pFemt.mesh_kind, "kuhn_delaunay");
  assert.equal(pFemt.hull_type, "CNO");
});

test("T-TSMOD-07/08 UI: Via 1/2/3, gráficos SVG acessíveis, Workspace Dock, atalho LMI, recarga e exportação passiva", async () => {
  const doc = new FakeDocument();
  const root = new FakeElement("div", doc);
  doc.body.appendChild(root);

  const client = new MockWorkerAdapter();
  await client.init();

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
  });

  app.shell.switchTab("ts_modeling");
  const panel = root.querySelector<FakeElement>("#ts-modeling-workspace-panel")!;
  assert.ok(panel, "Painel da Aba 6 deve existir");
  assert.equal(panel.hasAttribute("hidden"), false, "Painel da Aba 6 deve ficar visível ao ativar ts_modeling");

  // Via 1 (Setor) — Pêndulo 4 premissas / 16 regras
  const btnAnalyze = root.querySelector<FakeElement>("#btn-ts-analyze")!;
  btnAnalyze.click();
  await new Promise((r) => setTimeout(r, 20));
  assert.ok(
    root.querySelector<FakeElement>("#ts-status")!.textContent.includes("Análise concluída: 16 regras"),
    "Análise de premissas deve atualizar status",
  );
  assert.ok(
    root.querySelector<FakeElement>("#ts-summary")!.textContent.includes("16"),
    "Resumo deve mostrar 16 regras",
  );

  const btnDerive = root.querySelector<FakeElement>("#btn-ts-derive")!;
  btnDerive.click();
  await new Promise((r) => setTimeout(r, 30));

  assert.ok(
    root.querySelector<FakeElement>("#ts-summary")!.textContent.includes("16"),
    "Resumo após derivação deve mostrar 16 regras",
  );
  const hrSlot = root.querySelector<FakeElement>("#ts-hr-chart-slot")!;
  assert.ok(hrSlot.innerHTML.includes("<svg"), "Gráfico 1D h_r deve renderizar SVG");
  assert.ok(hrSlot.innerHTML.includes('role="img"'), "SVG deve ter role=img (WCAG)");

  // Exportação passiva Python e MATLAB
  const btnPy = root.querySelector<FakeElement>("#btn-ts-export-python")!;
  btnPy.click();
  await new Promise((r) => setTimeout(r, 20));
  const modalContent = root.querySelector<FakeElement>("#export-modal-content")!;
  assert.ok(modalContent.textContent.includes("#"), "Modal deve exibir script Python passivo");

  const btnMat = root.querySelector<FakeElement>("#btn-ts-export-matlab")!;
  btnMat.click();
  await new Promise((r) => setTimeout(r, 20));
  assert.ok(
    modalContent.textContent.includes("%"),
    "Modal deve exibir script MATLAB passivo",
  );

  // Via 3 (FEMT) + Comparação TPMT vs FEMT no benchmark não separável
  const presetSel = root.querySelector<FakeElement>("#ts-preset-select")!;
  presetSel.value = "nonseparable_benchmark";
  presetSel.dispatchEvent("change");
  const viaSel = root.querySelector<FakeElement>("#ts-via-select")!;
  viaSel.value = "femt";
  viaSel.dispatchEvent("change");

  btnDerive.click();
  await new Promise((r) => setTimeout(r, 30));

  assert.ok(root.querySelector<FakeElement>("#ts-mesh-chart-slot")!.innerHTML.includes("<svg"), "Malha 2D FEMT deve renderizar SVG");
  assert.ok(root.querySelector<FakeElement>("#ts-bases-chart-slot")!.innerHTML.includes("<svg"), "Bases U vs W devem renderizar SVG");
  assert.ok(root.querySelector<FakeElement>("#ts-scree-chart-slot")!.innerHTML.includes("<svg"), "Scree plot deve renderizar SVG");
  assert.ok(root.querySelector<FakeElement>("#ts-error-heatmap-slot")!.innerHTML.includes("<svg"), "Heatmap off-grid deve renderizar SVG");

  const btnCompare = root.querySelector<FakeElement>("#btn-ts-compare")!;
  btnCompare.click();
  await new Promise((r) => setTimeout(r, 30));
  assert.ok(
    root.querySelector<FakeElement>("#ts-compare-slot")!.textContent.includes("TPMT"),
    "Comparativo TPMT vs FEMT deve ser exibido",
  );

  // Promoção em 1 clique ao Workspace Dock + atalho "Registrar e Abrir em LMIs"
  const btnRegOpen = root.querySelector<FakeElement>("#btn-ts-register-open-lmi")!;
  btnRegOpen.click();
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(app.shell.getActiveTab(), "optimization_lmi", "Atalho deve abrir a Aba 7 (LMIs)");
  assert.ok(
    app.shell.getTypedWorkspace().listRegisteredObjects(["ts_measured"]).length >= 1,
    "TSStateSpace deve ficar registrado no Workspace Dock",
  );

  // Recarga via provenance.ts_derivation
  app.shell.switchTab("ts_modeling");
  const registered = app.shell.getTypedWorkspace().listRegisteredObjects(["ts_measured"])[0];
  const recipe = extractRecipeFromProvenance(registered.value);
  assert.ok(recipe, "provenance.ts_derivation deve conter receita");
  assert.equal(recipe!.via, "femt");

  const recipeSel = root.querySelector<FakeElement>("#ts-recipe-select")!;
  recipeSel.value = registered.key;
  const btnReload = root.querySelector<FakeElement>("#btn-ts-reload-recipe")!;
  btnReload.click();
  await new Promise((r) => setTimeout(r, 20));
  assert.ok(
    root.querySelector<FakeElement>("#ts-status")!.textContent.includes("recarregada"),
    "Recarga de receita deve atualizar status",
  );
  // Referencia explicitamente renderTsModelingViewHtml / TsModelingView para cobertura de tipo
  assert.ok(renderTsModelingViewHtml().includes("ts-modeling-workspace-panel"));
  assert.equal(typeof TsModelingView, "function");
});

test("Segurança R-21: ts_modeling_view.ts e ts_modeling_charts.ts não contêm eval ou new Function", () => {
  const viewPath = fileURLToPath(new URL("../../../web/features/views/ts_modeling_view.ts", import.meta.url));
  const chartsPath = fileURLToPath(new URL("../../../web/charts/ts_modeling_charts.ts", import.meta.url));
  for (const p of [viewPath, chartsPath]) {
    const raw = fs.readFileSync(p, "utf8");
    const src = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    assert.equal(/\beval\s*\(/.test(src), false, `eval( proibido em ${p}`);
    assert.equal(/\bnew\s+Function\b/.test(src), false, `new Function proibido em ${p}`);
  }
});
