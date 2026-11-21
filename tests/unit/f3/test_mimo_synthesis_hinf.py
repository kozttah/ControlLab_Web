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


def test_design_hinf_mixed_sensitivity_siso() -> None:
    # Planta SISO G(s) = 1 / (s + 1)
    plant = TransferFunction(num=[1.0], den=[1.0, 1.0], dt=None)
    w_s = {"dc_gain": 100.0, "wb": 1.0, "m_s": 2.0}
    w_u = {"gain": 0.1}
    w_t = {"wt": 10.0, "m_t": 2.0, "at": 0.01}

    res = design_hinf_mixed_sensitivity(plant, w_s=w_s, w_u=w_u, w_t=w_t, gamma_tol=1e-2)
    assert res.status in ("success", "warning")
    assert res.data is not None

    d = res.data
    assert d["controller"]["kind"] == "StateSpace"
    assert d["is_stable"] is True
    gamma = float(d["gamma_achieved"])
    assert np.isfinite(gamma) and gamma > 0.0
    assert float(d["hinf_norm_grid"]) <= gamma * 1.02

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
    assert res.status in ("success", "warning")
    assert res.data is not None

    d = res.data
    assert d["is_stable"] is True
    gamma = float(d["gamma_achieved"])
    assert np.isfinite(gamma) and gamma > 0.0
    assert float(d["hinf_norm_grid"]) <= gamma * 1.05

    gp = d["generalized_plant_summary"]
    assert gp["n_w"] == 2 and gp["n_u"] == 2 and gp["n_y"] == 2 and gp["n_z"] == 6

    sigma_S = tensor_to_array(d["sigma_S"], expected_ndim=1)
    inv_ws = tensor_to_array(d["inv_ws_bound"], expected_ndim=1)
    assert np.all(sigma_S <= inv_ws * 1.05)

    # Planta discreta deve ser rejeitada honestamente
    plant_d = StateSpace(A=np.array([[0.5]]), B=np.array([[1.0]]), C=np.array([[1.0]]), D=np.array([[0.0]]), dt=0.1)
    with pytest.raises(UnsupportedModelError):
        design_hinf_mixed_sensitivity(plant_d, raise_on_error=True)
