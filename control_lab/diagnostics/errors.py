"""Erros tipados, categorias normativas e validação JSON finita (CL-DIR-001 Seção 8.4)."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

ERROR_CATEGORIES: tuple[str, ...] = (
    "VALIDATION_ERROR",
    "DIMENSION_MISMATCH",
    "UNSUPPORTED_MODEL",
    "HYPOTHESIS_VIOLATED",
    "NUMERICAL_INCONCLUSIVE",
    "SOLVER_UNAVAILABLE",
    "RESOURCE_LIMIT",
    "CANCELLED",
    "WORKER_RESTARTED",
    "SCHEMA_UNSUPPORTED",
    "IMPORT_UNTRUSTED_CODE",
    "INTERNAL_ERROR",
)

_ERROR_CATEGORY_SET = frozenset(ERROR_CATEGORIES)


def _reject_non_finite_constant(token: str) -> Any:
    raise ValidationError(
        message=f"Constante JSON não finita proibida encontrada: {token!r}",
        parameters={"token": token},
        next_step="Substitua NaN/Infinity por valores finitos antes de serializar ou carregar JSON.",
    )


def ensure_json_finite(value: Any, *, path: str = "$", _seen: set[int] | None = None) -> Any:
    """Converte e valida recursivamente uma estrutura para JSON finito (sem NaN/Inf)."""
    if _seen is None:
        _seen = set()

    if value is None or isinstance(value, (bool, str)):
        return value

    if isinstance(value, np.bool_):
        return bool(value)

    if isinstance(value, (int, np.integer)):
        return int(value)

    if isinstance(value, (float, np.floating)):
        fval = float(value)
        if not math.isfinite(fval):
            raise ValidationError(
                message=f"Valor numérico não finito proibido em {path}: {fval!r}",
                parameters={"path": path, "value": repr(fval)},
                next_step="Verifique os cálculos e remova NaN ou Inf antes da serialização.",
            )
        return fval

    if isinstance(value, np.ndarray):
        if np.issubdtype(value.dtype, np.complexfloating):
            if not (np.all(np.isfinite(value.real)) and np.all(np.isfinite(value.imag))):
                raise ValidationError(
                    message=f"Array complexo contém NaN ou Inf em {path}",
                    parameters={"path": path},
                )
            order = "F" if (value.flags.f_contiguous and not value.flags.c_contiguous) else "C"
            if value.ndim == 0:
                return {
                    "real": [float(value.real.item())],
                    "imag": [float(value.imag.item())],
                }
            return {
                "shape": [int(d) for d in value.shape],
                "dtype": "complex128" if value.dtype == np.complex128 else "complex64",
                "order": order,
                "real": [float(v) for v in value.real.ravel(order=order).tolist()],
                "imag": [float(v) for v in value.imag.ravel(order=order).tolist()],
            }
        if np.issubdtype(value.dtype, np.bool_):
            arr_int = value.astype(np.int64)
            order = "F" if (value.flags.f_contiguous and not value.flags.c_contiguous) else "C"
            if value.ndim == 0:
                return bool(value.item())
            return {
                "shape": [int(d) for d in value.shape],
                "dtype": "bool",
                "order": order,
                "data": [int(v) for v in arr_int.ravel(order=order).tolist()],
            }
        if np.issubdtype(value.dtype, np.integer):
            order = "F" if (value.flags.f_contiguous and not value.flags.c_contiguous) else "C"
            dtype_str = "int32" if value.dtype == np.int32 else "int64"
            if value.ndim == 0:
                return int(value.item())
            return {
                "shape": [int(d) for d in value.shape],
                "dtype": dtype_str,
                "order": order,
                "data": [int(v) for v in value.ravel(order=order).tolist()],
            }
        if np.issubdtype(value.dtype, np.floating):
            if not np.all(np.isfinite(value)):
                raise ValidationError(
                    message=f"Array numérico contém NaN ou Inf em {path}",
                    parameters={"path": path},
                )
            order = "F" if (value.flags.f_contiguous and not value.flags.c_contiguous) else "C"
            dtype_str = "float32" if value.dtype == np.float32 else "float64"
            if value.ndim == 0:
                return float(value.item())
            return {
                "shape": [int(d) for d in value.shape],
                "dtype": dtype_str,
                "order": order,
                "data": [float(v) for v in value.ravel(order=order).tolist()],
            }
        raise ValidationError(
            message=f"Dtype de ndarray não suportado em JSON em {path}: {value.dtype}",
            parameters={"path": path, "dtype": str(value.dtype)},
        )

    obj_id = id(value)
    if isinstance(value, (list, tuple)):
        if obj_id in _seen:
            raise ValidationError(
                message=f"Referência circular detectada em {path}",
                parameters={"path": path},
            )
        _seen.add(obj_id)
        try:
            return [ensure_json_finite(item, path=f"{path}[{idx}]", _seen=_seen) for idx, item in enumerate(value)]
        finally:
            _seen.remove(obj_id)

    if isinstance(value, Mapping):
        if obj_id in _seen:
            raise ValidationError(
                message=f"Referência circular detectada em {path}",
                parameters={"path": path},
            )
        _seen.add(obj_id)
        try:
            out: dict[str, Any] = {}
            for k, v in value.items():
                if not isinstance(k, str):
                    raise ValidationError(
                        message=f"Chave de dicionário deve ser string em {path}, recebido {type(k).__name__}",
                        parameters={"path": path, "key_type": type(k).__name__},
                    )
                out[k] = ensure_json_finite(v, path=f"{path}.{k}", _seen=_seen)
            return out
        finally:
            _seen.remove(obj_id)

    to_dict_fn = getattr(value, "to_dict", None)
    if callable(to_dict_fn):
        if obj_id in _seen:
            raise ValidationError(
                message=f"Referência circular detectada em {path}",
                parameters={"path": path},
            )
        _seen.add(obj_id)
        try:
            return ensure_json_finite(to_dict_fn(), path=path, _seen=_seen)
        finally:
            _seen.remove(obj_id)

    raise ValidationError(
        message=f"Tipo não serializável em JSON em {path}: {type(value).__name__}",
        parameters={"path": path, "type": type(value).__name__},
    )


def strict_json_dumps(obj: Any, *, indent: int | None = None, sort_keys: bool = True) -> str:
    """Serializa para string JSON garantindo rejeição estrita de NaN e Inf."""
    sanitized = ensure_json_finite(obj)
    return json.dumps(sanitized, allow_nan=False, indent=indent, sort_keys=sort_keys)


def strict_json_loads(raw: str | bytes) -> Any:
    """Carrega string JSON rejeitando NaN, Infinity e -Infinity."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        raise ValidationError(
            message=f"Conteúdo JSON deve ser str ou bytes, recebido {type(raw).__name__}",
        )
    try:
        loaded = json.loads(raw, parse_constant=_reject_non_finite_constant)
    except ControlLabError:
        raise
    except json.JSONDecodeError as exc:
        raise ValidationError(
            message=f"JSON inválido: {exc.msg}",
            parameters={"lineno": exc.lineno, "colno": exc.colno},
        ) from exc
    return ensure_json_finite(loaded)


@dataclass(frozen=True)
class WarningItem:
    """Aviso científico estruturado conforme result.schema.json."""

    code: str
    message: str
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValidationError("WarningItem.code deve ser uma string não vazia.")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValidationError("WarningItem.message deve ser uma string não vazia.")
        if self.details is not None:
            if not isinstance(self.details, Mapping):
                raise ValidationError("WarningItem.details deve ser um mapeamento (dict) ou None.")
            object.__setattr__(self, "details", ensure_json_finite(dict(self.details), path="$.details"))

    def __getattribute__(self, name: str) -> Any:
        val = super().__getattribute__(name)
        if name == "details" and val is not None:
            return copy.deepcopy(val)
        return val

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details is not None:
            payload["details"] = ensure_json_finite(self.details, path="$.details")
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WarningItem:
        if not isinstance(data, Mapping):
            raise ValidationError("WarningItem deve ser um objeto JSON.")
        if "code" not in data or "message" not in data:
            raise ValidationError("WarningItem requer campos 'code' e 'message'.")
        return cls(
            code=data["code"],
            message=data["message"],
            details=data.get("details"),
        )


@dataclass(frozen=True)
class TypedError:
    """Estrutura de erro tipado serializável conforme result.schema.json."""

    code: str
    message: str
    parameters: dict[str, Any] | None = None
    next_step: str | None = None
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or self.code not in _ERROR_CATEGORY_SET:
            raise ValidationError(
                message=f"Categoria de erro inválida: {self.code!r}",
                parameters={"code": self.code, "allowed": list(ERROR_CATEGORIES)},
            )
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValidationError("TypedError.message deve ser uma string não vazia.")
        if self.parameters is not None:
            if not isinstance(self.parameters, Mapping):
                raise ValidationError("TypedError.parameters deve ser dict ou None.")
            object.__setattr__(
                self, "parameters", ensure_json_finite(dict(self.parameters), path="$.parameters")
            )
        if self.next_step is not None and not isinstance(self.next_step, str):
            raise ValidationError("TypedError.next_step deve ser str ou None.")
        if self.details is not None:
            if not isinstance(self.details, Mapping):
                raise ValidationError("TypedError.details deve ser dict ou None.")
            object.__setattr__(
                self, "details", ensure_json_finite(dict(self.details), path="$.details")
            )

    def __getattribute__(self, name: str) -> Any:
        val = super().__getattribute__(name)
        if name in ("parameters", "details") and val is not None:
            return copy.deepcopy(val)
        return val

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.parameters is not None:
            payload["parameters"] = ensure_json_finite(self.parameters, path="$.parameters")
        if self.next_step is not None:
            payload["next_step"] = self.next_step
        if self.details is not None:
            payload["details"] = ensure_json_finite(self.details, path="$.details")
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TypedError:
        if not isinstance(data, Mapping):
            raise ValidationError("TypedError deve ser um objeto JSON.")
        allowed_keys = {"code", "message", "parameters", "next_step", "details"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            raise ValidationError(
                message=f"Campos não permitidos em TypedError: {sorted(extra_keys)}",
                parameters={"extra_keys": sorted(extra_keys)},
            )
        if "code" not in data or "message" not in data:
            raise ValidationError("TypedError requer campos 'code' e 'message'.")
        return cls(
            code=data["code"],
            message=data["message"],
            parameters=data.get("parameters"),
            next_step=data.get("next_step"),
            details=data.get("details"),
        )

    def to_exception(self) -> ControlLabError:
        exc_cls = _CODE_TO_EXCEPTION_CLASS.get(self.code, ControlLabError)
        if exc_cls is ControlLabError:
            return ControlLabError(
                code=self.code,
                message=self.message,
                parameters=self.parameters,
                next_step=self.next_step,
                details=self.details,
            )
        return exc_cls(
            message=self.message,
            parameters=self.parameters,
            next_step=self.next_step,
            details=self.details,
            code=self.code,
        )


class ControlLabError(Exception):
    """Exceção base tipada do ControlLab Web."""

    default_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        code: str,
        message: str,
        parameters: Mapping[str, Any] | None = None,
        next_step: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(code, str) or code not in _ERROR_CATEGORY_SET:
            raise ValueError(f"Categoria de erro desconhecida: {code!r}")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Mensagem de erro deve ser uma string não vazia.")
        self.code = code
        self.message = message
        self.parameters = dict(parameters) if parameters is not None else None
        self.next_step = next_step
        self.details = dict(details) if details is not None else None
        super().__init__(f"[{self.code}] {self.message}")

    def to_typed_error(self) -> TypedError:
        safe_params = ensure_json_finite(self.parameters, path="$.parameters") if self.parameters is not None else None
        safe_details = ensure_json_finite(self.details, path="$.details") if self.details is not None else None
        return TypedError(
            code=self.code,
            message=self.message,
            parameters=safe_params,
            next_step=self.next_step,
            details=safe_details,
        )


class _CategoryErrorMixin(ControlLabError):
    """Mixin para subclasses especializadas com código padrão e assinatura ergonômica."""

    def __init__(
        self,
        message: str,
        parameters: Mapping[str, Any] | None = None,
        next_step: str | None = None,
        details: Mapping[str, Any] | None = None,
        *,
        code: str | None = None,
    ) -> None:
        # Suporta opcionalmente chamada no estilo (code, message, ...)
        if message in _ERROR_CATEGORY_SET and isinstance(parameters, str):
            resolved_code = code or message
            resolved_message = parameters
            resolved_params = next_step if isinstance(next_step, Mapping) else None
            resolved_next = details if isinstance(details, str) else None
            resolved_details = None
        else:
            resolved_code = code or self.default_code
            resolved_message = message
            resolved_params = parameters
            resolved_next = next_step
            resolved_details = details
        ControlLabError.__init__(
            self,
            code=resolved_code,
            message=resolved_message,
            parameters=resolved_params,
            next_step=resolved_next,
            details=resolved_details,
        )


class ValidationError(_CategoryErrorMixin, ValueError):
    default_code = "VALIDATION_ERROR"


class DimensionMismatchError(_CategoryErrorMixin, ValueError):
    default_code = "DIMENSION_MISMATCH"


class UnsupportedModelError(_CategoryErrorMixin, TypeError):
    default_code = "UNSUPPORTED_MODEL"


class HypothesisViolatedError(_CategoryErrorMixin, ValueError):
    default_code = "HYPOTHESIS_VIOLATED"


class NumericalInconclusiveError(_CategoryErrorMixin, ArithmeticError):
    default_code = "NUMERICAL_INCONCLUSIVE"


class SolverUnavailableError(_CategoryErrorMixin, RuntimeError):
    default_code = "SOLVER_UNAVAILABLE"


class ResourceLimitError(_CategoryErrorMixin, RuntimeError):
    default_code = "RESOURCE_LIMIT"


class CancelledError(_CategoryErrorMixin, RuntimeError):
    default_code = "CANCELLED"


class WorkerRestartedError(_CategoryErrorMixin, RuntimeError):
    default_code = "WORKER_RESTARTED"


class SchemaUnsupportedError(_CategoryErrorMixin, ValueError):
    default_code = "SCHEMA_UNSUPPORTED"


class ImportUntrustedCodeError(_CategoryErrorMixin, PermissionError):
    default_code = "IMPORT_UNTRUSTED_CODE"


class InternalError(_CategoryErrorMixin, RuntimeError):
    default_code = "INTERNAL_ERROR"


_CODE_TO_EXCEPTION_CLASS: dict[str, type[ControlLabError]] = {
    "VALIDATION_ERROR": ValidationError,
    "DIMENSION_MISMATCH": DimensionMismatchError,
    "UNSUPPORTED_MODEL": UnsupportedModelError,
    "HYPOTHESIS_VIOLATED": HypothesisViolatedError,
    "NUMERICAL_INCONCLUSIVE": NumericalInconclusiveError,
    "SOLVER_UNAVAILABLE": SolverUnavailableError,
    "RESOURCE_LIMIT": ResourceLimitError,
    "CANCELLED": CancelledError,
    "WORKER_RESTARTED": WorkerRestartedError,
    "SCHEMA_UNSUPPORTED": SchemaUnsupportedError,
    "IMPORT_UNTRUSTED_CODE": ImportUntrustedCodeError,
    "INTERNAL_ERROR": InternalError,
}
