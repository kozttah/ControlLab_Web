"""Solver didático isolado de Pontos Interiores Primal-Dual (R-13 / ADR-008 / CL-DIR-001 Seção 6.5).

Este pacote possui maturidade estritamente `"experimental"` (`experimental=True`),
nunca atua como backend padrão de produção em `get_backend("auto")` e tem toda saída
auditada pelo verificador espectral independente em 5 dimensões (`verify()`).
"""

from .solver import (
    EducationalPrimalDualSDPBackend,
    EducationalSolverConfig,
    IterationRecord,
    make_educational_barrier_backend,
    solve_sdp_educational,
    solve_sdp_educational_raw,
)
from .suite import run_educational_levels_a_to_d_suite

__all__ = [
    "EducationalPrimalDualSDPBackend",
    "EducationalSolverConfig",
    "IterationRecord",
    "make_educational_barrier_backend",
    "run_educational_levels_a_to_d_suite",
    "solve_sdp_educational",
    "solve_sdp_educational_raw",
]
