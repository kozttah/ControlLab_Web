"""Núcleo de análise e síntese em espaço de estados (CL-DIR-001 Seção 5.4, 10.2 e 13.4)."""

from .analysis import analyze, check_pbh, gramians
from .design import (
    design_kalman,
    design_lqg,
    design_lqi,
    design_lqr,
    design_observer,
    design_pole_placement,
)
from .equations import solve_care, solve_dare, solve_lyapunov, solve_sylvester
from .simulation import discretize_zoh, simulate_lti

__all__ = [
    "analyze",
    "check_pbh",
    "design_kalman",
    "design_lqg",
    "design_lqi",
    "design_lqr",
    "design_observer",
    "design_pole_placement",
    "discretize_zoh",
    "gramians",
    "simulate_lti",
    "solve_care",
    "solve_dare",
    "solve_lyapunov",
    "solve_sylvester",
]
