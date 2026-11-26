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
import type { RpcRequest, RpcResponse } from "../../../web/bridge/protocol.ts";
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
  substitutePremises,
  TS_PRESETS,
  TsModelingView,
} from "../../../web/features/views/ts_modeling_view.ts";
import { cpythonLoader } from "../f7/cpython_runtime.mjs";

class RealPythonTsAdapter extends MockWorkerAdapter {
  protected override async dispatchRpc(
    request: RpcRequest,
    options?: Parameters<MockWorkerAdapter["execute"]>[1],
  ): Promise<{ response: RpcResponse; bridgeTransferMs?: number }> {
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

test("Segurança R-21: módulos da Aba 6 não contêm eval ou construtor dinâmico Function", () => {
  const files = [
    fileURLToPath(new URL("../../../web/features/ts_modeling/symbolic_qlpv_ast.ts", import.meta.url)),
    fileURLToPath(new URL("../../../web/features/views/ts_modeling_view.ts", import.meta.url)),
    fileURLToPath(new URL("../../../web/charts/ts_modeling_charts.ts", import.meta.url)),
  ];
  for (const p of files) {
    const raw = fs.readFileSync(p, "utf8");
    const src = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    assert.equal(/\beval\s*\(/.test(src), false, `eval proibido em ${p}`);
    assert.equal(/\bnew\s+Function\b/.test(src), false, `construtor Function proibido em ${p}`);
  }
});
