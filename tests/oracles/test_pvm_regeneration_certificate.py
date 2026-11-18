"""Independent scalar-equation fixtures versus explicit PVM trajectory leaves."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from scripts.pvm_regeneration_certificate import assert_pvm_regeneration_matches_frozen_gold

ROOT = Path(__file__).resolve().parents[2]


def frozen():
    return json.loads((ROOT / "contracts/fixtures/B-PVM-LQR.json").read_text())


def test_fresh_generator_and_gold_pass_independent_scalar_certificate():
    reference = frozen()
    spec = importlib.util.spec_from_file_location(
        "pvm_gold_generator", ROOT / "scripts/generate_release_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    candidate = module.pvm()
    original = deepcopy(candidate)
    for value in (candidate, deepcopy(reference)):
        report = assert_pvm_regeneration_matches_frozen_gold(value, reference)
        assert report["cases"] == 4 and report["time_points_checked"] == 324
        assert report["independent_care_residual"] == 0
        assert report["max_ode_residual"] < 1e-12
    assert candidate == original and reference == frozen()


@pytest.mark.parametrize(
    "damage",
    [
        "time",
        "switch",
        "metadata",
        "dtype",
        "shape",
        "rank",
        "input",
        "tolerance",
        "numeric_string",
        "nested_data",
        "clip",
    ],
)
def test_noncomputed_fields_and_saturation_are_strict(damage):
    reference = frozen()
    candidate = deepcopy(reference)
    data = candidate["data"]
    if damage == "time":
        data["t"]["data"][10] += 1e-15
    elif damage == "switch":
        data["cases"][1]["expected"]["switch_times"][0] += 1e-15
    elif damage == "metadata":
        data["external_pathview_verified"] = True
    elif damage == "dtype":
        data["cases"][0]["expected"]["x"]["dtype"] = "float32"
    elif damage == "shape":
        data["cases"][0]["expected"]["x"]["shape"] = [2, 81]
    elif damage == "rank":
        data["cases"][0]["expected"]["x"]["shape"] = [162]
    elif damage == "input":
        data["A"]["data"][0] += 1e-15
    elif damage == "tolerance":
        candidate["tolerances"]["trajectory_atol"] *= 2
    elif damage == "numeric_string":
        data["cases"][0]["expected"]["x"]["data"][0] = "1.0"
    elif damage == "nested_data":
        data["cases"][0]["expected"]["x"]["data"] = [
            [v] for v in data["cases"][0]["expected"]["x"]["data"]
        ]
    else:
        data["cases"][1]["expected"]["u"]["data"][0] -= 1e-16
    with pytest.raises((AssertionError, ValueError)):
        assert_pvm_regeneration_matches_frozen_gold(candidate, reference)


@pytest.mark.parametrize("key", ["x", "u", "y"])
def test_close_but_incoherent_trajectory_is_rejected(key):
    reference = frozen()
    candidate = deepcopy(reference)
    candidate["data"]["cases"][0]["expected"][key]["data"][20] += (
        reference["tolerances"]["trajectory_atol"] / 4
    )
    with pytest.raises(AssertionError):
        assert_pvm_regeneration_matches_frozen_gold(candidate, reference)


@pytest.mark.parametrize("key", ["x", "u", "y"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_trajectories_fail_before_normalization(key, value):
    reference = frozen()
    candidate = deepcopy(reference)
    candidate["data"]["cases"][0]["expected"][key]["data"][20] = value
    with pytest.raises(AssertionError):
        assert_pvm_regeneration_matches_frozen_gold(candidate, reference)
