"""Avaliação de resposta em frequência SISO, Bode, Nyquist e resposta ao degrau (Seção 5.3 e 13.5)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from control_lab.core.models import StateSpace, TransferFunction
from control_lab.core.tensors import complex_to_pair, ensure_finite_float64
from control_lab.diagnostics import (
    ControlLabError,
    Provenance,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
)
from control_lab.statespace.simulation import simulate_lti

from ._utils import (
    DEFAULT_N_OMEGA,
    compute_poles_zeros_gain,
    eval_siso_Clean_phase_and_mag,
    extract_siso_tf_channel,
    handle_failure,
    pade_delay_tf,
    resolve_omega_grid,
)


def eval_response(
    plant: Any,
    omega: Any = None,
    *,
    delay: float = 0.0,
    use_pade: bool = False,
    pade_order: int = 1,
    n_points: int = DEFAULT_N_OMEGA,
    omega_min: float | None = None,
    omega_max: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Avalia resposta em frequência SISO G(jw) ou G(e^{jw dt}) com suporte a atraso de transporte.

    Quando `delay > 0`:
    - Se `use_pade=False` (padrão), avalia o atraso exato $e^{-j\\omega\\tau}$ na frequência.
    - Se `use_pade=True` (seleção explícita exigida pela Seção 5.3), aplica aproximação racional
      de Padé de ordem `pade_order`.
    """
    prov: Provenance = build_provenance(
        "frequency.siso.eval_response",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not (isinstance(delay, (int, float)) and not isinstance(delay, bool) and math.isfinite(delay) and delay >= 0.0):
            raise ValidationError(
                message=f"delay deve ser número finito >= 0, recebido {delay!r}.",
                parameters={"delay": delay},
            )
        delay_val = float(delay)

        ch = extract_siso_tf_channel(plant, require_strictly_siso=True)
        num = ch["num"]
        den = ch["den"]
        dt = ch["dt"]
        domain = ch["domain"]
        warnings_out.extend(ch["warnings"])

        if delay_val > 0.0 and dt is not None and use_pade:
            raise UnsupportedModelError(
                message="Aproximação de Padé contínua não se aplica a modelos discretos (dt != None).",
                parameters={"dt": dt, "delay": delay_val, "use_pade": True},
            )

        effective_delay_exact = delay_val
        if delay_val > 0.0 and use_pade:
            p_num, p_den = pade_delay_tf(delay_val, order=pade_order)
            num = np.polymul(num, p_num)
            den = np.polymul(den, p_den)
            effective_delay_exact = 0.0
            warnings_out.append(
                WarningItem(
                    code="PADE_APPROXIMATION_APPLIED",
                    message=(
                        f"Atraso de transporte (delay={delay_val} s) aproximado racionalmente por "
                        f"Padé de ordem {pade_order} por seleção explícita."
                    ),
                    details={"delay": delay_val, "pade_order": pade_order},
                )
            )

        pzk = compute_poles_zeros_gain(num, den)
        poles = pzk["poles"]
        zeros = pzk["zeros"]

        if pzk["near_cancellations"]:
            warnings_out.append(
                WarningItem(
                    code="NEAR_POLE_ZERO_CANCELLATION",
                    message=f"Detectados {len(pzk['near_cancellations'])} par(es) polo-zero quase cancelados.",
                    details={"pairs": pzk["near_cancellations"]},
                )
            )

        # Classificação de fase mínima / RHP zeros / estabilidade de malha aberta
        if domain == "continuous":
            rhp_zeros = [z for z in zeros if float(np.real(z)) > 1e-10]
            rhp_poles = [p for p in poles if float(np.real(p)) > 1e-10]
            imag_poles = [p for p in poles if abs(float(np.real(p))) <= 1e-10]
        else:
            rhp_zeros = [z for z in zeros if float(abs(z)) > 1.0 + 1e-10]
            rhp_poles = [p for p in poles if float(abs(p)) > 1.0 + 1e-10]
            imag_poles = [p for p in poles if abs(float(abs(p)) - 1.0) <= 1e-10]

        is_non_minimum_phase = len(rhp_zeros) > 0 or delay_val > 0.0

        w_grid, w_warns = resolve_omega_grid(
            omega,
            poles=poles,
            zeros=zeros,
            dt=dt,
            n_points=n_points,
            omega_min=omega_min,
            omega_max=omega_max,
        )
        warnings_out.extend(w_warns)

        freq_eval = eval_siso_Clean_phase_and_mag(
            num,
            den,
            w_grid,
            dt=dt,
            delay=effective_delay_exact,
        )

        if freq_eval["singular_frequencies"]:
            warnings_out.append(
                WarningItem(
                    code="POLES_ON_FREQUENCY_GRID",
                    message=(
                        "A grade de frequência intercepta polo(s) no eixo imaginário/círculo unitário; "
                        "magnitude regularizada localmente."
                    ),
                    details={"singular_frequencies": freq_eval["singular_frequencies"]},
                )
            )

        # Ganho DC (s=0 ou z=1)
        s0 = 0.0 if dt is None else 1.0
        den_dc = float(np.polyval(den, s0))
        dc_gain = float(np.polyval(num, s0) / den_dc) if abs(den_dc) > 1e-14 else None

        assumptions = {
            "domain": domain,
            "dt": dt,
            "delay": delay_val,
            "delay_representation": "pade" if (delay_val > 0.0 and use_pade) else ("exact" if delay_val > 0.0 else "none"),
            "pade_order": pade_order if (delay_val > 0.0 and use_pade) else None,
            "is_minimum_phase": not is_non_minimum_phase,
            "open_loop_stable": len(rhp_poles) == 0 and len(imag_poles) == 0,
        }
        diagnostics = {
            "n_frequencies": int(w_grid.size),
            "omega_min": float(w_grid[0]),
            "omega_max": float(w_grid[-1]),
            "dc_gain": dc_gain,
            "high_freq_gain": pzk["gain"],
            "n_poles": int(poles.size),
            "n_zeros": int(zeros.size),
            "n_rhp_zeros": len(rhp_zeros),
            "n_rhp_poles": len(rhp_poles),
            "n_boundary_poles": len(imag_poles),
            "near_cancellations": pzk["near_cancellations"],
            "singular_frequencies": freq_eval["singular_frequencies"],
        }
        prov_ok = build_provenance(
            "frequency.siso.eval_response",
            model_revision=ch["revision"],
            domain=domain,
            dt=dt,
        )
        return Result(
            status="warning" if warnings_out else "success",
            data={
                "omega": w_grid,
                "response": freq_eval["H"],
                "mag": freq_eval["mag"],
                "mag_db": freq_eval["mag_db"],
                "phase_rad": freq_eval["phase_rad"],
                "phase_deg": freq_eval["phase_deg"],
                "poles": pzk["poles_pair"],
                "zeros": pzk["zeros_pair"],
                "gain": pzk["gain"],
                "dc_gain": dc_gain,
                "dt": dt,
                "domain": domain,
                "units": {
                    "frequency": "rad/s",
                    "magnitude_linear": "abs",
                    "magnitude_db": "dB",
                    "phase_deg": "deg",
                    "phase_rad": "rad",
                },
                "series_semantics": "numeric_verified",
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


def bode(
    plant: Any,
    omega: Any = None,
    *,
    delay: float = 0.0,
    use_pade: bool = False,
    pade_order: int = 1,
    n_points: int = DEFAULT_N_OMEGA,
    omega_min: float | None = None,
    omega_max: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Calcula diagrama de Bode SISO (magnitude linear/dB e fase contínua em graus/radianos)."""
    return eval_response(
        plant,
        omega,
        delay=delay,
        use_pade=use_pade,
        pade_order=pade_order,
        n_points=n_points,
        omega_min=omega_min,
        omega_max=omega_max,
        raise_on_error=raise_on_error,
    )


def nyquist_siso(
    plant: Any,
    omega: Any = None,
    *,
    delay: float = 0.0,
    n_points: int = DEFAULT_N_OMEGA,
    raise_on_error: bool = False,
) -> Result:
    """Calcula curva de Nyquist SISO (ramo positivo w >= 0 e espelho conjugado w <= 0)."""
    res = eval_response(
        plant,
        omega,
        delay=delay,
        n_points=n_points,
        raise_on_error=raise_on_error,
    )
    if res.status == "failure" or res.data is None:
        return res

    H_pos = res.data["response"]["real"] + 1j * np.asarray(res.data["response"]["imag"], dtype=np.float64)
    H_neg = np.conj(H_pos[::-1])
    dist_crit = np.abs(H_pos + 1.0)
    min_idx = int(np.argmin(dist_crit))
    min_dist = float(dist_crit[min_idx])
    w_grid = np.asarray(res.data["omega"]["data"], dtype=np.float64)

    data = dict(res.data)
    data["contour_positive"] = complex_to_pair(H_pos)
    data["contour_negative"] = complex_to_pair(H_neg)
    data["critical_point"] = {"real": -1.0, "imag": 0.0}
    data["min_distance_to_critical"] = min_dist
    data["omega_at_min_distance"] = float(w_grid[min_idx])

    diag = dict(res.diagnostics)
    diag["min_distance_to_critical"] = min_dist
    diag["sensitivity_peak_est"] = (1.0 / min_dist) if min_dist > 1e-12 else None

    return Result(
        status=res.status,
        data=data,
        assumptions=res.assumptions,
        diagnostics=diag,
        provenance=build_provenance("frequency.siso.nyquist_siso", model_revision=res.provenance.model_revision),
        warnings=res.warnings,
        error=None,
    )


def step_response_siso(
    plant: Any,
    t: Any = None,
    *,
    amplitude: float = 1.0,
    n_points: int = 500,
    t_final: float | None = None,
    settling_threshold: float = 0.02,
    raise_on_error: bool = False,
) -> Result:
    """Calcula a resposta ao degrau SISO e métricas temporais efetivas (sobressinal, ts, tr, ess)."""
    prov: Provenance = build_provenance(
        "frequency.siso.step_response_siso",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not (isinstance(amplitude, (int, float)) and not isinstance(amplitude, bool) and math.isfinite(amplitude) and amplitude != 0.0):
            raise ValidationError("amplitude do degrau deve ser número finito não nulo.")
        amp = float(amplitude)

        ch = extract_siso_tf_channel(plant, require_strictly_siso=True)
        ss: StateSpace = ch["ss"] if ch["ss"] is not None else ch["tf"].to_state_space()
        dt = ss.dt
        pzk = compute_poles_zeros_gain(ch["num"], ch["den"])
        poles = pzk["poles"]

        if t is not None:
            t_arr = ensure_finite_float64(t, ndim=1, name="t")
        else:
            if dt is not None:
                n_steps = max(20, int(n_points))
                t_arr = np.arange(n_steps, dtype=np.float64) * dt
            else:
                if t_final is not None:
                    tf_val = float(t_final)
                else:
                    real_parts = [abs(float(np.real(p))) for p in poles if abs(float(np.real(p))) > 1e-4]
                    tau_slow = (1.0 / min(real_parts)) if real_parts else 1.0
                    tf_val = max(1.0, min(1000.0, 8.0 * tau_slow))
                t_arr = np.linspace(0.0, tf_val, int(n_points), dtype=np.float64)

        u_arr = np.full((t_arr.size, 1), amp, dtype=np.float64)
        sim_res = simulate_lti(ss, t_arr, u=u_arr, raise_on_error=True)
        assert sim_res.data is not None
        y_arr = np.asarray(sim_res.data["y"]["data"], dtype=np.float64).ravel()

        # Valor de regime (analítico se estável, ou última amostra)
        if dt is None:
            is_stable = bool(poles.size == 0 or np.max(np.real(poles)) < -1e-9)
            s0 = 0.0
        else:
            is_stable = bool(poles.size == 0 or np.max(np.abs(poles)) < 1.0 - 1e-9)
            s0 = 1.0

        den_dc = float(np.polyval(ch["den"], s0))
        y_final = float(amp * np.polyval(ch["num"], s0) / den_dc) if (is_stable and abs(den_dc) > 1e-12) else float(y_arr[-1])
        y_init = float(y_arr[0])
        delta_y = y_final - y_init

        overshoot_pct = 0.0
        peak_val = float(np.max(y_arr)) if delta_y >= 0.0 else float(np.min(y_arr))
        peak_idx = int(np.argmax(y_arr)) if delta_y >= 0.0 else int(np.argmin(y_arr))
        peak_time = float(t_arr[peak_idx])
        if is_stable and abs(delta_y) > 1e-12:
            excursion = (peak_val - y_final) / delta_y
            overshoot_pct = max(0.0, 100.0 * float(excursion))

        # Tempo de acomodação (faixa settling_threshold, padrão 2%)
        settling_time: float | None = None
        if is_stable and abs(delta_y) > 1e-12:
            band = settling_threshold * abs(delta_y)
            outside = np.where(np.abs(y_arr - y_final) > band)[0]
            if outside.size == 0:
                settling_time = float(t_arr[0])
            elif outside[-1] < t_arr.size - 1:
                settling_time = float(t_arr[outside[-1] + 1])

        # Tempo de subida (10% a 90%)
        rise_time: float | None = None
        if is_stable and abs(delta_y) > 1e-12:
            norm_y = (y_arr - y_init) / delta_y
            idx_10 = np.where(norm_y >= 0.1)[0]
            idx_90 = np.where(norm_y >= 0.9)[0]
            if idx_10.size > 0 and idx_90.size > 0 and idx_90[0] >= idx_10[0]:
                rise_time = float(t_arr[idx_90[0]] - t_arr[idx_10[0]])

        steady_state_error = float(amp - y_final) if is_stable else None

        metrics = {
            "is_stable": is_stable,
            "steady_state_value": y_final if is_stable else None,
            "steady_state_error": steady_state_error,
            "overshoot_percent": overshoot_pct if is_stable else None,
            "peak_value": peak_val,
            "peak_time": peak_time,
            "settling_time": settling_time,
            "settling_threshold": float(settling_threshold),
            "rise_time_10_90": rise_time,
        }

        return Result(
            status="success",
            data={
                "t": t_arr,
                "y": y_arr,
                "u": u_arr.ravel(),
                "metrics": metrics,
                "dt": dt,
            },
            assumptions={"step_amplitude": amp, "domain": ch["domain"], "dt": dt},
            diagnostics=metrics,
            provenance=build_provenance("frequency.siso.step_response_siso", model_revision=ch["revision"]),
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
