"""Testes unitários para observadores TS com premissas não mensuradas (F5)."""

from __future__ import annotations

import numpy as np
import pytest

from control_lab.diagnostics import ValidationError
from control_lab.fuzzy import (
    TSUnmeasuredObserverSpec,
    build_dmvt_nonlinearity_spec,
    build_gradient_factorization_spec,
    simulate_ts_unmeasured_observer,
)


def test_build_dmvt_nonlinearity_spec_sector_vertices_and_metadata() -> None:
    A1 = np.array([[-1.0, 1.0], [-0.5, -2.0]])
    A2 = np.array([[-1.2, 1.0], [-0.8, -2.5]])
    C = np.array([[1.0, 0.0]])

    # Duas entradas variantes em J (0,1) e (1,1) -> 2^2 = 4 vértices
    j_min = np.array([[0.0, -0.3], [0.0, -0.4]])
    j_max = np.array([[0.0, 0.3], [0.0, 0.2]])

    spec = build_dmvt_nonlinearity_spec(
        [A1, A2],
        [C],
        jacobian_min=j_min,
        jacobian_max=j_max,
    )

    assert isinstance(spec, TSUnmeasuredObserverSpec)
    assert spec.method == "dmvt_nonlinearity"
    assert spec.n_states == 2
    assert spec.n_outputs == 1
    assert spec.measured_indices == (0,)
    assert spec.unmeasured_indices == (1,)
    assert len(spec.A_vertices) == 2
    assert len(spec.C_vertices) == 1
    assert len(spec.delta_A_vertices) == 4
    assert len(spec.delta_C_vertices) == 1
    assert np.allclose(spec.delta_C_vertices[0], np.zeros((1, 2)))
    assert len(spec.references) >= 1

    # Imutabilidade do spec e dos arrays
    with pytest.raises(Exception):
        spec.method = "other"  # type: ignore[misc]
    with pytest.raises(ValueError):
        spec.delta_A_vertices[0][0, 0] = 99.0


def test_build_dmvt_nonlinearity_spec_with_output_jacobian() -> None:
    A1 = np.eye(2) * -1.0
    C1 = np.array([[1.0, 0.0]])
    j_min = np.zeros((2, 2))
    j_max = np.zeros((2, 2))
    cj_min = np.array([[-0.1, 0.0]])
    cj_max = np.array([[0.2, 0.0]])

    spec = build_dmvt_nonlinearity_spec(
        [A1],
        [C1],
        jacobian_min=j_min,
        jacobian_max=j_max,
        output_jacobian_min=cj_min,
        output_jacobian_max=cj_max,
        measured_indices=(0,),
    )

    assert len(spec.delta_A_vertices) == 1
    assert len(spec.delta_C_vertices) == 2
    assert np.allclose(spec.delta_C_vertices[0], np.array([[-0.1, 0.0]]))
    assert np.allclose(spec.delta_C_vertices[1], np.array([[0.2, 0.0]]))


def test_build_gradient_factorization_spec_and_references() -> None:
    A1 = np.array([[0.0, 1.0], [-2.0, -3.0]])
    A2 = np.array([[0.0, 1.0], [-2.5, -3.5]])
    C1 = np.array([[1.0, 0.0]])
    dA1 = np.array([[0.0, 0.0], [0.0, -0.5]])
    dA2 = np.array([[0.0, 0.0], [0.0, 0.5]])
    dC1 = np.array([[0.0, 0.1]])

    spec = build_gradient_factorization_spec(
        [A1, A2],
        [C1],
        delta_A_vertices=[dA1, dA2],
        delta_C_vertices=[dC1],
        measured_indices=[0],
    )

    assert spec.method == "gradient_factorization"
    assert spec.n_states == 2
    assert spec.n_outputs == 1
    assert spec.measured_indices == (0,)
    assert spec.unmeasured_indices == (1,)
    assert len(spec.delta_A_vertices) == 2
    assert len(spec.delta_C_vertices) == 1
    assert "10.1016/j.fss.2020.04.012" in spec.references
    assert "hal-03425007" in spec.references
    assert "hal-04307213" in spec.references
    assert "10.1007/s40313-025-01189-y" in spec.references


def test_validation_errors_for_shapes_bounds_and_nonfinite() -> None:
    A_ok = np.array([[-1.0, 1.0], [0.0, -2.0]])
    C_ok = np.array([[1.0, 0.0]])

    # Shape mismatch em A_i (não quadrada)
    with pytest.raises(ValidationError):
        build_dmvt_nonlinearity_spec(
            [np.ones((2, 3))],
            [C_ok],
            jacobian_min=np.zeros((2, 2)),
            jacobian_max=np.zeros((2, 2)),
        )

    # Shape mismatch em C_i (colunas != n)
    with pytest.raises(ValidationError):
        build_dmvt_nonlinearity_spec(
            [A_ok],
            [np.array([[1.0, 0.0, 0.0]])],
            jacobian_min=np.zeros((2, 2)),
            jacobian_max=np.zeros((2, 2)),
        )

    # Shape mismatch em jacobian_min
    with pytest.raises(ValidationError):
        build_dmvt_nonlinearity_spec(
            [A_ok],
            [C_ok],
            jacobian_min=np.zeros((3, 3)),
            jacobian_max=np.zeros((2, 2)),
        )

    # J_min > J_max
    with pytest.raises(ValidationError):
        build_dmvt_nonlinearity_spec(
            [A_ok],
            [C_ok],
            jacobian_min=np.array([[0.5, 0.0], [0.0, 0.0]]),
            jacobian_max=np.array([[0.1, 0.0], [0.0, 0.0]]),
        )

    # output_jacobian_min sem output_jacobian_max
    with pytest.raises(ValidationError):
        build_dmvt_nonlinearity_spec(
            [A_ok],
            [C_ok],
            jacobian_min=np.zeros((2, 2)),
            jacobian_max=np.zeros((2, 2)),
            output_jacobian_min=np.zeros((1, 2)),
        )

    # NaN em gradient_factorization
    with pytest.raises(ValidationError):
        build_gradient_factorization_spec(
            [A_ok],
            [C_ok],
            delta_A_vertices=[np.array([[0.0, np.nan], [0.0, 0.0]])],
        )

    # Shape mismatch em delta_C_vertices
    with pytest.raises(ValidationError):
        build_gradient_factorization_spec(
            [A_ok],
            [C_ok],
            delta_A_vertices=[np.zeros((2, 2))],
            delta_C_vertices=[np.zeros((2, 2))],
        )

    # measured_indices inválido
    with pytest.raises(ValidationError):
        build_gradient_factorization_spec(
            [A_ok],
            [C_ok],
            delta_A_vertices=[np.zeros((2, 2))],
            measured_indices=[0, 0],
        )


def test_simulate_ts_unmeasured_observer_converges_dmvt_2state() -> None:
    """Sistema TS não linear de 2 estados com premissa não mensurada (z = x_2, y = x_1)."""
    A1 = np.array([[-1.0, 1.0], [-2.0, -3.0]])
    A2 = np.array([[-1.0, 1.0], [-2.5, -3.5]])
    C = np.array([[1.0, 0.0]])  # apenas x_1 é medido; x_2 é não mensurado

    # Não linearidade f_nl(x) = [0, -0.2 * sin(x_2)] -> d(f_nl)/dx_2 in [-0.2, 0.2]
    j_min = np.array([[0.0, 0.0], [0.0, -0.2]])
    j_max = np.array([[0.0, 0.0], [0.0, 0.2]])

    spec = build_dmvt_nonlinearity_spec(
        [A1, A2],
        [C],
        jacobian_min=j_min,
        jacobian_max=j_max,
    )

    # Ganhos de observador que estabilizam (A_i - L_i C + dA_k)
    L1 = np.array([[5.0], [6.0]])
    L2 = np.array([[5.5], [6.5]])

    def premise_fn(state: np.ndarray) -> np.ndarray:
        # Premissa depende do estado NÃO mensurado x_2
        w1 = 0.5 * (1.0 + np.tanh(state[1]))
        return np.array([w1, 1.0 - w1])

    def nonlinearity_fn(state: np.ndarray) -> np.ndarray:
        return np.array([0.0, -0.2 * np.sin(state[1])])

    result = simulate_ts_unmeasured_observer(
        spec,
        [L1, L2],
        x0=[1.2, -0.8],
        x_hat0=[0.0, 0.5],
        t_span=(0.0, 6.0),
        dt=0.01,
        nonlinearity_fn=nonlinearity_fn,
        premise_fn=premise_fn,
    )

    assert result["t"].shape[0] == result["x"].shape[0] == result["x_hat"].shape[0]
    assert result["error"].shape == (result["t"].shape[0], 2)
    assert result["max_final_error"] < 1e-3
    assert result["converged"] is True


def test_simulate_ts_unmeasured_observer_converges_gradient_factorization_with_input() -> None:
    A1 = np.array([[-1.5, 1.0], [-1.0, -2.5]])
    A2 = np.array([[-1.5, 1.0], [-1.2, -3.0]])
    B1 = np.array([[0.0], [1.0]])
    C = np.array([[1.0, 0.0]])

    spec = build_gradient_factorization_spec(
        [A1, A2],
        [C],
        delta_A_vertices=[
            np.array([[0.0, 0.0], [0.0, -0.3]]),
            np.array([[0.0, 0.0], [0.0, 0.3]]),
        ],
    )

    L1 = np.array([[4.0], [3.0]])
    L2 = np.array([[4.5], [3.5]])

    res = simulate_ts_unmeasured_observer(
        spec,
        [L1, L2],
        x0=[0.5, -1.0],
        x_hat0=[-0.5, 0.5],
        t_span=(0.0, 6.0),
        dt=0.01,
        u_fn=lambda t: np.array([0.5 * np.sin(t)]),
        nonlinearity_fn=lambda x, u: np.array([0.0, -0.15 * np.arctan(x[1])]),
        premise_fn=lambda x, u: np.array([1.0 / (1.0 + np.exp(-x[1])), 1.0 - 1.0 / (1.0 + np.exp(-x[1]))]),
        B_vertices=[B1],
    )

    assert res["max_final_error"] < 1e-3
    assert res["converged"] is True
