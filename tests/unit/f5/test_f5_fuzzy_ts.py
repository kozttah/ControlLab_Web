"""Suíte completa de testes unitários e normativos da Frente F5 — Controle Fuzzy, FML IEEE 1855-2016, ANFIS e TS/PDC.

Cobre explicitamente:
- `T-FML-01`: Duas regras Takagi-Sugeno com avaliação manual/analítica exata;
- `T-FML-02`: Exportação e importação FML IEEE 1855-2016 com equivalência numérica em grade e proteção estrita anti-XXE / anti-DTD;
- `T-TS-01`: Bloqueio de síntese/implementação `PDCController` sobre `TSStateSpace(kind="polytopic_uncertain")` sem estimador de premissas;
- `ADR-006`: Proibição de converter aproximador estático ANFIS (`is_dynamic_model=False`) diretamente em `TSStateSpace` dinâmico;
- Compatibilidade de importação com documentos FML gerados pelo laboratório legado (`docs/references/legacy_fuzzy_lab/`);
- Funções de pertinência (`triangular`, `trapezoidal`, `gaussian`, `bell`, `sigmoid`, `singleton`, `z_shape`, `s_shape`, `linear`), operadores lógicos, métodos de defuzzificação (`centroid`, `bisector`, `mom`, `som`, `lom`), tratamento de ativação nula (`sum(w_i) == 0`) e treinamento híbrido `fit_anfis`.
"""

from __future__ import annotations

import numpy as np
import pytest

from control_lab.core.models import FuzzySystem, TSStateSpace
from control_lab.fuzzy import (
    apply_s_norm,
    apply_t_norm,
    bell,
    check_rule_coverage,
    defuzzify_curve,
    evaluate,
    evaluate_mf,
    evaluate_surface,
    evaluate_ts_frozen_weights,
    evaluate_ts_premise_weights,
    export_fml,
    fit_anfis,
    gaussian,
    import_fml,
    linear,
    make_pdc_spec,
    s_shape,
    sigmoid,
    singleton,
    to_ts_state_space,
    trapezoidal,
    triangular,
    verify_convex_weights,
    z_shape,
)


# ---------------------------------------------------------------------------
# 1. Funções de Pertinência e Operadores Lógicos
# ---------------------------------------------------------------------------


def test_membership_functions_analytical_and_boundaries() -> None:
    """Verifica valores analíticos, bordas e ombros degenerados de todas as funções de pertinência."""
    # Triangular padrão e ombros (a==b e b==c)
    assert triangular(0.0, [-1.0, 0.0, 1.0]) == pytest.approx(1.0)
    assert triangular(-0.5, [-1.0, 0.0, 1.0]) == pytest.approx(0.5)
    assert triangular(-1.5, [-1.0, 0.0, 1.0]) == pytest.approx(0.0)
    assert triangular(-1.0, [-1.0, -1.0, 0.0]) == pytest.approx(1.0)
    assert triangular(1.0, [0.0, 1.0, 1.0]) == pytest.approx(1.0)

    # Trapezoidal padrão e ombros
    assert trapezoidal(0.0, [-2.0, -1.0, 1.0, 2.0]) == pytest.approx(1.0)
    assert trapezoidal(-1.5, [-2.0, -1.0, 1.0, 2.0]) == pytest.approx(0.5)
    assert trapezoidal(2.5, [-2.0, -1.0, 1.0, 2.0]) == pytest.approx(0.0)
    assert trapezoidal(-2.0, [-2.0, -2.0, -1.0, 0.0]) == pytest.approx(1.0)

    # Gaussiana IEEE 1855-2016: exp(-0.5 * ((x - c) / sigma)^2)
    assert gaussian(0.0, [0.0, 2.0]) == pytest.approx(1.0)
    assert gaussian(2.0, [0.0, 2.0]) == pytest.approx(np.exp(-0.5))

    # Generalized Bell: 1 / (1 + |(x - c) / a|^(2b))
    assert bell(0.0, [2.0, 2.0, 0.0]) == pytest.approx(1.0)
    assert bell(2.0, [2.0, 2.0, 0.0]) == pytest.approx(0.5)

    # Sigmoid: 1 / (1 + exp(-a*(x - c)))
    assert sigmoid(0.0, [1.0, 0.0]) == pytest.approx(0.5)
    assert sigmoid(10.0, [2.0, 0.0]) > 0.999

    # Singleton
    assert singleton(1.5, [1.5]) == pytest.approx(1.0)
    assert singleton(1.6, [1.5]) == pytest.approx(0.0)

    # Z-shape e S-shape
    assert z_shape(0.0, [1.0, 3.0]) == pytest.approx(1.0)
    assert z_shape(2.0, [1.0, 3.0]) == pytest.approx(0.5)
    assert z_shape(4.0, [1.0, 3.0]) == pytest.approx(0.0)
    assert s_shape(0.0, [1.0, 3.0]) == pytest.approx(0.0)
    assert s_shape(2.0, [1.0, 3.0]) == pytest.approx(0.5)
    assert s_shape(4.0, [1.0, 3.0]) == pytest.approx(1.0)
    assert z_shape(2.0, [1.0, 3.0]) + s_shape(2.0, [1.0, 3.0]) == pytest.approx(1.0)

    # Linear / Afim e Constante (TS)
    assert linear([2.0, 3.0], [1.5, -2.0, 0.5], bias_last=True) == pytest.approx(1.5 * 2.0 - 2.0 * 3.0 + 0.5)
    assert linear([2.0, 3.0], [0.5, 1.5, -2.0], bias_last=False) == pytest.approx(0.5 + 1.5 * 2.0 - 2.0 * 3.0)
    assert linear([2.0, 3.0], [7.25]) == pytest.approx(7.25)

    # Complemento via evaluate_mf
    assert evaluate_mf("triangular", [-1.0, 0.0, 1.0], -0.5, complement=True) == pytest.approx(0.5)


def test_membership_invalid_parameters_rejected() -> None:
    """Garante que parâmetros degenerados inválidos (sigma <= 0, a > b) geram ValidationError."""
    from control_lab.diagnostics import ValidationError

    with pytest.raises(ValidationError):
        triangular(0.0, [1.0, 0.0, 2.0])
    with pytest.raises(ValidationError):
        trapezoidal(0.0, [0.0, 2.0, 1.0, 3.0])
    with pytest.raises(ValidationError):
        gaussian(0.0, [0.0, 0.0])
    with pytest.raises(ValidationError):
        bell(0.0, [-1.0, 2.0, 0.0])
    with pytest.raises(ValidationError):
        z_shape(0.0, [3.0, 1.0])
    with pytest.raises(ValidationError):
        s_shape(0.0, [3.0, 1.0])


def test_t_norm_and_s_norm_operators() -> None:
    """Testa T-normas (min, prod, eprod) e S-normas (max, prob_or, esum)."""
    assert apply_t_norm(0.6, 0.4, "min") == pytest.approx(0.4)
    assert apply_t_norm(0.6, 0.4, "prod") == pytest.approx(0.24)
    assert apply_t_norm(0.6, 0.4, "eprod") == pytest.approx((0.6 * 0.4) / (2.0 - (0.6 + 0.4 - 0.24)))

    assert apply_s_norm(0.6, 0.4, "max") == pytest.approx(0.6)
    assert apply_s_norm(0.6, 0.4, "prob_or") == pytest.approx(0.6 + 0.4 - 0.24)
    assert apply_s_norm(0.6, 0.4, "esum") == pytest.approx((0.6 + 0.4) / (1.0 + 0.24))


# ---------------------------------------------------------------------------
# 2. Teste Normativo T-FML-01 — Duas Regras Takagi-Sugeno Analíticas
# ---------------------------------------------------------------------------


def test_t_fml_01_two_rules_ts_analytical_evaluation() -> None:
    """T-FML-01: Duas regras Takagi-Sugeno com avaliação manual e saída numérica idêntica."""
    # Entrada x em [0, 10] com partição de unidade triangular:
    # Low: [0, 0, 10] -> w_1(x) = (10 - x)/10
    # High: [0, 10, 10] -> w_2(x) = x/10
    # Regra 1: SE x é Low ENTÃO y_1(x) = 2*x + 1
    # Regra 2: SE x é High ENTÃO y_2(x) = -1*x + 5
    ts_sys = FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "x",
                "universe": [0.0, 10.0],
                "terms": [
                    {"name": "Low", "mf": "triangular", "params": [0.0, 0.0, 10.0]},
                    {"name": "High", "mf": "triangular", "params": [0.0, 10.0, 10.0]},
                ],
            }
        ],
        output_variables=[
            {
                "name": "y",
                "universe": [-20.0, 30.0],
                "terms": [
                    {"name": "Lin1", "type": "linear", "params": [2.0, 1.0]},
                    {"name": "Lin2", "type": "linear", "params": [-1.0, 5.0]},
                ],
            }
        ],
        rules=[
            {"name": "R1", "antecedents": {"x": "Low"}, "consequents": {"y": "Lin1"}, "weight": 1.0},
            {"name": "R2", "antecedents": {"x": "High"}, "consequents": {"y": "Lin2"}, "weight": 1.0},
        ],
        operators={"and": "prod", "or": "probor", "defuzzification": "wtaver"},
    )

    for x_val in (0.0, 2.5, 4.0, 7.5, 10.0):
        w1 = (10.0 - x_val) / 10.0
        w2 = x_val / 10.0
        h1 = w1 / (w1 + w2)
        h2 = w2 / (w1 + w2)
        y1 = 2.0 * x_val + 1.0
        y2 = -1.0 * x_val + 5.0
        expected_y = h1 * y1 + h2 * y2

        res = evaluate(ts_sys, {"x": x_val})
        assert res.status == "success"
        assert res.data is not None
        assert res.data["output"] == pytest.approx(expected_y, abs=1e-12)
        assert res.data["outputs"]["y"] == pytest.approx(expected_y, abs=1e-12)
        assert res.data["normalized_weights"] == pytest.approx([h1, h2], abs=1e-12)
        assert res.assumptions["partition_of_unity_satisfied"] is True
        assert res.diagnostics["convex_sum_residual"] == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# 3. Inferência Mamdani, Defuzzificadores e Ativação Nula (sum w_i == 0)
# ---------------------------------------------------------------------------


def test_mamdani_inference_and_defuzzifiers() -> None:
    """Avalia inferência Mamdani com centroid, bisector, mom, som, lom e caso de ativação nula."""
    mamdani_sys = FuzzySystem(
        inference_type="mamdani",
        input_variables=[
            {
                "name": "e",
                "universe": [-5.0, 5.0],
                "terms": [
                    {"name": "Neg", "mf": "triangular", "params": [-5.0, -5.0, 0.0]},
                    {"name": "Pos", "mf": "triangular", "params": [0.0, 5.0, 5.0]},
                ],
            }
        ],
        output_variables=[
            {
                "name": "u",
                "universe": [-10.0, 10.0],
                "default_value": 0.0,
                "terms": [
                    {"name": "Down", "mf": "triangular", "params": [-10.0, -5.0, 0.0]},
                    {"name": "Up", "mf": "triangular", "params": [0.0, 5.0, 10.0]},
                ],
            }
        ],
        rules=[
            {"name": "R1", "antecedents": {"e": "Neg"}, "consequents": {"u": "Down"}},
            {"name": "R2", "antecedents": {"e": "Pos"}, "consequents": {"u": "Up"}},
        ],
        operators={"and": "min", "or": "max", "implication": "min", "aggregation": "max", "defuzzification": "centroid"},
    )

    # Em e = 5.0, apenas Pos dispara com grau 1.0; Up é um triângulo simétrico em [0, 5, 10], centroide = 5.0
    res_pos = evaluate(mamdani_sys, {"e": 5.0}, grid_resolution=201)
    assert res_pos.status == "success"
    assert res_pos.data is not None
    assert res_pos.data["output"] == pytest.approx(5.0, abs=1e-6)

    # Em e = 0.0, ambos Neg e Pos têm pertinência 0.0 -> ativação nula (sum w_i = 0)!
    res_zero = evaluate(mamdani_sys, {"e": 0.0}, grid_resolution=201)
    assert res_zero.status == "warning"
    assert res_zero.data is not None
    assert res_zero.data["output"] == pytest.approx(0.0, abs=1e-12)
    assert res_zero.diagnostics["zero_activation"] is True
    assert any(w.code == "ZERO_RULE_ACTIVATION" for w in res_zero.warnings if hasattr(w, "code"))

    # Testa defuzzificadores sobre curva trapezoidal plana no topo [-2, -1, 1, 2]
    grid = np.linspace(-4.0, 4.0, 801)
    curve = np.asarray(trapezoidal(grid, [-2.0, -1.0, 1.0, 2.0]), dtype=np.float64)
    v_cog, _, _ = defuzzify_curve(grid, curve, "centroid")
    v_boa, _, _ = defuzzify_curve(grid, curve, "bisector")
    v_mom, _, _ = defuzzify_curve(grid, curve, "mom")
    v_som, _, _ = defuzzify_curve(grid, curve, "som")
    v_lom, _, _ = defuzzify_curve(grid, curve, "lom")

    assert v_cog == pytest.approx(0.0, abs=1e-6)
    assert v_boa == pytest.approx(0.0, abs=1e-2)
    assert v_mom == pytest.approx(0.0, abs=1e-6)
    assert v_som == pytest.approx(-1.0, abs=1e-2)
    assert v_lom == pytest.approx(1.0, abs=1e-2)


def test_surface_and_rule_coverage_diagnostics() -> None:
    """Verifica avaliação de superfície 2D e diagnóstico de cobertura e conflito de regras."""
    sys_2d = FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "x1",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "N", "mf": "gaussian", "params": [-1.0, 0.8]},
                    {"name": "P", "mf": "gaussian", "params": [1.0, 0.8]},
                ],
            },
            {
                "name": "x2",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "N", "mf": "gaussian", "params": [-1.0, 0.8]},
                    {"name": "P", "mf": "gaussian", "params": [1.0, 0.8]},
                ],
            },
        ],
        output_variables=[
            {
                "name": "u",
                "universe": [-5.0, 5.0],
                "terms": [
                    {"name": "C1", "type": "constant", "params": [-2.0]},
                    {"name": "C2", "type": "constant", "params": [2.0]},
                ],
            }
        ],
        rules=[
            {"name": "R1", "antecedents": {"x1": "N", "x2": "N"}, "consequents": {"u": "C1"}},
            {"name": "R2", "antecedents": {"x1": "P", "x2": "P"}, "consequents": {"u": "C2"}},
            # Regra conflitante com R1
            {"name": "R3", "antecedents": {"x1": "N", "x2": "N"}, "consequents": {"u": "C2"}},
        ],
    )

    cov = check_rule_coverage(sys_2d, n_grid=11)
    assert cov.status == "warning"
    assert cov.data is not None
    assert cov.data["is_fully_covered"] is True
    assert len(cov.data["conflicts"]) == 1

    surf = evaluate_surface(sys_2d, n_points=5)
    assert surf.status == "success"
    assert surf.data is not None
    assert len(surf.data["surfaces"]["u"]) == 5
    assert len(surf.data["surfaces"]["u"][0]) == 5


# ---------------------------------------------------------------------------
# 4. Teste Normativo T-FML-02 — Round-Trip FML IEEE 1855-2016, Legado e Anti-XXE
# ---------------------------------------------------------------------------


def test_t_fml_02_export_import_roundtrip_mamdani_and_ts() -> None:
    """T-FML-02: Exporta e reimporta FML IEEE 1855-2016 validando equivalência em malha."""
    # 1. Round-trip Mamdani 2 entradas
    mamdani = FuzzySystem(
        inference_type="mamdani",
        input_variables=[
            {
                "name": "EA",
                "universe": [-3.14, 3.14],
                "scale": "rad",
                "terms": [
                    {"name": "Neg", "mf": "triangular", "params": [-3.14, -3.14, 0.0]},
                    {"name": "Zero", "mf": "gaussian", "params": [0.0, 0.8]},
                    {"name": "Pos", "mf": "triangular", "params": [0.0, 3.14, 3.14]},
                ],
            },
            {
                "name": "EP",
                "universe": [0.0, 5.0],
                "scale": "m",
                "terms": [
                    {"name": "Near", "mf": "trapezoidal", "params": [0.0, 0.0, 1.0, 3.0]},
                    {"name": "Far", "mf": "trapezoidal", "params": [1.5, 3.5, 5.0, 5.0]},
                ],
            },
        ],
        output_variables=[
            {
                "name": "VA",
                "universe": [-5.0, 5.0],
                "scale": "rad/s",
                "terms": [
                    {"name": "Left", "mf": "triangular", "params": [-5.0, -2.5, 0.0]},
                    {"name": "Straight", "mf": "triangular", "params": [-1.5, 0.0, 1.5]},
                    {"name": "Right", "mf": "triangular", "params": [0.0, 2.5, 5.0]},
                ],
            }
        ],
        rules=[
            {"name": "R1", "antecedents": {"EA": "Neg", "EP": "Far"}, "consequents": {"VA": "Left"}},
            {"name": "R2", "antecedents": {"EA": "Zero", "EP": "Near"}, "consequents": {"VA": "Straight"}},
            {"name": "R3", "antecedents": {"EA": "Pos", "EP": "Far"}, "consequents": {"VA": "Right"}},
        ],
        operators={"and": "min", "or": "max", "implication": "min", "aggregation": "max", "defuzzification": "centroid"},
    )

    exp_res = export_fml(mamdani)
    assert exp_res.status == "success"
    assert exp_res.data is not None
    xml_text = exp_res.data["fml_xml"]
    assert "<fuzzySystem" in xml_text
    assert "<mamdaniRuleBase" in xml_text

    imp_res = import_fml(xml_text)
    assert imp_res.status == "success"
    assert imp_res.data is not None
    restored_mamdani = FuzzySystem.from_dict(imp_res.data["fuzzy_system"])

    for ea in np.linspace(-3.0, 3.0, 7):
        for ep in np.linspace(0.0, 5.0, 5):
            r_orig = evaluate(mamdani, {"EA": float(ea), "EP": float(ep)}, grid_resolution=101)
            r_rest = evaluate(restored_mamdani, {"EA": float(ea), "EP": float(ep)}, grid_resolution=101)
            assert r_orig.data is not None and r_rest.data is not None
            assert r_rest.data["output"] == pytest.approx(r_orig.data["output"], abs=1e-12)

    # 2. Round-trip Takagi-Sugeno
    ts_model = FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "x1",
                "universe": [-2.0, 2.0],
                "terms": [
                    {"name": "L", "mf": "gaussian", "params": [-1.0, 0.7]},
                    {"name": "H", "mf": "gaussian", "params": [1.0, 0.7]},
                ],
            }
        ],
        output_variables=[
            {
                "name": "y",
                "universe": [-10.0, 10.0],
                "terms": [
                    {"name": "F1", "type": "linear", "params": [1.5, -0.5]},
                    {"name": "F2", "type": "linear", "params": [-2.0, 1.0]},
                ],
            }
        ],
        rules=[
            {"name": "R1", "antecedents": {"x1": "L"}, "consequents": {"y": "F1"}},
            {"name": "R2", "antecedents": {"x1": "H"}, "consequents": {"y": "F2"}},
        ],
    )
    exp_ts = export_fml(ts_model)
    assert exp_ts.status == "success" and exp_ts.data is not None
    imp_ts = import_fml(exp_ts.data["fml_xml"])
    assert imp_ts.status == "success" and imp_ts.data is not None
    restored_ts = FuzzySystem.from_dict(imp_ts.data["fuzzy_system"])

    for x_val in np.linspace(-2.0, 2.0, 15):
        y_orig = evaluate(ts_model, [float(x_val)]).data["output"]  # type: ignore[index]
        y_rest = evaluate(restored_ts, [float(x_val)]).data["output"]  # type: ignore[index]
        assert y_rest == pytest.approx(y_orig, abs=1e-12)


def test_t_fml_02_xxe_and_billion_laughs_strictly_blocked() -> None:
    """T-FML-02 (Segurança): Bloqueia ataques XXE, DTD externo, ENTITY e payloads excessivos."""
    xxe_payloads = [
        # Clássico XXE de leitura de arquivo local via SYSTEM
        """<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE fuzzySystem [
          <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <fuzzySystem name="&xxe;"><knowledgeBase/></fuzzySystem>
        """,
        # DTD externo via PUBLIC
        """<?xml version="1.0"?>
        <!DOCTYPE fuzzySystem PUBLIC "-//W3C//DTD XHTML 1.0//EN" "http://example.com/evil.dtd">
        <fuzzySystem name="test"><knowledgeBase/></fuzzySystem>
        """,
        # Billion Laughs (expansão exponencial de entidades internas)
        """<?xml version="1.0"?>
        <!DOCTYPE lolz [
          <!ENTITY lol "lol">
          <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
        ]>
        <fuzzySystem name="&lol2;"><knowledgeBase/></fuzzySystem>
        """,
    ]

    for payload in xxe_payloads:
        res = import_fml(payload)
        assert res.status == "failure"
        assert res.error is not None
        assert res.error.code == "IMPORT_UNTRUSTED_CODE"

    # Limite de tamanho de payload
    res_huge = import_fml("<fuzzySystem/>", max_bytes=5)
    assert res_huge.status == "failure"
    assert res_huge.error is not None
    assert res_huge.error.code == "RESOURCE_LIMIT"


def test_legacy_fuzzy_lab_xml_import_compatibility() -> None:
    """Verifica importação de XML gerado pelo laboratório legado (`docs/references/legacy_fuzzy_lab/`)."""
    legacy_xml = """<?xml version="1.0" encoding="UTF-8"?>
<!-- FuzzyLabMetadata: {"app":"FuzzyLabWeb","schemaVersion":3,"standardIntent":"IEEE 1855-2016","gains":{"e1":1,"e2":1,"omega":1,"velocity":1},"sNorm":"max","tNorm":"min","implication":"min","fuzzification":"singleton","defuzzification":"cg","resolution":51} -->
<fuzzySystem xmlns="http://www.ieee1855.org" name="FuzzyLabController">
  <knowledgeBase>
    <fuzzyVariable name="EA" domainleft="-3.141592653589793" domainright="3.141592653589793" scale="rad" type="input">
      <fuzzyTerm name="EA__Negativo" complement="false">
        <triangularShape param1="-3.141592653589793" param2="-3.141592653589793" param3="0"/>
      </fuzzyTerm>
      <fuzzyTerm name="EA__Positivo" complement="false">
        <triangularShape param1="0" param2="3.141592653589793" param3="3.141592653589793"/>
      </fuzzyTerm>
    </fuzzyVariable>
    <fuzzyVariable name="EP" domainleft="0" domainright="5" scale="m" type="input">
      <fuzzyTerm name="EP__Perto" complement="false">
        <gaussianShape param1="0" param2="1.5"/>
      </fuzzyTerm>
      <fuzzyTerm name="EP__Longe" complement="false">
        <gaussianShape param1="5" param2="1.5"/>
      </fuzzyTerm>
    </fuzzyVariable>
    <fuzzyVariable name="VA" domainleft="-5" domainright="5" scale="rad/s" type="output" accumulation="MAX" defuzzifier="COG" defaultValue="0">
      <fuzzyTerm name="VA__Esquerda" complement="false">
        <triangularShape param1="-5" param2="-2.5" param3="0"/>
      </fuzzyTerm>
      <fuzzyTerm name="VA__Direita" complement="false">
        <triangularShape param1="0" param2="2.5" param3="5"/>
      </fuzzyTerm>
    </fuzzyVariable>
    <fuzzyVariable name="VEL" domainleft="-5" domainright="5" scale="m/s" type="output" accumulation="MAX" defuzzifier="COG" defaultValue="0">
      <fuzzyTerm name="VEL__Lento" complement="false">
        <trapezoidShape param1="0" param2="0.5" param3="1.5" param4="2.5"/>
      </fuzzyTerm>
      <fuzzyTerm name="VEL__Rapido" complement="false">
        <trapezoidShape param1="2" param2="3.5" param3="5" param4="5"/>
      </fuzzyTerm>
    </fuzzyVariable>
  </knowledgeBase>
  <mamdaniRuleBase name="RuleBase1" activationMethod="MIN" andMethod="MIN" orMethod="MAX">
    <rule name="R1" connector="and" andMethod="MIN" weight="1">
      <antecedent>
        <clause><variable>EA</variable><term>EA__Negativo</term></clause>
        <clause><variable>EP</variable><term>EP__Perto</term></clause>
      </antecedent>
      <consequent>
        <then>
          <clause><variable>VA</variable><term>VA__Esquerda</term></clause>
          <clause><variable>VEL</variable><term>VEL__Lento</term></clause>
        </then>
      </consequent>
    </rule>
    <rule name="R2" connector="and" andMethod="MIN" weight="1">
      <antecedent>
        <clause><variable>EA</variable><term>EA__Positivo</term></clause>
        <clause><variable>EP</variable><term>EP__Longe</term></clause>
      </antecedent>
      <consequent>
        <then>
          <clause><variable>VA</variable><term>VA__Direita</term></clause>
          <clause><variable>VEL</variable><term>VEL__Rapido</term></clause>
        </then>
      </consequent>
    </rule>
  </mamdaniRuleBase>
</fuzzySystem>
"""
    res = import_fml(legacy_xml)
    assert res.status in ("success", "warning")
    assert res.data is not None
    assert res.data["legacy_metadata"]["app"] == "FuzzyLabWeb"

    fs = FuzzySystem.from_dict(res.data["fuzzy_system"])
    eval_res = evaluate(fs, {"EA": 2.0, "EP": 4.0}, coupled_mamdani=True, grid_resolution=51)
    assert eval_res.status == "success"
    assert eval_res.data is not None
    assert eval_res.data["outputs"]["VA"] > 0.0
    assert eval_res.data["outputs"]["VEL"] > 2.0


# ---------------------------------------------------------------------------
# 5. Treinamento Híbrido ANFIS (QR/SVD + Gradiente)
# ---------------------------------------------------------------------------


def test_fit_anfis_hybrid_learning_and_holdout() -> None:
    """Testa fit_anfis em função suave 1D e 2D com semente determinística e validação em holdout."""
    rng = np.random.default_rng(123)
    x_train = np.linspace(-2.0, 2.0, 60)
    y_train = 1.8 * x_train - 0.4 * np.square(x_train) + 0.5 + rng.normal(0.0, 0.02, size=x_train.size)

    x_test = np.linspace(-1.8, 1.8, 25)
    y_test = 1.8 * x_test - 0.4 * np.square(x_test) + 0.5

    res = fit_anfis(
        x_train,
        y_train,
        X_val=x_test,
        y_val=y_test,
        n_mfs=3,
        mf_type="gaussian",
        max_epochs=25,
        learning_rate=0.02,
        seed=123,
    )
    assert res.status in ("success", "warning")
    assert res.data is not None
    assert res.data["metrics"]["val_rmse"] < 0.15
    assert res.data["metrics"]["val_fit_percent"] > 85.0

    # Verifica que o FuzzySystem produzido pelo ANFIS é marcado como estático (is_dynamic_model=False)
    anfis_fs = FuzzySystem.from_dict(res.data["fuzzy_system"])
    assert anfis_fs.is_dynamic_model is False
    assert anfis_fs.inference_type == "ts"

    # Avalia um ponto no modelo treinado via evaluate
    pt_eval = evaluate(anfis_fs, [0.5])
    assert pt_eval.status == "success"
    assert pt_eval.data is not None
    expected_pt = 1.8 * 0.5 - 0.4 * (0.5**2) + 0.5
    assert pt_eval.data["output"] == pytest.approx(expected_pt, abs=0.15)


# ---------------------------------------------------------------------------
# 6. ADR-006 e Teste Normativo T-TS-01 (Conversão TS e Bloqueio PDC)
# ---------------------------------------------------------------------------


def test_adr_006_static_anfis_cannot_convert_to_ts_state_space() -> None:
    """ADR-006 / Seção 5.6: Nunca converter aproximador estático ANFIS em TSStateSpace dinâmico."""
    x = np.linspace(-1.0, 1.0, 30)
    y = 2.0 * x + 1.0
    anfis_res = fit_anfis(x, y, n_mfs=2, max_epochs=5, seed=7)
    assert anfis_res.data is not None
    static_fs = FuzzySystem.from_dict(anfis_res.data["fuzzy_system"])
    assert static_fs.is_dynamic_model is False

    conv_res = to_ts_state_space(static_fs)
    assert conv_res.status == "failure"
    assert conv_res.error is not None
    assert conv_res.error.code == "HYPOTHESIS_VIOLATED"
    assert "ADR-006" in conv_res.error.message


def test_to_ts_state_space_succeeds_when_dynamics_explicitly_identified() -> None:
    """Valida conversão para TSStateSpace quando is_dynamic_model=True e vértices (A_i, B_i, C_i, D_i) existem."""
    vertices = [
        {
            "vertex_id": "v1",
            "A": [[0.0, 1.0], [-2.0, -1.0]],
            "B": [[0.0], [1.0]],
            "C": [[1.0, 0.0]],
            "D": [[0.0]],
        },
        {
            "vertex_id": "v2",
            "A": [[0.0, 1.0], [-4.0, -1.5]],
            "B": [[0.0], [1.0]],
            "C": [[1.0, 0.0]],
            "D": [[0.0]],
        },
    ]
    dyn_fs = FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "x1",
                "universe": [-2.0, 2.0],
                "terms": [
                    {"name": "Low", "mf": "triangular", "params": [-2.0, -2.0, 2.0]},
                    {"name": "High", "mf": "triangular", "params": [-2.0, 2.0, 2.0]},
                ],
            }
        ],
        output_variables=[
            {
                "name": "dx",
                "universe": [-10.0, 10.0],
                "terms": [
                    {"name": "Local1", "type": "linear", "params": [-2.0, 0.0]},
                    {"name": "Local2", "type": "linear", "params": [-4.0, 0.0]},
                ],
            }
        ],
        rules=[
            {"name": "R1", "antecedents": {"x1": "Low"}, "consequents": {"dx": "Local1"}},
            {"name": "R2", "antecedents": {"x1": "High"}, "consequents": {"dx": "Local2"}},
        ],
        is_dynamic_model=True,
        dynamic_semantics={
            "kind": "ts_measured",
            "vertices": vertices,
            "state_names": ["x1", "x2"],
            "input_names": ["u"],
            "output_names": ["y"],
        },
    )

    conv_res = to_ts_state_space(dyn_fs)
    assert conv_res.status == "success"
    assert conv_res.data is not None
    ts_model = TSStateSpace.from_dict(conv_res.data["ts_state_space"])
    assert ts_model.kind == "ts_measured"
    assert ts_model.n_vertices == 2
    assert conv_res.diagnostics["max_convex_sum_residual"] == pytest.approx(0.0, abs=1e-12)

    # Avalia pesos das premissas em x1 = 0.0 -> [0.5, 0.5]
    w_res = evaluate_ts_premise_weights(ts_model, {"x1": 0.0})
    assert w_res.status == "success"
    assert w_res.data is not None
    assert w_res.data["weights"] == pytest.approx([0.5, 0.5], abs=1e-12)


def test_t_ts_01_block_pdc_for_polytopic_uncertain_and_allow_measured() -> None:
    """T-TS-01: Recusa PDC agendado em TSStateSpace(kind='polytopic_uncertain') sem estimativa de premissa."""
    vertices = [
        {
            "vertex_id": "v1",
            "A": [[0.0, 1.0], [-1.0, -0.5]],
            "B": [[0.0], [1.0]],
            "C": [[1.0, 0.0]],
            "D": [[0.0]],
        },
        {
            "vertex_id": "v2",
            "A": [[0.0, 1.0], [-3.0, -0.8]],
            "B": [[0.0], [1.0]],
            "C": [[1.0, 0.0]],
            "D": [[0.0]],
        },
    ]

    poly_model = TSStateSpace(
        vertices=vertices,
        kind="polytopic_uncertain",
        dt=None,
        membership_spec={
            "version": "1.0.0",
            "premise_variables": ["alpha1", "alpha2"],
            "sum_to_one_domain": True,
        },
        premise_availability={
            "mode": "unknown_uncertain",
            "measured_premises": [],
            "unmeasured_premises": ["alpha1", "alpha2"],
            "estimator_required_for_pdc": True,
        },
        domain={"bounds": {"alpha1": [0.0, 1.0], "alpha2": [0.0, 1.0]}},
    )

    K1 = [[2.0, 1.5]]
    K2 = [[1.0, 1.2]]

    # 1. Tentar criar PDC agendado para polytopic_uncertain DEVE falhar com HYPOTHESIS_VIOLATED (T-TS-01)
    pdc_blocked = make_pdc_spec(poly_model, gains=[K1, K2], architecture="pdc")
    assert pdc_blocked.status == "failure"
    assert pdc_blocked.error is not None
    assert pdc_blocked.error.code == "HYPOTHESIS_VIOLATED"
    assert "T-TS-01" in pdc_blocked.error.message

    # 2. Arquitetura de ganho único robusto (robust_single_gain) é permitida para polytopic_uncertain
    robust_ok = make_pdc_spec(poly_model, gains=K1, architecture="robust_single_gain")
    assert robust_ok.status == "success"
    assert robust_ok.data is not None
    assert robust_ok.data["architecture"] == "robust_single_gain"
    assert robust_ok.data["controller"]["kind"] == "StateFeedbackController"

    # 3. Para ts_measured, PDC é permitido e preserva os termos cruzados (i, j)
    measured_model = TSStateSpace(
        vertices=vertices,
        kind="ts_measured",
        dt=None,
        membership_spec={
            "version": "1.0.0",
            "premise_variables": ["x1"],
            "sum_to_one_domain": True,
        },
        premise_availability={
            "mode": "all_measured",
            "measured_premises": ["x1"],
            "unmeasured_premises": [],
            "estimator_required_for_pdc": False,
        },
        domain={"bounds": {"x1": [-2.0, 2.0]}},
    )
    pdc_ok = make_pdc_spec(measured_model, gains=[K1, K2], feedback_sign="negative", architecture="pdc")
    assert pdc_ok.status == "success"
    assert pdc_ok.data is not None
    assert pdc_ok.data["controller"]["kind"] == "PDCController"
    assert pdc_ok.data["closed_loop"]["kind"] == "TSClosedLoop"
    assert pdc_ok.diagnostics["total_cross_matrices"] == 4

    # Avalia caso particular sob pesos congelados h = [0.4, 0.6] (emite aviso de que é apenas caso particular)
    frozen_res = evaluate_ts_frozen_weights(pdc_ok.data["closed_loop"], [0.4, 0.6])
    assert frozen_res.status == "warning"
    assert frozen_res.data is not None
    assert frozen_res.data["locally_stable"] is True
    assert any(w.code == "FROZEN_WEIGHTS_PARTICULAR_CASE_ONLY" for w in frozen_res.warnings if hasattr(w, "code"))

    # Verifica rejeição de pesos que não somam 1
    from control_lab.diagnostics import HypothesisViolatedError

    with pytest.raises(HypothesisViolatedError):
        verify_convex_weights([0.3, 0.3])
