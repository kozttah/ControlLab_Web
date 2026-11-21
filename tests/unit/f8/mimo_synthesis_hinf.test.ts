/**
 * Testes unitários de WP-PHASE2-B3-F8-MIMO-SYNTHESIS-HINF-UI (F8: f8-ui-charts)
 *
 * Verificam ponta a ponta com motor científico Python real (`control_lab.core.rpc`):
 * 1. Quadro 1 — Desacoplador SVD (`mimo.design_decoupler`), comparação κ(G), ||Λ - I||,
 *    heatmap RGA pós-desacoplamento e registro da planta desacoplada no Workspace.
 * 2. Quadro 1 — Simulação em Malha Fechada (`mimo.simulate_closed_loop`) com e sem
 *    desacoplador em série, resumo de estabilidade/acoplamento/polos e gráfico SVG.
 * 3. Quadro 2 — Síntese Robusta H∞ (`mimo.design_hinf`) com Planta Generalizada P(s),
 *    resumo γ / ||T_zw||∞ / dimensões P(s), gráfico SVG σ̄(S), σ̄(T) vs 1/|W_S|, 1/|W_T|
 *    e registro do controlador K∞ no Workspace.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  ControlLabBridgeError,
  RPC_API_VERSION,
  type CapabilityDescriptor,
  type EngineLifecycleState,
  type ExecutionMetrics,
  type RpcRequest,
  type RpcResponse,
} from "../../../web/bridge/protocol.ts";
import {
  createInitialExecutionMetrics,
  type CommitProjectInput,
  type CommitProjectResult,
  type ControlLabEngineClient,
  type EngineClientEvent,
  type EngineEventListener,
  type ExecuteOptions,
  type RegisteredObjectRef,
  type RegisterObjectOptions,
} from "../../../web/bridge/client.ts";
import type { PortableProjectSnapshot } from "../../../web/storage/indexeddb_store.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import { cpythonLoader } from "../f7/cpython_runtime.mjs";

class FakeElement {
  public tagName: string;
  public id = "";
  public className = "";
  public value = "";
  public checked = false;
  public disabled = false;
  public min = "";
  public max = "";
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
    if (name === "min") this.min = s;
    if (name === "max") this.max = s;
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

  public dispatchEvent(
    type: string | { type: string; [key: string]: unknown },
    evInit?: Record<string, unknown>,
  ): boolean {
    const evType = typeof type === "string" ? type : type.type;
    const base: Record<string, unknown> = typeof type === "string" ? {} : type;
    const evObj = {
      ...base,
      ...(evInit ?? {}),
      type: evType,
      target: (evInit?.target ?? base.target ?? this) as unknown,
      currentTarget: this,
      preventDefault() {},
    };
    for (const fn of this.listeners.get(evType) ?? []) {
      fn(evObj);
    }
    if (
      this.parentNode &&
      evInit?.bubbles !== false &&
      (evType === "change" || evType === "input" || evType === "click")
    ) {
      for (const fn of this.parentNode.listeners.get(evType) ?? []) {
        fn({ ...evObj, currentTarget: this.parentNode });
      }
    }
    return true;
  }

  public focus(): void {
    this.ownerDocument.activeElement = this;
  }

  public closest(selector: string): FakeElement | null {
    let cur: FakeElement | null = this;
    while (cur) {
      if (matchesSimpleSelector(cur, selector)) return cur;
      cur = cur.parentNode;
    }
    return null;
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
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  while ((match = tokenRe.exec(html)) !== null) {
    if (match.index > lastIdx) {
      const text = html.slice(lastIdx, match.index);
      const cur = stack[stack.length - 1];
      if (cur && cur !== rootParent) {
        cur.appendText(text);
        if (cur.tagName === "TEXTAREA") {
          cur.value += text
            .replaceAll("&amp;", "&")
            .replaceAll("&lt;", "<")
            .replaceAll("&gt;", ">")
            .replaceAll("&quot;", '"')
            .replaceAll("&#39;", "'");
        }
      }
    }
    lastIdx = tokenRe.lastIndex;
    const isClosing = match[1] === "/";
    const tag = match[2].toLowerCase();
    const attrText = match[3];
    const isSelfClosing = match[4] === "/" || voidTags.has(tag);

    if (isClosing) {
      for (let i = stack.length - 1; i >= 1; i -= 1) {
        if (stack[i].tagName === tag.toUpperCase()) {
          stack.length = i;
          break;
        }
      }
      continue;
    }

    const el = doc.createElement(tag);
    const attrRe = /([a-zA-Z0-9_:-]+)(?:="([^"]*)")?/g;
    let am: RegExpExecArray | null;
    while ((am = attrRe.exec(attrText)) !== null) {
      el.setAttribute(am[1], am[2] ?? "");
    }
    const parent = stack[stack.length - 1];
    el.parentNode = parent;
    parent.children.push(el);
    if (parent === rootParent) {
      topNodes.push(el);
    }
    if (!isSelfClosing) {
      stack.push(el);
    }
  }
  return topNodes;
}

class CpythonMimoBridgeClient implements ControlLabEngineClient {
  public readonly executedRequests: RpcRequest[] = [];
  private readonly store = new Map<
    string,
    {
      project_id: string;
      object_id: string;
      revision: number;
      kind: string;
      value: Record<string, unknown>;
      persisted: boolean;
    }
  >();

  public async init(): Promise<CapabilityDescriptor> {
    return this.getCapabilities();
  }

  public getLifecycleState(): EngineLifecycleState {
    return "ready";
  }

  public subscribe(_listener: EngineEventListener): () => void {
    return () => {};
  }

  public emit(_event: EngineClientEvent): void {}

  public async initialize(): Promise<void> {}

  public getCapabilities(): CapabilityDescriptor {
    return {
      api_version: RPC_API_VERSION,
      engine_kind: "pyodide",
      runtime_id: "test-f8-mimo-synthesis-hinf",
      operations: [
        "mimo.design_decoupler",
        "mimo.simulate_closed_loop",
        "mimo.design_hinf",
      ],
      backends: {
        numpy_scipy: { available: true, maturity: "beta" },
        native_primal_dual: { available: true, maturity: "beta" },
      },
      maturity: {
        "mimo.design_decoupler": "beta",
        "mimo.simulate_closed_loop": "beta",
        "mimo.design_hinf": "beta",
      },
      supports_transferables: true,
      supports_cooperative_cancel: true,
      max_memory_bytes: 256 * 1024 * 1024,
      lib_versions: { python: "3.12", numpy: "2.0", scipy: "1.14", control_lab: "1.0.0" },
      offline_ready: false,
    };
  }

  public getMetrics(): ExecutionMetrics {
    return createInitialExecutionMetrics();
  }

  public getCommittedRevision(): number {
    return 1;
  }

  public async syncAdoptedProjectState(): Promise<void> {}

  private materializeRefs(
    projectId: string,
    operation: string,
    payload: Record<string, unknown>,
  ): Record<string, unknown> {
    const out = structuredClone(payload);
    const lookup = (refField: string, targetField: string) => {
      const ref = out[refField] as { id?: string; revision?: number } | undefined;
      if (ref && typeof ref.id === "string" && typeof ref.revision === "number") {
        let entry = this.store.get(`${projectId}::${ref.id}#${ref.revision}`);
        if (!entry) {
          for (const [k, v] of this.store.entries()) {
            if (k.endsWith(`::${ref.id}#${ref.revision}`)) {
              entry = v;
              break;
            }
          }
        }
        if (!entry) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Referência ${refField} (${ref.id}#${ref.revision}) não encontrada.`,
          );
        }
        out[targetField] = structuredClone(entry.value);
        delete out[refField];
      }
    };
    if (operation.startsWith("mimo.") || operation.startsWith("frequency.")) {
      lookup("plant_ref", "plant");
      lookup("model_ref", "plant");
      lookup("controller_ref", "controller");
      lookup("decoupler_ref", "decoupler");
    }
    return out;
  }

  public async execute(request: RpcRequest, _options?: ExecuteOptions): Promise<RpcResponse> {
    this.executedRequests.push(structuredClone(request));
    const materialized = this.materializeRefs(
      request.project_id,
      request.operation,
      request.payload,
    );
    const loaded = await cpythonLoader({ indexURL: "", packages: [] });
    const pyodide = loaded.pyodide;
    if (!pyodide.pyimport || !pyodide.toPy) {
      throw new Error("cpythonLoader não expôs pyimport/toPy.");
    }
    const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
      dispatch: (arg: unknown) => RpcResponse;
      destroy?: () => void;
    };
    const proxy = pyodide.toPy({ request, payload: materialized });
    const rawResp = rpcMod.dispatch(proxy);
    proxy.destroy();
    rpcMod.destroy?.();
    return rawResp;
  }

  public async cancel(): Promise<boolean> {
    return false;
  }

  public async resetWorker(): Promise<void> {}

  public async registerObject(
    project_id: string,
    id: string,
    revision: number,
    value: Record<string, unknown>,
    options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef> {
    const kind = options?.kind ?? String(value.kind ?? "unknown");
    const persisted = options?.persistToIndexedDB ?? false;
    this.store.set(`${project_id}::${id}#${revision}`, {
      project_id,
      object_id: id,
      revision,
      kind,
      value: structuredClone(value),
      persisted,
    });
    return { project_id, object_id: id, revision, persisted, cached_in_worker: true };
  }

  public async getObject(
    project_id: string,
    id: string,
    revision: number,
  ): Promise<Record<string, unknown> | null> {
    const found = this.store.get(`${project_id}::${id}#${revision}`);
    return found ? structuredClone(found.value) : null;
  }

  public async commitProject(
    projectId: string,
    revision: number,
    _input?: CommitProjectInput,
  ): Promise<CommitProjectResult> {
    return {
      committed: true,
      project: {
        project_id: projectId,
        committed_revision: revision,
        last_request_id: null,
        last_committed_result: null,
        active_object_refs: [],
        updated_at: "2026-11-21T00:00:00Z",
        metadata: {},
      },
      snapshot: {
        snapshot_key: `${projectId}:${revision}`,
        schema_version: "1.0.0",
        project_id: projectId,
        project_revision: revision,
        confirmed: true,
        objects: [],
        experiments: [],
        committed_result: null,
        pinned: true,
        content_hash: "0".repeat(64),
        created_at: "2026-11-21T00:00:00Z",
      },
    };
  }

  public async exportProject(project_id: string): Promise<PortableProjectSnapshot> {
    return {
      format: "controllab_snapshot",
      schema_version: "1.0.0",
      project_id,
      project_revision: 1,
      objects: [],
      experiments: [],
      committed_result: null,
      content_hash: "0".repeat(64),
      exported_at: "2026-11-21T00:00:00Z",
    };
  }

  public dispose(): void {}
}

async function flushAsync(): Promise<void> {
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
}

test("WP-PHASE2-B3-F8-MIMO-SYNTHESIS-HINF-UI: Desacoplador SVD, Malha Fechada canal-a-canal e Síntese H∞", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const client = new CpythonMimoBridgeClient();

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
  });

  // Navega para Aba 4 (MIMO) e carrega planta MIMO 2x2 acoplada
  app.shell.switchTab("mimo_frequency");
  root.querySelector<FakeElement>('[data-action="mimo-load-example"]')?.dispatchEvent("click");
  await flushAsync();

  const synthesisCard = root.querySelector<FakeElement>("#mimo-synthesis-card");
  const hinfCard = root.querySelector<FakeElement>("#mimo-hinf-card");
  assert.ok(synthesisCard, "Quadro #mimo-synthesis-card deve existir");
  assert.ok(hinfCard, "Quadro #mimo-hinf-card deve existir");

  // 1. Workflow SVD Decoupler (modo automático)
  const omegaEl = root.querySelector<FakeElement>("#mimo-decoupler-omega");
  const modeEl = root.querySelector<FakeElement>("#mimo-decoupler-mode");
  assert.ok(omegaEl && modeEl);
  omegaEl.value = "1.0";
  modeEl.value = "auto";

  root.querySelector<FakeElement>('[data-action="mimo-design-decoupler"]')?.dispatchEvent("click");
  await flushAsync();

  const decReq = client.executedRequests.find((r) => r.operation === "mimo.design_decoupler");
  assert.ok(decReq, "RPC mimo.design_decoupler deve ser executado");
  assert.equal(decReq.payload.realization_mode, "auto");
  assert.equal(decReq.payload.omega_target, 1.0);

  const decSummaryHtml = root.querySelector<FakeElement>("#mimo-decoupler-summary")?.innerHTML ?? "";
  assert.ok(decSummaryHtml.includes("Ordem do desacoplador:"), "Resumo deve exibir ordem do desacoplador");
  assert.ok(decSummaryHtml.includes("Condicionamento κ(G):"), "Resumo deve exibir κ(G) antes vs depois");
  assert.ok(decSummaryHtml.includes("||Λ − I||"), "Resumo deve exibir norma off-diagonal da RGA");
  assert.ok(decSummaryHtml.includes("RGA pós-desacoplamento"), "Resumo deve exibir tabela RGA pós-desacoplamento");

  const useDecouplerCb = root.querySelector<FakeElement>("#mimo-cl-use-decoupler");
  assert.equal(useDecouplerCb?.checked, true, "Checkbox do desacoplador deve marcar automaticamente após projeto");

  const btnRegDec = root.querySelector<FakeElement>("#btn-mimo-register-decoupler");
  assert.equal(btnRegDec?.disabled, false, "Botão de registrar planta desacoplada deve habilitar");
  btnRegDec?.dispatchEvent("click");
  await flushAsync();

  // 2. Workflow Simulação em Malha Fechada (Degrau Canal-a-Canal)
  const gainsEl = root.querySelector<FakeElement>("#mimo-cl-gains");
  const tFinalEl = root.querySelector<FakeElement>("#mimo-cl-t-final");
  assert.ok(gainsEl && tFinalEl);
  gainsEl.value = "1.0, 1.0";
  tFinalEl.value = "8.0";

  root.querySelector<FakeElement>('[data-action="mimo-simulate-cl"]')?.dispatchEvent("click");
  await flushAsync();

  const clReq = client.executedRequests.find((r) => r.operation === "mimo.simulate_closed_loop");
  assert.ok(clReq, "RPC mimo.simulate_closed_loop deve ser executado");
  assert.deepEqual(clReq.payload.controller_gains, [1.0, 1.0]);
  assert.ok(clReq.payload.decoupler, "Decoupler deve ser enviado quando checkbox marcado");
  assert.equal(clReq.payload.n_points, 160);

  const clSummaryHtml = root.querySelector<FakeElement>("#mimo-cl-summary")?.innerHTML ?? "";
  assert.ok(clSummaryHtml.includes("Estável ✓"), "Resumo de malha fechada deve indicar estabilidade");
  assert.ok(clSummaryHtml.includes("Acoplamento cruzado máximo:"), "Resumo deve exibir max_cross_coupling");
  assert.ok(clSummaryHtml.includes("Polos de malha fechada:"), "Resumo deve exibir polos");

  const clSvgHtml = root.querySelector<FakeElement>("#mimo-cl-chart-slot")?.innerHTML ?? "";
  assert.ok(clSvgHtml.includes("<svg"), "Gráfico SVG de resposta ao degrau MIMO deve ser renderizado");
  assert.ok(clSvgHtml.includes("r1→y1") && clSvgHtml.includes("r1→y2"), "Gráfico deve incluir canais diagonais e cruzados");

  // 3. Workflow Síntese Robusta H∞ (Planta Generalizada P(s))
  const wsDcEl = root.querySelector<FakeElement>("#hinf-ws-dc");
  const wsWbEl = root.querySelector<FakeElement>("#hinf-ws-wb");
  const wsMsEl = root.querySelector<FakeElement>("#hinf-ws-ms");
  const wuGainEl = root.querySelector<FakeElement>("#hinf-wu-gain");
  const wtWbEl = root.querySelector<FakeElement>("#hinf-wt-wb");
  const wtMtEl = root.querySelector<FakeElement>("#hinf-wt-mt");
  assert.ok(wsDcEl && wsWbEl && wsMsEl && wuGainEl && wtWbEl && wtMtEl);

  root.querySelector<FakeElement>('[data-action="mimo-design-hinf"]')?.dispatchEvent("click");
  await flushAsync();

  const hinfReq = client.executedRequests.find((r) => r.operation === "mimo.design_hinf");
  assert.ok(hinfReq, "RPC mimo.design_hinf deve ser executado");

  const hinfSummaryHtml = root.querySelector<FakeElement>("#mimo-hinf-summary")?.innerHTML ?? "";
  assert.ok(hinfSummaryHtml.includes("γ atingido:"), "Resumo H∞ deve exibir gamma_achieved");
  assert.ok(hinfSummaryHtml.includes("||T_zw||∞ (grade):"), "Resumo H∞ deve exibir hinf_norm_grid");
  assert.ok(hinfSummaryHtml.includes("n_states="), "Resumo H∞ deve exibir generalized_plant_summary");

  const hinfSvgHtml = root.querySelector<FakeElement>("#mimo-hinf-chart-slot")?.innerHTML ?? "";
  assert.ok(hinfSvgHtml.includes("<svg"), "Gráfico SVG H∞ deve ser renderizado");
  assert.ok(hinfSvgHtml.includes("σ̄(S)") && hinfSvgHtml.includes("1/|W_S|"), "Gráfico H∞ deve exibir σ̄(S) e limite 1/|W_S|");

  const btnRegHinf = root.querySelector<FakeElement>("#btn-mimo-register-hinf");
  assert.equal(btnRegHinf?.disabled, false, "Botão de registrar K∞ deve habilitar após síntese");
  btnRegHinf?.dispatchEvent("click");
  await flushAsync();

  const regObjects = app.shell.getTypedWorkspace().listRegisteredObjects();
  assert.ok(regObjects.length >= 3, "Planta exemplo, planta desacoplada e controlador K∞ devem estar registrados");
});

test("WP-PHASE2-D3-F8-MULTIFREQ-UI: Desacoplador SVD multi-frequência suporta modo automático e ordem explícita, exibindo ordem, erro de ajuste e tabelas", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const client = new CpythonMimoBridgeClient();

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
  });

  app.shell.switchTab("mimo_frequency");
  root.querySelector<FakeElement>('[data-action="mimo-load-example"]')?.dispatchEvent("click");
  await flushAsync();

  const omegaEl = root.querySelector<FakeElement>("#mimo-decoupler-omega");
  const modeEl = root.querySelector<FakeElement>("#mimo-decoupler-mode");
  assert.ok(omegaEl && modeEl, "Controles #mimo-decoupler-omega e #mimo-decoupler-mode devem existir");
  assert.equal(omegaEl.getAttribute("type"), "text", "#mimo-decoupler-omega deve ser type='text'");

  // 1) Modo automático ("auto")
  omegaEl.value = "0.1, 1.0, 10.0";
  modeEl.value = "auto";

  root.querySelector<FakeElement>('[data-action="mimo-design-decoupler"]')?.dispatchEvent("click");
  await flushAsync();

  const decReqsAuto = client.executedRequests.filter((r) => r.operation === "mimo.design_decoupler");
  assert.equal(decReqsAuto.length, 1, "RPC mimo.design_decoupler deve ser executado em modo auto");
  const decReqAuto = decReqsAuto[0];
  assert.equal(decReqAuto.payload.realization_mode, "auto");
  assert.equal(decReqAuto.payload.order, undefined);
  assert.deepEqual(decReqAuto.payload.omega_targets, [0.1, 1.0, 10.0]);
  assert.equal(decReqAuto.payload.omega_target, 1.0);

  const summaryEl = root.querySelector<FakeElement>("#mimo-decoupler-summary");
  assert.ok(summaryEl, "#mimo-decoupler-summary deve existir");
  const autoHtml = summaryEl.innerHTML;
  assert.ok(autoHtml.includes("Ordem do desacoplador:"), "Resumo deve exibir ordem do desacoplador");
  assert.ok(autoHtml.includes("(automática)"), "Resumo deve indicar modo automático");
  assert.ok(
    /Ordem do desacoplador:<\/strong>\s*<code>\d+<\/code>\s*\(automática\)/.test(autoHtml),
    "Resumo deve exibir orderUsed numérico com (automática)",
  );
  assert.ok(
    autoHtml.includes("Erro de ajuste em frequência:") && autoHtml.includes("%"),
    "Resumo deve exibir erro de ajuste em frequência em %",
  );

  const perFreqTable = summaryEl.querySelector<FakeElement>(
    'table[aria-label="Comparação por frequência do desacoplador"]',
  );
  assert.ok(perFreqTable, "Tabela comparativa por frequência deve ser renderizada");
  assert.ok(
    perFreqTable.className.includes("mimo-rga-table") &&
      perFreqTable.className.includes("accessible-data-table"),
    "Tabela comparativa deve reutilizar classes .accessible-data-table .mimo-rga-table",
  );
  const perFreqTbody = perFreqTable.querySelector<FakeElement>("tbody");
  assert.ok(perFreqTbody, "Tabela comparativa deve ter tbody");
  const perFreqRows = perFreqTbody.querySelectorAll<FakeElement>("tr");
  assert.equal(perFreqRows.length, 3, "Tabela comparativa deve conter 3 linhas (0.1, 1.0, 10.0)");

  const rgaAfterTable = summaryEl.querySelector<FakeElement>(
    'table[aria-label="RGA pós-desacoplamento"]',
  );
  assert.ok(rgaAfterTable, "Tabela RGA pós-desacoplamento deve ser renderizada");

  // 2) Modo manual com ordem explícita "2"
  modeEl.value = "2";
  root.querySelector<FakeElement>('[data-action="mimo-design-decoupler"]')?.dispatchEvent("click");
  await flushAsync();

  const decReqsAll = client.executedRequests.filter((r) => r.operation === "mimo.design_decoupler");
  assert.equal(decReqsAll.length, 2, "Segunda chamada mimo.design_decoupler deve ser executada");
  const decReqManual = decReqsAll[1];
  assert.equal(decReqManual.payload.realization_mode, "rational");
  assert.equal(decReqManual.payload.order, 2);

  const manualHtml = summaryEl.innerHTML;
  assert.ok(
    /Ordem do desacoplador:<\/strong>\s*<code>2<\/code>\s*\(manual\)/.test(manualHtml),
    "Resumo deve exibir orderUsed === 2 e orderMode === 'manual'",
  );
  assert.ok(
    manualHtml.includes("Erro de ajuste em frequência:") && manualHtml.includes("%"),
    "Resumo em modo manual deve exibir erro de ajuste em frequência em %",
  );
});

