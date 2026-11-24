"""Solver didático de Pontos Interiores Primal-Dual para Programação Semidefinida (SDP).

Fundamentação matemática (CL-DIR-001 Seção 6.5, R-13, ADR-008; Boyd & Vandenberghe, Cap. 11):
- Problema primal canônico:
      min_{x in R^K}   c^T x + c_0
      sujeito a        F_b(x) = F_{b,0} + sum_{k=0}^{K-1} x_k F_{b,k} >= 0   (b = 0..B-1)
                       E x = d                                               (p igualdades)
                       H x <= h                                              (q desigualdades -> blocos 1x1)
- Pré-processamento algébrico sem inversão (`linalg.inv` proibido):
  * Eliminação de igualdades `Ex = d` via SVD em subespaço nulo `x = x_eq + N_eq y`;
  * Ortonormalização da imagem do operador cônico `A_cone` via SVD e detecção explícita
    de direções recessivas não restringidas no núcleo (`Q_N`);
- Fase I (ponto estritamente interior / inviabilidade forte de Farkas):
  * Resolve `min t  s.t.  F_b(z) + t I >= 0,  t_cap + t >= 0`, com saída antecipada para Fase II
    ao atingir interior de Slater estrito, ou extração auditada de certificado de Farkas;
- Fase II (Núcleo Primal-Dual de Seguimento de Caminho):
  * Barreira log-determinante `-sum_b ln det(S_b)` no cone semidefinido positivo;
  * Escalonamento simétrico de Nesterov-Todd (NT) via Cholesky + SVD sem `inv()`;
  * Direção Preditor-Corretor de Mehrotra com centralidade dinâmica `sigma = (mu_aff/mu)^3`;
  * Sistema normal simétrico de Schur resolvido por precondicionamento diagonal de Jacobi + Cholesky
    com refino iterativo; busca de passo fracionário via transformação congruente + `eigvalsh`
    + backtracking em Cholesky exata e polimento final no subespaço dual estacionário.

Aviso normativo (R-13 / ADR-008):
Este módulo possui maturidade estritamente `"experimental"`, não integra `get_backend("auto")`
e toda solução passa pelo verificador independente em 5 dimensões (`verify()`).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Mapping, Sequence

import numpy as np
import scipy.linalg

from control_lab.core.tensors import ensure_finite_float64
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
from control_lab.optimization.backends.base import SDPBackend
from control_lab.optimization.backends.unavailable import EducationalBarrierBackend
from control_lab.optimization.modeling.canonical import CanonicalSDPProblem
from control_lab.optimization.verification.verifier import DEFAULT_SDP_TOLERANCES, verify


from control_lab.optimization.backends.native_core import (
    IterationRecord, NativeSolverConfig as EducationalSolverConfig, solve_native_raw,
)


def solve_sdp_educational_raw(problem, options=None):
    edu_opts = {"use_hsde": False}
    if options is not None:
        edu_opts.update(dict(options))
    raw = solve_native_raw(problem, edu_opts)
    raw.update(backend="educational_primal_dual", maturity="experimental", experimental=True)
    return raw


class EducationalPrimalDualSDPBackend(SDPBackend):
    """Backend didático de Pontos Interiores Primal-Dual em `experimental/sdp_educational/`.

    Segue estritamente R-13 e ADR-008:
    - `maturity = "experimental"` e `is_experimental = True`;
    - Nunca é selecionado automaticamente por `get_backend("auto")`;
    - Toda saída é auditada pelo verificador independente `verify()`.
    """

    name: str = "educational_primal_dual"
    maturity: str = "experimental"
    is_experimental: bool = True

    def __init__(self, *, options: Mapping[str, Any] | None = None) -> None:
        self._cfg = EducationalSolverConfig.from_options(options)
        self._raw_options = dict(options or {})

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "maturity": "experimental",
            "available": True,
            "experimental": True,
            "certified": False,
            "method": "primal_dual_nt_mehrotra_interior_point",
            "psd": True,
            "lp": True,
            "dual": True,
            "infeasibility_certificate": True,
            "unboundedness_certificate": True,
            "warm_start": False,
            "cancellation": False,
            "tolerances": {
                "configurable": True,
                "tol_gap": self._cfg.tol_gap,
                "tol_feas": self._cfg.tol_feas,
                "tol_psd": self._cfg.tol_psd,
                "max_iter": self._cfg.max_iter,
            },
            "reason": None,
            "lib_versions": {
                "numpy": str(np.__version__),
                "scipy": str(scipy.__version__),
            },
        }

    def solve_raw(
        self,
        problem: Any,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged = {**self._raw_options, **dict(options or {})}
        return solve_sdp_educational_raw(problem, options=merged)


def make_educational_barrier_backend(
    *,
    options: Mapping[str, Any] | None = None,
) -> EducationalBarrierBackend:
    """Injeta `solve_sdp_educational_raw` no adaptador `EducationalBarrierBackend` sem acoplar imports em `optimization/`."""
    base_opts = dict(options or {})

    def _runner(prob: CanonicalSDPProblem, call_opts: Mapping[str, Any] | None) -> dict[str, Any]:
        merged = {**base_opts, **dict(call_opts or {})}
        return solve_sdp_educational_raw(prob, options=merged)

    return EducationalBarrierBackend(
        solver_fn=_runner,
        solver_capabilities=EducationalPrimalDualSDPBackend(options=base_opts).capabilities(),
    )


def solve_sdp_educational(
    problem: CanonicalSDPProblem,
    *,
    options: Mapping[str, Any] | None = None,
    tolerances: Mapping[str, Any] | None = None,
    verify_solution: bool = True,
    raise_on_error: bool = False,
) -> Result:
    """Resolve `CanonicalSDPProblem` com o solver primal-dual educacional e audita via `verify()`.

    Retorna `Result` com `maturity="experimental"`, histórico iterativo do caminho central
    e as 5 dimensões de verificação da Tabela 6.3 (`solver_status`, `audit_feasibility`,
    `certificate_status`, `conditioning`, `controller_validity`).
    """
    prov_init: Provenance = build_provenance("experimental.sdp_educational.solve_sdp_educational")
    try:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(
                f"solve_sdp_educational() requer CanonicalSDPProblem, recebido {type(problem).__name__}."
            )
        if not isinstance(verify_solution, bool):
            raise ValidationError("verify_solution deve ser booleano.")

        backend_obj = EducationalPrimalDualSDPBackend(options=options)
        caps = backend_obj.capabilities()
        prov = build_provenance(
            "experimental.sdp_educational.primal_dual",
            tolerances=dict(tolerances) if tolerances is not None else dict(DEFAULT_SDP_TOLERANCES),
            backend=backend_obj.name,
            maturity="experimental",
            lib_versions=caps["lib_versions"],
        )

        raw_out = backend_obj.solve_raw(problem, options=options)
        warnings_list: list[WarningItem] = list(raw_out.get("warnings", ()))
        warnings_list.append(
            WarningItem(
                code="EXPERIMENTAL_EDUCATIONAL_SOLVER",
                message=(
                    "Solução calculada pelo solver didático experimental (experimental/sdp_educational); "
                    "uso restrito a ensino e inspeção de caminho central (R-13 / ADR-008)."
                ),
            )
        )

        data_out: dict[str, Any] = {
            "backend": backend_obj.name,
            "maturity": "experimental",
            "experimental": True,
            "method": raw_out["method"],
            "capabilities": caps,
            "solver_status": raw_out["solver_status"],
            "raw_status": raw_out.get("raw_status"),
            "iterations": raw_out.get("iterations"),
            "solve_time": raw_out.get("solve_time"),
            "objective": raw_out.get("objective"),
            "history": raw_out.get("history", []),
            "phase1_summary": raw_out.get("phase1_summary"),
            "phase2_summary": raw_out.get("phase2_summary"),
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
        ):
            if opt_key in raw_out and raw_out[opt_key] is not None:
                data_out[opt_key] = raw_out[opt_key]

        if "x" in data_out:
            data_out["variables"] = problem.reconstruct_variables(
                ensure_finite_float64(data_out["x"], ndim=1, shape=(problem.n_vars,), name="x")
            )

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
            warnings_list.extend(ver_res.warnings)

            result_status = "warning" if ver_res.status == "success" else ver_res.status
            assumptions = {
                **ver_res.assumptions,
                "backend": backend_obj.name,
                "maturity": "experimental",
                "experimental": True,
                "method": raw_out["method"],
            }
            diagnostics = {
                **ver_res.diagnostics,
                "backend": backend_obj.name,
                "maturity": "experimental",
                "experimental": True,
                "raw_status": raw_out.get("raw_status"),
                "iterations": raw_out.get("iterations"),
                "solve_time": raw_out.get("solve_time"),
            }
        else:
            warnings_list.append(
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
                "maturity": "experimental",
                "experimental": True,
            }
            diagnostics = {
                "solver_status": raw_out["solver_status"],
                "audit_feasibility": "inconclusive",
                "certificate_status": "not_available",
                "backend": backend_obj.name,
                "maturity": "experimental",
                "experimental": True,
            }

        return Result(
            status=result_status,
            data=ensure_json_finite(data_out),
            assumptions=ensure_json_finite(assumptions),
            diagnostics=ensure_json_finite(diagnostics),
            provenance=prov,
            warnings=tuple(warnings_list),
            error=None,
        )

    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions={"maturity": "experimental", "experimental": True},
            diagnostics={"maturity": "experimental", "experimental": True},
            provenance=prov_init,
            warnings=(),
            error=exc.to_typed_error(),
        )
    except Exception as exc:
        err = NumericalInconclusiveError(f"Falha inesperada no solver SDP educacional: {exc}")
        if raise_on_error:
            raise err from exc
        return Result(
            status="failure",
            data=None,
            assumptions={"maturity": "experimental", "experimental": True},
            diagnostics={"maturity": "experimental", "experimental": True},
            provenance=prov_init,
            warnings=(),
            error=err.to_typed_error(),
        )
