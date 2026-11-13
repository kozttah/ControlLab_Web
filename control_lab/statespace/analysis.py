"""Análise estrutural LTI: PBH, posto de controlabilidade/observabilidade via SVD e gramianos."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from control_lab.core.tensors import complex_to_pair
from control_lab.diagnostics import (
    ControlLabError,
    HypothesisViolatedError,
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from ._utils import (
    DEFAULT_COND_WARN_THRESHOLD,
    DEFAULT_STAB_TOL,
    handle_failure,
    pbh_analysis_core,
    resolve_state_space_inputs,
    safe_svd_metrics,
    sort_complex_eigs,
)
from .equations import solve_lyapunov


def _build_power_hankel_block(
    A: np.ndarray,
    M: np.ndarray,
    *,
    mode: str,
) -> tuple[np.ndarray | None, list[WarningItem]]:
    """Constrói matriz de controlabilidade [B, AB, ...] ou observabilidade [C; CA; ...] evitando overflow."""
    n = A.shape[0]
    if n == 0:
        return np.zeros((0, M.shape[1] if mode == "ctrb" else 0), dtype=np.float64), []

    blocks: list[np.ndarray] = []
    cur = np.array(M, dtype=np.float64, copy=True)
    for k in range(n):
        if not np.all(np.isfinite(cur)) or float(np.max(np.abs(cur))) > 1e150:
            return None, [
                WarningItem(
                    code=f"{'CONTROLLABILITY' if mode == 'ctrb' else 'OBSERVABILITY'}_MATRIX_OVERFLOW",
                    message=(
                        f"Matriz de {'controlabilidade' if mode == 'ctrb' else 'observabilidade'} "
                        f"excedeu limite numérico seguro no passo k={k}; usando PBH como critério autoritativo."
                    ),
                    details={"step_k": k},
                )
            ]
        blocks.append(cur)
        if k + 1 < n:
            cur = (A @ cur) if mode == "ctrb" else (cur @ A)

    mat = np.hstack(blocks) if mode == "ctrb" else np.vstack(blocks)
    return mat, []


def check_pbh(
    plant_or_A: Any,
    B: Any = None,
    C: Any = None,
    *,
    dt: float | None = None,
    tol: float | None = None,
    stab_tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Executa teste Popov-Belevitch-Hautus (PBH) via SVD para (A, B) e/ou (A, C)."""
    dt_provided = dt is not None
    prov: Provenance = build_provenance(
        "statespace.check_pbh",
        model_revision=getattr(plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sys_info = resolve_state_space_inputs(
            plant_or_A,
            B=B,
            C=C,
            dt=dt,
            dt_provided=dt_provided,
            require_nonempty_states=False,
        )
        A_arr: np.ndarray = sys_info["A"]
        B_arr: np.ndarray | None = sys_info["B"]
        C_arr: np.ndarray | None = sys_info["C"]
        resolved_dt: float | None = sys_info["dt"]
        n: int = sys_info["n"]

        if B_arr is None and C_arr is None:
            raise ValidationError(
                message="check_pbh requer StateSpace ou ao menos uma das matrizes B ou C.",
                next_step="Passe um StateSpace completo ou forneça B e/ou C.",
            )

        pbh = pbh_analysis_core(A_arr, B=B_arr, C=C_arr, dt=resolved_dt, tol=tol, stab_tol=stab_tol)
        warnings_out.extend(pbh["warnings"])

        domain = "continuous" if resolved_dt is None else "discrete"
        data: dict[str, Any] = {
            "open_loop_poles": complex_to_pair(pbh["open_loop_poles"]),
        }
        assumptions = {
            "domain": domain,
            "dt": resolved_dt,
            "n_states": n,
        }
        diagnostics = {
            "stab_tol": pbh.get("stab_tol"),
        }

        if B_arr is not None:
            data.update(
                {
                    "controllable": bool(pbh["controllable"]),
                    "stabilizable": bool(pbh["stabilizable"]),
                    "uncontrollable_modes": complex_to_pair(np.asarray(pbh["uncontrollable_modes"])),
                    "unstabilizable_modes": complex_to_pair(np.asarray(pbh["unstabilizable_modes"])),
                }
            )
            assumptions["controllable"] = bool(pbh["controllable"])
            assumptions["stabilizable"] = bool(pbh["stabilizable"])
            diagnostics["min_sv_controllability"] = pbh["min_sv_controllability"]
            diagnostics["min_sv_stabilizability"] = pbh["min_sv_stabilizability"]

        if C_arr is not None:
            data.update(
                {
                    "observable": bool(pbh["observable"]),
                    "detectable": bool(pbh["detectable"]),
                    "unobservable_modes": complex_to_pair(np.asarray(pbh["unobservable_modes"])),
                    "undetectable_modes": complex_to_pair(np.asarray(pbh["undetectable_modes"])),
                }
            )
            assumptions["observable"] = bool(pbh["observable"])
            assumptions["detectable"] = bool(pbh["detectable"])
            diagnostics["min_sv_observability"] = pbh["min_sv_observability"]
            diagnostics["min_sv_detectability"] = pbh["min_sv_detectability"]

        prov_ok = build_provenance(
            "statespace.check_pbh",
            tolerances={"tol": tol, "stab_tol": pbh.get("stab_tol")},
            model_revision=sys_info["model_revision"],
        )
        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov_ok,
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


def gramians(
    plant_or_A: Any,
    B: Any = None,
    C: Any = None,
    *,
    kind: str = "both",
    dt: float | None = None,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Calcula gramianos de controlabilidade (Wc) e observabilidade (Wo) via Lyapunov quando estável."""
    dt_provided = dt is not None
    prov: Provenance = build_provenance(
        "statespace.gramians",
        model_revision=getattr(plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        norm_kind = kind.lower() if isinstance(kind, str) else ""
        if norm_kind in ("both", "all"):
            want_c, want_o = True, True
        elif norm_kind in ("controllability", "c", "wc"):
            want_c, want_o = True, False
        elif norm_kind in ("observability", "o", "wo"):
            want_c, want_o = False, True
        else:
            raise ValidationError(
                f"kind inválido em gramians: {kind!r}. Use 'both', 'controllability' ou 'observability'."
            )

        sys_info = resolve_state_space_inputs(
            plant_or_A,
            B=B,
            C=C,
            dt=dt,
            dt_provided=dt_provided,
            require_nonempty_states=True,
        )
        A_arr: np.ndarray = sys_info["A"]
        B_arr: np.ndarray | None = sys_info["B"]
        C_arr: np.ndarray | None = sys_info["C"]
        resolved_dt: float | None = sys_info["dt"]
        n: int = sys_info["n"]
        domain = "continuous" if resolved_dt is None else "discrete"

        if want_c and B_arr is None:
            raise ValidationError("Matriz B é obrigatória para o gramiano de controlabilidade Wc.")
        if want_o and C_arr is None:
            raise ValidationError("Matriz C é obrigatória para o gramiano de observabilidade Wo.")

        eigs = np.linalg.eigvals(A_arr)
        norm_A = float(np.linalg.norm(A_arr, "fro"))
        stab_tol = max(DEFAULT_STAB_TOL, 1e-12 * norm_A)

        if domain == "continuous":
            max_real = float(np.max(np.real(eigs)))
            is_asymp_stable = max_real < -stab_tol
            metric_desc = f"max Re(eig(A))={max_real:.3e} >= -{stab_tol:.1e}"
        else:
            rho = float(np.max(np.abs(eigs)))
            is_asymp_stable = rho < 1.0 - stab_tol
            metric_desc = f"rho(A)={rho:.6f} >= {1.0 - stab_tol:.6f}"

        assumptions = {
            "domain": domain,
            "dt": resolved_dt,
            "asymptotically_stable": is_asymp_stable,
            "kind": norm_kind,
            "n_states": n,
        }

        if not is_asymp_stable:
            raise HypothesisViolatedError(
                message=(
                    f"Gramianos infinitos não existem: sistema não é assintoticamente estável ({metric_desc})."
                ),
                parameters={"domain": domain, "asymptotically_stable": False},
                next_step="Estabilize o sistema em malha fechada antes de calcular gramianos infinitos.",
            )

        data: dict[str, Any] = {}
        Wc: np.ndarray | None = None
        Wo: np.ndarray | None = None

        if want_c and B_arr is not None:
            res_wc = solve_lyapunov(
                A_arr,
                B_arr @ B_arr.T,
                domain=domain,
                tol=tol,
                raise_on_error=True,
            )
            assert res_wc.data is not None
            from control_lab.core.tensors import tensor_to_array

            Wc = tensor_to_array(res_wc.data["X"], expected_ndim=2, dtype="float64")
            data["Wc"] = Wc
            diagnostics["Wc_residual_rel"] = res_wc.diagnostics["residual_rel"]
            diagnostics["Wc_symmetry_error"] = res_wc.diagnostics["symmetry_error"]
            warnings_out.extend(
                w if isinstance(w, WarningItem) else WarningItem(code="WC_WARN", message=str(w))
                for w in res_wc.warnings
            )

        if want_o and C_arr is not None:
            res_wo = solve_lyapunov(
                A_arr.T,
                C_arr.T @ C_arr,
                domain=domain,
                tol=tol,
                raise_on_error=True,
            )
            assert res_wo.data is not None
            from control_lab.core.tensors import tensor_to_array

            Wo = tensor_to_array(res_wo.data["X"], expected_ndim=2, dtype="float64")
            data["Wo"] = Wo
            diagnostics["Wo_residual_rel"] = res_wo.diagnostics["residual_rel"]
            diagnostics["Wo_symmetry_error"] = res_wo.diagnostics["symmetry_error"]
            warnings_out.extend(
                w if isinstance(w, WarningItem) else WarningItem(code="WO_WARN", message=str(w))
                for w in res_wo.warnings
            )

        if Wc is not None and Wo is not None:
            prod_eigs = np.linalg.eigvals(Wc @ Wo)
            real_parts = np.real(prod_eigs)
            scale_p = max(1.0, float(np.max(np.abs(real_parts)))) if real_parts.size else 1.0
            if float(np.min(real_parts)) < -1e-8 * scale_p:
                warnings_out.append(
                    WarningItem(
                        code="GRAMIAN_PRODUCT_NEGATIVE_EIG",
                        message="Produto Wc @ Wo apresentou autovalor negativo além do ruído numérico.",
                        details={"min_real_eig": float(np.min(real_parts))},
                    )
                )
            hsv = np.sort(np.sqrt(np.maximum(real_parts, 0.0)))[::-1]
            data["hankel_singular_values"] = hsv

        prov_ok = build_provenance(
            "statespace.gramians",
            tolerances={"stab_tol": stab_tol},
            model_revision=sys_info["model_revision"],
        )
        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov_ok,
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


def analyze(
    plant_or_A: Any,
    B: Any = None,
    C: Any = None,
    D: Any = None,
    *,
    dt: float | None = None,
    tol: float | None = None,
    stab_tol: float | None = None,
    compute_gramians: bool = True,
    raise_on_error: bool = False,
) -> Result:
    """Análise estrutural completa de sistema LTI: polos, estabilidade, PBH, SVD e gramianos."""
    dt_provided = dt is not None
    prov: Provenance = build_provenance(
        "statespace.analyze",
        model_revision=getattr(plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sys_info = resolve_state_space_inputs(
            plant_or_A,
            B=B,
            C=C,
            D=D,
            dt=dt,
            dt_provided=dt_provided,
            require_nonempty_states=False,
        )
        A_arr: np.ndarray = sys_info["A"]
        B_arr: np.ndarray | None = sys_info["B"]
        C_arr: np.ndarray | None = sys_info["C"]
        resolved_dt: float | None = sys_info["dt"]
        n: int = sys_info["n"]
        m: int = sys_info["m"]
        p: int = sys_info["p"]
        domain = "continuous" if resolved_dt is None else "discrete"

        eigs = sort_complex_eigs(np.linalg.eigvals(A_arr)) if n > 0 else np.array([], dtype=np.complex128)
        norm_A = float(np.linalg.norm(A_arr, "fro")) if n > 0 else 0.0
        resolved_stab_tol = stab_tol if stab_tol is not None else max(DEFAULT_STAB_TOL, 1e-12 * norm_A)

        if n == 0:
            is_asymp_stable = True
            is_unstable = False
            is_marginal = False
            max_real = None
            rho = None
        elif domain == "continuous":
            max_real = float(np.max(np.real(eigs)))
            rho = None
            is_asymp_stable = max_real < -resolved_stab_tol
            is_unstable = max_real > resolved_stab_tol
            is_marginal = not is_asymp_stable and not is_unstable
        else:
            rho = float(np.max(np.abs(eigs)))
            max_real = None
            is_asymp_stable = rho < 1.0 - resolved_stab_tol
            is_unstable = rho > 1.0 + resolved_stab_tol
            is_marginal = not is_asymp_stable and not is_unstable

        pbh = pbh_analysis_core(A_arr, B=B_arr, C=C_arr, dt=resolved_dt, tol=tol, stab_tol=resolved_stab_tol)
        warnings_out.extend(pbh["warnings"])

        data: dict[str, Any] = {
            "domain": domain,
            "dt": resolved_dt,
            "n_states": n,
            "n_inputs": m,
            "n_outputs": p,
            "open_loop_poles": complex_to_pair(eigs),
            "asymptotically_stable": is_asymp_stable,
            "marginally_stable": is_marginal,
            "unstable": is_unstable,
        }
        assumptions = {
            "domain": domain,
            "dt": resolved_dt,
            "n_states": n,
            "asymptotically_stable": is_asymp_stable,
            "gramians_well_defined": bool(is_asymp_stable and n > 0 and (B_arr is not None or C_arr is not None)),
        }
        diagnostics = {
            "stab_tol": resolved_stab_tol,
            "max_real_pole": max_real,
            "spectral_radius": rho,
        }

        if B_arr is not None:
            data["controllable"] = bool(pbh["controllable"])
            data["stabilizable"] = bool(pbh["stabilizable"])
            data["uncontrollable_modes"] = complex_to_pair(np.asarray(pbh["uncontrollable_modes"]))
            data["unstabilizable_modes"] = complex_to_pair(np.asarray(pbh["unstabilizable_modes"]))
            assumptions["controllable"] = bool(pbh["controllable"])
            assumptions["stabilizable"] = bool(pbh["stabilizable"])
            diagnostics["pbh_min_sv_controllability"] = pbh["min_sv_controllability"]
            diagnostics["pbh_min_sv_stabilizability"] = pbh["min_sv_stabilizability"]

            ctrb_mat, ctrb_warns = _build_power_hankel_block(A_arr, B_arr, mode="ctrb")
            warnings_out.extend(ctrb_warns)
            if ctrb_mat is not None and n > 0:
                svd_c = safe_svd_metrics(ctrb_mat)
                diagnostics["ctrb_rank"] = svd_c["rank"]
                diagnostics["ctrb_min_sv"] = svd_c["s_min"]
                diagnostics["ctrb_cond"] = svd_c["cond"]
                if svd_c["cond"] is not None and svd_c["cond"] > DEFAULT_COND_WARN_THRESHOLD:
                    warnings_out.append(
                        WarningItem(
                            code="ILL_CONDITIONED_CONTROLLABILITY_MATRIX",
                            message=f"Matriz de controlabilidade mal condicionada (cond={svd_c['cond']:.3e}).",
                            details={"ctrb_cond": svd_c["cond"]},
                        )
                    )
                if (svd_c["rank"] == n) != bool(pbh["controllable"]):
                    warnings_out.append(
                        WarningItem(
                            code="CTRB_RANK_PBH_DISCREPANCY",
                            message=(
                                f"Posto SVD da matriz de controlabilidade ({svd_c['rank']}/{n}) diverge do "
                                f"teste PBH (controllable={pbh['controllable']}); PBH é numericamente mais confiável."
                            ),
                            details={"ctrb_rank": svd_c["rank"], "pbh_controllable": bool(pbh["controllable"])},
                        )
                    )
            elif n == 0:
                diagnostics["ctrb_rank"] = 0

        if C_arr is not None:
            data["observable"] = bool(pbh["observable"])
            data["detectable"] = bool(pbh["detectable"])
            data["unobservable_modes"] = complex_to_pair(np.asarray(pbh["unobservable_modes"]))
            data["undetectable_modes"] = complex_to_pair(np.asarray(pbh["undetectable_modes"]))
            assumptions["observable"] = bool(pbh["observable"])
            assumptions["detectable"] = bool(pbh["detectable"])
            diagnostics["pbh_min_sv_observability"] = pbh["min_sv_observability"]
            diagnostics["pbh_min_sv_detectability"] = pbh["min_sv_detectability"]

            obsv_mat, obsv_warns = _build_power_hankel_block(A_arr, C_arr, mode="obsv")
            warnings_out.extend(obsv_warns)
            if obsv_mat is not None and n > 0:
                svd_o = safe_svd_metrics(obsv_mat)
                diagnostics["obsv_rank"] = svd_o["rank"]
                diagnostics["obsv_min_sv"] = svd_o["s_min"]
                diagnostics["obsv_cond"] = svd_o["cond"]
                if svd_o["cond"] is not None and svd_o["cond"] > DEFAULT_COND_WARN_THRESHOLD:
                    warnings_out.append(
                        WarningItem(
                            code="ILL_CONDITIONED_OBSERVABILITY_MATRIX",
                            message=f"Matriz de observabilidade mal condicionada (cond={svd_o['cond']:.3e}).",
                            details={"obsv_cond": svd_o["cond"]},
                        )
                    )
                if (svd_o["rank"] == n) != bool(pbh["observable"]):
                    warnings_out.append(
                        WarningItem(
                            code="OBSV_RANK_PBH_DISCREPANCY",
                            message=(
                                f"Posto SVD da matriz de observabilidade ({svd_o['rank']}/{n}) diverge do "
                                f"teste PBH (observable={pbh['observable']}); PBH é numericamente mais confiável."
                            ),
                            details={"obsv_rank": svd_o["rank"], "pbh_observable": bool(pbh["observable"])},
                        )
                    )
            elif n == 0:
                diagnostics["obsv_rank"] = 0

        if compute_gramians and is_asymp_stable and n > 0 and (B_arr is not None or C_arr is not None):
            g_kind = "both" if (B_arr is not None and C_arr is not None) else ("controllability" if B_arr is not None else "observability")
            g_res = gramians(A_arr, B=B_arr, C=C_arr, kind=g_kind, dt=resolved_dt, tol=tol, raise_on_error=False)
            if g_res.status in ("success", "warning") and g_res.data is not None:
                if "Wc" in g_res.data:
                    data["Wc"] = g_res.data["Wc"]
                if "Wo" in g_res.data:
                    data["Wo"] = g_res.data["Wo"]
                if "hankel_singular_values" in g_res.data:
                    data["hankel_singular_values"] = g_res.data["hankel_singular_values"]
                diagnostics["gramians_diagnostics"] = g_res.diagnostics
                warnings_out.extend(
                    w if isinstance(w, WarningItem) else WarningItem(code="GRAMIAN_WARN", message=str(w))
                    for w in g_res.warnings
                )
            else:
                warnings_out.append(
                    WarningItem(
                        code="GRAMIANS_UNAVAILABLE",
                        message="Não foi possível calcular os gramianos numericamente.",
                        details=g_res.error.to_dict() if g_res.error is not None else None,
                    )
                )

        prov_ok = build_provenance(
            "statespace.analyze",
            tolerances={"tol": tol, "stab_tol": resolved_stab_tol},
            model_revision=sys_info["model_revision"],
        )
        return Result(
            status="warning" if warnings_out else "success",
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov_ok,
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
