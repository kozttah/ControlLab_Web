"""Hierarquia canônica de controladores (ADR-005, Seção 4.2, Apêndice B e controller.schema.json)."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.diagnostics import (
    DimensionMismatchError,
    HypothesisViolatedError,
    Provenance,
    UnsupportedModelError,
    ValidationError,
    ensure_json_finite,
    strict_json_loads,
)

from .models import TSStateSpace, _ImmutableModelBase, _normalize_provenance_mapping
from .tensors import (
    array_to_tensor,
    check_dt_compatible,
    compute_canonical_sha256,
    ensure_finite_float64,
    tensor_to_array,
    validate_name_list,
    validate_non_empty_str,
    validate_revision,
    validate_sample_time,
    validate_schema_version,
)

FEEDBACK_SIGNS: tuple[str, ...] = ("negative", "positive")
_FEEDBACK_SIGN_SET = frozenset(FEEDBACK_SIGNS)

REFERENCE_MAP_KINDS: tuple[str, ...] = (
    "output_prefilter",
    "state_equilibrium",
    "zero_feedforward",
)
_REF_MAP_KIND_SET = frozenset(REFERENCE_MAP_KINDS)

INPUT_PORT_ROLES: tuple[str, ...] = ("y", "r", "w", "u_ff", "error")
OUTPUT_PORT_ROLES: tuple[str, ...] = ("u", "z", "aux")
INTERCONNECTION_SCHEMES: tuple[str, ...] = (
    "output_feedback",
    "error_feedback",
    "two_dof",
    "observer_based",
    "custom",
)
ALLOWED_PDC_TS_KINDS: tuple[str, ...] = ("ts_measured", "ts_partially_observed")


def _validate_feedback_sign(feedback_sign: Any) -> str:
    if not isinstance(feedback_sign, str) or feedback_sign not in _FEEDBACK_SIGN_SET:
        raise ValidationError(
            message=f"feedback_sign inválido ou ausente: {feedback_sign!r}. Deve ser explicitamente 'negative' ou 'positive'.",
            parameters={"feedback_sign": feedback_sign, "allowed": list(FEEDBACK_SIGNS)},
            next_step="Declare feedback_sign='negative' ou feedback_sign='positive'.",
        )
    return feedback_sign


def _normalize_reference_map(
    reference_map: Any,
    m: int,
) -> tuple[dict[str, Any] | np.ndarray | None, np.ndarray | None, str | None, tuple[str, ...] | None, str]:
    """Valida e normaliza reference_map conforme controller.schema.json."""
    if reference_map is None:
        return None, None, None, None, "C"

    # Caso 1: Tensor MatrixFloat64 serializado
    if isinstance(reference_map, Mapping) and "shape" in reference_map and "data" in reference_map:
        order = str(reference_map.get("order", "C"))
        mat = tensor_to_array(reference_map, expected_ndim=2, dtype="float64", strict_dtype=True)
        if mat.shape[0] != m or mat.shape[1] < 1:
            raise DimensionMismatchError(
                message=f"reference_map deve ter {m} linhas (m entradas da planta), recebido shape={mat.shape}.",
                parameters={"expected_rows": m, "actual_shape": list(mat.shape)},
            )
        mat.setflags(write=False)
        return mat, mat, None, None, order

    # Caso 2: Objeto estruturado {kind, matrix, ?reference_names}
    if isinstance(reference_map, Mapping):
        allowed = {"kind", "matrix", "reference_names"}
        extra = set(reference_map.keys()) - allowed
        if extra:
            raise ValidationError(f"Campos extras proibidos em reference_map: {sorted(extra)}")
        if "kind" not in reference_map or "matrix" not in reference_map:
            raise ValidationError("reference_map estruturado requer campos 'kind' e 'matrix'.")
        rm_kind = reference_map["kind"]
        if not isinstance(rm_kind, str) or rm_kind not in _REF_MAP_KIND_SET:
            raise ValidationError(f"reference_map.kind inválido: {rm_kind!r}")

        raw_mat = reference_map["matrix"]
        if isinstance(raw_mat, Mapping) and "shape" in raw_mat and "data" in raw_mat:
            order = str(raw_mat.get("order", "C"))
            mat = tensor_to_array(raw_mat, expected_ndim=2, dtype="float64", strict_dtype=True)
        else:
            order = "C"
            mat = ensure_finite_float64(raw_mat, ndim=2, name="reference_map.matrix")

        if mat.shape[0] != m or mat.shape[1] < 1:
            raise DimensionMismatchError(
                message=f"reference_map.matrix deve ter shape ({m}, p_ref >= 1), recebido {mat.shape}.",
                parameters={"expected_rows": m, "actual_shape": list(mat.shape)},
            )
        mat.setflags(write=False)

        ref_names: tuple[str, ...] | None = None
        if "reference_names" in reference_map and reference_map["reference_names"] is not None:
            rn = reference_map["reference_names"]
            if isinstance(rn, (str, bytes)) or not isinstance(rn, Sequence):
                raise ValidationError("reference_map.reference_names deve ser sequência de strings.")
            if len(rn) != mat.shape[1]:
                raise DimensionMismatchError(
                    f"reference_names tem comprimento {len(rn)}, esperado {mat.shape[1]}."
                )
            for idx, item in enumerate(rn):
                if not isinstance(item, str):
                    raise ValidationError(f"reference_names[{idx}] deve ser string.")
            ref_names = tuple(rn)

        structured: dict[str, Any] = {
            "kind": rm_kind,
            "matrix": mat,
        }
        if ref_names is not None:
            structured["reference_names"] = list(ref_names)
        return structured, mat, rm_kind, ref_names, order

    # Caso 3: array/lista 2D direta
    mat = ensure_finite_float64(reference_map, ndim=2, name="reference_map")
    if mat.shape[0] != m or mat.shape[1] < 1:
        raise DimensionMismatchError(
            message=f"reference_map deve ter shape ({m}, p_ref >= 1), recebido {mat.shape}.",
            parameters={"expected_rows": m, "actual_shape": list(mat.shape)},
        )
    mat.setflags(write=False)
    return mat, mat, None, None, "C"


def _serialize_reference_map(
    ref_raw: dict[str, Any] | np.ndarray | None,
    ref_mat: np.ndarray | None,
    ref_kind: str | None,
    ref_names: tuple[str, ...] | None,
    order: str,
) -> dict[str, Any] | None:
    if ref_raw is None or ref_mat is None:
        return None
    mat_tensor = array_to_tensor(ref_mat, dtype="float64", order=order)
    if ref_kind is None:
        return mat_tensor
    payload: dict[str, Any] = {
        "kind": ref_kind,
        "matrix": mat_tensor,
    }
    if ref_names is not None:
        payload["reference_names"] = list(ref_names)
    return payload


class Controller(_ImmutableModelBase, ABC):
    """Classe base abstrata para hierarquia distinta de controladores (ADR-005)."""

    kind: str

    @property
    @abstractmethod
    def id(self) -> str:
        ...

    @property
    @abstractmethod
    def revision(self) -> int:
        ...

    @property
    @abstractmethod
    def feedback_sign(self) -> str:
        ...

    @property
    @abstractmethod
    def dt(self) -> float | None:
        ...

    @property
    @abstractmethod
    def schema_version(self) -> str:
        ...

    @property
    @abstractmethod
    def provenance(self) -> dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# 1. StateFeedbackController
# ---------------------------------------------------------------------------


class StateFeedbackController(Controller):
    """Controlador por realimentação estática completa de estados: u = u_ff + sign * K x."""

    kind: str = "StateFeedbackController"

    def __init__(
        self,
        K: Any,
        *,
        feedback_sign: str,
        state_coordinates: Sequence[str] | None = None,
        reference_map: Any = None,
        dt: float | None = None,
        id: str | None = None,
        revision: int = 0,
        input_names: Sequence[str] | None = None,
        units: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
        k_order: str = "C",
    ) -> None:
        sign = _validate_feedback_sign(feedback_sign)
        if isinstance(K, Mapping) and "shape" in K and "data" in K:
            resolved_k_order = str(K.get("order", "C"))
            K_arr = tensor_to_array(K, expected_ndim=2, dtype="float64", strict_dtype=True)
        else:
            resolved_k_order = k_order
            if resolved_k_order not in ("C", "F"):
                raise ValidationError(f"k_order inválido: {resolved_k_order!r}")
            K_arr = ensure_finite_float64(K, ndim=2, name="K")

        m, n = K_arr.shape
        if m < 1 or n < 1:
            raise DimensionMismatchError(
                f"Ganho K deve ter shape (m >= 1, n >= 1), recebido {K_arr.shape}."
            )
        K_arr.setflags(write=False)

        coords = validate_name_list(state_coordinates, n, prefix="x", field_name="state_coordinates")
        ref_raw, ref_mat, ref_kind, ref_names, ref_order = _normalize_reference_map(reference_map, m)

        clean_input_names: tuple[str, ...] | None = None
        if input_names is not None:
            if isinstance(input_names, (str, bytes)) or not isinstance(input_names, Sequence):
                raise ValidationError("input_names deve ser sequência de strings.")
            if len(input_names) != m:
                raise DimensionMismatchError(f"input_names deve ter comprimento {m}, recebido {len(input_names)}.")
            for idx, item in enumerate(input_names):
                if not isinstance(item, str):
                    raise ValidationError(f"input_names[{idx}] deve ser string.")
            clean_input_names = tuple(input_names)

        clean_units = ensure_json_finite(dict(units), path="$.units") if units is not None else None
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")

        self._K = K_arr
        self._k_order = resolved_k_order
        self._feedback_sign = sign
        self._state_coordinates = coords
        self._reference_map_raw = ref_raw
        self._reference_matrix = ref_mat
        self._reference_kind = ref_kind
        self._reference_names = ref_names
        self._reference_order = ref_order
        self._dt = validate_sample_time(dt)
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._input_names = clean_input_names
        self._units = clean_units
        self._provenance = _normalize_provenance_mapping(provenance, "control_lab")
        self._created_at = created_at

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "feedback_sign": self._feedback_sign,
                    "dt": self._dt,
                    "K": array_to_tensor(self._K, dtype="float64", order="C"),
                    "state_coordinates": list(self._state_coordinates),
                }
            )
            self._id = f"ctrl-sf-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    @property
    def K(self) -> np.ndarray:
        return self._K

    @property
    def n_inputs(self) -> int:
        return int(self._K.shape[0])

    @property
    def n_states(self) -> int:
        return int(self._K.shape[1])

    @property
    def feedback_sign(self) -> str:
        return self._feedback_sign

    @property
    def state_coordinates(self) -> tuple[str, ...]:
        return self._state_coordinates

    @property
    def reference_map(self) -> dict[str, Any] | np.ndarray | None:
        if isinstance(self._reference_map_raw, dict):
            return copy.deepcopy(self._reference_map_raw)
        return self._reference_map_raw

    @property
    def reference_matrix(self) -> np.ndarray | None:
        return self._reference_matrix

    @property
    def reference_kind(self) -> str | None:
        return self._reference_kind

    @property
    def reference_names(self) -> tuple[str, ...] | None:
        return self._reference_names

    @property
    def dt(self) -> float | None:
        return self._dt

    @property
    def id(self) -> str:
        return self._id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def schema_version(self) -> str:
        return self._schema_version

    @property
    def input_names(self) -> tuple[str, ...] | None:
        return self._input_names

    @property
    def units(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._units) if self._units is not None else None

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    def with_revision(self, revision: int | None = None, **updates: Any) -> StateFeedbackController:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        K_new = updates.pop("K", self._K)
        K_arr = ensure_finite_float64(K_new, ndim=2, name="K")
        n_new = K_arr.shape[1]
        state_coords = updates.pop(
            "state_coordinates",
            self._state_coordinates if n_new == self.n_states else None,
        )
        kwargs = dict(
            K=K_new,
            feedback_sign=updates.pop("feedback_sign", self._feedback_sign),
            state_coordinates=state_coords,
            reference_map=updates.pop("reference_map", self._reference_map_raw),
            dt=updates.pop("dt", self._dt),
            id=updates.pop("id", self._id),
            revision=new_rev,
            input_names=updates.pop("input_names", self._input_names),
            units=updates.pop("units", self._units),
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
            k_order=updates.pop("k_order", self._k_order),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em StateFeedbackController.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return StateFeedbackController(**kwargs)

    def evolve(self, **updates: Any) -> StateFeedbackController:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "feedback_sign": self._feedback_sign,
            "K": array_to_tensor(self._K, dtype="float64", order=self._k_order),
            "state_coordinates": list(self._state_coordinates),
            "reference_map": _serialize_reference_map(
                self._reference_map_raw,
                self._reference_matrix,
                self._reference_kind,
                self._reference_names,
                self._reference_order,
            ),
            "dt": self._dt,
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._input_names is not None:
            payload["input_names"] = list(self._input_names)
        if self._units is not None:
            payload["units"] = copy.deepcopy(self._units)
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StateFeedbackController:
        if not isinstance(data, Mapping):
            raise ValidationError("StateFeedbackController deve ser um objeto JSON.")
        required = {
            "schema_version",
            "id",
            "revision",
            "kind",
            "feedback_sign",
            "K",
            "state_coordinates",
            "reference_map",
            "dt",
            "provenance",
        }
        optional = {"input_names", "units", "created_at"}
        keys = set(data.keys())
        extra = keys - (required | optional)
        if extra:
            raise ValidationError(f"Campos extras proibidos em StateFeedbackController: {sorted(extra)}")
        missing = required - keys
        if missing:
            raise ValidationError(f"Campos obrigatórios ausentes em StateFeedbackController: {sorted(missing)}")
        if data["kind"] != "StateFeedbackController":
            raise UnsupportedModelError(f"kind esperado 'StateFeedbackController', recebido {data['kind']!r}.")
        validate_schema_version(data["schema_version"])
        return cls(
            K=data["K"],
            feedback_sign=data["feedback_sign"],
            state_coordinates=data["state_coordinates"],
            reference_map=data["reference_map"],
            dt=data["dt"],
            id=data["id"],
            revision=data["revision"],
            input_names=data.get("input_names"),
            units=data.get("units"),
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> StateFeedbackController:
        return cls.from_dict(strict_json_loads(raw))


# ---------------------------------------------------------------------------
# 2. DynamicController
# ---------------------------------------------------------------------------


def _validate_ports(
    ports: Mapping[str, Any],
    *,
    nu_c: int,
    ny_c: int,
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(ports, Mapping):
        raise ValidationError("DynamicController.ports deve ser dict com 'inputs' e 'outputs'.")
    if set(ports.keys()) != {"inputs", "outputs"}:
        raise ValidationError(f"DynamicController.ports deve conter exatamente 'inputs' e 'outputs', recebido {sorted(ports.keys())}.")

    clean_ports: dict[str, list[dict[str, Any]]] = {"inputs": [], "outputs": []}
    in_sum = 0
    raw_inputs = ports["inputs"]
    if not isinstance(raw_inputs, Sequence) or isinstance(raw_inputs, (str, bytes)) or len(raw_inputs) < 1:
        raise ValidationError("ports.inputs deve ser lista não vazia.")
    for idx, p in enumerate(raw_inputs):
        if not isinstance(p, Mapping) or set(p.keys()) != {"name", "role", "size"}:
            raise ValidationError(f"ports.inputs[{idx}] deve conter exatamente name, role, size.")
        pname = validate_non_empty_str(p["name"], field_name=f"ports.inputs[{idx}].name")
        role = p["role"]
        if role not in INPUT_PORT_ROLES:
            raise ValidationError(f"ports.inputs[{idx}].role inválido: {role!r}")
        size = p["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValidationError(f"ports.inputs[{idx}].size deve ser inteiro >= 1.")
        in_sum += size
        clean_ports["inputs"].append({"name": pname, "role": role, "size": size})

    out_sum = 0
    raw_outputs = ports["outputs"]
    if not isinstance(raw_outputs, Sequence) or isinstance(raw_outputs, (str, bytes)) or len(raw_outputs) < 1:
        raise ValidationError("ports.outputs deve ser lista não vazia.")
    for idx, p in enumerate(raw_outputs):
        if not isinstance(p, Mapping) or set(p.keys()) != {"name", "role", "size"}:
            raise ValidationError(f"ports.outputs[{idx}] deve conter exatamente name, role, size.")
        pname = validate_non_empty_str(p["name"], field_name=f"ports.outputs[{idx}].name")
        role = p["role"]
        if role not in OUTPUT_PORT_ROLES:
            raise ValidationError(f"ports.outputs[{idx}].role inválido: {role!r}")
        size = p["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValidationError(f"ports.outputs[{idx}].size deve ser inteiro >= 1.")
        out_sum += size
        clean_ports["outputs"].append({"name": pname, "role": role, "size": size})

    if in_sum != nu_c:
        raise DimensionMismatchError(
            message=f"Soma dos tamanhos de ports.inputs ({in_sum}) difere da dimensão de entrada de Bc/Dc ({nu_c}).",
            parameters={"ports_inputs_sum": in_sum, "nu_c": nu_c},
        )
    if out_sum != ny_c:
        raise DimensionMismatchError(
            message=f"Soma dos tamanhos de ports.outputs ({out_sum}) difere da dimensão de saída de Cc/Dc ({ny_c}).",
            parameters={"ports_outputs_sum": out_sum, "ny_c": ny_c},
        )
    return clean_ports


class DynamicController(Controller):
    """Controlador dinâmico (LQG, H∞ dinâmico, PID com estados internos, observadores)."""

    kind: str = "DynamicController"

    def __init__(
        self,
        Ac: Any,
        Bc: Any,
        Cc: Any,
        Dc: Any,
        *,
        feedback_sign: str,
        ports: Mapping[str, Any] | None = None,
        interconnection_scheme: str | None = None,
        initial_state: Any = None,
        dt: float | None = None,
        id: str | None = None,
        revision: int = 0,
        state_names: Sequence[str] | None = None,
        units: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
    ) -> None:
        sign = _validate_feedback_sign(feedback_sign)

        orders = {"Ac": "C", "Bc": "C", "Cc": "C", "Dc": "C", "initial_state": "C"}
        mats: dict[str, np.ndarray] = {}
        for mkey, raw_m in (("Ac", Ac), ("Bc", Bc), ("Cc", Cc), ("Dc", Dc)):
            if isinstance(raw_m, Mapping) and "shape" in raw_m and "data" in raw_m:
                orders[mkey] = str(raw_m.get("order", "C"))
                mats[mkey] = tensor_to_array(raw_m, expected_ndim=2, dtype="float64", strict_dtype=True)
            else:
                mats[mkey] = ensure_finite_float64(raw_m, ndim=2, name=mkey)

        Ac_arr, Bc_arr, Cc_arr, Dc_arr = mats["Ac"], mats["Bc"], mats["Cc"], mats["Dc"]
        nc, nc2 = Ac_arr.shape
        if nc != nc2:
            raise DimensionMismatchError(f"DynamicController.Ac deve ser quadrada, recebido {Ac_arr.shape}.")
        if Bc_arr.shape[0] != nc:
            raise DimensionMismatchError(
                f"DynamicController.Bc linhas ({Bc_arr.shape[0]}) devem igualar nc={nc}."
            )
        nu_c = Bc_arr.shape[1]
        if nu_c < 1:
            raise DimensionMismatchError("DynamicController deve possuir ao menos 1 entrada (nu_c >= 1).")

        if Cc_arr.shape[1] != nc:
            raise DimensionMismatchError(
                f"DynamicController.Cc colunas ({Cc_arr.shape[1]}) devem igualar nc={nc}."
            )
        ny_c = Cc_arr.shape[0]
        if ny_c < 1:
            raise DimensionMismatchError("DynamicController deve possuir ao menos 1 saída (ny_c >= 1).")

        if Dc_arr.shape != (ny_c, nu_c):
            raise DimensionMismatchError(
                f"DynamicController.Dc tem shape {Dc_arr.shape}, esperado ({ny_c}, {nu_c})."
            )

        if interconnection_scheme is not None:
            if not isinstance(interconnection_scheme, str) or interconnection_scheme not in INTERCONNECTION_SCHEMES:
                raise ValidationError(
                    f"interconnection_scheme inválido: {interconnection_scheme!r}. Esperado um de {INTERCONNECTION_SCHEMES}."
                )

        if ports is None:
            if interconnection_scheme in (None, "output_feedback", "observer_based"):
                ports = {
                    "inputs": [{"name": "y", "role": "y", "size": nu_c}],
                    "outputs": [{"name": "u", "role": "u", "size": ny_c}],
                }
            elif interconnection_scheme == "error_feedback":
                ports = {
                    "inputs": [{"name": "e", "role": "error", "size": nu_c}],
                    "outputs": [{"name": "u", "role": "u", "size": ny_c}],
                }
            else:
                raise ValidationError(
                    f"ports é obrigatório quando interconnection_scheme={interconnection_scheme!r}."
                )

        clean_ports = _validate_ports(ports, nu_c=nu_c, ny_c=ny_c)

        if initial_state is None:
            x0_arr = np.zeros((nc,), dtype=np.float64)
        elif isinstance(initial_state, Mapping) and "shape" in initial_state and "data" in initial_state:
            orders["initial_state"] = str(initial_state.get("order", "C"))
            x0_arr = tensor_to_array(initial_state, expected_ndim=1, expected_shape=(nc,), dtype="float64")
        else:
            x0_raw = ensure_finite_float64(initial_state, name="initial_state")
            if x0_raw.ndim == 2 and x0_raw.shape == (nc, 1):
                x0_arr = x0_raw.reshape((nc,))
            elif x0_raw.ndim == 1 and x0_raw.shape == (nc,):
                x0_arr = x0_raw
            else:
                raise DimensionMismatchError(
                    f"initial_state deve ter shape ({nc},), recebido {x0_raw.shape}."
                )

        for arr in (Ac_arr, Bc_arr, Cc_arr, Dc_arr, x0_arr):
            arr.setflags(write=False)

        clean_state_names: tuple[str, ...] | None = None
        if state_names is not None:
            if isinstance(state_names, (str, bytes)) or not isinstance(state_names, Sequence):
                raise ValidationError("state_names deve ser sequência de strings.")
            if len(state_names) != nc:
                raise DimensionMismatchError(f"state_names deve ter comprimento {nc}, recebido {len(state_names)}.")
            for idx, item in enumerate(state_names):
                if not isinstance(item, str):
                    raise ValidationError(f"state_names[{idx}] deve ser string.")
            clean_state_names = tuple(state_names)

        clean_units = ensure_json_finite(dict(units), path="$.units") if units is not None else None
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")

        self._Ac = Ac_arr
        self._Bc = Bc_arr
        self._Cc = Cc_arr
        self._Dc = Dc_arr
        self._initial_state = x0_arr
        self._orders = orders
        self._ports = clean_ports
        self._interconnection_scheme = interconnection_scheme
        self._feedback_sign = sign
        self._dt = validate_sample_time(dt)
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._state_names = clean_state_names
        self._units = clean_units
        self._provenance = _normalize_provenance_mapping(provenance, "control_lab")
        self._created_at = created_at

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "feedback_sign": self._feedback_sign,
                    "dt": self._dt,
                    "Ac": array_to_tensor(self._Ac, dtype="float64", order="C"),
                    "Bc": array_to_tensor(self._Bc, dtype="float64", order="C"),
                    "Cc": array_to_tensor(self._Cc, dtype="float64", order="C"),
                    "Dc": array_to_tensor(self._Dc, dtype="float64", order="C"),
                    "ports": self._ports,
                    "interconnection_scheme": self._interconnection_scheme,
                }
            )
            self._id = f"ctrl-dyn-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    @property
    def Ac(self) -> np.ndarray:
        return self._Ac

    @property
    def Bc(self) -> np.ndarray:
        return self._Bc

    @property
    def Cc(self) -> np.ndarray:
        return self._Cc

    @property
    def Dc(self) -> np.ndarray:
        return self._Dc

    @property
    def initial_state(self) -> np.ndarray:
        return self._initial_state

    @property
    def n_states(self) -> int:
        return int(self._Ac.shape[0])

    @property
    def n_inputs(self) -> int:
        return int(self._Bc.shape[1])

    @property
    def n_outputs(self) -> int:
        return int(self._Cc.shape[0])

    @property
    def ports(self) -> dict[str, list[dict[str, Any]]]:
        return copy.deepcopy(self._ports)

    @property
    def interconnection_scheme(self) -> str | None:
        return self._interconnection_scheme

    @property
    def resolved_scheme(self) -> str:
        if self._interconnection_scheme is not None:
            return self._interconnection_scheme
        roles_in = [p["role"] for p in self._ports["inputs"]]
        if roles_in == ["error"]:
            return "error_feedback"
        if "y" in roles_in and "r" in roles_in:
            return "two_dof"
        return "output_feedback"

    @property
    def feedback_sign(self) -> str:
        return self._feedback_sign

    @property
    def dt(self) -> float | None:
        return self._dt

    @property
    def id(self) -> str:
        return self._id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def schema_version(self) -> str:
        return self._schema_version

    @property
    def state_names(self) -> tuple[str, ...] | None:
        return self._state_names

    @property
    def units(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._units) if self._units is not None else None

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    def with_revision(self, revision: int | None = None, **updates: Any) -> DynamicController:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        Ac_new = updates.pop("Ac", self._Ac)
        Ac_arr = ensure_finite_float64(Ac_new, ndim=2, name="Ac")
        nc_new = Ac_arr.shape[0]
        kwargs = dict(
            Ac=Ac_new,
            Bc=updates.pop("Bc", self._Bc),
            Cc=updates.pop("Cc", self._Cc),
            Dc=updates.pop("Dc", self._Dc),
            feedback_sign=updates.pop("feedback_sign", self._feedback_sign),
            ports=updates.pop("ports", self._ports),
            interconnection_scheme=updates.pop("interconnection_scheme", self._interconnection_scheme),
            initial_state=updates.pop(
                "initial_state",
                self._initial_state if nc_new == self.n_states else None,
            ),
            dt=updates.pop("dt", self._dt),
            id=updates.pop("id", self._id),
            revision=new_rev,
            state_names=updates.pop(
                "state_names",
                self._state_names if nc_new == self.n_states else None,
            ),
            units=updates.pop("units", self._units),
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em DynamicController.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return DynamicController(**kwargs)

    def evolve(self, **updates: Any) -> DynamicController:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "feedback_sign": self._feedback_sign,
            "dt": self._dt,
            "Ac": array_to_tensor(self._Ac, dtype="float64", order=self._orders["Ac"]),
            "Bc": array_to_tensor(self._Bc, dtype="float64", order=self._orders["Bc"]),
            "Cc": array_to_tensor(self._Cc, dtype="float64", order=self._orders["Cc"]),
            "Dc": array_to_tensor(self._Dc, dtype="float64", order=self._orders["Dc"]),
            "ports": copy.deepcopy(self._ports),
            "initial_state": array_to_tensor(
                self._initial_state, dtype="float64", order=self._orders["initial_state"]
            ),
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._interconnection_scheme is not None:
            payload["interconnection_scheme"] = self._interconnection_scheme
        if self._state_names is not None:
            payload["state_names"] = list(self._state_names)
        if self._units is not None:
            payload["units"] = copy.deepcopy(self._units)
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DynamicController:
        if not isinstance(data, Mapping):
            raise ValidationError("DynamicController deve ser um objeto JSON.")
        required = {
            "schema_version",
            "id",
            "revision",
            "kind",
            "feedback_sign",
            "dt",
            "Ac",
            "Bc",
            "Cc",
            "Dc",
            "ports",
            "initial_state",
            "provenance",
        }
        optional = {"interconnection_scheme", "state_names", "units", "created_at"}
        keys = set(data.keys())
        extra = keys - (required | optional)
        if extra:
            raise ValidationError(f"Campos extras proibidos em DynamicController: {sorted(extra)}")
        missing = required - keys
        if missing:
            raise ValidationError(f"Campos obrigatórios ausentes em DynamicController: {sorted(missing)}")
        if data["kind"] != "DynamicController":
            raise UnsupportedModelError(f"kind esperado 'DynamicController', recebido {data['kind']!r}.")
        validate_schema_version(data["schema_version"])
        return cls(
            Ac=data["Ac"],
            Bc=data["Bc"],
            Cc=data["Cc"],
            Dc=data["Dc"],
            feedback_sign=data["feedback_sign"],
            ports=data["ports"],
            interconnection_scheme=data.get("interconnection_scheme"),
            initial_state=data["initial_state"],
            dt=data["dt"],
            id=data["id"],
            revision=data["revision"],
            state_names=data.get("state_names"),
            units=data.get("units"),
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> DynamicController:
        return cls.from_dict(strict_json_loads(raw))


# ---------------------------------------------------------------------------
# 3. PDCController
# ---------------------------------------------------------------------------


class PDCController(Controller):
    """Controlador Parallel Distributed Compensation (PDC) para modelos TS com premissas explícitas."""

    kind: str = "PDCController"

    def __init__(
        self,
        K_i: Sequence[Any],
        *,
        feedback_sign: str,
        membership_ref: Mapping[str, Any],
        measurement_requirements: Mapping[str, Any],
        state_coordinates: Sequence[str] | None = None,
        reference_map: Any = None,
        dt: float | None = None,
        id: str | None = None,
        revision: int = 0,
        units: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
    ) -> None:
        sign = _validate_feedback_sign(feedback_sign)

        if not isinstance(K_i, Sequence) or isinstance(K_i, (str, bytes)) or len(K_i) < 1:
            raise ValidationError("PDCController.K_i deve ser lista não vazia de ganhos.")

        parsed_gains: list[np.ndarray] = []
        orders: list[str] = []
        expected_shape: tuple[int, int] | None = None
        for idx, raw_k in enumerate(K_i):
            if isinstance(raw_k, Mapping) and "shape" in raw_k and "data" in raw_k:
                orders.append(str(raw_k.get("order", "C")))
                k_arr = tensor_to_array(raw_k, expected_ndim=2, dtype="float64", strict_dtype=True)
            else:
                orders.append("C")
                k_arr = ensure_finite_float64(raw_k, ndim=2, name=f"K_i[{idx}]")
            if k_arr.shape[0] < 1 or k_arr.shape[1] < 1:
                raise DimensionMismatchError(f"K_i[{idx}] deve ter shape (m >= 1, n >= 1), recebido {k_arr.shape}.")
            if expected_shape is None:
                expected_shape = (k_arr.shape[0], k_arr.shape[1])
            elif k_arr.shape != expected_shape:
                raise DimensionMismatchError(
                    f"Todos os ganhos K_i devem ter shape idêntico; K_i[0]={expected_shape}, K_i[{idx}]={k_arr.shape}."
                )
            k_arr.setflags(write=False)
            parsed_gains.append(k_arr)

        assert expected_shape is not None
        m, n = expected_shape

        # Valida membership_ref
        if not isinstance(membership_ref, Mapping):
            raise ValidationError("PDCController.membership_ref deve ser Mapping.")
        mref_req = {"model_id", "model_revision", "membership_version"}
        if set(membership_ref.keys()) != mref_req:
            raise ValidationError(
                f"membership_ref deve conter exatamente {sorted(mref_req)}, recebido {sorted(membership_ref.keys())}."
            )
        clean_mref = ensure_json_finite(dict(membership_ref), path="$.membership_ref")
        validate_non_empty_str(clean_mref["model_id"], field_name="membership_ref.model_id")
        validate_revision(clean_mref["model_revision"], field_name="membership_ref.model_revision")
        validate_non_empty_str(clean_mref["membership_version"], field_name="membership_ref.membership_version")

        # Valida measurement_requirements
        if not isinstance(measurement_requirements, Mapping):
            raise ValidationError("PDCController.measurement_requirements deve ser Mapping.")
        mr_req = {"required_premise_variables", "requires_full_state", "allowed_ts_kinds"}
        if set(measurement_requirements.keys()) != mr_req:
            raise ValidationError(
                f"measurement_requirements deve conter exatamente {sorted(mr_req)}, recebido {sorted(measurement_requirements.keys())}."
            )
        clean_mr = ensure_json_finite(dict(measurement_requirements), path="$.measurement_requirements")
        req_vars = clean_mr["required_premise_variables"]
        if not isinstance(req_vars, list) or not all(isinstance(v, str) and len(v) > 0 for v in req_vars):
            raise ValidationError("required_premise_variables deve ser lista de strings não vazias.")
        if not isinstance(clean_mr["requires_full_state"], bool):
            raise ValidationError("requires_full_state deve ser booleano.")
        allowed_kinds = clean_mr["allowed_ts_kinds"]
        if not isinstance(allowed_kinds, list) or len(allowed_kinds) < 1:
            raise ValidationError("allowed_ts_kinds deve ser lista não vazia.")
        for k_item in allowed_kinds:
            if k_item == "polytopic_uncertain":
                raise HypothesisViolatedError(
                    message=(
                        "PDCController não pode incluir 'polytopic_uncertain' em allowed_ts_kinds: "
                        "pesos politópicos desconhecidos não permitem agendamento PDC sem estimador explícito (T-TS-01)."
                    ),
                    parameters={"allowed_ts_kinds": allowed_kinds},
                    next_step="Use arquitetura robusta de ganho único ou modelo TS com premissas mensuráveis/observador explícito.",
                )
            if k_item not in ALLOWED_PDC_TS_KINDS:
                raise ValidationError(
                    f"Tipo TS inválido em allowed_ts_kinds: {k_item!r}. Permitidos: {ALLOWED_PDC_TS_KINDS}."
                )

        clean_coords: tuple[str, ...] | None = None
        if state_coordinates is not None:
            if isinstance(state_coordinates, (str, bytes)) or not isinstance(state_coordinates, Sequence):
                raise ValidationError("state_coordinates deve ser sequência de strings.")
            if len(state_coordinates) != n:
                raise DimensionMismatchError(
                    f"state_coordinates deve ter comprimento {n}, recebido {len(state_coordinates)}."
                )
            for idx, item in enumerate(state_coordinates):
                if not isinstance(item, str):
                    raise ValidationError(f"state_coordinates[{idx}] deve ser string.")
            clean_coords = tuple(state_coordinates)

        ref_raw, ref_mat, ref_kind, ref_names, ref_order = _normalize_reference_map(reference_map, m)
        clean_units = ensure_json_finite(dict(units), path="$.units") if units is not None else None
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")

        self._K_i = tuple(parsed_gains)
        self._k_orders = tuple(orders)
        self._n_inputs = m
        self._n_states = n
        self._feedback_sign = sign
        self._membership_ref = clean_mref
        self._measurement_requirements = clean_mr
        self._state_coordinates = clean_coords
        self._reference_map_raw = ref_raw
        self._reference_matrix = ref_mat
        self._reference_kind = ref_kind
        self._reference_names = ref_names
        self._reference_order = ref_order
        self._dt = validate_sample_time(dt)
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._units = clean_units
        self._provenance = _normalize_provenance_mapping(provenance, "control_lab")
        self._created_at = created_at

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "feedback_sign": self._feedback_sign,
                    "dt": self._dt,
                    "K_i": [array_to_tensor(k, dtype="float64", order="C") for k in self._K_i],
                    "membership_ref": self._membership_ref,
                }
            )
            self._id = f"ctrl-pdc-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    @property
    def K_i(self) -> tuple[np.ndarray, ...]:
        return self._K_i

    @property
    def n_rules(self) -> int:
        return len(self._K_i)

    @property
    def n_inputs(self) -> int:
        return self._n_inputs

    @property
    def n_states(self) -> int:
        return self._n_states

    @property
    def feedback_sign(self) -> str:
        return self._feedback_sign

    @property
    def membership_ref(self) -> dict[str, Any]:
        return copy.deepcopy(self._membership_ref)

    @property
    def measurement_requirements(self) -> dict[str, Any]:
        return copy.deepcopy(self._measurement_requirements)

    @property
    def state_coordinates(self) -> tuple[str, ...] | None:
        return self._state_coordinates

    @property
    def reference_map(self) -> dict[str, Any] | np.ndarray | None:
        if isinstance(self._reference_map_raw, dict):
            return copy.deepcopy(self._reference_map_raw)
        return self._reference_map_raw

    @property
    def reference_matrix(self) -> np.ndarray | None:
        return self._reference_matrix

    @property
    def reference_kind(self) -> str | None:
        return self._reference_kind

    @property
    def reference_names(self) -> tuple[str, ...] | None:
        return self._reference_names

    @property
    def dt(self) -> float | None:
        return self._dt

    @property
    def id(self) -> str:
        return self._id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def schema_version(self) -> str:
        return self._schema_version

    @property
    def units(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._units) if self._units is not None else None

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    def validate_against_ts_model(
        self,
        ts_model: TSStateSpace,
        *,
        premise_estimator: Any = None,
    ) -> None:
        """Valida compatibilidade física, dimensional e de premissas com TSStateSpace (T-TS-01)."""
        if not isinstance(ts_model, TSStateSpace):
            raise UnsupportedModelError("validate_against_ts_model requer instância TSStateSpace.")

        if ts_model.kind == "polytopic_uncertain":
            if premise_estimator is None:
                raise HypothesisViolatedError(
                    message=(
                        "PDCController não é implementável sobre TSStateSpace(kind='polytopic_uncertain') "
                        "sem estimador explícito de premissas (T-TS-01 / ADR-006)."
                    ),
                    parameters={
                        "ts_model_id": ts_model.id,
                        "ts_kind": ts_model.kind,
                        "premise_mode": ts_model.premise_availability["mode"],
                    },
                    next_step="Substitua por controlador de ganho único robusto ou forneça premissas medidas/estimador.",
                )
            if ts_model.kind not in self._measurement_requirements["allowed_ts_kinds"]:
                raise HypothesisViolatedError(
                    message="PDCController não autoriza associação direta com 'polytopic_uncertain'.",
                    parameters={"allowed_ts_kinds": self._measurement_requirements["allowed_ts_kinds"]},
                )

        if ts_model.kind not in self._measurement_requirements["allowed_ts_kinds"]:
            raise HypothesisViolatedError(
                message=f"TSStateSpace.kind={ts_model.kind!r} não está autorizado em allowed_ts_kinds={self._measurement_requirements['allowed_ts_kinds']!r}.",
                parameters={"ts_kind": ts_model.kind, "allowed": self._measurement_requirements["allowed_ts_kinds"]},
            )

        check_dt_compatible(ts_model.dt, self._dt, label_a="ts_model", label_b="pdc_controller")

        if self._membership_ref["model_id"] != ts_model.id:
            raise ValidationError(
                message=f"membership_ref.model_id ({self._membership_ref['model_id']!r}) difere de ts_model.id ({ts_model.id!r}).",
                parameters={"expected_id": ts_model.id, "actual_id": self._membership_ref["model_id"]},
            )
        if self._membership_ref["model_revision"] != ts_model.revision:
            raise HypothesisViolatedError(
                message=(
                    f"Revisão obsoleta: PDCController referencia model_revision={self._membership_ref['model_revision']}, "
                    f"mas ts_model está na revision={ts_model.revision}."
                ),
                parameters={"controller_model_revision": self._membership_ref["model_revision"], "ts_revision": ts_model.revision},
            )
        if self._membership_ref["membership_version"] != ts_model.membership_spec["version"]:
            raise HypothesisViolatedError(
                message=(
                    f"Versão de pertinência incompatível: controller={self._membership_ref['membership_version']!r} "
                    f"vs model={ts_model.membership_spec['version']!r}."
                )
            )

        if self.n_rules != ts_model.n_vertices:
            raise DimensionMismatchError(
                f"Número de ganhos K_i ({self.n_rules}) difere do número de vértices ({ts_model.n_vertices})."
            )
        if (self._n_inputs, self._n_states) != (ts_model.n_inputs, ts_model.n_states):
            raise DimensionMismatchError(
                f"Dimensão dos ganhos K_i ({self._n_inputs}, {self._n_states}) incompatível com planta TS ({ts_model.n_inputs}, {ts_model.n_states})."
            )

        pa = ts_model.premise_availability
        model_premises = set(ts_model.membership_spec["premise_variables"])
        req_vars = set(self._measurement_requirements["required_premise_variables"])
        measured = set(pa["measured_premises"])
        unmeasured = set(pa["unmeasured_premises"])

        if not model_premises.issubset(req_vars):
            omitted = sorted(model_premises - req_vars)
            raise HypothesisViolatedError(
                message=(
                    "PDCController.measurement_requirements.required_premise_variables omite "
                    f"premissas definidas em membership_spec: {omitted}."
                ),
                parameters={"omitted_premises": omitted, "model_premises": sorted(model_premises)},
                next_step="Inclua todas as variáveis de premissa do modelo TS e forneça estimador se houver não medidas.",
            )

        missing_measured = req_vars - measured
        if ts_model.kind == "ts_measured":
            if missing_measured or (req_vars & unmeasured):
                raise HypothesisViolatedError(
                    message=f"Premissas requeridas pelo PDC não estão todas medidas: faltam {sorted(missing_measured)}.",
                    parameters={"missing_premises": sorted(missing_measured)},
                )
        elif ts_model.kind == "ts_partially_observed":
            est_required = pa.get("estimator_required_for_pdc", True)
            if (unmeasured or est_required or (req_vars & unmeasured) or missing_measured) and premise_estimator is None:
                raise HypothesisViolatedError(
                    message=(
                        "TSStateSpace(kind='ts_partially_observed') possui premissas não medidas ou requer estimador "
                        "explícito; interconexão com PDCController exige premise_estimator (Seção 4.3 / ADR-006)."
                    ),
                    parameters={
                        "unmeasured_premises": sorted(unmeasured),
                        "unmeasured_required": sorted(req_vars & unmeasured),
                        "estimator_required_for_pdc": bool(est_required),
                    },
                    next_step="Forneça um premise_estimator explícito para reconstruir as premissas/estados não medidos.",
                )

    def with_revision(self, revision: int | None = None, **updates: Any) -> PDCController:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        kwargs = dict(
            K_i=updates.pop("K_i", self._K_i),
            feedback_sign=updates.pop("feedback_sign", self._feedback_sign),
            membership_ref=updates.pop("membership_ref", self._membership_ref),
            measurement_requirements=updates.pop("measurement_requirements", self._measurement_requirements),
            state_coordinates=updates.pop("state_coordinates", self._state_coordinates),
            reference_map=updates.pop("reference_map", self._reference_map_raw),
            dt=updates.pop("dt", self._dt),
            id=updates.pop("id", self._id),
            revision=new_rev,
            units=updates.pop("units", self._units),
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em PDCController.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return PDCController(**kwargs)

    def evolve(self, **updates: Any) -> PDCController:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "feedback_sign": self._feedback_sign,
            "K_i": [
                array_to_tensor(k, dtype="float64", order=ord_k)
                for k, ord_k in zip(self._K_i, self._k_orders, strict=True)
            ],
            "membership_ref": copy.deepcopy(self._membership_ref),
            "measurement_requirements": copy.deepcopy(self._measurement_requirements),
            "dt": self._dt,
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._state_coordinates is not None:
            payload["state_coordinates"] = list(self._state_coordinates)
        if self._reference_map_raw is not None:
            payload["reference_map"] = _serialize_reference_map(
                self._reference_map_raw,
                self._reference_matrix,
                self._reference_kind,
                self._reference_names,
                self._reference_order,
            )
        if self._units is not None:
            payload["units"] = copy.deepcopy(self._units)
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PDCController:
        if not isinstance(data, Mapping):
            raise ValidationError("PDCController deve ser um objeto JSON.")
        required = {
            "schema_version",
            "id",
            "revision",
            "kind",
            "feedback_sign",
            "K_i",
            "membership_ref",
            "measurement_requirements",
            "dt",
            "provenance",
        }
        optional = {"state_coordinates", "reference_map", "units", "created_at"}
        keys = set(data.keys())
        extra = keys - (required | optional)
        if extra:
            raise ValidationError(f"Campos extras proibidos em PDCController: {sorted(extra)}")
        missing = required - keys
        if missing:
            raise ValidationError(f"Campos obrigatórios ausentes em PDCController: {sorted(missing)}")
        if data["kind"] != "PDCController":
            raise UnsupportedModelError(f"kind esperado 'PDCController', recebido {data['kind']!r}.")
        validate_schema_version(data["schema_version"])
        return cls(
            K_i=data["K_i"],
            feedback_sign=data["feedback_sign"],
            membership_ref=data["membership_ref"],
            measurement_requirements=data["measurement_requirements"],
            state_coordinates=data.get("state_coordinates"),
            reference_map=data.get("reference_map"),
            dt=data["dt"],
            id=data["id"],
            revision=data["revision"],
            units=data.get("units"),
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> PDCController:
        return cls.from_dict(strict_json_loads(raw))
