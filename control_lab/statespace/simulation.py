"""Discretização ZOH exata e simulação LTI contínua (expm/FOH/solve_ivp) e discreta."""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import scipy.integrate
import scipy.linalg

from control_lab.core.models import StateSpace
from control_lab.core.tensors import complex_to_pair, ensure_finite_float64, validate_sample_time
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
    handle_failure,
    sort_complex_eigs,
    validate_x0_vector,
)


def discretize_zoh(
    plant: StateSpace,
    dt: float,
    *,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Discretiza modelo StateSpace contínuo via Zero-Order Hold exato com exponencial matricial em bloco."""
    del tol  # reservado para assinatura uniforme
    prov: Provenance = build_provenance(
        "statespace.discretize_zoh",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(plant, StateSpace):
            raise UnsupportedModelError(
                message=f"discretize_zoh requer instância StateSpace, recebido {type(plant).__name__}.",
                parameters={"plant_type": type(plant).__name__},
            )
        if plant.dt is not None:
            raise UnsupportedModelError(
                message=f"Modelo StateSpace já é discreto (dt={plant.dt}); discretize_zoh exige sistema contínuo (dt=None).",
                parameters={"plant_dt": plant.dt},
                next_step="Forneça um modelo contínuo (dt=None) para discretização ZOH.",
            )

        resolved_dt = validate_sample_time(dt)
        if resolved_dt is None:
            raise ValidationError("dt deve ser um número real positivo (> 0) para discretize_zoh.")

        n, m, p = plant.n_states, plant.n_inputs, plant.n_outputs
        if n == 0:
            A_d = np.zeros((0, 0), dtype=np.float64)
            B_d = np.zeros((0, m), dtype=np.float64)
            bottom_err = 0.0
            eigs_d = np.array([], dtype=np.complex128)
            rho = None
        else:
            M = np.zeros((n + m, n + m), dtype=np.float64)
            M[:n, :n] = plant.A * resolved_dt
            if m > 0:
                M[:n, n:] = plant.B * resolved_dt
            E = scipy.linalg.expm(M)
            if not np.all(np.isfinite(E)):
                raise NumericalInconclusiveError("scipy.linalg.expm retornou valores não finitos na discretização ZOH.")

            A_d = np.array(E[:n, :n], dtype=np.float64)
            B_d = np.array(E[:n, n:], dtype=np.float64)
            expected_bottom = np.hstack([np.zeros((m, n), dtype=np.float64), np.eye(m, dtype=np.float64)])
            bottom_err = float(np.linalg.norm(E[n:, :] - expected_bottom, "fro") / max(1.0, math.sqrt(max(1, m))))
            eigs_d = sort_complex_eigs(np.linalg.eigvals(A_d))
            rho = float(np.max(np.abs(eigs_d)))

            if bottom_err > 1e-8:
                warnings_out.append(
                    WarningItem(
                        code="ZOH_EXPM_BOTTOM_DRIFT",
                        message=f"Desvio no bloco inferior da exponencial matricial ZOH: {bottom_err:.3e}.",
                        details={"expm_bottom_block_error": bottom_err},
                    )
                )

        prov_ok = build_provenance(
            "scipy.linalg.expm.zoh",
            model_revision=plant.revision,
            dt=resolved_dt,
        )
        ss_d = StateSpace(
            A=A_d,
            B=B_d,
            C=plant.C,
            D=plant.D,
            dt=resolved_dt,
            state_names=plant.state_names,
            input_names=plant.input_names,
            output_names=plant.output_names,
            units=plant.units,
            provenance={
                "source": "statespace.discretize_zoh",
                "continuous_model_ref": {"id": plant.id, "revision": plant.revision},
                "dt": resolved_dt,
            },
        )

        assumptions = {
            "hold": "zero_order_hold",
            "continuous_source": True,
            "dt": resolved_dt,
            "n_states": n,
            "n_inputs": m,
            "n_outputs": p,
        }
        diagnostics = {
            "expm_bottom_block_error": bottom_err,
            "spectral_radius": rho,
        }
        return Result(
            status="warning" if warnings_out else "success",
            data={
                "model": ss_d.to_dict(),
                "A_d": A_d,
                "B_d": B_d,
                "C_d": np.array(plant.C, dtype=np.float64),
                "D_d": np.array(plant.D, dtype=np.float64),
                "dt": resolved_dt,
                "poles": complex_to_pair(eigs_d),
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


def _eval_callable_input(u_fn: Callable[[float], Any], t_val: float, m: int) -> np.ndarray:
    raw = u_fn(float(t_val))
    if m == 1 and isinstance(raw, (int, float, np.integer, np.floating)) and not isinstance(raw, bool):
        arr = np.array([float(raw)], dtype=np.float64)
    else:
        arr = ensure_finite_float64(raw, name="u(t)")
        if arr.ndim == 0 and m == 1:
            arr = arr.reshape((1,))
        elif arr.ndim == 2 and arr.shape in ((m, 1), (1, m)):
            arr = arr.reshape((m,))
        elif arr.ndim != 1 or arr.shape != (m,):
            raise DimensionMismatchError(
                f"u({t_val}) deve retornar vetor de tamanho m={m}, recebido shape={arr.shape}."
            )
    if not np.all(np.isfinite(arr)):
        raise ValidationError(f"u({t_val}) retornou valor não finito.")
    return arr


def _interp_input_piecewise_linear(t_grid: np.ndarray, u_grid: np.ndarray, tau: float) -> np.ndarray:
    """Interpolação linear vetorial de u(tau) sobre grade estritamente crescente t_grid."""
    if tau <= t_grid[0]:
        return u_grid[0]
    if tau >= t_grid[-1]:
        return u_grid[-1]
    idx = int(np.searchsorted(t_grid, tau, side="right")) - 1
    idx = max(0, min(idx, t_grid.shape[0] - 2))
    t0 = float(t_grid[idx])
    t1 = float(t_grid[idx + 1])
    alpha = (tau - t0) / (t1 - t0)
    return (1.0 - alpha) * u_grid[idx] + alpha * u_grid[idx + 1]


def simulate_lti(
    plant: StateSpace,
    t: Any,
    u: Any = None,
    x0: Any = None,
    *,
    method: str = "auto",
    rtol: float = 1e-9,
    atol: float = 1e-12,
    raise_on_error: bool = False,
) -> Result:
    """Simula sistema StateSpace contínuo (expm/ZOH, FOH ou solve_ivp) ou discreto preservando t original."""
    prov: Provenance = build_provenance(
        "statespace.simulate_lti",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(plant, StateSpace):
            raise UnsupportedModelError(
                message=f"simulate_lti requer instância StateSpace, recebido {type(plant).__name__}.",
                parameters={"plant_type": type(plant).__name__},
            )

        t_arr = ensure_finite_float64(t, ndim=1, name="t")
        N = t_arr.shape[0]
        if N < 1:
            raise ValidationError("Vetor de tempo t deve conter ao menos 1 amostra.")
        if N >= 2 and not np.all(np.diff(t_arr) > 0.0):
            raise ValidationError(
                message="Vetor de tempo t deve ser estritamente crescente.",
                next_step="Forneça instantes temporais estritamente crescentes sem duplicatas.",
            )

        if not isinstance(method, str) or not method.strip():
            raise ValidationError("method deve ser string não vazia.")
        method_norm = method.lower()

        if not (isinstance(rtol, (int, float)) and not isinstance(rtol, bool) and math.isfinite(rtol) and rtol > 0.0):
            raise ValidationError("rtol deve ser número real positivo finito.")
        if not (isinstance(atol, (int, float)) and not isinstance(atol, bool) and math.isfinite(atol) and atol > 0.0):
            raise ValidationError("atol deve ser número real positivo finito.")

        n, m, p = plant.n_states, plant.n_inputs, plant.n_outputs
        x0_vec = np.zeros((n,), dtype=np.float64) if x0 is None else validate_x0_vector(x0, n)

        u_callable: Callable[[float], Any] | None = None
        if u is None:
            u_arr = np.zeros((N, m), dtype=np.float64)
        elif callable(u):
            if plant.dt is not None:
                raise ValidationError("Entrada u callable só é suportada em simulação contínua; forneça array (N, m) no discreto.")
            u_callable = u
            u_arr = np.vstack([_eval_callable_input(u_callable, float(tk), m) for tk in t_arr])
        else:
            u_raw = ensure_finite_float64(u, name="u")
            if u_raw.ndim == 1:
                if m != 1:
                    raise DimensionMismatchError(
                        message=f"Entrada u 1D só é válida para m=1; planta possui m={m} entradas.",
                        parameters={"u_shape": list(u_raw.shape), "m": m},
                    )
                if u_raw.shape[0] != N:
                    raise DimensionMismatchError(
                        message=f"Comprimento de u ({u_raw.shape[0]}) difere de len(t)={N}.",
                        parameters={"len_u": int(u_raw.shape[0]), "len_t": N},
                    )
                u_arr = u_raw.reshape((N, 1))
            elif u_raw.ndim == 2:
                if u_raw.shape != (N, m):
                    raise DimensionMismatchError(
                        message=f"Entrada u tem shape {u_raw.shape}, esperado ({N}, {m}).",
                        parameters={"u_shape": list(u_raw.shape), "expected_shape": [N, m]},
                    )
                u_arr = u_raw
            else:
                raise DimensionMismatchError(f"Entrada u deve ser 1D ou 2D, recebido {u_raw.ndim}D.")

        x_traj = np.zeros((N, n), dtype=np.float64)
        if n > 0:
            x_traj[0, :] = x0_vec

        domain = "continuous" if plant.dt is None else "discrete"
        used_method: str

        if plant.dt is not None:
            if method_norm not in ("auto", "discrete", "recurrence"):
                raise UnsupportedModelError(
                    message=f"Método {method!r} não suportado para sistema discreto (use 'auto' ou 'discrete').",
                    parameters={"method": method, "dt": plant.dt},
                )
            if N >= 2:
                diffs = np.diff(t_arr)
                if not np.allclose(diffs, plant.dt, rtol=1e-6, atol=1e-12):
                    raise HypothesisViolatedError(
                        message=(
                            f"Espaçamento temporal de t não corresponde a plant.dt={plant.dt}: "
                            f"min_dt={float(np.min(diffs)):.6g}, max_dt={float(np.max(diffs)):.6g}."
                        ),
                        parameters={"plant_dt": plant.dt, "min_dt": float(np.min(diffs)), "max_dt": float(np.max(diffs))},
                        next_step="Forneça grade temporal uniforme t_k = t_0 + k * dt compatível com plant.dt.",
                    )
            used_method = "discrete_recurrence"
            A, B = plant.A, plant.B
            for k in range(N - 1):
                if n > 0:
                    x_next = A @ x_traj[k, :] + B @ u_arr[k, :]
                    if not np.all(np.isfinite(x_next)) or float(np.max(np.abs(x_next))) > 1e150:
                        raise NumericalInconclusiveError(
                            f"Divergência/overflow numérico na simulação discreta no passo k={k + 1}."
                        )
                    x_traj[k + 1, :] = x_next
        else:
            # Sistema contínuo
            ivp_aliases = {
                "solve_ivp": "DOP853",
                "ivp": "DOP853",
                "dop853": "DOP853",
                "rk45": "RK45",
                "radau": "Radau",
                "bdf": "BDF",
            }
            if method_norm == "auto":
                if n == 0 or N == 1:
                    resolved = "expm"
                elif u_callable is not None:
                    resolved = "DOP853"
                elif np.all(u_arr == u_arr[0:1, :]):
                    resolved = "expm"
                else:
                    resolved = "foh"
            elif method_norm in ("expm", "zoh"):
                resolved = "expm"
            elif method_norm == "foh":
                resolved = "foh"
            elif method_norm in ivp_aliases:
                resolved = ivp_aliases[method_norm]
            else:
                raise ValidationError(
                    f"method inválido em simulate_lti: {method!r}. "
                    "Use 'auto', 'expm', 'zoh', 'foh', 'solve_ivp', 'dop853', 'rk45', 'radau' ou 'bdf'."
                )

            if n > 0 and N >= 2:
                A, B = plant.A, plant.B
                if resolved == "expm":
                    used_method = "expm_zoh"
                    diffs = np.diff(t_arr)
                    is_uniform = bool(np.max(np.abs(diffs - diffs[0])) <= 1e-12 * max(1.0, float(diffs[0])))
                    if is_uniform:
                        dt_step = float(diffs[0])
                        M = np.zeros((n + m, n + m), dtype=np.float64)
                        M[:n, :n] = A * dt_step
                        if m > 0:
                            M[:n, n:] = B * dt_step
                        E = scipy.linalg.expm(M)
                        if not np.all(np.isfinite(E)):
                            raise NumericalInconclusiveError("expm produziu valores não finitos.")
                        Ad = E[:n, :n]
                        Bd = E[:n, n:]
                        for k in range(N - 1):
                            x_next = Ad @ x_traj[k, :] + Bd @ u_arr[k, :]
                            if not np.all(np.isfinite(x_next)) or float(np.max(np.abs(x_next))) > 1e150:
                                raise NumericalInconclusiveError(f"Divergência numérica em t={t_arr[k + 1]}.")
                            x_traj[k + 1, :] = x_next
                    else:
                        for k in range(N - 1):
                            dt_k = float(diffs[k])
                            M = np.zeros((n + m, n + m), dtype=np.float64)
                            M[:n, :n] = A * dt_k
                            if m > 0:
                                M[:n, n:] = B * dt_k
                            E = scipy.linalg.expm(M)
                            if not np.all(np.isfinite(E)):
                                raise NumericalInconclusiveError("expm produziu valores não finitos.")
                            x_next = E[:n, :n] @ x_traj[k, :] + E[:n, n:] @ u_arr[k, :]
                            if not np.all(np.isfinite(x_next)) or float(np.max(np.abs(x_next))) > 1e150:
                                raise NumericalInconclusiveError(f"Divergência numérica em t={t_arr[k + 1]}.")
                            x_traj[k + 1, :] = x_next
                elif resolved == "foh":
                    used_method = "expm_foh"
                    diffs = np.diff(t_arr)
                    is_uniform = bool(np.max(np.abs(diffs - diffs[0])) <= 1e-12 * max(1.0, float(diffs[0])))
                    cached_E: np.ndarray | None = None
                    for k in range(N - 1):
                        dt_k = float(diffs[k])
                        if is_uniform and cached_E is not None:
                            E = cached_E
                        else:
                            M = np.zeros((n + 2 * m, n + 2 * m), dtype=np.float64)
                            M[:n, :n] = A * dt_k
                            if m > 0:
                                M[:n, n : n + m] = B * dt_k
                                M[n : n + m, n + m :] = np.eye(m, dtype=np.float64)
                            E = scipy.linalg.expm(M)
                            if not np.all(np.isfinite(E)):
                                raise NumericalInconclusiveError("expm FOH produziu valores não finitos.")
                            if is_uniform:
                                cached_E = E
                        aug = np.concatenate([x_traj[k, :], u_arr[k, :], u_arr[k + 1, :] - u_arr[k, :]])
                        x_next = E[:n, :] @ aug
                        if not np.all(np.isfinite(x_next)) or float(np.max(np.abs(x_next))) > 1e150:
                            raise NumericalInconclusiveError(f"Divergência numérica FOH em t={t_arr[k + 1]}.")
                        x_traj[k + 1, :] = x_next
                else:
                    used_method = f"solve_ivp.{resolved}"
                    if u_callable is not None:
                        def _rhs(tau: float, x_vec: np.ndarray) -> np.ndarray:
                            u_t = _eval_callable_input(u_callable, tau, m)
                            return A @ x_vec + B @ u_t
                    else:
                        def _rhs(tau: float, x_vec: np.ndarray) -> np.ndarray:
                            u_t = _interp_input_piecewise_linear(t_arr, u_arr, float(tau))
                            return A @ x_vec + B @ u_t

                    sol = scipy.integrate.solve_ivp(
                        _rhs,
                        (float(t_arr[0]), float(t_arr[-1])),
                        x0_vec,
                        method=resolved,
                        t_eval=t_arr,
                        rtol=float(rtol),
                        atol=float(atol),
                    )
                    if not sol.success or sol.y.shape != (n, N) or not np.all(np.isfinite(sol.y)):
                        raise NumericalInconclusiveError(
                            f"Integrador {resolved} falhou na simulação LTI: {sol.message}"
                        )
                    x_traj = np.array(sol.y.T, dtype=np.float64)
            else:
                used_method = "static_evaluation" if n == 0 else "single_sample"

        # Saída y[k] = C x[k] + D u[k]
        y_traj = (x_traj @ plant.C.T) + (u_arr @ plant.D.T)
        if not np.all(np.isfinite(y_traj)):
            raise NumericalInconclusiveError("Trajetória de saída y contém valores não finitos.")

        assumptions = {
            "domain": domain,
            "dt": plant.dt,
            "method": used_method,
            "timestamps_preserved": True,
            "n_samples": N,
            "n_states": n,
            "n_inputs": m,
            "n_outputs": p,
        }
        diagnostics = {
            "method_used": used_method,
            "n_samples": N,
            "t_start": float(t_arr[0]),
            "t_end": float(t_arr[-1]),
            "max_abs_state": float(np.max(np.abs(x_traj))) if x_traj.size > 0 else 0.0,
            "max_abs_output": float(np.max(np.abs(y_traj))) if y_traj.size > 0 else 0.0,
        }
        prov_ok = build_provenance(
            f"statespace.simulate_lti.{used_method}",
            tolerances={"rtol": float(rtol), "atol": float(atol)},
            model_revision=plant.revision,
        )
        return Result(
            status="warning" if warnings_out else "success",
            data={
                "t": t_arr,
                "x": x_traj,
                "u": u_arr,
                "y": y_traj,
                "dt": plant.dt,
                "state_names": list(plant.state_names),
                "input_names": list(plant.input_names),
                "output_names": list(plant.output_names),
                "units": plant.units,
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
    except (ValueError, np.linalg.LinAlgError) as exc:
        err = NumericalInconclusiveError(f"Falha numérica em simulate_lti: {exc}")
        return handle_failure(
            err,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )
