/**
 * Gráficos SVG determinísticos da Aba 6 — Obtenção de Modelos TS (Setor, TPMT & FEMT)
 * (CL-TS-MOD-DIR-001 Seções 5-7). Funções puras: nenhum `eval`/`new Function`;
 * todo texto dinâmico passa por `escapeHtml` (R-21) e todo gráfico expõe
 * `role="img"` + `aria-label` + `<title>`/`<desc>` (WCAG 2.2 AA).
 */

import {
  escapeHtml,
  formatNumericDisplay,
  getThemeTokens,
  type AccessibilityThemeMode,
} from "../app/accessibility.ts";
import type {
  DerivedTsFemtResult,
  DerivedTsSectorResult,
  DerivedTsTpmtResult,
} from "../bridge/ts_modeling.ts";

export type TsDerivationResult =
  | DerivedTsSectorResult
  | DerivedTsTpmtResult
  | DerivedTsFemtResult;

/** Paleta com contraste >= 3:1 sobre fundo claro (UI component, WCAG 1.4.11). */
export const TS_CHART_PALETTE: readonly string[] = [
  "#1D4ED8",
  "#B45309",
  "#047857",
  "#6D28D9",
  "#BE123C",
  "#0E7490",
  "#4D7C0F",
  "#334155",
];

export interface TsLineSeries {
  label: string;
  x: number[];
  y: number[];
  dashed?: boolean;
  colorIndex?: number;
}

export interface TsLineChartModel {
  id: string;
  title: string;
  xLabel: string;
  yLabel: string;
  series: TsLineSeries[];
  logY?: boolean;
  description: string;
}

export interface TsMeshModel {
  nodes: number[][];
  triangles: number[][];
  variables: string[];
  kind: string;
}

export interface TsHeatmapModel {
  xs: number[];
  ys: number[];
  values: number[][];
  maxError: number;
  xLabel: string;
  yLabel: string;
}

function isNumArray(v: unknown): v is number[] {
  return Array.isArray(v) && v.every((n) => typeof n === "number" && Number.isFinite(n));
}

function isNumMatrix(v: unknown): v is number[][] {
  return Array.isArray(v) && v.every(isNumArray);
}

function column(matrix: number[][], j: number): number[] {
  return matrix.map((row) => row[j] ?? 0);
}

function tensorNodes(grids: number[][]): number[][] {
  let nodes: number[][] = [[]];
  for (const g of grids) {
    const next: number[][] = [];
    for (const prefix of nodes) for (const v of g) next.push([...prefix, v]);
    nodes = next;
  }
  return nodes;
}

function isTensorLayout(grids: number[][], rows: number): boolean {
  return grids.length > 0 && grids.every(isNumArray) &&
    grids.reduce((acc, g) => acc * g.length, 1) === rows;
}

function sectorPremises(result: TsDerivationResult): Array<{ name: string; min: number; max: number }> {
  const spec = result.ts_state_space.membership_spec;
  const list = (spec as { sector_premises?: unknown }).sector_premises;
  if (!Array.isArray(list)) return [];
  const out: Array<{ name: string; min: number; max: number }> = [];
  for (const p of list) {
    const rec = p as { name?: unknown; min?: unknown; max?: unknown };
    if (typeof rec.name === "string" && typeof rec.min === "number" && typeof rec.max === "number") {
      out.push({ name: rec.name, min: rec.min, max: rec.max });
    }
  }
  return out;
}

/** Curvas 1D das funções de pertinência h_r (Setor: pesos lineares; TPMT: bases por eixo; FEMT: fatia nodal). */
export function buildMembership1DChartModel(result: TsDerivationResult): TsLineChartModel | null {
  const spec = result.ts_state_space.membership_spec;
  const kind = spec.representation_kind;
  const maxSeries = 8;
  if (kind === "sector_nonlinearity") {
    const premises = sectorPremises(result).slice(0, 4);
    if (premises.length === 0) return null;
    const series: TsLineSeries[] = [];
    premises.forEach((p, i) => {
      const span = p.max - p.min;
      const x = Array.from({ length: 21 }, (_, k) => p.min + (span * k) / 20);
      const w1 = x.map((v) => (span === 0 ? 1 : (v - p.min) / span));
      series.push({ label: `${p.name}: w₀`, x, y: w1.map((w) => 1 - w), colorIndex: i });
      series.push({ label: `${p.name}: w₁`, x, y: w1, dashed: true, colorIndex: i });
    });
    return {
      id: "ts-hr-chart",
      title: "Pesos setoriais 1D (w₀ + w₁ = 1 por premissa)",
      xLabel: "valor da premissa z",
      yLabel: "peso",
      series,
      description: `${premises.length} premissas setoriais; regra h_r = produto dos pesos.`,
    };
  }
  if (kind === "tpmt_interpolated") {
    const axis = (spec as { tpmt_axes?: Array<{ grid: number[]; weights_table: number[][]; variable: string }> })
      .tpmt_axes?.[0];
    if (!axis || !isNumArray(axis.grid) || !isNumMatrix(axis.weights_table)) return null;
    const rank = axis.weights_table[0]?.length ?? 0;
    const series: TsLineSeries[] = [];
    for (let j = 0; j < Math.min(rank, maxSeries); j += 1) {
      series.push({ label: `w₁,${j + 1}(${axis.variable})`, x: axis.grid, y: column(axis.weights_table, j), colorIndex: j });
    }
    return {
      id: "ts-hr-chart",
      title: `Bases de pertinência TPMT no eixo ${axis.variable}`,
      xLabel: axis.variable,
      yLabel: "peso",
      series,
      description: `Eixo 1 com posto ${rank}; h_r = produto tensorial das bases por eixo.`,
    };
  }
  const femt = (result as DerivedTsFemtResult);
  const grids = femt.axes_grids;
  const w = femt.W_nodal;
  if (!isNumMatrix(w) || !Array.isArray(grids) || !grids.every(isNumArray) || !isTensorLayout(grids, w.length)) {
    return null;
  }
  const stride = grids.slice(1).reduce((acc, g) => acc * g.length, 1);
  const idx = grids[0].map((_, i) => i * stride);
  const rules = w[0]?.length ?? 0;
  const series: TsLineSeries[] = [];
  for (let r = 0; r < Math.min(rules, maxSeries); r += 1) {
    series.push({ label: `h_${r + 1}`, x: grids[0], y: idx.map((n) => w[n][r]), colorIndex: r });
  }
  return {
    id: "ts-hr-chart",
    title: "Funções h_r FEMT (fatia nodal ao longo do eixo 1)",
    xLabel: femt.active_variables?.[0] ?? "x1",
    yLabel: "h_r",
    series,
    description: `Fatia nodal de ${rules} funções P1; demais eixos fixados no primeiro nó.`,
  };
}

/** Malha 2D (FEMT: Delaunay/Kuhn-Delaunay; TPMT: grade tensorial triangulada) em projeção nos 2 primeiros eixos. */
export function buildMesh2DModel(result: TsDerivationResult): TsMeshModel | null {
  const kind = result.ts_state_space.membership_spec.representation_kind;
  if (kind === "sector_nonlinearity") return null;
  const femt = result as DerivedTsFemtResult;
  const grids = kind === "femt_simplicial"
    ? femt.axes_grids
    : (result as DerivedTsTpmtResult).axis_grids;
  if (!Array.isArray(grids) || !grids.every(isNumArray)) return null;
  let nodes: number[][] | null = kind === "femt_simplicial" && isNumMatrix(femt.nodes) ? femt.nodes : null;
  let triangles: number[][] | null = kind === "femt_simplicial" && isNumMatrix(femt.simplices) ? femt.simplices : null;
  if (!nodes) {
    if (grids.length !== 2) return null;
    nodes = tensorNodes(grids);
  }
  if (!triangles) {
    if (grids.length !== 2 || nodes.length !== grids[0].length * grids[1].length) return null;
    const n1 = grids[1].length;
    triangles = [];
    for (let i = 0; i + 1 < grids[0].length; i += 1) {
      for (let j = 0; j + 1 < n1; j += 1) {
        const a = i * n1 + j;
        const b = a + 1;
        const c = a + n1;
        const d = c + 1;
        triangles.push([a, c, d], [a, d, b]);
      }
    }
  }
  const variables = kind === "femt_simplicial"
    ? femt.active_variables.slice(0, 2)
    : (result as DerivedTsTpmtResult).active_variables.slice(0, 2);
  return {
    nodes: nodes.map((n) => [n[0] ?? 0, n[1] ?? 0]),
    triangles: triangles.filter((t) => t.every((i) => Number.isInteger(i) && i >= 0 && i < nodes.length)),
    variables,
    kind: kind === "femt_simplicial" ? femt.mesh_kind : "tensorial",
  };
}

/** Bases U (SVD bruta / pré-transformação) versus W (nodal / pós-envoltória). */
export function buildBasesChartModel(result: TsDerivationResult): TsLineChartModel | null {
  const kind = result.ts_state_space.membership_spec.representation_kind;
  let x: number[] = [];
  let u: number[][] | null = null;
  let w: number[][] | null = null;
  if (kind === "femt_simplicial") {
    const f = result as DerivedTsFemtResult;
    if (!isNumMatrix(f.U_raw) || !isNumMatrix(f.W_nodal)) return null;
    u = f.U_raw;
    w = f.W_nodal;
    x = u.map((_, i) => i + 1);
  } else if (kind === "tpmt_interpolated") {
    const t = result as DerivedTsTpmtResult;
    const pre = t.bases_pre_transform?.[0];
    const post = t.bases_post_transform?.[0];
    if (!isNumMatrix(pre) || !isNumMatrix(post)) return null;
    u = pre;
    w = post;
    x = isNumArray(t.axis_grids?.[0]) && t.axis_grids[0].length === pre.length
      ? t.axis_grids[0]
      : pre.map((_, i) => i + 1);
  } else {
    return null;
  }
  const cols = Math.min(u[0]?.length ?? 0, w[0]?.length ?? 0, 4);
  const series: TsLineSeries[] = [];
  for (let k = 0; k < cols; k += 1) {
    series.push({ label: `U[:,${k + 1}]`, x, y: column(u, k), colorIndex: k });
    series.push({ label: `W[:,${k + 1}]`, x, y: column(w, k), dashed: true, colorIndex: k });
  }
  return {
    id: "ts-bases-chart",
    title: "Bases U (SVD bruta) vs W (pesos convexos)",
    xLabel: kind === "femt_simplicial" ? "índice do nó" : "grade do eixo 1",
    yLabel: "valor da base",
    series,
    description: "Linha cheia: U (pode ter sinal). Tracejada: W (não negativa, soma 1) após envoltória.",
  };
}

/** Scree plot (escala log) dos valores singulares. */
export function buildScreeChartModel(result: TsDerivationResult): TsLineChartModel | null {
  const kind = result.ts_state_space.membership_spec.representation_kind;
  if (kind === "sector_nonlinearity") return null;
  const series: TsLineSeries[] = [];
  const raw = (result as DerivedTsFemtResult | DerivedTsTpmtResult).singular_values as unknown;
  if (isNumArray(raw)) {
    series.push({ label: "σ (matriz nodal)", x: raw.map((_, i) => i + 1), y: raw, colorIndex: 0 });
  } else if (isNumMatrix(raw)) {
    raw.forEach((s, i) => series.push({ label: `σ eixo ${i + 1}`, x: s.map((_, k) => k + 1), y: s, colorIndex: i }));
  } else {
    return null;
  }
  const rank = kind === "femt_simplicial" ? (result as DerivedTsFemtResult).svd_rank : undefined;
  return {
    id: "ts-scree-chart",
    title: "Scree plot dos valores singulares",
    xLabel: "índice k",
    yLabel: "σ_k (log)",
    series,
    logY: true,
    description: rank !== undefined ? `Posto retido R = ${rank}.` : "Valores singulares por eixo (HOSVD/HOOI).",
  };
}

function interp1(grid: number[], table: number[][], x: number): number[] {
  const n = grid.length;
  if (n === 0) return [];
  if (x <= grid[0]) return table[0].slice();
  if (x >= grid[n - 1]) return table[n - 1].slice();
  let hi = 1;
  while (hi < n - 1 && grid[hi] < x) hi += 1;
  const t = (x - grid[hi - 1]) / (grid[hi] - grid[hi - 1]);
  return table[hi].map((v, k) => (1 - t) * table[hi - 1][k] + t * v);
}

function weightsAt(result: TsDerivationResult, px: number, py: number): number[] | null {
  const kind = result.ts_state_space.membership_spec.representation_kind;
  if (kind === "tpmt_interpolated") {
    const axes = (result.ts_state_space.membership_spec as { tpmt_axes?: Array<{ grid: number[]; weights_table: number[][] }> }).tpmt_axes;
    if (!axes || axes.length !== 2) return null;
    const a = interp1(axes[0].grid, axes[0].weights_table, px);
    const b = interp1(axes[1].grid, axes[1].weights_table, py);
    const out: number[] = [];
    for (const wa of a) for (const wb of b) out.push(wa * wb);
    return out;
  }
  if (kind === "femt_simplicial") {
    const f = result as DerivedTsFemtResult;
    if (!isNumMatrix(f.W_nodal) || f.axes_grids?.length !== 2 || !isTensorLayout(f.axes_grids, f.W_nodal.length)) return null;
    const [g0, g1] = f.axes_grids;
    const rows0 = g0.map((_, i) => interp1(g1, f.W_nodal.slice(i * g1.length, (i + 1) * g1.length), py));
    return interp1(g0, rows0, px);
  }
  return null;
}

/** Mapa de calor do defeito de partição da unidade fora da grade: |Σh − 1| + max(0, −min h). */
export function buildOffGridErrorHeatmap(result: TsDerivationResult, resolution = 20): TsHeatmapModel | null {
  const kind = result.ts_state_space.membership_spec.representation_kind;
  if (kind === "sector_nonlinearity") return null;
  const grids = kind === "femt_simplicial"
    ? (result as DerivedTsFemtResult).axes_grids
    : (result as DerivedTsTpmtResult).axis_grids;
  if (!Array.isArray(grids) || grids.length !== 2 || !grids.every(isNumArray)) return null;
  const [g0, g1] = grids;
  const lo0 = g0[0], hi0 = g0[g0.length - 1], lo1 = g1[0], hi1 = g1[g1.length - 1];
  const n = Math.max(2, Math.min(60, Math.round(resolution)));
  const xs = Array.from({ length: n }, (_, i) => lo0 + ((hi0 - lo0) * (i + 0.37)) / n);
  const ys = Array.from({ length: n }, (_, j) => lo1 + ((hi1 - lo1) * (j + 0.37)) / n);
  let maxError = 0;
  const values: number[][] = [];
  for (const y of ys) {
    const row: number[] = [];
    for (const x of xs) {
      const w = weightsAt(result, x, y);
      if (!w) return null;
      const sum = w.reduce((a, b) => a + b, 0);
      const err = Math.abs(sum - 1) + Math.max(0, -Math.min(...w));
      row.push(err);
      if (err > maxError) maxError = err;
    }
    values.push(row);
  }
  const vars = kind === "femt_simplicial"
    ? (result as DerivedTsFemtResult).active_variables
    : (result as DerivedTsTpmtResult).active_variables;
  return { xs, ys, values, maxError, xLabel: vars?.[0] ?? "x1", yLabel: vars?.[1] ?? "x2" };
}

function fmt(v: number): string {
  return formatNumericDisplay(v, 4);
}

function frame(
  id: string,
  title: string,
  desc: string,
  body: string,
  width: number,
  height: number,
  mode: AccessibilityThemeMode,
): string {
  const theme = getThemeTokens(mode);
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" id="${escapeHtml(id)}" role="img" aria-label="${escapeHtml(title)}" class="scientific-chart-svg ts-modeling-chart-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">`,
    `<title>${escapeHtml(title)}</title><desc>${escapeHtml(desc)}</desc>`,
    `<rect x="0" y="0" width="${width}" height="${height}" fill="${theme.surface}" />`,
    body,
    `</svg>`,
  ].join("");
}

const PAD = { l: 52, r: 14, t: 34, b: 40 } as const;

export function renderTsLineChartSvg(
  model: TsLineChartModel,
  options: { themeMode?: AccessibilityThemeMode; width?: number; height?: number } = {},
): string {
  const mode = options.themeMode ?? "standard_aa";
  const theme = getThemeTokens(mode);
  const width = options.width ?? 520;
  const height = options.height ?? 280;
  const plotW = width - PAD.l - PAD.r;
  const plotH = height - PAD.t - PAD.b;
  const tf = (v: number): number => (model.logY ? Math.log10(Math.max(v, 1e-16)) : v);
  const xs = model.series.flatMap((s) => s.x);
  const ys = model.series.flatMap((s) => s.y.map(tf));
  if (xs.length === 0) return "";
  let xMin = Math.min(...xs), xMax = Math.max(...xs);
  let yMin = Math.min(...ys), yMax = Math.max(...ys);
  if (xMax === xMin) { xMin -= 1; xMax += 1; }
  if (yMax === yMin) { yMin -= 1; yMax += 1; }
  const px = (v: number): number => PAD.l + ((v - xMin) / (xMax - xMin)) * plotW;
  const py = (v: number): number => PAD.t + plotH - ((tf(v) - yMin) / (yMax - yMin)) * plotH;
  const yTickLabel = (t: number): string => (model.logY ? `1e${Math.round(t)}` : fmt(t));
  const parts: string[] = [
    `<rect x="${PAD.l}" y="${PAD.t}" width="${plotW}" height="${plotH}" fill="${theme.surfaceAlt}" stroke="${theme.border}" stroke-width="1" />`,
  ];
  for (let k = 0; k <= 4; k += 1) {
    const tv = yMin + ((yMax - yMin) * k) / 4;
    const y = PAD.t + plotH - (plotH * k) / 4;
    parts.push(`<line x1="${PAD.l}" y1="${y.toFixed(1)}" x2="${PAD.l + plotW}" y2="${y.toFixed(1)}" stroke="${theme.chartGrid}" stroke-width="0.6" />`);
    parts.push(`<text x="${PAD.l - 5}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="${theme.textSecondary}">${escapeHtml(yTickLabel(tv))}</text>`);
  }
  for (let k = 0; k <= 4; k += 1) {
    const tv = xMin + ((xMax - xMin) * k) / 4;
    parts.push(`<text x="${(px(tv)).toFixed(1)}" y="${PAD.t + plotH + 14}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(fmt(tv))}</text>`);
  }
  model.series.forEach((s, i) => {
    const color = TS_CHART_PALETTE[(s.colorIndex ?? i) % TS_CHART_PALETTE.length];
    const pts = s.x.map((xv, k) => `${px(xv).toFixed(1)},${py(s.y[k] ?? 0).toFixed(1)}`).join(" ");
    parts.push(`<polyline fill="none" stroke="${color}" stroke-width="2" ${s.dashed ? 'stroke-dasharray="6 3" ' : ""}points="${pts}" data-series="${escapeHtml(s.label)}" />`);
    s.x.forEach((xv, k) => {
      if (s.x.length <= 40) parts.push(`<circle cx="${px(xv).toFixed(1)}" cy="${py(s.y[k] ?? 0).toFixed(1)}" r="2.2" fill="${color}" />`);
    });
  });
  const legend = model.series.slice(0, 8).map((s, i) => {
    const color = TS_CHART_PALETTE[(s.colorIndex ?? i) % TS_CHART_PALETTE.length];
    const lx = PAD.l + 6 + (i % 4) * 118;
    const ly = 10 + Math.floor(i / 4) * 11;
    return `<text x="${lx}" y="${ly}" font-size="9" font-weight="bold" fill="${color}">${s.dashed ? "┄" : "━"} ${escapeHtml(s.label)}</text>`;
  });
  parts.push(...legend);
  parts.push(`<text x="${(PAD.l + plotW / 2).toFixed(1)}" y="${height - 6}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(model.xLabel)}</text>`);
  parts.push(`<text x="12" y="${(PAD.t + plotH / 2).toFixed(1)}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}" transform="rotate(-90 12 ${(PAD.t + plotH / 2).toFixed(1)})">${escapeHtml(model.yLabel)}</text>`);
  return frame(model.id, model.title, model.description, parts.join(""), width, height, mode);
}

export function renderTsMeshSvg(
  mesh: TsMeshModel,
  options: { themeMode?: AccessibilityThemeMode; width?: number; height?: number } = {},
): string {
  const mode = options.themeMode ?? "standard_aa";
  const theme = getThemeTokens(mode);
  const width = options.width ?? 420;
  const height = options.height ?? 320;
  const xs = mesh.nodes.map((n) => n[0]);
  const ys = mesh.nodes.map((n) => n[1]);
  const xMin = Math.min(...xs), xMax = Math.max(...xs), yMin = Math.min(...ys), yMax = Math.max(...ys);
  const plotW = width - PAD.l - PAD.r, plotH = height - PAD.t - PAD.b;
  const px = (v: number): number => PAD.l + (xMax === xMin ? 0.5 : (v - xMin) / (xMax - xMin)) * plotW;
  const py = (v: number): number => PAD.t + plotH - (yMax === yMin ? 0.5 : (v - yMin) / (yMax - yMin)) * plotH;
  const tris = mesh.triangles.map((t, k) => {
    const pts = t.map((i) => `${px(mesh.nodes[i][0]).toFixed(1)},${py(mesh.nodes[i][1]).toFixed(1)}`).join(" ");
    return `<polygon points="${pts}" fill="${theme.surfaceAlt}" stroke="${theme.chartClosedLoop}" stroke-width="1" data-simplex="${k}" />`;
  });
  const dots = mesh.nodes.length <= 600
    ? mesh.nodes.map((n) => `<circle cx="${px(n[0]).toFixed(1)}" cy="${py(n[1]).toFixed(1)}" r="2.4" fill="${theme.chartOpenLoop}" />`)
    : [];
  const body = [
    `<rect x="${PAD.l}" y="${PAD.t}" width="${plotW}" height="${plotH}" fill="none" stroke="${theme.border}" />`,
    ...tris,
    ...dots,
    `<text x="${PAD.l}" y="16" font-size="10" fill="${theme.textSecondary}">${escapeHtml(`${mesh.kind}: ${mesh.nodes.length} nós, ${mesh.triangles.length} simplexos`)}</text>`,
    `<text x="${(PAD.l + plotW / 2).toFixed(1)}" y="${height - 6}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(mesh.variables[0] ?? "x1")}</text>`,
    `<text x="12" y="${(PAD.t + plotH / 2).toFixed(1)}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}" transform="rotate(-90 12 ${(PAD.t + plotH / 2).toFixed(1)})">${escapeHtml(mesh.variables[1] ?? "x2")}</text>`,
  ].join("");
  return frame(
    "ts-mesh-chart",
    "Malha simplicial 2D",
    `Malha ${mesh.kind} com ${mesh.nodes.length} nós e ${mesh.triangles.length} simplexos.`,
    body,
    width,
    height,
    mode,
  );
}

export function renderTsHeatmapSvg(
  map: TsHeatmapModel,
  options: { themeMode?: AccessibilityThemeMode; width?: number; height?: number } = {},
): string {
  const mode = options.themeMode ?? "standard_aa";
  const theme = getThemeTokens(mode);
  const width = options.width ?? 420;
  const height = options.height ?? 320;
  const plotW = width - PAD.l - 60, plotH = height - PAD.t - PAD.b;
  const nx = map.xs.length, ny = map.ys.length;
  const cw = plotW / nx, ch = plotH / ny;
  const color = (v: number): string => {
    const t = map.maxError > 0 ? Math.min(1, v / map.maxError) : 0;
    const c = (a: number, b: number): number => Math.round(a + (b - a) * t);
    return `rgb(${c(239, 153)},${c(246, 27)},${c(255, 27)})`;
  };
  const cells: string[] = [];
  map.values.forEach((row, j) => row.forEach((v, i) => {
    cells.push(`<rect x="${(PAD.l + i * cw).toFixed(1)}" y="${(PAD.t + plotH - (j + 1) * ch).toFixed(1)}" width="${cw.toFixed(1)}" height="${ch.toFixed(1)}" fill="${color(v)}" />`);
  }));
  const body = [
    ...cells,
    `<rect x="${PAD.l}" y="${PAD.t}" width="${plotW}" height="${plotH}" fill="none" stroke="${theme.border}" />`,
    `<text x="${PAD.l + plotW + 8}" y="${PAD.t + 10}" font-size="10" fill="${theme.textSecondary}">máx</text>`,
    `<text x="${PAD.l + plotW + 8}" y="${PAD.t + 24}" font-size="10" fill="${theme.textPrimary}">${escapeHtml(fmt(map.maxError))}</text>`,
    `<text x="${PAD.l + plotW + 8}" y="${PAD.t + plotH}" font-size="10" fill="${theme.textSecondary}">mín 0</text>`,
    `<text x="${(PAD.l + plotW / 2).toFixed(1)}" y="${height - 6}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}">${escapeHtml(map.xLabel)}</text>`,
    `<text x="12" y="${(PAD.t + plotH / 2).toFixed(1)}" text-anchor="middle" font-size="10" fill="${theme.textSecondary}" transform="rotate(-90 12 ${(PAD.t + plotH / 2).toFixed(1)})">${escapeHtml(map.yLabel)}</text>`,
  ].join("");
  return frame(
    "ts-error-heatmap",
    "Mapa de calor do erro fora da grade",
    `Defeito de partição da unidade fora dos nós; erro máximo ${fmt(map.maxError)}.`,
    body,
    width,
    height,
    mode,
  );
}

/** Tabela acessível alternativa para um gráfico de linhas (WCAG 1.1.1). */
export function renderTsLineChartTableHtml(model: TsLineChartModel): string {
  const rows = model.series.map((s) => {
    const first = s.y.length > 0 ? fmt(s.y[0]) : "—";
    const last = s.y.length > 0 ? fmt(s.y[s.y.length - 1]) : "—";
    const max = s.y.length > 0 ? fmt(Math.max(...s.y)) : "—";
    return `<tr><th scope="row">${escapeHtml(s.label)}</th><td>${s.y.length}</td><td>${escapeHtml(first)}</td><td>${escapeHtml(last)}</td><td>${escapeHtml(max)}</td></tr>`;
  }).join("");
  return `<table class="accessible-data-table" aria-label="${escapeHtml(model.title)} — resumo"><thead><tr><th scope="col">Série</th><th scope="col">Pontos</th><th scope="col">Primeiro</th><th scope="col">Último</th><th scope="col">Máximo</th></tr></thead><tbody>${rows}</tbody></table>`;
}
