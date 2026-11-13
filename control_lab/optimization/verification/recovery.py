"""Recuperação e auditoria física/espectral de controladores a partir de soluções SDP (CL-DIR-001 Seção 6.4).

Regras obrigatórias:
- Recuperar ganhos via resolução linear `solve(Q.T, Y.T).T`, nunca por `linalg.inv(Q)`.
- Auditar positividade estrita de Q (autovalores e Cholesky), condicionamento, LMIs reconstruídas
  e espectro de malha fechada antes de emitir `controller_validity="verified_under_assumptions"`.
- Em BRL H-infinito, registrar a planta generalizada e marcar explicitamente que varredura amostral
  em frequência não substitui o certificado rigoroso da LMI BRL.
- Em TS/PDC, validar premissas (rejeitar `polytopic_uncertain`) e não exigir estabilidade individual
  de `A_i + s B_i K_j` para `i != j`.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
import scipy.linalg

from control_lab.core.controllers import PDCController, StateFeedbackController
from control_lab.core.interconnect import get_closed_loop_matrix, interconnect
from control_lab.core.models import StateSpace, TSStateSpace
from control_lab.core.tensors import complex_to_pair, ensure_finite_float64, tensor_to_array
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    NumericalInconclusiveError,
    Provenance,
    Result,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
    ensure_json_finite,
)

from ..modeling.canonical import CanonicalSDPProblem
from ..modeling.svec import symmetry_error_rel
from .verifier import DEFAULT_SDP_TOLERANCES, verify


def pack_variables_to_x(problem: CanonicalSDPProblem, var_values: Mapping[str, Any]) -> np.ndarray:
    """Empacota dicionário {var_name: matriz} no vetor canônico x usando variable_map."""
    if not isinstance(problem, CanonicalSDPProblem):
        raise ValidationError("problem deve ser CanonicalSDPProblem.")
    x_vec = np.zeros((problem.n_vars,), dtype=np.float64)
    vmap = problem.variable_map
    for vname, meta in vmap.items():
        if vname not in var_values:
            raise ValidationError(f"Variável {vname!r} ausente para empacotamento em x.")
        raw = var_values[vname]
        r, c = int(meta["shape"][0]), int(meta["shape"][1])
        offset = int(meta["offset"])
        coords = meta["coords"]
        if isinstance(raw, (int, float, np.integer, np.floating)) and not isinstance(raw, bool) and (r, c) == (1, 1):
            arr = np.array([[float(raw)]], dtype=np.float64)
        else:
            arr = ensure_finite_float64(raw, ndim=2, shape=(r, c), name=vname)
        if meta.get("symmetric"):
            if symmetry_error_rel(arr) > DEFAULT_SDP_TOLERANCES["sym_tol"]:
                raise ValidationError(f"Variável simétrica {vname!r} recebeu matriz assimétrica.")
            arr = 0.5 * (arr + arr.T)
        for idx, (i, j) in enumerate(coords):
            x_vec[offset + idx] = float(arr[int(i), int(j)])
    return x_vec


def _sort_complex_eigs(vals: np.ndarray) -> np.ndarray:
    arr = np.asarray(vals, dtype=np.complex128).ravel()
    if arr.size == 0:
        return arr
    order = np.lexsort((np.imag(arr), np.real(arr)))
    return arr[order]


def _extract_x_from_solution(
    problem: CanonicalSDPProblem,
    solution: Result | Mapping[str, Any],
) -> tuple[np.ndarray | None, dict[str, Any]]:
    if isinstance(solution, Result):
        if solution.data is None:
            return None, {}
        sol_dict = dict(solution.data)
    elif isinstance(solution, Mapping):
        sol_dict = dict(solution)
    else:
        raise ValidationError(f"solution deve ser Result ou Mapping, recebido {type(solution).__name__}.")

    if "x" in sol_dict and sol_dict["x"] is not None:
        raw_x = sol_dict["x"]
        if isinstance(raw_x, Mapping) and "shape" in raw_x and "data" in raw_x:
            x_vec = tensor_to_array(raw_x, expected_ndim=1, expected_shape=(problem.n_vars,), dtype="float64")
        else:
            x_vec = ensure_finite_float64(raw_x, ndim=1, shape=(problem.n_vars,), name="solution.x")
        return x_vec, sol_dict

    # Suporte opcional à auditoria direta via variáveis nomeadas (ex.: Q_lmi/Y/gamma)
    plan = problem.recovery_plan
    if plan and plan.get("Q_var") in sol_dict or "Q_lmi" in sol_dict:
        q_key = str(plan.get("Q_var", "Q"))
        if q_key in sol_dict or "Q_lmi" in sol_dict:
            packed_map: dict[str, Any] = {}
            packed_map[q_key] = sol_dict.get(q_key, sol_dict.get("Q_lmi"))
            if "Y_var" in plan and plan["Y_var"] in sol_dict:
                packed_map[plan["Y_var"]] = sol_dict[plan["Y_var"]]
            if "Y_vars" in plan:
                for yname in plan["Y_vars"]:
                    if yname in sol_dict:
                        packed_map[yname] = sol_dict[yname]
            if plan.get("gamma_var") and plan["gamma_var"] in sol_dict:
                packed_map[plan["gamma_var"]] = sol_dict[plan["gamma_var"]]
            if set(packed_map.keys()) == set(problem.variable_map.keys()):
                x_vec = pack_variables_to_x(problem, packed_map)
                sol_dict = dict(sol_dict)
                sol_dict["x"] = x_vec
                if "solver_status" not in sol_dict:
                    sol_dict["solver_status"] = "optimal"
                return x_vec, sol_dict

    return None, sol_dict


def _failure_result(
    exc: ControlLabError,
    *,
    provenance: Provenance,
    diagnostics: Mapping[str, Any] | None = None,
    assumptions: Mapping[str, Any] | None = None,
    warnings_out: Sequence[WarningItem] = (),
    raise_on_error: bool = False,
) -> Result:
    if raise_on_error:
        raise exc
    return Result(
        status="failure",
        data=None,
        assumptions=dict(assumptions or {}),
        diagnostics=ensure_json_finite(dict(diagnostics or {})),
        provenance=provenance,
        warnings=tuple(warnings_out),
        error=exc.to_typed_error(),
    )


def recover_controller(
    problem: CanonicalSDPProblem,
    solution: Result | Mapping[str, Any],
    *,
    plant: StateSpace | TSStateSpace | None = None,
    tolerances: Mapping[str, Any] | None = None,
    premise_estimator: Any = None,
    raise_on_error: bool = False,
) -> Result:
    """Reconstrói e audita controlador canônico a partir de um CanonicalSDPProblem e sua solução."""
    prov = build_provenance("optimization.verification.recover_controller")
    diagnostics: dict[str, Any] = {"controller_validity": "not_assessed"}
    assumptions: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(problem, CanonicalSDPProblem):
            raise ValidationError(f"recover_controller requer CanonicalSDPProblem, recebido {type(problem).__name__}.")
        plan = problem.recovery_plan
        if not plan or "template_kind" not in plan:
            raise ValidationError(
                "CanonicalSDPProblem não possui recovery_plan com template_kind para recuperação de controlador."
            )

        x_vec, sol_dict = _extract_x_from_solution(problem, solution)
        if x_vec is None:
            diagnostics["controller_validity"] = "not_assessed"
            raise NumericalInconclusiveError(
                "Solução não contém vetor primal x para recuperação de controlador."
            )

        # Auditar solução SDP de forma independente antes de recuperar o controlador
        ver_res = verify(problem, sol_dict, tolerances=tolerances, raise_on_error=True)
        assert ver_res.data is not None
        ver_data = dict(ver_res.data)
        warnings_out.extend(ver_res.warnings)
        diagnostics["verification"] = ver_data

        if ver_data["audit_feasibility"] == "violated" or ver_data["certificate_status"] == "failed_validation":
            diagnostics["controller_validity"] = "violated"
            raise HypothesisViolatedError(
                message=(
                    "Recuperação de controlador bloqueada: solução SDP falhou na auditoria independente "
                    f"(audit_feasibility={ver_data['audit_feasibility']!r}, "
                    f"certificate_status={ver_data['certificate_status']!r})."
                ),
                parameters={
                    "audit_feasibility": ver_data["audit_feasibility"],
                    "certificate_status": ver_data["certificate_status"],
                },
            )
        if ver_data["audit_feasibility"] == "inconclusive":
            diagnostics["controller_validity"] = "not_assessed"
            raise NumericalInconclusiveError(
                "Solução SDP inconclusiva na auditoria independente; não é seguro recuperar controlador."
            )

        # Auditoria estrita da matriz de Lyapunov Q
        q_name = str(plan.get("Q_var", "Q"))
        Q_raw = problem.reconstruct_variable(q_name, x_vec)
        sym_tol = DEFAULT_SDP_TOLERANCES["sym_tol"]
        sym_err_Q = symmetry_error_rel(Q_raw)
        if sym_err_Q > sym_tol:
            diagnostics["controller_validity"] = "violated"
            raise HypothesisViolatedError(
                f"Matriz de Lyapunov {q_name!r} não é simétrica (erro={sym_err_Q:.3e})."
            )
        Q_sym = 0.5 * (Q_raw + Q_raw.T)
        eigs_Q = np.linalg.eigvalsh(Q_sym)
        min_eig_Q = float(np.min(eigs_Q))
        max_eig_Q = float(np.max(eigs_Q))
        if min_eig_Q <= 0.0:
            diagnostics["controller_validity"] = "violated"
            raise HypothesisViolatedError(
                f"Matriz de Lyapunov {q_name!r} não é estritamente definida positiva (min_eig={min_eig_Q:.3e})."
            )
        try:
            scipy.linalg.cho_factor(Q_sym, lower=True, check_finite=True)
        except np.linalg.LinAlgError as exc:
            diagnostics["controller_validity"] = "violated"
            raise HypothesisViolatedError(
                f"Fatoração de Cholesky falhou para matriz de Lyapunov {q_name!r}: {exc}"
            ) from exc

        cond_Q = float(max_eig_Q / min_eig_Q)
        diagnostics["Q_min_eigenvalue"] = min_eig_Q
        diagnostics["Q_max_eigenvalue"] = max_eig_Q
        diagnostics["Q_condition_number"] = cond_Q if math.isfinite(cond_Q) else None
        diagnostics["Q_symmetry_error"] = sym_err_Q

        if not math.isfinite(cond_Q) or cond_Q > 1e8:
            warnings_out.append(
                WarningItem(
                    code="ILL_CONDITIONED_LYAPUNOV_Q",
                    message=f"Matriz Q possui número de condição elevado (cond={cond_Q:.3e}).",
                    details={"Q_condition_number": cond_Q if math.isfinite(cond_Q) else -1.0},
                )
            )

        t_kind = str(plan["template_kind"])
        sign_str = str(plan["feedback_sign"])
        s = 1.0 if sign_str == "positive" else -1.0

        # ------------------------------------------------------------------
        # Casos LTI: continuous_stabilization, regional_pole_placement, hinf_brl
        # ------------------------------------------------------------------
        if t_kind in ("continuous_stabilization", "regional_pole_placement", "hinf_brl"):
            if t_kind == "hinf_brl":
                A = tensor_to_array(plan["A"], expected_ndim=2, dtype="float64")
                B1 = tensor_to_array(plan["B1"], expected_ndim=2, dtype="float64")
                B2 = tensor_to_array(plan["B2"], expected_ndim=2, dtype="float64")
                C1 = tensor_to_array(plan["C1"], expected_ndim=2, dtype="float64")
                D11 = tensor_to_array(plan["D11"], expected_ndim=2, dtype="float64")
                D12 = tensor_to_array(plan["D12"], expected_ndim=2, dtype="float64")
                B = B2
            else:
                A = tensor_to_array(plan["A"], expected_ndim=2, dtype="float64")
                B = tensor_to_array(plan["B"], expected_ndim=2, dtype="float64")

            if plant is not None:
                if not isinstance(plant, StateSpace):
                    raise UnsupportedModelError(f"plant deve ser StateSpace para template {t_kind!r}.")
                if plant.dt is not None:
                    raise UnsupportedModelError(f"plant deve ser contínuo (dt=None), recebido dt={plant.dt}.")
                if not (np.allclose(plant.A, A, atol=1e-10) and np.allclose(plant.B, B, atol=1e-10)):
                    raise ValidationError("Matrizes (A, B) de plant não coincidem com o problema compilado.")

            Y = problem.reconstruct_variable(str(plan.get("Y_var", "Y")), x_vec)
            # Recuperação obrigatória por solve linear (sem inv!)
            K = np.linalg.solve(Q_sym.T, Y.T).T
            if not np.all(np.isfinite(K)):
                diagnostics["controller_validity"] = "violated"
                raise NumericalInconclusiveError("Ganho recuperado K contém valores não finitos.")

            Acl = get_closed_loop_matrix(A, B, K, sign_str)
            cl_eigs = _sort_complex_eigs(np.linalg.eigvals(Acl))
            max_real_cl = float(np.max(np.real(cl_eigs)))
            max_abs_cl = float(np.max(np.abs(cl_eigs)))
            diagnostics["max_real_pole"] = max_real_cl
            diagnostics["max_abs_pole"] = max_abs_cl

            if t_kind == "continuous_stabilization":
                alpha_val = float(plan.get("alpha", 0.0))
                M = A @ Q_sym + s * (B @ Y)
                lmi_mat = 0.5 * ((M + M.T + 2.0 * alpha_val * Q_sym) + (M + M.T + 2.0 * alpha_val * Q_sym).T)
                max_eig_lmi = float(np.max(np.linalg.eigvalsh(lmi_mat)))
                diagnostics["lmi_max_eigenvalue"] = max_eig_lmi
                if max_eig_lmi >= 0.0 or max_real_cl >= -alpha_val:
                    diagnostics["controller_validity"] = "violated"
                    raise HypothesisViolatedError(
                        message=(
                            f"Controlador recuperado falhou na auditoria de decaimento alpha={alpha_val}: "
                            f"max_eig_lmi={max_eig_lmi:.3e}, max_real_pole={max_real_cl:.3e}."
                        )
                    )
                assumptions = {
                    "feedback_sign": sign_str,
                    "alpha": alpha_val,
                    "continuous_time": True,
                }

            elif t_kind == "regional_pole_placement":
                r_val = float(plan["radius"])
                alpha_val = plan.get("alpha")
                M = A @ Q_sym + s * (B @ Y)
                disk = np.block([[-r_val * Q_sym, M], [M.T, -r_val * Q_sym]])
                disk = 0.5 * (disk + disk.T)
                max_eig_disk = float(np.max(np.linalg.eigvalsh(disk)))
                diagnostics["disk_lmi_max_eigenvalue"] = max_eig_disk
                if max_eig_disk >= 0.0 or max_abs_cl >= r_val:
                    diagnostics["controller_validity"] = "violated"
                    raise HypothesisViolatedError(
                        message=(
                            f"Controlador falhou na alocação em disco r={r_val}: "
                            f"max|lambda|={max_abs_cl:.6f}, disk_max_eig={max_eig_disk:.3e}."
                        )
                    )
                if alpha_val is not None:
                    a_f = float(alpha_val)
                    half = 0.5 * ((M + M.T + 2.0 * a_f * Q_sym) + (M + M.T + 2.0 * a_f * Q_sym).T)
                    max_eig_half = float(np.max(np.linalg.eigvalsh(half)))
                    diagnostics["halfplane_lmi_max_eigenvalue"] = max_eig_half
                    if max_eig_half >= 0.0 or max_real_cl >= -a_f:
                        diagnostics["controller_validity"] = "violated"
                        raise HypothesisViolatedError(
                            message=(
                                f"Controlador falhou no semiplano Re(lambda) < -{a_f}: "
                                f"max Re={max_real_cl:.6f}, half_max_eig={max_eig_half:.3e}."
                            )
                        )
                assumptions = {
                    "feedback_sign": sign_str,
                    "radius": r_val,
                    "alpha": alpha_val,
                    "continuous_time": True,
                }

            else:  # hinf_brl
                gamma_var = plan.get("gamma_var")
                if gamma_var is not None:
                    gamma_val = float(problem.reconstruct_variable(str(gamma_var), x_vec)[0, 0])
                else:
                    gamma_val = float(plan["gamma_fixed"])
                if not math.isfinite(gamma_val) or gamma_val <= 0.0:
                    diagnostics["controller_validity"] = "violated"
                    raise HypothesisViolatedError(f"Nível gamma recuperado inválido: {gamma_val!r}.")

                nw = B1.shape[1]
                nz = C1.shape[0]
                Z_blk = A @ Q_sym + s * (B2 @ Y)
                W_blk = C1 @ Q_sym + s * (D12 @ Y)
                brl_mat = np.block(
                    [
                        [Z_blk + Z_blk.T, B1, W_blk.T],
                        [B1.T, -gamma_val * np.eye(nw), D11.T],
                        [W_blk, D11, -gamma_val * np.eye(nz)],
                    ]
                )
                brl_mat = 0.5 * (brl_mat + brl_mat.T)
                max_eig_brl = float(np.max(np.linalg.eigvalsh(brl_mat)))
                diagnostics["brl_max_eigenvalue"] = max_eig_brl
                diagnostics["gamma"] = gamma_val
                if max_eig_brl >= 0.0 or max_real_cl >= 0.0:
                    diagnostics["controller_validity"] = "violated"
                    raise HypothesisViolatedError(
                        message=(
                            f"Auditoria BRL H-infinito falhou: brl_max_eig={max_eig_brl:.3e}, "
                            f"max_real_pole={max_real_cl:.3e}."
                        )
                    )

                # Verificação espectral auxiliar amostral (explicitamente não substituta da LMI BRL)
                Ccl = C1 + s * (D12 @ K)
                eye_nx = np.eye(A.shape[0], dtype=np.complex128)
                omegas = np.concatenate([np.array([0.0]), np.logspace(-3, 3, 500)])
                sampled_svs = [
                    float(
                        np.linalg.svd(
                            Ccl @ np.linalg.solve(1j * float(w) * eye_nx - Acl, B1) + D11,
                            compute_uv=False,
                        )[0]
                    )
                    for w in omegas
                ]
                sampled_hinf = max(sampled_svs)
                diagnostics["sampled_hinf_norm_max"] = sampled_hinf
                diagnostics["sampled_hinf_is_not_rigorous_certificate"] = True
                if sampled_hinf >= gamma_val:
                    diagnostics["controller_validity"] = "violated"
                    raise HypothesisViolatedError(
                        f"Norma H-infinito amostral ({sampled_hinf:.6f}) excedeu gamma={gamma_val:.6f}."
                    )
                assumptions = {
                    "feedback_sign": sign_str,
                    "gamma": gamma_val,
                    "same_generalized_plant_required_for_comparison": True,
                    "continuous_time": True,
                }

            state_coords = plan.get("state_names") if plant is None else plant.state_names
            in_names = plan.get("input_names") if plant is None else plant.input_names
            ctrl_prov = build_provenance(
                f"optimization.{t_kind}",
                model_revision=plan.get("plant_revision") if plant is None else plant.revision,
                feedback_sign=sign_str,
            )
            ctrl = StateFeedbackController(
                K=K,
                feedback_sign=sign_str,
                state_coordinates=state_coords,
                dt=None,
                input_names=in_names,
                provenance=ctrl_prov.to_dict(),
            )

            diagnostics["controller_validity"] = "verified_under_assumptions"
            ver_data["controller_validity"] = "verified_under_assumptions"
            diagnostics["verification"] = ver_data

            data_out: dict[str, Any] = {
                "controller": ctrl.to_dict(),
                "controller_ref": {"id": ctrl.id, "revision": ctrl.revision},
                "controller_kind": ctrl.kind,
                "feedback_sign": sign_str,
                "K": K,
                "Q_lmi": Q_sym,
                "Y": Y,
                "closed_loop_poles": complex_to_pair(cl_eigs),
                "controller_validity": "verified_under_assumptions",
                "conditioning": ver_data["conditioning"],
                "verification": ver_data,
            }
            if t_kind == "hinf_brl":
                data_out["gamma"] = diagnostics["gamma"]
                data_out["sampled_hinf_norm_max"] = diagnostics["sampled_hinf_norm_max"]
            if plant is not None:
                cl_ss = interconnect(plant, ctrl, sign_convention=sign_str)
                data_out["closed_loop"] = cl_ss.to_dict()

            status_out = "warning" if warnings_out else "success"
            return Result(
                status=status_out,
                data=ensure_json_finite(data_out),
                assumptions=ensure_json_finite(assumptions),
                diagnostics=ensure_json_finite(diagnostics),
                provenance=ctrl_prov,
                warnings=tuple(warnings_out),
                error=None,
            )

        # ------------------------------------------------------------------
        # Caso TS/PDC
        # ------------------------------------------------------------------
        if t_kind == "ts_pdc_stabilization":
            verts_plan = plan["vertices"]
            r = len(verts_plan)
            A_list = [tensor_to_array(v["A"], expected_ndim=2, dtype="float64") for v in verts_plan]
            B_list = [tensor_to_array(v["B"], expected_ndim=2, dtype="float64") for v in verts_plan]
            alpha_val = float(plan.get("alpha", 0.0))

            if plant is not None:
                if not isinstance(plant, TSStateSpace):
                    raise UnsupportedModelError(f"plant deve ser TSStateSpace, recebido {type(plant).__name__}.")
                if plant.kind == "polytopic_uncertain":
                    diagnostics["controller_validity"] = "violated"
                    raise HypothesisViolatedError(
                        "PDCController não pode ser recuperado/aplicado em TSStateSpace(kind='polytopic_uncertain')."
                    )
                if plant.id != plan["ts_model_id"] or plant.revision != plan["ts_model_revision"]:
                    diagnostics["controller_validity"] = "violated"
                    raise HypothesisViolatedError(
                        "plant TSStateSpace não coincide com id/revision usados na compilação da LMI PDC."
                    )

            Y_list = [problem.reconstruct_variable(yname, x_vec) for yname in plan["Y_vars"]]
            K_list = [np.linalg.solve(Q_sym.T, Yi.T).T for Yi in Y_list]
            for idx, Ki in enumerate(K_list):
                if not np.all(np.isfinite(Ki)):
                    diagnostics["controller_validity"] = "violated"
                    raise NumericalInconclusiveError(f"Ganho K_i[{idx}] contém NaN/Inf.")

            def _g_mat(i: int, j: int) -> np.ndarray:
                M_ij = A_list[i] @ Q_sym + s * (B_list[i] @ Y_list[j])
                return 0.5 * ((M_ij + M_ij.T + 2.0 * alpha_val * Q_sym) + (M_ij + M_ij.T + 2.0 * alpha_val * Q_sym).T)

            diag_max_eigs: list[float] = []
            cross_max_eigs: list[float] = []
            for i in range(r):
                me_ii = float(np.max(np.linalg.eigvalsh(_g_mat(i, i))))
                diag_max_eigs.append(me_ii)
                if me_ii >= 0.0:
                    diagnostics["controller_validity"] = "violated"
                    raise HypothesisViolatedError(f"LMI diagonal G_{i}{i} >= 0 (max_eig={me_ii:.3e}).")
            for i in range(r):
                for j in range(i + 1, r):
                    me_ij = float(np.max(np.linalg.eigvalsh(_g_mat(i, j) + _g_mat(j, i))))
                    cross_max_eigs.append(me_ij)
                    if me_ij >= 0.0:
                        diagnostics["controller_validity"] = "violated"
                        raise HypothesisViolatedError(f"LMI cruzada G_{i}{j}+G_{j}{i} >= 0 (max_eig={me_ij:.3e}).")

            diagnostics["diag_lmi_max_eigenvalues"] = diag_max_eigs
            diagnostics["cross_lmi_max_eigenvalues"] = cross_max_eigs

            ts_kind = str(plan.get("ts_kind", "ts_measured"))
            allowed_kinds = [ts_kind] if ts_kind in ("ts_measured", "ts_partially_observed") else ["ts_measured"]
            ctrl_prov = build_provenance(
                "optimization.ts_pdc_stabilization",
                model_revision=int(plan["ts_model_revision"]),
                feedback_sign=sign_str,
            )
            pdc_ctrl = PDCController(
                K_i=K_list,
                feedback_sign=sign_str,
                membership_ref={
                    "model_id": str(plan["ts_model_id"]),
                    "model_revision": int(plan["ts_model_revision"]),
                    "membership_version": str(plan["membership_version"]),
                },
                measurement_requirements={
                    "required_premise_variables": list(plan["premise_variables"]),
                    "requires_full_state": True,
                    "allowed_ts_kinds": allowed_kinds,
                },
                state_coordinates=plan.get("state_names"),
                dt=None,
                provenance=ctrl_prov.to_dict(),
            )

            # Verificar estabilidade em amostras do simplex convexo (sem exigir A_i + s B_i K_j individual!)
            sample_weights: list[np.ndarray] = []
            for i in range(r):
                w = np.zeros((r,), dtype=np.float64)
                w[i] = 1.0
                sample_weights.append(w)
            sample_weights.append(np.full((r,), 1.0 / r, dtype=np.float64))
            for i in range(r):
                for j in range(i + 1, r):
                    w = np.zeros((r,), dtype=np.float64)
                    w[i] = 0.5
                    w[j] = 0.5
                    sample_weights.append(w)

            worst_real_simplex = -float("inf")
            for w in sample_weights:
                Acl_w = np.zeros_like(A_list[0])
                for i in range(r):
                    for j in range(r):
                        Acl_w += float(w[i] * w[j]) * (A_list[i] + s * (B_list[i] @ K_list[j]))
                worst_real_simplex = max(worst_real_simplex, float(np.max(np.real(np.linalg.eigvals(Acl_w)))))
            diagnostics["worst_sampled_simplex_max_real_pole"] = worst_real_simplex
            if worst_real_simplex >= -alpha_val:
                diagnostics["controller_validity"] = "violated"
                raise HypothesisViolatedError(
                    f"Espectro amostrado no simplex violou taxa alpha={alpha_val}: max_real={worst_real_simplex:.3e}."
                )

            diagnostics["controller_validity"] = "verified_under_assumptions"
            ver_data["controller_validity"] = "verified_under_assumptions"
            diagnostics["verification"] = ver_data

            data_out = {
                "controller": pdc_ctrl.to_dict(),
                "controller_ref": {"id": pdc_ctrl.id, "revision": pdc_ctrl.revision},
                "controller_kind": pdc_ctrl.kind,
                "feedback_sign": sign_str,
                "K_i": K_list,
                "Q_lmi": Q_sym,
                "Y_i": Y_list,
                "controller_validity": "verified_under_assumptions",
                "conditioning": ver_data["conditioning"],
                "verification": ver_data,
            }
            if plant is not None:
                ts_cl = interconnect(
                    plant,
                    pdc_ctrl,
                    sign_convention=sign_str,
                    premise_estimator=premise_estimator,
                )
                data_out["closed_loop"] = ts_cl.to_dict()

            assumptions = {
                "feedback_sign": sign_str,
                "alpha": alpha_val,
                "ts_kind": ts_kind,
                "common_quadratic_lyapunov": True,
                "cross_terms_summed": True,
            }
            return Result(
                status="warning" if warnings_out else "success",
                data=ensure_json_finite(data_out),
                assumptions=ensure_json_finite(assumptions),
                diagnostics=ensure_json_finite(diagnostics),
                provenance=ctrl_prov,
                warnings=tuple(warnings_out),
                error=None,
            )

        raise ValidationError(f"template_kind desconhecido em recovery_plan: {t_kind!r}.")

    except ControlLabError as exc:
        return _failure_result(
            exc,
            provenance=prov,
            diagnostics=diagnostics,
            assumptions=assumptions,
            warnings_out=warnings_out,
            raise_on_error=raise_on_error,
        )
    except Exception as exc:
        err = NumericalInconclusiveError(f"Falha inesperada na recuperação de controlador: {exc}")
        return _failure_result(
            err,
            provenance=prov,
            diagnostics=diagnostics,
            assumptions=assumptions,
            warnings_out=warnings_out,
            raise_on_error=raise_on_error,
        )
