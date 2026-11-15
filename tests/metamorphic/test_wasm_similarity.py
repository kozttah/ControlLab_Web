"""T-CARE-04: independent congruence identities tested in CPython and Wasm."""

import json

import numpy as np
from control_lab.statespace import solve_care
from scripts.browser_harness import browser_harness

SOURCE = """import json, numpy as np
from control_lab.statespace import solve_care
A=np.array([[0.,1.],[0.,0.]])
B=np.array([[0.],[1.]])
Q=np.diag([4.,5.]); R=np.ones((1,1)); x0=np.array([1.,-.5])
T=np.array([[2.,.3],[0.,.7]]); Ti=np.linalg.inv(T)
r=solve_care(A,B,Q,R,x0=x0)
s=solve_care(T@A@Ti,T@B,Ti.T@Q@Ti,R,x0=T@x0)
json.dumps({"base":r.to_dict(),"transformed":s.to_dict(),"T":T.tolist()})"""


def test_similarity_preserves_gain_cost_and_poles_in_wasm(browser_harness):
    report = browser_harness.python(SOURCE)
    native = {}
    exec(SOURCE.rsplit("json.dumps", 1)[0], native)
    base, transformed = report["base"], report["transformed"]
    assert base["status"] == transformed["status"] == "success"

    def matrix(result, key):
        t = result["data"][key]
        return np.array(t["data"]).reshape(t["shape"])

    P, Pt = matrix(base, "P"), matrix(transformed, "P")
    K, Kt = matrix(base, "K"), matrix(transformed, "K")
    T = np.array(report["T"])
    Ti = np.linalg.inv(T)
    np.testing.assert_allclose(Pt, Ti.T @ P @ Ti, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(Kt, K @ Ti, rtol=1e-10, atol=1e-10)
    assert abs(base["data"]["optimal_cost"] - transformed["data"]["optimal_cost"]) < 1e-10
    np.testing.assert_allclose(P, np.array([[6.0, 2.0], [2.0, 3.0]]), atol=1e-10, rtol=0)
    np.testing.assert_allclose(Pt, matrix(native["s"].to_dict(), "P"), atol=1e-10, rtol=1e-10)
    A = np.array([[0.0, 1.0], [0.0, 0.0]])
    B = np.array([[0.0], [1.0]])
    np.testing.assert_allclose(
        np.sort_complex(np.linalg.eigvals(A - B @ K)),
        np.sort_complex(np.linalg.eigvals(T @ A @ Ti - T @ B @ Kt)),
        rtol=1e-10,
        atol=1e-10,
    )
    browser_harness.record("similarity", report)
