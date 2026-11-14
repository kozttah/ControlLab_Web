"""Helpers compartilhados para análise e projeto SISO no domínio da frequência (Frente F3)."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import scipy.linalg

from control_lab.core.controllers import DynamicController, StateFeedbackController
from control_lab.core.models import StateSpace, TransferFunction
from control_lab.core.tensors import complex_to_pair, ensure_finite_float64, validate_sample_time
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    Provenance,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
)

DEFAULT_OMEGA_MIN: float = 1e-3
DEFAULT_OMEGA_MAX: float = 1e3
DEFAULT_N_OMEGA: int = 500
DEFAULT_POLE_ZERO_TOL: float = 1e-10


def handle_failure(
    exc: ControlLabError,
    *,
    raise_on_error: bool,
    provenance: Provenance,
    assumptions: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    warnings_out: Sequence[str | WarningItem] = (),
) -> Result:
    """Empacota uma exceção ControlLabError em Result(status='failure') ou relança se raise_on_error=True."""
    if raise_on_error:
        raise exc
    return Result(
        status="failure",
        data=None,
        assumptions=dict(assumptions) if assumptions is not None else {},
        diagnostics=dict(diagnostics) if diagnostics is not None else {},
        provenance=provenance,
        warnings=tuple(warnings_out),
        error=exc.to_typed_error(),
    )


def sort_complex_roots(roots: np.ndarray) -> np.ndarray:
    """Ordena raízes complexas deterministicamente por (Re, Im)."""
    arr = np.asarray(roots, dtype=np.complex128).ravel()
    if arr.size == 0:
        return arr
    order = np.lexsort((np.imag(arr), np.real(arr)))
    return arr[order]


def extract_siso_tf_channel(
    plant: Any,
    *,
    output_index: int = 0,
    input_index: int = 0,
    require_strictly_siso: bool = True,
) -> dict[str, Any]:
    """Extrai polinômios (num, den) em ordem decrescente de s ou z para um canal SISO."""
    if isinstance(plant, DynamicController):
        ss = StateSpace(
            A=plant.Ac,
            B=plant.Bc,
            C=plant.Cc,
            D=plant.Dc,
            dt=plant.dt,
            id=plant.id,
            revision=plant.revision,
        )
        plant = ss

    if isinstance(plant, StateSpace):
        if require_strictly_siso and (plant.n_inputs != 1 or plant.n_outputs != 1):
            raise DimensionMismatchError(
                message=(
                    f"Operação SISO exige sistema 1x1, recebido StateSpace "
                    f"({plant.n_outputs}x{plant.n_inputs})."
                ),
                parameters={"n_outputs": plant.n_outputs, "n_inputs": plant.n_inputs},
                next_step="Use as rotinas de control_lab.frequency.mimo para sistemas multivariáveis.",
            )
        tf = TransferFunction.from_state_space(plant)
        num, den = tf._channel_descending_z_or_s(output_index, input_index)
        return {
            "num": num,
            "den": den,
            "dt": plant.dt,
            "domain": "continuous" if plant.dt is None else "discrete",
            "id": plant.id,
            "revision": plant.revision,
            "units": plant.units,
            "input_name": plant.input_names[input_index],
            "output_name": plant.output_names[output_index],
            "warnings": list(tf.warnings),
            "source_kind": "StateSpace",
            "ss": plant,
            "tf": tf,
        }

    if isinstance(plant, TransferFunction):
        if require_strictly_siso and not plant.is_siso:
            raise DimensionMismatchError(
                message=(
                    f"Operação SISO exige TransferFunction 1x1, recebido "
                    f"({plant.n_outputs}x{plant.n_inputs})."
                ),
                parameters={"n_outputs": plant.n_outputs, "n_inputs": plant.n_inputs},
                next_step="Use as rotinas de control_lab.frequency.mimo para sistemas multivariáveis.",
            )
        if not (0 <= output_index < plant.n_outputs and 0 <= input_index < plant.n_inputs):
            raise DimensionMismatchError(
                f"Canal ({output_index}, {input_index}) fora dos limites ({plant.n_outputs}, {plant.n_inputs})."
            )
        num, den = plant._channel_descending_z_or_s(output_index, input_index)
        return {
            "num": num,
            "den": den,
            "dt": plant.dt,
            "domain": "continuous" if plant.dt is None else "discrete",
            "id": plant.id,
            "revision": plant.revision,
            "units": plant.units,
            "input_name": plant.input_names[input_index],
            "output_name": plant.output_names[output_index],
            "warnings": list(plant.warnings),
            "source_kind": "TransferFunction",
            "ss": None,
            "tf": plant,
        }

    if isinstance(plant, StateFeedbackController):
        raise UnsupportedModelError(
            message="StateFeedbackController estático requer planta associada para análise em frequência.",
            next_step="Passe StateSpace, TransferFunction ou DynamicController.",
        )

    raise UnsupportedModelError(
        message=f"Modelo não suportado em frequência SISO: {type(plant).__name__}.",
        parameters={"model_type": type(plant).__name__},
        next_step="Forneça uma instância de TransferFunction, StateSpace ou DynamicController.",
    )


def compute_poles_zeros_gain(
    num: np.ndarray,
    den: np.ndarray,
    *,
    cancel_tol: float = 1e-6,
) -> dict[str, Any]:
    """Calcula polos, zeros, ganho líder, ganho DC e detecta cancelamentos quase exatos."""
    num_clean = np.trim_zeros(np.asarray(num, dtype=np.float64), "f")
    den_clean = np.trim_zeros(np.asarray(den, dtype=np.float64), "f")
    if den_clean.size == 0 or float(den_clean[0]) == 0.0:
        raise ValidationError("Denominador identicamente nulo.")
    if num_clean.size == 0:
        num_clean = np.array([0.0], dtype=np.float64)

    poles = sort_complex_roots(np.roots(den_clean)) if den_clean.size > 1 else np.array([], dtype=np.complex128)
    if num_clean.size > 1 and float(num_clean[0]) != 0.0:
        zeros = sort_complex_roots(np.roots(num_clean))
    else:
        zeros = np.array([], dtype=np.complex128)

    k_lead = float(num_clean[0] / den_clean[0])

    # Detecção de cancelamentos polo-zero quase exatos
    near_cancellations: list[dict[str, Any]] = []
    used_poles: set[int] = set()
    for z in zeros:
        best_idx = -1
        best_dist = float("inf")
        for idx, p in enumerate(poles):
            if idx in used_poles:
                continue
            dist = float(abs(z - p))
            scale = max(1.0, float(abs(p)), float(abs(z)))
            if dist <= cancel_tol * scale and dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx >= 0:
            used_poles.add(best_idx)
            near_cancellations.append(
                {
                    "zero": {"real": float(np.real(z)), "imag": float(np.imag(z))},
                    "pole": {
                        "real": float(np.real(poles[best_idx])),
                        "imag": float(np.imag(poles[best_idx])),
                    },
                    "distance": best_dist,
                }
            )

    return {
        "num": num_clean,
        "den": den_clean,
        "poles": poles,
        "zeros": zeros,
        "gain": k_lead,
        "near_cancellations": near_cancellations,
        "poles_pair": complex_to_pair(poles),
        "zeros_pair": complex_to_pair(zeros),
    }


def resolve_omega_grid(
    omega: Any = None,
    *,
    poles: np.ndarray | None = None,
    zeros: np.ndarray | None = None,
    dt: float | None = None,
    n_points: int = DEFAULT_N_OMEGA,
    omega_min: float | None = None,
    omega_max: float | None = None,
) -> tuple[np.ndarray, list[WarningItem]]:
    """Resolve ou gera grade logarítmica de frequências (rad/s) validando Nyquist no discreto."""
    warnings_out: list[WarningItem] = []
    resolved_dt = validate_sample_time(dt)
    nyquist_freq = (math.pi / resolved_dt) if resolved_dt is not None else None

    if omega is not None:
        w_arr = ensure_finite_float64(omega, ndim=1, name="omega")
        if w_arr.size < 1:
            raise ValidationError("Grade de frequências omega deve conter ao menos 1 ponto.")
        if np.any(w_arr < 0.0):
            raise ValidationError(
                message="Frequências em omega devem ser não-negativas (omega >= 0).",
                parameters={"min_omega": float(np.min(w_arr))},
            )
        if w_arr.size >= 2 and not np.all(np.diff(w_arr) > 0.0):
            raise ValidationError(
                message="Vetor de frequências omega deve ser estritamente crescente.",
                next_step="Ordene omega em ordem estritamente crescente e remova duplicatas.",
            )
        if nyquist_freq is not None and float(np.max(w_arr)) > nyquist_freq * (1.0 + 1e-12):
            warnings_out.append(
                WarningItem(
                    code="ABOVE_NYQUIST_FREQUENCY",
                    message=(
                        f"Frequência máxima ({float(np.max(w_arr)):.4g} rad/s) excede a frequência de "
                        f"Nyquist pi/dt = {nyquist_freq:.4g} rad/s."
                    ),
                    details={"max_omega": float(np.max(w_arr)), "nyquist_omega": nyquist_freq},
                )
            )
        return w_arr, warnings_out

    if isinstance(n_points, bool) or not isinstance(n_points, int) or n_points < 2:
        raise ValidationError("n_points deve ser inteiro >= 2.")

    # Estima faixa de frequências a partir das singularidades não-nulas
    char_freqs: list[float] = []
    for arr in (poles, zeros):
        if arr is not None and arr.size > 0:
            if resolved_dt is None:
                mags = np.abs(arr)
                char_freqs.extend(float(m) for m in mags if m > 1e-6)
            else:
                for root in arr:
                    if abs(root) > 1e-12:
                        w_eq = abs(cmath_log_safe(complex(root)) / resolved_dt)
                        if w_eq > 1e-6:
                            char_freqs.append(w_eq)

    if omega_min is not None:
        w_low = float(omega_min)
    elif char_freqs:
        w_low = max(1e-4, 0.05 * min(char_freqs))
    else:
        w_low = DEFAULT_OMEGA_MIN

    if omega_max is not None:
        w_high = float(omega_max)
    elif char_freqs:
        w_high = min(1e5, 20.0 * max(char_freqs))
    else:
        w_high = DEFAULT_OMEGA_MAX

    if nyquist_freq is not None:
        if omega_max is None:
            w_high = min(w_high, 0.999 * nyquist_freq)
            w_low = min(w_low, 0.01 * nyquist_freq)
        elif w_high > nyquist_freq * (1.0 + 1e-12):
            warnings_out.append(
                WarningItem(
                    code="ABOVE_NYQUIST_FREQUENCY",
                    message=f"omega_max={w_high:.4g} excede a frequência de Nyquist ({nyquist_freq:.4g} rad/s).",
                    details={"omega_max": w_high, "nyquist_omega": nyquist_freq},
                )
            )

    if not (math.isfinite(w_low) and math.isfinite(w_high) and w_low > 0.0 and w_high > w_low):
        raise ValidationError(
            message=f"Limites de frequência inválidos: omega_min={w_low}, omega_max={w_high}.",
            parameters={"omega_min": w_low, "omega_max": w_high},
        )

    w_grid = np.logspace(math.log10(w_low), math.log10(w_high), n_points, dtype=np.float64)
    return w_grid, warnings_out


def cmath_log_safe(z: complex) -> complex:
    return complex(np.log(np.complex128(z)))


def pade_delay_tf(delay: float, order: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Calcula aproximação racional de Padé simétrica (grau n/n) para e^{-delay * s}.

    Fórmula fechada:
        P_n(x) = sum_{k=0}^n ((2n - k)! n!) / ((2n)! k! (n - k)!) * (-x)^k
        Q_n(x) = P_n(-x), onde x = delay * s.
    """
    if isinstance(order, bool) or not isinstance(order, int) or order < 1 or order > 10:
        raise ValidationError(
            message=f"Ordem de Padé inválida: {order!r}. Use inteiro entre 1 e 10.",
            parameters={"pade_order": order},
        )
    if not (isinstance(delay, (int, float)) and not isinstance(delay, bool) and math.isfinite(delay) and delay >= 0.0):
        raise ValidationError(
            message=f"Atraso de transporte delay deve ser finito >= 0, recebido {delay!r}.",
            parameters={"delay": delay},
        )
    if delay == 0.0:
        return np.array([1.0], dtype=np.float64), np.array([1.0], dtype=np.float64)

    n = order
    num_asc = np.zeros(n + 1, dtype=np.float64)
    den_asc = np.zeros(n + 1, dtype=np.float64)
    for k in range(n + 1):
        coeff = (
            math.factorial(2 * n - k)
            * math.factorial(n)
            / (math.factorial(2 * n) * math.factorial(k) * math.factorial(n - k))
        )
        term = coeff * (delay**k)
        den_asc[k] = term
        num_asc[k] = term * ((-1.0) ** k)

    # Normaliza pelo coeficiente de maior grau (s^n) em ordem decrescente
    num_desc = num_asc[::-1] / den_asc[-1]
    den_desc = den_asc[::-1] / den_asc[-1]
    return num_desc, den_desc


def eval_siso_Clean_phase_and_mag(
    num: np.ndarray,
    den: np.ndarray,
    omega: np.ndarray,
    *,
    dt: float | None = None,
    delay: float = 0.0,
) -> dict[str, Any]:
    """Avalia resposta em frequência SISO com fase analítica contínua para polos/zeros na origem."""
    num_clean = np.trim_zeros(np.asarray(num, dtype=np.float64), "f")
    den_clean = np.trim_zeros(np.asarray(den, dtype=np.float64), "f")
    if num_clean.size == 0:
        num_clean = np.array([0.0], dtype=np.float64)

    N = omega.shape[0]
    if np.all(num_clean == 0.0):
        return {
            "H": np.zeros(N, dtype=np.complex128),
            "mag": np.zeros(N, dtype=np.float64),
            "mag_db": np.full(N, -300.0, dtype=np.float64),
            "phase_rad": np.zeros(N, dtype=np.float64),
            "phase_deg": np.zeros(N, dtype=np.float64),
            "singular_frequencies": [],
        }

    if dt is None:
        s_pts = 1j * omega
    else:
        s_pts = np.exp(1j * omega * dt)

    # Avaliação polinomial direta + detecção de singularidade sobre o contorno
    num_vals = np.polyval(num_clean, s_pts)
    den_vals = np.polyval(den_clean, s_pts)

    singular_indices = np.where(np.abs(den_vals) <= 1e-14 * max(1.0, float(np.max(np.abs(den_clean)))))[0]
    singular_freqs = [float(omega[idx]) for idx in singular_indices.tolist()]

    # Evitar divisão por zero (NaN/Inf proibidos em JSON): regularização local controlada
    den_safe = den_vals.copy()
    if singular_indices.size > 0:
        den_safe[singular_indices] = 1e-15 + 0j

    delay_factor = np.exp(-1j * omega * delay) if (dt is None and delay > 0.0) else np.ones(N, dtype=np.complex128)
    H = (num_vals / den_safe) * delay_factor

    mag = np.abs(H)
    mag_safe = np.maximum(mag, 1e-15)
    mag_db = 20.0 * np.log10(mag_safe)

    # Cálculo de fase contínua: decomposição em fatores para evitar salto espúrio em s=0
    if dt is None:
        # Conta zeros e polos exatos na origem (s=0)
        n_zeros_origin = 0
        idx = num_clean.size - 1
        while idx >= 0 and abs(float(num_clean[idx])) <= 1e-15:
            n_zeros_origin += 1
            idx -= 1

        n_poles_origin = 0
        idx = den_clean.size - 1
        while idx >= 0 and abs(float(den_clean[idx])) <= 1e-15:
            n_poles_origin += 1
            idx -= 1

        num_red = num_clean[: num_clean.size - n_zeros_origin]
        den_red = den_clean[: den_clean.size - n_poles_origin]

        H_red = np.polyval(num_red, s_pts) / np.where(
            np.abs(np.polyval(den_red, s_pts)) > 1e-15,
            np.polyval(den_red, s_pts),
            1e-15 + 0j,
        )
        phase_red = np.unwrap(np.angle(H_red))
        origin_phase = (n_zeros_origin - n_poles_origin) * (math.pi / 2.0)
        phase_rad = phase_red + origin_phase - omega * delay
    else:
        raw_angle = np.angle((num_vals / den_safe))
        phase_rad = np.unwrap(raw_angle)
        if delay > 0.0:
            phase_rad = phase_rad - omega * delay

    phase_deg = np.degrees(phase_rad)
    return {
        "H": H,
        "mag": mag,
        "mag_db": mag_db,
        "phase_rad": phase_rad,
        "phase_deg": phase_deg,
        "singular_frequencies": singular_freqs,
    }
