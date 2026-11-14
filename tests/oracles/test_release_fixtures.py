"""Frozen independent release gold versus production (CL-DIR-001 §§10.2/10.4).

Never regenerate references from production; official PathView/Wasm gates stay open.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import scipy.linalg as la

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
    # Full state port is mandatory even when output has only one component.
    conn = next(x for x in pvm['graph']['connections'] if x['targetNodeId']=='gain_K')
    assert conn['sourcePortIndex']==1
    out = good(simulate_pvm_graph(pvm,array(d['t']),r=array(case['r']),rtol=1e-11,atol=1e-13))
    for key in ('x','u','y'):
        np.testing.assert_allclose(array(out[key]),array(case['expected'][key]),rtol=0,atol=tol['trajectory_atol'])
    assert d['external_pathview_verified'] is False and d['gate_status']=='PENDING_G0D'
    assert pvm['metadata']['external_pathview_verified'] is False


def test_generator_independent_and_new_gold_deterministic():
    spec = importlib.util.spec_from_file_location('release_gold',ROOT/'scripts/generate_release_fixtures.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for build in (mod.dare,mod.arx,mod.mimo,mod.pvm):
        generated = build()
        saved = load(generated['fixture_id'])
        assert generated == saved
    for name, digest in mod.OLD.items():
        assert hashlib.sha256((FIX/name).read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'unlisted'])
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
    else:
        (tmp_path/'untracked.json').write_text('{}')
    monkeypatch.setattr(mod,'FIXTURES_DIR',tmp_path)
    with pytest.raises(ValueError):
        mod.verify_checksums()
