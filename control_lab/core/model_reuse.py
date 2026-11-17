"""Lossless model reuse, version 1.0.0 (CL-DIR-001 R-03/R-06/R-27).

Derivation creates a separate deterministic identity at revision zero. It never
registers a model, changes sampling time, minimizes a realization, approximates a
delay, or certifies identification quality. Consumers register the returned DTO
using their project-scoped store before sending its ModelRef to other operations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from control_lab.diagnostics import (
    ControlLabError,
    Result,
    TypedError,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .models import IdentifiedModel, StateSpace, TSStateSpace, TransferFunction
from .serialization import restore_model
from .tensors import compute_canonical_sha256

MODEL_REUSE_VERSION = "1.0.0"
_IDENTITY_POLICY = "derived_new_identity_revision_zero"


def reuse_model(
    source: Any, *, target_kind: str = "native", raise_on_error: bool = False
) -> Result:
    """Extract/convert a canonical model without changing its time-domain meaning.

    ``native`` copies the identified inner model's canonical representation.
    ``StateSpace`` realizes a proper TF exactly through ``to_state_space``;
    TS-to-LTI conversion is explicitly unsupported. The caller cannot override
    sampling time, identity or revision. Full source content and the resulting
    representation enter the identity hash, including identification provenance.
    Source creation timestamps and optional hashes are retained in lineage, not
    copied as a fresh derived object's timestamp/hash. Errors return Result.
    """
    prov = build_provenance("core.reuse_model", reuse_version=MODEL_REUSE_VERSION)
    try:
        if not isinstance(target_kind, str) or target_kind not in ("native", "StateSpace"):
            raise ValidationError("target_kind deve ser 'native' ou 'StateSpace'.")
        if isinstance(source, Mapping):
            source = restore_model(source)
        if not isinstance(source, (IdentifiedModel, StateSpace, TransferFunction, TSStateSpace)):
            raise UnsupportedModelError(
                "reuse_model requer IdentifiedModel ou modelo LTI/TS canônico."
            )
        source_dto = source.to_dict()
        inner = source.model if isinstance(source, IdentifiedModel) else source
        if isinstance(inner, Mapping):
            inner = restore_model(inner)
        if not isinstance(inner, (StateSpace, TransferFunction, TSStateSpace)):
            raise UnsupportedModelError(
                "IdentifiedModel.model deve ser StateSpace, TransferFunction ou TSStateSpace canônico."
            )
        inner_dto = inner.to_dict()
        changed = target_kind == "StateSpace" and not isinstance(inner, StateSpace)
        if changed and not isinstance(inner, TransferFunction):
            raise UnsupportedModelError(
                "TSStateSpace não pode ser reduzido implicitamente a StateSpace LTI."
            )
        if changed:
            # Derive warnings from coefficients, not arbitrary source metadata.
            conversion_input = inner.to_dict()
            conversion_input["provenance"] = {}
            output = TransferFunction.from_dict(conversion_input).to_state_space()
        else:
            output = inner
        source_ref = {"id": source.id, "revision": source.revision}
        inner_ref = {"id": inner.id, "revision": inner.revision}
        derivation = {
            "source_ref": source_ref,
            "source_model_ref": inner_ref,
            "source_kind": source.kind,
            "source_model_kind": inner.kind,
            "target_kind": target_kind,
            "representation_changed": changed,
            "time_domain_changed": False,
            "registration_required": True,
        }
        output_dto = output.to_dict()
        digest = compute_canonical_sha256(
            {
                "reuse_version": MODEL_REUSE_VERSION,
                "source": source_dto,
                "representation": output_dto,
                "target_kind": target_kind,
            }
        )
        output_dto["id"] = "reuse-" + digest
        output_dto["revision"] = 0
        output_dto.pop("content_hash", None)
        output_dto.pop("created_at", None)
        output_dto["provenance"] = {
            **inner.provenance,
            **output.provenance,
            "model_reuse": {
                "version": MODEL_REUSE_VERSION,
                "identity_policy": _IDENTITY_POLICY,
                **derivation,
                "source_metadata": {
                    k: source_dto[k]
                    for k in (
                        "schema_version",
                        "id",
                        "revision",
                        "kind",
                        "created_at",
                        "content_hash",
                        "provenance",
                        "algorithm",
                        "dataset_ref",
                        "partitions",
                        "metrics",
                        "noise_hypothesis",
                        "excitation_diagnostics",
                        "residual_diagnostics",
                        "covariance",
                    )
                    if k in source_dto
                },
                "source_model_provenance": inner_dto["provenance"],
            },
        }
        derived = restore_model(output_dto)
        warnings: list[WarningItem] = []
        if isinstance(inner, TransferFunction):
            warnings.extend(inner.warnings)
        if changed:
            # Conversion warnings are emitted by the existing scientific method;
            # arbitrary source provenance is never treated as a new certificate.
            warnings = [
                WarningItem.from_dict(w) for w in output.provenance.get("conversion_warnings", [])
            ]
        dimensions = {
            "n_states": getattr(derived, "n_states", None),
            "n_inputs": derived.n_inputs,
            "n_outputs": derived.n_outputs,
        }
        return Result(
            status="warning" if warnings else "success",
            data={
                "reuse_version": MODEL_REUSE_VERSION,
                "model": derived.to_dict(),
                "model_ref": {"id": derived.id, "revision": derived.revision},
                "source_ref": source_ref,
                "source_model_ref": inner_ref,
                "identity_policy": _IDENTITY_POLICY,
                "dt": derived.dt,
                "dimensions": dimensions,
                "derivation": derivation,
            },
            assumptions={"time_domain_preserved": True, "identification_quality_reassessed": False},
            diagnostics={"representation_changed": changed, "registration_required": True},
            provenance=build_provenance(
                "core.reuse_model",
                model_revision=source.revision,
                reuse_version=MODEL_REUSE_VERSION,
                **derivation,
            ),
            warnings=tuple(warnings),
        )
    except Exception as exc:
        if raise_on_error:
            raise
        error = (
            exc.to_typed_error()
            if isinstance(exc, ControlLabError)
            else TypedError(
                code="INTERNAL_ERROR",
                message=f"Falha na reutilização canônica: {type(exc).__name__}: {exc}",
            )
        )
        return Result(status="failure", data=None, provenance=prov, error=error)
