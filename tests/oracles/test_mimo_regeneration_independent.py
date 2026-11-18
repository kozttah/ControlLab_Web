"""Independent adversarial F9 review of the fixed MIMO regeneration certificate.

Candidates mutate preserved bytes only in memory. No production scientific
function or fixture generator is used to manufacture expected values here.
"""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.mimo_regeneration_certificate import assert_mimo_regeneration_matches_frozen_gold

ROOT = Path(__file__).resolve().parents[2]


def gold():
    return json.loads((ROOT / "contracts/fixtures/B-MIMO-2x2.json").read_text())


def check(candidate, frozen):
    return assert_mimo_regeneration_matches_frozen_gold(candidate, frozen)


def test_independent_frozen_and_actual_ci_candidate_are_accepted_without_mutation():
    reference = gold()
    actual = json.loads((ROOT / "docs/audits/mimo-regeneration/candidate-from-ci.json").read_text())
    before, frozen_before = deepcopy(actual), deepcopy(reference)
    check(deepcopy(reference), reference)
    check(actual, reference)
    assert actual == before and reference == frozen_before


@pytest.mark.parametrize("field", ["G", "S", "T", "RGA", "singular_values", "crossing"])
def test_independent_frozen_criteria_remain_mandatory(field):
    reference = gold()
    actual = deepcopy(reference)
    expected = actual["data"]["expected"]
    if field == "singular_values":
        expected[field]["data"][0] += 2 * reference["tolerances"]["singular_values_atol"]
    elif field == "crossing":
        actual["data"]["multiple_crossings"]["gain_crossings"][0] += 2 * reference["tolerances"]["crossing_atol"]
    else:
        expected[field]["real"][0] += 2 * reference["tolerances"]["response_atol"]
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize("field", ["G", "S", "T", "RGA", "singular_values", "crossing"])
def test_independent_near_frozen_but_incoherent_results_are_rejected(field):
    reference = gold()
    actual = deepcopy(reference)
    expected = actual["data"]["expected"]
    if field == "singular_values":
        expected[field]["data"][0] += reference["tolerances"]["singular_values_atol"] / 2
    elif field == "crossing":
        actual["data"]["multiple_crossings"]["gain_crossings"][0] += reference["tolerances"]["crossing_atol"] / 2
    else:
        expected[field]["real"][0] += reference["tolerances"]["response_atol"] / 2
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


def test_independent_coordinated_s_t_damage_cannot_hide_behind_identity():
    reference = gold()
    actual = deepcopy(reference)
    expected = actual["data"]["expected"]
    delta = reference["tolerances"]["response_atol"] / 2
    expected["S"]["real"][0] += delta
    expected["T"]["real"][0] -= delta
    assert abs(expected["S"]["real"][0] + expected["T"]["real"][0] - 1) < 1e-15
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize("damage", ["small_relative_shift", "reorder", "negative", "zero_endpoint", "low_endpoint", "high_endpoint", "duplicate_crossing", "crossing_order"])
def test_independent_grid_and_crossing_contract_is_not_a_global_allclose(damage):
    reference = gold()
    actual = deepcopy(reference)
    omega = actual["data"]["omega"]["data"]
    crossings = actual["data"]["multiple_crossings"]["gain_crossings"]
    if damage == "small_relative_shift":
        omega[1] += 1e-12  # below response_atol, vastly above grid roundoff
    elif damage == "reorder":
        omega[9], omega[10] = omega[10], omega[9]
    elif damage == "negative":
        omega[4] = -omega[4]
    elif damage == "zero_endpoint":
        omega[0] = float(np.nextafter(0.0, np.inf))
    elif damage == "low_endpoint":
        omega[1] = float(np.nextafter(omega[1], np.inf))
    elif damage == "high_endpoint":
        omega[-1] = float(np.nextafter(omega[-1], np.inf))
    elif damage == "duplicate_crossing":
        crossings[1] = crossings[0]
    else:
        crossings.reverse()
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize("damage", ["input_ulp", "schema", "dtype", "order", "shape", "extra", "tolerance", "provenance", "singular_case", "numeric_string", "nested_values", "imaginary_boolean", "extra_imaginary", "identity_claim"])
def test_independent_structure_and_unenumerated_fields_remain_exact(damage):
    reference = gold()
    actual = deepcopy(reference)
    data = actual["data"]
    if damage == "input_ulp":
        data["C"]["data"][0] = float(np.nextafter(data["C"]["data"][0], np.inf))
    elif damage == "schema":
        actual["schema_version"] = "1.0.1"
    elif damage == "dtype":
        data["omega"]["dtype"] = "float32"
    elif damage == "order":
        data["omega"]["order"] = "F"
    elif damage == "shape":
        data["omega"]["shape"] = [31, 2]
    elif damage == "extra":
        data["expected"]["extra"] = 0.0
    elif damage == "tolerance":
        actual["tolerances"]["response_atol"] *= 2
    elif damage == "provenance":
        actual["provenance"]["lib_versions"]["numpy"] = "unknown"
    elif damage == "singular_case":
        data["singular_cases"][0]["expected_rga_status"] = "defined"
    elif damage == "numeric_string":
        data["omega"]["data"][5] = str(data["omega"]["data"][5])
    elif damage == "nested_values":
        data["expected"]["G"]["real"] = [[v] for v in data["expected"]["G"]["real"]]
    elif damage == "imaginary_boolean":
        data["expected"]["G"]["imag"][0] = False
    elif damage == "extra_imaginary":
        data["expected"]["G"]["imag"].append(0.0)
    else:
        data["expected"]["max_identity_residual"] = -1e-17
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["grid", "G", "singular_values", "crossing", "residual"])
def test_independent_nonfinite_leaves_are_rejected(field, bad):
    reference = gold()
    actual = deepcopy(reference)
    data = actual["data"]
    if field == "grid":
        data["omega"]["data"][8] = bad
    elif field == "G":
        data["expected"]["G"]["real"][8] = bad
    elif field == "singular_values":
        data["expected"]["singular_values"]["data"][8] = bad
    elif field == "crossing":
        data["multiple_crossings"]["gain_crossings"][0] = bad
    else:
        data["expected"]["max_identity_residual"] = bad
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)
