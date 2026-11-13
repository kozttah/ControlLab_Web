"""Helpers internos de validação, álgebra linear estável (sem inv) e métricas espectrais."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import scipy.linalg
import scipy.optimize

from control_lab.core.models import StateSpace
from control_lab.core.tensors import (
    check_dt_compatible,
    ensure_finite_float64,
    validate_sample_time,
)
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    NumericalInconclusiveError,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
)

DEFAULT_SYMMETRY_TOL: float = 1e-10
DEFAULT_STAB_TOL: float = 1e-9
DEFAULT_RCARE_WARN_TOL: float = 1e-9
DEFAULT_RCARE_FAIL_TOL: float = 1e-4
DEFAULT_COND_WARN_THRESHOLD: float = 1e8


def sort_complex_eigs(vals: np.ndarray) -> np.ndarray:
    """Ordena autovalores complexos deterministicamente por (Re, Im)."""
    arr = np.asarray(vals, dtype=np.complex128).ravel()
    if arr.size == 0:
        return arr
    order = np.lexsort((np.imag(arr), np.real(arr)))
    return arr[order]


def symmetry_error_rel(M: np.ndarray) -> float:
    """Erro relativo de simetria ||M - M^T||_F / (1 + ||M||_F)."""
    if M.size == 0:
        return 0.0
    return float(np.linalg.norm(M - M.T, "fro") / (1.0 + np.linalg.norm(M, "fro")))


def safe_svd_metrics(M: np.ndarray) -> dict[str, Any]:
    """Calcula posto numérico, valores singulares extremos e condicionamento finito para JSON."""
    if M.size == 0:
        return {
            "rank": 0,
            "s_max": 0.0,
            "s_min": 0.0,
            "cond": 1.0,
            "is_singular": False,
        }
    svals = np.linalg.svd(M, compute_uv=False)
    s_max = float(svals[0])
    s_min = float(svals[-1])
    eps = float(np.finfo(np.float64).eps)
    rank_tol = max(M.shape) * eps * s_max if s_max > 0.0 else 0.0
    rank = int(np.sum(svals > rank_tol)) if s_max > 0.0 else 0
    if s_max == 0.0 or s_min <= max(M.shape) * eps * s_max:
        return {
            "rank": rank,
            "s_max": s_max,
            "s_min": s_min,
            "cond": None,
            "is_singular": True,
        }
    cond = float(s_max / s_min)
    return {
        "rank": rank,
        "s_max": s_max,
        "s_min": s_min,
        "cond": cond if math.isfinite(cond) else None,
        "is_singular": not math.isfinite(cond),
    }


def validate_square_matrix(value: Any, name: str, *, allow_empty: bool = False) -> tuple[np.ndarray, int]:
    """Valida que a entrada é matriz 2D quadrada e finita em float64."""
    arr = ensure_finite_float64(value, ndim=2, name=name)
    n, n2 = arr.shape
    if n != n2:
        raise DimensionMismatchError(
            message=f"Matriz {name} deve ser quadrada (n, n), recebido shape={arr.shape}.",
            parameters={"matrix": name, "shape": list(arr.shape)},
            next_step=f"Forneça uma matriz {name} quadrada.",
        )
    if not allow_empty and n < 1:
        raise DimensionMismatchError(
            message=f"Matriz {name} deve ter dimensão n >= 1, recebido {arr.shape}.",
            parameters={"matrix": name, "shape": list(arr.shape)},
        )
    return arr, n


def validate_symmetric_psd(
    value: Any,
    name: str,
    *,
    expected_n: int | None = None,
    sym_tol: float = DEFAULT_SYMMETRY_TOL,
    tol: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, list[WarningItem]]:
    """Valida matriz simétrica semidefinida positiva (Q = Q^T >= 0) e retorna fator Q_factor."""
    M, n = validate_square_matrix(value, name, allow_empty=False)
    if expected_n is not None and n != expected_n:
        raise DimensionMismatchError(
            message=f"Matriz {name} tem shape {M.shape}, esperado ({expected_n}, {expected_n}).",
            parameters={"matrix": name, "actual_shape": list(M.shape), "expected_shape": [expected_n, expected_n]},
        )

    sym_err = symmetry_error_rel(M)
    if sym_err > sym_tol:
        raise HypothesisViolatedError(
            message=f"Matriz {name} não é simétrica (erro relativo={sym_err:.3e} > {sym_tol:.1e}).",
            parameters={"matrix": name, "symmetry_error": sym_err, "tolerance": sym_tol},
            next_step=f"Simetrize {name} ou corrija entradas assimétricas antes da síntese.",
        )

    M_sym = 0.5 * (M + M.T)
    eigs, vecs = np.linalg.eigh(M_sym)
    max_abs = float(np.max(np.abs(eigs)))
    max_eig = float(np.max(eigs))
    min_eig = float(np.min(eigs))

    eps = float(np.finfo(np.float64).eps)
    psd_tol = tol if tol is not None else max(1e-12, n * 1e-12 * max(1.0, max_abs))
    if min_eig < -psd_tol:
        raise HypothesisViolatedError(
            message=(
                f"Matriz {name} não é semidefinida positiva: menor autovalor={min_eig:.3e} < -{psd_tol:.1e}."
            ),
            parameters={"matrix": name, "min_eigenvalue": min_eig, "tolerance": psd_tol},
            next_step=f"Ajuste {name} para que todos os autovalores sejam >= 0.",
        )

    warnings_out: list[WarningItem] = []
    if min_eig < 0.0:
        warnings_out.append(
            WarningItem(
                code=f"{name}_SLIGHTLY_NEGATIVE_EIG",
                message=(
                    f"Matriz {name} apresentou menor autovalor {min_eig:.3e} dentro da tolerância "
                    "numérica PSD; truncado para 0 na fatoração espectral."
                ),
                details={"matrix": name, "min_eigenvalue": min_eig, "psd_tol": psd_tol},
            )
        )

    # Zerar ruído de arredondamento próximo a eps * max_eig antes da raiz quadrada para evitar
    # artefato sqrt(eps) ~ 1e-8 na verificação de detectabilidade PBH.
    zero_cutoff = max(0.0, 100.0 * n * eps * max(0.0, max_eig))
    eigs_clean = np.where(eigs > zero_cutoff, eigs, 0.0)
    pos_mask = eigs_clean > 0.0
    if np.any(pos_mask):
        factor = (vecs[:, pos_mask] * np.sqrt(eigs_clean[pos_mask])).T
    else:
        factor = np.zeros((0, n), dtype=np.float64)

    return M_sym, factor, eigs, vecs, sym_err, warnings_out


def validate_symmetric_pd(
    value: Any,
    name: str,
    *,
    expected_n: int | None = None,
    sym_tol: float = DEFAULT_SYMMETRY_TOL,
    tol: float | None = None,
) -> tuple[np.ndarray, tuple[np.ndarray, bool], np.ndarray, float, float, list[WarningItem]]:
    """Valida matriz simétrica estritamente definida positiva (R = R^T > 0) via autovalores e Cholesky."""
    M, m = validate_square_matrix(value, name, allow_empty=False)
    if expected_n is not None and m != expected_n:
        raise DimensionMismatchError(
            message=f"Matriz {name} tem shape {M.shape}, esperado ({expected_n}, {expected_n}).",
            parameters={"matrix": name, "actual_shape": list(M.shape), "expected_shape": [expected_n, expected_n]},
        )

    sym_err = symmetry_error_rel(M)
    if sym_err > sym_tol:
        raise HypothesisViolatedError(
            message=f"Matriz {name} não é simétrica (erro relativo={sym_err:.3e} > {sym_tol:.1e}).",
            parameters={"matrix": name, "symmetry_error": sym_err, "tolerance": sym_tol},
            next_step=f"Forneça uma matriz {name} simétrica definida positiva.",
        )

    M_sym = 0.5 * (M + M.T)
    eigs = np.linalg.eigvalsh(M_sym)
    min_eig = float(np.min(eigs))
    max_eig = float(np.max(eigs))
    eps = float(np.finfo(np.float64).eps)

    pd_tol = tol if tol is not None else max(0.0, m * eps * max(1.0, max_eig))
    if min_eig <= pd_tol:
        raise HypothesisViolatedError(
            message=(
                f"Matriz {name} não é estritamente definida positiva: "
                f"menor autovalor={min_eig:.3e} <= {pd_tol:.3e}."
            ),
            parameters={"matrix": name, "min_eigenvalue": min_eig, "max_eigenvalue": max_eig},
            next_step=f"Escolha {name} simétrica com todos os autovalores estritamente > 0.",
        )

    try:
        cho_fac = scipy.linalg.cho_factor(M_sym, lower=True, check_finite=True)
    except np.linalg.LinAlgError as exc:
        raise HypothesisViolatedError(
            message=f"Fatoração de Cholesky falhou para {name}: matriz singular ou indefinida ({exc}).",
            parameters={"matrix": name, "min_eigenvalue": min_eig},
            next_step=f"Verifique a positividade estrita de {name}.",
        ) from exc

    cond_val = float(max_eig / min_eig)
    warnings_out: list[WarningItem] = []
    if not math.isfinite(cond_val) or cond_val > DEFAULT_COND_WARN_THRESHOLD:
        warnings_out.append(
            WarningItem(
                code=f"ILL_CONDITIONED_{name}",
                message=f"Matriz {name} possui número de condição elevado (cond={cond_val:.3e}).",
                details={"matrix": name, "condition_number": cond_val if math.isfinite(cond_val) else -1.0},
            )
        )

    return M_sym, cho_fac, eigs, sym_err, cond_val, warnings_out


def resolve_state_space_inputs(
    plant_or_A: Any,
    B: Any = None,
    C: Any = None,
    D: Any = None,
    *,
    dt: float | None = None,
    dt_provided: bool = False,
    require_nonempty_states: bool = True,
) -> dict[str, Any]:
    """Extrai matrizes validadas (A, B, C, D, dt, metadados) de StateSpace ou matrizes brutas."""
    if isinstance(plant_or_A, StateSpace):
        plant = plant_or_A
        if dt_provided:
            resolved_dt = validate_sample_time(dt)
            check_dt_compatible(plant.dt, resolved_dt, label_a="plant", label_b="dt")
        if require_nonempty_states and plant.n_states < 1:
            raise DimensionMismatchError(
                message="Operação requer modelo StateSpace com pelo menos 1 estado (n >= 1).",
                parameters={"n_states": plant.n_states},
            )
        return {
            "plant": plant,
            "A": np.array(plant.A, dtype=np.float64, copy=True),
            "B": np.array(plant.B, dtype=np.float64, copy=True),
            "C": np.array(plant.C, dtype=np.float64, copy=True),
            "D": np.array(plant.D, dtype=np.float64, copy=True),
            "dt": plant.dt,
            "n": plant.n_states,
            "m": plant.n_inputs,
            "p": plant.n_outputs,
            "model_revision": plant.revision,
            "state_names": plant.state_names,
            "input_names": plant.input_names,
            "output_names": plant.output_names,
            "units": plant.units,
        }

    # Rejeitar explicitamente outros tipos de modelos não StateSpace (TransferFunction, TSStateSpace, etc.)
    if hasattr(plant_or_A, "kind") and not isinstance(plant_or_A, (np.ndarray, list, tuple)):
        raise UnsupportedModelError(
            message=f"Tipo de modelo {type(plant_or_A).__name__} não suportado diretamente; converta para StateSpace.",
            parameters={"model_type": type(plant_or_A).__name__},
            next_step="Converta o modelo para StateSpace antes de invocar rotinas de espaço de estados.",
        )

    A_arr, n = validate_square_matrix(plant_or_A, "A", allow_empty=not require_nonempty_states)
    resolved_dt = validate_sample_time(dt) if dt_provided else None

    B_arr: np.ndarray | None = None
    m = 0
    if B is not None:
        B_arr = ensure_finite_float64(B, ndim=2, name="B")
        if B_arr.shape[0] != n:
            raise DimensionMismatchError(
                message=f"Dimensão incompatível entre A {A_arr.shape} e B {B_arr.shape}: linhas de B devem ser {n}.",
                parameters={"A_shape": list(A_arr.shape), "B_shape": list(B_arr.shape)},
            )
        m = B_arr.shape[1]

    C_arr: np.ndarray | None = None
    p = 0
    if C is not None:
        C_arr = ensure_finite_float64(C, ndim=2, name="C")
        if C_arr.shape[1] != n:
            raise DimensionMismatchError(
                message=f"Dimensão incompatível entre A {A_arr.shape} e C {C_arr.shape}: colunas de C devem ser {n}.",
                parameters={"A_shape": list(A_arr.shape), "C_shape": list(C_arr.shape)},
            )
        p = C_arr.shape[0]

    D_arr: np.ndarray | None = None
    if D is not None:
        if B_arr is None or C_arr is None:
            raise ValidationError("Matriz D só pode ser fornecida junto com B e C.")
        D_arr = ensure_finite_float64(D, ndim=2, name="D")
        if D_arr.shape != (p, m):
            raise DimensionMismatchError(
                message=f"Matriz D tem shape {D_arr.shape}, esperado ({p}, {m}).",
                parameters={"D_shape": list(D_arr.shape), "expected_shape": [p, m]},
            )

    return {
        "plant": None,
        "A": A_arr,
        "B": B_arr,
        "C": C_arr,
        "D": D_arr,
        "dt": resolved_dt,
        "n": n,
        "m": m,
        "p": p,
        "model_revision": None,
        "state_names": tuple(f"x{i + 1}" for i in range(n)),
        "input_names": tuple(f"u{i + 1}" for i in range(m)),
        "output_names": tuple(f"y{i + 1}" for i in range(p)),
        "units": None,
    }


def _is_unstable_mode(lam: complex, *, dt: float | None, stab_tol: float) -> bool:
    if dt is None:
        return bool(np.real(lam) >= -stab_tol)
    return bool(abs(lam) >= 1.0 - stab_tol)


def pbh_analysis_core(
    A: np.ndarray,
    B: np.ndarray | None = None,
    C: np.ndarray | None = None,
    *,
    dt: float | None = None,
    tol: float | None = None,
    stab_tol: float | None = None,
) -> dict[str, Any]:
    """Executa teste PBH via SVD para controlabilidade, estabilizabilidade, observabilidade e detectabilidade."""
    n = A.shape[0]
    if n == 0:
        out: dict[str, Any] = {
            "open_loop_poles": np.array([], dtype=np.complex128),
            "warnings": [],
        }
        if B is not None:
            out.update(
                {
                    "controllable": True,
                    "stabilizable": True,
                    "min_sv_controllability": None,
                    "min_sv_stabilizability": None,
                    "uncontrollable_modes": [],
                    "unstabilizable_modes": [],
                }
            )
        if C is not None:
            out.update(
                {
                    "observable": True,
                    "detectable": True,
                    "min_sv_observability": None,
                    "min_sv_detectability": None,
                    "unobservable_modes": [],
                    "undetectable_modes": [],
                }
            )
        return out

    norm_A = float(np.linalg.norm(A, "fro"))
    resolved_stab_tol = stab_tol if stab_tol is not None else max(DEFAULT_STAB_TOL, 1e-12 * norm_A)
    eigs = sort_complex_eigs(np.linalg.eigvals(A))
    eye_n = np.eye(n, dtype=np.complex128)
    A_c = A.astype(np.complex128)

    warnings_out: list[WarningItem] = []
    near_boundary_modes: list[complex] = []
    for lam in eigs:
        if dt is None:
            if abs(float(np.real(lam))) < 1e-6 * max(1.0, norm_A) and abs(float(np.real(lam))) > 0.0:
                near_boundary_modes.append(complex(lam))
        else:
            if abs(abs(complex(lam)) - 1.0) < 1e-6 and abs(abs(complex(lam)) - 1.0) > 0.0:
                near_boundary_modes.append(complex(lam))

    res: dict[str, Any] = {
        "open_loop_poles": eigs,
        "stab_tol": resolved_stab_tol,
        "warnings": warnings_out,
    }

    if B is not None:
        B_c = B.astype(np.complex128)
        m = B.shape[1]
        if m == 0:
            unstable_modes = [complex(lam) for lam in eigs if _is_unstable_mode(lam, dt=dt, stab_tol=resolved_stab_tol)]
            res.update(
                {
                    "controllable": False,
                    "stabilizable": len(unstable_modes) == 0,
                    "min_sv_controllability": 0.0,
                    "min_sv_stabilizability": 0.0 if unstable_modes else None,
                    "uncontrollable_modes": [complex(lam) for lam in eigs],
                    "unstabilizable_modes": unstable_modes,
                }
            )
        else:
            uncontrollable: list[complex] = []
            unstabilizable: list[complex] = []
            min_sv_ctrl = float("inf")
            min_sv_stab = float("inf")
            has_unstable = False
            weak_ratio = float("inf")

            for lam in eigs:
                M = np.hstack([lam * eye_n - A_c, B_c])
                svals = np.linalg.svd(M, compute_uv=False)
                s_max = float(svals[0])
                s_min = float(svals[-1])
                rank_thresh = tol if tol is not None else (max(M.shape) * 1e-12 * s_max if s_max > 0.0 else 0.0)
                rank = int(np.sum(svals > rank_thresh)) if s_max > 0.0 else 0

                min_sv_ctrl = min(min_sv_ctrl, s_min)
                if s_max > 0.0:
                    weak_ratio = min(weak_ratio, s_min / s_max)
                is_unstab = _is_unstable_mode(lam, dt=dt, stab_tol=resolved_stab_tol)
                if is_unstab:
                    has_unstable = True
                    min_sv_stab = min(min_sv_stab, s_min)

                if rank < n:
                    uncontrollable.append(complex(lam))
                    if is_unstab:
                        unstabilizable.append(complex(lam))

            if len(uncontrollable) == 0 and weak_ratio < 1e-7:
                warnings_out.append(
                    WarningItem(
                        code="WEAK_CONTROLLABILITY_MODE",
                        message=f"Sistema próximo da não controlabilidade via PBH (razão sigma_min/sigma_max={weak_ratio:.3e}).",
                        details={"min_sv_ratio": weak_ratio},
                    )
                )

            res.update(
                {
                    "controllable": len(uncontrollable) == 0,
                    "stabilizable": len(unstabilizable) == 0,
                    "min_sv_controllability": min_sv_ctrl if math.isfinite(min_sv_ctrl) else None,
                    "min_sv_stabilizability": min_sv_stab if (has_unstable and math.isfinite(min_sv_stab)) else None,
                    "uncontrollable_modes": uncontrollable,
                    "unstabilizable_modes": unstabilizable,
                }
            )

    if C is not None:
        C_c = C.astype(np.complex128)
        p = C.shape[0]
        if p == 0:
            unstable_modes = [complex(lam) for lam in eigs if _is_unstable_mode(lam, dt=dt, stab_tol=resolved_stab_tol)]
            res.update(
                {
                    "observable": False,
                    "detectable": len(unstable_modes) == 0,
                    "min_sv_observability": 0.0,
                    "min_sv_detectability": 0.0 if unstable_modes else None,
                    "unobservable_modes": [complex(lam) for lam in eigs],
                    "undetectable_modes": unstable_modes,
                }
            )
        else:
            unobservable: list[complex] = []
            undetectable: list[complex] = []
            min_sv_obs = float("inf")
            min_sv_det = float("inf")
            has_unstable = False
            weak_ratio = float("inf")

            for lam in eigs:
                M = np.vstack([lam * eye_n - A_c, C_c])
                svals = np.linalg.svd(M, compute_uv=False)
                s_max = float(svals[0])
                s_min = float(svals[-1])
                rank_thresh = tol if tol is not None else (max(M.shape) * 1e-12 * s_max if s_max > 0.0 else 0.0)
                rank = int(np.sum(svals > rank_thresh)) if s_max > 0.0 else 0

                min_sv_obs = min(min_sv_obs, s_min)
                if s_max > 0.0:
                    weak_ratio = min(weak_ratio, s_min / s_max)
                is_unstab = _is_unstable_mode(lam, dt=dt, stab_tol=resolved_stab_tol)
                if is_unstab:
                    has_unstable = True
                    min_sv_det = min(min_sv_det, s_min)

                if rank < n:
                    unobservable.append(complex(lam))
                    if is_unstab:
                        undetectable.append(complex(lam))

            if len(unobservable) == 0 and weak_ratio < 1e-7:
                warnings_out.append(
                    WarningItem(
                        code="WEAK_OBSERVABILITY_MODE",
                        message=f"Sistema próximo da não observabilidade via PBH (razão sigma_min/sigma_max={weak_ratio:.3e}).",
                        details={"min_sv_ratio": weak_ratio},
                    )
                )

            res.update(
                {
                    "observable": len(unobservable) == 0,
                    "detectable": len(undetectable) == 0,
                    "min_sv_observability": min_sv_obs if math.isfinite(min_sv_obs) else None,
                    "min_sv_detectability": min_sv_det if (has_unstable and math.isfinite(min_sv_det)) else None,
                    "unobservable_modes": unobservable,
                    "undetectable_modes": undetectable,
                }
            )

    return res


def care_residual_rel(
    A: np.ndarray,
    B: np.ndarray,
    Q: np.ndarray,
    R: np.ndarray,
    P: np.ndarray,
    K_lqr: np.ndarray | None = None,
) -> float:
    """Resíduo normalizado rCARE conforme Seção 10.2 do Documento Diretor."""
    R_inv_BT_P = np.linalg.solve(R, B.T @ P) if K_lqr is None else K_lqr
    ATP = A.T @ P
    PA = P @ A
    PBRBTP = P @ B @ R_inv_BT_P
    E = ATP + PA - PBRBTP + Q
    denom = (
        1.0
        + float(np.linalg.norm(ATP, "fro"))
        + float(np.linalg.norm(PA, "fro"))
        + float(np.linalg.norm(PBRBTP, "fro"))
        + float(np.linalg.norm(Q, "fro"))
    )
    return float(np.linalg.norm(E, "fro") / denom)


def dare_residual_rel(
    A: np.ndarray,
    B: np.ndarray,
    Q: np.ndarray,
    R: np.ndarray,
    P: np.ndarray,
    K_lqr: np.ndarray | None = None,
) -> float:
    """Resíduo normalizado rDARE análogo à Seção 10.2."""
    if K_lqr is None:
        M_d = 0.5 * ((R + B.T @ P @ B) + (R + B.T @ P @ B).T)
        K_eff = np.linalg.solve(M_d, B.T @ P @ A)
    else:
        K_eff = K_lqr
    ATPA = A.T @ P @ A
    ATPBK = A.T @ P @ B @ K_eff
    E = ATPA - P - ATPBK + Q
    denom = (
        1.0
        + float(np.linalg.norm(ATPA, "fro"))
        + float(np.linalg.norm(P, "fro"))
        + float(np.linalg.norm(ATPBK, "fro"))
        + float(np.linalg.norm(Q, "fro"))
    )
    return float(np.linalg.norm(E, "fro") / denom)


def lyap_residual_rel(
    A: np.ndarray,
    Q: np.ndarray,
    X: np.ndarray,
    *,
    domain: str = "continuous",
) -> float:
    """Resíduo normalizado de Lyapunov pelos termos efetivamente somados (Seção 10.2)."""
    if domain == "continuous":
        AX = A @ X
        XAT = X @ A.T
        E = AX + XAT + Q
        denom = (
            1.0
            + float(np.linalg.norm(AX, "fro"))
            + float(np.linalg.norm(XAT, "fro"))
            + float(np.linalg.norm(Q, "fro"))
        )
    else:
        AXAT = A @ X @ A.T
        E = AXAT - X + Q
        denom = (
            1.0
            + float(np.linalg.norm(AXAT, "fro"))
            + float(np.linalg.norm(X, "fro"))
            + float(np.linalg.norm(Q, "fro"))
        )
    return float(np.linalg.norm(E, "fro") / denom)


def sylv_residual_rel(
    A: np.ndarray,
    B: np.ndarray,
    Q: np.ndarray,
    X: np.ndarray,
    *,
    add_q: bool = False,
) -> float:
    """Resíduo normalizado de Sylvester A X + X B = Q (ou + Q = 0)."""
    AX = A @ X
    XB = X @ B
    E = (AX + XB + Q) if add_q else (AX + XB - Q)
    denom = (
        1.0
        + float(np.linalg.norm(AX, "fro"))
        + float(np.linalg.norm(XB, "fro"))
        + float(np.linalg.norm(Q, "fro"))
    )
    return float(np.linalg.norm(E, "fro") / denom)


def match_poles_error(achieved: np.ndarray, target: np.ndarray) -> float:
    """Calcula erro máximo |lambda_achieved - lambda_target| via pareamento ótimo bipartido."""
    a = np.asarray(achieved, dtype=np.complex128).ravel()
    b = np.asarray(target, dtype=np.complex128).ravel()
    if a.shape != b.shape:
        raise DimensionMismatchError("Vetores de polos têm comprimentos diferentes.")
    if a.size == 0:
        return 0.0
    cost_mat = np.abs(a[:, None] - b[None, :])
    row_ind, col_ind = scipy.optimize.linear_sum_assignment(cost_mat)
    return float(np.max(cost_mat[row_ind, col_ind]))


def validate_conjugate_poles(poles: Any, n: int) -> np.ndarray:
    """Valida vetor 1D de n polos finitos e fechamento por conjugação complexa."""
    if poles is None or isinstance(poles, (str, bytes)):
        raise ValidationError("poles deve ser uma sequência numérica 1D de comprimento n.")
    try:
        arr = np.asarray(poles, dtype=np.complex128)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"poles inválido: {exc}") from exc
    if arr.ndim != 1:
        raise DimensionMismatchError(f"poles deve ser 1D, recebido {arr.ndim}D (shape={arr.shape}).")
    if arr.shape[0] != n:
        raise DimensionMismatchError(
            message=f"Número de polos ({arr.shape[0]}) difere do número de estados n={n}.",
            parameters={"expected_n": n, "actual_n": int(arr.shape[0])},
        )
    if not (np.all(np.isfinite(arr.real)) and np.all(np.isfinite(arr.imag))):
        raise ValidationError("poles contém valores não finitos (NaN ou Inf).")

    scale = max(1.0, float(np.max(np.abs(arr)))) if arr.size > 0 else 1.0
    conj_tol = 1e-10 * scale
    unmatched = list(arr)
    while unmatched:
        z = unmatched.pop(0)
        if abs(z.imag) <= conj_tol:
            continue
        conj_z = np.conj(z)
        best_idx = -1
        best_dist = float("inf")
        for idx, cand in enumerate(unmatched):
            dist = abs(cand - conj_z)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx < 0 or best_dist > conj_tol:
            raise ValidationError(
                message=(
                    f"Conjunto de polos não é fechado sob conjugação complexa: "
                    f"polo {z!r} não possui conjugado correspondente."
                ),
                parameters={"unmatched_pole": [float(z.real), float(z.imag)]},
                next_step="Forneça pares complexos conjugados a +- jb para obter ganho real.",
            )
        unmatched.pop(best_idx)

    return arr


def validate_x0_vector(x0: Any, n: int) -> np.ndarray:
    """Valida vetor de estado inicial x0 de shape (n,) ou (n, 1) e retorna array 1D (n,)."""
    x0_raw = ensure_finite_float64(x0, name="x0")
    if x0_raw.ndim == 1 and x0_raw.shape == (n,):
        return x0_raw
    if x0_raw.ndim == 2 and x0_raw.shape == (n, 1):
        return x0_raw.reshape((n,))
    raise DimensionMismatchError(
        message=f"Vetor x0 deve ter shape ({n},) ou ({n}, 1), recebido {x0_raw.shape}.",
        parameters={"expected_n": n, "actual_shape": list(x0_raw.shape)},
    )


def handle_failure(
    exc: ControlLabError,
    *,
    raise_on_error: bool,
    provenance: Any,
    assumptions: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    warnings_out: Sequence[Any] = (),
) -> Any:
    """Re-lança exceção ou encapsula em Result(status='failure') conforme raise_on_error."""
    if raise_on_error:
        raise exc
    from control_lab.diagnostics import Result

    return Result(
        status="failure",
        data=None,
        assumptions=assumptions if assumptions is not None else {},
        diagnostics=diagnostics if diagnostics is not None else {},
        provenance=provenance,
        warnings=tuple(warnings_out),
        error=exc.to_typed_error(),
    )
