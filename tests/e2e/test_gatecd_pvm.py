"""G-0D actual UI downloads with actuator clipping and a dynamic controller."""

import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pathview
import pytest
from pathsim import Connection
from pathsim.blocks import Scope
from pathview.converter import generate_python, load_registry, sanitize_name
from scipy.integrate import solve_ivp

from control_lab.core import StateSpace, DynamicController, array_to_tensor
from control_lab.io import load_ctrlab
from scripts.audit_pvm_official import DURATION, STEP, ERROR_LIMIT
from scripts.browser_harness import browser_harness, EVIDENCE
from scripts.gatecd_browser import mount_ui, wait_committed


@pytest.fixture(scope="module")
def registry():
    assert version("pathview") == "0.21.0" and version("pathsim") == "0.31.0"
    return load_registry(Path(pathview.__file__).parent / "data/registry.json")


def apply_plant_and_state(page, plant, x0):
    page.locator("#lqr-plant-json").fill(json.dumps(plant.to_dict()))
    page.locator("#btn-apply-plant").click()
    page.locator("#lqr-weights-json").fill(json.dumps({"x0": array_to_tensor(np.array(x0))}))
    page.locator("#btn-apply-weights").click()
    actual = page.evaluate("() => app.shell.getLqrWorkspace().getPlant()")
    assert actual["matrices"] == plant.to_dict()["matrices"]


def download_pvm(page, path):
    page.locator("#btn-export-pvm").click()
    with page.expect_download() as event:
        page.locator("#export-modal-download").click()
    assert event.value.suggested_filename.endswith(".pvm")
    event.value.save_as(path)
    page.locator("#export-modal-close").click()
    return path.read_bytes()


def roundtrip_export_options(harness, page, archive_path, project_id):
    """Reopen the real downloaded native ZIP and inspect its configuration in both readers."""
    expected = page.evaluate("() => app.shell.getPvmExportOptions()")
    assert expected is not None
    selected = page.locator("#pvm-controller-kind").input_value()
    page.locator("#btn-export-ctrlab").click()
    with page.expect_download() as event:
        page.locator("#export-modal-download").click()
    event.value.save_as(archive_path)
    page.locator("#export-modal-close").click()
    raw = archive_path.read_bytes()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / archive_path.name).write_bytes(raw)
    native = load_ctrlab(raw)
    assert native.status in ("success", "warning"), native.error
    assert native.data["experiments"][0]["parameters"]["pvm_export_options"] == expected
    mount_ui(harness, project_id)
    page.locator("#ctrlab-file-input").set_input_files(str(archive_path))
    wait_committed(page)
    actual = page.evaluate("() => app.shell.getPvmExportOptions()")
    assert actual == expected
    assert page.locator("#pvm-controller-kind").input_value() == selected
    return {
        "ctrlab_sha256": hashlib.sha256(raw).hexdigest(),
        "options_preserved": True,
        "controller_kind": selected,
    }


def audit_download(raw, case, registry):
    """Execute the official conversion of only this test's known-input UI download."""
    model = json.loads(raw)
    nodes = {node["id"]: node for node in model["graph"]["nodes"]}
    for node in nodes.values():
        assert set(node["params"]) <= set(registry["blocks"][node["type"]]["params"])
    source = generate_python(model, registry, source_name="actual-ui-download.pvm")
    ns = {"__name__": "f9_known_input_ui_download"}
    exec(compile(source, "<F9 controlled design downloaded by UI>", "exec"), ns)
    sim = ns["sim"]
    # The official converter coalesces fan-out into one Connection with several targets.
    # Expand every transfer and compare the complete directed, port-indexed topology.
    block_ids = {id(ns[sanitize_name(node["name"])]): node_id for node_id, node in nodes.items()}
    actual_edges = set()
    for connection in sim.connections:
        for target in connection.targets:
            for source_port, target_port in zip(
                connection.source._get_output_indices(), target._get_input_indices(), strict=True
            ):
                actual_edges.add(
                    (
                        block_ids[id(connection.source.block)],
                        source_port,
                        block_ids[id(target.block)],
                        target_port,
                    )
                )
    expected_edges = {
        (
            edge["sourceNodeId"],
            edge["sourcePortIndex"],
            edge["targetNodeId"],
            edge["targetPortIndex"],
        )
        for edge in model["graph"]["connections"]
    }
    assert actual_edges == expected_edges
    plant = ns[sanitize_name(nodes["plant_ss"]["name"])]
    output = ns[sanitize_name(nodes["scope_y"]["name"])]
    inputs = Scope()
    sim.add_block(inputs)
    for edge in model["graph"]["connections"]:
        if edge["targetNodeId"] == "plant_ss":
            origin = ns[sanitize_name(nodes[edge["sourceNodeId"]]["name"])]
            sim.add_connection(
                Connection(origin[edge["sourcePortIndex"]], inputs[edge["targetPortIndex"]])
            )
    sim.dt = STEP
    sim.run(duration=DURATION, adaptive=False)
    times, actual_y = output.read()
    input_times, actual_u = inputs.read()
    np.testing.assert_array_equal(times, input_times)
    A, B, C, D = (case[k] for k in ("A", "B", "C", "D"))
    n = A.shape[0]

    def signals(state):
        x = state[:n]
        if "K" in case:
            command = case["sign"] * case["K"] @ x + np.ones(B.shape[1])
            u = np.clip(command, case["u_min"], case["u_max"])
        else:
            z = state[n:]
            # r=1, output feedback, with the original nonzero Dp and Dc.
            u = np.linalg.solve(
                np.eye(B.shape[1]) - case["sign"] * case["Dc"] @ D,
                np.ones(B.shape[1]) + case["sign"] * (case["Cc"] @ z + case["Dc"] @ C @ x),
            )
        return u, C @ x + D @ u

    def rhs(t, state):
        u, y = signals(state)
        dx = A @ state[:n] + B @ u
        return np.r_[dx, case["Ac"] @ state[n:] + case["Bc"] @ y] if "Ac" in case else dx

    initial = np.r_[case["x0"], case.get("z0", np.empty(0))]
    solution = solve_ivp(
        rhs, (0, DURATION), initial, dense_output=True, rtol=1e-11, atol=1e-12, max_step=STEP
    )
    assert solution.success
    expected_state = solution.sol(times)
    expected = [signals(expected_state[:, i]) for i in range(len(times))]
    expected_u = np.column_stack([u for u, y in expected])
    expected_y = np.column_stack([y for u, y in expected])
    np.testing.assert_allclose(actual_u, expected_u, atol=ERROR_LIMIT, rtol=0)
    np.testing.assert_allclose(actual_y, expected_y, atol=ERROR_LIMIT, rtol=0)
    final_error = float(np.max(abs(plant.engine.state - expected_state[:n, -1])))
    assert final_error <= ERROR_LIMIT
    controller_error = None
    if "Ac" in case:
        controller = ns[sanitize_name(nodes["ctrl_dynamic"]["name"])]
        controller_error = float(np.max(abs(controller.engine.state - expected_state[n:, -1])))
        assert controller_error <= ERROR_LIMIT
    if "K" in case:
        assert any(node["type"] == "Clip" for node in nodes.values())
        assert np.max(abs(actual_u)) <= max(abs(case["u_min"]), abs(case["u_max"])) + 1e-12
        assert np.any(np.isclose(actual_u, case["u_min"], atol=1e-8))
    return dict(
        samples=len(times),
        max_u_error=float(np.max(abs(actual_u - expected_u))),
        max_y_error=float(np.max(abs(actual_y - expected_y))),
        max_plant_final_error=final_error,
        max_controller_final_error=controller_error,
        error_limit=ERROR_LIMIT,
        pvm_sha256=hashlib.sha256(raw).hexdigest(),
        connections=len(model["graph"]["connections"]),
    )


def test_download_saturated_lqr_matches_official_pathsim(browser_harness, registry, tmp_path):
    page = mount_ui(browser_harness, "gatecd-saturated")
    A = np.array([[0.0, 1.0], [0.0, 0.0]])
    B = np.array([[0.0], [1.0]])
    C = np.array([[1.0, 0.2]])
    D = np.array([[0.1]])
    plant = StateSpace(A, B, C, D, id="saturated-ui-plant", revision=1)
    x0 = np.array([2.0, 0.0])
    apply_plant_and_state(page, plant, x0)
    page.locator('[data-action="commit-lqr"]').click()
    wait_committed(page)
    snapshot = page.evaluate("() => app.shell.getLqrWorkspace().getCommittedSnapshot()")
    K = np.array(snapshot["K"]["data"]).reshape(snapshot["K"]["shape"])
    page.locator("#pvm-export-options summary").click()
    page.locator("#pvm-saturation-enabled").check()
    page.locator("#pvm-u-min").fill("-0.25")
    page.locator("#pvm-u-min").press("Tab")
    page.locator("#pvm-u-max").fill("0.25")
    page.locator("#pvm-u-max").press("Tab")
    raw = download_pvm(page, tmp_path / "saturated.pvm")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "gatecd-saturated.pvm").write_bytes(raw)
    case = dict(A=A, B=B, C=C, D=D, K=K, sign=-1, x0=x0, u_min=-0.25, u_max=0.25)
    result = audit_download(raw, case, registry)
    result["roundtrip"] = roundtrip_export_options(
        browser_harness, page, tmp_path / "saturated.ctrlab", "gatecd-saturated"
    )
    reopened = download_pvm(page, tmp_path / "saturated-reopened.pvm")
    result["reopened_pvm"] = audit_download(reopened, case, registry)
    browser_harness.record("gatecd-download-saturation", result)


def test_download_dynamic_without_lqr_matches_official_pathsim(browser_harness, registry, tmp_path):
    page = mount_ui(browser_harness, "gatecd-dynamic")
    A = np.array([[-1.2, 0.3], [-0.4, -2.5]])
    B = np.array([[1.0], [0.5]])
    C = np.array([[1.5, -0.5]])
    D = np.array([[0.4]])
    Ac = np.array([[-3.0]])
    Bc = np.array([[1.0]])
    Cc = np.array([[1.2]])
    Dc = np.array([[0.3]])
    x0 = np.array([0.5, -0.3])
    z0 = np.array([-0.8])
    plant = StateSpace(A, B, C, D, id="dynamic-ui-plant", revision=1)
    controller = DynamicController(
        Ac,
        Bc,
        Cc,
        Dc,
        feedback_sign="negative",
        ports={
            "inputs": [{"name": "y", "role": "y", "size": 1}],
            "outputs": [{"name": "u", "role": "u", "size": 1}],
        },
        interconnection_scheme="output_feedback",
        initial_state=z0,
        id="dynamic-ui-controller",
        revision=1,
    )
    apply_plant_and_state(page, plant, x0)
    assert page.evaluate("() => app.shell.getLqrWorkspace().getCommittedSnapshot()") is None
    page.locator("#pvm-export-options summary").click()
    page.locator("#pvm-controller-kind").select_option("dynamic")
    page.locator("#pvm-dynamic-controller-json").fill(json.dumps(controller.to_dict()))
    page.locator("#pvm-dynamic-controller-json").press("Tab")
    page.locator("#pvm-controller-kind").select_option("lqr")
    page.locator("#pvm-controller-kind").select_option("dynamic")
    assert (
        json.loads(page.locator("#pvm-dynamic-controller-json").input_value())
        == controller.to_dict()
    )
    raw = download_pvm(page, tmp_path / "dynamic.pvm")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "gatecd-dynamic.pvm").write_bytes(raw)
    assert page.evaluate("() => app.shell.getLqrWorkspace().getCommittedSnapshot()") is None
    case = dict(A=A, B=B, C=C, D=D, Ac=Ac, Bc=Bc, Cc=Cc, Dc=Dc, sign=-1, x0=x0, z0=z0)
    result = audit_download(raw, case, registry)
    # The native ZIP workspace is LQR. After demonstrating standalone dynamic PVM,
    # confirm LQR to persist/reopen this workspace's dynamic export configuration.
    page.locator('[data-action="commit-lqr"]').click()
    wait_committed(page)
    result["roundtrip"] = roundtrip_export_options(
        browser_harness, page, tmp_path / "dynamic-options.ctrlab", "gatecd-dynamic"
    )
    reopened = download_pvm(page, tmp_path / "dynamic-reopened.pvm")
    result["reopened_pvm"] = audit_download(reopened, case, registry)
    browser_harness.record("gatecd-download-dynamic", result)
