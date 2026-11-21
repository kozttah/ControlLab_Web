"""Subpacote MIMO no domínio da frequência (CL-DIR-001 Seções 5.5, 10.2 e 13.5)."""

from .analysis import (
    DEFAULT_RGA_COND_MAX,
    eval_mimo_response,
    nyquist_generalized,
    rga,
    sensitivity,
    singular_values,
)

from .synthesis import (
    design_hinf_mixed_sensitivity,
    design_svd_decoupler,
    simulate_mimo_closed_loop,
)

__all__ = [
    "DEFAULT_RGA_COND_MAX",
    "design_hinf_mixed_sensitivity",
    "design_svd_decoupler",
    "eval_mimo_response",
    "nyquist_generalized",
    "rga",
    "sensitivity",
    "simulate_mimo_closed_loop",
    "singular_values",
]
