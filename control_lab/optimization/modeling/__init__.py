"""Modelagem canônica SDP/LMI, DSL afim e templates de controle (CL-DIR-001 Seção 6.1, 6.4)."""

from .canonical import CanonicalSDPProblem, SDPBlock, compile
from .dsl import (
    AffineExpr,
    LMIBlockConstraint,
    LinearEqConstraint,
    LinearIneqConstraint,
    SDPVar,
    bmat,
    linear_eq,
    linear_ineq,
    psd,
    sdpvar,
    trace,
)
from .svec import (
    DEFAULT_SYMMETRY_TOL,
    is_diagonal_matrix,
    smat,
    smat_dim,
    svec,
    svec_dim,
    symmetric_basis_matrices,
    symmetry_error_rel,
)
from .templates import (
    continuous_stabilization_lmi,
    hinf_brl_lmi,
    regional_pole_placement_lmi,
    ts_pdc_stabilization_lmi,
)

__all__ = [
    "AffineExpr",
    "CanonicalSDPProblem",
    "DEFAULT_SYMMETRY_TOL",
    "LMIBlockConstraint",
    "LinearEqConstraint",
    "LinearIneqConstraint",
    "SDPBlock",
    "SDPVar",
    "bmat",
    "compile",
    "continuous_stabilization_lmi",
    "hinf_brl_lmi",
    "is_diagonal_matrix",
    "linear_eq",
    "linear_ineq",
    "psd",
    "regional_pole_placement_lmi",
    "sdpvar",
    "smat",
    "smat_dim",
    "svec",
    "svec_dim",
    "symmetric_basis_matrices",
    "symmetry_error_rel",
    "trace",
    "ts_pdc_stabilization_lmi",
]
