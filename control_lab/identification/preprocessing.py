"""Pré-processamento de sinais, gerador determinístico de PRBS e diagnóstico de Persistência de Excitação (PE).

Escopo normativo (CL-DIR-001 Seção 5.1, Seção 5.2, Seção 10.3, Seção 10.4, Seção 13.6 e Apêndice C):
- Pré-processamento explícito e reversível (remoção de média, tendência linear, reescalonamento);
- Geração de PRBS determinística por LFSR de comprimento máximo ou gerador explícito com seed;
- Diagnóstico de Persistência de Excitação (PE) via matriz de covariância de Hankel dos sinais de entrada
  e análise de posto numérico / número de condição por SVD (sem inversão matricial explícita).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

import numpy as np
import scipy.linalg
import scipy.signal

from control_lab.core.models import Dataset
from control_lab.core.tensors import array_to_tensor, ensure_finite_float64, tensor_to_array
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

DEFAULT_COND_WARN_THRESHOLD: float = 1e8
DEFAULT_RANK_RTOL: float = 1e-10

# Polinômios primitivos padrão (taps 1-indexed) para LFSR de comprimento máximo 2^m - 1
_LFSR_PRIMITIVE_TAPS: dict[int, tuple[int, ...]] = {
    2: (2, 1),
    3: (3, 2),
    4: (4, 3),
    5: (5, 3),
    6: (6, 5),
    7: (7, 6),
    8: (8, 6, 5, 4),
    9: (9, 5),
    10: (10, 7),
    11: (11, 9),
    12: (12, 11, 10, 4),
    13: (13, 12, 11, 8),
    14: (14, 13, 12, 2),
    15: (15, 14),
    16: (16, 15, 13, 4),
}


def handle_id_failure(
    exc: Exception,
    *,
    prov: Provenance,
    assumptions: Mapping[str, Any] | None = None,
    diagnostics: Mapping[str, Any] | None = None,
    warnings: list[WarningItem] | tuple[WarningItem, ...] = (),
    raise_on_error: bool = False,
) -> Result:
    """Converte exceção em Result(status='failure') ou propaga se raise_on_error=True."""
    if raise_on_error:
        if isinstance(exc, ControlLabError):
            raise exc
        raise ValidationError(str(exc)) from exc

    if isinstance(exc, ControlLabError):
        typed_err = exc.to_typed_error()
    else:
        typed_err = ValidationError(str(exc)).to_typed_error()

    return Result(
        status="failure",
        data=None,
        assumptions=dict(assumptions) if assumptions is not None else {},
        diagnostics=dict(diagnostics) if diagnostics is not None else {},
        provenance=prov,
        warnings=tuple(warnings),
        error=typed_err,
    )


def resolve_dataset_inputs(
    dataset_or_u: Any = None,
    y: Any = None,
    t: Any = None,
    *,
    dataset: Dataset | Mapping[str, Any] | None = None,
    u: Any = None,
    dt: float | None = None,
    require_uniform: bool = True,
    allow_irregular_sampling: bool = False,
    sampling_rtol: float = 1e-6,
) -> Dataset:
    """Normaliza entradas (Dataset, dict serializado ou arrays t, u, y) em instância Dataset validada."""
    ds_cand = dataset if dataset is not None else (
        dataset_or_u if isinstance(dataset_or_u, (Dataset, Mapping)) and y is None and u is None else None
    )

    if ds_cand is not None:
        if isinstance(ds_cand, Dataset):
            ds_obj = ds_cand
        elif isinstance(ds_cand, Mapping):
            if ds_cand.get("kind") == "Dataset" and "schema_version" in ds_cand:
                ds_obj = Dataset.from_dict(ds_cand)
            elif "u" in ds_cand and "y" in ds_cand:
                u_arr = (
                    tensor_to_array(ds_cand["u"])
                    if isinstance(ds_cand["u"], Mapping) and "data" in ds_cand["u"]
                    else ds_cand["u"]
                )
                y_arr = (
                    tensor_to_array(ds_cand["y"])
                    if isinstance(ds_cand["y"], Mapping) and "data" in ds_cand["y"]
                    else ds_cand["y"]
                )
                n_s = np.asarray(u_arr).shape[0]
                dt_val = float(dt if dt is not None else ds_cand.get("dt", 1.0) or 1.0)
                t_raw = ds_cand.get("t")
                if t_raw is None:
                    t_arr = np.arange(n_s, dtype=np.float64) * dt_val
                elif isinstance(t_raw, Mapping) and "data" in t_raw:
                    t_arr = tensor_to_array(t_raw, expected_ndim=1)
                else:
                    t_arr = np.asarray(t_raw, dtype=np.float64)
                ds_obj = Dataset(
                    t=t_arr,
                    u=u_arr,
                    y=y_arr,
                    dt=dt_val,
                    require_uniform=False,
                    sampling_rtol=sampling_rtol,
                )
            else:
                raise ValidationError("Mapeamento de Dataset inválido: requer campos 'u' e 'y'.")
        else:
            raise ValidationError(f"Tipo de dataset inválido: {type(ds_cand).__name__}.")

        if dt is not None and ds_obj.dt is not None and not math.isclose(float(dt), float(ds_obj.dt), rel_tol=1e-9):
            raise ValidationError(
                message=f"Conflito entre dt informado ({dt}) e Dataset.dt ({ds_obj.dt}).",
                parameters={"dt_arg": dt, "dataset_dt": ds_obj.dt},
            )
        if ds_obj.dt is None:
            inferred_dt = float(dt) if dt is not None else float(ds_obj.sampling_diagnostics.get("dt_mean", 1.0) or 1.0)
            if inferred_dt <= 0.0:
                inferred_dt = 1.0
            ds_obj = ds_obj.with_revision(ds_obj.revision, dt=inferred_dt)
    else:
        u_in = u if u is not None else dataset_or_u
        if u_in is None or y is None:
            raise ValidationError(
                message="Forneça um objeto Dataset ou os pares de séries temporais (u, y).",
                next_step="Passe Dataset(t, u, y, dt=...) ou u=..., y=..., dt=...",
            )
        if isinstance(u_in, Mapping) and "data" in u_in:
            u_in = tensor_to_array(u_in)
        if isinstance(y, Mapping) and "data" in y:
            y = tensor_to_array(y)

        u_arr = ensure_finite_float64(u_in, name="u")
        y_arr = ensure_finite_float64(y, name="y")
        n_samples = u_arr.shape[0]
        resolved_dt = float(dt) if dt is not None else None
        if t is None:
            step = resolved_dt if resolved_dt is not None else 1.0
            if step <= 0.0 or not math.isfinite(step):
                raise ValidationError(f"Passo de amostragem dt deve ser positivo finito, recebido {step!r}.")
            t_arr = np.arange(n_samples, dtype=np.float64) * step
            resolved_dt = step
        else:
            if isinstance(t, Mapping) and "data" in t:
                t = tensor_to_array(t, expected_ndim=1)
            t_arr = ensure_finite_float64(t, ndim=1, name="t")
            if resolved_dt is None and t_arr.size >= 2:
                resolved_dt = float(np.mean(np.diff(t_arr)))
            elif resolved_dt is None:
                resolved_dt = 1.0

        ds_obj = Dataset(
            t=t_arr,
            u=u_arr,
            y=y_arr,
            dt=resolved_dt,
            require_uniform=False,
            sampling_rtol=sampling_rtol,
        )

    if require_uniform and not allow_irregular_sampling and not ds_obj.is_uniform_sampling:
        diag = ds_obj.sampling_diagnostics
        raise ValidationError(
            message=(
                f"Amostragem irregular detectada em identificação discreta "
                f"(rel_jitter={diag['rel_jitter']:.3e} > rtol={diag['sampling_rtol']:.3e})."
            ),
            parameters=diag,
            next_step="Reamostre os sinais para grade uniforme ou passe allow_irregular_sampling=True.",
        )

    return ds_obj


def generate_prbs(
    n_samples: int,
    *,
    register_length: int = 9,
    clock_divider: int = 1,
    levels: tuple[float, float] = (-1.0, 1.0),
    n_channels: int = 1,
    seed: int | None = None,
) -> np.ndarray:
    """Gera sequência binária pseudoaleatória (PRBS) determinística via LFSR de comprimento máximo.

    Problema matemático
    -------------------
    Produz sinal de excitação binário de dois níveis $u(k) \\in \\{u_{\\min}, u_{\\max}\\}$ baseado em
    registrador de deslocamento com realimentação linear (LFSR) de polinômio primitivo sobre GF(2),
    com período máximo $N_p = 2^m - 1$ (onde $m = \\text{register\\_length}$). Para múltiplos canais,
    aplica deslocamentos circulares disjuntos ou sementes independentes para evitar colinearidade entre entradas.
    """
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 1:
        raise ValidationError(f"n_samples deve ser inteiro >= 1, recebido {n_samples!r}.")
    if isinstance(register_length, bool) or not isinstance(register_length, int) or not (2 <= register_length <= 16):
        raise ValidationError(f"register_length deve ser inteiro em [2, 16], recebido {register_length!r}.")
    if isinstance(clock_divider, bool) or not isinstance(clock_divider, int) or clock_divider < 1:
        raise ValidationError(f"clock_divider deve ser inteiro >= 1, recebido {clock_divider!r}.")
    if isinstance(n_channels, bool) or not isinstance(n_channels, int) or n_channels < 1:
        raise ValidationError(f"n_channels deve ser inteiro >= 1, recebido {n_channels!r}.")
    if not isinstance(levels, (tuple, list)) or len(levels) != 2:
        raise ValidationError("levels deve ser um par (low, high).")
    low, high = float(levels[0]), float(levels[1])
    if not (math.isfinite(low) and math.isfinite(high)) or low == high:
        raise ValidationError(f"levels deve conter dois valores finitos distintos, recebido {levels!r}.")

    taps = _LFSR_PRIMITIVE_TAPS[register_length]
    n_base = int(math.ceil(n_samples / clock_divider)) + n_channels * max(7, register_length * 2)

    rng = np.random.default_rng(seed if seed is not None else 0)
    # Estado inicial não nulo de m bits determinado pela seed
    if seed is None:
        init_bits = [1] * register_length
    else:
        raw_val = int(rng.integers(1, (1 << register_length)))
        init_bits = [(raw_val >> bit) & 1 for bit in range(register_length)]
        if not any(init_bits):
            init_bits[0] = 1

    state = list(init_bits)
    base_bits = np.empty(n_base, dtype=np.int64)
    for k in range(n_base):
        out_bit = state[-1]
        base_bits[k] = out_bit
        fb = 0
        for tap in taps:
            fb ^= state[tap - 1]
        state = [fb] + state[:-1]

    channels: list[np.ndarray] = []
    shift_step = max(3, (1 << register_length) // max(2, n_channels + 1))
    for ch in range(n_channels):
        offset = (ch * shift_step) % max(1, n_base - int(math.ceil(n_samples / clock_divider)))
        ch_bits = base_bits[offset : offset + int(math.ceil(n_samples / clock_divider))]
        if clock_divider > 1:
            ch_bits = np.repeat(ch_bits, clock_divider)[:n_samples]
        else:
            ch_bits = ch_bits[:n_samples]
        sig = np.where(ch_bits == 1, high, low).astype(np.float64)
        channels.append(sig)

    if n_channels == 1:
        return channels[0]
    return np.column_stack(channels)


def check_persistence_of_excitation(
    u: Any,
    order: int,
    *,
    rank_rtol: float = DEFAULT_RANK_RTOL,
    cond_warn_threshold: float = DEFAULT_COND_WARN_THRESHOLD,
    raise_on_error: bool = False,
) -> Result:
    """Avalia Persistência de Excitação (PE) de ordem `order` via SVD da matriz de regressores de Hankel.

    Problema matemático
    -------------------
    Um sinal $u(k) \\in \\mathbb{R}^m$ é persistentemente excitante de ordem $L$ se a matriz de
    covariância empírica de Hankel $R_{uu}(L) = \\frac{1}{N_{\\text{eff}}} H_L^T H_L \\in \\mathbb{R}^{(m L) \\times (m L)}$
    for simétrica definida positiva (posto completo $m L$). Avaliamos diretamente os valores singulares
    de $H_L$ via decomposição SVD sem formar ou inverter $(H_L^T H_L)^{-1}$.
    """
    prov = build_provenance(
        "identification.check_persistence_of_excitation",
        tolerances={"rank_rtol": float(rank_rtol), "cond_warn_threshold": float(cond_warn_threshold)},
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if isinstance(order, bool) or not isinstance(order, int) or order < 1:
            raise ValidationError(f"Ordem de persistência de excitação deve ser inteiro >= 1, recebido {order!r}.")
        if isinstance(u, Dataset):
            u_arr = u.u
        elif isinstance(u, Mapping) and "data" in u:
            u_arr = tensor_to_array(u)
        else:
            u_arr = ensure_finite_float64(u, name="u")

        if u_arr.ndim == 1:
            u_mat = u_arr.reshape(-1, 1)
        elif u_arr.ndim == 2:
            u_mat = u_arr
        else:
            raise DimensionMismatchError(f"Sinal u deve ser 1D ou 2D, recebido {u_arr.ndim}D.")

        n_samples, n_inputs = u_mat.shape
        expected_rank = n_inputs * order
        n_eff = n_samples - order + 1
        if n_eff < expected_rank:
            raise ValidationError(
                message=(
                    f"Amostras insuficientes ({n_samples}) para avaliar PE de ordem {order} "
                    f"com {n_inputs} entrada(s) (mínimo {order + expected_rank - 1})."
                ),
                parameters={"n_samples": n_samples, "order": order, "n_inputs": n_inputs},
            )

        # Matriz de Hankel centrada e não centrada
        blocks_raw: list[np.ndarray] = []
        blocks_centered: list[np.ndarray] = []
        u_mean = np.mean(u_mat, axis=0, keepdims=True)
        u_std = np.std(u_mat, axis=0)
        is_constant_channel = [bool(s <= 1e-14 * max(1.0, float(np.max(np.abs(u_mat[:, j]))))) for j, s in enumerate(u_std)]

        u_cent = u_mat - u_mean
        for lag in range(order):
            sl = slice(order - 1 - lag, n_samples - lag)
            blocks_raw.append(u_mat[sl, :])
            blocks_centered.append(u_cent[sl, :])

        H_raw = np.hstack(blocks_raw)
        H_cent = np.hstack(blocks_centered)

        svals_raw = scipy.linalg.svdvals(H_raw)
        svals_cent = scipy.linalg.svdvals(H_cent)

        s_max_raw = float(svals_raw[0]) if svals_raw.size > 0 else 0.0
        s_min_raw = float(svals_raw[-1]) if svals_raw.size > 0 else 0.0
        cutoff_raw = max(float(rank_rtol) * s_max_raw, 1e-14)
        rank_raw = int(np.sum(svals_raw > cutoff_raw))

        s_max_cent = float(svals_cent[0]) if svals_cent.size > 0 else 0.0
        s_min_cent = float(svals_cent[-1]) if svals_cent.size > 0 else 0.0
        cutoff_cent = max(float(rank_rtol) * s_max_cent, 1e-14)
        rank_cent = int(np.sum(svals_cent > cutoff_cent))

        cond_raw = float(s_max_raw / s_min_raw) if s_min_raw > 1e-15 * max(1.0, s_max_raw) else 1e16
        cond_cent = float(s_max_cent / s_min_cent) if s_min_cent > 1e-15 * max(1.0, s_max_cent) else 1e16

        # Para excitação dinâmica de ordem >= 1, um sinal constante tem variância nula (rank_cent == 0)
        # e não excita modos dinâmicos (mesmo que rank_raw seja 1 para order=1).
        any_constant = any(is_constant_channel)
        is_pe_raw = (rank_raw == expected_rank) and not any_constant
        is_pe_dynamic = (rank_cent == expected_rank) and not any_constant
        rank_deficient = not is_pe_dynamic

        if rank_deficient:
            warnings_out.append(
                WarningItem(
                    code="PERSISTENCE_OF_EXCITATION_INSUFFICIENT",
                    message=(
                        f"Persistência de excitação insuficiente para ordem {order}: "
                        f"posto dinâmico={rank_cent}/{expected_rank}, posto bruto={rank_raw}/{expected_rank}."
                    ),
                    details={
                        "order": order,
                        "expected_rank": expected_rank,
                        "rank_dynamic": rank_cent,
                        "rank_raw": rank_raw,
                        "any_constant_channel": any_constant,
                    },
                )
            )
        elif cond_cent > cond_warn_threshold or cond_raw > cond_warn_threshold:
            warnings_out.append(
                WarningItem(
                    code="ILL_CONDITIONED_EXCITATION",
                    message=(
                        f"Matriz de excitação de Hankel mal condicionada "
                        f"(cond_dynamic={cond_cent:.3e}, cond_raw={cond_raw:.3e})."
                    ),
                    details={"cond_dynamic": cond_cent, "cond_raw": cond_raw},
                )
            )

        cov_cent = (H_cent.T @ H_cent) / float(n_eff)

        assumptions = {
            "pe_satisfied": bool(is_pe_dynamic),
            "pe_raw_satisfied": bool(is_pe_raw),
            "rank_deficient": bool(rank_deficient),
            "any_constant_input": bool(any_constant),
        }
        diagnostics = {
            "order": int(order),
            "n_inputs": int(n_inputs),
            "n_effective_samples": int(n_eff),
            "expected_rank": int(expected_rank),
            "rank_raw": int(rank_raw),
            "rank_dynamic": int(rank_cent),
            "rank_deficient": bool(rank_deficient),
            "condition_raw": float(cond_raw),
            "condition_dynamic": float(cond_cent),
            "singular_values_raw": [float(v) for v in svals_raw.tolist()],
            "singular_values_dynamic": [float(v) for v in svals_cent.tolist()],
            "channel_std": [float(v) for v in u_std.tolist()],
            "is_constant_channel": is_constant_channel,
        }
        data = {
            "is_persistently_exciting": bool(is_pe_dynamic),
            "rank_deficient": bool(rank_deficient),
            "order": int(order),
            "expected_rank": int(expected_rank),
            "rank_raw": int(rank_raw),
            "rank_dynamic": int(rank_cent),
            "covariance_matrix": array_to_tensor(cov_cent, dtype="float64", order="C"),
            "singular_values_raw": array_to_tensor(svals_raw, dtype="float64", order="C"),
            "singular_values_dynamic": array_to_tensor(svals_cent, dtype="float64", order="C"),
        }
        status = "warning" if warnings_out else "success"
        return Result(
            status=status,
            data=data,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except Exception as exc:
        return handle_id_failure(
            exc,
            prov=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings=warnings_out,
            raise_on_error=raise_on_error,
        )


def preprocess_dataset(
    dataset_or_u: Any = None,
    y: Any = None,
    t: Any = None,
    *,
    dataset: Dataset | Mapping[str, Any] | None = None,
    u: Any = None,
    dt: float | None = None,
    detrend_mode: str = "mean",
    normalize: bool = False,
    allow_irregular_sampling: bool = False,
    raise_on_error: bool = False,
) -> Result:
    """Aplica pré-processamento explícito (remoção de média/tendência linear e normalização opcional) ao Dataset.

    Preserva na proveniência e em `Result.data["preprocessing_info"]` os offsets, inclinações e escalas
    exatos removidos para auditoria e reconstrução do ponto de operação.
    """
    prov = build_provenance("identification.preprocess_dataset")
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if not isinstance(detrend_mode, str) or detrend_mode.lower() not in ("none", "mean", "constant", "linear"):
            raise ValidationError(
                f"detrend_mode inválido: {detrend_mode!r}. Use 'none', 'mean' ('constant') ou 'linear'."
            )
        mode = detrend_mode.lower()
        if mode == "constant":
            mode = "mean"

        ds = resolve_dataset_inputs(
            dataset_or_u,
            y,
            t,
            dataset=dataset,
            u=u,
            dt=dt,
            require_uniform=not allow_irregular_sampling,
            allow_irregular_sampling=allow_irregular_sampling,
        )
        warnings_out.extend(ds.warnings)

        u_proc = ds.u.copy()
        y_proc = ds.y.copy()
        u_mean = np.mean(u_proc, axis=0)
        y_mean = np.mean(y_proc, axis=0)

        if mode == "mean":
            u_proc = u_proc - u_mean
            y_proc = y_proc - y_mean
        elif mode == "linear":
            u_proc = scipy.signal.detrend(u_proc, axis=0, type="linear")
            y_proc = scipy.signal.detrend(y_proc, axis=0, type="linear")

        u_scale = np.ones(ds.n_inputs, dtype=np.float64)
        y_scale = np.ones(ds.n_outputs, dtype=np.float64)
        if normalize:
            u_std = np.std(u_proc, axis=0)
            y_std = np.std(y_proc, axis=0)
            for j in range(ds.n_inputs):
                if u_std[j] > 1e-14:
                    u_scale[j] = float(u_std[j])
                    u_proc[:, j] /= u_scale[j]
            for i in range(ds.n_outputs):
                if y_std[i] > 1e-14:
                    y_scale[i] = float(y_std[i])
                    y_proc[:, i] /= y_scale[i]

        pre_info = {
            "detrend_mode": mode,
            "normalized": bool(normalize),
            "u_mean": [float(v) for v in u_mean.tolist()],
            "y_mean": [float(v) for v in y_mean.tolist()],
            "u_scale": [float(v) for v in u_scale.tolist()],
            "y_scale": [float(v) for v in y_scale.tolist()],
        }

        new_prov = copy.deepcopy(ds.provenance)
        new_prov["preprocessing"] = pre_info
        ds_out = ds.with_revision(
            ds.revision + 1,
            u=u_proc,
            y=y_proc,
            provenance=new_prov,
        )

        assumptions = {
            "uniform_sampling": ds.is_uniform_sampling,
            "detrend_mode": mode,
            "normalized": bool(normalize),
        }
        diagnostics = {
            "n_samples": ds.n_samples,
            "sampling_diagnostics": ds.sampling_diagnostics,
            "preprocessing_info": pre_info,
        }
        return Result(
            status="warning" if warnings_out else "success",
            data={
                "dataset": ds_out.to_dict(),
                "preprocessing_info": pre_info,
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except Exception as exc:
        return handle_id_failure(
            exc,
            prov=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings=warnings_out,
            raise_on_error=raise_on_error,
        )


def split_dataset(
    dataset_or_u: Any = None,
    y: Any = None,
    t: Any = None,
    *,
    dataset: Dataset | Mapping[str, Any] | None = None,
    u: Any = None,
    dt: float | None = None,
    train_fraction: float = 0.7,
    train_slice: slice | None = None,
    val_slice: slice | None = None,
    allow_irregular_sampling: bool = False,
) -> tuple[Dataset, Dataset]:
    """Divide Dataset (ou séries t, u, y) em partições disjuntas de treino e validação (holdout)."""
    ds = resolve_dataset_inputs(
        dataset_or_u,
        y,
        t,
        dataset=dataset,
        u=u,
        dt=dt,
        require_uniform=not allow_irregular_sampling,
        allow_irregular_sampling=allow_irregular_sampling,
    )
    return ds.train_val_split(
        train_fraction=train_fraction,
        train_slice=train_slice,
        val_slice=val_slice,
    )
