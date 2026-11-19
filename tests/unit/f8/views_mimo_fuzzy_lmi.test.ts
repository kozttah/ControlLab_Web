/**
 * Testes unitários de WP-UX-REFACTOR-03-MIMO-FUZZY-LMI (F8: f8-ui-charts)
 *
 * Verificam ponta a ponta com motor científico Python real (`control_lab.core.rpc`):
 * 1. Isolamento estrito entre as 6 abas, `.single-main-col` e ordenação DOM.
 * 2. Parser determinístico `lmi_dsl_parser.ts` (templates, `bmat`, aviso bilinear `K*Q`,
 *    formatação matemática e ausência absoluta de `eval` / `new Function`).
 * 3. `LmiView` (Aba 6): editor estilo Monaco, gutter de linhas, salvar/carregar/exportar `.lmi`,
 *    exportação CVXPY/YALMIP disponível antes da solução (ADR-010), `optimization.solve`,
 *    `optimization.verify`, certificado 5D e espectro LMI SVG.
 * 4. `MimoView` (Aba 4): exemplo 2×2 acoplado em 1 clique, `mimo.singular_values` +
 *    `mimo.sensitivity` + toggles de curva + `[SVG]`/`[PNG]`, slider RGA `Λ(G(jω))` e
 *    diagnóstico explícito de matriz singular (`RGA indefinida`).
 * 5. `FuzzyView` (Aba 5): modelo inicial canônico, editor visual/numérico de MFs, matriz
 *    de regras 2D, banner científico estático vs `TSStateSpace`, `fuzzy.evaluate_surface`,
 *    `fuzzy.evaluate` e round-trip IEEE 1855-2016 (`fuzzy.export_fml` / `fuzzy.import_fml`).
 */

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

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
import {
  LMI_DSL_TEMPLATES,
  parseLmiDsl,
} from "../../../web/features/views/lmi_dsl_parser.ts";
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

class PythonMimoFuzzyLmiClient implements ControlLabEngineClient {
  public readonly executedRequests: RpcRequest[] = [];
  private readonly store = new Map<
    string,
    { project_id: string; object_id: string; revision: number; kind: string; value: Record<string, unknown>; persisted: boolean }
  >();
  private readonly listeners = new Set<EngineEventListener>();
  private state: EngineLifecycleState = "ready";

  public async init(): Promise<CapabilityDescriptor> {
    this.state = "ready";
    return this.getCapabilities();
  }

  public getLifecycleState(): EngineLifecycleState {
    return this.state;
  }

  public getCapabilities(): CapabilityDescriptor {
    return {
      api_version: RPC_API_VERSION,
      engine_kind: "pyodide",
      runtime_id: "test-f8-mimo-fuzzy-lmi-python",
      operations: [
        "worker.ping",
        "core.capabilities",
        "mimo.singular_values",
        "mimo.rga",
        "mimo.sensitivity",
        "fuzzy.evaluate",
        "fuzzy.evaluate_surface",
        "fuzzy.import_fml",
        "fuzzy.export_fml",
        "optimization.solve",
        "optimization.verify",
        "optimization.export_cvxpy",
        "optimization.export_yalmip",
        "statespace.design_lqr",
        "statespace.analyze",
      ],
      backends: {
        numpy_scipy: { available: true, maturity: "beta" },
        native_primal_dual: { available: true, maturity: "beta" },
      },
      maturity: {
        "mimo.singular_values": "beta",
        "mimo.rga": "beta",
        "mimo.sensitivity": "beta",
        "fuzzy.evaluate": "beta",
        "fuzzy.evaluate_surface": "beta",
        "fuzzy.import_fml": "beta",
        "fuzzy.export_fml": "beta",
        "optimization.solve": "beta",
        "optimization.verify": "beta",
        "optimization.export_cvxpy": "beta",
        "optimization.export_yalmip": "beta",
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
    if (operation.startsWith("mimo.") || operation.startsWith("frequency.") || operation.startsWith("statespace.")) {
      lookup("plant_ref", "plant");
      lookup("model_ref", "plant");
      lookup("controller_ref", "controller");
    } else if (operation.startsWith("fuzzy.")) {
      lookup("system_ref", "system");
    } else if (operation.startsWith("optimization.")) {
      lookup("plant_ref", "plant");
      lookup("ts_model_ref", "ts_model");
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
        updated_at: "2026-11-19T00:00:00Z",
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
        created_at: "2026-11-19T00:00:00Z",
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
      exported_at: "2026-11-19T00:00:00Z",
    };
  }

  public subscribe(listener: EngineEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  public emit(ev: EngineClientEvent): void {
    for (const fn of this.listeners) fn(ev);
  }

  public dispose(): void {
    this.listeners.clear();
  }
}

test("WP-UX-REFACTOR-03: lmi_dsl_parser.ts (templates, bmat, detecção bilinear K*Q e zero eval/new Function)", () => {
  // 1. Static safety guard: strictly NO eval or new Function
  const parserPath = fileURLToPath(
    new URL("../../../web/features/views/lmi_dsl_parser.ts", import.meta.url),
  );
  const parserSource = fs.readFileSync(parserPath, "utf8");
  assert.equal(/\beval\s*\(/.test(parserSource), false, "lmi_dsl_parser.ts não pode usar eval(");
  assert.equal(/new\s+Function\b/.test(parserSource), false, "lmi_dsl_parser.ts não pode usar new Function");

  // 2. Starter template: Decaimento alpha + Estabilização
  const starter = parseLmiDsl(LMI_DSL_TEMPLATES[0].dsl);
  assert.equal(starter.valid, true);
  assert.equal(starter.inferredTemplate, "decay_rate");
  assert.equal(starter.inferredAlpha, 0.5);
  assert.equal(starter.inferredFeedbackSign, "positive");
  assert.equal(starter.variables.length, 2);
  assert.equal(starter.params[0].name, "alpha");
  assert.equal(starter.constraints[0].mathText, "Q ≻ 0");
  assert.ok(starter.constraints[1].mathText.includes("Aᵀ"));
  assert.ok(starter.constraints[1].mathText.includes("α"));
  assert.ok(starter.constraints[1].mathText.includes("≺ 0"));
  assert.ok(starter.recoveries[0].mathText.includes("Q⁻¹"));

  // 3. Multi-line bmat regional pole placement
  const regionalDsl = [
    "var Q sym(n)",
    "var Y rect(m, n)",
    "param radius = 4.0",
    "bmat([",
    "  [-radius*Q, A*Q + B*Y],",
    "  [(A*Q + B*Y)', -radius*Q]",
    "]) < 0",
  ].join("\n");
  const regParsed = parseLmiDsl(regionalDsl);
  assert.equal(regParsed.valid, true);
  assert.equal(regParsed.inferredTemplate, "regional_pole_placement");
  assert.equal(regParsed.inferredRadius, 4.0);
  assert.ok(regParsed.constraints[0].bmatRows !== null);
  assert.equal(regParsed.constraints[0].bmatRows?.length, 2);
  assert.ok(regParsed.constraints[0].mathHtml.includes("lmi-bmat-grid"));

  // 4. Pedagogical bilinear warning on K*Q
  const bmiParsed = parseLmiDsl([
    "var Q sym(n)",
    "Q > 0",
    "A*Q + Q*A' + B*K*Q + Q*K'*B' < 0",
  ].join("\n"));
  assert.equal(bmiParsed.bilinearWarnings.length > 0, true);
  assert.ok(bmiParsed.bilinearWarnings[0].token.includes("K*Q"));
  assert.ok(bmiParsed.bilinearWarnings[0].suggestion.includes("Y = K"));

  // 5. CanonicalSDPProblem JSON fallback
  const jsonTemplate = LMI_DSL_TEMPLATES.find((t) => t.id === "canonical_sdp_json")!;
  const jsonParsed = parseLmiDsl(jsonTemplate.dsl);
  assert.equal(jsonParsed.valid, true);
  assert.equal(jsonParsed.inferredTemplate, "canonical_sdp_json");
  assert.ok(jsonParsed.canonicalSdpOverride !== null);
});

test("WP-UX-REFACTOR-03: isolamento estrito das 6 abas, .single-main-col e ordem DOM", () => {
  const client = new PythonMimoFuzzyLmiClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-6tabs-isolation",
  });

  const mainEl = root.querySelector<FakeElement>("#controllab-main")!;
  const idPanel = root.querySelector<FakeElement>("#identification-workspace-panel")!;
  const sisoPanel = root.querySelector<FakeElement>("#siso-workspace-panel")!;
  const ssPanel = root.querySelector<FakeElement>("#statespace-workspace-panel")!;
  const mimoPanel = root.querySelector<FakeElement>("#mimo-workspace-panel")!;
  const fuzzyPanel = root.querySelector<FakeElement>("#fuzzy-workspace-panel")!;
  const lmiPanel = root.querySelector<FakeElement>("#lmi-workspace-panel")!;

  // Default statespace: Tabs 4, 5, 6 hidden
  assert.equal(app.shell.getActiveTab(), "statespace");
  assert.equal(mimoPanel.hasAttribute("hidden"), true);
  assert.equal(fuzzyPanel.hasAttribute("hidden"), true);
  assert.equal(lmiPanel.hasAttribute("hidden"), true);

  // Switch to Tab 4 (MIMO)
  app.shell.switchTab("mimo_frequency");
  assert.equal(mimoPanel.hasAttribute("hidden"), false);
  assert.equal(fuzzyPanel.hasAttribute("hidden"), true);
  assert.equal(lmiPanel.hasAttribute("hidden"), true);
  assert.equal(idPanel.hasAttribute("hidden"), true);
  assert.equal(sisoPanel.hasAttribute("hidden"), true);
  assert.ok(mainEl.className.includes("single-main-col"));

  // Switch to Tab 5 (Fuzzy)
  app.shell.switchTab("fuzzy_ts");
  assert.equal(fuzzyPanel.hasAttribute("hidden"), false);
  assert.equal(mimoPanel.hasAttribute("hidden"), true);
  assert.equal(lmiPanel.hasAttribute("hidden"), true);
  assert.ok(mainEl.className.includes("single-main-col"));

  // Switch to Tab 6 (LMI)
  app.shell.switchTab("optimization_lmi");
  assert.equal(lmiPanel.hasAttribute("hidden"), false);
  assert.equal(mimoPanel.hasAttribute("hidden"), true);
  assert.equal(fuzzyPanel.hasAttribute("hidden"), true);
  assert.ok(mainEl.className.includes("single-main-col"));

  // Verify DOM order inside #controllab-main first card
  const leftCard = mainEl.children[0];
  const sectionIds = leftCard.children.map((c) => c.id).filter(Boolean);
  assert.ok(sectionIds.indexOf("mimo-workspace-panel") < sectionIds.indexOf("typed-workspace-panel"));
  assert.ok(sectionIds.indexOf("fuzzy-workspace-panel") < sectionIds.indexOf("typed-workspace-panel"));
  assert.ok(sectionIds.indexOf("lmi-workspace-panel") < sectionIds.indexOf("typed-workspace-panel"));
  assert.ok(sectionIds.indexOf("statespace-workspace-panel") < sectionIds.indexOf("mimo-workspace-panel"));

  app.destroy();
});

test("WP-UX-REFACTOR-03: MimoView (planta 2x2, σ(G,S,T,KS), toggles, slider RGA e diagnóstico singular)", async () => {
  const client = new PythonMimoFuzzyLmiClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-mimo-view",
  });
  await app.client.init();

  app.shell.switchTab("mimo_frequency");

  // 1. Load 2x2 coupled example in 1 click
  root.querySelector('[data-action="mimo-load-example"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 40));
  assert.ok(root.querySelector("#mimo-active-plant-info")!.textContent.includes("ss-mimo-distillation-2x2"));

  // 2. Run MIMO Analysis via real Python
  root.querySelector<FakeElement>("#mimo-n-points")!.value = "12";
  root.querySelector('[data-action="mimo-analyze"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 250));

  const sigmaSlot = root.querySelector<FakeElement>("#mimo-sigma-chart-slot")!;
  assert.ok(sigmaSlot.innerHTML.includes("singular-values-chart"), "SVG de valores singulares deve ser renderizado");
  assert.ok(sigmaSlot.innerHTML.includes('data-curve-group="G"'));
  assert.ok(sigmaSlot.innerHTML.includes('data-curve-group="S"'));
  assert.ok(sigmaSlot.innerHTML.includes('data-curve-group="T"'));
  assert.equal(sigmaSlot.innerHTML.includes('data-curve-group="KS"'), false);

  const exportBar = root.querySelector<FakeElement>('[data-export-bar-for="mimo-sigma-chart-slot"]')!;
  assert.equal(exportBar.hasAttribute("hidden"), false, "Barra [SVG]/[PNG] MIMO deve ficar visível");
  assert.equal(root.querySelector("#mimo-sigma-table-slot")!.innerHTML.includes("accessible-data-table"), true);

  // Toggle KS curve on
  const ksCb = root.querySelector<FakeElement>("#mimo-toggle-KS")!;
  ksCb.checked = true;
  ksCb.dispatchEvent("change");
  assert.ok(sigmaSlot.innerHTML.includes('data-curve-group="KS"'));

  // 3. RGA slider moves across frequencies and updates Λ(G(jω)) + κ(G)
  const rgaSlider = root.querySelector<FakeElement>("#mimo-rga-omega-slider")!;
  assert.equal(rgaSlider.disabled, false);
  rgaSlider.value = "0";
  rgaSlider.dispatchEvent("input");
  const wLabel0 = root.querySelector("#mimo-rga-omega-label")!.textContent;
  const rgaHeatmap = root.querySelector<FakeElement>("#mimo-rga-heatmap-slot")!;
  assert.ok(rgaHeatmap.textContent.includes("Cond. κ(G)"));
  assert.ok(rgaHeatmap.innerHTML.includes("mimo-rga-table"));

  rgaSlider.value = "11";
  rgaSlider.dispatchEvent("input");
  const wLabel11 = root.querySelector("#mimo-rga-omega-label")!.textContent;
  assert.notEqual(wLabel0, wLabel11, "Slider RGA deve atualizar frequência exibida");

  // 4. Register singular 2x2 plant (zero row 2) -> RGA undefined diagnostic
  const singularSs = {
    schema_version: "1.0.0",
    id: "ss-mimo-singular",
    revision: 1,
    kind: "StateSpace",
    dt: null,
    state_names: ["x1", "x2"],
    input_names: ["u1", "u2"],
    output_names: ["y1", "y2"],
    matrices: {
      A: { shape: [2, 2], dtype: "float64", order: "C", data: [-1, 0, 0, -2] },
      B: { shape: [2, 2], dtype: "float64", order: "C", data: [1, 1, 0, 0] },
      C: { shape: [2, 2], dtype: "float64", order: "C", data: [1, 0, 0, 1] },
      D: { shape: [2, 2], dtype: "float64", order: "C", data: [0, 0, 0, 0] },
    },
    units: { time: "s", states: ["1", "1"], inputs: ["1", "1"], outputs: ["1", "1"] },
    provenance: { source: "test_singular" },
  };
  await app.shell.getTypedWorkspace().registerTypedObject(singularSs, { selectRole: "frequencyPlant" });
  root.querySelector('[data-action="mimo-analyze"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 250));
  assert.ok(rgaHeatmap.textContent.includes("RGA indefinida"));

  app.destroy();
});

test("WP-UX-REFACTOR-03: FuzzyView (MF editor, regras 2D, superfície, ponto e round-trip FML IEEE 1855-2016)", async () => {
  const client = new PythonMimoFuzzyLmiClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-fuzzy-view",
  });
  await app.client.init();

  app.shell.switchTab("fuzzy_ts");

  // 1. Starter FuzzySystem & scientific banner
  assert.ok(root.querySelector("#fuzzy-scientific-banner")!.textContent.includes("TSStateSpace"));
  assert.ok(root.querySelector("#fuzzy-mf-svg")!.innerHTML.includes("fuzzy-mf-svg"));
  assert.ok(root.querySelector("#fuzzy-rules-matrix")!.innerHTML.includes("fuzzy-rule-table"));
  assert.ok(root.querySelector("#fuzzy-coverage-status")!.textContent.includes("9 regras"));

  // 2. Edit numeric MF parameter (erro -> Z -> b) and verify SVG updates
  const paramInput = root.querySelector<FakeElement>(
    'input[data-fuzzy-term-idx="1"][data-fuzzy-param-idx="1"]',
  )!;
  paramInput.value = "1.5";
  paramInput.dispatchEvent("change");
  assert.ok(root.querySelector("#fuzzy-mf-svg")!.innerHTML.includes('data-mf-term="Z"'));

  // Reset back to 0 for clean surface
  paramInput.value = "0";
  paramInput.dispatchEvent("change");

  // 3. Edit a rule cell in 2D rule matrix
  const ruleSelect = root.querySelector<FakeElement>(
    'select[data-rule-t0="Z"][data-rule-t1="Z"]',
  )!;
  ruleSelect.value = "PM";
  ruleSelect.dispatchEvent("change");
  ruleSelect.value = "Z";
  ruleSelect.dispatchEvent("change");

  // 4. Register in typedWorkspace
  root.querySelector('[data-action="fuzzy-register"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 40));
  assert.ok(
    app.shell.getTypedWorkspace().listRegisteredObjects(["FuzzySystem"]).length >= 1,
  );

  // 5. Evaluate Control Surface via real Python
  root.querySelector<FakeElement>("#fuzzy-surface-n-points")!.value = "7";
  root.querySelector('[data-action="fuzzy-eval-surface"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 250));
  const surfSlot = root.querySelector<FakeElement>("#fuzzy-surface-chart-slot")!;
  assert.ok(surfSlot.innerHTML.includes("fuzzy-surface-chart"));
  assert.ok(root.querySelector("#fuzzy-surface-table-slot")!.innerHTML.includes("accessible-data-table"));
  assert.equal(
    root.querySelector('[data-export-bar-for="fuzzy-surface-chart-slot"]')!.hasAttribute("hidden"),
    false,
  );

  // 6. Evaluate point via real Python
  root.querySelector<FakeElement>("#fuzzy-point-x0")!.value = "5";
  root.querySelector<FakeElement>("#fuzzy-point-x1")!.value = "2.5";
  root.querySelector('[data-action="fuzzy-eval-point"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 150));
  assert.ok(root.querySelector("#fuzzy-point-result")!.textContent.includes("controle ="));

  // 7. Export & Import FML round-trip via real Python
  root.querySelector('[data-action="fuzzy-export-fml"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 150));
  const fmlBox = root.querySelector<FakeElement>("#fuzzy-fml-xml")!;
  assert.ok(fmlBox.value.includes("<fuzzySystem"), "Exportação FML deve preencher XML IEEE 1855-2016");
  assert.equal(
    root.querySelector("#controllab-export-modal")!.hasAttribute("hidden"),
    false,
  );
  root.querySelector("#export-modal-close")!.dispatchEvent("click");

  root.querySelector('[data-action="fuzzy-import-fml"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 150));
  assert.ok(root.querySelector("#fuzzy-coverage-status")!.textContent.includes("9 regras"));

  app.destroy();
});

test("WP-UX-REFACTOR-03: LmiView (editor Monaco, salvar/carregar, exportação CVXPY/YALMIP pré-solução, solve/verify 5D e espectro)", async () => {
  const client = new PythonMimoFuzzyLmiClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-lmi-view",
  });
  await app.client.init();

  app.shell.switchTab("optimization_lmi");

  // 1. Preloaded starter template & line gutter & live math reading
  const editor = root.querySelector<FakeElement>("#lmi-code-editor")!;
  const gutter = root.querySelector<FakeElement>("#lmi-line-gutter")!;
  assert.ok(editor.value.includes("param alpha = 0.5"));
  assert.ok(gutter.textContent.includes("1"));
  assert.ok(root.querySelector("#lmi-parsed-math")!.textContent.includes("Q ≻ 0"));
  assert.equal(root.querySelector("#lmi-syntax-badge")!.textContent, "Sintaxe OK");

  // 2. Live edit with bilinear warning, then restore
  const savedStarter = editor.value;
  editor.value = "var Q sym(n)\nQ > 0\nA*Q + Q*A' + B*K*Q < 0";
  editor.dispatchEvent("input");
  assert.equal(root.querySelector("#lmi-syntax-badge")!.textContent, "Aviso Bilinear (BMI)");
  assert.ok(root.querySelector("#lmi-parsed-alert")!.textContent.includes("K*Q"));

  // Restore valid starter and save preset
  editor.value = savedStarter;
  editor.dispatchEvent("input");
  root.querySelector<FakeElement>("#lmi-preset-name")!.value = "Meu Decay 0.5";
  root.querySelector('[data-action="lmi-save-dsl"]')!.dispatchEvent("click");
  assert.ok(root.querySelector("#lmi-saved-select")!.innerHTML.includes("Meu Decay 0.5"));

  // Switch template to quadratic_stabilization, then load saved preset back
  const tplSelect = root.querySelector<FakeElement>("#lmi-template-select")!;
  tplSelect.value = "quadratic_stabilization";
  tplSelect.dispatchEvent("change");
  assert.equal(editor.value.includes("param alpha = 0.5"), false);

  const savedSelect = root.querySelector<FakeElement>("#lmi-saved-select")!;
  savedSelect.value = "lmi-preset-1";
  savedSelect.dispatchEvent("change");
  assert.ok(editor.value.includes("param alpha = 0.5"));

  // 3. Export CVXPY & YALMIP BEFORE solving (ADR-010 invariant)
  root.querySelector('[data-action="lmi-export-cvxpy"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 150));
  const modalPre = root.querySelector<FakeElement>("#export-modal-content")!;
  assert.ok(modalPre.textContent.includes("import cvxpy"), "Exportação CVXPY deve funcionar sem solução prévia");
  root.querySelector("#export-modal-close")!.dispatchEvent("click");

  root.querySelector('[data-action="lmi-export-yalmip"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 150));
  assert.ok(modalPre.textContent.includes("sdpvar"), "Exportação YALMIP deve funcionar sem solução prévia");
  root.querySelector("#export-modal-close")!.dispatchEvent("click");

  // 4. Solve LMI via real Python (`optimization.solve`) -> 5D certificate + recovered K + spectrum SVG
  root.querySelector('[data-action="lmi-solve"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 350));

  const certPanel = root.querySelector<FakeElement>("#lmi-certificate-panel")!;
  assert.ok(certPanel.textContent.includes("1. Solver Status"));
  assert.ok(certPanel.textContent.includes("2. Auditoria Factibilidade"));
  assert.ok(certPanel.textContent.includes("3. Certificado Dual"));
  assert.ok(certPanel.textContent.includes("4. Condicionamento κ"));
  assert.ok(certPanel.textContent.includes("5. Validade Controlador"));
  assert.ok(certPanel.textContent.includes("Ganho recuperado K"));

  const specSlot = root.querySelector<FakeElement>("#lmi-spectrum-chart-slot")!;
  assert.ok(specSlot.innerHTML.includes("lmi-spectrum-chart"), "SVG do espectro LMI deve ser renderizado");
  assert.equal(
    root.querySelector('[data-export-bar-for="lmi-spectrum-chart-slot"]')!.hasAttribute("hidden"),
    false,
  );
  assert.ok(root.querySelector("#lmi-spectrum-table-slot")!.innerHTML.includes("accessible-data-table"));

  // 5. Independent Audit (`optimization.verify`) via real Python
  root.querySelector('[data-action="lmi-verify"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 250));
  assert.ok(certPanel.textContent.includes("3. Certificado Dual"));

  app.destroy();
});
