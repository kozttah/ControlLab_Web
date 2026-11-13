"""Serialização e restauração canônica de modelos (CL-DIR-001 Seção 13.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from control_lab.diagnostics import (
    Result,
    SchemaUnsupportedError,
    UnsupportedModelError,
    ValidationError,
    ensure_json_finite,
    strict_json_loads,
)

from .controllers import DynamicController, PDCController, StateFeedbackController
from .interconnect import TSClosedLoop
from .models import (
    Dataset,
    Experiment,
    FuzzySystem,
    IdentifiedModel,
    StateSpace,
    TSStateSpace,
    TransferFunction,
)
from .tensors import validate_schema_version


def serialize_model(obj: Any) -> dict[str, Any]:
    """Serializa qualquer objeto canônico do ControlLab para dicionário JSON finito."""
    if isinstance(
        obj,
        (
            StateSpace,
            TransferFunction,
            Dataset,
            IdentifiedModel,
            TSStateSpace,
            FuzzySystem,
            StateFeedbackController,
            DynamicController,
            PDCController,
            Experiment,
            TSClosedLoop,
            Result,
        ),
    ):
        return ensure_json_finite(obj.to_dict())

    to_dict_fn = getattr(obj, "to_dict", None)
    if callable(to_dict_fn):
        return ensure_json_finite(to_dict_fn())

    raise UnsupportedModelError(
        f"Objeto do tipo {type(obj).__name__} não é um modelo ControlLab serializável."
    )


def restore_model(payload: Mapping[str, Any] | str | bytes) -> Any:
    """Restaura um modelo canônico ou Result a partir de dict ou JSON string sem execução de código."""
    if isinstance(payload, (str, bytes)):
        data = strict_json_loads(payload)
    elif isinstance(payload, Mapping):
        data = ensure_json_finite(payload)
    else:
        raise ValidationError(f"Payload inválido para restore_model: {type(payload).__name__}")

    if not isinstance(data, Mapping):
        raise ValidationError("Payload serializado deve ser um objeto JSON (dict).")

    if "schema_version" in data:
        validate_schema_version(data["schema_version"])

    kind = data.get("kind")
    if kind is None:
        if {"status", "data", "assumptions", "diagnostics", "provenance", "warnings", "error"}.issubset(
            data.keys()
        ):
            return Result.from_dict(data)
        raise ValidationError("Objeto serializado não contém campo discriminador 'kind'.")

    if kind == "StateSpace":
        return StateSpace.from_dict(data)
    if kind == "TransferFunction":
        return TransferFunction.from_dict(data)
    if kind == "Dataset":
        return Dataset.from_dict(data)
    if kind == "IdentifiedModel":
        return IdentifiedModel.from_dict(data)
    if kind in ("ts_measured", "polytopic_uncertain", "ts_partially_observed"):
        return TSStateSpace.from_dict(data)
    if kind == "FuzzySystem":
        return FuzzySystem.from_dict(data)
    if kind == "StateFeedbackController":
        return StateFeedbackController.from_dict(data)
    if kind == "DynamicController":
        return DynamicController.from_dict(data)
    if kind == "PDCController":
        return PDCController.from_dict(data)
    if kind == "Experiment":
        return Experiment.from_dict(data)
    if kind == "TSClosedLoop":
        return TSClosedLoop.from_dict(data)

    raise UnsupportedModelError(
        message=f"Tipo de modelo desconhecido/não suportado: {kind!r}.",
        parameters={"kind": kind},
    )


def load_model(source: Mapping[str, Any] | str | bytes | Path) -> Any:
    """Carrega e valida passivamente um modelo a partir de dict, string JSON ou caminho de arquivo."""
    if isinstance(source, Path):
        if not source.exists() or not source.is_file():
            raise ValidationError(f"Arquivo de modelo não encontrado: {source}")
        raw = source.read_text(encoding="utf-8")
        return restore_model(raw)

    if isinstance(source, str):
        stripped = source.lstrip()
        if stripped.startswith("{"):
            return restore_model(source)
        path = Path(source)
        if path.exists() and path.is_file():
            return restore_model(path.read_text(encoding="utf-8"))
        raise ValidationError("String fornecida para load_model não é JSON válido nem arquivo existente.")

    return restore_model(source)
