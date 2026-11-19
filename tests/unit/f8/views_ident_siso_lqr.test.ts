/**
 * Testes unitários de WP-UX-REFACTOR-02-IDENT-SISO-LQR (F8: f8-ui-charts)
 *
 * Verificam:
 * 1. Datatips geométricos em `web/charts/scientific_chart.ts`:
 *    - `inspectBodeAtSvgPoint`, `inspectNyquistAtSvgPoint`, `inspectRootLocusAtSvgPoint`
 *    - Overlays `<g data-layer="datatip">` e `<g data-layer="frozen-poles-datatip">`
 *      congelando TODOS os polos em malha fechada nos ramos do Root Locus para ganho K.
 * 2. `IdentificationView` (Aba 1):
 *    - Barra guiada de 3 etapas, controles rápidos ARX/Subespaços,
 *      quadro comparativo multi-modelo (`#id-models-session-list`) com distinção
 *      Simulação Livre (Holdout) vs Previsão 1-Passo (Holdout) e promoção 1-clique.
 * 3. `SisoView` (Aba 2):
 *    - Diagrama de blocos (`#siso-loop-diagram-bar`), tuner `C(s)=K` (`#siso-gain-slider`),
 *      guarda MIMO (`#siso-mimo-guard-callout`), datatips interativos por clique em
 *      Bode, Nyquist e Root Locus + limpar/aplicar K.
 * 4. `StatespaceView` (Aba 3):
 *    - Cartões KPI (`#lqr-kpi-cards`), badges estruturais PBH (`#lqr-pbh-badges`),
 *      abas de filtro matricial (`Todas | Planta | Pesos`) mantendo células no DOM,
 *      e modal JSON documentado (`#lqr-json-modal`).
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
import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import type { PortableProjectSnapshot } from "../../../web/storage/indexeddb_store.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import {
  buildBodeChartModel,
  buildNyquistChartModel,
  buildRootLocusChartModel,
  inspectBodeAtSvgPoint,
  inspectNyquistAtSvgPoint,
  inspectRootLocusAtSvgPoint,
  renderBodeSvg,
  renderNyquistSvg,
  renderRootLocusSvg,
} from "../../../web/charts/scientific_chart.ts";
import { cpythonLoader } from "../f7/cpython_runtime.mjs";

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
      (evType === "change" || evType === "click")
    ) {
      for (const fn of this.parentNode.listeners.get(evType) ?? []) {
        fn({ ...evObj, currentTarget: this.parentNode });
      }
    }
    return true;
  }

  public getBoundingClientRect() {
    return { left: 0, top: 0, width: 640, height: 420, right: 640, bottom: 420 };
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

class PythonBackedFullEngineClient implements ControlLabEngineClient {
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
      runtime_id: "test-f8-views-python",
      operations: [
        "worker.ping",
        "core.capabilities",
        "core.reuse_model",
        "identification.fit_arx",
        "identification.fit_subspace",
        "identification.validate_model",
        "frequency.eval_response",
        "frequency.bode",
        "frequency.stability_margins",
        "frequency.root_locus",
        "frequency.step_response",
        "statespace.design_lqr",
        "statespace.analyze",
      ],
      backends: {
        numpy_scipy: { available: true, maturity: "beta" },
        native_primal_dual: { available: true, maturity: "beta" },
      },
      maturity: {
        "core.reuse_model": "beta",
        "identification.fit_arx": "beta",
        "identification.fit_subspace": "beta",
        "identification.validate_model": "beta",
        "frequency.eval_response": "beta",
        "frequency.bode": "beta",
        "frequency.stability_margins": "beta",
        "frequency.root_locus": "beta",
        "frequency.step_response": "beta",
        "statespace.design_lqr": "beta",
        "statespace.analyze": "beta",
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
    if (operation === "identification.fit_arx" || operation === "identification.fit_subspace") {
      lookup("dataset_ref", "dataset");
      lookup("val_dataset_ref", "val_dataset");
    } else if (operation === "identification.validate_model") {
      lookup("model_ref", "model");
      lookup("val_dataset_ref", "val_dataset");
      lookup("train_dataset_ref", "train_dataset");
    } else if (operation === "core.reuse_model") {
      lookup("model_ref", "model");
    } else if (operation.startsWith("frequency.") || operation.startsWith("statespace.")) {
      lookup("plant_ref", "plant");
      lookup("model_ref", "plant");
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

test("WP-UX-REFACTOR-02: datatips geométricos em Bode, Nyquist e Root Locus (congelamento de todos os polos)", () => {
  // 1. Bode datatip inspection + SVG overlay
  const bodeModel = buildBodeChartModel({
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    dt: null,
    omega: [0.1, 1.0, 10.0],
    mag_db: [-0.04, -3.01, -20.04],
    phase_deg: [-5.71, -45.0, -84.29],
  });
  const bodePlainSvg = renderBodeSvg(bodeModel);
  assert.ok(bodePlainSvg.includes("bode-chart"));
  assert.ok(bodePlainSvg.includes('viewBox="0 0 640 480"'));
  assert.equal(bodePlainSvg.includes('data-layer="datatip"'), false);

  const bodeTip = inspectBodeAtSvgPoint(bodeModel, 340);
  assert.ok(bodeTip !== null);
  assert.equal(bodeTip.sampleIndex, 1);
  assert.equal(bodeTip.omega, 1.0);
  const bodeTipSvg = renderBodeSvg(bodeModel, { selectedSampleIndex: bodeTip.sampleIndex });
  assert.ok(bodeTipSvg.includes('data-layer="datatip"'));
  assert.ok(bodeTipSvg.includes('data-sample-index="1"'));

  // 2. Nyquist datatip inspection + SVG overlay
  const nyqModel = buildNyquistChartModel({
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    dt: null,
    omega: [0.1, 1.0, 10.0],
    re: [0.99, 0.5, 0.01],
    im: [-0.099, -0.5, -0.099],
  });
  const nyqPlainSvg = renderNyquistSvg(nyqModel);
  assert.ok(nyqPlainSvg.includes("nyquist-chart"));
  assert.ok(nyqPlainSvg.includes('viewBox="0 0 640 400"'));
  assert.equal(nyqPlainSvg.includes('data-layer="datatip"'), false);

  const midTip = inspectNyquistAtSvgPoint(nyqModel, 400, 300);
  assert.ok(midTip !== null);
  const nyqTip = inspectNyquistAtSvgPoint(nyqModel, midTip.pxX, midTip.pxY);
  assert.ok(nyqTip !== null);
  assert.equal(nyqTip.sampleIndex, midTip.sampleIndex);
  const nyqTipSvg = renderNyquistSvg(nyqModel, { selectedSampleIndex: nyqTip.sampleIndex });
  assert.ok(nyqTipSvg.includes('data-layer="datatip"'));

  // 3. Root Locus datatip inspection -> freeze ALL closed-loop poles across EVERY branch at gain_K
  const rlModel = buildRootLocusChartModel({
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    dt: null,
    gains: [0, 1, 5, 10],
    branches: [
      { real: [-1, -1, -1, -1], imag: [1, 1.414, 2.449, 3.317] },
      { real: [-1, -1, -1, -1], imag: [-1, -1.414, -2.449, -3.317] },
      { real: [-3, -3.5, -4.2, -5.0], imag: [0, 0, 0, 0] },
    ],
    open_loop_poles: { real: [-1, -1, -3], imag: [1, -1, 0] },
  });
  const rlPlainSvg = renderRootLocusSvg(rlModel);
  assert.ok(rlPlainSvg.includes("root-locus-chart"));
  assert.ok(rlPlainSvg.includes('viewBox="0 0 640 420"'));
  assert.equal(rlPlainSvg.includes('data-layer="frozen-poles-datatip"'), false);

  // Inspect at index 2 (K=5) coordinates on branch 0
  const probeFirst = inspectRootLocusAtSvgPoint(rlModel, 450, 90);
  assert.ok(probeFirst !== null);
  assert.equal(probeFirst.poles.length, 3, "Deve congelar todos os 3 polos de malha fechada nos 3 ramos");
  assert.equal(probeFirst.gain_K, rlModel.gains[probeFirst.gainIndex]);

  const rlFrozenSvg = renderRootLocusSvg(rlModel, { frozenGainIndex: probeFirst.gainIndex });
  assert.ok(rlFrozenSvg.includes('data-layer="datatip"'));
  assert.ok(rlFrozenSvg.includes('data-layer="frozen-poles-datatip"'));
  assert.ok(rlFrozenSvg.includes('data-frozen-pole-branch="0"'));
  assert.ok(rlFrozenSvg.includes('data-frozen-pole-branch="1"'));
  assert.ok(rlFrozenSvg.includes('data-frozen-pole-branch="2"'));
});

test("WP-UX-REFACTOR-02: IdentificationView (pipeline 3 etapas, estimação rápida ARX/Subespaços e quadro multi-modelo)", async () => {
  const client = new PythonBackedFullEngineClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-ident-view",
  });
  await app.client.init();

  app.shell.switchTab("identification");
  assert.ok(root.querySelector("#id-pipeline-bar") !== null);

  // Load PRBS benchmark
  root.querySelector('[data-action="id-load-prbs"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 40));

  // Quick estimation 1: ARX(2,2,1) directly from Tab 1 controls
  root.querySelector<FakeElement>("#id-arx-na")!.value = "2";
  root.querySelector<FakeElement>("#id-arx-nb")!.value = "2";
  root.querySelector<FakeElement>("#id-arx-nk")!.value = "1";
  root.querySelector('[data-action="id-fit-arx"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 100));

  // Quick estimation 2: Subspace MOESP(n=2) directly from Tab 1 controls
  root.querySelector<FakeElement>("#id-sub-method")!.value = "moesp";
  root.querySelector<FakeElement>("#id-sub-order")!.value = "2";
  root.querySelector('[data-action="id-fit-subspace"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 100));

  const board = root.querySelector<FakeElement>("#id-models-session-list")!;
  assert.ok(board.innerHTML.includes("ARX(2,2,1)"), "Quadro deve listar o modelo ARX estimado");
  assert.ok(board.innerHTML.includes("MOESP(n=2)"), "Quadro deve listar o modelo MOESP estimado");
  assert.ok(board.innerHTML.includes("Simulação Livre (Holdout)"), "Quadro deve explicitar Simulação Livre (Holdout)");
  assert.ok(board.innerHTML.includes("Previsão 1-Passo (Holdout)"), "Quadro deve explicitar Previsão 1-Passo (Holdout)");
  assert.ok(board.querySelectorAll(".id-model-compare-checkbox").length >= 2);
  assert.ok(board.innerHTML.includes("Comparação de modelos selecionados"));

  // Promote directly to SISO tab via 1-click button
  root.querySelector('[data-action="id-reuse-to-siso"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 100));
  assert.equal(app.shell.getActiveTab(), "siso_frequency");

  app.destroy();
});

test("WP-UX-REFACTOR-02: SisoView (diagrama de malha, guarda MIMO, slider C(s) e datatips clicáveis Bode/Nyquist/Root Locus)", async () => {
  const client = new PythonBackedFullEngineClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-siso-view",
  });
  await app.client.init();

  // 1. Register MIMO 2x2 plant and verify MIMO Guard Callout + 1-click switch to Tab 4
  const mimoTf = {
    schema_version: "1.0.0",
    id: "tf-mimo-2x2",
    revision: 1,
    kind: "TransferFunction",
    dt: null,
    variable: "s",
    poly_order: "descending",
    num: [
      [{ shape: [1], dtype: "float64", order: "C", data: [1] }, { shape: [1], dtype: "float64", order: "C", data: [0.2] }],
      [{ shape: [1], dtype: "float64", order: "C", data: [0.1] }, { shape: [1], dtype: "float64", order: "C", data: [1] }],
    ],
    den: [
      [{ shape: [2], dtype: "float64", order: "C", data: [1, 1] }, { shape: [2], dtype: "float64", order: "C", data: [1, 2] }],
      [{ shape: [2], dtype: "float64", order: "C", data: [1, 3] }, { shape: [2], dtype: "float64", order: "C", data: [1, 1] }],
    ],
    units: { time: "s", inputs: ["u1", "u2"], outputs: ["y1", "y2"] },
    provenance: { source: "test" },
  };
  await app.shell.getTypedWorkspace().registerTypedObject(mimoTf, { selectRole: "frequencyPlant" });
  app.shell.switchTab("siso_frequency");

  const mimoGuard = root.querySelector<FakeElement>("#siso-mimo-guard-callout")!;
  assert.equal(mimoGuard.hasAttribute("hidden"), false, "Guarda MIMO deve estar visível para planta 2x2");
  root.querySelector('[data-action="siso-open-mimo"]')!.dispatchEvent("click");
  assert.equal(app.shell.getActiveTab(), "mimo_frequency");

  // 2. Register SISO plant G(s) = 1 / (s^2 + 2s + 2) and switch back to siso_frequency
  const sisoTf = {
    schema_version: "1.0.0",
    id: "tf-siso-2nd",
    revision: 1,
    kind: "TransferFunction",
    dt: null,
    variable: "s",
    poly_order: "descending",
    num: [[{ shape: [1], dtype: "float64", order: "C", data: [1] }]],
    den: [[{ shape: [3], dtype: "float64", order: "C", data: [1, 2, 2] }]],
    units: { time: "s", inputs: ["u1"], outputs: ["y1"] },
    provenance: { source: "test" },
  };
  await app.shell.getTypedWorkspace().registerTypedObject(sisoTf, { selectRole: "frequencyPlant" });
  app.shell.switchTab("siso_frequency");
  assert.equal(mimoGuard.hasAttribute("hidden"), true);

  // Verify Loop Block-Diagram Header
  const loopBar = root.querySelector<FakeElement>("#siso-loop-diagram-bar")!;
  assert.ok(loopBar.textContent.includes("Σ (r - y)"));
  assert.ok(loopBar.textContent.includes("C(s) ="));
  assert.ok(loopBar.textContent.includes("tf-siso-2nd"));

  // Evaluate Bode/Nyquist and Root Locus
  root.querySelector('[data-action="siso-eval-bode"]')!.dispatchEvent("click");
  root.querySelector('[data-action="siso-eval-rl"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 120));

  assert.ok(loopBar.textContent.includes("MF:"));
  assert.ok(loopBar.textContent.includes("Estável"));

  // Click on Bode chart -> updates #siso-bode-datatip + SVG datatip layer + clear button
  const bodeSlot = root.querySelector<FakeElement>("#siso-bode-chart-slot")!;
  bodeSlot.dispatchEvent("click", { svgX: 320, svgY: 160 });
  const bodeTip = root.querySelector<FakeElement>("#siso-bode-datatip")!;
  assert.equal(bodeTip.hasAttribute("hidden"), false);
  assert.ok(bodeTip.textContent.includes("rad/s"));
  assert.ok(bodeTip.textContent.includes("dB"));
  assert.ok(bodeSlot.innerHTML.includes('data-layer="datatip"'));
  root.querySelector("#btn-siso-bode-clear-tip")!.dispatchEvent("click");
  assert.equal(bodeTip.hasAttribute("hidden"), true);

  // Click on Nyquist chart -> updates #siso-nyquist-datatip + clear button
  const nyqSlot = root.querySelector<FakeElement>("#siso-nyquist-chart-slot")!;
  nyqSlot.dispatchEvent("click", { svgX: 350, svgY: 200 });
  const nyqTip = root.querySelector<FakeElement>("#siso-nyquist-datatip")!;
  assert.equal(nyqTip.hasAttribute("hidden"), false);
  assert.ok(nyqTip.textContent.includes("L(jω)"));
  assert.ok(nyqSlot.innerHTML.includes('data-layer="datatip"'));
  root.querySelector("#btn-siso-nyquist-clear-tip")!.dispatchEvent("click");
  assert.equal(nyqTip.hasAttribute("hidden"), true);

  // Click on Root Locus chart -> freezes ALL poles + renders frozen-poles-datatip + Apply K + Clear
  const rlSlot = root.querySelector<FakeElement>("#siso-rl-chart-slot")!;
  rlSlot.dispatchEvent("click", { svgX: 300, svgY: 120 });
  const rlTip = root.querySelector<FakeElement>("#siso-rl-datatip")!;
  assert.equal(rlTip.hasAttribute("hidden"), false);
  assert.ok(rlTip.textContent.includes("Polos congelados em K ="));
  assert.ok(rlTip.textContent.includes("Ramo 1:"));
  assert.ok(rlTip.textContent.includes("Ramo 2:"));
  assert.ok(rlSlot.innerHTML.includes('data-layer="frozen-poles-datatip"'));

  root.querySelector("#btn-siso-rl-clear-tip")!.dispatchEvent("click");
  assert.equal(rlTip.hasAttribute("hidden"), true);
  assert.equal(rlSlot.innerHTML.includes('data-layer="frozen-poles-datatip"'), false);

  // Tuner slider pointerdown -> pointermove -> pointerup
  const gainSlider = root.querySelector<FakeElement>("#siso-gain-slider")!;
  gainSlider.dispatchEvent("pointerdown", { pointerId: 1 });
  gainSlider.dispatchEvent("pointermove", { pointerId: 1, clientX: 320 });
  assert.ok(root.querySelector("#siso-tuner-status")!.textContent.includes("Pré-visualizando"));
  gainSlider.dispatchEvent("pointerup", { pointerId: 1 });
  await new Promise((r) => setTimeout(r, 80));

  app.destroy();
});

test("WP-UX-REFACTOR-02: StatespaceView (KPIs, badges PBH, filtros matriciais e modal JSON documentado)", async () => {
  const client = new MockWorkerAdapter();
  await client.init();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-ss-view",
  });

  // 1. KPI cards and PBH badges update after LQR commit & analyzeOpenLoop
  await app.shell.getLqrWorkspace().commitCurrentDesign();
  const kpiCards = root.querySelector<FakeElement>("#lqr-kpi-cards")!;
  assert.ok(kpiCards.textContent.includes("Ganho Ótimo K"));
  assert.ok(kpiCards.textContent.includes("[2.0000, 3.0000]"));
  assert.ok(kpiCards.textContent.includes("Custo Ótimo J*"));
  assert.ok(kpiCards.textContent.includes("13.0000"));

  root.querySelector('[data-action="analyze-open-loop"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));
  const pbhBadges = root.querySelector<FakeElement>("#lqr-pbh-badges")!;
  assert.ok(pbhBadges.textContent.includes("Controlável (PBH)"));
  assert.ok(pbhBadges.textContent.includes("Observável (PBH)"));
  assert.ok(pbhBadges.textContent.includes("CARE (Contínuo)"));

  // 2. Matrix filter tabs toggle block visibility while keeping ALL cells in DOM
  root.querySelector("#btn-lqr-filter-plant")!.dispatchEvent("click");
  assert.equal(root.querySelector('[data-matrix-block="A"]')!.hasAttribute("hidden"), false);
  assert.equal(root.querySelector('[data-matrix-block="Q"]')!.hasAttribute("hidden"), true);
  assert.ok(root.querySelector('input[data-matrix="Q"][data-row="0"][data-col="0"]') !== null);

  root.querySelector("#btn-lqr-filter-weights")!.dispatchEvent("click");
  assert.equal(root.querySelector('[data-matrix-block="A"]')!.hasAttribute("hidden"), true);
  assert.equal(root.querySelector('[data-matrix-block="Q"]')!.hasAttribute("hidden"), false);

  root.querySelector("#btn-lqr-filter-all")!.dispatchEvent("click");
  assert.equal(root.querySelector('[data-matrix-block="A"]')!.hasAttribute("hidden"), false);
  assert.equal(root.querySelector('[data-matrix-block="Q"]')!.hasAttribute("hidden"), false);

  // 3. Documented JSON modal opens, applies weights JSON, and closes cleanly
  const jsonModal = root.querySelector<FakeElement>("#lqr-json-modal")!;
  assert.equal(jsonModal.hasAttribute("hidden"), true);
  root.querySelector("#btn-open-lqr-json-modal")!.dispatchEvent("click");
  assert.equal(jsonModal.hasAttribute("hidden"), false);

  root.querySelector<FakeElement>("#lqr-modal-weights-json")!.value = JSON.stringify({
    Q: [[9, 0], [0, 3]],
    R: [[1]],
    x0: [1, 0],
  });
  root.querySelector("#btn-lqr-modal-apply-weights")!.dispatchEvent("click");
  assert.equal(jsonModal.hasAttribute("hidden"), true);
  assert.deepEqual(app.shell.getLqrWorkspace().getWeights().Q.data, [9, 0, 0, 3]);

  app.destroy();
});
