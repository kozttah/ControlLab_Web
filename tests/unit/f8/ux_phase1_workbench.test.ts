/**
 * Testes unitários de WP-UX-PHASE1-01-WORKSPACE-CSV-LEGEND-SISO-FUZZY (F8: f8-ui-charts)
 *
 * Verificam os 5 itens da Fase 1:
 * 1. Workspace Dock: Limpar Workspace (clearRegisteredObjects), Carregar Exemplo (5 presets)
 *    e Remover item individual (removeRegisteredObject) sem remover fallback lqr_plant.
 * 2. Upload de arquivo .csv (#new-obj-csv-file no modal + Novo e #id-csv-file-input na Aba 1).
 * 3. Gráfico de validação da Aba 1 (buildIdentificationResponseChartModel + renderTimeResponseSvg):
 *    cores distintas e legenda dinâmica sem quebrar legenda padrão LQR.
 * 4. Aba 2 (SISO): Editor de Compensador Dinâmico C(s) (TF num/den e Polos & Zeros) com
 *    avaliação real no motor científico Python (Bode, Nyquist, Root Locus e Degrau).
 * 5. Aba 5 (Fuzzy): Limpar / Novo Sistema, Restaurar Exemplo PD, Excluir Termo individual
 *    e Limpar Regras.
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
import {
  buildIdentificationResponseChartModel,
  buildTimeResponseChartModel,
  renderTimeResponseSvg,
} from "../../../web/charts/scientific_chart.ts";
import { cpythonLoader } from "../f7/cpython_runtime.mjs";

class FakeElement {
  public tagName: string;
  public id = "";
  public className = "";
  public value = "";
  public checked = false;
  public disabled = false;
  public files: Array<{ name: string; text?: () => Promise<string> }> = [];
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

  public dispatchEvent(type: string | { type: string; key?: string; target?: unknown }): boolean {
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

  public click(): void {
    this.dispatchEvent("click");
  }

  public focus(): void {
    this.ownerDocument.activeElement = this;
  }

  public querySelector<T = FakeElement>(selector: string): T | null {
    return (this.querySelectorAll<FakeElement>(selector)[0] ?? null) as T | null;
  }

  public querySelectorAll<T = FakeElement>(selector: string): T[] {
    const parts = selector
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const out: FakeElement[] = [];
    const seen = new Set<FakeElement>();
    const matchSingle = (el: FakeElement, sel: string): boolean => {
      if (sel.startsWith("#")) return el.id === sel.slice(1);
      if (sel.startsWith(".")) return el.className.split(/\s+/).includes(sel.slice(1));
      if (sel.startsWith("[") && sel.endsWith("]")) {
        const inner = sel.slice(1, -1);
        const eqIdx = inner.indexOf("=");
        if (eqIdx < 0) return el.hasAttribute(inner);
        const k = inner.slice(0, eqIdx).trim();
        const v = inner.slice(eqIdx + 1).trim().replace(/^["']|["']$/g, "");
        return el.getAttribute(k) === v;
      }
      return el.tagName === sel.toUpperCase();
    };
    const walk = (node: FakeElement): void => {
      for (const child of node.children) {
        if (!seen.has(child) && parts.some((p) => matchSingle(child, p))) {
          seen.add(child);
          out.push(child);
        }
        walk(child);
      }
    };
    walk(this);
    return out as unknown as T[];
  }
}

class FakeDocument {
  public body: FakeElement;
  public documentElement: FakeElement;
  public activeElement: FakeElement | null = null;
  constructor() {
    this.body = new FakeElement("body", this);
    this.documentElement = new FakeElement("html", this);
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
            .replaceAll("&quot;", '"');
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
    if (tag === "select") {
      el.value = "";
    }
    const parent = stack[stack.length - 1];
    el.parentNode = parent;
    if (parent === rootParent) topNodes.push(el);
    else parent.children.push(el);
    if (!selfClose) stack.push(el);
    if (tag === "option" && parent.tagName === "SELECT") {
      if (el.hasAttribute("selected") || parent.value === "") {
        parent.value = el.getAttribute("value") ?? "";
      }
    }
  }
  return topNodes;
}

class PythonPhase1Client implements ControlLabEngineClient {
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
  public getLifecycleState(): EngineLifecycleState { return this.state; }
  public getCapabilities(): CapabilityDescriptor {
    return {
      api_version: RPC_API_VERSION,
      engine_kind: "pyodide",
      runtime_id: "test-f8-phase1-python",
      operations: [
        "worker.ping",
        "core.capabilities",
        "frequency.eval_response",
        "frequency.stability_margins",
        "frequency.root_locus",
        "frequency.step_response",
        "identification.split_dataset",
      ],
      backends: {
        numpy_scipy: { available: true, maturity: "beta" },
      },
      maturity: {},
      supports_transferables: true,
      supports_cooperative_cancel: true,
      max_memory_bytes: 256 * 1024 * 1024,
      lib_versions: { python: "3.12", numpy: "2.0", scipy: "1.14", control_lab: "1.0.0" },
      offline_ready: false,
    };
  }
  public isOperationSupported(): boolean { return true; }
  public async ping(): Promise<{ alive: boolean; rtt_ms: number }> {
    return { alive: true, rtt_ms: 1 };
  }
  public async execute(request: RpcRequest, _options?: ExecuteOptions): Promise<RpcResponse> {
    this.executedRequests.push(structuredClone(request));
    const materialized = structuredClone(request.payload);
    const ref = materialized.plant_ref as { id?: string; revision?: number } | undefined;
    if (ref && typeof ref.id === "string" && typeof ref.revision === "number") {
      const entry = this.store.get(`${request.project_id}:${ref.id}:${ref.revision}`);
      if (entry) {
        materialized.plant = structuredClone(entry.value);
        delete materialized.plant_ref;
      }
    }
    const dsRef = materialized.dataset_ref as { id?: string; revision?: number } | undefined;
    if (dsRef && typeof dsRef.id === "string" && typeof dsRef.revision === "number") {
      const entry = this.store.get(`${request.project_id}:${dsRef.id}:${dsRef.revision}`);
      if (entry) {
        materialized.dataset = structuredClone(entry.value);
        delete materialized.dataset_ref;
      }
    }
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
  public async cancel(): Promise<boolean> { return false; }
  public async resetWorker(): Promise<void> {}
  public async registerObject(
    projectId: string,
    objectId: string,
    revision: number,
    value: Record<string, unknown>,
    options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef> {
    const rec = {
      project_id: projectId,
      object_id: objectId,
      revision,
      kind: options?.kind ?? String(value.kind ?? "StateSpace"),
      value: structuredClone(value),
      persisted: options?.persistToIndexedDB ?? false,
    };
    this.store.set(`${projectId}:${objectId}:${revision}`, rec);
    return { project_id: projectId, object_id: objectId, revision, persisted: rec.persisted, cached_in_worker: true };
  }
  public async getObject(
    projectId: string,
    objectId: string,
    revision: number,
  ): Promise<Record<string, unknown> | null> {
    return this.store.get(`${projectId}:${objectId}:${revision}`)?.value ?? null;
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
        updated_at: new Date().toISOString(),
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
        created_at: new Date().toISOString(),
      },
    };
  }
  public getCommittedRevision(): number { return 0; }
  public async syncAdoptedProjectState(): Promise<void> {}
  public async exportProject(projectId: string): Promise<PortableProjectSnapshot> {
    const objects = Array.from(this.store.values())
      .filter((r) => r.project_id === projectId)
      .map((r) => ({
        storage_key: `${r.project_id}:${r.object_id}:${r.revision}`,
        project_id: r.project_id,
        object_id: r.object_id,
        revision: r.revision,
        kind: r.kind,
        value: structuredClone(r.value),
        content_hash: "test-hash",
        created_at: new Date().toISOString(),
      }));
    return {
      format: "controllab_snapshot",
      schema_version: "1.0.0",
      project_id: projectId,
      project_revision: 1,
      objects,
      experiments: [],
      committed_result: null,
      content_hash: "0".repeat(64),
      exported_at: new Date().toISOString(),
    };
  }
  public async importProject(): Promise<{ project_id: string; committed_revision: number }> {
    return { project_id: "proj", committed_revision: 0 };
  }
  public getMetrics(): ExecutionMetrics { return createInitialExecutionMetrics(); }
  public getLastFailureDiagnostics() { return null; }
  public subscribe(listener: EngineEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  public dispose(): void { this.listeners.clear(); }
}

async function flushMicrotasks(): Promise<void> {
  await new Promise((r) => setTimeout(r, 20));
}

test("Phase 1 Item 1: Workspace Dock Limpar, Carregar Exemplo e Remover Item individual", async () => {
  const doc = new FakeDocument();
  const rootEl = doc.createElement("div");
  const root = rootEl as unknown as HTMLElement;
  const client = new PythonPhase1Client();
  const app = mountControlLabApp(root, { client, project_id: "proj-phase1-dock" });
  try {
    const typed = app.shell.getTypedWorkspace();

    // Load TransferFunction example: mass_spring_damper
    const exampleSelect = rootEl.querySelector<FakeElement>("#dock-example-select")!;
    const btnLoadExample = rootEl.querySelector<FakeElement>("#btn-dock-load-example")!;
    assert.ok(exampleSelect, "Seletor de exemplos deve existir");
    assert.ok(btnLoadExample, "Botão Carregar Exemplo deve existir");

    exampleSelect.value = "mass_spring_damper";
    btnLoadExample.click();
    await flushMicrotasks();

    assert.equal(typed.listRegisteredObjects(["TransferFunction"]).length, 1);
    assert.equal(typed.getEffectiveSelection("frequencyPlant")?.object.id, "mass-spring-damper");

    // Load PRBS dataset example
    exampleSelect.value = "prbs_dataset";
    btnLoadExample.click();
    await flushMicrotasks();
    assert.ok(typed.listRegisteredObjects(["Dataset"]).length >= 2);

    // Verify synthetic active lqr_plant has NO remove button, while registered items DO
    const removeBtns = rootEl.querySelectorAll<FakeElement>('[data-action="dock-remove-item"]');
    assert.ok(removeBtns.length >= 3, "Itens registrados devem possuir botão de remoção individual");
    assert.equal(
      removeBtns.some((b) => b.getAttribute("data-obj-id") === "lqr_plant"),
      false,
      "Fallback sintético lqr_plant não deve ter botão de remover",
    );

    // Remove individual item: mass-spring-damper
    const msdRemoveBtn = removeBtns.find((b) => b.getAttribute("data-obj-id") === "mass-spring-damper");
    assert.ok(msdRemoveBtn);
    msdRemoveBtn.click();
    await flushMicrotasks();
    assert.equal(typed.listRegisteredObjects(["TransferFunction"]).length, 0);

    // Clear workspace button
    const btnClear = rootEl.querySelector<FakeElement>("#btn-dock-clear-workspace")!;
    assert.ok(btnClear);
    btnClear.click();
    await flushMicrotasks();
    assert.equal(typed.listRegisteredObjects().length, 0);
  } finally {
    app.destroy();
  }
});

test("Phase 1 Item 2: Upload .csv no modal + Novo e na Aba 1 (Identificação)", async () => {
  const doc = new FakeDocument();
  const rootEl = doc.createElement("div");
  const root = rootEl as unknown as HTMLElement;
  const client = new PythonPhase1Client();
  const app = mountControlLabApp(root, { client, project_id: "proj-phase1-csv" });
  try {
    const csvSample = "t,u,y\n0.0,1.0,0.0\n0.1,1.0,0.2\n0.2,1.0,0.5";

    // Modal + Novo CSV file input
    const modalCsvFile = rootEl.querySelector<FakeElement>("#new-obj-csv-file")!;
    const modalCsvText = rootEl.querySelector<FakeElement>("#new-csv-content")!;
    assert.ok(modalCsvFile);
    modalCsvFile.files = [{ name: "ensaio.csv", text: async () => csvSample }];
    modalCsvFile.dispatchEvent("change");
    await flushMicrotasks();
    assert.equal(modalCsvText.value, csvSample);

    // Aba 1 CSV file input
    const idCsvFile = rootEl.querySelector<FakeElement>("#id-csv-file-input")!;
    const idCsvText = rootEl.querySelector<FakeElement>("#id-csv-input")!;
    assert.ok(idCsvFile);
    idCsvFile.files = [{ name: "bancada.csv", text: async () => csvSample }];
    idCsvFile.dispatchEvent("change");
    await flushMicrotasks();
    assert.equal(idCsvText.value, csvSample);
  } finally {
    app.destroy();
  }
});

test("Phase 1 Item 3: Gráfico de validação da Aba 1 com cores distintas e legenda dinâmica", () => {
  const idModel = buildIdentificationResponseChartModel({
    partition: "validation",
    dt: 0.1,
    t: [0, 0.1, 0.2, 0.3],
    y_measured: [0, 0.2, 0.5, 0.8],
    y_one_step: [0, 0.19, 0.51, 0.79],
    y_free_sim: [0, 0.18, 0.48, 0.77],
    residuals: [0, 0.01, -0.01, 0.01],
    provenance: null,
    model_revision: 1,
    project_revision: 1,
  });

  const idSvg = renderTimeResponseSvg(idModel);
  assert.ok(idSvg.includes("y Medido (Holdout)"));
  assert.ok(idSvg.includes("ŷ Previsão 1-Passo (Holdout)"));
  assert.ok(idSvg.includes("ŷ Simulação Livre (Holdout)"));
  assert.ok(idSvg.includes("Resíduo e(k)=y-ŷ (Holdout)"));
  assert.equal(idSvg.includes("Estado (x)"), false, "Não deve renderizar legenda hardcoded de StateSpace");

  // Extrai cores dos polylines dos 4 canais
  const colorMatches = Array.from(
    idSvg.matchAll(/stroke="([^"]+)"[^>]*data-channel-id="((?:y|residuals)-[^"]+)"/g),
  );
  const colorByChannel = new Map(colorMatches.map((m) => [m[2], m[1]]));
  assert.equal(colorByChannel.size, 4);
  const uniqueColors = new Set(colorByChannel.values());
  assert.equal(uniqueColors.size, 4, "Os 4 canais de identificação (incluindo resíduo) devem possuir cores distintas");
  assert.equal(colorByChannel.get("residuals-one-step-validation"), "#9333EA");
  assert.ok(idSvg.includes('stroke="#9333EA" stroke-width="1.4"'));

  const idSvgHc = renderTimeResponseSvg(idModel, { themeMode: "high_contrast" });
  assert.ok(idSvgHc.includes('stroke="#F472B6" stroke-width="1.4"'));

  // Verifica que gráfico LQR padrão preserva legenda tradicional
  const lqrModel = buildTimeResponseChartModel({
    chart_id: "lqr-time",
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    series_semantics: "numeric_verified",
    dt: null,
    t: [0, 0.5, 1.0],
    y: [[0], [0.5], [0.9]],
    u: [[1], [0.5], [0.1]],
  });
  const lqrSvg = renderTimeResponseSvg(lqrModel);
  assert.ok(lqrSvg.includes("— Saída (y)"));
  assert.ok(lqrSvg.includes("-- Entrada (u)"));
  assert.ok(lqrSvg.includes("·· Estado (x)"));
});

test("Phase 1 Item 4: Compensador Dinâmico C(s) (TF num/den e Polos & Zeros) na Aba 2 com motor Python", async () => {
  const doc = new FakeDocument();
  const rootEl = doc.createElement("div");
  const root = rootEl as unknown as HTMLElement;
  const client = new PythonPhase1Client();
  const app = mountControlLabApp(root, { client, project_id: "proj-phase1-siso" });
  try {
    app.shell.switchTab("siso_frequency");

    // Registra planta G(s) = 1 / (s + 1)
    await app.shell.getTypedWorkspace().registerTypedObject(
      {
        schema_version: "1.0.0",
        id: "tf-first-order",
        revision: 1,
        kind: "TransferFunction",
        dt: null,
        variable: "s",
        poly_order: "descending",
        num: [[{ shape: [1], dtype: "float64", order: "C", data: [1] }]],
        den: [[{ shape: [2], dtype: "float64", order: "C", data: [1, 1] }]],
        units: { time: "s", inputs: ["u1"], outputs: ["y1"] },
        provenance: { source: "test" },
      },
      { selectRole: "frequencyPlant" },
    );

    const siso = app.shell.getSisoWorkspace();

    // Abre modal C(s) e aplica TF C(s) = (s + 2) / (s + 10)
    const editBtn = rootEl.querySelector<FakeElement>("#btn-siso-edit-compensator")!;
    const compModal = rootEl.querySelector<FakeElement>("#siso-compensator-modal")!;
    assert.ok(editBtn);
    assert.equal(compModal.hasAttribute("hidden"), true);
    editBtn.click();
    assert.equal(compModal.hasAttribute("hidden"), false);

    rootEl.querySelector<FakeElement>("#siso-comp-num")!.value = "1, 2";
    rootEl.querySelector<FakeElement>("#siso-comp-den")!.value = "1, 10";
    rootEl.querySelector<FakeElement>("#btn-siso-apply-comp")!.click();
    await flushMicrotasks();

    assert.equal(compModal.hasAttribute("hidden"), true);
    assert.deepEqual(siso.getCompensatorTf().num, [1, 2]);
    assert.deepEqual(siso.getCompensatorTf().den, [1, 10]);
    assert.ok(siso.getBodeChartModel() !== null, "Bode deve ser reavaliado com o compensador");
    assert.ok(siso.getTimeResponseChartModel() !== null, "Degrau em malha fechada deve ser reavaliado");

    const loopBar = rootEl.querySelector<FakeElement>("#siso-loop-diagram-bar")!;
    assert.ok(loopBar.textContent.includes("s + 2") && loopBar.textContent.includes("s + 10"));

    // Testa ZPK: K = 3, zero em s = -2, polos em s = -1, -5 => (s+2)/(s^2 + 6s + 5)
    siso.setCompensatorZpk(3, [{ re: -2, im: 0 }], [{ re: -1, im: 0 }, { re: -5, im: 0 }]);
    assert.deepEqual(siso.getCompensatorTf().num, [1, 2]);
    assert.deepEqual(siso.getCompensatorTf().den, [1, 6, 5]);
    assert.equal(siso.getCompensatorGain(), 3);

    const { bodeChart } = await siso.evaluateBodeAndMargins();
    assert.ok(bodeChart.mag_db.length > 0);

    // Reset para C(s) = K
    rootEl.querySelector<FakeElement>("#btn-siso-reset-comp")!.click();
    await flushMicrotasks();
    assert.deepEqual(siso.getCompensatorTf().num, [1]);
    assert.deepEqual(siso.getCompensatorTf().den, [1]);
  } finally {
    app.destroy();
  }
});

test("Phase 1 Item 5: Aba 5 (Fuzzy) Limpar / Novo Sistema, Restaurar PD, Excluir Termo e Limpar Regras", async () => {
  const doc = new FakeDocument();
  const rootEl = doc.createElement("div");
  const root = rootEl as unknown as HTMLElement;
  const client = new PythonPhase1Client();
  const app = mountControlLabApp(root, { client, project_id: "proj-phase1-fuzzy" });
  try {
    app.shell.switchTab("fuzzy_ts");

    // Estado inicial: 3 termos em erro, 9 regras
    assert.equal(rootEl.querySelectorAll('[data-action="fuzzy-remove-term"]').length, 3);
    assert.ok(rootEl.querySelector<FakeElement>("#fuzzy-coverage-status")!.textContent.includes("9 regras"));

    // Excluir 1 termo
    rootEl.querySelectorAll<FakeElement>('[data-action="fuzzy-remove-term"]')[0].click();
    assert.equal(rootEl.querySelectorAll('[data-action="fuzzy-remove-term"]').length, 2);

    // Limpar regras
    rootEl.querySelector<FakeElement>("#btn-fuzzy-clear-rules")!.click();
    assert.ok(rootEl.querySelector<FakeElement>("#fuzzy-coverage-status")!.textContent.includes("0 regras"));

    // Limpar / Novo Sistema
    rootEl.querySelector<FakeElement>("#btn-fuzzy-clear-system")!.click();
    assert.equal(rootEl.querySelectorAll('[data-action="fuzzy-remove-term"]').length, 1);
    assert.ok(rootEl.querySelector<FakeElement>("#fuzzy-coverage-status")!.textContent.includes("0 regras"));

    // Restaurar Exemplo PD
    rootEl.querySelector<FakeElement>("#btn-fuzzy-reset-starter")!.click();
    assert.equal(rootEl.querySelectorAll('[data-action="fuzzy-remove-term"]').length, 3);
    assert.ok(rootEl.querySelector<FakeElement>("#fuzzy-coverage-status")!.textContent.includes("9 regras"));
  } finally {
    app.destroy();
  }
});
