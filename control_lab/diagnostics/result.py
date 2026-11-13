"""Envelope científico imutável Result conforme Seção 4.4 e result.schema.json."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .errors import (
    TypedError,
    ValidationError,
    WarningItem,
    ensure_json_finite,
    strict_json_dumps,
    strict_json_loads,
)
from .provenance import Provenance, build_provenance

RESULT_STATUSES: tuple[str, ...] = ("success", "warning", "inconclusive", "failure")
_RESULT_STATUS_SET = frozenset(RESULT_STATUSES)


def _default_provenance() -> Provenance:
    return build_provenance("control_lab")


@dataclass(frozen=True)
class Result:
    """Envelope científico imutável comum para retorno de operações do ControlLab."""

    status: str
    data: dict[str, Any] | None = None
    assumptions: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=_default_provenance)
    warnings: tuple[str | WarningItem, ...] = ()
    error: TypedError | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in _RESULT_STATUS_SET:
            raise ValidationError(
                message=f"Result.status inválido: {self.status!r}",
                parameters={"status": self.status, "allowed": list(RESULT_STATUSES)},
            )

        if self.data is not None:
            if not isinstance(self.data, Mapping):
                raise ValidationError("Result.data deve ser um dicionário (dict) ou None.")
            object.__setattr__(self, "data", ensure_json_finite(dict(self.data), path="$.data"))

        if self.assumptions is None:
            object.__setattr__(self, "assumptions", {})
        elif isinstance(self.assumptions, Mapping):
            object.__setattr__(
                self,
                "assumptions",
                ensure_json_finite(dict(self.assumptions), path="$.assumptions"),
            )
        else:
            raise ValidationError("Result.assumptions deve ser um dicionário (dict).")

        if self.diagnostics is None:
            object.__setattr__(self, "diagnostics", {})
        elif isinstance(self.diagnostics, Mapping):
            object.__setattr__(
                self,
                "diagnostics",
                ensure_json_finite(dict(self.diagnostics), path="$.diagnostics"),
            )
        else:
            raise ValidationError("Result.diagnostics deve ser um dicionário (dict).")

        if self.provenance is None:
            raise ValidationError("Result.provenance não pode ser None.")
        if isinstance(self.provenance, Mapping) and not isinstance(self.provenance, Provenance):
            object.__setattr__(self, "provenance", Provenance.from_dict(self.provenance))
        elif not isinstance(self.provenance, Provenance):
            raise ValidationError("Result.provenance deve ser Provenance ou Mapping válido.")

        if self.warnings is None:
            object.__setattr__(self, "warnings", ())
        elif isinstance(self.warnings, Sequence) and not isinstance(self.warnings, (str, bytes)):
            normalized_warnings: list[str | WarningItem] = []
            for idx, item in enumerate(self.warnings):
                if isinstance(item, WarningItem):
                    normalized_warnings.append(item)
                elif isinstance(item, str):
                    if not item.strip():
                        raise ValidationError(f"Result.warnings[{idx}] string não pode ser vazia.")
                    normalized_warnings.append(item)
                elif isinstance(item, Mapping):
                    normalized_warnings.append(WarningItem.from_dict(item))
                else:
                    raise ValidationError(
                        f"Item inválido em Result.warnings[{idx}]: {type(item).__name__}"
                    )
            object.__setattr__(self, "warnings", tuple(normalized_warnings))
        else:
            raise ValidationError("Result.warnings deve ser uma sequência de strings ou WarningItem.")

        err = self.error
        if isinstance(err, Mapping):
            err = TypedError.from_dict(err)
            object.__setattr__(self, "error", err)
        elif err is not None and not isinstance(err, TypedError):
            raise ValidationError("Result.error deve ser TypedError ou None.")

        if self.status == "failure" and err is None:
            raise ValidationError(
                message="Invariante violada: Result com status='failure' exige error=TypedError não nulo.",
                parameters={"status": self.status},
            )
        if self.status == "success" and err is not None:
            raise ValidationError(
                message="Invariante violada: Result com status='success' não pode possuir error não nulo.",
                parameters={"status": self.status},
            )

    def __getattribute__(self, name: str) -> Any:
        val = super().__getattribute__(name)
        if name in ("data", "assumptions", "diagnostics") and val is not None:
            return copy.deepcopy(val)
        return val

    def to_dict(self) -> dict[str, Any]:
        warnings_list: list[Any] = [
            w.to_dict() if isinstance(w, WarningItem) else w for w in self.warnings
        ]
        payload = {
            "status": self.status,
            "data": ensure_json_finite(self.data, path="$.data") if self.data is not None else None,
            "assumptions": ensure_json_finite(self.assumptions, path="$.assumptions"),
            "diagnostics": ensure_json_finite(self.diagnostics, path="$.diagnostics"),
            "provenance": self.provenance.to_dict(),
            "warnings": warnings_list,
            "error": self.error.to_dict() if self.error is not None else None,
        }
        return ensure_json_finite(payload)

    def to_json(self, *, indent: int | None = None, sort_keys: bool = True) -> str:
        return strict_json_dumps(self.to_dict(), indent=indent, sort_keys=sort_keys)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Result:
        if not isinstance(payload, Mapping):
            raise ValidationError("Payload de Result deve ser um objeto JSON.")
        allowed = {"status", "data", "assumptions", "diagnostics", "provenance", "warnings", "error"}
        extra = set(payload.keys()) - allowed
        if extra:
            raise ValidationError(
                message=f"Campos adicionais proibidos em Result: {sorted(extra)}",
                parameters={"extra_keys": sorted(extra)},
            )
        missing = allowed - set(payload.keys())
        if missing:
            raise ValidationError(
                message=f"Campos obrigatórios ausentes em Result: {sorted(missing)}",
                parameters={"missing_keys": sorted(missing)},
            )
        clean = ensure_json_finite(payload)
        err_raw = clean["error"]
        err_obj = TypedError.from_dict(err_raw) if err_raw is not None else None
        return cls(
            status=clean["status"],
            data=clean["data"],
            assumptions=clean["assumptions"],
            diagnostics=clean["diagnostics"],
            provenance=Provenance.from_dict(clean["provenance"]),
            warnings=clean["warnings"],
            error=err_obj,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> Result:
        parsed = strict_json_loads(raw)
        return cls.from_dict(parsed)
