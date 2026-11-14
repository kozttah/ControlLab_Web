"""Síntese de compensadores SISO (Avanço, Atraso, Avanço-Atraso, PID/PI/PD) e overlays semânticos (Seção 5.3 e R-07)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from control_lab.core.controllers import DynamicController, _validate_feedback_sign
from control_lab.core.interconnect import interconnect
from control_lab.core.models import StateSpace, TransferFunction
from control_lab.diagnostics import (
    ControlLabError,
    HypothesisViolatedError,
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from ._utils import (
    compute_poles_zeros_gain,
    eval_siso_Clean_phase_and_mag,
    extract_siso_tf_channel,
    handle_failure,
)
from .margins import stability_margins

REQUIREMENT_CLASSIFICATIONS: tuple[str, ...] = ("exact", "sufficient", "heuristic", "estimated")


def _tf_to_dynamic_controller(
    tf_ctrl: TransferFunction,
    *,
    feedback_sign: str = "negative",
    interconnection_scheme: str = "error_feedback",
    provenance: Provenance | dict[str, Any] | None = None,
) -> DynamicController:
    """Converte TransferFunction própria 1x1 em DynamicController canônico (ADR-005)."""
    ss_c = tf_ctrl.to_state_space()
    ports = {
        "inputs": [{"name": "e" if interconnection_scheme == "error_feedback" else "y", "role": "error" if interconnection_scheme == "error_feedback" else "y", "size": 1}],
        "outputs": [{"name": "u", "role": "u", "size": 1}],
    }
    return DynamicController(
        Ac=ss_c.A,
        Bc=ss_c.B,
        Cc=ss_c.C,
        Dc=ss_c.D,
        feedback_sign=feedback_sign,
        ports=ports,
        interconnection_scheme=interconnection_scheme,
        dt=tf_ctrl.dt,
        provenance=provenance if provenance is not None else tf_ctrl.provenance,
    )


def _series_tf(tf1: TransferFunction, tf2: TransferFunction) -> TransferFunction:
    """Produto em série C(s)*G(s) para sistemas SISO compatíveis."""
    n1, d1 = tf1._channel_descending_z_or_s(0, 0)
    n2, d2 = tf2._channel_descending_z_or_s(0, 0)
    num_prod = np.polymul(n1, n2)
    den_prod = np.polymul(d1, d2)
    return TransferFunction(
        num=num_prod,
        den=den_prod,
        dt=tf1.dt,
        variable="s" if tf1.dt is None else "z",
        poly_order="descending",
    )


def classify_requirement_overlays(
    *,
    max_real_part: float | None = None,
    min_damping_ratio: float | None = None,
    min_natural_freq: float | None = None,
    max_overshoot_pct: float | None = None,
    max_settling_time: float | None = None,
    settling_threshold: float = 0.02,
    plant: Any = None,
    controller: Any = None,
    raise_on_error: bool = False,
) -> Result:
    """Classifica overlays de requisitos SISO honestamente como exact, sufficient, heuristic ou estimated (Seção 5.3 / R-07).

    Regra científica obrigatória (Seção 5.3):
    - `Re(lambda) < -alpha` é classificado como `exact` (requisito espectral exato para polos de malha fechada).
    - Relações entre `zeta`, `omega_n`, sobressinal (`Mp`) e tempo de acomodação (`ts`) decorrentes de
      aproximação de 2ª ordem dominante NUNCA são prometidas como garantias exatas para sistemas de
      ordem superior (> 2) ou com zeros finitos próximos; são classificadas como `heuristic` ou `estimated`.
    """
    prov = build_provenance("frequency.siso.classify_requirement_overlays")
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        closed_loop_order = 2
        has_finite_zeros = False
        is_purely_second_order_no_zeros = False

        if plant is not None:
            ch_p = extract_siso_tf_channel(plant, require_strictly_siso=True)
            num_cl, den_cl = ch_p["num"], ch_p["den"]
            if controller is not None:
                ch_c = extract_siso_tf_channel(controller, require_strictly_siso=True)
                num_l = np.polymul(ch_c["num"], num_cl)
                den_l = np.polymul(ch_c["den"], den_cl)
                max_len = max(num_l.size, den_l.size)
                cl_den = np.trim_zeros(
                    np.pad(den_l, (max_len - den_l.size, 0)) + np.pad(num_l, (max_len - num_l.size, 0)),
                    "f",
                )
                cl_num = np.trim_zeros(num_l, "f")
            else:
                cl_num, cl_den = num_cl, den_cl
            pzk = compute_poles_zeros_gain(cl_num, cl_den)
            closed_loop_order = int(pzk["poles"].size)
            has_finite_zeros = int(pzk["zeros"].size) > 0
            is_purely_second_order_no_zeros = closed_loop_order == 2 and not has_finite_zeros
        else:
            is_purely_second_order_no_zeros = False

        overlays: list[dict[str, Any]] = []

        # 1. Requisito espectral Re(lambda) < -alpha -> SEMPRE exact
        if max_real_part is not None:
            mr = float(max_real_part)
            if not math.isfinite(mr):
                raise ValidationError("max_real_part deve ser finito.")
            alpha = -mr
            overlays.append(
                {
                    "id": "spectral_decay_abscissa",
                    "parameter": "max_real_part",
                    "target_value": mr,
                    "alpha": alpha,
                    "region_equation": f"Re(lambda) < {mr:.6g}",
                    "classification": "exact",
                    "rationale": (
                        "Requisito espectral exato sobre a abscissa de estabilidade/taxa de decaimento "
                        "modal dos polos de malha fechada (Seção 5.3)."
                    ),
                }
            )

        # 2. Sobressinal Mp -> amortecimento zeta (aproximação de 2ª ordem dominante)
        derived_zeta = min_damping_ratio
        if max_overshoot_pct is not None:
            mp = float(max_overshoot_pct)
            if not (math.isfinite(mp) and 0.0 < mp < 100.0):
                raise ValidationError("max_overshoot_pct deve estar em (0, 100).")
            ln_mp = math.log(mp / 100.0)
            zeta_from_mp = -ln_mp / math.sqrt(math.pi**2 + ln_mp**2)
            derived_zeta = max(float(derived_zeta), zeta_from_mp) if derived_zeta is not None else zeta_from_mp
            cls_mp = "sufficient" if is_purely_second_order_no_zeros else "heuristic"
            overlays.append(
                {
                    "id": "overshoot_to_damping_cone",
                    "parameter": "max_overshoot_pct",
                    "target_value": mp,
                    "mapped_min_zeta": zeta_from_mp,
                    "sector_half_angle_deg": math.degrees(math.acos(min(1.0, max(0.0, zeta_from_mp)))),
                    "classification": cls_mp,
                    "rationale": (
                        "Mapeamento Mp -> zeta derivado da fórmula de 2ª ordem padrão sem zeros; "
                        "em ordem superior ou na presença de zeros próximos é apenas heurístico e deve ser "
                        "verificado na simulação temporal efetiva (Seção 5.3)."
                    ),
                }
            )
            if not is_purely_second_order_no_zeros:
                warnings_out.append(
                    WarningItem(
                        code="SECOND_ORDER_DOMINANCE_HEURISTIC",
                        message=(
                            "Relação entre sobressinal (Mp) e amortecimento (zeta) usa aproximação de 2ª ordem "
                            "dominante (classification='heuristic'); não é garantia exata para este sistema."
                        ),
                        details={"closed_loop_order": closed_loop_order, "has_finite_zeros": has_finite_zeros},
                    )
                )

        if min_damping_ratio is not None:
            z_val = float(min_damping_ratio)
            if not (math.isfinite(z_val) and 0.0 <= z_val <= 1.0):
                raise ValidationError("min_damping_ratio deve estar em [0, 1].")
            overlays.append(
                {
                    "id": "damping_ratio_sector",
                    "parameter": "min_damping_ratio",
                    "target_value": z_val,
                    "sector_half_angle_deg": math.degrees(math.acos(z_val)),
                    "classification": "exact",
                    "rationale": "Restrição geométrica cônica exata sobre o amortecimento modal dos polos complexos.",
                }
            )

        # 3. Tempo de acomodação ts -> sigma = 4 / ts (estimated/heuristic)
        if max_settling_time is not None:
            ts_val = float(max_settling_time)
            if not (math.isfinite(ts_val) and ts_val > 0.0):
                raise ValidationError("max_settling_time deve ser finito > 0.")
            factor = -math.log(settling_threshold) if 0.0 < settling_threshold < 1.0 else 4.0
            sigma_est = factor / ts_val
            overlays.append(
                {
                    "id": "settling_time_abscissa_estimate",
                    "parameter": "max_settling_time",
                    "target_value": ts_val,
                    "mapped_alpha": sigma_est,
                    "region_equation": f"Re(lambda) < -{sigma_est:.6g}",
                    "classification": "estimated",
                    "rationale": (
                        "Estimativa de abscissa Re(lambda) < -ln(tol)/ts baseada em envelope exponencial "
                        "de 2ª ordem; resíduos modais, zeros e múltiplos polos alteram o tempo de acomodação real."
                    ),
                }
            )

        # 4. Frequência natural mínima omega_n
        if min_natural_freq is not None:
            wn_val = float(min_natural_freq)
            if not (math.isfinite(wn_val) and wn_val > 0.0):
                raise ValidationError("min_natural_freq deve ser finito > 0.")
            overlays.append(
                {
                    "id": "natural_frequency_radius",
                    "parameter": "min_natural_freq",
                    "target_value": wn_val,
                    "region_equation": f"|lambda| >= {wn_val:.6g}",
                    "classification": "exact",
                    "rationale": "Restrição espectral exata sobre o módulo mínimo dos polos |lambda| >= omega_n.",
                }
            )

        assumptions = {
            "closed_loop_order": closed_loop_order,
            "has_finite_zeros": has_finite_zeros,
            "second_order_dominance_assumed_exact": False,
        }
        diagnostics = {
            "n_overlays": len(overlays),
            "classifications": {ov["id"]: ov["classification"] for ov in overlays},
            "derived_min_zeta": derived_zeta,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "overlays": overlays,
                "allowed_classifications": list(REQUIREMENT_CLASSIFICATIONS),
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
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


def design_lead(
    plant: Any,
    *,
    target_phase_margin_deg: float = 50.0,
    target_omega_gc: float | None = None,
    dc_gain_boost: float = 1.0,
    safety_margin_deg: float = 5.0,
    feedback_sign: str = "negative",
    raise_on_error: bool = False,
) -> Result:
    """Projeta compensador de avanço de fase C(s) = Kc * (T s + 1) / (alpha T s + 1), 0 < alpha < 1."""
    prov = build_provenance("frequency.siso.design_lead", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sign_str = _validate_feedback_sign(feedback_sign)
        if not (isinstance(target_phase_margin_deg, (int, float)) and 0.0 < float(target_phase_margin_deg) < 90.0):
            raise ValidationError("target_phase_margin_deg deve estar em (0, 90) graus.")
        if not (isinstance(dc_gain_boost, (int, float)) and float(dc_gain_boost) > 0.0):
            raise ValidationError("dc_gain_boost deve ser > 0.")

        ch = extract_siso_tf_channel(plant, require_strictly_siso=True)
        if ch["dt"] is not None:
            raise ValidationError("design_lead analógico requer modelo contínuo (dt=None).")
        tf_plant = ch["tf"] if ch["tf"] is not None else TransferFunction.from_state_space(ch["ss"])

        # Margens antes da compensação (com ganho dc_gain_boost)
        num_g = float(dc_gain_boost) * ch["num"]
        den_g = ch["den"]
        tf_boosted = TransferFunction(num=num_g, den=den_g, dt=None)
        m_before_res = stability_margins(tf_boosted, raise_on_error=True)
        assert m_before_res.data is not None

        if target_omega_gc is not None:
            w_m = float(target_omega_gc)
            if w_m <= 0.0 or not math.isfinite(w_m):
                raise ValidationError("target_omega_gc deve ser finito > 0.")
            eval_wm = eval_siso_Clean_phase_and_mag(num_g, den_g, np.array([w_m], dtype=np.float64))
            ph_at_wm = float(eval_wm["phase_deg"][0])
            pm_current = ((180.0 + ph_at_wm) % 360.0)
            if pm_current > 180.0:
                pm_current -= 360.0
            phi_max_deg = float(target_phase_margin_deg) - pm_current + float(safety_margin_deg)
        else:
            pm_curr = m_before_res.data["critical_phase_margin_deg"]
            if pm_curr is None:
                pm_curr = 0.0
            phi_max_deg = float(target_phase_margin_deg) - float(pm_curr) + float(safety_margin_deg)

        phi_max_deg = max(5.0, min(65.0, phi_max_deg))
        if phi_max_deg >= 64.9:
            warnings_out.append(
                WarningItem(
                    code="LEAD_PHASE_CLAMPED",
                    message="Avanço de fase requerido excede ~65 graus para um único estágio; limitado a 65 graus.",
                    details={"phi_max_deg": phi_max_deg},
                )
            )

        sin_phi = math.sin(math.radians(phi_max_deg))
        alpha = (1.0 - sin_phi) / (1.0 + sin_phi)

        # Determina frequência w_m onde |G_boosted(jw_m)| = sqrt(alpha)
        if target_omega_gc is not None:
            w_m = float(target_omega_gc)
        else:
            target_db = 10.0 * math.log10(alpha)
            w_search = np.logspace(-3, 4, 2000, dtype=np.float64)
            ev = eval_siso_Clean_phase_and_mag(num_g, den_g, w_search)
            idx_m = int(np.argmin(np.abs(ev["mag_db"] - target_db)))
            w_m = float(w_search[idx_m])

        T_lead = 1.0 / (w_m * math.sqrt(alpha))
        eval_at_wm = eval_siso_Clean_phase_and_mag(ch["num"], ch["den"], np.array([w_m], dtype=np.float64))
        mag_g_wm = float(eval_at_wm["mag"][0])
        Kc = (math.sqrt(alpha) / mag_g_wm) if mag_g_wm > 1e-12 else float(dc_gain_boost)

        # C(s) = Kc * (T s + 1) / (alpha * T * s + 1)
        num_c = np.array([Kc * T_lead, Kc], dtype=np.float64)
        den_c = np.array([alpha * T_lead, 1.0], dtype=np.float64)
        tf_ctrl = TransferFunction(
            num=num_c,
            den=den_c,
            dt=None,
            provenance={"algorithm": "frequency.siso.design_lead", "alpha": alpha, "T": T_lead, "Kc": Kc},
        )
        dyn_ctrl = _tf_to_dynamic_controller(tf_ctrl, feedback_sign=sign_str)

        loop_after = _series_tf(tf_ctrl, tf_plant)
        m_after_res = stability_margins(loop_after, raise_on_error=True)
        assert m_after_res.data is not None

        ss_plant = ch["ss"] if ch["ss"] is not None else tf_plant.to_state_space()
        cl_ss = interconnect(ss_plant, dyn_ctrl, sign_convention=sign_str)

        assumptions = {
            "compensator_type": "lead",
            "alpha": alpha,
            "T": T_lead,
            "Kc": Kc,
            "feedback_sign": sign_str,
        }
        diagnostics = {
            "phi_max_deg": phi_max_deg,
            "alpha": alpha,
            "T": T_lead,
            "Kc": Kc,
            "zero": -1.0 / T_lead,
            "pole": -1.0 / (alpha * T_lead),
            "omega_m": w_m,
            "phase_margin_before_deg": m_before_res.data["critical_phase_margin_deg"],
            "phase_margin_after_deg": m_after_res.data["critical_phase_margin_deg"],
            "omega_gc_after": m_after_res.data["critical_omega_gc"],
            "closed_loop_stable": m_after_res.data["closed_loop_stable"],
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "controller": dyn_ctrl.to_dict(),
                "controller_tf": tf_ctrl.to_dict(),
                "controller_ref": {"id": dyn_ctrl.id, "revision": dyn_ctrl.revision},
                "controller_kind": dyn_ctrl.kind,
                "parameters": {"Kc": Kc, "T": T_lead, "alpha": alpha, "zero": -1.0 / T_lead, "pole": -1.0 / (alpha * T_lead)},
                "margins_before": m_before_res.data,
                "margins_after": m_after_res.data,
                "closed_loop": cl_ss.to_dict(),
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
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


def design_lag(
    plant: Any,
    *,
    target_phase_margin_deg: float = 50.0,
    dc_gain_boost: float = 5.0,
    safety_margin_deg: float = 8.0,
    zero_decade_offset: float = 0.1,
    feedback_sign: str = "negative",
    raise_on_error: bool = False,
) -> Result:
    """Projeta compensador de atraso de fase C(s) = Kc * (T s + 1) / (beta T s + 1), beta > 1."""
    prov = build_provenance("frequency.siso.design_lag", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sign_str = _validate_feedback_sign(feedback_sign)
        if not (isinstance(target_phase_margin_deg, (int, float)) and 0.0 < float(target_phase_margin_deg) < 180.0):
            raise ValidationError("target_phase_margin_deg deve estar em (0, 180) graus.")
        if not (isinstance(dc_gain_boost, (int, float)) and float(dc_gain_boost) > 0.0):
            raise ValidationError("dc_gain_boost deve ser > 0.")

        ch = extract_siso_tf_channel(plant, require_strictly_siso=True)
        if ch["dt"] is not None:
            raise ValidationError("design_lag analógico requer modelo contínuo (dt=None).")
        tf_plant = ch["tf"] if ch["tf"] is not None else TransferFunction.from_state_space(ch["ss"])

        m_before_res = stability_margins(tf_plant, raise_on_error=True)
        assert m_before_res.data is not None

        num_boost = float(dc_gain_boost) * ch["num"]
        den_boost = ch["den"]
        w_search = np.logspace(-3, 4, 2500, dtype=np.float64)
        ev = eval_siso_Clean_phase_and_mag(num_boost, den_boost, w_search)
        target_ph = -180.0 + float(target_phase_margin_deg) + float(safety_margin_deg)
        idx_gc = int(np.argmin(np.abs(ev["phase_deg"] - target_ph)))
        w_gc_new = float(w_search[idx_gc])
        mag_at_wgc = float(ev["mag"][idx_gc])

        beta = max(1.05, mag_at_wgc)
        w_zero = float(zero_decade_offset) * w_gc_new
        T_lag = 1.0 / max(1e-6, w_zero)
        Kc = float(dc_gain_boost)

        # C(s) = Kc * (T s + 1) / (beta * T * s + 1), ganho DC = Kc, ganho alta freq = Kc / beta
        num_c = np.array([Kc * T_lag, Kc], dtype=np.float64)
        den_c = np.array([beta * T_lag, 1.0], dtype=np.float64)
        tf_ctrl = TransferFunction(
            num=num_c,
            den=den_c,
            dt=None,
            provenance={"algorithm": "frequency.siso.design_lag", "beta": beta, "T": T_lag, "Kc": Kc},
        )
        dyn_ctrl = _tf_to_dynamic_controller(tf_ctrl, feedback_sign=sign_str)

        loop_after = _series_tf(tf_ctrl, tf_plant)
        m_after_res = stability_margins(loop_after, raise_on_error=True)
        assert m_after_res.data is not None

        ss_plant = ch["ss"] if ch["ss"] is not None else tf_plant.to_state_space()
        cl_ss = interconnect(ss_plant, dyn_ctrl, sign_convention=sign_str)

        assumptions = {
            "compensator_type": "lag",
            "beta": beta,
            "T": T_lag,
            "Kc": Kc,
            "feedback_sign": sign_str,
        }
        diagnostics = {
            "beta": beta,
            "T": T_lag,
            "Kc": Kc,
            "zero": -1.0 / T_lag,
            "pole": -1.0 / (beta * T_lag),
            "target_omega_gc": w_gc_new,
            "phase_margin_before_deg": m_before_res.data["critical_phase_margin_deg"],
            "phase_margin_after_deg": m_after_res.data["critical_phase_margin_deg"],
            "closed_loop_stable": m_after_res.data["closed_loop_stable"],
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "controller": dyn_ctrl.to_dict(),
                "controller_tf": tf_ctrl.to_dict(),
                "controller_ref": {"id": dyn_ctrl.id, "revision": dyn_ctrl.revision},
                "controller_kind": dyn_ctrl.kind,
                "parameters": {"Kc": Kc, "T": T_lag, "beta": beta, "zero": -1.0 / T_lag, "pole": -1.0 / (beta * T_lag)},
                "margins_before": m_before_res.data,
                "margins_after": m_after_res.data,
                "closed_loop": cl_ss.to_dict(),
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
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


def design_lead_lag(
    plant: Any,
    *,
    mode: str = "lead_lag",
    target_phase_margin_deg: float = 50.0,
    target_omega_gc: float | None = None,
    dc_gain_boost: float = 2.0,
    feedback_sign: str = "negative",
    raise_on_error: bool = False,
) -> Result:
    """Interface unificada de síntese de compensadores Avanço (`lead`), Atraso (`lag`) ou Avanço-Atraso (`lead_lag`)."""
    prov = build_provenance("frequency.siso.design_lead_lag", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        mode_norm = mode.lower().strip() if isinstance(mode, str) else ""
        if mode_norm == "lead":
            return design_lead(
                plant,
                target_phase_margin_deg=target_phase_margin_deg,
                target_omega_gc=target_omega_gc,
                dc_gain_boost=dc_gain_boost,
                feedback_sign=feedback_sign,
                raise_on_error=raise_on_error,
            )
        if mode_norm == "lag":
            return design_lag(
                plant,
                target_phase_margin_deg=target_phase_margin_deg,
                dc_gain_boost=dc_gain_boost,
                feedback_sign=feedback_sign,
                raise_on_error=raise_on_error,
            )
        if mode_norm not in ("lead_lag", "lead-lag"):
            raise ValidationError(
                message=f"mode inválido em design_lead_lag: {mode!r}. Use 'lead', 'lag' ou 'lead_lag'.",
                parameters={"mode": mode},
            )

        sign_str = _validate_feedback_sign(feedback_sign)
        ch = extract_siso_tf_channel(plant, require_strictly_siso=True)
        if ch["dt"] is not None:
            raise ValidationError("design_lead_lag requer modelo contínuo (dt=None).")
        tf_plant = ch["tf"] if ch["tf"] is not None else TransferFunction.from_state_space(ch["ss"])

        # Estágio 1: Avanço para atingir frequência de cruzamento e margem de fase
        lead_res = design_lead(
            tf_plant,
            target_phase_margin_deg=min(85.0, float(target_phase_margin_deg) + 5.0),
            target_omega_gc=target_omega_gc,
            dc_gain_boost=1.0,
            feedback_sign=sign_str,
            raise_on_error=True,
        )
        assert lead_res.data is not None
        tf_lead = TransferFunction.from_dict(lead_res.data["controller_tf"])
        p_lead = lead_res.data["parameters"]

        # Estágio 2: Atraso em baixa frequência para reforçar ganho DC por fator beta = dc_gain_boost
        beta = max(1.1, float(dc_gain_boost))
        w_gc_lead = float(lead_res.data["margins_after"]["critical_omega_gc"] or (target_omega_gc or 1.0))
        T_lag = 10.0 / max(1e-4, w_gc_lead)
        tf_lag_stage = TransferFunction(
            num=np.array([beta * T_lag, beta], dtype=np.float64),
            den=np.array([beta * T_lag, 1.0], dtype=np.float64),
            dt=None,
        )

        tf_total = _series_tf(tf_lead, tf_lag_stage)
        dyn_ctrl = _tf_to_dynamic_controller(tf_total, feedback_sign=sign_str, provenance=prov)

        m_before_res = stability_margins(tf_plant, raise_on_error=True)
        loop_after = _series_tf(tf_total, tf_plant)
        m_after_res = stability_margins(loop_after, raise_on_error=True)
        assert m_before_res.data is not None and m_after_res.data is not None

        ss_plant = ch["ss"] if ch["ss"] is not None else tf_plant.to_state_space()
        cl_ss = interconnect(ss_plant, dyn_ctrl, sign_convention=sign_str)

        assumptions = {
            "compensator_type": "lead_lag",
            "feedback_sign": sign_str,
            "alpha": p_lead["alpha"],
            "beta": beta,
        }
        diagnostics = {
            "alpha": p_lead["alpha"],
            "T_lead": p_lead["T"],
            "beta": beta,
            "T_lag": T_lag,
            "Kc": p_lead["Kc"],
            "phase_margin_before_deg": m_before_res.data["critical_phase_margin_deg"],
            "phase_margin_after_deg": m_after_res.data["critical_phase_margin_deg"],
            "omega_gc_after": m_after_res.data["critical_omega_gc"],
            "closed_loop_stable": m_after_res.data["closed_loop_stable"],
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "controller": dyn_ctrl.to_dict(),
                "controller_tf": tf_total.to_dict(),
                "controller_ref": {"id": dyn_ctrl.id, "revision": dyn_ctrl.revision},
                "controller_kind": dyn_ctrl.kind,
                "parameters": {
                    "Kc": p_lead["Kc"],
                    "alpha": p_lead["alpha"],
                    "T_lead": p_lead["T"],
                    "beta": beta,
                    "T_lag": T_lag,
                },
                "margins_before": m_before_res.data,
                "margins_after": m_after_res.data,
                "closed_loop": cl_ss.to_dict(),
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
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


def design_pid(
    plant: Any = None,
    *,
    Kp: float | None = None,
    Ki: float = 0.0,
    Kd: float = 0.0,
    N: float = 20.0,
    target_bandwidth: float | None = None,
    target_phase_margin_deg: float = 60.0,
    feedback_sign: str = "negative",
    raise_on_error: bool = False,
) -> Result:
    """Constrói ou sintoniza controlador PID/PI/PD/P próprio com filtro derivativo N.

    Lei no domínio de Laplace (sempre própria para admitir StateSpace / DynamicController):
        $C(s) = K_p + \\frac{K_i}{s} + \\frac{K_d N s}{s + N}$
    """
    prov = build_provenance("frequency.siso.design_pid", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sign_str = _validate_feedback_sign(feedback_sign)
        if not (isinstance(N, (int, float)) and not isinstance(N, bool) and math.isfinite(N) and float(N) > 0.0):
            raise ValidationError("Filtro derivativo N deve ser número real positivo finito (N > 0).")
        N_val = float(N)

        ch: dict[str, Any] | None = None
        if plant is not None:
            ch = extract_siso_tf_channel(plant, require_strictly_siso=True)
            if ch["dt"] is not None:
                raise ValidationError("design_pid analógico requer modelo contínuo (dt=None).")

        # Se Kp não foi passado explicitamente, sintoniza por cancelamento/margem de fase na banda alvo
        if Kp is None:
            if ch is None:
                raise ValidationError("Forneça Kp explícito ou uma planta SISO para sintonia automática.")
            w_c = float(target_bandwidth) if target_bandwidth is not None else 2.0
            if w_c <= 0.0 or not math.isfinite(w_c):
                raise ValidationError("target_bandwidth deve ser finito > 0.")
            ev = eval_siso_Clean_phase_and_mag(ch["num"], ch["den"], np.array([w_c], dtype=np.float64))
            mag_wc = max(1e-9, float(ev["mag"][0]))
            ph_wc_rad = math.radians(float(ev["phase_deg"][0]))
            pm_rad = math.radians(float(target_phase_margin_deg))
            phi_req = -math.pi + pm_rad - ph_wc_rad
            Kp_val = max(1e-3, math.cos(phi_req) / mag_wc)
            sin_term = math.sin(phi_req) / mag_wc
            if sin_term >= 0.0:
                Kd_val = sin_term / w_c
                Ki_val = 0.1 * w_c * Kp_val
            else:
                Kd_val = 0.0
                Ki_val = max(0.0, -w_c * sin_term)
        else:
            if not (isinstance(Kp, (int, float)) and not isinstance(Kp, bool) and math.isfinite(Kp)):
                raise ValidationError("Kp deve ser número real finito.")
            if not (isinstance(Ki, (int, float)) and not isinstance(Ki, bool) and math.isfinite(Ki)):
                raise ValidationError("Ki deve ser número real finito.")
            if not (isinstance(Kd, (int, float)) and not isinstance(Kd, bool) and math.isfinite(Kd)):
                raise ValidationError("Kd deve ser número real finito.")
            Kp_val = float(Kp)
            Ki_val = float(Ki)
            Kd_val = float(Kd)

        if abs(Kp_val) == 0.0 and abs(Ki_val) == 0.0 and abs(Kd_val) == 0.0:
            raise HypothesisViolatedError("Pelo menos um ganho (Kp, Ki, Kd) deve ser não nulo.")

        # Monta C(s) racional própria:
        # - P: Kp
        # - PI: (Kp s + Ki) / s
        # - PD filtrado: ((Kp + Kd N) s + Kp N) / (s + N)
        # - PID filtrado: ((Kp + Kd N) s^2 + (Kp N + Ki) s + Ki N) / (s^2 + N s)
        has_i = abs(Ki_val) > 0.0
        has_d = abs(Kd_val) > 0.0

        if not has_i and not has_d:
            structure = "P"
            num_c = np.array([Kp_val], dtype=np.float64)
            den_c = np.array([1.0], dtype=np.float64)
        elif has_i and not has_d:
            structure = "PI"
            num_c = np.array([Kp_val, Ki_val], dtype=np.float64)
            den_c = np.array([1.0, 0.0], dtype=np.float64)
        elif not has_i and has_d:
            structure = "PD"
            num_c = np.array([Kp_val + Kd_val * N_val, Kp_val * N_val], dtype=np.float64)
            den_c = np.array([1.0, N_val], dtype=np.float64)
        else:
            structure = "PID"
            num_c = np.array(
                [Kp_val + Kd_val * N_val, Kp_val * N_val + Ki_val, Ki_val * N_val],
                dtype=np.float64,
            )
            den_c = np.array([1.0, N_val, 0.0], dtype=np.float64)

        tf_ctrl = TransferFunction(
            num=num_c,
            den=den_c,
            dt=None,
            provenance={
                "algorithm": "frequency.siso.design_pid",
                "structure": structure,
                "Kp": Kp_val,
                "Ki": Ki_val,
                "Kd": Kd_val,
                "N": N_val,
            },
        )
        dyn_ctrl = _tf_to_dynamic_controller(tf_ctrl, feedback_sign=sign_str, provenance=prov)

        margins_before = None
        margins_after = None
        cl_dict = None
        if ch is not None:
            tf_plant = ch["tf"] if ch["tf"] is not None else TransferFunction.from_state_space(ch["ss"])
            mb = stability_margins(tf_plant, raise_on_error=True)
            ma = stability_margins(_series_tf(tf_ctrl, tf_plant), raise_on_error=True)
            margins_before = mb.data
            margins_after = ma.data
            ss_plant = ch["ss"] if ch["ss"] is not None else tf_plant.to_state_space()
            cl_ss = interconnect(ss_plant, dyn_ctrl, sign_convention=sign_str)
            cl_dict = cl_ss.to_dict()

        assumptions = {
            "structure": structure,
            "proper_derivative_filter": True,
            "filter_N": N_val,
            "feedback_sign": sign_str,
        }
        diagnostics = {
            "structure": structure,
            "Kp": Kp_val,
            "Ki": Ki_val,
            "Kd": Kd_val,
            "N": N_val,
            "controller_states": dyn_ctrl.n_states,
            "phase_margin_after_deg": margins_after["critical_phase_margin_deg"] if margins_after is not None else None,
            "closed_loop_stable": margins_after["closed_loop_stable"] if margins_after is not None else None,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "controller": dyn_ctrl.to_dict(),
                "controller_tf": tf_ctrl.to_dict(),
                "controller_ref": {"id": dyn_ctrl.id, "revision": dyn_ctrl.revision},
                "controller_kind": dyn_ctrl.kind,
                "structure": structure,
                "parameters": {"Kp": Kp_val, "Ki": Ki_val, "Kd": Kd_val, "N": N_val},
                "margins_before": margins_before,
                "margins_after": margins_after,
                "closed_loop": cl_dict,
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
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
