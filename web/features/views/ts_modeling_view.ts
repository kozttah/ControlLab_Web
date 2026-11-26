/**
 * Bancada da Aba 6 — Obtenção de Modelos TS a partir de Sistemas LPV/qLPV
 * (`CL-TS-MOD-DIR-001 v1.1.0` Seções 1–7, `CL-UX-DIR-001 v1.0.0` e `ADR-014`).
 *
 * Arquitetura ergonômica de 4 Zonas:
 * - Zona 1: Seletor de Via (1: Setor | 2: TPMT | 3: FEMT), Presets didáticos + Novo Sistema
 *           Customizado + JSON qLPV, Recarga de Receita (`provenance.ts_derivation`),
 *           Promoção 1-clique ao Workspace Dock / Aba 7 (LMIs) e Exportação Python/MATLAB.
 * - Zona 2: Domínio de tempo (Contínuo / Discreto `dt`), Dimensões `(n, m, p)` + Canais
 *           Generalizados `(Bw, Dyw, Cz, Dzu, Dzw)`, Estados `x_i ∈ [x_min, x_max]` (medidos
 *           ou estimados) e Sinais Externos `w_ext ∈ [w_min, w_max]` + classificação inferida.
 * - Zona 3: Editor completo da representação qLPV:
 *   • Via 1 (Setor): Tabela editável de premissas `z_k = g_k(x, w_ext)`, cálculo híbrido global
 *     de `[z_min, z_max]`, override manual seguro, grade simbólica `A(z), B(z), C(z), D(z)` e
 *     auditoria instantânea de isolamento e multilinearidade.
 *   • Via 2 (TPMT): Grade simbólica direta `A(x,w), B(x,w), C(x,w), D(x,w)`, extração automática
 *     das variáveis não-lineares ativas `p = (p_1, ..., p_D)`, envelope de memória Wasm, tabela
 *     de discretização `G_d`, posto `R_d`, fecho convexo (`CNO`, `RNO-INO`, `SN-NN`, `MGK`) e
 *     reamostragem fina por dimensão, com escolha entre `HOSVD` e `HOOI`.
 *   • Via 3 (FEMT): Grade simbólica direta, discretização nodal `G_d` por dimensão ativa, SVD
 *     matricial global ótima (Eckart–Young), fecho convexo global e malha simplicial P1
 *     (`kuhn_delaunay` ou `delaunay`).
 * - Zona 4: Split 2-colunas — Zona 4A (Certificado de Fidelidade, Comparativo entre Vias na
 *           planta atual e Inspetor Interativo das Matrizes Vértices `A_r, B_r, C_r, D_r`) +
 *           Zona 4B (5 gráficos SVG acessíveis com seletores de eixo/regra e exportação SVG).
 *
 * Segurança R-21: zero avaliação dinâmica de código; todo texto dinâmico escapado via `escapeHtml`.
 */

import {
  supportsTsModeling,
  type ControlLabEngineClient,
  type TsModelingEngineClient,
} from "../../bridge/client.ts";
import {
  ControlLabBridgeError,
  generateUuid,
  isPlainObject,
  type RealTensor,
} from "../../bridge/protocol.ts";
import type {
  AnalyzedSectorPremise,
  DerivedTsFemtResult,
  DerivedTsKind,
  DerivedTsSectorResult,
  DerivedTsTpmtResult,
  FemtMeshKind,
  SectorPremiseSpec,
  TsDerivationLanguage,
  TsHull,
  TsModelingContext,
  TsRpcResponse,
} from "../../bridge/ts_modeling.ts";
import {
  escapeHtml,
  formatMatrixDisplay,
  formatNumericDisplay,
} from "../../app/accessibility.ts";
import type { ControlLabShell } from "../../app/shell.ts";
import {
  buildBasesChartModel,
  buildMembership1DChartModel,
  buildMesh2DModel,
  buildOffGridErrorHeatmap,
  buildScreeChartModel,
  GENERALIZED_CHANNEL_NAMES,
  renderTsHeatmapSvg,
  renderTsLineChartSvg,
  renderTsLineChartTableHtml,
  renderTsMeshSvg,
  type GeneralizedChannelName,
  type OffGridErrorHeatmapOptions,
  type TsDerivationResult,
} from "../../charts/ts_modeling_charts.ts";
import {
  auditSectorMatrices,
  expandSectorMatrixToDirect,
  inspectDirectQlpvMatrices,
  parseQlpvExpr,
} from "../ts_modeling/symbolic_qlpv_ast.ts";

export type TsVia = "sector" | "tpmt" | "femt";
export type TsPresetId =
  | "pendulum_16"
  | "pendulum_2d"
  | "nonseparable_benchmark"
  | "external_lpv";
export type TsMatrixFilter = "all" | "A" | "B" | "C" | "D" | "gen";

export const TS_VIAS: readonly TsVia[] = ["sector", "tpmt", "femt"];
export const TS_HULLS: readonly TsHull[] = ["CNO", "RNO-INO", "SN-NN", "MGK"];

export interface TsModelingExportModalPayload {
  title: string;
  filename: string;
  mimeType: string;
  content: string;
  offlineDesign?: boolean;
}

export interface TsModelingViewOptions {
  shell: ControlLabShell;
  client: ControlLabEngineClient;
  container: HTMLElement;
  onRequestRender?: () => void;
  onOpenExportModal?: (payload: TsModelingExportModalPayload, trigger: HTMLElement | null) => void;
  onRouteToLmi?: (refKey: string) => void;
}

export interface TsStateVarRow {
  name: string;
  min: number;
  max: number;
  unit: string;
  measured: boolean;
}

export interface TsExternalVarRow {
  name: string;
  min: number;
  max: number;
  measured: boolean;
}

export interface TsPremiseDraftRow {
  name: string;
  expression: string;
  measured: boolean;
  userMin: string;
  userMax: string;
  computedMin: number | null;
  computedMax: number | null;
  activeVariables: string[];
}

export interface TsAxisDraftConfig {
  gridPoints: number;
  rank: string;
  hull: TsHull;
  resamplePoints: string;
}

export interface TsSymbolicSystemMatrices {
  A: string[][];
  B: string[][];
  C: string[][];
  D: string[][];
  Bw: string[][];
  Dyw: string[][];
  Cz: string[][];
  Dzu: string[][];
  Dzw: string[][];
}

export interface TsQlpvDraft {
  modelId: string;
  presetSource: TsPresetId | "custom";
  timeDomain: "continuous" | "discrete";
  dt: number;
  n: number;
  m: number;
  p: number;
  enableGeneralized: boolean;
  nw: number;
  nz: number;
  states: TsStateVarRow[];
  externals: TsExternalVarRow[];
  premises: TsPremiseDraftRow[];
  sectorMatrices: TsSymbolicSystemMatrices;
  directMatrices: TsSymbolicSystemMatrices;
  axisSettings: Record<string, TsAxisDraftConfig>;
  tpmtDecomposition: "hosvd" | "hooi";
  svdTol: number;
  snTol: number;
  resampleMethod: "linear" | "pchip";
  hooiMaxIter: number;
  hooiConvTol: number;
  femtGlobalRank: string;
  femtHull: TsHull;
  femtMeshKind: FemtMeshKind;
  valPoints: number;
}

export interface TsPresetSpec {
  id: TsPresetId;
  label: string;
  description: string;
  defaultVia: TsVia;
  buildDraft: () => TsQlpvDraft;
}

function zeroMatrix(rows: number, cols: number, diagOne = false): string[][] {
  return Array.from({ length: rows }, (_, r) =>
    Array.from({ length: cols }, (__, c) => (diagOne && r === c ? "1" : "0")),
  );
}

function resizeMatrix(prev: string[][], rows: number, cols: number, fill = "0"): string[][] {
  return Array.from({ length: rows }, (_, r) =>
    Array.from({ length: cols }, (__, c) => prev[r]?.[c] ?? fill),
  );
}

function baseSymbolicMatrices(
  n: number,
  m: number,
  p: number,
  nw = 1,
  nz = 1,
): TsSymbolicSystemMatrices {
  return {
    A: zeroMatrix(n, n),
    B: zeroMatrix(n, m),
    C: zeroMatrix(p, n, true),
    D: zeroMatrix(p, m),
    Bw: zeroMatrix(n, nw),
    Dyw: zeroMatrix(p, nw),
    Cz: zeroMatrix(nz, n, true),
    Dzu: zeroMatrix(nz, m),
    Dzw: zeroMatrix(nz, nw),
  };
}

function defaultAxisConfig(gridPoints = 15): TsAxisDraftConfig {
  return {
    gridPoints,
    rank: "",
    hull: "CNO",
    resamplePoints: "",
  };
}

function makePendulum16Draft(): TsQlpvDraft {
  const premises: TsPremiseDraftRow[] = [
    {
      name: "z1",
      expression: "1 / (1.0 + 0.2 * sin(x3)^2)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x3"],
    },
    {
      name: "z2",
      expression: "cos(x3)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x3"],
    },
    {
      name: "z3",
      expression: "sinc_rad(x3)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x3"],
    },
    {
      name: "z4",
      expression: "x4 * sin(x3)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x3", "x4"],
    },
  ];
  const sec = baseSymbolicMatrices(4, 1, 2);
  sec.A = [
    ["0", "1", "0", "0"],
    ["0", "0", "-1.962 * z1 * z2 * z3", "0.1 * z1 * z4"],
    ["0", "0", "0", "1"],
    ["0", "0", "23.544 * z1 * z3", "-0.2 * z1 * z2 * z4"],
  ];
  sec.B = [["0"], ["z1"], ["0"], ["-2.0 * z1 * z2"]];
  sec.C = [
    ["1", "0", "0", "0"],
    ["0", "0", "1", "0"],
  ];
  sec.D = [["0"], ["0"]];

  const dir = baseSymbolicMatrices(4, 1, 2);
  dir.A = expandSectorMatrixToDirect(sec.A, premises);
  dir.B = expandSectorMatrixToDirect(sec.B, premises);
  dir.C = structuredClone(sec.C);
  dir.D = structuredClone(sec.D);

  return {
    modelId: "ts-pendulum-16",
    presetSource: "pendulum_16",
    timeDomain: "continuous",
    dt: 0.01,
    n: 4,
    m: 1,
    p: 2,
    enableGeneralized: false,
    nw: 1,
    nz: 1,
    states: [
      { name: "x1", min: -2.0, max: 2.0, unit: "m", measured: true },
      { name: "x2", min: -3.0, max: 3.0, unit: "m/s", measured: true },
      { name: "x3", min: -0.6, max: 0.6, unit: "rad", measured: true },
      { name: "x4", min: -2.0, max: 2.0, unit: "rad/s", measured: true },
    ],
    externals: [],
    premises,
    sectorMatrices: sec,
    directMatrices: dir,
    axisSettings: {
      x3: defaultAxisConfig(15),
      x4: defaultAxisConfig(15),
    },
    tpmtDecomposition: "hosvd",
    svdTol: 1e-6,
    snTol: 1e-6,
    resampleMethod: "linear",
    hooiMaxIter: 50,
    hooiConvTol: 1e-9,
    femtGlobalRank: "",
    femtHull: "CNO",
    femtMeshKind: "kuhn_delaunay",
    valPoints: 128,
  };
}

function makePendulum2DDraft(): TsQlpvDraft {
  const premises: TsPremiseDraftRow[] = [
    {
      name: "z1",
      expression: "sinc_rad(x1)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x1"],
    },
    {
      name: "z2",
      expression: "cos(x1)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x1"],
    },
  ];
  const sec = baseSymbolicMatrices(2, 1, 1);
  sec.A = [
    ["0", "1"],
    ["-9.81 * z1", "-0.4 - 0.15 * z2"],
  ];
  sec.B = [["0"], ["1.0 + 0.2 * z2"]];
  sec.C = [["1", "0"]];
  sec.D = [["0"]];

  const dir = baseSymbolicMatrices(2, 1, 1);
  dir.A = expandSectorMatrixToDirect(sec.A, premises);
  dir.B = expandSectorMatrixToDirect(sec.B, premises);
  dir.C = structuredClone(sec.C);
  dir.D = structuredClone(sec.D);

  return {
    modelId: "ts-pendulum-2d",
    presetSource: "pendulum_2d",
    timeDomain: "continuous",
    dt: 0.01,
    n: 2,
    m: 1,
    p: 1,
    enableGeneralized: false,
    nw: 1,
    nz: 1,
    states: [
      { name: "x1", min: -1.0, max: 1.0, unit: "rad", measured: true },
      { name: "x2", min: -2.5, max: 2.5, unit: "rad/s", measured: true },
    ],
    externals: [],
    premises,
    sectorMatrices: sec,
    directMatrices: dir,
    axisSettings: { x1: defaultAxisConfig(25) },
    tpmtDecomposition: "hosvd",
    svdTol: 1e-6,
    snTol: 1e-6,
    resampleMethod: "linear",
    hooiMaxIter: 50,
    hooiConvTol: 1e-9,
    femtGlobalRank: "",
    femtHull: "CNO",
    femtMeshKind: "kuhn_delaunay",
    valPoints: 128,
  };
}

function makeNonseparableBenchmarkDraft(): TsQlpvDraft {
  const premises: TsPremiseDraftRow[] = [
    {
      name: "z1",
      expression: "sin(x1 + x2)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x1", "x2"],
    },
    {
      name: "z2",
      expression: "cos(x1 - x2)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x1", "x2"],
    },
  ];
  const sec = baseSymbolicMatrices(2, 1, 1);
  sec.A = [
    ["-1.0 - 0.5 * z1", "0.3 * z2"],
    ["0.2 * z1", "-2.0 + 0.4 * z2"],
  ];
  sec.B = [["1.0"], ["0.5 + 0.2 * z1"]];
  sec.C = [["1", "0"]];
  sec.D = [["0"]];

  const dir = baseSymbolicMatrices(2, 1, 1);
  dir.A = expandSectorMatrixToDirect(sec.A, premises);
  dir.B = expandSectorMatrixToDirect(sec.B, premises);
  dir.C = structuredClone(sec.C);
  dir.D = structuredClone(sec.D);

  return {
    modelId: "ts-coupled-2d",
    presetSource: "nonseparable_benchmark",
    timeDomain: "continuous",
    dt: 0.01,
    n: 2,
    m: 1,
    p: 1,
    enableGeneralized: false,
    nw: 1,
    nz: 1,
    states: [
      { name: "x1", min: -1.2, max: 1.2, unit: "", measured: true },
      { name: "x2", min: -1.2, max: 1.2, unit: "", measured: true },
    ],
    externals: [],
    premises,
    sectorMatrices: sec,
    directMatrices: dir,
    axisSettings: {
      x1: defaultAxisConfig(13),
      x2: defaultAxisConfig(13),
    },
    tpmtDecomposition: "hosvd",
    svdTol: 1e-6,
    snTol: 1e-6,
    resampleMethod: "linear",
    hooiMaxIter: 50,
    hooiConvTol: 1e-9,
    femtGlobalRank: "",
    femtHull: "CNO",
    femtMeshKind: "delaunay",
    valPoints: 128,
  };
}

function makeExternalLpvDraft(): TsQlpvDraft {
  const premises: TsPremiseDraftRow[] = [
    {
      name: "z1",
      expression: "theta1",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["theta1"],
    },
    {
      name: "z2",
      expression: "tanh(x1)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x1"],
    },
  ];
  const sec = baseSymbolicMatrices(2, 1, 1);
  sec.A = [
    ["0", "1"],
    ["-2.0 * z1 - 0.5 * z2", "-1.2 * z1"],
  ];
  sec.B = [["0"], ["1.0 + 0.3 * z1"]];
  sec.C = [["1", "0"]];
  sec.D = [["0"]];

  const dir = baseSymbolicMatrices(2, 1, 1);
  dir.A = expandSectorMatrixToDirect(sec.A, premises);
  dir.B = expandSectorMatrixToDirect(sec.B, premises);
  dir.C = structuredClone(sec.C);
  dir.D = structuredClone(sec.D);

  return {
    modelId: "ts-lpv-external",
    presetSource: "external_lpv",
    timeDomain: "continuous",
    dt: 0.01,
    n: 2,
    m: 1,
    p: 1,
    enableGeneralized: false,
    nw: 1,
    nz: 1,
    states: [
      { name: "x1", min: -1.5, max: 1.5, unit: "m", measured: true },
      { name: "x2", min: -2.0, max: 2.0, unit: "m/s", measured: false },
    ],
    externals: [{ name: "theta1", min: 0.5, max: 1.5, measured: true }],
    premises,
    sectorMatrices: sec,
    directMatrices: dir,
    axisSettings: {
      x1: defaultAxisConfig(15),
      theta1: defaultAxisConfig(15),
    },
    tpmtDecomposition: "hosvd",
    svdTol: 1e-6,
    snTol: 1e-6,
    resampleMethod: "linear",
    hooiMaxIter: 50,
    hooiConvTol: 1e-9,
    femtGlobalRank: "",
    femtHull: "CNO",
    femtMeshKind: "kuhn_delaunay",
    valPoints: 128,
  };
}

export function makeBlankCustomDraft(): TsQlpvDraft {
  const premises: TsPremiseDraftRow[] = [
    {
      name: "z1",
      expression: "cos(x1)",
      measured: true,
      userMin: "",
      userMax: "",
      computedMin: null,
      computedMax: null,
      activeVariables: ["x1"],
    },
  ];
  const sec = baseSymbolicMatrices(2, 1, 1);
  sec.A = [
    ["0", "1"],
    ["-1.0 * z1", "-0.5"],
  ];
  sec.B = [["0"], ["1"]];
  sec.C = [["1", "0"]];
  sec.D = [["0"]];

  const dir = baseSymbolicMatrices(2, 1, 1);
  dir.A = [
    ["0", "1"],
    ["-1.0 * cos(x1)", "-0.5"],
  ];
  dir.B = [["0"], ["1"]];
  dir.C = [["1", "0"]];
  dir.D = [["0"]];

  return {
    modelId: "ts-custom-qlpv",
    presetSource: "custom",
    timeDomain: "continuous",
    dt: 0.01,
    n: 2,
    m: 1,
    p: 1,
    enableGeneralized: false,
    nw: 1,
    nz: 1,
    states: [
      { name: "x1", min: -1.0, max: 1.0, unit: "", measured: true },
      { name: "x2", min: -2.0, max: 2.0, unit: "", measured: true },
    ],
    externals: [],
    premises,
    sectorMatrices: sec,
    directMatrices: dir,
    axisSettings: { x1: defaultAxisConfig(15) },
    tpmtDecomposition: "hosvd",
    svdTol: 1e-6,
    snTol: 1e-6,
    resampleMethod: "linear",
    hooiMaxIter: 50,
    hooiConvTol: 1e-9,
    femtGlobalRank: "",
    femtHull: "CNO",
    femtMeshKind: "kuhn_delaunay",
    valPoints: 128,
  };
}

export const TS_PRESETS: Readonly<Record<TsPresetId, TsPresetSpec>> = {
  pendulum_16: {
    id: "pendulum_16",
    label: "Pêndulo Invertido sobre Carro (4 est. • 4 premissas / 16 regras)",
    description:
      "Planta mecânica qLPV clássica com 4 estados e 4 termos não-lineares z1..z4 (2⁴ = 16 vértices exatos no Setor). Edite livremente qualquer premissa, limite ou célula de A, B, C, D.",
    defaultVia: "sector",
    buildDraft: makePendulum16Draft,
  },
  pendulum_2d: {
    id: "pendulum_2d",
    label: "Pêndulo Mecânico Amortecido 2D (2 est. • sinc_rad & cos)",
    description:
      "Modelo compacto de 2 estados usando sinc_rad(x1) = sin(x1)/x1 suave na origem e cos(x1) (4 regras no Setor; 1 eixo ativo na TPMT/FEMT).",
    defaultVia: "sector",
    buildDraft: makePendulum2DDraft,
  },
  nonseparable_benchmark: {
    id: "nonseparable_benchmark",
    label: "Benchmark Acoplado 2D — sin(x1+x2) & cos(x1−x2) (FEMT vs TPMT)",
    description:
      "Não-linearidades acopladas entre x1 e x2 quebram a separabilidade modal: a FEMT (SVD global + simplices Delaunay) atinge exatidão nodal com estritamente menos regras que a TPMT.",
    defaultVia: "femt",
    buildDraft: makeNonseparableBenchmarkDraft,
  },
  external_lpv: {
    id: "external_lpv",
    label: "Planta LPV/qLPV com Sinal Externo θ₁(t) + Estado Não Medido",
    description:
      "Demonstra combinação de estados (x2 não medido) e parâmetro variante externo θ₁(t) ∈ [0.5, 1.5] medido em tempo real.",
    defaultVia: "sector",
    buildDraft: makeExternalLpvDraft,
  },
};

export function isTsPresetId(value: string): value is TsPresetId {
  return Object.hasOwn(TS_PRESETS, value);
}

/** Compatibilidade auxiliar para substituição simbólica baseada em AST (zero regex inseguro). */
export function substitutePremises(
  expr: string,
  premises: readonly SectorPremiseSpec[],
): string {
  const mapped = premises.map((p) => ({ name: p.name, expression: String(p.expression) }));
  return expandSectorMatrixToDirect([[expr]], mapped)[0]?.[0] ?? expr;
}

export interface TsFormParams {
  gridPoints: number;
  rank: number | null;
  hull: TsHull;
  decomposition: "hosvd" | "hooi";
  meshKind: FemtMeshKind;
  valPoints: number;
}

export const DEFAULT_TS_FORM_PARAMS: TsFormParams = {
  gridPoints: 15,
  rank: null,
  hull: "CNO",
  decomposition: "hosvd",
  meshKind: "kuhn_delaunay",
  valPoints: 128,
};

/**
 * Serializa de forma determinística todos os parâmetros do rascunho e a via ativa
 * que definem a derivação TS atual, para detectar edições pós-derivação (estado obsoleto).
 */
export function serializeDraftDerivationSignature(
  draft: TsQlpvDraft,
  activeMethod: TsVia,
): string {
  const sortedAxisKeys = Object.keys(draft.axisSettings).sort();
  const axisSettings: Record<string, TsAxisDraftConfig> = {};
  for (const key of sortedAxisKeys) {
    const cfg = draft.axisSettings[key];
    if (!cfg) continue;
    axisSettings[key] = {
      gridPoints: cfg.gridPoints,
      rank: cfg.rank.trim(),
      hull: cfg.hull,
      resamplePoints: cfg.resamplePoints.trim(),
    };
  }

  const pickMatrices = (m: TsSymbolicSystemMatrices): Record<string, string[][]> => ({
    A: m.A,
    B: m.B,
    C: m.C,
    D: m.D,
    ...(draft.enableGeneralized
      ? {
          Bw: m.Bw,
          Dyw: m.Dyw,
          Cz: m.Cz,
          Dzu: m.Dzu,
          Dzw: m.Dzw,
        }
      : {}),
  });

  return JSON.stringify({
    activeMethod,
    presetId: draft.presetSource,
    name: draft.modelId.trim(),
    timeDomain: draft.timeDomain,
    sampleTime: draft.timeDomain === "discrete" ? draft.dt : null,
    nStates: draft.n,
    nInputs: draft.m,
    nOutputs: draft.p,
    enableGeneralized: draft.enableGeneralized,
    nw: draft.enableGeneralized ? draft.nw : 0,
    nz: draft.enableGeneralized ? draft.nz : 0,
    stateBounds: draft.states.map((s) => ({
      name: s.name.trim(),
      min: s.min,
      max: s.max,
      unit: s.unit.trim(),
      measured: s.measured,
    })),
    externalBounds: draft.externals.map((e) => ({
      name: e.name.trim(),
      min: e.min,
      max: e.max,
      measured: e.measured,
    })),
    premises: draft.premises.map((p) => ({
      name: p.name.trim(),
      expression: p.expression,
      measured: p.measured,
      userMin: p.userMin.trim(),
      userMax: p.userMax.trim(),
    })),
    sectorMatrices: pickMatrices(draft.sectorMatrices),
    directMatrices: pickMatrices(draft.directMatrices),
    axisSettings,
    tpmtParams: {
      decomposition: draft.tpmtDecomposition,
      svdTol: draft.svdTol,
      snTol: draft.snTol,
      resampleMethod: draft.resampleMethod,
      hooiMaxIter: draft.hooiMaxIter,
      hooiConvTol: draft.hooiConvTol,
    },
    femtParams: {
      globalRank: draft.femtGlobalRank.trim(),
      hull: draft.femtHull,
      meshKind: draft.femtMeshKind,
      svdTol: draft.svdTol,
      snTol: draft.snTol,
    },
    valPoints: draft.valPoints,
  });
}

/** Constrói payload RPC canônico a partir de um rascunho completo `TsQlpvDraft`. */
export function buildTsPayloadFromDraft(
  draft: TsQlpvDraft,
  via: TsVia,
): Record<string, unknown> {
  const stateBounds: Record<string, [number, number]> = {};
  const measuredStates: Record<string, boolean> = {};
  const stateNames: string[] = [];
  const stateUnits: Record<string, string> = {};

  for (const st of draft.states) {
    const id = st.name.trim();
    if (!id) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Todo estado deve ter um identificador válido.");
    }
    if (!Number.isFinite(st.min) || !Number.isFinite(st.max) || st.max <= st.min) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Limites inválidos para o estado '${id}': exija x_max > x_min.`,
      );
    }
    stateBounds[id] = [st.min, st.max];
    measuredStates[id] = st.measured;
    stateNames.push(id);
    if (st.unit.trim()) stateUnits[id] = st.unit.trim();
  }

  const externalBounds: Record<string, [number, number]> = {};
  const measuredExternals: Record<string, boolean> = {};
  for (const ext of draft.externals) {
    const id = ext.name.trim();
    if (!id) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Todo sinal externo adicionado deve ter identificador válido.",
      );
    }
    if (Object.hasOwn(stateBounds, id)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `O sinal externo '${id}' colide com o nome de um estado.`,
      );
    }
    if (!Number.isFinite(ext.min) || !Number.isFinite(ext.max) || ext.max <= ext.min) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Limites inválidos para o sinal externo '${id}': exija max > min.`,
      );
    }
    externalBounds[id] = [ext.min, ext.max];
    measuredExternals[id] = ext.measured;
  }

  const dtVal =
    draft.timeDomain === "discrete"
      ? (() => {
          if (!Number.isFinite(draft.dt) || draft.dt <= 0) {
            throw new ControlLabBridgeError(
              "VALIDATION_ERROR",
              "No domínio discreto, informe o passo de amostragem dt > 0.",
            );
          }
          return draft.dt;
        })()
      : null;

  const mats = via === "sector" ? draft.sectorMatrices : draft.directMatrices;
  const genChannels = draft.enableGeneralized
    ? {
        Bw: structuredClone(mats.Bw),
        Dyw: structuredClone(mats.Dyw),
        Cz: structuredClone(mats.Cz),
        Dzu: structuredClone(mats.Dzu),
        Dzw: structuredClone(mats.Dzw),
      }
    : null;

  const basePayload: Record<string, unknown> = {
    state_bounds: stateBounds,
    ...(Object.keys(externalBounds).length > 0 ? { external_bounds: externalBounds } : {}),
    measured_states: measuredStates,
    ...(Object.keys(measuredExternals).length > 0 ? { measured_externals: measuredExternals } : {}),
    A_expr: structuredClone(mats.A),
    B_expr: structuredClone(mats.B),
    C_expr: structuredClone(mats.C),
    D_expr: structuredClone(mats.D),
    ...(genChannels ? { generalized_channels: genChannels } : {}),
    dt: dtVal,
    state_names: stateNames,
    input_names: Array.from({ length: draft.m }, (_, j) => `u${j + 1}`),
    output_names: Array.from({ length: draft.p }, (_, i) => `y${i + 1}`),
    ...(Object.keys(stateUnits).length > 0 ? { units: stateUnits } : {}),
    model_id: draft.modelId.trim() || `ts-${via}`,
    n_val_points: draft.valPoints,
  };

  if (via === "sector") {
    if (draft.premises.length === 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Defina ao menos 1 variável premissa z_k para a Via 1 (Não-Linearidade de Setor).",
      );
    }
    const premiseSpecs: SectorPremiseSpec[] = draft.premises.map((p) => {
      const name = p.name.trim();
      const expr = p.expression.trim();
      if (!name || !expr) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Toda variável premissa deve possuir identificador (ex.: z1) e expressão não vazia.",
        );
      }
      const hasMin = p.userMin.trim().length > 0;
      const hasMax = p.userMax.trim().length > 0;
      let userBounds: [number, number] | null = null;
      if (hasMin || hasMax) {
        const uLo = Number(p.userMin);
        const uHi = Number(p.userMax);
        if (!hasMin || !hasMax || !Number.isFinite(uLo) || !Number.isFinite(uHi) || uHi <= uLo) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Override manual de '${name}' requer limites finitos [z_min, z_max] com z_max > z_min.`,
          );
        }
        if (
          p.computedMin !== null &&
          p.computedMax !== null &&
          (uLo > p.computedMin + 1e-11 || uHi < p.computedMax - 1e-11)
        ) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Override manual [${uLo}, ${uHi}] em '${name}' estreita o intervalo real [${formatNumericDisplay(p.computedMin, 6)}, ${formatNumericDisplay(p.computedMax, 6)}] e violaria a não-negatividade de w_${name}(z).`,
          );
        }
        userBounds = [uLo, uHi];
      }
      return {
        name,
        expression: expr,
        measured: p.measured ? null : false,
        ...(userBounds ? { user_bounds: userBounds } : {}),
      };
    });
    return {
      ...basePayload,
      premises: premiseSpecs,
    };
  }

  const inspected = inspectDirectQlpvMatrices(
    {
      A: mats.A,
      B: mats.B,
      C: mats.C,
      D: mats.D,
      ...(genChannels ?? {}),
    },
    stateNames,
    Object.keys(externalBounds),
  );
  if (inspected.errors.length > 0) {
    throw new ControlLabBridgeError("VALIDATION_ERROR", inspected.errors[0]);
  }
  const activeVars = inspected.activeVariables;
  const gridMap: Record<string, number> = {};
  for (const v of activeVars) {
    const cfg = draft.axisSettings[v] ?? defaultAxisConfig(15);
    if (!Number.isInteger(cfg.gridPoints) || cfg.gridPoints < 3 || cfg.gridPoints > 201) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Pontos de discretização do eixo '${v}' devem ser inteiros entre 3 e 201.`,
      );
    }
    gridMap[v] = cfg.gridPoints;
  }

  if (via === "tpmt") {
    const hullMap: Record<string, TsHull> = {};
    const rankMap: Record<string, number> = {};
    const resampleMap: Record<string, number> = {};
    let hasAnyRank = false;
    let hasAnyResample = false;

    for (const v of activeVars) {
      const cfg = draft.axisSettings[v] ?? defaultAxisConfig(15);
      hullMap[v] = cfg.hull;
      if (cfg.rank.trim().length > 0) {
        const rNum = Number(cfg.rank);
        if (!Number.isInteger(rNum) || rNum < 1 || rNum > 64) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Posto manual R_d do eixo '${v}' deve ser inteiro >= 1 (ou vazio para automático).`,
          );
        }
        rankMap[v] = rNum;
        hasAnyRank = true;
      }
      if (cfg.resamplePoints.trim().length > 0) {
        const rsNum = Number(cfg.resamplePoints);
        if (!Number.isInteger(rsNum) || rsNum <= cfg.gridPoints || rsNum > 1001) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Reamostragem fina de '${v}' deve ser inteiro maior que G_d (${cfg.gridPoints}) e <= 1001.`,
          );
        }
        resampleMap[v] = rsNum;
        hasAnyResample = true;
      }
    }

    // Se o usuário especificou posto apenas em alguns eixos, só envia `ranks` se todos os eixos tiverem posto
    // ou quando D=1, caso contrário usa o escalar/mapa completo conforme contrato Python
    const allAxesHaveRank = activeVars.length > 0 && activeVars.every((v) => Object.hasOwn(rankMap, v));
    if (hasAnyRank && !allAxesHaveRank) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Na TPMT, ao definir postos manuais R_d, preencha R_d para todos os eixos ativos (ou deixe todos vazios para seleção automática via svd_tol).",
      );
    }
    const allAxesHaveResample =
      activeVars.length > 0 && activeVars.every((v) => Object.hasOwn(resampleMap, v));
    if (hasAnyResample && !allAxesHaveResample) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Ao habilitar reamostragem fina, informe o número de pontos finos para todos os eixos ativos (ou deixe vazios).",
      );
    }

    return {
      ...basePayload,
      grid_points: activeVars.length > 0 ? gridMap : 15,
      decomposition: draft.tpmtDecomposition,
      svd_tol: draft.svdTol,
      sn_tol: draft.snTol,
      hull_type: activeVars.length > 0 ? hullMap : "CNO",
      hooi_max_iter: draft.hooiMaxIter,
      hooi_conv_tol: draft.hooiConvTol,
      ...(allAxesHaveRank ? { ranks: rankMap } : {}),
      ...(allAxesHaveResample
        ? { resample_points: resampleMap, resample_method: draft.resampleMethod }
        : {}),
    };
  }

  let femtRank: number | null = null;
  if (draft.femtGlobalRank.trim().length > 0) {
    const r = Number(draft.femtGlobalRank);
    if (!Number.isInteger(r) || r < 1 || r > 128) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Posto global R da FEMT deve ser inteiro >= 1 (ou vazio para automático via Eckart–Young).",
      );
    }
    femtRank = r;
  }

  return {
    ...basePayload,
    grid_points: activeVars.length > 0 ? gridMap : 15,
    svd_tol: draft.svdTol,
    sn_tol: draft.snTol,
    hull_type: draft.femtHull,
    mesh_kind: draft.femtMeshKind,
    ...(femtRank !== null ? { rank: femtRank } : {}),
  };
}

/** Atalho compatível com testes unitários rápidos a partir de preset + `TsFormParams`. */
export function buildTsPayload(
  presetId: TsPresetId,
  via: TsVia,
  params: TsFormParams = DEFAULT_TS_FORM_PARAMS,
): Record<string, unknown> {
  const draft = TS_PRESETS[presetId].buildDraft();
  draft.modelId = `ts-${presetId}-${via}`;
  draft.valPoints = params.valPoints;
  draft.tpmtDecomposition = params.decomposition;
  draft.femtHull = params.hull;
  draft.femtMeshKind = params.meshKind;
  if (params.rank !== null) {
    draft.femtGlobalRank = String(params.rank);
  }
  for (const key of Object.keys(draft.axisSettings)) {
    draft.axisSettings[key] = {
      gridPoints: params.gridPoints,
      rank: params.rank !== null ? String(params.rank) : "",
      hull: params.hull,
      resamplePoints: "",
    };
  }
  return buildTsPayloadFromDraft(draft, via);
}

export interface TsDerivationRecipe {
  via: TsVia;
  preset: string | null;
  draft: TsQlpvDraft | null;
  payload: Record<string, unknown>;
}

function viaFromMethod(method: unknown): TsVia | null {
  if (method === "sector_nonlinearity" || method === "sector") return "sector";
  if (method === "tpmt") return "tpmt";
  if (method === "femt") return "femt";
  return null;
}

function toStringMatrix(raw: unknown): string[][] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const out: string[][] = [];
  for (const row of raw) {
    if (!Array.isArray(row) || row.length === 0) return null;
    out.push(row.map((c) => String(c)));
  }
  return out;
}

/**
 * Reconstrói a receita completa e o rascunho editável `TsQlpvDraft` a partir de
 * `provenance.ts_derivation` nativo do backend Python (ou de `recipe.draft` salvo pela UI).
 */
export function extractRecipeFromProvenance(
  dto: Record<string, unknown>,
): TsDerivationRecipe | null {
  const prov = dto.provenance;
  if (!isPlainObject(prov) || !isPlainObject(prov.ts_derivation)) return null;
  const deriv = prov.ts_derivation;

  const rec = deriv.recipe;
  const via =
    (isPlainObject(rec) ? viaFromMethod(rec.via) : null) ?? viaFromMethod(deriv.method);
  if (!via) return null;

  if (isPlainObject(rec) && isPlainObject(rec.draft)) {
    return {
      via,
      preset: typeof rec.preset === "string" ? rec.preset : null,
      draft: structuredClone(rec.draft) as unknown as TsQlpvDraft,
      payload: isPlainObject(rec.payload) ? structuredClone(rec.payload) : {},
    };
  }

  // Reconstrução pura a partir dos metadados científicos nativos do Python (`provenance.ts_derivation`)
  const A = toStringMatrix(deriv.A_expr);
  const B = toStringMatrix(deriv.B_expr);
  const C = toStringMatrix(deriv.C_expr);
  const D = toStringMatrix(deriv.D_expr);
  if (!A || !B) {
    return {
      via,
      preset: isPlainObject(rec) && typeof rec.preset === "string" ? rec.preset : null,
      draft: null,
      payload: isPlainObject(rec) && isPlainObject(rec.payload) ? structuredClone(rec.payload) : {},
    };
  }

  const n = A.length;
  const m = B[0]?.length ?? 1;
  const p = C?.length ?? 1;
  const blank = makeBlankCustomDraft();
  blank.modelId = typeof dto.id === "string" ? dto.id : `ts-reloaded-${via}`;
  blank.presetSource = "custom";
  blank.timeDomain = typeof dto.dt === "number" && dto.dt > 0 ? "discrete" : "continuous";
  blank.dt = typeof dto.dt === "number" && dto.dt > 0 ? dto.dt : 0.01;
  blank.n = n;
  blank.m = m;
  blank.p = p;

  const stateNames = Array.isArray(dto.state_names)
    ? dto.state_names.map((s) => String(s))
    : Array.from({ length: n }, (_, i) => `x${i + 1}`);
  const sb = isPlainObject(deriv.state_bounds) ? deriv.state_bounds : {};
  const pa = isPlainObject(dto.premise_availability) ? dto.premise_availability : {};
  const unmeasuredSet = new Set(
    Array.isArray(pa.unmeasured_premises) ? pa.unmeasured_premises.map((x) => String(x)) : [],
  );
  const unitsObj = isPlainObject(dto.units) ? dto.units : {};

  blank.states = stateNames.map((sName) => {
    const b = sb[sName];
    const lo = Array.isArray(b) && b.length === 2 ? Number(b[0]) : -1;
    const hi = Array.isArray(b) && b.length === 2 ? Number(b[1]) : 1;
    return {
      name: sName,
      min: lo,
      max: hi,
      unit: typeof unitsObj[sName] === "string" ? String(unitsObj[sName]) : "",
      measured: !unmeasuredSet.has(sName),
    };
  });

  const eb = isPlainObject(deriv.external_bounds) ? deriv.external_bounds : {};
  blank.externals = Object.entries(eb).map(([eName, b]) => ({
    name: eName,
    min: Array.isArray(b) && b.length === 2 ? Number(b[0]) : -1,
    max: Array.isArray(b) && b.length === 2 ? Number(b[1]) : 1,
    measured: !unmeasuredSet.has(eName),
  }));

  const genProv = isPlainObject(prov.generalized_channels) ? prov.generalized_channels : null;
  const genExpr = genProv && isPlainObject(genProv.expressions) ? genProv.expressions : null;
  const mats = baseSymbolicMatrices(n, m, p);
  mats.A = A;
  mats.B = B;
  mats.C = C ?? zeroMatrix(p, n, true);
  mats.D = D ?? zeroMatrix(p, m);
  if (genExpr) {
    const Bw = toStringMatrix(genExpr.Bw);
    const Dyw = toStringMatrix(genExpr.Dyw);
    const Cz = toStringMatrix(genExpr.Cz);
    const Dzu = toStringMatrix(genExpr.Dzu);
    const Dzw = toStringMatrix(genExpr.Dzw);
    blank.enableGeneralized = true;
    blank.nw = Bw?.[0]?.length ?? Dyw?.[0]?.length ?? 1;
    blank.nz = Cz?.length ?? Dzu?.length ?? 1;
    mats.Bw = Bw ?? zeroMatrix(n, blank.nw);
    mats.Dyw = Dyw ?? zeroMatrix(p, blank.nw);
    mats.Cz = Cz ?? zeroMatrix(blank.nz, n, true);
    mats.Dzu = Dzu ?? zeroMatrix(blank.nz, m);
    mats.Dzw = Dzw ?? zeroMatrix(blank.nz, blank.nw);
  }

  if (via === "sector" && Array.isArray(deriv.premises)) {
    blank.premises = deriv.premises
      .filter((pr): pr is Record<string, unknown> => isPlainObject(pr))
      .map((pr) => ({
        name: String(pr.name ?? "z1"),
        expression: String(pr.expression ?? "0"),
        measured: pr.measured !== false,
        userMin: "",
        userMax: "",
        computedMin: typeof pr.min === "number" ? pr.min : null,
        computedMax: typeof pr.max === "number" ? pr.max : null,
        activeVariables: [],
      }));
    blank.sectorMatrices = mats;
    blank.directMatrices = {
      ...structuredClone(mats),
      A: expandSectorMatrixToDirect(mats.A, blank.premises),
      B: expandSectorMatrixToDirect(mats.B, blank.premises),
      C: expandSectorMatrixToDirect(mats.C, blank.premises),
      D: expandSectorMatrixToDirect(mats.D, blank.premises),
    };
  } else {
    blank.directMatrices = mats;
    blank.sectorMatrices = structuredClone(mats);
    const activeVars = Array.isArray(deriv.active_variables)
      ? deriv.active_variables.map((v) => String(v))
      : [];
    const gSizes = Array.isArray(deriv.grid_points) ? deriv.grid_points : [];
    const hullTypes = Array.isArray(deriv.hull_types) ? deriv.hull_types : [];
    const axisRanks = Array.isArray(deriv.axis_ranks) ? deriv.axis_ranks : [];
    blank.axisSettings = {};
    activeVars.forEach((v, idx) => {
      const hRaw = String(hullTypes[idx] ?? deriv.hull_type ?? "CNO");
      const hull: TsHull = (TS_HULLS as readonly string[]).includes(hRaw) ? (hRaw as TsHull) : "CNO";
      blank.axisSettings[v] = {
        gridPoints: typeof gSizes[idx] === "number" ? Number(gSizes[idx]) : 15,
        rank: typeof axisRanks[idx] === "number" ? String(axisRanks[idx]) : "",
        hull,
        resamplePoints: "",
      };
    });
    if (deriv.decomposition === "hooi") blank.tpmtDecomposition = "hooi";
    if (typeof deriv.svd_tol === "number") blank.svdTol = deriv.svd_tol;
    if (via === "femt") {
      if (deriv.mesh_kind === "delaunay") blank.femtMeshKind = "delaunay";
      const hRaw = String(deriv.hull_type ?? "CNO");
      if ((TS_HULLS as readonly string[]).includes(hRaw)) blank.femtHull = hRaw as TsHull;
      if (typeof deriv.svd_rank === "number") blank.femtGlobalRank = String(deriv.svd_rank);
    }
  }

  return {
    via,
    preset: null,
    draft: blank,
    payload: {},
  };
}

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function unpackTensor(t: RealTensor): number[][] {
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

const VIA_LABELS: Record<TsVia, string> = {
  sector: "Via 1 — Não-Linearidade de Setor (Exata, 2ⁿⁿ regras)",
  tpmt: "Via 2 — Produto Tensorial TPMT (HOSVD / HOOI + Bases 1D)",
  femt: "Via 3 — Elementos Finitos FEMT (SVD Global + Simplices P₁)",
};

const VIA_SHORT_LABELS: Record<TsVia, string> = {
  sector: "Via 1: Setor (2ⁿⁿ)",
  tpmt: "Via 2: TPMT (HOSVD/HOOI)",
  femt: "Via 3: FEMT (SVD + Delaunay)",
};

function chartCardHtml(
  slotId: string,
  title: string,
  tableId: string,
  exportKey: string,
): string {
  return [
    `<div class="chart-card ts-chart-card">`,
    `<div class="ts-chart-card-header">`,
    `<h5>${escapeHtml(title)}</h5>`,
    `<button type="button" class="touch-control btn-subtle btn-small" data-action="ts-export-svg" data-chart-slot="${slotId}" data-chart-key="${exportKey}">[SVG]</button>`,
    `</div>`,
    `<div id="${slotId}" class="chart-container" aria-live="polite"><p>Execute a derivação para visualizar o gráfico.</p></div>`,
    `<details><summary>Tabela acessível — ${escapeHtml(title)}</summary><div id="${tableId}"></div></details>`,
    `</div>`,
  ].join("");
}

export function renderTsModelingViewHtml(): string {
  const presetOpts = [
    ...(Object.values(TS_PRESETS) as TsPresetSpec[]).map(
      (p) => `<option value="${p.id}">${escapeHtml(p.label)}</option>`,
    ),
    `<option value="custom">Sistema qLPV Customizado (Edição Livre)</option>`,
  ].join("");

  const viaOpts = TS_VIAS.map(
    (v) => `<option value="${v}">${escapeHtml(VIA_LABELS[v])}</option>`,
  ).join("");

  const hullOpts = TS_HULLS.map((h) => `<option value="${h}">${escapeHtml(h)}</option>`).join("");

  return [
    `<section id="ts-modeling-workspace-panel" class="panel-card workspace-section" aria-label="Obtenção de Modelos TS (Setor, TPMT e FEMT)" hidden>`,
    `<div class="ts-header-row">`,
    `<div>`,
    `<h3>Obtenção de Modelos Fuzzy Takagi–Sugeno a partir de Sistemas LPV/qLPV</h3>`,
    `<p class="dock-item-summary">Descreva um sistema LPV/qLPV simbólico e obtenha automaticamente sua representação politópica convexa <code>TSStateSpace</code> via Não-Linearidade de Setor, Produto Tensorial (TPMT) ou Elementos Finitos Simpliciais (FEMT).</p>`,
    `</div>`,
    `</div>`,

    `<ol id="ts-guided-steps" class="ts-step-pills" aria-label="Etapas guiadas de obtenção do modelo TS">`,
    `<li id="ts-step-1" data-step="domain"><span class="ts-step-badge">1</span><span>Domínio Ω &amp; Estados</span></li>`,
    `<li id="ts-step-2" data-step="qlpv"><span class="ts-step-badge">2</span><span>Matrizes qLPV &amp; Via</span></li>`,
    `<li id="ts-step-3" data-step="derive"><span class="ts-step-badge">3</span><span>Certificado &amp; Gráficos</span></li>`,
    `<li id="ts-step-4" data-step="register"><span class="ts-step-badge">4</span><span>Workspace &amp; LMIs</span></li>`,
    `</ol>`,

    /* ==================== ZONA 1: BARRA DE MÉTODO, EXEMPLOS & PROMOÇÃO ==================== */
    `<div id="ts-zone-1-toolbar" class="subcard ts-zone-card">`,
    `<div class="ts-via-bar" role="group" aria-label="Escolha o caminho de obtenção do modelo TS">`,
    `<button type="button" id="btn-ts-via-sector" class="touch-control btn-secondary ts-via-pill" data-via-btn="sector" aria-pressed="true">${escapeHtml(VIA_SHORT_LABELS.sector)}</button>`,
    `<button type="button" id="btn-ts-via-tpmt" class="touch-control btn-secondary ts-via-pill" data-via-btn="tpmt" aria-pressed="false">${escapeHtml(VIA_SHORT_LABELS.tpmt)}</button>`,
    `<button type="button" id="btn-ts-via-femt" class="touch-control btn-secondary ts-via-pill" data-via-btn="femt" aria-pressed="false">${escapeHtml(VIA_SHORT_LABELS.femt)}</button>`,
    `<label for="ts-via-select" class="sr-only">Via de obtenção TS</label>`,
    `<select id="ts-via-select" class="touch-control ts-via-select-compact" aria-label="Via de obtenção TS">${viaOpts}</select>`,
    `</div>`,

    `<div class="ts-toolbar-row">`,
    `<div class="tool-field ts-grow-field">`,
    `<label for="ts-preset-select">Exemplo didático / Ponto de partida</label>`,
    `<select id="ts-preset-select" class="touch-control" aria-label="Preset didático TS">${presetOpts}</select>`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="ts-model-id-input">ID do Modelo TS</label>`,
    `<input type="text" id="ts-model-id-input" class="touch-control ts-mono-input" value="ts-pendulum-16" aria-label="Identificador do modelo TS" />`,
    `</div>`,
    `<button type="button" id="btn-ts-new-custom" class="touch-control btn-secondary" data-action="ts-new-custom">Limpar / Novo Sistema</button>`,
    `<button type="button" id="btn-ts-toggle-json" class="touch-control btn-subtle" data-action="ts-toggle-json">JSON qLPV…</button>`,
    `</div>`,

    `<p id="ts-preset-description" class="dock-item-summary ts-preset-desc"></p>`,

    `<div id="ts-json-drawer" class="subcard ts-json-drawer" hidden>`,
    `<label for="ts-qlpv-json-textarea"><strong>Especificação qLPV em JSON</strong> (importe ou copie estados, premissas e matrizes simbólicas):</label>`,
    `<textarea id="ts-qlpv-json-textarea" class="ts-json-textarea" rows="7" spellcheck="false" aria-label="JSON da especificação qLPV"></textarea>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-ts-apply-json" class="touch-control btn-primary" data-action="ts-apply-json">Aplicar JSON ao Editor</button>`,
    `<button type="button" id="btn-ts-refresh-json" class="touch-control btn-secondary" data-action="ts-refresh-json">Atualizar do Editor</button>`,
    `</div>`,
    `</div>`,

    `<div class="panel-actions ts-primary-actions">`,
    `<button type="button" id="btn-ts-derive" class="touch-control btn-primary" data-action="ts-derive">Validar &amp; Gerar Modelo TS</button>`,
    `<button type="button" id="btn-ts-compare" class="touch-control btn-secondary" data-action="ts-compare">Comparar Vias na Planta Atual</button>`,
    `<button type="button" id="btn-ts-register" class="touch-control btn-secondary" data-action="ts-register" disabled aria-disabled="true">Registrar no Workspace</button>`,
    `<button type="button" id="btn-ts-register-open-lmi" class="touch-control btn-primary" data-action="ts-register-open-lmi" disabled aria-disabled="true">Registrar e Abrir em LMIs →</button>`,
    `<button type="button" id="btn-ts-export-python" class="touch-control btn-secondary" data-action="ts-export-python" disabled aria-disabled="true">Exportar Script Python</button>`,
    `<button type="button" id="btn-ts-export-matlab" class="touch-control btn-secondary" data-action="ts-export-matlab" disabled aria-disabled="true">Exportar Script MATLAB</button>`,
    `</div>`,
    `<div id="ts-stale-banner" class="ts-diagnostic-banner is-warn" role="alert" aria-live="assertive" hidden></div>`,

    `<div class="panel-actions ts-recipe-bar">`,
    `<label for="ts-recipe-select">Recarregar receita de modelo TS do Workspace:</label>`,
    `<select id="ts-recipe-select" class="touch-control" aria-label="Receita de derivação registrada"></select>`,
    `<button type="button" id="btn-ts-reload-recipe" class="touch-control btn-secondary" data-action="ts-reload-recipe" disabled aria-disabled="true">Recarregar Receita</button>`,
    `</div>`,
    `</div>`,

    /* ==================== ZONA 2: VARIÁVEIS, DOMÍNIO COMPACTO Ω & CANAIS ==================== */
    `<div id="ts-zone-2-domain" class="subcard ts-zone-card">`,
    `<div class="ts-zone-title-row">`,
    `<h4>Zona 2 — Variáveis do Sistema, Domínio Compacto Ω e Estrutura de Canais</h4>`,
    `<span id="ts-inferred-kind-badge" class="ts-kind-badge">ts_measured • Premissas medidas</span>`,
    `</div>`,

    `<div class="ts-dims-toolbar">`,
    `<div class="tool-field">`,
    `<label for="ts-time-domain-select">Domínio de Tempo</label>`,
    `<select id="ts-time-domain-select" class="touch-control" aria-label="Domínio de tempo">`,
    `<option value="continuous">Contínuo ẋ(t) = A(·)x + B(·)u</option>`,
    `<option value="discrete">Discreto x[k+1] = A(·)x[k] + B(·)u[k]</option>`,
    `</select>`,
    `</div>`,
    `<div id="ts-dt-field-wrap" class="tool-field" hidden>`,
    `<label for="ts-dt-input">Passo dt (s)</label>`,
    `<input type="number" id="ts-dt-input" class="touch-control id-param-input" min="0.0001" step="0.005" value="0.01" aria-label="Passo de amostragem dt" />`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="ts-dim-n">Estados n</label>`,
    `<input type="number" id="ts-dim-n" class="touch-control id-param-input" min="1" max="12" step="1" value="4" aria-label="Número de estados n" />`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="ts-dim-m">Entradas m</label>`,
    `<input type="number" id="ts-dim-m" class="touch-control id-param-input" min="1" max="8" step="1" value="1" aria-label="Número de entradas m" />`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="ts-dim-p">Saídas p</label>`,
    `<input type="number" id="ts-dim-p" class="touch-control id-param-input" min="1" max="8" step="1" value="2" aria-label="Número de saídas p" />`,
    `</div>`,
    `<label class="lmi-check-label ts-gen-toggle-label">`,
    `<input type="checkbox" id="ts-enable-gen-channels" />`,
    `<span>Planta Generalizada (Bw, Dyw, Cz, Dzu, Dzw)</span>`,
    `</label>`,
    `<div id="ts-gen-dims-wrap" class="ts-gen-dims-inline" hidden>`,
    `<div class="tool-field"><label for="ts-dim-nw">Perturb. n_w</label><input type="number" id="ts-dim-nw" class="touch-control id-param-input" min="1" max="6" step="1" value="1" /></div>`,
    `<div class="tool-field"><label for="ts-dim-nz">Desemp. n_z</label><input type="number" id="ts-dim-nz" class="touch-control id-param-input" min="1" max="6" step="1" value="1" /></div>`,
    `</div>`,
    `</div>`,

    `<div class="ts-domain-split">`,
    `<div class="subcard ts-bounds-card">`,
    `<div class="ts-subcard-header">`,
    `<h5>Estados x_i e Limites Compactos [x_min, x_max]</h5>`,
    `</div>`,
    `<div id="ts-states-slot"></div>`,
    `</div>`,
    `<div class="subcard ts-bounds-card">`,
    `<div class="ts-subcard-header">`,
    `<h5>Sinais Externos / Parâmetros Variantes w_ext (Opcional)</h5>`,
    `<button type="button" id="btn-ts-add-external" class="touch-control btn-secondary btn-small" data-action="ts-add-external">+ Adicionar sinal externo</button>`,
    `</div>`,
    `<div id="ts-externals-slot"></div>`,
    `</div>`,
    `</div>`,
    `</div>`,

    /* ==================== ZONA 3: ESPECIFICAÇÃO qLPV & PARAMETRIZAÇÃO ==================== */
    `<div id="ts-zone-3-qlpv" class="subcard ts-zone-card">`,
    `<h4>Zona 3 — Descrição Simbólica qLPV e Parametrização da Transformação</h4>`,
    `<div class="ts-syntax-hint" role="note">`,
    `<strong>Gramática simbólica segura (zero eval):</strong> operadores <code>+ - * / ^</code>, constantes <code>pi, e</code>, funções <code>sin, cos, tan, asin, acos, atan, sinh, cosh, tanh, exp, log, sqrt, abs, sign</code> e singularidades removíveis suaves <code>sinc_rad(u)</code> (= sin(u)/u com sinc_rad(0)=1) e <code>cos1m_div_u(u)</code>.`,
    `</div>`,

    /* --- Bloco Exclusivo Via 1: Variáveis Premissas z_k --- */
    `<div id="ts-sector-step-1a" class="subcard ts-pathway-card" data-via-only="sector">`,
    `<div class="ts-subcard-header">`,
    `<div>`,
    `<h5>Passo 1A — Variáveis Premissas z_k = g_k(x, w_ext) e Extremos Globais [z_min, z_max]</h5>`,
    `<p class="dock-item-summary">Defina cada não-linearidade extraída das matrizes. O motor híbrido (Aritmética Intervalar SUE + Malha Vetorizada + L-BFGS-B/Brent) encontra os extremos globais sobre Ω.</p>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<span id="ts-sector-rule-counter" class="ts-rule-pill">4 premissas ⇒ 16 regras</span>`,
    `<button type="button" id="btn-ts-add-premise" class="touch-control btn-secondary btn-small" data-action="ts-add-premise">+ Adicionar premissa z_k</button>`,
    `<button type="button" id="btn-ts-analyze" class="touch-control btn-primary btn-small" data-action="ts-analyze">Calcular Extremos [z_min, z_max]</button>`,
    `</div>`,
    `</div>`,
    `<div id="ts-premises-slot"></div>`,
    `</div>`,

    /* --- Editor de Matrizes Simbólicas A, B, C, D (+ Canais Gen.) --- */
    `<div class="subcard ts-matrices-card">`,
    `<div class="ts-subcard-header">`,
    `<div>`,
    `<h5 id="ts-matrices-heading">Passo 1B — Matrizes do Sistema em Espaço de Estados A(z), B(z), C(z), D(z)</h5>`,
    `<p id="ts-matrices-subtitle" class="dock-item-summary">Na Via 1 (Setor), escreva as entradas de forma afim/multilinear usando as variáveis premissas z_k declaradas acima.</p>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-ts-expand-to-direct" class="touch-control btn-secondary btn-small" data-via-only="sector" data-action="ts-expand-to-direct">Copiar S(z) → S(x,w) p/ TPMT &amp; FEMT</button>`,
    `</div>`,
    `</div>`,

    `<div class="ts-matrix-filter-bar" role="group" aria-label="Filtro de matrizes do sistema">`,
    `<button type="button" class="touch-control btn-subtle btn-small" data-matrix-filter="all" aria-pressed="true">Todas (A, B, C, D)</button>`,
    `<button type="button" class="touch-control btn-subtle btn-small" data-matrix-filter="A" aria-pressed="false">A</button>`,
    `<button type="button" class="touch-control btn-subtle btn-small" data-matrix-filter="B" aria-pressed="false">B</button>`,
    `<button type="button" class="touch-control btn-subtle btn-small" data-matrix-filter="C" aria-pressed="false">C</button>`,
    `<button type="button" class="touch-control btn-subtle btn-small" data-matrix-filter="D" aria-pressed="false">D</button>`,
    `<button type="button" id="btn-ts-filter-gen" class="touch-control btn-subtle btn-small" data-matrix-filter="gen" aria-pressed="false" hidden>Generalizadas (Bw, Cz…)</button>`,
    `</div>`,

    `<div id="ts-sector-affinity-banner" class="ts-diagnostic-banner" data-via-only="sector" role="status" aria-live="polite"></div>`,
    `<div id="ts-active-vars-bar" class="ts-diagnostic-banner" data-via-only="tpmt femt" role="status" aria-live="polite"></div>`,

    `<div id="ts-symbolic-matrices-slot" class="ts-matrices-grid"></div>`,
    `</div>`,

    /* --- Passo 2B (TPMT) e Passo 3B (FEMT): Discretização por Eixo e Fecho Convexo --- */
    `<div id="ts-sampled-config-card" class="subcard ts-pathway-card" data-via-only="tpmt femt">`,
    `<h5 id="ts-sampled-step-heading">Discretização por Dimensão Ativa e Manipulação do Fecho Convexo</h5>`,
    `<div id="ts-per-axis-slot"></div>`,

    `<div id="ts-params" class="ts-params-grid">`,
    `<div class="tool-field" data-via-only="tpmt">`,
    `<label for="ts-decomp-select">Decomposição Tensorial</label>`,
    `<select id="ts-decomp-select" class="touch-control" aria-label="Decomposição tensorial"><option value="hosvd">HOSVD (Direta por modo)</option><option value="hooi">HOOI (Iteração Ortogonal Ótima)</option></select>`,
    `</div>`,
    `<div class="tool-field" data-via-only="femt">`,
    `<label for="ts-mesh-select">Interpolação Simplicial P₁</label>`,
    `<select id="ts-mesh-select" class="touch-control" aria-label="Tipo de malha FEMT"><option value="kuhn_delaunay">Kuhn-Delaunay Conformante O(D log D)</option><option value="delaunay">Triangulação de Delaunay Explícita (2D/3D)</option></select>`,
    `</div>`,
    `<div class="tool-field" data-via-only="femt">`,
    `<label for="ts-hull-select">Fecho Convexo Global</label>`,
    `<select id="ts-hull-select" class="touch-control" aria-label="Tipo de envoltória">${hullOpts}</select>`,
    `</div>`,
    `<div class="tool-field" data-via-only="femt">`,
    `<label for="ts-rank">Posto Global R (vazio = Auto)</label>`,
    `<input type="number" id="ts-rank" class="touch-control id-param-input" min="1" max="128" step="1" placeholder="Auto (Eckart-Young)" aria-label="Posto global de truncamento" />`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="ts-svd-tol-input">Tolerância Relativa SVD (svd_tol)</label>`,
    `<input type="number" id="ts-svd-tol-input" class="touch-control id-param-input" min="1e-14" max="0.5" step="any" value="1e-6" aria-label="Tolerância relativa de valores singulares" />`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="ts-grid-points">Grade Uniforme Rápida (aplicar a todos os eixos)</label>`,
    `<div class="ts-inline-apply">`,
    `<input type="number" id="ts-grid-points" class="touch-control id-param-input" min="3" max="201" step="2" value="15" aria-label="Pontos de grade por eixo" />`,
    `<button type="button" id="btn-ts-apply-uniform-grid" class="touch-control btn-subtle btn-small" data-action="ts-apply-uniform-grid">Aplicar G_d</button>`,
    `</div>`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="ts-val-points">Pontos de Validação Off-Grid</label>`,
    `<input type="number" id="ts-val-points" class="touch-control id-param-input" min="16" max="2048" step="16" value="128" aria-label="Pontos de validação fora da grade" />`,
    `</div>`,
    `</div>`,

    `<details class="ts-advanced-details" data-via-only="tpmt">`,
    `<summary>Opções Avançadas TPMT (HOOI e Reamostragem Fina)</summary>`,
    `<div class="ts-params-grid">`,
    `<div class="tool-field"><label for="ts-resample-method">Método de Reamostragem 1D</label><select id="ts-resample-method" class="touch-control"><option value="linear">Linear por partes</option><option value="pchip">PCHIP Hermite Monotônica</option></select></div>`,
    `<div class="tool-field"><label for="ts-hooi-max-iter">Máx. Iterações HOOI</label><input type="number" id="ts-hooi-max-iter" class="touch-control id-param-input" min="1" max="500" value="50" /></div>`,
    `<div class="tool-field"><label for="ts-sn-tol-input">Tolerância Soma Unitária (sn_tol)</label><input type="number" id="ts-sn-tol-input" class="touch-control id-param-input" step="any" value="1e-6" /></div>`,
    `</div>`,
    `</details>`,
    `</div>`,
    `</div>`,

    /* ==================== STATUS & ZONA 4 (INSPEÇÃO + GRÁFICOS) ==================== */
    `<div id="ts-status" class="ts-status" role="status" aria-live="polite"></div>`,

    `<div id="ts-zone-4-results" class="ts-results-split">`,
    `<div class="ts-zone-4a">`,
    `<div id="ts-summary" class="subcard ts-summary" aria-live="polite">`,
    `<h4>Zona 4A — Certificado de Fidelidade &amp; Inspeção</h4>`,
    `<p>Configure ou escolha um sistema qLPV acima e clique em <strong>Validar &amp; Gerar Modelo TS</strong>.</p>`,
    `</div>`,
    `<div id="ts-compare-slot" class="subcard" aria-live="polite" hidden></div>`,
    `<div id="ts-vertex-inspector-card" class="subcard" hidden>`,
    `<div class="ts-subcard-header">`,
    `<h5>Inspetor de Regras e Matrizes Vértices (A_r, B_r, C_r, D_r)</h5>`,
    `<select id="ts-vertex-select" class="touch-control" aria-label="Selecionar vértice/regra TS"></select>`,
    `</div>`,
    `<div id="ts-vertex-detail-slot"></div>`,
    `</div>`,
    `</div>`,

    `<div class="ts-zone-4b">`,
    `<div class="subcard ts-chart-controls-bar">`,
    `<div class="tool-field">`,
    `<label for="ts-chart-axis-select">Premissa / Eixo ativo (1D &amp; Bases U/W)</label>`,
    `<select id="ts-chart-axis-select" class="touch-control" aria-label="Selecionar eixo para gráficos 1D"><option value="0">Eixo 1</option></select>`,
    `</div>`,
    `<div class="tool-field">`,
    `<label for="ts-chart-rule-select">Regra p/ Superfície Simplicial 2D</label>`,
    `<select id="ts-chart-rule-select" class="touch-control" aria-label="Selecionar regra para malha 2D"><option value="0">Regra h_1</option></select>`,
    `</div>`,
    `</div>`,
    `<div class="ts-charts-grid">`,
    chartCardHtml("ts-hr-chart-slot", "Funções de Pertinência 1D", "ts-hr-table-slot", "pertinencia_1d"),
    chartCardHtml("ts-mesh-chart-slot", "Malha / Superfície Simplicial 2D (h_r)", "ts-mesh-table-slot", "malha_simplicial_2d"),
    chartCardHtml("ts-bases-chart-slot", "Bases SVD/HOSVD U vs Pertinências W", "ts-bases-table-slot", "bases_u_vs_w"),
    chartCardHtml("ts-scree-chart-slot", "Espectro de Valores Singulares (Scree)", "ts-scree-table-slot", "valores_singulares"),
    chartCardHtml("ts-error-heatmap-slot", "Mapa de Calor do Erro Off-Grid ||S − Ŝ||_F", "ts-error-table-slot", "erro_offgrid"),
    `</div>`,
    `</div>`,
    `</div>`,
    `</section>`,
  ].join("\n");
}

export class TsModelingView {
  private readonly shell: ControlLabShell;
  private readonly client: ControlLabEngineClient;
  private readonly container: HTMLElement;
  private readonly onRequestRender?: () => void;
  private readonly onOpenExportModal?: TsModelingViewOptions["onOpenExportModal"];
  private readonly onRouteToLmi?: (refKey: string) => void;

  private readonly q = <T extends HTMLElement>(sel: string): T | null =>
    this.container.querySelector<T>(sel);

  private via: TsVia = "sector";
  private draft: TsQlpvDraft = makePendulum16Draft();
  private matrixFilter: TsMatrixFilter = "all";
  private jsonDrawerOpen = false;
  private selectedVertexIdx = 0;
  private selectedChartAxisIdx = 0;
  private selectedChartRuleIdx = 0;

  private result: TsDerivationResult | null = null;
  private resultVia: TsVia | null = null;
  private resultWarnings: Array<{ code: string; message: string }> = [];
  private lastSubmittedPayload: Record<string, unknown> | null = null;
  private lastDerivedSignature: string | null = null;
  private lastDerivedDraftSnapshot: TsQlpvDraft | null = null;
  private registeredKey: string | null = null;

  private busy = false;
  private domInitialized = false;
  private lastActiveAxisKey = "";
  private statusText = "";
  private compareHtml = "";
  private chartsCacheKey = "";

  constructor(options: TsModelingViewOptions) {
    this.shell = options.shell;
    this.client = options.client;
    this.container = options.container;
    this.onRequestRender = options.onRequestRender;
    this.onOpenExportModal = options.onOpenExportModal;
    this.onRouteToLmi = options.onRouteToLmi;
    this.bindStaticEvents();
    if (supportsTsModeling(this.client)) {
      this.client.subscribeTsModelingProgress((event) => {
        this.setStatus(
          `Executando no motor científico (${event.progress.stage} • ${Math.round(event.progress.elapsed_ms)} ms)…`,
        );
      });
    }
  }

  public isLastDerivationStale(): boolean {
    if (
      !this.result ||
      !this.resultVia ||
      !this.lastDerivedSignature ||
      !this.lastDerivedDraftSnapshot
    ) {
      return true;
    }
    return this.lastDerivedSignature !== serializeDraftDerivationSignature(this.draft, this.via);
  }

  public getState(): {
    presetSource: TsPresetId | "custom";
    via: TsVia;
    hasResult: boolean;
    isStale: boolean;
    registeredKey: string | null;
  } {
    return {
      presetSource: this.draft.presetSource,
      via: this.via,
      hasResult: this.result !== null,
      isStale: this.isLastDerivationStale(),
      registeredKey: this.registeredKey,
    };
  }

  public getDraft(): TsQlpvDraft {
    return structuredClone(this.draft);
  }

  private bindStaticEvents(): void {
    const on = (selector: string, event: string, handler: (ev: Event) => void): void => {
      this.q<HTMLElement>(selector)?.addEventListener(event, handler);
    };

    for (const v of TS_VIAS) {
      on(`#btn-ts-via-${v}`, "click", () => this.setVia(v));
    }
    on("#ts-via-select", "change", () => {
      const v = this.q<HTMLSelectElement>("#ts-via-select")?.value ?? "";
      if ((TS_VIAS as readonly string[]).includes(v)) {
        this.setVia(v as TsVia);
      }
    });

    on("#ts-preset-select", "change", () => {
      const v = this.q<HTMLSelectElement>("#ts-preset-select")?.value ?? "";
      if (isTsPresetId(v)) {
        this.selectPreset(v);
      } else if (v === "custom") {
        this.draft.presetSource = "custom";
        this.syncHeaderControls();
        this.syncStaleState();
      }
    });

    on("#ts-model-id-input", "change", () => {
      this.draft.modelId = this.q<HTMLInputElement>("#ts-model-id-input")?.value.trim() || "ts-model";
      this.syncStaleState();
    });
    on("#ts-model-id-input", "input", () => {
      this.draft.modelId = this.q<HTMLInputElement>("#ts-model-id-input")?.value.trim() || "ts-model";
      this.syncStaleState();
    });

    on('[data-action="ts-new-custom"]', "click", () => this.resetToBlankCustom());
    on('[data-action="ts-toggle-json"]', "click", () => {
      this.jsonDrawerOpen = !this.jsonDrawerOpen;
      if (this.jsonDrawerOpen) this.refreshJsonTextarea();
      setElHidden(this.q("#ts-json-drawer"), !this.jsonDrawerOpen);
    });
    on('[data-action="ts-refresh-json"]', "click", () => this.refreshJsonTextarea());
    on('[data-action="ts-apply-json"]', "click", () => this.applyJsonFromTextarea());

    on("#ts-time-domain-select", "change", () => {
      const mode = this.q<HTMLSelectElement>("#ts-time-domain-select")?.value;
      this.draft.timeDomain = mode === "discrete" ? "discrete" : "continuous";
      setElHidden(this.q("#ts-dt-field-wrap"), this.draft.timeDomain !== "discrete");
      this.syncStaleState();
    });
    on("#ts-dt-input", "change", () => {
      const val = Number(this.q<HTMLInputElement>("#ts-dt-input")?.value ?? "0.01");
      if (Number.isFinite(val) && val > 0) this.draft.dt = val;
      this.syncStaleState();
    });

    on("#ts-dim-n", "change", () => this.handleDimensionChange());
    on("#ts-dim-m", "change", () => this.handleDimensionChange());
    on("#ts-dim-p", "change", () => this.handleDimensionChange());
    on("#ts-enable-gen-channels", "change", () => {
      const cb = this.q<HTMLInputElement>("#ts-enable-gen-channels");
      this.draft.enableGeneralized = Boolean(cb?.checked);
      if (!this.draft.enableGeneralized && this.matrixFilter === "gen") {
        this.matrixFilter = "all";
      }
      this.rebuildEditableSections();
    });
    on("#ts-dim-nw", "change", () => this.handleDimensionChange());
    on("#ts-dim-nz", "change", () => this.handleDimensionChange());

    on('[data-action="ts-add-external"]', "click", () => {
      const idx = this.draft.externals.length + 1;
      let cand = `theta${idx}`;
      const used = new Set([
        ...this.draft.states.map((s) => s.name),
        ...this.draft.externals.map((e) => e.name),
      ]);
      let k = idx;
      while (used.has(cand)) {
        k += 1;
        cand = `theta${k}`;
      }
      this.draft.externals.push({ name: cand, min: 0.5, max: 1.5, measured: true });
      this.draft.presetSource = "custom";
      this.renderExternalsTable();
      this.updateLiveDiagnostics();
    });

    on('[data-action="ts-add-premise"]', "click", () => {
      const used = new Set(this.draft.premises.map((p) => p.name));
      let k = this.draft.premises.length + 1;
      let cand = `z${k}`;
      while (used.has(cand)) {
        k += 1;
        cand = `z${k}`;
      }
      const firstState = this.draft.states[0]?.name ?? "x1";
      this.draft.premises.push({
        name: cand,
        expression: firstState,
        measured: true,
        userMin: "",
        userMax: "",
        computedMin: null,
        computedMax: null,
        activeVariables: [firstState],
      });
      this.draft.presetSource = "custom";
      this.renderPremisesTable();
      this.updateLiveDiagnostics();
    });

    on('[data-action="ts-expand-to-direct"]', "click", () => {
      this.syncSectorToDirectMatrices();
      this.setStatus(
        "Premissas z_k substituídas algebricamente nas matrizes diretas S(x, w_ext) para uso na TPMT e FEMT.",
      );
      if (this.via !== "sector") {
        this.renderSymbolicMatrices();
      }
      this.updateLiveDiagnostics(true);
    });

    for (const fBtn of Array.from(
      this.container.querySelectorAll<HTMLButtonElement>("[data-matrix-filter]"),
    )) {
      fBtn.addEventListener("click", () => {
        const mf = fBtn.getAttribute("data-matrix-filter") as TsMatrixFilter;
        this.matrixFilter = mf;
        this.syncMatrixFilterButtons();
        this.renderSymbolicMatrices();
      });
    }

    on("#ts-decomp-select", "change", () => {
      const v = this.q<HTMLSelectElement>("#ts-decomp-select")?.value;
      this.draft.tpmtDecomposition = v === "hooi" ? "hooi" : "hosvd";
      this.syncStaleState();
    });
    on("#ts-mesh-select", "change", () => {
      const v = this.q<HTMLSelectElement>("#ts-mesh-select")?.value;
      this.draft.femtMeshKind = v === "delaunay" ? "delaunay" : "kuhn_delaunay";
      this.syncStaleState();
    });
    on("#ts-hull-select", "change", () => {
      const v = this.q<HTMLSelectElement>("#ts-hull-select")?.value ?? "CNO";
      if ((TS_HULLS as readonly string[]).includes(v)) {
        this.draft.femtHull = v as TsHull;
      }
      this.syncStaleState();
    });
    on("#ts-rank", "change", () => {
      this.draft.femtGlobalRank = this.q<HTMLInputElement>("#ts-rank")?.value.trim() ?? "";
      this.syncStaleState();
    });
    on("#ts-svd-tol-input", "change", () => {
      const v = Number(this.q<HTMLInputElement>("#ts-svd-tol-input")?.value ?? "1e-6");
      if (Number.isFinite(v) && v > 0) this.draft.svdTol = v;
      this.syncStaleState();
    });
    on("#ts-sn-tol-input", "change", () => {
      const v = Number(this.q<HTMLInputElement>("#ts-sn-tol-input")?.value ?? "1e-6");
      if (Number.isFinite(v) && v > 0) this.draft.snTol = v;
      this.syncStaleState();
    });
    on("#ts-resample-method", "change", () => {
      const v = this.q<HTMLSelectElement>("#ts-resample-method")?.value;
      this.draft.resampleMethod = v === "pchip" ? "pchip" : "linear";
      this.syncStaleState();
    });
    on("#ts-hooi-max-iter", "change", () => {
      const v = Number(this.q<HTMLInputElement>("#ts-hooi-max-iter")?.value ?? "50");
      if (Number.isInteger(v) && v >= 1) this.draft.hooiMaxIter = v;
      this.syncStaleState();
    });
    on("#ts-val-points", "change", () => {
      const v = Number(this.q<HTMLInputElement>("#ts-val-points")?.value ?? "128");
      if (Number.isInteger(v) && v >= 1 && v <= 2048) this.draft.valPoints = v;
      this.syncStaleState();
    });

    on('[data-action="ts-apply-uniform-grid"]', "click", () => {
      const g = Number(this.q<HTMLInputElement>("#ts-grid-points")?.value ?? "15");
      if (!Number.isInteger(g) || g < 3 || g > 201) {
        this.shell.presentError(
          new ControlLabBridgeError(
            "VALIDATION_ERROR",
            "Informe um número inteiro de pontos entre 3 e 201.",
          ),
        );
        return;
      }
      for (const k of Object.keys(this.draft.axisSettings)) {
        this.draft.axisSettings[k].gridPoints = g;
      }
      this.renderPerAxisTable();
      this.updateLiveDiagnostics();
    });

    on('[data-action="ts-analyze"]', "click", () => void this.analyze());
    on('[data-action="ts-derive"]', "click", () => void this.derive());
    on('[data-action="ts-compare"]', "click", () => void this.compare());
    on('[data-action="ts-register"]', "click", () => void this.register(false));
    on('[data-action="ts-register-open-lmi"]', "click", () => void this.register(true));
    on('[data-action="ts-reload-recipe"]', "click", () => this.reloadRecipe());
    on('[data-action="ts-export-python"]', "click", (ev) =>
      void this.exportScript("python", ev.currentTarget as HTMLElement | null),
    );
    on('[data-action="ts-export-matlab"]', "click", (ev) =>
      void this.exportScript("matlab", ev.currentTarget as HTMLElement | null),
    );

    on("#ts-vertex-select", "change", () => {
      this.selectedVertexIdx = Number(this.q<HTMLSelectElement>("#ts-vertex-select")?.value ?? "0");
      this.renderVertexDetail();
    });
    on("#ts-chart-axis-select", "change", () => {
      this.selectedChartAxisIdx = Number(
        this.q<HTMLSelectElement>("#ts-chart-axis-select")?.value ?? "0",
      );
      this.chartsCacheKey = "";
      this.renderCharts(this.shell.getThemeMode());
    });
    on("#ts-chart-rule-select", "change", () => {
      this.selectedChartRuleIdx = Number(
        this.q<HTMLSelectElement>("#ts-chart-rule-select")?.value ?? "0",
      );
      this.chartsCacheKey = "";
      this.renderCharts(this.shell.getThemeMode());
    });

    for (const svgBtn of Array.from(
      this.container.querySelectorAll<HTMLButtonElement>('[data-action="ts-export-svg"]'),
    )) {
      svgBtn.addEventListener("click", (ev) => {
        const slotId = svgBtn.getAttribute("data-chart-slot") ?? "";
        const key = svgBtn.getAttribute("data-chart-key") ?? "grafico_ts";
        const slot = this.q<HTMLElement>(`#${slotId}`);
        const svgMatch = /<svg[\s\S]*<\/svg>/i.exec(slot?.innerHTML ?? "");
        if (!svgMatch) {
          this.shell.presentError(
            new ControlLabBridgeError(
              "VALIDATION_ERROR",
              "Gere o modelo TS primeiro para exportar este gráfico em SVG.",
            ),
          );
          return;
        }
        this.onOpenExportModal?.(
          {
            title: `Gráfico SVG — ${key}`,
            filename: `${this.draft.modelId || "ts_model"}_${key}.svg`,
            mimeType: "image/svg+xml;charset=utf-8",
            content: svgMatch[0],
          },
          ev.currentTarget as HTMLElement | null,
        );
      });
    }
  }

  private clearDerivedResult(): void {
    this.result = null;
    this.resultVia = null;
    this.resultWarnings = [];
    this.lastSubmittedPayload = null;
    this.lastDerivedSignature = null;
    this.lastDerivedDraftSnapshot = null;
    this.registeredKey = null;
    this.compareHtml = "";
    this.selectedVertexIdx = 0;
    this.selectedChartAxisIdx = 0;
    this.selectedChartRuleIdx = 0;
    this.chartsCacheKey = "";

    const summary = this.q<HTMLElement>("#ts-summary");
    if (summary) {
      summary.innerHTML = [
        `<h4>Zona 4A — Certificado de Fidelidade &amp; Inspeção</h4>`,
        `<p>Configure ou escolha um sistema qLPV acima e clique em <strong>Validar &amp; Gerar Modelo TS</strong>.</p>`,
      ].join("");
    }
    const compareSlot = this.q<HTMLElement>("#ts-compare-slot");
    if (compareSlot) {
      compareSlot.innerHTML = "";
      setElHidden(compareSlot, true);
    }
    setElHidden(this.q<HTMLElement>("#ts-vertex-inspector-card"), true);
    const vertexSlot = this.q<HTMLElement>("#ts-vertex-detail-slot");
    if (vertexSlot) vertexSlot.innerHTML = "";

    this.renderCharts(this.shell.getThemeMode());
    this.syncStaleState();
  }

  public selectPreset(id: TsPresetId): void {
    const spec = TS_PRESETS[id];
    this.draft = spec.buildDraft();
    this.via = spec.defaultVia;
    this.lastActiveAxisKey = "";
    this.domInitialized = true;
    this.clearDerivedResult();
    this.rebuildEditableSections();
    this.onRequestRender?.();
    this.render();
  }

  public resetToBlankCustom(): void {
    this.draft = makeBlankCustomDraft();
    this.lastActiveAxisKey = "";
    this.domInitialized = true;
    this.clearDerivedResult();
    this.rebuildEditableSections();
    this.setStatus("Novo sistema qLPV em branco inicializado. Edite estados, limites e matrizes.");
    this.onRequestRender?.();
    this.render();
  }

  public setVia(via: TsVia): void {
    const prevVia = this.via;
    this.via = via;
    // Se o usuário estava editando na Via 1 e muda pela primeira vez para TPMT/FEMT,
    // oferecemos sincronização automática quando o modelo vem de preset/setor compatível
    if (prevVia === "sector" && via !== "sector" && this.draft.premises.length > 0) {
      const secDiag = auditSectorMatrices(
        {
          A: this.draft.sectorMatrices.A,
          B: this.draft.sectorMatrices.B,
          C: this.draft.sectorMatrices.C,
          D: this.draft.sectorMatrices.D,
        },
        this.draft.premises.map((p) => p.name.trim()),
        [
          ...this.draft.states.map((s) => s.name.trim()),
          ...this.draft.externals.map((e) => e.name.trim()),
        ],
      );
      if (secDiag.length === 0) {
        this.syncSectorToDirectMatrices();
      }
    }
    this.lastActiveAxisKey = "";
    this.rebuildEditableSections();
    this.onRequestRender?.();
    this.render();
  }

  private syncSectorToDirectMatrices(): void {
    const pList = this.draft.premises.map((p) => ({
      name: p.name.trim(),
      expression: p.expression.trim(),
    }));
    const sm = this.draft.sectorMatrices;
    this.draft.directMatrices = {
      A: expandSectorMatrixToDirect(sm.A, pList),
      B: expandSectorMatrixToDirect(sm.B, pList),
      C: expandSectorMatrixToDirect(sm.C, pList),
      D: expandSectorMatrixToDirect(sm.D, pList),
      Bw: expandSectorMatrixToDirect(sm.Bw, pList),
      Dyw: expandSectorMatrixToDirect(sm.Dyw, pList),
      Cz: expandSectorMatrixToDirect(sm.Cz, pList),
      Dzu: expandSectorMatrixToDirect(sm.Dzu, pList),
      Dzw: expandSectorMatrixToDirect(sm.Dzw, pList),
    };
  }

  private handleDimensionChange(): void {
    const readDim = (sel: string, fallback: number, maxVal: number): number => {
      const raw = Number(this.q<HTMLInputElement>(sel)?.value ?? String(fallback));
      if (!Number.isInteger(raw) || raw < 1) return 1;
      return Math.min(maxVal, raw);
    };
    const nextN = readDim("#ts-dim-n", this.draft.n, 12);
    const nextM = readDim("#ts-dim-m", this.draft.m, 8);
    const nextP = readDim("#ts-dim-p", this.draft.p, 8);
    const nextNw = readDim("#ts-dim-nw", this.draft.nw, 6);
    const nextNz = readDim("#ts-dim-nz", this.draft.nz, 6);

    const usedNames = new Set(this.draft.states.map((s) => s.name));
    const nextStates: TsStateVarRow[] = [];
    for (let i = 0; i < nextN; i += 1) {
      if (i < this.draft.states.length) {
        nextStates.push(this.draft.states[i]);
      } else {
        let idx = i + 1;
        let cand = `x${idx}`;
        while (usedNames.has(cand)) {
          idx += 1;
          cand = `x${idx}`;
        }
        usedNames.add(cand);
        nextStates.push({ name: cand, min: -1.0, max: 1.0, unit: "", measured: true });
      }
    }
    this.draft.states = nextStates;
    this.draft.n = nextN;
    this.draft.m = nextM;
    this.draft.p = nextP;
    this.draft.nw = nextNw;
    this.draft.nz = nextNz;
    this.draft.presetSource = "custom";

    const resizeGroup = (g: TsSymbolicSystemMatrices): TsSymbolicSystemMatrices => ({
      A: resizeMatrix(g.A, nextN, nextN, "0"),
      B: resizeMatrix(g.B, nextN, nextM, "0"),
      C: resizeMatrix(g.C, nextP, nextN, "0"),
      D: resizeMatrix(g.D, nextP, nextM, "0"),
      Bw: resizeMatrix(g.Bw, nextN, nextNw, "0"),
      Dyw: resizeMatrix(g.Dyw, nextP, nextNw, "0"),
      Cz: resizeMatrix(g.Cz, nextNz, nextN, "0"),
      Dzu: resizeMatrix(g.Dzu, nextNz, nextM, "0"),
      Dzw: resizeMatrix(g.Dzw, nextNz, nextNw, "0"),
    });
    this.draft.sectorMatrices = resizeGroup(this.draft.sectorMatrices);
    this.draft.directMatrices = resizeGroup(this.draft.directMatrices);
    this.rebuildEditableSections();
  }

  private refreshJsonTextarea(): void {
    const ta = this.q<HTMLTextAreaElement>("#ts-qlpv-json-textarea");
    if (!ta) return;
    const exported = {
      via: this.via,
      model_id: this.draft.modelId,
      dt: this.draft.timeDomain === "discrete" ? this.draft.dt : null,
      states: this.draft.states,
      externals: this.draft.externals,
      premises: this.draft.premises.map((p) => ({
        name: p.name,
        expression: p.expression,
        measured: p.measured,
      })),
      sector_matrices: {
        A: this.draft.sectorMatrices.A,
        B: this.draft.sectorMatrices.B,
        C: this.draft.sectorMatrices.C,
        D: this.draft.sectorMatrices.D,
      },
      direct_matrices: {
        A: this.draft.directMatrices.A,
        B: this.draft.directMatrices.B,
        C: this.draft.directMatrices.C,
        D: this.draft.directMatrices.D,
      },
    };
    ta.value = JSON.stringify(exported, null, 2);
  }

  private applyJsonFromTextarea(): void {
    try {
      const ta = this.q<HTMLTextAreaElement>("#ts-qlpv-json-textarea");
      const parsed: unknown = JSON.parse(ta?.value ?? "{}");
      if (!isPlainObject(parsed)) {
        throw new ControlLabBridgeError("VALIDATION_ERROR", "JSON deve ser um objeto estruturado.");
      }
      if (typeof parsed.via === "string" && (TS_VIAS as readonly string[]).includes(parsed.via)) {
        this.via = parsed.via as TsVia;
      }
      if (typeof parsed.model_id === "string" && parsed.model_id.trim()) {
        this.draft.modelId = parsed.model_id.trim();
      }
      if (typeof parsed.dt === "number" && parsed.dt > 0) {
        this.draft.timeDomain = "discrete";
        this.draft.dt = parsed.dt;
      } else if (parsed.dt === null) {
        this.draft.timeDomain = "continuous";
      }
      if (Array.isArray(parsed.states) && parsed.states.length > 0) {
        this.draft.states = parsed.states
          .filter((s): s is Record<string, unknown> => isPlainObject(s))
          .map((s, idx) => ({
            name: String(s.name ?? `x${idx + 1}`),
            min: Number(s.min ?? -1),
            max: Number(s.max ?? 1),
            unit: typeof s.unit === "string" ? s.unit : "",
            measured: s.measured !== false,
          }));
        this.draft.n = this.draft.states.length;
      }
      if (Array.isArray(parsed.externals)) {
        this.draft.externals = parsed.externals
          .filter((e): e is Record<string, unknown> => isPlainObject(e))
          .map((e, idx) => ({
            name: String(e.name ?? `theta${idx + 1}`),
            min: Number(e.min ?? -1),
            max: Number(e.max ?? 1),
            measured: e.measured !== false,
          }));
      }
      if (Array.isArray(parsed.premises)) {
        this.draft.premises = parsed.premises
          .filter((pr): pr is Record<string, unknown> => isPlainObject(pr))
          .map((pr, idx) => ({
            name: String(pr.name ?? `z${idx + 1}`),
            expression: String(pr.expression ?? "0"),
            measured: pr.measured !== false,
            userMin: "",
            userMax: "",
            computedMin: null,
            computedMax: null,
            activeVariables: [],
          }));
      }
      const applyMatGroup = (
        src: unknown,
        target: TsSymbolicSystemMatrices,
      ): void => {
        if (!isPlainObject(src)) return;
        const A = toStringMatrix(src.A);
        const B = toStringMatrix(src.B);
        const C = toStringMatrix(src.C);
        const D = toStringMatrix(src.D);
        if (A) {
          target.A = A;
          this.draft.n = A.length;
        }
        if (B) {
          target.B = B;
          this.draft.m = B[0]?.length ?? this.draft.m;
        }
        if (C) {
          target.C = C;
          this.draft.p = C.length;
        }
        if (D) target.D = D;
      };
      applyMatGroup(parsed.sector_matrices, this.draft.sectorMatrices);
      applyMatGroup(parsed.direct_matrices, this.draft.directMatrices);
      if (parsed.A && parsed.B) {
        applyMatGroup(parsed, this.via === "sector" ? this.draft.sectorMatrices : this.draft.directMatrices);
      }
      this.draft.presetSource = "custom";
      this.lastActiveAxisKey = "";
      this.rebuildEditableSections();
      this.setStatus("Especificação JSON aplicada com sucesso ao editor qLPV.");
    } catch (err: unknown) {
      this.shell.presentError(
        err instanceof ControlLabBridgeError
          ? err
          : new ControlLabBridgeError(
              "VALIDATION_ERROR",
              `Falha ao ler JSON qLPV: ${err instanceof Error ? err.message : String(err)}`,
            ),
      );
    }
  }

  private rebuildEditableSections(): void {
    this.syncHeaderControls();
    this.renderStatesTable();
    this.renderExternalsTable();
    this.renderPremisesTable();
    this.syncMatrixFilterButtons();
    this.renderSymbolicMatrices();
    this.updateLiveDiagnostics(true);
  }

  private syncHeaderControls(): void {
    for (const v of TS_VIAS) {
      const btn = this.q<HTMLButtonElement>(`#btn-ts-via-${v}`);
      if (btn) btn.setAttribute("aria-pressed", v === this.via ? "true" : "false");
    }
    const viaSel = this.q<HTMLSelectElement>("#ts-via-select");
    if (viaSel && viaSel.value !== this.via) viaSel.value = this.via;

    const presetSel = this.q<HTMLSelectElement>("#ts-preset-select");
    if (presetSel && presetSel.value !== this.draft.presetSource) {
      presetSel.value = this.draft.presetSource;
    }
    const modelInput = this.q<HTMLInputElement>("#ts-model-id-input");
    if (modelInput && modelInput.value !== this.draft.modelId) {
      modelInput.value = this.draft.modelId;
    }
    const descEl = this.q<HTMLElement>("#ts-preset-description");
    if (descEl) {
      descEl.textContent =
        this.draft.presetSource === "custom"
          ? "Modo de edição customizada ativo: defina livremente dimensões, limites, variáveis premissas e equações simbólicas de A, B, C, D."
          : TS_PRESETS[this.draft.presetSource].description;
    }

    const tdSel = this.q<HTMLSelectElement>("#ts-time-domain-select");
    if (tdSel) tdSel.value = this.draft.timeDomain;
    setElHidden(this.q("#ts-dt-field-wrap"), this.draft.timeDomain !== "discrete");
    const dtInput = this.q<HTMLInputElement>("#ts-dt-input");
    if (dtInput) dtInput.value = String(this.draft.dt);

    const setNum = (sel: string, v: number): void => {
      const el = this.q<HTMLInputElement>(sel);
      if (el) el.value = String(v);
    };
    setNum("#ts-dim-n", this.draft.n);
    setNum("#ts-dim-m", this.draft.m);
    setNum("#ts-dim-p", this.draft.p);
    setNum("#ts-dim-nw", this.draft.nw);
    setNum("#ts-dim-nz", this.draft.nz);

    const genCb = this.q<HTMLInputElement>("#ts-enable-gen-channels");
    if (genCb) genCb.checked = this.draft.enableGeneralized;
    setElHidden(this.q("#ts-gen-dims-wrap"), !this.draft.enableGeneralized);
    setElHidden(this.q("#btn-ts-filter-gen"), !this.draft.enableGeneralized);

    const matHeading = this.q<HTMLElement>("#ts-matrices-heading");
    const matSub = this.q<HTMLElement>("#ts-matrices-subtitle");
    if (matHeading && matSub) {
      if (this.via === "sector") {
        matHeading.textContent =
          "Passo 1B — Matrizes do Sistema em Função das Premissas A(z), B(z), C(z), D(z)";
        matSub.textContent =
          "Escreva cada entrada como combinação afim/multilinear das premissas z_k definidas no Passo 1A (constantes numéricas + z_1..z_nn).";
      } else if (this.via === "tpmt") {
        matHeading.textContent =
          "Passo 2A — Matrizes qLPV Diretas A(x, w_ext), B(x, w_ext), C(x, w_ext), D(x, w_ext)";
        matSub.textContent =
          "Escreva as não-linearidades diretamente em função dos estados x_i e sinais externos w_ext. Apenas as variáveis que aparecem nas matrizes geram modos no tensor.";
      } else {
        matHeading.textContent =
          "Passo 3A — Matrizes qLPV Diretas A(x, w_ext), B(x, w_ext), C(x, w_ext), D(x, w_ext)";
        matSub.textContent =
          "Escreva as não-linearidades diretamente em função dos estados e sinais externos. A FEMT vetoriza S(p) em matriz 2D e aplica SVD global ótima sem produto tensorial.";
      }
    }

    const sampledHeading = this.q<HTMLElement>("#ts-sampled-step-heading");
    if (sampledHeading) {
      sampledHeading.textContent =
        this.via === "tpmt"
          ? "Passo 2B — Discretização por Dimensão G_d, Postos Modais R_d e Fecho Convexo (TPMT)"
          : "Passo 3B — Malha Nodal G_d, Posto Global SVD (Eckart–Young) e Simplices P₁ (FEMT)";
    }

    const decompSel = this.q<HTMLSelectElement>("#ts-decomp-select");
    if (decompSel) decompSel.value = this.draft.tpmtDecomposition;
    const meshSel = this.q<HTMLSelectElement>("#ts-mesh-select");
    if (meshSel) meshSel.value = this.draft.femtMeshKind;
    const hullSel = this.q<HTMLSelectElement>("#ts-hull-select");
    if (hullSel) hullSel.value = this.draft.femtHull;
    const rankIn = this.q<HTMLInputElement>("#ts-rank");
    if (rankIn) rankIn.value = this.draft.femtGlobalRank;
    const svdTolIn = this.q<HTMLInputElement>("#ts-svd-tol-input");
    if (svdTolIn) svdTolIn.value = String(this.draft.svdTol);
    const valPtsIn = this.q<HTMLInputElement>("#ts-val-points");
    if (valPtsIn) valPtsIn.value = String(this.draft.valPoints);
  }

  private renderStatesTable(): void {
    const slot = this.q<HTMLElement>("#ts-states-slot");
    if (!slot) return;
    const rowsHtml = this.draft.states
      .map(
        (st, i) => [
          `<tr data-state-row="${i}">`,
          `<td><input type="text" class="touch-control ts-var-name-input" data-state-field="name" data-idx="${i}" value="${escapeHtml(st.name)}" aria-label="Nome do estado ${i + 1}" /></td>`,
          `<td><input type="number" step="any" class="touch-control ts-bound-input" data-state-field="min" data-idx="${i}" value="${st.min}" aria-label="Limite mínimo de ${escapeHtml(st.name)}" /></td>`,
          `<td><input type="number" step="any" class="touch-control ts-bound-input" data-state-field="max" data-idx="${i}" value="${st.max}" aria-label="Limite máximo de ${escapeHtml(st.name)}" /></td>`,
          `<td><input type="text" class="touch-control ts-unit-input" data-state-field="unit" data-idx="${i}" value="${escapeHtml(st.unit)}" placeholder="ex: rad" aria-label="Unidade de ${escapeHtml(st.name)}" /></td>`,
          `<td><label class="lmi-check-label"><input type="checkbox" data-state-field="measured" data-idx="${i}"${st.measured ? " checked" : ""} /><span>Medido</span></label></td>`,
          `</tr>`,
        ].join(""),
      )
      .join("");
    slot.innerHTML = `<table class="accessible-data-table ts-compact-table" aria-label="Estados e limites"><thead><tr><th scope="col">Estado</th><th scope="col">Mín</th><th scope="col">Máx</th><th scope="col">Unid.</th><th scope="col">Medição</th></tr></thead><tbody>${rowsHtml}</tbody></table>`;

    for (const inp of Array.from(slot.querySelectorAll<HTMLInputElement>("[data-state-field]"))) {
      const idx = Number(inp.getAttribute("data-idx") ?? "0");
      const field = inp.getAttribute("data-state-field");
      const onEdit = (): void => {
        const row = this.draft.states[idx];
        if (!row) return;
        if (field === "name") row.name = inp.value.trim() || `x${idx + 1}`;
        else if (field === "min") row.min = Number(inp.value);
        else if (field === "max") row.max = Number(inp.value);
        else if (field === "unit") row.unit = inp.value;
        else if (field === "measured") row.measured = inp.checked;
        this.draft.presetSource = "custom";
        this.updateLiveDiagnostics();
      };
      inp.addEventListener("change", onEdit);
      if (field !== "measured") inp.addEventListener("input", onEdit);
    }
  }

  private renderExternalsTable(): void {
    const slot = this.q<HTMLElement>("#ts-externals-slot");
    if (!slot) return;
    if (this.draft.externals.length === 0) {
      slot.innerHTML = `<p class="dock-item-summary">Nenhum sinal ou parâmetro externo variante adicionado. Clique em <strong>+ Adicionar sinal externo</strong> se a planta depender de parâmetros como θ(t) ou velocidade longitudinal v(t).</p>`;
      return;
    }
    const rowsHtml = this.draft.externals
      .map(
        (ext, i) => [
          `<tr data-ext-row="${i}">`,
          `<td><input type="text" class="touch-control ts-var-name-input" data-ext-field="name" data-idx="${i}" value="${escapeHtml(ext.name)}" aria-label="Nome do sinal externo ${i + 1}" /></td>`,
          `<td><input type="number" step="any" class="touch-control ts-bound-input" data-ext-field="min" data-idx="${i}" value="${ext.min}" aria-label="Mínimo de ${escapeHtml(ext.name)}" /></td>`,
          `<td><input type="number" step="any" class="touch-control ts-bound-input" data-ext-field="max" data-idx="${i}" value="${ext.max}" aria-label="Máximo de ${escapeHtml(ext.name)}" /></td>`,
          `<td><label class="lmi-check-label"><input type="checkbox" data-ext-field="measured" data-idx="${i}"${ext.measured ? " checked" : ""} /><span>Medido</span></label></td>`,
          `<td><button type="button" class="touch-control btn-subtle btn-small" data-ext-remove="${i}" aria-label="Remover sinal externo ${escapeHtml(ext.name)}">×</button></td>`,
          `</tr>`,
        ].join(""),
      )
      .join("");
    slot.innerHTML = `<table class="accessible-data-table ts-compact-table" aria-label="Sinais externos e limites"><thead><tr><th scope="col">Sinal w_ext</th><th scope="col">Mín</th><th scope="col">Máx</th><th scope="col">Medição</th><th scope="col"></th></tr></thead><tbody>${rowsHtml}</tbody></table>`;

    for (const inp of Array.from(slot.querySelectorAll<HTMLInputElement>("[data-ext-field]"))) {
      const idx = Number(inp.getAttribute("data-idx") ?? "0");
      const field = inp.getAttribute("data-ext-field");
      const onEdit = (): void => {
        const row = this.draft.externals[idx];
        if (!row) return;
        if (field === "name") row.name = inp.value.trim() || `theta${idx + 1}`;
        else if (field === "min") row.min = Number(inp.value);
        else if (field === "max") row.max = Number(inp.value);
        else if (field === "measured") row.measured = inp.checked;
        this.draft.presetSource = "custom";
        this.updateLiveDiagnostics();
      };
      inp.addEventListener("change", onEdit);
      if (field !== "measured") inp.addEventListener("input", onEdit);
    }
    for (const btn of Array.from(slot.querySelectorAll<HTMLButtonElement>("[data-ext-remove]"))) {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-ext-remove") ?? "0");
        this.draft.externals.splice(idx, 1);
        this.draft.presetSource = "custom";
        this.renderExternalsTable();
        this.updateLiveDiagnostics();
      });
    }
  }

  private renderPremisesTable(): void {
    const slot = this.q<HTMLElement>("#ts-premises-slot");
    if (!slot) return;
    if (this.draft.premises.length === 0) {
      slot.innerHTML = `<p class="dock-item-summary">Nenhuma premissa definida. Clique em <strong>+ Adicionar premissa z_k</strong>.</p>`;
      return;
    }

    const rowsHtml = this.draft.premises
      .map((pr, i) => {
        const parsed = parseQlpvExpr(pr.expression);
        const sincBtn =
          parsed.hasSinOverArg && parsed.suggestedSincSource
            ? `<button type="button" class="touch-control btn-subtle btn-small ts-sinc-btn" data-premise-sinc="${i}" title="Substituir sin(u)/u por sinc_rad(u) contínuo em 0">Usar sinc_rad</button>`
            : "";
        const computedStr =
          pr.computedMin !== null && pr.computedMax !== null
            ? `[${formatNumericDisplay(pr.computedMin, 5)}, ${formatNumericDisplay(pr.computedMax, 5)}]`
            : "Clique em Calcular Extremos";
        return [
          `<tr data-premise-row="${i}">`,
          `<td><input type="text" class="touch-control ts-var-name-input" data-premise-field="name" data-idx="${i}" value="${escapeHtml(pr.name)}" aria-label="Identificador da premissa ${i + 1}" /></td>`,
          `<td class="ts-expr-cell"><div class="ts-expr-inline"><input type="text" class="touch-control ts-expr-input${parsed.ok ? "" : " lmi-input-invalid"}" data-premise-field="expression" data-idx="${i}" value="${escapeHtml(pr.expression)}" aria-label="Expressão de ${escapeHtml(pr.name)}" />${sincBtn}</div></td>`,
          `<td class="ts-computed-bounds-cell"><code>${escapeHtml(computedStr)}</code></td>`,
          `<td><div class="ts-override-pair"><input type="number" step="any" class="touch-control ts-bound-input" data-premise-field="userMin" data-idx="${i}" value="${escapeHtml(pr.userMin)}" placeholder="auto" aria-label="Override mínimo ${escapeHtml(pr.name)}" /><input type="number" step="any" class="touch-control ts-bound-input" data-premise-field="userMax" data-idx="${i}" value="${escapeHtml(pr.userMax)}" placeholder="auto" aria-label="Override máximo ${escapeHtml(pr.name)}" /></div></td>`,
          `<td><label class="lmi-check-label"><input type="checkbox" data-premise-field="measured" data-idx="${i}"${pr.measured ? " checked" : ""} /><span>Sim</span></label></td>`,
          `<td><button type="button" class="touch-control btn-subtle btn-small" data-premise-remove="${i}" aria-label="Remover premissa ${escapeHtml(pr.name)}">×</button></td>`,
          `</tr>`,
        ].join("");
      })
      .join("");

    slot.innerHTML = `<table class="accessible-data-table ts-compact-table" aria-label="Variáveis premissas de setor"><thead><tr><th scope="col">Premissa</th><th scope="col">Relação g_k(x, w_ext)</th><th scope="col">Extremos [z_min, z_max]</th><th scope="col">Override [mín, máx]</th><th scope="col">Medida</th><th scope="col"></th></tr></thead><tbody>${rowsHtml}</tbody></table>`;

    for (const inp of Array.from(slot.querySelectorAll<HTMLInputElement>("[data-premise-field]"))) {
      const idx = Number(inp.getAttribute("data-idx") ?? "0");
      const field = inp.getAttribute("data-premise-field");
      const onEdit = (): void => {
        const row = this.draft.premises[idx];
        if (!row) return;
        if (field === "name") {
          row.name = inp.value.trim() || `z${idx + 1}`;
        } else if (field === "expression") {
          row.expression = inp.value;
          row.computedMin = null;
          row.computedMax = null;
          const p = parseQlpvExpr(row.expression);
          row.activeVariables = p.activeVariables;
          inp.className = `touch-control ts-expr-input${p.ok ? "" : " lmi-input-invalid"}`;
        } else if (field === "userMin") {
          row.userMin = inp.value;
        } else if (field === "userMax") {
          row.userMax = inp.value;
        } else if (field === "measured") {
          row.measured = inp.checked;
        }
        this.draft.presetSource = "custom";
        this.updateLiveDiagnostics();
      };
      inp.addEventListener("change", () => {
        onEdit();
        if (field === "expression") this.renderPremisesTable();
      });
      if (field !== "measured") inp.addEventListener("input", onEdit);
    }

    for (const sBtn of Array.from(slot.querySelectorAll<HTMLButtonElement>("[data-premise-sinc]"))) {
      sBtn.addEventListener("click", () => {
        const idx = Number(sBtn.getAttribute("data-premise-sinc") ?? "0");
        const row = this.draft.premises[idx];
        if (!row) return;
        const p = parseQlpvExpr(row.expression);
        if (p.suggestedSincSource) {
          row.expression = p.suggestedSincSource;
          row.computedMin = null;
          row.computedMax = null;
          this.renderPremisesTable();
          this.updateLiveDiagnostics();
        }
      });
    }

    for (const rBtn of Array.from(
      slot.querySelectorAll<HTMLButtonElement>("[data-premise-remove]"),
    )) {
      rBtn.addEventListener("click", () => {
        const idx = Number(rBtn.getAttribute("data-premise-remove") ?? "0");
        if (this.draft.premises.length <= 1) {
          this.shell.presentError(
            new ControlLabBridgeError(
              "VALIDATION_ERROR",
              "A Via 1 requer pelo menos 1 variável premissa.",
            ),
          );
          return;
        }
        this.draft.premises.splice(idx, 1);
        this.draft.presetSource = "custom";
        this.renderPremisesTable();
        this.updateLiveDiagnostics();
      });
    }
  }

  private syncMatrixFilterButtons(): void {
    for (const btn of Array.from(
      this.container.querySelectorAll<HTMLButtonElement>("[data-matrix-filter]"),
    )) {
      const mf = btn.getAttribute("data-matrix-filter");
      btn.setAttribute("aria-pressed", mf === this.matrixFilter ? "true" : "false");
    }
  }

  private renderSymbolicMatrices(): void {
    const slot = this.q<HTMLElement>("#ts-symbolic-matrices-slot");
    if (!slot) return;
    const mats = this.via === "sector" ? this.draft.sectorMatrices : this.draft.directMatrices;
    const argLabel = this.via === "sector" ? "z" : "x, w";

    const entries: Array<{ key: keyof TsSymbolicSystemMatrices; title: string }> = [];
    if (this.matrixFilter === "all") {
      entries.push(
        { key: "A", title: `A(${argLabel}) [${this.draft.n}×${this.draft.n}]` },
        { key: "B", title: `B(${argLabel}) [${this.draft.n}×${this.draft.m}]` },
        { key: "C", title: `C(${argLabel}) [${this.draft.p}×${this.draft.n}]` },
        { key: "D", title: `D(${argLabel}) [${this.draft.p}×${this.draft.m}]` },
      );
    } else if (this.matrixFilter === "gen" && this.draft.enableGeneralized) {
      entries.push(
        { key: "Bw", title: `Bw(${argLabel}) [${this.draft.n}×${this.draft.nw}]` },
        { key: "Dyw", title: `Dyw(${argLabel}) [${this.draft.p}×${this.draft.nw}]` },
        { key: "Cz", title: `Cz(${argLabel}) [${this.draft.nz}×${this.draft.n}]` },
        { key: "Dzu", title: `Dzu(${argLabel}) [${this.draft.nz}×${this.draft.m}]` },
        { key: "Dzw", title: `Dzw(${argLabel}) [${this.draft.nz}×${this.draft.nw}]` },
      );
    } else if (
      this.matrixFilter === "A" ||
      this.matrixFilter === "B" ||
      this.matrixFilter === "C" ||
      this.matrixFilter === "D"
    ) {
      const k = this.matrixFilter;
      const mat = mats[k];
      entries.push({
        key: k,
        title: `${k}(${argLabel}) [${mat.length}×${mat[0]?.length ?? 1}]`,
      });
    }

    slot.innerHTML = entries
      .map(({ key, title }) => {
        const grid = mats[key];
        const rowsHtml = grid
          .map(
            (row, r) =>
              `<tr>${row
                .map((cell, c) => {
                  const ok = parseQlpvExpr(cell).ok;
                  return `<td><input type="text" class="touch-control ts-matrix-cell-input${ok ? "" : " lmi-input-invalid"}" data-mat-key="${key}" data-row="${r}" data-col="${c}" value="${escapeHtml(cell)}" aria-label="${key}(${r + 1},${c + 1})" /></td>`;
                })
                .join("")}</tr>`,
          )
          .join("");
        return `<div class="ts-matrix-box"><h6>${escapeHtml(title)}</h6><div class="ts-matrix-scroll"><table class="ts-matrix-table" aria-label="Matriz ${escapeHtml(title)}"><tbody>${rowsHtml}</tbody></table></div></div>`;
      })
      .join("");

    for (const cellIn of Array.from(
      slot.querySelectorAll<HTMLInputElement>("[data-mat-key]"),
    )) {
      const mKey = cellIn.getAttribute("data-mat-key") as keyof TsSymbolicSystemMatrices;
      const r = Number(cellIn.getAttribute("data-row") ?? "0");
      const c = Number(cellIn.getAttribute("data-col") ?? "0");
      const onCellInput = (): void => {
        const target =
          this.via === "sector" ? this.draft.sectorMatrices : this.draft.directMatrices;
        if (target[mKey]?.[r]) {
          target[mKey][r][c] = cellIn.value;
        }
        const parsed = parseQlpvExpr(cellIn.value);
        cellIn.className = `touch-control ts-matrix-cell-input${parsed.ok ? "" : " lmi-input-invalid"}`;
        this.draft.presetSource = "custom";
        this.updateLiveDiagnostics();
      };
      cellIn.addEventListener("input", onCellInput);
      cellIn.addEventListener("change", onCellInput);
    }
  }

  private renderPerAxisTable(): void {
    const slot = this.q<HTMLElement>("#ts-per-axis-slot");
    if (!slot || this.via === "sector") return;

    const stateNames = this.draft.states.map((s) => s.name.trim());
    const extNames = this.draft.externals.map((e) => e.name.trim());
    const dm = this.draft.directMatrices;
    const inspected = inspectDirectQlpvMatrices(
      {
        A: dm.A,
        B: dm.B,
        C: dm.C,
        D: dm.D,
        ...(this.draft.enableGeneralized
          ? { Bw: dm.Bw, Dyw: dm.Dyw, Cz: dm.Cz, Dzu: dm.Dzu, Dzw: dm.Dzw }
          : {}),
      },
      stateNames,
      extNames,
    );

    const activeVars = inspected.activeVariables;
    if (activeVars.length === 0) {
      slot.innerHTML = `<p class="dock-item-summary">Nenhuma variável não-linear ativa detectada nas matrizes diretas (sistema LTI constante — 1 regra trivial).</p>`;
      return;
    }

    const boundsLookup: Record<string, [number, number]> = {};
    for (const s of this.draft.states) boundsLookup[s.name.trim()] = [s.min, s.max];
    for (const e of this.draft.externals) boundsLookup[e.name.trim()] = [e.min, e.max];

    for (const v of activeVars) {
      if (!this.draft.axisSettings[v]) {
        this.draft.axisSettings[v] = defaultAxisConfig(15);
      }
    }

    if (this.via === "tpmt") {
      const rows = activeVars
        .map((v, d) => {
          const cfg = this.draft.axisSettings[v];
          const b = boundsLookup[v] ?? [-1, 1];
          const hullOpts = TS_HULLS.map(
            (h) => `<option value="${h}"${cfg.hull === h ? " selected" : ""}>${h}</option>`,
          ).join("");
          return [
            `<tr>`,
            `<th scope="row">Modo ${d + 1}: <code>${escapeHtml(v)}</code> ∈ [${formatNumericDisplay(b[0], 3)}, ${formatNumericDisplay(b[1], 3)}]</th>`,
            `<td><input type="number" min="3" max="201" step="1" class="touch-control id-param-input" data-axis-var="${escapeHtml(v)}" data-axis-field="gridPoints" value="${cfg.gridPoints}" aria-label="Pontos G_${d + 1} para ${escapeHtml(v)}" /></td>`,
            `<td><input type="number" min="1" max="64" step="1" class="touch-control id-param-input" data-axis-var="${escapeHtml(v)}" data-axis-field="rank" value="${escapeHtml(cfg.rank)}" placeholder="Auto" aria-label="Posto R_${d + 1} para ${escapeHtml(v)}" /></td>`,
            `<td><select class="touch-control" data-axis-var="${escapeHtml(v)}" data-axis-field="hull" aria-label="Fecho convexo para ${escapeHtml(v)}">${hullOpts}</select></td>`,
            `<td><input type="number" min="5" max="1001" step="1" class="touch-control id-param-input" data-axis-var="${escapeHtml(v)}" data-axis-field="resamplePoints" value="${escapeHtml(cfg.resamplePoints)}" placeholder="Off" aria-label="Reamostragem fina para ${escapeHtml(v)}" /></td>`,
            `</tr>`,
          ].join("");
        })
        .join("");

      slot.innerHTML = `<table class="accessible-data-table ts-compact-table" aria-label="Discretização por dimensão TPMT"><thead><tr><th scope="col">Variável Ativa p_d</th><th scope="col">Pontos G_d</th><th scope="col">Posto R_d</th><th scope="col">Fecho Convexo</th><th scope="col">Grade Fina (opc.)</th></tr></thead><tbody>${rows}</tbody></table>`;
    } else {
      const rows = activeVars
        .map((v, d) => {
          const cfg = this.draft.axisSettings[v];
          const b = boundsLookup[v] ?? [-1, 1];
          return [
            `<tr>`,
            `<th scope="row">Eixo ${d + 1}: <code>${escapeHtml(v)}</code> ∈ [${formatNumericDisplay(b[0], 3)}, ${formatNumericDisplay(b[1], 3)}]</th>`,
            `<td><input type="number" min="3" max="201" step="1" class="touch-control id-param-input" data-axis-var="${escapeHtml(v)}" data-axis-field="gridPoints" value="${cfg.gridPoints}" aria-label="Nós G_${d + 1} para ${escapeHtml(v)}" /></td>`,
            `</tr>`,
          ].join("");
        })
        .join("");
      slot.innerHTML = `<table class="accessible-data-table ts-compact-table" aria-label="Discretização nodal por dimensão FEMT"><thead><tr><th scope="col">Variável Ativa p_d</th><th scope="col">Nós Amostrados G_d</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    for (const el of Array.from(
      slot.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[data-axis-var]"),
    )) {
      const vName = el.getAttribute("data-axis-var") ?? "";
      const field = el.getAttribute("data-axis-field");
      const onAxisChange = (): void => {
        const cfg = this.draft.axisSettings[vName];
        if (!cfg) return;
        if (field === "gridPoints") cfg.gridPoints = Number(el.value);
        else if (field === "rank") cfg.rank = el.value.trim();
        else if (field === "hull" && (TS_HULLS as readonly string[]).includes(el.value)) {
          cfg.hull = el.value as TsHull;
        } else if (field === "resamplePoints") cfg.resamplePoints = el.value.trim();
        this.updateLiveDiagnostics();
      };
      el.addEventListener("change", onAxisChange);
      if (field === "gridPoints") el.addEventListener("input", onAxisChange);
    }
  }

  private inferCurrentKind(): DerivedTsKind {
    const unmeasuredVars = new Set<string>();
    for (const s of this.draft.states) {
      if (!s.measured) unmeasuredVars.add(s.name.trim());
    }
    for (const e of this.draft.externals) {
      if (!e.measured) unmeasuredVars.add(e.name.trim());
    }

    if (this.via === "sector") {
      for (const pr of this.draft.premises) {
        if (!pr.measured) return "ts_partially_observed";
        const parsed = parseQlpvExpr(pr.expression);
        if (parsed.activeVariables.some((v) => unmeasuredVars.has(v))) {
          return "ts_partially_observed";
        }
      }
      return "ts_measured";
    }

    const dm = this.draft.directMatrices;
    const inspected = inspectDirectQlpvMatrices(
      { A: dm.A, B: dm.B, C: dm.C, D: dm.D },
      this.draft.states.map((s) => s.name.trim()),
      this.draft.externals.map((e) => e.name.trim()),
    );
    return inspected.activeVariables.some((v) => unmeasuredVars.has(v))
      ? "ts_partially_observed"
      : "ts_measured";
  }

  private updateLiveDiagnostics(forceAxisRebuild = false): void {
    // 1. Classificação inferida (Zona 2)
    const kind = this.inferCurrentKind();
    const kindBadge = this.q<HTMLElement>("#ts-inferred-kind-badge");
    if (kindBadge) {
      kindBadge.textContent =
        kind === "ts_measured"
          ? "Classificação inferida: ts_measured (Premissas medidas — PDC direto)"
          : "Classificação inferida: ts_partially_observed (Requer observador TS na Aba 7)";
      kindBadge.className = `ts-kind-badge ${kind === "ts_measured" ? "is-measured" : "is-partial"}`;
    }

    // 2. Contador de regras e auditoria de afinidade na Via 1
    const nn = this.draft.premises.length;
    const ruleCounter = this.q<HTMLElement>("#ts-sector-rule-counter");
    if (ruleCounter) {
      ruleCounter.textContent = `${nn} premissa${nn === 1 ? "" : "s"} ⇒ 2^${nn} = ${Math.pow(2, nn)} regras`;
    }

    const secBanner = this.q<HTMLElement>("#ts-sector-affinity-banner");
    if (secBanner && this.via === "sector") {
      const premBounds: Record<string, [number, number]> = {};
      for (const pr of this.draft.premises) {
        if (pr.computedMin !== null && pr.computedMax !== null) {
          premBounds[pr.name.trim()] = [pr.computedMin, pr.computedMax];
        }
      }
      const sm = this.draft.sectorMatrices;
      const diags = auditSectorMatrices(
        {
          A: sm.A,
          B: sm.B,
          C: sm.C,
          D: sm.D,
          ...(this.draft.enableGeneralized
            ? { Bw: sm.Bw, Dyw: sm.Dyw, Cz: sm.Cz, Dzu: sm.Dzu, Dzw: sm.Dzw }
            : {}),
        },
        this.draft.premises.map((p) => p.name.trim()),
        [
          ...this.draft.states.map((s) => s.name.trim()),
          ...this.draft.externals.map((e) => e.name.trim()),
        ],
        premBounds,
      );
      if (diags.length === 0) {
        secBanner.className = "ts-diagnostic-banner is-ok";
        secBanner.innerHTML = `<strong>✓ Afinidade multilinear verificada:</strong> todas as entradas de <code>S(z)</code> dependem apenas das premissas declaradas <code>{${escapeHtml(this.draft.premises.map((p) => p.name.trim()).join(", "))}}</code> de forma afim por coordenada.`;
      } else {
        secBanner.className = "ts-diagnostic-banner is-warn";
        secBanner.innerHTML = `<strong>Atenção estrutural na Via 1:</strong> ${escapeHtml(diags[0].message)}`;
      }
    }

    // 3. Extração de variáveis não-lineares ativas + Envelope Wasm (Vias 2 e 3)
    const activeBar = this.q<HTMLElement>("#ts-active-vars-bar");
    if (this.via !== "sector") {
      const dm = this.draft.directMatrices;
      const inspected = inspectDirectQlpvMatrices(
        {
          A: dm.A,
          B: dm.B,
          C: dm.C,
          D: dm.D,
          ...(this.draft.enableGeneralized
            ? { Bw: dm.Bw, Dyw: dm.Dyw, Cz: dm.Cz, Dzu: dm.Dzu, Dzw: dm.Dzw }
            : {}),
        },
        this.draft.states.map((s) => s.name.trim()),
        this.draft.externals.map((e) => e.name.trim()),
      );
      const axisKey = `${this.via}:${inspected.activeVariables.join(",")}`;
      if (forceAxisRebuild || axisKey !== this.lastActiveAxisKey) {
        this.lastActiveAxisKey = axisKey;
        this.renderPerAxisTable();
      }
      if (activeBar) {
        if (inspected.errors.length > 0) {
          activeBar.className = "ts-diagnostic-banner is-warn";
          activeBar.innerHTML = `<strong>Erro nas matrizes diretas:</strong> ${escapeHtml(inspected.errors[0])}`;
        } else {
          const dCount = inspected.activeVariables.length;
          const gDims = inspected.activeVariables.map(
            (v) => this.draft.axisSettings[v]?.gridPoints ?? 15,
          );
          const totalNodes = gDims.reduce((acc, g) => acc * (Number.isFinite(g) ? g : 15), 1);
          const m1 = this.draft.n + this.draft.p + (this.draft.enableGeneralized ? this.draft.nz : 0);
          const m2 = this.draft.n + this.draft.m + (this.draft.enableGeneralized ? this.draft.nw : 0);
          const scalarCount = totalNodes * m1 * m2;
          const approxMb = (scalarCount * 8) / (1024 * 1024);
          const overTeto = dCount > 5 || totalNodes > 250_000 || scalarCount > 10_000_000;
          const nearLimit = dCount > 3 || totalNodes > 50_000 || scalarCount > 2_000_000;
          activeBar.className = `ts-diagnostic-banner ${overTeto ? "is-warn" : "is-ok"}`;
          const shapeInfo =
            this.via === "tpmt"
              ? `Tensor 𝒮ᴰ ∈ ℝ^(${gDims.length ? gDims.join("×") : "1"}×${m1}×${m2})`
              : `Matriz empilhada X ∈ ℝ^(${m1 * m2} × ${totalNodes})`;
          const linInfo =
            inspected.linearOnlyStates.length > 0
              ? ` • Estados puramente lineares poupados: <code>${escapeHtml(inspected.linearOnlyStates.join(", "))}</code>`
              : "";
          const memTag = overTeto
            ? `Acima do teto Wasm (~${approxMb.toFixed(1)} MB) — reduza G_d ou exporte script Python/MATLAB`
            : nearLimit
              ? `Malha densa (~${approxMb.toFixed(1)} MB)`
              : `Envelope interativo seguro (~${approxMb.toFixed(2)} MB)`;
          activeBar.innerHTML = `<strong>Variáveis não-lineares ativas (D = ${dCount}):</strong> <code>${escapeHtml(inspected.activeVariables.join(", ") || "nenhuma")}</code>${linInfo} • <strong>N_g = ${totalNodes}</strong> nós • ${escapeHtml(shapeInfo)} • <span>${escapeHtml(memTag)}</span>`;
        }
      }
    }
    this.syncStaleState();
  }

  public setStatus(text: string): void {
    this.statusText = text;
    const el = this.q<HTMLElement>("#ts-status");
    if (el) el.textContent = text;
  }

  private requireClient(): TsModelingEngineClient {
    if (!supportsTsModeling(this.client)) {
      throw new ControlLabBridgeError(
        "SOLVER_UNAVAILABLE",
        "O motor atual não expõe as operações de modelagem TS.",
      );
    }
    return this.client;
  }

  private context(): TsModelingContext {
    const lqr = this.shell.getLqrWorkspace();
    const projectId = lqr.getProjectId();
    return {
      request_id: `ts-modeling-${generateUuid()}`,
      project_id: projectId,
      project_revision: Math.max(
        lqr.getProjectRevision(),
        this.client.getCommittedRevision(projectId),
      ),
    };
  }

  private unwrap<T extends Record<string, unknown>>(
    resp: TsRpcResponse<T>,
    fallback: string,
  ): { data: T; warnings: Array<{ code: string; message: string }> } {
    if (resp.status === "failure" || !resp.result) {
      throw new ControlLabBridgeError(
        resp.error?.code ?? "INTERNAL_ERROR",
        resp.error?.message ?? fallback,
      );
    }
    const warnings = Array.isArray(resp.warnings)
      ? resp.warnings.map((w) =>
          typeof w === "string"
            ? { code: "WARNING", message: w }
            : { code: String(w.code ?? "WARNING"), message: String(w.message ?? "") },
        )
      : [];
    return { data: resp.result, warnings };
  }

  private async withBusy(task: () => Promise<void>): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.syncActionButtons();
    try {
      await task();
    } catch (err: unknown) {
      this.setStatus("Operação interrompida: verifique o diagnóstico exibido acima.");
      this.shell.presentError(err);
    } finally {
      this.busy = false;
      this.syncActionButtons();
      this.onRequestRender?.();
    }
  }

  public async analyze(): Promise<void> {
    await this.withBusy(async () => {
      const client = this.requireClient();
      const payload = buildTsPayloadFromDraft(this.draft, "sector");
      const { data: res, warnings } = this.unwrap(
        await client.analyzeSectorPremises(this.context(), {
          premises: payload.premises as SectorPremiseSpec[],
          state_bounds: payload.state_bounds as Record<string, [number, number]>,
          ...(payload.external_bounds
            ? { external_bounds: payload.external_bounds as Record<string, [number, number]> }
            : {}),
          ...(payload.measured_states
            ? { measured_states: payload.measured_states as Record<string, boolean> }
            : {}),
          ...(payload.measured_externals
            ? { measured_externals: payload.measured_externals as Record<string, boolean> }
            : {}),
        }),
        "Falha ao analisar extremos globais das premissas.",
      );

      res.premises.forEach((ap: AnalyzedSectorPremise, idx: number) => {
        const target =
          this.draft.premises.find((p) => p.name.trim() === ap.name) ?? this.draft.premises[idx];
        if (target) {
          target.computedMin = ap.min;
          target.computedMax = ap.max;
          target.activeVariables = ap.active_variables ?? [];
        }
      });
      this.renderPremisesTable();
      this.updateLiveDiagnostics();

      const rows = res.premises
        .map(
          (p) =>
            `<tr><th scope="row"><code>${escapeHtml(p.name)}</code></th><td><code>${escapeHtml(p.expression)}</code></td><td>${escapeHtml(p.active_variables.join(", ") || "constante")}</td><td>${escapeHtml(formatNumericDisplay(p.min, 6))}</td><td>${escapeHtml(formatNumericDisplay(p.max, 6))}</td></tr>`,
        )
        .join("");
      const warnHtml =
        warnings.length > 0
          ? `<ul class="ts-warnings-list">${warnings.map((w) => `<li><strong>${escapeHtml(w.code)}:</strong> ${escapeHtml(w.message)}</li>`).join("")}</ul>`
          : "";
      const summary = this.q<HTMLElement>("#ts-summary");
      if (summary) {
        summary.innerHTML = [
          `<h4>Extremos Globais das Premissas Certificados</h4>`,
          `<p><strong>${res.num_premises}</strong> premissas ⇒ <strong id="ts-analysis-rules">${res.num_rules}</strong> regras (2ⁿⁿ) • Classificação: <code>${escapeHtml(res.inferred_kind)}</code> (${escapeHtml(res.premise_availability.mode)}).</p>`,
          warnHtml,
          `<table class="accessible-data-table ts-compact-table" aria-label="Extremos certificados das premissas"><thead><tr><th scope="col">Premissa</th><th scope="col">Expressão</th><th scope="col">Vars. Ativas</th><th scope="col">z_min</th><th scope="col">z_max</th></tr></thead><tbody>${rows}</tbody></table>`,
        ].join("");
      }
      this.setStatus(`Análise concluída: ${res.num_premises} premissas ⇒ ${res.num_rules} regras.`);
    });
  }

  private async runVia(
    client: TsModelingEngineClient,
    via: TsVia,
    payload: Record<string, unknown>,
  ): Promise<{ data: TsDerivationResult; warnings: Array<{ code: string; message: string }> }> {
    const ctx = this.context();
    if (via === "sector") {
      return this.unwrap<DerivedTsSectorResult>(
        await client.deriveTsSector(
          ctx,
          payload as unknown as Parameters<TsModelingEngineClient["deriveTsSector"]>[1],
        ),
        "Falha na derivação por Não-Linearidade de Setor.",
      );
    }
    if (via === "tpmt") {
      return this.unwrap<DerivedTsTpmtResult>(
        await client.deriveTsTpmt(
          ctx,
          payload as unknown as Parameters<TsModelingEngineClient["deriveTsTpmt"]>[1],
        ),
        "Falha na derivação por Produto Tensorial (TPMT).",
      );
    }
    return this.unwrap<DerivedTsFemtResult>(
      await client.deriveTsFemt(
        ctx,
        payload as unknown as Parameters<TsModelingEngineClient["deriveTsFemt"]>[1],
      ),
      "Falha na derivação por Elementos Finitos (FEMT).",
    );
  }

  public async derive(): Promise<void> {
    await this.withBusy(async () => {
      const client = this.requireClient();
      const activeVia = this.via;
      const snapshotDraft = structuredClone(this.draft);
      const payload = buildTsPayloadFromDraft(snapshotDraft, activeVia);
      const { data, warnings } = await this.runVia(client, activeVia, payload);
      this.result = data;
      this.resultVia = activeVia;
      this.resultWarnings = warnings;
      this.lastSubmittedPayload = payload;
      this.registeredKey = null;
      this.selectedVertexIdx = 0;
      this.selectedChartAxisIdx = 0;
      this.selectedChartRuleIdx = 0;
      this.chartsCacheKey = "";

      if (activeVia === "sector" && "premises" in data && Array.isArray(data.premises)) {
        data.premises.forEach((ap, idx) => {
          const target =
            this.draft.premises.find((p) => p.name.trim() === ap.name) ?? this.draft.premises[idx];
          if (target) {
            target.computedMin = ap.min;
            target.computedMax = ap.max;
          }
          const snapTarget =
            snapshotDraft.premises.find((p) => p.name.trim() === ap.name) ??
            snapshotDraft.premises[idx];
          if (snapTarget) {
            snapTarget.computedMin = ap.min;
            snapTarget.computedMax = ap.max;
          }
        });
        this.renderPremisesTable();
      }

      this.lastDerivedDraftSnapshot = structuredClone(snapshotDraft);
      this.lastDerivedSignature = serializeDraftDerivationSignature(
        this.lastDerivedDraftSnapshot,
        activeVia,
      );

      this.syncStaleState();
      this.syncChartSelectors();
      this.renderSummary();
      this.renderVertexInspector();
      this.renderCharts(this.shell.getThemeMode());
      this.setStatus(
        `Modelo TS '${data.model_id}' gerado pela via ${activeVia.toUpperCase()} com ${data.num_rules} regras.`,
      );
      this.shell
        .getAnnouncer()
        .announce(
          `Modelo TS obtido com ${data.num_rules} regras pela via ${activeVia}.`,
          "polite",
          "status",
        );
    });
  }

  public async compare(): Promise<void> {
    await this.withBusy(async () => {
      const client = this.requireClient();
      // Se o usuário estiver na Via 1 e pedir comparação, garante que S(x,w) esteja sincronizada
      if (this.via === "sector" && this.draft.premises.length > 0) {
        this.syncSectorToDirectMatrices();
      }

      const rows: Array<{
        label: string;
        rules: number;
        gridErr: string;
        valErr: string;
        badge: string;
      }> = [];

      // Tenta Setor se houver premissas válidas sem erro de afinidade
      if (this.draft.premises.length > 0) {
        const sm = this.draft.sectorMatrices;
        const secDiags = auditSectorMatrices(
          { A: sm.A, B: sm.B, C: sm.C, D: sm.D },
          this.draft.premises.map((p) => p.name.trim()),
          [
            ...this.draft.states.map((s) => s.name.trim()),
            ...this.draft.externals.map((e) => e.name.trim()),
          ],
        );
        if (secDiags.length === 0) {
          try {
            const pSec = buildTsPayloadFromDraft(this.draft, "sector");
            const { data: rSec } = await this.runVia(client, "sector", pSec);
            const c = rSec.fidelity_certificate;
            rows.push({
              label: "Via 1 — Setor (2ⁿⁿ)",
              rules: rSec.num_rules,
              gridErr: "0 (analítico)",
              valErr:
                typeof c.rel_l2_error === "number"
                  ? c.rel_l2_error.toExponential(2)
                  : typeof c.val_rel_l2_error === "number"
                    ? c.val_rel_l2_error.toExponential(2)
                    : "0",
              badge: String(c.verification_badge ?? "EXACT"),
            });
          } catch {
            // Ignora Via 1 se o usuário editou apenas matrizes diretas
          }
        }
      }

      const pTpmt = buildTsPayloadFromDraft(this.draft, "tpmt");
      const pFemt = buildTsPayloadFromDraft(this.draft, "femt");
      const [{ data: rTpmt }, { data: rFemt }] = await Promise.all([
        this.runVia(client, "tpmt", pTpmt),
        this.runVia(client, "femt", pFemt),
      ]);

      const fmtCert = (
        label: string,
        res: TsDerivationResult,
      ): { label: string; rules: number; gridErr: string; valErr: string; badge: string } => {
        const c = res.fidelity_certificate;
        return {
          label,
          rules: res.num_rules,
          gridErr:
            typeof c.grid_rel_l2_error === "number" ? c.grid_rel_l2_error.toExponential(2) : "—",
          valErr:
            typeof c.val_rel_l2_error === "number" ? c.val_rel_l2_error.toExponential(2) : "—",
          badge: String(c.verification_badge ?? "—"),
        };
      };
      rows.push(fmtCert("Via 2 — TPMT (Produto Tensorial)", rTpmt));
      rows.push(fmtCert("Via 3 — FEMT (Elementos Finitos SVD)", rFemt));

      const bodyHtml = rows
        .map(
          (r) =>
            `<tr><th scope="row">${escapeHtml(r.label)}</th><td><strong>${r.rules}</strong></td><td><code>${escapeHtml(r.gridErr)}</code></td><td><code>${escapeHtml(r.valErr)}</code></td><td><code>${escapeHtml(r.badge)}</code></td></tr>`,
        )
        .join("");

      const reductionNote =
        rFemt.num_rules < rTpmt.num_rules
          ? `<p class="ts-reduction-highlight">✓ Redução algébrica confirmada: a <strong>FEMT</strong> exigiu apenas <strong>${rFemt.num_rules}</strong> regras contra <strong>${rTpmt.num_rules}</strong> da <strong>TPMT</strong> sobre a planta atual.</p>`
          : "";

      this.compareHtml = [
        `<h5>Comparativo entre Vias na Planta qLPV Atual</h5>`,
        reductionNote,
        `<table class="accessible-data-table ts-compact-table" aria-label="Comparativo entre Setor, TPMT e FEMT"><thead><tr><th scope="col">Via</th><th scope="col">Nº Regras N_r</th><th scope="col">Erro Rel. Grade</th><th scope="col">Erro Rel. Off-Grid</th><th scope="col">Selo</th></tr></thead><tbody>${bodyHtml}</tbody></table>`,
      ].join("");

      const compareSlot = this.q<HTMLElement>("#ts-compare-slot");
      if (compareSlot) {
        compareSlot.innerHTML = this.compareHtml;
        setElHidden(compareSlot, false);
      }
      this.setStatus(
        `Comparativo concluído na planta atual: TPMT = ${rTpmt.num_rules} regras vs FEMT = ${rFemt.num_rules} regras.`,
      );
    });
  }

  public async register(openLmi: boolean): Promise<void> {
    await this.withBusy(async () => {
      if (!this.result || !this.resultVia || !this.lastDerivedDraftSnapshot) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Valide e gere um modelo TS antes de registrá-lo no Workspace.",
        );
      }
      if (this.isLastDerivationStale()) {
        this.syncStaleState();
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Especificação alterada desde a última derivação — clique em Derivar novamente antes de registrar no Workspace.",
        );
      }
      const frozenDraft = structuredClone(this.lastDerivedDraftSnapshot);
      const typed = this.shell.getTypedWorkspace();
      const dto = structuredClone(this.result.ts_state_space) as Record<string, unknown>;
      const customId = frozenDraft.modelId.trim();
      if (customId) dto.id = customId;

      const existing = typed
        .listRegisteredObjects()
        .filter((o) => o.id === String(dto.id));
      const maxRev = existing.reduce((m, o) => Math.max(m, o.revision), 0);
      const revNow = typeof dto.revision === "number" ? dto.revision : 0;
      dto.revision = Math.max(revNow, maxRev + 1);

      const prov = isPlainObject(dto.provenance) ? { ...dto.provenance } : {};
      const derivation = isPlainObject(prov.ts_derivation) ? { ...prov.ts_derivation } : {};
      derivation.recipe = {
        via: this.resultVia,
        preset: frozenDraft.presetSource === "custom" ? null : frozenDraft.presetSource,
        draft: frozenDraft,
        payload: structuredClone(this.lastSubmittedPayload ?? {}),
      };
      prov.ts_derivation = derivation;
      dto.provenance = prov;

      const reg = await typed.registerTypedObject(dto, {
        selectRole: "tsModel",
        source: "manual",
      });
      this.registeredKey = reg.key;
      this.setStatus(
        `Modelo '${reg.id}#r${reg.revision}' (${reg.kind}) registrado no Workspace Dock.`,
      );
      this.shell
        .getAnnouncer()
        .announce(
          `Modelo TS '${reg.id}#r${reg.revision}' registrado no Workspace.`,
          "polite",
          "status",
        );
      if (openLmi) {
        this.onRouteToLmi?.(reg.key);
        this.shell.switchTab("optimization_lmi");
      }
    });
  }

  private recipeOptions(): Array<{ key: string; label: string }> {
    const typed = this.shell.getTypedWorkspace();
    return typed
      .listRegisteredObjects(["ts_measured", "ts_partially_observed"])
      .filter((o) => extractRecipeFromProvenance(o.value) !== null)
      .map((o) => ({ key: o.key, label: `${o.id}#r${o.revision}` }));
  }

  public reloadRecipe(refKey?: string): void {
    try {
      const sel = this.q<HTMLSelectElement>("#ts-recipe-select");
      const key = refKey ?? sel?.value ?? "";
      const typed = this.shell.getTypedWorkspace();
      const obj = typed
        .listRegisteredObjects(["ts_measured", "ts_partially_observed"])
        .find((o) => o.key === key);
      if (!obj) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Selecione um modelo TS registrado no Workspace que possua receita de derivação.",
        );
      }
      const recipe = extractRecipeFromProvenance(obj.value);
      if (!recipe) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "O modelo selecionado não possui provenance.ts_derivation.",
        );
      }
      this.via = recipe.via;
      if (recipe.draft) {
        this.draft = structuredClone(recipe.draft);
      } else if (recipe.preset && isTsPresetId(recipe.preset)) {
        this.draft = TS_PRESETS[recipe.preset].buildDraft();
      }
      this.lastActiveAxisKey = "";
      this.clearDerivedResult();
      this.rebuildEditableSections();
      this.setStatus(
        `Receita de '${obj.id}#r${obj.revision}' recarregada integralmente na bancada (${recipe.via}).`,
      );
      this.onRequestRender?.();
      this.render();
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  public async exportScript(
    language: TsDerivationLanguage,
    trigger: HTMLElement | null,
  ): Promise<void> {
    await this.withBusy(async () => {
      if (!this.result) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Gere um modelo TS antes de exportar scripts Python ou MATLAB.",
        );
      }
      if (this.isLastDerivationStale()) {
        this.syncStaleState();
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Especificação alterada desde a última derivação — clique em Derivar novamente antes de exportar o script.",
        );
      }
      const client = this.requireClient();
      const { data: res } = this.unwrap(
        await client.exportTsDerivationScript(this.context(), {
          language,
          model: structuredClone(this.result.ts_state_space) as Record<string, unknown>,
        }),
        "Falha ao exportar script passivo de derivação TS.",
      );
      if (res.code_executed !== false || typeof res.script !== "string") {
        throw new ControlLabBridgeError(
          "INTERNAL_ERROR",
          "Violação de contrato: script exportado deve ser estritamente passivo (code_executed=false).",
        );
      }
      this.onOpenExportModal?.(
        {
          title: `Script ${language === "python" ? "Python (NumPy/SciPy)" : "MATLAB"} de Derivação TS`,
          filename: res.filename,
          mimeType: `${res.media_type};charset=utf-8`,
          content: res.script,
          offlineDesign: true,
        },
        trigger,
      );
      this.setStatus(`Script ${res.filename} gerado em modo passivo.`);
    });
  }

  private syncChartSelectors(): void {
    if (!this.result) return;
    const axisSel = this.q<HTMLSelectElement>("#ts-chart-axis-select");
    const ruleSel = this.q<HTMLSelectElement>("#ts-chart-rule-select");
    const spec = this.result.ts_state_space.membership_spec;

    let axisLabels: string[] = [];
    if (spec.representation_kind === "sector_nonlinearity") {
      axisLabels = spec.sector_premises.map((p, i) => `Premissa ${i + 1}: ${p.name}`);
    } else if (spec.representation_kind === "tpmt_interpolated") {
      axisLabels = spec.tpmt_axes.map((a, i) => `Modo ${i + 1}: ${a.variable}`);
    } else if (spec.representation_kind === "femt_simplicial") {
      axisLabels = spec.femt_mesh.variables.map((v, i) => `Eixo ${i + 1}: ${v}`);
    }
    if (axisSel) {
      axisSel.innerHTML =
        axisLabels.length > 0
          ? axisLabels
              .map((lbl, idx) => `<option value="${idx}">${escapeHtml(lbl)}</option>`)
              .join("")
          : `<option value="0">Padrão</option>`;
      axisSel.value = String(this.selectedChartAxisIdx);
    }

    if (ruleSel) {
      ruleSel.innerHTML = Array.from(
        { length: Math.max(1, this.result.num_rules) },
        (_, r) => `<option value="${r}">Regra h_${r + 1}</option>`,
      ).join("");
      ruleSel.value = String(this.selectedChartRuleIdx);
    }
  }

  private renderSummary(): void {
    const el = this.q<HTMLElement>("#ts-summary");
    if (!el || !this.result) return;
    const r = this.result;
    const cert = r.fidelity_certificate;
    const badge = typeof cert.verification_badge === "string" ? cert.verification_badge : "—";
    const isExact = badge.startsWith("EXACT");
    const gridRel =
      typeof cert.grid_rel_l2_error === "number"
        ? cert.grid_rel_l2_error.toExponential(3)
        : isExact
          ? "0 (analítico)"
          : "—";
    const valRel =
      typeof cert.val_rel_l2_error === "number"
        ? cert.val_rel_l2_error.toExponential(3)
        : typeof cert.rel_l2_error === "number"
          ? cert.rel_l2_error.toExponential(3)
          : "—";
    const valMax =
      typeof cert.val_max_abs_error === "number"
        ? cert.val_max_abs_error.toExponential(3)
        : typeof cert.max_abs_error === "number"
          ? cert.max_abs_error.toExponential(3)
          : "—";
    const minW =
      typeof cert.min_weight === "number" ? formatNumericDisplay(cert.min_weight, 6) : "0";
    const sumDev =
      typeof cert.max_sum_deviation === "number"
        ? cert.max_sum_deviation.toExponential(2)
        : "0";

    let extraLine = "";
    const repKind = r.ts_state_space.membership_spec.representation_kind;
    if (repKind === "femt_simplicial") {
      const femt = r as DerivedTsFemtResult;
      extraLine = `<p class="dock-item-summary">Posto SVD global R = <strong>${femt.svd_rank}</strong> • Erro nodal de Eckart–Young ||Xᵀ − U_R C_0||_F = <code>${femt.eckart_young_frobenius_error.toExponential(3)}</code> • Malha: <code>${escapeHtml(femt.mesh_kind)}</code>.</p>`;
    } else if (repKind === "tpmt_interpolated") {
      const tpmt = r as DerivedTsTpmtResult;
      extraLine = `<p class="dock-item-summary">Cota superior de truncamento HOSVD (De Lathauwer): <code>${tpmt.truncation_bound.toExponential(3)}</code>.</p>`;
    }

    const warnHtml =
      this.resultWarnings.length > 0
        ? `<ul class="ts-warnings-list">${this.resultWarnings.map((w) => `<li><strong>${escapeHtml(w.code)}:</strong> ${escapeHtml(w.message)}</li>`).join("")}</ul>`
        : "";

    el.innerHTML = [
      `<div class="ts-subcard-header">`,
      `<h4>Zona 4A — Certificado de Fidelidade</h4>`,
      `<span class="ts-cert-badge ${isExact ? "is-exact" : "is-approx"}">${escapeHtml(badge)}</span>`,
      `</div>`,
      `<div class="ts-kpi-grid">`,
      `<div class="ts-kpi-box"><span>Nº de Regras N_r</span><strong id="ts-result-rules">${r.num_rules}</strong></div>`,
      `<div class="ts-kpi-box"><span>Erro Rel. Grade</span><strong><code>${escapeHtml(gridRel)}</code></strong></div>`,
      `<div class="ts-kpi-box"><span>Erro Rel. Off-Grid</span><strong><code>${escapeHtml(valRel)}</code></strong></div>`,
      `<div class="ts-kpi-box"><span>Erro Máx. ||ΔS||_F</span><strong><code>${escapeHtml(valMax)}</code></strong></div>`,
      `<div class="ts-kpi-box"><span>min h_r(·)</span><strong><code>${escapeHtml(minW)}</code></strong></div>`,
      `<div class="ts-kpi-box"><span>máx |∑h_r − 1|</span><strong><code>${escapeHtml(sumDev)}</code></strong></div>`,
      `</div>`,
      `<p class="dock-item-summary">Modelo <code>${escapeHtml(r.model_id)}</code> • Tipo: <code>${escapeHtml(r.kind)}</code> • Premissas: ${escapeHtml(r.ts_state_space.premise_availability.mode)}.</p>`,
      extraLine,
      warnHtml,
    ].join("");
  }

  private renderVertexInspector(): void {
    const card = this.q<HTMLElement>("#ts-vertex-inspector-card");
    const sel = this.q<HTMLSelectElement>("#ts-vertex-select");
    if (!card || !sel) return;
    if (!this.result || this.result.ts_state_space.vertices.length === 0) {
      setElHidden(card, true);
      return;
    }
    setElHidden(card, false);
    const verts = this.result.ts_state_space.vertices;
    sel.innerHTML = verts
      .map(
        (v, idx) =>
          `<option value="${idx}">Regra ${idx + 1} (${escapeHtml(v.vertex_id)})</option>`,
      )
      .join("");
    this.selectedVertexIdx = Math.min(this.selectedVertexIdx, verts.length - 1);
    sel.value = String(this.selectedVertexIdx);
    this.renderVertexDetail();
  }

  private renderVertexDetail(): void {
    const slot = this.q<HTMLElement>("#ts-vertex-detail-slot");
    if (!slot || !this.result) return;
    const verts = this.result.ts_state_space.vertices;
    const idx = Math.min(Math.max(0, this.selectedVertexIdx), verts.length - 1);
    const v = verts[idx];
    if (!v) return;
    const fnSpec = this.result.ts_state_space.membership_spec.functions[idx];
    const expr = fnSpec?.expression ?? `h_${idx + 1}`;

    const fmtMat = (name: string, t: RealTensor): string => {
      const m = unpackTensor(t);
      const flatC = m.flat();
      const strGrid = formatMatrixDisplay(flatC, t.shape[0] ?? 0, t.shape[1] ?? 0, 4);
      const formatted = strGrid.map((row) => `[ ${row.join(",  ")} ]`).join("\n");
      return `<div class="ts-vertex-mat"><h6>${name}_${idx + 1} [${t.shape[0]}×${t.shape[1]}]</h6><pre class="ts-vertex-pre">${escapeHtml(formatted)}</pre></div>`;
    };

    slot.innerHTML = [
      `<p class="dock-item-summary"><strong>Pertinência <code>h_${idx + 1}</code>:</strong> <code>${escapeHtml(expr)}</code></p>`,
      `<div class="ts-vertex-mats-grid">`,
      fmtMat("A", v.A),
      fmtMat("B", v.B),
      fmtMat("C", v.C),
      fmtMat("D", v.D),
      `</div>`,
    ].join("");
  }

  private renderCharts(themeMode: "standard_aa" | "high_contrast"): void {
    const cacheKey = `${themeMode}|${this.resultVia}|${this.selectedChartAxisIdx}|${this.selectedChartRuleIdx}|${this.result ? `${this.result.model_id}:${this.result.num_rules}` : "empty"}`;
    if (cacheKey === this.chartsCacheKey) return;
    this.chartsCacheKey = cacheKey;

    const setSlot = (
      slotId: string,
      tableId: string,
      svg: string | null,
      table: string,
      emptyMsg: string,
    ): void => {
      const slot = this.q<HTMLElement>(`#${slotId}`);
      const tab = this.q<HTMLElement>(`#${tableId}`);
      if (slot) slot.innerHTML = svg ?? `<p class="dock-item-summary">${escapeHtml(emptyMsg)}</p>`;
      if (tab) tab.innerHTML = table;
    };

    const r = this.result;
    const h = r ? buildMembership1DChartModel(r, this.selectedChartAxisIdx) : null;
    setSlot(
      "ts-hr-chart-slot",
      "ts-hr-table-slot",
      h ? renderTsLineChartSvg(h, { themeMode }) : null,
      h ? renderTsLineChartTableHtml(h) : "",
      r
        ? "Gráfico 1D indisponível para esta configuração."
        : "Gere um modelo TS para inspecionar as funções de pertinência.",
    );

    const m = r ? buildMesh2DModel(r, this.selectedChartRuleIdx) : null;
    setSlot(
      "ts-mesh-chart-slot",
      "ts-mesh-table-slot",
      m ? renderTsMeshSvg(m, { themeMode }) : null,
      m
        ? `<p>${m.nodes.length} nós; ${m.triangles.length} elementos simpliciais (${escapeHtml(m.kind)}).</p>`
        : "",
      r
        ? "Superfície/malha 2D disponível nas vias TPMT e FEMT quando há ≥ 2 variáveis ativas."
        : "Gere um modelo TS (TPMT ou FEMT 2D+) para visualizar a malha simplicial.",
    );

    const b = r ? buildBasesChartModel(r, this.selectedChartAxisIdx) : null;
    setSlot(
      "ts-bases-chart-slot",
      "ts-bases-table-slot",
      b ? renderTsLineChartSvg(b, { themeMode }) : null,
      b ? renderTsLineChartTableHtml(b) : "",
      r
        ? "Comparação de bases U vs W disponível nas vias numéricas TPMT e FEMT."
        : "Gere um modelo via TPMT ou FEMT para comparar U (SVD) vs W (fecho convexo).",
    );

    const s = r ? buildScreeChartModel(r) : null;
    setSlot(
      "ts-scree-chart-slot",
      "ts-scree-table-slot",
      s ? renderTsLineChartSvg(s, { themeMode }) : null,
      s ? renderTsLineChartTableHtml(s) : "",
      r
        ? "Espectro de valores singulares disponível nas vias TPMT e FEMT."
        : "Gere um modelo via TPMT ou FEMT para inspecionar a queda dos valores singulares.",
    );

    const heatmapOptions: OffGridErrorHeatmapOptions = {};
    if (r) {
      const prov = isPlainObject(r.ts_state_space.provenance)
        ? r.ts_state_space.provenance
        : null;
      const provGen =
        prov && isPlainObject(prov.generalized_channels) ? prov.generalized_channels : null;
      if (provGen && Array.isArray(provGen.vertices)) {
        heatmapOptions.generalizedVertices = provGen.vertices as ReadonlyArray<
          Partial<Record<GeneralizedChannelName, number[][]>>
        >;
      }
      if (this.lastDerivedDraftSnapshot?.enableGeneralized) {
        const snapMats =
          this.resultVia === "sector"
            ? this.lastDerivedDraftSnapshot.sectorMatrices
            : this.lastDerivedDraftSnapshot.directMatrices;
        const genExprs: Partial<Record<GeneralizedChannelName, string[][]>> = {};
        for (const ch of GENERALIZED_CHANNEL_NAMES) {
          genExprs[ch] = snapMats[ch];
        }
        heatmapOptions.generalizedExpressions = genExprs;
      } else if (provGen && isPlainObject(provGen.expressions)) {
        heatmapOptions.generalizedExpressions = provGen.expressions as Partial<
          Record<GeneralizedChannelName, string[][]>
        >;
      }
    }

    const e = r ? buildOffGridErrorHeatmap(r, heatmapOptions) : null;
    setSlot(
      "ts-error-heatmap-slot",
      "ts-error-table-slot",
      e ? renderTsHeatmapSvg(e, { themeMode }) : null,
      e
        ? `<p>Erro máximo amostrado fora da grade (${escapeHtml(e.metricLabel)}): <code>${escapeHtml(e.maxError.toExponential(3))}</code>.</p>`
        : "",
      r
        ? "Mapa de calor 2D requer pelo menos 2 variáveis de domínio."
        : "Gere um modelo TS para auditar o erro fora da grade em Ω.",
    );
  }

  private setDisabled(selector: string, disabled: boolean): void {
    const el = this.q<HTMLButtonElement>(selector);
    if (!el) return;
    el.disabled = disabled;
    if (disabled) el.setAttribute("aria-disabled", "true");
    else el.removeAttribute("aria-disabled");
  }

  private syncStaleState(): void {
    this.syncActionButtons();
    const banner = this.q<HTMLElement>("#ts-stale-banner");
    if (!banner) return;
    if (this.result !== null && this.isLastDerivationStale()) {
      banner.innerHTML =
        "<strong>Especificação alterada desde a última derivação</strong> — clique em <strong>Validar &amp; Gerar Modelo TS</strong> novamente antes de registrar no Workspace.";
      setElHidden(banner, false);
    } else {
      banner.textContent = "";
      setElHidden(banner, true);
    }
  }

  private syncActionButtons(): void {
    const canUseResult = this.result !== null && !this.isLastDerivationStale();
    this.setDisabled("#btn-ts-register", !canUseResult || this.busy);
    this.setDisabled("#btn-ts-register-open-lmi", !canUseResult || this.busy);
    this.setDisabled("#btn-ts-export-python", !canUseResult || this.busy);
    this.setDisabled("#btn-ts-export-matlab", !canUseResult || this.busy);
    this.setDisabled("#btn-ts-derive", this.busy);
    this.setDisabled("#btn-ts-compare", this.busy);
    this.setDisabled("#btn-ts-analyze", this.busy);
  }

  public render(): void {
    const panel = this.q<HTMLElement>("#ts-modeling-workspace-panel");
    const active = this.shell.getActiveTab() === "ts_modeling";
    setElHidden(panel, !active);
    if (!active) return;

    if (!this.domInitialized) {
      this.domInitialized = true;
      this.rebuildEditableSections();
    } else {
      this.syncHeaderControls();
      this.updateLiveDiagnostics();
    }

    for (const el of Array.from(this.container.querySelectorAll<HTMLElement>("[data-via-only]"))) {
      const allowed = (el.getAttribute("data-via-only") ?? "").split(/\s+/).filter(Boolean);
      setElHidden(el, !allowed.includes(this.via));
    }

    this.syncStaleState();

    const recipes = this.recipeOptions();
    const recipeSel = this.q<HTMLSelectElement>("#ts-recipe-select");
    if (recipeSel) {
      const prevVal = recipeSel.value;
      const optionsHtml =
        recipes.length === 0
          ? `<option value="">— nenhuma receita registrada —</option>`
          : recipes
              .map((o) => `<option value="${escapeHtml(o.key)}">${escapeHtml(o.label)}</option>`)
              .join("");
      if (recipeSel.innerHTML !== optionsHtml) {
        recipeSel.innerHTML = optionsHtml;
        if (recipes.some((r) => r.key === prevVal)) {
          recipeSel.value = prevVal;
        }
      }
    }
    this.setDisabled("#btn-ts-reload-recipe", recipes.length === 0 || this.busy);

    const hasResult = this.result !== null;
    const stepStates: Array<[string, boolean]> = [
      ["#ts-step-1", this.draft.states.length > 0],
      ["#ts-step-2", true],
      ["#ts-step-3", hasResult],
      ["#ts-step-4", this.registeredKey !== null],
    ];
    for (const [sel, done] of stepStates) {
      this.q<HTMLElement>(sel)?.setAttribute("data-step-state", done ? "done" : "pending");
    }

    const statusEl = this.q<HTMLElement>("#ts-status");
    if (statusEl && statusEl.textContent !== this.statusText) {
      statusEl.textContent = this.statusText;
    }

    this.renderCharts(this.shell.getThemeMode());
  }
}
