"""F9 independent oracles for canonical reuse, delay, lineage and RPC isolation.

Expected transfer values and trajectories are derived from scalar equations or
planted state recurrences, never from the conversion routine under test.
"""

from copy import deepcopy

import numpy as np
import pytest

from control_lab.core import Dataset, StateSpace, TransferFunction, TSStateSpace
from control_lab.core.rpc import dispatch
from control_lab.identification import fit_arx, fit_subspace


def request(payload, *, options=None, project="reuse-f9", revision=0):
    return {
        "api_version": "1.0",
        "request_id": "reuse-independent",
        "project_id": project,
        "project_revision": revision,
        "operation": "core.reuse_model",
        "payload": payload,
        "options": options or {},
        "timeout_policy": {"hard_timeout_ms": 30000},
    }


def good(response):
    assert response["status"] in {"success", "warning"}, response
    assert response["error"] is None
    return response["result"]


def array(tensor):
    return np.asarray(tensor["data"]).reshape(tensor["shape"], order=tensor["order"])


def frequency(model, point):
    A, B, C, D = [array(model["matrices"][key]) for key in ("A", "B", "C", "D")]
    return C @ np.linalg.solve(point * np.eye(len(A)) - A, B) + D


def samples(model, inputs):
    A, B, C, D = [array(model["matrices"][key]) for key in ("A", "B", "C", "D")]
    state = np.zeros(len(A))
    output = []
    for value in np.asarray(inputs).reshape(-1, B.shape[1]):
        output.append(C @ state + D @ value)
        state = A @ state + B @ value
    return np.asarray(output)


def discrete_delay_source():
    return TransferFunction(
        [0, 0, 0, 0.4, -0.1], [1, -0.65, 0.12],
        variable="z^-1", poly_order="ascending", dt=0.2,
        id="delayed-transfer", revision=4,
        input_names=["force"], output_names=["position"],
        units={"input": "N", "output": "m"},
        provenance={"algorithm": "analytic_recurrence"},
    ).to_dict()


def test_f9_continuous_transfer_and_new_identity_are_reproducible():
    source = TransferFunction([2], [1, 3], id="ct-source", revision=7).to_dict()
    before = deepcopy(source)
    out = good(dispatch(request({"model": source, "target_kind": "StateSpace"})))
    again = good(dispatch(request({"model": source, "target_kind": "StateSpace"}, revision=17)))
    model = out["model"]
    assert model["dt"] is None and out["dt"] is None
    assert out["reuse_version"] == "1.0.0"
    assert model["id"] != source["id"] and model["revision"] == 0
    assert out["model_ref"] == {"id": model["id"], "revision": 0}
    assert again["model_ref"] == out["model_ref"]
    assert out["identity_policy"] == "derived_new_identity_revision_zero"
    assert out["dimensions"] == {"n_states": 1, "n_inputs": 1, "n_outputs": 1}
    assert out["derivation"]["time_domain_changed"] is False
    assert out["derivation"]["registration_required"] is True
    for point in (0.2j, 1.5j, 4 + 2j):
        np.testing.assert_allclose(frequency(model, point), [[2 / (point + 3)]], atol=1e-13)
    altered = deepcopy(source)
    altered["provenance"]["experiment"] = "another origin"
    assert good(dispatch(request({"model": altered, "target_kind": "StateSpace"})))["model_ref"] != out["model_ref"]
    altered = TransferFunction([3], [1, 3], id=source["id"], revision=7).to_dict()
    assert good(dispatch(request({"model": altered, "target_kind": "StateSpace"})))["model_ref"] != out["model_ref"]
    assert source == before


def test_f9_discrete_delay_is_preserved_by_impulse_recurrence():
    source = discrete_delay_source()
    out = good(dispatch(request({"model": source, "target_kind": "StateSpace"})))
    model = out["model"]
    assert out["dt"] == model["dt"] == 0.2
    assert model["input_names"] == source["input_names"]
    assert model["output_names"] == source["output_names"]
    assert model["units"] == source["units"]
    signal = np.r_[1.0, np.zeros(24)]
    expected = np.zeros(len(signal))
    for k in range(len(signal)):
        expected[k] = (
            (0.65 * expected[k - 1] if k >= 1 else 0)
            - (0.12 * expected[k - 2] if k >= 2 else 0)
            + (0.4 * signal[k - 3] if k >= 3 else 0)
            - (0.1 * signal[k - 4] if k >= 4 else 0)
        )
    actual = samples(model, signal)[:, 0]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-14)
    np.testing.assert_array_equal(actual[:3], [0, 0, 0])


def test_f9_arx_delay_identification_reuse_preserves_dataset_and_dynamics():
    u = np.random.default_rng(124).normal(size=400)
    y = np.zeros(len(u))
    for k in range(1, len(y)):
        y[k] = 0.7 * y[k - 1] + (0.4 * u[k - 3] if k >= 3 else 0)
    dataset = Dataset(np.arange(len(u)) * 0.1, u, y, dt=0.1, id="measured", revision=2)
    fitted = fit_arx(dataset=dataset, na=1, nb=1, nk=3)
    assert fitted.status in {"success", "warning"}
    identified = fitted.data["identified_model"]
    before = deepcopy(identified)
    out = good(dispatch(request({"model": identified, "target_kind": "StateSpace"})))
    assert out["source_ref"] == {"id": identified["id"], "revision": identified["revision"]}
    assert out["source_model_ref"] == {"id": identified["model"]["id"], "revision": identified["model"]["revision"]}
    assert out["dt"] == 0.1
    np.testing.assert_allclose(samples(out["model"], u)[:, 0], y, rtol=0, atol=2e-12)
    lineage = out["model"]["provenance"]
    # The dataset identity must be retained somewhere in the canonical lineage,
    # rather than discarded when the IdentifiedModel wrapper is removed.
    assert "measured" in str(lineage) and "ARX_QR_SVD" in str(lineage)
    assert identified == before


def test_f9_subspace_reuse_is_checked_by_transfer_not_state_coordinates():
    A = np.array([[0.45, 0.1], [0, 0.7]])
    B = np.array([[1], [0.4]])
    C = np.array([[1, -0.2]])
    u = np.random.default_rng(93).normal(size=(360, 1))
    state = np.zeros(2)
    y = []
    for value in u:
        y.append(C @ state)
        state = A @ state + B @ value
    dataset = Dataset(np.arange(len(u)) * 0.2, u, y, dt=0.2, id="subspace-data", revision=3)
    fitted = fit_subspace(dataset=dataset, order=2, horizon=8)
    assert fitted.status in {"success", "warning"}
    identified = fitted.data["identified_model"]
    native = good(dispatch(request({"model": identified})))
    ss = good(dispatch(request({"model": identified, "target_kind": "StateSpace"})))
    assert native["model"]["kind"] == ss["model"]["kind"] == "StateSpace"
    assert native["dt"] == ss["dt"] == 0.2
    for point in (np.exp(0.1j), np.exp(0.7j), np.exp(2.0j)):
        expected = C @ np.linalg.solve(point * np.eye(2) - A, B)
        np.testing.assert_allclose(frequency(ss["model"], point), expected, rtol=0, atol=2e-11)
        np.testing.assert_allclose(frequency(native["model"], point), expected, rtol=0, atol=2e-11)


def test_f9_mimo_realization_preserves_each_transfer_channel():
    source = TransferFunction(
        [[[1], [2]], [[0], [3]]],
        [[[1, 1], [1, 2]], [[1], [1, 3]]],
        id="mimo-source", revision=2,
    ).to_dict()
    out = good(dispatch(request({"model": source, "target_kind": "StateSpace"})))
    assert out["dimensions"]["n_inputs"] == out["dimensions"]["n_outputs"] == 2
    for point in (0.5j, 2j):
        expected = [[1 / (point + 1), 2 / (point + 2)], [0, 3 / (point + 3)]]
        np.testing.assert_allclose(frequency(out["model"], point), expected, rtol=0, atol=1e-13)


def test_f9_ts_native_preserves_uncertainty_and_cannot_be_silently_lti():
    source = TSStateSpace(
        [{"vertex_id": "one", "A": [[-1]], "B": [[1]], "C": [[1]], "D": [[0]]}],
        kind="polytopic_uncertain",
        membership_spec={"version": "1.0.0", "premise_variables": ["alpha"], "sum_to_one_domain": True},
        premise_availability={"mode": "unknown_uncertain", "measured_premises": [], "unmeasured_premises": ["alpha"]},
        domain={"bounds": {"alpha": [0, 1]}}, id="uncertain", revision=3,
    ).to_dict()
    out = good(dispatch(request({"model": source})))
    for key in ("kind", "dt", "vertices", "domain", "membership_spec", "premise_availability"):
        assert out["model"][key] == source[key]
    response = dispatch(request({"model": source, "target_kind": "StateSpace"}))
    assert response["status"] == "failure" and response["error"]["code"] == "UNSUPPORTED_MODEL"


@pytest.mark.parametrize("damage", ["dt", "id", "revision", "target", "both", "nan", "shape", "option"])
def test_f9_reuse_rejects_ambiguous_or_damaged_input(damage):
    source = discrete_delay_source()
    payload = {"model": source, "target_kind": "StateSpace"}
    options = {}
    if damage in {"dt", "id", "revision"}:
        payload[damage] = 99
    elif damage == "target":
        payload["target_kind"] = "continuous"
    elif damage == "both":
        payload["model_ref"] = {"id": source["id"], "revision": source["revision"]}
    elif damage == "nan":
        source["provenance"]["invalid"] = float("nan")
    elif damage == "shape":
        payload["model"] = StateSpace([[0.5]], [[1]], [[1]], [[0]], dt=0.1).to_dict()
        payload["model"]["matrices"]["B"]["shape"] = [2, 1]
    else:
        options["dt"] = None
    response = dispatch(request(payload, options=options))
    assert response["status"] == "failure" and response["error"], response
    assert not response.get("result"), response


def test_f9_reference_identity_revision_and_project_are_exact():
    source = discrete_delay_source()
    ref = {"id": source["id"], "revision": source["revision"]}
    source_key = ("reuse-f9", source["id"], source["revision"])
    store = {source_key: source}
    before = deepcopy(store)
    out = good(dispatch(request({"model_ref": ref}), store=store))
    assert out["source_ref"] == ref and store == before
    stale = {**ref, "revision": ref["revision"] - 1}
    assert dispatch(request({"model_ref": stale}), store=store)["status"] == "failure"
    assert dispatch(request({"model_ref": ref}, project="other"), store=store)["status"] == "failure"
    impostor = deepcopy(source)
    impostor["id"] = "wrong-object-with-same-revision"
    assert dispatch(request({"model_ref": ref}), store={source_key: impostor})["status"] == "failure"
    # An unscoped dictionary cannot prove the request's project identity.
    for flat in ({source["id"]: source}, {(source["id"], source["revision"]): source}):
        assert dispatch(request({"model_ref": ref}, project="other"), store=flat)["status"] == "failure"
    # A malformed mixed store must never fall back to the global entry.
    mixed = {"actual-owner": {source["id"]: source}, source["id"]: source}
    assert dispatch(request({"model_ref": ref}, project="other"), store=mixed)["status"] == "failure"
