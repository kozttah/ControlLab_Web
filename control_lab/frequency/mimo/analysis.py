"""Análise MIMO no domínio da frequência: SVD, RGA, Sensibilidades S/T/KS e Nyquist Generalizado (Seções 5.5, 10.2 e 13.5)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.linalg

from control_lab.core.controllers import DynamicController, StateFeedbackController, _validate_feedback_sign
from control_lab.core.models import StateSpace, TransferFunction
from control_lab.core.tensors import check_dt_compatible, complex_to_pair, ensure_finite_float64
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    NumericalInconclusiveError,
    Provenance,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
)
from control_lab.frequency.siso._utils import (
    DEFAULT_N_OMEGA,
    handle_failure,
    resolve_omega_grid,
    sort_complex_roots,
)

DEFAULT_RGA_COND_MAX: float = 1e12


def _eval_model_matrix_at_omega(
    model: Any,
    omega: np.ndarray,
) -> dict[str, Any]:
    """Avalia matriz de resposta em frequência G(jw) ou G(e^{jw dt}) com shape (N_omega, p, m)."""
    N = omega.shape[0]

    if isinstance(model, DynamicController):
        model = StateSpace(
            A=model.Ac,
            B=model.Bc,
            C=model.Cc,
            D=model.Dc,
            dt=model.dt,
            id=model.id,
            revision=model.revision,
        )

    if isinstance(model, StateFeedbackController):
        p, m = model.K.shape
        G_mat = np.broadcast_to(model.K.astype(np.complex128)[None, :, :], (N, p, m)).copy()
        return {
            "G": G_mat,
            "p": p,
            "m": m,
            "dt": model.dt,
            "domain": "continuous" if model.dt is None else "discrete",
            "poles": np.array([], dtype=np.complex128),
            "revision": model.revision,
            "singular_frequencies": [],
            "warnings": [],
        }

    if isinstance(model, StateSpace):
        p, m = model.n_outputs, model.n_inputs
        n = model.n_states
        dt = model.dt
        s_pts = (1j * omega) if dt is None else np.exp(1j * omega * dt)
        poles = sort_complex_roots(np.linalg.eigvals(model.A)) if n > 0 else np.array([], dtype=np.complex128)
        G_mat = np.zeros((N, p, m), dtype=np.complex128)
        singular_freqs: list[float] = []
        if n == 0:
            G_mat[:] = model.D.astype(np.complex128)[None, :, :]
        else:
            eye_n = np.eye(n, dtype=np.complex128)
            A_c = model.A.astype(np.complex128)
            B_c = model.B.astype(np.complex128)
            C_c = model.C.astype(np.complex128)
            D_c = model.D.astype(np.complex128)
            for k in range(N):
                M_k = s_pts[k] * eye_n - A_c
                svals_k = np.linalg.svd(M_k, compute_uv=False)
                if svals_k[-1] <= 1e-13 * max(1.0, float(svals_k[0])):
                    singular_freqs.append(float(omega[k]))
                    M_k = M_k + 1e-13 * eye_n
                X_k = np.linalg.solve(M_k, B_c)
                G_mat[k, :, :] = C_c @ X_k + D_c
        return {
            "G": G_mat,
            "p": p,
            "m": m,
            "dt": dt,
            "domain": "continuous" if dt is None else "discrete",
            "poles": poles,
            "revision": model.revision,
            "singular_frequencies": singular_freqs,
            "warnings": [],
        }

    if isinstance(model, TransferFunction):
        p, m = model.n_outputs, model.n_inputs
        dt = model.dt
        s_pts = (1j * omega) if dt is None else np.exp(1j * omega * dt)
        G_mat = np.zeros((N, p, m), dtype=np.complex128)
        singular_freqs_set: set[float] = set()
        poles_list: list[np.ndarray] = []

        for i in range(p):
            for j in range(m):
                num_ij, den_ij = model._channel_descending_z_or_s(i, j)
                if den_ij.size > 1:
                    poles_list.append(np.roots(den_ij))
                num_vals = np.polyval(num_ij, s_pts)
                den_vals = np.polyval(den_ij, s_pts)
                bad_mask = np.abs(den_vals) <= 1e-14 * max(1.0, float(np.max(np.abs(den_ij))))
                if np.any(bad_mask):
                    for idx in np.where(bad_mask)[0].tolist():
                        singular_freqs_set.add(float(omega[idx]))
                    den_vals = np.where(bad_mask, 1e-14 + 0j, den_vals)
                G_mat[:, i, j] = num_vals / den_vals

        all_poles = sort_complex_roots(np.concatenate(poles_list)) if poles_list else np.array([], dtype=np.complex128)
        return {
            "G": G_mat,
            "p": p,
            "m": m,
            "dt": dt,
            "domain": "continuous" if dt is None else "discrete",
            "poles": all_poles,
            "revision": model.revision,
            "singular_frequencies": sorted(singular_freqs_set),
            "warnings": list(model.warnings),
        }

    # Suporte direto a matriz estática 2D ou tensor 3D (N_omega, p, m) para testes/álgebra matricial
    if isinstance(model, (np.ndarray, list, tuple)):
        arr = np.asarray(model)
        if arr.ndim == 2:
            if not (np.all(np.isfinite(arr.real)) and np.all(np.isfinite(arr.imag))):
                raise ValidationError("Matriz MIMO contém NaN ou Inf.")
            p, m = arr.shape
            G_mat = np.broadcast_to(arr.astype(np.complex128)[None, :, :], (N, p, m)).copy()
            return {
                "G": G_mat,
                "p": p,
                "m": m,
                "dt": None,
                "domain": "continuous",
                "poles": np.array([], dtype=np.complex128),
                "revision": None,
                "singular_frequencies": [],
                "warnings": [],
            }
        if arr.ndim == 3 and arr.shape[0] == N:
            p, m = arr.shape[1], arr.shape[2]
            return {
                "G": arr.astype(np.complex128),
                "p": p,
                "m": m,
                "dt": None,
                "domain": "continuous",
                "poles": np.array([], dtype=np.complex128),
                "revision": None,
                "singular_frequencies": [],
                "warnings": [],
            }

    raise UnsupportedModelError(
        message=f"Modelo MIMO não suportado: {type(model).__name__}.",
        parameters={"model_type": type(model).__name__},
        next_step="Forneça TransferFunction, StateSpace, DynamicController ou matriz 2D.",
    )


def eval_mimo_response(
    plant: Any,
    omega: Any = None,
    *,
    n_points: int = DEFAULT_N_OMEGA,
    omega_min: float | None = None,
    omega_max: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Avalia matriz de resposta em frequência MIMO G(jw) com shape (N_omega, p, m)."""
    prov = build_provenance("frequency.mimo.eval_mimo_response", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        dt = getattr(plant, "dt", None)
        w_grid, w_warns = resolve_omega_grid(
            omega,
            dt=dt,
            n_points=n_points,
            omega_min=omega_min,
            omega_max=omega_max,
        )
        warnings_out.extend(w_warns)

        eval_info = _eval_model_matrix_at_omega(plant, w_grid)
        warnings_out.extend(eval_info["warnings"])
        G_mat = eval_info["G"]
        p, m = eval_info["p"], eval_info["m"]

        if eval_info["singular_frequencies"]:
            warnings_out.append(
                WarningItem(
                    code="MIMO_POLES_ON_GRID",
                    message="Grade de frequências intercepta polo(s) sobre o eixo jw / círculo unitário.",
                    details={"singular_frequencies": eval_info["singular_frequencies"]},
                )
            )

        assumptions = {
            "domain": eval_info["domain"],
            "dt": eval_info["dt"],
            "n_outputs": p,
            "n_inputs": m,
            "is_square": p == m,
        }
        diagnostics = {
            "n_frequencies": int(w_grid.size),
            "shape": [int(w_grid.size), int(p), int(m)],
            "singular_frequencies": eval_info["singular_frequencies"],
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "omega": w_grid,
                "G": G_mat,
                "n_outputs": p,
                "n_inputs": m,
                "dt": eval_info["dt"],
                "domain": eval_info["domain"],
                "units": {"frequency": "rad/s"},
                "series_semantics": "numeric_verified",
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def singular_values(
    plant: Any,
    omega: Any = None,
    *,
    n_points: int = DEFAULT_N_OMEGA,
    omega_min: float | None = None,
    omega_max: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Calcula decomposição em valores singulares (SVD) de G(jw), sigma_max, sigma_min e condicionamento."""
    prov = build_provenance("frequency.mimo.singular_values", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        resp_res = eval_mimo_response(
            plant,
            omega,
            n_points=n_points,
            omega_min=omega_min,
            omega_max=omega_max,
            raise_on_error=True,
        )
        assert resp_res.data is not None
        warnings_out.extend(resp_res.warnings)

        w_grid = np.asarray(resp_res.data["omega"]["data"], dtype=np.float64)
        G_real = np.asarray(resp_res.data["G"]["real"], dtype=np.float64)
        G_imag = np.asarray(resp_res.data["G"]["imag"], dtype=np.float64)
        shape_3d = tuple(resp_res.data["G"]["shape"])
        G_mat = (G_real + 1j * G_imag).reshape(shape_3d)
        N, p, m = G_mat.shape
        k_sv = min(p, m)

        sv_all = np.zeros((N, k_sv), dtype=np.float64)
        cond_arr = np.zeros(N, dtype=np.float64)
        rank_deficient_freqs: list[float] = []
        eps = float(np.finfo(np.float64).eps)

        for idx in range(N):
            svals = np.linalg.svd(G_mat[idx], compute_uv=False)
            sv_all[idx, :] = svals
            s_max = float(svals[0])
            s_min = float(svals[-1])
            tol_rk = max(p, m) * eps * max(1.0, s_max)
            if s_min <= tol_rk:
                rank_deficient_freqs.append(float(w_grid[idx]))
                cond_arr[idx] = 1e16
            else:
                cond_arr[idx] = min(1e16, float(s_max / s_min))

        sigma_max = sv_all[:, 0]
        sigma_min = sv_all[:, -1]
        sigma_max_db = 20.0 * np.log10(np.maximum(sigma_max, 1e-15))
        sigma_min_db = 20.0 * np.log10(np.maximum(sigma_min, 1e-15))

        peak_idx = int(np.argmax(sigma_max))
        hinf_peak = float(sigma_max[peak_idx])
        omega_peak = float(w_grid[peak_idx])

        if rank_deficient_freqs:
            warnings_out.append(
                WarningItem(
                    code="MIMO_RANK_DEFICIENT_FREQUENCIES",
                    message=f"Matriz G(jw) é singular ou quase singular em {len(rank_deficient_freqs)} frequência(s).",
                    details={"rank_deficient_frequencies": rank_deficient_freqs[:20]},
                )
            )

        assumptions = {
            **resp_res.assumptions,
            "unitary_invariance": True,
        }
        diagnostics = {
            "n_frequencies": N,
            "hinf_norm_sample_peak": hinf_peak,
            "omega_at_peak": omega_peak,
            "min_singular_value_overall": float(np.min(sigma_min)),
            "max_condition_number": float(np.max(cond_arr)),
            "n_rank_deficient_frequencies": len(rank_deficient_freqs),
            "rank_deficient_frequencies": rank_deficient_freqs,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "omega": w_grid,
                "singular_values": sv_all,
                "sigma_max": sigma_max,
                "sigma_min": sigma_min,
                "sigma_max_db": sigma_max_db,
                "sigma_min_db": sigma_min_db,
                "condition_number": cond_arr,
                "hinf_peak": hinf_peak,
                "omega_peak": omega_peak,
                "n_outputs": p,
                "n_inputs": m,
                "units": {"frequency": "rad/s", "singular_values_db": "dB"},
                "series_semantics": "numeric_verified",
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def rga(
    plant: Any,
    omega: Any = None,
    *,
    cond_max: float = DEFAULT_RGA_COND_MAX,
    raise_on_error: bool = False,
) -> Result:
    """Calcula a Relative Gain Array (RGA) Lambda(w) = G(w) o (G(w)^{-1})^T exclusivamente para G quadrada e não singular.

    Regras científicas e normativas (Seção 5.5, 10.2, T-MIMO-01, T-MIMO-02):
    - Exclusivamente para `G` quadrada (`p == m`). Se `p != m`, falha com `DIMENSION_MISMATCH` e
      `rga_status='undefined'`.
    - Se `G(jw)` for singular ou mal condicionada (ex.: singularidade DC em `omega=0`, `T-MIMO-02`),
      NÃO aplica inversão ingênua nem regra de soma 1: marca a frequência como `'undefined'` com diagnóstico
      explícito (`singular_frequencies`, `undefined_frequencies`, `rga_status='undefined'`).
    """
    prov = build_provenance("frequency.mimo.rga", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {"rga_status": "undefined"}
    warnings_out: list[WarningItem] = []

    try:
        if omega is None:
            w_grid = np.array([0.0], dtype=np.float64)
        else:
            w_arr = ensure_finite_float64(omega, name="omega")
            w_grid = w_arr.reshape((1,)) if w_arr.ndim == 0 else w_arr.ravel()
            if w_grid.size < 1 or np.any(w_grid < 0.0):
                raise ValidationError("Frequências em omega para RGA devem ser não-negativas.")

        eval_info = _eval_model_matrix_at_omega(plant, w_grid)
        warnings_out.extend(eval_info["warnings"])
        G_mat = eval_info["G"]
        p, m = eval_info["p"], eval_info["m"]
        N = w_grid.shape[0]

        if p != m:
            diagnostics = {
                "rga_status": "undefined",
                "reason": "non_square_plant",
                "n_outputs": p,
                "n_inputs": m,
            }
            raise DimensionMismatchError(
                message=(
                    f"RGA clássica Lambda(G) = G o (G^-1)^T é definida exclusivamente para matriz G quadrada "
                    f"(p == m); recebido ({p}x{m})."
                ),
                parameters={"n_outputs": p, "n_inputs": m, "rga_status": "undefined"},
                next_step="Selecione um subsistema quadrado (p == m) ou utilize singular_values().",
            )

        eps = float(np.finfo(np.float64).eps)
        rga_entries: list[dict[str, Any]] = []
        valid_rga_list: list[np.ndarray] = []
        undefined_frequencies: list[float] = []
        max_row_sum_err = 0.0
        max_col_sum_err = 0.0
        max_cond = 0.0

        for idx in range(N):
            w_val = float(w_grid[idx])
            G_k = G_mat[idx]
            svals = np.linalg.svd(G_k, compute_uv=False)
            s_max = float(svals[0]) if svals.size > 0 else 0.0
            s_min = float(svals[-1]) if svals.size > 0 else 0.0
            tol_sing = max(p, 1) * eps * max(1.0, s_max)

            is_singular = (
                (w_val in eval_info["singular_frequencies"])
                or s_max == 0.0
                or s_min <= tol_sing
                or (s_max / s_min) > float(cond_max)
            )
            if is_singular:
                undefined_frequencies.append(w_val)
                cond_k = float(s_max / s_min) if (s_min > 0.0 and math.isfinite(s_max / s_min)) else None
                rga_entries.append(
                    {
                        "omega": w_val,
                        "status": "undefined",
                        "reason": "singular_or_ill_conditioned_matrix",
                        "sigma_min": s_min,
                        "sigma_max": s_max,
                        "condition_number": cond_k,
                        "rga_matrix": None,
                        "row_sums": None,
                        "col_sums": None,
                    }
                )
                continue

            cond_k = float(s_max / s_min)
            max_cond = max(max_cond, cond_k)
            # Evitar inv explícita: resolver G_k * X = I via np.linalg.solve
            eye_p = np.eye(p, dtype=np.complex128)
            G_inv_k = np.linalg.solve(G_k, eye_p)
            Lambda_k = G_k * (G_inv_k.T)

            row_sums = np.sum(Lambda_k, axis=1)
            col_sums = np.sum(Lambda_k, axis=0)
            row_err = float(np.max(np.abs(row_sums - 1.0)))
            col_err = float(np.max(np.abs(col_sums - 1.0)))
            max_row_sum_err = max(max_row_sum_err, row_err)
            max_col_sum_err = max(max_col_sum_err, col_err)

            if cond_k > 1e6:
                warnings_out.append(
                    WarningItem(
                        code="RGA_HIGH_CONDITION_NUMBER",
                        message=f"Matriz G(jw) mal condicionada em w={w_val:.4g} rad/s (kappa={cond_k:.3e}).",
                        details={"omega": w_val, "condition_number": cond_k},
                    )
                )

            valid_rga_list.append(Lambda_k)
            rga_entries.append(
                {
                    "omega": w_val,
                    "status": "defined",
                    "sigma_min": s_min,
                    "sigma_max": s_max,
                    "condition_number": cond_k,
                    "rga_matrix": Lambda_k,
                    "rga_magnitude": np.abs(Lambda_k),
                    "row_sums": complex_to_pair(row_sums),
                    "col_sums": complex_to_pair(col_sums),
                    "row_sum_error": row_err,
                    "col_sum_error": col_err,
                }
            )

        all_undefined = len(undefined_frequencies) == N
        partial_undefined = 0 < len(undefined_frequencies) < N

        if undefined_frequencies:
            warnings_out.append(
                WarningItem(
                    code="RGA_UNDEFINED_AT_SINGULAR_FREQUENCIES",
                    message=(
                        f"RGA indefinida ('undefined') em {len(undefined_frequencies)} de {N} frequência(s) "
                        f"por singularidade matricial (ex.: w={undefined_frequencies[0]:.4g} rad/s)."
                    ),
                    details={
                        "undefined_frequencies": undefined_frequencies,
                        "rga_status": "undefined" if all_undefined else "partially_defined",
                    },
                )
            )

        rga_status = "undefined" if all_undefined else ("partially_defined" if partial_undefined else "defined")

        # Sugestão de pareamento diagonal quando definida na primeira frequência válida
        pairing_recommendation: list[dict[str, Any]] | None = None
        for entry in rga_entries:
            if entry["status"] == "defined":
                lam_mat = entry["rga_matrix"]
                lam_real = (
                    np.asarray(lam_mat.real, dtype=np.float64)
                    if isinstance(lam_mat, np.ndarray)
                    else np.asarray(lam_mat["real"], dtype=np.float64).reshape((p, p))
                )
                pairing_recommendation = [
                    {
                        "output": i,
                        "recommended_input": int(np.argmin(np.abs(lam_real[i, :] - 1.0))),
                        "rga_element_real": float(lam_real[i, int(np.argmin(np.abs(lam_real[i, :] - 1.0)))]),
                        "diagonal_rga_real": float(lam_real[i, i]),
                    }
                    for i in range(p)
                ]
                break

        assumptions = {
            "is_square": True,
            "n_channels": p,
            "invertible_at_all_frequencies": len(undefined_frequencies) == 0,
            "cond_max_threshold": float(cond_max),
        }
        diagnostics = {
            "rga_status": rga_status,
            "n_frequencies": N,
            "n_defined": N - len(undefined_frequencies),
            "n_undefined": len(undefined_frequencies),
            "undefined_frequencies": undefined_frequencies,
            "max_row_sum_error": max_row_sum_err if valid_rga_list else None,
            "max_col_sum_error": max_col_sum_err if valid_rga_list else None,
            "max_condition_number": max_cond if valid_rga_list else None,
        }

        res_status = "inconclusive" if all_undefined else ("warning" if warnings_out else "success")
        return Result(
            status=res_status,
            data={
                "rga_status": rga_status,
                "omega": w_grid,
                "entries": rga_entries,
                "undefined_frequencies": undefined_frequencies,
                "pairing_analysis": pairing_recommendation,
                "n_outputs": p,
                "n_inputs": m,
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def sensitivity(
    plant: Any,
    controller: Any = None,
    omega: Any = None,
    *,
    feedback_sign: str = "negative",
    n_points: int = DEFAULT_N_OMEGA,
    omega_min: float | None = None,
    omega_max: float | None = None,
    base_tol: float = 1e-12,
    raise_on_error: bool = False,
) -> Result:
    """Calcula funções de sensibilidade MIMO de saída (S, T, KS) e de entrada (S_i, T_i) verificando S + T = I.

    Para `feedback_sign='negative'`:
    - Malha de saída: $L_o = G K$, $S_o = (I + L_o)^{-1}$, $T_o = L_o (I + L_o)^{-1}$, $K S_o = K (I + L_o)^{-1}$
    - Malha de entrada: $L_i = K G$, $S_i = (I + L_i)^{-1}$, $T_i = L_i (I + L_i)^{-1}$
    - Identidade algébrica verificada com tolerância escalonada por $\\kappa(I + L(j\\omega))$ (Seção 10.2).
    """
    prov = build_provenance("frequency.mimo.sensitivity", model_revision=getattr(plant, "revision", None))
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sign_str = _validate_feedback_sign(feedback_sign)
        dt_p = getattr(plant, "dt", None)
        if controller is not None:
            dt_c = getattr(controller, "dt", None)
            if dt_p is not None and dt_c is not None:
                check_dt_compatible(dt_p, dt_c, label_a="plant", label_b="controller")

        w_grid, w_warns = resolve_omega_grid(
            omega,
            dt=dt_p,
            n_points=n_points,
            omega_min=omega_min,
            omega_max=omega_max,
        )
        warnings_out.extend(w_warns)
        N = w_grid.shape[0]

        g_info = _eval_model_matrix_at_omega(plant, w_grid)
        warnings_out.extend(g_info["warnings"])
        G_mat = g_info["G"]
        p, m = g_info["p"], g_info["m"]

        if controller is None:
            if p != m:
                raise DimensionMismatchError(
                    message=(
                        f"Realimentação unitária (controller=None) requer planta quadrada (p == m), "
                        f"recebido ({p}x{m})."
                    ),
                    parameters={"n_outputs": p, "n_inputs": m},
                    next_step="Forneça um controlador K com shape (m, p) ou uma planta quadrada.",
                )
            K_mat = np.broadcast_to(np.eye(m, dtype=np.complex128)[None, :, :], (N, m, p)).copy()
        else:
            k_info = _eval_model_matrix_at_omega(controller, w_grid)
            warnings_out.extend(k_info["warnings"])
            K_mat = k_info["G"]
            pk, mk = k_info["p"], k_info["m"]
            if (pk, mk) != (m, p):
                raise DimensionMismatchError(
                    message=(
                        f"Dimensões incompatíveis entre planta G ({p}x{m}) e controlador K ({pk}x{mk}); "
                        f"esperado K com shape ({m}, {p})."
                    ),
                    parameters={"G_shape": [p, m], "K_shape": [pk, mk]},
                )

        s_mult = 1.0 if sign_str == "negative" else -1.0
        eye_p = np.eye(p, dtype=np.complex128)
        eye_m = np.eye(m, dtype=np.complex128)
        eps = float(np.finfo(np.float64).eps)

        S_out = np.zeros((N, p, p), dtype=np.complex128)
        T_out = np.zeros((N, p, p), dtype=np.complex128)
        KS_out = np.zeros((N, m, p), dtype=np.complex128)
        S_in = np.zeros((N, m, m), dtype=np.complex128)
        T_in = np.zeros((N, m, m), dtype=np.complex128)

        sigma_max_S = np.zeros(N, dtype=np.float64)
        sigma_max_T = np.zeros(N, dtype=np.float64)
        sigma_max_KS = np.zeros(N, dtype=np.float64)
        sigma_max_Si = np.zeros(N, dtype=np.float64)
        sigma_max_Ti = np.zeros(N, dtype=np.float64)

        cond_return_diff = np.zeros(N, dtype=np.float64)
        identity_residuals = np.zeros(N, dtype=np.float64)
        scaled_tolerances = np.zeros(N, dtype=np.float64)
        input_identity_residuals = np.zeros(N, dtype=np.float64)

        for idx in range(N):
            Gk = G_mat[idx]
            Kk = K_mat[idx]
            Lo_k = s_mult * (Gk @ Kk)
            Li_k = s_mult * (Kk @ Gk)

            M_out = eye_p + Lo_k
            svals_out = np.linalg.svd(M_out, compute_uv=False)
            if svals_out[-1] <= p * eps * max(1.0, float(svals_out[0])):
                raise HypothesisViolatedError(
                    message=f"Matriz de retorno (I + L_o(jw)) é singular em w={float(w_grid[idx]):.4g} rad/s.",
                    parameters={"omega": float(w_grid[idx]), "sigma_min": float(svals_out[-1])},
                )
            cond_k = float(svals_out[0] / svals_out[-1])
            cond_return_diff[idx] = cond_k

            So_k = np.linalg.solve(M_out, eye_p)
            To_k = Lo_k @ So_k
            KSo_k = Kk @ So_k

            M_in = eye_m + Li_k
            Si_k = np.linalg.solve(M_in, eye_m)
            Ti_k = Li_k @ Si_k

            S_out[idx] = So_k
            T_out[idx] = To_k
            KS_out[idx] = KSo_k
            S_in[idx] = Si_k
            T_in[idx] = Ti_k

            sigma_max_S[idx] = float(np.linalg.svd(So_k, compute_uv=False)[0])
            sigma_max_T[idx] = float(np.linalg.svd(To_k, compute_uv=False)[0])
            sigma_max_KS[idx] = float(np.linalg.svd(KSo_k, compute_uv=False)[0])
            sigma_max_Si[idx] = float(np.linalg.svd(Si_k, compute_uv=False)[0])
            sigma_max_Ti[idx] = float(np.linalg.svd(Ti_k, compute_uv=False)[0])

            # Verificação S(jw) + T(jw) = I com tolerância escalonada por kappa(I + L) (Seção 10.2)
            res_out = float(np.linalg.norm((So_k + To_k) - eye_p, "fro"))
            tol_k = float(base_tol) * max(1.0, cond_k) * math.sqrt(p)
            identity_residuals[idx] = res_out
            scaled_tolerances[idx] = tol_k

            res_in = float(np.linalg.norm((Si_k + Ti_k) - eye_m, "fro"))
            input_identity_residuals[idx] = res_in

        identity_verified = bool(np.all(identity_residuals <= scaled_tolerances))
        Ms_peak = float(np.max(sigma_max_S))
        Mt_peak = float(np.max(sigma_max_T))
        Mks_peak = float(np.max(sigma_max_KS))

        if Ms_peak > 2.0:
            warnings_out.append(
                WarningItem(
                    code="HIGH_SENSITIVITY_PEAK",
                    message=f"Pico de sensibilidade elevado: ||S||_inf = {Ms_peak:.3f} (> 2.0).",
                    details={"Ms_peak": Ms_peak, "Mt_peak": Mt_peak},
                )
            )

        assumptions = {
            "feedback_sign": sign_str,
            "domain": g_info["domain"],
            "dt": g_info["dt"],
            "output_loop_transfer": "L_o = G K",
            "input_loop_transfer": "L_i = K G",
        }
        diagnostics = {
            "identity_S_plus_T_verified": identity_verified,
            "max_identity_residual": float(np.max(identity_residuals)),
            "max_input_identity_residual": float(np.max(input_identity_residuals)),
            "max_scaled_tolerance": float(np.max(scaled_tolerances)),
            "max_cond_I_plus_L": float(np.max(cond_return_diff)),
            "Ms_peak": Ms_peak,
            "Mt_peak": Mt_peak,
            "Mks_peak": Mks_peak,
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "omega": w_grid,
                "S": S_out,
                "T": T_out,
                "KS": KS_out,
                "S_input": S_in,
                "T_input": T_in,
                "sigma_max_S": sigma_max_S,
                "sigma_max_T": sigma_max_T,
                "sigma_max_KS": sigma_max_KS,
                "sigma_max_S_input": sigma_max_Si,
                "sigma_max_T_input": sigma_max_Ti,
                "cond_I_plus_L": cond_return_diff,
                "identity_residuals": identity_residuals,
                "scaled_tolerances": scaled_tolerances,
                "identity_verified": identity_verified,
                "Ms_peak": Ms_peak,
                "Mt_peak": Mt_peak,
                "Mks_peak": Mks_peak,
                "units": {"frequency": "rad/s"},
                "series_semantics": "numeric_verified",
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def nyquist_generalized(
    plant: Any,
    controller: Any = None,
    omega: Any = None,
    *,
    feedback_sign: str = "negative",
    n_points: int = 1000,
    omega_min: float | None = None,
    omega_max: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Calcula o diagrama de Nyquist multivariável generalizado det(I + L(jw)) e trajetórias de autovalores (Seção 5.5).

    Observação normativa (Seção 5.5 e 13.5):
    - Classificado com `maturity='beta'`.
    - Conta explicitamente polos instáveis de malha aberta ($P$) e verifica a presença de polos sobre
      o eixo imaginário/fronteira antes de emitir diagnóstico do princípio do argumento ($Z = N + P$).
    """
    prov = build_provenance(
        "frequency.mimo.nyquist_generalized",
        model_revision=getattr(plant, "revision", None),
        maturity="beta",
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sign_str = _validate_feedback_sign(feedback_sign)
        dt_p = getattr(plant, "dt", None)
        w_grid, w_warns = resolve_omega_grid(
            omega,
            dt=dt_p,
            n_points=max(200, int(n_points)),
            omega_min=omega_min,
            omega_max=omega_max,
        )
        warnings_out.extend(w_warns)
        N = w_grid.shape[0]

        g_info = _eval_model_matrix_at_omega(plant, w_grid)
        warnings_out.extend(g_info["warnings"])
        G_mat = g_info["G"]
        p, m = g_info["p"], g_info["m"]
        open_poles = list(g_info["poles"])

        if controller is None:
            if p != m:
                raise DimensionMismatchError(
                    f"nyquist_generalized sem controlador exige G quadrada (p == m), recebido ({p}x{m})."
                )
            K_mat = np.broadcast_to(np.eye(m, dtype=np.complex128)[None, :, :], (N, m, p)).copy()
        else:
            k_info = _eval_model_matrix_at_omega(controller, w_grid)
            warnings_out.extend(k_info["warnings"])
            K_mat = k_info["G"]
            if (k_info["p"], k_info["m"]) != (m, p):
                raise DimensionMismatchError(
                    f"Dimensões incompatíveis entre G ({p}x{m}) e K ({k_info['p']}x{k_info['m']})."
                )
            open_poles.extend(k_info["poles"])

        poles_arr = np.asarray(open_poles, dtype=np.complex128)
        domain = g_info["domain"]
        if domain == "continuous":
            n_unstable_open = int(np.sum(np.real(poles_arr) > 1e-9)) if poles_arr.size > 0 else 0
            n_boundary_open = int(np.sum(np.abs(np.real(poles_arr)) <= 1e-9)) if poles_arr.size > 0 else 0
        else:
            n_unstable_open = int(np.sum(np.abs(poles_arr) > 1.0 + 1e-9)) if poles_arr.size > 0 else 0
            n_boundary_open = int(np.sum(np.abs(np.abs(poles_arr) - 1.0) <= 1e-9)) if poles_arr.size > 0 else 0

        s_mult = 1.0 if sign_str == "negative" else -1.0
        eye_p = np.eye(p, dtype=np.complex128)
        det_pos = np.zeros(N, dtype=np.complex128)
        eig_loci = np.zeros((N, p), dtype=np.complex128)

        for idx in range(N):
            Lo_k = s_mult * (G_mat[idx] @ K_mat[idx])
            det_pos[idx] = complex(np.linalg.det(eye_p + Lo_k))
            eig_loci[idx, :] = sort_complex_roots(np.linalg.eigvals(Lo_k))

        min_dist_origin = float(np.min(np.abs(det_pos)))
        has_contour_singularity = bool(
            n_boundary_open > 0
            or len(g_info["singular_frequencies"]) > 0
            or min_dist_origin <= 1e-10
        )

        # Variação de fase no contorno fechado (w: 0 -> +w_max -> -w_max -> 0)
        angles_pos = np.unwrap(np.angle(det_pos))
        delta_phase_pos = float(angles_pos[-1] - angles_pos[0])
        total_phase_change = 2.0 * delta_phase_pos
        # Número líquido de voltas horárias em torno da origem (convenção N = -Delta_arg / (2*pi))
        cw_encirclements = int(round(-total_phase_change / (2.0 * math.pi)))

        if has_contour_singularity:
            warnings_out.append(
                WarningItem(
                    code="NYQUIST_POLES_ON_IMAGINARY_AXIS",
                    message=(
                        "Existem polos de malha aberta sobre o eixo imaginário/fronteira ou singularidades no contorno; "
                        "contagem de encirclements sem indentação analítica é inconclusiva (Seção 5.5)."
                    ),
                    details={
                        "n_boundary_poles": n_boundary_open,
                        "min_abs_det_I_plus_L": min_dist_origin,
                    },
                )
            )
            stability_verdict = "inconclusive_boundary_poles"
            estimated_unstable_cl = None
        else:
            estimated_unstable_cl = cw_encirclements + n_unstable_open
            stability_verdict = (
                "stable_under_nyquist_criterion"
                if estimated_unstable_cl == 0
                else "unstable_under_nyquist_criterion"
            )

        assumptions = {
            "feedback_sign": sign_str,
            "domain": domain,
            "dt": g_info["dt"],
            "maturity": "beta",
            "open_loop_unstable_poles_counted": True,
            "boundary_poles_checked": True,
        }
        diagnostics = {
            "maturity": "beta",
            "n_open_loop_unstable_poles": n_unstable_open,
            "n_open_loop_boundary_poles": n_boundary_open,
            "cw_encirclements_of_origin": cw_encirclements,
            "estimated_closed_loop_unstable_poles": estimated_unstable_cl,
            "min_abs_det_I_plus_L": min_dist_origin,
            "stability_verdict": stability_verdict,
        }

        res_status = "inconclusive" if has_contour_singularity else ("warning" if warnings_out else "success")
        return Result(
            status=res_status,
            data={
                "omega": w_grid,
                "det_I_plus_L_positive": complex_to_pair(det_pos),
                "det_I_plus_L_negative": complex_to_pair(np.conj(det_pos[::-1])),
                "characteristic_loci": eig_loci,
                "n_open_loop_unstable_poles": n_unstable_open,
                "n_open_loop_boundary_poles": n_boundary_open,
                "cw_encirclements_of_origin": cw_encirclements,
                "estimated_closed_loop_unstable_poles": estimated_unstable_cl,
                "min_abs_det_I_plus_L": min_dist_origin,
                "stability_verdict": stability_verdict,
                "maturity": "beta",
                "series_semantics": "approximate" if has_contour_singularity else "numeric_verified",
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )
