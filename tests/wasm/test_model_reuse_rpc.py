"""F9 real Worker RPC: identification -> canonical reuse -> discrete LQR.

Model-reference rehydration in the JS store is outside this F1 WorkPackage.
The positive path sends canonical inline DTOs through the actual product RPC.
"""

import numpy as np
import pytest

from control_lab.core import Dataset
from control_lab.core.rpc import dispatch
from scripts.browser_harness import browser_harness as browser_harness


def rpc(operation, payload, *, options=None):
    return {
        "api_version": "1.0",
        "request_id": operation + "-f9-reuse",
        "project_id": "f9-model-reuse",
        "project_revision": 0,
        "operation": operation,
        "payload": payload,
        "options": options or {},
        "timeout_policy": {"hard_timeout_ms": 30000},
    }


def array(tensor):
    return np.asarray(tensor["data"]).reshape(tensor["shape"], order=tensor["order"])


def good(response):
    assert response["status"] in {"success", "warning"}, response
    return response["result"]


@pytest.mark.parametrize("method", ["arx_delay", "subspace"])
def test_identification_reuse_consumer_and_ref_limit_through_real_worker(browser_harness, method):
    rng = np.random.default_rng(721)
    u = rng.normal(size=(360, 1))
    if method == "arx_delay":
        y = np.zeros((len(u), 1))
        for k in range(1, len(u)):
            y[k] = 0.7 * y[k - 1] + (0.4 * u[k - 3] if k >= 3 else 0)
        operation = "identification.fit_arx"
        parameters = {"na": 1, "nb": 1, "nk": 3}
    else:
        A = np.array([[0.45, 0.1], [0.0, 0.7]])
        B = np.array([[1.0], [0.4]])
        C = np.array([[1.0, -0.2]])
        state = np.zeros(2)
        y = []
        for value in u:
            y.append(C @ state)
            state = A @ state + B @ value
        operation = "identification.fit_subspace"
        parameters = {"order": 2, "horizon": 8}
    dataset = Dataset(np.arange(len(u)) * 0.2, u, y, dt=0.2, id="wasm-reuse-data", revision=2)
    fit = good(browser_harness.rpc(rpc(operation, {"dataset": dataset.to_dict(), **parameters})))
    identified = fit["identified_model"]
    request = rpc("core.reuse_model", {"model": identified, "target_kind": "StateSpace"})
    result = good(browser_harness.rpc(request))
    native = good(dispatch(request))
    model = result["model"]
    assert model["dt"] == result["dt"] == 0.2
    assert model["id"] != identified["id"]
    assert result["model_ref"] == native["model_ref"]
    assert result["source_ref"] == native["source_ref"]
    assert result["identity_policy"] == "derived_new_identity_revision_zero"
    A_ss, B_ss, C_ss, D_ss = [array(model["matrices"][key]) for key in ("A", "B", "C", "D")]
    errors = []
    for point in (np.exp(0.1j), np.exp(0.8j), np.exp(2j)):
        actual = C_ss @ np.linalg.solve(point * np.eye(len(A_ss)) - A_ss, B_ss) + D_ss
        if method == "arx_delay":
            expected = np.array([[0.4 * point**-3 / (1 - 0.7 * point**-1)]])
        else:
            expected = C @ np.linalg.solve(point * np.eye(2) - A, B)
        error = float(np.max(np.abs(actual - expected)))
        errors.append(error)
        assert error < 2e-10
    design = good(browser_harness.rpc(rpc(
        "statespace.design_lqr",
        {"plant": model, "Q": np.eye(len(A_ss)).tolist(), "R": [[1.0]]},
        options={"method": "dare"},
    )))
    P, K = [array(design[key]) for key in ("P", "K")]
    terms = [A_ss.T @ P @ A_ss, -P, -A_ss.T @ P @ B_ss @ K, np.eye(len(A_ss))]
    residual = float(np.linalg.norm(sum(terms)) / (1 + sum(np.linalg.norm(term) for term in terms)))
    assert residual < 1e-10
    assert max(abs(np.linalg.eigvals(A_ss - B_ss @ K))) < 1
    # F1 does not silently register its DTO in the JS WorkerModelStore. A ref-only
    # reuse call with no Python store must fail honestly until the F7 follow-up.
    unregistered = browser_harness.rpc(rpc("core.reuse_model", {"model_ref": result["model_ref"]}))
    assert unregistered["status"] == "failure" and unregistered["error"]
    browser_harness.record("model-reuse-" + method, {
        "operation": "core.reuse_model", "transport": "real product Worker RPC",
        "source_kind": identified["kind"], "dt": result["dt"],
        "frequency_errors": errors, "independent_dare_residual": residual,
        "model_ref": result["model_ref"], "reference_without_store": unregistered["error"],
    })
