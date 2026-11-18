/**
 * Testes unitários normativos de WP-V1-F8-IDENTIFICATION-VERTICAL (F8: f8-ui-charts)
 *
 * Cobrem:
 * - T-ID-01: Importação de Dataset (JSON/CSV), particionamento disjunto em treino e holdout,
 *   estimação ARX (`identification.fit_arx`) e por subespaços (`identification.fit_subspace`,
 *   MOESP/N4SID) via `ControlLabEngineClient` com extração de parâmetros, polos e métricas.
 * - T-ID-02: Detecção e apresentação visível de regressão rank-deficient / falta de persistência
 *   de excitação (`PERSISTENCE_OF_EXCITATION_INSUFFICIENT`, `RANK_DEFICIENT_REGRESSION`) com
 *   posto numérico, número de condição $\kappa(\Phi)$ e `rank_deficient=true`.
 * - T-ID-03: Separação explícita entre previsão de 1 passo (`one_step_prediction`) e simulação
 *   livre (`free_simulation`) para treino e conjunto de validação (`holdout`) em
 *   `identification.fit_arx`, `identification.fit_subspace` e `identification.validate_model`.
 * - Gráficos científicos SVG + tabelas acessíveis WCAG 2.2 AA + exportação CSV para comparação
 *   temporal (y medido, ŷ 1-passo, ŷ simulação livre, resíduos) e diagnóstico de correlação de
 *   resíduos ($R_{\varepsilon\varepsilon}(\tau)$ e $R_{u\varepsilon}(\tau)$ com bandas 95% e 99%).
 * - T-ID-04 / R-06: Fluxo explícito de reutilização do modelo identificado:
 *   registro explícito do `IdentifiedModel` -> derivação via `core.reuse_model` (`StateSpace` ou
 *   `native`) -> registro explícito do modelo derivado -> consumo direto na Aba 3 (LQR) e na
 *   Aba 2 (Frequência SISO) preservando `dt` e proveniência.
 * - Integração ponta a ponta com o motor científico real em Python (`control_lab.core.rpc.dispatch`)
 *   via `PyodideWorkerRuntime` quando Python 3 está disponível no ambiente.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  ControlLabBridgeError,
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
import { ControlLabShell } from "../../../web/app/shell.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import {
  buildAccessibleChartTable,
  exportChartToCsv,
  renderAccessibleTableHtml,
  renderResidualCorrelationSvg,
  renderTimeResponseSvg,
} from "../../../web/charts/scientific_chart.ts";
import {
  buildBenchmarkArxDatasetDto,
  parseCsvToDatasetDto,
  splitDatasetDtoTrainHoldout,
} from "../../../web/features/identification_workspace.ts";
import { cpythonLoader } from "../f7/cpython_runtime.mjs";

/**
 * Cliente que despacha requisições RPC diretamente ao motor Python real
 * (`control_lab.core.rpc.dispatch`) via `cpythonLoader`,
 * mantendo o store de objetos por `(project_id, object_id, revision)` e
 * materializando referências exatamente como o Worker F7 (`payload_references.ts`).
 */
class PythonBackedIdentificationEngineClient implements ControlLabEngineClient {
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
  private readonly useRealPython: boolean;

  constructor(options?: { useRealPython?: boolean }) {
    this.useRealPython = options?.useRealPython ?? true;
  }

  public async init(): Promise<CapabilityDescriptor> {
    this.state = "ready";
    return this.getCapabilities();
  }

  public getLifecycleState(): EngineLifecycleState {
    return this.state;
  }

  public getCapabilities(): CapabilityDescriptor {
    return {
      api_version: "1.0",
      engine_kind: "pyodide",
      runtime_id: "test-f8-identification-python-engine",
      operations: [
        "worker.ping",
        "core.capabilities",
        "core.reuse_model",
        "identification.fit_arx",
        "identification.fit_subspace",
        "identification.validate_model",
        "frequency.eval_response",
        "statespace.design_lqr",
        "statespace.analyze",
        "statespace.simulate_lti",
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
        "statespace.design_lqr": "beta",
        "statespace.analyze": "beta",
        "statespace.simulate_lti": "beta",
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
        const entry = this.store.get(`${projectId}::${ref.id}#${ref.revision}`);
        if (!entry) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Referência ${refField} (${ref.id}#${ref.revision}) não encontrada no store.`,
          );
        }
        out[targetField] = structuredClone(entry.value);
        delete out[refField];
      }
    };

    if (
      operation === "identification.fit_arx" ||
      operation === "identification.fit_subspace"
    ) {
      lookup("dataset_ref", "dataset");
      lookup("val_dataset_ref", "val_dataset");
    } else if (operation === "identification.validate_model") {
      lookup("model_ref", "model");
      lookup("val_dataset_ref", "val_dataset");
      lookup("train_dataset_ref", "train_dataset");
    } else if (operation === "core.reuse_model") {
      lookup("model_ref", "model");
    } else if (
      operation.startsWith("frequency.") ||
      operation.startsWith("statespace.")
    ) {
      lookup("plant_ref", "plant");
      lookup("model_ref", "plant");
    }
    return out;
  }

  public async execute(
    request: RpcRequest,
    _options?: ExecuteOptions,
  ): Promise<RpcResponse> {
    this.executedRequests.push(structuredClone(request));
    const materializedPayload = this.materializeRefs(
      request.project_id,
      request.operation,
      request.payload,
    );

    if (this.useRealPython) {
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

    throw new Error("Modo sem Python não configurado neste cliente.");
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
        updated_at: "2026-11-18T00:00:00Z",
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
        created_at: "2026-11-18T00:00:00Z",
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
          created_at: "2026-11-18T00:00:00Z",
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
      exported_at: "2026-11-18T00:00:00Z",
    };
  }

  public subscribe(listener: EngineEventListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  public emit(ev: EngineClientEvent): void {
    for (const fn of this.listeners) fn(ev);
  }

  public dispose(): void {
    this.listeners.clear();
  }
}

test("WP-V1-F8-IDENTIFICATION-VERTICAL: importação CSV, validação e particionamento disjunto treino/holdout", () => {
  const csvContent = [
    "# Comentário ignorado",
    "t,u1,y1",
    "0.00,1.0,0.00",
    "0.05,-1.0,0.40",
    "0.10,1.0,0.20",
    "0.15,1.0,0.32",
    "0.20,-1.0,0.74",
    "0.25,1.0,0.49",
    "0.30,-1.0,0.62",
    "0.35,1.0,0.19",
    "0.40,1.0,0.25",
    "0.45,-1.0,0.64",
  ].join("\n");

  const parsedDto = parseCsvToDatasetDto(csvContent, {
    id: "ds-csv-01",
    revision: 2,
  });
  assert.equal(parsedDto.kind, "Dataset");
  assert.equal(parsedDto.id, "ds-csv-01");
  assert.equal(parsedDto.revision, 2);
  assert.equal(parsedDto.dt, 0.05);

  const split = splitDatasetDtoTrainHoldout(parsedDto, {
    trainFraction: 0.6,
  });
  assert.equal(split.trainSamples, 6);
  assert.equal(split.valSamples, 4);
  assert.equal(split.trainDto.id, "ds-csv-01-train");
  assert.equal(split.valDto.id, "ds-csv-01-val");
  assert.equal(split.trainDto.dt, 0.05);
  assert.equal(split.valDto.dt, 0.05);

  // Rejeita CSV com tempo não estritamente crescente
  assert.throws(
    () =>
      parseCsvToDatasetDto("t,u,y\n0.0,1,0\n0.0,-1,0.2", {
        id: "ds-bad-t",
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );

  // Rejeita particionamento se trainId === valId (prevenção de contaminação T-ID-03)
  assert.throws(
    () =>
      splitDatasetDtoTrainHoldout(parsedDto, {
        trainId: "same-id",
        valId: "same-id",
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );
});

test("WP-V1-F8-IDENTIFICATION-VERTICAL: T-ID-01, T-ID-02, T-ID-03 e T-ID-04 ponta a ponta com motor científico Python real", async () => {
  const client = new PythonBackedIdentificationEngineClient({
    useRealPython: true,
  });
  const shell = new ControlLabShell({
    client,
    project_id: "proj-f8-id-vertical",
    initialTab: "identification",
  });
  const idWorkspace = shell.getIdentificationWorkspace();
  const typedWorkspace = shell.getTypedWorkspace();
  const tabs = shell.getTabsController();

  // -------------------------------------------------------------------------
  // 1. T-ID-01 + T-ID-03: Benchmark PRBS com particionamento Treino/Holdout
  //    e estimação ARX(2, 2, 1) no motor Python real
  // -------------------------------------------------------------------------
  const loaded = await idWorkspace.loadBenchmarkDataset({
    preset: "prbs",
    nSamples: 160,
    dt: 0.05,
    trainFraction: 0.7,
    splitTrainHoldout: true,
  });
  assert.ok(loaded.split);
  assert.equal(loaded.split.trainSamples, 112);
  assert.equal(loaded.split.valSamples, 48);
  assert.deepEqual(typedWorkspace.getSelectedRef("dataset"), {
    id: "ds-b-arx-prbs-train",
    revision: 1,
  });
  assert.deepEqual(typedWorkspace.getSelectedRef("valDataset"), {
    id: "ds-b-arx-prbs-val",
    revision: 1,
  });

  const arxReport = await idWorkspace.fitArx({
    na: 2,
    nb: 2,
    nk: 1,
    detrend: "none",
  });

  assert.equal(arxReport.status, "success");
  assert.equal(arxReport.inner_model_kind, "TransferFunction");
  assert.equal(arxReport.dt, 0.05);
  assert.equal(arxReport.is_stable, true);
  assert.equal(arxReport.excitation.rank_deficient, false);
  assert.equal(arxReport.excitation.pe_satisfied, true);
  assert.equal(arxReport.excitation.rank, 4);
  assert.equal(arxReport.excitation.expected_rank, 4);

  // T-ID-01: Recupera coeficientes exatos a = [-1.5, 0.7], b = [0.4, 0.2]
  const aCoeffs = arxReport.parameters_summary.a as number[];
  const bCoeffs = arxReport.parameters_summary.b as number[];
  assert.ok(Array.isArray(aCoeffs) && aCoeffs.length === 2);
  assert.ok(Array.isArray(bCoeffs) && bCoeffs.length === 2);
  assert.ok(Math.abs(aCoeffs[0] - -1.5) < 1e-8);
  assert.ok(Math.abs(aCoeffs[1] - 0.7) < 1e-8);
  assert.ok(Math.abs(bCoeffs[0] - 0.4) < 1e-8);
  assert.ok(Math.abs(bCoeffs[1] - 0.2) < 1e-8);

  // T-ID-03: Distinção explícita entre one_step_prediction e free_simulation em treino e holdout
  assert.ok(arxReport.train_metrics);
  assert.equal(
    arxReport.train_metrics.one_step_prediction.evaluation_mode,
    "one_step_prediction",
  );
  assert.equal(
    arxReport.train_metrics.free_simulation.evaluation_mode,
    "free_simulation",
  );
  assert.ok(
    (arxReport.train_metrics.one_step_prediction.fit_percent ?? 0) > 99.9,
  );
  assert.ok(
    (arxReport.train_metrics.free_simulation.fit_percent ?? 0) > 99.9,
  );

  assert.ok(arxReport.validation_metrics);
  assert.equal(
    arxReport.validation_metrics.one_step_prediction.evaluation_mode,
    "one_step_prediction",
  );
  assert.equal(
    arxReport.validation_metrics.free_simulation.evaluation_mode,
    "free_simulation",
  );
  assert.ok(
    (arxReport.validation_metrics.one_step_prediction.fit_percent ?? 0) > 99.9,
  );
  assert.ok(
    (arxReport.validation_metrics.free_simulation.fit_percent ?? 0) > 99.9,
  );

  // Gráficos científicos de resposta comparativa e de correlação de resíduos + tabelas WCAG 2.2 AA
  const respChart = idWorkspace.buildResponseChart("validation");
  assert.ok(respChart);
  assert.equal(respChart.kind, "time_response");
  assert.ok(respChart.channels.length >= 3);
  const respSvg = renderTimeResponseSvg(respChart);
  assert.match(respSvg, /y Medido \(Holdout\)/);
  assert.match(respSvg, /ŷ Previsão 1-Passo \(Holdout\)/);
  assert.match(respSvg, /ŷ Simulação Livre \(Holdout\)/);
  const respTable = buildAccessibleChartTable(respChart, 4);
  assert.equal(respTable.rows.length, 48);
  const respTableHtml = renderAccessibleTableHtml(respTable);
  assert.match(respTableHtml, /<table class="accessible-data-table"/);
  const respCsv = exportChartToCsv(respChart);
  assert.match(respCsv, /# chart_id=id-response-validation/);

  const residChart = idWorkspace.buildResidualCorrelationChart("validation");
  assert.ok(residChart);
  assert.equal(residChart.kind, "residual_correlation");
  assert.ok(residChart.bound_95 > 0);
  assert.ok(residChart.bound_99 > residChart.bound_95);
  const residSvg = renderResidualCorrelationSvg(residChart);
  assert.match(residSvg, /data-chart-kind="residual_correlation"/);
  assert.match(residSvg, /data-bound="95-upper"/);
  assert.match(residSvg, /data-bound="99-upper"/);
  const residTable = buildAccessibleChartTable(residChart, 4);
  assert.ok(residTable.rows.length > 0);
  const residCsv = exportChartToCsv(residChart);
  assert.match(residCsv, /# chart_id=id-residuals-corr-validation/);

  const pzChart = idWorkspace.buildIdentifiedPoleZeroChart();
  assert.ok(pzChart);
  assert.equal(pzChart.dt, 0.05);
  assert.equal(pzChart.open_loop_poles?.real.length, 2);

  // -------------------------------------------------------------------------
  // 2. Validação cruzada explícita via identification.validate_model
  // -------------------------------------------------------------------------
  const valReport = await idWorkspace.validateModel({
    autoRegisterPendingIfNeeded: true,
  });
  assert.equal(valReport.operation, "identification.validate_model");
  assert.ok(valReport.validation_metrics);
  assert.ok(
    (valReport.validation_metrics.free_simulation.fit_percent ?? 0) > 99.9,
  );
  assert.ok(valReport.validation_residuals);

  // -------------------------------------------------------------------------
  // 3. T-ID-04 / R-06: Reutilização canônica do modelo ARX identificado
  //    na Aba 2 (Frequência SISO) e na Aba 3 (Espaço de Estados / LQR)
  // -------------------------------------------------------------------------
  const reuseSiso = await idWorkspace.reuseIdentifiedModel({
    targetKind: "native",
    registerIdentifiedIfPending: true,
    registerDerived: true,
    applyToDestination: "siso_frequency",
  });
  assert.ok(reuseSiso.derivedObject);
  assert.equal(reuseSiso.derivedObject.kind, "TransferFunction");
  assert.equal(reuseSiso.reuseOutcome.dt, 0.05);
  assert.equal(shell.getActiveTab(), "siso_frequency");

  // Executa frequency.eval_response (siso.bode_nyquist) com a TransferFunction derivada do ARX
  const sisoExec = await tabs.executeTool("siso.bode_nyquist", {
    project_id: "proj-f8-id-vertical",
    project_revision: 1,
  });
  assert.ok(
    sisoExec.response.status === "success" ||
      sisoExec.response.status === "warning",
  );
  assert.ok(sisoExec.response.result?.mag_db);
  assert.equal(sisoExec.response.result?.dt, 0.05);

  // Agora deriva como StateSpace discreto e aplica diretamente ao workspace LQR (Aba 3)
  const reuseLqr = await idWorkspace.reuseIdentifiedModel({
    targetKind: "StateSpace",
    registerIdentifiedIfPending: true,
    registerDerived: true,
    applyToDestination: "lqr",
  });
  assert.ok(reuseLqr.derivedObject);
  assert.equal(reuseLqr.derivedObject.kind, "StateSpace");
  assert.equal(reuseLqr.reuseOutcome.dt, 0.05);
  assert.equal(shell.getActiveTab(), "statespace");

  // Verifica que o workspace LQR adotou a planta discreta derivada (dt=0.05, n=2) sem cópia manual
  const activeLqrPlant = shell.getLqrWorkspace().getPlant();
  assert.equal(activeLqrPlant.id, reuseLqr.derivedObject.id);
  assert.equal(activeLqrPlant.dt, 0.05);
  assert.deepEqual(activeLqrPlant.matrices.A.shape, [2, 2]);

  // -------------------------------------------------------------------------
  // 4. Identificação por Subespaços (MOESP) via identification.fit_subspace
  // -------------------------------------------------------------------------
  shell.switchTab("identification");
  const subReport = await idWorkspace.fitSubspace({
    method: "moesp",
    order: 2,
    horizon: 8,
    estimate_feedthrough: false,
  });
  assert.equal(subReport.operation, "identification.fit_subspace");
  assert.equal(subReport.inner_model_kind, "StateSpace");
  assert.equal(subReport.is_stable, true);
  assert.ok(subReport.excitation.hankel_singular_values.length >= 2);
  assert.ok(
    (subReport.validation_metrics?.free_simulation.fit_percent ?? 0) > 95.0,
  );

  // -------------------------------------------------------------------------
  // 5. T-ID-02: Dataset com entrada constante (sem persistência de excitação)
  //    sinaliza rank_deficient=true e warnings estruturados
  // -------------------------------------------------------------------------
  await idWorkspace.loadBenchmarkDataset({
    preset: "constant_input",
    nSamples: 80,
    dt: 0.05,
    splitTrainHoldout: false,
  });
  // Limpa valDataset para ajustar apenas no dataset de entrada constante
  typedWorkspace.selectRef("valDataset", null);

  const peReport = await idWorkspace.fitArx({
    na: 2,
    nb: 2,
    nk: 1,
  });
  assert.equal(peReport.status, "warning");
  assert.equal(peReport.excitation.rank_deficient, true);
  assert.equal(peReport.excitation.pe_satisfied, false);
  const warningCodes = peReport.warnings.map((w) =>
    typeof w === "string" ? w : w.code,
  );
  assert.ok(
    warningCodes.includes("PERSISTENCE_OF_EXCITATION_INSUFFICIENT") ||
      warningCodes.includes("RANK_DEFICIENT_REGRESSION"),
  );
});

test("WP-V1-F8-IDENTIFICATION-VERTICAL: DOM mountControlLabApp renderiza painel vertical da Aba 1, gráficos, avisos T-ID-02 e fluxo de reutilização", async () => {
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
        preventDefault() {
          (this as Record<string, unknown>).defaultPrevented = true;
        },
        ...evInit,
      };
      for (const fn of this.listeners.get(type) ?? []) {
        fn(ev);
      }
      if (this.parentElement && evInit?.bubbles !== false) {
        this.parentElement.dispatchEvent(type, { ...ev, target: ev.target });
      }
    }

    public focus(): void {
      this.ownerDocument.activeElement = this;
    }

    public closest(selector: string): FakeElement | null {
      let cur: FakeElement | null = this;
      while (cur) {
        if (matchesSelector(cur, selector)) return cur;
        cur = cur.parentElement;
      }
      return null;
    }

    public querySelector<T = FakeElement>(selector: string): T | null {
      return (this.querySelectorAll(selector)[0] as unknown as T) ?? null;
    }

    public querySelectorAll<T = FakeElement>(selector: string): T[] {
      const out: FakeElement[] = [];
      const visit = (node: FakeElement) => {
        for (const child of node.children) {
          if (matchesSelector(child, selector)) out.push(child);
          visit(child);
        }
      };
      visit(this);
      return out as unknown as T[];
    }
  }

  class FakeDocument {
    public activeElement: FakeElement | null = null;
    public body = new FakeElement("body", this);
    public createElement(tag: string): FakeElement {
      return new FakeElement(tag, this);
    }
  }

  function matchesSelector(el: FakeElement, selector: string): boolean {
    if (selector.startsWith("#")) {
      return el.id === selector.slice(1);
    }
    const attrMatches = Array.from(
      selector.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g),
    );
    if (attrMatches.length > 0) {
      return attrMatches.every((m) => {
        const attrName = m[1];
        const attrVal = m[2];
        const actual = el.getAttribute(attrName);
        return attrVal === undefined ? actual !== null : actual === attrVal;
      });
    }
    return false;
  }

  function parseFakeHtml(
    html: string,
    doc: FakeDocument,
    parent: FakeElement,
  ): FakeElement[] {
    const nodes: FakeElement[] = [];
    const tagRe =
      /<(button|input|select|textarea|section|div|span|pre|h2|h3|article|details|ul|li|table)\b([^>]*)>/gi;
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

  const client = new PythonBackedIdentificationEngineClient({
    useRealPython: true,
  });
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-dom-id-vertical",
  });

  // Muda para a Aba 1 (Identificação)
  app.shell.switchTab("identification");
  const idPanel = root.querySelector("#identification-workspace-panel")!;
  assert.equal(idPanel.getAttribute("hidden"), null);

  // Clica em "Benchmark PRBS (Treino + Holdout)"
  const btnLoadPrbs = root.querySelector('[data-action="id-load-prbs"]')!;
  btnLoadPrbs.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 30));

  assert.deepEqual(
    app.shell.getTypedWorkspace().getSelectedRef("dataset"),
    { id: "ds-b-arx-prbs-train", revision: 1 },
  );
  assert.deepEqual(
    app.shell.getTypedWorkspace().getSelectedRef("valDataset"),
    { id: "ds-b-arx-prbs-val", revision: 1 },
  );

  // Dispara a ferramenta declarativa identification.fit_arx pelo botão da card na UI
  const toolsSlot = root.querySelector("#controllab-tools-slot")!;
  const execArxBtn = root.querySelector(
    '[data-action="execute-tool"][data-tool-id="identification.fit_arx"]',
  )!;
  toolsSlot.dispatchEvent("click", { target: execArxBtn });
  await new Promise((r) => setTimeout(r, 80));

  // Verifica que o painel de diagnósticos de identificação e os gráficos SVG foram renderizados
  const diagSlot = root.querySelector("#id-diagnostics-panel")!;
  assert.match(diagSlot.innerHTML, /Previsão 1-Passo FIT/);
  assert.match(diagSlot.innerHTML, /Simulação Livre FIT/);
  assert.match(diagSlot.innerHTML, /Validação \/ Holdout/);

  const respChartSlot = root.querySelector("#id-response-chart-slot")!;
  assert.match(respChartSlot.innerHTML, /<svg/);
  assert.match(respChartSlot.innerHTML, /y Medido \(Holdout\)/);

  const residChartSlot = root.querySelector("#id-residuals-chart-slot")!;
  assert.match(residChartSlot.innerHTML, /<svg/);
  assert.match(residChartSlot.innerHTML, /data-chart-kind="residual_correlation"/);

  // Clica em "Derivar StateSpace + Registrar + Aplicar ao LQR (Aba 3)"
  const btnReuseToLqr = root.querySelector('[data-action="id-reuse-to-lqr"]')!;
  btnReuseToLqr.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 80));

  assert.equal(app.shell.getActiveTab(), "statespace");
  assert.equal(app.shell.getLqrWorkspace().getPlant().dt, 0.05);

  // Verifica buildBenchmarkArxDatasetDto diretamente
  const benchConst = buildBenchmarkArxDatasetDto({
    constantInput: true,
    nSamples: 16,
  });
  assert.equal(benchConst.kind, "Dataset");

  app.destroy();
});
