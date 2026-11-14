"""Second-author cross-oracles of the exact four §10.4 fixture problems.

Imports only NumPy/SciPy, never generators or control_lab. PVM uses adaptive
DOP853 integration against author's piecewise analytic arrays; MIMO uses dense
linear solve/SVD against adjugate/eigenvalue references; ARX uses NumPy least
squares and direct recurrences; DARE independently re-derives the ZOH block exp.
"""
import json
from pathlib import Path
import numpy as np
from scipy import integrate, linalg, optimize

ROOT = Path(__file__).resolve().parents[2]


def fixture(name):
    value = json.loads((ROOT / 'contracts/fixtures' / (name + '.json')).read_text())
    return value['data'], value['tolerances']


def arr(t):
    return np.array(t['data'], dtype=float).reshape(t['shape'], order=t['order'])


def complex_array(t):
    return (np.array(t['real']) + 1j * np.array(t['imag'])).reshape(t['shape'])


def test_independent_dare_exact_discretization_and_solution():
    d, tol = fixture('B-DARE-12x3')
    ac, bc = arr(d['continuous']['A']), arr(d['continuous']['B'])
    n, m = bc.shape
    block = np.zeros((n + m, n + m))
    block[:n, :n], block[:n, n:] = ac, bc
    zoh = linalg.expm(d['dt'] * block)
    a, b, q, r = [arr(d[key]) for key in ('A', 'B', 'Q', 'R')]
    np.testing.assert_allclose(a, zoh[:n, :n], atol=tol['matrix_atol'], rtol=0)
    np.testing.assert_allclose(b, zoh[:n, n:], atol=tol['matrix_atol'], rtol=0)
    p = arr(d['expected']['P'])
    reference = linalg.solve_discrete_are(a, b, q, r)
    np.testing.assert_allclose(p, reference, atol=0, rtol=tol['P_rel_tol'])
    k = np.linalg.solve(r + b.T @ p @ b, b.T @ p @ a)
    np.testing.assert_allclose(k, arr(d['expected']['K']), rtol=tol['K_rel_tol'], atol=1e-12)
    terms = [a.T @ p @ a, -p, -a.T @ p @ b @ k, q]
    residual = np.linalg.norm(sum(terms), 'fro') / (1 + sum(np.linalg.norm(t, 'fro') for t in terms))
    assert residual <= tol['rDARE_max']
    assert np.max(abs(np.linalg.eigvals(a - b @ k))) < 1
    assert np.min(np.linalg.eigvalsh(p)) > 0
    assert d['feedback_sign'] == 'negative'


def test_independent_arx_chronological_holdout_all_arrays():
    d, tol = fixture('B-ARX-PRBS')
    u, y, clean, e = [arr(d[key]).ravel() for key in ('u', 'y', 'clean_y', 'innovations')]
    train, validation = d['splits']['train'], d['splits']['validation']
    assert train == [0, 512] and validation == [512, 768]
    theta0 = arr(d['expected']['generating_theta'])
    for values, innovation in ((y, e), (clean, np.zeros_like(e))):
        prediction = -theta0[0] * values[1:-1] - theta0[1] * values[:-2] + theta0[2] * u[1:-1] + theta0[3] * u[:-2]
        np.testing.assert_allclose(values[2:], prediction + innovation[2:], atol=1e-12, rtol=0)
    phi = np.column_stack((-y[1:511], -y[:510], u[1:511], u[:510]))
    theta, _, rank, singular = np.linalg.lstsq(phi, y[2:512], rcond=None)
    assert rank == d['expected']['rank'] == 4
    np.testing.assert_allclose(theta, arr(d['expected']['theta']), atol=tol['theta_atol'], rtol=0)
    np.testing.assert_allclose(singular, arr(d['expected']['singular_values']), atol=1e-10, rtol=0)
    assert abs(20 * np.log10(np.linalg.norm(clean[2:]) / np.linalg.norm((y-clean)[2:])) - 35) < tol['snr_atol']
    for label, (lo, hi) in [('train', train), ('validation', validation)]:
        actual, input_values = y[lo:hi], u[lo:hi]
        for mode in ('one_step_prediction', 'free_simulation'):
            predicted = actual.copy()
            for k in range(2, hi-lo):
                history = predicted if mode == 'free_simulation' else actual
                predicted[k] = np.dot(theta, [-history[k-1], -history[k-2], input_values[k-1], input_values[k-2]])
            np.testing.assert_allclose(predicted, arr(d['expected']['predictions'][label][mode]).ravel(), atol=tol['prediction_atol'], rtol=0)
            fit = 100 * (1 - np.linalg.norm(actual[2:] - predicted[2:]) / np.linalg.norm(actual[2:] - actual[2:].mean()))
            assert abs(fit - d['expected']['fit'][label][mode]) < tol['fit_atol']
            if label == 'validation':
                assert fit > 90


def test_independent_mimo_full_grid_svd_rga_and_crossings():
    d, tol = fixture('B-MIMO-2x2')
    a, b, c, feed = [arr(d[key]) for key in ('A', 'B', 'C', 'D')]
    g_all, s_all, t_all, rga_all, sv_all = [], [], [], [], []
    for w in arr(d['omega']):
        g = c @ np.linalg.solve(1j*w*np.eye(2)-a, b) + feed
        s = np.linalg.solve(np.eye(2)+g, np.eye(2))
        g_all.append(g); s_all.append(s); t_all.append(np.eye(2)-s)
        rga_all.append(g * np.linalg.inv(g).T)
        sv_all.append(np.linalg.svd(g, compute_uv=False))
    for key, value in [('G',g_all),('S',s_all),('T',t_all),('RGA',rga_all)]:
        np.testing.assert_allclose(value, complex_array(d['expected'][key]), atol=tol['response_atol'], rtol=0)
    np.testing.assert_allclose(sv_all, arr(d['expected']['singular_values']), atol=tol['singular_values_atol'], rtol=0)
    assert all(np.linalg.matrix_rank(arr(case['matrix'])) < 2 for case in d['singular_cases'])
    crossings = d['multiple_crossings']
    def magnitude_minus_one(w):
        return abs(np.polyval(crossings['num'],1j*w)/np.polyval(crossings['den'],1j*w))-1
    grid = np.geomspace(crossings['omega_min'],crossings['omega_max'],10000)
    roots = [optimize.brentq(magnitude_minus_one, lo, hi) for lo,hi in zip(grid[:-1],grid[1:]) if magnitude_minus_one(lo)*magnitude_minus_one(hi)<0]
    assert len(roots) == 3
    np.testing.assert_allclose(roots,crossings['gain_crossings'],atol=tol['crossing_atol'],rtol=0)


def test_independent_pvm_full_state_negative_feedback_linear_and_saturated():
    d, tol = fixture('B-PVM-LQR')
    a,b,k,q,r,p = [arr(d[key]) for key in ('A','B','K','Q','R','P')]
    np.testing.assert_allclose(linalg.solve_continuous_are(a,b,q,r),p,atol=tol['gain_atol'],rtol=0)
    t, x0 = arr(d['t']), arr(d['x0'])
    assert d['feedback_sign'] == 'negative'
    assert d['external_pathview_verified'] is False
    assert d['gate_status'] == 'PENDING_G0D'
    for case in d['cases']:
        c, feed, n, reference = [arr(case[key]) for key in ('C','D','reference_map','r')]
        assert n.shape == (b.shape[1], reference.shape[1])
        np.testing.assert_allclose(reference, np.tile(reference[0],(len(t),1)),atol=0,rtol=0)
        def control(x):
            value = n @ reference[0] - k @ x
            sat = case['saturation']
            return np.clip(value,sat['u_min'],sat['u_max']) if sat['enabled'] else value
        solution = integrate.solve_ivp(lambda time,x: a @ x + b @ control(x),(t[0],t[-1]),x0,t_eval=t,method='DOP853',rtol=2e-12,atol=2e-14,max_step=.01)
        assert solution.success
        x = solution.y.T
        u = np.array([control(value) for value in x])
        y = x @ c.T + u @ feed.T
        for key,value in [('x',x),('u',u),('y',y)]:
            np.testing.assert_allclose(value,arr(case['expected'][key]),atol=tol['trajectory_atol'],rtol=0)
