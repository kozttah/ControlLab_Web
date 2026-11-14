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
}

export interface TimeResponseChartModel extends ChartCommonMetadata {
  kind: "time_response";
  dt: number | null;
  t: readonly number[];
  channels: readonly TimeSeriesChannel[];
  preview_channels: readonly TimeSeriesChannel[];
}

export type ScientificChartModel = PoleZeroChartModel | TimeResponseChartModel;

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
  options?: { widthPx?: number; heightPx?: number; decimals?: number },
): string {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 400;
  const decimals = options?.decimals ?? 3;
  const theme = getThemeTokens(model.theme_mode ?? "standard_aa");

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

  if (model.dt !== null) {
    allRe.push(-1, 1);
    allIm.push(-1, 1);
  }

  const xBounds = computeSafeAxisBounds(allRe, 0.15);
  const yBounds = computeSafeAxisBounds(allIm, 0.15);

  const vp: ChartViewport = {
    widthPx,
    heightPx,
    padLeftPx: 64,
    padRightPx: 24,
    padTopPx: 40,
    padBottomPx: 54,
    xMin: xBounds.min,
    xMax: xBounds.max,
    yMin: yBounds.min,
    yMax: yBounds.max,
  };
  const plotW = vp.widthPx - vp.padLeftPx - vp.padRightPx;
  const plotH = vp.heightPx - vp.padTopPx - vp.padBottomPx;

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
    .map((ov) => {
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
          return `<ellipse cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" rx="${rx.toFixed(2)}" ry="${ry.toFixed(2)}" fill="none" stroke="${theme.chartAxis}" stroke-dasharray="4 4" stroke-width="1.5" aria-label="Círculo unitário |z|=1" />`;
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
      return `<line x1="${px}" y1="${yBase}" x2="${px}" y2="${yBase + 4}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${px}" y="${yBase + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatNumericDisplay(v, decimals))}</text>`;
    })
    .join("");
  const pzTicksY = [vp.yMin, (vp.yMin + vp.yMax) / 2, vp.yMax]
    .map((v) => {
      const py = toPxY(v).toFixed(2);
      return `<line x1="${vp.padLeftPx - 4}" y1="${py}" x2="${vp.padLeftPx}" y2="${py}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${vp.padLeftPx - 7}" y="${(Number(py) + 3).toFixed(2)}" text-anchor="end" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatNumericDisplay(v, decimals))}</text>`;
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
    `<text x="${vp.padLeftPx}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(model.title)} [${escapeHtml(model.series_semantics)}]</text>`,
    `<text x="${(vp.padLeftPx + plotW / 2).toFixed(2)}" y="${heightPx - 10}" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.x_axis)} | ${escapeHtml(signText)}</text>`,
    `<text x="16" y="${(vp.padTopPx + plotH / 2).toFixed(2)}" transform="rotate(-90 16 ${(vp.padTopPx + plotH / 2).toFixed(2)})" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.y_axis)}</text>`,
    `</svg>`,
  ].join("");
}

export function renderTimeResponseSvg(
  model: TimeResponseChartModel,
  options?: { widthPx?: number; heightPx?: number; decimals?: number },
): string {
  const widthPx = options?.widthPx ?? 640;
  const heightPx = options?.heightPx ?? 360;
  const decimals = options?.decimals ?? 3;
  const theme = getThemeTokens(model.theme_mode ?? "standard_aa");

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
    return `<polyline fill="none" stroke="${color}" stroke-width="${isPreview ? "2" : "2.2"}" stroke-dasharray="${ch.stroke_dasharray}" points="${pts.join(" ")}" data-channel-id="${escapeHtml(ch.id)}" data-series-semantics="${escapeHtml(ch.series_semantics)}"><title>${escapeHtml(label)}</title></polyline>`;
  };

  const committedLines = model.channels
    .map((ch) =>
      buildPolyline(
        ch,
        ch.group === "u"
          ? theme.chartOpenLoop
          : ch.group === "x"
            ? theme.chartOverlayExact
            : theme.chartClosedLoop,
        false,
      ),
    )
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
      return `<line x1="${px}" y1="${yBase}" x2="${px}" y2="${yBase + 4}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${px}" y="${yBase + 16}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatNumericDisplay(v, decimals))}</text>`;
    })
    .join("");
  const timeTicksY = [yBounds.min, (yBounds.min + yBounds.max) / 2, yBounds.max]
    .map((v) => {
      const py = toPxY(v).toFixed(2);
      return `<line x1="${padLeft - 4}" y1="${py}" x2="${padLeft}" y2="${py}" stroke="${theme.chartAxis}" stroke-width="1" /><text x="${padLeft - 7}" y="${(Number(py) + 3).toFixed(2)}" text-anchor="end" font-size="10" fill="${theme.textSecondary}">${escapeHtml(formatNumericDisplay(v, decimals))}</text>`;
    })
    .join("");

  const timeLegendItems: string[] = [
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
    `<text x="${padLeft}" y="22" font-size="13" font-weight="bold" fill="${theme.textPrimary}">${escapeHtml(model.title)} [${escapeHtml(model.series_semantics)}]</text>`,
    `<text x="${(padLeft + plotW / 2).toFixed(2)}" y="${heightPx - 10}" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.x_axis)}</text>`,
    `<text x="16" y="${(padTop + plotH / 2).toFixed(2)}" transform="rotate(-90 16 ${(padTop + plotH / 2).toFixed(2)})" text-anchor="middle" font-size="12" fill="${theme.textSecondary}">${escapeHtml(model.units.y_axis)}</text>`,
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
