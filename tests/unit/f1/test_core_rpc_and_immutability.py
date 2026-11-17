"""Testes unitários e de contrato para WP-AUDIT-FIX-F1-CORE-RPC.

Cobre:
- Blindagem de imutabilidade de arrays (`setflags(write=True)` não altera estado interno)
  e monotonicidade estrita de `with_revision` em todos os modelos e controladores canônicos;
- Tratamento de `UnicodeDecodeError` em `strict_json_loads` -> `ValidationError`;
- Dispatcher real `control_lab.core.rpc.dispatch` validado contra
  `contracts/schemas/rpc_request.schema.json` e `contracts/schemas/rpc_response.schema.json`,
  incluindo regressões `test_arrays_cannot_change_model_revision_content` e
  `test_unstabilizable_plant_through_real_rpc`.
"""

from __future__ import annotations

import json
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core import (
    Dataset,
    DynamicController,
    Experiment,
    FuzzySystem,
    IdentifiedModel,
    PDCController,
    RPC_API_VERSION,
    StateFeedbackController,
    StateSpace,
    TSStateSpace,
    TransferFunction,
    array_to_tensor,
    dispatch,
    interconnect,
    tensor_to_array,
)
from control_lab.diagnostics import Result, ValidationError, strict_json_loads

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
EXAMPLES_DIR = ROOT / "contracts" / "examples"
FIXTURES_DIR = ROOT / "contracts" / "fixtures"


@pytest.fixture(scope="module")
def schema_registry() -> tuple[Registry, dict[str, dict[str, Any]]]:
    schemas: dict[str, dict[str, Any]] = {}
    registry = Registry()
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name] = loaded
        res = Resource.from_contents(loaded)
        registry = registry.with_resource(path.name, res)
        if "$id" in loaded:
            registry = registry.with_resource(loaded["$id"], res)
    return registry, schemas


def _validate_schema(
    obj: dict[str, Any],
    schema_name: str,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    registry, schemas = schema_registry
    validator = Draft202012Validator(schemas[schema_name], registry=registry)
    validator.validate(obj)


def _make_req(
    operation: str,
    payload: dict[str, Any],
    *,
    options: dict[str, Any] | None = None,
    request_id: str = "req-test-001",
    project_id: str = "proj-test-001",
    project_revision: int = 1,
    api_version: str = RPC_API_VERSION,
) -> dict[str, Any]:
    return {
        "api_version": api_version,
        "request_id": request_id,
        "project_id": project_id,
        "project_revision": project_revision,
        "operation": operation,
        "payload": payload,
        "options": options if options is not None else {},
        "timeout_policy": {
            "hard_timeout_ms": 15000,
            "cancel_on_supersede": True,
        },
    }


def _sample_fuzzy() -> FuzzySystem:
    return FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "x1",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "low", "mf": "triangular", "params": [-1.0, -1.0, 1.0]},
                    {"name": "high", "mf": "triangular", "params": [-1.0, 1.0, 1.0]},
                ],
            }
        ],
        output_variables=[
            {
                "name": "y",
                "universe": [-10.0, 10.0],
                "terms": [
                    {"name": "c1", "type": "linear", "params": [1.0, 0.0]},
                    {"name": "c2", "type": "linear", "params": [2.0, 1.0]},
                ],
            }
        ],
        rules=[
            {"name": "r1", "antecedents": {"x1": "low"}, "consequents": {"y": "c1"}, "weight": 1.0},
            {"name": "r2", "antecedents": {"x1": "high"}, "consequents": {"y": "c2"}, "weight": 1.0},
        ],
        id="fz-001",
        revision=1,
    )


def _sample_ts() -> TSStateSpace:
    return TSStateSpace(
        vertices=[
            {
                "vertex_id": "v1",
                "A": [[0.0, 1.0], [-2.0, -1.0]],
                "B": [[0.0], [1.0]],
                "C": [[1.0, 0.0]],
                "D": [[0.0]],
            },
            {
                "vertex_id": "v2",
                "A": [[0.0, 1.0], [-3.0, -1.5]],
                "B": [[0.0], [1.0]],
                "C": [[1.0, 0.0]],
                "D": [[0.0]],
            },
        ],
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
        id="ts-001",
        revision=1,
    )


# ---------------------------------------------------------------------------
# 1. Regressões obrigatórias de imutabilidade e strict_json_loads (AUD-005)
# ---------------------------------------------------------------------------


def test_arrays_cannot_change_model_revision_content() -> None:
    """Garante que nem atribuição direta nem .setflags(write=True) alteram conteúdo interno."""
    ss = StateSpace(
        A=[[0.0, 1.0], [-2.0, -3.0]],
        B=[[0.0], [1.0]],
        C=[[1.0, 0.0]],
        D=[[0.0]],
        id="ss-immut",
        revision=2,
    ).with_content_hash()
    hash_before = ss.compute_content_hash()
    dict_before = ss.to_dict(include_content_hash=True)

    # Leitura é write=False
    assert ss.A.flags.writeable is False
    with pytest.raises(ValueError):
        ss.A[0, 0] = 99.0

    # Bypass via setflags(write=True) só altera a cópia destacada
    for prop_name in ("A", "B", "C", "D"):
        arr = getattr(ss, prop_name)
        arr.setflags(write=True)
        arr[0, 0] = np.nan

    assert ss.compute_content_hash() == hash_before
    assert ss.to_dict(include_content_hash=True) == dict_before
    assert np.isfinite(ss.A).all()

    # TransferFunction
    tf = TransferFunction(num=[1.0, 2.0], den=[1.0, 3.0, 2.0], id="tf-immut", revision=1)
    tf_dict_before = tf.to_dict()
    assert tf.num[0][0].flags.writeable is False
    num_copy = tf.num[0][0]
    num_copy.setflags(write=True)
    num_copy[0] = 999.0
    den_copy = tf.den[0][0]
    den_copy.setflags(write=True)
    den_copy[0] = np.nan
    assert tf.to_dict() == tf_dict_before

    # Dataset
    ds = Dataset(t=[0.0, 0.1, 0.2], u=[1.0, 0.5, -0.5], y=[0.0, 0.1, 0.2], dt=0.1, id="ds-immut", revision=1)
    ds_dict_before = ds.to_dict()
    for prop_name in ("t", "u", "y"):
        arr = getattr(ds, prop_name)
        assert arr.flags.writeable is False
        arr.setflags(write=True)
        arr[0] = np.nan
    assert ds.to_dict() == ds_dict_before

    # IdentifiedModel
    im = IdentifiedModel(
        model=tf,
        algorithm="arx",
        dataset_ref={"id": ds.id, "revision": ds.revision},
        partitions={"train": [0, 1], "validation": [2]},
        metrics={"fit_percent": 95.0},
        covariance=np.eye(2),
        id="im-immut",
        revision=1,
    )
    im_dict_before = im.to_dict()
    assert im.covariance is not None and im.covariance.flags.writeable is False
    cov_copy = im.covariance
    cov_copy.setflags(write=True)
    cov_copy[0, 0] = 12345.0
    assert im.to_dict() == im_dict_before

    # TSStateSpace
    ts = _sample_ts()
    ts_dict_before = ts.to_dict()
    v_arr = ts.vertices[0]["A"]
    assert v_arr.flags.writeable is False
    v_arr.setflags(write=True)
    v_arr[0, 0] = -999.0
    assert ts.to_dict() == ts_dict_before

    # StateFeedbackController
    sfc = StateFeedbackController(
        K=[[2.0, 3.0]],
        feedback_sign="negative",
        reference_map={"kind": "output_prefilter", "matrix": [[1.5]]},
        id="ctrl-sf-immut",
        revision=1,
    )
    sfc_dict_before = sfc.to_dict()
    k_copy = sfc.K
    assert k_copy.flags.writeable is False
    k_copy.setflags(write=True)
    k_copy[0, 0] = np.nan
    ref_mat = sfc.reference_matrix
    assert ref_mat is not None and ref_mat.flags.writeable is False
    ref_mat.setflags(write=True)
    ref_mat[0, 0] = 42.0
    ref_map = sfc.reference_map
    assert isinstance(ref_map, dict)
    ref_map["matrix"].setflags(write=True)
    ref_map["matrix"][0, 0] = -42.0
    assert sfc.to_dict() == sfc_dict_before

    # DynamicController
    dyn = DynamicController(
        Ac=[[-1.0]],
        Bc=[[1.0]],
        Cc=[[1.0]],
        Dc=[[0.2]],
        feedback_sign="negative",
        interconnection_scheme="output_feedback",
        initial_state=[0.5],
        id="ctrl-dyn-immut",
        revision=1,
    )
    dyn_dict_before = dyn.to_dict()
    for prop_name in ("Ac", "Bc", "Cc", "Dc", "initial_state"):
        arr = getattr(dyn, prop_name)
        assert arr.flags.writeable is False
        arr.setflags(write=True)
        arr[0] = 777.0
    assert dyn.to_dict() == dyn_dict_before

    # PDCController + TSClosedLoop
    pdc = PDCController(
        K_i=[[[1.0, 2.0]], [[1.5, 2.5]]],
        feedback_sign="negative",
        membership_ref={"model_id": ts.id, "model_revision": ts.revision, "membership_version": "1.0.0"},
        measurement_requirements={
            "required_premise_variables": ["x1"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_measured"],
        },
        id="ctrl-pdc-immut",
        revision=1,
    )
    pdc_dict_before = pdc.to_dict()
    pk = pdc.K_i[0]
    assert pk.flags.writeable is False
    pk.setflags(write=True)
    pk[0, 0] = 555.0
    assert pdc.to_dict() == pdc_dict_before

    ts_cl = interconnect(ts, pdc)
    a00_before = ts_cl.get_cross_matrix(0, 0).copy()
    cross_copy = ts_cl.get_cross_matrix(0, 0)
    assert cross_copy.flags.writeable is False
    cross_copy.setflags(write=True)
    cross_copy[0, 0] = 888.0
    assert np.array_equal(ts_cl.get_cross_matrix(0, 0), a00_before)


def test_with_revision_monotonicity_and_metadata_only_rules() -> None:
    ss = StateSpace(A=[[0.0, 1.0], [0.0, 0.0]], B=[[0.0], [1.0]], C=[[1.0, 0.0]], revision=3)
    # Regressão sempre proibida
    with pytest.raises(ValidationError):
        ss.with_revision(2, A=[[0.0, 1.0], [-1.0, -1.0]])
    with pytest.raises(ValidationError):
        ss.with_revision(2)

    # Mesma revisão com kwargs vazios ou alteração científica/identidade -> proibido
    with pytest.raises(ValidationError):
        ss.with_revision(3)
    with pytest.raises(ValidationError):
        ss.with_revision(3, A=[[0.0, 1.0], [-1.0, -1.0]])
    with pytest.raises(ValidationError):
        ss.with_revision(3, id="forged-id")

    # Operação de metadados em objeto ainda não selado é permitida (padrão F4)
    ss_prov = ss.with_revision(3, provenance={"source": "subspace"})
    assert ss_prov.revision == 3
    assert ss_prov.provenance["source"] == "subspace"

    # Selagem de content_hash na mesma revisão e idempotência
    ss_sealed = ss_prov.with_content_hash()
    assert ss_sealed.content_hash == ss_sealed.compute_content_hash()
    assert ss_sealed.with_content_hash().content_hash == ss_sealed.content_hash

    # Após selagem, alteração de provenance ou content_hash na mesma revisão é bloqueada
    with pytest.raises(ValidationError):
        ss_sealed.with_revision(3, provenance={"source": "tampered"})
    with pytest.raises(ValidationError):
        ss_sealed.with_revision(3, content_hash="0" * 64)
    with pytest.raises(ValidationError):
        ss.with_revision(3, content_hash="0" * 64)

    # Evolução monotônica (revision=None ou > self.revision) funciona normalmente
    ss_next = ss_sealed.with_revision(A=[[0.0, 1.0], [-1.0, -2.0]])
    assert ss_next.revision == 4
    assert ss_next.content_hash is None

    # Demais classes canônicas
    tf = TransferFunction(num=[1.0], den=[1.0, 1.0], revision=2)
    ds = Dataset(t=[0.0, 0.1], u=[1.0, 1.0], y=[0.0, 0.1], dt=0.1, revision=2)
    im = IdentifiedModel(
        model=tf,
        algorithm="arx",
        dataset_ref={"id": ds.id, "revision": ds.revision},
        partitions={"train": [0], "validation": [1]},
        metrics={"fit_percent": 90.0},
        revision=2,
    )
    ts = _sample_ts().with_revision(2)
    fz = _sample_fuzzy().with_revision(2)
    exp = Experiment(method="lqr", revision=2)
    sfc = StateFeedbackController(K=[[1.0, 2.0]], feedback_sign="negative", revision=2)
    dyn = DynamicController(Ac=[[-1.0]], Bc=[[1.0]], Cc=[[1.0]], Dc=[[0.0]], feedback_sign="negative", revision=2)
    pdc = PDCController(
        K_i=[[[1.0, 2.0]], [[1.5, 2.5]]],
        feedback_sign="negative",
        membership_ref={"model_id": ts.id, "model_revision": ts.revision, "membership_version": "1.0.0"},
        measurement_requirements={
            "required_premise_variables": ["x1"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_measured"],
        },
        revision=2,
    )

    for obj, bad_kwargs in [
        (tf, {"den": [1.0, 2.0]}),
        (ds, {"u": [0.0, 0.0]}),
        (im, {"algorithm": "oe"}),
        (ts, {"dt": 0.1}),
        (fz, {"inference_type": "mamdani"}),
        (exp, {"method": "dare"}),
        (sfc, {"K": [[3.0, 4.0]]}),
        (dyn, {"Dc": [[0.5]]}),
        (pdc, {"feedback_sign": "positive"}),
    ]:
        with pytest.raises(ValidationError):
            obj.with_revision(1)
        with pytest.raises(ValidationError):
            obj.with_revision(2)
        with pytest.raises(ValidationError):
            obj.with_revision(2, **bad_kwargs)
        # Provenance na mesma revisão continua suportada (F4)
        evolved_meta = obj.with_revision(2, provenance={"source": "audit"})
        assert evolved_meta.revision == 2
        assert evolved_meta.provenance["source"] == "audit"
        # Incremento explícito funciona
        evolved_next = obj.with_revision(3, **bad_kwargs)
        assert evolved_next.revision == 3


def test_strict_json_loads_invalid_utf8_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        strict_json_loads(b"\xff\xfe\xfd")
    with pytest.raises(ValidationError):
        strict_json_loads(bytearray(b"\x80\x81"))
    with pytest.raises(ValidationError):
        strict_json_loads('{"x": NaN}')
    with pytest.raises(ValidationError):
        strict_json_loads("{bad json")


# ---------------------------------------------------------------------------
# 2. Dispatcher RPC real: LQR, não-estabilizável, esquemas e domínios
# ---------------------------------------------------------------------------


def test_unstabilizable_plant_through_real_rpc(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    """Regressão obrigatória: A=diag(1,2), B=0 via RPC real falha com HYPOTHESIS_VIOLATED."""
    plant = StateSpace(
        A=[[1.0, 0.0], [0.0, 2.0]],
        B=[[0.0], [0.0]],
        C=[[1.0, 0.0], [0.0, 1.0]],
        D=[[0.0], [0.0]],
        id="plant-unstab",
        revision=1,
    )
    req = _make_req(
        "statespace.design_lqr",
        {
            "plant": plant.to_dict(),
            "Q": array_to_tensor(np.eye(2), dtype="float64", order="C"),
            "R": array_to_tensor(np.array([[1.0]]), dtype="float64", order="C"),
            "feedback_sign": "negative",
        },
        options={"method": "care"},
    )
    _validate_schema(req, "rpc_request.schema.json", schema_registry)
    resp = dispatch(req)
    _validate_schema(resp, "rpc_response.schema.json", schema_registry)

    assert resp["status"] == "failure"
    assert resp["result"] is None
    assert resp["error"] is not None
    assert resp["error"]["code"] == "HYPOTHESIS_VIOLATED"

    # Também via matrizes diretas (sem objeto StateSpace) e via plant_ref no store
    req_ref = _make_req(
        "statespace.design_lqr",
        {
            "plant_ref": {"id": plant.id, "revision": plant.revision},
            "Q": array_to_tensor(np.eye(2)),
            "R": array_to_tensor(np.array([[1.0]])),
            "feedback_sign": "negative",
        },
    )
    _validate_schema(req_ref, "rpc_request.schema.json", schema_registry)
    resp_ref = dispatch(req_ref, store={(plant.id, plant.revision): plant})
    _validate_schema(resp_ref, "rpc_response.schema.json", schema_registry)
    assert resp_ref["status"] == "failure"
    assert resp_ref["error"]["code"] == "HYPOTHESIS_VIOLATED"


def test_rpc_example_lqr_b_care_02_and_b_care_12x3_and_dare(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    example_req = json.loads((EXAMPLES_DIR / "rpc_request_lqr.json").read_text(encoding="utf-8"))
    example_resp = json.loads((EXAMPLES_DIR / "rpc_response_lqr.json").read_text(encoding="utf-8"))
    _validate_schema(example_req, "rpc_request.schema.json", schema_registry)
    _validate_schema(example_resp, "rpc_response.schema.json", schema_registry)

    b12 = json.loads((FIXTURES_DIR / "B-CARE-12x3.json").read_text(encoding="utf-8"))
    b12_plant = StateSpace(
        A=np.asarray(b12["data"]["A"]["data"]).reshape(tuple(b12["data"]["A"]["shape"])),
        B=np.asarray(b12["data"]["B"]["data"]).reshape(tuple(b12["data"]["B"]["shape"])),
        C=np.eye(12),
        D=np.zeros((12, 3)),
        id="plant-001",
        revision=3,
    )

    # Sem buffers fornecidos, buffer_ref não reidratado deve falhar com VALIDATION_ERROR
    resp_no_buf = dispatch(example_req, store={(b12_plant.id, b12_plant.revision): b12_plant})
    _validate_schema(resp_no_buf, "rpc_response.schema.json", schema_registry)
    assert resp_no_buf["status"] == "failure"
    assert resp_no_buf["error"]["code"] == "VALIDATION_ERROR"

    # Com store + buffers (reidratação real de Q-01 / R-01 para B-CARE-12x3)
    Q_buf = np.asarray(b12["data"]["Q"]["data"], dtype=np.float64).reshape((12, 12)).tobytes()
    R_buf = np.asarray(b12["data"]["R"]["data"], dtype=np.float64).reshape((3, 3)).tobytes()
    resp_b12_ex = dispatch(
        example_req,
        store={(b12_plant.id, b12_plant.revision): b12_plant},
        buffers={"Q-01": Q_buf, "R-01": R_buf},
    )
    _validate_schema(resp_b12_ex, "rpc_response.schema.json", schema_registry)
    assert resp_b12_ex["status"] in ("success", "warning")
    assert resp_b12_ex["provenance"]["model_revision"] == 3
    assert resp_b12_ex["diagnostics"]["care_residual_rel"] < 1e-10
    assert "time_response" in resp_b12_ex["result"]

    # Planta analítica B-CARE-02 exatamente na revisão 3 (comparação exata com rpc_response_lqr.json)
    b_care_02_ss = StateSpace(
        A=[[0.0, 1.0], [0.0, 0.0]],
        B=[[0.0], [1.0]],
        C=[[1.0, 0.0], [0.0, 1.0]],
        D=[[0.0], [0.0]],
        id="plant-001",
        revision=3,
    )
    req_b02 = _make_req(
        "statespace.design_lqr",
        {
            "plant_ref": {"id": b_care_02_ss.id, "revision": b_care_02_ss.revision},
            "Q": array_to_tensor(np.diag([4.0, 5.0])),
            "R": array_to_tensor(np.array([[1.0]])),
            "feedback_sign": "negative",
        },
        options={"method": "care"},
    )
    _validate_schema(req_b02, "rpc_request.schema.json", schema_registry)
    resp = dispatch(req_b02, store={(b_care_02_ss.id, b_care_02_ss.revision): b_care_02_ss})
    _validate_schema(resp, "rpc_response.schema.json", schema_registry)

    assert resp["status"] == "success"
    assert resp["error"] is None
    assert resp["provenance"]["model_revision"] == 3
    assert resp["assumptions"]["stabilizable"] is True
    assert resp["assumptions"]["detectable"] is True
    assert resp["assumptions"]["R_positive_definite"] is True
    assert resp["diagnostics"]["care_residual_rel"] < 1e-12
    assert resp["diagnostics"]["symmetry_error"] < 1e-12

    K = np.asarray(resp["result"]["K"]["data"], dtype=np.float64).reshape(tuple(resp["result"]["K"]["shape"]))
    P = np.asarray(resp["result"]["P"]["data"], dtype=np.float64).reshape(tuple(resp["result"]["P"]["shape"]))
    assert np.allclose(K, [[2.0, 3.0]], atol=1e-12)
    assert np.allclose(P, [[6.0, 2.0], [2.0, 3.0]], atol=1e-12)
    assert np.allclose(resp["result"]["closed_loop_poles"]["real"], [-2.0, -1.0], atol=1e-12)
    assert np.allclose(resp["result"]["closed_loop_poles"]["imag"], [0.0, 0.0], atol=1e-12)

    # Fluxo LQRWorkspace (envelope Worker + compute_time_response=True + feedback_sign="positive")
    worker_envelope = {
        "request": _make_req(
            "statespace.design_lqr",
            {
                "plant_ref": {"id": b_care_02_ss.id, "revision": b_care_02_ss.revision},
                "Q": array_to_tensor(np.diag([4.0, 5.0])),
                "R": array_to_tensor(np.array([[1.0]])),
                "x0": [1.0, 1.0],
                "feedback_sign": "positive",
            },
            options={"method": "care", "compute_time_response": True},
        ),
        "payload": {
            "plant": b_care_02_ss.to_dict(),
            "Q": array_to_tensor(np.diag([4.0, 5.0])),
            "R": array_to_tensor(np.array([[1.0]])),
            "x0": [1.0, 1.0],
            "feedback_sign": "positive",
        },
    }
    resp_pos = dispatch(worker_envelope)
    _validate_schema(resp_pos, "rpc_response.schema.json", schema_registry)
    assert resp_pos["status"] == "success"
    K_pos = np.asarray(resp_pos["result"]["K"]["data"]).reshape((1, 2))
    assert np.allclose(K_pos, [[-2.0, -3.0]], atol=1e-12)
    assert np.isclose(resp_pos["result"]["optimal_cost"], 13.0, atol=1e-12)
    tr = resp_pos["result"]["time_response"]
    assert len(tr["t"]) == 101
    assert np.isclose(tr["u"][0][0], -5.0, atol=1e-12)

    # Benchmark MIMO B-CARE-12x3 real
    b12 = json.loads((FIXTURES_DIR / "B-CARE-12x3.json").read_text(encoding="utf-8"))
    ss12 = StateSpace(
        A=b12["data"]["A"]["data"] if False else np.asarray(b12["data"]["A"]["data"]).reshape(tuple(b12["data"]["A"]["shape"])),
        B=np.asarray(b12["data"]["B"]["data"]).reshape(tuple(b12["data"]["B"]["shape"])),
        C=np.eye(12),
        D=np.zeros((12, 3)),
        id="b-care-12x3",
        revision=1,
    )
    req12 = _make_req(
        "statespace.design_lqr",
        {
            "plant": ss12.to_dict(),
            "Q": b12["data"]["Q"],
            "R": b12["data"]["R"],
            "feedback_sign": "negative",
        },
        options={"method": "care"},
    )
    _validate_schema(req12, "rpc_request.schema.json", schema_registry)
    resp12 = dispatch(req12)
    _validate_schema(resp12, "rpc_response.schema.json", schema_registry)
    assert resp12["status"] in ("success", "warning")
    assert resp12["diagnostics"]["care_residual_rel"] < 1e-10
    assert max(resp12["result"]["closed_loop_poles"]["real"]) < 0.0

    # Caso discreto DARE
    ss_d = StateSpace(
        A=[[1.0, 0.1], [0.0, 1.0]],
        B=[[0.005], [0.1]],
        C=[[1.0, 0.0]],
        D=[[0.0]],
        dt=0.1,
        id="plant-disc",
        revision=1,
    )
    req_d = _make_req(
        "statespace.design_lqr",
        {
            "plant": ss_d.to_dict(),
            "Q": array_to_tensor(np.eye(2)),
            "R": array_to_tensor(np.array([[1.0]])),
            "feedback_sign": "negative",
        },
        options={"method": "dare", "compute_time_response": True},
    )
    _validate_schema(req_d, "rpc_request.schema.json", schema_registry)
    resp_d = dispatch(req_d)
    _validate_schema(resp_d, "rpc_response.schema.json", schema_registry)
    assert resp_d["status"] == "success"
    mags = np.hypot(
        resp_d["result"]["closed_loop_poles"]["real"],
        resp_d["result"]["closed_loop_poles"]["imag"],
    )
    assert np.all(mags < 1.0)


def test_rpc_error_propagation_and_schema_compliance(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    # 1. api_version incompatível -> SCHEMA_UNSUPPORTED
    resp_ver = dispatch(_make_req("worker.ping", {}, api_version="2.0"))
    _validate_schema(resp_ver, "rpc_response.schema.json", schema_registry)
    assert resp_ver["status"] == "failure"
    assert resp_ver["error"]["code"] == "SCHEMA_UNSUPPORTED"

    # 2. JSON inválido / UTF-8 corrompido / operação inválida -> VALIDATION_ERROR
    resp_utf8 = dispatch(b"\xff\xfe\x00")
    _validate_schema(resp_utf8, "rpc_response.schema.json", schema_registry)
    assert resp_utf8["status"] == "failure"
    assert resp_utf8["error"]["code"] == "VALIDATION_ERROR"

    resp_bad_op = dispatch(_make_req("BadOperation", {}))
    _validate_schema(resp_bad_op, "rpc_response.schema.json", schema_registry)
    assert resp_bad_op["status"] == "failure"
    assert resp_bad_op["error"]["code"] == "VALIDATION_ERROR"

    # 3. Operação desconhecida -> UNSUPPORTED_MODEL
    resp_unk = dispatch(_make_req("quantum.teleport", {}))
    _validate_schema(resp_unk, "rpc_response.schema.json", schema_registry)
    assert resp_unk["status"] == "failure"
    assert resp_unk["error"]["code"] == "UNSUPPORTED_MODEL"

    # 4. TransferFunction enviada para statespace.design_lqr -> UNSUPPORTED_MODEL
    tf = TransferFunction(num=[1.0], den=[1.0, 1.0], id="tf-err", revision=0)
    resp_tf = dispatch(
        _make_req(
            "statespace.design_lqr",
            {"plant": tf.to_dict(), "Q": [[1.0]], "R": [[1.0]]},
        )
    )
    _validate_schema(resp_tf, "rpc_response.schema.json", schema_registry)
    assert resp_tf["status"] == "failure"
    assert resp_tf["error"]["code"] == "UNSUPPORTED_MODEL"

    # 5. Planta discreta com method='care' -> UNSUPPORTED_MODEL
    ss_d = StateSpace(A=[[0.9]], B=[[1.0]], C=[[1.0]], D=[[0.0]], dt=0.1)
    resp_dom = dispatch(
        _make_req(
            "statespace.design_lqr",
            {"plant": ss_d.to_dict(), "Q": [[1.0]], "R": [[1.0]]},
            options={"method": "care"},
        )
    )
    _validate_schema(resp_dom, "rpc_response.schema.json", schema_registry)
    assert resp_dom["status"] == "failure"
    assert resp_dom["error"]["code"] == "UNSUPPORTED_MODEL"

    # 6. Dimensão incompatível de Q -> DIMENSION_MISMATCH
    ss_c = StateSpace(A=[[0.0, 1.0], [-1.0, -1.0]], B=[[0.0], [1.0]], C=[[1.0, 0.0]])
    resp_dim = dispatch(
        _make_req(
            "statespace.design_lqr",
            {"plant": ss_c.to_dict(), "Q": np.eye(3), "R": [[1.0]]},
        )
    )
    _validate_schema(resp_dim, "rpc_response.schema.json", schema_registry)
    assert resp_dim["status"] == "failure"
    assert resp_dim["error"]["code"] == "DIMENSION_MISMATCH"

    # 7. R não definida positiva -> HYPOTHESIS_VIOLATED
    resp_r = dispatch(
        _make_req(
            "statespace.design_lqr",
            {"plant": ss_c.to_dict(), "Q": np.eye(2), "R": [[-1.0]]},
        )
    )
    _validate_schema(resp_r, "rpc_response.schema.json", schema_registry)
    assert resp_r["status"] == "failure"
    assert resp_r["error"]["code"] == "HYPOTHESIS_VIOLATED"

    # 8. timeout_policy.soft_timeout_ms (mínimo 1, sem None/bool) -> VALIDATION_ERROR
    for bad_soft in (0, -1, None, True):
        req_soft = _make_req("worker.ping", {})
        req_soft["timeout_policy"] = {"hard_timeout_ms": 1000, "soft_timeout_ms": bad_soft}
        resp_soft = dispatch(req_soft)
        _validate_schema(resp_soft, "rpc_response.schema.json", schema_registry)
        assert resp_soft["status"] == "failure"
        assert resp_soft["error"]["code"] == "VALIDATION_ERROR"

    # 9. buffer_ref com buffer truncado de tamanho em bytes não múltiplo de itemsize -> DIMENSION_MISMATCH (nunca INTERNAL_ERROR)
    req_trunc_buf = _make_req(
        "statespace.design_lqr",
        {
            "plant": ss_c.to_dict(),
            "Q": {"shape": [2, 2], "dtype": "float64", "order": "C", "buffer_ref": "Q-trunc"},
            "R": array_to_tensor(np.array([[1.0]])),
        },
    )
    resp_trunc = dispatch(req_trunc_buf, buffers={"Q-trunc": b"\x00\x01\x02"})
    _validate_schema(resp_trunc, "rpc_response.schema.json", schema_registry)
    assert resp_trunc["status"] == "failure"
    assert resp_trunc["error"]["code"] in ("DIMENSION_MISMATCH", "VALIDATION_ERROR")
    assert resp_trunc["error"]["code"] != "INTERNAL_ERROR"


def test_rpc_multidomain_operations_dispatch_real_engines(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    ss = StateSpace(
        A=[[0.0, 1.0], [-2.0, -3.0]],
        B=[[0.0], [1.0]],
        C=[[1.0, 0.0]],
        D=[[0.0]],
        id="ss-multi",
        revision=1,
    )

    # worker.ping e worker.get_stats
    for op in ("worker.ping", "worker.get_stats", "optimization.capabilities"):
        r = dispatch(_make_req(op, {}))
        _validate_schema(r, "rpc_response.schema.json", schema_registry)
        assert r["status"] == "success"

    # statespace.analyze, check_pbh, simulate_lti, discretize_zoh, solve_lyapunov, design_pole_placement
    for op, payload in [
        ("statespace.analyze", {"plant": ss.to_dict()}),
        ("statespace.check_pbh", {"plant": ss.to_dict()}),
        ("statespace.simulate_lti", {"plant": ss.to_dict(), "t_final": 2.0, "n_steps": 21, "x0": [1.0, 0.0]}),
        ("statespace.discretize_zoh", {"plant": ss.to_dict(), "dt": 0.05}),
        ("statespace.solve_lyapunov", {"plant": ss.to_dict(), "Q": [[1.0, 0.0], [0.0, 1.0]]}),
        ("statespace.design_pole_placement", {"plant": ss.to_dict(), "poles": {"real": [-4.0, -5.0], "imag": [0.0, 0.0]}}),
        ("statespace.design_observer", {"plant": ss.to_dict(), "poles": {"real": [-6.0, -7.0], "imag": [0.0, 0.0]}}),
        ("statespace.design_kalman", {"plant": ss.to_dict(), "Qn": [[0.1]], "Rn": [[0.01]], "G": [[0.0], [1.0]]}),
    ]:
        r = dispatch(_make_req(op, payload))
        _validate_schema(r, "rpc_response.schema.json", schema_registry)
        assert r["status"] in ("success", "warning"), f"{op} falhou: {r['error']}"

    # frequency.bode, stability_margins, mimo.singular_values
    tf_siso = TransferFunction(num=[1.0], den=[1.0, 2.0], id="tf-1st", revision=1)
    for op, payload in [
        ("frequency.bode", {"plant": tf_siso.to_dict(), "w_min": 0.1, "w_max": 100.0, "n_points": 30}),
        ("frequency.stability_margins", {"plant": TransferFunction(num=[2.0], den=[1.0, 3.0, 2.0, 0.0]).to_dict()}),
        ("mimo.singular_values", {"plant": ss.to_dict(), "w_min": 0.1, "w_max": 10.0, "n_points": 20}),
    ]:
        r = dispatch(_make_req(op, payload))
        _validate_schema(r, "rpc_response.schema.json", schema_registry)
        assert r["status"] in ("success", "warning"), f"{op} falhou: {r['error']}"

    # identification.fit_arx (com sinal PRBS / multi-senoidal persistente)
    t_id = np.arange(80, dtype=np.float64) * 0.1
    u_id = np.sin(0.7 * t_id) + 0.5 * np.cos(1.9 * t_id) + 0.3 * np.sin(3.3 * t_id)
    y_id = np.zeros_like(u_id)
    for k in range(1, len(u_id)):
        y_id[k] = 0.7 * y_id[k - 1] + 0.3 * u_id[k - 1]
    ds_id = Dataset(t=t_id, u=u_id, y=y_id, dt=0.1, id="ds-arx", revision=1)
    r_arx = dispatch(
        _make_req(
            "identification.fit_arx",
            {"dataset": ds_id.to_dict(), "na": 1, "nb": 1, "nk": 1},
        )
    )
    _validate_schema(r_arx, "rpc_response.schema.json", schema_registry)
    assert r_arx["status"] in ("success", "warning")
    assert r_arx["result"]["metrics"]["train"]["one_step_prediction"]["fit_percent"] > 99.0

    # fuzzy.evaluate e fuzzy.evaluate_surface
    fz = _sample_fuzzy()
    r_fz = dispatch(_make_req("fuzzy.evaluate", {"system": fz.to_dict(), "inputs": {"x1": 0.0}}))
    _validate_schema(r_fz, "rpc_response.schema.json", schema_registry)
    assert r_fz["status"] == "success"
    # w_low(0)=0.5 -> y1=0.0, w_high(0)=0.5 -> y2=1.0 -> média 0.5
    assert np.isclose(r_fz["result"]["outputs"]["y"], 0.5, atol=1e-12)

    r_surf = dispatch(_make_req("fuzzy.evaluate_surface", {"system": fz.to_dict(), "n_points": 11}))
    _validate_schema(r_surf, "rpc_response.schema.json", schema_registry)
    assert r_surf["status"] == "success"

    # optimization.verify e optimization.solve contra fixture real B-SDP-A-D (T-SDP-A1 diagonal LP)
    b_sdp = json.loads((FIXTURES_DIR / "B-SDP-A-D.json").read_text(encoding="utf-8"))
    case_a1 = b_sdp["data"]["cases"]["T-SDP-A1"]
    r_ver = dispatch(
        _make_req(
            "optimization.verify",
            {
                "canonical_sdp": case_a1["canonical_sdp"],
                "solution": {
                    "solver_status": "optimal",
                    "x": case_a1["expected"]["x_opt"],
                    "dual_Z": case_a1["expected"]["dual_Z"],
                },
            },
        )
    )
    _validate_schema(r_ver, "rpc_response.schema.json", schema_registry)
    assert r_ver["status"] in ("success", "warning")
    assert r_ver["result"]["audit_feasibility"] == case_a1["expected"]["audit_feasibility"]
    assert r_ver["result"]["certificate_status"] == case_a1["expected"]["certificate_status"]

    r_lp_solve = dispatch(
        _make_req(
            "optimization.solve",
            {"canonical_sdp": case_a1["canonical_sdp"]},
        )
    )
    _validate_schema(r_lp_solve, "rpc_response.schema.json", schema_registry)
    assert r_lp_solve["status"] in ("success", "warning")
    assert np.isclose(r_lp_solve["result"]["objective"], 1.0, atol=1e-7)



@pytest.mark.parametrize("case_id", ["T-SDP-B1", "T-SDP-D1"])
def test_rpc_auto_sdp_against_real_backend_profile(
    case_id: str, schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    fixture = json.loads((FIXTURES_DIR / "B-SDP-A-D.json").read_text(encoding="utf-8"))
    case = fixture["data"]["cases"][case_id]
    tolerances = fixture["tolerances"]
    if case_id == "T-SDP-B1":
        problem = {"canonical_sdp": case["canonical_sdp"]}
    else:
        problem = {
            "template": "quadratic_stabilization",
            **{key: case[key] for key in ("A", "B", "alpha", "feedback_sign")},
        }

    response = dispatch(_make_req("optimization.solve", problem))
    _validate_schema(response, "rpc_response.schema.json", schema_registry)
    # ADR-010: the native audited backend also serves the no-Clarabel profile.
    assert response["status"] == "success", response["error"]
    result = response["result"]
    assert result["solver_status"] == "optimal"
    solution = {key: result[key] for key in ("solver_status", "x", "dual_Z")}
    audited = dispatch(_make_req("optimization.verify", {**problem, "solution": solution}))
    _validate_schema(audited, "rpc_response.schema.json", schema_registry)
    assert audited["status"] == "success", audited["error"]
    assert audited["assumptions"]["independent_audit"] is True
    audit = audited["result"]
    assert audit["certificate_status"] == result["certificate_status"] == "validated_dual"
    residuals = audit["residuals"]
    assert max(residuals["primal_block_violations_rel"]) <= tolerances["primal_tol"]
    assert min(residuals["dual_block_min_eigs"]) >= -tolerances["psd_tol"]
    assert residuals["dual_stationarity_rel"] <= tolerances["dual_tol"]
    assert residuals["duality_gap_rel"] <= tolerances["gap_tol"]

    if case_id == "T-SDP-B1":
        expected = case["expected"]
        assert audit["audit_feasibility"] == expected["audit_feasibility"]
        np.testing.assert_allclose(tensor_to_array(result["x"]), expected["x_opt"],
                                   atol=tolerances["primal_tol"], rtol=0)
        assert abs(result["objective"] - expected["obj_opt"]) <= tolerances["primal_tol"]
    else:
        q = tensor_to_array(audit["variables"]["Q"])
        y = tensor_to_array(audit["variables"]["Y"])
        assert np.linalg.eigvalsh(q).min() > 0
        gain = np.linalg.solve(q.T, y.T).T
        closed_loop = tensor_to_array(case["A"]) + tensor_to_array(case["B"]) @ gain
        assert np.max(np.linalg.eigvals(closed_loop).real) < -case["alpha"]
