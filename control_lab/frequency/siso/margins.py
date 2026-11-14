"""Cálculo de múltiplas frequências de cruzamento e margens de estabilidade SISO (Seção 5.3 e T-FREQ-02)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.optimize

from control_lab.diagnostics import (
    ControlLabError,
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
    pade_delay_tf,
    resolve_omega_grid,
)


def _refine_root_bracket(fn: Any, a: float, b: float) -> float:
    """Refina zero em [a, b] via Brentq com fallback linear seguro."""
    fa = float(fn(a))
    fb = float(fn(b))
    if fa == 0.0:
        return a
    if fb == 0.0:
        return b
    if fa * fb < 0.0:
        try:
            root = scipy.optimize.brentq(fn, a, b, xtol=1e-12, rtol=1e-12, maxiter=100)
            return float(root)
        except ValueError:
            pass
    denom = fb - fa
    if abs(denom) > 1e-15:
        return float(a - fa * (b - a) / denom)
    return 0.5 * (a + b)


def _wrap_phase_margin_deg(phase_deg: float) -> float:
    """Calcula margem de fase em graus em (-180, 180] como 180 + phase_deg (mod 360)."""
    pm = (180.0 + phase_deg) % 360.0
    if pm > 180.0:
        pm -= 360.0
    return float(pm)


def stability_margins(
    plant: Any,
    omega: Any = None,
    *,
    delay: float = 0.0,
    use_pade: bool = False,
    pade_order: int = 1,
    n_points: int = 2000,
    omega_min: float | None = None,
    omega_max: float | None = None,
    return_all: bool = True,
    raise_on_error: bool = False,
) -> Result:
    """Calcula todas as frequências de cruzamento de ganho e fase e as margens de estabilidade SISO.

    Suporta sistemas com múltiplas travessias de 0 dB e -180° (T-FREQ-02), sistemas de fase não-mínima,
    atraso de transporte e sistemas condicionalmente estáveis.
    """
    del return_all  # todas as travessias são sempre incluídas no payload estruturado
    prov: Provenance = build_provenance(
        "frequency.siso.stability_margins",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not (isinstance(delay, (int, float)) and not isinstance(delay, bool) and math.isfinite(delay) and delay >= 0.0):
            raise ValidationError("delay deve ser número finito >= 0.")
        delay_val = float(delay)

        ch = extract_siso_tf_channel(plant, require_strictly_siso=True)
        num = ch["num"]
        den = ch["den"]
        dt = ch["dt"]
        domain = ch["domain"]
        warnings_out.extend(ch["warnings"])

        effective_delay_exact = delay_val
        if delay_val > 0.0 and use_pade:
            p_num, p_den = pade_delay_tf(delay_val, order=pade_order)
            num = np.polymul(num, p_num)
            den = np.polymul(den, p_den)
            effective_delay_exact = 0.0

        pzk = compute_poles_zeros_gain(num, den)
        poles = pzk["poles"]
        zeros = pzk["zeros"]

        w_grid, w_warns = resolve_omega_grid(
            omega,
            poles=poles,
            zeros=zeros,
            dt=dt,
            n_points=max(500, int(n_points)),
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
        mag_db = freq_eval["mag_db"]
        phase_deg = freq_eval["phase_deg"]

        def _eval_single_w(w: float) -> tuple[float, float, float]:
            res_w = eval_siso_Clean_phase_and_mag(
                num,
                den,
                np.array([w], dtype=np.float64),
                dt=dt,
                delay=effective_delay_exact,
            )
            return float(res_w["mag"][0]), float(res_w["mag_db"][0]), float(res_w["phase_deg"][0])

        # 1. Travessias de ganho (|L(jw)| = 1 <=> mag_db = 0)
        gain_crossovers: list[dict[str, Any]] = []
        for idx in range(w_grid.size - 1):
            y0 = float(mag_db[idx])
            y1 = float(mag_db[idx + 1])
            if y0 == 0.0 or y0 * y1 < 0.0:
                w_a = float(w_grid[idx])
                w_b = float(w_grid[idx + 1])
                w_gc = w_a if y0 == 0.0 else _refine_root_bracket(lambda w: _eval_single_w(w)[1], w_a, w_b)
                if gain_crossovers and abs(w_gc - gain_crossovers[-1]["omega_gc"]) <= 1e-7 * max(1.0, w_gc):
                    continue
                # Interpola fase contínua no intervalo e refina
                alpha = (w_gc - w_a) / (w_b - w_a) if w_b > w_a else 0.0
                ph_interp = float(phase_deg[idx] + alpha * (phase_deg[idx + 1] - phase_deg[idx]))
                _, _, ph_exact_mod = _eval_single_w(w_gc)
                # Alinha o múltiplo de 360 graus com ph_interp
                k_360 = round((ph_interp - ph_exact_mod) / 360.0)
                ph_gc = ph_exact_mod + 360.0 * k_360
                pm_deg = _wrap_phase_margin_deg(ph_gc)
                dm_sec = (math.radians(pm_deg) / w_gc) if (w_gc > 0.0 and pm_deg > 0.0) else None
                gain_crossovers.append(
                    {
                        "omega_gc": w_gc,
                        "phase_deg": ph_gc,
                        "phase_margin_deg": pm_deg,
                        "delay_margin_sec": dm_sec,
                        "slope_db_per_dec": float(
                            (y1 - y0) / (math.log10(w_b) - math.log10(w_a))
                        )
                        if w_b > w_a > 0.0
                        else 0.0,
                    }
                )

        # 2. Travessias de fase: phase_deg(w) = -180 + 360*k (para qualquer inteiro k)
        # Equivale a sin((phase_rad + pi)/2) = 0 ou cruzamentos de múltiplos ímpares de 180 deg.
        phase_crossovers: list[dict[str, Any]] = []
        for idx in range(w_grid.size - 1):
            p0 = float(phase_deg[idx])
            p1 = float(phase_deg[idx + 1])
            p_min, p_max = min(p0, p1), max(p0, p1)
            # Encontra todos os k tais que target = -180 + 360*k pertença a [p_min, p_max]
            k_start = math.ceil((p_min + 180.0) / 360.0)
            k_end = math.floor((p_max + 180.0) / 360.0)
            for k_int in range(k_start, k_end + 1):
                target_deg = -180.0 + 360.0 * k_int
                if abs(p1 - p0) <= 1e-12:
                    continue
                w_a = float(w_grid[idx])
                w_b = float(w_grid[idx + 1])

                def _phase_diff(w: float, _tgt: float = target_deg, _p0: float = p0, _wa: float = w_a, _wb: float = w_b, _p1: float = p1) -> float:
                    _, _, ph_mod = _eval_single_w(w)
                    alpha_loc = (w - _wa) / (_wb - _wa) if _wb > _wa else 0.0
                    ph_est = _p0 + alpha_loc * (_p1 - _p0)
                    n_turns = round((ph_est - ph_mod) / 360.0)
                    return (ph_mod + 360.0 * n_turns) - _tgt

                w_pc = _refine_root_bracket(_phase_diff, w_a, w_b)
                if phase_crossovers and abs(w_pc - phase_crossovers[-1]["omega_pc"]) <= 1e-7 * max(1.0, w_pc):
                    continue
                mag_lin, mag_db_pc, _ = _eval_single_w(w_pc)
                gm_lin = (1.0 / mag_lin) if mag_lin > 1e-15 else None
                gm_db = -mag_db_pc
                phase_crossovers.append(
                    {
                        "omega_pc": w_pc,
                        "target_phase_deg": target_deg,
                        "loop_gain_abs": mag_lin,
                        "loop_gain_db": mag_db_pc,
                        "gain_margin_linear": gm_lin,
                        "gain_margin_db": gm_db,
                    }
                )

        # Ordena por frequência crescente
        gain_crossovers.sort(key=lambda item: item["omega_gc"])
        phase_crossovers.sort(key=lambda item: item["omega_pc"])

        # Estabilidade de malha fechada unitária (1 + L(s) = 0) quando delay=0 ou via Padé
        closed_loop_stable: bool | None = None
        cl_poles_pair: dict[str, list[float]] | None = None
        if effective_delay_exact == 0.0:
            max_len = max(num.size, den.size)
            num_pad = np.pad(num, (max_len - num.size, 0))
            den_pad = np.pad(den, (max_len - den.size, 0))
            cl_poly = np.trim_zeros(den_pad + num_pad, "f")
            cl_poles = np.roots(cl_poly) if cl_poly.size > 1 else np.array([], dtype=np.complex128)
            if domain == "continuous":
                closed_loop_stable = bool(cl_poles.size == 0 or np.max(np.real(cl_poles)) < -1e-9)
            else:
                closed_loop_stable = bool(cl_poles.size == 0 or np.max(np.abs(cl_poles)) < 1.0 - 1e-9)
            from ._utils import sort_complex_roots

            cl_poles_sorted = sort_complex_roots(cl_poles)
            cl_poles_pair = {
                "real": [float(np.real(p)) for p in cl_poles_sorted],
                "imag": [float(np.imag(p)) for p in cl_poles_sorted],
            }

        # Seleção da margem crítica (a mais restritiva em torno de 0 dB / -180 deg)
        critical_pm = None
        if gain_crossovers:
            critical_pm = min(gain_crossovers, key=lambda c: abs(c["phase_margin_deg"]))

        critical_gm = None
        if phase_crossovers:
            critical_gm = min(phase_crossovers, key=lambda c: abs(c["gain_margin_db"]))

        if len(gain_crossovers) > 1 or len(phase_crossovers) > 1:
            warnings_out.append(
                WarningItem(
                    code="MULTIPLE_CROSSOVER_FREQUENCIES",
                    message=(
                        f"Detectadas múltiplas frequências de cruzamento "
                        f"(n_gc={len(gain_crossovers)}, n_pc={len(phase_crossovers)}); "
                        "inspecione todas as margens antes de concluir robustez."
                    ),
                    details={
                        "n_gain_crossovers": len(gain_crossovers),
                        "n_phase_crossovers": len(phase_crossovers),
                    },
                )
            )

        assumptions = {
            "domain": domain,
            "dt": dt,
            "unity_negative_feedback": True,
            "delay": delay_val,
        }
        diagnostics = {
            "n_gain_crossovers": len(gain_crossovers),
            "n_phase_crossovers": len(phase_crossovers),
            "has_multiple_crossings": len(gain_crossovers) > 1 or len(phase_crossovers) > 1,
            "closed_loop_stable": closed_loop_stable,
            "infinite_gain_margin": len(phase_crossovers) == 0,
            "infinite_phase_margin": len(gain_crossovers) == 0,
        }

        data = {
            "gain_crossovers": gain_crossovers,
            "phase_crossovers": phase_crossovers,
            "omega_gc_all": [c["omega_gc"] for c in gain_crossovers],
            "omega_pc_all": [c["omega_pc"] for c in phase_crossovers],
            "phase_margins_deg": [c["phase_margin_deg"] for c in gain_crossovers],
            "gain_margins_db": [c["gain_margin_db"] for c in phase_crossovers],
            "gain_margins_linear": [c["gain_margin_linear"] for c in phase_crossovers],
            "critical_phase_margin_deg": critical_pm["phase_margin_deg"] if critical_pm is not None else None,
            "critical_omega_gc": critical_pm["omega_gc"] if critical_pm is not None else None,
            "critical_delay_margin_sec": critical_pm["delay_margin_sec"] if critical_pm is not None else None,
            "critical_gain_margin_db": critical_gm["gain_margin_db"] if critical_gm is not None else None,
            "critical_gain_margin_linear": critical_gm["gain_margin_linear"] if critical_gm is not None else None,
            "critical_omega_pc": critical_gm["omega_pc"] if critical_gm is not None else None,
            "closed_loop_stable": closed_loop_stable,
            "closed_loop_poles": cl_poles_pair,
            "units": {
                "frequency": "rad/s",
                "gain_margin_db": "dB",
                "phase_margin_deg": "deg",
                "delay_margin": "s",
            },
        }

        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=build_provenance("frequency.siso.stability_margins", model_revision=ch["revision"]),
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
