"""Regressions for AUD-006/007/008 and OBS-F9-WP10-01 (CL-DIR-001 §6).

Expected values are analytic: tiny nonzero coupling has determinant -epsilon²;
diagonal spectral norms are maxima of absolute entries, not Frobenius norms.
No golden expected value or tolerance is derived from the code under test.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from control_lab.experimental.sdp_educational import (
    EducationalPrimalDualSDPBackend,
    make_educational_barrier_backend,
)
from control_lab.optimization import (
    CanonicalSDPProblem,
    EducationalBarrierBackend,
    ScipyLinprogBackend,
    UnavailableBackend,
    get_backend,
    solve,
    verify,
)
from control_lab.optimization.backends.base import SolverUnavailableError
from control_lab.optimization.backends import capabilities as backend_registry
from control_lab.optimization.modeling.canonical import SDPBlock


def _assert_readonly_through_bases(array: np.ndarray) -> None:
    """Even walking ndarray.base must not reach a re-enableable owner."""
    current = array
    while isinstance(current, np.ndarray):
        with pytest.raises(ValueError):
            current.setflags(write=True)
        current = current.base
    assert isinstance(current, bytes)


def test_canonical_sdp_deep_immutability() -> None:
    arrays = {
        "c": np.array([2.0, 3.0]), "E": np.eye(2), "d": np.ones(2),
        "H": np.eye(2), "h": np.ones(2) * 4,
    }
    F0 = np.diag([1.0, 2.0])
    F1 = np.diag([3.0, 4.0])
    metadata = {"nested": {"values": [1, 2]}}
    block = SDPBlock("frozen", F0, {0: F1}, n_vars=2)
    problem = CanonicalSDPProblem(**arrays, blocks=[block], metadata=metadata)
    serialized = problem.to_json()
    for arr in (*arrays.values(), F0, F1):
        arr[...] = 99
    metadata["nested"]["values"][0] = 99
    assert problem.to_json() == serialized

    views = [problem.c, problem.E, problem.d, problem.H, problem.h,
             block.F0, block.get_Fk(0), block.get_Fk(1),
             *block.F_terms.values(), *block.F_k]
    for arr in views:
        _assert_readonly_through_bases(arr)
        if arr.size:
            with pytest.raises(ValueError):
                arr.flat[0] = 99
            # A read-only ndarray still allows shape reassignment. Its metadata
            # must therefore belong to a fresh view, not to canonical storage.
            arr.shape = (arr.size,)
            if isinstance(arr.base, np.ndarray):
                arr.base.shape = (arr.size,)
    assert problem.to_json() == serialized

    for obj, changes in (
        (block, {"_is_diagonal": False, "_dim": 99, "_F0": np.eye(9), "_locked": False}),
        (problem, {"_n_vars": 99, "_blocks": (), "_c": np.zeros(2), "_locked": False}),
    ):
        assert not hasattr(obj, "__dict__")
        for attr, value in changes.items():
            with pytest.raises(AttributeError):
                setattr(obj, attr, value)
            with pytest.raises(AttributeError):
                delattr(obj, attr)
    with pytest.raises(TypeError):
        block._F_terms_specs[0] = (b"", (0,))
    with pytest.raises(TypeError):
        problem._metadata["nested"]["values"][0] = 99
    public_metadata = problem.metadata
    public_metadata["nested"]["values"][0] = 99
    data = problem.to_dict()
    data["metadata"]["nested"]["values"][0] = 99
    assert problem.to_json() == serialized
    assert CanonicalSDPProblem.from_dict(json.loads(serialized)).to_json() == serialized
    np.testing.assert_array_equal(block.evaluate([2.0, 0.0]), np.diag([7.0, 10.0]))


@pytest.mark.parametrize("tiny", [1e-15, np.nextafter(0.0, 1.0)])
@pytest.mark.parametrize("coupled_coefficient", ["F0", "Fk"])
def test_lp_requires_exact_structural_diagonal(monkeypatch, tiny, coupled_coefficient) -> None:
    # F=[[x, eps],[eps,0]] has negative determinant for every finite x.
    # Classifying it as LP would discard the essential coupling entirely.
    F0 = np.zeros((2, 2))
    F1 = np.diag([1.0, 0.0])
    target = F0 if coupled_coefficient == "F0" else F1
    target[0, 1] = target[1, 0] = tiny
    block = SDPBlock("coupled", F0, [F1])
    problem = CanonicalSDPProblem(c=[1.0], blocks=[block])
    assert block.is_diagonal is False
    assert problem.all_blocks_diagonal() is False
    with pytest.raises(SolverUnavailableError) as error:
        ScipyLinprogBackend().solve_raw(problem)
    assert error.value.to_typed_error().parameters["reason"] == "unsupported_psd"
    monkeypatch.setattr(backend_registry.ClarabelDirectBackend, "capabilities", lambda _: {"available": False})
    monkeypatch.setattr(backend_registry.ClarabelCvxpyBackend, "capabilities", lambda _: {"available": False})
    assert get_backend("auto", problem=problem).name == "native_primal_dual"
    diagonal = CanonicalSDPProblem(c=[1.0], blocks=[SDPBlock("diagonal", -np.eye(2), [np.eye(2)])])
    assert isinstance(get_backend("auto", problem=diagonal), ScipyLinprogBackend)
    exact_lp = solve(diagonal, backend="scipy_linprog")
    assert exact_lp.data is not None
    assert float(exact_lp.data["objective"]) == pytest.approx(1.0)


def test_psd_violation_uses_spectral_norm() -> None:
    zero = np.zeros((3, 3))
    first = SDPBlock("constant", np.diag([100.0, 100.0, -1.0]), [zero, zero])
    # At x=[2,-3], denominator=1+4+2*3+3*5=26.
    second = SDPBlock("affine", np.diag([4.0, 4.0, -1.0]),
                      [np.diag([3.0, 1.0, 0.0]), np.diag([0.0, 2.0, 5.0])])
    # Here evaluated F=diag(10,0,-16), so violation=16, same denominator=26.
    problem = CanonicalSDPProblem(c=[0.0, 0.0], blocks=[first, second])
    result = verify(problem, {"x": [2.0, -3.0]}, claimed_status="unknown")
    assert result.data is not None
    residuals = result.data["residuals"]
    np.testing.assert_allclose(residuals["primal_block_violations_rel"], [1.0 / 101.0, 16.0 / 26.0], rtol=1e-14)
    assert result.data["audit_feasibility"] == "violated"


def test_educational_capabilities_are_registered_not_guessed() -> None:
    absent = EducationalBarrierBackend().capabilities()
    unknown = EducationalBarrierBackend(solver_fn=lambda problem, options: {}).capabilities()
    for caps in (absent, unknown):
        assert not caps["dual"]
        assert not caps["infeasibility_certificate"]
        assert not caps["unboundedness_certificate"]
        assert caps["lib_versions"] == {}
    assert absent["available"] is False and unknown["available"] is True
    actual = make_educational_barrier_backend(options={"tol_gap": 1e-8})
    caps = actual.capabilities()
    reference = EducationalPrimalDualSDPBackend(options={"tol_gap": 1e-8}).capabilities()
    for key in ("psd", "lp", "dual", "infeasibility_certificate", "unboundedness_certificate",
                "warm_start", "cancellation", "tolerances", "lib_versions"):
        assert caps[key] == reference[key]
    assert caps["dual"] is True
    assert caps["infeasibility_certificate"] is True
    assert caps["unboundedness_certificate"] is True
    assert caps["maturity"] == "experimental" and caps["certified"] is False
    caps["lib_versions"].clear()
    assert actual.capabilities()["lib_versions"]
    attempted_promotion = EducationalBarrierBackend(
        solver_fn=lambda problem, options: {},
        solver_capabilities={"maturity": "stable", "certified": True},
    ).capabilities()
    assert attempted_promotion["maturity"] == "experimental"
    assert attempted_promotion["certified"] is False
