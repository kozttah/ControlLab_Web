"""Treinamento ANFIS híbrido (QR/SVD + gradiente descendente) sem uso de inv (CL-DIR-001 Seção 5.1, 5.6 e 13.7)."""

from __future__ import annotations

import itertools
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.core.models import FuzzySystem
from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

_EPS = 1e-12


def _compute_rmse_and_fit(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    err = y_true - y_pred
    rmse = float(np.sqrt(np.mean(np.square(err))))
    denom = float(np.linalg.norm(y_true - np.mean(y_true)))
    if denom <= _EPS:
        fit = 100.0 if rmse <= _EPS else 0.0
    else:
        fit = float(100.0 * (1.0 - float(np.linalg.norm(err)) / denom))
    return rmse, fit


def _solve_consequents_qr_svd(
    Phi: np.ndarray,
    y: np.ndarray,
    *,
    rcond: float = 1e-10,
) -> tuple[np.ndarray, int, float, str]:
    """Resolve mínimos quadrados lineares `Phi @ theta ≈ y` por QR (posto completo) ou SVD truncada, sem `inv`."""
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
    theta = Vt.T @ (s_inv * (U.T @ y))
    return theta, rank, cond, "svd"


def _eval_premise_and_grads_gaussian(
    X: np.ndarray,
    centers: np.ndarray,
    sigmas: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Avalia pertinências gaussianas `mu[N, n_in, M]` e derivadas `dmu/dc`, `dmu/dsigma`."""
    # X: (N, n_in), centers/sigmas: (n_in, M)
    diff = X[:, :, None] - centers[None, :, :]  # (N, n_in, M)
    s_safe = np.maximum(sigmas[None, :, :], 1e-4)
    q = diff / s_safe
    mu = np.exp(-0.5 * np.square(q))
    mu = np.clip(mu, _EPS, 1.0)
    dmu_dc = mu * (diff / np.square(s_safe))
    dmu_ds = mu * (np.square(diff) / np.power(s_safe, 3))
    return mu, dmu_dc, dmu_ds


def _eval_premise_and_grads_bell(
    X: np.ndarray,
    a_param: np.ndarray,
    b_param: np.ndarray,
    c_param: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Avalia pertinências Generalized Bell `1 / (1 + |(x-c)/a|^(2b))` e derivadas em relação a `a, b, c`."""
    diff = X[:, :, None] - c_param[None, :, :]
    a_safe = np.maximum(a_param[None, :, :], 1e-4)
    b_safe = np.maximum(b_param[None, :, :], 1e-2)
    u = np.abs(diff / a_safe)
    u_safe = np.maximum(u, 1e-8)
    p = np.power(u_safe, 2.0 * b_safe)
    mu = 1.0 / (1.0 + p)
    mu = np.clip(mu, _EPS, 1.0)

    common = np.square(mu) * p
    dmu_da = common * (2.0 * b_safe / a_safe)
    dmu_dc = np.where(
        np.abs(diff) <= 1e-10,
        0.0,
        common * (2.0 * b_safe / diff),
    )
    dmu_db = -common * (2.0 * np.log(u_safe))
    return mu, dmu_da, dmu_db, dmu_dc


def _forward_layer_activations(
    mu: np.ndarray,
    rule_grid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calcula `w` (N, R), `sum_w` (N,) e `h` (N, R) a partir de `mu` (N, n_in, M) e `rule_grid` (R, n_in)."""
    N, n_in, _ = mu.shape
    R = rule_grid.shape[0]
    # rule_mu: (N, R, n_in)
    rule_mu = np.empty((N, R, n_in), dtype=np.float64)
    for d in range(n_in):
        rule_mu[:, :, d] = mu[:, d, rule_grid[:, d]]
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
    mf_type: str = "gaussian",
    max_epochs: int = 30,
    learning_rate: float = 0.01,
    validation_split: float = 0.2,
    X_val: Any = None,
    y_val: Any = None,
    early_stopping_patience: int = 8,
    seed: int = 42,
    input_names: Sequence[str] | None = None,
    output_name: str = "y",
    rcond: float = 1e-10,
) -> Result:
    """Ajusta um aproximador Takagi-Sugeno de 1ª ordem via algoritmo ANFIS híbrido (Jang, 1993).

    - Passagem para frente (forward pass): estima parâmetros consequentes afins via QR/SVD (`_solve_consequents_qr_svd`).
    - Passagem para trás (backward pass): atualiza parâmetros de premissa (`gaussian` ou `bell`) por gradiente descendente.
    - Retorna `FuzzySystem` estático (`is_dynamic_model=False`, respeitando `ADR-006`).
    """
    try:
        X_arr = ensure_finite_float64(X, name="X")
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)
        elif X_arr.ndim != 2:
            raise DimensionMismatchError(f"X deve ser 1D ou 2D (N, n_inputs), recebido shape={X_arr.shape}.")

        y_arr = ensure_finite_float64(y, name="y")
        if y_arr.ndim == 2 and y_arr.shape[1] == 1:
            y_arr = y_arr.ravel()
        elif y_arr.ndim != 1:
            raise DimensionMismatchError(f"ANFIS suporta saída escalar 1D (N,), recebido shape={y_arr.shape}.")

        n_total, n_in = X_arr.shape
        if y_arr.size != n_total:
            raise DimensionMismatchError(
                message=f"Número de amostras em X ({n_total}) difere de y ({y_arr.size}).",
                parameters={"X_rows": n_total, "y_len": int(y_arr.size)},
            )
        if n_total < 4:
            raise ValidationError("fit_anfis requer pelo menos 4 amostras.")

        mf_kind = mf_type.strip().lower()
        if mf_kind in ("gauss", "gaussian", "gaussmf"):
            mf_kind = "gaussian"
        elif mf_kind in ("bell", "gbell", "gbellmf"):
            mf_kind = "bell"
        else:
            raise ValidationError(
                message=f"fit_anfis suporta mf_type 'gaussian' ou 'bell', recebido {mf_type!r}.",
                parameters={"mf_type": mf_type, "allowed": ["gaussian", "bell"]},
            )

        if isinstance(n_mfs, int) and not isinstance(n_mfs, bool):
            if n_mfs < 2 or n_mfs > 10:
                raise ValidationError("n_mfs deve estar entre 2 e 10.")
            mfs_per_input = [n_mfs] * n_in
        elif isinstance(n_mfs, Sequence) and not isinstance(n_mfs, (str, bytes)):
            if len(n_mfs) != n_in:
                raise DimensionMismatchError(f"n_mfs deve ter comprimento {n_in}, recebido {len(n_mfs)}.")
            mfs_per_input = [int(v) for v in n_mfs]
            if any(v < 2 or v > 10 for v in mfs_per_input):
                raise ValidationError("Cada entrada deve ter entre 2 e 10 funções de pertinência.")
        else:
            raise ValidationError("n_mfs deve ser inteiro ou sequência de inteiros.")

        if len(set(mfs_per_input)) != 1:
            raise ValidationError("fit_anfis requer o mesmo número de MFs por entrada na grade cartesiana.")
        M = mfs_per_input[0]

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

        # Partição treino / validação
        if X_val is not None and y_val is not None:
            X_tr = X_arr
            y_tr = y_arr
            X_va = ensure_finite_float64(X_val, name="X_val")
            if X_va.ndim == 1:
                X_va = X_va.reshape(-1, 1)
            y_va = ensure_finite_float64(y_val, name="y_val").ravel()
            if X_va.shape[1] != n_in or X_va.shape[0] != y_va.size:
                raise DimensionMismatchError("Dimensões de X_val e y_val incompatíveis.")
        elif validation_split > 0.0 and n_total >= 6:
            rng = np.random.default_rng(seed)
            perm = rng.permutation(n_total)
            n_val = max(1, int(round(n_total * validation_split)))
            n_train = n_total - n_val
            tr_idx = perm[:n_train]
            va_idx = perm[n_train:]
            X_tr, y_tr = X_arr[tr_idx], y_arr[tr_idx]
            X_va, y_va = X_arr[va_idx], y_arr[va_idx]
        else:
            X_tr, y_tr = X_arr, y_arr
            X_va, y_va = X_arr, y_arr

        # Inicializa centros e larguras uniformemente nos universos dos dados
        x_min = np.min(X_arr, axis=0)
        x_max = np.max(X_arr, axis=0)
        spans = np.maximum(x_max - x_min, 1e-3)

        centers = np.zeros((n_in, M), dtype=np.float64)
        sigmas = np.zeros((n_in, M), dtype=np.float64)
        bell_b = np.full((n_in, M), 2.0, dtype=np.float64)
        for d in range(n_in):
            centers[d, :] = np.linspace(x_min[d], x_max[d], M, dtype=np.float64)
            step = spans[d] / max(1, M - 1)
            sigmas[d, :] = max(step / 1.5, 1e-2)

        rule_tuples = list(itertools.product(range(M), repeat=n_in))
        rule_grid = np.array(rule_tuples, dtype=np.int64)  # (R, n_in)
        R = rule_grid.shape[0]
        p_per_rule = n_in + 1

        best_val_rmse = float("inf")
        best_theta: np.ndarray | None = None
        best_centers = centers.copy()
        best_sigmas = sigmas.copy()
        best_bell_b = bell_b.copy()
        best_epoch = 0
        best_rank = 0
        best_cond = 1.0
        best_solver = "qr"
        patience_counter = 0

        train_rmse_history: list[float] = []
        val_rmse_history: list[float] = []

        for epoch in range(max_epochs):
            # 1. Forward pass: avalia premissas e resolve consequentes por QR/SVD
            if mf_kind == "gaussian":
                mu_tr, dmu_dc, dmu_ds = _eval_premise_and_grads_gaussian(X_tr, centers, sigmas)
            else:
                mu_tr, dmu_da, dmu_db, dmu_dc = _eval_premise_and_grads_bell(X_tr, sigmas, bell_b, centers)

            w_tr, sum_w_tr, h_tr = _forward_layer_activations(mu_tr, rule_grid)
            Phi_tr = _build_regressor_matrix(X_tr, h_tr)
            theta, rank, cond, solver_used = _solve_consequents_qr_svd(Phi_tr, y_tr, rcond=rcond)

            y_hat_tr = Phi_tr @ theta
            tr_rmse, _ = _compute_rmse_and_fit(y_tr, y_hat_tr)
            train_rmse_history.append(tr_rmse)

            # Avalia na validação
            if mf_kind == "gaussian":
                mu_va, _, _ = _eval_premise_and_grads_gaussian(X_va, centers, sigmas)
            else:
                mu_va, _, _, _ = _eval_premise_and_grads_bell(X_va, sigmas, bell_b, centers)
            _, _, h_va = _forward_layer_activations(mu_va, rule_grid)
            Phi_va = _build_regressor_matrix(X_va, h_va)
            y_hat_va = Phi_va @ theta
            va_rmse, _ = _compute_rmse_and_fit(y_va, y_hat_va)
            val_rmse_history.append(va_rmse)

            if va_rmse < best_val_rmse - 1e-10:
                best_val_rmse = va_rmse
                best_theta = theta.copy()
                best_centers = centers.copy()
                best_sigmas = sigmas.copy()
                best_bell_b = bell_b.copy()
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

            theta_mat = theta.reshape(R, p_per_rule)  # (R, n_in + 1)
            X_aug_tr = np.hstack([X_tr, np.ones((X_tr.shape[0], 1), dtype=np.float64)])
            f_rules = X_aug_tr @ theta_mat.T  # (N, R): saída individual de cada regra r
            err_tr = y_hat_tr - y_tr  # (N,): dE/dy_hat para E = 1/(2N) sum (y_hat - y)^2
            safe_sw = np.where(sum_w_tr > _EPS, sum_w_tr, 1.0)
            # dy_hat / dw_r = (f_r - y_hat) / sum_w
            dy_dw = (f_rules - y_hat_tr[:, None]) / safe_sw[:, None]  # (N, R)
            dE_dw = (err_tr[:, None] / float(X_tr.shape[0])) * dy_dw  # (N, R)

            grad_c = np.zeros_like(centers)
            grad_s = np.zeros_like(sigmas)
            grad_b = np.zeros_like(bell_b)

            for d in range(n_in):
                for m_idx in range(M):
                    rules_with_dm = np.where(rule_grid[:, d] == m_idx)[0]
                    if rules_with_dm.size == 0:
                        continue
                    mu_dm = np.maximum(mu_tr[:, d, m_idx], _EPS)  # (N,)
                    # dw_r / dmu_{d,m} = w_r / mu_{d,m}
                    dw_dmu = np.sum(
                        dE_dw[:, rules_with_dm] * (w_tr[:, rules_with_dm] / mu_dm[:, None]),
                        axis=1,
                    )  # (N,)
                    grad_c[d, m_idx] = float(np.sum(dw_dmu * dmu_dc[:, d, m_idx]))
                    if mf_kind == "gaussian":
                        grad_s[d, m_idx] = float(np.sum(dw_dmu * dmu_ds[:, d, m_idx]))
                    else:
                        grad_s[d, m_idx] = float(np.sum(dw_dmu * dmu_da[:, d, m_idx]))
                        grad_b[d, m_idx] = float(np.sum(dw_dmu * dmu_db[:, d, m_idx]))

            # Normalização de passo por variável para estabilidade numérica
            for d in range(n_in):
                scale_d = spans[d]
                gc_norm = float(np.linalg.norm(grad_c[d, :]))
                gs_norm = float(np.linalg.norm(grad_s[d, :]))
                if gc_norm > _EPS:
                    centers[d, :] -= learning_rate * scale_d * (grad_c[d, :] / max(1.0, gc_norm))
                if gs_norm > _EPS:
                    sigmas[d, :] -= learning_rate * scale_d * (grad_s[d, :] / max(1.0, gs_norm))
                sigmas[d, :] = np.maximum(sigmas[d, :], 1e-3 * scale_d)
                if mf_kind == "bell":
                    gb_norm = float(np.linalg.norm(grad_b[d, :]))
                    if gb_norm > _EPS:
                        bell_b[d, :] -= 0.5 * learning_rate * (grad_b[d, :] / max(1.0, gb_norm))
                    bell_b[d, :] = np.clip(bell_b[d, :], 0.2, 20.0)

        assert best_theta is not None
        # Recalcula predições finais com os melhores parâmetros
        if mf_kind == "gaussian":
            mu_tr_f, _, _ = _eval_premise_and_grads_gaussian(X_tr, best_centers, best_sigmas)
            mu_va_f, _, _ = _eval_premise_and_grads_gaussian(X_va, best_centers, best_sigmas)
        else:
            mu_tr_f, _, _, _ = _eval_premise_and_grads_bell(X_tr, best_sigmas, best_bell_b, best_centers)
            mu_va_f, _, _, _ = _eval_premise_and_grads_bell(X_va, best_sigmas, best_bell_b, best_centers)

        _, _, h_tr_f = _forward_layer_activations(mu_tr_f, rule_grid)
        _, _, h_va_f = _forward_layer_activations(mu_va_f, rule_grid)
        y_pred_tr = _build_regressor_matrix(X_tr, h_tr_f) @ best_theta
        y_pred_va = _build_regressor_matrix(X_va, h_va_f) @ best_theta

        final_tr_rmse, final_tr_fit = _compute_rmse_and_fit(y_tr, y_pred_tr)
        final_va_rmse, final_va_fit = _compute_rmse_and_fit(y_va, y_pred_va)

        # Constrói FuzzySystem Takagi-Sugeno estático (is_dynamic_model=False conforme ADR-006)
        in_vars_spec: list[dict[str, Any]] = []
        for d in range(n_in):
            margin = 0.05 * spans[d]
            univ = [float(x_min[d] - margin), float(x_max[d] + margin)]
            terms_d: list[dict[str, Any]] = []
            for m_idx in range(M):
                tname = f"{in_names[d]}_mf{m_idx + 1}"
                if mf_kind == "gaussian":
                    terms_d.append(
                        {
                            "name": tname,
                            "mf": "gaussian",
                            "params": [float(best_centers[d, m_idx]), float(best_sigmas[d, m_idx])],
                        }
                    )
                else:
                    terms_d.append(
                        {
                            "name": tname,
                            "mf": "bell",
                            "params": [
                                float(best_sigmas[d, m_idx]),
                                float(best_bell_b[d, m_idx]),
                                float(best_centers[d, m_idx]),
                            ],
                        }
                    )
            in_vars_spec.append({"name": in_names[d], "universe": univ, "terms": terms_d})

        y_min, y_max = float(np.min(y_arr)), float(np.max(y_arr))
        y_span = max(y_max - y_min, 1.0)
        out_univ = [y_min - 0.1 * y_span, y_max + 0.1 * y_span]

        theta_rules = best_theta.reshape(R, p_per_rule)
        out_terms_spec: list[dict[str, Any]] = []
        rules_spec: list[dict[str, Any]] = []

        for r_idx in range(R):
            tname_out = f"rule_{r_idx + 1}_consequent"
            coeffs = [float(v) for v in theta_rules[r_idx, :].tolist()]
            out_terms_spec.append(
                {
                    "name": tname_out,
                    "type": "linear",
                    "params": coeffs,
                    "coefficients": coeffs,
                    "bias_last": True,
                }
            )
            ants = {
                in_names[d]: f"{in_names[d]}_mf{int(rule_grid[r_idx, d]) + 1}"
                for d in range(n_in)
            }
            rules_spec.append(
                {
                    "name": f"R{r_idx + 1}",
                    "connector": "and",
                    "antecedents": ants,
                    "consequents": {output_name: tname_out},
                    "weight": 1.0,
                }
            )

        out_vars_spec = [{"name": output_name, "universe": out_univ, "terms": out_terms_spec}]

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
        n_total_params = R * p_per_rule + n_in * M * (2 if mf_kind == "gaussian" else 3)
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
        if overfit_detected or X_tr.shape[0] < n_total_params:
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

        return Result(
            status="warning" if warnings_list else "success",
            data={
                "fuzzy_system": anfis_system.to_dict(),
                "system_id": anfis_system.id,
                "metrics": {
                    "train_rmse": final_tr_rmse,
                    "val_rmse": final_va_rmse,
                    "train_fit_percent": final_tr_fit,
                    "val_fit_percent": final_va_fit,
                },
                "training_history": {
                    "train_rmse": train_rmse_history,
                    "val_rmse": val_rmse_history,
                    "best_epoch": best_epoch,
                    "epochs_executed": len(train_rmse_history),
                },
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
