#!/usr/bin/env python3
"""Independent F9 release oracles. Never imports control_lab or rewrites old gold."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import scipy
import scipy.linalg as la
import scipy.signal as signal

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'contracts/fixtures'
OLD = {
    'B-CARE-02.json': 'f08f9fe28302c1704554460eb660a00c2911b75272358872672bbbb5068e516f',
    'B-CARE-12x3.json': '0bacb2e43ebfb4a7803cd223de8c219deda4876a180175af30f20cd07f8686a4',
    'B-SDP-A-D.json': '4377341309c5df1df3c814e3f1a3d38ea3783232c3f4ae84e201f829e5f33076',
}


def tensor(x):
    a = np.asarray(x, dtype=float)
    return dict(shape=list(a.shape), dtype='float64', order='C', data=a.ravel().tolist())


def arr(x):
    return np.array(x['data']).reshape(x['shape'])


def pair(x):
    a = np.asarray(x, dtype=complex)
    return dict(shape=list(a.shape), real=a.real.ravel().tolist(), imag=a.imag.ravel().tolist())


def fixture(name, kind, tests, description, data, oracle, tolerances):
    return dict(fixture_id=name, schema_version='1.0.0', benchmark_type=kind,
                description=description, normative_tests=tests, tolerances=tolerances,
                provenance=dict(oracle=oracle, generated_by='scripts/generate_release_fixtures.py',
                                python_version='3.12.14', lib_versions={'numpy': '2.3.5', 'scipy': '1.17.0'},
                                hardware='IEEE-754 float64 CPU; BLAS last-bit variation permitted by tolerances',
                                scope='independent_cpython_oracle_only; no Wasm or official PathView acceptance'), data=data)


def dare():
    old = json.loads((DEST / 'B-CARE-12x3.json').read_text())['data']
    A, B, C, D, Q, R, x0 = [arr(old[k]) for k in ('A', 'B', 'C', 'D', 'Q', 'R', 'x0')]
    dt = .05
    Ad, Bd, _, _, _ = signal.cont2discrete((A, B, C, D), dt, method='zoh')
    # Independent quadrature cross-check of B integral and exp(A dt).
    import scipy.integrate as integrate
    Bd_quad = integrate.quad_vec(lambda s: la.expm(A*s) @ B, 0., dt, epsabs=1e-13)[0]
    assert np.max(np.abs(Bd-Bd_quad)) < 1e-13
    P = la.solve_discrete_are(Ad, Bd, Q, R)
    K = la.solve(R + Bd.T@P@Bd, Bd.T@P@Ad)
    terms = [Ad.T@P@Ad, -P, -Ad.T@P@Bd@K, Q]
    residual = la.norm(sum(terms), 'fro') / (1 + sum(la.norm(z, 'fro') for z in terms))
    poles = np.sort_complex(la.eigvals(Ad-Bd@K))
    assert residual < 1e-12 and np.max(abs(poles)) < 1
    data = dict(dt=dt, discretization={'method': 'exact ZOH', 'formula': 'Ad=exp(Ac*ts); Bd=integral_0^ts exp(Ac*s)Bc ds',
                'cost': 'Q,R are per-sample discrete weights, not discretized continuous cost'},
                continuous={k: old[k] for k in ('A','B','C','D')}, feedback_sign='negative',
                **{k:tensor(v) for k,v in zip(('A','B','C','D','Q','R','x0'),(Ad,Bd,C,D,Q,R,x0))},
                expected=dict(P=tensor(P), K=tensor(K), closed_loop_poles=pair(poles), rDARE=residual,
                              spectral_radius=float(max(abs(poles))), symmetry_error=float(la.norm(P-P.T)/(1+la.norm(P))),
                              optimal_cost=float((x0.T@P@x0).item()), zoh_quadrature_max_error=float(np.max(abs(Bd-Bd_quad)))))
    return fixture('B-DARE-12x3','dare_numerical',['T-CARE-02'],'12x3 exact ZOH of preserved B-CARE-12x3; discrete LQR reference.',data,
                   'SciPy cont2discrete + quad_vec/expm cross-check; solve_discrete_are + independent residual',
                   {'matrix_atol':1e-12,'P_rel_tol':1e-7,'K_rel_tol':1e-7,'rDARE_max':1e-9,'poles_atol':1e-7,'symmetry_error_max':1e-12})


def evaluate_arx(u, y, theta, free):
    out = y.copy()
    for k in range(2,len(y)):
        past = out if free else y
        out[k] = -theta[0]*past[k-1]-theta[1]*past[k-2]+theta[2]*u[k-1]+theta[3]*u[k-2]
    return out


def arx():
    n, split, dt, seed = 768, 512, .1, 20261114
    # Maximal-length LFSR polynomial x^10+x^3+1, all-ones initial state.
    bits, _ = signal.max_len_seq(10, state=np.ones(10,dtype=int), length=n)
    u = 2.*bits-1.
    theta = np.array([-.9,.2,.7,.15])
    clean = np.zeros(n)
    for k in range(2,n):
        clean[k] = -theta[0]*clean[k-1]-theta[1]*clean[k-2]+theta[2]*u[k-1]+theta[3]*u[k-2]
    noise = np.random.Generator(np.random.PCG64(seed)).standard_normal(n)
    noise[:2] = 0
    # Equation noise filtered by 1/A, scale to exactly 35 dB output SNR.
    colored = signal.lfilter([1.],[1.,*theta[:2]],noise)
    scale = np.linalg.norm(clean[2:]) / (10**(35/20)*np.linalg.norm(colored[2:]))
    e = noise*scale
    y = clean + colored*scale
    phi = np.array([[-y[k-1],-y[k-2],u[k-1],u[k-2]] for k in range(2,split)])
    est, _, rank, svals = la.lstsq(phi, y[2:split], lapack_driver='gelsd')
    expected = dict(theta=tensor(est), generating_theta=tensor(theta), rank=int(rank), singular_values=tensor(svals),
                    poles=pair(np.sort_complex(np.roots([1.,*est[:2]]))), fit={}, predictions={})
    for part, sl in [('train',slice(0,split)),('validation',slice(split,n))]:
        expected['fit'][part] = {}
        expected['predictions'][part] = {}
        for mode in ('one_step_prediction','free_simulation'):
            pred = evaluate_arx(u[sl],y[sl],est,mode=='free_simulation')
            fit = 100*(1-la.norm(y[sl][2:]-pred[2:])/la.norm(y[sl][2:]-np.mean(y[sl][2:])))
            expected['fit'][part][mode] = float(fit)
            expected['predictions'][part][mode] = tensor(pred[:,None])
    assert rank == 4 and min(expected['fit']['validation'].values()) > 90
    data = dict(na=2,nb=2,nk=1,n_samples=n,dt=dt,initial_conditions=[0.,0.],
                equation='y[k]-.9*y[k-1]+.2*y[k-2]=.7*u[k-1]+.15*u[k-2]+e[k]',
                prbs={'generator':'SciPy max_len_seq', 'bits':10,'polynomial':'x^10+x^3+1','initial_state':[1]*10},
                noise={'generator':'NumPy PCG64 standard_normal; first two innovations zero','seed':seed,
                       'structure':'white equation error; output noise filtered by 1/A','innovation_scale':float(scale),
                       'snr_db':35.,'snr_definition':'20 log10 norm(clean[2:])/norm(y-clean)[2:]'},
                splits={'train':[0,split],'validation':[split,n],'indexing':'zero-based half-open; no overlap; first 2 samples initialize each recurrence'},
                t=tensor(np.arange(n)*dt),u=tensor(u[:,None]),y=tensor(y[:,None]),clean_y=tensor(clean[:,None]),
                innovations=tensor(e[:,None]),expected=expected)
    return fixture('B-ARX-PRBS','arx_prbs',['T-ID-01','T-ID-03'],'Full PRBS dataset, seeded equation noise and chronological independent holdout.',data,
                   'Known-coefficient recurrence + SciPy LAPACK gelsd (independent of production QR); explicit recurrence/FIT',
                   {'theta_atol':1e-10,'prediction_atol':1e-9,'fit_atol':1e-8,'pole_atol':1e-9,'planted_coefficient_atol':.03,'snr_atol':1e-10})


def mimo():
    w = np.r_[0.,np.logspace(-3,3,61)]
    M = np.array([[2.,1.],[.5,3.]])
    # G(s)=M/(s+1); RGA constant and real analytically.
    G = M[None,:,:]/(1+1j*w[:,None,None])
    rga = np.broadcast_to(np.array([[12/11,-1/11],[-1/11,12/11]]), G.shape).copy()
    sv0 = np.sqrt(np.sort(np.linalg.eigvalsh(M.T@M))[::-1])
    sv = sv0[None,:]/np.sqrt(1+w[:,None]**2)
    S, T = [], []
    for z in 1+1j*w:
        # Explicit 2x2 adjugate, not production linear solve.
        H = z*np.eye(2)+M
        adj = np.array([[H[1,1],-H[0,1]],[-H[1,0],H[0,0]]])
        s = z*adj/(H[0,0]*H[1,1]-H[0,1]*H[1,0])
        S.append(s)
        T.append(M@adj/(H[0,0]*H[1,1]-H[0,1]*H[1,0]))
    # Multiple crossings: |11(s+1)/((s+.1)(s²+.2s+100))|=1.
    # In z=w²: (z+.01)*((100-z)^2+.04*z)-121*(z+1)=0.
    poly = np.polymul([1.,.01],[1.,-199.96,10000.])-np.array([0.,0.,121.,121.])
    roots = np.roots(poly)
    crossings = sorted(float(np.sqrt(z.real)) for z in roots if abs(z.imag)<1e-9 and z.real>0)
    assert len(crossings)==3
    data = dict(A=tensor(-np.eye(2)),B=tensor(np.eye(2)),C=tensor(M),D=tensor(np.zeros((2,2))),dt=None,
                formula='G(s)=[[2,1],[.5,3]]/(s+1); L=G; negative unity feedback',omega=tensor(w),
                expected=dict(G=pair(G),RGA=pair(rga),singular_values=tensor(sv),S=pair(S),T=pair(T),
                              max_identity_residual=float(np.max(abs(np.array(S)+np.array(T)-np.eye(2))))),
                singular_cases=[{'name':'rank_one_all_frequencies','matrix':tensor([[1.,2.],[2.,4.]]),'expected_rga_status':'undefined'},
                                {'name':'zero_matrix','matrix':tensor(np.zeros((2,2))),'expected_rga_status':'undefined'}],
                multiple_crossings={'num':[11.,11.],'den':np.polymul([1.,.1],[1.,.2,100.]).tolist(),
                                    'omega_min':1e-4,'omega_max':1e3,'gain_crossings':crossings,'magnitude_polynomial_in_w_squared':poly.tolist()})
    return fixture('B-MIMO-2x2','mimo_freq',['T-MIMO-01','T-MIMO-02','T-FREQ-02'],'Analytical full frequency grid and separate singular cases; auxiliary multiple-crossing SISO.',data,
                   'Closed-form 2x2 adjugate/RGA; eigenvalues of M.T M; polynomial magnitude crossing roots',
                   {'response_atol':1e-11,'identity_atol':1e-11,'singular_values_atol':1e-11,'crossing_atol':1e-7})


def scalar_curve(a, v, x0, t, limit):
    eq = v/(1-a)
    if limit is None or abs(v-x0) <= limit:
        return eq+(x0-eq)*np.exp((a-1)*t), None
    saturated_u = float(np.clip(v-x0,-limit,limit))
    eq_sat = -saturated_u/a
    threshold = v-saturated_u
    switch = float(np.log((threshold-eq_sat)/(x0-eq_sat))/a)
    assert switch > 0 and abs(v-eq) <= limit+1e-14
    pre = eq_sat+(x0-eq_sat)*np.exp(a*t)
    post = eq+(threshold-eq)*np.exp((a-1)*(t-switch))
    return np.where(t<=switch,pre,post), switch


def pvm():
    A,B,K,Q,R = np.diag([-1.,-2.]),np.eye(2),np.eye(2),np.diag([3.,5.]),np.eye(2)
    t = np.linspace(0,4,81)
    x0 = np.array([1.,-.5])
    cases = []
    for label,C,N,ref in [('C_identity',np.eye(2),np.eye(2),np.array([.4,-.2])),
                           ('C_not_identity_m_ne_p',np.array([[1.,2.]]),np.array([[1.],[.5]]),np.array([.4]))]:
        for enabled in (False,True):
            v = N@ref
            curves = [scalar_curve(a,vi,xi,t,.2 if enabled else None) for a,vi,xi in zip(np.diag(A),v,x0)]
            x = np.column_stack([c[0] for c in curves])
            raw = v[None,:]-x
            u = np.clip(raw,-.2,.2) if enabled else raw
            y = x@C.T
            cases.append(dict(name=label+('_sat_on' if enabled else '_sat_off'),C=tensor(C),D=tensor(np.zeros((C.shape[0],2))),
                              reference_map=tensor(N),r=tensor(np.tile(ref,(len(t),1))),
                              saturation={'enabled':enabled,'u_min':-.2,'u_max':.2},
                              expected=dict(x=tensor(x),u=tensor(u),y=tensor(y),switch_times=[c[1] for c in curves])))
    assert np.max(abs(A.T@np.eye(2)+A-K.T@K+Q)) == 0
    data = dict(A=tensor(A),B=tensor(B),Q=tensor(Q),R=tensor(R),K=tensor(K),P=tensor(np.eye(2)),x0=tensor(x0),t=tensor(t),dt=None,
                feedback_sign='negative',equations={'plant':'xdot=A*x+B*u; y=C*x+D*u',
                'controller':'u_raw=N*r-K*x; u=clip(u_raw,u_min,u_max) only when saturation enabled',
                'reference':'r has p_ref columns; N is m by p_ref; K reads full state x, never y',
                'linear_solution':'x_i=v_i/(1-a_i)+(x0_i-v_i/(1-a_i))*exp((a_i-1)t)',
                'saturation_solution':'constant saturated u until x=v-u_sat; then continuous linear solution; switch times stored'},
                cases=cases,external_pathview_verified=False,gate_status='PENDING_G0D')
    return fixture('B-PVM-LQR','pvm_lqr',['T-PVM-01'],'Analytical diagonal LQR trajectories with C=I/C!=I, m!=p, full-state feedback and saturation on/off.',data,
                   'Exact CARE P=I,K=I,Q=diag(3,5); closed-form piecewise exponential trajectories (no numerical simulator)',
                   {'trajectory_atol':2e-8,'gain_atol':1e-12,'equation_atol':1e-12})


def main():
    if platform.python_version() != '3.12.14' or np.__version__ != '2.3.5' or scipy.__version__ != '1.17.0':
        raise RuntimeError('Generation requires pinned Python 3.12.14 / NumPy 2.3.5 / SciPy 1.17.0; review version changes independently.')
    for name, digest in OLD.items():
        assert hashlib.sha256((DEST/name).read_bytes()).hexdigest() == digest, f'Old gold changed: {name}'
    for build in (dare,arx,mimo,pvm):
        f = build()
        (DEST/(f['fixture_id']+'.json')).write_text(json.dumps(f,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    files = [DEST/name for name in OLD] + sorted(p for p in DEST.glob('B-*.json') if p.name not in OLD)
    (DEST/'checksums.sha256').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files))
    print('Generated four independent release fixtures; preserved three original byte hashes.')


if __name__ == '__main__':
    main()
