/**
 * Workspace tipado para objetos científicos canônicos do ControlLab Web:
 * StateSpace, TransferFunction, Dataset, IdentifiedModel, FuzzySystem e TSStateSpace
 * (ts_measured, polytopic_uncertain, ts_partially_observed).
 *
 * Responsabilidades estritas de F8:
 * - Validação estrutural, dimensional, de domínio e de tipo de DTOs canônicos (sem
 *   reimplementar algoritmos científicos Python).
 * - Registro explícito no cliente F7 (ControlLabEngineClient.registerObject) e
 *   hidratação pós-reinício via IndexedDB/Worker.
 * - Seleção tipada por papel/operação, eliminando envio cego de plant_ref.
 * - Fluxo core.reuse_model com visualização do derivado e registro explícito
 *   obrigatório antes do consumo em frequency.*, statespace.* ou LQR.
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping, erasableSyntaxOnly
 * e verbatimModuleSyntax.
 */

import type { ControlLabEngineClient } from "../bridge/client.ts";
import {
  ControlLabBridgeError,
  ensureFiniteJson,
  generateUuid,
  isPlainObject,
  RPC_API_VERSION,
  validateTensorDescriptor,
  type RealTensor,
  type RpcResponse,
  type TensorDescriptor,
  type WarningEntry,
} from "../bridge/protocol.ts";
import type { AriaLiveAnnouncer } from "../app/accessibility.ts";
import {
  validateCanonicalStateSpace,
  type CanonicalStateSpaceModel,
  type FeedbackSign,
} from "./lqr_workspace.ts";

export const TS_MODEL_KINDS = [
  "ts_measured",
  "polytopic_uncertain",
  "ts_partially_observed",
] as const;
export type TsModelKind = (typeof TS_MODEL_KINDS)[number];

export const TYPED_OBJECT_KINDS = [
  "StateSpace",
  "TransferFunction",
  "Dataset",
  "IdentifiedModel",
  "FuzzySystem",
  ...TS_MODEL_KINDS,
] as const;
export type TypedObjectKind = (typeof TYPED_OBJECT_KINDS)[number];

export const TYPED_SELECTION_ROLES = [
  "statespacePlant",
  "frequencyPlant",
  "dataset",
  "valDataset",
  "fuzzySystem",
  "tsModel",
  "validationModel",
  "reuseSource",
] as const;
export type TypedSelectionRole = (typeof TYPED_SELECTION_ROLES)[number];

export interface CanonicalObjectRef {
  id: string;
  revision: number;
}

export interface RegisteredTypedObject {
  key: string;
  id: string;
  revision: number;
  kind: TypedObjectKind;
  summary: string;
  value: Record<string, unknown>;
  persisted: boolean;
  registered_at: string;
  source: "manual" | "lqr_plant" | "derived_reuse" | "identified_result" | "imported";
}

export interface PendingIdentifiedModelState {
  model: Record<string, unknown>;
  model_ref: CanonicalObjectRef;
  kind: "IdentifiedModel";
  algorithm: string;
  summary: string;
  registered: boolean;
  response: RpcResponse;
  recorded_at: string;
}

export interface PendingDerivedModelState {
  model: Record<string, unknown>;
  model_ref: CanonicalObjectRef;
  kind: TypedObjectKind;
  source_ref: CanonicalObjectRef;
  source_model_ref: CanonicalObjectRef | null;
  target_kind: "native" | "StateSpace";
  dt: number | null;
  dimensions: Record<string, unknown>;
  derivation: Record<string, unknown>;
  warnings: WarningEntry[];
  summary: string;
  registration_required: true;
  registered: boolean;
  response: RpcResponse;
  derived_at: string;
}

export interface ReuseModelOptions {
  sourceRef?: CanonicalObjectRef;
  targetKind?: "native" | "StateSpace";
}

export interface ReuseModelOutcome {
  response: RpcResponse;
  derivedModel: Record<string, unknown>;
  derivedRef: CanonicalObjectRef;
  derivedKind: TypedObjectKind;
  sourceRef: CanonicalObjectRef;
  sourceModelRef: CanonicalObjectRef | null;
  targetKind: "native" | "StateSpace";
  dt: number | null;
  dimensions: Record<string, unknown>;
  derivation: Record<string, unknown>;
  warnings: WarningEntry[];
  registration_required: boolean;
}

export interface TypedExecutionPlan {
  operation: string;
  extraPayload: Record<string, unknown>;
  ephemeralWorkerRegistrations: RegisteredTypedObject[];
}

export interface TypedWorkspaceOptions {
  client: ControlLabEngineClient;
  projectIdProvider: () => string;
  projectRevisionProvider: () => number;
  activeLqrPlantProvider?: () => CanonicalStateSpaceModel | null;
  announcer?: AriaLiveAnnouncer;
  onError?: (err: unknown) => void;
}

const TS_MODEL_KIND_SET = new Set<string>(TS_MODEL_KINDS);
const TYPED_OBJECT_KIND_SET = new Set<string>(TYPED_OBJECT_KINDS);

const ROLE_ALLOWED_KINDS: Record<TypedSelectionRole, readonly TypedObjectKind[]> = {
  statespacePlant: ["StateSpace"],
  frequencyPlant: ["StateSpace", "TransferFunction"],
  dataset: ["Dataset"],
  valDataset: ["Dataset"],
  fuzzySystem: ["FuzzySystem"],
  tsModel: [...TS_MODEL_KINDS],
  validationModel: ["IdentifiedModel", "StateSpace", "TransferFunction"],
  reuseSource: [
    "IdentifiedModel",
    "TransferFunction",
    "StateSpace",
    ...TS_MODEL_KINDS,
  ],
};

const LTI_OPTIMIZATION_TEMPLATES = new Set<string>([
  "quadratic_stabilization",
  "continuous_stabilization",
  "decay_rate",
  "lqr_lmi",
  "regional_pole_placement",
]);

export function isTsModelKind(kind: string): kind is TsModelKind {
  return TS_MODEL_KIND_SET.has(kind);
}

export function isTypedObjectKind(kind: string): kind is TypedObjectKind {
  return TYPED_OBJECT_KIND_SET.has(kind);
}

export function getAllowedKindsForRole(
  role: TypedSelectionRole,
): readonly TypedObjectKind[] {
  return ROLE_ALLOWED_KINDS[role];
}

export function isKindAllowedForRole(
  kind: string,
  role: TypedSelectionRole,
): boolean {
  return ROLE_ALLOWED_KINDS[role].includes(kind as TypedObjectKind);
}

export function encodeObjectRefKey(ref: CanonicalObjectRef): string {
  return `${encodeURIComponent(ref.id)}#${String(ref.revision)}`;
}

export function decodeObjectRefKey(encoded: string): CanonicalObjectRef | null {
  if (typeof encoded !== "string" || encoded.trim().length === 0) {
    return null;
  }
  const sepIdx = encoded.lastIndexOf("#");
  if (sepIdx <= 0) {
    return null;
  }
  const rawId = encoded.slice(0, sepIdx);
  const rawRev = encoded.slice(sepIdx + 1);
  let id: string;
  try {
    id = decodeURIComponent(rawId);
  } catch {
    return null;
  }
  const revision = Number(rawRev);
  if (
    id.trim().length === 0 ||
    !Number.isInteger(revision) ||
    revision < 0
  ) {
    return null;
  }
  return { id, revision };
}

function cloneRecord(value: Record<string, unknown>): Record<string, unknown> {
  return structuredClone(value);
}

function assertNonEmptyStr(value: unknown, path: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser uma string não vazia.`,
    );
  }
  return value;
}

function assertRevisionInt(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser inteiro >= 0, recebido ${String(value)}.`,
    );
  }
  return value;
}

function assertSchemaVersion(value: unknown, path: string): "1.0.0" {
  if (value !== "1.0.0") {
    throw new ControlLabBridgeError(
      "SCHEMA_UNSUPPORTED",
      `${path}='${String(value)}' não é suportada (esperado '1.0.0').`,
    );
  }
  return "1.0.0";
}

function assertSampleTime(value: unknown, path: string): number | null {
  if (value === null) {
    return null;
  }
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser null (contínuo) ou número finito > 0.`,
    );
  }
  return value;
}

function assertRealFloat64Tensor(
  desc: TensorDescriptor,
  path: string,
): RealTensor {
  if (!("dtype" in desc) || !("data" in desc) || desc.dtype !== "float64") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser RealTensor com dtype='float64'.`,
    );
  }
  return desc;
}

function assertStringArray(
  value: unknown,
  path: string,
  expectedLength?: number,
): string[] {
  if (
    !Array.isArray(value) ||
    !value.every((item) => typeof item === "string" && item.trim().length > 0)
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser uma lista de strings não vazias.`,
    );
  }
  if (expectedLength !== undefined && value.length !== expectedLength) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `${path} deve possuir comprimento ${expectedLength}, recebido ${value.length}.`,
    );
  }
  return value;
}

function validateTransferFunctionDto(dto: Record<string, unknown>): string {
  const dt = assertSampleTime(dto.dt ?? null, "TransferFunction.dt");
  const variable = assertNonEmptyStr(dto.variable, "TransferFunction.variable");
  if (dt === null && variable !== "s") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `TransferFunction contínua (dt=null) exige variable='s', recebido '${variable}'.`,
    );
  }
  if (dt !== null && variable !== "z" && variable !== "z^-1") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `TransferFunction discreta (dt=${dt}) exige variable 'z' ou 'z^-1', recebido '${variable}'.`,
    );
  }
  if (dto.poly_order !== "descending" && dto.poly_order !== "ascending") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `TransferFunction.poly_order inválido: '${String(dto.poly_order)}'.`,
    );
  }
  if (!Array.isArray(dto.num) || dto.num.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "TransferFunction.num deve ser matriz 2D não vazia de polinômios.",
    );
  }
  if (!Array.isArray(dto.den) || dto.den.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "TransferFunction.den deve ser matriz 2D não vazia de polinômios.",
    );
  }
  const p = dto.num.length;
  if (dto.den.length !== p) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `TransferFunction num (${p} linhas) e den (${dto.den.length} linhas) diferem.`,
    );
  }
  let m: number | null = null;
  for (let i = 0; i < p; i += 1) {
    const numRow = dto.num[i];
    const denRow = dto.den[i];
    if (!Array.isArray(numRow) || !Array.isArray(denRow) || numRow.length === 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `TransferFunction.num[${i}] e den[${i}] devem ser linhas não vazias.`,
      );
    }
    if (m === null) {
      m = numRow.length;
    }
    if (numRow.length !== m || denRow.length !== m) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `TransferFunction linha ${i} com colunas incompatíveis.`,
      );
    }
    for (let j = 0; j < m; j += 1) {
      const nT = assertRealFloat64Tensor(
        validateTensorDescriptor(numRow[j], `TransferFunction.num[${i}][${j}]`),
        `TransferFunction.num[${i}][${j}]`,
      );
      const dT = assertRealFloat64Tensor(
        validateTensorDescriptor(denRow[j], `TransferFunction.den[${i}][${j}]`),
        `TransferFunction.den[${i}][${j}]`,
      );
      if (nT.shape.length !== 1 || nT.data.length === 0) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `TransferFunction.num[${i}][${j}] deve ser tensor 1D não vazio.`,
        );
      }
      if (dT.shape.length !== 1 || dT.data.length === 0) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `TransferFunction.den[${i}][${j}] deve ser tensor 1D não vazio.`,
        );
      }
    }
  }
  if (!isPlainObject(dto.units)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "TransferFunction.units deve ser um objeto.",
    );
  }
  const domainText = dt === null ? "contínuo (s)" : `discreto (${variable}, dt=${dt})`;
  return `TransferFunction (${p}x${String(m ?? 1)}, ${domainText})`;
}

function validateDatasetDto(dto: Record<string, unknown>): string {
  const t = assertRealFloat64Tensor(
    validateTensorDescriptor(dto.t, "Dataset.t"),
    "Dataset.t",
  );
  if (t.shape.length !== 1 || t.shape[0] < 1) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      "Dataset.t deve ser vetor 1D com ao menos 1 amostra.",
    );
  }
  for (let i = 1; i < t.data.length; i += 1) {
    if (t.data[i] <= t.data[i - 1]) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Dataset.t deve ser estritamente crescente.",
      );
    }
  }
  const u = assertRealFloat64Tensor(
    validateTensorDescriptor(dto.u, "Dataset.u"),
    "Dataset.u",
  );
  const y = assertRealFloat64Tensor(
    validateTensorDescriptor(dto.y, "Dataset.y"),
    "Dataset.y",
  );
  if (u.shape.length !== 2 || y.shape.length !== 2) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      "Dataset.u e Dataset.y devem ser matrizes 2D [N, canais].",
    );
  }
  const nSamples = t.shape[0];
  if (u.shape[0] !== nSamples || y.shape[0] !== nSamples) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Dataset com comprimentos incompatíveis: len(t)=${nSamples}, u=${u.shape[0]}, y=${y.shape[0]}.`,
    );
  }
  if (u.shape[1] < 1 || y.shape[1] < 1) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      "Dataset deve possuir ao menos 1 canal de entrada e 1 de saída.",
    );
  }
  const dt = dto.dt === undefined ? null : assertSampleTime(dto.dt, "Dataset.dt");
  if (!isPlainObject(dto.units)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Dataset.units deve ser um objeto.",
    );
  }
  return `Dataset (N=${nSamples}, m=${u.shape[1]}, p=${y.shape[1]}${dt !== null ? `, dt=${dt}` : ""})`;
}

function validateFuzzySystemDto(dto: Record<string, unknown>): string {
  if (dto.inference_type !== "mamdani" && dto.inference_type !== "ts") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `FuzzySystem.inference_type inválido: '${String(dto.inference_type)}'.`,
    );
  }
  if (!Array.isArray(dto.input_variables) || dto.input_variables.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "FuzzySystem.input_variables deve ser lista não vazia.",
    );
  }
  if (!Array.isArray(dto.output_variables) || dto.output_variables.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "FuzzySystem.output_variables deve ser lista não vazia.",
    );
  }
  for (const [role, vars] of [
    ["input_variables", dto.input_variables],
    ["output_variables", dto.output_variables],
  ] as const) {
    for (let i = 0; i < vars.length; i += 1) {
      const v = vars[i];
      if (!isPlainObject(v)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `FuzzySystem.${role}[${i}] deve ser objeto.`,
        );
      }
      assertNonEmptyStr(v.name, `FuzzySystem.${role}[${i}].name`);
      if (
        !Array.isArray(v.universe) ||
        v.universe.length !== 2 ||
        typeof v.universe[0] !== "number" ||
        typeof v.universe[1] !== "number" ||
        !Number.isFinite(v.universe[0]) ||
        !Number.isFinite(v.universe[1]) ||
        v.universe[0] >= v.universe[1]
      ) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `FuzzySystem.${role}[${i}].universe deve satisfazer [min, max] com min < max.`,
        );
      }
      if (!Array.isArray(v.terms) || v.terms.length === 0) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `FuzzySystem.${role}[${i}].terms deve ser lista não vazia.`,
        );
      }
    }
  }
  if (!Array.isArray(dto.rules)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "FuzzySystem.rules deve ser lista.",
    );
  }
  for (let i = 0; i < dto.rules.length; i += 1) {
    const r = dto.rules[i];
    if (!isPlainObject(r) || !isPlainObject(r.antecedents) || !isPlainObject(r.consequents)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `FuzzySystem.rules[${i}] requer antecedents e consequents.`,
      );
    }
  }
  return `FuzzySystem (${dto.inference_type}, ${dto.input_variables.length} entradas, ${dto.output_variables.length} saídas, ${dto.rules.length} regras)`;
}

function validateTsStateSpaceDto(dto: Record<string, unknown>, kind: TsModelKind): string {
  const dt = assertSampleTime(dto.dt ?? null, `${kind}.dt`);
  if (
    !isPlainObject(dto.membership_spec) ||
    !isPlainObject(dto.premise_availability) ||
    !isPlainObject(dto.domain) ||
    !isPlainObject(dto.units)
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${kind} requer membership_spec, premise_availability, domain e units.`,
    );
  }
  if (!Array.isArray(dto.vertices) || dto.vertices.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${kind}.vertices deve ser lista não vazia de vértices.`,
    );
  }
  const seenIds = new Set<string>();
  let nStates: number | null = null;
  let nInputs: number | null = null;
  let nOutputs: number | null = null;

  for (let i = 0; i < dto.vertices.length; i += 1) {
    const v = dto.vertices[i];
    if (!isPlainObject(v)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `${kind}.vertices[${i}] deve ser objeto.`,
      );
    }
    const vid = assertNonEmptyStr(v.vertex_id, `${kind}.vertices[${i}].vertex_id`);
    if (seenIds.has(vid)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `vertex_id duplicado em ${kind}: '${vid}'.`,
      );
    }
    seenIds.add(vid);
    const A = assertRealFloat64Tensor(validateTensorDescriptor(v.A, `vertices[${i}].A`), `vertices[${i}].A`);
    const B = assertRealFloat64Tensor(validateTensorDescriptor(v.B, `vertices[${i}].B`), `vertices[${i}].B`);
    const C = assertRealFloat64Tensor(validateTensorDescriptor(v.C, `vertices[${i}].C`), `vertices[${i}].C`);
    const D = assertRealFloat64Tensor(validateTensorDescriptor(v.D, `vertices[${i}].D`), `vertices[${i}].D`);
    if (A.shape.length !== 2 || A.shape[0] !== A.shape[1]) {
      throw new ControlLabBridgeError("DIMENSION_MISMATCH", `${kind}.vertices[${i}].A deve ser quadrada.`);
    }
    const n = A.shape[0];
    if (B.shape.length !== 2 || B.shape[0] !== n) {
      throw new ControlLabBridgeError("DIMENSION_MISMATCH", `${kind}.vertices[${i}].B incompatível com n=${n}.`);
    }
    const m = B.shape[1];
    if (C.shape.length !== 2 || C.shape[1] !== n) {
      throw new ControlLabBridgeError("DIMENSION_MISMATCH", `${kind}.vertices[${i}].C incompatível com n=${n}.`);
    }
    const p = C.shape[0];
    if (D.shape.length !== 2 || D.shape[0] !== p || D.shape[1] !== m) {
      throw new ControlLabBridgeError("DIMENSION_MISMATCH", `${kind}.vertices[${i}].D incompatível com (${p}, ${m}).`);
    }
    if (nStates === null) {
      nStates = n;
      nInputs = m;
      nOutputs = p;
    } else if (n !== nStates || m !== nInputs || p !== nOutputs) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `Dimensões de vértice ${i} em ${kind} diferem dos vértices anteriores.`,
      );
    }
  }
  assertStringArray(dto.state_names, `${kind}.state_names`, nStates ?? undefined);
  assertStringArray(dto.input_names, `${kind}.input_names`, nInputs ?? undefined);
  assertStringArray(dto.output_names, `${kind}.output_names`, nOutputs ?? undefined);
  return `${kind} (${dto.vertices.length} vértices, n=${String(nStates)}, m=${String(nInputs)}, p=${String(nOutputs)}${dt !== null ? `, dt=${dt}` : ""})`;
}

function validateIdentifiedModelDto(dto: Record<string, unknown>): string {
  const algorithm = assertNonEmptyStr(dto.algorithm, "IdentifiedModel.algorithm");
  if (!isPlainObject(dto.model)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "IdentifiedModel.model deve ser um objeto modelo canônico.",
    );
  }
  const innerKind = typeof dto.model.kind === "string" ? dto.model.kind : "desconhecido";
  if (
    innerKind === "StateSpace" ||
    innerKind === "TransferFunction" ||
    isTsModelKind(innerKind)
  ) {
    validateTypedCanonicalDto(dto.model);
  } else {
    throw new ControlLabBridgeError(
      "UNSUPPORTED_MODEL",
      `IdentifiedModel.model.kind inválido: '${innerKind}'.`,
    );
  }
  return `IdentifiedModel (${algorithm} -> ${innerKind})`;
}

export function validateTypedCanonicalDto(raw: unknown): {
  kind: TypedObjectKind;
  id: string;
  revision: number;
  dto: Record<string, unknown>;
  summary: string;
} {
  if (!isPlainObject(raw)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Objeto canônico deve ser um objeto JSON plano.",
    );
  }
  const clean = ensureFiniteJson(cloneRecord(raw), "$.object");
  const rawKind = clean.kind;
  if (rawKind === "TSStateSpace") {
    throw new ControlLabBridgeError(
      "UNSUPPORTED_MODEL",
      "Discriminante 'TSStateSpace' inválido na serialização; utilize 'ts_measured', 'polytopic_uncertain' ou 'ts_partially_observed'.",
    );
  }
  if (typeof rawKind !== "string" || !isTypedObjectKind(rawKind)) {
    throw new ControlLabBridgeError(
      "UNSUPPORTED_MODEL",
      `Tipo canônico não suportado para registro no workspace: '${String(rawKind)}'.`,
    );
  }

  assertSchemaVersion(clean.schema_version, `${rawKind}.schema_version`);
  const id = assertNonEmptyStr(clean.id, `${rawKind}.id`);
  const revision = assertRevisionInt(clean.revision, `${rawKind}.revision`);
  if (!isPlainObject(clean.provenance)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${rawKind}.provenance deve ser um objeto.`,
    );
  }

  let summary: string;
  if (rawKind === "StateSpace") {
    assertStringArray(clean.state_names, "StateSpace.state_names");
    assertStringArray(clean.input_names, "StateSpace.input_names");
    assertStringArray(clean.output_names, "StateSpace.output_names");
    if (!isPlainObject(clean.units)) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "StateSpace.units deve ser objeto.");
    }
    const ss = validateCanonicalStateSpace(clean as unknown as CanonicalStateSpaceModel);
    const n = ss.matrices.A.shape[0];
    const m = ss.matrices.B.shape[1];
    const p = ss.matrices.C.shape[0];
    summary = `StateSpace (n=${n}, m=${m}, p=${p}${ss.dt !== null ? `, dt=${ss.dt}` : ", contínuo"})`;
  } else if (rawKind === "TransferFunction") {
    summary = validateTransferFunctionDto(clean);
  } else if (rawKind === "Dataset") {
    summary = validateDatasetDto(clean);
  } else if (rawKind === "FuzzySystem") {
    summary = validateFuzzySystemDto(clean);
  } else if (rawKind === "IdentifiedModel") {
    summary = validateIdentifiedModelDto(clean);
  } else {
    summary = validateTsStateSpaceDto(clean, rawKind);
  }

  return {
    kind: rawKind,
    id,
    revision,
    dto: clean,
    summary,
  };
}

function summarizeStateSpacePlant(plant: CanonicalStateSpaceModel): string {
  const n = plant.matrices.A.shape[0];
  const m = plant.matrices.B.shape[1];
  const p = plant.matrices.C.shape[0];
  return `StateSpace (n=${n}, m=${m}, p=${p}${plant.dt !== null ? `, dt=${plant.dt}` : ", contínuo"})`;
}

function extractRefFromField(
  raw: unknown,
  fieldName: string,
): CanonicalObjectRef | null {
  if (raw === undefined || raw === null) {
    return null;
  }
  if (!isPlainObject(raw)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${fieldName} deve ser { id, revision }.`,
    );
  }
  const id = assertNonEmptyStr(raw.id, `${fieldName}.id`);
  const revision = assertRevisionInt(raw.revision, `${fieldName}.revision`);
  return { id, revision };
}

export class TypedObjectWorkspace {
  private readonly client: ControlLabEngineClient;
  private readonly projectIdProvider: () => string;
  private readonly projectRevisionProvider: () => number;
  private readonly activeLqrPlantProvider?: () => CanonicalStateSpaceModel | null;
  private readonly announcer?: AriaLiveAnnouncer;
  private readonly onError?: (err: unknown) => void;

  private readonly objects = new Map<string, RegisteredTypedObject>();
  private readonly selectedRefs: Record<TypedSelectionRole, CanonicalObjectRef | null> = {
    statespacePlant: null,
    frequencyPlant: null,
    dataset: null,
    valDataset: null,
    fuzzySystem: null,
    tsModel: null,
    validationModel: null,
    reuseSource: null,
  };

  private activeLqrMirror: RegisteredTypedObject | null = null;
  private pendingIdentifiedModel: PendingIdentifiedModelState | null = null;
  private pendingDerivedModel: PendingDerivedModelState | null = null;
  private lastReuseOutcome: ReuseModelOutcome | null = null;
  private readonly selectionVersionByRole: Record<TypedSelectionRole, number> = {
    statespacePlant: 0,
    frequencyPlant: 0,
    dataset: 0,
    valDataset: 0,
    fuzzySystem: 0,
    tsModel: 0,
    validationModel: 0,
    reuseSource: 0,
  };
  private readonly listeners = new Set<() => void>();

  constructor(options: TypedWorkspaceOptions) {
    this.client = options.client;
    this.projectIdProvider = options.projectIdProvider;
    this.projectRevisionProvider = options.projectRevisionProvider;
    this.activeLqrPlantProvider = options.activeLqrPlantProvider;
    this.announcer = options.announcer;
    this.onError = options.onError;

    if (this.activeLqrPlantProvider) {
      this.syncFromActiveLqrPlant(this.activeLqrPlantProvider());
    }
  }

  public syncFromActiveLqrPlant(plant: CanonicalStateSpaceModel | null): void {
    if (!plant) {
      if (this.activeLqrMirror === null) {
        return;
      }
      this.activeLqrMirror = null;
      this.notify();
      return;
    }
    const prevMirror = this.activeLqrMirror;
    if (
      prevMirror &&
      prevMirror.id === plant.id &&
      prevMirror.revision === plant.revision &&
      prevMirror.value.dt === plant.dt
    ) {
      return;
    }
    const key = encodeObjectRefKey({ id: plant.id, revision: plant.revision });
    const nextMirror: RegisteredTypedObject = {
      key,
      id: plant.id,
      revision: plant.revision,
      kind: "StateSpace",
      summary: summarizeStateSpacePlant(plant),
      value: structuredClone(plant) as unknown as Record<string, unknown>,
      persisted: false,
      registered_at: new Date().toISOString(),
      source: "lqr_plant",
    };
    this.activeLqrMirror = nextMirror;

    if (
      prevMirror &&
      this.selectedRefs.statespacePlant &&
      this.selectedRefs.statespacePlant.id === prevMirror.id &&
      this.selectedRefs.statespacePlant.revision === prevMirror.revision &&
      !this.objects.has(encodeObjectRefKey(this.selectedRefs.statespacePlant))
    ) {
      this.selectedRefs.statespacePlant = null;
    }
    if (
      prevMirror &&
      this.selectedRefs.frequencyPlant &&
      this.selectedRefs.frequencyPlant.id === prevMirror.id &&
      this.selectedRefs.frequencyPlant.revision === prevMirror.revision &&
      !this.objects.has(encodeObjectRefKey(this.selectedRefs.frequencyPlant))
    ) {
      this.selectedRefs.frequencyPlant = null;
    }
    this.notify();
  }

  private isRevisionStrictlyOlderThanSelected(
    id: string,
    revision: number,
    currentRef: CanonicalObjectRef | null,
  ): boolean {
    return (
      currentRef !== null &&
      currentRef.id === id &&
      revision < currentRef.revision
    );
  }

  public async registerTypedObject(
    rawDto: unknown,
    options?: {
      persistToIndexedDB?: boolean;
      pinProject?: boolean;
      source?: RegisteredTypedObject["source"];
      selectRole?: TypedSelectionRole;
    },
  ): Promise<RegisteredTypedObject> {
    const validated = validateTypedCanonicalDto(rawDto);
    const projectId = this.projectIdProvider();
    const persistToIndexedDB = options?.persistToIndexedDB ?? true;
    const targetRole = options?.selectRole;
    const roleVersionSnapshot = targetRole
      ? this.selectionVersionByRole[targetRole]
      : null;

    const regRef = await this.client.registerObject(
      projectId,
      validated.id,
      validated.revision,
      validated.dto,
      {
        kind: validated.kind,
        pinProject: options?.pinProject ?? true,
        persistToIndexedDB,
      },
    );

    const key = encodeObjectRefKey({ id: validated.id, revision: validated.revision });
    const entry: RegisteredTypedObject = {
      key,
      id: validated.id,
      revision: validated.revision,
      kind: validated.kind,
      summary: validated.summary,
      value: structuredClone(validated.dto),
      persisted: regRef.persisted,
      registered_at: new Date().toISOString(),
      source: options?.source ?? "manual",
    };
    this.objects.set(key, entry);

    const ref: CanonicalObjectRef = { id: entry.id, revision: entry.revision };
    if (targetRole) {
      const selectionAdvancedWhilePending =
        this.selectionVersionByRole[targetRole] !== roleVersionSnapshot;
      const currentSelected = this.selectedRefs[targetRole];
      if (
        !selectionAdvancedWhilePending &&
        !this.isRevisionStrictlyOlderThanSelected(entry.id, entry.revision, currentSelected)
      ) {
        this.selectRef(targetRole, ref);
      }
    } else {
      const maybeAutoSelect = (role: TypedSelectionRole) => {
        if (this.selectedRefs[role] === null) {
          this.selectedRefs[role] = ref;
          this.selectionVersionByRole[role] += 1;
        }
      };
      if (entry.kind === "Dataset") {
        maybeAutoSelect("dataset");
      } else if (entry.kind === "FuzzySystem") {
        maybeAutoSelect("fuzzySystem");
      } else if (isTsModelKind(entry.kind)) {
        maybeAutoSelect("tsModel");
        maybeAutoSelect("reuseSource");
      } else if (entry.kind === "TransferFunction") {
        maybeAutoSelect("frequencyPlant");
        maybeAutoSelect("reuseSource");
        maybeAutoSelect("validationModel");
      } else if (entry.kind === "IdentifiedModel") {
        maybeAutoSelect("reuseSource");
        maybeAutoSelect("validationModel");
      } else if (entry.kind === "StateSpace") {
        maybeAutoSelect("statespacePlant");
      }
    }

    this.announcer?.announce(
      `Objeto ${entry.kind} (${entry.id} rev. ${entry.revision}) registrado no projeto.`,
      "polite",
      "status",
    );
    this.notify();
    return structuredClone(entry);
  }

  public async rehydrateFromStorage(): Promise<RegisteredTypedObject[]> {
    const projectId = this.projectIdProvider();
    const restored: RegisteredTypedObject[] = [];
    try {
      if (typeof this.client.exportProject === "function") {
        const snap = await this.client.exportProject(projectId);
        if (snap && Array.isArray(snap.objects)) {
          for (const rec of snap.objects) {
            if (!rec || !isPlainObject(rec.value)) continue;
            try {
              const validated = validateTypedCanonicalDto(rec.value);
              const key = encodeObjectRefKey({ id: validated.id, revision: validated.revision });
              if (!this.objects.has(key)) {
                const entry: RegisteredTypedObject = {
                  key,
                  id: validated.id,
                  revision: validated.revision,
                  kind: validated.kind,
                  summary: validated.summary,
                  value: structuredClone(validated.dto),
                  persisted: true,
                  registered_at: rec.created_at ?? new Date().toISOString(),
                  source: "imported",
                };
                this.objects.set(key, entry);
                restored.push(structuredClone(entry));
              }
            } catch {
              // Ignorar objetos auxiliares não tipados (ex.: controladores)
            }
          }
        }
      }
      if (typeof this.client.getObject === "function") {
        for (const entry of this.objects.values()) {
          if (entry.persisted) {
            await this.client.getObject(projectId, entry.id, entry.revision);
          }
        }
      }
      this.notify();
    } catch {
      // Falhas transitórias de reidratação não quebram ciclo de vida
    }
    return restored;
  }

  public listRegisteredObjects(
    filterKinds?: readonly TypedObjectKind[],
  ): RegisteredTypedObject[] {
    const kindSet = filterKinds ? new Set<string>(filterKinds) : null;
    const out: RegisteredTypedObject[] = [];
    for (const entry of this.objects.values()) {
      if (kindSet && !kindSet.has(entry.kind)) continue;
      out.push(structuredClone(entry));
    }
    return out;
  }

  public listSelectableObjectsForRole(
    role: TypedSelectionRole,
  ): RegisteredTypedObject[] {
    const allowed = ROLE_ALLOWED_KINDS[role];
    const items = this.listRegisteredObjects(allowed);
    if (
      this.activeLqrMirror &&
      isKindAllowedForRole(this.activeLqrMirror.kind, role) &&
      !this.objects.has(this.activeLqrMirror.key)
    ) {
      items.unshift(structuredClone(this.activeLqrMirror));
    }
    return items;
  }

  public getRegisteredObject(
    ref: CanonicalObjectRef,
  ): RegisteredTypedObject | null {
    const found = this.objects.get(encodeObjectRefKey(ref));
    return found ? structuredClone(found) : null;
  }

  public getSelectableObject(
    ref: CanonicalObjectRef,
  ): RegisteredTypedObject | null {
    const key = encodeObjectRefKey(ref);
    const registered = this.objects.get(key);
    if (registered) {
      return structuredClone(registered);
    }
    if (this.activeLqrMirror && this.activeLqrMirror.key === key) {
      return structuredClone(this.activeLqrMirror);
    }
    return null;
  }

  public selectRef(
    role: TypedSelectionRole,
    ref: CanonicalObjectRef | null,
    options?: { allowHistoricalDowngrade?: boolean },
  ): CanonicalObjectRef | null {
    if (ref === null) {
      this.selectedRefs[role] = null;
      this.selectionVersionByRole[role] += 1;
      this.notify();
      return null;
    }
    const id = assertNonEmptyStr(ref.id, `${role}.id`);
    const revision = assertRevisionInt(ref.revision, `${role}.revision`);
    const found = this.getSelectableObject({ id, revision });
    if (!found) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Referência '${id}' (revisão ${revision}) não está registrada no projeto.`,
        { parameters: { role, id, revision } },
      );
    }
    if (!isKindAllowedForRole(found.kind, role)) {
      throw new ControlLabBridgeError(
        "UNSUPPORTED_MODEL",
        `Objeto '${id}' (kind='${found.kind}') não é compatível com '${role}' (permitido: ${ROLE_ALLOWED_KINDS[role].join(", ")}).`,
        {
          parameters: {
            role,
            id,
            revision,
            actual_kind: found.kind,
            allowed_kinds: [...ROLE_ALLOWED_KINDS[role]],
          },
        },
      );
    }
    const current = this.selectedRefs[role];
    if (
      !options?.allowHistoricalDowngrade &&
      current &&
      current.id === found.id &&
      found.revision < current.revision
    ) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Revisão antiga '${found.id}#${found.revision}' não pode sobrescrever seleção mais recente '${current.id}#${current.revision}' sem escolha explícita.`,
        {
          parameters: {
            role,
            id: found.id,
            requested_revision: found.revision,
            active_revision: current.revision,
          },
        },
      );
    }
    const cleanRef: CanonicalObjectRef = { id: found.id, revision: found.revision };
    this.selectedRefs[role] = cleanRef;
    this.selectionVersionByRole[role] += 1;
    this.notify();
    return { ...cleanRef };
  }

  public handleRoleKeyNavigation(
    role: TypedSelectionRole,
    key: string,
  ): { handled: boolean; selectedRef: CanonicalObjectRef | null } {
    const items = this.listSelectableObjectsForRole(role);
    if (items.length === 0) {
      return { handled: false, selectedRef: null };
    }
    const current = this.getEffectiveSelection(role)?.ref ?? null;
    const currentIndex = current
      ? items.findIndex(
          (item) => item.id === current.id && item.revision === current.revision,
        )
      : -1;

    let nextIndex = -1;
    if (key === "ArrowDown" || key === "ArrowRight") {
      nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % items.length;
    } else if (key === "ArrowUp" || key === "ArrowLeft") {
      nextIndex =
        currentIndex <= 0 ? items.length - 1 : (currentIndex - 1) % items.length;
    } else if (key === "Home") {
      nextIndex = 0;
    } else if (key === "End") {
      nextIndex = items.length - 1;
    } else {
      return { handled: false, selectedRef: current };
    }

    const chosen = items[nextIndex];
    const ref = this.selectRef(
      role,
      { id: chosen.id, revision: chosen.revision },
      { allowHistoricalDowngrade: true },
    );
    return { handled: true, selectedRef: ref };
  }

  public getSelectedRef(role: TypedSelectionRole): CanonicalObjectRef | null {
    const ref = this.selectedRefs[role];
    return ref ? { ...ref } : null;
  }

  public getEffectiveSelection(role: TypedSelectionRole): {
    ref: CanonicalObjectRef;
    object: RegisteredTypedObject;
    isFallback: boolean;
  } | null {
    const explicit = this.selectedRefs[role];
    if (explicit) {
      const obj = this.getSelectableObject(explicit);
      if (obj && isKindAllowedForRole(obj.kind, role)) {
        return { ref: { ...explicit }, object: obj, isFallback: false };
      }
    }
    if (role === "statespacePlant" && this.activeLqrMirror) {
      return {
        ref: { id: this.activeLqrMirror.id, revision: this.activeLqrMirror.revision },
        object: structuredClone(this.activeLqrMirror),
        isFallback: true,
      };
    }
    if (role === "frequencyPlant") {
      const ssEff = this.getEffectiveSelection("statespacePlant");
      if (ssEff && isKindAllowedForRole(ssEff.object.kind, "frequencyPlant")) {
        return { ...ssEff, isFallback: true };
      }
    }
    return null;
  }

  public getAllSelectedRefsSummary(): Record<
    TypedSelectionRole,
    { ref: CanonicalObjectRef | null; kind: TypedObjectKind | null; isFallback: boolean }
  > {
    const out = {} as Record<
      TypedSelectionRole,
      { ref: CanonicalObjectRef | null; kind: TypedObjectKind | null; isFallback: boolean }
    >;
    for (const role of TYPED_SELECTION_ROLES) {
      const eff = this.getEffectiveSelection(role);
      out[role] = eff
        ? { ref: eff.ref, kind: eff.object.kind, isFallback: eff.isFallback }
        : { ref: null, kind: null, isFallback: false };
    }
    return out;
  }

  public recordIdentifiedModelResult(
    rawIdentified: unknown,
    response: RpcResponse,
  ): PendingIdentifiedModelState {
    const validated = validateTypedCanonicalDto(rawIdentified);
    if (validated.kind !== "IdentifiedModel") {
      throw new ControlLabBridgeError(
        "UNSUPPORTED_MODEL",
        `Resultado de identificação deve ter kind='IdentifiedModel', recebido '${validated.kind}'.`,
      );
    }
    const state: PendingIdentifiedModelState = {
      model: validated.dto,
      model_ref: { id: validated.id, revision: validated.revision },
      kind: "IdentifiedModel",
      algorithm: String(validated.dto.algorithm ?? "identification"),
      summary: validated.summary,
      registered: this.objects.has(
        encodeObjectRefKey({ id: validated.id, revision: validated.revision }),
      ),
      response: structuredClone(response),
      recorded_at: new Date().toISOString(),
    };
    this.pendingIdentifiedModel = state;
    this.announcer?.announce(
      `Modelo identificado (${validated.id} rev. ${validated.revision}) disponível; registre explicitamente antes de reutilizar ou validar.`,
      "polite",
      "status",
    );
    this.notify();
    return structuredClone(state);
  }

  public getPendingIdentifiedModel(): PendingIdentifiedModelState | null {
    return this.pendingIdentifiedModel
      ? structuredClone(this.pendingIdentifiedModel)
      : null;
  }

  public async registerPendingIdentifiedModel(options?: {
    persistToIndexedDB?: boolean;
    selectForReuse?: boolean;
  }): Promise<RegisteredTypedObject> {
    if (!this.pendingIdentifiedModel) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Não há IdentifiedModel pendente de registro.",
      );
    }
    const registered = await this.registerTypedObject(
      this.pendingIdentifiedModel.model,
      {
        persistToIndexedDB: options?.persistToIndexedDB ?? true,
        source: "identified_result",
        selectRole:
          options?.selectForReuse === false ? undefined : "reuseSource",
      },
    );
    if (this.selectedRefs.validationModel === null) {
      this.selectedRefs.validationModel = {
        id: registered.id,
        revision: registered.revision,
      };
    }
    this.pendingIdentifiedModel = {
      ...this.pendingIdentifiedModel,
      registered: true,
    };
    this.notify();
    return registered;
  }

  public recordReuseResult(
    response: RpcResponse,
    targetKind: "native" | "StateSpace" = "native",
  ): PendingDerivedModelState {
    if (!response.result || !isPlainObject(response.result.model)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Resposta de core.reuse_model sem campo 'model' válido.",
      );
    }
    const validated = validateTypedCanonicalDto(response.result.model);
    const sourceRef = extractRefFromField(response.result.source_ref, "source_ref") ?? {
      id: validated.id,
      revision: validated.revision,
    };
    const sourceModelRef = extractRefFromField(
      response.result.source_model_ref,
      "source_model_ref",
    );
    const derivation = isPlainObject(response.result.derivation)
      ? structuredClone(response.result.derivation)
      : {};
    const dimensions = isPlainObject(response.result.dimensions)
      ? structuredClone(response.result.dimensions)
      : {};
    const dt =
      response.result.dt === null || typeof response.result.dt === "number"
        ? (response.result.dt as number | null)
        : null;
    const isAlreadyRegistered = this.objects.has(
      encodeObjectRefKey({ id: validated.id, revision: validated.revision }),
    );
    const pending: PendingDerivedModelState = {
      model: validated.dto,
      model_ref: { id: validated.id, revision: validated.revision },
      kind: validated.kind,
      source_ref: sourceRef,
      source_model_ref: sourceModelRef,
      target_kind: targetKind,
      dt,
      dimensions,
      derivation,
      warnings: [...response.warnings],
      summary: validated.summary,
      registration_required: true,
      registered: isAlreadyRegistered,
      response: structuredClone(response),
      derived_at: new Date().toISOString(),
    };
    this.pendingDerivedModel = pending;
    this.notify();
    return structuredClone(pending);
  }

  public getPendingDerivedModel(): PendingDerivedModelState | null {
    return this.pendingDerivedModel
      ? structuredClone(this.pendingDerivedModel)
      : null;
  }

  public getLastReuseOutcome(): ReuseModelOutcome | null {
    return this.lastReuseOutcome ? structuredClone(this.lastReuseOutcome) : null;
  }

  public async registerPendingDerivedModel(options?: {
    persistToIndexedDB?: boolean;
    selectCompatible?: boolean;
  }): Promise<RegisteredTypedObject> {
    if (!this.pendingDerivedModel) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Não há modelo derivado pendente de registro.",
      );
    }
    const derived = this.pendingDerivedModel;
    const registered = await this.registerTypedObject(derived.model, {
      persistToIndexedDB: options?.persistToIndexedDB ?? true,
      source: "derived_reuse",
    });
    this.pendingDerivedModel = {
      ...derived,
      registered: true,
    };
    if (options?.selectCompatible) {
      const ref = { id: registered.id, revision: registered.revision };
      if (registered.kind === "StateSpace") {
        this.selectedRefs.statespacePlant = ref;
        this.selectedRefs.frequencyPlant = ref;
      } else if (registered.kind === "TransferFunction") {
        this.selectedRefs.frequencyPlant = ref;
      } else if (isTsModelKind(registered.kind)) {
        this.selectedRefs.tsModel = ref;
      }
    }
    this.announcer?.announce(
      `Derivado ${registered.kind} (${registered.id} rev. ${registered.revision}) registrado explicitamente no projeto.`,
      "polite",
      "status",
    );
    this.notify();
    return registered;
  }

  public async reuseModel(
    options?: ReuseModelOptions,
  ): Promise<ReuseModelOutcome> {
    const targetKind = options?.targetKind ?? "native";
    if (targetKind !== "native" && targetKind !== "StateSpace") {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `target_kind inválido para core.reuse_model: '${String(targetKind)}'.`,
      );
    }
    const selectedEff = options?.sourceRef
      ? null
      : this.getEffectiveSelection("reuseSource");
    const sourceRef = options?.sourceRef ?? selectedEff?.ref ?? null;
    if (!sourceRef) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Selecione ou registre um modelo de origem (IdentifiedModel, TransferFunction, StateSpace ou TS) antes de executar core.reuse_model.",
      );
    }
    const cleanRef: CanonicalObjectRef = {
      id: assertNonEmptyStr(sourceRef.id, "model_ref.id"),
      revision: assertRevisionInt(sourceRef.revision, "model_ref.revision"),
    };

    const known = this.getSelectableObject(cleanRef);
    if (known) {
      if (!isKindAllowedForRole(known.kind, "reuseSource")) {
        throw new ControlLabBridgeError(
          "UNSUPPORTED_MODEL",
          `core.reuse_model não suporta objetos '${known.kind}'; selecione IdentifiedModel, StateSpace, TransferFunction ou TSStateSpace.`,
          { parameters: { id: known.id, revision: known.revision, kind: known.kind } },
        );
      }
      await this.ensureRegisteredInWorkerRam(known);
    }

    const projectId = this.projectIdProvider();
    const projectRev = this.projectRevisionProvider();
    const response = await this.client.execute(
      {
        api_version: RPC_API_VERSION,
        request_id: `reuse-${generateUuid()}`,
        project_id: projectId,
        project_revision: projectRev,
        operation: "core.reuse_model",
        payload: {
          model_ref: cleanRef,
          target_kind: targetKind,
        },
        options: {},
        timeout_policy: { hard_timeout_ms: 30000, cancel_on_supersede: true },
      },
      { commitOnSuccess: false },
    );

    if (response.status === "failure" || response.status === "inconclusive" || !response.result) {
      const err = response.error ?? {
        code: "VALIDATION_ERROR" as const,
        message: "core.reuse_model não produziu um modelo derivado válido.",
      };
      const bridgeErr = new ControlLabBridgeError(err.code, err.message, {
        parameters: err.parameters,
        next_step: err.next_step,
        details: err.details,
      });
      this.onError?.(bridgeErr);
      throw bridgeErr;
    }

    const pending = this.recordReuseResult(response, targetKind);
    const outcome: ReuseModelOutcome = {
      response: structuredClone(response),
      derivedModel: structuredClone(pending.model),
      derivedRef: { ...pending.model_ref },
      derivedKind: pending.kind,
      sourceRef: { ...pending.source_ref },
      sourceModelRef: pending.source_model_ref
        ? { ...pending.source_model_ref }
        : null,
      targetKind,
      dt: pending.dt,
      dimensions: structuredClone(pending.dimensions),
      derivation: structuredClone(pending.derivation),
      warnings: [...pending.warnings],
      registration_required: true,
    };
    this.lastReuseOutcome = outcome;
    this.announcer?.announce(
      `Modelo derivado (${outcome.derivedKind} id=${outcome.derivedRef.id} rev=${outcome.derivedRef.revision}) aguardando registro explícito.`,
      "polite",
      "status",
    );
    this.notify();
    return structuredClone(outcome);
  }

  private async ensureRegisteredInWorkerRam(
    entry: RegisteredTypedObject,
  ): Promise<void> {
    const projectId = this.projectIdProvider();
    if (entry.persisted && typeof this.client.getObject === "function") {
      const existing = await this.client.getObject(projectId, entry.id, entry.revision);
      if (existing) {
        return;
      }
    }
    await this.client.registerObject(
      projectId,
      entry.id,
      entry.revision,
      structuredClone(entry.value),
      {
        kind: entry.kind,
        pinProject: true,
        persistToIndexedDB: false,
      },
    );
  }

  private assertKnownRefCompatible(
    ref: CanonicalObjectRef,
    allowedKinds: readonly TypedObjectKind[],
    contextLabel: string,
  ): RegisteredTypedObject | null {
    const known = this.getSelectableObject(ref);
    if (!known) {
      return null;
    }
    if (!allowedKinds.includes(known.kind)) {
      throw new ControlLabBridgeError(
        "UNSUPPORTED_MODEL",
        `Referência '${known.id}' (kind='${known.kind}') é incompatível com ${contextLabel}; esperado: ${allowedKinds.join(", ")}.`,
        {
          parameters: {
            context: contextLabel,
            id: known.id,
            revision: known.revision,
            actual_kind: known.kind,
            allowed_kinds: [...allowedKinds],
          },
        },
      );
    }
    return known;
  }

  public async prepareToolExecution(
    operation: string,
    sanitizedParams: Record<string, unknown>,
    options?: {
      extraPayload?: Record<string, unknown>;
      feedbackSign?: FeedbackSign;
    },
  ): Promise<TypedExecutionPlan> {
    const provided = options?.extraPayload ? { ...options.extraPayload } : {};
    const ephemeralWorkerRegistrations: RegisteredTypedObject[] = [];

    const ensureAndTrack = async (obj: RegisteredTypedObject | null): Promise<void> => {
      if (!obj) return;
      await this.ensureRegisteredInWorkerRam(obj);
      if (!obj.persisted) {
        ephemeralWorkerRegistrations.push(obj);
      }
    };

    // 1. Identificação: fit_arx / fit_oe / fit_subspace -> Dataset(s) apenas!
    if (
      operation === "identification.fit_arx" ||
      operation === "identification.fit_oe" ||
      operation === "identification.fit_subspace"
    ) {
      if ("plant_ref" in provided || "plant" in provided || "model_ref" in provided || "model" in provided) {
        throw new ControlLabBridgeError(
          "UNSUPPORTED_MODEL",
          `Operação '${operation}' exige Dataset (dataset_ref) e proíbe envio de plant_ref/model_ref.`,
        );
      }
      if ("u" in sanitizedParams || "y" in sanitizedParams || "t" in sanitizedParams) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Operação '${operation}' utiliza dataset_ref registrado em vez de séries brutas u/y/t.`,
        );
      }
      const explicitDsRef = extractRefFromField(provided.dataset_ref, "dataset_ref");
      if (explicitDsRef) {
        const known = this.assertKnownRefCompatible(explicitDsRef, ["Dataset"], operation);
        await ensureAndTrack(known);
        const explicitValRef = extractRefFromField(provided.val_dataset_ref, "val_dataset_ref");
        if (explicitValRef) {
          const knownVal = this.assertKnownRefCompatible(explicitValRef, ["Dataset"], `${operation}.val_dataset_ref`);
          await ensureAndTrack(knownVal);
        }
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      if ("dataset" in provided) {
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      const dsEff = this.getEffectiveSelection("dataset");
      if (!dsEff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Selecione ou registre um objeto Dataset de treino antes de executar '${operation}'.`,
        );
      }
      await ensureAndTrack(dsEff.object);
      const outPayload: Record<string, unknown> = {
        ...provided,
        dataset_ref: { ...dsEff.ref },
      };
      const valEff = this.getEffectiveSelection("valDataset");
      if (valEff && !(valEff.ref.id === dsEff.ref.id && valEff.ref.revision === dsEff.ref.revision)) {
        await ensureAndTrack(valEff.object);
        outPayload.val_dataset_ref = { ...valEff.ref };
      } else if (valEff && provided.val_dataset_ref === undefined && this.selectedRefs.valDataset !== null) {
        await ensureAndTrack(valEff.object);
        outPayload.val_dataset_ref = { ...valEff.ref };
      }
      return { operation, extraPayload: outPayload, ephemeralWorkerRegistrations };
    }

    // 2. Validação de modelo identificado -> model_ref + val_dataset_ref
    if (operation === "identification.validate_model") {
      if ("plant_ref" in provided) {
        throw new ControlLabBridgeError(
          "UNSUPPORTED_MODEL",
          "identification.validate_model exige model_ref e val_dataset_ref explícitos.",
        );
      }
      const explicitModelRef = extractRefFromField(provided.model_ref, "model_ref");
      const explicitValRef = extractRefFromField(provided.val_dataset_ref, "val_dataset_ref");
      const outPayload: Record<string, unknown> = { ...provided };
      if (explicitModelRef) {
        const known = this.assertKnownRefCompatible(
          explicitModelRef,
          ["IdentifiedModel", "StateSpace", "TransferFunction"],
          operation,
        );
        await ensureAndTrack(known);
      } else if (!("model" in provided)) {
        const modelEff =
          this.getEffectiveSelection("validationModel") ??
          (() => {
            const reuseEff = this.getEffectiveSelection("reuseSource");
            return reuseEff && isKindAllowedForRole(reuseEff.object.kind, "validationModel")
              ? reuseEff
              : null;
          })();
        if (!modelEff) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            "Selecione ou registre um IdentifiedModel/TransferFunction/StateSpace antes de executar identification.validate_model.",
          );
        }
        await ensureAndTrack(modelEff.object);
        outPayload.model_ref = { ...modelEff.ref };
      }

      if (explicitValRef) {
        const knownVal = this.assertKnownRefCompatible(explicitValRef, ["Dataset"], `${operation}.val_dataset_ref`);
        await ensureAndTrack(knownVal);
      } else if (!("val_dataset" in provided)) {
        const valEff = this.getEffectiveSelection("valDataset") ?? this.getEffectiveSelection("dataset");
        if (!valEff) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            "Selecione ou registre um Dataset de validação antes de executar identification.validate_model.",
          );
        }
        await ensureAndTrack(valEff.object);
        outPayload.val_dataset_ref = { ...valEff.ref };
      }

      const explicitTrainRef = extractRefFromField(provided.train_dataset_ref, "train_dataset_ref");
      if (explicitTrainRef) {
        const knownTrain = this.assertKnownRefCompatible(explicitTrainRef, ["Dataset"], `${operation}.train_dataset_ref`);
        await ensureAndTrack(knownTrain);
      } else if (!("train_dataset" in provided) && this.selectedRefs.dataset !== null) {
        const trainEff = this.getEffectiveSelection("dataset");
        if (trainEff) {
          await ensureAndTrack(trainEff.object);
          outPayload.train_dataset_ref = { ...trainEff.ref };
        }
      }
      return { operation, extraPayload: outPayload, ephemeralWorkerRegistrations };
    }

    // 3. Fuzzy -> system_ref (FuzzySystem) apenas!
    if (
      operation === "fuzzy.evaluate" ||
      operation === "fuzzy.evaluate_surface" ||
      operation === "fuzzy.export_fml"
    ) {
      if ("plant_ref" in provided || "plant" in provided || "model_ref" in provided) {
        throw new ControlLabBridgeError(
          "UNSUPPORTED_MODEL",
          `Operação '${operation}' exige FuzzySystem (system_ref) e proíbe envio de plant_ref/StateSpace.`,
        );
      }
      if ("inputs" in sanitizedParams && typeof sanitizedParams.inputs === "string") {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Campo 'inputs' de fuzzy.evaluate deve ser um objeto JSON válido.",
        );
      }
      const explicitSysRef = extractRefFromField(provided.system_ref, "system_ref");
      if (explicitSysRef) {
        const known = this.assertKnownRefCompatible(explicitSysRef, ["FuzzySystem"], operation);
        await ensureAndTrack(known);
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      if ("system" in provided) {
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      const fuzzyEff = this.getEffectiveSelection("fuzzySystem");
      if (!fuzzyEff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Selecione ou registre um objeto FuzzySystem antes de executar '${operation}'.`,
        );
      }
      await ensureAndTrack(fuzzyEff.object);
      return {
        operation,
        extraPayload: { ...provided, system_ref: { ...fuzzyEff.ref } },
        ephemeralWorkerRegistrations,
      };
    }

    // 4. Frequência / MIMO -> StateSpace ou TransferFunction
    if (operation.startsWith("frequency.") || operation.startsWith("mimo.")) {
      const explicitRef =
        extractRefFromField(provided.plant_ref, "plant_ref") ??
        extractRefFromField(provided.model_ref, "model_ref");
      if (explicitRef) {
        const known = this.assertKnownRefCompatible(
          explicitRef,
          ["StateSpace", "TransferFunction"],
          operation,
        );
        await ensureAndTrack(known);
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      if ("plant" in provided || "model" in provided) {
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      const freqEff = this.getEffectiveSelection("frequencyPlant");
      if (!freqEff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Selecione um modelo StateSpace ou TransferFunction antes de executar '${operation}'.`,
        );
      }
      await ensureAndTrack(freqEff.object);
      return {
        operation,
        extraPayload: { ...provided, plant_ref: { ...freqEff.ref } },
        ephemeralWorkerRegistrations,
      };
    }

    // 5. Espaço de Estados -> StateSpace apenas!
    if (operation.startsWith("statespace.")) {
      if ("A" in sanitizedParams || "B" in sanitizedParams || "C" in sanitizedParams || "D" in sanitizedParams) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Operação '${operation}' usa plant_ref registrado em vez de matrizes A/B/C/D concorrentes.`,
        );
      }
      const explicitRef =
        extractRefFromField(provided.plant_ref, "plant_ref") ??
        extractRefFromField(provided.model_ref, "model_ref");
      if (explicitRef) {
        const known = this.assertKnownRefCompatible(explicitRef, ["StateSpace"], operation);
        await ensureAndTrack(known);
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      if ("plant" in provided || "model" in provided) {
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      const ssEff = this.getEffectiveSelection("statespacePlant");
      if (!ssEff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Selecione um objeto StateSpace antes de executar '${operation}'.`,
        );
      }
      await ensureAndTrack(ssEff.object);
      return {
        operation,
        extraPayload: { ...provided, plant_ref: { ...ssEff.ref } },
        ephemeralWorkerRegistrations,
      };
    }

    // 6. Otimização / LMI (templates LTI, ts_pdc_stabilization, hinf_brl, problem JSON)
    if (
      operation === "optimization.solve" ||
      operation === "optimization.verify" ||
      operation === "optimization.export_cvxpy" ||
      operation === "optimization.export_yalmip"
    ) {
      if (sanitizedParams.problem !== undefined) {
        if (!isPlainObject(sanitizedParams.problem)) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            "Campo 'problem' deve ser um CanonicalSDPProblem JSON válido.",
          );
        }
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      if ("problem" in provided || "canonical_sdp" in provided || operation === "optimization.verify") {
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      if (sanitizedParams.premise_estimator !== undefined && !isPlainObject(sanitizedParams.premise_estimator)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Campo 'premise_estimator' deve ser um objeto JSON válido.",
        );
      }

      const template =
        typeof sanitizedParams.template === "string"
          ? sanitizedParams.template.trim().toLowerCase()
          : typeof provided.template === "string"
            ? provided.template.trim().toLowerCase()
            : "";

      if (template === "ts_pdc_stabilization") {
        if ("plant_ref" in provided) {
          const explicitPlantRef = extractRefFromField(provided.plant_ref, "plant_ref");
          if (explicitPlantRef) {
            this.assertKnownRefCompatible(explicitPlantRef, TS_MODEL_KINDS, "ts_pdc_stabilization");
          }
        }
        const explicitTsRef = extractRefFromField(provided.ts_model_ref, "ts_model_ref");
        if (explicitTsRef) {
          const knownTs = this.assertKnownRefCompatible(
            explicitTsRef,
            TS_MODEL_KINDS,
            "ts_pdc_stabilization",
          );
          await ensureAndTrack(knownTs);
          return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
        }
        if ("ts_model" in provided) {
          return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
        }
        const tsEff = this.getEffectiveSelection("tsModel");
        if (!tsEff) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            "Template 'ts_pdc_stabilization' exige um objeto TSStateSpace registrado (ts_measured, polytopic_uncertain ou ts_partially_observed).",
          );
        }
        await ensureAndTrack(tsEff.object);
        return {
          operation,
          extraPayload: {
            ...provided,
            ts_model_ref: { ...tsEff.ref },
            ...(options?.feedbackSign && provided.feedback_sign === undefined
              ? { feedback_sign: options.feedbackSign }
              : {}),
          },
          ephemeralWorkerRegistrations,
        };
      }

      if (template === "hinf_brl" || template === "") {
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }

      if (LTI_OPTIMIZATION_TEMPLATES.has(template)) {
        const explicitRef = extractRefFromField(provided.plant_ref, "plant_ref");
        if (explicitRef) {
          const known = this.assertKnownRefCompatible(explicitRef, ["StateSpace"], `${operation}:${template}`);
          await ensureAndTrack(known);
          return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
        }
        if ("plant" in provided) {
          return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
        }
        const ssEff = this.getEffectiveSelection("statespacePlant");
        if (!ssEff) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Template '${template}' exige um objeto StateSpace selecionado.`,
          );
        }
        await ensureAndTrack(ssEff.object);
        return {
          operation,
          extraPayload: {
            ...provided,
            plant_ref: { ...ssEff.ref },
            ...(options?.feedbackSign && provided.feedback_sign === undefined
              ? { feedback_sign: options.feedbackSign }
              : {}),
          },
          ephemeralWorkerRegistrations,
        };
      }

      return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
    }

    // 7. Reutilização canônica -> model_ref
    if (operation === "core.reuse_model") {
      const explicitRef = extractRefFromField(provided.model_ref, "model_ref");
      if (explicitRef) {
        const known = this.assertKnownRefCompatible(
          explicitRef,
          ROLE_ALLOWED_KINDS.reuseSource,
          operation,
        );
        await ensureAndTrack(known);
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      if ("model" in provided) {
        return { operation, extraPayload: provided, ephemeralWorkerRegistrations };
      }
      const reuseEff = this.getEffectiveSelection("reuseSource");
      if (!reuseEff) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Selecione ou registre um modelo de origem antes de executar core.reuse_model.",
        );
      }
      await ensureAndTrack(reuseEff.object);
      return {
        operation,
        extraPayload: { ...provided, model_ref: { ...reuseEff.ref } },
        ephemeralWorkerRegistrations,
      };
    }

    // Fallback seguro para ferramentas customizadas desconhecidas: nunca injeta plant_ref cegamente.
    return {
      operation,
      extraPayload: provided,
      ephemeralWorkerRegistrations,
    };
  }

  public async prepareSdpExportSpecification(
    sanitizedParams: Record<string, unknown>,
    feedbackSign: FeedbackSign,
  ): Promise<Record<string, unknown>> {
    const plan = await this.prepareToolExecution("optimization.solve", sanitizedParams, {
      feedbackSign,
    });
    return {
      ...sanitizedParams,
      ...plan.extraPayload,
    };
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
