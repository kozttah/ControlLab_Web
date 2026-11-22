"""Observadores Takagi-Sugeno com premissas não mensuradas aplicados diretamente às não linearidades do sistema (F5).

Suporta dois paradigmas complementares para sistemas não lineares:
1. `dmvt_nonlinearity`: Aplicação do Teorema do Valor Médio Diferencial (DMVT)
   diretamente sobre as não linearidades f(x) - f(x_hat) e h(x) - h(x_hat) via
   limitantes jacobianos [J_min, J_max], gerando vértices de perturbação setorial
   dA_k e dC_k sem depender de linearização nas funções de pertinência.
2. `gradient_factorization`: Fatoração algébrica exata de gradiente
   f(x) - f(x_hat) = A(x, x_hat) e_x e h(x) - h(x_hat) = C(x, x_hat) e_x
   (cf. 10.1016/j.fss.2020.04.012, hal-03425007, hal-04307213,
   10.1007/s40313-025-01189-y), desacoplando sinais mensurados e não mensurados
   sem exigir saída linear ou estrutura afim no controle.
"""

from __future__ import annotations

import inspect
import itertools
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np

from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import ControlLabError, NumericalInconclusiveError, ValidationError

_DMVT_REFERENCES: tuple[str, ...] = (
    "Zemouche & Boutayeb (2013) DMVT observer design",
    "10.1016/j.fss.2020.04.012",
)

_GRADIENT_FACTORIZATION_REFERENCES: tuple[str, ...] = (
    "10.1016/j.fss.2020.04.012",
    "hal-03425007",
    "hal-04307213",
    "10.1007/s40313-025-01189-y",
)


@dataclass(frozen=True)
class TSUnmeasuredObserverSpec:
    """Especificação imutável de observador Takagi-Sugeno com premissas não mensuradas."""

    method: str
    A_vertices: tuple[np.ndarray, ...]
    C_vertices: tuple[np.ndarray, ...]
    delta_A_vertices: tuple[np.ndarray, ...]
    delta_C_vertices: tuple[np.ndarray, ...]
    n_states: int
    n_outputs: int
    measured_indices: tuple[int, ...]
    unmeasured_indices: tuple[int, ...]
    references: tuple[str, ...]


def _coerce_finite_matrix(
    value: Any,
    *,
    name: str,
    expected_shape: tuple[int, int] | None = None,
) -> np.ndarray:
    try:
        arr = ensure_finite_float64(value, ndim=2, name=name)
    except ControlLabError as exc:
        raise ValidationError(
            message=exc.message,
            parameters=exc.parameters,
            next_step=exc.next_step,
        ) from exc
    if expected_shape is not None and arr.shape != expected_shape:
        raise ValidationError(
            message=f"{name} deve ter shape {expected_shape}, recebido {arr.shape}.",
            parameters={"name": name, "expected_shape": list(expected_shape), "actual_shape": list(arr.shape)},
        )
    out = np.array(arr, dtype=np.float64, copy=True)
    out.setflags(write=False)
    return out


def _coerce_finite_vector(
    value: Any,
    *,
    name: str,
    expected_len: int,
) -> np.ndarray:
    try:
        arr = ensure_finite_float64(value, ndim=1, name=name)
    except ControlLabError as exc:
        raise ValidationError(
            message=exc.message,
            parameters=exc.parameters,
            next_step=exc.next_step,
        ) from exc
    if arr.size != expected_len:
        raise ValidationError(
            message=f"{name} deve ter comprimento {expected_len}, recebido {arr.size}.",
            parameters={"name": name, "expected_len": expected_len, "actual_len": int(arr.size)},
        )
    return np.array(arr, dtype=np.float64, copy=True)


def _validate_A_and_C_vertices(
    A_vertices: Sequence[Any],
    C_vertices: Sequence[Any],
) -> tuple[tuple[np.ndarray, ...], tuple[np.ndarray, ...], int, int]:
    if not isinstance(A_vertices, Sequence) or isinstance(A_vertices, (str, bytes)) or len(A_vertices) == 0:
        raise ValidationError("A_vertices deve ser uma sequência não vazia de matrizes quadradas n x n.")
    if not isinstance(C_vertices, Sequence) or isinstance(C_vertices, (str, bytes)) or len(C_vertices) == 0:
        raise ValidationError("C_vertices deve ser uma sequência não vazia de matrizes p x n.")

    a_first = _coerce_finite_matrix(A_vertices[0], name="A_vertices[0]")
    n_states, n_cols = a_first.shape
    if n_states == 0 or n_states != n_cols:
        raise ValidationError(
            message=f"A_vertices[0] deve ser quadrada e não vazia (n x n), recebido {a_first.shape}.",
            parameters={"shape": list(a_first.shape)},
        )

    a_list: list[np.ndarray] = [a_first]
    for idx in range(1, len(A_vertices)):
        a_list.append(
            _coerce_finite_matrix(
                A_vertices[idx],
                name=f"A_vertices[{idx}]",
                expected_shape=(n_states, n_states),
            )
        )

    c_first = _coerce_finite_matrix(C_vertices[0], name="C_vertices[0]")
    n_outputs, c_cols = c_first.shape
    if n_outputs == 0 or c_cols != n_states:
        raise ValidationError(
            message=f"C_vertices[0] deve ter shape (p, {n_states}) com p >= 1, recebido {c_first.shape}.",
            parameters={"expected_cols": n_states, "actual_shape": list(c_first.shape)},
        )

    c_list: list[np.ndarray] = [c_first]
    for idx in range(1, len(C_vertices)):
        c_list.append(
            _coerce_finite_matrix(
                C_vertices[idx],
                name=f"C_vertices[{idx}]",
                expected_shape=(n_outputs, n_states),
            )
        )

    if len(c_list) not in (1, len(a_list)):
        raise ValidationError(
            message=(
                f"C_vertices deve ter comprimento 1 (saída compartilhada) ou igual a A_vertices ({len(a_list)}), "
                f"recebido {len(c_list)}."
            ),
            parameters={"n_A": len(a_list), "n_C": len(c_list)},
        )

    return tuple(a_list), tuple(c_list), n_states, n_outputs


def _resolve_measured_indices(
    C_vertices: tuple[np.ndarray, ...],
    n_states: int,
    measured_indices: Sequence[int] | None,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if measured_indices is None:
        inferred = tuple(
            j for j in range(n_states) if any(bool(np.any(C[:, j] != 0.0)) for C in C_vertices)
        )
        unmeasured = tuple(j for j in range(n_states) if j not in inferred)
        return inferred, unmeasured

    if isinstance(measured_indices, (str, bytes)):
        raise ValidationError("measured_indices deve ser uma sequência de inteiros.")

    seen: set[int] = set()
    cleaned: list[int] = []
    for raw_idx in measured_indices:
        if isinstance(raw_idx, bool) or not isinstance(raw_idx, (int, np.integer)):
            raise ValidationError(f"Índice medido inválido: {raw_idx!r}.")
        idx = int(raw_idx)
        if idx < 0 or idx >= n_states:
            raise ValidationError(
                message=f"Índice medido {idx} fora do intervalo [0, {n_states - 1}].",
                parameters={"index": idx, "n_states": n_states},
            )
        if idx in seen:
            raise ValidationError(
                message=f"Índice medido duplicado: {idx}.",
                parameters={"index": idx},
            )
        seen.add(idx)
        cleaned.append(idx)

    measured_tuple = tuple(cleaned)
    unmeasured_tuple = tuple(j for j in range(n_states) if j not in seen)
    return measured_tuple, unmeasured_tuple


def _generate_sector_vertices(
    j_min: np.ndarray,
    j_max: np.ndarray,
    *,
    name_prefix: str,
    max_sector_vertices: int,
) -> tuple[np.ndarray, ...]:
    if np.any(j_min > j_max):
        bad_idx = np.argwhere(j_min > j_max)[0]
        i, j = int(bad_idx[0]), int(bad_idx[1])
        raise ValidationError(
            message=(
                f"{name_prefix}_min[{i}, {j}] = {j_min[i, j]} excede "
                f"{name_prefix}_max[{i}, {j}] = {j_max[i, j]}."
            ),
            parameters={"row": i, "col": j, "j_min": float(j_min[i, j]), "j_max": float(j_max[i, j])},
        )

    varying_mask = j_min != j_max
    varying_coords = np.argwhere(varying_mask)
    n_varying = int(varying_coords.shape[0])

    if n_varying == 0:
        mat = np.array(j_min, dtype=np.float64, copy=True)
        mat.setflags(write=False)
        return (mat,)

    n_vertices = 1 << n_varying
    if n_vertices > max_sector_vertices:
        raise ValidationError(
            message=(
                f"Número de vértices setoriais DMVT ({n_vertices}) excede o limite max_sector_vertices={max_sector_vertices}."
            ),
            parameters={"n_varying": n_varying, "n_vertices": n_vertices, "max_sector_vertices": max_sector_vertices},
        )

    base = np.array(j_min, dtype=np.float64, copy=True)
    vertices: list[np.ndarray] = []
    coord_pairs = [(int(r), int(c)) for r, c in varying_coords]
    for bits in itertools.product((0, 1), repeat=n_varying):
        mat = base.copy()
        for bit, (r, c) in zip(bits, coord_pairs):
            if bit == 1:
                mat[r, c] = j_max[r, c]
        mat.setflags(write=False)
        vertices.append(mat)
    return tuple(vertices)


def build_dmvt_nonlinearity_spec(
    A_vertices: Sequence[Any],
    C_vertices: Sequence[Any],
    *,
    jacobian_min: Any,
    jacobian_max: Any,
    output_jacobian_min: Any = None,
    output_jacobian_max: Any = None,
    measured_indices: Sequence[int] | None = None,
    max_sector_vertices: int = 1024,
) -> TSUnmeasuredObserverSpec:
    """Constrói especificação DMVT aplicada diretamente às não linearidades do sistema."""
    a_verts, c_verts, n_states, n_outputs = _validate_A_and_C_vertices(A_vertices, C_vertices)

    j_min = _coerce_finite_matrix(jacobian_min, name="jacobian_min", expected_shape=(n_states, n_states))
    j_max = _coerce_finite_matrix(jacobian_max, name="jacobian_max", expected_shape=(n_states, n_states))
    delta_a_verts = _generate_sector_vertices(
        j_min,
        j_max,
        name_prefix="jacobian",
        max_sector_vertices=max_sector_vertices,
    )

    if (output_jacobian_min is None) != (output_jacobian_max is None):
        raise ValidationError(
            "output_jacobian_min e output_jacobian_max devem ser fornecidos em conjunto ou ambos omitidos."
        )
    if output_jacobian_min is not None and output_jacobian_max is not None:
        cj_min = _coerce_finite_matrix(
            output_jacobian_min,
            name="output_jacobian_min",
            expected_shape=(n_outputs, n_states),
        )
        cj_max = _coerce_finite_matrix(
            output_jacobian_max,
            name="output_jacobian_max",
            expected_shape=(n_outputs, n_states),
        )
        delta_c_verts = _generate_sector_vertices(
            cj_min,
            cj_max,
            name_prefix="output_jacobian",
            max_sector_vertices=max_sector_vertices,
        )
    else:
        zero_dc = np.zeros((n_outputs, n_states), dtype=np.float64)
        zero_dc.setflags(write=False)
        delta_c_verts = (zero_dc,)

    measured, unmeasured = _resolve_measured_indices(c_verts, n_states, measured_indices)
    return TSUnmeasuredObserverSpec(
        method="dmvt_nonlinearity",
        A_vertices=a_verts,
        C_vertices=c_verts,
        delta_A_vertices=delta_a_verts,
        delta_C_vertices=delta_c_verts,
        n_states=n_states,
        n_outputs=n_outputs,
        measured_indices=measured,
        unmeasured_indices=unmeasured,
        references=_DMVT_REFERENCES,
    )


def build_gradient_factorization_spec(
    A_vertices: Sequence[Any],
    C_vertices: Sequence[Any],
    *,
    delta_A_vertices: Sequence[Any],
    delta_C_vertices: Sequence[Any] | None = None,
    measured_indices: Sequence[int] | None = None,
) -> TSUnmeasuredObserverSpec:
    """Constrói especificação via fatoração algébrica exata de gradiente f(x)-f(x_hat) = A(x,x_hat)e_x."""
    a_verts, c_verts, n_states, n_outputs = _validate_A_and_C_vertices(A_vertices, C_vertices)

    if (
        not isinstance(delta_A_vertices, Sequence)
        or isinstance(delta_A_vertices, (str, bytes))
        or len(delta_A_vertices) == 0
    ):
        raise ValidationError("delta_A_vertices deve ser uma sequência não vazia de matrizes n x n.")

    da_list = tuple(
        _coerce_finite_matrix(mat, name=f"delta_A_vertices[{idx}]", expected_shape=(n_states, n_states))
        for idx, mat in enumerate(delta_A_vertices)
    )

    if delta_C_vertices is None:
        zero_dc = np.zeros((n_outputs, n_states), dtype=np.float64)
        zero_dc.setflags(write=False)
        dc_list: tuple[np.ndarray, ...] = (zero_dc,)
    else:
        if (
            not isinstance(delta_C_vertices, Sequence)
            or isinstance(delta_C_vertices, (str, bytes))
            or len(delta_C_vertices) == 0
        ):
            raise ValidationError("delta_C_vertices deve ser uma sequência não vazia de matrizes p x n ou None.")
        dc_list = tuple(
            _coerce_finite_matrix(mat, name=f"delta_C_vertices[{idx}]", expected_shape=(n_outputs, n_states))
            for idx, mat in enumerate(delta_C_vertices)
        )

    measured, unmeasured = _resolve_measured_indices(c_verts, n_states, measured_indices)
    return TSUnmeasuredObserverSpec(
        method="gradient_factorization",
        A_vertices=a_verts,
        C_vertices=c_verts,
        delta_A_vertices=da_list,
        delta_C_vertices=dc_list,
        n_states=n_states,
        n_outputs=n_outputs,
        measured_indices=measured,
        unmeasured_indices=unmeasured,
        references=_GRADIENT_FACTORIZATION_REFERENCES,
    )


def _count_positional_args(fn: Callable[..., Any]) -> int:
    sig = inspect.signature(fn)
    count = 0
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            return 2
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            count += 1
    return count


def _normalize_weights(raw_weights: Any, n_vertices: int) -> np.ndarray:
    arr = _coerce_finite_vector(raw_weights, name="premise_weights", expected_len=n_vertices)
    if np.any(arr < -1e-12):
        raise ValidationError(
            message=f"Pesos de premissa devem ser não negativos, recebido min={float(np.min(arr)):.3e}.",
            parameters={"min_weight": float(np.min(arr))},
        )
    arr = np.maximum(arr, 0.0)
    total = float(np.sum(arr))
    if total <= 0.0:
        raise ValidationError("Soma dos pesos de premissa deve ser estritamente positiva.")
    return arr / total


def simulate_ts_unmeasured_observer(
    spec: TSUnmeasuredObserverSpec,
    observer_gains_L: Sequence[Any],
    *,
    x0: Sequence[float] | np.ndarray,
    x_hat0: Sequence[float] | np.ndarray,
    t_span: tuple[float, float],
    dt: float,
    u_fn: Callable[..., Any] | None = None,
    nonlinearity_fn: Callable[..., Any] | None = None,
    premise_fn: Callable[..., Any] | None = None,
    output_nonlinearity_fn: Callable[..., Any] | None = None,
    B_vertices: Sequence[Any] | None = None,
    convergence_tol: float = 1e-3,
) -> dict[str, Any]:
    """Simula planta não linear + observador TS com premissa não mensurada via RK4."""
    if not isinstance(spec, TSUnmeasuredObserverSpec):
        raise ValidationError("spec deve ser uma instância de TSUnmeasuredObserverSpec.")

    n = spec.n_states
    p = spec.n_outputs
    r = len(spec.A_vertices)

    if (
        not isinstance(observer_gains_L, Sequence)
        or isinstance(observer_gains_L, (str, bytes))
        or len(observer_gains_L) not in (1, r)
    ):
        raise ValidationError(
            message=f"observer_gains_L deve conter 1 ou {r} matrizes de ganho ({n} x {p}).",
            parameters={"expected_count": r, "actual_count": len(observer_gains_L) if isinstance(observer_gains_L, Sequence) else None},
        )

    L_list = tuple(
        _coerce_finite_matrix(mat, name=f"observer_gains_L[{idx}]", expected_shape=(n, p))
        for idx, mat in enumerate(observer_gains_L)
    )
    if len(L_list) == 1 and r > 1:
        L_list = tuple(L_list[0] for _ in range(r))

    c_list = spec.C_vertices
    if len(c_list) == 1 and r > 1:
        c_list = tuple(c_list[0] for _ in range(r))

    b_list: tuple[np.ndarray, ...] | None = None
    if B_vertices is not None:
        if (
            not isinstance(B_vertices, Sequence)
            or isinstance(B_vertices, (str, bytes))
            or len(B_vertices) not in (1, r)
        ):
            raise ValidationError(f"B_vertices deve conter 1 ou {r} matrizes.")
        b_first = _coerce_finite_matrix(B_vertices[0], name="B_vertices[0]")
        if b_first.shape[0] != n:
            raise ValidationError(f"B_vertices[0] deve ter {n} linhas, recebido {b_first.shape[0]}.")
        m_inputs = b_first.shape[1]
        b_parsed = [b_first] + [
            _coerce_finite_matrix(B_vertices[idx], name=f"B_vertices[{idx}]", expected_shape=(n, m_inputs))
            for idx in range(1, len(B_vertices))
        ]
        b_list = tuple(b_parsed[0] for _ in range(r)) if len(b_parsed) == 1 and r > 1 else tuple(b_parsed)

    x_init = _coerce_finite_vector(x0, name="x0", expected_len=n)
    x_hat_init = _coerce_finite_vector(x_hat0, name="x_hat0", expected_len=n)

    if not isinstance(t_span, (tuple, list)) or len(t_span) != 2:
        raise ValidationError("t_span deve ser uma tupla (t0, tf).")
    t0 = float(t_span[0])
    tf = float(t_span[1])
    dt_val = float(dt)
    if not (np.isfinite(t0) and np.isfinite(tf) and np.isfinite(dt_val)):
        raise ValidationError("t_span e dt devem ser finitos.")
    if tf <= t0:
        raise ValidationError(f"t_span inválido: tf ({tf}) deve ser maior que t0 ({t0}).")
    if dt_val <= 0.0:
        raise ValidationError(f"dt deve ser estritamente positivo, recebido {dt_val}.")

    u_arity = _count_positional_args(u_fn) if u_fn is not None else 0
    nl_arity = _count_positional_args(nonlinearity_fn) if nonlinearity_fn is not None else 0
    out_nl_arity = _count_positional_args(output_nonlinearity_fn) if output_nonlinearity_fn is not None else 0
    prem_arity = _count_positional_args(premise_fn) if premise_fn is not None else 0

    def _eval_u(t_cur: float, x_cur: np.ndarray) -> np.ndarray | None:
        if u_fn is None:
            return None
        raw_u = u_fn(t_cur) if u_arity <= 1 else u_fn(t_cur, x_cur)
        u_arr = np.atleast_1d(np.asarray(raw_u, dtype=np.float64)).ravel()
        if not np.all(np.isfinite(u_arr)):
            raise ValidationError("u_fn retornou valores não finitos.")
        return u_arr

    def _eval_nonlinearity(fn: Callable[..., Any] | None, arity: int, state: np.ndarray, u_val: np.ndarray | None, out_len: int) -> np.ndarray:
        if fn is None:
            return np.zeros(out_len, dtype=np.float64)
        raw = fn(state) if arity <= 1 else fn(state, u_val)
        return _coerce_finite_vector(raw, name="nonlinearity", expected_len=out_len)

    def _eval_weights(state: np.ndarray, u_val: np.ndarray | None) -> np.ndarray:
        if premise_fn is None:
            return np.full(r, 1.0 / r, dtype=np.float64)
        raw = premise_fn(state) if prem_arity <= 1 else premise_fn(state, u_val)
        return _normalize_weights(raw, r)

    def _rhs(t_cur: float, aug_state: np.ndarray) -> np.ndarray:
        x_cur = aug_state[:n]
        xh_cur = aug_state[n:]

        u_val = _eval_u(t_cur, x_cur)
        w_plant = _eval_weights(x_cur, u_val)
        w_obs = _eval_weights(xh_cur, u_val)

        A_plant = sum(w_plant[i] * spec.A_vertices[i] for i in range(r))
        C_plant = sum(w_plant[i] * c_list[i] for i in range(r))

        A_obs = sum(w_obs[i] * spec.A_vertices[i] for i in range(r))
        C_obs = sum(w_obs[i] * c_list[i] for i in range(r))
        L_obs = sum(w_obs[i] * L_list[i] for i in range(r))

        phi_x = _eval_nonlinearity(nonlinearity_fn, nl_arity, x_cur, u_val, n)
        phi_xh = _eval_nonlinearity(nonlinearity_fn, nl_arity, xh_cur, u_val, n)

        psi_x = _eval_nonlinearity(output_nonlinearity_fn, out_nl_arity, x_cur, u_val, p)
        psi_xh = _eval_nonlinearity(output_nonlinearity_fn, out_nl_arity, xh_cur, u_val, p)

        bu_plant = np.zeros(n, dtype=np.float64)
        bu_obs = np.zeros(n, dtype=np.float64)
        if b_list is not None and u_val is not None:
            B_plant = sum(w_plant[i] * b_list[i] for i in range(r))
            B_obs = sum(w_obs[i] * b_list[i] for i in range(r))
            bu_plant = B_plant @ u_val
            bu_obs = B_obs @ u_val

        y_plant = C_plant @ x_cur + psi_x
        y_obs = C_obs @ xh_cur + psi_xh
        innovation = y_plant - y_obs

        dx = A_plant @ x_cur + bu_plant + phi_x
        dx_hat = A_obs @ xh_cur + bu_obs + phi_xh + L_obs @ innovation
        return np.concatenate((dx, dx_hat))

    n_steps = max(1, int(np.ceil((tf - t0) / dt_val)))
    t_list: list[float] = [t0]
    x_hist: list[np.ndarray] = [x_init.copy()]
    xh_hist: list[np.ndarray] = [x_hat_init.copy()]

    aug = np.concatenate((x_init, x_hat_init))
    t_cur = t0
    for step in range(n_steps):
        h = dt_val if step < n_steps - 1 else (tf - t_cur)
        if h <= 0.0:
            break
        k1 = _rhs(t_cur, aug)
        k2 = _rhs(t_cur + 0.5 * h, aug + 0.5 * h * k1)
        k3 = _rhs(t_cur + 0.5 * h, aug + 0.5 * h * k2)
        k4 = _rhs(t_cur + h, aug + h * k3)
        aug = aug + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        if not np.all(np.isfinite(aug)):
            raise NumericalInconclusiveError(
                message="Simulação do observador TS divergiu para valores não finitos.",
                parameters={"step": step, "t": t_cur + h},
            )
        t_cur = t0 + (step + 1) * dt_val if step < n_steps - 1 else tf
        t_list.append(t_cur)
        x_hist.append(aug[:n].copy())
        xh_hist.append(aug[n:].copy())

    t_arr = np.asarray(t_list, dtype=np.float64)
    x_arr = np.vstack(x_hist)
    xh_arr = np.vstack(xh_hist)
    err_arr = x_arr - xh_arr
    max_final_error = float(np.linalg.norm(err_arr[-1]))
    converged = bool(max_final_error < convergence_tol)

    return {
        "t": t_arr,
        "x": x_arr,
        "x_hat": xh_arr,
        "error": err_arr,
        "max_final_error": max_final_error,
        "converged": converged,
    }


__all__ = [
    "TSUnmeasuredObserverSpec",
    "build_dmvt_nonlinearity_spec",
    "build_gradient_factorization_spec",
    "simulate_ts_unmeasured_observer",
]
