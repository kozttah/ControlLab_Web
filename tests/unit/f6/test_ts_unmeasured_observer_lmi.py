"""Unit tests for ts_unmeasured_observer_lmi and recover_ts_observer_gains (F6)."""

import numpy as np
import pytest

from control_lab.core import tensor_to_array
from control_lab.diagnostics import DimensionMismatchError, ValidationError
from control_lab.optimization import (
    recover_ts_observer_gains,
    solve,
    ts_unmeasured_observer_lmi,
)


def test_ts_unmeasured_observer_lmi_2state_2rule_with_dA_perturbations():
    A1 = np.array([[0.0, 1.0], [-2.0, -1.0]], dtype=np.float64)
    A2 = np.array([[0.0, 1.0], [-3.5, -1.5]], dtype=np.float64)
    C1 = np.array([[1.0, 0.0]], dtype=np.float64)
    C2 = np.array([[1.0, 0.0]], dtype=np.float64)

    dA1 = np.array([[0.0, 0.0], [0.25, -0.1]], dtype=np.float64)
    dA2 = np.array([[0.0, 0.0], [-0.25, 0.1]], dtype=np.float64)
    alpha = 0.5

    problem = ts_unmeasured_observer_lmi(
        [A1, A2],
        [C1, C2],
        delta_A_vertices=[dA1, dA2],
        alpha=alpha,
        method="dmvt_nonlinearity",
    )
    assert problem.metadata["template"] == "ts_unmeasured_observer_lmi"
    assert problem.metadata["method"] == "dmvt_nonlinearity"
    assert problem.metadata["n"] == 2
    assert problem.metadata["p"] == 1
    assert problem.metadata["n_rules"] == 2
    assert problem.metadata["n_perturbations"] == 2
    assert problem.metadata["alpha"] == pytest.approx(alpha)

    result = solve(problem, backend="native_primal_dual")
    assert result.status != "failure", result.error
    data = result.data
    assert data["certificate_status"] == "validated_dual"
    assert data["audit_feasibility"] in ("feasible", "strictly_feasible")

    x = tensor_to_array(data["x"])
    gains = recover_ts_observer_gains(problem, x)
    assert len(gains) == 2

    A_list = [A1, A2]
    C_list = [C1, C2]
    dA_list = [dA1, dA2]
    dC_zero = np.zeros_like(C1)

    for i, L_i in enumerate(gains):
        assert L_i.shape == (2, 1)
        for dA_k in dA_list:
            A_err = (A_list[i] + dA_k) - L_i @ (C_list[i] + dC_zero)
            max_real_eig = float(np.max(np.linalg.eigvals(A_err).real))
            assert max_real_eig < -alpha


def test_ts_unmeasured_observer_lmi_varying_C_and_gradient_factorization():
    A1 = np.array([[0.0, 1.0], [-2.0, -1.0]], dtype=np.float64)
    A2 = np.array([[0.0, 1.0], [-3.0, -1.5]], dtype=np.float64)
    C1 = np.array([[1.0, 0.0]], dtype=np.float64)
    C2 = np.array([[1.0, 0.1]], dtype=np.float64)

    dA1 = np.array([[0.0, 0.0], [0.15, 0.0]], dtype=np.float64)
    dA2 = np.array([[0.0, 0.0], [-0.15, 0.0]], dtype=np.float64)
    dC1 = np.array([[0.0, 0.02]], dtype=np.float64)
    dC2 = np.array([[0.0, -0.02]], dtype=np.float64)
    alpha = 0.25

    problem = ts_unmeasured_observer_lmi(
        [A1, A2],
        [C1, C2],
        delta_A_vertices=[dA1, dA2],
        delta_C_vertices=[dC1, dC2],
        alpha=alpha,
        method="exact_gradient_factorization",
    )
    assert problem.metadata["method"] == "exact_gradient_factorization"
    # 1 (P>=eps) + 2*2 (diagonal i,k) + 1*2 (off-diagonal i<j,k) = 7 LMI blocks
    assert len(problem.blocks) == 7

    result = solve(problem, backend="native_primal_dual")
    assert result.status != "failure", result.error
    assert result.data["certificate_status"] == "validated_dual"
    assert result.data["audit_feasibility"] in ("feasible", "strictly_feasible")

    x = tensor_to_array(result.data["x"])
    gains = recover_ts_observer_gains(problem, x)
    for A_i, C_i, L_i in zip([A1, A2], [C1, C2], gains):
        for dA_k, dC_k in zip([dA1, dA2], [dC1, dC2]):
            A_err = (A_i + dA_k) - L_i @ (C_i + dC_k)
            assert float(np.max(np.linalg.eigvals(A_err).real)) < -alpha


def test_ts_unmeasured_observer_lmi_defaults_and_validation():
    A1 = np.array([[-1.0, 1.0], [0.0, -2.0]], dtype=np.float64)
    C1 = np.array([[1.0, 0.0]], dtype=np.float64)
    prob = ts_unmeasured_observer_lmi([A1], [C1])
    assert prob.metadata["n_perturbations"] == 1
    res = solve(prob, backend="native_primal_dual")
    assert res.data["certificate_status"] == "validated_dual"
    gains = recover_ts_observer_gains(prob, res.data["x"])
    assert len(gains) == 1
    assert float(np.max(np.linalg.eigvals(A1 - gains[0] @ C1).real)) < 0.0

    with pytest.raises(ValidationError):
        ts_unmeasured_observer_lmi([], [C1])

    with pytest.raises(DimensionMismatchError):
        ts_unmeasured_observer_lmi([A1], [C1, C1])

    with pytest.raises(DimensionMismatchError):
        ts_unmeasured_observer_lmi([A1], [np.array([[1.0, 0.0, 0.0]])])

    with pytest.raises(DimensionMismatchError):
        ts_unmeasured_observer_lmi(
            [A1],
            [C1],
            delta_A_vertices=[np.zeros((2, 2))],
            delta_C_vertices=[np.zeros((1, 2)), np.zeros((1, 2))],
        )
