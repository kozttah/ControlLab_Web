"""Deterministic, passive code generation for the three derived TS representations."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from control_lab.core.models import TSStateSpace
from control_lab.diagnostics import ValidationError
from control_lab.fuzzy.symbolic_qlpv import (
    BinaryOpNode,
    CallNode,
    ConstNode,
    ExprNode,
    NumberNode,
    UnaryOpNode,
    VarNode,
    parse_expression,
)

DERIVED_REPRESENTATIONS = frozenset(
    {"sector_nonlinearity", "tpmt_interpolated", "femt_simplicial"}
)


def _expression(node: ExprNode, variables: Mapping[str, str], *, matlab: bool = False) -> str:
    """Print only typed symbolic nodes, with all names mapped to generated identifiers."""
    if isinstance(node, (NumberNode, ConstNode)):
        return repr(node.value)
    if isinstance(node, VarNode):
        return variables[node.name]
    if isinstance(node, UnaryOpNode):
        return f"({node.op}{_expression(node.operand, variables, matlab=matlab)})"
    if isinstance(node, BinaryOpNode):
        left = _expression(node.left, variables, matlab=matlab)
        right = _expression(node.right, variables, matlab=matlab)
        if node.op == "^" and not matlab:
            return f"_real_power({left}, {right})"
        return f"({left} {node.op} {right})"
    assert isinstance(node, CallNode)
    function = node.func
    if not matlab and function not in {"sinc_rad", "cos1m_div_u"}:
        function = {"asin": "arcsin", "acos": "arccos", "atan": "arctan"}.get(function, function)
        function = f"np.{function}"
    return f"{function}({_expression(node.arg, variables, matlab=matlab)})"


_PY_SYMBOLIC = """\
def sinc_rad(u):
    if abs(u) < 1e-4:
        u2 = u * u
        return 1.0 - u2 / 6.0 + u2 * u2 / 120.0
    return np.sin(u) / u


def cos1m_div_u(u):
    if abs(u) < 1e-4:
        u2 = u * u
        return u * (0.5 - u2 / 24.0 + u2 * u2 / 720.0)
    return (1.0 - np.cos(u)) / u


def _real_power(base, exponent):
    return float(np.float_power(base, exponent))
"""

_PY_KUHN = """\
def _femt_weights(point):
    corner = []
    fractions = []
    for value, grid in zip(point, _GRIDS):
        value = np.clip(value, grid[0], grid[-1])
        i = int(np.clip(np.searchsorted(grid, value, side="right") - 1, 0, len(grid) - 2))
        corner.append(i)
        fractions.append((value - grid[i]) / (grid[i + 1] - grid[i]))
    shape = tuple(map(len, _GRIDS))
    order = np.argsort(-np.asarray(fractions), kind="stable")
    coefficients = -np.diff(np.r_[1.0, np.asarray(fractions)[order], 0.0])
    row = np.ravel_multi_index(tuple(corner), shape)
    h = coefficients[0] * _NODAL[row]
    for weight, axis in zip(coefficients[1:], order):
        corner[axis] += 1
        row = np.ravel_multi_index(tuple(corner), shape)
        h += weight * _NODAL[row]
    return h
"""

_PY_DELAUNAY = """\
def _femt_weights(point):
    point = np.clip(point, _BOUNDS[:, 0], _BOUNDS[:, 1])
    if _NODES.shape[1] == 1:
        order = np.argsort(_NODES[:, 0], kind="stable")
        return np.array([np.interp(point[0], _NODES[order, 0], col[order]) for col in _NODAL.T])
    candidates = np.all((point >= _SIMPLEX_MIN) & (point <= _SIMPLEX_MAX), axis=1)
    for indices in _SIMPLICES[candidates]:
        vertices = _NODES[indices]
        try:
            tail = np.linalg.solve((vertices[1:] - vertices[0]).T, point - vertices[0])
        except np.linalg.LinAlgError:
            continue
        bary = np.r_[1.0 - tail.sum(), tail]
        if np.min(bary) >= -1e-10:
            bary = np.clip(bary, 0.0, 1.0)
            return (bary / bary.sum()) @ _NODAL[indices]
    return _NODAL[np.argmin(np.sum((_NODES - point) ** 2, axis=1))]
"""


def _list_of(value: Any) -> list[Any]:
    return [list(item) if isinstance(item, (tuple, list)) else item for item in value]


def _weight_expressions(model: TSStateSpace) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    spec = model.membership_spec
    kind = spec.get("representation_kind")
    if kind == "sector_nonlinearity":
        premises = spec["sector_premises"]
        sources = [(item["name"], item["expression"]) for item in premises]
        low = [float(item["min"]) for item in premises]
        high = [float(item["max"]) for item in premises]
        bits = _list_of(item["bits"] for item in spec["functions"])
        setup = [
            f"_LO = np.array({low!r})",
            f"_HI = np.array({high!r})",
            f"_BITS = np.array({bits!r}, dtype=int)",
        ]
        body = [
            "    ratio = (point - _LO) / (_HI - _LO)",
            "    h = np.where(_BITS == 0, ratio, 1.0 - ratio).prod(axis=1)",
        ]
    elif kind == "tpmt_interpolated":
        axes = spec["tpmt_axes"]
        sources = [(axis["variable"], axis.get("expression", axis["variable"])) for axis in axes]
        grids = _list_of(axis["grid"] for axis in axes)
        tables = [_list_of(axis["weights_table"]) for axis in axes]
        indices = _list_of(item["axis_basis_indices"] for item in spec["functions"])
        setup = [
            f"_GRIDS = {grids!r}",
            f"_TABLES = [np.array(table) for table in {tables!r}]",
            f"_INDICES = {indices!r}",
        ]
        body = [
            "    factors = [[np.interp(p, grid, col) for col in table.T]",
            "               for p, grid, table in zip(point, _GRIDS, _TABLES)]",
            "    h = np.array([np.prod([factors[d][i] for d, i in enumerate(row)]) for row in _INDICES])",
        ]
    elif kind == "femt_simplicial":
        mesh = spec["femt_mesh"]
        sources = [(v, v) for v in mesh["variables"]]
        setup = [f"_NODAL = np.array({_list_of(mesh['nodal_weights'])!r})"]
        if mesh["mesh_kind"] == "kuhn_delaunay":
            setup.extend([f"_GRIDS = {_list_of(mesh['axes_grids'])!r}", _PY_KUHN])
        elif mesh["mesh_kind"] == "delaunay":
            setup.extend(
                [
                    f"_NODES = np.array({_list_of(mesh['nodes'])!r})",
                    f"_BOUNDS = np.array({_list_of(mesh['bounds'])!r})",
                    f"_SIMPLICES = np.array({_list_of(mesh['simplices'])!r}, dtype=int)",
                    "_SIMPLEX_MIN = _NODES[_SIMPLICES].min(axis=1) - 1e-11",
                    "_SIMPLEX_MAX = _NODES[_SIMPLICES].max(axis=1) + 1e-11",
                    _PY_DELAUNAY,
                ]
            )
        else:
            raise ValidationError("Unknown FEMT mesh kind.")
        body = ["    h = _femt_weights(point)"]
    else:
        raise ValidationError("Expected a sector, TPMT or FEMT derived TS model.")
    return setup, body, sources


def emit_python_membership(model: TSStateSpace) -> list[str]:
    """Generate a NumPy evaluator using the same nodes and ordering as the derived model."""
    setup, body, sources = _weight_expressions(model)
    state_names = list(model.state_names)
    names = {name: f"x[{i}]" for i, name in enumerate(state_names)}
    expressions = [parse_expression(source) for _, source in sources]
    missing = sorted({var for expr in expressions for var in expr.active_variables} - names.keys())
    names.update({name: f"external_values[{i}]" for i, name in enumerate(missing)})
    lines = [
        _PY_SYMBOLIC,
        *setup,
        "",
        "def premise_weights(point):",
        "    point = np.asarray(point, dtype=float)",
        *body,
        "    total = h.sum()",
        "    if not np.all(np.isfinite(h)) or total <= 1e-12 or np.any(h / total < -1e-9):",
        "        raise ValueError('Premises do not give convex weights in the model domain.')",
        "    return h / total",
        "",
        f"REQUIRED_EXTERNAL_PREMISES = {missing!r}",
        "",
        "def default_h_fn(x, t=0.0, external_premises=None):",
        "    external_values = []",
        "    for name in REQUIRED_EXTERNAL_PREMISES:",
        "        if external_premises is None or name not in external_premises:",
        "            raise ValueError(f'Supply external premise {name!r} as a constant or a function of time.')",
        "        signal = external_premises[name]",
        "        external_values.append(float(signal(t) if callable(signal) else signal))",
    ]
    values = ", ".join(_expression(expr.ast, names) for expr in expressions)
    return [*lines, "    x = np.asarray(x, dtype=float)", f"    return premise_weights([{values}])", ""]


def _parsed_matrices(model: TSStateSpace) -> dict[str, list[list[Any]]]:
    provenance = model.provenance
    derivation = provenance.get("ts_derivation", {})
    generalized = provenance.get("generalized_channels", {}).get("expressions", {})
    expressions = {key: derivation.get(f"{key}_expr") for key in ("A", "B", "C", "D")}
    for key in ("Bw", "Dyw", "Cz", "Dzu", "Dzw"):
        if key in generalized:
            expressions[key] = generalized[key]
    if any(not matrix for matrix in expressions.values()):
        raise ValidationError("The TS derivation provenance does not contain symbolic matrices.")
    return {
        key: [[parse_expression(entry) for entry in row] for row in matrix]
        for key, matrix in expressions.items()
    }


def _hull_projection_operator(basis, sampled_basis, final, diagnostics):
    """Map original samples into the frozen hull coordinates of a single mode."""
    import numpy as np
    from scipy.linalg import lstsq

    from control_lab.fuzzy.tpmt import cno_matrix, mgk_matrix, rno_ino_matrix, sn_nn_matrix

    augmented = diagnostics["rank_augmented"]
    raw = sampled_basis
    rhs = basis.T
    if augmented:
        raw = np.column_stack([raw, 1.0 - raw.sum(axis=1)])
        rhs = np.vstack([rhs, np.zeros((1, rhs.shape[1]))])
    change, _, rank, _ = lstsq(raw, final)
    if rank == raw.shape[1] and np.linalg.cond(change) < 1e10:
        if np.allclose(raw @ change, final, atol=2e-9, rtol=0.0):
            return np.linalg.solve(change, rhs)

    # If a regridded basis was rank deficient, the stored nodal functions cannot
    # identify a unique ambient change of coordinates. Replay the original hull step
    # on that sampling grid and accept it only if it reproduces the frozen weights.
    constant = np.ones(sampled_basis.shape[0])
    alpha, *_ = lstsq(sampled_basis, constant)
    residual = np.max(np.abs(sampled_basis @ alpha - constant))
    sn_tol = residual / 2 if augmented else max(1e-6, residual * 2)
    weights, _, info = sn_nn_matrix(sampled_basis, core=basis.T, mode=0, sn_tol=sn_tol)
    operator = info["core"]
    method = diagnostics["hull_type"]
    if method != "SN-NN":
        hull = {"RNO-INO": rno_ino_matrix, "CNO": cno_matrix, "MGK": mgk_matrix}[method]
        weights, _, info = hull(weights, core=operator, mode=0)
        operator = info["core"]
    if not np.allclose(weights, final, atol=2e-9, rtol=0.0):
        raise ValidationError("The selected hull basis does not admit a numerically faithful replay.")
    return operator


def _projection_operators(
    model: TSStateSpace,
    parsed: dict[str, list[list[Any]]],
) -> tuple[list[list[float]], list[list[list[float]]]]:
    """Extract fixed linear replay operators from the selected SVD and hull basis.

    Using the original basis transpose before the change of coordinates preserves
    the truncation even when SN-NN has appended a new (zero coefficient) mode.
    """
    import numpy as np

    from control_lab.fuzzy.femt import femt_svd_decompose
    from control_lab.fuzzy.tpmt import (
        _assemble_block_batch,
        hooi_sampled_func,
        hosvd_sampled_func,
        resample_basis_1d,
    )

    spec = model.membership_spec
    recipe = model.provenance["ts_derivation"]
    topology = spec["representation_kind"]
    axes = list(recipe["active_variables"])
    bounds = {**recipe["state_bounds"], **recipe["external_bounds"]}
    grids = [
        np.linspace(float(bounds[axis][0]), float(bounds[axis][1]), int(size))
        for axis, size in zip(axes, recipe["grid_points"])
    ]
    dimensions = [grid.size for grid in grids]
    mesh = np.meshgrid(*grids, indexing="ij")
    env = {axis: points.ravel() for axis, points in zip(axes, mesh)}
    generalized = {key: value for key, value in parsed.items() if key not in {"A", "B", "C", "D"}}
    nw = next((len(parsed[key][0]) for key in ("Bw", "Dyw", "Dzw") if key in parsed), 0)
    nz = next((len(parsed[key]) for key in ("Cz", "Dzu", "Dzw") if key in parsed), 0)
    samples = _assemble_block_batch(
        parsed["A"], parsed["B"], parsed["C"], parsed["D"], generalized, env,
        math.prod(dimensions),
        n=model.n_states, m=model.n_inputs, p_out=model.n_outputs, nw=nw, nz=nz,
    )

    if topology == "femt_simplicial":
        bases = [femt_svd_decompose(samples, rank=int(recipe["svd_rank"])).U_raw]
        final_bases = [np.asarray(spec["femt_mesh"]["nodal_weights"])]
        diagnostics = [recipe["hull_diagnostics"]]
    else:
        diagnostics = list(recipe["hull_diagnostics"])
        ranks = [int(axis["rank_before"]) for axis in diagnostics]
        original_bases = recipe.get("bases_pre_transform")
        if original_bases is not None:
            bases = [np.asarray(basis) for basis in original_bases]
        else:
            tensor = samples.reshape(*dimensions, *samples.shape[-2:])
            iterations = int((recipe.get("hooi") or {}).get("n_iter", 0))
            if iterations:
                bases = hooi_sampled_func(
                    tensor, ranks=ranks, max_iter=iterations, conv_tol=np.finfo(float).tiny,
                ).U_list
            else:
                bases = hosvd_sampled_func(tensor, ranks=ranks).U_list
        final_bases = [np.asarray(axis["weights_table"]) for axis in spec["tpmt_axes"]]

    if topology == "tpmt_interpolated" and recipe.get("projection_operators") is not None:
        return [grid.tolist() for grid in grids], [
            np.asarray(op, dtype=float).tolist() for op in recipe["projection_operators"]
        ]

    operators = []
    for axis, (basis, final, diag) in enumerate(zip(bases, final_bases, diagnostics)):
        mode = basis
        if topology == "tpmt_interpolated" and recipe.get("resample_points") is not None:
            _, mode = resample_basis_1d(
                grids[axis], basis, spec["tpmt_axes"][axis]["grid"], method=recipe["resample_method"],
            )
        operator = _hull_projection_operator(basis, mode, final, diag)
        operators.append(operator.tolist())

    return [grid.tolist() for grid in grids], operators


def _matrix_function(
    name: str,
    variables: list[str],
    parsed: dict[str, list[list[Any]]],
    *,
    matlab: bool,
) -> list[str]:
    """Emit the symbolic plant with positional inputs, avoiding user identifiers."""
    qs = {var: f"p({i + 1})" if matlab else f"p[{i}]" for i, var in enumerate(variables)}
    expressions = {
        key: [[_expression(entry.ast, qs, matlab=matlab) for entry in row] for row in matrix]
        for key, matrix in parsed.items()
    }
    if matlab:
        output = [f"function [{', '.join(expressions)}] = {name}(p)"]
        for key, matrix in expressions.items():
            output.append(f"    {key} = [" + "; ".join(", ".join(row) for row in matrix) + "];")
        return [*output, "end"]
    output = [f"def {name}(p):", "    return {"]
    for key, matrix in expressions.items():
        rows = ", ".join("[" + ", ".join(row) + "]" for row in matrix)
        output.append(f"        {key!r}: np.array([{rows}], dtype=float),")
    return [*output, "    }"]


_MATLAB_SYMBOLIC = """\
function y = sinc_rad(u)
    if abs(u) < 1e-4
        u2 = u*u;
        y = 1-u2/6+u2*u2/120;
    else
        y = sin(u)/u;
    end
end

function y = cos1m_div_u(u)
    if abs(u) < 1e-4
        u2 = u*u;
        y = u*(0.5-u2/24+u2*u2/720);
    else
        y = (1-cos(u))/u;
    end
end
"""

_PY_REPLAY = """\
def rebuild_vertices():
    nodes = itertools.product(*GRIDS)
    sampled = {}
    for point in nodes:
        for key, block in sample_plant(point).items():
            sampled.setdefault(key, []).append(block)
    vertices = {}
    for key, blocks in sampled.items():
        data = np.asarray(blocks)
        if METHOD == "femt_simplicial":
            vertices[key] = np.einsum("ij,jkl->ikl", OPERATORS[0], data)
        else:
            data = data.reshape(*(len(grid) for grid in GRIDS), *data.shape[-2:])
            for mode, operator in enumerate(OPERATORS):
                data = np.moveaxis(np.tensordot(operator, data, axes=(1, mode)), 0, mode)
            vertices[key] = data[tuple(INDICES.T)]
    return vertices
"""

_MATLAB_REPLAY = """\
function vertices = project_samples(samples, grids, operators, indices, is_femt)
    [n, m, n_nodes] = size(samples);
    if is_femt
        projected = operators{1} * reshape(samples, n*m, n_nodes).';
        vertices = reshape(projected.', n, m, size(projected,1));
        return
    end
    sizes = cellfun(@numel, grids);
    d = numel(sizes);
    % Mixed-radix enumeration has the last scheduling dimension varying fastest.
    data = reshape(samples, [n*m, fliplr(sizes)]);
    data = permute(data, [d+1:-1:2, 1]);
    for axis = 1:d
        order = [axis, 1:axis-1, axis+1:d+1];
        unfolded = permute(data, order);
        dimensions = [sizes, n*m];
        dimensions = dimensions(order);
        product = operators{axis} * reshape(unfolded, dimensions(1), []);
        dimensions(1) = size(product, 1);
        data = ipermute(reshape(product, dimensions), order);
        sizes(axis) = dimensions(1);
    end
    vertices = zeros(n, m, size(indices, 1));
    for r = 1:size(indices, 1)
        subs = num2cell(indices(r, :));
        vertices(:, :, r) = reshape(data(subs{:}, :), n, m);
    end
end
"""


def _matlab_matrix(rows: list[list[float]] | list[list[int]]) -> str:
    return "[" + "; ...\n".join(" ".join(repr(value) for value in row) for row in rows) + "]"


def export_ts_derivation_script(model: TSStateSpace, language: str) -> str:
    """Export a standalone Python or MATLAB replay of the selected TS derivation.

    The numerical rank and hull decisions are fixed to ensure that replay reproduces
    the exported representation independently of LAPACK/Qhull versions.
    """
    if not isinstance(language, str) or language not in {"python", "matlab"}:
        raise ValidationError("Select either 'python' or 'matlab' for the derivation script.")
    parsed = _parsed_matrices(model)
    spec = model.membership_spec
    method = spec.get("representation_kind")
    if method not in DERIVED_REPRESENTATIONS:
        raise ValidationError("Expected a sector, TPMT or FEMT derived TS model.")
    sector = method == "sector_nonlinearity"
    matlab = language == "matlab"

    if sector:
        premises = spec["sector_premises"]
        variables = [premise["name"] for premise in premises]
        sector_corners = [
            [float(premise["max" if bit == 0 else "min"]) for premise, bit in zip(premises, rule["bits"])]
            for rule in spec["functions"]
        ]
    else:
        variables = list(model.provenance["ts_derivation"]["active_variables"])
        grids, operators = _projection_operators(model, parsed)
        indices = (
            _list_of(rule["axis_basis_indices"] for rule in spec["functions"])
            if method == "tpmt_interpolated"
            else [[r] for r in range(model.n_vertices)]
        )

    sample_fn = _matrix_function("sample_plant", variables, parsed, matlab=matlab)
    title = "Rebuild TS vertex matrices from the original symbolic plant."
    replay_note = "The selected grid, rank and hull basis are fixed for reproducibility."
    if not matlab:
        lines = [f"# {title}", f"# {replay_note}", "import itertools", "import numpy as np", ""]
        lines.extend(emit_python_membership(model))
        lines.extend(sample_fn)
        if sector:
            lines.extend([
                f"CORNERS = {sector_corners!r}", "",
                "def rebuild_vertices():",
                "    sampled = [sample_plant(p) for p in CORNERS]",
                "    return {key: np.stack([row[key] for row in sampled]) for key in sampled[0]}",
            ])
        else:
            lines.extend([
                f"METHOD = {method!r}", f"GRIDS = {grids!r}",
                f"INDICES = np.array({indices!r}, dtype=int)",
                f"OPERATORS = [np.array(m) for m in {operators!r}]", _PY_REPLAY,
            ])
        lines.extend(["", "if __name__ == '__main__':", "    np.savez('ts_vertices.npz', **rebuild_vertices())", ""])
        return "\n".join(lines)

    lines = [f"% {title}", f"% {replay_note}"]
    keys = list(parsed)
    outputs = ", ".join(f"{key}_node" for key in keys)
    if sector:
        lines.extend([f"corners = {_matlab_matrix(sector_corners)};", "n_nodes = size(corners, 1);"])
    else:
        nr = ", ".join(_matlab_matrix(op) for op in operators)
        grid_rows = ", ".join(_matlab_matrix([grid]) for grid in grids)
        one_based = [[index + 1 for index in row] for row in indices]
        lines.extend([
            f"grids = {{{grid_rows}}};", f"operators = {{{nr}}};",
            f"indices = {_matlab_matrix(one_based)};", "sizes = cellfun(@numel, grids);",
            "n_nodes = prod(sizes);",
        ])
    lines.append("for q = 1:n_nodes")
    if sector:
        lines.append("    point = corners(q, :);")
    else:
        lines.extend([
            "    point = zeros(1, numel(grids));",
            "    remaining = q - 1;",
            "    for d = numel(grids):-1:1",
            "        point(d) = grids{d}(mod(remaining, sizes(d)) + 1);",
            "        remaining = floor(remaining / sizes(d));",
            "    end",
        ])
    lines.extend([f"    [{outputs}] = sample_plant(point);", "    if q == 1"])
    lines.extend(f"        {key}_samples = zeros([size({key}_node), n_nodes]);" for key in keys)
    lines.append("    end")
    lines.extend(f"    {key}_samples(:, :, q) = {key}_node;" for key in keys)
    lines.append("end")
    for key in keys:
        if sector:
            lines.append(f"{key}_vertices = {key}_samples;")
        else:
            is_femt = "true" if method == "femt_simplicial" else "false"
            lines.append(f"{key}_vertices = project_samples({key}_samples, grids, operators, indices, {is_femt});")
    names = ", ".join(f"'{key}_vertices'" for key in keys)
    lines.extend([f"save('ts_vertices.mat', {names});", "", *sample_fn, "", _MATLAB_SYMBOLIC])
    if not sector:
        lines.append(_MATLAB_REPLAY)
    return "\n".join(lines)
