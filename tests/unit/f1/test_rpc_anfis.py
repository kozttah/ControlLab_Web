"""Unit tests for fuzzy.fit_anfis RPC operation in control_lab.core.rpc."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core.rpc import SUPPORTED_OPERATIONS, dispatch_rpc


def _rpc_request(operation: str, payload: dict, *, options: dict | None = None) -> dict:
    return {
        "api_version": "1.0",
        "request_id": f"req-{operation}",
        "project_id": "proj-anfis",
        "project_revision": 1,
        "operation": operation,
        "payload": payload,
        "options": options or {},
        "timeout_policy": {"hard_timeout_ms": 30000},
    }


def _validate_rpc_response_schema(response: dict) -> None:
    schemas_dir = Path(__file__).resolve().parents[3] / "contracts/schemas"
    registry = Registry()
    for schema_file in schemas_dir.glob("*.schema.json"):
        raw = json.loads(schema_file.read_text(encoding="utf-8"))
        resource = Resource.from_contents(raw)
        registry = registry.with_resource(schema_file.name, resource)
        if "$id" in raw:
            registry = registry.with_resource(raw["$id"], resource)
    rpc_schema = json.loads((schemas_dir / "rpc_response.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(rpc_schema, registry=registry).validate(response)


class _DummyStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, int], object] = {}

    def put(self, project_id: str, obj_id: str, revision: int, obj: object) -> None:
        self._items[(project_id, obj_id, revision)] = obj

    def get(self, project_id: str, obj_id: str, revision: int) -> object | None:
        return self._items.get((project_id, obj_id, revision))


def test_supported_operations_register_fuzzy_fit_anfis():
    assert "fuzzy.fit_anfis" in SUPPORTED_OPERATIONS

    cap_resp = dispatch_rpc(_rpc_request("core.capabilities", {}))
    assert cap_resp["status"] == "success"
    assert "fuzzy.fit_anfis" in cap_resp["result"]["supported_operations"]


def test_rpc_fuzzy_fit_anfis_2d_dataset():
    rng = np.random.default_rng(7)
    X = rng.uniform(-2.0, 2.0, size=(60, 2))
    y = np.sin(X[:, 0]) + 0.5 * X[:, 1]

    req = _rpc_request(
        "fuzzy.fit_anfis",
        {
            "X": X.tolist(),
            "y": y.tolist(),
            "n_mfs": 2,
            "mf_type": "gaussian",
            "max_epochs": 15,
            "learning_rate": 0.02,
            "validation_split": 0.2,
            "input_names": ["x1", "x2"],
            "output_name": "y",
        },
    )
    resp = dispatch_rpc(req)
    _validate_rpc_response_schema(resp)

    assert resp["status"] == "success"
    result = resp["result"]
    assert "fuzzy_system" in result
    assert result["fuzzy_system"]["kind"] == "FuzzySystem"
    assert result["fuzzy_system"]["inference_type"] == "ts"
    train_rmse_history = result["training_history"]["train_rmse"]
    assert isinstance(train_rmse_history, list)
    assert len(train_rmse_history) > 0
    assert result["metrics"]["train_rmse"] >= 0.0


def test_rpc_fuzzy_fit_anfis_registers_in_store_and_evaluates():
    x = np.linspace(-1.0, 1.0, 24)
    y = 2.0 * x + 0.5

    store = _DummyStore()
    req = _rpc_request(
        "fuzzy.fit_anfis",
        {
            "X": x.tolist(),
            "y": y.tolist(),
            "n_mfs": 2,
            "max_epochs": 10,
            "validation_split": 0.2,
            "input_names": ["x"],
            "output_name": "y",
        },
    )
    resp = dispatch_rpc(req, store=store)
    _validate_rpc_response_schema(resp)

    assert resp["status"] == "success"
    ref = resp["result"].get("fuzzy_system_ref")
    assert ref is not None
    assert "id" in ref and "revision" in ref

    eval_resp = dispatch_rpc(
        _rpc_request(
            "fuzzy.evaluate",
            {
                "system_ref": ref,
                "inputs": {"x": 0.0},
            },
        ),
        store=store,
    )
    _validate_rpc_response_schema(eval_resp)
    assert eval_resp["status"] == "success"


def test_rpc_fuzzy_fit_anfis_missing_inputs_fails_typed():
    resp = dispatch_rpc(_rpc_request("fuzzy.fit_anfis", {"X": [[1.0, 2.0]]}))
    _validate_rpc_response_schema(resp)
    assert resp["status"] == "failure"
    assert resp["error"] is not None


def test_rpc_fuzzy_fit_anfis_multi_output_heterogeneous_mfs_and_store():
    rng = np.random.default_rng(19)
    X = rng.uniform(-1.5, 1.5, size=(64, 2))
    y1 = 1.2 * X[:, 0] - 0.6 * X[:, 1] + 0.3
    y2 = -0.4 * X[:, 0] + 0.9 * np.sin(X[:, 1])
    Y = np.column_stack([y1, y2])

    store = _DummyStore()
    req = _rpc_request(
        "fuzzy.fit_anfis",
        {
            "X": X.tolist(),
            "y": Y.tolist(),
            "n_mfs": [2, 3],
            "mf_type": ["gaussian", "bell"],
            "max_epochs": 8,
            "learning_rate": 0.015,
            "validation_split": 0.2,
            "early_stopping_patience": 5,
            "seed": 19,
            "input_names": ["e", "de"],
            "output_names": ["u1", "u2"],
        },
    )
    resp = dispatch_rpc(req, store=store)
    _validate_rpc_response_schema(resp)

    assert resp["status"] == "success"
    result = resp["result"]
    fs = result["fuzzy_system"]
    assert fs["kind"] == "FuzzySystem"
    assert [v["name"] for v in fs["input_variables"]] == ["e", "de"]
    assert [len(v["terms"]) for v in fs["input_variables"]] == [2, 3]
    assert [v["terms"][0]["mf"] for v in fs["input_variables"]] == ["gaussian", "bell"]
    assert [v["name"] for v in fs["output_variables"]] == ["u1", "u2"]

    ref = result.get("fuzzy_system_ref")
    assert ref is not None
    assert "id" in ref and "revision" in ref
    assert store.get("proj-anfis", ref["id"], ref["revision"]) is not None


def test_rpc_fuzzy_evaluate_surface_3in_2out_with_fixed_inputs_and_output_name():
    rng = np.random.default_rng(23)
    X = rng.uniform(-1.0, 1.0, size=(72, 3))
    y1 = 2.0 * X[:, 0] + 0.5 * X[:, 1] - 0.3 * X[:, 2]
    y2 = -1.5 * X[:, 0] + 1.2 * X[:, 2] + 0.8
    Y = np.column_stack([y1, y2])

    store = _DummyStore()
    fit_resp = dispatch_rpc(
        _rpc_request(
            "fuzzy.fit_anfis",
            {
                "X": X.tolist(),
                "y": Y.tolist(),
                "n_mfs": [2, 2, 2],
                "mf_type": ["gaussian", "bell", "gaussian"],
                "max_epochs": 6,
                "validation_split": 0.2,
                "seed": 23,
                "input_names": ["x1", "x2", "x3"],
                "output_names": ["u1", "u2"],
            },
        ),
        store=store,
    )
    _validate_rpc_response_schema(fit_resp)
    assert fit_resp["status"] == "success"
    ref = fit_resp["result"]["fuzzy_system_ref"]

    surf_u2 = dispatch_rpc(
        _rpc_request(
            "fuzzy.evaluate_surface",
            {
                "system_ref": ref,
                "input_axes": ["x1", "x3"],
                "fixed_inputs": {"x2": 0.25},
                "output_name": "u2",
                "n_points": 6,
            },
        ),
        store=store,
    )
    _validate_rpc_response_schema(surf_u2)
    assert surf_u2["status"] == "success"
    s2 = surf_u2["result"]
    assert s2["axes"] == ["x1", "x3"]
    assert s2["output_name"] == "u2"
    assert len(s2["grids"]["x1"]) == 6
    assert len(s2["grids"]["x3"]) == 6
    assert s2["Z"] == s2["surfaces"]["u2"]
    assert s2["Z"] != s2["surfaces"]["u1"]

    bad_name = dispatch_rpc(
        _rpc_request(
            "fuzzy.evaluate_surface",
            {
                "system_ref": ref,
                "input_axes": ["x1", "x3"],
                "output_name": "u_missing",
                "n_points": 5,
            },
        ),
        store=store,
    )
    _validate_rpc_response_schema(bad_name)
    assert bad_name["status"] == "failure"
    assert bad_name["error"]["code"] == "VALIDATION_ERROR"

    bad_type = dispatch_rpc(
        _rpc_request(
            "fuzzy.evaluate_surface",
            {
                "system_ref": ref,
                "input_axes": ["x1", "x3"],
                "output_name": 42,
                "n_points": 5,
            },
        ),
        store=store,
    )
    _validate_rpc_response_schema(bad_type)
    assert bad_type["status"] == "failure"
    assert bad_type["error"]["code"] == "VALIDATION_ERROR"


def test_rpc_fuzzy_fit_anfis_rejects_3d_y_and_invalid_mf_type():
    X = np.zeros((10, 2), dtype=float)
    y_3d = np.zeros((10, 2, 1), dtype=float)
    resp_3d = dispatch_rpc(
        _rpc_request(
            "fuzzy.fit_anfis",
            {
                "X": X.tolist(),
                "y": y_3d.tolist(),
                "n_mfs": 2,
                "max_epochs": 2,
            },
        )
    )
    _validate_rpc_response_schema(resp_3d)
    assert resp_3d["status"] == "failure"
    assert resp_3d["error"]["code"] == "DIMENSION_MISMATCH"

    resp_bad_mf = dispatch_rpc(
        _rpc_request(
            "fuzzy.fit_anfis",
            {
                "X": X.tolist(),
                "y": np.zeros((10,), dtype=float).tolist(),
                "mf_type": 123,
                "max_epochs": 2,
            },
        )
    )
    _validate_rpc_response_schema(resp_bad_mf)
    assert resp_bad_mf["status"] == "failure"
    assert resp_bad_mf["error"]["code"] == "VALIDATION_ERROR"

