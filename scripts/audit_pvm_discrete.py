"""Independent F9 clock assay against official PathView/PathSim.

Only models freshly constructed from the constants below are converted and
executed. Expected samples come from explicit synchronous recurrences, not
ControlLab's PVM compiler, adapter callbacks, or its internal simulator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_lab.core import DynamicController, StateFeedbackController, StateSpace
from control_lab.io.pvm import make_pvm
from pathview.converter import generate_python, load_registry, sanitize_name
import pathview
from pathsim import Connection
from pathsim.blocks import Scope

ERROR_LIMIT = 1e-10
CLOCK_TIME_LIMIT = 1e-10
STEPS = 24


def cases():
    for sign in (-1, 1):
        yield dict(
            name="scalar_negative" if sign < 0 else "scalar_positive",
            A=np.array([[0.8]]),
            B=np.array([[0.2]]),
            C=np.array([[1.0]]),
            D=np.zeros((1, 1)),
            K=np.array([[0.5]]),
            N=np.ones((1, 1)),
            r=np.array([0.3]),
            x0=np.array([1.0]),
            sign=sign,
            T=0.1 if sign < 0 else 0.037,
        )
    for special in ("rk4", "adaptive"):
        yield dict(
            name="scalar_" + special,
            A=np.array([[0.8]]),
            B=np.array([[0.2]]),
            C=np.array([[1.0]]),
            D=np.zeros((1, 1)),
            K=np.array([[0.5]]),
            N=np.ones((1, 1)),
            r=np.array([0.3]),
            x0=np.array([1.0]),
            sign=-1,
            T=0.1,
            solver="RK4" if special == "rk4" else "RKCK54",
            adaptive=special == "adaptive",
        )
    for saturated in (False, True):
        yield dict(
            name="mimo_saturated" if saturated else "mimo_rectangular",
            A=np.array([[0.7, 0.13], [-0.08, 0.6]]),
            B=np.array([[0.2, 0.04], [0.03, 0.18]]),
            C=np.array([[1.0, -0.3]]),
            D=np.array([[0.1, -0.05]]),
            K=np.array([[0.4, -0.1], [0.2, 0.5]]),
            N=np.array([[1.0], [-0.5]]),
            r=np.array([0.25]),
            x0=np.array([1.2, -0.7]),
            sign=-1,
            T=0.05,
            saturation={"enabled": True, "u_min": [-0.12, -0.08], "u_max": [0.12, 0.08]}
            if saturated
            else None,
        )
    yield dict(
        name="open_loop",
        A=np.array([[0.65, 0.1], [0.0, 0.8]]),
        B=np.array([[0.2], [0.1]]),
        C=np.eye(2),
        D=np.array([[0.1], [0.0]]),
        r=np.array([0.2]),
        x0=np.array([-0.4, 0.6]),
        T=0.07,
    )
    for scheme, order, sign, zero in [
        ("output_feedback", "y", -1, False),
        ("output_feedback", "y", 1, False),
        ("error_feedback", "e", -1, False),
        ("two_dof", "yr", -1, False),
        ("two_dof", "ry", -1, False),
        ("output_feedback", "y", -1, True),
    ]:
        case = dict(
            name=(
                "dynamic_zero_state"
                if zero
                else f"dynamic_{scheme}_{order}_{'negative' if sign < 0 else 'positive'}"
            ),
            A=np.array([[0.7, 0.08], [-0.06, 0.75]]),
            B=np.array([[0.18], [0.09]]),
            C=np.array([[1.1, -0.2]]),
            D=np.array([[0.12]]),
            Ac=np.empty((0, 0)) if zero else np.array([[0.6, 0.1], [-0.07, 0.5]]),
            Cc=np.empty((1, 0)) if zero else np.array([[0.3, -0.12]]),
            z0=np.empty(0) if zero else np.array([-0.35, 0.22]),
            r=np.array([0.17]),
            x0=np.array([0.8, -0.45]),
            sign=sign,
            scheme=scheme,
            order=order,
            T=0.125 if scheme == "two_dof" else 0.03,
        )
        case["By"] = np.empty((0, 1)) if zero else np.array([[0.15], [-0.08]])
        case["Dy"] = np.array([[0.11]])
        if scheme == "two_dof":
            case["Br"] = np.array([[0.08], [0.12]])
            case["Dr"] = np.array([[0.7]])
        yield case


def construct(case):
    T = case["T"]
    plant = StateSpace(
        case["A"], case["B"], case["C"], case["D"], dt=T, id="f9_clock_plant", revision=1
    )
    if "K" in case:
        controller = StateFeedbackController(
            case["K"],
            reference_map=case["N"],
            feedback_sign="negative" if case["sign"] < 0 else "positive",
            dt=T,
            id="f9_clock_controller",
            revision=1,
        )
    elif "Ac" in case:
        if case["order"] == "yr":
            Bc, Dc = np.hstack([case["By"], case["Br"]]), np.hstack([case["Dy"], case["Dr"]])
            inputs = [{"name": "y", "role": "y", "size": 1}, {"name": "r", "role": "r", "size": 1}]
        elif case["order"] == "ry":
            Bc, Dc = np.hstack([case["Br"], case["By"]]), np.hstack([case["Dr"], case["Dy"]])
            inputs = [{"name": "r", "role": "r", "size": 1}, {"name": "y", "role": "y", "size": 1}]
        else:
            Bc, Dc = case["By"], case["Dy"]
            inputs = [
                {
                    "name": "e" if case["order"] == "e" else "y",
                    "role": "error" if case["order"] == "e" else "y",
                    "size": 1,
                }
            ]
        controller = DynamicController(
            case["Ac"],
            Bc,
            case["Cc"],
            Dc,
            feedback_sign="negative" if case["sign"] < 0 else "positive",
            dt=T,
            initial_state=case["z0"],
            ports={"inputs": inputs, "outputs": [{"name": "u", "role": "u", "size": 1}]},
            interconnection_scheme=case["scheme"],
            id="f9_clock_controller",
            revision=1,
        )
    else:
        controller = None
    scenario = {
        "initial_state": case["x0"],
        "reference": {"type": "constant", "value": case["r"]},
        "duration": str(STEPS * T),
        "dt": str(T),
        "atol": "1e-12",
        "rtol": "1e-12",
        "ftol": "1e-12",
    }
    if "solver" in case:
        scenario["solver"] = case["solver"]
    if "adaptive" in case:
        scenario["adaptive"] = case["adaptive"]
    if case.get("saturation"):
        scenario["saturation"] = case["saturation"]
    return make_pvm(plant, controller, scenario=scenario)


def recurrence(case):
    """Calculate u[k], y[k], x[k+1], z[k+1] from the SAME old states."""
    A, B, C, D, r = [case[k] for k in ("A", "B", "C", "D", "r")]
    x, z = case["x0"].copy(), case.get("z0", np.empty(0)).copy()
    history = {k: [] for k in ("x", "z", "u", "y")}
    for _ in range(STEPS + 1):
        if "K" in case:
            u = case["sign"] * case["K"] @ x + case["N"] @ r
            if case.get("saturation"):
                u = np.clip(u, case["saturation"]["u_min"], case["saturation"]["u_max"])
        elif "Ac" in case:
            s, Dy, Cc = case["sign"], case["Dy"], case["Cc"]
            if case["scheme"] == "output_feedback":
                rhs = r + s * (Cc @ z + Dy @ C @ x)
            elif case["scheme"] == "error_feedback":
                rhs = Cc @ z + Dy @ (r + s * C @ x)
            else:
                rhs = Cc @ z + s * Dy @ C @ x + case["Dr"] @ r
            u = np.linalg.solve(np.eye(B.shape[1]) - s * Dy @ D, rhs)
        else:
            u = r.copy()
        y = C @ x + D @ u
        for k, value in (("x", x), ("z", z), ("u", u), ("y", y)):
            history[k].append(value.copy())
        if "Ac" in case:
            if case["scheme"] == "output_feedback":
                next_z = case["Ac"] @ z + case["By"] @ y
            elif case["scheme"] == "error_feedback":
                next_z = case["Ac"] @ z + case["By"] @ (r + case["sign"] * y)
            else:
                next_z = case["Ac"] @ z + case["By"] @ (case["sign"] * y) + case["Br"] @ r
        else:
            next_z = z
        x, z = A @ x + B @ u, next_z
    return {k: np.array(values) for k, values in history.items()}


def run_case(case, model, registry, out, divisor, reverse):
    graph = model["graph"]
    if reverse:
        model = json.loads(json.dumps(model))
        model["graph"]["nodes"].reverse()
        model["graph"]["connections"].reverse()
    source = generate_python(model, registry, source_name=case["name"] + ".pvm")
    ns = {"__name__": "f9_fresh_generated_clock_case"}
    exec(compile(source, "<F9 trusted generated discrete graph>", "exec"), ns)
    sim = ns["sim"]
    sim.dt = case["T"] / divisor
    # Observe all actual clock registers and applied plant inputs without altering
    # the exported equations. Scope is an official passive recording block.
    memory_node = next(n for n in graph["nodes"] if n["type"] == "SampleHold")
    memory = ns[sanitize_name(memory_node["name"])]
    plant_node = next(n for n in graph["nodes"] if n["id"] == "plant_ss")
    plant = ns[sanitize_name(plant_node["name"])]
    nstate = len(case["x0"]) + len(case.get("z0", []))
    monitor = Scope()
    sim.add_block(monitor)
    layout = memory_node["controlLab"]["state_layout"]
    covered = []
    initial = np.empty(nstate)
    expected_by_node = {"plant_ss": (case["x0"], "x")}
    if len(case.get("z0", [])):
        expected_by_node["ctrl_dynamic"] = (case["z0"], "z")
    for entry in layout:
        init, _ = expected_by_node[entry["node_id"]]
        assert entry["size"] == len(init)
        start, stop = entry["offset"], entry["offset"] + entry["size"]
        covered.extend(range(start, stop))
        initial[start:stop] = init
    assert sorted(covered) == list(range(nstate))
    for i in range(nstate):
        sim.add_connection(Connection(memory[i], monitor[i]))
    p, m = len(case["C"]), case["B"].shape[1]
    # Fan-out from actual graph outputs adds only passive observation channels.
    for connection in graph["connections"]:
        if connection["targetNodeId"] == "scope_y":
            source_node = next(n for n in graph["nodes"] if n["id"] == connection["sourceNodeId"])
            source_block = ns[sanitize_name(source_node["name"])]
            sim.add_connection(
                Connection(
                    source_block[connection["sourcePortIndex"]],
                    monitor[nstate + connection["targetPortIndex"]],
                )
            )
    for i in range(m):
        echo = next(
            port["index"] for port in plant_node["outputs"] if port.get("name") == f"input_echo{i}"
        )
        sim.add_connection(Connection(plant[echo], monitor[nstate + p + i]))
    sim.run(duration=STEPS * case["T"], adaptive=case.get("adaptive", False))
    times, monitored = monitor.read()
    q, actual_y, actual_u = (
        monitored[:nstate],
        monitored[nstate : nstate + p],
        monitored[nstate + p :],
    )
    assert times[0] == 0 and abs(times[-1] - STEPS * case["T"]) < 1e-10
    if case.get("adaptive"):
        # Event times accumulate floating-point roundoff. Classify only points
        # within the same explicit time-grid tolerance used below as kT; do
        # not relax any state/output/input tolerance at a discontinuity.
        positions = times / case["T"]
        nearest = np.rint(positions)
        on_clock = np.abs(times - nearest * case["T"]) <= CLOCK_TIME_LIMIT
        indices = np.where(on_clock, nearest, np.floor(positions)).astype(int)
        for k in range(STEPS + 1):
            assert np.min(np.abs(times - k * case["T"])) < 1e-10
    else:
        tick = np.rint(times / (case["T"] / divisor)).astype(int)
        assert np.max(np.abs(times - tick * (case["T"] / divisor))) < 1e-10
        indices = tick // divisor
    expected = recurrence(case)
    actual_state = q.T + initial
    expected_state = np.empty((len(indices), nstate))
    for entry in layout:
        _, key = expected_by_node[entry["node_id"]]
        expected_state[:, entry["offset"] : entry["offset"] + entry["size"]] = expected[key][
            indices
        ]
    expected_y = expected["y"][indices]
    expected_u = expected["u"][indices]
    errors = {
        "y": float(np.max(np.abs(actual_y.T - expected_y))),
        "u": float(np.max(np.abs(actual_u.T - expected_u))),
        "all_states": float(np.max(np.abs(actual_state - expected_state))),
    }
    suffix = f"div{divisor}" + ("_reversed" if reverse else "")
    np.savetxt(
        out / f"{case['name']}_{suffix}.csv",
        np.c_[times, actual_y.T, expected_y, actual_u.T, expected_u, actual_state, expected_state],
        delimiter=",",
        header="t,actual_y...,reference_y...,actual_u...,reference_u...,actual_states...,reference_states...",
        comments="",
    )
    assert len(times) >= STEPS + 1
    return {
        "case": case["name"],
        "step_divisor": divisor,
        "solver": case.get("solver", "RKCK54"),
        "adaptive": case.get("adaptive", False),
        "graph_order_reversed": reverse,
        "samples": len(times),
        "max_abs_errors": errors,
        "error_limit": ERROR_LIMIT,
        "clock_boundary_time_tolerance": CLOCK_TIME_LIMIT,
        "initial_state_preserved": bool(np.max(np.abs(actual_state[0] - initial)) <= ERROR_LIMIT),
        "zero_order_hold_checked": divisor > 1,
        "passed": all(e <= ERROR_LIMIT for e in errors.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/audits/pvm-discrete-clock")
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    assert version("pathview") == "0.21.0" and version("pathsim") == "0.31.0"
    package = Path(pathview.__file__).parent
    registry = load_registry(package / "data/registry.json")
    source_hashes = {}
    for relative, expected in {
        "converter.py": "9993b6247434f712cd7fede6117f127c5988541e",
        "buses.py": "29a1953ab486205cbbaa4014800c7e57c120f0ee",
    }.items():
        b = (package / relative).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()
        assert actual == expected
        source_hashes[relative] = {"git_blob_sha1": actual, "sha256": hashlib.sha256(b).hexdigest()}
    logging.getLogger("pathsim").setLevel(logging.ERROR)
    results = []
    for case in cases():
        try:
            model = construct(case)
            assert sum(n["type"] == "SampleHold" for n in model["graph"]["nodes"]) == 1
            assert not any(n["type"] == "DiscreteStateSpace" for n in model["graph"]["nodes"])
            for node in model["graph"]["nodes"]:
                entry = registry["blocks"][node["type"]]
                assert set(node["params"]) <= set(entry["params"])
            (out / (case["name"] + ".pvm")).write_text(json.dumps(model, indent=2) + "\n")
            (out / (case["name"] + ".py.txt")).write_text(
                generate_python(model, registry, source_name=case["name"] + ".pvm")
            )
            np.savetxt(
                out / (case["name"] + "_reference.csv"),
                np.c_[
                    np.arange(STEPS + 1) * case["T"],
                    recurrence(case)["x"],
                    recurrence(case)["z"],
                    recurrence(case)["u"],
                    recurrence(case)["y"],
                ],
                delimiter=",",
                header="t,x...,z...,u...,y...",
                comments="",
            )
            for divisor, reverse in [(1, False), (4, False), (4, True)]:
                result = run_case(case, model, registry, out, divisor, reverse)
                results.append(result)
                print(json.dumps(result), flush=True)
        except Exception as exc:
            result = {
                "case": case["name"],
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            results.append(result)
            print(json.dumps(result), flush=True)
    report = {
        "document_id": "CL-DIR-001",
        "work_package": "WP-AUDIT-FIX-F1-PVM-DISCRETE-CLOCK",
        "source_base_commit": "53e31974e4d56b73712629cf849de3e93bf3c537",
        "versions": {m: version(m) for m in ["pathview", "pathsim", "numpy", "scipy"]},
        "official_sources": source_hashes,
        "only_fresh_trusted_generated_code_executed": True,
        "oracle": "Independent synchronous recurrence and algebraic-loop elimination; all states before simultaneous update",
        "steps_per_case": STEPS,
        "error_limit": ERROR_LIMIT,
        "all_passed": all(r["passed"] for r in results),
        "cases": results,
        "source_sha256": {
            str(p): hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in [
                Path("control_lab/io/pvm.py"),
                Path("control_lab/io/pvm_official.py"),
                Path("control_lab/io/pvm_discrete.py"),
            ]
        },
        "assay_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (out / "discrete-assay.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["all_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
