/**
 * Gráficos SVG determinísticos e acessíveis da Aba 6 — Obtenção de Modelos TS
 * (`CL-TS-MOD-DIR-001` Seções 2, 4, 5, 6 e `CL-UX-DIR-001` WCAG 2.2 AA).
 *
 * Contempla:
 * 1. Funções de pertinência 1D `w_{k,j}(z_k)` (Setor), `w_{d,j}(p_d)` (TPMT) ou corte 1D P1 (FEMT).
 * 2. Malha / superfície simplicial 2D (`delaunay` ou `kuhn_delaunay`) colorida por `h_r(p1, p2)`.
 * 3. Comparador de funções de base pré-fecho `U` (tracejado) vs pós-fecho `W` (contínuo).
 * 4. Scree plot logarítmico dos valores singulares `sigma_k^{(d)}` (TPMT) ou `sigma_k` global (FEMT).
 * 5. Mapa de calor real do erro fora da grade `||S(p) - S_TS(p)||_F` sobre o domínio compacto.
 */

import {
  escapeHtml,
  formatNumericDisplay,
  getThemeTokens,
  type AccessibilityThemeMode,
} from "../app/accessibility.ts";
import { isPlainObject, type RealTensor } from "../bridge/protocol.ts";
import type {
  DerivedTsFemtResult,
  DerivedTsSectorResult,
  DerivedTsTpmtResult,
} from "../bridge/ts_modeling.ts";
import { evalQlpvAst, parseQlpvExpr, type QlpvAstNode } from "../features/ts_modeling/symbolic_qlpv_ast.ts";

export type TsDerivationResult =
  | DerivedTsSectorResult
  | DerivedTsTpmtResult
  | DerivedTsFemtResult;

/** Paleta com contraste >= 3:1 sobre fundo claro/escuro (WCAG 1.4.11). */
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
  seriesSemantics?: string;
}

export interface TsMeshModel {
  nodes: number[][];
  triangles: number[][];
  nodalRuleWeights: number[];
  ruleIndex: number;
  numRules: number;
  variables: string[];
  kind: string;
}

export interface TsHeatmapModel {
  xs: number[];
  ys: number[];
  values: number[][];
  maxError: number;
  metricLabel: string;
  xLabel: string;
  yLabel: string;
}

function clampDust(v: number): number {
  return Math.abs(v) < 1e-13 ? 0 : v;
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

function linspace(lo: number, hi: number, count: number): number[] {
  if (count <= 1) return [0.5 * (lo + hi)];
  const step = (hi - lo) / (count - 1);
  return Array.from({ length: count }, (_, i) => (i === count - 1 ? hi : lo + i * step));
}

function interp1d(x: number, grid: readonly number[], values: readonly number[]): number {
  if (grid.length === 0 || values.length === 0) return 0;
  if (grid.length === 1 || x <= grid[0]) return values[0];
  const last = grid.length - 1;
  if (x >= grid[last]) return values[last] ?? 0;
  let lo = 0;
  let hi = last;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (grid[mid] <= x) lo = mid;
    else hi = mid;
  }
  const denom = grid[hi] - grid[lo];
  const t = denom > 0 ? (x - grid[lo]) / denom : 0;
  return (1 - t) * (values[lo] ?? 0) + t * (values[hi] ?? 0);
}

/** Avaliação baricêntrica P1 conformante de Kuhn-Delaunay O(D log D) em qualquer dimensão D >= 1. */
export function evaluateKuhnDelaunayWeights(
  point: readonly number[],
  axesGrids: ReadonlyArray<readonly number[]>,
  nodalWeights: ReadonlyArray<readonly number[]>,
): number[] {
  const d = axesGrids.length;
  const nRules = nodalWeights[0]?.length ?? 0;
  if (d === 0 || nRules === 0) return [];

  const shape = axesGrids.map((g) => g.length);
  const corner: number[] = [];
  const xi: number[] = [];
  for (let axis = 0; axis < d; axis += 1) {
    const g = axesGrids[axis];
    const pClamp = Math.min(Math.max(point[axis] ?? g[0], g[0]), g[g.length - 1]);
    let idx = 0;
    for (let k = 0; k < g.length - 1; k += 1) {
      if (pClamp >= g[k]) idx = k;
    }
    idx = Math.min(idx, Math.max(0, g.length - 2));
    const span = (g[idx + 1] ?? g[idx]) - g[idx];
    corner.push(idx);
    xi.push(span > 0 ? Math.min(1, Math.max(0, (pClamp - g[idx]) / span)) : 0);
  }

  const order = Array.from({ length: d }, (_, i) => i).sort((a, b) => (xi[b] ?? 0) - (xi[a] ?? 0));
  const ravelIndex = (coords: readonly number[]): number => {
    let flat = 0;
    for (let a = 0; a < d; a += 1) {
      flat = flat * shape[a] + coords[a];
    }
    return flat;
  };

  const out = new Array<number>(nRules).fill(0);
  const cur = [...corner];
  const lambda0 = 1.0 - (d > 0 ? xi[order[0]] : 0);
  const row0 = nodalWeights[ravelIndex(cur)] ?? [];
  for (let r = 0; r < nRules; r += 1) {
    out[r] += lambda0 * (row0[r] ?? 0);
  }
  for (let m = 0; m < d; m += 1) {
    const axis = order[m];
    cur[axis] = Math.min(shape[axis] - 1, cur[axis] + 1);
    const nextXi = m + 1 < d ? xi[order[m + 1]] : 0.0;
    const lambdaM = xi[axis] - nextXi;
    const rowM = nodalWeights[ravelIndex(cur)] ?? [];
    for (let r = 0; r < nRules; r += 1) {
      out[r] += lambdaM * (rowM[r] ?? 0);
    }
  }
  return out;
}

/** Avaliação baricêntrica P1 explícita sobre triângulos 2D (Delaunay). */
function evaluateDelaunay2DWeights(
  p1: number,
  p2: number,
  nodes: ReadonlyArray<readonly number[]>,
  simplices: ReadonlyArray<readonly number[]>,
  nodalWeights: ReadonlyArray<readonly number[]>,
): number[] | null {
  const nRules = nodalWeights[0]?.length ?? 0;
  for (const tri of simplices) {
    if (tri.length !== 3) continue;
    const n0 = nodes[tri[0]];
    const n1 = nodes[tri[1]];
    const n2 = nodes[tri[2]];
    if (!n0 || !n1 || !n2) continue;
    const det = (n1[0] - n0[0]) * (n2[1] - n0[1]) - (n2[0] - n0[0]) * (n1[1] - n0[1]);
    if (Math.abs(det) < 1e-14) continue;
    const l1 = ((p1 - n0[0]) * (n2[1] - n0[1]) - (n2[0] - n0[0]) * (p2 - n0[1])) / det;
    const l2 = ((n1[0] - n0[0]) * (p2 - n0[1]) - (p1 - n0[0]) * (n1[1] - n0[1])) / det;
    const l0 = 1.0 - l1 - l2;
    if (l0 >= -1e-9 && l1 >= -1e-9 && l2 >= -1e-9) {
      const c0 = Math.max(0, l0);
      const c1 = Math.max(0, l1);
      const c2 = Math.max(0, l2);
      const s = c0 + c1 + c2 || 1;
      const w0 = nodalWeights[tri[0]] ?? [];
      const w1 = nodalWeights[tri[1]] ?? [];
      const w2 = nodalWeights[tri[2]] ?? [];
      return Array.from(
        { length: nRules },
        (_, r) => (c0 * (w0[r] ?? 0) + c1 * (w1[r] ?? 0) + c2 * (w2[r] ?? 0)) / s,
      );
    }
  }
  return null;
}

/** Avalia o vetor de pertinências `h(x, w_ext)` para qualquer uma das 3 vias. */
export function evaluateDerivedMembershipWeights(
  result: TsDerivationResult,
  env: Readonly<Record<string, number>>,
): number[] | null {
  const spec = result.ts_state_space.membership_spec;
  if (spec.representation_kind === "sector_nonlinearity") {
    const premises = spec.sector_premises;
    const funcs = spec.functions;
    if (!Array.isArray(premises) || !Array.isArray(funcs) || premises.length === 0) return null;
    const wPairs: Array<[number, number]> = [];
    for (const p of premises) {
      const parsed = parseQlpvExpr(p.expression);
      const zVal =
        parsed.ok && parsed.ast
          ? evalQlpvAst(parsed.ast, env)
          : typeof env[p.name] === "number"
            ? env[p.name]
            : 0.5 * (p.min + p.max);
      const span = p.max - p.min;
      const w0 = span > 0 ? Math.min(1, Math.max(0, (zVal - p.min) / span)) : 0.5;
      wPairs.push([w0, 1.0 - w0]);
    }
    return funcs.map((fn) => {
      let prod = 1.0;
      for (let k = 0; k < fn.bits.length; k += 1) {
        const bit = fn.bits[k] === 0 ? 0 : 1;
        prod *= wPairs[k]?.[bit] ?? 1.0;
      }
      return prod;
    });
  }

  if (spec.representation_kind === "tpmt_interpolated") {
    const axes = spec.tpmt_axes;
    const funcs = spec.functions;
    if (!Array.isArray(axes) || !Array.isArray(funcs)) return null;
    const axisFactors = axes.map((ax) => {
      const val = env[ax.variable] ?? 0.5 * (ax.bounds[0] + ax.bounds[1]);
      const nBasis = ax.weights_table[0]?.length ?? 0;
      return Array.from({ length: nBasis }, (_, j) => interp1d(val, ax.grid, column(ax.weights_table, j)));
    });
    return funcs.map((fn) => {
      let prod = 1.0;
      for (let d = 0; d < fn.axis_basis_indices.length; d += 1) {
        prod *= axisFactors[d]?.[fn.axis_basis_indices[d]] ?? 0;
      }
      return prod;
    });
  }

  if (spec.representation_kind === "femt_simplicial") {
    const mesh = spec.femt_mesh;
    const pt = mesh.variables.map((v, i) => {
      const b = mesh.bounds[i] ?? [-1, 1];
      return env[v] ?? 0.5 * (b[0] + b[1]);
    });
    if (
      mesh.mesh_kind === "delaunay" &&
      pt.length === 2 &&
      Array.isArray(mesh.nodes) &&
      Array.isArray(mesh.simplices)
    ) {
      const triW = evaluateDelaunay2DWeights(
        pt[0],
        pt[1],
        mesh.nodes,
        mesh.simplices,
        mesh.nodal_weights,
      );
      if (triW) return triW;
    }
    if (Array.isArray(mesh.axes_grids) && mesh.axes_grids.length === pt.length) {
      return evaluateKuhnDelaunayWeights(pt, mesh.axes_grids, mesh.nodal_weights);
    }
  }
  return null;
}

/**
 * 1. Funções de pertinência 1D (Setor: w_{k,0}/w_{k,1}; TPMT: w_{d,j}(p_d); FEMT: corte 1D P1).
 */
export function buildMembership1DChartModel(
  result: TsDerivationResult,
  axisIndex = 0,
): TsLineChartModel | null {
  const spec = result.ts_state_space.membership_spec;

  if (spec.representation_kind === "sector_nonlinearity") {
    const premises = spec.sector_premises;
    if (!Array.isArray(premises) || premises.length === 0) return null;
    const k = Math.min(Math.max(0, axisIndex), premises.length - 1);
    const p = premises[k];
    const xs = linspace(p.min, p.max, 41);
    const span = p.max - p.min || 1;
    const w0 = xs.map((z) => (z - p.min) / span);
    const w1 = xs.map((z) => (p.max - z) / span);
    return {
      id: "ts-hr-1d",
      title: `Funções elementares de setor — ${p.name} = ${p.expression}`,
      xLabel: p.name,
      yLabel: "Pertinência",
      series: [
        { label: `w_${p.name},0 (máx)`, x: xs, y: w0, colorIndex: 0 },
        { label: `w_${p.name},1 (mín)`, x: xs, y: w1, dashed: true, colorIndex: 1 },
      ],
      description: `Funções lineares complementares de setor para ${p.name} em [${formatNumericDisplay(p.min, 4)}, ${formatNumericDisplay(p.max, 4)}].`,
      seriesSemantics: "numeric_verified",
    };
  }

  if (spec.representation_kind === "tpmt_interpolated") {
    const axes = spec.tpmt_axes;
    if (!Array.isArray(axes) || axes.length === 0) return null;
    const d = Math.min(Math.max(0, axisIndex), axes.length - 1);
    const ax = axes[d];
    const nBasis = ax.weights_table[0]?.length ?? 0;
    if (ax.grid.length < 2 || nBasis === 0) return null;
    const series: TsLineSeries[] = Array.from({ length: nBasis }, (_, j) => ({
      label: `w_${d + 1},${j + 1}(${ax.variable})`,
      x: ax.grid,
      y: column(ax.weights_table, j),
      colorIndex: j,
    }));
    return {
      id: "ts-hr-1d",
      title: `Funções de pertinência 1D (${ax.hull_type}) — eixo ${ax.variable}`,
      xLabel: ax.variable,
      yLabel: "w(p)",
      series,
      description: `${nBasis} funções de pertinência convexas no eixo ${ax.variable} (TPMT).`,
      seriesSemantics: "numeric_verified",
    };
  }

  if (spec.representation_kind === "femt_simplicial") {
    const mesh = spec.femt_mesh;
    if (mesh.variables.length === 0) return null;
    const d = Math.min(Math.max(0, axisIndex), mesh.variables.length - 1);
    const varName = mesh.variables[d];
    const b = mesh.bounds[d] ?? [-1, 1];
    const xs = linspace(b[0], b[1], 45);
    const baseEnv: Record<string, number> = {};
    for (let i = 0; i < mesh.variables.length; i += 1) {
      const bi = mesh.bounds[i] ?? [-1, 1];
      baseEnv[mesh.variables[i]] = 0.5 * (bi[0] + bi[1]);
    }
    const samples = xs.map((xVal) => evaluateDerivedMembershipWeights(result, { ...baseEnv, [varName]: xVal }) ?? []);
    const nShow = Math.min(8, mesh.num_rules);
    const series: TsLineSeries[] = Array.from({ length: nShow }, (_, r) => ({
      label: `h_${r + 1}`,
      x: xs,
      y: samples.map((row) => row[r] ?? 0),
      colorIndex: r,
    }));
    return {
      id: "ts-hr-1d",
      title: `Corte 1D das pertinências P1 (${mesh.mesh_kind}) — eixo ${varName}`,
      xLabel: varName,
      yLabel: "h_r(p)",
      series,
      description: `Corte unidimensional das funções baricêntricas P1 ao longo de ${varName} (demais variáveis fixas no centro de Ω).`,
      seriesSemantics: "numeric_verified",
    };
  }

  return null;
}

function buildCartesian2DTriangles(g0: readonly number[], g1: readonly number[]): {
  nodes: number[][];
  triangles: number[][];
} {
  const n0 = g0.length;
  const n1 = g1.length;
  const nodes: number[][] = [];
  for (let i = 0; i < n0; i += 1) {
    for (let j = 0; j < n1; j += 1) {
      nodes.push([g0[i], g1[j]]);
    }
  }
  const triangles: number[][] = [];
  for (let i = 0; i < n0 - 1; i += 1) {
    for (let j = 0; j < n1 - 1; j += 1) {
      const v00 = i * n1 + j;
      const v01 = i * n1 + (j + 1);
      const v10 = (i + 1) * n1 + j;
      const v11 = (i + 1) * n1 + (j + 1);
      // Subdivisão diagonal canônica de Kuhn-Freudenthal (v00 -> v11)
      triangles.push([v00, v10, v11], [v00, v11, v01]);
    }
  }
  return { nodes, triangles };
}

/**
 * 2. Malha / superfície simplicial 2D colorida pela regra selecionada `h_r(p_1, p_2)`.
 */
export function buildMesh2DModel(
  result: TsDerivationResult,
  ruleIndex = 0,
): TsMeshModel | null {
  const spec = result.ts_state_space.membership_spec;
  const safeRule = Math.min(Math.max(0, ruleIndex), Math.max(0, result.num_rules - 1));

  if (spec.representation_kind === "femt_simplicial") {
    const femt = result as DerivedTsFemtResult;
    const mesh = spec.femt_mesh;
    if (mesh.variables.length < 2) return null;

    if (
      mesh.mesh_kind === "delaunay" &&
      mesh.variables.length === 2 &&
      isNumMatrix(femt.nodes ?? mesh.nodes) &&
      Array.isArray(femt.simplices ?? mesh.simplices)
    ) {
      const nodes = (femt.nodes ?? mesh.nodes)!;
      const rawSimplices = (femt.simplices ?? mesh.simplices)!;
      const triangles = rawSimplices.filter(
        (t): t is number[] => Array.isArray(t) && t.length === 3,
      );
      const nodalRuleWeights = nodes.map((_, idx) => mesh.nodal_weights[idx]?.[safeRule] ?? 0);
      return {
        nodes,
        triangles,
        nodalRuleWeights,
        ruleIndex: safeRule,
        numRules: result.num_rules,
        variables: mesh.variables.slice(0, 2),
        kind: "delaunay",
      };
    }

    const grids = femt.axes_grids ?? mesh.axes_grids;
    if (grids.length >= 2 && grids[0].length >= 2 && grids[1].length >= 2) {
      // Limita densidade visual a no máx 21x21 para SVG leve e responsivo
      const g0 = grids[0].length > 21 ? linspace(grids[0][0], grids[0][grids[0].length - 1], 17) : grids[0];
      const g1 = grids[1].length > 21 ? linspace(grids[1][0], grids[1][grids[1].length - 1], 17) : grids[1];
      const { nodes, triangles } = buildCartesian2DTriangles(g0, g1);
      const midEnv: Record<string, number> = {};
      for (let a = 2; a < mesh.variables.length; a += 1) {
        const b = mesh.bounds[a] ?? [-1, 1];
        midEnv[mesh.variables[a]] = 0.5 * (b[0] + b[1]);
      }
      const nodalRuleWeights = nodes.map(([x, y]) => {
        const ws = evaluateDerivedMembershipWeights(result, {
          ...midEnv,
          [mesh.variables[0]]: x,
          [mesh.variables[1]]: y,
        });
        return ws?.[safeRule] ?? 0;
      });
      return {
        nodes,
        triangles,
        nodalRuleWeights,
        ruleIndex: safeRule,
        numRules: result.num_rules,
        variables: mesh.variables.slice(0, 2),
        kind: mesh.mesh_kind,
      };
    }
  }

  if (spec.representation_kind === "tpmt_interpolated") {
    const axes = spec.tpmt_axes;
    if (!Array.isArray(axes) || axes.length < 2) return null;
    const g0 = axes[0].grid.length > 17 ? linspace(axes[0].bounds[0], axes[0].bounds[1], 15) : axes[0].grid;
    const g1 = axes[1].grid.length > 17 ? linspace(axes[1].bounds[0], axes[1].bounds[1], 15) : axes[1].grid;
    const { nodes, triangles } = buildCartesian2DTriangles(g0, g1);
    const midEnv: Record<string, number> = {};
    for (let a = 2; a < axes.length; a += 1) {
      midEnv[axes[a].variable] = 0.5 * (axes[a].bounds[0] + axes[a].bounds[1]);
    }
    const nodalRuleWeights = nodes.map(([x, y]) => {
      const ws = evaluateDerivedMembershipWeights(result, {
        ...midEnv,
        [axes[0].variable]: x,
        [axes[1].variable]: y,
      });
      return ws?.[safeRule] ?? 0;
    });
    return {
      nodes,
      triangles,
      nodalRuleWeights,
      ruleIndex: safeRule,
      numRules: result.num_rules,
      variables: [axes[0].variable, axes[1].variable],
      kind: "tensor_grid_2d",
    };
  }

  return null;
}

/**
 * 3. Comparador de bases pré-transformação `U` (SVD/HOSVD) vs pós-transformação convexa `W`.
 */
export function buildBasesChartModel(
  result: TsDerivationResult,
  axisIndex = 0,
): TsLineChartModel | null {
  const kind = result.ts_state_space.membership_spec.representation_kind;
  if (kind === "tpmt_interpolated") {
    const tpmt = result as DerivedTsTpmtResult;
    const preList = tpmt.bases_pre_transform;
    const postList = tpmt.bases_post_transform;
    const grids = tpmt.axis_grids;
    if (!Array.isArray(preList) || preList.length === 0) return null;
    const d = Math.min(Math.max(0, axisIndex), preList.length - 1);
    const U = preList[d];
    const W = postList[d];
    const g = grids[d];
    const vName = tpmt.active_variables[d] ?? `p_${d + 1}`;
    if (!isNumMatrix(U) || !isNumMatrix(W) || !isNumArray(g) || g.length < 2) return null;

    const series: TsLineSeries[] = [];
    const nU = Math.min(6, U[0]?.length ?? 0);
    const nW = Math.min(6, W[0]?.length ?? 0);
    const xU = U.length === g.length ? g : linspace(g[0], g[g.length - 1], U.length);
    const xW = W.length === g.length ? g : linspace(g[0], g[g.length - 1], W.length);
    for (let j = 0; j < nU; j += 1) {
      series.push({
        label: `U_${j + 1} (ortogonal)`,
        x: xU,
        y: column(U, j),
        dashed: true,
        colorIndex: j,
      });
    }
    for (let j = 0; j < nW; j += 1) {
      series.push({
        label: `W_${j + 1} (fecho SN+NN)`,
        x: xW,
        y: column(W, j),
        dashed: false,
        colorIndex: j,
      });
    }
    return {
      id: "ts-bases-uw",
      title: `Bases HOSVD/HOOI U vs Pertinências W — eixo ${vName}`,
      xLabel: vName,
      yLabel: "Amplitude",
      series,
      description: `Comparação entre vetores singulares esquerdos U (tracejado) e funções convexas W (contínuo) no eixo ${vName}.`,
      seriesSemantics: "numeric_verified",
    };
  }

  if (kind === "femt_simplicial") {
    const femt = result as DerivedTsFemtResult;
    const U = femt.U_raw;
    const W = femt.W_nodal;
    if (!isNumMatrix(U) || !isNumMatrix(W) || U.length < 2 || W.length < 2) return null;
    const maxPts = 80;
    const stride = Math.max(1, Math.ceil(U.length / maxPts));
    const idxList: number[] = [];
    for (let q = 0; q < U.length; q += stride) idxList.push(q);
    if (idxList[idxList.length - 1] !== U.length - 1) idxList.push(U.length - 1);

    const xs = idxList.map((q) => q + 1);
    const series: TsLineSeries[] = [];
    const nU = Math.min(5, U[0]?.length ?? 0);
    const nW = Math.min(5, W[0]?.length ?? 0);
    for (let j = 0; j < nU; j += 1) {
      series.push({
        label: `U_${j + 1} (SVD)`,
        x: xs,
        y: idxList.map((q) => U[q]?.[j] ?? 0),
        dashed: true,
        colorIndex: j,
      });
    }
    for (let j = 0; j < nW; j += 1) {
      series.push({
        label: `W_${j + 1} (nodal)`,
        x: xs,
        y: idxList.map((q) => W[q]?.[j] ?? 0),
        dashed: false,
        colorIndex: j,
      });
    }
    return {
      id: "ts-bases-uw",
      title: "Bases nodais SVD U vs Pesos convexos W (FEMT)",
      xLabel: "Índice nodal amostrado q",
      yLabel: "Amplitude",
      series,
      description: "Comparação entre as colunas ortonormais U da SVD global e os pesos nodais convexos W.",
      seriesSemantics: "numeric_verified",
    };
  }

  return null;
}

/**
 * 4. Espectro logarítmico dos valores singulares (por modo na TPMT; global Eckart-Young na FEMT).
 */
export function buildScreeChartModel(result: TsDerivationResult): TsLineChartModel | null {
  const kind = result.ts_state_space.membership_spec.representation_kind;
  if (kind === "tpmt_interpolated") {
    const tpmt = result as DerivedTsTpmtResult;
    const modalSvs = tpmt.singular_values;
    if (!Array.isArray(modalSvs) || modalSvs.length === 0) return null;
    const series: TsLineSeries[] = modalSvs
      .filter((arr) => isNumArray(arr) && arr.length > 0)
      .map((arr, d) => ({
        label: `Modo ${d + 1} (${tpmt.active_variables[d] ?? `p_${d + 1}`})`,
        x: arr.map((_, k) => k + 1),
        y: arr.map((v) => Math.max(v, 1e-16)),
        colorIndex: d,
      }));
    if (series.length === 0) return null;
    return {
      id: "ts-scree",
      title: "Espectro de valores singulares modais σ_k^(d) (TPMT)",
      xLabel: "Índice k",
      yLabel: "σ_k (escala log)",
      series,
      logY: true,
      description: "Queda dos valores singulares em cada desdobramento modal do tensor amostrado.",
      seriesSemantics: "numeric_verified",
    };
  }

  if (kind === "femt_simplicial") {
    const femt = result as DerivedTsFemtResult;
    const svRaw = femt.singular_values;
    if (!isNumArray(svRaw) || svRaw.length === 0) return null;
    const xs = svRaw.map((_, k) => k + 1);
    const ys = svRaw.map((v) => Math.max(v, 1e-16));
    return {
      id: "ts-scree",
      title: "Espectro global de valores singulares σ_k (FEMT — Eckart–Young)",
      xLabel: "Índice k",
      yLabel: "σ_k (escala log)",
      series: [{ label: "σ_k global", x: xs, y: ys, colorIndex: 0 }],
      logY: true,
      description: "Valores singulares da matriz empilhada X^T que determinam o posto mínimo de regras.",
      seriesSemantics: "numeric_verified",
    };
  }
  return null;
}

function unpackTensor2D(t: RealTensor): number[][] {
  const rows = t.shape[0] ?? 0;
  const cols = t.shape[1] ?? 0;
  const out: number[][] = [];
  for (let r = 0; r < rows; r += 1) {
    const row: number[] = [];
    for (let c = 0; c < cols; c += 1) {
      row.push(t.order === "F" ? (t.data[c * rows + r] ?? 0) : (t.data[r * cols + c] ?? 0));
    }
    out.push(row);
  }
  return out;
}

function packSystemMatrix(A: number[][], B: number[][], C: number[][], D: number[][]): number[][] {
  const top = A.map((row, i) => [...row, ...(B[i] ?? [])]);
  const bot = C.map((row, i) => [...row, ...(D[i] ?? [])]);
  return [...top, ...bot];
}

function parseSymbolicMatrixAst(raw: unknown): QlpvAstNode[][] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const out: QlpvAstNode[][] = [];
  for (const row of raw) {
    if (!Array.isArray(row) || row.length === 0) return null;
    const astRow: QlpvAstNode[] = [];
    for (const cell of row) {
      const p = parseQlpvExpr(String(cell));
      if (!p.ok || !p.ast) return null;
      astRow.push(p.ast);
    }
    out.push(astRow);
  }
  return out;
}

function evalAstMatrix(mat: QlpvAstNode[][], env: Readonly<Record<string, number>>): number[][] {
  return mat.map((row) => row.map((node) => evalQlpvAst(node, env)));
}

/**
 * 5. Mapa de calor 2D do erro de aproximação fora da grade `||S(p) - S_TS(p)||_F` em Ω.
 */
export function buildOffGridErrorHeatmap(result: TsDerivationResult): TsHeatmapModel | null {
  const model = result.ts_state_space;
  const spec = model.membership_spec;
  const prov = isPlainObject(model.provenance) ? model.provenance : {};
  const deriv = isPlainObject(prov.ts_derivation) ? prov.ts_derivation : {};

  // Determina os 2 primeiros eixos contínuos para varredura fora da grade
  let axisVars: string[] = [];
  let boundsMap: Record<string, [number, number]> = {};
  if (isPlainObject(deriv.state_bounds)) {
    for (const [k, v] of Object.entries(deriv.state_bounds)) {
      if (Array.isArray(v) && v.length === 2) boundsMap[k] = [Number(v[0]), Number(v[1])];
    }
  }
  if (isPlainObject(deriv.external_bounds)) {
    for (const [k, v] of Object.entries(deriv.external_bounds)) {
      if (Array.isArray(v) && v.length === 2) boundsMap[k] = [Number(v[0]), Number(v[1])];
    }
  }
  if (Object.keys(boundsMap).length === 0 && isPlainObject(model.domain?.bounds)) {
    for (const [k, v] of Object.entries(model.domain.bounds)) {
      if (Array.isArray(v) && v.length === 2) boundsMap[k] = [Number(v[0]), Number(v[1])];
    }
  }

  if (spec.representation_kind === "femt_simplicial") {
    axisVars = [...spec.femt_mesh.variables];
    spec.femt_mesh.variables.forEach((v, i) => {
      const b = spec.femt_mesh.bounds[i];
      if (b) boundsMap[v] = [b[0], b[1]];
    });
  } else if (spec.representation_kind === "tpmt_interpolated") {
    axisVars = spec.tpmt_axes.map((a) => a.variable);
    spec.tpmt_axes.forEach((a) => {
      boundsMap[a.variable] = [a.bounds[0], a.bounds[1]];
    });
  } else if (spec.representation_kind === "sector_nonlinearity") {
    const active = new Set<string>();
    for (const p of spec.sector_premises) {
      for (const v of p.active_variables) active.add(v);
    }
    axisVars = active.size >= 2 ? Array.from(active) : Object.keys(boundsMap);
  }

  if (axisVars.length < 2) {
    const allKeys = Object.keys(boundsMap);
    for (const k of allKeys) {
      if (!axisVars.includes(k)) axisVars.push(k);
    }
  }
  if (axisVars.length < 2) return null;

  const vX = axisVars[0];
  const vY = axisVars[1];
  const bX = boundsMap[vX] ?? [-1, 1];
  const bY = boundsMap[vY] ?? [-1, 1];

  // Pontos deslocados (centros de subcélulas) para medir genuinamente fora da grade nodal
  const nGrid = 16;
  const xs = Array.from(
    { length: nGrid },
    (_, i) => bX[0] + ((i + 0.5) / nGrid) * (bX[1] - bX[0]),
  );
  const ys = Array.from(
    { length: nGrid },
    (_, j) => bY[0] + ((j + 0.5) / nGrid) * (bY[1] - bY[0]),
  );

  const baseEnv: Record<string, number> = {};
  for (const [k, b] of Object.entries(boundsMap)) {
    baseEnv[k] = 0.5 * (b[0] + b[1]);
  }

  const astA = parseSymbolicMatrixAst(deriv.A_expr);
  const astB = parseSymbolicMatrixAst(deriv.B_expr);
  const astC = parseSymbolicMatrixAst(deriv.C_expr);
  const astD = parseSymbolicMatrixAst(deriv.D_expr);
  const hasSymbolicTruth = Boolean(astA && astB && astC && astD && model.vertices.length > 0);

  const vertexPacked = hasSymbolicTruth
    ? model.vertices.map((v) =>
        packSystemMatrix(
          unpackTensor2D(v.A),
          unpackTensor2D(v.B),
          unpackTensor2D(v.C),
          unpackTensor2D(v.D),
        ),
      )
    : [];

  const sectorPremiseAsts =
    spec.representation_kind === "sector_nonlinearity"
      ? spec.sector_premises.map((p) => ({ name: p.name, parsed: parseQlpvExpr(p.expression) }))
      : [];

  let maxError = 0;
  const values: number[][] = [];
  for (let j = 0; j < ys.length; j += 1) {
    const rowVals: number[] = [];
    for (let i = 0; i < xs.length; i += 1) {
      const env: Record<string, number> = { ...baseEnv, [vX]: xs[i], [vY]: ys[j] };
      for (const sp of sectorPremiseAsts) {
        if (sp.parsed.ok && sp.parsed.ast) {
          env[sp.name] = evalQlpvAst(sp.parsed.ast, env);
        }
      }
      const h = evaluateDerivedMembershipWeights(result, env);
      let errVal = 0;
      if (hasSymbolicTruth && h && h.length === vertexPacked.length) {
        const sTrue = packSystemMatrix(
          evalAstMatrix(astA!, env),
          evalAstMatrix(astB!, env),
          evalAstMatrix(astC!, env),
          evalAstMatrix(astD!, env),
        );
        let sqSum = 0;
        for (let r = 0; r < sTrue.length; r += 1) {
          for (let c = 0; c < (sTrue[r]?.length ?? 0); c += 1) {
            let sHatRC = 0;
            for (let rule = 0; rule < h.length; rule += 1) {
              sHatRC += (h[rule] ?? 0) * (vertexPacked[rule]?.[r]?.[c] ?? 0);
            }
            const dRC = (sTrue[r]?.[c] ?? 0) - sHatRC;
            sqSum += dRC * dRC;
          }
        }
        errVal = Math.sqrt(sqSum);
      } else if (h && h.length > 0) {
        const sumH = h.reduce((acc, w) => acc + w, 0);
        const negViolation = Math.max(0, -Math.min(...h));
        errVal = Math.abs(sumH - 1.0) + negViolation;
      }
      if (!Number.isFinite(errVal)) errVal = 0;
      if (errVal > maxError) maxError = errVal;
      rowVals.push(errVal);
    }
    values.push(rowVals);
  }

  return {
    xs,
    ys,
    values,
    maxError,
    metricLabel: hasSymbolicTruth ? "||S(p) − Ŝ_TS(p)||_F" : "|∑ h_r − 1|",
    xLabel: vX,
    yLabel: vY,
  };
}

export function renderTsLineChartSvg(
  model: TsLineChartModel,
  options: { themeMode?: AccessibilityThemeMode; decimals?: number } = {},
): string {
  const tokens = getThemeTokens(options.themeMode ?? "standard_aa");
  const decimals = options.decimals ?? 4;
  const width = 460;
  const height = 250;
  const padL = 56;
  const padR = 18;
  const padT = 30;
  const padB = 46;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  let xMin = Number.POSITIVE_INFINITY;
  let xMax = Number.NEGATIVE_INFINITY;
  let yMin = Number.POSITIVE_INFINITY;
  let yMax = Number.NEGATIVE_INFINITY;

  const projectY = (y: number): number => (model.logY ? Math.log10(Math.max(y, 1e-16)) : y);

  for (const s of model.series) {
    for (const x of s.x) {
      if (x < xMin) xMin = x;
      if (x > xMax) xMax = x;
    }
    for (const y of s.y) {
      const py = projectY(y);
      if (py < yMin) yMin = py;
      if (py > yMax) yMax = py;
    }
  }
  if (!Number.isFinite(xMin) || !Number.isFinite(xMax)) {
    xMin = 0;
    xMax = 1;
  }
  if (Math.abs(xMax - xMin) < 1e-12) {
    xMin -= 0.5;
    xMax += 0.5;
  }
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) {
    yMin = 0;
    yMax = 1;
  }
  if (Math.abs(yMax - yMin) < 1e-12) {
    yMin -= 0.5;
    yMax += 0.5;
  } else {
    const margin = 0.06 * (yMax - yMin);
    yMin -= margin;
    yMax += margin;
  }

  const sx = (x: number): number => padL + ((x - xMin) / (xMax - xMin)) * plotW;
  const sy = (y: number): number => padT + (1 - (projectY(y) - yMin) / (yMax - yMin)) * plotH;

  const gridLines: string[] = [];
  for (let t = 0; t <= 4; t += 1) {
    const frac = t / 4;
    const gx = padL + frac * plotW;
    const gy = padT + (1 - frac) * plotH;
    const valX = clampDust(xMin + frac * (xMax - xMin));
    const rawValY = yMin + frac * (yMax - yMin);
    const valY = model.logY ? Math.pow(10, rawValY) : clampDust(rawValY);
    gridLines.push(
      `<line x1="${gx.toFixed(1)}" y1="${padT}" x2="${gx.toFixed(1)}" y2="${padT + plotH}" stroke="${tokens.border}" stroke-dasharray="2,3" stroke-width="0.8" />`,
      `<text x="${gx.toFixed(1)}" y="${padT + plotH + 15}" text-anchor="middle" fill="${tokens.textSecondary}" font-size="10">${escapeHtml(formatNumericDisplay(valX, Math.min(decimals, 3)))}</text>`,
      `<line x1="${padL}" y1="${gy.toFixed(1)}" x2="${padL + plotW}" y2="${gy.toFixed(1)}" stroke="${tokens.border}" stroke-dasharray="2,3" stroke-width="0.8" />`,
      `<text x="${padL - 6}" y="${(gy + 3).toFixed(1)}" text-anchor="end" fill="${tokens.textSecondary}" font-size="10">${escapeHtml(model.logY ? valY.toExponential(1) : formatNumericDisplay(valY, Math.min(decimals, 3)))}</text>`,
    );
  }

  const paths = model.series.map((s, idx) => {
    const color = TS_CHART_PALETTE[(s.colorIndex ?? idx) % TS_CHART_PALETTE.length];
    const pts = s.x
      .map((x, k) => `${k === 0 ? "M" : "L"}${sx(x).toFixed(2)},${sy(s.y[k] ?? 0).toFixed(2)}`)
      .join(" ");
    const dash = s.dashed ? ` stroke-dasharray="5,3"` : "";
    const circles =
      s.x.length <= 18
        ? s.x
            .map(
              (x, k) =>
                `<circle cx="${sx(x).toFixed(1)}" cy="${sy(s.y[k] ?? 0).toFixed(1)}" r="2.6" fill="${color}" />`,
            )
            .join("")
        : "";
    return `<path d="${pts}" fill="none" stroke="${color}" stroke-width="2"${dash} />${circles}`;
  });

  const legendItems = model.series.slice(0, 6).map((s, idx) => {
    const color = TS_CHART_PALETTE[(s.colorIndex ?? idx) % TS_CHART_PALETTE.length];
    const lx = padL + (idx % 3) * 130;
    const ly = height - 8 - (idx >= 3 ? 11 : 0);
    return `<g transform="translate(${lx},${ly})"><line x1="0" y1="-3" x2="12" y2="-3" stroke="${color}" stroke-width="2"${s.dashed ? ' stroke-dasharray="4,2"' : ""}/><text x="15" y="0" fill="${tokens.textPrimary}" font-size="9.5">${escapeHtml(s.label)}</text></g>`;
  });

  return [
    `<svg class="scientific-svg ts-line-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(model.title)}" data-series-semantics="${escapeHtml(model.seriesSemantics ?? "numeric_verified")}">`,
    `<title>${escapeHtml(model.title)}</title>`,
    `<desc>${escapeHtml(model.description)}</desc>`,
    `<rect x="0" y="0" width="${width}" height="${height}" fill="${tokens.surface}" rx="6" />`,
    `<text x="${width / 2}" y="17" text-anchor="middle" fill="${tokens.textPrimary}" font-size="11.5" font-weight="600">${escapeHtml(model.title)}</text>`,
    ...gridLines,
    `<rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="none" stroke="${tokens.textSecondary}" stroke-width="1" />`,
    ...paths,
    `<text x="${padL + plotW / 2}" y="${padT + plotH + 28}" text-anchor="middle" fill="${tokens.textPrimary}" font-size="10.5">${escapeHtml(model.xLabel)}</text>`,
    `<text x="13" y="${padT + plotH / 2}" text-anchor="middle" fill="${tokens.textPrimary}" font-size="10.5" transform="rotate(-90 13 ${padT + plotH / 2})">${escapeHtml(model.yLabel)}</text>`,
    ...legendItems,
    `</svg>`,
  ].join("");
}

function weightToFillColor(w: number): string {
  const c = Math.min(1, Math.max(0, w));
  const r = Math.round(239 - c * (239 - 29));
  const g = Math.round(246 - c * (246 - 78));
  const b = Math.round(255 - c * (255 - 216));
  return `rgb(${r},${g},${b})`;
}

export function renderTsMeshSvg(
  mesh: TsMeshModel,
  options: { themeMode?: AccessibilityThemeMode } = {},
): string {
  const tokens = getThemeTokens(options.themeMode ?? "standard_aa");
  const width = 460;
  const height = 250;
  const padL = 52;
  const padR = 46;
  const padT = 30;
  const padB = 38;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  let xMin = Number.POSITIVE_INFINITY;
  let xMax = Number.NEGATIVE_INFINITY;
  let yMin = Number.POSITIVE_INFINITY;
  let yMax = Number.NEGATIVE_INFINITY;
  for (const [x, y] of mesh.nodes) {
    if (x < xMin) xMin = x;
    if (x > xMax) xMax = x;
    if (y < yMin) yMin = y;
    if (y > yMax) yMax = y;
  }
  if (!Number.isFinite(xMin) || xMax <= xMin) {
    xMin = -1;
    xMax = 1;
  }
  if (!Number.isFinite(yMin) || yMax <= yMin) {
    yMin = -1;
    yMax = 1;
  }
  const sx = (x: number): number => padL + ((x - xMin) / (xMax - xMin)) * plotW;
  const sy = (y: number): number => padT + (1 - (y - yMin) / (yMax - yMin)) * plotH;

  const polys = mesh.triangles.map(([i0, i1, i2]) => {
    const p0 = mesh.nodes[i0] ?? [0, 0];
    const p1 = mesh.nodes[i1] ?? [0, 0];
    const p2 = mesh.nodes[i2] ?? [0, 0];
    const wAvg =
      ((mesh.nodalRuleWeights[i0] ?? 0) +
        (mesh.nodalRuleWeights[i1] ?? 0) +
        (mesh.nodalRuleWeights[i2] ?? 0)) /
      3;
    const pts = `${sx(p0[0]).toFixed(1)},${sy(p0[1]).toFixed(1)} ${sx(p1[0]).toFixed(1)},${sy(p1[1]).toFixed(1)} ${sx(p2[0]).toFixed(1)},${sy(p2[1]).toFixed(1)}`;
    return `<polygon points="${pts}" fill="${weightToFillColor(wAvg)}" stroke="#334155" stroke-width="0.65" />`;
  });

  const dots =
    mesh.nodes.length <= 225
      ? mesh.nodes
          .map(
            ([x, y]) =>
              `<circle cx="${sx(x).toFixed(1)}" cy="${sy(y).toFixed(1)}" r="1.8" fill="#0F172A" />`,
          )
          .join("")
      : "";

  const title = `Malha 2D (${mesh.kind}) — superfície de h_${mesh.ruleIndex + 1}(${mesh.variables[0]}, ${mesh.variables[1]})`;
  return [
    `<svg class="scientific-svg ts-mesh-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}" data-series-semantics="numeric_verified">`,
    `<title>${escapeHtml(title)}</title>`,
    `<desc>Malha com ${mesh.nodes.length} nós e ${mesh.triangles.length} elementos simpliciais coloridos por h_${mesh.ruleIndex + 1} em [0, 1].</desc>`,
    `<rect x="0" y="0" width="${width}" height="${height}" fill="${tokens.surface}" rx="6" />`,
    `<text x="${width / 2}" y="17" text-anchor="middle" fill="${tokens.textPrimary}" font-size="11.5" font-weight="600">${escapeHtml(title)}</text>`,
    ...polys,
    dots,
    `<rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="none" stroke="${tokens.textSecondary}" stroke-width="1" />`,
    `<text x="${padL}" y="${padT + plotH + 14}" fill="${tokens.textSecondary}" font-size="10">${escapeHtml(formatNumericDisplay(clampDust(xMin), 3))}</text>`,
    `<text x="${padL + plotW}" y="${padT + plotH + 14}" text-anchor="end" fill="${tokens.textSecondary}" font-size="10">${escapeHtml(formatNumericDisplay(clampDust(xMax), 3))}</text>`,
    `<text x="${padL + plotW / 2}" y="${padT + plotH + 28}" text-anchor="middle" fill="${tokens.textPrimary}" font-size="10.5">${escapeHtml(mesh.variables[0] ?? "p1")}</text>`,
    `<text x="14" y="${padT + plotH / 2}" text-anchor="middle" fill="${tokens.textPrimary}" font-size="10.5" transform="rotate(-90 14 ${padT + plotH / 2})">${escapeHtml(mesh.variables[1] ?? "p2")}</text>`,
    // Barra de cor 0..1
    `<rect x="${width - 28}" y="${padT}" width="10" height="${plotH}" fill="${weightToFillColor(0.55)}" stroke="${tokens.border}" />`,
    `<text x="${width - 14}" y="${padT + 8}" fill="${tokens.textSecondary}" font-size="9">1</text>`,
    `<text x="${width - 14}" y="${padT + plotH}" fill="${tokens.textSecondary}" font-size="9">0</text>`,
    `</svg>`,
  ].join("");
}

function errorHeatColor(ratio: number): string {
  const t = Math.min(1, Math.max(0, ratio));
  const r = Math.round(240 - t * (240 - 190));
  const g = Math.round(249 - t * (249 - 18));
  const b = Math.round(255 - t * (255 - 60));
  return `rgb(${r},${g},${b})`;
}

export function renderTsHeatmapSvg(
  hm: TsHeatmapModel,
  options: { themeMode?: AccessibilityThemeMode } = {},
): string {
  const tokens = getThemeTokens(options.themeMode ?? "standard_aa");
  const width = 460;
  const height = 250;
  const padL = 52;
  const padR = 24;
  const padT = 32;
  const padB = 38;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const nx = Math.max(1, hm.xs.length);
  const ny = Math.max(1, hm.ys.length);
  const cw = plotW / nx;
  const ch = plotH / ny;
  const denom = hm.maxError > 1e-16 ? hm.maxError : 1;

  const rects: string[] = [];
  for (let j = 0; j < ny; j += 1) {
    for (let i = 0; i < nx; i += 1) {
      const val = hm.values[j]?.[i] ?? 0;
      const rx = padL + i * cw;
      const ry = padT + (ny - 1 - j) * ch;
      rects.push(
        `<rect x="${rx.toFixed(1)}" y="${ry.toFixed(1)}" width="${(cw + 0.4).toFixed(1)}" height="${(ch + 0.4).toFixed(1)}" fill="${errorHeatColor(val / denom)}" />`,
      );
    }
  }

  const title = `Erro fora da grade ${hm.metricLabel} (máx = ${hm.maxError.toExponential(2)})`;
  return [
    `<svg class="scientific-svg ts-heatmap-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}" data-series-semantics="numeric_verified">`,
    `<title>${escapeHtml(title)}</title>`,
    `<desc>Mapa de calor bidimensional de ${escapeHtml(hm.metricLabel)} sobre (${escapeHtml(hm.xLabel)}, ${escapeHtml(hm.yLabel)}).</desc>`,
    `<rect x="0" y="0" width="${width}" height="${height}" fill="${tokens.surface}" rx="6" />`,
    `<text x="${width / 2}" y="18" text-anchor="middle" fill="${tokens.textPrimary}" font-size="11" font-weight="600">${escapeHtml(title)}</text>`,
    ...rects,
    `<rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="none" stroke="${tokens.textSecondary}" stroke-width="1" />`,
    `<text x="${padL + plotW / 2}" y="${padT + plotH + 26}" text-anchor="middle" fill="${tokens.textPrimary}" font-size="10.5">${escapeHtml(hm.xLabel)}</text>`,
    `<text x="14" y="${padT + plotH / 2}" text-anchor="middle" fill="${tokens.textPrimary}" font-size="10.5" transform="rotate(-90 14 ${padT + plotH / 2})">${escapeHtml(hm.yLabel)}</text>`,
    `</svg>`,
  ].join("");
}

export function renderTsLineChartTableHtml(model: TsLineChartModel): string {
  if (model.series.length === 0) return `<p>Sem séries disponíveis.</p>`;
  const s0 = model.series[0];
  const stride = Math.max(1, Math.ceil(s0.x.length / 8));
  const indices: number[] = [];
  for (let i = 0; i < s0.x.length; i += stride) indices.push(i);
  if (indices[indices.length - 1] !== s0.x.length - 1) indices.push(s0.x.length - 1);

  const headCols = model.series.map((s) => `<th scope="col">${escapeHtml(s.label)}</th>`).join("");
  const rows = indices
    .map((idx) => {
      const cells = model.series
        .map((s) => `<td>${escapeHtml(formatNumericDisplay(s.y[idx] ?? 0, 4))}</td>`)
        .join("");
      return `<tr><th scope="row">${escapeHtml(formatNumericDisplay(s0.x[idx] ?? 0, 4))}</th>${cells}</tr>`;
    })
    .join("");
  return `<table class="accessible-data-table" aria-label="${escapeHtml(model.title)}"><thead><tr><th scope="col">${escapeHtml(model.xLabel)}</th>${headCols}</tr></thead><tbody>${rows}</tbody></table>`;
}
