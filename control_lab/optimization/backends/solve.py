"""Execução unificada de problemas SDP/LMI retornando Result auditado (CL-DIR-001 Seção 6.2 e 6.3)."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from control_lab.diagnostics import (
    ControlLabError,
    NumericalInconclusiveError,
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
    ensure_json_finite,
)

from ..modeling.canonical import CanonicalSDPProblem
from ..verification.verifier import DEFAULT_SDP_TOLERANCES, verify
from .base import SDPBackend
from .capabilities import get_backend


def solve(
    problem: CanonicalSDPProblem,
    backend: str | SDPBackend = "auto",
    *,
    options: Mapping[str, Any] | None = None,
    tolerances: Mapping[str, Any] | None = None,
    verify_solution: bool = True,
    raise_on_error: bool = False,
) -> Result:
    """Resolve CanonicalSDPProblem via backend selecionado e audita independentemente em Result."""
    prov_init: Provenance = build_provenance("optimization.solve")
    try:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(f"solve() requer CanonicalSDPProblem, recebido {type(problem).__name__}.")
        if not isinstance(verify_solution, bool):
            raise ValidationError("verify_solution deve ser booleano.")

        backend_obj = get_backend(backend, problem=problem)
        caps = backend_obj.capabilities()
        if backend_obj.name == "native_primal_dual" and not verify_solution:
            raise ValidationError("Native SDP requires independent verification.")
        prov = build_provenance(
            f"optimization.solve.{backend_obj.name}",
            tolerances=dict(tolerances) if tolerances is not None else dict(DEFAULT_SDP_TOLERANCES),
            backend=backend_obj.name,
            lib_versions=caps.get("lib_versions", {}),
        )

        raw_out = backend_obj.solve_raw(problem, options=options)
        raw_warnings = list(raw_out.get("warnings", ()))

        if backend_obj.is_experimental:
            raw_warnings.append(
                WarningItem(
                    code="EXPERIMENTAL_BACKEND",
                    message=(
                        f"Solução gerada pelo backend experimental {backend_obj.name!r}; "
                        "uso restrito a fins didáticos/experimentais."
                    ),
                )
            )

        data_out: dict[str, Any] = {
            "backend": backend_obj.name,
            "capabilities": caps,
            "solver_status": raw_out["solver_status"],
            "raw_status": raw_out.get("raw_status"),
            "iterations": raw_out.get("iterations"),
            "solve_time": raw_out.get("solve_time"),
            "objective": raw_out.get("objective"),
        }

        for opt_key in (
            "x",
            "dual_Z",
            "dual_eq",
            "dual_ineq",
            "farkas_Z",
            "farkas_eq",
            "farkas_ineq",
            "recession_direction",
            "feasible_x0",
            "simultaneous_primal_infeasible",
        ):
            if opt_key in raw_out and raw_out[opt_key] is not None:
                data_out[opt_key] = raw_out[opt_key]

        if "x" in data_out:
            data_out["variables"] = problem.reconstruct_variables(np.asarray(data_out["x"], dtype=np.float64))

        if verify_solution:
            ver_res = verify(
                problem,
                raw_out,
                claimed_status=raw_out["solver_status"],
                tolerances=tolerances,
                raise_on_error=True,
            )
            assert ver_res.data is not None
            ver_data = dict(ver_res.data)
            data_out["verification"] = ver_data
            data_out["audit_feasibility"] = ver_data["audit_feasibility"]
            data_out["certificate_status"] = ver_data["certificate_status"]
            data_out["conditioning"] = ver_data["conditioning"]
            data_out["controller_validity"] = ver_data["controller_validity"]
            data_out["residuals"] = ver_data["residuals"]
            raw_warnings.extend(ver_res.warnings)

            result_status = ver_res.status
            if backend_obj.is_experimental and result_status == "success":
                result_status = "warning"
            assumptions = {
                **ver_res.assumptions,
                "backend": backend_obj.name,
                "experimental": bool(backend_obj.is_experimental),
            }
            diagnostics = {
                **ver_res.diagnostics,
                "backend": backend_obj.name,
                "raw_status": raw_out.get("raw_status"),
                "iterations": raw_out.get("iterations"),
                "solve_time": raw_out.get("solve_time"),
            }
        else:
            raw_warnings.append(
                WarningItem(
                    code="UNVERIFIED_SOLVER_OUTPUT",
                    message="Auditoria independente desabilitada (verify_solution=False); saída não certificada.",
                )
            )
            data_out["audit_feasibility"] = "inconclusive"
            data_out["certificate_status"] = "not_available"
            data_out["conditioning"] = {
                "condition_number": None,
                "scaling_warning": False,
                "near_boundary": False,
                "loss_of_significance": False,
            }
            data_out["controller_validity"] = "not_assessed" if problem.recovery_plan else "not_applicable"
            result_status = "warning"
            assumptions = {
                "independent_audit": False,
                "backend": backend_obj.name,
                "experimental": bool(backend_obj.is_experimental),
            }
            diagnostics = {
                "solver_status": raw_out["solver_status"],
                "audit_feasibility": "inconclusive",
                "certificate_status": "not_available",
                "backend": backend_obj.name,
            }

        from .native import within_browser_envelope
        conditioning = data_out.get("conditioning", {})
        recommend_offline = (
            not within_browser_envelope(problem)
            or conditioning.get("status") != "well_conditioned"
            or data_out.get("certificate_status") not in ("validated_dual", "validated_infeasibility", "validated_unboundedness")
            or result_status == "inconclusive"
        )
        diagnostics["offline_recommended"] = recommend_offline
        diagnostics["offline_exports"] = ["optimization.export_cvxpy", "optimization.export_yalmip"]
        if recommend_offline:
            raw_warnings.append(WarningItem(
                code="SDP_OFFLINE_RECOMMENDED",
                message="Execute offline em Python/CVXPY ou MATLAB/YALMIP com MOSEK, Clarabel, SeDuMi ou SDPT3. "
                        "Inspecione condicionamento, resíduos primal/dual e gap antes de usar os ganhos."))
            if result_status == "success":
                result_status = "warning"

        return Result(
            status=result_status,
            data=ensure_json_finite(data_out),
            assumptions=ensure_json_finite(assumptions),
            diagnostics=ensure_json_finite(diagnostics),
            provenance=prov,
            warnings=tuple(raw_warnings),
            error=None,
        )

    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={"offline_recommended": True, "offline_exports": ["optimization.export_cvxpy", "optimization.export_yalmip"]},
            provenance=prov_init,
            warnings=(),
            error=exc.to_typed_error(),
        )
    except Exception as exc:
        err = NumericalInconclusiveError(f"Falha inesperada ao executar solver SDP: {exc}")
        if raise_on_error:
            raise err from exc
        return Result(
            status="failure",
            data=None,
            assumptions={},
            diagnostics={"offline_recommended": True, "offline_exports": ["optimization.export_cvxpy", "optimization.export_yalmip"]},
            provenance=prov_init,
            warnings=(),
            error=err.to_typed_error(),
        )


def solve_and_verify(
    problem: CanonicalSDPProblem,
    backend: str | SDPBackend = "auto",
    *,
    options: Mapping[str, Any] | None = None,
    tolerances: Mapping[str, Any] | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Resolve CanonicalSDPProblem e executa auditoria independente obrigatória."""
    return solve(
        problem,
        backend=backend,
        options=options,
        tolerances=tolerances,
        verify_solution=True,
        raise_on_error=raise_on_error,
    )
