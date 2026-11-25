"""Dispatcher RPC científico canônico em Python para CPython e Pyodide/Worker (CL-DIR-001 Seções 7.2, 8.2, 13.3).

Valida estritamente envelopes `RpcRequest` contra `rpc_request.schema.json`,
despacha exclusivamente às implementações científicas reais (`control_lab.statespace`,
`control_lab.frequency`, `control_lab.identification`, `control_lab.fuzzy`,
`control_lab.optimization`, `control_lab.core`) e serializa envelopes `RpcResponse`
100% conformes a `rpc_response.schema.json`, preservando erros tipados e proveniência.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Mapping
from typing import Any

import numpy as np

from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    NumericalInconclusiveError,
    Provenance,
    Result,
    SchemaUnsupportedError,
    TypedError,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
    default_lib_versions,
    ensure_json_finite,
    strict_json_loads,
)

from .controllers import DynamicController, PDCController, StateFeedbackController
from .interconnect import interconnect, validate_interconnection
from .models import (
    Dataset,
    Experiment,
    FuzzySystem,
    IdentifiedModel,
    StateSpace,
    TSStateSpace,
    TransferFunction,
)
from .serialization import restore_model
from .tensors import array_to_tensor, ensure_finite_float64, pair_to_complex, tensor_to_array

RPC_API_VERSION = "1.0"

_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_REQUIRED_REQUEST_KEYS = frozenset(
    {
        "api_version",
        "request_id",
        "project_id",
        "project_revision",
        "operation",
        "payload",
        "options",
        "timeout_policy",
    }
)
_RESPONSE_STATUSES = frozenset({"success", "warning", "inconclusive", "failure"})
_UNSET: Any = object()

SUPPORTED_OPERATIONS: frozenset[str] = frozenset(
    {
        "worker.ping",
        "rpc.ping",
        "worker.get_stats",
        "core.capabilities",
        "core.reuse_model",
        "rpc.capabilities",
        "io.export_ctrlab",
        "io.import_ctrlab",
        "io.export_pvm",
        "io.import_pvm",
        "io.export_pathsim_script",
        "core.interconnect",
        "core.validate_interconnection",
        "statespace.design_lqr",
        "statespace.design_lqi",
        "statespace.design_pole_placement",
        "statespace.design_observer",
        "statespace.design_kalman",
        "statespace.design_lqg",
        "statespace.analyze",
        "statespace.check_pbh",
        "statespace.gramians",
        "statespace.solve_care",
        "statespace.solve_dare",
        "statespace.solve_lyapunov",
        "statespace.solve_sylvester",
        "statespace.discretize_zoh",
        "statespace.simulate_lti",
        "frequency.eval_response",
        "frequency.bode",
        "frequency.stability_margins",
        "frequency.root_locus",
        "frequency.step_response",
        "frequency.singular_values",
        "mimo.singular_values",
        "mimo.rga",
        "mimo.sensitivity",
        "mimo.design_decoupler",
        "mimo.simulate_closed_loop",
        "mimo.design_hinf",
        "identification.fit_arx",
        "identification.fit_oe",
        "identification.fit_subspace",
        "identification.validate_model",
        "fuzzy.evaluate",
        "fuzzy.evaluate_surface",
        "fuzzy.fit_anfis",
        "fuzzy.import_fml",
        "fuzzy.export_fml",
        "fuzzy.analyze_sector_premises",
        "fuzzy.derive_ts_sector",
        "fuzzy.derive_ts_tpmt",
        "fuzzy.derive_ts_femt",
        "fuzzy.export_ts_derivation_script",
        "optimization.export_cvxpy",
        "optimization.export_yalmip",
        "optimization.solve",
        "optimization.verify",
        "optimization.capabilities",
    }
)


def _is_non_bool_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _to_python_native(obj: Any) -> Any:
    """Converte JsProxy do Pyodide (se aplicável) para objetos Python puros."""
    to_py = getattr(obj, "to_py", None)
    if callable(to_py) and not isinstance(obj, (dict, list, tuple, set, str, bytes)):
        return to_py()
    return obj


def _extract_fallback_envelope(raw: Any) -> tuple[str, str, int]:
    req_id = "invalid-request"
    proj_id = "invalid-project"
    proj_rev = 0
    if isinstance(raw, Mapping):
        cand_id = raw.get("request_id")
        if isinstance(cand_id, str) and len(cand_id.strip()) > 0:
            req_id = cand_id
        cand_proj = raw.get("project_id")
        if isinstance(cand_proj, str) and len(cand_proj.strip()) > 0:
            proj_id = cand_proj
        cand_rev = raw.get("project_revision")
        if _is_non_bool_int(cand_rev) and cand_rev >= 0:
            proj_rev = int(cand_rev)
    return req_id, proj_id, proj_rev


def _normalize_provenance_dict(
    prov: Provenance | Mapping[str, Any] | None,
    *,
    algorithm: str,
    model_revision: int | None = None,
) -> dict[str, Any]:
    if isinstance(prov, Provenance):
        out = prov.to_dict()
    elif isinstance(prov, Mapping):
        out = dict(prov)
        alg = out.get("algorithm")
        if not isinstance(alg, str) or not alg.strip():
            out["algorithm"] = algorithm
        libs = out.get("lib_versions")
        if not isinstance(libs, Mapping) or not libs:
            out["lib_versions"] = default_lib_versions()
        else:
            out["lib_versions"] = {str(k): str(v) for k, v in libs.items()}
    else:
        out = build_provenance(algorithm, model_revision=model_revision).to_dict()

    if model_revision is not None and out.get("model_revision") is None:
        out["model_revision"] = model_revision
    return ensure_json_finite(out, path="$.provenance")


def _build_rpc_response(
    *,
    request_id: str,
    project_id: str,
    project_revision: int,
    status: str,
    result: dict[str, Any] | None,
    assumptions: Mapping[str, Any] | None,
    diagnostics: Mapping[str, Any] | None,
    provenance: Provenance | Mapping[str, Any] | None,
    warnings: list[Any] | tuple[Any, ...] | None,
    error: TypedError | Mapping[str, Any] | None,
    fallback_algorithm: str,
) -> dict[str, Any]:
    if status not in _RESPONSE_STATUSES:
        status = "failure"

    if status == "failure":
        clean_result = None
        if isinstance(error, TypedError):
            clean_error: dict[str, Any] | None = error.to_dict()
        elif isinstance(error, Mapping):
            clean_error = TypedError.from_dict(error).to_dict()
        else:
            clean_error = TypedError(
                code="INTERNAL_ERROR",
                message="Falha científica ou operacional sem detalhes tipados.",
            ).to_dict()
    else:
        clean_result = ensure_json_finite(dict(result or {}), path="$.result")
        if status == "inconclusive" and error is not None:
            clean_error = (
                error.to_dict()
                if isinstance(error, TypedError)
                else TypedError.from_dict(error).to_dict()
            )
        else:
            clean_error = None

    clean_assumptions = ensure_json_finite(dict(assumptions or {}), path="$.assumptions")
    clean_diagnostics = ensure_json_finite(dict(diagnostics or {}), path="$.diagnostics")
    clean_provenance = _normalize_provenance_dict(provenance, algorithm=fallback_algorithm)

    clean_warnings: list[Any] = []
    for item in warnings or ():
        if isinstance(item, WarningItem):
            clean_warnings.append(item.to_dict())
        elif isinstance(item, Mapping):
            clean_warnings.append(WarningItem.from_dict(item).to_dict())
        elif isinstance(item, str) and item.strip():
            clean_warnings.append(item)

    response = {
        "api_version": RPC_API_VERSION,
        "request_id": request_id,
        "project_id": project_id,
        "project_revision": project_revision,
        "status": status,
        "result": clean_result,
        "assumptions": clean_assumptions,
        "diagnostics": clean_diagnostics,
        "provenance": clean_provenance,
        "warnings": clean_warnings,
        "error": clean_error,
    }
    return ensure_json_finite(response, path="$.rpc_response")


def _result_to_rpc_response(
    res: Result,
    *,
    request_id: str,
    project_id: str,
    project_revision: int,
    fallback_algorithm: str,
) -> dict[str, Any]:
    return _build_rpc_response(
        request_id=request_id,
        project_id=project_id,
        project_revision=project_revision,
        status=res.status,
        result=res.data,
        assumptions=res.assumptions,
        diagnostics=res.diagnostics,
        provenance=res.provenance,
        warnings=res.warnings,
        error=res.error,
        fallback_algorithm=fallback_algorithm,
    )


def _error_to_rpc_response(
    exc: Exception,
    *,
    request_id: str,
    project_id: str,
    project_revision: int,
    algorithm: str,
) -> dict[str, Any]:
    if isinstance(exc, ControlLabError):
        typed = exc.to_typed_error()
    else:
        typed = TypedError(
            code="INTERNAL_ERROR",
            message=f"Erro inesperado no dispatcher RPC ({type(exc).__name__}): {exc}",
            details={"exception_type": type(exc).__name__},
            next_step="Verifique os parâmetros e os logs locais do motor Python.",
        )
    return _build_rpc_response(
        request_id=request_id,
        project_id=project_id,
        project_revision=project_revision,
        status="failure",
        result=None,
        assumptions={},
        diagnostics={},
        provenance=build_provenance(algorithm),
        warnings=[],
        error=typed,
        fallback_algorithm=algorithm,
    )


def _validate_request_envelope(raw_input: Any, store: Any) -> tuple[dict[str, Any], Any]:
    unwrapped = _to_python_native(raw_input)
    if isinstance(unwrapped, (str, bytes, bytearray)):
        unwrapped = strict_json_loads(unwrapped)

    if not isinstance(unwrapped, Mapping):
        raise ValidationError(
            message=f"RpcRequest deve ser um objeto JSON/Mapping, recebido {type(unwrapped).__name__}.",
        )

    # Suporta envelope de Worker {request, payload, ?store, ?buffers} além de RpcRequest direto
    if (
        "request" in unwrapped
        and "operation" not in unwrapped
        and set(unwrapped.keys()).issubset({"request", "payload", "store", "buffers"})
    ):
        req_part = _to_python_native(unwrapped["request"])
        if not isinstance(req_part, Mapping):
            raise ValidationError("Envelope Worker.request deve ser um objeto Mapping.")
        req_dict = dict(req_part)
        if "payload" in unwrapped and unwrapped["payload"] is not None:
            resolved_payload = _to_python_native(unwrapped["payload"])
            if not isinstance(resolved_payload, Mapping):
                raise ValidationError("Envelope Worker.payload deve ser um objeto Mapping.")
            req_dict["payload"] = dict(resolved_payload)
        if store is None and "store" in unwrapped:
            store = unwrapped["store"]
        if "buffers" in unwrapped and unwrapped["buffers"] is not None:
            resolved_bufs = _to_python_native(unwrapped["buffers"])
            if not isinstance(resolved_bufs, Mapping):
                raise ValidationError("Envelope Worker.buffers deve ser um objeto Mapping.")
    else:
        req_dict = dict(unwrapped)

    keys = set(req_dict.keys())
    extra = keys - _REQUIRED_REQUEST_KEYS
    if extra:
        raise ValidationError(
            message=f"Campos extras proibidos em RpcRequest: {sorted(extra)}",
            parameters={"extra_fields": sorted(extra)},
        )
    missing = _REQUIRED_REQUEST_KEYS - keys
    if missing:
        raise ValidationError(
            message=f"Campos obrigatórios ausentes em RpcRequest: {sorted(missing)}",
            parameters={"missing_fields": sorted(missing)},
        )

    api_version = req_dict["api_version"]
    if not isinstance(api_version, str):
        raise ValidationError("RpcRequest.api_version deve ser string.")
    if api_version != RPC_API_VERSION:
        raise SchemaUnsupportedError(
            message=f"api_version não suportada: {api_version!r} (esperado {RPC_API_VERSION!r}).",
            parameters={"api_version": api_version, "supported": RPC_API_VERSION},
        )

    request_id = req_dict["request_id"]
    if not isinstance(request_id, str) or len(request_id) < 1 or not request_id.strip():
        raise ValidationError("RpcRequest.request_id deve ser string não vazia.")

    project_id = req_dict["project_id"]
    if not isinstance(project_id, str) or len(project_id) < 1 or not project_id.strip():
        raise ValidationError("RpcRequest.project_id deve ser string não vazia.")

    project_revision = req_dict["project_revision"]
    if not _is_non_bool_int(project_revision) or project_revision < 0:
        raise ValidationError(
            f"RpcRequest.project_revision deve ser inteiro >= 0, recebido {project_revision!r}."
        )

    operation = req_dict["operation"]
    if not isinstance(operation, str) or not _OPERATION_RE.fullmatch(operation):
        raise ValidationError(
            message=f"RpcRequest.operation inválido: {operation!r}.",
            parameters={"operation": operation},
        )

    payload_raw = _to_python_native(req_dict["payload"])
    if not isinstance(payload_raw, Mapping):
        raise ValidationError("RpcRequest.payload deve ser um objeto JSON (dict).")

    options_raw = _to_python_native(req_dict["options"])
    if not isinstance(options_raw, Mapping):
        raise ValidationError("RpcRequest.options deve ser um objeto JSON (dict).")

    tp_raw = _to_python_native(req_dict["timeout_policy"])
    if not isinstance(tp_raw, Mapping):
        raise ValidationError("RpcRequest.timeout_policy deve ser um objeto JSON (dict).")
    if "hard_timeout_ms" not in tp_raw:
        raise ValidationError("RpcRequest.timeout_policy exige 'hard_timeout_ms'.")
    hard_ms = tp_raw["hard_timeout_ms"]
    if not _is_non_bool_int(hard_ms) or hard_ms < 1:
        raise ValidationError(
            f"timeout_policy.hard_timeout_ms deve ser inteiro >= 1, recebido {hard_ms!r}."
        )
    if "soft_timeout_ms" in tp_raw:
        soft_ms = tp_raw["soft_timeout_ms"]
        if not _is_non_bool_int(soft_ms) or soft_ms < 1:
            raise ValidationError(
                f"timeout_policy.soft_timeout_ms deve ser inteiro >= 1, recebido {soft_ms!r}."
            )
    if "cancel_on_supersede" in tp_raw and not isinstance(tp_raw["cancel_on_supersede"], bool):
        raise ValidationError("timeout_policy.cancel_on_supersede deve ser booleano.")

    validated = {
        "api_version": api_version,
        "request_id": request_id,
        "project_id": project_id,
        "project_revision": int(project_revision),
        "operation": operation,
        "payload": ensure_json_finite(dict(payload_raw), path="$.payload"),
        "options": ensure_json_finite(dict(options_raw), path="$.options"),
        "timeout_policy": ensure_json_finite(dict(tp_raw), path="$.timeout_policy"),
    }
    return validated, store


# ---------------------------------------------------------------------------
# Helpers de coerção de tensores, referências e modelos
# ---------------------------------------------------------------------------


def _parse_ref(ref: Any, *, field_name: str = "ref") -> tuple[str, int]:
    if not isinstance(ref, Mapping):
        raise ValidationError(f"{field_name} deve ser um objeto com 'id' e 'revision'.")
    obj_id = ref.get("id")
    rev = ref.get("revision")
    if not isinstance(obj_id, str) or not obj_id.strip():
        raise ValidationError(f"{field_name}.id deve ser string não vazia.")
    if not _is_non_bool_int(rev) or rev < 0:
        raise ValidationError(f"{field_name}.revision deve ser inteiro >= 0.")
    return obj_id, int(rev)


def _lookup_store(store: Any, project_id: str, obj_id: str, revision: int) -> Any:
    if store is None:
        return None

    candidates: list[Any] = []
    if callable(store):
        for args in ((project_id, obj_id, revision), (obj_id, revision), (obj_id,)):
            try:
                found = store(*args)
                if found is not None:
                    candidates.append(found)
                    break
            except TypeError:
                continue
    elif isinstance(store, Mapping):
        for key in (
            (project_id, obj_id, revision),
            (obj_id, revision),
            f"{project_id}:{obj_id}:{revision}",
            f"{obj_id}@{revision}",
            f"{obj_id}:{revision}",
        ):
            if key in store and store[key] is not None:
                candidates.append(store[key])
                break
        if not candidates and project_id in store and isinstance(store[project_id], Mapping):
            proj_bucket = store[project_id]
            if (obj_id, revision) in proj_bucket:
                candidates.append(proj_bucket[(obj_id, revision)])
            elif obj_id in proj_bucket:
                sub = proj_bucket[obj_id]
                if isinstance(sub, Mapping) and revision in sub:
                    candidates.append(sub[revision])
                else:
                    candidates.append(sub)
        if not candidates and obj_id in store and store[obj_id] is not None:
            candidates.append(store[obj_id])
    elif hasattr(store, "get") and callable(store.get):
        for args in ((project_id, obj_id, revision), (obj_id, revision), ((obj_id, revision),)):
            try:
                found = store.get(*args)
                if found is not None:
                    candidates.append(found)
                    break
            except TypeError:
                continue

    if not candidates:
        return None

    item = _to_python_native(candidates[0])
    if isinstance(item, Mapping) and "value" in item and "kind" not in item:
        item = _to_python_native(item["value"])

    # Valida que revisão do objeto recuperado corresponde exatamente à solicitada
    item_rev = getattr(item, "revision", None)
    if item_rev is None and isinstance(item, Mapping):
        item_rev = item.get("revision")
    if item_rev is not None and _is_non_bool_int(item_rev) and int(item_rev) != revision:
        return None
    return item


def _store_put_object(store: Any, project_id: str, obj: Any) -> None:
    obj_id = getattr(obj, "id", None)
    obj_rev = getattr(obj, "revision", 0)
    if obj_id is None:
        return
    if hasattr(store, "put") and callable(store.put):
        for args in (
            (project_id, obj_id, obj_rev, obj),
            (obj_id, obj_rev, obj),
            ((obj_id, obj_rev), obj),
            (obj,),
        ):
            try:
                store.put(*args)
                return
            except TypeError:
                continue
    elif isinstance(store, dict):
        store[(project_id, obj_id, obj_rev)] = obj


def _restore_canonical_object(raw_obj: Any, *, field_name: str = "model") -> Any:
    raw_obj = _to_python_native(raw_obj)
    if isinstance(
        raw_obj,
        (
            StateSpace,
            TransferFunction,
            TSStateSpace,
            FuzzySystem,
            Dataset,
            IdentifiedModel,
            Experiment,
            StateFeedbackController,
            DynamicController,
            PDCController,
        ),
    ):
        return raw_obj
    if isinstance(raw_obj, Mapping):
        if "kind" not in raw_obj:
            raise ValidationError(f"Objeto {field_name} deve conter campo canônico 'kind'.")
        return restore_model(raw_obj)
    raise ValidationError(f"Objeto {field_name} inválido: esperado modelo canônico ou dict.")


def _resolve_from_store_or_inline(
    payload: Mapping[str, Any],
    *,
    inline_keys: tuple[str, ...],
    ref_keys: tuple[str, ...],
    store: Any,
    project_id: str,
) -> Any | None:
    for key in inline_keys:
        if key in payload and payload[key] is not None:
            raw_val = _to_python_native(payload[key])
            if isinstance(raw_val, Mapping) and "kind" not in raw_val and "A" in raw_val:
                return raw_val
            return _restore_canonical_object(raw_val, field_name=key)

    for rkey in ref_keys:
        if rkey in payload and payload[rkey] is not None:
            obj_id, rev = _parse_ref(payload[rkey], field_name=rkey)
            found = _lookup_store(store, project_id, obj_id, rev)
            if found is None:
                raise ValidationError(
                    message=(
                        f"Referência {rkey} (id={obj_id!r}, revision={rev}) não encontrada no store; "
                        "forneça o objeto inline ou registre a revisão solicitada antes da chamada."
                    ),
                    parameters={"ref_field": rkey, "id": obj_id, "revision": rev},
                    next_step="Envie o objeto completo no payload ou registre-o no ModelStore com a mesma revisão.",
                )
            return _restore_canonical_object(found, field_name=rkey)
    return None


def _coerce_array(
    val: Any,
    *,
    name: str,
    ndim: int | None = None,
    shape: tuple[int, ...] | None = None,
    allow_complex: bool = False,
) -> np.ndarray:
    val = _to_python_native(val)
    if isinstance(val, Mapping):
        if "buffer_ref" in val:
            raise ValidationError(
                message=f"Tensor '{name}' referencia buffer_ref={val['buffer_ref']!r} não reidratado.",
                parameters={"field": name, "buffer_ref": val["buffer_ref"]},
            )
        if "shape" in val and ("data" in val or ("real" in val and "imag" in val)):
            target_dtype = None if allow_complex else "float64"
            return tensor_to_array(
                val,
                expected_ndim=ndim,
                expected_shape=shape,
                dtype=target_dtype,
            )
        if allow_complex and "real" in val and "imag" in val:
            arr = pair_to_complex(val)
            if ndim is not None and arr.ndim != ndim:
                raise DimensionMismatchError(f"{name} deve ter {ndim}D, recebido {arr.ndim}D.")
            if shape is not None and arr.shape != shape:
                raise DimensionMismatchError(f"{name} deve ter shape {shape}, recebido {arr.shape}.")
            return arr
        raise ValidationError(f"Estrutura de tensor inválida para '{name}'.")

    return ensure_finite_float64(val, ndim=ndim, shape=shape, name=name)


def _coerce_poles(val: Any, *, name: str = "poles") -> Any:
    val = _to_python_native(val)
    if isinstance(val, Mapping) and "real" in val and "imag" in val:
        return pair_to_complex(val)
    if isinstance(val, list):
        out: list[Any] = []
        for item in val:
            if isinstance(item, Mapping) and "real" in item and "imag" in item:
                out.append(complex(float(item["real"]), float(item["imag"])))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                out.append(complex(float(item[0]), float(item[1])))
            else:
                out.append(item)
        return out
    return val


def _pick_param(
    payload: Mapping[str, Any],
    options: Mapping[str, Any],
    key: str,
    default: Any = _UNSET,
) -> Any:
    in_p = key in payload and payload[key] is not None
    in_o = key in options and options[key] is not None
    if in_p and in_o:
        if payload[key] != options[key]:
            raise ValidationError(
                message=f"Parâmetro conflitante {key!r} entre payload ({payload[key]!r}) e options ({options[key]!r}).",
                parameters={"parameter": key},
            )
        return payload[key]
    if in_p:
        return payload[key]
    if in_o:
        return options[key]
    return default


def _resolve_omega_arg(payload: Mapping[str, Any], options: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    omega = None
    if "omega" in payload and payload["omega"] is not None:
        omega = _coerce_array(payload["omega"], name="omega", ndim=1)
    kwargs: dict[str, Any] = {}
    n_pts = _pick_param(payload, options, "n_points", _UNSET)
    if n_pts is not _UNSET:
        if not _is_non_bool_int(n_pts) or n_pts < 2:
            raise ValidationError("n_points deve ser inteiro >= 2.")
        kwargs["n_points"] = int(n_pts)
    w_min = payload.get("omega_min", payload.get("w_min", options.get("omega_min", options.get("w_min", _UNSET))))
    w_max = payload.get("omega_max", payload.get("w_max", options.get("omega_max", options.get("w_max", _UNSET))))
    if w_min is not _UNSET and w_min is not None:
        kwargs["omega_min"] = float(w_min)
    if w_max is not _UNSET and w_max is not None:
        kwargs["omega_max"] = float(w_max)
    return omega, kwargs


def _resolve_plant_or_matrices(
    payload: Mapping[str, Any],
    *,
    store: Any,
    project_id: str,
    require_B: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """Retorna `(plant_obj_or_None, raw_matrix_kwargs)` a partir do payload/store."""
    resolved = _resolve_from_store_or_inline(
        payload,
        inline_keys=("plant", "model"),
        ref_keys=("plant_ref", "model_ref"),
        store=store,
        project_id=project_id,
    )
    if resolved is not None:
        if isinstance(resolved, Mapping):
            # Dicionário matricial explícito sem kind canônico
            if "A" not in resolved:
                raise ValidationError("Dicionário de planta requer matriz 'A'.")
            mats: dict[str, Any] = {"A": _coerce_array(resolved["A"], name="A", ndim=2)}
            if "B" in resolved and resolved["B"] is not None:
                mats["B"] = _coerce_array(resolved["B"], name="B", ndim=2)
            elif require_B:
                raise ValidationError("Matriz B é obrigatória para esta operação.")
            if "C" in resolved and resolved["C"] is not None:
                mats["C"] = _coerce_array(resolved["C"], name="C", ndim=2)
            if "D" in resolved and resolved["D"] is not None:
                mats["D"] = _coerce_array(resolved["D"], name="D", ndim=2)
            if "dt" in resolved:
                mats["dt"] = resolved["dt"]
            return None, mats
        return resolved, {}

    if "A" in payload and payload["A"] is not None:
        mats = {"A": _coerce_array(payload["A"], name="A", ndim=2)}
        if "B" in payload and payload["B"] is not None:
            mats["B"] = _coerce_array(payload["B"], name="B", ndim=2)
        elif require_B:
            raise ValidationError("Matriz B é obrigatória para esta operação.")
        if "C" in payload and payload["C"] is not None:
            mats["C"] = _coerce_array(payload["C"], name="C", ndim=2)
        if "D" in payload and payload["D"] is not None:
            mats["D"] = _coerce_array(payload["D"], name="D", ndim=2)
        if "dt" in payload:
            mats["dt"] = payload["dt"]
        return None, mats

    raise ValidationError(
        message="Payload deve fornecer 'plant', 'plant_ref' ou matrizes de estado ('A', ...).",
        next_step="Envie um objeto StateSpace canônico em payload.plant ou registre plant_ref no store.",
    )


def _extract_ss_dims(plant_obj: Any, mats: Mapping[str, Any]) -> tuple[int | None, int | None]:
    if isinstance(plant_obj, StateSpace):
        return plant_obj.n_states, plant_obj.n_inputs
    if "A" in mats:
        A_arr = mats["A"]
        n = int(A_arr.shape[0]) if A_arr.ndim == 2 else None
        B_arr = mats.get("B")
        m = int(B_arr.shape[1]) if (B_arr is not None and B_arr.ndim == 2) else None
        return n, m
    return None, None


# ---------------------------------------------------------------------------
# Handlers por domínio científico
# ---------------------------------------------------------------------------


def _handle_worker_ping(req: dict[str, Any], store: Any) -> dict[str, Any]:
    del store
    prov = build_provenance("worker.ping")
    return _build_rpc_response(
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        status="success",
        result={
            "pong": True,
            "runtime": "python",
            "api_version": RPC_API_VERSION,
            "supported_operations": sorted(SUPPORTED_OPERATIONS),
        },
        assumptions={"dispatcher": "control_lab.core.rpc"},
        diagnostics={},
        provenance=prov,
        warnings=[],
        error=None,
        fallback_algorithm="worker.ping",
    )


def _handle_capabilities(req: dict[str, Any], store: Any) -> dict[str, Any]:
    del store
    from control_lab.optimization.backends.capabilities import describe_solver_capabilities

    opt_caps = describe_solver_capabilities("all")
    prov = build_provenance("core.capabilities")
    return _build_rpc_response(
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        status="success",
        result={
            "api_version": RPC_API_VERSION,
            "lib_versions": default_lib_versions(),
            "supported_operations": sorted(SUPPORTED_OPERATIONS),
            "optimization_backends": opt_caps,
        },
        assumptions={"runtime": "python"},
        diagnostics={},
        provenance=prov,
        warnings=[],
        error=None,
        fallback_algorithm="core.capabilities",
    )


def _handle_core_reuse_model(req: dict[str, Any], store: Any) -> dict[str, Any]:
    """RPC 1.0 additive operation; model reuse result contract is version 1.0.0.

    Python stores must be explicitly project-bucketed or keyed by
    project/id/revision. A store never falls back to another project or an
    unscoped entry; resolver callables must accept all three identity arguments.
    The JS Worker currently materializes only plant_ref; callers must send model
    inline unless an explicit Python store is provided to dispatch.
    """
    from .model_reuse import reuse_model

    payload = req["payload"]
    if set(payload) - {"model", "model_ref", "target_kind"}:
        raise ValidationError("core.reuse_model aceita apenas model/model_ref e target_kind; dt e identidade não podem ser sobrescritos.")
    if req["options"]:
        raise ValidationError("core.reuse_model versão 1.0.0 exige options vazio.")
    if ("model" in payload) == ("model_ref" in payload):
        raise ValidationError("Forneça exatamente um de model ou model_ref.")
    if "model" in payload:
        source = _restore_canonical_object(payload["model"], field_name="model")
    else:
        ref = payload["model_ref"]
        obj_id, revision = _parse_ref(ref, field_name="model_ref")
        if set(ref) != {"id", "revision"}:
            raise ValidationError("model_ref contém campos desconhecidos.")
        if store is None:
            raise ValidationError(
                "model_ref exige store Python explícito; a ponte Worker atual não reidrata model_ref. Envie o modelo canônico inline.",
                next_step="Materialize a revisão requerida no cliente e envie payload.model, ou forneça store a dispatch em CPython.",
            )
        found = None
        if isinstance(store, Mapping):
            def project_bucket(value: Any) -> bool:
                return isinstance(value, Mapping) and "kind" not in value and "value" not in value

            has_project_keys = any(isinstance(key, tuple) and len(key) == 3 for key in store)
            has_buckets = any(project_bucket(value) for value in store.values())
            if has_project_keys:
                found = store.get((req["project_id"], obj_id, revision))
            elif has_buckets:
                bucket = store.get(req["project_id"])
                if project_bucket(bucket):
                    found = _lookup_store({req["project_id"]: bucket}, req["project_id"], obj_id, revision)
            else:
                raise ValidationError("core.reuse_model exige store com escopo explícito de projeto; use chave (project_id, id, revision) ou bucket por project_id.")
        else:
            resolver = store if callable(store) else getattr(store, "get", None)
            if not callable(resolver):
                raise ValidationError("store deve ser Mapping ou resolver(project_id, id, revision).")
            try:
                found = resolver(req["project_id"], obj_id, revision)
            except TypeError as exc:
                raise ValidationError("Resolver do store exige project_id, id e revision explícitos.") from exc
        if isinstance(found, Mapping) and "value" in found and "kind" not in found:
            found = found["value"]
        if found is None:
            raise ValidationError("model_ref não encontrado no projeto e revisão solicitados.")
        source = _restore_canonical_object(found, field_name="model_ref")
        if source.id != obj_id or source.revision != revision:
            raise ValidationError("model_ref diverge da identidade/revisão do objeto armazenado.")
    res = reuse_model(source, target_kind=payload.get("target_kind", "native"))
    return _result_to_rpc_response(
        res, request_id=req["request_id"], project_id=req["project_id"],
        project_revision=req["project_revision"], fallback_algorithm="core.reuse_model",
    )


def _handle_core_interconnect(req: dict[str, Any], store: Any) -> dict[str, Any]:
    payload = req["payload"]
    plant = _resolve_from_store_or_inline(
        payload,
        inline_keys=("plant",),
        ref_keys=("plant_ref",),
        store=store,
        project_id=req["project_id"],
    )
    controller = _resolve_from_store_or_inline(
        payload,
        inline_keys=("controller",),
        ref_keys=("controller_ref",),
        store=store,
        project_id=req["project_id"],
    )
    if plant is None or controller is None:
        raise ValidationError("Operação de interconexão exige 'plant' e 'controller' (ou *_ref).")

    sign_conv = payload.get("sign_convention", payload.get("feedback_sign"))
    wiring = payload.get("wiring")
    premise_estimator = payload.get("premise_estimator")

    if req["operation"] == "core.validate_interconnection":
        res = validate_interconnection(
            plant,
            controller,
            wiring=wiring,
            sign_convention=sign_conv,
            premise_estimator=premise_estimator,
            raise_on_error=False,
        )
        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm="core.validate_interconnection",
        )

    closed_loop = interconnect(
        plant,
        controller,
        wiring=wiring,
        sign_convention=sign_conv,
        premise_estimator=premise_estimator,
    )
    prov = build_provenance(
        "core.interconnect",
        model_revision=getattr(plant, "revision", None),
    )
    return _build_rpc_response(
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        status="success",
        result={"closed_loop": closed_loop.to_dict()},
        assumptions={"sign_convention": closed_loop.feedback_sign if hasattr(closed_loop, "feedback_sign") else sign_conv},
        diagnostics={},
        provenance=prov,
        warnings=[],
        error=None,
        fallback_algorithm="core.interconnect",
    )


def _handle_statespace_design_lqr(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.statespace import design_lqr, simulate_lti

    payload = req["payload"]
    options = req["options"]

    plant_obj, mats = _resolve_plant_or_matrices(
        payload,
        store=store,
        project_id=req["project_id"],
        require_B=True,
    )
    n_dim, m_dim = _extract_ss_dims(plant_obj, mats)

    if "Q" in payload and payload["Q"] is not None:
        Q_arr = _coerce_array(payload["Q"], name="Q", ndim=2)
    elif "q_scale" in payload and payload["q_scale"] is not None and n_dim is not None:
        q_scale = float(payload["q_scale"])
        if not np.isfinite(q_scale) or q_scale <= 0.0:
            raise ValidationError("q_scale deve ser número real positivo finito.")
        Q_arr = q_scale * np.eye(n_dim, dtype=np.float64)
    else:
        raise ValidationError("Matriz Q (ou q_scale com planta StateSpace) é obrigatória para design_lqr.")

    if "R" in payload and payload["R"] is not None:
        R_arr = _coerce_array(payload["R"], name="R", ndim=2)
    elif "r_scale" in payload and payload["r_scale"] is not None and m_dim is not None:
        r_scale = float(payload["r_scale"])
        if not np.isfinite(r_scale) or r_scale <= 0.0:
            raise ValidationError("r_scale deve ser número real positivo finito.")
        R_arr = r_scale * np.eye(m_dim, dtype=np.float64)
    else:
        raise ValidationError("Matriz R (ou r_scale com planta StateSpace) é obrigatória para design_lqr.")

    x0_arr = None
    if "x0" in payload and payload["x0"] is not None:
        x0_arr = _coerce_array(payload["x0"], name="x0")

    feedback_sign = _pick_param(payload, options, "feedback_sign", "negative")
    method = _pick_param(payload, options, "method", None)
    tol = _pick_param(payload, options, "tol", None)
    reference_map = payload.get("reference_map")
    if isinstance(reference_map, Mapping) and "shape" in reference_map and "data" in reference_map:
        reference_map = _coerce_array(reference_map, name="reference_map", ndim=2)

    if plant_obj is not None:
        res = design_lqr(
            plant=plant_obj,
            Q=Q_arr,
            R=R_arr,
            x0=x0_arr,
            feedback_sign=feedback_sign,
            reference_map=reference_map,
            method=method,
            tol=tol,
            raise_on_error=False,
        )
    else:
        kwargs: dict[str, Any] = {
            "A": mats["A"],
            "B": mats["B"],
            "Q": Q_arr,
            "R": R_arr,
            "x0": x0_arr,
            "feedback_sign": feedback_sign,
            "reference_map": reference_map,
            "method": method,
            "tol": tol,
            "raise_on_error": False,
        }
        if "dt" in mats:
            kwargs["dt"] = mats["dt"]
        res = design_lqr(**kwargs)

    if res.status == "failure":
        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm="scipy.linalg.solve_continuous_are",
        )

    data_out = dict(res.data or {})
    compute_tr = bool(_pick_param(payload, options, "compute_time_response", False))
    if compute_tr and isinstance(plant_obj, StateSpace) and "closed_loop" in data_out:
        cl_ss = StateSpace.from_dict(data_out["closed_loop"])
        K_lqr = tensor_to_array(data_out["K_lqr"], expected_ndim=2, dtype="float64")
        n = plant_obj.n_states
        if "t" in payload and payload["t"] is not None:
            t_grid = _coerce_array(payload["t"], name="t", ndim=1)
        elif plant_obj.dt is None:
            t_final = float(_pick_param(payload, options, "t_final", 5.0))
            n_steps = int(_pick_param(payload, options, "n_steps", 101))
            if not np.isfinite(t_final) or t_final <= 0.0 or n_steps < 2:
                raise ValidationError("t_final > 0 e n_steps >= 2 são obrigatórios para resposta temporal.")
            t_grid = np.linspace(0.0, t_final, n_steps, dtype=np.float64)
        else:
            n_steps = int(_pick_param(payload, options, "n_steps", 51))
            if n_steps < 2:
                raise ValidationError("n_steps deve ser >= 2 para resposta temporal discreta.")
            t_grid = np.arange(n_steps, dtype=np.float64) * float(plant_obj.dt)

        if x0_arr is not None:
            x0_sim = x0_arr.reshape((n,))
        else:
            x0_sim = np.zeros((n,), dtype=np.float64)
            if n > 0:
                x0_sim[0] = 1.0

        sim_res = simulate_lti(cl_ss, t_grid, u=None, x0=x0_sim, raise_on_error=False)
        if sim_res.status in ("success", "warning") and sim_res.data is not None:
            t_sim = tensor_to_array(sim_res.data["t"], expected_ndim=1, dtype="float64")
            x_sim = tensor_to_array(sim_res.data["x"], expected_ndim=2, dtype="float64")
            y_sim = tensor_to_array(sim_res.data["y"], expected_ndim=2, dtype="float64")
            u_sim = x_sim @ (-K_lqr.T)
            data_out["time_response"] = {
                "t": t_sim.tolist(),
                "x": x_sim.tolist(),
                "u": u_sim.tolist(),
                "y": y_sim.tolist(),
                "state_names": list(plant_obj.state_names),
                "input_names": list(plant_obj.input_names),
                "output_names": list(plant_obj.output_names),
            }

    return _build_rpc_response(
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        status=res.status,
        result=data_out,
        assumptions=res.assumptions,
        diagnostics=res.diagnostics,
        provenance=res.provenance,
        warnings=res.warnings,
        error=res.error,
        fallback_algorithm="scipy.linalg.solve_continuous_are",
    )


def _handle_statespace_design_lqi(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.statespace import design_lqi

    payload = req["payload"]
    options = req["options"]
    plant_obj, _ = _resolve_plant_or_matrices(payload, store=store, project_id=req["project_id"])
    if not isinstance(plant_obj, StateSpace):
        raise UnsupportedModelError("design_lqi exige modelo StateSpace canônico.")
    if "Q" not in payload or "R" not in payload:
        raise ValidationError("design_lqi exige matrizes 'Q' e 'R'.")
    Q_arr = _coerce_array(payload["Q"], name="Q", ndim=2)
    R_arr = _coerce_array(payload["R"], name="R", ndim=2)
    Q_i_arr = _coerce_array(payload["Q_i"], name="Q_i", ndim=2) if payload.get("Q_i") is not None else None
    x0_arr = _coerce_array(payload["x0"], name="x0") if payload.get("x0") is not None else None
    xi0_arr = _coerce_array(payload["xi0"], name="xi0") if payload.get("xi0") is not None else None
    res = design_lqi(
        plant_obj,
        Q_arr,
        R_arr,
        Q_i=Q_i_arr,
        output_indices=payload.get("output_indices"),
        x0=x0_arr,
        xi0=xi0_arr,
        feedback_sign=_pick_param(payload, options, "feedback_sign", "negative"),
        integral_dt_scaled=bool(payload.get("integral_dt_scaled", True)),
        tol=_pick_param(payload, options, "tol", None),
        raise_on_error=False,
    )
    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm="statespace.design_lqi",
    )


def _handle_statespace_pole_placement(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.statespace import design_observer, design_pole_placement

    payload = req["payload"]
    options = req["options"]
    is_observer = req["operation"] == "statespace.design_observer"
    plant_obj, mats = _resolve_plant_or_matrices(
        payload,
        store=store,
        project_id=req["project_id"],
        require_B=not is_observer,
    )
    if "poles" not in payload or payload["poles"] is None:
        raise ValidationError("Operação de alocação de polos exige 'poles'.")
    poles = _coerce_poles(payload["poles"])
    method = _pick_param(payload, options, "method", "YT")
    tol = _pick_param(payload, options, "tol", None)

    if is_observer:
        if plant_obj is not None:
            res = design_observer(plant_obj, poles=poles, method=method, tol=tol, raise_on_error=False)
        else:
            if "C" not in mats:
                raise ValidationError("design_observer com matrizes exige 'A' e 'C'.")
            res = design_observer(
                mats["A"],
                C_or_poles=mats["C"],
                poles=poles,
                method=method,
                dt=mats.get("dt"),
                tol=tol,
                raise_on_error=False,
            )
        alg = "statespace.design_observer"
    else:
        fb_sign = _pick_param(payload, options, "feedback_sign", "negative")
        ref_map = payload.get("reference_map")
        if plant_obj is not None:
            res = design_pole_placement(
                plant_obj,
                poles=poles,
                feedback_sign=fb_sign,
                reference_map=ref_map,
                method=method,
                tol=tol,
                raise_on_error=False,
            )
        else:
            res = design_pole_placement(
                mats["A"],
                B_or_poles=mats["B"],
                poles=poles,
                feedback_sign=fb_sign,
                reference_map=ref_map,
                method=method,
                dt=mats.get("dt"),
                tol=tol,
                raise_on_error=False,
            )
        alg = "statespace.design_pole_placement"

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=alg,
    )


def _handle_statespace_kalman_lqg(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.statespace import design_kalman, design_lqg

    payload = req["payload"]
    options = req["options"]
    plant_obj, mats = _resolve_plant_or_matrices(payload, store=store, project_id=req["project_id"])
    tol = _pick_param(payload, options, "tol", None)
    if "Qn" not in payload or "Rn" not in payload:
        raise ValidationError("Operação Kalman/LQG exige covariâncias 'Qn' e 'Rn'.")
    Qn_arr = _coerce_array(payload["Qn"], name="Qn", ndim=2)
    Rn_arr = _coerce_array(payload["Rn"], name="Rn", ndim=2)
    G_arr = _coerce_array(payload["G"], name="G", ndim=2) if payload.get("G") is not None else None

    if req["operation"] == "statespace.design_kalman":
        if plant_obj is not None:
            res = design_kalman(
                plant=plant_obj,
                Qn=Qn_arr,
                Rn=Rn_arr,
                G=G_arr,
                tol=tol,
                raise_on_error=False,
            )
        else:
            if "C" not in mats:
                raise ValidationError("design_kalman com matrizes exige 'A' e 'C'.")
            kwargs: dict[str, Any] = {
                "A": mats["A"],
                "C": mats["C"],
                "Qn": Qn_arr,
                "Rn": Rn_arr,
                "G": G_arr,
                "tol": tol,
                "raise_on_error": False,
            }
            if "dt" in mats:
                kwargs["dt"] = mats["dt"]
            res = design_kalman(**kwargs)
        alg = "statespace.design_kalman"
    else:
        if not isinstance(plant_obj, StateSpace):
            raise UnsupportedModelError("design_lqg exige modelo StateSpace canônico.")
        if "Q" not in payload or "R" not in payload:
            raise ValidationError("design_lqg exige matrizes de peso 'Q' e 'R'.")
        Q_arr = _coerce_array(payload["Q"], name="Q", ndim=2)
        R_arr = _coerce_array(payload["R"], name="R", ndim=2)
        x0_init = (
            _coerce_array(payload["initial_state"], name="initial_state")
            if payload.get("initial_state") is not None
            else None
        )
        res = design_lqg(
            plant_obj,
            Q_arr,
            R_arr,
            Qn_arr,
            Rn_arr,
            G=G_arr,
            feedback_sign=_pick_param(payload, options, "feedback_sign", "negative"),
            initial_state=x0_init,
            tol=tol,
            raise_on_error=False,
        )
        alg = "statespace.design_lqg"

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=alg,
    )


def _handle_statespace_analysis(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.statespace import analyze, check_pbh, gramians

    payload = req["payload"]
    options = req["options"]
    plant_obj, mats = _resolve_plant_or_matrices(payload, store=store, project_id=req["project_id"])
    tol = _pick_param(payload, options, "tol", None)
    stab_tol = _pick_param(payload, options, "stab_tol", None)
    op = req["operation"]

    if op == "statespace.analyze":
        comp_gram = bool(_pick_param(payload, options, "compute_gramians", True))
        if plant_obj is not None:
            res = analyze(
                plant_obj,
                tol=tol,
                stab_tol=stab_tol,
                compute_gramians=comp_gram,
                raise_on_error=False,
            )
        else:
            res = analyze(
                mats["A"],
                B=mats.get("B"),
                C=mats.get("C"),
                D=mats.get("D"),
                dt=mats.get("dt"),
                tol=tol,
                stab_tol=stab_tol,
                compute_gramians=comp_gram,
                raise_on_error=False,
            )
    elif op == "statespace.check_pbh":
        if plant_obj is not None:
            res = check_pbh(plant_obj, tol=tol, stab_tol=stab_tol, raise_on_error=False)
        else:
            res = check_pbh(
                mats["A"],
                B=mats.get("B"),
                C=mats.get("C"),
                dt=mats.get("dt"),
                tol=tol,
                stab_tol=stab_tol,
                raise_on_error=False,
            )
    else:  # statespace.gramians
        kind = str(_pick_param(payload, options, "kind", "both"))
        if plant_obj is not None:
            res = gramians(plant_obj, kind=kind, tol=tol, raise_on_error=False)
        else:
            res = gramians(
                mats["A"],
                B=mats.get("B"),
                C=mats.get("C"),
                kind=kind,
                dt=mats.get("dt"),
                tol=tol,
                raise_on_error=False,
            )

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=op,
    )


def _handle_statespace_equations(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.statespace import solve_care, solve_dare, solve_lyapunov, solve_sylvester

    payload = req["payload"]
    options = req["options"]
    op = req["operation"]
    tol = _pick_param(payload, options, "tol", None)

    if op == "statespace.solve_sylvester":
        for key in ("A", "B", "Q"):
            if key not in payload or payload[key] is None:
                raise ValidationError(f"solve_sylvester exige matriz '{key}'.")
        res = solve_sylvester(
            _coerce_array(payload["A"], name="A", ndim=2),
            _coerce_array(payload["B"], name="B", ndim=2),
            _coerce_array(payload["Q"], name="Q", ndim=2),
            add_q=bool(payload.get("add_q", False)),
            tol=tol,
            raise_on_error=False,
        )
        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm="scipy.linalg.solve_sylvester",
        )

    if op == "statespace.solve_lyapunov":
        plant_obj, mats = _resolve_plant_or_matrices(payload, store=store, project_id=req["project_id"])
        if "Q" not in payload or payload["Q"] is None:
            raise ValidationError("solve_lyapunov exige matriz 'Q'.")
        Q_arr = _coerce_array(payload["Q"], name="Q", ndim=2)
        domain = _pick_param(payload, options, "domain", None)
        require_sym = bool(_pick_param(payload, options, "require_symmetric", True))
        if plant_obj is not None:
            res = solve_lyapunov(
                plant_obj,
                Q_arr,
                domain=domain,
                require_symmetric=require_sym,
                tol=tol,
                raise_on_error=False,
            )
        else:
            res = solve_lyapunov(
                mats["A"],
                Q_arr,
                domain=domain,
                dt=mats.get("dt"),
                require_symmetric=require_sym,
                tol=tol,
                raise_on_error=False,
            )
        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm="statespace.solve_lyapunov",
        )

    # CARE / DARE
    plant_obj, mats = _resolve_plant_or_matrices(
        payload,
        store=store,
        project_id=req["project_id"],
        require_B=True,
    )
    if "Q" not in payload or "R" not in payload:
        raise ValidationError(f"{op} exige matrizes 'Q' e 'R'.")
    Q_arr = _coerce_array(payload["Q"], name="Q", ndim=2)
    R_arr = _coerce_array(payload["R"], name="R", ndim=2)
    x0_arr = _coerce_array(payload["x0"], name="x0") if payload.get("x0") is not None else None
    check_hyp = bool(_pick_param(payload, options, "check_hypotheses", True))
    solver_fn = solve_care if op == "statespace.solve_care" else solve_dare

    if plant_obj is not None:
        res = solver_fn(
            plant=plant_obj,
            Q=Q_arr,
            R=R_arr,
            x0=x0_arr,
            tol=tol,
            check_hypotheses=check_hyp,
            raise_on_error=False,
        )
    else:
        kwargs: dict[str, Any] = {
            "A": mats["A"],
            "B": mats["B"],
            "Q": Q_arr,
            "R": R_arr,
            "x0": x0_arr,
            "tol": tol,
            "check_hypotheses": check_hyp,
            "raise_on_error": False,
        }
        if "dt" in mats:
            kwargs["dt"] = mats["dt"]
        res = solver_fn(**kwargs)

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=op,
    )


def _handle_statespace_sim_discretize(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.statespace import discretize_zoh, simulate_lti

    payload = req["payload"]
    options = req["options"]
    plant_obj, _ = _resolve_plant_or_matrices(payload, store=store, project_id=req["project_id"])
    if not isinstance(plant_obj, StateSpace):
        raise UnsupportedModelError(f"{req['operation']} exige modelo StateSpace canônico.")

    if req["operation"] == "statespace.discretize_zoh":
        if "dt" not in payload or payload["dt"] is None:
            raise ValidationError("discretize_zoh exige 'dt' positivo.")
        res = discretize_zoh(
            plant_obj,
            payload["dt"],
            tol=_pick_param(payload, options, "tol", None),
            raise_on_error=False,
        )
        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm="scipy.linalg.expm.zoh",
        )

    # simulate_lti
    if "t" in payload and payload["t"] is not None:
        t_arr = _coerce_array(payload["t"], name="t", ndim=1)
    elif "t_final" in payload or "n_steps" in payload:
        n_steps = int(payload.get("n_steps", 101))
        if n_steps < 2:
            raise ValidationError("n_steps deve ser >= 2.")
        if plant_obj.dt is not None:
            t_arr = np.arange(n_steps, dtype=np.float64) * float(plant_obj.dt)
        else:
            t_final = float(payload.get("t_final", 5.0))
            if not np.isfinite(t_final) or t_final <= 0.0:
                raise ValidationError("t_final deve ser número finito > 0.")
            t_arr = np.linspace(0.0, t_final, n_steps, dtype=np.float64)
    else:
        raise ValidationError("simulate_lti exige vetor 't' ou ('t_final', 'n_steps').")

    u_arr = _coerce_array(payload["u"], name="u") if payload.get("u") is not None else None
    x0_arr = _coerce_array(payload["x0"], name="x0") if payload.get("x0") is not None else None
    method = str(_pick_param(payload, options, "method", "auto"))
    rtol = float(_pick_param(payload, options, "rtol", 1e-9))
    atol = float(_pick_param(payload, options, "atol", 1e-12))

    res = simulate_lti(
        plant_obj,
        t_arr,
        u=u_arr,
        x0=x0_arr,
        method=method,
        rtol=rtol,
        atol=atol,
        raise_on_error=False,
    )
    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm="statespace.simulate_lti",
    )


def _handle_frequency(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.frequency import (
        bode,
        eval_response,
        rga,
        root_locus,
        sensitivity,
        singular_values,
        stability_margins,
        step_response_siso,
    )

    payload = req["payload"]
    options = req["options"]
    op = req["operation"]

    plant_obj = _resolve_from_store_or_inline(
        payload,
        inline_keys=("plant", "model"),
        ref_keys=("plant_ref", "model_ref"),
        store=store,
        project_id=req["project_id"],
    )
    if plant_obj is None:
        raise ValidationError(f"Operação {op} exige 'plant' ou 'plant_ref'.")

    omega, w_kwargs = _resolve_omega_arg(payload, options)

    if op in ("frequency.eval_response", "frequency.bode", "frequency.stability_margins"):
        delay = float(_pick_param(payload, options, "delay", 0.0))
        use_pade = bool(_pick_param(payload, options, "use_pade", False))
        pade_order = int(_pick_param(payload, options, "pade_order", 1))
        fn = (
            eval_response
            if op == "frequency.eval_response"
            else (bode if op == "frequency.bode" else stability_margins)
        )
        res = fn(
            plant_obj,
            omega,
            delay=delay,
            use_pade=use_pade,
            pade_order=pade_order,
            raise_on_error=False,
            **w_kwargs,
        )
    elif op == "frequency.root_locus":
        gains = _coerce_array(payload["gains"], name="gains", ndim=1) if payload.get("gains") is not None else None
        extra: dict[str, Any] = {
            "feedback_sign": _pick_param(payload, options, "feedback_sign", "negative"),
            "raise_on_error": False,
        }
        if "n_gains" in payload:
            extra["n_gains"] = int(payload["n_gains"])
        if "k_max" in payload and payload["k_max"] is not None:
            extra["k_max"] = float(payload["k_max"])
        res = root_locus(plant_obj, gains, **extra)
    elif op == "frequency.step_response":
        t_arr = _coerce_array(payload["t"], name="t", ndim=1) if payload.get("t") is not None else None
        extra_step: dict[str, Any] = {
            "amplitude": float(payload.get("amplitude", 1.0)),
            "raise_on_error": False,
        }
        if "n_points" in payload:
            extra_step["n_points"] = int(payload["n_points"])
        if "t_final" in payload and payload["t_final"] is not None:
            extra_step["t_final"] = float(payload["t_final"])
        res = step_response_siso(plant_obj, t_arr, **extra_step)
    elif op in ("frequency.singular_values", "mimo.singular_values"):
        res = singular_values(plant_obj, omega, raise_on_error=False, **w_kwargs)
    elif op == "mimo.rga":
        res = rga(plant_obj, omega, raise_on_error=False)
    else:  # mimo.sensitivity
        ctrl = _resolve_from_store_or_inline(
            payload,
            inline_keys=("controller",),
            ref_keys=("controller_ref",),
            store=store,
            project_id=req["project_id"],
        )
        res = sensitivity(
            plant_obj,
            controller=ctrl,
            omega=omega,
            feedback_sign=_pick_param(payload, options, "feedback_sign", "negative"),
            raise_on_error=False,
            **w_kwargs,
        )

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=op,
    )


def _resolve_optional_mimo_weight(raw_val: Any, *, field_name: str) -> Any:
    if raw_val is None:
        return None
    val = _to_python_native(raw_val)
    if isinstance(val, Mapping) and "kind" in val:
        return _restore_canonical_object(val, field_name=field_name)
    if isinstance(val, Mapping):
        return dict(val)
    return val


def _handle_mimo_synthesis(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.frequency.mimo import (
        design_hinf_mixed_sensitivity,
        design_svd_decoupler,
        simulate_mimo_closed_loop,
    )

    payload = req["payload"]
    options = req["options"]
    op = req["operation"]

    plant_obj = _resolve_from_store_or_inline(
        payload,
        inline_keys=("plant", "model"),
        ref_keys=("plant_ref", "model_ref"),
        store=store,
        project_id=req["project_id"],
    )
    if plant_obj is None:
        raise ValidationError(f"Operação {op} exige 'plant' ou 'plant_ref'.")

    if op == "mimo.design_decoupler":
        omega_targets_raw = _pick_param(payload, options, "omega_targets", None)
        omega_targets: list[float] | None = None
        if omega_targets_raw is not None:
            raw_ot = _to_python_native(omega_targets_raw)
            if not isinstance(raw_ot, (list, tuple, np.ndarray)) and not (
                isinstance(raw_ot, Mapping) and "shape" in raw_ot and "data" in raw_ot
            ):
                raise ValidationError("omega_targets deve ser uma lista não vazia de números finitos.")
            if isinstance(raw_ot, (list, tuple)) and any(isinstance(x, bool) for x in raw_ot):
                raise ValidationError("omega_targets não pode conter booleanos.")
            ot_arr = _coerce_array(raw_ot, name="omega_targets", ndim=1)
            if ot_arr.size == 0:
                raise ValidationError("omega_targets deve ser uma lista não vazia.")
            omega_targets = [float(x) for x in ot_arr.tolist()]

        omega_target_raw = _pick_param(payload, options, "omega_target", 1.0)
        raw_o = _to_python_native(omega_target_raw)
        omega_target: float | list[float]
        if isinstance(raw_o, (list, tuple, np.ndarray)) or (
            isinstance(raw_o, Mapping) and "shape" in raw_o and "data" in raw_o
        ):
            if isinstance(raw_o, (list, tuple)) and any(isinstance(x, bool) for x in raw_o):
                raise ValidationError("omega_target não pode conter booleanos.")
            o_arr = _coerce_array(raw_o, name="omega_target", ndim=1)
            if o_arr.size == 0:
                raise ValidationError("omega_target como lista não pode ser vazio.")
            omega_target = [float(x) for x in o_arr.tolist()]
        elif isinstance(raw_o, (int, float)) and not isinstance(raw_o, bool):
            if not np.isfinite(float(raw_o)):
                raise ValidationError("omega_target deve ser um número finito.")
            omega_target = float(raw_o)
        else:
            raise ValidationError(
                "omega_target deve ser um escalar numérico finito ou uma lista não vazia de números finitos."
            )

        realization_mode = _pick_param(payload, options, "realization_mode", "auto")
        order = payload.get("order")
        if order is not None:
            if not _is_non_bool_int(order) or order < 0 or order > 6:
                raise ValidationError(
                    "order deve ser inteiro entre 0 e 6.",
                    parameters={"order": order},
                )
            order = int(order)
        dt_val = _pick_param(payload, options, "dt", None)
        decoupler_kwargs: dict[str, Any] = {
            "omega_target": omega_target,
            "realization_mode": realization_mode,
            "order": order,
            "dt": dt_val,
            "raise_on_error": False,
        }
        if omega_targets is not None:
            decoupler_kwargs["omega_targets"] = omega_targets
        res = design_svd_decoupler(plant_obj, **decoupler_kwargs)
    elif op == "mimo.simulate_closed_loop":
        has_ctrl = (
            ("controller" in payload and payload["controller"] is not None)
            or ("controller_ref" in payload and payload["controller_ref"] is not None)
        )
        has_gains = "controller_gains" in payload and payload["controller_gains"] is not None
        if has_ctrl and has_gains:
            raise ValidationError(
                "Forneça apenas um entre 'controller'/'controller_ref' e 'controller_gains'."
            )

        ctrl: Any = None
        if has_gains:
            raw_gains = _to_python_native(payload["controller_gains"])
            if isinstance(raw_gains, (int, float)) and not isinstance(raw_gains, bool):
                n_in = getattr(plant_obj, "n_inputs", None)
                dim = int(n_in) if isinstance(n_in, int) and n_in >= 1 else 1
                ctrl = np.full(dim, float(raw_gains), dtype=np.float64)
            else:
                ctrl = _coerce_array(raw_gains, name="controller_gains")
        elif has_ctrl:
            if "controller" in payload and payload["controller"] is not None:
                raw_ctrl = _to_python_native(payload["controller"])
                if isinstance(raw_ctrl, (int, float)) and not isinstance(raw_ctrl, bool):
                    n_in = getattr(plant_obj, "n_inputs", None)
                    dim = int(n_in) if isinstance(n_in, int) and n_in >= 1 else 1
                    ctrl = np.full(dim, float(raw_ctrl), dtype=np.float64)
                elif isinstance(raw_ctrl, (list, tuple, np.ndarray)) or (
                    isinstance(raw_ctrl, Mapping) and "kind" not in raw_ctrl and "shape" in raw_ctrl
                ):
                    ctrl = _coerce_array(raw_ctrl, name="controller")
                else:
                    ctrl = _restore_canonical_object(raw_ctrl, field_name="controller")
            else:
                ctrl = _resolve_from_store_or_inline(
                    payload,
                    inline_keys=(),
                    ref_keys=("controller_ref",),
                    store=store,
                    project_id=req["project_id"],
                )

        dec: Any = None
        if "decoupler" in payload and payload["decoupler"] is not None:
            raw_dec = _to_python_native(payload["decoupler"])
            if isinstance(raw_dec, (list, tuple, np.ndarray)) or (
                isinstance(raw_dec, Mapping) and "kind" not in raw_dec and "shape" in raw_dec
            ):
                dec = _coerce_array(raw_dec, name="decoupler")
            else:
                dec = _restore_canonical_object(raw_dec, field_name="decoupler")
        elif "decoupler_ref" in payload and payload["decoupler_ref"] is not None:
            dec = _resolve_from_store_or_inline(
                payload,
                inline_keys=(),
                ref_keys=("decoupler_ref",),
                store=store,
                project_id=req["project_id"],
            )

        feedback_sign = _pick_param(payload, options, "feedback_sign", "negative")
        t_final = _pick_param(payload, options, "t_final", 10.0)
        n_points = _pick_param(payload, options, "n_points", 200)
        res = simulate_mimo_closed_loop(
            plant_obj,
            controller=ctrl,
            decoupler=dec,
            feedback_sign=feedback_sign,
            t_final=t_final,
            n_points=n_points,
            raise_on_error=False,
        )
    else:  # mimo.design_hinf
        w_s = _resolve_optional_mimo_weight(payload.get("w_s"), field_name="w_s")
        w_u = _resolve_optional_mimo_weight(payload.get("w_u"), field_name="w_u")
        w_t = _resolve_optional_mimo_weight(payload.get("w_t"), field_name="w_t")
        omega, _ = _resolve_omega_arg(payload, options)
        gamma_tol = _pick_param(payload, options, "gamma_tol", 1e-2)
        res = design_hinf_mixed_sensitivity(
            plant_obj,
            w_s=w_s,
            w_u=w_u,
            w_t=w_t,
            omega=omega,
            gamma_tol=gamma_tol,
            raise_on_error=False,
        )

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=op,
    )


def _handle_identification(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.identification import fit_arx, fit_oe, fit_subspace, validate_model

    payload = req["payload"]
    options = req["options"]
    op = req["operation"]

    if op == "identification.validate_model":
        model = _resolve_from_store_or_inline(
            payload,
            inline_keys=("model", "plant"),
            ref_keys=("model_ref", "plant_ref"),
            store=store,
            project_id=req["project_id"],
        )
        val_ds = _resolve_from_store_or_inline(
            payload,
            inline_keys=("val_dataset", "dataset"),
            ref_keys=("val_dataset_ref", "dataset_ref"),
            store=store,
            project_id=req["project_id"],
        )
        if model is None or val_ds is None:
            raise ValidationError("validate_model exige 'model' e 'val_dataset'.")
        train_ds = _resolve_from_store_or_inline(
            payload,
            inline_keys=("train_dataset",),
            ref_keys=("train_dataset_ref",),
            store=store,
            project_id=req["project_id"],
        )
        res = validate_model(model, val_ds, train_dataset=train_ds, raise_on_error=False)
        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm=op,
        )

    ds = _resolve_from_store_or_inline(
        payload,
        inline_keys=("dataset",),
        ref_keys=("dataset_ref",),
        store=store,
        project_id=req["project_id"],
    )
    val_ds = _resolve_from_store_or_inline(
        payload,
        inline_keys=("val_dataset",),
        ref_keys=("val_dataset_ref",),
        store=store,
        project_id=req["project_id"],
    )
    u_arr = _coerce_array(payload["u"], name="u") if payload.get("u") is not None else None
    y_arr = _coerce_array(payload["y"], name="y") if payload.get("y") is not None else None
    t_arr = _coerce_array(payload["t"], name="t", ndim=1) if payload.get("t") is not None else None
    dt_val = payload.get("dt")
    allow_irreg = bool(payload.get("allow_irregular_sampling", False))
    seed = payload.get("seed")

    if op == "identification.fit_arx":
        res = fit_arx(
            dataset=ds,
            val_dataset=val_ds,
            u=u_arr,
            y=y_arr,
            t=t_arr,
            dt=dt_val,
            na=int(payload.get("na", 2)),
            nb=payload.get("nb", 2),
            nk=payload.get("nk", 1),
            detrend=str(payload.get("detrend", "none")),
            allow_irregular_sampling=allow_irreg,
            seed=seed,
            raise_on_error=False,
        )
    elif op == "identification.fit_oe":
        res = fit_oe(
            dataset=ds,
            val_dataset=val_ds,
            u=u_arr,
            y=y_arr,
            t=t_arr,
            dt=dt_val,
            nb=payload.get("nb", 2),
            nf=int(payload.get("nf", 2)),
            nk=payload.get("nk", 1),
            allow_irregular_sampling=allow_irreg,
            seed=seed,
            raise_on_error=False,
        )
    else:  # fit_subspace
        res = fit_subspace(
            dataset=ds,
            val_dataset=val_ds,
            u=u_arr,
            y=y_arr,
            t=t_arr,
            dt=dt_val,
            order=payload.get("order"),
            horizon=payload.get("horizon"),
            method=str(_pick_param(payload, options, "method", "moesp")),
            estimate_feedthrough=bool(payload.get("estimate_feedthrough", False)),
            allow_irregular_sampling=allow_irreg,
            seed=seed,
            raise_on_error=False,
        )

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=op,
    )


def _handle_fuzzy(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.fuzzy import evaluate, evaluate_surface, export_fml, fit_anfis, import_fml

    payload = req["payload"]
    op = req["operation"]

    if op == "fuzzy.fit_anfis":
        if "X" not in payload or "y" not in payload:
            raise ValidationError("Operação fuzzy.fit_anfis exige 'X' e 'y' no payload.")
        X_arr = _coerce_array(payload["X"], name="X")
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)
        elif X_arr.ndim != 2:
            raise DimensionMismatchError(f"X deve ser 1D ou 2D (N, n_inputs), recebido {X_arr.ndim}D.")
        y_arr = _coerce_array(payload["y"], name="y", ndim=1)

        n_mfs = payload.get("n_mfs", 2)
        mf_type = str(payload.get("mf_type", "gaussian"))
        max_epochs_raw = payload.get("max_epochs", 30)
        if isinstance(max_epochs_raw, bool) or not isinstance(max_epochs_raw, int):
            raise ValidationError("max_epochs deve ser inteiro >= 1.")
        learning_rate = float(payload.get("learning_rate", 0.02))
        validation_split = float(payload.get("validation_split", 0.2))
        input_names = payload.get("input_names")
        output_name = str(payload.get("output_name", "y"))

        res = fit_anfis(
            X_arr,
            y_arr,
            n_mfs=n_mfs,
            mf_type=mf_type,
            max_epochs=max_epochs_raw,
            learning_rate=learning_rate,
            validation_split=validation_split,
            input_names=input_names,
            output_name=output_name,
        )
        if res.status != "failure" and res.data is not None and isinstance(res.data, Mapping):
            result_data = dict(res.data)
            fs_raw = result_data.get("fuzzy_system")
            fs_obj: FuzzySystem | None = None
            if isinstance(fs_raw, FuzzySystem):
                fs_obj = fs_raw
                result_data["fuzzy_system"] = fs_obj.to_dict()
            elif isinstance(fs_raw, Mapping) and fs_raw.get("kind") == "FuzzySystem":
                fs_obj = restore_model(fs_raw)
            if fs_obj is not None and store is not None:
                _store_put_object(store, req["project_id"], fs_obj)
                result_data["fuzzy_system_ref"] = {"id": fs_obj.id, "revision": fs_obj.revision}
            return _build_rpc_response(
                request_id=req["request_id"],
                project_id=req["project_id"],
                project_revision=req["project_revision"],
                status=res.status,
                result=result_data,
                assumptions=res.assumptions,
                diagnostics=res.diagnostics,
                provenance=res.provenance,
                warnings=res.warnings,
                error=res.error,
                fallback_algorithm="fuzzy.fit_anfis",
            )

        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm="fuzzy.fit_anfis",
        )

    if op == "fuzzy.import_fml":
        xml_content = payload.get("xml_content", payload.get("xml"))
        if not isinstance(xml_content, str):
            raise ValidationError("fuzzy.import_fml exige 'xml_content' em string.")
        res = import_fml(xml_content)
        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm="fuzzy.import_fml",
        )

    system = _resolve_from_store_or_inline(
        payload,
        inline_keys=("system", "plant", "model"),
        ref_keys=("system_ref", "plant_ref", "model_ref"),
        store=store,
        project_id=req["project_id"],
    )
    if system is None:
        raise ValidationError(f"Operação {op} exige 'system' FuzzySystem (ou system_ref).")

    if op == "fuzzy.export_fml":
        res = export_fml(system)
    elif op == "fuzzy.evaluate_surface" or (op == "fuzzy.evaluate" and "inputs" not in payload):
        n_pts = int(payload.get("n_points", payload.get("grid_points", 25)))
        grid_res = int(payload.get("grid_resolution", 101))
        res = evaluate_surface(
            system,
            input_axes=payload.get("input_axes"),
            fixed_inputs=payload.get("fixed_inputs"),
            n_points=n_pts,
            grid_resolution=grid_res,
        )
    else:
        res = evaluate(
            system,
            payload["inputs"],
            grid_resolution=int(payload.get("grid_resolution", 201)),
            saturate_inputs=bool(payload.get("saturate_inputs", True)),
            coupled_mamdani=bool(payload.get("coupled_mamdani", False)),
        )

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=op,
    )


def _handle_ts_derivation(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.fuzzy.femt import derive_ts_femt
    from control_lab.fuzzy.sector_nonlinearity import analyze_sector_premises, derive_ts_sector
    from control_lab.fuzzy.tpmt import derive_ts_tpmt

    del store
    operation = req["operation"]
    engines = {
        "fuzzy.analyze_sector_premises": analyze_sector_premises,
        "fuzzy.derive_ts_sector": derive_ts_sector,
        "fuzzy.derive_ts_tpmt": derive_ts_tpmt,
        "fuzzy.derive_ts_femt": derive_ts_femt,
    }
    engine = engines[operation]
    try:
        arguments = inspect.signature(engine).bind(**req["payload"])
    except TypeError as exc:
        raise ValidationError(f"Payload inválido para {operation}: {exc}.") from exc

    return _result_to_rpc_response(
        engine(*arguments.args, **arguments.kwargs),
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=operation,
    )


def _handle_export_ts_derivation_script(req: dict[str, Any], store: Any) -> dict[str, Any]:
    operation = req["operation"]
    payload = req["payload"]
    extra = set(payload) - {"model", "model_ref", "language"}
    if extra:
        raise ValidationError(f"Campos extras não suportados em {operation}: {sorted(extra)}.")
    if (payload.get("model") is None) == (payload.get("model_ref") is None):
        raise ValidationError(f"{operation} exige exatamente um entre 'model' e 'model_ref'.")

    language = payload.get("language")
    if language not in ("python", "matlab"):
        raise ValidationError("payload.language deve ser 'python' ou 'matlab'.")
    model = _resolve_from_store_or_inline(
        payload,
        inline_keys=("model",),
        ref_keys=("model_ref",),
        store=store,
        project_id=req["project_id"],
    )
    if not isinstance(model, TSStateSpace):
        raise ValidationError(f"{operation} exige um modelo TSStateSpace.")

    from control_lab.io.ts_derivation import export_ts_derivation_script

    extension, media_type = ("py", "text/x-python") if language == "python" else ("m", "text/x-matlab")
    result = Result(
        status="success",
        data={
            "script": export_ts_derivation_script(model, language),
            "filename": f"controllab_ts_derivation.{extension}",
            "media_type": media_type,
            "language": language,
            "code_executed": False,
            "requires_explicit_user_execution": True,
        },
        provenance=build_provenance(operation, model_revision=model.revision),
    )
    return _result_to_rpc_response(
        result,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm=operation,
    )


def _resolve_sdp_problem_from_payload(
    payload: Mapping[str, Any],
    *,
    store: Any,
    project_id: str,
) -> Any:
    from control_lab.optimization import (
        CanonicalSDPProblem,
        continuous_stabilization_lmi,
        lqr_lmi,
        hinf_brl_lmi,
        regional_pole_placement_lmi,
        ts_pdc_stabilization_lmi,
    )

    if "problem" in payload and payload["problem"] is not None:
        prob = payload["problem"]
        if isinstance(prob, CanonicalSDPProblem):
            return prob
        if isinstance(prob, Mapping):
            if "canonical_sdp" in prob:
                return CanonicalSDPProblem.from_fixture_case(prob)
            return CanonicalSDPProblem.from_dict(prob)
        raise ValidationError("Campo 'problem' deve ser CanonicalSDPProblem ou dict compatível.")

    if "canonical_sdp" in payload and payload["canonical_sdp"] is not None:
        return CanonicalSDPProblem.from_fixture_case({"canonical_sdp": payload["canonical_sdp"]})

    template = payload.get("template")
    if isinstance(template, str) and template.strip():
        t_key = template.strip().lower()
        if t_key in ("quadratic_stabilization", "continuous_stabilization", "decay_rate"):
            plant_obj, mats = _resolve_plant_or_matrices(payload, store=store, project_id=project_id, require_B=True)
            alpha = float(payload.get("alpha", 0.0 if t_key != "decay_rate" else 0.5))
            fb_sign = str(payload.get("feedback_sign", "positive"))
            if plant_obj is not None:
                return continuous_stabilization_lmi(plant_obj, alpha=alpha, feedback_sign=fb_sign)
            return continuous_stabilization_lmi(mats["A"], mats["B"], alpha=alpha, feedback_sign=fb_sign)
        if t_key == "lqr_lmi":
            plant_obj, mats = _resolve_plant_or_matrices(payload, store=store, project_id=project_id, require_B=True)
            return lqr_lmi(plant_obj if plant_obj is not None else mats["A"],
                           None if plant_obj is not None else mats["B"],
                           Q_cost=_coerce_array(payload["Q_cost"], name="Q_cost", ndim=2) if "Q_cost" in payload else None,
                           R_cost=_coerce_array(payload["R_cost"], name="R_cost", ndim=2) if "R_cost" in payload else None,
                           feedback_sign=str(payload.get("feedback_sign", "negative")))
        if t_key == "regional_pole_placement":
            plant_obj, mats = _resolve_plant_or_matrices(payload, store=store, project_id=project_id, require_B=True)
            radius = float(payload["radius"])
            alpha = float(payload["alpha"]) if payload.get("alpha") is not None else None
            fb_sign = str(payload.get("feedback_sign", "positive"))
            if plant_obj is not None:
                return regional_pole_placement_lmi(plant_obj, radius=radius, alpha=alpha, feedback_sign=fb_sign)
            return regional_pole_placement_lmi(mats["A"], mats["B"], radius=radius, alpha=alpha, feedback_sign=fb_sign)
        if t_key == "hinf_brl":
            for k in ("A", "B1", "B2", "C1"):
                if k not in payload:
                    raise ValidationError(f"Template hinf_brl exige matriz '{k}'.")
            return hinf_brl_lmi(
                _coerce_array(payload["A"], name="A", ndim=2),
                _coerce_array(payload["B1"], name="B1", ndim=2),
                _coerce_array(payload["B2"], name="B2", ndim=2),
                _coerce_array(payload["C1"], name="C1", ndim=2),
                D11=_coerce_array(payload["D11"], name="D11", ndim=2) if payload.get("D11") is not None else None,
                D12=_coerce_array(payload["D12"], name="D12", ndim=2) if payload.get("D12") is not None else None,
                gamma=float(payload["gamma"]) if payload.get("gamma") is not None else None,
                feedback_sign=str(payload.get("feedback_sign", "positive")),
            )
        if t_key == "ts_pdc_stabilization":
            ts_obj = _resolve_from_store_or_inline(
                payload,
                inline_keys=("ts_model", "plant"),
                ref_keys=("ts_model_ref", "plant_ref"),
                store=store,
                project_id=project_id,
            )
            if not isinstance(ts_obj, TSStateSpace):
                raise UnsupportedModelError("ts_pdc_stabilization exige modelo TSStateSpace.")
            return ts_pdc_stabilization_lmi(
                ts_obj,
                alpha=float(payload.get("alpha", 0.0)),
                feedback_sign=str(payload.get("feedback_sign", "positive")),
                premise_estimator=payload.get("premise_estimator"),
            )
        raise ValidationError(f"Template SDP desconhecido: {template!r}.")

    raise ValidationError(
        "Operação de otimização exige 'problem', 'canonical_sdp' ou 'template' com planta."
    )


def _handle_optimization(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.optimization import describe_solver_capabilities, solve, verify

    payload = req["payload"]
    options = req["options"]
    op = req["operation"]

    if op == "optimization.capabilities":
        backend = str(_pick_param(payload, options, "backend", "auto"))
        caps = describe_solver_capabilities(backend)
        return _build_rpc_response(
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            status="success",
            result={"capabilities": caps},
            assumptions={"backend": backend},
            diagnostics={},
            provenance=build_provenance("optimization.capabilities"),
            warnings=[],
            error=None,
            fallback_algorithm="optimization.capabilities",
        )

    problem = _resolve_sdp_problem_from_payload(payload, store=store, project_id=req["project_id"])
    tols = payload.get("tolerances", options.get("tolerances"))

    if op == "optimization.verify":
        sol_raw = payload.get("solution", payload)
        sol_dict = dict(sol_raw) if isinstance(sol_raw, Mapping) else sol_raw
        if isinstance(sol_dict, dict):
            if "x" in sol_dict and sol_dict["x"] is not None:
                sol_dict["x"] = _coerce_array(sol_dict["x"], name="x", ndim=1)
            for list_key in ("dual_Z", "farkas_Z"):
                if list_key in sol_dict and isinstance(sol_dict[list_key], list):
                    sol_dict[list_key] = [
                        _coerce_array(item, name=f"{list_key}[{i}]", ndim=2)
                        for i, item in enumerate(sol_dict[list_key])
                    ]
            for vec_key in (
                "dual_eq",
                "dual_ineq",
                "farkas_eq",
                "farkas_ineq",
                "recession_direction",
                "feasible_x0",
            ):
                if vec_key in sol_dict and sol_dict[vec_key] is not None:
                    sol_dict[vec_key] = _coerce_array(sol_dict[vec_key], name=vec_key, ndim=1)

        claimed = payload.get("claimed_status")
        res = verify(
            problem,
            sol_dict,
            claimed_status=claimed,
            tolerances=tols,
            raise_on_error=False,
        )
        return _result_to_rpc_response(
            res,
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            fallback_algorithm="optimization.verification.verify",
        )

    if op in ("optimization.export_cvxpy", "optimization.export_yalmip"):
        from control_lab.optimization import export_to_cvxpy_script, export_to_yalmip_script
        is_python = op == "optimization.export_cvxpy"
        script = export_to_cvxpy_script(problem) if is_python else export_to_yalmip_script(problem)
        return _build_rpc_response(
            request_id=req["request_id"], project_id=req["project_id"],
            project_revision=req["project_revision"], status="success",
            result={"script": script, "filename": "controllab_sdp.py" if is_python else "controllab_sdp.m",
                    "media_type": "text/x-python" if is_python else "text/plain"},
            assumptions={"offline_execution": True}, diagnostics={},
            provenance=build_provenance(op), warnings=[], error=None, fallback_algorithm=op,
        )

    # optimization.solve
    backend = _pick_param(payload, options, "backend", "auto")
    solver_opts = payload.get("solver_options")
    verify_sol = bool(_pick_param(payload, options, "verify_solution", True))
    res = solve(
        problem,
        backend=backend,
        options=solver_opts,
        tolerances=tols,
        verify_solution=verify_sol,
        raise_on_error=False,
    )
    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm="optimization.solve",
    )


def _handle_file(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from control_lab.io.rpc import dispatch_file

    result = dispatch_file(req["operation"], req["payload"], req["project_id"], req["project_revision"])
    return _result_to_rpc_response(
        result, request_id=req["request_id"], project_id=req["project_id"],
        project_revision=req["project_revision"], fallback_algorithm=req["operation"],
    )


def _handle_export_pathsim_script(req: dict[str, Any], store: Any) -> dict[str, Any]:
    from dataclasses import replace

    from control_lab.io.pvm import generate_pathsim_script

    payload = req["payload"]
    allowed_keys = {
        "plant",
        "plant_ref",
        "fuzzy_system",
        "fuzzy_system_ref",
        "system",
        "system_ref",
        "model",
        "model_ref",
        "controller",
        "controller_ref",
        "scenario",
        "filename",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ValidationError(
            message=f"Campos extras não suportados em io.export_pathsim_script: {sorted(extra)}.",
            parameters={"extra_fields": sorted(extra)},
        )

    plant_obj = _resolve_from_store_or_inline(
        payload,
        inline_keys=("plant", "fuzzy_system", "system", "model"),
        ref_keys=("plant_ref", "fuzzy_system_ref", "system_ref", "model_ref"),
        store=store,
        project_id=req["project_id"],
    )
    if plant_obj is None:
        raise ValidationError(
            message=(
                "io.export_pathsim_script exige 'plant'/'plant_ref' ou "
                "'fuzzy_system'/'system_ref'."
            ),
            next_step="Envie um modelo canônico (TSStateSpace, FuzzySystem ou StateSpace) no payload ou via store.",
        )

    ctrl_obj = _resolve_from_store_or_inline(
        payload,
        inline_keys=("controller",),
        ref_keys=("controller_ref",),
        store=store,
        project_id=req["project_id"],
    )

    scenario = payload.get("scenario")
    if scenario is not None and not isinstance(scenario, Mapping):
        raise ValidationError("payload.scenario deve ser um objeto JSON (Mapping) ou null.")

    raw_filename = payload.get("filename")
    if raw_filename is not None:
        if not isinstance(raw_filename, str) or not raw_filename.strip():
            raise ValidationError("payload.filename deve ser string não vazia quando fornecido.")
        filename = raw_filename.strip()
        if not filename.endswith(".py"):
            filename = f"{filename}.py"
    else:
        filename = "controllab_pathsim_simulation.py"

    res = generate_pathsim_script(
        plant_obj,
        controller=ctrl_obj,
        scenario=scenario,
        raise_on_error=False,
    )
    if res.status != "failure" and res.data is not None:
        enriched = dict(res.data)
        enriched["filename"] = filename
        enriched["media_type"] = "text/x-python"
        enriched["code_executed"] = False
        enriched["requires_explicit_user_execution"] = True
        enriched["language"] = "python"
        res = replace(res, data=enriched)

    return _result_to_rpc_response(
        res,
        request_id=req["request_id"],
        project_id=req["project_id"],
        project_revision=req["project_revision"],
        fallback_algorithm="io.export_pathsim_script",
    )


_DISPATCH_TABLE = {
    "core.reuse_model": _handle_core_reuse_model,
    "io.export_ctrlab": _handle_file,
    "io.import_ctrlab": _handle_file,
    "io.export_pvm": _handle_file,
    "io.import_pvm": _handle_file,
    "io.export_pathsim_script": _handle_export_pathsim_script,
    "worker.ping": _handle_worker_ping,
    "rpc.ping": _handle_worker_ping,
    "worker.get_stats": _handle_capabilities,
    "core.capabilities": _handle_capabilities,
    "rpc.capabilities": _handle_capabilities,
    "core.interconnect": _handle_core_interconnect,
    "core.validate_interconnection": _handle_core_interconnect,
    "statespace.design_lqr": _handle_statespace_design_lqr,
    "statespace.design_lqi": _handle_statespace_design_lqi,
    "statespace.design_pole_placement": _handle_statespace_pole_placement,
    "statespace.design_observer": _handle_statespace_pole_placement,
    "statespace.design_kalman": _handle_statespace_kalman_lqg,
    "statespace.design_lqg": _handle_statespace_kalman_lqg,
    "statespace.analyze": _handle_statespace_analysis,
    "statespace.check_pbh": _handle_statespace_analysis,
    "statespace.gramians": _handle_statespace_analysis,
    "statespace.solve_care": _handle_statespace_equations,
    "statespace.solve_dare": _handle_statespace_equations,
    "statespace.solve_lyapunov": _handle_statespace_equations,
    "statespace.solve_sylvester": _handle_statespace_equations,
    "statespace.discretize_zoh": _handle_statespace_sim_discretize,
    "statespace.simulate_lti": _handle_statespace_sim_discretize,
    "frequency.eval_response": _handle_frequency,
    "frequency.bode": _handle_frequency,
    "frequency.stability_margins": _handle_frequency,
    "frequency.root_locus": _handle_frequency,
    "frequency.step_response": _handle_frequency,
    "frequency.singular_values": _handle_frequency,
    "mimo.singular_values": _handle_frequency,
    "mimo.rga": _handle_frequency,
    "mimo.sensitivity": _handle_frequency,
    "mimo.design_decoupler": _handle_mimo_synthesis,
    "mimo.simulate_closed_loop": _handle_mimo_synthesis,
    "mimo.design_hinf": _handle_mimo_synthesis,
    "identification.fit_arx": _handle_identification,
    "identification.fit_oe": _handle_identification,
    "identification.fit_subspace": _handle_identification,
    "identification.validate_model": _handle_identification,
    "fuzzy.evaluate": _handle_fuzzy,
    "fuzzy.evaluate_surface": _handle_fuzzy,
    "fuzzy.fit_anfis": _handle_fuzzy,
    "fuzzy.import_fml": _handle_fuzzy,
    "fuzzy.export_fml": _handle_fuzzy,
    "fuzzy.analyze_sector_premises": _handle_ts_derivation,
    "fuzzy.derive_ts_sector": _handle_ts_derivation,
    "fuzzy.derive_ts_tpmt": _handle_ts_derivation,
    "fuzzy.derive_ts_femt": _handle_ts_derivation,
    "fuzzy.export_ts_derivation_script": _handle_export_ts_derivation_script,
    "optimization.export_cvxpy": _handle_optimization,
    "optimization.export_yalmip": _handle_optimization,
    "optimization.solve": _handle_optimization,
    "optimization.verify": _handle_optimization,
    "optimization.capabilities": _handle_optimization,
}


def _rehydrate_buffers(
    obj: Any,
    buffers: Mapping[str, Any] | None,
    *,
    _inside_packed: bool = False,
) -> Any:
    """Reidrata BufferTensorRef recursivamente quando `buffers` explícito é fornecido.

    Para subárvores sob ``F_k_packed`` (ADR-015), aplica caminho rápido *zero-copy*:
    valida ``shape``/``dtype``/``order``/comprimento em bytes e finitude em C,
    retornando ``np.ndarray`` diretamente sem expansão para listas Python.
    """
    if buffers is None:
        return obj
    if isinstance(obj, list):
        return [_rehydrate_buffers(item, buffers, _inside_packed=_inside_packed) for item in obj]
    if isinstance(obj, Mapping):
        if "buffer_ref" in obj and set(obj.keys()) == {"shape", "dtype", "order", "buffer_ref"}:
            ref_id = obj["buffer_ref"]
            if not isinstance(ref_id, str) or not ref_id.strip():
                raise ValidationError("BufferTensorRef.buffer_ref deve ser string não vazia.")
            if ref_id not in buffers:
                raise ValidationError(
                    message=f"BufferTensorRef {ref_id!r} não encontrado no mapa de buffers fornecido.",
                    parameters={"buffer_ref": ref_id},
                )
            raw_buf = _to_python_native(buffers[ref_id])
            shape = obj["shape"]
            dtype_str = obj["dtype"]
            order = obj["order"]
            if not isinstance(shape, list) or len(shape) < 1 or any(not _is_non_bool_int(d) or d < 0 for d in shape):
                raise ValidationError(f"BufferTensorRef.shape inválido: {shape!r}")
            if order not in ("C", "F"):
                raise ValidationError(f"BufferTensorRef.order inválido: {order!r}")
            np_dtype_map = {
                "float64": np.float64,
                "float32": np.float32,
                "int64": np.int64,
                "int32": np.int32,
                "complex128": np.complex128,
                "complex64": np.complex64,
                "bool": np.bool_,
            }
            if dtype_str not in np_dtype_map:
                raise ValidationError(f"BufferTensorRef.dtype inválido: {dtype_str!r}")
            np_dt = np.dtype(np_dtype_map[dtype_str])
            if isinstance(raw_buf, (bytes, bytearray, memoryview)):
                try:
                    arr = np.frombuffer(raw_buf, dtype=np_dt)
                except (ValueError, TypeError) as exc:
                    byte_len = raw_buf.nbytes if isinstance(raw_buf, memoryview) else len(raw_buf)
                    raise DimensionMismatchError(
                        message=f"Buffer {ref_id!r} incompatível com dtype={dtype_str!r}: {exc}",
                        parameters={
                            "buffer_ref": ref_id,
                            "dtype": dtype_str,
                            "byte_length": byte_len,
                        },
                    ) from exc
                expected_count = int(np.prod(shape))
                if arr.size != expected_count:
                    raise DimensionMismatchError(
                        f"Buffer {ref_id!r} tem {arr.size} elementos, esperado {expected_count} para shape={shape}."
                    )
                arr = arr.reshape(tuple(shape), order=order)
            else:
                try:
                    arr = np.asarray(raw_buf, dtype=np_dt)
                except (ValueError, TypeError) as exc:
                    raise ValidationError(
                        message=f"Conteúdo de buffer {ref_id!r} inválido para dtype={dtype_str!r}: {exc}",
                        parameters={"buffer_ref": ref_id, "dtype": dtype_str},
                    ) from exc
                if list(arr.shape) != shape:
                    raise DimensionMismatchError(
                        f"Buffer {ref_id!r} tem shape {list(arr.shape)}, esperado {shape}."
                    )
            if (
                np.issubdtype(arr.dtype, np.floating)
                or np.issubdtype(arr.dtype, np.complexfloating)
            ) and not bool(np.all(np.isfinite(arr))):
                raise ValidationError(
                    message=f"Buffer {ref_id!r} contém valores não finitos (NaN ou Inf).",
                    parameters={"buffer_ref": ref_id, "dtype": dtype_str},
                )
            if _inside_packed:
                return arr
            return array_to_tensor(arr, dtype=dtype_str, order=order)
        return {
            k: _rehydrate_buffers(v, buffers, _inside_packed=(_inside_packed or k == "F_k_packed"))
            for k, v in obj.items()
        }
    return obj


def dispatch(
    request: Any,
    *,
    store: Any = None,
    buffers: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Despacha RpcRequest canônico (ou envelope Worker) para o motor científico ControlLab.

    Nunca propaga exceções cruas; toda falha de validação, esquema, dimensão ou
    hipótese matemática retorna um `RpcResponse` estritamente válido com `status='failure'`
    e `error` tipado segundo `rpc_response.schema.json`.
    """
    raw_py = _to_python_native(request)
    if (
        isinstance(raw_py, Mapping)
        and "request" in raw_py
        and "operation" not in raw_py
        and isinstance(_to_python_native(raw_py.get("request")), Mapping)
    ):
        req_id, proj_id, proj_rev = _extract_fallback_envelope(_to_python_native(raw_py["request"]))
        op_hint = str(_to_python_native(raw_py["request"]).get("operation") or "core.rpc")
    else:
        req_id, proj_id, proj_rev = _extract_fallback_envelope(raw_py)
        op_hint = (
            str(raw_py.get("operation") or "core.rpc")
            if isinstance(raw_py, Mapping)
            else "core.rpc"
        )

    try:
        envelope_input = raw_py
        if isinstance(envelope_input, (str, bytes, bytearray)):
            envelope_input = strict_json_loads(envelope_input)

        validated_req, resolved_store = _validate_request_envelope(envelope_input, store)

        resolved_buffers = _to_python_native(buffers) if buffers is not None else None
        if (
            resolved_buffers is None
            and isinstance(envelope_input, Mapping)
            and "request" in envelope_input
            and "operation" not in envelope_input
            and "buffers" in envelope_input
            and envelope_input["buffers"] is not None
        ):
            resolved_buffers = _to_python_native(envelope_input["buffers"])

        if resolved_buffers is not None:
            if not isinstance(resolved_buffers, Mapping):
                raise ValidationError("Envelope Worker.buffers deve ser um objeto Mapping.")
            validated_req["payload"] = _rehydrate_buffers(
                validated_req["payload"],
                resolved_buffers,
            )
    except Exception as exc:
        return _error_to_rpc_response(
            exc,
            request_id=req_id,
            project_id=proj_id,
            project_revision=proj_rev,
            algorithm=op_hint,
        )

    req_id = validated_req["request_id"]
    proj_id = validated_req["project_id"]
    proj_rev = validated_req["project_revision"]
    op = validated_req["operation"]

    handler = _DISPATCH_TABLE.get(op)
    if handler is None:
        return _error_to_rpc_response(
            UnsupportedModelError(
                message=f"Operação RPC não suportada: {op!r}.",
                parameters={"operation": op, "supported_operations": sorted(SUPPORTED_OPERATIONS)},
                next_step="Consulte core.capabilities ou worker.ping para listar operações suportadas.",
            ),
            request_id=req_id,
            project_id=proj_id,
            project_revision=proj_rev,
            algorithm=op,
        )

    try:
        return handler(validated_req, resolved_store)
    except Exception as exc:
        return _error_to_rpc_response(
            exc,
            request_id=req_id,
            project_id=proj_id,
            project_revision=proj_rev,
            algorithm=op,
        )


dispatch_rpc = dispatch

__all__ = [
    "RPC_API_VERSION",
    "SUPPORTED_OPERATIONS",
    "dispatch",
    "dispatch_rpc",
]
