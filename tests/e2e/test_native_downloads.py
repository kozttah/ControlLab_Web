"""F9. Verify files captured from the download buttons in the shipped Pyodide app."""

import ast
import hashlib
import json
import re
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pathview
import pytest
from pathsim import Connection
from pathsim.blocks import Scope
from pathview.converter import generate_python, load_registry, sanitize_name
from scipy.integrate import solve_ivp

from control_lab.core import StateSpace, tensor_to_array
from control_lab.io import load_ctrlab
from scripts.audit_pvm_discrete import run_case as run_clock_assay
from scripts.audit_pvm_official import DURATION, ERROR_LIMIT, STEP

pytest_plugins = ("scripts.browser_harness",)

CASES = [
    ("identity-negative", [[1, 0], [0, 1]], "negative", None),
    ("partial-positive", [[1, 0.3]], "positive", None),
    ("clocked-negative", [[1, 0.3]], "negative", 0.05),
]


def mount(page, project_id):
    page.evaluate(
        """async project => {
        app.destroy();
        document.body.replaceChildren();
        const root = document.body.appendChild(document.createElement('div'));
        const {mountControlLabApp} = await import('/app/main.js');
        globalThis.app = mountControlLabApp(root, {project_id:project});
        await app.client.init();
    }""",
        project_id,
    )


def configure(page, outputs, sign, dt):
    a = [[-1, 0.2], [0, -2]] if dt is None else [[0.8, 0.1], [0, 0.7]]
    b = [[0.2], [1.0]]
    plant = StateSpace(
        a,
        b,
        outputs,
        [[0.05]] * len(outputs),
        dt=dt,
        id="download-plant",
        revision=1,
        units={"time": "s", "inputs": ["V"], "outputs": ["m"] * len(outputs)},
    )
    page.locator("#lqr-plant-json").fill(json.dumps(plant.to_dict()))
    page.locator("#btn-apply-plant").click()
    if sign == "positive":
        page.locator("#lqr-feedback-sign").select_option(sign)
    else:
        page.locator('[data-action="commit-lqr"]').click()
    page.wait_for_function("() => app.shell.getLqrWorkspace().getCommittedSnapshot() !== null")
    state = page.evaluate("""() => {
        const w=app.shell.getLqrWorkspace();
        return {plant:w.getPlant(),snapshot:w.getCommittedSnapshot(),weights:w.getWeights()};
    }""")
    assert state["plant"]["matrices"] == plant.to_dict()["matrices"]
    assert state["plant"]["dt"] == dt
    assert state["plant"]["id"] == plant.id
    assert state["snapshot"]["feedback_sign"] == sign
    return state


def download(page, extension, target):
    page.locator(f"#btn-export-{extension}").click()
    with page.expect_download() as event:
        page.locator("#export-modal-download").click()
    assert event.value.suggested_filename.endswith("." + extension)
    event.value.save_as(target)
    page.locator("#export-modal-close").click()
    return target.read_bytes()


@pytest.fixture(scope="module")
def registry():
    assert version("pathview") == "0.21.0"
    assert version("pathsim") == "0.31.0"
    return load_registry(Path(pathview.__file__).parent / "data/registry.json")


def continuous_assay(model, registry, case):
    """Run only the freshly produced, known-input graph. Observe x, u and y."""
    source = generate_python(model, registry, source_name="download.pvm")
    ns = {"__name__": "f9_known_input_download"}
    exec(compile(source, "<F9 trusted test design>", "exec"), ns)
    graph = model["graph"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    sim = ns["sim"]
    assert len(sim.connections) == len(graph["connections"])
    plant = nodes["plant_ss"]
    plant_block = ns[sanitize_name(plant["name"])]
    n = len(case["x0"])
    monitor = Scope()
    sim.add_block(monitor)
    for i in range(n):
        port = next(p["index"] for p in plant["outputs"] if p["name"] == f"x{i}")
        sim.add_connection(Connection(plant_block[port], monitor[i]))
    for edge in graph["connections"]:
        if edge["targetNodeId"] == "plant_ss":
            block = ns[sanitize_name(nodes[edge["sourceNodeId"]]["name"])]
            sim.add_connection(
                Connection(block[edge["sourcePortIndex"]], monitor[n + edge["targetPortIndex"]])
            )
    sim.dt = STEP
    sim.run(duration=DURATION, adaptive=False)
    times, xu = monitor.read()
    ty, y = ns[sanitize_name(nodes["scope_y"]["name"])].read()
    np.testing.assert_array_equal(times, ty)
    assert len(times) > 1 and times[0] == 0 and abs(times[-1] - DURATION) < STEP / 2
    A, B, C, D = (case[k] for k in ("A", "B", "C", "D"))
    # The LQR UI exports a unit input reference and no prefilter.
    gain = case["sign"] * case["K"]
    sol = solve_ivp(
        lambda t, x: A @ x + B @ (gain @ x + 1),
        (0, DURATION),
        case["x0"],
        dense_output=True,
        rtol=1e-11,
        atol=1e-12,
        max_step=STEP,
    )
    assert sol.success
    x = sol.sol(times)
    u = gain @ x + 1
    expected = np.vstack((x, u, C @ x + D @ u))
    actual = np.vstack((xu, y))
    np.testing.assert_allclose(actual, expected, atol=ERROR_LIMIT, rtol=0)
    return {"samples": len(times), "max_abs_error": float(np.max(abs(actual - expected)))}


@pytest.mark.parametrize("name,outputs,sign,dt", CASES, ids=[case[0] for case in CASES])
def test_download_and_reopen(browser_harness, registry, tmp_path, name, outputs, sign, dt):
    page = browser_harness.page
    mount(page, name)
    state = configure(page, outputs, sign, dt)
    archive = tmp_path / "design.ctrlab"
    zip_bytes = download(page, "ctrlab", archive)
    pvm_bytes = download(page, "pvm", tmp_path / "design.pvm")
    project = load_ctrlab(zip_bytes)
    assert project.status in {"success", "warning"}, project.error
    snap = state["snapshot"]
    manifest = project.data["manifest"]
    assert (
        manifest["project_id"] == name and manifest["project_revision"] == snap["project_revision"]
    )
    assert manifest["provenance"] == snap["provenance"] and project.diagnostics["hashes_verified"]
    plant = project.data["models"][0]
    for key in (
        "id",
        "revision",
        "units",
        "matrices",
        "dt",
        "state_names",
        "input_names",
        "output_names",
    ):
        assert plant[key] == state["plant"][key]
    ctrl = project.data["controllers"][0]
    assert ctrl["kind"] == "StateFeedbackController"
    assert ctrl["K"] == snap["K"] and ctrl["feedback_sign"] == sign
    case = {key: tensor_to_array(val) for key, val in plant["matrices"].items()}
    case.update(
        name=name,
        sign=-1 if sign == "negative" else 1,
        K=tensor_to_array(ctrl["K"]),
        x0=tensor_to_array(state["weights"]["x0"]).reshape(-1),
    )
    model = json.loads(pvm_bytes)
    if dt is None:
        result = continuous_assay(model, registry, case)
    else:
        case.update(T=dt, N=np.eye(1), r=np.ones(1))
        result = run_clock_assay(case, model, registry, tmp_path, divisor=4, reverse=False)
        assert result["passed"], result
    mount(page, name)
    assert page.evaluate("() => app.shell.getLqrWorkspace().getCommittedSnapshot()") is None
    page.locator("#ctrlab-file-input").set_input_files(str(archive))
    page.wait_for_function("() => app.shell.getLqrWorkspace().getCommittedSnapshot() !== null")
    reopened = page.evaluate("""() => {
        const w=app.shell.getLqrWorkspace();
        return {plant:w.getPlant(),snapshot:w.getCommittedSnapshot(),weights:w.getWeights()};
    }""")
    for key in ("K", "feedback_sign", "model_revision", "project_revision", "provenance"):
        assert reopened["snapshot"][key] == snap[key]
    assert reopened["weights"] == state["weights"]
    for key in ("matrices", "revision", "units", "dt"):
        assert reopened["plant"][key] == state["plant"][key]
    browser_harness.record(
        "download-" + name,
        {
            "pathsim": result,
            "ctrlab_sha256": hashlib.sha256(zip_bytes).hexdigest(),
            "pvm_sha256": hashlib.sha256(pvm_bytes).hexdigest(),
        },
    )


def test_project_metadata_preserves_converted_ast(browser_harness, registry, tmp_path):
    """Convert and parse both downloads; do not execute the metadata-variant program."""
    trees = []
    for project_id in ("baseline", 'F9\r\n“ação” "λ"'):
        mount(browser_harness.page, project_id)
        configure(browser_harness.page, [[1, 0.3]], "negative", None)
        raw = download(browser_harness.page, "pvm", tmp_path / "metadata.pvm")
        source = generate_python(json.loads(raw), registry, source_name="download.pvm")
        tree = ast.parse(source)
        # Only the converter's UTC timestamp in its module docstring varies by run.
        # Preserve every executable node and every other literal in the comparison.
        header = tree.body[0]
        assert isinstance(header, ast.Expr) and isinstance(header.value, ast.Constant)
        header.value.value, replacements = re.subn(
            r"(?m)^Generated by pvm2py on [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$",
            "Generated by pvm2py on <UTC>",
            header.value.value,
        )
        assert replacements == 1
        trees.append(ast.dump(tree, include_attributes=False))
    assert trees[0] == trees[1]
