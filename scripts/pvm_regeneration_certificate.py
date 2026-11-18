"""Independent fixed PVM closed-form regeneration certificate, F9 CPython QA.

Only trajectory leaves may round differently. No production simulator, CARE
solver or fixture generator is imported to manufacture expected trajectories.
"""

from copy import deepcopy
from decimal import Decimal, localcontext
import math

from scripts.mimo_regeneration_certificate import _d, _exact, _gamma, _structure


def _clip(value, lower, upper):
    return min(upper, max(lower, value))


def _rows(tensor):
    rows, columns = tensor["shape"]
    return [[_d(v) for v in tensor["data"][i * columns : (i + 1) * columns]] for i in range(rows)]


def _parameters(a, v, initial, enabled, lower, upper, stored_switch):
    equilibrium = v / (1 - a)
    result = {
        "a": a,
        "v": v,
        "initial": initial,
        "equilibrium": equilibrium,
        "saturated": enabled and not lower <= v - initial <= upper,
        "switch": None,
        "switch_budget": Decimal(0),
    }
    if not result["saturated"]:
        assert stored_switch is None, "unexpected switching time"
        return result
    saturated_u = _clip(v - initial, lower, upper)
    equilibrium_sat = -saturated_u / a
    threshold = v - saturated_u
    numerator, denominator = threshold - equilibrium_sat, initial - equilibrium_sat
    assert numerator / denominator > 0
    logarithm = (numerator / denominator).ln()
    switch = logarithm / a
    assert switch > 0 and isinstance(stored_switch, float)
    # Error of the rounded numerator/denominator is propagated through ln, not
    # hidden in a universal time atol. The stored switch remains exactly frozen.
    relative_n = _gamma(4) * (abs(v) + abs(saturated_u) + abs(equilibrium_sat)) / abs(numerator)
    relative_d = _gamma(2) * (abs(initial) + abs(equilibrium_sat)) / abs(denominator)
    assert relative_n < 1 and relative_d < 1
    log_error = -(1 - relative_n).ln() - (1 - relative_d).ln()
    log_error += 2 * _d(math.ulp(float(logarithm)))
    switch_budget = log_error / abs(a) + _gamma(1) * abs(switch)
    assert abs(_d(stored_switch) - switch) <= switch_budget, (
        "stored switch inconsistent with closed form"
    )
    at_switch = equilibrium_sat + (initial - equilibrium_sat) * (a * switch).exp()
    assert abs(at_switch - threshold) <= Decimal("1e-65") * max(1, abs(threshold)), (
        "switch continuity failed"
    )
    assert lower <= v - equilibrium <= upper, "fixture requires more than one saturation switch"
    result.update(
        saturated_u=saturated_u,
        equilibrium_sat=equilibrium_sat,
        threshold=threshold,
        switch=switch,
        switch_budget=switch_budget,
    )
    return result


def _state(parameters, time):
    a = parameters["a"]
    switch = parameters["switch"]
    if parameters["saturated"] and time <= switch:
        equilibrium = parameters["equilibrium_sat"]
        coefficient = parameters["initial"] - equilibrium
        rate, shift, shift_budget = a, Decimal(0), Decimal(0)
    else:
        equilibrium = parameters["equilibrium"]
        coefficient = (
            parameters["threshold"] if parameters["saturated"] else parameters["initial"]
        ) - equilibrium
        rate = a - 1
        shift = switch if parameters["saturated"] else Decimal(0)
        shift_budget = parameters["switch_budget"] if parameters["saturated"] else Decimal(0)
    argument = rate * (time - shift)
    exponential = argument.exp()
    value = equilibrium + coefficient * exponential
    derivative = rate * coefficient * exponential
    # Rounded subtraction/multiplication in the exponent, and independently
    # bounded stored-switch arithmetic; exp accuracy is declared at two ULPs.
    argument_budget = _gamma(4) * (abs(rate) * (abs(time) + abs(shift)) + abs(argument))
    argument_budget += abs(rate) * shift_budget
    exponential_budget = exponential * (argument_budget.exp() - 1) + 2 * _d(
        math.ulp(float(exponential))
    )
    scale = (
        abs(equilibrium)
        + abs(coefficient) * exponential
        + abs(parameters["initial"])
        + abs(parameters["v"])
    )
    budget = _gamma(16) * max(1, scale) + abs(coefficient) * exponential_budget
    return value, derivative, budget


def assert_pvm_regeneration_matches_frozen_gold(generated, saved):
    """Check fixed scalar piecewise ODEs and exact schema before normalization."""
    _structure(generated, saved)
    assert saved["fixture_id"] == "B-PVM-LQR"
    normalized = deepcopy(generated)
    for actual, frozen in zip(normalized["data"]["cases"], saved["data"]["cases"]):
        for key in ("x", "u", "y"):
            actual["expected"][key]["data"] = deepcopy(frozen["expected"][key]["data"])
    _exact(normalized, saved)
    with localcontext() as context:
        context.prec = 80
        data, frozen_data, tolerance = generated["data"], saved["data"], saved["tolerances"]
        A, B, Q, R, K, P = [_rows(data[key]) for key in ("A", "B", "Q", "R", "K", "P")]
        identity = [[Decimal(1), Decimal(0)], [Decimal(0), Decimal(1)]]
        assert B == R == K == P == identity
        assert A == [[Decimal(-1), Decimal(0)], [Decimal(0), Decimal(-2)]]
        assert Q == [[Decimal(3), Decimal(0)], [Decimal(0), Decimal(5)]]
        # Here R=B=P=I, so CARE is A.T + A - K.T K + Q = 0.
        care_error = max(
            abs(A[j][i] + A[i][j] - sum(K[k][i] * K[k][j] for k in range(2)) + Q[i][j])
            for i in range(2)
            for j in range(2)
        )
        gain_error = max(abs(K[i][j] - P[i][j]) for i in range(2) for j in range(2))
        assert care_error <= _d(tolerance["equation_atol"])
        assert gain_error <= _d(tolerance["gain_atol"])
        time = [_d(v) for v in data["t"]["data"]]
        assert len(time) == 81 and time[0] == 0 and time[-1] == 4
        assert all(a < b for a, b in zip(time, time[1:]))
        initial = [_d(v) for v in data["x0"]["data"]]
        maximum_state_error, maximum_equation_error = Decimal(0), Decimal(0)
        maximum_budget, maximum_switch_error = Decimal(0), Decimal(0)
        points = 0
        for case, frozen_case in zip(data["cases"], frozen_data["cases"]):
            C, D, N, reference = [_rows(case[key]) for key in ("C", "D", "reference_map", "r")]
            assert all(row == reference[0] for row in reference), (
                "reference must be constant in this fixture"
            )
            assert all(value == 0 for row in D for value in row)
            v = [sum(a * b for a, b in zip(row, reference[0])) for row in N]
            lower, upper = map(_d, (case["saturation"]["u_min"], case["saturation"]["u_max"]))
            enabled = case["saturation"]["enabled"]
            parameters = [
                _parameters(
                    A[i][i],
                    v[i],
                    initial[i],
                    enabled,
                    lower,
                    upper,
                    case["expected"]["switch_times"][i],
                )
                for i in range(2)
            ]
            for i, p in enumerate(parameters):
                if p["switch"] is not None:
                    maximum_switch_error = max(
                        maximum_switch_error,
                        abs(_d(case["expected"]["switch_times"][i]) - p["switch"]),
                    )
            actual_x, actual_u, actual_y = [_rows(case["expected"][key]) for key in ("x", "u", "y")]
            frozen = {key: _rows(frozen_case["expected"][key]) for key in ("x", "u", "y")}
            for k, t in enumerate(time):
                states = [_state(p, t) for p in parameters]
                for i, (x, derivative, state_budget) in enumerate(states):
                    u = _clip(v[i] - x, lower, upper) if enabled else v[i] - x
                    raw_budget = _gamma(4) * max(1, abs(v[i]) + abs(x))
                    control_budget = state_budget + raw_budget
                    error_x = abs(actual_x[k][i] - x)
                    assert error_x <= state_budget, (
                        "independent PVM state trajectory certificate failed"
                    )
                    assert abs(actual_u[k][i] - u) <= control_budget, (
                        "independent PVM control certificate failed"
                    )
                    actual_control = (
                        _clip(v[i] - actual_x[k][i], lower, upper)
                        if enabled
                        else v[i] - actual_x[k][i]
                    )
                    assert abs(actual_u[k][i] - actual_control) <= raw_budget, (
                        "PVM control law inconsistent"
                    )
                    if enabled:
                        assert lower <= actual_u[k][i] <= upper, "actuator bounds violated"
                    equation = abs(A[i][i] * actual_x[k][i] + actual_u[k][i] - derivative)
                    assert equation <= _d(tolerance["equation_atol"])
                    assert equation <= abs(A[i][i]) * state_budget + control_budget
                    maximum_equation_error = max(maximum_equation_error, equation)
                    maximum_state_error = max(maximum_state_error, error_x)
                    maximum_budget = max(maximum_budget, state_budget, control_budget)
                for j, row in enumerate(C):
                    y = sum(coefficient * state[0] for coefficient, state in zip(row, states))
                    propagated = sum(
                        abs(coefficient) * state[2] for coefficient, state in zip(row, states)
                    )
                    output_budget = propagated + _gamma(4) * max(
                        1,
                        sum(abs(coefficient * state[0]) for coefficient, state in zip(row, states)),
                    )
                    assert abs(actual_y[k][j] - y) <= output_budget, (
                        "independent PVM output certificate failed"
                    )
                    actual_output = sum(
                        coefficient * state for coefficient, state in zip(row, actual_x[k])
                    )
                    assert abs(actual_y[k][j] - actual_output) <= _gamma(4) * max(
                        1,
                        sum(
                            abs(coefficient * state) for coefficient, state in zip(row, actual_x[k])
                        ),
                    ), "PVM output equation inconsistent"
                    maximum_budget = max(maximum_budget, output_budget)
                for key, actual in (("x", actual_x), ("u", actual_u), ("y", actual_y)):
                    for actual_value, frozen_value in zip(actual[k], frozen[key][k]):
                        assert abs(actual_value - frozen_value) <= _d(
                            tolerance["trajectory_atol"]
                        ), "frozen trajectory tolerance exceeded"
                points += 1
        return {
            "decimal_precision": context.prec,
            "cases": len(data["cases"]),
            "time_points_checked": points,
            "independent_care_residual": float(care_error),
            "independent_gain_error": float(gain_error),
            "max_state_reference_error": float(maximum_state_error),
            "max_ode_residual": float(maximum_equation_error),
            "max_closed_form_roundoff_budget": float(maximum_budget),
            "max_frozen_switch_reference_error": float(maximum_switch_error),
            "exp_accuracy_assumption": "two float64 ULPs, fixture-specific libm envelope",
        }
