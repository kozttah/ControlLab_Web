"""Independent, fixture-specific ARX regeneration certificate (F9 only).

Never imports control_lab or the fixture generator. Frozen inputs/metadata remain
exact; only explicitly enumerated computed output leaves may differ numerically.
See docs/audits/arx-regeneration/NUMERICAL_CERTIFICATE.md for the error budgets.
"""

from copy import deepcopy
from decimal import Decimal, localcontext
import math

import numpy as np


def _finite_tree(value):
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item)
    elif isinstance(value, float):
        assert math.isfinite(value), "nonfinite fixture value"


def _exact(actual, reference):
    assert type(actual) is type(reference), "fixture structural type changed"
    if isinstance(reference, dict):
        assert actual.keys() == reference.keys(), "fixture keys changed"
        for key in reference:
            _exact(actual[key], reference[key])
    elif isinstance(reference, list):
        assert len(actual) == len(reference), "fixture length changed"
        for left, right in zip(actual, reference):
            _exact(left, right)
    else:
        assert actual == reference, "deterministic fixture field changed"


def _structure(actual, reference):
    """Reject coercible malformed values before numeric leaves are normalized."""
    assert type(actual) is type(reference), "fixture structural type changed"
    if isinstance(reference, dict):
        assert actual.keys() == reference.keys(), "fixture keys changed"
        for key in reference:
            _structure(actual[key], reference[key])
    elif isinstance(reference, list):
        assert len(actual) == len(reference), "fixture length changed"
        for left, right in zip(actual, reference):
            _structure(left, right)


def _d(value):
    return Decimal.from_float(float(value))


def _gamma(operations):
    unit = np.finfo(float).eps / 2
    assert operations * unit < 1
    return operations * unit / (1 - operations * unit)


def _norm(vector):
    return sum((value * value for value in vector), Decimal(0)).sqrt()


def _array(tensor):
    return np.asarray(tensor["data"], dtype=float).reshape(tensor["shape"])


def _gram_eigenvalues(gram):
    """60-digit Jacobi diagonalization of the 4x4 symmetric normal matrix."""
    matrix = deepcopy(gram)
    n = len(matrix)
    scale = max(abs(value) for row in matrix for value in row)
    cutoff = scale * Decimal("1e-45")
    for _ in range(200):
        p, q = max(
            ((i, j) for i in range(n) for j in range(i + 1, n)),
            key=lambda pair: abs(matrix[pair[0]][pair[1]]),
        )
        if abs(matrix[p][q]) <= cutoff:
            break
        tau = (matrix[q][q] - matrix[p][p]) / (2 * matrix[p][q])
        tangent = (1 if tau >= 0 else -1) / (abs(tau) + (1 + tau * tau).sqrt())
        cosine = 1 / (1 + tangent * tangent).sqrt()
        sine = tangent * cosine
        app, aqq, apq = matrix[p][p], matrix[q][q], matrix[p][q]
        for k in range(n):
            if k not in (p, q):
                left, right = matrix[k][p], matrix[k][q]
                matrix[k][p] = matrix[p][k] = cosine * left - sine * right
                matrix[k][q] = matrix[q][k] = sine * left + cosine * right
        matrix[p][p] = app - tangent * apq
        matrix[q][q] = aqq + tangent * apq
        matrix[p][q] = matrix[q][p] = Decimal(0)
    else:
        raise AssertionError("independent Decimal Gram eigensolver did not converge")
    # Gershgorin residual is below 3e-45*scale, negligible versus float64 budgets.
    assert max(sum(abs(matrix[i][j]) for j in range(n) if i != j) for i in range(n)) <= n * cutoff
    return sorted((matrix[i][i] for i in range(n)), reverse=True)


def _prediction(u, y, theta, free):
    prediction = y.copy()
    local_error = Decimal(0)
    for k in range(2, len(y)):
        past = prediction if free else y
        terms = [
            -theta[0] * past[k - 1],
            -theta[1] * past[k - 2],
            theta[2] * u[k - 1],
            theta[3] * u[k - 2],
        ]
        prediction[k] = sum(terms, Decimal(0))
        local_error = max(local_error, sum(map(abs, terms)))
    amplification = Decimal(1)
    if free:
        h_previous, h_current = Decimal(0), Decimal(1)
        amplification = Decimal(0)
        for _ in range(len(y) - 2):
            amplification += abs(h_current)
            h_previous, h_current = h_current, -theta[0] * h_current - theta[1] * h_previous
    # Four products + three sums; include final float64 conversion of the
    # high-precision reference and the local-error bound's own rounding.
    budget = float(Decimal.from_float(_gamma(7)) * local_error * amplification)
    budget += np.finfo(float).eps * max(1, max(abs(float(v)) for v in prediction))
    return prediction, budget


def assert_arx_regeneration_matches_frozen_gold(generated, saved):
    """Validate ARX regeneration without editing either input or frozen criteria.

    Returns certificate diagnostics for audit logs. Assertion failure is mandatory
    for nonfinite, structural, numerical-oracle or independent-certificate faults.
    """
    _structure(generated, saved)
    _finite_tree(generated)
    _finite_tree(saved)
    actual = deepcopy(generated)
    assert saved["fixture_id"] == "B-ARX-PRBS"
    expected, frozen = actual["data"]["expected"], saved["data"]["expected"]
    tolerance = saved["tolerances"]

    def tensor(key, atol):
        np.testing.assert_allclose(_array(expected[key]), _array(frozen[key]), rtol=0, atol=atol)
        expected[key]["data"] = deepcopy(frozen[key]["data"])

    tensor("theta", tolerance["theta_atol"])
    for component in ("real", "imag"):
        np.testing.assert_allclose(
            expected["poles"][component],
            frozen["poles"][component],
            rtol=0,
            atol=tolerance["pole_atol"],
        )
        expected["poles"][component] = deepcopy(frozen["poles"][component])
    for part in ("train", "validation"):
        for mode in ("one_step_prediction", "free_simulation"):
            np.testing.assert_allclose(
                expected["fit"][part][mode],
                frozen["fit"][part][mode],
                rtol=0,
                atol=tolerance["fit_atol"],
            )
            expected["fit"][part][mode] = frozen["fit"][part][mode]
            target = expected["predictions"][part][mode]
            reference = frozen["predictions"][part][mode]
            np.testing.assert_allclose(
                _array(target), _array(reference), rtol=0, atol=tolerance["prediction_atol"]
            )
            target["data"] = deepcopy(reference["data"])
    # Singular values have no frozen atol. Their certificate is checked below;
    # replace only data, never shape/dtype/order or any other metadata.
    expected["singular_values"]["data"] = deepcopy(frozen["singular_values"]["data"])
    _exact(actual, saved)

    with localcontext() as context:
        context.prec = 60
        data = saved["data"]
        output = generated["data"]["expected"]
        u, y = [[_d(v) for v in _array(data[key]).ravel()] for key in ("u", "y")]
        theta = [_d(v) for v in _array(output["theta"]).ravel()]
        start, end = data["splits"]["train"]
        assert start == 0 and data["na"] == data["nb"] == 2 and data["nk"] == 1
        phi = [[-y[k - 1], -y[k - 2], u[k - 1], u[k - 2]] for k in range(2, end)]
        target = y[2:end]
        m, n = len(phi), 4
        gram = [
            [sum((row[i] * row[j] for row in phi), Decimal(0)) for j in range(n)] for i in range(n)
        ]
        eigenvalues = _gram_eigenvalues(gram)
        norm_phi = sum((gram[i][i] for i in range(n)), Decimal(0)).sqrt()
        assert eigenvalues[-1] > 0 and output["rank"] == n
        singular = [_d(v) for v in _array(output["singular_values"]).ravel()]
        assert len(singular) == n and all(s > 0 for s in singular)
        assert singular == sorted(singular, reverse=True)
        gram_budget = _d(_gamma(m + 8 * n)) * norm_phi * norm_phi
        sv_error = max(abs(s * s - value) for s, value in zip(singular, eigenvalues))
        assert sv_error <= gram_budget, "singular-value independent Gram certificate failed"
        # Positive definite normal matrix + stationary residual certifies the
        # unique OLS optimum. All sums here are independent 60-digit arithmetic.
        residual = [
            sum((a * b for a, b in zip(row, theta)), Decimal(0)) - value
            for row, value in zip(phi, target)
        ]
        gradient = [
            sum((row[j] * value for row, value in zip(phi, residual)), Decimal(0)) for j in range(n)
        ]
        normal_budget = _d(_gamma(m + 8 * n)) * (
            norm_phi * norm_phi * _norm(theta) + norm_phi * _norm(target)
        )
        normal_error = _norm(gradient)
        assert normal_error <= normal_budget, "independent OLS stationarity certificate failed"
        for real, imag in zip(output["poles"]["real"], output["poles"]["imag"]):
            z = complex(real, imag)
            a, b = map(float, theta[:2])
            poly_error = abs(z * z + a * z + b)
            poly_budget = _gamma(8) * (abs(z) ** 2 + abs(a * z) + abs(b))
            assert poly_error <= poly_budget, "independent ARX pole polynomial failed"
        for part in ("train", "validation"):
            begin, stop = data["splits"][part]
            part_u, part_y = u[begin:stop], y[begin:stop]
            for mode in ("one_step_prediction", "free_simulation"):
                prediction, prediction_budget = _prediction(
                    part_u, part_y, theta, mode == "free_simulation"
                )
                np.testing.assert_allclose(
                    _array(output["predictions"][part][mode]).ravel(),
                    [float(value) for value in prediction],
                    rtol=0,
                    atol=prediction_budget,
                    err_msg="independent ARX recurrence certificate failed",
                )
                measured, estimated = part_y[2:], prediction[2:]
                mean = sum(measured, Decimal(0)) / len(measured)
                denominator = _norm([value - mean for value in measured])
                numerator = _norm(
                    [value - estimate for value, estimate in zip(measured, estimated)]
                )
                assert denominator > 0
                fit = float(100 * (1 - numerator / denominator))
                ratio = float(numerator / denominator)
                fit_budget = 100 * (
                    math.sqrt(len(measured)) * prediction_budget / float(denominator)
                    + _gamma(8 * len(measured) + 32)
                    * (1 + ratio)
                    * (1 + float(_norm(measured) / denominator))
                )
                assert abs(output["fit"][part][mode] - fit) <= fit_budget, (
                    "independent ARX FIT certificate failed"
                )
        return {
            "rows": m,
            "columns": n,
            "decimal_precision": context.prec,
            "normal_residual": float(normal_error),
            "normal_roundoff_bound": float(normal_budget),
            "gram_spectrum_error": float(sv_error),
            "gram_roundoff_bound": float(gram_budget),
            "normal_condition": float(eigenvalues[0] / eigenvalues[-1]),
        }
