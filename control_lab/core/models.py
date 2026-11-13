"""Modelos científicos canônicos imutáveis por revisão (CL-DIR-001 Seção 4.1, 4.3, Apêndice B)."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Sequence

import numpy as np
import scipy.signal

from control_lab.diagnostics import (
    DimensionMismatchError,
    HypothesisViolatedError,
    Provenance,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    ensure_json_finite,
    strict_json_dumps,
    strict_json_loads,
)

from .tensors import (
    array_to_tensor,
    compute_canonical_sha256,
    ensure_finite_float64,
    tensor_to_array,
    validate_name_list,
    validate_non_empty_str,
    validate_revision,
    validate_sample_time,
    validate_schema_version,
    validate_sha256_hex,
    validate_units_dict,
)

TS_MODEL_KINDS: tuple[str, ...] = (
    "ts_measured",
    "polytopic_uncertain",
    "ts_partially_observed",
)
_TS_KIND_SET = frozenset(TS_MODEL_KINDS)

PREMISE_MODES: tuple[str, ...] = (
    "all_measured",
    "partially_observed",
    "unknown_uncertain",
)
_PREMISE_MODE_SET = frozenset(PREMISE_MODES)


class _ImmutableModelBase:
    """Base auxiliar que bloqueia mutação pós-inicialização e oferece evolução por revisão."""

    _locked: bool = False

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_locked", False):
            raise AttributeError(
                f"{type(self).__name__} é imutável por revisão; use with_revision() ou evolve()."
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            f"{type(self).__name__} é imutável por revisão; não é permitido remover atributos."
        )

    def _lock(self) -> None:
        object.__setattr__(self, "_locked", True)

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - interface abstrata
        raise NotImplementedError

    def to_json(self, *, indent: int | None = None, sort_keys: bool = True) -> str:
        return strict_json_dumps(self.to_dict(), indent=indent, sort_keys=sort_keys)


def _normalize_provenance_mapping(provenance: Mapping[str, Any] | Provenance | None, default_source: str) -> dict[str, Any]:
    if provenance is None:
        return {"source": default_source}
    if isinstance(provenance, Provenance):
        return provenance.to_dict()
    if isinstance(provenance, Mapping):
        return ensure_json_finite(dict(provenance), path="$.provenance")
    raise ValidationError("provenance deve ser dict/Mapping ou Provenance.")


# ---------------------------------------------------------------------------
# 1. StateSpace
# ---------------------------------------------------------------------------


class StateSpace(_ImmutableModelBase):
    """Modelo LTI em espaço de estados contínuo ou discreto, imutável por revisão."""

    kind: str = "StateSpace"

    def __init__(
        self,
        A: Any,
        B: Any,
        C: Any,
        D: Any = None,
        dt: float | None = None,
        *,
        id: str | None = None,
        revision: int = 0,
        state_names: Sequence[str] | None = None,
        input_names: Sequence[str] | None = None,
        output_names: Sequence[str] | None = None,
        units: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
        content_hash: str | None = None,
        matrix_orders: Mapping[str, str] | None = None,
    ) -> None:
        A_arr = ensure_finite_float64(A, ndim=2, name="A")
        n, n2 = A_arr.shape
        if n != n2:
            raise DimensionMismatchError(
                message=f"Matriz A deve ser quadrada (n, n), recebido shape={A_arr.shape}.",
                parameters={"A_shape": list(A_arr.shape)},
                next_step="Forneça uma matriz A quadrada n x n.",
            )

        B_arr = ensure_finite_float64(B, ndim=2, name="B")
        if B_arr.shape[0] != n:
            raise DimensionMismatchError(
                message=f"Dimensão incompatível entre A {A_arr.shape} e B {B_arr.shape}: linhas de B devem ser {n}.",
                parameters={"A_shape": list(A_arr.shape), "B_shape": list(B_arr.shape)},
                next_step="Ajuste o número de linhas de B para igualar o número de estados n.",
            )
        m = B_arr.shape[1]

        C_arr = ensure_finite_float64(C, ndim=2, name="C")
        if C_arr.shape[1] != n:
            raise DimensionMismatchError(
                message=f"Dimensão incompatível entre A {A_arr.shape} e C {C_arr.shape}: colunas de C devem ser {n}.",
                parameters={"A_shape": list(A_arr.shape), "C_shape": list(C_arr.shape)},
                next_step="Ajuste o número de colunas de C para igualar n.",
            )
        p = C_arr.shape[0]

        if D is None:
            D_arr = np.zeros((p, m), dtype=np.float64)
        else:
            D_arr = ensure_finite_float64(D, ndim=2, name="D")
            if D_arr.shape != (p, m):
                raise DimensionMismatchError(
                    message=f"Dimensão incompatível de D {D_arr.shape}; esperado ({p}, {m}) conforme C e B.",
                    parameters={"D_shape": list(D_arr.shape), "expected_shape": [p, m]},
                    next_step="Ajuste D para shape (p, m).",
                )

        for arr in (A_arr, B_arr, C_arr, D_arr):
            arr.setflags(write=False)

        resolved_dt = validate_sample_time(dt)
        resolved_schema = validate_schema_version(schema_version)
        resolved_rev = validate_revision(revision)
        resolved_states = validate_name_list(state_names, n, prefix="x", field_name="state_names")
        resolved_inputs = validate_name_list(input_names, m, prefix="u", field_name="input_names")
        resolved_outputs = validate_name_list(output_names, p, prefix="y", field_name="output_names")
        resolved_units = validate_units_dict(units, n_states=n, n_inputs=m, n_outputs=p, require_io=True)
        resolved_prov = _normalize_provenance_mapping(provenance, "control_lab")

        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")
        resolved_hash = validate_sha256_hex(content_hash)

        orders = {"A": "C", "B": "C", "C": "C", "D": "C"}
        if matrix_orders is not None:
            for k, v in matrix_orders.items():
                if k in orders:
                    if v not in ("C", "F"):
                        raise ValidationError(f"Ordem de matriz inválida para {k}: {v!r}")
                    orders[k] = v

        self._A = A_arr
        self._B = B_arr
        self._C = C_arr
        self._D = D_arr
        self._dt = resolved_dt
        self._schema_version = resolved_schema
        self._revision = resolved_rev
        self._state_names = resolved_states
        self._input_names = resolved_inputs
        self._output_names = resolved_outputs
        self._units = resolved_units
        self._provenance = resolved_prov
        self._created_at = created_at
        self._content_hash = resolved_hash
        self._matrix_orders = orders

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "dt": self._dt,
                    "A": array_to_tensor(self._A, dtype="float64", order="C"),
                    "B": array_to_tensor(self._B, dtype="float64", order="C"),
                    "C": array_to_tensor(self._C, dtype="float64", order="C"),
                    "D": array_to_tensor(self._D, dtype="float64", order="C"),
                    "state_names": list(self._state_names),
                    "input_names": list(self._input_names),
                    "output_names": list(self._output_names),
                    "units": self._units,
                }
            )
            self._id = f"ss-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    @property
    def A(self) -> np.ndarray:
        return self._A

    @property
    def B(self) -> np.ndarray:
        return self._B

    @property
    def C(self) -> np.ndarray:
        return self._C

    @property
    def D(self) -> np.ndarray:
        return self._D

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
    def state_names(self) -> tuple[str, ...]:
        return self._state_names

    @property
    def input_names(self) -> tuple[str, ...]:
        return self._input_names

    @property
    def output_names(self) -> tuple[str, ...]:
        return self._output_names

    @property
    def units(self) -> dict[str, Any]:
        return copy.deepcopy(self._units)

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    @property
    def content_hash(self) -> str | None:
        return self._content_hash

    @property
    def n_states(self) -> int:
        return int(self._A.shape[0])

    @property
    def n_inputs(self) -> int:
        return int(self._B.shape[1])

    @property
    def n_outputs(self) -> int:
        return int(self._C.shape[0])

    @property
    def is_continuous(self) -> bool:
        return self._dt is None

    @property
    def is_discrete(self) -> bool:
        return self._dt is not None

    def poles(self) -> np.ndarray:
        return np.linalg.eigvals(self._A)

    def _base_payload_for_hash(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "dt": self._dt,
            "state_names": list(self._state_names),
            "input_names": list(self._input_names),
            "output_names": list(self._output_names),
            "matrices": {
                "A": array_to_tensor(self._A, dtype="float64", order=self._matrix_orders["A"]),
                "B": array_to_tensor(self._B, dtype="float64", order=self._matrix_orders["B"]),
                "C": array_to_tensor(self._C, dtype="float64", order=self._matrix_orders["C"]),
                "D": array_to_tensor(self._D, dtype="float64", order=self._matrix_orders["D"]),
            },
            "units": copy.deepcopy(self._units),
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return payload

    def compute_content_hash(self) -> str:
        return compute_canonical_sha256(self._base_payload_for_hash())

    def with_content_hash(self) -> StateSpace:
        digest = self.compute_content_hash()
        return self.with_revision(self._revision, content_hash=digest)

    def with_revision(self, revision: int | None = None, **updates: Any) -> StateSpace:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        A = updates.pop("A", self._A)
        B = updates.pop("B", self._B)
        C = updates.pop("C", self._C)
        D = updates.pop("D", self._D)
        dt = updates.pop("dt", self._dt)

        A_new = ensure_finite_float64(A, ndim=2, name="A")
        B_new = ensure_finite_float64(B, ndim=2, name="B")
        C_new = ensure_finite_float64(C, ndim=2, name="C")
        n_new, m_new, p_new = A_new.shape[0], B_new.shape[1], C_new.shape[0]

        state_names = updates.pop("state_names", self._state_names if n_new == self.n_states else None)
        input_names = updates.pop("input_names", self._input_names if m_new == self.n_inputs else None)
        output_names = updates.pop("output_names", self._output_names if p_new == self.n_outputs else None)

        if "units" in updates:
            units = updates.pop("units")
        elif n_new == self.n_states and m_new == self.n_inputs and p_new == self.n_outputs:
            units = self._units
        else:
            units = {"time": self._units.get("time", "s")}

        id_val = updates.pop("id", self._id)
        provenance_val = updates.pop("provenance", self._provenance)
        schema_val = updates.pop("schema_version", self._schema_version)
        created_val = updates.pop("created_at", self._created_at)
        hash_val = updates.pop("content_hash", None)
        orders_val = updates.pop("matrix_orders", self._matrix_orders)
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em StateSpace.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )

        return StateSpace(
            A=A_new,
            B=B_new,
            C=C_new,
            D=D,
            dt=dt,
            id=id_val,
            revision=new_rev,
            state_names=state_names,
            input_names=input_names,
            output_names=output_names,
            units=units,
            provenance=provenance_val,
            schema_version=schema_val,
            created_at=created_val,
            content_hash=hash_val,
            matrix_orders=orders_val,
        )

    def evolve(self, **updates: Any) -> StateSpace:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self, *, include_content_hash: bool = False) -> dict[str, Any]:
        payload = self._base_payload_for_hash()
        if self._content_hash is not None:
            payload["content_hash"] = self._content_hash
        elif include_content_hash:
            payload["content_hash"] = self.compute_content_hash()
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StateSpace:
        if not isinstance(data, Mapping):
            raise ValidationError("StateSpace deve ser um objeto JSON.")
        required = {
            "schema_version",
            "id",
            "revision",
            "kind",
            "dt",
            "state_names",
            "input_names",
            "output_names",
            "matrices",
            "units",
            "provenance",
        }
        optional = {"created_at", "content_hash"}
        keys = set(data.keys())
        extra = keys - (required | optional)
        if extra:
            raise ValidationError(f"Campos extras proibidos em StateSpace: {sorted(extra)}")
        missing = required - keys
        if missing:
            raise ValidationError(f"Campos obrigatórios ausentes em StateSpace: {sorted(missing)}")

        if data["kind"] != "StateSpace":
            raise UnsupportedModelError(f"kind esperado 'StateSpace', recebido {data['kind']!r}.")

        validate_schema_version(data["schema_version"])

        matrices = data["matrices"]
        if not isinstance(matrices, Mapping) or set(matrices.keys()) != {"A", "B", "C", "D"}:
            raise ValidationError("StateSpace.matrices deve conter exatamente as chaves A, B, C, D.")

        A = tensor_to_array(matrices["A"], expected_ndim=2, dtype="float64", strict_dtype=True)
        B = tensor_to_array(matrices["B"], expected_ndim=2, dtype="float64", strict_dtype=True)
        C = tensor_to_array(matrices["C"], expected_ndim=2, dtype="float64", strict_dtype=True)
        D = tensor_to_array(matrices["D"], expected_ndim=2, dtype="float64", strict_dtype=True)

        units = data["units"]
        if not isinstance(units, Mapping) or not {"time", "inputs", "outputs"}.issubset(units.keys()):
            raise ValidationError("StateSpace.units requer campos 'time', 'inputs' e 'outputs'.")

        orders = {k: str(matrices[k]["order"]) for k in ("A", "B", "C", "D")}
        return cls(
            A=A,
            B=B,
            C=C,
            D=D,
            dt=data["dt"],
            id=data["id"],
            revision=data["revision"],
            state_names=data["state_names"],
            input_names=data["input_names"],
            output_names=data["output_names"],
            units=units,
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
            content_hash=data.get("content_hash"),
            matrix_orders=orders,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> StateSpace:
        return cls.from_dict(strict_json_loads(raw))


# ---------------------------------------------------------------------------
# 2. TransferFunction
# ---------------------------------------------------------------------------


def _normalize_poly_matrix(
    raw: Any,
    *,
    name: str,
) -> tuple[tuple[tuple[np.ndarray, ...], ...], int, int]:
    """Normaliza entrada SISO (1D) ou MIMO (matriz p x m de polinômios 1D)."""
    if raw is None or isinstance(raw, (str, bytes, Mapping)):
        raise ValidationError(f"TransferFunction.{name} inválido.")

    # Detecta SISO 1D: [1.0, 2.0] ou np.ndarray 1D
    if isinstance(raw, np.ndarray) and raw.ndim == 1:
        arr = ensure_finite_float64(raw, ndim=1, name=f"{name}[0,0]")
        if arr.size == 0:
            raise ValidationError(f"Polinômio em {name} não pode ser vazio.")
        arr.setflags(write=False)
        return ((arr,),), 1, 1

    if isinstance(raw, Sequence) and len(raw) > 0 and all(
        isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool) for x in raw
    ):
        arr = ensure_finite_float64(raw, ndim=1, name=f"{name}[0,0]")
        arr.setflags(write=False)
        return ((arr,),), 1, 1

    if not isinstance(raw, Sequence) or len(raw) == 0:
        raise ValidationError(f"TransferFunction.{name} deve ser lista/matriz não vazia de polinômios.")

    rows: list[tuple[np.ndarray, ...]] = []
    expected_m: int | None = None
    for i, row in enumerate(raw):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) == 0:
            raise ValidationError(f"TransferFunction.{name}[{i}] deve ser linha não vazia de polinômios.")
        if expected_m is None:
            expected_m = len(row)
        elif len(row) != expected_m:
            raise DimensionMismatchError(
                f"TransferFunction.{name} tem linhas de comprimentos diferentes ({expected_m} vs {len(row)})."
            )
        row_arrs: list[np.ndarray] = []
        for j, poly in enumerate(row):
            p_arr = ensure_finite_float64(poly, ndim=1, name=f"{name}[{i},{j}]")
            if p_arr.size == 0:
                raise ValidationError(f"Polinômio {name}[{i},{j}] não pode ser vazio.")
            p_arr.setflags(write=False)
            row_arrs.append(p_arr)
        rows.append(tuple(row_arrs))

    assert expected_m is not None
    return tuple(rows), len(rows), expected_m


class TransferFunction(_ImmutableModelBase):
    """Função de transferência contínua (s) ou discreta (z, z^-1), SISO e MIMO."""

    kind: str = "TransferFunction"

    def __init__(
        self,
        num: Any,
        den: Any,
        dt: float | None = None,
        *,
        variable: str | None = None,
        poly_order: str = "descending",
        id: str | None = None,
        revision: int = 0,
        input_names: Sequence[str] | None = None,
        output_names: Sequence[str] | None = None,
        units: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
    ) -> None:
        resolved_dt = validate_sample_time(dt)
        if variable is None:
            resolved_var = "s" if resolved_dt is None else "z"
        else:
            resolved_var = variable

        if resolved_dt is None:
            if resolved_var != "s":
                raise ValidationError(
                    message=f"Sistema contínuo (dt=None) requer variable='s', recebido {resolved_var!r}.",
                    parameters={"dt": None, "variable": resolved_var},
                )
        else:
            if resolved_var not in ("z", "z^-1"):
                raise ValidationError(
                    message=f"Sistema discreto (dt={resolved_dt}) requer variable 'z' ou 'z^-1', recebido {resolved_var!r}.",
                    parameters={"dt": resolved_dt, "variable": resolved_var},
                )

        if poly_order not in ("descending", "ascending"):
            raise ValidationError(
                f"poly_order inválido: {poly_order!r}. Use 'descending' ou 'ascending'."
            )

        num_mat, p_num, m_num = _normalize_poly_matrix(num, name="num")
        den_mat, p_den, m_den = _normalize_poly_matrix(den, name="den")
        if (p_num, m_num) != (p_den, m_den):
            raise DimensionMismatchError(
                message=f"Dimensões de num {(p_num, m_num)} e den {(p_den, m_den)} não coincidem.",
                parameters={"num_shape": [p_num, m_num], "den_shape": [p_den, m_den]},
            )

        for i in range(p_den):
            for j in range(m_den):
                if np.all(den_mat[i][j] == 0.0):
                    raise ValidationError(
                        message=f"Denominador identicamente nulo no canal ({i}, {j}).",
                        parameters={"output_index": i, "input_index": j},
                    )

        self._num = num_mat
        self._den = den_mat
        self._n_outputs = p_num
        self._n_inputs = m_num
        self._dt = resolved_dt
        self._variable = resolved_var
        self._poly_order = poly_order
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._input_names = validate_name_list(input_names, m_num, prefix="u", field_name="input_names")
        self._output_names = validate_name_list(output_names, p_num, prefix="y", field_name="output_names")
        self._units = validate_units_dict(units, n_inputs=m_num, n_outputs=p_num, require_io=True)
        self._provenance = _normalize_provenance_mapping(provenance, "control_lab")
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")
        self._created_at = created_at
        self._warnings = tuple(self._compute_conditioning_warnings())

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "dt": self._dt,
                    "variable": self._variable,
                    "poly_order": self._poly_order,
                    "num": [[a.tolist() for a in row] for row in self._num],
                    "den": [[a.tolist() for a in row] for row in self._den],
                }
            )
            self._id = f"tf-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    def _compute_conditioning_warnings(self) -> list[WarningItem]:
        warnings_found: list[WarningItem] = []
        max_deg = 0
        max_ratio = 1.0
        near_singular_lead = False
        for i in range(self._n_outputs):
            for j in range(self._n_inputs):
                for poly, is_den in ((self._num[i][j], False), (self._den[i][j], True)):
                    deg = max(0, poly.size - 1)
                    max_deg = max(max_deg, deg)
                    nz = np.abs(poly[poly != 0.0])
                    if nz.size > 0:
                        ratio = float(np.max(nz) / np.min(nz))
                        max_ratio = max(max_ratio, ratio)
                    if is_den and poly.size > 1:
                        lead = abs(float(poly[0] if self._poly_order == "descending" else poly[-1]))
                        pmax = float(np.max(np.abs(poly)))
                        if pmax > 0.0 and lead < 1e-12 * pmax:
                            near_singular_lead = True

        if max_deg >= 12 or max_ratio > 1e10 or near_singular_lead:
            warnings_found.append(
                WarningItem(
                    code="ILL_CONDITIONED_POLYNOMIAL",
                    message=(
                        "Função de transferência potencialmente mal condicionada "
                        f"(grau_max={max_deg}, razão_coeficientes={max_ratio:.3e})."
                    ),
                    details={
                        "max_degree": max_deg,
                        "max_coeff_ratio": max_ratio,
                        "near_singular_leading_den": near_singular_lead,
                    },
                )
            )
        return warnings_found

    @property
    def num(self) -> tuple[tuple[np.ndarray, ...], ...]:
        return self._num

    @property
    def den(self) -> tuple[tuple[np.ndarray, ...], ...]:
        return self._den

    @property
    def dt(self) -> float | None:
        return self._dt

    @property
    def variable(self) -> str:
        return self._variable

    @property
    def poly_order(self) -> str:
        return self._poly_order

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
    def input_names(self) -> tuple[str, ...]:
        return self._input_names

    @property
    def output_names(self) -> tuple[str, ...]:
        return self._output_names

    @property
    def units(self) -> dict[str, Any]:
        return copy.deepcopy(self._units)

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    @property
    def n_inputs(self) -> int:
        return self._n_inputs

    @property
    def n_outputs(self) -> int:
        return self._n_outputs

    @property
    def is_siso(self) -> bool:
        return self._n_inputs == 1 and self._n_outputs == 1

    @property
    def warnings(self) -> tuple[WarningItem, ...]:
        return self._warnings

    def assess_conditioning(self) -> dict[str, Any]:
        return {
            "is_ill_conditioned": len(self._warnings) > 0,
            "warnings": [w.to_dict() for w in self._warnings],
        }

    def _channel_descending_z_or_s(self, i: int, j: int) -> tuple[np.ndarray, np.ndarray]:
        num_ij = self._num[i][j].copy()
        den_ij = self._den[i][j].copy()
        if self._poly_order == "ascending":
            num_ij = num_ij[::-1]
            den_ij = den_ij[::-1]
        if self._variable == "z^-1":
            # num(z^-1)/den(z^-1) = (z^k * num_asc) / (z^k * den_asc)
            num_asc = self._num[i][j] if self._poly_order == "ascending" else self._num[i][j][::-1]
            den_asc = self._den[i][j] if self._poly_order == "ascending" else self._den[i][j][::-1]
            deg = max(num_asc.size, den_asc.size) - 1
            num_z = np.zeros(deg + 1, dtype=np.float64)
            den_z = np.zeros(deg + 1, dtype=np.float64)
            for idx, val in enumerate(num_asc):
                num_z[deg - idx] = val
            for idx, val in enumerate(den_asc):
                den_z[deg - idx] = val
            num_ij, den_ij = num_z[::-1], den_z[::-1]
        num_ij = np.trim_zeros(num_ij, "f")
        den_ij = np.trim_zeros(den_ij, "f")
        if num_ij.size == 0:
            num_ij = np.array([0.0], dtype=np.float64)
        if den_ij.size == 0:
            raise ValidationError(f"Denominador nulo no canal ({i}, {j}).")
        return num_ij, den_ij

    def to_state_space(self) -> StateSpace:
        """Converte TransferFunction própria (SISO ou MIMO) em StateSpace com detecção de mal condicionamento."""
        A_blocks: list[np.ndarray] = []
        B_blocks: list[np.ndarray] = []
        C_blocks: list[np.ndarray] = []
        D_mat = np.zeros((self._n_outputs, self._n_inputs), dtype=np.float64)
        extra_warnings: list[dict[str, Any]] = [w.to_dict() for w in self._warnings]

        for i in range(self._n_outputs):
            for j in range(self._n_inputs):
                num_ij, den_ij = self._channel_descending_z_or_s(i, j)
                if num_ij.size > den_ij.size:
                    raise UnsupportedModelError(
                        message=f"Função de transferência imprópria no canal ({i}, {j}): grau(num) > grau(den).",
                        parameters={"output": i, "input": j, "deg_num": num_ij.size - 1, "deg_den": den_ij.size - 1},
                    )
                den_max = float(np.max(np.abs(den_ij)))
                if (
                    abs(float(den_ij[0])) <= 1e-15 * max(1.0, den_max)
                    if den_ij.size > 1
                    else float(den_ij[0]) == 0.0
                ):
                    raise ValidationError(f"Coeficiente líder do denominador próximo de zero no canal ({i}, {j}).")

                # Canais nulos ou puramente estáticos não têm dinâmica: evitar scipy.signal.tf2ss
                # (que fabrica polo espúrio em 0.0 e emite BadCoefficients).
                if np.all(num_ij == 0.0):
                    D_mat[i, j] = 0.0
                    continue
                if den_ij.size == 1:
                    d_val = float(num_ij[0] / den_ij[0])
                    if not math.isfinite(d_val):
                        raise ValidationError(f"Ganho estático não finito no canal ({i}, {j}).")
                    D_mat[i, j] = d_val
                    continue

                A_ij, B_ij, C_ij, D_ij = scipy.signal.tf2ss(num_ij, den_ij)
                if A_ij.shape[0] >= 2:
                    cond_a = float(np.linalg.cond(A_ij))
                    if not math.isfinite(cond_a) or cond_a > 1e10:
                        extra_warnings.append(
                            WarningItem(
                                code="ILL_CONDITIONED_CONVERSION",
                                message=f"Realização de estado mal condicionada no canal ({i}, {j}): cond(A)={cond_a:.3e}.",
                                details={"channel": [i, j], "cond_A": cond_a if math.isfinite(cond_a) else -1.0},
                            ).to_dict()
                        )
                n_ij = A_ij.shape[0]
                if n_ij > 0:
                    A_blocks.append(A_ij)
                    B_full = np.zeros((n_ij, self._n_inputs), dtype=np.float64)
                    B_full[:, [j]] = B_ij
                    B_blocks.append(B_full)
                    C_full = np.zeros((self._n_outputs, n_ij), dtype=np.float64)
                    C_full[[i], :] = C_ij
                    C_blocks.append(C_full)
                D_mat[i, j] = float(D_ij[0, 0])

        if A_blocks:
            n_tot = sum(blk.shape[0] for blk in A_blocks)
            A_tot = np.zeros((n_tot, n_tot), dtype=np.float64)
            offset = 0
            for blk in A_blocks:
                k = blk.shape[0]
                A_tot[offset : offset + k, offset : offset + k] = blk
                offset += k
            B_tot = np.vstack(B_blocks)
            C_tot = np.hstack(C_blocks)
        else:
            A_tot = np.zeros((0, 0), dtype=np.float64)
            B_tot = np.zeros((0, self._n_inputs), dtype=np.float64)
            C_tot = np.zeros((self._n_outputs, 0), dtype=np.float64)

        prov = copy.deepcopy(self._provenance)
        prov["converted_from"] = {"kind": "TransferFunction", "id": self._id, "revision": self._revision}
        if extra_warnings:
            prov["conversion_warnings"] = extra_warnings

        return StateSpace(
            A=A_tot,
            B=B_tot,
            C=C_tot,
            D=D_mat,
            dt=self._dt,
            input_names=self._input_names,
            output_names=self._output_names,
            units=self._units,
            provenance=prov,
        )

    @classmethod
    def from_state_space(cls, ss: StateSpace) -> TransferFunction:
        if not isinstance(ss, StateSpace):
            raise UnsupportedModelError("from_state_space requer uma instância StateSpace.")
        p, m = ss.n_outputs, ss.n_inputs
        num_grid: list[list[np.ndarray]] = [[np.array([0.0]) for _ in range(m)] for _ in range(p)]
        den_grid: list[list[np.ndarray]] = [[np.array([1.0]) for _ in range(m)] for _ in range(p)]
        if ss.n_states == 0:
            for i in range(p):
                for j in range(m):
                    num_grid[i][j] = np.array([float(ss.D[i, j])], dtype=np.float64)
                    den_grid[i][j] = np.array([1.0], dtype=np.float64)
        else:
            for j in range(m):
                nums_j, den_j = scipy.signal.ss2tf(ss.A, ss.B, ss.C, ss.D, input=j)
                den_clean = np.trim_zeros(np.asarray(den_j, dtype=np.float64), "f")
                if den_clean.size == 0:
                    den_clean = np.array([1.0], dtype=np.float64)
                for i in range(p):
                    num_clean = np.trim_zeros(np.asarray(nums_j[i], dtype=np.float64), "f")
                    if num_clean.size == 0:
                        num_clean = np.array([0.0], dtype=np.float64)
                    num_grid[i][j] = num_clean
                    den_grid[i][j] = den_clean
        prov = ss.provenance
        prov["converted_from"] = {"kind": "StateSpace", "id": ss.id, "revision": ss.revision}
        return cls(
            num=num_grid,
            den=den_grid,
            dt=ss.dt,
            variable="s" if ss.dt is None else "z",
            poly_order="descending",
            input_names=ss.input_names,
            output_names=ss.output_names,
            units=ss.units,
            provenance=prov,
        )

    def with_revision(self, revision: int | None = None, **updates: Any) -> TransferFunction:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        kwargs = dict(
            num=updates.pop("num", self._num),
            den=updates.pop("den", self._den),
            dt=updates.pop("dt", self._dt),
            variable=updates.pop("variable", self._variable),
            poly_order=updates.pop("poly_order", self._poly_order),
            id=updates.pop("id", self._id),
            revision=new_rev,
            input_names=updates.pop("input_names", self._input_names),
            output_names=updates.pop("output_names", self._output_names),
            units=updates.pop("units", self._units),
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em TransferFunction.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return TransferFunction(**kwargs)

    def evolve(self, **updates: Any) -> TransferFunction:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "dt": self._dt,
            "variable": self._variable,
            "poly_order": self._poly_order,
            "input_names": list(self._input_names),
            "output_names": list(self._output_names),
            "num": [[array_to_tensor(a, dtype="float64", order="C") for a in row] for row in self._num],
            "den": [[array_to_tensor(a, dtype="float64", order="C") for a in row] for row in self._den],
            "units": copy.deepcopy(self._units),
            "warnings": [w.to_dict() for w in self._warnings],
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TransferFunction:
        if not isinstance(data, Mapping):
            raise ValidationError("TransferFunction deve ser um objeto JSON.")
        if data.get("kind") != "TransferFunction":
            raise UnsupportedModelError(f"kind esperado 'TransferFunction', recebido {data.get('kind')!r}.")
        for req in ("schema_version", "id", "revision", "dt", "variable", "poly_order", "num", "den", "units", "provenance"):
            if req not in data:
                raise ValidationError(f"Campo obrigatório ausente em TransferFunction: {req!r}")
        validate_schema_version(data["schema_version"])
        num_raw = data["num"]
        den_raw = data["den"]
        if not isinstance(num_raw, list) or not isinstance(den_raw, list):
            raise ValidationError("num e den em TransferFunction serializada devem ser matrizes 2D.")
        num_arrs = [[tensor_to_array(cell, expected_ndim=1, dtype="float64", strict_dtype=True) for cell in row] for row in num_raw]
        den_arrs = [[tensor_to_array(cell, expected_ndim=1, dtype="float64", strict_dtype=True) for cell in row] for row in den_raw]
        return cls(
            num=num_arrs,
            den=den_arrs,
            dt=data["dt"],
            variable=data["variable"],
            poly_order=data["poly_order"],
            id=data["id"],
            revision=data["revision"],
            input_names=data.get("input_names"),
            output_names=data.get("output_names"),
            units=data["units"],
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> TransferFunction:
        return cls.from_dict(strict_json_loads(raw))


# ---------------------------------------------------------------------------
# 3. Dataset e IdentifiedModel
# ---------------------------------------------------------------------------


class Dataset(_ImmutableModelBase):
    """Séries temporais experimentais t, u, y (SISO/MIMO) com verificação de amostragem."""

    kind: str = "Dataset"

    def __init__(
        self,
        t: Any,
        u: Any,
        y: Any,
        *,
        dt: float | None = None,
        require_uniform: bool = False,
        sampling_rtol: float = 1e-6,
        id: str | None = None,
        revision: int = 0,
        input_names: Sequence[str] | None = None,
        output_names: Sequence[str] | None = None,
        units: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
    ) -> None:
        t_arr = ensure_finite_float64(t, ndim=1, name="t")
        if t_arr.size < 1:
            raise ValidationError("Dataset.t deve conter pelo menos 1 amostra.")
        if t_arr.size >= 2 and not np.all(np.diff(t_arr) > 0.0):
            raise ValidationError(
                message="Dataset.t deve ser estritamente crescente.",
                next_step="Ordene e remova timestamps duplicados ou regressivos.",
            )

        u_raw = ensure_finite_float64(u, name="u")
        if u_raw.ndim == 1:
            u_arr = u_raw.reshape(-1, 1)
        elif u_raw.ndim == 2:
            u_arr = u_raw
        else:
            raise DimensionMismatchError(f"Dataset.u deve ser 1D ou 2D, recebido {u_raw.ndim}D.")

        y_raw = ensure_finite_float64(y, name="y")
        if y_raw.ndim == 1:
            y_arr = y_raw.reshape(-1, 1)
        elif y_raw.ndim == 2:
            y_arr = y_raw
        else:
            raise DimensionMismatchError(f"Dataset.y deve ser 1D ou 2D, recebido {y_raw.ndim}D.")

        n_samples = t_arr.shape[0]
        if u_arr.shape[0] != n_samples or y_arr.shape[0] != n_samples:
            raise DimensionMismatchError(
                message=(
                    f"Comprimento das séries incompatível: len(t)={n_samples}, "
                    f"u.shape[0]={u_arr.shape[0]}, y.shape[0]={y_arr.shape[0]}."
                ),
                parameters={"len_t": n_samples, "u_rows": u_arr.shape[0], "y_rows": y_arr.shape[0]},
            )
        if u_arr.shape[1] < 1 or y_arr.shape[1] < 1:
            raise DimensionMismatchError("Dataset deve possuir ao menos 1 canal de entrada e 1 de saída.")

        for arr in (t_arr, u_arr, y_arr):
            arr.setflags(write=False)

        resolved_dt = validate_sample_time(dt)
        if sampling_rtol <= 0.0 or not math.isfinite(sampling_rtol):
            raise ValidationError("sampling_rtol deve ser finito > 0.")

        if n_samples >= 2:
            diffs = np.diff(t_arr)
            dt_mean = float(np.mean(diffs))
            dt_min = float(np.min(diffs))
            dt_max = float(np.max(diffs))
            ref_dt = resolved_dt if resolved_dt is not None else dt_mean
            deviations = np.abs(diffs - ref_dt)
            max_jitter = float(np.max(deviations))
            rel_jitter = float(max_jitter / ref_dt) if ref_dt > 0.0 else float("inf")
            irregular_idx = [int(i) for i in np.where(deviations > sampling_rtol * ref_dt)[0].tolist()]
            is_uniform = len(irregular_idx) == 0
        else:
            dt_mean = resolved_dt if resolved_dt is not None else 0.0
            dt_min = dt_mean
            dt_max = dt_mean
            max_jitter = 0.0
            rel_jitter = 0.0
            irregular_idx = []
            is_uniform = True

        sampling_diag: dict[str, Any] = {
            "n_samples": int(n_samples),
            "is_uniform": bool(is_uniform),
            "dt_declared": resolved_dt,
            "dt_mean": dt_mean,
            "dt_min": dt_min,
            "dt_max": dt_max,
            "max_jitter": max_jitter,
            "rel_jitter": rel_jitter,
            "sampling_rtol": float(sampling_rtol),
            "irregular_count": len(irregular_idx),
        }

        if require_uniform and not is_uniform:
            raise ValidationError(
                message=f"Amostragem irregular detectada (rel_jitter={rel_jitter:.3e} > rtol={sampling_rtol:.3e}).",
                parameters=sampling_diag,
                next_step="Reamostre os dados ou desative require_uniform se usar método compatível.",
            )

        m = u_arr.shape[1]
        p = y_arr.shape[1]
        self._t = t_arr
        self._u = u_arr
        self._y = y_arr
        self._dt = resolved_dt
        self._sampling_diagnostics = sampling_diag
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._input_names = validate_name_list(input_names, m, prefix="u", field_name="input_names")
        self._output_names = validate_name_list(output_names, p, prefix="y", field_name="output_names")
        self._units = validate_units_dict(units, n_inputs=m, n_outputs=p, require_io=True)
        self._provenance = _normalize_provenance_mapping(provenance, "control_lab")
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")
        self._created_at = created_at
        self._warnings: tuple[WarningItem, ...] = (
            (
                WarningItem(
                    code="NON_UNIFORM_SAMPLING",
                    message=f"Amostragem não uniforme detectada ({len(irregular_idx)} intervalos fora da tolerância).",
                    details=sampling_diag,
                ),
            )
            if not is_uniform
            else ()
        )

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "t": array_to_tensor(self._t, dtype="float64", order="C"),
                    "u": array_to_tensor(self._u, dtype="float64", order="C"),
                    "y": array_to_tensor(self._y, dtype="float64", order="C"),
                }
            )
            self._id = f"ds-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    @property
    def t(self) -> np.ndarray:
        return self._t

    @property
    def u(self) -> np.ndarray:
        return self._u

    @property
    def y(self) -> np.ndarray:
        return self._y

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
    def n_samples(self) -> int:
        return int(self._t.shape[0])

    @property
    def n_inputs(self) -> int:
        return int(self._u.shape[1])

    @property
    def n_outputs(self) -> int:
        return int(self._y.shape[1])

    @property
    def is_uniform_sampling(self) -> bool:
        return bool(self._sampling_diagnostics["is_uniform"])

    @property
    def sampling_diagnostics(self) -> dict[str, Any]:
        return copy.deepcopy(self._sampling_diagnostics)

    @property
    def input_names(self) -> tuple[str, ...]:
        return self._input_names

    @property
    def output_names(self) -> tuple[str, ...]:
        return self._output_names

    @property
    def units(self) -> dict[str, Any]:
        return copy.deepcopy(self._units)

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    @property
    def warnings(self) -> tuple[WarningItem, ...]:
        return self._warnings

    def train_val_split(
        self,
        *,
        train_fraction: float = 0.7,
        train_slice: slice | None = None,
        val_slice: slice | None = None,
    ) -> tuple[Dataset, Dataset]:
        """Divide Dataset em partições disjuntas de treino e validação."""
        n = self.n_samples
        if n < 2:
            raise ValidationError("São necessárias pelo menos 2 amostras para particionar treino/validação.")
        if train_slice is None and val_slice is None:
            if not (0.0 < train_fraction < 1.0):
                raise ValidationError("train_fraction deve estar estritamente em (0, 1).")
            split_idx = max(1, min(n - 1, int(round(n * train_fraction))))
            train_idx = np.arange(0, split_idx)
            val_idx = np.arange(split_idx, n)
        elif train_slice is not None and val_slice is not None:
            all_idx = np.arange(n)
            train_idx = all_idx[train_slice]
            val_idx = all_idx[val_slice]
            if train_idx.size == 0 or val_idx.size == 0:
                raise ValidationError("Partições de treino e validação devem ser não vazias.")
            if set(train_idx.tolist()) & set(val_idx.tolist()):
                raise HypothesisViolatedError(
                    "Contaminação detectada: treino e validação possuem amostras sobrepostas."
                )
        else:
            raise ValidationError("Forneça ambos train_slice e val_slice ou nenhum.")

        prov_tr = copy.deepcopy(self._provenance)
        prov_tr["partition"] = {"role": "train", "parent_id": self._id, "parent_revision": self._revision}
        prov_va = copy.deepcopy(self._provenance)
        prov_va["partition"] = {"role": "validation", "parent_id": self._id, "parent_revision": self._revision}

        ds_train = Dataset(
            t=self._t[train_idx],
            u=self._u[train_idx],
            y=self._y[train_idx],
            dt=self._dt,
            id=f"{self._id}-train",
            revision=self._revision,
            input_names=self._input_names,
            output_names=self._output_names,
            units=self._units,
            provenance=prov_tr,
        )
        ds_val = Dataset(
            t=self._t[val_idx],
            u=self._u[val_idx],
            y=self._y[val_idx],
            dt=self._dt,
            id=f"{self._id}-val",
            revision=self._revision,
            input_names=self._input_names,
            output_names=self._output_names,
            units=self._units,
            provenance=prov_va,
        )
        return ds_train, ds_val

    def with_revision(self, revision: int | None = None, **updates: Any) -> Dataset:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        kwargs = dict(
            t=updates.pop("t", self._t),
            u=updates.pop("u", self._u),
            y=updates.pop("y", self._y),
            dt=updates.pop("dt", self._dt),
            require_uniform=updates.pop("require_uniform", False),
            sampling_rtol=updates.pop("sampling_rtol", self._sampling_diagnostics["sampling_rtol"]),
            id=updates.pop("id", self._id),
            revision=new_rev,
            input_names=updates.pop("input_names", self._input_names),
            output_names=updates.pop("output_names", self._output_names),
            units=updates.pop("units", self._units),
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em Dataset.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return Dataset(**kwargs)

    def evolve(self, **updates: Any) -> Dataset:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "dt": self._dt,
            "input_names": list(self._input_names),
            "output_names": list(self._output_names),
            "t": array_to_tensor(self._t, dtype="float64", order="C"),
            "u": array_to_tensor(self._u, dtype="float64", order="C"),
            "y": array_to_tensor(self._y, dtype="float64", order="C"),
            "sampling_diagnostics": copy.deepcopy(self._sampling_diagnostics),
            "units": copy.deepcopy(self._units),
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Dataset:
        if not isinstance(data, Mapping):
            raise ValidationError("Dataset deve ser um objeto JSON.")
        if data.get("kind") != "Dataset":
            raise UnsupportedModelError(f"kind esperado 'Dataset', recebido {data.get('kind')!r}.")
        for req in ("schema_version", "id", "revision", "t", "u", "y", "units", "provenance"):
            if req not in data:
                raise ValidationError(f"Campo obrigatório ausente em Dataset: {req!r}")
        validate_schema_version(data["schema_version"])
        return cls(
            t=tensor_to_array(data["t"], expected_ndim=1, dtype="float64", strict_dtype=True),
            u=tensor_to_array(data["u"], expected_ndim=2, dtype="float64", strict_dtype=True),
            y=tensor_to_array(data["y"], expected_ndim=2, dtype="float64", strict_dtype=True),
            dt=data.get("dt"),
            id=data["id"],
            revision=data["revision"],
            input_names=data.get("input_names"),
            output_names=data.get("output_names"),
            units=data["units"],
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> Dataset:
        return cls.from_dict(strict_json_loads(raw))


class IdentifiedModel(_ImmutableModelBase):
    """Modelo identificado com partição treino/validação, métricas e diagnósticos de ruído/excitação."""

    kind: str = "IdentifiedModel"

    def __init__(
        self,
        model: StateSpace | TransferFunction | TSStateSpace | Mapping[str, Any],
        *,
        algorithm: str,
        dataset_ref: Mapping[str, Any] | None = None,
        partitions: Mapping[str, Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        noise_hypothesis: Mapping[str, Any] | None = None,
        excitation_diagnostics: Mapping[str, Any] | None = None,
        covariance: Any = None,
        residual_diagnostics: Mapping[str, Any] | None = None,
        id: str | None = None,
        revision: int = 0,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
    ) -> None:
        if isinstance(model, (StateSpace, TransferFunction, TSStateSpace)):
            resolved_model = model
        elif isinstance(model, Mapping):
            resolved_model = ensure_json_finite(dict(model), path="$.model")
        else:
            raise UnsupportedModelError(
                f"IdentifiedModel.model inválido: {type(model).__name__}."
            )

        validate_non_empty_str(algorithm, field_name="algorithm")

        if dataset_ref is not None:
            if not isinstance(dataset_ref, Mapping) or "id" not in dataset_ref:
                raise ValidationError("IdentifiedModel.dataset_ref deve conter ao menos 'id'.")
            clean_ds_ref = ensure_json_finite(dict(dataset_ref), path="$.dataset_ref")
        else:
            clean_ds_ref = None

        clean_partitions = ensure_json_finite(dict(partitions), path="$.partitions") if partitions is not None else {}
        if "train_indices" in clean_partitions and "validation_indices" in clean_partitions:
            tr_set = set(clean_partitions["train_indices"])
            va_set = set(clean_partitions["validation_indices"])
            if tr_set & va_set:
                raise HypothesisViolatedError(
                    "Contaminação de partições em IdentifiedModel: train_indices e validation_indices se sobrepõem."
                )

        clean_metrics = ensure_json_finite(dict(metrics), path="$.metrics") if metrics is not None else {}
        clean_noise = (
            ensure_json_finite(dict(noise_hypothesis), path="$.noise_hypothesis")
            if noise_hypothesis is not None
            else {}
        )
        clean_excit = (
            ensure_json_finite(dict(excitation_diagnostics), path="$.excitation_diagnostics")
            if excitation_diagnostics is not None
            else {}
        )
        clean_resid = (
            ensure_json_finite(dict(residual_diagnostics), path="$.residual_diagnostics")
            if residual_diagnostics is not None
            else {}
        )

        if covariance is not None:
            cov_arr = ensure_finite_float64(covariance, ndim=2, name="covariance")
            if cov_arr.shape[0] != cov_arr.shape[1]:
                raise DimensionMismatchError("covariance deve ser matriz quadrada.")
            cov_arr.setflags(write=False)
        else:
            cov_arr = None

        self._model = resolved_model
        self._algorithm = algorithm
        self._dataset_ref = clean_ds_ref
        self._partitions = clean_partitions
        self._metrics = clean_metrics
        self._noise_hypothesis = clean_noise
        self._excitation_diagnostics = clean_excit
        self._covariance = cov_arr
        self._residual_diagnostics = clean_resid
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._provenance = _normalize_provenance_mapping(provenance, algorithm)
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")
        self._created_at = created_at

        if id is None:
            model_dict = self._model.to_dict() if hasattr(self._model, "to_dict") else self._model
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "algorithm": self._algorithm,
                    "model": model_dict,
                    "metrics": self._metrics,
                }
            )
            self._id = f"idmod-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    @property
    def model(self) -> StateSpace | TransferFunction | TSStateSpace | dict[str, Any]:
        return copy.deepcopy(self._model) if isinstance(self._model, dict) else self._model

    @property
    def algorithm(self) -> str:
        return self._algorithm

    @property
    def dataset_ref(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._dataset_ref)

    @property
    def partitions(self) -> dict[str, Any]:
        return copy.deepcopy(self._partitions)

    @property
    def metrics(self) -> dict[str, Any]:
        return copy.deepcopy(self._metrics)

    @property
    def noise_hypothesis(self) -> dict[str, Any]:
        return copy.deepcopy(self._noise_hypothesis)

    @property
    def excitation_diagnostics(self) -> dict[str, Any]:
        return copy.deepcopy(self._excitation_diagnostics)

    @property
    def covariance(self) -> np.ndarray | None:
        return self._covariance

    @property
    def residual_diagnostics(self) -> dict[str, Any]:
        return copy.deepcopy(self._residual_diagnostics)

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
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    def with_revision(self, revision: int | None = None, **updates: Any) -> IdentifiedModel:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        kwargs = dict(
            model=updates.pop("model", self._model),
            algorithm=updates.pop("algorithm", self._algorithm),
            dataset_ref=updates.pop("dataset_ref", self._dataset_ref),
            partitions=updates.pop("partitions", self._partitions),
            metrics=updates.pop("metrics", self._metrics),
            noise_hypothesis=updates.pop("noise_hypothesis", self._noise_hypothesis),
            excitation_diagnostics=updates.pop("excitation_diagnostics", self._excitation_diagnostics),
            covariance=updates.pop("covariance", self._covariance),
            residual_diagnostics=updates.pop("residual_diagnostics", self._residual_diagnostics),
            id=updates.pop("id", self._id),
            revision=new_rev,
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em IdentifiedModel.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return IdentifiedModel(**kwargs)

    def evolve(self, **updates: Any) -> IdentifiedModel:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        model_payload = self._model.to_dict() if hasattr(self._model, "to_dict") else copy.deepcopy(self._model)
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "algorithm": self._algorithm,
            "model": model_payload,
            "dataset_ref": copy.deepcopy(self._dataset_ref),
            "partitions": copy.deepcopy(self._partitions),
            "metrics": copy.deepcopy(self._metrics),
            "noise_hypothesis": copy.deepcopy(self._noise_hypothesis),
            "excitation_diagnostics": copy.deepcopy(self._excitation_diagnostics),
            "residual_diagnostics": copy.deepcopy(self._residual_diagnostics),
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._covariance is not None:
            payload["covariance"] = array_to_tensor(self._covariance, dtype="float64", order="C")
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IdentifiedModel:
        if not isinstance(data, Mapping):
            raise ValidationError("IdentifiedModel deve ser um objeto JSON.")
        if data.get("kind") != "IdentifiedModel":
            raise UnsupportedModelError(f"kind esperado 'IdentifiedModel', recebido {data.get('kind')!r}.")
        for req in ("schema_version", "id", "revision", "algorithm", "model", "provenance"):
            if req not in data:
                raise ValidationError(f"Campo obrigatório ausente em IdentifiedModel: {req!r}")
        validate_schema_version(data["schema_version"])
        raw_model = data["model"]
        model_obj: Any = raw_model
        if isinstance(raw_model, Mapping):
            mkind = raw_model.get("kind")
            if mkind == "StateSpace":
                model_obj = StateSpace.from_dict(raw_model)
            elif mkind == "TransferFunction":
                model_obj = TransferFunction.from_dict(raw_model)
            elif mkind in _TS_KIND_SET:
                model_obj = TSStateSpace.from_dict(raw_model)

        cov = None
        if data.get("covariance") is not None:
            cov = tensor_to_array(data["covariance"], expected_ndim=2, dtype="float64", strict_dtype=True)

        return cls(
            model=model_obj,
            algorithm=data["algorithm"],
            dataset_ref=data.get("dataset_ref"),
            partitions=data.get("partitions"),
            metrics=data.get("metrics"),
            noise_hypothesis=data.get("noise_hypothesis"),
            excitation_diagnostics=data.get("excitation_diagnostics"),
            covariance=cov,
            residual_diagnostics=data.get("residual_diagnostics"),
            id=data["id"],
            revision=data["revision"],
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> IdentifiedModel:
        return cls.from_dict(strict_json_loads(raw))


# ---------------------------------------------------------------------------
# 4. TSStateSpace (ts_measured, polytopic_uncertain, ts_partially_observed)
# ---------------------------------------------------------------------------


class TSStateSpace(_ImmutableModelBase):
    """Modelo Takagi-Sugeno ou politópico incerto com distinção semântica obrigatória (ADR-006)."""

    def __init__(
        self,
        vertices: Sequence[Mapping[str, Any]],
        *,
        kind: str = "ts_measured",
        dt: float | None = None,
        membership_spec: Mapping[str, Any],
        premise_availability: Mapping[str, Any],
        domain: Mapping[str, Any],
        id: str | None = None,
        revision: int = 0,
        state_names: Sequence[str] | None = None,
        input_names: Sequence[str] | None = None,
        output_names: Sequence[str] | None = None,
        units: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
    ) -> None:
        if kind not in _TS_KIND_SET:
            raise UnsupportedModelError(
                message=f"TSStateSpace.kind inválido: {kind!r}. Esperado um de {TS_MODEL_KINDS}.",
                parameters={"kind": kind},
            )

        if not isinstance(vertices, Sequence) or isinstance(vertices, (str, bytes)) or len(vertices) < 1:
            raise ValidationError("TSStateSpace.vertices deve ser lista não vazia de vértices.")

        parsed_vertices: list[dict[str, Any]] = []
        seen_vertex_ids: set[str] = set()
        n: int | None = None
        m: int | None = None
        p: int | None = None

        for idx, v in enumerate(vertices):
            if not isinstance(v, Mapping):
                raise ValidationError(f"vertices[{idx}] deve ser Mapping com vertex_id, A, B, C, D.")
            for req_k in ("vertex_id", "A", "B", "C", "D"):
                if req_k not in v:
                    raise ValidationError(f"Campo obrigatório ausente em vertices[{idx}]: {req_k!r}")
            vid = validate_non_empty_str(v["vertex_id"], field_name=f"vertices[{idx}].vertex_id")
            if vid in seen_vertex_ids:
                raise ValidationError(f"vertex_id duplicado em TSStateSpace: {vid!r}")
            seen_vertex_ids.add(vid)

            orders = {"A": "C", "B": "C", "C": "C", "D": "C"}
            mats: dict[str, np.ndarray] = {}
            for mkey in ("A", "B", "C", "D"):
                raw_m = v[mkey]
                if isinstance(raw_m, Mapping) and "shape" in raw_m and "data" in raw_m:
                    orders[mkey] = str(raw_m.get("order", "C"))
                    mats[mkey] = tensor_to_array(raw_m, expected_ndim=2, dtype="float64", strict_dtype=True)
                else:
                    mats[mkey] = ensure_finite_float64(raw_m, ndim=2, name=f"vertices[{idx}].{mkey}")

            A_v, B_v, C_v, D_v = mats["A"], mats["B"], mats["C"], mats["D"]
            if A_v.shape[0] != A_v.shape[1]:
                raise DimensionMismatchError(f"vertices[{idx}].A deve ser quadrada, recebido {A_v.shape}.")
            nv, mv, pv = A_v.shape[0], B_v.shape[1], C_v.shape[0]
            if B_v.shape != (nv, mv) or C_v.shape != (pv, nv) or D_v.shape != (pv, mv):
                raise DimensionMismatchError(
                    f"Dimensões incompatíveis dentro de vertices[{idx}]: A={A_v.shape}, B={B_v.shape}, C={C_v.shape}, D={D_v.shape}."
                )

            if n is None:
                n, m, p = nv, mv, pv
            elif (nv, mv, pv) != (n, m, p):
                raise DimensionMismatchError(
                    message=(
                        f"Todos os vértices de TSStateSpace devem ter dimensões idênticas; "
                        f"vértice 0 tem (n={n}, m={m}, p={p}), vértice {idx} tem (n={nv}, m={mv}, p={pv})."
                    ),
                    parameters={"expected": [n, m, p], "actual": [nv, mv, pv]},
                )

            for arr in (A_v, B_v, C_v, D_v):
                arr.setflags(write=False)

            parsed_vertices.append(
                {
                    "vertex_id": vid,
                    "A": A_v,
                    "B": B_v,
                    "C": C_v,
                    "D": D_v,
                    "_orders": orders,
                }
            )

        assert n is not None and m is not None and p is not None

        # Valida membership_spec
        if not isinstance(membership_spec, Mapping):
            raise ValidationError("membership_spec deve ser Mapping.")
        for req in ("version", "premise_variables", "sum_to_one_domain"):
            if req not in membership_spec:
                raise ValidationError(f"Campo obrigatório ausente em membership_spec: {req!r}")
        clean_ms = ensure_json_finite(dict(membership_spec), path="$.membership_spec")
        validate_non_empty_str(clean_ms["version"], field_name="membership_spec.version")
        if not isinstance(clean_ms["premise_variables"], list) or not all(
            isinstance(x, str) and len(x) > 0 for x in clean_ms["premise_variables"]
        ):
            raise ValidationError("membership_spec.premise_variables deve ser lista de strings não vazias.")
        if not isinstance(clean_ms["sum_to_one_domain"], bool):
            raise ValidationError("membership_spec.sum_to_one_domain deve ser booleano.")
        if "functions" in clean_ms and not isinstance(clean_ms["functions"], list):
            raise ValidationError("membership_spec.functions deve ser uma lista de dicts.")

        # Valida premise_availability
        if not isinstance(premise_availability, Mapping):
            raise ValidationError("premise_availability deve ser Mapping.")
        pa_allowed = {"mode", "measured_premises", "unmeasured_premises", "estimator_required_for_pdc"}
        pa_extra = set(premise_availability.keys()) - pa_allowed
        if pa_extra:
            raise ValidationError(f"Campos extras proibidos em premise_availability: {sorted(pa_extra)}")
        for req in ("mode", "measured_premises", "unmeasured_premises"):
            if req not in premise_availability:
                raise ValidationError(f"Campo obrigatório ausente em premise_availability: {req!r}")
        clean_pa = ensure_json_finite(dict(premise_availability), path="$.premise_availability")
        mode = clean_pa["mode"]
        if mode not in _PREMISE_MODE_SET:
            raise ValidationError(f"premise_availability.mode inválido: {mode!r}")
        measured = clean_pa["measured_premises"]
        unmeasured = clean_pa["unmeasured_premises"]
        if not isinstance(measured, list) or not all(isinstance(x, str) for x in measured):
            raise ValidationError("premise_availability.measured_premises deve ser lista de strings.")
        if not isinstance(unmeasured, list) or not all(isinstance(x, str) for x in unmeasured):
            raise ValidationError("premise_availability.unmeasured_premises deve ser lista de strings.")
        if set(measured) & set(unmeasured):
            raise ValidationError("Premissas não podem aparecer simultaneamente como medidas e não medidas.")
        if "estimator_required_for_pdc" in clean_pa and not isinstance(clean_pa["estimator_required_for_pdc"], bool):
            raise ValidationError("premise_availability.estimator_required_for_pdc deve ser booleano.")

        # Coerência semântica obrigatória (ADR-006 / Seção 4.3)
        req_premises = set(clean_ms["premise_variables"])
        est_req = clean_pa.get("estimator_required_for_pdc")
        if kind == "ts_measured":
            if mode != "all_measured":
                raise HypothesisViolatedError(
                    f"Modelo 'ts_measured' exige premise_availability.mode='all_measured', recebido {mode!r}."
                )
            if unmeasured:
                raise HypothesisViolatedError(
                    "Modelo 'ts_measured' não pode possuir premissas em unmeasured_premises."
                )
            if not req_premises.issubset(set(measured)):
                raise HypothesisViolatedError(
                    "Modelo 'ts_measured' requer todas as premise_variables listadas em measured_premises."
                )
            if est_req is True:
                raise HypothesisViolatedError(
                    "Modelo 'ts_measured' com todas as premissas medidas não deve marcar estimator_required_for_pdc=True."
                )
        elif kind == "polytopic_uncertain":
            if mode != "unknown_uncertain":
                raise HypothesisViolatedError(
                    f"Modelo 'polytopic_uncertain' exige mode='unknown_uncertain', recebido {mode!r}."
                )
            if measured:
                raise HypothesisViolatedError(
                    "Modelo 'polytopic_uncertain' não pode declarar premissas convexas desconhecidas como medidas."
                )
            if est_req is False:
                raise HypothesisViolatedError(
                    "Modelo 'polytopic_uncertain' não pode declarar estimator_required_for_pdc=False."
                )
        elif kind == "ts_partially_observed":
            if mode != "partially_observed":
                raise HypothesisViolatedError(
                    f"Modelo 'ts_partially_observed' exige mode='partially_observed', recebido {mode!r}."
                )
            if not unmeasured:
                raise HypothesisViolatedError(
                    "Modelo 'ts_partially_observed' deve declarar ao menos uma premissa em unmeasured_premises."
                )
            if est_req is False:
                raise HypothesisViolatedError(
                    "Modelo 'ts_partially_observed' requer estimador para premissas não medidas."
                )

        # Valida domain.bounds
        if not isinstance(domain, Mapping) or "bounds" not in domain:
            raise ValidationError("TSStateSpace.domain deve conter 'bounds'.")
        clean_dom = ensure_json_finite(dict(domain), path="$.domain")
        bounds = clean_dom["bounds"]
        if not isinstance(bounds, Mapping):
            raise ValidationError("TSStateSpace.domain.bounds deve ser Mapping.")
        for bname, bpair in bounds.items():
            if not isinstance(bpair, list) or len(bpair) != 2:
                raise ValidationError(f"domain.bounds[{bname!r}] deve ter formato [min, max].")
            lo, hi = bpair
            if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
                raise ValidationError(f"Limites de domain.bounds[{bname!r}] devem ser numéricos.")
            if float(lo) > float(hi):
                raise ValidationError(f"Limite inferior > superior em domain.bounds[{bname!r}]: [{lo}, {hi}].")

        self._kind = kind
        self._dt = validate_sample_time(dt)
        self._vertices = tuple(parsed_vertices)
        self._membership_spec = clean_ms
        self._premise_availability = clean_pa
        self._domain = clean_dom
        self._n_states = n
        self._n_inputs = m
        self._n_outputs = p
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._state_names = validate_name_list(state_names, n, prefix="x", field_name="state_names")
        self._input_names = validate_name_list(input_names, m, prefix="u", field_name="input_names")
        self._output_names = validate_name_list(output_names, p, prefix="y", field_name="output_names")
        self._units = validate_units_dict(units, n_states=n, n_inputs=m, n_outputs=p, require_io=False)
        self._provenance = _normalize_provenance_mapping(provenance, "control_lab")
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")
        self._created_at = created_at

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self._kind,
                    "dt": self._dt,
                    "n_vertices": len(self._vertices),
                    "membership_spec": self._membership_spec,
                    "premise_availability": self._premise_availability,
                    "domain": self._domain,
                }
            )
            self._id = f"ts-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    @property
    def kind(self) -> str:
        return self._kind

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
    def vertices(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "vertex_id": v["vertex_id"],
                "A": v["A"],
                "B": v["B"],
                "C": v["C"],
                "D": v["D"],
            }
            for v in self._vertices
        )

    @property
    def n_vertices(self) -> int:
        return len(self._vertices)

    @property
    def n_states(self) -> int:
        return self._n_states

    @property
    def n_inputs(self) -> int:
        return self._n_inputs

    @property
    def n_outputs(self) -> int:
        return self._n_outputs

    @property
    def membership_spec(self) -> dict[str, Any]:
        return copy.deepcopy(self._membership_spec)

    @property
    def premise_availability(self) -> dict[str, Any]:
        return copy.deepcopy(self._premise_availability)

    @property
    def domain(self) -> dict[str, Any]:
        return copy.deepcopy(self._domain)

    @property
    def state_names(self) -> tuple[str, ...]:
        return self._state_names

    @property
    def input_names(self) -> tuple[str, ...]:
        return self._input_names

    @property
    def output_names(self) -> tuple[str, ...]:
        return self._output_names

    @property
    def units(self) -> dict[str, Any]:
        return copy.deepcopy(self._units)

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    def with_revision(self, revision: int | None = None, **updates: Any) -> TSStateSpace:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        kwargs = dict(
            vertices=updates.pop("vertices", self.vertices),
            kind=updates.pop("kind", self._kind),
            dt=updates.pop("dt", self._dt),
            membership_spec=updates.pop("membership_spec", self._membership_spec),
            premise_availability=updates.pop("premise_availability", self._premise_availability),
            domain=updates.pop("domain", self._domain),
            id=updates.pop("id", self._id),
            revision=new_rev,
            state_names=updates.pop("state_names", self._state_names),
            input_names=updates.pop("input_names", self._input_names),
            output_names=updates.pop("output_names", self._output_names),
            units=updates.pop("units", self._units),
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em TSStateSpace.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return TSStateSpace(**kwargs)

    def evolve(self, **updates: Any) -> TSStateSpace:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self._kind,
            "dt": self._dt,
            "membership_spec": copy.deepcopy(self._membership_spec),
            "premise_availability": copy.deepcopy(self._premise_availability),
            "domain": copy.deepcopy(self._domain),
            "vertices": [
                {
                    "vertex_id": v["vertex_id"],
                    "A": array_to_tensor(v["A"], dtype="float64", order=v["_orders"]["A"]),
                    "B": array_to_tensor(v["B"], dtype="float64", order=v["_orders"]["B"]),
                    "C": array_to_tensor(v["C"], dtype="float64", order=v["_orders"]["C"]),
                    "D": array_to_tensor(v["D"], dtype="float64", order=v["_orders"]["D"]),
                }
                for v in self._vertices
            ],
            "state_names": list(self._state_names),
            "input_names": list(self._input_names),
            "output_names": list(self._output_names),
            "units": copy.deepcopy(self._units),
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TSStateSpace:
        if not isinstance(data, Mapping):
            raise ValidationError("TSStateSpace deve ser um objeto JSON.")
        required = {
            "schema_version",
            "id",
            "revision",
            "kind",
            "dt",
            "membership_spec",
            "premise_availability",
            "domain",
            "vertices",
            "state_names",
            "input_names",
            "output_names",
            "units",
            "provenance",
        }
        optional = {"created_at"}
        keys = set(data.keys())
        extra = keys - (required | optional)
        if extra:
            raise ValidationError(f"Campos extras proibidos em TSStateSpace: {sorted(extra)}")
        missing = required - keys
        if missing:
            raise ValidationError(f"Campos obrigatórios ausentes em TSStateSpace: {sorted(missing)}")

        validate_schema_version(data["schema_version"])
        for idx, v in enumerate(data["vertices"]):
            if not isinstance(v, Mapping) or set(v.keys()) != {"vertex_id", "A", "B", "C", "D"}:
                raise ValidationError(f"vertices[{idx}] deve conter exatamente vertex_id, A, B, C, D.")

        return cls(
            vertices=data["vertices"],
            kind=data["kind"],
            dt=data["dt"],
            membership_spec=data["membership_spec"],
            premise_availability=data["premise_availability"],
            domain=data["domain"],
            id=data["id"],
            revision=data["revision"],
            state_names=data["state_names"],
            input_names=data["input_names"],
            output_names=data["output_names"],
            units=data["units"],
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> TSStateSpace:
        return cls.from_dict(strict_json_loads(raw))


# ---------------------------------------------------------------------------
# 5. FuzzySystem (aproximador estático por padrão, perfil IEEE 1855-2016)
# ---------------------------------------------------------------------------


class FuzzySystem(_ImmutableModelBase):
    """Sistema Fuzzy Mamdani/TS com distinção explícita entre aproximador estático e modelo dinâmico."""

    kind: str = "FuzzySystem"

    def __init__(
        self,
        *,
        inference_type: str = "mamdani",
        input_variables: Sequence[Mapping[str, Any]],
        output_variables: Sequence[Mapping[str, Any]],
        rules: Sequence[Mapping[str, Any]],
        operators: Mapping[str, str] | None = None,
        fml_profile: str = "IEEE-1855-2016",
        is_dynamic_model: bool = False,
        dynamic_semantics: Mapping[str, Any] | None = None,
        id: str | None = None,
        revision: int = 0,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
    ) -> None:
        if inference_type not in ("mamdani", "ts"):
            raise ValidationError(
                f"inference_type inválido: {inference_type!r}. Esperado 'mamdani' ou 'ts'."
            )
        if not isinstance(is_dynamic_model, bool):
            raise ValidationError("is_dynamic_model deve ser booleano.")
        if is_dynamic_model and (dynamic_semantics is None or not isinstance(dynamic_semantics, Mapping)):
            raise HypothesisViolatedError(
                message="FuzzySystem com is_dynamic_model=True exige dynamic_semantics explícita (estados e dinâmica identificados).",
                next_step="Mantenha is_dynamic_model=False para aproximadores estáticos ou declare dynamic_semantics.",
            )

        if not isinstance(input_variables, Sequence) or isinstance(input_variables, (str, bytes)) or len(input_variables) < 1:
            raise ValidationError("FuzzySystem.input_variables deve ser lista não vazia.")
        if not isinstance(output_variables, Sequence) or isinstance(output_variables, (str, bytes)) or len(output_variables) < 1:
            raise ValidationError("FuzzySystem.output_variables deve ser lista não vazia.")
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
            raise ValidationError("FuzzySystem.rules deve ser uma lista.")

        clean_inputs = self._validate_variables(input_variables, role="input", inference_type=inference_type)
        clean_outputs = self._validate_variables(output_variables, role="output", inference_type=inference_type)

        in_terms = {v["name"]: {t["name"] for t in v["terms"]} for v in clean_inputs}
        out_terms = {v["name"]: {t["name"] for t in v["terms"]} for v in clean_outputs}

        clean_rules: list[dict[str, Any]] = []
        for idx, r in enumerate(rules):
            if not isinstance(r, Mapping):
                raise ValidationError(f"FuzzySystem.rules[{idx}] deve ser Mapping.")
            cr = ensure_json_finite(dict(r), path=f"$.rules[{idx}]")
            ants = cr.get("antecedents")
            cons = cr.get("consequents")
            if not isinstance(ants, Mapping) or not isinstance(cons, Mapping):
                raise ValidationError(f"rules[{idx}] requer mapeamentos 'antecedents' e 'consequents'.")
            for vname, tname in ants.items():
                if vname not in in_terms or tname not in in_terms[vname]:
                    raise ValidationError(f"rules[{idx}] referencia antecedente desconhecido {vname}={tname}.")
            for vname, tname in cons.items():
                if vname not in out_terms or tname not in out_terms[vname]:
                    raise ValidationError(f"rules[{idx}] referencia consequente desconhecido {vname}={tname}.")
            weight = cr.get("weight", 1.0)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not (0.0 < float(weight) <= 1.0):
                raise ValidationError(f"rules[{idx}].weight deve estar em (0, 1].")
            cr["weight"] = float(weight)
            clean_rules.append(cr)

        default_ops = (
            {"and": "min", "or": "max", "implication": "min", "aggregation": "max", "defuzzification": "centroid"}
            if inference_type == "mamdani"
            else {"and": "prod", "or": "probor", "defuzzification": "wtaver"}
        )
        clean_ops = dict(default_ops)
        if operators is not None:
            if not isinstance(operators, Mapping):
                raise ValidationError("operators deve ser Mapping str -> str.")
            for k, v in operators.items():
                validate_non_empty_str(k, field_name="operator key")
                validate_non_empty_str(v, field_name=f"operators[{k}]")
                clean_ops[k] = v

        validate_non_empty_str(fml_profile, field_name="fml_profile")

        self._inference_type = inference_type
        self._input_variables = tuple(clean_inputs)
        self._output_variables = tuple(clean_outputs)
        self._rules = tuple(clean_rules)
        self._operators = clean_ops
        self._fml_profile = fml_profile
        self._is_dynamic_model = is_dynamic_model
        self._dynamic_semantics = (
            ensure_json_finite(dict(dynamic_semantics), path="$.dynamic_semantics")
            if dynamic_semantics is not None
            else None
        )
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._provenance = _normalize_provenance_mapping(provenance, "control_lab")
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")
        self._created_at = created_at

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "inference_type": self._inference_type,
                    "inputs": list(self._input_variables),
                    "outputs": list(self._output_variables),
                    "rules": list(self._rules),
                    "is_dynamic_model": self._is_dynamic_model,
                }
            )
            self._id = f"fuzzy-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

    @staticmethod
    def _validate_variables(
        variables: Sequence[Mapping[str, Any]],
        *,
        role: str,
        inference_type: str,
    ) -> list[dict[str, Any]]:
        seen_names: set[str] = set()
        out: list[dict[str, Any]] = []
        for idx, var in enumerate(variables):
            if not isinstance(var, Mapping):
                raise ValidationError(f"{role}_variables[{idx}] deve ser Mapping.")
            cv = ensure_json_finite(dict(var), path=f"$.{role}_variables[{idx}]")
            name = validate_non_empty_str(cv.get("name"), field_name=f"{role}_variables[{idx}].name")
            if name in seen_names:
                raise ValidationError(f"Variável duplicada em {role}_variables: {name!r}")
            seen_names.add(name)

            univ = cv.get("universe")
            if not isinstance(univ, list) or len(univ) != 2:
                raise ValidationError(f"{role}_variables[{idx}].universe deve ser [min, max].")
            lo, hi = univ
            if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
                raise ValidationError(f"Limites do universo de {name} devem ser numéricos.")
            if float(lo) >= float(hi):
                raise ValidationError(f"Universo de {name} deve satisfazer min < max.")

            terms = cv.get("terms")
            if not isinstance(terms, list) or len(terms) < 1:
                raise ValidationError(f"{role}_variables[{idx}].terms deve ser lista não vazia.")
            seen_terms: set[str] = set()
            for t_idx, term in enumerate(terms):
                if not isinstance(term, Mapping):
                    raise ValidationError(f"{name}.terms[{t_idx}] deve ser Mapping.")
                tname = validate_non_empty_str(term.get("name"), field_name=f"{name}.terms[{t_idx}].name")
                if tname in seen_terms:
                    raise ValidationError(f"Termo duplicado {tname!r} na variável {name!r}.")
                seen_terms.add(tname)
                if role == "output" and inference_type == "ts":
                    if "type" not in term and "params" not in term and "coefficients" not in term:
                        raise ValidationError(f"Termo TS de saída {name}.{tname} exige 'type'/'params' ou 'coefficients'.")
                else:
                    if "mf" not in term and "type" not in term:
                        raise ValidationError(f"Termo {name}.{tname} exige 'mf' ou 'type'.")
            out.append(cv)
        return out

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
    def inference_type(self) -> str:
        return self._inference_type

    @property
    def input_variables(self) -> tuple[dict[str, Any], ...]:
        return copy.deepcopy(self._input_variables)

    @property
    def output_variables(self) -> tuple[dict[str, Any], ...]:
        return copy.deepcopy(self._output_variables)

    @property
    def rules(self) -> tuple[dict[str, Any], ...]:
        return copy.deepcopy(self._rules)

    @property
    def operators(self) -> dict[str, str]:
        return dict(self._operators)

    @property
    def fml_profile(self) -> str:
        return self._fml_profile

    @property
    def is_dynamic_model(self) -> bool:
        return self._is_dynamic_model

    @property
    def dynamic_semantics(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._dynamic_semantics)

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    def with_revision(self, revision: int | None = None, **updates: Any) -> FuzzySystem:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        kwargs = dict(
            inference_type=updates.pop("inference_type", self._inference_type),
            input_variables=updates.pop("input_variables", self._input_variables),
            output_variables=updates.pop("output_variables", self._output_variables),
            rules=updates.pop("rules", self._rules),
            operators=updates.pop("operators", self._operators),
            fml_profile=updates.pop("fml_profile", self._fml_profile),
            is_dynamic_model=updates.pop("is_dynamic_model", self._is_dynamic_model),
            dynamic_semantics=updates.pop("dynamic_semantics", self._dynamic_semantics),
            id=updates.pop("id", self._id),
            revision=new_rev,
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em FuzzySystem.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return FuzzySystem(**kwargs)

    def evolve(self, **updates: Any) -> FuzzySystem:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "inference_type": self._inference_type,
            "fml_profile": self._fml_profile,
            "is_dynamic_model": self._is_dynamic_model,
            "input_variables": copy.deepcopy(list(self._input_variables)),
            "output_variables": copy.deepcopy(list(self._output_variables)),
            "rules": copy.deepcopy(list(self._rules)),
            "operators": dict(self._operators),
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._dynamic_semantics is not None:
            payload["dynamic_semantics"] = copy.deepcopy(self._dynamic_semantics)
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FuzzySystem:
        if not isinstance(data, Mapping):
            raise ValidationError("FuzzySystem deve ser um objeto JSON.")
        if data.get("kind") != "FuzzySystem":
            raise UnsupportedModelError(f"kind esperado 'FuzzySystem', recebido {data.get('kind')!r}.")
        for req in ("schema_version", "id", "revision", "inference_type", "input_variables", "output_variables", "rules", "provenance"):
            if req not in data:
                raise ValidationError(f"Campo obrigatório ausente em FuzzySystem: {req!r}")
        validate_schema_version(data["schema_version"])
        return cls(
            inference_type=data["inference_type"],
            input_variables=data["input_variables"],
            output_variables=data["output_variables"],
            rules=data["rules"],
            operators=data.get("operators"),
            fml_profile=data.get("fml_profile", "IEEE-1855-2016"),
            is_dynamic_model=data.get("is_dynamic_model", False),
            dynamic_semantics=data.get("dynamic_semantics"),
            id=data["id"],
            revision=data["revision"],
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> FuzzySystem:
        return cls.from_dict(strict_json_loads(raw))


# ---------------------------------------------------------------------------
# 6. Experiment
# ---------------------------------------------------------------------------


class Experiment(_ImmutableModelBase):
    """Registro auditável e imutável de experimento científico."""

    kind: str = "Experiment"

    def __init__(
        self,
        *,
        method: str,
        model_ref: Mapping[str, Any] | None = None,
        controller_ref: Mapping[str, Any] | None = None,
        parameters: Mapping[str, Any] | None = None,
        tolerances: Mapping[str, Any] | None = None,
        results: Result | Mapping[str, Any] | None = None,
        data_source: str | Mapping[str, Any] | None = None,
        id: str | None = None,
        revision: int = 0,
        provenance: Mapping[str, Any] | Provenance | None = None,
        schema_version: str = "1.0.0",
        created_at: str | None = None,
    ) -> None:
        validate_non_empty_str(method, field_name="method")
        if model_ref is not None:
            if not isinstance(model_ref, Mapping) or "id" not in model_ref or "revision" not in model_ref:
                raise ValidationError("Experiment.model_ref deve conter 'id' e 'revision'.")
            clean_model_ref = ensure_json_finite(dict(model_ref), path="$.model_ref")
        else:
            clean_model_ref = None

        if controller_ref is not None:
            if not isinstance(controller_ref, Mapping) or "id" not in controller_ref or "revision" not in controller_ref:
                raise ValidationError("Experiment.controller_ref deve conter 'id' e 'revision'.")
            clean_ctrl_ref = ensure_json_finite(dict(controller_ref), path="$.controller_ref")
        else:
            clean_ctrl_ref = None

        clean_params = ensure_json_finite(dict(parameters), path="$.parameters") if parameters is not None else {}
        clean_tols = ensure_json_finite(dict(tolerances), path="$.tolerances") if tolerances is not None else {}

        if results is None:
            resolved_results: Result | dict[str, Any] | None = None
        elif isinstance(results, Result):
            resolved_results = results
        elif isinstance(results, Mapping):
            resolved_results = ensure_json_finite(dict(results), path="$.results")
        else:
            raise ValidationError("Experiment.results deve ser Result, dict ou None.")

        if data_source is not None and not isinstance(data_source, (str, Mapping)):
            raise ValidationError("Experiment.data_source deve ser str, dict ou None.")
        clean_ds = (
            ensure_json_finite(dict(data_source), path="$.data_source")
            if isinstance(data_source, Mapping)
            else data_source
        )

        self._method = method
        self._model_ref = clean_model_ref
        self._controller_ref = clean_ctrl_ref
        self._parameters = clean_params
        self._tolerances = clean_tols
        self._results = resolved_results
        self._data_source = clean_ds
        self._schema_version = validate_schema_version(schema_version)
        self._revision = validate_revision(revision)
        self._provenance = _normalize_provenance_mapping(provenance, method)
        if created_at is not None:
            validate_non_empty_str(created_at, field_name="created_at")
        self._created_at = created_at

        if id is None:
            digest = compute_canonical_sha256(
                {
                    "kind": self.kind,
                    "method": self._method,
                    "model_ref": self._model_ref,
                    "controller_ref": self._controller_ref,
                    "parameters": self._parameters,
                }
            )
            self._id = f"exp-{digest[:12]}"
        else:
            self._id = validate_non_empty_str(id, field_name="id")

        self._lock()

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
    def method(self) -> str:
        return self._method

    @property
    def model_ref(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._model_ref)

    @property
    def controller_ref(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._controller_ref)

    @property
    def parameters(self) -> dict[str, Any]:
        return copy.deepcopy(self._parameters)

    @property
    def tolerances(self) -> dict[str, Any]:
        return copy.deepcopy(self._tolerances)

    @property
    def results(self) -> Result | dict[str, Any] | None:
        if isinstance(self._results, Result):
            return self._results
        return copy.deepcopy(self._results)

    @property
    def data_source(self) -> str | dict[str, Any] | None:
        return copy.deepcopy(self._data_source)

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    @property
    def created_at(self) -> str | None:
        return self._created_at

    def with_revision(self, revision: int | None = None, **updates: Any) -> Experiment:
        new_rev = (self._revision + 1) if revision is None else validate_revision(revision)
        kwargs = dict(
            method=updates.pop("method", self._method),
            model_ref=updates.pop("model_ref", self._model_ref),
            controller_ref=updates.pop("controller_ref", self._controller_ref),
            parameters=updates.pop("parameters", self._parameters),
            tolerances=updates.pop("tolerances", self._tolerances),
            results=updates.pop("results", self._results),
            data_source=updates.pop("data_source", self._data_source),
            id=updates.pop("id", self._id),
            revision=new_rev,
            provenance=updates.pop("provenance", self._provenance),
            schema_version=updates.pop("schema_version", self._schema_version),
            created_at=updates.pop("created_at", self._created_at),
        )
        if updates:
            raise ValidationError(
                message=f"Argumentos desconhecidos em Experiment.with_revision: {sorted(updates.keys())}",
                parameters={"unknown_fields": sorted(updates.keys())},
            )
        return Experiment(**kwargs)

    def evolve(self, **updates: Any) -> Experiment:
        rev = updates.pop("revision", None)
        return self.with_revision(rev, **updates)

    def to_dict(self) -> dict[str, Any]:
        res_dict = self._results.to_dict() if isinstance(self._results, Result) else copy.deepcopy(self._results)
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "id": self._id,
            "revision": self._revision,
            "kind": self.kind,
            "method": self._method,
            "model_ref": copy.deepcopy(self._model_ref),
            "controller_ref": copy.deepcopy(self._controller_ref),
            "parameters": copy.deepcopy(self._parameters),
            "tolerances": copy.deepcopy(self._tolerances),
            "results": res_dict,
            "data_source": copy.deepcopy(self._data_source),
            "provenance": copy.deepcopy(self._provenance),
        }
        if self._created_at is not None:
            payload["created_at"] = self._created_at
        return ensure_json_finite(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Experiment:
        if not isinstance(data, Mapping):
            raise ValidationError("Experiment deve ser um objeto JSON.")
        if data.get("kind") != "Experiment":
            raise UnsupportedModelError(f"kind esperado 'Experiment', recebido {data.get('kind')!r}.")
        for req in ("schema_version", "id", "revision", "method", "provenance"):
            if req not in data:
                raise ValidationError(f"Campo obrigatório ausente em Experiment: {req!r}")
        validate_schema_version(data["schema_version"])
        raw_res = data.get("results")
        parsed_res: Result | Mapping[str, Any] | None = raw_res
        if isinstance(raw_res, Mapping) and {"status", "data", "assumptions", "diagnostics", "provenance", "warnings", "error"}.issubset(raw_res.keys()):
            parsed_res = Result.from_dict(raw_res)

        return cls(
            method=data["method"],
            model_ref=data.get("model_ref"),
            controller_ref=data.get("controller_ref"),
            parameters=data.get("parameters"),
            tolerances=data.get("tolerances"),
            results=parsed_res,
            data_source=data.get("data_source"),
            id=data["id"],
            revision=data["revision"],
            provenance=data["provenance"],
            schema_version=data["schema_version"],
            created_at=data.get("created_at"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> Experiment:
        return cls.from_dict(strict_json_loads(raw))
