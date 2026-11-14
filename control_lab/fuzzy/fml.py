"""Serialização e parsing IEEE 1855-2016 FML com proteção estrita anti-XXE (CL-DIR-001 Seção 5.6, 9.4, 12.2 e T-FML-01/02)."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping
from xml.sax.saxutils import escape as xml_escape

from control_lab.core.models import FuzzySystem
from control_lab.diagnostics import (
    ControlLabError,
    ImportUntrustedCodeError,
    ResourceLimitError,
    Result,
    SchemaUnsupportedError,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .inference import _coerce_fuzzy_system, normalize_defuzz_method
from .membership import extract_term_spec, normalize_mf_type

DEFAULT_MAX_FML_BYTES: int = 2 * 1024 * 1024  # 2 MiB
DEFAULT_MAX_XML_DEPTH: int = 32
DEFAULT_MAX_XML_ELEMENTS: int = 20_000

# Expressão regular pré-compilada para bloqueio determinístico anti-XXE / anti-DTD / anti-billion-laughs
_XXE_FORBIDDEN_RE = re.compile(
    r"<!\s*(DOCTYPE|ENTITY|ELEMENT|ATTLIST|NOTATION)\b",
    flags=re.IGNORECASE,
)
_XXE_EXT_KEYWORDS_RE = re.compile(
    r"<!\s*[^\>]*\b(SYSTEM|PUBLIC)\b",
    flags=re.IGNORECASE,
)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def _attr_ci(elem: ET.Element, *names: str, default: str | None = None) -> str | None:
    attrib_lower = {k.lower(): v for k, v in elem.attrib.items()}
    for nm in names:
        val = attrib_lower.get(nm.lower())
        if val is not None:
            return val
    return default


def _parse_float_attr(elem: ET.Element, *names: str, field_label: str) -> float:
    raw = _attr_ci(elem, *names)
    if raw is None or not str(raw).strip():
        raise ValidationError(f"Atributo numérico obrigatório ausente ({field_label}).")
    try:
        val = float(raw)
    except ValueError as exc:
        raise ValidationError(f"Atributo numérico inválido em {field_label}: {raw!r}") from exc
    if not (val == val and abs(val) != float("inf")):
        raise ValidationError(f"Atributo numérico não finito em {field_label}: {raw!r}")
    return val


def _to_fml_and(method: str) -> str:
    m = str(method or "min").strip().lower()
    if m in ("prod", "product"):
        return "PROD"
    if m in ("eprod", "eins", "einstein", "einstein_prod"):
        return "EPROD"
    if m in ("lukasiewicz", "bounded_diff"):
        return "BDIF"
    return "MIN"


def _from_fml_and(value: str | None, *, default: str = "min") -> str:
    if not value:
        return default
    v = value.strip().upper()
    if v in ("PROD", "PRODUCT"):
        return "prod"
    if v in ("EPROD", "EINS", "EINSTEIN"):
        return "eprod"
    if v in ("BDIF", "LUKASIEWICZ"):
        return "lukasiewicz"
    return "min"


def _to_fml_or(method: str) -> str:
    m = str(method or "max").strip().lower()
    if m in ("prob", "probor", "prob_or"):
        return "PROBOR"
    if m in ("esum", "eins", "einstein", "einstein_sum"):
        return "ESUM"
    if m in ("sum", "bounded_sum", "bsum"):
        return "BSUM"
    return "MAX"


def _from_fml_or(value: str | None, *, default: str = "max") -> str:
    if not value:
        return default
    v = value.strip().upper()
    if v in ("PROBOR", "PROB", "PROB_OR"):
        return "probor"
    if v in ("ESUM", "EINS", "EINSTEIN"):
        return "esum"
    if v in ("BSUM", "SUM", "BOUNDED_SUM"):
        return "bounded_sum"
    return "max"


def _to_fml_defuzz(method: str, *, inference_type: str = "mamdani") -> str:
    canonical = normalize_defuzz_method(method, inference_type=inference_type)
    mapping = {
        "centroid": "COG",
        "bisector": "BOA",
        "mom": "MOM",
        "som": "LM",
        "lom": "RM",
        "wtaver": "WTAVER",
        "wtsum": "WTSUM",
    }
    return mapping.get(canonical, "COG")


def _from_fml_defuzz(value: str | None, *, inference_type: str = "mamdani") -> str:
    if not value:
        return "centroid" if inference_type == "mamdani" else "wtaver"
    v = value.strip().upper()
    mapping = {
        "COG": "centroid",
        "COA": "centroid",
        "CG": "centroid",
        "CENTROID": "centroid",
        "BOA": "bisector",
        "BISECTOR": "bisector",
        "MOM": "mom",
        "LM": "som",
        "SOM": "som",
        "RM": "lom",
        "LOM": "lom",
        "WTAVER": "wtaver",
        "WTSUM": "wtsum",
    }
    return mapping.get(v, normalize_defuzz_method(value, inference_type=inference_type))


def _check_xml_safety_and_limits(
    xml_content: str | bytes,
    *,
    max_bytes: int = DEFAULT_MAX_FML_BYTES,
    max_depth: int = DEFAULT_MAX_XML_DEPTH,
    max_elements: int = DEFAULT_MAX_XML_ELEMENTS,
) -> ET.Element:
    """Inspeciona o payload XML bloqueando XXE/DTD/ENTITY e impondo limites de tamanho e profundidade."""
    if isinstance(xml_content, bytes):
        raw_bytes = xml_content
        if len(raw_bytes) > max_bytes:
            raise ResourceLimitError(
                message=f"Payload FML excede o limite máximo de {max_bytes} bytes ({len(raw_bytes)} bytes recebidos).",
                parameters={"size_bytes": len(raw_bytes), "max_bytes": max_bytes},
                next_step="Reduza o tamanho do arquivo XML/FML antes de importar.",
            )
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("Arquivo FML deve estar codificado em UTF-8 válido.") from exc
    elif isinstance(xml_content, str):
        raw_bytes = xml_content.encode("utf-8")
        if len(raw_bytes) > max_bytes:
            raise ResourceLimitError(
                message=f"Payload FML excede o limite máximo de {max_bytes} bytes ({len(raw_bytes)} bytes recebidos).",
                parameters={"size_bytes": len(raw_bytes), "max_bytes": max_bytes},
                next_step="Reduza o tamanho do arquivo XML/FML antes de importar.",
            )
        text = xml_content
    else:
        raise ValidationError(f"Conteúdo FML deve ser str ou bytes, recebido {type(xml_content).__name__}.")

    if not text.strip():
        raise ValidationError("Conteúdo XML/FML vazio.")

    # Bloqueio estrito de declarações DTD / ENTITY / SYSTEM / PUBLIC (proteção XXE e Billion Laughs)
    m_dtd = _XXE_FORBIDDEN_RE.search(text)
    m_ext = _XXE_EXT_KEYWORDS_RE.search(text)
    if m_dtd is not None or m_ext is not None:
        token = m_dtd.group(0) if m_dtd is not None else (m_ext.group(0) if m_ext is not None else "DTD/XXE")
        raise ImportUntrustedCodeError(
            message=(
                f"Declaração DTD/ENTITY/XXE proibida detectada no documento FML ({token!r}). "
                "Entidades externas e DTDs são bloqueados por política de segurança (Seção 9.4 / 12.2)."
            ),
            parameters={"forbidden_construct": token},
            next_step="Remova quaisquer diretivas <!DOCTYPE, <!ENTITY, SYSTEM ou PUBLIC do XML.",
        )

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        msg = str(exc)
        if "entity" in msg.lower() or "doctype" in msg.lower():
            raise ImportUntrustedCodeError(
                message=f"Construção XML de entidade não permitida: {msg}",
                parameters={"parse_error": msg},
            ) from exc
        raise ValidationError(
            message=f"Documento XML/FML malformado: {msg}",
            parameters={"parse_error": msg},
        ) from exc

    # Verifica profundidade máxima e número total de elementos
    element_count = 0
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    while stack:
        elem, depth = stack.pop()
        element_count += 1
        if depth > max_depth:
            raise ResourceLimitError(
                message=f"Profundidade XML ({depth}) excede o limite de segurança ({max_depth}).",
                parameters={"depth": depth, "max_depth": max_depth},
            )
        if element_count > max_elements:
            raise ResourceLimitError(
                message=f"Número de elementos XML ({element_count}) excede o limite de segurança ({max_elements}).",
                parameters={"elements": element_count, "max_elements": max_elements},
            )
        for child in elem:
            stack.append((child, depth + 1))

    return root


def _term_to_fml_xml(term: Mapping[str, Any], *, role: str, inference_type: str, indent: str = "      ") -> str:
    tname = xml_escape(str(term["name"]), {'"': "&quot;"})
    complement_str = "true" if term.get("complement", False) else "false"
    mf_type, params, _ = extract_term_spec(term)

    if role == "output" and inference_type == "ts":
        bias_last = "true" if term.get("bias_last", True) else "false"
        if mf_type in ("constant", "singleton") or len(params) == 1:
            return (
                f'{indent}<tskTerm name="{tname}" order="0">\n'
                f'{indent}  <tskValue>{repr(float(params[0]))}</tskValue>\n'
                f"{indent}</tskTerm>"
            )
        vals = "\n".join(f"{indent}  <tskValue>{repr(float(p))}</tskValue>" for p in params)
        return (
            f'{indent}<tskTerm name="{tname}" order="1" biasLast="{bias_last}">\n'
            f"{vals}\n"
            f"{indent}</tskTerm>"
        )

    if mf_type == "triangular":
        shape_tag = (
            f'<triangularShape param1="{repr(float(params[0]))}" '
            f'param2="{repr(float(params[1]))}" param3="{repr(float(params[2]))}"/>'
        )
    elif mf_type == "trapezoidal":
        shape_tag = (
            f'<trapezoidShape param1="{repr(float(params[0]))}" '
            f'param2="{repr(float(params[1]))}" param3="{repr(float(params[2]))}" '
            f'param4="{repr(float(params[3]))}"/>'
        )
    elif mf_type == "gaussian":
        shape_tag = (
            f'<gaussianShape param1="{repr(float(params[0]))}" '
            f'param2="{repr(float(params[1]))}"/>'
        )
    elif mf_type == "bell":
        shape_tag = (
            f'<bellShape param1="{repr(float(params[0]))}" '
            f'param2="{repr(float(params[1]))}" param3="{repr(float(params[2]))}"/>'
        )
    elif mf_type == "sigmoid":
        shape_tag = (
            f'<sigmoidShape param1="{repr(float(params[0]))}" '
            f'param2="{repr(float(params[1]))}"/>'
        )
    elif mf_type in ("singleton", "constant"):
        shape_tag = f'<singletonShape param1="{repr(float(params[0]))}"/>'
    elif mf_type == "z_shape":
        shape_tag = (
            f'<zShape param1="{repr(float(params[0]))}" '
            f'param2="{repr(float(params[1]))}"/>'
        )
    elif mf_type == "s_shape":
        shape_tag = (
            f'<sShape param1="{repr(float(params[0]))}" '
            f'param2="{repr(float(params[1]))}"/>'
        )
    else:
        raise SchemaUnsupportedError(f"Exportação FML não suporta formato de pertinência {mf_type!r}.")

    return (
        f'{indent}<fuzzyTerm name="{tname}" complement="{complement_str}">\n'
        f"{indent}  {shape_tag}\n"
        f"{indent}</fuzzyTerm>"
    )


def export_fml(system: FuzzySystem | Mapping[str, Any]) -> Result:
    """Exporta `FuzzySystem` para documento XML no perfil suportado do padrão IEEE 1855-2016 FML."""
    try:
        fs = _coerce_fuzzy_system(system)
        ops = fs.operators
        inf_type = fs.inference_type

        var_blocks: list[str] = []
        for var in fs.input_variables:
            vname = xml_escape(str(var["name"]), {'"': "&quot;"})
            lo = repr(float(var["universe"][0]))
            hi = repr(float(var["universe"][1]))
            scale = xml_escape(str(var.get("scale", var.get("unit", ""))), {'"': "&quot;"})
            terms_xml = "\n".join(
                _term_to_fml_xml(t, role="input", inference_type=inf_type) for t in var["terms"]
            )
            var_blocks.append(
                f'    <fuzzyVariable name="{vname}" domainleft="{lo}" domainright="{hi}" '
                f'scale="{scale}" type="input">\n{terms_xml}\n    </fuzzyVariable>'
            )

        for var in fs.output_variables:
            vname = xml_escape(str(var["name"]), {'"': "&quot;"})
            lo = repr(float(var["universe"][0]))
            hi = repr(float(var["universe"][1]))
            scale = xml_escape(str(var.get("scale", var.get("unit", ""))), {'"': "&quot;"})
            default_val = repr(float(var.get("default_value", 0.0)))
            terms_xml = "\n".join(
                _term_to_fml_xml(t, role="output", inference_type=inf_type) for t in var["terms"]
            )
            if inf_type == "ts":
                comb = _to_fml_defuzz(ops.get("defuzzification", "wtaver"), inference_type="ts")
                var_blocks.append(
                    f'    <tskVariable name="{vname}" domainleft="{lo}" domainright="{hi}" '
                    f'scale="{scale}" type="output" combination="{comb}" defaultValue="{default_val}">\n'
                    f"{terms_xml}\n    </tskVariable>"
                )
            else:
                acc = _to_fml_or(var.get("accumulation", ops.get("aggregation", ops.get("or", "max"))))
                defuzz = _to_fml_defuzz(
                    var.get("defuzzifier", ops.get("defuzzification", "centroid")),
                    inference_type="mamdani",
                )
                var_blocks.append(
                    f'    <fuzzyVariable name="{vname}" domainleft="{lo}" domainright="{hi}" '
                    f'scale="{scale}" type="output" accumulation="{acc}" defuzzifier="{defuzz}" '
                    f'defaultValue="{default_val}">\n{terms_xml}\n    </fuzzyVariable>'
                )

        rules_blocks: list[str] = []
        default_and_fml = _to_fml_and(ops.get("and", "min" if inf_type == "mamdani" else "prod"))
        default_or_fml = _to_fml_or(ops.get("or", "max" if inf_type == "mamdani" else "probor"))

        for idx, rule in enumerate(fs.rules):
            rname = xml_escape(str(rule.get("name", f"R{idx + 1}")), {'"': "&quot;"})
            connector = xml_escape(str(rule.get("connector", "and")).lower(), {'"': "&quot;"})
            r_and = _to_fml_and(rule.get("and_method", ops.get("and", "min" if inf_type == "mamdani" else "prod")))
            r_or = _to_fml_or(rule.get("or_method", ops.get("or", "max" if inf_type == "mamdani" else "probor")))
            weight = repr(float(rule.get("weight", 1.0)))

            ant_clauses = "\n".join(
                f"        <clause><variable>{xml_escape(str(k))}</variable><term>{xml_escape(str(v))}</term></clause>"
                for k, v in rule["antecedents"].items()
            )
            cons_clauses = "\n".join(
                f"          <clause><variable>{xml_escape(str(k))}</variable><term>{xml_escape(str(v))}</term></clause>"
                for k, v in rule["consequents"].items()
            )
            rules_blocks.append(
                f'    <rule name="{rname}" connector="{connector}" andMethod="{r_and}" orMethod="{r_or}" weight="{weight}">\n'
                f"      <antecedent>\n{ant_clauses}\n      </antecedent>\n"
                f"      <consequent>\n        <then>\n{cons_clauses}\n        </then>\n      </consequent>\n"
                f"    </rule>"
            )

        kb_xml = "\n".join(var_blocks)
        rb_rules_xml = "\n".join(rules_blocks)
        if inf_type == "ts":
            act_fml = _to_fml_and(ops.get("implication", ops.get("and", "prod")))
            rb_tag = "tskRuleBase"
            rb_attrs = f'name="RuleBase1" activationMethod="{act_fml}" andMethod="{default_and_fml}" orMethod="{default_or_fml}"'
        else:
            act_fml = _to_fml_and(ops.get("implication", "min"))
            rb_tag = "mamdaniRuleBase"
            rb_attrs = f'name="RuleBase1" activationMethod="{act_fml}" andMethod="{default_and_fml}" orMethod="{default_or_fml}"'

        meta_payload = {
            "id": fs.id,
            "revision": fs.revision,
            "schema_version": fs.schema_version,
            "fml_profile": fs.fml_profile,
            "is_dynamic_model": fs.is_dynamic_model,
            "dynamic_semantics": fs.dynamic_semantics,
        }
        meta_comment = json.dumps(meta_payload, sort_keys=True).replace("--", "—")
        sys_name = xml_escape(fs.id, {'"': "&quot;"})

        xml_str = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<!-- ControlLabMetadata: {meta_comment} -->\n"
            f'<fuzzySystem xmlns="http://www.ieee1855.org" name="{sys_name}" profile="{xml_escape(fs.fml_profile, {chr(34): "&quot;"})}">\n'
            f"  <knowledgeBase>\n{kb_xml}\n  </knowledgeBase>\n"
            f"  <{rb_tag} {rb_attrs}>\n{rb_rules_xml}\n  </{rb_tag}>\n"
            "</fuzzySystem>\n"
        )

        return Result(
            status="success",
            data={
                "fml_xml": xml_str,
                "system_id": fs.id,
                "inference_type": fs.inference_type,
                "fml_profile": fs.fml_profile,
            },
            assumptions={"fml_profile": fs.fml_profile, "xxe_safe": True},
            diagnostics={
                "byte_length": len(xml_str.encode("utf-8")),
                "n_inputs": len(fs.input_variables),
                "n_outputs": len(fs.output_variables),
                "n_rules": len(fs.rules),
            },
            provenance=build_provenance("control_lab.fuzzy.export_fml", model_revision=fs.revision),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.export_fml"),
            warnings=(),
            error=exc.to_typed_error(),
        )


def _parse_fml_term(term_el: ET.Element, *, role: str, is_tsk: bool) -> dict[str, Any]:
    tname = _attr_ci(term_el, "name")
    if not tname or not tname.strip():
        raise ValidationError("Elemento de termo FML sem atributo 'name'.")
    comp_attr = _attr_ci(term_el, "complement", default="false")
    complement = str(comp_attr).strip().lower() == "true"

    lname = _local_name(term_el.tag).lower()
    if is_tsk or lname == "tskterm":
        vals: list[float] = []
        for child in term_el:
            cl = _local_name(child.tag).lower()
            if cl in ("tskvalue", "value", "param", "coefficient"):
                txt = (child.text or "").strip()
                if not txt:
                    txt = _attr_ci(child, "value", "param1", default="") or ""
                try:
                    v = float(txt)
                except ValueError as exc:
                    raise ValidationError(f"Valor numérico inválido em tskTerm {tname!r}: {txt!r}") from exc
                vals.append(v)
        if not vals:
            # Tenta ler atributos param1, param2...
            idx = 1
            while True:
                p_attr = _attr_ci(term_el, f"param{idx}")
                if p_attr is None:
                    break
                vals.append(float(p_attr))
                idx += 1
        if not vals:
            raise ValidationError(f"tskTerm {tname!r} não possui coeficientes numéricos.")
        order_attr = _attr_ci(term_el, "order")
        bias_last_attr = _attr_ci(term_el, "biaslast", default="true")
        bias_last = str(bias_last_attr).strip().lower() != "false"
        if order_attr == "0" or len(vals) == 1:
            return {"name": tname, "type": "constant", "params": [vals[0]], "coefficients": [vals[0]]}
        return {
            "name": tname,
            "type": "linear",
            "params": vals,
            "coefficients": vals,
            "bias_last": bias_last,
        }

    children = list(term_el)
    if not children:
        raise ValidationError(f"fuzzyTerm {tname!r} não contém elemento de formato (shape).")

    shape_el = children[0]
    sname = _local_name(shape_el.tag).lower()

    if "triangular" in sname:
        p1 = _parse_float_attr(shape_el, "param1", "a", field_label=f"{tname}.param1")
        p2 = _parse_float_attr(shape_el, "param2", "b", field_label=f"{tname}.param2")
        p3 = _parse_float_attr(shape_el, "param3", "c", field_label=f"{tname}.param3")
        params = sorted([p1, p2, p3])
        return {"name": tname, "mf": "triangular", "params": params, "complement": complement}

    if "trapezoid" in sname:
        p1 = _parse_float_attr(shape_el, "param1", "a", field_label=f"{tname}.param1")
        p2 = _parse_float_attr(shape_el, "param2", "b", field_label=f"{tname}.param2")
        p3 = _parse_float_attr(shape_el, "param3", "c", field_label=f"{tname}.param3")
        p4 = _parse_float_attr(shape_el, "param4", "d", field_label=f"{tname}.param4")
        params = sorted([p1, p2, p3, p4])
        return {"name": tname, "mf": "trapezoidal", "params": params, "complement": complement}

    if "gaussian" in sname:
        c = _parse_float_attr(shape_el, "param1", "c", "mean", field_label=f"{tname}.param1")
        sigma = abs(_parse_float_attr(shape_el, "param2", "sigma", "std", field_label=f"{tname}.param2"))
        if sigma <= 0.0:
            sigma = 1e-3
        return {"name": tname, "mf": "gaussian", "params": [c, sigma], "complement": complement}

    if "bell" in sname:
        a = abs(_parse_float_attr(shape_el, "param1", "a", field_label=f"{tname}.param1"))
        b = abs(_parse_float_attr(shape_el, "param2", "b", field_label=f"{tname}.param2"))
        c = _parse_float_attr(shape_el, "param3", "c", field_label=f"{tname}.param3")
        return {"name": tname, "mf": "bell", "params": [max(a, 1e-6), max(b, 1e-6), c], "complement": complement}

    if "sigmoid" in sname:
        a = _parse_float_attr(shape_el, "param1", "a", field_label=f"{tname}.param1")
        c = _parse_float_attr(shape_el, "param2", "c", field_label=f"{tname}.param2")
        return {"name": tname, "mf": "sigmoid", "params": [a, c], "complement": complement}

    if "singleton" in sname or "pointset" in sname:
        if shape_el.attrib:
            c = _parse_float_attr(shape_el, "param1", "value", "x", field_label=f"{tname}.param1")
        else:
            pts = [ch for ch in shape_el if _local_name(ch.tag).lower() == "point"]
            if not pts:
                raise ValidationError(f"Termo singleton/pointSet {tname!r} sem coordenadas.")
            c = _parse_float_attr(pts[0], "x", "param1", field_label=f"{tname}.point.x")
        return {"name": tname, "mf": "singleton", "params": [c], "complement": complement}

    if sname in ("zshape", "z_shape"):
        p1 = _parse_float_attr(shape_el, "param1", "a", field_label=f"{tname}.param1")
        p2 = _parse_float_attr(shape_el, "param2", "b", field_label=f"{tname}.param2")
        return {"name": tname, "mf": "z_shape", "params": sorted([p1, p2]), "complement": complement}

    if sname in ("sshape", "s_shape"):
        p1 = _parse_float_attr(shape_el, "param1", "a", field_label=f"{tname}.param1")
        p2 = _parse_float_attr(shape_el, "param2", "b", field_label=f"{tname}.param2")
        return {"name": tname, "mf": "s_shape", "params": sorted([p1, p2]), "complement": complement}

    if "linear" in sname:
        vals = []
        idx = 1
        while True:
            pa = _attr_ci(shape_el, f"param{idx}")
            if pa is None:
                break
            vals.append(float(pa))
            idx += 1
        if not vals:
            raise ValidationError(f"linearShape em {tname!r} sem parâmetros.")
        return {"name": tname, "type": "linear", "params": vals, "coefficients": vals}

    raise SchemaUnsupportedError(
        message=f"Formato de pertinência FML não suportado no perfil IEEE 1855-2016: {shape_el.tag!r}.",
        parameters={"term": tname, "shape_tag": _local_name(shape_el.tag)},
    )


def import_fml(
    xml_content: str | bytes,
    *,
    max_bytes: int = DEFAULT_MAX_FML_BYTES,
    max_depth: int = DEFAULT_MAX_XML_DEPTH,
    max_elements: int = DEFAULT_MAX_XML_ELEMENTS,
) -> Result:
    """Importa documento XML IEEE 1855-2016 FML (ou dialeto compatível `legacy_fuzzy_lab`) para `FuzzySystem`.

    Bloqueia estritamente XXE (`<!DOCTYPE`, `<!ENTITY`, `SYSTEM`, `PUBLIC`) com erro tipado
    `IMPORT_UNTRUSTED_CODE` (`T-FML-02`).
    """
    try:
        root = _check_xml_safety_and_limits(
            xml_content,
            max_bytes=max_bytes,
            max_depth=max_depth,
            max_elements=max_elements,
        )
        raw_text = xml_content.decode("utf-8") if isinstance(xml_content, bytes) else xml_content

        if _local_name(root.tag).lower() != "fuzzysystem":
            raise SchemaUnsupportedError(
                message=f"Elemento raiz FML esperado 'fuzzySystem', recebido {_local_name(root.tag)!r}.",
                parameters={"root_tag": _local_name(root.tag)},
            )

        sys_name = _attr_ci(root, "name", default="fml-imported") or "fml-imported"
        fml_profile = _attr_ci(root, "profile", default="IEEE-1855-2016") or "IEEE-1855-2016"

        # Detecta metadados opcionais em comentário (ControlLabMetadata ou FuzzyLabMetadata legado)
        ctrl_meta: dict[str, Any] = {}
        legacy_meta: dict[str, Any] = {}
        m_ctrl = re.search(r"<!--\s*ControlLabMetadata:\s*([\s\S]*?)-->", raw_text, flags=re.IGNORECASE)
        if m_ctrl:
            try:
                ctrl_meta = json.loads(m_ctrl.group(1).strip())
            except json.JSONDecodeError:
                ctrl_meta = {}
        m_leg = re.search(r"<!--\s*FuzzyLabMetadata:\s*([\s\S]*?)-->", raw_text, flags=re.IGNORECASE)
        if m_leg:
            try:
                legacy_meta = json.loads(m_leg.group(1).strip())
            except json.JSONDecodeError:
                legacy_meta = {}

        # Localiza knowledgeBase e ruleBase
        kb_el: ET.Element | None = None
        rb_el: ET.Element | None = None
        rb_kind: str = "mamdani"

        for child in root:
            cname = _local_name(child.tag).lower()
            if cname == "knowledgebase":
                kb_el = child
            elif cname in ("mamdanirulebase", "rulebase"):
                rb_el = child
                rb_kind = "mamdani"
            elif cname in ("tskrulebase", "tsrulebase", "takagisugenorulebase"):
                rb_el = child
                rb_kind = "ts"

        if kb_el is None:
            raise ValidationError("Documento FML não contém elemento <knowledgeBase>.")

        input_vars: list[dict[str, Any]] = []
        output_vars: list[dict[str, Any]] = []
        has_tsk_var = False

        for var_el in kb_el:
            vtag = _local_name(var_el.tag).lower()
            if vtag not in ("fuzzyvariable", "tskvariable"):
                continue
            is_tsk_var = vtag == "tskvariable"
            if is_tsk_var:
                has_tsk_var = True

            vname = _attr_ci(var_el, "name")
            if not vname:
                raise ValidationError("Variável FML sem atributo 'name'.")
            vtype = (_attr_ci(var_el, "type", default="input") or "input").strip().lower()
            lo = _parse_float_attr(var_el, "domainleft", "min", field_label=f"{vname}.domainleft")
            hi = _parse_float_attr(var_el, "domainright", "max", field_label=f"{vname}.domainright")
            scale = _attr_ci(var_el, "scale", "unit", default="") or ""

            terms: list[dict[str, Any]] = []
            for t_el in var_el:
                ttag = _local_name(t_el.tag).lower()
                if ttag in ("fuzzyterm", "tskterm"):
                    terms.append(_parse_fml_term(t_el, role=vtype, is_tsk=(is_tsk_var or ttag == "tskterm")))

            var_dict: dict[str, Any] = {
                "name": vname,
                "universe": [lo, hi],
                "terms": terms,
            }
            if scale:
                var_dict["scale"] = scale

            if vtype == "output":
                def_val = _attr_ci(var_el, "defaultvalue")
                if def_val is not None:
                    try:
                        var_dict["default_value"] = float(def_val)
                    except ValueError:
                        pass
                acc_attr = _attr_ci(var_el, "accumulation")
                if acc_attr:
                    var_dict["accumulation"] = _from_fml_or(acc_attr)
                defuzz_attr = _attr_ci(var_el, "defuzzifier", "combination")
                if defuzz_attr:
                    var_dict["defuzzifier"] = _from_fml_defuzz(
                        defuzz_attr,
                        inference_type="ts" if (is_tsk_var or rb_kind == "ts") else "mamdani",
                    )
                output_vars.append(var_dict)
            else:
                input_vars.append(var_dict)

        inference_type = "ts" if (rb_kind == "ts" or has_tsk_var) else "mamdani"

        ops: dict[str, str] = (
            {"and": "min", "or": "max", "implication": "min", "aggregation": "max", "defuzzification": "centroid"}
            if inference_type == "mamdani"
            else {"and": "prod", "or": "probor", "defuzzification": "wtaver"}
        )

        if output_vars:
            first_out = output_vars[0]
            if "accumulation" in first_out and inference_type == "mamdani":
                ops["aggregation"] = str(first_out["accumulation"])
            if "defuzzifier" in first_out:
                ops["defuzzification"] = str(first_out["defuzzifier"])

        rules_list: list[dict[str, Any]] = []
        if rb_el is not None:
            rb_and = _attr_ci(rb_el, "andmethod")
            rb_or = _attr_ci(rb_el, "ormethod")
            rb_act = _attr_ci(rb_el, "activationmethod")
            if rb_and:
                ops["and"] = _from_fml_and(rb_and, default=ops["and"])
            if rb_or:
                ops["or"] = _from_fml_or(rb_or, default=ops["or"])
            if rb_act and inference_type == "mamdani":
                ops["implication"] = _from_fml_and(rb_act, default=ops["implication"])

            in_var_names = {v["name"] for v in input_vars}
            out_var_names = {v["name"] for v in output_vars}
            in_var_ci = {v["name"].lower(): v["name"] for v in input_vars}
            out_var_ci = {v["name"].lower(): v["name"] for v in output_vars}

            for r_idx, r_el in enumerate(rb_el):
                if _local_name(r_el.tag).lower() not in ("rule", "tskrule"):
                    continue
                rname = _attr_ci(r_el, "name", default=f"R{r_idx + 1}") or f"R{r_idx + 1}"
                connector = (_attr_ci(r_el, "connector", default="and") or "and").strip().lower()
                w_str = _attr_ci(r_el, "weight", default="1.0") or "1.0"
                try:
                    weight = float(w_str)
                except ValueError as exc:
                    raise ValidationError(f"Peso inválido na regra {rname!r}: {w_str!r}") from exc

                ants: dict[str, str] = {}
                cons: dict[str, str] = {}

                for sub in r_el:
                    sub_name = _local_name(sub.tag).lower()
                    if sub_name == "antecedent":
                        for cl in sub.iter():
                            if _local_name(cl.tag).lower() == "clause":
                                v_txt = ""
                                t_txt = ""
                                for c_ch in cl:
                                    cn = _local_name(c_ch.tag).lower()
                                    if cn == "variable":
                                        v_txt = (c_ch.text or "").strip()
                                    elif cn == "term":
                                        t_txt = (c_ch.text or "").strip()
                                v_resolved = in_var_ci.get(v_txt.lower(), v_txt)
                                if v_resolved:
                                    ants[v_resolved] = t_txt
                    elif sub_name == "consequent":
                        for cl in sub.iter():
                            if _local_name(cl.tag).lower() == "clause":
                                v_txt = ""
                                t_txt = ""
                                for c_ch in cl:
                                    cn = _local_name(c_ch.tag).lower()
                                    if cn == "variable":
                                        v_txt = (c_ch.text or "").strip()
                                    elif cn == "term":
                                        t_txt = (c_ch.text or "").strip()
                                v_resolved = out_var_ci.get(v_txt.lower(), v_txt)
                                if v_resolved:
                                    cons[v_resolved] = t_txt

                rule_dict: dict[str, Any] = {
                    "name": rname,
                    "connector": connector,
                    "antecedents": ants,
                    "consequents": cons,
                    "weight": weight,
                }
                r_and_attr = _attr_ci(r_el, "andmethod")
                if r_and_attr:
                    rule_dict["and_method"] = _from_fml_and(r_and_attr, default=ops["and"])
                r_or_attr = _attr_ci(r_el, "ormethod")
                if r_or_attr:
                    rule_dict["or_method"] = _from_fml_or(r_or_attr, default=ops["or"])
                rules_list.append(rule_dict)

        prov: dict[str, Any] = {"source": "import_fml", "fml_profile": fml_profile}
        if legacy_meta:
            prov["legacy_fuzzy_lab_metadata"] = legacy_meta

        sys_id = str(ctrl_meta.get("id", sys_name))
        sys_rev = int(ctrl_meta.get("revision", 0))
        is_dyn = bool(ctrl_meta.get("is_dynamic_model", False))
        dyn_sem = ctrl_meta.get("dynamic_semantics")

        fuzzy_sys = FuzzySystem(
            inference_type=inference_type,
            input_variables=input_vars,
            output_variables=output_vars,
            rules=rules_list,
            operators=ops,
            fml_profile=fml_profile,
            is_dynamic_model=is_dyn,
            dynamic_semantics=dyn_sem if isinstance(dyn_sem, Mapping) else None,
            id=sys_id,
            revision=sys_rev,
            provenance=prov,
        )

        warnings_list: list[WarningItem] = []
        if legacy_meta:
            warnings_list.append(
                WarningItem(
                    code="LEGACY_FUZZY_LAB_METADATA_IMPORTED",
                    message="Metadados de compatibilidade do laboratório legado FuzzyLabWeb foram preservados em provenance.",
                    details={"app": legacy_meta.get("app", "FuzzyLabWeb")},
                )
            )

        return Result(
            status="warning" if warnings_list else "success",
            data={
                "fuzzy_system": fuzzy_sys.to_dict(),
                "system_id": fuzzy_sys.id,
                "inference_type": fuzzy_sys.inference_type,
                "legacy_metadata": legacy_meta if legacy_meta else None,
            },
            assumptions={
                "fml_profile": fuzzy_sys.fml_profile,
                "xxe_checked": True,
                "passive_import": True,
            },
            diagnostics={
                "n_inputs": len(fuzzy_sys.input_variables),
                "n_outputs": len(fuzzy_sys.output_variables),
                "n_rules": len(fuzzy_sys.rules),
            },
            provenance=build_provenance("control_lab.fuzzy.import_fml", model_revision=fuzzy_sys.revision),
            warnings=tuple(warnings_list),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={"xxe_checked": True, "passive_import": True},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.import_fml"),
            warnings=(),
            error=exc.to_typed_error(),
        )
