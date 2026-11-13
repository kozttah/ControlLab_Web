"""Backend Clarabel via CVXPY (CL-DIR-001 Seção 6.2 e Gate G-0B)."""

from __future__ import annotations

import importlib
import importlib.metadata
import math
from typing import Any, Mapping

import numpy as np

from control_lab.diagnostics import ValidationError, WarningItem

from ..modeling.canonical import CanonicalSDPProblem
from .base import SDPBackend, SolverUnavailableError


def _import_cvxpy_clarabel() -> tuple[Any | None, str | None, str | None]:
    try:
        cp = importlib.import_module("cvxpy")
        clb = importlib.import_module("clarabel")
        _ = clb
    except Exception:
        return None, None, None

    try:
        installed = list(cp.installed_solvers())
    except Exception:
        installed = []
    if "CLARABEL" not in installed:
        return None, None, None

    try:
        cvx_ver = importlib.metadata.version("cvxpy")
    except Exception:
        try:
            cvx_ver = importlib.metadata.version("cvxpy-base")
        except Exception:
            cvx_ver = None
    try:
        clb_ver = importlib.metadata.version("clarabel")
    except Exception:
        clb_ver = None
    return cp, cvx_ver, clb_ver


class ClarabelCvxpyBackend(SDPBackend):
    """Adaptador CVXPY configurado exclusivamente com solver=CLARABEL."""

    name: str = "clarabel_cvxpy"
    maturity: str = "beta"
    is_experimental: bool = False

    def __init__(self, *, solver_options: Mapping[str, Any] | None = None) -> None:
        self._solver_options = dict(solver_options or {})

    def capabilities(self) -> dict[str, Any]:
        cp, cvx_ver, clb_ver = _import_cvxpy_clarabel()
        avail = cp is not None
        versions: dict[str, str] = {}
        if cvx_ver is not None:
            versions["cvxpy"] = cvx_ver
        if clb_ver is not None:
            versions["clarabel"] = clb_ver
        return {
            "name": self.name,
            "maturity": self.maturity if avail else "unavailable_wasm",
            "available": avail,
            "experimental": False,
            "psd": avail,
            "lp": avail,
            "dual": avail,
            "infeasibility_certificate": avail,
            "unboundedness_certificate": False,
            "warm_start": False,
            "cancellation": False,
            "tolerances": {
                "configurable": True,
                "tol_feas": float(self._solver_options.get("tol_feas", 1e-8)),
                "tol_gap_abs": float(self._solver_options.get("tol_gap_abs", 1e-8)),
                "tol_gap_rel": float(self._solver_options.get("tol_gap_rel", 1e-8)),
                "max_iter": int(self._solver_options.get("max_iter", 200)),
            },
            "reason": None if avail else "missing_dependency",
            "lib_versions": versions,
        }

    def solve_raw(
        self,
        problem: Any,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(f"ClarabelCvxpyBackend requer CanonicalSDPProblem, recebido {type(problem).__name__}.")
        cp, _, _ = _import_cvxpy_clarabel()
        if cp is None:
            raise SolverUnavailableError(
                "Pacotes 'cvxpy'/'cvxpy-base' com solver 'CLARABEL' não estão disponíveis neste ambiente.",
                reason="missing_dependency",
                backend=self.name,
                next_step="Instale cvxpy-base e clarabel ou utilize ScipyLinprogBackend para blocos diagonais.",
            )

        merged_opts = {**self._solver_options, **dict(options or {})}
        merged_opts.setdefault("verbose", False)

        x = cp.Variable(problem.n_vars)
        constraints: list[Any] = []
        eq_con = None
        if problem.n_eq > 0:
            eq_con = problem.E @ x == problem.d
            constraints.append(eq_con)
        ineq_con = None
        if problem.n_ineq > 0:
            ineq_con = problem.H @ x <= problem.h
            constraints.append(ineq_con)

        psd_cons: list[Any] = []
        for blk in problem.blocks:
            expr = blk.F0
            for k, fk in blk.F_terms.items():
                expr = expr + x[k] * fk
            con = expr >> 0
            psd_cons.append(con)
            constraints.append(con)

        obj = cp.Minimize(problem.c @ x + problem.c0)
        cvx_prob = cp.Problem(obj, constraints)

        try:
            cvx_prob.solve(solver=cp.CLARABEL, **merged_opts)
        except Exception as exc:
            return {
                "backend": self.name,
                "solver_status": "numerical_error",
                "raw_status": f"exception:{type(exc).__name__}:{exc}",
                "objective": None,
                "warnings": [
                    WarningItem(code="CVXPY_SOLVE_EXCEPTION", message=f"Erro durante solve CVXPY: {exc}")
                ],
            }

        raw_status = str(cvx_prob.status)
        warnings_list: list[WarningItem] = []

        if cvx_prob.status == cp.OPTIMAL:
            solver_status = "optimal"
        elif cvx_prob.status == cp.OPTIMAL_INACCURATE:
            solver_status = "optimal_inaccurate"
            warnings_list.append(
                WarningItem(
                    code="CVXPY_OPTIMAL_INACCURATE",
                    message="CVXPY/Clarabel reportou optimal_inaccurate.",
                )
            )
        elif cvx_prob.status == cp.INFEASIBLE:
            solver_status = "primal_infeasible"
        elif cvx_prob.status == cp.INFEASIBLE_INACCURATE:
            solver_status = "primal_infeasible"
            warnings_list.append(
                WarningItem(
                    code="CVXPY_INFEASIBLE_INACCURATE",
                    message="CVXPY/Clarabel reportou infeasible_inaccurate; certificado será auditado.",
                )
            )
        elif cvx_prob.status == cp.UNBOUNDED:
            solver_status = "dual_infeasible"
        elif cvx_prob.status == cp.UNBOUNDED_INACCURATE:
            solver_status = "dual_infeasible"
            warnings_list.append(
                WarningItem(
                    code="CVXPY_UNBOUNDED_INACCURATE",
                    message="CVXPY/Clarabel reportou unbounded_inaccurate.",
                )
            )
        elif cvx_prob.status == cp.SOLVER_ERROR:
            solver_status = "numerical_error"
        else:
            solver_status = "unknown"

        stats = getattr(cvx_prob, "solver_stats", None)
        solve_time = getattr(stats, "solve_time", None) if stats is not None else None
        num_iters = getattr(stats, "num_iters", None) if stats is not None else None

        obj_val: float | None = None
        if (
            cvx_prob.value is not None
            and math.isfinite(float(cvx_prob.value))
            and solver_status not in ("primal_infeasible", "dual_infeasible")
        ):
            obj_val = float(cvx_prob.value)

        out: dict[str, Any] = {
            "backend": self.name,
            "solver_status": solver_status,
            "raw_status": raw_status,
            "iterations": int(num_iters) if num_iters is not None else None,
            "solve_time": float(solve_time) if (solve_time is not None and math.isfinite(float(solve_time))) else None,
            "objective": obj_val,
            "warnings": warnings_list,
        }

        def _extract_duals_cvx() -> tuple[list[np.ndarray] | None, np.ndarray | None, np.ndarray | None]:
            dZ: list[np.ndarray] = []
            for con in psd_cons:
                dv = con.dual_value
                if dv is None:
                    return None, None, None
                arr = np.asarray(dv, dtype=np.float64)
                if not np.all(np.isfinite(arr)):
                    return None, None, None
                dZ.append(0.5 * (arr + arr.T))

            d_eq = None
            if eq_con is not None:
                if eq_con.dual_value is None:
                    return None, None, None
                d_eq = np.asarray(eq_con.dual_value, dtype=np.float64).reshape((problem.n_eq,))
                if not np.all(np.isfinite(d_eq)):
                    return None, None, None

            d_ineq = None
            if ineq_con is not None:
                if ineq_con.dual_value is None:
                    return None, None, None
                d_ineq = np.asarray(ineq_con.dual_value, dtype=np.float64).reshape((problem.n_ineq,))
                if not np.all(np.isfinite(d_ineq)):
                    return None, None, None

            return dZ, d_eq, d_ineq

        if solver_status == "primal_infeasible":
            fZ, f_eq, f_ineq = _extract_duals_cvx()
            if fZ is not None:
                out["farkas_Z"] = fZ
                out["farkas_eq"] = f_eq
                out["farkas_ineq"] = f_ineq
        elif solver_status != "dual_infeasible":
            if x.value is not None:
                x_arr = np.asarray(x.value, dtype=np.float64).reshape((problem.n_vars,))
                if np.all(np.isfinite(x_arr)):
                    out["x"] = x_arr
            dZ, d_eq, d_ineq = _extract_duals_cvx()
            if dZ is not None:
                out["dual_Z"] = dZ
                out["dual_eq"] = d_eq
                out["dual_ineq"] = d_ineq

        return out
