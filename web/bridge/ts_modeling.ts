/** Public TypeScript contract for the Python TS/qLPV RPC operations (CL-TS-MOD-DIR-001). */
import type { RealTensor, RpcRequest, RpcResponse } from "./protocol.ts";

export const TS_MODELING_OPERATIONS = {
  analyzeSectorPremises: "fuzzy.analyze_sector_premises",
  deriveTsSector: "fuzzy.derive_ts_sector",
  deriveTsTpmt: "fuzzy.derive_ts_tpmt",
  deriveTsFemt: "fuzzy.derive_ts_femt",
  exportTsDerivationScript: "fuzzy.export_ts_derivation_script",
} as const;

export type TsModelingOperation = (typeof TS_MODELING_OPERATIONS)[keyof typeof TS_MODELING_OPERATIONS];
const tsModelingOperationNames = new Set<string>(Object.values(TS_MODELING_OPERATIONS));

export function isTsModelingOperation(operation: string): operation is TsModelingOperation {
  return tsModelingOperationNames.has(operation);
}

export type TsModelingContext = Pick<RpcRequest, "request_id" | "project_id" | "project_revision">
  & Partial<Pick<RpcRequest, "options" | "timeout_policy">>;

export const TS_MODELING_PROGRESS_STAGES = ["validating", "computing", "completed"] as const;
export type TsModelingProgressStage = (typeof TS_MODELING_PROGRESS_STAGES)[number];
export interface TsModelingProgressEvent {
  request_id: string;
  progress: { stage: TsModelingProgressStage; elapsed_ms: number };
}

export type SymbolicMatrix = ReadonlyArray<ReadonlyArray<string | number>>;
export type TsBounds = Readonly<Record<string, readonly [number, number]>>;
type MeasuredVariables = Readonly<Record<string, boolean>> | readonly string[];
type AxisSetting<T> = Readonly<Record<string, T>> | readonly T[];
export type TsHull = "CNO" | "RNO-INO" | "SN-NN" | "MGK";
export type FemtMeshKind = "delaunay" | "kuhn_delaunay";
export type DerivedTsKind = "ts_measured" | "ts_partially_observed";
export type TsDerivationLanguage = "python" | "matlab";

interface TsSchedulingSpec {
  state_bounds: TsBounds;
  external_bounds?: TsBounds | null;
  measured_states?: MeasuredVariables | null;
  measured_externals?: MeasuredVariables | null;
}

export interface SectorPremiseSpec {
  name: string;
  expression: string | number;
  user_bounds?: readonly [number, number] | null;
  measured?: boolean | null;
}

export interface AnalyzeSectorPremisesPayload extends TsSchedulingSpec {
  premises: readonly SectorPremiseSpec[];
}

interface TsPlantDerivationPayload extends TsSchedulingSpec {
  A_expr: SymbolicMatrix;
  B_expr: SymbolicMatrix;
  C_expr?: SymbolicMatrix | null;
  D_expr?: SymbolicMatrix | null;
  generalized_channels?: Readonly<Partial<Record<"Bw" | "Cz" | "Dyw" | "Dzw" | "Dzu", SymbolicMatrix>>> | null;
  dt?: number | null;
  state_names?: readonly string[] | null;
  input_names?: readonly string[] | null;
  output_names?: readonly string[] | null;
  units?: Record<string, unknown> | null;
  model_id?: string | null;
  n_val_points?: number;
}

export interface DeriveTsSectorPayload extends TsPlantDerivationPayload {
  premises: readonly SectorPremiseSpec[];
}

interface SampledDerivationPayload extends TsPlantDerivationPayload {
  grid_points?: number | AxisSetting<number>;
  svd_tol?: number;
  sn_tol?: number;
}

export interface DeriveTsTpmtPayload extends SampledDerivationPayload {
  decomposition?: "hosvd" | "hooi";
  ranks?: AxisSetting<number> | null;
  hull_type?: TsHull | AxisSetting<TsHull>;
  resample_points?: number | AxisSetting<number> | null;
  resample_method?: "linear" | "pchip";
  hooi_max_iter?: number;
  hooi_conv_tol?: number;
}

export interface DeriveTsFemtPayload extends SampledDerivationPayload {
  rank?: number | null;
  hull_type?: TsHull;
  mesh_kind?: FemtMeshKind;
}

export type ExportTsDerivationScriptPayload = { language: TsDerivationLanguage } & (
  | { model: Record<string, unknown>; model_ref?: never }
  | { model?: never; model_ref: { id: string; revision: number } }
);

export interface AnalyzedSectorPremise extends Record<string, unknown> {
  name: string;
  expression: string;
  active_variables: string[];
  min: number;
  max: number;
  measured: boolean;
}

export interface TsPremiseAvailability {
  mode: "all_measured" | "partially_observed";
  measured_premises: string[];
  unmeasured_premises: string[];
  estimator_required_for_pdc: boolean;
}

export interface SectorAnalysisResult extends Record<string, unknown> {
  premises: AnalyzedSectorPremise[];
  num_premises: number;
  num_rules: number;
  inferred_kind: DerivedTsKind;
  premise_availability: TsPremiseAvailability;
  state_bounds: TsBounds;
  external_bounds: TsBounds;
}

interface MembershipSpec {
  version: string;
  premise_variables: string[];
  sum_to_one_domain: boolean;
}

export interface SectorMembership extends MembershipSpec {
  representation_kind: "sector_nonlinearity";
  sector_premises: AnalyzedSectorPremise[];
  functions: Array<{ id: string; vertex_id: string; bits: number[]; expression: string }>;
}

export interface TpmtMembership extends MembershipSpec {
  representation_kind: "tpmt_interpolated";
  tpmt_axes: Array<{
    axis_index: number;
    variable: string;
    expression: string;
    bounds: [number, number];
    hull_type: TsHull;
    rank: number;
    grid: number[];
    weights_table: number[][];
  }>;
  functions: Array<{ id: string; vertex_id: string; axis_basis_indices: number[]; expression: string }>;
}

export interface FemtMembership extends MembershipSpec {
  representation_kind: "femt_simplicial";
  femt_mesh: {
    mesh_kind: FemtMeshKind;
    variables: string[];
    bounds: Array<[number, number]>;
    hull_type: TsHull;
    svd_rank: number;
    num_rules: number;
    axes_grids: number[][];
    nodal_weights: number[][];
    nodes?: number[][];
    simplices: number[][] | null;
  };
  functions: Array<{ id: string; vertex_id: string; rule_index: number; expression: string }>;
}

type DerivedMembership = SectorMembership | TpmtMembership | FemtMembership;
export interface DerivedTsStateSpace<M extends DerivedMembership = DerivedMembership> extends Record<string, unknown> {
  schema_version: string;
  id: string;
  revision: number;
  kind: DerivedTsKind;
  dt: number | null;
  membership_spec: M;
  premise_availability: TsPremiseAvailability;
  domain: { bounds: TsBounds } & Record<string, unknown>;
  vertices: Array<{ vertex_id: string; A: RealTensor; B: RealTensor; C: RealTensor; D: RealTensor }>;
  state_names: string[];
  input_names: string[];
  output_names: string[];
  units: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

interface DerivedTsResult<M extends DerivedMembership> extends Record<string, unknown> {
  ts_state_space: DerivedTsStateSpace<M>;
  model_id: string;
  kind: DerivedTsKind;
  num_rules: number;
  fidelity_certificate: Record<string, unknown>;
}

export interface DerivedTsSectorResult extends DerivedTsResult<SectorMembership> {
  num_premises: number;
  premises: AnalyzedSectorPremise[];
}

export interface DerivedTsTpmtResult extends DerivedTsResult<TpmtMembership> {
  active_variables: string[];
  singular_values: number[][];
  bases_pre_transform: number[][][];
  bases_post_transform: number[][][];
  axis_grids: number[][];
  hull_diagnostics: Array<Record<string, unknown>>;
  hooi: Record<string, unknown> | null;
  truncation_bound: number;
}

export interface DerivedTsFemtResult extends DerivedTsResult<FemtMembership> {
  active_variables: string[];
  mesh_kind: FemtMeshKind;
  svd_rank: number;
  singular_values: number[];
  eckart_young_frobenius_error: number;
  eckart_young_spectral_error: number;
  U_raw: number[][];
  W_nodal: number[][];
  axes_grids: number[][];
  nodes: number[][] | null;
  simplices: number[][] | null;
  hull_diagnostics: Record<string, unknown>;
}

export interface TsDerivationScriptResult extends Record<string, unknown> {
  script: string;
  filename: string;
  media_type: "text/x-python" | "text/x-matlab";
  language: TsDerivationLanguage;
  code_executed: false;
  requires_explicit_user_execution: true;
}

export type TsRpcResponse<T extends Record<string, unknown>> = Omit<RpcResponse, "result"> & { result: T | null };
