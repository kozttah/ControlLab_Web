#!/usr/bin/env python3
"""Gerador determinístico das fixtures ouro da Frente F9 (CL-DIR-001 Seção 10.4).

Nota de governança (Seção 13.11 / Apêndice E):
Este script pertence exclusivamente à F9 e gera referências a partir de:
- Soluções analíticas exatas em forma fechada (B-CARE-02, B-SDP-A-D A1..D1/D2);
- Oráculo independente CPython (scipy.linalg.solve_continuous_are) para B-CARE-12x3;
NUNCA importa nem executa código do pacote `control_lab`.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import scipy
import scipy.linalg

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "contracts" / "fixtures"


def _tensor(arr: np.ndarray) -> dict[str, Any]:
    arr_c = np.ascontiguousarray(arr, dtype=np.float64)
    return {
        "shape": list(arr_c.shape),
        "dtype": "float64",
        "order": "C",
        "data": [float(x) for x in arr_c.ravel(order="C")],
    }


def _complex_pair(eigs: np.ndarray) -> dict[str, list[float]]:
    # Ordenação determinística por (real, imag) para estabilidade de hash/comparação
    order = np.lexsort((np.imag(eigs), np.real(eigs)))
    sorted_eigs = eigs[order]
    return {
        "real": [float(np.real(z)) for z in sorted_eigs],
        "imag": [float(np.imag(z)) for z in sorted_eigs],
    }


def _provenance(oracle: str, seed: int | None = None) -> dict[str, Any]:
    return {
        "oracle": oracle,
        "generated_by": "scripts/generate_golden_fixtures.py",
        "python_version": platform.python_version(),
        "lib_versions": {
            "numpy": importlib.metadata.version("numpy"),
            "scipy": importlib.metadata.version("scipy"),
        },
        "seed": seed,
    }


def build_b_care_02() -> dict[str, Any]:
    # Sistema 2x1 analítico exato (duplo integrador):
    # A = [[0, 1], [0, 0]], B = [[0], [1]], Q = [[4, 0], [0, 5]], R = [[1]]
    # Solução analítica fechada: P = [[6, 2], [2, 3]], K = [[2, 3]]
    # Polos de malha fechada: eig(A - BK) = {-2, -1}
    A = np.array([[0.0, 1.0], [0.0, 0.0]], dtype=np.float64)
    B = np.array([[0.0], [1.0]], dtype=np.float64)
    C = np.array([[1.0, 0.0]], dtype=np.float64)
    D = np.array([[0.0]], dtype=np.float64)
    Q = np.array([[4.0, 0.0], [0.0, 5.0]], dtype=np.float64)
    R = np.array([[1.0]], dtype=np.float64)
    x0 = np.array([[1.0], [1.0]], dtype=np.float64)

    P = np.array([[6.0, 2.0], [2.0, 3.0]], dtype=np.float64)
    K = np.array([[2.0, 3.0]], dtype=np.float64)
    Acl = A - B @ K
    eigs_cl = np.linalg.eigvals(Acl)
    opt_cost = float((x0.T @ P @ x0)[0, 0])

    # Verificação algébrica independente antes de gravar
    E = A.T @ P + P @ A - P @ B @ np.linalg.solve(R, B.T @ P) + Q
    denom = (
        1.0
        + np.linalg.norm(A.T @ P, "fro")
        + np.linalg.norm(P @ A, "fro")
        + np.linalg.norm(P @ B @ np.linalg.solve(R, B.T @ P), "fro")
        + np.linalg.norm(Q, "fro")
    )
    r_care = float(np.linalg.norm(E, "fro") / denom)
    sym_err = float(np.linalg.norm(P - P.T, "fro") / (1.0 + np.linalg.norm(P, "fro")))
    assert r_care == 0.0, f"Erro inesperado no resíduo analítico: {r_care}"
    assert sym_err == 0.0

    return {
        "fixture_id": "B-CARE-02",
        "schema_version": "1.0.0",
        "benchmark_type": "care_analytical",
        "description": (
            "Planta LTI contínua 2x1 (duplo integrador) com solução analítica exata em forma "
            "fechada P=[[6,2],[2,3]], K=[2,3] e polos em {-2, -1} (Seção 10.4, T-CARE-01)."
        ),
        "normative_tests": ["T-CARE-01"],
        "tolerances": {
            "rCARE_max": 1e-12,
            "symmetry_error_max": 1e-14,
            "P_atol": 1e-12,
            "K_atol": 1e-12,
            "cost_atol": 1e-12,
            "poles_atol": 1e-12,
        },
        "provenance": _provenance("closed_form_analytical_algebra", seed=None),
        "data": {
            "feedback_sign": "negative",
            "dt": None,
            "A": _tensor(A),
            "B": _tensor(B),
            "C": _tensor(C),
            "D": _tensor(D),
            "Q": _tensor(Q),
            "R": _tensor(R),
            "x0": _tensor(x0),
            "expected": {
                "P": _tensor(P),
                "K": _tensor(K),
                "closed_loop_poles": _complex_pair(eigs_cl),
                "optimal_cost": opt_cost,
                "rCARE": r_care,
                "symmetry_error": sym_err,
            },
        },
    }


def build_b_care_12x3() -> dict[str, Any]:
    seed = 20261113
    rng = np.random.default_rng(seed)
    n, m, p = 12, 3, 4

    # Construção determinística de A (12x12) com pelo menos um modo instável (Re(lambda) > 0)
    # Blocos 2x2: um bloco instável (+0.6, +0.25) e 5 blocos amortecidos com acoplamento leve
    A = np.zeros((n, n), dtype=np.float64)
    A[0:2, 0:2] = np.array([[0.6, 0.8], [0.0, 0.25]])
    A[2:4, 2:4] = np.array([[0.0, 1.0], [-2.0, -0.4]])
    A[4:6, 4:6] = np.array([[0.0, 1.0], [-5.0, -0.8]])
    A[6:8, 6:8] = np.array([[-0.3, 1.5], [-1.5, -0.3]])
    A[8:10, 8:10] = np.array([[-0.5, 2.0], [-2.0, -0.5]])
    A[10:12, 10:12] = np.array([[-1.2, 0.3], [0.0, -1.8]])
    # Acoplamento esparso determinístico preservando instabilidade
    coupling = 0.08 * rng.standard_normal((n, n))
    np.fill_diagonal(coupling, 0.0)
    A = A + coupling

    # Matriz B (12x3) determinística garantindo atuabilidade nos modos instáveis e demais blocos
    B = np.zeros((n, m), dtype=np.float64)
    B[0:4, 0] = [1.0, 0.8, 0.2, 1.0]
    B[3:8, 1] = [0.5, 1.0, 0.7, 0.3, 1.0]
    B[7:12, 2] = [0.4, 0.6, 1.0, 0.5, 1.0]
    B = B + 0.05 * rng.standard_normal((n, m))

    C = np.zeros((p, n), dtype=np.float64)
    C[0, 0] = 1.0
    C[1, 2] = 1.0
    C[2, 6] = 1.0
    C[3, 10] = 1.0
    D = np.zeros((p, m), dtype=np.float64)

    Q_diag = np.array([2.0, 1.5, 1.0, 1.0, 1.2, 0.8, 1.0, 1.0, 1.5, 0.9, 1.1, 1.0], dtype=np.float64)
    Q = np.diag(Q_diag)
    R = np.diag([1.0, 1.5, 0.8])
    x0 = np.array([[1.0], [-0.5], [0.5], [0.0], [-0.3], [0.2], [0.4], [-0.2], [0.1], [0.3], [-0.4], [0.2]])

    # Oráculo independente CPython: scipy.linalg.solve_continuous_are
    P = scipy.linalg.solve_continuous_are(A, B, Q, R)
    P = 0.5 * (P + P.T)
    K = np.linalg.solve(R, B.T @ P)

    Acl = A - B @ K
    eigs_open = np.linalg.eigvals(A)
    eigs_cl = np.linalg.eigvals(Acl)
    opt_cost = float((x0.T @ P @ x0)[0, 0])

    R_inv_BT_P = np.linalg.solve(R, B.T @ P)
    E = A.T @ P + P @ A - P @ B @ R_inv_BT_P + Q
    denom = (
        1.0
        + np.linalg.norm(A.T @ P, "fro")
        + np.linalg.norm(P @ A, "fro")
        + np.linalg.norm(P @ B @ R_inv_BT_P, "fro")
        + np.linalg.norm(Q, "fro")
    )
    r_care = float(np.linalg.norm(E, "fro") / denom)
    sym_err = float(np.linalg.norm(P - P.T, "fro") / (1.0 + np.linalg.norm(P, "fro")))
    min_eig_P = float(np.min(np.linalg.eigvalsh(P)))
    max_real_open = float(np.max(np.real(eigs_open)))
    max_real_cl = float(np.max(np.real(eigs_cl)))

    assert max_real_open > 0.1, f"A deve ter modo instável: {max_real_open}"
    assert max_real_cl < -0.05, f"A-BK deve ser estável: {max_real_cl}"
    assert r_care <= 1e-12, f"rCARE muito alto: {r_care}"
    assert min_eig_P > 0.0

    return {
        "fixture_id": "B-CARE-12x3",
        "schema_version": "1.0.0",
        "benchmark_type": "care_numerical",
        "description": (
            "Sistema LTI contínuo determinístico com 12 estados e 3 entradas, contendo modo "
            "instável em A, Q e R SPD explícitas e x0 fixado (Seção 10.4, T-CARE-02)."
        ),
        "normative_tests": ["T-CARE-02"],
        "tolerances": {
            "rCARE_max": 1e-9,
            "symmetry_error_max": 1e-12,
            "P_rel_tol": 1e-7,
            "K_rel_tol": 1e-7,
            "cost_rel_tol": 1e-7,
            "poles_atol": 1e-7,
        },
        "provenance": _provenance("scipy.linalg.solve_continuous_are", seed=seed),
        "data": {
            "feedback_sign": "negative",
            "dt": None,
            "A": _tensor(A),
            "B": _tensor(B),
            "C": _tensor(C),
            "D": _tensor(D),
            "Q": _tensor(Q),
            "R": _tensor(R),
            "x0": _tensor(x0),
            "expected": {
                "P": _tensor(P),
                "K": _tensor(K),
                "open_loop_poles": _complex_pair(eigs_open),
                "closed_loop_poles": _complex_pair(eigs_cl),
                "optimal_cost": opt_cost,
                "rCARE": r_care,
                "symmetry_error": sym_err,
                "min_eig_P": min_eig_P,
                "max_real_open_loop": max_real_open,
                "max_real_closed_loop": max_real_cl,
            },
        },
    }


def build_b_sdp_a_d() -> dict[str, Any]:
    # T-SDP-A1: min x s.t. x >= 1  => F(x) = [-1] + x [1] >= 0
    case_a1 = {
        "test_id": "T-SDP-A1",
        "level": "A",
        "description": "LP/escalar factível na fronteira: min x sujeito a x >= 1.",
        "canonical_sdp": {
            "c": [1.0],
            "c0": 0.0,
            "blocks": [
                {
                    "name": "x_ge_1",
                    "F0": _tensor(np.array([[-1.0]])),
                    "F_k": [_tensor(np.array([[1.0]]))],
                }
            ],
        },
        "expected": {
            "solver_status": "optimal",
            "audit_feasibility": "approximately_feasible",
            "certificate_status": "validated_dual",
            "x_opt": [1.0],
            "obj_opt": 1.0,
            "dual_Z": [_tensor(np.array([[1.0]]))],
            "duality_gap": 0.0,
        },
    }

    # T-SDP-A2: x >= 2 e x <= 1 => diag(x-2, 1-x) >= 0; Farkas Z = I_2
    case_a2 = {
        "test_id": "T-SDP-A2",
        "level": "A",
        "description": "LP/escalar infactível forte: x >= 2 e x <= 1 com certificado de Farkas Z=I_2.",
        "canonical_sdp": {
            "c": [1.0],
            "c0": 0.0,
            "blocks": [
                {
                    "name": "contradictory_bounds",
                    "F0": _tensor(np.array([[-2.0, 0.0], [0.0, 1.0]])),
                    "F_k": [_tensor(np.array([[1.0, 0.0], [0.0, -1.0]]))],
                }
            ],
        },
        "expected": {
            "solver_status": "primal_infeasible",
            "audit_feasibility": "violated",
            "certificate_status": "validated_infeasibility",
            "farkas_Z": [_tensor(np.array([[1.0, 0.0], [0.0, 1.0]]))],
        },
    }

    # T-SDP-A3: min x s.t. x <= 2 => F(x) = [2] + x [-1] >= 0; direção recessiva d = [-1]
    case_a3 = {
        "test_id": "T-SDP-A3",
        "level": "A",
        "description": "LP/escalar ilimitado: min x sujeito a x <= 2 com direção recessiva d=[-1].",
        "canonical_sdp": {
            "c": [1.0],
            "c0": 0.0,
            "blocks": [
                {
                    "name": "x_le_2",
                    "F0": _tensor(np.array([[2.0]])),
                    "F_k": [_tensor(np.array([[-1.0]]))],
                }
            ],
        },
        "expected": {
            "solver_status": "dual_infeasible",
            "audit_feasibility": "strictly_feasible",
            "certificate_status": "validated_unboundedness",
            "feasible_x0": [0.0],
            "recession_direction": [-1.0],
        },
    }

    # T-SDP-B1: min x s.t. [[1, x], [x, 1]] >= 0 => x* = -1 na fronteira
    case_b1 = {
        "test_id": "T-SDP-B1",
        "level": "B",
        "description": "Bloco PSD 2x2 analítico: min x sujeito a [[1,x],[x,1]] >= 0, ótimo de fronteira x*=-1.",
        "canonical_sdp": {
            "c": [1.0],
            "c0": 0.0,
            "blocks": [
                {
                    "name": "psd_2x2",
                    "F0": _tensor(np.array([[1.0, 0.0], [0.0, 1.0]])),
                    "F_k": [_tensor(np.array([[0.0, 1.0], [1.0, 0.0]]))],
                }
            ],
        },
        "expected": {
            "solver_status": "optimal",
            "audit_feasibility": "approximately_feasible",
            "certificate_status": "validated_dual",
            "x_opt": [-1.0],
            "obj_opt": -1.0,
            "boundary_eigenvalues": [0.0, 2.0],
            "dual_Z": [_tensor(np.array([[0.5, 0.5], [0.5, 0.5]]))],
            "duality_gap": 0.0,
        },
    }

    # T-SDP-C1: SDP 3x3, 2 variáveis, interior de Slater x=(3,3), ótimo x*=(1,2), gap=0
    F0_c1 = np.array([[0.0, -1.0, 0.0], [-1.0, -1.0, 0.0], [0.0, 0.0, -1.0]])
    F1_c1 = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    F2_c1 = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    Z_c1 = np.array([[1.0, 1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 0.0]])
    case_c1 = {
        "test_id": "T-SDP-C1",
        "level": "C",
        "description": "SDP 3x3 analítico com interior de Slater estrito e gap primal-dual nulo.",
        "canonical_sdp": {
            "c": [1.0, 1.0],
            "c0": 0.0,
            "blocks": [
                {
                    "name": "psd_3x3",
                    "F0": _tensor(F0_c1),
                    "F_k": [_tensor(F1_c1), _tensor(F2_c1)],
                }
            ],
        },
        "expected": {
            "solver_status": "optimal",
            "audit_feasibility": "approximately_feasible",
            "certificate_status": "validated_dual",
            "slater_x": [3.0, 3.0],
            "x_opt": [1.0, 2.0],
            "obj_opt": 3.0,
            "dual_Z": [_tensor(Z_c1)],
            "duality_gap": 0.0,
        },
    }

    # T-SDP-D1: Estabilização contínua com taxa alpha > 0 (sinal positivo u = Kx)
    # (A Q + B Y) + (A Q + B Y)^T + 2 alpha Q < 0, Q > 0, K = Y Q^{-1}
    A_d1 = np.array([[0.0, 1.0], [2.0, -1.0]], dtype=np.float64)
    B_d1 = np.array([[0.0], [1.0]], dtype=np.float64)
    alpha_d1 = 1.0
    Q_d1 = np.array([[2.0, -3.0], [-3.0, 6.0]], dtype=np.float64)
    Y_d1 = np.array([[-4.0, 0.0]], dtype=np.float64)
    K_d1 = np.linalg.solve(Q_d1.T, Y_d1.T).T  # [-8.0, -4.0]
    Acl_d1 = A_d1 + B_d1 @ K_d1
    eigs_d1 = np.linalg.eigvals(Acl_d1)
    lmi_d1 = (A_d1 @ Q_d1 + B_d1 @ Y_d1) + (A_d1 @ Q_d1 + B_d1 @ Y_d1).T + 2.0 * alpha_d1 * Q_d1
    assert np.min(np.linalg.eigvalsh(Q_d1)) > 0.0
    assert np.max(np.linalg.eigvalsh(lmi_d1)) < 0.0
    assert np.max(np.real(eigs_d1)) < -alpha_d1

    case_d1 = {
        "test_id": "T-SDP-D1",
        "level": "D",
        "description": "Estabilização contínua por LMI com taxa de decaimento alpha=1.0 e sinal positivo u=Kx.",
        "feedback_sign": "positive",
        "A": _tensor(A_d1),
        "B": _tensor(B_d1),
        "alpha": alpha_d1,
        "Q_lmi": _tensor(Q_d1),
        "Y": _tensor(Y_d1),
        "K": _tensor(K_d1),
        "expected": {
            "controller_validity": "verified_under_assumptions",
            "closed_loop_poles": _complex_pair(eigs_d1),
            "max_real_pole": float(np.max(np.real(eigs_d1))),
            "lmi_max_eigenvalue": float(np.max(np.linalg.eigvalsh(lmi_d1))),
            "Q_min_eigenvalue": float(np.min(np.linalg.eigvalsh(Q_d1))),
        },
    }

    # T-SDP-D2: BRL H-infinito generalizado (Seção 6.4)
    A_d2 = np.array([[0.0, 1.0], [-1.0, 0.0]], dtype=np.float64)
    B1_d2 = np.array([[0.0], [1.0]], dtype=np.float64)
    B2_d2 = np.array([[0.0], [1.0]], dtype=np.float64)
    C1_d2 = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.float64)
    D11_d2 = np.array([[0.0], [0.0]], dtype=np.float64)
    D12_d2 = np.array([[0.0], [0.5]], dtype=np.float64)

    Q_d2 = np.array([[2.0, -1.0], [-1.0, 2.0]], dtype=np.float64)
    K_d2 = np.array([[-1.0, -3.0]], dtype=np.float64)
    Y_d2 = K_d2 @ Q_d2  # [1.0, -5.0]
    gamma_d2 = 3.0

    Z_blk = A_d2 @ Q_d2 + B2_d2 @ Y_d2
    W_blk = C1_d2 @ Q_d2 + D12_d2 @ Y_d2
    nw = B1_d2.shape[1]
    nz = C1_d2.shape[0]
    brl_mat = np.block([
        [Z_blk + Z_blk.T, B1_d2, W_blk.T],
        [B1_d2.T, -gamma_d2 * np.eye(nw), D11_d2.T],
        [W_blk, D11_d2, -gamma_d2 * np.eye(nz)],
    ])
    brl_mat = 0.5 * (brl_mat + brl_mat.T)
    max_eig_brl = float(np.max(np.linalg.eigvalsh(brl_mat)))
    Acl_d2 = A_d2 + B2_d2 @ K_d2
    eigs_d2 = np.linalg.eigvals(Acl_d2)
    assert np.min(np.linalg.eigvalsh(Q_d2)) > 0.0
    assert max_eig_brl < -0.1, f"BRL não estritamente negativo: {max_eig_brl}"
    assert np.max(np.real(eigs_d2)) < 0.0

    # Verificação espectral amostral em grade log-espaçada de frequências
    omegas = np.logspace(-3, 3, 500)
    Ccl_d2 = C1_d2 + D12_d2 @ K_d2
    eye_nx = np.eye(A_d2.shape[0], dtype=np.complex128)
    svals = []
    for w in omegas:
        Twz_jw = Ccl_d2 @ np.linalg.solve(1j * w * eye_nx - Acl_d2, B1_d2) + D11_d2
        svals.append(float(np.linalg.svd(Twz_jw, compute_uv=False)[0]))
    hinf_sample = max(svals)
    assert hinf_sample < gamma_d2

    case_d2 = {
        "test_id": "T-SDP-D2",
        "level": "D",
        "description": "BRL H-infinito generalizado com realimentação de estados (sinal positivo u=Kx) e LMI estritamente negativa definida.",
        "feedback_sign": "positive",
        "A": _tensor(A_d2),
        "B1": _tensor(B1_d2),
        "B2": _tensor(B2_d2),
        "C1": _tensor(C1_d2),
        "D11": _tensor(D11_d2),
        "D12": _tensor(D12_d2),
        "gamma": gamma_d2,
        "Q_lmi": _tensor(Q_d2),
        "Y": _tensor(Y_d2),
        "K": _tensor(K_d2),
        "expected": {
            "controller_validity": "verified_under_assumptions",
            "closed_loop_poles": _complex_pair(eigs_d2),
            "brl_max_eigenvalue": max_eig_brl,
            "Q_min_eigenvalue": float(np.min(np.linalg.eigvalsh(Q_d2))),
            "sampled_hinf_norm_max": hinf_sample,
        },
    }

    return {
        "fixture_id": "B-SDP-A-D",
        "schema_version": "1.0.0",
        "benchmark_type": "sdp_suite",
        "description": (
            "Conjunto de casos de referência para validação SDP escada Níveis A–D "
            "(T-SDP-A1, A2, A3, B1, C1, D1, D2) conforme Seções 6.3, 6.4, 6.5 e 10.4."
        ),
        "normative_tests": [
            "T-SDP-A1",
            "T-SDP-A2",
            "T-SDP-A3",
            "T-SDP-B1",
            "T-SDP-C1",
            "T-SDP-D1",
            "T-SDP-D2",
        ],
        "tolerances": {
            "primal_tol": 1e-7,
            "dual_tol": 1e-7,
            "gap_tol": 1e-6,
            "psd_tol": 1e-8,
            "strict_margin": 1e-4,
            "gain_tol": 1e-8,
        },
        "provenance": _provenance("closed_form_analytical_and_spectral_verification", seed=None),
        "data": {
            "cases": {
                "T-SDP-A1": case_a1,
                "T-SDP-A2": case_a2,
                "T-SDP-A3": case_a3,
                "T-SDP-B1": case_b1,
                "T-SDP-C1": case_c1,
                "T-SDP-D1": case_d1,
                "T-SDP-D2": case_d2,
            }
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    content = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main() -> int:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = [
        ("B-CARE-02.json", build_b_care_02()),
        ("B-CARE-12x3.json", build_b_care_12x3()),
        ("B-SDP-A-D.json", build_b_sdp_a_d()),
    ]
    checksum_lines: list[str] = []
    for filename, payload in fixtures:
        digest = _write_json(FIXTURES_DIR / filename, payload)
        checksum_lines.append(f"{digest}  {filename}")
        print(f"[F9-GEN] {filename}: sha256={digest}")

    checksum_path = FIXTURES_DIR / "checksums.sha256"
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(f"[F9-GEN] Manifesto de hashes gravado em {checksum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
