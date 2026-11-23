"""Testes unitários F1 para transporte zero-copy de buffers empacotados (`F_k_packed`, ADR-015)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

import control_lab.core.rpc as rpc_mod
from control_lab.core.rpc import (
    RPC_API_VERSION,
    _rehydrate_buffers,
    _validate_request_envelope,
    dispatch_rpc,
)


def _base_request(
    operation: str = "optimization.solve",
    payload: dict[str, Any] | None = None,
    *,
    request_id: str = "req-packed-001",
) -> dict[str, Any]:
    return {
        "api_version": RPC_API_VERSION,
        "request_id": request_id,
        "project_id": "proj-packed",
        "project_revision": 1,
        "operation": operation,
        "payload": payload if payload is not None else {},
        "options": {},
        "timeout_policy": {"hard_timeout_ms": 5000},
    }


def _packed_block_payload_and_buffers(
    *,
    vals_arr: np.ndarray | None = None,
    vals_dtype: str = "float64",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray]]:
    k_idx_arr = np.array([0, 1, 1], dtype=np.int32)
    rows_arr = np.array([0, 0, 1], dtype=np.int32)
    cols_arr = np.array([0, 1, 1], dtype=np.int32)
    if vals_arr is None:
        vals_arr = np.array([1.5, -0.25, 2.0], dtype=np.dtype(vals_dtype))
    f0_arr = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64)

    payload = {
        "problem": {
            "n_vars": 2,
            "c": {"shape": [2], "dtype": "float64", "order": "C", "data": [1.0, 1.0]},
            "blocks": [
                {
                    "name": "B0",
                    "F0": {
                        "shape": [2, 2],
                        "dtype": "float64",
                        "order": "C",
                        "buffer_ref": "buf_f0",
                    },
                    "F_k_packed": {
                        "num_vars": 2,
                        "k_idx": {
                            "shape": [len(k_idx_arr)],
                            "dtype": "int32",
                            "order": "C",
                            "buffer_ref": "buf_k_idx",
                        },
                        "rows": {
                            "shape": [len(rows_arr)],
                            "dtype": "int32",
                            "order": "C",
                            "buffer_ref": "buf_rows",
                        },
                        "cols": {
                            "shape": [len(cols_arr)],
                            "dtype": "int32",
                            "order": "C",
                            "buffer_ref": "buf_cols",
                        },
                        "vals": {
                            "shape": [len(vals_arr)],
                            "dtype": vals_dtype,
                            "order": "C",
                            "buffer_ref": "buf_vals",
                        },
                    },
                }
            ],
        }
    }
    buffers = {
        "buf_f0": memoryview(f0_arr),
        "buf_k_idx": memoryview(k_idx_arr),
        "buf_rows": memoryview(rows_arr),
        "buf_cols": memoryview(cols_arr),
        "buf_vals": memoryview(vals_arr),
    }
    originals = {
        "f0": f0_arr,
        "k_idx": k_idx_arr,
        "rows": rows_arr,
        "cols": cols_arr,
        "vals": vals_arr,
    }
    return payload, buffers, originals


def test_rehydrate_buffers_fk_packed_zero_copy_and_normal_tensor_unchanged() -> None:
    payload, buffers, originals = _packed_block_payload_and_buffers()

    rehydrated = _rehydrate_buffers(payload, buffers)
    block = rehydrated["problem"]["blocks"][0]
    packed = block["F_k_packed"]

    for field in ("k_idx", "rows", "cols"):
        arr = packed[field]
        assert isinstance(arr, np.ndarray)
        assert not isinstance(arr, list)
        assert arr.dtype == np.int32
        assert np.array_equal(arr, originals[field])
        assert np.shares_memory(arr, originals[field])

    vals = packed["vals"]
    assert isinstance(vals, np.ndarray)
    assert not isinstance(vals, list)
    assert vals.dtype == np.float64
    assert np.array_equal(vals, originals["vals"])
    assert np.shares_memory(vals, originals["vals"])
    assert packed["num_vars"] == 2

    # BufferTensorRef fora de F_k_packed permanece TensorDescriptor canônico com data: list
    f0_tensor = block["F0"]
    assert isinstance(f0_tensor, dict)
    assert f0_tensor["shape"] == [2, 2]
    assert f0_tensor["dtype"] == "float64"
    assert f0_tensor["order"] == "C"
    assert isinstance(f0_tensor["data"], list)
    assert f0_tensor["data"] == [1.0, 0.0, 0.0, 1.0]


@pytest.mark.parametrize("operation", ["optimization.solve", "optimization.verify"])
def test_dispatch_rpc_worker_envelope_buffers_fk_packed_zero_copy(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    payload, buffers, originals = _packed_block_payload_and_buffers()
    captured: dict[str, Any] = {}

    def _capture_handler(req: dict[str, Any], store: Any) -> dict[str, Any]:
        captured["payload"] = req["payload"]
        return rpc_mod._build_rpc_response(
            request_id=req["request_id"],
            project_id=req["project_id"],
            project_revision=req["project_revision"],
            status="success",
            result={"captured": True},
            assumptions={},
            diagnostics={},
            provenance=None,
            warnings=[],
            error=None,
            fallback_algorithm=operation,
        )

    monkeypatch.setitem(rpc_mod._DISPATCH_TABLE, operation, _capture_handler)

    worker_envelope = {
        "request": _base_request(operation=operation, payload={}),
        "payload": payload,
        "buffers": buffers,
    }
    resp = dispatch_rpc(worker_envelope)
    assert resp["status"] == "success"
    assert resp["result"] == {"captured": True}

    block = captured["payload"]["problem"]["blocks"][0]
    packed = block["F_k_packed"]
    for field in ("k_idx", "rows", "cols"):
        arr = packed[field]
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.int32
        assert np.array_equal(arr, originals[field])
        assert np.shares_memory(arr, originals[field])

    vals = packed["vals"]
    assert isinstance(vals, np.ndarray)
    assert vals.dtype == np.float64
    assert np.array_equal(vals, originals["vals"])
    assert np.shares_memory(vals, originals["vals"])

    # BufferTensorRef fora de F_k_packed permanece TensorDescriptor canônico com data: list
    f0_tensor = block["F0"]
    assert isinstance(f0_tensor, dict)
    assert isinstance(f0_tensor["data"], list)
    assert f0_tensor["data"] == [1.0, 0.0, 0.0, 1.0]


@pytest.mark.parametrize(
    ("bad_value", "vals_dtype"),
    [
        (np.nan, "float64"),
        (np.inf, "float64"),
        (-np.inf, "float64"),
        (np.nan, "float32"),
        (np.inf, "float32"),
    ],
)
def test_dispatch_rpc_fk_packed_non_finite_vals_rejected(
    bad_value: float,
    vals_dtype: str,
) -> None:
    bad_vals = np.array([1.0, bad_value, -2.0], dtype=np.dtype(vals_dtype))
    payload, buffers, _ = _packed_block_payload_and_buffers(
        vals_arr=bad_vals,
        vals_dtype=vals_dtype,
    )
    worker_envelope = {
        "request": _base_request(operation="optimization.solve", payload={}),
        "payload": payload,
        "buffers": buffers,
    }
    resp = dispatch_rpc(worker_envelope)
    assert resp["status"] == "failure"
    assert resp["error"] is not None
    assert resp["error"]["code"] == "VALIDATION_ERROR"


def test_dispatch_rpc_fk_packed_invalid_buffer_shapes_and_envelope_validation() -> None:
    payload, buffers, _ = _packed_block_payload_and_buffers()

    # 1. Buffer truncado (não múltiplo do itemsize int32) -> DIMENSION_MISMATCH
    bad_trunc = dict(buffers)
    bad_trunc["buf_k_idx"] = memoryview(bytearray(b"\x01\x02\x03"))
    resp_trunc = dispatch_rpc(
        {
            "request": _base_request(operation="optimization.solve", payload={}),
            "payload": payload,
            "buffers": bad_trunc,
        }
    )
    assert resp_trunc["status"] == "failure"
    assert resp_trunc["error"]["code"] == "DIMENSION_MISMATCH"

    # 2. Quantidade de elementos divergente do shape declarado -> DIMENSION_MISMATCH
    bad_count = dict(buffers)
    bad_count["buf_rows"] = memoryview(np.array([0, 1], dtype=np.int32))
    resp_count = dispatch_rpc(
        {
            "request": _base_request(operation="optimization.solve", payload={}),
            "payload": payload,
            "buffers": bad_count,
        }
    )
    assert resp_count["status"] == "failure"
    assert resp_count["error"]["code"] == "DIMENSION_MISMATCH"

    # 3. Worker envelope com buffers não-Mapping -> VALIDATION_ERROR
    resp_bad_bufs = dispatch_rpc(
        {
            "request": _base_request(operation="optimization.solve", payload={}),
            "payload": payload,
            "buffers": ["not", "a", "mapping"],
        }
    )
    assert resp_bad_bufs["status"] == "failure"
    assert resp_bad_bufs["error"]["code"] == "VALIDATION_ERROR"

    # 4. _validate_request_envelope aceita chave opcional buffers sem quebrar assinatura (2-tupla)
    validated, resolved_store = _validate_request_envelope(
        {
            "request": _base_request(operation="worker.ping", payload={}),
            "payload": {},
            "buffers": buffers,
        },
        None,
    )
    assert validated["operation"] == "worker.ping"
    assert resolved_store is None


def test_dispatch_rpc_worker_envelope_buffers_normal_tensor_end_to_end() -> None:
    q_arr = np.eye(2, dtype=np.float64)
    r_arr = np.array([[1.0]], dtype=np.float64)
    worker_envelope = {
        "request": _base_request(operation="statespace.design_lqr", payload={}),
        "payload": {
            "A": [[0.0, 1.0], [0.0, 0.0]],
            "B": [[0.0], [1.0]],
            "Q": {"shape": [2, 2], "dtype": "float64", "order": "C", "buffer_ref": "Q-buf"},
            "R": {"shape": [1, 1], "dtype": "float64", "order": "C", "buffer_ref": "R-buf"},
        },
        "buffers": {
            "Q-buf": memoryview(q_arr),
            "R-buf": memoryview(r_arr),
        },
    }
    resp = dispatch_rpc(worker_envelope)
    assert resp["status"] == "success"
    assert resp["result"] is not None
    assert "K" in resp["result"]


def test_rehydrate_buffers_fk_packed_empty_arrays() -> None:
    empty_i32 = np.array([], dtype=np.int32)
    empty_f64 = np.array([], dtype=np.float64)
    payload = {
        "F_k_packed": {
            "k_idx": {"shape": [0], "dtype": "int32", "order": "C", "buffer_ref": "k"},
            "rows": {"shape": [0], "dtype": "int32", "order": "C", "buffer_ref": "r"},
            "cols": {"shape": [0], "dtype": "int32", "order": "C", "buffer_ref": "c"},
            "vals": {"shape": [0], "dtype": "float64", "order": "C", "buffer_ref": "v"},
        }
    }
    out = _rehydrate_buffers(
        payload,
        {
            "k": memoryview(empty_i32),
            "r": memoryview(empty_i32),
            "c": memoryview(empty_i32),
            "v": memoryview(empty_f64),
        },
    )
    packed = out["F_k_packed"]
    for key in ("k_idx", "rows", "cols"):
        assert isinstance(packed[key], np.ndarray)
        assert packed[key].dtype == np.int32
        assert packed[key].shape == (0,)
    assert isinstance(packed["vals"], np.ndarray)
    assert packed["vals"].dtype == np.float64
    assert packed["vals"].shape == (0,)
