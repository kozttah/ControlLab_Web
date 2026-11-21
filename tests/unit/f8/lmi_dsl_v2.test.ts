/**
 * Testes unitários de WP-LMI-V2-01-DSL-PARSER-QUANTIFIERS e WP-LMI-V2-02-SYSTEM-CHARACTERIZATION-UI
 * (F8: f8-ui-charts) seguindo CL-LMI-DSL-DIR-001 v1.0.0.
 */

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import {
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
  generateQuantifiedCvxpySnippet,
  generateQuantifiedYalmipSnippet,
  LMI_DSL_TEMPLATES,
  parseLmiDsl,
  resolveShapeLabel,
} from "../../../web/features/views/lmi_dsl_parser.ts";

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

class StubLmiClient implements ControlLabEngineClient {
  private readonly listeners = new Set<EngineEventListener>();
  private state: EngineLifecycleState = "ready";

  public async init(): Promise<CapabilityDescriptor> {
    return this.getCapabilities();
  }
  public getLifecycleState(): EngineLifecycleState {
    return this.state;
  }
  public getCapabilities(): CapabilityDescriptor {
    return {
      api_version: RPC_API_VERSION,
      engine_kind: "pyodide",
      runtime_id: "stub-lmi-v2",
      operations: ["optimization.solve", "optimization.verify", "optimization.export_cvxpy", "optimization.export_yalmip"],
      backends: {
        numpy_scipy: { available: true, maturity: "beta" },
        native_primal_dual: { available: true, maturity: "beta" },
      },
      maturity: {},
      supports_transferables: false,
      supports_cooperative_cancel: false,
      max_memory_bytes: 128 * 1024 * 1024,
      lib_versions: { python: "3.12" },
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
  public async execute(req: RpcRequest, _opts?: ExecuteOptions): Promise<RpcResponse> {
    return {
      api_version: RPC_API_VERSION,
      request_id: req.request_id,
      project_id: req.project_id,
      project_revision: req.project_revision,
      status: "success",
      result: {},
      diagnostics: {},
      assumptions: {},
      warnings: [],
      error: null,
      provenance: { algorithm: "stub", lib_versions: { python: "3.12" } },
    };
  }
  public async cancel(): Promise<boolean> {
    return false;
  }
  public async resetWorker(): Promise<void> {}
  public async registerObject(
    project_id: string,
    id: string,
    revision: number,
    _value: Record<string, unknown>,
    _options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef> {
    return { project_id, object_id: id, revision, persisted: false, cached_in_worker: true };
  }
  public async getObject(): Promise<Record<string, unknown> | null> {
    return null;
  }
  public async commitProject(projectId: string, revision: number, _input?: CommitProjectInput): Promise<CommitProjectResult> {
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
  public subscribe(listener: EngineEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  public dispose(): void {
    this.listeners.clear();
  }
}

test("WP-LMI-V2-01: DSL Parser v2.0 (system, index, var[i], macro, He, bmat *, forall, CVXPY/YALMIP)", () => {
  const parserPath = fileURLToPath(
    new URL("../../../web/features/views/lmi_dsl_parser.ts", import.meta.url),
  );
  const parserSource = fs.readFileSync(parserPath, "utf8");
  assert.equal(/\beval\s*\(/.test(parserSource), false);
  assert.equal(/new\s+Function\b/.test(parserSource), false);

  // 1. Takagi-Sugeno PDC relaxed with macro, indexed vars, forall i & forall i, j where j > i
  const tsDsl = [
    "system ts rules=3 index=i,j premises=measured",
    "index k in 1..N",
    "var Q sym(n)",
    "var P[i] sym(n)",
    "var Y[i] rect(m, n)",
    "var L_obs[i] rect(n, p)",
    "Q > 0",
    "macro M(i, j) = A[i]*Q + Q*A[i]' + B[i]*Y[j] + Y[j]'*B[i]'",
    "forall i:",
    "  M(i, i) < 0",
    "forall i, j where j > i:",
    "  M(i, j) + M(j, i) < 0",
    "forall i:",
    "  recover K[i] = Y[i] * inv(Q)",
  ].join("\n");

  const parsedTs = parseLmiDsl(tsDsl);
  assert.equal(parsedTs.valid, true, `Erros inesperados: ${JSON.stringify(parsedTs.errors)}`);
  assert.equal(parsedTs.systemSpec?.systemClass, "ts");
  assert.equal(parsedTs.systemSpec?.nCount, 3);
  assert.equal(parsedTs.systemSpec?.premises, "measured");
  assert.equal(parsedTs.indices.length, 1);
  assert.equal(parsedTs.indices[0].name, "k");
  assert.equal(parsedTs.indices[0].resolvedEnd, 3);
  assert.equal(parsedTs.macros.length, 1);
  assert.equal(parsedTs.effectiveSystemN, 3);

  // Variables & indexedBy
  assert.equal(parsedTs.variables.length, 4);
  assert.deepEqual(parsedTs.variables[1].indexedBy, ["i"]);
  assert.deepEqual(parsedTs.variables[2].indexedBy, ["i"]);
  assert.ok(resolveShapeLabel(parsedTs.variables[2], { n: 2, m: 1, p: 1 }).includes("[i]"));

  // Quantifiers & exact expanded block count: 1 (Q>0) + 3 (forall i) + 3 (forall j>i) = 7
  assert.equal(parsedTs.constraints.length, 3);
  assert.equal(parsedTs.constraints[1].quantifier?.cardinality, 3);
  assert.ok(parsedTs.constraints[1].mathText.includes("∀ i ∈ {1..3}:"));
  assert.ok(parsedTs.constraints[1].mathText.includes("Aᵢ Q"));
  assert.equal(parsedTs.constraints[2].quantifier?.cardinality, 3);
  assert.ok(parsedTs.constraints[2].mathText.includes("∀ i, j ∈ {1..3}, j > i:"));
  assert.equal(parsedTs.expandedBlockCount, 7);
  assert.equal(parsedTs.bilinearWarnings.length, 0);

  // Recovery quantifier
  assert.equal(parsedTs.recoveries.length, 1);
  assert.equal(parsedTs.recoveries[0].quantifier?.cardinality, 3);
  assert.ok(parsedTs.recoveries[0].mathText.includes("Kᵢ = Yᵢ Q⁻¹"));

  // 2. Generalized plant Hinf with He(...) and bmat symmetry *
  const genTpl = LMI_DSL_TEMPLATES.find((t) => t.id === "hinf_generalized_brl")!;
  const parsedGen = parseLmiDsl(genTpl.dsl);
  assert.equal(parsedGen.valid, true);
  assert.equal(parsedGen.systemSpec?.systemClass, "lti");
  assert.equal(parsedGen.systemSpec?.generalized, true);
  assert.equal(parsedGen.inferredTemplate, "hinf_generalized_brl");
  assert.equal(parsedGen.bilinearWarnings.length, 0, "He(A*Q + B*Y) não deve gerar falso positivo bilinear");
  const bmatConstraint = parsedGen.constraints.find((c) => c.bmatRows !== null)!;
  assert.equal(bmatConstraint.bmatRows?.length, 3);
  assert.equal(bmatConstraint.bmatRows?.[1][0], "*");
  assert.ok(bmatConstraint.mathText.includes("B_w"));
  assert.ok(bmatConstraint.mathText.includes("C_z"));
  assert.ok(bmatConstraint.mathHtml.includes("lmi-bmat-sym"));

  // 3. Bilinear detection still catches K[i]*Q
  const bmiIndexed = parseLmiDsl("var Q sym(n)\nforall i: He(A[i]*Q + B[i]*K[i]*Q) < 0");
  assert.ok(bmiIndexed.bilinearWarnings.length > 0);
  assert.ok(bmiIndexed.bilinearWarnings[0].token.includes("K*Q"));

  // 4. Quantified CVXPY & YALMIP snippet generation
  const ctx = { systemClass: "ts" as const, n: 2, m: 1, p: 1, systemN: 3, premisesMeasured: true };
  const pySnippet = generateQuantifiedCvxpySnippet(parsedTs, ctx);
  assert.ok(pySnippet.includes("for i in range(N):"));
  assert.ok(pySnippet.includes("for j in range(i + 1, N):"));
  assert.ok(pySnippet.includes("Y_list = [cp.Variable((m, n)) for _ in range(N)]"));

  const mSnippet = generateQuantifiedYalmipSnippet(parsedTs, ctx);
  assert.ok(mSnippet.includes("for i = 1:N"));
  assert.ok(mSnippet.includes("for j = (i + 1):N"));
  assert.ok(mSnippet.includes("Y{i} = sdpvar(m, n, 'full')"));
});

test("WP-LMI-V2-02: Zona 2 Caracterização do Sistema (LTI generalizada, Politópica e TS) + Bidirecionalidade", async () => {
  const client = new StubLmiClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-lmi-zona2",
  });
  await app.client.init();
  app.shell.switchTab("optimization_lmi");

  // 1. Zona 2 card exists and starts in LTI mode
  const z2Card = root.querySelector<FakeElement>("#lmi-system-characterization-card")!;
  assert.ok(z2Card !== null);
  const sysSelect = root.querySelector<FakeElement>("#lmi-sys-class-select")!;
  assert.equal(sysSelect.value, "lti");
  assert.equal(root.querySelector<FakeElement>("#lmi-sys-panel-lti")!.hasAttribute("hidden"), false);
  assert.equal(root.querySelector<FakeElement>("#lmi-sys-panel-polytopic")!.hasAttribute("hidden"), true);
  assert.equal(root.querySelector<FakeElement>("#lmi-sys-panel-ts")!.hasAttribute("hidden"), true);

  // Enable generalized channels w and z
  const cbW = root.querySelector<FakeElement>("#lmi-gen-enable-w")!;
  const cbZ = root.querySelector<FakeElement>("#lmi-gen-enable-z")!;
  cbW.checked = true;
  cbW.dispatchEvent("change");
  cbZ.checked = true;
  cbZ.dispatchEvent("change");
  assert.equal(root.querySelector<FakeElement>("#lmi-gen-matrices-panel")!.hasAttribute("hidden"), false);

  // 2. Switch to Polytopic mode, set N_v=4, generate vertices, load polytopic template
  sysSelect.value = "polytopic";
  sysSelect.dispatchEvent("change");
  assert.equal(root.querySelector<FakeElement>("#lmi-sys-panel-polytopic")!.hasAttribute("hidden"), false);

  const tplSelect = root.querySelector<FakeElement>("#lmi-template-select")!;
  tplSelect.value = "polytopic_robust";
  tplSelect.dispatchEvent("change");
  assert.ok(root.querySelector("#lmi-expanded-blocks-badge")!.textContent.includes("3 blocos LMI"));

  const nvInput = root.querySelector<FakeElement>("#lmi-poly-vertices-count")!;
  nvInput.value = "4";
  nvInput.dispatchEvent("change");
  root.querySelector('[data-action="lmi-gen-polytope"]')!.dispatchEvent("click");
  assert.ok(root.querySelector("#lmi-poly-vertex-preview")!.textContent.includes("Vértice 4"));
  // Sync directive to DSL -> expanded blocks updates to 1 (Q>0) + 4 (forall i) = 5
  root.querySelector('[data-action="lmi-sync-dsl"]')!.dispatchEvent("click");
  assert.ok(root.querySelector("#lmi-expanded-blocks-badge")!.textContent.includes("5 blocos LMI"));

  // Export CVXPY quantified directly from modal
  root.querySelector('[data-action="lmi-export-cvxpy"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));
  const modalPre = root.querySelector<FakeElement>("#export-modal-content")!;
  assert.ok(modalPre.textContent.includes("for i in range(N):"));
  root.querySelector("#export-modal-close")!.dispatchEvent("click");

  // 3. Switch to TS mode, import memberships from Tab 5, toggle premise measured <-> unmeasured
  tplSelect.value = "ts_pdc_relaxed";
  tplSelect.dispatchEvent("change");
  assert.equal(sysSelect.value, "ts");
  assert.equal(root.querySelector<FakeElement>("#lmi-sys-panel-ts")!.hasAttribute("hidden"), false);

  root.querySelector('[data-action="lmi-import-fuzzy"]')!.dispatchEvent("click");
  assert.ok(root.querySelector("#lmi-ts-mf-summary")!.textContent.includes("h₁"));

  const toggleBtn = root.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!;
  assert.equal(toggleBtn.textContent, "Medida");
  toggleBtn.dispatchEvent("click");
  const toggleBtnAfter = root.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!;
  assert.equal(toggleBtnAfter.textContent, "Não Medida (Estimada)");
  assert.ok(root.querySelector("#lmi-ts-premises-list")!.textContent.includes("ts_partially_observed"));

  app.destroy();
});
