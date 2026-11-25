"""Testes unitários normativos da Frente F5 — Não-Linearidade de Setor & Motor Simbólico qLPV.

Cobre integralmente `T-TSMOD-01`, `T-TSMOD-02` e `T-TSMOD-03` de `CL-TS-MOD-DIR-001 v1.0.0`.
"""

from __future__ import annotations

import ast
import json
import math
import pathlib
import time

import jsonschema
import numpy as np
import pytest
from referencing import Registry, Resource

from control_lab.core.models import TSStateSpace
from control_lab.diagnostics import ValidationError
from control_lab.fuzzy import (
    analyze_sector_premises,
    cos1m_div_u,
    derive_ts_sector,
    evaluate_scalar,
    evaluate_ts_premise_weights,
    evaluate_vectorized,
    extract_active_variables,
    find_global_extrema,
    is_single_use_expression,
    parse_expression,
    sinc_rad,
    verify_matrix_multilinearity,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "contracts" / "schemas"


def _build_ts_schema_validator() -> jsonschema.Draft202012Validator:
    ts_schema = json.loads((SCHEMAS_DIR / "ts_state_space.schema.json").read_text(encoding="utf-8"))
    tensor_schema = json.loads((SCHEMAS_DIR / "tensor.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources(
        [
            (ts_schema["$id"], Resource.from_contents(ts_schema)),
            (tensor_schema["$id"], Resource.from_contents(tensor_schema)),
            ("tensor.schema.json", Resource.from_contents(tensor_schema)),
        ]
    )
    return jsonschema.Draft202012Validator(ts_schema, registry=registry)


# ---------------------------------------------------------------------------
# T-TSMOD-01: Segurança AST (R-21), Zero eval/exec/linalg.inv, sinc_rad
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malicious_expr",
    [
        "__import__('os').system('echo pwn')",
        "eval('1+1')",
        "exec('x=1')",
        "open('/etc/passwd')",
        "x1.__class__",
        "x1.real",
        "x1[0]",
        "lambda x: x",
        "1 + 2; 3",
        "getattr(x1, 'real')",
        "os.path",
        "_private + 1",
        "unknown_fn(x1)",
        "sin(x1, x2)",
    ],
)
def test_t_tsmod_01_ast_security_blocks_malicious_inputs(malicious_expr: str) -> None:
    with pytest.raises(ValidationError):
        parse_expression(malicious_expr)


def test_t_tsmod_01_no_forbidden_calls_in_f5_modules() -> None:
    """Garante por inspeção AST estática zero eval, exec, compile, getattr dinâmico ou linalg.inv."""
    forbidden_funcs = {"eval", "exec", "compile", "getattr"}
    for fname in ("symbolic_qlpv.py", "sector_nonlinearity.py"):
        fpath = REPO_ROOT / "control_lab" / "fuzzy" / fname
        tree = ast.parse(fpath.read_text(encoding="utf-8"), filename=str(fpath))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in forbidden_funcs:
                    pytest.fail(f"Chamada proibida '{node.func.id}' encontrada em {fname}:{node.lineno}")
                if isinstance(node.func, ast.Attribute) and node.func.attr == "inv":
                    pytest.fail(f"Chamada proibida '.inv()' encontrada em {fname}:{node.lineno}")


def test_t_tsmod_01_sinc_rad_and_cos1m_div_u_smooth_continuity() -> None:
    # Em x = 0 e |x| = 1e-8 (erro < 1e-15)
    assert abs(float(sinc_rad(0.0)) - 1.0) < 1e-15
    assert abs(float(sinc_rad(1e-8)) - (1.0 - (1e-16 / 6.0))) < 1e-15
    assert abs(float(sinc_rad(-1e-8)) - (1.0 - (1e-16 / 6.0))) < 1e-15
    # Continuidade na fronteira |u| = 1e-4
    left = float(sinc_rad(1e-4 - 1e-12))
    right = float(sinc_rad(1e-4 + 1e-12))
    assert abs(left - right) < 1e-14

    # cos1m_div_u na origem e fora
    assert abs(float(cos1m_div_u(0.0)) - 0.0) < 1e-15
    assert abs(float(cos1m_div_u(1e-8)) - 0.5e-8) < 1e-15
    assert abs(float(cos1m_div_u(0.7)) - (1.0 - math.cos(0.7)) / 0.7) < 1e-15

    # Vetorizado
    pts = np.array([-1.0, -1e-8, 0.0, 1e-8, 1e-4, 1.0], dtype=np.float64)
    vals = evaluate_vectorized("sinc_rad(x1)", {"x1": pts})
    assert np.all(np.isfinite(vals))
    assert abs(float(vals[2]) - 1.0) < 1e-15


def test_t_tsmod_01_removable_singularity_auto_rewrite() -> None:
    parsed = parse_expression("sin(x3) / x3")
    assert len(parsed.rewrites) == 1
    assert parsed.rewrites[0].code == "REMOVABLE_SINGULARITY_REWRITTEN"
    assert parsed.to_string() == "sinc_rad(x3)"
    # Avalia suavemente em x3 = 0 sem NaN/ZeroDivision
    assert abs(evaluate_scalar(parsed, {"x3": 0.0}) - 1.0) < 1e-15
    assert abs(evaluate_scalar(parsed, {"x3": 0.5}) - math.sin(0.5) / 0.5) < 1e-15

    # Também reescreve (1 - cos(x3)) / x3
    parsed2 = parse_expression("(1 - cos(x3)) / x3")
    assert len(parsed2.rewrites) == 1
    assert abs(evaluate_scalar(parsed2, {"x3": 0.0}) - 0.0) < 1e-15


def test_t_tsmod_01_active_variables_sue_and_precedence() -> None:
    assert extract_active_variables("2 * pi + cos(x3) - e * x1") == ("x3", "x1")
    assert is_single_use_expression("1 / (1 + 0.2 * sin(x3)^2)") is True
    assert is_single_use_expression("x3 * cos(x3)") is False
    # Precedência de potência e unário: -x^2 = -(x^2), x^-2 = 1/x^2
    assert abs(evaluate_scalar("-x1^2", {"x1": 3.0}) - (-9.0)) < 1e-15
    assert abs(evaluate_scalar("x1**-2", {"x1": 2.0}) - 0.25) < 1e-15


# ---------------------------------------------------------------------------
# T-TSMOD-02: Extremos Globais Híbridos em 3 Estágios
# ---------------------------------------------------------------------------


def test_t_tsmod_02_exact_interval_sue_extrema() -> None:
    res_cos = find_global_extrema("cos(x3)", {"x3": [-0.6, 0.6]})
    assert res_cos["is_sue"] is True
    assert res_cos["method"] == "exact_interval_sue_plus_polish"
    assert abs(res_cos["min"] - math.cos(0.6)) <= 1e-14
    assert abs(res_cos["max"] - 1.0) <= 1e-14

    res_sinc = find_global_extrema("sinc_rad(x3)", {"x3": [-0.6, 0.6]})
    assert abs(res_sinc["min"] - math.sin(0.6) / 0.6) <= 1e-14
    assert abs(res_sinc["max"] - 1.0) <= 1e-14


def test_t_tsmod_02_multimodal_interior_extrema_1d_and_2d() -> None:
    # Função multimodal 1D: f(x) = sin(5*x) + 0.15*(x - 0.37)^2 em [-2.0, 2.0]
    # Possui múltiplos mínimos locais; o mínimo global está no interior (não em um nó de grade simples)
    expr_1d = "sin(5 * x1) + 0.15 * (x1 - 0.37)^2"
    res_1d = find_global_extrema(expr_1d, {"x1": [-2.0, 2.0]})

    # Verificação independente por condição de estacionariedade f'(x*) = 0:
    # Em float64 sem derivada analítica, |x - x*| ~ sqrt(eps) ~ 1.5e-8 => |f'(x)| < 1e-6 e |f(x) - f(x*)| <= 1e-13.
    x_min = res_1d["argmin_point"]["x1"]
    grad_at_min = 5.0 * math.cos(5.0 * x_min) + 0.3 * (x_min - 0.37)
    assert abs(grad_at_min) < 1e-6
    # Refina localmente a raiz de f'(x)=0 por Newton para conferir erro de valor <= 1e-13
    x_ref = x_min
    for _ in range(10):
        fp = 5.0 * math.cos(5.0 * x_ref) + 0.3 * (x_ref - 0.37)
        fpp = -25.0 * math.sin(5.0 * x_ref) + 0.3
        x_ref -= fp / fpp
    f_ref = math.sin(5.0 * x_ref) + 0.15 * (x_ref - 0.37) ** 2
    assert abs(res_1d["min"] - f_ref) <= 1e-13

    # Função multimodal 2D com ótimo interior não trivial:
    # g(x1, x2) = -(cos(2*x1 - 0.3) * cos(2*x2 + 0.4)) + 0.05*(x1^2 + x2^2)
    expr_2d = "-(cos(2*x1 - 0.3) * cos(2*x2 + 0.4)) + 0.05*(x1^2 + x2^2)"
    res_2d = find_global_extrema(expr_2d, {"x1": [-1.5, 1.5], "x2": [-1.5, 1.5]})
    xm1, xm2 = res_2d["argmin_point"]["x1"], res_2d["argmin_point"]["x2"]
    g1 = 2.0 * math.sin(2.0 * xm1 - 0.3) * math.cos(2.0 * xm2 + 0.4) + 0.1 * xm1
    g2 = 2.0 * math.cos(2.0 * xm1 - 0.3) * math.sin(2.0 * xm2 + 0.4) + 0.1 * xm2
    assert math.hypot(g1, g2) < 1e-6


def test_t_tsmod_02_high_dim_4d_fast_and_accurate() -> None:
    expr_4d = "sin(x1) + cos(x2) + 0.5*x3^2 - tanh(x4) + 0.1*x1*x4"
    bounds_4d = {"x1": [-1.0, 1.0], "x2": [-1.0, 1.0], "x3": [-1.0, 1.0], "x4": [-1.0, 1.0]}
    t0 = time.perf_counter()
    res = find_global_extrema(expr_4d, bounds_4d)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0  # Rápido e determinístico
    # No vértice ótimo: x1=1, x2=0, x3=1, x4=-1 => sin(1)+1+0.5+tanh(1)-0.1
    # ou x1=1, x2=0, x3=1, x4=-1 vs x4=-1: f(1,0,1,-1) = sin(1)+1+0.5+tanh(1)-0.1
    cand_max = math.sin(1.0) + 1.0 + 0.5 + math.tanh(1.0) - 0.1
    assert res["max"] >= cand_max - 1e-12


def test_t_tsmod_02_constant_premise_and_manual_override() -> None:
    res_const = find_global_extrema("sin(x1)^2 + cos(x1)^2", {"x1": [-1.0, 1.0]})
    assert res_const["is_constant"] is True
    assert any(w["code"] == "DEGENERATE_CONSTANT_PREMISE" for w in res_const["warnings"])

    # Override mais largo (válido)
    res_wide = find_global_extrema("cos(x3)", {"x3": [-0.6, 0.6]}, user_override=[0.82, 1.01])
    assert res_wide["override_applied"] is True
    assert res_wide["override_violates_positivity"] is False
    assert res_wide["min"] == 0.82
    assert res_wide["max"] == 1.01

    # Override mais estreito (alerta de violação de positividade)
    res_narrow = find_global_extrema("cos(x3)", {"x3": [-0.6, 0.6]}, user_override=[0.90, 0.99])
    assert res_narrow["override_violates_positivity"] is True
    assert any(w["code"] == "SECTOR_BOUNDS_OVERRIDE_NARROWER" for w in res_narrow["warnings"])


# ---------------------------------------------------------------------------
# T-TSMOD-03: Exatidão de Setor (Pêndulo Invertido 4 estados / 4 premissas / 16 regras)
# ---------------------------------------------------------------------------


def _inverted_pendulum_4state_spec() -> dict:
    """Pêndulo invertido sobre carro: 4 estados, 4 premissas setoriais => 16 regras exatas."""
    # Parâmetros físicos: M=1.0, m=0.2, l=0.5, g=9.81
    # d = 1.0 + 0.2*sin(x3)^2
    # z1 = 1/d, z2 = cos(x3), z3 = sinc_rad(x3), z4 = x4 * sin(x3)
    premises = [
        {"name": "z1", "expression": "1 / (1.0 + 0.2 * sin(x3)^2)"},
        {"name": "z2", "expression": "cos(x3)"},
        {"name": "z3", "expression": "sin(x3) / x3"},  # testa reescrita automática para sinc_rad(x3)
        {"name": "z4", "expression": "x4 * sin(x3)"},
    ]
    state_bounds = {
        "x1": [-2.0, 2.0],
        "x2": [-3.0, 3.0],
        "x3": [-0.6, 0.6],
        "x4": [-2.0, 2.0],
    }
    A_expr = [
        ["0", "1", "0", "0"],
        ["0", "0", "-1.962 * z1 * z2 * z3", "0.1 * z1 * z4"],
        ["0", "0", "0", "1"],
        ["0", "0", "23.544 * z1 * z3", "-0.2 * z1 * z2 * z4"],
    ]
    B_expr = [
        ["0"],
        ["z1"],
        ["0"],
        ["-2.0 * z1 * z2"],
    ]
    C_expr = [
        ["1", "0", "0", "0"],
        ["0", "0", "1", "0"],
    ]
    D_expr = [
        ["0"],
        ["0"],
    ]
    return {
        "premises": premises,
        "state_bounds": state_bounds,
        "A_expr": A_expr,
        "B_expr": B_expr,
        "C_expr": C_expr,
        "D_expr": D_expr,
    }


def test_t_tsmod_03_inverted_pendulum_4state_16rules_exact_and_schema_valid() -> None:
    spec = _inverted_pendulum_4state_spec()
    res = derive_ts_sector(
        premises=spec["premises"],
        state_bounds=spec["state_bounds"],
        A_expr=spec["A_expr"],
        B_expr=spec["B_expr"],
        C_expr=spec["C_expr"],
        D_expr=spec["D_expr"],
        input_names=["F"],
        output_names=["pos", "theta"],
    )
    # Status pode ser 'warning' devido ao rewrite informativo sin(x3)/x3 -> sinc_rad(x3)
    assert res.status in ("success", "warning")
    assert res.data is not None
    assert res.data["num_premises"] == 4
    assert res.data["num_rules"] == 16
    assert res.data["kind"] == "ts_measured"

    cert = res.data["fidelity_certificate"]
    assert cert["verification_badge"] == "EXACT_ANALYTICAL_SECTOR"
    assert cert["verified"] is True
    assert cert["max_abs_error"] <= 1e-13
    assert cert["rel_l2_error"] <= 1e-13
    assert cert["min_weight"] >= -1e-15
    assert cert["max_sum_deviation"] <= 1e-14

    ts_dict = res.data["ts_state_space"]
    # Validação estrita contra contracts/schemas/ts_state_space.schema.json
    validator = _build_ts_schema_validator()
    validator.validate(ts_dict)

    # Round-trip canônico
    ts_obj = TSStateSpace.from_dict(ts_dict)
    assert ts_obj.n_vertices == 16
    assert ts_obj.n_states == 4
    assert ts_obj.n_inputs == 1
    assert ts_obj.n_outputs == 2
    assert ts_obj.membership_spec["representation_kind"] == "sector_nonlinearity"
    assert len(ts_obj.membership_spec["functions"]) == 16
    assert ts_obj.membership_spec["functions"][0]["bits"] == [0, 0, 0, 0]
    assert ts_obj.membership_spec["functions"][-1]["bits"] == [1, 1, 1, 1]
    assert "ts_derivation" in ts_obj.provenance

    # Avaliação via evaluate_ts_premise_weights (usando estados x1..x4 e também z1..z4)
    test_state = {"x1": 0.4, "x2": -0.5, "x3": 0.35, "x4": -1.2}
    w_res_x = evaluate_ts_premise_weights(ts_obj, test_state)
    assert w_res_x.status == "success"
    h_x = np.asarray(w_res_x.data["weights"], dtype=np.float64)
    assert np.min(h_x) >= -1e-15
    assert abs(float(np.sum(h_x)) - 1.0) <= 1e-14

    # Passando z1..z4 diretamente deve produzir exatamente os mesmos pesos
    z_vals = w_res_x.data["premise_values"]
    w_res_z = evaluate_ts_premise_weights(ts_obj, z_vals)
    assert w_res_z.status == "success"
    h_z = np.asarray(w_res_z.data["weights"], dtype=np.float64)
    assert np.allclose(h_x, h_z, atol=1e-15)

    # Passando z1..z4 como vetor ndarray diretamente
    z_vec = np.array([z_vals["z1"], z_vals["z2"], z_vals["z3"], z_vals["z4"]])
    w_res_zvec = evaluate_ts_premise_weights(ts_obj, z_vec)
    assert w_res_zvec.status == "success"
    assert np.allclose(np.asarray(w_res_zvec.data["weights"]), h_x, atol=1e-15)

    # Valores z fora do setor devem falhar por violação de não-negatividade
    w_res_oob = evaluate_ts_premise_weights(ts_obj, np.array([0.4, -0.5, 0.35, -1.2]))
    assert w_res_oob.status == "failure"
    assert w_res_oob.error is not None
    assert w_res_oob.error.code == "HYPOTHESIS_VIOLATED"

    # Reconstrução matricial exata no ponto test_state
    A_rec = sum(h_x[r] * ts_obj.vertices[r]["A"] for r in range(16))
    B_rec = sum(h_x[r] * ts_obj.vertices[r]["B"] for r in range(16))
    d_val = 1.0 + 0.2 * math.sin(0.35) ** 2
    A_true = np.array(
        [
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, -1.962 * math.cos(0.35) * (math.sin(0.35) / 0.35) / d_val, 0.1 * (-1.2) * math.sin(0.35) / d_val],
            [0.0, 0.0, 0.0, 1.0],
            [0.0, 0.0, 23.544 * (math.sin(0.35) / 0.35) / d_val, -0.2 * math.cos(0.35) * (-1.2) * math.sin(0.35) / d_val],
        ]
    )
    B_true = np.array([[0.0], [1.0 / d_val], [0.0], [-2.0 * math.cos(0.35) / d_val]])
    assert np.linalg.norm(A_rec - A_true, ord="fro") <= 1e-13
    assert np.linalg.norm(B_rec - B_true, ord="fro") <= 1e-13


def test_t_tsmod_03_detects_non_affine_matrix_and_isolation_violation() -> None:
    # Caso 1: Violação de afinidade (z1^2 em A[1, 0])
    res_non_aff = derive_ts_sector(
        premises=[{"name": "z1", "expression": "x1"}],
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[["0", "1"], ["z1^2", "-1"]],
        B_expr=[["0"], ["1"]],
    )
    assert res_non_aff.status == "failure"
    assert res_non_aff.error is not None
    assert res_non_aff.error.code == "HYPOTHESIS_VIOLATED"
    entries = res_non_aff.error.parameters["non_affine_entries"]
    assert len(entries) == 1
    assert entries[0]["matrix_name"] == "A"
    assert entries[0]["row"] == 1
    assert entries[0]["col"] == 0
    assert entries[0]["premise"] == "z1"

    # Caso 2: Violação de isolamento (uso direto de x2 em A[0, 1])
    res_iso = derive_ts_sector(
        premises=[{"name": "z1", "expression": "cos(x1)"}],
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[["0", "x2"], ["z1", "-1"]],
        B_expr=[["0"], ["1"]],
    )
    assert res_iso.status == "failure"
    assert res_iso.error is not None
    assert res_iso.error.code == "HYPOTHESIS_VIOLATED"
    viols = res_iso.error.parameters["isolation_violations"]
    assert viols[0]["matrix_name"] == "A"
    assert viols[0]["row"] == 0
    assert viols[0]["col"] == 1
    assert "x2" in viols[0]["illegal_variables"]

    # Verifica também verify_matrix_multilinearity diretamente para 1/z1
    chk = verify_matrix_multilinearity(
        {"A": [["1 / z1", "0"], ["0", "-1"]]},
        premise_names=["z1"],
        premise_bounds={"z1": [0.5, 2.0]},
    )
    assert chk["is_valid"] is False
    assert chk["non_affine_entries"][0]["matrix_name"] == "A"
    assert chk["non_affine_entries"][0]["row"] == 0
    assert chk["non_affine_entries"][0]["col"] == 0


def test_t_tsmod_03_external_signals_partially_observed_and_generalized_channels() -> None:
    # Sistema 2 estados + 1 sinal externo theta1; x2 não medido => z2 não medida => ts_partially_observed
    res = derive_ts_sector(
        premises=[
            {"name": "z1", "expression": "theta1 * cos(x1)"},
            {"name": "z2", "expression": "x2^2"},
        ],
        state_bounds={"x1": [-0.5, 0.5], "x2": [-1.0, 1.0]},
        external_bounds={"theta1": [0.8, 1.2]},
        measured_states={"x1": True, "x2": False},
        measured_externals={"theta1": True},
        A_expr=[["0", "1"], ["-2 * z1", "-1 - 0.5 * z2"]],
        B_expr=[["0"], ["z1"]],
        C_expr=[["1", "0"]],
        D_expr=[["0"]],
        generalized_channels={
            "Bw": [["0"], ["0.5 * z1"]],
            "Cz": [["1", "0"], ["0", "0.2"]],
            "Dzu": [["0"], ["0.1"]],
            "Dzw": [["0"], ["0"]],
        },
        dt=0.01,
    )
    assert res.status == "success"
    assert res.data["kind"] == "ts_partially_observed"
    ts_dict = res.data["ts_state_space"]
    _build_ts_schema_validator().validate(ts_dict)

    assert ts_dict["premise_availability"] == {
        "mode": "partially_observed",
        "measured_premises": ["z1"],
        "unmeasured_premises": ["z2"],
        "estimator_required_for_pdc": True,
    }
    assert "generalized_channels" in ts_dict["provenance"]
    assert len(ts_dict["provenance"]["generalized_channels"]["vertices"]) == 4

    # Avaliação via evaluate_ts_premise_weights passando estados + sinal externo
    w_res = evaluate_ts_premise_weights(ts_dict, {"x1": 0.2, "x2": -0.5, "theta1": 1.1})
    assert w_res.status == "success"
    assert abs(sum(w_res.data["weights"]) - 1.0) <= 1e-14


def test_t_tsmod_03_premise_count_limits() -> None:
    # nn = 7 => warning HIGH_RULE_COUNT_SECTOR em analyze_sector_premises
    bounds_7 = {f"x{i}": [-1.0, 1.0] for i in range(1, 8)}
    prems_7 = [{"name": f"z{i}", "expression": f"x{i}"} for i in range(1, 8)]
    res_7 = analyze_sector_premises(prems_7, bounds_7)
    assert res_7.status == "warning"
    assert res_7.data["num_rules"] == 128
    assert any(w.code == "HIGH_RULE_COUNT_SECTOR" for w in res_7.warnings)

    # nn = 9 => erro (> 8)
    bounds_9 = {f"x{i}": [-1.0, 1.0] for i in range(1, 10)}
    prems_9 = [{"name": f"z{i}", "expression": f"x{i}"} for i in range(1, 10)]
    res_9 = analyze_sector_premises(prems_9, bounds_9)
    assert res_9.status == "failure"
    assert res_9.error is not None
    assert res_9.error.code == "VALIDATION_ERROR"
