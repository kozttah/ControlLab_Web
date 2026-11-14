"""Estimação de modelos ARX (AutoRegressive with eXogenous input) por fatoração QR/SVD e seleção de ordem.

Escopo normativo (CL-DIR-001 Seção 5.1, Seção 5.2, Seção 10.2, Seção 10.4, Seção 13.6 e Apêndice C):
- Estimação linear na estrutura ARX $(n_a, n_b, n_k)$ para sistemas SISO e MISO/MIMO;
- Solução numérica via fatoração QR com pivotamento de colunas (`scipy.linalg.qr(..., pivoting=True)`)
  e SVD (`scipy.linalg.svd`) para mínimo-norma em casos rank-deficient — jamais formando $(\\Phi^T \\Phi)^{-1}$
  por inversão matricial explícita (`np.linalg.inv` proibido);
- Verificação rigorosa de posto numérico (`rank`), número de condição $\\kappa(\\Phi)$ e Persistência de Excitação (PE)
  do sinal de entrada (emitindo `PERSISTENCE_OF_EXCITATION_INSUFFICIENT` / `RANK_DEFICIENT_REGRESSION` em `T-ID-02`);
- Cálculo da matriz de covariância assintótica dos parâmetros $\\hat{P}_\\theta = \\hat{\\sigma}_e^2 (\\Phi^T \\Phi)^{-1}$
  via triangular superior $R$ da fatoração QR quando posto completo;
- Cálculo de previsões de 1 passo e simulações livres tanto no conjunto de treino quanto no conjunto de validação (`holdout`).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Sequence

import numpy as np
import scipy.linalg

from control_lab.core.models import Dataset, IdentifiedModel, TransferFunction
from control_lab.core.tensors import array_to_tensor, complex_to_pair, tensor_to_array
from control_lab.diagnostics import (
    DimensionMismatchError,
    HypothesisViolatedError,
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .preprocessing import (
    DEFAULT_COND_WARN_THRESHOLD,
    DEFAULT_RANK_RTOL,
    check_persistence_of_excitation,
    handle_id_failure,
    resolve_dataset_inputs,
)
from .validation import (
    analyze_residuals,
    compute_fit_percent,
    compute_information_criteria,
    predict,
    simulate,
)


def _normalize_per_input_int(val: int | Sequence[int], n_inputs: int, *, name: str, min_val: int) -> list[int]:
    if isinstance(val, bool):
        raise ValidationError(f"{name} deve ser inteiro ou sequência de inteiros, recebido bool.")
    if isinstance(val, (int, np.integer)):
        iv = int(val)
        if iv < min_val:
            raise ValidationError(f"{name} deve ser >= {min_val}, recebido {iv}.")
        return [iv] * n_inputs
    if isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
        if len(val) != n_inputs:
            raise DimensionMismatchError(
                message=f"Comprimento de {name} ({len(val)}) incompatível com número de entradas ({n_inputs}).",
                parameters={name: list(val), "n_inputs": n_inputs},
            )
        out: list[int] = []
        for idx, item in enumerate(val):
            if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
                raise ValidationError(f"{name}[{idx}] deve ser inteiro.")
            iv = int(item)
            if iv < min_val:
                raise ValidationError(f"{name}[{idx}] deve ser >= {min_val}, recebido {iv}.")
            out.append(iv)
        return out
    raise ValidationError(f"{name} deve ser inteiro ou lista de inteiros.")


def _solve_qr_svd_least_squares(
    Phi: np.ndarray,
    y_target: np.ndarray,
    *,
    rank_rtol: float = DEFAULT_RANK_RTOL,
) -> dict[str, Any]:
    """Resolve $\\min_\\theta \\|\\Phi \\theta - y\\|_2$ via QR com pivotamento e SVD, sem `inv` explícita."""
    n_eff, d = Phi.shape
    if d == 0:
        return {
            "theta": np.zeros(0, dtype=np.float64),
            "rank": 0,
            "expected_rank": 0,
            "rank_deficient": False,
            "condition": 1.0,
            "singular_values": np.zeros(0, dtype=np.float64),
            "R_factor": np.zeros((0, 0), dtype=np.float64),
            "pivots": np.zeros(0, dtype=int),
            "unscaled_cov": None,
        }

    # Decomposição SVD para valores singulares exatos, posto numérico e número de condição
    U_svd, svals, Vt_svd = scipy.linalg.svd(Phi, full_matrices=False)
    s_max = float(svals[0]) if svals.size > 0 else 0.0
    s_min = float(svals[-1]) if svals.size > 0 else 0.0
    cutoff = max(float(rank_rtol) * s_max, 1e-14)
    rank = int(np.sum(svals > cutoff))
    rank_deficient = rank < d
    cond = float(s_max / s_min) if (not rank_deficient and s_min > 1e-15 * max(1.0, s_max)) else 1e16

    # Fatoração QR econômica com pivotamento de colunas: Phi[:, piv] = Q @ R
    Q_qr, R_qr, piv = scipy.linalg.qr(Phi, mode="economic", pivoting=True)

    if not rank_deficient:
        # Solução triangular superior R @ theta_piv = Q^T @ y
        rhs = Q_qr.T @ y_target
        theta_piv = scipy.linalg.solve_triangular(R_qr[:d, :d], rhs[:d], lower=False)
        theta = np.empty(d, dtype=np.float64)
        theta[piv] = theta_piv

        # Covariância não escalada (Phi^T Phi)^{-1}: resolve R @ X = I por substituição triangular
        # Pois Phi[:, piv]^T Phi[:, piv] = R^T R => (R^T R)^{-1} = R^{-1} R^{-T}
        R_inv = scipy.linalg.solve_triangular(R_qr[:d, :d], np.eye(d, dtype=np.float64), lower=False)
        cov_piv = R_inv @ R_inv.T
        unscaled_cov = np.empty((d, d), dtype=np.float64)
        unscaled_cov[np.ix_(piv, piv)] = 0.5 * (cov_piv + cov_piv.T)
    else:
        # Solução de norma mínima no subespaço de valores singulares significativos (SVD truncada)
        if rank == 0:
            theta = np.zeros(d, dtype=np.float64)
        else:
            U_r = U_svd[:, :rank]
            s_r = svals[:rank]
            Vt_r = Vt_svd[:rank, :]
            theta = Vt_r.T @ ((U_r.T @ y_target) / s_r)
        unscaled_cov = None

    return {
        "theta": theta,
        "rank": rank,
        "expected_rank": d,
        "rank_deficient": rank_deficient,
        "condition": cond,
        "singular_values": svals,
        "R_factor": R_qr,
        "pivots": piv,
        "unscaled_cov": unscaled_cov,
    }


def _build_arx_regressor_matrix(
    y_col: np.ndarray,
    u_mat: np.ndarray,
    *,
    na: int,
    nb_list: list[int],
    nk_list: list[int],
) -> tuple[np.ndarray, np.ndarray, int]:
    """Constrói matriz de regressores $\\Phi \\in \\mathbb{R}^{N_{\\text{eff}} \\times d}$ e vetor alvo $Y$."""
    n_samples, n_inputs = u_mat.shape
    max_lag_u = max((nk_list[j] + nb_list[j] - 1 for j in range(n_inputs) if nb_list[j] > 0), default=0)
    max_lag = max(na, max_lag_u)
    n_eff = n_samples - max_lag
    d = na + sum(nb_list)

    if n_eff < max(1, d):
        raise ValidationError(
            message=(
                f"Número de amostras ({n_samples}) insuficiente para estimar ARX(na={na}, nb={nb_list}, nk={nk_list}): "
                f"amostras efetivas={n_eff}, número de parâmetros={d}."
            ),
            parameters={"n_samples": n_samples, "max_lag": max_lag, "n_effective": n_eff, "n_parameters": d},
        )

    cols: list[np.ndarray] = []
    # Colunas autorregressivas: -y(k-1), ..., -y(k-na)
    for r in range(1, na + 1):
        cols.append(-y_col[max_lag - r : n_samples - r])

    # Colunas exógenas por canal j: u_j(k - nk_j), ..., u_j(k - nk_j - nb_j + 1)
    for j in range(n_inputs):
        nk_j = nk_list[j]
        nb_j = nb_list[j]
        for s in range(nb_j):
            lag = nk_j + s
            cols.append(u_mat[max_lag - lag : n_samples - lag, j])

    Phi = np.column_stack(cols) if cols else np.zeros((n_eff, 0), dtype=np.float64)
    y_target = y_col[max_lag:n_samples].copy()
    return Phi, y_target, max_lag


def fit_arx(
    dataset_or_u: Any = None,
    y: Any = None,
    *,
    na: int = 2,
    nb: int | Sequence[int] = 2,
    nk: int | Sequence[int] = 1,
    dataset: Dataset | Mapping[str, Any] | None = None,
    val_dataset: Dataset | Mapping[str, Any] | None = None,
    u: Any = None,
    t: Any = None,
    dt: float | None = None,
    detrend: str = "none",
    rank_rtol: float = DEFAULT_RANK_RTOL,
    cond_warn_threshold: float = DEFAULT_COND_WARN_THRESHOLD,
    max_lag_residuals: int = 20,
    allow_irregular_sampling: bool = False,
    seed: int | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Estima modelo ARX discreto $A(q^{-1}) y(k) = B(q^{-1}) u(k - n_k) + e(k)$ via fatoração QR/SVD.

    Problema matemático
    -------------------
    Para cada canal de saída $i \\in \\{1, \\dots, p\\}$:
    $$y_i(k) + a_{i,1} y_i(k-1) + \\dots + a_{i,n_a} y_i(k-n_a) = \\sum_{j=1}^m \\sum_{s=0}^{n_{b,j}-1} b_{i,j,s+1} u_j(k - n_{k,j} - s) + e_i(k)$$
    O preditor linear de 1 passo é $\\hat{y}_i(k|k-1) = \\varphi_i^T(k) \\theta_i$, e $\\hat{\\theta}_i$
    minimiza $\\|\\Phi_i \\theta_i - Y_i\\|_2^2$ via decomposição QR com pivotamento / SVD.

    Hipóteses e diagnósticos
    ------------------------
    - Verifica amostragem uniforme (salvo `allow_irregular_sampling=True`), Persistência de Excitação (PE) da
      entrada $u(k)$ de ordem $n_a + \\max(n_b)$, posto completo de $\\Phi$ e número de condição $\\kappa(\\Phi)$.
    - Se a entrada for constante ou colinear (`T-ID-02`), marca `rank_deficient=True` e emite aviso estruturado
      `PERSISTENCE_OF_EXCITATION_INSUFFICIENT` e/ou `RANK_DEFICIENT_REGRESSION` com `status="warning"`.
    """
    prov: Provenance = build_provenance(
        "identification.fit_arx",
        seed=seed,
        tolerances={"rank_rtol": float(rank_rtol), "cond_warn_threshold": float(cond_warn_threshold)},
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if isinstance(na, bool) or not isinstance(na, (int, np.integer)) or int(na) < 0:
            raise ValidationError(f"na deve ser inteiro >= 0, recebido {na!r}.")
        na_int = int(na)

        ds_train = resolve_dataset_inputs(
            dataset_or_u,
            y,
            t,
            dataset=dataset,
            u=u,
            dt=dt,
            require_uniform=not allow_irregular_sampling,
            allow_irregular_sampling=allow_irregular_sampling,
        )
        warnings_out.extend(ds_train.warnings)
        resolved_dt = float(ds_train.dt if ds_train.dt is not None else (dt if dt is not None else 1.0))

        m = ds_train.n_inputs
        p = ds_train.n_outputs
        nb_list = _normalize_per_input_int(nb, m, name="nb", min_val=1)
        nk_list = _normalize_per_input_int(nk, m, name="nk", min_val=0)

        if na_int == 0 and sum(nb_list) == 0:
            raise ValidationError("Ordem total do modelo ARX (na + sum(nb)) deve ser >= 1.")

        if not isinstance(detrend, str) or detrend.lower() not in ("none", "mean", "constant", "linear"):
            raise ValidationError(f"detrend inválido: {detrend!r}. Use 'none', 'mean' ou 'linear'.")
        detrend_mode = detrend.lower()

        u_work = ds_train.u.copy()
        y_work = ds_train.y.copy()
        u_offset = np.zeros(m, dtype=np.float64)
        y_offset = np.zeros(p, dtype=np.float64)
        if detrend_mode in ("mean", "constant"):
            u_offset = np.mean(u_work, axis=0)
            y_offset = np.mean(y_work, axis=0)
            u_work = u_work - u_offset
            y_work = y_work - y_offset

        # 1. Diagnóstico de Persistência de Excitação (PE) na entrada u
        pe_order = max(1, na_int + max(nb_list))
        if ds_train.n_samples >= pe_order + m * pe_order:
            pe_res = check_persistence_of_excitation(
                u_work,
                order=pe_order,
                rank_rtol=rank_rtol,
                cond_warn_threshold=cond_warn_threshold,
            )
            pe_diag = pe_res.diagnostics
            pe_satisfied = bool(pe_res.assumptions.get("pe_satisfied", False))
            warnings_out.extend(pe_res.warnings)
        else:
            u_std = np.std(u_work, axis=0)
            any_const = bool(np.any(u_std <= 1e-14 * np.maximum(1.0, np.max(np.abs(u_work), axis=0))))
            pe_satisfied = not any_const
            pe_diag = {
                "order": pe_order,
                "pe_satisfied": pe_satisfied,
                "any_constant_channel": any_const,
            }
            if any_const:
                warnings_out.append(
                    WarningItem(
                        code="PERSISTENCE_OF_EXCITATION_INSUFFICIENT",
                        message="Entrada constante detectada: persistência de excitação insuficiente.",
                        details=pe_diag,
                    )
                )

        # 2. Estimação QR/SVD para cada canal de saída
        a_coeffs_all: list[list[float]] = []
        b_coeffs_all: list[list[list[float]]] = []
        b_full_all: list[list[list[float]]] = []
        cov_matrices: list[np.ndarray | None] = []
        channel_ls_diags: list[dict[str, Any]] = []
        overall_rank_deficient = not pe_satisfied
        max_cond = float(pe_diag.get("condition_raw", 1.0))

        # Polinômios para construir TransferFunction discreta em z (descending)
        num_z_grid: list[list[np.ndarray]] = []
        den_z_grid: list[list[np.ndarray]] = []

        for i in range(p):
            Phi_i, y_target_i, max_lag = _build_arx_regressor_matrix(
                y_work[:, i],
                u_work,
                na=na_int,
                nb_list=nb_list,
                nk_list=nk_list,
            )
            ls_i = _solve_qr_svd_least_squares(Phi_i, y_target_i, rank_rtol=rank_rtol)
            theta_i: np.ndarray = ls_i["theta"]
            rank_i: int = ls_i["rank"]
            d_i: int = ls_i["expected_rank"]
            rdef_i: bool = ls_i["rank_deficient"]
            cond_i: float = ls_i["condition"]
            svals_i: np.ndarray = ls_i["singular_values"]

            if rdef_i:
                overall_rank_deficient = True
                warnings_out.append(
                    WarningItem(
                        code="RANK_DEFICIENT_REGRESSION",
                        message=(
                            f"Matriz de regressores ARX deficiente de posto no canal de saída {i}: "
                            f"rank={rank_i}/{d_i} (cond={cond_i:.3e})."
                        ),
                        details={
                            "output_channel": i,
                            "rank": rank_i,
                            "expected_rank": d_i,
                            "condition": cond_i,
                        },
                    )
                )
            elif cond_i > cond_warn_threshold:
                warnings_out.append(
                    WarningItem(
                        code="ILL_CONDITIONED_REGRESSION",
                        message=(
                            f"Matriz de regressores ARX mal condicionada no canal {i}: cond={cond_i:.3e}."
                        ),
                        details={"output_channel": i, "condition": cond_i},
                    )
                )

            max_cond = max(max_cond, cond_i)

            # Separa coeficientes a_1..a_na e b_{j, 1}..b_{j, nb_j}
            a_i = [float(v) for v in theta_i[:na_int].tolist()]
            a_coeffs_all.append(a_i)

            offset = na_int
            row_b: list[list[float]] = []
            row_b_full: list[list[float]] = []
            for j in range(m):
                nb_j = nb_list[j]
                nk_j = nk_list[j]
                b_ij = [float(v) for v in theta_i[offset : offset + nb_j].tolist()]
                offset += nb_j
                row_b.append(b_ij)
                # Polinômio em z^-1 com zeros iniciais de atraso nk_j: [0, ..., 0, b_1, ..., b_nb]
                b_full_ij = ([0.0] * nk_j) + b_ij
                row_b_full.append(b_full_ij)
            b_coeffs_all.append(row_b)
            b_full_all.append(row_b_full)

            # Resíduos de 1 passo na janela efetiva e variância estimada sigma_e^2
            res_i = y_target_i - (Phi_i @ theta_i)
            n_eff_i = Phi_i.shape[0]
            dof_i = max(1, n_eff_i - d_i)
            sigma2_i = float(np.dot(res_i, res_i) / dof_i)

            if ls_i["unscaled_cov"] is not None and not overall_rank_deficient:
                cov_i = sigma2_i * ls_i["unscaled_cov"]
                cov_matrices.append(cov_i)
            else:
                cov_matrices.append(None)

            channel_ls_diags.append(
                {
                    "output_channel": i,
                    "rank": rank_i,
                    "expected_rank": d_i,
                    "rank_deficient": bool(rdef_i or not pe_satisfied),
                    "condition": float(cond_i),
                    "singular_values": [float(v) for v in svals_i.tolist()],
                    "noise_variance_estimate": sigma2_i,
                    "n_effective_samples": n_eff_i,
                }
            )

            # Conversão exata para polinômios descendentes em z:
            # A(z^-1) = 1 + a1 z^-1 + ... + ana z^-na
            # B_j(z^-1) = b_full[0] + b_full[1] z^-1 + ... + b_full[L] z^-L
            # Multiplicando numerador e denominador por z^N_deg onde N_deg = max(na, L):
            a_asc = np.array([1.0] + a_i, dtype=np.float64)
            row_num_z: list[np.ndarray] = []
            row_den_z: list[np.ndarray] = []
            for j in range(m):
                b_asc = np.array(row_b_full[j], dtype=np.float64)
                deg_ij = max(a_asc.size - 1, b_asc.size - 1)
                den_z = np.zeros(deg_ij + 1, dtype=np.float64)
                num_z = np.zeros(deg_ij + 1, dtype=np.float64)
                den_z[: a_asc.size] = a_asc
                num_z[: b_asc.size] = b_asc
                num_trim = np.trim_zeros(num_z, "f")
                if num_trim.size == 0:
                    num_trim = np.array([0.0], dtype=np.float64)
                row_num_z.append(num_trim)
                row_den_z.append(den_z)
            num_z_grid.append(row_num_z)
            den_z_grid.append(row_den_z)

        model_structure = {
            "family": "ARX",
            "na": na_int,
            "nb": nb_list[0] if m == 1 else nb_list,
            "nk": nk_list[0] if m == 1 else nk_list,
            "nb_per_input": nb_list,
            "nk_per_input": nk_list,
            "n_inputs": m,
            "n_outputs": p,
            "a_coeffs": a_coeffs_all,
            "b_coeffs": b_coeffs_all,
            "b_full_coeffs": b_full_all,
            "dt": resolved_dt,
            "detrend_mode": detrend_mode,
            "u_offset": [float(v) for v in u_offset.tolist()],
            "y_offset": [float(v) for v in y_offset.tolist()],
        }

        tf_prov = build_provenance(
            "identification.fit_arx",
            seed=seed,
            tolerances={"rank_rtol": float(rank_rtol), "cond_warn_threshold": float(cond_warn_threshold)},
            model_revision=ds_train.revision,
            model_structure=model_structure,
        )
        tf_model = TransferFunction(
            num=num_z_grid,
            den=den_z_grid,
            dt=resolved_dt,
            variable="z",
            poly_order="descending",
            input_names=ds_train.input_names,
            output_names=ds_train.output_names,
            units=ds_train.units,
            provenance=tf_prov.to_dict(),
        )
        warnings_out.extend(tf_model.warnings)

        # 3. Avaliação no conjunto de treino (1-step prediction e free simulation)
        y_pred_tr, max_lag_tr = _run_arx_eval_with_offset(
            model_structure, ds_train.u, ds_train.y, mode="one_step_prediction"
        )
        y_sim_tr, _ = _run_arx_eval_with_offset(
            model_structure, ds_train.u, ds_train.y, mode="free_simulation"
        )
        tr_slice = slice(max_lag_tr, ds_train.n_samples)
        fit_pred_tr = compute_fit_percent(ds_train.y[tr_slice], y_pred_tr[tr_slice])
        fit_sim_tr = compute_fit_percent(ds_train.y[tr_slice], y_sim_tr[tr_slice])
        residuals_tr = ds_train.y[tr_slice] - y_pred_tr[tr_slice]

        n_params_total = p * (na_int + sum(nb_list))
        info_criteria = compute_information_criteria(residuals_tr, n_params_total)
        resid_diag_tr = analyze_residuals(
            residuals_tr,
            ds_train.u[tr_slice],
            max_lag=min(max_lag_residuals, max(1, residuals_tr.shape[0] - 1)),
        )

        metrics_dict: dict[str, Any] = {
            "train": {
                "partition": "train",
                "n_samples": ds_train.n_samples,
                "n_effective_samples": int(residuals_tr.shape[0]),
                "one_step_prediction": {
                    "evaluation_mode": "one_step_prediction",
                    "fit_percent": fit_pred_tr["fit_percent"],
                    "fit_per_channel": fit_pred_tr["fit_per_channel"],
                    "rmse": fit_pred_tr["rmse"],
                },
                "free_simulation": {
                    "evaluation_mode": "free_simulation",
                    "fit_percent": fit_sim_tr["fit_percent"],
                    "fit_per_channel": fit_sim_tr["fit_per_channel"],
                    "rmse": fit_sim_tr["rmse"],
                },
            },
            "information_criteria": info_criteria,
        }
        resid_dict: dict[str, Any] = {"train": resid_diag_tr}
        partitions_dict: dict[str, Any] = {
            "train_dataset_id": ds_train.id,
            "train_n_samples": ds_train.n_samples,
        }

        # 4. Se val_dataset (holdout) foi fornecido, avalia também separadamente em validação
        y_pred_val: np.ndarray | None = None
        y_sim_val: np.ndarray | None = None
        if val_dataset is not None:
            ds_val = resolve_dataset_inputs(
                val_dataset,
                dt=resolved_dt,
                require_uniform=not allow_irregular_sampling,
                allow_irregular_sampling=allow_irregular_sampling,
            )
            if ds_val.id == ds_train.id and np.array_equal(ds_val.t, ds_train.t):
                raise HypothesisViolatedError(
                    "Contaminação detectada em fit_arx: val_dataset é idêntico ao dataset de treino."
                )
            y_pred_val, mlag_v = _run_arx_eval_with_offset(
                model_structure, ds_val.u, ds_val.y, mode="one_step_prediction"
            )
            y_sim_val, _ = _run_arx_eval_with_offset(
                model_structure, ds_val.u, ds_val.y, mode="free_simulation"
            )
            v_slice = slice(mlag_v, ds_val.n_samples)
            fit_pred_val = compute_fit_percent(ds_val.y[v_slice], y_pred_val[v_slice])
            fit_sim_val = compute_fit_percent(ds_val.y[v_slice], y_sim_val[v_slice])
            res_val = ds_val.y[v_slice] - y_pred_val[v_slice]
            resid_diag_val = analyze_residuals(
                res_val,
                ds_val.u[v_slice],
                max_lag=min(max_lag_residuals, max(1, res_val.shape[0] - 1)),
            )
            metrics_dict["validation"] = {
                "partition": "validation",
                "n_samples": ds_val.n_samples,
                "n_effective_samples": int(res_val.shape[0]),
                "one_step_prediction": {
                    "evaluation_mode": "one_step_prediction",
                    "fit_percent": fit_pred_val["fit_percent"],
                    "fit_per_channel": fit_pred_val["fit_per_channel"],
                    "rmse": fit_pred_val["rmse"],
                },
                "free_simulation": {
                    "evaluation_mode": "free_simulation",
                    "fit_percent": fit_sim_val["fit_percent"],
                    "fit_per_channel": fit_sim_val["fit_per_channel"],
                    "rmse": fit_sim_val["rmse"],
                },
            }
            resid_dict["validation"] = resid_diag_val
            partitions_dict["validation_dataset_id"] = ds_val.id
            partitions_dict["validation_n_samples"] = ds_val.n_samples

        # Polos estimados de A(z)
        if na_int > 0:
            poles_list = [np.roots(np.array([1.0] + a_coeffs_all[i], dtype=np.float64)) for i in range(p)]
            poles_arr = np.concatenate(poles_list)
            order_idx = np.lexsort((np.imag(poles_arr), np.real(poles_arr)))
            poles_sorted = poles_arr[order_idx]
            spec_radius = float(np.max(np.abs(poles_sorted)))
        else:
            poles_sorted = np.array([], dtype=np.complex128)
            spec_radius = 0.0

        is_stable = bool(spec_radius < 1.0 - 1e-12)
        if not is_stable:
            warnings_out.append(
                WarningItem(
                    code="UNSTABLE_IDENTIFIED_MODEL",
                    message=f"Modelo ARX estimado possui raio espectral >= 1 ({spec_radius:.6f}).",
                    details={"spectral_radius": spec_radius},
                )
            )

        excitation_diag = {
            "pe_diagnostics": pe_diag,
            "regression_channels": channel_ls_diags,
            "rank_deficient": bool(overall_rank_deficient),
            "condition": float(max_cond),
        }
        noise_hyp = {
            "structure": "ARX",
            "equation_error_white_noise": True,
            "noise_transfer_function": "1 / A(q^-1)",
            "delay_convention": "y(k) + a_1 y(k-1) + ... = b_1 u(k - nk) + ...",
        }

        cov_primary = cov_matrices[0] if (p == 1 and cov_matrices[0] is not None) else None

        id_model = IdentifiedModel(
            model=tf_model,
            algorithm="ARX_QR_SVD",
            dataset_ref={"id": ds_train.id, "revision": ds_train.revision},
            partitions=partitions_dict,
            metrics=metrics_dict,
            noise_hypothesis=noise_hyp,
            excitation_diagnostics=excitation_diag,
            covariance=cov_primary,
            residual_diagnostics=resid_dict,
            provenance=tf_prov,
        )

        assumptions = {
            "uniform_sampling": ds_train.is_uniform_sampling,
            "pe_satisfied": bool(pe_satisfied),
            "full_rank_regressor": bool(not overall_rank_deficient),
            "predictor_stable": is_stable,
            "noise_structure": "ARX",
        }
        diagnostics = {
            "rank": channel_ls_diags[0]["rank"] if p == 1 else [c["rank"] for c in channel_ls_diags],
            "expected_rank": (
                channel_ls_diags[0]["expected_rank"] if p == 1 else [c["expected_rank"] for c in channel_ls_diags]
            ),
            "rank_deficient": bool(overall_rank_deficient),
            "condition": float(max_cond),
            "singular_values": (
                channel_ls_diags[0]["singular_values"]
                if p == 1
                else [c["singular_values"] for c in channel_ls_diags]
            ),
            "spectral_radius": spec_radius,
            "is_stable": is_stable,
            "fit_train_one_step": fit_pred_tr["fit_percent"],
            "fit_train_free_sim": fit_sim_tr["fit_percent"],
            "rmse_train_one_step": fit_pred_tr["rmse"],
            "rmse_train_free_sim": fit_sim_tr["rmse"],
            "aic": info_criteria["aic"],
            "bic": info_criteria["bic"],
            "fpe": info_criteria["fpe"],
        }
        if "validation" in metrics_dict:
            diagnostics["fit_val_one_step"] = metrics_dict["validation"]["one_step_prediction"]["fit_percent"]
            diagnostics["fit_val_free_sim"] = metrics_dict["validation"]["free_simulation"]["fit_percent"]

        data: dict[str, Any] = {
            "identified_model": id_model.to_dict(),
            "transfer_function": tf_model.to_dict(),
            "parameters": {
                "na": na_int,
                "nb": nb_list[0] if m == 1 else nb_list,
                "nk": nk_list[0] if m == 1 else nk_list,
                "a": a_coeffs_all[0] if p == 1 else a_coeffs_all,
                "b": (
                    b_coeffs_all[0][0]
                    if (p == 1 and m == 1)
                    else (b_coeffs_all[0] if p == 1 else b_coeffs_all)
                ),
                "theta": (
                    array_to_tensor(np.array(a_coeffs_all[0] + b_coeffs_all[0][0], dtype=np.float64))
                    if (p == 1 and m == 1)
                    else None
                ),
            },
            "poles": complex_to_pair(poles_sorted),
            "metrics": metrics_dict,
            "y_hat_train_one_step": array_to_tensor(y_pred_tr, dtype="float64", order="C"),
            "y_hat_train_free_sim": array_to_tensor(y_sim_tr, dtype="float64", order="C"),
            "residuals_train": array_to_tensor(residuals_tr, dtype="float64", order="C"),
        }
        if cov_primary is not None:
            data["covariance"] = array_to_tensor(cov_primary, dtype="float64", order="C")
        if y_pred_val is not None and y_sim_val is not None:
            data["y_hat_val_one_step"] = array_to_tensor(y_pred_val, dtype="float64", order="C")
            data["y_hat_val_free_sim"] = array_to_tensor(y_sim_val, dtype="float64", order="C")

        status = "warning" if warnings_out else "success"
        return Result(
            status=status,
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=tf_prov,
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


def _run_arx_eval_with_offset(
    struct: Mapping[str, Any],
    u_raw: np.ndarray,
    y_raw: np.ndarray,
    *,
    mode: str,
) -> tuple[np.ndarray, int]:
    u_off = np.asarray(struct.get("u_offset", np.zeros(u_raw.shape[1])), dtype=np.float64)
    y_off = np.asarray(struct.get("y_offset", np.zeros(y_raw.shape[1])), dtype=np.float64)
    u_centered = u_raw - u_off
    y_centered = y_raw - y_off
    from .validation import _run_arx_or_oe_recurrence

    yh_cent, max_lag = _run_arx_or_oe_recurrence(struct, u_centered, y_centered, mode=mode)
    return yh_cent + y_off, max_lag


def select_arx_order(
    train_dataset: Dataset | Mapping[str, Any],
    val_dataset: Dataset | Mapping[str, Any] | None = None,
    *,
    na_range: Sequence[int] = (1, 2, 3, 4),
    nb_range: Sequence[int] = (1, 2, 3, 4),
    nk_range: Sequence[int] = (1,),
    criterion: str = "bic",
    raise_on_error: bool = False,
) -> Result:
    """Seleciona estrutura ARX $(n_a, n_b, n_k)$ comparando AIC, BIC, FPE e FIT em holdout."""
    prov = build_provenance("identification.select_arx_order")
    assumptions: dict[str, Any] = {"criterion": criterion.lower()}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        crit = criterion.lower()
        if crit not in ("aic", "bic", "fpe", "val_free_sim_fit", "val_one_step_fit"):
            raise ValidationError(
                f"Critério de seleção de ordem inválido: {criterion!r}. "
                "Use 'aic', 'bic', 'fpe', 'val_free_sim_fit' ou 'val_one_step_fit'."
            )
        if crit.startswith("val_") and val_dataset is None:
            raise ValidationError(f"Critério {crit!r} exige fornecimento de val_dataset.")

        candidates: list[dict[str, Any]] = []
        best_res: Result | None = None
        best_score: float | None = None

        for na_c in na_range:
            for nb_c in nb_range:
                for nk_c in nk_range:
                    res_c = fit_arx(
                        dataset=train_dataset,
                        val_dataset=val_dataset,
                        na=int(na_c),
                        nb=int(nb_c),
                        nk=int(nk_c),
                        raise_on_error=False,
                    )
                    if res_c.status == "failure" or res_c.data is None:
                        continue
                    ic = res_c.data["metrics"]["information_criteria"]
                    entry: dict[str, Any] = {
                        "na": int(na_c),
                        "nb": int(nb_c),
                        "nk": int(nk_c),
                        "aic": ic["aic"],
                        "bic": ic["bic"],
                        "fpe": ic["fpe"],
                        "fit_train_one_step": res_c.diagnostics["fit_train_one_step"],
                        "fit_train_free_sim": res_c.diagnostics["fit_train_free_sim"],
                        "rank_deficient": res_c.diagnostics["rank_deficient"],
                    }
                    if "validation" in res_c.data["metrics"]:
                        val_m = res_c.data["metrics"]["validation"]
                        entry["fit_val_one_step"] = val_m["one_step_prediction"]["fit_percent"]
                        entry["fit_val_free_sim"] = val_m["free_simulation"]["fit_percent"]

                    candidates.append(entry)

                    if crit in ("aic", "bic", "fpe"):
                        val_s = entry.get(crit)
                        if val_s is None:
                            continue
                        score = -float(val_s)  # menor AIC/BIC/FPE é melhor
                    elif crit == "val_free_sim_fit":
                        val_s = entry.get("fit_val_free_sim")
                        if val_s is None:
                            continue
                        score = float(val_s)
                    else:
                        val_s = entry.get("fit_val_one_step")
                        if val_s is None:
                            continue
                        score = float(val_s)

                    if best_score is None or score > best_score:
                        best_score = score
                        best_res = res_c

        if best_res is None or best_res.data is None:
            raise ValidationError("Nenhuma ordem candidata de ARX pôde ser estimada com sucesso.")

        diagnostics = {
            "n_candidates_evaluated": len(candidates),
            "selected_parameters": best_res.data["parameters"],
            "criterion": crit,
        }
        return Result(
            status=best_res.status,
            data={
                "best_identified_model": best_res.data["identified_model"],
                "best_parameters": best_res.data["parameters"],
                "candidates": candidates,
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=best_res.warnings,
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
