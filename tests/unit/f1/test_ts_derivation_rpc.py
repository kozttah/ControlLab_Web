"""T-TSMOD-07/08: canonical RPC and passive workspace transport."""

import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core.rpc import dispatch
from control_lab.core.serialization import restore_model
from control_lab.fuzzy.ts_bridge import evaluate_ts_premise_weights

OPERATIONS = {
    "fuzzy.analyze_sector_premises",
    "fuzzy.derive_ts_sector",
    "fuzzy.derive_ts_tpmt",
    "fuzzy.derive_ts_femt",
    "fuzzy.export_ts_derivation_script",
}


@pytest.fixture(scope="module")
def schemas():
    directory = Path(__file__).resolve().parents[3] / "contracts" / "schemas"
    contents = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.schema.json")
    }
    registry = Registry().with_resources(
        (doc["$id"], Resource.from_contents(doc)) for doc in contents.values()
    )
    return {
        name: Draft202012Validator(doc, registry=registry)
        for name, doc in contents.items()
    }


def _request(operation, payload):
    return {
        "api_version": "1.0",
        "request_id": f"test-{operation}",
        "project_id": "ts-derivation-rpc",
        "project_revision": 1,
        "operation": operation,
        "payload": payload,
        "options": {},
        "timeout_policy": {"hard_timeout_ms": 30000},
    }


def _call(schemas, operation, payload, *, store=None, expected_error=None):
    request = _request(operation, payload)
    schemas["rpc_request.schema.json"].validate(request)
    response = dispatch(request, store=store)
    schemas["rpc_response.schema.json"].validate(response)
    assert response["request_id"] == request["request_id"]
    assert response["project_revision"] == request["project_revision"]
    if expected_error is not None:
        assert response["status"] == "failure"
        assert response["result"] is None
        assert response["error"]["code"] == expected_error
    else:
        assert response["status"] in {"success", "warning"}, response["error"]
        return response["result"]


def _sector_premises():
    return {
        "state_bounds": {"x1": [-1.0, 1.0]},
        "premises": [{"name": "z1", "expression": "x1"}],
    }


def test_modeling_rpc_catalog_and_sector_analysis(schemas):
    capabilities = _call(schemas, "core.capabilities", {})
    assert OPERATIONS <= set(capabilities["supported_operations"])

    analyzed = _call(schemas, "fuzzy.analyze_sector_premises", _sector_premises())
    premise = analyzed["premises"][0]
    assert premise["name"] == "z1"
    assert premise["min"] == pytest.approx(-1.0)
    assert premise["max"] == pytest.approx(1.0)
    _call(schemas, "fuzzy.analyze_sector_premises", {}, expected_error="VALIDATION_ERROR")
    _call(
        schemas,
        "fuzzy.derive_ts_femt",
        {"unsafe_extra_field": 1},
        expected_error="VALIDATION_ERROR",
    )
    _call(
        schemas,
        "fuzzy.derive_ts_sector",
        {
            **_sector_premises(),
            "A_expr": [["z1^2"]],
            "B_expr": [[1.0]],
        },
        expected_error="HYPOTHESIS_VIOLATED",
    )


@pytest.fixture(
    params=[
        ("sector", "sector_nonlinearity", {}),
        ("tpmt", "tpmt_interpolated", {"grid_points": 5}),
        ("femt", "femt_simplicial", {"grid_points": 5, "mesh_kind": "kuhn_delaunay"}),
        ("femt", "femt_simplicial", {"grid_points": 5, "mesh_kind": "delaunay"}),
    ],
    ids=["sector", "tpmt", "femt-kuhn", "femt-delaunay"],
)
def model_data(request, schemas):
    method, representation, options = request.param
    payload = {
        "state_bounds": {"x1": [-1.0, 1.0]},
        "A_expr": [["-2 + 0.5*x1"]],
        "B_expr": [[1.0]],
        "n_val_points": 64,
        **options,
    }
    if method == "sector":
        payload.update(_sector_premises(), A_expr=[["-2 + 0.5*z1"]])
    result = _call(schemas, f"fuzzy.derive_ts_{method}", payload)
    assert result["num_rules"] == 2
    data = result["ts_state_space"]
    schemas["ts_state_space.schema.json"].validate(data)
    assert data["membership_spec"]["representation_kind"] == representation
    assert data["provenance"]["ts_derivation"]["method"]
    return data


def test_derived_model_ctrlab_round_trip(schemas, model_data):
    file = _call(schemas, "io.export_ctrlab", {"project": {"models": [model_data]}})
    restored = _call(schemas, "io.import_ctrlab", {"bytes_base64": file["bytes_base64"]})
    assert restored["models"] == [model_data]
    model = restore_model(restored["models"][0])
    plant_vertices = np.array([vertex["A"][0, 0] for vertex in model.vertices])
    for x in [-1.0, -0.37, 0.2, 1.0]:
        evaluation = evaluate_ts_premise_weights(model, {"x1": x})
        assert evaluation.status == "success", evaluation.error
        weights = np.asarray(evaluation.data["weights"])
        assert np.min(weights) >= -1e-13
        assert np.sum(weights) == pytest.approx(1.0)
        assert weights @ plant_vertices == pytest.approx(-2.0 + 0.5 * x, abs=1e-12)


def test_export_ts_derivation_script_rpc(schemas, model_data):
    for language, extension in [("python", ".py"), ("matlab", ".m")]:
        operation = "fuzzy.export_ts_derivation_script"
        result = _call(schemas, operation, {"model": model_data, "language": language})
        assert result["language"] == language
        assert result["filename"].endswith(extension)
        assert result["code_executed"] is False
        assert result["requires_explicit_user_execution"] is True
        model_id, revision = model_data["id"], model_data["revision"]
        by_ref = _call(
            schemas,
            operation,
            {"model_ref": {"id": model_id, "revision": revision}, "language": language},
            store={("ts-derivation-rpc", model_id, revision): model_data},
        )
        assert result == by_ref
        if language == "python":
            compile(result["script"], result["filename"], "exec")


def test_export_ts_derivation_script_rejects_invalid_language_or_missing_model(schemas):
    operation = "fuzzy.export_ts_derivation_script"
    _call(schemas, operation, {"language": "python"}, expected_error="VALIDATION_ERROR")
    _call(
        schemas,
        operation,
        {"model_ref": {"id": "missing", "revision": 1}, "language": "matlab"},
        expected_error="VALIDATION_ERROR",
    )
    _call(
        schemas,
        operation,
        {"model_ref": {"id": "missing", "revision": 1}, "language": "octave"},
        expected_error="VALIDATION_ERROR",
    )
