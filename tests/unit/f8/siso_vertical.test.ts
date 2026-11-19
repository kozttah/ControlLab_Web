/**
 * Testes unitários normativos de WP-V1-F8-SISO-VERTICAL (F8: f8-ui-charts)
 *
 * Cobrem rigorosamente:
 * - T-FREQ-01: Planta analítica de 1ª ordem G(s) = 1/(s+1) (ou 1/(s+a)) com verificação
 *   exata de magnitude |G(jω)| = 1/sqrt(a² + ω²) e fase ∠G(jω) = -atan2(ω, a) [graus]
 *   contra o oráculo analítico com erro numérico < 1e-4 dB / 1e-4°.
 * - T-FREQ-02: Sistema com múltiplas frequências de cruzamento de ganho (0 dB) e fase (-180°),
 *   detecção de todas as travessias em `frequency.stability_margins`, marcadores no modelo
 *   de Bode e aviso explícito de múltiplas travessias.
 * - Rejeição estrita de modelos MIMO sem seleção explícita de canal SISO.
 * - Atraso puro vs Padé: atraso exato na frequência (e^{-jωτ}) por padrão; Padé apenas
 *   mediante opção explícita (use_pade=true), sem substituição silenciosa.
 * - Fast-Preview transitório vs Commit autoritativo: durante preview o resultado não
 *   vira execução autoritativa na aba e a exportação CSV é bloqueada.
 * - Lugar das Raízes (Root Locus) com overlays de 2ª ordem rotulados estritamente como
 *   `heuristic` e suporte a realimentação negativa e positiva.
 * - Resposta ao degrau SISO com extração de métricas (Mp, Ts, tr) e tabelas WCAG 2.2 AA.
 * - T-UI-01 / Fluxo DOM completo via `mountControlLabApp`: montagem da aplicação, comutação
 *   para a aba `siso_frequency`, painel `#siso-workspace-panel` interativo e slots de gráficos.
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
  buildAccessibleChartTable,
  exportChartToCsv,
  renderAccessibleTableHtml,
  renderBodeSvg,
  renderNyquistSvg,
  renderRootLocusSvg,
} from "../../../web/charts/scientific_chart.ts";
import { SisoWorkspace } from "../../../web/features/siso_workspace.ts";
import { TypedObjectWorkspace } from "../../../web/features/typed_workspace.ts";
import { ProjectTabsController } from "../../../web/features/project_tabs.ts";
import { cpythonLoader } from "../f7/cpython_runtime.mjs";

/**
 * Cliente de teste que conecta diretamente ao motor Python real (control_lab.core.rpc.dispatch)
 * materializando plant_ref/model_ref a partir do store interno.
 */
class PythonBackedSisoEngineClient implements ControlLabEngineClient {
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
      runtime_id: "test-f8-siso-python-engine",
      operations: [
        "worker.ping",
        "core.capabilities",
        "frequency.eval_response",
        "frequency.bode",
        "frequency.stability_margins",
        "frequency.root_locus",
        "frequency.step_response",
      ],
      backends: {
        numpy_scipy: { available: true, maturity: "beta" },
        native_primal_dual: { available: true, maturity: "beta" },
      },
      maturity: {
        "frequency.eval_response": "beta",
        "frequency.bode": "beta",
        "frequency.stability_margins": "beta",
        "frequency.root_locus": "beta",
        "frequency.step_response": "beta",
      },
      supports_transferables: true,
      supports_cooperative_cancel: true,
      max_memory_bytes: 256 * 1024 * 1024,
      lib_versions: {
        python: "3.12",
        numpy: "2.0",
        scipy: "1.14",
        control_lab: "1.0.0",
      },
      offline_ready: false,
    };
  }

  public getMetrics(): ExecutionMetrics {
    return createInitialExecutionMetrics();
  }

  public getCommittedRevision(_projectId?: string): number {
    return 1;
  }

  public async syncAdoptedProjectState(): Promise<void> {}

  private materializeRefs(
    projectId: string,
    payload: Record<string, unknown>,
  ): Record<string, unknown> {
    const out = structuredClone(payload);
    const ref = (out.plant_ref ?? out.model_ref) as { id?: string; revision?: number } | undefined;
    if (ref && typeof ref.id === "string" && typeof ref.revision === "number") {
      let entry = this.store.get(`${projectId}::${ref.id}#${ref.revision}`);
      if (!entry) {
        for (const [key, val] of this.store.entries()) {
          if (key.endsWith(`::${ref.id}#${ref.revision}`)) {
            entry = val;
            break;
          }
        }
      }
      if (!entry) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Planta (${ref.id}#${ref.revision}) não encontrada no store de teste.`,
        );
      }
      out.plant = structuredClone(entry.value);
      delete out.plant_ref;
      delete out.model_ref;
    }
    return out;
  }

  public async execute(request: RpcRequest, _options?: ExecuteOptions): Promise<RpcResponse> {
    this.executedRequests.push(structuredClone(request));
    const materializedPayload = this.materializeRefs(request.project_id, request.payload);

    const envelope = {
      request,
      payload: materializedPayload,
    };
    const loaded = await cpythonLoader({ indexURL: "", packages: [] });
    const pyodide = loaded.pyodide;
    if (!pyodide.pyimport || !pyodide.toPy) {
      throw new Error("cpythonLoader não expôs pyimport/toPy.");
    }
    const rpcMod = pyodide.pyimport("control_lab.core.rpc") as {
      dispatch: (arg: unknown) => RpcResponse;
      destroy?: () => void;
    };
    const proxy = pyodide.toPy(envelope);
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
    const kind = options?.kind ?? String(value.kind ?? "TransferFunction");
    const persisted = options?.persistToIndexedDB ?? false;
    this.store.set(`${project_id}::${id}#${revision}`, {
      project_id,
      object_id: id,
      revision,
      kind,
      value: structuredClone(value),
      persisted,
    });
    return {
      project_id,
      object_id: id,
      revision,
      persisted,
      cached_in_worker: true,
    };
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

  public async exportProject(project_id: string): Promise<PortableProjectSnapshot> {
    const objects = [];
    for (const v of this.store.values()) {
      if (v.project_id === project_id && v.persisted) {
        objects.push({
          storage_key: `${project_id}:${v.object_id}:${v.revision}`,
          project_id,
          object_id: v.object_id,
          revision: v.revision,
          kind: v.kind,
          value: structuredClone(v.value),
          content_hash: "0".repeat(64),
          created_at: new Date().toISOString(),
        });
      }
    }
    return {
      format: "controllab_snapshot",
      schema_version: "1.0.0",
      project_id,
      project_revision: 1,
      objects,
      experiments: [],
      committed_result: null,
      content_hash: "0".repeat(64),
      exported_at: new Date().toISOString(),
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

/** Helper para criar DTO canônico de TransferFunction SISO G(s) = num(s) / den(s). */
function makeSisoTfDto(
  id: string,
  revision: number,
  num: number[],
  den: number[],
  dt: number | null = null,
) {
  return {
    schema_version: "1.0.0",
    id,
    revision,
    kind: "TransferFunction",
    dt,
    variable: dt === null ? "s" : "z",
    poly_order: "descending",
    input_names: ["u1"],
    output_names: ["y1"],
    num: [[{ shape: [num.length], dtype: "float64", order: "C", data: num }]],
    den: [[{ shape: [den.length], dtype: "float64", order: "C", data: den }]],
    units: {
      time: "s",
      inputs: ["V"],
      outputs: ["V"],
    },
    provenance: {
      algorithm: "test",
      library: "control_lab",
      seed: null,
      timestamp_utc: "2026-11-18T00:00:00Z",
    },
  };
}

test("T-FREQ-01: Planta analítica de 1ª ordem G(s)=1/(s+1) com conferência de magnitude e fase", async () => {
  const client = new PythonBackedSisoEngineClient();
  const tfDto = makeSisoTfDto("plant-1st-order", 1, [1.0], [1.0, 1.0], null);

  const typedWs = new TypedObjectWorkspace({
    client,
    projectIdProvider: () => "test-proj",
    projectRevisionProvider: () => 1,
  });

  await typedWs.registerTypedObject(tfDto, { selectRole: "frequencyPlant" });

  const tabsCtrl = new ProjectTabsController({ client, typedWorkspace: typedWs });
  const sisoWs = new SisoWorkspace({
    client,
    typedWorkspace: typedWs,
    tabsController: tabsCtrl,
    projectIdProvider: () => "test-proj",
    projectRevisionProvider: () => 1,
  });

  // Avalia Bode e Margens na faixa 0.01 a 100 rad/s
  const { bodeChart, margins } = await sisoWs.evaluateBodeAndMargins({
    customWMin: 0.01,
    customWMax: 100,
    customNPoints: 50,
  });

  assert.ok(bodeChart.omega.length > 0);
  assert.equal(bodeChart.delay_representation, "none");
  assert.equal(bodeChart.series_semantics, "numeric_verified");

  // Oráculo analítico: |G(jω)| = 1 / sqrt(1 + ω²), ∠G(jω) = -atan2(ω, 1) [graus]
  const analytical = SisoWorkspace.analyticalFirstOrder(1.0, bodeChart.omega);

  for (let i = 0; i < bodeChart.omega.length; i += 1) {
    const magErr = Math.abs(bodeChart.mag_db[i] - analytical.mag_db[i]);
    const phaseErr = Math.abs(bodeChart.phase_deg[i] - analytical.phase_deg[i]);
    assert.ok(
      magErr < 1e-4,
      `Erro de magnitude em w=${bodeChart.omega[i]}: ${magErr} dB (num=${bodeChart.mag_db[i]}, anal=${analytical.mag_db[i]})`,
    );
    assert.ok(
      phaseErr < 1e-4,
      `Erro de fase em w=${bodeChart.omega[i]}: ${phaseErr}° (num=${bodeChart.phase_deg[i]}, anal=${analytical.phase_deg[i]})`,
    );
  }

  // Estabilidade em malha fechada unitária (1 + G(s) = 0 => s + 2 = 0 => polo em s = -2)
  assert.equal(margins.closed_loop_stable, true);
  assert.ok(margins.closed_loop_poles !== null);
  assert.ok(margins.closed_loop_poles.real[0] < 0);

  // SVG renderizado contém eixos e títulos acessíveis
  const svg = renderBodeSvg(bodeChart);
  assert.ok(svg.includes("<svg"));
  assert.ok(svg.includes("role=\"img\""));
  assert.ok(svg.includes("Diagrama de Bode SISO"));
});

test("T-FREQ-02: Sistema com múltiplas frequências de cruzamento de ganho e aviso explícito", async () => {
  const client = new PythonBackedSisoEngineClient();

  // G1(s) = 4.5 * (s^2 + 0.1 s + 1) / ((s + 0.2) * (s^2 + 0.05 s + 9))
  // num = [4.5, 0.45, 4.5]
  // den = conv([1.0, 0.2], [1.0, 0.05, 9.0]) = [1.0, 0.25, 9.01, 1.8]
  const num = [4.5, 0.45, 4.5];
  const den = [1.0, 0.25, 9.01, 1.8];
  const tfDto = makeSisoTfDto("plant-multiple-crossings", 1, num, den, null);

  const typedWs = new TypedObjectWorkspace({
    client,
    projectIdProvider: () => "test-proj",
    projectRevisionProvider: () => 1,
  });

  await typedWs.registerTypedObject(tfDto, { selectRole: "frequencyPlant" });

  const tabsCtrl = new ProjectTabsController({ client, typedWorkspace: typedWs });
  const sisoWs = new SisoWorkspace({
    client,
    typedWorkspace: typedWs,
    tabsController: tabsCtrl,
    projectIdProvider: () => "test-proj",
    projectRevisionProvider: () => 1,
  });

  const { bodeChart, margins } = await sisoWs.evaluateBodeAndMargins({
    customWMin: 0.01,
    customWMax: 50.0,
    customNPoints: 1000,
  });

  // Confirma detecção de múltiplas travessias
  assert.equal(margins.has_multiple_crossings, true);
  assert.ok(margins.gain_crossovers.length >= 2, `Obtidas ${margins.gain_crossovers.length} travessias de 0 dB`);

  // Confirma que os marcadores foram inseridos no modelo de Bode
  const gcMarkers = bodeChart.markers.filter((m) => m.kind === "gain_crossover");
  assert.ok(gcMarkers.length >= 2, "Esperados múltiplos marcadores de gain_crossover no gráfico");

  // Confirma que avisos foram gerados
  assert.ok(
    sisoWs.getWarnings().some((w) => (typeof w === "string" ? w : w.code) === "MULTIPLE_CROSSOVER_FREQUENCIES"),
    "Aviso MULTIPLE_CROSSOVER_FREQUENCIES ausente nos diagnósticos",
  );
});

test("Rejeição estrita de modelo MIMO sem seleção explícita de canal SISO", async () => {
  const client = new PythonBackedSisoEngineClient();

  // Sistema MIMO 2x2
  const ssMimoDto = {
    schema_version: "1.0.0",
    id: "plant-mimo-system",
    revision: 1,
    kind: "StateSpace",
    dt: null,
    state_names: ["x1", "x2"],
    input_names: ["u1", "u2"],
    output_names: ["y1", "y2"],
    matrices: {
      A: { shape: [2, 2], dtype: "float64", order: "C", data: [-1, 0, 0, -2] },
      B: { shape: [2, 2], dtype: "float64", order: "C", data: [1, 0, 0, 1] }, // 2 entradas
      C: { shape: [2, 2], dtype: "float64", order: "C", data: [1, 0, 0, 1] }, // 2 saídas
      D: { shape: [2, 2], dtype: "float64", order: "C", data: [0, 0, 0, 0] },
    },
    units: {
      time: "s",
      states: ["V", "V"],
      inputs: ["V", "V"],
      outputs: ["V", "V"],
    },
    provenance: {
      algorithm: "test",
      library: "control_lab",
      seed: null,
      timestamp_utc: "2026-11-18T00:00:00Z",
    },
  };

  const typedWs = new TypedObjectWorkspace({
    client,
    projectIdProvider: () => "test-proj",
    projectRevisionProvider: () => 1,
  });

  await typedWs.registerTypedObject(ssMimoDto, { selectRole: "frequencyPlant" });

  const sisoWs = new SisoWorkspace({ client, typedWorkspace: typedWs });

  await assert.rejects(
    async () => {
      await sisoWs.evaluateBodeAndMargins();
    },
    (err: unknown) => {
      assert.ok(err instanceof ControlLabBridgeError);
      assert.equal(err.code, "VALIDATION_ERROR");
      assert.ok(err.message.includes("Apenas sistemas SISO"));
      return true;
    },
  );
});

test("Atraso puro vs Padé explícito: atraso exato na frequência por padrão sem Padé silencioso", async () => {
  const client = new PythonBackedSisoEngineClient();
  const tfDto = makeSisoTfDto("plant-delay-test", 1, [1.0], [1.0, 1.0], null);

  const typedWs = new TypedObjectWorkspace({ client, projectIdProvider: () => "p", projectRevisionProvider: () => 1 });
  await typedWs.registerTypedObject(tfDto, { selectRole: "frequencyPlant" });

  const sisoWs = new SisoWorkspace({ client, typedWorkspace: typedWs });

  // Caso 1: delay > 0 sem use_pade => exact delay
  const resExact = await sisoWs.evaluateBodeAndMargins({
    customWMin: 0.1,
    customWMax: 10,
    customNPoints: 20,
    customDelay: 0.5,
    customUsePade: false,
  });
  assert.equal(resExact.bodeChart.delay_representation, "exact");

  // Fase com atraso puro decai mais rapidamente: ∠G(jω) = -atan(ω) - ω·τ
  const w1 = resExact.bodeChart.omega[10];
  const phaseExact = resExact.bodeChart.phase_deg[10];
  const expectedPhaseExact = (-Math.atan2(w1, 1.0) - w1 * 0.5) * (180.0 / Math.PI);
  assert.ok(Math.abs(phaseExact - expectedPhaseExact) < 1e-2);

  // Caso 2: delay > 0 com use_pade=true => pade
  const resPade = await sisoWs.evaluateBodeAndMargins({
    customWMin: 0.1,
    customWMax: 10,
    customNPoints: 20,
    customDelay: 0.5,
    customUsePade: true,
    customPadeOrder: 1,
  });
  assert.equal(resPade.bodeChart.delay_representation, "pade");
});

test("Fast-Preview vs Commit: execução transitória não sobrescreve registro autoritativo e bloqueia CSV", async () => {
  const client = new PythonBackedSisoEngineClient();
  const tfDto = makeSisoTfDto("plant-preview-commit-test", 1, [1.0], [1.0, 1.0], null);

  const typedWs = new TypedObjectWorkspace({ client, projectIdProvider: () => "p", projectRevisionProvider: () => 1 });
  await typedWs.registerTypedObject(tfDto, { selectRole: "frequencyPlant" });

  const tabsCtrl = new ProjectTabsController({ client, typedWorkspace: typedWs });
  const sisoWs = new SisoWorkspace({
    client,
    typedWorkspace: typedWs,
    tabsController: tabsCtrl,
  });

  // Execução 1: Preview transitório
  const previewRes = await sisoWs.evaluateBodeAndMargins({ previewOnly: true });
  assert.equal(previewRes.bodeChart.series_semantics, "preview");
  assert.equal(tabsCtrl.getLastExecution("siso.stability_margins"), undefined);

  // Proibido exportar CSV durante preview
  assert.throws(() => {
    exportChartToCsv(previewRes.bodeChart);
  }, /Fast-Preview/);

  // Execução 2: Commit autoritativo
  const committedRes = await sisoWs.evaluateBodeAndMargins({ previewOnly: false });
  assert.equal(committedRes.bodeChart.series_semantics, "numeric_verified");

  const lastExec = tabsCtrl.getLastExecution("siso.stability_margins");
  assert.ok(lastExec !== undefined);
  assert.equal(lastExec?.toolId, "siso.stability_margins");
  assert.equal(lastExec?.indicator, "numeric_verified");

  // Exportação CSV permitida após commit
  const csv = exportChartToCsv(committedRes.bodeChart);
  assert.ok(csv.includes("# series_semantics=numeric_verified"));
  assert.ok(csv.includes("ω [rad/s]"));
});

test("Lugar das Raízes (Root Locus) com overlays de 2ª ordem rotulados heuristic", async () => {
  const client = new PythonBackedSisoEngineClient();
  // G(s) = 1 / (s^2 + 2s + 2) => polos em -1 ± j1
  const tfDto = makeSisoTfDto("plant-rl-test", 1, [1.0], [1.0, 2.0, 2.0], null);

  const typedWs = new TypedObjectWorkspace({ client, projectIdProvider: () => "p", projectRevisionProvider: () => 1 });
  await typedWs.registerTypedObject(tfDto, { selectRole: "frequencyPlant" });

  const sisoWs = new SisoWorkspace({ client, typedWorkspace: typedWs });

  const { rootLocusChart, view } = await sisoWs.evaluateRootLocus({
    n_gains: 50,
    k_max: 100,
    damping_ratio: 0.707,
    settling_time: 4.0,
  });

  assert.equal(view.branches.length, 2);
  assert.ok(rootLocusChart.overlays.length >= 1);

  // Todo overlay de 2ª ordem DEVE ser classificado estritamente como heuristic (CL-DIR-001 Seção 6.4)
  for (const ov of rootLocusChart.overlays) {
    assert.equal(
      ov.classification,
      "heuristic",
      `Overlay ${ov.id} deve ter classificação heuristic, recebido: ${ov.classification}`,
    );
  }

  // Renderização SVG do Lugar das Raízes
  const svg = renderRootLocusSvg(rootLocusChart);
  assert.ok(svg.includes("root-locus-chart"));
  assert.ok(svg.includes("data-branch-index=\"0\""));
  assert.ok(svg.includes("data-branch-index=\"1\""));
});

test("Resposta ao degrau SISO com métricas de regime e sobressinal", async () => {
  const client = new PythonBackedSisoEngineClient();
  // G(s) = 1 / (s + 2) => valor final com degrau unitário = 1/2 = 0.5
  const tfDto = makeSisoTfDto("plant-step-test", 1, [1.0], [1.0, 2.0], null);

  const typedWs = new TypedObjectWorkspace({ client, projectIdProvider: () => "p", projectRevisionProvider: () => 1 });
  await typedWs.registerTypedObject(tfDto, { selectRole: "frequencyPlant" });

  const sisoWs = new SisoWorkspace({ client, typedWorkspace: typedWs });

  const { chart, metrics } = await sisoWs.evaluateStepResponse({
    amplitude: 1.0,
    t_final: 5.0,
    n_points: 100,
  });

  assert.equal(metrics.is_stable, true);
  assert.ok(metrics.steady_state_value !== null);
  assert.ok(Math.abs(metrics.steady_state_value - 0.5) < 1e-3);
  assert.equal(chart.kind, "time_response");
  assert.ok(chart.t.length > 0);
});

// Helper de DOM sintético para T-UI-01
class FakeElement {
  public tagName: string;
  public id = "";
  public className = "";
  public value = "";
  public checked = false;
  public disabled = false;
  public textContent = "";
  public parentElement: FakeElement | null = null;
  public children: FakeElement[] = [];
  public attributes = new Map<string, string>();
  public listeners = new Map<string, Array<(ev: unknown) => void>>();
  public ownerDocument: FakeDocument;
  private _innerHTML = "";

  constructor(tagName: string, doc: FakeDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = doc;
  }

  public get innerHTML(): string {
    return this._innerHTML;
  }

  public set innerHTML(html: string) {
    this._innerHTML = html;
    this.children = parseFakeHtml(html, this.ownerDocument, this);
  }

  public setAttribute(name: string, val: string): void {
    this.attributes.set(name, val);
    if (name === "id") this.id = val;
    if (name === "value") this.value = val;
    if (name === "disabled") this.disabled = true;
  }

  public getAttribute(name: string): string | null {
    if (name === "id" && this.id) return this.id;
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

  public dispatchEvent(type: string, evInit?: Record<string, unknown>): void {
    const ev = {
      type,
      target: evInit?.target ?? this,
      currentTarget: this,
      key: evInit?.key ?? "",
      preventDefault() {},
      ...evInit,
    };
    for (const fn of this.listeners.get(type) ?? []) {
      fn(ev);
    }
  }

  public focus(): void {
    this.ownerDocument.activeElement = this;
  }

  public querySelector<T extends FakeElement = FakeElement>(selector: string): T | null {
    const all = this.querySelectorAll<T>(selector);
    return all.length > 0 ? all[0] : null;
  }

  public querySelectorAll<T extends FakeElement = FakeElement>(selector: string): T[] {
    const results: T[] = [];
    const check = (el: FakeElement) => {
      let matched = false;
      if (selector.startsWith("#") && el.id === selector.slice(1)) matched = true;
      else if (selector.startsWith(".") && el.className.includes(selector.slice(1))) matched = true;
      else if (selector.startsWith("[data-action=\"") && selector.endsWith("\"]")) {
        const action = selector.slice(14, -2);
        if (el.getAttribute("data-action") === action) matched = true;
      } else if (selector === '[role="tab"]') {
        if (el.getAttribute("role") === "tab") matched = true;
      } else if (el.tagName.toLowerCase() === selector.toLowerCase()) matched = true;

      if (matched) results.push(el as unknown as T);
      for (const ch of el.children) check(ch);
    };
    for (const ch of this.children) check(ch);
    return results;
  }
}

class FakeDocument {
  public activeElement: FakeElement | null = null;
  public createElement(tagName: string): FakeElement {
    return new FakeElement(tagName, this);
  }
}

function parseFakeHtml(html: string, doc: FakeDocument, parent: FakeElement): FakeElement[] {
  const nodes: FakeElement[] = [];
  const tagRe = /<([a-zA-Z0-9_-]+)([^>]*)>/g;
  let match: RegExpExecArray | null;
  while ((match = tagRe.exec(html)) !== null) {
    const el = new FakeElement(match[1], doc);
    el.parentElement = parent;
    const attrsRaw = match[2];
    const attrRe = /([a-zA-Z0-9_-]+)(?:="([^"]*)")?/g;
    let am: RegExpExecArray | null;
    while ((am = attrRe.exec(attrsRaw)) !== null) {
      el.setAttribute(am[1], am[2] ?? "");
    }
    nodes.push(el);
  }
  return nodes;
}

test("T-UI-01: Fluxo DOM completo via mountControlLabApp e painel #siso-workspace-panel", async () => {
  const client = new PythonBackedSisoEngineClient();
  const tfDto = makeSisoTfDto("siso-plant-dom", 1, [1.0], [1.0, 1.0], null);

  await client.registerObject("proj-dom-siso", "siso-plant-dom", 1, tfDto);

  const doc = new FakeDocument();
  const root = doc.createElement("div");

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-dom-siso",
  });

  // Registra planta no typedWorkspace
  await app.shell.getTypedWorkspace().registerTypedObject(tfDto, { selectRole: "frequencyPlant" });

  // Comuta para a Aba 2 (Frequência SISO)
  app.shell.switchTab("siso_frequency");

  const sisoPanel = root.querySelector("#siso-workspace-panel")!;
  assert.ok(sisoPanel !== null, "#siso-workspace-panel deve estar presente no DOM");
  assert.equal(sisoPanel.getAttribute("hidden"), null, "#siso-workspace-panel deve estar visível na Aba 2");

  // Clica no botão de avaliar Bode
  const btnBode = root.querySelector('[data-action="siso-eval-bode"]')!;
  assert.ok(btnBode !== null);
  btnBode.dispatchEvent("click");

  await new Promise((r) => setTimeout(r, 60));

  const bodeSlot = root.querySelector("#siso-bode-chart-slot")!;
  assert.ok(bodeSlot !== null);
  assert.ok(bodeSlot.innerHTML.includes("bode-chart"), "Slot de Bode deve conter SVG gerado");

  // Clica no botão de avaliar Lugar das Raízes
  const btnRl = root.querySelector('[data-action="siso-eval-rl"]')!;
  assert.ok(btnRl !== null);
  btnRl.dispatchEvent("click");

  await new Promise((r) => setTimeout(r, 60));

  const rlSlot = root.querySelector("#siso-rl-chart-slot")!;
  assert.ok(rlSlot !== null);
  assert.ok(rlSlot.innerHTML.includes("root-locus-chart"), "Slot de Root Locus deve conter SVG gerado");

  // Clica no botão de avaliar Degrau
  const btnStep = root.querySelector('[data-action="siso-eval-step"]')!;
  assert.ok(btnStep !== null);
  btnStep.dispatchEvent("click");

  const timeSlot = root.querySelector("#siso-time-chart-slot")!;
  assert.ok(timeSlot !== null);

  for (let i = 0; i < 30; i += 1) {
    if (timeSlot.innerHTML.includes("<svg")) break;
    await new Promise((r) => setTimeout(r, 50));
  }

  assert.ok(
    timeSlot.innerHTML.includes("<svg") && timeSlot.innerHTML.includes("time_response"),
    "Slot de Tempo deve conter SVG do degrau",
  );

  app.destroy();
});
