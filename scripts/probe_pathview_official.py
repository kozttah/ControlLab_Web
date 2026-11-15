"""Audit generated PVM against an unmodified, pinned official PathView converter.

Usage: python scripts/probe_pathview_official.py --upstream /path/to/pathview-checkout
       --output docs/audits/pathview

No third-party PVM/codeContext is executed. The official converter emits source;
we inspect its AST and compare its topology with ControlLab's generated graph.
Exit 2 means G-0D blocked; a generated Python file alone never proves parity.
"""

import argparse
import ast
import hashlib
import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_lab.core.controllers import DynamicController, StateFeedbackController
from control_lab.core.models import StateSpace
from control_lab.io.pvm import make_pvm

UPSTREAM = "4afdcc461ed63aa4231930170d20774428d51e8d"
PINNED = {
    "pathview/__init__.py": "f9cd1b4fd2a031f956a15cad66719a71e00a30e3",
    "pathview/converter.py": "9993b6247434f712cd7fede6117f127c5988541e",
    "pathview/buses.py": "29a1953ab486205cbbaa4014800c7e57c120f0ee",
    "pathview/data/registry.json": "b5a054b250843fe99dcd90d616768020594aac13",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_hashes = {}
    for relative, expected in PINNED.items():
        data = (args.upstream / relative).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected:
            raise ValueError(f"Official source mismatch: {relative}: {actual} != {expected}")
        source_hashes[relative] = {
            "git_blob_sha1": actual,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    sys.path.insert(0, str(args.upstream.resolve()))
    official = importlib.import_module("pathview.converter")
    assert Path(official.__file__).resolve() == (args.upstream / "pathview/converter.py").resolve()
    registry = official.load_registry(args.upstream / "pathview/data/registry.json")
    args.output.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, C, controller, scenario in [
        (
            "lqr_c_eq_i",
            [[1, 0], [0, 1]],
            StateFeedbackController(K=[[2, 3]], feedback_sign="negative", dt=None),
            {},
        ),
        (
            "lqr_c_neq_i",
            [[1, 0]],
            StateFeedbackController(K=[[2, 3]], feedback_sign="negative", dt=None),
            {},
        ),
        (
            "lqr_saturation",
            [[1, 0]],
            StateFeedbackController(K=[[2, 3]], feedback_sign="negative", dt=None),
            {"saturation": {"enabled": True, "u_min": [-1], "u_max": [1]}},
        ),
        (
            "dynamic",
            [[1, 0]],
            DynamicController(
                Ac=[[-2]],
                Bc=[[1, 0.5]],
                Cc=[[1.2]],
                Dc=[[0.3, 0.8]],
                feedback_sign="negative",
                dt=None,
                ports={
                    "inputs": [
                        {"name": "y", "role": "y", "size": 1},
                        {"name": "r", "role": "r", "size": 1},
                    ],
                    "outputs": [{"name": "u", "role": "u", "size": 1}],
                },
                interconnection_scheme="two_dof",
                initial_state=[0.25],
            ),
            {},
        ),
    ]:
        plant = StateSpace(
            [[0, 1], [0, 0]], [[0], [1]], C, [[0]] if len(C) == 1 else [[0], [0]], dt=None
        )
        pvm = make_pvm(plant, controller, scenario={"initial_state": [1.0, 0.0], **scenario})
        generated = official.generate_python(pvm, registry, source_name=f"{name}.pvm")
        tree = ast.parse(generated)
        unknown = sorted(
            {
                node["type"]
                for node in pvm["graph"]["nodes"]
                if node["type"] not in registry["blocks"]
            }
        )
        connections = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Connection"
        ]
        filtered = {}
        for node in pvm["graph"]["nodes"]:
            block = registry["blocks"].get(node["type"])
            if block:
                invalid = sorted(set(node["params"]) - set(block["params"]))
                if invalid:
                    filtered[node["id"]] = {"type": node["type"], "ignored_params": invalid}
        (args.output / f"{name}.pvm").write_text(json.dumps(pvm, indent=2) + "\n")
        (args.output / f"{name}.py.txt").write_text(generated)
        cases.append(
            {
                "case": name,
                "input_nodes": len(pvm["graph"]["nodes"]),
                "input_connections": len(pvm["graph"]["connections"]),
                "generated_connection_calls": len(connections),
                "unknown_blocks": unknown,
                "ignored_parameters": filtered,
                "trajectory_equivalence_verified": False,
            }
        )
    result = {
        "upstream_repository": "https://github.com/pathsim/pathview",
        "upstream_commit": UPSTREAM,
        "official_source_hashes": source_hashes,
        "converter_executed": True,
        "generated_simulation_executed": False,
        "official_ui_import_verified": False,
        "gate": "G-0D",
        "verdict": "fail",
        "external_pathview_verified": False,
        "reason": "Official converter omits unregistered blocks and connected feedback wires; trajectory parity cannot be claimed.",
        "cases": cases,
    }
    (args.output / "official-converter-probe.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
