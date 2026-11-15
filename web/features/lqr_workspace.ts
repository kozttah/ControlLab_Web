/**
 * Espaço de trabalho LQR (Aba 3 — Espaço de Estados) com separação estrita entre
 * Fast-Preview efêmero a 60 FPS (pointermove) e committed_result autoritativo
 * via ControlLabEngineClient (pointerup -> pending_commit -> Python/Mock RPC -> IndexedDB).
 *
 * PROIBIDO duplicar CARE/Riccati/LQR na UI: apenas cálculos estritamente geométricos
 * de renderização e preview transitório marcado como 'preview' são permitidos.
 * (CL-DIR-001 Seções 4.1–4.4, 5.4, 7.2, 13.10, Gate G-0C, T-UI-01).
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping e erasableSyntaxOnly.
 */

import type { ControlLabEngineClient } from "../bridge/client.ts";
import {
  ControlLabBridgeError,
  ensureFiniteJson,
  generateUuid,
  isPlainObject,
  RPC_API_VERSION,
  validateTensorDescriptor,
  type BinaryTensorInput,
  type ComplexVectorPair,
  type Provenance,
  type RealTensor,
  type RpcRequest,
  type RpcResponse,
  type TensorDescriptor,
  type TypedError,
  type WarningItem,
} from "../bridge/protocol.ts";
import {
  AriaLiveAnnouncer,
  handleSliderKeyDown,
  type AccessibilityThemeMode,
  type AccessibleSliderConfig,
} from "../app/accessibility.ts";
import type { ResultVerificationIndicator } from "../app/tool_descriptor.ts";
import type { RequirementOverlay } from "../charts/overlays.ts";
import {
  buildPoleZeroChartModel,
  buildTimeResponseChartModel,
  FrameBudgetTracker,
  type FrameBudgetStats,
  type PoleZeroChartModel,
  type TimeResponseChartModel,
} from "../charts/scientific_chart.ts";

export type FeedbackSign = "negative" | "positive";

export interface CanonicalStateSpaceModel {
  schema_version: "1.0.0";
  id: string;
  revision: number;
  kind: "StateSpace";
  dt: number | null;
  state_names: string[];
  input_names: string[];
  output_names: string[];
  matrices: {
    A: RealTensor;
    B: RealTensor;
    C: RealTensor;
    D: RealTensor;
  };
  units: {
    time: string;
    states?: string[];
    inputs: string[];
    outputs: string[];
  };
  provenance: Record<string, unknown>;
}

export interface LqrTimeResponseData {
  t: number[];
  x: number[][];
  u: number[][];
  y: number[][];
  state_names?: string[];
  input_names?: string[];
  output_names?: string[];
}

export interface CommittedLqrSnapshot {
  project_id: string;
  project_revision: number;
  model_revision: number;
  request_id: string;
  controller_ref: { id: string; revision: number } | null;
  controller_kind: string;
  feedback_sign: FeedbackSign;
  K: RealTensor | null;
  P: RealTensor | null;
  optimal_cost: number | null;
  open_loop_poles: ComplexVectorPair | null;
  closed_loop_poles: ComplexVectorPair | null;
  time_response: LqrTimeResponseData | null;
  assumptions: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  provenance: Provenance;
  warnings: Array<string | WarningItem>;
  status: "success" | "warning" | "inconclusive";
  response: RpcResponse;
  committed_at: string;
}

export interface LqrFastPreviewState {
  active: boolean;
  dragHandleId: string | null;
  indicator: "preview";
  baselineProjectRevision: number | null;
  baseQ: RealTensor | null;
  baseR: RealTensor | null;
  previewQ: RealTensor | null;
  previewR: RealTensor | null;
  qScale: number;
  rScale: number;
  previewPoles: ComplexVectorPair | null;
  previewY: number[][] | null;
  pointerMoveCount: number;
  lastMoveElapsedMs: number;
  frameMetrics: FrameBudgetStats;
}

export interface LqrExportGuardStatus {
  allowed: boolean;
  reason: string | null;
}

interface WorkspaceUndoSnapshot {
  plant: CanonicalStateSpaceModel;
  Q: RealTensor;
  R: RealTensor;
  x0: RealTensor;
  feedbackSign: FeedbackSign;
  qScale: number;
  rScale: number;
}

function nowMs(): number {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

function makeIdentityTensor(size: number, scale = 1.0): RealTensor {
  const data = new Array<number>(size * size).fill(0);
  for (let i = 0; i < size; i += 1) {
    data[i * size + i] = scale;
  }
  return {
    shape: [size, size],
    dtype: "float64",
    order: "C",
    data,
  };
}

function scaleTensorCopy(tensor: RealTensor, factor: number): RealTensor {
  return {
    shape: [...tensor.shape],
    dtype: "float64",
    order: "C",
    data: tensor.data.map((v) => v * factor),
  };
}

export function createDoubleIntegratorPlant(
  options?: { id?: string; revision?: number },
): CanonicalStateSpaceModel {
  return {
    schema_version: "1.0.0",
    id: options?.id ?? "plant-double-integrator",
    revision: options?.revision ?? 1,
    kind: "StateSpace",
    dt: null,
    state_names: ["x1", "x2"],
    input_names: ["u1"],
    output_names: ["y1"],
    matrices: {
      A: { shape: [2, 2], dtype: "float64", order: "C", data: [0, 1, 0, 0] },
      B: { shape: [2, 1], dtype: "float64", order: "C", data: [0, 1] },
      C: { shape: [1, 2], dtype: "float64", order: "C", data: [1, 0] },
      D: { shape: [1, 1], dtype: "float64", order: "C", data: [0] },
    },
    units: {
      time: "s",
      states: ["m", "m/s"],
      inputs: ["N"],
      outputs: ["m"],
    },
    provenance: { source: "B-CARE-02" },
  };
}

export function validateCanonicalStateSpace(
  raw: CanonicalStateSpaceModel,
): CanonicalStateSpaceModel {
  if (!isPlainObject(raw) || raw.kind !== "StateSpace") {
    throw new ControlLabBridgeError(
      "UNSUPPORTED_MODEL",
      "Modelo deve possuir kind='StateSpace'.",
    );
  }
  if (typeof raw.id !== "string" || raw.id.trim().length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "StateSpace.id deve ser string não vazia.",
    );
  }
  if (!Number.isInteger(raw.revision) || raw.revision < 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `StateSpace.revision deve ser inteiro >= 0, recebido ${String(raw.revision)}.`,
    );
  }
  if (raw.dt !== null && (typeof raw.dt !== "number" || !Number.isFinite(raw.dt) || raw.dt <= 0)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `StateSpace.dt deve ser null (contínuo) ou número finito > 0, recebido ${String(raw.dt)}.`,
    );
  }

  const A = assertRealFloat64Tensor(validateTensorDescriptor(raw.matrices?.A, "matrices.A"), "matrices.A");
  const B = assertRealFloat64Tensor(validateTensorDescriptor(raw.matrices?.B, "matrices.B"), "matrices.B");
  const C = assertRealFloat64Tensor(validateTensorDescriptor(raw.matrices?.C, "matrices.C"), "matrices.C");
  const D = assertRealFloat64Tensor(validateTensorDescriptor(raw.matrices?.D, "matrices.D"), "matrices.D");
  if (A.shape.length !== 2 || A.shape[0] !== A.shape[1]) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Matriz A deve ser quadrada (n x n), recebido [${A.shape.join(", ")}].`,
      { parameters: { A_shape: A.shape } },
    );
  }
  const n = A.shape[0];
  if (B.shape.length !== 2 || B.shape[0] !== n) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Matriz B deve ter shape (${n}, m), recebido [${B.shape.join(", ")}].`,
      { parameters: { n, B_shape: B.shape } },
    );
  }
  const m = B.shape[1];
  if (C.shape.length !== 2 || C.shape[1] !== n) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Matriz C deve ter shape (p, ${n}), recebido [${C.shape.join(", ")}].`,
      { parameters: { n, C_shape: C.shape } },
    );
  }
  const p = C.shape[0];
  if (D.shape.length !== 2 || D.shape[0] !== p || D.shape[1] !== m) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Matriz D deve ter shape (${p}, ${m}), recebido [${D.shape.join(", ")}].`,
      { parameters: { p, m, D_shape: D.shape } },
    );
  }

  if (raw.state_names.length !== n) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `state_names (${raw.state_names.length}) deve corresponder a n=${n}.`,
    );
  }
  if (raw.input_names.length !== m) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `input_names (${raw.input_names.length}) deve corresponder a m=${m}.`,
    );
  }
  if (raw.output_names.length !== p) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `output_names (${raw.output_names.length}) deve corresponder a p=${p}.`,
    );
  }

  return ensureFiniteJson(structuredClone(raw), "$.plant") as CanonicalStateSpaceModel;
}

/**
 * Constrói um `CanonicalStateSpaceModel` a partir dos dados de uma fixture ouro
 * (como B-CARE-02 ou B-CARE-12x3), preservando integralmente dimensões (ex.: n=12, m=3, p=4, C!=I).
 */
export function buildPlantFromFixtureData(input: {
  id: string;
  revision?: number;
  A: number[][];
  B: number[][];
  C?: number[][];
  D?: number[][];
  dt?: number | null;
  units?: { time?: string; inputs?: string[]; outputs?: string[] };
  provenance?: Record<string, unknown>;
}): CanonicalStateSpaceModel {
  const n = input.A.length;
  const m = input.B[0]?.length ?? 1;
  const Cmat =
    input.C ??
    Array.from({ length: n }, (_, r) =>
      Array.from({ length: n }, (__, c) => (r === c ? 1.0 : 0.0)),
    );
  const p = Cmat.length;
  const Dmat =
    input.D ??
    Array.from({ length: p }, () => Array.from({ length: m }, () => 0.0));

  const flatten = (mat: number[][]): number[] => mat.flat();

  return validateCanonicalStateSpace({
    schema_version: "1.0.0",
    id: input.id,
    revision: input.revision ?? 1,
    kind: "StateSpace",
    dt: input.dt ?? null,
    state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
    input_names: Array.from({ length: m }, (_, i) => `u${i + 1}`),
    output_names: Array.from({ length: p }, (_, i) => `y${i + 1}`),
    matrices: {
      A: { shape: [n, n], dtype: "float64", order: "C", data: flatten(input.A) },
      B: { shape: [n, m], dtype: "float64", order: "C", data: flatten(input.B) },
      C: { shape: [p, n], dtype: "float64", order: "C", data: flatten(Cmat) },
      D: { shape: [p, m], dtype: "float64", order: "C", data: flatten(Dmat) },
    },
    units: {
      time: input.units?.time ?? "s",
      inputs:
        input.units?.inputs ?? Array.from({ length: m }, (_, i) => `in${i + 1}`),
      outputs:
        input.units?.outputs ?? Array.from({ length: p }, (_, i) => `out${i + 1}`),
    },
    provenance: input.provenance ?? { source: "fixture" },
  });
}

function assertRealFloat64Tensor(
  desc: TensorDescriptor,
  name: string,
): RealTensor {
  if (!("dtype" in desc) || !("data" in desc) || desc.dtype !== "float64") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Tensor '${name}' deve ser RealTensor com dtype='float64'.`,
    );
  }
  return desc;
}

function validateWeightTensor(
  tensor: RealTensor,
  expectedDim: number,
  name: string,
): RealTensor {
  const valid = assertRealFloat64Tensor(
    validateTensorDescriptor(tensor, name),
    name,
  );
  if (
    valid.shape.length !== 2 ||
    valid.shape[0] !== expectedDim ||
    valid.shape[1] !== expectedDim
  ) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Matriz ${name} deve ter shape (${expectedDim}, ${expectedDim}), recebido [${valid.shape.join(", ")}].`,
      { parameters: { name, expected: [expectedDim, expectedDim], actual: valid.shape } },
    );
  }
  return valid;
}

export function validateInitialStateTensor(
  raw: unknown,
  n: number,
): RealTensor {
  const valid = assertRealFloat64Tensor(
    validateTensorDescriptor(raw, "x0"),
    "x0",
  );
  const isValidShape =
    (valid.shape.length === 1 && valid.shape[0] === n) ||
    (valid.shape.length === 2 &&
      ((valid.shape[0] === n && valid.shape[1] === 1) ||
        (valid.shape[0] === 1 && valid.shape[1] === n)));
  if (!isValidShape || valid.data.length !== n) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Estado inicial x0 deve ter shape [${n}, 1], [1, ${n}] ou [${n}] com ${n} elementos, recebido [${valid.shape.join(", ")}].`,
      { parameters: { name: "x0", expected_n: n, actual_shape: valid.shape } },
    );
  }
  return valid;
}

function parseComplexVectorPair(raw: unknown): ComplexVectorPair | null {
  if (!isPlainObject(raw)) return null;
  if (!Array.isArray(raw.real) || !Array.isArray(raw.imag)) return null;
  if (
    raw.real.some((v) => typeof v !== "number" || !Number.isFinite(v)) ||
    raw.imag.some((v) => typeof v !== "number" || !Number.isFinite(v))
  ) {
    return null;
  }
  return {
    real: [...(raw.real as number[])],
    imag: [...(raw.imag as number[])],
  };
}

function parseTimeResponse(raw: unknown): LqrTimeResponseData | null {
  if (!isPlainObject(raw)) return null;
  if (!Array.isArray(raw.t) || !Array.isArray(raw.y)) return null;
  const t = raw.t.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const normalize2d = (m: unknown): number[][] => {
    if (!Array.isArray(m)) return [];
    return m.map((row) =>
      Array.isArray(row)
        ? row.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : 0))
        : typeof row === "number" && Number.isFinite(row)
          ? [row]
          : [],
    );
  };
  return {
    t,
    x: normalize2d(raw.x),
    u: normalize2d(raw.u),
    y: normalize2d(raw.y),
    state_names: Array.isArray(raw.state_names)
      ? (raw.state_names as string[])
      : undefined,
    input_names: Array.isArray(raw.input_names)
      ? (raw.input_names as string[])
      : undefined,
    output_names: Array.isArray(raw.output_names)
      ? (raw.output_names as string[])
      : undefined,
  };
}

export interface LqrWorkspaceOptions {
  client: ControlLabEngineClient;
  project_id?: string;
  initial_revision?: number;
  plant?: CanonicalStateSpaceModel;
  Q?: RealTensor;
  R?: RealTensor;
  x0?: RealTensor;
  feedbackSign?: FeedbackSign;
  announcer?: AriaLiveAnnouncer;
  useCoalescedWorkerPreview?: boolean;
  useTransferableBuffers?: boolean;
  themeMode?: AccessibilityThemeMode;
}

export class LqrWorkspaceController {
  private readonly client: ControlLabEngineClient;
  private projectId: string;
  private projectRevision: number;
  private latestCommitRevision = 0;
  private inFlightRequestId: string | null = null;
  private activeCommitToken = 0;

  private plant: CanonicalStateSpaceModel;
  private readonly plantHistory = new Map<number, CanonicalStateSpaceModel>();
  private Q: RealTensor;
  private R: RealTensor;
  private x0: RealTensor;
  private feedbackSign: FeedbackSign;
  private currentQScale = 1.0;
  private currentRScale = 1.0;

  private pendingCommit = false;
  private fileImportPending = false;
  private controllerInvalidated = false;
  private invalidationReason: string | null = null;
  private committedSnapshot: CommittedLqrSnapshot | null = null;
  private openLoopPoles: ComplexVectorPair | null = null;
  private lastError: TypedError | null = null;
  private readonly overlays: RequirementOverlay[] = [];
  private readonly undoStack: WorkspaceUndoSnapshot[] = [];

  private readonly announcer: AriaLiveAnnouncer;
  private readonly frameTracker = new FrameBudgetTracker();
  private readonly useCoalescedWorkerPreview: boolean;
  private readonly useTransferableBuffers: boolean;
  private themeMode: AccessibilityThemeMode;
  private readonly listeners = new Set<() => void>();

  private previewState: LqrFastPreviewState;

  constructor(options: LqrWorkspaceOptions) {
    this.client = options.client;
    this.projectId = options.project_id ?? "proj-lqr-default";
    this.projectRevision = options.initial_revision ?? 0;
    this.plant = validateCanonicalStateSpace(
      options.plant ?? createDoubleIntegratorPlant(),
    );
    this.plantHistory.set(this.plant.revision, structuredClone(this.plant));

    const n = this.plant.matrices.A.shape[0];
    const m = this.plant.matrices.B.shape[1];

    this.Q = options.Q
      ? validateWeightTensor(options.Q, n, "Q")
      : makeIdentityTensor(n, 1.0);
    this.R = options.R
      ? validateWeightTensor(options.R, m, "R")
      : makeIdentityTensor(m, 1.0);
    this.x0 = options.x0
      ? validateInitialStateTensor(options.x0, n)
      : {
          shape: [n, 1],
          dtype: "float64",
          order: "C",
          data: Array.from({ length: n }, (_, i) => (i === 0 ? 1.0 : 0.0)),
        };
    this.feedbackSign = options.feedbackSign ?? "negative";
    this.announcer = options.announcer ?? new AriaLiveAnnouncer();
    this.useCoalescedWorkerPreview = options.useCoalescedWorkerPreview ?? false;
    this.useTransferableBuffers = options.useTransferableBuffers ?? false;
    this.themeMode = options.themeMode ?? "standard_aa";

    this.previewState = this.createIdlePreviewState();
  }

  private createIdlePreviewState(): LqrFastPreviewState {
    return {
      active: false,
      dragHandleId: null,
      indicator: "preview",
      baselineProjectRevision: null,
      baseQ: null,
      baseR: null,
      previewQ: null,
      previewR: null,
      qScale: 1.0,
      rScale: 1.0,
      previewPoles: null,
      previewY: null,
      pointerMoveCount: 0,
      lastMoveElapsedMs: 0,
      frameMetrics: this.frameTracker.getStats(),
    };
  }

  public getProjectId(): string {
    return this.projectId;
  }

  public getProjectRevision(): number {
    return this.projectRevision;
  }

  public isPendingCommit(): boolean {
    return this.pendingCommit;
  }

  public isControllerInvalidated(): boolean {
    return this.controllerInvalidated;
  }

  public getInvalidationReason(): string | null {
    return this.invalidationReason;
  }

  public getPlant(): CanonicalStateSpaceModel {
    return structuredClone(this.plant);
  }

  public getPlantHistoryRevision(revision: number): CanonicalStateSpaceModel | null {
    const found = this.plantHistory.get(revision);
    return found ? structuredClone(found) : null;
  }

  public getWeights(): { Q: RealTensor; R: RealTensor; x0: RealTensor } {
    return {
      Q: structuredClone(this.Q),
      R: structuredClone(this.R),
      x0: structuredClone(this.x0),
    };
  }

  public getFeedbackSign(): FeedbackSign {
    return this.feedbackSign;
  }

  public getCurrentScaleFactors(): { qScale: number; rScale: number } {
    return {
      qScale: this.currentQScale,
      rScale: this.currentRScale,
    };
  }

  public getCommittedSnapshot(): CommittedLqrSnapshot | null {
    return this.committedSnapshot ? structuredClone(this.committedSnapshot) : null;
  }

  public getPreviewState(): LqrFastPreviewState {
    return {
      ...this.previewState,
      baseQ: this.previewState.baseQ ? structuredClone(this.previewState.baseQ) : null,
      baseR: this.previewState.baseR ? structuredClone(this.previewState.baseR) : null,
      previewQ: this.previewState.previewQ
        ? structuredClone(this.previewState.previewQ)
        : null,
      previewR: this.previewState.previewR
        ? structuredClone(this.previewState.previewR)
        : null,
      previewPoles: this.previewState.previewPoles
        ? {
            real: [...this.previewState.previewPoles.real],
            imag: [...this.previewState.previewPoles.imag],
          }
        : null,
      previewY: this.previewState.previewY
        ? this.previewState.previewY.map((r) => [...r])
        : null,
      frameMetrics: this.frameTracker.getStats(),
    };
  }

  public getLastError(): TypedError | null {
    return this.lastError ? structuredClone(this.lastError) : null;
  }

  public getAnnouncer(): AriaLiveAnnouncer {
    return this.announcer;
  }

  public setThemeMode(mode: AccessibilityThemeMode): void {
    this.themeMode = mode;
    this.notify();
  }

  public getOverlays(): readonly RequirementOverlay[] {
    return [...this.overlays];
  }

  public addOverlay(overlay: RequirementOverlay): void {
    const idx = this.overlays.findIndex((o) => o.id === overlay.id);
    if (idx >= 0) {
      this.overlays[idx] = overlay;
    } else {
      this.overlays.push(overlay);
    }
    this.notify();
  }

  public removeOverlay(id: string): boolean {
    const idx = this.overlays.findIndex((o) => o.id === id);
    if (idx >= 0) {
      this.overlays.splice(idx, 1);
      this.notify();
      return true;
    }
    return false;
  }

  /**
   * Verifica rigorosamente se exportação (.pvm, .ctrlab, ganhos, CSV) é permitida.
   * Estritamente proibido durante Fast-Preview ou com pending_commit=true.
   */
  public beginFileImport(): void {
    this.assertEditable();
    if (this.pendingCommit || this.previewState.active) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Finalize a edição antes de abrir outro projeto.");
    }
    this.fileImportPending = true;
    this.notify();
  }

  public endFileImport(): void {
    this.fileImportPending = false;
    this.notify();
  }

  private assertEditable(): void {
    if (this.fileImportPending) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Aguarde a abertura do projeto antes de editar ou importar novamente.");
    }
  }

  public canExport(): LqrExportGuardStatus {
    if (this.fileImportPending) return { allowed: false, reason: "Abertura de projeto em andamento." };
    if (this.previewState.active) {
      return {
        allowed: false,
        reason:
          "Exportação bloqueada durante Fast-Preview transitório (finalize o arraste antes de exportar).",
      };
    }
    if (this.pendingCommit) {
      return {
        allowed: false,
        reason:
          "Exportação bloqueada enquanto o recálculo autoritativo Python está pendente (pending_commit=true).",
      };
    }
    if (this.committedSnapshot === null) {
      return {
        allowed: false,
        reason:
          "Exportação bloqueada: nenhum resultado científico foi confirmado ainda.",
      };
    }
    if (this.controllerInvalidated || this.committedSnapshot.project_revision !== this.projectRevision) {
      return {
        allowed: false,
        reason:
          this.invalidationReason ??
          "Exportação bloqueada: a planta foi editada (nova model_revision); recalcule e confirme o controlador antes de exportar.",
      };
    }
    return { allowed: true, reason: null };
  }

  public assertExportAllowed(): void {
    const guard = this.canExport();
    if (!guard.allowed) {
      this.announcer.announce(
        guard.reason ?? "Exportação bloqueada.",
        "assertive",
        "export_blocked",
      );
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        guard.reason ?? "Exportação não autorizada no estado atual.",
        {
          parameters: {
            preview_active: this.previewState.active,
            pending_commit: this.pendingCommit,
            controller_invalidated: this.controllerInvalidated,
          },
          next_step:
            "Conclua a edição (pointerup) e aguarde a confirmação autoritativa do controlador.",
        },
      );
    }
  }

  private pushUndoSnapshot(): void {
    this.undoStack.push({
      plant: structuredClone(this.plant),
      Q: structuredClone(this.Q),
      R: structuredClone(this.R),
      x0: structuredClone(this.x0),
      feedbackSign: this.feedbackSign,
      qScale: this.currentQScale,
      rScale: this.currentRScale,
    });
    if (this.undoStack.length > 50) {
      this.undoStack.shift();
    }
  }

  /**
   * Edita a planta StateSpace criando nova `model_revision` imutável e invalidando
   * o controlador dependente até novo projeto autoritativo (CL-DIR-001 Seção 4.1).
   */
  private invalidatePendingExecution(): void {
    if (!this.pendingCommit) return;
    const requestId = this.inFlightRequestId;
    this.activeCommitToken += 1;
    this.pendingCommit = false;
    this.inFlightRequestId = null;
    if (requestId) void this.client.cancel(requestId, { reason: "Parâmetros editados na UI" }).catch(() => undefined);
  }

  /** Restaura dados já validados pelo importador nativo, sem executar síntese. */
  public async restoreProject(input: {
    plant: CanonicalStateSpaceModel;
    snapshot: CommittedLqrSnapshot;
    Q: RealTensor;
    R: RealTensor;
    x0: RealTensor;
  }): Promise<void> {
    if (!this.fileImportPending || this.pendingCommit || this.previewState.active) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR", "Conclua ou cancele a edição antes de abrir um projeto.",
      );
    }
    const plant = validateCanonicalStateSpace(input.plant);
    const snapshot = structuredClone(input.snapshot);
    const n = plant.matrices.A.shape[0];
    const m = plant.matrices.B.shape[1];
    const Q = validateWeightTensor(input.Q, n, "Q");
    const R = validateWeightTensor(input.R, m, "R");
    const x0 = validateInitialStateTensor(input.x0, n);
    if (snapshot.model_revision !== plant.revision || !snapshot.K ||
        snapshot.K.shape[0] !== m || snapshot.K.shape[1] !== n ||
        !["negative", "positive"].includes(snapshot.feedback_sign) ||
        this.client.getCommittedRevision(snapshot.project_id) > snapshot.project_revision) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR", "Projeto incompatível com a planta ou anterior à revisão já aberta.",
      );
    }
    const outcome = await this.client.commitProject(snapshot.project_id, snapshot.project_revision, {
      committed_result: snapshot.response,
      objects: [{ object_id: plant.id, revision: plant.revision, kind: plant.kind,
        value: plant as unknown as Record<string, unknown> }],
      require_strictly_greater: false,
    });
    if (outcome.project.committed_revision !== snapshot.project_revision) {
      throw new ControlLabBridgeError("CANCELLED", "Uma revisão mais recente impediu a reabertura.");
    }
    this.invalidatePendingExecution();
    this.projectId = snapshot.project_id;
    this.projectRevision = snapshot.project_revision;
    this.latestCommitRevision = snapshot.project_revision;
    this.plant = plant;
    this.plantHistory.clear();
    this.plantHistory.set(plant.revision, structuredClone(plant));
    this.Q = Q;
    this.R = R;
    this.x0 = x0;
    this.feedbackSign = snapshot.feedback_sign;
    this.currentQScale = 1;
    this.currentRScale = 1;
    this.committedSnapshot = snapshot;
    this.openLoopPoles = snapshot.open_loop_poles;
    this.controllerInvalidated = false;
    this.invalidationReason = null;
    this.lastError = null;
    this.undoStack.length = 0;
    this.notify();
  }

  public updatePlant(nextModel: CanonicalStateSpaceModel): CanonicalStateSpaceModel {
    this.assertEditable();
    if (this.previewState.active) {
      this.cancelPreviewOnly();
    }
    const candidate: CanonicalStateSpaceModel = {
      ...structuredClone(nextModel),
      revision: Math.max(this.plant.revision + 1, nextModel.revision),
    };
    const validated = validateCanonicalStateSpace(candidate);
    this.pushUndoSnapshot();

    const prevN = this.plant.matrices.A.shape[0];
    const prevM = this.plant.matrices.B.shape[1];
    const nextN = validated.matrices.A.shape[0];
    const nextM = validated.matrices.B.shape[1];

    this.invalidatePendingExecution();
    this.plant = validated;
    this.plantHistory.set(validated.revision, structuredClone(validated));

    if (nextN !== prevN) {
      this.Q = makeIdentityTensor(nextN, 1.0);
      this.currentQScale = 1.0;
      this.x0 = {
        shape: [nextN, 1],
        dtype: "float64",
        order: "C",
        data: Array.from({ length: nextN }, (_, i) => (i === 0 ? 1.0 : 0.0)),
      };
    }
    if (nextM !== prevM) {
      this.R = makeIdentityTensor(nextM, 1.0);
      this.currentRScale = 1.0;
    }

    if (this.committedSnapshot !== null) {
      this.controllerInvalidated = true;
      this.invalidationReason = `Planta atualizada para model_revision=${validated.revision}; controlador anterior (model_revision=${this.committedSnapshot.model_revision}) invalidado.`;
      this.announcer.announce(
        this.invalidationReason,
        "polite",
        "status",
      );
    }
    this.notify();
    return this.getPlant();
  }

  public updateWeights(weights: {
    Q?: RealTensor;
    R?: RealTensor;
    x0?: RealTensor;
    feedbackSign?: FeedbackSign;
  }): void {
    this.assertEditable();
    if (this.previewState.active) {
      this.cancelPreviewOnly();
    }
    const n = this.plant.matrices.A.shape[0];
    const m = this.plant.matrices.B.shape[1];
    const nextQ = weights.Q ? validateWeightTensor(weights.Q, n, "Q") : this.Q;
    const nextR = weights.R ? validateWeightTensor(weights.R, m, "R") : this.R;
    const nextX0 = weights.x0
      ? validateInitialStateTensor(weights.x0, n)
      : this.x0;
    const nextSign = weights.feedbackSign ?? this.feedbackSign;

    this.pushUndoSnapshot();
    this.invalidatePendingExecution();
    this.Q = nextQ;
    this.R = nextR;
    this.x0 = nextX0;
    this.feedbackSign = nextSign;
    if (weights.Q) {
      this.currentQScale = 1.0;
    }
    if (weights.R) {
      this.currentRScale = 1.0;
    }
    if (this.committedSnapshot !== null) {
      this.controllerInvalidated = true;
      this.invalidationReason =
        "Pesos/parâmetros LQR alterados; recalcule e confirme o controlador antes de exportar.";
    }
    this.notify();
  }

  /**
   * Inicia sessão de arraste efêmero (pointerdown). Não comita nem grava em IndexedDB.
   */
  public pointerDown(handleId: string): void {
    this.assertEditable();
    if (typeof handleId !== "string" || handleId.trim().length === 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "pointerDown requer handleId não vazio.",
      );
    }
    this.previewState = {
      active: true,
      dragHandleId: handleId,
      indicator: "preview",
      baselineProjectRevision: this.projectRevision,
      baseQ: structuredClone(this.Q),
      baseR: structuredClone(this.R),
      previewQ: structuredClone(this.Q),
      previewR: structuredClone(this.R),
      qScale: 1.0,
      rScale: 1.0,
      previewPoles: this.committedSnapshot?.closed_loop_poles
        ? {
            real: [...this.committedSnapshot.closed_loop_poles.real],
            imag: [...this.committedSnapshot.closed_loop_poles.imag],
          }
        : null,
      previewY: null,
      pointerMoveCount: 0,
      lastMoveElapsedMs: 0,
      frameMetrics: this.frameTracker.getStats(),
    };
    this.announcer.announce(
      `Fast-Preview iniciado em ${handleId}. Resultado ainda não confirmado.`,
      "polite",
      "preview",
    );
    this.notify();
  }

  /**
   * Atualiza exclusivamente o estado efêmero de Fast-Preview a 60 FPS (pointermove).
   * Executa APENAS projeção geométrica de renderização (< 16.67 ms), sem síntese
   * CARE/Riccati nem mutação de committedSnapshot ou IndexedDB.
   */
  public pointerMove(input: {
    qScale?: number;
    rScale?: number;
    deltaX?: number;
    deltaY?: number;
  }): LqrFastPreviewState {
    const t0 = nowMs();
    if (!this.previewState.active) {
      this.pointerDown("drag-handle");
    }

    const rawQScale =
      input.qScale ?? (this.previewState.active ? this.previewState.qScale : 1.0);
    const rawRScale =
      input.rScale ?? (this.previewState.active ? this.previewState.rScale : 1.0);
    const qScale =
      typeof rawQScale === "number" && Number.isFinite(rawQScale) && rawQScale > 0
        ? rawQScale
        : 1.0;
    const rScale =
      typeof rawRScale === "number" && Number.isFinite(rawRScale) && rawRScale > 0
        ? rawRScale
        : 1.0;

    const baseQ = this.previewState.baseQ ?? this.Q;
    const baseR = this.previewState.baseR ?? this.R;
    const previewQ = scaleTensorCopy(baseQ, qScale);
    const previewR = scaleTensorCopy(baseR, rScale);

    // Projeção estritamente geométrica dos polos já conhecidos (NUNCA resolve CARE!)
    let previewPoles: ComplexVectorPair | null = null;
    const baselinePoles = this.committedSnapshot?.closed_loop_poles;
    const dx = typeof input.deltaX === "number" && Number.isFinite(input.deltaX) ? input.deltaX : 0;
    const dy = typeof input.deltaY === "number" && Number.isFinite(input.deltaY) ? input.deltaY : 0;

    if (baselinePoles) {
      const ratioLog = Math.log(Math.max(1e-4, qScale / rScale));
      const geomFactor = Math.max(0.2, 1.0 + 0.15 * ratioLog);
      previewPoles = {
        real: baselinePoles.real.map((re) => re * geomFactor + dx),
        imag: baselinePoles.imag.map((im) =>
          im === 0 ? 0 : im * (1.0 + 0.05 * ratioLog) + Math.sign(im) * dy,
        ),
      };
    }

    // Projeção estritamente geométrica da curva de saída (quando já existe trajetória comitada)
    let previewY: number[][] | null = null;
    const committedTime = this.committedSnapshot?.time_response;
    if (committedTime && committedTime.y.length > 0) {
      const ampScale = Math.max(0.25, Math.min(2.5, 1.0 - 0.08 * Math.log(Math.max(1e-4, qScale / rScale))));
      previewY = committedTime.y.map((row) => row.map((v) => v * ampScale));
    }

    const t1 = nowMs();
    const elapsedMs = Math.max(0, t1 - t0);
    this.frameTracker.recordFrame(elapsedMs);

    this.previewState = {
      ...this.previewState,
      active: true,
      indicator: "preview",
      previewQ,
      previewR,
      qScale,
      rScale,
      previewPoles,
      previewY,
      pointerMoveCount: this.previewState.pointerMoveCount + 1,
      lastMoveElapsedMs: elapsedMs,
      frameMetrics: this.frameTracker.getStats(),
    };

    if (this.useCoalescedWorkerPreview) {
      const previewReq: RpcRequest = {
        api_version: RPC_API_VERSION,
        request_id: `lqr-preview-${generateUuid()}`,
        project_id: this.projectId,
        project_revision: this.projectRevision,
        operation: "statespace.design_lqr",
        payload: {
          plant_ref: { id: this.plant.id, revision: this.plant.revision },
          Q: previewQ,
          R: previewR,
          feedback_sign: this.feedbackSign,
        },
        options: { preview: true, method: this.plant.dt === null ? "care" : "dare" },
        timeout_policy: { hard_timeout_ms: 2000, cancel_on_supersede: true },
      };
      void this.client
        .execute(previewReq, {
          commitOnSuccess: false,
          coalesceKey: `lqr-preview-${this.projectId}`,
          debounceMs: 30,
          preserveSenderCopy: true,
        })
        .catch(() => undefined);
    }

    this.notify();
    return this.getPreviewState();
  }

  /**
   * Finaliza o arraste (pointerup): marca `pending_commit=true`, promove os pesos
   * finais e dispara obrigatoriamente o cálculo autoritativo Python/Mock no Worker.
   */
  public async pointerUp(options?: {
    qScale?: number;
    rScale?: number;
    computeTimeResponse?: boolean;
    hardTimeoutMs?: number;
    extraRpcOptions?: Record<string, unknown>;
  }): Promise<CommittedLqrSnapshot | null> {
    this.assertEditable();
    if (options?.qScale !== undefined || options?.rScale !== undefined) {
      const baseQ = this.previewState.baseQ ?? this.Q;
      const baseR = this.previewState.baseR ?? this.R;
      const qS =
        options.qScale !== undefined &&
        Number.isFinite(options.qScale) &&
        options.qScale > 0
          ? options.qScale
          : this.previewState.qScale;
      const rS =
        options.rScale !== undefined &&
        Number.isFinite(options.rScale) &&
        options.rScale > 0
          ? options.rScale
          : this.previewState.rScale;
      this.pushUndoSnapshot();
      this.Q = scaleTensorCopy(baseQ, qS);
      this.R = scaleTensorCopy(baseR, rS);
      this.currentQScale = this.currentQScale * qS;
      this.currentRScale = this.currentRScale * rS;
      if (this.committedSnapshot !== null) {
        this.controllerInvalidated = true;
        this.invalidationReason =
          "Pesos LQR alterados pelo arraste; aguardando commit autoritativo.";
      }
    } else if (this.previewState.active && this.previewState.previewQ && this.previewState.previewR) {
      this.pushUndoSnapshot();
      this.Q = structuredClone(this.previewState.previewQ);
      this.R = structuredClone(this.previewState.previewR);
      this.currentQScale = this.currentQScale * this.previewState.qScale;
      this.currentRScale = this.currentRScale * this.previewState.rScale;
      if (this.committedSnapshot !== null) {
        this.controllerInvalidated = true;
        this.invalidationReason =
          "Pesos LQR alterados pelo arraste; aguardando commit autoritativo.";
      }
    }

    this.previewState = this.createIdlePreviewState();
    return this.commitCurrentDesign({
      computeTimeResponse: options?.computeTimeResponse,
      hardTimeoutMs: options?.hardTimeoutMs,
      extraRpcOptions: options?.extraRpcOptions,
    });
  }

  /**
   * Executa cálculo autoritativo `statespace.design_lqr` via ControlLabEngineClient,
   * respeitando `pending_commit`, `project_revision` monotônico e descarte de obsoletos.
   */
  public async commitCurrentDesign(options?: {
    computeTimeResponse?: boolean;
    hardTimeoutMs?: number;
    extraRpcOptions?: Record<string, unknown>;
  }): Promise<CommittedLqrSnapshot | null> {
    this.assertEditable();
    this.projectRevision = Math.max(this.projectRevision, this.client.getCommittedRevision(this.projectId)) + 1;
    const targetRevision = this.projectRevision;
    this.latestCommitRevision = targetRevision;
    this.activeCommitToken += 1;
    const myToken = this.activeCommitToken;
    const reqId = `lqr-commit-r${targetRevision}-${generateUuid()}`;
    this.inFlightRequestId = reqId;
    this.pendingCommit = true;
    this.controllerInvalidated = this.committedSnapshot !== null;
    this.invalidationReason = "Novo cálculo pendente; resultado anterior permanece apenas histórico.";
    this.lastError = null;

    this.announcer.announce(
      `Calculando controlador LQR autoritativo (revisão ${targetRevision})...`,
      "polite",
      "pending_commit",
    );
    this.notify();

    try {
      // Registra planta no WorkerModelStore em RAM (sem persistir em IndexedDB antes do commit!)
      await this.client.registerObject(
        this.projectId,
        this.plant.id,
        this.plant.revision,
        this.plant as unknown as Record<string, unknown>,
        {
          kind: "StateSpace",
          pinProject: true,
          persistToIndexedDB: false,
        },
      );

      if (myToken !== this.activeCommitToken || targetRevision < this.latestCommitRevision) {
        this.notify();
        return this.committedSnapshot ? structuredClone(this.committedSnapshot) : null;
      }

      let payloadQ: unknown = structuredClone(this.Q);
      let payloadR: unknown = structuredClone(this.R);
      let buffers: Record<string, BinaryTensorInput> | undefined;

      if (this.useTransferableBuffers) {
        const qBuf = new Float64Array(this.Q.data).buffer;
        const rBuf = new Float64Array(this.R.data).buffer;
        payloadQ = {
          dtype: "float64",
          shape: [...this.Q.shape],
          order: "C",
          buffer_ref: "Q-01",
        };
        payloadR = {
          dtype: "float64",
          shape: [...this.R.shape],
          order: "C",
          buffer_ref: "R-01",
        };
        buffers = {
          "Q-01": { shape: [...this.Q.shape], dtype: "float64", order: "C", buffer: qBuf },
          "R-01": { shape: [...this.R.shape], dtype: "float64", order: "C", buffer: rBuf },
        };
      }

      const request: RpcRequest = {
        api_version: RPC_API_VERSION,
        request_id: reqId,
        project_id: this.projectId,
        project_revision: targetRevision,
        operation: "statespace.design_lqr",
        payload: {
          plant_ref: { id: this.plant.id, revision: this.plant.revision },
          Q: payloadQ,
          R: payloadR,
          x0: structuredClone(this.x0),
          feedback_sign: this.feedbackSign,
        },
        options: {
          method: this.plant.dt === null ? "care" : "dare",
          compute_time_response: options?.computeTimeResponse ?? true,
          ...(options?.extraRpcOptions ?? {}),
        },
        timeout_policy: {
          hard_timeout_ms: options?.hardTimeoutMs ?? 30000,
          cancel_on_supersede: true,
        },
      };

      const resp = await this.client.execute(request, {
        commitOnSuccess: false,
        buffers,
        preserveSenderCopy: true,
      });

      // Descartar qualquer resposta obsoleta ou superada por revisão mais recente
      const isStale =
        myToken !== this.activeCommitToken ||
        targetRevision < this.latestCommitRevision ||
        resp.diagnostics?.stale_discarded === true ||
        resp.project_revision < this.latestCommitRevision;

      if (isStale) {
        this.notify();
        return this.committedSnapshot ? structuredClone(this.committedSnapshot) : null;
      }

      if (resp.status === "failure" || resp.status === "inconclusive" ||
          !resp.result || resp.project_revision !== targetRevision ||
          resp.project_id !== this.projectId || resp.request_id !== reqId) {
        this.pendingCommit = false;
        this.inFlightRequestId = null;
        this.lastError = resp.error ?? {
          code: "VALIDATION_ERROR",
          message: "Resultado LQR inconclusivo, ausente ou de revisão divergente; exportação não autorizada.",
        };
        this.announcer.announce(
          `Erro no cálculo LQR [${this.lastError.code}]: ${this.lastError.message}`,
          "assertive",
          "error",
        );
        this.notify();
        return null;
      }

      const resObj = resp.result ?? {};
      const ctrlRefRaw = resObj.controller_ref;
      const ctrlRef =
        isPlainObject(ctrlRefRaw) &&
        typeof ctrlRefRaw.id === "string" &&
        typeof ctrlRefRaw.revision === "number"
          ? { id: ctrlRefRaw.id, revision: ctrlRefRaw.revision }
          : null;

      // Referências são válidas no contrato; resolva o objeto autoritativo pelo cliente F7.
      const referencedController = !resObj.K && ctrlRef
        ? await this.client.getObject(this.projectId, ctrlRef.id, ctrlRef.revision) : null;
      const rawK = resObj.K ?? referencedController?.K;
      const parsedK =
        isPlainObject(rawK) && Array.isArray(rawK.data)
          ? assertRealFloat64Tensor(
              validateTensorDescriptor(rawK, "result.K"),
              "result.K",
            )
          : null;
      const parsedP =
        isPlainObject(resObj.P) && Array.isArray(resObj.P.data)
          ? assertRealFloat64Tensor(
              validateTensorDescriptor(resObj.P, "result.P"),
              "result.P",
            )
          : null;
      const openPoles = parseComplexVectorPair(resObj.open_loop_poles) ?? this.openLoopPoles;
      const closedPoles = parseComplexVectorPair(resObj.closed_loop_poles);
      const timeResp = parseTimeResponse(resObj.time_response);
      const optimalCost =
        typeof resObj.optimal_cost === "number" && Number.isFinite(resObj.optimal_cost)
          ? resObj.optimal_cost
          : null;
      const sign =
        resObj.feedback_sign === "positive" || resObj.feedback_sign === "negative"
          ? resObj.feedback_sign
          : this.feedbackSign;

      // Validação estrutural do resultado científico antes de qualquer persistência.
      // A UI não reexecuta a síntese nem infere sucesso de dados parciais.
      const n = this.plant.state_names.length;
      const m = this.plant.input_names.length;
      if (!parsedK || parsedK.shape.length !== 2 || parsedK.shape[0] !== m || parsedK.shape[1] !== n ||
          (parsedP !== null && (parsedP.shape.length !== 2 || parsedP.shape[0] !== n || parsedP.shape[1] !== n)) ||
          !closedPoles || closedPoles.real.length !== n || !ctrlRef ||
          !Number.isInteger(ctrlRef.revision) || ctrlRef.revision < 0 ||
          resObj.feedback_sign !== this.feedbackSign) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", "Resultado LQR incompleto ou incompatível com a planta; nenhum commit autorizado.");
      }
      if (myToken !== this.activeCommitToken || targetRevision !== this.latestCommitRevision) return null;
      const confirmedResponse: RpcResponse = {
        ...resp, diagnostics: { ...resp.diagnostics, committed: true },
      };
      const outcome = await this.client.commitProject(this.projectId, targetRevision, {
        request_id: reqId,
        committed_result: confirmedResponse,
        require_strictly_greater: true,
        objects: [{ object_id: this.plant.id, revision: this.plant.revision,
          kind: "StateSpace", value: structuredClone(this.plant) as unknown as Record<string, unknown> }],
      });
      if (myToken !== this.activeCommitToken || targetRevision !== this.latestCommitRevision ||
          outcome.project.committed_revision !== targetRevision) {
        this.notify();
        return null;
      }
      this.pendingCommit = false;
      this.inFlightRequestId = null;

      const committed: CommittedLqrSnapshot = {
        project_id: this.projectId,
        project_revision: resp.project_revision,
        model_revision:
          typeof resp.provenance.model_revision === "number"
            ? resp.provenance.model_revision
            : this.plant.revision,
        request_id: resp.request_id,
        controller_ref: ctrlRef,
        controller_kind:
          typeof resObj.controller_kind === "string"
            ? resObj.controller_kind
            : "StateFeedbackController",
        feedback_sign: sign,
        K: parsedK,
        P: parsedP,
        optimal_cost: optimalCost,
        open_loop_poles: openPoles,
        closed_loop_poles: closedPoles,
        time_response: timeResp,
        assumptions: { ...resp.assumptions },
        diagnostics: { ...confirmedResponse.diagnostics },
        provenance: { ...resp.provenance },
        warnings: [...resp.warnings],
        status: resp.status,
        response: confirmedResponse,
        committed_at: new Date().toISOString(),
      };

      this.committedSnapshot = committed;
      this.controllerInvalidated = false;
      this.invalidationReason = null;
      this.lastError = null;

      this.announcer.announce(
        `Controlador LQR confirmado na revisão ${committed.project_revision} (modelo rev. ${committed.model_revision}).`,
        "polite",
        "committed",
      );
      this.notify();
      return structuredClone(committed);
    } catch (err: unknown) {
      if (myToken === this.activeCommitToken) {
        this.pendingCommit = false;
        this.inFlightRequestId = null;
        this.lastError =
          err instanceof ControlLabBridgeError
            ? err.typedError
            : {
                code: "INTERNAL_ERROR",
                message: err instanceof Error ? err.message : String(err),
              };
        this.announcer.announce(
          `Falha ao executar LQR: ${this.lastError.message}`,
          "assertive",
          "error",
        );
        this.notify();
      }
      return null;
    }
  }

  /**
   * Analisa estabilidade e controlabilidade (PBH) em malha aberta via Worker.
   */
  public async analyzeOpenLoop(): Promise<RpcResponse> {
    this.assertEditable();
    const rev = this.projectRevision;

    await this.client.registerObject(
      this.projectId,
      this.plant.id,
      this.plant.revision,
      this.plant as unknown as Record<string, unknown>,
      { kind: "StateSpace", pinProject: true, persistToIndexedDB: false },
    );

    const resp = await this.client.execute(
      {
        api_version: RPC_API_VERSION,
        request_id: `lqr-analyze-r${rev}-${generateUuid()}`,
        project_id: this.projectId,
        project_revision: rev,
        operation: "statespace.analyze",
        payload: {
          plant_ref: { id: this.plant.id, revision: this.plant.revision },
        },
        options: {},
        timeout_policy: { hard_timeout_ms: 15000, cancel_on_supersede: true },
      },
      { commitOnSuccess: false },
    );

    if (resp.status !== "failure" && resp.result) {
      const olp = parseComplexVectorPair(resp.result.open_loop_poles);
      if (olp) {
        this.openLoopPoles = olp;
      }
    } else if (resp.status === "failure") {
      this.lastError = resp.error;
    }
    this.notify();
    return resp;
  }

  private cancelPreviewOnly(): void {
    if (!this.previewState.active) return;
    if (this.previewState.baseQ) {
      this.Q = structuredClone(this.previewState.baseQ);
    }
    if (this.previewState.baseR) {
      this.R = structuredClone(this.previewState.baseR);
    }
    this.previewState = this.createIdlePreviewState();
  }

  /**
   * Cancela arraste em andamento ou requisição autoritativa em voo (Escape / botão Cancelar),
   * preservando integralmente o último `committedSnapshot` válido.
   */
  public async cancelDrag(): Promise<void> {
    const wasPreview = this.previewState.active;
    this.cancelPreviewOnly();

    if (this.pendingCommit) {
      const reqToCancel = this.inFlightRequestId;
      this.activeCommitToken += 1;
      this.pendingCommit = false;
      this.inFlightRequestId = null;
      if (reqToCancel) {
        await this.client.cancel(reqToCancel, {
          reason: "Cancelado pelo usuário na UI",
        });
      }
    }

    if (wasPreview || this.lastError === null) {
      this.announcer.announce(
        "Operação cancelada; último resultado confirmado preservado.",
        "polite",
        "status",
      );
    }
    this.notify();
  }

  /**
   * Perda de foco durante arraste descarta preview efêmero sem gravar em IndexedDB.
   */
  public handleBlur(): void {
    if (this.previewState.active) {
      this.cancelPreviewOnly();
      this.announcer.announce(
        "Foco perdido durante arraste: preview transitório descartado.",
        "polite",
        "status",
      );
      this.notify();
    }
  }

  /**
   * Troca de aba durante arraste descarta preview efêmero sem corromper committedSnapshot.
   */
  public handleTabSwitch(): void {
    if (this.previewState.active) {
      this.cancelPreviewOnly();
      this.announcer.announce(
        "Troca de aba: preview transitório descartado.",
        "polite",
        "status",
      );
      this.notify();
    }
  }

  /**
   * Desfaz última edição de planta/pesos e recompila autoritativamente em revisão monotônica.
   */
  public async undo(): Promise<boolean> {
    this.assertEditable();
    if (this.previewState.active) {
      this.cancelPreviewOnly();
    }
    const prev = this.undoStack.pop();
    if (!prev) {
      return false;
    }
    this.plant = structuredClone(prev.plant);
    this.Q = structuredClone(prev.Q);
    this.R = structuredClone(prev.R);
    this.x0 = structuredClone(prev.x0);
    this.feedbackSign = prev.feedbackSign;
    this.currentQScale = prev.qScale;
    this.currentRScale = prev.rScale;
    this.controllerInvalidated = this.committedSnapshot !== null;
    this.notify();

    if (this.committedSnapshot !== null) {
      await this.commitCurrentDesign();
    }
    return true;
  }

  /**
   * Manipula controle por teclado (ArrowLeft/ArrowRight/PageUp/PageDown/Home/End/Escape)
   * garantindo que passos confirmados disparem cálculo autoritativo sem travar em preview
   * e preservando a estrutura matricial de Q/R.
   */
  public async handleKeyboardSlider(
    key: string,
    axis: "q_scale" | "r_scale",
    sliderConfig: AccessibleSliderConfig,
  ): Promise<{ handled: boolean; nextValue: number }> {
    this.assertEditable();
    const res = handleSliderKeyDown(key, sliderConfig);
    if (!res.handled) {
      return { handled: false, nextValue: sliderConfig.value };
    }
    if (res.cancelled) {
      await this.cancelDrag();
      return { handled: true, nextValue: sliderConfig.value };
    }
    if (res.committed) {
      const prevVal =
        typeof sliderConfig.value === "number" &&
        Number.isFinite(sliderConfig.value) &&
        sliderConfig.value > 0
          ? sliderConfig.value
          : 1.0;
      const factor = res.nextValue > 0 ? res.nextValue / prevVal : 1.0;
      this.pushUndoSnapshot();
      const sourceQ =
        this.previewState.active && this.previewState.previewQ
          ? this.previewState.previewQ
          : this.Q;
      const sourceR =
        this.previewState.active && this.previewState.previewR
          ? this.previewState.previewR
          : this.R;
      const activePreviewRScale = this.previewState.active
        ? this.previewState.rScale
        : 1.0;
      const activePreviewQScale = this.previewState.active
        ? this.previewState.qScale
        : 1.0;
      this.previewState = this.createIdlePreviewState();
      if (axis === "q_scale") {
        this.Q = scaleTensorCopy(sourceQ, factor);
        this.R = structuredClone(sourceR);
        this.currentQScale = res.nextValue;
        this.currentRScale = this.currentRScale * activePreviewRScale;
      } else {
        this.R = scaleTensorCopy(sourceR, factor);
        this.Q = structuredClone(sourceQ);
        this.currentRScale = res.nextValue;
        this.currentQScale = this.currentQScale * activePreviewQScale;
      }
      await this.commitCurrentDesign();
    }
    return { handled: true, nextValue: res.nextValue };
  }

  public buildPoleZeroChart(): PoleZeroChartModel {
    // Um resultado de revisão anterior pode permanecer no histórico, nunca como curva atual.
    const current = !this.controllerInvalidated && this.committedSnapshot?.project_revision === this.projectRevision
      ? this.committedSnapshot : null;
    const isPreview = this.previewState.active;
    const semantics: ResultVerificationIndicator = isPreview
      ? "preview"
      : current
        ? "numeric_verified"
        : "experimental";

    return buildPoleZeroChartModel({
      chart_id: `lqr-pz-${this.projectId}`,
      title: `Polos e Zeros LQR — ${this.plant.id} (rev. ${this.plant.revision})`,
      dt: this.plant.dt,
      model_revision: this.plant.revision,
      project_revision:
        current?.project_revision ?? this.projectRevision,
      provenance: current?.provenance ?? null,
      series_semantics: semantics,
      feedback_sign: current?.feedback_sign ?? this.feedbackSign,
      open_loop_poles:
        current?.open_loop_poles ?? this.openLoopPoles,
      committed_closed_loop_poles:
        current?.closed_loop_poles ?? null,
      preview_poles: isPreview ? this.previewState.previewPoles : null,
      overlays: this.overlays,
      theme_mode: this.themeMode,
    });
  }

  public buildTimeResponseChart(): TimeResponseChartModel | null {
    if (this.controllerInvalidated || this.committedSnapshot?.project_revision !== this.projectRevision) return null;
    const tr = this.committedSnapshot?.time_response;
    if (!tr || tr.t.length === 0) {
      return null;
    }
    const isPreview = this.previewState.active;
    return buildTimeResponseChartModel({
      chart_id: `lqr-time-${this.projectId}`,
      title: `Resposta Temporal LQR (${this.plant.state_names.length} estados, ${this.plant.input_names.length} entradas, ${this.plant.output_names.length} saídas)`,
      dt: this.plant.dt,
      t: tr.t,
      x: tr.x,
      u: tr.u,
      y: tr.y,
      state_names: tr.state_names ?? this.plant.state_names,
      input_names: tr.input_names ?? this.plant.input_names,
      output_names: tr.output_names ?? this.plant.output_names,
      units: this.plant.units,
      model_revision: this.committedSnapshot?.model_revision ?? this.plant.revision,
      project_revision:
        this.committedSnapshot?.project_revision ?? this.projectRevision,
      provenance: this.committedSnapshot?.provenance ?? null,
      series_semantics: isPreview ? "preview" : "numeric_verified",
      feedback_sign: this.committedSnapshot?.feedback_sign ?? this.feedbackSign,
      preview_y: isPreview ? this.previewState.previewY : null,
      theme_mode: this.themeMode,
    });
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const fn of this.listeners) {
      try {
        fn();
      } catch {
        // Isolar falhas de assinantes
      }
    }
  }
}
