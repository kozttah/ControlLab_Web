"""Classe base abstrata e contratos estruturais de backends SDP/LP (CL-DIR-001 Seção 6.2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from control_lab.diagnostics import ControlLabError, TypedError

UNAVAILABLE_REASONS: tuple[str, ...] = (
    "unsupported_psd",
    "missing_wasm_wheel",
    "out_of_memory",
    "unsupported_cone",
    "missing_dependency",
    "experimental_not_registered",
)


class SolverUnavailableError(ControlLabError):
    """Erro tipado SOLVER_UNAVAILABLE com razão estruturada."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "missing_dependency",
        backend: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        next_step: str | None = None,
    ) -> None:
        params = dict(parameters or {})
        params["reason"] = reason
        if backend is not None:
            params["backend"] = backend
        super().__init__(
            code="SOLVER_UNAVAILABLE",
            message=message,
            parameters=params,
            next_step=next_step,
        )


class SDPBackend(ABC):
    """Interface base para adaptadores de solver SDP/LP."""

    name: str = "base"
    maturity: str = "beta"
    is_experimental: bool = False

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        """Retorna dicionário descritivo de capacidades reais do backend."""

    @abstractmethod
    def solve_raw(
        self,
        problem: Any,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Executa o solver sobre CanonicalSDPProblem e retorna saída bruta estruturada.

        Em caso de indisponibilidade/incompatibilidade estrutural do backend, deve levantar
        SolverUnavailableError.
        """
