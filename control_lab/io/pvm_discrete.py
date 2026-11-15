"""Synchronous discrete PathView adapter using one official vector SampleHold.

The shared register stores state deviations, so its documented zero initial
output represents every nonzero plant/controller initial value exactly. Its
first capture is at T, after the k=0 algebraic network has settled. A single
vector capture updates all states simultaneously, independent of node order.
No callback stores state, modifies a PathSim class, or precomputes a trajectory.
"""

from __future__ import annotations

import copy

import numpy as np

from control_lab.diagnostics import ImportUntrustedCodeError, UnsupportedModelError, ValidationError
from control_lab.io.pvm_official import (
    PATHVIEW_COMMIT,
    _dimensions,
    _expr,
    _numeric,
    _port,
    _render_node,
)

CLOCK_PROFILE = "controllab.pathview.clocked.v2"
CLOCK_ID = "controllab_clock_state"


def _edge(source, sp, target, tp):
    return {
        "sourceNodeId": source,
        "sourcePortIndex": sp,
        "targetNodeId": target,
        "targetPortIndex": tp,
    }


def _key(connection):
    return tuple(
        connection[k]
        for k in ("sourceNodeId", "sourcePortIndex", "targetNodeId", "targetPortIndex")
    )


def _state(node):
    p = node["params"]
    dynamic = node["type"] == "DynamicController"
    if node["type"] not in {"StateSpace", "DynamicController"}:
        return None
    A = _numeric(p["Ac"] if dynamic else p["A"])
    n = len(A)
    if not n:
        return None
    m = sum(_dimensions(node)[0])
    out = sum(_dimensions(node)[1]) if dynamic else _dimensions(node)[1][0]
    A = A.reshape(n, n)
    B = _numeric(p["Bc"] if dynamic else p["B"]).reshape(n, m)
    C = _numeric(p["Cc"] if dynamic else p["C"]).reshape(out, n)
    D = _numeric(p["Dc"] if dynamic else p["D"]).reshape(out, m)
    initial = _numeric(p["initial_state"]).reshape(n)
    T = p["dt"]
    if isinstance(T, bool) or not isinstance(T, (int, float)) or not np.isfinite(T) or T <= 0:
        raise UnsupportedModelError(
            "Clocked PathView requires one finite positive discrete period."
        )
    return A, B, C, D, initial, float(T), dynamic


def _parts(originals):
    specs = {node["id"]: _state(node) for node in originals}
    state_ids = sorted(nid for nid, spec in specs.items() if spec is not None)
    if not state_ids:
        raise UnsupportedModelError(
            "Clocked PathView requires at least one stateful discrete component."
        )
    periods = {specs[nid][5] for nid in state_ids}
    if len(periods) != 1:
        raise UnsupportedModelError(
            "Multirate PathView export is not supported by the synchronous adapter."
        )
    T = periods.pop()
    offset, ranges = 0, {}
    for nid in state_ids:
        n = len(specs[nid][0])
        ranges[nid] = (offset, n)
        offset += n
    nodes, imap, omap, internal = [], {}, {}, []
    for order, original in enumerate(originals):
        nid = original["id"]
        spec = specs[nid]
        if spec is None:
            rendered, ins, outs = _render_node(original)
            for actual in rendered:
                actual["controlLab"].update(profile=CLOCK_PROFILE, legacy_order=order)
            nodes.extend(rendered)
            imap.update(ins)
            omap.update(outs)
            continue
        A, B, C, D, initial, _, dynamic = spec
        ins, outs = _dimensions(original)
        m, n, outsize = sum(ins), len(A), sum(outs)
        if not dynamic and len(outs) > 1:
            C = np.vstack([C, np.eye(n)])
            D = np.vstack([D, np.zeros((n, m))])
        xexpr = f"(np.asarray(v[{m}:{m + n}], dtype=float) + {_expr(initial.tolist())})"
        uexpr = f"np.asarray(v[:{m}], dtype=float)"
        output_expr = f"{_expr(C.tolist())} @ {xexpr} + {_expr(D.tolist())} @ {uexpr}"
        # The dynamic controller's complete state remains visible; echoed
        # inputs feed its separate transition node without hidden fan-in.
        sections = [output_expr] + ([xexpr] if dynamic else []) + [uexpr]
        hidden_state_count = n if dynamic else 0
        echo_offset = outsize + hidden_state_count
        input_ports, output_ports = [], []
        for port, size in enumerate(ins):
            for component in range(size):
                index = len(input_ports)
                input_ports.append(_port(nid, "input", index, f"u{index}"))
                imap[(nid, port, component)] = (nid, index)
        for port, size in enumerate(outs):
            for component in range(size):
                index = len(output_ports)
                output_ports.append(_port(nid, "output", index, f"out{index}"))
                omap[(nid, port, component)] = (nid, index)
        for j in range(hidden_state_count):
            output_ports.append(_port(nid, "output", len(output_ports), f"state{j}"))
        for j in range(m):
            output_ports.append(_port(nid, "output", len(output_ports), f"input_echo{j}"))
        for j in range(n):
            input_ports.append(_port(nid, "input", len(input_ports), f"delta_state{j}"))
        extension = {
            "profile": CLOCK_PROFILE,
            "legacy_node": copy.deepcopy(original),
            "legacy_order": order,
        }
        actual = {
            "id": nid,
            "type": "Function",
            "name": original["name"],
            "position": copy.deepcopy(original["position"]),
            "inputs": input_ports,
            "outputs": output_ports,
            "params": {"func": f"lambda *v: np.concatenate(({', '.join(sections)}))"},
            "controlLab": {
                **extension,
                "role": "component_output",
                "state_output_offset": outsize if dynamic else (outs[0] if len(outs) > 1 else None),
            },
        }
        next_id = nid + "__clock_next"
        next_node = {
            "id": next_id,
            "type": "Function",
            "name": original["name"] + "_NextState",
            "position": {"x": 1200.0, "y": 200.0 + 240.0 * state_ids.index(nid)},
            "inputs": [
                _port(next_id, "input", j, f"u{j}" if j < m else f"delta_state{j - m}")
                for j in range(m + n)
            ],
            "outputs": [_port(next_id, "output", j, f"next_delta{j}") for j in range(n)],
            "params": {
                "func": f"lambda *v: {_expr(A.tolist())} @ {xexpr} + {_expr(B.tolist())} @ {uexpr} - {_expr(initial.tolist())}"
            },
            "controlLab": {**extension, "role": "component_transition"},
        }
        nodes.extend([actual, next_node])
        start = ranges[nid][0]
        for j in range(n):
            internal.extend(
                [
                    _edge(CLOCK_ID, start + j, nid, m + j),
                    _edge(CLOCK_ID, start + j, next_id, m + j),
                    _edge(next_id, j, CLOCK_ID, start + j),
                ]
            )
        for j in range(m):
            internal.append(_edge(nid, echo_offset + j, next_id, j))
    nodes.append(
        {
            "id": CLOCK_ID,
            "type": "SampleHold",
            "name": "SynchronousStateRegister",
            "position": {"x": 1500.0, "y": 100.0},
            "inputs": [_port(CLOCK_ID, "input", j, f"next_delta{j}") for j in range(offset)],
            "outputs": [_port(CLOCK_ID, "output", j, f"delta{j}") for j in range(offset)],
            "params": {"T": repr(T), "tau": repr(T)},
            "controlLab": {
                "profile": CLOCK_PROFILE,
                "role": "synchronous_state_register",
                "state_layout": [
                    {"node_id": nid, "offset": ranges[nid][0], "size": ranges[nid][1]}
                    for nid in state_ids
                ],
            },
        }
    )
    return nodes, imap, omap, internal, T


def lower_clocked(legacy):
    if legacy.get("events"):
        raise UnsupportedModelError(
            "External events are not supported by the verified synchronous discrete adapter."
        )
    originals = legacy["graph"]["nodes"]
    if any(node["id"] == CLOCK_ID or "__clock_next" in node["id"] for node in originals):
        raise ValidationError("Reserved synchronous adapter node identifier.")
    nodes, imap, omap, internal, T = _parts(originals)
    by_id = {node["id"]: node for node in originals}
    connections = list(internal)
    for connection in legacy["graph"]["connections"]:
        sid, sp, tid, tp = _key(connection)
        sizes = _dimensions(by_id[sid])[1][sp], _dimensions(by_id[tid])[0][tp]
        if sizes[0] != sizes[1]:
            raise ValidationError("Incompatible vector dimensions in the synchronous adapter.")
        for j in range(sizes[0]):
            source, sport = omap[(sid, sp, j)]
            target, tport = imap[(tid, tp, j)]
            connections.append(_edge(source, sport, target, tport))
    for index, connection in enumerate(connections):
        connection["id"] = f"clock_conn_{index:04d}"
    doc = copy.deepcopy(legacy)
    doc["graph"].update(nodes=nodes, connections=connections)
    doc["metadata"].update(
        adapter_profile=CLOCK_PROFILE,
        pathview_target_commit=PATHVIEW_COMMIT,
        pathview_target_version="0.21.0",
        passive_projection=True,
        discrete_clock_period=T,
        discrete_clock_semantics="single_vector_capture_at_kT_after_initial_state",
    )
    if doc["simulationSettings"]["solver"] == "Discrete":
        doc["simulationSettings"]["solver"] = "RKCK54"
    return doc


def restore_clocked(official):
    if official.get("events"):
        raise ImportUntrustedCodeError(
            "Imported events cannot be evaluated by the synchronous numeric projection."
        )
    originals, orders = {}, {}
    actual_nodes = official["graph"]["nodes"]
    for actual in actual_nodes:
        ext = actual.get("controlLab", {})
        if ext.get("profile") != CLOCK_PROFILE:
            raise ImportUntrustedCodeError("Missing synchronous projection metadata.")
        if actual["id"] == CLOCK_ID:
            continue
        original = ext.get("legacy_node")
        order = ext.get("legacy_order")
        if not isinstance(original, dict) or isinstance(order, bool) or not isinstance(order, int):
            raise ImportUntrustedCodeError(
                "Missing numeric component or component order in synchronous projection."
            )
        nid = original["id"]
        if nid in originals and (originals[nid] != original or orders[nid] != order):
            raise ValidationError("Inconsistent synchronous component projections.")
        originals[nid], orders[nid] = original, order
    if sorted(orders.values()) != list(range(len(originals))):
        raise ValidationError("Invalid synchronous numeric component order.")
    original_nodes = sorted(originals.values(), key=lambda node: orders[node["id"]])
    rendered, imap, omap, internal, T = _parts(original_nodes)
    if official["metadata"].get("discrete_clock_period") != T:
        raise ValidationError("Clock period differs from the numeric component periods.")
    expected = {node["id"]: node for node in rendered}
    if len(actual_nodes) != len(expected) or {node["id"] for node in actual_nodes} != set(expected):
        raise ValidationError("Incomplete synchronous graph expansion.")
    for actual in actual_nodes:
        for field in ("type", "params", "inputs", "outputs", "controlLab"):
            if actual.get(field) != expected[actual["id"]][field]:
                raise ImportUntrustedCodeError(
                    f"Synchronous node projection mismatch ({actual['id']}, {field})."
                )
    expected_internal = {_key(connection) for connection in internal}
    actual_internal = []
    reverse_in, reverse_out = {v: k for k, v in imap.items()}, {v: k for k, v in omap.items()}
    groups = {}
    for connection in official["graph"]["connections"]:
        key = _key(connection)
        if key in expected_internal:
            actual_internal.append(key)
            continue
        source, target = reverse_out.get(key[:2]), reverse_in.get(key[2:])
        if source is None or target is None or source[2] != target[2]:
            raise ValidationError("Unexpected synchronous graph connection.")
        groups.setdefault(source[:2] + target[:2], []).append(source[2])
    if len(actual_internal) != len(expected_internal) or set(actual_internal) != expected_internal:
        raise ValidationError("Missing or duplicated synchronous internal connection.")
    connections = []
    for (sid, sp, tid, tp), components in groups.items():
        sizes = _dimensions(originals[sid])[1][sp], _dimensions(originals[tid])[0][tp]
        if sizes[0] != sizes[1] or sorted(components) != list(range(sizes[0])):
            raise ValidationError("Incomplete external scalar connection in synchronous graph.")
        connections.append(_edge(sid, sp, tid, tp))
    result = copy.deepcopy(official)
    result["graph"].update(nodes=original_nodes, connections=connections)
    return result
