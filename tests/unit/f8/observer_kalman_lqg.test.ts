/**
 * Testes unitários de WP-PHASE2-A1-F8-OBSERVER-KALMAN-LQG (F8: f8-ui-charts)
 *
 * Verificam:
 * 1. Parsers de polos do observador (`parseObserverPolesInput`) e vetores (`parseNumericVectorInput`).
 * 2. Síntese Kalman + LQG (u = -K x_hat) na Aba 3 (`StatespaceView`):
 *    - Popula `#obs-results-summary` com L, K e polos λ(A - BK) e λ(A - LC).
 *    - Habilita `#btn-obs-simulate` e `#btn-obs-register-ctrl`.
 *    - Registra o `DynamicController` retornado em `typedWorkspace` e no Workspace Dock.
 * 3. Síntese Observador de Luenberger:
 *    - Faz parse de polos complexos (ex: `-3+2j, -3-2j`) e chama `statespace.design_observer`.
 * 4. Simulação `x(t)` vs `x̂(t)`:
 *    - Chama `statespace.simulate_lti` com sistema aumentado `2n × 2n` e `[x0; x̂(0)]`.
 *    - Renderiza `#obs-sim-chart-slot svg` com série sólida `x_1` e tracejada `x̂_1` + tabela acessível.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  RPC_API_VERSION,
  type RpcRequest,
  type RpcResponse,
} from "../../../web/bridge/protocol.ts";
import type {
  ControlLabEngineClient,
  ExecuteOptions,
} from "../../../web/bridge/client.ts";
import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import {
  parseNumericVectorInput,
  parseObserverPolesInput,
} from "../../../web/features/views/statespace_view.ts";

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
    if (name === "checked") this.checked = true;
  }

  public getAttribute(name: string): string | null {
    if (name === "class") return this.className || null;
    if (name === "id") return this.id || null;
    return this.attributes.get(name) ?? null;
  }

  public removeAttribute(name: string): void {
    this.attributes.delete(name);
    if (name === "disabled") this.disabled = false;
    if (name === "checked") this.checked = false;
  }

  public hasAttribute(name: string): boolean {
    return this.attributes.has(name);
  }

  public addEventListener(type: string, fn: (ev: unknown) => void): void {
    const arr = this.listeners.get(type) ?? [];
    arr.push(fn);
    this.listeners.set(type, arr);
  }

  public dispatchEvent(type: string, eventObj: Record<string, unknown> = {}): void {
    const ev = {
      type,
      target: this,
      currentTarget: this,
      preventDefault: () => {},
      ...eventObj,
    };
    for (const fn of this.listeners.get(type) ?? []) {
      fn(ev);
    }
  }

  public focus(): void {
    this.ownerDocument.activeElement = this;
  }

  public querySelector<T = FakeElement>(selector: string): T | null {
    return (this.querySelectorAll(selector)[0] as unknown as T) ?? null;
  }

  public querySelectorAll(selector: string): FakeElement[] {
    const results: FakeElement[] = [];
    const parts = selector.split(",").map((s) => s.trim()).filter(Boolean);
    const matchesSingle = (el: FakeElement, sel: string): boolean => {
      if (sel.startsWith("#")) return el.id === sel.slice(1);
      if (sel.startsWith(".")) return el.className.split(/\s+/).includes(sel.slice(1));
      const attrMatch = sel.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      if (attrMatch) {
        const attrVal = el.getAttribute(attrMatch[1]);
        if (attrMatch[2] !== undefined) return attrVal === attrMatch[2];
        return attrVal !== null;
      }
      return el.tagName === sel.toUpperCase();
    };
    const matches = (el: FakeElement): boolean =>
      parts.some((sel) => matchesSingle(el, sel));
    const walk = (node: FakeElement): void => {
      for (const child of node.children) {
        if (matches(child)) results.push(child);
        walk(child);
      }
    };
    walk(this);
    return results;
  }
}

class FakeDocument {
  public activeElement: FakeElement | null = null;
  public documentElement: FakeElement;
  public body: FakeElement;

  constructor() {
    this.documentElement = new FakeElement("html", this);
    this.body = new FakeElement("body", this);
  }

  public createElement(tagName: string): FakeElement {
    return new FakeElement(tagName, this);
  }
}

function parseFakeHtml(html: string, doc: FakeDocument, root: FakeElement): FakeElement[] {
  const stack: FakeElement[] = [root];
  const tokenRe = /<\/?([a-zA-Z0-9_-]+)([^>]*)>|([^<]+)/g;
  const selfClosing = new Set(["input", "br", "hr", "img", "meta", "link"]);
  let m: RegExpExecArray | null;
  while ((m = tokenRe.exec(html)) !== null) {
    if (m[3] !== undefined) {
      const parent = stack[stack.length - 1];
      if (parent && parent !== root) parent.appendText(m[3]);
      continue;
    }
    const tag = m[1].toLowerCase();
    const rawAttrs = m[2] ?? "";
    const isClose = m[0].startsWith("</");
    if (isClose) {
      if (stack.length > 1) stack.pop();
      continue;
    }
    const el = new FakeElement(tag, doc);
    const attrRe = /([a-zA-Z0-9_:-]+)(?:="([^"]*)")?/g;
    let am: RegExpExecArray | null;
    while ((am = attrRe.exec(rawAttrs)) !== null) {
      if (am[1] === "/") continue;
      el.setAttribute(am[1], am[2] ?? "");
    }
    const parent = stack[stack.length - 1];
    el.parentNode = parent;
    parent.children.push(el);
    if (!selfClosing.has(tag) && !rawAttrs.trim().endsWith("/")) {
      stack.push(el);
    }
  }
  return root.children;
}

function createObserverMockClient(): {
  client: ControlLabEngineClient;
  calls: Array<{ operation: string; payload: Record<string, unknown> }>;
} {
  const base = new MockWorkerAdapter();
  const calls: Array<{ operation: string; payload: Record<string, unknown> }> = [];
  const origExecute = base.execute.bind(base);

  base.execute = async (req: RpcRequest, options?: ExecuteOptions): Promise<RpcResponse> => {
    calls.push({ operation: req.operation, payload: req.payload });
    const rev = base.getCommittedRevision(req.project_id);

    if (req.operation === "statespace.design_lqg") {
      return {
        api_version: RPC_API_VERSION,
        request_id: req.request_id,
        project_id: req.project_id,
        project_revision: rev,
        status: "success",
        result: {
          K_lqr: { shape: [1, 2], dtype: "float64", order: "C", data: [1.0, 1.732] },
          L_kalman: { shape: [2, 1], dtype: "float64", order: "C", data: [2.1, 1.4] },
          regulator_poles: { real: [-0.866, -0.866], imag: [0.5, -0.5] },
          observer_poles: { real: [-1.05, -1.05], imag: [0.55, -0.55] },
          closed_loop_poles: {
            real: [-0.866, -0.866, -1.05, -1.05],
            imag: [0.5, -0.5, 0.55, -0.55],
          },
          closed_loop_matrix: {
            shape: [4, 4],
            dtype: "float64",
            order: "C",
            data: [
              0, 1, 0, 0,
              0, 0, -1.0, -1.732,
              2.1, 0, -2.1, 1,
              1.4, 0, -2.4, -1.732,
            ],
          },
          controller: {
            schema_version: "1.0.0",
            id: "lqg-ctrl-1",
            revision: 1,
            kind: "DynamicController",
            feedback_sign: "negative",
            dt: null,
            Ac: { shape: [2, 2], dtype: "float64", order: "C", data: [-2.1, 1, -2.4, -1.732] },
            Bc: { shape: [2, 1], dtype: "float64", order: "C", data: [2.1, 1.4] },
            Cc: { shape: [1, 2], dtype: "float64", order: "C", data: [1.0, 1.732] },
            Dc: { shape: [1, 1], dtype: "float64", order: "C", data: [0] },
            ports: {
              inputs: [{ name: "y", role: "y", size: 1 }],
              outputs: [{ name: "u", role: "u", size: 1 }],
            },
            initial_state: { shape: [2], dtype: "float64", order: "C", data: [0, 0] },
            interconnection_scheme: "observer_based",
            provenance: { source: "statespace.design_lqg" },
          },
        },
        assumptions: { separation_principle_verified: true, closed_loop_stable: true },
        diagnostics: {},
        warnings: [],
        provenance: {
          algorithm: "statespace.design_lqg",
          lib_versions: { control_lab: "1.0.0" },
        },
        error: null,
      };
    }

    if (req.operation === "statespace.design_observer") {
      return {
        api_version: RPC_API_VERSION,
        request_id: req.request_id,
        project_id: req.project_id,
        project_revision: rev,
        status: "success",
        result: {
          L: { shape: [2, 1], dtype: "float64", order: "C", data: [6.0, 13.0] },
          observer_poles: { real: [-3.0, -3.0], imag: [2.0, -2.0] },
          observer_error_matrix: {
            shape: [2, 2],
            dtype: "float64",
            order: "C",
            data: [-6.0, 1.0, -13.0, 0.0],
          },
        },
        assumptions: { observable: true },
        diagnostics: { pole_placement_error: 1e-12 },
        warnings: [],
        provenance: {
          algorithm: "statespace.design_observer",
          lib_versions: { control_lab: "1.0.0" },
        },
        error: null,
      };
    }

    if (req.operation === "statespace.simulate_lti") {
      const t = [0, 1, 2, 3, 4, 5, 6];
      const x = [
        [1.0, 0.0, 0.0, 0.0],
        [0.7, -0.3, 0.5, -0.1],
        [0.35, -0.25, 0.3, -0.2],
        [0.12, -0.12, 0.11, -0.11],
        [0.03, -0.04, 0.03, -0.04],
        [0.005, -0.01, 0.005, -0.01],
        [0.0, 0.0, 0.0, 0.0],
      ];
      return {
        api_version: RPC_API_VERSION,
        request_id: req.request_id,
        project_id: req.project_id,
        project_revision: rev,
        status: "success",
        result: {
          t: { shape: [t.length], dtype: "float64", order: "C", data: t },
          x: { shape: [t.length, 4], dtype: "float64", order: "C", data: x.flat() },
        },
        assumptions: {},
        diagnostics: {},
        warnings: [],
        provenance: {
          algorithm: "statespace.simulate_lti",
          lib_versions: { control_lab: "1.0.0" },
        },
        error: null,
      };
    }

    return origExecute(req, options);
  };

  return { client: base, calls };
}

test("WP-PHASE2-A1-F8-OBSERVER-KALMAN-LQG: parsers de polos complexos e vetores numéricos", () => {
  const realPoles = parseObserverPolesInput("-4, -5");
  assert.deepEqual(realPoles, [
    { real: -4, imag: 0 },
    { real: -5, imag: 0 },
  ]);

  const complexPoles = parseObserverPolesInput("-3 + 2j, -3-2j, 4i, -j");
  assert.deepEqual(complexPoles, [
    { real: -3, imag: 2 },
    { real: -3, imag: -2 },
    { real: 0, imag: 4 },
    { real: 0, imag: -1 },
  ]);

  assert.throws(() => parseObserverPolesInput(""), /Informe os polos/);
  assert.throws(() => parseObserverPolesInput("abc"), /Polo inválido/);

  assert.deepEqual(parseNumericVectorInput("0.5, -1", 2, "xhat0"), [0.5, -1]);
  assert.deepEqual(parseNumericVectorInput("", 2, "xhat0"), [0, 0]);
  assert.throws(() => parseNumericVectorInput("1, 2, 3", 2, "xhat0"), /deve ter 2 elemento/);
});

test("WP-PHASE2-A1-F8-OBSERVER-KALMAN-LQG: Kalman/LQG, Luenberger, simulação x(t) vs x_hat(t) e registro no Workspace", async () => {
  const doc = new FakeDocument();
  const root = new FakeElement("div", doc);
  const { client, calls } = createObserverMockClient();

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-obs-lqg",
  });
  await app.client.init();
  app.shell.switchTab("statespace");

  // 1. Verificar card e botões iniciais
  const obsCard = root.querySelector("#lqr-observer-lqg-card");
  assert.ok(obsCard !== null);
  assert.equal(obsCard.hasAttribute("hidden"), false);

  const btnSynth = root.querySelector<FakeElement>("#btn-obs-synthesize")!;
  const btnSim = root.querySelector<FakeElement>("#btn-obs-simulate")!;
  const btnReg = root.querySelector<FakeElement>("#btn-obs-register-ctrl")!;
  assert.equal(btnSim.disabled, true);
  assert.equal(btnReg.disabled, true);

  // 2. Sintetizar Kalman + LQG (u = -K x_hat)
  root.querySelector<FakeElement>("#obs-qn-scale")!.value = "0.2";
  root.querySelector<FakeElement>("#obs-rn-scale")!.value = "0.05";
  root.querySelector<FakeElement>("#obs-xhat0-input")!.value = "0, 0";
  btnSynth.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const lqgCall = calls.find((c) => c.operation === "statespace.design_lqg");
  assert.ok(lqgCall !== undefined, "Deve chamar statespace.design_lqg");
  const summary = root.querySelector<FakeElement>("#obs-results-summary")!;
  assert.ok(summary.textContent.includes("2.1000"), "Resumo deve exibir ganho L");
  assert.ok(summary.textContent.includes("1.7320"), "Resumo deve exibir ganho K");
  assert.ok(summary.textContent.includes("-0.87"), "Resumo deve exibir polos de regulação");
  assert.ok(summary.textContent.includes("-1.05"), "Resumo deve exibir polos do observador");
  assert.equal(btnSim.disabled, false);
  assert.equal(btnReg.disabled, false);

  // 3. Registrar Controlador LQG no Workspace
  btnReg.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const dynCtrls = app.shell.getTypedWorkspace().listRegisteredObjects(["DynamicController"]);
  assert.equal(dynCtrls.length, 1);
  assert.equal(dynCtrls[0].id, "lqg-ctrl-1");
  const dockEl = root.querySelector("#workspace-dock-aside")!;
  assert.ok(dockEl.textContent.includes("lqg-ctrl-1"), "Controlador LQG deve aparecer no Workspace Dock");

  // 4. Simular x(t) vs x_hat(t)
  btnSim.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const simCall = calls.find((c) => c.operation === "statespace.simulate_lti");
  assert.ok(simCall !== undefined, "Deve chamar statespace.simulate_lti");
  const simPlant = simCall.payload.plant as { matrices: { A: { shape: number[] } } };
  assert.deepEqual(simPlant.matrices.A.shape, [4, 4]);
  assert.deepEqual(simCall.payload.x0, [1, 0, 0, 0]);

  const chartSlot = root.querySelector("#obs-sim-chart-slot")!;
  assert.ok(chartSlot.innerHTML.includes("<svg"), "Deve renderizar SVG de convergência");
  assert.ok(chartSlot.innerHTML.includes('data-channel-id="x-true-1"'));
  assert.ok(chartSlot.innerHTML.includes('data-channel-id="x-hat-1"'));
  assert.ok(chartSlot.innerHTML.includes('stroke-dasharray="6 3"'));

  const tableSlot = root.querySelector("#obs-sim-table-slot")!;
  assert.ok(tableSlot.innerHTML.includes("<table"), "Deve renderizar tabela acessível WCAG 2.2 AA");

  // 5. Trocar para modo Luenberger e sintetizar com polos complexos
  const modeSelect = root.querySelector<FakeElement>("#obs-mode-select")!;
  modeSelect.value = "luenberger";
  modeSelect.dispatchEvent("change");
  assert.equal(root.querySelector("#obs-luenberger-fields")!.hasAttribute("hidden"), false);
  assert.equal(root.querySelector("#obs-kalman-fields")!.hasAttribute("hidden"), true);

  root.querySelector<FakeElement>("#obs-poles-input")!.value = "-3+2j, -3-2j";
  btnSynth.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  const obsCall = calls.find((c) => c.operation === "statespace.design_observer");
  assert.ok(obsCall !== undefined, "Deve chamar statespace.design_observer");
  assert.deepEqual(obsCall.payload.poles, [
    { real: -3, imag: 2 },
    { real: -3, imag: -2 },
  ]);
  assert.ok(summary.textContent.includes("6.0000"), "Resumo deve exibir ganho L do observador de Luenberger");
  assert.equal(btnReg.disabled, true, "Modo Luenberger puro não habilita registro de DynamicController LQG");
});
