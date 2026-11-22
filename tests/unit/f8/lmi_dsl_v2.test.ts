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
  type SolverProgressEvent,
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
  type SolverProgressListener,
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
import {
  compileLmiDslToCanonicalSdp,
  type LmiCompileContext,
} from "../../../web/features/views/lmi_dsl_compiler.ts";
import {
  evaluateMathExpression,
  validateConvexMembershipFunctions,
} from "../../../web/features/views/lmi_ts_mf_eval.ts";
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

  // 3. Switch to TS mode, verify Tab 5 import is removed, verify default analytical h_i(z), toggle premise measured <-> unmeasured
  tplSelect.value = "ts_pdc_relaxed";
  tplSelect.dispatchEvent("change");
  assert.equal(sysSelect.value, "ts");
  assert.equal(root.querySelector<FakeElement>("#lmi-sys-panel-ts")!.hasAttribute("hidden"), false);

  assert.equal(root.querySelector("#btn-lmi-import-fuzzy"), null);
  assert.equal(root.querySelector('[data-action="lmi-import-fuzzy"]'), null);
  assert.ok(root.querySelector("#lmi-ts-mf-summary")!.textContent.includes("h₁(z) = (1 + sin(z1)) / 2"));
  assert.ok(root.querySelector("#lmi-ts-mf-validation")!.textContent.includes("Soma convexa válida"));

  const toggleBtn = root.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!;
  assert.equal(toggleBtn.textContent, "Medida");
  toggleBtn.dispatchEvent("click");
  const toggleBtnAfter = root.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!;
  assert.equal(toggleBtnAfter.textContent, "Não Medida (Estimada)");
  assert.ok(root.querySelector("#lmi-ts-premises-list")!.textContent.includes("ts_partially_observed"));

  app.destroy();
});

test("WP-PHASE3-S3-F8: Live subscribeProgress, post-solve iteration_log e envelope n<=28 / n<=20 H∞", async () => {
  class ProgressStubClient extends StubLmiClient {
    public readonly progressListeners = new Set<SolverProgressListener>();
    public emitLiveDuringSolve = true;
    public responseIterationLog: Array<Record<string, number>> | null = null;
    public liveStatusSeenDuringExecute = "";
    public liveRowsSeenDuringExecute = 0;
    public docRoot: FakeElement | null = null;

    public subscribeProgress(listener: SolverProgressListener): () => void {
      this.progressListeners.add(listener);
      return () => {
        this.progressListeners.delete(listener);
      };
    }

    public override async execute(req: RpcRequest, opts?: ExecuteOptions): Promise<RpcResponse> {
      if (req.operation === "optimization.solve" && this.emitLiveDuringSolve) {
        // Unrelated request_id should be ignored by LmiView
        for (const fn of this.progressListeners) {
          fn({
            request_id: "other-unrelated-request",
            progress: {
              iter: 99,
              max_iters: 100,
              gap: 0.99,
              primal_res: 0.5,
              dual_res: 0.5,
              min_eig: -0.1,
              alpha: 0.5,
              elapsed_ms: 999.0,
            },
          });
        }

        const liveEvents: SolverProgressEvent[] = [
          {
            request_id: req.request_id,
            progress: {
              iter: 1,
              max_iters: 50,
              gap: 1.25e-1,
              primal_res: 4.0e-3,
              dual_res: 3.1e-3,
              min_eig: -1.5e-2,
              alpha: 0.8,
              elapsed_ms: 4.2,
            },
          },
          {
            request_id: req.request_id,
            progress: {
              iter: 2,
              max_iters: 50,
              gap: 3.4e-4,
              primal_res: 1.2e-6,
              dual_res: 9.5e-7,
              min_eig: 2.1e-3,
              alpha: 1.0,
              elapsed_ms: 8.7,
            },
          },
        ];
        for (const ev of liveEvents) {
          for (const fn of this.progressListeners) fn(ev);
        }

        if (this.docRoot) {
          this.liveStatusSeenDuringExecute =
            this.docRoot.querySelector("#lmi-solver-progress-status")?.textContent ?? "";
          this.liveRowsSeenDuringExecute =
            this.docRoot.querySelector("#lmi-solver-progress-tbody")?.querySelectorAll("tr").length ?? 0;
        }
      }

      const base = await super.execute(req, opts);
      if (req.operation === "optimization.solve") {
        return {
          ...base,
          result: {
            solver_status: "optimal",
            audit_feasibility: "strictly_feasible",
            certificate_status: "validated_dual",
            conditioning: { status: "well_conditioned", condition_number: 12.4 },
            controller_validity: "verified_under_assumptions",
            residuals: { primal_block_min_eigs: [0.0021, 0.15] },
            ...(this.responseIterationLog ? { iteration_log: this.responseIterationLog } : {}),
          },
          diagnostics: {
            ...(this.responseIterationLog ? { iteration_log: this.responseIterationLog } : {}),
          },
        };
      }
      return base;
    }
  }

  const client = new ProgressStubClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  client.docRoot = root;

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-lmi-progress",
  });
  await app.client.init();
  app.shell.switchTab("optimization_lmi");

  // 1. Live progress updates during solve() + unsubscribe in finally
  assert.ok(root.querySelector("#lmi-solver-progress-panel") !== null);
  assert.ok(root.querySelector("#lmi-solver-progress-table") !== null);

  const solveBtn = root.querySelector<FakeElement>('[data-action="lmi-solve"]')!;
  solveBtn.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 25));
  assert.ok(client.liveStatusSeenDuringExecute.includes("iteração 2/50"));
  assert.equal(client.liveRowsSeenDuringExecute, 2);
  assert.equal(client.progressListeners.size, 0, "subscribeProgress deve ser cancelada no finally");

  const tbodyAfterLive = root.querySelector("#lmi-solver-progress-tbody")!;
  assert.equal(tbodyAfterLive.querySelectorAll("tr").length, 2);
  assert.ok(!tbodyAfterLive.textContent.includes("999.0"), "Eventos de outro request_id devem ser ignorados");

  // 2. Post-solve iteration_log (long run > 60 iterations compacts cleanly)
  client.emitLiveDuringSolve = false;
  client.responseIterationLog = Array.from({ length: 75 }, (_, idx) => ({
    iter: idx + 1,
    max_iters: 100,
    gap: 1e-2 / (idx + 1),
    primal_res: 1e-5 / (idx + 1),
    dual_res: 1e-5 / (idx + 1),
    min_eig: 0.001 + idx * 1e-5,
    alpha: 1.0,
    elapsed_ms: (idx + 1) * 1.5,
  }));
  solveBtn.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 25));
  assert.equal(client.progressListeners.size, 0);
  const statusAfterLog = root.querySelector("#lmi-solver-progress-status")!.textContent;
  assert.ok(statusAfterLog.includes("75 iteração(ões)"));
  const rowsAfterLog = root.querySelector("#lmi-solver-progress-tbody")!.querySelectorAll("tr");
  assert.equal(rowsAfterLog.length, 56, "75 iterações devem compactar em 15 iniciais + 1 resumo + 40 finais");
  assert.ok(root.querySelector("#lmi-solver-progress-tbody")!.textContent.includes("20 iterações intermediárias omitidas"));

  // 3. Updated browser envelope checks: n=24 allowed for general feasibility, n=30 exceeds, n=22 exceeds for Hinf
  const makePlant = (n: number) => {
    const aData = Array.from({ length: n * n }, (_, k) => (Math.floor(k / n) === k % n ? -1 : 0));
    const bData = Array.from({ length: n }, (_, i) => (i === n - 1 ? 1 : 0));
    const cData = Array.from({ length: n }, (_, i) => (i === 0 ? 1 : 0));
    return {
      ...app.shell.getLqrWorkspace().getPlant(),
      state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
      matrices: {
        A: { shape: [n, n], dtype: "float64" as const, order: "C" as const, data: aData },
        B: { shape: [n, 1], dtype: "float64" as const, order: "C" as const, data: bData },
        C: { shape: [1, n], dtype: "float64" as const, order: "C" as const, data: cData },
        D: { shape: [1, 1], dtype: "float64" as const, order: "C" as const, data: [0] },
      },
    };
  };

  const editorEl = root.querySelector<FakeElement>("#lmi-code-editor")!;

  // General stabilization with n=24 (n_vars = 300 <= 448) -> hidden
  app.shell.getLqrWorkspace().updatePlant(makePlant(24));
  editorEl.value = "var Q sym(n)\nQ > 0\nA*Q + Q*A' < 0";
  editorEl.dispatchEvent("input");
  const banner = root.querySelector<FakeElement>("#lmi-envelope-banner")!;
  assert.equal(banner.hasAttribute("hidden"), true, "n=24 em factibilidade geral deve ficar dentro do envelope");

  // General stabilization with n=30 (> 28, n_vars = 465 > 448) -> visible
  app.shell.getLqrWorkspace().updatePlant(makePlant(30));
  editorEl.value = "var Q sym(n)\nQ > 0\nA*Q + Q*A' < 0";
  editorEl.dispatchEvent("input");
  assert.equal(banner.hasAttribute("hidden"), false, "n=30 deve exibir aviso do envelope");
  assert.ok(banner.textContent.includes("max_variables=448"));

  // Hinf norm minimization with n=22 (> 20) -> visible
  app.shell.getLqrWorkspace().updatePlant(makePlant(22));
  const hinfTpl = LMI_DSL_TEMPLATES.find((t) => t.id === "hinf_brl")!;
  editorEl.value = hinfTpl.dsl;
  editorEl.dispatchEvent("input");
  assert.equal(banner.hasAttribute("hidden"), false, "n=22 em H∞ (> 20) deve exibir aviso do envelope");

  app.destroy();
});

test("WP-PHASE4-01: Compilador Direto DSL v2.0 -> CanonicalSDPProblem (LTI, Politópico, TS PDC, H∞ BRL, rejeição bilinear e solve CPython)", async () => {
  const compilerPath = fileURLToPath(
    new URL("../../../web/features/views/lmi_dsl_compiler.ts", import.meta.url),
  );
  const compilerSource = fs.readFileSync(compilerPath, "utf8");
  assert.equal(/\beval\s*\(/.test(compilerSource), false, "Compilador não pode conter eval()");
  assert.equal(/new\s+Function\b/.test(compilerSource), false, "Compilador não pode conter new Function");

  const baseCtx: LmiCompileContext = {
    A: [
      [0, 1],
      [-2, -1],
    ],
    B: [[0], [1]],
    C: [[1, 0]],
    D: [[0]],
    Bw: [[0], [1]],
    Cz: [
      [1, 0],
      [0, 0.5],
    ],
    Dzu: [[0], [0.1]],
    Dzw: [[0], [0]],
  };

  // Helper to assert symmetry of all F0 and F_k
  const assertAllBlocksSymmetric = (problem: ReturnType<typeof compileLmiDslToCanonicalSdp>["problem"]) => {
    for (const blk of problem.blocks) {
      const dim = blk.F0.shape[0];
      assert.equal(blk.F0.shape[1], dim);
      for (const mat of [blk.F0, ...blk.F_k]) {
        for (let r = 0; r < dim; r += 1) {
          for (let c = r + 1; c < dim; c += 1) {
            assert.equal(mat.data[r * dim + c], mat.data[c * dim + r], `Assimetria em ${blk.name}`);
          }
        }
      }
    }
  };

  // 1. Custom LTI decay rate LMI: He(A*Q + B*Y) + 2*alpha*Q < 0, Q > 0
  const ltiDsl = [
    "var Q sym(n)",
    "var Y rect(m, n)",
    "param alpha = 0.5",
    "Q > 0",
    "He(A*Q + B*Y) + 2*alpha*Q < 0",
    "recover K = Y * inv(Q)",
  ].join("\n");
  const ltiParsed = parseLmiDsl(ltiDsl);
  assert.equal(ltiParsed.valid, true);
  const ltiCompiled = compileLmiDslToCanonicalSdp(ltiParsed, baseCtx);
  assert.equal(ltiCompiled.nVars, 5);
  assert.equal(ltiCompiled.blockCount, 2);
  assert.equal(ltiCompiled.problem.recovery_plan, null);
  assertAllBlocksSymmetric(ltiCompiled.problem);

  // 2. Polytopic robust stabilization (forall i: He(A[i]*Q + B[i]*Y) < 0)
  const polyDsl = LMI_DSL_TEMPLATES.find((t) => t.id === "polytopic_robust")!.dsl;
  const polyParsed = parseLmiDsl(polyDsl);
  const polyCtx: LmiCompileContext = {
    ...baseCtx,
    vertices: [
      {
        A: [
          [0, 1],
          [-1.7, -0.85],
        ],
        B: [[0], [1]],
      },
      {
        A: [
          [0, 1],
          [-2.3, -1.15],
        ],
        B: [[0], [1]],
      },
    ],
  };
  const polyCompiled = compileLmiDslToCanonicalSdp(polyParsed, polyCtx);
  assert.equal(polyCompiled.nVars, 5);
  assert.equal(polyCompiled.blockCount, 3);
  assertAllBlocksSymmetric(polyCompiled.problem);

  // 3. Takagi-Sugeno PDC with macro & forall i + forall i, j where j > i
  const tsDsl = LMI_DSL_TEMPLATES.find((t) => t.id === "ts_pdc_relaxed")!.dsl;
  const tsParsed = parseLmiDsl(tsDsl);
  const tsCompiled = compileLmiDslToCanonicalSdp(tsParsed, polyCtx);
  assert.equal(tsCompiled.nVars, 7, "Q(3) + Y[1](2) + Y[2](2) = 7");
  assert.equal(tsCompiled.blockCount, 4, "Q>0 + 2*(i) + 1*(j>i) = 4");
  assert.ok("Q" in tsCompiled.problem.variable_map);
  assert.ok("Y[1]" in tsCompiled.problem.variable_map);
  assert.ok("Y[2]" in tsCompiled.problem.variable_map);
  assertAllBlocksSymmetric(tsCompiled.problem);

  // 4. Generalized H-infinity BRL with bmat, *, Bw, Cz, Dzu, Dzw, minimize gamma_sq
  const hinfGenDsl = LMI_DSL_TEMPLATES.find((t) => t.id === "hinf_generalized_brl")!.dsl;
  const hinfGenParsed = parseLmiDsl(hinfGenDsl);
  const hinfGenCompiled = compileLmiDslToCanonicalSdp(hinfGenParsed, baseCtx);
  assert.equal(hinfGenCompiled.nVars, 6, "Q(3) + Y(2) + gamma_sq(1) = 6");
  assert.equal(hinfGenCompiled.blockCount, 3, "Q>0, gamma_sq>0, BRL(5x5)");
  assert.equal(hinfGenCompiled.problem.blocks[2].F0.shape[0], 5, "n(2) + nw(1) + nz(2) = 5");
  assert.deepEqual(hinfGenCompiled.problem.c.data, [0, 0, 0, 0, 0, 1]);
  assertAllBlocksSymmetric(hinfGenCompiled.problem);

  // 5. Bilinear term rejection (Y * Q)
  const bmiParsed = parseLmiDsl("var Q sym(n)\nvar Y rect(m, n)\nY * Q < 0");
  assert.throws(
    () => compileLmiDslToCanonicalSdp(bmiParsed, baseCtx),
    /bilinear|não afim/i,
  );
  // Also test directly inside compiler evaluator when parser warning is bypassed
  const forcedParsed = {
    ...bmiParsed,
    bilinearWarnings: [],
  };
  assert.throws(
    () => compileLmiDslToCanonicalSdp(forcedParsed, baseCtx),
    /bilinear/i,
  );

  // 6. Real CPython optimization.solve on all 4 compiled problems!
  const loaded = await cpythonLoader({ indexURL: "", packages: [] });
  const pyodide = loaded.pyodide;
  if (!pyodide.pyimport || !pyodide.toPy) {
    throw new Error("cpythonLoader não expôs pyimport/toPy.");
  }
  const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
    dispatch: (arg: unknown) => RpcResponse;
  };
  const runSolve = (problem: unknown): RpcResponse => {
    const req: RpcRequest = {
      api_version: RPC_API_VERSION,
      request_id: `comp-test-${Math.random().toString(36).slice(2)}`,
      project_id: "proj-compiler-test",
      project_revision: 1,
      operation: "optimization.solve",
      payload: { problem },
      options: {},
      timeout_policy: { hard_timeout_ms: 30000 },
    };
    const proxy = pyodide.toPy!({ request: req, payload: req.payload });
    const resp = rpcMod.dispatch(proxy);
    proxy.destroy();
    return resp;
  };

  const resLti = runSolve(ltiCompiled.problem);
  assert.equal(resLti.status, "success", JSON.stringify(resLti.error));
  const ltiRes = resLti.result as Record<string, unknown>;
  assert.equal(ltiRes.audit_feasibility, "strictly_feasible");
  const ltiVars = ltiRes.variables as Record<string, unknown>;
  assert.ok(ltiVars?.Q && ltiVars?.Y);

  const resPoly = runSolve(polyCompiled.problem);
  assert.equal(resPoly.status, "success", JSON.stringify(resPoly.error));
  assert.equal((resPoly.result as Record<string, unknown>).audit_feasibility, "strictly_feasible");

  const resTs = runSolve(tsCompiled.problem);
  assert.equal(resTs.status, "success", JSON.stringify(resTs.error));
  const tsRes = resTs.result as Record<string, unknown>;
  assert.equal(tsRes.audit_feasibility, "strictly_feasible");
  const tsVars = tsRes.variables as Record<string, unknown>;
  assert.ok(tsVars?.["Y[1]"] && tsVars?.["Y[2]"]);

  const resHinf = runSolve(hinfGenCompiled.problem);
  assert.equal(resHinf.status, "success", JSON.stringify(resHinf.error));
  const hinfRes = resHinf.result as Record<string, unknown>;
  assert.ok(
    hinfRes.audit_feasibility === "strictly_feasible" ||
      hinfRes.audit_feasibility === "approximately_feasible",
    `Esperado feasible para H∞ BRL, obtido ${String(hinfRes.audit_feasibility)}`,
  );
  const hinfVars = hinfRes.variables as Record<string, unknown>;
  assert.ok(hinfVars?.gamma_sq);
});

test("WP-PHASE4-01: LmiView end-to-end TS PDC com compilador direto e recuperação K[1], K[2]", async () => {
  const loaded = await cpythonLoader({ indexURL: "", packages: [] });
  const pyodide = loaded.pyodide;
  if (!pyodide.pyimport || !pyodide.toPy) {
    throw new Error("cpythonLoader não expôs pyimport/toPy.");
  }
  const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
    dispatch: (arg: unknown) => RpcResponse;
  };
  let resolveDone: (() => void) | null = null;
  const donePromise = new Promise<void>((r) => {
    resolveDone = r;
  });
  class RealPythonLmiClient extends StubLmiClient {
    public override async execute(req: RpcRequest): Promise<RpcResponse> {
      try {
        const proxy = pyodide.toPy!({ request: req, payload: req.payload });
        const resp = rpcMod.dispatch(proxy);
        proxy.destroy();
        return resp;
      } finally {
        if (req.operation === "optimization.solve") {
          setTimeout(() => resolveDone?.(), 20);
        }
      }
    }
  }

  const client = new RealPythonLmiClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-lmi-ts-e2e",
  });
  await app.client.init();
  app.shell.switchTab("optimization_lmi");

  const tplSelect = root.querySelector<FakeElement>("#lmi-template-select")!;
  tplSelect.value = "ts_pdc_relaxed";
  tplSelect.dispatchEvent("change");

  root.querySelector('[data-action="lmi-solve"]')!.dispatchEvent("click");
  await donePromise;

  const gainText = root.querySelector("#lmi-recovered-gain")!.textContent;
  assert.ok(gainText.includes("K[1]"), `Esperado K[1] em '${gainText}'`);
  assert.ok(gainText.includes("K[2]"), `Esperado K[2] em '${gainText}'`);

  app.destroy();
});

test("WP-ROADMAP-TS-UNMEASURED-OBS: Observador TS com premissas não medidas (DSL, deltaVertices, solve CPython, L[1]/L[2] e LmiView)", async () => {
  // 1. Parser + Compiler + CPython solve for 2-rule, 2-perturbation TS unmeasured-premise observer
  const obsDsl = [
    "system ts (unmeasured_observer)",
    "index i in 1..2",
    "index k in 1..2",
    "param alpha = 0.2",
    "var P sym(n)",
    "var N[i] rect(n, p)",
    "P > 0",
    "forall i, k:",
    "  He(P * (A[i] + dA[k]) - N[i] * (C[i] + dC[k])) + 2*alpha*P < 0",
    "recover L[i] = inv(P) * N[i]",
  ].join("\n");

  const parsed = parseLmiDsl(obsDsl);
  assert.equal(parsed.valid, true, `Erros inesperados: ${JSON.stringify(parsed.errors)}`);
  assert.equal(parsed.systemSpec?.systemClass, "ts");
  assert.equal(parsed.systemSpec?.premises, "unmeasured");
  assert.equal(parsed.indices.length, 2);
  assert.equal(parsed.bilinearWarnings.length, 0);
  assert.equal(parsed.expandedBlockCount, 5, "P>0 (1) + 2x2 Cartesian product (4) = 5 blocos");

  const obsCtx: LmiCompileContext = {
    A: [
      [0, 1],
      [-2, -1],
    ],
    B: [[0], [1]],
    C: [[1, 0]],
    D: [[0]],
    vertices: [
      {
        A: [
          [0, 1],
          [-1.8, -0.9],
        ],
        B: [[0], [1]],
        C: [[1, 0]],
      },
      {
        A: [
          [0, 1],
          [-2.2, -1.1],
        ],
        B: [[0], [1]],
        C: [[1, 0]],
      },
    ],
    deltaVertices: [
      {
        dA: [
          [0, 0.2],
          [0, 0],
        ],
        dC: [[0, 0]],
      },
      {
        dA: [
          [0, -0.2],
          [0, 0],
        ],
        dC: [[0, 0]],
      },
    ],
  };

  const compiled = compileLmiDslToCanonicalSdp(parsed, obsCtx);
  assert.equal(compiled.nVars, 7, "P sym(2)=3 + N[1] rect(2,1)=2 + N[2] rect(2,1)=2 -> 7");
  assert.equal(compiled.blockCount, 5);
  assert.ok("P" in compiled.problem.variable_map);
  assert.ok("N[1]" in compiled.problem.variable_map);
  assert.ok("N[2]" in compiled.problem.variable_map);

  const loaded = await cpythonLoader({ indexURL: "", packages: [] });
  const pyodide = loaded.pyodide;
  if (!pyodide.pyimport || !pyodide.toPy) {
    throw new Error("cpythonLoader não expôs pyimport/toPy.");
  }
  const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
    dispatch: (arg: unknown) => RpcResponse;
  };

  const req: RpcRequest = {
    api_version: RPC_API_VERSION,
    request_id: "ts-obs-unmeasured-1",
    project_id: "proj-ts-obs-test",
    project_revision: 1,
    operation: "optimization.solve",
    payload: { problem: compiled.problem },
    options: {},
    timeout_policy: { hard_timeout_ms: 30000 },
  };
  const proxy = pyodide.toPy!({ request: req, payload: req.payload });
  const resp = rpcMod.dispatch(proxy);
  proxy.destroy();

  assert.equal(resp.status, "success", JSON.stringify(resp.error));
  const resObj = resp.result as Record<string, unknown>;
  assert.equal(resObj.audit_feasibility, "strictly_feasible");
  const vars = resObj.variables as Record<string, { shape: number[]; data: number[] }>;
  assert.ok(vars?.P && vars?.["N[1]"] && vars?.["N[2]"]);

  // 2. LmiView UI: #lmi-ts-unmeasured-panel visibility, #btn-lmi-generate-ts-observer, and E2E L[1]/L[2] display
  let resolveDone: (() => void) | null = null;
  const donePromise = new Promise<void>((r) => {
    resolveDone = r;
  });
  class RealPythonObsClient extends StubLmiClient {
    public override async execute(r: RpcRequest): Promise<RpcResponse> {
      try {
        const px = pyodide.toPy!({ request: r, payload: r.payload });
        const out = rpcMod.dispatch(px);
        px.destroy();
        return out;
      } finally {
        if (r.operation === "optimization.solve") {
          setTimeout(() => resolveDone?.(), 20);
        }
      }
    }
  }

  const client = new RealPythonObsClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-ts-obs-ui",
  });
  await app.client.init();
  app.shell.switchTab("optimization_lmi");

  const sysSelect = root.querySelector<FakeElement>("#lmi-sys-class-select")!;
  sysSelect.value = "ts";
  sysSelect.dispatchEvent("change");

  const unmeasuredPanel = root.querySelector<FakeElement>("#lmi-ts-unmeasured-panel")!;
  assert.equal(unmeasuredPanel.hasAttribute("hidden"), true, "Oculto enquanto todas as premissas são medidas");

  const toggleBtn = root.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!;
  toggleBtn.dispatchEvent("click");
  assert.equal(unmeasuredPanel.hasAttribute("hidden"), false, "Visível quando premissa não medida é selecionada");

  const methodSel = root.querySelector<FakeElement>("#lmi-ts-obs-method")!;
  assert.ok(methodSel !== null);
  const daInput = root.querySelector<FakeElement>("#lmi-ts-obs-da")!;
  const dcInput = root.querySelector<FakeElement>("#lmi-ts-obs-dc")!;
  assert.ok(daInput !== null && dcInput !== null);

  root.querySelector("#btn-lmi-generate-ts-observer")!.dispatchEvent("click");
  const editorEl = root.querySelector<FakeElement>("#lmi-code-editor")!;
  assert.ok(editorEl.value.includes("system ts (unmeasured_observer)"));
  assert.ok(editorEl.value.includes("recover L[i] = inv(P) * N[i]"));
  assert.equal(root.querySelector("#lmi-syntax-badge")!.textContent, "Sintaxe OK");
  assert.ok(root.querySelector("#lmi-expanded-blocks-badge")!.textContent.includes("5 blocos LMI"));

  root.querySelector('[data-action="lmi-solve"]')!.dispatchEvent("click");
  await donePromise;

  const gainText = root.querySelector("#lmi-recovered-gain")!.textContent;
  assert.ok(gainText.includes("L[1]"), `Esperado L[1] em '${gainText}'`);
  assert.ok(gainText.includes("L[2]"), `Esperado L[2] em '${gainText}'`);

  app.destroy();
});

test("WP-PHASE4-03-F8: Vértices editáveis A,B,C,D (Politópico e TS) e Funções de Pertinência TS", async () => {
  const capturedProblems: Array<{ blocks: Array<{ name: string; F0: { data: number[] }; F_k: Array<{ data: number[] }> }> }> = [];
  class CaptureClient extends StubLmiClient {
    public override async execute(req: RpcRequest): Promise<RpcResponse> {
      if (req.operation === "optimization.solve" && req.payload.problem) {
        capturedProblems.push(req.payload.problem as { blocks: Array<{ name: string; F0: { data: number[] }; F_k: Array<{ data: number[] }> }> });
      }
      return super.execute(req);
    }
  }

  const client = new CaptureClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-lmi-editable-vertices",
  });
  await app.client.init();
  app.shell.switchTab("optimization_lmi");

  // 1. Polytopic mode: edit A[1] and B[1] (idx=0) and verify invalid syntax marking + resize preservation + compiled problem
  const tplSelect = root.querySelector<FakeElement>("#lmi-template-select")!;
  tplSelect.value = "polytopic_robust";
  tplSelect.dispatchEvent("change");

  const polyA1 = root.querySelector<FakeElement>('input[data-vertex-kind="poly"][data-vertex-idx="0"][data-vertex-mat="A"]')!;
  const polyB1 = root.querySelector<FakeElement>('input[data-vertex-kind="poly"][data-vertex-idx="0"][data-vertex-mat="B"]')!;
  assert.ok(polyA1 !== null && polyB1 !== null);

  // Invalid syntax marks aria-invalid="true" and .lmi-input-invalid without overwriting value
  polyA1.value = "[[0, 1], [-5";
  polyA1.dispatchEvent("input");
  assert.equal(polyA1.getAttribute("aria-invalid"), "true");
  assert.ok(polyA1.className.includes("lmi-input-invalid"));
  assert.equal(polyA1.value, "[[0, 1], [-5");

  // Valid edit to A[1] and B[1]
  polyA1.value = "[[0, 1], [-7.5, -3.25]]";
  polyA1.dispatchEvent("input");
  assert.equal(polyA1.getAttribute("aria-invalid"), null);
  assert.equal(polyA1.className.includes("lmi-input-invalid"), false);

  polyB1.value = "[[0], [2.5]]";
  polyB1.dispatchEvent("change");

  // Resize N_v from 2 -> 3 preserves edited vertex 0 and initializes vertex 2 from active plant
  const nvInput = root.querySelector<FakeElement>("#lmi-poly-vertices-count")!;
  nvInput.value = "3";
  nvInput.dispatchEvent("change");
  const polyA1AfterResize = root.querySelector<FakeElement>('input[data-vertex-kind="poly"][data-vertex-idx="0"][data-vertex-mat="A"]')!;
  assert.equal(polyA1AfterResize.value, "[[0, 1], [-7.5, -3.25]]");
  const polyA3 = root.querySelector<FakeElement>('input[data-vertex-kind="poly"][data-vertex-idx="2"][data-vertex-mat="A"]')!;
  assert.ok(polyA3 !== null);

  // Restore N_v=2 and solve to verify compiled CanonicalSDPProblem reflects edited A[1] & B[1]
  nvInput.value = "2";
  nvInput.dispatchEvent("change");
  root.querySelector('[data-action="lmi-solve"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 20));

  assert.equal(capturedProblems.length, 1);
  // In He(A[1]*Q + B[1]*Y) < 0, F_k for Y[0] (var_id=3, row=0 of Y -> [1, 0]) has -B[1] = [[0], [-2.5]]
  const polyBlock = capturedProblems[0].blocks[1];
  assert.ok(
    polyBlock.F_k.some((fk) => fk.data.some((val) => Math.abs(val - (-2.5)) < 1e-9 || Math.abs(val - 2.5) < 1e-9)),
    "Esperado B[1]=[0; 2.5] refletido em F_k do CanonicalSDPProblem politópico",
  );
  // And F_k for Q00 (var_id=0, Q=[[1,0],[0,0]]) has -He(A[1]*E_00) -> off-diagonal -(-7.5) = 7.5
  assert.ok(
    polyBlock.F_k[0].data.some((val) => Math.abs(val - 7.5) < 1e-9),
    "Esperado A[1][1][0]=-7.5 refletido em F_k[0] do CanonicalSDPProblem politópico",
  );

  // 2. Takagi-Sugeno mode: edit A[1]/B[1] in #lmi-ts-vertex-editor and verify compiled problem
  tplSelect.value = "ts_pdc_relaxed";
  tplSelect.dispatchEvent("change");

  const tsA1 = root.querySelector<FakeElement>('input[data-vertex-kind="ts"][data-vertex-idx="0"][data-vertex-mat="A"]')!;
  const tsB1 = root.querySelector<FakeElement>('input[data-vertex-kind="ts"][data-vertex-idx="0"][data-vertex-mat="B"]')!;
  assert.ok(tsA1 !== null && tsB1 !== null);
  tsA1.value = "[[0, 1], [-9.25, -4]]";
  tsA1.dispatchEvent("input");
  tsB1.value = "[[0], [3.5]]";
  tsB1.dispatchEvent("input");

  root.querySelector('[data-action="lmi-solve"]')!.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 20));

  assert.equal(capturedProblems.length, 2);
  const tsBlock = capturedProblems[1].blocks[1];
  assert.ok(
    tsBlock.F_k[0].data.some((val) => Math.abs(val - 9.25) < 1e-9),
    "Esperado A[1][1][0]=-9.25 refletido no CanonicalSDPProblem TS",
  );
  assert.ok(
    tsBlock.F_k.some((fk) => fk.data.some((val) => Math.abs(val - (-3.5)) < 1e-9 || Math.abs(val - 3.5) < 1e-9)),
    "Esperado B[1]=[0; 3.5] refletido no CanonicalSDPProblem TS",
  );

  // 3. TS Analytical Weighting Functions editor (#lmi-ts-mf-editor) & Premise Universe [z_min, z_max]:
  assert.equal(root.querySelector("#btn-lmi-import-fuzzy"), null);

  const toggle0 = root.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!;
  toggle0.dispatchEvent("click");
  assert.equal(
    root.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!.textContent,
    "Não Medida (Estimada)",
  );

  // Add a second premise and edit its name and universe [z_min, z_max]
  root.querySelector("#btn-lmi-add-ts-premise")!.dispatchEvent("click");
  const premName1 = root.querySelector<FakeElement>('input[data-premise-field="name"][data-premise-idx="1"]')!;
  const premMin1 = root.querySelector<FakeElement>('input[data-premise-field="min"][data-premise-idx="1"]')!;
  const premMax1 = root.querySelector<FakeElement>('input[data-premise-field="max"][data-premise-idx="1"]')!;
  assert.ok(premName1 !== null && premMin1 !== null && premMax1 !== null);
  premName1.value = "theta_2";
  premName1.dispatchEvent("input");
  premMin1.value = "0";
  premMin1.dispatchEvent("input");
  premMax1.value = "2";
  premMax1.dispatchEvent("input");

  // Add a third h_3(z) function -> initially "0" (valid sum since h1+h2=1), then edit to invalid "-0.5"
  root.querySelector("#btn-lmi-add-ts-mf")!.dispatchEvent("click");
  const mfExpr2 = root.querySelector<FakeElement>('input[data-mf-field="expression"][data-mf-idx="2"]')!;
  assert.ok(mfExpr2 !== null);

  mfExpr2.value = "theta_2 * 0.25";
  mfExpr2.dispatchEvent("input");
  const mfSummaryText = root.querySelector("#lmi-ts-mf-summary")!.textContent;
  assert.ok(mfSummaryText.includes("h₃(z) = theta_2 * 0.25"), `Resumo inesperado: ${mfSummaryText}`);

  const validationInvalid = root.querySelector("#lmi-ts-mf-validation")!.textContent;
  assert.ok(validationInvalid.includes("Inválido"), `Esperado inválido quando soma != 1, obtido: ${validationInvalid}`);

  // Premise 0 should still be unmeasured
  assert.equal(
    root.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!.textContent,
    "Não Medida (Estimada)",
  );

  // Remove the added MF row -> back to h1 + h2 = 1 -> valid
  root.querySelector<FakeElement>('[data-action="lmi-remove-ts-mf"][data-mf-idx="2"]')!.dispatchEvent("click");
  assert.equal(root.querySelector('input[data-mf-field="expression"][data-mf-idx="2"]'), null);
  assert.ok(root.querySelector("#lmi-ts-mf-validation")!.textContent.includes("Soma convexa válida"));

  app.destroy();
});

test("WP-PHASE4-05-F8: Avaliador analítico h_i(z) e validateConvexMembershipFunctions", () => {
  // 1. Valid sector-nonlinearity functions (1 + sin(z1))/2 and (1 - sin(z1))/2 on [-1, 1]
  const validRes = validateConvexMembershipFunctions(
    [{ name: "z1", min: -1, max: 1 }],
    [
      { label: "h1", expression: "(1 + sin(z1)) / 2" },
      { label: "h2", expression: "(1 - sin(z1)) / 2" },
    ],
  );
  assert.equal(validRes.valid, true, validRes.message);
  assert.ok(validRes.minWeight >= 0);
  assert.ok(validRes.maxSumError <= 1e-6);

  // 2. Valid 2D sector-nonlinearity on [-1, 1] x [-1, 1]
  const valid2D = validateConvexMembershipFunctions(
    [
      { name: "z1", min: -1, max: 1 },
      { name: "z2", min: -1, max: 1 },
    ],
    [
      { label: "h1", expression: "((1 + z1) * (1 + z2)) / 4" },
      { label: "h2", expression: "((1 + z1) * (1 - z2)) / 4" },
      { label: "h3", expression: "((1 - z1) * (1 + z2)) / 4" },
      { label: "h4", expression: "((1 - z1) * (1 - z2)) / 4" },
    ],
  );
  assert.equal(valid2D.valid, true, valid2D.message);

  // 3. Invalid negative weight: z1 and 1 - z1 on [-1, 1]
  const negRes = validateConvexMembershipFunctions(
    [{ name: "z1", min: -1, max: 1 }],
    [
      { label: "h1", expression: "z1" },
      { label: "h2", expression: "1 - z1" },
    ],
  );
  assert.equal(negRes.valid, false);
  assert.ok(negRes.counterexample !== undefined);
  assert.ok(negRes.counterexample.z1 < 0, `Esperado z1 < 0 no contraexemplo: ${JSON.stringify(negRes.counterexample)}`);

  // 4. Invalid sum != 1: 0.4 and 0.4 on [-1, 1]
  const sumRes = validateConvexMembershipFunctions(
    [{ name: "z1", min: -1, max: 1 }],
    [
      { label: "h1", expression: "0.4" },
      { label: "h2", expression: "0.4" },
    ],
  );
  assert.equal(sumRes.valid, false);
  assert.ok(sumRes.counterexample !== undefined);
  assert.ok(sumRes.maxSumError > 0.19);

  // 5. Division by zero on domain [-1, 1] (z1 = 0 is in 11-point grid)
  const divZeroRes = validateConvexMembershipFunctions(
    [{ name: "z1", min: -1, max: 1 }],
    [
      { label: "h1", expression: "1 / z1" },
      { label: "h2", expression: "1 - 1 / z1" },
    ],
  );
  assert.equal(divZeroRes.valid, false);
  assert.equal(divZeroRes.counterexample?.z1, 0);

  // 6. Direct expression evaluation: scientific notation, pi, e, power, functions
  assert.ok(Math.abs(evaluateMathExpression("1e-2 + cos(pi) + log(e^2) - 2^3^1", {}) - (0.01 - 1 + 2 - 8)) < 1e-12);
  assert.equal(evaluateMathExpression("min(abs(-3), max(1, sqrt(16)))", {}), 3);
  assert.equal(evaluateMathExpression("-x^2 + 1", { x: 3 }), -8);
});

test("WP-ROADMAP-CTRLAB-LMI-PERSISTENCE: roundtrip .ctrlab preserva e restaura estado completo da Aba 6 LMI", async () => {
  const loaded = await cpythonLoader({ indexURL: "", packages: [] });
  const pyodide = loaded.pyodide;
  if (!pyodide.pyimport || !pyodide.toPy) {
    throw new Error("cpythonLoader não expôs pyimport/toPy.");
  }
  const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
    dispatch: (arg: unknown) => RpcResponse;
  };

  class RealPythonRoundtripClient extends StubLmiClient {
    private readonly objects = new Map<string, Record<string, unknown>>();

    public override async registerObject(
      project_id: string,
      id: string,
      revision: number,
      value: Record<string, unknown>,
      _options?: RegisterObjectOptions,
    ): Promise<RegisteredObjectRef> {
      this.objects.set(`${project_id}::${id}#${revision}`, structuredClone(value));
      return { project_id, object_id: id, revision, persisted: false, cached_in_worker: true };
    }

    public override async execute(req: RpcRequest): Promise<RpcResponse> {
      const payload = structuredClone(req.payload);
      if (payload.plant_ref && !payload.plant) {
        const ref = payload.plant_ref as { id: string; revision: number };
        const found = this.objects.get(`${req.project_id}::${ref.id}#${ref.revision}`);
        if (found) {
          payload.plant = found;
          delete payload.plant_ref;
        }
      }
      const proxy = pyodide.toPy!({ request: req, payload });
      const resp = rpcMod.dispatch(proxy);
      proxy.destroy();
      return resp;
    }
  }

  const client1 = new RealPythonRoundtripClient();
  const doc1 = new FakeDocument();
  const root1 = doc1.createElement("div");

  const app1 = mountControlLabApp(root1 as unknown as HTMLElement, {
    client: client1,
    project_id: "proj-lmi-persistence",
  });
  await app1.client.init();

  // Garante projeto LQR comitado para liberar exportação .ctrlab
  await app1.shell.getLqrWorkspace().pointerUp({ qScale: 1.0, rScale: 1.0 });
  assert.equal(
    app1.shell.getLqrWorkspace().canExport().allowed,
    true,
    JSON.stringify({
      guard: app1.shell.getLqrWorkspace().canExport(),
      err: app1.shell.getLqrWorkspace().getLastError(),
    }),
  );

  app1.shell.switchTab("optimization_lmi");

  // 1. Mudar para Takagi-Sugeno, editar A[1], h_1(z), premissas [z_min, z_max], unmeasured + dA/dC, extraIndices e DSL customizada
  const sysClassEl = root1.querySelector<FakeElement>("#lmi-sys-class-select")!;
  sysClassEl.value = "ts";
  sysClassEl.dispatchEvent("change");

  const tsA1 = root1.querySelector<FakeElement>('input[data-vertex-kind="ts"][data-vertex-idx="0"][data-vertex-mat="A"]')!;
  tsA1.value = "[[0, 1], [-8.75, -3.25]]";
  tsA1.dispatchEvent("input");

  const mf0 = root1.querySelector<FakeElement>('input[data-mf-field="expression"][data-mf-idx="0"]')!;
  mf0.value = "(1 + cos(z1)) / 2";
  mf0.dispatchEvent("input");

  const premMin0 = root1.querySelector<FakeElement>('input[data-premise-field="min"][data-premise-idx="0"]')!;
  premMin0.value = "-2.5";
  premMin0.dispatchEvent("input");
  const premMax0 = root1.querySelector<FakeElement>('input[data-premise-field="max"][data-premise-idx="0"]')!;
  premMax0.value = "2.5";
  premMax0.dispatchEvent("input");

  root1.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!.dispatchEvent("click");

  const daEl = root1.querySelector<FakeElement>("#lmi-ts-obs-da")!;
  daEl.value = "[[[0, 0.35], [0, 0]], [[0, -0.35], [0, 0]]]";
  daEl.dispatchEvent("input");

  const dcEl = root1.querySelector<FakeElement>("#lmi-ts-obs-dc")!;
  dcEl.value = "[[[0.1, 0]], [[-0.1, 0]]]";
  dcEl.dispatchEvent("input");

  const extraIdxEl = root1.querySelector<FakeElement>("#lmi-extra-indices")!;
  extraIdxEl.value = "j, k";
  extraIdxEl.dispatchEvent("input");

  const customDsl = [
    "system ts rules=2 index=i,j,k premises=unmeasured",
    "var Q symmetric(n, n) > 0",
    "var Y[i] matrix(m, n)",
    "forall i in 1..N:",
    "  He(A[i]*Q + B[i]*Y[i]) + 0.1*I < 0",
    "minimize trace(Q)",
  ].join("\n");
  const codeEl = root1.querySelector<FakeElement>("#lmi-code-editor")!;
  codeEl.value = customDsl;
  codeEl.dispatchEvent("input");

  // 2. Exportar .ctrlab via Python real
  const exported = await app1.shell.exportCtrlLab();
  assert.ok(exported.bytes.length > 0);
  app1.destroy();

  // 3. Montar app totalmente nova (LmiView limpa) e importar .ctrlab
  const client2 = new RealPythonRoundtripClient();
  const doc2 = new FakeDocument();
  const root2 = doc2.createElement("div");

  const app2 = mountControlLabApp(root2 as unknown as HTMLElement, {
    client: client2,
    project_id: "proj-lmi-persistence-2",
  });
  await app2.client.init();

  // Antes do import, não está em 'ts'
  assert.notEqual(root2.querySelector<FakeElement>("#lmi-sys-class-select")!.value, "ts");

  await app2.shell.importCtrlLab(exported.bytes);
  app2.shell.switchTab("optimization_lmi");

  // 4. Verificar restauração 100% fiel de toda a Aba 6
  assert.equal(root2.querySelector<FakeElement>("#lmi-sys-class-select")!.value, "ts");
  assert.equal(
    root2.querySelector<FakeElement>('input[data-vertex-kind="ts"][data-vertex-idx="0"][data-vertex-mat="A"]')!.value,
    "[[0, 1], [-8.75, -3.25]]",
  );
  assert.equal(
    root2.querySelector<FakeElement>('input[data-mf-field="expression"][data-mf-idx="0"]')!.value,
    "(1 + cos(z1)) / 2",
  );
  assert.equal(
    root2.querySelector<FakeElement>('input[data-premise-field="min"][data-premise-idx="0"]')!.value,
    "-2.5",
  );
  assert.equal(
    root2.querySelector<FakeElement>('input[data-premise-field="max"][data-premise-idx="0"]')!.value,
    "2.5",
  );
  assert.equal(
    root2.querySelector<FakeElement>('[data-action="lmi-toggle-premise"][data-premise-idx="0"]')!.textContent,
    "Não Medida (Estimada)",
  );
  assert.equal(
    root2.querySelector<FakeElement>("#lmi-ts-obs-da")!.value,
    "[[[0, 0.35], [0, 0]], [[0, -0.35], [0, 0]]]",
  );
  assert.equal(
    root2.querySelector<FakeElement>("#lmi-ts-obs-dc")!.value,
    "[[[0.1, 0]], [[-0.1, 0]]]",
  );
  assert.equal(root2.querySelector<FakeElement>("#lmi-extra-indices")!.value, "j, k");
  assert.equal(root2.querySelector<FakeElement>("#lmi-code-editor")!.value, customDsl);

  app2.destroy();
});




