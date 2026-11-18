"""Producer mathematical/structural regression tests; gold never rewritten."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.mimo_regeneration_certificate import assert_mimo_regeneration_matches_frozen_gold

ROOT = Path(__file__).resolve().parents[2]


def frozen():
    return json.loads((ROOT / "contracts/fixtures/B-MIMO-2x2.json").read_text())


def test_gold_and_real_ci_candidate_are_certified_without_mutation():
    reference = frozen()
    for candidate in (
        deepcopy(reference),
        json.loads((ROOT / "docs/audits/mimo-regeneration/candidate-from-ci.json").read_text()),
    ):
        original = deepcopy(candidate)
        report = assert_mimo_regeneration_matches_frozen_gold(candidate, reference)
        assert report["grid_points"] == 62 and report["decimal_precision"] == 80
        assert report["max_grid_relative_error"] < 1e-13
        assert report["max_closed_form_error"] < 1e-13
        assert candidate == original and reference == frozen()


@pytest.mark.parametrize(
    "damage",
    [
        "grid",
        "zero",
        "endpoint",
        "order",
        "matrix",
        "shape",
        "dtype",
        "type",
        "tolerance",
        "extra",
        "identity",
        "crossing",
        "singular_case",
    ],
)
def test_named_calculated_leaves_do_not_hide_corruption(damage):
    reference = frozen()
    candidate = deepcopy(reference)
    data = candidate["data"]
    if damage == "grid":
        data["omega"]["data"][20] *= 1 + 1e-10
    elif damage == "zero":
        data["omega"]["data"][0] = 1e-20
    elif damage == "endpoint":
        data["omega"]["data"][-1] += 1e-10
    elif damage == "order":
        data["omega"]["data"][10:12] = data["omega"]["data"][10:12][::-1]
    elif damage == "matrix":
        data["C"]["data"][0] += 1e-15
    elif damage == "shape":
        data["expected"]["G"]["shape"] = [31, 4, 2]
    elif damage == "dtype":
        data["expected"]["singular_values"]["dtype"] = "float32"
    elif damage == "type":
        data["expected"]["G"]["real"][0] = str(data["expected"]["G"]["real"][0])
    elif damage == "tolerance":
        candidate["tolerances"]["response_atol"] *= 2
    elif damage == "extra":
        data["expected"]["new"] = 0.0
    elif damage == "identity":
        data["expected"]["max_identity_residual"] += 1e-12
    elif damage == "crossing":
        data["multiple_crossings"]["gain_crossings"][1] += (
            reference["tolerances"]["crossing_atol"] / 2
        )
    else:
        data["singular_cases"][0]["expected_rga_status"] = "success"
    with pytest.raises((AssertionError, ValueError)):
        assert_mimo_regeneration_matches_frozen_gold(candidate, reference)


@pytest.mark.parametrize("field", ["G", "S", "T", "RGA", "singular_values"])
def test_in_tolerance_but_false_formula_is_rejected(field):
    reference = frozen()
    candidate = deepcopy(reference)
    target = candidate["data"]["expected"][field]
    if field == "singular_values":
        target["data"][0] += reference["tolerances"]["singular_values_atol"] / 2
    else:
        target["real"][0] += reference["tolerances"]["response_atol"] / 2
    with pytest.raises(AssertionError):
        assert_mimo_regeneration_matches_frozen_gold(candidate, reference)
