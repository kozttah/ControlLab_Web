/**
 * Testes unitários de WP-UX11-04-F8-MIMO-CONTROLLER-DISPLAY-AND-LAYOUT (F8: f8-ui-charts)
 *
 * Verificam (CL-UX-DIR-001 v1.1.0 Seções 9.1, 9.3 e 9.5):
 * 1. Aba 4 (MIMO): exibição explícita na tela do controlador H∞ K∞ (#mimo-hinf-controller-display)
 *    com matrizes A_k, B_k, C_k, D_k formatadas em tabela, botão de cópia (#btn-mimo-copy-hinf-matrices)
 *    e preservação do botão #btn-mimo-register-hinf.
 * 2. Abas 1 e 3: palco de gráficos em largura total (.ident-workbench-stack, .ss-workbench-stack)
 *    preservando todos os IDs interativos e bloqueio R-23.
 * 3. Aba 7 (LMI): cartões matriciais formatados (.lmi-matrix-card) em #lmi-recovered-matrices-display
 *    para ganhos recuperados (K / K[1]..K[r]) e variáveis de decisão (Q, P), com #btn-lmi-copy-matrices
 *    e preservação do registro de controlador e exportação PathSim.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import type { ExecuteOptions } from "../../../web/bridge/client.ts";
import type {
  RpcRequest,
  RpcResponse,
} from "../../../web/bridge/protocol.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import {
  extractHinfControllerMatrices,
  formatHinfControllerCopyText,
  formatHinfControllerMatricesHtml,
} from "../../../web/features/views/mimo_view.ts";
import { renderIdentificationViewHtml } from "../../../web/features/views/identification_view.ts";
import { renderStatespaceViewHtml } from "../../../web/features/views/statespace_view.ts";
import { formatLmiMatricesCopyText } from "../../../web/features/views/lmi_view.ts";

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

async function flushAsync(): Promise<void> {
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
}

class Phase11StubClient extends MockWorkerAdapter {
  public override async execute(req: RpcRequest, opts?: ExecuteOptions): Promise<RpcResponse> {
    if (req.operation === "mimo.design_hinf") {
      return {
        api_version: req.api_version,
        request_id: req.request_id,
        status: "success",
        project_id: req.project_id,
        project_revision: req.project_revision,
        result: {
          controller: {
            schema_version: "1.0.0",
            id: "ctrl-hinf-test-2x2",
            revision: 1,
            kind: "DynamicController",
            feedback_sign: "negative",
            dt: null,
            Ac: { shape: [2, 2], dtype: "float64", order: "C", data: [-3.5, 0.25, -0.1, -4.2] },
            Bc: { shape: [2, 2], dtype: "float64", order: "C", data: [1.2, 0.0, 0.0, 1.4] },
            Cc: { shape: [2, 2], dtype: "float64", order: "C", data: [0.85, -0.15, 0.1, 0.92] },
            Dc: { shape: [2, 2], dtype: "float64", order: "C", data: [0.0, 0.0, 0.0, 0.0] },
            initial_state: { shape: [2], dtype: "float64", order: "C", data: [0, 0] },
            ports: { inputs: ["e1", "e2"], outputs: ["u1", "u2"] },
            provenance: { source: "test_hinf" },
          },
          generalized_plant_summary: { n_states: 6, n_w: 2, n_u: 2, n_z: 6, n_y: 2 },
          gamma_achieved: 1.245,
          hinf_norm_grid: 1.241,
          hinf_norm_exact: 1.242,
          hamiltonian_exact_verified: true,
          riccati_X_residual_rel: 1.2e-11,
          riccati_Y_residual_rel: 2.5e-11,
          is_stable: true,
          closed_loop_poles: { real: [-1.5, -2.5], imag: [0.3, -0.3] },
          omega: [0.1, 1.0, 10.0],
          sigma_S: [0.05, 0.8, 1.0],
          sigma_T: [1.0, 0.9, 0.1],
          inv_ws_bound: [0.01, 0.5, 2.0],
          inv_wt_bound: [1.5, 1.5, 0.2],
        },
        assumptions: {},
        diagnostics: {
          hamiltonian_exact_verified: true,
          hinf_norm_exact: 1.242,
        },
        warnings: [],
        error: null,
        provenance: {
          lib_versions: {},
          algorithm: "dgkf_mixed_sensitivity",
        },
      };
    }

    if (req.operation === "optimization.solve") {
      return {
        api_version: req.api_version,
        request_id: req.request_id,
        status: "success",
        project_id: req.project_id,
        project_revision: req.project_revision,
        result: {
          solver_status: "optimal",
          audit_feasibility: "strictly_feasible",
          certificate_status: "validated_dual",
          conditioning: { status: "well_conditioned", condition_number: 3.14 },
          controller_validity: "verified_under_assumptions",
          residuals: { primal_block_min_eigs: [0.12, 0.25] },
          variables: {
            Q: { shape: [2, 2], dtype: "float64", order: "C", data: [2.0, 0.0, 0.0, 4.0] },
            Y: { shape: [1, 2], dtype: "float64", order: "C", data: [-4.0, -12.0] },
          },
        },
        assumptions: {},
        diagnostics: {},
        warnings: [],
        error: null,
        provenance: {
          lib_versions: {},
          algorithm: "native_ipm",
        },
      };
    }

    return super.execute(req, opts);
  }
}

test("WP-UX11-04: helpers de extração e formatação de K∞ suportam DynamicController e state_space aninhado", () => {
  const nestedCtrl = {
    name: "K_nested",
    state_space: {
      dt: 0.05,
      A: [[0.5, 0.1], [0.0, 0.4]],
      B: [[1.0], [0.5]],
      C: [[0.2, 0.3]],
      D: [[0.0]],
    },
    poles: [{ re: 0.5, im: 0 }, { re: 0.4, im: 0 }],
  };

  const extracted = extractHinfControllerMatrices(nestedCtrl);
  assert.ok(extracted !== null);
  assert.equal(extracted.id, "K_nested");
  assert.equal(extracted.nStates, 2);
  assert.equal(extracted.nInputs, 1);
  assert.equal(extracted.nOutputs, 1);
  assert.equal(extracted.dt, 0.05);

  const html = formatHinfControllerMatricesHtml(nestedCtrl, 3);
  assert.ok(html.includes('id="mimo-hinf-controller-display"'));
  assert.ok(html.includes('id="btn-mimo-copy-hinf-matrices"'));
  assert.ok(html.includes("Discreto (dt=0.05 s)"));
  assert.ok(html.includes("0.500"));

  const copyText = formatHinfControllerCopyText(nestedCtrl, 2);
  assert.ok(copyText.includes("A_k = ["));
  assert.ok(copyText.includes("B_k = ["));
  assert.ok(copyText.includes("C_k = ["));
  assert.ok(copyText.includes("D_k = ["));
});

test("WP-UX11-04: Aba 4 exibe #mimo-hinf-controller-display (A_k, B_k, C_k, D_k) e cópia logo após síntese H∞", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const client = new Phase11StubClient();
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-ux11-mimo",
  });
  await app.client.init();

  app.shell.switchTab("mimo_frequency");
  root.querySelector<FakeElement>('[data-action="mimo-load-example"]')?.dispatchEvent("click");
  await flushAsync();

  root.querySelector<FakeElement>('[data-action="mimo-design-hinf"]')?.dispatchEvent("click");
  await flushAsync();

  // Antes mesmo de clicar em Registrar no Workspace, #mimo-hinf-controller-display deve estar visível
  const ctrlDisplay = root.querySelector<FakeElement>("#mimo-hinf-controller-display");
  assert.ok(ctrlDisplay !== null, "Painel #mimo-hinf-controller-display deve aparecer após síntese H∞");

  const matCards = ctrlDisplay.querySelectorAll<FakeElement>(".mimo-matrix-card");
  assert.equal(matCards.length, 4, "Deve renderizar 4 cartões de matriz (A_k, B_k, C_k, D_k)");
  const matNames = matCards.map((c) => c.getAttribute("data-controller-matrix"));
  assert.deepEqual(matNames, ["A_k", "B_k", "C_k", "D_k"]);

  const displayHtml = root.querySelector<FakeElement>("#mimo-hinf-summary")!.innerHTML;
  assert.ok(displayHtml.includes("-3.5000") && displayHtml.includes("-4.2000"), "Valores de A_k devem aparecer formatados");
  assert.ok(displayHtml.includes("1.2000") && displayHtml.includes("1.4000"), "Valores de B_k devem aparecer formatados");
  assert.ok(displayHtml.includes("0.8500") && displayHtml.includes("0.9200"), "Valores de C_k devem aparecer formatados");
  assert.ok(displayHtml.includes("tabular-num"), "Células devem usar numerais tabulares");

  // Botão Copiar Matrizes K∞ funciona de forma segura sem navigator.clipboard e anuncia confirmação
  const copyBtn = root.querySelector<FakeElement>("#btn-mimo-copy-hinf-matrices");
  assert.ok(copyBtn !== null, "Botão #btn-mimo-copy-hinf-matrices deve existir");
  copyBtn.dispatchEvent("click");
  const livePolite = root.querySelector<FakeElement>("#controllab-live-polite")?.textContent ?? "";
  assert.ok(livePolite.includes("K∞") || livePolite.includes("copiadas"), "Anunciador deve confirmar cópia");

  // Botão Registrar Controlador K∞ no Workspace permanece habilitado e funcional
  const regBtn = root.querySelector<FakeElement>("#btn-mimo-register-hinf");
  assert.ok(regBtn !== null && regBtn.disabled === false);
  regBtn.dispatchEvent("click");
  await flushAsync();
  const registered = app.shell.getTypedWorkspace().listRegisteredObjects();
  assert.ok(registered.some((o) => o.id === "ctrl-hinf-test-2x2"));

  app.destroy();
});

test("WP-UX11-04: Abas 1 e 3 usam palco em largura total preservando todos os IDs e bloqueio R-23", async () => {
  const identHtml = renderIdentificationViewHtml();
  assert.ok(identHtml.includes('class="ident-workbench-stack"'));
  assert.ok(identHtml.includes('class="ident-controls-bar"'));
  assert.ok(identHtml.includes('class="ident-results-stage"'));
  assert.ok(identHtml.includes('class="ident-charts-grid"'));
  assert.equal(identHtml.includes('class="workspace-two-col"'), false, "Aba 1 não deve usar .workspace-two-col comprimido");

  for (const id of [
    "btn-id-load-prbs",
    "btn-id-split-dataset",
    "btn-id-fit-arx",
    "btn-id-fit-subspace",
    "id-response-chart-slot",
    "id-residuals-chart-slot",
    "id-models-session-list",
  ]) {
    assert.ok(identHtml.includes(`id="${id}"`), `Aba 1 deve preservar #${id}`);
  }

  const ssHtml = renderStatespaceViewHtml({ n: 2, m: 1, p: 1 });
  assert.ok(ssHtml.includes('class="ss-workbench-stack"'));
  assert.ok(ssHtml.includes('class="ss-top-controls-grid"'));
  assert.ok(ssHtml.includes('class="ss-editors-grid"'));
  for (const id of [
    "statespace-workspace-panel",
    "lqr-kpi-cards",
    "lqr-pbh-badges",
    "lqr-q-slider",
    "lqr-matrix-editor",
    "lqr-observer-lqg-card",
    "btn-export-pvm",
  ]) {
    assert.ok(ssHtml.includes(`id="${id}"`), `Aba 3 deve preservar #${id}`);
  }

  // Verifica bloqueio R-23 preservado na Aba 3
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client: new MockWorkerAdapter(),
    project_id: "proj-ux11-ss-r23",
  });
  await app.client.init();
  await app.shell.getLqrWorkspace().commitCurrentDesign();

  const pzBar = root.querySelector<FakeElement>('[data-export-bar-for="pz-chart-slot"]')!;
  const pzSvgBtn = pzBar.querySelector<FakeElement>('[data-action="export-chart-svg"]')!;
  assert.equal(pzSvgBtn.disabled, false);

  app.shell.getLqrWorkspace().pointerDown("lqr-q-slider");
  app.shell.getLqrWorkspace().pointerMove({ qScale: 2.5 });
  assert.equal(pzSvgBtn.disabled, true, "R-23 deve bloquear exportação durante Fast-Preview");
  await app.shell.getLqrWorkspace().cancelDrag();

  app.destroy();
});

test("WP-UX11-04: Aba 7 (LMI) renderiza cartões matriciais formatados (.lmi-matrix-card) e cópia preservando registro e PathSim", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const client = new Phase11StubClient();
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-ux11-lmi",
  });
  await app.client.init();
  app.shell.switchTab("optimization_lmi");

  const editorEl = root.querySelector<FakeElement>("#lmi-code-editor")!;
  editorEl.value = [
    "var Q sym(n)",
    "var Y rect(m, n)",
    "Q > 0",
    "A*Q + Q*A' + B*Y + Y'*B' < 0",
    "recover K = Y * inv(Q)",
    "recover P = inv(Q)",
  ].join("\n");
  editorEl.dispatchEvent("input");

  root.querySelector<FakeElement>('[data-action="lmi-solve"]')?.dispatchEvent("click");
  await flushAsync();
  await new Promise((r) => setTimeout(r, 30));

  const displayEl = root.querySelector<FakeElement>("#lmi-recovered-matrices-display");
  assert.ok(displayEl !== null, "Painel #lmi-recovered-matrices-display deve ser renderizado");

  const cards = displayEl.querySelectorAll<FakeElement>(".lmi-matrix-card");
  assert.ok(cards.length >= 2, `Esperado >= 2 cartões matriciais (K, P, Q, Y), obtido ${cards.length}`);

  const matrixKeys = cards.map((c) => c.getAttribute("data-lmi-matrix"));
  assert.ok(matrixKeys.includes("K"), "Cartão matricial de K deve existir");
  assert.ok(matrixKeys.includes("P"), "Cartão matricial de P deve existir");
  assert.ok(matrixKeys.includes("Q"), "Cartão matricial da variável de decisão Q deve existir");

  const html = root.querySelector<FakeElement>("#lmi-recovered-gain")!.innerHTML;
  assert.ok(html.includes("-2.0000") && html.includes("-3.0000"), "Valores de K=[-2, -3] devem aparecer em tabela");
  assert.ok(html.includes("0.5000") && html.includes("0.2500"), "Valores de P=inv(Q) devem aparecer em tabela");

  const copyBtn = root.querySelector<FakeElement>("#btn-lmi-copy-matrices");
  assert.ok(copyBtn !== null, "Botão #btn-lmi-copy-matrices deve existir");
  copyBtn.dispatchEvent("click");
  const livePolite = root.querySelector<FakeElement>("#controllab-live-polite")?.textContent ?? "";
  assert.ok(livePolite.includes("Matrizes LMI"), "Anunciador deve confirmar cópia das matrizes LMI");

  // Botões de registro e PathSim preservados e habilitados
  const regBtn = root.querySelector<FakeElement>("#btn-lmi-register-controller");
  const pathSimBtn = root.querySelector<FakeElement>("#btn-lmi-export-pathsim");
  assert.ok(regBtn !== null && regBtn.disabled === false, "Botão #btn-lmi-register-controller deve permanecer habilitado");
  assert.ok(pathSimBtn !== null && pathSimBtn.disabled === false, "Botão #btn-lmi-export-pathsim deve permanecer habilitado");

  const copyStr = formatLmiMatricesCopyText(
    [{ label: "K", mat: { rows: 1, cols: 2, data: [-2, -3] } }],
    3,
  );
  assert.ok(copyStr.includes("K = [") && copyStr.includes("-2.000, -3.000"));

  app.destroy();
});
