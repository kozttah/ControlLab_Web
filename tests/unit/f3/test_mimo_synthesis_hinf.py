"""Testes unitários para síntese MIMO em frequência: Desacoplador SVD/ALIGN, Malha Fechada e H-infinito Misto."""

from __future__ import annotations

import numpy as np
import pytest

from control_lab.core import StateSpace, TransferFunction, tensor_to_array
from control_lab.diagnostics import DimensionMismatchError, NumericalInconclusiveError, UnsupportedModelError, ValidationError
from control_lab.frequency.mimo import (
    design_hinf_mixed_sensitivity,
    design_svd_decoupler,
    simulate_mimo_closed_loop,
)


def _coupled_2x2_tf() -> TransferFunction:
    """Planta 2x2 fortemente acoplada (Wood-Berry / processo térmico clássico)."""
    num = [
        [[2.0], [1.2]],
        [[0.8], [2.5]],
    ]
    den = [
        [[1.0, 1.0], [1.0, 2.0]],
        [[1.0, 1.5], [1.0, 1.0]],
    ]
    return TransferFunction(num=num, den=den, dt=None)


def test_design_svd_decoupler_static_and_first_order() -> None:
    plant = _coupled_2x2_tf()

    res_static = design_svd_decoupler(plant, omega_target=0.5, realization_mode="static")
    assert res_static.status in ("success", "warning")
    assert res_static.data is not None

    d_static = res_static.data
    assert d_static["realization_mode"] == "static"
    assert d_static["decoupler"]["kind"] == "StateSpace"
    assert d_static["decoupled_plant"]["kind"] == "StateSpace"
    assert d_static["kappa_after"] <= d_static["kappa_before"]
    assert d_static["rga_offdiag_norm_after"] < d_static["rga_offdiag_norm_before"]

    rga_after = tensor_to_array(d_static["rga_after"], expected_ndim=2)
    np.testing.assert_allclose(rga_after, np.eye(2), atol=0.15)

    # Modo first_order produz TransferFunction própria realizável
    res_fo = design_svd_decoupler(plant, omega_target=0.5, realization_mode="first_order")
    assert res_fo.status in ("success", "warning")
    assert res_fo.data is not None
    assert res_fo.data["decoupler"]["kind"] == "TransferFunction"
    assert res_fo.data["kappa_after"] <= res_fo.data["kappa_before"]
    assert res_fo.data["rga_offdiag_norm_after"] < res_fo.data["rga_offdiag_norm_before"]


def test_design_svd_decoupler_discrete_and_validation() -> None:
    dt = 0.1
    A = np.array([[0.8, 0.15], [0.1, 0.75]])
    B = np.array([[0.5, 0.3], [0.25, 0.6]])
    C = np.eye(2)
    D = np.zeros((2, 2))
    plant_d = StateSpace(A=A, B=B, C=C, D=D, dt=dt)

    res_d = design_svd_decoupler(plant_d, omega_target=1.0, realization_mode="first_order")
    assert res_d.status in ("success", "warning")
    assert res_d.data is not None
    assert res_d.data["kappa_after"] <= res_d.data["kappa_before"]

    # Erro em planta não quadrada
    non_sq = StateSpace(A=np.array([[-1.0]]), B=np.array([[1.0, 2.0]]), C=np.array([[1.0]]), D=np.zeros((1, 2)))
    with pytest.raises(DimensionMismatchError):
        design_svd_decoupler(non_sq, raise_on_error=True)

    # Erro em realization_mode inválido
    with pytest.raises(ValidationError):
        design_svd_decoupler(_coupled_2x2_tf(), realization_mode="invalid", raise_on_error=True)

    # Erro em omega_targets vazio ou negativo
    with pytest.raises(ValidationError):
        design_svd_decoupler(_coupled_2x2_tf(), omega_targets=[], raise_on_error=True)
    with pytest.raises(ValidationError):
        design_svd_decoupler(_coupled_2x2_tf(), omega_targets=[0.1, -1.0], raise_on_error=True)


def test_design_svd_decoupler_multifreq_static_and_first_order() -> None:
    plant = _coupled_2x2_tf()
    targets = [0.1, 1.0, 10.0]

    res_static = design_svd_decoupler(plant, realization_mode="static", omega_targets=targets)
    assert res_static.status in ("success", "warning")
    assert res_static.data is not None
    d_static = res_static.data
    assert d_static["omega_targets"] == targets
    assert d_static["omega_target"] == 1.0
    assert len(d_static["per_frequency"]) == 3
    assert d_static["rga_offdiag_norm_after"] < d_static["rga_offdiag_norm_before"]

    # Também aceita sequência diretamente em omega_target (com deduplicação e ordenação)
    res_seq = design_svd_decoupler(plant, omega_target=[10.0, 0.1, 1.0, 1.0], realization_mode="first_order")
    assert res_seq.status in ("success", "warning")
    assert res_seq.data is not None
    d_fo = res_seq.data
    assert d_fo["omega_targets"] == targets
    assert d_fo["omega_target"] == 1.0
    assert d_fo["decoupler"]["kind"] == "TransferFunction"
    assert len(d_fo["per_frequency"]) == 3
    assert d_fo["rga_offdiag_norm_after"] < d_fo["rga_offdiag_norm_before"]
    for entry in d_fo["per_frequency"]:
        assert entry["rga_offdiag_norm_after"] < entry["rga_offdiag_norm_before"]

    # Discreto multi-frequência em modo first_order
    dt = 0.05
    plant_d = StateSpace(
        A=np.array([[0.85, 0.12], [0.08, 0.80]]),
        B=np.array([[0.5, 0.3], [0.25, 0.6]]),
        C=np.eye(2),
        D=np.zeros((2, 2)),
        dt=dt,
    )
    res_d_multi = design_svd_decoupler(plant_d, omega_targets=[0.2, 1.0, 5.0], realization_mode="first_order")
    assert res_d_multi.status in ("success", "warning")
    assert res_d_multi.data is not None
    assert res_d_multi.data["order_used"] == 1
    assert res_d_multi.data["order_mode"] == "manual"
    assert len(res_d_multi.data["per_frequency"]) == 3
    assert res_d_multi.data["rga_offdiag_norm_after"] < res_d_multi.data["rga_offdiag_norm_before"]


def test_design_svd_decoupler_rational_order_and_auto() -> None:
    plant = _coupled_2x2_tf()
    targets = [0.1, 1.0, 10.0]

    # Ordem explícita 2 (contínuo)
    res_ord2 = design_svd_decoupler(plant, omega_targets=targets, order=2)
    assert res_ord2.status in ("success", "warning")
    assert res_ord2.data is not None
    d2 = res_ord2.data
    assert d2["order_used"] == 2
    assert d2["order_mode"] == "manual"
    assert d2["decoupler"]["kind"] == "TransferFunction"
    assert np.isfinite(d2["fit_relative_error"])
    assert d2["rga_offdiag_norm_after"] < d2["rga_offdiag_norm_before"]
    for entry in d2["per_frequency"]:
        assert entry["rga_offdiag_norm_after"] < entry["rga_offdiag_norm_before"]
    # Verificar que todos os canais do desacoplador são próprios e estritamente estáveis
    w_tf = TransferFunction.from_dict(d2["decoupler"])
    for i in range(2):
        for j in range(2):
            assert len(w_tf.num[i][j]) <= len(w_tf.den[i][j])
            poles = np.roots(w_tf.den[i][j])
            assert np.all(np.real(poles) < 0.0)

    # Modo automático (order=None, realization_mode="auto") escolhe a menor ordem própria
    res_auto = design_svd_decoupler(plant, omega_targets=targets, realization_mode="auto", order=None)
    assert res_auto.status in ("success", "warning")
    assert res_auto.data is not None
    da = res_auto.data
    assert da["order_mode"] == "auto"
    assert 1 <= da["order_used"] <= 4
    assert np.isfinite(da["fit_relative_error"])
    assert da["rga_offdiag_norm_after"] < da["rga_offdiag_norm_before"]
    for entry in da["per_frequency"]:
        assert entry["rga_offdiag_norm_after"] < entry["rga_offdiag_norm_before"]

    # Para planta estática constante, modo automático deve selecionar ordem 0
    static_plant = StateSpace(
        A=np.zeros((0, 0)),
        B=np.zeros((0, 2)),
        C=np.zeros((2, 0)),
        D=np.array([[2.0, 1.0], [0.5, 3.0]]),
    )
    res_auto_static = design_svd_decoupler(static_plant, omega_targets=targets, realization_mode="auto")
    assert res_auto_static.data is not None
    assert res_auto_static.data["order_used"] == 0
    assert res_auto_static.data["order_mode"] == "auto"
    assert res_auto_static.data["decoupler"]["kind"] == "StateSpace"

    # Compatibilidade order=0 / static
    res_ord0 = design_svd_decoupler(plant, omega_targets=targets, order=0)
    assert res_ord0.data is not None
    assert res_ord0.data["order_used"] == 0
    assert res_ord0.data["order_mode"] == "manual"
    assert res_ord0.data["decoupler"]["kind"] == "StateSpace"

    # Ordem explícita 2 (discreto)
    dt = 0.05
    plant_d = StateSpace(
        A=np.array([[0.85, 0.12], [0.08, 0.80]]),
        B=np.array([[0.5, 0.3], [0.25, 0.6]]),
        C=np.eye(2),
        D=np.zeros((2, 2)),
        dt=dt,
    )
    res_d_ord2 = design_svd_decoupler(plant_d, omega_targets=[0.2, 1.0, 5.0], order=2)
    assert res_d_ord2.status in ("success", "warning")
    assert res_d_ord2.data is not None
    assert res_d_ord2.data["order_used"] == 2
    assert res_d_ord2.data["order_mode"] == "manual"
    w_tf_d = TransferFunction.from_dict(res_d_ord2.data["decoupler"])
    for i in range(2):
        for j in range(2):
            poles_d = np.roots(w_tf_d.den[i][j])
            assert np.all(np.abs(poles_d) < 1.0)

    # Validações de order
    with pytest.raises(ValidationError):
        design_svd_decoupler(plant, order=-1, raise_on_error=True)
    with pytest.raises(ValidationError):
        design_svd_decoupler(plant, order=7, raise_on_error=True)
    with pytest.raises(ValidationError):
        design_svd_decoupler(plant, order=True, raise_on_error=True)
    with pytest.raises(ValidationError):
        design_svd_decoupler(plant, realization_mode="static", order=2, raise_on_error=True)


def test_simulate_mimo_closed_loop_with_and_without_decoupler() -> None:
    plant = _coupled_2x2_tf()
    k_diag = [1.5, 1.5]

    sim_raw = simulate_mimo_closed_loop(
        plant,
        controller=k_diag,
        decoupler=None,
        t_final=12.0,
        n_points=200,
    )
    assert sim_raw.status in ("success", "warning")
    assert sim_raw.data is not None
    assert sim_raw.data["is_stable"] is True

    y_raw = tensor_to_array(sim_raw.data["step_responses"], expected_ndim=3)
    assert y_raw.shape == (2, 200, 2)
    cc_raw = float(sim_raw.data["max_cross_coupling"])
    assert cc_raw > 0.05

    # Com desacoplador SVD em baixa frequência
    dec_res = design_svd_decoupler(plant, omega_target=0.2, realization_mode="static")
    assert dec_res.data is not None
    dec_ss = StateSpace.from_dict(dec_res.data["decoupler"])

    sim_dec = simulate_mimo_closed_loop(
        plant,
        controller=k_diag,
        decoupler=dec_ss,
        t_final=12.0,
        n_points=200,
    )
    assert sim_dec.status in ("success", "warning")
    assert sim_dec.data is not None
    assert sim_dec.data["is_stable"] is True

    cc_dec = float(sim_dec.data["max_cross_coupling"])
    assert cc_dec < cc_raw

    # Malha algebricamente mal posta: G = -I, K = I => det(I + G K) = 0
    bad_plant = StateSpace(A=np.zeros((0, 0)), B=np.zeros((0, 2)), C=np.zeros((2, 0)), D=-np.eye(2))
    with pytest.raises(NumericalInconclusiveError):
        simulate_mimo_closed_loop(bad_plant, controller=np.eye(2), raise_on_error=True)


def _assert_hinf_stable_proof_certificates(res) -> None:
    """Valida todos os certificados matemáticos (Riccati + BRL Hamiltoniano) em data e diagnostics."""
    assert res.status in ("success", "warning")
    assert res.data is not None
    d = res.data
    diag = res.diagnostics

    expected_keys = (
        "controller",
        "generalized_plant_summary",
        "gamma_achieved",
        "hinf_norm_grid",
        "hinf_norm_exact",
        "is_stable",
        "closed_loop_poles",
        "omega",
        "sigma_S",
        "sigma_T",
        "inv_ws_bound",
        "inv_wt_bound",
        "riccati_X_residual_rel",
        "riccati_Y_residual_rel",
        "rho_XY",
        "coupling_margin",
        "hamiltonian_exact_verified",
        "hamiltonian_min_abs_real",
        "stable_subclass",
        "maturity",
    )
    for key in expected_keys:
        assert key in d, f"Chave ausente em data: {key}"

    cert_keys = (
        "riccati_X_residual_rel",
        "riccati_Y_residual_rel",
        "rho_XY",
        "coupling_margin",
        "hamiltonian_exact_verified",
        "hamiltonian_min_abs_real",
        "hinf_norm_exact",
        "stable_subclass",
        "maturity",
    )
    for key in cert_keys:
        assert key in diag, f"Chave ausente em diagnostics: {key}"
        assert d[key] == diag[key]

    assert d["controller"]["kind"] == "StateSpace"
    assert d["is_stable"] is True
    assert d["stable_subclass"] == "continuous_regular_dgkf_mixed_sensitivity"
    assert d["maturity"] == "stable"
    assert d["hamiltonian_exact_verified"] is True
    assert float(d["hamiltonian_min_abs_real"]) > 1e-8
    assert float(d["riccati_X_residual_rel"]) < 1e-8
    assert float(d["riccati_Y_residual_rel"]) < 1e-8
    assert float(d["rho_XY"]) >= 0.0
    assert float(d["coupling_margin"]) > 0.0

    gamma = float(d["gamma_achieved"])
    norm_grid = float(d["hinf_norm_grid"])
    norm_exact = float(d["hinf_norm_exact"])
    assert np.isfinite(gamma) and gamma > 0.0
    assert np.isfinite(norm_exact) and norm_exact > 0.0
    assert norm_grid <= norm_exact * (1.0 + 1e-4) <= gamma * (1.0 + 1e-4)
    np.testing.assert_allclose(float(d["coupling_margin"]), gamma**2 - float(d["rho_XY"]), rtol=1e-12, atol=1e-12)

    cl_poles_pair = d["closed_loop_poles"]
    poles_re = np.asarray(cl_poles_pair["real"], dtype=np.float64)
    assert poles_re.size > 0
    assert np.all(poles_re < -1e-7)


def test_design_hinf_mixed_sensitivity_siso() -> None:
    # Planta SISO G(s) = 1 / (s + 1)
    plant = TransferFunction(num=[1.0], den=[1.0, 1.0], dt=None)
    w_s = {"dc_gain": 100.0, "wb": 1.0, "m_s": 2.0}
    w_u = {"gain": 0.1}
    w_t = {"wt": 10.0, "m_t": 2.0, "at": 0.01}

    res = design_hinf_mixed_sensitivity(plant, w_s=w_s, w_u=w_u, w_t=w_t, gamma_tol=1e-2)
    _assert_hinf_stable_proof_certificates(res)
    assert res.data is not None
    d = res.data

    gp = d["generalized_plant_summary"]
    assert gp["n_w"] == 1 and gp["n_u"] == 1 and gp["n_y"] == 1 and gp["n_z"] == 3
    assert gp["n_states"] >= 3

    sigma_S = tensor_to_array(d["sigma_S"], expected_ndim=1)
    inv_ws = tensor_to_array(d["inv_ws_bound"], expected_ndim=1)
    assert np.all(sigma_S <= inv_ws * 1.02)


def test_design_hinf_mixed_sensitivity_mimo_2x2() -> None:
    plant = _coupled_2x2_tf()
    res = design_hinf_mixed_sensitivity(
        plant,
        w_s={"dc_gain": 50.0, "wb": 0.5, "m_s": 2.0},
        w_u={"gain": 0.1},
        w_t={"wt": 10.0, "m_t": 2.0, "at": 0.05},
        gamma_tol=2e-2,
    )
    _assert_hinf_stable_proof_certificates(res)
    assert res.data is not None
    d = res.data

    gp = d["generalized_plant_summary"]
    assert gp["n_w"] == 2 and gp["n_u"] == 2 and gp["n_y"] == 2 and gp["n_z"] == 6

    sigma_S = tensor_to_array(d["sigma_S"], expected_ndim=1)
    inv_ws = tensor_to_array(d["inv_ws_bound"], expected_ndim=1)
    assert np.all(sigma_S <= inv_ws * 1.05)


def test_design_hinf_mixed_sensitivity_unstable_siso_and_mimo_stabilization() -> None:
    # Planta SISO instável: G(s) = 1 / (s - 1)
    plant_u_siso = TransferFunction(num=[1.0], den=[1.0, -1.0], dt=None)
    res_siso = design_hinf_mixed_sensitivity(
        plant_u_siso,
        w_s={"dc_gain": 50.0, "wb": 0.5, "m_s": 2.0},
        w_u={"gain": 0.1},
        w_t={"wt": 15.0, "m_t": 2.0, "at": 0.05},
        gamma_tol=1e-2,
    )
    _assert_hinf_stable_proof_certificates(res_siso)
    assert res_siso.data is not None
    assert float(res_siso.data["rho_XY"]) > 0.0

    # Planta MIMO 2x2 acoplada com polo instável em malha aberta
    plant_u_mimo = StateSpace(
        A=np.array([[0.5, 0.2], [0.1, -1.0]]),
        B=np.array([[1.0, 0.3], [0.2, 1.0]]),
        C=np.eye(2),
        D=np.zeros((2, 2)),
        dt=None,
    )
    assert np.max(np.real(np.linalg.eigvals(plant_u_mimo.A))) > 0.0

    res_mimo = design_hinf_mixed_sensitivity(
        plant_u_mimo,
        w_s={"dc_gain": 40.0, "wb": 0.5, "m_s": 2.0},
        w_u={"gain": 0.1},
        w_t={"wt": 15.0, "m_t": 2.0, "at": 0.05},
        gamma_tol=2e-2,
    )
    _assert_hinf_stable_proof_certificates(res_mimo)
    assert res_mimo.data is not None
    assert float(res_mimo.data["rho_XY"]) > 0.0

    # Verificar estabilização também via simulação em malha fechada
    k_ss = StateSpace.from_dict(res_mimo.data["controller"])
    sim_res = simulate_mimo_closed_loop(plant_u_mimo, controller=k_ss, t_final=8.0, n_points=100)
    assert sim_res.status in ("success", "warning")
    assert sim_res.data is not None
    assert sim_res.data["is_stable"] is True


def test_design_hinf_mixed_sensitivity_out_of_subclass_rejections() -> None:
    # 1. Planta discreta deve ser rejeitada com UnsupportedModelError
    plant_d = StateSpace(
        A=np.array([[0.5]]),
        B=np.array([[1.0]]),
        C=np.array([[1.0]]),
        D=np.array([[0.0]]),
        dt=0.1,
    )
    with pytest.raises(UnsupportedModelError):
        design_hinf_mixed_sensitivity(plant_d, raise_on_error=True)

    # 2. Planta não quadrada (1x2 e 2x1) deve ser rejeitada com DimensionMismatchError
    plant_1x2 = StateSpace(
        A=np.array([[-1.0]]),
        B=np.array([[1.0, 2.0]]),
        C=np.array([[1.0]]),
        D=np.zeros((1, 2)),
        dt=None,
    )
    with pytest.raises(DimensionMismatchError):
        design_hinf_mixed_sensitivity(plant_1x2, raise_on_error=True)

    plant_2x1 = StateSpace(
        A=np.array([[-1.0]]),
        B=np.array([[1.0]]),
        C=np.array([[1.0], [0.5]]),
        D=np.zeros((2, 1)),
        dt=None,
    )
    with pytest.raises(DimensionMismatchError):
        design_hinf_mixed_sensitivity(plant_2x1, raise_on_error=True)

    # 3. D12 singular: W_U(s) = 1 / (s + 1) estritamente própria com ganho zero em alta frequência
    plant_siso = TransferFunction(num=[1.0], den=[1.0, 1.0], dt=None)
    wu_strictly_proper = TransferFunction(num=[1.0], den=[1.0, 1.0], dt=None)
    with pytest.raises((ValidationError, NumericalInconclusiveError)):
        design_hinf_mixed_sensitivity(plant_siso, w_u=wu_strictly_proper, raise_on_error=True)

    res_err = design_hinf_mixed_sensitivity(plant_siso, w_u=wu_strictly_proper, raise_on_error=False)
    assert res_err.status == "failure"
    assert res_err.error is not None

    # Também em MIMO 2x2 com W_U estritamente própria
    with pytest.raises((ValidationError, NumericalInconclusiveError)):
        design_hinf_mixed_sensitivity(_coupled_2x2_tf(), w_u=wu_strictly_proper, raise_on_error=True)

    # 4. Peso com polo no eixo imaginário (integrador puro) fora da subclasse regular
    ws_integrator = TransferFunction(num=[1.0], den=[1.0, 0.0], dt=None)
    with pytest.raises(ValidationError):
        design_hinf_mixed_sensitivity(plant_siso, w_s=ws_integrator, raise_on_error=True)


def test_hamiltonian_exact_hinf_norm_analytical_oracles() -> None:
    from control_lab.frequency.mimo.synthesis import _compute_exact_hinf_norm_hamiltonian

    # Sistema ressonante de 2a ordem: G(s) = 1 / (s^2 + 2*zeta*s + 1), norma H-inf analítica exata
    zeta = 0.05
    exact_res_norm = 1.0 / (2.0 * zeta * np.sqrt(1.0 - zeta**2))
    ss_res = TransferFunction(num=[1.0], den=[1.0, 2.0 * zeta, 1.0], dt=None).to_state_space()

    cert_ok = _compute_exact_hinf_norm_hamiltonian(
        ss_res.A, ss_res.B, ss_res.C, ss_res.D, gamma_upper=exact_res_norm * 1.25, tol=1e-6
    )
    assert cert_ok["hamiltonian_exact_verified"] is True
    assert cert_ok["hamiltonian_min_abs_real"] > 1e-8
    assert abs(cert_ok["hinf_norm_exact"] - exact_res_norm) / exact_res_norm < 1e-5

    # Para gamma abaixo da norma exata, o BRL Hamiltoniano deve detectar falha
    cert_fail = _compute_exact_hinf_norm_hamiltonian(
        ss_res.A, ss_res.B, ss_res.C, ss_res.D, gamma_upper=exact_res_norm * 0.99, tol=1e-6
    )
    assert cert_fail["hamiltonian_exact_verified"] is False
    assert abs(cert_fail["hinf_norm_exact"] - exact_res_norm) / exact_res_norm < 1e-5

    # Passa-alta G(s) = s / (s + 1): supremo atingido em omega -> infinito (||G||_inf = 1)
    ss_hp = TransferFunction(num=[1.0, 0.0], den=[1.0, 1.0], dt=None).to_state_space()
    cert_hp = _compute_exact_hinf_norm_hamiltonian(
        ss_hp.A, ss_hp.B, ss_hp.C, ss_hp.D, gamma_upper=1.5, tol=1e-6
    )
    assert cert_hp["hamiltonian_exact_verified"] is True
    assert abs(cert_hp["hinf_norm_exact"] - 1.0) < 1e-5

