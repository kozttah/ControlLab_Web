"""Backend direto para Clarabel via svec/PSDTriangleConeT (CL-DIR-001 Seção 6.1, 6.2)."""

from __future__ import annotations

import importlib
import importlib.metadata
import math
from typing import Any, Mapping

import numpy as np
import scipy.sparse as sp

from control_lab.diagnostics import ValidationError, WarningItem

from ..modeling.canonical import CanonicalSDPProblem
from ..modeling.svec import smat, svec, svec_dim
from .base import SDPBackend, SolverUnavailableError


def _import_clarabel() -> Any | None:
    try:
        return importlib.import_module("clarabel")
    except Exception:
        return None


def _clarabel_version() -> str | None:
    try:
        return importlib.metadata.version("clarabel")
    except Exception:
        return None


def _build_clarabel_matrices(
    problem: CanonicalSDPProblem, clarabel_mod: Any
) -> tuple[sp.csc_matrix, np.ndarray, sp.csc_matrix, np.ndarray, list[Any], dict[str, Any]]:
    n_vars = problem.n_vars
    P_mat = sp.csc_matrix((n_vars, n_vars), dtype=np.float64)
    q_vec = np.array(problem.c, dtype=np.float64, copy=True)

    A_rows: list[np.ndarray] = []
    b_parts: list[np.ndarray] = []
    cones: list[Any] = []
    slices: dict[str, Any] = {"eq": None, "ineq": None, "psd": []}
    offset = 0

    if problem.n_eq > 0:
        A_rows.append(problem.E)
        b_parts.append(problem.d)
        cones.append(clarabel_mod.ZeroConeT(problem.n_eq))
        slices["eq"] = (offset, offset + problem.n_eq)
        offset += problem.n_eq

    if problem.n_ineq > 0:
        A_rows.append(problem.H)
        b_parts.append(problem.h)
        cones.append(clarabel_mod.NonnegativeConeT(problem.n_ineq))
        slices["ineq"] = (offset, offset + problem.n_ineq)
        offset += problem.n_ineq

    for blk in problem.blocks:
        tri_dim = svec_dim(blk.dim)
        A_blk = np.zeros((tri_dim, n_vars), dtype=np.float64)
        for k, fk in blk.F_terms.items():
            A_blk[:, k] = -svec(fk)
        b_blk = svec(blk.F0)
        A_rows.append(A_blk)
        b_parts.append(b_blk)
        cones.append(clarabel_mod.PSDTriangleConeT(blk.dim))
        slices["psd"].append((offset, offset + tri_dim, blk.dim))
        offset += tri_dim

    if A_rows:
        A_mat = sp.csc_matrix(np.vstack(A_rows), dtype=np.float64)
        b_vec = np.concatenate(b_parts).astype(np.float64, copy=False)
    else:
        A_mat = sp.csc_matrix((0, n_vars), dtype=np.float64)
        b_vec = np.zeros((0,), dtype=np.float64)

    return P_mat, q_vec, A_mat, b_vec, cones, slices


def _extract_duals(z_vec: np.ndarray, slices: Mapping[str, Any]) -> tuple[list[np.ndarray], np.ndarray | None, np.ndarray | None]:
    dual_eq = None
    if slices["eq"] is not None:
        i0, i1 = slices["eq"]
        dual_eq = np.array(z_vec[i0:i1], dtype=np.float64, copy=True)

    dual_ineq = None
    if slices["ineq"] is not None:
        i0, i1 = slices["ineq"]
        dual_ineq = np.array(z_vec[i0:i1], dtype=np.float64, copy=True)

    dual_Z: list[np.ndarray] = []
    for i0, i1, dim in slices["psd"]:
        dual_Z.append(smat(z_vec[i0:i1], n=dim))
    return dual_Z, dual_eq, dual_ineq


class ClarabelDirectBackend(SDPBackend):
    """Adaptador direto para o solver cônico Clarabel utilizando svec/PSDTriangleConeT."""

    name: str = "clarabel_direct"
    maturity: str = "beta"
    is_experimental: bool = False

    def __init__(self, *, settings_overrides: Mapping[str, Any] | None = None) -> None:
        self._settings_overrides = dict(settings_overrides or {})

    def capabilities(self) -> dict[str, Any]:
        clb = _import_clarabel()
        ver = _clarabel_version()
        avail = clb is not None
        return {
            "name": self.name,
            "maturity": self.maturity if avail else "unavailable_wasm",
            "available": avail,
            "experimental": False,
            "psd": avail,
            "lp": avail,
            "dual": avail,
            "infeasibility_certificate": avail,
            "unboundedness_certificate": avail,
            "warm_start": False,
            "cancellation": False,
            "tolerances": {
                "configurable": True,
                "tol_feas": float(self._settings_overrides.get("tol_feas", 1e-8)),
                "tol_gap_abs": float(self._settings_overrides.get("tol_gap_abs", 1e-8)),
                "tol_gap_rel": float(self._settings_overrides.get("tol_gap_rel", 1e-8)),
                "max_iter": int(self._settings_overrides.get("max_iter", 200)),
            },
            "reason": None if avail else "missing_dependency",
            "lib_versions": {"clarabel": ver} if ver is not None else {},
        }

    def _build_settings(self, clarabel_mod: Any, options: Mapping[str, Any] | None) -> Any:
        settings = clarabel_mod.DefaultSettings()
        settings.verbose = False
        merged = {**self._settings_overrides, **dict(options or {})}
        allowed = (
            "tol_feas",
            "tol_gap_abs",
            "tol_gap_rel",
            "tol_infeas_abs",
            "tol_infeas_rel",
            "tol_ktratio",
            "max_iter",
            "time_limit",
            "verbose",
            "equilibrate_enable",
            "presolve_enable",
        )
        for key, val in merged.items():
            if key not in allowed:
                raise ValidationError(f"Opção desconhecida para ClarabelDirectBackend: {key!r}.")
            setattr(settings, key, val)
        return settings

    def solve_raw(
        self,
        problem: Any,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(f"ClarabelDirectBackend requer CanonicalSDPProblem, recebido {type(problem).__name__}.")
        clb = _import_clarabel()
        if clb is None:
            raise SolverUnavailableError(
                "Biblioteca 'clarabel' não está disponível neste ambiente.",
                reason="missing_dependency",
                backend=self.name,
                next_step="Instale clarabel>=0.9 ou utilize ScipyLinprogBackend para blocos diagonais.",
            )

        settings = self._build_settings(clb, options)
        P_mat, q_vec, A_mat, b_vec, cones, slices = _build_clarabel_matrices(problem, clb)
        solver = clb.DefaultSolver(P_mat, q_vec, A_mat, b_vec, cones, settings)
        sol = solver.solve()

        raw_status = str(sol.status)
        warnings_list: list[WarningItem] = []

        if sol.status == clb.SolverStatus.Solved:
            solver_status = "optimal"
        elif sol.status == clb.SolverStatus.AlmostSolved:
            solver_status = "optimal_inaccurate"
            warnings_list.append(
                WarningItem(
                    code="CLARABEL_ALMOST_SOLVED",
                    message="Clarabel terminou com AlmostSolved (precisão reduzida).",
                )
            )
        elif sol.status == clb.SolverStatus.PrimalInfeasible:
            solver_status = "primal_infeasible"
        elif sol.status == clb.SolverStatus.AlmostPrimalInfeasible:
            solver_status = "primal_infeasible"
            warnings_list.append(
                WarningItem(
                    code="CLARABEL_ALMOST_PRIMAL_INFEASIBLE",
                    message="Clarabel terminou com AlmostPrimalInfeasible; certificado será auditado.",
                )
            )
        elif sol.status == clb.SolverStatus.DualInfeasible:
            solver_status = "dual_infeasible"
        elif sol.status == clb.SolverStatus.AlmostDualInfeasible:
            solver_status = "dual_infeasible"
            warnings_list.append(
                WarningItem(
                    code="CLARABEL_ALMOST_DUAL_INFEASIBLE",
                    message="Clarabel terminou com AlmostDualInfeasible; direção recessiva será auditada.",
                )
            )
        elif sol.status in (clb.SolverStatus.MaxIterations, clb.SolverStatus.MaxTime):
            solver_status = "max_iterations"
        elif sol.status in (clb.SolverStatus.NumericalError, clb.SolverStatus.InsufficientProgress):
            solver_status = "numerical_error"
        else:
            solver_status = "unknown"

        x_arr = np.asarray(sol.x, dtype=np.float64) if sol.x is not None else None
        z_arr = np.asarray(sol.z, dtype=np.float64) if sol.z is not None else None
        x_finite = x_arr is not None and x_arr.shape == (problem.n_vars,) and bool(np.all(np.isfinite(x_arr)))
        z_finite = z_arr is not None and bool(np.all(np.isfinite(z_arr)))

        obj_val: float | None = None
        if sol.obj_val is not None and math.isfinite(float(sol.obj_val)) and solver_status not in ("primal_infeasible", "dual_infeasible"):
            obj_val = float(sol.obj_val) + problem.c0

        out: dict[str, Any] = {
            "backend": self.name,
            "solver_status": solver_status,
            "raw_status": raw_status,
            "iterations": int(sol.iterations),
            "solve_time": float(sol.solve_time) if math.isfinite(float(sol.solve_time)) else None,
            "r_prim": float(sol.r_prim) if math.isfinite(float(sol.r_prim)) else None,
            "r_dual": float(sol.r_dual) if math.isfinite(float(sol.r_dual)) else None,
            "objective": obj_val,
            "warnings": warnings_list,
        }

        if solver_status == "primal_infeasible":
            if z_finite:
                fZ, f_eq, f_ineq = _extract_duals(z_arr, slices)  # type: ignore[arg-type]
                out["farkas_Z"] = fZ
                out["farkas_eq"] = f_eq
                out["farkas_ineq"] = f_ineq
        elif solver_status == "dual_infeasible":
            if x_finite:
                out["recession_direction"] = x_arr
            # Checagem auxiliar q=0 para obter ponto factível x0 ou comprovar infactibilidade primal simultânea
            zero_q = np.zeros((problem.n_vars,), dtype=np.float64)
            sol0 = clb.DefaultSolver(P_mat, zero_q, A_mat, b_vec, cones, settings).solve()
            if sol0.status in (clb.SolverStatus.Solved, clb.SolverStatus.AlmostSolved) and sol0.x is not None:
                x0_arr = np.asarray(sol0.x, dtype=np.float64)
                if x0_arr.shape == (problem.n_vars,) and np.all(np.isfinite(x0_arr)):
                    out["feasible_x0"] = x0_arr
            elif sol0.status in (clb.SolverStatus.PrimalInfeasible, clb.SolverStatus.AlmostPrimalInfeasible):
                out["simultaneous_primal_infeasible"] = True
                if sol0.z is not None and np.all(np.isfinite(sol0.z)):
                    fZ0, f_eq0, f_ineq0 = _extract_duals(np.asarray(sol0.z, dtype=np.float64), slices)
                    out["solver_status"] = "primal_infeasible"
                    out["farkas_Z"] = fZ0
                    out["farkas_eq"] = f_eq0
                    out["farkas_ineq"] = f_ineq0
        else:
            if x_finite:
                out["x"] = x_arr
            if z_finite:
                dZ, d_eq, d_ineq = _extract_duals(z_arr, slices)  # type: ignore[arg-type]
                out["dual_Z"] = dZ
                out["dual_eq"] = d_eq
                out["dual_ineq"] = d_ineq

        return out
