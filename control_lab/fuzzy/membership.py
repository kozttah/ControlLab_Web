"""Funções de pertinência e operadores lógicos fuzzy (CL-DIR-001 Seção 5.6, 13.7 e IEEE 1855-2016)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import ValidationError

_EPS = 1e-12

SUPPORTED_MF_TYPES: tuple[str, ...] = (
    "triangular",
    "trapezoidal",
    "gaussian",
    "bell",
    "sigmoid",
    "singleton",
    "z_shape",
    "s_shape",
    "linear",
    "constant",
)

MF_TYPE_ALIASES: dict[str, str] = {
    "tri": "triangular",
    "trimf": "triangular",
    "triangle": "triangular",
    "triangular": "triangular",
    "triangularshape": "triangular",
    "trap": "trapezoidal",
    "trapmf": "trapezoidal",
    "trapezoid": "trapezoidal",
    "trapezoidal": "trapezoidal",
    "trapezoidshape": "trapezoidal",
    "gauss": "gaussian",
    "gaussmf": "gaussian",
    "gaussian": "gaussian",
    "gaussianshape": "gaussian",
    "bell": "bell",
    "gbell": "bell",
    "gbellmf": "bell",
    "generalizedbell": "bell",
    "bellshape": "bell",
    "sig": "sigmoid",
    "sigmf": "sigmoid",
    "sigmoid": "sigmoid",
    "sigmoidshape": "sigmoid",
    "singleton": "singleton",
    "singletonshape": "singleton",
    "pointsetshape": "singleton",
    "z": "z_shape",
    "zmf": "z_shape",
    "z_shape": "z_shape",
    "zshape": "z_shape",
    "s": "s_shape",
    "smf": "s_shape",
    "s_shape": "s_shape",
    "sshape": "s_shape",
    "linear": "linear",
    "affine": "linear",
    "tsk_linear": "linear",
    "constant": "constant",
    "const": "constant",
    "zero_order": "constant",
}


def normalize_mf_type(raw_type: Any) -> str:
    """Normaliza nome/alias de função de pertinência para identificador canônico."""
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ValidationError(f"Tipo de função de pertinência inválido: {raw_type!r}")
    key = raw_type.strip().lower().replace("-", "_")
    if key in MF_TYPE_ALIASES:
        return MF_TYPE_ALIASES[key]
    raise ValidationError(
        message=f"Tipo de função de pertinência não suportado: {raw_type!r}.",
        parameters={"mf_type": raw_type, "supported": list(SUPPORTED_MF_TYPES)},
        next_step="Escolha um tipo em SUPPORTED_MF_TYPES (triangular, trapezoidal, gaussian, bell, sigmoid, singleton, z_shape, s_shape, linear, constant).",
    )


def _to_eval_array(x: Any) -> tuple[np.ndarray, bool]:
    if isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool):
        val = float(x)
        if not np.isfinite(val):
            raise ValidationError(f"Entrada x não finita na avaliação de pertinência: {x!r}")
        return np.array([val], dtype=np.float64), True
    arr = ensure_finite_float64(x, name="x")
    return arr, False


def _validate_params(params: Sequence[Any], expected_len: int, mf_name: str) -> tuple[float, ...]:
    if isinstance(params, (str, bytes)) or not isinstance(params, Sequence):
        raise ValidationError(f"Parâmetros de {mf_name} devem ser uma sequência numérica.")
    if len(params) != expected_len:
        raise ValidationError(
            message=f"Função {mf_name} requer exatamente {expected_len} parâmetro(s), recebido {len(params)}.",
            parameters={"mf_type": mf_name, "expected_len": expected_len, "actual_len": len(params)},
        )
    out: list[float] = []
    for idx, p in enumerate(params):
        if isinstance(p, bool) or not isinstance(p, (int, float, np.integer, np.floating)):
            raise ValidationError(f"Parâmetro {idx} de {mf_name} deve ser numérico, recebido {p!r}.")
        fp = float(p)
        if not np.isfinite(fp):
            raise ValidationError(f"Parâmetro {idx} de {mf_name} deve ser finito, recebido {p!r}.")
        out.append(fp)
    return tuple(out)


def triangular(x: Any, params: Sequence[Any]) -> float | np.ndarray:
    """Função de pertinência triangular [a, b, c] com suporte a ombros degenerados (a==b ou b==c)."""
    a, b, c = _validate_params(params, 3, "triangular")
    if not (a <= b <= c):
        raise ValidationError(
            message=f"Parâmetros triangulares devem satisfazer a <= b <= c, recebido [{a}, {b}, {c}].",
            parameters={"params": [a, b, c]},
        )
    arr, is_scalar = _to_eval_array(x)
    out = np.zeros_like(arr, dtype=np.float64)

    mask_in = (arr >= a) & (arr <= c)
    if np.any(mask_in):
        xv = arr[mask_in]
        res = np.zeros_like(xv, dtype=np.float64)
        at_peak = np.abs(xv - b) <= _EPS
        left_side = (xv < b) & (~at_peak)
        right_side = (xv > b) & (~at_peak)

        res[at_peak] = 1.0
        if np.any(left_side):
            if abs(b - a) <= _EPS:
                res[left_side] = 1.0
            else:
                res[left_side] = np.clip((xv[left_side] - a) / (b - a), 0.0, 1.0)
        if np.any(right_side):
            if abs(c - b) <= _EPS:
                res[right_side] = 1.0
            else:
                res[right_side] = np.clip((c - xv[right_side]) / (c - b), 0.0, 1.0)
        out[mask_in] = res

    return float(out[0]) if is_scalar else out


def trapezoidal(x: Any, params: Sequence[Any]) -> float | np.ndarray:
    """Função de pertinência trapezoidal [a, b, c, d] com suporte a ombros (a==b ou c==d)."""
    a, b, c, d = _validate_params(params, 4, "trapezoidal")
    if not (a <= b <= c <= d):
        raise ValidationError(
            message=f"Parâmetros trapezoidais devem satisfazer a <= b <= c <= d, recebido [{a}, {b}, {c}, {d}].",
            parameters={"params": [a, b, c, d]},
        )
    arr, is_scalar = _to_eval_array(x)
    out = np.zeros_like(arr, dtype=np.float64)

    mask_in = (arr >= a) & (arr <= d)
    if np.any(mask_in):
        xv = arr[mask_in]
        res = np.zeros_like(xv, dtype=np.float64)
        core = (xv >= b) & (xv <= c)
        left_side = xv < b
        right_side = xv > c

        res[core] = 1.0
        if np.any(left_side):
            if abs(b - a) <= _EPS:
                res[left_side] = 1.0
            else:
                res[left_side] = np.clip((xv[left_side] - a) / (b - a), 0.0, 1.0)
        if np.any(right_side):
            if abs(d - c) <= _EPS:
                res[right_side] = 1.0
            else:
                res[right_side] = np.clip((d - xv[right_side]) / (d - c), 0.0, 1.0)
        out[mask_in] = res

    return float(out[0]) if is_scalar else out


def gaussian(x: Any, params: Sequence[Any]) -> float | np.ndarray:
    """Função de pertinência gaussiana IEEE 1855-2016: exp(-0.5 * ((x - c) / sigma)^2), params=[c, sigma]."""
    c, sigma = _validate_params(params, 2, "gaussian")
    if sigma <= 0.0:
        raise ValidationError(
            message=f"Parâmetro sigma da função gaussiana deve ser estritamente positivo (> 0), recebido {sigma}.",
            parameters={"c": c, "sigma": sigma},
        )
    arr, is_scalar = _to_eval_array(x)
    q = (arr - c) / sigma
    out = np.exp(-0.5 * np.square(q))
    out = np.clip(out, 0.0, 1.0)
    return float(out[0]) if is_scalar else out


def bell(x: Any, params: Sequence[Any]) -> float | np.ndarray:
    """Função Generalized Bell: 1 / (1 + |((x - c) / a)|^(2b)), params=[a, b, c]."""
    a, b, c = _validate_params(params, 3, "bell")
    if a <= 0.0:
        raise ValidationError(
            message=f"Parâmetro de largura 'a' da função bell deve ser > 0, recebido {a}.",
            parameters={"a": a, "b": b, "c": c},
        )
    if b <= 0.0:
        raise ValidationError(
            message=f"Parâmetro de inclinação 'b' da função bell deve ser > 0, recebido {b}.",
            parameters={"a": a, "b": b, "c": c},
        )
    arr, is_scalar = _to_eval_array(x)
    dist = np.abs((arr - c) / a)
    with np.errstate(over="ignore"):
        powered = np.power(dist, 2.0 * b)
        out = 1.0 / (1.0 + powered)
    out = np.clip(out, 0.0, 1.0)
    return float(out[0]) if is_scalar else out


def sigmoid(x: Any, params: Sequence[Any]) -> float | np.ndarray:
    """Função sigmoidal: 1 / (1 + exp(-a * (x - c))), params=[a, c]."""
    a, c = _validate_params(params, 2, "sigmoid")
    arr, is_scalar = _to_eval_array(x)
    z = np.clip(-a * (arr - c), -500.0, 500.0)
    out = 1.0 / (1.0 + np.exp(z))
    out = np.clip(out, 0.0, 1.0)
    return float(out[0]) if is_scalar else out


def singleton(x: Any, params: Sequence[Any], *, atol: float = 1e-9) -> float | np.ndarray:
    """Função de pertinência singleton em c: 1.0 se |x - c| <= atol, caso contrário 0.0."""
    (c,) = _validate_params(params, 1, "singleton")
    arr, is_scalar = _to_eval_array(x)
    out = np.where(np.abs(arr - c) <= atol, 1.0, 0.0).astype(np.float64)
    return float(out[0]) if is_scalar else out


def z_shape(x: Any, params: Sequence[Any]) -> float | np.ndarray:
    """Função spline Z-shape decrescente de 1 (x <= a) até 0 (x >= b), params=[a, b]."""
    a, b = _validate_params(params, 2, "z_shape")
    if a > b:
        raise ValidationError(
            message=f"Parâmetros de z_shape devem satisfazer a <= b, recebido [{a}, {b}].",
            parameters={"params": [a, b]},
        )
    arr, is_scalar = _to_eval_array(x)
    if abs(b - a) <= _EPS:
        out = np.where(arr <= a, 1.0, 0.0).astype(np.float64)
        return float(out[0]) if is_scalar else out

    out = np.zeros_like(arr, dtype=np.float64)
    mid = 0.5 * (a + b)
    span = b - a
    m1 = arr <= a
    m2 = (arr > a) & (arr <= mid)
    m3 = (arr > mid) & (arr < b)
    out[m1] = 1.0
    out[m2] = 1.0 - 2.0 * np.square((arr[m2] - a) / span)
    out[m3] = 2.0 * np.square((arr[m3] - b) / span)
    out = np.clip(out, 0.0, 1.0)
    return float(out[0]) if is_scalar else out


def s_shape(x: Any, params: Sequence[Any]) -> float | np.ndarray:
    """Função spline S-shape crescente de 0 (x <= a) até 1 (x >= b), params=[a, b]."""
    a, b = _validate_params(params, 2, "s_shape")
    if a > b:
        raise ValidationError(
            message=f"Parâmetros de s_shape devem satisfazer a <= b, recebido [{a}, {b}].",
            parameters={"params": [a, b]},
        )
    arr, is_scalar = _to_eval_array(x)
    if abs(b - a) <= _EPS:
        out = np.where(arr >= b, 1.0, 0.0).astype(np.float64)
        return float(out[0]) if is_scalar else out

    out = np.zeros_like(arr, dtype=np.float64)
    mid = 0.5 * (a + b)
    span = b - a
    m2 = (arr > a) & (arr <= mid)
    m3 = (arr > mid) & (arr < b)
    m4 = arr >= b
    out[m2] = 2.0 * np.square((arr[m2] - a) / span)
    out[m3] = 1.0 - 2.0 * np.square((arr[m3] - b) / span)
    out[m4] = 1.0
    out = np.clip(out, 0.0, 1.0)
    return float(out[0]) if is_scalar else out


def linear(
    inputs: Sequence[float] | np.ndarray | float,
    params: Sequence[Any],
    *,
    bias_last: bool = True,
) -> float:
    """Avalia consequente Takagi-Sugeno afim (1ª ordem) ou constante (0ª ordem).

    Convenções aceitas:
    - Se `len(params) == 1`: consequente constante (0ª ordem) `y = c_0`.
    - Se `len(params) == n_inputs + 1`:
      - `bias_last=True` (padrão IEEE 1855 / ANFIS): `y = p_1*x_1 + ... + p_n*x_n + p_0` onde `params = [p_1, ..., p_n, p_0]`.
      - `bias_last=False`: `params = [p_0, p_1, ..., p_n]`.
    - Se `len(params) == n_inputs`: linear homogêneo sem termo constante (`p_0 = 0`).
    """
    if isinstance(inputs, (int, float, np.integer, np.floating)) and not isinstance(inputs, bool):
        x_vec = np.array([float(inputs)], dtype=np.float64)
    else:
        x_vec = ensure_finite_float64(inputs, ndim=1, name="inputs")

    if isinstance(params, (str, bytes)) or not isinstance(params, Sequence) or len(params) < 1:
        raise ValidationError("Parâmetros de consequente linear TS devem ser sequência não vazia.")
    p_vec = ensure_finite_float64(params, ndim=1, name="linear_params")
    n_in = x_vec.size

    if p_vec.size == 1:
        return float(p_vec[0])
    if p_vec.size == n_in + 1:
        if bias_last:
            return float(np.dot(p_vec[:-1], x_vec) + p_vec[-1])
        return float(p_vec[0] + np.dot(p_vec[1:], x_vec))
    if p_vec.size == n_in:
        return float(np.dot(p_vec, x_vec))

    raise ValidationError(
        message=(
            f"Comprimento de parâmetros TS linear ({p_vec.size}) incompatível com número de entradas ({n_in}). "
            f"Esperado 1 (constante), {n_in} (sem bias) ou {n_in + 1} (afim)."
        ),
        parameters={"n_params": int(p_vec.size), "n_inputs": int(n_in)},
    )


def extract_term_spec(term: Mapping[str, Any]) -> tuple[str, list[float], bool]:
    """Extrai `(mf_type, params, complement)` de um dicionário de termo de `FuzzySystem`."""
    if not isinstance(term, Mapping):
        raise ValidationError("Termo fuzzy deve ser Mapping.")
    complement = bool(term.get("complement", False))

    raw_type = term.get("mf") or term.get("type")
    raw_params = term.get("params")
    if raw_params is None and "coefficients" in term:
        raw_params = term.get("coefficients")

    if isinstance(raw_type, Mapping):
        nested = raw_type
        raw_type = nested.get("type") or nested.get("mf") or nested.get("shape")
        if raw_params is None:
            raw_params = nested.get("params") or nested.get("coefficients")

    if raw_type is None:
        if "coefficients" in term:
            coeffs = term["coefficients"]
            if isinstance(coeffs, (int, float, np.integer, np.floating)):
                return "constant", [float(coeffs)], complement
            c_arr = ensure_finite_float64(coeffs, ndim=1, name="coefficients")
            return ("constant" if c_arr.size == 1 else "linear"), c_arr.tolist(), complement
        raise ValidationError(f"Termo {term.get('name', '?')!r} não declara tipo ('mf' ou 'type').")

    mf_type = normalize_mf_type(raw_type)
    if raw_params is None:
        if "value" in term:
            raw_params = [term["value"]]
        else:
            raise ValidationError(f"Termo {term.get('name', '?')!r} ({mf_type}) não possui 'params' ou 'coefficients'.")

    if isinstance(raw_params, (int, float, np.integer, np.floating)) and not isinstance(raw_params, bool):
        params_list = [float(raw_params)]
    else:
        p_arr = ensure_finite_float64(raw_params, ndim=1, name=f"term[{term.get('name', '?')}].params")
        params_list = [float(v) for v in p_arr.tolist()]

    return mf_type, params_list, complement


def evaluate_mf(
    mf_type: str,
    params: Sequence[Any],
    x: Any,
    *,
    complement: bool = False,
) -> float | np.ndarray:
    """Avalia uma função de pertinência de entrada/saída Mamdani pelo nome ou alias."""
    canonical = normalize_mf_type(mf_type)
    if canonical == "triangular":
        val = triangular(x, params)
    elif canonical == "trapezoidal":
        val = trapezoidal(x, params)
    elif canonical == "gaussian":
        val = gaussian(x, params)
    elif canonical == "bell":
        val = bell(x, params)
    elif canonical == "sigmoid":
        val = sigmoid(x, params)
    elif canonical == "singleton":
        val = singleton(x, params)
    elif canonical == "z_shape":
        val = z_shape(x, params)
    elif canonical == "s_shape":
        val = s_shape(x, params)
    elif canonical == "constant":
        (c_val,) = _validate_params(params, 1, "constant")
        arr, is_scalar = _to_eval_array(x)
        out = np.full_like(arr, np.clip(c_val, 0.0, 1.0), dtype=np.float64)
        val = float(out[0]) if is_scalar else out
    else:
        raise ValidationError(
            message=f"Tipo {canonical!r} não é função de pertinência escalar avaliável em x.",
            parameters={"mf_type": canonical},
        )

    if complement:
        return (1.0 - val) if isinstance(val, float) else (1.0 - val)
    return val


def apply_t_norm(a: Any, b: Any, method: str = "min") -> float | np.ndarray:
    """Aplica T-norma (conjunção / implicação): min, prod ou einstein_prod (eprod)."""
    key = str(method or "min").strip().lower()
    a_clip = np.clip(a, 0.0, 1.0)
    b_clip = np.clip(b, 0.0, 1.0)
    if key in ("min", "minimum"):
        res = np.minimum(a_clip, b_clip)
    elif key in ("prod", "product", "algebraic_product"):
        res = a_clip * b_clip
    elif key in ("eprod", "eins", "einstein", "einstein_prod"):
        denom = np.maximum(_EPS, 2.0 - (a_clip + b_clip - a_clip * b_clip))
        res = (a_clip * b_clip) / denom
    elif key in ("lukasiewicz", "bounded_diff"):
        res = np.maximum(0.0, a_clip + b_clip - 1.0)
    else:
        raise ValidationError(
            message=f"Operador T-norma desconhecido: {method!r}.",
            parameters={"method": method, "allowed": ["min", "prod", "eprod", "lukasiewicz"]},
        )
    if isinstance(a, (int, float, np.floating)) and isinstance(b, (int, float, np.floating)):
        return float(res)
    return np.asarray(res, dtype=np.float64)


def apply_s_norm(a: Any, b: Any, method: str = "max") -> float | np.ndarray:
    """Aplica S-norma (disjunção / agregação): max, prob_or (probor) ou einstein_sum (esum)."""
    key = str(method or "max").strip().lower()
    a_clip = np.clip(a, 0.0, 1.0)
    b_clip = np.clip(b, 0.0, 1.0)
    if key in ("max", "maximum"):
        res = np.maximum(a_clip, b_clip)
    elif key in ("prob", "probor", "prob_or", "algebraic_sum"):
        res = a_clip + b_clip - a_clip * b_clip
    elif key in ("esum", "eins", "einstein", "einstein_sum"):
        denom = np.maximum(_EPS, 1.0 + a_clip * b_clip)
        res = (a_clip + b_clip) / denom
    elif key in ("sum", "bounded_sum", "lukasiewicz"):
        res = np.minimum(1.0, a_clip + b_clip)
    else:
        raise ValidationError(
            message=f"Operador S-norma desconhecido: {method!r}.",
            parameters={"method": method, "allowed": ["max", "prob_or", "probor", "esum", "bounded_sum"]},
        )
    if isinstance(a, (int, float, np.floating)) and isinstance(b, (int, float, np.floating)):
        return float(res)
    return np.asarray(res, dtype=np.float64)
