"""Previsão de 1 passo, simulação livre, FIT%, análise estatística de resíduos e publicação de modelos identificados.

Escopo normativo (CL-DIR-001 Seção 5.2, Seção 10.2, Seção 10.4, Seção 13.6, R-06 e Apêndice C):
- `compute_fit_percent`: FIT(%) = 100 * (1 - ||y - y_hat||_2 / ||y - mean(y)||_2) com proteção de denominador nulo;
- `predict`: Previsão de 1 passo à frente y_hat(k | k-1) ("one_step_prediction");
- `simulate`: Simulação livre y_hat_free(k) usando apenas u e saídas simuladas passadas ("free_simulation");
- `analyze_residuals`: Autocorrelação dos resíduos R_ee(tau) e correlação cruzada entrada-resíduo R_ue(tau)
  com intervalos de confiança de 95% e 99% e tamanho efetivo da amostra N_eff;
- `compute_information_criteria`: Critérios AIC, BIC e FPE de Akaike;
- `validate_model`: Validação completa separando conjunto de treino e holdout/validação (T-ID-03);
- `publish_identified_model`: Promove um IdentifiedModel validado para TransferFunction e StateSpace
  discreto canônicos do `control_lab.core` interoperáveis com as Abas 2 (SISO/MIMO) e 3 (LQR/Estados) (R-06).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

import numpy as np
import scipy.linalg
import scipy.signal
import scipy.stats

from control_lab.core.models import Dataset, IdentifiedModel, StateSpace, TSStateSpace, TransferFunction
from control_lab.core.tensors import array_to_tensor, complex_to_pair, ensure_finite_float64, tensor_to_array
from control_lab.diagnostics import (
    DimensionMismatchError,
    HypothesisViolatedError,
    Provenance,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .preprocessing import handle_id_failure, resolve_dataset_inputs


def compute_fit_percent(
    y_true: Any,
    y_hat: Any,
    *,
    zero_denom_tol: float = 1e-14,
) -> dict[str, Any]:
    """Calcula FIT(%) = 100 * (1 - ||y - y_hat||_2 / ||y - mean(y)||_2) e RMSE por canal e global.

    Quando `||y - mean(y)||_2 <= zero_denom_tol` (saída medida constante), evita divisão por zero,
    sinaliza `fit_defined=False` e reporta RMSE absoluto.
    """
    y_arr = ensure_finite_float64(y_true, name="y_true")
    yh_arr = ensure_finite_float64(y_hat, name="y_hat")
    if y_arr.ndim == 1:
        y_arr = y_arr.reshape(-1, 1)
    if yh_arr.ndim == 1:
        yh_arr = yh_arr.reshape(-1, 1)
    if y_arr.shape != yh_arr.shape:
        raise DimensionMismatchError(
            message=f"Dimensões incompatíveis em compute_fit_percent: y_true={y_arr.shape}, y_hat={yh_arr.shape}.",
            parameters={"y_true_shape": list(y_arr.shape), "y_hat_shape": list(yh_arr.shape)},
        )
    if y_arr.shape[0] < 1:
        raise ValidationError("compute_fit_percent requer ao menos 1 amostra.")

    n_samples, n_outputs = y_arr.shape
    err = y_arr - yh_arr
    rmse_per_channel: list[float] = []
    fit_per_channel: list[float | None] = []
    defined_channels: list[bool] = []

    for ch in range(n_outputs):
        e_ch = err[:, ch]
        y_ch = y_arr[:, ch]
        rmse_ch = float(np.sqrt(np.mean(e_ch**2)))
        rmse_per_channel.append(rmse_ch)

        err_norm = float(np.linalg.norm(e_ch, ord=2))
        denom_norm = float(np.linalg.norm(y_ch - np.mean(y_ch), ord=2))
        scale_ref = max(1.0, float(np.linalg.norm(y_ch, ord=2)))

        if denom_norm <= zero_denom_tol * scale_ref:
            defined_channels.append(False)
            # Se o erro também for identicamente zero na constante, fit=100.0 mas marcado como constante
            if err_norm <= zero_denom_tol * scale_ref:
                fit_per_channel.append(100.0)
            else:
                fit_per_channel.append(None)
        else:
            defined_channels.append(True)
            fit_val = 100.0 * (1.0 - err_norm / denom_norm)
            fit_per_channel.append(float(fit_val))

    rmse_overall = float(np.sqrt(np.mean(err**2)))
    valid_fits = [f for f in fit_per_channel if f is not None]
    fit_overall = float(np.mean(valid_fits)) if valid_fits else None

    return {
        "fit_percent": fit_overall,
        "fit_per_channel": fit_per_channel,
        "fit_defined": all(defined_channels),
        "rmse": rmse_overall,
        "rmse_per_channel": rmse_per_channel,
        "n_samples": int(n_samples),
    }


def compute_information_criteria(
    residuals: Any,
    n_parameters: int,
) -> dict[str, Any]:
    """Calcula critérios de informação de Akaike (AIC), Schwarz/Bayesiano (BIC) e Final Prediction Error (FPE)."""
    res_arr = ensure_finite_float64(residuals, name="residuals")
    if res_arr.ndim == 1:
        res_arr = res_arr.reshape(-1, 1)
    n_eff, p = res_arr.shape
    d = int(n_parameters)
    if n_eff < 1 or d < 0:
        raise ValidationError("n_effective_samples >= 1 e n_parameters >= 0 são obrigatórios.")

    # Covariância empírica dos resíduos Sigma_e = (1/N) * E^T E
    sigma_e = (res_arr.T @ res_arr) / float(n_eff)
    if p == 1:
        det_val = float(max(sigma_e[0, 0], 1e-30))
    else:
        sign, logdet = np.linalg.slogdet(sigma_e + 1e-30 * np.eye(p))
        det_val = float(math.exp(logdet)) if sign > 0 else 1e-30

    log_loss = math.log(max(det_val, 1e-30))
    aic = float(n_eff * log_loss + 2.0 * d)
    bic = float(n_eff * log_loss + d * math.log(max(1, n_eff)))

    if n_eff > d:
        fpe = float(det_val * ((n_eff + d) / (n_eff - d)))
    else:
        fpe = None

    return {
        "aic": aic,
        "bic": bic,
        "fpe": fpe,
        "noise_variance": float(sigma_e[0, 0]) if p == 1 else [float(v) for v in np.diag(sigma_e).tolist()],
        "n_effective_samples": int(n_eff),
        "n_parameters": int(d),
    }


def analyze_residuals(
    residuals: Any,
    u: Any = None,
    *,
    max_lag: int = 20,
    confidence_levels: tuple[float, ...] = (0.95, 0.99),
) -> dict[str, Any]:
    """Calcula autocorrelação dos resíduos R_ee(tau) e correlação cruzada entrada-resíduo R_ue(tau).

    Inclui intervalos de confiança assintóticos gaussianos para ruído branco (`± z_{alpha/2} / sqrt(N_eff)`)
    e fração de lags dentro das bandas (sem declarar "garantia de brancura" por uma única estatística,
    conforme Seção 5.2).
    """
    e_arr = ensure_finite_float64(residuals, name="residuals")
    if e_arr.ndim == 1:
        e_arr = e_arr.reshape(-1, 1)
    n_eff, p = e_arr.shape
    if n_eff < 2:
        raise ValidationError("Análise de resíduos requer pelo menos 2 amostras efetivas.")

    lag_max = min(int(max_lag), n_eff - 1)
    if lag_max < 1:
        lag_max = 1
    lags = list(range(0, lag_max + 1))

    # Bandas de confiança assintóticas 1 / sqrt(N_eff)
    bounds: dict[str, float] = {}
    for lvl in confidence_levels:
        if not (0.5 < float(lvl) < 1.0):
            raise ValidationError(f"Nível de confiança inválido: {lvl!r}")
        z_val = float(scipy.stats.norm.ppf(0.5 + 0.5 * float(lvl)))
        key = f"bound_{int(round(lvl * 100))}"
        bounds[key] = float(z_val / math.sqrt(n_eff))

    b95 = bounds.get("bound_95", 1.959963984540054 / math.sqrt(n_eff))
    b99 = bounds.get("bound_99", 2.5758293035489004 / math.sqrt(n_eff))

    # Autocorrelação normalizada R_ee(tau) por canal de saída (lags 0..lag_max)
    autocorr_per_output: list[list[float]] = []
    max_abs_autocorr_nonzero = 0.0
    within_99_autocorr_counts: list[float] = []

    for i in range(p):
        e_ch = e_arr[:, i] - np.mean(e_arr[:, i])
        denom = float(np.dot(e_ch, e_ch))
        if denom <= 1e-28:
            r_ee = [1.0] + [0.0] * lag_max
        else:
            r_ee = [1.0]
            for tau in range(1, lag_max + 1):
                c_tau = float(np.dot(e_ch[: n_eff - tau], e_ch[tau:]) / denom)
                r_ee.append(c_tau)
                max_abs_autocorr_nonzero = max(max_abs_autocorr_nonzero, abs(c_tau))
        autocorr_per_output.append(r_ee)
        nonzero_lags = r_ee[1:]
        if nonzero_lags:
            frac_99 = sum(1 for v in nonzero_lags if abs(v) <= b99) / float(len(nonzero_lags))
            within_99_autocorr_counts.append(frac_99)

    # Correlação cruzada entrada-resíduo R_ue(tau) para tau em [-lag_max, ..., +lag_max]
    cross_lags = list(range(-lag_max, lag_max + 1))
    crosscorr_matrix: list[list[list[float]]] = []
    max_abs_crosscorr = 0.0
    within_99_crosscorr_counts: list[float] = []

    if u is not None:
        u_arr = ensure_finite_float64(u, name="u")
        if u_arr.ndim == 1:
            u_arr = u_arr.reshape(-1, 1)
        if u_arr.shape[0] >= n_eff:
            u_eff = u_arr[u_arr.shape[0] - n_eff :, :]
        else:
            raise DimensionMismatchError(
                f"Sinal u ({u_arr.shape[0]}) menor que resíduos ({n_eff}) em analyze_residuals."
            )
        m = u_eff.shape[1]
        for i in range(p):
            e_ch = e_arr[:, i] - np.mean(e_arr[:, i])
            norm_e = float(np.linalg.norm(e_ch, ord=2))
            row_i: list[list[float]] = []
            for j in range(m):
                u_ch = u_eff[:, j] - np.mean(u_eff[:, j])
                norm_u = float(np.linalg.norm(u_ch, ord=2))
                denom_ue = norm_e * norm_u
                r_ue: list[float] = []
                for tau in cross_lags:
                    if denom_ue <= 1e-28:
                        r_ue.append(0.0)
                    elif tau >= 0:
                        val = float(np.dot(e_ch[tau:], u_ch[: n_eff - tau]) / denom_ue)
                        r_ue.append(val)
                        max_abs_crosscorr = max(max_abs_crosscorr, abs(val))
                    else:
                        k = -tau
                        val = float(np.dot(e_ch[: n_eff - k], u_ch[k:]) / denom_ue)
                        r_ue.append(val)
                        max_abs_crosscorr = max(max_abs_crosscorr, abs(val))
                row_i.append(r_ue)
                if r_ue:
                    frac_99_ue = sum(1 for v in r_ue if abs(v) <= b99) / float(len(r_ue))
                    within_99_crosscorr_counts.append(frac_99_ue)
            crosscorr_matrix.append(row_i)

    whiteness_99_ratio = float(np.mean(within_99_autocorr_counts)) if within_99_autocorr_counts else 1.0
    independence_99_ratio = float(np.mean(within_99_crosscorr_counts)) if within_99_crosscorr_counts else 1.0

    return {
        "n_effective_samples": int(n_eff),
        "max_lag": int(lag_max),
        "lags": lags,
        "cross_lags": cross_lags,
        "confidence_bounds": {
            "bound_95": float(b95),
            "bound_99": float(b99),
            **bounds,
        },
        "autocorrelation": autocorr_per_output[0] if p == 1 else autocorr_per_output,
        "autocorrelation_per_output": autocorr_per_output,
        "crosscorrelation_u_e": (
            crosscorr_matrix[0][0]
            if (p == 1 and len(crosscorr_matrix) == 1 and len(crosscorr_matrix[0]) == 1)
            else crosscorr_matrix
        ),
        "crosscorrelation_matrix": crosscorr_matrix,
        "max_abs_autocorr_nonzero_lag": float(max_abs_autocorr_nonzero),
        "max_abs_crosscorr": float(max_abs_crosscorr),
        "whiteness_within_99_fraction": whiteness_99_ratio,
        "uncorrelated_input_within_99_fraction": independence_99_ratio,
        "whiteness_consistent_at_99": bool(whiteness_99_ratio >= 0.90),
        "input_uncorrelated_at_99": bool(independence_99_ratio >= 0.90),
    }


def _extract_model_structure(
    model_or_id: IdentifiedModel | StateSpace | TransferFunction | Mapping[str, Any],
) -> dict[str, Any]:
    """Extrai estrutura interna de simulação/predição de IdentifiedModel, TransferFunction ou StateSpace."""
    if isinstance(model_or_id, Mapping):
        kind = model_or_id.get("kind")
        if kind == "IdentifiedModel":
            model_or_id = IdentifiedModel.from_dict(model_or_id)
        elif kind == "TransferFunction":
            model_or_id = TransferFunction.from_dict(model_or_id)
        elif kind == "StateSpace":
            model_or_id = StateSpace.from_dict(model_or_id)
        else:
            raise UnsupportedModelError(f"Modelo dict com kind={kind!r} não suportado em identificação.")

    if isinstance(model_or_id, IdentifiedModel):
        inner = model_or_id.model
        prov = model_or_id.provenance
        alg = model_or_id.algorithm.upper()
        struct = prov.get("model_structure", {})
        if isinstance(struct, Mapping) and struct.get("family") in ("ARX", "OE", "SUBSPACE"):
            return {
                "identified_model": model_or_id,
                "inner_model": inner,
                "family": struct["family"],
                "structure": dict(struct),
                "dt": getattr(inner, "dt", struct.get("dt", 1.0)),
            }
        # Fallback baseado no tipo do modelo interno
        if isinstance(inner, TransferFunction):
            return _tf_to_structure(inner, identified_model=model_or_id, default_family="OE" if "OE" in alg else "ARX")
        if isinstance(inner, StateSpace):
            return _ss_to_structure(inner, identified_model=model_or_id)
        raise UnsupportedModelError(f"Modelo interno de IdentifiedModel não suportado: {type(inner).__name__}.")

    if isinstance(model_or_id, TransferFunction):
        return _tf_to_structure(model_or_id, identified_model=None, default_family="ARX")

    if isinstance(model_or_id, StateSpace):
        return _ss_to_structure(model_or_id, identified_model=None)

    raise UnsupportedModelError(f"Tipo de modelo não suportado: {type(model_or_id).__name__}.")


def _tf_to_structure(
    tf: TransferFunction,
    *,
    identified_model: IdentifiedModel | None,
    default_family: str = "ARX",
) -> dict[str, Any]:
    if tf.dt is None:
        raise UnsupportedModelError("Identificação discreta requer TransferFunction com dt > 0.")
    p, m = tf.n_outputs, tf.n_inputs
    a_polys: list[list[float]] = []
    b_polys: list[list[list[float]]] = []

    for i in range(p):
        # Extrai polinômios em potências crescentes de z^-1 (1 + a1 z^-1 + ...)
        den_0 = tf._den[i][0]
        if tf.variable == "z^-1" and tf.poly_order == "ascending":
            a_asc = den_0.copy()
        elif tf.variable == "z^-1" and tf.poly_order == "descending":
            a_asc = den_0[::-1].copy()
        else:
            num_z, den_z = tf._channel_descending_z_or_s(i, 0)
            a_asc = den_z.copy()
        lead = float(a_asc[0])
        if abs(lead) <= 1e-15:
            raise ValidationError("Coeficiente líder nulo no denominador discreto.")
        a_norm = (a_asc / lead).tolist()
        a_polys.append([float(v) for v in a_norm[1:]])

        row_b: list[list[float]] = []
        for j in range(m):
            num_ij = tf._num[i][j]
            if tf.variable == "z^-1" and tf.poly_order == "ascending":
                b_asc = (num_ij / lead).tolist()
            elif tf.variable == "z^-1" and tf.poly_order == "descending":
                b_asc = (num_ij[::-1] / lead).tolist()
            else:
                num_z, den_z = tf._channel_descending_z_or_s(i, j)
                deg_den = den_z.size - 1
                deg_num = num_z.size - 1
                pad = max(0, deg_den - deg_num)
                b_asc = ([0.0] * pad + (num_z / float(den_z[0])).tolist())
            row_b.append([float(v) for v in b_asc])
        b_polys.append(row_b)

    na = max((len(a) for a in a_polys), default=0)
    nb = max((len(b_polys[i][j]) for i in range(p) for j in range(m)), default=1)
    return {
        "identified_model": identified_model,
        "inner_model": tf,
        "family": default_family,
        "dt": tf.dt,
        "structure": {
            "family": default_family,
            "na": na,
            "nb": nb,
            "nk": 0,
            "n_inputs": m,
            "n_outputs": p,
            "a_coeffs": a_polys,
            "b_full_coeffs": b_polys,
            "f_coeffs": a_polys,
            "dt": tf.dt,
        },
    }


def _ss_to_structure(
    ss: StateSpace,
    *,
    identified_model: IdentifiedModel | None,
) -> dict[str, Any]:
    if ss.dt is None:
        raise UnsupportedModelError("Identificação discreta requer StateSpace com dt > 0.")
    return {
        "identified_model": identified_model,
        "inner_model": ss,
        "family": "SUBSPACE",
        "dt": ss.dt,
        "structure": {
            "family": "SUBSPACE",
            "n_states": ss.n_states,
            "n_inputs": ss.n_inputs,
            "n_outputs": ss.n_outputs,
            "dt": ss.dt,
        },
    }


def _run_arx_or_oe_recurrence(
    struct: Mapping[str, Any],
    u_mat: np.ndarray,
    y_meas: np.ndarray | None,
    *,
    mode: str,
) -> tuple[np.ndarray, int]:
    """Executa recorrência temporal exata para modelos polinomiais ARX e OE.

    - Em `mode="one_step_prediction"`:
      * ARX: $\\hat{y}(k|k-1) = -\\sum_{r=1}^{n_a} a_r y_{\\text{meas}}(k-r) + \\sum_{j=1}^m \\sum_{s=0}^{L_j-1} b_{j,s} u_j(k-s)$
      * OE: $\\hat{y}(k|k-1) = w(k)$ (como $H(q) = 1$ no modelo Output-Error $y(k) = \\frac{B(q^{-1})}{F(q^{-1})}u(k) + e(k)$,
        o preditor ótimo de 1 passo sob ruído aditivo branco coincide com a saída livre de ruído $w(k)$).
    - Em `mode="free_simulation"`:
      * Tanto ARX quanto OE evoluem exclusivamente a partir de $u(k)$ e das saídas simuladas passadas $\\hat{y}_{\\text{free}}(k-r)$:
        $\\hat{y}_{\\text{free}}(k) = -\\sum_{r=1}^{n_a} a_r \\hat{y}_{\\text{free}}(k-r) + \\sum_{j=1}^m \\sum_{s=0}^{L_j-1} b_{j,s} u_j(k-s)$.
    """
    n_samples, m = u_mat.shape
    p = int(struct["n_outputs"])
    if m != int(struct["n_inputs"]):
        raise DimensionMismatchError(
            f"Número de entradas u ({m}) difere do modelo identificado ({struct['n_inputs']})."
        )
    if y_meas is not None and y_meas.shape != (n_samples, p):
        raise DimensionMismatchError(
            f"Saída medida y ({y_meas.shape}) incompatível com ({n_samples}, {p})."
        )

    family = str(struct["family"]).upper()
    a_coeffs: list[list[float]] = (
        struct["f_coeffs"] if family == "OE" and "f_coeffs" in struct else struct["a_coeffs"]
    )
    b_full: list[list[list[float]]] = struct["b_full_coeffs"]

    max_a = max((len(a) for a in a_coeffs), default=0)
    max_b = max((len(b_full[i][j]) - 1 for i in range(p) for j in range(m)), default=0)
    max_lag = max(max_a, max_b)

    y_hat = np.zeros((n_samples, p), dtype=np.float64)
    # Condições iniciais nos primeiros max_lag instantes: se y_meas está disponível,
    # alinha estado inicial para evitar transiente artificial na borda inicial.
    if y_meas is not None and max_lag > 0:
        init_len = min(max_lag, n_samples)
        y_hat[:init_len, :] = y_meas[:init_len, :]

    use_measured_past = (mode == "one_step_prediction") and (family == "ARX")
    if use_measured_past and y_meas is None:
        raise ValidationError(
            "Previsão de 1 passo à frente ('one_step_prediction') para modelo ARX requer a saída medida y."
        )

    start_k = max_lag if (y_meas is not None and max_lag < n_samples) else 0
    for k in range(start_k, n_samples):
        for i in range(p):
            acc = 0.0
            a_i = a_coeffs[i]
            for r_idx, a_r in enumerate(a_i, start=1):
                if k - r_idx >= 0:
                    past_y = y_meas[k - r_idx, i] if use_measured_past else y_hat[k - r_idx, i]
                    acc -= a_r * float(past_y)
            for j in range(m):
                b_ij = b_full[i][j]
                for s_idx, b_s in enumerate(b_ij):
                    if b_s != 0.0 and k - s_idx >= 0:
                        acc += b_s * float(u_mat[k - s_idx, j])
            y_hat[k, i] = acc

    return y_hat, max_lag


def _run_subspace_recurrence(
    ss: StateSpace,
    struct: Mapping[str, Any],
    u_mat: np.ndarray,
    y_meas: np.ndarray | None,
    *,
    mode: str,
    x0: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Executa predição de 1 passo (com ganho de inovação K_kalman ou observador) ou simulação livre em StateSpace."""
    A, B, C, D = ss.A, ss.B, ss.C, ss.D
    n = ss.n_states
    m = ss.n_inputs
    p = ss.n_outputs
    n_samples = u_mat.shape[0]
    if u_mat.shape[1] != m:
        raise DimensionMismatchError(f"Entrada u tem {u_mat.shape[1]} canais, esperado {m}.")
    if y_meas is not None and y_meas.shape != (n_samples, p):
        raise DimensionMismatchError(f"Saída y tem shape {y_meas.shape}, esperado ({n_samples}, {p}).")

    # Estima x0 por mínimos quadrados via QR se não fornecido e y_meas estiver disponível
    if x0 is not None:
        x_curr = ensure_finite_float64(x0, name="x0").reshape(n)
    elif y_meas is not None and n > 0:
        n_obs = min(n_samples, max(n * 3, 10))
        obs_rows: list[np.ndarray] = []
        rhs_rows: list[np.ndarray] = []
        CA_k = C.copy()
        A_pows = [np.eye(n, dtype=np.float64)]
        for _ in range(1, n_obs):
            A_pows.append(A_pows[-1] @ A)
        for k in range(n_obs):
            obs_rows.append(C @ A_pows[k])
            forced = D @ u_mat[k, :]
            for j in range(k):
                forced = forced + (C @ A_pows[k - 1 - j] @ B) @ u_mat[j, :]
            rhs_rows.append(y_meas[k, :] - forced)
        O_mat = np.vstack(obs_rows)
        y_vec = np.concatenate(rhs_rows)
        x_curr, _, _, _ = scipy.linalg.lstsq(O_mat, y_vec, lapack_driver="gelsy")
    else:
        x_curr = np.zeros(n, dtype=np.float64)

    K_innov: np.ndarray | None = None
    if mode == "one_step_prediction" and "kalman_gain" in struct and struct["kalman_gain"] is not None:
        raw_k = struct["kalman_gain"]
        if isinstance(raw_k, Mapping) and "data" in raw_k:
            K_innov = tensor_to_array(raw_k, expected_ndim=2)
        else:
            K_innov = ensure_finite_float64(raw_k, ndim=2, name="kalman_gain")

    x_hist = np.zeros((n_samples, n), dtype=np.float64)
    y_hat = np.zeros((n_samples, p), dtype=np.float64)

    for k in range(n_samples):
        x_hist[k, :] = x_curr
        u_k = u_mat[k, :]
        y_k_hat = C @ x_curr + D @ u_k
        y_hat[k, :] = y_k_hat
        if mode == "one_step_prediction" and y_meas is not None and K_innov is not None:
            innov = y_meas[k, :] - y_k_hat
            x_curr = A @ x_curr + B @ u_k + K_innov @ innov
        else:
            x_curr = A @ x_curr + B @ u_k

    return y_hat, x_hist, 0


def predict(
    model: IdentifiedModel | StateSpace | TransferFunction | Mapping[str, Any],
    dataset_or_u: Any = None,
    y: Any = None,
    t: Any = None,
    *,
    dataset: Dataset | Mapping[str, Any] | None = None,
    u: Any = None,
    dt: float | None = None,
    x0: Any = None,
    allow_irregular_sampling: bool = False,
    raise_on_error: bool = False,
) -> Result:
    """Gera previsão de 1 passo à frente (`evaluation_mode='one_step_prediction'`) $\\hat{y}(k|k-1)$."""
    prov = build_provenance("identification.predict")
    assumptions: dict[str, Any] = {"evaluation_mode": "one_step_prediction", "horizon": 1}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        info = _extract_model_structure(model)
        struct = info["structure"]
        model_dt = info["dt"]

        ds = resolve_dataset_inputs(
            dataset_or_u,
            y,
            t,
            dataset=dataset,
            u=u,
            dt=dt if dt is not None else model_dt,
            require_uniform=not allow_irregular_sampling,
            allow_irregular_sampling=allow_irregular_sampling,
        )
        warnings_out.extend(ds.warnings)

        if info["family"] in ("ARX", "OE"):
            y_hat, max_lag = _run_arx_or_oe_recurrence(
                struct,
                ds.u,
                ds.y,
                mode="one_step_prediction",
            )
            x_hist = None
        else:
            y_hat, x_hist, max_lag = _run_subspace_recurrence(
                info["inner_model"],
                struct,
                ds.u,
                ds.y,
                mode="one_step_prediction",
                x0=x0,
            )

        eval_slice = slice(max_lag, ds.n_samples) if ds.n_samples > max_lag else slice(0, ds.n_samples)
        fit_info = compute_fit_percent(ds.y[eval_slice], y_hat[eval_slice])
        residuals = ds.y[eval_slice] - y_hat[eval_slice]

        if not fit_info["fit_defined"]:
            warnings_out.append(
                WarningItem(
                    code="CONSTANT_OUTPUT_FIT_UNDEFINED",
                    message="Saída medida constante no intervalo avaliado; FIT% indefinido (denominador nulo).",
                    details={"rmse": fit_info["rmse"]},
                )
            )

        diagnostics = {
            "evaluation_mode": "one_step_prediction",
            "max_lag": int(max_lag),
            "n_evaluated_samples": int(fit_info["n_samples"]),
            "fit_percent": fit_info["fit_percent"],
            "fit_per_channel": fit_info["fit_per_channel"],
            "rmse": fit_info["rmse"],
            "rmse_per_channel": fit_info["rmse_per_channel"],
        }
        data: dict[str, Any] = {
            "evaluation_mode": "one_step_prediction",
            "t": array_to_tensor(ds.t, dtype="float64", order="C"),
            "y_true": array_to_tensor(ds.y, dtype="float64", order="C"),
            "y_hat": array_to_tensor(y_hat, dtype="float64", order="C"),
            "residuals": array_to_tensor(residuals, dtype="float64", order="C"),
            "fit_percent": fit_info["fit_percent"],
            "fit_per_channel": fit_info["fit_per_channel"],
            "rmse": fit_info["rmse"],
            "max_lag": int(max_lag),
        }
        if x_hist is not None:
            data["x_hat"] = array_to_tensor(x_hist, dtype="float64", order="C")

        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except Exception as exc:
        return handle_id_failure(
            exc,
            prov=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings=warnings_out,
            raise_on_error=raise_on_error,
        )


def simulate(
    model: IdentifiedModel | StateSpace | TransferFunction | Mapping[str, Any],
    dataset_or_u: Any = None,
    y: Any = None,
    t: Any = None,
    *,
    dataset: Dataset | Mapping[str, Any] | None = None,
    u: Any = None,
    dt: float | None = None,
    x0: Any = None,
    allow_irregular_sampling: bool = False,
    raise_on_error: bool = False,
) -> Result:
    """Executa simulação livre (`evaluation_mode='free_simulation'`) $\\hat{y}_{\\text{free}}(k)$ a partir de $u(k)$."""
    prov = build_provenance("identification.simulate")
    assumptions: dict[str, Any] = {"evaluation_mode": "free_simulation", "uses_measured_past_outputs": False}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        info = _extract_model_structure(model)
        struct = info["structure"]
        model_dt = float(info["dt"] if info["dt"] is not None else (dt if dt is not None else 1.0))

        # Permite simular passando apenas `u` (sem `y` medido) ou um `Dataset(t, u, y)`
        y_meas: np.ndarray | None = None
        if isinstance(dataset_or_u, (Dataset, Mapping)) or dataset is not None or y is not None:
            ds = resolve_dataset_inputs(
                dataset_or_u,
                y,
                t,
                dataset=dataset,
                u=u,
                dt=dt if dt is not None else model_dt,
                require_uniform=not allow_irregular_sampling,
                allow_irregular_sampling=allow_irregular_sampling,
            )
            warnings_out.extend(ds.warnings)
            t_arr = ds.t
            u_mat = ds.u
            y_meas = ds.y
        else:
            u_raw = u if u is not None else dataset_or_u
            if u_raw is None:
                raise ValidationError("simulate requer um Dataset ou sinal de entrada u.")
            if isinstance(u_raw, Mapping) and "data" in u_raw:
                u_raw = tensor_to_array(u_raw)
            u_arr = ensure_finite_float64(u_raw, name="u")
            u_mat = u_arr.reshape(-1, 1) if u_arr.ndim == 1 else u_arr
            if t is None:
                t_arr = np.arange(u_mat.shape[0], dtype=np.float64) * model_dt
            else:
                t_arr = ensure_finite_float64(t, ndim=1, name="t")

        if info["family"] in ("ARX", "OE"):
            y_hat, max_lag = _run_arx_or_oe_recurrence(
                struct,
                u_mat,
                y_meas,
                mode="free_simulation",
            )
            x_hist = None
        else:
            y_hat, x_hist, max_lag = _run_subspace_recurrence(
                info["inner_model"],
                struct,
                u_mat,
                y_meas,
                mode="free_simulation",
                x0=x0,
            )

        data: dict[str, Any] = {
            "evaluation_mode": "free_simulation",
            "t": array_to_tensor(t_arr, dtype="float64", order="C"),
            "u": array_to_tensor(u_mat, dtype="float64", order="C"),
            "y_hat": array_to_tensor(y_hat, dtype="float64", order="C"),
            "max_lag": int(max_lag),
        }
        if x_hist is not None:
            data["x_hat"] = array_to_tensor(x_hist, dtype="float64", order="C")

        diagnostics = {
            "evaluation_mode": "free_simulation",
            "max_lag": int(max_lag),
            "n_samples": int(u_mat.shape[0]),
        }

        if y_meas is not None:
            eval_slice = slice(max_lag, u_mat.shape[0]) if u_mat.shape[0] > max_lag else slice(0, u_mat.shape[0])
            fit_info = compute_fit_percent(y_meas[eval_slice], y_hat[eval_slice])
            residuals = y_meas[eval_slice] - y_hat[eval_slice]
            data["y_true"] = array_to_tensor(y_meas, dtype="float64", order="C")
            data["residuals"] = array_to_tensor(residuals, dtype="float64", order="C")
            data["fit_percent"] = fit_info["fit_percent"]
            data["fit_per_channel"] = fit_info["fit_per_channel"]
            data["rmse"] = fit_info["rmse"]
            diagnostics["fit_percent"] = fit_info["fit_percent"]
            diagnostics["fit_per_channel"] = fit_info["fit_per_channel"]
            diagnostics["rmse"] = fit_info["rmse"]
            diagnostics["rmse_per_channel"] = fit_info["rmse_per_channel"]
            if not fit_info["fit_defined"]:
                warnings_out.append(
                    WarningItem(
                        code="CONSTANT_OUTPUT_FIT_UNDEFINED",
                        message="Saída medida constante na simulação livre; FIT% indefinido.",
                        details={"rmse": fit_info["rmse"]},
                    )
                )

        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except Exception as exc:
        return handle_id_failure(
            exc,
            prov=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings=warnings_out,
            raise_on_error=raise_on_error,
        )


def validate_model(
    model: IdentifiedModel | StateSpace | TransferFunction | Mapping[str, Any],
    val_dataset: Dataset | Mapping[str, Any],
    *,
    train_dataset: Dataset | Mapping[str, Any] | None = None,
    max_lag: int = 20,
    allow_irregular_sampling: bool = False,
    raise_on_error: bool = False,
) -> Result:
    """Valida modelo identificado em conjunto de holdout/validação separado do conjunto de treino (T-ID-03).

    Calcula explicitamente métricas de:
    1. Previsão de 1 passo à frente (`one_step_prediction`) e
    2. Simulação livre (`free_simulation`),
    separando conjunto de treino e conjunto de validação (`holdout`), além de análise estatística de resíduos
    (autocorrelação $R_{\\varepsilon\\varepsilon}(\\tau)$ e correlação cruzada $R_{u\\varepsilon}(\\tau)$ com intervalos de 95% e 99%)
    e polos discretos estimados.
    """
    prov = build_provenance("identification.validate_model")
    assumptions: dict[str, Any] = {
        "separate_holdout_validation": True,
        "reports_both_prediction_and_free_simulation": True,
    }
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        info = _extract_model_structure(model)
        id_mod: IdentifiedModel | None = info["identified_model"]
        inner = info["inner_model"]
        dt_val = info["dt"]

        ds_val = resolve_dataset_inputs(
            val_dataset,
            dt=dt_val,
            require_uniform=not allow_irregular_sampling,
            allow_irregular_sampling=allow_irregular_sampling,
        )
        warnings_out.extend(ds_val.warnings)

        ds_train: Dataset | None = None
        if train_dataset is not None:
            ds_train = resolve_dataset_inputs(
                train_dataset,
                dt=dt_val,
                require_uniform=not allow_irregular_sampling,
                allow_irregular_sampling=allow_irregular_sampling,
            )
            if ds_train.id == ds_val.id and np.array_equal(ds_train.t, ds_val.t):
                raise HypothesisViolatedError(
                    message="Contaminação de validação detectada: conjunto de validação idêntico ao conjunto de treino.",
                    next_step="Utilize partições disjuntas (ex.: Dataset.train_val_split) para treino e holdout.",
                )

        pred_val = predict(
            model,
            ds_val,
            allow_irregular_sampling=allow_irregular_sampling,
            raise_on_error=True,
        )
        sim_val = simulate(
            model,
            ds_val,
            allow_irregular_sampling=allow_irregular_sampling,
            raise_on_error=True,
        )
        assert pred_val.data is not None and sim_val.data is not None
        warnings_out.extend(pred_val.warnings)

        res_val_arr = tensor_to_array(pred_val.data["residuals"])
        mlag = int(pred_val.data["max_lag"])
        u_eval_val = ds_val.u[mlag:] if ds_val.n_samples > mlag else ds_val.u
        resid_stats_val = analyze_residuals(res_val_arr, u_eval_val, max_lag=max_lag)

        val_metrics: dict[str, Any] = {
            "partition": "validation",
            "n_samples": ds_val.n_samples,
            "one_step_prediction": {
                "evaluation_mode": "one_step_prediction",
                "fit_percent": pred_val.data["fit_percent"],
                "fit_per_channel": pred_val.data["fit_per_channel"],
                "rmse": pred_val.data["rmse"],
            },
            "free_simulation": {
                "evaluation_mode": "free_simulation",
                "fit_percent": sim_val.data["fit_percent"],
                "fit_per_channel": sim_val.data["fit_per_channel"],
                "rmse": sim_val.data["rmse"],
            },
        }

        train_metrics: dict[str, Any] | None = None
        if ds_train is not None:
            pred_tr = predict(
                model,
                ds_train,
                allow_irregular_sampling=allow_irregular_sampling,
                raise_on_error=True,
            )
            sim_tr = simulate(
                model,
                ds_train,
                allow_irregular_sampling=allow_irregular_sampling,
                raise_on_error=True,
            )
            assert pred_tr.data is not None and sim_tr.data is not None
            train_metrics = {
                "partition": "train",
                "n_samples": ds_train.n_samples,
                "one_step_prediction": {
                    "evaluation_mode": "one_step_prediction",
                    "fit_percent": pred_tr.data["fit_percent"],
                    "fit_per_channel": pred_tr.data["fit_per_channel"],
                    "rmse": pred_tr.data["rmse"],
                },
                "free_simulation": {
                    "evaluation_mode": "free_simulation",
                    "fit_percent": sim_tr.data["fit_percent"],
                    "fit_per_channel": sim_tr.data["fit_per_channel"],
                    "rmse": sim_tr.data["rmse"],
                },
            }
        elif id_mod is not None and "train" in id_mod.metrics:
            train_metrics = copy.deepcopy(id_mod.metrics["train"])

        # Polos discretos estimados e margem de estabilidade (raio espectral < 1)
        if isinstance(inner, StateSpace):
            poles = inner.poles()
        elif isinstance(inner, TransferFunction):
            ss_conv = inner.to_state_space()
            poles = ss_conv.poles()
        else:
            poles = np.array([], dtype=np.complex128)

        order = np.lexsort((np.imag(poles), np.real(poles))) if poles.size > 0 else np.array([], dtype=int)
        poles_sorted = poles[order] if poles.size > 0 else poles
        spectral_radius = float(np.max(np.abs(poles_sorted))) if poles_sorted.size > 0 else 0.0
        is_stable = bool(spectral_radius < 1.0 - 1e-12) if poles_sorted.size > 0 else True

        updated_id_model: dict[str, Any] | None = None
        if id_mod is not None:
            merged_metrics = copy.deepcopy(id_mod.metrics)
            merged_metrics["validation"] = val_metrics
            if train_metrics is not None:
                merged_metrics["train"] = train_metrics
            merged_resid = copy.deepcopy(id_mod.residual_diagnostics)
            merged_resid["validation"] = resid_stats_val
            evolved = id_mod.with_revision(
                id_mod.revision + 1,
                metrics=merged_metrics,
                residual_diagnostics=merged_resid,
            )
            updated_id_model = evolved.to_dict()

        diagnostics = {
            "validation_metrics": val_metrics,
            "train_metrics": train_metrics,
            "residual_diagnostics": resid_stats_val,
            "spectral_radius": spectral_radius,
            "is_stable": is_stable,
        }
        data = {
            "validation_metrics": val_metrics,
            "train_metrics": train_metrics,
            "residual_diagnostics": resid_stats_val,
            "poles": complex_to_pair(poles_sorted),
            "spectral_radius": spectral_radius,
            "is_stable": is_stable,
            "y_hat_one_step": pred_val.data["y_hat"],
            "y_hat_free_sim": sim_val.data["y_hat"],
            "updated_identified_model": updated_id_model,
        }
        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except Exception as exc:
        return handle_id_failure(
            exc,
            prov=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings=warnings_out,
            raise_on_error=raise_on_error,
        )


def publish_identified_model(
    identified_model: IdentifiedModel | Mapping[str, Any],
    *,
    target_kind: str = "both",
    raise_on_error: bool = False,
) -> Result:
    """Publica `IdentifiedModel` como `TransferFunction` e/ou `StateSpace` discreto canônico (R-06).

    Permite reutilização imediata do modelo identificado nas Abas 2 (Frequência SISO/MIMO: Bode,
    Root Locus, margens, compensadores) e 3 (Espaço de Estados: LQR/DARE, observadores, simulação)
    sem cópia manual de coeficientes e preservando proveniência, incerteza/covariância e métricas de ajuste.
    """
    prov = build_provenance("identification.publish_identified_model")
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if isinstance(identified_model, Mapping):
            id_mod = IdentifiedModel.from_dict(identified_model)
        elif isinstance(identified_model, IdentifiedModel):
            id_mod = identified_model
        else:
            raise UnsupportedModelError(
                f"publish_identified_model requer IdentifiedModel, recebido {type(identified_model).__name__}."
            )

        if not isinstance(target_kind, str) or target_kind.lower() not in (
            "both",
            "transfer_function",
            "transferfunction",
            "state_space",
            "statespace",
        ):
            raise ValidationError(
                f"target_kind inválido: {target_kind!r}. Use 'both', 'TransferFunction' ou 'StateSpace'."
            )
        tk = target_kind.lower()

        inner = id_mod.model
        pub_meta = {
            "published_from_identified_model": {
                "id": id_mod.id,
                "revision": id_mod.revision,
                "algorithm": id_mod.algorithm,
                "dataset_ref": id_mod.dataset_ref,
                "metrics": id_mod.metrics,
            }
        }

        tf_obj: TransferFunction | None = None
        ss_obj: StateSpace | None = None

        if isinstance(inner, TransferFunction):
            tf_prov = copy.deepcopy(inner.provenance)
            tf_prov.update(pub_meta)
            # Normaliza para variável 'z' descendente para interoperabilidade direta com tf2ss, Bode e Root Locus
            p, m = inner.n_outputs, inner.n_inputs
            num_z_grid: list[list[np.ndarray]] = []
            den_z_grid: list[list[np.ndarray]] = []
            for i in range(p):
                row_n: list[np.ndarray] = []
                row_d: list[np.ndarray] = []
                for j in range(m):
                    n_ij, d_ij = inner._channel_descending_z_or_s(i, j)
                    row_n.append(n_ij)
                    row_d.append(d_ij)
                num_z_grid.append(row_n)
                den_z_grid.append(row_d)

            tf_obj = TransferFunction(
                num=num_z_grid,
                den=den_z_grid,
                dt=inner.dt,
                variable="z",
                poly_order="descending",
                input_names=inner.input_names,
                output_names=inner.output_names,
                units=inner.units,
                provenance=tf_prov,
            )
            warnings_out.extend(tf_obj.warnings)
            if tk in ("both", "state_space", "statespace"):
                ss_raw = tf_obj.to_state_space()
                ss_prov = copy.deepcopy(ss_raw.provenance)
                ss_prov.update(pub_meta)
                ss_obj = ss_raw.with_revision(ss_raw.revision, provenance=ss_prov)
        elif isinstance(inner, StateSpace):
            ss_prov = copy.deepcopy(inner.provenance)
            ss_prov.update(pub_meta)
            ss_obj = inner.with_revision(inner.revision, provenance=ss_prov)
            if tk in ("both", "transfer_function", "transferfunction"):
                tf_raw = TransferFunction.from_state_space(ss_obj)
                tf_prov = copy.deepcopy(tf_raw.provenance)
                tf_prov.update(pub_meta)
                tf_obj = tf_raw.with_revision(tf_raw.revision, provenance=tf_prov)
                warnings_out.extend(tf_obj.warnings)
        elif isinstance(inner, TSStateSpace):
            raise UnsupportedModelError(
                "Modelos TSStateSpace identificados já são publicados diretamente para síntese TS/PDC."
            )
        else:
            raise UnsupportedModelError(f"Modelo interno não suportado para publicação: {type(inner).__name__}.")

        assumptions = {
            "discrete_time": True,
            "dt": float(tf_obj.dt if tf_obj is not None else ss_obj.dt),  # type: ignore[arg-type]
            "interoperable_with_siso_mimo_and_statespace": True,
        }
        diagnostics = {
            "identified_model_id": id_mod.id,
            "identified_model_revision": id_mod.revision,
            "algorithm": id_mod.algorithm,
            "has_transfer_function": tf_obj is not None,
            "has_state_space": ss_obj is not None,
            "n_states": ss_obj.n_states if ss_obj is not None else None,
        }
        data: dict[str, Any] = {
            "identified_model": id_mod.to_dict(),
            "transfer_function": tf_obj.to_dict() if tf_obj is not None else None,
            "state_space": ss_obj.to_dict() if ss_obj is not None else None,
        }
        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except Exception as exc:
        return handle_id_failure(
            exc,
            prov=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings=warnings_out,
            raise_on_error=raise_on_error,
        )
