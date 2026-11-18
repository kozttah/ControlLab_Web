"""Producer checks of unchanged oracle limits and certificate non-mutation."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.arx_regeneration_certificate import assert_arx_regeneration_matches_frozen_gold


def _gold():
    return json.loads(
        (Path(__file__).resolve().parents[2] / "contracts/fixtures/B-ARX-PRBS.json").read_text()
    )


def test_arx_certificate_does_not_modify_arguments():
    reference = _gold()
    candidate = deepcopy(reference)
    before_candidate, before_reference = deepcopy(candidate), deepcopy(reference)
    diagnostic = assert_arx_regeneration_matches_frozen_gold(candidate, reference)
    assert candidate == before_candidate and reference == before_reference
    assert diagnostic["rows"] == 510 and diagnostic["columns"] == 4
    assert diagnostic["normal_residual"] < diagnostic["normal_roundoff_bound"]
    assert diagnostic["gram_spectrum_error"] < diagnostic["gram_roundoff_bound"]


@pytest.mark.parametrize("field", ["theta", "pole", "prediction", "fit"])
def test_arx_certificate_rejects_existing_frozen_limit_exceeded(field):
    reference = _gold()
    candidate = deepcopy(reference)
    expected, tol = candidate["data"]["expected"], reference["tolerances"]
    if field == "theta":
        expected["theta"]["data"][0] += 2 * tol["theta_atol"]
    elif field == "pole":
        expected["poles"]["real"][0] += 2 * tol["pole_atol"]
    elif field == "prediction":
        expected["predictions"]["train"]["one_step_prediction"]["data"][2] += (
            2 * tol["prediction_atol"]
        )
    else:
        expected["fit"]["train"]["free_simulation"] += 2 * tol["fit_atol"]
    with pytest.raises(AssertionError):
        assert_arx_regeneration_matches_frozen_gold(candidate, reference)


@pytest.mark.parametrize("field", ["t", "u", "clean_y", "innovations", "split", "noise", "prbs"])
def test_arx_certificate_keeps_all_deterministic_inputs_exact(field):
    reference = _gold()
    candidate = deepcopy(reference)
    data = candidate["data"]
    if field in {"t", "u", "clean_y", "innovations"}:
        data[field]["data"][2] += 1e-15
    elif field == "split":
        data["splits"]["validation"][0] += 1
    elif field == "noise":
        data["noise"]["innovation_scale"] += 1e-15
    else:
        data["prbs"]["initial_state"][0] = 0
    with pytest.raises(AssertionError):
        assert_arx_regeneration_matches_frozen_gold(candidate, reference)
