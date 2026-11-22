"""ADR-010 regressions, independent certificates and standalone offline scripts."""
import ast
import json
from pathlib import Path

import numpy as np
import pytest
from control_lab.core import TSStateSpace
from control_lab.optimization import (
    CanonicalSDPProblem, continuous_stabilization_lmi, ts_pdc_stabilization_lmi,
    export_to_cvxpy_script, export_to_yalmip_script, solve, recover_controller,
)
from control_lab.optimization.verification.gate0b import _build_gate_0b_suite
from control_lab.optimization.backends.native import BROWSER_ENVELOPE


@pytest.mark.parametrize('case', list(_build_gate_0b_suite()))
def test_native_ladder_independently_audited(case):
    spec = _build_gate_0b_suite()[case]
    result = solve(spec['problem'], backend='native_primal_dual')
    assert result.status != 'failure', result.error
    data = result.data
    assert result.assumptions['independent_audit']
    if spec['kind'] == 'infeasible':
        assert data['certificate_status'] == 'validated_infeasibility'
    elif spec['kind'] == 'unbounded':
        assert data['certificate_status'] == 'validated_unboundedness'
    else:
        assert data['certificate_status'] == 'validated_dual'
        if 'expected_obj' in spec:
            assert data['objective'] == pytest.approx(spec['expected_obj'], abs=1e-6)
        if spec['kind'] == 'controller':
            assert recover_controller(spec['problem'], result).data['controller_validity'] == 'verified_under_assumptions'


def test_moderate_ts_pdc_native():
    n = 4
    vertices = [dict(vertex_id=str(i), A=np.diag([0.2, -1., -2., -3.]) + i*0.01*np.eye(n),
                     B=np.eye(n), C=np.eye(n), D=np.zeros((n,n))) for i in range(3)]
    plant = TSStateSpace(vertices, kind='ts_measured', dt=None,
        membership_spec={'version':'1.0.0','premise_variables':['x1'],'sum_to_one_domain':True},
        premise_availability={'mode':'all_measured','measured_premises':['x1'],
                              'unmeasured_premises':[], 'estimator_required_for_pdc':False},
        domain={'bounds':{'x1':[-1.,1.]}})
    problem = ts_pdc_stabilization_lmi(plant, alpha=0.2)
    result = solve(problem, backend='native_primal_dual')
    assert result.data['certificate_status'] == 'validated_dual'
    assert recover_controller(problem, result, plant=plant).data['controller_validity'] == 'verified_under_assumptions'


def test_offline_exports_are_deterministic_and_python_executes():
    problem = continuous_stabilization_lmi([[0,1],[2,-1]], [[0],[1]], alpha=0.4)
    source = export_to_cvxpy_script(problem)
    ast.parse(source)
    assert source == export_to_cvxpy_script(problem)
    assert 'PSD=True' in source
    namespace = {}
    exec(compile(source, '<controlled native SDP export>', 'exec'), namespace)
    P, K = namespace['P'], namespace['K']
    assert np.linalg.eigvalsh(P).min() > 0
    assert max(np.linalg.eigvals(np.array([[0,1],[2,-1]]) + np.array([[0],[1]]) @ K).real) < -0.4
    matlab = export_to_yalmip_script(problem)
    assert matlab == export_to_yalmip_script(problem)
    for token in ('sdpvar(', 'sdpsettings(', 'optimize(', 'check(', 'value(M) / value(P)'):
        assert token in matlab
    # Exact numeric lowering is covered through the Python export and the same canonical coefficients.
    assert 'F0 = ' in matlab and 'constraints = [constraints, F0 >= 0]' in matlab


def test_native_requires_audit_and_recommends_offline_limits():
    problem = continuous_stabilization_lmi([[1.]], [[1.]])
    result = solve(problem, backend='native_primal_dual', verify_solution=False)
    assert result.status == 'failure' and result.error.code == 'VALIDATION_ERROR'
    n = BROWSER_ENVELOPE['max_variables'] + 1
    large = CanonicalSDPProblem(c=np.ones(n))
    result = solve(large, backend='native_primal_dual')
    assert result.error.code == 'RESOURCE_LIMIT'
    assert result.diagnostics['offline_recommended']
    for exporter in (export_to_cvxpy_script, export_to_yalmip_script):
        assert len(exporter(large)) > 0
    inconclusive = solve(_build_gate_0b_suite()['SDP_3x3_C1']['problem'], backend='native_primal_dual', options={'max_iter':1,'phase1_max_iter':1})
    assert inconclusive.diagnostics['offline_recommended']
    assert any(w.code == 'SDP_OFFLINE_RECOMMENDED' for w in inconclusive.warnings)


def test_native_does_not_trust_ill_conditioning():
    # Deliberate scale imbalance in the canonical input, not a changed oracle tolerance.
    from control_lab.optimization import SDPBlock
    problem = CanonicalSDPProblem(c=[1.], blocks=[SDPBlock('scaled', np.diag([-1.,1e-8]), [np.diag([1.,0.])])])
    result = solve(problem, backend='native_primal_dual')
    assert result.diagnostics['offline_recommended']
    assert result.data['conditioning']['status'] != 'well_conditioned'


def test_native_lqr_lmi_cost_inequality():
    from control_lab.optimization import lqr_lmi
    A = np.array([[0.,1.],[2.,-1.]])
    B = np.array([[0.],[1.]])
    problem = lqr_lmi(A,B)
    result = solve(problem,backend='native_primal_dual')
    assert result.data['certificate_status'] == 'validated_dual'
    variables = result.data['variables']
    from control_lab.core import tensor_to_array
    X = tensor_to_array(variables['Q'])
    Y = tensor_to_array(variables['Y'])
    P = np.linalg.solve(X,np.eye(2))
    K = np.linalg.solve(X.T,Y.T).T
    Acl = A-B@K
    residual = Acl.T@P+P@Acl+np.eye(2)+K.T@K
    assert np.linalg.eigvalsh(residual).max() < 0


def test_export_rpc_uses_same_template_and_is_available_before_solve():
    from control_lab.core.rpc import dispatch
    payload = {'template':'lqr_lmi', 'A':[[0,1],[2,-1]], 'B':[[0],[1]], 'feedback_sign':'negative'}
    for kind, exporter in [('cvxpy',export_to_cvxpy_script), ('yalmip',export_to_yalmip_script)]:
        response = dispatch(dict(api_version='1.0',request_id='offline-'+kind,project_id='offline',
            project_revision=0,operation='optimization.export_'+kind,payload=payload,options={},
            timeout_policy={'hard_timeout_ms':30000}))
        assert response['status'] == 'success',response
        assert response['result']['script'] == exporter(payload)


@pytest.mark.parametrize('options', [{'tol_gap':float('nan')},{'max_iter':True},{'sigma_min':0.99,'sigma_max':0.1}])
def test_native_options_validation(options):
    result = solve(_build_gate_0b_suite()['SDP_3x3_C1']['problem'],backend='native_primal_dual',options=options)
    assert result.status == 'failure' and result.error.code == 'VALIDATION_ERROR'


def test_browser_envelope_448_and_n24_stabilization():
    assert BROWSER_ENVELOPE == {
        'max_variables': 448,
        'max_block_dimension': 64,
        'max_cone_entries': 32768,
    }
    n = 24
    A = np.diag([-1.0 - 0.1 * i for i in range(n - 1)] + [0.5])
    B = np.zeros((n, 1))
    B[-1, 0] = 1.0
    problem = continuous_stabilization_lmi(A, B, alpha=0.2)
    assert problem.n_vars == 324
    assert 256 < problem.n_vars <= BROWSER_ENVELOPE['max_variables']
    result = solve(problem, backend='native_primal_dual')
    assert result.status != 'failure', result.error
    assert result.data['certificate_status'] == 'validated_dual'
    assert recover_controller(problem, result).data['controller_validity'] == 'verified_under_assumptions'


def test_native_iteration_log_and_progress_callback():
    from control_lab.optimization.backends.native_core import (
        clear_progress_callback,
        set_progress_callback,
    )

    problem = _build_gate_0b_suite()['SDP_3x3_C1']['problem']
    seen_entries = []

    def _cb(entry):
        seen_entries.append(entry)
        if len(seen_entries) == 1:
            raise RuntimeError("simulated UI callback failure")

    set_progress_callback(_cb)
    try:
        result = solve(problem, backend='native_primal_dual')
    finally:
        clear_progress_callback()

    assert result.status != 'failure', result.error
    data_log = result.data['iteration_log']
    diag_log = result.diagnostics['iteration_log']
    assert isinstance(data_log, list) and len(data_log) > 0
    assert data_log == diag_log
    assert len(seen_entries) == len(data_log)
    required_keys = {'iter', 'max_iters', 'gap', 'primal_res', 'dual_res', 'min_eig', 'alpha', 'elapsed_ms'}
    for entry in data_log:
        assert required_keys.issubset(entry.keys())
        assert entry['iter'] >= 1
        assert entry['max_iters'] >= 1
        assert entry['elapsed_ms'] >= 0.0

