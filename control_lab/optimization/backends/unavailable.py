"""Backends estruturalmente indisponível (UnavailableBackend) e didático isolado (EducationalBarrierBackend).

Nota de arquitetura (CL-DIR-001 Seção 6.2, ADR-008 e Seção 13.8):
`control_lab/optimization/` NUNCA importa `control_lab/experimental/`. O `EducationalBarrierBackend`
aceita injeção explícita de um executável experimental (quando fornecido pelo WP-10) sem acoplamento
de importação e jamais serve como backend padrão ou certificador silencioso.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from control_lab.diagnostics import ValidationError, ensure_json_finite

from ..modeling.canonical import CanonicalSDPProblem
from .base import SDPBackend, SolverUnavailableError, UNAVAILABLE_REASONS


class UnavailableBackend(SDPBackend):
    """Backend explícito para representar indisponibilidade estruturada (SOLVER_UNAVAILABLE)."""

    name: str = "unavailable"
    maturity: str = "unavailable_wasm"
    is_experimental: bool = False

    def __init__(self, *, reason: str = "missing_wasm_wheel", detail: str | None = None) -> None:
        if reason not in UNAVAILABLE_REASONS:
            raise ValidationError(
                f"reason inválido para UnavailableBackend: {reason!r}. Esperado um de {UNAVAILABLE_REASONS}."
            )
        self._reason = reason
        self._detail = detail

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "maturity": self.maturity,
            "available": False,
            "experimental": False,
            "psd": False,
            "lp": False,
            "dual": False,
            "infeasibility_certificate": False,
            "unboundedness_certificate": False,
            "warm_start": False,
            "cancellation": False,
            "tolerances": {"configurable": False},
            "reason": self._reason,
            "lib_versions": {},
        }

    def solve_raw(
        self,
        problem: Any,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = options
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(f"UnavailableBackend requer CanonicalSDPProblem, recebido {type(problem).__name__}.")
        msg = self._detail or f"Solver SDP indisponível neste runtime (reason={self._reason!r})."
        raise SolverUnavailableError(
            message=msg,
            reason=self._reason,
            backend=self.name,
            next_step="Utilize um backend disponível ou exporte o script CPython local via export_cpython_script().",
        )


class EducationalBarrierBackend(SDPBackend):
    """Adaptador didático isolado para métodos de barreira/pontos interiores (sem garantia automática).

    Não importa nenhum módulo de `experimental/`; aceita apenas um callable injetado em runtime.
    """

    name: str = "educational_barrier"
    maturity: str = "experimental"
    is_experimental: bool = True

    def __init__(
        self,
        solver_fn: Callable[[CanonicalSDPProblem, Mapping[str, Any] | None], Mapping[str, Any]] | None = None,
        *,
        solver_capabilities: Mapping[str, Any] | None = None,
    ) -> None:
        if solver_fn is not None and not callable(solver_fn):
            raise ValidationError("solver_fn de EducationalBarrierBackend deve ser callable.")
        self._solver_fn = solver_fn
        # Registration metadata is explicit: an arbitrary callable does not imply
        # support for dual solutions, Farkas/recession certificates or versions.
        self._solver_capabilities = ensure_json_finite(dict(solver_capabilities or {}))

    def capabilities(self) -> dict[str, Any]:
        has_fn = self._solver_fn is not None
        caps = {
            "name": self.name,
            "maturity": "experimental",
            "available": has_fn,
            "experimental": True,
            "certified": False,
            "psd": has_fn,
            "lp": has_fn,
            "dual": False,
            "infeasibility_certificate": False,
            "unboundedness_certificate": False,
            "warm_start": False,
            "cancellation": False,
            "tolerances": {"configurable": has_fn},
            "reason": None if has_fn else "experimental_not_registered",
            "lib_versions": {},
        }
        if has_fn:
            caps.update(ensure_json_finite(self._solver_capabilities))
        # A descriptor cannot promote the educational adapter or certify a result.
        caps.update(name=self.name, maturity="experimental", available=has_fn,
                    experimental=True, certified=False,
                    reason=None if has_fn else "experimental_not_registered")
        return caps

    def solve_raw(
        self,
        problem: Any,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(f"EducationalBarrierBackend requer CanonicalSDPProblem, recebido {type(problem).__name__}.")
        if self._solver_fn is None:
            raise SolverUnavailableError(
                message=(
                    "EducationalBarrierBackend está isolado e não possui implementação experimental registrada "
                    "(reason='experimental_not_registered'). Nunca é utilizado como backend padrão."
                ),
                reason="experimental_not_registered",
                backend=self.name,
                next_step="Forneça um backend de produção (clarabel_direct / clarabel_cvxpy) ou injete solver_fn didático.",
            )
        raw = dict(self._solver_fn(problem, options))
        raw["backend"] = self.name
        raw["experimental"] = True
        return raw
