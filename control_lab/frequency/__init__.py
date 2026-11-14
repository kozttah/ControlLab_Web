"""Núcleo de análise e síntese no domínio da frequência SISO e MIMO (CL-DIR-001 Seções 5.3, 5.5 e 13.5)."""

from __future__ import annotations

from typing import Any

from control_lab.diagnostics import Result

from . import mimo, siso
from .mimo import (
    eval_mimo_response,
    nyquist_generalized,
    rga,
    sensitivity,
    singular_values,
)
from .siso import (
    REQUIREMENT_CLASSIFICATIONS,
    bode,
    classify_requirement_overlays,
    design_lag,
    design_lead,
    design_lead_lag,
    design_pid,
    eval_response as eval_siso_response,
    nyquist_siso,
    root_locus,
    stability_margins,
    step_response_siso,
)


def eval_response(plant: Any, omega: Any = None, **kwargs: Any) -> Result:
    """Despacha avaliação de resposta em frequência para SISO (1x1) ou MIMO (p x m)."""
    n_in = getattr(plant, "n_inputs", None)
    n_out = getattr(plant, "n_outputs", None)
    if n_in is not None and n_out is not None and (n_in > 1 or n_out > 1):
        return eval_mimo_response(plant, omega, **kwargs)
    return eval_siso_response(plant, omega, **kwargs)


__all__ = [
    "REQUIREMENT_CLASSIFICATIONS",
    "bode",
    "classify_requirement_overlays",
    "design_lag",
    "design_lead",
    "design_lead_lag",
    "design_pid",
    "eval_mimo_response",
    "eval_response",
    "eval_siso_response",
    "mimo",
    "nyquist_generalized",
    "nyquist_siso",
    "rga",
    "root_locus",
    "sensitivity",
    "singular_values",
    "siso",
    "stability_margins",
    "step_response_siso",
]
