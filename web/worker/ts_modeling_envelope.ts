import { ControlLabBridgeError, isPlainObject } from "../bridge/protocol.ts";
import { TS_MODELING_OPERATIONS } from "../bridge/ts_modeling.ts";

const MAX_NODES = 250_000;
const MAX_DELAUNAY_NODES = 50_000;
const MAX_SAMPLED_VALUES = 10_000_000;
const MAX_ACTIVE_DIMENSIONS = 5;
const MAX_RULES = 256;

function limit(field: string, actual: number, max: number): never {
  throw new ControlLabBridgeError(
    "RESOURCE_LIMIT",
    `${field} (${actual}) excede o teto de modelagem no Worker (${max}).`,
    {
      parameters: { field, actual, max },
      next_step: "Reduza o tamanho da grade ou use a derivação offline (Python/MATLAB).",
    },
  );
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function requireIntegers(field: string, values: unknown[]): void {
  if (values.some((value) => typeof value !== "number" || !Number.isInteger(value))) {
    throw new ControlLabBridgeError("VALIDATION_ERROR", `${field} exige valores inteiros.`, {
      parameters: { field },
    });
  }
}

function axisValues(setting: unknown): unknown[] {
  return Array.isArray(setting) ? setting : isPlainObject(setting) ? Object.values(setting) : [setting];
}

function shape(matrix: unknown): [number, number] {
  if (Array.isArray(matrix)) return [matrix.length, Array.isArray(matrix[0]) ? matrix[0].length : 0];
  if (isPlainObject(matrix) && Array.isArray(matrix.shape) && matrix.shape.length === 2 &&
      matrix.shape.every(positiveInteger)) return [matrix.shape[0], matrix.shape[1]];
  return [0, 0];
}

function blockSize(A: unknown, B: unknown, C: unknown, generalized: unknown): number {
  const [states] = shape(A);
  const [, inputs] = shape(B);
  const [outputs] = C == null ? [states] : shape(C);
  const channels = isPlainObject(generalized) ? generalized : {};
  const nw = Math.max(...[channels.Bw, channels.Dyw, channels.Dzw].map((matrix) => shape(matrix)[1]));
  const nz = Math.max(...[channels.Cz, channels.Dzu, channels.Dzw].map((matrix) => shape(matrix)[0]));
  return (states + outputs + nz) * (states + inputs + nw);
}

// Only an explicit vector fixes the count of axes. Named sizes can also name
// inactive variables. Python resolves active axes using the symbolic AST and
// checks the exact shape, element count, and rule count before allocation.
function minimumGridNodes(grid: unknown, defaultSize: number): number {
  if (grid === undefined) return defaultSize;
  if (positiveInteger(grid)) return grid;
  if (Array.isArray(grid) && grid.length > 0 && grid.every(positiveInteger)) {
    let nodes = 1;
    for (const size of grid) {
      nodes = Math.min(Number.MAX_SAFE_INTEGER, nodes * size);
      if (nodes > MAX_NODES) break;
    }
    return nodes;
  }
  if (isPlainObject(grid)) {
    const sizes = Object.values(grid);
    if (sizes.length > 0 && sizes.every(positiveInteger)) {
      return sizes.reduce((smallest, size) => Math.min(smallest, size), Infinity);
    }
  }
  return 0;
}

export function checkTsModelingEnvelope(operation: string, payload: Record<string, unknown>): void {
  if (operation === TS_MODELING_OPERATIONS.exportTsDerivationScript) {
    checkReplayEnvelope(payload.model);
    return;
  }

  const tpmt = operation === TS_MODELING_OPERATIONS.deriveTsTpmt;
  const femt = operation === TS_MODELING_OPERATIONS.deriveTsFemt;
  if (!tpmt && !femt && operation !== TS_MODELING_OPERATIONS.deriveTsSector) return;

  const valuesPerSample = blockSize(payload.A_expr, payload.B_expr, payload.C_expr, payload.generalized_channels);
  if (payload.n_val_points !== undefined) requireIntegers("n_val_points", [payload.n_val_points]);
  if (positiveInteger(payload.n_val_points) && payload.n_val_points > MAX_NODES) {
    limit("n_val_points", payload.n_val_points, MAX_NODES);
  }
  const validationPoints = typeof payload.n_val_points === "number" ? Math.max(payload.n_val_points, 64) : 2048;
  const possibleRules = tpmt || femt || !Array.isArray(payload.premises)
    ? MAX_RULES : 2 ** Math.min(payload.premises.length, 8);
  const validationValues = validationPoints * Math.max(valuesPerSample, possibleRules);
  if (validationValues > MAX_SAMPLED_VALUES) limit("validation_values", validationValues, MAX_SAMPLED_VALUES);

  if (!tpmt && !femt) return;

  const maxNodes = femt && typeof payload.mesh_kind === "string" &&
    payload.mesh_kind.trim().toLowerCase() === "delaunay" ? MAX_DELAUNAY_NODES : MAX_NODES;
  if (payload.grid_points !== undefined) requireIntegers("grid_points", axisValues(payload.grid_points));
  const minimumNodes = minimumGridNodes(payload.grid_points, tpmt ? 51 : 21);
  if (minimumNodes > maxNodes) limit("grid_points", minimumNodes, maxNodes);

  const minimumValues = minimumNodes * valuesPerSample;
  if (minimumValues > MAX_SAMPLED_VALUES) limit("sampled_values", minimumValues, MAX_SAMPLED_VALUES);

  if (tpmt) {
    const resample = payload.resample_points;
    if (resample != null) requireIntegers("resample_points", axisValues(resample));
    const sizes = Array.isArray(resample) ? resample : [resample];
    const oversized = sizes.find((size) => positiveInteger(size) && size > MAX_NODES);
    if (typeof oversized === "number") limit("resample_points", oversized, MAX_NODES);
  }
}

function checkReplayEnvelope(model: unknown): void {
  if (!isPlainObject(model) || !isPlainObject(model.membership_spec)) return;
  const representation = model.membership_spec.representation_kind;
  if (representation !== "femt_simplicial" && representation !== "tpmt_interpolated") return;

  const provenance = isPlainObject(model.provenance) ? model.provenance : {};
  const recipe = isPlainObject(provenance.ts_derivation) ? provenance.ts_derivation : {};
  const grid = recipe.grid_points;
  if (!Array.isArray(grid) || grid.length === 0 || !grid.every(positiveInteger) ||
      !Array.isArray(recipe.active_variables) || recipe.active_variables.length !== grid.length) {
    throw new ControlLabBridgeError("VALIDATION_ERROR", "A receita de derivação TS requer tamanhos de grade inteiros e positivos para cada variável ativa.");
  }
  if (grid.length > MAX_ACTIVE_DIMENSIONS) limit("active_variables", grid.length, MAX_ACTIVE_DIMENSIONS);
  const maxNodes = representation === "femt_simplicial" && recipe.mesh_kind === "delaunay"
    ? MAX_DELAUNAY_NODES : MAX_NODES;
  const nodes = minimumGridNodes(grid, 0);
  if (nodes > maxNodes) limit("grid_points", nodes, maxNodes);
  const vertex = Array.isArray(model.vertices) && isPlainObject(model.vertices[0]) ? model.vertices[0] : {};
  const generalized = isPlainObject(provenance.generalized_channels) ? provenance.generalized_channels.expressions : undefined;
  const entries = nodes * Math.max(
    blockSize(vertex.A, vertex.B, vertex.C, generalized),
    blockSize(recipe.A_expr, recipe.B_expr, recipe.C_expr, generalized),
  );
  if (entries > MAX_SAMPLED_VALUES) limit("sampled_values", entries, MAX_SAMPLED_VALUES);
}

export function oversizedNamedResamples(payload: Record<string, unknown>): Map<string, number> {
  const oversized = new Map<string, number>();
  if (isPlainObject(payload.resample_points)) {
    for (const [axis, count] of Object.entries(payload.resample_points)) {
      if (positiveInteger(count) && count > MAX_NODES) oversized.set(axis, count);
    }
  }
  return oversized;
}

export function checkNamedResample(axis: string, count: number): never {
  return limit(`resample_points.${axis}`, count, MAX_NODES);
}
