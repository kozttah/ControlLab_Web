"""Deterministic lowering to the pinned official PathView scalar-channel ABI.

The numeric extension on each node is a passive, versioned projection of the
supported ControlLab subset. It is not executable and cannot override the
exported graph: restoring it verifies every official constructor expression,
port and scalar connection before the numeric evaluator sees the projection.
Arbitrary PathView Python expressions remain import-only, never evaluated.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

from control_lab.diagnostics import (
    ControlLabError,
    ImportUntrustedCodeError,
    UnsupportedModelError,
    ValidationError,
)

PROFILE = "controllab.pathview.scalar.v1"
PATHVIEW_COMMIT = "4afdcc461ed63aa4231930170d20774428d51e8d"
OFFICIAL_PARAMS = {
    "Source": ["func"],
    "Function": ["func"],
    "StateSpace": [
        "A",
        "B",
        "C",
        "D",
        "initial_value",
        "state_labels",
        "input_labels",
        "output_labels",
    ],
    "DiscreteStateSpace": ["A", "B", "C", "D", "T", "tau", "initial_value"],
    "Adder": ["operations"],
    "Clip": ["min_val", "max_val"],
    "Scope": ["sampling_period", "t_wait", "labels"],
    "SampleHold": ["T", "tau"],
}


def _numeric(value: Any) -> np.ndarray:
    def allowed(v):
        return (isinstance(v, (int, float)) and not isinstance(v, bool)) or (
            isinstance(v, list) and all(allowed(x) for x in v)
        )

    if not allowed(value):
        raise ImportUntrustedCodeError(
            "Only numeric literals are accepted in the passive PathView projection."
        )
    result = np.asarray(value, dtype=float)
    if not np.isfinite(result).all():
        raise ValidationError("Non-finite matrix in PathView projection.")
    return result


def _expr(value: Any) -> str:
    return f"np.array({_numeric(value).tolist()!r}, dtype=float)"


def _port(nid: str, direction: str, index: int, name: str) -> dict:
    return {"nodeId": nid, "direction": direction, "index": index, "name": name}


def _dimensions(node: dict) -> tuple[list[int], list[int]]:
    p, kind = node["params"], node["type"]
    if kind == "Source":
        return [], [int(p["dim"])]
    if kind == "StateSpace":
        m, out = len(p["D"][0]), len(p["D"])
        return [m], [out] + ([len(p["A"])] if len(node["outputs"]) > 1 else [])
    if kind == "DynamicController":
        return [int(x["size"]) for x in p["ports"]["inputs"]], [
            int(x["size"]) for x in p["ports"]["outputs"]
        ]
    if kind == "MatrixGain":
        return [len(p["gain"][0])], [len(p["gain"])]
    if kind == "Adder":
        return [int(p["dim"])] * len(node["inputs"]), [int(p["dim"])]
    if kind == "Saturation":
        return [int(p["dim"])], [int(p["dim"])]
    if kind == "Scope":
        return [int(p["dim"])], []
    raise UnsupportedModelError(f"Unsupported numeric PathView projection: {kind!r}.")


def _render_node(node: dict) -> tuple[list[dict], dict, dict]:
    nid, p, kind = node["id"], node["params"], node["type"]
    ins, outs = _dimensions(node)
    input_map, output_map = {}, {}
    if kind == "Source":
        if p.get("signal_type") not in {"zero", "step", "constant"}:
            raise UnsupportedModelError(
                "Only constant/step/zero reference sources are supported by the official exporter."
            )
        values = _numeric(p["value"]).reshape(-1)
        if len(values) != outs[0]:
            raise ValidationError("Source dimension mismatch.")
        nodes = []
        for component, value in enumerate(values):
            actual_id = nid if component == 0 else f"{nid}__ch{component}"
            actual = {
                "id": actual_id,
                "type": "Source",
                "name": f"{node['name']}_{component}",
                "position": {
                    "x": node["position"]["x"],
                    "y": node["position"]["y"] + 90 * component,
                },
                "inputs": [],
                "outputs": [_port(actual_id, "output", 0, f"out{component}")],
                "params": {"func": f"lambda t: {float(value)!r}"},
                "controlLab": {
                    "profile": PROFILE,
                    "legacy_node": copy.deepcopy(node),
                    "component": component,
                },
            }
            nodes.append(actual)
            output_map[(nid, 0, component)] = (actual_id, 0)
        return nodes, input_map, output_map

    official_type, params = "Function", {}
    if kind in {"StateSpace", "DynamicController"}:
        dynamic = kind == "DynamicController"
        A = _numeric(p["Ac"] if dynamic else p["A"])
        m = sum(ins)
        A = A.reshape((len(p["Ac"] if dynamic else p["A"]), -1)) if A.size else np.empty((0, 0))
        B = _numeric(p["Bc"] if dynamic else p["B"]).reshape((A.shape[0], m))
        C = _numeric(p["Cc"] if dynamic else p["C"]).reshape(
            (sum(outs) if dynamic else outs[0], A.shape[0])
        )
        D = _numeric(p["Dc"] if dynamic else p["D"]).reshape((sum(outs) if dynamic else outs[0], m))
        if not dynamic and len(outs) > 1:
            C = np.vstack([C, np.eye(A.shape[0])])
            D = np.vstack([D, np.zeros((A.shape[0], m))])
        if A.shape[0] == 0:
            params = {"func": f"lambda *v: {_expr(D.tolist())} @ np.asarray(v, dtype=float)"}
        else:
            official_type = "StateSpace" if p.get("dt") is None else "DiscreteStateSpace"
            params = {
                "A": _expr(A.tolist()),
                "B": _expr(B.tolist()),
                "C": _expr(C.tolist()),
                "D": _expr(D.tolist()),
                "initial_value": _expr(p["initial_state"]),
            }
            if official_type == "DiscreteStateSpace":
                params["T"] = repr(float(p["dt"]))
    elif kind == "MatrixGain":
        params = {"func": f"lambda *v: {_expr(p['gain'])} @ np.asarray(v, dtype=float)"}
    elif kind == "Adder":
        if any(s not in {"+", "-"} for s in p["signs"]):
            raise ValidationError("Invalid feedback sum sign.")
        dim = ins[0]
        if dim == 1:
            official_type, params = "Adder", {"operations": repr("".join(p["signs"]))}
        else:
            expression = " ".join(
                f"{sign} np.asarray(v[{i * dim}:{(i + 1) * dim}], dtype=float)"
                for i, sign in enumerate(p["signs"])
            )
            params = {"func": f"lambda *v: {expression}"}
    elif kind == "Saturation":
        if p["enabled"]:
            official_type, params = (
                "Clip",
                {"min_val": _expr(p["u_min"]), "max_val": _expr(p["u_max"])},
            )
        else:
            params = {"func": "lambda *v: np.asarray(v, dtype=float)"}
    elif kind == "Scope":
        official_type, params = (
            "Scope",
            {"labels": repr(p.get("channel_names", [f"y{i}" for i in range(ins[0])]))},
        )
    else:
        raise UnsupportedModelError(f"Unsupported official projection for {kind}.")
    input_ports, output_ports = [], []
    for direction, sizes, mapping, ports in [
        ("input", ins, input_map, input_ports),
        ("output", outs, output_map, output_ports),
    ]:
        for original_port, size in enumerate(sizes):
            for component in range(size):
                index = len(ports)
                label = node["inputs" if direction == "input" else "outputs"][original_port].get(
                    "name", direction
                )
                ports.append(_port(nid, direction, index, f"{label}{component}"))
                mapping[(nid, original_port, component)] = (nid, index)
    actual = {
        "id": nid,
        "type": official_type,
        "name": node["name"],
        "position": copy.deepcopy(node["position"]),
        "inputs": input_ports,
        "outputs": output_ports,
        "params": params,
        "controlLab": {"profile": PROFILE, "legacy_node": copy.deepcopy(node)},
    }
    return [actual], input_map, output_map


def lower_to_official(legacy: dict) -> dict:
    if any(node["type"] == "StateSpace" and node["params"].get("dt") is not None
           for node in legacy["graph"]["nodes"]):
        from control_lab.io.pvm_discrete import lower_clocked

        return lower_clocked(legacy)
    doc = copy.deepcopy(legacy)
    nodes, imap, omap = [], {}, {}
    originals = {n["id"]: n for n in legacy["graph"]["nodes"]}
    for node in originals.values():
        rendered, inputs, outputs = _render_node(node)
        nodes.extend(rendered)
        imap.update(inputs)
        omap.update(outputs)
    connections = []
    for conn in legacy["graph"]["connections"]:
        source, sp = conn["sourceNodeId"], conn["sourcePortIndex"]
        target, tp = conn["targetNodeId"], conn["targetPortIndex"]
        sizes = _dimensions(originals[source])[1], _dimensions(originals[target])[0]
        if sizes[0][sp] != sizes[1][tp]:
            raise ValidationError("Incompatible vector connection dimensions.")
        for component in range(sizes[0][sp]):
            sid, sport = omap[(source, sp, component)]
            tid, tport = imap[(target, tp, component)]
            connections.append(
                {
                    "id": f"scalar_conn_{len(connections):04d}",
                    "sourceNodeId": sid,
                    "sourcePortIndex": sport,
                    "targetNodeId": tid,
                    "targetPortIndex": tport,
                }
            )
    doc["graph"]["nodes"], doc["graph"]["connections"] = nodes, connections
    doc["metadata"].update(
        {
            "adapter_profile": PROFILE,
            "pathview_target_commit": PATHVIEW_COMMIT,
            "pathview_target_version": "0.21.0",
            "passive_projection": True,
        }
    )
    # Every expression is deterministic and self-contained; imported code is never executed.
    doc["codeContext"]["code"] = legacy["codeContext"]["code"]
    if doc["simulationSettings"]["solver"] == "Discrete":
        doc["simulationSettings"]["solver"] = "RKCK54"
    return doc


def _restore_numeric_projection(official: dict) -> dict:
    if official.get("metadata", {}).get("adapter_profile") == "controllab.pathview.clocked.v2":
        from control_lab.io.pvm_discrete import restore_clocked

        return restore_clocked(official)
    if official.get("metadata", {}).get("adapter_profile") != PROFILE:
        return official
    originals = {}
    actual_nodes = official["graph"]["nodes"]
    for node in actual_nodes:
        extension = node.get("controlLab", {})
        if extension.get("profile") != PROFILE or not isinstance(
            extension.get("legacy_node"), dict
        ):
            raise ImportUntrustedCodeError(
                "Missing numeric PathView projection; arbitrary callbacks cannot be simulated passively."
            )
        original = extension["legacy_node"]
        nid = original["id"]
        if nid in originals and originals[nid] != original:
            raise ValidationError("Inconsistent channel projections.")
        originals[nid] = original
    expected_nodes, reverse_in, reverse_out = {}, {}, {}
    for original in originals.values():
        rendered, ins, outs = _render_node(original)
        expected_nodes.update({n["id"]: n for n in rendered})
        reverse_in.update({v: k for k, v in ins.items()})
        reverse_out.update({v: k for k, v in outs.items()})
    if {n["id"] for n in actual_nodes} != set(expected_nodes):
        raise ValidationError("Incomplete official projection nodes.")
    for actual in actual_nodes:
        expected = expected_nodes[actual["id"]]
        for key in ["type", "params", "inputs", "outputs", "controlLab"]:
            if actual.get(key) != expected[key]:
                raise ImportUntrustedCodeError(
                    f"Official node {actual['id']!r} does not match its passive numeric projection ({key})."
                )
    grouped = {}
    for conn in official["graph"]["connections"]:
        source = reverse_out.get((conn["sourceNodeId"], conn["sourcePortIndex"]))
        target = reverse_in.get((conn["targetNodeId"], conn["targetPortIndex"]))
        if source is None or target is None or source[2] != target[2]:
            raise ValidationError("Noncanonical scalar connection; cannot project passively.")
        key = source[:2] + target[:2]
        grouped.setdefault(key, []).append(source[2])
    connections = []
    for (sid, sp, tid, tp), components in grouped.items():
        outsize, insize = _dimensions(originals[sid])[1][sp], _dimensions(originals[tid])[0][tp]
        if outsize != insize or sorted(components) != list(range(outsize)):
            raise ValidationError("Incomplete scalar channel connection.")
        connections.append(
            {"sourceNodeId": sid, "sourcePortIndex": sp, "targetNodeId": tid, "targetPortIndex": tp}
        )
    result = copy.deepcopy(official)
    result["graph"]["nodes"], result["graph"]["connections"] = list(originals.values()), connections
    return result


def restore_numeric_projection(official: dict) -> dict:
    """Reject malformed extension data with typed errors, never Python execution."""
    try:
        return _restore_numeric_projection(official)
    except ControlLabError:
        raise
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValidationError(
            f"Malformed passive PathView projection: {type(exc).__name__}."
        ) from exc
