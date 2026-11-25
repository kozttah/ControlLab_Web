"""Conversão semântica Takagi-Sugeno e especificações PDC (ADR-006, R-05, Seções 4.3, 5.6, 13.7 e T-TS-01)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.core.controllers import (
    ALLOWED_PDC_TS_KINDS,
    PDCController,
    StateFeedbackController,
)
from control_lab.core.interconnect import TSClosedLoop, interconnect
from control_lab.core.models import FuzzySystem, StateSpace, TSStateSpace
from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .inference import _coerce_fuzzy_system, _compute_rule_activations, _evaluate_input_memberships
from .membership import evaluate_mf
from .symbolic_qlpv import evaluate_scalar

_EPS = 1e-12


def verify_convex_weights(
    weights: Sequence[float] | np.ndarray,
    *,
    atol: float = 1e-9,
) -> dict[str, Any]:
    """Verifica a propriedade de soma convexa `h_i >= 0` e `sum_i h_i == 1` dos pesos TS."""
    h_arr = ensure_finite_float64(weights, ndim=1, name="weights")
    if h_arr.size < 1:
        raise ValidationError("Vetor de pesos TS não pode ser vazio.")
    min_h = float(np.min(h_arr))
    sum_h = float(np.sum(h_arr))
    sum_err = abs(sum_h - 1.0)
    non_negative = min_h >= -atol
    sums_to_one = sum_err <= atol
    if not non_negative:
        raise HypothesisViolatedError(
            message=f"Propriedade de não negatividade violada nos pesos TS: min(h_i) = {min_h:.3e} < 0.",
            parameters={"min_weight": min_h, "atol": atol},
        )
    if not sums_to_one:
        raise HypothesisViolatedError(
            message=f"Propriedade de soma convexa violada nos pesos TS: sum(h_i) = {sum_h:.9f} != 1.0.",
            parameters={"sum_weights": sum_h, "residual": sum_err, "atol": atol},
        )
    return {
        "valid_convex_sum": True,
        "min_weight": min_h,
        "sum_weights": sum_h,
        "convex_sum_residual": sum_err,
    }


def evaluate_ts_premise_weights(
    ts_model: TSStateSpace | FuzzySystem | Mapping[str, Any],
    premise_values: Mapping[str, float] | Sequence[float] | np.ndarray,
    *,
    atol: float = 1e-9,
) -> Result:
    """Avalia `h_i(z) = w_i(z) / sum_j w_j(z)` a partir de `FuzzySystem` ou `TSStateSpace.membership_spec`."""
    try:
        if isinstance(ts_model, FuzzySystem) or (isinstance(ts_model, Mapping) and ts_model.get("kind") == "FuzzySystem"):
            fs = _coerce_fuzzy_system(ts_model)
            in_vars = fs.input_variables
            in_names = [v["name"] for v in in_vars]
            if isinstance(premise_values, Mapping):
                eval_in = {nm: float(premise_values[nm]) for nm in in_names}
            else:
                z_arr = ensure_finite_float64(premise_values, ndim=1, name="premise_values")
                if z_arr.size != len(in_names):
                    raise DimensionMismatchError(
                        f"Esperado {len(in_names)} variáveis de premissa, recebido {z_arr.size}."
                    )
                eval_in = {in_names[i]: float(z_arr[i]) for i in range(len(in_names))}
            mems = _evaluate_input_memberships(eval_in, in_vars)
            acts = _compute_rule_activations(fs.rules, mems, fs.operators)
            w_arr = np.asarray(acts, dtype=np.float64)
            model_rev = fs.revision
        else:
            ts_obj = ts_model if isinstance(ts_model, TSStateSpace) else TSStateSpace.from_dict(ts_model)
            if ts_obj.kind == "polytopic_uncertain":
                raise HypothesisViolatedError(
                    message=(
                        "TSStateSpace(kind='polytopic_uncertain') possui pesos politópicos desconhecidos em tempo real; "
                        "não há função h_i(z(t)) mensurável para avaliação online (ADR-006 / T-TS-01)."
                    ),
                    parameters={"ts_kind": ts_obj.kind},
                )
            ms = ts_obj.membership_spec
            p_vars = list(ms["premise_variables"])
            funcs = ms.get("functions", [])
            if len(funcs) != ts_obj.n_vertices:
                raise HypothesisViolatedError(
                    f"membership_spec.functions ({len(funcs)}) deve ter uma entrada por vértice ({ts_obj.n_vertices}) para avaliação direta."
                )

            if ms.get("representation_kind") == "sector_nonlinearity":
                sector_premises = ms.get("sector_premises", [])
                if not isinstance(sector_premises, Sequence) or len(sector_premises) != len(p_vars):
                    raise ValidationError(
                        "membership_spec.sector_premises deve conter exatamente uma entrada por premise_variable."
                    )

                if isinstance(premise_values, Mapping):
                    if all(nm in premise_values for nm in p_vars):
                        eval_in = {nm: float(premise_values[nm]) for nm in p_vars}
                    else:
                        raw_env = {str(k): float(v) for k, v in premise_values.items()}
                        eval_in = {}
                        for sp in sector_premises:
                            sp_name = str(sp["name"])
                            if sp_name in raw_env:
                                eval_in[sp_name] = raw_env[sp_name]
                            else:
                                eval_in[sp_name] = float(evaluate_scalar(str(sp["expression"]), raw_env))
                else:
                    z_arr = ensure_finite_float64(premise_values, ndim=1, name="premise_values")
                    if z_arr.size == len(p_vars):
                        eval_in = {p_vars[i]: float(z_arr[i]) for i in range(len(p_vars))}
                    elif z_arr.size == ts_obj.n_states:
                        raw_env = {ts_obj.state_names[i]: float(z_arr[i]) for i in range(ts_obj.n_states)}
                        eval_in = {
                            str(sp["name"]): float(evaluate_scalar(str(sp["expression"]), raw_env))
                            for sp in sector_premises
                        }
                    else:
                        raise DimensionMismatchError(
                            f"Esperado {len(p_vars)} premissas ou {ts_obj.n_states} estados, recebido {z_arr.size}."
                        )

                w0_vec: list[float] = []
                w1_vec: list[float] = []
                for sp in sector_premises:
                    sp_name = str(sp["name"])
                    z_min = float(sp["min"])
                    z_max = float(sp["max"])
                    span = z_max - z_min
                    if span <= _EPS:
                        raise ValidationError(f"Premissa setorial {sp_name!r} possui intervalo degenerado [{z_min}, {z_max}].")
                    zk = eval_in[sp_name]
                    w0_vec.append((zk - z_min) / span)
                    w1_vec.append((z_max - zk) / span)

                w_list: list[float] = []
                for f_spec in funcs:
                    bits = f_spec.get("bits")
                    if not isinstance(bits, Sequence) or len(bits) != len(sector_premises):
                        raise ValidationError(
                            f"Função setorial {f_spec!r} requer 'bits' de comprimento {len(sector_premises)}."
                        )
                    prod_val = 1.0
                    for k, b in enumerate(bits):
                        prod_val *= w0_vec[k] if int(b) == 0 else w1_vec[k]
                    w_list.append(float(prod_val))
                w_arr = np.asarray(w_list, dtype=np.float64)
                model_rev = ts_obj.revision
            elif ms.get("representation_kind") == "tpmt_interpolated":
                tpmt_axes = ms.get("tpmt_axes", [])
                if not isinstance(tpmt_axes, Sequence) or len(tpmt_axes) != len(p_vars):
                    raise ValidationError(
                        "membership_spec.tpmt_axes deve conter exatamente uma entrada por premise_variable."
                    )

                if isinstance(premise_values, Mapping):
                    raw_env = {str(k): float(v) for k, v in premise_values.items()}
                    eval_in = {}
                    for ax in tpmt_axes:
                        var_name = str(ax["variable"])
                        if var_name in raw_env:
                            eval_in[var_name] = raw_env[var_name]
                        else:
                            expr = str(ax.get("expression", var_name))
                            eval_in[var_name] = float(evaluate_scalar(expr, raw_env))
                else:
                    z_arr = ensure_finite_float64(premise_values, ndim=1, name="premise_values")
                    if z_arr.size == len(p_vars):
                        eval_in = {str(tpmt_axes[i]["variable"]): float(z_arr[i]) for i in range(len(p_vars))}
                    elif z_arr.size == ts_obj.n_states:
                        raw_env = {ts_obj.state_names[i]: float(z_arr[i]) for i in range(ts_obj.n_states)}
                        eval_in = {}
                        for ax in tpmt_axes:
                            var_name = str(ax["variable"])
                            if var_name in raw_env:
                                eval_in[var_name] = raw_env[var_name]
                            else:
                                eval_in[var_name] = float(evaluate_scalar(str(ax.get("expression", var_name)), raw_env))
                    else:
                        raise DimensionMismatchError(
                            f"Esperado {len(p_vars)} premissas ou {ts_obj.n_states} estados, recebido {z_arr.size}."
                        )

                axis_weights: list[np.ndarray] = []
                for ax in tpmt_axes:
                    var_name = str(ax["variable"])
                    grid_d = ensure_finite_float64(ax["grid"], ndim=1, name=f"tpmt_axes[{var_name}].grid")
                    w_table = ensure_finite_float64(ax["weights_table"], ndim=2, name=f"tpmt_axes[{var_name}].weights_table")
                    if grid_d.size < 2 or w_table.shape[0] != grid_d.size:
                        raise ValidationError(
                            f"Eixo TPMT {var_name!r} com grid ({grid_d.size}) incompatível com weights_table {w_table.shape}."
                        )
                    p_val = float(np.clip(eval_in[var_name], grid_d[0], grid_d[-1]))
                    w_d = np.array(
                        [float(np.interp(p_val, grid_d, w_table[:, j])) for j in range(w_table.shape[1])],
                        dtype=np.float64,
                    )
                    axis_weights.append(w_d)

                w_list = []
                for f_spec in funcs:
                    basis_idx = f_spec.get("axis_basis_indices")
                    if not isinstance(basis_idx, Sequence) or len(basis_idx) != len(tpmt_axes):
                        raise ValidationError(
                            f"Função TPMT {f_spec!r} requer 'axis_basis_indices' de comprimento {len(tpmt_axes)}."
                        )
                    prod_val = 1.0
                    for d_idx, j_idx in enumerate(basis_idx):
                        j_int = int(j_idx)
                        if j_int < 0 or j_int >= axis_weights[d_idx].size:
                            raise ValidationError(
                                f"Índice de base {j_int} fora do intervalo [0, {axis_weights[d_idx].size - 1}] no eixo {d_idx}."
                            )
                        prod_val *= float(axis_weights[d_idx][j_int])
                    w_list.append(float(prod_val))
                w_arr = np.asarray(w_list, dtype=np.float64)
                model_rev = ts_obj.revision
            else:
                if isinstance(premise_values, Mapping):
                    eval_in = {nm: float(premise_values[nm]) for nm in p_vars}
                else:
                    z_arr = ensure_finite_float64(premise_values, ndim=1, name="premise_values")
                    if z_arr.size != len(p_vars):
                        raise DimensionMismatchError(f"Esperado {len(p_vars)} premissas, recebido {z_arr.size}.")
                    eval_in = {p_vars[i]: float(z_arr[i]) for i in range(len(p_vars))}

                w_list = []
                for f_spec in funcs:
                    if "clauses" in f_spec:
                        deg = 1.0
                        for cl in f_spec["clauses"]:
                            v_val = eval_in[cl["variable"]]
                            deg *= float(evaluate_mf(cl["mf"], cl["params"], v_val, complement=bool(cl.get("complement", False))))
                        w_list.append(deg)
                    elif "mf" in f_spec and "variable" in f_spec:
                        v_val = eval_in[f_spec["variable"]]
                        w_list.append(float(evaluate_mf(f_spec["mf"], f_spec["params"], v_val)))
                    elif "weight" in f_spec:
                        w_list.append(float(f_spec["weight"]))
                    else:
                        raise ValidationError(f"Formato de função de premissa não reconhecido: {f_spec!r}")
                w_arr = np.asarray(w_list, dtype=np.float64)
                model_rev = ts_obj.revision

        sum_w = float(np.sum(w_arr))
        if sum_w <= _EPS:
            raise HypothesisViolatedError(
                message="Soma de ativações nula (sum(w_i(z)) == 0) no ponto consultado; propriedade de soma convexa não satisfeita.",
                parameters={"premise_values": eval_in, "sum_w": sum_w},
            )
        h_arr = w_arr / sum_w
        conv_diag = verify_convex_weights(h_arr, atol=atol)

        return Result(
            status="success",
            data={
                "weights": [float(v) for v in h_arr.tolist()],
                "raw_activations": [float(v) for v in w_arr.tolist()],
                "premise_values": eval_in,
            },
            assumptions={"sum_to_one": True, "non_negative": True},
            diagnostics=conv_diag,
            provenance=build_provenance("control_lab.fuzzy.evaluate_ts_premise_weights", model_revision=model_rev),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.evaluate_ts_premise_weights"),
            warnings=(),
            error=exc.to_typed_error(),
        )


def to_ts_state_space(
    system: FuzzySystem | Mapping[str, Any],
    *,
    dynamic_vertices: Sequence[Mapping[str, Any]] | None = None,
    kind: str = "ts_measured",
    dt: float | None = None,
    premise_availability: Mapping[str, Any] | None = None,
    state_names: Sequence[str] | None = None,
    input_names: Sequence[str] | None = None,
    output_names: Sequence[str] | None = None,
    units: Mapping[str, Any] | None = None,
    membership_version: str = "1.0.0",
    n_grid_verify: int = 11,
) -> Result:
    """Converte um `FuzzySystem` Takagi-Sugeno em `TSStateSpace` canônico **somente** quando a dinâmica e os estados foram explicitamente identificados (ADR-006, R-05, Seção 5.6, Seção 13.7).

    Regras inegociáveis:
    1. **PROIBIDO** converter aproximador estático ANFIS (`is_dynamic_model=False` e sem equação de estado explícita em `dynamic_semantics` ou `dynamic_vertices` validados) diretamente em `TSStateSpace`. Se chamado sobre um aproximador estático sem dinâmica, retorna `status='failure'` com código `HYPOTHESIS_VIOLATED` (ou `UNSUPPORTED_MODEL`) citando `ADR-006`.
    2. Verifica numericamente a propriedade de soma convexa `sum_i h_i(z) == 1`, `h_i(z) >= 0` no domínio das premissas.
    """
    try:
        fs = _coerce_fuzzy_system(system)

        if fs.inference_type != "ts":
            raise UnsupportedModelError(
                message=(
                    f"to_ts_state_space requer sistema Takagi-Sugeno (inference_type='ts'), "
                    f"recebido {fs.inference_type!r} (ADR-006)."
                ),
                parameters={"inference_type": fs.inference_type},
                next_step="Use um modelo Takagi-Sugeno com equações de estado locais identificadas por regra.",
            )

        dyn_sem = fs.dynamic_semantics if fs.dynamic_semantics is not None else {}
        verts_source = dynamic_vertices if dynamic_vertices is not None else dyn_sem.get("vertices")

        # Bloqueio estrito ADR-006 / Seção 5.6 / Seção 13.7:
        # Nunca converter aproximador estático entrada-saída ANFIS em TSStateSpace dinâmico!
        if not fs.is_dynamic_model or verts_source is None:
            raise HypothesisViolatedError(
                message=(
                    "Violação de ADR-006 / Seção 5.6: não é permitido converter um aproximador estático "
                    "Fuzzy/ANFIS (is_dynamic_model=False ou sem vértices de estado (A_i, B_i, C_i, D_i) "
                    "explicitamente identificados) em TSStateSpace dinâmico."
                ),
                parameters={
                    "system_id": fs.id,
                    "is_dynamic_model": fs.is_dynamic_model,
                    "has_dynamic_vertices": verts_source is not None,
                    "adr": "ADR-006",
                },
                next_step=(
                    "Identifique explicitamente a dinâmica em espaço de estados por regra "
                    "(is_dynamic_model=True e dynamic_semantics.vertices com matrizes A_i, B_i, C_i, D_i) "
                    "antes de construir um TSStateSpace."
                ),
            )

        if not isinstance(verts_source, Sequence) or len(verts_source) != len(fs.rules):
            raise DimensionMismatchError(
                message=(
                    f"Número de vértices dinâmicos ({len(verts_source) if isinstance(verts_source, Sequence) else 0}) "
                    f"deve coincidir com o número de regras TS ({len(fs.rules)})."
                ),
                parameters={"n_rules": len(fs.rules)},
            )

        # Verifica se as regras cobrem o domínio com soma convexa h_i(z) >= 0, sum h_i(z) = 1
        in_vars = fs.input_variables
        p_vars = [v["name"] for v in in_vars]
        bounds = {v["name"]: [float(v["universe"][0]), float(v["universe"][1])] for v in in_vars}

        grids = [
            np.linspace(float(v["universe"][0]), float(v["universe"][1]), n_grid_verify, dtype=np.float64)
            for v in in_vars
        ]
        mesh = np.meshgrid(*grids, indexing="ij")
        pts = np.stack([m.ravel() for m in mesh], axis=-1)
        max_conv_residual = 0.0
        for pt in pts:
            eval_in = {p_vars[d]: float(pt[d]) for d in range(len(p_vars))}
            mems = _evaluate_input_memberships(eval_in, in_vars)
            acts = _compute_rule_activations(fs.rules, mems, fs.operators)
            sw = float(np.sum(acts))
            if sw <= _EPS:
                raise HypothesisViolatedError(
                    message=(
                        f"Modelo TS possui ponto sem ativação no domínio ({eval_in}): sum(w_i(z)) = 0; "
                        "impossível garantir soma convexa sum_i h_i(z) = 1 em todo o domínio."
                    ),
                    parameters={"point": eval_in},
                )
            h_vec = np.asarray(acts, dtype=np.float64) / sw
            c_diag = verify_convex_weights(h_vec)
            max_conv_residual = max(max_conv_residual, float(c_diag["convex_sum_residual"]))

        # Constrói especificação das funções de premissa por regra/vértice
        term_map_by_var = {
            v["name"]: {t["name"]: t for t in v["terms"]}
            for v in in_vars
        }
        functions_spec: list[dict[str, Any]] = []
        for idx, rule in enumerate(fs.rules):
            clauses_spec: list[dict[str, Any]] = []
            for vname, tname in rule["antecedents"].items():
                t_obj = term_map_by_var[vname][tname]
                mf_t = t_obj.get("mf") or t_obj.get("type")
                clauses_spec.append(
                    {
                        "variable": vname,
                        "term": tname,
                        "mf": str(mf_t),
                        "params": list(t_obj.get("params", [])),
                        "complement": bool(t_obj.get("complement", False)),
                    }
                )
            functions_spec.append(
                {
                    "vertex_id": str(verts_source[idx].get("vertex_id", f"v{idx + 1}")),
                    "rule_name": str(rule.get("name", f"R{idx + 1}")),
                    "clauses": clauses_spec,
                }
            )

        membership_spec = {
            "version": membership_version,
            "premise_variables": p_vars,
            "sum_to_one_domain": True,
            "functions": functions_spec,
        }

        resolved_dt = dt if dt is not None else dyn_sem.get("dt", None)
        resolved_kind = str(dyn_sem.get("kind", kind))

        if premise_availability is None:
            if "premise_availability" in dyn_sem and isinstance(dyn_sem["premise_availability"], Mapping):
                resolved_pa = dict(dyn_sem["premise_availability"])
            elif resolved_kind == "ts_measured":
                resolved_pa = {
                    "mode": "all_measured",
                    "measured_premises": list(p_vars),
                    "unmeasured_premises": [],
                    "estimator_required_for_pdc": False,
                }
            elif resolved_kind == "polytopic_uncertain":
                resolved_pa = {
                    "mode": "unknown_uncertain",
                    "measured_premises": [],
                    "unmeasured_premises": list(p_vars),
                    "estimator_required_for_pdc": True,
                }
            else:
                resolved_pa = {
                    "mode": "partially_observed",
                    "measured_premises": list(p_vars[:-1]),
                    "unmeasured_premises": list(p_vars[-1:]),
                    "estimator_required_for_pdc": True,
                }
        else:
            resolved_pa = dict(premise_availability)

        ts_ss = TSStateSpace(
            vertices=verts_source,
            kind=resolved_kind,
            dt=resolved_dt,
            membership_spec=membership_spec,
            premise_availability=resolved_pa,
            domain={"bounds": bounds},
            state_names=state_names or dyn_sem.get("state_names"),
            input_names=input_names or dyn_sem.get("input_names"),
            output_names=output_names or dyn_sem.get("output_names"),
            units=units or dyn_sem.get("units"),
            provenance={
                "source": "to_ts_state_space",
                "fuzzy_system_id": fs.id,
                "fuzzy_system_revision": fs.revision,
            },
        )

        return Result(
            status="success",
            data={
                "ts_state_space": ts_ss.to_dict(),
                "model_id": ts_ss.id,
                "kind": ts_ss.kind,
                "n_vertices": ts_ss.n_vertices,
            },
            assumptions={
                "is_dynamic_model": True,
                "adr_006_verified": True,
                "convex_sum_verified_on_grid": True,
            },
            diagnostics={
                "n_vertices": ts_ss.n_vertices,
                "n_states": ts_ss.n_states,
                "n_inputs": ts_ss.n_inputs,
                "n_outputs": ts_ss.n_outputs,
                "max_convex_sum_residual": max_conv_residual,
                "grid_points_checked": int(pts.shape[0]),
            },
            provenance=build_provenance(
                "control_lab.fuzzy.to_ts_state_space",
                model_revision=ts_ss.revision,
            ),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={"adr_006_enforced": True},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.to_ts_state_space"),
            warnings=(),
            error=exc.to_typed_error(),
        )


def make_pdc_spec(
    ts_model: TSStateSpace | Mapping[str, Any],
    gains: Sequence[Any] | np.ndarray | None = None,
    *,
    feedback_sign: str = "negative",
    architecture: str = "pdc",
    premise_estimator: Any = None,
    reference_map: Any = None,
    requires_full_state: bool = True,
) -> Result:
    """Constrói especificação de síntese/implementação PDC ou controlador `PDCController` (Seção 4.3, 13.7, ADR-006 e T-TS-01).

    Regras inegociáveis (`T-TS-01` / `ADR-006`):
    - Se `ts_model.kind == "polytopic_uncertain"` e `architecture == "pdc"` (agendamento pelas premissas em tempo real)
      sem `premise_estimator` explícito, **RECUSA** com `status='failure'` e erro tipado `HYPOTHESIS_VIOLATED`,
      pois os pesos politópicos `alpha_i(t)` não são mensuráveis em tempo real.
    - Para `polytopic_uncertain` com `architecture == "robust_single_gain"`, gera especificação robusta de ganho único
      (`StateFeedbackController` se um ganho `K` for fornecido).
    - Para `ts_partially_observed` sem `premise_estimator` quando há premissas não medidas, bloqueia a instanciação
      direta de `PDCController` ou exige estimador explícito.
    """
    try:
        ts_obj = ts_model if isinstance(ts_model, TSStateSpace) else TSStateSpace.from_dict(ts_model)
        arch = str(architecture or "pdc").strip().lower()
        if arch not in ("pdc", "robust_single_gain"):
            raise ValidationError(
                message=f"Arquitetura de controle TS inválida: {architecture!r}. Use 'pdc' ou 'robust_single_gain'.",
                parameters={"architecture": architecture},
            )

        # Bloqueio normativo T-TS-01 / ADR-006 / R-05
        if ts_obj.kind == "polytopic_uncertain" and arch == "pdc" and premise_estimator is None:
            raise HypothesisViolatedError(
                message=(
                    "Bloqueio T-TS-01 / ADR-006: TSStateSpace(kind='polytopic_uncertain') possui premissas/pesos "
                    "politópicos desconhecidos em tempo real; agendamento PDC u(t) = sign * sum_j h_j(z(t)) K_j x(t) "
                    "não é fisicamente implementável sem estimador explícito."
                ),
                parameters={
                    "ts_model_id": ts_obj.id,
                    "ts_kind": ts_obj.kind,
                    "premise_mode": ts_obj.premise_availability["mode"],
                    "requested_architecture": arch,
                },
                next_step=(
                    "Use architecture='robust_single_gain' (ganho único robusto K independente de alpha(t)) "
                    "ou forneça um modelo 'ts_measured' com premissas mensuráveis."
                ),
            )

        if ts_obj.kind == "ts_partially_observed" and arch == "pdc" and premise_estimator is None:
            raise HypothesisViolatedError(
                message=(
                    "Bloqueio ADR-006 / Seção 4.3: TSStateSpace(kind='ts_partially_observed') possui premissas "
                    f"não medidas ({ts_obj.premise_availability['unmeasured_premises']}); síntese/implementação PDC "
                    "requer premise_estimator explícito."
                ),
                parameters={
                    "ts_model_id": ts_obj.id,
                    "ts_kind": ts_obj.kind,
                    "unmeasured_premises": ts_obj.premise_availability["unmeasured_premises"],
                },
                next_step="Forneça premise_estimator explícito ou use architecture='robust_single_gain'.",
            )

        r = ts_obj.n_vertices
        n = ts_obj.n_states
        m = ts_obj.n_inputs

        membership_ref = {
            "model_id": ts_obj.id,
            "model_revision": ts_obj.revision,
            "membership_version": ts_obj.membership_spec["version"],
        }
        measurement_requirements = {
            "required_premise_variables": list(ts_obj.membership_spec["premise_variables"]),
            "requires_full_state": bool(requires_full_state),
            "allowed_ts_kinds": (
                ["ts_measured", "ts_partially_observed"]
                if ts_obj.kind == "ts_partially_observed"
                else ["ts_measured"]
            ),
        }

        if arch == "robust_single_gain":
            spec_payload: dict[str, Any] = {
                "architecture": "robust_single_gain",
                "ts_kind": ts_obj.kind,
                "feedback_sign": feedback_sign,
                "n_vertices": r,
                "n_states": n,
                "n_inputs": m,
                "lmi_structure": "single_gain_vertex_lmis",
                "double_sum_required": False,
                "controller": None,
            }
            if gains is not None:
                # Ganho único K (m, n) ou lista de 1 matriz 2D [K]
                if (
                    isinstance(gains, Sequence)
                    and not isinstance(gains, np.ndarray)
                    and len(gains) == 1
                    and isinstance(gains[0], (Sequence, np.ndarray))
                    and len(gains[0]) > 0
                    and isinstance(gains[0][0], (Sequence, np.ndarray))
                ):
                    K_mat = ensure_finite_float64(gains[0], ndim=2, name="K")
                else:
                    K_mat = ensure_finite_float64(gains, ndim=2, name="K")
                sf_ctrl = StateFeedbackController(
                    K=K_mat,
                    feedback_sign=feedback_sign,
                    state_coordinates=ts_obj.state_names,
                    reference_map=reference_map,
                    dt=ts_obj.dt,
                    provenance={
                        "source": "make_pdc_spec.robust_single_gain",
                        "ts_model_id": ts_obj.id,
                        "ts_model_revision": ts_obj.revision,
                    },
                )
                spec_payload["controller"] = sf_ctrl.to_dict()

            return Result(
                status="success",
                data=spec_payload,
                assumptions={
                    "architecture": "robust_single_gain",
                    "premise_scheduling_used": False,
                    "implementable_without_premise_measurement": True,
                },
                diagnostics={"n_vertices": r, "n_lmi_blocks": r},
                provenance=build_provenance("control_lab.fuzzy.make_pdc_spec", model_revision=ts_obj.revision),
            )

        # Arquitetura PDC (ts_measured ou ts_partially_observed com premise_estimator)
        cross_pairs = [(i, j) for i in range(r) for j in range(i + 1, r)]
        pdc_spec: dict[str, Any] = {
            "architecture": "pdc",
            "ts_kind": ts_obj.kind,
            "feedback_sign": feedback_sign,
            "membership_ref": membership_ref,
            "measurement_requirements": measurement_requirements,
            "n_vertices": r,
            "n_states": n,
            "n_inputs": m,
            "double_sum_required": True,
            "diagonal_pairs": [(i, i) for i in range(r)],
            "off_diagonal_pairs": cross_pairs,
            "controller": None,
            "closed_loop": None,
        }

        if gains is not None:
            pdc_ctrl = PDCController(
                K_i=gains,
                feedback_sign=feedback_sign,
                membership_ref=membership_ref,
                measurement_requirements=measurement_requirements,
                state_coordinates=ts_obj.state_names,
                reference_map=reference_map,
                dt=ts_obj.dt,
                provenance={
                    "source": "make_pdc_spec",
                    "ts_model_id": ts_obj.id,
                    "ts_model_revision": ts_obj.revision,
                },
            )
            pdc_ctrl.validate_against_ts_model(ts_obj, premise_estimator=premise_estimator)
            cl_obj = interconnect(
                ts_obj,
                pdc_ctrl,
                wiring={"premise_estimator": premise_estimator} if premise_estimator is not None else None,
                sign_convention=feedback_sign,
            )
            pdc_spec["controller"] = pdc_ctrl.to_dict()
            if isinstance(cl_obj, Result):
                if cl_obj.status == "failure" or cl_obj.data is None:
                    return cl_obj
                pdc_spec["closed_loop"] = cl_obj.data["closed_loop"]
            else:
                pdc_spec["closed_loop"] = cl_obj.to_dict()

        return Result(
            status="success",
            data=pdc_spec,
            assumptions={
                "architecture": "pdc",
                "premises_measurable_or_estimated": True,
                "double_sum_expanded": True,
                "frozen_average_prohibited_for_general_validation": True,
            },
            diagnostics={
                "n_vertices": r,
                "n_diagonal_terms": r,
                "n_off_diagonal_pairs": len(cross_pairs),
                "total_cross_matrices": r * r,
            },
            provenance=build_provenance("control_lab.fuzzy.make_pdc_spec", model_revision=ts_obj.revision),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={"t_ts_01_enforced": True},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.make_pdc_spec"),
            warnings=(),
            error=exc.to_typed_error(),
        )


def evaluate_ts_frozen_weights(
    closed_loop: TSClosedLoop | Mapping[str, Any],
    weights: Sequence[float] | np.ndarray,
) -> Result:
    """Avalia a dinâmica instantânea `sum_i sum_j h_i h_j (A_i + sign * B_i K_j)` sob pesos fixos `h`.

    Nota científica (Seções 4.3 e 13.7): A equivalência sob pesos congelados `h` é apenas um caso particular
    instantâneo/LTI local e **não** constitui prova geral de estabilidade do sistema TS variante no tempo.
    """
    try:
        cl_obj = closed_loop if isinstance(closed_loop, TSClosedLoop) else TSClosedLoop.from_dict(closed_loop)
        conv_diag = verify_convex_weights(weights)
        ss_local: StateSpace = cl_obj.evaluate_at_weights(weights)
        eigs = np.linalg.eigvals(ss_local.A)
        if ss_local.is_continuous:
            locally_stable = bool(np.all(np.real(eigs) < -1e-9))
        else:
            locally_stable = bool(np.all(np.abs(eigs) < 1.0 - 1e-9))

        return Result(
            status="warning",
            data={
                "local_state_space": ss_local.to_dict(),
                "weights": [float(v) for v in np.asarray(weights, dtype=np.float64).tolist()],
                "eigenvalues": {
                    "real": [float(v) for v in np.real(eigs).tolist()],
                    "imag": [float(v) for v in np.imag(eigs).tolist()],
                },
                "locally_stable": locally_stable,
            },
            assumptions={
                "frozen_weights_particular_case": True,
                "not_a_general_ts_stability_proof": True,
            },
            diagnostics={
                **conv_diag,
                "max_real_eig": float(np.max(np.real(eigs))),
                "spectral_radius": float(np.max(np.abs(eigs))),
            },
            provenance=build_provenance("control_lab.fuzzy.evaluate_ts_frozen_weights"),
            warnings=(
                WarningItem(
                    code="FROZEN_WEIGHTS_PARTICULAR_CASE_ONLY",
                    message=(
                        "Avaliação com pesos fixos h é apenas um caso particular congelado e "
                        "NÃO substitui a verificação por LMIs cruzadas para estabilidade TS geral (Seção 4.3 / 13.7)."
                    ),
                    details={"weights": [float(v) for v in np.asarray(weights, dtype=np.float64).tolist()]},
                ),
            ),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.evaluate_ts_frozen_weights"),
            warnings=(),
            error=exc.to_typed_error(),
        )
