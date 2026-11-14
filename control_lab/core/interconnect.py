"""Interconexão, verificação de bem-postura algébrica e fechamento de malha (Seção 4.2, 4.3 e 13.3)."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    Provenance,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
    ensure_json_finite,
)

from .controllers import (
    Controller,
    DynamicController,
    PDCController,
    StateFeedbackController,
    _validate_feedback_sign,
)
from .models import StateSpace, TSStateSpace, _ImmutableModelBase
from .tensors import array_to_tensor, check_dt_compatible, ensure_finite_float64, readonly_copy, tensor_to_array

_ALLOWED_WIRING_KEYS = frozenset({"scheme", "reference_map", "premise_estimator", "feedback_sign", "port_map"})


class TSClosedLoop(_ImmutableModelBase):
    """Sistema em malha fechada (TSStateSpace + PDCController) preservando todos os termos duplos (i, j)."""

    kind: str = "TSClosedLoop"

    def __init__(
        self,
        ts_model: TSStateSpace,
        controller: PDCController,
        cross_terms: Sequence[Sequence[Mapping[str, np.ndarray]]],
        input_terms: Sequence[Mapping[str, np.ndarray]],
        *,
        feedback_sign: str,
        input_names: Sequence[str],
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        self._ts_model = ts_model
        self._controller = controller
        self._feedback_sign = _validate_feedback_sign(feedback_sign)
        self._input_names = tuple(input_names)
        self._provenance = ensure_json_finite(dict(provenance), path="$.provenance") if provenance is not None else {}

        frozen_cross: list[tuple[dict[str, np.ndarray], ...]] = []
        for row in cross_terms:
            frozen_row: list[dict[str, np.ndarray]] = []
            for cell in row:
                A_ij = ensure_finite_float64(cell["A"], ndim=2, name="Acl_ij")
                C_ij = ensure_finite_float64(cell["C"], ndim=2, name="Ccl_ij")
                A_ij.setflags(write=False)
                C_ij.setflags(write=False)
                frozen_row.append({"A": A_ij, "C": C_ij})
            frozen_cross.append(tuple(frozen_row))
        self._cross_terms = tuple(frozen_cross)

        frozen_in: list[dict[str, np.ndarray]] = []
        for item in input_terms:
            B_i = ensure_finite_float64(item["B"], ndim=2, name="Bcl_i")
            D_i = ensure_finite_float64(item["D"], ndim=2, name="Dcl_i")
            B_i.setflags(write=False)
            D_i.setflags(write=False)
            frozen_in.append({"B": B_i, "D": D_i})
        self._input_terms = tuple(frozen_in)
        self._lock()

    @property
    def ts_model(self) -> TSStateSpace:
        return self._ts_model

    @property
    def controller(self) -> PDCController:
        return self._controller

    @property
    def feedback_sign(self) -> str:
        return self._feedback_sign

    @property
    def dt(self) -> float | None:
        return self._ts_model.dt

    @property
    def n_vertices(self) -> int:
        return self._ts_model.n_vertices

    @property
    def n_states(self) -> int:
        return self._ts_model.n_states

    @property
    def n_inputs(self) -> int:
        return int(self._input_terms[0]["B"].shape[1])

    @property
    def n_outputs(self) -> int:
        return self._ts_model.n_outputs

    @property
    def cross_terms(self) -> tuple[tuple[dict[str, np.ndarray], ...], ...]:
        return tuple(
            tuple({"A": readonly_copy(cell["A"]), "C": readonly_copy(cell["C"])} for cell in row)
            for row in self._cross_terms
        )

    @property
    def input_terms(self) -> tuple[dict[str, np.ndarray], ...]:
        return tuple(
            {"B": readonly_copy(item["B"]), "D": readonly_copy(item["D"])}
            for item in self._input_terms
        )

    @property
    def input_names(self) -> tuple[str, ...]:
        return self._input_names

    @property
    def provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._provenance)

    def get_cross_matrix(self, i: int, j: int) -> np.ndarray:
        """Retorna A_i + sign * B_i @ K_j para o par de índices (i, j)."""
        return readonly_copy(self._cross_terms[i][j]["A"])

    def evaluate_at_weights(self, h: Sequence[float]) -> StateSpace:
        """Avalia o sistema instantâneo exato sum_i sum_j h_i h_j (A_i + sign*B_i K_j)."""
        h_arr = ensure_finite_float64(h, ndim=1, shape=(self.n_vertices,), name="h")
        if np.any(h_arr < -1e-12):
            raise HypothesisViolatedError("Pesos de pertinência h_i devem ser não negativos (h_i >= 0).")
        if not np.isclose(float(np.sum(h_arr)), 1.0, atol=1e-9, rtol=1e-9):
            raise HypothesisViolatedError(f"Pesos de pertinência devem somar 1 no domínio, soma={float(np.sum(h_arr))}.")

        r = self.n_vertices
        n = self.n_states
        m_ref = self.n_inputs
        p = self.n_outputs
        Acl = np.zeros((n, n), dtype=np.float64)
        Ccl = np.zeros((p, n), dtype=np.float64)
        Bcl = np.zeros((n, m_ref), dtype=np.float64)
        Dcl = np.zeros((p, m_ref), dtype=np.float64)

        for i in range(r):
            hi = float(h_arr[i])
            Bcl = Bcl + hi * self._input_terms[i]["B"]
            Dcl = Dcl + hi * self._input_terms[i]["D"]
            for j in range(r):
                wij = hi * float(h_arr[j])
                Acl = Acl + wij * self._cross_terms[i][j]["A"]
                Ccl = Ccl + wij * self._cross_terms[i][j]["C"]

        return StateSpace(
            A=Acl,
            B=Bcl,
            C=Ccl,
            D=Dcl,
            dt=self.dt,
            state_names=self._ts_model.state_names,
            input_names=self._input_names,
            output_names=self._ts_model.output_names,
            provenance={"source": "TSClosedLoop.evaluate_at_weights", "weights": h_arr.tolist()},
        )

    def to_dict(self) -> dict[str, Any]:
        r = self.n_vertices
        return ensure_json_finite(
            {
                "schema_version": "1.0.0",
                "kind": self.kind,
                "feedback_sign": self._feedback_sign,
                "dt": self.dt,
                "input_names": list(self._input_names),
                "ts_model": self._ts_model.to_dict(),
                "controller": self._controller.to_dict(),
                "cross_terms": [
                    [
                        {
                            "i": i,
                            "j": j,
                            "A": array_to_tensor(self._cross_terms[i][j]["A"], dtype="float64", order="C"),
                            "C": array_to_tensor(self._cross_terms[i][j]["C"], dtype="float64", order="C"),
                        }
                        for j in range(r)
                    ]
                    for i in range(r)
                ],
                "input_terms": [
                    {
                        "i": i,
                        "B": array_to_tensor(self._input_terms[i]["B"], dtype="float64", order="C"),
                        "D": array_to_tensor(self._input_terms[i]["D"], dtype="float64", order="C"),
                    }
                    for i in range(r)
                ],
                "provenance": copy.deepcopy(self._provenance),
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TSClosedLoop:
        if not isinstance(data, Mapping) or data.get("kind") != "TSClosedLoop":
            raise ValidationError("Payload inválido para TSClosedLoop.")
        ts_m = TSStateSpace.from_dict(data["ts_model"])
        ctrl = PDCController.from_dict(data["controller"])
        cross_terms = [
            [
                {
                    "A": tensor_to_array(cell["A"], expected_ndim=2, dtype="float64", strict_dtype=True),
                    "C": tensor_to_array(cell["C"], expected_ndim=2, dtype="float64", strict_dtype=True),
                }
                for cell in row
            ]
            for row in data["cross_terms"]
        ]
        input_terms = [
            {
                "B": tensor_to_array(item["B"], expected_ndim=2, dtype="float64", strict_dtype=True),
                "D": tensor_to_array(item["D"], expected_ndim=2, dtype="float64", strict_dtype=True),
            }
            for item in data["input_terms"]
        ]
        return cls(
            ts_model=ts_m,
            controller=ctrl,
            cross_terms=cross_terms,
            input_terms=input_terms,
            feedback_sign=data["feedback_sign"],
            input_names=data["input_names"],
            provenance=data.get("provenance"),
        )


def get_closed_loop_matrix(
    plant_or_A: Any,
    controller_or_B: Any = None,
    K: Any = None,
    feedback_sign: str | None = None,
) -> np.ndarray:
    """Retorna A_cl estritamente para realimentação estática completa (StateFeedbackController ou (A, B, K, sign)).

    Rejeita explicitamente DynamicController e PDCController com UnsupportedModelError / TypeError (Seção 4.2).
    """
    if isinstance(plant_or_A, StateSpace):
        plant = plant_or_A
        ctrl = controller_or_B
        if isinstance(ctrl, (DynamicController, PDCController)):
            raise UnsupportedModelError(
                message=(
                    f"get_closed_loop_matrix não se aplica a {type(ctrl).__name__}; "
                    "esse método é restrito à realimentação estática completa."
                ),
                parameters={"plant_id": plant.id, "controller_kind": type(ctrl).__name__},
                next_step="Use interconnect(plant, controller) para construir o sistema aumentado ou PDC.",
            )
        if not isinstance(ctrl, StateFeedbackController):
            raise UnsupportedModelError(
                message=f"Controlador incompatível para get_closed_loop_matrix: {type(ctrl).__name__}.",
                next_step="Forneça um StateFeedbackController ou chame interconnect().",
            )
        if K is not None:
            raise ValidationError("Não forneça K separado ao passar StateFeedbackController.")
        check_dt_compatible(plant.dt, ctrl.dt, label_a="plant", label_b="controller")
        if feedback_sign is not None:
            _validate_feedback_sign(feedback_sign)
            if feedback_sign != ctrl.feedback_sign:
                raise ValidationError(
                    f"Conflito de feedback_sign: argumento={feedback_sign!r} vs controller={ctrl.feedback_sign!r}."
                )
        if ctrl.K.shape != (plant.n_inputs, plant.n_states):
            raise DimensionMismatchError(
                message=f"Ganho K {ctrl.K.shape} incompatível com planta (m={plant.n_inputs}, n={plant.n_states}).",
                parameters={"K_shape": list(ctrl.K.shape), "expected": [plant.n_inputs, plant.n_states]},
            )
        sign = -1.0 if ctrl.feedback_sign == "negative" else 1.0
        return np.array(plant.A + sign * (plant.B @ ctrl.K), dtype=np.float64)

    if isinstance(plant_or_A, (TSStateSpace, Controller)):
        raise UnsupportedModelError(
            f"get_closed_loop_matrix não suporta {type(plant_or_A).__name__} diretamente; use interconnect()."
        )

    if isinstance(controller_or_B, DynamicController):
        raise UnsupportedModelError(
            "get_closed_loop_matrix não se aplica a DynamicController; use interconnect()."
        )

    if controller_or_B is None or K is None:
        raise ValidationError(
            "Chamada matricial de get_closed_loop_matrix requer (A, B, K, feedback_sign)."
        )

    A_arr = ensure_finite_float64(plant_or_A, ndim=2, name="A")
    if A_arr.shape[0] != A_arr.shape[1]:
        raise DimensionMismatchError(f"Matriz A deve ser quadrada, recebido {A_arr.shape}.")
    n = A_arr.shape[0]
    B_arr = ensure_finite_float64(controller_or_B, ndim=2, name="B")
    if B_arr.shape[0] != n:
        raise DimensionMismatchError(f"Matriz B ({B_arr.shape}) incompatível com A ({A_arr.shape}).")
    m = B_arr.shape[1]
    K_arr = ensure_finite_float64(K, ndim=2, name="K")
    if K_arr.shape != (m, n):
        raise DimensionMismatchError(f"Ganho K {K_arr.shape} incompatível com (m={m}, n={n}).")

    sign_str = _validate_feedback_sign(feedback_sign)
    sign = -1.0 if sign_str == "negative" else 1.0
    return np.array(A_arr + sign * (B_arr @ K_arr), dtype=np.float64)


def _check_wiring(wiring: Mapping[str, Any] | None) -> dict[str, Any]:
    if wiring is None:
        return {}
    if not isinstance(wiring, Mapping):
        raise ValidationError("wiring deve ser Mapping ou None.")
    extra = set(wiring.keys()) - _ALLOWED_WIRING_KEYS
    if extra:
        raise ValidationError(f"Chaves não reconhecidas em wiring: {sorted(extra)}")
    return dict(wiring)


def _resolve_sign_convention(controller: Controller, sign_convention: str | None, wiring: Mapping[str, Any]) -> str:
    w_sign = wiring.get("feedback_sign")
    if w_sign is not None:
        _validate_feedback_sign(w_sign)
    if sign_convention is not None:
        _validate_feedback_sign(sign_convention)
    if w_sign is not None and sign_convention is not None and w_sign != sign_convention:
        raise ValidationError(
            f"Conflito entre sign_convention={sign_convention!r} e wiring.feedback_sign={w_sign!r}."
        )
    explicit_sign = sign_convention or w_sign
    if explicit_sign is not None and explicit_sign != controller.feedback_sign:
        raise ValidationError(
            message=(
                f"Conflito de convenção de sinal: sign_convention={explicit_sign!r} difere de "
                f"controller.feedback_sign={controller.feedback_sign!r}."
            ),
            parameters={"sign_convention": explicit_sign, "controller_feedback_sign": controller.feedback_sign},
            next_step="Alinhe sign_convention com controller.feedback_sign ou evolua o controlador.",
        )
    return controller.feedback_sign


def _slice_controller_ports(
    controller: DynamicController,
    plant: StateSpace,
    scheme: str,
) -> dict[str, Any]:
    """Extrai blocos de Bc, Cc, Dc indexados por role de porta validando dimensões da planta."""
    n_p_out = plant.n_outputs
    n_p_in = plant.n_inputs

    # Saídas do controlador -> sinal 'u' para a planta
    u_row_indices: list[int] = []
    out_offset = 0
    for port in controller.ports["outputs"]:
        sz = port["size"]
        if port["role"] == "u":
            u_row_indices.extend(range(out_offset, out_offset + sz))
        out_offset += sz

    if len(u_row_indices) != n_p_in:
        raise DimensionMismatchError(
            message=(
                f"Soma dos tamanhos de portas de saída 'u' do controlador ({len(u_row_indices)}) "
                f"difere do número de entradas da planta (m={n_p_in})."
            ),
            parameters={"controller_u_size": len(u_row_indices), "plant_m": n_p_in},
        )

    Cc_u = controller.Cc[u_row_indices, :]
    Dc_u = controller.Dc[u_row_indices, :]

    # Entradas do controlador por role
    role_col_indices: dict[str, list[int]] = {}
    in_offset = 0
    for port in controller.ports["inputs"]:
        sz = port["size"]
        role_col_indices.setdefault(port["role"], []).extend(range(in_offset, in_offset + sz))
        in_offset += sz

    if scheme in ("output_feedback", "observer_based"):
        y_cols = role_col_indices.get("y", [])
        if len(y_cols) != n_p_out:
            raise DimensionMismatchError(
                message=(
                    f"Porta de entrada 'y' do controlador tem tamanho {len(y_cols)}, "
                    f"mas a planta tem p={n_p_out} saídas."
                ),
                parameters={"controller_y_size": len(y_cols), "plant_p": n_p_out},
            )
        extra_cols = [r for r in role_col_indices if r != "y"]
        if extra_cols:
            raise ValidationError(
                f"Esquema {scheme!r} espera apenas porta de entrada 'y'; encontradas {sorted(role_col_indices.keys())}."
            )
        return {
            "Cc_u": Cc_u,
            "Dc_u": Dc_u,
            "Bc_y": controller.Bc[:, y_cols],
            "Dc_uy": Dc_u[:, y_cols],
        }

    if scheme == "error_feedback":
        err_cols = role_col_indices.get("error", [])
        used_role = "error"
        if not err_cols and "y" in role_col_indices and len(role_col_indices) == 1:
            err_cols = role_col_indices["y"]
            used_role = "y"
        if len(err_cols) != n_p_out:
            raise DimensionMismatchError(
                message=(
                    f"Porta de erro do controlador tem tamanho {len(err_cols)}, "
                    f"mas a planta tem p={n_p_out} saídas."
                ),
                parameters={"controller_error_size": len(err_cols), "plant_p": n_p_out},
            )
        extra_roles = [r for r in role_col_indices if r != used_role]
        if extra_roles:
            raise ValidationError(
                message=f"Esquema 'error_feedback' não suporta portas de entrada extras: {sorted(extra_roles)}.",
                parameters={"scheme": "error_feedback", "extra_roles": sorted(extra_roles)},
            )
        return {
            "Cc_u": Cc_u,
            "Dc_u": Dc_u,
            "Bc_e": controller.Bc[:, err_cols],
            "Dc_ue": Dc_u[:, err_cols],
        }

    if scheme == "two_dof":
        y_cols = role_col_indices.get("y", [])
        r_cols = role_col_indices.get("r", [])
        if len(y_cols) != n_p_out:
            raise DimensionMismatchError(
                f"Esquema 'two_dof': porta 'y' ({len(y_cols)}) difere de p={n_p_out}."
            )
        if len(r_cols) < 1:
            raise DimensionMismatchError("Esquema 'two_dof' exige porta de entrada de referência 'r' com tamanho >= 1.")
        extra_roles = [r for r in role_col_indices if r not in ("y", "r")]
        if extra_roles:
            raise ValidationError(
                message=f"Esquema 'two_dof' suporta apenas portas de entrada 'y' e 'r'; extras encontradas: {sorted(extra_roles)}.",
                parameters={"scheme": "two_dof", "extra_roles": sorted(extra_roles)},
            )
        return {
            "Cc_u": Cc_u,
            "Dc_u": Dc_u,
            "Bc_y": controller.Bc[:, y_cols],
            "Bc_r": controller.Bc[:, r_cols],
            "Dc_uy": Dc_u[:, y_cols],
            "Dc_ur": Dc_u[:, r_cols],
        }

    raise UnsupportedModelError(
        message=f"Esquema de interconexão {scheme!r} não suportado para construção automática.",
        parameters={"scheme": scheme},
    )


def _check_well_posed_loop_matrix(M_u: np.ndarray, *, sign_str: str) -> dict[str, Any]:
    """Verifica invertibilidade e condicionamento de (I - s * Dc * Dp) via SVD (sem inv)."""
    svals = np.linalg.svd(M_u, compute_uv=False)
    s_max = float(svals[0]) if svals.size > 0 else 0.0
    s_min = float(svals[-1]) if svals.size > 0 else 0.0
    if not np.all(np.isfinite(svals)) or s_min <= 1e-12 * max(1.0, s_max):
        raise HypothesisViolatedError(
            message=(
                f"Interconexão algebricamente mal posta: matriz de fechamento (I - s Dc Dp) "
                f"é singular ou numericamente degenerada (sigma_min={s_min:.3e})."
            ),
            parameters={
                "feedback_sign": sign_str,
                "min_singular_value": s_min,
                "max_singular_value": s_max,
            },
            next_step="Altere os termos de feedthrough direto Dc ou Dp para que (I - s Dc Dp) seja invertível.",
        )
    cond_val = float(s_max / s_min)
    return {
        "min_singular_value": s_min,
        "max_singular_value": s_max,
        "condition_number": cond_val,
        "well_posed": True,
    }


def _build_interconnection(
    plant: Any,
    controller: Any,
    wiring: Mapping[str, Any] | None = None,
    sign_convention: str | None = None,
    *,
    premise_estimator: Any = None,
) -> tuple[StateSpace | TSClosedLoop, dict[str, Any], list[WarningItem]]:
    wiring_dict = _check_wiring(wiring)
    est = premise_estimator if premise_estimator is not None else wiring_dict.get("premise_estimator")
    warnings_out: list[WarningItem] = []

    if isinstance(plant, StateSpace) and isinstance(controller, StateFeedbackController):
        sign_str = _resolve_sign_convention(controller, sign_convention, wiring_dict)
        check_dt_compatible(plant.dt, controller.dt, label_a="plant", label_b="controller")
        n, m, p = plant.n_states, plant.n_inputs, plant.n_outputs
        if controller.K.shape != (m, n):
            raise DimensionMismatchError(
                message=f"Ganho K {controller.K.shape} incompatível com planta (m={m}, n={n}).",
                parameters={"K_shape": list(controller.K.shape), "plant_m": m, "plant_n": n},
            )

        s = -1.0 if sign_str == "negative" else 1.0
        Acl = np.array(plant.A + s * (plant.B @ controller.K), dtype=np.float64)
        Ccl = np.array(plant.C + s * (plant.D @ controller.K), dtype=np.float64)

        ref_mat = controller.reference_matrix
        ref_kind = controller.reference_kind
        ref_names = controller.reference_names
        if ref_mat is None and wiring_dict.get("reference_map") is not None:
            ref_mat = ensure_finite_float64(wiring_dict["reference_map"], ndim=2, name="wiring.reference_map")
            if ref_mat.shape[0] != m:
                raise DimensionMismatchError(
                    f"wiring.reference_map linhas ({ref_mat.shape[0]}) devem igualar m={m}."
                )

        if ref_mat is None:
            Bcl = np.array(plant.B, dtype=np.float64)
            Dcl = np.array(plant.D, dtype=np.float64)
            in_names = plant.input_names
            in_units = list(plant.units.get("inputs", [""] * m))
            p_ref = m
        else:
            if ref_mat.shape[0] != m:
                raise DimensionMismatchError(
                    f"Prefiltro N {ref_mat.shape} incompatível com m={m} entradas da planta."
                )
            if ref_kind == "output_prefilter" and ref_mat.shape[1] != p:
                raise DimensionMismatchError(
                    message=f"output_prefilter N {ref_mat.shape} incompatível com (m={m}, p={p}).",
                    parameters={"N_shape": list(ref_mat.shape), "expected": [m, p]},
                )
            Bcl = np.array(plant.B @ ref_mat, dtype=np.float64)
            Dcl = np.array(plant.D @ ref_mat, dtype=np.float64)
            p_ref = ref_mat.shape[1]
            in_names = ref_names if ref_names is not None else tuple(f"r{i + 1}" for i in range(p_ref))
            in_units = [""] * p_ref

        cl_units = {
            "time": plant.units.get("time", "s"),
            "inputs": in_units,
            "outputs": list(plant.units.get("outputs", [""] * p)),
            "states": list(plant.units.get("states", [""] * n)) if "states" in plant.units else [""] * n,
        }
        cl_ss = StateSpace(
            A=Acl,
            B=Bcl,
            C=Ccl,
            D=Dcl,
            dt=plant.dt,
            state_names=plant.state_names,
            input_names=in_names,
            output_names=plant.output_names,
            units=cl_units,
            provenance={
                "source": "interconnect",
                "interconnection_kind": "state_feedback",
                "feedback_sign": sign_str,
                "plant_ref": {"id": plant.id, "revision": plant.revision},
                "controller_ref": {"id": controller.id, "revision": controller.revision},
            },
        )
        diag = {
            "interconnection_kind": "state_feedback",
            "feedback_sign": sign_str,
            "well_posed": True,
            "closed_loop_states": n,
            "closed_loop_inputs": p_ref,
            "closed_loop_outputs": p,
        }
        return cl_ss, diag, warnings_out

    if isinstance(plant, StateSpace) and isinstance(controller, DynamicController):
        sign_str = _resolve_sign_convention(controller, sign_convention, wiring_dict)
        check_dt_compatible(plant.dt, controller.dt, label_a="plant", label_b="controller")

        w_scheme = wiring_dict.get("scheme")
        if w_scheme is not None:
            if controller.interconnection_scheme is not None and w_scheme != controller.interconnection_scheme:
                raise ValidationError(
                    f"Conflito de esquema: wiring.scheme={w_scheme!r} vs controller.interconnection_scheme={controller.interconnection_scheme!r}."
                )
            scheme = w_scheme
        else:
            scheme = controller.resolved_scheme

        sliced = _slice_controller_ports(controller, plant, scheme)
        s = -1.0 if sign_str == "negative" else 1.0
        Ap, Bp, Cp, Dp = plant.A, plant.B, plant.C, plant.D
        Ac = controller.Ac
        Cc_u = sliced["Cc_u"]
        np_s, m, p = plant.n_states, plant.n_inputs, plant.n_outputs
        nc_s = controller.n_states

        if scheme in ("output_feedback", "observer_based"):
            Bc_y = sliced["Bc_y"]
            Dc_uy = sliced["Dc_uy"]
            M_u = np.eye(m, dtype=np.float64) - s * (Dc_uy @ Dp)
            loop_diag = _check_well_posed_loop_matrix(M_u, sign_str=sign_str)
            try:
                G_uxp = np.linalg.solve(M_u, s * (Dc_uy @ Cp))
                G_uxc = np.linalg.solve(M_u, s * Cc_u)
                G_ur = np.linalg.solve(M_u, np.eye(m, dtype=np.float64))
            except np.linalg.LinAlgError as exc:
                raise HypothesisViolatedError(
                    f"Falha na solução linear do loop algébrico (I - s Dc Dp): {exc}"
                ) from exc

            Acl = np.block(
                [
                    [Ap + Bp @ G_uxp, Bp @ G_uxc],
                    [Bc_y @ (Cp + Dp @ G_uxp), Ac + Bc_y @ (Dp @ G_uxc)],
                ]
            )
            Bcl = np.vstack([Bp @ G_ur, Bc_y @ (Dp @ G_ur)])
            Ccl = np.hstack([Cp + Dp @ G_uxp, Dp @ G_uxc])
            Dcl = np.array(Dp @ G_ur, dtype=np.float64)
            in_names = plant.input_names
            in_units = list(plant.units.get("inputs", [""] * m))
        elif scheme == "error_feedback":
            Bc_e = sliced["Bc_e"]
            Dc_ue = sliced["Dc_ue"]
            M_u = np.eye(m, dtype=np.float64) - s * (Dc_ue @ Dp)
            loop_diag = _check_well_posed_loop_matrix(M_u, sign_str=sign_str)
            try:
                G_uxp = np.linalg.solve(M_u, s * (Dc_ue @ Cp))
                G_uxc = np.linalg.solve(M_u, Cc_u)
                G_ur = np.linalg.solve(M_u, Dc_ue)
            except np.linalg.LinAlgError as exc:
                raise HypothesisViolatedError(
                    f"Falha na solução linear do loop algébrico (I - s Dc Dp): {exc}"
                ) from exc

            Acl = np.block(
                [
                    [Ap + Bp @ G_uxp, Bp @ G_uxc],
                    [s * Bc_e @ (Cp + Dp @ G_uxp), Ac + s * Bc_e @ (Dp @ G_uxc)],
                ]
            )
            Bcl = np.vstack([Bp @ G_ur, Bc_e @ (np.eye(p, dtype=np.float64) + s * (Dp @ G_ur))])
            Ccl = np.hstack([Cp + Dp @ G_uxp, Dp @ G_uxc])
            Dcl = np.array(Dp @ G_ur, dtype=np.float64)
            in_names = tuple(f"r{i + 1}" for i in range(p))
            in_units = list(plant.units.get("outputs", [""] * p))
        elif scheme == "two_dof":
            Bc_y, Bc_r = sliced["Bc_y"], sliced["Bc_r"]
            Dc_uy, Dc_ur = sliced["Dc_uy"], sliced["Dc_ur"]
            M_u = np.eye(m, dtype=np.float64) - s * (Dc_uy @ Dp)
            loop_diag = _check_well_posed_loop_matrix(M_u, sign_str=sign_str)
            try:
                G_uxp = np.linalg.solve(M_u, s * (Dc_uy @ Cp))
                G_uxc = np.linalg.solve(M_u, Cc_u)
                G_ur = np.linalg.solve(M_u, Dc_ur)
            except np.linalg.LinAlgError as exc:
                raise HypothesisViolatedError(
                    f"Falha na solução linear do loop algébrico (I - s Dcy Dp): {exc}"
                ) from exc

            Acl = np.block(
                [
                    [Ap + Bp @ G_uxp, Bp @ G_uxc],
                    [s * Bc_y @ (Cp + Dp @ G_uxp), Ac + s * Bc_y @ (Dp @ G_uxc)],
                ]
            )
            Bcl = np.vstack([Bp @ G_ur, Bc_r + s * Bc_y @ (Dp @ G_ur)])
            Ccl = np.hstack([Cp + Dp @ G_uxp, Dp @ G_uxc])
            Dcl = np.array(Dp @ G_ur, dtype=np.float64)
            p_ref = Dc_ur.shape[1]
            in_names = tuple(f"r{i + 1}" for i in range(p_ref))
            in_units = [""] * p_ref
        else:
            raise UnsupportedModelError(f"Esquema {scheme!r} não suportado em interconnect.")

        if loop_diag["condition_number"] > 1e10:
            warnings_out.append(
                WarningItem(
                    code="ILL_CONDITIONED_ALGEBRAIC_LOOP",
                    message=(
                        f"Matriz de fechamento (I - s Dc Dp) mal condicionada: "
                        f"cond={loop_diag['condition_number']:.3e}."
                    ),
                    details=loop_diag,
                )
            )

        ctrl_states = (
            list(controller.state_names)
            if controller.state_names is not None
            else [f"xc{i + 1}" for i in range(nc_s)]
        )
        aug_state_names = [f"plant.{sn}" for sn in plant.state_names] + [f"ctrl.{cn}" for cn in ctrl_states]
        cl_units = {
            "time": plant.units.get("time", "s"),
            "inputs": in_units,
            "outputs": list(plant.units.get("outputs", [""] * p)),
        }
        cl_ss = StateSpace(
            A=Acl,
            B=Bcl,
            C=Ccl,
            D=Dcl,
            dt=plant.dt,
            state_names=aug_state_names,
            input_names=in_names,
            output_names=plant.output_names,
            units=cl_units,
            provenance={
                "source": "interconnect",
                "interconnection_kind": "dynamic_controller",
                "interconnection_scheme": scheme,
                "feedback_sign": sign_str,
                "plant_ref": {"id": plant.id, "revision": plant.revision},
                "controller_ref": {"id": controller.id, "revision": controller.revision},
                "loop_diagnostics": loop_diag,
            },
        )
        diag = {
            "interconnection_kind": "dynamic_controller",
            "interconnection_scheme": scheme,
            "feedback_sign": sign_str,
            "closed_loop_states": np_s + nc_s,
            "closed_loop_inputs": int(Bcl.shape[1]),
            "closed_loop_outputs": p,
            **loop_diag,
        }
        return cl_ss, diag, warnings_out

    if isinstance(plant, TSStateSpace) and isinstance(controller, PDCController):
        sign_str = _resolve_sign_convention(controller, sign_convention, wiring_dict)
        controller.validate_against_ts_model(plant, premise_estimator=est)

        s = -1.0 if sign_str == "negative" else 1.0
        r = plant.n_vertices
        m = plant.n_inputs
        p = plant.n_outputs
        verts = plant.vertices

        ref_mat = controller.reference_matrix
        ref_kind = controller.reference_kind
        ref_names = controller.reference_names
        if ref_mat is not None and ref_kind == "output_prefilter" and ref_mat.shape[1] != p:
            raise DimensionMismatchError(f"output_prefilter N {ref_mat.shape} incompatível com (m={m}, p={p}).")

        cross_terms: list[list[dict[str, np.ndarray]]] = []
        for i in range(r):
            Ai = verts[i]["A"]
            Bi = verts[i]["B"]
            Ci = verts[i]["C"]
            Di = verts[i]["D"]
            row_i: list[dict[str, np.ndarray]] = []
            for j in range(r):
                Kj = controller.K_i[j]
                row_i.append(
                    {
                        "A": np.array(Ai + s * (Bi @ Kj), dtype=np.float64),
                        "C": np.array(Ci + s * (Di @ Kj), dtype=np.float64),
                    }
                )
            cross_terms.append(row_i)

        input_terms: list[dict[str, np.ndarray]] = []
        for i in range(r):
            Bi = verts[i]["B"]
            Di = verts[i]["D"]
            if ref_mat is None:
                input_terms.append({"B": np.array(Bi, dtype=np.float64), "D": np.array(Di, dtype=np.float64)})
            else:
                input_terms.append({"B": np.array(Bi @ ref_mat, dtype=np.float64), "D": np.array(Di @ ref_mat, dtype=np.float64)})

        if ref_mat is None:
            in_names = plant.input_names
            p_ref = m
        else:
            p_ref = ref_mat.shape[1]
            in_names = ref_names if ref_names is not None else tuple(f"r{i + 1}" for i in range(p_ref))

        ts_cl = TSClosedLoop(
            ts_model=plant,
            controller=controller,
            cross_terms=cross_terms,
            input_terms=input_terms,
            feedback_sign=sign_str,
            input_names=in_names,
            provenance={
                "source": "interconnect",
                "interconnection_kind": "ts_pdc",
                "feedback_sign": sign_str,
                "ts_kind": plant.kind,
                "premise_estimator_provided": est is not None,
            },
        )
        diag = {
            "interconnection_kind": "ts_pdc",
            "ts_kind": plant.kind,
            "feedback_sign": sign_str,
            "n_vertices": r,
            "n_cross_terms": r * r,
            "well_posed": True,
            "closed_loop_inputs": p_ref,
        }
        return ts_cl, diag, warnings_out

    raise UnsupportedModelError(
        message=f"Combinação não suportada para interconexão: ({type(plant).__name__}, {type(controller).__name__}).",
        parameters={"plant_type": type(plant).__name__, "controller_type": type(controller).__name__},
    )


def validate_interconnection(
    plant: Any,
    controller: Any,
    wiring: Mapping[str, Any] | None = None,
    sign_convention: str | None = None,
    *,
    raise_on_error: bool = True,
    premise_estimator: Any = None,
) -> Result:
    """Valida dimensões, domínio temporal, premissas TS e bem-postura algébrica de uma interconexão."""
    prov: Provenance = build_provenance(
        "control_lab.core.validate_interconnection",
        model_revision=getattr(plant, "revision", None),
    )
    try:
        cl_obj, diag, warns = _build_interconnection(
            plant,
            controller,
            wiring=wiring,
            sign_convention=sign_convention,
            premise_estimator=premise_estimator,
        )
        status = "warning" if warns else "success"
        return Result(
            status=status,
            data={
                "valid": True,
                "plant_id": getattr(plant, "id", None),
                "controller_id": getattr(controller, "id", None),
                "closed_loop_kind": cl_obj.kind,
            },
            assumptions={
                "dt_compatible": True,
                "well_posed": True,
                "feedback_sign": cl_obj.feedback_sign if hasattr(cl_obj, "feedback_sign") else getattr(controller, "feedback_sign", None),
            },
            diagnostics=diag,
            provenance=prov,
            warnings=warns,
            error=None,
        )
    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions={"well_posed": False},
            diagnostics={},
            provenance=prov,
            warnings=[],
            error=exc.to_typed_error(),
        )


def interconnect(
    plant: Any,
    controller: Any,
    wiring: Mapping[str, Any] | None = None,
    sign_convention: str | None = None,
    *,
    premise_estimator: Any = None,
) -> StateSpace | TSClosedLoop:
    """Constrói o sistema em malha fechada validando dimensões, dt e bem-postura do loop algébrico."""
    cl_obj, _, _ = _build_interconnection(
        plant,
        controller,
        wiring=wiring,
        sign_convention=sign_convention,
        premise_estimator=premise_estimator,
    )
    return cl_obj


def make_closed_loop(
    plant: Any,
    controller: Any,
    wiring: Mapping[str, Any] | None = None,
    sign_convention: str | None = None,
    *,
    return_result: bool = False,
    premise_estimator: Any = None,
) -> StateSpace | TSClosedLoop | Result:
    """Interface canônica da Seção 13.3 para fechamento de malha (modelo ou Result)."""
    if not return_result:
        return interconnect(
            plant,
            controller,
            wiring=wiring,
            sign_convention=sign_convention,
            premise_estimator=premise_estimator,
        )

    prov = build_provenance(
        "control_lab.core.make_closed_loop",
        model_revision=getattr(plant, "revision", None),
    )
    try:
        cl_obj, diag, warns = _build_interconnection(
            plant,
            controller,
            wiring=wiring,
            sign_convention=sign_convention,
            premise_estimator=premise_estimator,
        )
        return Result(
            status="warning" if warns else "success",
            data={"closed_loop": cl_obj.to_dict()},
            assumptions={"dt_compatible": True, "well_posed": True},
            diagnostics=diag,
            provenance=prov,
            warnings=warns,
            error=None,
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={"well_posed": False},
            diagnostics={},
            provenance=prov,
            warnings=[],
            error=exc.to_typed_error(),
        )
