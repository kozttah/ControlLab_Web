"""Derivação exata de modelos Takagi–Sugeno via Não-Linearidade de Setor (CL-TS-MOD-DIR-001 Seção 3 & 5).

Implementa:
- `analyze_sector_premises(...)`: análise das premissas z_k = g_k(x, w_ext) com pipeline híbrido de 3 estágios;
- `derive_ts_sector(...)`: validação de isolamento/multilinearidade, expansão exata dos 2^nn vértices em ordem
  lexicográfica binária determinística, construção canônica de `TSStateSpace` e auditoria independente fora da
  grade (`ModelFidelityCertificate`).
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import qmc

from control_lab.core.models import TSStateSpace
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .symbolic_qlpv import (
    ParsedExpression,
    evaluate_scalar,
    evaluate_vectorized,
    find_global_extrema,
    parse_expression,
    verify_matrix_multilinearity,
)

MAX_SECTOR_PREMISES_WARN = 6
MAX_SECTOR_PREMISES_HARD = 8
ALLOWED_GENERALIZED_CHANNELS: frozenset[str] = frozenset({"Bw", "Dyw", "Cz", "Dzu", "Dzw"})


def _normalize_bounds_map(
    raw_bounds: Mapping[str, Sequence[float]] | None,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> dict[str, list[float]]:
    if raw_bounds is None:
        if allow_empty:
            return {}
        raise ValidationError(f"{field_name} não pode ser nulo.")
    if not isinstance(raw_bounds, Mapping):
        raise ValidationError(f"{field_name} deve ser um mapeamento nome -> [min, max].")
    if not allow_empty and len(raw_bounds) == 0:
        raise ValidationError(f"{field_name} não pode ser vazio.")
    clean: dict[str, list[float]] = {}
    for var_name, pair in raw_bounds.items():
        if not isinstance(var_name, str) or not var_name.strip():
            raise ValidationError(f"Nome de variável inválido em {field_name}: {var_name!r}.")
        if not isinstance(pair, Sequence) or isinstance(pair, (str, bytes)) or len(pair) != 2:
            raise ValidationError(f"Limite inválido em {field_name}[{var_name!r}]: esperado [min, max].")
        lo, hi = float(pair[0]), float(pair[1])
        if not (math.isfinite(lo) and math.isfinite(hi)) or lo > hi:
            raise ValidationError(f"Intervalo inválido em {field_name}[{var_name!r}]: [{lo}, {hi}].")
        clean[var_name.strip()] = [lo, hi]
    return clean


def _resolve_measured_flags(
    var_names: Sequence[str],
    measured_spec: Mapping[str, bool] | Sequence[str] | None,
) -> dict[str, bool]:
    if measured_spec is None:
        return {v: True for v in var_names}
    if isinstance(measured_spec, Mapping):
        return {v: bool(measured_spec.get(v, True)) for v in var_names}
    if isinstance(measured_spec, Sequence) and not isinstance(measured_spec, (str, bytes)):
        mset = set(str(x) for x in measured_spec)
        return {v: (v in mset) for v in var_names}
    raise ValidationError("Especificação de variáveis medidas deve ser Mapping[str, bool] ou lista de nomes.")


def _parse_symbolic_matrix(
    raw_mat: Sequence[Sequence[str | float | int | ParsedExpression]],
    *,
    name: str,
) -> list[list[ParsedExpression]]:
    if not isinstance(raw_mat, Sequence) or isinstance(raw_mat, (str, bytes)) or len(raw_mat) == 0:
        raise ValidationError(f"Matriz simbólica {name!r} deve ser uma lista 2D não vazia.")
    parsed_rows: list[list[ParsedExpression]] = []
    n_cols: int | None = None
    for i, row in enumerate(raw_mat):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) == 0:
            raise ValidationError(f"Linha {i} de {name!r} deve ser sequência não vazia.")
        if n_cols is None:
            n_cols = len(row)
        elif len(row) != n_cols:
            raise DimensionMismatchError(
                f"Linhas de {name!r} têm comprimentos inconsistentes ({n_cols} vs {len(row)})."
            )
        parsed_rows.append([parse_expression(cell) for cell in row])
    return parsed_rows


def _eval_symbolic_matrix_scalar(
    parsed_mat: list[list[ParsedExpression]],
    env: Mapping[str, float],
) -> np.ndarray:
    n_r = len(parsed_mat)
    n_c = len(parsed_mat[0])
    out = np.empty((n_r, n_c), dtype=np.float64)
    for i in range(n_r):
        for j in range(n_c):
            out[i, j] = evaluate_scalar(parsed_mat[i][j], env)
    return out


def _eval_symbolic_matrix_batch(
    parsed_mat: list[list[ParsedExpression]],
    env_vec: Mapping[str, np.ndarray],
    n_pts: int,
) -> np.ndarray:
    """Retorna array (n_pts, n_r, n_c) com avaliação vetorizada da matriz simbólica."""
    n_r = len(parsed_mat)
    n_c = len(parsed_mat[0])
    out = np.empty((n_pts, n_r, n_c), dtype=np.float64)
    for i in range(n_r):
        for j in range(n_c):
            vals = evaluate_vectorized(parsed_mat[i][j], env_vec)
            out[:, i, j] = np.broadcast_to(vals, (n_pts,))
    return out


def _analyze_premises_internal(
    premises: Sequence[Mapping[str, Any]],
    state_bounds: Mapping[str, Sequence[float]],
    *,
    external_bounds: Mapping[str, Sequence[float]] | None = None,
    measured_states: Mapping[str, bool] | Sequence[str] | None = None,
    measured_externals: Mapping[str, bool] | Sequence[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(premises, Sequence) or isinstance(premises, (str, bytes)) or len(premises) < 1:
        raise ValidationError("Pelo menos uma variável premissa z_k deve ser fornecida.")

    nn = len(premises)
    if nn > MAX_SECTOR_PREMISES_HARD:
        raise ValidationError(
            message=(
                f"Número de premissas setoriais nn={nn} excede o teto máximo permitido ({MAX_SECTOR_PREMISES_HARD}, "
                f"2^{MAX_SECTOR_PREMISES_HARD}=256 regras)."
            ),
            parameters={"nn": nn, "max_nn": MAX_SECTOR_PREMISES_HARD},
            next_step="Reduza o número de premissas ou utilize a Via 2 (TPMT) para redução de regras.",
        )

    clean_state_bounds = _normalize_bounds_map(state_bounds, field_name="state_bounds", allow_empty=False)
    clean_ext_bounds = _normalize_bounds_map(external_bounds, field_name="external_bounds", allow_empty=True)

    overlap_vars = set(clean_state_bounds.keys()) & set(clean_ext_bounds.keys())
    if overlap_vars:
        raise ValidationError(
            f"Conflito de nomes entre state_bounds e external_bounds: {sorted(overlap_vars)}."
        )

    all_domain_bounds: dict[str, list[float]] = {**clean_state_bounds, **clean_ext_bounds}
    state_meas = _resolve_measured_flags(list(clean_state_bounds.keys()), measured_states)
    ext_meas = _resolve_measured_flags(list(clean_ext_bounds.keys()), measured_externals)
    var_measured = {**state_meas, **ext_meas}

    warnings_items: list[WarningItem] = []
    if nn > MAX_SECTOR_PREMISES_WARN:
        warnings_items.append(
            WarningItem(
                code="HIGH_RULE_COUNT_SECTOR",
                message=(
                    f"nn={nn} premissas geram 2^{nn}={2**nn} regras; síntese LMI PDC com muitas regras pode ser "
                    "custosa no navegador. Considere usar a Via 2 (TPMT) para redução de regras."
                ),
                details={"nn": nn, "num_rules": 2**nn},
            )
        )

    analyzed: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    parsed_premises: list[ParsedExpression] = []

    for idx, p_item in enumerate(premises):
        if not isinstance(p_item, Mapping):
            raise ValidationError(f"premises[{idx}] deve ser um mapeamento com 'name' e 'expression'.")
        p_name = str(p_item.get("name", "")).strip()
        if not p_name:
            raise ValidationError(f"premises[{idx}].name deve ser uma string não vazia.")
        if p_name in seen_names:
            raise ValidationError(f"Nome de premissa duplicado: {p_name!r}.")
        if p_name in all_domain_bounds:
            raise ValidationError(
                f"Nome de premissa {p_name!r} colide com variável de estado/sinal externo já declarada."
            )
        seen_names.add(p_name)

        if "expression" not in p_item:
            raise ValidationError(f"premises[{idx}] ({p_name!r}) requer o campo 'expression'.")
        parsed = parse_expression(p_item["expression"])
        parsed_premises.append(parsed)

        unknown_vars = [v for v in parsed.active_variables if v not in all_domain_bounds]
        if unknown_vars:
            raise ValidationError(
                message=(
                    f"Premissa {p_name!r} referencia variáveis sem limites declarados em "
                    f"state_bounds/external_bounds: {unknown_vars}."
                ),
                parameters={"premise": p_name, "unknown_variables": unknown_vars},
            )

        user_override = p_item.get("user_bounds")
        ext_res = find_global_extrema(parsed, all_domain_bounds, user_override=user_override)
        warnings_items.extend(ext_res.pop("_warning_items", ()))

        inferred_measured = all(var_measured[v] for v in parsed.active_variables)
        if "measured" in p_item and p_item["measured"] is not None:
            is_measured = bool(p_item["measured"])
        else:
            is_measured = inferred_measured

        analyzed.append(
            {
                "name": p_name,
                "expression": parsed.source,
                "rewritten_expression": ext_res["rewritten_expression"],
                "active_variables": ext_res["active_variables"],
                "is_sue": ext_res["is_sue"],
                "min": ext_res["min"],
                "max": ext_res["max"],
                "computed_min": ext_res["computed_min"],
                "computed_max": ext_res["computed_max"],
                "argmin_point": ext_res["argmin_point"],
                "argmax_point": ext_res["argmax_point"],
                "method": ext_res["method"],
                "is_constant": ext_res["is_constant"],
                "override_applied": ext_res["override_applied"],
                "override_violates_positivity": ext_res["override_violates_positivity"],
                "measured": is_measured,
                "warnings": ext_res["warnings"],
            }
        )

    measured_premises = [p["name"] for p in analyzed if p["measured"]]
    unmeasured_premises = [p["name"] for p in analyzed if not p["measured"]]

    if unmeasured_premises:
        inferred_kind = "ts_partially_observed"
        premise_availability = {
            "mode": "partially_observed",
            "measured_premises": measured_premises,
            "unmeasured_premises": unmeasured_premises,
            "estimator_required_for_pdc": True,
        }
    else:
        inferred_kind = "ts_measured"
        premise_availability = {
            "mode": "all_measured",
            "measured_premises": measured_premises,
            "unmeasured_premises": [],
            "estimator_required_for_pdc": False,
        }

    return {
        "premises": analyzed,
        "parsed_premises": parsed_premises,
        "num_premises": nn,
        "num_rules": 2**nn,
        "inferred_kind": inferred_kind,
        "premise_availability": premise_availability,
        "state_bounds": clean_state_bounds,
        "external_bounds": clean_ext_bounds,
        "all_domain_bounds": all_domain_bounds,
        "warning_items": tuple(warnings_items),
    }


def analyze_sector_premises(
    premises: Sequence[Mapping[str, Any]],
    state_bounds: Mapping[str, Sequence[float]],
    *,
    external_bounds: Mapping[str, Sequence[float]] | None = None,
    measured_states: Mapping[str, bool] | Sequence[str] | None = None,
    measured_externals: Mapping[str, bool] | Sequence[str] | None = None,
) -> Result:
    """Analisa premissas setoriais z_k = g_k(x, w_ext) e certifica seus extremos globais em Omega."""
    try:
        info = _analyze_premises_internal(
            premises=premises,
            state_bounds=state_bounds,
            external_bounds=external_bounds,
            measured_states=measured_states,
            measured_externals=measured_externals,
        )
        warnings_tuple = info["warning_items"]
        status = "warning" if warnings_tuple else "success"
        return Result(
            status=status,
            data={
                "premises": info["premises"],
                "num_premises": info["num_premises"],
                "num_rules": info["num_rules"],
                "inferred_kind": info["inferred_kind"],
                "premise_availability": info["premise_availability"],
                "state_bounds": info["state_bounds"],
                "external_bounds": info["external_bounds"],
            },
            assumptions={
                "compact_domain": True,
                "deterministic_3stage_extrema": True,
            },
            diagnostics={
                "num_premises": info["num_premises"],
                "num_rules": info["num_rules"],
                "n_constant_premises": sum(1 for p in info["premises"] if p["is_constant"]),
                "inferred_kind": info["inferred_kind"],
            },
            provenance=build_provenance("control_lab.fuzzy.analyze_sector_premises"),
            warnings=warnings_tuple,
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.analyze_sector_premises"),
            warnings=(),
            error=exc.to_typed_error(),
        )


def _format_rule_expression(
    analyzed_premises: Sequence[Mapping[str, Any]],
    bits: Sequence[int],
) -> str:
    """Constrói expressão analítica normalizada `h_r(z) = prod_k w_{k, b_{r,k}}(z_k)`."""
    factors: list[str] = []
    for p, bit in zip(analyzed_premises, bits):
        name = p["name"]
        z_min = float(p["min"])
        z_max = float(p["max"])
        span = z_max - z_min
        if bit == 0:
            factors.append(f"(({name} - {z_min!r})/({span!r}))")
        else:
            factors.append(f"(({z_max!r} - {name})/({span!r}))")
    return " * ".join(factors)


def _run_offgrid_fidelity_audit(
    *,
    analyzed_premises: Sequence[Mapping[str, Any]],
    parsed_premises: Sequence[ParsedExpression],
    all_domain_bounds: Mapping[str, list[float]],
    parsed_A: list[list[ParsedExpression]],
    parsed_B: list[list[ParsedExpression]],
    parsed_C: list[list[ParsedExpression]],
    parsed_D: list[list[ParsedExpression]],
    vertices_S: np.ndarray,
    rule_bits: list[list[int]],
    n_val_points: int = 2048,
) -> dict[str, Any]:
    """Executa auditoria independente fora da grade (`ModelFidelityCertificate`)."""
    # União ordenada das variáveis ativas nas premissas
    active_union: list[str] = []
    seen: set[str] = set()
    for pe in parsed_premises:
        for v in pe.active_variables:
            if v not in seen:
                seen.add(v)
                active_union.append(v)

    d_act = len(active_union)
    lo_act = np.array([all_domain_bounds[v][0] for v in active_union], dtype=np.float64)
    hi_act = np.array([all_domain_bounds[v][1] for v in active_union], dtype=np.float64)

    blocks: list[np.ndarray] = []
    if d_act <= 8:
        verts = np.array(list(itertools.product(*zip(lo_act.tolist(), hi_act.tolist()))), dtype=np.float64)
        blocks.append(verts)

    n_verts_added = blocks[0].shape[0] if blocks else 0
    n_sobol = max(64, n_val_points - n_verts_added)
    m_pow = max(6, int(math.ceil(math.log2(n_sobol))))
    sampler = qmc.Sobol(d=d_act, scramble=True, seed=20261124)
    unit_pts = sampler.random_base2(m=m_pow)[:n_sobol]
    blocks.append(lo_act + unit_pts * (hi_act - lo_act))

    sample_pts = np.vstack(blocks)
    n_pts = int(sample_pts.shape[0])
    dom_env = {active_union[i]: sample_pts[:, i] for i in range(d_act)}

    # Avalia z_k(xi) para k = 1..nn
    nn = len(analyzed_premises)
    z_env: dict[str, np.ndarray] = {}
    w0_list: list[np.ndarray] = []
    w1_list: list[np.ndarray] = []

    for k in range(nn):
        p = analyzed_premises[k]
        z_vals = evaluate_vectorized(parsed_premises[k], dom_env)
        z_vals = np.broadcast_to(z_vals, (n_pts,))
        z_env[p["name"]] = z_vals
        z_min = float(p["min"])
        z_max = float(p["max"])
        span = z_max - z_min
        w0 = (z_vals - z_min) / span
        w1 = (z_max - z_vals) / span
        w0_list.append(w0)
        w1_list.append(w1)

    # Calcula pesos h_r(z(xi)) com shape (n_pts, n_rules)
    n_rules = len(rule_bits)
    H = np.ones((n_pts, n_rules), dtype=np.float64)
    for r_idx, bits in enumerate(rule_bits):
        for k, b in enumerate(bits):
            H[:, r_idx] *= w0_list[k] if b == 0 else w1_list[k]

    min_weight = float(np.min(H))
    max_sum_deviation = float(np.max(np.abs(np.sum(H, axis=1) - 1.0)))

    # Avalia matriz empacotada original S(z(xi)) = [A B; C D]
    A_batch = _eval_symbolic_matrix_batch(parsed_A, z_env, n_pts)
    B_batch = _eval_symbolic_matrix_batch(parsed_B, z_env, n_pts)
    C_batch = _eval_symbolic_matrix_batch(parsed_C, z_env, n_pts)
    D_batch = _eval_symbolic_matrix_batch(parsed_D, z_env, n_pts)

    top = np.concatenate([A_batch, B_batch], axis=2)
    bot = np.concatenate([C_batch, D_batch], axis=2)
    S_true = np.concatenate([top, bot], axis=1)  # (n_pts, n+p, n+m)

    # Reconstrução convexa S_hat = sum_r h_r S_r
    S_hat = np.tensordot(H, vertices_S, axes=([1], [0]))  # (n_pts, n+p, n+m)

    diff = S_true - S_hat
    err_frob = np.linalg.norm(diff.reshape(n_pts, -1), axis=1)
    true_frob = np.linalg.norm(S_true.reshape(n_pts, -1), axis=1)

    max_abs_error = float(np.max(err_frob))
    rms_err = float(np.sqrt(np.sum(err_frob**2)))
    rms_true = float(np.sqrt(np.sum(true_frob**2)))
    rel_l2_error = float(rms_err / (rms_true + 1e-15))

    exact_ok = (rel_l2_error <= 1e-12) and (min_weight >= -1e-12) and (max_sum_deviation <= 1e-12)
    verification_badge = "EXACT_ANALYTICAL_SECTOR" if exact_ok else "NUMERIC_WARNING"

    return {
        "n_validation_points": n_pts,
        "max_abs_error": max_abs_error,
        "rel_l2_error": rel_l2_error,
        "min_weight": min_weight,
        "max_sum_deviation": max_sum_deviation,
        "verification_badge": verification_badge,
        "verified": exact_ok,
    }


def derive_ts_sector(
    premises: Sequence[Mapping[str, Any]],
    state_bounds: Mapping[str, Sequence[float]],
    A_expr: Sequence[Sequence[str | float | int]],
    B_expr: Sequence[Sequence[str | float | int]],
    *,
    C_expr: Sequence[Sequence[str | float | int]] | None = None,
    D_expr: Sequence[Sequence[str | float | int]] | None = None,
    external_bounds: Mapping[str, Sequence[float]] | None = None,
    measured_states: Mapping[str, bool] | Sequence[str] | None = None,
    measured_externals: Mapping[str, bool] | Sequence[str] | None = None,
    generalized_channels: Mapping[str, Sequence[Sequence[str | float | int]]] | None = None,
    dt: float | None = None,
    state_names: Sequence[str] | None = None,
    input_names: Sequence[str] | None = None,
    output_names: Sequence[str] | None = None,
    units: Mapping[str, Any] | None = None,
    model_id: str | None = None,
    n_val_points: int = 2048,
) -> Result:
    """Deriva um `TSStateSpace` canônico exato via Não-Linearidade de Setor (2^nn vértices)."""
    try:
        info = _analyze_premises_internal(
            premises=premises,
            state_bounds=state_bounds,
            external_bounds=external_bounds,
            measured_states=measured_states,
            measured_externals=measured_externals,
        )
        analyzed = info["premises"]
        parsed_premises = info["parsed_premises"]
        nn = info["num_premises"]
        warnings_list: list[WarningItem] = list(info["warning_items"])

        # Bloqueia premissas degeneradas constantes (evita divisão por zero em w_{k,0})
        const_premises = [p["name"] for p in analyzed if p["is_constant"]]
        if const_premises:
            raise ValidationError(
                message=(
                    f"Premissas constantes detectadas ({const_premises}): z_max - z_min <= 1e-12. "
                    "Substitua-as por seus valores escalares constantes nas matrizes para evitar divisão por zero "
                    "e economizar metade das regras."
                ),
                parameters={"constant_premises": const_premises},
                next_step="Remova as premissas constantes e substitua seus valores escalares em A(z), B(z), C(z), D(z).",
            )

        # Parse e validação dimensional das matrizes simbólicas A, B, C, D
        parsed_A = _parse_symbolic_matrix(A_expr, name="A")
        n = len(parsed_A)
        if len(parsed_A[0]) != n:
            raise DimensionMismatchError(
                f"Matriz simbólica A deve ser quadrada (n x n), recebido ({n}, {len(parsed_A[0])})."
            )
        parsed_B = _parse_symbolic_matrix(B_expr, name="B")
        if len(parsed_B) != n:
            raise DimensionMismatchError(
                f"Matriz simbólica B deve ter {n} linhas para coincidir com A, recebido {len(parsed_B)}."
            )
        m = len(parsed_B[0])

        if C_expr is None:
            C_raw: list[list[str | float | int]] = [
                [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)
            ]
        else:
            C_raw = [list(r) for r in C_expr]
        parsed_C = _parse_symbolic_matrix(C_raw, name="C")
        p_out = len(parsed_C)
        if len(parsed_C[0]) != n:
            raise DimensionMismatchError(
                f"Matriz simbólica C deve ter {n} colunas para coincidir com A, recebido {len(parsed_C[0])}."
            )

        if D_expr is None:
            D_raw: list[list[str | float | int]] = [[0.0 for _ in range(m)] for _ in range(p_out)]
        else:
            D_raw = [list(r) for r in D_expr]
        parsed_D = _parse_symbolic_matrix(D_raw, name="D")
        if len(parsed_D) != p_out or len(parsed_D[0]) != m:
            raise DimensionMismatchError(
                f"Matriz simbólica D deve ter shape ({p_out}, {m}), recebido ({len(parsed_D)}, {len(parsed_D[0])})."
            )

        # Canais generalizados opcionais (Bw, Dyw, Cz, Dzu, Dzw)
        parsed_gen: dict[str, list[list[ParsedExpression]]] = {}
        if generalized_channels is not None:
            if not isinstance(generalized_channels, Mapping):
                raise ValidationError("generalized_channels deve ser um mapeamento de matrizes simbólicas.")
            unknown_ch = set(generalized_channels.keys()) - ALLOWED_GENERALIZED_CHANNELS
            if unknown_ch:
                raise ValidationError(
                    f"Canais generalizados desconhecidos: {sorted(unknown_ch)}. "
                    f"Permitidos: {sorted(ALLOWED_GENERALIZED_CHANNELS)}."
                )
            nw: int | None = None
            nz: int | None = None
            for ch_name, ch_raw in generalized_channels.items():
                pm = _parse_symbolic_matrix(ch_raw, name=ch_name)
                cr, cc = len(pm), len(pm[0])
                if ch_name == "Bw":
                    if cr != n:
                        raise DimensionMismatchError(f"Bw deve ter {n} linhas, recebido {cr}.")
                    nw = cc if nw is None else nw
                    if cc != nw:
                        raise DimensionMismatchError(f"Dimensão nw inconsistente em Bw ({cc} vs {nw}).")
                elif ch_name == "Dyw":
                    if cr != p_out:
                        raise DimensionMismatchError(f"Dyw deve ter {p_out} linhas, recebido {cr}.")
                    nw = cc if nw is None else nw
                    if cc != nw:
                        raise DimensionMismatchError(f"Dimensão nw inconsistente em Dyw ({cc} vs {nw}).")
                elif ch_name == "Cz":
                    if cc != n:
                        raise DimensionMismatchError(f"Cz deve ter {n} colunas, recebido {cc}.")
                    nz = cr if nz is None else nz
                    if cr != nz:
                        raise DimensionMismatchError(f"Dimensão nz inconsistente em Cz ({cr} vs {nz}).")
                elif ch_name == "Dzu":
                    if cc != m:
                        raise DimensionMismatchError(f"Dzu deve ter {m} colunas, recebido {cc}.")
                    nz = cr if nz is None else nz
                    if cr != nz:
                        raise DimensionMismatchError(f"Dimensão nz inconsistente em Dzu ({cr} vs {nz}).")
                elif ch_name == "Dzw":
                    nz = cr if nz is None else nz
                    nw = cc if nw is None else nw
                    if cr != nz or cc != nw:
                        raise DimensionMismatchError(
                            f"Dzw deve ter shape ({nz}, {nw}), recebido ({cr}, {cc})."
                        )
                parsed_gen[ch_name] = pm

        # Validação estrutural de isolamento e multilinearidade em z
        premise_names = [p["name"] for p in analyzed]
        premise_bounds = {p["name"]: [float(p["min"]), float(p["max"])] for p in analyzed}
        mats_to_verify: dict[str, Any] = {
            "A": parsed_A,
            "B": parsed_B,
            "C": parsed_C,
            "D": parsed_D,
            **parsed_gen,
        }
        aff_check = verify_matrix_multilinearity(
            mats_to_verify,
            premise_names=premise_names,
            premise_bounds=premise_bounds,
        )
        if not aff_check["isolation_ok"]:
            first_v = aff_check["isolation_violations"][0]
            raise HypothesisViolatedError(
                message=(
                    f"Violação de isolamento de variáveis na Via 1 (Setor): "
                    f"{first_v['matrix_name']}[{first_v['row']},{first_v['col']}] referencia "
                    f"{first_v['illegal_variables']} fora das premissas {premise_names}."
                ),
                parameters={"isolation_violations": aff_check["isolation_violations"]},
                next_step="Encapsule todas as variáveis de estado/externas em premissas z_k ou utilize a Via 2 (TPMT).",
            )
        if not aff_check["is_multilinear"]:
            first_na = aff_check["non_affine_entries"][0]
            raise HypothesisViolatedError(
                message=(
                    f"Violação de multilinearidade em z na Via 1 (Setor): entrada "
                    f"{first_na['matrix_name']}[{first_na['row']},{first_na['col']}] = '{first_na['expression']}' "
                    f"não é afim em '{first_na['premise']}' (desvio={first_na['collinearity_deviation']:.3e})."
                ),
                parameters={
                    "non_affine_entries": aff_check["non_affine_entries"],
                    "max_collinearity_deviation": aff_check["max_collinearity_deviation"],
                },
                next_step=(
                    "Reescreva a não-linearidade como uma premissa z_k separada de modo que A(z), B(z), C(z), D(z) "
                    "sejam afins/multilineares em z, ou use a Via 2 (TPMT)."
                ),
            )

        # Expansão exata dos 2^nn vértices em ordem lexicográfica binária determinística
        # b_{r,k} = 0 -> z_{k,max}, b_{r,k} = 1 -> z_{k,min}
        n_rules = 2**nn
        vertices_list: list[dict[str, Any]] = []
        functions_spec: list[dict[str, Any]] = []
        rule_bits: list[list[int]] = []
        vertices_S = np.empty((n_rules, n + p_out, n + m), dtype=np.float64)
        gen_vertices: list[dict[str, Any]] = []

        for r_idx in range(n_rules):
            bits = [(r_idx >> (nn - 1 - k)) & 1 for k in range(nn)]
            rule_bits.append(bits)
            z_vertex = {
                analyzed[k]["name"]: float(analyzed[k]["max"] if bits[k] == 0 else analyzed[k]["min"])
                for k in range(nn)
            }
            A_r = _eval_symbolic_matrix_scalar(parsed_A, z_vertex)
            B_r = _eval_symbolic_matrix_scalar(parsed_B, z_vertex)
            C_r = _eval_symbolic_matrix_scalar(parsed_C, z_vertex)
            D_r = _eval_symbolic_matrix_scalar(parsed_D, z_vertex)

            vid = f"rule_{r_idx + 1}"
            vertices_list.append(
                {
                    "vertex_id": vid,
                    "A": A_r,
                    "B": B_r,
                    "C": C_r,
                    "D": D_r,
                }
            )
            vertices_S[r_idx] = np.block([[A_r, B_r], [C_r, D_r]])

            if parsed_gen:
                gv: dict[str, Any] = {"vertex_id": vid}
                for ch_name, pm in parsed_gen.items():
                    gv[ch_name] = _eval_symbolic_matrix_scalar(pm, z_vertex).tolist()
                gen_vertices.append(gv)

            functions_spec.append(
                {
                    "id": f"h_{r_idx + 1}",
                    "vertex_id": vid,
                    "bits": bits,
                    "expression": _format_rule_expression(analyzed, bits),
                }
            )

        # Auditoria independente fora da grade (ModelFidelityCertificate)
        fidelity_cert = _run_offgrid_fidelity_audit(
            analyzed_premises=analyzed,
            parsed_premises=parsed_premises,
            all_domain_bounds=info["all_domain_bounds"],
            parsed_A=parsed_A,
            parsed_B=parsed_B,
            parsed_C=parsed_C,
            parsed_D=parsed_D,
            vertices_S=vertices_S,
            rule_bits=rule_bits,
            n_val_points=n_val_points,
        )

        # Montagem canônica de membership_spec, domain e provenance
        membership_spec: dict[str, Any] = {
            "version": "1.0.0",
            "representation_kind": "sector_nonlinearity",
            "premise_variables": premise_names,
            "sum_to_one_domain": True,
            "sector_premises": [
                {
                    "name": p["name"],
                    "expression": p["expression"],
                    "active_variables": list(p["active_variables"]),
                    "min": float(p["min"]),
                    "max": float(p["max"]),
                    "measured": bool(p["measured"]),
                }
                for p in analyzed
            ],
            "functions": functions_spec,
        }

        domain_payload: dict[str, Any] = {
            "bounds": {
                **info["state_bounds"],
                **info["external_bounds"],
                **premise_bounds,
            },
            "state_bounds": info["state_bounds"],
            "external_bounds": info["external_bounds"],
            "premise_bounds": premise_bounds,
        }

        resolved_state_names = (
            list(state_names)
            if state_names is not None
            else (list(info["state_bounds"].keys()) if len(info["state_bounds"]) == n else None)
        )

        provenance_payload: dict[str, Any] = {
            "source": "control_lab.fuzzy.derive_ts_sector",
            "ts_derivation": {
                "method": "sector_nonlinearity",
                "num_premises": nn,
                "num_rules": n_rules,
                "premises": [
                    {
                        "name": p["name"],
                        "expression": p["expression"],
                        "min": p["min"],
                        "max": p["max"],
                        "measured": p["measured"],
                    }
                    for p in analyzed
                ],
                "state_bounds": info["state_bounds"],
                "external_bounds": info["external_bounds"],
                "A_expr": [[pe.source for pe in row] for row in parsed_A],
                "B_expr": [[pe.source for pe in row] for row in parsed_B],
                "C_expr": [[pe.source for pe in row] for row in parsed_C],
                "D_expr": [[pe.source for pe in row] for row in parsed_D],
                "multilinearity_check": {
                    "is_multilinear": True,
                    "max_collinearity_deviation": aff_check["max_collinearity_deviation"],
                },
                "fidelity_certificate": fidelity_cert,
            },
        }
        if parsed_gen:
            provenance_payload["generalized_channels"] = {
                "channels": sorted(parsed_gen.keys()),
                "expressions": {
                    ch_name: [[pe.source for pe in row] for row in pm]
                    for ch_name, pm in parsed_gen.items()
                },
                "vertices": gen_vertices,
            }

        ts_ss = TSStateSpace(
            vertices=vertices_list,
            kind=info["inferred_kind"],
            dt=dt,
            membership_spec=membership_spec,
            premise_availability=info["premise_availability"],
            domain=domain_payload,
            id=model_id,
            state_names=resolved_state_names,
            input_names=input_names,
            output_names=output_names,
            units=units,
            provenance=provenance_payload,
        )

        if not fidelity_cert["verified"]:
            warnings_list.append(
                WarningItem(
                    code="FIDELITY_CERTIFICATE_WARNING",
                    message=(
                        "Auditoria fora da grade detectou desvio acima da tolerância exata "
                        f"(rel_l2={fidelity_cert['rel_l2_error']:.3e}, min_h={fidelity_cert['min_weight']:.3e})."
                    ),
                    details=fidelity_cert,
                )
            )

        status = "warning" if warnings_list else "success"
        return Result(
            status=status,
            data={
                "ts_state_space": ts_ss.to_dict(),
                "model_id": ts_ss.id,
                "kind": ts_ss.kind,
                "num_premises": nn,
                "num_rules": n_rules,
                "premises": analyzed,
                "fidelity_certificate": fidelity_cert,
            },
            assumptions={
                "method": "sector_nonlinearity",
                "affine_multilinear_in_z": True,
                "sum_to_one_domain": True,
                "compact_domain": True,
            },
            diagnostics={
                "num_premises": nn,
                "num_rules": n_rules,
                "n_states": ts_ss.n_states,
                "n_inputs": ts_ss.n_inputs,
                "n_outputs": ts_ss.n_outputs,
                "max_collinearity_deviation": aff_check["max_collinearity_deviation"],
                "max_abs_error": fidelity_cert["max_abs_error"],
                "rel_l2_error": fidelity_cert["rel_l2_error"],
                "min_weight": fidelity_cert["min_weight"],
                "max_sum_deviation": fidelity_cert["max_sum_deviation"],
                "verification_badge": fidelity_cert["verification_badge"],
            },
            provenance=build_provenance(
                "control_lab.fuzzy.derive_ts_sector",
                model_revision=ts_ss.revision,
            ),
            warnings=tuple(warnings_list),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={"method": "sector_nonlinearity"},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.derive_ts_sector"),
            warnings=(),
            error=exc.to_typed_error(),
        )
