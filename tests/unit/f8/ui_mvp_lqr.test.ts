import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  ControlLabBridgeError,
  sha256Hex,
  ERROR_CATEGORIES,
  type RealTensor,
  type CapabilityDescriptor,
} from "../../../web/bridge/protocol.ts";
import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { PyodideEngineClient } from "../../../web/bridge/pyodide_client.ts";
import {
  IndexedDBProjectStore,
  InMemoryIDBFactory,
} from "../../../web/storage/indexeddb_store.ts";

import {
  AriaLiveAnnouncer,
  contrastRatio,
  FocusRestorer,
  formatNumericDisplay,
  getSliderAriaAttributes,
  getTabAriaAttributes,
  handleSliderKeyDown,
  handleTablistKeyDown,
  HIGH_CONTRAST_THEME,
  meetsWcagAA,
  MIN_TOUCH_TARGET_PX,
  STANDARD_AA_THEME,
  validateTouchTarget,
} from "../../../web/app/accessibility.ts";
import {
  PROJECT_TAB_IDS,
  ToolDescriptorRenderer,
  resolveEffectiveMaturity,
  type ToolDescriptor,
} from "../../../web/app/tool_descriptor.ts";
import {
  ControlLabShell,
  DEFAULT_DYNAMIC_EXPORT_CONTROLLER,
  presentTypedError,
} from "../../../web/app/shell.ts";
import {
  createDiscreteSpectralRadiusOverlay,
  createHalfPlaneDecayOverlay,
  createLmiCrossRegionOverlay,
  createRequirementOverlay,
  createSecondOrderRegionOverlay,
  evaluatePolesAgainstOverlay,
} from "../../../web/charts/overlays.ts";
import {
  buildAccessibleChartTable,
  buildTimeResponseChartModel,
  classifyPoleStability,
  computeSafeAxisBounds,
  exportChartToCsv,
  FRAME_BUDGET_60FPS_MS,
  renderAccessibleTableHtml,
  renderPoleZeroSvg,
  renderTimeResponseSvg,
} from "../../../web/charts/scientific_chart.ts";
import {
  createDoubleIntegratorPlant,
  LqrWorkspaceController,
  validateCanonicalStateSpace,
  validateInitialStateTensor,
  type CanonicalStateSpaceModel,
} from "../../../web/features/lqr_workspace.ts";
import { ProjectTabsController } from "../../../web/features/project_tabs.ts";
import { mountControlLabApp, registerControlLabServiceWorker, resolveBrowserRuntimeAssets } from "../../../web/app/main.ts";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "../../..");
const FIXTURES_DIR = path.join(REPO_ROOT, "contracts", "fixtures");

function loadChecksums(): Record<string, string> {
  const raw = fs.readFileSync(path.join(FIXTURES_DIR, "checksums.sha256"), "utf8");
  const out: Record<string, string> = {};
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const [digest, fname] = trimmed.split(/\s+/);
    out[fname.trim()] = digest.trim().toLowerCase();
  }
  return out;
}

function loadCertifiedFixtures() {
  const checksums = loadChecksums();
  const bCare02Raw = fs.readFileSync(path.join(FIXTURES_DIR, "B-CARE-02.json"), "utf8");
  const bCare12Raw = fs.readFileSync(path.join(FIXTURES_DIR, "B-CARE-12x3.json"), "utf8");
  const bSdpRaw = fs.readFileSync(path.join(FIXTURES_DIR, "B-SDP-A-D.json"), "utf8");
  return {
    bCare02Raw,
    bCare12Raw,
    bSdpRaw,
    fixturesMap: {
      "B-CARE-02": {
        rawJson: bCare02Raw,
        expectedSha256: checksums["B-CARE-02.json"],
      },
      "B-CARE-12x3": {
        rawJson: bCare12Raw,
        expectedSha256: checksums["B-CARE-12x3.json"],
      },
      "B-SDP-A-D": {
        rawJson: bSdpRaw,
        expectedSha256: checksums["B-SDP-A-D.json"],
      },
    },
  };
}

function buildPlantFromFixtureJson(
  fixtureRaw: string,
  id: string,
): {
  plant: CanonicalStateSpaceModel;
  Q: RealTensor;
  R: RealTensor;
  x0: RealTensor;
  expected: Record<string, unknown>;
} {
  const parsed = JSON.parse(fixtureRaw) as {
    fixture_id: string;
    data: {
      dt: number | null;
      A: RealTensor;
      B: RealTensor;
      C: RealTensor;
      D: RealTensor;
      Q: RealTensor;
      R: RealTensor;
      x0: RealTensor;
      expected: Record<string, unknown>;
    };
  };
  const d = parsed.data;
  const n = d.A.shape[0];
  const m = d.B.shape[1];
  const p = d.C.shape[0];

  const plant = validateCanonicalStateSpace({
    schema_version: "1.0.0",
    id,
    revision: 1,
    kind: "StateSpace",
    dt: d.dt,
    state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
    input_names: Array.from({ length: m }, (_, i) => `u${i + 1}`),
    output_names: Array.from({ length: p }, (_, i) => `y${i + 1}`),
    matrices: { A: d.A, B: d.B, C: d.C, D: d.D },
    units: {
      time: "s",
      states: Array.from({ length: n }, () => "rad"),
      inputs: Array.from({ length: m }, () => "V"),
      outputs: Array.from({ length: p }, () => "rad"),
    },
    provenance: { source: parsed.fixture_id },
  });

  return { plant, Q: d.Q, R: d.R, x0: d.x0, expected: d.expected };
}

function createMockSetup(options?: { latencyMs?: number }) {
  const loaded = loadCertifiedFixtures();
  const store = new IndexedDBProjectStore({
    idbFactory: new InMemoryIDBFactory(),
    dbName: `f8_test_${Math.random().toString(36).slice(2)}`,
  });
  // O adapter F7 12x3 publica apenas referência/polos. Este double F8 explicita
  // K/P da fixture assinada para exercitar uma resposta completa, sem síntese UI.
  class CompleteFixtureAdapter extends MockWorkerAdapter {
    protected override async dispatchRpc(...args: Parameters<MockWorkerAdapter["execute"]>) {
      const request = args[0];
      // Double exclusivo do transporte Node. A validade dos bytes ZIP/PVM é auditada
      // pela F9 com o motor Python e navegador reais, fora deste teste de UI.
      if (request.operation.startsWith("io.")) {
        let result: Record<string, unknown>;
        if (request.operation.startsWith("io.export_")) {
          const bytes = new TextEncoder().encode(JSON.stringify(request.payload));
          result = { bytes_base64: btoa(String.fromCharCode(...bytes)),
            sha256: sha256Hex(bytes), size_bytes: bytes.length,
            media_type: request.operation === "io.export_ctrlab" ? "application/zip" : "application/json" };
        } else {
          const payload = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(String(request.payload.bytes_base64)), (c) => c.charCodeAt(0))));
          const project = payload.project;
          const K = project.controllers[0].K;
          project.controllers[0].K = { data: K.data, dtype: K.dtype, shape: K.shape, order: K.order };
          result = { ...project, manifest: { project_id: project.project_id, project_revision: project.project_revision }, code_executed: false };
        }
        return { response: { api_version: request.api_version, request_id: request.request_id,
          project_id: request.project_id, project_revision: request.project_revision,
          status: "success" as const, result, assumptions: {}, diagnostics: { transport_double_only: true },
          provenance: { algorithm: "test.io_transport", lib_versions: {} }, warnings: [], error: null } };
      }
      const output = await super.dispatchRpc(...args);
      if (output.response.result && output.response.provenance.fixture_id === "B-CARE-12x3") {
        const expected = JSON.parse(loaded.bCare12Raw).data.expected;
        output.response.result = { ...output.response.result, K: expected.K, P: expected.P };
      }
      return output;
    }
  }
  const client = new CompleteFixtureAdapter({
    store,
    fixtures: loaded.fixturesMap,
    latencyMs: options?.latencyMs ?? 0,
  });
  return { loaded, store, client };
}

// ---------------------------------------------------------------------------
// 1. T-UI-01 parcial Node/Mock: custo local de preview vs commit de fixtures
// ---------------------------------------------------------------------------

test("T-UI-01 parcial Node/Mock (B-CARE-02 e B-CARE-12x3): Fast-Preview no pointermove não grava em IndexedDB nem libera exportação; pointerup exige pending_commit e comita fixture, sem prova Wasm", async () => {
  const { loaded, store, client } = createMockSetup({ latencyMs: 15 });
  await client.init();

  try {
    const f02 = buildPlantFromFixtureJson(loaded.bCare02Raw, "plant-care-02");
    const shell = new ControlLabShell({
      client,
      project_id: "proj-tui01",
      lqrWorkspace: new LqrWorkspaceController({
        client,
        project_id: "proj-tui01",
        plant: f02.plant,
        Q: f02.Q,
        R: f02.R,
        x0: f02.x0,
      }),
    });
    const lqr = shell.getLqrWorkspace();

    // Commit da fixture Mock (revisão 1); não executa Python.
    const initialCommitted = await lqr.commitCurrentDesign();
    assert.ok(initialCommitted !== null);
    assert.equal(initialCommitted.project_revision, 1);
    assert.equal(initialCommitted.provenance.algorithm, "mock.certified_fixture.care");
    assert.deepEqual(initialCommitted.K?.data, [2.0, 3.0]);
    assert.equal(lqr.isPendingCommit(), false);
    assert.equal(lqr.canExport().allowed, true);

    const dbBeforeDrag = await store.getProject("proj-tui01");
    assert.equal(dbBeforeDrag?.committed_revision, 1);
    const objsBeforeDrag = await store.listObjects("proj-tui01");

    // Início do arraste (pointerdown + rajada de 60 pointermove a 60 FPS)
    lqr.pointerDown("q-gain-slider");
    for (let frame = 1; frame <= 60; frame += 1) {
      const preview = lqr.pointerMove({
        qScale: 1.0 + frame * 0.05,
        rScale: 1.0,
        deltaX: -0.01 * frame,
      });
      assert.equal(preview.active, true);
      assert.equal(preview.indicator, "preview");
      assert.ok(
        preview.lastMoveElapsedMs < FRAME_BUDGET_60FPS_MS,
        `Frame ${frame} excedeu orçamento de 60 FPS (${preview.lastMoveElapsedMs} ms)`,
      );

      // Exportações estritamente proibidas durante Fast-Preview!
      assert.equal(lqr.canExport().allowed, false);
      assert.throws(
        () => shell.exportGains(),
        (err: unknown) =>
          err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
      );
      assert.throws(
        () => shell.exportPvm(),
        (err: unknown) =>
          err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
      );
      await assert.rejects(
        () => shell.exportCtrlLab(),
        (err: unknown) =>
          err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
      );
      assert.throws(
        () => shell.exportChartCsv(lqr.buildPoleZeroChart()),
        (err: unknown) =>
          err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
      );
      assert.throws(
        () => shell.addCommittedExperiment("preview-proibido"),
        (err: unknown) =>
          err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
      );

      // committedSnapshot permanece imutável durante todo o arraste
      assert.equal(lqr.getCommittedSnapshot()?.project_revision, 1);
    }

    const previewStats = lqr.getPreviewState().frameMetrics;
    assert.equal(previewStats.frameCount, 60);
    assert.ok(previewStats.p95FrameMs < FRAME_BUDGET_60FPS_MS);

    // IndexedDB NÃO pode ter recebido nenhuma revisão ou objeto durante o preview
    const dbDuringDrag = await store.getProject("proj-tui01");
    assert.equal(dbDuringDrag?.committed_revision, 1);
    assert.equal((await store.listObjects("proj-tui01")).length, objsBeforeDrag.length);

    // Gráfico em modo preview exibe camada separada de preview com semântica explícita
    const pzDuringDrag = lqr.buildPoleZeroChart();
    assert.equal(pzDuringDrag.series_semantics, "preview");
    assert.ok(pzDuringDrag.preview_poles !== null);
    assert.ok(pzDuringDrag.committed_closed_loop_poles !== null);

    // pointerup: marca pending_commit=true imediatamente enquanto aguarda motor Python/Mock
    const commitPromise = lqr.pointerUp({ qScale: 4.0, rScale: 1.0 });
    assert.equal(lqr.isPendingCommit(), true);
    assert.equal(lqr.canExport().allowed, false);
    assert.throws(() => shell.exportPvm(), ControlLabBridgeError);

    const committedAfterDrop = await commitPromise;
    assert.ok(committedAfterDrop !== null);
    assert.equal(lqr.isPendingCommit(), false);
    assert.equal(lqr.getPreviewState().active, false);
    assert.equal(committedAfterDrop.project_revision, 2);
    assert.equal(lqr.canExport().allowed, true);

    // IndexedDB agora contém revisão 2 confirmada e exportações estão desbloqueadas
    const dbAfterDrop = await store.getProject("proj-tui01");
    assert.equal(dbAfterDrop?.committed_revision, 2);
    const gainsExport = shell.exportGains();
    assert.equal(gainsExport.project_revision, 2);
    assert.equal(gainsExport.feedback_sign, "negative");
    assert.ok((await shell.exportPvm()).bytes.length > 0);
    const ctrlabPkg = await shell.exportCtrlLab();
    assert.equal(ctrlabPkg.project_revision, 2);

    // Repete com B-CARE-12x3 (n=12, m=3, p=4 -> m != p e C != I)
    const f12 = buildPlantFromFixtureJson(loaded.bCare12Raw, "plant-care-12x3");
    lqr.updatePlant(f12.plant);
    // Enquanto controlador invalidado pela edição da planta, exportação permanece bloqueada!
    assert.equal(lqr.isControllerInvalidated(), true);
    assert.equal(lqr.canExport().allowed, false);

    lqr.updateWeights({ Q: f12.Q, R: f12.R, x0: f12.x0 });
    const committed12 = await lqr.commitCurrentDesign();
    assert.ok(committed12 !== null);
    assert.equal(committed12.closed_loop_poles?.real.length, 12);
    assert.equal(committed12.provenance.fixture_id, "B-CARE-12x3");
    assert.deepEqual(committed12.K, f12.expected.K);
    assert.equal(lqr.canExport().allowed, true);
    assert.ok((await shell.exportPvm()).bytes.length > 0);
    assert.equal((await shell.exportCtrlLab()).project_revision, committed12.project_revision);

    shell.dispose();
  } finally {
    client.dispose();
    store.close();
  }
});

// ---------------------------------------------------------------------------
// 2. Falha fechada sem transporte: Node, sem prova de Gate G-0C/Wasm.
// ---------------------------------------------------------------------------

test("UI Node: Pyodide sem worker explícito falha e não permite commit/exportação", async () => {
  const store = new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory(), dbName: "f8_no_worker" });
  const client = new PyodideEngineClient({ store });
  const shell = new ControlLabShell({ client, project_id: "no-worker" });
  try {
    await assert.rejects(() => client.init(), (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "SOLVER_UNAVAILABLE");
    assert.equal(await shell.getLqrWorkspace().commitCurrentDesign(), null);
    assert.equal(shell.getLqrWorkspace().getCommittedSnapshot(), null);
    assert.equal(shell.getLqrWorkspace().canExport().allowed, false);
    assert.equal(client.getCapabilities().offline_ready, false);
    assert.equal((await store.getProject("no-worker"))?.committed_revision ?? 0, 0);
  } finally {
    shell.dispose(); client.dispose(); store.close();
  }
});

// ---------------------------------------------------------------------------
// 3. Concorrência, Cancelamento, Perda de Foco, Troca de Aba, Undo e Erros
// ---------------------------------------------------------------------------

test("Concorrência, cancelamento (Escape), blur, troca de aba, undo, model_revision e 12 categorias de erro", async () => {
  const { store, client } = createMockSetup({ latencyMs: 35 });
  await client.init();

  try {
    const shell = new ControlLabShell({
      client,
      project_id: "proj-edge",
      lqrWorkspace: new LqrWorkspaceController({
        client,
        project_id: "proj-edge",
        plant: createDoubleIntegratorPlant(),
      }),
    });
    const lqr = shell.getLqrWorkspace();

    // Baseline commit (rev 1)
    const baseCommit = await lqr.commitCurrentDesign();
    assert.ok(baseCommit !== null);
    assert.equal(baseCommit.project_revision, 1);

    // 1) Respostas fora de ordem / superseding: dispara rev 2 e logo após rev 3
    const pRev2 = lqr.commitCurrentDesign();
    const pRev3 = lqr.commitCurrentDesign();
    const [r2, r3] = await Promise.all([pRev2, pRev3]);
    assert.ok(r3 !== null);
    assert.equal(r3.project_revision, 3);
    assert.equal(lqr.getCommittedSnapshot()?.project_revision, 3);
    assert.ok(r2 !== null);

    // 2) Perda de foco (blur) durante arraste descarta preview sem gravar no IndexedDB
    lqr.pointerDown("handle-blur");
    lqr.pointerMove({ qScale: 5.0 });
    assert.equal(lqr.getPreviewState().active, true);
    lqr.handleBlur();
    assert.equal(lqr.getPreviewState().active, false);
    assert.equal((await store.getProject("proj-edge"))?.committed_revision, 3);

    // 3) Troca de aba durante arraste descarta preview
    lqr.pointerDown("handle-tab");
    lqr.pointerMove({ qScale: 8.0 });
    shell.switchTab("identification");
    assert.equal(shell.getActiveTab(), "identification");
    assert.equal(lqr.getPreviewState().active, false);
    shell.switchTab("statespace");

    // 4) Cancelamento durante pending_commit preserva último resultado confirmado
    const pCancelled = lqr.commitCurrentDesign();
    assert.equal(lqr.isPendingCommit(), true);
    await lqr.cancelDrag();
    await pCancelled;
    assert.equal(lqr.isPendingCommit(), false);
    assert.equal(lqr.getCommittedSnapshot()?.project_revision, 3);

    // 5) Falha matemática (HYPOTHESIS_VIOLATED com R <= 0 e modo não controlável) preserva commit válido
    lqr.updateWeights({
      R: { shape: [1, 1], dtype: "float64", order: "C", data: [-1.0] },
    });
    const failR = await lqr.commitCurrentDesign();
    assert.equal(failR, null);
    assert.equal(lqr.getLastError()?.code, "HYPOTHESIS_VIOLATED");
    const presented = shell.getPresentedLastError();
    assert.ok(presented !== null);
    assert.equal(presented.code, "HYPOTHESIS_VIOLATED");
    assert.ok(presented.next_step.length > 0);
    assert.equal(lqr.getCommittedSnapshot()?.project_revision, 3);

    // 6) Undo restaura pesos anteriores e recompila em revisão monotônica (> 3)
    const undone = await lqr.undo();
    assert.equal(undone, true);
    assert.ok((lqr.getCommittedSnapshot()?.project_revision ?? 0) > 3);
    assert.equal(lqr.getWeights().R.data[0], 1.0);

    // 7) Edição de planta com dimensão inválida falha sem corromper modelo ativo
    assert.throws(
      () =>
        lqr.updatePlant({
          ...createDoubleIntegratorPlant(),
          matrices: {
            ...createDoubleIntegratorPlant().matrices,
            B: { shape: [3, 1], dtype: "float64", order: "C", data: [0, 0, 1] },
          },
        }),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "DIMENSION_MISMATCH",
    );
    assert.equal(lqr.getPlant().revision, 1);

    // 8) Apresentador cobre todas as 12 categorias normativas de erro
    assert.equal(ERROR_CATEGORIES.length, 12);
    for (const cat of ERROR_CATEGORIES) {
      const pErr = presentTypedError({
        code: cat,
        message: `Mensagem de teste para ${cat}`,
      });
      assert.equal(pErr.code, cat);
      assert.ok(pErr.title.length > 0);
      assert.ok(pErr.next_step.length > 0);
      assert.equal(pErr.local_only, true);
    }

    shell.dispose();
  } finally {
    client.dispose();
    store.close();
  }
});

// ---------------------------------------------------------------------------
// 4. ToolDescriptor Registry, Descoberta Dinâmica e Selos de Maturidade
// ---------------------------------------------------------------------------

test("ToolDescriptor: descoberta dinâmica sem alterar roteamento global e selos stable/beta/experimental/unavailable_wasm", async () => {
  const { store, client } = createMockSetup();
  await client.init();

  try {
    const tabs = new ProjectTabsController({ client });
    const renderer = new ToolDescriptorRenderer();

    // Todas as 6 abas existem e carregam descritores declarativos
    assert.equal(PROJECT_TAB_IDS.length, 6);
    const lmiTab = tabs.getTabViewModel("optimization_lmi");
    const sdpSolveTool = lmiTab.tools.find(
      (t) => t.toolId === "optimization.solve",
    );
    assert.ok(sdpSolveTool, "Aba 6 deve conter optimization.solve");
    // MockWorkerAdapter declara clarabel_cvxpy: { available: false, maturity: "unavailable_wasm" }
    assert.equal(sdpSolveTool.maturity.maturity, "unavailable_wasm");
    assert.equal(sdpSolveTool.maturity.available, false);
    assert.equal(sdpSolveTool.canExecute, false);

    // Tentar executar ferramenta unavailable_wasm falha honestamente com SOLVER_UNAVAILABLE
    await assert.rejects(
      () =>
        tabs.executeTool("optimization.solve", {
          project_id: "proj-tools",
          project_revision: 1,
        }),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "SOLVER_UNAVAILABLE",
    );

    // Registro dinâmico de uma nova ferramenta científica na Aba 1 sem alterar código de roteamento
    const customTool: ToolDescriptor = {
      id: "identification.subspace_experimental",
      title: "Identificação por Subespaços (N4SID Experimental)",
      description: "Protótipo de identificação multivariável por subespaços.",
      tab: "identification",
      input_types: ["Dataset(t,u,y)"],
      parameter_schema: [
        {
          name: "order",
          label: "Ordem do sistema",
          type: "integer",
          required: true,
          default_value: 3,
          min: 1,
          max: 20,
        },
      ],
      operation: "identification.fit_subspace",
      output_types: ["IdentifiedModel"],
      visualizations: ["pole_zero_map"],
      requirements: ["Excitação multivariável suficiente"],
      interaction_mode: "batch_async",
      maturity: "experimental",
      limits: { hard_timeout_ms: 15000, notes: "Experimental." },
      examples: [],
      default_indicator: "experimental",
    };

    tabs.registerTool(customTool);
    const idTabAfter = tabs.getTabViewModel("identification");
    const discovered = idTabAfter.tools.find(
      (t) => t.toolId === "identification.subspace_experimental",
    );
    assert.ok(discovered, "Nova ferramenta deve ser descoberta automaticamente na aba");
    assert.equal(discovered.maturity.maturity, "experimental");
    assert.equal(discovered.indicator, "experimental");
    assert.ok(discovered.toHtml().includes('data-maturity-badge="experimental"'));

    // Validação local rejeita NaN e números fora da faixa
    const invalidVm = renderer.render(customTool, {
      capabilities: client.getCapabilities(),
      parameterValues: { order: Number.NaN },
    });
    assert.equal(invalidVm.validation.valid, false);
    assert.equal(invalidVm.canExecute, false);
  } finally {
    client.dispose();
    store.close();
  }
});

test("test_tool_descriptor_unlisted_operation_and_typecheck", async () => {
  const { client, store } = createMockSetup();
  try {
    await client.init();
    const caps = client.getCapabilities();
    const tabs = new ProjectTabsController({ client });
    const descriptor = tabs.getRegistry().get("statespace.design_lqr");
    assert.ok(descriptor);
    assert.equal(descriptor.maturity, "beta");
    assert.equal(caps.offline_ready, false);
    assert.equal(resolveEffectiveMaturity(descriptor, null).available, false);
    for (const backends of [{}, { missing: { available: false, maturity: "beta" } }]) {
      assert.equal(resolveEffectiveMaturity({ ...descriptor, required_backend: "missing" }, { ...caps, backends }).available, false);
    }
    const omitted = { ...caps, operations: caps.operations.filter((op) => op !== descriptor.operation) };
    // Mesmo com mapa de maturidade aparentemente utilizável, lista de operações é obrigatória.
    for (const maturity of ["stable", "beta", "experimental", "unavailable_wasm"] as const) {
      const unlisted: CapabilityDescriptor = { ...omitted, maturity: { ...omitted.maturity, [descriptor.operation]: maturity } };
      assert.equal(resolveEffectiveMaturity(descriptor, unlisted).available, false);
      const vm = new ToolDescriptorRenderer().render(descriptor, { capabilities: unlisted });
      assert.equal(vm.canExecute, false);
    }
    // Mock F7 nativo não anuncia numpy_scipy: catálogo deve permanecer indisponível.
    assert.equal(resolveEffectiveMaturity(descriptor, caps).available, false);
    assert.equal(resolveEffectiveMaturity(descriptor, { ...caps, backends: {
      ...caps.backends, numpy_scipy: { available: true, maturity: "beta" },
    } }).available, true);
  } finally { client.dispose(); store.close(); }
});

test("UI Node/adapter explícito: resposta inconclusive não vira snapshot nem libera exportação", async () => {
  const { client, store } = createMockSetup();
  await client.init();
  client.execute = async (request) => ({
    api_version: request.api_version, request_id: request.request_id,
    project_id: request.project_id, project_revision: request.project_revision,
    status: "inconclusive", result: {}, diagnostics: { committed: false },
    assumptions: {}, provenance: { algorithm: "test.inconclusive_adapter", lib_versions: {} },
    warnings: ["Sem certificado"], error: null,
  });
  const shell = new ControlLabShell({ client, project_id: "inconclusive-ui" });
  try {
    assert.equal(await shell.getLqrWorkspace().commitCurrentDesign(), null);
    assert.equal(shell.getLqrWorkspace().isPendingCommit(), false);
    assert.equal(shell.getLqrWorkspace().getCommittedSnapshot(), null);
    assert.equal(shell.getLqrWorkspace().canExport().allowed, false);
    assert.equal(shell.getLqrWorkspace().getLastError()?.code, "VALIDATION_ERROR");
    assert.throws(() => shell.exportGains(), ControlLabBridgeError);
    assert.equal((await store.getProject("inconclusive-ui"))?.committed_revision ?? 0, 0);
    assert.equal((await store.listObjects("inconclusive-ui")).length, 0);
  } finally { shell.dispose(); client.dispose(); store.close(); }
});

test("Bootstrap Node: contrato de URLs de build e registro SW module, sem prova offline", async () => {
  const calls: { url: string | URL; options?: RegistrationOptions }[] = [];
  const registration = {} as ServiceWorkerRegistration;
  const assets = resolveBrowserRuntimeAssets("https://example.org/ControlLab/app/main.js");
  const result = await registerControlLabServiceWorker({
    async register(url, options) { calls.push({ url, options }); return registration; },
  }, assets);
  assert.equal(result, registration);
  assert.deepEqual(calls, [{ url: "https://example.org/ControlLab/service_worker.js", options: { type: "module", scope: "https://example.org/ControlLab/", updateViaCache: "none" } }]);
  assert.equal(await registerControlLabServiceWorker(undefined), null);
  await assert.rejects(() => registerControlLabServiceWorker({ async register() { throw new Error("registration failed"); } }));
  assert.equal(assets.workerUrl, "https://example.org/ControlLab/worker/pyodide_worker.js");
  assert.equal(assets.pyodideIndexUrl, "https://example.org/ControlLab/pyodide/");
  assert.equal(assets.controlLabWheel, "https://example.org/ControlLab/wheels/control_lab-1.0.0-py3-none-any.whl");
  const mainSource = fs.readFileSync(path.join(REPO_ROOT, "web/app/main.ts"), "utf8");
  assert.ok(mainSource.includes("workerUrl: options?.workerUrl ?? BROWSER_RUNTIME_ASSETS.workerUrl"));
  const html = fs.readFileSync(path.join(REPO_ROOT, "web/app/index.html"), "utf8");
  assert.ok(html.includes('href="./app/styles.css"'));
  assert.ok(html.includes('src="./app/main.js"'));
});

// ---------------------------------------------------------------------------
// 5. Overlays Semânticos e Gráficos (Valores Repetidos, Tabela Acessível, CSV)
// ---------------------------------------------------------------------------

test("Overlays semânticos (exact/sufficient/heuristic/estimated) e gráficos com valores repetidos + tabela acessível", () => {
  // Região espectral exata
  const halfPlane = createHalfPlaneDecayOverlay(0.5);
  assert.equal(halfPlane.classification, "exact");

  const discreteDisk = createDiscreteSpectralRadiusOverlay(0.95);
  assert.equal(discreteDisk.classification, "exact");

  // Região LMI cruzada deve ser sufficient e proibida como exact
  const lmiRegion = createLmiCrossRegionOverlay({ alpha: 0.2, diskRadius: 10 });
  assert.equal(lmiRegion.classification, "sufficient");
  assert.throws(
    () =>
      createRequirementOverlay({
        id: "bad-lmi",
        label: "LMI falsa",
        kind: "lmi_cross_region",
        classification: "exact",
        domain: "continuous",
        parameters: { alpha: 0.2 },
        mathematical_basis: "teste",
        geometry_hint: { shape: "half_plane", boundary_values: { max_real: -0.2 } },
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );

  // Regiões de 2ª ordem (ζ, ω_n, overshoot, T_s) são heuristic/estimated e PROIBIDAS como exact
  const dampingOverlay = createSecondOrderRegionOverlay({
    zetaMin: 0.7,
    maxOvershootPct: 5,
    classification: "heuristic",
  });
  assert.equal(dampingOverlay.classification, "heuristic");
  assert.throws(
    () =>
      createRequirementOverlay({
        id: "bad-2nd-order",
        label: "2a ordem falsa exata",
        kind: "second_order_overshoot",
        classification: "exact",
        domain: "continuous",
        parameters: { zeta_min: 0.7 },
        mathematical_basis: "teste",
        geometry_hint: { shape: "wedge", boundary_values: { theta_rad: 0.78 } },
      }),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );

  // Avaliação de polos contra overlay
  const evalOk = evaluatePolesAgainstOverlay(
    { real: [-2.0, -1.0], imag: [0.0, 0.0] },
    halfPlane,
  );
  assert.equal(evalOk.satisfied, true);
  assert.equal(evalOk.violatingIndices.length, 0);

  const evalFail = evaluatePolesAgainstOverlay(
    { real: [-2.0, -0.1], imag: [0.0, 0.0] },
    halfPlane,
  );
  assert.equal(evalFail.satisfied, false);
  assert.deepEqual(evalFail.violatingIndices, [1]);

  // Valores repetidos/constantes não produzem NaN nem divisão por zero
  const constBounds = computeSafeAxisBounds([4.25, 4.25, 4.25, 4.25]);
  assert.equal(constBounds.isConstant, true);
  assert.ok(Number.isFinite(constBounds.span) && constBounds.span > 0);

  const timeModel = buildTimeResponseChartModel({
    dt: null,
    t: [0, 0.5, 1.0],
    x: [
      [0, 0],
      [0, 0],
      [0, 0],
    ],
    u: [[5], [5], [5]],
    y: [[0], [0], [0]],
    model_revision: 2,
    project_revision: 4,
    provenance: { algorithm: "statespace.simulate_lti", lib_versions: {} },
    series_semantics: "numeric_verified",
    feedback_sign: "negative",
  });
  const timeSvg = renderTimeResponseSvg(timeModel);
  assert.ok(!timeSvg.includes("NaN"), "SVG com valores constantes não pode conter NaN");
  assert.ok(timeSvg.includes('data-model-revision="2"'));

  const pzSvg = renderPoleZeroSvg({
    kind: "pole_zero",
    chart_id: "pz-const",
    title: "Polos repetidos",
    model_revision: 2,
    project_revision: 4,
    provenance: { algorithm: "scipy.linalg.solve_continuous_are", lib_versions: {} },
    series_semantics: "numeric_verified",
    feedback_sign: "negative",
    units: { x_axis: "Re", y_axis: "Im" },
    dt: null,
    open_loop_poles: { real: [0, 0], imag: [0, 0] },
    committed_closed_loop_poles: { real: [-1, -1], imag: [0, 0] },
    preview_poles: null,
    zeros: null,
    overlays: [halfPlane, dampingOverlay],
  });
  assert.ok(!pzSvg.includes("NaN"));
  assert.ok(pzSvg.includes('data-overlay-class="exact"'));
  assert.ok(pzSvg.includes('data-overlay-class="heuristic"'));

  // Tabela acessível e exportação CSV com cabeçalho de proveniência
  const table = buildAccessibleChartTable(timeModel, 2);
  assert.equal(table.rows.length, 3);
  const tableHtml = renderAccessibleTableHtml(table);
  assert.ok(tableHtml.includes("<table") && tableHtml.includes("<thead") && tableHtml.includes("<tbody"));

  const csv = exportChartToCsv(timeModel);
  assert.ok(csv.includes("# series_semantics=numeric_verified"));
  assert.ok(csv.includes("# feedback_sign=negative"));
});

// ---------------------------------------------------------------------------
// 6. Acessibilidade WCAG 2.2 AA, Foco, Live Region, Casas Decimais e Relatório R-27
// ---------------------------------------------------------------------------

test("WCAG 2.2 AA: contraste (>=4.5:1 / >=3.0:1), toque >=44px, teclado, FocusRestorer, AriaLive, decimais sem mutação e relatório R-27", async () => {
  // Contraste em ambos os temas
  for (const theme of [STANDARD_AA_THEME, HIGH_CONTRAST_THEME]) {
    assert.ok(
      meetsWcagAA(theme.textPrimary, theme.background, "normal_text"),
      `Contraste insuficiente textPrimary/background em ${theme.mode}: ${contrastRatio(theme.textPrimary, theme.background)}`,
    );
    assert.ok(
      meetsWcagAA(theme.textSecondary, theme.surface, "normal_text"),
      `Contraste insuficiente textSecondary/surface em ${theme.mode}`,
    );
    assert.ok(
      meetsWcagAA(theme.accentText, theme.accent, "normal_text"),
      `Contraste insuficiente accentText/accent em ${theme.mode}`,
    );
    assert.ok(
      meetsWcagAA(theme.statusErrorFg, theme.statusErrorBg, "normal_text"),
      `Contraste insuficiente statusError em ${theme.mode}`,
    );
    assert.ok(
      meetsWcagAA(theme.chartClosedLoop, theme.surfaceAlt, "ui_component"),
      `Contraste insuficiente série gráfico em ${theme.mode}`,
    );
  }

  // Área de toque >= 44px
  assert.equal(MIN_TOUCH_TARGET_PX, 44);
  assert.equal(validateTouchTarget({ widthPx: 44, heightPx: 44 }).valid, true);
  assert.equal(validateTouchTarget({ widthPx: 32, heightPx: 44 }).valid, false);

  // Navegação por teclado em tablist e slider
  const tabList = PROJECT_TAB_IDS.map((id) => ({ id, label: id }));
  const tabNav1 = handleTablistKeyDown("ArrowRight", tabList, 0);
  assert.equal(tabNav1.nextIndex, 1);
  const tabNavEnd = handleTablistKeyDown("End", tabList, 0);
  assert.equal(tabNavEnd.nextIndex, PROJECT_TAB_IDS.length - 1);
  const tabNavHome = handleTablistKeyDown("Home", tabList, 4);
  assert.equal(tabNavHome.nextIndex, 0);
  assert.equal(getTabAriaAttributes("statespace", "panel-statespace", true)["aria-selected"], "true");

  const sliderCfg = { min: 0.1, max: 10, step: 0.5, value: 2.0, label: "Peso Q" };
  const sUp = handleSliderKeyDown("ArrowRight", sliderCfg);
  assert.equal(sUp.nextValue, 2.5);
  assert.equal(sUp.committed, true);
  const sEsc = handleSliderKeyDown("Escape", sliderCfg);
  assert.equal(sEsc.cancelled, true);
  assert.equal(getSliderAriaAttributes(sliderCfg, 2)["aria-valuenow"], "2");

  // FocusRestorer após modal
  const restorer = new FocusRestorer();
  let restoredCalls = 0;
  restorer.pushModalTrigger(
    {
      id: "btn-open-report",
      focus: () => {
        restoredCalls += 1;
      },
    },
    "modal-report",
  );
  const restored = restorer.popAndRestoreFocus("modal-report");
  assert.equal(restored?.id, "btn-open-report");
  assert.equal(restoredCalls, 1);

  // AriaLiveAnnouncer
  const announcer = new AriaLiveAnnouncer();
  announcer.announce("Aguardando commit", "polite", "pending_commit");
  announcer.announce("Erro dimensional", "assertive", "error");
  assert.equal(announcer.getCurrentText("polite"), "Aguardando commit");
  assert.equal(announcer.getCurrentText("assertive"), "Erro dimensional");

  // Formatação de decimais NÃO muta float64 armazenado + Comparador + Relatório R-27
  const { loaded, store, client } = createMockSetup();
  await client.init();
  try {
    const f02 = buildPlantFromFixtureJson(loaded.bCare02Raw, "plant-r27");
    const shell = new ControlLabShell({
      client,
      project_id: "proj-r27",
      lqrWorkspace: new LqrWorkspaceController({
        client,
        project_id: "proj-r27",
        plant: f02.plant,
        Q: f02.Q,
        R: f02.R,
        x0: f02.x0,
      }),
    });

    // Teclado no shell navega entre as 6 abas e fecha modal com Escape
    shell.openModal("modal-help", { id: "btn-help" });
    assert.equal(shell.getOpenModalId(), "modal-help");
    shell.handleTabKeyDown("Escape");
    assert.equal(shell.getOpenModalId(), null);
    assert.equal(shell.getFocusRestorer().getActiveFocusId(), "btn-help");

    const kbdTab = shell.handleTabKeyDown("ArrowLeft");
    assert.equal(kbdTab.handled, true);
    shell.switchTab("statespace");

    // Executa commit LQR e verifica formatação de casas decimais sem mutação float64
    const snap = await shell.getLqrWorkspace().commitCurrentDesign();
    assert.ok(snap !== null);
    const rawVal = 1.23456789012345;
    assert.equal(formatNumericDisplay(rawVal, 2), "1.23");
    assert.equal(formatNumericDisplay(rawVal, 6), "1.234568");
    assert.equal(rawVal, 1.23456789012345);

    shell.setDisplayDecimals(2);
    shell.addCommittedExperiment("Base 2 decimais");
    shell.setDisplayDecimals(6);
    const comp = shell.compareExperiments();
    assert.equal(comp.length, 1);
    assert.equal(comp[0].K_display?.[0][0], "2.000000");
    // Valor float64 interno permanece exato!
    assert.equal(shell.getLqrWorkspace().getCommittedSnapshot()?.K?.data[0], 2.0);

    const report = shell.buildScientificReport();
    assert.equal(report.project_id, "proj-r27");
    assert.equal(report.model_revision, 1);
    assert.equal(report.algorithm, "mock.certified_fixture.care");
    assert.equal(report.series_semantics, "numeric_verified");
    assert.ok("care_residual_rel" in report.residuals);
    assert.ok("numpy" in report.lib_versions);

    shell.dispose();
  } finally {
    client.dispose();
    store.close();
  }
});

// ---------------------------------------------------------------------------
// 7. Auditoria estática F8: zero Node globals, zero Python, zero duplicação de síntese
// ---------------------------------------------------------------------------

test("UI Node: adapter F7 bruto 12x3 com ref não resolvível falha fechado antes de persistir", async () => {
  const loaded = loadCertifiedFixtures();
  const store = new IndexedDBProjectStore({ idbFactory: new InMemoryIDBFactory(), dbName: "raw-incomplete-f8" });
  const client = new MockWorkerAdapter({ store, fixtures: loaded.fixturesMap });
  const f12 = buildPlantFromFixtureJson(loaded.bCare12Raw, "raw12");
  const lqr = new LqrWorkspaceController({ client, project_id: "raw12", plant: f12.plant, Q: f12.Q, R: f12.R, x0: f12.x0 });
  try {
    assert.equal(await lqr.commitCurrentDesign(), null);
    assert.equal(lqr.canExport().allowed, false);
    assert.equal((await store.getProject("raw12"))?.committed_revision ?? 0, 0);
    assert.equal((await store.listObjects("raw12")).length, 0);
  } finally { client.dispose(); store.close(); }
});

test("Guard arquitetural distingue imports Python de URLs wheel", () => {
  const pythonImport = /\b(?:from\s+control_lab(?:\.[A-Za-z_]\w*)*\s+import\b|import\s+control_lab\b)/;
  for (const source of ["import control_lab", "from control_lab.core.rpc import dispatch", "import control_lab as engine"]) {
    assert.equal(pythonImport.test(source), true, source);
  }
  for (const source of ['new URL("wheels/control_lab-1.0.0-py3-none-any.whl", base)', 'const name = "control_lab";']) {
    assert.equal(pythonImport.test(source), false, source);
  }
});

test("Auditoria F8: web/{app,charts,features} não importam Python, Node globals nem duplicam síntese CARE/Riccati", () => {
  const dirs = [
    path.join(REPO_ROOT, "web", "app"),
    path.join(REPO_ROOT, "web", "charts"),
    path.join(REPO_ROOT, "web", "features"),
  ];
  const forbiddenPatterns: Array<{ name: string; re: RegExp }> = [
    { name: "node: module import", re: /["']node:/ },
    { name: "CommonJS require", re: /\brequire\s*\(/ },
    { name: "Python control_lab import", re: /\b(?:from\s+control_lab(?:\.[A-Za-z_]\w*)*\s+import\b|import\s+control_lab\b)/ },
    { name: "SciPy Riccati solver duplication", re: /solve_continuous_are|solve_discrete_are/ },
    { name: "TypeScript enum (forbidden by erasableSyntaxOnly)", re: /^\s*(?:export\s+)?enum\s+/m },
    { name: "TypeScript namespace (forbidden by erasableSyntaxOnly)", re: /^\s*(?:export\s+)?namespace\s+/m },
  ];

  for (const dir of dirs) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const ent of entries) {
      if (!ent.isFile() || !ent.name.endsWith(".ts")) continue;
      const fullPath = path.join(dir, ent.name);
      const src = fs.readFileSync(fullPath, "utf8");
      for (const pat of forbiddenPatterns) {
        assert.equal(
          pat.re.test(src),
          false,
          `Padrão proibido (${pat.name}) encontrado em ${fullPath}`,
        );
      }
    }
  }
});

// ---------------------------------------------------------------------------
// 8. Cobertura complementar: m!=p, C!=I, feedback_sign positivo, lifecycle, buffers
// ---------------------------------------------------------------------------

test("F8-EXT-01: suporte explícito a m!=p (3 entradas, 4 saídas), C!=I, feedback_sign positivo, ciclo de vida e buffers transferíveis", async () => {
  const { loaded, store, client } = createMockSetup();
  const shell = new ControlLabShell({
    client,
    project_id: "proj-ext",
    lqrWorkspace: new LqrWorkspaceController({
      client,
      project_id: "proj-ext",
      ...(() => {
        const f12 = buildPlantFromFixtureJson(loaded.bCare12Raw, "plant-mimo-12x3");
        return { plant: f12.plant, Q: f12.Q, R: f12.R, x0: f12.x0 };
      })(),
      useTransferableBuffers: true,
      useCoalescedWorkerPreview: true,
    }),
  });

  // Antes de init, estado do motor é uninitialized
  assert.equal(shell.getEngineState(), "uninitialized");
  await client.init();
  assert.equal(shell.getEngineState(), "ready");
  assert.ok(shell.getEngineEventsLog().some((ev) => ev.type === "lifecycle" && ev.current === "ready"));

  try {
    const lqr = shell.getLqrWorkspace();
    // Commit com transferable buffers
    const committed = await lqr.commitCurrentDesign();
    assert.ok(committed !== null);
    assert.equal(committed.project_revision, 1);

    // Worker coalesced preview NÃO altera committed_revision no IndexedDB
    lqr.pointerDown("slider-coalesced");
    lqr.pointerMove({ qScale: 2.0 });
    lqr.pointerMove({ qScale: 3.0 });
    await new Promise((r) => setTimeout(r, 60));
    assert.equal((await store.getProject("proj-ext"))?.committed_revision, 1);

    // Escape no slider cancela preview preservando revisão comitada
    const escRes = await lqr.handleKeyboardSlider("Escape", "q_scale", {
      min: 0.1,
      max: 10,
      step: 0.5,
      value: 1.0,
      label: "Q",
    });
    assert.equal(escRes.handled, true);
    assert.equal(lqr.getPreviewState().active, false);

    // ArrowRight no slider executa commit autoritativo diretamente
    const arrowRes = await lqr.handleKeyboardSlider("ArrowRight", "q_scale", {
      min: 0.1,
      max: 10,
      step: 0.5,
      value: 1.0,
      label: "Q",
    });
    assert.equal(arrowRes.nextValue, 1.5);
    assert.equal(lqr.getCommittedSnapshot()?.project_revision, 2);

    // Gráfico temporal com m=3 entradas, p=4 saídas (m!=p) e feedback_sign positivo
    const multiChannelChart = buildTimeResponseChartModel({
      dt: null,
      t: [0, 0.25, 0.5],
      x: [
        new Array(12).fill(0.1),
        new Array(12).fill(0.05),
        new Array(12).fill(0.01),
      ],
      u: [
        [1.0, -0.5, 0.2],
        [0.4, -0.2, 0.1],
        [0.1, 0.0, 0.0],
      ],
      y: [
        [0.1, 0.2, 0.3, 0.4],
        [0.05, 0.1, 0.15, 0.2],
        [0.01, 0.02, 0.03, 0.04],
      ],
      input_names: ["u1", "u2", "u3"],
      output_names: ["y1", "y2", "y3", "y4"],
      model_revision: 1,
      project_revision: 2,
      provenance: committed.provenance,
      series_semantics: "numeric_verified",
      feedback_sign: "positive",
    });
    assert.equal(
      multiChannelChart.channels.filter((c) => c.group === "u").length,
      3,
    );
    assert.equal(
      multiChannelChart.channels.filter((c) => c.group === "y").length,
      4,
    );
    const svg = renderTimeResponseSvg(multiChannelChart);
    assert.ok(!svg.includes("NaN"));
    const csv = shell.exportChartCsv(multiChannelChart);
    assert.ok(csv.includes("# feedback_sign=positive"));

    // Reset do worker notifica recuperação no shell
    await client.resetWorker("teste recuperação UI");
    assert.equal(shell.getEngineState(), "ready");
    assert.ok(
      shell.getEngineEventsLog().some((ev) => ev.type === "worker_recovered"),
    );

    // Um ganho confirmado mantém o bloqueio PVM e permite a exportação de projeto existente.
    const origExecExt = client.execute.bind(client);
    client.execute = async (req, opts) => {
      const resp = await origExecExt(req, opts);
      if (req.operation === "statespace.design_lqr" && resp.result) {
        return {
          ...resp,
          result: {
            ...resp.result,
            K: {
              shape: [3, 12],
              dtype: "float64",
              order: "C",
              data: Array.from({ length: 36 }, (_, idx) => (idx + 1) * 0.05),
            },
          },
        };
      }
      return resp;
    };
    const committedWithK = await lqr.commitCurrentDesign();
    assert.ok(committedWithK?.K !== null);
    assert.ok((await shell.exportPvm()).bytes.length > 0);
    const ctrlabExt = await shell.exportCtrlLab();
    assert.equal(JSON.parse(new TextDecoder().decode(ctrlabExt.bytes)).project.controllers.length, 1);

    shell.dispose();
  } finally {
    client.dispose();
    store.close();
  }
});

test("F8-EXT-02: contraste completo WCAG 2.2 AA, ToolDescriptor HTML (<select>/number), teclado preservando Q, analyzeOpenLoop concorrente e .pvm discreto", async () => {
  for (const theme of [STANDARD_AA_THEME, HIGH_CONTRAST_THEME]) {
    assert.ok(meetsWcagAA(theme.textPrimary, theme.surface, "normal_text"));
    assert.ok(meetsWcagAA(theme.textPrimary, theme.surfaceAlt, "normal_text"));
    assert.ok(meetsWcagAA(theme.textSecondary, theme.background, "normal_text"));
    assert.ok(meetsWcagAA(theme.statusSuccessFg, theme.statusSuccessBg, "normal_text"));
    assert.ok(meetsWcagAA(theme.statusWarningFg, theme.statusWarningBg, "normal_text"));
    assert.ok(meetsWcagAA(theme.statusInfoFg, theme.statusInfoBg, "normal_text"));
    assert.ok(meetsWcagAA(theme.border, theme.surface, "ui_component"));
    assert.ok(meetsWcagAA(theme.chartOpenLoop, theme.surfaceAlt, "ui_component"));
    assert.ok(meetsWcagAA(theme.chartPreview, theme.surfaceAlt, "ui_component"));
    assert.ok(meetsWcagAA(theme.chartOverlayExact, theme.surfaceAlt, "ui_component"));
    assert.ok(meetsWcagAA(theme.chartOverlaySufficient, theme.surfaceAlt, "ui_component"));
    assert.ok(meetsWcagAA(theme.chartOverlayHeuristic, theme.surfaceAlt, "ui_component"));
  }

  const { store, client } = createMockSetup({ latencyMs: 20 });
  await client.init();

  try {
    const tabs = new ProjectTabsController({ client });
    const ssVm = tabs.getTabViewModel("statespace");
    const lqrToolVm = ssVm.tools.find((t) => t.toolId === "statespace.design_lqr");
    assert.ok(lqrToolVm);
    const lqrHtml = lqrToolVm.toHtml();
    assert.ok(lqrHtml.includes("<select "), "Campos select devem renderizar <select>");
    assert.ok(lqrHtml.includes('type="number"'), "Campos numéricos devem renderizar type=number");
    assert.ok(lqrHtml.includes('data-action="execute-tool"'));

    // Matriz Q não-identidade (diag(10, 1)) deve manter proporção em handleKeyboardSlider
    const customQ: RealTensor = { shape: [2, 2], dtype: "float64", order: "C", data: [10, 0, 0, 1] };
    const shell = new ControlLabShell({
      client,
      project_id: "proj-ext2",
      lqrWorkspace: new LqrWorkspaceController({
        client,
        project_id: "proj-ext2",
        plant: createDoubleIntegratorPlant(),
        Q: customQ,
      }),
    });
    const lqr = shell.getLqrWorkspace();
    await lqr.commitCurrentDesign();

    const kRes = await lqr.handleKeyboardSlider("ArrowRight", "q_scale", {
      min: 0.1,
      max: 20,
      step: 0.5,
      value: 1.0,
      label: "Q",
    });
    assert.equal(kRes.nextValue, 1.5);
    assert.equal(lqr.getCurrentScaleFactors().qScale, 1.5);
    assert.equal(lqr.getWeights().Q.data[0], 15.0);
    assert.equal(lqr.getWeights().Q.data[3], 1.5);

    // analyzeOpenLoop paralelo NÃO invalida nem supera commitCurrentDesign em voo
    const commitInFlight = lqr.commitCurrentDesign();
    const analyzeRes = await lqr.analyzeOpenLoop();
    const committed = await commitInFlight;
    assert.ok(committed !== null);
    assert.equal(analyzeRes.project_id, "proj-ext2");
    assert.equal(lqr.isPendingCommit(), false);

    // A contenção também se aplica ao modelo discreto.
    const discretePlant = validateCanonicalStateSpace({
      ...createDoubleIntegratorPlant(),
      id: "plant-discrete",
      revision: 2,
      dt: 0.05,
    });
    lqr.updatePlant(discretePlant);
    await lqr.commitCurrentDesign();
    assert.ok((await shell.exportPvm()).bytes.length > 0);

    const report = shell.buildScientificReport();
    assert.equal(report.method, "dare");
    assert.equal(report.parameters.dt, 0.05);

    // Overlay lmi_cross_region inclui disco (A) e reta de semiplano (L) no SVG
    lqr.addOverlay(createLmiCrossRegionOverlay({ alpha: 0.5, diskRadius: 8 }));
    const pzSvg = renderPoleZeroSvg(lqr.buildPoleZeroChart());
    assert.ok(pzSvg.includes('data-overlay-class="sufficient"'));

    shell.dispose();
  } finally {
    client.dispose();
    store.close();
  }
});

test("F8-EXT-03: mountControlLabApp mantém identidade do slider durante pointermove, atualiza aria-disabled e restaura foco ao fechar modal", async () => {
  interface MockEl {
    id: string;
    tagName: string;
    attrs: Record<string, string>;
    listeners: Map<string, Array<(ev: unknown) => void>>;
    children: MockEl[];
    disabled: boolean;
    value: string;
    textContent: string;
    _innerHTML: string;
    focused: boolean;
    ownerDocument: { activeElement: MockEl | null };
    setAttribute(k: string, v: string): void;
    getAttribute(k: string): string | null;
    removeAttribute(k: string): void;
    addEventListener(type: string, fn: (ev: unknown) => void): void;
    dispatchEvent(type: string, ev?: Record<string, unknown>): void;
    querySelector(sel: string): MockEl | null;
    querySelectorAll(sel: string): MockEl[];
    getBoundingClientRect(): { left: number; width: number; top: number; height: number };
    setPointerCapture(id: number): void;
    hasPointerCapture(id: number): boolean;
    releasePointerCapture(id: number): void;
    focus(): void;
    closest(sel: string): MockEl | null;
  }

  const doc = { activeElement: null as MockEl | null };
  const makeEl = (tagName: string, id = "", attrs: Record<string, string> = {}): MockEl => {
    const el: MockEl = {
      id,
      tagName: tagName.toUpperCase(),
      attrs: { ...attrs },
      listeners: new Map(),
      children: [],
      disabled: "disabled" in attrs,
      value: attrs.value ?? "",
      textContent: "",
      _innerHTML: "",
      focused: false,
      ownerDocument: doc,
      setAttribute(k, v) {
        this.attrs[k] = v;
        if (k === "id") this.id = v;
      },
      getAttribute(k) {
        return k in this.attrs ? this.attrs[k] : null;
      },
      removeAttribute(k) {
        delete this.attrs[k];
      },
      addEventListener(type, fn) {
        const list = this.listeners.get(type) ?? [];
        list.push(fn);
        this.listeners.set(type, list);
      },
      dispatchEvent(type, ev = {}) {
        const eventObj = {
          target: this,
          currentTarget: this,
          preventDefault() {},
          ...ev,
        };
        for (const fn of this.listeners.get(type) ?? []) {
          fn(eventObj);
        }
      },
      querySelector(sel) {
        return this.querySelectorAll(sel)[0] ?? null;
      },
      querySelectorAll(sel) {
        const out: MockEl[] = [];
        const match = (cand: MockEl): boolean => {
          if (sel.startsWith("#")) return cand.id === sel.slice(1);
          const attrMatch = /^\[([^=\]]+)="([^"]*)"\]$/.exec(sel);
          if (attrMatch) return cand.attrs[attrMatch[1]] === attrMatch[2];
          return false;
        };
        const walk = (node: MockEl) => {
          for (const ch of node.children) {
            if (match(ch)) out.push(ch);
            walk(ch);
          }
        };
        walk(this);
        return out;
      },
      getBoundingClientRect() {
        return { left: 0, width: 200, top: 0, height: 44 };
      },
      setPointerCapture() {},
      hasPointerCapture() {
        return false;
      },
      releasePointerCapture() {},
      focus() {
        this.focused = true;
        doc.activeElement = this;
      },
      closest(sel) {
        const attrMatch = /^\[([^=\]]+)="([^"]*)"\]$/.exec(sel);
        if (attrMatch && this.attrs[attrMatch[1]] === attrMatch[2]) return this;
        return null;
      },
    };
    return el;
  };

  const root = makeEl("div", "controllab-app");
  Object.defineProperty(root, "innerHTML", {
    get() {
      return root._innerHTML;
    },
    set(html: string) {
      root._innerHTML = html;
      root.children = [];
      const tagRe = /<(button|div|span|input|select|h2|p|strong|main|section|nav|header)\b([^>]*)>/gi;
      let m: RegExpExecArray | null;
      while ((m = tagRe.exec(html)) !== null) {
        const tag = m[1];
        const rawAttrs = m[2];
        const attrs: Record<string, string> = {};
        const attrRe = /([a-zA-Z0-9_-]+)="([^"]*)"/g;
        let am: RegExpExecArray | null;
        while ((am = attrRe.exec(rawAttrs)) !== null) {
          attrs[am[1]] = am[2];
        }
        root.children.push(makeEl(tag, attrs.id ?? "", attrs));
      }
    },
  });

  const { store, client } = createMockSetup({ latencyMs: 10 });
  await client.init();

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-dom-mount",
  });
  try {
    const sliderBefore = root.querySelector("#lqr-q-slider");
    const exportPvmBtn = root.querySelector("#btn-export-pvm");
    const modalEl = root.querySelector("#controllab-export-modal");
    const modalCloseBtn = root.querySelector("#export-modal-close");
    assert.ok(sliderBefore && exportPvmBtn && modalEl && modalCloseBtn);

    // Sem commit inicial, botão de exportação começa desabilitado
    assert.equal(exportPvmBtn.disabled, true);
    assert.equal(exportPvmBtn.getAttribute("aria-disabled"), "true");

    // Arraste de ponteiro no slider preserva o elemento DOM original!
    sliderBefore.dispatchEvent("pointerdown", { pointerId: 1 });
    for (let i = 1; i <= 5; i += 1) {
      sliderBefore.dispatchEvent("pointermove", { pointerId: 1, clientX: i * 25 });
      assert.strictEqual(root.querySelector("#lqr-q-slider"), sliderBefore);
      assert.equal(exportPvmBtn.disabled, true);
    }

    sliderBefore.dispatchEvent("pointerup", { pointerId: 1 });
    // Aguardar término do commit disparado em pointerup
    await new Promise((r) => setTimeout(r, 40));

    assert.equal(app.shell.getLqrWorkspace().isPendingCommit(), false);
    assert.equal(exportPvmBtn.disabled, false);
    assert.equal(exportPvmBtn.getAttribute("aria-disabled"), null);

    // Abrir e fechar modal deve restaurar foco no botão disparador
    const exportGainsBtn = root.querySelector("#btn-export-gains");
    assert.ok(exportGainsBtn);
    exportGainsBtn.focus();
    exportGainsBtn.dispatchEvent("click");
    assert.equal(modalEl.getAttribute("hidden"), null);
    assert.equal(app.shell.getOpenModalId(), "modal-export");

    modalCloseBtn.dispatchEvent("click");
    assert.equal(modalEl.getAttribute("hidden"), "true");
    assert.equal(app.shell.getOpenModalId(), null);
    assert.strictEqual(doc.activeElement, exportGainsBtn);
  } finally {
    app.destroy();
    store.close();
  }
});

test("F8-EXT-04: aderência aos schemas (.ctrlab, StateFeedbackController, StateSpace, .pvm), contraste WCAG total, CSV alta precisão, teclado durante preview e DOM completo", async () => {
  // 1. Contraste WCAG 2.2 AA completo em todos os tokens restantes
  for (const theme of [STANDARD_AA_THEME, HIGH_CONTRAST_THEME]) {
    assert.ok(meetsWcagAA(theme.statusErrorFg, theme.statusErrorBg, "normal_text"));
    assert.ok(meetsWcagAA(theme.accentText, theme.accent, "normal_text"));
    assert.ok(meetsWcagAA(theme.chartClosedLoop, theme.surfaceAlt, "ui_component"));
    assert.ok(meetsWcagAA(theme.chartAxis, theme.surfaceAlt, "ui_component"));
  }

  const { loaded, store, client } = createMockSetup({ latencyMs: 10 });
  await client.init();

  const origExecSchema = client.execute.bind(client);
  client.execute = async (req, opts) => {
    const resp = await origExecSchema(req, opts);
    if (req.operation === "statespace.design_lqr" && resp.result && !resp.result.K) {
      return {
        ...resp,
        result: {
          ...resp.result,
          K: {
            shape: [3, 12],
            dtype: "float64",
            order: "C",
            data: Array.from({ length: 36 }, (_, idx) => (idx + 1) * 0.1),
          },
        },
      };
    }
    return resp;
  };

  try {
    const f12 = buildPlantFromFixtureJson(loaded.bCare12Raw, "plant-schema-check");
    const shell = new ControlLabShell({
      client,
      project_id: "proj-schema-check",
      lqrWorkspace: new LqrWorkspaceController({
        client,
        project_id: "proj-schema-check",
        plant: f12.plant,
        Q: f12.Q,
        R: f12.R,
        x0: f12.x0,
      }),
    });
    const lqr = shell.getLqrWorkspace();
    await lqr.commitCurrentDesign();

    // 2. Transporte do projeto canônico para o motor, sem gerador ZIP na UI.
    const ctrlabPkg = await shell.exportCtrlLab();
    assert.equal(ctrlabPkg.media_type, "application/zip");
    const projectPayload = JSON.parse(new TextDecoder().decode(ctrlabPkg.bytes)).project;
    assert.deepEqual(projectPayload.models[0], lqr.getPlant());
    assert.equal(projectPayload.controllers[0].kind, "StateFeedbackController");
    assert.deepEqual(projectPayload.controllers[0].K, lqr.getCommittedSnapshot()?.K);
    assert.equal(projectPayload.experiments[0].kind, "Experiment");
    assert.ok((await shell.exportPvm()).bytes.length > 0);

    // 4. exportChartCsv preserva precisão total mesmo com displayDecimals=2
    shell.setDisplayDecimals(2);
    const precisionChart = buildTimeResponseChartModel({
      dt: null,
      t: [0, 0.123456789012],
      x: [
        [0, 0],
        [0.123456789012, 0],
      ],
      u: [[0], [0]],
      y: [[1.987654321098], [0.543210987654]],
      model_revision: 1,
      project_revision: 1,
      provenance: { algorithm: "scipy.linalg.solve_continuous_are", lib_versions: {} },
      series_semantics: "numeric_verified",
      feedback_sign: "negative",
    });
    const fullCsv = shell.exportChartCsv(precisionChart);
    assert.ok(fullCsv.includes("1.987654321098"));
    assert.ok(fullCsv.includes("0.123456789012"));

    // 5. Teclado durante Fast-Preview ativo limpa estado de preview e comita normalmente
    lqr.pointerDown("slider-kbd-preview");
    lqr.pointerMove({ qScale: 2.0 });
    assert.equal(lqr.getPreviewState().active, true);
    const kbdAfterDrag = await lqr.handleKeyboardSlider("ArrowRight", "q_scale", {
      min: 0.1,
      max: 20,
      step: 0.5,
      value: 2.0,
      label: "Q",
    });
    assert.equal(kbdAfterDrag.handled, true);
    assert.equal(kbdAfterDrag.nextValue, 2.5);
    assert.equal(lqr.getPreviewState().active, false);
    assert.equal(lqr.isPendingCommit(), false);
    assert.equal(lqr.canExport().allowed, true);

    // 6. SVG inclui camada axis-ticks e legend com formatação de casas decimais
    const pzSvg = renderPoleZeroSvg(lqr.buildPoleZeroChart(), { decimals: 3 });
    assert.ok(pzSvg.includes('data-layer="axis-ticks"'));
    assert.ok(pzSvg.includes('data-layer="legend"'));

    shell.dispose();
  } finally {
    client.dispose();
    store.close();
  }
});

test("F8-EXT-05: mountControlLabApp renderiza tabela temporal, painel R-27, comparador de experimentos e executa ferramenta auxiliar sem sobrescrever snapshot LQR", async () => {
  interface MockNode {
    id: string;
    tagName: string;
    attrs: Record<string, string>;
    listeners: Map<string, Array<(ev: unknown) => void>>;
    children: MockNode[];
    disabled: boolean;
    value: string;
    textContent: string;
    _innerHTML: string;
    ownerDocument: { activeElement: MockNode | null };
    setAttribute(k: string, v: string): void;
    getAttribute(k: string): string | null;
    removeAttribute(k: string): void;
    addEventListener(type: string, fn: (ev: unknown) => void): void;
    dispatchEvent(type: string, ev?: Record<string, unknown>): void;
    querySelector(sel: string): MockNode | null;
    querySelectorAll(sel: string): MockNode[];
    getBoundingClientRect(): { left: number; width: number; top: number; height: number };
    focus(): void;
    closest(sel: string): MockNode | null;
  }

  const doc = { activeElement: null as MockNode | null };
  const parseHtmlInto = (target: MockNode, html: string): void => {
    target._innerHTML = html;
    target.children = [];
    const tagRe = /<(button|div|span|input|select|h2|h3|p|strong|main|section|nav|header|article|table|tr|th|td)\b([^>]*)>/gi;
    let m: RegExpExecArray | null;
    while ((m = tagRe.exec(html)) !== null) {
      const attrs: Record<string, string> = {};
      const attrRe = /([a-zA-Z0-9_-]+)="([^"]*)"/g;
      let am: RegExpExecArray | null;
      while ((am = attrRe.exec(m[2])) !== null) {
        attrs[am[1]] = am[2];
      }
      target.children.push(makeNode(m[1], attrs.id ?? "", attrs));
    }
  };
  const makeNode = (tagName: string, id = "", attrs: Record<string, string> = {}): MockNode => {
    const el: MockNode = {
      id,
      tagName: tagName.toUpperCase(),
      attrs: { ...attrs },
      listeners: new Map(),
      children: [],
      disabled: "disabled" in attrs,
      value: attrs.value ?? "",
      textContent: "",
      _innerHTML: "",
      ownerDocument: doc,
      setAttribute(k, v) {
        this.attrs[k] = v;
        if (k === "id") this.id = v;
      },
      getAttribute(k) {
        return k in this.attrs ? this.attrs[k] : null;
      },
      removeAttribute(k) {
        delete this.attrs[k];
      },
      addEventListener(type, fn) {
        const list = this.listeners.get(type) ?? [];
        list.push(fn);
        this.listeners.set(type, list);
      },
      dispatchEvent(type, ev = {}) {
        const eventObj = {
          target: this,
          currentTarget: this,
          preventDefault() {},
          ...ev,
        };
        for (const fn of this.listeners.get(type) ?? []) {
          fn(eventObj);
        }
      },
      querySelector(sel) {
        return this.querySelectorAll(sel)[0] ?? null;
      },
      querySelectorAll(sel) {
        const out: MockNode[] = [];
        const match = (cand: MockNode): boolean => {
          if (sel.startsWith("#")) return cand.id === sel.slice(1);
          const doubleAttr = /^\[([^=\]]+)="([^"]*)"\]\[([^=\]]+)="([^"]*)"\]$/.exec(sel);
          if (doubleAttr) {
            return (
              cand.attrs[doubleAttr[1]] === doubleAttr[2] &&
              cand.attrs[doubleAttr[3]] === doubleAttr[4]
            );
          }
          const attrMatch = /^\[([^=\]]+)="([^"]*)"\]$/.exec(sel);
          if (attrMatch) return cand.attrs[attrMatch[1]] === attrMatch[2];
          if (sel === `[data-tool-id]` || sel === "[data-param-name]") {
            return sel.slice(1, -1) in cand.attrs;
          }
          return false;
        };
        const walk = (node: MockNode) => {
          for (const ch of node.children) {
            if (match(ch)) out.push(ch);
            walk(ch);
          }
        };
        walk(this);
        return out;
      },
      getBoundingClientRect() {
        return { left: 0, width: 200, top: 0, height: 44 };
      },
      focus() {
        doc.activeElement = this;
      },
      closest(sel) {
        const attrMatch = /^\[([^=\]]+)="([^"]*)"\]$/.exec(sel);
        if (attrMatch && this.attrs[attrMatch[1]] === attrMatch[2]) return this;
        return null;
      },
    };
    Object.defineProperty(el, "innerHTML", {
      get() {
        return el._innerHTML;
      },
      set(html: string) {
        parseHtmlInto(el, html);
      },
    });
    return el;
  };

  const root = makeNode("div", "controllab-app");
  const { store, client } = createMockSetup({ latencyMs: 10 });
  await client.init();

  const origExecute = client.execute.bind(client);
  let injectTimeResponse = false;
  client.execute = async (request, options) => {
    const resp = await origExecute(request, options);
    if (
      injectTimeResponse &&
      request.operation === "statespace.design_lqr" &&
      resp.status === "success" &&
      resp.result
    ) {
      return {
        ...resp,
        result: {
          ...resp.result,
          time_response: {
            t: [0, 0.5, 1.0],
            x: [
              [1, 0],
              [0.45, -0.35],
              [0.12, -0.2],
            ],
            u: [[-2], [-0.2], [0.36]],
            y: [[1], [0.45], [0.12]],
          },
        },
      };
    }
    return resp;
  };

  const app = mountControlLabApp(root as unknown as HTMLElement, {
    client,
    project_id: "proj-ext5-dom",
  });
  try {
    const commitBtn = root.querySelector('[data-action="commit-lqr"]');
    const saveExpBtn = root.querySelector("#btn-save-experiment");
    const diagPanel = root.querySelector("#lqr-diagnostics-panel");
    const pzTableSlot = root.querySelector("#pz-table-slot");
    const timeChartSlot = root.querySelector("#time-chart-slot");
    const timeTableSlot = root.querySelector("#time-table-slot");
    const compareSlot = root.querySelector("#experiments-compare-slot");
    const toolsSlot = root.querySelector("#controllab-tools-slot");
    assert.ok(
      commitBtn &&
        saveExpBtn &&
        diagPanel &&
        pzTableSlot &&
        timeChartSlot &&
        timeTableSlot &&
        compareSlot &&
        toolsSlot,
    );

    commitBtn.dispatchEvent("click");
    await new Promise((r) => setTimeout(r, 40));

    assert.ok(diagPanel._innerHTML.includes("mock.certified_fixture.care"));
    assert.ok(pzTableSlot._innerHTML.includes("<table"));
    assert.ok(timeTableSlot._innerHTML.includes("Sem trajetória temporal comitada."));

    injectTimeResponse = true;
    commitBtn.dispatchEvent("click");
    await new Promise((r) => setTimeout(r, 40));
    assert.ok(timeChartSlot._innerHTML.includes('data-chart-kind="time_response"'));
    assert.ok(timeTableSlot._innerHTML.includes("<table"));

    saveExpBtn.dispatchEvent("click");
    assert.equal(app.shell.listExperiments().length, 1);
    assert.ok(compareSlot._innerHTML.includes("Exp. Rev 2"));

    const persistedBeforeTool = await store.getProject("proj-ext5-dom");
    const analyzeBtn = toolsSlot.querySelector('[data-action="execute-tool"][data-tool-id="statespace.analyze"]');
    assert.ok(analyzeBtn);
    toolsSlot.dispatchEvent("click", { target: analyzeBtn });
    await new Promise((r) => setTimeout(r, 40));

    // Execução de ferramenta auxiliar NÃO pode sobrescrever o snapshot LQR comitado no IndexedDB
    const persistedAfterTool = await store.getProject("proj-ext5-dom");
    assert.deepEqual(
      persistedAfterTool?.last_committed_result,
      persistedBeforeTool?.last_committed_result,
    );
    const analyzeRecord =
      app.shell.getTabsController().getTabViewModel("statespace").lastExecutionByTool["statespace.analyze"];
    assert.ok(analyzeRecord);
    assert.equal(analyzeRecord.response.status, "success");
  } finally {
    app.destroy();
    store.close();
  }
});

test("F8-EXT-06: B3.1 cancelDrag durante registerObject, B3.2 updateWeights invalida exportação, B3.4 x0 DIMENSION_MISMATCH, axis-ticks/chart-legend/borda 0+0j, textarea/shape_hint/simulate_lti e apply-plant/apply-weights/save-experiment em main.ts", async () => {
  const { store, client } = createMockSetup({ latencyMs: 10 });
  await client.init();

  try {
    // 1. B3.4: validateInitialStateTensor rejeita x0 com shape incompatível com n
    assert.throws(
      () =>
        validateInitialStateTensor(
          { shape: [5, 1], dtype: "float64", order: "C", data: [1, 0, 0, 0, 0] },
          2,
        ),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "DIMENSION_MISMATCH",
    );
    assert.throws(
      () =>
        new LqrWorkspaceController({
          client,
          project_id: "proj-b34",
          plant: createDoubleIntegratorPlant(),
          x0: { shape: [3, 1], dtype: "float64", order: "C", data: [1, 0, 0] },
        }),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "DIMENSION_MISMATCH",
    );

    const shell = new ControlLabShell({
      client,
      project_id: "proj-b3",
      lqrWorkspace: new LqrWorkspaceController({
        client,
        project_id: "proj-b3",
        plant: createDoubleIntegratorPlant(),
      }),
    });
    const lqr = shell.getLqrWorkspace();

    const firstCommit = await lqr.commitCurrentDesign();
    assert.ok(firstCommit !== null);
    assert.equal(firstCommit.project_revision, 1);
    assert.equal(lqr.canExport().allowed, true);

    // 2. B3.2: updateWeights invalida controlador quando committedSnapshot !== null
    lqr.updateWeights({
      Q: { shape: [2, 2], dtype: "float64", order: "C", data: [4, 0, 0, 4] },
    });
    assert.equal(lqr.isControllerInvalidated(), true);
    assert.equal(lqr.canExport().allowed, false);
    assert.throws(
      () => shell.exportPvm(),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
    );
    assert.throws(
      () =>
        lqr.updateWeights({
          x0: { shape: [4, 1], dtype: "float64", order: "C", data: [1, 0, 0, 0] },
        }),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "DIMENSION_MISMATCH",
    );

    // Recalcular restaura permissão de exportação
    const secondCommit = await lqr.commitCurrentDesign();
    assert.ok(secondCommit !== null);
    assert.equal(lqr.isControllerInvalidated(), false);
    assert.equal(lqr.canExport().allowed, true);

    // 3. B3.1: cancelDrag durante registerObject (antes de client.execute) aborta commit!
    const origRegister = client.registerObject.bind(client);
    let executeCalledDuringCancel = false;
    const origExec = client.execute.bind(client);
    client.registerObject = async (...args) => {
      await new Promise((r) => setTimeout(r, 25));
      return origRegister(...args);
    };
    client.execute = async (req, opts) => {
      executeCalledDuringCancel = true;
      return origExec(req, opts);
    };

    const pCommit = lqr.commitCurrentDesign();
    assert.equal(lqr.isPendingCommit(), true);
    await lqr.cancelDrag();
    assert.equal(lqr.isPendingCommit(), false);
    const resCancelledDuringReg = await pCommit;
    assert.equal(executeCalledDuringCancel, false);
    assert.equal(resCancelledDuringReg?.project_revision, 2);

    client.registerObject = origRegister;
    client.execute = origExec;

    // 4. Gráficos: axis-ticks, chart-legend e classificação unificada de estabilidade (0+0j marginal -> diamond, >0 instável -> cross)
    assert.equal(classifyPoleStability(-0.5, 0, null).label, "Estável");
    assert.equal(classifyPoleStability(0, 0, null).label, "Marginal / Borda");
    assert.equal(classifyPoleStability(0.5, 0, null).label, "Instável");
    assert.equal(classifyPoleStability(0.5, 0, 0.1).label, "Estável");
    assert.equal(classifyPoleStability(1.0, 0, 0.1).label, "Marginal / Borda");
    assert.equal(classifyPoleStability(1.2, 0, 0.1).label, "Instável");

    const pzChartModel = lqr.buildPoleZeroChart();
    pzChartModel.open_loop_poles = { real: [0, 0.5, -1.0], imag: [0, 0, 0] };
    const pzSvg = renderPoleZeroSvg(pzChartModel);
    assert.ok(pzSvg.includes('<g class="axis-ticks"'));
    assert.ok(pzSvg.includes('<g class="chart-legend"'));
    assert.ok(pzSvg.includes('data-stability="marginal"'));
    assert.ok(pzSvg.includes('data-stability="unstable"'));
    const pzTable = buildAccessibleChartTable(pzChartModel, 3);
    assert.equal(pzTable.rows[0][4], "Marginal / Borda");
    assert.equal(pzTable.rows[1][4], "Instável");
    assert.equal(pzTable.rows[2][4], "Estável");

    const timeChartModel = buildTimeResponseChartModel({
      dt: null,
      t: [0, 1],
      y: [[1], [0.5]],
      model_revision: 1,
      project_revision: 2,
      provenance: null,
      series_semantics: "numeric_verified",
    });
    const timeSvg = renderTimeResponseSvg(timeChartModel);
    assert.ok(timeSvg.includes('<g class="axis-ticks"'));
    assert.ok(timeSvg.includes('<g class="chart-legend"'));

    // 5. ToolDescriptor (<textarea>, shape_hint) e statespace.simulate_lti no catálogo
    const ssVm = shell.getTabsController().getTabViewModel("statespace");
    const simToolVm = ssVm.tools.find((t) => t.toolId === "statespace.simulate_lti");
    assert.ok(simToolVm, "Catálogo deve incluir statespace.simulate_lti na aba statespace");
    const simHtml = simToolVm.toHtml();
    assert.ok(simHtml.includes("<textarea "), "Parâmetros vector/matrix/json devem usar <textarea>");
    assert.ok(simHtml.includes("[n, 1]"), "HTML deve exibir shape_hint quando presente");

    // 6. main.ts: apply-plant, apply-weights, save-experiment e apresentação de erro em #controllab-error-slot
    interface SimpleEl {
      id: string;
      tagName: string;
      attrs: Record<string, string>;
      listeners: Map<string, Array<(ev: unknown) => void>>;
      children: SimpleEl[];
      disabled: boolean;
      value: string;
      textContent: string;
      _innerHTML: string;
      ownerDocument: { activeElement: SimpleEl | null };
      setAttribute(k: string, v: string): void;
      getAttribute(k: string): string | null;
      removeAttribute(k: string): void;
      addEventListener(type: string, fn: (ev: unknown) => void): void;
      dispatchEvent(type: string, ev?: Record<string, unknown>): void;
      querySelector(sel: string): SimpleEl | null;
      querySelectorAll(sel: string): SimpleEl[];
      getBoundingClientRect(): { left: number; width: number; top: number; height: number };
      focus(): void;
      closest(sel: string): SimpleEl | null;
    }
    const doc = { activeElement: null as SimpleEl | null };
    const parseHtml = (target: SimpleEl, html: string): void => {
      target._innerHTML = html;
      target.children = [];
      const tagRe = /<(button|div|span|input|textarea|select|h2|h3|p|strong|main|section|nav|header|article|table|tr|th|td)\b([^>]*)>/gi;
      let m: RegExpExecArray | null;
      while ((m = tagRe.exec(html)) !== null) {
        const attrs: Record<string, string> = {};
        const attrRe = /([a-zA-Z0-9_-]+)="([^"]*)"/g;
        let am: RegExpExecArray | null;
        while ((am = attrRe.exec(m[2])) !== null) {
          attrs[am[1]] = am[2];
        }
        target.children.push(createEl(m[1], attrs.id ?? "", attrs));
      }
    };
    const createEl = (tagName: string, id = "", attrs: Record<string, string> = {}): SimpleEl => {
      const el: SimpleEl = {
        id,
        tagName: tagName.toUpperCase(),
        attrs: { ...attrs },
        listeners: new Map(),
        children: [],
        disabled: "disabled" in attrs,
        value: attrs.value ?? "",
        textContent: "",
        _innerHTML: "",
        ownerDocument: doc,
        setAttribute(k, v) {
          this.attrs[k] = v;
          if (k === "id") this.id = v;
        },
        getAttribute(k) {
          return k in this.attrs ? this.attrs[k] : null;
        },
        removeAttribute(k) {
          delete this.attrs[k];
        },
        addEventListener(type, fn) {
          const list = this.listeners.get(type) ?? [];
          list.push(fn);
          this.listeners.set(type, list);
        },
        dispatchEvent(type, ev = {}) {
          const eventObj = { target: this, currentTarget: this, preventDefault() {}, ...ev };
          for (const fn of this.listeners.get(type) ?? []) fn(eventObj);
        },
        querySelector(sel) {
          return this.querySelectorAll(sel)[0] ?? null;
        },
        querySelectorAll(sel) {
          const out: SimpleEl[] = [];
          const match = (cand: SimpleEl): boolean => {
            if (sel.startsWith("#")) return cand.id === sel.slice(1);
            const attrMatch = /^\[([^=\]]+)="([^"]*)"\]$/.exec(sel);
            if (attrMatch) return cand.attrs[attrMatch[1]] === attrMatch[2];
            return false;
          };
          const walk = (node: SimpleEl) => {
            for (const ch of node.children) {
              if (match(ch)) out.push(ch);
              walk(ch);
            }
          };
          walk(this);
          return out;
        },
        getBoundingClientRect() {
          return { left: 0, width: 200, top: 0, height: 44 };
        },
        focus() {
          doc.activeElement = this;
        },
        closest(sel) {
          const attrMatch = /^\[([^=\]]+)="([^"]*)"\]$/.exec(sel);
          if (attrMatch && this.attrs[attrMatch[1]] === attrMatch[2]) return this;
          return null;
        },
      };
      Object.defineProperty(el, "innerHTML", {
        get() {
          return el._innerHTML;
        },
        set(html: string) {
          parseHtml(el, html);
        },
      });
      return el;
    };

    const domRoot = createEl("div", "controllab-app");
    const mounted = mountControlLabApp(domRoot as unknown as HTMLElement, {
      client,
      project_id: "proj-dom-actions",
    });

    const applyPlantBtn = domRoot.querySelector('[data-action="apply-plant"]');
    const applyWeightsBtn = domRoot.querySelector('[data-action="apply-weights"]');
    const saveExpBtn = domRoot.querySelector('[data-action="save-experiment"]');
    const exportPvmBtn = domRoot.querySelector('[data-action="export-pvm"]');
    const errorSlot = domRoot.querySelector("#controllab-error-slot");
    assert.ok(applyPlantBtn && applyWeightsBtn && saveExpBtn && exportPvmBtn && errorSlot);

    // Tentar exportar antes de commit apresenta erro no #controllab-error-slot
    exportPvmBtn.dispatchEvent("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.ok(errorSlot._innerHTML.includes("VALIDATION_ERROR"));

    // apply-plant incrementa model_revision
    const revBefore = mounted.shell.getLqrWorkspace().getPlant().revision;
    applyPlantBtn.dispatchEvent("click");
    assert.equal(mounted.shell.getLqrWorkspace().getPlant().revision, revBefore + 1);

    // apply-weights atualiza pesos
    const weightsInput = domRoot.querySelector("#lqr-weights-json");
    assert.ok(weightsInput);
    weightsInput.value = JSON.stringify({
      Q: { shape: [2, 2], dtype: "float64", order: "C", data: [2, 0, 0, 2] },
    });
    applyWeightsBtn.dispatchEvent("click");
    assert.equal(mounted.shell.getLqrWorkspace().getWeights().Q.data[0], 2);

    mounted.destroy();
    shell.dispose();
  } finally {
    client.dispose();
    store.close();
  }
});








test("AUD-019/020/021 Node transport: bytes canônicos, metadados inertes e reabertura sem recálculo", async () => {
  const { store, client } = createMockSetup();
  await client.init();
  const projectId = 'projeto\r\n"citação" Ω';
  const shell = new ControlLabShell({ client, project_id: projectId });
  try {
    await shell.getLqrWorkspace().commitCurrentDesign();
    const original = shell.getLqrWorkspace().getCommittedSnapshot();
    const originalPlant = shell.getLqrWorkspace().getPlant();
    const file = await shell.exportCtrlLab();
    const pvm = await shell.exportPvm();
    assert.equal(pvm.media_type, "application/json");
    assert.equal(pvm.filename.includes(projectId), false);
    const request = JSON.parse(new TextDecoder().decode(pvm.bytes));
    assert.equal(request.name, "ControlLab LQR");
    assert.equal("codeContext" in request, false);
    await shell.importCtrlLab(file.bytes);
    assert.deepEqual(shell.getLqrWorkspace().getPlant(), originalPlant);
    assert.deepEqual(shell.getLqrWorkspace().getCommittedSnapshot(), original);
    let releaseRead!: (bytes: Uint8Array) => void;
    const read = new Promise<Uint8Array>((resolve) => { releaseRead = resolve; });
    const importing = shell.importCtrlLab(read);
    assert.equal(shell.getLqrWorkspace().canExport().allowed, false);
    assert.throws(() => shell.getLqrWorkspace().updatePlant(originalPlant), ControlLabBridgeError);
    assert.throws(() => shell.getLqrWorkspace().updateWeights({ Q: shell.getLqrWorkspace().getWeights().Q }), ControlLabBridgeError);
    await assert.rejects(shell.importCtrlLab(file.bytes), ControlLabBridgeError);
    releaseRead(file.bytes);
    await importing;
    assert.equal(shell.getLqrWorkspace().canExport().allowed, true);
    const source = fs.readFileSync(path.join(__dirname, "../../../web/app/shell.ts"), "utf8");
    assert.equal(source.includes("codeContext:"), false);
    assert.equal(source.includes('type: "MatrixGain"'), false);
    assert.equal(source.includes("reshapeRowMajor"), false);
  } finally {
    shell.dispose(); client.dispose(); store.close();
  }
});


test("G0D Node transport: DynamicController usa confirmação Python sem LQR e bloqueia configuração obsoleta", async () => {
  const { store, client } = createMockSetup();
  await client.init();
  const execute = client.execute.bind(client);
  const operations: string[] = [];
  let validationFailed = false;
  let waitAt: string | null = null;
  let entered!: () => void;
  let release!: () => void;
  let awaiting: Promise<void> | null = null;
  // This transport double tests sequencing and identity only. F9 checks actual
  // DynamicController dimensions, trajectories and saturation against the real engine.
  client.execute = async (request, options) => {
    operations.push(request.operation);
    if (request.operation === waitAt) {
      entered();
      await awaiting;
    }
    if (request.operation === "core.validate_interconnection") {
      return {
        api_version: request.api_version, request_id: request.request_id,
        project_id: request.project_id, project_revision: request.project_revision,
        status: validationFailed ? "failure" : "success", result: validationFailed ? null : { well_posed: true },
        assumptions: {}, diagnostics: { transport_double_only: true },
        provenance: { algorithm: "test.interconnection_transport", lib_versions: {} }, warnings: [],
        error: validationFailed ? { code: "DIMENSION_MISMATCH", message: "Dimensões incompatíveis." } : null,
      };
    }
    return execute(request, options);
  };
  const shell = new ControlLabShell({ client, project_id: "dynamic-export" });
  const options = {
    controller_kind: "dynamic" as const,
    dynamic_controller: structuredClone(DEFAULT_DYNAMIC_EXPORT_CONTROLLER),
    saturation: { enabled: false, u_min: -1, u_max: 1 },
  };
  try {
    assert.equal(shell.getLqrWorkspace().getCommittedSnapshot(), null);
    shell.setPvmExportOptions(options);
    const file = await shell.exportPvm();
    assert.deepEqual(operations, ["core.validate_interconnection", "io.export_pvm"]);
    const payload = JSON.parse(new TextDecoder().decode(file.bytes));
    assert.equal(payload.controller.kind, "DynamicController");
    assert.equal(file.pvm_controller_kind, "dynamic");
    shell.assertDynamicPvmExportAllowed(file.request_id, file.configuration_revision);
    assert.equal(shell.getLqrWorkspace().getCommittedSnapshot(), null);
    shell.setPvmExportOptions({ ...options, saturation: { enabled: true, u_min: -0.1, u_max: 0.1 } });
    assert.throws(() => shell.assertDynamicPvmExportAllowed(file.request_id, file.configuration_revision), ControlLabBridgeError);

    for (const operation of ["core.validate_interconnection", "io.export_pvm"]) {
      waitAt = operation;
      const reached = new Promise<void>((resolve) => { entered = resolve; });
      awaiting = new Promise<void>((resolve) => { release = resolve; });
      const exporting = shell.exportPvm();
      await reached;
      shell.setPvmExportOptions(options);
      release();
      await assert.rejects(exporting, (error: unknown) => error instanceof ControlLabBridgeError && error.code === "CANCELLED");
    }
    waitAt = null;
    validationFailed = true;
    operations.length = 0;
    await assert.rejects(shell.exportPvm(), (error: unknown) => error instanceof ControlLabBridgeError && error.code === "DIMENSION_MISMATCH");
    assert.deepEqual(operations, ["core.validate_interconnection"]);

    validationFailed = false;
    await shell.getLqrWorkspace().commitCurrentDesign();
    shell.getLqrWorkspace().pointerDown("dynamic-export-test");
    assert.throws(() => shell.exportPvm(), ControlLabBridgeError);
    await shell.getLqrWorkspace().cancelDrag();
    shell.getLqrWorkspace().beginFileImport();
    assert.throws(() => shell.exportPvm(), ControlLabBridgeError);
    shell.getLqrWorkspace().endFileImport();
  } finally {
    shell.dispose(); client.dispose(); store.close();
  }
});


test("R19 Node transport: .ctrlab preserva opções PVM e aceita projetos anteriores sem o campo", async () => {
  const { store, client } = createMockSetup();
  await client.init();
  const shell = new ControlLabShell({ client, project_id: "pvm-options-roundtrip" });
  try {
    await shell.getLqrWorkspace().commitCurrentDesign();
    const configured = {
      controller_kind: "dynamic" as const,
      dynamic_controller: structuredClone(DEFAULT_DYNAMIC_EXPORT_CONTROLLER),
      saturation: { enabled: true, u_min: [-0.2], u_max: [0.3] },
    };
    shell.setPvmExportOptions(configured);
    const file = await shell.exportCtrlLab();
    const payload = JSON.parse(new TextDecoder().decode(file.bytes));
    assert.deepEqual(payload.project.experiments[0].parameters.pvm_export_options, configured);
    shell.setPvmExportOptions({ controller_kind: "lqr", saturation: { enabled: false, u_min: -1, u_max: 1 } });
    await shell.importCtrlLab(file.bytes);
    assert.deepEqual(shell.getPvmExportOptions(), configured);
    const execute = client.execute.bind(client);
    let entered!: () => void;
    let release!: () => void;
    const reached = new Promise<void>((resolve) => { entered = resolve; });
    const wait = new Promise<void>((resolve) => { release = resolve; });
    client.execute = async (request, options) => {
      if (request.operation === "io.export_ctrlab") { entered(); await wait; }
      return execute(request, options);
    };
    const exporting = shell.exportCtrlLab();
    await reached;
    shell.setPvmExportOptions({ controller_kind: "lqr", saturation: { enabled: false, u_min: -1, u_max: 1 } });
    release();
    await assert.rejects(exporting, (error: unknown) => error instanceof ControlLabBridgeError && error.code === "CANCELLED");
    client.execute = execute;
    const snapshot = shell.getLqrWorkspace().getCommittedSnapshot();
    delete payload.project.experiments[0].parameters.pvm_export_options;
    await shell.importCtrlLab(new TextEncoder().encode(JSON.stringify(payload)));
    assert.deepEqual(shell.getLqrWorkspace().getCommittedSnapshot(), snapshot);
    assert.deepEqual(shell.getPvmExportOptions(), {
      controller_kind: "lqr", saturation: { enabled: false, u_min: -1, u_max: 1 },
    });
    const state = shell.getPvmExportOptions()!;
    state.saturation.enabled = true;
    assert.equal(shell.getPvmExportOptions()?.saturation.enabled, false);
  } finally {
    shell.dispose(); client.dispose(); store.close();
  }
});
