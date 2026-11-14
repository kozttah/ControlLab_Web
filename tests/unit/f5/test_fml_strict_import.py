"""AUD-009 regressions: invalid FML has no silent scientific reinterpretation."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from control_lab.core.models import FuzzySystem
from control_lab.fuzzy import evaluate, export_fml, import_fml


VALID_TS = """<fuzzySystem name="strict">
<knowledgeBase>
 <fuzzyVariable name="x" type="input" domainleft="0" domainright="1">
  <fuzzyTerm name="Low"><triangularShape param1="0" param2="0" param3="1"/></fuzzyTerm>
  <fuzzyTerm name="High"><triangularShape param1="0" param2="1" param3="1"/></fuzzyTerm>
 </fuzzyVariable>
 <tskVariable name="y" type="output" domainleft="0" domainright="1" defaultValue="0.25" combination="WTAVER">
  <tskTerm name="Zero" order="0"><tskValue>0</tskValue></tskTerm>
  <tskTerm name="One" order="0"><tskValue>1</tskValue></tskTerm>
 </tskVariable>
</knowledgeBase>
<tskRuleBase andMethod="PROD" orMethod="PROBOR" activationMethod="PROD">
 <rule name="L" connector="and"><antecedent><clause><variable>x</variable><term>Low</term></clause></antecedent><consequent><then><clause><variable>y</variable><term>Zero</term></clause></then></consequent></rule>
 <rule name="H" connector="and"><antecedent><clause><variable>x</variable><term>High</term></clause></antecedent><consequent><then><clause><variable>y</variable><term>One</term></clause></then></consequent></rule>
</tskRuleBase></fuzzySystem>"""


def _failure(root: ET.Element) -> None:
    result = import_fml(ET.tostring(root, encoding="unicode"))
    assert result.status == "failure"
    assert result.data is None
    assert result.error is not None
    assert result.error.code in ("VALIDATION_ERROR", "SCHEMA_UNSUPPORTED")
    assert result.provenance is not None


@pytest.mark.parametrize("shape,params", [
    ("triangularShape", [1, 0, 2]),
    ("trapezoidShape", [0, 2, 1, 3]),
    ("gaussianShape", [0, 0]),
    ("gaussianShape", [0, -0.1]),
    ("bellShape", [0, 1, 0]),
    ("bellShape", [-1, 1, 0]),
    ("bellShape", [1, 0, 0]),
    ("bellShape", [1, -2, 0]),
    ("zShape", [1, 0]),
    ("sShape", [1, 0]),
    ("gaussianShape", [0, "NaN"]),
    ("triangularShape", [0, 0, "inf"]),
])
def test_fml_invalid_parameters_are_not_silently_repaired(shape, params):
    root = ET.fromstring(VALID_TS)
    term = root.find(".//fuzzyTerm")
    term.clear(); term.set("name", "Low")
    ET.SubElement(term, shape, {f"param{i+1}": str(value) for i, value in enumerate(params)})
    _failure(root)


@pytest.mark.parametrize("selector,attribute,value", [
    (".//tskRuleBase", "andMethod", "UNSUPPORTED"),
    (".//tskRuleBase", "orMethod", "UNKNOWN"),
    (".//tskRuleBase", "activationMethod", "UNKNOWN"),
    (".//tskRuleBase", "andMethod", ""),
    (".//rule", "andMethod", "UNKNOWN"),
    (".//rule", "orMethod", "UNKNOWN"),
    (".//rule", "connector", "xor"),
    (".//rule", "connector", ""),
    (".//rule", "weight", ""),
    (".//tskVariable", "combination", "UNKNOWN"),
    (".//tskVariable", "combination", "COG"),
    (".//tskVariable", "accumulation", "MAX"),
    (".//tskVariable", "defaultValue", "bad"),
    (".//tskVariable", "defaultValue", ""),
    (".//tskVariable", "defaultValue", "NaN"),
    (".//tskVariable", "defaultValue", "inf"),
    (".//fuzzyTerm", "complement", "sometimes"),
    (".//tskTerm", "order", "2"),
    (".//fuzzyVariable", "type", "inpt"),
])
def test_fml_unknown_operators_and_malformed_defaults_fail(selector, attribute, value):
    root = ET.fromstring(VALID_TS)
    root.find(selector).set(attribute, value)
    _failure(root)


@pytest.mark.parametrize("mutation", ["unknown_shape", "two_shapes", "two_rulebases", "nested_group", "duplicate_clause", "zero_order_coeffs", "unknown_profile", "linear_input", "first_order_missing_coefficients"])
def test_fml_unsupported_structure_is_not_flattened_or_discarded(mutation):
    root = ET.fromstring(VALID_TS)
    if mutation == "unknown_shape":
        root.find(".//triangularShape").tag = "eviltriangularShape"
    elif mutation == "two_shapes":
        ET.SubElement(root.find(".//fuzzyTerm"), "gaussianShape", param1="0", param2="1")
    elif mutation == "two_rulebases":
        ET.SubElement(root, "tskRuleBase")
    elif mutation == "nested_group":
        ant = root.find(".//antecedent"); clauses = list(ant); ant.clear()
        group = ET.SubElement(ant, "or")
        group.extend(clauses)
    elif mutation == "duplicate_clause":
        ant = root.find(".//antecedent")
        clause = ET.SubElement(ant, "clause")
        ET.SubElement(clause, "variable").text = "x"
        ET.SubElement(clause, "term").text = "High"
    elif mutation == "zero_order_coeffs":
        ET.SubElement(root.find(".//tskTerm"), "tskValue").text = "2"
    elif mutation == "linear_input":
        shape = root.find(".//triangularShape")
        shape.tag = "linearShape"
        shape.attrib.clear()
        shape.set("param1", "1")
        shape.set("param2", "0")
    elif mutation == "first_order_missing_coefficients":
        root.find(".//tskTerm").set("order", "1")
    else:
        root.set("profile", "unsupported")
    _failure(root)


def test_valid_import_and_roundtrip_preserve_analytic_partition_y_equals_x():
    result = import_fml(VALID_TS)
    assert result.status == "success", result.error
    system = FuzzySystem.from_dict(result.data["fuzzy_system"])
    assert system.output_variables[0]["default_value"] == 0.25
    xml = export_fml(system)
    assert xml.status == "success"
    restored = import_fml(xml.data["fml_xml"])
    assert restored.status == "success", restored.error
    for candidate in (system, FuzzySystem.from_dict(restored.data["fuzzy_system"])):
        for x in np.linspace(0, 1, 11):
            observed = evaluate(candidate, [float(x)])
            assert observed.status == "success"
            assert observed.data["output"] == pytest.approx(float(x), abs=1e-12)


@pytest.mark.parametrize("bias_last", [True, False])
def test_homogeneous_multivariable_consequents_export_with_explicit_zero_bias(bias_last):
    inputs = [
        {"name": name, "universe": [0, 1], "terms": [{"name": "All", "mf": "triangular", "params": [0, 0.5, 1]}]}
        for name in ("x", "z")
    ]
    model = FuzzySystem(
        inference_type="ts", input_variables=inputs,
        output_variables=[{"name": "y", "universe": [-10, 10], "terms": [{"name": "Line", "type": "linear", "params": [2, 3], "bias_last": bias_last}]}],
        rules=[{"antecedents": {"x": "All", "z": "All"}, "consequents": {"y": "Line"}}],
    )
    xml = export_fml(model)
    assert xml.status == "success"
    root = ET.fromstring(xml.data["fml_xml"])
    values = [float(e.text) for e in root.iter() if e.tag.endswith("tskValue")]
    assert values == ([2, 3, 0] if bias_last else [0, 2, 3])
    result = import_fml(xml.data["fml_xml"])
    assert result.status == "success", result.error
    restored = FuzzySystem.from_dict(result.data["fuzzy_system"])
    for candidate in (model, restored):
        assert evaluate(candidate, [0.25, 0.5]).data["output"] == pytest.approx(2.0)
