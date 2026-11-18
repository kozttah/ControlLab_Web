"""Independent F9 adversarial checks, using only preserved reference bytes.

These tests do not use the fixture generator or production estimator to create
expected values. Mutations remain in memory and never rewrite the gold.
"""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.arx_regeneration_certificate import assert_arx_regeneration_matches_frozen_gold

ROOT = Path(__file__).resolve().parents[2]


def frozen():
    return json.loads((ROOT / 'contracts/fixtures/B-ARX-PRBS.json').read_text())


def check(actual, reference):
    return assert_arx_regeneration_matches_frozen_gold(actual, reference)


def test_independent_preserved_gold_and_last_bit_changes_are_accepted():
    reference = frozen()
    check(deepcopy(reference), reference)
    actual = deepcopy(reference)
    expected = actual['data']['expected']
    for key in ('theta', 'singular_values'):
        expected[key]['data'] = [float(np.nextafter(x, np.inf)) for x in expected[key]['data']]
    for component in ('real', 'imag'):
        expected['poles'][component] = [float(np.nextafter(x, np.inf)) for x in expected['poles'][component]]
    for part in ('train', 'validation'):
        for mode in ('one_step_prediction', 'free_simulation'):
            expected['fit'][part][mode] = float(np.nextafter(expected['fit'][part][mode], np.inf))
            tensor = expected['predictions'][part][mode]
            tensor['data'] = [float(np.nextafter(x, np.inf)) for x in tensor['data']]
    check(actual, reference)


@pytest.mark.parametrize('field', ['theta', 'prediction', 'fit', 'pole'])
def test_independent_in_tolerance_but_incoherent_certificates_are_rejected(field):
    reference = frozen()
    actual = deepcopy(reference)
    expected = actual['data']['expected']
    tol = reference['tolerances']
    if field == 'theta':
        expected['theta']['data'][0] += tol['theta_atol'] / 2
    elif field == 'prediction':
        expected['predictions']['validation']['free_simulation']['data'][10] += tol['prediction_atol'] / 2
    elif field == 'fit':
        expected['fit']['validation']['one_step_prediction'] += tol['fit_atol'] / 2
    else:
        expected['poles']['real'][0] += tol['pole_atol'] / 2
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize('field', ['theta', 'prediction', 'fit', 'pole'])
def test_independent_existing_frozen_thresholds_remain_hard_limits(field):
    reference = frozen()
    actual = deepcopy(reference)
    expected = actual['data']['expected']
    tol = reference['tolerances']
    if field == 'theta':
        expected['theta']['data'][0] += 2 * tol['theta_atol']
    elif field == 'prediction':
        expected['predictions']['validation']['free_simulation']['data'][10] += 2 * tol['prediction_atol']
    elif field == 'fit':
        expected['fit']['validation']['one_step_prediction'] += 2 * tol['fit_atol']
    else:
        expected['poles']['real'][0] += 2 * tol['pole_atol']
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


def test_independent_svd_trace_preserving_corruption_is_rejected():
    reference = frozen()
    actual = deepcopy(reference)
    singular = actual['data']['expected']['singular_values']['data']
    first, second = singular[:2]
    singular[0] += 1e-5
    singular[1] = float(np.sqrt(first**2 + second**2 - singular[0]**2))
    # A mere Frobenius/trace comparison would miss this coordinated corruption.
    np.testing.assert_allclose(sum(x*x for x in singular),
                               sum(x*x for x in reference['data']['expected']['singular_values']['data']),
                               rtol=1e-15, atol=0)
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize('damage', ['input_ulp', 'dtype', 'order', 'shape', 'schema',
                                  'extra_expected', 'tolerance', 'rank', 'provenance'])
def test_independent_only_explicit_calculated_fields_may_vary(damage):
    reference = frozen()
    actual = deepcopy(reference)
    expected = actual['data']['expected']
    if damage == 'input_ulp':
        actual['data']['y']['data'][20] = float(np.nextafter(actual['data']['y']['data'][20], np.inf))
    elif damage == 'dtype':
        expected['theta']['dtype'] = 'float32'
    elif damage == 'order':
        expected['theta']['order'] = 'F'
    elif damage == 'shape':
        expected['theta']['shape'] = [2, 2]
    elif damage == 'schema':
        actual['schema_version'] = '1.0.1'
    elif damage == 'extra_expected':
        expected['unreviewed_numeric'] = 0.0
    elif damage == 'tolerance':
        actual['tolerances']['theta_atol'] *= 2
    elif damage == 'rank':
        expected['rank'] = 3
    else:
        actual['provenance']['lib_versions']['numpy'] = 'unknown'
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
@pytest.mark.parametrize('field', ['theta', 'singular_values', 'prediction', 'fit', 'pole'])
def test_independent_nonfinite_calculated_values_are_rejected(field, value):
    reference = frozen()
    actual = deepcopy(reference)
    expected = actual['data']['expected']
    if field in ('theta', 'singular_values'):
        expected[field]['data'][0] = value
    elif field == 'prediction':
        expected['predictions']['train']['one_step_prediction']['data'][10] = value
    elif field == 'fit':
        expected['fit']['train']['free_simulation'] = value
    else:
        expected['poles']['real'][0] = value
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)


@pytest.mark.parametrize('damage', [
    'theta_numeric_string', 'theta_nested_data', 'svd_numeric_string',
    'pole_zero_bool', 'pole_zero_integer', 'pole_extra_imag',
    'fit_numeric_string', 'prediction_numeric_string', 'prediction_nested_data',
])
def test_independent_numeric_normalization_cannot_hide_structural_damage(damage):
    reference = frozen()
    actual = deepcopy(reference)
    expected = actual['data']['expected']
    if damage == 'theta_numeric_string':
        expected['theta']['data'][0] = str(expected['theta']['data'][0])
    elif damage == 'theta_nested_data':
        expected['theta']['data'] = [[x] for x in expected['theta']['data']]
    elif damage == 'svd_numeric_string':
        expected['singular_values']['data'][0] = str(expected['singular_values']['data'][0])
    elif damage == 'pole_zero_bool':
        expected['poles']['imag'][0] = False
    elif damage == 'pole_zero_integer':
        expected['poles']['imag'][0] = 0
    elif damage == 'pole_extra_imag':
        expected['poles']['imag'].append(0.0)
    elif damage == 'fit_numeric_string':
        expected['fit']['validation']['free_simulation'] = str(
            expected['fit']['validation']['free_simulation'])
    elif damage == 'prediction_numeric_string':
        expected['predictions']['train']['one_step_prediction']['data'][0] = str(
            expected['predictions']['train']['one_step_prediction']['data'][0])
    else:
        tensor = expected['predictions']['train']['one_step_prediction']
        tensor['data'] = [[x] for x in tensor['data']]
    with pytest.raises((AssertionError, ValueError)):
        check(actual, reference)
