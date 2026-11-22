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
