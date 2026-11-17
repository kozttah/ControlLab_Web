"""Registro e introspecção de capacidades de backends SDP/LP (CL-DIR-001 Seção 6.2)."""

from __future__ import annotations

import sys
from typing import Any

from control_lab.diagnostics import ValidationError, ensure_json_finite

from ..modeling.canonical import CanonicalSDPProblem
from .native import NativePrimalDualBackend
from .base import SDPBackend
from .clarabel_cvxpy import ClarabelCvxpyBackend
from .clarabel_direct import ClarabelDirectBackend
from .scipy_linprog import ScipyLinprogBackend
from .unavailable import EducationalBarrierBackend, UnavailableBackend

_BACKEND_REGISTRY: dict[str, type[SDPBackend]] = {
    "native_primal_dual": NativePrimalDualBackend,
    "clarabel_direct": ClarabelDirectBackend,
    "clarabel_cvxpy": ClarabelCvxpyBackend,
    "scipy_linprog": ScipyLinprogBackend,
    "educational_barrier": EducationalBarrierBackend,
    "unavailable": UnavailableBackend,
}


def get_backend(
    backend: str | SDPBackend = "auto",
    *,
    problem: CanonicalSDPProblem | None = None,
) -> SDPBackend:
    """Resolve nome ou instância de backend SDP/LP. Nunca seleciona EducationalBarrierBackend em 'auto'."""
    if isinstance(backend, SDPBackend):
        return backend
    if not isinstance(backend, str) or not backend.strip():
        raise ValidationError(f"backend inválido: {backend!r}. Esperado instância SDPBackend ou nome válido.")
    key = backend.strip().lower()

    if key == "auto":
        if problem is not None and problem.all_blocks_diagonal():
            return ScipyLinprogBackend()
        if sys.platform == "emscripten":
            return NativePrimalDualBackend()
        direct = ClarabelDirectBackend()
        if direct.capabilities()["available"]:
            return direct
        cvx = ClarabelCvxpyBackend()
        if cvx.capabilities()["available"]:
            return cvx
        if problem is not None and problem.all_blocks_diagonal():
            return ScipyLinprogBackend()
        return NativePrimalDualBackend()

    if key not in _BACKEND_REGISTRY:
        raise ValidationError(
            message=f"Backend desconhecido: {backend!r}. Disponíveis: {sorted(_BACKEND_REGISTRY.keys()) + ['auto']}.",
            parameters={"backend": backend, "available_names": sorted(_BACKEND_REGISTRY.keys())},
        )
    return _BACKEND_REGISTRY[key]()


def describe_solver_capabilities(
    backend: str | SDPBackend | type[SDPBackend] = "auto",
) -> dict[str, Any]:
    """Anuncia capacidades reais, maturidade, suporte a cones/duais e versões de um backend."""
    if isinstance(backend, type) and issubclass(backend, SDPBackend):
        inst = backend()
    elif isinstance(backend, str) and backend.strip().lower() == "all":
        return ensure_json_finite(
            {
                name: cls().capabilities()
                for name, cls in _BACKEND_REGISTRY.items()
            }
        )
    else:
        inst = get_backend(backend)
    return ensure_json_finite(inst.capabilities())
