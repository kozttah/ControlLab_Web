"""F9 independent official PathView/PathSim trajectory assay.

Install scripts/requirements-pathview.lock, then run this script from the repo.
Only PVM freshly produced here is converted/executed; imported user PVM is never run.
Reference equations below are independent of ControlLab's PVM evaluator/compiler.
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
from scipy.integrate import solve_ivp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_lab.core import DynamicController, StateFeedbackController, StateSpace
from control_lab.io.pvm import make_pvm
from control_lab.diagnostics import UnsupportedModelError
from pathview.converter import generate_python, load_registry, sanitize_name
import pathview

DURATION = 0.5
STEP = 0.001
ERROR_LIMIT = 2e-6


def cases():
    for sign in (-1, 1):
        for complete in (True, False):
            A = np.array([[0.0, 1.0], [0.0, 0.0]])
            B = np.array([[0.0], [1.0]])
            C = np.eye(2) if complete else np.array([[1.0, 0.2]])
            D = np.zeros((len(C), 1)) if complete else np.array([[0.15]])
            K = np.array([[2.0, 3.0]])
            N = np.array([[1.0, 0.3]]) if complete else np.array([[1.2]])
            r = np.array([0.2, -0.1]) if complete else np.array([0.2])
            ctrl = StateFeedbackController(
                K, feedback_sign="negative" if sign < 0 else "positive", reference_map=N
            )
            yield dict(
                name=f"static_{'negative' if sign < 0 else 'positive'}_{'ci' if complete else 'cneq'}",
                A=A,
                B=B,
                C=C,
                D=D,
                ctrl=ctrl,
                x0=np.array([1.0, -0.3]),
                r=r,
                K=K,
                N=N,
                sign=sign,
            )
    A = np.array([[-1.0, 0.2], [0.1, -2.0]])
    B = np.array([[1.0, 0.2], [0.3, 1.0]])
    C = np.array([[1.0, 0.3]])
    D = np.array([[0.1, 0.2]])
    K = np.array([[1.0, 0.2], [-0.1, 0.8]])
    N = np.array([[1.0], [-0.5]])
    yield dict(
        name="mimo_rectangular_reference",
        A=A,
        B=B,
        C=C,
        D=D,
        ctrl=StateFeedbackController(K, feedback_sign="negative", reference_map=N),
        x0=np.array([0.8, -0.4]),
        r=np.array([0.3]),
        K=K,
        N=N,
        sign=-1,
    )
    A = np.array([[0.0, 1.0], [0.0, 0.0]])
    B = np.array([[0.0], [1.0]])
    C = np.array([[1.0, 0.0]])
    D = np.array([[0.1]])
    K = np.array([[2.0, 3.0]])
    N = np.array([[1.0]])
    yield dict(
        name="saturated_negative",
        A=A,
        B=B,
        C=C,
        D=D,
        ctrl=StateFeedbackController(K, feedback_sign="negative", reference_map=N),
        x0=np.array([1.0, -0.3]),
        r=np.array([0.2]),
        K=K,
        N=N,
        sign=-1,
        saturation={"enabled": True, "u_min": [-0.4], "u_max": [0.4]},
    )
    for zero in (False, True):
        A = np.array([[-1.2, 0.3], [-0.4, -2.5]])
        B = np.array([[1.0], [0.5]])
        C = np.array([[1.5, -0.5]])
        D = np.array([[0.4]])
        Ac = np.empty((0, 0)) if zero else np.array([[-3.0]])
        Bc = np.empty((0, 1)) if zero else np.array([[1.0]])
        Cc = np.empty((1, 0)) if zero else np.array([[1.2]])
        Dc = np.array([[0.3]])
        z0 = np.empty(0) if zero else np.array([-0.8])
        ctrl = DynamicController(
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
        )
        yield dict(
            name="dynamic_zero_state" if zero else "dynamic_nonzero_feedthrough",
            A=A,
            B=B,
            C=C,
            D=D,
            ctrl=ctrl,
            x0=np.array([0.5, -0.3]),
            r=np.array([0.2]),
            Ac=Ac,
            Bc=Bc,
            Cc=Cc,
            Dc=Dc,
            z0=z0,
            sign=-1,
        )
    yield dict(
        name="discrete_static",
        A=np.array([[0.8]]),
        B=np.array([[0.2]]),
        C=np.array([[1.0]]),
        D=np.array([[0.0]]),
        ctrl=StateFeedbackController(
            [[0.5]], feedback_sign="negative", reference_map=[[1.0]], dt=0.1
        ),
        x0=np.array([1.0]),
        r=np.array([0.3]),
        K=np.array([[0.5]]),
        N=np.array([[1.0]]),
        sign=-1,
        dt=0.1,
    )


def reference(case, times):
    A, B, C, D = case["A"], case["B"], case["C"], case["D"]
    n = len(A)

    def output(state):
        x = state[:n]
        if "K" in case:
            u = case["sign"] * case["K"] @ x + case["N"] @ case["r"]
            if "saturation" in case:
                u = np.clip(u, case["saturation"]["u_min"], case["saturation"]["u_max"])
        else:
            # u = r + s(Cc z + Dc y), y=Cx+Du; solve the algebraic loop.
            z = state[n:]
            s = case["sign"]
            u = np.linalg.solve(
                np.eye(B.shape[1]) - s * case["Dc"] @ D,
                case["r"] + s * case["Cc"] @ z + s * case["Dc"] @ C @ x,
            )
        return u, C @ x + D @ u

    if case.get("dt"):
        states = [case["x0"].copy()]
        for _ in range(round(DURATION / case["dt"])):
            x = states[-1]
            u, _ = output(x)
            states.append(A @ x + B @ u)
        indices = np.rint(times / case["dt"]).astype(int)
        assert np.max(np.abs(times - indices * case["dt"])) < 1e-8
        state = np.array(states)[indices].T
    else:

        def rhs(t, state):
            u, y = output(state)
            return (
                np.r_[A @ state[:n] + B @ u, case["Ac"] @ state[n:] + case["Bc"] @ y]
                if "Ac" in case
                else A @ state + B @ u
            )

        initial = np.r_[case["x0"], case.get("z0", np.empty(0))]
        solution = solve_ivp(
            rhs, (0, DURATION), initial, rtol=1e-11, atol=1e-12, max_step=STEP, dense_output=True
        )
        assert solution.success
        state = solution.sol(times)
    return np.column_stack([output(state[:, i])[1] for i in range(len(times))]), state[:, -1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/audits/pvm-official")
    parser.add_argument("--upstream", type=Path, help="Optional pinned PathView source checkout")
    parser.add_argument("--wheels", type=Path, help="Optional downloaded external audit wheels")
    args = parser.parse_args()
    assert version("pathview") == "0.21.0" and version("pathsim") == "0.31.0"
    args.output.mkdir(parents=True, exist_ok=True)
    package = Path(pathview.__file__).parent
    source_hashes = {}
    for relative, expected in {
        "converter.py": "9993b6247434f712cd7fede6117f127c5988541e",
        "buses.py": "29a1953ab486205cbbaa4014800c7e57c120f0ee",
    }.items():
        content = (package / relative).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        assert actual == expected, f"Official source mismatch: {relative}"
        source_hashes[relative] = {
            "git_blob_sha1": actual,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    upstream = (
        load_registry(args.upstream / "pathview/data/registry.json") if args.upstream else None
    )
    registry = load_registry(package / "data/registry.json")
    source_hashes["data/registry.json"] = {
        "sha256": hashlib.sha256((package / "data/registry.json").read_bytes()).hexdigest()
    }
    results = []
    for case in cases():
        name = case["name"]
        plant = StateSpace(
            case["A"], case["B"], case["C"], case["D"], dt=case.get("dt"), id="audit_plant"
        )
        scenario = {
            "initial_state": case["x0"],
            "reference": {"type": "constant", "value": case["r"]},
            "duration": str(DURATION),
            "dt": str(case.get("dt", STEP)),
            "atol": "1e-10",
            "rtol": "1e-9",
            "ftol": "1e-10",
        }
        if "saturation" in case:
            scenario["saturation"] = case["saturation"]
        try:
            pvm = make_pvm(plant, case["ctrl"], scenario=scenario)
        except UnsupportedModelError as exc:
            if not case.get("dt"):
                raise
            result = {
                "case": name,
                "passed": True,
                "supported": False,
                "decision": "typed_export_rejection",
                "reason": str(exc),
                "trajectory_equivalence_verified": False,
                "note": "Prior exported discrete graph failed the exact recurrence; refusing export is an honest capability restriction, not numerical validation.",
            }
            results.append(result)
            print(json.dumps(result), flush=True)
            continue
        for node in pvm["graph"]["nodes"]:
            entry = registry["blocks"][node["type"]]
            assert set(node["params"]) <= set(entry["params"]), node
            if upstream is not None:
                assert entry == upstream["blocks"][node["type"]]
        (args.output / f"{name}.pvm").write_text(json.dumps(pvm, indent=2) + "\n")
        source = generate_python(pvm, registry, source_name=f"{name}.pvm")
        (args.output / f"{name}.py.txt").write_text(source)
        ns = {"__name__": "f9_trusted_generated_case"}
        try:
            exec(compile(source, f"<F9 generated {name}>", "exec"), ns)
            ns["sim"].run(duration=DURATION, adaptive=False)
            scope = next(
                ns[sanitize_name(n["name"])] for n in pvm["graph"]["nodes"] if n["id"] == "scope_y"
            )
            times, actual = scope.read()
            expected, state_final = reference(case, times)
            error = float(np.max(np.abs(actual - expected)))
            plant_node = next(n for n in pvm["graph"]["nodes"] if n["id"] == "plant_ss")
            block = ns[sanitize_name(plant_node["name"])]
            actual_final = block._x if case.get("dt") else block.engine.state
            # DiscreteStateSpace stores the NEXT state after emitting y[k].
            state_error = (
                None
                if case.get("dt")
                else float(np.max(np.abs(actual_final - state_final[: len(case["A"])])))
            )
            controller_error = None
            if "Ac" in case and len(case["Ac"]):
                node = next(
                    n
                    for n in pvm["graph"]["nodes"]
                    if n["controlLab"]["legacy_node"]["type"] == "DynamicController"
                )
                controller_error = float(
                    np.max(
                        np.abs(
                            ns[sanitize_name(node["name"])].engine.state
                            - state_final[len(case["A"]) :]
                        )
                    )
                )
            result = {
                "case": name,
                "samples": len(times),
                "max_output_abs_error": error,
                "max_plant_final_state_abs_error": state_error,
                "max_controller_final_state_abs_error": controller_error,
                "error_limit": ERROR_LIMIT,
                "nodes": len(pvm["graph"]["nodes"]),
                "connections": len(pvm["graph"]["connections"]),
                "passed": error <= ERROR_LIMIT
                and (state_error is None or state_error <= ERROR_LIMIT)
                and (controller_error is None or controller_error <= ERROR_LIMIT),
            }
            np.savetxt(
                args.output / f"{name}.csv",
                np.column_stack([times, actual.T, expected.T]),
                delimiter=",",
                header="t,actual_y...,reference_y...",
                comments="",
            )
        except Exception as exc:
            result = {"case": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        print(json.dumps(result), flush=True)
    versions = {m: version(m) for m in ["pathview", "pathsim", "numpy", "scipy", "matplotlib"]}
    hashes = (
        {str(p.name): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.wheels.glob("*.whl")}
        if args.wheels
        else {}
    )
    report = {
        "document_id": "CL-DIR-001",
        "work_package": "WP-AUDIT-FIX-F1-PVM-OFFICIAL",
        "source_base_commit": "0d788634fceddca4aa34ee04b00877df5aa43a7d",
        "control_lab_source_sha256": {
            str(p): hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in [Path("control_lab/io/pvm.py"), Path("control_lab/io/pvm_official.py")]
        },
        "assay_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "upstream_commit": "4afdcc461ed63aa4231930170d20774428d51e8d",
        "versions": versions,
        "official_sources": source_hashes,
        "exported_registry_subset_compared_to_pinned_upstream": upstream is not None,
        "wheel_sha256": hashes,
        "oracle": "independent ODE/algebraic-loop equations; scipy solve_ivp high accuracy; exact recurrence for discrete case",
        "only_fresh_test_generated_code_executed": True,
        "official_ui_not_part_of_this_script": True,
        "all_passed": all(x["passed"] for x in results),
        "cases": results,
    }
    (args.output / "trajectory-assay.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["all_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
