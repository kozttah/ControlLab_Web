"""Motor de inferência Mamdani e Takagi-Sugeno e validação de cobertura (CL-DIR-001 Seção 5.6, 13.7)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.core.models import FuzzySystem
from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .membership import (
    apply_s_norm,
    apply_t_norm,
    evaluate_mf,
    extract_term_spec,
    linear,
)

_EPS = 1e-12

SUPPORTED_DEFUZZ_METHODS: tuple[str, ...] = (
    "centroid",
    "bisector",
    "mom",
    "som",
    "lom",
    "wtaver",
    "wtsum",
)

DEFUZZ_ALIASES: dict[str, str] = {
    "centroid": "centroid",
    "cog": "centroid",
    "coa": "centroid",
    "cg": "centroid",
    "center_of_gravity": "centroid",
    "bisector": "bisector",
    "boa": "bisector",
    "mom": "mom",
    "mean_of_maxima": "mom",
    "som": "som",
    "lm": "som",
    "smallest_of_maxima": "som",
    "lom": "lom",
    "rm": "lom",
    "largest_of_maxima": "lom",
    "wtaver": "wtaver",
    "weighted_average": "wtaver",
    "wtsum": "wtsum",
    "weighted_sum": "wtsum",
}


def normalize_defuzz_method(raw_method: Any, *, inference_type: str = "mamdani") -> str:
    if raw_method is None:
        return "centroid" if inference_type == "mamdani" else "wtaver"
    if not isinstance(raw_method, str) or not raw_method.strip():
        raise ValidationError(f"Método de defuzzificação inválido: {raw_method!r}")
    key = raw_method.strip().lower().replace("-", "_")
    if key in DEFUZZ_ALIASES:
        return DEFUZZ_ALIASES[key]
    raise ValidationError(
        message=f"Método de defuzzificação não suportado: {raw_method!r}.",
        parameters={"defuzzification": raw_method, "supported": list(SUPPORTED_DEFUZZ_METHODS)},
    )


def defuzzify_curve(
    grid: np.ndarray,
    mu: np.ndarray,
    method: str = "centroid",
    *,
    default_value: float | None = None,
) -> tuple[float, float, bool]:
    """Defuzzifica curva agregada Mamdani `mu(grid)` retornando `(valor, area_massa, ativacao_nula)`."""
    canonical = normalize_defuzz_method(method, inference_type="mamdani")
    g = np.asarray(grid, dtype=np.float64)
    m = np.clip(np.asarray(mu, dtype=np.float64), 0.0, 1.0)
    mass = float(np.sum(m))
    max_mu = float(np.max(m)) if m.size > 0 else 0.0

    if g.size == 0 or mass <= _EPS or max_mu <= _EPS or not np.isfinite(mass):
        neutral = float(default_value) if default_value is not None else 0.0
        return neutral, 0.0, True

    if canonical == "centroid":
        # Integração discreta em malha uniforme equivale à média ponderada sum(g * m) / sum(m)
        val = float(np.sum(g * m) / mass)
        return val, mass, False

    if canonical == "bisector":
        # Ponto que divide a área acumulada (trapézio) em duas partes iguais
        if g.size == 1:
            return float(g[0]), mass, False
        dx = np.diff(g)
        seg_areas = 0.5 * (m[:-1] + m[1:]) * dx
        cum_area = np.concatenate(([0.0], np.cumsum(seg_areas)))
        total_area = float(cum_area[-1])
        if total_area <= _EPS:
            val = float(np.sum(g * m) / mass)
            return val, mass, False
        half = 0.5 * total_area
        idx = int(np.searchsorted(cum_area, half, side="left"))
        if idx <= 0:
            return float(g[0]), total_area, False
        if idx >= g.size:
            return float(g[-1]), total_area, False
        a0, a1 = float(cum_area[idx - 1]), float(cum_area[idx])
        if abs(a1 - a0) <= _EPS:
            return float(g[idx]), total_area, False
        frac = (half - a0) / (a1 - a0)
        val = float(g[idx - 1] + frac * (g[idx] - g[idx - 1]))
        return val, total_area, False

    # Métodos de máximo (MOM, SOM, LOM)
    max_mask = np.abs(m - max_mu) <= 1e-12
    max_points = g[max_mask]
    if max_points.size == 0:
        max_points = np.array([g[int(np.argmax(m))]], dtype=np.float64)

    if canonical == "som":
        return float(np.min(max_points)), mass, False
    if canonical == "lom":
        return float(np.max(max_points)), mass, False
    # mom
    return float(np.mean(max_points)), mass, False


def _coerce_fuzzy_system(system: FuzzySystem | Mapping[str, Any]) -> FuzzySystem:
    if isinstance(system, FuzzySystem):
        return system
    if isinstance(system, Mapping):
        if "kind" in system and system.get("kind") == "FuzzySystem":
            return FuzzySystem.from_dict(system)
        return FuzzySystem(
            inference_type=str(system.get("inference_type", "mamdani")),
            input_variables=system["input_variables"],
            output_variables=system["output_variables"],
            rules=system.get("rules", []),
            operators=system.get("operators"),
            fml_profile=str(system.get("fml_profile", "IEEE-1855-2016")),
            is_dynamic_model=bool(system.get("is_dynamic_model", False)),
            dynamic_semantics=system.get("dynamic_semantics"),
            id=system.get("id"),
            revision=int(system.get("revision", 0)),
            provenance=system.get("provenance"),
        )
    raise ValidationError(f"Esperado FuzzySystem ou dict compatível, recebido {type(system).__name__}.")


def _parse_inputs(
    inputs: Mapping[str, Any] | Sequence[Any] | np.ndarray | float | int,
    input_vars: Sequence[Mapping[str, Any]],
    *,
    saturate: bool,
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    in_names = [v["name"] for v in input_vars]
    n_in = len(in_names)
    raw_map: dict[str, float] = {}

    if isinstance(inputs, Mapping):
        missing = [nm for nm in in_names if nm not in inputs]
        if missing:
            raise ValidationError(
                message=f"Variáveis de entrada ausentes na avaliação fuzzy: {missing}.",
                parameters={"missing_inputs": missing, "expected_inputs": in_names},
            )
        extra = [k for k in inputs.keys() if k not in in_names]
        if extra:
            raise ValidationError(
                message=f"Variáveis de entrada desconhecidas: {extra}.",
                parameters={"unknown_inputs": extra, "expected_inputs": in_names},
            )
        for nm in in_names:
            val = inputs[nm]
            if isinstance(val, bool) or not isinstance(val, (int, float, np.integer, np.floating)):
                raise ValidationError(f"Entrada {nm!r} deve ser escalar numérico, recebido {val!r}.")
            fval = float(val)
            if not np.isfinite(fval):
                raise ValidationError(f"Entrada {nm!r} não é finita: {val!r}.")
            raw_map[nm] = fval
    elif isinstance(inputs, (int, float, np.integer, np.floating)) and not isinstance(inputs, bool):
        if n_in != 1:
            raise DimensionMismatchError(
                message=f"Sistema requer {n_in} entradas ({in_names}), mas recebeu escalar único.",
                parameters={"expected_inputs": n_in, "actual_inputs": 1},
            )
        fval = float(inputs)
        if not np.isfinite(fval):
            raise ValidationError(f"Entrada escalar não finita: {inputs!r}.")
        raw_map[in_names[0]] = fval
    else:
        arr = ensure_finite_float64(inputs, ndim=1, name="inputs")
        if arr.size != n_in:
            raise DimensionMismatchError(
                message=f"Dimensão de entrada ({arr.size}) difere do número de variáveis de entrada ({n_in}: {in_names}).",
                parameters={"expected_inputs": n_in, "actual_inputs": int(arr.size)},
            )
        for idx, nm in enumerate(in_names):
            raw_map[nm] = float(arr[idx])

    eval_map: dict[str, float] = {}
    saturated_vars: list[str] = []
    for var in input_vars:
        nm = var["name"]
        lo, hi = float(var["universe"][0]), float(var["universe"][1])
        val = raw_map[nm]
        if val < lo or val > hi:
            saturated_vars.append(nm)
            if saturate:
                val = float(np.clip(val, lo, hi))
        eval_map[nm] = val

    return raw_map, eval_map, saturated_vars


def _evaluate_input_memberships(
    eval_inputs: Mapping[str, float],
    input_vars: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    memberships: dict[str, dict[str, float]] = {}
    for var in input_vars:
        vname = var["name"]
        x_val = eval_inputs[vname]
        v_dict: dict[str, float] = {}
        for term in var["terms"]:
            tname = term["name"]
            mf_type, params, complement = extract_term_spec(term)
            mu = float(evaluate_mf(mf_type, params, x_val, complement=complement))
            v_dict[tname] = float(np.clip(mu, 0.0, 1.0))
        memberships[vname] = v_dict
    return memberships


def _compute_rule_activations(
    rules: Sequence[Mapping[str, Any]],
    memberships: Mapping[str, Mapping[str, float]],
    operators: Mapping[str, str],
) -> list[float]:
    default_and = operators.get("and", "min")
    default_or = operators.get("or", "max")
    activations: list[float] = []

    for rule in rules:
        ants = rule["antecedents"]
        connector = str(rule.get("connector", "and")).strip().lower()
        and_method = str(rule.get("and_method", default_and))
        or_method = str(rule.get("or_method", default_or))
        weight = float(rule.get("weight", 1.0))

        degrees: list[float] = []
        for vname, tname in ants.items():
            deg = float(memberships[vname][tname])
            degrees.append(deg)

        if not degrees:
            firing = 0.0
        else:
            firing = degrees[0]
            for deg in degrees[1:]:
                if connector == "or":
                    firing = float(apply_s_norm(firing, deg, or_method))
                else:
                    firing = float(apply_t_norm(firing, deg, and_method))

        activations.append(float(np.clip(firing * weight, 0.0, 1.0)))

    return activations


def _evaluate_ts_consequent(
    term: Mapping[str, Any],
    input_vector: np.ndarray,
) -> float:
    mf_type, params, _ = extract_term_spec(term)
    bias_last = bool(term.get("bias_last", True))
    if mf_type in ("constant", "singleton"):
        return float(params[0])
    if mf_type == "linear":
        return float(linear(input_vector, params, bias_last=bias_last))
    # Se o termo de saída em um sistema TS foi definido com formato triangular/gaussiano, usa seu centro
    if mf_type == "triangular":
        return float(params[1])
    if mf_type == "trapezoidal":
        return float(0.5 * (params[1] + params[2]))
    if mf_type == "gaussian":
        return float(params[0])
    if mf_type == "bell":
        return float(params[2])
    raise ValidationError(f"Tipo de consequente TS não suportado: {mf_type!r}.")


def evaluate(
    system: FuzzySystem | Mapping[str, Any],
    inputs: Mapping[str, Any] | Sequence[Any] | np.ndarray | float | int,
    *,
    grid_resolution: int = 201,
    saturate_inputs: bool = True,
    coupled_mamdani: bool = False,
) -> Result:
    """Avalia um `FuzzySystem` (Mamdani ou Takagi-Sugeno) retornando `Result` canônico auditável.

    Garante:
    - Verificação explícita da soma de ativações `sum_w = sum_i w_i(z)`.
    - Em Takagi-Sugeno, calcula pesos normalizados `h_i(z) = w_i(z) / sum_j w_j(z)` verificando
      `h_i >= 0` e `sum_i h_i == 1` (propriedade de soma convexa).
    - Tratamento seguro de ativação nula (`sum_w == 0`) com `status='warning'` e código `ZERO_RULE_ACTIVATION`,
      aplicando o `default_value` da variável de saída (ou `0.0`) sem jamais produzir `NaN`/`Inf`.
    """
    try:
        fs = _coerce_fuzzy_system(system)
        if isinstance(grid_resolution, bool) or not isinstance(grid_resolution, int) or grid_resolution < 11:
            raise ValidationError("grid_resolution deve ser inteiro >= 11.")

        in_vars = fs.input_variables
        out_vars = fs.output_variables
        rules = fs.rules
        ops = fs.operators

        raw_inputs, eval_inputs, saturated_vars = _parse_inputs(
            inputs, in_vars, saturate=saturate_inputs
        )
        in_names = [v["name"] for v in in_vars]
        # No modelo TS afim y = p^T x + p0, os consequentes lineares operam sobre o vetor de entrada x
        input_vec = np.array(
            [eval_inputs[nm] if saturate_inputs else raw_inputs[nm] for nm in in_names],
            dtype=np.float64,
        )

        memberships = _evaluate_input_memberships(eval_inputs, in_vars)
        rule_activations = _compute_rule_activations(rules, memberships, ops)
        w_arr = np.asarray(rule_activations, dtype=np.float64)
        sum_w = float(np.sum(w_arr))
        active_rules = int(np.sum(w_arr > _EPS))

        warnings_list: list[WarningItem] = []
        if saturated_vars:
            warnings_list.append(
                WarningItem(
                    code="INPUT_SATURATED_TO_UNIVERSE" if saturate_inputs else "INPUT_OUTSIDE_UNIVERSE",
                    message=(
                        f"Entradas fora do universo de discurso detectadas em {saturated_vars}."
                    ),
                    details={"variables": saturated_vars, "raw_inputs": raw_inputs, "evaluated_inputs": eval_inputs},
                )
            )

        if len(rules) == 0:
            warnings_list.append(
                WarningItem(
                    code="EMPTY_RULE_BASE",
                    message="Base de regras vazia: saída neutra padrão aplicada.",
                    details={"n_rules": 0},
                )
            )

        zero_activation = (len(rules) == 0) or (sum_w <= _EPS)
        if sum_w > _EPS:
            h_arr = w_arr / sum_w
            convex_sum_ok = bool(
                np.all(h_arr >= -1e-12) and np.isclose(float(np.sum(h_arr)), 1.0, atol=1e-9, rtol=1e-9)
            )
        else:
            h_arr = np.zeros_like(w_arr, dtype=np.float64)
            convex_sum_ok = False
            if len(rules) > 0:
                warnings_list.append(
                    WarningItem(
                        code="ZERO_RULE_ACTIVATION",
                        message="Nenhuma regra foi ativada (soma de disparos sum(w_i) = 0); saída neutra aplicada.",
                        details={"inputs": eval_inputs, "sum_w": 0.0},
                    )
                )

        outputs_map: dict[str, float] = {}
        out_details: dict[str, Any] = {}

        if fs.inference_type == "ts":
            defuzz_method = normalize_defuzz_method(ops.get("defuzzification", "wtaver"), inference_type="ts")
            rule_consequents_per_out: dict[str, list[float]] = {v["name"]: [] for v in out_vars}

            for v in out_vars:
                vname = v["name"]
                term_lookup = {t["name"]: t for t in v["terms"]}
                default_val = float(v.get("default_value", 0.0))

                if zero_activation:
                    outputs_map[vname] = default_val
                    out_details[vname] = {
                        "rule_outputs": [],
                        "default_applied": True,
                    }
                    continue

                y_rules: list[float] = []
                w_used: list[float] = []
                for r_idx, rule in enumerate(rules):
                    cons = rule["consequents"]
                    if vname not in cons:
                        continue
                    tname = cons[vname]
                    y_r = _evaluate_ts_consequent(term_lookup[tname], input_vec)
                    y_rules.append(y_r)
                    w_used.append(float(w_arr[r_idx]))

                rule_consequents_per_out[vname] = y_rules
                w_u_arr = np.asarray(w_used, dtype=np.float64)
                y_u_arr = np.asarray(y_rules, dtype=np.float64)
                denom = float(np.sum(w_u_arr))

                if denom <= _EPS:
                    outputs_map[vname] = default_val
                    out_details[vname] = {
                        "rule_outputs": y_rules,
                        "default_applied": True,
                    }
                elif defuzz_method == "wtsum":
                    outputs_map[vname] = float(np.dot(w_u_arr, y_u_arr))
                    out_details[vname] = {
                        "rule_outputs": y_rules,
                        "default_applied": False,
                    }
                else:
                    h_u = w_u_arr / denom
                    outputs_map[vname] = float(np.dot(h_u, y_u_arr))
                    out_details[vname] = {
                        "rule_outputs": y_rules,
                        "normalized_weights": [float(v) for v in h_u.tolist()],
                        "default_applied": False,
                    }

        else:
            # Inferência Mamdani
            imp_method = ops.get("implication", "min")
            agg_method = ops.get("aggregation", ops.get("or", "max"))
            defuzz_method = normalize_defuzz_method(ops.get("defuzzification", "centroid"), inference_type="mamdani")
            and_method = ops.get("and", "min")

            if coupled_mamdani and len(out_vars) == 2:
                # Modo acoplado 2D compatível com o legado FuzzySets.cs / legacy_fuzzy_lab
                v1, v2 = out_vars[0], out_vars[1]
                n1, n2 = v1["name"], v2["name"]
                g1 = np.linspace(float(v1["universe"][0]), float(v1["universe"][1]), grid_resolution, dtype=np.float64)
                g2 = np.linspace(float(v2["universe"][0]), float(v2["universe"][1]), grid_resolution, dtype=np.float64)
                t1_map = {
                    t["name"]: np.asarray(evaluate_mf(*extract_term_spec(t)[:2], g1, complement=extract_term_spec(t)[2]), dtype=np.float64)
                    for t in v1["terms"]
                }
                t2_map = {
                    t["name"]: np.asarray(evaluate_mf(*extract_term_spec(t)[:2], g2, complement=extract_term_spec(t)[2]), dtype=np.float64)
                    for t in v2["terms"]
                }
                agg_2d: np.ndarray = np.zeros((grid_resolution, grid_resolution), dtype=np.float64)
                for r_idx, rule in enumerate(rules):
                    cons = rule["consequents"]
                    if n1 not in cons or n2 not in cons:
                        continue
                    mu1 = t1_map[cons[n1]][:, None]
                    mu2 = t2_map[cons[n2]][None, :]
                    conj_cons = apply_t_norm(mu1, mu2, and_method)
                    imp_val = apply_t_norm(w_arr[r_idx], conj_cons, imp_method)
                    agg_2d = imp_val if r_idx == 0 else apply_s_norm(agg_2d, imp_val, agg_method)

                mass_2d = float(np.sum(agg_2d))
                if mass_2d <= _EPS or zero_activation:
                    outputs_map[n1] = float(v1.get("default_value", 0.0))
                    outputs_map[n2] = float(v2.get("default_value", 0.0))
                    zero_activation = True
                else:
                    W1, W2 = np.meshgrid(g1, g2, indexing="ij")
                    if defuzz_method == "centroid":
                        outputs_map[n1] = float(np.sum(agg_2d * W1) / mass_2d)
                        outputs_map[n2] = float(np.sum(agg_2d * W2) / mass_2d)
                    else:
                        max_mu = float(np.max(agg_2d))
                        idx_i, idx_j = np.where(np.abs(agg_2d - max_mu) <= 1e-12)
                        if defuzz_method == "som":
                            outputs_map[n1] = float(g1[int(np.min(idx_i))])
                            outputs_map[n2] = float(g2[int(np.min(idx_j))])
                        elif defuzz_method == "lom":
                            outputs_map[n1] = float(g1[int(np.max(idx_i))])
                            outputs_map[n2] = float(g2[int(np.max(idx_j))])
                        else:
                            outputs_map[n1] = float(np.mean(g1[idx_i]))
                            outputs_map[n2] = float(np.mean(g2[idx_j]))
                out_details[n1] = {"mass": mass_2d, "coupled_2d": True}
                out_details[n2] = {"mass": mass_2d, "coupled_2d": True}
            else:
                for v in out_vars:
                    vname = v["name"]
                    lo, hi = float(v["universe"][0]), float(v["universe"][1])
                    default_val = float(v.get("default_value", 0.0))
                    v_defuzz = normalize_defuzz_method(
                        v.get("defuzzifier", ops.get("defuzzification", defuzz_method)),
                        inference_type="mamdani",
                    )
                    v_agg = str(v.get("accumulation", agg_method))

                    grid = np.linspace(lo, hi, grid_resolution, dtype=np.float64)
                    term_curves: dict[str, np.ndarray] = {}
                    for t in v["terms"]:
                        mf_type, params, complement = extract_term_spec(t)
                        if mf_type == "singleton":
                            # Coloca o pico singleton exatamente no nó mais próximo da grade
                            s_pos = float(params[0])
                            curve = np.zeros_like(grid, dtype=np.float64)
                            nearest_idx = int(np.argmin(np.abs(grid - s_pos)))
                            curve[nearest_idx] = 1.0
                            if complement:
                                curve = 1.0 - curve
                            term_curves[t["name"]] = curve
                        else:
                            term_curves[t["name"]] = np.asarray(
                                evaluate_mf(mf_type, params, grid, complement=complement),
                                dtype=np.float64,
                            )

                    agg_curve = np.zeros_like(grid, dtype=np.float64)
                    first_rule = True
                    for r_idx, rule in enumerate(rules):
                        cons = rule["consequents"]
                        if vname not in cons:
                            continue
                        tname = cons[vname]
                        cons_curve = term_curves[tname]
                        implied = np.asarray(apply_t_norm(w_arr[r_idx], cons_curve, imp_method), dtype=np.float64)
                        if first_rule:
                            agg_curve = implied
                            first_rule = False
                        else:
                            agg_curve = np.asarray(apply_s_norm(agg_curve, implied, v_agg), dtype=np.float64)

                    val, area_mass, is_zero = defuzzify_curve(
                        grid,
                        agg_curve,
                        v_defuzz,
                        default_value=default_val,
                    )
                    if is_zero and not zero_activation:
                        zero_activation = True
                        warnings_list.append(
                            WarningItem(
                                code="ZERO_RULE_ACTIVATION",
                                message=f"Massa agregada nula na saída {vname!r}; saída neutra aplicada.",
                                details={"output": vname, "default_value": default_val},
                            )
                        )
                    outputs_map[vname] = float(val)
                    out_details[vname] = {
                        "mass": float(area_mass),
                        "max_membership": float(np.max(agg_curve)) if agg_curve.size > 0 else 0.0,
                        "defuzzifier": v_defuzz,
                        "default_applied": bool(is_zero),
                    }

        out_names = [v["name"] for v in out_vars]
        out_vec = [outputs_map[nm] for nm in out_names]
        status = "warning" if warnings_list else "success"

        return Result(
            status=status,
            data={
                "outputs": outputs_map,
                "output_vector": out_vec,
                "output": out_vec[0] if len(out_vec) == 1 else out_vec,
                "inputs": raw_inputs,
                "evaluated_inputs": eval_inputs,
                "memberships": memberships,
                "rule_activations": [float(v) for v in w_arr.tolist()],
                "normalized_weights": [float(v) for v in h_arr.tolist()],
                "output_details": out_details,
            },
            assumptions={
                "inference_type": fs.inference_type,
                "is_dynamic_model": fs.is_dynamic_model,
                "partition_of_unity_satisfied": convex_sum_ok,
                "saturate_inputs": saturate_inputs,
            },
            diagnostics={
                "sum_rule_activations": sum_w,
                "active_rules_count": active_rules,
                "total_rules_count": len(rules),
                "zero_activation": zero_activation,
                "convex_sum_residual": abs(float(np.sum(h_arr)) - 1.0) if not zero_activation else 1.0,
                "grid_resolution": grid_resolution if fs.inference_type == "mamdani" else None,
            },
            provenance=build_provenance(
                f"control_lab.fuzzy.evaluate.{fs.inference_type}",
                model_revision=fs.revision,
                tolerances={"eps": _EPS},
            ),
            warnings=tuple(warnings_list),
            error=None,
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.evaluate"),
            warnings=(),
            error=exc.to_typed_error(),
        )


def evaluate_surface(
    system: FuzzySystem | Mapping[str, Any],
    *,
    input_axes: Sequence[str] | None = None,
    fixed_inputs: Mapping[str, float] | None = None,
    output_name: str | None = None,
    n_points: int = 25,
    grid_resolution: int = 101,
) -> Result:
    """Avalia curva (1D) ou superfície de controle (2D) sobre grade de entradas."""
    try:
        fs = _coerce_fuzzy_system(system)
        if isinstance(n_points, bool) or not isinstance(n_points, int) or n_points < 2 or n_points > 250:
            raise ValidationError("n_points deve ser inteiro entre 2 e 250.")

        in_vars = {v["name"]: v for v in fs.input_variables}
        all_in_names = [v["name"] for v in fs.input_variables]
        if input_axes is None:
            axes = all_in_names[: min(2, len(all_in_names))]
        else:
            axes = list(input_axes)
        if len(axes) not in (1, 2):
            raise ValidationError("evaluate_surface suporta 1 ou 2 eixos de entrada.")
        if len(set(axes)) != len(axes):
            raise ValidationError("Eixos de entrada em evaluate_surface devem ser distintos.")
        for ax in axes:
            if ax not in in_vars:
                raise ValidationError(f"Eixo de entrada desconhecido em evaluate_surface: {ax!r}")

        out_names = [v["name"] for v in fs.output_variables]
        if output_name is None:
            selected_output = out_names[0]
        else:
            if not isinstance(output_name, str) or output_name not in out_names:
                raise ValidationError(
                    message=f"Variável de saída desconhecida em evaluate_surface: {output_name!r}.",
                    parameters={"output_name": output_name, "available_outputs": out_names},
                )
            selected_output = output_name

        base_in: dict[str, float] = {}
        for nm, v in in_vars.items():
            if fixed_inputs and nm in fixed_inputs:
                base_in[nm] = float(fixed_inputs[nm])
            else:
                base_in[nm] = 0.5 * (float(v["universe"][0]) + float(v["universe"][1]))

        zero_count = 0

        if len(axes) == 1:
            ax0 = axes[0]
            u0 = in_vars[ax0]["universe"]
            x0_grid = np.linspace(float(u0[0]), float(u0[1]), n_points, dtype=np.float64)
            surfaces: dict[str, list[float]] = {onm: [] for onm in out_names}
            for x0 in x0_grid:
                pt = dict(base_in)
                pt[ax0] = float(x0)
                res = evaluate(fs, pt, grid_resolution=grid_resolution)
                if res.status == "failure" or res.data is None:
                    return res
                if res.diagnostics.get("zero_activation"):
                    zero_count += 1
                for onm in out_names:
                    surfaces[onm].append(float(res.data["outputs"][onm]))

            return Result(
                status="warning" if zero_count > 0 else "success",
                data={
                    "axes": axes,
                    "grids": {ax0: [float(v) for v in x0_grid.tolist()]},
                    "surfaces": surfaces,
                    "outputs": surfaces,
                    "output_name": selected_output,
                    "Z": surfaces[selected_output],
                },
                assumptions={"inference_type": fs.inference_type},
                diagnostics={"n_points": n_points, "zero_activation_points": zero_count},
                provenance=build_provenance("control_lab.fuzzy.evaluate_surface", model_revision=fs.revision),
                warnings=(
                    (
                        WarningItem(
                            code="SURFACE_ZERO_ACTIVATION_POINTS",
                            message=f"{zero_count} ponto(s) da malha não tiveram ativação de regras.",
                            details={"zero_activation_points": zero_count},
                        ),
                    )
                    if zero_count > 0
                    else ()
                ),
            )

        ax0, ax1 = axes[0], axes[1]
        u0 = in_vars[ax0]["universe"]
        u1 = in_vars[ax1]["universe"]
        x0_grid = np.linspace(float(u0[0]), float(u0[1]), n_points, dtype=np.float64)
        x1_grid = np.linspace(float(u1[0]), float(u1[1]), n_points, dtype=np.float64)
        surfaces_2d: dict[str, list[list[float]]] = {onm: [] for onm in out_names}

        for x0 in x0_grid:
            row_per_out: dict[str, list[float]] = {onm: [] for onm in out_names}
            for x1 in x1_grid:
                pt = dict(base_in)
                pt[ax0] = float(x0)
                pt[ax1] = float(x1)
                res = evaluate(fs, pt, grid_resolution=grid_resolution)
                if res.status == "failure" or res.data is None:
                    return res
                if res.diagnostics.get("zero_activation"):
                    zero_count += 1
                for onm in out_names:
                    row_per_out[onm].append(float(res.data["outputs"][onm]))
            for onm in out_names:
                surfaces_2d[onm].append(row_per_out[onm])

        return Result(
            status="warning" if zero_count > 0 else "success",
            data={
                "axes": axes,
                "grids": {
                    ax0: [float(v) for v in x0_grid.tolist()],
                    ax1: [float(v) for v in x1_grid.tolist()],
                },
                "surfaces": surfaces_2d,
                "outputs": surfaces_2d,
                "output_name": selected_output,
                "Z": surfaces_2d[selected_output],
            },
            assumptions={"inference_type": fs.inference_type},
            diagnostics={"n_points": n_points, "total_evaluations": n_points * n_points, "zero_activation_points": zero_count},
            provenance=build_provenance("control_lab.fuzzy.evaluate_surface", model_revision=fs.revision),
            warnings=(
                (
                    WarningItem(
                        code="SURFACE_ZERO_ACTIVATION_POINTS",
                        message=f"{zero_count} ponto(s) da superfície não tiveram ativação de regras.",
                        details={"zero_activation_points": zero_count},
                    ),
                )
                if zero_count > 0
                else ()
            ),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.evaluate_surface"),
            warnings=(),
            error=exc.to_typed_error(),
        )


def check_rule_coverage(
    system: FuzzySystem | Mapping[str, Any],
    *,
    n_grid: int = 21,
) -> Result:
    """Verifica cobertura dos universos de entrada, regras conflitantes e ativação nula."""
    try:
        fs = _coerce_fuzzy_system(system)
        if isinstance(n_grid, bool) or not isinstance(n_grid, int) or n_grid < 3 or n_grid > 101:
            raise ValidationError("n_grid deve ser inteiro entre 3 e 101.")

        in_vars = fs.input_variables
        rules = fs.rules
        warnings_list: list[WarningItem] = []

        # 1. Detecta regras com mesmos antecedentes e consequentes diferentes (conflito)
        seen_ant: dict[tuple[tuple[str, str], ...], dict[str, str]] = {}
        conflicts: list[dict[str, Any]] = []
        for idx, r in enumerate(rules):
            ant_key = tuple(sorted((str(k), str(v)) for k, v in r["antecedents"].items()))
            cons_map = {str(k): str(v) for k, v in r["consequents"].items()}
            if ant_key in seen_ant and seen_ant[ant_key] != cons_map:
                conflicts.append({"rule_index": idx, "antecedents": dict(ant_key), "consequents": cons_map})
            else:
                seen_ant[ant_key] = cons_map

        if conflicts:
            warnings_list.append(
                WarningItem(
                    code="CONFLICTING_RULES",
                    message=f"Detectadas {len(conflicts)} regra(s) com mesmos antecedentes e consequentes distintos.",
                    details={"conflicts": conflicts},
                )
            )

        # 2. Amostra grade nos universos de entrada para checar cobertura (sum(w_i) > 0)
        grids = [
            np.linspace(float(v["universe"][0]), float(v["universe"][1]), n_grid, dtype=np.float64)
            for v in in_vars
        ]
        # Limita produto cartesiano se houver muitas variáveis
        effective_n = n_grid if len(in_vars) <= 3 else max(3, int(round(1000 ** (1.0 / len(in_vars)))))
        if effective_n != n_grid:
            grids = [
                np.linspace(float(v["universe"][0]), float(v["universe"][1]), effective_n, dtype=np.float64)
                for v in in_vars
            ]

        mesh = np.meshgrid(*grids, indexing="ij")
        pts = np.stack([m.ravel() for m in mesh], axis=-1)
        uncovered = 0
        min_sum_w = float("inf")

        for row in pts:
            eval_in = {in_vars[i]["name"]: float(row[i]) for i in range(len(in_vars))}
            mems = _evaluate_input_memberships(eval_in, in_vars)
            acts = _compute_rule_activations(rules, mems, fs.operators)
            sw = float(np.sum(acts))
            min_sum_w = min(min_sum_w, sw)
            if sw <= _EPS:
                uncovered += 1

        if pts.shape[0] == 0:
            min_sum_w = 0.0
        coverage_ratio = float((pts.shape[0] - uncovered) / max(1, pts.shape[0]))
        if uncovered > 0:
            warnings_list.append(
                WarningItem(
                    code="INCOMPLETE_UNIVERSE_COVERAGE",
                    message=f"{uncovered} de {pts.shape[0]} pontos amostrados possuem ativação nula.",
                    details={"uncovered_points": uncovered, "total_points": int(pts.shape[0]), "coverage_ratio": coverage_ratio},
                )
            )

        return Result(
            status="warning" if warnings_list else "success",
            data={
                "is_fully_covered": uncovered == 0 and len(rules) > 0,
                "coverage_ratio": coverage_ratio,
                "conflicts": conflicts,
            },
            assumptions={"n_grid_per_axis": effective_n},
            diagnostics={
                "total_sampled_points": int(pts.shape[0]),
                "uncovered_points": uncovered,
                "min_sum_activation": float(min_sum_w if np.isfinite(min_sum_w) else 0.0),
                "conflict_count": len(conflicts),
            },
            provenance=build_provenance("control_lab.fuzzy.check_rule_coverage", model_revision=fs.revision),
            warnings=tuple(warnings_list),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.check_rule_coverage"),
            warnings=(),
            error=exc.to_typed_error(),
        )
