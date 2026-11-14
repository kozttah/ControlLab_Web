"""Testes unitários, analíticos, estatísticos, metamórficos e normativos da Frente F4 (Identificação de Sistemas).

Cobertura normativa (CL-DIR-001 Seção 5.2, Seção 10.2, Seção 10.3, Seção 10.4, Seção 13.6, R-06 e Apêndice C):
- T-ID-01: ARX sem ruído (1ª e 2ª ordem) recupera coeficientes plantados dentro do erro de arredondamento;
- T-ID-02: Entrada constante e colunas colineares detectam posto deficiente (`rank_deficient=True`) e emitem
  aviso explícito de Persistência de Excitação insuficiente (`PERSISTENCE_OF_EXCITATION_INSUFFICIENT`);
- T-ID-03: Validação em conjunto holdout sintético separado do conjunto de treino, com distinção explícita
  entre previsão de 1 passo (`one_step_prediction`) e simulação livre (`free_simulation`), FIT% e polos;
- B-ARX-PRBS: Benchmark com definição fechada (ordem na=2, nb=2, nk=1, SNR definido, gerador determinístico,
  n de amostras, divisão treino/validação, covariância assintótica e limiares de erro de parâmetros/polos/FIT);
- Estimação Output-Error (`fit_oe`) sob ruído aditivo de saída não branco para ARX;
- Identificação por subespaços (`fit_subspace`: MOESP e N4SID) com recuperação de polos/resposta em frequência;
- Requisito R-06 (`publish_identified_model`): modelo identificado publicado como `TransferFunction` e `StateSpace`
  consumido diretamente por `frequency.bode` / `frequency.root_locus` (Aba 2) e `statespace.design_lqr` (Aba 3);
- Casos de falha obrigatórios (Seção 10.3): NaN/Inf, desbalanceamento u/y, amostragem irregular, saída constante
  no denominador do FIT%, contaminação de partições treino/validação.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import scipy.signal

from control_lab.core import Dataset, IdentifiedModel, StateSpace, TransferFunction, tensor_to_array
from control_lab.diagnostics import DimensionMismatchError, HypothesisViolatedError, ValidationError
from control_lab.frequency import bode, root_locus
from control_lab.identification import (
    analyze_residuals,
    check_persistence_of_excitation,
    compute_fit_percent,
    compute_information_criteria,
    fit_arx,
    fit_oe,
    fit_subspace,
    generate_prbs,
    predict,
    preprocess_dataset,
    publish_identified_model,
    select_arx_order,
    simulate,
    split_dataset,
    validate_model,
)
from control_lab.statespace import design_lqr


def _simulate_exact_arx(
    a_coeffs: list[float],
    b_coeffs: list[float],
    nk: int,
    u: np.ndarray,
    noise: np.ndarray | None = None,
) -> np.ndarray:
    """Oráculo independente de simulação da equação a diferenças ARX:
    y(k) + a_1 y(k-1) + ... + a_na y(k-na) = b_1 u(k-nk) + ... + b_nb u(k-nk-nb+1) + e(k).
    """
    n = u.shape[0]
    y = np.zeros(n, dtype=np.float64)
    na = len(a_coeffs)
    nb = len(b_coeffs)
    for k in range(n):
        acc = float(noise[k]) if noise is not None else 0.0
        for r in range(1, na + 1):
            if k - r >= 0:
                acc -= a_coeffs[r - 1] * y[k - r]
        for s in range(nb):
            lag = nk + s
            if k - lag >= 0:
                acc += b_coeffs[s] * float(u[k - lag])
        y[k] = acc
    return y


def _pair_to_complex_sorted(pair: dict[str, list[float]]) -> np.ndarray:
    arr = np.asarray(pair["real"], dtype=np.float64) + 1j * np.asarray(pair["imag"], dtype=np.float64)
    if arr.size == 0:
        return arr
    order = np.lexsort((np.imag(arr), np.real(arr)))
    return arr[order]


# ---------------------------------------------------------------------------
# 1. T-ID-01: ARX sem ruído recupera coeficientes plantados
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("a_true", "b_true", "nk"),
    [
        ([-0.8], [0.5], 1),
        ([-1.5, 0.7], [1.0, 0.5], 1),
        ([-0.6, -0.16], [0.4, -0.2, 0.1], 2),
    ],
)
def test_t_id_01_arx_noiseless_exact_recovery(
    a_true: list[float],
    b_true: list[float],
    nk: int,
) -> None:
    """T-ID-01: Sistema ARX de 1ª e 2ª ordem sem ruído recupera coeficientes dentro do erro de arredondamento."""
    n_samples = 300
    dt = 0.05
    t = np.arange(n_samples, dtype=np.float64) * dt
    u = generate_prbs(n_samples, register_length=8, levels=(-1.0, 1.0), seed=42)
    y = _simulate_exact_arx(a_true, b_true, nk, u, noise=None)

    ds = Dataset(t=t, u=u, y=y, dt=dt)
    res = fit_arx(ds, na=len(a_true), nb=len(b_true), nk=nk)

    assert res.status == "success"
    assert res.data is not None
    assert res.assumptions["pe_satisfied"] is True
    assert res.assumptions["full_rank_regressor"] is True
    assert res.diagnostics["rank_deficient"] is False

    a_est = res.data["parameters"]["a"]
    b_est = res.data["parameters"]["b"]
    np.testing.assert_allclose(a_est, a_true, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(b_est, b_true, rtol=1e-12, atol=1e-12)

    # Sem ruído, tanto previsão de 1 passo quanto simulação livre atingem FIT = 100%
    assert math.isclose(float(res.diagnostics["fit_train_one_step"]), 100.0, abs_tol=1e-10)
    assert math.isclose(float(res.diagnostics["fit_train_free_sim"]), 100.0, abs_tol=1e-10)
    assert float(res.diagnostics["rmse_train_one_step"]) < 1e-13
    assert float(res.diagnostics["rmse_train_free_sim"]) < 1e-13

    # Polos estimados coincidem com as raízes analíticas de A(z) = z^na + a_1 z^(na-1) + ... + a_na
    poles_expected = np.roots([1.0] + a_true)
    poles_expected = poles_expected[np.lexsort((np.imag(poles_expected), np.real(poles_expected)))]
    poles_est = _pair_to_complex_sorted(res.data["poles"])
    np.testing.assert_allclose(poles_est, poles_expected, rtol=1e-10, atol=1e-10)


# ---------------------------------------------------------------------------
# 2. T-ID-02: Entrada constante / colinear -> rank_deficient e aviso de PE
# ---------------------------------------------------------------------------
def test_t_id_02_constant_and_collinear_input_insufficient_pe() -> None:
    """T-ID-02: Entrada constante ou colinear gera rank_deficient=True e aviso de PE insuficiente."""
    n_samples = 150
    dt = 0.1
    t = np.arange(n_samples, dtype=np.float64) * dt

    # Caso A: Entrada constante u(k) = 2.0 (sem excitação dinâmica)
    u_const = np.full(n_samples, 2.0, dtype=np.float64)
    y_const = _simulate_exact_arx([-0.7, 0.12], [0.5, 0.2], 1, u_const)
    ds_const = Dataset(t=t, u=u_const, y=y_const, dt=dt)

    pe_res = check_persistence_of_excitation(ds_const, order=4)
    assert pe_res.status == "warning"
    assert pe_res.data is not None
    assert pe_res.data["is_persistently_exciting"] is False
    assert pe_res.data["rank_deficient"] is True
    assert pe_res.diagnostics["rank_dynamic"] == 0
    assert any(w.code == "PERSISTENCE_OF_EXCITATION_INSUFFICIENT" for w in pe_res.warnings)

    arx_const = fit_arx(ds_const, na=2, nb=2, nk=1)
    assert arx_const.status == "warning"
    assert arx_const.assumptions["pe_satisfied"] is False
    assert arx_const.diagnostics["rank_deficient"] is True
    warn_codes = {w.code for w in arx_const.warnings if hasattr(w, "code")}
    assert "PERSISTENCE_OF_EXCITATION_INSUFFICIENT" in warn_codes
    assert "RANK_DEFICIENT_REGRESSION" in warn_codes
    # Quando o regressor é rank-deficient, não deve forjar matriz de covariância falsa
    assert arx_const.data is not None
    assert "covariance" not in arx_const.data

    # Caso B: Sistema MISO 2 entradas com colunas perfeitamente colineares u_2(k) = 3 * u_1(k)
    u1 = generate_prbs(n_samples, register_length=7, seed=11)
    u_collinear = np.column_stack([u1, 3.0 * u1])
    y_miso = _simulate_exact_arx([-0.5], [0.8], 1, u1)
    ds_collinear = Dataset(t=t, u=u_collinear, y=y_miso, dt=dt)

    arx_col = fit_arx(ds_collinear, na=1, nb=[2, 2], nk=[1, 1])
    assert arx_col.status == "warning"
    assert arx_col.diagnostics["rank_deficient"] is True
    assert arx_col.diagnostics["rank"] < arx_col.diagnostics["expected_rank"]
    warn_codes_col = {w.code for w in arx_col.warnings if hasattr(w, "code")}
    assert "RANK_DEFICIENT_REGRESSION" in warn_codes_col or "PERSISTENCE_OF_EXCITATION_INSUFFICIENT" in warn_codes_col

    # Caso C: PRBS com período muito curto (register_length=2 -> período 3) para modelo de ordem elevada
    u_short_prbs = generate_prbs(n_samples, register_length=2, clock_divider=1, seed=3)
    pe_short = check_persistence_of_excitation(u_short_prbs, order=6)
    assert pe_short.status == "warning"
    assert pe_short.data is not None
    assert pe_short.data["rank_deficient"] is True
    assert pe_short.diagnostics["rank_raw"] <= 3


# ---------------------------------------------------------------------------
# 3. T-ID-03 e B-ARX-PRBS: Holdout sintético e benchmark fechado ARX + PRBS
# ---------------------------------------------------------------------------
def test_t_id_03_and_b_arx_prbs_holdout_validation_and_statistical_consistency() -> None:
    """T-ID-03 e B-ARX-PRBS: Benchmark ARX(2,2,1) com PRBS, ruído branco, holdout e tendência estatística."""
    # Parâmetros fechados do benchmark B-ARX-PRBS:
    # A(q^-1) = 1 - 1.5 q^-1 + 0.7 q^-2  (polos complexos conjugados 0.75 ± j 0.3708099, |z| = sqrt(0.7) ≈ 0.83666)
    # B(q^-1) = 1.0 q^-1 + 0.5 q^-2      (nk = 1, nb = 2)
    a_true = [-1.5, 0.7]
    b_true = [1.0, 0.5]
    nk = 1
    dt = 0.1
    n_total = 1000
    t = np.arange(n_total, dtype=np.float64) * dt

    u_prbs = generate_prbs(n_total, register_length=10, levels=(-1.0, 1.0), seed=2026)
    rng = np.random.default_rng(20261113)
    sigma_e = 0.05
    e_noise = rng.normal(0.0, sigma_e, size=n_total)
    y_noisy = _simulate_exact_arx(a_true, b_true, nk, u_prbs, noise=e_noise)

    ds_full = Dataset(t=t, u=u_prbs, y=y_noisy, dt=dt, id="ds-b-arx-prbs")
    ds_train, ds_val = split_dataset(ds_full, train_fraction=0.7)
    assert ds_train.n_samples == 700
    assert ds_val.n_samples == 300

    res = fit_arx(ds_train, val_dataset=ds_val, na=2, nb=2, nk=1, seed=20261113)
    assert res.status == "success"
    assert res.data is not None

    # 1. Recuperação de coeficientes dentro da tolerância estatística esperada para N=700, sigma_e=0.05
    a_est = np.asarray(res.data["parameters"]["a"], dtype=np.float64)
    b_est = np.asarray(res.data["parameters"]["b"], dtype=np.float64)
    np.testing.assert_allclose(a_est, a_true, atol=0.02)
    np.testing.assert_allclose(b_est, b_true, atol=0.02)

    # 2. Covariância estimada é SPD e compatível com o erro quadrático observado (intervalo 3-sigma)
    cov = tensor_to_array(res.data["covariance"], expected_ndim=2)
    assert cov.shape == (4, 4)
    assert np.min(np.linalg.eigvalsh(cov)) > 0.0
    std_theta = np.sqrt(np.diag(cov))
    theta_err = np.abs(np.concatenate([a_est - a_true, b_est - b_true]))
    assert np.all(theta_err <= 3.5 * std_theta)

    # 3. Polos no holdout dentro da tolerância da fixture
    poles_true = np.roots([1.0] + a_true)
    poles_true = poles_true[np.lexsort((np.imag(poles_true), np.real(poles_true)))]
    poles_est = _pair_to_complex_sorted(res.data["poles"])
    np.testing.assert_allclose(poles_est, poles_true, atol=0.015)

    # 4. Separação explícita treino vs holdout e previsão de 1 passo vs simulação livre (T-ID-03)
    val_res = validate_model(res.data["identified_model"], ds_val, train_dataset=ds_train)
    assert val_res.status == "success"
    assert val_res.data is not None

    val_m = val_res.data["validation_metrics"]
    tr_m = val_res.data["train_metrics"]
    assert val_m["partition"] == "validation"
    assert tr_m["partition"] == "train"
    assert val_m["one_step_prediction"]["evaluation_mode"] == "one_step_prediction"
    assert val_m["free_simulation"]["evaluation_mode"] == "free_simulation"

    fit_val_1step = float(val_m["one_step_prediction"]["fit_percent"])
    fit_val_free = float(val_m["free_simulation"]["fit_percent"])
    assert fit_val_1step > 95.0
    assert fit_val_free > 90.0
    # As curvas de 1 passo e simulação livre são distintas na presença de ruído
    yh_1step = tensor_to_array(val_res.data["y_hat_one_step"])
    yh_free = tensor_to_array(val_res.data["y_hat_free_sim"])
    assert not np.allclose(yh_1step, yh_free)

    # 5. Diagnósticos de brancura e independência entrada-resíduo no holdout
    r_diag = val_res.data["residual_diagnostics"]
    assert r_diag["n_effective_samples"] == ds_val.n_samples - 2
    assert r_diag["whiteness_within_99_fraction"] >= 0.85
    assert r_diag["uncorrelated_input_within_99_fraction"] >= 0.85

    # 6. Consistência assintótica: erro de parâmetros e traço da covariância decrescem de N=150 para N=700
    ds_small = Dataset(t=t[:150], u=u_prbs[:150], y=y_noisy[:150], dt=dt)
    res_small = fit_arx(ds_small, na=2, nb=2, nk=1)
    assert res_small.data is not None
    cov_small = tensor_to_array(res_small.data["covariance"], expected_ndim=2)
    assert np.trace(cov) < 0.35 * np.trace(cov_small)


# ---------------------------------------------------------------------------
# 4. Seleção de ordem (AIC / BIC / FPE / Holdout)
# ---------------------------------------------------------------------------
def test_arx_order_selection_bic_and_holdout() -> None:
    """Seleciona a ordem verdadeira (na=2, nb=2, nk=1) via BIC e FIT em holdout."""
    a_true = [-1.4, 0.65]
    b_true = [0.8, 0.4]
    n_samples = 500
    t = np.arange(n_samples, dtype=np.float64) * 0.1
    u = generate_prbs(n_samples, register_length=9, seed=77)
    rng = np.random.default_rng(77)
    y = _simulate_exact_arx(a_true, b_true, 1, u, noise=rng.normal(0.0, 0.02, size=n_samples))
    ds_tr, ds_va = split_dataset(Dataset(t=t, u=u, y=y, dt=0.1), train_fraction=0.7)

    sel_res = select_arx_order(
        ds_tr,
        ds_va,
        na_range=(1, 2, 3),
        nb_range=(1, 2, 3),
        nk_range=(1,),
        criterion="bic",
    )
    assert sel_res.status == "success"
    assert sel_res.data is not None
    assert sel_res.data["best_parameters"]["na"] == 2
    assert sel_res.data["best_parameters"]["nb"] == 2


# ---------------------------------------------------------------------------
# 5. Output-Error (fit_oe) sob ruído aditivo colorido na equação ARX
# ---------------------------------------------------------------------------
def test_fit_oe_recovers_plant_with_output_additive_white_noise() -> None:
    """No modelo Output-Error y(k) = (B(q^-1)/F(q^-1)) u(k-nk) + e(k), fit_oe é não-enviesado enquanto ARX sofre viés."""
    f_true = [-1.5, 0.7]
    b_true = [1.0, 0.5]
    nk = 1
    n_samples = 600
    dt = 0.05
    t = np.arange(n_samples, dtype=np.float64) * dt
    u = generate_prbs(n_samples, register_length=9, seed=99)

    # Saída limpa w(k) = (B/F) u(k), e y(k) = w(k) + e(k) (ruído NÃO passa por 1/F)
    w_clean = _simulate_exact_arx(f_true, b_true, nk, u, noise=None)
    rng = np.random.default_rng(12345)
    y_oe = w_clean + rng.normal(0.0, 0.25, size=n_samples)

    ds_tr, ds_va = split_dataset(Dataset(t=t, u=u, y=y_oe, dt=dt), train_fraction=0.75)

    res_arx = fit_arx(ds_tr, val_dataset=ds_va, na=2, nb=2, nk=1)
    res_oe = fit_oe(ds_tr, val_dataset=ds_va, nb=2, nf=2, nk=1)

    assert res_oe.status == "success"
    assert res_oe.data is not None
    assert res_arx.data is not None

    f_oe = np.asarray(res_oe.data["parameters"]["f"], dtype=np.float64)
    a_arx = np.asarray(res_arx.data["parameters"]["a"], dtype=np.float64)

    # O estimador OE recupera f_true com erro substancialmente menor que o ARX enviesado
    err_oe = float(np.linalg.norm(f_oe - f_true))
    err_arx = float(np.linalg.norm(a_arx - f_true))
    assert err_oe < 0.05
    assert err_oe < 0.25 * err_arx


# ---------------------------------------------------------------------------
# 6. Identificação por Subespaços (fit_subspace: MOESP e N4SID)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["moesp", "n4sid"])
def test_fit_subspace_moesp_and_n4sid_recovers_eigenvalues_and_trajectory(method: str) -> None:
    """Identificação por subespaços recupera os polos do sistema discreto de 2ª ordem e simula com alto FIT%."""
    dt = 0.1
    A_true = np.array([[0.8, -0.5], [0.5, 0.8]], dtype=np.float64)  # polos 0.8 ± j 0.5 (|z| = sqrt(0.89) ≈ 0.9434)
    B_true = np.array([[1.0], [0.2]], dtype=np.float64)
    C_true = np.array([[1.0, 0.5]], dtype=np.float64)
    D_true = np.array([[0.0]], dtype=np.float64)

    n_samples = 400
    t = np.arange(n_samples, dtype=np.float64) * dt
    u = generate_prbs(n_samples, register_length=9, seed=314)
    x = np.zeros(2, dtype=np.float64)
    y = np.zeros((n_samples, 1), dtype=np.float64)
    for k in range(n_samples):
        y[k, 0] = float((C_true @ x)[0] + D_true[0, 0] * u[k])
        x = A_true @ x + B_true[:, 0] * u[k]

    ds_tr, ds_va = split_dataset(Dataset(t=t, u=u, y=y, dt=dt), train_fraction=0.75)

    res_sub = fit_subspace(ds_tr, val_dataset=ds_va, order=2, horizon=8, method=method)
    assert res_sub.status == "success"
    assert res_sub.data is not None
    assert res_sub.data["order"] == 2

    # Verifica valores singulares de Hankel: 2 valores significativos seguidos de queda abrupta (~0 sem ruído)
    hsv = tensor_to_array(res_sub.data["hankel_singular_values"], expected_ndim=1)
    assert hsv[1] > 1e-2 * hsv[0]
    assert hsv[2] < 1e-10 * hsv[0]

    # Polos invariantes por transformação de similaridade
    poles_true = np.linalg.eigvals(A_true)
    poles_true = poles_true[np.lexsort((np.imag(poles_true), np.real(poles_true)))]
    poles_est = _pair_to_complex_sorted(res_sub.data["poles"])
    np.testing.assert_allclose(poles_est, poles_true, atol=1e-9)

    assert float(res_sub.diagnostics["fit_train_free_sim"]) > 99.999
    val_fit = float(res_sub.data["metrics"]["validation"]["free_simulation"]["fit_percent"])
    assert val_fit > 99.999


# ---------------------------------------------------------------------------
# 7. R-06: Interoperabilidade de IdentifiedModel com Abas 2 (SISO) e 3 (LQR)
# ---------------------------------------------------------------------------
def test_r_06_publish_identified_model_to_siso_frequency_and_statespace_lqr() -> None:
    """R-06: Modelo identificado em F4 é publicado e usado diretamente em Bode/RootLocus (F3) e LQR discreto (F2)."""
    a_true = [-1.3, 0.42]  # polos em z = 0.6 e z = 0.7
    b_true = [0.2, 0.1]
    dt = 0.05
    n_samples = 300
    t = np.arange(n_samples, dtype=np.float64) * dt
    u = generate_prbs(n_samples, register_length=8, seed=55)
    y = _simulate_exact_arx(a_true, b_true, 1, u)

    arx_res = fit_arx(Dataset(t=t, u=u, y=y, dt=dt), na=2, nb=2, nk=1)
    assert arx_res.status == "success"
    assert arx_res.data is not None

    pub_res = publish_identified_model(arx_res.data["identified_model"], target_kind="both")
    assert pub_res.status == "success"
    assert pub_res.data is not None

    tf_published = TransferFunction.from_dict(pub_res.data["transfer_function"])
    ss_published = StateSpace.from_dict(pub_res.data["state_space"])
    assert tf_published.dt == dt
    assert ss_published.dt == dt
    assert "published_from_identified_model" in tf_published.provenance
    assert "published_from_identified_model" in ss_published.provenance

    # Aba 2 (F3): Bode e Root Locus SISO consomem diretamente tf_published
    bode_res = bode(tf_published, omega=np.linspace(0.5, 20.0, 30))
    assert bode_res.status == "success"
    rl_res = root_locus(tf_published)
    assert rl_res.status == "success"

    # Aba 3 (F2): design_lqr discreto (DARE) consome diretamente ss_published
    Q = np.eye(ss_published.n_states, dtype=np.float64)
    R = np.eye(ss_published.n_inputs, dtype=np.float64)
    lqr_res = design_lqr(plant=ss_published, Q=Q, R=R, method="dare")
    assert lqr_res.status == "success"
    assert lqr_res.assumptions["closed_loop_stable"] is True


# ---------------------------------------------------------------------------
# 8. Casos de borda, pré-processamento e falhas tipadas (Seção 10.3)
# ---------------------------------------------------------------------------
def test_edge_cases_preprocessing_irregular_sampling_nan_and_constant_output() -> None:
    """Verifica detrend, amostragem irregular, NaN/Inf, desbalanceamento u/y e FIT com denominador nulo."""
    # 1. Pré-processamento com offset DC significativo
    n = 200
    t = np.arange(n, dtype=np.float64) * 0.1
    u_dc = generate_prbs(n, register_length=8, seed=7) + 10.0
    y_dc = _simulate_exact_arx([-0.5], [0.5], 1, u_dc - 10.0) + 25.0
    ds_dc = Dataset(t=t, u=u_dc, y=y_dc, dt=0.1)

    pre_res = preprocess_dataset(ds_dc, detrend_mode="mean", normalize=True)
    assert pre_res.status == "success"
    assert pre_res.data is not None
    ds_clean = Dataset.from_dict(pre_res.data["dataset"])
    assert abs(float(np.mean(ds_clean.u))) < 1e-12
    assert abs(float(np.mean(ds_clean.y))) < 1e-12

    # 2. Amostragem irregular rejeitada por padrão, permitida com allow_irregular_sampling=True e warning
    t_irreg = t.copy()
    t_irreg[50] += 0.02
    ds_irreg = Dataset(t=t_irreg, u=u_dc, y=y_dc, dt=0.1, require_uniform=False)
    res_fail_irreg = fit_arx(ds_irreg, na=1, nb=1, nk=1, allow_irregular_sampling=False)
    assert res_fail_irreg.status == "failure"
    assert res_fail_irreg.error is not None
    assert res_fail_irreg.error.code == "VALIDATION_ERROR"

    res_warn_irreg = fit_arx(ds_irreg, na=1, nb=1, nk=1, allow_irregular_sampling=True)
    assert res_warn_irreg.status == "warning"
    assert any(w.code == "NON_UNIFORM_SAMPLING" for w in res_warn_irreg.warnings)

    # 3. FIT% com saída constante (denominador nulo) não gera NaN/ZeroDivisionError
    y_const = np.ones(50, dtype=np.float64) * 3.0
    y_hat_err = np.ones(50, dtype=np.float64) * 3.1
    fit_info = compute_fit_percent(y_const, y_hat_err)
    assert fit_info["fit_defined"] is False
    assert fit_info["fit_percent"] is None
    assert math.isclose(fit_info["rmse"], 0.1, rel_tol=1e-12)

    # 4. NaN e comprimentos incompatíveis u/y geram ValidationError / DimensionMismatchError
    u_nan = u_dc.copy()
    u_nan[10] = float("nan")
    res_nan = fit_arx(u_nan, y_dc, dt=0.1)
    assert res_nan.status == "failure"
    assert res_nan.error is not None
    assert res_nan.error.code == "VALIDATION_ERROR"

    res_mismatch = fit_arx(u_dc[:100], y_dc[:80], dt=0.1)
    assert res_mismatch.status == "failure"
    assert res_mismatch.error is not None
    assert res_mismatch.error.code == "DIMENSION_MISMATCH"

    # 5. Contaminação de treino e validação (mesmo dataset usado em validate_model)
    arx_ok = fit_arx(ds_clean, na=1, nb=1, nk=1)
    assert arx_ok.data is not None
    with pytest.raises(HypothesisViolatedError):
        validate_model(arx_ok.data["identified_model"], ds_clean, train_dataset=ds_clean, raise_on_error=True)
