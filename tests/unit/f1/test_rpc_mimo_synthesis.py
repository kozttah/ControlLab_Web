"""Unit tests for MIMO synthesis RPC operations in control_lab.core.rpc."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core.models import StateSpace, TransferFunction
from control_lab.core.rpc import SUPPORTED_OPERATIONS, dispatch_rpc


def _make_2x2_mimo_plant() -> StateSpace:
    """Stable, coupled 2x2 MIMO continuous-time StateSpace plant."""
    A = np.array(
        [
            [-1.0, 0.2],
            [0.1, -2.0],
        ],
        dtype=np.float64,
    )
    B = np.array(
        [
            [1.0, 0.4],
            [0.3, 1.2],
        ],
        dtype=np.float64,
    )
    C = np.array(
        [
            [1.0, 0.1],
            [0.2, 1.0],
        ],
        dtype=np.float64,
    )
    D = np.zeros((2, 2), dtype=np.float64)
    return StateSpace(A=A, B=B, C=C, D=D, dt=None, id="mimo-plant", revision=1)


def _rpc_request(operation: str, payload: dict, *, options: dict | None = None) -> dict:
    return {
        "api_version": "1.0",
        "request_id": f"req-{operation}",
        "project_id": "proj-mimo",
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


def test_supported_operations_register_mimo_synthesis():
    for op in ("mimo.design_decoupler", "mimo.simulate_closed_loop", "mimo.design_hinf"):
        assert op in SUPPORTED_OPERATIONS

    cap_resp = dispatch_rpc(_rpc_request("core.capabilities", {}))
    assert cap_resp["status"] == "success"
    supported = cap_resp["result"]["supported_operations"]
    assert "mimo.design_decoupler" in supported
    assert "mimo.simulate_closed_loop" in supported
    assert "mimo.design_hinf" in supported


def test_rpc_mimo_design_decoupler_static_and_first_order():
    plant = _make_2x2_mimo_plant()

    for mode in ("static", "first_order"):
        req = _rpc_request(
            "mimo.design_decoupler",
            {
                "plant": plant.to_dict(),
                "omega_target": 1.0,
                "realization_mode": mode,
            },
        )
        resp = dispatch_rpc(req)
        _validate_rpc_response_schema(resp)

        assert resp["status"] == "success"
        assert resp["api_version"] == "1.0"
        assert "provenance" in resp and resp["provenance"]["algorithm"]
        assert resp["provenance"]["lib_versions"]

        result = resp["result"]
        assert result["realization_mode"] == mode
        assert "decoupler" in result
        assert "schema_version" in result["decoupler"]
        assert "decoupled_plant" in result
        assert "schema_version" in result["decoupled_plant"]
        assert result["kappa_after"] <= result["kappa_before"] + 1e-6

        serialized = json.dumps(resp)
        assert isinstance(serialized, str) and len(serialized) > 0


def test_rpc_mimo_design_decoupler_with_plant_ref():
    plant = _make_2x2_mimo_plant()
    store = {("proj-mimo", "mimo-plant", 1): plant.to_dict()}

    req = _rpc_request(
        "mimo.design_decoupler",
        {"plant_ref": {"id": "mimo-plant", "revision": 1}, "omega_target": 0.5},
    )
    resp = dispatch_rpc(req, store=store)
    _validate_rpc_response_schema(resp)

    assert resp["status"] == "success"
    assert resp["result"]["omega_target"] == 0.5
    assert json.dumps(resp)


def test_rpc_mimo_simulate_closed_loop_with_decoupler_and_gains():
    plant = _make_2x2_mimo_plant()

    dec_resp = dispatch_rpc(
        _rpc_request(
            "mimo.design_decoupler",
            {"plant": plant.to_dict(), "omega_target": 1.0, "realization_mode": "static"},
        )
    )
    assert dec_resp["status"] == "success"
    decoupler_dict = dec_resp["result"]["decoupler"]

    # Array controller_gains
    req_arr = _rpc_request(
        "mimo.simulate_closed_loop",
        {
            "plant": plant.to_dict(),
            "controller_gains": [1.0, 1.0],
            "decoupler": decoupler_dict,
            "feedback_sign": "negative",
            "t_final": 8.0,
            "n_points": 100,
        },
    )
    resp_arr = dispatch_rpc(req_arr)
    _validate_rpc_response_schema(resp_arr)

    assert resp_arr["status"] == "success"
    assert resp_arr["api_version"] == "1.0"
    assert "provenance" in resp_arr and resp_arr["provenance"]["algorithm"]
    res_arr = resp_arr["result"]
    assert res_arr["is_stable"] is True
    assert "closed_loop_system" in res_arr
    assert "schema_version" in res_arr["closed_loop_system"]
    assert res_arr["t"]["shape"] == [100]
    assert res_arr["step_responses"]["shape"] == [2, 100, 2]
    assert json.dumps(resp_arr)

    # Scalar controller_gains
    req_scalar = _rpc_request(
        "mimo.simulate_closed_loop",
        {
            "plant": plant.to_dict(),
            "controller_gains": 1.5,
            "t_final": 5.0,
            "n_points": 50,
        },
    )
    resp_scalar = dispatch_rpc(req_scalar)
    _validate_rpc_response_schema(resp_scalar)
    assert resp_scalar["status"] == "success"
    assert json.dumps(resp_scalar)


def test_rpc_mimo_design_hinf():
    plant = _make_2x2_mimo_plant()

    req = _rpc_request(
        "mimo.design_hinf",
        {
            "plant": plant.to_dict(),
            "w_s": {"dc_gain": 20.0, "wb": 0.5, "m_s": 2.0},
            "w_u": {"gain": 0.2},
            "w_t": {"wt": 10.0, "m_t": 2.0, "at": 0.05},
            "omega": np.logspace(-2, 2, 40).tolist(),
            "gamma_tol": 1e-2,
        },
    )
    resp = dispatch_rpc(req)
    _validate_rpc_response_schema(resp)

    assert resp["status"] == "success"
    assert resp["api_version"] == "1.0"
    assert "provenance" in resp and resp["provenance"]["algorithm"]
    assert resp["provenance"]["lib_versions"]

    result = resp["result"]
    assert result["is_stable"] is True
    assert result["gamma_achieved"] > 0.0
    assert "controller" in result
    assert "schema_version" in result["controller"]
    assert result["omega"]["shape"] == [40]
    assert result["sigma_S"]["shape"] == [40]
    assert result["sigma_T"]["shape"] == [40]
    assert json.dumps(resp)


def test_rpc_mimo_design_hinf_with_canonical_weight_model():
    plant = _make_2x2_mimo_plant()
    w_u_tf = TransferFunction(num=[0.2], den=[1.0], dt=None)

    req = _rpc_request(
        "mimo.design_hinf",
        {
            "plant": plant.to_dict(),
            "w_u": w_u_tf.to_dict(),
            "gamma_tol": 2e-2,
        },
    )
    resp = dispatch_rpc(req)
    _validate_rpc_response_schema(resp)

    assert resp["status"] == "success"
    assert "schema_version" in resp["result"]["controller"]
    assert json.dumps(resp)


def test_rpc_mimo_synthesis_validation_errors():
    plant = _make_2x2_mimo_plant()

    missing_plant = dispatch_rpc(_rpc_request("mimo.design_decoupler", {}))
    _validate_rpc_response_schema(missing_plant)
    assert missing_plant["status"] == "failure"
    assert missing_plant["error"]["code"] == "VALIDATION_ERROR"

    conflict_ctrl = dispatch_rpc(
        _rpc_request(
            "mimo.simulate_closed_loop",
            {
                "plant": plant.to_dict(),
                "controller": plant.to_dict(),
                "controller_gains": [1.0, 1.0],
            },
        )
    )
    _validate_rpc_response_schema(conflict_ctrl)
    assert conflict_ctrl["status"] == "failure"
    assert conflict_ctrl["error"]["code"] == "VALIDATION_ERROR"
