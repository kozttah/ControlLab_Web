"""Transporte JSON de arquivos nos RPCs v1.0. Os adaptadores nativos detêm o formato."""

import base64
import binascii
from dataclasses import replace
from typing import Any

from control_lab.core.serialization import restore_model
from control_lab.diagnostics import ResourceLimitError, Result, ValidationError

from .ctrlab import DEFAULT_MAX_ARCHIVE_BYTES, DEFAULT_MAX_MEMBER_BYTES, export_ctrlab, load_ctrlab
from .pvm import DEFAULT_MAX_PVM_BYTES, export_pvm, import_pvm


def _fields(obj: dict, required: set[str], allowed: set[str]) -> None:
    missing = required - obj.keys()
    extra = obj.keys() - allowed
    if missing or extra:
        raise ValidationError(f"Campos obrigatórios ausentes: {sorted(missing)}; extras: {sorted(extra)}.")


def _file_bytes(payload: dict, limit: int) -> bytes:
    _fields(payload, {"bytes_base64"}, {"bytes_base64"})
    encoded = payload["bytes_base64"]
    if not isinstance(encoded, str) or not encoded:
        raise ValidationError("bytes_base64 deve conter um arquivo em base64.")
    if len(encoded) > 4 * ((limit + 2) // 3):
        raise ResourceLimitError("Arquivo codificado excede o limite do formato.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValidationError("bytes_base64 inválido.") from exc
    if len(raw) > limit:
        raise ResourceLimitError("Arquivo decodificado excede o limite do formato.")
    return raw


def _ctrlab_project(payload: dict, project_id: str, project_revision: int) -> dict:
    _fields(payload, {"project"}, {"project"})
    if not isinstance(payload["project"], dict):
        raise ValidationError("project deve ser um objeto.")
    project = dict(payload["project"])
    _fields(project, set(), {"project_id", "project_revision", "models", "controllers",
                             "experiments", "datasets", "plots", "exports", "created_at", "modified_at", "provenance"})
    for key, value in (("project_id", project_id), ("project_revision", project_revision)):
        if key in project and (type(project[key]) is not type(value) or project[key] != value):
            raise ValidationError(f"project.{key} difere do envelope RPC.")
        project[key] = value
    for key in ("models", "controllers", "experiments"):
        items = project.get(key, [])
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValidationError(f"project.{key} deve ser uma lista de objetos canônicos.")
        project[key] = [restore_model(item) for item in items]
    if "provenance" in project and not isinstance(project["provenance"], dict):
        raise ValidationError("project.provenance deve ser um objeto.")
    for key in ("datasets", "plots", "exports"):
        if key not in project:
            continue
        entries = project[key]
        if not isinstance(entries, dict):
            raise ValidationError(f"project.{key} deve ser um mapa de arquivos.")
        project[key] = dict(entries)
        for path, value in entries.items():
            if isinstance(value, str):
                continue
            if key == "plots" and isinstance(value, dict):
                project[key][path] = _file_bytes(value, DEFAULT_MAX_MEMBER_BYTES)
            elif key != "exports" or not isinstance(value, dict):
                raise ValidationError(f"Valor inválido em project.{key}[{path!r}].")
    return project


def dispatch_file(operation: str, payload: dict[str, Any], project_id: str,
                  project_revision: int) -> Result:
    if operation == "io.import_ctrlab":
        return load_ctrlab(_file_bytes(payload, DEFAULT_MAX_ARCHIVE_BYTES))
    if operation == "io.import_pvm":
        return import_pvm(_file_bytes(payload, DEFAULT_MAX_PVM_BYTES))
    if operation == "io.export_ctrlab":
        project = _ctrlab_project(payload, project_id, project_revision)
        result = export_ctrlab(project, provenance=project.get("provenance"), include_base64=True)
        if result.data is None:
            return result
        data = result.data
        file_data = {"bytes_base64": data["zip_base64"], "size_bytes": data["size_bytes"],
                     "sha256": data["sha256"], "media_type": "application/zip"}
    elif operation == "io.export_pvm":
        _fields(payload, {"plant"}, {"plant", "controller", "scenario", "name", "target_spec_version"})
        if not isinstance(payload["plant"], dict):
            raise ValidationError("plant deve ser um modelo canônico.")
        if "scenario" in payload and not isinstance(payload["scenario"], dict):
            raise ValidationError("scenario deve ser um objeto.")
        if "name" in payload and (not isinstance(payload["name"], str) or not payload["name"].strip()):
            raise ValidationError("name deve ser uma string não vazia.")
        controller = payload.get("controller")
        if controller is not None and not isinstance(controller, dict):
            raise ValidationError("controller deve ser um controlador canônico ou null.")
        result = export_pvm(
            restore_model(payload["plant"]),
            controller=restore_model(controller) if controller is not None else None,
            scenario=payload.get("scenario"),
            name=payload.get("name"),
            target_spec_version=payload.get("target_spec_version", "1.0.0"),
        )
        if result.data is None:
            return result
        raw = result.data["pvm_json"].encode("utf-8")
        file_data = {"bytes_base64": base64.b64encode(raw).decode("ascii"), "size_bytes": len(raw),
                     "sha256": result.data["sha256"], "media_type": "application/json"}
    else:
        raise ValidationError(f"Operação de arquivo desconhecida: {operation!r}.")
    return replace(result, data=file_data)
