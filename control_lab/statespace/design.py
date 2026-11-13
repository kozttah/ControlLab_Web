"""Síntese em espaço de estados: LQR, LQI, alocação de polos, observadores, Kalman e LQG."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import scipy.linalg
import scipy.signal

from control_lab.core.controllers import (
    DynamicController,
    StateFeedbackController,
    _validate_feedback_sign,
)
from control_lab.core.interconnect import get_closed_loop_matrix, interconnect
from control_lab.core.models import StateSpace
from control_lab.core.tensors import complex_to_pair, ensure_finite_float64, tensor_to_array
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    NumericalInconclusiveError,
    Provenance,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
)

from ._utils import (
    DEFAULT_COND_WARN_THRESHOLD,
    DEFAULT_SYMMETRY_TOL,
    care_residual_rel,
    dare_residual_rel,
    handle_failure,
    match_poles_error,
    pbh_analysis_core,
    resolve_state_space_inputs,
    safe_svd_metrics,
    sort_complex_eigs,
    symmetry_error_rel,
    validate_conjugate_poles,
    validate_symmetric_pd,
    validate_symmetric_psd,
    validate_x0_vector,
)
from .equations import _resolve_riccati_inputs, _solve_are_core

_UNSET: Any = object()


def _merge_warnings(*warn_lists: Sequence[Any]) -> list[WarningItem]:
    out: list[WarningItem] = []
    for wl in warn_lists:
        for item in wl:
            if isinstance(item, WarningItem):
                out.append(item)
            else:
                out.append(WarningItem(code="STATESPACE_WARNING", message=str(item)))
    return out


def design_lqr(
    plant_or_A: Any = None,
    B_or_Q: Any = None,
    Q_or_R: Any = None,
    R_mat: Any = None,
    *,
    plant: StateSpace | None = None,
    A: Any = None,
    B: Any = None,
    Q: Any = None,
    R: Any = None,
    x0: Any = None,
    feedback_sign: str = "negative",
    reference_map: Any = None,
    method: str | None = None,
    dt: float | None = _UNSET,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Sintetiza controlador LQR (contínuo via CARE ou discreto via DARE) retornando StateFeedbackController em Result."""
    dt_provided = dt is not _UNSET
    resolved_dt_arg = None if dt is _UNSET else dt
    prov: Provenance = build_provenance(
        "statespace.design_lqr",
        model_revision=getattr(plant if plant is not None else plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sign_str = _validate_feedback_sign(feedback_sign)
        info = _resolve_riccati_inputs(
            plant_or_A,
            B_or_Q,
            Q_or_R,
            R_mat,
            plant=plant,
            A=A,
            B=B,
            Q=Q,
            R=R,
            dt=resolved_dt_arg,
            dt_provided=dt_provided,
        )
        ss_plant: StateSpace | None = info["plant"]
        resolved_dt: float | None = info["dt"]

        if method is not None:
            if not isinstance(method, str) or method.lower() not in ("care", "dare", "auto"):
                raise ValidationError(
                    f"method inválido em design_lqr: {method!r}. Use 'auto', 'care' ou 'dare'."
                )
            m_low = method.lower()
        else:
            m_low = "auto"

        if m_low == "auto":
            domain = "continuous" if resolved_dt is None else "discrete"
        elif m_low == "care":
            if resolved_dt is not None:
                raise UnsupportedModelError(
                    message=f"method='care' incompatível com modelo discreto (dt={resolved_dt}).",
                    parameters={"method": "care", "dt": resolved_dt},
                )
            domain = "continuous"
        else:  # dare
            if ss_plant is not None and ss_plant.dt is None:
                raise UnsupportedModelError(
                    message="method='dare' incompatível com StateSpace contínuo (dt=None).",
                    parameters={"method": "dare", "dt": None},
                )
            if dt_provided and resolved_dt_arg is None:
                raise UnsupportedModelError(
                    message="method='dare' incompatível com dt=None explícito.",
                    parameters={"method": "dare", "dt": None},
                )
            domain = "discrete"

        alg_id = "scipy.linalg.solve_continuous_are" if domain == "continuous" else "scipy.linalg.solve_discrete_are"
        are_res = _solve_are_core(
            domain=domain,
            plant_or_A=plant_or_A,
            B_or_Q=B_or_Q,
            Q_or_R=Q_or_R,
            R_mat=R_mat,
            plant=plant,
            A=A,
            B=B,
            Q=Q,
            R=R,
            x0=x0,
            dt=resolved_dt_arg,
            dt_provided=dt_provided,
            tol=tol,
            check_hypotheses=True,
            raise_on_error=True,
            alg_id=alg_id,
        )
        assert are_res.data is not None

        P = tensor_to_array(are_res.data["P"], expected_ndim=2, dtype="float64")
        K_lqr = tensor_to_array(are_res.data["K"], expected_ndim=2, dtype="float64")
        K_ctrl = K_lqr if sign_str == "negative" else -K_lqr

        ctrl_prov = build_provenance(
            alg_id,
            tolerances=are_res.provenance.tolerances,
            model_revision=info["model_revision"],
            feedback_sign=sign_str,
        )
        ctrl = StateFeedbackController(
            K=K_ctrl,
            feedback_sign=sign_str,
            state_coordinates=info["state_names"],
            reference_map=reference_map,
            dt=resolved_dt,
            input_names=info["input_names"],
            provenance=ctrl_prov.to_dict(),
        )

        # Garantir coerência com interconnect / get_closed_loop_matrix da F1
        A_cl_check = get_closed_loop_matrix(info["A"], info["B"], K_ctrl, sign_str)
        if not np.allclose(A_cl_check, info["A"] - info["B"] @ K_lqr, rtol=1e-10, atol=1e-12):
            raise NumericalInconclusiveError("Inconsistência numérica na verificação de malha fechada LQR.")

        cl_dict: dict[str, Any] | None = None
        if ss_plant is not None:
            cl_ss = interconnect(ss_plant, ctrl, sign_convention=sign_str)
            cl_dict = cl_ss.to_dict()

        assumptions = {
            **are_res.assumptions,
            "feedback_sign": sign_str,
        }
        diagnostics = dict(are_res.diagnostics)
        warnings_out = _merge_warnings(are_res.warnings)

        data: dict[str, Any] = {
            "controller": ctrl.to_dict(),
            "controller_ref": {"id": ctrl.id, "revision": ctrl.revision},
            "controller_kind": ctrl.kind,
            "feedback_sign": sign_str,
            "K": K_ctrl,
            "K_lqr": K_lqr,
            "P": P,
            "open_loop_poles": are_res.data["open_loop_poles"],
            "closed_loop_poles": are_res.data["closed_loop_poles"],
            "optimal_cost": are_res.data["optimal_cost"],
        }
        if cl_dict is not None:
            data["closed_loop"] = cl_dict

        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=ctrl_prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def design_lqi(
    plant: StateSpace,
    Q: Any,
    R: Any,
    *,
    Q_i: Any = None,
    output_indices: Sequence[int] | None = None,
    x0: Any = None,
    xi0: Any = None,
    feedback_sign: str = "negative",
    integral_dt_scaled: bool = True,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Sintetiza controlador LQR com ação integral (LQI) sobre saídas rastreadas de StateSpace."""
    prov: Provenance = build_provenance(
        "statespace.design_lqi",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(plant, StateSpace):
            raise UnsupportedModelError(
                message=f"design_lqi requer instância StateSpace, recebido {type(plant).__name__}.",
                parameters={"plant_type": type(plant).__name__},
            )
        if plant.n_states < 1 or plant.n_inputs < 1 or plant.n_outputs < 1:
            raise DimensionMismatchError(
                message="design_lqi requer planta com n >= 1 estados, m >= 1 entradas e p >= 1 saídas.",
                parameters={"n": plant.n_states, "m": plant.n_inputs, "p": plant.n_outputs},
            )

        sign_str = _validate_feedback_sign(feedback_sign)
        n, m, p = plant.n_states, plant.n_inputs, plant.n_outputs

        if output_indices is None:
            idx_list = list(range(p))
        else:
            if isinstance(output_indices, (str, bytes)) or not isinstance(output_indices, Sequence):
                raise ValidationError("output_indices deve ser sequência de inteiros.")
            idx_list = list(output_indices)
            if len(idx_list) < 1:
                raise ValidationError("output_indices não pode ser vazio.")
            if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= p for i in idx_list):
                raise ValidationError(f"output_indices contém índice inválido para p={p}: {idx_list!r}")
            if len(set(idx_list)) != len(idx_list):
                raise ValidationError("output_indices não pode conter índices duplicados.")

        p_i = len(idx_list)
        Cr = plant.C[idx_list, :]
        Dr = plant.D[idx_list, :]

        if Q_i is not None:
            Q_x = ensure_finite_float64(Q, ndim=2, shape=(n, n), name="Q")
            Q_int = ensure_finite_float64(Q_i, ndim=2, shape=(p_i, p_i), name="Q_i")
            Q_aug = scipy.linalg.block_diag(Q_x, Q_int)
        else:
            Q_aug = ensure_finite_float64(Q, ndim=2, name="Q")
            if Q_aug.shape != (n + p_i, n + p_i):
                raise DimensionMismatchError(
                    message=(
                        f"Matriz Q aumentada deve ter shape ({n + p_i}, {n + p_i}) "
                        f"(ou forneça Q ({n}, {n}) junto com Q_i ({p_i}, {p_i})), recebido {Q_aug.shape}."
                    ),
                    parameters={"Q_shape": list(Q_aug.shape), "expected_aug": [n + p_i, n + p_i]},
                )

        if plant.dt is None:
            domain = "continuous"
            Aa = np.block([[plant.A, np.zeros((n, p_i))], [-Cr, np.zeros((p_i, p_i))]])
            Ba = np.vstack([plant.B, -Dr])
            Br = np.vstack([np.zeros((n, p_i)), np.eye(p_i, dtype=np.float64)])
            alg_id = "statespace.design_lqi.care"
        else:
            domain = "discrete"
            ti = float(plant.dt) if integral_dt_scaled else 1.0
            Aa = np.block([[plant.A, np.zeros((n, p_i))], [-ti * Cr, np.eye(p_i, dtype=np.float64)]])
            Ba = np.vstack([plant.B, -ti * Dr])
            Br = np.vstack([np.zeros((n, p_i)), ti * np.eye(p_i, dtype=np.float64)])
            alg_id = "statespace.design_lqi.dare"

        z0_vec: np.ndarray | None = None
        if x0 is not None or xi0 is not None:
            if x0 is None:
                x0_v = np.zeros((n,), dtype=np.float64)
                xi0_v = validate_x0_vector(xi0, p_i)
                z0_vec = np.concatenate([x0_v, xi0_v])
            else:
                x0_raw = ensure_finite_float64(x0, name="x0")
                if x0_raw.size == n + p_i and xi0 is None:
                    z0_vec = validate_x0_vector(x0_raw, n + p_i)
                else:
                    x0_v = validate_x0_vector(x0_raw, n)
                    xi0_v = validate_x0_vector(xi0, p_i) if xi0 is not None else np.zeros((p_i,), dtype=np.float64)
                    z0_vec = np.concatenate([x0_v, xi0_v])

        are_res = _solve_are_core(
            domain=domain,
            plant_or_A=Aa,
            B_or_Q=Ba,
            Q_or_R=Q_aug,
            R_mat=R,
            plant=None,
            A=None,
            B=None,
            Q=None,
            R=None,
            x0=z0_vec,
            dt=plant.dt,
            dt_provided=(plant.dt is not None),
            tol=tol,
            check_hypotheses=True,
            raise_on_error=True,
            alg_id=alg_id,
        )
        assert are_res.data is not None

        P_aug = tensor_to_array(are_res.data["P"], expected_ndim=2, dtype="float64")
        K_lqr = tensor_to_array(are_res.data["K"], expected_ndim=2, dtype="float64")
        K_x = K_lqr[:, :n]
        K_i = K_lqr[:, n:]
        K_ctrl = K_lqr if sign_str == "negative" else -K_lqr

        aug_state_names = list(plant.state_names) + [f"xi_{plant.output_names[idx]}" for idx in idx_list]
        aug_ref_names = [f"r_{plant.output_names[idx]}" for idx in idx_list]

        prov_ok = build_provenance(
            alg_id,
            tolerances=are_res.provenance.tolerances,
            model_revision=plant.revision,
            feedback_sign=sign_str,
            integral_dt_scaled=integral_dt_scaled,
        )
        ctrl = StateFeedbackController(
            K=K_ctrl,
            feedback_sign=sign_str,
            state_coordinates=aug_state_names,
            dt=plant.dt,
            input_names=plant.input_names,
            provenance=prov_ok.to_dict(),
        )

        # Planta aumentada e malha fechada rastreando r -> y
        Ca_zeros = np.zeros((p, p_i), dtype=np.float64)
        aug_plant = StateSpace(
            A=Aa,
            B=Ba,
            C=np.hstack([plant.C, Ca_zeros]),
            D=plant.D,
            dt=plant.dt,
            state_names=aug_state_names,
            input_names=plant.input_names,
            output_names=plant.output_names,
            provenance={"source": "design_lqi.augmented_plant", "plant_id": plant.id},
        )

        Acl = Aa - Ba @ K_lqr
        Ccl = np.hstack([plant.C - plant.D @ K_x, -plant.D @ K_i])
        Dcl = np.zeros((p, p_i), dtype=np.float64)
        cl_ss = StateSpace(
            A=Acl,
            B=Br,
            C=Ccl,
            D=Dcl,
            dt=plant.dt,
            state_names=aug_state_names,
            input_names=aug_ref_names,
            output_names=plant.output_names,
            provenance={"source": "design_lqi.closed_loop", "plant_id": plant.id},
        )

        assumptions = {
            **are_res.assumptions,
            "feedback_sign": sign_str,
            "tracked_output_indices": idx_list,
            "integral_dt_scaled": integral_dt_scaled,
        }
        diagnostics = dict(are_res.diagnostics)
        warnings_out = _merge_warnings(are_res.warnings)

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "controller": ctrl.to_dict(),
                "controller_ref": {"id": ctrl.id, "revision": ctrl.revision},
                "controller_kind": ctrl.kind,
                "feedback_sign": sign_str,
                "K": K_ctrl,
                "K_lqr": K_lqr,
                "K_x": K_x,
                "K_i": K_i,
                "P": P_aug,
                "augmented_plant": aug_plant.to_dict(),
                "closed_loop": cl_ss.to_dict(),
                "open_loop_poles": are_res.data["open_loop_poles"],
                "closed_loop_poles": are_res.data["closed_loop_poles"],
                "optimal_cost": are_res.data["optimal_cost"],
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov_ok,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def _max_pole_multiplicity(poles: np.ndarray) -> int:
    scale = max(1.0, float(np.max(np.abs(poles)))) if poles.size > 0 else 1.0
    tol = 1e-9 * scale
    max_m = 0
    for i in range(poles.size):
        cnt = int(np.sum(np.abs(poles - poles[i]) <= tol))
        if cnt > max_m:
            max_m = cnt
    return max_m


def _ackermann_siso(A: np.ndarray, B: np.ndarray, poles: np.ndarray) -> tuple[np.ndarray, float | None]:
    """Fórmula de Ackermann SISO sem inv explícita para polos repetidos em sistemas de baixa ordem."""
    n = A.shape[0]
    blocks = []
    cur = np.array(B, dtype=np.float64, copy=True)
    for k in range(n):
        blocks.append(cur)
        if k + 1 < n:
            cur = A @ cur
    Ctrb = np.hstack(blocks)
    svd_c = safe_svd_metrics(Ctrb)
    if svd_c["is_singular"]:
        raise HypothesisViolatedError("Matriz de controlabilidade singular na fórmula de Ackermann.")

    coeffs = np.real_if_close(np.poly(poles), tol=1e4)
    if np.iscomplexobj(coeffs):
        coeffs = np.real(coeffs)
    coeffs = np.asarray(coeffs, dtype=np.float64)

    eye_n = np.eye(n, dtype=np.float64)
    poly_A = coeffs[0] * eye_n
    for c in coeffs[1:]:
        poly_A = poly_A @ A + float(c) * eye_n

    e_n = np.zeros((n, 1), dtype=np.float64)
    e_n[-1, 0] = 1.0
    last_row = np.linalg.solve(Ctrb.T, e_n).T
    K = np.asarray(last_row @ poly_A, dtype=np.float64)
    return K, svd_c["cond"]


def _resolve_placement_inputs(
    plant_or_A: Any,
    B_or_poles: Any,
    poles: Any,
    *,
    dt: float | None,
    dt_provided: bool,
    second_label: str,
) -> tuple[dict[str, Any], Any]:
    if isinstance(plant_or_A, StateSpace):
        if poles is not None and B_or_poles is not None:
            raise ValidationError(f"Não misture {second_label} com objeto StateSpace.")
        target_poles = poles if poles is not None else B_or_poles
        sys_info = resolve_state_space_inputs(
            plant_or_A, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
        )
        return sys_info, target_poles

    if hasattr(plant_or_A, "kind") and not isinstance(plant_or_A, (np.ndarray, list, tuple)):
        raise UnsupportedModelError(
            f"Tipo de modelo {type(plant_or_A).__name__} não suportado; forneça StateSpace."
        )

    if B_or_poles is None or poles is None:
        raise ValidationError(f"Chamada matricial requer (A, {second_label}, poles).")
    if second_label == "B":
        sys_info = resolve_state_space_inputs(
            plant_or_A, B=B_or_poles, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
        )
    else:
        sys_info = resolve_state_space_inputs(
            plant_or_A, C=B_or_poles, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
        )
    return sys_info, poles


def design_pole_placement(
    plant_or_A: Any,
    B_or_poles: Any = None,
    poles: Any = None,
    *,
    feedback_sign: str = "negative",
    reference_map: Any = None,
    method: str = "YT",
    dt: float | None = None,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Alocação de polos por realimentação de estados (YT/KNV0 ou Ackermann SISO para multiplicidade > 1)."""
    dt_provided = dt is not None
    prov: Provenance = build_provenance(
        "statespace.design_pole_placement",
        model_revision=getattr(plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sign_str = _validate_feedback_sign(feedback_sign)
        if method not in ("YT", "KNV0"):
            raise ValidationError(f"method inválido em design_pole_placement: {method!r}. Use 'YT' ou 'KNV0'.")

        sys_info, raw_poles = _resolve_placement_inputs(
            plant_or_A, B_or_poles, poles, dt=dt, dt_provided=dt_provided, second_label="B"
        )
        A_arr: np.ndarray = sys_info["A"]
        B_arr: np.ndarray = sys_info["B"]
        n: int = sys_info["n"]
        m: int = sys_info["m"]
        resolved_dt: float | None = sys_info["dt"]
        ss_plant: StateSpace | None = sys_info["plant"]

        if m < 1:
            raise DimensionMismatchError("Alocação de polos requer pelo menos 1 entrada (m >= 1).")

        target_poles = validate_conjugate_poles(raw_poles, n)
        pbh = pbh_analysis_core(A_arr, B=B_arr, dt=resolved_dt, tol=tol)
        warnings_out.extend(pbh["warnings"])
        assumptions = {
            "domain": "continuous" if resolved_dt is None else "discrete",
            "dt": resolved_dt,
            "controllable": bool(pbh["controllable"]),
            "feedback_sign": sign_str,
        }
        diagnostics = {
            "pbh_min_sv_controllability": pbh["min_sv_controllability"],
        }

        if not pbh["controllable"]:
            raise HypothesisViolatedError(
                message="Par (A, B) não é controlável pelo teste PBH; alocação completa de polos é impossível.",
                parameters={"uncontrollable_modes": complex_to_pair(np.asarray(pbh["uncontrollable_modes"]))},
                next_step="Verifique atuadores ou limite o projeto ao subespaço controlável.",
            )

        svd_B = safe_svd_metrics(B_arr)
        rank_B = svd_B["rank"]
        max_mult = _max_pole_multiplicity(target_poles)
        used_alg = f"scipy.signal.place_poles.{method}"

        if max_mult > rank_B:
            if m == 1 and n <= 12:
                used_alg = "ackermann_siso"
                K_neg, ctrb_cond = _ackermann_siso(A_arr, B_arr, target_poles)
                diagnostics["ctrb_cond"] = ctrb_cond
                if n > 6 or (ctrb_cond is not None and ctrb_cond > 1e8):
                    warnings_out.append(
                        WarningItem(
                            code="ACKERMANN_CONDITIONING",
                            message=(
                                "Polos repetidos em SISO resolvidos via fórmula de Ackermann "
                                f"(n={n}, cond_ctrb={ctrb_cond})."
                            ),
                            details={"n": n, "ctrb_cond": ctrb_cond},
                        )
                    )
            else:
                raise HypothesisViolatedError(
                    message=(
                        f"Multiplicidade de polo ({max_mult}) excede posto(B)={rank_B}; "
                        "scipy.signal.place_poles não suporta multiplicidade > rank(B) em MIMO."
                    ),
                    parameters={"max_multiplicity": max_mult, "rank_B": rank_B},
                )
        else:
            placed = scipy.signal.place_poles(A_arr, B_arr, target_poles, method=method)
            K_neg = np.asarray(placed.gain_matrix, dtype=np.float64)

        if not np.all(np.isfinite(K_neg)):
            raise NumericalInconclusiveError("Ganho de alocação de polos contém NaN/Inf.")

        Acl = A_arr - B_arr @ K_neg
        achieved_eigs = sort_complex_eigs(np.linalg.eigvals(Acl))
        pole_err = match_poles_error(achieved_eigs, target_poles)
        scale_p = max(1.0, float(np.max(np.abs(target_poles))))

        diagnostics["pole_placement_error"] = pole_err
        diagnostics["K_norm_fro"] = float(np.linalg.norm(K_neg, "fro"))

        if pole_err > 1e-4 * scale_p:
            raise NumericalInconclusiveError(
                message=f"Erro na alocação de polos excedeu tolerância: max|lam - target|={pole_err:.3e}.",
                parameters={"pole_placement_error": pole_err, "scale": scale_p},
            )
        if pole_err > 1e-7 * scale_p:
            warnings_out.append(
                WarningItem(
                    code="POLE_PLACEMENT_MODERATE_ERROR",
                    message=f"Alocação de polos com erro numérico moderado: {pole_err:.3e}.",
                    details={"pole_placement_error": pole_err},
                )
            )

        K_ctrl = K_neg if sign_str == "negative" else -K_neg
        prov_ok = build_provenance(
            used_alg,
            model_revision=sys_info["model_revision"],
            feedback_sign=sign_str,
        )
        ctrl = StateFeedbackController(
            K=K_ctrl,
            feedback_sign=sign_str,
            state_coordinates=sys_info["state_names"],
            reference_map=reference_map,
            dt=resolved_dt,
            input_names=sys_info["input_names"],
            provenance=prov_ok.to_dict(),
        )

        data: dict[str, Any] = {
            "controller": ctrl.to_dict(),
            "controller_ref": {"id": ctrl.id, "revision": ctrl.revision},
            "controller_kind": ctrl.kind,
            "feedback_sign": sign_str,
            "K": K_ctrl,
            "desired_poles": complex_to_pair(sort_complex_eigs(target_poles)),
            "closed_loop_poles": complex_to_pair(achieved_eigs),
        }
        if ss_plant is not None:
            data["closed_loop"] = interconnect(ss_plant, ctrl, sign_convention=sign_str).to_dict()

        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov_ok,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )
    except (ValueError, np.linalg.LinAlgError) as exc:
        err = NumericalInconclusiveError(f"Falha numérica na alocação de polos: {exc}")
        return handle_failure(
            err,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def design_observer(
    plant_or_A: Any,
    C_or_poles: Any = None,
    poles: Any = None,
    *,
    method: str = "YT",
    dt: float | None = None,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Sintetiza observador de Luenberger por dualidade: eig(A - L C) = poles."""
    dt_provided = dt is not None
    prov: Provenance = build_provenance(
        "statespace.design_observer",
        model_revision=getattr(plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if method not in ("YT", "KNV0"):
            raise ValidationError(f"method inválido em design_observer: {method!r}. Use 'YT' ou 'KNV0'.")

        sys_info, raw_poles = _resolve_placement_inputs(
            plant_or_A, C_or_poles, poles, dt=dt, dt_provided=dt_provided, second_label="C"
        )
        A_arr: np.ndarray = sys_info["A"]
        C_arr: np.ndarray = sys_info["C"]
        n: int = sys_info["n"]
        p: int = sys_info["p"]
        resolved_dt: float | None = sys_info["dt"]
        ss_plant: StateSpace | None = sys_info["plant"]

        if p < 1:
            raise DimensionMismatchError("Observador requer pelo menos 1 saída medida (p >= 1).")

        target_poles = validate_conjugate_poles(raw_poles, n)
        pbh = pbh_analysis_core(A_arr, C=C_arr, dt=resolved_dt, tol=tol)
        warnings_out.extend(pbh["warnings"])
        assumptions = {
            "domain": "continuous" if resolved_dt is None else "discrete",
            "dt": resolved_dt,
            "observable": bool(pbh["observable"]),
        }
        diagnostics = {
            "pbh_min_sv_observability": pbh["min_sv_observability"],
        }

        if not pbh["observable"]:
            raise HypothesisViolatedError(
                message="Par (A, C) não é observável pelo teste PBH; alocação completa de polos do observador é impossível.",
                parameters={"unobservable_modes": complex_to_pair(np.asarray(pbh["unobservable_modes"]))},
                next_step="Adicione sensores/saídas para tornar todos os modos observáveis.",
            )

        # Dualidade: (A - L C)^T = A^T - C^T L^T
        svd_C = safe_svd_metrics(C_arr)
        rank_C = svd_C["rank"]
        max_mult = _max_pole_multiplicity(target_poles)
        used_alg = f"dual.scipy.signal.place_poles.{method}"

        if max_mult > rank_C:
            if p == 1 and n <= 12:
                used_alg = "dual.ackermann_siso"
                K_dual, obsv_cond = _ackermann_siso(A_arr.T, C_arr.T, target_poles)
                diagnostics["obsv_cond"] = obsv_cond
                if n > 6 or (obsv_cond is not None and obsv_cond > 1e8):
                    warnings_out.append(
                        WarningItem(
                            code="OBSERVER_ACKERMANN_CONDITIONING",
                            message=f"Observador com polos repetidos via Ackermann dual (n={n}, cond={obsv_cond}).",
                            details={"n": n, "obsv_cond": obsv_cond},
                        )
                    )
            else:
                raise HypothesisViolatedError(
                    message=(
                        f"Multiplicidade de polo ({max_mult}) excede posto(C)={rank_C}; "
                        "alocação dual MIMO não suporta multiplicidade > rank(C)."
                    ),
                    parameters={"max_multiplicity": max_mult, "rank_C": rank_C},
                )
        else:
            placed = scipy.signal.place_poles(A_arr.T, C_arr.T, target_poles, method=method)
            K_dual = np.asarray(placed.gain_matrix, dtype=np.float64)

        L = np.array(K_dual.T, dtype=np.float64)
        if not np.all(np.isfinite(L)):
            raise NumericalInconclusiveError("Ganho de observador L contém NaN/Inf.")

        A_obs = A_arr - L @ C_arr
        achieved_eigs = sort_complex_eigs(np.linalg.eigvals(A_obs))
        pole_err = match_poles_error(achieved_eigs, target_poles)
        scale_p = max(1.0, float(np.max(np.abs(target_poles))))
        diagnostics["pole_placement_error"] = pole_err
        diagnostics["L_norm_fro"] = float(np.linalg.norm(L, "fro"))

        if pole_err > 1e-4 * scale_p:
            raise NumericalInconclusiveError(
                message=f"Erro na alocação de polos do observador excedeu tolerância: {pole_err:.3e}.",
                parameters={"pole_placement_error": pole_err},
            )
        if pole_err > 1e-7 * scale_p:
            warnings_out.append(
                WarningItem(
                    code="OBSERVER_POLE_MODERATE_ERROR",
                    message=f"Erro numérico moderado nos polos do observador: {pole_err:.3e}.",
                    details={"pole_placement_error": pole_err},
                )
            )

        data: dict[str, Any] = {
            "L": L,
            "observer_error_matrix": A_obs,
            "desired_poles": complex_to_pair(sort_complex_eigs(target_poles)),
            "observer_poles": complex_to_pair(achieved_eigs),
        }
        if ss_plant is not None:
            B_arr: np.ndarray = sys_info["B"]
            D_arr: np.ndarray = sys_info["D"]
            m: int = sys_info["m"]
            obs_ss = StateSpace(
                A=A_obs,
                B=np.hstack([B_arr - L @ D_arr, L]),
                C=np.eye(n, dtype=np.float64),
                D=np.zeros((n, m + p), dtype=np.float64),
                dt=resolved_dt,
                state_names=[f"{sn}_hat" for sn in ss_plant.state_names],
                input_names=list(ss_plant.input_names) + list(ss_plant.output_names),
                output_names=[f"{sn}_hat" for sn in ss_plant.state_names],
                provenance={"source": "design_observer", "plant_id": ss_plant.id},
            )
            data["observer_system"] = obs_ss.to_dict()

        prov_ok = build_provenance(used_alg, model_revision=sys_info["model_revision"])
        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov_ok,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )
    except (ValueError, np.linalg.LinAlgError) as exc:
        err = NumericalInconclusiveError(f"Falha numérica na síntese do observador: {exc}")
        return handle_failure(
            err,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def _resolve_kalman_inputs(
    plant_or_A: Any,
    Qn_or_C: Any,
    Rn_or_Qn: Any,
    Rn_mat: Any,
    *,
    plant: StateSpace | None,
    A: Any,
    C: Any,
    Qn: Any,
    Rn: Any,
    dt: float | None,
    dt_provided: bool,
) -> dict[str, Any]:
    if plant is not None:
        if plant_or_A is not None:
            raise ValidationError("Não forneça 'plant' posicional e keyword simultaneamente.")
        if A is not None or C is not None or Rn_mat is not None:
            raise ValidationError("Não misture 'plant' com matrizes A/C extras.")
        sys_info = resolve_state_space_inputs(
            plant, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
        )
        Qn_val = Qn if Qn is not None else Qn_or_C
        Rn_val = Rn if Rn is not None else Rn_or_Qn
        return {**sys_info, "Qn_raw": Qn_val, "Rn_raw": Rn_val}

    if isinstance(plant_or_A, StateSpace):
        if A is not None or C is not None or Rn_mat is not None:
            raise ValidationError("Não misture objeto StateSpace com A/C extras.")
        sys_info = resolve_state_space_inputs(
            plant_or_A, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
        )
        Qn_val = Qn if Qn is not None else Qn_or_C
        Rn_val = Rn if Rn is not None else Rn_or_Qn
        return {**sys_info, "Qn_raw": Qn_val, "Rn_raw": Rn_val}

    if hasattr(plant_or_A, "kind") and not isinstance(plant_or_A, (np.ndarray, list, tuple)):
        raise UnsupportedModelError(
            f"Tipo de modelo {type(plant_or_A).__name__} não suportado em design_kalman; use StateSpace."
        )

    A_val = A if A is not None else plant_or_A
    C_val = C if C is not None else Qn_or_C
    Qn_val = Qn if Qn is not None else Rn_or_Qn
    Rn_val = Rn if Rn is not None else Rn_mat
    if A_val is None or C_val is None or Qn_val is None or Rn_val is None:
        raise ValidationError("Chamada matricial de design_kalman requer A, C, Qn e Rn.")
    sys_info = resolve_state_space_inputs(
        A_val, C=C_val, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
    )
    return {**sys_info, "Qn_raw": Qn_val, "Rn_raw": Rn_val}


def design_kalman(
    plant_or_A: Any = None,
    Qn_or_C: Any = None,
    Rn_or_Qn: Any = None,
    Rn_mat: Any = None,
    *,
    plant: StateSpace | None = None,
    A: Any = None,
    C: Any = None,
    Qn: Any = None,
    Rn: Any = None,
    G: Any = None,
    dt: float | None = _UNSET,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Sintetiza filtro de Kalman estacionário contínuo (CARE dual) ou discreto (DARE dual)."""
    dt_provided = dt is not _UNSET
    resolved_dt_arg = None if dt is _UNSET else dt
    prov: Provenance = build_provenance(
        "statespace.design_kalman",
        model_revision=getattr(plant if plant is not None else plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        info = _resolve_kalman_inputs(
            plant_or_A,
            Qn_or_C,
            Rn_or_Qn,
            Rn_mat,
            plant=plant,
            A=A,
            C=C,
            Qn=Qn,
            Rn=Rn,
            dt=resolved_dt_arg,
            dt_provided=dt_provided,
        )
        A_arr: np.ndarray = info["A"]
        C_arr: np.ndarray = info["C"]
        n: int = info["n"]
        p: int = info["p"]
        resolved_dt: float | None = info["dt"]
        ss_plant: StateSpace | None = info["plant"]
        domain = "continuous" if resolved_dt is None else "discrete"

        if p < 1:
            raise DimensionMismatchError("Filtro de Kalman requer ao menos 1 saída medida (p >= 1).")
        if info["Qn_raw"] is None or info["Rn_raw"] is None:
            raise ValidationError("Matrizes Qn e Rn são obrigatórias para design_kalman.")

        if G is None:
            G_arr = np.eye(n, dtype=np.float64)
            nw = n
        else:
            G_arr = ensure_finite_float64(G, ndim=2, name="G")
            if G_arr.shape[0] != n or G_arr.shape[1] < 1:
                raise DimensionMismatchError(
                    f"Matriz G tem shape {G_arr.shape}, esperado ({n}, nw >= 1)."
                )
            nw = G_arr.shape[1]

        Qn_sym, Qn_factor, eigs_Qn, _, qn_sym_err, qn_warns = validate_symmetric_psd(
            info["Qn_raw"], "Qn", expected_n=nw
        )
        Rn_sym, cho_Rn, eigs_Rn, rn_sym_err, cond_Rn, rn_warns = validate_symmetric_pd(
            info["Rn_raw"], "Rn", expected_n=p
        )
        warnings_out.extend(qn_warns)
        warnings_out.extend(rn_warns)

        Q_dual = G_arr @ Qn_sym @ G_arr.T
        Q_dual = 0.5 * (Q_dual + Q_dual.T)
        # Fator do ruído de processo na planta: B_noise = G @ Qn_factor^T (B_noise @ B_noise^T == Q_dual)
        B_noise = G_arr @ Qn_factor.T

        # Dualidade: detectabilidade de (A, C) e estabilizabilidade de (A, G Qn^{1/2})
        pbh = pbh_analysis_core(A_arr, B=B_noise, C=C_arr, dt=resolved_dt, tol=tol)
        warnings_out.extend(pbh["warnings"])

        assumptions = {
            "domain": domain,
            "dt": resolved_dt,
            "detectable": bool(pbh["detectable"]),
            "observable": bool(pbh["observable"]),
            "process_noise_stabilizable": bool(pbh["stabilizable"]),
            "Qn_positive_semidefinite": True,
            "Rn_positive_definite": True,
        }
        diagnostics = {
            "pbh_min_sv_detectability": pbh["min_sv_detectability"],
            "pbh_min_sv_noise_stabilizability": pbh["min_sv_stabilizability"],
            "Qn_symmetry_error": qn_sym_err,
            "Rn_symmetry_error": rn_sym_err,
            "min_eig_Qn": float(np.min(eigs_Qn)),
            "min_eig_Rn": float(np.min(eigs_Rn)),
            "cond_Rn": cond_Rn,
        }

        if not pbh["detectable"]:
            raise HypothesisViolatedError(
                message="Par (A, C) não é detectável pelo teste PBH para o filtro de Kalman.",
                parameters={"undetectable_modes": complex_to_pair(np.asarray(pbh["undetectable_modes"]))},
                next_step="Torne os modos instáveis ou marginais observáveis em C.",
            )
        if not pbh["stabilizable"]:
            raise HypothesisViolatedError(
                message="Par (A, G Qn^{1/2}) não é estabilizável pelo teste PBH.",
                parameters={"unstabilizable_modes": complex_to_pair(np.asarray(pbh["unstabilizable_modes"]))},
                next_step="Ajuste G ou Qn para excitar modos instáveis/marginais.",
            )

        if domain == "continuous":
            alg_id = "kalman.scipy.linalg.solve_continuous_are"
            P_raw = scipy.linalg.solve_continuous_are(A_arr.T, C_arr.T, Q_dual, Rn_sym)
        else:
            alg_id = "kalman.scipy.linalg.solve_discrete_are"
            P_raw = scipy.linalg.solve_discrete_are(A_arr.T, C_arr.T, Q_dual, Rn_sym)

        if not np.all(np.isfinite(P_raw)):
            raise NumericalInconclusiveError("Solver dual do filtro de Kalman retornou NaN/Inf.")

        raw_sym_err = symmetry_error_rel(P_raw)
        if raw_sym_err > 1e-6:
            raise NumericalInconclusiveError(
                f"Covariância P_e do filtro de Kalman perdeu simetria ({raw_sym_err:.3e})."
            )
        P_e = 0.5 * (P_raw + P_raw.T)

        eigs_P = np.linalg.eigvalsh(P_e)
        min_eig_P = float(np.min(eigs_P))
        p_tol = max(1e-10, n * 1e-11 * max(1.0, float(np.max(np.abs(eigs_P)))))
        if min_eig_P < -p_tol:
            raise NumericalInconclusiveError(
                f"Covariância P_e não é semidefinida positiva (min_eig={min_eig_P:.3e})."
            )

        # Recuperação de ganho L sem inv explícita
        if domain == "continuous":
            K_dual = scipy.linalg.cho_solve(cho_Rn, C_arr @ P_e)
            L = np.array(K_dual.T, dtype=np.float64)
            r_res = care_residual_rel(A_arr.T, C_arr.T, Q_dual, Rn_sym, P_e, K_lqr=K_dual)
        else:
            S_raw = Rn_sym + C_arr @ P_e @ C_arr.T
            S_innov = 0.5 * (S_raw + S_raw.T)
            cho_S = scipy.linalg.cho_factor(S_innov, lower=True, check_finite=True)
            K_dual = scipy.linalg.cho_solve(cho_S, C_arr @ P_e @ A_arr.T)
            L = np.array(K_dual.T, dtype=np.float64)
            r_res = dare_residual_rel(A_arr.T, C_arr.T, Q_dual, Rn_sym, P_e, K_lqr=K_dual)

        A_obs = A_arr - L @ C_arr
        obs_eigs = sort_complex_eigs(np.linalg.eigvals(A_obs))

        if domain == "continuous":
            max_real_obs = float(np.max(np.real(obs_eigs)))
            is_stable_obs = max_real_obs < 0.0
            diagnostics["care_residual_rel"] = r_res
            diagnostics["max_real_observer"] = max_real_obs
        else:
            rho_obs = float(np.max(np.abs(obs_eigs)))
            is_stable_obs = rho_obs < 1.0
            diagnostics["dare_residual_rel"] = r_res
            diagnostics["spectral_radius_observer"] = rho_obs

        diagnostics["residual_rel"] = r_res
        diagnostics["symmetry_error"] = raw_sym_err
        diagnostics["min_eig_P"] = min_eig_P
        assumptions["observer_stable"] = is_stable_obs

        if not is_stable_obs:
            raise NumericalInconclusiveError("Dinâmica de erro do filtro de Kalman (A - L C) não resultou estável.")

        if r_res > 1e-4:
            raise NumericalInconclusiveError(f"Resíduo Riccati do filtro de Kalman excessivo: {r_res:.3e}.")
        if r_res > 1e-9:
            warnings_out.append(
                WarningItem(
                    code="HIGH_KALMAN_RICCATI_RESIDUAL",
                    message=f"Resíduo Riccati do filtro de Kalman elevado: {r_res:.3e}.",
                    details={"residual_rel": r_res},
                )
            )

        data: dict[str, Any] = {
            "L": L,
            "P": P_e,
            "observer_error_matrix": A_obs,
            "observer_poles": complex_to_pair(obs_eigs),
        }
        if ss_plant is not None:
            B_arr: np.ndarray = info["B"]
            D_arr: np.ndarray = info["D"]
            m: int = info["m"]
            kf_ss = StateSpace(
                A=A_obs,
                B=np.hstack([B_arr - L @ D_arr, L]),
                C=np.eye(n, dtype=np.float64),
                D=np.zeros((n, m + p), dtype=np.float64),
                dt=resolved_dt,
                state_names=[f"{sn}_hat" for sn in ss_plant.state_names],
                input_names=list(ss_plant.input_names) + list(ss_plant.output_names),
                output_names=[f"{sn}_hat" for sn in ss_plant.state_names],
                provenance={"source": "design_kalman", "plant_id": ss_plant.id},
            )
            data["observer_system"] = kf_ss.to_dict()

        prov_ok = build_provenance(
            alg_id,
            tolerances={"residual_warn_tol": 1e-9, "symmetry_tol": DEFAULT_SYMMETRY_TOL},
            model_revision=info["model_revision"],
        )
        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov_ok,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )
    except (np.linalg.LinAlgError, ValueError) as exc:
        err = NumericalInconclusiveError(f"Falha numérica em design_kalman: {exc}")
        return handle_failure(
            err,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def design_lqg(
    plant: StateSpace,
    Q: Any,
    R: Any,
    Qn: Any,
    Rn: Any,
    *,
    G: Any = None,
    feedback_sign: str = "negative",
    initial_state: Any = None,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Sintetiza controlador LQG (LQR + Kalman) retornando DynamicController interoperável com interconnect."""
    prov: Provenance = build_provenance(
        "statespace.design_lqg",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(plant, StateSpace):
            raise UnsupportedModelError(
                message=f"design_lqg requer instância StateSpace, recebido {type(plant).__name__}.",
                parameters={"plant_type": type(plant).__name__},
            )
        if plant.n_states < 1 or plant.n_inputs < 1 or plant.n_outputs < 1:
            raise DimensionMismatchError(
                message="design_lqg requer StateSpace com n >= 1, m >= 1 e p >= 1.",
                parameters={"n": plant.n_states, "m": plant.n_inputs, "p": plant.n_outputs},
            )

        sign_str = _validate_feedback_sign(feedback_sign)
        n, m, p = plant.n_states, plant.n_inputs, plant.n_outputs
        domain = "continuous" if plant.dt is None else "discrete"

        lqr_res = design_lqr(
            plant,
            Q,
            R,
            feedback_sign=sign_str,
            tol=tol,
            raise_on_error=True,
        )
        assert lqr_res.data is not None

        kf_res = design_kalman(
            plant,
            Qn,
            Rn,
            G=G,
            tol=tol,
            raise_on_error=True,
        )
        assert kf_res.data is not None

        K_lqr = tensor_to_array(lqr_res.data["K_lqr"], expected_ndim=2, dtype="float64")
        P_lqr = tensor_to_array(lqr_res.data["P"], expected_ndim=2, dtype="float64")
        L_kf = tensor_to_array(kf_res.data["L"], expected_ndim=2, dtype="float64")
        P_kf = tensor_to_array(kf_res.data["P"], expected_ndim=2, dtype="float64")

        # Construção de DynamicController compatível com interconnect(scheme="observer_based"):
        # Em interconnect: u = r + s * (Cc x_hat + Dc y), x_hat_dot = Ac x_hat + Bc y
        # Com Dc = 0, s * Cc = -K_lqr, Bc = L_kf, Ac = A - L_kf C - (B - L_kf D) K_lqr:
        # A_cl = [[A, -B K_lqr], [L_kf C, A - L_kf C - B K_lqr]] -> princípio da separação exato!
        Ac = plant.A - L_kf @ plant.C - (plant.B - L_kf @ plant.D) @ K_lqr
        Bc = L_kf
        Cc = K_lqr if sign_str == "negative" else -K_lqr
        Dc = np.zeros((m, p), dtype=np.float64)

        prov_ok = build_provenance(
            "statespace.design_lqg",
            tolerances=lqr_res.provenance.tolerances,
            model_revision=plant.revision,
            feedback_sign=sign_str,
            domain=domain,
        )
        ctrl = DynamicController(
            Ac=Ac,
            Bc=Bc,
            Cc=Cc,
            Dc=Dc,
            feedback_sign=sign_str,
            ports={
                "inputs": [{"name": "y", "role": "y", "size": p}],
                "outputs": [{"name": "u", "role": "u", "size": m}],
            },
            interconnection_scheme="observer_based",
            initial_state=initial_state,
            dt=plant.dt,
            state_names=[f"{sn}_hat" for sn in plant.state_names],
            provenance=prov_ok.to_dict(),
        )

        cl_ss = interconnect(plant, ctrl, sign_convention=sign_str)
        eigs_reg = sort_complex_eigs(np.linalg.eigvals(plant.A - plant.B @ K_lqr))
        eigs_obs = sort_complex_eigs(np.linalg.eigvals(plant.A - L_kf @ plant.C))
        eigs_cl = sort_complex_eigs(np.linalg.eigvals(cl_ss.A))
        sep_err = match_poles_error(eigs_cl, np.concatenate([eigs_reg, eigs_obs]))

        if domain == "continuous":
            cl_stable = bool(np.max(np.real(eigs_cl)) < 0.0)
        else:
            cl_stable = bool(np.max(np.abs(eigs_cl)) < 1.0)

        warnings_out = _merge_warnings(lqr_res.warnings, kf_res.warnings)
        if not cl_stable:
            raise NumericalInconclusiveError("Malha fechada LQG não resultou estável pelo critério espectral.")

        assumptions = {
            "domain": domain,
            "dt": plant.dt,
            "feedback_sign": sign_str,
            "stabilizable": lqr_res.assumptions["stabilizable"],
            "detectable_Q": lqr_res.assumptions["detectable"],
            "detectable_C": kf_res.assumptions["detectable"],
            "process_noise_stabilizable": kf_res.assumptions["process_noise_stabilizable"],
            "R_positive_definite": True,
            "Rn_positive_definite": True,
            "closed_loop_stable": cl_stable,
            "separation_principle_verified": sep_err <= 1e-7 * max(1.0, float(np.max(np.abs(eigs_cl)))),
        }
        diagnostics = {
            "lqr": lqr_res.diagnostics,
            "kalman": kf_res.diagnostics,
            "separation_pole_diff": sep_err,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "controller": ctrl.to_dict(),
                "controller_ref": {"id": ctrl.id, "revision": ctrl.revision},
                "controller_kind": ctrl.kind,
                "feedback_sign": sign_str,
                "K_lqr": K_lqr,
                "L_kalman": L_kf,
                "P_lqr": P_lqr,
                "P_kalman": P_kf,
                "closed_loop": cl_ss.to_dict(),
                "regulator_poles": complex_to_pair(eigs_reg),
                "observer_poles": complex_to_pair(eigs_obs),
                "closed_loop_poles": complex_to_pair(eigs_cl),
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov_ok,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )
