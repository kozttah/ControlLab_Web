"""Backends de otimização SDP/LP e introspecção de capacidades (CL-DIR-001 Seção 6.2)."""

from .native import NativePrimalDualBackend
from .base import SDPBackend, SolverUnavailableError, UNAVAILABLE_REASONS
from .capabilities import describe_solver_capabilities, get_backend
from .clarabel_cvxpy import ClarabelCvxpyBackend
from .clarabel_direct import ClarabelDirectBackend
from .scipy_linprog import ScipyLinprogBackend
from .solve import solve, solve_and_verify
from .unavailable import EducationalBarrierBackend, UnavailableBackend

__all__ = [
    "NativePrimalDualBackend",
    "ClarabelCvxpyBackend",
    "ClarabelDirectBackend",
    "EducationalBarrierBackend",
    "SDPBackend",
    "ScipyLinprogBackend",
    "SolverUnavailableError",
    "UNAVAILABLE_REASONS",
    "UnavailableBackend",
    "describe_solver_capabilities",
    "get_backend",
    "solve",
    "solve_and_verify",
]
