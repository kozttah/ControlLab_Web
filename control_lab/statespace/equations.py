"""Solvers de Lyapunov, Sylvester, CARE e DARE com verificação PBH e resíduos normalizados."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.linalg

from control_lab.core.models import StateSpace
from control_lab.core.tensors import complex_to_pair, ensure_finite_float64, validate_sample_time
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

from ._utils import (
    DEFAULT_COND_WARN_THRESHOLD,
    DEFAULT_RCARE_FAIL_TOL,
    DEFAULT_RCARE_WARN_TOL,
    DEFAULT_SYMMETRY_TOL,
    care_residual_rel,
    dare_residual_rel,
    handle_failure,
    lyap_residual_rel,
    pbh_analysis_core,
    resolve_state_space_inputs,
    safe_svd_metrics,
    sort_complex_eigs,
    sylv_residual_rel,
    symmetry_error_rel,
    validate_square_matrix,
    validate_symmetric_pd,
    validate_symmetric_psd,
    validate_x0_vector,
)


def solve_lyapunov(
    plant_or_A: Any,
    Q: Any,
    *,
    domain: str | None = None,
    dt: float | None = None,
    require_symmetric: bool = True,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Resolve equação de Lyapunov contínua (A X + X A^T + Q = 0) ou discreta (A X A^T - X + Q = 0)."""
    dt_provided = dt is not None
    prov: Provenance = build_provenance(
        "statespace.solve_lyapunov",
        model_revision=getattr(plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        sys_info = resolve_state_space_inputs(
            plant_or_A,
            dt=dt,
            dt_provided=dt_provided,
            require_nonempty_states=True,
        )
        A = sys_info["A"]
        n = sys_info["n"]
        resolved_dt = sys_info["dt"]

        if domain is not None:
            if domain not in ("continuous", "discrete"):
                raise ValidationError(
                    f"domain inválido em solve_lyapunov: {domain!r}. Use 'continuous' ou 'discrete'."
                )
            if sys_info["plant"] is not None:
                expected_dom = "continuous" if resolved_dt is None else "discrete"
                if domain != expected_dom:
                    raise UnsupportedModelError(
                        message=(
                            f"Domínio solicitado ({domain!r}) incompatível com StateSpace.dt={resolved_dt!r}."
                        ),
                        parameters={"domain": domain, "plant_dt": resolved_dt},
                    )
            if dt_provided and domain == "continuous":
                raise ValidationError("Não forneça dt > 0 junto com domain='continuous'.")
            resolved_domain = domain
        else:
            resolved_domain = "discrete" if (resolved_dt is not None or dt_provided) else "continuous"

        Q_arr, nq = validate_square_matrix(Q, "Q", allow_empty=False)
        if nq != n:
            raise DimensionMismatchError(
                message=f"Dimensão de Q {Q_arr.shape} incompatível com A {A.shape}.",
                parameters={"A_shape": list(A.shape), "Q_shape": list(Q_arr.shape)},
            )

        q_sym_err = symmetry_error_rel(Q_arr)
        if require_symmetric:
            if q_sym_err > DEFAULT_SYMMETRY_TOL:
                raise HypothesisViolatedError(
                    message=f"Matriz Q não é simétrica (erro relativo={q_sym_err:.3e}).",
                    parameters={"Q_symmetry_error": q_sym_err},
                    next_step="Simetrize Q ou passe require_symmetric=False se intencional.",
                )
            Q_eff = 0.5 * (Q_arr + Q_arr.T)
        else:
            Q_eff = Q_arr

        # Verificação espectral de existência/unicidade
        eigs_A = np.linalg.eigvals(A)
        norm_A = float(np.linalg.norm(A, "fro"))
        if resolved_domain == "continuous":
            sum_mat = np.abs(eigs_A[:, None] + eigs_A[None, :])
            spectral_gap = float(np.min(sum_mat))
            gap_tol = tol if tol is not None else 1e-11 * max(1.0, norm_A)
            if spectral_gap <= gap_tol:
                raise HypothesisViolatedError(
                    message=(
                        "Equação de Lyapunov contínua singular: existem autovalores com "
                        f"lambda_i + lambda_j ~ 0 (gap={spectral_gap:.3e})."
                    ),
                    parameters={"min_spectral_gap": spectral_gap, "tolerance": gap_tol},
                    next_step="Garanta que A não possua autovalores simétricos em relação à origem.",
                )
            alg_name = "scipy.linalg.solve_continuous_lyapunov"
            X_raw = scipy.linalg.solve_continuous_lyapunov(A, -Q_eff)
        else:
            prod_mat = np.abs(eigs_A[:, None] * eigs_A[None, :] - 1.0)
            spectral_gap = float(np.min(prod_mat))
            gap_tol = tol if tol is not None else 1e-11 * max(1.0, norm_A * norm_A)
            if spectral_gap <= gap_tol:
                raise HypothesisViolatedError(
                    message=(
                        "Equação de Lyapunov discreta singular: existem autovalores com "
                        f"lambda_i * lambda_j ~ 1 (gap={spectral_gap:.3e})."
                    ),
                    parameters={"min_spectral_gap": spectral_gap, "tolerance": gap_tol},
                    next_step="Garanta que lambda_i * lambda_j != 1 para todo par de modos.",
                )
            alg_name = "scipy.linalg.solve_discrete_lyapunov"
            X_raw = scipy.linalg.solve_discrete_lyapunov(A, Q_eff)

        if not np.all(np.isfinite(X_raw)):
            raise NumericalInconclusiveError("Solver de Lyapunov retornou valores não finitos (NaN/Inf).")

        x_sym_err = symmetry_error_rel(X_raw)
        if require_symmetric:
            if x_sym_err > 1e-6:
                raise NumericalInconclusiveError(
                    message=f"Solução de Lyapunov perdeu simetria (erro={x_sym_err:.3e}).",
                    parameters={"symmetry_error": x_sym_err},
                )
            X = 0.5 * (X_raw + X_raw.T)
        else:
            X = np.array(X_raw, dtype=np.float64)

        res_rel = lyap_residual_rel(A, Q_eff, X, domain=resolved_domain)
        if not math.isfinite(res_rel):
            raise NumericalInconclusiveError("Resíduo de Lyapunov não finito.")

        svd_A = safe_svd_metrics(A)
        svd_X = safe_svd_metrics(X)

        if res_rel > DEFAULT_RCARE_FAIL_TOL:
            raise NumericalInconclusiveError(
                message=f"Resíduo normalizado de Lyapunov excessivo: {res_rel:.3e}.",
                parameters={"residual_rel": res_rel},
            )
        if res_rel > DEFAULT_RCARE_WARN_TOL:
            warnings_out.append(
                WarningItem(
                    code="HIGH_LYAPUNOV_RESIDUAL",
                    message=f"Resíduo relativo de Lyapunov acima de {DEFAULT_RCARE_WARN_TOL:.1e}: {res_rel:.3e}.",
                    details={"residual_rel": res_rel},
                )
            )

        if svd_A["cond"] is not None and svd_A["cond"] > DEFAULT_COND_WARN_THRESHOLD:
            warnings_out.append(
                WarningItem(
                    code="ILL_CONDITIONED_A",
                    message=f"Matriz A mal condicionada (cond={svd_A['cond']:.3e}).",
                    details={"cond_A": svd_A["cond"]},
                )
            )
        if spectral_gap < 1e-7 * max(1.0, norm_A):
            warnings_out.append(
                WarningItem(
                    code="NEAR_SINGULAR_LYAPUNOV_OPERATOR",
                    message=f"Operador de Lyapunov próximo à singularidade (gap espectral={spectral_gap:.3e}).",
                    details={"min_spectral_gap": spectral_gap},
                )
            )

        assumptions = {
            "domain": resolved_domain,
            "dt": resolved_dt,
            "n_states": n,
            "Q_symmetric": q_sym_err <= DEFAULT_SYMMETRY_TOL,
            "unique_solution_verified": True,
        }
        diagnostics = {
            "residual_rel": res_rel,
            "symmetry_error": x_sym_err,
            "Q_symmetry_error": q_sym_err,
            "min_spectral_gap": spectral_gap,
            "cond_A": svd_A["cond"],
            "cond_X": svd_X["cond"],
            "X_norm_fro": float(np.linalg.norm(X, "fro")),
        }
        prov_ok = build_provenance(
            alg_name,
            tolerances={"residual_warn_tol": DEFAULT_RCARE_WARN_TOL, "symmetry_tol": DEFAULT_SYMMETRY_TOL},
            model_revision=sys_info["model_revision"],
            equation="A*X + X*A^T + Q = 0" if resolved_domain == "continuous" else "A*X*A^T - X + Q = 0",
        )
        return Result(
            status="warning" if warnings_out else "success",
            data={"X": X, "domain": resolved_domain},
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
    except (np.linalg.LinAlgError, ValueError) as exc:
        err = NumericalInconclusiveError(f"Falha numérica ao resolver equação de Lyapunov: {exc}")
        return handle_failure(
            err,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def solve_sylvester(
    A: Any,
    B: Any,
    Q: Any,
    *,
    add_q: bool = False,
    tol: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Resolve equação de Sylvester A X + X B = Q (ou A X + X B + Q = 0 se add_q=True)."""
    prov = build_provenance("scipy.linalg.solve_sylvester")
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        A_arr, n = validate_square_matrix(A, "A", allow_empty=False)
        B_arr, m = validate_square_matrix(B, "B", allow_empty=False)
        Q_arr = ensure_finite_float64(Q, ndim=2, shape=(n, m), name="Q")

        eigs_A = np.linalg.eigvals(A_arr)
        eigs_B = np.linalg.eigvals(B_arr)
        spectral_gap = float(np.min(np.abs(eigs_A[:, None] + eigs_B[None, :])))
        scale = max(1.0, float(np.linalg.norm(A_arr, "fro")), float(np.linalg.norm(B_arr, "fro")))
        gap_tol = tol if tol is not None else 1e-11 * scale
        if spectral_gap <= gap_tol:
            raise HypothesisViolatedError(
                message=(
                    "Equação de Sylvester singular: espectros de A e -B se interceptam "
                    f"(min |lambda_i(A) + lambda_j(B)| = {spectral_gap:.3e})."
                ),
                parameters={"min_spectral_gap": spectral_gap, "tolerance": gap_tol},
                next_step="Escolha matrizes A e B sem autovalores opostos.",
            )

        rhs = -Q_arr if add_q else Q_arr
        X = scipy.linalg.solve_sylvester(A_arr, B_arr, rhs)
        if not np.all(np.isfinite(X)):
            raise NumericalInconclusiveError("solve_sylvester retornou valores não finitos.")

        res_rel = sylv_residual_rel(A_arr, B_arr, Q_arr, X, add_q=add_q)
        if not math.isfinite(res_rel):
            raise NumericalInconclusiveError("Resíduo de Sylvester não finito.")
        if res_rel > DEFAULT_RCARE_FAIL_TOL:
            raise NumericalInconclusiveError(
                message=f"Resíduo normalizado de Sylvester excessivo: {res_rel:.3e}.",
                parameters={"residual_rel": res_rel},
            )
        if res_rel > DEFAULT_RCARE_WARN_TOL:
            warnings_out.append(
                WarningItem(
                    code="HIGH_SYLVESTER_RESIDUAL",
                    message=f"Resíduo relativo de Sylvester elevado: {res_rel:.3e}.",
                    details={"residual_rel": res_rel},
                )
            )
        if spectral_gap < 1e-7 * scale:
            warnings_out.append(
                WarningItem(
                    code="NEAR_SINGULAR_SYLVESTER_OPERATOR",
                    message=f"Espectros de A e -B próximos (gap={spectral_gap:.3e}).",
                    details={"min_spectral_gap": spectral_gap},
                )
            )

        svd_A = safe_svd_metrics(A_arr)
        svd_B = safe_svd_metrics(B_arr)
        svd_X = safe_svd_metrics(X)
        assumptions = {
            "equation": "A*X + X*B + Q = 0" if add_q else "A*X + X*B = Q",
            "disjoint_spectra_A_negB": True,
            "shape_X": [n, m],
        }
        diagnostics = {
            "residual_rel": res_rel,
            "min_spectral_gap": spectral_gap,
            "cond_A": svd_A["cond"],
            "cond_B": svd_B["cond"],
            "cond_X": svd_X["cond"],
        }
        return Result(
            status="warning" if warnings_out else "success",
            data={"X": X},
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
    except (np.linalg.LinAlgError, ValueError) as exc:
        err = NumericalInconclusiveError(f"Falha numérica em solve_sylvester: {exc}")
        return handle_failure(
            err,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


def _resolve_riccati_inputs(
    plant_or_A: Any,
    B_or_Q: Any,
    Q_or_R: Any,
    R_mat: Any,
    *,
    plant: StateSpace | None,
    A: Any,
    B: Any,
    Q: Any,
    R: Any,
    dt: float | None,
    dt_provided: bool,
) -> dict[str, Any]:
    """Desambigua chamadas (plant, Q, R) e (A, B, Q, R) em formatos posicional ou keyword."""
    if plant is not None:
        if plant_or_A is not None:
            raise ValidationError("Não forneça 'plant' posicional e keyword simultaneamente.")
        if A is not None or B is not None or R_mat is not None:
            raise ValidationError("Não misture 'plant' com matrizes A/B extras.")
        sys_info = resolve_state_space_inputs(
            plant, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
        )
        Q_val = Q if Q is not None else B_or_Q
        R_val = R if R is not None else Q_or_R
        if B_or_Q is not None and Q is not None:
            raise ValidationError("Argumento Q duplicado.")
        if Q_or_R is not None and R is not None:
            raise ValidationError("Argumento R duplicado.")
        return {**sys_info, "Q_raw": Q_val, "R_raw": R_val}

    if isinstance(plant_or_A, StateSpace):
        if A is not None or B is not None or R_mat is not None:
            raise ValidationError("Não misture objeto StateSpace com A, B ou 4º argumento posicional.")
        if B_or_Q is not None and Q is not None:
            raise ValidationError("Argumento Q duplicado.")
        if Q_or_R is not None and R is not None:
            raise ValidationError("Argumento R duplicado.")
        Q_val = Q if Q is not None else B_or_Q
        R_val = R if R is not None else Q_or_R
        sys_info = resolve_state_space_inputs(
            plant_or_A, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
        )
        return {**sys_info, "Q_raw": Q_val, "R_raw": R_val}

    if hasattr(plant_or_A, "kind") and not isinstance(plant_or_A, (np.ndarray, list, tuple)):
        raise UnsupportedModelError(
            message=f"Tipo de modelo {type(plant_or_A).__name__} não suportado por Riccati; use StateSpace.",
            parameters={"model_type": type(plant_or_A).__name__},
        )

    A_val = A if A is not None else plant_or_A
    B_val = B if B is not None else B_or_Q
    Q_val = Q if Q is not None else Q_or_R
    R_val = R if R is not None else R_mat
    if A_val is None or B_val is None or Q_val is None or R_val is None:
        raise ValidationError("Chamada matricial requer A, B, Q e R não nulos.")
    sys_info = resolve_state_space_inputs(
        A_val, B=B_val, dt=dt, dt_provided=dt_provided, require_nonempty_states=True
    )
    return {**sys_info, "Q_raw": Q_val, "R_raw": R_val}


def _solve_are_core(
    *,
    domain: str,
    plant_or_A: Any,
    B_or_Q: Any,
    Q_or_R: Any,
    R_mat: Any,
    plant: StateSpace | None,
    A: Any,
    B: Any,
    Q: Any,
    R: Any,
    x0: Any,
    dt: float | None,
    dt_provided: bool,
    tol: float | None,
    check_hypotheses: bool,
    raise_on_error: bool,
    alg_id: str,
) -> Result:
    prov = build_provenance(
        alg_id,
        tolerances={"rCARE_warn_max": DEFAULT_RCARE_WARN_TOL, "symmetry_tol": DEFAULT_SYMMETRY_TOL},
        model_revision=getattr(plant if plant is not None else plant_or_A, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        info = _resolve_riccati_inputs(
            plant_or_A,
            B_or_Q,
            Q_or_R,
            R_mat,
            plant=plant,
            A=A,
            B=B,
            Q=Q,
            R=R,
            dt=dt,
            dt_provided=dt_provided,
        )
        A_arr: np.ndarray = info["A"]
        B_arr: np.ndarray = info["B"]
        n: int = info["n"]
        m: int = info["m"]
        resolved_dt: float | None = info["dt"]
        ss_plant: StateSpace | None = info["plant"]

        if m < 1:
            raise DimensionMismatchError("Sistema deve possuir ao menos 1 entrada (m >= 1) para CARE/DARE.")

        # Regra estrita de domínio temporal
        if domain == "continuous":
            if resolved_dt is not None or (dt_provided and dt is not None):
                raise UnsupportedModelError(
                    message=(
                        f"solve_care é exclusivo para tempo contínuo (dt=None), recebido dt={resolved_dt!r}. "
                        "Use solve_dare para sistemas discretos."
                    ),
                    parameters={"dt": resolved_dt, "expected_domain": "continuous"},
                    next_step="Invoque solve_dare() para modelos discretos.",
                )
        else:
            if ss_plant is not None and ss_plant.dt is None:
                raise UnsupportedModelError(
                    message=(
                        "solve_dare é exclusivo para modelos discretos (dt > 0), recebido StateSpace contínuo (dt=None). "
                        "Use solve_care ou discretize antes via discretize_zoh()."
                    ),
                    parameters={"dt": None, "expected_domain": "discrete"},
                    next_step="Invoque solve_care() ou discretize o modelo com discretize_zoh().",
                )
            if dt_provided and dt is None:
                raise UnsupportedModelError(
                    message="solve_dare não aceita dt=None explícito; use solve_care para contínuo.",
                    parameters={"dt": None},
                )

        if info["Q_raw"] is None or info["R_raw"] is None:
            raise ValidationError("Matrizes Q e R são obrigatórias para CARE/DARE.")

        Q_arr = ensure_finite_float64(info["Q_raw"], ndim=2, name="Q")
        Q_sym, Q_factor, eigs_Q, _, q_sym_err, q_warns = validate_symmetric_psd(
            Q_arr, "Q", expected_n=n
        )
        R_sym, cho_R, eigs_R, r_sym_err, cond_R, r_warns = validate_symmetric_pd(
            info["R_raw"], "R", expected_n=m
        )
        warnings_out.extend(q_warns)
        warnings_out.extend(r_warns)

        # Verificação PBH de estabilizabilidade (A, B) e detectabilidade (A, Q^{1/2})
        pbh_dt = None if domain == "continuous" else (resolved_dt if resolved_dt is not None else 1.0)
        pbh = pbh_analysis_core(A_arr, B=B_arr, C=Q_factor, dt=pbh_dt, tol=tol)
        warnings_out.extend(pbh["warnings"])

        assumptions = {
            "domain": domain,
            "dt": resolved_dt,
            "stabilizable": bool(pbh["stabilizable"]),
            "detectable": bool(pbh["detectable"]),
            "controllable": bool(pbh["controllable"]),
            "observable_Q": bool(pbh["observable"]),
            "Q_positive_semidefinite": True,
            "R_positive_definite": True,
        }
        diagnostics = {
            "pbh_min_sv_stabilizability": pbh["min_sv_stabilizability"],
            "pbh_min_sv_detectability": pbh["min_sv_detectability"],
            "pbh_min_sv_controllability": pbh["min_sv_controllability"],
            "pbh_min_sv_observability_Q": pbh["min_sv_observability"],
            "Q_symmetry_error": q_sym_err,
            "R_symmetry_error": r_sym_err,
            "min_eig_Q": float(np.min(eigs_Q)),
            "min_eig_R": float(np.min(eigs_R)),
            "cond_R": cond_R,
        }

        if check_hypotheses:
            if not pbh["stabilizable"]:
                raise HypothesisViolatedError(
                    message=(
                        "Hipótese violada para Riccati: par (A, B) não é estabilizável pelo teste PBH "
                        f"({len(pbh['unstabilizable_modes'])} modo(s) instável(is)/marginal(is) não controlável(is))."
                    ),
                    parameters={
                        "domain": domain,
                        "unstabilizable_modes": complex_to_pair(np.asarray(pbh["unstabilizable_modes"])),
                    },
                    next_step="Adicione atuadores/entradas que alcancem os modos instáveis ou marginais.",
                )
            if not pbh["detectable"]:
                raise HypothesisViolatedError(
                    message=(
                        "Hipótese violada para Riccati: par (A, Q^{1/2}) não é detectável pelo teste PBH "
                        f"({len(pbh['undetectable_modes'])} modo(s) instável(is)/marginal(is) não penalizado(s) em Q)."
                    ),
                    parameters={
                        "domain": domain,
                        "undetectable_modes": complex_to_pair(np.asarray(pbh["undetectable_modes"])),
                    },
                    next_step="Ajuste Q para penalizar os modos instáveis/marginais não observáveis em Q^{1/2}.",
                )

        x0_vec: np.ndarray | None = None
        if x0 is not None:
            x0_vec = validate_x0_vector(x0, n)

        # Resolução Numérica CARE / DARE
        if domain == "continuous":
            P_raw = scipy.linalg.solve_continuous_are(A_arr, B_arr, Q_sym, R_sym)
        else:
            P_raw = scipy.linalg.solve_discrete_are(A_arr, B_arr, Q_sym, R_sym)

        if not np.all(np.isfinite(P_raw)):
            raise NumericalInconclusiveError("Solver de Riccati retornou valores não finitos (NaN/Inf).")

        raw_sym_err = symmetry_error_rel(P_raw)
        if raw_sym_err > 1e-6:
            raise NumericalInconclusiveError(
                message=f"Solução P da equação de Riccati apresentou assimetria excessiva ({raw_sym_err:.3e}).",
                parameters={"symmetry_error": raw_sym_err},
            )
        P = 0.5 * (P_raw + P_raw.T)

        eigs_P = np.linalg.eigvalsh(P)
        min_eig_P = float(np.min(eigs_P))
        max_eig_P = float(np.max(eigs_P))
        p_psd_tol = max(1e-10, n * 1e-11 * max(1.0, float(np.max(np.abs(eigs_P)))))
        if min_eig_P < -p_psd_tol:
            raise NumericalInconclusiveError(
                message=f"Solução P de Riccati não é semidefinida positiva (min_eig_P={min_eig_P:.3e}).",
                parameters={"min_eig_P": min_eig_P},
            )

        # Recuperação de ganho K SEM inv explícita
        if domain == "continuous":
            K_lqr = scipy.linalg.cho_solve(cho_R, B_arr.T @ P)
            r_res = care_residual_rel(A_arr, B_arr, Q_arr, R_sym, P, K_lqr=K_lqr)
        else:
            M_d_raw = R_sym + B_arr.T @ P @ B_arr
            M_d = 0.5 * (M_d_raw + M_d_raw.T)
            try:
                cho_Md = scipy.linalg.cho_factor(M_d, lower=True, check_finite=True)
            except np.linalg.LinAlgError as exc:
                raise NumericalInconclusiveError(
                    f"Matriz (R + B^T P B) falhou fatoração de Cholesky na DARE: {exc}"
                ) from exc
            K_lqr = scipy.linalg.cho_solve(cho_Md, B_arr.T @ P @ A_arr)
            r_res = dare_residual_rel(A_arr, B_arr, Q_arr, R_sym, P, K_lqr=K_lqr)

        if not np.all(np.isfinite(K_lqr)) or not math.isfinite(r_res):
            raise NumericalInconclusiveError("Ganho LQR ou resíduo Riccati contém NaN/Inf.")

        # Estabilidade espectral de malha fechada (A - B K_lqr)
        Acl = A_arr - B_arr @ K_lqr
        eigs_open = sort_complex_eigs(np.linalg.eigvals(A_arr))
        eigs_cl = sort_complex_eigs(np.linalg.eigvals(Acl))

        if domain == "continuous":
            max_real_open = float(np.max(np.real(eigs_open)))
            max_real_cl = float(np.max(np.real(eigs_cl)))
            is_stable_cl = max_real_cl < 0.0
            diagnostics.update(
                {
                    "care_residual_rel": r_res,
                    "residual_rel": r_res,
                    "symmetry_error": raw_sym_err,
                    "min_eig_P": min_eig_P,
                    "max_real_open_loop": max_real_open,
                    "max_real_closed_loop": max_real_cl,
                }
            )
            if not is_stable_cl:
                raise NumericalInconclusiveError(
                    message=(
                        f"Malha fechada contínua não é estritamente estável: max Re eig(A-BK)={max_real_cl:.3e} >= 0."
                    ),
                    parameters={"max_real_closed_loop": max_real_cl, "care_residual_rel": r_res},
                )
        else:
            rho_open = float(np.max(np.abs(eigs_open)))
            rho_cl = float(np.max(np.abs(eigs_cl)))
            is_stable_cl = rho_cl < 1.0
            diagnostics.update(
                {
                    "dare_residual_rel": r_res,
                    "residual_rel": r_res,
                    "symmetry_error": raw_sym_err,
                    "min_eig_P": min_eig_P,
                    "spectral_radius_open_loop": rho_open,
                    "spectral_radius_closed_loop": rho_cl,
                }
            )
            if not is_stable_cl:
                raise NumericalInconclusiveError(
                    message=(
                        f"Malha fechada discreta não é estritamente estável: rho(A-BK)={rho_cl:.6f} >= 1."
                    ),
                    parameters={"spectral_radius_closed_loop": rho_cl, "dare_residual_rel": r_res},
                )

        if r_res > DEFAULT_RCARE_FAIL_TOL:
            raise NumericalInconclusiveError(
                message=f"Resíduo normalizado de Riccati acima do limite de falha: {r_res:.3e}.",
                parameters={"residual_rel": r_res, "fail_tol": DEFAULT_RCARE_FAIL_TOL},
            )
        if r_res > DEFAULT_RCARE_WARN_TOL:
            warnings_out.append(
                WarningItem(
                    code="HIGH_RICCATI_RESIDUAL",
                    message=(
                        f"Resíduo relativo de Riccati ({r_res:.3e}) excedeu meta {DEFAULT_RCARE_WARN_TOL:.1e} "
                        "(possível mal condicionamento)."
                    ),
                    details={"residual_rel": r_res},
                )
            )

        # Avisos de condicionamento de Q (quando Q é SPD) e P (quando P > 0)
        cond_P = float(max_eig_P / min_eig_P) if min_eig_P > 0.0 else None
        diagnostics["cond_P"] = cond_P if (cond_P is not None and math.isfinite(cond_P)) else None
        if cond_P is not None and (not math.isfinite(cond_P) or cond_P > DEFAULT_COND_WARN_THRESHOLD):
            warnings_out.append(
                WarningItem(
                    code="ILL_CONDITIONED_P",
                    message=f"Solução P de Riccati apresenta número de condição elevado (cond={cond_P:.3e}).",
                    details={"cond_P": cond_P if math.isfinite(cond_P) else -1.0},
                )
            )

        min_eig_Q = float(np.min(eigs_Q))
        max_eig_Q = float(np.max(eigs_Q))
        cond_Q = float(max_eig_Q / min_eig_Q) if min_eig_Q > 1e-14 * max(1.0, max_eig_Q) else None
        diagnostics["cond_Q"] = cond_Q if (cond_Q is not None and math.isfinite(cond_Q)) else None
        if cond_Q is not None and cond_Q > DEFAULT_COND_WARN_THRESHOLD:
            warnings_out.append(
                WarningItem(
                    code="ILL_CONDITIONED_Q",
                    message=f"Matriz Q definida positiva apresenta número de condição elevado (cond={cond_Q:.3e}).",
                    details={"cond_Q": cond_Q},
                )
            )

        assumptions["closed_loop_stable"] = is_stable_cl

        data: dict[str, Any] = {
            "P": P,
            "K": K_lqr,
            "open_loop_poles": complex_to_pair(eigs_open),
            "closed_loop_poles": complex_to_pair(eigs_cl),
            "optimal_cost": float(x0_vec @ P @ x0_vec) if x0_vec is not None else None,
        }

        prov_ok = build_provenance(
            alg_id,
            tolerances={
                "residual_warn_tol": DEFAULT_RCARE_WARN_TOL,
                "residual_fail_tol": DEFAULT_RCARE_FAIL_TOL,
                "symmetry_tol": DEFAULT_SYMMETRY_TOL,
            },
            model_revision=info["model_revision"],
            domain=domain,
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
    except (np.linalg.LinAlgError, ValueError) as exc:
        err = NumericalInconclusiveError(f"Falha numérica no solver de Riccati ({domain}): {exc}")
        return handle_failure(
            err,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )


_UNSET: Any = object()


def solve_care(
    plant_or_A: Any = None,
    B_or_Q: Any = None,
    Q_or_R: Any = None,
    R_mat: Any = None,
    *,
    plant: StateSpace | None = None,
    A: Any = None,
    B: Any = None,
    Q: Any = None,
    R: Any = None,
    x0: Any = None,
    dt: float | None = _UNSET,
    tol: float | None = None,
    check_hypotheses: bool = True,
    raise_on_error: bool = False,
) -> Result:
    """Resolve a Equação Algébrica de Riccati Contínua (CARE): A^T P + P A - P B R^-1 B^T P + Q = 0."""
    dt_provided = dt is not _UNSET
    resolved_dt_arg = None if dt is _UNSET else dt
    return _solve_are_core(
        domain="continuous",
        plant_or_A=plant_or_A,
        B_or_Q=B_or_Q,
        Q_or_R=Q_or_R,
        R_mat=R_mat,
        plant=plant,
        A=A,
        B=B,
        Q=Q,
        R=R,
        x0=x0,
        dt=resolved_dt_arg,
        dt_provided=dt_provided,
        tol=tol,
        check_hypotheses=check_hypotheses,
        raise_on_error=raise_on_error,
        alg_id="scipy.linalg.solve_continuous_are",
    )


def solve_dare(
    plant_or_A: Any = None,
    B_or_Q: Any = None,
    Q_or_R: Any = None,
    R_mat: Any = None,
    *,
    plant: StateSpace | None = None,
    A: Any = None,
    B: Any = None,
    Q: Any = None,
    R: Any = None,
    x0: Any = None,
    dt: float | None = _UNSET,
    tol: float | None = None,
    check_hypotheses: bool = True,
    raise_on_error: bool = False,
) -> Result:
    """Resolve a Equação Algébrica de Riccati Discreta (DARE): A^T P A - P - A^T P B (R+B^T P B)^-1 B^T P A + Q = 0."""
    dt_provided = dt is not _UNSET
    resolved_dt_arg = None if dt is _UNSET else dt
    return _solve_are_core(
        domain="discrete",
        plant_or_A=plant_or_A,
        B_or_Q=B_or_Q,
        Q_or_R=Q_or_R,
        R_mat=R_mat,
        plant=plant,
        A=A,
        B=B,
        Q=Q,
        R=R,
        x0=x0,
        dt=resolved_dt_arg,
        dt_provided=dt_provided,
        tol=tol,
        check_hypotheses=check_hypotheses,
        raise_on_error=raise_on_error,
        alg_id="scipy.linalg.solve_discrete_are",
    )
