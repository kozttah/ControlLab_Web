/** Explicit transport aliases. Scientific validation remains in Python. */
import { ControlLabBridgeError, isPlainObject } from "../bridge/protocol.ts";
import type { RpcRequest } from "../bridge/protocol.ts";
import type { WorkerModelStore } from "./model_store.ts";

interface SourceGroup {
  target: string;
  inline: readonly string[];
  refs: readonly string[];
  kinds: readonly string[];
  competingRaw?: readonly string[];
}

const MODELS = ["StateSpace", "TransferFunction", "IdentifiedModel"];
// Serialized discriminants, not the Python class name TSStateSpace.
const TS_MODELS = ["ts_measured", "polytopic_uncertain", "ts_partially_observed"];
const REUSABLE = [...MODELS, ...TS_MODELS];
const dataset: SourceGroup = { target: "dataset", inline: ["dataset"], refs: ["dataset_ref"], kinds: ["Dataset"], competingRaw: ["u", "y", "t"] };
const validation: SourceGroup = { target: "val_dataset", inline: ["val_dataset"], refs: ["val_dataset_ref"], kinds: ["Dataset"] };
const plant: SourceGroup = { target: "plant", inline: ["plant", "model"], refs: ["plant_ref", "model_ref"], kinds: ["StateSpace", "TransferFunction"] };

const PLANT_OPERATIONS = new Set([
  "statespace.design_lqr", "statespace.design_lqi", "statespace.design_pole_placement",
  "statespace.design_observer", "statespace.design_kalman", "statespace.design_lqg",
  "statespace.analyze", "statespace.check_pbh", "statespace.gramians",
  "statespace.solve_care", "statespace.solve_dare", "statespace.solve_lyapunov",
  "statespace.discretize_zoh", "statespace.simulate_lti",
  "frequency.eval_response", "frequency.bode", "frequency.stability_margins",
  "frequency.root_locus", "frequency.step_response", "frequency.singular_values",
  "mimo.singular_values", "mimo.rga", "mimo.sensitivity",
  "mimo.design_decoupler", "mimo.simulate_closed_loop", "mimo.design_hinf",
  "io.export_pvm",
]);

function sources(operation: string, payload: Record<string, unknown>): readonly SourceGroup[] {
  if (operation === "core.reuse_model") {
    return [{ target: "model", inline: ["model"], refs: ["model_ref"], kinds: REUSABLE }];
  }
  if (["core.interconnect", "core.validate_interconnection"].includes(operation)) {
    return [{ target: "plant", inline: ["plant"], refs: ["plant_ref"], kinds: ["StateSpace", "TransferFunction", ...TS_MODELS] }];
  }
  if (["fuzzy.evaluate", "fuzzy.evaluate_surface", "fuzzy.export_fml"].includes(operation)) {
    return [{ target: "system", inline: ["system", "plant", "model"], refs: ["system_ref", "plant_ref", "model_ref"], kinds: ["FuzzySystem"] }];
  }
  if (["identification.fit_arx", "identification.fit_oe", "identification.fit_subspace"].includes(operation)) {
    return [dataset, validation];
  }
  if (operation === "identification.validate_model") {
    return [
      { target: "model", inline: ["model", "plant"], refs: ["model_ref", "plant_ref"], kinds: MODELS },
      { target: "val_dataset", inline: ["val_dataset", "dataset"], refs: ["val_dataset_ref", "dataset_ref"], kinds: ["Dataset"] },
      { target: "train_dataset", inline: ["train_dataset"], refs: ["train_dataset_ref"], kinds: ["Dataset"] },
    ];
  }
  if (["optimization.solve", "optimization.verify", "optimization.export_cvxpy", "optimization.export_yalmip"].includes(operation)) {
    const template = typeof payload.template === "string" ? payload.template.trim().toLowerCase() : "";
    if (template === "ts_pdc_stabilization") {
      return [{ target: "ts_model", inline: ["ts_model", "plant"], refs: ["ts_model_ref", "plant_ref"], kinds: TS_MODELS }];
    }
    if (["quadratic_stabilization", "continuous_stabilization", "decay_rate", "lqr_lmi", "regional_pole_placement"].includes(template)) {
      return [{ ...plant, kinds: ["StateSpace"], competingRaw: ["A", "B", "C", "D"] }];
    }
    return [];
  }
  if (operation === "mimo.simulate_closed_loop") {
    return [
      plant,
      { target: "decoupler", inline: ["decoupler"], refs: ["decoupler_ref"], kinds: ["StateSpace", "TransferFunction"] },
      { target: "controller", inline: ["controller"], refs: ["controller_ref"], kinds: ["StateSpace", "TransferFunction", "DynamicController"] },
    ];
  }
  if (!PLANT_OPERATIONS.has(operation)) return [];
  return [operation.startsWith("statespace.")
    ? { ...plant, kinds: ["StateSpace"], competingRaw: ["A", "B", "C", "D"] }
    : plant];
}

function invalid(field: string, message: string): never {
  throw new ControlLabBridgeError("VALIDATION_ERROR", message, {
    parameters: { ref_field: field },
    next_step: "Forneça uma única fonte canônica ou registre a identidade/revisão exata no mesmo projeto.",
  });
}

/** Resolves only known top-level aliases, never arbitrary provenance/user fields.
 * Preflight all source groups before any lookup. The caller's input and stored
 * DTOs remain unchanged; the scientific result is never registered here.
 */
export function materializePayloadReferences(
  request: Pick<RpcRequest, "operation" | "project_id">,
  payload: Record<string, unknown>,
  store: WorkerModelStore,
): Record<string, unknown> {
  const groups = sources(request.operation, payload);
  for (const group of groups) {
    const supplied = [...group.inline, ...group.refs].filter(key => Object.hasOwn(payload, key));
    if (supplied.length > 1) invalid(group.target, `Fontes simultâneas/ambíguas: ${supplied.join(", ")}.`);
    if (supplied.length === 1 && group.competingRaw?.some(key => Object.hasOwn(payload, key))) {
      invalid(group.target, `Fonte ${supplied[0]} simultânea a dados/matrizes inline.`);
    }
  }
  const resolved = structuredClone(payload);
  for (const group of groups) {
    const inline = group.inline.find(key => Object.hasOwn(payload, key));
    if (inline !== undefined) {
      resolved[group.target] = resolved[inline];
      if (inline !== group.target) delete resolved[inline];
      continue;
    }
    const field = group.refs.find(key => Object.hasOwn(payload, key));
    if (field === undefined) continue;
    const ref = payload[field];
    if (!isPlainObject(ref) || Object.keys(ref).length !== 2 ||
        !Object.hasOwn(ref, "id") || !Object.hasOwn(ref, "revision") ||
        typeof ref.id !== "string" || ref.id.trim().length === 0 ||
        typeof ref.revision !== "number" || !Number.isSafeInteger(ref.revision) || ref.revision < 0) {
      invalid(field, `${field} exige somente {id: string não vazia, revision: inteiro >= 0}.`);
    }
    const entry = store.get(request.project_id, ref.id, ref.revision);
    if (!entry) invalid(field, `${field} não encontrado no projeto e revisão solicitados.`);
    if (entry.project_id !== request.project_id || entry.object_id !== ref.id ||
        entry.revision !== ref.revision || entry.value.id !== ref.id ||
        entry.value.revision !== ref.revision || entry.kind !== entry.value.kind) {
      invalid(field, `${field} diverge da identidade/revisão/tipo do objeto armazenado.`);
    }
    if (!group.kinds.includes(entry.kind)) {
      throw new ControlLabBridgeError("UNSUPPORTED_MODEL", `${field} requer ${group.kinds.join("/")}, recebido ${entry.kind}.`, {
        parameters: { ref_field: field, kind: entry.kind },
      });
    }
    resolved[group.target] = structuredClone(entry.value);
    delete resolved[field];
  }
  return resolved;
}
