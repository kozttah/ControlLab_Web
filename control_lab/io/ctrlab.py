"""Exportação, importação passiva, validação e migração do contêiner `.ctrlab` ZIP.

Normas (CL-DIR-001 Seções 9.1, 9.2, 12.2, 13.3 e T-IO-01):
- Contêiner ZIP determinístico contendo `manifest.json` (conforme
  `contracts/schemas/ctrlab_manifest.schema.json`), `models.json`,
  `controllers.json`, `experiments.json` e pastas opcionais `datasets/`,
  `artifacts/plots/` e `exports/`.
- Importação 100% passiva em memória (nunca extrai nem cria arquivos/diretórios
  em disco e nunca executa código/scripts presentes em arquivos).
- Proteção estrita contra path traversal, symlinks, colisões Unicode NFC,
  duplicidades case-folded, entradas duplicadas, ZIP bombs (limites de tamanho,
  membros e razão de compressão por leitura em streaming) e adulteração SHA-256.
"""

from __future__ import annotations

import base64
import copy
import csv
from datetime import datetime
import hashlib
import io
import math
from pathlib import Path
import re
import stat
import unicodedata
from typing import Any, IO, Mapping, Sequence
import zipfile
import zlib

import numpy as np

from control_lab.core.controllers import DynamicController, PDCController, StateFeedbackController
from control_lab.core.models import (
    Dataset,
    Experiment,
    FuzzySystem,
    IdentifiedModel,
    StateSpace,
    TSStateSpace,
    TransferFunction,
)
from control_lab.core.serialization import restore_model, serialize_model
from control_lab.core.tensors import (
    validate_non_empty_str,
    validate_revision,
    validate_schema_version,
)
from control_lab.diagnostics import (
    ControlLabError,
    Provenance,
    ResourceLimitError,
    Result,
    SchemaUnsupportedError,
    ValidationError,
    WarningItem,
    build_provenance,
    ensure_json_finite,
    strict_json_dumps,
    strict_json_loads,
)

from .pvm import import_pvm, validate_pvm_structure

CTRLAB_FORMAT: str = "ctrlab"
CTRLAB_SCHEMA_VERSION: str = "1.0.0"
CTRLAB_APP_VERSION: str = "1.0.0"
DEFAULT_CREATED_AT: str = "2026-11-13T00:00:00Z"
DEFAULT_ZIP_DATE_TIME: tuple[int, int, int, int, int, int] = (2026, 11, 13, 0, 0, 0)

DEFAULT_MAX_ARCHIVE_BYTES: int = 64 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES: int = 64 * 1024 * 1024
DEFAULT_MAX_MEMBER_BYTES: int = 32 * 1024 * 1024
DEFAULT_MAX_MEMBERS: int = 1024
DEFAULT_MAX_COMPRESSION_RATIO: float = 500.0
DEFAULT_MIN_BYTES_FOR_RATIO: int = 2 * 1024 * 1024

_SCHEMA_VERSION_RE = re.compile(r"^1\.0\.\d+\Z")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}\Z")
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SVG_UNSAFE_RE = re.compile(r"(<\s*script\b|javascript:|on[a-z]+\s*=)", re.IGNORECASE)
_SCRIPT_EXTS = frozenset({".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".exe", ".dll", ".so"})

_MANIFEST_ALLOWED_KEYS = frozenset(
    {
        "format",
        "schema_version",
        "app_version",
        "created_at",
        "modified_at",
        "project_id",
        "project_revision",
        "hashes",
        "capabilities",
        "contents",
        "provenance",
    }
)
_MANIFEST_REQUIRED_KEYS = frozenset(
    {
        "format",
        "schema_version",
        "app_version",
        "created_at",
        "project_id",
        "project_revision",
        "hashes",
        "capabilities",
    }
)
_CORE_REQUIRED_FILES = ("models.json", "controllers.json", "experiments.json")


def _safe_strict_json_loads(raw: str | bytes | bytearray | memoryview, *, context: str = "JSON") -> Any:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(
                message=f"Conteúdo {context} não é UTF-8 válido: {exc}",
                parameters={"context": context},
            ) from exc
        return strict_json_loads(text)
    return strict_json_loads(raw)


def _validate_iso_datetime(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ValidationError(f"{field_name} deve ser string ISO-8601 date-time não vazia.")
    if "T" not in value and "t" not in value and " " not in value:
        raise ValidationError(f"{field_name} deve incluir data e hora ISO-8601: {value!r}.")
    norm = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(norm)
    except ValueError as exc:
        raise ValidationError(
            message=f"{field_name} não é um timestamp ISO-8601 válido: {value!r}.",
            parameters={field_name: value},
        ) from exc
    return value


def _zip_datetime_from_iso(iso_ts: str) -> tuple[int, int, int, int, int, int]:
    norm = iso_ts[:-1] + "+00:00" if iso_ts.endswith("Z") else iso_ts
    try:
        dt = datetime.fromisoformat(norm)
    except ValueError:
        return DEFAULT_ZIP_DATE_TIME
    year = max(1980, min(2107, dt.year))
    sec = dt.second - (dt.second % 2)
    return (year, dt.month, dt.day, dt.hour, dt.minute, sec)


def _is_non_bool_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def validate_ctrlab_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Valida manifesto `.ctrlab` estritamente contra `ctrlab_manifest.schema.json`."""
    if not isinstance(manifest, Mapping):
        raise ValidationError("Manifesto .ctrlab deve ser um objeto JSON (Mapping).")

    clean = ensure_json_finite(dict(manifest), path="$.manifest")

    if "schema_version" not in clean:
        raise ValidationError("Campo obrigatório ausente no manifesto .ctrlab: 'schema_version'.")
    sv = clean["schema_version"]
    if not isinstance(sv, str) or not _SCHEMA_VERSION_RE.match(sv):
        raise SchemaUnsupportedError(
            message=f"schema_version .ctrlab não suportada: {sv!r} (esperado 1.0.x).",
            parameters={"schema_version": sv},
            next_step="Use migrate_ctrlab_manifest() para versões legadas suportadas ou atualize o contêiner.",
        )

    keys = set(clean.keys())
    extra = keys - _MANIFEST_ALLOWED_KEYS
    if extra:
        raise ValidationError(
            message=f"Campos extras proibidos em manifest.json: {sorted(extra)}",
            parameters={"extra_fields": sorted(extra)},
        )
    missing = _MANIFEST_REQUIRED_KEYS - keys
    if missing:
        raise ValidationError(
            message=f"Campos obrigatórios ausentes em manifest.json: {sorted(missing)}",
            parameters={"missing_fields": sorted(missing)},
        )

    if clean["format"] != CTRLAB_FORMAT:
        raise ValidationError(f"manifest.format deve ser 'ctrlab', recebido {clean['format']!r}.")
    validate_non_empty_str(clean["app_version"], field_name="manifest.app_version")
    _validate_iso_datetime(clean["created_at"], field_name="manifest.created_at")
    if "modified_at" in clean:
        _validate_iso_datetime(clean["modified_at"], field_name="manifest.modified_at")
    validate_non_empty_str(clean["project_id"], field_name="manifest.project_id")

    rev = clean["project_revision"]
    if not _is_non_bool_int(rev) or rev < 0:
        raise ValidationError(f"manifest.project_revision deve ser inteiro >= 0, recebido {rev!r}.")

    hashes = clean["hashes"]
    if not isinstance(hashes, Mapping):
        raise ValidationError("manifest.hashes deve ser um dicionário caminho -> SHA-256.")
    for h_path, h_val in hashes.items():
        if not isinstance(h_path, str) or not h_path:
            raise ValidationError("Chave de caminho em manifest.hashes deve ser string não vazia.")
        if not isinstance(h_val, str) or not _SHA256_RE.match(h_val):
            raise ValidationError(
                message=f"Hash SHA-256 inválido em manifest.hashes[{h_path!r}]: {h_val!r}.",
                parameters={"member": h_path},
            )

    caps = clean["capabilities"]
    if not isinstance(caps, Mapping) or "required_features" not in caps:
        raise ValidationError("manifest.capabilities deve conter 'required_features'.")
    req_feats = caps["required_features"]
    if not isinstance(req_feats, list) or not all(isinstance(f, str) and len(f) > 0 for f in req_feats):
        raise ValidationError("manifest.capabilities.required_features deve ser lista de strings não vazias.")
    if "optional_features" in caps:
        opt_feats = caps["optional_features"]
        if not isinstance(opt_feats, list) or not all(isinstance(f, str) and len(f) > 0 for f in opt_feats):
            raise ValidationError("manifest.capabilities.optional_features deve ser lista de strings não vazias.")
    if "max_uncompressed_bytes" in caps:
        mub = caps["max_uncompressed_bytes"]
        if not _is_non_bool_int(mub) or mub < 1:
            raise ValidationError("manifest.capabilities.max_uncompressed_bytes deve ser inteiro >= 1.")
    if "max_members" in caps:
        mm = caps["max_members"]
        if not _is_non_bool_int(mm) or mm < 1:
            raise ValidationError("manifest.capabilities.max_members deve ser inteiro >= 1.")

    if "contents" in clean and not isinstance(clean["contents"], Mapping):
        raise ValidationError("manifest.contents deve ser um objeto JSON.")
    if "provenance" in clean and not isinstance(clean["provenance"], Mapping):
        raise ValidationError("manifest.provenance deve ser um objeto JSON.")

    return clean


def migrate_ctrlab_manifest(
    manifest: Mapping[str, Any],
    target_version: str = "1.0.0",
    *,
    dry_run: bool = False,
    return_result: bool = False,
) -> dict[str, Any] | Result:
    """Função pura e não destrutiva de migração de manifestos `.ctrlab` (Seção 9.1)."""
    prov: Provenance = build_provenance("control_lab.io.migrate_ctrlab_manifest")
    try:
        if not isinstance(target_version, str) or target_version != CTRLAB_SCHEMA_VERSION:
            raise SchemaUnsupportedError(
                message=f"Versão de destino não suportada para migração .ctrlab: {target_version!r}.",
                parameters={"target_version": target_version, "supported_target": CTRLAB_SCHEMA_VERSION},
            )
        if not isinstance(manifest, Mapping):
            raise ValidationError("manifest deve ser um dicionário Mapping.")

        src = ensure_json_finite(copy.deepcopy(dict(manifest)), path="$.manifest")
        src_version = src.get("schema_version")
        used_legacy_version_key = False
        if src_version is None and "version" in src:
            src_version = src.get("version")
            used_legacy_version_key = True

        if not isinstance(src_version, str) or not src_version.strip():
            raise ValidationError("Manifesto não possui 'schema_version' válida.")

        changes: list[str] = []
        if _SCHEMA_VERSION_RE.match(src_version):
            validated = validate_ctrlab_manifest(src)
            migrated = copy.deepcopy(validated)
            if src_version != target_version:
                migrated["schema_version"] = target_version
                changes.append(f"schema_version: {src_version} -> {target_version}")
            needs_migration = len(changes) > 0
        elif src_version in ("0.4.0", "0.9.0"):
            migrated = copy.deepcopy(src)
            if used_legacy_version_key:
                migrated.pop("version", None)
                changes.append("renamed key 'version' -> 'schema_version'")
            migrated["format"] = migrated.get("format", CTRLAB_FORMAT)
            if "format" not in src:
                changes.append("added format='ctrlab'")
            migrated["schema_version"] = target_version
            changes.append(f"schema_version: {src_version} -> {target_version}")
            if "app_version" not in migrated:
                migrated["app_version"] = CTRLAB_APP_VERSION
                changes.append(f"added default app_version={CTRLAB_APP_VERSION!r}")
            if "project_revision" not in migrated:
                migrated["project_revision"] = 0
                changes.append("added default project_revision=0")
            if "capabilities" not in migrated:
                migrated["capabilities"] = {
                    "required_features": ["core.serialization"],
                }
                changes.append("added default capabilities.required_features")
            prov_meta = dict(migrated.get("provenance") or {})
            prov_meta["migrated_from"] = src_version
            migrated["provenance"] = prov_meta
            changes.append(f"recorded provenance.migrated_from={src_version!r}")
            migrated = validate_ctrlab_manifest(migrated)
            needs_migration = True
        else:
            raise SchemaUnsupportedError(
                message=(
                    f"Versão de manifesto .ctrlab desconhecida/não suportada: {src_version!r}. "
                    "Versões futuras não são reinterpretadas silenciosamente."
                ),
                parameters={"source_version": src_version, "target_version": target_version},
                next_step="Atualize o motor ControlLab antes de abrir contêineres de versões futuras.",
            )

        if dry_run:
            report: dict[str, Any] = {
                "dry_run": True,
                "source_version": src_version,
                "target_version": target_version,
                "needs_migration": needs_migration,
                "valid": True,
                "changes": changes,
                "preview_manifest": migrated,
            }
            if return_result:
                return Result(
                    status="success",
                    data=report,
                    assumptions={"pure_migration": True, "dry_run": True, "input_mutated": False},
                    diagnostics={"changes_count": len(changes)},
                    provenance=prov,
                )
            return report

        if return_result:
            return Result(
                status="success",
                data={
                    "dry_run": False,
                    "source_version": src_version,
                    "target_version": target_version,
                    "needs_migration": needs_migration,
                    "changes": changes,
                    "manifest": migrated,
                },
                assumptions={"pure_migration": True, "dry_run": False, "input_mutated": False},
                diagnostics={"changes_count": len(changes)},
                provenance=prov,
            )
        return migrated
    except ControlLabError as exc:
        if not return_result:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions={"pure_migration": True, "dry_run": dry_run},
            diagnostics={},
            provenance=prov,
            error=exc.to_typed_error(),
        )


# ---------------------------------------------------------------------------
# CSV científico passivo para datasets/*.csv (Seção 9.2)
# ---------------------------------------------------------------------------


def dataset_to_csv(
    dataset: Dataset,
    *,
    delimiter: str = ",",
    include_metadata_comments: bool = True,
) -> str:
    """Serializa `Dataset` para CSV/TSV determinístico preservando canais, unidades e precisão."""
    if not isinstance(dataset, Dataset):
        raise ValidationError(f"dataset_to_csv requer Dataset, recebido {type(dataset).__name__}.")
    if delimiter not in (",", "\t", ";"):
        raise ValidationError(f"Delimitador inválido: {delimiter!r}. Use ',', '\\t' ou ';'.")

    buf = io.StringIO()
    if include_metadata_comments:
        meta = {
            "id": dataset.id,
            "revision": dataset.revision,
            "dt": dataset.dt,
            "input_names": list(dataset.input_names),
            "output_names": list(dataset.output_names),
            "units": dataset.units,
        }
        buf.write("# format: controllab_dataset_csv_v1\n")
        buf.write(f"# metadata: {strict_json_dumps(meta, sort_keys=True)}\n")

    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    header = ["t", *dataset.input_names, *dataset.output_names]
    writer.writerow(header)

    t_vals = dataset.t.tolist()
    u_vals = dataset.u.tolist()
    y_vals = dataset.y.tolist()
    for idx in range(dataset.n_samples):
        row = [repr(float(t_vals[idx]))]
        row.extend(repr(float(v)) for v in u_vals[idx])
        row.extend(repr(float(v)) for v in y_vals[idx])
        writer.writerow(row)
    return buf.getvalue()


def parse_csv_dataset(
    raw: str | bytes,
    *,
    delimiter: str | None = None,
    n_inputs: int | None = None,
    n_outputs: int | None = None,
    dt: float | None = None,
    id: str | None = None,
    revision: int = 0,
    require_uniform: bool = False,
) -> Dataset:
    """Importa CSV/TSV passivamente para `Dataset` (sem eval/exec)."""
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"CSV/TSV não é UTF-8 válido: {exc}") from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise ValidationError(f"parse_csv_dataset requer str ou bytes, recebido {type(raw).__name__}.")

    meta: dict[str, Any] = {}
    data_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if stripped.startswith("# metadata:"):
                payload_s = stripped[len("# metadata:") :].strip()
                parsed_meta = strict_json_loads(payload_s)
                if isinstance(parsed_meta, Mapping):
                    meta.update(parsed_meta)
            continue
        data_lines.append(line)

    if len(data_lines) < 2:
        raise ValidationError("CSV deve conter cabeçalho e ao menos 1 linha de dados.")

    if delimiter is None:
        hdr_line = data_lines[0]
        counts = {d: hdr_line.count(d) for d in (",", "\t", ";")}
        delimiter = max(counts, key=lambda k: counts[k])
        if counts[delimiter] == 0:
            raise ValidationError("Não foi possível detectar delimitador CSV válido (',', '\\t' ou ';').")

    rows = list(csv.reader(data_lines, delimiter=delimiter))
    header = [h.strip() for h in rows[0]]
    n_cols = len(header)
    if n_cols < 3:
        raise ValidationError("CSV de Dataset deve ter ao menos 3 colunas (t, u, y).")

    numeric_rows: list[list[float]] = []
    for r_idx, row in enumerate(rows[1:], start=1):
        if len(row) != n_cols:
            raise ValidationError(f"Linha {r_idx} do CSV tem {len(row)} colunas, esperado {n_cols}.")
        parsed_row: list[float] = []
        for c_idx, cell in enumerate(row):
            cell_s = cell.strip()
            try:
                val = float(cell_s)
            except ValueError as exc:
                raise ValidationError(
                    f"Célula não numérica na linha {r_idx}, coluna {c_idx} ({header[c_idx]!r}): {cell_s!r}."
                ) from exc
            if not math.isfinite(val):
                raise ValidationError(f"Valor não finito na linha {r_idx}, coluna {c_idx}: {cell_s!r}.")
            parsed_row.append(val)
        numeric_rows.append(parsed_row)

    arr = np.asarray(numeric_rows, dtype=np.float64)
    in_names_meta = meta.get("input_names")
    out_names_meta = meta.get("output_names")

    if n_inputs is not None and n_outputs is not None:
        m, p = int(n_inputs), int(n_outputs)
    elif isinstance(in_names_meta, list) and isinstance(out_names_meta, list):
        m, p = len(in_names_meta), len(out_names_meta)
    else:
        u_cols = [i for i, h in enumerate(header[1:], start=1) if h.startswith("u")]
        y_cols = [i for i, h in enumerate(header[1:], start=1) if h.startswith("y")]
        if u_cols and y_cols and (len(u_cols) + len(y_cols) == n_cols - 1):
            m, p = len(u_cols), len(y_cols)
        else:
            m = n_inputs if n_inputs is not None else 1
            p = n_outputs if n_outputs is not None else (n_cols - 1 - m)

    if 1 + m + p != n_cols or m < 1 or p < 1:
        raise ValidationError(
            f"Contagem de colunas (1 + m={m} + p={p}) incompatível com {n_cols} colunas do CSV."
        )

    t_vec = arr[:, 0]
    u_mat = arr[:, 1 : 1 + m]
    y_mat = arr[:, 1 + m : 1 + m + p]

    return Dataset(
        t=t_vec,
        u=u_mat,
        y=y_mat,
        dt=dt if dt is not None else meta.get("dt"),
        require_uniform=require_uniform,
        id=id if id is not None else meta.get("id"),
        revision=revision if id is not None else int(meta.get("revision", revision)),
        input_names=in_names_meta if isinstance(in_names_meta, list) else header[1 : 1 + m],
        output_names=out_names_meta if isinstance(out_names_meta, list) else header[1 + m :],
        units=meta.get("units"),
        provenance={"source": "csv_passive_import"},
    )


# ---------------------------------------------------------------------------
# Segurança ZIP (anti-traversal, NFC/casefold, symlinks, anti-ZIP bomb)
# ---------------------------------------------------------------------------


def _validate_archive_path_string(raw_name: str, *, is_dir: bool = False) -> str:
    if not isinstance(raw_name, str) or not raw_name:
        raise ValidationError("Nome de entrada ZIP não pode ser vazio.")

    for ch in raw_name:
        code = ord(ch)
        if code < 0x20 or code == 0x7F or (0x202A <= code <= 0x202E) or (0x2066 <= code <= 0x2069):
            raise ValidationError(
                message=f"Caractere de controle/bidi proibido em caminho ZIP: {raw_name!r}.",
                parameters={"member": repr(raw_name)},
            )

    if "\\" in raw_name:
        raise ValidationError(
            message=f"Separador '\\' proibido em caminho ZIP (risco de traversal): {raw_name!r}.",
            parameters={"member": raw_name},
        )
    if raw_name.startswith("/") or _WIN_DRIVE_RE.match(raw_name):
        raise ValidationError(
            message=f"Caminho absoluto/drive proibido no ZIP: {raw_name!r}.",
            parameters={"member": raw_name},
        )

    trimmed = raw_name[:-1] if (is_dir and raw_name.endswith("/")) else raw_name
    if not trimmed:
        raise ValidationError(f"Entrada de diretório inválida no ZIP: {raw_name!r}.")

    parts = trimmed.split("/")
    for seg in parts:
        if seg in ("", ".", ".."):
            raise ValidationError(
                message=f"Path traversal ou segmento inválido detectado no ZIP: {raw_name!r}.",
                parameters={"member": raw_name},
            )
    if ":" in parts[0]:
        raise ValidationError(f"Prefixo inválido no primeiro segmento ZIP: {raw_name!r}.")

    return trimmed


def _prevalidate_zip_entries(
    infos: Sequence[zipfile.ZipInfo],
    *,
    max_members: int,
    max_member_bytes: int,
    max_uncompressed_bytes: int,
    max_compression_ratio: float,
    min_bytes_for_ratio: int,
) -> dict[str, zipfile.ZipInfo]:
    if len(infos) == 0:
        raise ValidationError("Arquivo ZIP .ctrlab está vazio.")
    if len(infos) > max_members:
        raise ResourceLimitError(
            message=f"Contêiner .ctrlab excede limite de membros ({len(infos)} > {max_members}).",
            parameters={"member_count": len(infos), "max_members": max_members},
        )

    seen_raw: set[str] = set()
    seen_nfc: set[str] = set()
    seen_casefold: set[str] = set()
    file_entries: dict[str, zipfile.ZipInfo] = {}
    total_header_bytes = 0

    for info in infos:
        if info.flag_bits & 0x1:
            raise ValidationError(f"Entrada ZIP criptografada não é suportada: {info.filename!r}.")

        unix_mode = (info.external_attr >> 16) & 0xFFFF
        ftype = stat.S_IFMT(unix_mode)
        if stat.S_ISLNK(unix_mode):
            raise ValidationError(
                message=f"Symlink proibido detectado no ZIP: {info.filename!r}.",
                parameters={"member": info.filename},
            )
        if ftype != 0:
            if info.is_dir():
                if ftype != stat.S_IFDIR:
                    raise ValidationError(f"Entrada de diretório ZIP com tipo inválido: {info.filename!r}.")
            elif ftype != stat.S_IFREG:
                raise ValidationError(f"Arquivo especial proibido no ZIP: {info.filename!r}.")

        norm_path = _validate_archive_path_string(info.filename, is_dir=info.is_dir())
        if info.is_dir():
            if info.file_size != 0 or info.compress_size != 0:
                raise ValidationError(f"Entrada de diretório ZIP não pode ter conteúdo: {info.filename!r}.")

        if info.filename in seen_raw:
            raise ValidationError(f"Entrada duplicada no arquivo ZIP: {info.filename!r}.")
        seen_raw.add(info.filename)

        nfc = unicodedata.normalize("NFC", norm_path)
        if nfc in seen_nfc:
            raise ValidationError(
                message=f"Colisão de nomes após normalização Unicode NFC no ZIP: {info.filename!r}.",
                parameters={"member": info.filename, "nfc": nfc},
            )
        seen_nfc.add(nfc)

        cf = nfc.casefold()
        if cf in seen_casefold:
            raise ValidationError(
                message=f"Colisão de nomes case-folded no ZIP: {info.filename!r}.",
                parameters={"member": info.filename},
            )
        seen_casefold.add(cf)

        if not info.is_dir():
            if info.file_size > max_member_bytes:
                raise ResourceLimitError(
                    message=(
                        f"Membro {info.filename!r} excede max_member_bytes "
                        f"({info.file_size} > {max_member_bytes})."
                    ),
                    parameters={"member": info.filename, "file_size": info.file_size, "limit": max_member_bytes},
                )
            total_header_bytes += info.file_size
            if total_header_bytes > max_uncompressed_bytes:
                raise ResourceLimitError(
                    message=(
                        f"Tamanho total declarado no ZIP excede max_uncompressed_bytes "
                        f"({total_header_bytes} > {max_uncompressed_bytes})."
                    ),
                    parameters={"total_bytes": total_header_bytes, "limit": max_uncompressed_bytes},
                )
            if info.file_size >= min_bytes_for_ratio:
                if info.compress_size == 0 or (info.file_size / info.compress_size) > max_compression_ratio:
                    raise ResourceLimitError(
                        message=f"Suspeita de ZIP bomb (razão de compressão excessiva em {info.filename!r}).",
                        parameters={
                            "member": info.filename,
                            "file_size": info.file_size,
                            "compress_size": info.compress_size,
                            "max_ratio": max_compression_ratio,
                        },
                    )
            file_entries[norm_path] = info

    return file_entries


def _read_zip_member_bounded(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_member_bytes: int,
    remaining_total_bytes: int,
    max_compression_ratio: float,
    min_bytes_for_ratio: int,
) -> bytes:
    """Lê membro ZIP em streaming com verificação contínua contra ZIP bomb (não confia no cabeçalho)."""
    chunk_size = min(16384, max(1024, max_member_bytes + 1))
    chunks: list[bytes] = []
    member_bytes = 0
    try:
        with zf.open(info, "r") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                member_bytes += len(chunk)
                if member_bytes > max_member_bytes:
                    raise ResourceLimitError(
                        message=f"Membro {info.filename!r} ultrapassou {max_member_bytes} bytes durante leitura.",
                        parameters={"member": info.filename, "limit": max_member_bytes},
                    )
                if member_bytes > remaining_total_bytes:
                    raise ResourceLimitError(
                        message="Tamanho descompactado acumulado excedeu max_uncompressed_bytes.",
                        parameters={"member": info.filename},
                    )
                if member_bytes >= min_bytes_for_ratio:
                    if info.compress_size == 0 or (member_bytes / info.compress_size) > max_compression_ratio:
                        raise ResourceLimitError(
                            message=(
                                f"ZIP bomb detectada durante descompressão de {info.filename!r}: "
                                f"razão > {max_compression_ratio:.1f}x."
                            ),
                            parameters={
                                "member": info.filename,
                                "actual_bytes": member_bytes,
                                "compress_size": info.compress_size,
                                "max_ratio": max_compression_ratio,
                            },
                        )
                chunks.append(chunk)
    except ControlLabError:
        raise
    except (zipfile.BadZipFile, zlib.error, RuntimeError, OSError, EOFError, ValueError) as exc:
        raise ValidationError(
            message=f"Falha ao ler membro ZIP {info.filename!r}: {exc}",
            parameters={"member": info.filename},
        ) from exc
    return b"".join(chunks)


def _read_archive_bytes(
    source: str | Path | bytes | bytearray | memoryview | IO[bytes],
    *,
    max_archive_bytes: int,
) -> bytes:
    if isinstance(source, (bytes, bytearray, memoryview)):
        raw = bytes(source)
        if len(raw) > max_archive_bytes:
            raise ResourceLimitError(f"Arquivo .ctrlab excede limite de {max_archive_bytes} bytes.")
        return raw

    if isinstance(source, (str, Path)):
        try:
            path = Path(source)
            if not path.exists() or not path.is_file():
                raise ValidationError(f"Arquivo .ctrlab não encontrado: {path}")
            size = path.stat().st_size
            if size > max_archive_bytes:
                raise ResourceLimitError(
                    f"Arquivo .ctrlab excede limite de {max_archive_bytes} bytes ({size} bytes)."
                )
            return path.read_bytes()
        except ControlLabError:
            raise
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Falha ao acessar arquivo .ctrlab: {exc}") from exc

    read_fn = getattr(source, "read", None)
    if callable(read_fn):
        try:
            if hasattr(source, "seek"):
                source.seek(0)
            raw = read_fn(max_archive_bytes + 1)
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Falha ao ler stream .ctrlab: {exc}") from exc
        if not isinstance(raw, (bytes, bytearray)):
            raise ValidationError("Stream .ctrlab deve retornar bytes.")
        if len(raw) > max_archive_bytes:
            raise ResourceLimitError(f"Stream .ctrlab excede limite de {max_archive_bytes} bytes.")
        return bytes(raw)

    raise ValidationError(f"Tipo de entrada inválido para .ctrlab: {type(source).__name__}")


def _sanitize_dataset_filename(ds_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", ds_id).strip("._")
    return cleaned or "dataset"


def _infer_capabilities(
    models: Sequence[Any],
    controllers: Sequence[Any],
    experiments: Sequence[Any],
    has_csv: bool,
    has_plots: bool,
    has_pvm: bool,
    max_uncompressed_bytes: int,
    max_members: int,
) -> dict[str, Any]:
    req: list[str] = ["core.serialization"]
    opt: list[str] = []

    def _add_req(feat: str) -> None:
        if feat not in req:
            req.append(feat)

    for m in models:
        if isinstance(m, StateSpace):
            _add_req("core.state_space")
        elif isinstance(m, TransferFunction):
            _add_req("core.transfer_function")
        elif isinstance(m, Dataset):
            _add_req("core.dataset")
        elif isinstance(m, IdentifiedModel):
            _add_req("core.identified_model")
        elif isinstance(m, TSStateSpace):
            _add_req(f"core.{m.kind}")
        elif isinstance(m, FuzzySystem):
            _add_req("core.fuzzy_system")
        else:
            _add_req("core.model")

    for c in controllers:
        if isinstance(c, StateFeedbackController):
            _add_req("core.state_feedback_controller")
        elif isinstance(c, DynamicController):
            _add_req("core.dynamic_controller")
        elif isinstance(c, PDCController):
            _add_req("core.pdc_controller")
        else:
            _add_req("core.controller")

    if experiments:
        _add_req("core.experiment")
    if has_pvm:
        _add_req("io.pvm_v1")
    if has_csv:
        opt.append("datasets.csv")
    if has_plots:
        opt.append("artifacts.plots")

    return {
        "required_features": req,
        "optional_features": opt,
        "max_uncompressed_bytes": int(max_uncompressed_bytes),
        "max_members": int(max_members),
    }


def _normalize_subpath(prefix: str, key: str) -> str:
    norm = _validate_archive_path_string(key, is_dir=False)
    if norm.startswith(prefix):
        return norm
    return f"{prefix}{norm}"


def _prepare_ctrlab_package(
    project: Mapping[str, Any] | None = None,
    *,
    project_id: str | None = None,
    project_revision: int | None = None,
    models: Sequence[Any] | None = None,
    controllers: Sequence[Any] | None = None,
    experiments: Sequence[Any] | None = None,
    datasets: Mapping[str, Any] | Sequence[Dataset] | None = None,
    plots: Mapping[str, str | bytes] | None = None,
    exports: Mapping[str, Any] | None = None,
    created_at: str | None = None,
    modified_at: str | None = None,
    app_version: str = CTRLAB_APP_VERSION,
    schema_version: str = CTRLAB_SCHEMA_VERSION,
    required_features: Sequence[str] | None = None,
    optional_features: Sequence[str] | None = None,
    provenance: Mapping[str, Any] | None = None,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    auto_export_dataset_csv: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    if project is not None and not isinstance(project, Mapping):
        raise ValidationError("project deve ser um Mapping ou None.")
    proj = dict(project) if project is not None else {}

    res_project_id = validate_non_empty_str(
        project_id if project_id is not None else proj.get("project_id", "controllab-project"),
        field_name="project_id",
    )
    res_project_rev = validate_revision(
        project_revision if project_revision is not None else proj.get("project_revision", 0),
        field_name="project_revision",
    )
    validate_schema_version(schema_version, field_name="schema_version")
    validate_non_empty_str(app_version, field_name="app_version")

    res_created_at = _validate_iso_datetime(
        created_at if created_at is not None else proj.get("created_at", DEFAULT_CREATED_AT),
        field_name="created_at",
    )
    raw_mod_at = modified_at if modified_at is not None else proj.get("modified_at")
    res_modified_at = (
        _validate_iso_datetime(raw_mod_at, field_name="modified_at") if raw_mod_at is not None else None
    )

    raw_models = list(models if models is not None else proj.get("models", ()))
    raw_ctrls = list(controllers if controllers is not None else proj.get("controllers", ()))
    raw_exps = list(experiments if experiments is not None else proj.get("experiments", ()))
    raw_datasets = datasets if datasets is not None else proj.get("datasets")
    raw_plots = plots if plots is not None else proj.get("plots")
    raw_exports = exports if exports is not None else proj.get("exports")

    # Armazenamento de membros adicionais: path -> bytes
    extra_members: dict[str, bytes] = {}
    dataset_objs_seen: set[tuple[str, int]] = {
        (m.id, m.revision) for m in raw_models if isinstance(m, Dataset)
    }

    if raw_datasets is not None:
        if isinstance(raw_datasets, Sequence) and not isinstance(raw_datasets, (str, bytes)):
            for ds_item in raw_datasets:
                if not isinstance(ds_item, Dataset):
                    raise ValidationError("Sequência datasets deve conter apenas instâncias Dataset.")
                if (ds_item.id, ds_item.revision) not in dataset_objs_seen:
                    raw_models.append(ds_item)
                    dataset_objs_seen.add((ds_item.id, ds_item.revision))
                csv_path = f"datasets/{_sanitize_dataset_filename(ds_item.id)}.csv"
                extra_members[csv_path] = dataset_to_csv(ds_item).encode("utf-8")
        elif isinstance(raw_datasets, Mapping):
            for k, v in raw_datasets.items():
                csv_path = _normalize_subpath("datasets/", str(k))
                if isinstance(v, Dataset):
                    if (v.id, v.revision) not in dataset_objs_seen:
                        raw_models.append(v)
                        dataset_objs_seen.add((v.id, v.revision))
                    extra_members[csv_path] = dataset_to_csv(v).encode("utf-8")
                elif isinstance(v, str):
                    extra_members[csv_path] = v.encode("utf-8")
                elif isinstance(v, bytes):
                    extra_members[csv_path] = v
                else:
                    raise ValidationError(
                        f"datasets[{k!r}] deve ser Dataset, str ou bytes, recebido {type(v).__name__}."
                    )
        else:
            raise ValidationError("datasets deve ser Mapping ou Sequence[Dataset].")

    if auto_export_dataset_csv:
        for m in raw_models:
            if isinstance(m, Dataset):
                csv_path = f"datasets/{_sanitize_dataset_filename(m.id)}.csv"
                if csv_path not in extra_members:
                    extra_members[csv_path] = dataset_to_csv(m).encode("utf-8")

    if raw_plots is not None:
        if not isinstance(raw_plots, Mapping):
            raise ValidationError("plots deve ser Mapping caminho -> str/bytes.")
        for k, v in raw_plots.items():
            plot_path = _normalize_subpath("artifacts/plots/", str(k))
            if isinstance(v, str):
                extra_members[plot_path] = v.encode("utf-8")
            elif isinstance(v, bytes):
                extra_members[plot_path] = v
            else:
                raise ValidationError(f"plots[{k!r}] deve ser str ou bytes.")

    if raw_exports is not None:
        if not isinstance(raw_exports, Mapping):
            raise ValidationError("exports deve ser Mapping caminho -> dict/str/bytes.")
        for k, v in raw_exports.items():
            exp_path = _normalize_subpath("exports/", str(k))
            if isinstance(v, Mapping):
                if exp_path.endswith(".pvm"):
                    validate_pvm_structure(v, require_known_blocks=False)
                extra_members[exp_path] = (strict_json_dumps(v, indent=2, sort_keys=True) + "\n").encode("utf-8")
            elif isinstance(v, str):
                if exp_path.endswith(".pvm"):
                    validate_pvm_structure(_safe_strict_json_loads(v, context=exp_path), require_known_blocks=False)
                extra_members[exp_path] = v.encode("utf-8")
            elif isinstance(v, bytes):
                if exp_path.endswith(".pvm"):
                    validate_pvm_structure(_safe_strict_json_loads(v, context=exp_path), require_known_blocks=False)
                extra_members[exp_path] = v
            else:
                raise ValidationError(f"exports[{k!r}] deve ser Mapping, str ou bytes.")

    ser_models = [serialize_model(m) for m in raw_models]
    ser_ctrls = [serialize_model(c) for c in raw_ctrls]
    ser_exps = [serialize_model(e) for e in raw_exps]

    # Validar compatibilidade restaurável antes de gerar o ZIP
    for m_dict in ser_models:
        restore_model(m_dict)
    for c_dict in ser_ctrls:
        restore_model(c_dict)
    for e_dict in ser_exps:
        restore_model(e_dict)

    member_bytes: dict[str, bytes] = {
        "models.json": (
            strict_json_dumps({"schema_version": schema_version, "items": ser_models}, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "controllers.json": (
            strict_json_dumps({"schema_version": schema_version, "items": ser_ctrls}, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "experiments.json": (
            strict_json_dumps({"schema_version": schema_version, "items": ser_exps}, sort_keys=True) + "\n"
        ).encode("utf-8"),
    }
    for ep in sorted(extra_members.keys()):
        if ep in ("manifest.json", *member_bytes.keys()):
            raise ValidationError(f"Caminho reservado não pode ser sobrescrito: {ep!r}.")
        member_bytes[ep] = extra_members[ep]

    # Prevalidar colisões Unicode NFC / casefold em membros produzidos
    seen_nfc: set[str] = set()
    seen_cf: set[str] = set()
    for p_str in ("manifest.json", *member_bytes.keys()):
        nfc = unicodedata.normalize("NFC", p_str)
        cf = nfc.casefold()
        if nfc in seen_nfc or cf in seen_cf:
            raise ValidationError(f"Colisão de caminhos na exportação .ctrlab: {p_str!r}.")
        seen_nfc.add(nfc)
        seen_cf.add(cf)

    hashes = {
        path_key: hashlib.sha256(payload).hexdigest()
        for path_key, payload in sorted(member_bytes.items())
    }

    has_csv = any(p.startswith("datasets/") for p in member_bytes)
    has_plots = any(p.startswith("artifacts/plots/") for p in member_bytes)
    has_pvm = any(p.startswith("exports/") and p.endswith(".pvm") for p in member_bytes)

    caps = _infer_capabilities(
        raw_models,
        raw_ctrls,
        raw_exps,
        has_csv=has_csv,
        has_plots=has_plots,
        has_pvm=has_pvm,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_members=max_members,
    )
    if required_features is not None:
        caps["required_features"] = [
            validate_non_empty_str(f, field_name="required_features[]") for f in required_features
        ]
    if optional_features is not None:
        caps["optional_features"] = [
            validate_non_empty_str(f, field_name="optional_features[]") for f in optional_features
        ]

    prov_dict = (
        ensure_json_finite(dict(provenance), path="$.provenance")
        if provenance is not None
        else {"source": "control_lab.io.ctrlab", "deterministic": True}
    )

    manifest: dict[str, Any] = {
        "format": CTRLAB_FORMAT,
        "schema_version": schema_version,
        "app_version": app_version,
        "created_at": res_created_at,
        "project_id": res_project_id,
        "project_revision": res_project_rev,
        "hashes": hashes,
        "capabilities": caps,
        "contents": {
            "models_count": len(ser_models),
            "controllers_count": len(ser_ctrls),
            "experiments_count": len(ser_exps),
            "datasets": sorted(p for p in member_bytes if p.startswith("datasets/")),
            "artifacts": sorted(p for p in member_bytes if p.startswith("artifacts/")),
            "exports": sorted(p for p in member_bytes if p.startswith("exports/")),
        },
        "provenance": prov_dict,
    }
    if res_modified_at is not None:
        manifest["modified_at"] = res_modified_at

    manifest = validate_ctrlab_manifest(manifest)
    manifest_bytes = (strict_json_dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

    all_entries: list[tuple[str, bytes]] = [("manifest.json", manifest_bytes)]
    for path_key in sorted(member_bytes.keys()):
        all_entries.append((path_key, member_bytes[path_key]))

    if len(all_entries) > max_members:
        raise ResourceLimitError(
            f"Contagem de membros ({len(all_entries)}) excede max_members ({max_members})."
        )
    total_uncompressed = sum(len(b) for _, b in all_entries)
    if total_uncompressed > max_uncompressed_bytes:
        raise ResourceLimitError(
            f"Tamanho descompactado ({total_uncompressed}) excede max_uncompressed_bytes ({max_uncompressed_bytes})."
        )

    zip_dt = _zip_datetime_from_iso(res_created_at)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for arcname, payload in all_entries:
            zinfo = zipfile.ZipInfo(filename=arcname, date_time=zip_dt)
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zinfo.create_system = 3
            zinfo.external_attr = (stat.S_IFREG | 0o644) << 16
            zf.writestr(zinfo, payload)

    zip_raw = buf.getvalue()
    if len(zip_raw) > max_archive_bytes:
        raise ResourceLimitError(
            f"Arquivo .ctrlab compactado ({len(zip_raw)} bytes) excede max_archive_bytes ({max_archive_bytes})."
        )
    return zip_raw, manifest


def export_ctrlab_bytes(
    project: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> bytes:
    """Exporta projeto ControlLab para bytes ZIP `.ctrlab` determinísticos."""
    raw, _ = _prepare_ctrlab_package(project, **kwargs)
    return raw


def export_ctrlab(
    project: Mapping[str, Any] | None = None,
    *,
    output_path: str | Path | None = None,
    include_base64: bool = False,
    raise_on_error: bool = False,
    **kwargs: Any,
) -> Result:
    """Exporta `.ctrlab` encapsulado em `Result` (opcionalmente gravando em arquivo)."""
    prov: Provenance = build_provenance("control_lab.io.export_ctrlab")
    try:
        raw, manifest = _prepare_ctrlab_package(project, **kwargs)
        sha = hashlib.sha256(raw).hexdigest()
        data: dict[str, Any] = {
            "manifest": manifest,
            "size_bytes": len(raw),
            "sha256": sha,
        }
        if include_base64:
            data["zip_base64"] = base64.b64encode(raw).decode("ascii")
        if output_path is not None:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_bytes(raw)
            data["path"] = str(out_p)
        return Result(
            status="success",
            data=data,
            assumptions={"deterministic_package": True, "format": CTRLAB_FORMAT},
            diagnostics={
                "size_bytes": len(raw),
                "members_count": len(manifest["hashes"]) + 1,
                "sha256": sha,
            },
            provenance=prov,
            warnings=(),
            error=None,
        )
    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions={"format": CTRLAB_FORMAT},
            diagnostics={},
            provenance=prov,
            error=exc.to_typed_error(),
        )


def save_ctrlab(
    path: str | Path,
    project: Mapping[str, Any] | None = None,
    *,
    raise_on_error: bool = False,
    **kwargs: Any,
) -> Result:
    """Grava contêiner `.ctrlab` ZIP determinístico em `path` retornando `Result`."""
    return export_ctrlab(
        project,
        output_path=path,
        include_base64=False,
        raise_on_error=raise_on_error,
        **kwargs,
    )


def _load_ctrlab_internal(
    source: str | Path | bytes | bytearray | memoryview | IO[bytes],
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
    min_bytes_for_ratio: int = DEFAULT_MIN_BYTES_FOR_RATIO,
    inspect_only: bool = False,
) -> dict[str, Any]:
    if max_archive_bytes < 1 or max_uncompressed_bytes < 1 or max_member_bytes < 1 or max_members < 1:
        raise ValidationError("Limites de leitura .ctrlab devem ser inteiros positivos.")
    if max_compression_ratio <= 1.0 or not math.isfinite(max_compression_ratio):
        raise ValidationError("max_compression_ratio deve ser finito > 1.0.")

    archive_bytes = _read_archive_bytes(source, max_archive_bytes=max_archive_bytes)
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r")
    except (zipfile.BadZipFile, zlib.error, OSError, ValueError) as exc:
        raise ValidationError(f"Arquivo .ctrlab não é um ZIP válido: {exc}") from exc

    with zf:
        infos = zf.infolist()
        file_entries = _prevalidate_zip_entries(
            infos,
            max_members=max_members,
            max_member_bytes=max_member_bytes,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_compression_ratio=max_compression_ratio,
            min_bytes_for_ratio=min_bytes_for_ratio,
        )
        if "manifest.json" not in file_entries:
            raise ValidationError("Contêiner .ctrlab não contém 'manifest.json' obrigatório.")

        remaining_bytes = max_uncompressed_bytes
        raw_members: dict[str, bytes] = {}
        actual_hashes: dict[str, str] = {}
        total_uncompressed = 0

        # Ler manifest.json primeiro via leitor limitado
        manifest_info = file_entries["manifest.json"]
        manifest_raw = _read_zip_member_bounded(
            zf,
            manifest_info,
            max_member_bytes=max_member_bytes,
            remaining_total_bytes=remaining_bytes,
            max_compression_ratio=max_compression_ratio,
            min_bytes_for_ratio=min_bytes_for_ratio,
        )
        remaining_bytes -= len(manifest_raw)
        total_uncompressed += len(manifest_raw)

        manifest_parsed = _safe_strict_json_loads(manifest_raw, context="manifest.json")
        manifest = validate_ctrlab_manifest(manifest_parsed)

        cap_max_members = manifest["capabilities"].get("max_members")
        if cap_max_members is not None and len(infos) > int(cap_max_members):
            raise ResourceLimitError(
                f"Número de entradas ({len(infos)}) excede capabilities.max_members ({cap_max_members})."
            )
        cap_max_bytes = manifest["capabilities"].get("max_uncompressed_bytes")
        effective_max_uncompressed = (
            min(max_uncompressed_bytes, int(cap_max_bytes))
            if cap_max_bytes is not None
            else max_uncompressed_bytes
        )
        if total_uncompressed > effective_max_uncompressed:
            raise ResourceLimitError("manifest.json excede max_uncompressed_bytes declarado.")
        remaining_bytes = effective_max_uncompressed - total_uncompressed

        for arc_path, info in file_entries.items():
            if arc_path == "manifest.json":
                continue
            payload = _read_zip_member_bounded(
                zf,
                info,
                max_member_bytes=max_member_bytes,
                remaining_total_bytes=remaining_bytes,
                max_compression_ratio=max_compression_ratio,
                min_bytes_for_ratio=min_bytes_for_ratio,
            )
            remaining_bytes -= len(payload)
            total_uncompressed += len(payload)
            raw_members[arc_path] = payload
            actual_hashes[arc_path] = hashlib.sha256(payload).hexdigest()

    # Verificar conjunto exato de hashes e integridade SHA-256
    declared_hashes = {k: v.lower() for k, v in manifest["hashes"].items()}
    if set(declared_hashes.keys()) != set(raw_members.keys()):
        missing_in_zip = sorted(set(declared_hashes.keys()) - set(raw_members.keys()))
        unhashed_in_zip = sorted(set(raw_members.keys()) - set(declared_hashes.keys()))
        raise ValidationError(
            message="Divergência entre membros do ZIP e manifest.hashes.",
            parameters={"missing_in_zip": missing_in_zip, "unhashed_in_zip": unhashed_in_zip},
        )
    for arc_path, expected_sha in declared_hashes.items():
        if actual_hashes[arc_path] != expected_sha:
            raise ValidationError(
                message=f"Falha de integridade SHA-256 em {arc_path!r}.",
                parameters={
                    "member": arc_path,
                    "expected_sha256": expected_sha,
                    "actual_sha256": actual_hashes[arc_path],
                },
            )

    for req_core in _CORE_REQUIRED_FILES:
        if req_core not in raw_members:
            raise ValidationError(f"Arquivo principal obrigatório ausente no .ctrlab: {req_core!r}.")

    if inspect_only:
        return {
            "manifest": manifest,
            "members": sorted(file_entries.keys()),
            "hashes_verified": True,
            "total_uncompressed_bytes": total_uncompressed,
            "archive_bytes": len(archive_bytes),
        }

    warnings_out: list[WarningItem] = []

    def _parse_collection(member_name: str) -> list[Any]:
        parsed = _safe_strict_json_loads(raw_members[member_name], context=member_name)
        if isinstance(parsed, Mapping):
            if "schema_version" in parsed:
                validate_schema_version(parsed["schema_version"], field_name=f"{member_name}.schema_version")
            items = parsed.get("items")
            if not isinstance(items, list):
                raise ValidationError(f"{member_name}.items deve ser uma lista.")
        elif isinstance(parsed, list):
            items = parsed
        else:
            raise ValidationError(f"{member_name} deve ser objeto JSON com 'items' ou lista JSON.")
        return [restore_model(item) for item in items]

    models_obj = _parse_collection("models.json")
    controllers_obj = _parse_collection("controllers.json")
    experiments_obj = _parse_collection("experiments.json")

    datasets_out: dict[str, dict[str, Any]] = {}
    artifacts_out: dict[str, dict[str, Any]] = {}
    exports_out: dict[str, dict[str, Any]] = {}

    for arc_path in sorted(raw_members.keys()):
        if arc_path in _CORE_REQUIRED_FILES:
            continue
        payload = raw_members[arc_path]
        ext = Path(arc_path).suffix.lower()

        if ext in _SCRIPT_EXTS:
            warnings_out.append(
                WarningItem(
                    code="UNTRUSTED_EMBEDDED_FILE_IGNORED",
                    message=f"Arquivo executável/script {arc_path!r} não foi executado (importação passiva).",
                    details={"member": arc_path, "code_executed": False},
                )
            )

        if arc_path.startswith("datasets/") and ext in (".csv", ".tsv"):
            try:
                csv_text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValidationError(f"Dataset CSV/TSV {arc_path!r} não é UTF-8 válido.") from exc
            parsed_ds = parse_csv_dataset(csv_text, delimiter="\t" if ext == ".tsv" else None)
            datasets_out[arc_path] = {
                "content": csv_text,
                "dataset": parsed_ds,
                "sha256": actual_hashes[arc_path],
            }
        elif arc_path.startswith("exports/") and ext == ".pvm":
            pvm_res = import_pvm(payload, raise_on_error=True)
            assert pvm_res.data is not None
            for w in pvm_res.warnings:
                if isinstance(w, WarningItem):
                    warnings_out.append(w)
            exports_out[arc_path] = {
                "pvm": pvm_res.data["pvm"],
                "code_executed": False,
                "sha256": actual_hashes[arc_path],
            }
        elif arc_path.startswith("artifacts/"):
            if ext == ".svg":
                try:
                    svg_text = payload.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValidationError(f"Artefato SVG {arc_path!r} não é UTF-8 válido.") from exc
                if _SVG_UNSAFE_RE.search(svg_text):
                    warnings_out.append(
                        WarningItem(
                            code="UNTRUSTED_SVG_CONTENT_DETECTED",
                            message=f"SVG {arc_path!r} contém marcação ativa potencial (script/handler); não executado.",
                            details={"member": arc_path, "code_executed": False},
                        )
                    )
                artifacts_out[arc_path] = {
                    "content": svg_text,
                    "media_type": "image/svg+xml",
                    "sha256": actual_hashes[arc_path],
                }
            else:
                artifacts_out[arc_path] = {
                    "base64": base64.b64encode(payload).decode("ascii"),
                    "size_bytes": len(payload),
                    "sha256": actual_hashes[arc_path],
                }
        else:
            # Outros arquivos (validados por hash e path traversal; lidos passivamente)
            try:
                text_val = payload.decode("utf-8")
                artifacts_out[arc_path] = {"content": text_val, "sha256": actual_hashes[arc_path]}
            except UnicodeDecodeError:
                artifacts_out[arc_path] = {
                    "base64": base64.b64encode(payload).decode("ascii"),
                    "size_bytes": len(payload),
                    "sha256": actual_hashes[arc_path],
                }

    return {
        "manifest": manifest,
        "models": models_obj,
        "controllers": controllers_obj,
        "experiments": experiments_obj,
        "datasets": datasets_out,
        "artifacts": artifacts_out,
        "exports": exports_out,
        "warnings": warnings_out,
        "total_uncompressed_bytes": total_uncompressed,
        "archive_bytes": len(archive_bytes),
    }


def inspect_ctrlab(
    source: str | Path | bytes | bytearray | memoryview | IO[bytes],
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
    min_bytes_for_ratio: int = DEFAULT_MIN_BYTES_FOR_RATIO,
    raise_on_error: bool = False,
) -> Result:
    """Inspeciona passivamente um contêiner `.ctrlab` (sem extrair em disco e sem executar scripts)."""
    prov: Provenance = build_provenance("control_lab.io.inspect_ctrlab")
    assumptions: dict[str, Any] = {
        "passive_inspection": True,
        "disk_extraction": False,
        "code_executed": False,
    }
    try:
        info = _load_ctrlab_internal(
            source,
            max_archive_bytes=max_archive_bytes,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_member_bytes=max_member_bytes,
            max_members=max_members,
            max_compression_ratio=max_compression_ratio,
            min_bytes_for_ratio=min_bytes_for_ratio,
            inspect_only=True,
        )
        return Result(
            status="success",
            data=info,
            assumptions=assumptions,
            diagnostics={
                "hashes_verified": True,
                "members_count": len(info["members"]),
                "total_uncompressed_bytes": info["total_uncompressed_bytes"],
                "archive_bytes": info["archive_bytes"],
            },
            provenance=prov,
            warnings=(),
            error=None,
        )
    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions=assumptions,
            diagnostics={},
            provenance=prov,
            warnings=(),
            error=exc.to_typed_error(),
        )


def load_ctrlab_objects(
    source: str | Path | bytes | bytearray | memoryview | IO[bytes],
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
    min_bytes_for_ratio: int = DEFAULT_MIN_BYTES_FOR_RATIO,
) -> dict[str, Any]:
    """Carrega passivamente o `.ctrlab` retornando instâncias Python tipadas vivas (ou levanta ControlLabError)."""
    return _load_ctrlab_internal(
        source,
        max_archive_bytes=max_archive_bytes,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_member_bytes=max_member_bytes,
        max_members=max_members,
        max_compression_ratio=max_compression_ratio,
        min_bytes_for_ratio=min_bytes_for_ratio,
        inspect_only=False,
    )


def load_ctrlab(
    source: str | Path | bytes | bytearray | memoryview | IO[bytes],
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
    min_bytes_for_ratio: int = DEFAULT_MIN_BYTES_FOR_RATIO,
    raise_on_error: bool = False,
) -> Result:
    """Importação 100% passiva de `.ctrlab` encapsulada em `Result` (Seção 9.1 e T-IO-01)."""
    prov: Provenance = build_provenance("control_lab.io.load_ctrlab")
    assumptions: dict[str, Any] = {
        "passive_import": True,
        "disk_extraction": False,
        "code_executed": False,
    }
    try:
        loaded = _load_ctrlab_internal(
            source,
            max_archive_bytes=max_archive_bytes,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_member_bytes=max_member_bytes,
            max_members=max_members,
            max_compression_ratio=max_compression_ratio,
            min_bytes_for_ratio=min_bytes_for_ratio,
            inspect_only=False,
        )
        warnings_out: list[WarningItem] = list(loaded["warnings"])
        data_out: dict[str, Any] = {
            "manifest": loaded["manifest"],
            "models": [serialize_model(m) for m in loaded["models"]],
            "controllers": [serialize_model(c) for c in loaded["controllers"]],
            "experiments": [serialize_model(e) for e in loaded["experiments"]],
            "datasets": {
                k: {
                    "content": v["content"],
                    "dataset": serialize_model(v["dataset"]),
                    "sha256": v["sha256"],
                }
                for k, v in loaded["datasets"].items()
            },
            "artifacts": loaded["artifacts"],
            "exports": loaded["exports"],
            "code_executed": False,
        }
        return Result(
            status="warning" if warnings_out else "success",
            data=data_out,
            assumptions=assumptions,
            diagnostics={
                "hashes_verified": True,
                "code_executed": False,
                "models_count": len(loaded["models"]),
                "controllers_count": len(loaded["controllers"]),
                "experiments_count": len(loaded["experiments"]),
                "datasets_count": len(loaded["datasets"]),
                "total_uncompressed_bytes": loaded["total_uncompressed_bytes"],
                "archive_bytes": loaded["archive_bytes"],
            },
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions=assumptions,
            diagnostics={"code_executed": False},
            provenance=prov,
            warnings=(),
            error=exc.to_typed_error(),
        )
