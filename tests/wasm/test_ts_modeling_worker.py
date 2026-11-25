"""F9 independent T-TSMOD-07 transport oracle against the product Worker."""

import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core.rpc import dispatch
from control_lab.core.serialization import restore_model
from control_lab.fuzzy.ts_bridge import evaluate_ts_premise_weights
from scripts.browser_harness import DIST, BrowserHarness, ReleaseHandler
import scripts.browser_harness as real_browser

browser_harness = real_browser.browser_harness


ROOT = Path(__file__).resolve().parents[2]
MODEL_SCHEMA = "ts_state_space.schema.json"
RESPONSE_SCHEMA = "rpc_response.schema.json"
LIMIT = 1e-10


@pytest.fixture(scope="module")
def ts_schemas():
    schemas = {
        file.name: json.loads(file.read_text())
        for file in (ROOT / "contracts" / "schemas").glob("*.json")
    }
    registry = Registry().with_resources(
        (document["$id"], Resource.from_contents(document)) for document in schemas.values()
    )
    return {
        name: Draft202012Validator(schemas[name], registry=registry)
        for name in (MODEL_SCHEMA, RESPONSE_SCHEMA)
    }


def context(name, project="f9-ts-derive", revision=1):
    return {
        "request_id": name,
        "project_id": project,
        "project_revision": revision,
        "timeout_policy": {"hard_timeout_ms": 30000},
    }


def rpc(operation, payload, ctx):
    return {
        **ctx,
        "api_version": "1.0",
        "operation": operation,
        "options": {},
        "payload": payload,
    }


def ready(response, schema):
    schema.validate(response)
    assert response["status"] in {"success", "warning"}, response
    assert response["provenance"]["lib_versions"], response
    return response["result"]


def check_proxies(stats):
    counts = stats["pyproxy"]
    assert counts["activeProxies"] == 0, stats
    assert counts["totalCreated"] == counts["totalDestroyed"], stats


def plant_spec(sector):
    variable = "z" if sector else "x"
    payload = {
        "state_bounds": {"x1": [-1, 1], "x2": [-1, 1]},
        "A_expr": [
            [f"-3 + 0.25 * {variable}1 + 0.5 * {variable}2", 0.125],
            [f"0.1 * {variable}2", -2],
        ],
        "B_expr": [[1], [f"0.5 + 0.1 * {variable}2"]],
        "C_expr": [[1, 0]],
        "D_expr": [[0]],
        "n_val_points": 64,
    }
    if sector:
        payload["premises"] = [
            {"name": "z1", "expression": "x1"},
            {"name": "z2", "expression": "x2"},
        ]
    else:
        payload["grid_points"] = [5, 5]
    return payload


def reconstruction_error(model_dto):
    model = restore_model(model_dto)
    a_vertices = np.asarray([v["A"] for v in model.vertices])
    b_vertices = np.asarray([v["B"] for v in model.vertices])
    error = 0.0
    for x1, x2 in [(-1, -1), (-0.23, 0.71), (0.42, -0.17), (0.95, 1)]:
        result = evaluate_ts_premise_weights(model, {"x1": x1, "x2": x2})
        assert result.status == "success", result.error
        h = np.asarray(result.data["weights"])
        assert np.min(h) >= -LIMIT
        assert np.sum(h) == pytest.approx(1.0, abs=LIMIT)
        expected_a = np.array([[-3 + 0.25 * x1 + 0.5 * x2, 0.125], [0.1 * x2, -2]])
        expected_b = np.array([[1], [0.5 + 0.1 * x2]])
        error = max(
            error,
            float(np.max(np.abs(np.tensordot(h, a_vertices, axes=1) - expected_a))),
            float(np.max(np.abs(np.tensordot(h, b_vertices, axes=1) - expected_b))),
        )
    return error


@pytest.mark.parametrize(
    ("method", "operation", "representation", "mesh"),
    [
        ("deriveTsSector", "sector", "sector_nonlinearity", None),
        ("deriveTsTpmt", "tpmt", "tpmt_interpolated", None),
        ("deriveTsFemt", "femt", "femt_simplicial", "kuhn_delaunay"),
        ("deriveTsFemt", "femt", "femt_simplicial", "delaunay"),
    ],
)
def test_typed_ts_derivation_reconstructs_analytic_plant(
    browser_harness, ts_schemas, method, operation, representation, mesh
):
    payload = plant_spec(operation == "sector")
    if mesh:
        payload["mesh_kind"] = mesh
    ctx = context(f"derive-{mesh or operation}")
    actual = browser_harness.page.evaluate(
        """async ({method, ctx, payload}) => {
        const progress = [];
        const unsubscribe = app.client.subscribeTsModelingProgress(e => progress.push(e));
        try {
            const response = await app.client[method](ctx, payload);
            const stats = await app.client.getWorkerStats();
            return {response, progress, stats, revision: app.client.getCommittedRevision(ctx.project_id)};
        } finally { unsubscribe(); }
        }""",
        {"method": method, "ctx": ctx, "payload": payload},
    )
    schema = ts_schemas[RESPONSE_SCHEMA]
    result = ready(actual["response"], schema)
    native = ready(dispatch(rpc(f"fuzzy.derive_ts_{operation}", payload, ctx)), schema)
    model = result["ts_state_space"]
    ts_schemas[MODEL_SCHEMA].validate(model)
    assert model["membership_spec"]["representation_kind"] == representation
    assert (
        model["provenance"]["ts_derivation"]["method"]
        == native["ts_state_space"]["provenance"]["ts_derivation"]["method"]
    )
    assert actual["response"]["request_id"] == ctx["request_id"]
    assert actual["response"]["project_revision"] == ctx["project_revision"]
    stages = [event["progress"]["stage"] for event in actual["progress"]]
    assert stages == ["validating", "computing", "completed"], actual
    assert all(event["request_id"] == ctx["request_id"] for event in actual["progress"])
    elapsed = [event["progress"]["elapsed_ms"] for event in actual["progress"]]
    assert elapsed == sorted(elapsed) and elapsed[0] >= 0
    check_proxies(actual["stats"])
    assert actual["revision"] < ctx["project_revision"]
    error = reconstruction_error(model)
    native_error = reconstruction_error(native["ts_state_space"])
    assert error <= LIMIT and native_error <= LIMIT
    package = ready(
        browser_harness.rpc(
            rpc(
                "io.export_ctrlab",
                {"project": {"models": [model]}},
                context(f"pack-{mesh or operation}"),
            )
        ),
        schema,
    )
    restored = ready(
        browser_harness.rpc(
            rpc(
                "io.import_ctrlab",
                {"bytes_base64": package["bytes_base64"]},
                context(f"restore-{mesh or operation}"),
            )
        ),
        schema,
    )
    assert restored["models"] == [model]
    pathsim = ready(
        browser_harness.rpc(
            rpc(
                "io.export_pathsim_script",
                {"plant": restored["models"][0]},
                context(f"pathsim-{mesh or operation}"),
            )
        ),
        schema,
    )
    assert pathsim["code_executed"] is False
    assert pathsim["requires_explicit_user_execution"] is True
    assert "def default_h_fn(" in pathsim["script"]
    compile(pathsim["script"], "<passive PathSim export>", "exec")
    browser_harness.record(
        f"ts-modeling-{mesh or operation}",
        {
            "worker_analytic_error": error,
            "cpython_analytic_error": native_error,
            "state_space_representation": representation,
            "progress": actual["progress"],
            "pyproxy": actual["stats"]["pyproxy"],
        },
    )


def test_typed_ts_analysis_and_passive_export(browser_harness, ts_schemas):
    schema = ts_schemas[RESPONSE_SCHEMA]
    payload = plant_spec(sector=True)
    actual = browser_harness.page.evaluate(
        """async ({payload, analysis, derivation, python, matlab}) => {
        const analyzed = await app.client.analyzeSectorPremises(analysis, {
            state_bounds: payload.state_bounds, premises: payload.premises
        });
        const derived = await app.client.deriveTsSector(derivation, payload);
        const model = derived.result.ts_state_space;
        const exported = await app.client.exportTsDerivationScript(
            python, {model, language: 'python'}
        );
        await app.client.registerObject(matlab.project_id, model.id, model.revision, model);
        const viaReference = await app.client.exportTsDerivationScript(
            matlab, {model_ref: {id: model.id, revision: model.revision}, language: 'matlab'}
        );
        return {analyzed, exported, viaReference, stats: await app.client.getWorkerStats()};
        }""",
        {
            "payload": payload,
            "analysis": context("analyze"),
            "derivation": context("derive-for-export"),
            "python": context("export-python"),
            "matlab": context("export-matlab"),
        },
    )
    premises = ready(actual["analyzed"], schema)["premises"]
    assert [(p["name"], p["min"], p["max"]) for p in premises] == [("z1", -1, 1), ("z2", -1, 1)]
    for response, extension in (("exported", ".py"), ("viaReference", ".m")):
        exported = ready(actual[response], schema)
        assert exported["code_executed"] is False
        assert exported["requires_explicit_user_execution"] is True
        assert exported["filename"].endswith(extension)
        assert exported["script"]
    compile(actual["exported"]["result"]["script"], "<passive offline export>", "exec")
    check_proxies(actual["stats"])


def test_ts_worker_memory_limit_precedes_compute(browser_harness, ts_schemas):
    tests = [
        ("deriveTsTpmt", "tpmt", {"grid_points": [501, 501]}),
        ("deriveTsFemt", "femt", {"grid_points": [225, 225], "mesh_kind": "delaunay"}),
    ]
    for method, operation, limit_args in tests:
        payload = {**plant_spec(sector=False), **limit_args}
        ctx = context(f"limit-{operation}")
        actual = browser_harness.page.evaluate(
            """async ({method, ctx, payload}) => {
            const progress = [];
            const unsubscribe = app.client.subscribeTsModelingProgress(e => progress.push(e.progress.stage));
            try {
                const response = await app.client[method](ctx, payload);
                return {response, progress, stats: await app.client.getWorkerStats()};
            } finally { unsubscribe(); }
            }""",
            {"method": method, "ctx": ctx, "payload": payload},
        )
        ts_schemas[RESPONSE_SCHEMA].validate(actual["response"])
        assert actual["response"]["status"] == "failure", actual
        assert actual["response"]["error"]["code"] == "RESOURCE_LIMIT", actual
        assert actual["response"]["error"]["next_step"], actual
        assert actual["progress"] == ["validating"], actual
        check_proxies(actual["stats"])
        browser_harness.record(f"ts-modeling-limit-{operation}", actual)


def test_ts_export_checks_recipe_limits_for_inline_and_reference(browser_harness, ts_schemas):
    actual = browser_harness.page.evaluate(
        """async ({ctx, payload}) => {
        const derived = await app.client.deriveTsFemt(ctx, payload);
        const model = structuredClone(derived.result.ts_state_space);
        model.provenance.ts_derivation.grid_points = [501, 501];
        await app.client.registerObject(ctx.project_id, model.id, model.revision, model);
        const inline = await app.client.exportTsDerivationScript(
            {...ctx, request_id:'limit-export-inline'}, {model, language:'python'}
        );
        const reference = await app.client.exportTsDerivationScript(
            {...ctx, request_id:'limit-export-ref'},
            {model_ref:{id:model.id, revision:model.revision}, language:'matlab'}
        );
        return {inline, reference, stats:await app.client.getWorkerStats()};
        }""",
        {"ctx": context("derive-for-recipe-limit"), "payload": plant_spec(sector=False)},
    )
    for source in ("inline", "reference"):
        response = actual[source]
        ts_schemas[RESPONSE_SCHEMA].validate(response)
        assert response["status"] == "failure", response
        assert response["error"]["code"] == "RESOURCE_LIMIT", response
        assert response["error"]["next_step"], response
    check_proxies(actual["stats"])
    browser_harness.record("ts-modeling-limit-export", actual)


class IsolatedReleaseHandler(ReleaseHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()


@pytest.fixture
def isolated_ts_browser(browser_harness):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(IsolatedReleaseHandler, directory=DIST))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    browser_context = browser_harness.page.context.browser.new_context()
    page = browser_context.new_page()
    page.set_default_timeout(120000)
    try:
        page.goto(origin + "/probe.html")
        page.evaluate(
            """async () => {
            const {mountControlLabApp} = await import('/app/main.js');
            const node = document.createElement('div'); document.body.append(node);
            globalThis.app = mountControlLabApp(node, {project_id: 'f9-ts-isolated'});
            globalThis.request = (revision, project) => ({
                api_version:'1.0', request_id:crypto.randomUUID(), project_id:project,
                project_revision:revision, operation:'statespace.design_lqr',
                payload:{A:[[0,1],[0,0]],B:[[0],[1]],Q:[[4,0],[0,5]],R:[[1]]},
                options:{method:'care'}, timeout_policy:{hard_timeout_ms:30000}
            });
            await app.client.init();
            }"""
        )
        yield BrowserHarness(page, origin, browser_harness.version)
    finally:
        browser_context.close()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("isolated", [False, True], ids=["pages", "cross-origin-isolated"])
def test_cancel_running_ts_discards_without_committing(browser_harness, request, isolated):
    browser = request.getfixturevalue("isolated_ts_browser") if isolated else browser_harness
    spec = {**plant_spec(sector=False), "grid_points": [301, 301]}
    result = browser.page.evaluate(
        """async ({spec, goodSpec}) => {
        const project = 'f9-ts-cancel';
        const before = await app.client.execute(request(3, project), {commitOnSuccess: true});
        const workerBefore = (await app.client.getWorkerStats()).worker_id;
        const committedBefore = app.client.getCommittedRevision(project);
        const ctx = {request_id:'cancel-ts', project_id:project, project_revision:4};
        let cancelRequested;
        const phases = [];
        let concurrent;
        const unsubscribe = app.client.subscribeTsModelingProgress(e => {
            if (e.request_id !== ctx.request_id) return;
            phases.push(e.progress.stage);
            if (e.progress.stage === 'computing') {
                if (crossOriginIsolated) {
                    concurrent = app.client.deriveTsFemt(
                        {...ctx, request_id:'ts-concurrent', project_id:'f9-ts-parallel'}, goodSpec
                    );
                }
                cancelRequested = app.client.cancel(ctx.request_id);
            }
        });
        try {
            const cancelled = await app.client.deriveTsFemt(ctx, spec, {commitOnSuccess: true});
            const signalled = await cancelRequested;
            const committedAfter = app.client.getCommittedRevision(project);
            const other = concurrent ? await concurrent : null;
            const healthy = await app.client.deriveTsFemt(
                {...ctx, request_id:'ts-after-cancel', project_revision:5}, goodSpec
            );
            return {before, committedBefore, committedAfter, cancelled, signalled,
                    phases, healthy, workerBefore, other, isolated: crossOriginIsolated,
                    stats:await app.client.getWorkerStats()};
        } finally { unsubscribe(); }
        }""",
        {"spec": spec, "goodSpec": plant_spec(sector=False)},
    )
    assert result["isolated"] is isolated
    assert result["before"]["status"] == "success"
    assert result["committedBefore"] == result["committedAfter"] == 3
    assert result["cancelled"]["status"] == "failure", result
    assert result["cancelled"]["error"]["code"] == "CANCELLED", result
    assert result["signalled"]
    assert result["phases"] == ["validating", "computing"]
    assert result["healthy"]["status"] in {"success", "warning"}, result["healthy"]
    check_proxies(result["stats"])
    if isolated:
        assert result["other"]["status"] in {"success", "warning"}, result
        assert result["workerBefore"] == result["stats"]["worker_id"], result
    browser.record(
        f"ts-modeling-cancel-{isolated}",
        {
            key: result[key]
            for key in (
                "committedBefore",
                "committedAfter",
                "cancelled",
                "signalled",
                "phases",
                "stats",
                "isolated",
                "workerBefore",
            )
        },
    )
