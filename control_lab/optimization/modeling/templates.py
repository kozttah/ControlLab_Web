"""Templates de síntese de controladores por LMIs (CL-DIR-001 Seção 5.7, 6.4 e Apêndice C).

Inclui:
1. Estabilização contínua com taxa de decaimento alpha >= 0 (T-SDP-D1);
2. Alocação regional (D-estabilidade: disco de raio r + semiplano Re(lambda) < -alpha);
3. Síntese H-infinito por Bounded Real Lemma (BRL) generalizado (T-SDP-D2);
4. Síntese Takagi-Sugeno / PDC contínua com expansão dupla i=j e i<j (T-TS-01 / ADR-006).
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.core.controllers import _validate_feedback_sign
from control_lab.core.models import StateSpace, TSStateSpace
from control_lab.core.tensors import array_to_tensor, ensure_finite_float64
from control_lab.diagnostics import DimensionMismatchError, HypothesisViolatedError, UnsupportedModelError, ValidationError

from .canonical import CanonicalSDPProblem, compile
from .dsl import bmat, sdpvar, trace


def _extract_lti_matrices(plant_or_A: Any, B: Any = None) -> tuple[np.ndarray, np.ndarray, StateSpace | None]:
    if isinstance(plant_or_A, StateSpace):
        if B is not None:
            raise ValidationError("Não forneça B separado quando plant_or_A já é StateSpace.")
        if plant_or_A.dt is not None:
            raise UnsupportedModelError(
                message=f"Templates LMI contínuos exigem modelo contínuo (dt=None), recebido dt={plant_or_A.dt}.",
                parameters={"dt": plant_or_A.dt},
                next_step="Forneça um StateSpace contínuo (dt=None).",
            )
        if plant_or_A.n_states < 1 or plant_or_A.n_inputs < 1:
            raise ValidationError(
                message=(
                    f"Templates LMI exigem StateSpace dinâmico com n_states >= 1 e n_inputs >= 1; "
                    f"recebido n_states={plant_or_A.n_states}, n_inputs={plant_or_A.n_inputs}."
                ),
                parameters={"n_states": plant_or_A.n_states, "n_inputs": plant_or_A.n_inputs},
                next_step="Forneça um modelo StateSpace com pelo menos 1 estado e 1 entrada.",
            )
        return plant_or_A.A.copy(), plant_or_A.B.copy(), plant_or_A

    if isinstance(plant_or_A, TSStateSpace) or (hasattr(plant_or_A, "kind") and not isinstance(plant_or_A, (np.ndarray, list, tuple))):
        raise UnsupportedModelError(
            message=f"Template LTI requer StateSpace ou matrizes (A, B), recebido {type(plant_or_A).__name__}.",
            parameters={"model_type": type(plant_or_A).__name__},
        )

    if B is None:
        raise ValidationError("Forneça (A, B) ou uma instância de StateSpace.")
    A_arr = ensure_finite_float64(plant_or_A, ndim=2, name="A")
    if A_arr.shape[0] != A_arr.shape[1] or A_arr.shape[0] < 1:
        raise DimensionMismatchError(f"Matriz A deve ser quadrada n x n (n >= 1), recebido {A_arr.shape}.")
    B_arr = ensure_finite_float64(B, ndim=2, name="B")
    if B_arr.shape[0] != A_arr.shape[0] or B_arr.shape[1] < 1:
        raise DimensionMismatchError(
            f"Matriz B {B_arr.shape} incompatível com A {A_arr.shape} (esperado ({A_arr.shape[0]}, m >= 1))."
        )
    return A_arr, B_arr, None


def _validate_positive_scalar(val: Any, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float, np.integer, np.floating)):
        raise ValidationError(f"Parâmetro {name} deve ser número real, recebido {val!r}.")
    fval = float(val)
    if not math.isfinite(fval):
        raise ValidationError(f"Parâmetro {name} deve ser finito, recebido {fval!r}.")
    if allow_zero:
        if fval < 0.0:
            raise ValidationError(f"Parâmetro {name} deve ser >= 0, recebido {fval}.")
    else:
        if fval <= 0.0:
            raise ValidationError(f"Parâmetro {name} deve ser > 0, recebido {fval}.")
    return fval


def _validate_q_bounds(q_bounds: tuple[float, float] | None) -> tuple[float, float] | None:
    if q_bounds is None:
        return None
    if not isinstance(q_bounds, (tuple, list)) or len(q_bounds) != 2:
        raise ValidationError("q_bounds deve ser tupla (q_min, q_max).")
    q_min = _validate_positive_scalar(q_bounds[0], "q_bounds[0]")
    q_max = _validate_positive_scalar(q_bounds[1], "q_bounds[1]")
    if q_min >= q_max:
        raise ValidationError(f"q_bounds deve satisfazer 0 < q_min < q_max, recebido ({q_min}, {q_max}).")
    return (q_min, q_max)


def continuous_stabilization_lmi(
    plant_or_A: Any,
    B: Any = None,
    *,
    alpha: float = 0.0,
    feedback_sign: str = "positive",
    eps_lmi: float = 1e-4,
    eps_q: float = 1e-4,
    q_bounds: tuple[float, float] | None = None,
    minimize_trace_q: bool = False,
    name: str = "continuous_stabilization_lmi",
) -> CanonicalSDPProblem:
    """Constrói CanonicalSDPProblem para estabilização contínua com taxa de decaimento alpha >= 0.

    LMI (com sinal s = +1 para u = +K x ou s = -1 para u = -K x, K = Y Q^{-1}):
        Q >= eps_q * I
        (A Q + s B Y) + (A Q + s B Y)^T + 2 alpha Q <= -eps_lmi * I
    """
    A_arr, B_arr, ss_plant = _extract_lti_matrices(plant_or_A, B)
    sign_str = _validate_feedback_sign(feedback_sign)
    alpha_val = _validate_positive_scalar(alpha, "alpha", allow_zero=True)
    eps_l = _validate_positive_scalar(eps_lmi, "eps_lmi")
    eps_q_val = _validate_positive_scalar(eps_q, "eps_q")
    qb = _validate_q_bounds(q_bounds)

    n = A_arr.shape[0]
    m = B_arr.shape[1]
    s = 1.0 if sign_str == "positive" else -1.0

    Q = sdpvar((n, n), name="Q", symmetric=True)
    Y = sdpvar((m, n), name="Y", symmetric=False)
    I_n = np.eye(n, dtype=np.float64)

    q_min = qb[0] if qb is not None else eps_q_val
    cons: list[Any] = [Q >= q_min * I_n]
    if qb is not None:
        cons.append(Q <= qb[1] * I_n)

    M = A_arr @ Q + s * (B_arr @ Y)
    stab_expr = M + M.T + 2.0 * alpha_val * Q
    cons.append(stab_expr <= -eps_l * I_n)

    obj = trace(Q) if minimize_trace_q else None

    recovery_plan: dict[str, Any] = {
        "template_kind": "continuous_stabilization",
        "controller_kind": "StateFeedbackController",
        "feedback_sign": sign_str,
        "Q_var": "Q",
        "Y_var": "Y",
        "alpha": alpha_val,
        "eps_lmi": eps_l,
        "eps_q": q_min,
        "dt": None,
        "A": array_to_tensor(A_arr, dtype="float64", order="C"),
        "B": array_to_tensor(B_arr, dtype="float64", order="C"),
    }
    if ss_plant is not None:
        recovery_plan["plant_id"] = ss_plant.id
        recovery_plan["plant_revision"] = ss_plant.revision
        recovery_plan["state_names"] = list(ss_plant.state_names)
        recovery_plan["input_names"] = list(ss_plant.input_names)

    return compile(
        objective=obj,
        constraints=cons,
        sense="minimize",
        name=name,
        recovery_plan=recovery_plan,
        metadata={"template": "continuous_stabilization_lmi", "n": n, "m": m, "alpha": alpha_val},
    )


def regional_pole_placement_lmi(
    plant_or_A: Any,
    B: Any = None,
    *,
    radius: float,
    alpha: float | None = None,
    feedback_sign: str = "positive",
    eps_lmi: float = 1e-4,
    eps_q: float = 1e-4,
    q_bounds: tuple[float, float] | None = None,
    name: str = "regional_pole_placement_lmi",
) -> CanonicalSDPProblem:
    """Constrói CanonicalSDPProblem para D-estabilidade em disco |lambda| < r e semiplano Re(lambda) < -alpha.

    Condição de disco de raio r > 0 centrado na origem com M = A Q + s B Y:
        [[ -r Q, M ], [ M^T, -r Q ]] <= -eps_lmi * I_{2n}
    Se alpha is not None (alpha >= 0):
        M + M^T + 2 alpha Q <= -eps_lmi * I_n
    """
    A_arr, B_arr, ss_plant = _extract_lti_matrices(plant_or_A, B)
    sign_str = _validate_feedback_sign(feedback_sign)
    r_val = _validate_positive_scalar(radius, "radius")
    alpha_val = _validate_positive_scalar(alpha, "alpha", allow_zero=True) if alpha is not None else None
    eps_l = _validate_positive_scalar(eps_lmi, "eps_lmi")
    eps_q_val = _validate_positive_scalar(eps_q, "eps_q")
    qb = _validate_q_bounds(q_bounds)

    n = A_arr.shape[0]
    m = B_arr.shape[1]
    s = 1.0 if sign_str == "positive" else -1.0

    Q = sdpvar((n, n), name="Q", symmetric=True)
    Y = sdpvar((m, n), name="Y", symmetric=False)
    I_n = np.eye(n, dtype=np.float64)
    I_2n = np.eye(2 * n, dtype=np.float64)

    q_min = qb[0] if qb is not None else eps_q_val
    cons: list[Any] = [Q >= q_min * I_n]
    if qb is not None:
        cons.append(Q <= qb[1] * I_n)

    M = A_arr @ Q + s * (B_arr @ Y)
    disk_lmi = bmat([[-r_val * Q, M], [M.T, -r_val * Q]])
    cons.append(disk_lmi <= -eps_l * I_2n)

    if alpha_val is not None:
        cons.append(M + M.T + 2.0 * alpha_val * Q <= -eps_l * I_n)

    recovery_plan: dict[str, Any] = {
        "template_kind": "regional_pole_placement",
        "controller_kind": "StateFeedbackController",
        "feedback_sign": sign_str,
        "Q_var": "Q",
        "Y_var": "Y",
        "radius": r_val,
        "alpha": alpha_val,
        "eps_lmi": eps_l,
        "eps_q": q_min,
        "dt": None,
        "A": array_to_tensor(A_arr, dtype="float64", order="C"),
        "B": array_to_tensor(B_arr, dtype="float64", order="C"),
    }
    if ss_plant is not None:
        recovery_plan["plant_id"] = ss_plant.id
        recovery_plan["plant_revision"] = ss_plant.revision
        recovery_plan["state_names"] = list(ss_plant.state_names)
        recovery_plan["input_names"] = list(ss_plant.input_names)

    return compile(
        objective=None,
        constraints=cons,
        sense="minimize",
        name=name,
        recovery_plan=recovery_plan,
        metadata={"template": "regional_pole_placement_lmi", "n": n, "m": m, "radius": r_val, "alpha": alpha_val},
    )


def hinf_brl_lmi(
    A: Any,
    B1: Any,
    B2: Any,
    C1: Any,
    D11: Any = None,
    D12: Any = None,
    *,
    gamma: float | None = None,
    feedback_sign: str = "positive",
    eps_lmi: float = 1e-4,
    eps_q: float = 1e-4,
    eps_gamma: float = 1e-4,
    q_bounds: tuple[float, float] | None = None,
    name: str = "hinf_brl_lmi",
) -> CanonicalSDPProblem:
    """Bounded Real Lemma (BRL) H-infinito por realimentação de estados para planta generalizada.

    Planta generalizada:
        dx/dt = A x + B1 w + B2 u
        z     = C1 x + D11 w + D12 u
    Com u = s K x (s=+1 para 'positive', s=-1 para 'negative'), K = Y Q^{-1}:
        Z = A Q + s B2 Y,   W = C1 Q + s D12 Y
        [[ Z + Z^T, B1, W^T ],
         [ B1^T, -gamma I_nw, D11^T ],
         [ W, D11, -gamma I_nz ]] <= -eps_lmi * I
    Se gamma=None, minimiza gamma; se gamma > 0 é fornecido, verifica factibilidade.
    """
    A_arr = ensure_finite_float64(A, ndim=2, name="A")
    if A_arr.shape[0] != A_arr.shape[1] or A_arr.shape[0] < 1:
        raise DimensionMismatchError(f"A deve ser quadrada n x n (n >= 1), recebido {A_arr.shape}.")
    n = A_arr.shape[0]

    B1_arr = ensure_finite_float64(B1, ndim=2, name="B1")
    if B1_arr.shape[0] != n or B1_arr.shape[1] < 1:
        raise DimensionMismatchError(f"B1 {B1_arr.shape} incompatível com n={n} (esperado ({n}, nw >= 1)).")
    nw = B1_arr.shape[1]

    B2_arr = ensure_finite_float64(B2, ndim=2, name="B2")
    if B2_arr.shape[0] != n or B2_arr.shape[1] < 1:
        raise DimensionMismatchError(f"B2 {B2_arr.shape} incompatível com n={n} (esperado ({n}, m >= 1)).")
    m = B2_arr.shape[1]

    C1_arr = ensure_finite_float64(C1, ndim=2, name="C1")
    if C1_arr.shape[1] != n or C1_arr.shape[0] < 1:
        raise DimensionMismatchError(f"C1 {C1_arr.shape} incompatível com n={n} (esperado (nz >= 1, {n})).")
    nz = C1_arr.shape[0]

    D11_arr = np.zeros((nz, nw), dtype=np.float64) if D11 is None else ensure_finite_float64(D11, ndim=2, shape=(nz, nw), name="D11")
    D12_arr = np.zeros((nz, m), dtype=np.float64) if D12 is None else ensure_finite_float64(D12, ndim=2, shape=(nz, m), name="D12")

    sign_str = _validate_feedback_sign(feedback_sign)
    eps_l = _validate_positive_scalar(eps_lmi, "eps_lmi")
    eps_q_val = _validate_positive_scalar(eps_q, "eps_q")
    eps_g = _validate_positive_scalar(eps_gamma, "eps_gamma")
    qb = _validate_q_bounds(q_bounds)

    gamma_fixed: float | None = None
    if gamma is not None:
        gamma_fixed = _validate_positive_scalar(gamma, "gamma")

    s = 1.0 if sign_str == "positive" else -1.0
    Q = sdpvar((n, n), name="Q", symmetric=True)
    Y = sdpvar((m, n), name="Y", symmetric=False)

    I_n = np.eye(n, dtype=np.float64)
    I_nw = np.eye(nw, dtype=np.float64)
    I_nz = np.eye(nz, dtype=np.float64)
    I_brl = np.eye(n + nw + nz, dtype=np.float64)

    q_min = qb[0] if qb is not None else eps_q_val
    cons: list[Any] = [Q >= q_min * I_n]
    if qb is not None:
        cons.append(Q <= qb[1] * I_n)

    if gamma_fixed is None:
        gamma_var = sdpvar((1, 1), name="gamma")
        cons.append(gamma_var >= eps_g)
        gamma_nw = -gamma_var * I_nw
        gamma_nz = -gamma_var * I_nz
        objective = gamma_var
    else:
        gamma_nw = -gamma_fixed * I_nw
        gamma_nz = -gamma_fixed * I_nz
        objective = None

    Z_blk = A_arr @ Q + s * (B2_arr @ Y)
    W_blk = C1_arr @ Q + s * (D12_arr @ Y)
    brl_expr = bmat(
        [
            [Z_blk + Z_blk.T, B1_arr, W_blk.T],
            [B1_arr.T, gamma_nw, D11_arr.T],
            [W_blk, D11_arr, gamma_nz],
        ]
    )
    cons.append(brl_expr <= -eps_l * I_brl)

    recovery_plan: dict[str, Any] = {
        "template_kind": "hinf_brl",
        "controller_kind": "StateFeedbackController",
        "feedback_sign": sign_str,
        "Q_var": "Q",
        "Y_var": "Y",
        "gamma_var": "gamma" if gamma_fixed is None else None,
        "gamma_fixed": gamma_fixed,
        "eps_lmi": eps_l,
        "eps_q": q_min,
        "dt": None,
        "A": array_to_tensor(A_arr, dtype="float64", order="C"),
        "B1": array_to_tensor(B1_arr, dtype="float64", order="C"),
        "B2": array_to_tensor(B2_arr, dtype="float64", order="C"),
        "C1": array_to_tensor(C1_arr, dtype="float64", order="C"),
        "D11": array_to_tensor(D11_arr, dtype="float64", order="C"),
        "D12": array_to_tensor(D12_arr, dtype="float64", order="C"),
    }

    return compile(
        objective=objective,
        constraints=cons,
        sense="minimize",
        name=name,
        recovery_plan=recovery_plan,
        metadata={
            "template": "hinf_brl_lmi",
            "n": n,
            "nw": nw,
            "m": m,
            "nz": nz,
            "mode": "minimize_gamma" if gamma_fixed is None else "fixed_gamma",
        },
    )


def ts_pdc_stabilization_lmi(
    ts_model: TSStateSpace,
    *,
    alpha: float = 0.0,
    feedback_sign: str = "positive",
    eps_lmi: float = 1e-4,
    eps_q: float = 1e-4,
    q_bounds: tuple[float, float] | None = None,
    premise_estimator: Any = None,
    name: str = "ts_pdc_stabilization_lmi",
) -> CanonicalSDPProblem:
    """Constrói CanonicalSDPProblem para síntese quadrática PDC de TSStateSpace contínuo.

    Regras normativas (ADR-006 / Seção 4.3 / Seção 6.4):
    - Rejeita obrigatoriamente `TSStateSpace(kind='polytopic_uncertain')` com HypothesisViolatedError.
    - Para `ts_partially_observed`, exige `premise_estimator` explícito.
    - Expande as condições suficientes de Tanaka-Wang nas somas duplas:
          G_ii <= -eps_lmi * I                              (i = 0..r-1)
          G_ij + G_ji <= -2 * eps_lmi * I                    (0 <= i < j < r)
      sem exigir estabilidade individual de (A_i + s B_i K_j) para i != j.
    """
    if not isinstance(ts_model, TSStateSpace):
        raise UnsupportedModelError(
            message=f"ts_pdc_stabilization_lmi requer TSStateSpace, recebido {type(ts_model).__name__}.",
            parameters={"model_type": type(ts_model).__name__},
        )
    if ts_model.dt is not None:
        raise UnsupportedModelError(
            message=f"Síntese PDC contínua requer dt=None, recebido dt={ts_model.dt}.",
            parameters={"dt": ts_model.dt},
        )
    if ts_model.kind == "polytopic_uncertain":
        raise HypothesisViolatedError(
            message=(
                "Síntese PDC proibida para TSStateSpace(kind='polytopic_uncertain'): "
                "pesos politópicos desconhecidos não podem ser agendados por lei PDC (T-TS-01 / ADR-006)."
            ),
            parameters={"ts_model_id": ts_model.id, "ts_kind": ts_model.kind},
            next_step="Utilize síntese de ganho robusto único ou modele as premissas mensuráveis em 'ts_measured'.",
        )
    if ts_model.kind == "ts_partially_observed" and premise_estimator is None:
        raise HypothesisViolatedError(
            message=(
                "TSStateSpace(kind='ts_partially_observed') exige premise_estimator explícito para síntese PDC."
            ),
            parameters={"ts_model_id": ts_model.id, "ts_kind": ts_model.kind},
            next_step="Forneça premise_estimator ou utilize modelo 'ts_measured'.",
        )
    if ts_model.kind not in ("ts_measured", "ts_partially_observed"):
        raise HypothesisViolatedError(f"Tipo TS não permitido para síntese PDC: {ts_model.kind!r}.")

    sign_str = _validate_feedback_sign(feedback_sign)
    alpha_val = _validate_positive_scalar(alpha, "alpha", allow_zero=True)
    eps_l = _validate_positive_scalar(eps_lmi, "eps_lmi")
    eps_q_val = _validate_positive_scalar(eps_q, "eps_q")
    qb = _validate_q_bounds(q_bounds)

    r = ts_model.n_vertices
    n = ts_model.n_states
    m = ts_model.n_inputs
    s = 1.0 if sign_str == "positive" else -1.0

    Q = sdpvar((n, n), name="Q", symmetric=True)
    Y_vars = [sdpvar((m, n), name=f"Y_{i}", symmetric=False) for i in range(r)]
    I_n = np.eye(n, dtype=np.float64)

    q_min = qb[0] if qb is not None else eps_q_val
    cons: list[Any] = [Q >= q_min * I_n]
    if qb is not None:
        cons.append(Q <= qb[1] * I_n)

    verts = ts_model.vertices

    def _g_ij(i: int, j: int) -> Any:
        Ai = verts[i]["A"]
        Bi = verts[i]["B"]
        M_ij = Ai @ Q + s * (Bi @ Y_vars[j])
        return M_ij + M_ij.T + 2.0 * alpha_val * Q

    for i in range(r):
        cons.append(_g_ij(i, i) <= -eps_l * I_n)
    for i in range(r):
        for j in range(i + 1, r):
            cons.append(_g_ij(i, j) + _g_ij(j, i) <= -2.0 * eps_l * I_n)

    recovery_plan: dict[str, Any] = {
        "template_kind": "ts_pdc_stabilization",
        "controller_kind": "PDCController",
        "feedback_sign": sign_str,
        "Q_var": "Q",
        "Y_vars": [f"Y_{i}" for i in range(r)],
        "alpha": alpha_val,
        "eps_lmi": eps_l,
        "eps_q": q_min,
        "dt": None,
        "ts_model_id": ts_model.id,
        "ts_model_revision": ts_model.revision,
        "ts_kind": ts_model.kind,
        "membership_version": ts_model.membership_spec["version"],
        "premise_variables": list(ts_model.membership_spec["premise_variables"]),
        "state_names": list(ts_model.state_names),
        "vertices": [
            {
                "vertex_id": v["vertex_id"],
                "A": array_to_tensor(v["A"], dtype="float64", order="C"),
                "B": array_to_tensor(v["B"], dtype="float64", order="C"),
            }
            for v in verts
        ],
    }

    return compile(
        objective=None,
        constraints=cons,
        sense="minimize",
        name=name,
        recovery_plan=recovery_plan,
        metadata={"template": "ts_pdc_stabilization_lmi", "n": n, "m": m, "n_vertices": r, "alpha": alpha_val},
    )
