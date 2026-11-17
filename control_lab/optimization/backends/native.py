"""Bounded native SDP backend using the ADR-010 primal-dual kernel."""
from typing import Any, Mapping
import numpy as np
import scipy
from control_lab.diagnostics import ResourceLimitError, ValidationError
from ..modeling.canonical import CanonicalSDPProblem
from .base import SDPBackend
from .native_core import NativeSolverConfig, solve_native_raw

# Dense Schur systems and cone factorizations bound browser memory and latency.
BROWSER_ENVELOPE = {"max_variables": 128, "max_block_dimension": 48, "max_cone_entries": 16384}


def within_browser_envelope(problem: CanonicalSDPProblem) -> bool:
    return (problem.n_vars <= BROWSER_ENVELOPE["max_variables"]
            and max((b.dim for b in problem.blocks), default=0) <= BROWSER_ENVELOPE["max_block_dimension"]
            and sum(b.dim ** 2 for b in problem.blocks) + problem.n_ineq <= BROWSER_ENVELOPE["max_cone_entries"])


class NativePrimalDualBackend(SDPBackend):
    name = "native_primal_dual"
    maturity = "beta"
    is_experimental = False

    def capabilities(self) -> dict[str, Any]:
        return dict(name=self.name, maturity=self.maturity, available=True, experimental=False,
                    psd=True, lp=True, dual=True, infeasibility_certificate=True,
                    unboundedness_certificate=True, warm_start=False, cancellation=False,
                    tolerances={"configurable": True}, reason=None,
                    browser_envelope=dict(BROWSER_ENVELOPE),
                    lib_versions={"numpy": np.__version__, "scipy": scipy.__version__})

    def solve_raw(self, problem: CanonicalSDPProblem, *, options: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError("Native SDP requires CanonicalSDPProblem.")
        if not within_browser_envelope(problem):
            raise ResourceLimitError(
                "Problema acima do envelope SDP nativo recomendado. Exporte para Python/CVXPY ou MATLAB/YALMIP "
                "e execute offline com MOSEK, Clarabel, SeDuMi ou SDPT3.")
        NativeSolverConfig.from_options(options)
        return solve_native_raw(problem, options)
