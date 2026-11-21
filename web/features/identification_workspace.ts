/**
 * Workspace vertical da Aba 1 — Identificação & Pré-processamento de Dados
 * (WP-V1-F8-IDENTIFICATION-VERTICAL, CL-DIR-001 Seção 5.2, 7.1–7.4, 13.10,
 * R-03, R-06, R-26, R-27 e Testes T-ID-01 a T-ID-04).
 *
 * Responsabilidades estritas de UI/Apresentação (F8):
 * - Importar/validar Dataset(t, u, y) passivo (JSON ou CSV) e particionar em
 *   subconjuntos disjuntos de treino e validação (holdout) com registro tipado.
 * - Orquestrar as chamadas RPC tipadas ao motor Python F4/F1 via ControlLabEngineClient
 *   (`identification.fit_arx`, `identification.fit_subspace`,
 *    `identification.validate_model`, `core.reuse_model`), sem reimplementar
 *   algoritmos científicos, fatorações ou cálculos estatísticos no cliente TypeScript.
 * - Extrair e apresentar métricas separadas de previsão de 1 passo
 *   (`one_step_prediction`) e simulação livre (`free_simulation`) para treino
 *   e holdout (T-ID-03), critérios AIC/BIC/FPE, diagnósticos de posto/PE/condicionamento
 *   e avisos estruturados (T-ID-02), além de polos discretos estimados e estabilidade.
 * - Construir modelos de gráficos SVG e tabelas acessíveis WCAG 2.2 AA para
 *   comparação temporal (y medido, ŷ 1-passo, ŷ simulação livre, resíduos),
 *   correlações de resíduos (R_ee e R_ue com bandas de 95% e 99%) e mapa de polos
 *   no círculo unitário |z|=1.
 * - Orquestrar o fluxo explícito de reutilização (R-06 / T-ID-04):
 *   registro explícito do IdentifiedModel -> derivação via `core.reuse_model`
 *   (`native` ou `StateSpace`) -> registro explícito do modelo derivado ->
 *   consumo direto na Aba 3 (LQR / Espaço de Estados) ou Aba 2 (Frequência SISO)
 *   sem cópia manual de coeficientes e preservando `dt` e proveniência.
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping, erasableSyntaxOnly
 * e verbatimModuleSyntax.
 */

import type { ControlLabEngineClient } from "../bridge/client.ts";
import {
  ControlLabBridgeError,
  isPlainObject,
  validateTensorDescriptor,
  type ComplexVectorPair,
  type Provenance,
  type RealTensor,
  type RpcResponse,
  type TensorDescriptor,
  type TypedError,
  type WarningEntry,
} from "../bridge/protocol.ts";
import {
  AriaLiveAnnouncer,
  type AccessibilityThemeMode,
} from "../app/accessibility.ts";

function assertRealFloat64Tensor(td: TensorDescriptor, path: string): RealTensor {
  if ("buffer_ref" in td || "real" in td || td.dtype !== "float64") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${path} deve ser um tensor real float64 inline.`,
      { parameters: { path } },
    );
  }
  return td;
}
import {
  buildIdentificationResponseChartModel,
  buildPoleZeroChartModel,
  buildResidualCorrelationChartModel,
  type PoleZeroChartModel,
  type ResidualCorrelationChartModel,
  type TimeResponseChartModel,
} from "../charts/scientific_chart.ts";
import type {
  ProjectTabsController,
  TabToolExecutionRecord,
} from "./project_tabs.ts";
import {
  validateTypedCanonicalDto,
  type CanonicalObjectRef,
  type RegisteredTypedObject,
  type ReuseModelOutcome,
  type TypedObjectWorkspace,
} from "./typed_workspace.ts";

export interface DatasetSplitOptions {
  trainFraction?: number;
  trainId?: string;
  valId?: string;
  revision?: number;
  persistToIndexedDB?: boolean;
}

export interface DatasetSplitResult {
  trainDataset: RegisteredTypedObject;
  valDataset: RegisteredTypedObject;
  trainSamples: number;
  valSamples: number;
  dt: number | null;
}

export interface IdentificationModeMetricsView {
  evaluation_mode: "one_step_prediction" | "free_simulation";
  fit_percent: number | null;
  fit_per_channel: readonly (number | null)[];
  rmse: number | null;
}

export interface IdentificationPartitionMetricsView {
  partition: "train" | "validation";
  n_samples: number | null;
  n_effective_samples: number | null;
  one_step_prediction: IdentificationModeMetricsView;
  free_simulation: IdentificationModeMetricsView;
}

export interface IdentificationInformationCriteriaView {
  aic: number | null;
  bic: number | null;
  fpe: number | null;
}

export interface IdentificationExcitationDiagnosticsView {
  rank: number | readonly number[] | null;
  expected_rank: number | readonly number[] | null;
  rank_deficient: boolean;
  condition: number | null;
  pe_satisfied: boolean | null;
  singular_values: readonly number[];
  hankel_singular_values: readonly number[];
}

export interface IdentificationResidualDiagnosticsView {
  partition: "train" | "validation";
  n_effective_samples: number;
  max_lag: number;
  bound_95: number;
  bound_99: number;
  lags: readonly number[];
  autocorrelation: readonly number[];
  cross_lags: readonly number[];
  crosscorrelation_u_e: readonly number[];
  whiteness_within_99_fraction: number | null;
  uncorrelated_input_within_99_fraction: number | null;
  whiteness_consistent_at_99: boolean | null;
  input_uncorrelated_at_99: boolean | null;
}

export interface IdentificationSeriesSnapshot {
  partition: "train" | "validation";
  dt: number | null;
  t: readonly number[];
  u: readonly number[];
  y_measured: readonly number[];
  y_one_step: readonly number[];
  y_free_sim: readonly number[];
  residuals: readonly number[];
  residuals_free_sim?: readonly number[];
  units: {
    time: string;
    input: string;
    output: string;
  };
}

export interface IdentificationReportView {
  operation:
    | "identification.fit_arx"
    | "identification.fit_oe"
    | "identification.fit_subspace"
    | "identification.validate_model";
  request_id: string;
  project_id: string;
  project_revision: number;
  status: RpcResponse["status"];
  algorithm: string;
  inner_model_kind: "TransferFunction" | "StateSpace" | null;
  model_ref: CanonicalObjectRef | null;
  train_dataset_ref: CanonicalObjectRef | null;
  val_dataset_ref: CanonicalObjectRef | null;
  dt: number | null;
  spectral_radius: number | null;
  is_stable: boolean | null;
  poles: ComplexVectorPair | null;
  parameters_summary: Record<string, unknown>;
  train_metrics: IdentificationPartitionMetricsView | null;
  validation_metrics: IdentificationPartitionMetricsView | null;
  information_criteria: IdentificationInformationCriteriaView;
  excitation: IdentificationExcitationDiagnosticsView;
  train_residuals: IdentificationResidualDiagnosticsView | null;
  validation_residuals: IdentificationResidualDiagnosticsView | null;
  train_series: IdentificationSeriesSnapshot | null;
  validation_series: IdentificationSeriesSnapshot | null;
  warnings: readonly WarningEntry[];
  provenance: Provenance;
  response: RpcResponse;
  recorded_at: string;
}

export interface IdentificationWorkspaceOptions {
  client: ControlLabEngineClient;
  typedWorkspace: TypedObjectWorkspace;
  tabsController: ProjectTabsController;
  projectIdProvider: () => string;
  projectRevisionProvider: () => number;
  themeModeProvider?: () => AccessibilityThemeMode;
  announcer?: AriaLiveAnnouncer;
  onApplyStateSpaceToLqr?: () => unknown;
  onSwitchTab?: (tab: "identification" | "siso_frequency" | "statespace") => void;
  onError?: (err: unknown) => void;
}

/**
 * Gera sinal determinístico PRBS e dataset sintético SISO de 2ª ordem
 * exclusivamente como dado de entrada passivo de demonstração na UI.
 * Toda estimação e validação científica ocorrem no motor Python via RPC.
 */
export function buildBenchmarkArxDatasetDto(options?: {
  id?: string;
  revision?: number;
  nSamples?: number;
  dt?: number;
  constantInput?: boolean;
}): Record<string, unknown> {
  const id = options?.id ?? "ds-b-arx-prbs";
  const revision = options?.revision ?? 1;
  const nSamples = options?.nSamples ?? 160;
  const dt = options?.dt ?? 0.05;
  const constantInput = options?.constantInput ?? false;

  // LFSR de 7 bits determinístico para entrada PRBS {-1, +1}
  let lfsr = 0x53;
  const u: number[] = [];
  const t: number[] = [];
  for (let k = 0; k < nSamples; k += 1) {
    t.push(Number((k * dt).toFixed(6)));
    if (constantInput) {
      u.push(1.0);
    } else {
      const bit = ((lfsr >> 6) ^ (lfsr >> 5)) & 1;
      lfsr = ((lfsr << 1) | bit) & 0x7f;
      if (lfsr === 0) lfsr = 0x53;
      u.push(bit === 1 ? 1.0 : -1.0);
    }
  }

  // Planta discreta de referência: y(k) - 1.5 y(k-1) + 0.7 y(k-2) = 0.4 u(k-1) + 0.2 u(k-2)
  const y = new Array<number>(nSamples).fill(0);
  for (let k = 2; k < nSamples; k += 1) {
    y[k] = 1.5 * y[k - 1] - 0.7 * y[k - 2] + 0.4 * u[k - 1] + 0.2 * u[k - 2];
  }

  return {
    schema_version: "1.0.0",
    kind: "Dataset",
    id,
    revision,
    dt,
    t: {
      dtype: "float64",
      order: "C",
      shape: [nSamples],
      data: t,
    },
    u: {
      dtype: "float64",
      order: "C",
      shape: [nSamples, 1],
      data: u,
    },
    y: {
      dtype: "float64",
      order: "C",
      shape: [nSamples, 1],
      data: y,
    },
    input_names: ["u1"],
    output_names: ["y1"],
    units: {
      time: "s",
      inputs: ["V"],
      outputs: ["rad"],
    },
    provenance: {
      algorithm: constantInput
        ? "dataset.constant_input_t_id_02"
        : "dataset.prbs_benchmark_b_arx",
      library: "control_lab",
      seed: 42,
      timestamp_utc: "2026-11-18T00:00:00Z",
    },
  };
}

/**
 * Converte texto CSV (colunas `t,u,y` ou `t,u1,...,um,y1,...,yp`) em DTO canônico `Dataset`.
 */
export function parseCsvToDatasetDto(
  csvText: string,
  options?: {
    id?: string;
    revision?: number;
    nInputs?: number;
    nOutputs?: number;
    timeUnit?: string;
  },
): Record<string, unknown> {
  if (typeof csvText !== "string" || csvText.trim().length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Conteúdo CSV vazio; informe linhas com colunas numéricas (t, u, y).",
    );
  }
  const lines = csvText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("#"));

  if (lines.length < 2) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "CSV de Dataset requer ao menos 2 amostras válidas.",
    );
  }

  const splitLine = (line: string): string[] =>
    line.split(/[,;\t]/).map((cell) => cell.trim().replace(/^"|"$/g, ""));

  const firstTokens = splitLine(lines[0]);
  const hasHeader = firstTokens.some((tok) => Number.isNaN(Number(tok)));
  const dataLines = hasHeader ? lines.slice(1) : lines;
  if (dataLines.length < 2) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "CSV de Dataset requer ao menos 2 linhas numéricas após o cabeçalho.",
    );
  }

  const rows: number[][] = [];
  let nCols = 0;
  for (let idx = 0; idx < dataLines.length; idx += 1) {
    const tokens = splitLine(dataLines[idx]);
    if (idx === 0) {
      nCols = tokens.length;
      if (nCols < 3) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `CSV de Dataset requer pelo menos 3 colunas (t, u, y), recebido ${nCols}.`,
        );
      }
    } else if (tokens.length !== nCols) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `Linha ${idx + 1} do CSV possui ${tokens.length} colunas, esperado ${nCols}.`,
      );
    }
    const nums = tokens.map((tok, colIdx) => {
      const val = Number(tok);
      if (!Number.isFinite(val)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `Valor não numérico na linha ${idx + 1}, coluna ${colIdx + 1}: '${tok}'.`,
        );
      }
      return val;
    });
    rows.push(nums);
  }

  const m = options?.nInputs ?? 1;
  const p = options?.nOutputs ?? nCols - 1 - m;
  if (m < 1 || p < 1 || 1 + m + p !== nCols) {
    throw new ControlLabBridgeError(
      "DIMENSION_MISMATCH",
      `Colunas do CSV (${nCols}) incompatíveis com 1 coluna de tempo + m=${m} entradas + p=${p} saídas.`,
    );
  }

  const nSamples = rows.length;
  const tData: number[] = [];
  const uData: number[] = [];
  const yData: number[] = [];

  for (let k = 0; k < nSamples; k += 1) {
    const r = rows[k];
    if (k > 0 && r[0] <= tData[k - 1]) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Vetor de tempo t no CSV deve ser estritamente crescente (t[${k}]=${r[0]} <= t[${k - 1}]=${tData[k - 1]}).`,
      );
    }
    tData.push(r[0]);
    for (let j = 0; j < m; j += 1) {
      uData.push(r[1 + j]);
    }
    for (let i = 0; i < p; i += 1) {
      yData.push(r[1 + m + i]);
    }
  }

  // Estima dt se amostragem for uniforme (tolerância 1e-6 relativa)
  const diffs: number[] = [];
  for (let k = 1; k < nSamples; k += 1) {
    diffs.push(tData[k] - tData[k - 1]);
  }
  const meanDt = diffs.reduce((acc, v) => acc + v, 0) / diffs.length;
  const maxDev = Math.max(...diffs.map((d) => Math.abs(d - meanDt)));
  const isUniform = meanDt > 0 && maxDev <= 1e-4 * Math.max(1, meanDt);

  const headerNames = hasHeader ? firstTokens : [];
  const inputNames = Array.from({ length: m }, (_, j) =>
    headerNames[1 + j] && headerNames[1 + j].length > 0 ? headerNames[1 + j] : `u${j + 1}`,
  );
  const outputNames = Array.from({ length: p }, (_, i) =>
    headerNames[1 + m + i] && headerNames[1 + m + i].length > 0
      ? headerNames[1 + m + i]
      : `y${i + 1}`,
  );

  const dto: Record<string, unknown> = {
    schema_version: "1.0.0",
    kind: "Dataset",
    id: options?.id?.trim() || "ds-csv-import",
    revision: options?.revision ?? 1,
    dt: isUniform ? Number(meanDt.toFixed(9)) : null,
    t: {
      dtype: "float64",
      order: "C",
      shape: [nSamples],
      data: tData,
    },
    u: {
      dtype: "float64",
      order: "C",
      shape: [nSamples, m],
      data: uData,
    },
    y: {
      dtype: "float64",
      order: "C",
      shape: [nSamples, p],
      data: yData,
    },
    input_names: inputNames,
    output_names: outputNames,
    units: {
      time: options?.timeUnit ?? "s",
      inputs: Array.from({ length: m }, () => "u"),
      outputs: Array.from({ length: p }, () => "y"),
    },
    provenance: {
      algorithm: "dataset.csv_import",
      library: "control_lab",
      seed: null,
      timestamp_utc: new Date().toISOString(),
    },
  };

  return validateTypedCanonicalDto(dto).dto;
}

/**
 * Particiona um DTO canônico `Dataset` em dois `Dataset`s disjuntos:
 * `train` ($0 \dots N_{\text{train}}-1$) e `validation` ($N_{\text{train}} \dots N-1$),
 * preservando `dt`, nomes de canais, unidades e proveniência de particionamento.
 */
export function splitDatasetDtoTrainHoldout(
  rawDatasetDto: unknown,
  options?: {
    trainFraction?: number;
    trainId?: string;
    valId?: string;
    revision?: number;
  },
): {
  trainDto: Record<string, unknown>;
  valDto: Record<string, unknown>;
  trainSamples: number;
  valSamples: number;
  dt: number | null;
} {
  const validated = validateTypedCanonicalDto(rawDatasetDto);
  if (validated.kind !== "Dataset") {
    throw new ControlLabBridgeError(
      "UNSUPPORTED_MODEL",
      `Particionamento treino/holdout requer objeto 'Dataset', recebido '${validated.kind}'.`,
    );
  }
  const dto = validated.dto;
  const trainFraction = options?.trainFraction ?? 0.7;
  if (
    typeof trainFraction !== "number" ||
    !Number.isFinite(trainFraction) ||
    trainFraction <= 0.1 ||
    trainFraction >= 0.9
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Fração de treino (trainFraction) deve estar no intervalo aberto (0.1, 0.9).",
      { parameters: { train_fraction: trainFraction } },
    );
  }

  const tTensor = assertRealFloat64Tensor(
    validateTensorDescriptor(dto.t, "Dataset.t"),
    "Dataset.t",
  );
  const uTensor = assertRealFloat64Tensor(
    validateTensorDescriptor(dto.u, "Dataset.u"),
    "Dataset.u",
  );
  const yTensor = assertRealFloat64Tensor(
    validateTensorDescriptor(dto.y, "Dataset.y"),
    "Dataset.y",
  );

  const nTotal = tTensor.shape[0];
  if (nTotal < 8) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Dataset '${validated.id}' possui apenas ${nTotal} amostras; são necessárias ao menos 8 amostras para dividir em treino e holdout.`,
      { parameters: { n_samples: nTotal } },
    );
  }

  const m = uTensor.shape.length === 2 ? uTensor.shape[1] : 1;
  const p = yTensor.shape.length === 2 ? yTensor.shape[1] : 1;
  const nTrain = Math.max(4, Math.min(nTotal - 4, Math.round(nTotal * trainFraction)));
  const nVal = nTotal - nTrain;

  const sliceMatrixFlat = (
    data: readonly number[],
    nCols: number,
    startRow: number,
    endRow: number,
  ): number[] => data.slice(startRow * nCols, endRow * nCols);

  const baseId = validated.id;
  const rev = options?.revision ?? validated.revision;
  const trainId = options?.trainId?.trim() || `${baseId}-train`;
  const valId = options?.valId?.trim() || `${baseId}-val`;
  if (trainId === valId) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "IDs de treino e validação (holdout) devem ser distintos para evitar contaminação.",
    );
  }

  const dtVal = typeof dto.dt === "number" ? dto.dt : null;
  const baseProv = isPlainObject(dto.provenance) ? dto.provenance : {};

  const trainDto: Record<string, unknown> = {
    ...structuredClone(dto),
    id: trainId,
    revision: rev,
    t: {
      dtype: "float64",
      order: "C",
      shape: [nTrain],
      data: tTensor.data.slice(0, nTrain),
    },
    u: {
      dtype: "float64",
      order: "C",
      shape: [nTrain, m],
      data: sliceMatrixFlat(uTensor.data, m, 0, nTrain),
    },
    y: {
      dtype: "float64",
      order: "C",
      shape: [nTrain, p],
      data: sliceMatrixFlat(yTensor.data, p, 0, nTrain),
    },
    provenance: {
      ...structuredClone(baseProv),
      algorithm: String(baseProv.algorithm ?? "dataset.partition"),
      partition: {
        role: "train",
        source_dataset_id: baseId,
        source_dataset_revision: validated.revision,
        start_index: 0,
        end_index: nTrain,
        train_fraction: trainFraction,
      },
    },
  };

  const valDto: Record<string, unknown> = {
    ...structuredClone(dto),
    id: valId,
    revision: rev,
    t: {
      dtype: "float64",
      order: "C",
      shape: [nVal],
      data: tTensor.data.slice(nTrain, nTotal),
    },
    u: {
      dtype: "float64",
      order: "C",
      shape: [nVal, m],
      data: sliceMatrixFlat(uTensor.data, m, nTrain, nTotal),
    },
    y: {
      dtype: "float64",
      order: "C",
      shape: [nVal, p],
      data: sliceMatrixFlat(yTensor.data, p, nTrain, nTotal),
    },
    provenance: {
      ...structuredClone(baseProv),
      algorithm: String(baseProv.algorithm ?? "dataset.partition"),
      partition: {
        role: "validation",
        source_dataset_id: baseId,
        source_dataset_revision: validated.revision,
        start_index: nTrain,
        end_index: nTotal,
        train_fraction: trainFraction,
      },
    },
  };

  return {
    trainDto: validateTypedCanonicalDto(trainDto).dto,
    valDto: validateTypedCanonicalDto(valDto).dto,
    trainSamples: nTrain,
    valSamples: nVal,
    dt: dtVal,
  };
}

function parseFiniteNumOrNull(val: unknown): number | null {
  return typeof val === "number" && Number.isFinite(val) ? val : null;
}

function extractFirstChannelFromTensor(rawTensor: unknown): number[] {
  if (!isPlainObject(rawTensor) || !Array.isArray(rawTensor.data)) {
    return [];
  }
  try {
    const tensor = assertRealFloat64Tensor(
      validateTensorDescriptor(rawTensor, "tensor"),
      "tensor",
    );
    if (tensor.shape.length === 1) {
      return [...tensor.data];
    }
    if (tensor.shape.length === 2) {
      const nRows = tensor.shape[0];
      const nCols = Math.max(1, tensor.shape[1]);
      const out: number[] = [];
      for (let r = 0; r < nRows; r += 1) {
        out.push(tensor.data[r * nCols]);
      }
      return out;
    }
  } catch {
    // Fallback
  }
  return [];
}

function parseModeMetrics(
  raw: unknown,
  mode: "one_step_prediction" | "free_simulation",
): IdentificationModeMetricsView {
  if (!isPlainObject(raw)) {
    return {
      evaluation_mode: mode,
      fit_percent: null,
      fit_per_channel: [],
      rmse: null,
    };
  }
  const fitPerChannel = Array.isArray(raw.fit_per_channel)
    ? raw.fit_per_channel.map((v) => parseFiniteNumOrNull(v))
    : [];
  return {
    evaluation_mode: mode,
    fit_percent: parseFiniteNumOrNull(raw.fit_percent),
    fit_per_channel: fitPerChannel,
    rmse: parseFiniteNumOrNull(raw.rmse),
  };
}

function parsePartitionMetrics(
  raw: unknown,
  partition: "train" | "validation",
): IdentificationPartitionMetricsView | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  return {
    partition,
    n_samples: parseFiniteNumOrNull(raw.n_samples),
    n_effective_samples: parseFiniteNumOrNull(raw.n_effective_samples),
    one_step_prediction: parseModeMetrics(
      raw.one_step_prediction,
      "one_step_prediction",
    ),
    free_simulation: parseModeMetrics(raw.free_simulation, "free_simulation"),
  };
}

function parseResidualDiagnostics(
  raw: unknown,
  partition: "train" | "validation",
): IdentificationResidualDiagnosticsView | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  const nEff =
    typeof raw.n_effective_samples === "number" &&
    Number.isFinite(raw.n_effective_samples)
      ? raw.n_effective_samples
      : 0;
  const maxLag =
    typeof raw.max_lag === "number" && Number.isFinite(raw.max_lag)
      ? raw.max_lag
      : 0;
  const bounds = isPlainObject(raw.confidence_bounds) ? raw.confidence_bounds : {};
  const b95 =
    typeof bounds.bound_95 === "number" && Number.isFinite(bounds.bound_95)
      ? bounds.bound_95
      : nEff > 0
        ? 1.959963984540054 / Math.sqrt(nEff)
        : 0.2;
  const b99 =
    typeof bounds.bound_99 === "number" && Number.isFinite(bounds.bound_99)
      ? bounds.bound_99
      : nEff > 0
        ? 2.5758293035489004 / Math.sqrt(nEff)
        : 0.25;

  const lags = Array.isArray(raw.lags)
    ? raw.lags.filter((v): v is number => typeof v === "number" && Number.isFinite(v))
    : [];
  const crossLags = Array.isArray(raw.cross_lags)
    ? raw.cross_lags.filter(
        (v): v is number => typeof v === "number" && Number.isFinite(v),
      )
    : [];

  let autocorr: number[] = [];
  if (Array.isArray(raw.autocorrelation)) {
    if (raw.autocorrelation.every((v) => typeof v === "number")) {
      autocorr = raw.autocorrelation as number[];
    } else if (Array.isArray(raw.autocorrelation[0])) {
      autocorr = (raw.autocorrelation[0] as unknown[]).filter(
        (v): v is number => typeof v === "number" && Number.isFinite(v),
      );
    }
  }

  let crosscorr: number[] = [];
  if (Array.isArray(raw.crosscorrelation_u_e)) {
    if (raw.crosscorrelation_u_e.every((v) => typeof v === "number")) {
      crosscorr = raw.crosscorrelation_u_e as number[];
    } else if (
      Array.isArray(raw.crosscorrelation_u_e[0]) &&
      Array.isArray((raw.crosscorrelation_u_e[0] as unknown[])[0])
    ) {
      crosscorr = ((raw.crosscorrelation_u_e[0] as unknown[])[0] as unknown[]).filter(
        (v): v is number => typeof v === "number" && Number.isFinite(v),
      );
    }
  }

  return {
    partition,
    n_effective_samples: nEff,
    max_lag: maxLag,
    bound_95: b95,
    bound_99: b99,
    lags,
    autocorrelation: autocorr,
    cross_lags: crossLags,
    crosscorrelation_u_e: crosscorr,
    whiteness_within_99_fraction: parseFiniteNumOrNull(
      raw.whiteness_within_99_fraction,
    ),
    uncorrelated_input_within_99_fraction: parseFiniteNumOrNull(
      raw.uncorrelated_input_within_99_fraction,
    ),
    whiteness_consistent_at_99:
      typeof raw.whiteness_consistent_at_99 === "boolean"
        ? raw.whiteness_consistent_at_99
        : null,
    input_uncorrelated_at_99:
      typeof raw.input_uncorrelated_at_99 === "boolean"
        ? raw.input_uncorrelated_at_99
        : null,
  };
}

function parseComplexPairOrNull(raw: unknown): ComplexVectorPair | null {
  if (
    !isPlainObject(raw) ||
    !Array.isArray(raw.real) ||
    !Array.isArray(raw.imag) ||
    raw.real.length !== raw.imag.length
  ) {
    return null;
  }
  const real: number[] = [];
  const imag: number[] = [];
  for (let i = 0; i < raw.real.length; i += 1) {
    const r = raw.real[i];
    const im = raw.imag[i];
    if (typeof r !== "number" || !Number.isFinite(r)) return null;
    if (typeof im !== "number" || !Number.isFinite(im)) return null;
    real.push(r);
    imag.push(im);
  }
  return { real, imag };
}

function extractDatasetSeries(
  datasetObj: RegisteredTypedObject | null,
): {
  dt: number | null;
  t: number[];
  u: number[];
  y: number[];
  units: { time: string; input: string; output: string };
} | null {
  if (!datasetObj || datasetObj.kind !== "Dataset") {
    return null;
  }
  const dto = datasetObj.value;
  const t = extractFirstChannelFromTensor(dto.t);
  const u = extractFirstChannelFromTensor(dto.u);
  const y = extractFirstChannelFromTensor(dto.y);
  if (t.length === 0 || y.length === 0) {
    return null;
  }
  const unitsRaw = isPlainObject(dto.units) ? dto.units : {};
  const timeUnit = typeof unitsRaw.time === "string" ? unitsRaw.time : "s";
  const inUnit =
    Array.isArray(unitsRaw.inputs) && typeof unitsRaw.inputs[0] === "string"
      ? unitsRaw.inputs[0]
      : "u";
  const outUnit =
    Array.isArray(unitsRaw.outputs) && typeof unitsRaw.outputs[0] === "string"
      ? unitsRaw.outputs[0]
      : "y";
  return {
    dt: typeof dto.dt === "number" ? dto.dt : null,
    t,
    u,
    y,
    units: { time: timeUnit, input: inUnit, output: outUnit },
  };
}

function alignTailToLength(
  values: readonly number[],
  targetLen: number,
  fallbackFirst = 0,
): number[] {
  if (values.length === 0) return [];
  if (values.length === targetLen) return [...values];
  if (values.length > targetLen) {
    return values.slice(values.length - targetLen);
  }
  const padLen = targetLen - values.length;
  const pad = new Array<number>(padLen).fill(fallbackFirst);
  return [...pad, ...values];
}

export class IdentificationWorkspace {
  private readonly client: ControlLabEngineClient;
  private readonly typedWorkspace: TypedObjectWorkspace;
  private readonly tabsController: ProjectTabsController;
  private readonly projectIdProvider: () => string;
  private readonly projectRevisionProvider: () => number;
  private readonly themeModeProvider: () => AccessibilityThemeMode;
  private readonly announcer: AriaLiveAnnouncer | null;
  private readonly onApplyStateSpaceToLqr?: () => unknown;
  private readonly onSwitchTab?: (
    tab: "identification" | "siso_frequency" | "statespace",
  ) => void;
  private readonly onError?: (err: unknown) => void;

  private lastFitReport: IdentificationReportView | null = null;
  private lastValidationReport: IdentificationReportView | null = null;
  private activePartitionView: "train" | "validation" = "validation";
  private lastError: TypedError | null = null;
  private readonly listeners = new Set<() => void>();

  constructor(options: IdentificationWorkspaceOptions) {
    this.client = options.client;
    this.typedWorkspace = options.typedWorkspace;
    this.tabsController = options.tabsController;
    this.projectIdProvider = options.projectIdProvider;
    this.projectRevisionProvider = options.projectRevisionProvider;
    this.themeModeProvider = options.themeModeProvider ?? (() => "standard_aa");
    this.announcer = options.announcer ?? null;
    this.onApplyStateSpaceToLqr = options.onApplyStateSpaceToLqr;
    this.onSwitchTab = options.onSwitchTab;
    this.onError = options.onError;
  }

  public getLastFitReport(): IdentificationReportView | null {
    return this.lastFitReport ? structuredClone(this.lastFitReport) : null;
  }

  public getLastValidationReport(): IdentificationReportView | null {
    return this.lastValidationReport
      ? structuredClone(this.lastValidationReport)
      : null;
  }

  public getActiveReport(): IdentificationReportView | null {
    const rep = this.lastValidationReport ?? this.lastFitReport;
    return rep ? structuredClone(rep) : null;
  }

  public getActivePartitionView(): "train" | "validation" {
    return this.activePartitionView;
  }

  public setActivePartitionView(partition: "train" | "validation"): void {
    this.activePartitionView = partition;
    this.notify();
  }

  public getLastError(): TypedError | null {
    return this.lastError ? structuredClone(this.lastError) : null;
  }

  /**
   * Importa um Dataset em CSV, registra no TypedObjectWorkspace e opcionalmente
   * particiona imediatamente em treino e holdout disjuntos.
   */
  public async importCsvDataset(
    csvText: string,
    options?: {
      id?: string;
      revision?: number;
      nInputs?: number;
      nOutputs?: number;
      splitTrainHoldout?: boolean;
      trainFraction?: number;
      persistToIndexedDB?: boolean;
    },
  ): Promise<{
    dataset: RegisteredTypedObject;
    split: DatasetSplitResult | null;
  }> {
    this.lastError = null;
    const dto = parseCsvToDatasetDto(csvText, {
      id: options?.id,
      revision: options?.revision,
      nInputs: options?.nInputs,
      nOutputs: options?.nOutputs,
    });
    const registered = await this.typedWorkspace.registerTypedObject(dto, {
      persistToIndexedDB: options?.persistToIndexedDB ?? true,
      selectRole: "dataset",
    });

    let split: DatasetSplitResult | null = null;
    if (options?.splitTrainHoldout) {
      split = await this.splitSelectedDatasetTrainHoldout({
        sourceRef: { id: registered.id, revision: registered.revision },
        trainFraction: options.trainFraction,
        persistToIndexedDB: options.persistToIndexedDB,
      });
    }
    this.notify();
    return { dataset: registered, split };
  }

  /**
   * Carrega o dataset PRBS de benchmark (T-ID-01 / T-ID-03 / T-ID-04) ou o
   * dataset com entrada constante sem persistência de excitação (T-ID-02),
   * registrando-o e particionando em treino e holdout disjuntos.
   */
  public async loadBenchmarkDataset(options?: {
    preset?: "prbs" | "constant_input";
    nSamples?: number;
    dt?: number;
    trainFraction?: number;
    splitTrainHoldout?: boolean;
    persistToIndexedDB?: boolean;
  }): Promise<{
    dataset: RegisteredTypedObject;
    split: DatasetSplitResult | null;
  }> {
    this.lastError = null;
    const isConst = options?.preset === "constant_input";
    const dto = buildBenchmarkArxDatasetDto({
      id: isConst ? "ds-const-pe-t-id-02" : "ds-b-arx-prbs",
      revision: 1,
      nSamples: options?.nSamples ?? 160,
      dt: options?.dt ?? 0.05,
      constantInput: isConst,
    });
    const dataset = await this.typedWorkspace.registerTypedObject(dto, {
      persistToIndexedDB: options?.persistToIndexedDB ?? true,
      selectRole: "dataset",
    });

    let split: DatasetSplitResult | null = null;
    if (options?.splitTrainHoldout !== false) {
      split = await this.splitSelectedDatasetTrainHoldout({
        sourceRef: { id: dataset.id, revision: dataset.revision },
        trainFraction: options?.trainFraction ?? 0.7,
        persistToIndexedDB: options?.persistToIndexedDB ?? true,
      });
    }
    this.notify();
    return { dataset, split };
  }

  /**
   * Particiona um Dataset registrado (ou o Dataset selecionado em `dataset`)
   * em subconjuntos disjuntos `train` e `val`, registrando ambos no workspace
   * e selecionando-os nos papéis `dataset` e `valDataset`.
   */
  public async splitSelectedDatasetTrainHoldout(
    options?: DatasetSplitOptions & { sourceRef?: CanonicalObjectRef },
  ): Promise<DatasetSplitResult> {
    this.lastError = null;
    const sourceObj = options?.sourceRef
      ? this.typedWorkspace.getSelectableObject(options.sourceRef)
      : (this.typedWorkspace.getEffectiveSelection("dataset")?.object ?? null);

    if (!sourceObj || sourceObj.kind !== "Dataset") {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Selecione ou registre um objeto Dataset antes de particionar em treino e holdout.",
      );
    }

    const split = splitDatasetDtoTrainHoldout(sourceObj.value, {
      trainFraction: options?.trainFraction ?? 0.7,
      trainId: options?.trainId,
      valId: options?.valId,
      revision: options?.revision ?? sourceObj.revision,
    });

    const trainDataset = await this.typedWorkspace.registerTypedObject(
      split.trainDto,
      {
        persistToIndexedDB: options?.persistToIndexedDB ?? true,
        selectRole: "dataset",
      },
    );
    const valDataset = await this.typedWorkspace.registerTypedObject(
      split.valDto,
      {
        persistToIndexedDB: options?.persistToIndexedDB ?? true,
        selectRole: "valDataset",
      },
    );

    this.announcer?.announce(
      `Dataset '${sourceObj.id}' particionado em treino (${trainDataset.id}, N=${split.trainSamples}) e holdout (${valDataset.id}, N=${split.valSamples}).`,
      "polite",
      "status",
    );
    this.notify();
    return {
      trainDataset,
      valDataset,
      trainSamples: split.trainSamples,
      valSamples: split.valSamples,
      dt: split.dt,
    };
  }

  /**
   * Executa estimação ARX via `identification.fit_arx` no motor Python/Worker.
   */
  public async fitArx(params?: {
    na?: number;
    nb?: number;
    nk?: number;
    detrend?: "none" | "mean" | "linear";
  }): Promise<IdentificationReportView> {
    if (params) {
      const updates: Record<string, unknown> = {};
      if (params.na !== undefined) updates.na = params.na;
      if (params.nb !== undefined) updates.nb = params.nb;
      if (params.nk !== undefined) updates.nk = params.nk;
      if (params.detrend !== undefined) updates.detrend = params.detrend;
      if (Object.keys(updates).length > 0) {
        this.tabsController.setToolParameters("identification.fit_arx", updates);
      }
    }
    return this.executeIdentificationTool("identification.fit_arx");
  }

  /**
   * Executa estimação por subespaços (MOESP / N4SID) via `identification.fit_subspace`.
   */
  public async fitSubspace(params?: {
    method?: "moesp" | "n4sid";
    order?: number;
    horizon?: number;
    estimate_feedthrough?: boolean;
  }): Promise<IdentificationReportView> {
    if (params) {
      const updates: Record<string, unknown> = {};
      if (params.method !== undefined) updates.method = params.method;
      if (params.order !== undefined) updates.order = params.order;
      if (params.horizon !== undefined) updates.horizon = params.horizon;
      if (params.estimate_feedthrough !== undefined) {
        updates.estimate_feedthrough = params.estimate_feedthrough;
      }
      if (Object.keys(updates).length > 0) {
        this.tabsController.setToolParameters(
          "identification.fit_subspace",
          updates,
        );
      }
    }
    return this.executeIdentificationTool("identification.fit_subspace");
  }

  /**
   * Executa validação cruzada em holdout via `identification.validate_model`.
   * Se houver um `IdentifiedModel` pendente ainda não registrado e nenhum `validationModel`
   * selecionado, registra explicitamente o `IdentifiedModel` quando `autoRegisterPendingIfNeeded=true`.
   */
  public async validateModel(options?: {
    autoRegisterPendingIfNeeded?: boolean;
  }): Promise<IdentificationReportView> {
    const pending = this.typedWorkspace.getPendingIdentifiedModel();
    if (
      options?.autoRegisterPendingIfNeeded &&
      pending &&
      !pending.registered &&
      this.typedWorkspace.getEffectiveSelection("validationModel") === null
    ) {
      await this.typedWorkspace.registerPendingIdentifiedModel();
    }
    return this.executeIdentificationTool("identification.validate_model");
  }

  /**
   * Ingesta qualquer `ToolExecutionRecord` de `identification.*` (disparado pelo
   * botão declarativo da ferramenta ou pelos métodos diretos de `IdentificationWorkspace`)
   * e constrói o `IdentificationReportView` estruturado.
   */
  public ingestExecutionRecord(
    record: TabToolExecutionRecord,
  ): IdentificationReportView | null {
    if (
      record.operation !== "identification.fit_arx" &&
      record.operation !== "identification.fit_oe" &&
      record.operation !== "identification.fit_subspace" &&
      record.operation !== "identification.validate_model"
    ) {
      return null;
    }
    const resp = record.response;
    if (resp.status === "failure" || !resp.result) {
      if (resp.error) {
        this.lastError = structuredClone(resp.error);
      }
      this.notify();
      return null;
    }

    const report = this.buildReportFromResponse(record.operation, resp);
    if (record.operation === "identification.validate_model") {
      this.lastValidationReport = report;
      this.activePartitionView = "validation";
    } else {
      this.lastFitReport = report;
      this.lastValidationReport = null;
      this.activePartitionView =
        report.validation_metrics !== null ? "validation" : "train";
    }
    this.lastError = null;
    this.notify();
    return structuredClone(report);
  }

  private async executeIdentificationTool(
    toolId:
      | "identification.fit_arx"
      | "identification.fit_subspace"
      | "identification.validate_model",
  ): Promise<IdentificationReportView> {
    this.lastError = null;
    const projectId = this.projectIdProvider();
    const projectRevision = Math.max(
      this.projectRevisionProvider(),
      this.client.getCommittedRevision(projectId),
    );
    try {
      const record = await this.tabsController.executeTool(toolId, {
        project_id: projectId,
        project_revision: projectRevision,
        commitOnSuccess: false,
      });
      if (record.response.status === "failure" || !record.response.result) {
        const err = record.response.error ?? {
          code: "VALIDATION_ERROR" as const,
          message: `Operação '${toolId}' falhou sem detalhes adicionais.`,
        };
        this.lastError = err;
        const bridgeErr = new ControlLabBridgeError(err.code, err.message, {
          parameters: err.parameters,
          next_step: err.next_step,
          details: err.details,
        });
        this.onError?.(bridgeErr);
        this.notify();
        throw bridgeErr;
      }
      const report = this.ingestExecutionRecord(record)!;
      return report;
    } catch (err: unknown) {
      if (err instanceof ControlLabBridgeError) {
        this.lastError = err.typedError;
      }
      this.onError?.(err);
      this.notify();
      throw err;
    }
  }

  private buildReportFromResponse(
    operation:
      | "identification.fit_arx"
      | "identification.fit_oe"
      | "identification.fit_subspace"
      | "identification.validate_model",
    resp: RpcResponse,
  ): IdentificationReportView {
    const res = resp.result ?? {};
    const diag = resp.diagnostics ?? {};

    const idModelDto = isPlainObject(res.identified_model)
      ? res.identified_model
      : isPlainObject(res.updated_identified_model)
        ? res.updated_identified_model
        : null;

    const modelRef: CanonicalObjectRef | null =
      idModelDto &&
      typeof idModelDto.id === "string" &&
      typeof idModelDto.revision === "number"
        ? { id: idModelDto.id, revision: idModelDto.revision }
        : this.typedWorkspace.getEffectiveSelection("validationModel")?.ref ??
          null;

    const innerModel =
      idModelDto && isPlainObject(idModelDto.model) ? idModelDto.model : null;
    const innerModelKind: "TransferFunction" | "StateSpace" | null =
      innerModel?.kind === "TransferFunction" || innerModel?.kind === "StateSpace"
        ? innerModel.kind
        : isPlainObject(res.state_space)
          ? "StateSpace"
          : isPlainObject(res.transfer_function)
            ? "TransferFunction"
            : null;

    const algorithm =
      typeof idModelDto?.algorithm === "string"
        ? idModelDto.algorithm
        : resp.provenance.algorithm;

    const trainSel = this.typedWorkspace.getEffectiveSelection("dataset");
    const valSel = this.typedWorkspace.getEffectiveSelection("valDataset");

    const dtFromModel =
      typeof innerModel?.dt === "number"
        ? innerModel.dt
        : typeof trainSel?.object.value.dt === "number"
          ? (trainSel.object.value.dt as number)
          : typeof valSel?.object.value.dt === "number"
            ? (valSel.object.value.dt as number)
            : null;

    const metricsRoot = isPlainObject(res.metrics) ? res.metrics : {};
    const trainMetrics =
      parsePartitionMetrics(
        operation === "identification.validate_model"
          ? res.train_metrics
          : metricsRoot.train,
        "train",
      ) ??
      (idModelDto &&
      isPlainObject(idModelDto.metrics) &&
      isPlainObject(idModelDto.metrics.train)
        ? parsePartitionMetrics(idModelDto.metrics.train, "train")
        : null);

    const valMetrics =
      parsePartitionMetrics(
        operation === "identification.validate_model"
          ? res.validation_metrics
          : metricsRoot.validation,
        "validation",
      ) ??
      (idModelDto &&
      isPlainObject(idModelDto.metrics) &&
      isPlainObject(idModelDto.metrics.validation)
        ? parsePartitionMetrics(idModelDto.metrics.validation, "validation")
        : null);

    const icRaw = isPlainObject(metricsRoot.information_criteria)
      ? metricsRoot.information_criteria
      : idModelDto &&
          isPlainObject(idModelDto.metrics) &&
          isPlainObject(idModelDto.metrics.information_criteria)
        ? idModelDto.metrics.information_criteria
        : {};
    const informationCriteria: IdentificationInformationCriteriaView = {
      aic: parseFiniteNumOrNull(icRaw.aic ?? diag.aic),
      bic: parseFiniteNumOrNull(icRaw.bic ?? diag.bic),
      fpe: parseFiniteNumOrNull(icRaw.fpe ?? diag.fpe),
    };

    const excDto =
      idModelDto && isPlainObject(idModelDto.excitation_diagnostics)
        ? idModelDto.excitation_diagnostics
        : {};
    const peDto = isPlainObject(excDto.pe_diagnostics)
      ? excDto.pe_diagnostics
      : {};

    const singularValues: number[] = Array.isArray(diag.singular_values)
      ? diag.singular_values.filter(
          (v): v is number => typeof v === "number" && Number.isFinite(v),
        )
      : [];
    const hankelSvals: number[] = Array.isArray(diag.hankel_singular_values)
      ? diag.hankel_singular_values.filter(
          (v): v is number => typeof v === "number" && Number.isFinite(v),
        )
      : extractFirstChannelFromTensor(res.hankel_singular_values);

    const rankVal =
      typeof diag.rank === "number"
        ? diag.rank
        : Array.isArray(diag.rank)
          ? (diag.rank as number[])
          : null;
    const expectedRankVal =
      typeof diag.expected_rank === "number"
        ? diag.expected_rank
        : Array.isArray(diag.expected_rank)
          ? (diag.expected_rank as number[])
          : null;

    const excitation: IdentificationExcitationDiagnosticsView = {
      rank: rankVal,
      expected_rank: expectedRankVal,
      rank_deficient: Boolean(
        diag.rank_deficient ?? excDto.rank_deficient ?? false,
      ),
      condition: parseFiniteNumOrNull(
        diag.condition ?? excDto.condition ?? peDto.condition_raw,
      ),
      pe_satisfied:
        typeof resp.assumptions?.pe_satisfied === "boolean"
          ? resp.assumptions.pe_satisfied
          : typeof peDto.pe_satisfied === "boolean"
            ? peDto.pe_satisfied
            : null,
      singular_values: singularValues,
      hankel_singular_values: hankelSvals,
    };

    const residRoot =
      idModelDto && isPlainObject(idModelDto.residual_diagnostics)
        ? idModelDto.residual_diagnostics
        : {};
    const trainResiduals = parseResidualDiagnostics(residRoot.train, "train");
    const validationResiduals =
      operation === "identification.validate_model"
        ? parseResidualDiagnostics(res.residual_diagnostics, "validation")
        : parseResidualDiagnostics(residRoot.validation, "validation");

    const poles = parseComplexPairOrNull(res.poles);
    const spectralRadius = parseFiniteNumOrNull(
      res.spectral_radius ?? diag.spectral_radius,
    );
    const isStable =
      typeof res.is_stable === "boolean"
        ? res.is_stable
        : typeof diag.is_stable === "boolean"
          ? diag.is_stable
          : typeof resp.assumptions?.predictor_stable === "boolean"
            ? resp.assumptions.predictor_stable
            : null;

    const paramsSummary: Record<string, unknown> = isPlainObject(res.parameters)
      ? structuredClone(res.parameters)
      : {};
    if (typeof res.order === "number") paramsSummary.order = res.order;
    if (typeof res.horizon === "number") paramsSummary.horizon = res.horizon;

    // Séries temporais para gráficos (alinhando com os Datasets registrados na sessão)
    const trainDsSeries = extractDatasetSeries(trainSel?.object ?? null);
    let trainSeries: IdentificationSeriesSnapshot | null = null;
    if (trainDsSeries) {
      const yPredTr = extractFirstChannelFromTensor(res.y_hat_train_one_step);
      const ySimTr = extractFirstChannelFromTensor(res.y_hat_train_free_sim);
      const resTr = extractFirstChannelFromTensor(res.residuals_train);
      if (yPredTr.length > 0 || ySimTr.length > 0) {
        const n = trainDsSeries.t.length;
        const alignedPred = alignTailToLength(yPredTr, n, trainDsSeries.y[0] ?? 0);
        const alignedSim = alignTailToLength(ySimTr, n, trainDsSeries.y[0] ?? 0);
        const alignedRes1 =
          resTr.length > 0
            ? alignTailToLength(resTr, n, 0)
            : alignedPred.length === n
              ? trainDsSeries.y.map((yv, idx) => yv - alignedPred[idx])
              : [];
        const computedResFree =
          alignedSim.length === n
            ? trainDsSeries.y.map((yv, idx) => yv - alignedSim[idx])
            : [];
        trainSeries = {
          partition: "train",
          dt: trainDsSeries.dt ?? dtFromModel,
          t: trainDsSeries.t,
          u: trainDsSeries.u,
          y_measured: trainDsSeries.y,
          y_one_step: alignedPred,
          y_free_sim: alignedSim,
          residuals: alignedRes1,
          residuals_free_sim: computedResFree,
          units: trainDsSeries.units,
        };
      }
    }

    const valDsObj = valSel?.object ?? trainSel?.object ?? null;
    const valDsSeries = extractDatasetSeries(valDsObj);
    let validationSeries: IdentificationSeriesSnapshot | null = null;
    if (valDsSeries) {
      const yPredVal = extractFirstChannelFromTensor(
        operation === "identification.validate_model"
          ? res.y_hat_one_step
          : res.y_hat_val_one_step,
      );
      const ySimVal = extractFirstChannelFromTensor(
        operation === "identification.validate_model"
          ? res.y_hat_free_sim
          : res.y_hat_val_free_sim,
      );
      if (yPredVal.length > 0 || ySimVal.length > 0) {
        const n = valDsSeries.t.length;
        const alignedPred = alignTailToLength(yPredVal, n, valDsSeries.y[0] ?? 0);
        const alignedSim = alignTailToLength(ySimVal, n, valDsSeries.y[0] ?? 0);
        const computedRes =
          alignedPred.length === n
            ? valDsSeries.y.map((yv, idx) => yv - alignedPred[idx])
            : [];
        const computedResFree =
          alignedSim.length === n
            ? valDsSeries.y.map((yv, idx) => yv - alignedSim[idx])
            : [];
        validationSeries = {
          partition: "validation",
          dt: valDsSeries.dt ?? dtFromModel,
          t: valDsSeries.t,
          u: valDsSeries.u,
          y_measured: valDsSeries.y,
          y_one_step: alignedPred,
          y_free_sim: alignedSim,
          residuals: computedRes,
          residuals_free_sim: computedResFree,
          units: valDsSeries.units,
        };
      }
    }

    return {
      operation,
      request_id: resp.request_id,
      project_id: resp.project_id,
      project_revision: resp.project_revision,
      status: resp.status,
      algorithm,
      inner_model_kind: innerModelKind,
      model_ref: modelRef,
      train_dataset_ref: trainSel?.ref ?? null,
      val_dataset_ref: valSel?.ref ?? null,
      dt: dtFromModel,
      spectral_radius: spectralRadius,
      is_stable: isStable,
      poles,
      parameters_summary: paramsSummary,
      train_metrics: trainMetrics,
      validation_metrics: valMetrics,
      information_criteria: informationCriteria,
      excitation,
      train_residuals: trainResiduals,
      validation_residuals: validationResiduals,
      train_series: trainSeries,
      validation_series: validationSeries,
      warnings: [...resp.warnings],
      provenance: structuredClone(resp.provenance),
      response: structuredClone(resp),
      recorded_at: new Date().toISOString(),
    };
  }

  private resolveSeriesAndSourceReport(partition?: "train" | "validation"): {
    series: IdentificationSeriesSnapshot;
    sourceReport: IdentificationReportView;
  } | null {
    const targetPart = partition ?? this.activePartitionView;
    const valReport = this.lastValidationReport;
    const fitReport = this.lastFitReport;

    let series: IdentificationSeriesSnapshot | null = null;
    let sourceReport: IdentificationReportView | null = null;

    if (targetPart === "validation") {
      if (valReport?.validation_series) {
        series = valReport.validation_series;
        sourceReport = valReport;
      } else if (fitReport?.validation_series) {
        series = fitReport.validation_series;
        sourceReport = fitReport;
      } else if (fitReport?.train_series) {
        series = fitReport.train_series;
        sourceReport = fitReport;
      }
    } else {
      if (fitReport?.train_series) {
        series = fitReport.train_series;
        sourceReport = fitReport;
      } else if (valReport?.validation_series) {
        series = valReport.validation_series;
        sourceReport = valReport;
      }
    }

    if (!series || !sourceReport) {
      return null;
    }
    return { series, sourceReport };
  }

  /**
   * Constrói o gráfico temporal comparativo (y medido vs previsão 1-passo vs simulação livre vs resíduos)
   * para a partição selecionada (`train` ou `validation`).
   */
  public buildResponseChart(
    partition?: "train" | "validation",
  ): TimeResponseChartModel | null {
    const resolved = this.resolveSeriesAndSourceReport(partition);
    if (!resolved) return null;
    const { series, sourceReport } = resolved;

    return buildIdentificationResponseChartModel({
      chart_id: `id-response-${series.partition}`,
      partition: series.partition,
      dt: series.dt,
      t: series.t,
      y_measured: series.y_measured,
      y_one_step: series.y_one_step,
      y_free_sim: series.y_free_sim,
      residuals: series.residuals,
      residuals_free_sim: series.residuals_free_sim,
      u: series.u,
      units: series.units,
      model_revision: sourceReport.model_ref?.revision ?? null,
      project_revision: sourceReport.project_revision,
      provenance: sourceReport.provenance,
      series_semantics:
        sourceReport.status === "warning" ? "approximate" : "numeric_verified",
      theme_mode: this.themeModeProvider(),
    });
  }

  /**
   * Constrói os 4 modelos de gráficos sincronizados separados (Entrada u(k), Previsão 1-Passo vs y,
   * Simulação Livre vs y e Resíduos 1-Passo vs Simulação Livre).
   */
  public buildSplitResponseCharts(partition?: "train" | "validation"): {
    inputChart: TimeResponseChartModel;
    oneStepChart: TimeResponseChartModel;
    freeSimChart: TimeResponseChartModel;
    residualsChart: TimeResponseChartModel;
  } | null {
    const combined = this.buildResponseChart(partition);
    if (!combined) return null;

    const filterChannels = (pred: (id: string) => boolean, chartId: string, title: string): TimeResponseChartModel => ({
      ...combined,
      chart_id: chartId,
      title,
      channels: combined.channels.filter((ch) => pred(ch.id)),
    });

    return {
      inputChart: filterChannels(
        (id) => id.startsWith("u-input-"),
        "id-plot-input",
        "1. Entrada u(k)",
      ),
      oneStepChart: filterChannels(
        (id) => id.startsWith("y-measured-") || id.startsWith("y-hat-one-step-"),
        "id-plot-one-step",
        "2. Previsão 1-Passo à Frente vs. Saída Medida",
      ),
      freeSimChart: filterChannels(
        (id) => id.startsWith("y-measured-") || id.startsWith("y-hat-free-sim-"),
        "id-plot-free-sim",
        "3. Simulação Livre vs. Saída Medida",
      ),
      residualsChart: filterChannels(
        (id) => id.startsWith("residuals-one-step-") || id.startsWith("residuals-free-sim-"),
        "id-plot-residuals",
        "4. Resíduos: 1-Passo vs. Simulação Livre",
      ),
    };
  }

  /**
   * Constrói o gráfico de correlação de resíduos ($R_{\varepsilon\varepsilon}(\tau)$ e $R_{u\varepsilon}(\tau)$
   * com bandas de confiança de 95% e 99%) retornado pelo motor Python.
   */
  public buildResidualCorrelationChart(
    partition?: "train" | "validation",
  ): ResidualCorrelationChartModel | null {
    const targetPart = partition ?? this.activePartitionView;
    const valReport = this.lastValidationReport;
    const fitReport = this.lastFitReport;

    let resid: IdentificationResidualDiagnosticsView | null = null;
    let sourceReport: IdentificationReportView | null = null;

    if (targetPart === "validation") {
      if (valReport?.validation_residuals) {
        resid = valReport.validation_residuals;
        sourceReport = valReport;
      } else if (fitReport?.validation_residuals) {
        resid = fitReport.validation_residuals;
        sourceReport = fitReport;
      } else if (fitReport?.train_residuals) {
        resid = fitReport.train_residuals;
        sourceReport = fitReport;
      }
    } else {
      if (fitReport?.train_residuals) {
        resid = fitReport.train_residuals;
        sourceReport = fitReport;
      } else if (valReport?.validation_residuals) {
        resid = valReport.validation_residuals;
        sourceReport = valReport;
      }
    }

    if (!resid || !sourceReport || resid.lags.length === 0) {
      return null;
    }

    return buildResidualCorrelationChartModel({
      chart_id: `id-residuals-corr-${resid.partition}`,
      partition: resid.partition,
      n_effective_samples: resid.n_effective_samples,
      bound_95: resid.bound_95,
      bound_99: resid.bound_99,
      lags: resid.lags,
      autocorrelation: resid.autocorrelation,
      cross_lags: resid.cross_lags,
      crosscorrelation_u_e: resid.crosscorrelation_u_e,
      whiteness_within_99_fraction: resid.whiteness_within_99_fraction,
      uncorrelated_input_within_99_fraction:
        resid.uncorrelated_input_within_99_fraction,
      model_revision: sourceReport.model_ref?.revision ?? null,
      project_revision: sourceReport.project_revision,
      provenance: sourceReport.provenance,
      series_semantics:
        sourceReport.status === "warning" ? "approximate" : "numeric_verified",
      theme_mode: this.themeModeProvider(),
    });
  }

  /**
   * Constrói o mapa de polos discretos estimados no plano-z (com círculo unitário $|z|=1$).
   */
  public buildIdentifiedPoleZeroChart(): PoleZeroChartModel | null {
    const report = this.lastValidationReport ?? this.lastFitReport;
    if (!report || !report.poles || report.poles.real.length === 0) {
      return null;
    }
    return buildPoleZeroChartModel({
      chart_id: "id-pole-zero-map",
      title: `Polos Discretos Estimados (${report.algorithm})`,
      dt: report.dt ?? 1.0,
      model_revision: report.model_ref?.revision ?? null,
      project_revision: report.project_revision,
      provenance: report.provenance,
      series_semantics:
        report.status === "warning" ? "approximate" : "numeric_verified",
      open_loop_poles: report.poles,
      theme_mode: this.themeModeProvider(),
    });
  }

  /**
   * Fluxo explícito de reutilização do modelo identificado (R-06 / T-ID-04):
   * 1. Exige que o `IdentifiedModel` esteja registrado (ou registra-o explicitamente
   *    se `registerIdentifiedIfPending=true`).
   * 2. Chama `core.reuse_model` com `targetKind` (`native` ou `StateSpace`).
   * 3. Registra explicitamente o modelo derivado quando `registerDerived=true`.
   * 4. Opcionalmente aplica ao workspace LQR (Aba 3) ou seleciona para Frequência SISO (Aba 2).
   */
  public async reuseIdentifiedModel(options: {
    targetKind: "native" | "StateSpace";
    registerIdentifiedIfPending?: boolean;
    registerDerived?: boolean;
    applyToDestination?: "none" | "lqr" | "siso_frequency";
  }): Promise<{
    identifiedObject: RegisteredTypedObject | null;
    reuseOutcome: ReuseModelOutcome;
    derivedObject: RegisteredTypedObject | null;
  }> {
    this.lastError = null;
    let identifiedObject: RegisteredTypedObject | null = null;
    const pendingId = this.typedWorkspace.getPendingIdentifiedModel();

    if (pendingId && !pendingId.registered) {
      if (options.registerIdentifiedIfPending) {
        identifiedObject =
          await this.typedWorkspace.registerPendingIdentifiedModel({
            selectForReuse: true,
          });
      } else {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Registre explicitamente o IdentifiedModel pendente antes de executar core.reuse_model.",
        );
      }
    }

    const reuseOutcome = await this.typedWorkspace.reuseModel({
      targetKind: options.targetKind,
      sourceRef: identifiedObject
        ? { id: identifiedObject.id, revision: identifiedObject.revision }
        : undefined,
    });

    let derivedObject: RegisteredTypedObject | null = null;
    if (options.registerDerived) {
      derivedObject = await this.typedWorkspace.registerPendingDerivedModel({
        selectCompatible: true,
      });

      if (options.applyToDestination === "lqr") {
        if (derivedObject.kind !== "StateSpace") {
          throw new ControlLabBridgeError(
            "UNSUPPORTED_MODEL",
            `O workspace LQR requer um modelo derivado 'StateSpace', recebido '${derivedObject.kind}'.`,
          );
        }
        this.onApplyStateSpaceToLqr?.();
        this.onSwitchTab?.("statespace");
      } else if (options.applyToDestination === "siso_frequency") {
        this.typedWorkspace.selectRef("frequencyPlant", {
          id: derivedObject.id,
          revision: derivedObject.revision,
        });
        this.onSwitchTab?.("siso_frequency");
      }
    }

    this.notify();
    return {
      identifiedObject,
      reuseOutcome,
      derivedObject,
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
