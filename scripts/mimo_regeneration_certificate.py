"""Independent, fixed-fixture MIMO regeneration certificate (F9 CPython QA).

No scientific production functions or generator results create the reference.
See docs/audits/mimo-regeneration/implementation/NUMERICAL_CERTIFICATE.md.
"""

from copy import deepcopy
from decimal import Decimal, localcontext
import math


def _structure(actual, reference):
    assert type(actual) is type(reference), "fixture structural type changed"
    if isinstance(reference, dict):
        assert actual.keys() == reference.keys(), "fixture keys changed"
        for key in reference:
            _structure(actual[key], reference[key])
    elif isinstance(reference, list):
        assert len(actual) == len(reference), "fixture length changed"
        for left, right in zip(actual, reference):
            _structure(left, right)
    elif isinstance(actual, float):
        assert math.isfinite(actual) and math.isfinite(reference), "nonfinite fixture value"


def _exact(actual, reference):
    _structure(actual, reference)
    if isinstance(reference, dict):
        for key in reference:
            _exact(actual[key], reference[key])
    elif isinstance(reference, list):
        for left, right in zip(actual, reference):
            _exact(left, right)
    else:
        assert actual == reference, "deterministic fixture field changed"


def _d(value):
    return Decimal.from_float(value) if isinstance(value, float) else Decimal(value)


def _gamma(count):
    unit = Decimal(2) ** -53
    return count * unit / (1 - count * unit)


def _add(a, b):
    return a[0] + b[0], a[1] + b[1]


def _mul(a, b):
    return a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0]


def _div(a, b):
    denominator = b[0] * b[0] + b[1] * b[1]
    assert denominator > 0, "singular independent complex division"
    return ((a[0] * b[0] + a[1] * b[1]) / denominator, (a[1] * b[0] - a[0] * b[1]) / denominator)


def _abs(z):
    return (z[0] * z[0] + z[1] * z[1]).sqrt()


def _distance(a, b):
    return _abs((a[0] - b[0], a[1] - b[1]))


def _complex(real=0, imag=0):
    return _d(real), _d(imag)


def _references(w):
    """Closed-form 2x2 adjugate, not inversion or numerical eigendecomposition."""
    z = _complex(1, w)
    h00, h11 = _complex(3, w), _complex(4, w)
    determinant = _add(_mul(h00, h11), _complex(Decimal("-0.5")))
    assert _abs(determinant) > 0
    # |det(H)|^2 = w^4 + 26*w^2 + 132.25, strictly positive at every grid point.
    det_identity = w**4 + 26 * w * w + Decimal("132.25")
    assert abs(determinant[0] ** 2 + determinant[1] ** 2 - det_identity) <= Decimal("1e-65") * max(
        1, det_identity
    )
    adjugate = [h11, _complex(-1), _complex(Decimal("-0.5")), h00]
    matrix = [Decimal(2), Decimal(1), Decimal("0.5"), Decimal(3)]
    g = [_div(_complex(value), z) for value in matrix]
    sensitivity = [_div(_mul(z, value), determinant) for value in adjugate]
    complementary = []
    for i in range(2):
        for j in range(2):
            numerator = _add(
                _mul(_complex(matrix[2 * i]), adjugate[j]),
                _mul(_complex(matrix[2 * i + 1]), adjugate[2 + j]),
            )
            complementary.append(_div(numerator, determinant))
    rga = [
        _complex(Decimal(12) / 11),
        _complex(-Decimal(1) / 11),
        _complex(-Decimal(1) / 11),
        _complex(Decimal(12) / 11),
    ]
    singular_zero = [((Decimal(57) + sign * Decimal(1313).sqrt()) / 8).sqrt() for sign in (1, -1)]
    singular = [value / (1 + w * w).sqrt() for value in singular_zero]
    return {"G": g, "S": sensitivity, "T": complementary, "RGA": rga}, singular


def _grid_certificate(values):
    assert len(values) == 62 and values[0] == 0.0
    assert values[1] == 0.001 and values[-1] == 1000.0, "grid endpoints changed"
    assert all(left < right for left, right in zip(values, values[1:])), "grid not increasing"
    logarithm = Decimal(10).ln()
    maximum_relative = Decimal(0)
    previous_log, previous_budget = None, None
    for k, value in enumerate(values[1:]):
        exponent = Decimal(-3) + Decimal(k) / 10
        reference = (exponent * logarithm).exp()
        # linspace: rounded division, multiplication and addition. The bound is
        # absolute, so cancellation near exponent zero is handled explicitly.
        exponent_budget = _gamma(3) * (3 + Decimal(k) / 10)
        # Declared supported pow/conversion accuracy envelope: two float64 ULPs.
        # This is a fixture-specific libm assumption, not an IEEE pow guarantee.
        conversion_budget = 2 * _d(math.ulp(float(reference)))
        budget = reference * ((logarithm * exponent_budget).exp() - 1) + conversion_budget
        error = abs(_d(value) - reference)
        assert error <= budget, "independent logspace grid certificate failed"
        maximum_relative = max(maximum_relative, error / reference)
        actual_log = _d(value).ln() / logarithm
        # A lower rounded value has a slightly larger inverse-log error. Use
        # -ln(1-r), valid here because r is strictly below one.
        log_budget = exponent_budget - (1 - conversion_budget / reference).ln() / logarithm
        assert abs(actual_log - exponent) <= log_budget, "grid exponent certificate failed"
        if previous_log is not None:
            assert abs(actual_log - previous_log - Decimal("0.1")) <= log_budget + previous_budget
        previous_log, previous_budget = actual_log, log_budget
    return maximum_relative


def _pair(tensor, index):
    return _d(tensor["real"][index]), _d(tensor["imag"][index])


def _roundoff(reference, operations):
    magnitude = _abs(reference) if isinstance(reference, tuple) else abs(reference)
    return _gamma(operations) * max(Decimal(1), magnitude)


def _grid_propagation(left, right):
    delta = abs(left - right)
    low, high = min(left, right), max(left, right)
    # H=(1+j*w)I+M; adjugate Frobenius bound over the tiny frequency interval.
    inverse_bound = (2 * high * high + Decimal("26.25")).sqrt() / (
        low**4 + 26 * low * low + Decimal("132.25")
    ).sqrt()
    st_derivative = inverse_bound + (1 + high * high).sqrt() * inverse_bound * inverse_bound
    sigma_zero = ((Decimal(57) + Decimal(1313).sqrt()) / 8).sqrt()
    return {
        "G": delta * 3 / (1 + low * low),
        "S": delta * st_derivative,
        "T": delta * st_derivative,
        "RGA": Decimal(0),
        "singular_values": delta * sigma_zero * high / (1 + low * low) ** Decimal("1.5"),
    }


def _polynomial(z):
    return ((z - Decimal("199.95")) * z + Decimal("9877.0004")) * z - 21


def _crossings_certificate(actual, reference, tolerance):
    assert len(actual) == 3 and all(a < b for a, b in zip(actual, actual[1:]))
    maximum = Decimal(0)
    # Three disjoint sign-changing intervals give all three roots of a cubic.
    for value, frozen, endpoints in zip(actual, reference, ((0, 1), (81, 100), (100, 121))):
        lo, hi = map(Decimal, endpoints)
        assert _polynomial(lo) * _polynomial(hi) < 0
        for _ in range(240):
            middle = (lo + hi) / 2
            if _polynomial(lo) * _polynomial(middle) <= 0:
                hi = middle
            else:
                lo = middle
        root = ((lo + hi) / 2).sqrt()
        w = _d(value)
        z = w * w
        derivative = abs(2 * w * (3 * z * z - Decimal("399.9") * z + Decimal("9877.0004")))
        assert derivative > 0
        terms = z**3 + Decimal("199.95") * z * z + Decimal("9877.0004") * z + 21
        # A scaled polynomial backward-error envelope controls the root error;
        # the independent high-precision isolated root also prevents duplicates.
        budget = _gamma(128) * terms / derivative + 4 * _d(math.ulp(float(root)))
        error = abs(w - root)
        assert error <= budget, "independent gain-crossing root certificate failed"
        assert abs(w - _d(frozen)) <= tolerance, "frozen crossing tolerance exceeded"
        assert abs(_polynomial(z)) <= _gamma(128) * terms, "crossing polynomial residual failed"
        maximum = max(maximum, error)
    return maximum


def assert_mimo_regeneration_matches_frozen_gold(generated, saved):
    """Validate only named computed fields; never mutate candidate or gold."""
    _structure(generated, saved)
    assert saved["fixture_id"] == "B-MIMO-2x2"
    normalized = deepcopy(generated)
    ndata, frozen_data = normalized["data"], saved["data"]
    ndata["omega"]["data"] = deepcopy(frozen_data["omega"]["data"])
    for key in ("G", "RGA", "S", "T"):
        for component in ("real", "imag"):
            ndata["expected"][key][component] = deepcopy(frozen_data["expected"][key][component])
    ndata["expected"]["singular_values"]["data"] = deepcopy(
        frozen_data["expected"]["singular_values"]["data"]
    )
    ndata["expected"]["max_identity_residual"] = frozen_data["expected"]["max_identity_residual"]
    ndata["multiple_crossings"]["gain_crossings"] = deepcopy(
        frozen_data["multiple_crossings"]["gain_crossings"]
    )
    _exact(normalized, saved)
    with localcontext() as context:
        context.prec = 80
        data, frozen = generated["data"], saved["data"]
        tolerance = saved["tolerances"]
        grid_error = _grid_certificate(data["omega"]["data"])
        _grid_certificate(frozen["omega"]["data"])
        maximum_error, maximum_identity, maximum_propagation = Decimal(0), Decimal(0), Decimal(0)
        matrix = [Decimal(2), Decimal(1), Decimal("0.5"), Decimal(3)]
        assert matrix[0] * matrix[3] - matrix[1] * matrix[2] == Decimal("5.5")
        for case in data["singular_cases"]:
            a, b, c, d = map(_d, case["matrix"]["data"])
            assert a * d - b * c == 0 and case["expected_rga_status"] == "undefined"
        for i, (value, frozen_value) in enumerate(
            zip(data["omega"]["data"], frozen["omega"]["data"])
        ):
            w, fw = _d(value), _d(frozen_value)
            refs, singular = _references(w)
            frozen_refs, frozen_singular = _references(fw)
            propagation = _grid_propagation(w, fw)
            maximum_propagation = max(maximum_propagation, *propagation.values())
            for key in ("G", "RGA", "S", "T"):
                for j in range(4):
                    actual = _pair(data["expected"][key], 4 * i + j)
                    old = _pair(frozen["expected"][key], 4 * i + j)
                    ref = refs[key][j]
                    old_ref = frozen_refs[key][j]
                    budget = _roundoff(ref, 64)
                    old_budget = _roundoff(old_ref, 64)
                    error = _distance(actual, ref)
                    assert error <= budget, f"independent {key} formula certificate failed"
                    assert _distance(old, old_ref) <= old_budget, (
                        "frozen formula certificate failed"
                    )
                    difference = _distance(actual, old)
                    assert difference <= _d(tolerance["response_atol"]), (
                        "frozen response tolerance exceeded"
                    )
                    assert difference <= budget + old_budget + propagation[key], (
                        "grid response propagation failed"
                    )
                    maximum_error = max(maximum_error, error)
                    if key == "S":
                        complementary = _pair(data["expected"]["T"], 4 * i + j)
                        total = _add(actual, complementary)
                        identity = _distance(total, _complex(1 if j in (0, 3) else 0))
                        assert identity <= _d(tolerance["identity_atol"])
                        assert identity <= budget + _roundoff(refs["T"][j], 64)
                        maximum_identity = max(maximum_identity, identity)
            for j in range(2):
                actual = _d(data["expected"]["singular_values"]["data"][2 * i + j])
                old = _d(frozen["expected"]["singular_values"]["data"][2 * i + j])
                assert actual > 0
                budget, old_budget = _roundoff(singular[j], 32), _roundoff(frozen_singular[j], 32)
                assert abs(actual - singular[j]) <= budget, (
                    "independent singular-value certificate failed"
                )
                assert abs(old - frozen_singular[j]) <= old_budget
                assert abs(actual - old) <= _d(tolerance["singular_values_atol"])
                assert abs(actual - old) <= budget + old_budget + propagation["singular_values"]
            assert (
                data["expected"]["singular_values"]["data"][2 * i]
                >= data["expected"]["singular_values"]["data"][2 * i + 1]
            )
        reported = _d(data["expected"]["max_identity_residual"])
        assert 0 <= reported <= _d(tolerance["identity_atol"])
        assert abs(reported - maximum_identity) <= _gamma(8), (
            "reported identity certificate incoherent"
        )
        crossing_error = _crossings_certificate(
            data["multiple_crossings"]["gain_crossings"],
            frozen["multiple_crossings"]["gain_crossings"],
            _d(tolerance["crossing_atol"]),
        )
        return {
            "decimal_precision": context.prec,
            "grid_points": 62,
            "max_grid_relative_error": float(grid_error),
            "max_closed_form_error": float(maximum_error),
            "max_identity_residual": float(maximum_identity),
            "max_grid_propagation_bound": float(maximum_propagation),
            "max_crossing_reference_error": float(crossing_error),
            "pow_accuracy_assumption": "two ULP float64, fixture-specific supported libm envelope",
        }
