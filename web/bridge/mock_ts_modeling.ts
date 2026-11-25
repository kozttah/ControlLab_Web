/** Synthetic, deterministic TS examples for exercising the UI through the mock transport. */
import { ControlLabBridgeError, isPlainObject, type RealTensor } from "./protocol.ts";
import { TS_MODELING_OPERATIONS, type TsModelingOperation } from "./ts_modeling.ts";

function tensor(shape: number[], data: number[]): RealTensor {
  return { shape, dtype: "float64", order: "C", data };
}

function analyzePremises(payload: Record<string, unknown>): Record<string, unknown> {
  if (!Array.isArray(payload.premises) || payload.premises.length === 0 ||
    !isPlainObject(payload.state_bounds)) {
    throw new ControlLabBridgeError("VALIDATION_ERROR", "A análise requer premissas e limites de estado.");
  }
  const stateBounds = payload.state_bounds;
  const premises = payload.premises.map(premise => {
    if (!isPlainObject(premise) || typeof premise.name !== "string" ||
      (typeof premise.expression !== "string" && typeof premise.expression !== "number")) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "Premissa setorial inválida.");
    }
    const expression = String(premise.expression);
    const bounds = premise.user_bounds ?? stateBounds[expression];
    const [min, max] = Array.isArray(bounds) && bounds.length === 2 ? bounds : [-1, 1];
    return {
      name: premise.name,
      expression,
      rewritten_expression: expression,
      active_variables: Object.hasOwn(stateBounds, expression) ? [expression] : [],
      min,
      max,
      computed_min: min,
      computed_max: max,
      method: "synthetic_mock",
      measured: premise.measured !== false,
    };
  });
  const measured = premises.filter(p => p.measured).map(p => p.name);
  const unmeasured = premises.filter(p => !p.measured).map(p => p.name);
  return {
    premises,
    num_premises: premises.length,
    num_rules: 2 ** premises.length,
    inferred_kind: unmeasured.length ? "ts_partially_observed" : "ts_measured",
    premise_availability: {
      mode: unmeasured.length ? "partially_observed" : "all_measured",
      measured_premises: measured,
      unmeasured_premises: unmeasured,
      estimator_required_for_pdc: unmeasured.length > 0,
    },
    state_bounds: payload.state_bounds,
    external_bounds: payload.external_bounds ?? {},
  };
}

function deriveExample(
  operation: TsModelingOperation,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  if (!isPlainObject(payload.state_bounds) || !Array.isArray(payload.A_expr) || !Array.isArray(payload.B_expr)) {
    throw new ControlLabBridgeError("VALIDATION_ERROR", "A derivação requer limites de estado e as matrizes A e B.");
  }
  // Static two-dimensional, stable plant used to make graphs and vertices
  // representative, independently of the scientific inputs to the test adapter.
  const stateBounds = { x1: [-1, 1], x2: [-1, 1] };
  const states = Object.keys(stateBounds);
  const sector = operation === TS_MODELING_OPERATIONS.deriveTsSector;
  const femt = operation === TS_MODELING_OPERATIONS.deriveTsFemt;
  const analysis = analyzePremises({
    state_bounds: stateBounds,
    premises: [{ name: "z1", expression: "x1" }, { name: "z2", expression: "x2" }],
  });
  const premiseVariables = sector ? ["z1", "z2"] : states;
  const indices = [[0, 0], [0, 1], [1, 0], [1, 1]];
  const grids = [[-1, 1], [-1, 1]];
  const nodes = indices.map(row => row.map(index => grids[0][index]));
  const nodalWeights = indices.map((_, i) => indices.map((_, j) => Number(i === j)));
  const axes = states.map((variable, axis) => ({
    axis_index: axis + 1,
    variable,
    expression: variable,
    bounds: grids[axis],
    hull_type: "CNO",
    rank: 2,
    grid: grids[axis],
    weights_table: [[1, 0], [0, 1]],
  }));
  const explicit = payload.mesh_kind === "delaunay";
  const simplices = explicit ? [[0, 2, 3], [0, 3, 1]] : null;
  const mesh = {
    mesh_kind: explicit ? "delaunay" : "kuhn_delaunay",
    variables: states,
    bounds: grids,
    hull_type: "CNO",
    svd_rank: 3,
    num_rules: 4,
    axes_grids: grids,
    nodal_weights: nodalWeights,
    simplices,
    ...(explicit ? { nodes } : {}),
  };
  const representation = sector ? "sector_nonlinearity" : femt ? "femt_simplicial" : "tpmt_interpolated";
  const functions = indices.map(([i, j], rule) => ({
    id: `h_${rule + 1}`,
    vertex_id: `rule_${rule + 1}`,
    ...(sector ? { bits: [i, j], expression: `w_z1_${i}(x1) * w_z2_${j}(x2)` }
      : femt ? { rule_index: rule, expression: `fem_p1_barycentric(x1, x2; r=${rule + 1})` }
        : { axis_basis_indices: [i, j], expression: `w_1_${i + 1}(x1) * w_2_${j + 1}(x2)` }),
  }));
  const vertices = functions.map(({ vertex_id }, rule) => ({
    vertex_id,
    A: tensor([2, 2], [-2 - indices[rule][0], 0, 0, -2 - indices[rule][1]]),
    B: tensor([2, 1], [1, 0]),
    C: tensor([1, 2], [1, 0]),
    D: tensor([1, 1], [0]),
  }));
  const method = sector ? "sector_nonlinearity" : femt ? "femt" : "tpmt";
  const fidelity = {
    mock: true,
    verified: false,
    verification_badge: "SYNTHETIC_MOCK",
    verification_tier: "approximate",
    min_weight: 0,
    max_sum_deviation: 0,
    grid_rel_l2_error: 0,
    val_rel_l2_error: 0,
  };
  const modelId = typeof payload.model_id === "string" && payload.model_id.length
    ? payload.model_id
    : `mock-ts-${method}`;
  const model = {
    schema_version: "1.0.0",
    id: modelId,
    revision: 0,
    kind: "ts_measured",
    dt: null,
    membership_spec: {
      version: "1.0.0",
      representation_kind: representation,
      sum_to_one_domain: true,
      premise_variables: premiseVariables,
      functions,
      ...(sector ? { sector_premises: analysis.premises }
        : femt ? { femt_mesh: mesh } : { tpmt_axes: axes }),
    },
    premise_availability: {
      mode: "all_measured",
      measured_premises: premiseVariables,
      unmeasured_premises: [],
      estimator_required_for_pdc: false,
    },
    domain: {
      bounds: sector ? { ...stateBounds, z1: grids[0], z2: grids[1] } : stateBounds,
    },
    vertices,
    state_names: states,
    input_names: ["u1"],
    output_names: ["y1"],
    units: {},
    provenance: { source: "MockWorkerAdapter", ts_derivation: { method, fidelity_certificate: fidelity } },
  };
  const common = {
    ts_state_space: model,
    model_id: modelId,
    kind: model.kind,
    num_rules: vertices.length,
    fidelity_certificate: fidelity,
  };
  const hullDiagnostics = { hull_type: "CNO", rank_before: 2, rank_after: 2, min_weight: 0 };
  if (sector) return { ...common, num_premises: 2, premises: analysis.premises };
  if (femt) {
    return {
      ...common,
      active_variables: states,
      mesh_kind: mesh.mesh_kind,
      svd_rank: mesh.svd_rank,
      singular_values: [3, 1, 0.5],
      eckart_young_frobenius_error: 0,
      eckart_young_spectral_error: 0,
      U_raw: nodalWeights.map(row => row.slice(0, 3)),
      W_nodal: nodalWeights,
      axes_grids: grids,
      nodes: explicit ? nodes : null,
      simplices,
      hull_diagnostics: hullDiagnostics,
    };
  }
  return {
    ...common,
    active_variables: states,
    singular_values: [[2, 1], [2, 1]],
    truncation_bound: 0,
    bases_pre_transform: axes.map(axis => axis.weights_table),
    bases_post_transform: axes.map(axis => axis.weights_table),
    axis_grids: grids,
    hull_diagnostics: axes.map(axis => ({ ...hullDiagnostics, axis: axis.variable })),
    hooi: null,
  };
}

export function makeMockTsModelingResult(
  operation: TsModelingOperation,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  if (operation === TS_MODELING_OPERATIONS.analyzeSectorPremises) return analyzePremises(payload);
  if (operation === TS_MODELING_OPERATIONS.exportTsDerivationScript) {
    if (!isPlainObject(payload.model) ||
      (payload.model.kind !== "ts_measured" && payload.model.kind !== "ts_partially_observed") ||
      (payload.language !== "python" && payload.language !== "matlab")) {
      throw new ControlLabBridgeError("VALIDATION_ERROR", "A exportação exige um modelo TS e uma linguagem válida.");
    }
    const matlab = payload.language === "matlab";
    return {
      language: payload.language,
      filename: `controllab_ts_derivation.${matlab ? "m" : "py"}`,
      media_type: matlab ? "text/x-matlab" : "text/x-python",
      script: matlab ? "% Exportação simulada do ControlLab\n" : "# Exportação simulada do ControlLab\n",
      code_executed: false,
      requires_explicit_user_execution: true,
    };
  }
  return deriveExample(operation, payload);
}
