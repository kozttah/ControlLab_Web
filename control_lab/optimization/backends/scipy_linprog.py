"""Fallback LP exato via scipy.optimize.linprog(..., method='highs') (CL-DIR-001 Seção 6.2).

Somente executa quando TODOS os blocos PSD do CanonicalSDPProblem reduzem exatamente
a escalares/diagonais; qualquer bloco PSD não diagonal é recusado explicitamente com
SOLVER_UNAVAILABLE (reason='unsupported_psd').
"""

from __future__ import annotations

import importlib.metadata
import math
from typing import Any, Mapping

import numpy as np
import scipy.optimize

from control_lab.diagnostics import ValidationError, WarningItem

from ..modeling.canonical import CanonicalSDPProblem
from .base import SDPBackend, SolverUnavailableError


def _scipy_version() -> str | None:
    try:
        return importlib.metadata.version("scipy")
    except Exception:
        return None


class ScipyLinprogBackend(SDPBackend):
    """Fallback LP exato (HiGHS) para SDPs puramente diagonais/escalares."""

    name: str = "scipy_linprog"
    maturity: str = "stable"
    is_experimental: bool = False

    def __init__(self, *, options: Mapping[str, Any] | None = None) -> None:
        self._options = dict(options or {})

    def capabilities(self) -> dict[str, Any]:
        ver = _scipy_version()
        return {
            "name": self.name,
            "maturity": self.maturity,
            "available": True,
            "experimental": False,
            "psd": False,
            "lp": True,
            "dual": True,
            "infeasibility_certificate": False,
            "unboundedness_certificate": False,
            "warm_start": False,
            "cancellation": False,
            "tolerances": {
                "configurable": True,
                "primal_feasibility_tolerance": float(self._options.get("primal_feasibility_tolerance", 1e-7)),
                "dual_feasibility_tolerance": float(self._options.get("dual_feasibility_tolerance", 1e-7)),
            },
            "reason": None,
            "lib_versions": {"scipy": ver} if ver is not None else {},
        }

    def solve_raw(
        self,
        problem: Any,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(f"ScipyLinprogBackend requer CanonicalSDPProblem, recebido {type(problem).__name__}.")

        non_diag = [blk.name for blk in problem.blocks if not blk.is_diagonal]
        if non_diag:
            raise SolverUnavailableError(
                message=(
                    f"ScipyLinprogBackend não suporta blocos PSD não diagonais: {non_diag}. "
                    "Recusa explícita (reason='unsupported_psd')."
                ),
                reason="unsupported_psd",
                backend=self.name,
                parameters={"non_diagonal_blocks": non_diag},
                next_step="Utilize ClarabelDirectBackend ou ClarabelCvxpyBackend para LMIs/blocos PSD gerais.",
            )

        # Reduzir blocos PSD diagonais F_{b,0}[i,i] + sum_k x_k F_{b,k}[i,i] >= 0
        # <=> sum_k (-F_{b,k}[i,i]) x_k <= F_{b,0}[i,i]
        ub_rows: list[np.ndarray] = []
        ub_rhs: list[float] = []
        block_row_counts: list[int] = []

        for blk in problem.blocks:
            dim = blk.dim
            block_row_counts.append(dim)
            A_b = np.zeros((dim, problem.n_vars), dtype=np.float64)
            for k, fk in blk.F_terms.items():
                A_b[:, k] = -np.diag(fk)
            b_b = np.diag(blk.F0)
            ub_rows.append(A_b)
            ub_rhs.extend(float(v) for v in b_b)

        if problem.n_ineq > 0:
            ub_rows.append(problem.H)
            ub_rhs.extend(float(v) for v in problem.h)

        A_ub = np.vstack(ub_rows) if ub_rows else None
        b_ub = np.array(ub_rhs, dtype=np.float64) if ub_rhs else None
        A_eq = problem.E if problem.n_eq > 0 else None
        b_eq = problem.d if problem.n_eq > 0 else None

        merged_opts = {**self._options, **dict(options or {})}
        res = scipy.optimize.linprog(
            c=problem.c,
            A_ub=A_ub,
            b_ub=b_ub,
            A_eq=A_eq,
            b_eq=b_eq,
            bounds=(None, None),
            method="highs",
            options=merged_opts if merged_opts else None,
        )

        warnings_list: list[WarningItem] = []
        if res.status == 0:
            solver_status = "optimal"
        elif res.status == 1:
            solver_status = "max_iterations"
        elif res.status == 2:
            solver_status = "primal_infeasible"
        elif res.status == 3:
            solver_status = "dual_infeasible"
        elif res.status == 4:
            solver_status = "numerical_error"
        else:
            solver_status = "unknown"

        obj_val: float | None = None
        if res.fun is not None and math.isfinite(float(res.fun)) and solver_status == "optimal":
            obj_val = float(res.fun) + problem.c0

        out: dict[str, Any] = {
            "backend": self.name,
            "solver_status": solver_status,
            "raw_status": f"highs:{res.status}:{res.message}",
            "iterations": int(res.nit) if hasattr(res, "nit") and res.nit is not None else None,
            "objective": obj_val,
            "warnings": warnings_list,
        }

        if solver_status == "optimal" and res.x is not None:
            x_arr = np.asarray(res.x, dtype=np.float64).reshape((problem.n_vars,))
            if np.all(np.isfinite(x_arr)):
                out["x"] = x_arr

            # Recuperar variáveis duais exatas a partir dos marginals do HiGHS
            if A_ub is not None and hasattr(res, "ineqlin") and res.ineqlin is not None and res.ineqlin.marginals is not None:
                lam_all = -np.asarray(res.ineqlin.marginals, dtype=np.float64)
                if np.all(np.isfinite(lam_all)):
                    dual_Z: list[np.ndarray] = []
                    offset = 0
                    for dim in block_row_counts:
                        dual_Z.append(np.diag(lam_all[offset : offset + dim]))
                        offset += dim
                    out["dual_Z"] = dual_Z
                    if problem.n_ineq > 0:
                        out["dual_ineq"] = np.array(lam_all[offset : offset + problem.n_ineq], dtype=np.float64, copy=True)
            elif len(block_row_counts) == 0 and problem.n_ineq == 0:
                out["dual_Z"] = []

            if problem.n_eq > 0 and hasattr(res, "eqlin") and res.eqlin is not None and res.eqlin.marginals is not None:
                nu_arr = -np.asarray(res.eqlin.marginals, dtype=np.float64)
                if np.all(np.isfinite(nu_arr)):
                    out["dual_eq"] = nu_arr

        return out
