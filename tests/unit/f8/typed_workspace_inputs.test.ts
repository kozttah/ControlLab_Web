/**
 * Testes unitários normativos de WP-V1-F8-TYPED-WORKSPACE-INPUTS (F8: f8-ui-charts)
 *
 * Cobrem:
 * - T-CORE-01 / T-RPC-01: Seleção explícita de objetos tipados na sessão e composição de
 *   payload por ferramenta (substituindo injeção indiscriminada do StateSpace LQR).
 * - Validação estrutural e dimensional de Dataset, TransferFunction, StateSpace,
 *   IdentifiedModel, FuzzySystem e TSStateSpace (ts_measured, polytopic_uncertain,
 *   ts_partially_observed); rejeição do discriminante inválido "TSStateSpace".
 * - Impedimento de execução sem insumos compatíveis, erros visíveis e tipados para
 *   ausência ou dimensão/tipo incompatível.
 * - Seleção por teclado (ArrowDown/ArrowUp/Home/End) e pelo DOM (<select>).
 * - Proteção contra sobrescrita por revisão antiga (síncrona ou assíncrona fora de ordem).
 * - Fluxo core.reuse_model sem registro automático: exige registro explícito de
 *   IdentifiedModel e de derivados antes de consumo em frequency.*, statespace.* ou LQR.
 * - Preservação da limpeza de campos numéricos opcionais em branco (sem NaN) e
 *   indisponibilidade honesta de cards não implementadas no runtime.
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
import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { ControlLabShell } from "../../../web/app/shell.ts";
import { mountControlLabApp } from "../../../web/app/main.ts";
import { ProjectTabsController } from "../../../web/features/project_tabs.ts";
import {
  TypedObjectWorkspace,
  decodeObjectRefKey,
  encodeObjectRefKey,
  validateTypedCanonicalDto,
} from "../../../web/features/typed_workspace.ts";
import { createDoubleIntegratorPlant } from "../../../web/features/lqr_workspace.ts";

function buildValidDatasetDto(overrides?: Partial<Record<string, unknown>>): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    kind: "Dataset",
    id: "ds-prbs-01",
    revision: 1,
    dt: 0.05,
    t: {
      dtype: "float64",
      order: "C",
      shape: [4],
      data: [0.0, 0.05, 0.1, 0.15],
    },
    u: {
      dtype: "float64",
      order: "C",
      shape: [4, 1],
      data: [1.0, -1.0, 1.0, 1.0],
    },
    y: {
      dtype: "float64",
      order: "C",
      shape: [4, 1],
      data: [0.0, 0.2, 0.1, 0.25],
    },
    input_names: ["u1"],
    output_names: ["y1"],
    units: { time: "s", inputs: ["V"], outputs: ["rad"] },
    provenance: {
      algorithm: "dataset.synthetic",
      library: "control_lab",
      seed: 42,
      timestamp_utc: "2026-11-18T00:00:00Z",
    },
    ...overrides,
  };
}

function buildValidTransferFunctionDto(overrides?: Partial<Record<string, unknown>>): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    kind: "TransferFunction",
    id: "tf-siso-01",
    revision: 2,
    variable: "s",
    poly_order: "descending",
    dt: null,
    num: [
      [
        {
          dtype: "float64",
          order: "C",
          shape: [1],
          data: [2.0],
        },
      ],
    ],
    den: [
      [
        {
          dtype: "float64",
          order: "C",
          shape: [2],
          data: [1.0, 3.0],
        },
      ],
    ],
    input_names: ["u1"],
    output_names: ["y1"],
    units: { time: "s", inputs: ["V"], outputs: ["V"] },
    provenance: {
      algorithm: "tf.test",
      library: "control_lab",
      seed: null,
      timestamp_utc: "2026-11-18T00:00:00Z",
    },
    ...overrides,
  };
}

function buildValidFuzzySystemDto(overrides?: Partial<Record<string, unknown>>): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    kind: "FuzzySystem",
    id: "fuzzy-mamdani-01",
    revision: 1,
    inference_type: "mamdani",
    input_variables: [
      {
        name: "erro",
        universe: [-1.0, 1.0],
        terms: [{ name: "zero", mf_type: "triangular", params: [-0.5, 0.0, 0.5] }],
      },
    ],
    output_variables: [
      {
        name: "u",
        universe: [-5.0, 5.0],
        terms: [{ name: "neutro", mf_type: "triangular", params: [-1.0, 0.0, 1.0] }],
      },
    ],
    rules: [
      {
        antecedents: { erro: "zero" },
        consequents: { u: "neutro" },
        weight: 1.0,
        connector: "and",
      },
    ],
    provenance: {
      algorithm: "fuzzy.fml",
      library: "control_lab",
      seed: null,
      timestamp_utc: "2026-11-18T00:00:00Z",
    },
    ...overrides,
  };
}

function buildValidTsModelDto(
  kind: "ts_measured" | "polytopic_uncertain" | "ts_partially_observed" = "ts_measured",
  overrides?: Partial<Record<string, unknown>>,
): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    kind,
    id: `ts-${kind}-01`,
    revision: 1,
    dt: null,
    state_names: ["x1", "x2"],
    input_names: ["u1"],
    output_names: ["y1"],
    units: { time: "s", states: ["m", "m/s"], inputs: ["N"], outputs: ["m"] },
    membership_spec: { type: "simplex", n_rules: 2 },
    premise_availability: { mode: kind },
    domain: { bounds: { x1: [-1, 1] } },
    vertices: [
      {
        vertex_id: "v1",
        A: { dtype: "float64", order: "C", shape: [2, 2], data: [0, 1, -1, -2] },
        B: { dtype: "float64", order: "C", shape: [2, 1], data: [0, 1] },
        C: { dtype: "float64", order: "C", shape: [1, 2], data: [1, 0] },
        D: { dtype: "float64", order: "C", shape: [1, 1], data: [0] },
      },
      {
        vertex_id: "v2",
        A: { dtype: "float64", order: "C", shape: [2, 2], data: [0, 1, -2, -3] },
        B: { dtype: "float64", order: "C", shape: [2, 1], data: [0, 1] },
        C: { dtype: "float64", order: "C", shape: [1, 2], data: [1, 0] },
        D: { dtype: "float64", order: "C", shape: [1, 1], data: [0] },
      },
    ],
    provenance: {
      algorithm: "ts.sector_nonlinearity",
      library: "control_lab",
      seed: null,
      timestamp_utc: "2026-11-18T00:00:00Z",
    },
    ...overrides,
  };
}

function buildValidIdentifiedModelDto(overrides?: Partial<Record<string, unknown>>): Record<string, unknown> {
  const innerTf = buildValidTransferFunctionDto({
    id: "tf-arx-inner",
    revision: 1,
    variable: "z^-1",
    dt: 0.05,
  });
  return {
    schema_version: "1.0.0",
    kind: "IdentifiedModel",
    id: "id-arx-01",
    revision: 1,
    algorithm: "ARX",
    model: innerTf,
    provenance: {
      algorithm: "identification.fit_arx",
      library: "control_lab",
      seed: 42,
      timestamp_utc: "2026-11-18T00:00:00Z",
    },
    ...overrides,
  };
}

class RecordingTypedEngineClient implements ControlLabEngineClient {
  public readonly executedRequests: RpcRequest[] = [];
  public readonly registeredObjects: Array<{
    project_id: string;
    id: string;
    revision: number;
    kind: string;
    value: Record<string, unknown>;
    persisted: boolean;
  }> = [];

  private readonly store = new Map<string, {
    ref: RegisteredObjectRef;
    kind: string;
    value: Record<string, unknown>;
  }>();
  private readonly listeners = new Set<EngineEventListener>();
  private state: EngineLifecycleState = "ready";
  private readonly baseCapabilities: CapabilityDescriptor;
  public registerDelayMsByKey = new Map<string, number>();
  public customHandler?: (req: RpcRequest) => RpcResponse | null;

  constructor(operations?: string[]) {
    this.baseCapabilities = {
      api_version: "1.0",
      engine_kind: "pyodide",
      runtime_id: "test-typed-pyodide",
      operations: operations ?? [
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
        "mimo.singular_values",
        "fuzzy.evaluate",
        "optimization.solve",
        "optimization.verify",
      ],
      backends: {
        numpy_scipy: { available: true, maturity: "beta" },
        native_primal_dual: { available: true, maturity: "beta" },
      },
      maturity: {
        "identification.fit_arx": "beta",
        "identification.fit_subspace": "beta",
        "identification.validate_model": "beta",
        "frequency.eval_response": "beta",
        "statespace.design_lqr": "beta",
        "statespace.analyze": "beta",
        "statespace.simulate_lti": "beta",
        "mimo.singular_values": "beta",
        "fuzzy.evaluate": "beta",
        "optimization.solve": "beta",
        "optimization.verify": "beta",
      },
      supports_transferables: true,
      supports_cooperative_cancel: true,
      max_memory_bytes: 256 * 1024 * 1024,
      lib_versions: {
        python: "3.12.1",
        numpy: "2.0.0",
        scipy: "1.14.0",
        control_lab: "1.0.0",
      },
      offline_ready: false,
    };
  }

  public async init(): Promise<CapabilityDescriptor> {
    this.state = "ready";
    return this.baseCapabilities;
  }

  public getLifecycleState(): EngineLifecycleState {
    return this.state;
  }

  public getCapabilities(): CapabilityDescriptor {
    return this.baseCapabilities;
  }

  public getMetrics(): ExecutionMetrics {
    return createInitialExecutionMetrics();
  }

  public getCommittedRevision(): number {
    return 1;
  }

  public async syncAdoptedProjectState(): Promise<void> {}

  public async execute(
    request: RpcRequest,
    _options?: ExecuteOptions,
  ): Promise<RpcResponse> {
    this.executedRequests.push(structuredClone(request));
    if (this.customHandler) {
      const custom = this.customHandler(request);
      if (custom) return custom;
    }

    if (request.operation === "identification.fit_arx") {
      const idModel = buildValidIdentifiedModelDto({
        id: "id-arx-result",
        revision: 3,
      });
      return {
        api_version: "1.0",
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: request.project_revision,
        status: "success",
        result: {
          identified_model: idModel,
          metrics: { train: { free_simulation: { fit_percent: 96.4 } } },
        },
        assumptions: {},
        diagnostics: {},
        provenance: {
          algorithm: "identification.fit_arx",
          lib_versions: this.baseCapabilities.lib_versions,
          seed: 42,
          timestamp_utc: "2026-11-18T00:00:00Z",
        },
        warnings: [],
        error: null,
      };
    }

    if (request.operation === "core.reuse_model") {
      const targetKind = request.payload.target_kind;
      const derived =
        targetKind === "StateSpace"
          ? {
              ...createDoubleIntegratorPlant(),
              id: "ss-derived-from-arx",
              revision: 1,
              dt: 0.05,
            }
          : buildValidTransferFunctionDto({
              id: "tf-derived-from-arx",
              revision: 1,
              variable: "z^-1",
              dt: 0.05,
            });
      return {
        api_version: "1.0",
        request_id: request.request_id,
        project_id: request.project_id,
        project_revision: request.project_revision,
        status: "success",
        result: {
          schema_version: "1.0.0",
          model: derived,
          model_ref: { id: derived.id, revision: derived.revision },
          source_ref: request.payload.model_ref,
          source_model_ref: { id: "tf-arx-inner", revision: 1 },
          dt: 0.05,
          dimensions: { n_inputs: 1, n_outputs: 1, n_states: 2 },
          derivation: {
            registration_required: true,
            converted_representation: targetKind === "StateSpace",
          },
        },
        assumptions: {},
        diagnostics: {},
        provenance: {
          algorithm: "core.reuse_model",
          lib_versions: this.baseCapabilities.lib_versions,
          seed: null,
          timestamp_utc: "2026-11-18T00:00:00Z",
        },
        warnings: [],
        error: null,
      };
    }

    return {
      api_version: "1.0",
      request_id: request.request_id,
      project_id: request.project_id,
      project_revision: request.project_revision,
      status: "success",
      result: { echoed_payload: structuredClone(request.payload) },
      assumptions: {},
      diagnostics: {},
      provenance: {
        algorithm: request.operation,
        lib_versions: this.baseCapabilities.lib_versions,
        seed: null,
        timestamp_utc: "2026-11-18T00:00:00Z",
      },
      warnings: [],
      error: null,
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
    value: Record<string, unknown>,
    options?: RegisterObjectOptions,
  ): Promise<RegisteredObjectRef> {
    const k = `${project_id}::${id}#${revision}`;
    const delay = this.registerDelayMsByKey.get(`${id}#${revision}`) ?? 0;
    if (delay > 0) {
      await new Promise((r) => setTimeout(r, delay));
    }
    const kind = options?.kind ?? String(value.kind ?? "unknown");
    const ref: RegisteredObjectRef = {
      project_id,
      object_id: id,
      revision,
      persisted: options?.persistToIndexedDB ?? false,
      cached_in_worker: true,
    };
    this.store.set(k, { ref, kind, value: structuredClone(value) });
    this.registeredObjects.push({
      project_id,
      id,
      revision,
      kind,
      value: structuredClone(value),
      persisted: ref.persisted,
    });
    return ref;
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
    const project = {
      project_id: projectId,
      committed_revision: revision,
      last_request_id: null,
      last_committed_result: null,
      active_object_refs: [],
      updated_at: "2026-11-18T00:00:00Z",
      metadata: {},
    };
    return {
      committed: true,
      project,
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
    for (const [k, v] of this.store.entries()) {
      if (k.startsWith(`${project_id}::`) && v.ref.persisted) {
        objects.push({
          storage_key: `${project_id}:${v.ref.object_id}:${v.ref.revision}`,
          project_id,
          object_id: v.ref.object_id,
          revision: v.ref.revision,
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

test("WP-V1-F8-TYPED-WORKSPACE-INPUTS: validação estrita de DTOs canônicos e rejeição de tipos/dimensões inválidos", () => {
  const ds = validateTypedCanonicalDto(buildValidDatasetDto());
  assert.equal(ds.kind, "Dataset");
  assert.match(ds.summary, /Dataset \(N=4, m=1, p=1, dt=0\.05\)/);

  const tf = validateTypedCanonicalDto(buildValidTransferFunctionDto());
  assert.equal(tf.kind, "TransferFunction");

  const fz = validateTypedCanonicalDto(buildValidFuzzySystemDto());
  assert.equal(fz.kind, "FuzzySystem");

  for (const tsKind of ["ts_measured", "polytopic_uncertain", "ts_partially_observed"] as const) {
    const ts = validateTypedCanonicalDto(buildValidTsModelDto(tsKind));
    assert.equal(ts.kind, tsKind);
  }

  const idm = validateTypedCanonicalDto(buildValidIdentifiedModelDto());
  assert.equal(idm.kind, "IdentifiedModel");

  // Rejeita discriminante serializado inválido "TSStateSpace"
  assert.throws(
    () =>
      validateTypedCanonicalDto({
        ...buildValidTsModelDto("ts_measured"),
        kind: "TSStateSpace",
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError &&
      err.code === "UNSUPPORTED_MODEL" &&
      /TSStateSpace/.test(err.message),
  );

  // Rejeita Dataset com comprimentos incompatíveis entre t, u e y
  assert.throws(
    () =>
      validateTypedCanonicalDto(
        buildValidDatasetDto({
          y: { dtype: "float64", order: "C", shape: [3, 1], data: [0.1, 0.2, 0.3] },
        }),
      ),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "DIMENSION_MISMATCH",
  );

  // Rejeita TransferFunction contínua com variável discreta
  assert.throws(
    () =>
      validateTypedCanonicalDto(
        buildValidTransferFunctionDto({ dt: null, variable: "z" }),
      ),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );

  // Rejeita TS com vértices de dimensões diferentes
  const badTs = buildValidTsModelDto("ts_measured");
  (badTs.vertices as Array<Record<string, unknown>>)[1] = {
    vertex_id: "v2",
    A: { dtype: "float64", order: "C", shape: [3, 3], data: [0, 0, 0, 0, 0, 0, 0, 0, 0] },
    B: { dtype: "float64", order: "C", shape: [3, 1], data: [0, 0, 1] },
    C: { dtype: "float64", order: "C", shape: [1, 3], data: [1, 0, 0] },
    D: { dtype: "float64", order: "C", shape: [1, 1], data: [0] },
  };
  assert.throws(
    () => validateTypedCanonicalDto(badTs),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "DIMENSION_MISMATCH",
  );
});

test("WP-V1-F8-TYPED-WORKSPACE-INPUTS: cada ferramenta recebe apenas referências do tipo correto e bloqueia ausência ou tipo incompatível", async () => {
  const client = new RecordingTypedEngineClient();
  const lqrPlant = createDoubleIntegratorPlant();
  const workspace = new TypedObjectWorkspace({
    client,
    projectIdProvider: () => "proj-typed-01",
    projectRevisionProvider: () => 1,
    activeLqrPlantProvider: () => lqrPlant,
  });
  const tabs = new ProjectTabsController({ client, typedWorkspace: workspace });

  // 1. Sem Dataset registrado, identification.fit_arx é bloqueado ANTES de chamar o RPC
  //    e nunca recebe o StateSpace LQR!
  await assert.rejects(
    () =>
      tabs.executeTool("identification.fit_arx", {
        project_id: "proj-typed-01",
        project_revision: 1,
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError &&
      err.code === "VALIDATION_ERROR" &&
      /Dataset/.test(err.message),
  );
  assert.equal(client.executedRequests.length, 0);

  // 2. Tentativa explícita de injetar plant_ref em identification.fit_arx falha com UNSUPPORTED_MODEL
  await assert.rejects(
    () =>
      tabs.executeTool("identification.fit_arx", {
        project_id: "proj-typed-01",
        project_revision: 1,
        extraPayload: { plant_ref: { id: lqrPlant.id, revision: lqrPlant.revision } },
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "UNSUPPORTED_MODEL",
  );
  assert.equal(client.executedRequests.length, 0);

  // 3. Sem FuzzySystem registrado, fuzzy.evaluate_surface falha com VALIDATION_ERROR
  await assert.rejects(
    () =>
      tabs.executeTool("fuzzy.evaluate_surface", {
        project_id: "proj-typed-01",
        project_revision: 1,
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError &&
      err.code === "VALIDATION_ERROR" &&
      /FuzzySystem/.test(err.message),
  );
  assert.equal(client.executedRequests.length, 0);

  // 4. optimization.solve com template ts_pdc_stabilization rejeita ausência de TSStateSpace
  //    (não envia plant_ref do LQR!)
  tabs.setToolParameters("optimization.solve", { template: "ts_pdc_stabilization" });
  await assert.rejects(
    () =>
      tabs.executeTool("optimization.solve", {
        project_id: "proj-typed-01",
        project_revision: 1,
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError &&
      err.code === "VALIDATION_ERROR" &&
      /TSStateSpace/.test(err.message),
  );
  assert.equal(client.executedRequests.length, 0);

  // 5. Registrar Dataset de treino e de validação -> fit_arx recebe dataset_ref e val_dataset_ref (sem plant_ref)
  await workspace.registerTypedObject(buildValidDatasetDto({ id: "ds-train", revision: 1 }));
  await workspace.registerTypedObject(
    buildValidDatasetDto({ id: "ds-val", revision: 2 }),
    { selectRole: "valDataset" },
  );

  const arxRec = await tabs.executeTool("identification.fit_arx", {
    project_id: "proj-typed-01",
    project_revision: 1,
  });
  assert.equal(arxRec.response.status, "success");
  const lastArxReq = client.executedRequests.at(-1)!;
  assert.deepEqual(lastArxReq.payload.dataset_ref, { id: "ds-train", revision: 1 });
  assert.deepEqual(lastArxReq.payload.val_dataset_ref, { id: "ds-val", revision: 2 });
  assert.equal("plant_ref" in lastArxReq.payload, false);

  // 6. Registrar FuzzySystem -> fuzzy.evaluate_surface recebe apenas system_ref
  await workspace.registerTypedObject(buildValidFuzzySystemDto({ id: "fz-01", revision: 4 }));
  await tabs.executeTool("fuzzy.evaluate_surface", {
    project_id: "proj-typed-01",
    project_revision: 1,
  });
  const lastFuzzyReq = client.executedRequests.at(-1)!;
  assert.deepEqual(lastFuzzyReq.payload.system_ref, { id: "fz-01", revision: 4 });
  assert.equal("plant_ref" in lastFuzzyReq.payload, false);

  // 7. Registrar TSStateSpace -> optimization.solve (ts_pdc_stabilization) recebe ts_model_ref
  await workspace.registerTypedObject(buildValidTsModelDto("ts_measured", { id: "ts-01", revision: 2 }));
  await tabs.executeTool("optimization.solve", {
    project_id: "proj-typed-01",
    project_revision: 1,
    feedbackSign: "negative",
  });
  const lastTsOptReq = client.executedRequests.at(-1)!;
  assert.deepEqual(lastTsOptReq.payload.ts_model_ref, { id: "ts-01", revision: 2 });
  assert.equal("plant_ref" in lastTsOptReq.payload, false);

  // 8. optimization.solve com template quadratic_stabilization usa plant_ref (StateSpace do LQR)
  tabs.setToolParameters("optimization.solve", { template: "quadratic_stabilization" });
  await tabs.executeTool("optimization.solve", {
    project_id: "proj-typed-01",
    project_revision: 1,
    feedbackSign: "negative",
  });
  const lastLtiOptReq = client.executedRequests.at(-1)!;
  assert.deepEqual(lastLtiOptReq.payload.plant_ref, {
    id: lqrPlant.id,
    revision: lqrPlant.revision,
  });
  assert.equal("ts_model_ref" in lastLtiOptReq.payload, false);

  // 9. optimization.verify NÃO recebe plant_ref injetado
  await tabs.executeTool("optimization.verify", {
    project_id: "proj-typed-01",
    project_revision: 1,
  });
  const lastVerifyReq = client.executedRequests.at(-1)!;
  assert.equal("plant_ref" in lastVerifyReq.payload, false);

  // 10. Selecionar incompatível em selectRef lança UNSUPPORTED_MODEL
  assert.throws(
    () => workspace.selectRef("statespacePlant", { id: "ds-train", revision: 1 }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "UNSUPPORTED_MODEL",
  );
  assert.throws(
    () => workspace.selectRef("frequencyPlant", { id: "fz-01", revision: 4 }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "UNSUPPORTED_MODEL",
  );
});

test("WP-V1-F8-TYPED-WORKSPACE-INPUTS: seleção por teclado e proteção contra sobrescrita por revisão antiga (síncrona e assíncrona)", async () => {
  const client = new RecordingTypedEngineClient();
  const workspace = new TypedObjectWorkspace({
    client,
    projectIdProvider: () => "proj-rev-guard",
    projectRevisionProvider: () => 1,
  });

  // Registra revisão 2 primeiro com selectRole
  await workspace.registerTypedObject(
    buildValidDatasetDto({ id: "ds-main", revision: 2 }),
    { selectRole: "dataset" },
  );
  assert.deepEqual(workspace.getSelectedRef("dataset"), { id: "ds-main", revision: 2 });

  // Tentativa padrão (sem allowHistoricalDowngrade) de sobrescrever ds-main#2 com ds-main#1 é bloqueada!
  await workspace.registerTypedObject(
    buildValidDatasetDto({ id: "ds-main", revision: 1 }),
  );
  assert.throws(
    () => workspace.selectRef("dataset", { id: "ds-main", revision: 1 }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError &&
      err.code === "VALIDATION_ERROR" &&
      /Revisão antiga/.test(err.message),
  );
  assert.deepEqual(workspace.getSelectedRef("dataset"), { id: "ds-main", revision: 2 });

  // Corrida assíncrona: registro lento da revisão 1 com selectRole iniciado ANTES do registro rápido da revisão 3
  client.registerDelayMsByKey.set("ds-race#1", 40);
  client.registerDelayMsByKey.set("ds-race#3", 1);

  const slowRev1 = workspace.registerTypedObject(
    buildValidDatasetDto({ id: "ds-race", revision: 1 }),
    { selectRole: "dataset" },
  );
  const fastRev3 = workspace.registerTypedObject(
    buildValidDatasetDto({ id: "ds-race", revision: 3 }),
    { selectRole: "dataset" },
  );
  await Promise.all([slowRev1, fastRev3]);

  // A revisão 1 atrasada NÃO pode sobrescrever a seleção atual ds-race#3!
  assert.deepEqual(workspace.getSelectedRef("dataset"), { id: "ds-race", revision: 3 });

  // Navegação por teclado (ArrowDown / ArrowUp / Home / End) cicla explicitamente entre objetos compatíveis
  const navHome = workspace.handleRoleKeyNavigation("dataset", "Home");
  assert.equal(navHome.handled, true);
  assert.deepEqual(navHome.selectedRef, { id: "ds-main", revision: 2 });

  const navDown = workspace.handleRoleKeyNavigation("dataset", "ArrowDown");
  assert.equal(navDown.handled, true);
  assert.deepEqual(navDown.selectedRef, { id: "ds-main", revision: 1 });

  const navEnd = workspace.handleRoleKeyNavigation("dataset", "End");
  assert.equal(navEnd.handled, true);
  assert.deepEqual(navEnd.selectedRef, { id: "ds-race", revision: 1 });

  const navUp = workspace.handleRoleKeyNavigation("dataset", "ArrowUp");
  assert.equal(navUp.handled, true);
  assert.deepEqual(navUp.selectedRef, { id: "ds-race", revision: 3 });

  const navUnhandled = workspace.handleRoleKeyNavigation("dataset", "Enter");
  assert.equal(navUnhandled.handled, false);
});

test("WP-V1-F8-TYPED-WORKSPACE-INPUTS: fluxo explícito fit_arx -> registro IdentifiedModel -> core.reuse_model -> registro derivado -> consumo SISO/LQR", async () => {
  const client = new RecordingTypedEngineClient();
  const shell = new ControlLabShell({ client, project_id: "proj-reuse-flow" });
  const workspace = shell.getTypedWorkspace();
  const tabs = shell.getTabsController();

  await workspace.registerTypedObject(buildValidDatasetDto({ id: "ds-reuse", revision: 1 }));
  await tabs.executeTool("identification.fit_arx", {
    project_id: "proj-reuse-flow",
    project_revision: 1,
  });

  // O resultado de fit_arx gera um IdentifiedModel pendente, mas NÃO o registra automaticamente!
  const pendingId = workspace.getPendingIdentifiedModel();
  assert.ok(pendingId);
  assert.equal(pendingId.registered, false);
  assert.equal(
    workspace.getRegisteredObject(pendingId.model_ref),
    null,
    "IdentifiedModel não deve ser registrado automaticamente sem ação do usuário",
  );

  // Registro explícito do IdentifiedModel pendente
  const regIdObj = await workspace.registerPendingIdentifiedModel();
  assert.equal(regIdObj.kind, "IdentifiedModel");
  assert.equal(workspace.getPendingIdentifiedModel()?.registered, true);
  assert.deepEqual(workspace.getSelectedRef("reuseSource"), {
    id: regIdObj.id,
    revision: regIdObj.revision,
  });

  // Executa core.reuse_model convertendo para StateSpace
  const reuseOutcome = await workspace.reuseModel({ targetKind: "StateSpace" });
  assert.equal(reuseOutcome.derivedKind, "StateSpace");
  assert.equal(reuseOutcome.dt, 0.05);
  assert.equal(reuseOutcome.registration_required, true);

  // Verifica que a requisição core.reuse_model seguiu o contrato RPC v1.0 (options vazio, model_ref exato)
  const reuseReq = client.executedRequests.find((r) => r.operation === "core.reuse_model")!;
  assert.deepEqual(reuseReq.options, {});
  assert.deepEqual(reuseReq.payload, {
    model_ref: { id: regIdObj.id, revision: regIdObj.revision },
    target_kind: "StateSpace",
  });

  // Antes do registro explícito, o derivado ainda NÃO está registrado no workspace
  assert.equal(workspace.getPendingDerivedModel()?.registered, false);
  assert.equal(workspace.getRegisteredObject(reuseOutcome.derivedRef), null);

  // Registro explícito do modelo derivado selecionando-o para StateSpace e Frequência
  const regDerived = await workspace.registerPendingDerivedModel({
    selectCompatible: true,
  });
  assert.equal(regDerived.kind, "StateSpace");
  assert.deepEqual(workspace.getSelectedRef("statespacePlant"), reuseOutcome.derivedRef);
  assert.deepEqual(workspace.getSelectedRef("frequencyPlant"), reuseOutcome.derivedRef);

  // Consumo em SISO (frequency.eval_response) usa o modelo derivado registrado
  await tabs.executeTool("siso.bode_nyquist", {
    project_id: "proj-reuse-flow",
    project_revision: 1,
  });
  const sisoReq = client.executedRequests.at(-1)!;
  assert.equal(sisoReq.operation, "frequency.eval_response");
  assert.deepEqual(sisoReq.payload.plant_ref, reuseOutcome.derivedRef);

  // Consumo direto no workspace LQR sem cópia manual de matrizes
  const appliedPlant = shell.applySelectedPlantToLqr();
  assert.equal(appliedPlant.id, reuseOutcome.derivedRef.id);
  assert.equal(appliedPlant.dt, 0.05);
});

test("WP-V1-F8-TYPED-WORKSPACE-INPUTS: DOM mountControlLabApp, seletores por teclado, campos opcionais em branco sem NaN e cards não implementadas indisponíveis", async () => {
  // Fake DOM minimalista compatível com mountControlLabApp
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
    const attrMatches = Array.from(selector.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g));
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

  function parseFakeHtml(html: string, doc: FakeDocument, parent: FakeElement): FakeElement[] {
    const nodes: FakeElement[] = [];
    const tagRe = /<(button|input|select|textarea|section|div|span|pre|h2|h3|article|details)\b([^>]*)>/gi;
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

  // 1. Cliente MockWorkerAdapter que NÃO implementa fuzzy.evaluate nem identification.fit_subspace:
  //    as cards não suportadas devem permanecer honestamente indisponíveis!
  const mockClient = new MockWorkerAdapter();
  await mockClient.init();
  const mockDoc = new FakeDocument();
  const mockRoot = mockDoc.createElement("div");
  const mountedMock = mountControlLabApp(mockRoot as unknown as HTMLElement, {
    client: mockClient,
    project_id: "proj-mock-honest",
  });

  const fuzzyTabVm = mountedMock.shell.getTabsController().getTabViewModel("fuzzy_ts");
  const fuzzyCard = fuzzyTabVm.tools.find((t) => t.toolId === "fuzzy.evaluate_surface")!;
  assert.equal(fuzzyCard.maturity.available, false);
  assert.equal(fuzzyCard.canExecute, false);
  assert.match(fuzzyCard.disabledReason ?? "", /não suportada no runtime/);
  mountedMock.destroy();

  // 2. Cliente Pyodide simulado com suporte às operações para testar UI tipada completa
  const client = new RecordingTypedEngineClient();
  const doc = new FakeDocument();
  const root = doc.createElement("div");
  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-dom-typed",
  });

  // Tenta registrar objeto vazio -> erro visível em #controllab-error-slot
  const regBtn = root.querySelector('[data-action="register-typed-object"]')!;
  regBtn.dispatchEvent("click");
  const errSlot = root.querySelector("#controllab-error-slot")!;
  assert.match(errSlot.innerHTML, /VALIDATION_ERROR/);

  // Preenche JSON válido de Dataset e clica em Registrar
  const jsonInput = root.querySelector("#typed-object-json")!;
  jsonInput.value = JSON.stringify(buildValidDatasetDto({ id: "ds-dom-1", revision: 1 }));
  regBtn.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 10));

  assert.equal(app.shell.getTypedWorkspace().listRegisteredObjects().length, 1);

  // Registra segundo Dataset e navega por teclado no seletor <select data-role="dataset">
  jsonInput.value = JSON.stringify(buildValidDatasetDto({ id: "ds-dom-2", revision: 2 }));
  regBtn.dispatchEvent("click");
  await new Promise((r) => setTimeout(r, 10));

  const selectorsSlot = root.querySelector("#typed-workspace-selectors-slot")!;
  const dsSelect = root.querySelector('[data-action="select-typed-ref"][data-role="dataset"]')!;
  selectorsSlot.dispatchEvent("keydown", { target: dsSelect, key: "ArrowDown" });
  assert.deepEqual(app.shell.getTypedWorkspace().getSelectedRef("dataset"), {
    id: "ds-dom-2",
    revision: 2,
  });

  // Muda seleção via evento change usando encode/decodeObjectRefKey
  const key1 = encodeObjectRefKey({ id: "ds-dom-1", revision: 1 });
  assert.deepEqual(decodeObjectRefKey(key1), { id: "ds-dom-1", revision: 1 });
  dsSelect.value = key1;
  selectorsSlot.dispatchEvent("change", { target: dsSelect });
  assert.deepEqual(app.shell.getTypedWorkspace().getSelectedRef("dataset"), {
    id: "ds-dom-1",
    revision: 1,
  });

  // Muda para aba optimization_lmi e deixa campo numérico opcional "radius" em branco (""):
  // deve continuar válido (sem NaN) e executar quadratic_stabilization com plant_ref do LQR
  app.shell.switchTab("optimization_lmi");
  const toolsSlot = root.querySelector("#controllab-tools-slot")!;
  const radiusInput = root.querySelector(
    '[data-tool-id="optimization.solve"][data-param-name="radius"]',
  )!;
  radiusInput.value = "";
  toolsSlot.dispatchEvent("change", { target: radiusInput });

  const optVm = app.shell
    .getTabsController()
    .getTabViewModel("optimization_lmi")
    .tools.find((t) => t.toolId === "optimization.solve")!;
  assert.equal(optVm.validation.valid, true);
  assert.equal("radius" in optVm.validation.sanitized, false);

  const templateSelect = root.querySelector(
    '[data-tool-id="optimization.solve"][data-param-name="template"]',
  )!;
  templateSelect.value = "quadratic_stabilization";
  const execOptBtn = root.querySelector(
    '[data-action="execute-tool"][data-tool-id="optimization.solve"]',
  )!;
  toolsSlot.dispatchEvent("click", { target: execOptBtn });
  await new Promise((r) => setTimeout(r, 15));

  const optReq = client.executedRequests.find((r) => r.operation === "optimization.solve")!;
  assert.ok(optReq);
  assert.deepEqual(optReq.payload.plant_ref, {
    id: app.shell.getLqrWorkspace().getPlant().id,
    revision: app.shell.getLqrWorkspace().getPlant().revision,
  });

  app.destroy();
});
