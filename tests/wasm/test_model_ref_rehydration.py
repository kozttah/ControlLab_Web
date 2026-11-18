"""F9 independent reference transport proofs through the real product Worker.

Expected transfer functions and Riccati residuals come from planted equations,
not from the reference resolver. Registration is always an explicit client action.
"""

from copy import deepcopy
import json

import numpy as np
import pytest

from control_lab.core import Dataset, StateSpace
from control_lab.core.rpc import dispatch
import scripts.browser_harness as real_browser

browser_harness = real_browser.browser_harness


def request(operation, payload, project, *, options=None, revision=0):
    return {
        "api_version": "1.0",
        "request_id": operation + "-f9-model-refs",
        "project_id": project,
        "project_revision": revision,
        "operation": operation,
        "payload": payload,
        "options": options or {},
        "timeout_policy": {"hard_timeout_ms": 30000},
    }


def good(response):
    assert response["status"] in {"success", "warning"}, response
    assert response["provenance"]["lib_versions"], response
    return response["result"]


def array(tensor):
    if "real" in tensor:
        values = np.asarray(tensor["real"]) + 1j * np.asarray(tensor["imag"])
    else:
        values = np.asarray(tensor["data"])
    return values.reshape(tensor["shape"], order=tensor.get("order", "C"))


def register(harness, project, dto, *, kind=None, key=None):
    return harness.page.evaluate(
        """async ({project,dto,kind,key}) =>
        app.client.registerObject(project,key ?? dto.id,dto.revision,dto,
          {kind:kind ?? dto.kind,persistToIndexedDB:true})""",
        {"project": project, "dto": dto, "kind": kind, "key": key},
    )


def stats(harness):
    result = harness.page.evaluate("() => app.client.getWorkerStats()")
    assert result["pyproxy"]["activeProxies"] == 0, result
    return result


def stored(harness, project, dto):
    return harness.page.evaluate(
        "({project,dto}) => app.client.getObject(project,dto.id,dto.revision)",
        {"project": project, "dto": dto},
    )


def datasets(method):
    datasets = []
    for part, length, seed in (("train", 360, 721), ("validation", 180, 722)):
        u = np.random.default_rng(seed).normal(size=(length, 1))
        if method == "arx_delay":
            y = np.zeros((length, 1))
            for k in range(1, length):
                y[k] = 0.7 * y[k - 1] + (0.4 * u[k - 3] if k >= 3 else 0)
        else:
            state, y = np.zeros(2), []
            for value in u:
                y.append(np.array([[1.0, -0.2]]) @ state)
                state = (
                    np.array([[0.45, 0.1], [0.0, 0.7]]) @ state + np.array([[1.0], [0.4]]) @ value
                )
        time = np.arange(length) * 0.2 + (100 if part == "validation" else 0)
        datasets.append(
            Dataset(time, u, y, dt=0.2, id=f"refs-{method}-{part}", revision=2).to_dict()
        )
    return datasets


@pytest.mark.parametrize("method", ["arx_delay", "subspace"])
def test_registered_dataset_model_reuse_and_registered_consumers(browser_harness, method):
    project = "f9-registered-" + method
    train, validation = datasets(method)
    register(browser_harness, project, train)
    register(browser_harness, project, validation)
    train_ref = {"id": train["id"], "revision": train["revision"]}
    validation_ref = {"id": validation["id"], "revision": validation["revision"]}
    operation = "identification.fit_arx" if method == "arx_delay" else "identification.fit_subspace"
    parameters = (
        {"na": 1, "nb": 1, "nk": 3} if method == "arx_delay" else {"order": 2, "horizon": 8}
    )
    before_fit = stats(browser_harness)["store"]["entry_count"]
    fitted = good(
        browser_harness.rpc(
            request(
                operation,
                {
                    "dataset_ref": train_ref,
                    "val_dataset_ref": validation_ref,
                    **parameters,
                },
                project,
            )
        )
    )
    identified = fitted["identified_model"]
    assert stats(browser_harness)["store"]["entry_count"] == before_fit
    assert stored(browser_harness, project, train) == train
    assert stored(browser_harness, project, validation) == validation
    identified["provenance"]["f9_inert_reference"] = {
        "dataset_ref": {"id": "not-registered-and-never-resolved", "revision": 77}
    }
    register(browser_harness, project, identified)
    identified_ref = {"id": identified["id"], "revision": identified["revision"]}
    before_validation = stats(browser_harness)["store"]["entry_count"]
    validated = good(
        browser_harness.rpc(
            request(
                "identification.validate_model",
                {
                    "model_ref": identified_ref,
                    "val_dataset_ref": validation_ref,
                    "train_dataset_ref": train_ref,
                },
                project,
            )
        )
    )
    assert validated["validation_metrics"], validated
    assert stats(browser_harness)["store"]["entry_count"] == before_validation
    before_reuse = stats(browser_harness)["store"]["entry_count"]
    result = good(
        browser_harness.rpc(
            request(
                "core.reuse_model",
                {
                    "model_ref": identified_ref,
                    "target_kind": "StateSpace",
                },
                project,
            )
        )
    )
    assert stats(browser_harness)["store"]["entry_count"] == before_reuse
    assert result["derivation"]["registration_required"] is True
    assert result["source_ref"] == identified_ref
    assert result["dt"] == 0.2 and result["model"]["dt"] == 0.2
    assert result["model"]["id"] != identified["id"] and result["model"]["revision"] == 0
    assert "not-registered-and-never-resolved" in json.dumps(result["model"]["provenance"])
    assert stored(browser_harness, project, identified) == identified
    native = good(
        dispatch(
            request(
                "core.reuse_model",
                {
                    "model": identified,
                    "target_kind": "StateSpace",
                },
                project,
            )
        )
    )
    assert result["model_ref"] == native["model_ref"]
    not_registered = browser_harness.rpc(
        request("core.reuse_model", {"model_ref": result["model_ref"]}, project)
    )
    assert not_registered["status"] == "failure" and not_registered["result"] is None
    register(browser_harness, project, result["model"])
    A, B, C, D = [array(result["model"]["matrices"][key]) for key in ("A", "B", "C", "D")]
    omega = [0.5, 2.0, 4.0]
    frequency = good(
        browser_harness.rpc(
            request(
                "frequency.eval_response",
                {
                    "model_ref": result["model_ref"],
                    "omega": omega,
                },
                project,
            )
        )
    )
    expected = []
    for w in omega:
        z = np.exp(1j * w * 0.2)
        if method == "arx_delay":
            expected.append(0.4 * z**-3 / (1 - 0.7 * z**-1))
        else:
            expected.append(
                (
                    np.array([[1.0, -0.2]])
                    @ np.linalg.solve(
                        z * np.eye(2) - np.array([[0.45, 0.1], [0.0, 0.7]]),
                        np.array([[1.0], [0.4]]),
                    )
                ).item()
            )
    response = array(frequency["response"])
    frequency_error = float(np.max(np.abs(response - expected)))
    assert frequency_error < 2e-10
    np.testing.assert_allclose(
        response,
        [
            (C @ np.linalg.solve(np.exp(1j * w * 0.2) * np.eye(len(A)) - A, B) + D).item()
            for w in omega
        ],
        rtol=0,
        atol=2e-10,
    )
    lqr_request = request(
        "statespace.design_lqr",
        {
            "plant_ref": result["model_ref"],
            "Q": {
                "shape": [len(A), len(A)],
                "dtype": "float64",
                "order": "C",
                "buffer_ref": "q-ref",
            },
            "R": {"shape": [1, 1], "dtype": "float64", "order": "C", "buffer_ref": "r-ref"},
        },
        project,
        options={"method": "dare", "return_binary_buffers": True},
    )
    binary = browser_harness.page.evaluate(
        """async ({request,n}) => {
      const q = new Float64Array(n*n); for(let i=0;i<n;i++) q[i*n+i]=1;
      const r = new Float64Array([1]);
      const response=await app.client.execute(request,{commitOnSuccess:true,buffers:{
        'q-ref':{shape:[n,n],dtype:'float64',order:'C',buffer:q.buffer},
        'r-ref':{shape:[1,1],dtype:'float64',order:'C',buffer:r.buffer}}});
      return {response,detached:[q.buffer.byteLength,r.buffer.byteLength]};
    }""",
        {"request": lqr_request, "n": len(A)},
    )
    assert binary["detached"] == [0, 0]
    design = good(binary["response"])
    P, K = [array(design[key]) for key in ("P", "K")]
    terms = [A.T @ P @ A, -P, -A.T @ P @ B @ K, np.eye(len(A))]
    residual = float(np.linalg.norm(sum(terms)) / (1 + sum(np.linalg.norm(term) for term in terms)))
    assert residual < 1e-10 and max(abs(np.linalg.eigvals(A - B @ K))) < 1
    recovery = None
    if method == "arx_delay":
        snapshot_before = browser_harness.page.evaluate(
            "project => app.client.exportProject(project)", project
        )
        worker_before = stats(browser_harness)["worker_id"]
        browser_harness.page.evaluate(
            "() => app.client.resetWorker('F9 reference snapshot recovery')"
        )
        worker_after = stats(browser_harness)["worker_id"]
        assert worker_after != worker_before
        snapshot_after = browser_harness.page.evaluate(
            "project => app.client.exportProject(project)", project
        )
        assert {k: v for k, v in snapshot_before.items() if k != "exported_at"} == {
            k: v for k, v in snapshot_after.items() if k != "exported_at"
        }
        recovered = good(
            browser_harness.rpc(
                request(
                    "core.reuse_model",
                    {
                        "model_ref": identified_ref,
                        "target_kind": "StateSpace",
                    },
                    project,
                    revision=1,
                )
            )
        )
        assert recovered["model_ref"] == result["model_ref"]
        recovered_fit = good(
            browser_harness.rpc(
                request(
                    operation,
                    {
                        "dataset_ref": train_ref,
                        "val_dataset_ref": validation_ref,
                        **parameters,
                    },
                    project,
                    revision=1,
                )
            )
        )
        assert recovered_fit["identified_model"]["model"]["dt"] == 0.2
        recovery = {
            "worker_before": worker_before,
            "worker_after": worker_after,
            "snapshots_equal": True,
        }
    final_stats = stats(browser_harness)
    browser_harness.record(
        "registered-model-refs-" + method,
        {
            "transport": "real product Worker RPC",
            "method": method,
            "dataset_refs": [train_ref, validation_ref],
            "identified_ref": identified_ref,
            "derived_ref": result["model_ref"],
            "frequency_error": frequency_error,
            "independent_dare_residual": residual,
            "registration_explicit": True,
            "binary_input_buffers_detached": binary["detached"],
            "binary_output_tensors_restored": ["P", "K"],
            "source_not_mutated": True,
            "recovery": recovery,
            "stats": final_stats,
        },
    )


def test_reference_isolation_types_revisions_and_ambiguity(browser_harness):
    project = "f9-reference-negative"
    plant = StateSpace(
        [[0.7]], [[0.4]], [[1.0]], [[0.0]], dt=0.2, id="same-model-id", revision=2
    ).to_dict()
    dataset = datasets("arx_delay")[0]
    register(browser_harness, project, plant)
    register(browser_harness, project, dataset)
    wrong_metadata = deepcopy(plant)
    wrong_metadata["id"] = "wrong-entry-kind"
    register(browser_harness, project, wrong_metadata, kind="Dataset")
    reference = {"id": plant["id"], "revision": 2}
    before = stats(browser_harness)["store"]["entry_count"]
    cases = [
        (
            "entry_kind_disagrees_with_dto",
            project,
            "core.reuse_model",
            {"model_ref": {"id": wrong_metadata["id"], "revision": 2}},
        ),
        ("cross_project", "other-project", "core.reuse_model", {"model_ref": reference}),
        (
            "missing_revision",
            project,
            "core.reuse_model",
            {"model_ref": {"id": plant["id"], "revision": 1}},
        ),
        (
            "wrong_kind_model",
            project,
            "core.reuse_model",
            {"model_ref": {"id": dataset["id"], "revision": 2}},
        ),
        (
            "wrong_kind_dataset",
            project,
            "identification.fit_arx",
            {"dataset_ref": reference, "na": 1, "nb": 1},
        ),
        ("inline_and_ref", project, "core.reuse_model", {"model": plant, "model_ref": reference}),
        (
            "null_inline_and_ref",
            project,
            "core.reuse_model",
            {"model": None, "model_ref": reference},
        ),
        (
            "ref_extra_project",
            project,
            "core.reuse_model",
            {"model_ref": {**reference, "project_id": project}},
        ),
        (
            "ref_fractional_revision",
            project,
            "core.reuse_model",
            {"model_ref": {"id": plant["id"], "revision": 1.5}},
        ),
        ("reference_string", project, "core.reuse_model", {"model_ref": "same-model-id"}),
        (
            "dataset_ambiguous",
            project,
            "identification.fit_arx",
            {"dataset": dataset, "dataset_ref": {"id": dataset["id"], "revision": 2}},
        ),
        (
            "validation_alias_ambiguous",
            project,
            "identification.validate_model",
            {
                "model": plant,
                "val_dataset": dataset,
                "dataset_ref": {"id": dataset["id"], "revision": 2},
            },
        ),
    ]
    results = []
    for label, target, operation, payload in cases:
        response = browser_harness.rpc(request(operation, payload, target))
        assert response["status"] == "failure" and response["result"] is None, (label, response)
        assert response["error"]["code"] in {"VALIDATION_ERROR", "UNSUPPORTED_MODEL"}, (
            label,
            response,
        )
        stats(browser_harness)
        results.append({"case": label, "error": response["error"]})
    assert stats(browser_harness)["store"]["entry_count"] == before
    # Explicit historical revision remains valid even after a newer revision exists.
    newer = deepcopy(plant)
    newer["revision"] = 3
    newer["matrices"]["A"]["data"] = [0.2]
    register(browser_harness, project, newer)
    old = good(browser_harness.rpc(request("core.reuse_model", {"model_ref": reference}, project)))
    assert array(old["model"]["matrices"]["A"])[0, 0] == 0.7
    assert old["source_ref"] == reference
    # Mismatched DTO identity under a legitimate key is never exposed to Python.
    impostor = deepcopy(plant)
    impostor["id"] = "dto-id-does-not-match-store-key"
    register(browser_harness, project, impostor, key="impostor-key")
    rejected = browser_harness.rpc(
        request("core.reuse_model", {"model_ref": {"id": "impostor-key", "revision": 2}}, project)
    )
    assert rejected["status"] == "failure" and rejected["result"] is None
    browser_harness.record(
        "registered-model-refs-negatives",
        {
            "transport": "real product Worker RPC",
            "cases": results,
            "historical_revision_exact": old["source_ref"],
            "impostor_rejected": rejected["error"],
            "stats": stats(browser_harness),
        },
    )
