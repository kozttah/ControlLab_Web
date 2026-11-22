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


def _normalize_omega_targets(
    omega_target: float | Sequence[float],
    omega_targets: Sequence[float] | None,
) -> list[float]:
    """Valida, converte e ordena/deduplica frequências alvo >= 0."""
    raw_source: Any = omega_targets if omega_targets is not None else omega_target
    if isinstance(raw_source, (int, float, np.number)) and not isinstance(raw_source, bool):
        val = float(raw_source)
        if not math.isfinite(val) or val < 0.0:
            raise ValidationError("omega_target deve ser um escalar real finito >= 0.")
        return [val]

    if isinstance(raw_source, (str, bytes)):
        raise ValidationError("omega_target / omega_targets deve ser um escalar ou sequência de floats >= 0.")

    if isinstance(raw_source, np.ndarray):
        if raw_source.ndim != 1:
            raise ValidationError("omega_targets como array deve ser 1D.")
        items = list(raw_source.tolist())
    elif isinstance(raw_source, Sequence):
        items = list(raw_source)
    else:
        raise ValidationError("omega_target / omega_targets deve ser um escalar ou sequência de floats >= 0.")

    if len(items) == 0:
        raise ValidationError("omega_targets não pode ser vazio.")

    parsed: list[float] = []
    for item in items:
        if not isinstance(item, (int, float, np.number)) or isinstance(item, bool):
            raise ValidationError("Todos os elementos de omega_targets devem ser números reais finitos >= 0.")
        val = float(item)
        if not math.isfinite(val) or val < 0.0:
            raise ValidationError("Todos os elementos de omega_targets devem ser números reais finitos >= 0.")
        parsed.append(val)

    omega_list = sorted(set(parsed))
    if not omega_list:
        raise ValidationError("omega_targets não pode ser vazio.")
    return omega_list


def _stabilize_denominator(
    den_coeffs: np.ndarray,
    *,
    is_discrete: bool,
) -> np.ndarray:
    """Reflete polos instáveis ou na fronteira para garantir denominador estritamente estável e mônico."""
    den = np.asarray(den_coeffs, dtype=np.float64)
    if den.size <= 1:
        return np.array([1.0], dtype=np.float64)
    if abs(den[0]) < 1e-15:
        den = den.copy()
        den[0] = 1.0
    else:
        den = den / den[0]

    roots = np.roots(den)
    stabilized = np.empty_like(roots, dtype=np.complex128)
    for idx, r in enumerate(roots):
        if is_discrete:
            mag = abs(r)
            if mag >= 0.999:
                stabilized[idx] = (0.98 * r / mag) if mag > 0.0 else 0.0 + 0.0j
            else:
                stabilized[idx] = r
        else:
            if r.real >= -1e-4:
                stabilized[idx] = complex(-abs(r.real) - 1e-3, r.imag)
            else:
                stabilized[idx] = r

    den_stable = np.real(np.poly(stabilized)).astype(np.float64)
    den_stable[0] = 1.0
    return den_stable


def _solve_numerator_for_denominator(
    s_arr: np.ndarray,
    h_arr: np.ndarray,
    den_coeffs: np.ndarray,
    order: int,
    *,
    reg: float = 1e-12,
) -> tuple[np.ndarray, float]:
    """Dado D(s) fixo e estável, resolve os coeficientes reais b_d..b_0 por mínimos quadrados."""
    n_w = s_arr.size
    n_num = order + 1
    d_vals = np.polyval(den_coeffs, s_arr)

    A_c = np.zeros((n_w, n_num), dtype=np.complex128)
    for col, pwr in enumerate(range(order, -1, -1)):
        A_c[:, col] = (s_arr**pwr) / d_vals

    A_r = np.vstack([np.real(A_c), np.imag(A_c)])
    y_r = np.concatenate([np.real(h_arr), np.imag(h_arr)])

    A_aug = np.vstack([A_r, math.sqrt(reg) * np.eye(n_num, dtype=np.float64)])
    y_aug = np.concatenate([y_r, np.zeros(n_num, dtype=np.float64)])
    b_coeffs, _, _, _ = np.linalg.lstsq(A_aug, y_aug, rcond=None)

    approx = np.polyval(b_coeffs, s_arr) / d_vals
    err = float(np.sum(np.abs(approx - h_arr) ** 2))
    return b_coeffs.astype(np.float64), err


def _fit_rational_entry_sk(
    s_arr: np.ndarray,
    h_arr: np.ndarray,
    den_init: np.ndarray,
    order: int,
    *,
    is_discrete: bool,
    n_iter: int = 8,
    reg: float = 1e-10,
) -> tuple[list[float], list[float]]:
    """Ajuste racional próprio estável via Sanathanan-Koerner iterativo."""
    if order == 0:
        b0 = float(np.mean(np.real(h_arr)))
        return [b0], [1.0]

    n_w = s_arr.size
    n_num = order + 1
    n_den = order
    n_params = n_num + n_den

    den_curr = _stabilize_denominator(den_init, is_discrete=is_discrete)
    best_num, best_err = _solve_numerator_for_denominator(s_arr, h_arr, den_curr, order)
    best_den = den_curr.copy()

    for _ in range(n_iter):
        d_prev = np.polyval(den_curr, s_arr)
        weights = 1.0 / np.maximum(np.abs(d_prev), 1e-12)

        A_c = np.zeros((n_w, n_params), dtype=np.complex128)
        for col, pwr in enumerate(range(order, -1, -1)):
            A_c[:, col] = weights * (s_arr**pwr)
        for col, pwr in enumerate(range(order - 1, -1, -1)):
            A_c[:, n_num + col] = -weights * h_arr * (s_arr**pwr)
        y_c = weights * h_arr * (s_arr**order)

        A_r = np.vstack([np.real(A_c), np.imag(A_c)])
        y_r = np.concatenate([np.real(y_c), np.imag(y_c)])

        A_aug = np.vstack([A_r, math.sqrt(reg) * np.eye(n_params, dtype=np.float64)])
        y_aug = np.concatenate([y_r, np.zeros(n_params, dtype=np.float64)])
        theta, _, _, _ = np.linalg.lstsq(A_aug, y_aug, rcond=None)

        if not np.all(np.isfinite(theta)):
            break

        den_cand = np.concatenate([[1.0], theta[n_num:]])
        den_stable = _stabilize_denominator(den_cand, is_discrete=is_discrete)
        num_cand, err_cand = _solve_numerator_for_denominator(s_arr, h_arr, den_stable, order)

        if math.isfinite(err_cand) and err_cand < best_err:
            best_err = err_cand
            best_num = num_cand
            best_den = den_stable

        den_curr = den_stable

    return [float(x) for x in best_num], [float(x) for x in best_den]


def _fit_rational_entry_continuous(
    w_arr: np.ndarray,
    w_ideal_ij: np.ndarray,
    order: int,
) -> tuple[list[float], list[float]]:
    """Ajusta W_ij(s) racional própria e estritamente estável de ordem `order`."""
    if order == 0:
        b0 = float(np.mean(np.real(w_ideal_ij)))
        return [b0], [1.0]

    w_min = float(np.min(w_arr))
    w_max = float(np.max(w_arr))
    a_low = max(0.05, 0.2 * w_min)
    a_high = max(1.0, 5.0 * w_max)
    if a_high <= a_low:
        a_high = a_low * 10.0
    poles_0 = -np.geomspace(a_low, a_high, order)
    den_init = np.real(np.poly(poles_0)).astype(np.float64)
    s_arr = 1j * w_arr
    return _fit_rational_entry_sk(
        s_arr,
        w_ideal_ij.astype(np.complex128),
        den_init,
        order,
        is_discrete=False,
    )


def _fit_rational_entry_discrete(
    w_arr: np.ndarray,
    dt: float,
    w_ideal_ij: np.ndarray,
    order: int,
) -> tuple[list[float], list[float]]:
    """Ajusta W_ij(z) racional própria e estritamente estável de ordem `order`."""
    if order == 0:
        b0 = float(np.mean(np.real(w_ideal_ij)))
        return [b0], [1.0]

    poles_0 = np.linspace(0.1, 0.85, order) if order > 1 else np.array([0.5])
    den_init = np.real(np.poly(poles_0)).astype(np.float64)
    z_arr = np.exp(1j * w_arr * dt)
    return _fit_rational_entry_sk(
        z_arr,
        w_ideal_ij.astype(np.complex128),
        den_init,
        order,
        is_discrete=True,
    )


def _build_static_w0(
    G_mats: list[np.ndarray],
    W0_list: list[np.ndarray],
    D_targets: list[np.ndarray],
    m: int,
) -> np.ndarray:
    """Calcula pré-compensador estático real W0 por mínimos quadrados multi-frequência."""
    if len(G_mats) == 1:
        return W0_list[0]

    A_blocks: list[np.ndarray] = []
    B_blocks: list[np.ndarray] = []
    for k in range(len(G_mats)):
        G_k = G_mats[k]
        D_k = D_targets[k]
        A_blocks.append(np.real(G_k))
        A_blocks.append(np.imag(G_k))
        B_blocks.append(np.real(D_k))
        B_blocks.append(np.imag(D_k))
    A_ls = np.vstack(A_blocks)
    B_ls = np.vstack(B_blocks)
    W0_ls, _, _, s_ls = np.linalg.lstsq(A_ls, B_ls, rcond=None)
    s_w = np.linalg.svd(W0_ls, compute_uv=False) if np.all(np.isfinite(W0_ls)) else np.array([0.0])
    if (
        s_ls.size < m
        or float(s_ls[-1]) <= 1e-12 * max(1.0, float(s_ls[0]))
        or float(s_w[-1]) <= 1e-12 * max(1.0, float(s_w[0]))
        or not np.all(np.isfinite(W0_ls))
    ):
        return np.mean(np.stack(W0_list, axis=0), axis=0)
    return W0_ls


def _build_decoupler_candidate(
    order: int,
    *,
    m: int,
    eff_dt: float | None,
    w_arr: np.ndarray,
    w_rep: float,
    G_mats: list[np.ndarray],
    W0_list: list[np.ndarray],
    D_targets: list[np.ndarray],
    W_ideal: np.ndarray,
    prefer_single_freq_fo: bool = False,
) -> tuple[StateSpace | TransferFunction, StateSpace, float]:
    """Constrói candidato W1 de ordem `order` e calcula seu erro relativo de ajuste em W_ideal."""
    n_w = w_arr.size
    if order == 0:
        W0 = _build_static_w0(G_mats, W0_list, D_targets, m)
        W1_model: StateSpace | TransferFunction = StateSpace(
            A=np.zeros((0, 0), dtype=np.float64),
            B=np.zeros((0, m), dtype=np.float64),
            C=np.zeros((m, 0), dtype=np.float64),
            D=W0,
            dt=eff_dt,
        )
        W1_ss = W1_model
    elif n_w == 1 and order == 1 and prefer_single_freq_fo:
        W0 = W0_list[0]
        omega_c = 5.0 * max(w_rep, 1.0)
        num_mat: list[list[list[float]]] = []
        den_mat: list[list[list[float]]] = []
        if eff_dt is None:
            gain_comp = math.sqrt(omega_c**2 + w_rep**2) / omega_c
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
    else:
        num_mat = []
        den_mat = []
        for i in range(m):
            row_n = []
            row_d = []
            for j in range(m):
                w_ij = W_ideal[:, i, j]
                if eff_dt is None:
                    n_ij, d_ij = _fit_rational_entry_continuous(w_arr, w_ij, order)
                else:
                    n_ij, d_ij = _fit_rational_entry_discrete(w_arr, eff_dt, w_ij, order)
                row_n.append(n_ij)
                row_d.append(d_ij)
            num_mat.append(row_n)
            den_mat.append(row_d)
        W1_model = TransferFunction(num=num_mat, den=den_mat, dt=eff_dt)
        W1_ss = W1_model.to_state_space()

    W1_mats = _eval_model_matrix_at_omega(W1_ss, w_arr)["G"]
    num_err = 0.0
    den_norm = 0.0
    for k in range(n_w):
        diff = W1_mats[k] - W_ideal[k]
        num_err += float(np.sum(np.abs(diff) ** 2))
        den_norm += float(np.sum(np.abs(W_ideal[k]) ** 2))
    fit_rel_err = math.sqrt(num_err / max(den_norm, 1e-24))
    return W1_model, W1_ss, fit_rel_err


def design_svd_decoupler(
    plant: Any,
    omega_target: float | Sequence[float] = 1.0,
    realization_mode: str = "auto",
    *,
    omega_targets: Sequence[float] | None = None,
    order: int | None = None,
    dt: float | None = None,
    raise_on_error: bool = True,
) -> Result:
    """Projeta pré-compensador desacoplador W1(s) via SVD / Maciejowski ALIGN em uma ou múltiplas frequências."""
    prov = build_provenance("frequency.mimo.design_svd_decoupler", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        omega_list = _normalize_omega_targets(omega_target, omega_targets)
        n_w = len(omega_list)
        rep_idx = n_w // 2
        w_rep = omega_list[rep_idx]

        if realization_mode not in ("auto", "static", "first_order", "rational"):
            raise ValidationError(
                f"realization_mode inválido '{realization_mode}'. Use 'auto', 'static', 'first_order' ou 'rational'."
            )

        if order is not None:
            if not isinstance(order, int) or isinstance(order, bool) or order < 0 or order > 6:
                raise ValidationError("order deve ser None ou inteiro no intervalo [0, 6].")

        if realization_mode == "static":
            if order is not None and order != 0:
                raise ValidationError("realization_mode='static' é incompatível com order != 0.")
            eff_order: int | None = 0
            order_mode = "manual"
        elif realization_mode == "first_order":
            if order is not None and order != 1:
                raise ValidationError("realization_mode='first_order' é incompatível com order != 1.")
            eff_order = 1
            order_mode = "manual"
        elif order is not None:
            eff_order = int(order)
            order_mode = "manual"
        else:
            eff_order = None
            order_mode = "auto"

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

        w_arr = np.asarray(omega_list, dtype=np.float64)
        eval_info = _eval_model_matrix_at_omega(G_ss, w_arr)
        warnings_out.extend(eval_info["warnings"])
        G_mats = eval_info["G"]

        W0_list: list[np.ndarray] = []
        for k in range(n_w):
            W0_k = _align_real_precompensator(G_mats[k])
            if k > 0:
                for j in range(m):
                    if float(np.dot(W0_k[:, j], W0_list[0][:, j])) < 0.0:
                        W0_k[:, j] = -W0_k[:, j]
            W0_list.append(W0_k)

        D_targets: list[np.ndarray] = []
        W_ideal = np.zeros((n_w, m, m), dtype=np.complex128)
        for k in range(n_w):
            diag_gw = np.diag(G_mats[k] @ W0_list[k]).copy()
            for j in range(m):
                if abs(diag_gw[j]) < 1e-12:
                    diag_gw[j] = 1.0 + 0.0j
            D_k = np.diag(diag_gw)
            D_targets.append(D_k)
            W_ideal[k] = np.linalg.solve(G_mats[k].astype(np.complex128), D_k.astype(np.complex128))

        def _extract_rga_matrix_at(rga_res_data: dict[str, Any], idx: int) -> np.ndarray:
            entry = rga_res_data["entries"][idx]
            if entry["status"] != "defined" or entry["rga_matrix"] is None:
                raise NumericalInconclusiveError("RGA indefinida na frequência alvo.")
            rm = entry["rga_matrix"]
            arr_re = np.asarray(rm["real"], dtype=np.float64)
            arr_im = np.asarray(rm["imag"], dtype=np.float64)
            return (arr_re + 1j * arr_im).reshape((m, m))

        if eff_order is not None:
            order_used = eff_order
            W1_model, W1_ss, fit_relative_error = _build_decoupler_candidate(
                order_used,
                m=m,
                eff_dt=eff_dt,
                w_arr=w_arr,
                w_rep=w_rep,
                G_mats=G_mats,
                W0_list=W0_list,
                D_targets=D_targets,
                W_ideal=W_ideal,
                prefer_single_freq_fo=(realization_mode == "first_order"),
            )
            G_des_ss = _series_ss(G_ss, W1_ss)
        else:
            # Seleção automática da menor ordem própria em 0..4
            has_freq_variation = False
            if n_w > 1:
                base_norm = max(float(np.linalg.norm(W_ideal[0])), 1e-12)
                max_var = max(float(np.linalg.norm(W_ideal[k] - W_ideal[0])) / base_norm for k in range(1, n_w))
                has_freq_variation = max_var > 0.05

            candidates: list[tuple[int, StateSpace | TransferFunction, StateSpace, StateSpace, float, float]] = []
            chosen: tuple[int, StateSpace | TransferFunction, StateSpace, StateSpace, float] | None = None

            for d_cand in range(0, 5):
                W1_m_c, W1_ss_c, fit_err_c = _build_decoupler_candidate(
                    d_cand,
                    m=m,
                    eff_dt=eff_dt,
                    w_arr=w_arr,
                    w_rep=w_rep,
                    G_mats=G_mats,
                    W0_list=W0_list,
                    D_targets=D_targets,
                    W_ideal=W_ideal,
                    prefer_single_freq_fo=False,
                )
                G_des_c = _series_ss(G_ss, W1_ss_c)
                rga_cand_res = rga(G_des_c, omega_list, raise_on_error=True)
                assert rga_cand_res.data is not None
                max_offdiag_c = max(
                    float(np.linalg.norm(_extract_rga_matrix_at(rga_cand_res.data, k) - np.eye(m, dtype=np.complex128)))
                    for k in range(n_w)
                )
                score_c = fit_err_c + 0.5 * max_offdiag_c
                candidates.append((d_cand, W1_m_c, W1_ss_c, G_des_c, fit_err_c, score_c))

                if d_cand == 0 and has_freq_variation and fit_err_c > 0.05:
                    continue
                if fit_err_c <= 0.05 or max_offdiag_c <= 0.15:
                    chosen = (d_cand, W1_m_c, W1_ss_c, G_des_c, fit_err_c)
                    break

            if chosen is None:
                best_cand = min(candidates, key=lambda item: item[5])
                chosen = (best_cand[0], best_cand[1], best_cand[2], best_cand[3], best_cand[4])

            order_used, W1_model, W1_ss, G_des_ss, fit_relative_error = chosen

        # Avaliar G_des(jw_k) e RGA antes/depois em todas as frequências alvo
        eval_after = _eval_model_matrix_at_omega(G_des_ss, w_arr)
        G_des_mats = eval_after["G"]

        rga_before_res = rga(G_ss, omega_list, raise_on_error=True)
        rga_after_res = rga(G_des_ss, omega_list, raise_on_error=True)
        assert rga_before_res.data is not None and rga_after_res.data is not None

        per_frequency: list[dict[str, Any]] = []
        rga_before_list: list[np.ndarray] = []
        for k, w_k in enumerate(omega_list):
            s_before_k = np.linalg.svd(G_mats[k], compute_uv=False)
            kappa_before_k = float(s_before_k[0] / s_before_k[-1]) if float(s_before_k[-1]) > 0.0 else float("inf")

            s_after_k = np.linalg.svd(G_des_mats[k], compute_uv=False)
            kappa_after_k = float(s_after_k[0] / s_after_k[-1]) if float(s_after_k[-1]) > 0.0 else float("inf")

            rga_before_c_k = _extract_rga_matrix_at(rga_before_res.data, k)
            rga_after_c_k = _extract_rga_matrix_at(rga_after_res.data, k)
            rga_before_list.append(np.real(rga_before_c_k))
            rga_after_k = np.real(rga_after_c_k)

            offdiag_before_k = float(np.linalg.norm(rga_before_c_k - np.eye(m, dtype=np.complex128)))
            offdiag_after_k = float(np.linalg.norm(rga_after_c_k - np.eye(m, dtype=np.complex128)))

            per_frequency.append(
                {
                    "omega": float(w_k),
                    "kappa_before": kappa_before_k,
                    "kappa_after": kappa_after_k,
                    "rga_offdiag_norm_before": offdiag_before_k,
                    "rga_offdiag_norm_after": offdiag_after_k,
                    "rga_after": rga_after_k,
                }
            )

        rep_entry = per_frequency[rep_idx]
        kappa_before = float(rep_entry["kappa_before"])
        kappa_after = float(rep_entry["kappa_after"])
        rga_before = rga_before_list[rep_idx]
        rga_after = rep_entry["rga_after"]
        offdiag_before = float(rep_entry["rga_offdiag_norm_before"])
        offdiag_after = float(rep_entry["rga_offdiag_norm_after"])

        assumptions = {
            "domain": "continuous" if eff_dt is None else "discrete",
            "dt": eff_dt,
            "omega_target": w_rep,
            "omega_targets": omega_list,
            "realization_mode": realization_mode,
            "order_mode": order_mode,
            "n_channels": m,
        }
        diagnostics = {
            "kappa_before": kappa_before,
            "kappa_after": kappa_after,
            "rga_offdiag_norm_before": offdiag_before,
            "rga_offdiag_norm_after": offdiag_after,
            "decoupler_states": W1_ss.n_states,
            "decoupled_plant_states": G_des_ss.n_states,
            "n_omega_targets": n_w,
            "order_used": order_used,
            "fit_relative_error": fit_relative_error,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "decoupler": W1_model.to_dict(),
                "decoupled_plant": G_des_ss.to_dict(),
                "omega_target": w_rep,
                "omega_targets": omega_list,
                "per_frequency": per_frequency,
                "realization_mode": realization_mode,
                "order_used": order_used,
                "order_mode": order_mode,
                "fit_relative_error": fit_relative_error,
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


def _build_closed_loop_tzw(
    P: dict[str, Any],
    K: StateSpace,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Constrói realização (A_cl, B_cl, C_cl, D_cl) de T_zw = F_l(P, K)."""
    A, B1, B2 = P["A"], P["B1"], P["B2"]
    C1, C2 = P["C1"], P["C2"]
    D11, D12, D21, D22 = P["D11"], P["D12"], P["D21"], P["D22"]
    nu = P["n_u"]

    # Fechamento u = K y_meas com y_meas = C2 x + D21 w + D22 u
    S_u = np.eye(nu, dtype=np.float64) - K.D @ D22
    s_su = np.linalg.svd(S_u, compute_uv=False)
    if s_su.size > 0 and float(s_su[-1]) <= 1e-12 * max(1.0, float(s_su[0])):
        raise NumericalInconclusiveError(
            message="Interconexão LFT algebricamente mal posta: det(I - D_K D_22) == 0.",
            parameters={"sigma_min": float(s_su[-1])},
        )

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
    return A_cl, B_cl, C_cl, D_cl


def _eval_sv_max_at_omega(
    A_cl: np.ndarray,
    B_cl: np.ndarray,
    C_cl: np.ndarray,
    D_cl: np.ndarray,
    w: float,
) -> float:
    """Avalia sigma_max(C_cl (jw I - A_cl)^{-1} B_cl + D_cl) para uma frequência w >= 0."""
    n_cl = A_cl.shape[0]
    if n_cl == 0:
        return float(np.linalg.svd(D_cl, compute_uv=False)[0]) if D_cl.size > 0 else 0.0
    M_w = 1j * float(w) * np.eye(n_cl, dtype=np.complex128) - A_cl
    try:
        T_w = C_cl @ np.linalg.solve(M_w, B_cl) + D_cl
    except np.linalg.LinAlgError:
        return float("inf")
    return float(np.linalg.svd(T_w, compute_uv=False)[0])


def _hamiltonian_brl_check(
    A_cl: np.ndarray,
    B_cl: np.ndarray,
    C_cl: np.ndarray,
    D_cl: np.ndarray,
    gamma: float,
    *,
    imag_tol: float = 1e-8,
) -> tuple[bool, float, np.ndarray]:
    """Testa ||T_zw||_inf < gamma pelo Lema Real Limitado usando o Hamiltoniano H(gamma).

    Retorna (no_imag_axis_eigs, min_abs_real, imag_omegas_nonneg).
    """
    n_cl = A_cl.shape[0]
    nw = B_cl.shape[1]
    sigma_D = float(np.linalg.svd(D_cl, compute_uv=False)[0]) if D_cl.size > 0 else 0.0
    if not math.isfinite(gamma) or gamma <= sigma_D * (1.0 + 1e-12):
        return False, 0.0, np.array([], dtype=np.float64)

    if n_cl == 0:
        return True, float(gamma - sigma_D), np.array([], dtype=np.float64)

    R_gamma = (gamma**2) * np.eye(nw, dtype=np.float64) - D_cl.T @ D_cl
    R_gamma = 0.5 * (R_gamma + R_gamma.T)
    min_eig_R = float(np.min(np.linalg.eigvalsh(R_gamma)))
    if not math.isfinite(min_eig_R) or min_eig_R <= 1e-12 * max(1.0, gamma**2):
        return False, 0.0, np.array([], dtype=np.float64)

    try:
        M_B = np.linalg.solve(R_gamma, B_cl.T)
        M_DC = np.linalg.solve(R_gamma, D_cl.T @ C_cl)
    except np.linalg.LinAlgError:
        return False, 0.0, np.array([], dtype=np.float64)

    A_tilde = A_cl + B_cl @ M_DC
    G_blk = B_cl @ M_B
    G_blk = 0.5 * (G_blk + G_blk.T)
    Q_blk = C_cl.T @ (C_cl + D_cl @ M_DC)
    Q_blk = 0.5 * (Q_blk + Q_blk.T)

    H = np.block([
        [A_tilde, G_blk],
        [-Q_blk, -A_tilde.T],
    ])
    if not np.all(np.isfinite(H)):
        return False, 0.0, np.array([], dtype=np.float64)

    eigs = np.linalg.eigvals(H)
    abs_real = np.abs(np.real(eigs))
    min_abs_real = float(np.min(abs_real))

    imag_mask = abs_real <= imag_tol * np.maximum(1.0, np.abs(np.imag(eigs)))
    no_imag = bool(not np.any(imag_mask))

    if np.any(imag_mask):
        im_vals = np.imag(eigs[imag_mask])
        nonneg = im_vals[im_vals >= -1e-9]
        omegas = np.sort(np.maximum(nonneg, 0.0))
    else:
        omegas = np.array([], dtype=np.float64)

    return no_imag, min_abs_real, omegas


def _compute_exact_hinf_norm_hamiltonian(
    A_cl: np.ndarray,
    B_cl: np.ndarray,
    C_cl: np.ndarray,
    D_cl: np.ndarray,
    *,
    gamma_upper: float,
    tol: float = 1e-6,
    hinf_norm_grid: float = 0.0,
) -> dict[str, Any]:
    """Certifica ||T_zw||_inf < gamma_upper e calcula ||T_zw||_inf exata via Hamiltoniano (Bruinsma-Steinbuch 1990)."""
    A_cl = ensure_finite_float64(A_cl, name="A_cl")
    B_cl = ensure_finite_float64(B_cl, name="B_cl")
    C_cl = ensure_finite_float64(C_cl, name="C_cl")
    D_cl = ensure_finite_float64(D_cl, name="D_cl")
    if not math.isfinite(float(gamma_upper)) or float(gamma_upper) <= 0.0:
        raise ValidationError("gamma_upper deve ser positivo e finito.")
    if not math.isfinite(float(tol)) or float(tol) <= 0.0:
        raise ValidationError("tol deve ser positivo e finito.")

    n_cl = A_cl.shape[0]
    sigma_D = float(np.linalg.svd(D_cl, compute_uv=False)[0]) if D_cl.size > 0 else 0.0

    if n_cl > 0:
        cl_eigs = np.linalg.eigvals(A_cl)
        is_hurwitz = bool(np.all(np.real(cl_eigs) < -1e-9))
    else:
        cl_eigs = np.array([], dtype=np.complex128)
        is_hurwitz = True

    if not is_hurwitz:
        return {
            "hamiltonian_exact_verified": False,
            "hamiltonian_min_abs_real": 0.0,
            "hinf_norm_exact": float("nan"),
            "sigma_max_D_cl": sigma_D,
            "iterations": 0,
        }

    verified_upper, min_abs_real_upper, omegas_upper = _hamiltonian_brl_check(
        A_cl, B_cl, C_cl, D_cl, float(gamma_upper), imag_tol=1e-8
    )

    if n_cl == 0:
        return {
            "hamiltonian_exact_verified": bool(verified_upper),
            "hamiltonian_min_abs_real": float(min_abs_real_upper),
            "hinf_norm_exact": sigma_D,
            "sigma_max_D_cl": sigma_D,
            "iterations": 0,
        }

    # Limite inferior garantido: max(sigma_max(D_cl), grid, omega=0, frequências dos polos)
    gamma_lb = sigma_D
    if math.isfinite(float(hinf_norm_grid)) and float(hinf_norm_grid) > gamma_lb:
        gamma_lb = float(hinf_norm_grid)

    init_omegas: list[float] = [0.0]
    for eig in cl_eigs:
        im_abs = abs(float(np.imag(eig)))
        mag = abs(complex(eig))
        if im_abs > 0.0:
            init_omegas.append(im_abs)
        if mag > 0.0:
            init_omegas.append(mag)
    if omegas_upper.size > 0:
        init_omegas.extend(float(w) for w in omegas_upper)
        for idx in range(omegas_upper.size - 1):
            w0, w1 = float(omegas_upper[idx]), float(omegas_upper[idx + 1])
            init_omegas.append(0.5 * (w0 + w1))
            if w0 > 0.0 and w1 > 0.0:
                init_omegas.append(math.sqrt(w0 * w1))

    for w_init in init_omegas:
        sv_w = _eval_sv_max_at_omega(A_cl, B_cl, C_cl, D_cl, w_init)
        if math.isfinite(sv_w) and sv_w > gamma_lb:
            gamma_lb = sv_w

    # Limite superior inicial certificado
    if verified_upper:
        gamma_ub = float(gamma_upper)
    else:
        gamma_ub = max(float(gamma_upper), gamma_lb) * 1.1 + 1e-6
        for _ in range(30):
            ok_ub, _, _ = _hamiltonian_brl_check(A_cl, B_cl, C_cl, D_cl, gamma_ub, imag_tol=1e-8)
            if ok_ub:
                break
            gamma_ub *= 2.0

    # Iteração híbrida Bruinsma-Steinbuch + bisseção
    use_bs = True
    n_iter = 0
    eff_tol = min(float(tol), 1e-5)
    for it in range(1, 61):
        n_iter = it
        if (gamma_ub - gamma_lb) <= eff_tol * max(1.0, gamma_ub):
            break

        if use_bs:
            gamma_bs = gamma_lb * (1.0 + 0.5 * eff_tol)
            if gamma_bs < gamma_ub and gamma_bs > sigma_D * (1.0 + 1e-10):
                gamma_test = gamma_bs
            else:
                gamma_test = 0.5 * (gamma_lb + gamma_ub)
        else:
            gamma_test = 0.5 * (gamma_lb + gamma_ub)

        no_imag, _, omegas = _hamiltonian_brl_check(A_cl, B_cl, C_cl, D_cl, gamma_test, imag_tol=1e-8)
        if no_imag:
            gamma_ub = min(gamma_ub, gamma_test)
            use_bs = True
        else:
            prev_lb = gamma_lb
            if gamma_test > gamma_lb:
                gamma_lb = gamma_test
            if omegas.size > 0:
                dedup: list[float] = [float(omegas[0])]
                for w_val in omegas[1:]:
                    wf = float(w_val)
                    if wf - dedup[-1] > 1e-9 * max(1.0, wf):
                        dedup.append(wf)
                candidates: list[float] = list(dedup)
                for idx in range(len(dedup) - 1):
                    w0, w1 = dedup[idx], dedup[idx + 1]
                    candidates.append(0.5 * (w0 + w1))
                    if w0 > 0.0 and w1 > 0.0:
                        candidates.append(math.sqrt(w0 * w1))
                for w_c in candidates:
                    sv_c = _eval_sv_max_at_omega(A_cl, B_cl, C_cl, D_cl, w_c)
                    if math.isfinite(sv_c) and sv_c > gamma_lb:
                        gamma_lb = sv_c

            if gamma_lb >= gamma_ub:
                gamma_ub = gamma_lb
                break
            use_bs = bool(gamma_lb > prev_lb * (1.0 + eff_tol))

    hinf_norm_exact = 0.5 * (gamma_lb + gamma_ub)
    return {
        "hamiltonian_exact_verified": bool(verified_upper),
        "hamiltonian_min_abs_real": float(min_abs_real_upper),
        "hinf_norm_exact": float(hinf_norm_exact),
        "sigma_max_D_cl": sigma_D,
        "iterations": n_iter,
    }


def _solve_hinf_care(
    A: np.ndarray,
    B: np.ndarray,
    Q: np.ndarray,
    R: np.ndarray,
    S: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Resolve ARE contínua indefinida H-infinito com seleção de menor resíduo (balanced=False/True) e refinamento de Newton."""

    def _eval_care_candidate(X_raw: np.ndarray) -> tuple[np.ndarray, np.ndarray, float] | None:
        X_sym = 0.5 * (X_raw + X_raw.T)
        if not np.all(np.isfinite(X_sym)):
            return None
        try:
            K_mat = np.linalg.solve(R, B.T @ X_sym + S.T)
        except np.linalg.LinAlgError:
            return None
        A_cl = A - B @ K_mat
        if not np.all(np.isfinite(A_cl)):
            return None
        if np.max(np.real(np.linalg.eigvals(A_cl))) >= -1e-9:
            return None
        res_mat = A.T @ X_sym + X_sym @ A - (X_sym @ B + S) @ K_mat + Q
        denom = max(
            1.0,
            float(
                np.linalg.norm(Q, ord="fro")
                + np.linalg.norm(A.T @ X_sym, ord="fro")
                + np.linalg.norm(X_sym @ A, ord="fro")
            ),
        )
        res_rel = float(np.linalg.norm(res_mat, ord="fro") / denom)
        if not math.isfinite(res_rel):
            return None
        return X_sym, K_mat, res_rel

    best: tuple[np.ndarray, np.ndarray, float] | None = None
    for balanced_flag in (False, True):
        try:
            X_try = scipy.linalg.solve_continuous_are(A, B, Q, R, s=S, balanced=balanced_flag)
        except Exception:
            continue
        cand = _eval_care_candidate(X_try)
        if cand is not None and (best is None or cand[2] < best[2]):
            best = cand

    if best is None:
        return None

    # Refinamento de Newton-Kleinman (até 2 passos) se o resíduo ainda estiver acima de 1e-12
    X_cur, K_cur, res_cur = best
    for _ in range(2):
        if res_cur <= 1e-12:
            break
        res_mat = A.T @ X_cur + X_cur @ A - (X_cur @ B + S) @ K_cur + Q
        A_cl = A - B @ K_cur
        try:
            dX = scipy.linalg.solve_continuous_lyapunov(A_cl.T, -res_mat)
        except Exception:
            break
        cand_ref = _eval_care_candidate(X_cur + dX)
        if cand_ref is not None and cand_ref[2] < res_cur:
            X_cur, K_cur, res_cur = cand_ref
        else:
            break

    return X_cur, K_cur, res_cur


def _try_solve_hinf_gamma_detailed(P: dict[str, Any], gamma: float) -> dict[str, Any] | None:
    """Tenta sintetizar controlador subótimo H-infinito K(s) via 2-Riccati DGKF e emite certificados numéricos."""
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
        try:
            D_K0 = -D1122 - D1121 @ np.linalg.solve(M_11, D1111.T @ D1112)
        except np.linalg.LinAlgError:
            return None
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

    if n > 0:
        sol_X = _solve_hinf_care(A_t, B_all, Q_x, R_x, S_x)
        sol_Y = _solve_hinf_care(A_t.T, C_all.T, Q_y, R_y, S_y)
        if sol_X is None or sol_Y is None:
            return None
        X, K_x, riccati_X_residual_rel = sol_X
        Y, K_y, riccati_Y_residual_rel = sol_Y

        # Verificar PSD (tolerância numérica pequena)
        if np.min(np.linalg.eigvalsh(X)) < -1e-7 or np.min(np.linalg.eigvalsh(Y)) < -1e-7:
            return None

        if riccati_X_residual_rel > 1e-6 or riccati_Y_residual_rel > 1e-6:
            return None

        # Verificar autovalores dos Hamiltonianos fora do eixo imaginário
        try:
            Rx_SxT = np.linalg.solve(R_x, S_x.T)
            Rx_BallT = np.linalg.solve(R_x, B_all.T)
            Ry_SyT = np.linalg.solve(R_y, S_y.T)
            Ry_Call = np.linalg.solve(R_y, C_all)
        except np.linalg.LinAlgError:
            return None

        H_x = np.block([
            [A_t - B_all @ Rx_SxT, -B_all @ Rx_BallT],
            [-Q_x + S_x @ Rx_SxT, -(A_t - B_all @ Rx_SxT).T],
        ])
        H_y = np.block([
            [A_t.T - C_all.T @ Ry_SyT, -C_all.T @ Ry_Call],
            [-Q_y + S_y @ Ry_SyT, -(A_t.T - C_all.T @ Ry_SyT).T],
        ])
        if np.min(np.abs(np.real(np.linalg.eigvals(H_x)))) < 1e-8 or np.min(np.abs(np.real(np.linalg.eigvals(H_y)))) < 1e-8:
            return None

        # Verificar raio espectral rho(X Y) < gamma^2
        rho_XY = float(np.max(np.abs(np.linalg.eigvals(X @ Y))))
        coupling_margin = float(gamma**2 - rho_XY)
        if not math.isfinite(rho_XY) or rho_XY >= (gamma**2) * (1.0 - 1e-7):
            return None

        F = -K_x
        F1 = F[:nw, :]
        F2 = F[nw:, :]
        L = -(K_y.T)
        L2 = L[:, nz:]

        try:
            Z = np.linalg.solve(np.eye(n) - (gamma**-2) * (Y @ X), np.eye(n))
        except np.linalg.LinAlgError:
            return None
        B_K_s = -Z @ L2
        C_K_s = F2
        A_K_s = A_t + B_all @ F - B_K_s @ (C2_s + D21_r @ F1)
    else:
        riccati_X_residual_rel = 0.0
        riccati_Y_residual_rel = 0.0
        rho_XY = 0.0
        coupling_margin = float(gamma**2)
        A_K_s = np.zeros((0, 0), dtype=np.float64)
        B_K_s = np.zeros((0, ny), dtype=np.float64)
        C_K_s = np.zeros((nu, 0), dtype=np.float64)

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
        try:
            C_k_new = np.linalg.solve(np.eye(nu) + D_k @ D22, C_k)
            D_k_new = np.linalg.solve(np.eye(nu) + D_k @ D22, D_k)
        except np.linalg.LinAlgError:
            return None
        A_k = A_k - B_k @ D22 @ C_k_new
        B_k = B_k @ (np.eye(ny) - D22 @ D_k_new)
        C_k = C_k_new
        D_k = D_k_new

    if not (np.all(np.isfinite(A_k)) and np.all(np.isfinite(B_k)) and np.all(np.isfinite(C_k)) and np.all(np.isfinite(D_k))):
        return None

    K_cand = StateSpace(A=A_k, B=B_k, C=C_k, D=D_k, dt=None)

    # Verificar estabilidade em malha fechada e Lema Real Limitado exato com P original
    M_cl = np.eye(ny) - D22 @ D_k
    s_mcl = np.linalg.svd(M_cl, compute_uv=False)
    if float(s_mcl[-1]) <= 1e-10 * max(1.0, float(s_mcl[0])):
        return None
    try:
        A_cl, B_cl, C_cl, D_cl = _build_closed_loop_tzw(P, K_cand)
    except ControlLabError:
        return None
    if A_cl.size > 0:
        cl_eigs = np.linalg.eigvals(A_cl)
        if not np.all(np.real(cl_eigs) < -1e-7):
            return None

    brl_ok, min_abs_real, _ = _hamiltonian_brl_check(A_cl, B_cl, C_cl, D_cl, gamma, imag_tol=1e-8)
    if not brl_ok:
        return None

    return {
        "controller": K_cand,
        "riccati_X_residual_rel": riccati_X_residual_rel,
        "riccati_Y_residual_rel": riccati_Y_residual_rel,
        "rho_XY": rho_XY,
        "coupling_margin": coupling_margin,
        "hamiltonian_min_abs_real": min_abs_real,
    }


def _try_solve_hinf_gamma(P: dict[str, Any], gamma: float) -> StateSpace | None:
    """Wrapper compatível que retorna apenas StateSpace K(s) ou None para um dado gamma."""
    res = _try_solve_hinf_gamma_detailed(P, gamma)
    return res["controller"] if res is not None else None


def _eval_closed_loop_tzw_norm(P: dict[str, Any], K: StateSpace, omega: np.ndarray) -> float:
    """Avalia ||T_zw(jw)||_inf na grade omega."""
    A_cl, B_cl, C_cl, D_cl = _build_closed_loop_tzw(P, K)
    n_cl = A_cl.shape[0]
    if n_cl == 0:
        return float(np.linalg.svd(D_cl, compute_uv=False)[0]) if D_cl.size > 0 else 0.0
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
    """Síntese H-infinito de sensibilidade mista (S/KS/T) via bisseção em gamma, 2-Riccati DGKF e prova Hamiltoniana BRL."""
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

        # Validar estabilidade assintótica dos pesos (subclasse regular contínua DGKF)
        for w_name, W_ss in (("w_s", W_S), ("w_u", W_U), ("w_t", W_T)):
            if W_ss.n_states > 0:
                w_poles = np.linalg.eigvals(W_ss.A)
                if not np.all(np.real(w_poles) < -1e-12):
                    raise ValidationError(
                        message=f"Peso {w_name} deve ser assintoticamente estável (Hurwitz) na subclasse regular DGKF.",
                        parameters={"weight": w_name, "max_real_pole": float(np.max(np.real(w_poles)))},
                        next_step=f"Desloque polos em jw/RHP de {w_name} para o semiplano esquerdo aberto.",
                    )

        P = _build_mixed_sensitivity_generalized_plant(G_ss, W_S, W_U, W_T)

        # Verificar regularidade DGKF: D12 posto completo por coluna e D21 posto completo por linha
        s12_check = np.linalg.svd(P["D12"], compute_uv=False)
        if s12_check.size < m or float(s12_check[-1]) <= 1e-12 * max(1.0, float(s12_check[0])):
            raise ValidationError(
                message="Problema H-infinito singular: D12 não possui posto completo por coluna (ex.: W_U estritamente própria com ganho nulo em alta frequência).",
                parameters={"sigma_min_D12": float(s12_check[-1]) if s12_check.size > 0 else 0.0, "n_u": m},
                next_step="Forneça um peso de controle W_U bipróprio com ganho não-nulo em alta frequência.",
            )
        s21_check = np.linalg.svd(P["D21"], compute_uv=False)
        if s21_check.size < p or float(s21_check[-1]) <= 1e-12 * max(1.0, float(s21_check[0])):
            raise ValidationError(
                message="Problema H-infinito singular: D21 não possui posto completo por linha.",
                parameters={"sigma_min_D21": float(s21_check[-1]) if s21_check.size > 0 else 0.0, "n_y": p},
                next_step="Verifique a regularidade da planta generalizada.",
            )

        w_grid, w_warns = resolve_omega_grid(omega, dt=None, n_points=300)
        warnings_out.extend(w_warns)

        # Encontrar limite superior viável gamma_hi por duplicação
        gamma_hi = 1.0
        best_sol: dict[str, Any] | None = None
        for _ in range(30):
            cand = _try_solve_hinf_gamma_detailed(P, gamma_hi)
            if cand is not None:
                best_sol = cand
                break
            gamma_hi *= 2.0

        if best_sol is None:
            raise NumericalInconclusiveError(
                message="Não foi possível encontrar gamma viável para o problema H-infinito (verifique estabilizabilidade/detectabilidade e pesos).",
                next_step="Verifique se a planta é estabilizável/detectável e se W_U possui ganho não-nulo em alta frequência.",
            )

        # Bisseção entre gamma_lo e gamma_hi
        gamma_lo = max(1e-3, float(np.linalg.norm(W_S.D, ord=2)) * 0.5)
        if gamma_lo >= gamma_hi:
            gamma_lo = 0.1 * gamma_hi

        # Garantir que gamma_lo é inviável ou reduzir
        while gamma_lo > 1e-4:
            cand_lo = _try_solve_hinf_gamma_detailed(P, gamma_lo)
            if cand_lo is None:
                break
            gamma_hi = gamma_lo
            best_sol = cand_lo
            gamma_lo *= 0.5

        gamma_achieved = gamma_hi
        for _ in range(40):
            if (gamma_hi - gamma_lo) <= float(gamma_tol) * max(1.0, gamma_hi):
                break
            gamma_mid = 0.5 * (gamma_lo + gamma_hi)
            cand_mid = _try_solve_hinf_gamma_detailed(P, gamma_mid)
            if cand_mid is not None:
                best_sol = cand_mid
                gamma_hi = gamma_mid
                gamma_achieved = gamma_mid
            else:
                gamma_lo = gamma_mid

        assert best_sol is not None
        K_best: StateSpace = best_sol["controller"]
        riccati_X_residual_rel = float(best_sol["riccati_X_residual_rel"])
        riccati_Y_residual_rel = float(best_sol["riccati_Y_residual_rel"])
        rho_XY = float(best_sol["rho_XY"])
        coupling_margin = float(best_sol["coupling_margin"])

        A_cl_tzw, B_cl_tzw, C_cl_tzw, D_cl_tzw = _build_closed_loop_tzw(P, K_best)
        hinf_norm_grid = _eval_closed_loop_tzw_norm(P, K_best, w_grid)

        # Verificação exata em todo w in [0, inf) via Lema Real Limitado Hamiltoniano (Bruinsma-Steinbuch 1990)
        ham_proof = _compute_exact_hinf_norm_hamiltonian(
            A_cl_tzw,
            B_cl_tzw,
            C_cl_tzw,
            D_cl_tzw,
            gamma_upper=float(gamma_achieved),
            tol=1e-6,
            hinf_norm_grid=float(hinf_norm_grid),
        )
        hamiltonian_exact_verified = bool(ham_proof["hamiltonian_exact_verified"])
        hamiltonian_min_abs_real = float(ham_proof["hamiltonian_min_abs_real"])
        hinf_norm_exact = float(ham_proof["hinf_norm_exact"])

        if not hamiltonian_exact_verified or not math.isfinite(hinf_norm_exact):
            raise NumericalInconclusiveError(
                message="Prova Hamiltoniana do Lema Real Limitado falhou na certificação de ||T_zw||_inf < gamma_achieved.",
                parameters={
                    "gamma_achieved": float(gamma_achieved),
                    "hamiltonian_min_abs_real": hamiltonian_min_abs_real,
                    "hinf_norm_grid": float(hinf_norm_grid),
                },
                next_step="Relaxe gamma_tol ou revise o condicionamento dos filtros de ponderação.",
            )

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

        # Verificar estabilidade em malha fechada de (I + G K)^{-1} e da planta generalizada
        GK_ss = _series_ss(G_ss, K_best)
        M_cl = np.eye(p, dtype=np.float64) + GK_ss.D
        C_cl_gk = np.linalg.solve(M_cl, GK_ss.C) if GK_ss.n_states > 0 else np.zeros((p, 0), dtype=np.float64)
        A_cl_gk = GK_ss.A - GK_ss.B @ C_cl_gk if GK_ss.n_states > 0 else np.zeros((0, 0), dtype=np.float64)
        cl_poles = sort_complex_roots(np.linalg.eigvals(A_cl_gk)) if A_cl_gk.size > 0 else np.array([], dtype=np.complex128)
        is_stable_gk = bool(np.all(np.real(cl_poles) < -1e-7)) if cl_poles.size > 0 else True
        tzw_poles = np.linalg.eigvals(A_cl_tzw) if A_cl_tzw.size > 0 else np.array([], dtype=np.complex128)
        is_stable_tzw = bool(np.all(np.real(tzw_poles) < -1e-7)) if tzw_poles.size > 0 else True
        is_stable = bool(is_stable_gk and is_stable_tzw)

        if not is_stable:
            raise NumericalInconclusiveError(
                message="Controlador sintetizado não atingiu estabilidade estrita em malha fechada.",
                next_step="Verifique estabilizabilidade/detectabilidade da planta e pesos.",
            )

        gp_summary = {
            "n_states": int(P["n_states"]),
            "n_w": int(P["n_w"]),
            "n_u": int(P["n_u"]),
            "n_z": int(P["n_z"]),
            "n_y": int(P["n_y"]),
        }

        stable_subclass = "continuous_regular_dgkf_mixed_sensitivity"
        maturity = "stable"

        assumptions = {
            "domain": "continuous",
            "dt": None,
            "n_channels": p,
            "gamma_tol": float(gamma_tol),
            "stable_subclass": stable_subclass,
        }
        diagnostics = {
            "gamma_achieved": float(gamma_achieved),
            "hinf_norm_grid": float(hinf_norm_grid),
            "hinf_norm_exact": hinf_norm_exact,
            "is_stable": is_stable,
            "controller_states": K_best.n_states,
            "generalized_plant_summary": gp_summary,
            "riccati_X_residual_rel": riccati_X_residual_rel,
            "riccati_Y_residual_rel": riccati_Y_residual_rel,
            "rho_XY": rho_XY,
            "coupling_margin": coupling_margin,
            "hamiltonian_exact_verified": hamiltonian_exact_verified,
            "hamiltonian_min_abs_real": hamiltonian_min_abs_real,
            "stable_subclass": stable_subclass,
            "maturity": maturity,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "controller": K_best.to_dict(),
                "generalized_plant_summary": gp_summary,
                "gamma_achieved": float(gamma_achieved),
                "hinf_norm_grid": float(hinf_norm_grid),
                "hinf_norm_exact": hinf_norm_exact,
                "is_stable": is_stable,
                "closed_loop_poles": complex_to_pair(cl_poles),
                "omega": w_grid,
                "sigma_S": sigma_S,
                "sigma_T": sigma_T,
                "inv_ws_bound": inv_ws_bound,
                "inv_wt_bound": inv_wt_bound,
                "riccati_X_residual_rel": riccati_X_residual_rel,
                "riccati_Y_residual_rel": riccati_Y_residual_rel,
                "rho_XY": rho_XY,
                "coupling_margin": coupling_margin,
                "hamiltonian_exact_verified": hamiltonian_exact_verified,
                "hamiltonian_min_abs_real": hamiltonian_min_abs_real,
                "stable_subclass": stable_subclass,
                "maturity": maturity,
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
