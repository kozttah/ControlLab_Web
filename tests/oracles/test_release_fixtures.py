"""Frozen independent release gold versus production (CL-DIR-001 §§10.2/10.4).

Never regenerate references from production; official PathView/Wasm gates stay open.
"""
import hashlib
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import scipy.linalg as la

from scripts.arx_regeneration_certificate import assert_arx_regeneration_matches_frozen_gold

from control_lab.core import Dataset, StateFeedbackController, StateSpace, TransferFunction
from control_lab.frequency.mimo import eval_mimo_response, rga, sensitivity, singular_values
from control_lab.frequency.siso import stability_margins
from control_lab.identification import fit_arx
from control_lab.io import make_pvm, simulate_pvm_graph
from control_lab.statespace import design_lqr, discretize_zoh, solve_care, solve_dare

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / 'contracts/fixtures'


def load(name):
    return json.loads((FIX/(name+'.json')).read_text())


def array(x):
    if isinstance(x, dict):
        if 'data' in x:
            return np.array(x['data']).reshape(x['shape'],order=x.get('order','C'))
        if 'real' in x:
            z = np.array(x['real'])+1j*np.array(x['imag'])
            return z.reshape(x.get('shape',z.shape))
    return np.asarray(x)


def good(result):
    assert result.status in ('success','warning'), result.to_dict()
    assert result.error is None and result.provenance is not None
    return result.data


def test_t_care_02_production_against_preserved_gold():
    f = load('B-CARE-12x3')
    d, e, tol = f['data'],f['data']['expected'],f['tolerances']
    out = good(solve_care(A=array(d['A']),B=array(d['B']),Q=array(d['Q']),R=array(d['R']),x0=array(d['x0'])))
    for key in ('P','K'):
        np.testing.assert_allclose(array(out[key]),array(e[key]),rtol=tol[key+'_rel_tol'],atol=1e-12)


def test_dare_zoh_production_and_independent_residual():
    f = load('B-DARE-12x3')
    d,e,tol = f['data'],f['data']['expected'],f['tolerances']
    A,B,Q,R = [array(d[k]) for k in ('A','B','Q','R')]
    c = d['continuous']
    plant = StateSpace(*[array(c[k]) for k in ('A','B','C','D')])
    zoh = good(discretize_zoh(plant,d['dt']))['model']['matrices']
    for key in ('A','B','C','D'):
        np.testing.assert_allclose(array(zoh[key]),array(d[key]),rtol=0,atol=tol['matrix_atol'])
    out = good(solve_dare(A=A,B=B,Q=Q,R=R,dt=d['dt'],x0=array(d['x0'])))
    for key in ('P','K'):
        np.testing.assert_allclose(array(out[key]),array(e[key]),rtol=tol[key+'_rel_tol'],atol=1e-12)
    P,K = array(out['P']),array(out['K'])
    terms = [A.T@P@A,-P,-A.T@P@B@K,Q]
    assert la.norm(sum(terms))/(1+sum(la.norm(x) for x in terms)) < tol['rDARE_max']
    assert la.norm(P-P.T)/(1+la.norm(P)) < tol['symmetry_error_max']
    assert np.min(la.eigvalsh(P)) > 0
    poles = np.sort_complex(la.eigvals(A-B@K))
    assert max(abs(poles)) < 1
    np.testing.assert_allclose(poles,array(e['closed_loop_poles']),rtol=0,atol=tol['poles_atol'])


def test_t_id_03_full_data_holdout_production():
    f = load('B-ARX-PRBS')
    d,e,tol = f['data'],f['data']['expected'],f['tolerances']
    t,u,y = [array(d[k]) for k in ('t','u','y')]
    train, val = [slice(*d['splits'][k]) for k in ('train','validation')]
    assert train.stop == val.start and val.stop == len(t)
    train_ds = Dataset(t[train],u[train],y[train],dt=d['dt'],id='gold-train')
    val_ds = Dataset(t[val],u[val],y[val],dt=d['dt'],id='gold-val')
    result = fit_arx(dataset=train_ds,val_dataset=val_ds,na=d['na'],nb=d['nb'],nk=d['nk'])
    out = good(result)
    est = np.r_[out['parameters']['a'],out['parameters']['b']]
    np.testing.assert_allclose(est,array(e['theta']),rtol=0,atol=tol['theta_atol'])
    np.testing.assert_allclose(est,array(e['generating_theta']),rtol=0,atol=tol['planted_coefficient_atol'])
    assert result.diagnostics['rank'] == e['rank'] == 4
    assert not result.diagnostics['rank_deficient'] and result.assumptions['pe_satisfied']
    np.testing.assert_allclose(array(out['poles']),array(e['poles']),rtol=0,atol=tol['pole_atol'])
    for part,key in [('train','train'),('validation','val')]:
        for mode,suffix in [('one_step_prediction','one_step'),('free_simulation','free_sim')]:
            actual = out['metrics'][part][mode]['fit_percent']
            assert abs(actual-e['fit'][part][mode]) < tol['fit_atol']
            assert actual > 90
            np.testing.assert_allclose(array(out['y_hat_'+key+'_'+suffix]),array(e['predictions'][part][mode]),rtol=0,atol=tol['prediction_atol'])
    # Check frozen data actually realizes the stated generator and SNR, not just a seed.
    clean,innov = array(d['clean_y']).ravel(),array(d['innovations']).ravel()
    flat = y.ravel()
    theta = array(e['generating_theta'])
    eq_err = flat[2:]+theta[0]*flat[1:-1]+theta[1]*flat[:-2]-theta[2]*u[1:-1,0]-theta[3]*u[:-2,0]
    np.testing.assert_allclose(eq_err,innov[2:],rtol=0,atol=1e-14)
    assert abs(20*np.log10(la.norm(clean[2:])/la.norm(flat[2:]-clean[2:]))-d['noise']['snr_db']) < tol['snr_atol']


def test_t_mimo_01_full_grid_production():
    f = load('B-MIMO-2x2')
    d,e,tol = f['data'],f['data']['expected'],f['tolerances']
    plant = StateSpace(*[array(d[k]) for k in ('A','B','C','D')])
    w = array(d['omega'])
    np.testing.assert_allclose(array(good(eval_mimo_response(plant,w))['G']),array(e['G']),rtol=0,atol=tol['response_atol'])
    np.testing.assert_allclose(array(good(singular_values(plant,w))['singular_values']),array(e['singular_values']),rtol=0,atol=tol['singular_values_atol'])
    entries = good(rga(plant,w))['entries']
    for i,entry in enumerate(entries):
        assert entry['status']=='defined'
        mat = array(entry['rga_matrix'])
        np.testing.assert_allclose(mat,array(e['RGA'])[i],rtol=0,atol=tol['response_atol'])
        np.testing.assert_allclose(mat.sum(axis=0),1.,rtol=0,atol=tol['identity_atol'])
        np.testing.assert_allclose(mat.sum(axis=1),1.,rtol=0,atol=tol['identity_atol'])
    st = good(sensitivity(plant,np.eye(2),w))
    for key in ('S','T'):
        np.testing.assert_allclose(array(st[key]),array(e[key]),rtol=0,atol=tol['response_atol'])
    np.testing.assert_allclose(array(st['S'])+array(st['T']),np.broadcast_to(np.eye(2),(len(w),2,2)),rtol=0,atol=tol['identity_atol'])


def test_t_mimo_02_singular_cases_are_undefined():
    d = load('B-MIMO-2x2')['data']
    for case in d['singular_cases']:
        result = rga(array(case['matrix']),array(d['omega']))
        assert result.status == 'inconclusive'
        assert result.data['rga_status'] == case['expected_rga_status']
        assert all(entry['rga_matrix'] is None for entry in result.data['entries'])
        assert result.warnings


def test_t_freq_02_all_polynomial_crossings_against_production():
    f = load('B-MIMO-2x2')
    c = f['data']['multiple_crossings']
    plant = TransferFunction(c['num'],c['den'])
    out = good(stability_margins(plant,omega_min=c['omega_min'],omega_max=c['omega_max'],n_points=20000))
    assert len(out['gain_crossovers']) == len(c['gain_crossings']) == 3
    np.testing.assert_allclose(out['omega_gc_all'],c['gain_crossings'],rtol=0,atol=f['tolerances']['crossing_atol'])
    for w in c['gain_crossings']:
        assert abs(abs(np.polyval(c['num'],1j*w)/np.polyval(c['den'],1j*w))-1) < 1e-10


@pytest.mark.parametrize('index',range(4))
def test_t_pvm_01_local_graph_against_analytic_gold(index):
    f = load('B-PVM-LQR')
    d,tol = f['data'],f['tolerances']
    case = d['cases'][index]
    A,B,Q,R,K = [array(d[k]) for k in ('A','B','Q','R','K')]
    plant = StateSpace(A,B,array(case['C']),array(case['D']))
    design = good(design_lqr(plant,Q,R))
    np.testing.assert_allclose(array(design['K']),K,rtol=0,atol=tol['gain_atol'])
    ctrl = StateFeedbackController(K,feedback_sign=d['feedback_sign'],reference_map=array(case['reference_map']))
    pvm = make_pvm(plant,ctrl,scenario={'initial_state':array(d['x0']),'saturation':case['saturation']})
    # Official scalar ABI: y occupies ports [0,p); every x[j] must feed K[j].
    # Check the complete channel map, including C=I and C!=I, without changing
    # any numerical oracle value or tolerance below.
    state_connections = [x for x in pvm['graph']['connections'] if x['targetNodeId']=='gain_K']
    assert len(state_connections) == plant.n_states
    assert sorted((x['sourceNodeId'],x['sourcePortIndex'],x['targetPortIndex']) for x in state_connections) == [
        ('plant_ss',plant.n_outputs+j,j) for j in range(plant.n_states)
    ]
    out = good(simulate_pvm_graph(pvm,array(d['t']),r=array(case['r']),rtol=1e-11,atol=1e-13))
    for key in ('x','u','y'):
        np.testing.assert_allclose(array(out[key]),array(case['expected'][key]),rtol=0,atol=tol['trajectory_atol'])
    assert d['external_pathview_verified'] is False and d['gate_status']=='PENDING_G0D'
    assert pvm['metadata']['external_pathview_verified'] is False


def assert_dare_regeneration_matches_frozen_gold(generated, saved):
    """Check LAPACK results numerically while retaining exact deterministic inputs.

    Frozen bytes are checked separately by verify_checksums. DARE eigenvectors,
    residuals and costs are floating-point computations, not byte-level identities.
    Only the fields listed below may differ, within the already frozen criteria.
    """
    actual = deepcopy(generated)
    tol = saved['tolerances']
    data, reference = actual['data'], saved['data']
    numeric = [
        (data, reference, 'A', 0, tol['matrix_atol']),
        (data, reference, 'B', 0, tol['matrix_atol']),
        (data['expected'], reference['expected'], 'P', tol['P_rel_tol'], tol['matrix_atol']),
        (data['expected'], reference['expected'], 'K', tol['K_rel_tol'], tol['matrix_atol']),
    ]
    for target, frozen, key, rtol, atol in numeric:
        # Normalize data only; shape/dtype/order must still match exactly.
        np.testing.assert_allclose(array(target[key]), array(frozen[key]), rtol=rtol, atol=atol)
        target[key]['data'] = deepcopy(frozen[key]['data'])
    expected, frozen = data['expected'], reference['expected']
    # Recompute the certificate from regenerated matrices, independently of any
    # residual field supplied by the generator. No production solver is called.
    A, B, Q, R, x0 = [array(generated['data'][key]) for key in ('A', 'B', 'Q', 'R', 'x0')]
    P, K = [array(generated['data']['expected'][key]) for key in ('P', 'K')]
    terms = [A.T@P@A, -P, -A.T@P@B@K, Q]
    assert la.norm(sum(terms))/(1+sum(la.norm(term) for term in terms)) < tol['rDARE_max']
    assert la.norm(P-P.T)/(1+la.norm(P)) < tol['symmetry_error_max']
    assert np.min(la.eigvalsh(P)) > 0
    np.testing.assert_allclose(K, la.solve(R+B.T@P@B, B.T@P@A),
                               rtol=tol['K_rel_tol'], atol=tol['matrix_atol'])
    poles = np.sort_complex(la.eigvals(A-B@K))
    assert max(abs(poles)) < 1
    np.testing.assert_allclose(poles, array(generated['data']['expected']['closed_loop_poles']),
                               rtol=0, atol=tol['poles_atol'])
    np.testing.assert_allclose(expected['spectral_radius'], max(abs(poles)),
                               rtol=0, atol=tol['poles_atol'])
    np.testing.assert_allclose(expected['optimal_cost'], (x0.T@P@x0).item(),
                               rtol=tol['P_rel_tol'], atol=0)
    for component in ('real', 'imag'):
        np.testing.assert_allclose(expected['closed_loop_poles'][component],
                                   frozen['closed_loop_poles'][component],
                                   rtol=0, atol=tol['poles_atol'])
        expected['closed_loop_poles'][component] = deepcopy(frozen['closed_loop_poles'][component])
    for key, rtol, atol in (
        ('spectral_radius', 0, tol['poles_atol']),
        # J=x0.T P x0 inherits the frozen relative P criterion.
        ('optimal_cost', tol['P_rel_tol'], 0),
    ):
        np.testing.assert_allclose(expected[key], frozen[key], rtol=rtol, atol=atol)
        expected[key] = frozen[key]
    for key, bound in (
        ('rDARE', tol['rDARE_max']),
        ('symmetry_error', tol['symmetry_error_max']),
        ('zoh_quadrature_max_error', tol['matrix_atol']),
    ):
        assert np.isfinite(expected[key]) and 0 <= expected[key] < bound, key
        expected[key] = frozen[key]
    assert actual == saved


def test_generator_independent_and_new_gold_deterministic():
    spec = importlib.util.spec_from_file_location('release_gold',ROOT/'scripts/generate_release_fixtures.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for build in (mod.dare,mod.arx,mod.mimo,mod.pvm):
        generated = build()
        saved = load(generated['fixture_id'])
        if generated['fixture_id'] == 'B-DARE-12x3':
            assert_dare_regeneration_matches_frozen_gold(generated, saved)
        elif generated['fixture_id'] == 'B-ARX-PRBS':
            assert_arx_regeneration_matches_frozen_gold(generated, saved)
        else:
            assert generated == saved
    for name, digest in mod.OLD.items():
        assert hashlib.sha256((FIX/name).read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'unlisted', 'modified'])
def test_verifier_rejects_incomplete_or_untracked_manifest(tmp_path, monkeypatch, damage):
    spec = importlib.util.spec_from_file_location('verify_gold',ROOT/'scripts/verify_fixtures.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for src in FIX.glob('*'):
        if src.is_file():
            (tmp_path/src.name).write_bytes(src.read_bytes())
    manifest = tmp_path/'checksums.sha256'
    lines = manifest.read_text().splitlines()
    if damage == 'missing':
        manifest.write_text('\n'.join(lines[:-1])+'\n')
    elif damage == 'duplicate':
        manifest.write_text('\n'.join(lines+[lines[0]])+'\n')
    elif damage == 'unlisted':
        (tmp_path/'untracked.json').write_text('{}')
    else:
        target = tmp_path/'B-DARE-12x3.json'
        target.write_text(target.read_text()+' ')  # Numerical values unchanged; bytes corrupted.
    monkeypatch.setattr(mod,'FIXTURES_DIR',tmp_path)
    with pytest.raises(ValueError):
        mod.verify_checksums()


def test_dare_regeneration_permits_last_bit_roundoff_only_in_named_fields():
    saved = load('B-DARE-12x3')
    generated = deepcopy(saved)
    for key in ('A', 'B'):
        generated['data'][key]['data'][0] += 1e-14
    for key in ('P', 'K'):
        generated['data']['expected'][key]['data'][0] *= 1 + 1e-14
    generated['data']['expected']['rDARE'] *= 2
    generated['data']['expected']['optimal_cost'] *= 1 + 1e-14
    generated['data']['expected']['closed_loop_poles']['real'][0] += 1e-14
    assert_dare_regeneration_matches_frozen_gold(generated, saved)
    assert saved == load('B-DARE-12x3')


@pytest.mark.parametrize('field', ['A', 'B', 'P', 'K', 'poles', 'rDARE', 'symmetry_error',
                                  'zoh_quadrature_max_error', 'optimal_cost', 'spectral_radius',
                                  'metadata', 'tolerance', 'shape', 'nonfinite'])
def test_dare_regeneration_rejects_corruption(field):
    saved = load('B-DARE-12x3')
    generated = deepcopy(saved)
    data, tol = generated['data'], saved['tolerances']
    if field in ('A', 'B'):
        data[field]['data'][0] += 100 * tol['matrix_atol']
    elif field in ('P', 'K'):
        data['expected'][field]['data'][0] += 1
    elif field == 'poles':
        data['expected']['closed_loop_poles']['real'][0] += 100 * tol['poles_atol']
    elif field in ('rDARE', 'symmetry_error', 'zoh_quadrature_max_error'):
        data['expected'][field] = 1
    elif field in ('optimal_cost', 'spectral_radius'):
        data['expected'][field] += 1
    elif field == 'metadata':
        data['feedback_sign'] = 'positive'
    elif field == 'nonfinite':
        data['expected']['K']['data'][0] = float('nan')
    elif field == 'tolerance':
        generated['tolerances']['K_rel_tol'] *= 10
    else:
        data['expected']['K']['shape'] = [3, 3, 4]
    with pytest.raises(AssertionError):
        assert_dare_regeneration_matches_frozen_gold(generated, saved)
