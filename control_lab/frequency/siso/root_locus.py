"""Lugar das raízes (Root Locus) com continuidade de ramos via designação ótima (Seção 5.3 e 13.5)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.optimize

from control_lab.core.tensors import complex_to_pair, ensure_finite_float64
from control_lab.diagnostics import (
    ControlLabError,
    Provenance,
    Result,
    ValidationError,
    WarningItem,
    build_provenance,
)

from ._utils import (
    compute_poles_zeros_gain,
    extract_siso_tf_channel,
    handle_failure,
    sort_complex_roots,
)


def _compute_breakaway_points(num: np.ndarray, den: np.ndarray) -> list[dict[str, Any]]:
    """Calcula pontos de quebra (breakaway/break-in) resolvendo N'(s)D(s) - N(s)D'(s) = 0 para K >= 0."""
    d_num = np.polyder(num) if num.size > 1 else np.array([0.0], dtype=np.float64)
    d_den = np.polyder(den) if den.size > 1 else np.array([0.0], dtype=np.float64)
    term1 = np.polymul(d_num, den)
    term2 = np.polymul(num, d_den)
    max_len = max(term1.size, term2.size)
    t1_pad = np.pad(term1, (max_len - term1.size, 0))
    t2_pad = np.pad(term2, (max_len - term2.size, 0))
    diff_poly = np.trim_zeros(t1_pad - t2_pad, "f")
    if diff_poly.size <= 1:
        return []

    cand_roots = sort_complex_roots(np.roots(diff_poly))
    break_pts: list[dict[str, Any]] = []
    for s_val in cand_roots:
        n_val = complex(np.polyval(num, s_val))
        if abs(n_val) <= 1e-12:
            continue
        d_val = complex(np.polyval(den, s_val))
        k_complex = -d_val / n_val
        if abs(k_complex.imag) <= 1e-6 * max(1.0, abs(k_complex.real)) and k_complex.real >= -1e-9:
            k_real = max(0.0, float(k_complex.real))
            # Evitar duplicatas próximas
            if any(abs(s_val - (bp["s_real"] + 1j * bp["s_imag"])) <= 1e-5 for bp in break_pts):
                continue
            break_pts.append(
                {
                    "s_real": float(np.real(s_val)),
                    "s_imag": float(np.imag(s_val)),
                    "gain_K": k_real,
                    "on_real_axis": abs(float(np.imag(s_val))) <= 1e-7,
                }
            )
    break_pts.sort(key=lambda item: item["gain_K"])
    return break_pts


def _build_default_gains(
    num: np.ndarray,
    den: np.ndarray,
    break_pts: list[dict[str, Any]],
    *,
    n_gains: int = 250,
    k_max: float | None = None,
) -> np.ndarray:
    """Constrói malha de ganhos K >= 0 incluindo K=0 e vizinhanças refinadas dos pontos de quebra."""
    lead_num = abs(float(num[0]))
    lead_den = abs(float(den[0]))
    k_scale = (lead_den / lead_num) if lead_num > 1e-12 else 1.0

    break_ks = [bp["gain_K"] for bp in break_pts if bp["gain_K"] > 1e-8]
    if k_max is not None:
        resolved_k_max = float(k_max)
    elif break_ks:
        resolved_k_max = max(20.0 * k_scale, 5.0 * max(break_ks))
    else:
        resolved_k_max = max(50.0, 50.0 * k_scale)

    if not (math.isfinite(resolved_k_max) and resolved_k_max > 0.0):
        raise ValidationError("k_max deve ser número real positivo finito.")

    k_min_pos = min(1e-4 * k_scale, 1e-4 * resolved_k_max)
    log_ks = np.logspace(math.log10(k_min_pos), math.log10(resolved_k_max), max(20, n_gains - 1), dtype=np.float64)
    extra_ks: list[float] = [0.0]
    for bk in break_ks:
        if bk <= resolved_k_max:
            extra_ks.extend([max(0.0, 0.98 * bk), bk, min(resolved_k_max, 1.02 * bk)])

    all_ks = np.unique(np.concatenate([np.asarray(extra_ks, dtype=np.float64), log_ks]))
    return np.sort(all_ks)


def root_locus(
    plant: Any,
    gains: Any = None,
    *,
    feedback_sign: str = "negative",
    n_gains: int = 250,
    k_max: float | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Calcula o lugar das raízes SISO com associação contínua de ramos via linear_sum_assignment.

    Equação característica:
    - `feedback_sign='negative'`: $D(s) + K N(s) = 0$
    - `feedback_sign='positive'`: $D(s) - K N(s) = 0$
    """
    prov: Provenance = build_provenance(
        "frequency.siso.root_locus",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings_out: list[WarningItem] = []

    try:
        if feedback_sign not in ("negative", "positive"):
            raise ValidationError(
                message=f"feedback_sign inválido: {feedback_sign!r}. Use 'negative' ou 'positive'.",
                parameters={"feedback_sign": feedback_sign},
            )
        if isinstance(n_gains, bool) or not isinstance(n_gains, int) or n_gains < 2:
            raise ValidationError("n_gains deve ser inteiro >= 2.")

        ch = extract_siso_tf_channel(plant, require_strictly_siso=True)
        num_raw = ch["num"]
        den_raw = ch["den"]
        dt = ch["dt"]
        domain = ch["domain"]
        warnings_out.extend(ch["warnings"])

        sign_mult = 1.0 if feedback_sign == "negative" else -1.0
        num_eff = sign_mult * num_raw

        pzk = compute_poles_zeros_gain(num_raw, den_raw)
        open_poles = pzk["poles"]
        open_zeros = pzk["zeros"]

        n_branches = max(den_raw.size - 1, num_raw.size - 1)
        if n_branches < 1:
            raise ValidationError(
                message="Sistema puramente estático (sem polos nem zeros) não possui lugar das raízes dinâmico.",
                parameters={"deg_den": den_raw.size - 1, "deg_num": num_raw.size - 1},
            )

        break_pts = _compute_breakaway_points(num_eff, den_raw)

        if gains is not None:
            k_vec = ensure_finite_float64(gains, ndim=1, name="gains")
            if k_vec.size < 1:
                raise ValidationError("Vetor gains deve conter ao menos 1 ganho.")
            if np.any(k_vec < 0.0):
                raise ValidationError(
                    message="Vetor gains deve conter ganhos não-negativos (K >= 0); use feedback_sign para inverter sinal.",
                    parameters={"min_gain": float(np.min(k_vec))},
                )
            if k_vec.size >= 2 and not np.all(np.diff(k_vec) >= 0.0):
                raise ValidationError("Vetor gains deve estar em ordem não-decrescente.")
        else:
            k_vec = _build_default_gains(num_eff, den_raw, break_pts, n_gains=n_gains, k_max=k_max)

        max_len = n_branches + 1
        den_pad = np.pad(den_raw, (max_len - den_raw.size, 0))
        num_pad = np.pad(num_eff, (max_len - num_eff.size, 0))

        n_k = k_vec.shape[0]
        branches = np.zeros((n_k, n_branches), dtype=np.complex128)
        branch_jump_norms = np.zeros(max(0, n_k - 1), dtype=np.float64)

        for idx, k_val in enumerate(k_vec):
            poly_k = den_pad + float(k_val) * num_pad
            poly_trim = np.trim_zeros(poly_k, "f")
            roots_k = np.roots(poly_trim) if poly_trim.size > 1 else np.array([], dtype=np.complex128)
            if roots_k.size < n_branches:
                # Se grau cair em ganho específico (ex.: K=0 quando grau(num) > grau(den)), preenche com raiz distante finita
                pad_val = open_poles[0] if open_poles.size > 0 else 0.0 + 0j
                roots_k = np.pad(roots_k, (0, n_branches - roots_k.size), constant_values=pad_val)

            if idx == 0:
                branches[0, :] = sort_complex_roots(roots_k)
            else:
                prev_roots = branches[idx - 1, :]
                # Matriz de custo quadrático |r_prev[i] - r_curr[j]|^2 para preservar identidade de ramo
                diff_mat = prev_roots[:, None] - roots_k[None, :]
                cost_mat = (diff_mat.real**2) + (diff_mat.imag**2)
                row_ind, col_ind = scipy.optimize.linear_sum_assignment(cost_mat)
                matched = np.zeros(n_branches, dtype=np.complex128)
                matched[row_ind] = roots_k[col_ind]
                branches[idx, :] = matched
                branch_jump_norms[idx - 1] = float(np.max(np.abs(matched - prev_roots)))

        # Assíntotas para n - m > 0
        n_poles = open_poles.size
        n_zeros = open_zeros.size
        rel_deg = n_poles - n_zeros
        asymptotes: dict[str, Any] | None = None
        if rel_deg > 0:
            centroid = float((np.sum(np.real(open_poles)) - np.sum(np.real(open_zeros))) / rel_deg)
            if feedback_sign == "negative":
                angles_deg = [float((180.0 * (2 * q + 1)) / rel_deg) for q in range(rel_deg)]
            else:
                angles_deg = [float((360.0 * q) / rel_deg) for q in range(rel_deg)]
            asymptotes = {
                "relative_degree": int(rel_deg),
                "centroid": centroid,
                "angles_deg": angles_deg,
            }

        # Detecção de cruzamentos de estabilidade ao longo dos ramos (Re(s)=0 no contínuo, |z|=1 no discreto)
        stability_crossings: list[dict[str, Any]] = []
        for b_idx in range(n_branches):
            b_curve = branches[:, b_idx]
            metric = np.real(b_curve) if domain == "continuous" else (np.abs(b_curve) - 1.0)
            for k_idx in range(n_k - 1):
                m0 = float(metric[k_idx])
                m1 = float(metric[k_idx + 1])
                if (m0 < -1e-9 and m1 >= -1e-9) or (m0 > 1e-9 and m1 <= 1e-9):
                    alpha = abs(m0) / (abs(m0) + abs(m1)) if (abs(m0) + abs(m1)) > 0.0 else 0.5
                    k_crit = float(k_vec[k_idx] + alpha * (k_vec[k_idx + 1] - k_vec[k_idx]))
                    s_crit = complex(b_curve[k_idx] + alpha * (b_curve[k_idx + 1] - b_curve[k_idx]))
                    stability_crossings.append(
                        {
                            "branch_index": int(b_idx),
                            "gain_K": k_crit,
                            "pole_real": float(np.real(s_crit)),
                            "pole_imag": float(np.imag(s_crit)),
                            "direction": "destabilizing" if m1 > m0 else "stabilizing",
                        }
                    )

        assumptions = {
            "domain": domain,
            "dt": dt,
            "feedback_sign": feedback_sign,
            "branch_matching": "scipy.optimize.linear_sum_assignment",
        }
        diagnostics = {
            "n_gains": int(n_k),
            "n_branches": int(n_branches),
            "relative_degree": int(rel_deg),
            "max_step_jump": float(np.max(branch_jump_norms)) if branch_jump_norms.size > 0 else 0.0,
            "n_breakaway_points": len(break_pts),
            "n_stability_crossings": len(stability_crossings),
        }

        return Result(
            status="warning" if warnings_out else "success",
            data={
                "gains": k_vec,
                "roots": branches,
                "open_loop_poles": pzk["poles_pair"],
                "open_loop_zeros": pzk["zeros_pair"],
                "asymptotes": asymptotes,
                "breakaway_points": break_pts,
                "stability_crossings": stability_crossings,
                "domain": domain,
                "dt": dt,
                "feedback_sign": feedback_sign,
                "stability_boundary": "imaginary_axis" if domain == "continuous" else "unit_circle",
                "series_semantics": "numeric_verified",
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=build_provenance("frequency.siso.root_locus", model_revision=ch["revision"]),
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        return handle_failure(
            exc,
            raise_on_error=raise_on_error,
            provenance=prov,
            assumptions=assumptions,
            diagnostics=diagnostics,
            warnings_out=warnings_out,
        )
