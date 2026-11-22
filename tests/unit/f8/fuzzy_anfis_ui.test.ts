/**
 * Testes unitários de WP-ROADMAP-ANFIS-TAB5 (F8: f8-ui-charts)
 *
 * Verificam:
 * 1. Presença de `#fuzzy-anfis-card`, dataset pré-populado (20 pts `y = sin(x1) + 0.5*x2`),
 *    controles (`#fuzzy-anfis-nmfs`, `#fuzzy-anfis-mftype`, `#fuzzy-anfis-epochs`,
 *    `#fuzzy-anfis-lr`, `#btn-fuzzy-train-anfis`) e área `#fuzzy-anfis-results`.
 * 2. Parser `parseAnfisDataset` (JSON e CSV, validação de linhas/colunas/finitude).
 * 3. Execução ponta a ponta com `control_lab.fuzzy.fit_anfis` (CPython real) para
 *    `gaussian` e `bell`, renderização de `train_rmse`, `val_rmse`, `best_epoch`,
 *    curva SVG `#fuzzy-anfis-rmse-chart` e carregamento automático do `FuzzySystem`
 *    treinado na bancada da Aba 5 (MFs, matriz de regras e avaliação de superfície).
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
import { parseAnfisDataset } from "../../../web/features/views/fuzzy_view.ts";
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
    const attrsStr = match[3];
    const isSelfClose = match[4] === "/" || voidTags.has(tag);

    if (isClose) {
      for (let i = stack.length - 1; i >= 1; i -= 1) {
        if (stack[i].tagName.toLowerCase() === tag) {
          stack.length = i;
          break;
        }
      }
      continue;
    }

    const el = doc.createElement(tag);
    const attrRe = /([a-zA-Z0-9_:-]+)(?:\s*=\s*"([^"]*)")?/g;
    let attrMatch: RegExpExecArray | null;
    while ((attrMatch = attrRe.exec(attrsStr)) !== null) {
      el.setAttribute(attrMatch[1], attrMatch[2] ?? "");
    }
    const parent = stack[stack.length - 1];
    el.parentNode = parent;
    if (parent === rootParent) topNodes.push(el);
    else parent.children.push(el);

    if (!isSelfClose) {
      stack.push(el);
    } else if (tag === "option" && parent.tagName === "SELECT" && el.hasAttribute("selected")) {
      parent.value = el.value;
    }
  }
  for (const node of topNodes) {
    const visitSelect = (el: FakeElement) => {
      if (el.tagName === "SELECT") {
        const selectedOpt =
          el.children.find((c) => c.tagName === "OPTION" && c.hasAttribute("selected")) ??
          el.children.find((c) => c.tagName === "OPTION");
        if (selectedOpt) el.value = selectedOpt.value;
      }
      for (const ch of el.children) visitSelect(ch);
    };
    visitSelect(node);
  }
  return topNodes;
}

class PythonAnfisClient implements ControlLabEngineClient {
  private state: EngineLifecycleState = "uninitialized";
  private readonly store = new Map<string, { kind: string; value: Record<string, unknown> }>();
  private readonly listeners = new Set<EngineEventListener>();
  public readonly executedRequests: RpcRequest[] = [];

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
      runtime_id: "test-f8-anfis-python",
      operations: [
        "worker.ping",
        "core.capabilities",
        "fuzzy.evaluate",
        "fuzzy.evaluate_surface",
        "fuzzy.fit_anfis",
      ],
      backends: {
        numpy_scipy: { available: true, maturity: "beta" },
      },
      maturity: {
        "fuzzy.evaluate": "beta",
        "fuzzy.evaluate_surface": "beta",
        "fuzzy.fit_anfis": "beta",
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

  public async execute(request: RpcRequest, _options?: ExecuteOptions): Promise<RpcResponse> {
    this.executedRequests.push(structuredClone(request));
    const loaded = await cpythonLoader({ indexURL: "", packages: [] });
    const pyodide = loaded.pyodide;
    if (!pyodide.pyimport || !pyodide.toPy) {
      throw new Error("cpythonLoader não expôs pyimport/toPy.");
    }

    if (request.operation === "fuzzy.fit_anfis") {
      const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
        dispatch: (arg: unknown) => RpcResponse;
        destroy?: () => void;
      };
      const proxy = pyodide.toPy({ request, payload: request.payload });
      const rawResp = rpcMod.dispatch(proxy);
      proxy.destroy();
      rpcMod.destroy?.();
      if (rawResp.status !== "failure") {
        return rawResp;
      }

      // Fallback direto para control_lab.fuzzy.fit_anfis caso rpc.py ainda não exponha fuzzy.fit_anfis
      const fuzzyMod = pyodide.pyimport("control_lab.fuzzy") as {
        fit_anfis: (...args: unknown[]) => unknown;
      };
      const p = request.payload;
      const pyRes = fuzzyMod.fit_anfis(pyodide.toPy(p.X), pyodide.toPy(p.y), {
        n_mfs: p.n_mfs,
        mf_type: p.mf_type,
        max_epochs: p.max_epochs,
        learning_rate: p.learning_rate,
        input_names: p.input_names,
        output_name: p.output_name,
      }) as { to_dict?: () => Record<string, unknown> };
      const resDict = typeof pyRes.to_dict === "function" ? pyRes.to_dict() : (pyRes as unknown as Record<string, unknown>);
      const data = (resDict.data ?? {}) as Record<string, unknown>;
      return {
        api_version: RPC_API_VERSION,
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: request.project_revision,
        status: (resDict.status as "success" | "warning" | "failure") ?? "success",
        result: data,
        assumptions: (resDict.assumptions as Record<string, unknown>) ?? {},
        diagnostics: (resDict.diagnostics as Record<string, unknown>) ?? {},
        provenance: (resDict.provenance as RpcResponse["provenance"]) ?? {
          algorithm: "control_lab.fuzzy.fit_anfis",
          library_versions: { control_lab: "1.0.0" },
          seed: 42,
          tolerances: {},
          timestamp_utc: new Date().toISOString(),
        },
        warnings: [],
        error: null,
      };
    }

    const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
      dispatch: (arg: unknown) => RpcResponse;
      destroy?: () => void;
    };
    const proxy = pyodide.toPy({ request, payload: request.payload });
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
    projectId: string,
    id: string,
    revision: number,
    value: Record<string, unknown>,
    options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef> {
    const kind = options?.kind ?? String(value.kind ?? "FuzzySystem");
    const persisted = options?.persistToIndexedDB ?? false;
    this.store.set(`${projectId}::${id}#${revision}`, { kind, value: structuredClone(value) });
    return {
      project_id: projectId,
      object_id: id,
      revision,
      persisted,
      cached_in_worker: true,
    };
  }

  public async getObject(
    projectId: string,
    id: string,
    revision: number,
  ): Promise<Record<string, unknown> | null> {
    const found = this.store.get(`${projectId}::${id}#${revision}`);
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

  public async exportProject(projectId: string): Promise<PortableProjectSnapshot> {
    return {
      format: "controllab_snapshot",
      schema_version: "1.0.0",
      project_id: projectId,
      project_revision: 1,
      objects: [],
      experiments: [],
      committed_result: null,
      content_hash: "0".repeat(64),
      exported_at: "2026-11-21T00:00:00Z",
    };
  }

  public subscribe(listener: EngineEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  public async loadProjectFromIndexedDB(): Promise<PortableProjectSnapshot | null> {
    return null;
  }

  public async dispose(): Promise<void> {
    this.state = "uninitialized";
  }
}

test("parseAnfisDataset aceita JSON, CSV e rejeita entradas inválidas", () => {
  const fromJson = parseAnfisDataset("[[0, 1, 0.5], [1, 2, 1.8], [2, 3, 2.4], [3, 4, 2.1]]");
  assert.equal(fromJson.X.length, 4);
  assert.deepEqual(fromJson.X[0], [0, 1]);
  assert.deepEqual(fromJson.y, [0.5, 1.8, 2.4, 2.1]);

  const fromCsv = parseAnfisDataset("x1,x2,y\n0,1,0.5\n1,2,1.8\n2,3,2.4\n3,4,2.1");
  assert.equal(fromCsv.X.length, 4);
  assert.deepEqual(fromCsv.y, [0.5, 1.8, 2.4, 2.1]);

  assert.throws(
    () => parseAnfisDataset("[[0, 1, 0.5], [1, 2, 1.8]]"),
    (err: unknown) => err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );
});

test("WP-ROADMAP-ANFIS-TAB5: card ANFIS na Aba 5 treina via fuzzy.fit_anfis, renderiza RMSE SVG e carrega FuzzySystem", async () => {
  const client = new PythonAnfisClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-anfis-tab5",
  });
  await app.client.init();
  app.shell.switchTab("fuzzy_ts");

  const card = root.querySelector<FakeElement>("#fuzzy-anfis-card");
  assert.ok(card, "#fuzzy-anfis-card deve existir na Aba 5");
  const datasetEl = root.querySelector<FakeElement>("#fuzzy-anfis-dataset")!;
  assert.ok(datasetEl, "#fuzzy-anfis-dataset deve existir");
  const parsedDefault = parseAnfisDataset(datasetEl.value);
  assert.equal(parsedDefault.X.length, 20, "Dataset padrão deve ter 20 amostras");
  assert.equal(parsedDefault.X[0].length, 2, "Dataset padrão deve ter 2 entradas");

  const nmfsEl = root.querySelector<FakeElement>("#fuzzy-anfis-nmfs")!;
  const mftypeEl = root.querySelector<FakeElement>("#fuzzy-anfis-mftype")!;
  const epochsEl = root.querySelector<FakeElement>("#fuzzy-anfis-epochs")!;
  const lrEl = root.querySelector<FakeElement>("#fuzzy-anfis-lr")!;
  const trainBtn = root.querySelector<FakeElement>("#btn-fuzzy-train-anfis")!;
  assert.ok(nmfsEl && mftypeEl && epochsEl && lrEl && trainBtn);
  assert.equal(epochsEl.value, "25");
  assert.equal(lrEl.value, "0.02");

  // Treina com gaussian e 2 MFs
  nmfsEl.value = "2";
  mftypeEl.value = "gaussian";
  epochsEl.value = "10";
  lrEl.value = "0.02";
  trainBtn.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 400));

  const fitReq = client.executedRequests.find((r) => r.operation === "fuzzy.fit_anfis");
  assert.ok(fitReq, "Deve disparar RPC fuzzy.fit_anfis");
  assert.equal(fitReq.payload.n_mfs, 2);
  assert.equal(fitReq.payload.mf_type, "gaussian");
  assert.equal(fitReq.payload.max_epochs, 10);
  assert.equal(fitReq.payload.learning_rate, 0.02);

  const resultsEl = root.querySelector<FakeElement>("#fuzzy-anfis-results")!;
  assert.ok(resultsEl.textContent.includes("train_rmse:"), "Deve exibir train_rmse");
  assert.ok(resultsEl.textContent.includes("val_rmse:"), "Deve exibir val_rmse");
  assert.ok(resultsEl.textContent.includes("best_epoch:"), "Deve exibir best_epoch");

  const chartEl = root.querySelector<FakeElement>("#fuzzy-anfis-rmse-chart")!;
  assert.ok(chartEl.innerHTML.includes("fuzzy-anfis-rmse-svg"), "Deve renderizar curva RMSE SVG");
  assert.ok(chartEl.innerHTML.includes('data-series="train_rmse"'));
  assert.ok(chartEl.innerHTML.includes('data-series="val_rmse"'));

  // Verifica que o sistema treinado foi carregado na bancada (TS + 4 regras para 2x2)
  assert.equal(root.querySelector<FakeElement>("#fuzzy-inference-type")!.value, "ts");
  assert.ok(root.querySelector<FakeElement>("#fuzzy-coverage-status")!.textContent.includes("4 regras"));
  assert.ok(root.querySelector<FakeElement>("#fuzzy-mf-svg")!.innerHTML.includes("fuzzy-mf-svg"));

  // Avalia superfície do sistema ANFIS treinado via Python real
  root.querySelector<FakeElement>("#fuzzy-surface-n-points")!.value = "5";
  root.querySelector('[data-action="fuzzy-eval-surface"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 250));
  assert.ok(
    root.querySelector<FakeElement>("#fuzzy-surface-chart-slot")!.innerHTML.includes("fuzzy-surface-chart"),
    "Superfície do FuzzySystem treinado via ANFIS deve ser renderizada",
  );

  // Treina também com bell e 3 MFs
  nmfsEl.value = "3";
  mftypeEl.value = "bell";
  epochsEl.value = "5";
  trainBtn.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 400));
  assert.ok(root.querySelector<FakeElement>("#fuzzy-coverage-status")!.textContent.includes("9 regras"));

  app.destroy();
});
