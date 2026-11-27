"""Treinamento ANFIS híbrido (QR/SVD + gradiente descendente) sem uso de inv (CL-DIR-001 Seção 5.1, 5.6 e 13.7)."""

from __future__ import annotations

import itertools
from typing import Any, Sequence

import numpy as np

from control_lab.core.models import FuzzySystem
from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

_EPS = 1e-12
MAX_ANFIS_RULES = 512


def _compute_rmse_and_fit(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    err = y_true - y_pred
    rmse = float(np.sqrt(np.mean(np.square(err))))
    denom = float(np.linalg.norm(y_true - np.mean(y_true)))
    if denom <= _EPS:
        fit = 100.0 if rmse <= _EPS else 0.0
    else:
        fit = float(100.0 * (1.0 - float(np.linalg.norm(err)) / denom))
    return rmse, fit


def _compute_multioutput_metrics(
    Y_true: np.ndarray,
    Y_pred: np.ndarray,
    out_names: Sequence[str],
) -> tuple[float, float, dict[str, float], dict[str, float]]:
    """Calcula RMSE/FIT agregados e por saída para `Y_true`, `Y_pred` de shape `(N, M_out)`."""
    m_out = Y_true.shape[1]
    rmse_per_out: dict[str, float] = {}
    fit_per_out: dict[str, float] = {}
    for j in range(m_out):
        r_j, f_j = _compute_rmse_and_fit(Y_true[:, j], Y_pred[:, j])
        rmse_per_out[out_names[j]] = r_j
        fit_per_out[out_names[j]] = f_j
    if m_out == 1:
        return rmse_per_out[out_names[0]], fit_per_out[out_names[0]], rmse_per_out, fit_per_out
    agg_rmse = float(np.sqrt(np.mean(np.square(Y_true - Y_pred))))
    agg_fit = float(np.mean(list(fit_per_out.values())))
    return agg_rmse, agg_fit, rmse_per_out, fit_per_out


def _normalize_single_mf_type(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError(
            message=f"fit_anfis suporta mf_type 'gaussian' ou 'bell', recebido {raw!r}.",
            parameters={"mf_type": raw, "allowed": ["gaussian", "bell"]},
        )
    mf_kind = raw.strip().lower()
    if mf_kind in ("gauss", "gaussian", "gaussmf"):
        return "gaussian"
    if mf_kind in ("bell", "gbell", "gbellmf"):
        return "bell"
    raise ValidationError(
        message=f"fit_anfis suporta mf_type 'gaussian' ou 'bell', recebido {raw!r}.",
        parameters={"mf_type": raw, "allowed": ["gaussian", "bell"]},
    )


def _solve_consequents_qr_svd(
    Phi: np.ndarray,
    y: np.ndarray,
    *,
    rcond: float = 1e-10,
) -> tuple[np.ndarray, int, float, str]:
    """Resolve mínimos quadrados lineares `Phi @ theta ≈ y` por QR (posto completo) ou SVD truncada, sem `inv`.

    Suporta `y` 1D `(N,)` ou 2D `(N, M_out)` resolvendo todas as saídas simultaneamente.
    """
    n_samples, n_params = Phi.shape
    svals = np.linalg.svd(Phi, compute_uv=False)
    s_max = float(svals[0]) if svals.size > 0 else 0.0
    s_min = float(svals[-1]) if svals.size > 0 else 0.0
    tol = rcond * max(n_samples, n_params) * max(s_max, _EPS)
    rank = int(np.sum(svals > tol))
    cond = float(s_max / max(s_min, _EPS)) if s_max > _EPS else float("inf")

    if n_samples >= n_params and rank == n_params:
        # Fatoração QR fina: Q^T y resolvido por substituição triangular superior (np.linalg.solve)
        Q, R = np.linalg.qr(Phi, mode="reduced")
        rhs = Q.T @ y
        try:
            theta = np.linalg.solve(R, rhs)
            return theta, rank, cond, "qr"
        except np.linalg.LinAlgError:
            pass

    # Fallback estável por SVD truncada (jamais usa inv explícita)
    U, s, Vt = np.linalg.svd(Phi, full_matrices=False)
    s_inv = np.where(s > tol, 1.0 / np.maximum(s, _EPS), 0.0)
    uty = U.T @ y
    scaled = (s_inv[:, None] * uty) if uty.ndim == 2 else (s_inv * uty)
    theta = Vt.T @ scaled
    return theta, rank, cond, "svd"


def _eval_premise_1d_gaussian(
    x_col: np.ndarray,
    centers_d: np.ndarray,
    sigmas_d: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Avalia pertinências gaussianas 1D `mu[N, M_d]` e derivadas `dmu/dc`, `dmu/dsigma`."""
    diff = x_col[:, None] - centers_d[None, :]  # (N, M_d)
    s_safe = np.maximum(sigmas_d[None, :], 1e-4)
    q = diff / s_safe
    mu = np.exp(-0.5 * np.square(q))
    mu = np.clip(mu, _EPS, 1.0)
    dmu_dc = mu * (diff / np.square(s_safe))
    dmu_ds = mu * (np.square(diff) / np.power(s_safe, 3))
    return mu, dmu_dc, dmu_ds


def _eval_premise_1d_bell(
    x_col: np.ndarray,
    a_d: np.ndarray,
    b_d: np.ndarray,
    c_d: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Avalia pertinências Generalized Bell 1D `1 / (1 + |(x-c)/a|^(2b))` e derivadas `da, db, dc`."""
    diff = x_col[:, None] - c_d[None, :]
    a_safe = np.maximum(a_d[None, :], 1e-4)
    b_safe = np.maximum(b_d[None, :], 1e-2)
    u = np.abs(diff / a_safe)
    u_safe = np.maximum(u, 1e-8)
    p = np.power(u_safe, 2.0 * b_safe)
    mu = 1.0 / (1.0 + p)
    mu = np.clip(mu, _EPS, 1.0)

    common = np.square(mu) * p
    dmu_da = common * (2.0 * b_safe / a_safe)
    safe_diff = np.where(np.abs(diff) <= 1e-10, 1.0, diff)
    dmu_dc = np.where(
        np.abs(diff) <= 1e-10,
        0.0,
        common * (2.0 * b_safe / safe_diff),
    )
    dmu_db = -common * (2.0 * np.log(u_safe))
    return mu, dmu_da, dmu_db, dmu_dc


def _eval_premises_hetero(
    X: np.ndarray,
    centers: list[np.ndarray],
    sigmas: list[np.ndarray],
    bell_b: list[np.ndarray],
    mf_types: Sequence[str],
) -> tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray], list[np.ndarray | None]]:
    """Avalia pertinências e derivadas por entrada para grade cartesiana heterogênea."""
    mu_list: list[np.ndarray] = []
    dmu_dc_list: list[np.ndarray] = []
    dmu_ds_list: list[np.ndarray] = []
    dmu_db_list: list[np.ndarray | None] = []
    for d, kind in enumerate(mf_types):
        if kind == "gaussian":
            mu_d, dc_d, ds_d = _eval_premise_1d_gaussian(X[:, d], centers[d], sigmas[d])
            mu_list.append(mu_d)
            dmu_dc_list.append(dc_d)
            dmu_ds_list.append(ds_d)
            dmu_db_list.append(None)
        else:
            mu_d, da_d, db_d, dc_d = _eval_premise_1d_bell(X[:, d], sigmas[d], bell_b[d], centers[d])
            mu_list.append(mu_d)
            dmu_dc_list.append(dc_d)
            dmu_ds_list.append(da_d)
            dmu_db_list.append(db_d)
    return mu_list, dmu_dc_list, dmu_ds_list, dmu_db_list


def _forward_layer_activations(
    mu_list: Sequence[np.ndarray],
    rule_grid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calcula `w` (N, R), `sum_w` (N,) e `h` (N, R) a partir de lista `mu_list[d]` (N, M_d) e `rule_grid` (R, n_in)."""
    N = mu_list[0].shape[0]
    n_in = len(mu_list)
    R = rule_grid.shape[0]
    rule_mu = np.empty((N, R, n_in), dtype=np.float64)
    for d in range(n_in):
        rule_mu[:, :, d] = mu_list[d][:, rule_grid[:, d]]
    w = np.prod(rule_mu, axis=2)  # T-norma produto diferenciável
    sum_w = np.sum(w, axis=1)
    safe_denom = np.where(sum_w > _EPS, sum_w, 1.0)
    h = w / safe_denom[:, None]
    return w, sum_w, h


def _build_regressor_matrix(X: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Constrói matriz regressora ANFIS `Phi` de shape `(N, R * (n_in + 1))` com `[x_1, ..., x_d, 1]` por regra."""
    N, n_in = X.shape
    R = h.shape[1]
    X_aug = np.hstack([X, np.ones((N, 1), dtype=np.float64)])  # (N, n_in + 1)
    # Produto de Kronecker por linha: h[:, :, None] * X_aug[:, None, :] -> (N, R, n_in + 1)
    Phi = (h[:, :, None] * X_aug[:, None, :]).reshape(N, R * (n_in + 1))
    return Phi


def fit_anfis(
    X: Any,
    y: Any,
    *,
    n_mfs: int | Sequence[int] = 2,
    mf_type: str | Sequence[str] = "gaussian",
    max_epochs: int = 30,
    learning_rate: float = 0.01,
    validation_split: float = 0.2,
    X_val: Any = None,
    y_val: Any = None,
    early_stopping_patience: int = 8,
    seed: int = 42,
    input_names: Sequence[str] | None = None,
    output_name: str = "y",
    output_names: Sequence[str] | None = None,
    rcond: float = 1e-10,
) -> Result:
    """Ajusta um aproximador Takagi-Sugeno de 1ª ordem via algoritmo ANFIS híbrido (Jang, 1993).

    Suporta:
    - Grade cartesiana heterogênea de funções de pertinência por entrada (`n_mfs: int | Sequence[int]`, 2..10, prod <= 512).
    - Tipos de pertinência por entrada (`mf_type: str | Sequence[str]`, `'gaussian'` ou `'bell'`).
    - Saída escalar `(N,)` / `(N, 1)` ou multi-saída `(N, M_out)` com resolução simultânea por QR/SVD e
      retropropagação do gradiente da soma de MSE para os parâmetros de premissa compartilhados.
    - Retorna `FuzzySystem` estático (`is_dynamic_model=False`, respeitando `ADR-006`).
    """
    try:
        X_arr = ensure_finite_float64(X, name="X")
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)
        elif X_arr.ndim != 2:
            raise DimensionMismatchError(f"X deve ser 1D ou 2D (N, n_inputs), recebido shape={X_arr.shape}.")

        y_arr = ensure_finite_float64(y, name="y")
        if y_arr.ndim == 1:
            Y_arr = y_arr.reshape(-1, 1)
        elif y_arr.ndim == 2 and y_arr.shape[1] >= 1:
            Y_arr = y_arr
        else:
            raise DimensionMismatchError(
                f"y deve ser 1D (N,) ou 2D (N, M_out) com M_out >= 1, recebido shape={y_arr.shape}."
            )

        n_total, n_in = X_arr.shape
        if Y_arr.shape[0] != n_total:
            raise DimensionMismatchError(
                message=f"Número de amostras em X ({n_total}) difere de y ({Y_arr.shape[0]}).",
                parameters={"X_rows": n_total, "y_rows": int(Y_arr.shape[0])},
            )
        if n_total < 4:
            raise ValidationError("fit_anfis requer pelo menos 4 amostras.")

        M_out = int(Y_arr.shape[1])

        if isinstance(mf_type, str):
            mf_types_per_input = [_normalize_single_mf_type(mf_type)] * n_in
        elif isinstance(mf_type, Sequence) and not isinstance(mf_type, (bytes, bytearray)):
            if len(mf_type) != n_in:
                raise DimensionMismatchError(
                    message=f"mf_type deve ter comprimento {n_in}, recebido {len(mf_type)}.",
                    parameters={"expected_inputs": n_in, "actual_len": len(mf_type)},
                )
            mf_types_per_input = [_normalize_single_mf_type(m) for m in mf_type]
        else:
            raise ValidationError(
                message=f"mf_type deve ser str ou sequência de str, recebido {type(mf_type).__name__}.",
                parameters={"mf_type": repr(mf_type)},
            )

        if isinstance(n_mfs, int) and not isinstance(n_mfs, bool):
            if n_mfs < 2 or n_mfs > 10:
                raise ValidationError("n_mfs deve estar entre 2 e 10.")
            mfs_per_input = [n_mfs] * n_in
        elif isinstance(n_mfs, Sequence) and not isinstance(n_mfs, (str, bytes)):
            if len(n_mfs) != n_in:
                raise DimensionMismatchError(f"n_mfs deve ter comprimento {n_in}, recebido {len(n_mfs)}.")
            mfs_per_input = []
            for v in n_mfs:
                if isinstance(v, bool) or not isinstance(v, (int, np.integer)):
                    raise ValidationError(f"Cada elemento de n_mfs deve ser inteiro entre 2 e 10, recebido {v!r}.")
                iv = int(v)
                if iv < 2 or iv > 10:
                    raise ValidationError("Cada entrada deve ter entre 2 e 10 funções de pertinência.")
                mfs_per_input.append(iv)
        else:
            raise ValidationError("n_mfs deve ser inteiro ou sequência de inteiros.")

        R_count = 1
        for m_d in mfs_per_input:
            R_count *= m_d
        if R_count > MAX_ANFIS_RULES:
            raise ValidationError(
                message=(
                    f"Número de regras da grade cartesiana ({R_count}) excede o limite máximo permitido "
                    f"({MAX_ANFIS_RULES})."
                ),
                parameters={"n_rules": R_count, "max_rules": MAX_ANFIS_RULES, "mfs_per_input": mfs_per_input},
            )

        if isinstance(max_epochs, bool) or not isinstance(max_epochs, int) or max_epochs < 1:
            raise ValidationError("max_epochs deve ser inteiro >= 1.")
        if learning_rate <= 0.0 or not np.isfinite(learning_rate):
            raise ValidationError("learning_rate deve ser positivo e finito.")
        if not (0.0 <= validation_split < 0.8):
            raise ValidationError("validation_split deve estar em [0.0, 0.8).")

        in_names = (
            [str(nm) for nm in input_names]
            if input_names is not None
            else [f"x{i + 1}" for i in range(n_in)]
        )
        if len(in_names) != n_in:
            raise DimensionMismatchError(f"input_names tem {len(in_names)} elementos, esperado {n_in}.")

        if output_names is not None:
            if isinstance(output_names, (str, bytes)) or not isinstance(output_names, Sequence):
                raise ValidationError("output_names deve ser uma sequência de strings.")
            if len(output_names) != M_out:
                raise DimensionMismatchError(
                    message=f"output_names tem {len(output_names)} elementos, esperado {M_out}.",
                    parameters={"expected_outputs": M_out, "actual_len": len(output_names)},
                )
            out_names = [str(nm) for nm in output_names]
            if any(not nm.strip() for nm in out_names):
                raise ValidationError("output_names não pode conter nomes vazios.")
            if len(set(out_names)) != M_out:
                raise ValidationError(f"output_names contém nomes duplicados: {out_names!r}.")
        else:
            out_names = [str(output_name)] if M_out == 1 else [f"y{j + 1}" for j in range(M_out)]

        # Partição treino / validação
        if X_val is not None and y_val is not None:
            X_tr = X_arr
            Y_tr = Y_arr
            X_va = ensure_finite_float64(X_val, name="X_val")
            if X_va.ndim == 1:
                X_va = X_va.reshape(-1, 1)
            elif X_va.ndim != 2:
                raise DimensionMismatchError(f"X_val deve ser 1D ou 2D, recebido shape={X_va.shape}.")
            y_va_raw = ensure_finite_float64(y_val, name="y_val")
            if y_va_raw.ndim == 1:
                Y_va = y_va_raw.reshape(-1, 1)
            elif y_va_raw.ndim == 2 and y_va_raw.shape[1] >= 1:
                Y_va = y_va_raw
            else:
                raise DimensionMismatchError(f"y_val deve ser 1D ou 2D, recebido shape={y_va_raw.shape}.")
            if X_va.shape[1] != n_in or X_va.shape[0] != Y_va.shape[0] or Y_va.shape[1] != M_out:
                raise DimensionMismatchError("Dimensões de X_val e y_val incompatíveis.")
        elif validation_split > 0.0 and n_total >= 6:
            rng = np.random.default_rng(seed)
            perm = rng.permutation(n_total)
            n_val = max(1, int(round(n_total * validation_split)))
            n_train = n_total - n_val
            tr_idx = perm[:n_train]
            va_idx = perm[n_train:]
            X_tr, Y_tr = X_arr[tr_idx], Y_arr[tr_idx]
            X_va, Y_va = X_arr[va_idx], Y_arr[va_idx]
        else:
            X_tr, Y_tr = X_arr, Y_arr
            X_va, Y_va = X_arr, Y_arr

        # Inicializa centros e larguras por entrada (arrays 1D heterogêneos)
        x_min = np.min(X_arr, axis=0)
        x_max = np.max(X_arr, axis=0)
        spans = np.maximum(x_max - x_min, 1e-3)

        centers: list[np.ndarray] = []
        sigmas: list[np.ndarray] = []
        bell_b: list[np.ndarray] = []
        for d in range(n_in):
            m_d = mfs_per_input[d]
            centers.append(np.linspace(x_min[d], x_max[d], m_d, dtype=np.float64))
            step = spans[d] / max(1, m_d - 1)
            sigmas.append(np.full(m_d, max(step / 1.5, 1e-2), dtype=np.float64))
            bell_b.append(np.full(m_d, 2.0, dtype=np.float64))

        rule_tuples = list(itertools.product(*[range(m_d) for m_d in mfs_per_input]))
        rule_grid = np.array(rule_tuples, dtype=np.int64)  # (R, n_in)
        R = rule_grid.shape[0]
        p_per_rule = n_in + 1

        # Pré-indexa regras por par (entrada d, termo m_idx) para o backward pass
        rules_by_dm: list[list[np.ndarray]] = [
            [np.where(rule_grid[:, d] == m_idx)[0] for m_idx in range(mfs_per_input[d])]
            for d in range(n_in)
        ]

        best_val_rmse = float("inf")
        best_theta: np.ndarray | None = None
        best_centers = [c.copy() for c in centers]
        best_sigmas = [s.copy() for s in sigmas]
        best_bell_b = [b.copy() for b in bell_b]
        best_epoch = 0
        best_rank = 0
        best_cond = 1.0
        best_solver = "qr"
        patience_counter = 0

        train_rmse_history: list[float] = []
        val_rmse_history: list[float] = []

        X_aug_tr = np.hstack([X_tr, np.ones((X_tr.shape[0], 1), dtype=np.float64)])

        for epoch in range(max_epochs):
            # 1. Forward pass: avalia premissas e resolve consequentes para todas as saídas por QR/SVD
            mu_tr, dmu_dc, dmu_ds, dmu_db = _eval_premises_hetero(
                X_tr, centers, sigmas, bell_b, mf_types_per_input
            )
            w_tr, sum_w_tr, h_tr = _forward_layer_activations(mu_tr, rule_grid)
            Phi_tr = _build_regressor_matrix(X_tr, h_tr)
            theta, rank, cond, solver_used = _solve_consequents_qr_svd(Phi_tr, Y_tr, rcond=rcond)

            Y_hat_tr = Phi_tr @ theta  # (N_tr, M_out)
            tr_rmse, _, _, _ = _compute_multioutput_metrics(Y_tr, Y_hat_tr, out_names)
            train_rmse_history.append(tr_rmse)

            # Avalia na validação
            mu_va, _, _, _ = _eval_premises_hetero(
                X_va, centers, sigmas, bell_b, mf_types_per_input
            )
            _, _, h_va = _forward_layer_activations(mu_va, rule_grid)
            Phi_va = _build_regressor_matrix(X_va, h_va)
            Y_hat_va = Phi_va @ theta  # (N_va, M_out)
            va_rmse, _, _, _ = _compute_multioutput_metrics(Y_va, Y_hat_va, out_names)
            val_rmse_history.append(va_rmse)

            if va_rmse < best_val_rmse - 1e-10:
                best_val_rmse = va_rmse
                best_theta = theta.copy()
                best_centers = [c.copy() for c in centers]
                best_sigmas = [s.copy() for s in sigmas]
                best_bell_b = [b.copy() for b in bell_b]
                best_epoch = epoch + 1
                best_rank = rank
                best_cond = cond
                best_solver = solver_used
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= early_stopping_patience:
                    break

            # 2. Backward pass: gradiente descendente nas premissas com consequentes fixos
            if epoch == max_epochs - 1:
                break

            theta_mat = theta.reshape(R, p_per_rule, M_out)  # (R, n_in + 1, M_out)
            f_rules = np.einsum("np,rpk->nrk", X_aug_tr, theta_mat)  # (N_tr, R, M_out)
            err_tr = Y_hat_tr - Y_tr  # (N_tr, M_out): dE/dy_hat para E = 1/(2N) sum_{n,k} (y_hat - y)^2
            safe_sw = np.where(sum_w_tr > _EPS, sum_w_tr, 1.0)
            # dy_hat_k / dw_r = (f_{r,k} - y_hat_k) / sum_w
            dy_dw = (f_rules - Y_hat_tr[:, None, :]) / safe_sw[:, None, None]  # (N_tr, R, M_out)
            dE_dw = np.sum((err_tr[:, None, :] / float(X_tr.shape[0])) * dy_dw, axis=2)  # (N_tr, R)

            for d in range(n_in):
                m_d = mfs_per_input[d]
                kind_d = mf_types_per_input[d]
                grad_c_d: np.ndarray = np.zeros(m_d, dtype=np.float64)
                grad_s_d: np.ndarray = np.zeros(m_d, dtype=np.float64)
                grad_b_d: np.ndarray = np.zeros(m_d, dtype=np.float64)
                dmu_db_d = dmu_db[d]

                for m_idx in range(m_d):
                    rules_with_dm = rules_by_dm[d][m_idx]
                    if rules_with_dm.size == 0:
                        continue
                    mu_dm = np.maximum(mu_tr[d][:, m_idx], _EPS)  # (N_tr,)
                    # dw_r / dmu_{d,m} = w_r / mu_{d,m}
                    dw_dmu = np.sum(
                        dE_dw[:, rules_with_dm] * (w_tr[:, rules_with_dm] / mu_dm[:, None]),
                        axis=1,
                    )  # (N_tr,)
                    grad_c_d[m_idx] = float(np.sum(dw_dmu * dmu_dc[d][:, m_idx]))
                    grad_s_d[m_idx] = float(np.sum(dw_dmu * dmu_ds[d][:, m_idx]))
                    if kind_d == "bell" and dmu_db_d is not None:
                        grad_b_d[m_idx] = float(np.sum(dw_dmu * dmu_db_d[:, m_idx]))

                # Normalização de passo por variável para estabilidade numérica
                scale_d = spans[d]
                gc_norm = float(np.linalg.norm(grad_c_d))
                gs_norm = float(np.linalg.norm(grad_s_d))
                if gc_norm > _EPS:
                    centers[d] -= learning_rate * scale_d * (grad_c_d / max(1.0, gc_norm))
                if gs_norm > _EPS:
                    sigmas[d] -= learning_rate * scale_d * (grad_s_d / max(1.0, gs_norm))
                sigmas[d] = np.maximum(sigmas[d], 1e-3 * scale_d)
                if kind_d == "bell":
                    gb_norm = float(np.linalg.norm(grad_b_d))
                    if gb_norm > _EPS:
                        bell_b[d] -= 0.5 * learning_rate * (grad_b_d / max(1.0, gb_norm))
                    bell_b[d] = np.clip(bell_b[d], 0.2, 20.0)

        assert best_theta is not None
        # Recalcula predições finais com os melhores parâmetros
        mu_tr_f, _, _, _ = _eval_premises_hetero(
            X_tr, best_centers, best_sigmas, best_bell_b, mf_types_per_input
        )
        mu_va_f, _, _, _ = _eval_premises_hetero(
            X_va, best_centers, best_sigmas, best_bell_b, mf_types_per_input
        )

        _, _, h_tr_f = _forward_layer_activations(mu_tr_f, rule_grid)
        _, _, h_va_f = _forward_layer_activations(mu_va_f, rule_grid)
        Y_pred_tr = _build_regressor_matrix(X_tr, h_tr_f) @ best_theta  # (N_tr, M_out)
        Y_pred_va = _build_regressor_matrix(X_va, h_va_f) @ best_theta  # (N_va, M_out)

        final_tr_rmse, final_tr_fit, tr_rmse_per_out, tr_fit_per_out = _compute_multioutput_metrics(
            Y_tr, Y_pred_tr, out_names
        )
        final_va_rmse, final_va_fit, va_rmse_per_out, va_fit_per_out = _compute_multioutput_metrics(
            Y_va, Y_pred_va, out_names
        )

        # Constrói FuzzySystem Takagi-Sugeno estático (is_dynamic_model=False conforme ADR-006)
        in_vars_spec: list[dict[str, Any]] = []
        for d in range(n_in):
            margin = 0.05 * spans[d]
            univ = [float(x_min[d] - margin), float(x_max[d] + margin)]
            terms_d: list[dict[str, Any]] = []
            kind_d = mf_types_per_input[d]
            for m_idx in range(mfs_per_input[d]):
                tname = f"{in_names[d]}_mf{m_idx + 1}"
                if kind_d == "gaussian":
                    terms_d.append(
                        {
                            "name": tname,
                            "mf": "gaussian",
                            "params": [float(best_centers[d][m_idx]), float(best_sigmas[d][m_idx])],
                        }
                    )
                else:
                    terms_d.append(
                        {
                            "name": tname,
                            "mf": "bell",
                            "params": [
                                float(best_sigmas[d][m_idx]),
                                float(best_bell_b[d][m_idx]),
                                float(best_centers[d][m_idx]),
                            ],
                        }
                    )
            in_vars_spec.append({"name": in_names[d], "universe": univ, "terms": terms_d})

        theta_rules = best_theta.reshape(R, p_per_rule, M_out)
        out_vars_spec: list[dict[str, Any]] = []
        for j in range(M_out):
            y_j = Y_arr[:, j]
            y_min, y_max = float(np.min(y_j)), float(np.max(y_j))
            y_span = max(y_max - y_min, 1.0)
            out_univ = [y_min - 0.1 * y_span, y_max + 0.1 * y_span]

            out_terms_j: list[dict[str, Any]] = []
            for r_idx in range(R):
                tname_out = f"rule_{r_idx + 1}_consequent"
                coeffs = [float(v) for v in theta_rules[r_idx, :, j].tolist()]
                out_terms_j.append(
                    {
                        "name": tname_out,
                        "type": "linear",
                        "params": coeffs,
                        "coefficients": coeffs,
                        "bias_last": True,
                    }
                )
            out_vars_spec.append({"name": out_names[j], "universe": out_univ, "terms": out_terms_j})

        rules_spec: list[dict[str, Any]] = []
        for r_idx in range(R):
            tname_out = f"rule_{r_idx + 1}_consequent"
            ants = {
                in_names[d]: f"{in_names[d]}_mf{int(rule_grid[r_idx, d]) + 1}"
                for d in range(n_in)
            }
            cons = {out_nm: tname_out for out_nm in out_names}
            rules_spec.append(
                {
                    "name": f"R{r_idx + 1}",
                    "connector": "and",
                    "antecedents": ants,
                    "consequents": cons,
                    "weight": 1.0,
                }
            )

        anfis_system = FuzzySystem(
            inference_type="ts",
            input_variables=in_vars_spec,
            output_variables=out_vars_spec,
            rules=rules_spec,
            operators={"and": "prod", "or": "probor", "defuzzification": "wtaver"},
            fml_profile="IEEE-1855-2016",
            is_dynamic_model=False,
            dynamic_semantics=None,
            provenance={
                "source": "fit_anfis",
                "seed": seed,
                "consequent_solver": best_solver,
                "is_static_approximator": True,
            },
        )

        warnings_list: list[WarningItem] = []
        n_premise_params = sum(
            mfs_per_input[d] * (2 if mf_types_per_input[d] == "gaussian" else 3)
            for d in range(n_in)
        )
        n_total_params = R * p_per_rule * M_out + n_premise_params
        if best_rank < R * p_per_rule:
            warnings_list.append(
                WarningItem(
                    code="ANFIS_RANK_DEFICIENT_REGRESSOR",
                    message=(
                        f"Matriz regressora de consequentes tem posto deficiente "
                        f"(rank={best_rank} < {R * p_per_rule}); regularização por SVD aplicada."
                    ),
                    details={"rank": best_rank, "expected_rank": R * p_per_rule, "condition_number": best_cond},
                )
            )
        overfit_detected = bool(
            X_va is not X_tr and final_tr_rmse > 1e-9 and (final_va_rmse / max(final_tr_rmse, 1e-6)) > 2.5
        )
        if overfit_detected or (X_tr.shape[0] * M_out) < n_total_params:
            warnings_list.append(
                WarningItem(
                    code="ANFIS_OVERFITTING_RISK",
                    message="Risco de sobreajuste (overfitting) detectado pelo número de parâmetros ou divergência treino/validação.",
                    details={
                        "n_train_samples": int(X_tr.shape[0]),
                        "n_total_parameters": n_total_params,
                        "train_rmse": final_tr_rmse,
                        "val_rmse": final_va_rmse,
                    },
                )
            )

        y_pred_train_out: list[Any] = (
            [float(v) for v in Y_pred_tr[:, 0].tolist()]
            if M_out == 1
            else [[float(v) for v in row] for row in Y_pred_tr.tolist()]
        )
        y_pred_val_out: list[Any] = (
            [float(v) for v in Y_pred_va[:, 0].tolist()]
            if M_out == 1
            else [[float(v) for v in row] for row in Y_pred_va.tolist()]
        )
        history_payload = {
            "train_rmse": train_rmse_history,
            "val_rmse": val_rmse_history,
            "best_epoch": best_epoch,
            "epochs_executed": len(train_rmse_history),
        }

        return Result(
            status="warning" if warnings_list else "success",
            data={
                "fuzzy_system": anfis_system.to_dict(),
                "system_id": anfis_system.id,
                "output_names": out_names,
                "n_outputs": M_out,
                "mfs_per_input": mfs_per_input,
                "mf_types_per_input": mf_types_per_input,
                "rmse_train": final_tr_rmse,
                "rmse_val": final_va_rmse,
                "fit_train_pct": final_tr_fit,
                "fit_val_pct": final_va_fit,
                "rmse_train_per_output": tr_rmse_per_out,
                "rmse_val_per_output": va_rmse_per_out,
                "fit_train_pct_per_output": tr_fit_per_out,
                "fit_val_pct_per_output": va_fit_per_out,
                "y_pred_train": y_pred_train_out,
                "y_pred_val": y_pred_val_out,
                "history": dict(history_payload),
                "metrics": {
                    "train_rmse": final_tr_rmse,
                    "val_rmse": final_va_rmse,
                    "train_fit_percent": final_tr_fit,
                    "val_fit_percent": final_va_fit,
                    "rmse_train_per_output": tr_rmse_per_out,
                    "rmse_val_per_output": va_rmse_per_out,
                    "fit_train_pct_per_output": tr_fit_per_out,
                    "fit_val_pct_per_output": va_fit_per_out,
                },
                "training_history": history_payload,
            },
            assumptions={
                "is_dynamic_model": False,
                "static_io_approximator": True,
                "hybrid_learning": True,
                "consequent_solver": best_solver,
            },
            diagnostics={
                "regressor_rank": best_rank,
                "regressor_columns": R * p_per_rule,
                "condition_number": best_cond if np.isfinite(best_cond) else 1e16,
                "n_rules": R,
                "n_inputs": n_in,
                "n_outputs": M_out,
                "mfs_per_input": mfs_per_input,
                "mf_types_per_input": mf_types_per_input,
                "n_train": int(X_tr.shape[0]),
                "n_val": int(X_va.shape[0]),
                "overfitting_flag": overfit_detected,
            },
            provenance=build_provenance(
                "control_lab.fuzzy.fit_anfis",
                seed=seed,
                tolerances={"rcond": rcond, "learning_rate": learning_rate},
                model_revision=anfis_system.revision,
            ),
            warnings=tuple(warnings_list),
        )
    except ControlLabError as exc:
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=build_provenance("control_lab.fuzzy.fit_anfis", seed=seed),
            warnings=(),
            error=exc.to_typed_error(),
        )

