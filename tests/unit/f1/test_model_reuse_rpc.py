"""R-03/R-06/R-27 reuse contract and independent recurrence/transfer checks."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core import (
    Dataset,
    IdentifiedModel,
    StateSpace,
    TransferFunction,
    dispatch,
    reuse_model,
)
from control_lab.identification import fit_arx, fit_subspace


def request(payload, *, options=None):
    return dict(
        api_version="1.0",
        request_id="reuse-test",
        project_id="project-a",
        project_revision=3,
        operation="core.reuse_model",
        payload=payload,
        options=options or {},
        timeout_policy={"hard_timeout_ms": 30000},
    )


def invoke(payload, *, store=None, options=None):
    response = dispatch(request(payload, options=options), store=store)
    schemas = Path(__file__).resolve().parents[3] / "contracts/schemas"
    registry = Registry()
    for file in schemas.glob("*.schema.json"):
        raw = json.loads(file.read_text())
        resource = Resource.from_contents(raw)
        registry = registry.with_resource(file.name, resource)
        if "$id" in raw:
            registry = registry.with_resource(raw["$id"], resource)
    Draft202012Validator(
        json.loads((schemas / "rpc_response.schema.json").read_text()), registry=registry
    ).validate(response)
    return response


def impulse_or_input(ss, inputs):
    x = np.zeros(ss.n_states)
    output = []
    for uk in inputs:
        output.append((ss.C @ x + ss.D @ np.atleast_1d(uk)).copy())
        x = ss.A @ x + ss.B @ np.atleast_1d(uk)
    return np.array(output)


def test_identified_arx_delay_reused_into_discrete_state_space_preserves_recurrence():
    rng = np.random.default_rng(8013)
    u = rng.normal(size=500)
    y = np.zeros_like(u)
    # Start the generator with zero prehistory, including its first delayed term.
    y[3] = 0.8 * u[0]
    for k in range(4, len(u)):
        y[k] = 0.55 * y[k - 1] + 0.8 * u[k - 3] - 0.2 * u[k - 4]
    ds = Dataset(
        np.arange(len(u)) * 0.2,
        u[:, None],
        y[:, None],
        dt=0.2,
        id="measured",
        revision=2,
        units={"time": "s", "inputs": ["V"], "outputs": ["m"]},
    )
    fitted = fit_arx(ds, na=1, nb=2, nk=3)
    assert fitted.status in ("success", "warning")
    identified = fitted.data["identified_model"]
    original = copy.deepcopy(identified)
    response = invoke({"model": identified, "target_kind": "StateSpace"})
    assert response["status"] in ("success", "warning"), response
    model = StateSpace.from_dict(response["result"]["model"])
    np.testing.assert_allclose(impulse_or_input(model, u)[:, 0], y, atol=2e-12, rtol=2e-12)
    for z in (1.1 + 0.7j, -0.4 + 1.3j):
        expected = (0.8 * z**-3 - 0.2 * z**-4) / (1 - 0.55 * z**-1)
        actual = (
            model.C @ np.linalg.solve(z * np.eye(model.n_states) - model.A, model.B) + model.D
        )[0, 0]
        np.testing.assert_allclose(actual, expected, atol=2e-12, rtol=2e-12)
    assert model.dt == ds.dt == response["result"]["dt"]
    lineage = model.provenance["model_reuse"]["source_metadata"]
    assert lineage["dataset_ref"] == {"id": "measured", "revision": 2}
    assert lineage["metrics"] == identified["metrics"]
    assert lineage["partitions"] == identified["partitions"]
    assert model.units["inputs"] == ["V"] and model.units["outputs"] == ["m"]
    assert model.id != identified["model"]["id"] and model.revision == 0
    assert original == identified


def test_subspace_identified_state_space_reuse_preserves_transfer_not_coordinates():
    rng = np.random.default_rng(9)
    u = rng.normal(size=500)
    plant = StateSpace([[0.8, 0.15], [0, 0.45]], [[1], [0.4]], [[1, -0.2]], [[0]], dt=0.125)
    y = impulse_or_input(plant, u)
    ds = Dataset(np.arange(len(u)) * 0.125, u[:, None], y, dt=0.125)
    fitted = fit_subspace(ds, order=2, horizon=8)
    assert fitted.status in ("success", "warning")
    identified = fitted.data["identified_model"]
    response = invoke({"model": identified, "target_kind": "StateSpace"})
    assert response["status"] == "success", response
    source = StateSpace.from_dict(identified["model"])
    reused = StateSpace.from_dict(response["result"]["model"])
    for z in (1 + 0.5j, -1 + 0.5j):
        H = lambda ss: ss.C @ np.linalg.solve(z * np.eye(ss.n_states) - ss.A, ss.B) + ss.D
        np.testing.assert_allclose(H(reused), H(source), rtol=0, atol=1e-14)
    assert source.id != reused.id and reused.dt == source.dt
    assert response["result"]["derivation"]["representation_changed"] is False


@pytest.mark.parametrize(
    "dt,variable,order,num,den",
    [
        (None, "s", "descending", [2], [1, 3]),
        (0.37, "z", "descending", [2], [1, -0.3]),
        (0.37, "z^-1", "ascending", [0, 0, 2], [1, -0.3]),
        (0.37, "z^-1", "descending", [2, 0, 0], [-0.3, 1]),
    ],
)
def test_transfer_function_realization_at_complex_points(dt, variable, order, num, den):
    source = TransferFunction(num, den, dt=dt, variable=variable, poly_order=order)
    response = invoke({"model": source.to_dict(), "target_kind": "StateSpace"})
    assert response["status"] in ("success", "warning"), response
    ss = StateSpace.from_dict(response["result"]["model"])
    for point in (0.8 + 0.9j, -0.7 + 1.1j):
        q = 1 / point if variable == "z^-1" else point
        poly = np.polynomial.polynomial.polyval if order == "ascending" else np.polyval
        expected = (
            poly(q, num) / poly(q, den) if order == "ascending" else poly(num, q) / poly(den, q)
        )
        actual = (ss.C @ np.linalg.solve(point * np.eye(ss.n_states) - ss.A, ss.B) + ss.D)[0, 0]
        np.testing.assert_allclose(actual, expected, rtol=1e-13, atol=1e-13)
    assert ss.dt == dt


def test_identity_content_lineage_and_immutability():
    source = StateSpace(
        [[-1]],
        [[2]],
        [[3]],
        [[4]],
        id="same",
        revision=5,
        created_at="2020-01-01T00:00:00Z",
        provenance={"source": "original"},
    )
    before = source.to_dict()
    a = reuse_model(source).data
    b = reuse_model(source.to_dict()).data
    assert a == b
    changed = source.evolve(A=[[-2]])
    assert reuse_model(changed).data["model_ref"] != a["model_ref"]
    illicit = StateSpace([[-2]], [[2]], [[3]], [[4]], id="same", revision=5)
    assert reuse_model(illicit).data["model_ref"] != a["model_ref"]
    assert a["identity_policy"] == "derived_new_identity_revision_zero"
    assert a["dimensions"] == {"n_states": 1, "n_inputs": 1, "n_outputs": 1}
    assert a["reuse_version"] == "1.0.0" and "created_at" not in a["model"]
    a["model"]["matrices"]["A"]["data"][0] = -100
    assert source.to_dict() == before


def test_native_tf_extraction_keeps_representation_and_new_identity():
    tf = TransferFunction([0, 0, 1], [1, -0.2], dt=0.25, variable="z^-1", poly_order="ascending")
    im = IdentifiedModel(tf, algorithm="arx", id="identified", revision=3)
    response = invoke({"model": im.to_dict()})
    assert response["status"] == "success"
    derived = TransferFunction.from_dict(response["result"]["model"])
    assert derived.variable == tf.variable and derived.poly_order == tf.poly_order
    assert derived.dt == tf.dt and derived.id != tf.id
    assert response["result"]["dimensions"]["n_states"] is None


def test_python_model_ref_exact_revision_identity_and_project_scope():
    source = TransferFunction([1], [1, 2], id="tf", revision=2)
    payload = {"model_ref": {"id": "tf", "revision": 2}, "target_kind": "StateSpace"}
    stores = [
        {"project-a": {"tf": source}},
        {("project-a", "tf", 2): source},
        lambda project, id, revision: source,
    ]
    for store in stores:
        snapshot = repr(store)
        result = invoke(payload, store=store)
        assert result["status"] == "success", result
        assert repr(store) == snapshot
    wrong = StateSpace([[-1]], [[1]], [[1]], [[0]], id="different", revision=2)
    for store in (
        None,
        {"project-a": {"tf": source.evolve()}},
        {"project-a": {"tf": wrong}},
        {"tf": source},
        {("tf", 2): source},
        {"project-b": {"tf": source}, "tf": source},
        {("project-b", "tf", 2): source, "tf": source},
    ):
        result = invoke(payload, store=store)
        assert result["status"] == "failure" and result["error"]["code"] == "VALIDATION_ERROR"
        assert result["result"] is None


@pytest.mark.parametrize(
    "extra", [{"dt": 0.1}, {"id": "overwrite"}, {"revision": 4}, {"method": "zoh"}]
)
def test_unknown_payload_cannot_change_time_domain_or_identity(extra):
    source = TransferFunction([1], [1, 2]).to_dict()
    result = invoke({"model": source, **extra})
    assert result["status"] == "failure" and result["error"]["code"] == "VALIDATION_ERROR"


def test_options_ambiguity_invalid_nested_and_improper_fail_typed():
    source = TransferFunction([1], [1, 2]).to_dict()
    cases = [
        ({}, None),
        ({"model": source, "model_ref": {"id": "x", "revision": 0}}, None),
        ({"model": source}, {"dt": 0.1}),
        ({"model": source, "target_kind": "TransferFunction"}, None),
        ({"model": IdentifiedModel({"kind": "unknown"}, algorithm="x").to_dict()}, None),
        ({"model": TransferFunction([1, 0], [1]).to_dict(), "target_kind": "StateSpace"}, None),
    ]
    for payload, options in cases:
        result = invoke(payload, options=options)
        assert result["status"] == "failure" and result["result"] is None, result
        assert result["error"]["code"] in ("VALIDATION_ERROR", "UNSUPPORTED_MODEL")


def test_capabilities_advertise_operation():
    req = request({})
    req["operation"] = "core.capabilities"
    assert "core.reuse_model" in dispatch(req)["result"]["supported_operations"]
