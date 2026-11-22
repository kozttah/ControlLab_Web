"""Núcleo de Controle Fuzzy, Takagi-Sugeno, FML IEEE 1855-2016 e ANFIS — Frente F5 (CL-DIR-001 Seções 4.3, 5.6, 9.4, 13.7, R-05 e R-10).

Reexporta a API pública de controle fuzzy:
- Funções de pertinência e operadores: `triangular`, `trapezoidal`, `gaussian`, `bell`, `sigmoid`, `singleton`, `z_shape`, `s_shape`, `linear`, `evaluate_mf`, `apply_t_norm`, `apply_s_norm`;
- Motor de inferência e validação: `evaluate`, `evaluate_surface`, `check_rule_coverage`, `defuzzify_curve`;
- Interoperabilidade IEEE 1855-2016 FML (anti-XXE): `export_fml`, `import_fml`;
- Aprendizado neuro-fuzzy: `fit_anfis` (QR/SVD + gradiente descendente);
- Ponte Takagi-Sugeno e especificações PDC (`ADR-006`, `T-TS-01`): `to_ts_state_space`, `make_pdc_spec`, `verify_convex_weights`, `evaluate_ts_premise_weights`, `evaluate_ts_frozen_weights`.
"""

from control_lab.core.controllers import PDCController, StateFeedbackController
from control_lab.core.interconnect import TSClosedLoop
from control_lab.core.models import FuzzySystem, StateSpace, TSStateSpace
from control_lab.diagnostics import Result

from .anfis import fit_anfis
from .fml import (
    DEFAULT_MAX_FML_BYTES,
    DEFAULT_MAX_XML_DEPTH,
    DEFAULT_MAX_XML_ELEMENTS,
    export_fml,
    import_fml,
)
from .inference import (
    SUPPORTED_DEFUZZ_METHODS,
    check_rule_coverage,
    defuzzify_curve,
    evaluate,
    evaluate_surface,
    normalize_defuzz_method,
)
from .membership import (
    SUPPORTED_MF_TYPES,
    apply_s_norm,
    apply_t_norm,
    bell,
    evaluate_mf,
    extract_term_spec,
    gaussian,
    linear,
    normalize_mf_type,
    s_shape,
    sigmoid,
    singleton,
    trapezoidal,
    triangular,
    z_shape,
)
from .ts_bridge import (
    evaluate_ts_frozen_weights,
    evaluate_ts_premise_weights,
    make_pdc_spec,
    to_ts_state_space,
    verify_convex_weights,
)
from .ts_observer import (
    TSUnmeasuredObserverSpec,
    build_dmvt_nonlinearity_spec,
    build_gradient_factorization_spec,
    simulate_ts_unmeasured_observer,
)

__all__ = [
    "DEFAULT_MAX_FML_BYTES",
    "DEFAULT_MAX_XML_DEPTH",
    "DEFAULT_MAX_XML_ELEMENTS",
    "SUPPORTED_DEFUZZ_METHODS",
    "SUPPORTED_MF_TYPES",
    "FuzzySystem",
    "PDCController",
    "Result",
    "StateFeedbackController",
    "StateSpace",
    "TSClosedLoop",
    "TSStateSpace",
    "TSUnmeasuredObserverSpec",
    "apply_s_norm",
    "apply_t_norm",
    "bell",
    "build_dmvt_nonlinearity_spec",
    "build_gradient_factorization_spec",
    "check_rule_coverage",
    "defuzzify_curve",
    "evaluate",
    "evaluate_mf",
    "evaluate_surface",
    "evaluate_ts_frozen_weights",
    "evaluate_ts_premise_weights",
    "export_fml",
    "extract_term_spec",
    "fit_anfis",
    "gaussian",
    "import_fml",
    "linear",
    "make_pdc_spec",
    "normalize_defuzz_method",
    "normalize_mf_type",
    "s_shape",
    "sigmoid",
    "simulate_ts_unmeasured_observer",
    "singleton",
    "to_ts_state_space",
    "trapezoidal",
    "triangular",
    "verify_convex_weights",
    "z_shape",
]
