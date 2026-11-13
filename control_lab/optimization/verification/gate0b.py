"""Ensaio automatizado do Gate G-0B (CL-DIR-001 Seção 14.1).

Cobre LP factível/infactível, bloco PSD 2x2 com variável fora da diagonal,
SDP 3x3 com Slater, estabilização com taxa alpha e BRL H-infinito com
auditoria independente em 5 dimensões e recuperação de controlador.
"""

from __future__ import annotations

import math
import sys
import time
import tracemalloc
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.diagnostics import (
    ControlLabError,
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
    ensure_json_finite,
)

from ..modeling.canonical import compile
from ..modeling.dsl import sdpvar
from ..modeling.templates import continuous_stabilization_lmi, hinf_brl_lmi
from .recovery import recover_controller


def _build_gate_0b_suite() -> dict[str, dict[str, Any]]:
    # 1. T-SDP-A1: LP 1x1 factível na fronteira (min x, x >= 1)
    x_a1 = sdpvar((1, 1), name="x")
    p_a1 = compile(x_a1, [x_a1 >= 1.0], name="G0B-LP-A1")

    # 2. T-SDP-A2: LP/diagonal infactível (x >= 2, x <= 1)
    x_a2 = sdpvar((1, 1), name="x")
    F0_a2 = np.array([[-2.0, 0.0], [0.0, 1.0]], dtype=np.float64)
    F1_a2 = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=np.float64)
    p_a2 = compile(x_a2, [F0_a2 + x_a2 * F1_a2 >= np.zeros((2, 2))], name="G0B-LP-A2")

    # 3. T-SDP-B1: Bloco PSD 2x2 com variável fora da diagonal
    x_b1 = sdpvar((1, 1), name="x")
    F0_b1 = np.eye(2, dtype=np.float64)
    F1_b1 = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.float64)
    p_b1 = compile(x_b1, [F0_b1 + x_b1 * F1_b1 >= np.zeros((2, 2))], name="G0B-PSD2x2-B1")

    # 4. T-SDP-C1: SDP 3x3 com Slater
    x_c1 = sdpvar((2, 1), name="x")
    F0_c1 = np.array([[0.0, -1.0, 0.0], [-1.0, -1.0, 0.0], [0.0, 0.0, -1.0]], dtype=np.float64)
    F1_c1 = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    F2_c1 = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    p_c1 = compile(
        x_c1[0, 0] + x_c1[1, 0],
        [F0_c1 + x_c1[0, 0] * F1_c1 + x_c1[1, 0] * F2_c1 >= np.zeros((3, 3))],
        name="G0B-SDP3x3-C1",
    )

    # 5. T-SDP-D1: Estabilização contínua com alpha=1.0
    A_d1 = np.array([[0.0, 1.0], [2.0, -1.0]], dtype=np.float64)
    B_d1 = np.array([[0.0], [1.0]], dtype=np.float64)
    p_d1 = continuous_stabilization_lmi(A_d1, B_d1, alpha=1.0, feedback_sign="positive", name="G0B-STAB-D1")

    # 6. T-SDP-D2: BRL H-infinito (gamma=3.0 fixo e minimização)
    A_d2 = np.array([[0.0, 1.0], [-1.0, 0.0]], dtype=np.float64)
    B1_d2 = np.array([[0.0], [1.0]], dtype=np.float64)
    B2_d2 = np.array([[0.0], [1.0]], dtype=np.float64)
    C1_d2 = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.float64)
    D11_d2 = np.array([[0.0], [0.0]], dtype=np.float64)
    D12_d2 = np.array([[0.0], [0.5]], dtype=np.float64)
    p_d2_fixed = hinf_brl_lmi(
        A_d2, B1_d2, B2_d2, C1_d2, D11_d2, D12_d2, gamma=3.0, feedback_sign="positive", name="G0B-BRL-D2-FIXED"
    )
    p_d2_min = hinf_brl_lmi(
        A_d2, B1_d2, B2_d2, C1_d2, D11_d2, D12_d2, gamma=None, feedback_sign="positive", name="G0B-BRL-D2-MIN"
    )

    return {
        "LP_A1": {"problem": p_a1, "kind": "optimal", "expected_obj": 1.0, "expected_x": [1.0]},
        "LP_A2_INFEASIBLE": {"problem": p_a2, "kind": "infeasible"},
        "PSD_2x2_B1": {"problem": p_b1, "kind": "optimal", "expected_obj": -1.0, "expected_x": [-1.0]},
        "SDP_3x3_C1": {"problem": p_c1, "kind": "optimal", "expected_obj": 3.0, "expected_x": [1.0, 2.0]},
        "CTRL_STAB_D1": {"problem": p_d1, "kind": "controller"},
        "CTRL_BRL_D2_FIXED": {"problem": p_d2_fixed, "kind": "controller"},
        "CTRL_BRL_D2_MIN": {"problem": p_d2_min, "kind": "controller"},
    }


def run_gate_0b_assay(
    backends: Sequence[str] = ("clarabel_direct", "clarabel_cvxpy"),
    *,
    tolerances: Mapping[str, Any] | None = None,
    track_memory: bool = True,
) -> Result:
    """Executa ensaio completo do Gate G-0B sobre os backends candidatos."""
    from ..backends.capabilities import describe_solver_capabilities
    from ..backends.solve import solve

    prov: Provenance = build_provenance("optimization.verification.run_gate_0b_assay")
    if isinstance(backends, (str, bytes)) or not isinstance(backends, Sequence) or len(backends) == 0:
        raise ValidationError("backends deve ser sequência não vazia de nomes de backends.")

    suite = _build_gate_0b_suite()
    backend_reports: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    is_wasm = sys.platform == "emscripten"
    if not is_wasm:
        warnings_out.append(
            WarningItem(
                code="GATE0B_LOCAL_CPYTHON_ONLY",
                message=(
                    "Ensaio Gate G-0B executado em CPython local; aprovação final de browser requer "
                    "repetição em Pyodide em dois navegadores (Seção 14.1)."
                ),
            )
        )

    n_passed_backends = 0
    for bname in backends:
        caps = describe_solver_capabilities(bname)
        if not caps["available"] or not caps["psd"]:
            backend_reports[bname] = {
                "capabilities": caps,
                "passed": False,
                "reason": caps.get("reason") or "backend_unavailable_or_no_psd",
                "cases": {},
            }
            continue

        case_reports: dict[str, Any] = {}
        all_cases_ok = True

        for case_id, spec in suite.items():
            prob = spec["problem"]
            t0 = time.perf_counter()
            mem_peak_kb: float | None = None
            started_trace = False
            if track_memory and not tracemalloc.is_tracing():
                tracemalloc.start()
                started_trace = True
            elif track_memory and tracemalloc.is_tracing():
                tracemalloc.reset_peak()

            try:
                res = solve(prob, backend=bname, tolerances=tolerances, verify_solution=True)
                elapsed_s = time.perf_counter() - t0
                if started_trace:
                    _, peak_bytes = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    mem_peak_kb = float(peak_bytes) / 1024.0
                elif track_memory and tracemalloc.is_tracing():
                    _, peak_bytes = tracemalloc.get_traced_memory()
                    mem_peak_kb = float(peak_bytes) / 1024.0

                if res.status == "failure" or res.data is None:
                    all_cases_ok = False
                    case_reports[case_id] = {
                        "passed": False,
                        "result_status": res.status,
                        "error": res.error.to_dict() if res.error else None,
                        "elapsed_s": elapsed_s,
                        "peak_memory_kb": mem_peak_kb,
                    }
                    continue

                d = res.data
                kind = spec["kind"]
                case_ok = True
                ctrl_validity = d["controller_validity"]

                if kind == "optimal":
                    x_got = np.asarray(d["x"]["data"], dtype=np.float64)
                    obj_got = float(d["objective"])
                    x_exp = np.asarray(spec["expected_x"], dtype=np.float64)
                    obj_exp = float(spec["expected_obj"])
                    case_ok = (
                        d["solver_status"] == "optimal"
                        and d["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
                        and d["certificate_status"] == "validated_dual"
                        and bool(np.allclose(x_got, x_exp, atol=1e-5))
                        and math.isclose(obj_got, obj_exp, abs_tol=1e-5)
                    )
                elif kind == "infeasible":
                    case_ok = (
                        d["solver_status"] == "primal_infeasible"
                        and d["audit_feasibility"] == "violated"
                        and d["certificate_status"] == "validated_infeasibility"
                    )
                elif kind == "controller":
                    rec = recover_controller(prob, res, tolerances=tolerances)
                    if rec.status == "failure" or rec.data is None:
                        case_ok = False
                        ctrl_validity = "violated"
                    else:
                        ctrl_validity = rec.data["controller_validity"]
                        case_ok = (
                            d["audit_feasibility"] in ("strictly_feasible", "approximately_feasible")
                            and d["certificate_status"] == "validated_dual"
                            and ctrl_validity == "verified_under_assumptions"
                        )

                if not case_ok:
                    all_cases_ok = False

                case_reports[case_id] = {
                    "passed": case_ok,
                    "solver_status": d["solver_status"],
                    "audit_feasibility": d["audit_feasibility"],
                    "certificate_status": d["certificate_status"],
                    "controller_validity": ctrl_validity,
                    "objective": d.get("objective"),
                    "elapsed_s": elapsed_s,
                    "peak_memory_kb": mem_peak_kb,
                }
            except ControlLabError as exc:
                if started_trace and tracemalloc.is_tracing():
                    tracemalloc.stop()
                all_cases_ok = False
                case_reports[case_id] = {
                    "passed": False,
                    "error": exc.to_typed_error().to_dict(),
                }

        if all_cases_ok:
            n_passed_backends += 1
        backend_reports[bname] = {
            "capabilities": caps,
            "passed": all_cases_ok,
            "cases": case_reports,
        }

    overall_passed = n_passed_backends == len(backends)
    if overall_passed:
        status_out = "warning" if warnings_out else "success"
    elif n_passed_backends > 0:
        status_out = "warning"
    else:
        status_out = "inconclusive"

    return Result(
        status=status_out,
        data=ensure_json_finite(
            {
                "gate": "G-0B",
                "environment": "pyodide_wasm" if is_wasm else "cpython_local",
                "browser_matrix_pending": not is_wasm,
                "overall_passed": overall_passed,
                "backends": backend_reports,
                "summary": {
                    "n_backends_tested": len(backends),
                    "n_backends_passed": n_passed_backends,
                    "n_cases_per_backend": len(suite),
                },
            }
        ),
        assumptions={
            "local_cpython_assay": not is_wasm,
            "requires_two_browsers_in_pyodide_for_final_gate": True,
        },
        diagnostics=ensure_json_finite(
            {
                "overall_passed": overall_passed,
                "n_backends_passed": n_passed_backends,
                "n_backends_tested": len(backends),
            }
        ),
        provenance=prov,
        warnings=tuple(warnings_out),
        error=None,
    )
