"""Helpers canônicos de tensores e validação dimensional/esquema (CL-DIR-001 Seção 4.1 e tensor.schema.json)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.diagnostics import (
    DimensionMismatchError,
    SchemaUnsupportedError,
    UnsupportedModelError,
    ValidationError,
    ensure_json_finite,
)

_SCHEMA_VERSION_RE = re.compile(r"^1\.0\.\d+$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")

_REAL_DTYPE_MAP: dict[str, np.dtype[Any]] = {
    "float64": np.dtype(np.float64),
    "float32": np.dtype(np.float32),
    "int64": np.dtype(np.int64),
    "int32": np.dtype(np.int32),
    "bool": np.dtype(np.bool_),
}

_COMPLEX_DTYPE_MAP: dict[str, np.dtype[Any]] = {
    "complex128": np.dtype(np.complex128),
    "complex64": np.dtype(np.complex64),
}


def _check_nested_no_bad_scalars(obj: Any, *, allow_bool: bool = False) -> None:
    if isinstance(obj, np.ndarray):
        if not allow_bool and np.issubdtype(obj.dtype, np.bool_):
            raise ValidationError("Valores booleanos não são permitidos em matriz/vetor numérico float64.")
        if np.issubdtype(obj.dtype, np.complexfloating):
            raise ValidationError("Valores complexos não são permitidos em matriz/vetor float64.")
        if obj.dtype == object:
            for item in obj.flat:
                _check_nested_no_bad_scalars(item, allow_bool=allow_bool)
        return
    if isinstance(obj, bool) or isinstance(obj, np.bool_):
        if not allow_bool:
            raise ValidationError("Valor booleano não é permitido em matriz/vetor numérico.")
        return
    if isinstance(obj, (str, bytes, Mapping)) or obj is None:
        raise ValidationError(f"Elemento inválido em tensor numérico: {type(obj).__name__}")
    if isinstance(obj, (complex, np.complexfloating)):
        raise ValidationError("Valor complexo não é permitido em tensor real float64.")
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _check_nested_no_bad_scalars(item, allow_bool=allow_bool)
        return
    if isinstance(obj, (int, float, np.integer, np.floating)):
        return
    raise ValidationError(f"Elemento não numérico em tensor: {type(obj).__name__}")


def ensure_finite_float64(
    value: Any,
    *,
    shape: tuple[int, ...] | None = None,
    ndim: int | None = None,
    name: str = "array",
    readonly: bool = False,
) -> np.ndarray:
    """Converte entrada numérica em np.ndarray float64 finito, validando shape e ndim."""
    if value is None or isinstance(value, (str, bytes, Mapping)):
        raise ValidationError(
            message=f"{name} deve ser um array numérico, recebido {type(value).__name__}.",
            parameters={"name": name, "type": type(value).__name__},
        )
    _check_nested_no_bad_scalars(value, allow_bool=False)
    try:
        arr = np.array(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            message=f"Não foi possível converter {name} para float64: {exc}",
            parameters={"name": name},
        ) from exc

    if not np.all(np.isfinite(arr)):
        raise ValidationError(
            message=f"{name} contém valores não finitos (NaN ou Inf).",
            parameters={"name": name},
            next_step="Substitua NaN/Inf por números reais finitos.",
        )

    if ndim is not None and arr.ndim != ndim:
        raise DimensionMismatchError(
            message=f"{name} deve ter {ndim} dimensões, recebido {arr.ndim}D (shape={arr.shape}).",
            parameters={"name": name, "expected_ndim": ndim, "actual_shape": list(arr.shape)},
        )

    if shape is not None and arr.shape != tuple(shape):
        raise DimensionMismatchError(
            message=f"{name} deve ter shape {tuple(shape)}, recebido {arr.shape}.",
            parameters={"name": name, "expected_shape": list(shape), "actual_shape": list(arr.shape)},
        )

    if readonly:
        arr.setflags(write=False)
    return arr


def array_to_tensor(
    arr: Any,
    *,
    dtype: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    """Serializa array NumPy/array-like no formato canônico de tensor.schema.json."""
    if arr is None or isinstance(arr, (str, bytes, Mapping)):
        raise ValidationError(f"Entrada inválida para tensor: {type(arr).__name__}")

    arr_np = np.asarray(arr)
    if arr_np.dtype == object:
        raise ValidationError("Array irregular (ragged/object) não é suportado como tensor.")
    if arr_np.ndim < 1:
        raise ValidationError(
            message="Tensor canônico requer ndim >= 1 conforme tensor.schema.json.",
            parameters={"ndim": arr_np.ndim},
        )

    if order is None:
        resolved_order = "F" if (arr_np.flags.f_contiguous and not arr_np.flags.c_contiguous) else "C"
    else:
        if order not in ("C", "F"):
            raise ValidationError(f"Ordem de memória inválida: {order!r}. Use 'C' ou 'F'.")
        resolved_order = order

    if dtype is None:
        if arr_np.dtype == np.float64:
            resolved_dtype = "float64"
        elif arr_np.dtype == np.float32:
            resolved_dtype = "float32"
        elif arr_np.dtype == np.int64:
            resolved_dtype = "int64"
        elif arr_np.dtype == np.int32:
            resolved_dtype = "int32"
        elif arr_np.dtype == np.bool_:
            resolved_dtype = "bool"
        elif arr_np.dtype == np.complex128:
            resolved_dtype = "complex128"
        elif arr_np.dtype == np.complex64:
            resolved_dtype = "complex64"
        elif np.issubdtype(arr_np.dtype, np.floating):
            resolved_dtype = "float64"
        elif np.issubdtype(arr_np.dtype, np.integer):
            resolved_dtype = "int64"
        elif np.issubdtype(arr_np.dtype, np.complexfloating):
            resolved_dtype = "complex128"
        else:
            raise ValidationError(f"Dtype não suportado em tensor: {arr_np.dtype}")
    else:
        if dtype not in _REAL_DTYPE_MAP and dtype not in _COMPLEX_DTYPE_MAP:
            raise ValidationError(f"Dtype de tensor inválido: {dtype!r}")
        resolved_dtype = dtype

    if resolved_dtype in _COMPLEX_DTYPE_MAP:
        c_arr = np.asarray(arr_np, dtype=_COMPLEX_DTYPE_MAP[resolved_dtype])
        if not (np.all(np.isfinite(c_arr.real)) and np.all(np.isfinite(c_arr.imag))):
            raise ValidationError("Tensor complexo contém NaN ou Inf.")
        return {
            "shape": [int(d) for d in c_arr.shape],
            "dtype": resolved_dtype,
            "order": resolved_order,
            "real": [float(v) for v in c_arr.real.ravel(order=resolved_order).tolist()],
            "imag": [float(v) for v in c_arr.imag.ravel(order=resolved_order).tolist()],
        }

    # Real tensor
    if resolved_dtype in ("float64", "float32") and np.issubdtype(arr_np.dtype, np.bool_):
        raise ValidationError("Valores booleanos não podem ser serializados como tensor float.")
    if np.issubdtype(arr_np.dtype, np.complexfloating):
        raise ValidationError("Tensor real não pode receber números complexos.")

    r_arr = np.asarray(arr_np, dtype=_REAL_DTYPE_MAP[resolved_dtype])
    if np.issubdtype(r_arr.dtype, np.floating) and not np.all(np.isfinite(r_arr)):
        raise ValidationError("Tensor real contém NaN ou Inf.")

    flat = r_arr.ravel(order=resolved_order)
    if resolved_dtype in ("float64", "float32"):
        data_list: list[Any] = [float(v) for v in flat.tolist()]
    else:
        data_list = [int(v) for v in flat.tolist()]

    return {
        "shape": [int(d) for d in r_arr.shape],
        "dtype": resolved_dtype,
        "order": resolved_order,
        "data": data_list,
    }


def tensor_to_array(
    tensor: Mapping[str, Any],
    *,
    expected_ndim: int | None = None,
    expected_shape: tuple[int, ...] | None = None,
    dtype: str | None = None,
    strict_dtype: bool = False,
    readonly: bool = False,
) -> np.ndarray:
    """Reconstrói np.ndarray a partir de um dicionário compatível com tensor.schema.json."""
    if not isinstance(tensor, Mapping):
        raise ValidationError(f"Tensor deve ser um dict/Mapping, recebido {type(tensor).__name__}.")

    if "buffer_ref" in tensor:
        raise UnsupportedModelError(
            "BufferTensorRef não pode ser materializado diretamente sem resolução do buffer.",
            parameters={"buffer_ref": tensor.get("buffer_ref")},
        )

    if "real" in tensor and "imag" in tensor and "shape" not in tensor:
        arr = pair_to_complex(tensor)
        if expected_ndim is not None and arr.ndim != expected_ndim:
            raise DimensionMismatchError(
                f"Tensor complexo deve ter {expected_ndim}D, recebido {arr.ndim}D."
            )
        if expected_shape is not None and arr.shape != tuple(expected_shape):
            raise DimensionMismatchError(
                f"Tensor complexo deve ter shape {expected_shape}, recebido {arr.shape}."
            )
        if readonly:
            arr.setflags(write=False)
        return arr

    for req in ("shape", "dtype", "order"):
        if req not in tensor:
            raise ValidationError(f"Campo obrigatório ausente em tensor: {req!r}")

    raw_shape = tensor["shape"]
    if not isinstance(raw_shape, (list, tuple)) or len(raw_shape) < 1:
        raise ValidationError("Tensor.shape deve ser lista não vazia de inteiros >= 0.")
    shape: list[int] = []
    for dim in raw_shape:
        if isinstance(dim, bool) or not isinstance(dim, int) or dim < 0:
            raise ValidationError(f"Dimensão inválida em tensor.shape: {dim!r}")
        shape.append(dim)
    shape_tuple = tuple(shape)

    order = tensor["order"]
    if order not in ("C", "F"):
        raise ValidationError(f"Tensor.order inválido: {order!r}")

    t_dtype = tensor["dtype"]
    if not isinstance(t_dtype, str):
        raise ValidationError("Tensor.dtype deve ser string.")
    if strict_dtype and dtype is not None and t_dtype != dtype:
        raise ValidationError(
            message=f"Tensor.dtype esperado {dtype!r}, recebido {t_dtype!r}.",
            parameters={"expected_dtype": dtype, "actual_dtype": t_dtype},
        )

    expected_len = math.prod(shape_tuple)

    if t_dtype in _COMPLEX_DTYPE_MAP:
        allowed_keys = {"shape", "dtype", "order", "real", "imag"}
        if set(tensor.keys()) != allowed_keys:
            raise ValidationError(
                f"Chaves inválidas em ComplexTensor: {sorted(set(tensor.keys()) ^ allowed_keys)}"
            )
        real_raw = tensor["real"]
        imag_raw = tensor["imag"]
        if not isinstance(real_raw, (list, tuple)) or not isinstance(imag_raw, (list, tuple)):
            raise ValidationError("Campos real/imag de ComplexTensor devem ser listas.")
        if len(real_raw) != expected_len or len(imag_raw) != expected_len:
            raise DimensionMismatchError(
                message=f"Comprimento de dados ({len(real_raw)}, {len(imag_raw)}) incompatível com shape {shape_tuple}.",
                parameters={"shape": list(shape_tuple), "expected_len": expected_len},
            )
        real_arr = ensure_finite_float64(real_raw, ndim=1, name="tensor.real")
        imag_arr = ensure_finite_float64(imag_raw, ndim=1, name="tensor.imag")
        target_np_dtype = _COMPLEX_DTYPE_MAP[dtype if (dtype in _COMPLEX_DTYPE_MAP) else t_dtype]
        arr = (real_arr + 1j * imag_arr).astype(target_np_dtype).reshape(shape_tuple, order=order)
    elif t_dtype in _REAL_DTYPE_MAP:
        allowed_keys = {"shape", "dtype", "order", "data"}
        if set(tensor.keys()) != allowed_keys:
            raise ValidationError(
                f"Chaves inválidas em RealTensor: {sorted(set(tensor.keys()) ^ allowed_keys)}"
            )
        data_raw = tensor["data"]
        if not isinstance(data_raw, (list, tuple)):
            raise ValidationError("Campo data do tensor deve ser uma lista.")
        if len(data_raw) != expected_len:
            raise DimensionMismatchError(
                message=f"Comprimento de tensor.data ({len(data_raw)}) incompatível com shape {shape_tuple} (esperado {expected_len}).",
                parameters={"shape": list(shape_tuple), "actual_len": len(data_raw), "expected_len": expected_len},
            )
        if t_dtype == "bool":
            for idx, v in enumerate(data_raw):
                if isinstance(v, (str, bytes)) or v is None:
                    raise ValidationError(f"Valor inválido em tensor bool[{idx}]: {v!r}")
                if not isinstance(v, (int, bool)) or v not in (0, 1, True, False):
                    raise ValidationError(f"Valor inválido em tensor bool[{idx}]: {v!r}")
            arr = np.array(data_raw, dtype=np.bool_).reshape(shape_tuple, order=order)
        elif t_dtype in ("int64", "int32"):
            for idx, v in enumerate(data_raw):
                if isinstance(v, bool) or not isinstance(v, (int, np.integer)):
                    raise ValidationError(f"Valor inteiro esperado em tensor[{idx}], recebido {v!r}")
            np_dt = _REAL_DTYPE_MAP[dtype if (dtype in _REAL_DTYPE_MAP) else t_dtype]
            arr = np.array(data_raw, dtype=np_dt).reshape(shape_tuple, order=order)
        else:
            flat_f = ensure_finite_float64(data_raw, ndim=1, name="tensor.data")
            target_dt = _REAL_DTYPE_MAP[dtype if (dtype in _REAL_DTYPE_MAP) else t_dtype]
            arr = flat_f.astype(target_dt, copy=False).reshape(shape_tuple, order=order)
    else:
        raise ValidationError(f"Dtype desconhecido em tensor: {t_dtype!r}")

    if expected_ndim is not None and arr.ndim != expected_ndim:
        raise DimensionMismatchError(
            message=f"Tensor deve ter {expected_ndim} dimensões, recebido {arr.ndim}D (shape={arr.shape}).",
            parameters={"expected_ndim": expected_ndim, "actual_shape": list(arr.shape)},
        )
    if expected_shape is not None and arr.shape != tuple(expected_shape):
        raise DimensionMismatchError(
            message=f"Tensor deve ter shape {tuple(expected_shape)}, recebido {arr.shape}.",
            parameters={"expected_shape": list(expected_shape), "actual_shape": list(arr.shape)},
        )

    if readonly:
        arr.setflags(write=False)
    return arr


def complex_to_pair(values: Any) -> dict[str, list[float]]:
    """Converte vetor complexo 1D no par explícito {'real': [...], 'imag': [...]}."""
    if values is None or isinstance(values, (str, bytes, Mapping)):
        raise ValidationError("Entrada inválida para complex_to_pair.")
    arr = np.asarray(values, dtype=np.complex128)
    if arr.ndim != 1:
        raise DimensionMismatchError(
            f"complex_to_pair espera vetor 1D, recebido {arr.ndim}D (shape={arr.shape})."
        )
    if not (np.all(np.isfinite(arr.real)) and np.all(np.isfinite(arr.imag))):
        raise ValidationError("Vetor complexo contém NaN ou Inf.")
    return {
        "real": [float(v) for v in arr.real.tolist()],
        "imag": [float(v) for v in arr.imag.tolist()],
    }


def pair_to_complex(pair: Mapping[str, Any]) -> np.ndarray:
    """Reconstrói vetor np.ndarray complex128 a partir de {'real': [...], 'imag': [...]}."""
    if not isinstance(pair, Mapping):
        raise ValidationError("Par complexo deve ser um mapeamento (dict).")
    if set(pair.keys()) != {"real", "imag"}:
        raise ValidationError(
            f"Par complexo deve conter exatamente chaves 'real' e 'imag', recebido {sorted(pair.keys())}."
        )
    real_arr = ensure_finite_float64(pair["real"], ndim=1, name="pair.real")
    imag_arr = ensure_finite_float64(pair["imag"], ndim=1, name="pair.imag")
    if real_arr.shape != imag_arr.shape:
        raise DimensionMismatchError(
            f"Comprimento de real ({real_arr.shape[0]}) difere de imag ({imag_arr.shape[0]})."
        )
    return (real_arr + 1j * imag_arr).astype(np.complex128)


# ---------------------------------------------------------------------------
# Validadores auxiliares compartilhados para modelos canônicos
# ---------------------------------------------------------------------------


def validate_schema_version(schema_version: Any, *, field_name: str = "schema_version") -> str:
    if not isinstance(schema_version, str) or not _SCHEMA_VERSION_RE.match(schema_version):
        raise SchemaUnsupportedError(
            message=f"{field_name} não suportada: {schema_version!r} (esperado 1.0.x).",
            parameters={"schema_version": schema_version},
            next_step="Atualize ou migre o objeto para schema_version compatível com 1.0.x.",
        )
    return schema_version


def validate_revision(revision: Any, *, field_name: str = "revision") -> int:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValidationError(
            message=f"{field_name} deve ser inteiro >= 0, recebido {revision!r}.",
            parameters={field_name: revision},
        )
    return revision


def validate_non_empty_str(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(
            message=f"{field_name} deve ser uma string não vazia.",
            parameters={field_name: value},
        )
    return value


def validate_sample_time(dt: Any) -> float | None:
    if dt is None:
        return None
    if isinstance(dt, bool) or not isinstance(dt, (int, float, np.integer, np.floating)):
        raise ValidationError(
            message=f"dt deve ser None (contínuo) ou número real > 0 (discreto), recebido {dt!r}.",
            parameters={"dt": repr(dt)},
        )
    fdt = float(dt)
    if not math.isfinite(fdt) or fdt <= 0.0:
        raise ValidationError(
            message=f"dt discreto deve ser finito e estritamente positivo (> 0), recebido {fdt!r}.",
            parameters={"dt": repr(fdt)},
        )
    return fdt


def validate_name_list(
    names: Sequence[str] | None,
    expected_len: int,
    *,
    prefix: str,
    field_name: str,
) -> tuple[str, ...]:
    if names is None:
        return tuple(f"{prefix}{i + 1}" for i in range(expected_len))
    if isinstance(names, (str, bytes)) or not isinstance(names, Sequence):
        raise ValidationError(f"{field_name} deve ser uma sequência de strings.")
    if len(names) != expected_len:
        raise DimensionMismatchError(
            message=f"{field_name} deve ter comprimento {expected_len}, recebido {len(names)}.",
            parameters={"field": field_name, "expected_len": expected_len, "actual_len": len(names)},
        )
    out: list[str] = []
    for idx, item in enumerate(names):
        if not isinstance(item, str) or len(item) == 0:
            raise ValidationError(f"{field_name}[{idx}] deve ser string não vazia.")
        out.append(item)
    return tuple(out)


def validate_units_dict(
    units: Mapping[str, Any] | None,
    *,
    n_states: int | None = None,
    n_inputs: int | None = None,
    n_outputs: int | None = None,
    require_io: bool = True,
) -> dict[str, Any]:
    if units is None:
        base: dict[str, Any] = {"time": "s"}
        if n_inputs is not None:
            base["inputs"] = [""] * n_inputs
        if n_outputs is not None:
            base["outputs"] = [""] * n_outputs
        return base

    if not isinstance(units, Mapping):
        raise ValidationError("units deve ser um dicionário (Mapping).")

    cleaned = ensure_json_finite(dict(units), path="$.units")
    if "time" not in cleaned:
        cleaned["time"] = "s"
    if not isinstance(cleaned["time"], str) or len(cleaned["time"]) == 0:
        raise ValidationError("units.time deve ser uma string não vazia.")

    if "inputs" in cleaned:
        if not isinstance(cleaned["inputs"], list) or not all(isinstance(u, str) for u in cleaned["inputs"]):
            raise ValidationError("units.inputs deve ser uma lista de strings.")
        if n_inputs is not None and len(cleaned["inputs"]) != n_inputs:
            raise DimensionMismatchError(
                f"units.inputs deve ter tamanho {n_inputs}, recebido {len(cleaned['inputs'])}."
            )
    elif require_io and n_inputs is not None:
        cleaned["inputs"] = [""] * n_inputs

    if "outputs" in cleaned:
        if not isinstance(cleaned["outputs"], list) or not all(isinstance(u, str) for u in cleaned["outputs"]):
            raise ValidationError("units.outputs deve ser uma lista de strings.")
        if n_outputs is not None and len(cleaned["outputs"]) != n_outputs:
            raise DimensionMismatchError(
                f"units.outputs deve ter tamanho {n_outputs}, recebido {len(cleaned['outputs'])}."
            )
    elif require_io and n_outputs is not None:
        cleaned["outputs"] = [""] * n_outputs

    if "states" in cleaned:
        if not isinstance(cleaned["states"], list) or not all(isinstance(u, str) for u in cleaned["states"]):
            raise ValidationError("units.states deve ser uma lista de strings.")
        if n_states is not None and len(cleaned["states"]) != n_states:
            raise DimensionMismatchError(
                f"units.states deve ter tamanho {n_states}, recebido {len(cleaned['states'])}."
            )

    return cleaned


def validate_sha256_hex(value: Any, *, field_name: str = "content_hash") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise ValidationError(f"{field_name} deve ser hash SHA-256 hexadecimal de 64 caracteres.")
    return value.lower()


def compute_canonical_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        ensure_json_finite(payload),
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def check_dt_compatible(dt_a: float | None, dt_b: float | None, *, label_a: str = "plant", label_b: str = "controller") -> None:
    if (dt_a is None) != (dt_b is None):
        raise DimensionMismatchError(
            message=(
                f"Domínio temporal incompatível: {label_a} tem dt={dt_a!r} enquanto "
                f"{label_b} tem dt={dt_b!r} (contínuo vs discreto)."
            ),
            parameters={f"{label_a}_dt": dt_a, f"{label_b}_dt": dt_b},
            next_step="Converta ambos os modelos para tempo contínuo ou para o mesmo passo de amostragem dt.",
        )
    if dt_a is not None and dt_b is not None:
        if not math.isclose(dt_a, dt_b, rel_tol=1e-12, abs_tol=1e-15):
            raise DimensionMismatchError(
                message=f"Passos de amostragem incompatíveis: {label_a}.dt={dt_a} != {label_b}.dt={dt_b}.",
                parameters={f"{label_a}_dt": dt_a, f"{label_b}_dt": dt_b},
                next_step="Reamostre para que ambos tenham o mesmo dt.",
            )
