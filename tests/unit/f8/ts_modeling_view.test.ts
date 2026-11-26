/**
 * Testes unitários e de integração UI→Python de WP-TSMOD-04-F8-TS-MODELING-TAB-UI (F8: f8-ui-charts)
 *
 * Cobrem integralmente os requisitos normativos de `CL-TS-MOD-DIR-001 v1.1.0` e `CL-UX-DIR-001`:
 * 1. Expansão de `PROJECT_TAB_IDS` e `PROJECT_TAB_METADATA` para 7 abas (`ts_modeling` na posição 6).
 * 2. Motor simbólico AST determinístico (`symbolic_qlpv_ast.ts`): `sinc_rad` suave em 0, reescrita
 *    `sin(u)/u -> sinc_rad(u)`, auditoria de isolamento e afinidade multilinear na Via 1 e extração
 *    de variáveis ativas `p = (p_1, ..., p_D)` nas Vias 2 e 3.
 * 3. Entrada customizada completa pelo usuário (sem depender de presets!):
 *    - Limpar / Novo sistema customizado, redimensionamento `(n, m, p)`, canais generalizados,
 *      adição de sinais externos `w_ext`, marcação de estados medidos vs não medidos (`ts_partially_observed`),
 *      edição livre de premissas `z_k = g_k(x, w_ext)` + override manual seguro, edição célula a célula de
 *      `A, B, C, D`, discretização individual por dimensão ativa `G_d`, posto `R_d` e fecho convexo.
 * 4. Execução ponta a ponta com motor científico Python real (`control_lab.core.rpc`):
 *    - Via 1 (Setor): extremos globais `[z_min, z_max]`, derivação exata e inspetor de vértices `(A_r, B_r, C_r, D_r)`.
 *    - Via 2 (TPMT) vs Via 3 (FEMT): redução estrita de regras `N_r(FEMT) < N_r(TPMT)` no sistema
 *      acoplado `sin(x1+x2), cos(x1-x2)`, gráficos SVG acessíveis (1D, malha Delaunay 2D, bases U vs W,
 *      scree plot e mapa de calor real de erro de Frobenius fora da grade `||S(p) - S_TS(p)||_F`).
 *    - Promoção em 1 clique ao Workspace Dock + atalho `→ Receita TS` + `Registrar e Abrir em LMIs` +
 *      reconstrução integral a partir de `provenance.ts_derivation` nativo + exportação Python/MATLAB.
 * 5. Segurança R-21: proibição absoluta de avaliação dinâmica de código.
 */

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { isTsModelingOperation } from "../../../web/bridge/ts_modeling.ts";
import {
  extractTensorsToBinaryBuffers,
  type RpcRequest,
  type RpcResponse,
} from "../../../web/bridge/protocol.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import {
  PROJECT_TAB_IDS,
  PROJECT_TAB_METADATA,
} from "../../../web/app/tool_descriptor.ts";
import {
  auditSectorMatrices,
  evalQlpvAst,
  expandSectorMatrixToDirect,
  inspectDirectQlpvMatrices,
  parseQlpvExpr,
  sincRad,
} from "../../../web/features/ts_modeling/symbolic_qlpv_ast.ts";
import {
  buildTsPayload,
  DEFAULT_TS_FORM_PARAMS,
  extractRecipeFromProvenance,
  renderTsModelingViewHtml,
  serializeDraftDerivationSignature,
  substitutePremises,
  TS_PRESETS,
  TsModelingView,
} from "../../../web/features/views/ts_modeling_view.ts";
import { LmiView, renderLmiViewHtml } from "../../../web/features/views/lmi_view.ts";
import {
  buildOffGridErrorHeatmap,
  evaluateDelaunayWeights,
  evaluateDerivedMembershipWeights,
} from "../../../web/charts/ts_modeling_charts.ts";
import type { DerivedTsFemtResult } from "../../../web/bridge/ts_modeling.ts";
import { cpythonLoader } from "../f7/cpython_runtime.mjs";
import { dispatchPythonWithBinaryBuffers } from "./cpython_binary_helper.mjs";

const REAL_PYTHON_EXTRA_OPS = new Set([
  "optimization.solve",
  "optimization.verify",
  "core.validate_interconnection",
  "core.interconnect",
  "io.export_pathsim_script",
]);

class RealPythonTsAdapter extends MockWorkerAdapter {
  protected override async dispatchRpc(
    request: RpcRequest,
    options?: Parameters<MockWorkerAdapter["execute"]>[1],
  ): Promise<{ response: RpcResponse; bridgeTransferMs?: number }> {
    if (REAL_PYTHON_EXTRA_OPS.has(request.operation)) {
      const extracted = extractTensorsToBinaryBuffers(request.payload);
      const response = dispatchPythonWithBinaryBuffers(
        {
          ...request,
          payload: extracted.replaced,
        },
        extracted.buffers,
      ) as RpcResponse;
      return { response };
    }
    if (isTsModelingOperation(request.operation)) {
      const loaded = await cpythonLoader({ indexURL: "", packages: [] });
      const pyodide = loaded.pyodide;
      if (!pyodide.pyimport || !pyodide.toPy) {
        throw new Error("cpythonLoader não expôs pyimport/toPy.");
      }
      const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
        dispatch: (arg: unknown) => RpcResponse;
        destroy?: () => void;
      };
      const proxy = pyodide.toPy({ request, payload: request.payload });
      const response = rpcMod.dispatch(proxy);
      proxy.destroy();
      rpcMod.destroy?.();
      return { response };
    }
    return super.dispatchRpc(request, options);
  }
}

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
    return this._textContent || this.children.map((c) => c.textContent).join(" ");
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
    this._textContent = html
      .replace(/<[^>]+>/g, " ")
      .replace(/&#39;/g, "'")
      .replace(/&quot;/g, '"')
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&")
      .replace(/\s+/g, " ")
      .trim();
  }

  public setAttribute(name: string, val: string): void {
    const s = String(val);
    this.attributes.set(name, s);
    if (name === "id") this.id = s;
    if (name === "class") this.className = s;
    if (name === "value") this.value = s;
    if (name === "checked") this.checked = true;
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
    if (name === "checked") this.checked = false;
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
    const parts = selector
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
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

function matchesSingleToken(el: FakeElement, token: string): boolean {
  if (token.startsWith("#")) return el.id === token.slice(1);
  if (token.startsWith(".")) return el.className.split(/\s+/).includes(token.slice(1));
  if (token.startsWith("[") && token.endsWith("]")) {
    const inner = token.slice(1, -1);
    const eq = inner.indexOf("=");
    if (eq === -1) return el.hasAttribute(inner);
    const k = inner.slice(0, eq);
    const v = inner.slice(eq + 1).replace(/^["']|["']$/g, "");
    return el.getAttribute(k) === v;
  }
  return el.tagName.toLowerCase() === token.toLowerCase();
}

function matchesSelector(el: FakeElement, selector: string): boolean {
  // Suporta seletores compostos por atributo como input[data-mat-key="A"][data-row="1"]
  const tokens = selector.match(/#[A-Za-z0-9_-]+|\.[A-Za-z0-9_-]+|\[[^\]]+\]|[A-Za-z0-9_-]+/g);
  if (!tokens || tokens.length === 0) return false;
  return tokens.every((tok) => matchesSingleToken(el, tok));
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
    if (tag === "option" && el.hasAttribute("selected")) {
      const selParent = stack[stack.length - 1];
      if (selParent && selParent.tagName === "SELECT") {
        selParent.value = el.value;
      }
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

function flushAsync(ms = 40): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
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

test("Motor AST simbólico TS: sinc_rad suave, reescrita sin(u)/u, auditoria de afinidade Setor e extração de variáveis ativas", () => {
  assert.equal(sincRad(0), 1.0);
  assert.ok(Math.abs(sincRad(1e-8) - (1 - 1e-16 / 6)) < 1e-15);

  const pSin = parseQlpvExpr("2.5 * sin(x3) / x3");
  assert.equal(pSin.ok, true);
  assert.equal(pSin.hasSinOverArg, true);
  assert.equal(pSin.suggestedSincSource, "2.5 * sinc_rad(x3)");
  assert.ok(Math.abs(evalQlpvAst(pSin.ast!, { x3: 0.2 }) - 2.5 * (Math.sin(0.2) / 0.2)) < 1e-14);

  // Auditoria Via 1: detecta variável de estado direta e termo quadrático não-afim
  const badState = auditSectorMatrices({ A: [["0", "x1"], ["-z1", "0"]] }, ["z1"], ["x1", "x2"]);
  assert.equal(badState.length, 1);
  assert.equal(badState[0].kind, "direct_state_or_ext");

  const badNonlin = auditSectorMatrices({ A: [["0", "1"], ["-z1^2", "0"]] }, ["z1"], ["x1", "x2"]);
  assert.equal(badNonlin.length, 1);
  assert.equal(badNonlin[0].kind, "nonlinear_in_premise");

  const okMultilinear = auditSectorMatrices(
    { A: [["0", "1"], ["-1.96 * z1 * z2", "-0.2 * z1"]] },
    ["z1", "z2"],
    ["x1", "x2"],
  );
  assert.equal(okMultilinear.length, 0);

  // Substituição algébrica segura com parênteses preservados
  assert.equal(
    substitutePremises("-2 * z1 * z2", [
      { name: "z1", expression: "1 + x1" },
      { name: "z2", expression: "cos(x2)" },
    ]),
    "-2 * (1 + x1) * cos(x2)",
  );
  const expanded = expandSectorMatrixToDirect(
    [["-z1"]],
    [{ name: "z1", expression: "x1 + x2" }],
  );
  assert.equal(expanded[0][0], "-(x1 + x2)");

  // Inspeção direta TPMT/FEMT poupa estados puramente lineares
  const insp = inspectDirectQlpvMatrices(
    { A: [["0", "1", "0"], ["0", "0", "cos(x3)"], ["0", "0", "-theta1"]], B: [["0"], ["0"], ["1"]] },
    ["x1", "x2", "x3"],
    ["theta1"],
  );
  assert.deepEqual(insp.activeVariables, ["x3", "theta1"]);
  assert.deepEqual(insp.linearOnlyStates, ["x1", "x2"]);

  assert.equal(TS_PRESETS.pendulum_16.buildDraft().premises.length, 4);
  const pFemt = buildTsPayload("nonseparable_benchmark", "femt", DEFAULT_TS_FORM_PARAMS);
  assert.equal(pFemt.hull_type, "CNO");
});

test("Entrada customizada qLPV completa + Motor Python Real: Via 1 (Setor), Via 2 (TPMT), Via 3 (FEMT), Vértices, Gráficos e Recarga de Receita", async () => {
  const doc = new FakeDocument();
  const root = new FakeElement("div", doc);
  doc.body.appendChild(root);

  const client = new RealPythonTsAdapter();
  await client.init();

  const app = mountControlLabApp(root as unknown as HTMLElement, { client });
  app.shell.switchTab("ts_modeling");

  const panel = root.querySelector<FakeElement>("#ts-modeling-workspace-panel")!;
  assert.equal(panel.hasAttribute("hidden"), false);

  // 1. Iniciar um sistema customizado do zero (Limpar / Novo Sistema)
  root.querySelector<FakeElement>("#btn-ts-new-custom")!.click();
  assert.equal(root.querySelector<FakeElement>("#ts-preset-select")!.value, "custom");

  // Adicionar sinal externo variante w_ext = theta1 ∈ [0.8, 1.2] e marcar x2 como não medido
  root.querySelector<FakeElement>("#btn-ts-add-external")!.click();
  const extMinIn = root.querySelector<FakeElement>('input[data-ext-field="min"][data-idx="0"]')!;
  const extMaxIn = root.querySelector<FakeElement>('input[data-ext-field="max"][data-idx="0"]')!;
  extMinIn.value = "0.8";
  extMinIn.dispatchEvent("change");
  extMaxIn.value = "1.2";
  extMaxIn.dispatchEvent("change");

  const st2Meas = root.querySelector<FakeElement>('input[data-state-field="measured"][data-idx="1"]')!;
  st2Meas.checked = false;
  st2Meas.dispatchEvent("change");

  // Editar premissa z1 = sin(x1)/x1 e usar botão 1-clique para converter em sinc_rad(x1)
  const z1Expr = root.querySelector<FakeElement>('input[data-premise-field="expression"][data-idx="0"]')!;
  z1Expr.value = "sin(x1) / x1";
  z1Expr.dispatchEvent("change");
  const sincBtn = root.querySelector<FakeElement>('button[data-premise-sinc="0"]');
  assert.ok(sincBtn !== null, "Botão de conversão para sinc_rad deve aparecer para sin(x1)/x1");
  sincBtn!.click();
  assert.equal(
    root.querySelector<FakeElement>('input[data-premise-field="expression"][data-idx="0"]')!.value,
    "sinc_rad(x1)",
  );

  // Adicionar segunda premissa z2 = theta1 * x2 (depende de x2 não medido -> ts_partially_observed!)
  root.querySelector<FakeElement>("#btn-ts-add-premise")!.click();
  const z2Expr = root.querySelector<FakeElement>('input[data-premise-field="expression"][data-idx="1"]')!;
  z2Expr.value = "theta1 * x2";
  z2Expr.dispatchEvent("change");
  assert.ok(
    root.querySelector<FakeElement>("#ts-inferred-kind-badge")!.textContent.includes("ts_partially_observed"),
    "Deve inferir ts_partially_observed quando premissa usa estado não medido x2",
  );

  // Testar alerta instantâneo de erro conceitual se digitar x1 direto em A(z)
  const cellA10 = root.querySelector<FakeElement>('input[data-mat-key="A"][data-row="1"][data-col="0"]')!;
  cellA10.value = "-2.0 * x1";
  cellA10.dispatchEvent("input");
  assert.ok(
    root.querySelector<FakeElement>("#ts-sector-affinity-banner")!.textContent.includes("absorva 'x1'"),
    "Deve avisar imediatamente sobre estado direto na matriz da Via 1",
  );

  // Corrigir célula A(2,1) = -4.0 * z1 e A(2,2) = -0.5 - 0.2 * z2
  cellA10.value = "-4.0 * z1";
  cellA10.dispatchEvent("change");
  const cellA11 = root.querySelector<FakeElement>('input[data-mat-key="A"][data-row="1"][data-col="1"]')!;
  cellA11.value = "-0.5 - 0.2 * z2";
  cellA11.dispatchEvent("change");
  assert.ok(
    root.querySelector<FakeElement>("#ts-sector-affinity-banner")!.textContent.includes("Afinidade multilinear verificada"),
  );

  // Calcular extremos globais [z_min, z_max] no Python real e derivar o modelo TS customizado (2^2 = 4 regras)
  root.querySelector<FakeElement>("#btn-ts-analyze")!.click();
  await flushAsync();
  assert.ok(root.querySelector<FakeElement>("#ts-status")!.textContent.includes("4 regras"));

  const modelIdIn = root.querySelector<FakeElement>("#ts-model-id-input")!;
  modelIdIn.value = "meu-modelo-custom-setor";
  modelIdIn.dispatchEvent("change");

  root.querySelector<FakeElement>("#btn-ts-derive")!.click();
  await flushAsync();
  assert.ok(root.querySelector<FakeElement>("#ts-summary")!.textContent.includes("EXACT_ANALYTICAL_SECTOR"));
  assert.equal(root.querySelector<FakeElement>("#ts-vertex-inspector-card")!.hasAttribute("hidden"), false);
  assert.ok(root.querySelector<FakeElement>("#ts-vertex-detail-slot")!.textContent.includes("A_1"));
  assert.ok(root.querySelector<FakeElement>("#ts-hr-chart-slot")!.innerHTML.includes("<svg"));
  assert.ok(root.querySelector<FakeElement>("#ts-error-heatmap-slot")!.innerHTML.includes("<svg"));

  // Exportação passiva Python e MATLAB gerada pelo motor Python real
  root.querySelector<FakeElement>("#btn-ts-export-python")!.click();
  await flushAsync();
  const modalPre = root.querySelector<FakeElement>("#export-modal-content")!;
  assert.ok(modalPre.textContent.includes("sinc_rad"), "Script Python deve conter avaliador da planta customizada");
  root.querySelector<FakeElement>("#btn-ts-export-matlab")!.click();
  await flushAsync();
  assert.ok(modalPre.textContent.includes("%"), "Script MATLAB passivo deve ser gerado");

  // Registrar no Workspace Dock e verificar recarga completa via provenance.ts_derivation
  root.querySelector<FakeElement>("#btn-ts-register")!.click();
  await flushAsync();
  const regModels = app.shell.getTypedWorkspace().listRegisteredObjects(["ts_partially_observed"]);
  assert.equal(regModels.length, 1);
  assert.equal(regModels[0].id, "meu-modelo-custom-setor");

  // 2. Testar Via 3 (FEMT) e Comparativo FEMT vs TPMT no sistema acoplado não-separável
  const presetSel = root.querySelector<FakeElement>("#ts-preset-select")!;
  presetSel.value = "nonseparable_benchmark";
  presetSel.dispatchEvent("change");
  assert.equal(root.querySelector<FakeElement>("#ts-via-select")!.value, "femt");

  // Customizar discretização individual G_1 = 9, G_2 = 11 na tabela por eixo
  const g1In = root.querySelector<FakeElement>('input[data-axis-var="x1"][data-axis-field="gridPoints"]')!;
  const g2In = root.querySelector<FakeElement>('input[data-axis-var="x2"][data-axis-field="gridPoints"]')!;
  assert.ok(g1In && g2In, "Tabela de nós por dimensão ativa deve expor x1 e x2");
  g1In.value = "9";
  g1In.dispatchEvent("change");
  g2In.value = "11";
  g2In.dispatchEvent("change");
  assert.ok(root.querySelector<FakeElement>("#ts-active-vars-bar")!.textContent.includes("N_g = 99"));

  root.querySelector<FakeElement>("#btn-ts-derive")!.click();
  await flushAsync(80);
  assert.ok(root.querySelector<FakeElement>("#ts-mesh-chart-slot")!.innerHTML.includes("<polygon"), "Malha Delaunay 2D deve renderizar triângulos SVG");
  assert.ok(root.querySelector<FakeElement>("#ts-bases-chart-slot")!.innerHTML.includes("<svg"));
  assert.ok(root.querySelector<FakeElement>("#ts-scree-chart-slot")!.innerHTML.includes("<svg"));
  assert.ok(root.querySelector<FakeElement>("#ts-error-heatmap-slot")!.innerHTML.includes("||S(p)"));

  // Rodar comparativo entre vias na planta atual: FEMT deve usar estritamente menos regras que TPMT!
  root.querySelector<FakeElement>("#btn-ts-compare")!.click();
  await flushAsync(120);
  const compareText = root.querySelector<FakeElement>("#ts-compare-slot")!.textContent;
  assert.ok(compareText.includes("Redução algébrica confirmada"), `Esperado destaque de redução FEMT < TPMT, obtido: ${compareText}`);

  // Promoção com abertura direta na Aba 7 (LMIs)
  root.querySelector<FakeElement>("#btn-ts-register-open-lmi")!.click();
  await flushAsync();
  assert.equal(app.shell.getActiveTab(), "optimization_lmi");

  // Voltar pelo botão "→ Receita TS" do Workspace Dock para recarregar o primeiro modelo customizado!
  const dockTsBtn = root.querySelector<FakeElement>(
    `button[data-dock-action="dock-route-ts-modeling"][data-object-key="${regModels[0].key}"]`,
  );
  assert.ok(dockTsBtn !== null, "Workspace Dock deve exibir botão → Receita TS para TSStateSpace derivado");
  dockTsBtn!.click();
  await flushAsync();
  assert.equal(app.shell.getActiveTab(), "ts_modeling");
  assert.equal(root.querySelector<FakeElement>("#ts-model-id-input")!.value, "meu-modelo-custom-setor");
  assert.equal(root.querySelector<FakeElement>("#ts-via-select")!.value, "sector");

  // Também valida reconstrução pura sem `recipe.draft` (somente provenance.ts_derivation nativo do Python)
  const rawDto = structuredClone(regModels[0].value);
  if (rawDto.provenance && typeof rawDto.provenance === "object") {
    const td = (rawDto.provenance as Record<string, unknown>).ts_derivation as Record<string, unknown>;
    delete td.recipe;
  }
  const pureRecipe = extractRecipeFromProvenance(rawDto);
  assert.ok(pureRecipe && pureRecipe.draft !== null, "Deve reconstruir rascunho direto do provenance.ts_derivation nativo");
  assert.equal(pureRecipe!.draft!.externals[0]?.name, "theta1");
  assert.equal(pureRecipe!.draft!.premises.length, 2);

  assert.ok(renderTsModelingViewHtml().includes("ts-zone-1-toolbar"));
  assert.equal(typeof TsModelingView, "function");
  app.destroy();
});

test("Regressão Achado 1: edição pós-derivação e troca de preset bloqueiam registro obsoleto e preservam integridade de matrizes/receita", async () => {
  const doc = new FakeDocument();
  const root = new FakeElement("div", doc);
  doc.body.appendChild(root);

  const client = new RealPythonTsAdapter();
  await client.init();

  const app = mountControlLabApp(root as unknown as HTMLElement, { client });
  app.shell.switchTab("ts_modeling");

  // 1. Derivar pendulum_16 (4 estados, 16 regras)
  assert.equal(root.querySelector<FakeElement>("#ts-preset-select")!.value, "pendulum_16");
  root.querySelector<FakeElement>("#btn-ts-derive")!.click();
  await flushAsync(80);

  const regBtn = root.querySelector<FakeElement>("#btn-ts-register")!;
  const staleBanner = root.querySelector<FakeElement>("#ts-stale-banner")!;
  assert.equal(regBtn.disabled, false, "Registrar deve estar habilitado logo após derivar");
  assert.equal(staleBanner.hasAttribute("hidden"), true, "Banner obsoleto deve estar oculto logo após derivar");

  // 2. Editar uma célula matricial após derivar -> deve marcar como obsoleto e bloquear registro
  const cellA12 = root.querySelector<FakeElement>('input[data-mat-key="A"][data-row="1"][data-col="2"]')!;
  cellA12.value = "-2.0 * z1 * z2 * z3";
  cellA12.dispatchEvent("input");

  assert.equal(regBtn.disabled, true, "Registrar deve ficar desabilitado após editar célula");
  assert.equal(staleBanner.hasAttribute("hidden"), false, "Banner de especificação alterada deve aparecer");
  assert.ok(staleBanner.textContent.includes("Especificação alterada desde a última derivação"));

  // Mesmo disparando clique diretamente, guarda defensiva impede gravação
  regBtn.click();
  await flushAsync();
  assert.equal(
    app.shell.getTypedWorkspace().listRegisteredObjects(["ts_measured", "ts_partially_observed"]).length,
    0,
    "Nenhum objeto obsoleto pode ser gravado após edição",
  );

  // 3. Re-selecionar pendulum_16, derivar novamente e trocar para nonseparable_benchmark (coupled_2d) sem re-derivar
  const presetSel = root.querySelector<FakeElement>("#ts-preset-select")!;
  presetSel.value = "pendulum_16";
  presetSel.dispatchEvent("change");
  root.querySelector<FakeElement>("#btn-ts-derive")!.click();
  await flushAsync(80);
  assert.equal(regBtn.disabled, false);

  presetSel.value = "nonseparable_benchmark";
  presetSel.dispatchEvent("change");

  assert.equal(regBtn.disabled, true, "Troca de preset deve desabilitar Registrar imediatamente");
  assert.equal(
    root.querySelector<FakeElement>("#ts-vertex-inspector-card")!.hasAttribute("hidden"),
    true,
    "Inspetor de vértices do pêndulo deve ser limpo ao trocar de preset",
  );
  assert.equal(
    root.querySelector<FakeElement>("#ts-hr-chart-slot")!.innerHTML.includes("<svg"),
    false,
    "Gráficos do pêndulo não devem permanecer visíveis após trocar para coupled_2d",
  );

  // Tentativa de registrar antes de derivar coupled_2d não deve gravar nada
  regBtn.click();
  await flushAsync();
  assert.equal(
    app.shell.getTypedWorkspace().listRegisteredObjects(["ts_measured", "ts_partially_observed"]).length,
    0,
    "Não deve gravar ts-coupled-2d com matrizes do pêndulo 4x4",
  );

  // 4. Derivar coupled_2d e registrar -> deve gravar matrizes 2x2 e receita de nonseparable_benchmark
  root.querySelector<FakeElement>("#btn-ts-derive")!.click();
  await flushAsync(100);
  assert.equal(regBtn.disabled, false);

  regBtn.click();
  await flushAsync();
  const objs = app.shell.getTypedWorkspace().listRegisteredObjects(["ts_measured", "ts_partially_observed"]);
  assert.equal(objs.length, 1);
  assert.equal(objs[0].id, "ts-coupled-2d");
  const verts = objs[0].value.vertices as Array<{ A: { shape: number[] } }>;
  assert.deepEqual(verts[0].A.shape, [2, 2], "Objeto ts-coupled-2d deve ter matrizes A 2x2");
  const recipe = extractRecipeFromProvenance(objs[0].value);
  assert.equal(recipe?.via, "femt");
  assert.equal(recipe?.preset, "nonseparable_benchmark");

  // Determinismo da assinatura
  const d1 = TS_PRESETS.pendulum_16.buildDraft();
  const d2 = TS_PRESETS.pendulum_16.buildDraft();
  assert.equal(
    serializeDraftDerivationSignature(d1, "sector"),
    serializeDraftDerivationSignature(d2, "sector"),
  );
  d2.sectorMatrices.A[0][0] = "0.1";
  assert.notEqual(
    serializeDraftDerivationSignature(d1, "sector"),
    serializeDraftDerivationSignature(d2, "sector"),
  );

  app.destroy();
});

test("Regressão Achado 2: mapa de erro off-grid inclui canais generalizados (Bw, Cz) na norma de Frobenius", async () => {
  const client = new RealPythonTsAdapter();
  await client.init();

  // Planta com A, B, C, D 100% constantes e não-linearidade EXCLUSIVA em Bw(x1, x2)
  const resp = await client.deriveTsFemt(
    { request_id: "test-gen-err-1", project_id: "proj-gen", project_revision: 1 },
    {
      state_bounds: { x1: [-1.2, 1.2], x2: [-1.2, 1.2] },
      A_expr: [
        ["-1.0", "0.5"],
        ["0.0", "-2.0"],
      ],
      B_expr: [["0.0"], ["1.0"]],
      C_expr: [["1.0", "0.0"]],
      D_expr: [["0.0"]],
      generalized_channels: {
        Bw: [["sin(x1 * x2)"], ["cos(x1 + x2)"]],
        Cz: [["1.0", "0.0"]],
      },
      grid_points: { x1: 5, x2: 5 },
      hull_type: "CNO",
      mesh_kind: "delaunay",
      model_id: "ts-gen-bw-only",
      n_val_points: 64,
    },
  );
  assert.equal(resp.status === "success" || resp.status === "warning", true);
  const result = resp.result!;

  const hm = buildOffGridErrorHeatmap(result);
  assert.ok(hm !== null, "Heatmap deve ser gerado");
  assert.ok(
    hm!.maxError > 1e-3,
    `Erro off-grid com não-linearidade exclusiva em Bw não pode ser ~0, obtido ${hm!.maxError}`,
  );

  // Validação exata ponto a ponto da norma de Frobenius de Bw em todos os pontos do heatmap
  const prov = result.ts_state_space.provenance as Record<string, unknown>;
  const genProv = prov.generalized_channels as {
    vertices: Array<{ Bw: number[][] }>;
  };
  let maxDiff = 0;
  for (let j = 0; j < hm!.ys.length; j += 1) {
    for (let i = 0; i < hm!.xs.length; i += 1) {
      const x1 = hm!.xs[i];
      const x2 = hm!.ys[j];
      const h = evaluateDerivedMembershipWeights(result, { x1, x2 })!;
      let bw0Hat = 0;
      let bw1Hat = 0;
      for (let r = 0; r < h.length; r += 1) {
        bw0Hat += h[r] * genProv.vertices[r].Bw[0][0];
        bw1Hat += h[r] * genProv.vertices[r].Bw[1][0];
      }
      const d0 = Math.sin(x1 * x2) - bw0Hat;
      const d1 = Math.cos(x1 + x2) - bw1Hat;
      const expectedFrob = Math.sqrt(d0 * d0 + d1 * d1);
      const diff = Math.abs(hm!.values[j][i] - expectedFrob);
      if (diff > maxDiff) maxDiff = diff;
    }
  }
  assert.ok(
    maxDiff < 1e-12,
    `Norma de Frobenius do heatmap deve coincidir com o erro exato em Bw (maxDiff=${maxDiff})`,
  );
});

test("Regressão Achado 3: avaliador FEMT Delaunay 3D em JS bate com evaluate_femt_delaunay do Python (< 1e-12)", async () => {
  const client = new RealPythonTsAdapter();
  await client.init();

  // Gera modelo FEMT 3D real com mesh_kind="delaunay"
  const resp = await client.deriveTsFemt(
    { request_id: "test-femt-3d-del", project_id: "proj-3d", project_revision: 1 },
    {
      state_bounds: { x1: [-1.0, 1.0], x2: [-1.0, 1.0], x3: [-1.0, 1.0] },
      A_expr: [
        ["-1.0 + 0.4 * sin(x1 + x2)", "0.3 * cos(x2 - x3)", "0.1"],
        ["0.2 * x1 * x3", "-2.0 + 0.25 * sin(x1 * x3)", "0.0"],
        ["0.0", "0.5", "-1.5 + 0.3 * cos(x1 + x2 + x3)"],
      ],
      B_expr: [["0.0"], ["0.0"], ["1.0"]],
      C_expr: [["1.0", "0.0", "0.0"]],
      D_expr: [["0.0"]],
      grid_points: { x1: 4, x2: 4, x3: 4 },
      hull_type: "CNO",
      mesh_kind: "delaunay",
      model_id: "ts-femt-3d-delaunay",
      n_val_points: 64,
    },
  );
  assert.equal(resp.status === "success" || resp.status === "warning", true);
  const femtResult = resp.result as DerivedTsFemtResult;
  const mesh = femtResult.ts_state_space.membership_spec.femt_mesh;
  assert.equal(mesh.mesh_kind, "delaunay");
  assert.equal(mesh.variables.length, 3);
  assert.ok(Array.isArray(femtResult.nodes) && femtResult.nodes.length === 64);
  assert.ok(Array.isArray(femtResult.simplices) && femtResult.simplices.length > 0);
  assert.equal(femtResult.simplices[0].length, 4, "Simplices 3D devem ser tetraedros com 4 vértices");

  const testPoints: Array<[number, number, number]> = [
    [0.13, -0.47, 0.62],
    [-0.71, 0.29, -0.18],
    [0.85, 0.77, -0.91],
    [0.0, 0.0, 0.0],
    [-1.0, 1.0, -1.0],
    [1.0, -0.3333333333333333, 0.5],
    [-0.25, -0.82, 0.99],
  ];

  // Compara diretamente com `control_lab.fuzzy.femt.evaluate_femt_delaunay` no Python real
  const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
  const cpModId = "node:child_process";
  const { spawnSync } = (await import(cpModId)) as {
    spawnSync: (
      cmd: string,
      args: string[],
      opts: Record<string, unknown>,
    ) => { status: number | null; stdout: string; stderr: string };
  };
  const pyProc = spawnSync(
    "python3",
    [
      "-c",
      "import sys, json; from control_lab.fuzzy.femt import evaluate_femt_delaunay; d = json.load(sys.stdin); out = evaluate_femt_delaunay(d['pts'], d['nodes'], d['simplices'], d['weights'], d['bounds']); print(json.dumps(out.tolist(), allow_nan=False))",
    ],
    {
      cwd: repoRoot,
      input: JSON.stringify({
        pts: testPoints,
        nodes: femtResult.nodes,
        simplices: femtResult.simplices,
        weights: mesh.nodal_weights,
        bounds: mesh.bounds,
      }),
      encoding: "utf8",
      timeout: 30000,
    },
  );
  assert.equal(pyProc.status, 0, `Python evaluate_femt_delaunay falhou: ${pyProc.stderr}`);
  const pyWeightsBatch = JSON.parse(pyProc.stdout) as number[][];

  let maxErr = 0;
  for (let k = 0; k < testPoints.length; k += 1) {
    const [p0, p1, p2] = testPoints[k];
    const env = {
      [mesh.variables[0]]: p0,
      [mesh.variables[1]]: p1,
      [mesh.variables[2]]: p2,
    };
    const hJs = evaluateDerivedMembershipWeights(femtResult, env);
    const hDirect = evaluateDelaunayWeights(
      [p0, p1, p2],
      femtResult.nodes!,
      femtResult.simplices!,
      mesh.nodal_weights,
      mesh.bounds,
    );
    assert.ok(hJs !== null && hDirect !== null);
    const hPy = Array.from(pyWeightsBatch[k]);
    assert.equal(hJs!.length, hPy.length);
    for (let r = 0; r < hPy.length; r += 1) {
      const err1 = Math.abs(hJs![r] - hPy[r]);
      const err2 = Math.abs(hDirect![r] - hPy[r]);
      if (err1 > maxErr) maxErr = err1;
      if (err2 > maxErr) maxErr = err2;
    }
  }
  assert.ok(
    maxErr < 1e-12,
    `Avaliador FEMT Delaunay 3D JS deve coincidir com Python (< 1e-12), obtido maxErr=${maxErr}`,
  );
});

test("WP-TSMOD-06: Fluxo E2E Aba 6 (Modelo TS FEMT) -> Aba 7 (LMI PDC / LTI) -> Registro de Controlador no Workspace & Exportação PathSim 0.31.0 estável", async () => {
  const doc = new FakeDocument();
  const root = new FakeElement("div", doc);
  doc.body.appendChild(root);

  const client = new RealPythonTsAdapter();
  await client.init();

  const app = mountControlLabApp(root as unknown as HTMLElement, { client });
  const projectId = app.shell.getLqrWorkspace().getProjectId();

  // Botões da Aba 7 começam desabilitados antes de qualquer resolução LMI
  const regCtrlBtn = root.querySelector<FakeElement>("#btn-lmi-register-controller")!;
  const exportPathSimBtn = root.querySelector<FakeElement>("#btn-lmi-export-pathsim")!;
  assert.ok(regCtrlBtn && exportPathSimBtn, "Botões de controlador e PathSim devem existir na Aba 7");
  assert.equal(regCtrlBtn.disabled, true);
  assert.equal(exportPathSimBtn.disabled, true);

  // 1. Aba 6: selecionar nonseparable_benchmark (FEMT) e tornar A(1,1) instável em malha aberta
  //    para provar que o sinal de realimentação PDC realmente estabiliza um sistema instável!
  app.shell.switchTab("ts_modeling");
  const presetSel = root.querySelector<FakeElement>("#ts-preset-select")!;
  presetSel.value = "nonseparable_benchmark";
  presetSel.dispatchEvent("change");
  assert.equal(root.querySelector<FakeElement>("#ts-via-select")!.value, "femt");

  const cellA00 = root.querySelector<FakeElement>('input[data-mat-key="A"][data-row="0"][data-col="0"]')!;
  cellA00.value = "0.85 + 0.5 * sin(x1 + x2)";
  cellA00.dispatchEvent("change");

  root.querySelector<FakeElement>("#btn-ts-derive")!.click();
  await flushAsync(120);

  // Registrar e abrir diretamente na Aba 7 (LMIs)
  root.querySelector<FakeElement>("#btn-ts-register-open-lmi")!.click();
  await flushAsync(60);
  assert.equal(app.shell.getActiveTab(), "optimization_lmi");

  const registeredTs = app.shell.getTypedWorkspace().listRegisteredObjects(["ts_measured"]);
  assert.equal(registeredTs.length, 1);
  assert.equal(registeredTs[0].id, "ts-coupled-2d");
  const nVerts = (registeredTs[0].value.vertices as unknown[]).length;
  assert.equal(nVerts, 3, "FEMT acoplado 2D deve produzir 3 vértices");

  // 2. Aba 7: carregar template PDC relaxado (ts_pdc_relaxed) e resolver LMI
  const tplSelect = root.querySelector<FakeElement>("#lmi-template-select")!;
  tplSelect.value = "ts_pdc_relaxed";
  tplSelect.dispatchEvent("change");
  assert.ok(
    root.querySelector<FakeElement>("#lmi-code-editor")!.value.includes("rules=3"),
    "Template ts_pdc_relaxed deve sincronizar rules=3 com o modelo TS selecionado",
  );

  root.querySelector<FakeElement>("#btn-lmi-solve")!.click();
  await flushAsync(150);

  const certText = root.querySelector<FakeElement>("#lmi-certificate-dims")!.textContent;
  assert.ok(certText.includes("validated_dual"), `Certificado esperado validated_dual, obtido: ${certText}`);
  assert.equal(regCtrlBtn.disabled, false, "#btn-lmi-register-controller deve habilitar após solveLmi factível");
  assert.equal(exportPathSimBtn.disabled, false, "#btn-lmi-export-pathsim deve habilitar para ts_measured");

  // 3. Registrar PDCController no Workspace (validando contra motor Python via core.validate_interconnection)
  regCtrlBtn.click();
  await flushAsync(80);

  const storedPdc = await app.client.getObject(projectId, "pdc-ts-coupled-2d", 1);
  assert.ok(storedPdc !== null, "PDCController deve ser persistido no Workspace");
  assert.equal(storedPdc!.kind, "PDCController");
  assert.equal(storedPdc!.schema_version, "1.0.0");
  assert.equal(storedPdc!.feedback_sign, "positive");
  assert.equal((storedPdc!.K_i as unknown[]).length, 3);
  assert.ok(
    root.querySelector<FakeElement>("#lmi-recovered-gain")!.textContent.includes("pdc-ts-coupled-2d#r1"),
    "Painel de ganhos recuperados deve confirmar registro no Workspace",
  );

  // 4. Exportar Simulação PathSim (.py) pelo botão da Aba 7
  exportPathSimBtn.click();
  await flushAsync(80);

  const exportTitle = root.querySelector<FakeElement>("#export-modal-title")!.textContent;
  const scriptContent = root.querySelector<FakeElement>("#export-modal-content")!.textContent;
  assert.ok(exportTitle.includes("PathSim"), `Título inesperado no modal: ${exportTitle}`);
  assert.ok(scriptContent.includes("def ts_pdc_rhs("), "Script PathSim deve definir ts_pdc_rhs");
  assert.ok(scriptContent.includes("def default_h_fn("), "Script PathSim deve definir default_h_fn");
  assert.ok(scriptContent.includes("K_vertices = ["), "Script PathSim deve exportar K_vertices");
  assert.equal(
    scriptContent.includes("1.0 / N_VERTICES"),
    false,
    "default_h_fn não pode usar stub uniforme 1/N para modelo FEMT derivado",
  );

  // Validar também chamada programática direta a LmiView.exportPathSimSimulation()
  const standaloneHost = new FakeElement("div", doc);
  standaloneHost.innerHTML = renderLmiViewHtml();
  let capturedModalCode = "";
  const standaloneLmi = new LmiView({
    shell: app.shell,
    client: app.client,
    container: standaloneHost as unknown as HTMLElement,
    onOpenExportModal: (payload) => {
      capturedModalCode = payload.content;
    },
  });
  standaloneLmi.selectSystemByRefKey(registeredTs[0].key);
  standaloneHost.querySelector<FakeElement>("#lmi-template-select")!.value = "ts_pdc_relaxed";
  standaloneHost.querySelector<FakeElement>("#lmi-template-select")!.dispatchEvent("change");
  await standaloneLmi.solveLmi();
  const extractedGains = standaloneLmi.extractSynthesizedControllerGains();
  assert.ok(extractedGains !== null);
  assert.equal(extractedGains!.controller.kind, "PDCController");
  const directScript = await standaloneLmi.exportPathSimSimulation();
  assert.ok(directScript !== null && directScript.includes("def ts_pdc_rhs("));
  assert.equal(capturedModalCode, directScript);

  // 5. Validação científica independente em Python:
  //    - Conformidade estrita do PDCController contra contracts/schemas/controller.schema.json;
  //    - Malha aberta instável (max Re λ(A_i) > 0) vs malha fechada A_i + sign*B_i*K_i e pares Tuan/Tanaka Hurwitz estáveis;
  //    - Execução numérica da EDO exportada (ts_pdc_rhs + default_h_fn) convergindo exponencialmente a zero.
  const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
  const cpModId = "node:child_process";
  const { spawnSync } = (await import(cpModId)) as {
    spawnSync: (
      cmd: string,
      args: string[],
      opts: Record<string, unknown>,
    ) => { status: number | null; stdout: string; stderr: string };
  };
  const pyCheck = spawnSync(
    "python3",
    [
      "-c",
      [
        "import sys, json, pathlib, numpy as np, scipy.integrate",
        "from jsonschema import Draft202012Validator",
        "from referencing import Registry, Resource",
        "from control_lab.core.controllers import PDCController",
        "payload = json.load(sys.stdin)",
        "schemas_dir = pathlib.Path('contracts/schemas')",
        "reg = Registry()",
        "for sp in schemas_dir.glob('*.schema.json'):",
        "    raw_s = json.loads(sp.read_text(encoding='utf-8'))",
        "    res = Resource.from_contents(raw_s)",
        "    reg = reg.with_resource(raw_s['$id'], res).with_resource(sp.name, res)",
        "ctrl_schema = json.loads((schemas_dir / 'controller.schema.json').read_text(encoding='utf-8'))",
        "Draft202012Validator(ctrl_schema, registry=reg).validate(payload['controller'])",
        "pdc = PDCController.from_dict(payload['controller'])",
        "ns = {}",
        "exec(compile(payload['script'], '<exported_ts_pdc_pathsim>', 'exec'), ns)",
        "A_list = ns['A_vertices']",
        "B_list = ns['B_vertices']",
        "K_list = ns['K_vertices']",
        "s = float(ns['sign_factor'])",
        "open_max_real = max(float(np.max(np.linalg.eigvals(Ai).real)) for Ai in A_list)",
        "cl_diag_max_real = max(float(np.max(np.linalg.eigvals(Ai + s * (Bi @ Ki)).real)) for Ai, Bi, Ki in zip(A_list, B_list, K_list))",
        "cl_pair_max_real = -1e9",
        "for i in range(len(A_list)):",
        "    for j in range(i + 1, len(A_list)):",
        "        Mij = 0.5 * ((A_list[i] + s * (B_list[i] @ K_list[j])) + (A_list[j] + s * (B_list[j] @ K_list[i])))",
        "        cl_pair_max_real = max(cl_pair_max_real, float(np.max(np.linalg.eigvals(Mij).real)))",
        "sol = scipy.integrate.solve_ivp(lambda t, x: ns['ts_pdc_rhs'](x, ns['default_h_fn'](x, t), np.zeros(1)), (0.0, 6.0), np.array([0.6, -0.5]))",
        "final_norm = float(np.linalg.norm(sol.y[:, -1]))",
        "print(json.dumps({'open_max_real': open_max_real, 'cl_diag_max_real': cl_diag_max_real, 'cl_pair_max_real': cl_pair_max_real, 'final_norm': final_norm, 'n_rules': pdc.n_rules}))",
      ].join("\n"),
    ],
    {
      cwd: repoRoot,
      input: JSON.stringify({ controller: storedPdc, script: scriptContent }),
      encoding: "utf8",
      timeout: 30000,
    },
  );
  assert.equal(pyCheck.status, 0, `Validação Python do PDC/PathSim falhou: ${pyCheck.stderr}`);
  const metrics = JSON.parse(pyCheck.stdout) as {
    open_max_real: number;
    cl_diag_max_real: number;
    cl_pair_max_real: number;
    final_norm: number;
    n_rules: number;
  };
  assert.equal(metrics.n_rules, 3);
  assert.ok(
    metrics.open_max_real > 0.1,
    `Planta em malha aberta deveria ser instável (> 0.1), obtido ${metrics.open_max_real}`,
  );
  assert.ok(
    metrics.cl_diag_max_real < -1e-3,
    `Malha fechada nos vértices A_i + s B_i K_i deve ser Hurwitz estável (< 0), obtido ${metrics.cl_diag_max_real}`,
  );
  assert.ok(
    metrics.cl_pair_max_real < -1e-3,
    `Pares relaxados Tuan/Tanaka devem ser Hurwitz estáveis (< 0), obtido ${metrics.cl_pair_max_real}`,
  );
  assert.ok(
    metrics.final_norm < 1e-2,
    `Trajetória fechada de ts_pdc_rhs deve convergir para a origem, obtido ||x(6)||=${metrics.final_norm}`,
  );

  // 6. Guarda de obsolescência: editar a DSL após solveLmi deve desabilitar imediatamente registro e exportação!
  const editorEl = root.querySelector<FakeElement>("#lmi-code-editor")!;
  editorEl.value = `${editorEl.value}\n# edicao posterior`;
  editorEl.dispatchEvent("input");
  assert.equal(regCtrlBtn.disabled, true, "Editar DSL deve invalidar registro do controlador anterior");
  assert.equal(exportPathSimBtn.disabled, true, "Editar DSL deve invalidar exportação PathSim anterior");

  // 7. Sistema LTI StateSpace com template lqr_lmi (-B*Y -> feedback_sign='negative'):
  //    extrai StateFeedbackController, registra no Workspace e exporta PathSim LTI estável.
  const lqrPlant = app.shell.getLqrWorkspace().getPlant();
  const ssSel = root.querySelector<FakeElement>("#lmi-workspace-system-select")!;
  const ssKey = `${encodeURIComponent(lqrPlant.id)}#${lqrPlant.revision}`;
  ssSel.value = ssKey;
  ssSel.dispatchEvent("change");

  tplSelect.value = "lqr_lmi";
  tplSelect.dispatchEvent("change");
  root.querySelector<FakeElement>("#btn-lmi-solve")!.click();
  await flushAsync(150);

  assert.equal(regCtrlBtn.disabled, false);
  assert.equal(exportPathSimBtn.disabled, false);
  regCtrlBtn.click();
  await flushAsync(80);

  const storedSf = await app.client.getObject(projectId, `sf-${lqrPlant.id}`, 1);
  assert.ok(storedSf !== null, "StateFeedbackController deve ser registrado no Workspace");
  assert.equal(storedSf!.kind, "StateFeedbackController");
  assert.equal(storedSf!.feedback_sign, "negative", "Template lqr_lmi (-B*Y) deve produzir feedback_sign='negative'");

  exportPathSimBtn.click();
  await flushAsync(80);
  const ltiScript = root.querySelector<FakeElement>("#export-modal-content")!.textContent;
  assert.ok(ltiScript.includes("duration ="), "Script PathSim LTI deve ser gerado sem erros");

  // 8. Bloqueio ADR-006 / ADR-013 para polytopic_uncertain: PathSim e PDC bloqueados!
  const polyReg = await app.shell.getTypedWorkspace().registerTypedObject({
    schema_version: "1.0.0",
    id: "poly-uncertain-2v",
    revision: 1,
    kind: "polytopic_uncertain",
    dt: null,
    state_names: ["x1", "x2"],
    input_names: ["u1"],
    output_names: ["y1"],
    units: { time: "s", states: ["", ""], inputs: [""], outputs: [""] },
    domain: { bounds: {} },
    premise_availability: {
      mode: "polytopic_unknown",
      measured_premises: [],
      unmeasured_premises: [],
    },
    membership_spec: {
      version: "1.0.0",
      premise_variables: [],
      functions: [],
    },
    vertices: [
      {
        vertex_id: "v1",
        A: { shape: [2, 2], dtype: "float64", order: "C", data: [0, 1, -1, -0.5] },
        B: { shape: [2, 1], dtype: "float64", order: "C", data: [0, 1] },
        C: { shape: [1, 2], dtype: "float64", order: "C", data: [1, 0] },
        D: { shape: [1, 1], dtype: "float64", order: "C", data: [0] },
      },
      {
        vertex_id: "v2",
        A: { shape: [2, 2], dtype: "float64", order: "C", data: [0, 1, -2, -0.8] },
        B: { shape: [2, 1], dtype: "float64", order: "C", data: [0, 1] },
        C: { shape: [1, 2], dtype: "float64", order: "C", data: [1, 0] },
        D: { shape: [1, 1], dtype: "float64", order: "C", data: [0] },
      },
    ],
    provenance: { source: "test" },
  });
  ssSel.value = polyReg.key;
  ssSel.dispatchEvent("change");
  tplSelect.value = "polytopic_robust";
  tplSelect.dispatchEvent("change");
  root.querySelector<FakeElement>("#btn-lmi-solve")!.click();
  await flushAsync(120);
  assert.equal(
    exportPathSimBtn.disabled,
    true,
    "#btn-lmi-export-pathsim deve permanecer desabilitado para polytopic_uncertain (ADR-006/ADR-013)",
  );

  app.destroy();
});

test("Segurança R-21: módulos das Abas 6 e 7 não contêm eval ou construtor dinâmico Function", () => {
  const files = [
    fileURLToPath(new URL("../../../web/features/ts_modeling/symbolic_qlpv_ast.ts", import.meta.url)),
    fileURLToPath(new URL("../../../web/features/views/ts_modeling_view.ts", import.meta.url)),
    fileURLToPath(new URL("../../../web/features/views/lmi_view.ts", import.meta.url)),
    fileURLToPath(new URL("../../../web/charts/ts_modeling_charts.ts", import.meta.url)),
  ];
  for (const p of files) {
    const raw = fs.readFileSync(p, "utf8");
    const src = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    assert.equal(/\beval\s*\(/.test(src), false, `eval proibido em ${p}`);
    assert.equal(/\bnew\s+Function\b/.test(src), false, `construtor Function proibido em ${p}`);
  }
});
