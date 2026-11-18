"""Independent F9 adversarial review of the additive fixed PVM certificate.

Only in-memory candidates change. Frozen expected values, generator and
production PathView/simulation code are never rewritten or used as an oracle.
"""

from copy import deepcopy
import json
from pathlib import Path
import re

import numpy as np
import pytest

from scripts.pvm_regeneration_certificate import assert_pvm_regeneration_matches_frozen_gold

ROOT = Path(__file__).resolve().parents[2]


def gold():
    return json.loads((ROOT / "contracts/fixtures/B-PVM-LQR.json").read_text())


def check(actual, reference):
    return assert_pvm_regeneration_matches_frozen_gold(actual, reference)


def test_independent_gold_and_observed_simd_differences_are_accepted_without_mutation():
    reference = gold()
    actual = deepcopy(reference)
    differences = json.loads((ROOT / "docs/audits/mimo-regeneration/reviewer/pvm-simd-differences.json").read_text())["differences"]
    assert len(differences) == 10
    for difference in differences:
        tokens = [key if key else int(index) for key, index in re.findall(r"([A-Za-z_]+)|\[(\d+)\]", difference["path"])]
        node = actual
        for token in tokens[:-1]:
            node = node[token]
        assert node[tokens[-1]] == difference["frozen"]
        node[tokens[-1]] = difference["actual"]
    before, frozen_before = deepcopy(actual), deepcopy(reference)
    check(deepcopy(reference), reference)
    check(actual, reference)
    assert actual == before and reference == frozen_before


@pytest.mark.parametrize("case", range(4))
@pytest.mark.parametrize("field", ["x", "u", "y"])
def test_independent_near_frozen_but_incoherent_trajectory_is_rejected(case, field):
    reference = gold()
    actual = deepcopy(reference)
    actual["data"]["cases"][case]["expected"][field]["data"][20] += reference["tolerances"]["trajectory_atol"] / 2
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize("field", ["x", "u", "y"])
def test_independent_frozen_trajectory_tolerance_is_mandatory(field):
    reference = gold()
    actual = deepcopy(reference)
    actual["data"]["cases"][0]["expected"][field]["data"][20] += 2 * reference["tolerances"]["trajectory_atol"]
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize("criterion", ["trajectory_atol", "equation_atol"])
def test_independent_coordinated_state_control_output_damage_is_rejected(criterion):
    reference = gold()
    actual = deepcopy(reference)
    expected = actual["data"]["cases"][0]["expected"]
    delta = reference["tolerances"][criterion] / 2
    expected["x"]["data"][20] += delta
    expected["u"]["data"][20] -= delta
    expected["y"]["data"][20] += delta
    assert abs(expected["u"]["data"][20] - (0.4 - expected["x"]["data"][20])) < 1e-15
    assert expected["y"]["data"][20] == expected["x"]["data"][20]
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize("damage", ["time_ulp", "switch_ulp", "saturation", "saturation_limit", "C_ulp", "K_ulp", "reference_ulp", "dtype", "order", "shape", "numeric_string", "nested_data", "float_to_int", "extra", "tolerance", "gate_status", "external_flag"])
def test_independent_pvm_inputs_structure_and_maturity_flags_remain_exact(damage):
    reference = gold()
    actual = deepcopy(reference)
    data = actual["data"]
    case = data["cases"][1]
    if damage == "time_ulp":
        data["t"]["data"][10] = float(np.nextafter(data["t"]["data"][10], np.inf))
    elif damage == "switch_ulp":
        switches = case["expected"]["switch_times"]
        index = next(i for i, v in enumerate(switches) if v is not None)
        switches[index] = float(np.nextafter(switches[index], np.inf))
    elif damage == "saturation":
        case["saturation"]["enabled"] = False
    elif damage == "saturation_limit":
        case["saturation"]["u_max"] = 0.3
    elif damage in ("C_ulp", "K_ulp", "reference_ulp"):
        tensor = case["C"] if damage == "C_ulp" else data["K"] if damage == "K_ulp" else case["r"]
        tensor["data"][0] = float(np.nextafter(tensor["data"][0], np.inf))
    elif damage == "dtype":
        case["expected"]["x"]["dtype"] = "float32"
    elif damage == "order":
        case["expected"]["x"]["order"] = "F"
    elif damage == "shape":
        case["expected"]["x"]["shape"] = [162]
    elif damage == "numeric_string":
        case["expected"]["x"]["data"][0] = str(case["expected"]["x"]["data"][0])
    elif damage == "nested_data":
        case["expected"]["x"]["data"] = [[v] for v in case["expected"]["x"]["data"]]
    elif damage == "float_to_int":
        case["expected"]["x"]["data"][0] = 1
    elif damage == "extra":
        case["expected"]["extra"] = 0.0
    elif damage == "tolerance":
        actual["tolerances"]["equation_atol"] *= 2
    elif damage == "gate_status":
        data["gate_status"] = "ACCEPTED_BY_F9"
    else:
        data["external_pathview_verified"] = True
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["x", "u", "y"])
def test_independent_pvm_nonfinite_trajectories_are_rejected(field, value):
    reference = gold()
    actual = deepcopy(reference)
    actual["data"]["cases"][3]["expected"][field]["data"][10] = value
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)
