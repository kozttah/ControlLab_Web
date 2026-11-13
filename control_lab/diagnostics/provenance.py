"""Proveniência reproduzível de cálculos e objetos científicos (CL-DIR-001 Seção 4.4 e R-27)."""

from __future__ import annotations

import copy
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping

import numpy as np
import scipy

from .errors import ValidationError, ensure_json_finite


def utc_now_iso() -> str:
    """Retorna timestamp UTC ISO-8601 com sufixo Z."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_lib_versions(extra_libs: Mapping[str, str] | None = None) -> dict[str, str]:
    """Captura versões padrão das bibliotecas científicas em execução."""
    versions: dict[str, str] = {
        "numpy": str(np.__version__),
        "scipy": str(scipy.__version__),
        "python": str(platform.python_version()),
    }
    if extra_libs is not None:
        for k, v in extra_libs.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValidationError("extra_libs deve mapear strings para strings.")
            versions[k] = v
    return versions


@dataclass(frozen=True)
class Provenance(Mapping[str, Any]):
    """Metadados estruturados e imutáveis de proveniência científica."""

    algorithm: str
    lib_versions: dict[str, str] = field(default_factory=default_lib_versions)
    seed: int | None = None
    tolerances: dict[str, Any] = field(default_factory=dict)
    model_revision: int | None = None
    timestamp: str = field(default_factory=utc_now_iso)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, str) or not self.algorithm.strip():
            raise ValidationError("Provenance.algorithm deve ser uma string não vazia.")

        if not isinstance(self.lib_versions, Mapping):
            raise ValidationError("Provenance.lib_versions deve ser um mapeamento str -> str.")
        clean_libs: dict[str, str] = {}
        for k, v in self.lib_versions.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValidationError(
                    "Provenance.lib_versions deve conter apenas chaves e valores string.",
                    parameters={"key": repr(k), "value": repr(v)},
                )
            clean_libs[k] = v
        object.__setattr__(self, "lib_versions", clean_libs)

        if self.seed is not None:
            if isinstance(self.seed, bool) or not isinstance(self.seed, int):
                raise ValidationError("Provenance.seed deve ser int ou None.")

        if self.tolerances is None:
            object.__setattr__(self, "tolerances", {})
        elif isinstance(self.tolerances, Mapping):
            object.__setattr__(
                self,
                "tolerances",
                ensure_json_finite(dict(self.tolerances), path="$.provenance.tolerances"),
            )
        else:
            raise ValidationError("Provenance.tolerances deve ser um mapeamento (dict).")

        if self.model_revision is not None:
            if isinstance(self.model_revision, bool) or not isinstance(self.model_revision, int) or self.model_revision < 0:
                raise ValidationError("Provenance.model_revision deve ser inteiro >= 0 ou None.")

        if not isinstance(self.timestamp, str) or not self.timestamp.strip():
            raise ValidationError("Provenance.timestamp deve ser uma string ISO-8601 não vazia.")

        if self.extra is None:
            object.__setattr__(self, "extra", {})
        elif isinstance(self.extra, Mapping):
            object.__setattr__(
                self,
                "extra",
                ensure_json_finite(dict(self.extra), path="$.provenance.extra"),
            )
        else:
            raise ValidationError("Provenance.extra deve ser um mapeamento (dict).")

    def __getattribute__(self, name: str) -> Any:
        val = super().__getattribute__(name)
        if name in ("lib_versions", "tolerances", "extra") and val is not None:
            return copy.deepcopy(val)
        return val

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "algorithm": self.algorithm,
            "lib_versions": dict(self.lib_versions),
            "seed": self.seed,
            "tolerances": ensure_json_finite(self.tolerances, path="$.provenance.tolerances"),
            "model_revision": self.model_revision,
            "timestamp": self.timestamp,
        }
        for k, v in self.extra.items():
            if k not in payload:
                payload[k] = ensure_json_finite(v, path=f"$.provenance.{k}")
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Provenance:
        if not isinstance(data, Mapping):
            raise ValidationError("Provenance deve ser um objeto JSON.")
        if "algorithm" not in data or "lib_versions" not in data:
            raise ValidationError("Provenance requer campos 'algorithm' e 'lib_versions'.")
        known = {"algorithm", "lib_versions", "seed", "tolerances", "model_revision", "timestamp"}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            algorithm=data["algorithm"],
            lib_versions=data["lib_versions"],
            seed=data.get("seed"),
            tolerances=data.get("tolerances") if data.get("tolerances") is not None else {},
            model_revision=data.get("model_revision"),
            timestamp=data.get("timestamp") if data.get("timestamp") is not None else utc_now_iso(),
            extra=extra,
        )

    # Interface Mapping para acesso conveniente por chave (ex.: prov["algorithm"])
    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        return d[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


def build_provenance(
    algorithm: str,
    *,
    seed: int | None = None,
    tolerances: Mapping[str, Any] | None = None,
    model_revision: int | None = None,
    timestamp: str | None = None,
    extra_libs: Mapping[str, str] | None = None,
    **extra: Any,
) -> Provenance:
    """Constrói Provenance preenchendo versões atuais de numpy, scipy e python."""
    return Provenance(
        algorithm=algorithm,
        lib_versions=default_lib_versions(extra_libs),
        seed=seed,
        tolerances=dict(tolerances) if tolerances is not None else {},
        model_revision=model_revision,
        timestamp=timestamp if timestamp is not None else utc_now_iso(),
        extra=extra,
    )
