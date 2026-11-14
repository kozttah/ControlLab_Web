"""Estimação de modelos Output-Error (OE) via otimização não-linear Gauss-Newton / Levenberg-Marquardt.

Escopo normativo (CL-DIR-001 Seção 5.1, Seção 5.2, Seção 13.6):
- Modelo Output-Error: $y(k) = \\sum_{j=1}^m \\frac{B_j(q^{-1})}{F(q^{-1})} u_j(k - n_{k,j}) + e(k)$,
  onde a dinâmica não contaminada $w(k)$ satisfaz $F(q^{-1}) w(k) = \\sum_{j=1}^m B_j(q^{-1}) u_j(k - n_{k,j})$;
- Inicialização consistente por ARX + variáveis instrumentais (IV) seguida de refinamento por mínimos quadrados
  não-lineares (`scipy.optimize.least_squares` com método Trust-Region Reflective / Levenberg-Marquardt);
- Verificação e projeção de estabilidade do preditor ($F(q^{-1})$ dentro do círculo unitário, $|z_p| < 1$);
- Estimação de covariância assintótica via decomposição QR/SVD da matriz Jacobiana dos resíduos no ótimo
  (sem usar `np.linalg.inv` explícito).
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
import scipy.linalg
import scipy.optimize
import scipy.signal

from control_lab.core.models import Dataset, IdentifiedModel, TransferFunction
from control_lab.core.tensors import array_to_tensor, complex_to_pair
from control_lab.diagnostics import (
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from .arx import _normalize_per_input_int, _solve_qr_svd_least_squares, fit_arx
from .preprocessing import (
    DEFAULT_COND_WARN_THRESHOLD,
    DEFAULT_RANK_RTOL,
    check_persistence_of_excitation,
    handle_id_failure,
    resolve_dataset_inputs,
)
from .validation import analyze_residuals, compute_fit_percent, compute_information_criteria


def _stabilize_monic_polynomial(f_coeffs: list[float] | np.ndarray, max_radius: float = 0.995) -> np.ndarray:
    """Reflete raízes fora de `max_radius` para dentro do círculo unitário preservando polinômio mônico real."""
    f_arr = np.asarray(f_coeffs, dtype=np.float64)
    if f_arr.size == 0:
        return f_arr
    poly = np.concatenate([[1.0], f_arr])
    roots = np.roots(poly)
    abs_r = np.abs(roots)
    modified = False
    for idx, r in enumerate(roots):
        mag = abs_r[idx]
        if mag >= max_radius:
            roots[idx] = (max_radius * r / mag) if mag > 0 else 0.0
            modified = True
    if not modified:
        return f_arr.copy()
    new_poly = np.real(np.poly(roots))
    return np.asarray(new_poly[1:], dtype=np.float64)


def _simulate_oe_channel(
    f_vec: np.ndarray,
    b_vecs: list[np.ndarray],
    nk_list: list[int],
    u_mat: np.ndarray,
    y_init: np.ndarray | None = None,
) -> np.ndarray:
    """Calcula a saída livre de ruído $w(k)$ de um canal Output-Error via filtro digital IIR."""
    n_samples, m = u_mat.shape
    nf = f_vec.size
    a_poly = np.concatenate([[1.0], f_vec])

    # Termo forçado B(q^-1) u(k - nk)
    v_forced = np.zeros(n_samples, dtype=np.float64)
    for j in range(m):
        nk_j = nk_list[j]
        b_j = b_vecs[j]
        nb_j = b_j.size
        for s in range(nb_j):
            lag = nk_j + s
            if lag == 0:
                v_forced += b_j[s] * u_mat[:, j]
            elif lag < n_samples:
                v_forced[lag:] += b_j[s] * u_mat[: n_samples - lag, j]

    if nf == 0:
        return v_forced

    # Se y_init estiver disponível para os primeiros nf passos, usa recorrência alinhada
    max_b_lag = max((nk_list[j] + b_vecs[j].size - 1 for j in range(m) if b_vecs[j].size > 0), default=0)
    max_lag = max(nf, max_b_lag)
    if y_init is not None and max_lag > 0 and max_lag < n_samples:
        w = np.zeros(n_samples, dtype=np.float64)
        w[:max_lag] = y_init[:max_lag]
        for k in range(max_lag, n_samples):
            acc = v_forced[k]
            for r in range(1, nf + 1):
                acc -= f_vec[r - 1] * w[k - r]
            w[k] = acc
        return w

    w_filt = scipy.signal.lfilter([1.0], a_poly, v_forced)
    return np.asarray(w_filt, dtype=np.float64)


def fit_oe(
    dataset_or_u: Any = None,
    y: Any = None,
    *,
    nb: int | Sequence[int] = 2,
    nf: int = 2,
    nk: int | Sequence[int] = 1,
    dataset: Dataset | Mapping[str, Any] | None = None,
    val_dataset: Dataset | Mapping[str, Any] | None = None,
    u: Any = None,
    t: Any = None,
    dt: float | None = None,
    max_nfev: int = 200,
    ftol: float = 1e-10,
    xtol: float = 1e-10,
    rank_rtol: float = DEFAULT_RANK_RTOL,
    cond_warn_threshold: float = DEFAULT_COND_WARN_THRESHOLD,
    max_lag_residuals: int = 20,
    allow_irregular_sampling: bool = False,
    seed: int | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Estima modelo Output-Error (OE) $(n_b, n_f, n_k)$ via Gauss-Newton / Trust-Region inicializado por ARX/IV.

    Problema matemático
    -------------------
    No modelo Output-Error:
    $$y(k) = \\sum_{j=1}^m \\frac{B_j(q^{-1})}{F(q^{-1})} u_j(k - n_{k,j}) + e(k), \\quad F(q^{-1}) = 1 + f_1 q^{-1} + \\dots + f_{n_f} q^{-n_f}$$
    Diferentemente do ARX, o ruído $e(k)$ afeta diretamente a saída sem passar pelo denominador dinâmico $1/F(q^{-1})$,
    de modo que o estimador OE permanece consistente mesmo quando o ruído aditivo na saída não compartilha os polos da planta.
    """
    prov: Provenance = build_provenance(
        "identification.fit_oe",
        seed=seed,
        tolerances={"ftol": float(ftol), "xtol": float(xtol), "rank_rtol": float(rank_rtol)},
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if isinstance(nf, bool) or not isinstance(nf, (int, np.integer)) or int(nf) < 0:
            raise ValidationError(f"nf deve ser inteiro >= 0, recebido {nf!r}.")
        nf_int = int(nf)

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

        # Verifica PE da entrada
        pe_order = max(1, nf_int + max(nb_list))
        pe_res = check_persistence_of_excitation(
            ds_train.u,
            order=pe_order,
            rank_rtol=rank_rtol,
            cond_warn_threshold=cond_warn_threshold,
        )
        warnings_out.extend(pe_res.warnings)
        pe_satisfied = bool(pe_res.assumptions.get("pe_satisfied", False))

        # Inicialização ARX
        arx_init = fit_arx(
            dataset=ds_train,
            na=nf_int,
            nb=nb_list,
            nk=nk_list,
            rank_rtol=rank_rtol,
            cond_warn_threshold=cond_warn_threshold,
            allow_irregular_sampling=allow_irregular_sampling,
            raise_on_error=True,
        )
        assert arx_init.data is not None
        init_struct = arx_init.data["identified_model"]["provenance"]["model_structure"]

        f_coeffs_all: list[list[float]] = []
        b_coeffs_all: list[list[list[float]]] = []
        b_full_all: list[list[list[float]]] = []
        cov_matrices: list[np.ndarray | None] = []
        opt_diags: list[dict[str, Any]] = []
        num_z_grid: list[list[np.ndarray]] = []
        den_z_grid: list[list[np.ndarray]] = []

        max_lag_u = max((nk_list[j] + nb_list[j] - 1 for j in range(m) if nb_list[j] > 0), default=0)
        max_lag = max(nf_int, max_lag_u)
        eval_slice = slice(max_lag, ds_train.n_samples)
        n_eff = ds_train.n_samples - max_lag

        for i in range(p):
            y_col = ds_train.y[:, i]
            f0 = _stabilize_monic_polynomial(init_struct["a_coeffs"][i], max_radius=0.98)
            b0_list = [np.asarray(init_struct["b_coeffs"][i][j], dtype=np.float64) for j in range(m)]

            # Passo de Variáveis Instrumentais (IV) usando a saída simulada do ARX inicial como instrumento
            w_iv = _simulate_oe_channel(f0, b0_list, nk_list, ds_train.u, y_init=y_col)
            cols_iv: list[np.ndarray] = []
            for r in range(1, nf_int + 1):
                cols_iv.append(-w_iv[max_lag - r : ds_train.n_samples - r])
            for j in range(m):
                for s in range(nb_list[j]):
                    lag = nk_list[j] + s
                    cols_iv.append(ds_train.u[max_lag - lag : ds_train.n_samples - lag, j])
            if cols_iv:
                Phi_iv = np.column_stack(cols_iv)
                ls_iv = _solve_qr_svd_least_squares(Phi_iv, y_col[eval_slice], rank_rtol=rank_rtol)
                if not ls_iv["rank_deficient"]:
                    theta_iv = ls_iv["theta"]
                    f_iv = _stabilize_monic_polynomial(theta_iv[:nf_int], max_radius=0.98)
                    b_iv_list: list[np.ndarray] = []
                    off = nf_int
                    for j in range(m):
                        b_iv_list.append(theta_iv[off : off + nb_list[j]])
                        off += nb_list[j]
                    w_test = _simulate_oe_channel(f_iv, b_iv_list, nk_list, ds_train.u, y_init=y_col)
                    if np.linalg.norm(y_col[eval_slice] - w_test[eval_slice]) < np.linalg.norm(
                        y_col[eval_slice] - w_iv[eval_slice]
                    ):
                        f0 = f_iv
                        b0_list = b_iv_list

            theta0 = np.concatenate([f0] + b0_list)

            def _unpack_theta(th: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
                f_v = th[:nf_int]
                b_vs: list[np.ndarray] = []
                idx_off = nf_int
                for j_in in range(m):
                    nb_j = nb_list[j_in]
                    b_vs.append(th[idx_off : idx_off + nb_j])
                    idx_off += nb_j
                return f_v, b_vs

            def _residual_fn(th: np.ndarray) -> np.ndarray:
                f_v, b_vs = _unpack_theta(th)
                if f_v.size > 0:
                    roots_f = np.roots(np.concatenate([[1.0], f_v]))
                    max_r = float(np.max(np.abs(roots_f)))
                    if max_r >= 0.9995:
                        f_stab = _stabilize_monic_polynomial(f_v, max_radius=0.998)
                        w_sim = _simulate_oe_channel(f_stab, b_vs, nk_list, ds_train.u, y_init=y_col)
                        res_base = y_col[eval_slice] - w_sim[eval_slice]
                        return res_base * (1.0 + 100.0 * (max_r - 0.999))
                w_sim = _simulate_oe_channel(f_v, b_vs, nk_list, ds_train.u, y_init=y_col)
                return y_col[eval_slice] - w_sim[eval_slice]

            opt_res = scipy.optimize.least_squares(
                _residual_fn,
                theta0,
                method="trf",
                ftol=ftol,
                xtol=xtol,
                gtol=1e-10,
                max_nfev=max_nfev,
            )

            f_opt_raw, b_opt_list = _unpack_theta(opt_res.x)
            f_opt = _stabilize_monic_polynomial(f_opt_raw, max_radius=0.999)
            if not np.allclose(f_opt, f_opt_raw, atol=1e-9):
                warnings_out.append(
                    WarningItem(
                        code="OE_PREDICTOR_STABILIZED",
                        message="Raízes de F(q^-1) projetadas para o interior do círculo unitário.",
                        details={"output_channel": i},
                    )
                )

            f_i_list = [float(v) for v in f_opt.tolist()]
            f_coeffs_all.append(f_i_list)

            row_b: list[list[float]] = []
            row_b_full: list[list[float]] = []
            for j in range(m):
                b_ij = [float(v) for v in b_opt_list[j].tolist()]
                row_b.append(b_ij)
                row_b_full.append(([0.0] * nk_list[j]) + b_ij)
            b_coeffs_all.append(row_b)
            b_full_all.append(row_b_full)

            # Covariância assintótica via QR/SVD da Jacobiana J no ótimo
            J_opt = np.asarray(opt_res.jac, dtype=np.float64)
            res_opt = _residual_fn(np.concatenate([f_opt] + b_opt_list))
            d_i = theta0.size
            dof_i = max(1, n_eff - d_i)
            sigma2_i = float(np.dot(res_opt, res_opt) / dof_i)

            jac_ls = _solve_qr_svd_least_squares(J_opt, res_opt, rank_rtol=rank_rtol)
            if jac_ls["unscaled_cov"] is not None and pe_satisfied:
                cov_matrices.append(sigma2_i * jac_ls["unscaled_cov"])
            else:
                cov_matrices.append(None)

            opt_diags.append(
                {
                    "output_channel": i,
                    "converged": bool(opt_res.success),
                    "nfev": int(opt_res.nfev),
                    "cost": float(opt_res.cost),
                    "jacobian_rank": int(jac_ls["rank"]),
                    "jacobian_condition": float(jac_ls["condition"]),
                    "noise_variance_estimate": sigma2_i,
                }
            )

            # Constrói polinômios em z descendente
            f_asc = np.array([1.0] + f_i_list, dtype=np.float64)
            row_num_z: list[np.ndarray] = []
            row_den_z: list[np.ndarray] = []
            for j in range(m):
                b_asc = np.array(row_b_full[j], dtype=np.float64)
                deg_ij = max(f_asc.size - 1, b_asc.size - 1)
                den_z = np.zeros(deg_ij + 1, dtype=np.float64)
                num_z = np.zeros(deg_ij + 1, dtype=np.float64)
                den_z[: f_asc.size] = f_asc
                num_z[: b_asc.size] = b_asc
                num_trim = np.trim_zeros(num_z, "f")
                if num_trim.size == 0:
                    num_trim = np.array([0.0], dtype=np.float64)
                row_num_z.append(num_trim)
                row_den_z.append(den_z)
            num_z_grid.append(row_num_z)
            den_z_grid.append(row_den_z)

        model_structure = {
            "family": "OE",
            "na": nf_int,
            "nf": nf_int,
            "nb": nb_list[0] if m == 1 else nb_list,
            "nk": nk_list[0] if m == 1 else nk_list,
            "nb_per_input": nb_list,
            "nk_per_input": nk_list,
            "n_inputs": m,
            "n_outputs": p,
            "a_coeffs": f_coeffs_all,
            "f_coeffs": f_coeffs_all,
            "b_coeffs": b_coeffs_all,
            "b_full_coeffs": b_full_all,
            "dt": resolved_dt,
        }

        tf_prov = build_provenance(
            "identification.fit_oe",
            seed=seed,
            tolerances={"ftol": float(ftol), "xtol": float(xtol), "rank_rtol": float(rank_rtol)},
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

        # Avaliação em treino (para OE, H(q)=1 => preditor de 1 passo e simulação livre coincidem com w(k))
        from .validation import _run_arx_or_oe_recurrence

        y_sim_tr, mlag_tr = _run_arx_or_oe_recurrence(model_structure, ds_train.u, ds_train.y, mode="free_simulation")
        tr_slice = slice(mlag_tr, ds_train.n_samples)
        fit_sim_tr = compute_fit_percent(ds_train.y[tr_slice], y_sim_tr[tr_slice])
        residuals_tr = ds_train.y[tr_slice] - y_sim_tr[tr_slice]

        n_params_total = p * (nf_int + sum(nb_list))
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
                    "fit_percent": fit_sim_tr["fit_percent"],
                    "fit_per_channel": fit_sim_tr["fit_per_channel"],
                    "rmse": fit_sim_tr["rmse"],
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

        if val_dataset is not None:
            ds_val = resolve_dataset_inputs(
                val_dataset,
                dt=resolved_dt,
                require_uniform=not allow_irregular_sampling,
                allow_irregular_sampling=allow_irregular_sampling,
            )
            y_sim_val, mlag_v = _run_arx_or_oe_recurrence(model_structure, ds_val.u, ds_val.y, mode="free_simulation")
            v_slice = slice(mlag_v, ds_val.n_samples)
            fit_sim_val = compute_fit_percent(ds_val.y[v_slice], y_sim_val[v_slice])
            res_val = ds_val.y[v_slice] - y_sim_val[v_slice]
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
                    "fit_percent": fit_sim_val["fit_percent"],
                    "fit_per_channel": fit_sim_val["fit_per_channel"],
                    "rmse": fit_sim_val["rmse"],
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

        if nf_int > 0:
            poles_list = [np.roots(np.array([1.0] + f_coeffs_all[i], dtype=np.float64)) for i in range(p)]
            poles_arr = np.concatenate(poles_list)
            order_idx = np.lexsort((np.imag(poles_arr), np.real(poles_arr)))
            poles_sorted = poles_arr[order_idx]
            spec_radius = float(np.max(np.abs(poles_sorted)))
        else:
            poles_sorted = np.array([], dtype=np.complex128)
            spec_radius = 0.0

        is_stable = bool(spec_radius < 1.0 - 1e-12)
        cov_primary = cov_matrices[0] if (p == 1 and cov_matrices[0] is not None) else None

        id_model = IdentifiedModel(
            model=tf_model,
            algorithm="OE_TRF_GAUSS_NEWTON",
            dataset_ref={"id": ds_train.id, "revision": ds_train.revision},
            partitions=partitions_dict,
            metrics=metrics_dict,
            noise_hypothesis={
                "structure": "OE",
                "output_additive_noise": True,
                "noise_transfer_function": "1",
                "delay_convention": "w(k) + f_1 w(k-1) + ... = b_1 u(k - nk) + ..., y(k) = w(k) + e(k)",
            },
            excitation_diagnostics={
                "pe_diagnostics": pe_res.diagnostics,
                "optimization_channels": opt_diags,
                "rank_deficient": not pe_satisfied,
            },
            covariance=cov_primary,
            residual_diagnostics=resid_dict,
            provenance=tf_prov,
        )

        assumptions = {
            "uniform_sampling": ds_train.is_uniform_sampling,
            "pe_satisfied": pe_satisfied,
            "predictor_stable": is_stable,
            "noise_structure": "OE",
        }
        diagnostics = {
            "converged": all(d["converged"] for d in opt_diags),
            "optimization_channels": opt_diags,
            "rank_deficient": not pe_satisfied,
            "spectral_radius": spec_radius,
            "is_stable": is_stable,
            "fit_train_free_sim": fit_sim_tr["fit_percent"],
            "rmse_train_free_sim": fit_sim_tr["rmse"],
            "aic": info_criteria["aic"],
            "bic": info_criteria["bic"],
            "fpe": info_criteria["fpe"],
        }
        data: dict[str, Any] = {
            "identified_model": id_model.to_dict(),
            "transfer_function": tf_model.to_dict(),
            "parameters": {
                "nb": nb_list[0] if m == 1 else nb_list,
                "nf": nf_int,
                "nk": nk_list[0] if m == 1 else nk_list,
                "f": f_coeffs_all[0] if p == 1 else f_coeffs_all,
                "b": (
                    b_coeffs_all[0][0]
                    if (p == 1 and m == 1)
                    else (b_coeffs_all[0] if p == 1 else b_coeffs_all)
                ),
            },
            "poles": complex_to_pair(poles_sorted),
            "metrics": metrics_dict,
            "y_hat_train_free_sim": array_to_tensor(y_sim_tr, dtype="float64", order="C"),
            "residuals_train": array_to_tensor(residuals_tr, dtype="float64", order="C"),
        }
        if cov_primary is not None:
            data["covariance"] = array_to_tensor(cov_primary, dtype="float64", order="C")

        return Result(
            status="warning" if warnings_out else "success",
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
