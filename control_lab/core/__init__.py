"""Núcleo canônico de modelos científicos, tensores, controladores e interconexões."""

from control_lab.diagnostics import Result

from .controllers import (
    ALLOWED_PDC_TS_KINDS,
    FEEDBACK_SIGNS,
    INPUT_PORT_ROLES,
    INTERCONNECTION_SCHEMES,
    OUTPUT_PORT_ROLES,
    REFERENCE_MAP_KINDS,
    Controller,
    DynamicController,
    PDCController,
    StateFeedbackController,
)
from .interconnect import (
    TSClosedLoop,
    get_closed_loop_matrix,
    interconnect,
    make_closed_loop,
    validate_interconnection,
)
from .models import (
    PREMISE_MODES,
    TS_MODEL_KINDS,
    Dataset,
    Experiment,
    FuzzySystem,
    IdentifiedModel,
    StateSpace,
    TSStateSpace,
    TransferFunction,
)
from .serialization import load_model, restore_model, serialize_model
from .tensors import (
    array_to_tensor,
    complex_to_pair,
    ensure_finite_float64,
    pair_to_complex,
    tensor_to_array,
)

__all__ = [
    "ALLOWED_PDC_TS_KINDS",
    "FEEDBACK_SIGNS",
    "INPUT_PORT_ROLES",
    "INTERCONNECTION_SCHEMES",
    "OUTPUT_PORT_ROLES",
    "PREMISE_MODES",
    "REFERENCE_MAP_KINDS",
    "TS_MODEL_KINDS",
    "Controller",
    "Dataset",
    "DynamicController",
    "Experiment",
    "FuzzySystem",
    "IdentifiedModel",
    "PDCController",
    "Result",
    "StateFeedbackController",
    "StateSpace",
    "TSClosedLoop",
    "TSStateSpace",
    "TransferFunction",
    "array_to_tensor",
    "complex_to_pair",
    "ensure_finite_float64",
    "get_closed_loop_matrix",
    "interconnect",
    "load_model",
    "make_closed_loop",
    "pair_to_complex",
    "restore_model",
    "serialize_model",
    "tensor_to_array",
    "validate_interconnection",
]
