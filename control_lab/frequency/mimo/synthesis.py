"""Síntese MIMO no domínio da frequência: Desacoplamento SVD/ALIGN, Simulação em Malha Fechada e H-infinito Misto (Seções 5.5, 10.2 e 13.5)."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import scipy.linalg
import scipy.signal

from control_lab.core.controllers import DynamicController, StateFeedbackController, _validate_feedback_sign
from control_lab.core.models import StateSpace, TransferFunction
from control_lab.core.tensors import check_dt_compatible, complex_to_pair, ensure_finite_float64, validate_sample_time
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    NumericalInconclusiveError,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
)
from control_lab.frequency.siso._utils import (
    DEFAULT_N_OMEGA,
    handle_failure,
    resolve_omega_grid,
    sort_complex_roots,
)

from .analysis import _eval_model_matrix_at_omega, rga


def _to_state_space(
    model: Any,
    *,
    expected_dt: float | None = None,
    has_expected_dt: bool = False,
    expected_shape: tuple[int, int] | None = None,
    name: str = "modelo",
) -> StateSpace:
    """Converte TransferFunction, StateSpace, DynamicController ou matriz/vetor de ganho para StateSpace canônico."""
    ss: StateSpace
    if isinstance(model, StateSpace):
        ss = model
    elif isinstance(model, TransferFunction):
        ss = model.to_state_space()
    elif isinstance(model, DynamicController):
        ss = StateSpace(
            A=model.Ac,
            B=model.Bc,
            C=model.Cc,
            D=model.Dc,
            dt=model.dt,
            id=model.id,
            revision=model.revision,
        )
    elif isinstance(model, StateFeedbackController):
        p_k, m_k = model.K.shape
        ss = StateSpace(
            A=np.zeros((0, 0), dtype=np.float64),
            B=np.zeros((0, m_k), dtype=np.float64),
            C=np.zeros((p_k, 0), dtype=np.float64),
            D=model.K,
            dt=model.dt,
            id=model.id,
            revision=model.revision,
        )
    elif isinstance(model, (np.ndarray, list, tuple)):
        arr = ensure_finite_float64(model, name=name)
        if arr.ndim == 1:
            D_mat = np.diag(arr)
        elif arr.ndim == 2:
            D_mat = arr
        else:
            raise ValidationError(f"{name} deve ser matriz 2D ou vetor diagonal 1D, recebido {arr.ndim}D.")
        p_d, m_d = D_mat.shape
        dt_val = expected_dt if has_expected_dt else None
        ss = StateSpace(
            A=np.zeros((0, 0), dtype=np.float64),
            B=np.zeros((0, m_d), dtype=np.float64),
            C=np.zeros((p_d, 0), dtype=np.float64),
            D=D_mat,
            dt=dt_val,
        )
    elif isinstance(model, dict) and model.get("kind") == "StateSpace":
        ss = StateSpace.from_dict(model)
    elif isinstance(model, dict) and model.get("kind") == "TransferFunction":
        ss = TransferFunction.from_dict(model).to_state_space()
    else:
        raise UnsupportedModelError(
            message=f"{name} não suportado: {type(model).__name__}.",
            parameters={"model_type": type(model).__name__},
            next_step="Forneça StateSpace, TransferFunction, DynamicController ou matriz de ganho.",
        )

    if has_expected_dt:
        if (ss.dt is None) != (expected_dt is None):
            # Ganhos estáticos (0 estados) passados como array já herdaram expected_dt;
            # instâncias explícitas devem ter dt compatível.
            raise ValidationError(
                f"Incompatibilidade de domínio temporal entre planta (dt={expected_dt}) e {name} (dt={ss.dt})."
            )
        if ss.dt is not None and expected_dt is not None:
            check_dt_compatible(ss.dt, expected_dt)

    if expected_shape is not None and (ss.n_outputs, ss.n_inputs) != expected_shape:
        raise DimensionMismatchError(
            f"Dimensões incompatíveis para {name}: esperado {expected_shape}, recebido ({ss.n_outputs}, {ss.n_inputs})."
        )
    return ss


def _series_ss(sys2: StateSpace, sys1: StateSpace) -> StateSpace:
    """Composição em série sys2(s) * sys1(s) (saída de sys1 entra em sys2)."""
    if sys1.n_outputs != sys2.n_inputs:
        raise DimensionMismatchError(
            f"Composição em série incompatível: sys1 tem {sys1.n_outputs} saídas, sys2 tem {sys2.n_inputs} entradas."
        )
    if (sys1.dt is None) != (sys2.dt is None):
        raise ValidationError("Incompatibilidade de domínio (contínuo vs discreto) na composição em série.")
    if sys1.dt is not None and sys2.dt is not None:
        check_dt_compatible(sys1.dt, sys2.dt)

    n1, n2 = sys1.n_states, sys2.n_states
    p2, m1 = sys2.n_outputs, sys1.n_inputs
    n_tot = n1 + n2

    A = np.zeros((n_tot, n_tot), dtype=np.float64)
    B = np.zeros((n_tot, m1), dtype=np.float64)
    C = np.zeros((p2, n_tot), dtype=np.float64)

    if n1 > 0:
        A[:n1, :n1] = sys1.A
        B[:n1, :] = sys1.B
        C[:, :n1] = sys2.D @ sys1.C
    if n2 > 0:
        A[n1:, n1:] = sys2.A
        B[n1:, :] = sys2.B @ sys1.D
        C[:, n1:] = sys2.C
    if n1 > 0 and n2 > 0:
        A[n1:, :n1] = sys2.B @ sys1.C
    D = sys2.D @ sys1.D

    return StateSpace(A=A, B=B, C=C, D=D, dt=sys1.dt)


def _align_real_precompensator(G0: np.ndarray) -> np.ndarray:
    """Calcula pré-compensador real W0 via SVD / algoritmo ALIGN de Maciejowski em G(jw0)."""
    m = G0.shape[0]
    svals = np.linalg.svd(G0, compute_uv=False)
    s_max = float(svals[0]) if svals.size > 0 else 0.0
    s_min = float(svals[-1]) if svals.size > 0 else 0.0
    if s_max == 0.0 or s_min <= 1e-12 * max(1.0, s_max):
        raise NumericalInconclusiveError(
            message="Planta singular ou mal condicionada na frequência alvo; não é possível calcular desacoplador ALIGN.",
            parameters={"sigma_min": s_min, "sigma_max": s_max},
            next_step="Escolha outra frequência omega_target onde G(jw0) seja inversível.",
        )

    # M = G0^{-1} via solve (sem np.linalg.inv)
    M = np.linalg.solve(G0.astype(np.complex128), np.eye(m, dtype=np.complex128))
    W0 = np.zeros((m, m), dtype=np.float64)
    for j in range(m):
        mj = M[:, j]
        x = np.real(mj)
        y = np.imag(mj)
        num_ang = 2.0 * float(np.dot(x, y))
        den_ang = float(np.dot(x, x) - np.dot(y, y))
        theta = 0.5 * math.atan2(num_ang, den_ang)
        wj = x * math.cos(theta) + y * math.sin(theta)
        # Escolher sinal para manter parte real do elemento diagonal positiva
        diag_val = complex(np.dot(G0[j, :], wj))
        if diag_val.real < 0.0:
            wj = -wj
        W0[:, j] = wj

    # Fallback se alguma coluna resultar nula ou W0 singular
    s_w = np.linalg.svd(W0, compute_uv=False)
    if float(s_w[-1]) <= 1e-12 * max(1.0, float(s_w[0])):
        # Fallback SVD na parte real ou pseudoinversa real alinhada
        U, s_g, Vh = np.linalg.svd(G0)
        G_pinv_real = np.real(Vh.conj().T @ np.diag(1.0 / s_g) @ U.conj().T)
        W0 = G_pinv_real
    return W0


def design_svd_decoupler(
    plant: Any,
    omega_target: float = 1.0,
    realization_mode: str = "static",
    *,
    dt: float | None = None,
    raise_on_error: bool = True,
) -> Result:
    """Projeta pré-compensador desacoplador real W1(s) via SVD / Maciejowski ALIGN em omega_target."""
    prov = build_provenance("frequency.mimo.design_svd_decoupler", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(omega_target, (int, float)) or isinstance(omega_target, bool) or not math.isfinite(float(omega_target)) or float(omega_target) < 0.0:
            raise ValidationError("omega_target deve ser um escalar real finito >= 0.")
        w0 = float(omega_target)

        if realization_mode not in ("static", "first_order"):
            raise ValidationError(
                f"realization_mode inválido '{realization_mode}'. Use 'static' ou 'first_order'."
            )

        plant_dt = getattr(plant, "dt", None)
        if dt is not None:
            dt_val = validate_sample_time(dt)
            if plant_dt is not None:
                check_dt_compatible(plant_dt, dt_val)
            eff_dt = dt_val
        else:
            eff_dt = plant_dt

        G_ss = _to_state_space(plant, name="plant")
        if eff_dt is not None and G_ss.dt is None:
            raise ValidationError("Parâmetro dt fornecido para planta contínua.")
        p, m = G_ss.n_outputs, G_ss.n_inputs
        if p != m or m < 2:
            raise DimensionMismatchError(
                f"Desacoplamento MIMO exige planta quadrada com p == m >= 2; recebido ({p}x{m})."
            )

        w_arr = np.array([w0], dtype=np.float64)
        eval_info = _eval_model_matrix_at_omega(G_ss, w_arr)
        warnings_out.extend(eval_info["warnings"])
        G0 = eval_info["G"][0]

        s_before = np.linalg.svd(G0, compute_uv=False)
        kappa_before = float(s_before[0] / s_before[-1]) if float(s_before[-1]) > 0.0 else float("inf")

        W0 = _align_real_precompensator(G0)

        if realization_mode == "static":
            W1_model: StateSpace | TransferFunction = StateSpace(
                A=np.zeros((0, 0), dtype=np.float64),
                B=np.zeros((0, m), dtype=np.float64),
                C=np.zeros((m, 0), dtype=np.float64),
                D=W0,
                dt=eff_dt,
            )
            W1_ss = W1_model
        else:
            # Realização própria de 1ª ordem com frequência de corte além de omega_target
            omega_c = 5.0 * max(w0, 1.0)
            num_mat: list[list[list[float]]] = []
            den_mat: list[list[list[float]]] = []
            if eff_dt is None:
                gain_comp = math.sqrt(omega_c**2 + w0**2) / omega_c
                for i in range(m):
                    row_n: list[list[float]] = []
                    row_d: list[list[float]] = []
                    for j in range(m):
                        row_n.append([float(W0[i, j] * omega_c * gain_comp)])
                        row_d.append([1.0, omega_c])
                    num_mat.append(row_n)
                    den_mat.append(row_d)
            else:
                alpha = math.exp(-omega_c * eff_dt)
                for i in range(m):
                    row_n = []
                    row_d = []
                    for j in range(m):
                        row_n.append([float(W0[i, j] * (1.0 - alpha))])
                        row_d.append([1.0, -alpha])
                    num_mat.append(row_n)
                    den_mat.append(row_d)
            W1_model = TransferFunction(num=num_mat, den=den_mat, dt=eff_dt)
            W1_ss = W1_model.to_state_space()

        G_des_ss = _series_ss(G_ss, W1_ss)

        # Avaliar G_des(jw0) e RGA antes/depois
        eval_after = _eval_model_matrix_at_omega(G_des_ss, w_arr)
        G_des0 = eval_after["G"][0]
        s_after = np.linalg.svd(G_des0, compute_uv=False)
        kappa_after = float(s_after[0] / s_after[-1]) if float(s_after[-1]) > 0.0 else float("inf")

        rga_before_res = rga(G_ss, [w0], raise_on_error=True)
        rga_after_res = rga(G_des_ss, [w0], raise_on_error=True)
        assert rga_before_res.data is not None and rga_after_res.data is not None

        def _extract_rga_matrix(rga_res_data: dict[str, Any]) -> np.ndarray:
            entry = rga_res_data["entries"][0]
            if entry["status"] != "defined" or entry["rga_matrix"] is None:
                raise NumericalInconclusiveError("RGA indefinida na frequência alvo.")
            rm = entry["rga_matrix"]
            arr_re = np.asarray(rm["real"], dtype=np.float64)
            arr_im = np.asarray(rm["imag"], dtype=np.float64)
            return (arr_re + 1j * arr_im).reshape((m, m))

        rga_before_c = _extract_rga_matrix(rga_before_res.data)
        rga_after_c = _extract_rga_matrix(rga_after_res.data)
        rga_before = np.real(rga_before_c)
        rga_after = np.real(rga_after_c)

        offdiag_before = float(np.linalg.norm(rga_before_c - np.eye(m, dtype=np.complex128)))
        offdiag_after = float(np.linalg.norm(rga_after_c - np.eye(m, dtype=np.complex128)))

        assumptions = {
            "domain": "continuous" if eff_dt is None else "discrete",
            "dt": eff_dt,
            "omega_target": w0,
            "realization_mode": realization_mode,
            "n_channels": m,
        }
        diagnostics = {
            "kappa_before": kappa_before,
            "kappa_after": kappa_after,
            "rga_offdiag_norm_before": offdiag_before,
            "rga_offdiag_norm_after": offdiag_after,
            "decoupler_states": W1_ss.n_states,
            "decoupled_plant_states": G_des_ss.n_states,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "decoupler": W1_model.to_dict(),
                "decoupled_plant": G_des_ss.to_dict(),
                "omega_target": w0,
                "realization_mode": realization_mode,
                "kappa_before": kappa_before,
                "kappa_after": kappa_after,
                "rga_before": rga_before,
                "rga_after": rga_after,
                "rga_offdiag_norm_before": offdiag_before,
                "rga_offdiag_norm_after": offdiag_after,
                "series_semantics": "numeric_verified",
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


def simulate_mimo_closed_loop(
    plant: Any,
    controller: Any = None,
    *,
    decoupler: Any = None,
    feedback_sign: str = "negative",
    t_final: float = 10.0,
    n_points: int = 200,
    raise_on_error: bool = True,
) -> Result:
    """Compõe L(s) = G(s) W1(s) K(s), fecha a malha T(s) = L(I +- L)^{-1} e simula degrau canal a canal."""
    prov = build_provenance("frequency.mimo.simulate_mimo_closed_loop", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sign_str = _validate_feedback_sign(feedback_sign)
        if not isinstance(t_final, (int, float)) or isinstance(t_final, bool) or not math.isfinite(float(t_final)) or float(t_final) <= 0.0:
            raise ValidationError("t_final deve ser positivo e finito.")
        if not isinstance(n_points, int) or isinstance(n_points, bool) or n_points < 2:
            raise ValidationError("n_points deve ser inteiro >= 2.")

        G_ss = _to_state_space(plant, name="plant")
        p, m = G_ss.n_outputs, G_ss.n_inputs
        dt = G_ss.dt

        if decoupler is None:
            W_ss = StateSpace(
                A=np.zeros((0, 0), dtype=np.float64),
                B=np.zeros((0, m), dtype=np.float64),
                C=np.zeros((m, 0), dtype=np.float64),
                D=np.eye(m, dtype=np.float64),
                dt=dt,
            )
        else:
            W_ss = _to_state_space(
                decoupler,
                expected_dt=dt,
                has_expected_dt=True,
                expected_shape=(m, m),
                name="decoupler",
            )

        if controller is None:
            if p != m:
                raise DimensionMismatchError(
                    f"Simulação sem controlador explícito exige planta quadrada (p == m), recebido ({p}x{m})."
                )
            K_ss = StateSpace(
                A=np.zeros((0, 0), dtype=np.float64),
                B=np.zeros((0, p), dtype=np.float64),
                C=np.zeros((m, 0), dtype=np.float64),
                D=np.eye(m, dtype=np.float64),
                dt=dt,
            )
        else:
            K_ss = _to_state_space(
                controller,
                expected_dt=dt,
                has_expected_dt=True,
                expected_shape=(m, p),
                name="controller",
            )

        # L(s) = G(s) * W(s) * K(s) -> entradas = p, saídas = p
        GW_ss = _series_ss(G_ss, W_ss)
        L_ss = _series_ss(GW_ss, K_ss)

        s_fb = 1.0 if sign_str == "negative" else -1.0
        eye_p = np.eye(p, dtype=np.float64)
        M_loop = eye_p + s_fb * L_ss.D
        s_loop = np.linalg.svd(M_loop, compute_uv=False)
        if float(s_loop[-1]) <= 1e-12 * max(1.0, float(s_loop[0])):
            raise NumericalInconclusiveError(
                message="Malha fechada algebricamente mal posta: det(I +- D_L) == 0.",
                parameters={"sigma_min": float(s_loop[-1])},
                next_step="Verifique os ganhos diretos D da planta, desacoplador e controlador.",
            )

        # C_cl = M_loop^-1 C_L, D_cl = M_loop^-1 D_L
        if L_ss.n_states > 0:
            C_cl = np.linalg.solve(M_loop, L_ss.C)
            D_cl = np.linalg.solve(M_loop, L_ss.D)
            A_cl = L_ss.A - s_fb * (L_ss.B @ C_cl)
            B_cl = L_ss.B @ (eye_p - s_fb * D_cl)
        else:
            A_cl = np.zeros((0, 0), dtype=np.float64)
            B_cl = np.zeros((0, p), dtype=np.float64)
            C_cl = np.zeros((p, 0), dtype=np.float64)
            D_cl = np.linalg.solve(M_loop, L_ss.D)

        T_ss = StateSpace(A=A_cl, B=B_cl, C=C_cl, D=D_cl, dt=dt)

        if T_ss.n_states > 0:
            cl_poles = sort_complex_roots(np.linalg.eigvals(A_cl))
            if dt is None:
                is_stable = bool(np.all(np.real(cl_poles) < -1e-9))
            else:
                is_stable = bool(np.all(np.abs(cl_poles) < 1.0 - 1e-9))
        else:
            cl_poles = np.array([], dtype=np.complex128)
            is_stable = True

        if not is_stable:
            warnings_out.append(
                WarningItem(
                    code="CLOSED_LOOP_UNSTABLE",
                    message="Sistema em malha fechada apresenta polos instáveis ou na fronteira de estabilidade.",
                )
            )

        # Simulação canal a canal: r_j(t) = e_j * 1(t) para j = 0..p-1
        if dt is None:
            t_grid = np.linspace(0.0, float(t_final), int(n_points), dtype=np.float64)
            step_resp = np.zeros((p, int(n_points), p), dtype=np.float64)
            for j in range(p):
                if T_ss.n_states == 0:
                    step_resp[j, :, :] = np.broadcast_to(D_cl[:, j][None, :], (int(n_points), p))
                else:
                    sys_j = scipy.signal.StateSpace(A_cl, B_cl[:, j : j + 1], C_cl, D_cl[:, j : j + 1])
                    _, y_j = scipy.signal.step(sys_j, T=t_grid)
                    if y_j.ndim == 1:
                        y_j = y_j[:, None]
                    step_resp[j, :, :] = y_j
        else:
            n_steps = max(2, min(int(n_points), int(round(float(t_final) / dt)) + 1))
            t_grid = np.arange(n_steps, dtype=np.float64) * dt
            step_resp = np.zeros((p, n_steps, p), dtype=np.float64)
            for j in range(p):
                if T_ss.n_states == 0:
                    step_resp[j, :, :] = np.broadcast_to(D_cl[:, j][None, :], (n_steps, p))
                else:
                    sys_j = scipy.signal.StateSpace(A_cl, B_cl[:, j : j + 1], C_cl, D_cl[:, j : j + 1], dt=dt)
                    _, y_j = scipy.signal.dstep(sys_j, n=n_steps)
                    y_arr = np.asarray(y_j[0], dtype=np.float64)
                    if y_arr.ndim == 1:
                        y_arr = y_arr[:, None]
                    step_resp[j, :, :] = y_arr[:n_steps, :]

        if not (np.all(np.isfinite(step_resp))):
            raise NumericalInconclusiveError("Simulação produziu valores não-finitos (overflow numérico).")

        max_cross_coupling = 0.0
        if p >= 2:
            for j in range(p):
                for i in range(p):
                    if i != j:
                        peak_ij = float(np.max(np.abs(step_resp[j, :, i])))
                        if peak_ij > max_cross_coupling:
                            max_cross_coupling = peak_ij

        assumptions = {
            "feedback_sign": sign_str,
            "domain": "continuous" if dt is None else "discrete",
            "dt": dt,
            "n_channels": p,
        }
        diagnostics = {
            "is_stable": is_stable,
            "n_closed_loop_states": T_ss.n_states,
            "max_cross_coupling": max_cross_coupling,
            "t_final": float(t_grid[-1]),
            "n_points": int(t_grid.size),
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "t": t_grid,
                "step_responses": step_resp,
                "max_cross_coupling": max_cross_coupling,
                "closed_loop_poles": complex_to_pair(cl_poles),
                "is_stable": is_stable,
                "closed_loop_system": T_ss.to_dict(),
                "units": {"time": "s"},
                "series_semantics": "numeric_verified",
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


def _expand_weight_to_ss(
    spec: Any,
    dim: int,
    kind: str,
) -> StateSpace:
    """Constrói StateSpace (dim x dim) para filtro de ponderação W_S, W_U ou W_T."""
    if spec is None:
        if kind == "ws":
            spec = {"dc_gain": 100.0, "wb": 1.0, "m_s": 2.0}
        elif kind == "wu":
            spec = {"gain": 0.1}
        elif kind == "wt":
            spec = {"wt": 10.0, "m_t": 2.0, "at": 0.01}
        else:
            raise ValidationError(f"Tipo de peso desconhecido: {kind}")

    if isinstance(spec, (StateSpace, TransferFunction, DynamicController)):
        ss = _to_state_space(spec, expected_dt=None, has_expected_dt=True, name=kind)
        if ss.n_outputs == 1 and ss.n_inputs == 1 and dim > 1:
            # Replicar diagonalmente W(s) * I_dim
            n_s = ss.n_states
            A_blk = scipy.linalg.block_diag(*([ss.A] * dim)) if n_s > 0 else np.zeros((0, 0), dtype=np.float64)
            B_blk = scipy.linalg.block_diag(*([ss.B] * dim)) if n_s > 0 else np.zeros((0, dim), dtype=np.float64)
            C_blk = scipy.linalg.block_diag(*([ss.C] * dim)) if n_s > 0 else np.zeros((dim, 0), dtype=np.float64)
            D_blk = scipy.linalg.block_diag(*([ss.D] * dim))
            return StateSpace(A=A_blk, B=B_blk, C=C_blk, D=D_blk, dt=None)
        if (ss.n_outputs, ss.n_inputs) != (dim, dim):
            raise DimensionMismatchError(f"Peso {kind} deve ser 1x1 ou {dim}x{dim}, recebido ({ss.n_outputs}x{ss.n_inputs}).")
        return ss

    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        gain = float(spec)
        if not math.isfinite(gain) or gain < 0.0:
            raise ValidationError(f"Ganho escalar de {kind} deve ser finito e >= 0.")
        return StateSpace(
            A=np.zeros((0, 0), dtype=np.float64),
            B=np.zeros((0, dim), dtype=np.float64),
            C=np.zeros((dim, 0), dtype=np.float64),
            D=gain * np.eye(dim, dtype=np.float64),
            dt=None,
        )

    if isinstance(spec, dict):
        if kind == "ws":
            dc_gain = float(spec.get("dc_gain", 100.0))
            wb = float(spec.get("wb", 1.0))
            m_s = float(spec.get("m_s", 2.0))
            if dc_gain <= 0.0 or wb <= 0.0 or m_s <= 0.0:
                raise ValidationError("Parâmetros de w_s (dc_gain, wb, m_s) devem ser > 0.")
            a_s = 1.0 / dc_gain
            # W_S(s) = (s/M_S + w_B) / (s + w_B * A_S)
            tf_1 = TransferFunction(num=[1.0 / m_s, wb], den=[1.0, wb * a_s], dt=None)
            return _expand_weight_to_ss(tf_1, dim, kind)
        if kind == "wu":
            if "wb" in spec or "wu" in spec:
                wu = float(spec.get("wu", spec.get("wb", 10.0)))
                m_u = float(spec.get("m_u", 2.0))
                a_u = float(spec.get("a_u", spec.get("dc_gain", 0.05)))
                if wu <= 0.0 or m_u <= 0.0 or a_u <= 0.0:
                    raise ValidationError("Parâmetros de w_u devem ser > 0.")
                # Passa-alta própria: (s + wu * a_u) / (s / m_u + wu) -> (m_u * s + m_u * wu * a_u) / (s + m_u * wu)
                tf_1 = TransferFunction(num=[m_u, m_u * wu * a_u], den=[1.0, m_u * wu], dt=None)
                return _expand_weight_to_ss(tf_1, dim, kind)
            gain = float(spec.get("gain", spec.get("dc_gain", 0.1)))
            if gain <= 0.0:
                raise ValidationError("Ganho de w_u deve ser > 0 para manter D12 com posto completo.")
            return _expand_weight_to_ss(gain, dim, kind)
        if kind == "wt":
            wt = float(spec.get("wt", spec.get("wb", 10.0)))
            m_t = float(spec.get("m_t", 2.0))
            if "at" in spec or "a_t" in spec:
                a_t = float(spec.get("at", spec.get("a_t")))
            elif "hf_gain" in spec:
                a_t = 1.0 / float(spec["hf_gain"])
            else:
                a_t = 0.01
            if wt <= 0.0 or m_t <= 0.0 or a_t <= 0.0:
                raise ValidationError("Parâmetros de w_t (wt, m_t, at) devem ser > 0.")
            # W_T(s) = (s + w_T / M_T) / (A_T * s + w_T)
            tf_1 = TransferFunction(num=[1.0, wt / m_t], den=[a_t, wt], dt=None)
            return _expand_weight_to_ss(tf_1, dim, kind)

    raise UnsupportedModelError(f"Especificação de peso {kind} não suportada: {type(spec).__name__}.")


def _build_mixed_sensitivity_generalized_plant(
    G: StateSpace,
    W_S: StateSpace,
    W_U: StateSpace,
    W_T: StateSpace,
) -> dict[str, Any]:
    """Constrói a planta generalizada P(s) de 2 portas: [w; u] -> [z; y_meas], com y_meas = w - G u."""
    ng, p, m = G.n_states, G.n_outputs, G.n_inputs
    ns, nu_s, nt = W_S.n_states, W_U.n_states, W_T.n_states
    n_tot = ng + ns + nu_s + nt

    # Blocos de estado x = [x_g; x_s; x_u; x_t]
    A = scipy.linalg.block_diag(G.A, W_S.A, W_U.A, W_T.A)
    # Acoplamentos de x_g para x_s e x_t:
    # x_s_dot = A_s x_s + B_s (-C_g x_g + w - D_g u)
    # x_t_dot = A_t x_t + B_t (C_g x_g + D_g u)
    idx_s = ng
    idx_u = ng + ns
    idx_t = ng + ns + nu_s
    if ng > 0 and ns > 0:
        A[idx_s:idx_u, :ng] = -W_S.B @ G.C
    if ng > 0 and nt > 0:
        A[idx_t:n_tot, :ng] = W_T.B @ G.C

    B1 = np.zeros((n_tot, p), dtype=np.float64)
    if ns > 0:
        B1[idx_s:idx_u, :] = W_S.B

    B2 = np.zeros((n_tot, m), dtype=np.float64)
    if ng > 0:
        B2[:ng, :] = G.B
    if ns > 0:
        B2[idx_s:idx_u, :] = -W_S.B @ G.D
    if nu_s > 0:
        B2[idx_u:idx_t, :] = W_U.B
    if nt > 0:
        B2[idx_t:n_tot, :] = W_T.B @ G.D

    # Saídas z = [z1 (p); z2 (m); z3 (p)]
    nz = p + m + p
    C1 = np.zeros((nz, n_tot), dtype=np.float64)
    if ng > 0:
        C1[:p, :ng] = -W_S.D @ G.C
        C1[p + m :, :ng] = W_T.D @ G.C
    if ns > 0:
        C1[:p, idx_s:idx_u] = W_S.C
    if nu_s > 0:
        C1[p : p + m, idx_u:idx_t] = W_U.C
    if nt > 0:
        C1[p + m :, idx_t:n_tot] = W_T.C

    D11 = np.zeros((nz, p), dtype=np.float64)
    D11[:p, :] = W_S.D

    D12 = np.zeros((nz, m), dtype=np.float64)
    D12[:p, :] = -W_S.D @ G.D
    D12[p : p + m, :] = W_U.D
    D12[p + m :, :] = W_T.D @ G.D

    # Saída medida y_meas = e = w - G u
    C2 = np.zeros((p, n_tot), dtype=np.float64)
    if ng > 0:
        C2[:, :ng] = -G.C
    D21 = np.eye(p, dtype=np.float64)
    D22 = -G.D.copy()

    return {
        "A": A,
        "B1": B1,
        "B2": B2,
        "C1": C1,
        "C2": C2,
        "D11": D11,
        "D12": D12,
        "D21": D21,
        "D22": D22,
        "n_states": n_tot,
        "n_w": p,
        "n_u": m,
        "n_z": nz,
        "n_y": p,
    }


def _try_solve_hinf_gamma(P: dict[str, Any], gamma: float) -> StateSpace | None:
    """Tenta sintetizar controlador subótimo H-infinito K(s) para um dado gamma via 2-Riccati (Glover-Doyle)."""
    A = P["A"]
    B1, B2 = P["B1"], P["B2"]
    C1, C2 = P["C1"], P["C2"]
    D11, D12, D21, D22 = P["D11"], P["D12"], P["D21"], P["D22"]
    n, nw, nu, nz, ny = P["n_states"], P["n_w"], P["n_u"], P["n_z"], P["n_y"]

    # Escalonamento de entrada u -> u_s tal que D12_s^T D12_s = I_nu
    U12, s12, Vt12 = np.linalg.svd(D12, full_matrices=True)
    if s12.size < nu or float(s12[-1]) <= 1e-12 * max(1.0, float(s12[0])):
        return None
    T_u = Vt12.T / s12[None, :]
    B2_s = B2 @ T_u
    D12_s = U12[:, :nu]

    # Rotação de z: colocar D12_s nas últimas nu linhas -> D12_r = [0; I_nu]
    U_rot = np.hstack([U12[:, nu:], U12[:, :nu]])
    C1_r = U_rot.T @ C1
    D11_r = U_rot.T @ D11
    D12_r = U_rot.T @ D12_s

    # Escalonamento de saída y -> y_s tal que D21_s D21_s^T = I_ny
    U21, s21, Vt21 = np.linalg.svd(D21, full_matrices=True)
    if s21.size < ny or float(s21[-1]) <= 1e-12 * max(1.0, float(s21[0])):
        return None
    T_y = (U21 / s21[None, :]).T
    C2_s = T_y @ C2
    D21_s = T_y @ D21

    V_rot = np.hstack([Vt21[ny:, :].T, Vt21[:ny, :].T])
    B1_r = B1 @ V_rot
    D11_rr = D11_r @ V_rot
    D21_r = D21_s @ V_rot

    nz1 = nz - nu
    nw1 = nw - ny
    D1111 = D11_rr[:nz1, :nw1]
    D1112 = D11_rr[:nz1, nw1:]
    D1121 = D11_rr[nz1:, :nw1]
    D1122 = D11_rr[nz1:, nw1:]

    if nw1 > 0 and np.linalg.norm(np.hstack([D1111, D1112]), ord=2) >= gamma * (1.0 - 1e-9):
        return None
    if nz1 > 0 and nw1 > 0 and np.linalg.norm(np.vstack([D1111, D1121]), ord=2) >= gamma * (1.0 - 1e-9):
        return None
    if nw1 == 0 and nz1 > 0 and np.linalg.norm(D1112, ord=2) >= gamma * (1.0 - 1e-9):
        return None

    # Feedthrough central D_K0 para zerar D1122 via loop-shifting
    if nw1 > 0 and nz1 > 0:
        M_11 = (gamma**2) * np.eye(nw1) - D1111.T @ D1111
        D_K0 = -D1122 - D1121 @ np.linalg.solve(M_11, D1111.T @ D1112)
    else:
        D_K0 = -D1122

    # Aplicar loop-shift u_s = D_K0 y_s + u_tilde (note que D22 já é tratado no final)
    A_t = A + B2_s @ D_K0 @ C2_s
    B1_t = B1_r + B2_s @ D_K0 @ D21_r
    C1_t = C1_r + D12_r @ D_K0 @ C2_s
    D11_t = D11_rr + D12_r @ D_K0 @ D21_r

    B_all = np.hstack([B1_t, B2_s])
    D_all = np.hstack([D11_t, D12_r])
    R_x = D_all.T @ D_all - np.diag(np.concatenate([np.full(nw, gamma**2), np.zeros(nu)]))
    S_x = C1_t.T @ D_all
    Q_x = C1_t.T @ C1_t

    C_all = np.vstack([C1_t, C2_s])
    D_yall = np.vstack([D11_t, D21_r])
    R_y = D_yall @ D_yall.T - np.diag(np.concatenate([np.full(nz, gamma**2), np.zeros(ny)]))
    S_y = B1_t @ D_yall.T
    Q_y = B1_t @ B1_t.T

    try:
        X = scipy.linalg.solve_continuous_are(A_t, B_all, Q_x, R_x, s=S_x)
        Y = scipy.linalg.solve_continuous_are(A_t.T, C_all.T, Q_y, R_y, s=S_y)
    except Exception:
        return None

    X = 0.5 * (X + X.T)
    Y = 0.5 * (Y + Y.T)
    if not (np.all(np.isfinite(X)) and np.all(np.isfinite(Y))):
        return None

    # Verificar PSD (tolerância numérica pequena)
    if np.min(np.linalg.eigvalsh(X)) < -1e-7 or np.min(np.linalg.eigvalsh(Y)) < -1e-7:
        return None

    # Verificar autovalores dos Hamiltonianos fora do eixo imaginário
    H_x = np.block([
        [A_t - B_all @ np.linalg.solve(R_x, S_x.T), -B_all @ np.linalg.solve(R_x, B_all.T)],
        [-Q_x + S_x @ np.linalg.solve(R_x, S_x.T), -(A_t - B_all @ np.linalg.solve(R_x, S_x.T)).T],
    ])
    H_y = np.block([
        [A_t.T - C_all.T @ np.linalg.solve(R_y, S_y.T), -C_all.T @ np.linalg.solve(R_y, C_all)],
        [-Q_y + S_y @ np.linalg.solve(R_y, S_y.T), -(A_t.T - C_all.T @ np.linalg.solve(R_y, S_y.T)).T],
    ])
    if np.min(np.abs(np.real(np.linalg.eigvals(H_x)))) < 1e-8 or np.min(np.abs(np.real(np.linalg.eigvals(H_y)))) < 1e-8:
        return None

    # Verificar raio espectral rho(X Y) < gamma^2
    rho = float(np.max(np.abs(np.linalg.eigvals(X @ Y)))) if n > 0 else 0.0
    if rho >= (gamma**2) * (1.0 - 1e-7):
        return None

    F = -np.linalg.solve(R_x, B_all.T @ X + S_x.T)
    F1 = F[:nw, :]
    F2 = F[nw:, :]
    L = -(Y @ C_all.T + S_y) @ np.linalg.solve(R_y, np.eye(nz + ny))
    L2 = L[:, nz:]

    Z = np.linalg.solve(np.eye(n) - (gamma**-2) * (Y @ X), np.eye(n))
    B_K_s = -Z @ L2
    C_K_s = F2
    A_K_s = A_t + B_all @ F - B_K_s @ (C2_s + D21_r @ F1)

    # Desfazer escalonamento de entrada/saída e adicionar D_K0: K_0(s) = T_u * (K_s + D_K0) * T_y
    A_k = A_K_s
    B_k = B_K_s @ T_y
    C_k = T_u @ C_K_s
    D_k = T_u @ D_K0 @ T_y

    # Desfazer D22 != 0: K = K_0 (I + D22 K_0)^{-1}
    if np.any(D22 != 0.0):
        M_d = np.eye(ny) + D22 @ D_k
        s_md = np.linalg.svd(M_d, compute_uv=False)
        if float(s_md[-1]) <= 1e-10 * max(1.0, float(s_md[0])):
            return None
        # (I + D22 D_k)^{-1} D22 C_k, etc.
        C_k_new = np.linalg.solve(np.eye(nu) + D_k @ D22, C_k)
        D_k_new = np.linalg.solve(np.eye(nu) + D_k @ D22, D_k)
        A_k = A_k - B_k @ D22 @ C_k_new
        B_k = B_k @ (np.eye(ny) - D22 @ D_k_new)
        C_k = C_k_new
        D_k = D_k_new

    # Verificar estabilidade em malha fechada com P original
    M_cl = np.eye(ny) - D22 @ D_k
    s_mcl = np.linalg.svd(M_cl, compute_uv=False)
    if float(s_mcl[-1]) <= 1e-10 * max(1.0, float(s_mcl[0])):
        return None
    D_k_cl = np.linalg.solve(np.eye(nu) - D_k @ D22, D_k)
    C_k_cl = np.linalg.solve(np.eye(nu) - D_k @ D22, C_k)
    A_cl = np.block([
        [A + B2 @ D_k_cl @ C2, B2 @ C_k_cl],
        [B_k @ (C2 + D22 @ D_k_cl @ C2), A_k + B_k @ D22 @ C_k_cl],
    ])
    cl_eigs = np.linalg.eigvals(A_cl)
    if not np.all(np.real(cl_eigs) < -1e-7):
        return None

    return StateSpace(A=A_k, B=B_k, C=C_k, D=D_k, dt=None)


def _eval_closed_loop_tzw_norm(P: dict[str, Any], K: StateSpace, omega: np.ndarray) -> float:
    """Avalia ||T_zw(jw)||_inf na grade omega."""
    A, B1, B2 = P["A"], P["B1"], P["B2"]
    C1, C2 = P["C1"], P["C2"]
    D11, D12, D21, D22 = P["D11"], P["D12"], P["D21"], P["D22"]
    ny = P["n_y"]
    nu = P["n_u"]

    # Fechamento u = K y_meas com y_meas = C2 x + D21 w + D22 u
    S_u = np.eye(nu) - K.D @ D22
    C_k_cl = np.linalg.solve(S_u, K.C)
    D_k_cl = np.linalg.solve(S_u, K.D)

    A_cl = np.block([
        [A + B2 @ D_k_cl @ C2, B2 @ C_k_cl],
        [K.B @ (C2 + D22 @ D_k_cl @ C2), K.A + K.B @ D22 @ C_k_cl],
    ])
    B_cl = np.vstack([
        B1 + B2 @ D_k_cl @ D21,
        K.B @ (D21 + D22 @ D_k_cl @ D21),
    ])
    C_cl = np.hstack([C1 + D12 @ D_k_cl @ C2, D12 @ C_k_cl])
    D_cl = D11 + D12 @ D_k_cl @ D21

    n_cl = A_cl.shape[0]
    eye_cl = np.eye(n_cl, dtype=np.complex128)
    max_sv = 0.0
    for w_val in omega:
        M_w = 1j * float(w_val) * eye_cl - A_cl
        T_w = C_cl @ np.linalg.solve(M_w, B_cl) + D_cl
        sv = float(np.linalg.svd(T_w, compute_uv=False)[0])
        if sv > max_sv:
            max_sv = sv
    return max_sv


def design_hinf_mixed_sensitivity(
    plant: Any,
    *,
    w_s: Any = None,
    w_u: Any = None,
    w_t: Any = None,
    omega: Any = None,
    gamma_tol: float = 1e-2,
    raise_on_error: bool = True,
) -> Result:
    """Síntese H-infinito de sensibilidade mista (S/KS/T) via bisseção em gamma e 2-Riccati (Glover-Doyle)."""
    prov = build_provenance("frequency.mimo.design_hinf_mixed_sensitivity", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(gamma_tol, (int, float)) or isinstance(gamma_tol, bool) or not math.isfinite(float(gamma_tol)) or float(gamma_tol) <= 0.0:
            raise ValidationError("gamma_tol deve ser positivo e finito.")

        G_ss = _to_state_space(plant, name="plant")
        if G_ss.dt is not None:
            raise UnsupportedModelError(
                message="Síntese H-infinito contínua (2-Riccati DGKF) suporta apenas modelos contínuos (dt=None).",
                parameters={"dt": G_ss.dt},
                next_step="Converta o modelo para tempo contínuo antes de executar design_hinf_mixed_sensitivity().",
            )
        p, m = G_ss.n_outputs, G_ss.n_inputs
        if p != m or p < 1:
            raise DimensionMismatchError(
                f"Síntese H-infinito mista exige planta SISO ou MIMO quadrada (p == m >= 1); recebido ({p}x{m})."
            )

        W_S = _expand_weight_to_ss(w_s, p, "ws")
        W_U = _expand_weight_to_ss(w_u, m, "wu")
        W_T = _expand_weight_to_ss(w_t, p, "wt")

        P = _build_mixed_sensitivity_generalized_plant(G_ss, W_S, W_U, W_T)
        w_grid, w_warns = resolve_omega_grid(omega, dt=None, n_points=300)
        warnings_out.extend(w_warns)

        # Encontrar limite superior viável gamma_hi por duplicação
        gamma_hi = 1.0
        K_best: StateSpace | None = None
        for _ in range(30):
            K_cand = _try_solve_hinf_gamma(P, gamma_hi)
            if K_cand is not None:
                K_best = K_cand
                break
            gamma_hi *= 2.0

        if K_best is None:
            raise NumericalInconclusiveError(
                message="Não foi possível encontrar gamma viável para o problema H-infinito (verifique estabilizabilidade/detectabilidade e pesos).",
                next_step="Verifique se a planta é estabilizável/detectável e se W_U possui ganho não-nulo em alta frequência.",
            )

        # Bisseção entre gamma_lo e gamma_hi
        gamma_lo = max(1e-3, float(np.linalg.norm(W_S.D, ord=2)) * 0.5)
        if gamma_lo >= gamma_hi:
            gamma_lo = 0.1 * gamma_hi

        # Garantir que gamma_lo é inviável ou reduzir
        while _try_solve_hinf_gamma(P, gamma_lo) is not None and gamma_lo > 1e-4:
            gamma_hi = gamma_lo
            K_best = _try_solve_hinf_gamma(P, gamma_hi)
            gamma_lo *= 0.5

        gamma_achieved = gamma_hi
        for _ in range(40):
            if (gamma_hi - gamma_lo) <= float(gamma_tol) * max(1.0, gamma_hi):
                break
            gamma_mid = 0.5 * (gamma_lo + gamma_hi)
            K_cand = _try_solve_hinf_gamma(P, gamma_mid)
            if K_cand is not None:
                K_best = K_cand
                gamma_hi = gamma_mid
                gamma_achieved = gamma_mid
            else:
                gamma_lo = gamma_mid

        assert K_best is not None
        hinf_norm_grid = _eval_closed_loop_tzw_norm(P, K_best, w_grid)

        # Avaliar S(jw), T(jw), 1/|W_S(jw)|, 1/|W_T(jw)| na grade
        G_eval = _eval_model_matrix_at_omega(G_ss, w_grid)["G"]
        K_eval = _eval_model_matrix_at_omega(K_best, w_grid)["G"]
        WS_eval = _eval_model_matrix_at_omega(W_S, w_grid)["G"]
        WT_eval = _eval_model_matrix_at_omega(W_T, w_grid)["G"]

        N_w = w_grid.size
        sigma_S = np.zeros(N_w, dtype=np.float64)
        sigma_T = np.zeros(N_w, dtype=np.float64)
        inv_ws_bound = np.zeros(N_w, dtype=np.float64)
        inv_wt_bound = np.zeros(N_w, dtype=np.float64)
        eye_p = np.eye(p, dtype=np.complex128)

        for idx in range(N_w):
            L_w = G_eval[idx] @ K_eval[idx]
            S_w = np.linalg.solve(eye_p + L_w, eye_p)
            T_w = eye_p - S_w
            sigma_S[idx] = float(np.linalg.svd(S_w, compute_uv=False)[0])
            sigma_T[idx] = float(np.linalg.svd(T_w, compute_uv=False)[0])

            sv_ws_min = float(np.linalg.svd(WS_eval[idx], compute_uv=False)[-1])
            sv_wt_min = float(np.linalg.svd(WT_eval[idx], compute_uv=False)[-1])
            inv_ws_bound[idx] = float(gamma_achieved / max(sv_ws_min, 1e-12))
            inv_wt_bound[idx] = float(gamma_achieved / max(sv_wt_min, 1e-12))

        # Verificar estabilidade em malha fechada de (I + G K)^{-1}
        GK_ss = _series_ss(G_ss, K_best)
        M_cl = eye_p + GK_ss.D
        C_cl = np.linalg.solve(M_cl, GK_ss.C) if GK_ss.n_states > 0 else np.zeros((p, 0))
        A_cl = GK_ss.A - GK_ss.B @ C_cl if GK_ss.n_states > 0 else np.zeros((0, 0))
        cl_poles = np.linalg.eigvals(A_cl) if A_cl.size > 0 else np.array([], dtype=np.complex128)
        is_stable = bool(np.all(np.real(cl_poles) < -1e-7)) if cl_poles.size > 0 else True

        gp_summary = {
            "n_states": int(P["n_states"]),
            "n_w": int(P["n_w"]),
            "n_u": int(P["n_u"]),
            "n_z": int(P["n_z"]),
            "n_y": int(P["n_y"]),
        }

        assumptions = {
            "domain": "continuous",
            "dt": None,
            "n_channels": p,
            "gamma_tol": float(gamma_tol),
        }
        diagnostics = {
            "gamma_achieved": float(gamma_achieved),
            "hinf_norm_grid": float(hinf_norm_grid),
            "is_stable": is_stable,
            "controller_states": K_best.n_states,
            "generalized_plant_summary": gp_summary,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "controller": K_best.to_dict(),
                "generalized_plant_summary": gp_summary,
                "gamma_achieved": float(gamma_achieved),
                "hinf_norm_grid": float(hinf_norm_grid),
                "is_stable": is_stable,
                "omega": w_grid,
                "sigma_S": sigma_S,
                "sigma_T": sigma_T,
                "inv_ws_bound": inv_ws_bound,
                "inv_wt_bound": inv_wt_bound,
                "units": {"frequency": "rad/s"},
                "series_semantics": "numeric_verified",
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
