"""Testes unitários e de contrato da Frente F1 para WP-01-F1-CORE-MODELS.

Cobre obrigatoriamente:
- T-CORE-01: Regras de dimensão (A 3x3, B 2x1 -> erro tipado sem objeto parcial)
- T-CORE-02: Realimentação estática (sinal negative/positive e prefiltro N não quadrado m != p)
- T-CORE-03: Controlador dinâmico com Dp != 0, Dc != 0 (solução analítica aumentada, caso singular, rejeição em get_closed_loop_matrix)
- T-TS-01: TSStateSpace (ts_measured, polytopic_uncertain, ts_partially_observed) e bloqueio de PDC em polytopic_uncertain
- Result imutável, todas as 12 categorias de erro, Provenance, rejeição de NaN/Inf,
  validação Draft202012 contra contracts/schemas/, e round-trip determinístico bit-a-bit.
"""

from __future__ import annotations

import inspect
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator, ValidationError as JsonSchemaValidationError
from referencing import Registry, Resource

from control_lab.core import (
    Controller,
    Dataset,
    DynamicController,
    Experiment,
    FuzzySystem,
    IdentifiedModel,
    PDCController,
    StateFeedbackController,
    StateSpace,
    TSClosedLoop,
    TSStateSpace,
    TransferFunction,
    array_to_tensor,
    complex_to_pair,
    ensure_finite_float64,
    get_closed_loop_matrix,
    interconnect,
    load_model,
    make_closed_loop,
    pair_to_complex,
    restore_model,
    serialize_model,
    tensor_to_array,
    validate_interconnection,
)
from control_lab.diagnostics import (
    ERROR_CATEGORIES,
    CancelledError,
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    ImportUntrustedCodeError,
    InternalError,
    NumericalInconclusiveError,
    Provenance,
    ResourceLimitError,
    Result,
    SchemaUnsupportedError,
    SolverUnavailableError,
    TypedError,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    WorkerRestartedError,
    build_provenance,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
EXAMPLES_DIR = ROOT / "contracts" / "examples"


@pytest.fixture(scope="module")
def schema_registry() -> tuple[Registry, dict[str, dict[str, Any]]]:
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        res = Resource.from_contents(schema)
        resources.append((schema.get("$id", path.name), res))
        resources.append((path.name, res))
    return Registry().with_resources(resources), schemas


def _assert_schema_valid(
    instance: dict[str, Any],
    schema_name: str,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    registry, schemas = schema_registry
    validator = Draft202012Validator(schemas[schema_name], registry=registry)
    validator.validate(instance)


# ---------------------------------------------------------------------------
# 1. Diagnostics: ERROR_CATEGORIES, exceções tipadas, Provenance e Result
# ---------------------------------------------------------------------------


def test_error_categories_and_exception_hierarchy() -> None:
    expected_12 = (
        "VALIDATION_ERROR",
        "DIMENSION_MISMATCH",
        "UNSUPPORTED_MODEL",
        "HYPOTHESIS_VIOLATED",
        "NUMERICAL_INCONCLUSIVE",
        "SOLVER_UNAVAILABLE",
        "RESOURCE_LIMIT",
        "CANCELLED",
        "WORKER_RESTARTED",
        "SCHEMA_UNSUPPORTED",
        "IMPORT_UNTRUSTED_CODE",
        "INTERNAL_ERROR",
    )
    assert ERROR_CATEGORIES == expected_12
    assert len(ERROR_CATEGORIES) == 12

    mapping = [
        (ValidationError, "VALIDATION_ERROR"),
        (DimensionMismatchError, "DIMENSION_MISMATCH"),
        (UnsupportedModelError, "UNSUPPORTED_MODEL"),
        (HypothesisViolatedError, "HYPOTHESIS_VIOLATED"),
        (NumericalInconclusiveError, "NUMERICAL_INCONCLUSIVE"),
        (SolverUnavailableError, "SOLVER_UNAVAILABLE"),
        (ResourceLimitError, "RESOURCE_LIMIT"),
        (CancelledError, "CANCELLED"),
        (WorkerRestartedError, "WORKER_RESTARTED"),
        (SchemaUnsupportedError, "SCHEMA_UNSUPPORTED"),
        (ImportUntrustedCodeError, "IMPORT_UNTRUSTED_CODE"),
        (InternalError, "INTERNAL_ERROR"),
    ]
    for exc_cls, expected_code in mapping:
        err = exc_cls(
            f"Falha {expected_code}",
            parameters={"param": 1},
            next_step="Corrigir entrada.",
            details={"info": "teste"},
        )
        assert isinstance(err, ControlLabError)
        assert err.code == expected_code
        te = err.to_typed_error()
        assert isinstance(te, TypedError)
        assert te.code == expected_code
        rebuilt = te.to_exception()
        assert isinstance(rebuilt, exc_cls)
        assert rebuilt.code == expected_code

    # Base ControlLabError(code, message, ...)
    base_err = ControlLabError("VALIDATION_ERROR", "Entrada inválida", parameters={"x": 2}, next_step="Fix")
    assert base_err.code == "VALIDATION_ERROR"
    assert base_err.to_typed_error().to_dict() == {
        "code": "VALIDATION_ERROR",
        "message": "Entrada inválida",
        "parameters": {"x": 2},
        "next_step": "Fix",
    }

    with pytest.raises(ValueError):
        ControlLabError("UNKNOWN_CATEGORY", "msg")


def test_provenance_and_result_envelope_schema_and_invariants(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    prov = build_provenance(
        "scipy.linalg.solve_continuous_are",
        seed=42,
        tolerances={"rCARE_max": 1e-12},
        model_revision=3,
    )
    assert isinstance(prov, Provenance)
    assert prov.algorithm == "scipy.linalg.solve_continuous_are"
    assert {"numpy", "scipy", "python"}.issubset(prov.lib_versions.keys())
    assert prov.seed == 42
    assert prov.model_revision == 3
    assert prov["algorithm"] == "scipy.linalg.solve_continuous_are"

    res_ok = Result(
        status="warning",
        data={"gain": [1.0, 2.0]},
        assumptions={"stabilizable": True},
        diagnostics={"residual_rel": 1.5e-14},
        provenance=prov,
        warnings=["Aviso simples", WarningItem(code="COND", message="Condicionamento elevado", details={"cond": 1e6})],
        error=None,
    )
    _assert_schema_valid(res_ok.to_dict(), "result.schema.json", schema_registry)

    # Imutabilidade (frozen dataclass)
    with pytest.raises(Exception):
        res_ok.status = "success"  # type: ignore[misc]

    # Round-trip JSON de Result
    raw_json = res_ok.to_json()
    res_restored = Result.from_json(raw_json)
    assert res_restored.to_dict() == res_ok.to_dict()

    # Invariante: status='failure' exige error=TypedError
    with pytest.raises(ValidationError):
        Result(status="failure", provenance=prov, error=None)

    # Invariante: status='success' não pode ter error
    with pytest.raises(ValidationError):
        Result(
            status="success",
            provenance=prov,
            error=TypedError(code="INTERNAL_ERROR", message="contraditório"),
        )

    # Todas as 12 categorias em Result(status='failure') validam contra result.schema.json
    for cat in ERROR_CATEGORIES:
        res_fail = Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={},
            provenance=prov,
            warnings=[],
            error=TypedError(code=cat, message=f"Falha simulada {cat}"),
        )
        _assert_schema_valid(res_fail.to_dict(), "result.schema.json", schema_registry)
        assert Result.from_json(res_fail.to_json()).to_dict() == res_fail.to_dict()

    # Rejeição estrita de NaN e Inf em Result e JSON
    for bad_val in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            Result(status="success", data={"x": bad_val}, provenance=prov)
        with pytest.raises(ValidationError):
            Result(status="success", diagnostics={"r": bad_val}, provenance=prov)

    with pytest.raises(ValidationError):
        Result.from_json(
            '{"status":"success","data":{"x":NaN},"assumptions":{},"diagnostics":{},"provenance":{"algorithm":"a","lib_versions":{}},"warnings":[],"error":null}'
        )


# ---------------------------------------------------------------------------
# 2. Helpers de Tensor: round-trip bit-a-bit, order C/F, rejeição NaN/Inf
# ---------------------------------------------------------------------------


def test_tensor_helpers_bit_exact_and_schema(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    arr = np.array([[math.pi, -1e-15], [1.2345678901234567e100, -0.0]], dtype=np.float64)
    t_c = array_to_tensor(arr, dtype="float64", order="C")
    _assert_schema_valid(t_c, "tensor.schema.json", schema_registry)
    restored_c = tensor_to_array(json.loads(json.dumps(t_c, allow_nan=False)))
    assert restored_c.dtype == np.float64
    assert restored_c.shape == arr.shape
    assert np.array_equal(restored_c.view(np.uint64), arr.view(np.uint64))

    # Ordem Fortran preservada
    arr_f = np.asfortranarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    t_f = array_to_tensor(arr_f)
    assert t_f["order"] == "F"
    assert t_f["data"] == [1.0, 4.0, 2.0, 5.0, 3.0, 6.0]
    _assert_schema_valid(t_f, "tensor.schema.json", schema_registry)
    restored_f = tensor_to_array(t_f)
    assert restored_f.flags.f_contiguous
    np.testing.assert_array_equal(restored_f, arr_f)

    # ComplexVectorPair e ComplexTensor
    poles = np.array([-1.0 + 2.5j, -1.0 - 2.5j], dtype=np.complex128)
    pair = complex_to_pair(poles)
    _assert_schema_valid(pair, "tensor.schema.json", schema_registry)
    np.testing.assert_array_equal(pair_to_complex(pair), poles)

    ctensor = array_to_tensor(np.array([[1 + 2j, 3 - 4j]], dtype=np.complex128))
    _assert_schema_valid(ctensor, "tensor.schema.json", schema_registry)
    np.testing.assert_array_equal(tensor_to_array(ctensor), np.array([[1 + 2j, 3 - 4j]]))

    # Rejeições
    for bad in ([1.0, float("nan")], [1.0, float("inf")], [True, False]):
        with pytest.raises(ValidationError):
            ensure_finite_float64(bad)
    with pytest.raises(DimensionMismatchError):
        tensor_to_array({"shape": [2, 2], "dtype": "float64", "order": "C", "data": [1.0, 2.0, 3.0]})


# ---------------------------------------------------------------------------
# 3. T-CORE-01: Dimensões inválidas, NaN/Inf, dt, imutabilidade e schema
# ---------------------------------------------------------------------------


def test_t_core_01_dimensions_and_statespace_invariants(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # T-CORE-01: A 3x3, B 2x1 -> erro tipado sem objeto parcial
    A_3x3 = np.eye(3)
    B_2x1 = np.ones((2, 1))
    C_1x3 = np.ones((1, 3))
    D_1x1 = np.zeros((1, 1))
    with pytest.raises(DimensionMismatchError) as exc_info:
        StateSpace(A_3x3, B_2x1, C_1x3, D_1x1)
    assert exc_info.value.code == "DIMENSION_MISMATCH"

    # A não quadrada
    with pytest.raises(DimensionMismatchError):
        StateSpace(np.zeros((2, 3)), np.zeros((2, 1)), np.zeros((1, 3)), np.zeros((1, 1)))

    # C incompatível e D incompatível
    with pytest.raises(DimensionMismatchError):
        StateSpace(np.eye(2), np.ones((2, 1)), np.ones((1, 3)), np.zeros((1, 1)))
    with pytest.raises(DimensionMismatchError):
        StateSpace(np.eye(2), np.ones((2, 1)), np.ones((1, 2)), np.zeros((2, 1)))

    # NaN / Inf rejeitados
    with pytest.raises(ValidationError):
        StateSpace([[0.0, 1.0], [float("nan"), -1.0]], [[0.0], [1.0]], [[1.0, 0.0]], [[0.0]])
    with pytest.raises(ValidationError):
        StateSpace([[0.0, 1.0], [-2.0, -3.0]], [[0.0], [float("inf")]], [[1.0, 0.0]], [[0.0]])

    # dt inválido (<= 0 ou NaN)
    with pytest.raises(ValidationError):
        StateSpace(np.eye(2), np.ones((2, 1)), np.ones((1, 2)), dt=0.0)
    with pytest.raises(ValidationError):
        StateSpace(np.eye(2), np.ones((2, 1)), np.ones((1, 2)), dt=-0.01)

    # Exemplo normativo statespace_example.json: round-trip bit-a-bit e schema
    ex_dict = json.loads((EXAMPLES_DIR / "statespace_example.json").read_text(encoding="utf-8"))
    ss = StateSpace.from_dict(ex_dict)
    assert ss.to_dict() == ex_dict
    _assert_schema_valid(ss.to_dict(), "state_space.schema.json", schema_registry)

    # Imutabilidade por revisão
    with pytest.raises(AttributeError):
        ss.revision = 99  # type: ignore[misc]
    with pytest.raises(ValueError):
        ss.A[0, 0] = 99.0

    ss_v4 = ss.with_revision(A=[[0.0, 1.0], [-5.0, -4.0]])
    assert ss_v4.revision == 4
    assert ss.revision == 3
    assert ss.A[1, 0] == -2.0
    assert ss_v4.A[1, 0] == -5.0
    _assert_schema_valid(ss_v4.with_content_hash().to_dict(), "state_space.schema.json", schema_registry)


# ---------------------------------------------------------------------------
# 4. T-CORE-02: Realimentação estática (negative/positive + prefiltro N, m != p)
# ---------------------------------------------------------------------------


def test_t_core_02_state_feedback_signs_and_nonsquare_prefilter(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # Planta MIMO com m=2 entradas, p=1 saída, n=2 estados -> N tem shape (2, 1) (não quadrado!)
    A = np.array([[0.0, 1.0], [-2.0, -3.0]])
    B = np.array([[1.0, 0.0], [0.0, 2.0]])
    C = np.array([[1.0, 0.5]])
    D = np.array([[0.2, -0.1]])
    plant = StateSpace(A, B, C, D, dt=None, id="plant-mimo-2x1", revision=1)

    K = np.array([[0.5, 1.0], [-0.25, 0.75]])  # shape (2, 2)
    N = np.array([[2.0], [-1.0]])  # shape (m=2, p=1)

    # Caso 1: feedback_sign="negative"
    ctrl_neg = StateFeedbackController(
        K=K,
        feedback_sign="negative",
        state_coordinates=["x1", "x2"],
        reference_map={"kind": "output_prefilter", "matrix": N, "reference_names": ["r_y"]},
        dt=None,
        id="ctrl-neg",
        revision=1,
    )
    _assert_schema_valid(ctrl_neg.to_dict(), "controller.schema.json", schema_registry)
    assert StateFeedbackController.from_dict(ctrl_neg.to_dict()).to_dict() == ctrl_neg.to_dict()

    Acl_neg_mat = get_closed_loop_matrix(plant, ctrl_neg)
    np.testing.assert_allclose(Acl_neg_mat, A - B @ K, atol=1e-15)
    np.testing.assert_allclose(get_closed_loop_matrix(A, B, K, "negative"), A - B @ K, atol=1e-15)

    cl_neg = interconnect(plant, ctrl_neg, sign_convention="negative")
    assert isinstance(cl_neg, StateSpace)
    np.testing.assert_allclose(cl_neg.A, A - B @ K, atol=1e-15)
    np.testing.assert_allclose(cl_neg.B, B @ N, atol=1e-15)
    np.testing.assert_allclose(cl_neg.C, C - D @ K, atol=1e-15)
    np.testing.assert_allclose(cl_neg.D, D @ N, atol=1e-15)
    assert cl_neg.B.shape == (2, 1)
    assert cl_neg.input_names == ("r_y",)

    # Caso 2: feedback_sign="positive"
    ctrl_pos = StateFeedbackController(
        K=K,
        feedback_sign="positive",
        state_coordinates=["x1", "x2"],
        reference_map=N,
        dt=None,
        id="ctrl-pos",
        revision=1,
    )
    _assert_schema_valid(ctrl_pos.to_dict(), "controller.schema.json", schema_registry)

    cl_pos = make_closed_loop(plant, ctrl_pos)
    assert isinstance(cl_pos, StateSpace)
    np.testing.assert_allclose(cl_pos.A, A + B @ K, atol=1e-15)
    np.testing.assert_allclose(cl_pos.B, B @ N, atol=1e-15)
    np.testing.assert_allclose(cl_pos.C, C + D @ K, atol=1e-15)
    np.testing.assert_allclose(cl_pos.D, D @ N, atol=1e-15)
    np.testing.assert_allclose(get_closed_loop_matrix(A, B, K, "positive"), A + B @ K, atol=1e-15)

    # Conflito de sinal explícito deve falhar
    with pytest.raises(ValidationError):
        interconnect(plant, ctrl_neg, sign_convention="positive")

    # Falha sem feedback_sign explícito
    with pytest.raises(ValidationError):
        get_closed_loop_matrix(A, B, K)

    # N com linhas incompatíveis com m
    with pytest.raises(DimensionMismatchError):
        StateFeedbackController(K=K, feedback_sign="negative", reference_map=np.ones((3, 1)))


# ---------------------------------------------------------------------------
# 5. T-CORE-03: DynamicController com Dp != 0, Dc != 0, singularidade e rejeição
# ---------------------------------------------------------------------------


def test_t_core_03_dynamic_controller_non_zero_feedthrough_and_well_posedness(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # Planta escalar com Dp = 0.5 != 0
    plant = StateSpace(
        A=[[-2.0]],
        B=[[1.0]],
        C=[[3.0]],
        D=[[0.5]],
        dt=None,
        id="plant-dp",
        revision=1,
    )

    # Controlador dinâmico com Dc = 0.5 != 0 (output_feedback, negative)
    dyn_out = DynamicController(
        Ac=[[-1.0]],
        Bc=[[1.0]],
        Cc=[[2.0]],
        Dc=[[0.5]],
        feedback_sign="negative",
        ports={
            "inputs": [{"name": "y", "role": "y", "size": 1}],
            "outputs": [{"name": "u", "role": "u", "size": 1}],
        },
        interconnection_scheme="output_feedback",
        initial_state=[0.0],
        dt=None,
        id="dyn-out",
        revision=1,
    )
    _assert_schema_valid(dyn_out.to_dict(), "controller.schema.json", schema_registry)
    assert DynamicController.from_dict(dyn_out.to_dict()).to_dict() == dyn_out.to_dict()

    # Rejeição obrigatória em get_closed_loop_matrix (Seção 4.2)
    with pytest.raises(UnsupportedModelError):
        get_closed_loop_matrix(plant, dyn_out)
    with pytest.raises(TypeError):
        get_closed_loop_matrix(plant, dyn_out)

    # Solução analítica fechada:
    # M = 1 + 0.5*0.5 = 1.25 => M^{-1} = 0.8
    # Acl = [[-3.2, -1.6], [2.4, -1.8]], Bcl = [[0.8], [0.4]], Ccl = [[2.4, -0.8]], Dcl = [[0.4]]
    cl_out = interconnect(plant, dyn_out)
    assert isinstance(cl_out, StateSpace)
    np.testing.assert_allclose(cl_out.A, np.array([[-3.2, -1.6], [2.4, -1.8]]), atol=1e-14)
    np.testing.assert_allclose(cl_out.B, np.array([[0.8], [0.4]]), atol=1e-14)
    np.testing.assert_allclose(cl_out.C, np.array([[2.4, -0.8]]), atol=1e-14)
    np.testing.assert_allclose(cl_out.D, np.array([[0.4]]), atol=1e-14)

    # Caso error_feedback MIMO 2x2 com Dp != 0, Dc != 0 comparado contra blocos analíticos explícitos
    Ap = np.array([[-1.0, 0.2], [0.0, -3.0]])
    Bp = np.array([[1.0, 0.5], [0.0, 1.0]])
    Cp = np.array([[1.0, 0.0], [0.5, 2.0]])
    Dp = np.array([[0.2, 0.1], [-0.1, 0.3]])
    plant_mimo = StateSpace(Ap, Bp, Cp, Dp)

    Ac = np.array([[-2.0, 0.1], [0.3, -4.0]])
    Bc = np.array([[1.0, -0.2], [0.4, 1.0]])
    Cc = np.array([[0.5, 0.1], [-0.3, 0.8]])
    Dc = np.array([[0.4, -0.2], [0.1, 0.5]])
    dyn_err = DynamicController(
        Ac,
        Bc,
        Cc,
        Dc,
        feedback_sign="negative",
        ports={
            "inputs": [{"name": "e", "role": "error", "size": 2}],
            "outputs": [{"name": "u", "role": "u", "size": 2}],
        },
        interconnection_scheme="error_feedback",
    )
    cl_err = interconnect(plant_mimo, dyn_err)
    assert isinstance(cl_err, StateSpace)

    # Solução analítica via bloco aumentado com resolução direta da equação algébrica
    # (I + Dc Dp) u = Cc xc + Dc r - Dc Cp xp
    M_ref = np.eye(2) + Dc @ Dp
    uxp_ref = np.linalg.solve(M_ref, -Dc @ Cp)
    uxc_ref = np.linalg.solve(M_ref, Cc)
    ur_ref = np.linalg.solve(M_ref, Dc)
    Acl_ref = np.block(
        [
            [Ap + Bp @ uxp_ref, Bp @ uxc_ref],
            [-Bc @ (Cp + Dp @ uxp_ref), Ac - Bc @ (Dp @ uxc_ref)],
        ]
    )
    Bcl_ref = np.vstack([Bp @ ur_ref, Bc @ (np.eye(2) - Dp @ ur_ref)])
    Ccl_ref = np.hstack([Cp + Dp @ uxp_ref, Dp @ uxc_ref])
    Dcl_ref = Dp @ ur_ref

    np.testing.assert_allclose(cl_err.A, Acl_ref, atol=1e-13)
    np.testing.assert_allclose(cl_err.B, Bcl_ref, atol=1e-13)
    np.testing.assert_allclose(cl_err.C, Ccl_ref, atol=1e-13)
    np.testing.assert_allclose(cl_err.D, Dcl_ref, atol=1e-13)

    # Caso singular: I - (+1) * Dc * Dp = 0 (Dc = 0.5, Dp = 2.0, positive feedback)
    plant_sing = StateSpace([[-1.0]], [[1.0]], [[1.0]], [[2.0]])
    dyn_sing = DynamicController([[-1.0]], [[1.0]], [[1.0]], [[0.5]], feedback_sign="positive")
    with pytest.raises(HypothesisViolatedError):
        interconnect(plant_sing, dyn_sing)
    res_sing = validate_interconnection(plant_sing, dyn_sing, raise_on_error=False)
    assert res_sing.status == "failure"
    assert res_sing.error is not None
    assert res_sing.error.code == "HYPOTHESIS_VIOLATED"

    # Portas incompatíveis com dimensões internas do controlador -> DimensionMismatchError
    with pytest.raises(DimensionMismatchError):
        DynamicController(
            Ac=[[-1.0]],
            Bc=[[1.0, 0.0]],
            Cc=[[1.0]],
            Dc=[[0.0, 0.0]],
            feedback_sign="negative",
            ports={
                "inputs": [{"name": "y", "role": "y", "size": 1}],
                "outputs": [{"name": "u", "role": "u", "size": 1}],
            },
        )

    # Confirmar ausência de np.linalg.inv no módulo interconnect.py
    import control_lab.core.interconnect as ic_mod

    src = inspect.getsource(ic_mod)
    assert "linalg.inv" not in src


# ---------------------------------------------------------------------------
# 6. T-TS-01: TSStateSpace (3 tipos), PDCController e bloqueio de polytopic_uncertain
# ---------------------------------------------------------------------------


def _make_ts_vertices() -> list[dict[str, Any]]:
    return [
        {
            "vertex_id": "v1",
            "A": [[0.0, 1.0], [-1.0, -2.0]],
            "B": [[0.0], [1.0]],
            "C": [[1.0, 0.0]],
            "D": [[0.0]],
        },
        {
            "vertex_id": "v2",
            "A": [[0.0, 1.0], [-3.0, -4.0]],
            "B": [[0.0], [2.0]],
            "C": [[1.0, 0.0]],
            "D": [[0.0]],
        },
    ]


def test_t_ts_01_pdc_blocked_on_polytopic_uncertain_and_accepted_on_ts_measured(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    verts = _make_ts_vertices()

    ts_measured = TSStateSpace(
        verts,
        kind="ts_measured",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["x1"], "sum_to_one_domain": True},
        premise_availability={
            "mode": "all_measured",
            "measured_premises": ["x1"],
            "unmeasured_premises": [],
            "estimator_required_for_pdc": False,
        },
        domain={"bounds": {"x1": [-1.0, 1.0]}},
        id="ts-meas-1",
        revision=1,
    )
    ts_poly = TSStateSpace(
        verts,
        kind="polytopic_uncertain",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["alpha1"], "sum_to_one_domain": True},
        premise_availability={
            "mode": "unknown_uncertain",
            "measured_premises": [],
            "unmeasured_premises": ["alpha1"],
            "estimator_required_for_pdc": True,
        },
        domain={"bounds": {"alpha1": [0.0, 1.0]}},
        id="ts-poly-1",
        revision=1,
    )
    ts_partial = TSStateSpace(
        verts,
        kind="ts_partially_observed",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["x1", "x2"], "sum_to_one_domain": True},
        premise_availability={
            "mode": "partially_observed",
            "measured_premises": ["x1"],
            "unmeasured_premises": ["x2"],
            "estimator_required_for_pdc": True,
        },
        domain={"bounds": {"x1": [-1.0, 1.0], "x2": [-2.0, 2.0]}},
        id="ts-part-1",
        revision=1,
    )

    for ts_obj in (ts_measured, ts_poly, ts_partial):
        _assert_schema_valid(ts_obj.to_dict(), "ts_state_space.schema.json", schema_registry)
        assert TSStateSpace.from_dict(ts_obj.to_dict()).to_dict() == ts_obj.to_dict()

    # Incoerência semântica em TSStateSpace deve ser rejeitada
    with pytest.raises(HypothesisViolatedError):
        TSStateSpace(
            verts,
            kind="ts_measured",
            membership_spec={"version": "1.0.0", "premise_variables": ["x1"], "sum_to_one_domain": True},
            premise_availability={
                "mode": "unknown_uncertain",
                "measured_premises": [],
                "unmeasured_premises": ["x1"],
            },
            domain={"bounds": {"x1": [-1.0, 1.0]}},
        )

    # T-TS-01 (a): PDCController não pode incluir polytopic_uncertain em allowed_ts_kinds
    with pytest.raises(HypothesisViolatedError):
        PDCController(
            K_i=[[[2.0, 3.0]], [[4.0, 5.0]]],
            feedback_sign="negative",
            membership_ref={"model_id": "ts-poly-1", "model_revision": 1, "membership_version": "1.0.0"},
            measurement_requirements={
                "required_premise_variables": ["alpha1"],
                "requires_full_state": True,
                "allowed_ts_kinds": ["polytopic_uncertain"],
            },
        )

    # T-TS-01 (b): PDCController associado/validado contra polytopic_uncertain deve ser rejeitado
    pdc_for_poly = PDCController(
        K_i=[[[2.0, 3.0]], [[4.0, 5.0]]],
        feedback_sign="negative",
        membership_ref={"model_id": "ts-poly-1", "model_revision": 1, "membership_version": "1.0.0"},
        measurement_requirements={
            "required_premise_variables": ["alpha1"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_measured"],
        },
    )
    with pytest.raises(HypothesisViolatedError):
        validate_interconnection(ts_poly, pdc_for_poly)
    with pytest.raises(HypothesisViolatedError):
        interconnect(ts_poly, pdc_for_poly)

    # ts_partially_observed sem estimador também deve falhar
    pdc_partial = PDCController(
        K_i=[[[2.0, 3.0]], [[4.0, 5.0]]],
        feedback_sign="negative",
        membership_ref={"model_id": "ts-part-1", "model_revision": 1, "membership_version": "1.0.0"},
        measurement_requirements={
            "required_premise_variables": ["x1", "x2"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_partially_observed"],
        },
    )
    with pytest.raises(HypothesisViolatedError):
        interconnect(ts_partial, pdc_partial)

    # T-TS-01 (c): ts_measured com PDCController é aceito e preserva todos os termos duplos (i, j)
    K1 = np.array([[2.0, 3.0]])
    K2 = np.array([[4.0, 5.0]])
    pdc_meas = PDCController(
        K_i=[K1, K2],
        feedback_sign="negative",
        membership_ref={"model_id": "ts-meas-1", "model_revision": 1, "membership_version": "1.0.0"},
        measurement_requirements={
            "required_premise_variables": ["x1"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_measured"],
        },
        id="ctrl-pdc-meas",
        revision=1,
    )
    _assert_schema_valid(pdc_meas.to_dict(), "controller.schema.json", schema_registry)
    assert PDCController.from_dict(pdc_meas.to_dict()).to_dict() == pdc_meas.to_dict()

    res_val = validate_interconnection(ts_measured, pdc_meas)
    assert res_val.status == "success"
    cl_ts = interconnect(ts_measured, pdc_meas)
    assert isinstance(cl_ts, TSClosedLoop)

    # Verifica termo cruzado (0, 1): A_0 - B_0 K_1
    A0 = np.array(verts[0]["A"])
    B0 = np.array(verts[0]["B"])
    np.testing.assert_allclose(cl_ts.get_cross_matrix(0, 1), A0 - B0 @ K2, atol=1e-15)

    # Verifica soma dupla exata em h = [0.25, 0.75] (diferente de média congelada A_bar - B_bar K_bar!)
    h = [0.25, 0.75]
    inst = cl_ts.evaluate_at_weights(h)
    A1 = np.array(verts[1]["A"])
    B1 = np.array(verts[1]["B"])
    expected_double_sum = (
        0.25 * 0.25 * (A0 - B0 @ K1)
        + 0.25 * 0.75 * (A0 - B0 @ K2)
        + 0.75 * 0.25 * (A1 - B1 @ K1)
        + 0.75 * 0.75 * (A1 - B1 @ K2)
    )
    np.testing.assert_allclose(inst.A, expected_double_sum, atol=1e-15)


# ---------------------------------------------------------------------------
# 7. Incompatibilidade de domínio temporal dt (contínuo vs discreto)
# ---------------------------------------------------------------------------


def test_incompatible_dt_rejected() -> None:
    plant_cont = StateSpace(np.eye(2), np.ones((2, 1)), np.ones((1, 2)), dt=None)
    plant_disc_01 = StateSpace(np.eye(2), np.ones((2, 1)), np.ones((1, 2)), dt=0.01)
    ctrl_disc_01 = StateFeedbackController([[1.0, 2.0]], feedback_sign="negative", dt=0.01)
    ctrl_disc_02 = StateFeedbackController([[1.0, 2.0]], feedback_sign="negative", dt=0.02)
    ctrl_cont = StateFeedbackController([[1.0, 2.0]], feedback_sign="negative", dt=None)

    with pytest.raises(DimensionMismatchError):
        interconnect(plant_cont, ctrl_disc_01)
    with pytest.raises(DimensionMismatchError):
        interconnect(plant_disc_01, ctrl_cont)
    with pytest.raises(DimensionMismatchError):
        interconnect(plant_disc_01, ctrl_disc_02)
    with pytest.raises(DimensionMismatchError):
        get_closed_loop_matrix(plant_cont, ctrl_disc_01)


# ---------------------------------------------------------------------------
# 8. TransferFunction, Dataset, IdentifiedModel, FuzzySystem, Experiment, Serialization
# ---------------------------------------------------------------------------


def test_transfer_function_siso_mimo_conditioning_and_roundtrip() -> None:
    tf_siso = TransferFunction([1.0], [1.0, 3.0, 2.0], dt=None)
    assert tf_siso.is_siso
    assert tf_siso.variable == "s"
    assert len(tf_siso.warnings) == 0
    ss_conv = tf_siso.to_state_space()
    assert ss_conv.n_states == 2
    np.testing.assert_allclose(np.sort(np.real(ss_conv.poles())), np.array([-2.0, -1.0]), atol=1e-12)

    # Discreta em z^-1 ascendente
    tf_zinv = TransferFunction([0.5, 0.25], [1.0, -0.8], dt=0.1, variable="z^-1", poly_order="ascending")
    assert TransferFunction.from_dict(tf_zinv.to_dict()).to_dict() == tf_zinv.to_dict()
    ss_z = tf_zinv.to_state_space()
    assert ss_z.dt == 0.1

    # MIMO 2x2
    tf_mimo = TransferFunction(
        num=[[[1.0], [0.5]], [[0.0], [2.0]]],
        den=[[[1.0, 1.0], [1.0, 2.0]], [[1.0], [1.0, 3.0]]],
        dt=None,
    )
    assert (tf_mimo.n_outputs, tf_mimo.n_inputs) == (2, 2)
    assert TransferFunction.from_json(tf_mimo.to_json()).to_dict() == tf_mimo.to_dict()

    # Ordem alta -> aviso explícito de condicionamento
    high_order_den = np.poly(np.arange(1, 15, dtype=np.float64)).tolist()
    tf_ill = TransferFunction([1.0], high_order_den)
    assert len(tf_ill.warnings) >= 1
    assert tf_ill.assess_conditioning()["is_ill_conditioned"] is True

    # Validação de inconsistência dt vs variable
    with pytest.raises(ValidationError):
        TransferFunction([1.0], [1.0, 1.0], dt=None, variable="z")
    with pytest.raises(ValidationError):
        TransferFunction([1.0], [1.0, 1.0], dt=0.1, variable="s")


def test_dataset_identified_model_fuzzy_experiment_and_serialization(tmp_path: Path) -> None:
    t = np.linspace(0.0, 1.0, 11)
    u = np.sin(t)
    y = 2.0 * u
    ds = Dataset(t=t, u=u, y=y, dt=0.1, require_uniform=True, id="ds-01", revision=1)
    assert ds.is_uniform_sampling is True
    assert ds.n_inputs == 1 and ds.n_outputs == 1
    assert Dataset.from_json(ds.to_json()).to_dict() == ds.to_dict()

    ds_tr, ds_va = ds.train_val_split(train_fraction=0.7)
    assert ds_tr.n_samples + ds_va.n_samples == ds.n_samples
    assert float(ds_tr.t[-1]) < float(ds_va.t[0])

    # Amostragem irregular detectada
    t_irreg = np.array([0.0, 0.1, 0.25, 0.3, 0.5])
    ds_irreg = Dataset(t=t_irreg, u=np.ones(5), y=np.ones(5))
    assert ds_irreg.is_uniform_sampling is False
    assert len(ds_irreg.warnings) == 1
    with pytest.raises(ValidationError):
        Dataset(t=t_irreg, u=np.ones(5), y=np.ones(5), require_uniform=True)

    # IdentifiedModel
    ss_id = StateSpace([[-1.0]], [[1.0]], [[1.0]], [[0.0]], dt=0.1, id="m-id", revision=1)
    tf_siso = TransferFunction([1.0], [1.0, 2.0], dt=None)
    id_mod = IdentifiedModel(
        model=ss_id,
        algorithm="arx_qr",
        dataset_ref={"id": ds.id, "revision": ds.revision},
        partitions={"train_indices": [0, 1, 2], "validation_indices": [3, 4]},
        metrics={"fit_percent": 99.5, "rmse": 1e-3},
        noise_hypothesis={"type": "white_equation_error"},
        excitation_diagnostics={"pe_sufficient": True, "cond": 3.2},
    )
    assert IdentifiedModel.from_json(id_mod.to_json()).to_dict() == id_mod.to_dict()

    # Sobreposição treino/validação rejeitada
    with pytest.raises(HypothesisViolatedError):
        IdentifiedModel(
            model=ss_id,
            algorithm="arx_qr",
            partitions={"train_indices": [0, 1, 2], "validation_indices": [2, 3]},
        )

    # FuzzySystem (is_dynamic_model=False por padrão)
    fuzzy = FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "e",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "neg", "type": "trimf", "params": [-1.0, -1.0, 1.0]},
                    {"name": "pos", "type": "trimf", "params": [-1.0, 1.0, 1.0]},
                ],
            }
        ],
        output_variables=[
            {
                "name": "u",
                "universe": [-10.0, 10.0],
                "terms": [
                    {"name": "low", "type": "constant", "params": [-5.0]},
                    {"name": "high", "type": "constant", "params": [5.0]},
                ],
            }
        ],
        rules=[
            {"antecedents": {"e": "neg"}, "consequents": {"u": "low"}, "weight": 1.0},
            {"antecedents": {"e": "pos"}, "consequents": {"u": "high"}, "weight": 1.0},
        ],
    )
    assert fuzzy.is_dynamic_model is False
    assert FuzzySystem.from_json(fuzzy.to_json()).to_dict() == fuzzy.to_dict()

    with pytest.raises(HypothesisViolatedError):
        FuzzySystem(
            inference_type="ts",
            input_variables=fuzzy.input_variables,
            output_variables=fuzzy.output_variables,
            rules=fuzzy.rules,
            is_dynamic_model=True,
        )

    # Experiment + serialize_model / restore_model / load_model (JSON string e Path)
    exp = Experiment(
        method="lqr_care",
        model_ref={"id": ss_id.id, "revision": ss_id.revision},
        parameters={"Q": [[1.0]], "R": [[1.0]]},
        tolerances={"rCARE_max": 1e-12},
        results=Result(status="success", data={"K": [[0.414]]}),
    )
    for obj in (ss_id, tf_siso, ds, id_mod, fuzzy, exp):
        payload = serialize_model(obj)
        restored = restore_model(payload)
        assert serialize_model(restored) == payload
        loaded = load_model(json.dumps(payload, allow_nan=False))
        assert serialize_model(loaded) == payload

    model_file = tmp_path / "model.json"
    model_file.write_text(ss_id.to_json(), encoding="utf-8")
    loaded_from_disk = load_model(model_file)
    assert isinstance(loaded_from_disk, StateSpace)
    assert loaded_from_disk.to_dict() == ss_id.to_dict()

    # schema_version não suportada
    bad_payload = serialize_model(ss_id)
    bad_payload["schema_version"] = "2.0.0"
    with pytest.raises(SchemaUnsupportedError):
        restore_model(bad_payload)


def test_two_dof_dynamic_controller_and_golden_care_12x3_interconnect(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # Controlador 2-DOF com portas y e r e feedthrough não nulo
    plant = StateSpace([[-1.0]], [[1.0]], [[2.0]], [[0.5]], dt=None)
    # u = Cc xc + s * Dcy * y + Dcr * r ; xc_dot = Ac xc + s * Bcy * y + Bcr * r
    dyn_2dof = DynamicController(
        Ac=[[-3.0]],
        Bc=[[1.0, 2.0]],
        Cc=[[1.5]],
        Dc=[[0.5, 1.0]],
        feedback_sign="negative",
        ports={
            "inputs": [
                {"name": "y", "role": "y", "size": 1},
                {"name": "r", "role": "r", "size": 1},
            ],
            "outputs": [{"name": "u", "role": "u", "size": 1}],
        },
        interconnection_scheme="two_dof",
    )
    assert isinstance(dyn_2dof, Controller)
    _assert_schema_valid(dyn_2dof.to_dict(), "controller.schema.json", schema_registry)

    cl_2dof = interconnect(plant, dyn_2dof)
    assert isinstance(cl_2dof, StateSpace)
    # s = -1, Dcy = 0.5, Dp = 0.5 => M = 1 - (-1)(0.5)(0.5) = 1.25 -> M^-1 = 0.8
    # G_uxp = 0.8 * (-0.5 * 2.0) = -0.8
    # G_uxc = 0.8 * 1.5 = 1.2
    # G_ur  = 0.8 * 1.0 = 0.8
    np.testing.assert_allclose(cl_2dof.A, np.array([[-1.8, 1.2], [-1.6, -3.6]]), atol=1e-14)
    np.testing.assert_allclose(cl_2dof.B, np.array([[0.8], [1.6]]), atol=1e-14)
    np.testing.assert_allclose(cl_2dof.C, np.array([[1.6, 0.6]]), atol=1e-14)
    np.testing.assert_allclose(cl_2dof.D, np.array([[0.4]]), atol=1e-14)

    # Teste integrado com fixture ouro B-CARE-12x3 e make_closed_loop(return_result=True)
    b12 = json.loads((ROOT / "contracts" / "fixtures" / "B-CARE-12x3.json").read_text(encoding="utf-8"))
    d12 = b12["data"]
    ss12 = StateSpace(
        A=tensor_to_array(d12["A"]),
        B=tensor_to_array(d12["B"]),
        C=tensor_to_array(d12["C"]),
        D=tensor_to_array(d12["D"]),
        dt=d12["dt"],
        id="B-CARE-12x3",
        revision=1,
    )
    K12 = tensor_to_array(d12["expected"]["K"])
    ctrl12 = StateFeedbackController(K=K12, feedback_sign=d12["feedback_sign"], dt=d12["dt"])
    assert isinstance(ctrl12, Controller)
    _assert_schema_valid(ss12.to_dict(), "state_space.schema.json", schema_registry)
    _assert_schema_valid(ctrl12.to_dict(), "controller.schema.json", schema_registry)

    res_cl = make_closed_loop(ss12, ctrl12, return_result=True)
    assert isinstance(res_cl, Result)
    assert res_cl.status == "success"
    _assert_schema_valid(res_cl.to_dict(), "result.schema.json", schema_registry)
    cl12 = StateSpace.from_dict(res_cl.data["closed_loop"])  # type: ignore[index]
    assert np.max(np.real(cl12.poles())) < 0.0

    # Round-trip from_state_space -> TransferFunction
    tf_back = TransferFunction.from_state_space(StateSpace([[-2.0]], [[1.0]], [[3.0]], [[0.0]]))
    np.testing.assert_allclose(tf_back.num[0][0], np.array([3.0]), atol=1e-12)
    np.testing.assert_allclose(tf_back.den[0][0], np.array([1.0, 2.0]), atol=1e-12)


# ---------------------------------------------------------------------------
# 9. Correções de Auditoria F9 (BUG-F1-01, BUG-F1-02, OBS-F1-03, OBS-F1-04)
# ---------------------------------------------------------------------------


def test_bug_f1_01_static_and_zero_tf_to_state_space_and_mimo_freq_parity(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    import warnings

    # Ganho puramente estático [2.5] / [1.0] -> 0 estados, sem polo espúrio em 0 nem BadCoefficients
    tf_static = TransferFunction([2.5], [1.0], dt=None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ss_static = tf_static.to_state_space()
    assert len(caught) == 0
    assert ss_static.n_states == 0
    assert ss_static.A.shape == (0, 0)
    assert ss_static.B.shape == (0, 1)
    assert ss_static.C.shape == (1, 0)
    np.testing.assert_allclose(ss_static.D, np.array([[2.5]]), atol=1e-15)
    assert "conversion_warnings" not in ss_static.provenance
    assert ss_static.poles().size == 0
    _assert_schema_valid(ss_static.to_dict(), "state_space.schema.json", schema_registry)
    assert StateSpace.from_dict(ss_static.to_dict()).to_dict() == ss_static.to_dict()
    tf_static_back = TransferFunction.from_state_space(ss_static)
    np.testing.assert_allclose(tf_static_back.num[0][0], np.array([2.5]), atol=1e-15)

    # Canal estritamente nulo 0 / (s + 2) -> 0 estados, D = 0
    tf_zero = TransferFunction([0.0], [1.0, 2.0], dt=None)
    ss_zero = tf_zero.to_state_space()
    assert ss_zero.n_states == 0
    assert ss_zero.D[0, 0] == 0.0
    assert "conversion_warnings" not in ss_zero.provenance

    # MIMO 2x2 com canal (1,0) nulo -> exatamente 3 estados reais e paridade exata inclusive em DC (w=0)
    tf_mimo = TransferFunction(
        num=[[[1.0], [0.5]], [[0.0], [2.0]]],
        den=[[[1.0, 1.0], [1.0, 2.0]], [[1.0], [1.0, 3.0]]],
        dt=None,
    )
    with warnings.catch_warnings(record=True) as caught_mimo:
        warnings.simplefilter("always")
        ss_mimo = tf_mimo.to_state_space()
    assert len(caught_mimo) == 0
    assert ss_mimo.n_states == 3
    assert "conversion_warnings" not in ss_mimo.provenance

    I3 = np.eye(3, dtype=np.complex128)
    for w in (0.0, 0.5, 1.0, 5.0):
        s_jw = 1j * w
        G_ss = ss_mimo.C @ np.linalg.solve(s_jw * I3 - ss_mimo.A, ss_mimo.B) + ss_mimo.D
        G_tf = np.array(
            [
                [1.0 / (s_jw + 1.0), 0.5 / (s_jw + 2.0)],
                [0.0 + 0.0j, 2.0 / (s_jw + 3.0)],
            ],
            dtype=np.complex128,
        )
        np.testing.assert_allclose(G_ss, G_tf, atol=1e-13)


def test_bug_f1_02_pdc_partially_observed_omitting_unmeasured_premise_blocked() -> None:
    verts = _make_ts_vertices()
    ts_partial = TSStateSpace(
        verts,
        kind="ts_partially_observed",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["x1", "x2"], "sum_to_one_domain": True},
        premise_availability={
            "mode": "partially_observed",
            "measured_premises": ["x1"],
            "unmeasured_premises": ["x2"],
            "estimator_required_for_pdc": True,
        },
        domain={"bounds": {"x1": [-1.0, 1.0], "x2": [-2.0, 2.0]}},
        id="ts-part-bug",
        revision=1,
    )

    # Tentativa de bypass declarando apenas a premissa medida ["x1"] em required_premise_variables
    pdc_bypass = PDCController(
        K_i=[[[2.0, 3.0]], [[4.0, 5.0]]],
        feedback_sign="negative",
        membership_ref={"model_id": "ts-part-bug", "model_revision": 1, "membership_version": "1.0.0"},
        measurement_requirements={
            "required_premise_variables": ["x1"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_partially_observed"],
        },
    )
    with pytest.raises(HypothesisViolatedError):
        validate_interconnection(ts_partial, pdc_bypass)
    with pytest.raises(HypothesisViolatedError):
        interconnect(ts_partial, pdc_bypass)

    # Mesmo declarando ambas ["x1", "x2"], continua bloqueado sem premise_estimator explícito
    pdc_full = PDCController(
        K_i=[[[2.0, 3.0]], [[4.0, 5.0]]],
        feedback_sign="negative",
        membership_ref={"model_id": "ts-part-bug", "model_revision": 1, "membership_version": "1.0.0"},
        measurement_requirements={
            "required_premise_variables": ["x1", "x2"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_partially_observed"],
        },
    )
    with pytest.raises(HypothesisViolatedError):
        interconnect(ts_partial, pdc_full)

    # Com premise_estimator explícito, interconnect aceita e preserva termos duplos
    cl = interconnect(ts_partial, pdc_full, premise_estimator={"kind": "ts_observer"})
    assert isinstance(cl, TSClosedLoop)


def test_obs_f1_03_reject_extra_input_ports_in_error_feedback_and_two_dof() -> None:
    plant = StateSpace([[-1.0]], [[1.0]], [[1.0]], [[0.0]], dt=None)

    dyn_err_extra = DynamicController(
        Ac=[[-2.0]],
        Bc=[[1.0, 0.5]],
        Cc=[[1.0]],
        Dc=[[0.2, 0.1]],
        feedback_sign="negative",
        ports={
            "inputs": [
                {"name": "e", "role": "error", "size": 1},
                {"name": "w", "role": "w", "size": 1},
            ],
            "outputs": [{"name": "u", "role": "u", "size": 1}],
        },
        interconnection_scheme="error_feedback",
    )
    with pytest.raises(ValidationError):
        interconnect(plant, dyn_err_extra)

    dyn_2dof_extra = DynamicController(
        Ac=[[-2.0]],
        Bc=[[1.0, 1.0, 0.5]],
        Cc=[[1.0]],
        Dc=[[0.2, 0.3, 0.1]],
        feedback_sign="negative",
        ports={
            "inputs": [
                {"name": "y", "role": "y", "size": 1},
                {"name": "r", "role": "r", "size": 1},
                {"name": "w", "role": "w", "size": 1},
            ],
            "outputs": [{"name": "u", "role": "u", "size": 1}],
        },
        interconnection_scheme="two_dof",
    )
    with pytest.raises(ValidationError):
        interconnect(plant, dyn_2dof_extra)


def test_obs_f1_04_result_deep_immutability_and_with_revision_unknown_kwargs() -> None:
    prov = build_provenance("test_alg", tolerances={"tol": 1e-9})
    warn = WarningItem("W1", "Msg", details={"nested": [1, 2]})
    err = TypedError(code="VALIDATION_ERROR", message="Err", parameters={"items": [10]})
    res = Result(
        status="warning",
        data={"K": [[1.0, 2.0]], "meta": {"a": 1}},
        assumptions={"stabilizable": True},
        diagnostics={"residual": 1e-14},
        provenance=prov,
        warnings=[warn],
    )
    res_fail = Result(status="failure", provenance=prov, error=err)

    # Tentativas de mutação externa pós-construção não afetam estado interno nem to_dict()
    d = res.data
    assert d is not None
    d["K"].append([99.0, 99.0])
    d["meta"]["a"] = 999
    d["injected"] = True
    res.assumptions["stabilizable"] = False
    res.diagnostics["residual"] = 999.0
    res.provenance.lib_versions["numpy"] = "hacked"
    res.provenance.tolerances["tol"] = 1.0
    warn_read = res.warnings[0]
    assert isinstance(warn_read, WarningItem)
    assert warn_read.details is not None
    warn_read.details["nested"].append(999)
    assert res_fail.error is not None and res_fail.error.parameters is not None
    res_fail.error.parameters["items"].append(999)

    assert res.data == {"K": [[1.0, 2.0]], "meta": {"a": 1}}
    assert res.assumptions == {"stabilizable": True}
    assert res.diagnostics == {"residual": 1e-14}
    assert res.to_dict()["data"] == {"K": [[1.0, 2.0]], "meta": {"a": 1}}
    assert res.provenance.tolerances == {"tol": 1e-9}
    assert res.warnings[0].details == {"nested": [1, 2]}  # type: ignore[union-attr]
    assert res_fail.error.parameters == {"items": [10]}

    # with_revision / evolve devem rejeitar kwargs desconhecidos com ValidationError
    ss = StateSpace([[-1.0]], [[1.0]], [[1.0]], [[0.0]])
    tf = TransferFunction([1.0], [1.0, 1.0])
    ds = Dataset([0.0, 0.1], [1.0, 1.0], [0.0, 0.1])
    idm = IdentifiedModel(ss, algorithm="arx")
    ts = TSStateSpace(
        _make_ts_vertices(),
        kind="ts_measured",
        membership_spec={"version": "1.0.0", "premise_variables": ["x1"], "sum_to_one_domain": True},
        premise_availability={"mode": "all_measured", "measured_premises": ["x1"], "unmeasured_premises": []},
        domain={"bounds": {"x1": [-1.0, 1.0]}},
        id="ts-imm",
        revision=1,
    )
    fuzzy = FuzzySystem(
        inference_type="ts",
        input_variables=[{"name": "e", "universe": [-1.0, 1.0], "terms": [{"name": "n", "type": "trimf", "params": [-1.0, 0.0, 1.0]}]}],
        output_variables=[{"name": "u", "universe": [-1.0, 1.0], "terms": [{"name": "c", "type": "constant", "params": [0.0]}]}],
        rules=[{"antecedents": {"e": "n"}, "consequents": {"u": "c"}, "weight": 1.0}],
    )
    exp = Experiment(method="lqr")
    sf = StateFeedbackController([[1.0]], feedback_sign="negative")
    dyn = DynamicController([[-1.0]], [[1.0]], [[1.0]], [[0.0]], feedback_sign="negative")
    pdc = PDCController(
        [[[1.0, 2.0]], [[3.0, 4.0]]],
        feedback_sign="negative",
        membership_ref={"model_id": "ts-imm", "model_revision": 1, "membership_version": "1.0.0"},
        measurement_requirements={"required_premise_variables": ["x1"], "requires_full_state": True, "allowed_ts_kinds": ["ts_measured"]},
    )

    for obj in (ss, tf, ds, idm, ts, fuzzy, exp, sf, dyn, pdc):
        with pytest.raises(ValidationError):
            obj.with_revision(unknown_kwarg=123)
        with pytest.raises(ValidationError):
            obj.evolve(unknown_kwarg=123)


