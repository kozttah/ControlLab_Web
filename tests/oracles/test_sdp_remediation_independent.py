"""Independent F9 probes for AUD-006/007/008 (CL-DIR-001 sections 6.1-6.3).

Expected numbers follow from diagonal eigenvalues and exact determinants, not
from a producer-generated fixture or solver output. CPython evidence only.
"""

import numpy as np
import pytest

from control_lab.optimization import (
    CanonicalSDPProblem,
    EducationalBarrierBackend,
    ScipyLinprogBackend,
    verify,
)
from control_lab.optimization.backends.base import SolverUnavailableError
from control_lab.optimization.backends.capabilities import get_backend
from control_lab.optimization.modeling.canonical import SDPBlock
from control_lab.experimental.sdp_educational.solver import (
    EducationalPrimalDualSDPBackend,
    make_educational_barrier_backend,
)


def _attempt_array_mutation(array):
    """A public getter may refuse writing or return an isolated writable copy."""
    candidate = array
    seen = set()
    while isinstance(candidate, np.ndarray) and id(candidate) not in seen:
        seen.add(id(candidate))
        try:
            candidate.setflags(write=True)
            if candidate.size:
                candidate.flat[0] = 987.0
        except (ValueError, TypeError):
            pass
        candidate = candidate.base


def test_f9_sdp_snapshot_survives_input_getter_and_structure_mutation():
    a = np.eye(2)
    fk = np.diag([2.0, 3.0])
    c, e, d, h, rhs = (np.array(x, dtype=float) for x in
                       ([1.0], [[2.0]], [3.0], [[4.0]], [5.0]))
    metadata = {"nested": {"values": [1, 2]}}
    block = SDPBlock("B", a, [fk])
    problem = CanonicalSDPProblem(c=c, blocks=[block], E=e, d=d, H=h, h=rhs,
                                  metadata=metadata)
    frozen = problem.to_json()
    expected = np.diag([3.0, 4.0])  # F0 + F1 with x=1.
    for array in (a, fk, c, e, d, h, rhs):
        _attempt_array_mutation(array)
    metadata["nested"]["values"][0] = 99
    for array in (block.F0, block.get_Fk(0), *block.F_k,
                  *block.F_terms.values(), problem.c, problem.E, problem.d,
                  problem.H, problem.h):
        _attempt_array_mutation(array)
    terms = block.F_terms
    try:
        terms[0] = np.zeros((2, 2))
    except TypeError:
        pass
    exposed = problem.metadata
    exposed["nested"]["values"][0] = 100
    mapping = problem.variable_map
    mapping["x"]["coords"][0][0] = 100
    serialized = problem.to_dict()
    serialized["name"] = "tampered"
    for obj, attribute, value in (
        (block, "_F0", np.zeros((2, 2))),
        (block, "_is_diagonal", False),
        (problem, "_c", np.array([0.0])),
        (problem, "_blocks", ()),
    ):
        with pytest.raises((AttributeError, TypeError)):
            setattr(obj, attribute, value)
        with pytest.raises((AttributeError, TypeError)):
            delattr(obj, attribute)
    assert problem.to_json() == frozen
    np.testing.assert_array_equal(block.evaluate([1.0]), expected)
    assert block.is_diagonal and problem.all_blocks_diagonal()


@pytest.mark.parametrize("epsilon", [1e-15, 1e-30, np.nextafter(0.0, 1.0)])
@pytest.mark.parametrize("in_basis", [False, True])
def test_f9_any_nonzero_off_diagonal_prevents_exact_lp(epsilon, in_basis):
    # det([[x,eps],[eps,0]]) = -eps**2 < 0 in exact arithmetic.
    off = np.array([[0.0, epsilon], [epsilon, 0.0]])
    if in_basis:
        block = SDPBlock("not_diagonal", np.zeros((2, 2)), [off])
    else:
        block = SDPBlock("not_diagonal", off, [np.diag([1.0, 0.0])])
    problem = CanonicalSDPProblem(c=[1.0], blocks=[block])
    assert not block.is_diagonal and not problem.all_blocks_diagonal()
    assert get_backend("auto", problem=problem).name != "scipy_linprog"
    with pytest.raises(SolverUnavailableError) as exc:
        ScipyLinprogBackend().solve_raw(problem)
    assert exc.value.parameters["reason"] == "unsupported_psd"


def test_f9_spectral_residual_matches_diagonal_analytic_values():
    blocks = [
        SDPBlock("constant", np.diag([100.0, 100.0, -1.0]), [np.zeros((3, 3))]),
        SDPBlock("affine", np.diag([4.0, -3.0]), [np.diag([1.0, -2.0])]),
    ]
    problem = CanonicalSDPProblem(c=[0.0], blocks=blocks)
    audited = verify(problem, {"x": [2.0], "solver_status": "unknown"})
    assert audited.data is not None
    # First: 1/(1+100). Second: F(2)=diag(6,-7), 7/(1+4+2*2).
    np.testing.assert_allclose(
        audited.data["residuals"]["primal_block_violations_rel"],
        [1.0 / 101.0, 7.0 / 9.0], rtol=1e-14, atol=0.0,
    )
    assert audited.data["audit_feasibility"] == "violated"
    # 0.008 lies between the old Frobenius residual (~0.00702) and 1/101.
    # The normative spectral scale must therefore reject this point.
    threshold_problem = CanonicalSDPProblem(c=[0.0], blocks=[blocks[0]])
    threshold_audit = verify(threshold_problem, {"x": [0.0]},
                             tolerances={"psd_tol": 0.008})
    assert threshold_audit.data["audit_feasibility"] == "violated"


def test_f9_educational_descriptor_is_explicit_and_experimental():
    empty = EducationalBarrierBackend().capabilities()
    unknown = EducationalBarrierBackend(solver_fn=lambda p, o: {}).capabilities()
    assert not empty["available"]
    for key in ("dual", "infeasibility_certificate", "unboundedness_certificate",
                "warm_start", "cancellation"):
        assert unknown[key] is False
    registered = make_educational_barrier_backend().capabilities()
    implementation = EducationalPrimalDualSDPBackend().capabilities()
    for key in ("psd", "lp", "dual", "infeasibility_certificate",
                "unboundedness_certificate", "warm_start", "cancellation"):
        assert registered[key] == implementation[key]
    assert registered["maturity"] == "experimental"
    assert registered["experimental"] is True and registered["certified"] is False
    registered["tolerances"]["configurable"] = False
    assert make_educational_barrier_backend().capabilities()["tolerances"]["configurable"] is True
