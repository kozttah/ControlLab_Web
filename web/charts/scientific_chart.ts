/**
 * Motor gráfico desacoplado de apresentação científica (mapa polo-zero,
 * resposta temporal x/u/y, tabela acessível WCAG 2.2 AA, exportação CSV,
 * tratamento de séries constantes e orçamento de 60 FPS para Fast-Preview)
 * (CL-DIR-001 Seções 7.1–7.4, 13.10, R-26, R-27).
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping e erasableSyntaxOnly.
 */

import {
  ControlLabBridgeError,
  type ComplexVectorPair,
  type Provenance,
} from "../bridge/protocol.ts";
import {
  escapeHtml,
  formatNumericDisplay,
  getThemeTokens,
  type AccessibilityThemeMode,
} from "../app/accessibility.ts";
import type { ResultVerificationIndicator } from "../app/tool_descriptor.ts";
import {
  createSecondOrderRegionOverlay,
  generateOverlaySvgPath,
  type ChartViewport,
  type OverlayConfidenceClass,
  type RequirementOverlay,
} from "./overlays.ts";

export const FRAME_BUDGET_60FPS_MS = 1000 / 60; // ~16.6667 ms

export type PointMarkerShape =
  | "circle"
  | "cross"
  | "diamond"
  | "triangle"
  | "square";

const SERIES_DASH_PATTERNS: readonly string[] = [
  "",
  "6 3",
  "2 2",
  "8 3 2 3",
  "10 2 2 2",
  "4 2",
];

const SERIES_MARKER_SHAPES: readonly PointMarkerShape[] = [
  "circle",
  "square",
  "triangle",
  "diamond",
  "cross",
];

export interface AxisBounds {
  min: number;
  max: number;
  span: number;
  isConstant: boolean;
}

/**
 * Calcula limites seguros para qualquer conjunto de valores (inclusive arrays
 * vazios ou com todos os elementos idênticos/constantes), evitando divisão por zero
 * e coordenadas NaN/Infinity em SVG.
 */
export function computeSafeAxisBounds(
  values: readonly number[],
  paddingRatio = 0.12,
): AxisBounds {
  const finiteVals = values.filter((v) => typeof v === "number" && Number.isFinite(v));
  if (finiteVals.length === 0) {
    return { min: -1, max: 1, span: 2, isConstant: true };
  }
  let min = finiteVals[0];
  let max = finiteVals[0];
  for (let i = 1; i < finiteVals.length; i += 1) {
    const v = finiteVals[i];
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const rawSpan = max - min;
  if (rawSpan <= 1e-12) {
    const center = min;
    const pad = Math.max(0.5, Math.abs(center) * 0.15);
    return {
      min: center - pad,
      max: center + pad,
      span: 2 * pad,
      isConstant: true,
    };
  }
  const pad = rawSpan * Math.max(0.02, paddingRatio);
  return {
    min: min - pad,
    max: max + pad,
    span: rawSpan + 2 * pad,
    isConstant: false,
  };
}

function formatAxisTickLabel(v: number, decimals: number): string {
  const cleaned = Number.isFinite(v) && Math.abs(v) < 1e-12 ? 0 : v;
  return formatNumericDisplay(cleaned, decimals);
}

function formatChartHeadingTitle(
  title: string,
  seriesSemantics: ResultVerificationIndicator,
): string {
  if (seriesSemantics === "preview") {
    return `${title} (Pré-visualização)`;
  }
  return title;
}

export interface ChartUnitsMetadata {
  x_axis: string;
  y_axis: string;
  time?: string;
  states?: readonly string[];
  inputs?: readonly string[];
  outputs?: readonly string[];
}

export interface ChartCommonMetadata {
  chart_id: string;
  title: string;
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics: ResultVerificationIndicator;
  feedback_sign?: "negative" | "positive";
  units: ChartUnitsMetadata;
  theme_mode?: AccessibilityThemeMode;
}

export interface PoleZeroSeries {
  id: string;
  label: string;
  poles: ComplexVectorPair;
  shape: PointMarkerShape;
  stroke_dasharray: string;
  series_semantics: ResultVerificationIndicator;
}

export interface PoleZeroChartModel extends ChartCommonMetadata {
  kind: "pole_zero";
  dt: number | null;
  open_loop_poles: ComplexVectorPair | null;
  committed_closed_loop_poles: ComplexVectorPair | null;
  preview_poles: ComplexVectorPair | null;
  zeros: ComplexVectorPair | null;
  overlays: readonly RequirementOverlay[];
}

export interface TimeSeriesChannel {
  id: string;
  group: "x" | "u" | "y";
  label: string;
  unit: string;
  values: readonly number[];
  shape: PointMarkerShape;
  stroke_dasharray: string;
  series_semantics: ResultVerificationIndicator;
  color?: string;
}

export interface TimeResponseChartModel extends ChartCommonMetadata {
  kind: "time_response";
  dt: number | null;
  t: readonly number[];
  channels: readonly TimeSeriesChannel[];
  preview_channels: readonly TimeSeriesChannel[];
}

export interface ResidualCorrelationChartModel extends ChartCommonMetadata {
  kind: "residual_correlation";
  partition: "train" | "validation";
  n_effective_samples: number;
  bound_95: number;
  bound_99: number;
  lags: readonly number[];
  autocorrelation: readonly number[];
  cross_lags: readonly number[];
  crosscorrelation_u_e: readonly number[];
  whiteness_within_99_fraction: number | null;
  uncorrelated_input_within_99_fraction: number | null;
}

export interface FrequencyCrossingMarker {
  id: string;
  kind: "gain_crossover" | "phase_crossover";
  omega: number;
  mag_db: number;
  phase_deg: number;
  label: string;
}

export interface BodeChartModel extends ChartCommonMetadata {
  kind: "bode";
  dt: number | null;
  omega: readonly number[];
  mag_db: readonly number[];
  phase_deg: readonly number[];
  markers: readonly FrequencyCrossingMarker[];
  delay_representation: "none" | "exact" | "pade";
}

export interface NyquistStabilityMarginsMetadata {
  gain_margin?: number | null;
  gain_margin_db?: number | null;
  phase_margin_deg?: number | null;
  w_gc?: number | null;
  w_pc?: number | null;
}

export interface NyquistChartModel extends ChartCommonMetadata {
  kind: "nyquist";
  dt: number | null;
  omega: readonly number[];
  re: readonly number[];
  im: readonly number[];
  delay_representation: "none" | "exact" | "pade";
  margins?: NyquistStabilityMarginsMetadata | null;
}

export interface RootLocusChartModel extends ChartCommonMetadata {
  kind: "root_locus";
  dt: number | null;
  gains: readonly number[];
  /** branches[b].real[i] / imag[i] = raiz do ramo b no ganho gains[i]. */
  branches: ReadonlyArray<{ real: readonly number[]; imag: readonly number[] }>;
  open_loop_poles: ComplexVectorPair | null;
  open_loop_zeros: ComplexVectorPair | null;
  breakaway_points: readonly number[];
  stability_crossings: readonly unknown[];
  overlays: readonly RequirementOverlay[];
}

export interface SingularValueCurve {
  id: string;
  label: string;
  group: "G" | "S" | "T" | "KS";
  omega: readonly number[];
  values_db: readonly number[];
  stroke_dasharray?: string;
}

export interface SingularValuesChartModel extends ChartCommonMetadata {
  kind: "singular_values";
  dt: number | null;
  omega: readonly number[];
  curves: readonly SingularValueCurve[];
}

export interface FuzzySurfaceChartModel extends ChartCommonMetadata {
  kind: "fuzzy_surface";
  axes: readonly string[];
  output_name: string;
  x0_grid: readonly number[];
  x1_grid: readonly number[] | null;
  /** 2D surface values z[i][j] when axes.length === 2, or null when 1D. */
  z_matrix: ReadonlyArray<readonly number[]> | null;
  /** 1D curve values z[i] when axes.length === 1, or null when 2D. */
  z_line: readonly number[] | null;
}

export interface LmiSpectrumChartModel extends ChartCommonMetadata {
  kind: "lmi_spectrum";
  block_min_eigs: readonly number[];
  block_labels: readonly string[];
  closed_loop_poles: ComplexVectorPair | null;
  alpha: number | null;
}

export type ScientificChartModel =
  | PoleZeroChartModel
  | TimeResponseChartModel
  | ResidualCorrelationChartModel
  | BodeChartModel
  | NyquistChartModel
  | RootLocusChartModel
  | SingularValuesChartModel
  | FuzzySurfaceChartModel
  | LmiSpectrumChartModel;

export function buildIdentificationResponseChartModel(input: {
  chart_id?: string;
  title?: string;
  partition: "train" | "validation";
  dt: number | null;
  t: readonly number[];
  y_measured: readonly number[];
  y_one_step?: readonly number[] | null;
  y_free_sim?: readonly number[] | null;
  residuals?: readonly number[] | null;
  residuals_free_sim?: readonly number[] | null;
  u?: readonly number[] | null;
  units?: {
    time?: string;
    input?: string;
    output?: string;
  };
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics?: ResultVerificationIndicator;
  theme_mode?: AccessibilityThemeMode;
}): TimeResponseChartModel {
  const semantics = input.series_semantics ?? "numeric_verified";
  const timeUnit = input.units?.time ?? "s";
  const outUnit = input.units?.output ?? "y";
  const inUnit = input.units?.input ?? "u";
  const partLabel = input.partition === "validation" ? "Holdout" : "Treino";

  const channels: TimeSeriesChannel[] = [
    {
      id: `y-measured-${input.partition}`,
      group: "y",
      label: `y Medido (${partLabel})`,
      unit: outUnit,
      values: [...input.y_measured],
      shape: "circle",
      stroke_dasharray: "",
      series_semantics: semantics,
    },
  ];

  if (input.y_one_step && input.y_one_step.length > 0) {
    channels.push({
      id: `y-hat-one-step-${input.partition}`,
      group: "y",
      label: `ŷ Previsão 1-Passo (${partLabel})`,
      unit: outUnit,
      values: [...input.y_one_step],
      shape: "square",
      stroke_dasharray: "2 2",
      series_semantics: semantics,
    });
  }

  if (input.y_free_sim && input.y_free_sim.length > 0) {
    channels.push({
      id: `y-hat-free-sim-${input.partition}`,
      group: "x",
      label: `ŷ Simulação Livre (${partLabel})`,
      unit: outUnit,
      values: [...input.y_free_sim],
      shape: "triangle",
      stroke_dasharray: "6 3",
      series_semantics: semantics,
    });
  }

  const resOneStepVals =
    input.residuals && input.residuals.length > 0
      ? [...input.residuals]
      : input.y_one_step && input.y_one_step.length > 0
        ? input.y_measured.map((yVal, idx) => yVal - (input.y_one_step![idx] ?? yVal))
        : [];
  if (resOneStepVals.length > 0) {
    channels.push({
      id: `residuals-one-step-${input.partition}`,
      group: "u",
      label: `Resíduo 1-Passo e(k)=y-ŷ (${partLabel})`,
      unit: outUnit,
      values: resOneStepVals,
      shape: "diamond",
      stroke_dasharray: "",
      series_semantics: semantics,
    });
  }

  const resFreeSimVals =
    input.residuals_free_sim && input.residuals_free_sim.length > 0
      ? [...input.residuals_free_sim]
      : input.y_free_sim && input.y_free_sim.length > 0
        ? input.y_measured.map((yVal, idx) => yVal - (input.y_free_sim![idx] ?? yVal))
        : [];
  if (resFreeSimVals.length > 0) {
    channels.push({
      id: `residuals-free-sim-${input.partition}`,
      group: "u",
      label: `Resíduo Simulação Livre e_livre(k)=y-ŷ_livre (${partLabel})`,
      unit: outUnit,
      values: resFreeSimVals,
      shape: "diamond",
      stroke_dasharray: "6 3",
      series_semantics: semantics,
    });
  }

  if (input.u && input.u.length > 0) {
    channels.push({
      id: `u-input-${input.partition}`,
      group: "u",
      label: `Entrada u(k) (${partLabel})`,
      unit: inUnit,
      values: [...input.u],
      shape: "cross",
      stroke_dasharray: "",
      series_semantics: semantics,
    });
  }

  return {
    kind: "time_response",
    chart_id: input.chart_id ?? `id-response-${input.partition}`,
    title:
      input.title ??
      `Identificação (${partLabel}): y Medido vs Previsão 1-Passo vs Simulação Livre`,
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: semantics,
    units: {
      x_axis: `Tempo [${timeUnit}]`,
      y_axis: `Saída [${outUnit}]`,
      time: timeUnit,
      inputs: [inUnit],
      outputs: [outUnit],
    },
    theme_mode: input.theme_mode ?? "standard_aa",
    dt: input.dt,
    t: [...input.t],
    channels,
    preview_channels: [],
  };
}

export function buildResidualCorrelationChartModel(input: {
  chart_id?: string;
  title?: string;
  partition: "train" | "validation";
  n_effective_samples: number;
  bound_95: number;
  bound_99: number;
  lags: readonly number[];
  autocorrelation: readonly number[];
  cross_lags: readonly number[];
  crosscorrelation_u_e: readonly number[];
  whiteness_within_99_fraction?: number | null;
  uncorrelated_input_within_99_fraction?: number | null;
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics?: ResultVerificationIndicator;
  theme_mode?: AccessibilityThemeMode;
}): ResidualCorrelationChartModel {
  const partLabel = input.partition === "validation" ? "Holdout" : "Treino";
  return {
    kind: "residual_correlation",
    chart_id: input.chart_id ?? `id-residuals-corr-${input.partition}`,
    title:
      input.title ??
      `Diagnóstico de Resíduos (${partLabel}): Autocorrelação R_ee(τ) e Correlação Cruzada R_ue(τ)`,
    partition: input.partition,
    n_effective_samples: input.n_effective_samples,
    bound_95: input.bound_95,
    bound_99: input.bound_99,
    lags: [...input.lags],
    autocorrelation: [...input.autocorrelation],
    cross_lags: [...input.cross_lags],
    crosscorrelation_u_e: [...input.crosscorrelation_u_e],
    whiteness_within_99_fraction: input.whiteness_within_99_fraction ?? null,
    uncorrelated_input_within_99_fraction:
      input.uncorrelated_input_within_99_fraction ?? null,
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics ?? "numeric_verified",
    units: {
      x_axis: "Atraso (Lag τ [amostras])",
      y_axis: "Correlação Normalizada [-1, 1]",
    },
    theme_mode: input.theme_mode ?? "standard_aa",
  };
}

export function buildBodeChartModel(input: {
  chart_id?: string;
  title?: string;
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics?: ResultVerificationIndicator;
  theme_mode?: AccessibilityThemeMode;
  dt: number | null;
  omega: readonly number[];
  mag_db: readonly number[];
  phase_deg: readonly number[];
  markers?: readonly FrequencyCrossingMarker[];
  delay_representation?: "none" | "exact" | "pade";
}): BodeChartModel {
  return {
    kind: "bode",
    chart_id: input.chart_id ?? "siso-bode-chart",
    title: input.title ?? "Diagrama de Bode SISO",
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics ?? "numeric_verified",
    units: {
      x_axis: "Frequência [rad/s]",
      y_axis: "Magnitude [dB] / Fase [graus]",
    },
    theme_mode: input.theme_mode ?? "standard_aa",
    dt: input.dt,
    omega: [...input.omega],
    mag_db: [...input.mag_db],
    phase_deg: [...input.phase_deg],
    markers: input.markers ? [...input.markers] : [],
    delay_representation: input.delay_representation ?? "none",
  };
}

export function buildNyquistChartModel(input: {
  chart_id?: string;
  title?: string;
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics?: ResultVerificationIndicator;
  theme_mode?: AccessibilityThemeMode;
  dt: number | null;
  omega: readonly number[];
  re: readonly number[];
  im: readonly number[];
  delay_representation?: "none" | "exact" | "pade";
  margins?: NyquistStabilityMarginsMetadata | null;
}): NyquistChartModel {
  return {
    kind: "nyquist",
    chart_id: input.chart_id ?? "siso-nyquist-chart",
    title: input.title ?? "Diagrama de Nyquist SISO",
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics ?? "numeric_verified",
    units: {
      x_axis: "Parte Real Re G(jω)",
      y_axis: "Parte Imaginária Im G(jω)",
    },
    theme_mode: input.theme_mode ?? "standard_aa",
    dt: input.dt,
    omega: [...input.omega],
    re: [...input.re],
    im: [...input.im],
    delay_representation: input.delay_representation ?? "none",
    margins: input.margins ? { ...input.margins } : undefined,
  };
}

export function buildRootLocusChartModel(input: {
  chart_id?: string;
  title?: string;
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics?: ResultVerificationIndicator;
  theme_mode?: AccessibilityThemeMode;
  dt: number | null;
  gains: readonly number[];
  branches: ReadonlyArray<{ real: readonly number[]; imag: readonly number[] }>;
  open_loop_poles?: ComplexVectorPair | null;
  open_loop_zeros?: ComplexVectorPair | null;
  breakaway_points?: readonly number[];
  stability_crossings?: readonly unknown[];
  overlays?: readonly RequirementOverlay[];
}): RootLocusChartModel {
  return {
    kind: "root_locus",
    chart_id: input.chart_id ?? "siso-root-locus-chart",
    title: input.title ?? "Lugar das Raízes SISO (Root Locus)",
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics ?? "numeric_verified",
    units: {
      x_axis: "Eixo Real (Re)",
      y_axis: "Eixo Imaginário (Im)",
    },
    theme_mode: input.theme_mode ?? "standard_aa",
    dt: input.dt,
    gains: [...input.gains],
    branches: input.branches.map((b) => ({ real: [...b.real], imag: [...b.imag] })),
    open_loop_poles: input.open_loop_poles ?? null,
    open_loop_zeros: input.open_loop_zeros ?? null,
    breakaway_points: input.breakaway_points ? [...input.breakaway_points] : [],
    stability_crossings: input.stability_crossings ? [...input.stability_crossings] : [],
    overlays: input.overlays ? [...input.overlays] : [],
  };
}


export function renderResidualCorrelationSvg(
  model: ResidualCorrelationChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 360;
  const decimals = options?.decimals ?? 3;
  const theme = getThemeTokens(options?.themeMode ?? model.theme_mode ?? "standard_aa");

  const allLags: number[] = [0, ...model.lags, ...model.cross_lags];
  const allVals: number[] = [
    -1,
    1,
    model.bound_95,
    -model.bound_95,
    model.bound_99,
    -model.bound_99,
    ...model.autocorrelation,
    ...model.crosscorrelation_u_e,
  ];
  const xBounds = computeSafeAxisBounds(allLags, 0.06);
  const yBounds = computeSafeAxisBounds(allVals, 0.08);

  const padLeft = 64;
  const padRight = 24;
  const padTop = 44;
  const padBottom = 52;
  const plotW = widthPx - padLeft - padRight;
  const plotH = heightPx - padTop - padBottom;

  const toPxX = (lagVal: number) =>
    mapCoord(lagVal, xBounds.min, xBounds.span, padLeft, plotW, false);
  const toPxY = (corrVal: number) =>
    mapCoord(corrVal, yBounds.min, yBounds.span, padTop, plotH, true);

  const yZero = toPxY(0);
  const b95PosY = toPxY(model.bound_95);
  const b95NegY = toPxY(-model.bound_95);
  const b99PosY = toPxY(model.bound_99);
  const b99NegY = toPxY(-model.bound_99);

  const autoPoints: string[] = [];
  const autoCount = Math.min(model.lags.length, model.autocorrelation.length);
  for (let i = 0; i < autoCount; i += 1) {
    const lag = model.lags[i];
    const val = model.autocorrelation[i];
    const px = toPxX(lag);
    const py = toPxY(val);
    const within99 = lag === 0 || Math.abs(val) <= model.bound_99;
    const lbl = `R_ee(τ=${lag}) = ${formatNumericDisplay(val, decimals)} (${within99 ? "dentro 99%" : "FORA 99%"})`;
    autoPoints.push(
      `<line x1="${px.toFixed(2)}" y1="${yZero.toFixed(2)}" x2="${px.toFixed(2)}" y2="${py.toFixed(2)}" stroke="${theme.chartClosedLoop}" stroke-width="2" />` +
        renderMarkerSvg(
          within99 ? "circle" : "cross",
          px,
          py,
          4,
          theme.chartClosedLoop,
          lbl,
          `data-corr-kind="R_ee" data-lag="${lag}" data-within-99="${within99 ? "true" : "false"}"`,
        ),
    );
  }

  const crossPoints: string[] = [];
  const crossCount = Math.min(
    model.cross_lags.length,
    model.crosscorrelation_u_e.length,
  );
  for (let i = 0; i < crossCount; i += 1) {
    const lag = model.cross_lags[i];
    const val = model.crosscorrelation_u_e[i];
    const px = toPxX(lag);
    const py = toPxY(val);
    const within99 = Math.abs(val) <= model.bound_99;
    const lbl = `R_ue(τ=${lag}) = ${formatNumericDisplay(val, decimals)} (${within99 ? "dentro 99%" : "FORA 99%"})`;
    crossPoints.push(
      renderMarkerSvg(
        within99 ? "square" : "diamond",
        px,
        py,
        3.8,
        theme.chartOpenLoop,
        lbl,
        `data-corr-kind="R_ue" data-lag="${lag}" data-within-99="${within99 ? "true" : "false"}"`,
      ),
    );
  }
  const crossPolylinePts: string[] = [];
  for (let i = 0; i < crossCount; i += 1) {
    crossPolylinePts.push(
      `${toPxX(model.cross_lags[i]).toFixed(2)},${toPxY(model.crosscorrelation_u_e[i]).toFixed(2)}`,
    );
  }
  const crossPolyline =
    crossPolylinePts.length > 1
      ? `<polyline fill="none" stroke="${theme.chartOpenLoop}" stroke-width="1.6" stroke-dasharray="5 3" points="${crossPolylinePts.join(" ")}" data-series="R_ue" />`
      : "";

  const ariaSummary = `${model.title}; partição=${model.partition}; N_eff=${model.n_effective_samples}; banda 95%=±${formatNumericDisplay(model.bound_95, decimals)}; banda 99%=±${formatNumericDisplay(model.bound_99, decimals)}.`;

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${widthPx} ${heightPx}" role="img" aria-label="${escapeHtml(ariaSummary)}" style="background:${theme.surface};color:${theme.textPrimary}" data-chart-kind="residual_correlation" data-partition="${escapeHtml(model.partition)}" data-series-semantics="${escapeHtml(model.series_semantics)}" data-model-revision="${escapeHtml(String(model.model_revision))}" data-project-revision="${escapeHtml(String(model.project_revision))}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(ariaSummary)}</desc>`,
    `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
    `<line x1="${padLeft}" y1="${yZero.toFixed(2)}" x2="${widthPx - padRight}" y2="${yZero.toFixed(2)}" stroke="${theme.chartAxis}" stroke-width="1.2" />`,
    `<line x1="${padLeft}" y1="${b95PosY.toFixed(2)}" x2="${widthPx - padRight}" y2="${b95PosY.toFixed(2)}" stroke="${theme.chartOverlaySufficient}" stroke-dasharray="4 4" stroke-width="1.3" data-bound="95-upper"><title>Limite confiança 95% (+${escapeHtml(formatNumericDisplay(model.bound_95, decimals))})</title></line>`,
    `<line x1="${padLeft}" y1="${b95NegY.toFixed(2)}" x2="${widthPx - padRight}" y2="${b95NegY.toFixed(2)}" stroke="${theme.chartOverlaySufficient}" stroke-dasharray="4 4" stroke-width="1.3" data-bound="95-lower"><title>Limite confiança 95% (-${escapeHtml(formatNumericDisplay(model.bound_95, decimals))})</title></line>`,
    `<line x1="${padLeft}" y1="${b99PosY.toFixed(2)}" x2="${widthPx - padRight}" y2="${b99PosY.toFixed(2)}" stroke="${theme.chartOverlayHeuristic}" stroke-dasharray="2 3" stroke-width="1.4" data-bound="99-upper"><title>Limite confiança 99% (+${escapeHtml(formatNumericDisplay(model.bound_99, decimals))})</title></line>`,
    `<line x1="${padLeft}" y1="${b99NegY.toFixed(2)}" x2="${widthPx - padRight}" y2="${b99NegY.toFixed(2)}" stroke="${theme.chartOverlayHeuristic}" stroke-dasharray="2 3" stroke-width="1.4" data-bound="99-lower"><title>Limite confiança 99% (-${escapeHtml(formatNumericDisplay(model.bound_99, decimals))})</title></line>`,
    `<g data-layer="autocorrelation-R_ee">${autoPoints.join("")}</g>`,
    `<g data-layer="crosscorrelation-R_ue">${crossPolyline}${crossPoints.join("")}</g>`,
    `<g class="chart-legend" data-layer="legend">`,
    `<text x="${padLeft + 8}" y="${padTop + 14}" font-size="10" fill="${theme.chartClosedLoop}">● R_ee(τ) Autocorrelação</text>`,
    `<text x="${padLeft + 150}" y="${padTop + 14}" font-size="10" fill="${theme.chartOpenLoop}">■ R_ue(τ) Cruzada u-e</text>`,
    `<text x="${padLeft + 285}" y="${padTop + 14}" font-size="10" fill="${theme.chartOverlaySufficient}">-- Banda 95% (±${escapeHtml(formatNumericDisplay(model.bound_95, decimals))})</text>`,
    `<text x="${padLeft + 430}" y="${padTop + 14}" font-size="10" fill="${theme.chartOverlayHeuristic}">·· Banda 99% (±${escapeHtml(formatNumericDisplay(model.bound_99, decimals))})</text>`,
    `</g>`,
    `<text x="${padLeft}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(model.title)}</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(2)}" y="${heightPx - 10}" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.x_axis)} | N_eff=${model.n_effective_samples}</text>`,
    `<text x="16" y="${(padTop + plotH / 2).toFixed(2)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(2)})" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.y_axis)}</text>`,
    `</svg>`,
  ].join("");
}

export interface BodeDatatipInspection {
  sampleIndex: number;
  omega: number;
  mag_db: number;
  phase_deg: number;
  pxX: number;
  pxMagY: number;
  pxPhaseY: number;
}

export interface NyquistDatatipInspection {
  sampleIndex: number;
  omega: number;
  re: number;
  im: number;
  pxX: number;
  pxY: number;
  distance_to_minus_one: number;
  sensitivity_mag: number;
}

export interface RootLocusFrozenPole {
  branchIndex: number;
  real: number;
  imag: number;
  pxX: number;
  pxY: number;
}

export interface RootLocusDatatipInspection {
  gainIndex: number;
  branchIndex: number;
  gain_K: number;
  poles: RootLocusFrozenPole[];
}

function computeBodeGeometry(
  model: BodeChartModel,
  options?: { widthPx?: number; heightPx?: number },
) {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 480;
  const padLeft = 64;
  const padRight = 24;
  const padTop = 36;
  const plotW = widthPx - padLeft - padRight;
  const subH = Math.floor((heightPx - padTop - 70) / 2);
  const gap = 24;
  const magTop = padTop;
  const phaseTop = magTop + subH + gap;

  const omegas = model.omega.filter((w) => Number.isFinite(w) && w > 0);
  const minW = omegas.length > 0 ? Math.min(...omegas) : 0.01;
  const maxW = omegas.length > 0 ? Math.max(...omegas) : 100;
  const logMinW = Math.log10(minW);
  const logMaxW = Math.log10(maxW);
  const logSpanW = Math.max(1e-4, logMaxW - logMinW);

  const toPxX = (w: number) => {
    const logW = Math.log10(Math.max(minW, w));
    return padLeft + ((logW - logMinW) / logSpanW) * plotW;
  };

  const magBounds = computeSafeAxisBounds(model.mag_db, 0.1);
  const phaseBounds = computeSafeAxisBounds(model.phase_deg, 0.1);

  const toPxMagY = (db: number) =>
    magTop + ((magBounds.max - db) / Math.max(1e-4, magBounds.span)) * subH;
  const toPxPhaseY = (deg: number) =>
    phaseTop + ((phaseBounds.max - deg) / Math.max(1e-4, phaseBounds.span)) * subH;

  return {
    widthPx,
    heightPx,
    padLeft,
    padRight,
    padTop,
    plotW,
    subH,
    gap,
    magTop,
    phaseTop,
    minW,
    maxW,
    logMinW,
    logMaxW,
    logSpanW,
    magBounds,
    phaseBounds,
    toPxX,
    toPxMagY,
    toPxPhaseY,
  };
}

export function inspectBodeAtSvgPoint(
  model: BodeChartModel,
  svgX: number,
  options?: { widthPx?: number; heightPx?: number },
): BodeDatatipInspection | null {
  if (!Number.isFinite(svgX)) return null;
  const count = Math.min(model.omega.length, model.mag_db.length, model.phase_deg.length);
  if (count === 0) return null;

  const geom = computeBodeGeometry(model, options);
  let bestIdx = -1;
  let bestDist = Number.POSITIVE_INFINITY;
  let bestPxX = 0;

  for (let i = 0; i < count; i += 1) {
    const w = model.omega[i];
    const mag = model.mag_db[i];
    const phase = model.phase_deg[i];
    if (!Number.isFinite(w) || w <= 0 || !Number.isFinite(mag) || !Number.isFinite(phase)) {
      continue;
    }
    const pxX = geom.toPxX(w);
    const dist = Math.abs(pxX - svgX);
    if (dist < bestDist) {
      bestDist = dist;
      bestIdx = i;
      bestPxX = pxX;
    }
  }

  if (bestIdx < 0) return null;
  return {
    sampleIndex: bestIdx,
    omega: model.omega[bestIdx],
    mag_db: model.mag_db[bestIdx],
    phase_deg: model.phase_deg[bestIdx],
    pxX: bestPxX,
    pxMagY: geom.toPxMagY(model.mag_db[bestIdx]),
    pxPhaseY: geom.toPxPhaseY(model.phase_deg[bestIdx]),
  };
}

export function renderBodeSvg(
  model: BodeChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    selectedSampleIndex?: number | null;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const decimals = options?.decimals ?? 2;
  const theme = getThemeTokens(options?.themeMode ?? model.theme_mode ?? "standard_aa");
  const geom = computeBodeGeometry(model, options);
  const {
    widthPx,
    heightPx,
    padLeft,
    plotW,
    subH,
    magTop,
    phaseTop,
    minW,
    maxW,
    logMinW,
    logMaxW,
    magBounds,
    phaseBounds,
    toPxX,
    toPxMagY,
    toPxPhaseY,
  } = geom;

  const n = Math.min(model.omega.length, model.mag_db.length);
  const magPts: string[] = [];
  for (let i = 0; i < n; i += 1) {
    if (model.omega[i] > 0) {
      magPts.push(`${toPxX(model.omega[i]).toFixed(1)},${toPxMagY(model.mag_db[i]).toFixed(1)}`);
    }
  }

  const nPhase = Math.min(model.omega.length, model.phase_deg.length);
  const phasePts: string[] = [];
  for (let i = 0; i < nPhase; i += 1) {
    if (model.omega[i] > 0) {
      phasePts.push(`${toPxX(model.omega[i]).toFixed(1)},${toPxPhaseY(model.phase_deg[i]).toFixed(1)}`);
    }
  }

  const zeroDbY = toPxMagY(0);
  const minus180Y = toPxPhaseY(-180);

  const zeroDbLine =
    magBounds.min <= 0 && magBounds.max >= 0
      ? `<line x1="${padLeft}" y1="${zeroDbY.toFixed(1)}" x2="${padLeft + plotW}" y2="${zeroDbY.toFixed(1)}" stroke="${theme.chartGrid}" stroke-dasharray="4 3" stroke-width="1.2" data-reference-line="0db"><title>0 dB</title></line>`
      : "";

  const minus180Line =
    phaseBounds.min <= -180 && phaseBounds.max >= -180
      ? `<line x1="${padLeft}" y1="${minus180Y.toFixed(1)}" x2="${padLeft + plotW}" y2="${minus180Y.toFixed(1)}" stroke="${theme.chartGrid}" stroke-dasharray="4 3" stroke-width="1.2" data-reference-line="-180deg"><title>-180°</title></line>`
      : "";

  const markerSvgs: string[] = [];
  for (const m of model.markers) {
    const mx = toPxX(m.omega);
    const color = m.kind === "gain_crossover" ? theme.chartOverlayExact : theme.chartOpenLoop;
    markerSvgs.push(
      `<line x1="${mx.toFixed(1)}" y1="${magTop}" x2="${mx.toFixed(1)}" y2="${phaseTop + subH}" stroke="${color}" stroke-dasharray="2 2" stroke-width="1.2" data-marker-kind="${m.kind}"><title>${escapeHtml(m.label)}: ω=${formatNumericDisplay(m.omega, decimals)} rad/s</title></line>`,
      `<circle cx="${mx.toFixed(1)}" cy="${toPxMagY(m.mag_db).toFixed(1)}" r="4" fill="${color}"><title>${escapeHtml(m.label)} (|G|=${formatNumericDisplay(m.mag_db, decimals)} dB)</title></circle>`,
      `<circle cx="${mx.toFixed(1)}" cy="${toPxPhaseY(m.phase_deg).toFixed(1)}" r="4" fill="${color}"><title>${escapeHtml(m.label)} (∠G=${formatNumericDisplay(m.phase_deg, decimals)}°)</title></circle>`,
    );
  }

  let datatipSvg = "";
  const selIdx = options?.selectedSampleIndex;
  if (
    typeof selIdx === "number" &&
    Number.isInteger(selIdx) &&
    selIdx >= 0 &&
    selIdx < model.omega.length &&
    selIdx < model.mag_db.length &&
    selIdx < model.phase_deg.length
  ) {
    const w = model.omega[selIdx];
    const mag = model.mag_db[selIdx];
    const phase = model.phase_deg[selIdx];
    if (Number.isFinite(w) && w > 0 && Number.isFinite(mag) && Number.isFinite(phase)) {
      const dx = toPxX(w);
      const dMagY = toPxMagY(mag);
      const dPhaseY = toPxPhaseY(phase);
      datatipSvg = [
        `<g data-layer="datatip" data-sample-index="${selIdx}">`,
        `<line x1="${dx.toFixed(1)}" y1="${magTop}" x2="${dx.toFixed(1)}" y2="${phaseTop + subH}" stroke="${theme.focusRing}" stroke-dasharray="3 2" stroke-width="1.5" />`,
        `<circle cx="${dx.toFixed(1)}" cy="${dMagY.toFixed(1)}" r="5" fill="${theme.chartClosedLoop}" stroke="${theme.surface}" stroke-width="1.5"><title>ω=${formatNumericDisplay(w, decimals)} rad/s | Mag=${formatNumericDisplay(mag, decimals)} dB</title></circle>`,
        `<circle cx="${dx.toFixed(1)}" cy="${dPhaseY.toFixed(1)}" r="5" fill="${theme.chartOpenLoop}" stroke="${theme.surface}" stroke-width="1.5"><title>ω=${formatNumericDisplay(w, decimals)} rad/s | Fase=${formatNumericDisplay(phase, decimals)}°</title></circle>`,
        `</g>`,
      ].join("");
    }
  }

  const minDecade = Math.floor(logMinW);
  const maxDecade = Math.ceil(logMaxW);
  const freqGridLines: string[] = [];
  for (let d = minDecade; d <= maxDecade; d += 1) {
    const wVal = 10 ** d;
    if (wVal >= minW && wVal <= maxW) {
      const gx = toPxX(wVal);
      freqGridLines.push(
        `<line x1="${gx.toFixed(1)}" y1="${magTop}" x2="${gx.toFixed(1)}" y2="${phaseTop + subH}" stroke="${theme.chartGrid}" stroke-dasharray="2 3" stroke-width="0.8" />`,
        `<text x="${gx.toFixed(1)}" y="${phaseTop + subH + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">10<tspan dy="-4" font-size="8">${d}</tspan></text>`,
      );
    }
  }

  const desc = `Diagrama de Bode de ${model.title}. Faixa de frequência: ${minW.toExponential(2)} a ${maxW.toExponential(2)} rad/s. ${model.markers.length} marcadores de cruzamento. Atraso: ${model.delay_representation}.`;

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(model.title)}" class="scientific-chart-svg bode-chart" viewBox="0 0 ${widthPx} ${heightPx}" width="${widthPx}" height="${heightPx}" data-chart-id="${escapeHtml(model.chart_id)}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(desc)}</desc>`,
    `<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="${theme.surface}" />`,
    `<rect x="${padLeft}" y="${magTop}" width="${plotW}" height="${subH}" fill="none" stroke="${theme.chartGrid}" stroke-width="1" />`,
    `<rect x="${padLeft}" y="${phaseTop}" width="${plotW}" height="${subH}" fill="none" stroke="${theme.chartGrid}" stroke-width="1" />`,
    ...freqGridLines,
    zeroDbLine,
    minus180Line,
    `<polyline fill="none" stroke="${theme.chartClosedLoop}" stroke-width="2" points="${magPts.join(" ")}" data-layer="mag_db" />`,
    `<polyline fill="none" stroke="${theme.chartOpenLoop}" stroke-width="2" points="${phasePts.join(" ")}" data-layer="phase_deg" />`,
    ...markerSvgs,
    datatipSvg,
    `<text x="${padLeft}" y="20" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(formatChartHeadingTitle(model.title, model.series_semantics))}</text>`,
    `<text x="16" y="${magTop + subH / 2}" transform="rotate(-90 16 ${magTop + subH / 2})" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">Mag [dB]</text>`,
    `<text x="16" y="${phaseTop + subH / 2}" transform="rotate(-90 16 ${phaseTop + subH / 2})" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">Fase [°]</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(1)}" y="${heightPx - 10}" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">Frequência ω [rad/s] (escala logarítmica)</text>`,
    `</svg>`,
  ].join("");
}

function computeCenteredDiscreteBounds(
  allRe: readonly number[],
  allIm: readonly number[],
  plotW: number,
  plotH: number,
): { xBounds: AxisBounds; yBounds: AxisBounds } {
  let maxAbs = 1.25;
  for (const v of allRe) {
    if (Number.isFinite(v) && Math.abs(v) > 1.15) {
      maxAbs = Math.max(maxAbs, Math.abs(v) * 1.12);
    }
  }
  for (const v of allIm) {
    if (Number.isFinite(v) && Math.abs(v) > 1.15) {
      maxAbs = Math.max(maxAbs, Math.abs(v) * 1.12);
    }
  }
  const safeW = Math.max(1, plotW);
  const safeH = Math.max(1, plotH);
  let xHalf: number;
  let yHalf: number;
  if (safeW >= safeH) {
    yHalf = maxAbs;
    xHalf = maxAbs * (safeW / safeH);
  } else {
    xHalf = maxAbs;
    yHalf = maxAbs * (safeH / safeW);
  }
  return {
    xBounds: { min: -xHalf, max: xHalf, span: 2 * xHalf, isConstant: false },
    yBounds: { min: -yHalf, max: yHalf, span: 2 * yHalf, isConstant: false },
  };
}

function normalizeOverlayForDomain(
  ov: RequirementOverlay,
  dt: number | null,
): RequirementOverlay {
  if (
    dt !== null &&
    Number.isFinite(dt) &&
    dt > 0 &&
    ov.domain !== "discrete" &&
    (ov.kind === "second_order_damping" ||
      ov.kind === "second_order_natural_freq" ||
      ov.kind === "second_order_settling_time" ||
      ov.kind === "second_order_overshoot")
  ) {
    const cls = ov.classification === "estimated" ? "estimated" : "heuristic";
    return createSecondOrderRegionOverlay({
      id: ov.id,
      zetaMin: ov.parameters.zeta_min,
      wnMin: ov.kind === "second_order_natural_freq" ? ov.parameters.wn_min : undefined,
      maxOvershootPct: ov.parameters.max_overshoot_pct,
      maxSettlingTimeS: ov.parameters.max_settling_time_s,
      dt,
      classification: cls,
    });
  }
  return ov;
}

function computeNyquistGeometry(
  model: NyquistChartModel,
  options?: { widthPx?: number; heightPx?: number },
) {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 400;
  const padLeft = 64;
  const padRight = 24;
  const padTop = 36;
  const padBottom = 48;
  const plotW = widthPx - padLeft - padRight;
  const plotH = heightPx - padTop - padBottom;

  const allRe = [-1, 0, 1, ...model.re.filter(Number.isFinite)];
  const allIm = [-1, 0, 1, ...model.im.filter(Number.isFinite)];
  const xBounds = computeSafeAxisBounds(allRe, 0.15);
  const yBounds = computeSafeAxisBounds(allIm, 0.15);

  const toPxX = (r: number) =>
    padLeft + ((r - xBounds.min) / Math.max(1e-4, xBounds.span)) * plotW;
  const toPxY = (i: number) =>
    padTop + ((yBounds.max - i) / Math.max(1e-4, yBounds.span)) * plotH;

  return {
    widthPx,
    heightPx,
    padLeft,
    padRight,
    padTop,
    padBottom,
    plotW,
    plotH,
    xBounds,
    yBounds,
    toPxX,
    toPxY,
  };
}

export function inspectNyquistAtSvgPoint(
  model: NyquistChartModel,
  svgX: number,
  svgY: number,
  options?: { widthPx?: number; heightPx?: number },
): NyquistDatatipInspection | null {
  if (!Number.isFinite(svgX) || !Number.isFinite(svgY)) return null;
  const count = Math.min(model.omega.length, model.re.length, model.im.length);
  if (count === 0) return null;

  const geom = computeNyquistGeometry(model, options);
  let bestIdx = -1;
  let bestDist2 = Number.POSITIVE_INFINITY;
  let bestPxX = 0;
  let bestPxY = 0;

  for (let i = 0; i < count; i += 1) {
    const r = model.re[i];
    const im = model.im[i];
    const w = model.omega[i];
    if (!Number.isFinite(r) || !Number.isFinite(im) || !Number.isFinite(w)) continue;
    const pxX = geom.toPxX(r);
    const pxY = geom.toPxY(im);
    const d2 = (pxX - svgX) ** 2 + (pxY - svgY) ** 2;
    if (d2 < bestDist2) {
      bestDist2 = d2;
      bestIdx = i;
      bestPxX = pxX;
      bestPxY = pxY;
    }
  }

  if (bestIdx < 0) return null;
  const bestRe = model.re[bestIdx];
  const bestIm = model.im[bestIdx];
  const distToMinusOne = Math.hypot(bestRe + 1, bestIm);
  const sensitivityMag =
    distToMinusOne > 1e-12 ? 1 / distToMinusOne : Number.POSITIVE_INFINITY;
  return {
    sampleIndex: bestIdx,
    omega: model.omega[bestIdx],
    re: bestRe,
    im: bestIm,
    pxX: bestPxX,
    pxY: bestPxY,
    distance_to_minus_one: distToMinusOne,
    sensitivity_mag: sensitivityMag,
  };
}

export function renderNyquistSvg(
  model: NyquistChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    selectedSampleIndex?: number | null;
    themeMode?: AccessibilityThemeMode;
    margins?: NyquistStabilityMarginsMetadata | null;
  },
): string {
  const decimals = options?.decimals ?? 3;
  const theme = getThemeTokens(options?.themeMode ?? model.theme_mode ?? "standard_aa");
  const geom = computeNyquistGeometry(model, options);
  const { widthPx, heightPx, padLeft, padTop, plotW, plotH, toPxX, toPxY } = geom;

  const pts: string[] = [];
  const n = Math.min(model.re.length, model.im.length);
  for (let i = 0; i < n; i += 1) {
    if (Number.isFinite(model.re[i]) && Number.isFinite(model.im[i])) {
      pts.push(`${toPxX(model.re[i]).toFixed(1)},${toPxY(model.im[i]).toFixed(1)}`);
    }
  }

  const critX = toPxX(-1);
  const critY = toPxY(0);
  const zeroX = toPxX(0);
  const zeroY = toPxY(0);

  // 1. Círculo unitário |L(jω)| = 1
  const unitRx = Math.abs(toPxX(1) - zeroX);
  const unitRy = Math.abs(toPxY(1) - zeroY);
  const unitCircleSvg = `<ellipse cx="${zeroX.toFixed(2)}" cy="${zeroY.toFixed(2)}" rx="${unitRx.toFixed(2)}" ry="${unitRy.toFixed(2)}" fill="none" stroke="${theme.chartAxis}" stroke-dasharray="4 4" stroke-width="1.2" opacity="0.65" data-nyquist-annotation="unit-circle" aria-label="Círculo unitário |L(jω)| = 1"><title>Círculo unitário |L(jω)| = 1</title></ellipse>`;

  // 2. Anotações visuais de Margem de Fase (MF) e Margem de Ganho (MG)
  const margins = options?.margins ?? model.margins ?? null;
  let phaseMarginSvg = "";
  let gainMarginSvg = "";

  if (margins) {
    const pmDeg = margins.phase_margin_deg;
    if (typeof pmDeg === "number" && Number.isFinite(pmDeg)) {
      const pmRad = (pmDeg * Math.PI) / 180;
      const phiGcRad = -Math.PI + pmRad;
      const gcRe = Math.cos(phiGcRad);
      const gcIm = Math.sin(phiGcRad);
      const gcPxX = toPxX(gcRe);
      const gcPxY = toPxY(gcIm);

      const arcSteps = 24;
      const arcCmds: string[] = [];
      for (let i = 0; i <= arcSteps; i += 1) {
        const theta = -Math.PI + (pmRad * i) / arcSteps;
        const ax = toPxX(Math.cos(theta));
        const ay = toPxY(Math.sin(theta));
        arcCmds.push(`${i === 0 ? "M" : "L"} ${ax.toFixed(2)} ${ay.toFixed(2)}`);
      }
      const midTheta = -Math.PI + pmRad / 2;
      const lblX = toPxX(1.14 * Math.cos(midTheta));
      const lblY = toPxY(1.14 * Math.sin(midTheta));
      const pmLabel = `MF = ${formatNumericDisplay(pmDeg, Math.min(decimals, 1))}°`;
      const wgcInfo =
        typeof margins.w_gc === "number" && Number.isFinite(margins.w_gc)
          ? ` (ω_gc = ${formatNumericDisplay(margins.w_gc, decimals)} rad/s)`
          : "";

      phaseMarginSvg = [
        `<g data-nyquist-annotation="phase-margin">`,
        `<path d="${arcCmds.join(" ")}" fill="none" stroke="${theme.chartOverlayExact}" stroke-width="2.4"><title>${escapeHtml(pmLabel + wgcInfo)}</title></path>`,
        `<line x1="${zeroX.toFixed(1)}" y1="${zeroY.toFixed(1)}" x2="${gcPxX.toFixed(1)}" y2="${gcPxY.toFixed(1)}" stroke="${theme.chartOverlayExact}" stroke-dasharray="3 2" stroke-width="1.2" opacity="0.85" />`,
        `<circle cx="${gcPxX.toFixed(1)}" cy="${gcPxY.toFixed(1)}" r="4.5" fill="${theme.chartOverlayExact}" stroke="${theme.surface}" stroke-width="1.5"><title>Cruzamento de ganho |L(jω_gc)| = 1 | ${escapeHtml(pmLabel + wgcInfo)}</title></circle>`,
        `<text x="${lblX.toFixed(1)}" y="${lblY.toFixed(1)}" font-size="10.5" font-weight="bold" fill="${theme.chartOverlayExact}" text-anchor="middle">${escapeHtml(pmLabel)}</text>`,
        `</g>`,
      ].join("");
    }

    let kGm: number | null = null;
    if (
      typeof margins.gain_margin === "number" &&
      Number.isFinite(margins.gain_margin) &&
      margins.gain_margin > 1e-6
    ) {
      kGm = margins.gain_margin;
    } else if (
      typeof margins.gain_margin_db === "number" &&
      Number.isFinite(margins.gain_margin_db)
    ) {
      const lin = 10 ** (margins.gain_margin_db / 20);
      if (Number.isFinite(lin) && lin > 1e-6) {
        kGm = lin;
      }
    }

    if (kGm !== null) {
      const gmDb =
        typeof margins.gain_margin_db === "number" && Number.isFinite(margins.gain_margin_db)
          ? margins.gain_margin_db
          : 20 * Math.log10(kGm);
      const pcRe = -1 / kGm;
      const pcPxX = toPxX(pcRe);
      const pcPxY = toPxY(0);
      const midX = (pcPxX + critX) / 2;
      const gmLabel = `MG = ${formatNumericDisplay(gmDb, Math.min(decimals, 1))} dB (×${formatNumericDisplay(kGm, Math.min(decimals, 2))})`;
      const wpcInfo =
        typeof margins.w_pc === "number" && Number.isFinite(margins.w_pc)
          ? ` (ω_pc = ${formatNumericDisplay(margins.w_pc, decimals)} rad/s)`
          : "";

      gainMarginSvg = [
        `<g data-nyquist-annotation="gain-margin">`,
        `<line x1="${pcPxX.toFixed(1)}" y1="${pcPxY.toFixed(1)}" x2="${critX.toFixed(1)}" y2="${critY.toFixed(1)}" stroke="${theme.chartOpenLoop}" stroke-width="3"><title>${escapeHtml(gmLabel + wpcInfo)}</title></line>`,
        `<circle cx="${pcPxX.toFixed(1)}" cy="${pcPxY.toFixed(1)}" r="4.5" fill="${theme.chartOpenLoop}" stroke="${theme.surface}" stroke-width="1.5"><title>Cruzamento de fase (-1/K_gm, 0) | ${escapeHtml(gmLabel + wpcInfo)}</title></circle>`,
        `<text x="${midX.toFixed(1)}" y="${(pcPxY + 16).toFixed(1)}" font-size="10.5" font-weight="bold" fill="${theme.chartOpenLoop}" text-anchor="middle">${escapeHtml(gmLabel)}</text>`,
        `</g>`,
      ].join("");
    }
  }

  // 3. Datatip interativo com vetor de distância até (-1, j0)
  let datatipSvg = "";
  const selIdx = options?.selectedSampleIndex;
  if (
    typeof selIdx === "number" &&
    Number.isInteger(selIdx) &&
    selIdx >= 0 &&
    selIdx < model.re.length &&
    selIdx < model.im.length
  ) {
    const r = model.re[selIdx];
    const im = model.im[selIdx];
    const w = model.omega[selIdx] ?? 0;
    if (Number.isFinite(r) && Number.isFinite(im)) {
      const dx = toPxX(r);
      const dy = toPxY(im);
      const dist = Math.hypot(r + 1, im);
      const sens = dist > 1e-12 ? 1 / dist : Number.POSITIVE_INFINITY;
      const midX = (critX + dx) / 2;
      const midY = (critY + dy) / 2 - 7;
      const distLabel = `d = ${formatNumericDisplay(dist, decimals)}`;
      const sensStr = Number.isFinite(sens) ? formatNumericDisplay(sens, decimals) : "∞";
      datatipSvg = [
        `<g data-layer="datatip" data-sample-index="${selIdx}">`,
        `<g data-nyquist-annotation="distance-vector" data-distance="${dist.toFixed(6)}" data-sensitivity="${Number.isFinite(sens) ? sens.toFixed(6) : "Infinity"}">`,
        `<line x1="${critX.toFixed(1)}" y1="${critY.toFixed(1)}" x2="${dx.toFixed(1)}" y2="${dy.toFixed(1)}" stroke="${theme.accent}" stroke-width="2" stroke-dasharray="5 3"><title>Distância até (-1, j0): d = ${escapeHtml(formatNumericDisplay(dist, decimals))} | |S(jω)| = ${escapeHtml(sensStr)}</title></line>`,
        `<text x="${midX.toFixed(1)}" y="${midY.toFixed(1)}" font-size="10.5" font-weight="bold" fill="${theme.accent}" text-anchor="middle">${escapeHtml(distLabel)}</text>`,
        `</g>`,
        `<circle cx="${dx.toFixed(1)}" cy="${dy.toFixed(1)}" r="5.5" fill="${theme.accent}" stroke="${theme.surface}" stroke-width="2"><title>ω=${formatNumericDisplay(w, decimals)} rad/s | L(jω)=${formatNumericDisplay(r, decimals)} ${im >= 0 ? "+" : "-"} j${formatNumericDisplay(Math.abs(im), decimals)} | d=${formatNumericDisplay(dist, decimals)} | |S|=${sensStr}</title></circle>`,
        `</g>`,
      ].join("");
    }
  }

  const desc = `Diagrama de Nyquist de ${model.title}. Círculo unitário |L(jω)|=1 e ponto crítico (-1, j0) destacados. Atraso: ${model.delay_representation}.`;

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(model.title)}" class="scientific-chart-svg nyquist-chart" viewBox="0 0 ${widthPx} ${heightPx}" width="${widthPx}" height="${heightPx}" data-chart-id="${escapeHtml(model.chart_id)}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(desc)}</desc>`,
    `<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="${theme.surface}" />`,
    `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="none" stroke="${theme.chartGrid}" stroke-width="1" />`,
    `<line x1="${padLeft}" y1="${zeroY.toFixed(1)}" x2="${padLeft + plotW}" y2="${zeroY.toFixed(1)}" stroke="${theme.chartGrid}" stroke-width="1" />`,
    `<line x1="${zeroX.toFixed(1)}" y1="${padTop}" x2="${zeroX.toFixed(1)}" y2="${padTop + plotH}" stroke="${theme.chartGrid}" stroke-width="1" />`,
    unitCircleSvg,
    `<polyline fill="none" stroke="${theme.chartClosedLoop}" stroke-width="2" points="${pts.join(" ")}" data-layer="nyquist-curve" />`,
    phaseMarginSvg,
    gainMarginSvg,
    `<g data-critical-point="minus-one">`,
    `<circle cx="${critX.toFixed(1)}" cy="${critY.toFixed(1)}" r="5" fill="${theme.chartOverlayHeuristic}" stroke="#fff" stroke-width="1.5" />`,
    `<text x="${(critX - 6).toFixed(1)}" y="${(critY - 8).toFixed(1)}" font-size="11" font-weight="bold" fill="${theme.chartOverlayHeuristic}" text-anchor="end">(-1, j0)</text>`,
    `</g>`,
    datatipSvg,
    `<text x="${padLeft}" y="20" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(formatChartHeadingTitle(model.title, model.series_semantics))}</text>`,
    `<text x="16" y="${(padTop + plotH / 2).toFixed(1)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(1)})" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">Im G(jω)</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(1)}" y="${heightPx - 10}" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">Re G(jω)</text>`,
    `</svg>`,
  ].join("");
}

function computeRootLocusGeometry(
  model: RootLocusChartModel,
  options?: { widthPx?: number; heightPx?: number },
) {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 420;
  const padLeft = 64;
  const padRight = 24;
  const padTop = 36;
  const padBottom = 48;
  const plotW = widthPx - padLeft - padRight;
  const plotH = heightPx - padTop - padBottom;

  const allRe: number[] = [0];
  const allIm: number[] = [0];
  if (model.open_loop_poles) {
    allRe.push(...model.open_loop_poles.real);
    allIm.push(...model.open_loop_poles.imag);
  }
  if (model.open_loop_zeros) {
    allRe.push(...model.open_loop_zeros.real);
    allIm.push(...model.open_loop_zeros.imag);
  }
  for (const b of model.branches) {
    allRe.push(...b.real.filter(Number.isFinite));
    allIm.push(...b.imag.filter(Number.isFinite));
  }

  let xBounds: AxisBounds;
  let yBounds: AxisBounds;
  if (model.dt !== null) {
    const centered = computeCenteredDiscreteBounds(allRe, allIm, plotW, plotH);
    xBounds = centered.xBounds;
    yBounds = centered.yBounds;
  } else {
    xBounds = computeSafeAxisBounds(allRe, 0.15);
    yBounds = computeSafeAxisBounds(allIm, 0.15);
  }

  const vp: ChartViewport = {
    widthPx,
    heightPx,
    padLeftPx: padLeft,
    padRightPx: padRight,
    padTopPx: padTop,
    padBottomPx: padBottom,
    xMin: xBounds.min,
    xMax: xBounds.max,
    yMin: yBounds.min,
    yMax: yBounds.max,
  };

  const toPxX = (r: number) =>
    padLeft + ((r - xBounds.min) / Math.max(1e-4, xBounds.span)) * plotW;
  const toPxY = (i: number) =>
    padTop + ((yBounds.max - i) / Math.max(1e-4, yBounds.span)) * plotH;

  return {
    widthPx,
    heightPx,
    padLeft,
    padRight,
    padTop,
    padBottom,
    plotW,
    plotH,
    vp,
    toPxX,
    toPxY,
  };
}

export function inspectRootLocusAtSvgPoint(
  model: RootLocusChartModel,
  svgX: number,
  svgY: number,
  options?: { widthPx?: number; heightPx?: number },
): RootLocusDatatipInspection | null {
  if (!Number.isFinite(svgX) || !Number.isFinite(svgY)) return null;
  if (model.gains.length === 0 || model.branches.length === 0) return null;

  const geom = computeRootLocusGeometry(model, options);
  let bestBranchIdx = -1;
  let bestGainIdx = -1;
  let bestDist2 = Number.POSITIVE_INFINITY;

  for (let bIdx = 0; bIdx < model.branches.length; bIdx += 1) {
    const b = model.branches[bIdx];
    const nSteps = Math.min(model.gains.length, b.real.length, b.imag.length);
    for (let kIdx = 0; kIdx < nSteps; kIdx += 1) {
      const re = b.real[kIdx];
      const im = b.imag[kIdx];
      const kVal = model.gains[kIdx];
      if (!Number.isFinite(re) || !Number.isFinite(im) || !Number.isFinite(kVal)) continue;
      const pxX = geom.toPxX(re);
      const pxY = geom.toPxY(im);
      const d2 = (pxX - svgX) ** 2 + (pxY - svgY) ** 2;
      if (d2 < bestDist2) {
        bestDist2 = d2;
        bestBranchIdx = bIdx;
        bestGainIdx = kIdx;
      }
    }
  }

  if (bestGainIdx < 0 || bestBranchIdx < 0) return null;

  const poles: RootLocusFrozenPole[] = [];
  for (let bIdx = 0; bIdx < model.branches.length; bIdx += 1) {
    const b = model.branches[bIdx];
    if (bestGainIdx < b.real.length && bestGainIdx < b.imag.length) {
      const re = b.real[bestGainIdx];
      const im = b.imag[bestGainIdx];
      if (Number.isFinite(re) && Number.isFinite(im)) {
        poles.push({
          branchIndex: bIdx,
          real: re,
          imag: im,
          pxX: geom.toPxX(re),
          pxY: geom.toPxY(im),
        });
      }
    }
  }

  return {
    gainIndex: bestGainIdx,
    branchIndex: bestBranchIdx,
    gain_K: model.gains[bestGainIdx],
    poles,
  };
}

export function renderRootLocusSvg(
  model: RootLocusChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    frozenGainIndex?: number | null;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const decimals = options?.decimals ?? 3;
  const theme = getThemeTokens(options?.themeMode ?? model.theme_mode ?? "standard_aa");
  const geom = computeRootLocusGeometry(model, options);
  const { widthPx, heightPx, padLeft, padTop, plotW, plotH, vp, toPxX, toPxY } = geom;

  const branchPolylines = model.branches.map((b, idx) => {
    const pts: string[] = [];
    const bn = Math.min(b.real.length, b.imag.length);
    for (let k = 0; k < bn; k += 1) {
      if (Number.isFinite(b.real[k]) && Number.isFinite(b.imag[k])) {
        pts.push(`${toPxX(b.real[k]).toFixed(1)},${toPxY(b.imag[k]).toFixed(1)}`);
      }
    }
    return `<polyline fill="none" stroke="${theme.chartClosedLoop}" stroke-width="1.8" points="${pts.join(" ")}" data-branch-index="${idx}"><title>Ramo ${idx + 1}</title></polyline>`;
  });

  const poleSvgs: string[] = [];
  if (model.open_loop_poles) {
    const pn = Math.min(model.open_loop_poles.real.length, model.open_loop_poles.imag.length);
    for (let i = 0; i < pn; i += 1) {
      const px = toPxX(model.open_loop_poles.real[i]);
      const py = toPxY(model.open_loop_poles.imag[i]);
      poleSvgs.push(
        `<g data-pole-index="${i}"><line x1="${(px - 5).toFixed(1)}" y1="${(py - 5).toFixed(1)}" x2="${(px + 5).toFixed(1)}" y2="${(py + 5).toFixed(1)}" stroke="${theme.chartOpenLoop}" stroke-width="2" /><line x1="${(px - 5).toFixed(1)}" y1="${(py + 5).toFixed(1)}" x2="${(px + 5).toFixed(1)}" y2="${(py - 5).toFixed(1)}" stroke="${theme.chartOpenLoop}" stroke-width="2" /><title>Polo malha aberta: ${formatNumericDisplay(model.open_loop_poles.real[i], decimals)} + j${formatNumericDisplay(model.open_loop_poles.imag[i], decimals)}</title></g>`,
      );
    }
  }

  const zeroSvgs: string[] = [];
  if (model.open_loop_zeros) {
    const zn = Math.min(model.open_loop_zeros.real.length, model.open_loop_zeros.imag.length);
    for (let i = 0; i < zn; i += 1) {
      const zx = toPxX(model.open_loop_zeros.real[i]);
      const zy = toPxY(model.open_loop_zeros.imag[i]);
      zeroSvgs.push(
        `<circle cx="${zx.toFixed(1)}" cy="${zy.toFixed(1)}" r="5" fill="none" stroke="${theme.chartOpenLoop}" stroke-width="2"><title>Zero malha aberta: ${formatNumericDisplay(model.open_loop_zeros.real[i], decimals)} + j${formatNumericDisplay(model.open_loop_zeros.imag[i], decimals)}</title></circle>`,
      );
    }
  }

  const overlaysSvg = model.overlays
    .map((rawOv) => {
      const ov = normalizeOverlayForDomain(rawOv, model.dt);
      const g = generateOverlaySvgPath(ov, vp);
      const col =
        ov.classification === "exact"
          ? theme.chartOverlayExact
          : ov.classification === "sufficient"
            ? theme.chartOverlaySufficient
            : theme.chartOverlayHeuristic;
      return `<path d="${g.pathD}" fill="none" stroke="${col}" stroke-width="1.8" stroke-dasharray="${g.strokeDasharray}" data-overlay-id="${escapeHtml(ov.id)}" data-overlay-class="${escapeHtml(ov.classification)}"><title>${escapeHtml(g.ariaDescription)} [${escapeHtml(ov.classification)}]</title></path>`;
    })
    .join("");

  let frozenDatatipSvg = "";
  const frozenIdx = options?.frozenGainIndex;
  if (
    typeof frozenIdx === "number" &&
    Number.isInteger(frozenIdx) &&
    frozenIdx >= 0 &&
    frozenIdx < model.gains.length
  ) {
    const kVal = model.gains[frozenIdx];
    const frozenMarkers: string[] = [];
    for (let bIdx = 0; bIdx < model.branches.length; bIdx += 1) {
      const br = model.branches[bIdx];
      if (frozenIdx < br.real.length && frozenIdx < br.imag.length) {
        const re = br.real[frozenIdx];
        const im = br.imag[frozenIdx];
        if (Number.isFinite(re) && Number.isFinite(im)) {
          const px = toPxX(re);
          const py = toPxY(im);
          const imAbs = formatNumericDisplay(Math.abs(im), decimals);
          const imSign = im >= 0 ? "+" : "-";
          frozenMarkers.push(
            `<g data-frozen-pole-branch="${bIdx}">` +
              `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="7" fill="none" stroke="${theme.focusRing}" stroke-width="1.5" stroke-dasharray="2 2" />` +
              `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="4.5" fill="${theme.chartPreview}" stroke="${theme.surface}" stroke-width="1.5"><title>K=${formatNumericDisplay(kVal, decimals)} | Ramo ${bIdx + 1}: ${formatNumericDisplay(re, decimals)} ${imSign} j${imAbs}</title></circle>` +
              `</g>`,
          );
        }
      }
    }
    if (frozenMarkers.length > 0) {
      frozenDatatipSvg = `<g data-layer="datatip" data-frozen-gain-index="${frozenIdx}" data-gain-k="${escapeHtml(String(kVal))}"><g data-layer="frozen-poles-datatip">${frozenMarkers.join("")}</g></g>`;
    }
  }

  const zeroX = toPxX(0);
  const zeroY = toPxY(0);
  const isDiscrete = model.dt !== null;
  const unitCircleSvg = isDiscrete
    ? (() => {
        const rx = Math.abs(toPxX(1) - zeroX);
        const ry = Math.abs(toPxY(1) - zeroY);
        return `<ellipse cx="${zeroX.toFixed(4)}" cy="${zeroY.toFixed(4)}" rx="${rx.toFixed(4)}" ry="${ry.toFixed(4)}" fill="none" stroke="${theme.chartAxis}" stroke-dasharray="4 4" stroke-width="1.5" data-unit-circle="true" aria-label="Círculo unitário |z|=1"><title>Círculo unitário |z| = 1</title></ellipse>`;
      })()
    : "";
  const axisVar = isDiscrete ? "z" : "s";

  const desc = `Lugar das Raízes (Root Locus) de ${model.title}. ${model.branches.length} ramos.${isDiscrete ? " Plano-z discreto com círculo unitário |z|=1 centrado." : ""}`;

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(model.title)}" class="scientific-chart-svg root-locus-chart" viewBox="0 0 ${widthPx} ${heightPx}" width="${widthPx}" height="${heightPx}" data-chart-id="${escapeHtml(model.chart_id)}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(desc)}</desc>`,
    `<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="${theme.surface}" />`,
    `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="none" stroke="${theme.chartGrid}" stroke-width="1" />`,
    `<line x1="${padLeft}" y1="${zeroY.toFixed(1)}" x2="${padLeft + plotW}" y2="${zeroY.toFixed(1)}" stroke="${theme.chartGrid}" stroke-width="1" />`,
    `<line x1="${zeroX.toFixed(1)}" y1="${padTop}" x2="${zeroX.toFixed(1)}" y2="${padTop + plotH}" stroke="${theme.chartGrid}" stroke-width="1" />`,
    unitCircleSvg,
    overlaysSvg,
    ...branchPolylines,
    ...poleSvgs,
    ...zeroSvgs,
    frozenDatatipSvg,
    `<text x="${padLeft}" y="20" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(formatChartHeadingTitle(model.title, model.series_semantics))}</text>`,
    `<text x="16" y="${(padTop + plotH / 2).toFixed(1)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(1)})" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">Im(${axisVar})</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(1)}" y="${heightPx - 10}" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">Re(${axisVar})</text>`,
    `</svg>`,
  ].join("");
}


export function buildPoleZeroChartModel(input: {
  chart_id?: string;
  title?: string;
  dt: number | null;
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics: ResultVerificationIndicator;
  feedback_sign?: "negative" | "positive";
  open_loop_poles?: ComplexVectorPair | null;
  committed_closed_loop_poles?: ComplexVectorPair | null;
  preview_poles?: ComplexVectorPair | null;
  zeros?: ComplexVectorPair | null;
  overlays?: readonly RequirementOverlay[];
  theme_mode?: AccessibilityThemeMode;
}): PoleZeroChartModel {
  const unitLabel = input.dt === null ? "1/s" : "plano-z";
  return {
    kind: "pole_zero",
    chart_id: input.chart_id ?? "pole-zero-map",
    title: input.title ?? "Mapa de Polos e Zeros",
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics,
    feedback_sign: input.feedback_sign,
    units: {
      x_axis: `Re(λ) [${unitLabel}]`,
      y_axis: `Im(λ) [${unitLabel}]`,
    },
    theme_mode: input.theme_mode ?? "standard_aa",
    dt: input.dt,
    open_loop_poles: input.open_loop_poles
      ? {
          real: [...input.open_loop_poles.real],
          imag: [...input.open_loop_poles.imag],
        }
      : null,
    committed_closed_loop_poles: input.committed_closed_loop_poles
      ? {
          real: [...input.committed_closed_loop_poles.real],
          imag: [...input.committed_closed_loop_poles.imag],
        }
      : null,
    preview_poles: input.preview_poles
      ? {
          real: [...input.preview_poles.real],
          imag: [...input.preview_poles.imag],
        }
      : null,
    zeros: input.zeros
      ? { real: [...input.zeros.real], imag: [...input.zeros.imag] }
      : null,
    overlays: input.overlays ? [...input.overlays] : [],
  };
}

export function buildTimeResponseChartModel(input: {
  chart_id?: string;
  title?: string;
  dt: number | null;
  t: readonly number[];
  x?: readonly (readonly number[])[] | null;
  u?: readonly (readonly number[])[] | null;
  y?: readonly (readonly number[])[] | null;
  state_names?: readonly string[];
  input_names?: readonly string[];
  output_names?: readonly string[];
  units?: {
    time?: string;
    states?: readonly string[];
    inputs?: readonly string[];
    outputs?: readonly string[];
  };
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics: ResultVerificationIndicator;
  feedback_sign?: "negative" | "positive";
  preview_y?: readonly (readonly number[])[] | null;
  theme_mode?: AccessibilityThemeMode;
}): TimeResponseChartModel {
  const channels: TimeSeriesChannel[] = [];
  const previewChannels: TimeSeriesChannel[] = [];
  let seq = 0;

  const pushGroup = (
    group: "x" | "u" | "y",
    matrix: readonly (readonly number[])[] | null | undefined,
    names: readonly string[] | undefined,
    unitList: readonly string[] | undefined,
    semantics: ResultVerificationIndicator,
    target: TimeSeriesChannel[],
  ) => {
    if (!matrix || matrix.length === 0) return;
    const nChannels = matrix[0]?.length ?? 0;
    for (let ch = 0; ch < nChannels; ch += 1) {
      const vals = matrix.map((row) =>
        typeof row[ch] === "number" && Number.isFinite(row[ch]) ? row[ch] : 0,
      );
      const chName = names?.[ch] ?? `${group}${ch + 1}`;
      const chUnit = unitList?.[ch] ?? (group === "u" ? "u" : group === "y" ? "y" : "st");
      target.push({
        id: `${group}-${ch}-${semantics}`,
        group,
        label:
          semantics === "preview"
            ? `${chName} (Preview)`
            : `${group === "x" ? "Estado" : group === "u" ? "Entrada" : "Saída"} ${chName}`,
        unit: chUnit,
        values: vals,
        shape: SERIES_MARKER_SHAPES[seq % SERIES_MARKER_SHAPES.length],
        stroke_dasharray:
          semantics === "preview"
            ? "3 3"
            : SERIES_DASH_PATTERNS[seq % SERIES_DASH_PATTERNS.length],
        series_semantics: semantics,
      });
      seq += 1;
    }
  };

  pushGroup(
    "x",
    input.x,
    input.state_names,
    input.units?.states,
    input.series_semantics,
    channels,
  );
  pushGroup(
    "u",
    input.u,
    input.input_names,
    input.units?.inputs,
    input.series_semantics,
    channels,
  );
  pushGroup(
    "y",
    input.y,
    input.output_names,
    input.units?.outputs,
    input.series_semantics,
    channels,
  );
  pushGroup(
    "y",
    input.preview_y,
    input.output_names,
    input.units?.outputs,
    "preview",
    previewChannels,
  );

  const timeUnit = input.units?.time ?? "s";
  return {
    kind: "time_response",
    chart_id: input.chart_id ?? "time-response",
    title: input.title ?? "Resposta Temporal (x, u, y)",
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics,
    feedback_sign: input.feedback_sign,
    units: {
      x_axis: `Tempo [${timeUnit}]`,
      y_axis: "Amplitude",
      time: timeUnit,
      states: input.units?.states ? [...input.units.states] : undefined,
      inputs: input.units?.inputs ? [...input.units.inputs] : undefined,
      outputs: input.units?.outputs ? [...input.units.outputs] : undefined,
    },
    theme_mode: input.theme_mode ?? "standard_aa",
    dt: input.dt,
    t: [...input.t],
    channels,
    preview_channels: previewChannels,
  };
}

function renderMarkerSvg(
  shape: PointMarkerShape,
  cx: number,
  cy: number,
  size: number,
  color: string,
  label: string,
  extraAttrs = "",
): string {
  const safeLabel = escapeHtml(label);
  const x = cx.toFixed(2);
  const y = cy.toFixed(2);
  const r = size;
  switch (shape) {
    case "circle":
      return `<circle cx="${x}" cy="${y}" r="${r}" fill="${color}" stroke="${color}" stroke-width="1.5" aria-label="${safeLabel}" ${extraAttrs}><title>${safeLabel}</title></circle>`;
    case "cross": {
      const d = `M ${(cx - r).toFixed(2)} ${(cy - r).toFixed(2)} L ${(cx + r).toFixed(2)} ${(cy + r).toFixed(2)} M ${(cx - r).toFixed(2)} ${(cy + r).toFixed(2)} L ${(cx + r).toFixed(2)} ${(cy - r).toFixed(2)}`;
      return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" aria-label="${safeLabel}" ${extraAttrs}><title>${safeLabel}</title></path>`;
    }
    case "diamond": {
      const d = `M ${x} ${(cy - r * 1.2).toFixed(2)} L ${(cx + r * 1.2).toFixed(2)} ${y} L ${x} ${(cy + r * 1.2).toFixed(2)} L ${(cx - r * 1.2).toFixed(2)} ${y} Z`;
      return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="2 2" aria-label="${safeLabel}" ${extraAttrs}><title>${safeLabel}</title></path>`;
    }
    case "triangle": {
      const d = `M ${x} ${(cy - r * 1.2).toFixed(2)} L ${(cx + r * 1.1).toFixed(2)} ${(cy + r).toFixed(2)} L ${(cx - r * 1.1).toFixed(2)} ${(cy + r).toFixed(2)} Z`;
      return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" aria-label="${safeLabel}" ${extraAttrs}><title>${safeLabel}</title></path>`;
    }
    case "square": {
      return `<rect x="${(cx - r).toFixed(2)}" y="${(cy - r).toFixed(2)}" width="${(2 * r).toFixed(2)}" height="${(2 * r).toFixed(2)}" fill="none" stroke="${color}" stroke-width="2" aria-label="${safeLabel}" ${extraAttrs}><title>${safeLabel}</title></rect>`;
    }
  }
}

function mapCoord(
  val: number,
  min: number,
  span: number,
  pxStart: number,
  pxLen: number,
  invert = false,
): number {
  const norm = (val - min) / Math.max(1e-12, span);
  return invert ? pxStart + (1 - norm) * pxLen : pxStart + norm * pxLen;
}

export function classifyPoleStability(
  re: number,
  im: number,
  dt: number | null,
): {
  status: "stable" | "marginal" | "unstable";
  label: "Estável" | "Marginal / Borda" | "Instável";
  tag: " [ESTÁVEL]" | " [MARGINAL / BORDA]" | " [INSTÁVEL]";
} {
  if (dt === null) {
    if (re < -1e-12) {
      return { status: "stable", label: "Estável", tag: " [ESTÁVEL]" };
    }
    if (Math.abs(re) <= 1e-12) {
      return {
        status: "marginal",
        label: "Marginal / Borda",
        tag: " [MARGINAL / BORDA]",
      };
    }
    return { status: "unstable", label: "Instável", tag: " [INSTÁVEL]" };
  }
  const mag = Math.hypot(re, im);
  if (mag < 1 - 1e-12) {
    return { status: "stable", label: "Estável", tag: " [ESTÁVEL]" };
  }
  if (Math.abs(mag - 1) <= 1e-12) {
    return {
      status: "marginal",
      label: "Marginal / Borda",
      tag: " [MARGINAL / BORDA]",
    };
  }
  return { status: "unstable", label: "Instável", tag: " [INSTÁVEL]" };
}

export function renderPoleZeroSvg(
  model: PoleZeroChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 400;
  const decimals = options?.decimals ?? 3;
  const theme = getThemeTokens(options?.themeMode ?? model.theme_mode ?? "standard_aa");

  const allRe: number[] = [0];
  const allIm: number[] = [0];
  const collect = (pair: ComplexVectorPair | null) => {
    if (!pair) return;
    for (const v of pair.real) if (Number.isFinite(v)) allRe.push(v);
    for (const v of pair.imag) if (Number.isFinite(v)) allIm.push(v);
  };
  collect(model.open_loop_poles);
  collect(model.committed_closed_loop_poles);
  collect(model.preview_poles);
  collect(model.zeros);

  const padLeftPx = 64;
  const padRightPx = 24;
  const padTopPx = 40;
  const padBottomPx = 54;
  const plotW = widthPx - padLeftPx - padRightPx;
  const plotH = heightPx - padTopPx - padBottomPx;

  let xBounds: AxisBounds;
  let yBounds: AxisBounds;
  if (model.dt !== null) {
    const centered = computeCenteredDiscreteBounds(allRe, allIm, plotW, plotH);
    xBounds = centered.xBounds;
    yBounds = centered.yBounds;
  } else {
    xBounds = computeSafeAxisBounds(allRe, 0.15);
    yBounds = computeSafeAxisBounds(allIm, 0.15);
  }

  const vp: ChartViewport = {
    widthPx,
    heightPx,
    padLeftPx,
    padRightPx,
    padTopPx,
    padBottomPx,
    xMin: xBounds.min,
    xMax: xBounds.max,
    yMin: yBounds.min,
    yMax: yBounds.max,
  };

  const toPxX = (x: number) => mapCoord(x, vp.xMin, xBounds.span, vp.padLeftPx, plotW, false);
  const toPxY = (y: number) => mapCoord(y, vp.yMin, yBounds.span, vp.padTopPx, plotH, true);

  const xZeroPx = toPxX(0);
  const yZeroPx = toPxY(0);

  const overlayColor = (cls: OverlayConfidenceClass): string =>
    cls === "exact"
      ? theme.chartOverlayExact
      : cls === "sufficient"
        ? theme.chartOverlaySufficient
        : theme.chartOverlayHeuristic;

  const overlaysSvg = model.overlays
    .map((rawOv) => {
      const ov = normalizeOverlayForDomain(rawOv, model.dt);
      const g = generateOverlaySvgPath(ov, vp);
      const col = overlayColor(ov.classification);
      return `<path d="${g.pathD}" fill="none" stroke="${col}" stroke-width="2" stroke-dasharray="${g.strokeDasharray}" data-overlay-id="${escapeHtml(ov.id)}" data-overlay-class="${escapeHtml(ov.classification)}"><title>${escapeHtml(g.ariaDescription)}</title></path>`;
    })
    .join("");

  const renderPolesGroup = (
    pair: ComplexVectorPair | null,
    layer: string,
    shape: PointMarkerShape,
    color: string,
    prefixLabel: string,
    semantics: ResultVerificationIndicator,
  ): string => {
    if (!pair) return "";
    const count = Math.min(pair.real.length, pair.imag.length);
    const items: string[] = [];
    for (let i = 0; i < count; i += 1) {
      const re = pair.real[i];
      const im = pair.imag[i];
      const px = toPxX(re);
      const py = toPxY(im);
      const stab = classifyPoleStability(re, im, model.dt);
      const markerShape: PointMarkerShape =
        stab.status === "marginal"
          ? "diamond"
          : stab.status === "unstable"
            ? "cross"
            : shape;
      const label = `${prefixLabel} #${i + 1}: ${formatNumericDisplay(re, decimals)} ${im >= 0 ? "+" : "-"} ${formatNumericDisplay(Math.abs(im), decimals)}j${stab.tag}`;
      items.push(
        renderMarkerSvg(
          markerShape,
          px,
          py,
          5,
          color,
          label,
          `data-pole-index="${i}" data-stability="${stab.status}" data-unstable="${stab.status === "unstable" ? "true" : "false"}" data-marginal="${stab.status === "marginal" ? "true" : "false"}"`,
        ),
      );
    }
    return `<g data-layer="${escapeHtml(layer)}" data-series-semantics="${escapeHtml(semantics)}">${items.join("")}</g>`;
  };

  const unitCircleSvg =
    model.dt !== null
      ? (() => {
          const cx = toPxX(0);
          const cy = toPxY(0);
          const rx = Math.abs(toPxX(1) - cx);
          const ry = Math.abs(toPxY(1) - cy);
          return `<ellipse cx="${cx.toFixed(4)}" cy="${cy.toFixed(4)}" rx="${rx.toFixed(4)}" ry="${ry.toFixed(4)}" fill="none" stroke="${theme.chartAxis}" stroke-dasharray="4 4" stroke-width="1.5" data-unit-circle="true" aria-label="Círculo unitário |z|=1" />`;
        })()
      : "";

  const algText = model.provenance?.algorithm ?? "N/D";
  const signText =
    model.feedback_sign === "positive"
      ? "Sinal positivo (A+BK)"
      : model.feedback_sign === "negative"
        ? "Sinal negativo (A-BK)"
        : "Sem realimentação";

  const pzTicksX = [vp.xMin, (vp.xMin + vp.xMax) / 2, vp.xMax]
    .map((v) => {
      const px = toPxX(v).toFixed(2);
      const yBase = vp.heightPx - vp.padBottomPx;
      return `<line x1="${px}" y1="${yBase}" x2="${px}" y2="${yBase + 4}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${px}" y="${yBase + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(v, decimals))}</text>`;
    })
    .join("");
  const pzTicksY = [vp.yMin, (vp.yMin + vp.yMax) / 2, vp.yMax]
    .map((v) => {
      const py = toPxY(v).toFixed(2);
      return `<line x1="${vp.padLeftPx - 4}" y1="${py}" x2="${vp.padLeftPx}" y2="${py}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${vp.padLeftPx - 7}" y="${(Number(py) + 3).toFixed(2)}" text-anchor="end" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(v, decimals))}</text>`;
    })
    .join("");

  const pzLegendItems: string[] = [];
  if (model.open_loop_poles) {
    pzLegendItems.push(
      `<text x="${vp.padLeftPx + 8}" y="${vp.padTopPx + 14}" font-size="10" fill="${theme.chartOpenLoop}">× Malha Aberta</text>`,
    );
  }
  if (model.committed_closed_loop_poles) {
    pzLegendItems.push(
      `<text x="${vp.padLeftPx + 108}" y="${vp.padTopPx + 14}" font-size="10" fill="${theme.chartClosedLoop}">● Confirmado</text>`,
    );
  }
  if (model.preview_poles) {
    pzLegendItems.push(
      `<text x="${vp.padLeftPx + 208}" y="${vp.padTopPx + 14}" font-size="10" fill="${theme.chartPreview}">◆ Fast-Preview</text>`,
    );
  }

  const ariaSummary = `${model.title}; semântica: ${model.series_semantics}; revisão modelo: ${String(model.model_revision)}; revisão projeto: ${String(model.project_revision)}; algoritmo: ${algText}; ${signText}.`;

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${widthPx} ${heightPx}" role="img" aria-label="${escapeHtml(ariaSummary)}" style="background:${theme.surface};color:${theme.textPrimary}" data-chart-kind="pole_zero" data-series-semantics="${escapeHtml(model.series_semantics)}" data-model-revision="${escapeHtml(String(model.model_revision))}" data-project-revision="${escapeHtml(String(model.project_revision))}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(ariaSummary)}</desc>`,
    `<rect x="${vp.padLeftPx}" y="${vp.padTopPx}" width="${plotW}" height="${plotH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
    `<line x1="${vp.padLeftPx}" y1="${yZeroPx.toFixed(2)}" x2="${vp.widthPx - vp.padRightPx}" y2="${yZeroPx.toFixed(2)}" stroke="${theme.chartGrid}" stroke-width="1" />`,
    `<line x1="${xZeroPx.toFixed(2)}" y1="${vp.padTopPx}" x2="${xZeroPx.toFixed(2)}" y2="${vp.heightPx - vp.padBottomPx}" stroke="${theme.chartAxis}" stroke-dasharray="5 3" stroke-width="1.2" />`,
    unitCircleSvg,
    `<g class="axis-ticks" data-layer="axis-ticks">${pzTicksX}${pzTicksY}</g>`,
    `<g data-layer="overlays">${overlaysSvg}</g>`,
    renderPolesGroup(
      model.open_loop_poles,
      "open-loop",
      "cross",
      theme.chartOpenLoop,
      "Polo Malha Aberta",
      "numeric_verified",
    ),
    renderPolesGroup(
      model.committed_closed_loop_poles,
      "committed",
      "circle",
      theme.chartClosedLoop,
      "Polo Malha Fechada (Confirmado)",
      model.series_semantics,
    ),
    renderPolesGroup(
      model.preview_poles,
      "fast-preview",
      "diamond",
      theme.chartPreview,
      "Polo Fast-Preview (Transitório)",
      "preview",
    ),
    `<g class="chart-legend" data-layer="legend">${pzLegendItems.join("")}</g>`,
    `<text x="${vp.padLeftPx}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(formatChartHeadingTitle(model.title, model.series_semantics))}</text>`,
    `<text x="${(vp.padLeftPx + plotW / 2).toFixed(2)}" y="${heightPx - 10}" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.x_axis)} | ${escapeHtml(signText)}</text>`,
    `<text x="16" y="${(vp.padTopPx + plotH / 2).toFixed(2)}" transform="rotate(-90 16 ${(vp.padTopPx + plotH / 2).toFixed(2)})" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.y_axis)}</text>`,
    `</svg>`,
  ].join("");
}

export function renderIdentificationFourPanelSvg(
  model: TimeResponseChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const widthPx = options?.widthPx ?? 760;
  const heightPx = options?.heightPx ?? 560;
  const decimals = options?.decimals ?? 3;
  const effectiveThemeMode = options?.themeMode ?? model.theme_mode ?? "standard_aa";
  const theme = getThemeTokens(effectiveThemeMode);
  const isHc = effectiveThemeMode === "high_contrast";

  const xBounds = computeSafeAxisBounds(model.t, 0.02);

  const uChan = model.channels.find((ch) => ch.id.startsWith("u-input-"));
  const yMeasChan = model.channels.find((ch) => ch.id.startsWith("y-measured-"));
  const yOneStepChan = model.channels.find((ch) => ch.id.startsWith("y-hat-one-step-"));
  const yFreeSimChan = model.channels.find((ch) => ch.id.startsWith("y-hat-free-sim-"));
  const resOneStepChan = model.channels.find((ch) => ch.id.startsWith("residuals-one-step-"));
  const resFreeSimChan = model.channels.find((ch) => ch.id.startsWith("residuals-free-sim-"));

  const colInput = isHc ? "#38BDF8" : "#0284C7";
  const colMeasured = theme.textPrimary;
  const colOneStep = isHc ? "#4ADE80" : "#059669";
  const colFreeSim = isHc ? "#38BDF8" : "#1D4ED8";
  const colResOneStep = isHc ? "#F472B6" : "#9333EA";
  const colResFreeSim = isHc ? "#FBBF24" : "#D97706";

  interface SubplotSpec {
    subplotId: "input" | "one-step" | "free-sim" | "residuals";
    title: string;
    colIdx: number;
    rowIdx: number;
    yUnit: string;
    includeZeroRef: boolean;
    series: Array<{
      channel: TimeSeriesChannel;
      color: string;
      dash: string;
      strokeWidth: string;
      legendSymbol: string;
    }>;
  }

  const outUnit = model.units.outputs?.[0] ?? "y";
  const inUnit = model.units.inputs?.[0] ?? "u";

  const specs: SubplotSpec[] = [
    {
      subplotId: "input",
      title: `1. Entrada u(k) [${inUnit}]`,
      colIdx: 0,
      rowIdx: 0,
      yUnit: inUnit,
      includeZeroRef: true,
      series: uChan
        ? [
            {
              channel: uChan,
              color: colInput,
              dash: "",
              strokeWidth: "1.8",
              legendSymbol: "—",
            },
          ]
        : [],
    },
    {
      subplotId: "one-step",
      title: `2. Previsão 1-Passo (ŷ_1p) vs. Saída Medida (y) [${outUnit}]`,
      colIdx: 1,
      rowIdx: 0,
      yUnit: outUnit,
      includeZeroRef: false,
      series: [
        ...(yMeasChan
          ? [
              {
                channel: yMeasChan,
                color: colMeasured,
                dash: "",
                strokeWidth: "2.0",
                legendSymbol: "—",
              },
            ]
          : []),
        ...(yOneStepChan
          ? [
              {
                channel: yOneStepChan,
                color: colOneStep,
                dash: "4 2",
                strokeWidth: "2.0",
                legendSymbol: "··",
              },
            ]
          : []),
      ],
    },
    {
      subplotId: "free-sim",
      title: `3. Simulação Livre (ŷ_livre) vs. Saída Medida (y) [${outUnit}]`,
      colIdx: 0,
      rowIdx: 1,
      yUnit: outUnit,
      includeZeroRef: false,
      series: [
        ...(yMeasChan
          ? [
              {
                channel: yMeasChan,
                color: colMeasured,
                dash: "",
                strokeWidth: "2.0",
                legendSymbol: "—",
              },
            ]
          : []),
        ...(yFreeSimChan
          ? [
              {
                channel: yFreeSimChan,
                color: colFreeSim,
                dash: "6 3",
                strokeWidth: "2.0",
                legendSymbol: "--",
              },
            ]
          : []),
      ],
    },
    {
      subplotId: "residuals",
      title: `4. Resíduos: 1-Passo (e_1p) vs. Sim. Livre (e_livre) [${outUnit}]`,
      colIdx: 1,
      rowIdx: 1,
      yUnit: outUnit,
      includeZeroRef: true,
      series: [
        ...(resOneStepChan
          ? [
              {
                channel: resOneStepChan,
                color: colResOneStep,
                dash: "",
                strokeWidth: "1.4",
                legendSymbol: "—",
              },
            ]
          : []),
        ...(resFreeSimChan
          ? [
              {
                channel: resFreeSimChan,
                color: colResFreeSim,
                dash: "6 3",
                strokeWidth: "1.4",
                legendSymbol: "--",
              },
            ]
          : []),
      ],
    },
  ];

  const colBoxes = [
    { left: 56, width: 310 },
    { left: 428, width: 310 },
  ];
  const rowBoxes = [
    { top: 58, height: 192 },
    { top: 316, height: 192 },
  ];

  const subplotGroups: string[] = [];
  const legendEntries: string[] = [];
  const emittedLegendChannels = new Set<string>();

  for (const spec of specs) {
    const cBox = colBoxes[spec.colIdx];
    const rBox = rowBoxes[spec.rowIdx];
    const boxLeft = cBox.left;
    const boxTop = rBox.top;
    const boxW = cBox.width;
    const boxH = rBox.height;

    const yValues: number[] = spec.includeZeroRef ? [0] : [];
    for (const s of spec.series) {
      yValues.push(...s.channel.values);
    }
    const yBounds = computeSafeAxisBounds(yValues, 0.14);

    const toPxX = (tVal: number) => mapCoord(tVal, xBounds.min, xBounds.span, boxLeft, boxW, false);
    const toPxY = (yVal: number) => mapCoord(yVal, yBounds.min, yBounds.span, boxTop, boxH, true);

    const zeroLine =
      yBounds.min <= 0 && yBounds.max >= 0
        ? `<line x1="${boxLeft}" y1="${toPxY(0).toFixed(2)}" x2="${boxLeft + boxW}" y2="${toPxY(0).toFixed(2)}" stroke="${theme.chartGrid}" stroke-dasharray="4 3" stroke-width="1" />`
        : "";

    const ticksX = [xBounds.min, (xBounds.min + xBounds.max) / 2, xBounds.max]
      .map((v) => {
        const px = toPxX(v).toFixed(2);
        const yBase = boxTop + boxH;
        return `<line x1="${px}" y1="${yBase}" x2="${px}" y2="${yBase + 4}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${px}" y="${yBase + 15}" text-anchor="middle" font-size="9.5" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(v, decimals))}</text>`;
      })
      .join("");

    const ticksY = [yBounds.min, (yBounds.min + yBounds.max) / 2, yBounds.max]
      .map((v) => {
        const py = toPxY(v).toFixed(2);
        return `<line x1="${boxLeft - 4}" y1="${py}" x2="${boxLeft}" y2="${py}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${boxLeft - 6}" y="${(Number(py) + 3).toFixed(2)}" text-anchor="end" font-size="9.5" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(v, decimals))}</text>`;
      })
      .join("");

    const polylines = spec.series
      .map((s) => {
        const ch = s.channel;
        const n = Math.min(model.t.length, ch.values.length);
        if (n === 0) return "";
        const pts: string[] = [];
        for (let i = 0; i < n; i += 1) {
          pts.push(`${toPxX(model.t[i]).toFixed(2)},${toPxY(ch.values[i]).toFixed(2)}`);
        }
        const label = `${ch.label} [${ch.unit}] (${ch.series_semantics})`;
        return `<polyline fill="none" stroke="${s.color}" stroke-width="${s.strokeWidth}" stroke-dasharray="${s.dash}" points="${pts.join(" ")}" data-channel-id="${escapeHtml(ch.id)}" data-subplot-channel="${escapeHtml(spec.subplotId)}" data-series-semantics="${escapeHtml(ch.series_semantics)}"><title>${escapeHtml(label)}</title></polyline>`;
      })
      .join("");

    const localLegends = spec.series
      .map((s, idx) => {
        const ch = s.channel;
        const lx = boxLeft + 6;
        const ly = boxTop + 13 + idx * 13;
        const attr = !emittedLegendChannels.has(ch.id)
          ? ` data-legend-channel="${escapeHtml(ch.id)}"`
          : ` data-subplot-legend="${escapeHtml(ch.id)}"`;
        emittedLegendChannels.add(ch.id);
        return `<text x="${lx}" y="${ly}" font-size="9.5" fill="${s.color}"${attr}>${s.legendSymbol} ${escapeHtml(ch.label)}</text>`;
      })
      .join("");

    legendEntries.push(localLegends);

    subplotGroups.push(
      [
        `<g class="id-subplot-panel" data-subplot="${spec.subplotId}">`,
        `<text x="${boxLeft}" y="${boxTop - 7}" font-size="11" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(spec.title)}</text>`,
        `<rect x="${boxLeft}" y="${boxTop}" width="${boxW}" height="${boxH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
        zeroLine,
        `<g class="axis-ticks">${ticksX}${ticksY}</g>`,
        `<g class="subplot-curves">${polylines}</g>`,
        `<g class="subplot-legend">${localLegends}</g>`,
        `</g>`,
      ].join(""),
    );
  }

  const ariaSummary = `${model.title}; 4 subgráficos sincronizados (Entrada, Previsão 1-Passo, Simulação Livre e Resíduos); ${model.channels.length} canais confirmados.`;

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${widthPx} ${heightPx}" role="img" aria-label="${escapeHtml(ariaSummary)}" style="background:${theme.surface};color:${theme.textPrimary}" data-chart-kind="time_response" data-chart-layout="identification-4panel" data-series-semantics="${escapeHtml(model.series_semantics)}" data-model-revision="${escapeHtml(String(model.model_revision))}" data-project-revision="${escapeHtml(String(model.project_revision))}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(ariaSummary)}</desc>`,
    `<text x="56" y="24" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(formatChartHeadingTitle(model.title, model.series_semantics))}</text>`,
    `<g data-layer="committed">${subplotGroups.join("")}</g>`,
    `<text x="${(widthPx / 2).toFixed(1)}" y="${heightPx - 10}" text-anchor="middle" font-size="11.5" fill="${theme.textSecondary}">${escapeHtml(model.units.x_axis)}</text>`,
    `</svg>`,
  ].join("");
}

export function renderTimeResponseSvg(
  model: TimeResponseChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const isIdentChart =
    model.chart_id.startsWith("id-response") ||
    model.channels.some((ch) => ch.id.startsWith("y-measured") || ch.id.startsWith("y-hat-"));

  if (isIdentChart) {
    return renderIdentificationFourPanelSvg(model, options);
  }

  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 360;
  const decimals = options?.decimals ?? 3;
  const effectiveThemeMode = options?.themeMode ?? model.theme_mode ?? "standard_aa";
  const theme = getThemeTokens(effectiveThemeMode);

  const xBounds = computeSafeAxisBounds(model.t, 0.02);
  const allY: number[] = [];
  for (const ch of model.channels) allY.push(...ch.values);
  for (const pch of model.preview_channels) allY.push(...pch.values);
  const yBounds = computeSafeAxisBounds(allY, 0.12);

  const padLeft = 64;
  const padRight = 24;
  const padTop = 40;
  const padBottom = 50;
  const plotW = widthPx - padLeft - padRight;
  const plotH = heightPx - padTop - padBottom;

  const toPxX = (tVal: number) => mapCoord(tVal, xBounds.min, xBounds.span, padLeft, plotW, false);
  const toPxY = (yVal: number) => mapCoord(yVal, yBounds.min, yBounds.span, padTop, plotH, true);

  const buildPolyline = (
    ch: TimeSeriesChannel,
    color: string,
    isPreview: boolean,
  ): string => {
    const n = Math.min(model.t.length, ch.values.length);
    if (n === 0) return "";
    const pts: string[] = [];
    for (let i = 0; i < n; i += 1) {
      pts.push(`${toPxX(model.t[i]).toFixed(2)},${toPxY(ch.values[i]).toFixed(2)}`);
    }
    const label = `${ch.label} [${ch.unit}] (${ch.series_semantics})`;
    const strokeWidth = isPreview ? "2" : ch.id.includes("residual") ? "1.4" : "2.2";
    return `<polyline fill="none" stroke="${color}" stroke-width="${strokeWidth}" stroke-dasharray="${ch.stroke_dasharray}" points="${pts.join(" ")}" data-channel-id="${escapeHtml(ch.id)}" data-series-semantics="${escapeHtml(ch.series_semantics)}"><title>${escapeHtml(label)}</title></polyline>`;
  };

  const isObserverChart =
    model.chart_id === "observer-state-comparison" ||
    model.channels.some((ch) => ch.id.startsWith("obs-state-"));

  const STATE_COLORS_LIGHT = ["#1D4ED8", "#059669", "#9333EA", "#EA580C", "#0891B2", "#DC2626"];
  const STATE_COLORS_HC = ["#38BDF8", "#4ADE80", "#F472B6", "#FB923C", "#22D3EE", "#FCA5A5"];

  const resolveChannelColor = (ch: TimeSeriesChannel): string => {
    if (isObserverChart) {
      const obsMatch = /^obs-state-(?:x|xhat)-(\d+)$/.exec(ch.id);
      if (obsMatch) {
        const stateIdx = Math.max(0, Number(obsMatch[1]) - 1);
        const palette = effectiveThemeMode === "high_contrast" ? STATE_COLORS_HC : STATE_COLORS_LIGHT;
        return palette[stateIdx % palette.length];
      }
    }
    if (ch.color) return ch.color;
    if (ch.group === "u") return theme.chartOpenLoop;
    if (ch.group === "x") return theme.chartOverlayExact;
    return theme.chartClosedLoop;
  };

  const committedLines = model.channels
    .map((ch) => buildPolyline(ch, resolveChannelColor(ch), false))
    .join("");
  const previewLines = model.preview_channels
    .map((ch) => buildPolyline(ch, theme.chartPreview, true))
    .join("");

  const zeroYGrid =
    yBounds.min <= 0 && yBounds.max >= 0
      ? `<line x1="${padLeft}" y1="${toPxY(0).toFixed(2)}" x2="${widthPx - padRight}" y2="${toPxY(0).toFixed(2)}" stroke="${theme.chartGrid}" stroke-dasharray="4 3" stroke-width="1" />`
      : "";

  const timeTicksX = [xBounds.min, (xBounds.min + xBounds.max) / 2, xBounds.max]
    .map((v) => {
      const px = toPxX(v).toFixed(2);
      const yBase = heightPx - padBottom;
      return `<line x1="${px}" y1="${yBase}" x2="${px}" y2="${yBase + 4}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${px}" y="${yBase + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(v, decimals))}</text>`;
    })
    .join("");
  const timeTicksY = [yBounds.min, (yBounds.min + yBounds.max) / 2, yBounds.max]
    .map((v) => {
      const py = toPxY(v).toFixed(2);
      return `<line x1="${padLeft - 4}" y1="${py}" x2="${padLeft}" y2="${py}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${padLeft - 7}" y="${(Number(py) + 3).toFixed(2)}" text-anchor="end" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(v, decimals))}</text>`;
    })
    .join("");

  const timeLegendItems: string[] = isObserverChart
    ? model.channels.map((ch, idx) => {
        const col = resolveChannelColor(ch);
        const sym = !ch.stroke_dasharray
          ? "—"
          : ch.stroke_dasharray.startsWith("2") || ch.stroke_dasharray.startsWith("3")
            ? "··"
            : "--";
        const colsPerRow = 4;
        const colWidth = 135;
        const lx = padLeft + 8 + (idx % colsPerRow) * colWidth;
        const ly = padTop + 14 + Math.floor(idx / colsPerRow) * 14;
        return `<text x="${lx}" y="${ly}" font-size="10" fill="${col}" data-legend-channel="${escapeHtml(ch.id)}">${sym} ${escapeHtml(ch.label)}</text>`;
      })
    : [
        `<text x="${padLeft + 8}" y="${padTop + 14}" font-size="10" fill="${theme.chartClosedLoop}">— Saída (y)</text>`,
        `<text x="${padLeft + 88}" y="${padTop + 14}" font-size="10" fill="${theme.chartOpenLoop}">-- Entrada (u)</text>`,
        `<text x="${padLeft + 178}" y="${padTop + 14}" font-size="10" fill="${theme.chartOverlayExact}">·· Estado (x)</text>`,
      ];
  if (model.preview_channels.length > 0) {
    timeLegendItems.push(
      `<text x="${padLeft + 266}" y="${padTop + 14}" font-size="10" fill="${theme.chartPreview}">⋯ Preview</text>`,
    );
  }

  const ariaSummary = `${model.title}; ${model.channels.length} canais confirmados; ${model.preview_channels.length} canais preview; constante=${String(yBounds.isConstant)}.`;

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${widthPx} ${heightPx}" role="img" aria-label="${escapeHtml(ariaSummary)}" style="background:${theme.surface};color:${theme.textPrimary}" data-chart-kind="time_response" data-series-semantics="${escapeHtml(model.series_semantics)}" data-model-revision="${escapeHtml(String(model.model_revision))}" data-project-revision="${escapeHtml(String(model.project_revision))}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(ariaSummary)}</desc>`,
    `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
    zeroYGrid,
    `<g class="axis-ticks" data-layer="axis-ticks">${timeTicksX}${timeTicksY}</g>`,
    `<g data-layer="committed">${committedLines}</g>`,
    `<g data-layer="fast-preview">${previewLines}</g>`,
    `<g class="chart-legend" data-layer="legend">${timeLegendItems.join("")}</g>`,
    `<text x="${padLeft}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(formatChartHeadingTitle(model.title, model.series_semantics))}</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(2)}" y="${heightPx - 10}" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.x_axis)}</text>`,
    `<text x="16" y="${(padTop + plotH / 2).toFixed(2)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(2)})" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.y_axis)}</text>`,
    `</svg>`,
  ].join("");
}

export function buildSingularValuesChartModel(input: {
  chart_id?: string;
  title?: string;
  dt: number | null;
  omega: readonly number[];
  curves: readonly SingularValueCurve[];
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics?: ResultVerificationIndicator;
  theme_mode?: AccessibilityThemeMode;
}): SingularValuesChartModel {
  return {
    kind: "singular_values",
    chart_id: input.chart_id ?? "mimo-singular-values",
    title: input.title ?? "Valores Singulares MIMO σ(G, S, T, KS)",
    dt: input.dt,
    omega: [...input.omega],
    curves: input.curves.map((c) => ({ ...c, omega: [...c.omega], values_db: [...c.values_db] })),
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics ?? "numeric_verified",
    units: {
      x_axis: "Frequência ω [rad/s]",
      y_axis: "Valor Singular [dB]",
    },
    theme_mode: input.theme_mode,
  };
}

export function renderSingularValuesSvg(
  model: SingularValuesChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    visibleGroups?: ReadonlySet<string>;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 380;
  const decimals = options?.decimals ?? 3;
  const theme = getThemeTokens(options?.themeMode ?? model.theme_mode ?? "standard_aa");
  const visibleGroups = options?.visibleGroups;

  const activeCurves = visibleGroups
    ? model.curves.filter((c) => visibleGroups.has(c.group))
    : model.curves;

  const padLeft = 64;
  const padRight = 24;
  const padTop = 44;
  const padBottom = 50;
  const plotW = widthPx - padLeft - padRight;
  const plotH = heightPx - padTop - padBottom;

  const validW = model.omega.filter((w) => Number.isFinite(w) && w > 0);
  const minW = validW.length > 0 ? Math.min(...validW) : 0.01;
  const maxW = validW.length > 0 ? Math.max(...validW) : 100;
  const logMinW = Math.log10(Math.max(1e-6, minW));
  const logMaxW = Math.max(logMinW + 1e-3, Math.log10(Math.max(1e-5, maxW)));

  const allDb: number[] = [];
  for (const c of activeCurves) {
    for (const v of c.values_db) {
      if (Number.isFinite(v)) allDb.push(v);
    }
  }
  const yBounds = computeSafeAxisBounds(allDb, 0.12);

  const toPxX = (w: number) => {
    const lw = Math.log10(Math.max(1e-6, w));
    return padLeft + ((lw - logMinW) / (logMaxW - logMinW)) * plotW;
  };
  const toPxY = (db: number) => mapCoord(db, yBounds.min, yBounds.span, padTop, plotH, true);

  const groupColor = (g: SingularValueCurve["group"]): string => {
    if (g === "G") return theme.chartClosedLoop;
    if (g === "S") return theme.chartOpenLoop;
    if (g === "T") return theme.chartOverlayExact;
    return theme.chartPreview;
  };

  const minDecade = Math.floor(logMinW);
  const maxDecade = Math.ceil(logMaxW);
  const freqGridLines: string[] = [];
  for (let d = minDecade; d <= maxDecade; d += 1) {
    const wVal = 10 ** d;
    if (wVal >= minW && wVal <= maxW) {
      const gx = toPxX(wVal);
      freqGridLines.push(
        `<line x1="${gx.toFixed(1)}" y1="${padTop}" x2="${gx.toFixed(1)}" y2="${padTop + plotH}" stroke="${theme.chartGrid}" stroke-dasharray="2 3" stroke-width="0.8" />`,
        `<text x="${gx.toFixed(1)}" y="${padTop + plotH + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">10<tspan dy="-4" font-size="8">${d}</tspan></text>`,
      );
    }
  }

  const zeroDbLine =
    yBounds.min <= 0 && yBounds.max >= 0
      ? `<line x1="${padLeft}" y1="${toPxY(0).toFixed(1)}" x2="${padLeft + plotW}" y2="${toPxY(0).toFixed(1)}" stroke="${theme.chartGrid}" stroke-dasharray="4 3" stroke-width="1.2" data-reference-line="0db" />`
      : "";

  const yTicks = [yBounds.min, (yBounds.min + yBounds.max) / 2, yBounds.max]
    .map((v) => {
      const py = toPxY(v).toFixed(1);
      return `<line x1="${padLeft - 4}" y1="${py}" x2="${padLeft}" y2="${py}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${padLeft - 7}" y="${(Number(py) + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(v, decimals))}</text>`;
    })
    .join("");

  const polylines: string[] = [];
  const legendItems: string[] = [];
  activeCurves.forEach((curve, idx) => {
    const n = Math.min(curve.omega.length, curve.values_db.length);
    const pts: string[] = [];
    for (let i = 0; i < n; i += 1) {
      const w = curve.omega[i];
      const v = curve.values_db[i];
      if (Number.isFinite(w) && w > 0 && Number.isFinite(v)) {
        pts.push(`${toPxX(w).toFixed(1)},${toPxY(v).toFixed(1)}`);
      }
    }
    const color = groupColor(curve.group);
    const dash = curve.stroke_dasharray ?? (idx % 2 === 1 ? "6 3" : "");
    if (pts.length > 0) {
      polylines.push(
        `<polyline fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="${dash}" points="${pts.join(" ")}" data-curve-id="${escapeHtml(curve.id)}" data-curve-group="${escapeHtml(curve.group)}"><title>${escapeHtml(curve.label)} [dB]</title></polyline>`,
      );
    }
    const lx = padLeft + 8 + (idx % 3) * 180;
    const ly = padTop + 14 + Math.floor(idx / 3) * 14;
    legendItems.push(
      `<text x="${lx}" y="${ly}" font-size="10" fill="${color}">${dash ? "--" : "—"} ${escapeHtml(curve.label)}</text>`,
    );
  });

  const desc = `${model.title}: ${activeCurves.length} curvas ativas em [${minW.toExponential(2)}, ${maxW.toExponential(2)}] rad/s.`;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(model.title)}" class="scientific-chart-svg singular-values-chart" viewBox="0 0 ${widthPx} ${heightPx}" width="${widthPx}" height="${heightPx}" data-chart-kind="singular_values" data-chart-id="${escapeHtml(model.chart_id)}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(desc)}</desc>`,
    `<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="${theme.surface}" />`,
    `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
    ...freqGridLines,
    zeroDbLine,
    `<g class="axis-ticks" data-layer="axis-ticks">${yTicks}</g>`,
    `<g data-layer="curves">${polylines.join("")}</g>`,
    `<g class="chart-legend" data-layer="legend">${legendItems.join("")}</g>`,
    `<text x="${padLeft}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(formatChartHeadingTitle(model.title, model.series_semantics))}</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(1)}" y="${heightPx - 10}" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">${escapeHtml(model.units.x_axis)}</text>`,
    `<text x="16" y="${(padTop + plotH / 2).toFixed(1)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(1)})" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">${escapeHtml(model.units.y_axis)}</text>`,
    `</svg>`,
  ].join("");
}

export function buildFuzzySurfaceChartModel(input: {
  chart_id?: string;
  title?: string;
  axes: readonly string[];
  output_name: string;
  x0_grid: readonly number[];
  x1_grid: readonly number[] | null;
  z_matrix: ReadonlyArray<readonly number[]> | null;
  z_line: readonly number[] | null;
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics?: ResultVerificationIndicator;
  theme_mode?: AccessibilityThemeMode;
}): FuzzySurfaceChartModel {
  return {
    kind: "fuzzy_surface",
    chart_id: input.chart_id ?? "fuzzy-control-surface",
    title: input.title ?? `Superfície de Controle Fuzzy: ${input.output_name}`,
    axes: [...input.axes],
    output_name: input.output_name,
    x0_grid: [...input.x0_grid],
    x1_grid: input.x1_grid ? [...input.x1_grid] : null,
    z_matrix: input.z_matrix ? input.z_matrix.map((row) => [...row]) : null,
    z_line: input.z_line ? [...input.z_line] : null,
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics ?? "numeric_verified",
    units: {
      x_axis: input.axes[0] ?? "x0",
      y_axis: input.axes[1] ?? input.output_name,
    },
    theme_mode: input.theme_mode,
  };
}

function interpolateHeatmapColor(tNorm: number): string {
  const t = Math.max(0, Math.min(1, tNorm));
  // Perceptually clear blue (#1e3a8a) -> teal (#0d9488) -> amber (#f59e0b) -> coral (#dc2626)
  const stops: ReadonlyArray<[number, number, number]> = [
    [30, 58, 138],
    [13, 148, 136],
    [245, 158, 11],
    [220, 38, 38],
  ];
  const scaled = t * (stops.length - 1);
  const idx = Math.min(stops.length - 2, Math.floor(scaled));
  const frac = scaled - idx;
  const c0 = stops[idx];
  const c1 = stops[idx + 1];
  const r = Math.round(c0[0] + (c1[0] - c0[0]) * frac);
  const g = Math.round(c0[1] + (c1[1] - c0[1]) * frac);
  const b = Math.round(c0[2] + (c1[2] - c0[2]) * frac);
  return `rgb(${r},${g},${b})`;
}

export function renderFuzzySurfaceSvg(
  model: FuzzySurfaceChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 400;
  const decimals = options?.decimals ?? 3;
  const theme = getThemeTokens(options?.themeMode ?? model.theme_mode ?? "standard_aa");

  const padLeft = 64;
  const padRight = 84;
  const padTop = 42;
  const padBottom = 50;
  const plotW = widthPx - padLeft - padRight;
  const plotH = heightPx - padTop - padBottom;

  if (model.axes.length === 1 || !model.z_matrix || !model.x1_grid) {
    const xVals = model.x0_grid;
    const zVals = model.z_line ?? [];
    const xBounds = computeSafeAxisBounds(xVals, 0.02);
    const yBounds = computeSafeAxisBounds(zVals, 0.12);
    const toPxX = (v: number) => mapCoord(v, xBounds.min, xBounds.span, padLeft, plotW, false);
    const toPxY = (v: number) => mapCoord(v, yBounds.min, yBounds.span, padTop, plotH, true);
    const pts: string[] = [];
    for (let i = 0; i < Math.min(xVals.length, zVals.length); i += 1) {
      pts.push(`${toPxX(xVals[i]).toFixed(1)},${toPxY(zVals[i]).toFixed(1)}`);
    }
    return [
      `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(model.title)}" class="scientific-chart-svg fuzzy-surface-chart" viewBox="0 0 ${widthPx} ${heightPx}" width="${widthPx}" height="${heightPx}" data-chart-kind="fuzzy_surface" data-chart-id="${escapeHtml(model.chart_id)}">`,
      `<title>${escapeHtml(model.title)}</title>`,
      `<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="${theme.surface}" />`,
      `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
      `<polyline fill="none" stroke="${theme.chartClosedLoop}" stroke-width="2.4" points="${pts.join(" ")}" />`,
      `<text x="${padLeft}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(model.title)}</text>`,
      `<text x="${(padLeft + plotW / 2).toFixed(1)}" y="${heightPx - 10}" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">${escapeHtml(model.axes[0] ?? "x0")}</text>`,
      `<text x="16" y="${(padTop + plotH / 2).toFixed(1)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(1)})" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">${escapeHtml(model.output_name)}</text>`,
      `</svg>`,
    ].join("");
  }

  const nx = model.x0_grid.length;
  const ny = model.x1_grid.length;
  const flatZ: number[] = [];
  for (const row of model.z_matrix) {
    for (const val of row) {
      if (Number.isFinite(val)) flatZ.push(val);
    }
  }
  const zMin = flatZ.length > 0 ? Math.min(...flatZ) : -1;
  const zMax = flatZ.length > 0 ? Math.max(...flatZ) : 1;
  const zSpan = Math.abs(zMax - zMin) <= 1e-12 ? 1 : zMax - zMin;

  const cellW = plotW / Math.max(1, nx);
  const cellH = plotH / Math.max(1, ny);
  const cellsSvg: string[] = [];
  for (let i = 0; i < nx; i += 1) {
    const row = model.z_matrix[i] ?? [];
    for (let j = 0; j < ny; j += 1) {
      const val = row[j] ?? 0;
      const norm = Math.abs(zMax - zMin) <= 1e-12 ? 0.5 : (val - zMin) / zSpan;
      const xPx = padLeft + i * cellW;
      const yPx = padTop + (ny - 1 - j) * cellH;
      cellsSvg.push(
        `<rect x="${xPx.toFixed(2)}" y="${yPx.toFixed(2)}" width="${(cellW + 0.4).toFixed(2)}" height="${(cellH + 0.4).toFixed(2)}" fill="${interpolateHeatmapColor(norm)}"><title>${escapeHtml(model.axes[0])}=${formatNumericDisplay(model.x0_grid[i], decimals)}, ${escapeHtml(model.axes[1])}=${formatNumericDisplay(model.x1_grid[j], decimals)} → ${escapeHtml(model.output_name)}=${formatNumericDisplay(val, decimals)}</title></rect>`,
      );
    }
  }

  // Colorbar
  const cbX = padLeft + plotW + 14;
  const cbW = 16;
  const cbSteps = 16;
  const cbSegH = plotH / cbSteps;
  const cbSvg: string[] = [];
  for (let k = 0; k < cbSteps; k += 1) {
    const norm = 1 - k / (cbSteps - 1);
    cbSvg.push(
      `<rect x="${cbX}" y="${(padTop + k * cbSegH).toFixed(1)}" width="${cbW}" height="${(cbSegH + 0.5).toFixed(1)}" fill="${interpolateHeatmapColor(norm)}" />`,
    );
  }
  cbSvg.push(
    `<rect x="${cbX}" y="${padTop}" width="${cbW}" height="${plotH}" fill="none" stroke="${theme.border}" stroke-width="1" />`,
    `<text x="${cbX + cbW + 5}" y="${padTop + 10}" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(zMax, decimals))}</text>`,
    `<text x="${cbX + cbW + 5}" y="${(padTop + plotH / 2 + 3).toFixed(1)}" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(0.5 * (zMin + zMax), decimals))}</text>`,
    `<text x="${cbX + cbW + 5}" y="${padTop + plotH}" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(zMin, decimals))}</text>`,
  );

  const xTicks =
    nx > 0
      ? [0, Math.floor((nx - 1) / 2), nx - 1].map((idx) => {
          const px = padLeft + (idx + 0.5) * cellW;
          return `<text x="${px.toFixed(1)}" y="${padTop + plotH + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(model.x0_grid[idx], decimals))}</text>`;
        })
      : [];
  const yTicks =
    ny > 0
      ? [0, Math.floor((ny - 1) / 2), ny - 1].map((idx) => {
          const py = padTop + (ny - 1 - idx + 0.5) * cellH;
          return `<text x="${padLeft - 6}" y="${(py + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(model.x1_grid![idx], decimals))}</text>`;
        })
      : [];

  const desc = `Superfície de controle fuzzy 2D (${nx}×${ny}) para ${model.output_name} em [${formatNumericDisplay(zMin, decimals)}, ${formatNumericDisplay(zMax, decimals)}].`;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(model.title)}" class="scientific-chart-svg fuzzy-surface-chart" viewBox="0 0 ${widthPx} ${heightPx}" width="${widthPx}" height="${heightPx}" data-chart-kind="fuzzy_surface" data-chart-id="${escapeHtml(model.chart_id)}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(desc)}</desc>`,
    `<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="${theme.surface}" />`,
    `<g data-layer="heatmap">${cellsSvg.join("")}</g>`,
    `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="none" stroke="${theme.border}" stroke-width="1" />`,
    `<g data-layer="colorbar">${cbSvg.join("")}</g>`,
    `<g class="axis-ticks" data-layer="axis-ticks">${xTicks.join("")}${yTicks.join("")}</g>`,
    `<text x="${padLeft}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(model.title)}</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(1)}" y="${heightPx - 10}" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">${escapeHtml(model.axes[0] ?? "x0")}</text>`,
    `<text x="16" y="${(padTop + plotH / 2).toFixed(1)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(1)})" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">${escapeHtml(model.axes[1] ?? "x1")}</text>`,
    `</svg>`,
  ].join("");
}

export function buildLmiSpectrumChartModel(input: {
  chart_id?: string;
  title?: string;
  block_min_eigs: readonly number[];
  block_labels?: readonly string[];
  closed_loop_poles?: ComplexVectorPair | null;
  alpha?: number | null;
  model_revision: number | null;
  project_revision: number | null;
  provenance: Provenance | null;
  series_semantics?: ResultVerificationIndicator;
  theme_mode?: AccessibilityThemeMode;
}): LmiSpectrumChartModel {
  const labels =
    input.block_labels && input.block_labels.length === input.block_min_eigs.length
      ? [...input.block_labels]
      : input.block_min_eigs.map((_, i) => `Bloco LMI F_${i + 1}(x*)`);
  return {
    kind: "lmi_spectrum",
    chart_id: input.chart_id ?? "lmi-eigenvalue-spectrum",
    title: input.title ?? "Espectro de Autovalores Mínimos dos Blocos LMI λ_min(F_b(x*))",
    block_min_eigs: [...input.block_min_eigs],
    block_labels: labels,
    closed_loop_poles: input.closed_loop_poles ?? null,
    alpha: input.alpha ?? null,
    model_revision: input.model_revision,
    project_revision: input.project_revision,
    provenance: input.provenance,
    series_semantics: input.series_semantics ?? "numeric_verified",
    units: {
      x_axis: "Autovalor mínimo λ_min(F_b(x*))",
      y_axis: "Bloco cônico",
    },
    theme_mode: input.theme_mode,
  };
}

export function renderLmiSpectrumSvg(
  model: LmiSpectrumChartModel,
  options?: {
    widthPx?: number;
    heightPx?: number;
    decimals?: number;
    themeMode?: AccessibilityThemeMode;
  },
): string {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 280;
  const decimals = options?.decimals ?? 4;
  const theme = getThemeTokens(options?.themeMode ?? model.theme_mode ?? "standard_aa");

  const padLeft = 140;
  const padRight = 32;
  const padTop = 44;
  const padBottom = 44;
  const plotW = widthPx - padLeft - padRight;
  const plotH = heightPx - padTop - padBottom;

  const vals = [0, ...model.block_min_eigs.filter(Number.isFinite)];
  const xBounds = computeSafeAxisBounds(vals, 0.15);
  const toPxX = (v: number) => mapCoord(v, xBounds.min, xBounds.span, padLeft, plotW, false);
  const zeroX = toPxX(0);

  const count = Math.max(1, model.block_min_eigs.length);
  const rowH = plotH / count;
  const barsSvg: string[] = [];

  for (let i = 0; i < model.block_min_eigs.length; i += 1) {
    const lam = model.block_min_eigs[i];
    const label = model.block_labels[i] ?? `Bloco ${i + 1}`;
    const yCenter = padTop + (i + 0.5) * rowH;
    const barH = Math.min(26, Math.max(10, rowH * 0.55));
    const lamX = toPxX(lam);
    const barX = Math.min(zeroX, lamX);
    const barW = Math.max(2, Math.abs(lamX - zeroX));
    const fillCol =
      lam < -1e-9
        ? theme.chartOpenLoop
        : lam <= 1e-6
          ? theme.chartPreview
          : theme.chartOverlayExact;

    barsSvg.push(
      `<text x="${padLeft - 8}" y="${(yCenter + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="${theme.textPrimary}">${escapeHtml(label)}</text>`,
      `<rect x="${barX.toFixed(1)}" y="${(yCenter - barH / 2).toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}" rx="3" fill="${fillCol}" data-lmi-block="${i}"><title>${escapeHtml(label)}: λ_min=${formatNumericDisplay(lam, decimals)}</title></rect>`,
      `<text x="${(lam >= 0 ? lamX + 5 : lamX - 5).toFixed(1)}" y="${(yCenter + 4).toFixed(1)}" text-anchor="${lam >= 0 ? "start" : "end"}" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatNumericDisplay(lam, decimals))}</text>`,
    );
  }

  const xTicks = [xBounds.min, 0, xBounds.max].map((v) => {
    const px = toPxX(v).toFixed(1);
    return `<line x1="${px}" y1="${padTop + plotH}" x2="${px}" y2="${padTop + plotH + 4}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${px}" y="${padTop + plotH + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatAxisTickLabel(v, decimals))}</text>`;
  });

  const desc = `Espectro LMI com ${model.block_min_eigs.length} blocos; limiar PSD λ_min >= 0 destacado.`;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(model.title)}" class="scientific-chart-svg lmi-spectrum-chart" viewBox="0 0 ${widthPx} ${heightPx}" width="${widthPx}" height="${heightPx}" data-chart-kind="lmi_spectrum" data-chart-id="${escapeHtml(model.chart_id)}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(desc)}</desc>`,
    `<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="${theme.surface}" />`,
    `<rect x="${padLeft}" y="${padTop}" width="${plotW}" height="${plotH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
    `<line x1="${zeroX.toFixed(1)}" y1="${padTop}" x2="${zeroX.toFixed(1)}" y2="${padTop + plotH}" stroke="${theme.chartAxis}" stroke-dasharray="4 3" stroke-width="1.5" data-threshold="0" />`,
    `<g data-layer="lmi-bars">${barsSvg.join("")}</g>`,
    `<g class="axis-ticks" data-layer="axis-ticks">${xTicks.join("")}</g>`,
    `<text x="${padLeft}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(model.title)}</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(1)}" y="${heightPx - 8}" text-anchor="middle" font-size="11" fill="${theme.textSecondary}">${escapeHtml(model.units.x_axis)} (factível quando λ_min ≥ 0)</text>`,
    `</svg>`,
  ].join("");
}

export interface AccessibleChartTable {
  caption: string;
  headers: readonly string[];
  rows: ReadonlyArray<readonly string[]>;
  rawNumericRowCount: number;
  decimals: number;
  series_semantics: ResultVerificationIndicator;
  ariaAttributes: Record<string, string>;
}

/**
 * Constrói tabela acessível WCAG 2.2 AA a partir do gráfico sem alterar os valores
 * numéricos float64 armazenados no modelo do gráfico.
 */
export function buildAccessibleChartTable(
  chart: ScientificChartModel,
  decimals = 4,
): AccessibleChartTable {
  if (chart.kind === "pole_zero") {
    const headers = ["Série", "Índice", "Parte Real", "Parte Imaginária", "Estabilidade", "Semântica"];
    const rows: string[][] = [];

    const appendPair = (
      seriesName: string,
      pair: ComplexVectorPair | null,
      sem: ResultVerificationIndicator,
    ) => {
      if (!pair) return;
      const count = Math.min(pair.real.length, pair.imag.length);
      for (let i = 0; i < count; i += 1) {
        const re = pair.real[i];
        const im = pair.imag[i];
        const stab = classifyPoleStability(re, im, chart.dt);
        rows.push([
          seriesName,
          String(i + 1),
          formatNumericDisplay(re, decimals),
          formatNumericDisplay(im, decimals),
          stab.label,
          sem,
        ]);
      }
    };

    appendPair("Malha Aberta", chart.open_loop_poles, "numeric_verified");
    appendPair(
      "Malha Fechada (Confirmado)",
      chart.committed_closed_loop_poles,
      chart.series_semantics,
    );
    appendPair("Fast-Preview", chart.preview_poles, "preview");

    return {
      caption: `${chart.title} (Rev. Modelo ${String(chart.model_revision)}, Rev. Projeto ${String(chart.project_revision)})`,
      headers,
      rows,
      rawNumericRowCount: rows.length,
      decimals,
      series_semantics: chart.series_semantics,
      ariaAttributes: {
        role: "table",
        "aria-label": `Tabela acessível de ${chart.title}`,
      },
    };
  }

  if (chart.kind === "bode" || chart.kind === "nyquist" || chart.kind === "root_locus") {
    const fmt = (v: number | undefined) =>
      v === undefined ? "—" : formatNumericDisplay(v, decimals);
    let headers: string[];
    const rows: string[][] = [];
    if (chart.kind === "bode") {
      headers = ["ω [rad/s]", "|G| [dB]", "Fase [graus]"];
      for (let i = 0; i < chart.omega.length; i += 1) {
        rows.push([fmt(chart.omega[i]), fmt(chart.mag_db[i]), fmt(chart.phase_deg[i])]);
      }
    } else if (chart.kind === "nyquist") {
      headers = ["ω [rad/s]", "Re G(jω)", "Im G(jω)"];
      for (let i = 0; i < chart.omega.length; i += 1) {
        rows.push([fmt(chart.omega[i]), fmt(chart.re[i]), fmt(chart.im[i])]);
      }
    } else {
      headers = ["Ganho K"];
      chart.branches.forEach((_, b) => {
        headers.push(`Ramo ${b + 1} Re`, `Ramo ${b + 1} Im`);
      });
      for (let i = 0; i < chart.gains.length; i += 1) {
        const row = [fmt(chart.gains[i])];
        for (const br of chart.branches) {
          row.push(fmt(br.real[i]), fmt(br.imag[i]));
        }
        rows.push(row);
      }
    }
    return {
      caption: `${chart.title} (Rev. Modelo ${String(chart.model_revision)}, Rev. Projeto ${String(chart.project_revision)}, ${chart.series_semantics})`,
      headers,
      rows,
      rawNumericRowCount: rows.length,
      decimals,
      series_semantics: chart.series_semantics,
      ariaAttributes: {
        role: "table",
        "aria-label": `Tabela acessível de ${chart.title}`,
      },
    };
  }

  if (chart.kind === "residual_correlation") {
    const headers = [
      "Lag τ",
      "R_ee(τ) Autocorrelação",
      "R_ue(τ) Cruzada u-e",
      "Banda 95% (±)",
      "Banda 99% (±)",
      "Dentro de 99%",
    ];
    const autoByLag = new Map<number, number>();
    for (let i = 0; i < Math.min(chart.lags.length, chart.autocorrelation.length); i += 1) {
      autoByLag.set(chart.lags[i], chart.autocorrelation[i]);
    }
    const crossByLag = new Map<number, number>();
    for (let i = 0; i < Math.min(chart.cross_lags.length, chart.crosscorrelation_u_e.length); i += 1) {
      crossByLag.set(chart.cross_lags[i], chart.crosscorrelation_u_e[i]);
    }
    const allLags = Array.from(new Set([...chart.cross_lags, ...chart.lags])).sort((a, b) => a - b);
    const rows: string[][] = [];
    const b95Str = formatNumericDisplay(chart.bound_95, decimals);
    const b99Str = formatNumericDisplay(chart.bound_99, decimals);

    for (const lag of allLags) {
      const ree = autoByLag.get(lag);
      const rue = crossByLag.get(lag);
      const reeOk = ree === undefined || lag === 0 || Math.abs(ree) <= chart.bound_99;
      const rueOk = rue === undefined || Math.abs(rue) <= chart.bound_99;
      rows.push([
        String(lag),
        ree !== undefined ? formatNumericDisplay(ree, decimals) : "—",
        rue !== undefined ? formatNumericDisplay(rue, decimals) : "—",
        b95Str,
        b99Str,
        reeOk && rueOk ? "Sim" : "Não (Fora)",
      ]);
    }

    return {
      caption: `${chart.title} (Partição: ${chart.partition}, N_eff=${chart.n_effective_samples}, Rev. Modelo ${String(chart.model_revision)}, Rev. Projeto ${String(chart.project_revision)})`,
      headers,
      rows,
      rawNumericRowCount: rows.length,
      decimals,
      series_semantics: chart.series_semantics,
      ariaAttributes: {
        role: "table",
        "aria-label": `Tabela acessível de ${chart.title}`,
      },
    };
  }

  if (chart.kind === "singular_values") {
    const headers = [
      "ω [rad/s]",
      ...chart.curves.map((c) => `${c.label} [dB]`),
    ];
    const rows: string[][] = [];
    for (let i = 0; i < chart.omega.length; i += 1) {
      const row = [formatNumericDisplay(chart.omega[i], decimals)];
      for (const c of chart.curves) {
        row.push(
          i < c.values_db.length ? formatNumericDisplay(c.values_db[i], decimals) : "—",
        );
      }
      rows.push(row);
    }
    return {
      caption: `${chart.title} (Rev. Modelo ${String(chart.model_revision)}, Rev. Projeto ${String(chart.project_revision)})`,
      headers,
      rows,
      rawNumericRowCount: rows.length,
      decimals,
      series_semantics: chart.series_semantics,
      ariaAttributes: {
        role: "table",
        "aria-label": `Tabela acessível de ${chart.title}`,
      },
    };
  }

  if (chart.kind === "fuzzy_surface") {
    if (chart.axes.length === 1 || !chart.z_matrix || !chart.x1_grid) {
      const headers = [chart.axes[0] ?? "x0", chart.output_name];
      const rows = chart.x0_grid.map((x0, i) => [
        formatNumericDisplay(x0, decimals),
        formatNumericDisplay(chart.z_line?.[i] ?? 0, decimals),
      ]);
      return {
        caption: `${chart.title}`,
        headers,
        rows,
        rawNumericRowCount: rows.length,
        decimals,
        series_semantics: chart.series_semantics,
        ariaAttributes: {
          role: "table",
          "aria-label": `Tabela acessível de ${chart.title}`,
        },
      };
    }
    const headers = [
      `${chart.axes[0]} \\ ${chart.axes[1]}`,
      ...chart.x1_grid.map((x1) => formatNumericDisplay(x1, decimals)),
    ];
    const rows = chart.x0_grid.map((x0, i) => [
      formatNumericDisplay(x0, decimals),
      ...(chart.z_matrix![i] ?? []).map((v) => formatNumericDisplay(v, decimals)),
    ]);
    return {
      caption: `${chart.title}`,
      headers,
      rows,
      rawNumericRowCount: rows.length,
      decimals,
      series_semantics: chart.series_semantics,
      ariaAttributes: {
        role: "table",
        "aria-label": `Tabela acessível de ${chart.title}`,
      },
    };
  }

  if (chart.kind === "lmi_spectrum") {
    const headers = ["Bloco LMI", "λ_min(F_b(x*))", "Factibilidade Cone"];
    const rows = chart.block_min_eigs.map((lam, i) => [
      chart.block_labels[i] ?? `Bloco ${i + 1}`,
      formatNumericDisplay(lam, decimals),
      lam < -1e-9 ? "Violado (< 0)" : lam <= 1e-6 ? "Na Fronteira (≈ 0)" : "Estritamente Factível (> 0)",
    ]);
    return {
      caption: `${chart.title}`,
      headers,
      rows,
      rawNumericRowCount: rows.length,
      decimals,
      series_semantics: chart.series_semantics,
      ariaAttributes: {
        role: "table",
        "aria-label": `Tabela acessível de ${chart.title}`,
      },
    };
  }

  const headers = [
    `t [${chart.units.time ?? "s"}]`,
    ...chart.channels.map((ch) => `${ch.label} [${ch.unit}]`),
  ];
  const rows: string[][] = [];
  for (let i = 0; i < chart.t.length; i += 1) {
    const row: string[] = [formatNumericDisplay(chart.t[i], decimals)];
    for (const ch of chart.channels) {
      row.push(
        i < ch.values.length ? formatNumericDisplay(ch.values[i], decimals) : "—",
      );
    }
    rows.push(row);
  }
  return {
    caption: `${chart.title} (Rev. Modelo ${String(chart.model_revision)}, Rev. Projeto ${String(chart.project_revision)})`,
    headers,
    rows,
    rawNumericRowCount: rows.length,
    decimals,
    series_semantics: chart.series_semantics,
    ariaAttributes: {
      role: "table",
      "aria-label": `Tabela acessível de ${chart.title}`,
    },
  };
}

export function renderAccessibleTableHtml(table: AccessibleChartTable): string {
  const ths = table.headers
    .map((h) => `<th scope="col">${escapeHtml(h)}</th>`)
    .join("");
  const trs = table.rows
    .map((row) => {
      const cells = row
        .map((cell, idx) =>
          idx === 0
            ? `<th scope="row">${escapeHtml(cell)}</th>`
            : `<td>${escapeHtml(cell)}</td>`,
        )
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  return [
    `<table class="accessible-data-table" aria-label="${escapeHtml(table.ariaAttributes["aria-label"] ?? table.caption)}">`,
    `<caption>${escapeHtml(table.caption)}</caption>`,
    `<thead><tr>${ths}</tr></thead>`,
    `<tbody>${trs}</tbody>`,
    `</table>`,
  ].join("");
}

/**
 * Exporta dados do gráfico para CSV com cabeçalho completo de proveniência.
 * PROIBIDO exportar dados marcados como `preview` ou com `pending_commit=true`.
 */
export function exportChartToCsv(
  chart: ScientificChartModel,
  options?: {
    decimals?: number;
    pendingCommit?: boolean;
    allowPreviewExport?: boolean;
  },
): string {
  if (
    options?.allowPreviewExport !== true &&
    (chart.series_semantics === "preview" || options?.pendingCommit === true)
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Proibido exportar gráfico durante Fast-Preview ou com pending_commit=true (CL-DIR-001 Seção 7.2).",
      {
        parameters: {
          series_semantics: chart.series_semantics,
          pending_commit: Boolean(options?.pendingCommit),
        },
        next_step:
          "Finalize o arraste (pointerup) e aguarde o commit autoritativo do motor Python antes de exportar.",
      },
    );
  }

  const decimals = options?.decimals ?? 15;
  const table = buildAccessibleChartTable(chart, decimals);
  const metaLines = [
    `# chart_id=${chart.chart_id}`,
    `# series_semantics=${chart.series_semantics}`,
    `# project_revision=${String(chart.project_revision)}`,
    `# model_revision=${String(chart.model_revision)}`,
    `# algorithm=${chart.provenance?.algorithm ?? "unknown"}`,
    `# feedback_sign=${chart.feedback_sign ?? "none"}`,
    `# units_x=${chart.units.x_axis}`,
    `# units_y=${chart.units.y_axis}`,
  ];
  const csvRows = [
    table.headers.map((h) => `"${h.replaceAll('"', '""')}"`).join(","),
    ...table.rows.map((r) =>
      r.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(","),
    ),
  ];
  return [...metaLines, ...csvRows].join("\n");
}

export interface FrameBudgetStats {
  frameCount: number;
  lastFrameMs: number;
  maxFrameMs: number;
  p95FrameMs: number;
  droppedFrames: number;
  withinBudgetRatio: number;
  budgetMs: number;
}

export class FrameBudgetTracker {
  private readonly samples: number[] = [];
  private readonly budgetMs: number;

  constructor(budgetMs = FRAME_BUDGET_60FPS_MS) {
    this.budgetMs = budgetMs;
  }

  public recordFrame(elapsedMs: number): void {
    const safe = Number.isFinite(elapsedMs) && elapsedMs >= 0 ? elapsedMs : 0;
    this.samples.push(safe);
    if (this.samples.length > 1000) {
      this.samples.shift();
    }
  }

  public getStats(): FrameBudgetStats {
    if (this.samples.length === 0) {
      return {
        frameCount: 0,
        lastFrameMs: 0,
        maxFrameMs: 0,
        p95FrameMs: 0,
        droppedFrames: 0,
        withinBudgetRatio: 1,
        budgetMs: this.budgetMs,
      };
    }
    const sorted = [...this.samples].sort((a, b) => a - b);
    const p95Idx = Math.min(sorted.length - 1, Math.floor(0.95 * (sorted.length - 1)));
    const dropped = this.samples.filter((s) => s > this.budgetMs).length;
    return {
      frameCount: this.samples.length,
      lastFrameMs: this.samples[this.samples.length - 1],
      maxFrameMs: sorted[sorted.length - 1],
      p95FrameMs: sorted[p95Idx],
      droppedFrames: dropped,
      withinBudgetRatio: (this.samples.length - dropped) / this.samples.length,
      budgetMs: this.budgetMs,
    };
  }

  public reset(): void {
    this.samples.length = 0;
  }
}

export const CHART_EXPORT_BASENAMES: Record<string, string> = {
  "id-response-chart-slot": "controllab-id-response",
  "id-residuals-chart-slot": "controllab-id-residuals",
  "siso-bode-chart-slot": "controllab-bode",
  "siso-nyquist-chart-slot": "controllab-nyquist",
  "siso-rl-chart-slot": "controllab-root-locus",
  "siso-time-chart-slot": "controllab-time-response",
  "mimo-sigma-chart-slot": "controllab-mimo-singular-values",
  "fuzzy-surface-chart-slot": "controllab-fuzzy-surface",
  "lmi-spectrum-chart-slot": "controllab-lmi-eigenvalues",
  "pz-chart-slot": "controllab-pole-zero",
  "time-chart-slot": "controllab-lqr-time-response",
};

export function getChartExportFilename(slotId: string, ext: "svg" | "png"): string {
  const base = CHART_EXPORT_BASENAMES[slotId] ?? `controllab-${slotId.replace(/[^a-z0-9_-]+/gi, "-")}`;
  return `${base}.${ext}`;
}

export function ensureSvgXmlns(svgMarkup: string): string {
  const trimmed = svgMarkup.trim();
  if (!/^<svg\b/i.test(trimmed)) return trimmed;
  if (/\bxmlns\s*=\s*["']http:\/\/www\.w3\.org\/2000\/svg["']/i.test(trimmed)) {
    return trimmed;
  }
  return trimmed.replace(/^<svg\b/i, '<svg xmlns="http://www.w3.org/2000/svg"');
}

export function serializeSvgForExport(slotOrSvg: Element | string | null | undefined): string | null {
  if (!slotOrSvg) return null;
  if (typeof slotOrSvg === "string") {
    const match = /<svg\b[\s\S]*<\/svg>/i.exec(slotOrSvg);
    return match ? ensureSvgXmlns(match[0]) : null;
  }

  const svgEl =
    slotOrSvg.tagName?.toLowerCase() === "svg"
      ? slotOrSvg
      : slotOrSvg.querySelector("svg");
  if (!svgEl) return null;

  if (typeof XMLSerializer !== "undefined" && typeof Node !== "undefined" && svgEl instanceof Node) {
    const serialized = new XMLSerializer().serializeToString(svgEl);
    return ensureSvgXmlns(serialized);
  }

  const outer = (svgEl as unknown as { outerHTML?: unknown }).outerHTML;
  if (typeof outer === "string" && /<svg\b/i.test(outer)) {
    return ensureSvgXmlns(outer);
  }

  const rawHtml = (slotOrSvg as unknown as { innerHTML?: unknown }).innerHTML;
  if (typeof rawHtml === "string") {
    const match = /<svg\b[\s\S]*<\/svg>/i.exec(rawHtml);
    if (match) return ensureSvgXmlns(match[0]);
  }
  return null;
}

export function parseSvgDimensions(svgMarkup: string): { width: number; height: number } {
  const viewBoxMatch = /\bviewBox\s*=\s*["']\s*[-+]?\d*\.?\d+\s+[-+]?\d*\.?\d+\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s*["']/i.exec(
    svgMarkup,
  );
  if (viewBoxMatch) {
    const w = Number(viewBoxMatch[1]);
    const h = Number(viewBoxMatch[2]);
    if (Number.isFinite(w) && w > 0 && Number.isFinite(h) && h > 0) {
      return { width: w, height: h };
    }
  }
  const widthMatch = /\bwidth\s*=\s*["'](\d+(?:\.\d+)?)/i.exec(svgMarkup);
  const heightMatch = /\bheight\s*=\s*["'](\d+(?:\.\d+)?)/i.exec(svgMarkup);
  const w = widthMatch ? Number(widthMatch[1]) : 640;
  const h = heightMatch ? Number(heightMatch[1]) : 400;
  return {
    width: Number.isFinite(w) && w > 0 ? w : 640,
    height: Number.isFinite(h) && h > 0 ? h : 400,
  };
}

export async function renderSvgMarkupToPngBlob(
  svgMarkup: string,
  options?: { scale?: number; backgroundColor?: string; doc?: Document },
): Promise<Blob> {
  const doc = options?.doc ?? globalThis.document;
  if (
    !doc ||
    typeof Blob === "undefined" ||
    typeof URL === "undefined" ||
    typeof URL.createObjectURL !== "function" ||
    typeof Image === "undefined"
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Exportação PNG indisponível neste ambiente sem suporte a Canvas/Image.",
    );
  }
  const scale = options?.scale ?? 2;
  const backgroundColor = options?.backgroundColor ?? "#ffffff";
  const normalizedSvg = ensureSvgXmlns(svgMarkup);
  const { width, height } = parseSvgDimensions(normalizedSvg);
  const svgBlob = new Blob([normalizedSvg], { type: "image/svg+xml;charset=utf-8" });
  const objectUrl = URL.createObjectURL(svgBlob);

  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("Falha ao decodificar SVG para renderização PNG."));
      image.src = objectUrl;
    });

    const canvas = doc.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      throw new Error("Contexto 2D de Canvas indisponível para exportação PNG.");
    }
    ctx.fillStyle = backgroundColor;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    const pngBlob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error("Canvas.toBlob retornou nulo ao gerar PNG."));
      }, "image/png");
    });
    return pngBlob;
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
