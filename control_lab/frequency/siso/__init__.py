"""Subpacote SISO no domínio da frequência (CL-DIR-001 Seção 5.3 e 13.5)."""

from .design import (
    REQUIREMENT_CLASSIFICATIONS,
    classify_requirement_overlays,
    design_lag,
    design_lead,
    design_lead_lag,
    design_pid,
)
from .margins import stability_margins
from .response import bode, eval_response, nyquist_siso, step_response_siso
from .root_locus import root_locus

__all__ = [
    "REQUIREMENT_CLASSIFICATIONS",
    "bode",
    "classify_requirement_overlays",
    "design_lag",
    "design_lead",
    "design_lead_lag",
    "design_pid",
    "eval_response",
    "nyquist_siso",
    "root_locus",
    "stability_margins",
    "step_response_siso",
]
