/**
 * Contrato RPC v1.0, validadores estritos, tratamento de erros tipados (12 categorias)
 * e utilitários de transferência binária via ArrayBuffer (CL-DIR-001 Seções 4.1, 4.4, 8.1, 8.4, 11.1, Apêndice A).
 *
 * 100% compatível com navegador / Web Worker / Service Worker e TypeScript `erasableSyntaxOnly`.
 */

export const RPC_API_VERSION = "1.0" as const;
export type RpcApiVersion = typeof RPC_API_VERSION;

export const RESULT_STATUSES = [
  "success",
  "warning",
  "inconclusive",
  "failure",
] as const;
export type ResultStatus = (typeof RESULT_STATUSES)[number];

export const ERROR_CATEGORIES = [
  "VALIDATION_ERROR",
  "DIMENSION_MISMATCH",
  "UNSUPPORTED_MODEL",
  "HYPOTHESIS_VIOLATED",
  "NUMERICAL_INCONCLUSIVE",
  "SOLVER_UNAVAILABLE",
  "RESOURCE_LIMIT",
  "CANCELLED",
  "WORKER_RESTARTED",
  "SCHEMA_UNSUPPORTED",
  "IMPORT_UNTRUSTED_CODE",
  "INTERNAL_ERROR",
] as const;
export type ErrorCategory = (typeof ERROR_CATEGORIES)[number];

export const ENGINE_LIFECYCLE_STATES = [
  "uninitialized",
  "loading",
  "ready",
  "error",
  "recovering",
] as const;
export type EngineLifecycleState = (typeof ENGINE_LIFECYCLE_STATES)[number];

export const REAL_DTYPES = [
  "float64",
  "float32",
  "int64",
  "int32",
  "bool",
] as const;
export type RealDType = (typeof REAL_DTYPES)[number];

export const COMPLEX_DTYPES = ["complex128", "complex64"] as const;
export type ComplexDType = (typeof COMPLEX_DTYPES)[number];

export type TensorDType = RealDType | ComplexDType;

export const MEMORY_ORDERS = ["C", "F"] as const;
export type MemoryOrder = (typeof MEMORY_ORDERS)[number];

export const OPERATION_NAME_RE = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/;

const RESULT_STATUS_SET = new Set<string>(RESULT_STATUSES);
const ERROR_CATEGORY_SET = new Set<string>(ERROR_CATEGORIES);
const REAL_DTYPE_SET = new Set<string>(REAL_DTYPES);
const COMPLEX_DTYPE_SET = new Set<string>(COMPLEX_DTYPES);
const MEMORY_ORDER_SET = new Set<string>(MEMORY_ORDERS);

export interface RealTensor {
  shape: number[];
  dtype: RealDType;
  order: MemoryOrder;
  data: number[];
}

export interface ComplexTensor {
  shape: number[];
  dtype: ComplexDType;
  order: MemoryOrder;
  real: number[];
  imag: number[];
}

export interface ComplexVectorPair {
  real: number[];
  imag: number[];
}

export interface BufferTensorRef {
  shape: number[];
  dtype: TensorDType;
  order: MemoryOrder;
  buffer_ref: string;
}

export type TensorDescriptor =
  | RealTensor
  | ComplexTensor
  | ComplexVectorPair
  | BufferTensorRef;

export interface PackedSparseCooPayload {
  k_idx: Int32Array | number[] | TensorDescriptor | BufferTensorRef;
  rows: Int32Array | number[] | TensorDescriptor | BufferTensorRef;
  cols: Int32Array | number[] | TensorDescriptor | BufferTensorRef;
  vals: Float64Array | number[] | TensorDescriptor | BufferTensorRef;
}

const PACKED_SPARSE_INT32_FIELDS = new Set<string>(["k_idx", "rows", "cols"]);
const PACKED_SPARSE_FLOAT64_FIELDS = new Set<string>(["vals"]);

export interface WarningItem {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  [key: string]: unknown;
}

export type WarningEntry = string | WarningItem;

export interface TypedError {
  code: ErrorCategory;
  message: string;
  parameters?: Record<string, unknown>;
  next_step?: string;
  details?: Record<string, unknown>;
}

export interface Provenance {
  algorithm: string;
  lib_versions: Record<string, string>;
  seed?: number | null;
  tolerances?: Record<string, unknown>;
  model_revision?: number | null;
  timestamp?: string;
  [key: string]: unknown;
}

export interface TimeoutPolicy {
  hard_timeout_ms: number;
  soft_timeout_ms?: number;
  cancel_on_supersede?: boolean;
  [key: string]: unknown;
}

export interface RpcRequest {
  api_version: RpcApiVersion;
  request_id: string;
  project_id: string;
  project_revision: number;
  operation: string;
  payload: Record<string, unknown>;
  options: Record<string, unknown>;
  timeout_policy: TimeoutPolicy;
}

export interface RpcResponse {
  api_version: RpcApiVersion;
  request_id: string;
  project_id: string;
  project_revision: number;
  status: ResultStatus;
  result: Record<string, unknown> | null;
  assumptions: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  provenance: Provenance;
  warnings: WarningEntry[];
  error: TypedError | null;
}

export type MaturityLevel =
  | "stable"
  | "beta"
  | "experimental"
  | "unavailable_wasm";

export interface CapabilityDescriptor {
  api_version: RpcApiVersion;
  engine_kind: "mock" | "pyodide";
  runtime_id: string;
  operations: string[];
  backends: Record<string, unknown>;
  supports_transferables: boolean;
  supports_cooperative_cancel: boolean;
  offline_ready: boolean;
  max_memory_bytes: number;
  maturity: Record<string, MaturityLevel>;
  lib_versions: Record<string, string>;
}

export interface ExecutionMetrics {
  T_download: number | null;
  T_init_pyodide: number | null;
  T_import_packages: number | null;
  T_first_call: number | null;
  T_warm_call: number | null;
  T_bridge_transfer: number | null;
  call_count: number;
  cold_completed: boolean;
  last_request_id: string | null;
  warm_calls_count: number;
  warm_call_avg_ms: number | null;
}

export interface SolverProgress {
  iter: number;
  max_iters: number;
  gap: number;
  primal_res: number;
  dual_res: number;
  min_eig: number;
  alpha: number;
  elapsed_ms: number;
}

export interface SolverProgressEvent {
  request_id: string;
  progress: SolverProgress;
}

export interface WireBinaryBuffer {
  buffer_ref: string;
  shape: number[];
  dtype: TensorDType;
  order: MemoryOrder;
  buffer: ArrayBuffer;
  byte_length: number;
  imag_buffer?: ArrayBuffer;
  imag_byte_length?: number;
  packed_sparse?: boolean;
}

export interface BinaryTensorInput {
  shape: number[];
  dtype: TensorDType;
  order?: MemoryOrder;
  buffer: ArrayBuffer;
  byteOffset?: number;
  byteLength?: number;
  imagBuffer?: ArrayBuffer;
  imagByteOffset?: number;
  imagByteLength?: number;
}

export interface ExtractedTransferables {
  descriptors: Record<string, BufferTensorRef>;
  binaryEntries: Record<string, WireBinaryBuffer>;
  transferList: ArrayBuffer[];
  sourceBuffers: Array<{
    buffer_ref: string;
    buffer: ArrayBuffer;
    expectedByteLength: number;
  }>;
  preservedSenderCopy: boolean;
}

export class ControlLabBridgeError extends Error {
  public readonly typedError: TypedError;
  public readonly code: ErrorCategory;

  constructor(
    code: ErrorCategory,
    message: string,
    options?: {
      parameters?: Record<string, unknown>;
      next_step?: string;
      details?: Record<string, unknown>;
      cause?: unknown;
    },
  ) {
    super(`[${code}] ${message}`);
    this.name = "ControlLabBridgeError";
    this.code = code;
    const typed: TypedError = {
      code,
      message,
    };
    if (options?.parameters !== undefined) {
      typed.parameters = sanitizeOptionalRecord(options.parameters, "$.error.parameters");
    }
    if (options?.next_step !== undefined) {
      typed.next_step = options.next_step;
    }
    if (options?.details !== undefined) {
      typed.details = sanitizeOptionalRecord(options.details, "$.error.details");
    }
    this.typedError = typed;
    if (options?.cause !== undefined) {
      (this as { cause?: unknown }).cause = options.cause;
    }
  }
}

export function createTypedError(
  code: ErrorCategory,
  message: string,
  options?: {
    parameters?: Record<string, unknown>;
    next_step?: string;
    details?: Record<string, unknown>;
  },
): TypedError {
  if (!ERROR_CATEGORY_SET.has(code)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Categoria de erro inválida: ${String(code)}`,
      { parameters: { code } },
    );
  }
  if (typeof message !== "string" || message.trim().length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "TypedError.message deve ser uma string não vazia.",
    );
  }
  const out: TypedError = { code, message };
  if (options?.parameters !== undefined) {
    out.parameters = sanitizeOptionalRecord(options.parameters, "$.error.parameters");
  }
  if (options?.next_step !== undefined) {
    if (typeof options.next_step !== "string") {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "TypedError.next_step deve ser string.",
      );
    }
    out.next_step = options.next_step;
  }
  if (options?.details !== undefined) {
    out.details = sanitizeOptionalRecord(options.details, "$.error.details");
  }
  return out;
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

export function isPyProxyLike(value: unknown): boolean {
  if ((typeof value !== "object" && typeof value !== "function") || value === null) {
    return false;
  }
  const rec = value as Record<string, unknown>;
  if (rec.__isPyProxy === true) {
    return true;
  }
  if (typeof rec.destroy === "function") {
    const ctorName =
      typeof (value as { constructor?: { name?: unknown } }).constructor?.name === "string"
        ? (value as { constructor: { name: string } }).constructor.name
        : "";
    if (
      "$$" in rec ||
      typeof rec.toJs === "function" ||
      ctorName.includes("PyProxy") ||
      rec[Symbol.toStringTag as unknown as string] === "PyProxy"
    ) {
      return true;
    }
  }
  return false;
}

function sanitizeOptionalRecord(
  rec: Record<string, unknown>,
  path: string,
): Record<string, unknown> {
  if (!isPlainObject(rec)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser um objeto JSON plano.`,
    );
  }
  return ensureFiniteJson(rec, path);
}

/**
 * Valida recursivamente que todos os números são finitos (sem NaN/Infinity),
 * sem referências circulares, sem PyProxy e sem tipos não serializáveis em JSON.
 */
export function ensureFiniteJson<T>(
  value: T,
  path = "$",
  seen: WeakSet<object> = new WeakSet<object>(),
  fromPythonProxy = false,
): T {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Valor numérico não finito proibido em ${path}: ${String(value)}`,
        {
          parameters: { path, value: String(value) },
          next_step: "Substitua NaN ou Infinity por números reais finitos antes de enviar RPC.",
        },
      );
    }
    return value;
  }
  if (typeof value === "undefined") {
    // PyProxy.toJs() representa Python None como undefined, inclusive em listas.
    if (fromPythonProxy) return null as T;
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Valor undefined não serializável em ${path}.`,
      { parameters: { path } },
    );
  }
  if (
    typeof value === "bigint" ||
    typeof value === "symbol" ||
    typeof value === "function"
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Tipo não serializável em JSON (${typeof value}) em ${path}.`,
      { parameters: { path, type: typeof value } },
    );
  }
  if (isPyProxyLike(value)) {
    throw new ControlLabBridgeError(
      "INTERNAL_ERROR",
      `Objeto PyProxy não pode ser serializado no contrato RPC em ${path}.`,
      { parameters: { path } },
    );
  }
  if (value instanceof ArrayBuffer || ArrayBuffer.isView(value)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Buffer binário bruto encontrado diretamente em JSON em ${path}; use BufferTensorRef + buffers transferíveis.`,
      { parameters: { path } },
    );
  }
  if (typeof value === "object") {
    const obj = value as object;
    if (seen.has(obj)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Referência circular detectada em ${path}.`,
        { parameters: { path } },
      );
    }
    seen.add(obj);
    try {
      if (Array.isArray(value)) {
        const outArr: unknown[] = [];
        for (let i = 0; i < value.length; i += 1) {
          outArr.push(ensureFiniteJson(value[i], `${path}[${i}]`, seen, fromPythonProxy));
        }
        return outArr as unknown as T;
      }
      if (!isPlainObject(value)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Objeto não-plano não suportado em JSON em ${path}.`,
          { parameters: { path } },
        );
      }
      const outObj: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(value)) {
        if (v === undefined && !fromPythonProxy) {
          continue;
        }
        if (k === "F_k_packed" && isPlainObject(v)) {
          outObj[k] = ensureFinitePackedSparseCoo(
            v,
            `${path}.${k}`,
            seen,
            fromPythonProxy,
          );
        } else {
          outObj[k] = ensureFiniteJson(v, `${path}.${k}`, seen, fromPythonProxy);
        }
      }
      return outObj as unknown as T;
    } finally {
      seen.delete(obj);
    }
  }
  throw new ControlLabBridgeError(
    "VALIDATION_ERROR",
    `Tipo inválido em ${path}.`,
    { parameters: { path } },
  );
}

function validatePackedTypedArray(
  fieldName: string,
  value: Int32Array | Float64Array,
  path: string,
): Int32Array | Float64Array {
  if (!(value.buffer instanceof ArrayBuffer)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Buffer de ${path} deve ser respaldado por ArrayBuffer transferível.`,
      { parameters: { path, field: fieldName } },
    );
  }
  if (isArrayBufferDetached(value.buffer)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Buffer de ${path} já foi transferido/destacado (detached) e não pode ser reutilizado.`,
      {
        parameters: { path, field: fieldName, detached: true },
        next_step: "Use preserveSenderCopy: true se precisar manter acesso ao buffer após postMessage.",
      },
    );
  }
  if (value instanceof Float64Array) {
    for (let i = 0; i < value.length; i += 1) {
      if (!Number.isFinite(value[i])) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Valor numérico não finito proibido em ${path}[${i}]: ${String(value[i])}`,
          {
            parameters: { path: `${path}[${i}]`, value: String(value[i]) },
            next_step: "Substitua NaN ou Infinity por números reais finitos antes de enviar RPC.",
          },
        );
      }
    }
  }
  return value;
}

function ensureFinitePackedSparseCoo(
  packed: Record<string, unknown>,
  path: string,
  seen: WeakSet<object>,
  fromPythonProxy: boolean,
): Record<string, unknown> {
  if (seen.has(packed)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Referência circular detectada em ${path}.`,
      { parameters: { path } },
    );
  }
  seen.add(packed);
  try {
    const outObj: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(packed)) {
      if (v === undefined && !fromPythonProxy) {
        continue;
      }
      if (PACKED_SPARSE_INT32_FIELDS.has(k) && v instanceof Int32Array) {
        outObj[k] = validatePackedTypedArray(k, v, `${path}.${k}`);
      } else if (PACKED_SPARSE_FLOAT64_FIELDS.has(k) && v instanceof Float64Array) {
        outObj[k] = validatePackedTypedArray(k, v, `${path}.${k}`);
      } else {
        outObj[k] = ensureFiniteJson(v, `${path}.${k}`, seen, fromPythonProxy);
      }
    }
    return outObj;
  } finally {
    seen.delete(packed);
  }
}

export function strictJsonStringify(value: unknown): string {
  const sanitized = ensureFiniteJson(value, "$");
  return JSON.stringify(sanitized);
}

export function strictJsonParse(raw: string): unknown {
  if (typeof raw !== "string") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "strictJsonParse exige uma string JSON.",
    );
  }
  // Rejeita tokens literais NaN / Infinity mesmo se houver extensão não-padrão
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (err: unknown) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `JSON inválido: ${err instanceof Error ? err.message : String(err)}`,
      { cause: err },
    );
  }
  return ensureFiniteJson(parsed, "$");
}

function assertNonEmptyString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Campo '${field}' deve ser uma string não vazia.`,
      { parameters: { field } },
    );
  }
  return value;
}

function assertNonNegativeInt(value: unknown, field: string): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0 ||
    !Number.isFinite(value)
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Campo '${field}' deve ser um inteiro >= 0, recebido ${String(value)}.`,
      { parameters: { field, value: String(value) } },
    );
  }
  return value;
}

function assertPositiveInt(value: unknown, field: string): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 1 ||
    !Number.isFinite(value)
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Campo '${field}' deve ser um inteiro >= 1, recebido ${String(value)}.`,
      { parameters: { field, value: String(value) } },
    );
  }
  return value;
}

function validateFiniteNumberArray(arr: unknown, path: string): number[] {
  if (!Array.isArray(arr)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser um array numérico.`,
      { parameters: { path } },
    );
  }
  const out: number[] = new Array(arr.length);
  for (let i = 0; i < arr.length; i += 1) {
    const v = arr[i];
    if (typeof v !== "number" || !Number.isFinite(v)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `${path}[${i}] deve ser um número finito, recebido ${String(v)}.`,
        { parameters: { path, index: i, value: String(v) } },
      );
    }
    out[i] = v;
  }
  return out;
}

function validateShape(rawShape: unknown, path: string): number[] {
  if (!Array.isArray(rawShape) || rawShape.length < 1) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path}.shape deve ser um array não vazio de inteiros >= 0.`,
      { parameters: { path } },
    );
  }
  const shape: number[] = [];
  for (let i = 0; i < rawShape.length; i += 1) {
    const d = rawShape[i];
    if (typeof d !== "number" || !Number.isInteger(d) || d < 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `${path}.shape[${i}] inválido: ${String(d)}.`,
        { parameters: { path, index: i } },
      );
    }
    shape.push(d);
  }
  return shape;
}

export function productOfShape(shape: readonly number[]): number {
  let prod = 1;
  for (let i = 0; i < shape.length; i += 1) {
    prod *= shape[i];
  }
  return prod;
}

export function validateTensorDescriptor(
  tensor: unknown,
  path = "$.tensor",
): TensorDescriptor {
  if (!isPlainObject(tensor)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser um objeto JSON.`,
      { parameters: { path } },
    );
  }

  const keys = Object.keys(tensor);

  if ("buffer_ref" in tensor) {
    const allowed = new Set(["shape", "dtype", "order", "buffer_ref"]);
    for (const k of keys) {
      if (!allowed.has(k)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Chave não permitida em BufferTensorRef (${path}): ${k}`,
          { parameters: { path, key: k } },
        );
      }
    }
    const shape = validateShape(tensor.shape, path);
    const dtype = tensor.dtype;
    if (
      typeof dtype !== "string" ||
      (!REAL_DTYPE_SET.has(dtype) && !COMPLEX_DTYPE_SET.has(dtype))
    ) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `dtype inválido em ${path}: ${String(dtype)}`,
        { parameters: { path, dtype: String(dtype) } },
      );
    }
    const order = tensor.order;
    if (typeof order !== "string" || !MEMORY_ORDER_SET.has(order)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `order inválido em ${path}: ${String(order)}`,
        { parameters: { path, order: String(order) } },
      );
    }
    const buffer_ref = assertNonEmptyString(tensor.buffer_ref, `${path}.buffer_ref`);
    return {
      shape,
      dtype: dtype as TensorDType,
      order: order as MemoryOrder,
      buffer_ref,
    };
  }

  if ("real" in tensor && "imag" in tensor && !("shape" in tensor)) {
    if (keys.length !== 2) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `ComplexVectorPair (${path}) deve conter apenas 'real' e 'imag'.`,
        { parameters: { path, keys } },
      );
    }
    const real = validateFiniteNumberArray(tensor.real, `${path}.real`);
    const imag = validateFiniteNumberArray(tensor.imag, `${path}.imag`);
    if (real.length !== imag.length) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `Comprimento de real (${real.length}) difere de imag (${imag.length}) em ${path}.`,
        { parameters: { path, real_len: real.length, imag_len: imag.length } },
      );
    }
    return { real, imag };
  }

  const shape = validateShape(tensor.shape, path);
  const dtype = tensor.dtype;
  const order = tensor.order;
  if (typeof order !== "string" || !MEMORY_ORDER_SET.has(order)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `order inválido em ${path}: ${String(order)}`,
      { parameters: { path, order: String(order) } },
    );
  }
  const expectedLen = productOfShape(shape);

  if (typeof dtype === "string" && COMPLEX_DTYPE_SET.has(dtype)) {
    const allowed = new Set(["shape", "dtype", "order", "real", "imag"]);
    if (keys.length !== allowed.size || keys.some((k) => !allowed.has(k))) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Chaves inválidas em ComplexTensor (${path}).`,
        { parameters: { path, keys } },
      );
    }
    const real = validateFiniteNumberArray(tensor.real, `${path}.real`);
    const imag = validateFiniteNumberArray(tensor.imag, `${path}.imag`);
    if (real.length !== expectedLen || imag.length !== expectedLen) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `Comprimento de ComplexTensor (${real.length}, ${imag.length}) incompatível com shape [${shape.join(",")}] em ${path}.`,
        { parameters: { path, shape, expectedLen } },
      );
    }
    return {
      shape,
      dtype: dtype as ComplexDType,
      order: order as MemoryOrder,
      real,
      imag,
    };
  }

  if (typeof dtype === "string" && REAL_DTYPE_SET.has(dtype)) {
    const allowed = new Set(["shape", "dtype", "order", "data"]);
    if (keys.length !== allowed.size || keys.some((k) => !allowed.has(k))) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Chaves inválidas em RealTensor (${path}).`,
        { parameters: { path, keys } },
      );
    }
    const data = validateFiniteNumberArray(tensor.data, `${path}.data`);
    if (data.length !== expectedLen) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `Comprimento de RealTensor.data (${data.length}) incompatível com shape [${shape.join(",")}] (esperado ${expectedLen}) em ${path}.`,
        { parameters: { path, shape, actualLen: data.length, expectedLen } },
      );
    }
    return {
      shape,
      dtype: dtype as RealDType,
      order: order as MemoryOrder,
      data,
    };
  }

  throw new ControlLabBridgeError(
    "VALIDATION_ERROR",
    `dtype inválido em tensor (${path}): ${String(dtype)}`,
    { parameters: { path, dtype: String(dtype) } },
  );
}

const RPC_REQUEST_KEYS = new Set([
  "api_version",
  "request_id",
  "project_id",
  "project_revision",
  "operation",
  "payload",
  "options",
  "timeout_policy",
]);

export function validateRpcRequest(raw: unknown): RpcRequest {
  if (!isPlainObject(raw)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcRequest deve ser um objeto JSON plano.",
    );
  }
  for (const key of Object.keys(raw)) {
    if (!RPC_REQUEST_KEYS.has(key)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Campo adicional proibido em RpcRequest: '${key}'`,
        { parameters: { field: key } },
      );
    }
  }
  for (const reqKey of RPC_REQUEST_KEYS) {
    if (!(reqKey in raw)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Campo obrigatório ausente em RpcRequest: '${reqKey}'`,
        { parameters: { field: reqKey } },
      );
    }
  }

  if (raw.api_version !== RPC_API_VERSION) {
    throw new ControlLabBridgeError(
      "SCHEMA_UNSUPPORTED",
      `api_version não suportada em RpcRequest: ${String(raw.api_version)} (esperado '${RPC_API_VERSION}').`,
      { parameters: { api_version: String(raw.api_version), expected: RPC_API_VERSION } },
    );
  }

  const request_id = assertNonEmptyString(raw.request_id, "request_id");
  const project_id = assertNonEmptyString(raw.project_id, "project_id");
  const project_revision = assertNonNegativeInt(raw.project_revision, "project_revision");

  const operation = assertNonEmptyString(raw.operation, "operation");
  if (!OPERATION_NAME_RE.test(operation)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Operação RPC inválida '${operation}'; esperado padrão namespace.acao (^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$).`,
      { parameters: { operation } },
    );
  }

  if (!isPlainObject(raw.payload)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcRequest.payload deve ser um objeto JSON.",
    );
  }
  const payload = ensureFiniteJson(raw.payload, "$.payload");

  if (!isPlainObject(raw.options)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcRequest.options deve ser um objeto JSON.",
    );
  }
  const options = ensureFiniteJson(raw.options, "$.options");

  if (!isPlainObject(raw.timeout_policy)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcRequest.timeout_policy deve ser um objeto JSON.",
    );
  }
  const tpRaw = ensureFiniteJson(raw.timeout_policy, "$.timeout_policy");
  if (!("hard_timeout_ms" in tpRaw)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcRequest.timeout_policy requer 'hard_timeout_ms'.",
    );
  }
  const hard_timeout_ms = assertPositiveInt(
    tpRaw.hard_timeout_ms,
    "timeout_policy.hard_timeout_ms",
  );
  if (tpRaw.soft_timeout_ms !== undefined) {
    assertPositiveInt(tpRaw.soft_timeout_ms, "timeout_policy.soft_timeout_ms");
  }
  if (
    tpRaw.cancel_on_supersede !== undefined &&
    typeof tpRaw.cancel_on_supersede !== "boolean"
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "timeout_policy.cancel_on_supersede deve ser boolean.",
    );
  }

  return {
    api_version: RPC_API_VERSION,
    request_id,
    project_id,
    project_revision,
    operation,
    payload,
    options,
    timeout_policy: {
      ...tpRaw,
      hard_timeout_ms,
    },
  };
}

export function validateTypedError(raw: unknown, path = "$.error"): TypedError {
  if (!isPlainObject(raw)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser um objeto TypedError.`,
    );
  }
  const allowed = new Set([
    "code",
    "message",
    "parameters",
    "next_step",
    "details",
  ]);
  for (const k of Object.keys(raw)) {
    if (!allowed.has(k)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Campo não permitido em TypedError (${path}): '${k}'`,
        { parameters: { field: k } },
      );
    }
  }
  if (typeof raw.code !== "string" || !ERROR_CATEGORY_SET.has(raw.code)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Categoria de erro inválida em ${path}.code: ${String(raw.code)}`,
      { parameters: { code: String(raw.code) } },
    );
  }
  const message = assertNonEmptyString(raw.message, `${path}.message`);
  const out: TypedError = {
    code: raw.code as ErrorCategory,
    message,
  };
  if (raw.parameters !== undefined) {
    out.parameters = sanitizeOptionalRecord(
      raw.parameters as Record<string, unknown>,
      `${path}.parameters`,
    );
  }
  if (raw.next_step !== undefined) {
    if (typeof raw.next_step !== "string") {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `${path}.next_step deve ser string.`,
      );
    }
    out.next_step = raw.next_step;
  }
  if (raw.details !== undefined) {
    out.details = sanitizeOptionalRecord(
      raw.details as Record<string, unknown>,
      `${path}.details`,
    );
  }
  return out;
}

export function validateProvenance(raw: unknown, path = "$.provenance"): Provenance {
  if (!isPlainObject(raw)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser um objeto Provenance.`,
    );
  }
  const clean = ensureFiniteJson(raw, path);
  const algorithm = assertNonEmptyString(clean.algorithm, `${path}.algorithm`);
  if (!isPlainObject(clean.lib_versions)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path}.lib_versions deve ser um objeto mapeando string -> string.`,
    );
  }
  const libVersions: Record<string, string> = {};
  for (const [k, v] of Object.entries(clean.lib_versions)) {
    if (typeof v !== "string") {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `${path}.lib_versions['${k}'] deve ser string.`,
      );
    }
    libVersions[k] = v;
  }
  if (clean.seed !== undefined && clean.seed !== null) {
    if (typeof clean.seed !== "number" || !Number.isInteger(clean.seed)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `${path}.seed deve ser inteiro ou null.`,
      );
    }
  }
  if (clean.tolerances !== undefined && !isPlainObject(clean.tolerances)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path}.tolerances deve ser objeto JSON.`,
    );
  }
  if (clean.model_revision !== undefined && clean.model_revision !== null) {
    assertNonNegativeInt(clean.model_revision, `${path}.model_revision`);
  }
  if (clean.timestamp !== undefined && typeof clean.timestamp !== "string") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path}.timestamp deve ser string.`,
    );
  }
  return {
    ...clean,
    algorithm,
    lib_versions: libVersions,
  };
}

const RPC_RESPONSE_KEYS = new Set([
  "api_version",
  "request_id",
  "project_id",
  "project_revision",
  "status",
  "result",
  "assumptions",
  "diagnostics",
  "provenance",
  "warnings",
  "error",
]);

export function validateRpcResponse(raw: unknown): RpcResponse {
  if (!isPlainObject(raw)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcResponse deve ser um objeto JSON plano.",
    );
  }
  for (const key of Object.keys(raw)) {
    if (!RPC_RESPONSE_KEYS.has(key)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Campo adicional proibido em RpcResponse: '${key}'`,
        { parameters: { field: key } },
      );
    }
  }
  for (const reqKey of RPC_RESPONSE_KEYS) {
    if (!(reqKey in raw)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Campo obrigatório ausente em RpcResponse: '${reqKey}'`,
        { parameters: { field: reqKey } },
      );
    }
  }

  if (raw.api_version !== RPC_API_VERSION) {
    throw new ControlLabBridgeError(
      "SCHEMA_UNSUPPORTED",
      `api_version não suportada em RpcResponse: ${String(raw.api_version)} (esperado '${RPC_API_VERSION}').`,
      { parameters: { api_version: String(raw.api_version), expected: RPC_API_VERSION } },
    );
  }

  const request_id = assertNonEmptyString(raw.request_id, "request_id");
  const project_id = assertNonEmptyString(raw.project_id, "project_id");
  const project_revision = assertNonNegativeInt(raw.project_revision, "project_revision");

  if (typeof raw.status !== "string" || !RESULT_STATUS_SET.has(raw.status)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `ResultStatus inválido em RpcResponse: ${String(raw.status)}`,
      { parameters: { status: String(raw.status) } },
    );
  }
  const status = raw.status as ResultStatus;

  let result: Record<string, unknown> | null = null;
  if (raw.result !== null) {
    if (!isPlainObject(raw.result)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "RpcResponse.result deve ser objeto JSON ou null.",
      );
    }
    result = ensureFiniteJson(raw.result, "$.result");
  }

  if (!isPlainObject(raw.assumptions)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcResponse.assumptions deve ser objeto JSON.",
    );
  }
  const assumptions = ensureFiniteJson(raw.assumptions, "$.assumptions");

  if (!isPlainObject(raw.diagnostics)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcResponse.diagnostics deve ser objeto JSON.",
    );
  }
  const diagnostics = ensureFiniteJson(raw.diagnostics, "$.diagnostics");

  const provenance = validateProvenance(raw.provenance, "$.provenance");

  if (!Array.isArray(raw.warnings)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RpcResponse.warnings deve ser um array.",
    );
  }
  const warnings: WarningEntry[] = [];
  for (let i = 0; i < raw.warnings.length; i += 1) {
    const w = raw.warnings[i];
    if (typeof w === "string") {
      if (w.length === 0) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `RpcResponse.warnings[${i}] string não pode ser vazia.`,
        );
      }
      warnings.push(w);
    } else if (isPlainObject(w)) {
      const cleanW = ensureFiniteJson(w, `$.warnings[${i}]`);
      const code = assertNonEmptyString(cleanW.code, `warnings[${i}].code`);
      const message = assertNonEmptyString(cleanW.message, `warnings[${i}].message`);
      if (cleanW.details !== undefined && !isPlainObject(cleanW.details)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `warnings[${i}].details deve ser objeto JSON.`,
        );
      }
      warnings.push({
        ...cleanW,
        code,
        message,
      } as WarningItem);
    } else {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `RpcResponse.warnings[${i}] deve ser string ou WarningItem.`,
      );
    }
  }

  const error = raw.error === null ? null : validateTypedError(raw.error, "$.error");

  if (status === "failure" && error === null) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Invariante violada: RpcResponse com status='failure' exige error !== null.",
    );
  }
  if (status === "success" && error !== null) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Invariante violada: RpcResponse com status='success' exige error === null.",
    );
  }

  return {
    api_version: RPC_API_VERSION,
    request_id,
    project_id,
    project_revision,
    status,
    result,
    assumptions,
    diagnostics,
    provenance,
    warnings,
    error,
  };
}

export function buildFailureRpcResponse(params: {
  request_id: string;
  project_id: string;
  project_revision: number;
  code: ErrorCategory;
  message: string;
  parameters?: Record<string, unknown>;
  next_step?: string;
  details?: Record<string, unknown>;
  algorithm?: string;
  lib_versions?: Record<string, string>;
  assumptions?: Record<string, unknown>;
  diagnostics?: Record<string, unknown>;
  warnings?: WarningEntry[];
  model_revision?: number | null;
}): RpcResponse {
  const err = createTypedError(params.code, params.message, {
    parameters: params.parameters,
    next_step: params.next_step,
    details: params.details,
  });
  return validateRpcResponse({
    api_version: RPC_API_VERSION,
    request_id: params.request_id || "unknown-request",
    project_id: params.project_id || "unknown-project",
    project_revision:
      typeof params.project_revision === "number" &&
      Number.isInteger(params.project_revision) &&
      params.project_revision >= 0
        ? params.project_revision
        : 0,
    status: "failure",
    result: null,
    assumptions: params.assumptions ?? {},
    diagnostics: params.diagnostics ?? {},
    provenance: {
      algorithm: params.algorithm ?? "controllab.bridge",
      lib_versions: params.lib_versions ?? {},
      model_revision: params.model_revision ?? null,
      timestamp: new Date().toISOString(),
    },
    warnings: params.warnings ?? [],
    error: err,
  });
}

// ---------------------------------------------------------------------------
// Transferência de ArrayBuffer e Detecção de Buffer Destacado
// ---------------------------------------------------------------------------

const transferredBufferRegistry = new WeakSet<ArrayBuffer>();

export function isArrayBufferDetached(buffer: ArrayBuffer): boolean {
  if (!(buffer instanceof ArrayBuffer)) {
    return true;
  }
  const maybeDetached = (buffer as ArrayBuffer & { readonly detached?: boolean }).detached;
  if (typeof maybeDetached === "boolean") {
    return maybeDetached;
  }
  return transferredBufferRegistry.has(buffer);
}

export function assertBufferUsable(
  buffer: ArrayBuffer,
  expectedMinByteLength = 1,
  label = "ArrayBuffer",
): void {
  if (!(buffer instanceof ArrayBuffer)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${label} não é uma instância válida de ArrayBuffer.`,
    );
  }
  if (isArrayBufferDetached(buffer)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${label} já foi transferido/destacado (detached, byteLength=${buffer.byteLength}) e não pode ser reutilizado.`,
      {
        parameters: { label, byteLength: buffer.byteLength, detached: true },
        next_step: "Use preserveSenderCopy: true se precisar manter acesso ao buffer após postMessage.",
      },
    );
  }
  if (expectedMinByteLength > 0 && buffer.byteLength === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${label} possui byteLength === 0 após transferência (buffer destacado).`,
      {
        parameters: { label, byteLength: 0 },
        next_step: "Use preserveSenderCopy: true para preservar uma cópia local no remetente.",
      },
    );
  }
}

export function markBufferTransferred(buffer: ArrayBuffer): void {
  transferredBufferRegistry.add(buffer);
}

export function dtypeByteSize(dtype: TensorDType): number {
  switch (dtype) {
    case "float64":
    case "int64":
      return 8;
    case "float32":
    case "int32":
      return 4;
    case "bool":
      return 1;
    case "complex128":
      return 8; // por plano (real e imag têm 8 bytes/elem cada)
    case "complex64":
      return 4; // por plano (real e imag têm 4 bytes/elem cada)
  }
}

function sliceArrayBuffer(
  buffer: ArrayBuffer,
  byteOffset = 0,
  byteLength?: number,
): ArrayBuffer {
  const start = byteOffset;
  const end = byteLength !== undefined ? byteOffset + byteLength : buffer.byteLength;
  if (start < 0 || end > buffer.byteLength || end < start) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Faixa de bytes inválida [${start}, ${end}) para ArrayBuffer de tamanho ${buffer.byteLength}.`,
    );
  }
  return buffer.slice(start, end);
}

function validateTypedArrayFinite(
  buffer: ArrayBuffer,
  dtype: TensorDType,
  expectedElements: number,
  label: string,
): void {
  const elemBytes = dtypeByteSize(dtype);
  const expectedBytes = expectedElements * elemBytes;
  if (buffer.byteLength !== expectedBytes) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Tamanho do buffer binário '${label}' (${buffer.byteLength} bytes) incompatível com shape (${expectedElements} elementos × ${elemBytes} bytes = ${expectedBytes} bytes).`,
      { parameters: { label, actualBytes: buffer.byteLength, expectedBytes } },
    );
  }
  if (dtype === "float64" || dtype === "complex128") {
    const view = new Float64Array(buffer);
    for (let i = 0; i < view.length; i += 1) {
      if (!Number.isFinite(view[i])) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Buffer binário '${label}' contém NaN/Infinity na posição ${i}.`,
          { parameters: { label, index: i, value: String(view[i]) } },
        );
      }
    }
  } else if (dtype === "float32" || dtype === "complex64") {
    const view = new Float32Array(buffer);
    for (let i = 0; i < view.length; i += 1) {
      if (!Number.isFinite(view[i])) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Buffer binário '${label}' contém NaN/Infinity na posição ${i}.`,
          { parameters: { label, index: i, value: String(view[i]) } },
        );
      }
    }
  }
}

export function extractTransferableBuffers(
  inputs: Record<string, BinaryTensorInput>,
  options?: { preserveSenderCopy?: boolean },
): ExtractedTransferables {
  const preserveSenderCopy = options?.preserveSenderCopy === true;
  const descriptors: Record<string, BufferTensorRef> = {};
  const binaryEntries: Record<string, WireBinaryBuffer> = {};
  const transferSet = new Set<ArrayBuffer>();
  const sourceBuffers: Array<{
    buffer_ref: string;
    buffer: ArrayBuffer;
    expectedByteLength: number;
  }> = [];

  for (const [buffer_ref, item] of Object.entries(inputs)) {
    assertNonEmptyString(buffer_ref, "buffer_ref");
    const shape = validateShape(item.shape, `$.buffers['${buffer_ref}']`);
    const order: MemoryOrder = item.order ?? "C";
    if (!MEMORY_ORDER_SET.has(order)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Ordem de memória inválida em buffer '${buffer_ref}': ${String(order)}`,
      );
    }
    const dtype = item.dtype;
    if (!REAL_DTYPE_SET.has(dtype) && !COMPLEX_DTYPE_SET.has(dtype)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Dtype inválido em buffer '${buffer_ref}': ${String(dtype)}`,
      );
    }

    const expectedElements = productOfShape(shape);
    const expectedMinBytes = expectedElements > 0 ? 1 : 0;
    assertBufferUsable(item.buffer, expectedMinBytes, `buffer['${buffer_ref}']`);

    const offset = item.byteOffset ?? 0;
    const len = item.byteLength ?? (item.buffer.byteLength - offset);
    const isSubSlice = offset !== 0 || len !== item.buffer.byteLength;

    let wireBuffer: ArrayBuffer;
    if (preserveSenderCopy || isSubSlice) {
      wireBuffer = sliceArrayBuffer(item.buffer, offset, len);
    } else {
      wireBuffer = item.buffer;
      sourceBuffers.push({
        buffer_ref,
        buffer: item.buffer,
        expectedByteLength: len,
      });
    }

    validateTypedArrayFinite(wireBuffer, dtype, expectedElements, buffer_ref);
    transferSet.add(wireBuffer);

    const entry: WireBinaryBuffer = {
      buffer_ref,
      shape,
      dtype,
      order,
      buffer: wireBuffer,
      byte_length: wireBuffer.byteLength,
    };

    if (COMPLEX_DTYPE_SET.has(dtype)) {
      if (!(item.imagBuffer instanceof ArrayBuffer)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Tensor complexo '${buffer_ref}' exige imagBuffer ArrayBuffer explícito.`,
        );
      }
      assertBufferUsable(
        item.imagBuffer,
        expectedMinBytes,
        `imagBuffer['${buffer_ref}']`,
      );
      const imOffset = item.imagByteOffset ?? 0;
      const imLen = item.imagByteLength ?? (item.imagBuffer.byteLength - imOffset);
      const imSubSlice = imOffset !== 0 || imLen !== item.imagBuffer.byteLength;
      const wireImag =
        preserveSenderCopy || imSubSlice
          ? sliceArrayBuffer(item.imagBuffer, imOffset, imLen)
          : item.imagBuffer;
      if (!preserveSenderCopy && !imSubSlice) {
        sourceBuffers.push({
          buffer_ref: `${buffer_ref}.imag`,
          buffer: item.imagBuffer,
          expectedByteLength: imLen,
        });
      }
      validateTypedArrayFinite(wireImag, dtype, expectedElements, `${buffer_ref}.imag`);
      transferSet.add(wireImag);
      entry.imag_buffer = wireImag;
      entry.imag_byte_length = wireImag.byteLength;
    }

    descriptors[buffer_ref] = {
      shape,
      dtype,
      order,
      buffer_ref,
    };
    binaryEntries[buffer_ref] = entry;
  }

  return {
    descriptors,
    binaryEntries,
    transferList: Array.from(transferSet),
    sourceBuffers,
    preservedSenderCopy: preserveSenderCopy,
  };
}

export function verifyPostTransferDetachment(
  extracted: ExtractedTransferables,
): void {
  if (extracted.preservedSenderCopy) {
    return;
  }
  for (const src of extracted.sourceBuffers) {
    markBufferTransferred(src.buffer);
    if (src.expectedByteLength > 0 && src.buffer.byteLength !== 0) {
      throw new ControlLabBridgeError(
        "INTERNAL_ERROR",
        `Falha de transferência: buffer '${src.buffer_ref}' ainda possui byteLength=${src.buffer.byteLength} após postMessage.`,
      );
    }
  }
}

export function validateWireBinaryBuffer(entry: WireBinaryBuffer): void {
  const expectedElements = productOfShape(entry.shape);
  assertBufferUsable(
    entry.buffer,
    expectedElements > 0 ? 1 : 0,
    `wireBuffer['${entry.buffer_ref}']`,
  );
  validateTypedArrayFinite(
    entry.buffer,
    entry.dtype,
    expectedElements,
    entry.buffer_ref,
  );
  if (COMPLEX_DTYPE_SET.has(entry.dtype)) {
    if (!(entry.imag_buffer instanceof ArrayBuffer)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Complex WireBinaryBuffer '${entry.buffer_ref}' sem imag_buffer.`,
      );
    }
    assertBufferUsable(
      entry.imag_buffer,
      expectedElements > 0 ? 1 : 0,
      `wireImagBuffer['${entry.buffer_ref}']`,
    );
    validateTypedArrayFinite(
      entry.imag_buffer,
      entry.dtype,
      expectedElements,
      `${entry.buffer_ref}.imag`,
    );
  }
}

export function rehydrateBinaryBufferToTensor(
  entry: WireBinaryBuffer,
): RealTensor | ComplexTensor {
  validateWireBinaryBuffer(entry);

  if (COMPLEX_DTYPE_SET.has(entry.dtype)) {
    const imagBuffer = entry.imag_buffer as ArrayBuffer;
    const realArr =
      entry.dtype === "complex128"
        ? Array.from(new Float64Array(entry.buffer))
        : Array.from(new Float32Array(entry.buffer));
    const imagArr =
      entry.dtype === "complex128"
        ? Array.from(new Float64Array(imagBuffer))
        : Array.from(new Float32Array(imagBuffer));
    return {
      shape: [...entry.shape],
      dtype: entry.dtype as ComplexDType,
      order: entry.order,
      real: realArr,
      imag: imagArr,
    };
  }

  let data: number[];
  switch (entry.dtype) {
    case "float64":
      data = Array.from(new Float64Array(entry.buffer));
      break;
    case "float32":
      data = Array.from(new Float32Array(entry.buffer));
      break;
    case "int32":
      data = Array.from(new Int32Array(entry.buffer));
      break;
    case "int64": {
      const view = new BigInt64Array(entry.buffer);
      data = Array.from(view, (v) => Number(v));
      break;
    }
    case "bool":
      data = Array.from(new Uint8Array(entry.buffer), (v) => (v ? 1 : 0));
      break;
    default:
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Dtype inesperado na reidratação binária: ${String(entry.dtype)}`,
      );
  }

  return {
    shape: [...entry.shape],
    dtype: entry.dtype as RealDType,
    order: entry.order,
    data,
  };
}

export function tensorToBinaryBuffer(
  buffer_ref: string,
  tensor: RealTensor | ComplexTensor,
): WireBinaryBuffer {
  const shape = validateShape(tensor.shape, buffer_ref);
  const expectedLen = productOfShape(shape);
  if ("data" in tensor) {
    let ab: ArrayBuffer;
    if (tensor.dtype === "float64") {
      const f = Float64Array.from(tensor.data);
      ab = f.buffer;
    } else if (tensor.dtype === "float32") {
      const f = Float32Array.from(tensor.data);
      ab = f.buffer;
    } else if (tensor.dtype === "int32") {
      const i = Int32Array.from(tensor.data);
      ab = i.buffer;
    } else if (tensor.dtype === "int64") {
      const bi = BigInt64Array.from(tensor.data.map((n) => BigInt(Math.trunc(n))));
      ab = bi.buffer;
    } else {
      const u = Uint8Array.from(tensor.data.map((n) => (n ? 1 : 0)));
      ab = u.buffer;
    }
    validateTypedArrayFinite(ab, tensor.dtype, expectedLen, buffer_ref);
    return {
      buffer_ref,
      shape,
      dtype: tensor.dtype,
      order: tensor.order,
      buffer: ab,
      byte_length: ab.byteLength,
    };
  }
  const realBuf =
    tensor.dtype === "complex128"
      ? Float64Array.from(tensor.real).buffer
      : Float32Array.from(tensor.real).buffer;
  const imagBuf =
    tensor.dtype === "complex128"
      ? Float64Array.from(tensor.imag).buffer
      : Float32Array.from(tensor.imag).buffer;
  return {
    buffer_ref,
    shape,
    dtype: tensor.dtype,
    order: tensor.order,
    buffer: realBuf,
    byte_length: realBuf.byteLength,
    imag_buffer: imagBuf,
    imag_byte_length: imagBuf.byteLength,
  };
}

function isPackedRealTensorDescriptor(value: unknown): value is RealTensor {
  return (
    isPlainObject(value) &&
    Array.isArray(value.shape) &&
    (value.dtype === "int32" || value.dtype === "float64") &&
    typeof value.order === "string" &&
    Array.isArray(value.data)
  );
}

export function containsExtractablePackedSparse(node: unknown): boolean {
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i += 1) {
      const item = node[i];
      if (
        typeof item === "object" &&
        item !== null &&
        containsExtractablePackedSparse(item)
      ) {
        return true;
      }
    }
    return false;
  }
  if (!isPlainObject(node)) {
    return false;
  }
  for (const [k, v] of Object.entries(node)) {
    if (k === "F_k_packed" && isPlainObject(v)) {
      for (const [fk, fv] of Object.entries(v)) {
        if (
          (PACKED_SPARSE_INT32_FIELDS.has(fk) && fv instanceof Int32Array) ||
          (PACKED_SPARSE_FLOAT64_FIELDS.has(fk) && fv instanceof Float64Array) ||
          ((PACKED_SPARSE_INT32_FIELDS.has(fk) ||
            PACKED_SPARSE_FLOAT64_FIELDS.has(fk)) &&
            isPackedRealTensorDescriptor(fv))
        ) {
          return true;
        }
      }
    } else if (typeof v === "object" && v !== null) {
      if (k === "data" || k === "real" || k === "imag") {
        if (Array.isArray(v) && (v.length === 0 || typeof v[0] === "number")) {
          continue;
        }
      }
      if (containsExtractablePackedSparse(v)) {
        return true;
      }
    }
  }
  return false;
}

export function extractTensorsToBinaryBuffers(
  record: Record<string, unknown>,
  prefix = "res",
  options?: {
    preserveSenderCopy?: boolean;
    packedSparseOnly?: boolean;
  },
): {
  replaced: Record<string, unknown>;
  buffers: Record<string, WireBinaryBuffer>;
  transferList: ArrayBuffer[];
} {
  const preserveSenderCopy = options?.preserveSenderCopy === true;
  const packedSparseOnly = options?.packedSparseOnly === true;
  const buffers: Record<string, WireBinaryBuffer> = {};
  const transferList: ArrayBuffer[] = [];
  const transferSet = new Set<ArrayBuffer>();
  let seq = 0;

  const pushUniqueTransfer = (ab: ArrayBuffer): ArrayBuffer => {
    if (transferSet.has(ab)) {
      const cloned = ab.slice(0);
      transferSet.add(cloned);
      transferList.push(cloned);
      return cloned;
    }
    transferSet.add(ab);
    transferList.push(ab);
    return ab;
  };

  const extractTypedArrayToPackedWireBuffer = (
    bufferRef: string,
    fieldName: string,
    arr: Int32Array | Float64Array,
    dtype: "int32" | "float64",
  ): BufferTensorRef => {
    validatePackedTypedArray(fieldName, arr, bufferRef);
    const rawBuf = arr.buffer as ArrayBuffer;
    const isSubSlice =
      arr.byteOffset !== 0 || arr.byteLength !== rawBuf.byteLength;
    const wireAb =
      preserveSenderCopy || isSubSlice
        ? sliceArrayBuffer(rawBuf, arr.byteOffset, arr.byteLength)
        : rawBuf;
    const uniqueAb = pushUniqueTransfer(wireAb);
    const shape = [arr.length];
    buffers[bufferRef] = {
      buffer_ref: bufferRef,
      shape,
      dtype,
      order: "C",
      buffer: uniqueAb,
      byte_length: uniqueAb.byteLength,
      packed_sparse: true,
    };
    return {
      shape,
      dtype,
      order: "C",
      buffer_ref: bufferRef,
    } satisfies BufferTensorRef;
  };

  const extractPackedSparseObject = (
    packed: Record<string, unknown>,
    keyPath: string,
  ): Record<string, unknown> => {
    const outPacked: Record<string, unknown> = {};
    for (const [fk, fv] of Object.entries(packed)) {
      if (PACKED_SPARSE_INT32_FIELDS.has(fk) && fv instanceof Int32Array) {
        seq += 1;
        const bufferRef = `${prefix}-${keyPath}_${fk}-${seq}`;
        outPacked[fk] = extractTypedArrayToPackedWireBuffer(
          bufferRef,
          fk,
          fv,
          "int32",
        );
      } else if (
        PACKED_SPARSE_FLOAT64_FIELDS.has(fk) &&
        fv instanceof Float64Array
      ) {
        seq += 1;
        const bufferRef = `${prefix}-${keyPath}_${fk}-${seq}`;
        outPacked[fk] = extractTypedArrayToPackedWireBuffer(
          bufferRef,
          fk,
          fv,
          "float64",
        );
      } else if (
        (PACKED_SPARSE_INT32_FIELDS.has(fk) ||
          PACKED_SPARSE_FLOAT64_FIELDS.has(fk)) &&
        isPackedRealTensorDescriptor(fv)
      ) {
        seq += 1;
        const bufferRef = `${prefix}-${keyPath}_${fk}-${seq}`;
        const wb = tensorToBinaryBuffer(bufferRef, fv);
        const uniqueAb = pushUniqueTransfer(wb.buffer);
        buffers[bufferRef] = {
          ...wb,
          buffer: uniqueAb,
          byte_length: uniqueAb.byteLength,
          packed_sparse: true,
        };
        outPacked[fk] = {
          shape: wb.shape,
          dtype: wb.dtype,
          order: wb.order,
          buffer_ref: bufferRef,
        } satisfies BufferTensorRef;
      } else {
        outPacked[fk] = walk(fv, `${keyPath}_${fk}`);
      }
    }
    return outPacked;
  };

  const walk = (node: unknown, keyPath: string): unknown => {
    if (Array.isArray(node)) {
      return node.map((item, idx) => walk(item, `${keyPath}_${idx}`));
    }
    if (isPlainObject(node)) {
      if (
        !packedSparseOnly &&
        Array.isArray(node.shape) &&
        typeof node.dtype === "string" &&
        typeof node.order === "string" &&
        (Array.isArray(node.data) ||
          (Array.isArray(node.real) && Array.isArray(node.imag)))
      ) {
        seq += 1;
        const bufferRef = `${prefix}-${keyPath}-${seq}`;
        const wb = tensorToBinaryBuffer(
          bufferRef,
          node as unknown as RealTensor | ComplexTensor,
        );
        const uniqueAb = pushUniqueTransfer(wb.buffer);
        let uniqueImag: ArrayBuffer | undefined;
        if (wb.imag_buffer) {
          uniqueImag = pushUniqueTransfer(wb.imag_buffer);
        }
        buffers[bufferRef] = {
          ...wb,
          buffer: uniqueAb,
          byte_length: uniqueAb.byteLength,
          ...(uniqueImag !== undefined
            ? { imag_buffer: uniqueImag, imag_byte_length: uniqueImag.byteLength }
            : {}),
        };
        return {
          shape: wb.shape,
          dtype: wb.dtype,
          order: wb.order,
          buffer_ref: bufferRef,
        } satisfies BufferTensorRef;
      }
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(node)) {
        if (k === "F_k_packed" && isPlainObject(v)) {
          out[k] = extractPackedSparseObject(v, "F_k_packed");
        } else {
          out[k] = walk(v, k);
        }
      }
      return out;
    }
    return node;
  };

  return {
    replaced: walk(record, "root") as Record<string, unknown>,
    buffers,
    transferList,
  };
}

export function rehydrateBufferRefsInRecord(
  record: Record<string, unknown>,
  wireBuffers: Record<string, WireBinaryBuffer>,
): Record<string, unknown> {
  const tensorMap: Record<string, RealTensor | ComplexTensor> = {};
  for (const [refName, wb] of Object.entries(wireBuffers)) {
    tensorMap[refName] = rehydrateBinaryBufferToTensor(wb);
  }
  const walk = (node: unknown): unknown => {
    if (Array.isArray(node)) {
      return node.map(walk);
    }
    if (isPlainObject(node)) {
      if (
        typeof node.buffer_ref === "string" &&
        node.buffer_ref in tensorMap &&
        Object.keys(node).length === 4
      ) {
        return tensorMap[node.buffer_ref];
      }
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(node)) {
        out[k] = walk(v);
      }
      return out;
    }
    return node;
  };
  return walk(record) as Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// SHA-256 puro em TypeScript (Web-compatível, sem node:crypto) + Canonical Hash
// ---------------------------------------------------------------------------

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const SHA256_INIT = new Uint32Array([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
  0x1f83d9ab, 0x5be0cd19,
]);

function rotr(x: number, n: number): number {
  return (x >>> n) | (x << (32 - n));
}

export function sha256Hex(input: string | Uint8Array): string {
  const bytes =
    typeof input === "string" ? new TextEncoder().encode(input) : input;
  const bitLen = bytes.length * 8;
  const withOneLen = bytes.length + 1;
  const rem = withOneLen % 64;
  const padZeroBytes = rem <= 56 ? 56 - rem : 64 + 56 - rem;
  const totalLen = withOneLen + padZeroBytes + 8;
  const padded = new Uint8Array(totalLen);
  padded.set(bytes, 0);
  padded[bytes.length] = 0x80;

  const view = new DataView(padded.buffer);
  const hi = Math.floor(bitLen / 0x100000000);
  const lo = bitLen >>> 0;
  view.setUint32(totalLen - 8, hi, false);
  view.setUint32(totalLen - 4, lo, false);

  const H = new Uint32Array(SHA256_INIT);
  const W = new Uint32Array(64);

  for (let offset = 0; offset < totalLen; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      W[i] = view.getUint32(offset + i * 4, false);
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
      const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
      W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
    }

    let a = H[0];
    let b = H[1];
    let c = H[2];
    let d = H[3];
    let e = H[4];
    let f = H[5];
    let g = H[6];
    let h = H[7];

    for (let i = 0; i < 64; i += 1) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + SHA256_K[i] + W[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;

      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    H[0] = (H[0] + a) >>> 0;
    H[1] = (H[1] + b) >>> 0;
    H[2] = (H[2] + c) >>> 0;
    H[3] = (H[3] + d) >>> 0;
    H[4] = (H[4] + e) >>> 0;
    H[5] = (H[5] + f) >>> 0;
    H[6] = (H[6] + g) >>> 0;
    H[7] = (H[7] + h) >>> 0;
  }

  let hex = "";
  for (let i = 0; i < 8; i += 1) {
    hex += H[i].toString(16).padStart(8, "0");
  }
  return hex;
}

function canonicalSortValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => canonicalSortValue(item));
  }
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    const keys = Object.keys(value).sort();
    for (const k of keys) {
      if (value[k] !== undefined) {
        out[k] = canonicalSortValue(value[k]);
      }
    }
    return out;
  }
  return value;
}

export function computeCanonicalSha256(value: unknown): string {
  const finite = ensureFiniteJson(value, "$");
  const sorted = canonicalSortValue(finite);
  return sha256Hex(JSON.stringify(sorted));
}

let fallbackUuidCounter = 0;

export function generateUuid(): string {
  const cryptoObj = (globalThis as { crypto?: Crypto }).crypto;
  if (cryptoObj && typeof cryptoObj.randomUUID === "function") {
    return cryptoObj.randomUUID();
  }
  fallbackUuidCounter += 1;
  const bytes = new Uint8Array(16);
  if (cryptoObj && typeof cryptoObj.getRandomValues === "function") {
    cryptoObj.getRandomValues(bytes);
  } else {
    const now = Date.now();
    for (let i = 0; i < 16; i += 1) {
      bytes[i] = ((now + fallbackUuidCounter * 37 + i * 13) & 0xff) >>> 0;
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
}
