"""Testes unitários, analíticos, metamórficos e normativos da Frente F3 (Frequência SISO e MIMO).

Cobertura obrigatória (CL-DIR-001 Seções 5.3, 5.5, 10.2, 13.5 e Apêndice C):
- T-FREQ-01: TF 1ª ordem G(s) = 1/(s+a) com degrau e Bode analíticos (ganho e fase corretos);
- T-FREQ-02: Sistema G(s) com múltiplas frequências de cruzamento e margens identificadas;
- T-MIMO-01: Matriz G quadrada e inversível 2x2 com RGA somando 1 (linhas/colunas) e S + T = I;
- T-MIMO-02: Sistema G singular em DC (omega=0) retornando rga_status='undefined' com diagnóstico;
- B-MIMO-2x2: Benchmark 2x2 em grade conhecida (valores singulares, RGA, S+T e casos singulares);
- Lugar das raízes com continuidade de ramos (linear_sum_assignment), breakaway, assíntotas e discreto;
- Compensadores Lead, Lag, Lead-Lag, PID (com filtro N próprio e interconnect) e overlays honestos.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import scipy.signal

from control_lab.core import DynamicController, StateSpace, TransferFunction, interconnect, tensor_to_array
from control_lab.diagnostics import DimensionMismatchError, ValidationError
from control_lab.frequency import (
    REQUIREMENT_CLASSIFICATIONS,
    bode,
    classify_requirement_overlays,
    design_lag,
    design_lead,
    design_lead_lag,
    design_pid,
    eval_mimo_response,
    eval_response,
    mimo,
    nyquist_generalized,
    nyquist_siso,
    rga,
    root_locus,
    sensitivity,
    singular_values,
    siso,
    stability_margins,
    step_response_siso,
)


def _pair_to_complex_arr(pair: dict[str, list[float]]) -> np.ndarray:
    r = np.asarray(pair["real"], dtype=np.float64)
    im = np.asarray(pair["imag"], dtype=np.float64)
    return r + 1j * im


# ---------------------------------------------------------------------------
# 1. T-FREQ-01: TF de 1ª ordem G(s) = 1/(s + a) — Bode e degrau analíticos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("a", [1.0, 2.5, 10.0])
def test_t_freq_01_first_order_analytical_bode_and_step(a: float) -> None:
    """T-FREQ-01: G(s) = 1/(s+a) confrontado com solução analítica fechada e scipy.signal."""
    tf = TransferFunction(num=[1.0], den=[1.0, a], dt=None)
    omega = np.array([0.1 * a, 0.5 * a, a, 2.0 * a, 10.0 * a], dtype=np.float64)

    res = bode(tf, omega)
    assert res.status == "success"
    assert res.data is not None

    mag = tensor_to_array(res.data["mag"], expected_ndim=1)
    mag_db = tensor_to_array(res.data["mag_db"], expected_ndim=1)
    phase_deg = tensor_to_array(res.data["phase_deg"], expected_ndim=1)
    phase_rad = tensor_to_array(res.data["phase_rad"], expected_ndim=1)

    # Solução analítica fechada: |G(jw)| = 1 / sqrt(w^2 + a^2), angle = -atan(w/a)
    mag_analytic = 1.0 / np.sqrt(omega**2 + a**2)
    mag_db_analytic = 20.0 * np.log10(mag_analytic)
    phase_rad_analytic = -np.arctan(omega / a)
    phase_deg_analytic = np.degrees(phase_rad_analytic)

    np.testing.assert_allclose(mag, mag_analytic, rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(mag_db, mag_db_analytic, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(phase_rad, phase_rad_analytic, rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(phase_deg, phase_deg_analytic, rtol=1e-12, atol=1e-12)

    # Em w = a (frequência de corte): ganho = 1/(a*sqrt(2)), fase = -45.0 graus exatos
    assert math.isclose(float(phase_deg[2]), -45.0, abs_tol=1e-12)
    assert math.isclose(float(mag[2]), 1.0 / (a * math.sqrt(2.0)), rel_tol=1e-12)
    assert math.isclose(float(res.data["dc_gain"]), 1.0 / a, rel_tol=1e-12)

    # Confronto independente com scipy.signal.bode
    _, mag_scipy, phase_scipy = scipy.signal.bode(([1.0], [1.0, a]), w=omega)
    np.testing.assert_allclose(mag_db, mag_scipy, rtol=1e-11, atol=1e-11)
    np.testing.assert_allclose(phase_deg, phase_scipy, rtol=1e-11, atol=1e-11)

    # Resposta ao degrau unitário analítica: y(t) = (1/a)*(1 - exp(-a*t))
    t_grid = np.linspace(0.0, 8.0 / a, 400, dtype=np.float64)
    step_res = step_response_siso(tf, t_grid)
    assert step_res.status == "success"
    assert step_res.data is not None
    y_num = tensor_to_array(step_res.data["y"], expected_ndim=1)
    y_analytic = (1.0 / a) * (1.0 - np.exp(-a * t_grid))
    np.testing.assert_allclose(y_num, y_analytic, rtol=1e-10, atol=1e-12)
    assert math.isclose(step_res.data["metrics"]["overshoot_percent"], 0.0, abs_tol=1e-9)
    assert math.isclose(step_res.data["metrics"]["steady_state_value"], 1.0 / a, rel_tol=1e-10)


def test_siso_second_order_integrator_rhp_zero_and_pade_delay() -> None:
    """Testa 2ª ordem subamortecida, integrador na origem, zero RHP (fase não mínima) e atraso Padé explícito."""
    # 1. Sistema de 2ª ordem com wn=4, zeta=0.25 -> pico de ressonância w_r = wn*sqrt(1 - 2*zeta^2)
    wn, zeta = 4.0, 0.25
    wr = wn * math.sqrt(1.0 - 2.0 * (zeta**2))
    mr_analytic = 1.0 / (2.0 * zeta * math.sqrt(1.0 - zeta**2))
    tf_2nd = TransferFunction(num=[wn**2], den=[1.0, 2.0 * zeta * wn, wn**2])

    res_2nd = eval_response(tf_2nd, omega=np.array([wr, wn]))
    assert res_2nd.status == "success"
    assert res_2nd.data is not None
    mag_2nd = tensor_to_array(res_2nd.data["mag"], expected_ndim=1)
    ph_2nd = tensor_to_array(res_2nd.data["phase_deg"], expected_ndim=1)
    assert math.isclose(float(mag_2nd[0]), mr_analytic, rel_tol=1e-12)
    assert math.isclose(float(ph_2nd[1]), -90.0, abs_tol=1e-11)

    # 2. Integrador puro com polo simples: G(s) = 1 / (s * (s + 1)) -> fase inicia em -90 deg
    tf_int = TransferFunction(num=[1.0], den=[1.0, 1.0, 0.0])
    res_int = eval_response(tf_int, omega=np.array([1e-3, 1.0, 100.0]))
    assert res_int.data is not None
    ph_int = tensor_to_array(res_int.data["phase_deg"], expected_ndim=1)
    assert math.isclose(float(ph_int[0]), -90.0 - math.degrees(math.atan(1e-3)), abs_tol=1e-9)
    assert math.isclose(float(ph_int[1]), -135.0, abs_tol=1e-9)
    assert res_int.data["dc_gain"] is None

    # 3. Sistema de fase não-mínima (zero no semiplano direito): G(s) = (-s + 1)/(s + 1) (all-pass)
    tf_nmp = TransferFunction(num=[-1.0, 1.0], den=[1.0, 1.0])
    res_nmp = eval_response(tf_nmp, omega=np.logspace(-2, 2, 50))
    assert res_nmp.data is not None
    assert res_nmp.assumptions["is_minimum_phase"] is False
    assert res_nmp.diagnostics["n_rhp_zeros"] == 1
    mag_nmp = tensor_to_array(res_nmp.data["mag"], expected_ndim=1)
    np.testing.assert_allclose(mag_nmp, np.ones_like(mag_nmp), atol=1e-12)

    # 4. Atraso exato vs Padé explícito (use_pade=True emite aviso PADE_APPROXIMATION_APPLIED)
    tf_base = TransferFunction(num=[1.0], den=[1.0, 1.0])
    res_exact_delay = eval_response(tf_base, omega=np.array([0.1, 0.5]), delay=0.2, use_pade=False)
    res_pade_delay = eval_response(tf_base, omega=np.array([0.1, 0.5]), delay=0.2, use_pade=True, pade_order=2)
    assert res_exact_delay.assumptions["delay_representation"] == "exact"
    assert res_pade_delay.assumptions["delay_representation"] == "pade"
    assert any(w.code == "PADE_APPROXIMATION_APPLIED" for w in res_pade_delay.warnings)
    ph_ex = tensor_to_array(res_exact_delay.data["phase_deg"], expected_ndim=1)
    ph_pd = tensor_to_array(res_pade_delay.data["phase_deg"], expected_ndim=1)
    np.testing.assert_allclose(ph_ex, ph_pd, atol=1e-2)

    # 5. Cancelamento quase exato sinalizado com warning
    tf_cancel = TransferFunction(num=[1.0, 2.0000001], den=[1.0, 3.0, 2.0])
    res_cancel = eval_response(tf_cancel)
    assert res_cancel.status == "warning"
    assert any(w.code == "NEAR_POLE_ZERO_CANCELLATION" for w in res_cancel.warnings)


# ---------------------------------------------------------------------------
# 2. T-FREQ-02: Sistema com múltiplas frequências de cruzamento de ganho e fase
# ---------------------------------------------------------------------------
def test_t_freq_02_multiple_crossover_frequencies_and_margins() -> None:
    """T-FREQ-02: Identifica todas as travessias de ganho (0 dB) e de fase (-180° + 360°k)."""
    # Caso A: Múltiplas travessias de ganho (0 dB)
    # G1(s) = 4.5 * (s^2 + 0.1 s + 1) / ((s + 0.2) * (s^2 + 0.05 s + 9))
    # Em w=0.01: |G1| = 2.5 (> 0 dB); em w=1 (notch): |G1| = 0.05 (< 0 dB);
    # em w=3 (ressonância): |G1| = 8.0 (> 0 dB); em w=20: |G1| = 0.2 (< 0 dB) -> 3 travessias exatas!
    num_mult_gc = 4.5 * np.array([1.0, 0.1, 1.0], dtype=np.float64)
    den_mult_gc = np.polymul([1.0, 0.2], [1.0, 0.05, 9.0])
    tf_mult_gc = TransferFunction(num=num_mult_gc, den=den_mult_gc)

    res_gc = stability_margins(tf_mult_gc, n_points=3000, omega_min=1e-2, omega_max=50.0)
    assert res_gc.status == "warning"
    assert res_gc.data is not None
    assert any(w.code == "MULTIPLE_CROSSOVER_FREQUENCIES" for w in res_gc.warnings)
    w_gc_list = res_gc.data["omega_gc_all"]
    assert len(w_gc_list) == 3, f"Esperadas 3 travessias de 0 dB, obtidas {w_gc_list}"

    # Verificação independente: em cada w_gc reportado, |G(j w_gc)| == 1.0 (0 dB)
    for w_gc in w_gc_list:
        val = np.polyval(num_mult_gc, 1j * w_gc) / np.polyval(den_mult_gc, 1j * w_gc)
        assert math.isclose(abs(val), 1.0, abs_tol=1e-7), f"|G(j*{w_gc})| = {abs(val)} != 1"

    # Caso B: Múltiplas travessias de fase (-180 deg) — sistema condicionalmente estável
    # L(s) = 20 * (s + 1)^2 / (s^3 * (0.1 s + 1)^2): fase sai de -270°, sobe acima de -180° e volta a cair abaixo de -180°
    num_cond = 20.0 * np.polymul([1.0, 1.0], [1.0, 1.0])
    den_cond = np.polymul([1.0, 0.0, 0.0, 0.0], np.polymul([0.1, 1.0], [0.1, 1.0]))
    tf_cond = TransferFunction(num=num_cond, den=den_cond)

    res_pc = stability_margins(tf_cond, n_points=3000, omega_min=1e-2, omega_max=100.0)
    assert res_pc.data is not None
    w_pc_list = res_pc.data["omega_pc_all"]
    assert len(w_pc_list) == 2, f"Esperadas 2 travessias de -180 deg, obtidas {w_pc_list}"

    for w_pc in w_pc_list:
        val = np.polyval(num_cond, 1j * w_pc) / np.polyval(den_cond, 1j * w_pc)
        assert abs(val.imag) <= 1e-6 * abs(val.real)
        assert val.real < 0.0


# ---------------------------------------------------------------------------
# 3. Lugar das Raízes (Root Locus): continuidade de ramos, breakaway e discreto
# ---------------------------------------------------------------------------
def test_root_locus_branch_continuity_breakaway_and_discrete() -> None:
    """Verifica continuidade de ramos com linear_sum_assignment, ponto de quebra analítico e círculo unitário."""
    # G(s) = 1 / (s * (s + 2)) -> polos em 0 e -2, breakaway analítico exato em s = -1 para K = 1
    tf = TransferFunction(num=[1.0], den=[1.0, 2.0, 0.0])
    gains = np.linspace(0.0, 5.0, 101, dtype=np.float64)

    rl_res = root_locus(tf, gains=gains)
    assert rl_res.status == "success"
    assert rl_res.data is not None

    # Verifica ponto de quebra analítico s = -1, K = 1
    bps = rl_res.data["breakaway_points"]
    assert len(bps) == 1
    assert math.isclose(bps[0]["s_real"], -1.0, abs_tol=1e-6)
    assert math.isclose(bps[0]["gain_K"], 1.0, abs_tol=1e-6)

    # Verifica assíntotas: centroide = (-2 + 0)/2 = -1.0, ângulos = [90, 270]
    asym = rl_res.data["asymptotes"]
    assert asym is not None
    assert math.isclose(asym["centroid"], -1.0, abs_tol=1e-12)
    assert asym["angles_deg"] == [90.0, 270.0]

    # Verifica continuidade dos ramos após K > 1 (um ramo sobe +j*sqrt(K-1), outro desce -j*sqrt(K-1) sem trocar sinal)
    roots_mat = _pair_to_complex_arr(rl_res.data["roots"]).reshape((gains.size, 2))
    k_gt_1_mask = gains > 1.05
    imag_branch_0 = np.imag(roots_mat[k_gt_1_mask, 0])
    imag_branch_1 = np.imag(roots_mat[k_gt_1_mask, 1])
    assert np.all(imag_branch_0 > 0.0) or np.all(imag_branch_0 < 0.0), "Ramo 0 trocou identidade!"
    assert np.all(imag_branch_1 > 0.0) or np.all(imag_branch_1 < 0.0), "Ramo 1 trocou identidade!"
    assert rl_res.diagnostics["max_step_jump"] < 0.35

    # Caso discreto: verifica fronteira unit_circle e detecção de cruzamento |z| = 1
    tf_d = TransferFunction(num=[1.0], den=[1.0, -0.5], dt=0.1)
    rl_d = root_locus(tf_d, gains=np.linspace(0.0, 2.0, 50))
    assert rl_d.status == "success"
    assert rl_d.data is not None
    assert rl_d.data["stability_boundary"] == "unit_circle"
    assert len(rl_d.data["stability_crossings"]) == 1
    # Para z - 0.5 + K = 0, cruza z = -1 em K = 1.5
    assert math.isclose(rl_d.data["stability_crossings"][0]["gain_K"], 1.5, abs_tol=0.05)


# ---------------------------------------------------------------------------
# 4. Compensadores SISO (Lead, Lag, Lead-Lag, PID) e Overlays de Requisitos
# ---------------------------------------------------------------------------
def test_siso_compensators_and_requirement_overlays_honesty() -> None:
    """Testa projeto de compensadores SISO e classificação honesta de overlays (exact vs heuristic/estimated)."""
    # Planta de 2ª ordem tipo 1: G(s) = 4 / (s * (s + 2)) -> PM inicial ~ 51.8 deg
    tf_plant = TransferFunction(num=[4.0], den=[1.0, 2.0, 0.0])

    # Lead compensator para elevar margem de fase para ~60 deg em w_gc = 4 rad/s
    lead_res = design_lead(tf_plant, target_phase_margin_deg=60.0, target_omega_gc=4.0)
    assert lead_res.status == "success"
    assert lead_res.data is not None
    assert lead_res.data["parameters"]["alpha"] < 1.0
    assert lead_res.data["margins_after"]["critical_phase_margin_deg"] > lead_res.data["margins_before"]["critical_phase_margin_deg"]
    assert lead_res.data["margins_after"]["closed_loop_stable"] is True
    ctrl_lead = DynamicController.from_dict(lead_res.data["controller"])
    assert isinstance(ctrl_lead, DynamicController)

    # Lag compensator
    lag_res = design_lag(tf_plant, target_phase_margin_deg=55.0, dc_gain_boost=4.0)
    assert lag_res.status == "success"
    assert lag_res.data is not None
    assert lag_res.data["parameters"]["beta"] > 1.0
    assert lag_res.data["margins_after"]["closed_loop_stable"] is True

    # Lead-Lag unificado
    ll_res = design_lead_lag(tf_plant, mode="lead_lag", target_phase_margin_deg=55.0, dc_gain_boost=3.0)
    assert ll_res.status == "success"
    assert ll_res.data is not None
    assert ll_res.data["margins_after"]["closed_loop_stable"] is True

    # PID com filtro derivativo N próprio
    pid_res = design_pid(tf_plant, Kp=3.0, Ki=1.0, Kd=0.8, N=25.0)
    assert pid_res.status == "success"
    assert pid_res.data is not None
    assert pid_res.data["structure"] == "PID"
    assert pid_res.data["margins_after"]["closed_loop_stable"] is True
    cl_ss = StateSpace.from_dict(pid_res.data["closed_loop"])
    assert np.max(np.real(cl_ss.poles())) < 0.0

    # Classificação de overlays de requisitos (Seção 5.3 / R-07):
    # Em sistema de 3ª ordem (planta 2ª ordem + controlador 1ª ordem), Mp -> zeta NUNCA pode ser 'exact'
    ov_res = classify_requirement_overlays(
        max_real_part=-0.5,
        min_damping_ratio=0.6,
        max_overshoot_pct=10.0,
        max_settling_time=4.0,
        min_natural_freq=1.5,
        plant=tf_plant,
        controller=ctrl_lead,
    )
    assert ov_res.status == "warning"
    assert ov_res.data is not None
    cls_map = ov_res.diagnostics["classifications"]
    assert set(cls_map.values()).issubset(set(REQUIREMENT_CLASSIFICATIONS))
    assert cls_map["spectral_decay_abscissa"] == "exact"
    assert cls_map["damping_ratio_sector"] == "exact"
    assert cls_map["natural_frequency_radius"] == "exact"
    assert cls_map["overshoot_to_damping_cone"] == "heuristic"
    assert cls_map["settling_time_abscissa_estimate"] == "estimated"
    assert any(w.code == "SECOND_ORDER_DOMINANCE_HEURISTIC" for w in ov_res.warnings)


# ---------------------------------------------------------------------------
# 5. T-MIMO-01: Matriz G 2x2 quadrada e invertível — RGA soma 1 e S + T = I
# ---------------------------------------------------------------------------
def test_t_mimo_01_square_invertible_rga_and_sensitivity_identity() -> None:
    """T-MIMO-01: RGA soma 1 nas linhas e colunas e S(jw) + T(jw) = I com tolerância escalonada."""
    # Planta 2x2 acoplada estável:
    # G(s) = [[ 2/(s+1),   1/(s+2) ],
    #         [ 0.5/(s+3), 3/(s+1) ]]
    # Em s=0 (DC): G(0) = [[2, 0.5], [1/6, 3]], det(G(0)) = 6 - 1/12 = 71/12
    # Lambda_11(0) = (2 * 3) / (71/12) = 72/71, Lambda_12(0) = -(1/12)/(71/12) = -1/71
    num_mimo = [
        [[2.0], [1.0]],
        [[0.5], [3.0]],
    ]
    den_mimo = [
        [[1.0, 1.0], [1.0, 2.0]],
        [[1.0, 3.0], [1.0, 1.0]],
    ]
    tf_mimo = TransferFunction(num=num_mimo, den=den_mimo)

    omega = np.array([0.0, 0.5, 1.0, 5.0, 20.0], dtype=np.float64)
    rga_res = rga(tf_mimo, omega=omega)
    assert rga_res.status == "success"
    assert rga_res.data is not None
    assert rga_res.data["rga_status"] == "defined"
    assert rga_res.diagnostics["n_undefined"] == 0

    # Verifica valor analítico exato em DC (omega=0): [[72/71, -1/71], [-1/71, 72/71]]
    entry_dc = rga_res.data["entries"][0]
    lam_dc = _pair_to_complex_arr(entry_dc["rga_matrix"]).reshape((2, 2))
    expected_dc = np.array([[72.0 / 71.0, -1.0 / 71.0], [-1.0 / 71.0, 72.0 / 71.0]], dtype=np.complex128)
    np.testing.assert_allclose(lam_dc, expected_dc, rtol=1e-12, atol=1e-14)

    # Verifica soma de linhas e colunas igual a 1 em todas as frequências
    for entry in rga_res.data["entries"]:
        assert entry["status"] == "defined"
        row_sums = _pair_to_complex_arr(entry["row_sums"])
        col_sums = _pair_to_complex_arr(entry["col_sums"])
        np.testing.assert_allclose(row_sums, np.ones(2, dtype=np.complex128), atol=1e-12)
        np.testing.assert_allclose(col_sums, np.ones(2, dtype=np.complex128), atol=1e-12)

    # Verifica S(jw) + T(jw) = I e distinção entre sensibilidade de saída (G K) e entrada (K G)
    K_ctrl = StateSpace(
        A=np.diag([-2.0, -4.0]),
        B=np.eye(2),
        C=np.array([[1.5, 0.2], [-0.1, 2.0]]),
        D=np.array([[1.0, 0.1], [0.0, 0.8]]),
    )
    sens_res = sensitivity(tf_mimo, K_ctrl, omega=np.logspace(-2, 2, 40))
    assert sens_res.status in ("success", "warning")
    assert sens_res.data is not None
    assert sens_res.data["identity_verified"] is True
    assert sens_res.diagnostics["max_identity_residual"] <= 1e-13
    assert sens_res.diagnostics["max_input_identity_residual"] <= 1e-13

    # Confirma que S_output = (I + G K)^{-1} e S_input = (I + K G)^{-1} são distintos para G e K não comutativos
    S_out = _pair_to_complex_arr(sens_res.data["S"]).reshape((40, 2, 2))
    S_in = _pair_to_complex_arr(sens_res.data["S_input"]).reshape((40, 2, 2))
    assert not np.allclose(S_out, S_in)


# ---------------------------------------------------------------------------
# 6. T-MIMO-02: Sistema G singular em DC (omega=0) e planta não quadrada
# ---------------------------------------------------------------------------
def test_t_mimo_02_dc_singularity_and_non_square_rga() -> None:
    """T-MIMO-02: RGA retorna 'undefined' com diagnóstico quando G é singular em DC ou não quadrada."""
    # G(s) com diferenciador / zero de transmissão em s=0:
    # G(s) = [[ s/(s+1),   0       ],
    #         [ 1/(s+2),   2/(s+1) ]]
    # Em s=0 (DC): primeira linha é [0, 0] -> G(0) é singular (posto 1 < 2).
    # Para w > 0: G(jw) é invertível e diagonal inferior triangular -> Lambda(jw) = I_2.
    tf_dc_singular = TransferFunction(
        num=[[[1.0, 0.0], [0.0]], [[1.0], [2.0]]],
        den=[[[1.0, 1.0], [1.0]], [[1.0, 2.0], [1.0, 1.0]]],
    )

    # 1. Avaliação apenas em DC (omega=0) -> status='inconclusive', rga_status='undefined'
    res_dc_only = rga(tf_dc_singular, omega=np.array([0.0]))
    assert res_dc_only.status == "inconclusive"
    assert res_dc_only.data is not None
    assert res_dc_only.data["rga_status"] == "undefined"
    assert res_dc_only.diagnostics["rga_status"] == "undefined"
    assert res_dc_only.data["undefined_frequencies"] == [0.0]
    assert res_dc_only.data["entries"][0]["status"] == "undefined"
    assert res_dc_only.data["entries"][0]["rga_matrix"] is None
    assert any(w.code == "RGA_UNDEFINED_AT_SINGULAR_FREQUENCIES" for w in res_dc_only.warnings)

    # 2. Avaliação em grade mista [0.0, 1.0, 10.0] -> 'undefined' em 0.0 e 'defined' em 1.0 e 10.0
    res_mixed = rga(tf_dc_singular, omega=np.array([0.0, 1.0, 10.0]))
    assert res_mixed.status == "warning"
    assert res_mixed.data is not None
    assert res_mixed.data["rga_status"] == "partially_defined"
    assert res_mixed.data["entries"][0]["status"] == "undefined"
    assert res_mixed.data["entries"][1]["status"] == "defined"
    assert res_mixed.data["entries"][2]["status"] == "defined"

    # 3. Planta não quadrada (2x3) -> erro tipado DIMENSION_MISMATCH com rga_status='undefined'
    ss_rect = StateSpace(
        A=np.diag([-1.0, -2.0]),
        B=np.ones((2, 3)),
        C=np.eye(2),
        D=np.zeros((2, 3)),
    )
    res_rect = rga(ss_rect)
    assert res_rect.status == "failure"
    assert res_rect.error is not None
    assert res_rect.error.code == "DIMENSION_MISMATCH"
    assert res_rect.diagnostics["rga_status"] == "undefined"

    with pytest.raises(DimensionMismatchError):
        rga(ss_rect, raise_on_error=True)


# ---------------------------------------------------------------------------
# 7. Benchmark B-MIMO-2x2 e propriedades metamórficas SVD / Nyquist Generalizado
# ---------------------------------------------------------------------------
def test_benchmark_b_mimo_2x2_and_unitary_invariance() -> None:
    """B-MIMO-2x2: Valores singulares, invariância por transformações unitárias, RGA, S+T e Nyquist."""
    # Planta 2x2 de benchmark (coluna de destilação Wood-Berry simplificada racional)
    tf_bench = TransferFunction(
        num=[[[12.8], [-18.9]], [[6.6], [-19.4]]],
        den=[[[16.7, 1.0], [21.0, 1.0]], [[10.9, 1.0], [14.4, 1.0]]],
    )
    omega_grid = np.array([0.0, 0.05, 0.1, 0.5, 1.0, 5.0], dtype=np.float64)

    # 1. Valores singulares e confronto direto com np.linalg.svd em cada ponto
    sv_res = singular_values(tf_bench, omega=omega_grid)
    assert sv_res.status == "success"
    assert sv_res.data is not None
    sv_mat = tensor_to_array(sv_res.data["singular_values"], expected_ndim=2)
    sigma_max = tensor_to_array(sv_res.data["sigma_max"], expected_ndim=1)
    sigma_min = tensor_to_array(sv_res.data["sigma_min"], expected_ndim=1)
    cond_num = tensor_to_array(sv_res.data["condition_number"], expected_ndim=1)

    # Em w=0 (DC): G(0) = [[12.8, -18.9], [6.6, -19.4]]
    G0 = np.array([[12.8, -18.9], [6.6, -19.4]], dtype=np.float64)
    sv0_ref = np.linalg.svd(G0, compute_uv=False)
    np.testing.assert_allclose(sv_mat[0], sv0_ref, rtol=1e-12)
    assert math.isclose(float(cond_num[0]), float(sv0_ref[0] / sv0_ref[1]), rel_tol=1e-12)
    np.testing.assert_allclose(sigma_max, sv_mat[:, 0], rtol=1e-14)
    np.testing.assert_allclose(sigma_min, sv_mat[:, 1], rtol=1e-14)

    # 2. Propriedade metamórfica (Seção 5.5): invariância de singular values sob multiplicação unitária U * G(jw) * V^H
    theta_u, theta_v = 0.73, -1.15
    U = np.array(
        [[math.cos(theta_u), -math.sin(theta_u)], [math.sin(theta_u), math.cos(theta_u)]],
        dtype=np.float64,
    )
    V = np.array(
        [[math.cos(theta_v), -math.sin(theta_v)], [math.sin(theta_v), math.cos(theta_v)]],
        dtype=np.float64,
    )
    ss_bench = tf_bench.to_state_space()
    ss_rotated = StateSpace(
        A=ss_bench.A,
        B=ss_bench.B @ V.T,
        C=U @ ss_bench.C,
        D=U @ ss_bench.D @ V.T,
    )
    sv_rot = singular_values(ss_rotated, omega=omega_grid)
    assert sv_rot.data is not None
    sv_mat_rot = tensor_to_array(sv_rot.data["singular_values"], expected_ndim=2)
    np.testing.assert_allclose(sv_mat, sv_mat_rot, rtol=1e-11, atol=1e-12)

    # 3. RGA em toda a grade e Nyquist generalizado
    rga_bench = rga(tf_bench, omega=omega_grid)
    assert rga_bench.data is not None
    assert rga_bench.data["rga_status"] == "defined"
    lam0 = _pair_to_complex_arr(rga_bench.data["entries"][0]["rga_matrix"]).reshape((2, 2))
    lam0_ref = G0 * np.linalg.inv(G0).T
    np.testing.assert_allclose(lam0.real, lam0_ref, rtol=1e-12)

    # 4. Nyquist generalizado: caso estável sem polos sobre jw vs caso com polo sobre jw (inconclusive)
    nyq_stable = nyquist_generalized(
        StateSpace(A=np.diag([-1.0, -2.0]), B=np.eye(2), C=np.eye(2), D=np.zeros((2, 2))),
        omega=np.logspace(-3, 3, 400),
    )
    assert nyq_stable.status == "success"
    assert nyq_stable.data is not None
    assert nyq_stable.data["maturity"] == "beta"
    assert nyq_stable.data["stability_verdict"] == "stable_under_nyquist_criterion"
    assert nyq_stable.data["estimated_closed_loop_unstable_poles"] == 0

    # Planta com polo em s=0 sobre o eixo imaginário -> deve sinalizar inconclusive_boundary_poles
    nyq_boundary = nyquist_generalized(
        StateSpace(A=np.diag([0.0, -2.0]), B=np.eye(2), C=np.eye(2), D=np.zeros((2, 2))),
        omega=np.logspace(-2, 2, 200),
    )
    assert nyq_boundary.status == "inconclusive"
    assert nyq_boundary.data is not None
    assert nyq_boundary.data["stability_verdict"] == "inconclusive_boundary_poles"
    assert any(w.code == "NYQUIST_POLES_ON_IMAGINARY_AXIS" for w in nyq_boundary.warnings)


def test_dispatcher_and_validation_error_paths() -> None:
    """Testa despacho unificado frequency.eval_response e caminhos de erro tipado."""
    tf_siso = TransferFunction(num=[1.0], den=[1.0, 1.0])
    tf_mimo = TransferFunction(num=[[[1.0], [0.0]], [[0.0], [1.0]]], den=[[[1.0, 1.0], [1.0]], [[1.0], [1.0, 2.0]]])

    r_siso = eval_response(tf_siso, omega=np.array([1.0, 2.0]))
    r_mimo = eval_response(tf_mimo, omega=np.array([1.0, 2.0]))
    assert r_siso.status == "success" and "mag_db" in r_siso.data
    assert r_mimo.status == "success" and "G" in r_mimo.data

    # Frequência negativa ou não-crescente deve retornar Result(status='failure') com VALIDATION_ERROR
    bad_omega = eval_response(tf_siso, omega=np.array([2.0, 1.0]))
    assert bad_omega.status == "failure"
    assert bad_omega.error is not None
    assert bad_omega.error.code == "VALIDATION_ERROR"

    with pytest.raises(ValidationError):
        eval_response(tf_siso, omega=np.array([-1.0, 1.0]), raise_on_error=True)

    # SISO recebendo MIMO falha com DIMENSION_MISMATCH
    bad_siso = siso.eval_response(tf_mimo)
    assert bad_siso.status == "failure"
    assert bad_siso.error is not None
    assert bad_siso.error.code == "DIMENSION_MISMATCH"

    # Nyquist SISO
    nyq_s = nyquist_siso(tf_siso, omega=np.array([0.0, 1.0, 10.0]))
    assert nyq_s.status == "success"
    assert nyq_s.data is not None
    assert nyq_s.data["min_distance_to_critical"] > 0.5


def test_no_explicit_linalg_inv_in_frequency_package() -> None:
    """Seção 5.1: Proíbe inv explícita no código de produção de control_lab/frequency/."""
    from pathlib import Path

    freq_dir = Path(__file__).resolve().parents[3] / "control_lab" / "frequency"
    for py_file in sorted(freq_dir.rglob("*.py")):
        src = py_file.read_text(encoding="utf-8")
        assert "linalg.inv(" not in src, f"Uso proibido de linalg.inv encontrado em {py_file}"

