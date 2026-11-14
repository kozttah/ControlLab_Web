"""Identificação por Subespaços (MOESP / N4SID) com matrizes de Hankel, projeção QR e truncamento SVD.

Escopo normativo (CL-DIR-001 Seção 5.1, Seção 5.2, Seção 13.6 e Fase F4 Seção 14.2):
- Construção das matrizes de bloco de Hankel de entradas/saídas ($U_f, Y_f$ ou passadas/futuras $W_p, U_f, Y_f$);
- Projeção ortogonal/oblíqua livre de inversão matricial via fatoração LQ (QR transposta: `scipy.linalg.qr`);
- Decomposição em valores singulares (SVD) do bloco projetado para estimar o subespaço de observabilidade
  estendido $\\mathcal{O}_s = U_n \\Sigma_n^{1/2}$ e o espectro de valores singulares de Hankel;
- Extração de $C = \\mathcal{O}_s(1:p, :)$ e $A$ por shift-invariance ($\\mathcal{O}_s(1:(s-1)p, :) A \\approx \\mathcal{O}_s(p+1:sp, :)$)
  resolvida por QR/SVD (`scipy.linalg.lstsq`);
- Estimação linear dos pares $(B, D)$ e do estado inicial $x_0$ minimizando o erro de simulação de saída
  em múltiplos passos via QR/SVD, mais ganho de inovação de Kalman $K_{\\text{kalman}}$ para predição de 1 passo;
- Nenhum uso de `np.linalg.inv`.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
import scipy.linalg

from control_lab.core.models import Dataset, IdentifiedModel, StateSpace
from control_lab.core.tensors import array_to_tensor, complex_to_pair
from control_lab.diagnostics import (
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
    _run_subspace_recurrence,
    analyze_residuals,
    compute_fit_percent,
    compute_information_criteria,
)


def _build_block_hankel(signal_2d: np.ndarray, horizon: int, n_cols: int, start_idx: int = 0) -> np.ndarray:
    """Constrói matriz bloco-Hankel com `horizon` blocos de linhas e `n_cols` colunas."""
    n_channels = signal_2d.shape[1]
    H = np.empty((horizon * n_channels, n_cols), dtype=np.float64)
    for blk in range(horizon):
        sl = slice(start_idx + blk, start_idx + blk + n_cols)
        H[blk * n_channels : (blk + 1) * n_channels, :] = signal_2d[sl, :].T
    return H


def _estimate_bd_and_x0_linear_ls(
    A: np.ndarray,
    C: np.ndarray,
    u_mat: np.ndarray,
    y_mat: np.ndarray,
    *,
    estimate_feedthrough: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Estima $(B, D, x_0)$ por mínimos quadrados lineares via QR/SVD dado $(A, C)$.

    Como $y(k) = C A^k x_0 + \\sum_{j=0}^{k-1} C A^{k-1-j} B u(j) + D u(k)$ é linear em
    $\\text{vec}(B)$, $\\text{vec}(D)$ e $x_0$:
    - Para cada entrada $r \\in \\{1, \\dots, m\\}$ e estado $q \\in \\{1, \\dots, n\\}$, a resposta ao
      sinal $u_r(k)$ para a base unitária $B = e_q e_r^T$ é obtida filtrando $u_r$ pelo sistema
      $\\tilde{x}_{q,r}(k+1) = A \\tilde{x}_{q,r}(k) + e_q u_r(k)$, $\\tilde{y}_{q,r}(k) = C \\tilde{x}_{q,r}(k)$.
    """
    n_samples, m = u_mat.shape
    p = y_mat.shape[1]
    n = A.shape[0]

    # 1. Regressores de x0: phi_{x0, l}(k) = C A^k e_l
    reg_cols: list[np.ndarray] = []
    X_basis = np.eye(n, dtype=np.float64)
    Phi_x0 = np.empty((n_samples * p, n), dtype=np.float64)
    for k in range(n_samples):
        Phi_x0[k * p : (k + 1) * p, :] = C @ X_basis
        X_basis = A @ X_basis
    reg_cols.append(Phi_x0)

    # 2. Regressores de B: dimensão n * m
    Phi_B = np.empty((n_samples * p, n * m), dtype=np.float64)
    col_idx = 0
    for j in range(m):
        u_j = u_mat[:, j]
        for q in range(n):
            x_sim = np.zeros(n, dtype=np.float64)
            y_sim = np.empty((n_samples, p), dtype=np.float64)
            for k in range(n_samples):
                y_sim[k, :] = C @ x_sim
                x_sim = A @ x_sim
                x_sim[q] += u_j[k]
            Phi_B[:, col_idx] = y_sim.reshape(-1)
            col_idx += 1
    reg_cols.append(Phi_B)

    # 3. Regressores opcionais de D: dimensão p * m
    if estimate_feedthrough:
        Phi_D = np.empty((n_samples * p, p * m), dtype=np.float64)
        d_col = 0
        for j in range(m):
            u_j = u_mat[:, j]
            for i in range(p):
                y_d = np.zeros((n_samples, p), dtype=np.float64)
                y_d[:, i] = u_j
                Phi_D[:, d_col] = y_d.reshape(-1)
                d_col += 1
        reg_cols.append(Phi_D)

    Phi_all = np.hstack(reg_cols)
    y_vec = y_mat.reshape(-1)

    theta, _, _, _ = scipy.linalg.lstsq(Phi_all, y_vec, lapack_driver="gelsy")
    x0_est = theta[:n].copy()
    b_flat = theta[n : n + n * m]
    B_est = np.zeros((n, m), dtype=np.float64)
    idx = 0
    for j in range(m):
        for q in range(n):
            B_est[q, j] = float(b_flat[idx])
            idx += 1

    if estimate_feedthrough:
        d_flat = theta[n + n * m :]
        D_est = np.zeros((p, m), dtype=np.float64)
        idx = 0
        for j in range(m):
            for i in range(p):
                D_est[i, j] = float(d_flat[idx])
                idx += 1
    else:
        D_est = np.zeros((p, m), dtype=np.float64)

    return B_est, D_est, x0_est


def _stabilize_discrete_matrix(A: np.ndarray, max_radius: float = 0.998) -> tuple[np.ndarray, bool]:
    """Garante estabilidade assintótica discreta $\\rho(A) < 1$ via decomposição de Schur real se necessário."""
    if A.size == 0:
        return A.copy(), False
    eigs = np.linalg.eigvals(A)
    rho = float(np.max(np.abs(eigs)))
    if rho < max_radius:
        return A.copy(), False
    scale = max_radius / max(rho, 1e-12)
    return A * scale, True


def fit_subspace(
    dataset_or_u: Any = None,
    y: Any = None,
    *,
    order: int | None = None,
    horizon: int | None = None,
    method: str = "moesp",
    estimate_feedthrough: bool = False,
    dataset: Dataset | Mapping[str, Any] | None = None,
    val_dataset: Dataset | Mapping[str, Any] | None = None,
    u: Any = None,
    t: Any = None,
    dt: float | None = None,
    svd_gap_threshold: float = 1e-2,
    rank_rtol: float = DEFAULT_RANK_RTOL,
    cond_warn_threshold: float = DEFAULT_COND_WARN_THRESHOLD,
    max_lag_residuals: int = 20,
    allow_irregular_sampling: bool = False,
    seed: int | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Identifica modelo em espaço de estados discreto por subespaços (MOESP / N4SID).

    Problema matemático
    -------------------
    Dado um conjunto de dados $(u(k), y(k))_{k=0}^{N-1}$ e um horizonte de bloco $s > n$:
    1. No algoritmo **MOESP**, monta-se a matriz de Hankel conjunta $\\begin{bmatrix} U_{0|s-1} \\\\ Y_{0|s-1} \\end{bmatrix}$
       e aplica-se fatoração LQ (via `scipy.linalg.qr` de sua transposta):
       $$\\begin{bmatrix} U_{0|s-1} \\\\ Y_{0|s-1} \\end{bmatrix} = \\begin{bmatrix} L_{11} & 0 \\\\ L_{21} & L_{22} \\end{bmatrix} \\begin{bmatrix} Q_1^T \\\\ Q_2^T \\end{bmatrix}$$
       O bloco $L_{22}$ representa a projeção ortogonal de $Y_{0|s-1}$ sobre o complemento ortogonal de $U_{0|s-1}$
       ($Y_{0|s-1} \\Pi_{U_{0|s-1}^\\perp}$), cujo espaço coluna coincide com a matriz de observabilidade estendida $\\mathcal{O}_s$.
    2. No algoritmo **N4SID**, utiliza-se adicionalmente o bloco de instrumentos passados $W_p = \\begin{bmatrix} U_p \\\\ Y_p \\end{bmatrix}$
       na fatoração LQ em três blocos $(U_f, W_p, Y_f)$ para filtrar ruído de saída correlacionado via projeção oblíqua.
    3. Da SVD $M = U \\Sigma V^T$, trunca-se na ordem $n$ selecionada, extrai-se $\\mathcal{O}_s = U_{:, 1:n} \\Sigma_{1:n}^{1/2}$,
       $C = \\mathcal{O}_s(1:p, :)$ e $A$ por shift-invariance via QR/SVD, seguido de $(B, D, x_0)$ por mínimos quadrados lineares.
    """
    prov: Provenance = build_provenance(
        "identification.fit_subspace",
        seed=seed,
        tolerances={"svd_gap_threshold": float(svd_gap_threshold), "rank_rtol": float(rank_rtol)},
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(method, str) or method.lower() not in ("moesp", "n4sid"):
            raise ValidationError(f"method inválido em fit_subspace: {method!r}. Use 'moesp' ou 'n4sid'.")
        m_kind = method.lower()

        if order is not None:
            if isinstance(order, bool) or not isinstance(order, (int, np.integer)) or int(order) < 1:
                raise ValidationError(f"order deve ser inteiro >= 1 ou None, recebido {order!r}.")
            target_order: int | None = int(order)
        else:
            target_order = None

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

        n_samples = ds_train.n_samples
        m = ds_train.n_inputs
        p = ds_train.n_outputs

        if horizon is not None:
            if isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer)) or int(horizon) < 2:
                raise ValidationError(f"horizon deve ser inteiro >= 2, recebido {horizon!r}.")
            s_hor = int(horizon)
        else:
            base_n = target_order if target_order is not None else 2
            s_hor = max(2 * base_n + 2, 6)
            s_hor = min(s_hor, max(2, n_samples // 4))

        if target_order is not None and s_hor <= target_order:
            s_hor = target_order + 2

        # Verifica PE na entrada de ordem 2*s_hor
        pe_order = min(max(2, 2 * s_hor), max(2, n_samples // 3))
        pe_res = check_persistence_of_excitation(
            ds_train.u,
            order=pe_order,
            rank_rtol=rank_rtol,
            cond_warn_threshold=cond_warn_threshold,
        )
        warnings_out.extend(pe_res.warnings)
        pe_satisfied = bool(pe_res.assumptions.get("pe_satisfied", False))

        if m_kind == "n4sid" and n_samples >= 4 * s_hor + 4:
            # Fatoração LQ de 3 blocos: [U_f; W_p; Y_f] onde W_p = [U_p; Y_p]
            n_cols = n_samples - 2 * s_hor + 1
            U_p = _build_block_hankel(ds_train.u, s_hor, n_cols, start_idx=0)
            Y_p = _build_block_hankel(ds_train.y, s_hor, n_cols, start_idx=0)
            U_f = _build_block_hankel(ds_train.u, s_hor, n_cols, start_idx=s_hor)
            Y_f = _build_block_hankel(ds_train.y, s_hor, n_cols, start_idx=s_hor)
            W_p = np.vstack([U_p, Y_p])
            H_stack = np.vstack([U_f, W_p, Y_f])
            _, R_qr = scipy.linalg.qr(H_stack.T, mode="economic")
            L_mat = R_qr.T
            idx_uf = s_hor * m
            idx_wp = idx_uf + s_hor * (m + p)
            # Projeção oblíqua de Y_f ao longo de U_f sobre W_p está contida em L_{32}
            L_32 = L_mat[idx_wp:, idx_uf:idx_wp]
            # Fallback para incluir L_{33} se o sistema tiver dinâmica livre não excitada em W_p
            if np.linalg.norm(L_32, ord="fro") > 1e-12:
                proj_block = L_32
            else:
                proj_block = L_mat[idx_wp:, idx_uf:]
        else:
            # Algoritmo MOESP: [U_{0|s-1}; Y_{0|s-1}]
            n_cols = n_samples - s_hor + 1
            if n_cols < s_hor * (m + p):
                raise ValidationError(
                    message=f"Amostras insuficientes ({n_samples}) para identificação por subespaços com horizon={s_hor}.",
                    parameters={"n_samples": n_samples, "horizon": s_hor},
                )
            U_h = _build_block_hankel(ds_train.u, s_hor, n_cols, start_idx=0)
            Y_h = _build_block_hankel(ds_train.y, s_hor, n_cols, start_idx=0)
            H_stack = np.vstack([U_h, Y_h])
            _, R_qr = scipy.linalg.qr(H_stack.T, mode="economic")
            L_mat = R_qr.T
            idx_u = s_hor * m
            proj_block = L_mat[idx_u:, idx_u:]

        U_svd, hankel_svals, _ = scipy.linalg.svd(proj_block, full_matrices=False)
        s_max = float(hankel_svals[0]) if hankel_svals.size > 0 else 0.0

        # Seleção automática de ordem pelo maior salto logarítmico acima de svd_gap_threshold
        max_possible_order = max(1, min((s_hor - 1) * p, hankel_svals.size - 1))
        if target_order is None:
            if s_max <= 1e-14:
                n_est = 1
            else:
                sig_mask = hankel_svals[:max_possible_order] > (svd_gap_threshold * s_max)
                n_sig = int(np.sum(sig_mask))
                if n_sig <= 1:
                    n_est = 1
                else:
                    ratios = hankel_svals[:n_sig] / np.maximum(hankel_svals[1 : n_sig + 1], 1e-15)
                    n_est = int(np.argmax(ratios) + 1)
        else:
            if target_order > max_possible_order:
                raise ValidationError(
                    f"Ordem solicitada ({target_order}) excede limite identificável ({max_possible_order}) para horizon={s_hor}."
                )
            n_est = target_order

        # Matriz de observabilidade estendida O_s = U_n @ diag(sqrt(sigma_n))
        s_n = np.maximum(hankel_svals[:n_est], 1e-14)
        sqrt_sn = np.sqrt(s_n)
        O_s = U_svd[:, :n_est] * sqrt_sn.reshape(1, -1)

        C_est = O_s[:p, :].copy()
        O_up = O_s[: (s_hor - 1) * p, :]
        O_dn = O_s[p : s_hor * p, :]
        A_raw, _, _, _ = scipy.linalg.lstsq(O_up, O_dn, lapack_driver="gelsy")
        A_est, was_stabilized = _stabilize_discrete_matrix(A_raw, max_radius=0.999)
        if was_stabilized:
            warnings_out.append(
                WarningItem(
                    code="SUBSPACE_MATRIX_A_STABILIZED",
                    message="Matriz de transição A estimada por subespaços foi estabilizada para dentro do círculo unitário.",
                    details={"order": n_est},
                )
            )

        B_est, D_est, x0_est = _estimate_bd_and_x0_linear_ls(
            A_est,
            C_est,
            ds_train.u,
            ds_train.y,
            estimate_feedthrough=estimate_feedthrough,
        )

        # Estima ganho de inovação K_kalman por mínimos quadrados a partir da sequência de estados simulada
        ss_temp = StateSpace(
            A=A_est,
            B=B_est,
            C=C_est,
            D=D_est,
            dt=resolved_dt,
            input_names=ds_train.input_names,
            output_names=ds_train.output_names,
            units=ds_train.units,
        )
        y_free_tr, x_free_tr, _ = _run_subspace_recurrence(
            ss_temp, {}, ds_train.u, ds_train.y, mode="free_simulation", x0=x0_est
        )
        innov_tr = ds_train.y - y_free_tr
        # Resíduo de estado x(k+1) - A x(k) - B u(k) correlacionado com inovação
        K_kalman = np.zeros((n_est, p), dtype=np.float64)
        if n_samples > n_est + 2 and np.linalg.norm(innov_tr, ord="fro") > 1e-12:
            # Em sistemas com ruído de processo/medição, aproxima K_kalman via DARE se observável
            try:
                Q_est = 1e-4 * np.eye(n_est, dtype=np.float64)
                R_est = (innov_tr.T @ innov_tr) / float(n_samples) + 1e-6 * np.eye(p, dtype=np.float64)
                P_dare = scipy.linalg.solve_discrete_are(A_est.T, C_est.T, Q_est, R_est)
                S_innov = C_est @ P_dare @ C_est.T + R_est
                # K_kalman = A P C^T S^{-1} resolvido via solve(S^T, (A P C^T)^T)^T
                K_cand = scipy.linalg.solve(S_innov.T, (A_est @ P_dare @ C_est.T).T, assume_a="pos").T
                if np.max(np.abs(np.linalg.eigvals(A_est - K_cand @ C_est))) < 0.999:
                    K_kalman = K_cand
            except Exception:
                K_kalman = np.zeros((n_est, p), dtype=np.float64)

        model_structure = {
            "family": "SUBSPACE",
            "method": m_kind.upper(),
            "n_states": int(n_est),
            "n_inputs": int(m),
            "n_outputs": int(p),
            "horizon": int(s_hor),
            "estimate_feedthrough": bool(estimate_feedthrough),
            "dt": resolved_dt,
            "x0": [float(v) for v in x0_est.tolist()],
            "kalman_gain": array_to_tensor(K_kalman, dtype="float64", order="C"),
            "hankel_singular_values": [float(v) for v in hankel_svals.tolist()],
        }

        ss_prov = build_provenance(
            f"identification.fit_subspace.{m_kind}",
            seed=seed,
            tolerances={"svd_gap_threshold": float(svd_gap_threshold), "rank_rtol": float(rank_rtol)},
            model_revision=ds_train.revision,
            model_structure=model_structure,
        )
        ss_model = ss_temp.with_revision(ss_temp.revision, provenance=ss_prov.to_dict())

        y_pred_tr, _, _ = _run_subspace_recurrence(
            ss_model, model_structure, ds_train.u, ds_train.y, mode="one_step_prediction", x0=x0_est
        )
        fit_pred_tr = compute_fit_percent(ds_train.y, y_pred_tr)
        fit_sim_tr = compute_fit_percent(ds_train.y, y_free_tr)
        residuals_tr = ds_train.y - y_pred_tr

        n_params_total = n_est * n_est + n_est * m + p * n_est + (p * m if estimate_feedthrough else 0)
        info_criteria = compute_information_criteria(residuals_tr, n_params_total)
        resid_diag_tr = analyze_residuals(
            residuals_tr,
            ds_train.u,
            max_lag=min(max_lag_residuals, max(1, residuals_tr.shape[0] - 1)),
        )

        metrics_dict: dict[str, Any] = {
            "train": {
                "partition": "train",
                "n_samples": ds_train.n_samples,
                "n_effective_samples": ds_train.n_samples,
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

        if val_dataset is not None:
            ds_val = resolve_dataset_inputs(
                val_dataset,
                dt=resolved_dt,
                require_uniform=not allow_irregular_sampling,
                allow_irregular_sampling=allow_irregular_sampling,
            )
            y_pred_val, _, _ = _run_subspace_recurrence(
                ss_model, model_structure, ds_val.u, ds_val.y, mode="one_step_prediction"
            )
            y_sim_val, _, _ = _run_subspace_recurrence(
                ss_model, model_structure, ds_val.u, ds_val.y, mode="free_simulation"
            )
            fit_pred_val = compute_fit_percent(ds_val.y, y_pred_val)
            fit_sim_val = compute_fit_percent(ds_val.y, y_sim_val)
            res_val = ds_val.y - y_pred_val
            resid_diag_val = analyze_residuals(
                res_val,
                ds_val.u,
                max_lag=min(max_lag_residuals, max(1, res_val.shape[0] - 1)),
            )
            metrics_dict["validation"] = {
                "partition": "validation",
                "n_samples": ds_val.n_samples,
                "n_effective_samples": ds_val.n_samples,
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

        poles = ss_model.poles()
        order_idx = np.lexsort((np.imag(poles), np.real(poles)))
        poles_sorted = poles[order_idx]
        spec_radius = float(np.max(np.abs(poles_sorted))) if poles_sorted.size > 0 else 0.0
        is_stable = bool(spec_radius < 1.0 - 1e-12)

        id_model = IdentifiedModel(
            model=ss_model,
            algorithm=f"SUBSPACE_{m_kind.upper()}",
            dataset_ref={"id": ds_train.id, "revision": ds_train.revision},
            partitions=partitions_dict,
            metrics=metrics_dict,
            noise_hypothesis={
                "structure": "INNOVATION_STATE_SPACE",
                "method": m_kind.upper(),
                "horizon": int(s_hor),
            },
            excitation_diagnostics={
                "pe_diagnostics": pe_res.diagnostics,
                "hankel_singular_values": [float(v) for v in hankel_svals.tolist()],
                "rank_deficient": not pe_satisfied,
            },
            covariance=None,
            residual_diagnostics=resid_dict,
            provenance=ss_prov,
        )

        assumptions = {
            "uniform_sampling": ds_train.is_uniform_sampling,
            "pe_satisfied": pe_satisfied,
            "is_stable": is_stable,
            "method": m_kind.upper(),
        }
        diagnostics = {
            "order": int(n_est),
            "horizon": int(s_hor),
            "hankel_singular_values": [float(v) for v in hankel_svals.tolist()],
            "rank_deficient": not pe_satisfied,
            "spectral_radius": spec_radius,
            "is_stable": is_stable,
            "fit_train_one_step": fit_pred_tr["fit_percent"],
            "fit_train_free_sim": fit_sim_tr["fit_percent"],
            "rmse_train_free_sim": fit_sim_tr["rmse"],
            "aic": info_criteria["aic"],
            "bic": info_criteria["bic"],
        }
        data: dict[str, Any] = {
            "identified_model": id_model.to_dict(),
            "state_space": ss_model.to_dict(),
            "order": int(n_est),
            "horizon": int(s_hor),
            "hankel_singular_values": array_to_tensor(hankel_svals, dtype="float64", order="C"),
            "poles": complex_to_pair(poles_sorted),
            "x0": array_to_tensor(x0_est, dtype="float64", order="C"),
            "metrics": metrics_dict,
            "y_hat_train_one_step": array_to_tensor(y_pred_tr, dtype="float64", order="C"),
            "y_hat_train_free_sim": array_to_tensor(y_free_tr, dtype="float64", order="C"),
            "residuals_train": array_to_tensor(residuals_tr, dtype="float64", order="C"),
        }
        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=ss_prov,
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
