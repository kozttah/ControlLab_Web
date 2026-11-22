"""Independent F9 mathematical oracle for H-infinity 2-Riccati DGKF (DEC-OPEN-06 / ADR-012).

Cross-verifies `design_hinf_mixed_sensitivity` using TWO completely independent oracles:
  1. Independent SDP/LMI Bounded Real Lemma (BRL) solved via Clarabel (`backend="clarabel_direct"`)
     on an independently reconstructed closed-loop realization T_zw = F_l(P, K), asserting
     `certificate_status == "validated_dual"` for gamma_check = 1.01 * gamma_achieved AND
     explicitly mapping the SDP certificate P_s back to original unscaled coordinates
     P_orig = L P_s L^T to verify P_orig > 0 and BRL(P_orig) < 0 directly.
  2. Independent Hamiltonian BRL / closed-loop stability / sensitivity identity verification:
     - max(Re(eig(A_cl))) < -1e-6 (strictly Hurwitz)
     - ||S(jw) + T(jw) - I||_2 < 1e-10 across frequency grid
     - Independent frequency-domain reconstruction matches state-space T_zw(jw) to < 1e-9
     - Independent Hamiltonian H(gamma_check) has zero imaginary-axis eigenvalues and
       hinf_norm_exact <= gamma_achieved * (1 + 1e-4)

Zero internal helpers from `control_lab.frequency.mimo.synthesis` are imported or invoked.
"""

from __future__ import annotations

import importlib.util
import math
from typing import Any

import numpy as np
import pytest
import scipy.linalg

from control_lab.core import StateSpace, TransferFunction, tensor_to_array
from control_lab.frequency.mimo import design_hinf_mixed_sensitivity
from control_lab.optimization import bmat, compile as compile_sdp, psd, sdpvar, solve


def _build_weight_ss_independent(spec: dict[str, float], dim: int, kind: str) -> StateSpace:
    """Independently constructs diagonal weighting filters W_S, W_U, W_T from standard formulas."""
    if kind == "ws":
        dc_gain = float(spec["dc_gain"])
        wb = float(spec["wb"])
        m_s = float(spec["m_s"])
        a_s = 1.0 / dc_gain
        # W_S(s) = (s / M_S + w_b) / (s + w_b * A_S)
        tf1 = TransferFunction(num=[1.0 / m_s, wb], den=[1.0, wb * a_s], dt=None).to_state_space()
    elif kind == "wu":
        gain = float(spec["gain"])
        return StateSpace(
            A=np.zeros((0, 0), dtype=np.float64),
            B=np.zeros((0, dim), dtype=np.float64),
            C=np.zeros((dim, 0), dtype=np.float64),
            D=gain * np.eye(dim, dtype=np.float64),
            dt=None,
        )
    elif kind == "wt":
        wt = float(spec["wt"])
        m_t = float(spec["m_t"])
        a_t = float(spec["at"])
        # W_T(s) = (s + w_T / M_T) / (A_T * s + w_T)
        tf1 = TransferFunction(num=[1.0, wt / m_t], den=[a_t, wt], dt=None).to_state_space()
    else:
        raise ValueError(f"Unknown weight kind: {kind}")

    if dim == 1:
        return tf1
    n_s = tf1.n_states
    A_blk = scipy.linalg.block_diag(*([tf1.A] * dim)) if n_s > 0 else np.zeros((0, 0), dtype=np.float64)
    B_blk = scipy.linalg.block_diag(*([tf1.B] * dim)) if n_s > 0 else np.zeros((0, dim), dtype=np.float64)
    C_blk = scipy.linalg.block_diag(*([tf1.C] * dim)) if n_s > 0 else np.zeros((dim, 0), dtype=np.float64)
    D_blk = scipy.linalg.block_diag(*([tf1.D] * dim))
    return StateSpace(A=A_blk, B=B_blk, C=C_blk, D=D_blk, dt=None)


def _reconstruct_closed_loop_tzw_independent(
    plant: StateSpace,
    controller: StateSpace,
    W_S: StateSpace,
    W_U: StateSpace,
    W_T: StateSpace,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Independently constructs T_zw = [W_S S; W_U K S; W_T T] from (G, K, W_S, W_U, W_T).

    Uses direct negative feedback wiring: e = w - y, u = K e, y = G u.
    """
    ng, p, m = plant.n_states, plant.n_outputs, plant.n_inputs
    nk = controller.n_states
    ns, nu_w, nt = W_S.n_states, W_U.n_states, W_T.n_states
    n_tot = ng + nk + ns + nu_w + nt

    # Solve algebraic loop: (I + D_k D_g) u = -D_k C_g x_g + C_k x_k + D_k w
    M_u = np.eye(m, dtype=np.float64) + controller.D @ plant.D
    K_xg = -np.linalg.solve(M_u, controller.D @ plant.C) if ng > 0 else np.zeros((m, 0), dtype=np.float64)
    K_xk = np.linalg.solve(M_u, controller.C) if nk > 0 else np.zeros((m, 0), dtype=np.float64)
    K_w = np.linalg.solve(M_u, controller.D)

    # Full-state maps: u = U_x x + U_w w, y = Y_x x + Y_w w, e = E_x x + E_w w
    i_g = (0, ng)
    i_k = (ng, ng + nk)
    i_s = (ng + nk, ng + nk + ns)
    i_u = (ng + nk + ns, ng + nk + ns + nu_w)
    i_t = (ng + nk + ns + nu_w, n_tot)

    U_x = np.zeros((m, n_tot), dtype=np.float64)
    U_x[:, i_g[0]:i_g[1]] = K_xg
    U_x[:, i_k[0]:i_k[1]] = K_xk
    U_w = K_w

    Y_x = np.zeros((p, n_tot), dtype=np.float64)
    if ng > 0:
        Y_x[:, i_g[0]:i_g[1]] = plant.C + plant.D @ K_xg
    if nk > 0:
        Y_x[:, i_k[0]:i_k[1]] = plant.D @ K_xk
    Y_w = plant.D @ K_w

    E_x = -Y_x
    E_w = np.eye(p, dtype=np.float64) - Y_w

    A_cl = np.zeros((n_tot, n_tot), dtype=np.float64)
    B_cl = np.zeros((n_tot, p), dtype=np.float64)

    if ng > 0:
        A_cl[i_g[0]:i_g[1], i_g[0]:i_g[1]] = plant.A
        A_cl[i_g[0]:i_g[1], :] += plant.B @ U_x
        B_cl[i_g[0]:i_g[1], :] = plant.B @ U_w
    if nk > 0:
        A_cl[i_k[0]:i_k[1], i_k[0]:i_k[1]] = controller.A
        A_cl[i_k[0]:i_k[1], :] += controller.B @ E_x
        B_cl[i_k[0]:i_k[1], :] = controller.B @ E_w
    if ns > 0:
        A_cl[i_s[0]:i_s[1], i_s[0]:i_s[1]] = W_S.A
        A_cl[i_s[0]:i_s[1], :] += W_S.B @ E_x
        B_cl[i_s[0]:i_s[1], :] = W_S.B @ E_w
    if nu_w > 0:
        A_cl[i_u[0]:i_u[1], i_u[0]:i_u[1]] = W_U.A
        A_cl[i_u[0]:i_u[1], :] += W_U.B @ U_x
        B_cl[i_u[0]:i_u[1], :] = W_U.B @ U_w
    if nt > 0:
        A_cl[i_t[0]:i_t[1], i_t[0]:i_t[1]] = W_T.A
        A_cl[i_t[0]:i_t[1], :] += W_T.B @ Y_x
        B_cl[i_t[0]:i_t[1], :] = W_T.B @ Y_w

    nz = p + m + p
    C_cl = np.zeros((nz, n_tot), dtype=np.float64)
    D_cl = np.zeros((nz, p), dtype=np.float64)

    # z1 = W_S e
    if ns > 0:
        C_cl[:p, i_s[0]:i_s[1]] = W_S.C
    C_cl[:p, :] += W_S.D @ E_x
    D_cl[:p, :] = W_S.D @ E_w

    # z2 = W_U u
    if nu_w > 0:
        C_cl[p:p + m, i_u[0]:i_u[1]] = W_U.C
    C_cl[p:p + m, :] += W_U.D @ U_x
    D_cl[p:p + m, :] = W_U.D @ U_w

    # z3 = W_T y
    if nt > 0:
        C_cl[p + m:, i_t[0]:i_t[1]] = W_T.C
    C_cl[p + m:, :] += W_T.D @ Y_x
    D_cl[p + m:, :] = W_T.D @ Y_w

    return A_cl, B_cl, C_cl, D_cl


def _eval_frf(sys: StateSpace, w: float) -> np.ndarray:
    """Evaluates C (jw I - A)^{-1} B + D directly."""
    if sys.n_states == 0:
        return sys.D.astype(np.complex128)
    M = 1j * float(w) * np.eye(sys.n_states, dtype=np.complex128) - sys.A
    return sys.C @ np.linalg.solve(M, sys.B) + sys.D


def _independent_hamiltonian_min_abs_real(
    A_cl: np.ndarray,
    B_cl: np.ndarray,
    C_cl: np.ndarray,
    D_cl: np.ndarray,
    gamma: float,
) -> float:
    """Independent Hamiltonian matrix H(gamma) eigenvalue check for ||T_zw||_inf < gamma."""
    nw = B_cl.shape[1]
    R = (gamma**2) * np.eye(nw, dtype=np.float64) - D_cl.T @ D_cl
    R = 0.5 * (R + R.T)
    assert float(np.min(np.linalg.eigvalsh(R))) > 0.0
    M_B = np.linalg.solve(R, B_cl.T)
    M_DC = np.linalg.solve(R, D_cl.T @ C_cl)
    A_hat = A_cl + B_cl @ M_DC
    G_blk = 0.5 * (B_cl @ M_B + (B_cl @ M_B).T)
    Q_blk = 0.5 * (C_cl.T @ (C_cl + D_cl @ M_DC) + (C_cl.T @ (C_cl + D_cl @ M_DC)).T)
    H = np.block([[A_hat, G_blk], [-Q_blk, -A_hat.T]])
    eigs = np.linalg.eigvals(H)
    return float(np.min(np.abs(np.real(eigs))))


def _verify_brl_lmi_via_clarabel(
    A_cl: np.ndarray,
    B_cl: np.ndarray,
    C_cl: np.ndarray,
    D_cl: np.ndarray,
    gamma_check: float,
    *,
    eps_p: float = 1e-4,
    eps_brl: float = 1e-6,
) -> tuple[dict[str, Any], np.ndarray]:
    """Independent SDP/LMI Bounded Real Lemma oracle solved via Clarabel direct.

    Uses an exact norm-preserving time scaling (alpha) and Lyapunov-Cholesky similarity
    transform (L) to condition the SDP without altering ||T_zw||_inf:
        A_s = L^T (A_cl / alpha) L^{-T},  B_s = L^T (B_cl / sqrt(alpha)),
        C_s = (C_cl / sqrt(alpha)) L^{-T}, D_s = D_cl.
    Solves for P_s = P_s^T >= eps_p I such that:
        [[ A_s^T P_s + P_s A_s + C_s^T C_s,  P_s B_s + C_s^T D_s ],
         [ B_s^T P_s + D_s^T C_s,            D_s^T D_s - gamma_check^2 I ]] <= -eps_brl I.
    Then maps P_orig = L P_s L^T back to original coordinates where:
        A_cl^T P_orig + P_orig A_cl + C_cl^T C_cl = alpha * L (A_s^T P_s + P_s A_s + C_s^T C_s) L^T.
    """
    n_cl = A_cl.shape[0]
    nw = B_cl.shape[1]

    # Exact norm-preserving time-scaling + Lyapunov-Cholesky similarity transform
    eigs = np.linalg.eigvals(A_cl)
    alpha = float(np.sqrt(np.max(np.abs(eigs)) * np.min(np.abs(np.real(eigs)))))
    A1 = A_cl / alpha
    B1 = B_cl / math.sqrt(alpha)
    C1 = C_cl / math.sqrt(alpha)

    P0 = scipy.linalg.solve_continuous_lyapunov(A1.T, -(C1.T @ C1 + np.eye(n_cl, dtype=np.float64)))
    P0 = 0.5 * (P0 + P0.T)
    L = np.linalg.cholesky(P0)

    A_s = scipy.linalg.solve_triangular(L, (L.T @ A1).T, lower=True).T
    B_s = L.T @ B1
    C_s = scipy.linalg.solve_triangular(L, C1.T, lower=True).T
    D_s = D_cl

    P = sdpvar((n_cl, n_cl), name="P_brl", symmetric=True)
    I_n = np.eye(n_cl, dtype=np.float64)
    I_nw = np.eye(nw, dtype=np.float64)

    top_left = -(A_s.T @ P + P @ A_s) - (C_s.T @ C_s) - eps_brl * I_n
    top_right = -(P @ B_s) - (C_s.T @ D_s)
    bot_left = -(B_s.T @ P) - (D_s.T @ C_s)
    bot_right = (gamma_check**2) * I_nw - (D_s.T @ D_s) - eps_brl * I_nw

    brl_psd = bmat([[top_left, top_right], [bot_left, bot_right]])
    prob = compile_sdp(
        objective=None,
        constraints=[
            psd(P - eps_p * I_n, name="P_pd"),
            psd(1e3 * I_n - P, name="P_ub"),
            psd(brl_psd, name="brl_ineq"),
        ],
        sense="minimize",
        name="independent_hinf_brl_oracle",
    )

    try:
        has_clarabel = importlib.util.find_spec("clarabel") is not None
    except (ValueError, ModuleNotFoundError):
        has_clarabel = False
    backend = "clarabel_direct" if has_clarabel else "native_primal_dual"
    sdp_res = solve(prob, backend=backend, verify_solution=True, raise_on_error=True)
    assert sdp_res.data is not None

    P_s_val = tensor_to_array(sdp_res.data["variables"]["P_brl"], expected_ndim=2)
    P_orig = L @ P_s_val @ L.T
    P_orig = 0.5 * (P_orig + P_orig.T)
    return sdp_res.data, P_orig


@pytest.mark.parametrize(
    "case_id,plant_factory,w_s,w_u,w_t,gamma_tol",
    [
        (
            "siso_stable",
            lambda: TransferFunction(num=[1.0], den=[1.0, 1.0], dt=None).to_state_space(),
            {"dc_gain": 50.0, "wb": 1.0, "m_s": 2.0},
            {"gain": 0.1},
            {"wt": 10.0, "m_t": 2.0, "at": 0.02},
            1e-2,
        ),
        (
            "siso_unstable",
            lambda: TransferFunction(num=[1.0], den=[1.0, -1.0], dt=None).to_state_space(),
            {"dc_gain": 40.0, "wb": 0.5, "m_s": 2.0},
            {"gain": 0.1},
            {"wt": 15.0, "m_t": 2.0, "at": 0.05},
            1e-2,
        ),
        (
            "mimo_2x2_coupled_stable",
            lambda: StateSpace(
                A=np.array([[-1.0, 0.2], [0.1, -2.0]], dtype=np.float64),
                B=np.array([[1.0, 0.4], [0.3, 1.2]], dtype=np.float64),
                C=np.array([[1.0, 0.1], [0.2, 1.0]], dtype=np.float64),
                D=np.zeros((2, 2), dtype=np.float64),
                dt=None,
            ),
            {"dc_gain": 25.0, "wb": 0.5, "m_s": 2.0},
            {"gain": 0.15},
            {"wt": 10.0, "m_t": 2.0, "at": 0.05},
            2e-2,
        ),
        (
            "mimo_2x2_coupled_unstable",
            lambda: StateSpace(
                A=np.array([[0.5, 0.2], [0.1, -1.0]], dtype=np.float64),
                B=np.array([[1.0, 0.3], [0.2, 1.0]], dtype=np.float64),
                C=np.eye(2, dtype=np.float64),
                D=np.zeros((2, 2), dtype=np.float64),
                dt=None,
            ),
            {"dc_gain": 30.0, "wb": 0.5, "m_s": 2.0},
            {"gain": 0.15},
            {"wt": 15.0, "m_t": 2.0, "at": 0.05},
            2e-2,
        ),
    ],
)
def test_hinf_dgkf_independent_clarabel_brl_and_hamiltonian_oracle(
    case_id: str,
    plant_factory: Any,
    w_s: dict[str, float],
    w_u: dict[str, float],
    w_t: dict[str, float],
    gamma_tol: float,
) -> None:
    """Cross-verifies DGKF H-infinity controller against Clarabel BRL SDP & independent Hamiltonian."""
    plant: StateSpace = plant_factory()
    p = plant.n_outputs

    res = design_hinf_mixed_sensitivity(
        plant,
        w_s=w_s,
        w_u=w_u,
        w_t=w_t,
        gamma_tol=gamma_tol,
        raise_on_error=True,
    )
    assert res.status in ("success", "warning"), f"[{case_id}] unexpected status: {res.status}"
    assert res.data is not None
    d = res.data

    assert d["stable_subclass"] == "continuous_regular_dgkf_mixed_sensitivity"
    assert d["maturity"] == "stable"
    assert d["hamiltonian_exact_verified"] is True
    assert float(d["riccati_X_residual_rel"]) < 1e-8
    assert float(d["riccati_Y_residual_rel"]) < 1e-8
    assert float(d["coupling_margin"]) > 0.0

    gamma_achieved = float(d["gamma_achieved"])
    hinf_norm_exact = float(d["hinf_norm_exact"])
    assert math.isfinite(gamma_achieved) and gamma_achieved > 0.0
    assert math.isfinite(hinf_norm_exact) and hinf_norm_exact > 0.0
    assert hinf_norm_exact <= gamma_achieved * (1.0 + 1e-4)

    # Independently reconstruct T_zw = F_l(P, K) from returned StateSpace controller K(s)
    K_ss = StateSpace.from_dict(d["controller"])
    W_S = _build_weight_ss_independent(w_s, p, "ws")
    W_U = _build_weight_ss_independent(w_u, p, "wu")
    W_T = _build_weight_ss_independent(w_t, p, "wt")
    A_cl, B_cl, C_cl, D_cl = _reconstruct_closed_loop_tzw_independent(plant, K_ss, W_S, W_U, W_T)

    # 1. Independent strict Hurwitz stability check
    cl_eigs = np.linalg.eigvals(A_cl)
    max_real_eig = float(np.max(np.real(cl_eigs)))
    assert max_real_eig < -1e-6, f"[{case_id}] closed-loop not strictly Hurwitz: max_real={max_real_eig}"

    # 2. Independent frequency-domain checks: S(jw) + T(jw) = I and T_zw(jw) parity + ||T_zw(jw)||_2 <= gamma
    eye_p = np.eye(p, dtype=np.complex128)
    w_probe = np.concatenate([[0.0], np.geomspace(1e-3, 1e3, 80)])
    max_sv_probe = 0.0
    for w in w_probe:
        G_w = _eval_frf(plant, float(w))
        K_w = _eval_frf(K_ss, float(w))
        WS_w = _eval_frf(W_S, float(w))
        WU_w = _eval_frf(W_U, float(w))
        WT_w = _eval_frf(W_T, float(w))

        S_w = np.linalg.solve(eye_p + G_w @ K_w, eye_p)
        T_w = G_w @ K_w @ S_w
        st_err = float(np.linalg.norm(S_w + T_w - eye_p, ord=2))
        assert st_err < 1e-10, f"[{case_id}] S(jw)+T(jw) != I at w={w}: err={st_err}"

        Tzw_freq = np.vstack([WS_w @ S_w, WU_w @ K_w @ S_w, WT_w @ T_w])
        M_cl = 1j * float(w) * np.eye(A_cl.shape[0], dtype=np.complex128) - A_cl
        Tzw_ss = C_cl @ np.linalg.solve(M_cl, B_cl) + D_cl
        np.testing.assert_allclose(Tzw_ss, Tzw_freq, rtol=1e-9, atol=1e-9)

        sv_w = float(np.linalg.svd(Tzw_ss, compute_uv=False)[0])
        if sv_w > max_sv_probe:
            max_sv_probe = sv_w

    assert max_sv_probe <= hinf_norm_exact * (1.0 + 1e-4)
    assert max_sv_probe <= gamma_achieved * (1.0 + 1e-4)

    # 3. Independent Hamiltonian check at gamma_check = 1.01 * gamma_achieved
    gamma_check = gamma_achieved * 1.01
    ham_margin = _independent_hamiltonian_min_abs_real(A_cl, B_cl, C_cl, D_cl, gamma_check)
    assert ham_margin > 1e-7, f"[{case_id}] Independent Hamiltonian has jw-axis eigenvalue: margin={ham_margin}"

    # 4. Completely independent SDP/LMI Bounded Real Lemma Oracle via Clarabel
    sdp_data, P_orig = _verify_brl_lmi_via_clarabel(A_cl, B_cl, C_cl, D_cl, gamma_check)
    assert sdp_data["certificate_status"] == "validated_dual", (
        f"[{case_id}] Independent Clarabel BRL SDP did not achieve validated_dual: "
        f"status={sdp_data['certificate_status']}, audit={sdp_data.get('audit_feasibility')}"
    )
    assert sdp_data["audit_feasibility"] in ("strictly_feasible", "feasible", "approximately_feasible")

    # 5. Direct unscaled-coordinate certificate check: P_orig > 0 and BRL(P_orig) < 0
    min_eig_P = float(np.min(np.linalg.eigvalsh(P_orig)))
    assert min_eig_P > 0.0, f"[{case_id}] Unscaled P_orig not strictly positive definite: min_eig={min_eig_P}"

    nw = B_cl.shape[1]
    brl_orig = np.block([
        [A_cl.T @ P_orig + P_orig @ A_cl + C_cl.T @ C_cl, P_orig @ B_cl + C_cl.T @ D_cl],
        [B_cl.T @ P_orig + D_cl.T @ C_cl, D_cl.T @ D_cl - (gamma_check**2) * np.eye(nw, dtype=np.float64)],
    ])
    brl_orig = 0.5 * (brl_orig + brl_orig.T)
    max_eig_brl = float(np.max(np.linalg.eigvalsh(brl_orig)))
    assert max_eig_brl < 0.0, f"[{case_id}] Unscaled BRL(P_orig) not strictly negative definite: max_eig={max_eig_brl}"
