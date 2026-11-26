"""Numerical replay and scheduler tests for the two TS script export paths."""

import runpy
import subprocess
import sys

import numpy as np
import pytest

from control_lab.core.models import TSStateSpace
from control_lab.fuzzy.femt import derive_ts_femt
from control_lab.fuzzy.sector_nonlinearity import derive_ts_sector
from control_lab.fuzzy.tpmt import derive_ts_tpmt
from control_lab.fuzzy.ts_bridge import evaluate_ts_premise_weights
from control_lab.io.pvm import generate_pathsim_script
from control_lab.io.ts_derivation import export_ts_derivation_script


@pytest.fixture(params=[
    "sector", "tpmt", "tpmt-resampled", "tpmt-rank-deficient-grid", "femt-kuhn", "femt-delaunay",
])
def derived(request):
    bounds = {"x1": [-1, 1], "x2": [-0.5, 0.5]}
    a_matrix = [["-2 + 0.3*sin(x1)", "0.2*cos(x2)"], ["0.1*sin(x1)", "-1"]]
    b_matrix = [[1.0], [0.5]]
    generalized = {"Bw": [[0.2], [0.0]]}
    if request.param == "sector":
        result = derive_ts_sector(
            state_bounds=bounds, A_expr=[["-2 + 0.3*z1", "0.2*z2"], ["0.1*z1", "-1"]], B_expr=b_matrix,
            generalized_channels=generalized,
            premises=[
                {"name": "z1", "expression": "sin(x1)"},
                {"name": "z2", "expression": "cos(x2)"},
            ],
        )
    elif request.param.startswith("tpmt"):
        options = {}
        if request.param == "tpmt-resampled":
            options = {"resample_points": [5, 7], "resample_method": "pchip", "decomposition": "hooi"}
        ranks = [2, 2]
        if request.param == "tpmt-rank-deficient-grid":
            options = {"resample_points": [3, 5], "hull_type": "SN-NN"}
            ranks = [4, 2]
        result = derive_ts_tpmt(
            bounds, a_matrix, b_matrix, grid_points=9, ranks=ranks,
            generalized_channels=generalized, **options,
        )
    else:
        mesh = "delaunay" if request.param == "femt-delaunay" else "kuhn_delaunay"
        result = derive_ts_femt(
            bounds, a_matrix, b_matrix, mesh_kind=mesh, grid_points=7, rank=2,
            generalized_channels=generalized,
        )
    assert result.data is not None, result.error
    return TSStateSpace.from_dict(result.data["ts_state_space"])


def test_standalone_python_recomputes_all_vertices(derived, tmp_path):
    path = tmp_path / "derive.py"
    script = export_ts_derivation_script(derived, "python")
    assert "from control_lab" not in script
    path.write_text(script, encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(path)], cwd=tmp_path, check=True)
    with np.load(tmp_path / "ts_vertices.npz", allow_pickle=False) as output:
        for key in ("A", "B", "C", "D"):
            np.testing.assert_allclose(output[key], [v[key] for v in derived.vertices], atol=2e-9, rtol=0)
        generalized = derived.provenance["generalized_channels"]["vertices"]
        np.testing.assert_allclose(output["Bw"], [v["Bw"] for v in generalized], atol=2e-9, rtol=0)


def test_pathsim_weights_match_canonical_representation(derived, tmp_path):
    result = generate_pathsim_script(derived, None)
    assert result.data is not None, result.error
    path = tmp_path / "simulate.py"
    path.write_text(result.data["script"], encoding="utf-8")
    script = runpy.run_path(str(path))
    for state in ([0.0, 0.0], [0.29, 0.27], [-0.83, 0.43]):
        reference = evaluate_ts_premise_weights(derived, dict(zip(derived.state_names, state)))
        assert reference.data is not None, reference.error
        np.testing.assert_allclose(script["default_h_fn"](state), reference.data["weights"], atol=2e-10, rtol=0)


def test_derived_external_premise_reuses_generated_weights(tmp_path):
    result = derive_ts_sector(
        state_bounds={"x1": [-1, 1]}, A_expr=[["-2 + z"]], B_expr=[[1.0]],
        external_bounds={"v": [-1, 1]}, premises=[{"name": "z", "expression": "sinc_rad(v)"}],
    )
    assert result.data is not None, result.error
    model = TSStateSpace.from_dict(result.data["ts_state_space"])
    exported = generate_pathsim_script(model, None)
    assert exported.data is not None, exported.error
    path = tmp_path / "external.py"
    path.write_text(exported.data["script"], encoding="utf-8")
    script = runpy.run_path(str(path))
    weights = script["default_h_fn"]
    with pytest.raises(ValueError, match="external premise 'v'"):
        weights([0.0])
    value = 0.27
    expected = evaluate_ts_premise_weights(model, {"x1": 0.0, "v": value})
    assert expected.data is not None, expected.error
    np.testing.assert_allclose(weights([0.0], 0.2, {"v": lambda _: value}), expected.data["weights"])
    np.testing.assert_allclose(weights([0.0], 0.2, {"v": value}), expected.data["weights"])


def test_tpmt_recipe_preserves_and_reapplies_exact_projection_operators(tmp_path):
    result = derive_ts_tpmt(
        state_bounds={"x1": [-1.0, 1.0], "x2": [-0.8, 0.8]},
        A_expr=[["-2 + 0.4 * sin(x1 + x2)", "1"], ["0.5 * cos(x1 - x2)", "-3"]],
        B_expr=[["0"], ["1"]],
        grid_points=[9, 9],
        resample_points=[3, 3],
        hull_type="CNO",
    )
    assert result.data is not None, result.error
    model = TSStateSpace.from_dict(result.data["ts_state_space"])
    recipe = model.provenance["ts_derivation"]
    assert "projection_operators" in recipe
    assert len(recipe["projection_operators"]) == 2

    script = export_ts_derivation_script(model, "python")
    assert "from control_lab" not in script
    path = tmp_path / "derive_tpmt_exact_op.py"
    path.write_text(script, encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(path)], cwd=tmp_path, check=True)
    with np.load(tmp_path / "ts_vertices.npz", allow_pickle=False) as output:
        for key in ("A", "B", "C", "D"):
            np.testing.assert_allclose(output[key], [v[key] for v in model.vertices], atol=1e-12, rtol=0)

