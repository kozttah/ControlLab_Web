"""Testes unitários normativos da Frente F5 — Motor TPMT (WP-TSMOD-02-F5-TPMT-ENGINE).

Cobre integralmente `T-TSMOD-04`, `T-TSMOD-05`, `T-TSMOD-06` e a validação ponta a ponta
de `derive_ts_tpmt` + `evaluate_ts_premise_weights` (`representation_kind='tpmt_interpolated'`).
"""

from __future__ import annotations

import ast
import json
import math
import pathlib

import jsonschema
import numpy as np
import pytest
from referencing import Registry, Resource

from control_lab.core.models import TSStateSpace
from control_lab.diagnostics import NumericalInconclusiveError
from control_lab.fuzzy import (
    cno_matrix,
    derive_ts_tpmt,
    evaluate_ts_premise_weights,
    fold_mode,
    hooi_sampled_func,
    hosvd_sampled_func,
    mgk_matrix,
    mode_inverse_product,
    mode_product,
    reconstruct_tensor,
    resample_basis_1d,
    rno_ino_matrix,
    sn_nn_matrix,
    unfold_mode,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "contracts" / "schemas"


def _build_ts_schema_validator() -> jsonschema.Draft202012Validator:
    ts_schema = json.loads((SCHEMAS_DIR / "ts_state_space.schema.json").read_text(encoding="utf-8"))
    tensor_schema = json.loads((SCHEMAS_DIR / "tensor.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources(
        [
            (ts_schema["$id"], Resource.from_contents(ts_schema)),
            (tensor_schema["$id"], Resource.from_contents(tensor_schema)),
            ("tensor.schema.json", Resource.from_contents(tensor_schema)),
        ]
    )
    return jsonschema.Draft202012Validator(ts_schema, registry=registry)


# ---------------------------------------------------------------------------
# T-TSMOD-04: Invariantes Tensoriais, HOSVD (De Lathauwer) & HOOI Monotônica
# ---------------------------------------------------------------------------


def test_t_tsmod_04_unfold_fold_and_mode_product_identities() -> None:
    rng = np.random.default_rng(20261125)
    for shape in ((5, 4, 3), (4, 5, 3, 2), (3, 4, 5, 2, 2)):
        T = rng.standard_normal(shape)
        for d in range(T.ndim):
            U = unfold_mode(T, d)
            assert U.shape[0] == shape[d]
            T_back = fold_mode(U, d, shape)
            assert np.array_equal(T_back, T)

    # Identidade mode_inverse_product(mode_product(T, M, d), M, d) == T
    T4 = rng.standard_normal((4, 5, 2, 2))
    M = np.array([[2.0, 0.3, -0.1, 0.2], [0.1, 1.8, 0.4, -0.2], [-0.2, 0.1, 2.5, 0.3], [0.0, -0.3, 0.2, 1.9]])
    T_prod = mode_product(T4, M, 0)
    T_inv = mode_inverse_product(T_prod, M, 0)
    assert np.allclose(T_inv, T4, atol=1e-13, rtol=1e-13)

    # Rejeita matriz singular em mode_inverse_product
    M_sing = np.ones((4, 4), dtype=np.float64)
    with pytest.raises(NumericalInconclusiveError):
        mode_inverse_product(T4, M_sing, 0)


def test_t_tsmod_04_hosvd_orthonormality_and_de_lathauwer_bound() -> None:
    # Sistema 2D inspirado em exemplo_de_uso2.m: tensor (25, 25, 2, 2)
    x1 = np.linspace(-math.pi, math.pi, 25)
    x2 = np.linspace(-math.pi, math.pi, 25)
    T = np.zeros((25, 25, 2, 2), dtype=np.float64)
    for i, v1 in enumerate(x1):
        for j, v2 in enumerate(x2):
            T[i, j] = [
                [-1.0 - math.sin(v2) ** 2, 0.5 * math.sin(v1) ** 2],
                [0.5 * math.cos(v1) ** 2, -1.0 - math.cos(v2) ** 2],
            ]

    core, U_list, sv_list, bound = hosvd_sampled_func(T, tol=1e-10, ord_func=2)
    assert len(U_list) == 2
    assert len(sv_list) == 2
    assert core.shape[-2:] == (2, 2)

    # Ortonormalidade ||U^T U - I||_F <= 1e-13
    for U_d in U_list:
        r_d = U_d.shape[1]
        err_orth = float(np.linalg.norm(U_d.T @ U_d - np.eye(r_d), ord="fro"))
        assert err_orth <= 1e-13

    # Reconstrução exata no posto completo
    T_rec = reconstruct_tensor(core, U_list)
    err_full = float(np.linalg.norm(T - T_rec))
    assert err_full <= 1e-12
    assert err_full <= bound + 1e-12

    # Cota de truncamento de De Lathauwer sob truncamento deliberado
    rng = np.random.default_rng(42)
    T_noisy = T + 0.05 * rng.standard_normal(T.shape)
    core_tr, U_tr, sv_tr, bound_tr = hosvd_sampled_func(T_noisy, ranks=[2, 2], ord_func=2)
    err_tr = float(np.linalg.norm(T_noisy - reconstruct_tensor(core_tr, U_tr)))
    expected_bound = math.sqrt(float(np.sum(sv_tr[0][2:] ** 2) + np.sum(sv_tr[1][2:] ** 2)))
    assert abs(bound_tr - expected_bound) <= 1e-13
    assert err_tr <= bound_tr + 1e-12


def test_t_tsmod_04_hooi_monotonic_convergence_improves_over_hosvd() -> None:
    # Tensor 3D acoplado com não-separabilidade (G1=12, G2=12, G3=10, M1=2, M2=2)
    g1 = np.linspace(-1.0, 1.0, 12)
    g2 = np.linspace(-1.0, 1.0, 12)
    g3 = np.linspace(-1.0, 1.0, 10)
    X1, X2, X3 = np.meshgrid(g1, g2, g3, indexing="ij")
    T = np.zeros((12, 12, 10, 2, 2), dtype=np.float64)
    T[..., 0, 0] = np.sin(X1 * X2 + 0.5 * X3) + 0.3 * np.exp(-X1**2 - X2**2)
    T[..., 0, 1] = np.cos(X2 * X3 - X1)
    T[..., 1, 0] = np.tanh(X1 + X2 * X3)
    T[..., 1, 1] = 1.0 / (1.5 + np.sin(X1 + X3) * np.cos(X2))

    ranks = [2, 2, 2]
    hosvd_res = hosvd_sampled_func(T, ranks=ranks, ord_func=2)
    hosvd_err = float(np.linalg.norm(T - reconstruct_tensor(hosvd_res.core, hosvd_res.U_list)))

    hooi_res = hooi_sampled_func(T, ranks=ranks, ord_func=2, max_iter=40, conv_tol=1e-10)
    hist = hooi_res.error_history
    assert len(hist) >= 2
    assert abs(hist[0] - hosvd_err) <= 1e-12
    # Redução monotônica não-crescente do erro de Frobenius
    for k in range(1, len(hist)):
        assert hist[k] <= hist[k - 1] + 1e-11
    # HOOI melhora (ou iguala) HOSVD em posto reduzido
    assert hist[-1] <= hosvd_err + 1e-12
    assert hist[-1] < hosvd_err  # tensor acoplado tem ganho estrito
    for U_d in hooi_res.U_list:
        r_d = U_d.shape[1]
        assert float(np.linalg.norm(U_d.T @ U_d - np.eye(r_d), ord="fro")) <= 1e-13


# ---------------------------------------------------------------------------
# T-TSMOD-05: Fechos Convexos (SN-NN, RNO-INO, CNO, MGK) + AST Gate Zero inv
# ---------------------------------------------------------------------------


def test_t_tsmod_05_ast_gate_zero_linalg_inv_and_eval() -> None:
    """Garante por inspeção AST estática zero eval/exec/compile/getattr dinâmico e zero .inv()."""
    forbidden_funcs = {"eval", "exec", "compile", "getattr"}
    for fname in ("tpmt.py", "ts_bridge.py"):
        fpath = REPO_ROOT / "control_lab" / "fuzzy" / fname
        tree = ast.parse(fpath.read_text(encoding="utf-8"), filename=str(fpath))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in forbidden_funcs:
                    pytest.fail(f"Chamada proibida '{node.func.id}' encontrada em {fname}:{node.lineno}")
                if isinstance(node.func, ast.Attribute) and node.func.attr == "inv":
                    pytest.fail(f"Chamada proibida '.inv()' encontrada em {fname}:{node.lineno}")


def test_t_tsmod_05_sn_nn_rank_augmentation_zero_slice_exact_invariance() -> None:
    # Caso em que 1 NÃO está no espaço coluna de U: B(theta) = [cos(theta); sin(theta)] (sem constante!)
    theta = np.linspace(-math.pi, math.pi, 61)
    T = np.zeros((61, 2, 1), dtype=np.float64)
    T[:, 0, 0] = np.cos(theta)
    T[:, 1, 0] = np.sin(theta)

    core0, U_list, _, _ = hosvd_sampled_func(T, tol=1e-10, ord_func=2)
    assert U_list[0].shape == (61, 2)
    T_hosvd = reconstruct_tensor(core0, U_list)

    W_sn, T_sn, info_sn = sn_nn_matrix(U_list[0], core=core0, mode=0, sn_tol=1e-6)
    assert info_sn["rank_augmented"] is True
    assert W_sn.shape == (61, 3)
    assert info_sn["core"].shape[0] == 3
    assert info_sn["min_weight"] >= -1e-11
    assert info_sn["max_sum_deviation"] <= 1e-11

    T_after_sn = mode_product(info_sn["core"], W_sn, 0)
    assert float(np.linalg.norm(T_hosvd - T_after_sn)) <= 1e-11 * (1.0 + float(np.linalg.norm(T)))

    # Encadeia RNO-INO e CNO mantendo invariância exata
    for hull_fn in (rno_ino_matrix, cno_matrix):
        W_h, T_h, info_h = hull_fn(W_sn, core=info_sn["core"], mode=0)
        assert info_h["min_weight"] >= -1e-11
        assert info_h["max_sum_deviation"] <= 1e-11
        assert np.allclose(W_sn @ T_h, W_h, atol=1e-11)
        T_after_h = mode_product(info_h["core"], W_h, 0)
        assert float(np.linalg.norm(T_hosvd - T_after_h)) <= 1e-10 * (1.0 + float(np.linalg.norm(T)))


def test_t_tsmod_05_all_hull_transforms_and_mgk_rank_cases() -> None:
    # Testa r=1, r=2, r=3 e r=4 com reconstrução exata
    x = np.linspace(-1.5, 1.5, 51)
    T_r1 = np.ones((51, 2, 2), dtype=np.float64) * 3.0
    c1, U1, _, _ = hosvd_sampled_func(T_r1, tol=1e-10, ord_func=2)
    W1, _, i1 = sn_nn_matrix(U1[0], core=c1, mode=0)
    assert W1.shape == (51, 1)
    assert np.allclose(W1, 1.0, atol=1e-12)
    W1_rno, _, _ = rno_ino_matrix(W1, core=i1["core"], mode=0)
    W1_cno, _, _ = cno_matrix(W1, core=i1["core"], mode=0)
    assert np.allclose(W1_rno, 1.0, atol=1e-12)
    assert np.allclose(W1_cno, 1.0, atol=1e-12)

    # r=4: [1, x, x^2, sin(x)]
    T_r4 = np.zeros((51, 2, 2), dtype=np.float64)
    T_r4[:, 0, 0] = 1.0
    T_r4[:, 0, 1] = x
    T_r4[:, 1, 0] = x**2
    T_r4[:, 1, 1] = np.sin(x)
    c4, U4, _, _ = hosvd_sampled_func(T_r4, tol=1e-10, ord_func=2)
    assert U4[0].shape == (51, 4)
    W4_sn, _, i4_sn = sn_nn_matrix(U4[0], core=c4, mode=0)
    assert i4_sn["rank_augmented"] is False
    assert W4_sn.shape == (51, 4)
    assert i4_sn["min_weight"] >= -1e-11
    assert i4_sn["max_sum_deviation"] <= 1e-11

    for fn in (rno_ino_matrix, cno_matrix, mgk_matrix):
        W4_h, T4_h, i4_h = fn(W4_sn, core=i4_sn["core"], mode=0)
        assert i4_h["max_sum_deviation"] <= 1e-10
        if fn is not mgk_matrix:
            assert i4_h["min_weight"] >= -1e-10
        T_rec = mode_product(i4_h["core"], W4_h, 0)
        assert float(np.linalg.norm(T_r4 - T_rec)) <= 1e-9 * (1.0 + float(np.linalg.norm(T_r4)))
        assert np.allclose(W4_sn @ T4_h, W4_h, atol=1e-10)


# ---------------------------------------------------------------------------
# T-TSMOD-06: Aperto Geométrico CNO / RNO-INO vs SN-NN (test_uni2.m) + Reamostragem
# ---------------------------------------------------------------------------


def test_t_tsmod_06_unicycle_cno_and_rno_ino_tighter_than_sn_nn() -> None:
    """Benchmark clássico de test_uni.m / test_uni2.m: B(theta) = [cos(theta) 0; sin(theta) 0; 0 1]."""
    theta = np.linspace(-math.pi, math.pi, 101)
    Bd = np.zeros((101, 3, 2), dtype=np.float64)
    Bd[:, 0, 0] = np.cos(theta)
    Bd[:, 1, 0] = np.sin(theta)
    Bd[:, 2, 1] = 1.0

    core0, U_list, _, _ = hosvd_sampled_func(Bd, tol=1e-6, ord_func=2)
    assert U_list[0].shape == (101, 3)

    W_sn, _, info_sn = sn_nn_matrix(U_list[0], core=core0, mode=0)
    core_sn = info_sn["core"]

    W_rno, T_rno, info_rno = rno_ino_matrix(W_sn, core=core_sn, mode=0)
    W_cno, T_cno, info_cno = cno_matrix(W_sn, core=core_sn, mode=0)

    # Volume simplicial proporcional a |det(T)|^{-1}: maior |det(T)| => simplex menor (mais apertado)
    det_rno = abs(float(np.linalg.det(T_rno)))
    det_cno = abs(float(np.linalg.det(T_cno)))
    assert det_rno >= 1.0 - 1e-9
    assert det_cno >= det_rno - 1e-6
    assert det_cno > 1.5  # aperto geométrico expressivo sobre SN-NN (|det(I)| = 1)

    # Dispersão dos vértices sob CNO menor que sob SN-NN
    verts_sn = core_sn.reshape(3, -1)
    verts_cno = info_cno["core"].reshape(3, -1)
    spread_sn = float(np.linalg.norm(verts_sn - verts_sn.mean(axis=0, keepdims=True)))
    spread_cno = float(np.linalg.norm(verts_cno - verts_cno.mean(axis=0, keepdims=True)))
    assert spread_cno < spread_sn

    # Reconstrução exata mantida nos 3 fechos
    assert float(np.linalg.norm(Bd - mode_product(core_sn, W_sn, 0))) <= 1e-11
    assert float(np.linalg.norm(Bd - mode_product(info_rno["core"], W_rno, 0))) <= 1e-10
    assert float(np.linalg.norm(Bd - mode_product(info_cno["core"], W_cno, 0))) <= 1e-10


def test_cno_rechecks_weights_after_roundoff_correction(monkeypatch: pytest.MonkeyPatch) -> None:
    # A compressed simplex forces cancellation when evaluating the CNO transform.
    nominal = np.vstack((np.eye(3), np.full((1, 3), 1.0 / 3.0)))
    scale = 2.0**-14
    U = scale * nominal + (1.0 - scale) / 3.0
    candidate = (np.eye(3) - (1.0 - scale) / 3.0) / scale
    candidate[:, 0] -= 2e-11
    candidate[:, -1] = 1.0 - np.sum(candidate[:, :-1], axis=1)
    assert np.min(U @ candidate) < 0

    def solve(_hull: np.ndarray, _initial: np.ndarray) -> tuple[np.ndarray, bool, float]:
        return candidate, True, 0.0

    def baseline(weights: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
        return weights, np.eye(3), {}

    monkeypatch.setattr("control_lab.fuzzy.tpmt.rno_ino_matrix", baseline)
    monkeypatch.setattr("control_lab.fuzzy.tpmt._solve_cno_slsqp", solve)
    W, T, info = cno_matrix(U, core=np.eye(3), mode=0)

    assert not info["fallback_used"]
    # A folga deve superar o resíduo de arredondamento ao recompor W.
    assert np.min(W) > 1e-12
    np.testing.assert_allclose(W.sum(axis=1), 1.0, atol=1e-11, rtol=0)
    np.testing.assert_array_equal(W, U @ T)
    np.testing.assert_allclose(W @ info["core"], U, atol=1e-11, rtol=0)


def test_t_tsmod_06_resample_basis_1d_linear_and_pchip() -> None:
    g = np.linspace(-math.pi, math.pi, 21)
    U = np.column_stack([np.cos(g), np.sin(g), np.ones_like(g)])
    g_lin, U_lin = resample_basis_1d(g, U, 101, method="linear")
    g_pchip, U_pchip = resample_basis_1d(g, U, 101, method="pchip")
    assert g_lin.shape == (101,)
    assert U_lin.shape == (101, 3)
    assert U_pchip.shape == (101, 3)
    # Nos nós originais (a cada 5 pontos), coincide exatamente
    assert np.allclose(U_lin[::5], U, atol=1e-13)
    assert np.allclose(U_pchip[::5], U, atol=1e-13)
    # PCHIP aproxima melhor curvas suaves cos/sin que interpolação linear
    err_lin = float(np.max(np.abs(U_lin[:, 0] - np.cos(g_lin))))
    err_pchip = float(np.max(np.abs(U_pchip[:, 0] - np.cos(g_pchip))))
    assert err_pchip < err_lin


# ---------------------------------------------------------------------------
# Pipeline Ponta a Ponta `derive_ts_tpmt` + Schema JSON + `evaluate_ts_premise_weights`
# ---------------------------------------------------------------------------


def test_derive_ts_tpmt_end_to_end_schema_and_active_var_detection() -> None:
    """Sistema de 4 estados onde apenas x3 é não-linear (x1, x2, x4 são lineares -> D=1!)."""
    res = derive_ts_tpmt(
        state_bounds={
            "x1": [-2.0, 2.0],
            "x2": [-3.0, 3.0],
            "x3": [-0.6, 0.6],
            "x4": [-2.0, 2.0],
        },
        A_expr=[
            [0, 1, 0, 0],
            [0, -0.1, "-1.5 * sinc_rad(x3)", 0],
            [0, 0, 0, 1],
            [0, 0, "9.81 * sinc_rad(x3)", -0.05],
        ],
        B_expr=[
            [0],
            ["1.0 / (2.0 + 0.5 * sin(x3)^2)"],
            [0],
            ["cos(x3) / (2.0 + 0.5 * sin(x3)^2)"],
        ],
        C_expr=[
            [1, 0, 0, 0],
            [0, 0, 1, 0],
        ],
        D_expr=[[0], [0]],
        grid_points=51,
        decomposition="hosvd",
        svd_tol=1e-8,
        hull_type="CNO",
        resample_points=101,
        resample_method="pchip",
    )
    assert res.status == "success", f"Falha inesperada: {res.error}"
    assert res.data is not None

    # Detecção automática: apenas x3 entra nas matrizes A, B, C, D -> D=1!
    assert res.data["active_variables"] == ["x3"]
    assert res.diagnostics["D_active"] == 1

    # Validação estrita contra contracts/schemas/ts_state_space.schema.json
    ts_dict = res.data["ts_state_space"]
    validator = _build_ts_schema_validator()
    validator.validate(ts_dict)

    ms = ts_dict["membership_spec"]
    assert ms["representation_kind"] == "tpmt_interpolated"
    assert ms["premise_variables"] == ["x3"]
    assert len(ms["tpmt_axes"]) == 1
    assert ms["tpmt_axes"][0]["hull_type"] == "CNO"
    assert len(ms["tpmt_axes"][0]["grid"]) == 101

    cert = res.data["fidelity_certificate"]
    assert cert["verification_badge"] == "EXACT_ON_GRID_TPMT"
    assert cert["verification_tier"] == "numeric_verified"
    assert cert["grid_rel_l2_error"] <= 1e-9
    assert cert["val_rel_l2_error"] <= 1e-4
    assert cert["min_weight"] >= -1e-11
    assert cert["max_sum_deviation"] <= 1e-11

    # Avaliação contínua fora da grade via evaluate_ts_premise_weights
    ts_obj = TSStateSpace.from_dict(ts_dict)
    for x3_test in (-0.75, -0.37, 0.0, 0.213, 0.59, 0.9):  # inclui clamping fora de [-0.6, 0.6]
        w_res = evaluate_ts_premise_weights(ts_obj, {"x3": x3_test})
        assert w_res.status == "success", f"Falha em x3={x3_test}: {w_res.error}"
        h = np.asarray(w_res.data["weights"], dtype=np.float64)
        assert float(np.min(h)) >= -1e-12
        assert abs(float(np.sum(h)) - 1.0) <= 1e-12

    # Avaliação passando vetor completo de 4 estados [x1, x2, x3, x4]
    w_vec = evaluate_ts_premise_weights(ts_obj, [0.5, -0.2, 0.25, 0.1])
    assert w_vec.status == "success"
    # Reconstrução de A(0.25) a partir dos pesos avaliados
    h_vec = np.asarray(w_vec.data["weights"], dtype=np.float64)
    A_hat = sum(h_vec[r] * np.asarray(ts_obj.vertices[r]["A"], dtype=np.float64) for r in range(ts_obj.n_vertices))
    expected_sinc = math.sin(0.25) / 0.25
    assert abs(A_hat[1, 2] - (-1.5 * expected_sinc)) < 1e-4
    assert abs(A_hat[3, 2] - (9.81 * expected_sinc)) < 1e-3


def test_derive_ts_tpmt_2d_hooi_reduced_rank_and_generalized_channels() -> None:
    """Testa HOOI com posto reduzido (APPROXIMATE_REDUCED_TPMT), canais generalizados e premissa não medida."""
    res = derive_ts_tpmt(
        state_bounds={"x1": [-1.5, 1.5], "x2": [-1.5, 1.5]},
        A_expr=[
            ["-1.0 - sin(x2)^2", "0.5 * sin(x1)^2 + 0.2 * cos(x1 * x2)"],
            ["0.5 * cos(x1)^2", "-1.0 - cos(x2)^2"],
        ],
        B_expr=[[1.0], ["0.5 + 0.2 * sin(x1)"]],
        generalized_channels={
            "Bw": [["0.1 * cos(x2)"], [0.0]],
            "Cz": [[1.0, 0.0]],
        },
        measured_states={"x1": True, "x2": False},
        grid_points=[17, 17],
        decomposition="hooi",
        ranks=[2, 2],  # truncamento deliberado em função não-separável cos(x1*x2)
        hull_type={"x1": "RNO-INO", "x2": "CNO"},
        n_val_points=512,
    )
    assert res.status == "success", f"Falha: {res.error}"
    ts_dict = res.data["ts_state_space"]
    _build_ts_schema_validator().validate(ts_dict)

    assert ts_dict["kind"] == "ts_partially_observed"
    assert ts_dict["premise_availability"]["mode"] == "partially_observed"
    assert ts_dict["premise_availability"]["unmeasured_premises"] == ["x2"]
    assert "generalized_channels" in ts_dict["provenance"]
    assert res.data["fidelity_certificate"]["verification_badge"] == "APPROXIMATE_REDUCED_TPMT"
    assert res.data["fidelity_certificate"]["verification_tier"] == "approximate"
    assert res.data["hooi"] is not None
    assert len(res.data["hooi"]["error_history"]) >= 2


def test_derive_ts_tpmt_wasm_envelope_guards() -> None:
    # 1. D > 5 bloqueado antes de alocar
    res_d6 = derive_ts_tpmt(
        state_bounds={f"x{i}": [-1.0, 1.0] for i in range(1, 7)},
        A_expr=[["x1 + x2 + x3 + x4 + x5 + x6"]],
        B_expr=[[1.0]],
        grid_points=5,
    )
    assert res_d6.status == "failure"
    assert res_d6.error is not None
    assert res_d6.error.code == "RESOURCE_LIMIT"

    # 2. prod(G_d) > 250_000 bloqueado antes de alocar
    res_nodes = derive_ts_tpmt(
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[["sin(x1) + cos(x2)"]],
        B_expr=[[1.0]],
        grid_points=[600, 600],  # 360_000 > 250_000
    )
    assert res_nodes.status == "failure"
    assert res_nodes.error is not None
    assert res_nodes.error.code == "RESOURCE_LIMIT"

    # 3. total_elements > 10_000_000 bloqueado antes de alocar (prod(G_d) <= 250_000 mas M1*M2 grande)
    n_big = 5
    A_big = [[("sin(x1)" if i == 0 and j == 0 else ("cos(x2)" if i == 1 and j == 1 else 0.0)) for j in range(n_big)] for i in range(n_big)]
    B_big = [[1.0] for _ in range(n_big)]
    # M1 = 5 + 5 = 10, M2 = 5 + 1 = 6 -> 60 elementos/nó; 200_000 * 60 = 12_000_000 > 10_000_000
    res_elems = derive_ts_tpmt(
        state_bounds={f"x{i}": [-1.0, 1.0] for i in range(1, n_big + 1)},
        A_expr=A_big,
        B_expr=B_big,
        grid_points=[500, 400],  # 200_000 <= 250_000, mas 12_000_000 > 10_000_000
    )
    assert res_elems.status == "failure"
    assert res_elems.error is not None
    assert res_elems.error.code == "RESOURCE_LIMIT"

    # 4. N_r > 256 bloqueado
    res_rules = derive_ts_tpmt(
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[["sin(x1) + cos(x2)"]],
        B_expr=[[1.0]],
        grid_points=[20, 20],
        ranks=[17, 17],  # 289 > 256
    )
    assert res_rules.status == "failure"
    assert res_rules.error is not None
    assert res_rules.error.code == "RESOURCE_LIMIT"
