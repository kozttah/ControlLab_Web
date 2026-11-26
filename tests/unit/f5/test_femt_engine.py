"""Testes unitários normativos da Frente F5 — Motor FEMT (WP-TSMOD-02B-F5-FEMT-ENGINE).

Cobre integralmente `T-TSMOD-08` e `T-TSMOD-05`:
- (a) Otimalidade SVD global e erro nodal exato de Eckart–Young–Mirsky;
- (b) Redução estrita de regras N_r^{FEMT} < N_r^{TPMT} em não-linearidades acopladas (2D e 3D);
- (c) Interpolação baricêntrica P1 (`delaunay` em 1D/2D/3D e `kuhn_delaunay` em 1D/2D/3D/4D):
      partição de Ruspini dentro e fora da caixa (clamping), igualdade exata nos nós e convergência O(h^2);
- (d) Todos os fechos convexos (`SN-NN`, `RNO-INO`, `CNO`, `MGK`), incluindo posto global alto N_r >= 7
      sem explosão do Qhull;
- (e) Validação JSON Schema (`ts_state_space.schema.json`), `evaluate_ts_premise_weights`,
      AST gate zero `linalg.inv`/`eval`/`exec` e guardas pré-alocação do envelope Wasm.
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
from control_lab.fuzzy import (
    cno_matrix,
    derive_ts_femt,
    derive_ts_tpmt,
    evaluate_femt_delaunay,
    evaluate_femt_kuhn_delaunay,
    evaluate_ts_premise_weights,
    femt_svd_decompose,
    sn_nn_matrix,
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
# T-TSMOD-08(a): Otimalidade SVD Global & Erro Exato de Eckart–Young–Mirsky
# ---------------------------------------------------------------------------


def test_t_tsmod_08_eckart_young_mirsky_exact_nodal_error() -> None:
    """Erro nodal de Frobenius sob truncamento de posto R iguala exatamente sqrt(sum_{k>R} sigma_k^2)."""
    res = derive_ts_femt(
        state_bounds={"x1": [-1.2, 1.2], "x2": [-1.2, 1.2]},
        A_expr=[
            ["-1.0 + sin(x1 + x2)", "0.4 * cos(x1 * x2)"],
            ["0.3 * exp(-x1^2 - x2^2)", "-2.0 + tanh(x1 - x2)"],
        ],
        B_expr=[["1.0 + 0.2 * sin(x1 - x2)"], ["0.5 * cos(x1 + x2)"]],
        grid_points=[13, 13],
        rank=3,  # truncamento deliberado abaixo do posto completo da matriz de amostras
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=512,
    )
    assert res.status == "success", f"Falha inesperada: {res.error}"
    assert res.data is not None

    sv = np.asarray(res.data["singular_values"], dtype=np.float64)
    assert sv.size >= 5
    expected_frob = math.sqrt(float(np.sum(sv[3:] ** 2)))
    expected_spec = float(sv[3])

    cert = res.data["fidelity_certificate"]
    assert expected_frob > 1e-3  # garante truncamento real não trivial
    assert abs(cert["eckart_young_frobenius_error"] - expected_frob) <= 1e-13
    assert abs(cert["eckart_young_spectral_error"] - expected_spec) <= 1e-13
    assert abs(cert["grid_frobenius_error"] - expected_frob) <= 1e-10 * (1.0 + expected_frob)
    assert cert["verification_badge"] == "APPROXIMATE_REDUCED_FEMT"
    assert cert["verification_tier"] == "approximate"

    # Validação direta da função femt_svd_decompose em matriz sintética
    rng = np.random.default_rng(20261125)
    S_syn = rng.standard_normal((40, 3, 3))
    svd_r = femt_svd_decompose(S_syn, rank=4)
    rec = (svd_r.U_raw @ svd_r.C_raw).reshape(40, 3, 3)
    frob_err = float(np.linalg.norm((S_syn - rec).reshape(40, -1), ord="fro"))
    spec_err = float(np.linalg.norm((S_syn - rec).reshape(40, -1), ord=2))
    assert abs(frob_err - svd_r.eckart_young_frobenius_error) <= 1e-12
    assert abs(spec_err - svd_r.eckart_young_spectral_error) <= 1e-12


# ---------------------------------------------------------------------------
# T-TSMOD-08(b): Redução Estrita de Regras FEMT vs TPMT em Não-Linearidade Acoplada
# ---------------------------------------------------------------------------


def test_t_tsmod_08_strict_rule_reduction_femt_vs_tpmt_coupled_2d() -> None:
    """Em sistema 2D com não-linearidade acoplada sin(x1 + x2) e cos(x1 - x2), N_r^{FEMT} < N_r^{TPMT}."""
    state_bounds = {"x1": [-1.2, 1.2], "x2": [-1.2, 1.2]}
    A_expr = [
        ["-1.0 - 0.5 * sin(x1 + x2)", "0.3 * cos(x1 - x2)"],
        ["0.2 * sin(x1 + x2)", "-2.0 + 0.4 * cos(x1 - x2)"],
    ]
    B_expr = [[1.0], ["0.5 + 0.2 * sin(x1 + x2)"]]

    res_tpmt = derive_ts_tpmt(
        state_bounds=state_bounds,
        A_expr=A_expr,
        B_expr=B_expr,
        grid_points=[21, 21],
        svd_tol=1e-10,
        hull_type="CNO",
        n_val_points=512,
    )
    res_femt = derive_ts_femt(
        state_bounds=state_bounds,
        A_expr=A_expr,
        B_expr=B_expr,
        grid_points=[21, 21],
        svd_tol=1e-10,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=512,
    )
    assert res_tpmt.status == "success", f"TPMT falhou: {res_tpmt.error}"
    assert res_femt.status == "success", f"FEMT falhou: {res_femt.error}"

    nr_tpmt = int(res_tpmt.data["num_rules"])
    nr_femt = int(res_femt.data["num_rules"])

    # Imagem de S(x1, x2) vive no espaço afim gerado por {1, sin(x1+x2), cos(x1-x2)} => R = 3, N_r^{FEMT} = 3!
    # Na TPMT, cada eixo tem posto >= 3 (1, sin, cos) => N_r^{TPMT} >= 9!
    assert nr_femt == 3
    assert nr_tpmt >= 9
    assert nr_femt < nr_tpmt
    assert res_femt.data["fidelity_certificate"]["grid_rel_l2_error"] <= 1e-12


def test_t_tsmod_08_strict_rule_reduction_femt_vs_tpmt_coupled_3d() -> None:
    """Em sistema 3D com termo acoplado sin(x1 + x2 + x3), FEMT requer apenas 2 regras vs 27 da TPMT!"""
    state_bounds = {"x1": [-0.8, 0.8], "x2": [-0.8, 0.8], "x3": [-0.8, 0.8]}
    A_expr = [
        ["-1.0 - 0.5 * sin(x1 + x2 + x3)", 1.0, 0.0],
        [0.0, -2.0, 1.0],
        [0.0, 0.0, -3.0],
    ]
    B_expr = [[0.0], [0.0], ["1.0 + 0.3 * sin(x1 + x2 + x3)"]]

    res_tpmt = derive_ts_tpmt(
        state_bounds=state_bounds,
        A_expr=A_expr,
        B_expr=B_expr,
        grid_points=[9, 9, 9],
        svd_tol=1e-8,
        hull_type="RNO-INO",
        n_val_points=256,
    )
    res_femt = derive_ts_femt(
        state_bounds=state_bounds,
        A_expr=A_expr,
        B_expr=B_expr,
        grid_points=[9, 9, 9],
        svd_tol=1e-8,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=256,
    )
    assert res_tpmt.status == "success", f"TPMT falhou: {res_tpmt.error}"
    assert res_femt.status == "success", f"FEMT falhou: {res_femt.error}"

    # Imagem de S é afim em 1 única função escalar sin(x1+x2+x3) => R = 2, N_r^{FEMT} = 2!
    # Na TPMT, sin(x1+x2+x3) tem posto 3 por eixo (1, sin, cos) => N_r^{TPMT} = 3^3 = 27!
    assert res_femt.data["num_rules"] == 2
    assert res_tpmt.data["num_rules"] >= 27
    assert res_femt.data["num_rules"] < res_tpmt.data["num_rules"]
    assert res_femt.data["fidelity_certificate"]["grid_rel_l2_error"] <= 1e-12


# ---------------------------------------------------------------------------
# T-TSMOD-08(c): Interpolação Baricêntrica P1 (Delaunay 1D/2D/3D, Kuhn 1D..4D) e O(h^2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dim", [1, 2, 3, 4])
def test_t_tsmod_08_kuhn_delaunay_properties_1d_to_4d(dim: int) -> None:
    """Kuhn–Freudenthal em 1D..4D: igualdade exata nos nós, Ruspini dentro e fora da caixa (clamping)."""
    rng = np.random.default_rng(100 + dim)
    g_per_axis = 5 if dim <= 3 else 4
    axes_grids = [np.linspace(-1.0 - 0.2 * d, 1.5 + 0.1 * d, g_per_axis) for d in range(dim)]
    mesh = np.meshgrid(*axes_grids, indexing="ij")
    nodes = np.column_stack([m.ravel() for m in mesh])
    n_nodes = nodes.shape[0]
    n_rules = 4

    # Pesos nodais convexos sintéticos (SN e NN exatos)
    raw = rng.uniform(0.05, 1.0, size=(n_nodes, n_rules))
    W = raw / np.sum(raw, axis=1, keepdims=True)

    # 1. Igualdade exata em todos os nós da grade
    H_nodes = evaluate_femt_kuhn_delaunay(nodes, axes_grids, W)
    assert np.allclose(H_nodes, W, atol=1e-14, rtol=1e-14)

    # 2. Pontos interiores aleatórios + pontos fora da caixa (clamping)
    lo = np.array([g[0] for g in axes_grids])
    hi = np.array([g[-1] for g in axes_grids])
    pts_in = lo + rng.random((120, dim)) * (hi - lo)
    pts_out = lo - 0.5 + rng.random((40, dim)) * ((hi - lo) + 1.0)
    pts_all = np.vstack([pts_in, pts_out])

    H_all = evaluate_femt_kuhn_delaunay(pts_all, axes_grids, W)
    assert H_all.shape == (pts_all.shape[0], n_rules)
    assert float(np.min(H_all)) >= -1e-14
    assert float(np.max(np.abs(np.sum(H_all, axis=1) - 1.0))) <= 1e-13

    # 3. Chamada de ponto único coincide com lote
    h_single = evaluate_femt_kuhn_delaunay(pts_in[0], axes_grids, W)
    assert h_single.shape == (n_rules,)
    assert np.allclose(h_single, H_all[0], atol=1e-15)


@pytest.mark.parametrize("dim", [1, 2, 3])
def test_t_tsmod_08_explicit_delaunay_properties_1d_to_3d(dim: int) -> None:
    """Delaunay explícita em 1D/2D/3D: igualdade exata nos nós, Ruspini dentro e fora da caixa."""
    rng = np.random.default_rng(200 + dim)
    g_per_axis = 7 if dim <= 2 else 5
    axes_grids = [np.linspace(-1.0, 1.0, g_per_axis) for _ in range(dim)]
    mesh = np.meshgrid(*axes_grids, indexing="ij")
    nodes = np.column_stack([m.ravel() for m in mesh])
    n_nodes = nodes.shape[0]
    n_rules = 3
    bounds = [[-1.0, 1.0] for _ in range(dim)]

    raw = rng.uniform(0.05, 1.0, size=(n_nodes, n_rules))
    W = raw / np.sum(raw, axis=1, keepdims=True)

    # 1. Igualdade exata em todos os nós
    H_nodes = evaluate_femt_delaunay(nodes, nodes, None, W, bounds=bounds)
    assert np.allclose(H_nodes, W, atol=1e-13, rtol=1e-13)

    # 2. Pontos interiores + fronteira + fora da caixa (clamping)
    pts_in = -1.0 + 2.0 * rng.random((100, dim))
    pts_out = -1.6 + 3.2 * rng.random((40, dim))
    pts_all = np.vstack([pts_in, pts_out])

    H_all = evaluate_femt_delaunay(pts_all, nodes, None, W, bounds=bounds)
    assert H_all.shape == (pts_all.shape[0], n_rules)
    assert float(np.min(H_all)) >= -1e-14
    assert float(np.max(np.abs(np.sum(H_all, axis=1) - 1.0))) <= 1e-13

    # 3. Ponto único
    h0 = evaluate_femt_delaunay(pts_in[0], nodes, None, W, bounds=bounds)
    assert np.allclose(h0, H_all[0], atol=1e-14)


@pytest.mark.parametrize("mesh_kind", ["kuhn_delaunay", "delaunay"])
def test_t_tsmod_08_o_h2_convergence_off_grid(mesh_kind: str) -> None:
    """Ao dobrar a densidade da malha (G -> 2G - 1), o erro P1 fora dos nós cai ~4x (O(h^2))."""
    state_bounds = {"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]}
    A_expr = [
        ["-1.0 + sin(x1 + x2)", "0.5 * cos(x1 - x2)"],
        [0.0, -2.0],
    ]
    B_expr = [[1.0], [0.0]]

    errs: list[float] = []
    for g in (9, 17, 33):
        res = derive_ts_femt(
            state_bounds=state_bounds,
            A_expr=A_expr,
            B_expr=B_expr,
            grid_points=[g, g],
            svd_tol=1e-10,
            hull_type="CNO",
            mesh_kind=mesh_kind,
            n_val_points=1024,
        )
        assert res.status == "success", f"Falha em G={g}, mesh_kind={mesh_kind}: {res.error}"
        errs.append(float(res.data["fidelity_certificate"]["val_rel_l2_error"]))

    # Convergência quadrática O(h^2): razão ~4.0 ao dividir h por 2
    ratio_1 = errs[0] / errs[1]
    ratio_2 = errs[1] / errs[2]
    assert ratio_1 > 3.2, f"Razão O(h^2) esperada ~4, obtido {ratio_1:.2f} (errs={errs})"
    assert ratio_2 > 3.2, f"Razão O(h^2) esperada ~4, obtido {ratio_2:.2f} (errs={errs})"


# ---------------------------------------------------------------------------
# T-TSMOD-05 & T-TSMOD-08(d): Todos os Fechos Convexos + Posto Global Alto (N_r >= 7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hull_type", ["SN-NN", "RNO-INO", "CNO", "MGK"])
def test_t_tsmod_05_femt_all_hull_types(hull_type: str) -> None:
    """Todos os fechos convexos preservam reconstrução nodal exata e soma unitária."""
    res = derive_ts_femt(
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[
            ["-1.0 + sin(x1 + x2)", "0.3 * cos(x1 - x2)"],
            [0.0, "-2.0 + 0.2 * x1 * x2"],
        ],
        B_expr=[[1.0], [0.5]],
        grid_points=[13, 13],
        svd_tol=1e-10,
        hull_type=hull_type,
        mesh_kind="kuhn_delaunay",
        n_val_points=256,
    )
    assert res.status in ("success", "warning"), f"Falha em {hull_type}: {res.error}"
    cert = res.data["fidelity_certificate"]
    assert cert["grid_rel_l2_error"] <= 1e-9
    assert cert["max_sum_deviation"] <= 1e-11
    if hull_type != "MGK":
        assert cert["min_weight"] >= -1e-11


def test_t_tsmod_05_cno_scalable_high_global_rank_ge_7() -> None:
    """Salvaguarda escalável para CNO em posto global N_r >= 7 sem explosão combinatória do Qhull."""
    # Constrói matriz S(x1, x2) de posto global 8 (8 funções linearmente independentes em 3x3)
    res = derive_ts_femt(
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[
            ["-1.0 + 0.3 * x1", "0.2 * x2", "0.2 * x1^2"],
            ["0.2 * x2^2", "-2.0 + 0.3 * x1 * x2", "0.2 * sin(x1 + x2)"],
            ["0.2 * cos(x1 - x2)", "0.15 * exp(0.5 * x1)", -3.0],
        ],
        B_expr=[[1.0], [0.0], [0.5]],
        grid_points=[15, 15],
        svd_tol=1e-10,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=256,
    )
    assert res.status == "success", f"Falha em posto alto CNO: {res.error}"
    assert res.data["num_rules"] >= 7
    h_diag = res.data["hull_diagnostics"]
    assert h_diag["used_directional_prefilter"] is True
    assert h_diag["used_convex_hull"] is False
    assert h_diag["min_weight"] >= -1e-10
    assert h_diag["max_sum_deviation"] <= 1e-10
    assert res.data["fidelity_certificate"]["grid_rel_l2_error"] <= 1e-9

    # Teste direto de cno_matrix sobre matriz sintética com r = 9 e N_g = 300
    rng = np.random.default_rng(999)
    U_raw = rng.standard_normal((300, 8))
    W_sn, _, _ = sn_nn_matrix(U_raw)
    assert W_sn.shape[1] >= 8
    W_cno, T_cno, info_cno = cno_matrix(W_sn)
    assert info_cno["used_directional_prefilter"] is True
    assert info_cno["used_convex_hull"] is False
    assert info_cno["min_weight"] >= -1e-10
    assert info_cno["max_sum_deviation"] <= 1e-10
    assert np.allclose(W_sn @ T_cno, W_cno, atol=1e-10)


# ---------------------------------------------------------------------------
# T-TSMOD-08(e): Schema JSON, ts_bridge, AST Gate Zero inv/eval e Envelope Wasm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mesh_kind", ["kuhn_delaunay", "delaunay"])
def test_t_tsmod_08_schema_validation_and_ts_bridge_evaluation(mesh_kind: str) -> None:
    """Valida TSStateSpace.to_dict() contra ts_state_space.schema.json e evaluate_ts_premise_weights."""
    res = derive_ts_femt(
        state_bounds={
            "x1": [-2.0, 2.0],
            "x2": [-1.0, 1.0],
            "x3": [-0.8, 0.8],
        },
        A_expr=[
            [0.0, 1.0, 0.0],
            ["-2.0 - 0.5 * sin(x2 + x3)", -0.4, "0.3 * cos(x2 - x3)"],
            [0.0, 0.0, -1.5],
        ],
        B_expr=[[0.0], ["1.0 + 0.2 * sin(x2 + x3)"], [1.0]],
        C_expr=[[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
        D_expr=[[0.0], [0.0]],
        generalized_channels={
            "Bw": [[0.0], ["0.1 * cos(x2 - x3)"], [0.0]],
            "Cz": [[1.0, 0.0, 0.0]],
        },
        measured_states={"x1": True, "x2": True, "x3": True},
        grid_points=[17, 17],
        svd_tol=1e-10,
        hull_type="CNO",
        mesh_kind=mesh_kind,
        n_val_points=512,
    )
    assert res.status == "success", f"Falha: {res.error}"
    assert res.data is not None
    # x1 entra apenas linearmente -> apenas x2 e x3 são ativos!
    assert res.data["active_variables"] == ["x2", "x3"]
    assert res.diagnostics["D_active"] == 2

    ts_dict = res.data["ts_state_space"]
    _build_ts_schema_validator().validate(ts_dict)

    ms = ts_dict["membership_spec"]
    assert ms["representation_kind"] == "femt_simplicial"
    assert ms["premise_variables"] == ["x2", "x3"]
    fm = ms["femt_mesh"]
    assert fm["mesh_kind"] == mesh_kind
    if mesh_kind == "delaunay":
        assert fm["nodes"] is not None
        assert fm["simplices"] is not None
    else:
        assert fm["simplices"] is None
        assert "nodes" not in fm

    assert "generalized_channels" in ts_dict["provenance"]
    assert ts_dict["provenance"]["ts_derivation"]["method"] == "femt"

    ts_obj = TSStateSpace.from_dict(ts_dict)

    # 1. Avaliação via dict (incluindo clamping fora da caixa)
    for pt_dict in ({"x2": 0.25, "x3": -0.35}, {"x2": -2.5, "x3": 2.0}):
        w_res = evaluate_ts_premise_weights(ts_obj, pt_dict)
        assert w_res.status == "success", f"Falha em {pt_dict}: {w_res.error}"
        h = np.asarray(w_res.data["weights"], dtype=np.float64)
        assert h.size == ts_obj.n_vertices
        assert float(np.min(h)) >= -1e-12
        assert abs(float(np.sum(h)) - 1.0) <= 1e-12

    # 2. Avaliação via vetor de premissas ativas [x2, x3]
    w_act = evaluate_ts_premise_weights(ts_obj, [0.25, -0.35])
    assert w_act.status == "success"

    # 3. Avaliação via vetor completo de estados [x1, x2, x3] e reconstrução de A(x2, x3)
    w_full = evaluate_ts_premise_weights(ts_obj, [1.2, 0.25, -0.35])
    assert w_full.status == "success"
    h_full = np.asarray(w_full.data["weights"], dtype=np.float64)
    assert np.allclose(h_full, np.asarray(w_act.data["weights"], dtype=np.float64), atol=1e-14)
    A_hat = sum(h_full[r] * np.asarray(ts_obj.vertices[r]["A"], dtype=np.float64) for r in range(ts_obj.n_vertices))
    expected_a10 = -2.0 - 0.5 * math.sin(0.25 - 0.35)
    expected_a12 = 0.3 * math.cos(0.25 + 0.35)
    assert abs(A_hat[1, 0] - expected_a10) < 2e-3
    assert abs(A_hat[1, 2] - expected_a12) < 2e-3


def test_t_tsmod_08_ast_gate_zero_linalg_inv_and_eval() -> None:
    """Inspeção AST estática garantindo ZERO eval/exec/compile/getattr e ZERO .inv() em femt/tpmt/ts_bridge."""
    forbidden_funcs = {"eval", "exec", "compile", "getattr"}
    for fname in ("femt.py", "tpmt.py", "ts_bridge.py"):
        fpath = REPO_ROOT / "control_lab" / "fuzzy" / fname
        tree = ast.parse(fpath.read_text(encoding="utf-8"), filename=str(fpath))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in forbidden_funcs:
                    pytest.fail(f"Chamada proibida '{node.func.id}' encontrada em {fname}:{node.lineno}")
                if isinstance(node.func, ast.Attribute) and node.func.attr == "inv":
                    pytest.fail(f"Chamada proibida '.inv()' encontrada em {fname}:{node.lineno}")


def test_t_tsmod_08_wasm_envelope_guards() -> None:
    """Guardas pré-alocação de envelope Wasm (D <= 5, N_g <= 250_000, N_g*M <= 10_000_000, Delaunay D <= 3)."""
    # 1. D > 5 bloqueado
    res_d6 = derive_ts_femt(
        state_bounds={f"x{i}": [-1.0, 1.0] for i in range(1, 7)},
        A_expr=[["x1 + x2 + x3 + x4 + x5 + x6"]],
        B_expr=[[1.0]],
        grid_points=3,
    )
    assert res_d6.status == "failure"
    assert res_d6.error is not None and res_d6.error.code == "RESOURCE_LIMIT"

    # 2. Delaunay explícito com D > 3 bloqueado recomendando kuhn_delaunay
    res_del_d4 = derive_ts_femt(
        state_bounds={f"x{i}": [-1.0, 1.0] for i in range(1, 5)},
        A_expr=[["x1 + x2 + x3 + x4"]],
        B_expr=[[1.0]],
        grid_points=3,
        mesh_kind="delaunay",
    )
    assert res_del_d4.status == "failure"
    assert res_del_d4.error is not None and res_del_d4.error.code == "RESOURCE_LIMIT"
    assert "kuhn_delaunay" in res_del_d4.error.message

    # 3. Delaunay explícito com N_g > 50_000 bloqueado recomendando kuhn_delaunay
    res_del_nodes = derive_ts_femt(
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[["sin(x1 + x2)"]],
        B_expr=[[1.0]],
        grid_points=[250, 250],  # 62_500 > 50_000
        mesh_kind="delaunay",
    )
    assert res_del_nodes.status == "failure"
    assert res_del_nodes.error is not None and res_del_nodes.error.code == "RESOURCE_LIMIT"
    assert "kuhn_delaunay" in res_del_nodes.error.message

    # 4. N_g > 250_000 bloqueado antes de alocar
    res_nodes = derive_ts_femt(
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[["sin(x1 + x2)"]],
        B_expr=[[1.0]],
        grid_points=[600, 600],
        mesh_kind="kuhn_delaunay",
    )
    assert res_nodes.status == "failure"
    assert res_nodes.error is not None and res_nodes.error.code == "RESOURCE_LIMIT"

    # 5. N_g * M > 10_000_000 bloqueado antes de alocar
    n_big = 5
    A_big = [
        [("sin(x1)" if i == 0 and j == 0 else ("cos(x2)" if i == 1 and j == 1 else 0.0)) for j in range(n_big)]
        for i in range(n_big)
    ]
    B_big = [[1.0] for _ in range(n_big)]
    res_elems = derive_ts_femt(
        state_bounds={f"x{i}": [-1.0, 1.0] for i in range(1, n_big + 1)},
        A_expr=A_big,
        B_expr=B_big,
        grid_points=[500, 400],  # 200_000 * 60 = 12_000_000 > 10_000_000
        mesh_kind="kuhn_delaunay",
    )
    assert res_elems.status == "failure"
    assert res_elems.error is not None and res_elems.error.code == "RESOURCE_LIMIT"


# ---------------------------------------------------------------------------
# T-TSMOD-08 (v1.2.0): FEMT Centrada no Subespaço Variante & Remontagem Exata
# ---------------------------------------------------------------------------


def _pendulum_16_spec() -> dict[str, object]:
    """Especificação canônica do pêndulo invertido de 4 estados (`pendulum_16`, M=30, M_var=6, M_const=24)."""
    z1 = "(1 / (1.0 + 0.2 * sin(x3)^2))"
    z2 = "cos(x3)"
    z3 = "sinc_rad(x3)"
    z4 = "(x4 * sin(x3))"
    return {
        "state_bounds": {
            "x1": [-2.0, 2.0],
            "x2": [-3.0, 3.0],
            "x3": [-0.6, 0.6],
            "x4": [-2.0, 2.0],
        },
        "A_expr": [
            ["0", "1", "0", "0"],
            ["0", "0", f"-1.962 * {z1} * {z2} * {z3}", f"0.1 * {z1} * {z4}"],
            ["0", "0", "0", "1"],
            ["0", "0", f"23.544 * {z1} * {z3}", f"-0.2 * {z1} * {z2} * {z4}"],
        ],
        "B_expr": [["0"], [z1], ["0"], [f"-2.0 * {z1} * {z2}"]],
        "C_expr": [["1", "0", "0", "0"], ["0", "0", "1", "0"]],
        "D_expr": [["0"], ["0"]],
    }


@pytest.mark.parametrize("hull_type", ["SN-NN", "RNO-INO", "CNO", "MGK"])
def test_t_tsmod_08_v12_pendulum_16_bitwise_constant_preservation_all_hulls(hull_type: str) -> None:
    """Preservação bit-a-bit exata de todas as 24 entradas constantes no pêndulo invertido de 4 estados."""
    spec = _pendulum_16_spec()
    res = derive_ts_femt(
        state_bounds=spec["state_bounds"],  # type: ignore[arg-type]
        A_expr=spec["A_expr"],  # type: ignore[arg-type]
        B_expr=spec["B_expr"],  # type: ignore[arg-type]
        C_expr=spec["C_expr"],  # type: ignore[arg-type]
        D_expr=spec["D_expr"],  # type: ignore[arg-type]
        grid_points=[15, 15],
        svd_tol=1e-6,
        hull_type=hull_type,
        mesh_kind="kuhn_delaunay",
        n_val_points=256,
    )
    assert res.status in ("success", "warning"), f"Falha em {hull_type}: {res.error}"
    assert res.data is not None

    # Redução de dimensão na SVD: apenas 6 de 30 entradas variam
    assert res.data["n_varying_entries"] == 6
    assert res.data["n_constant_entries"] == 24
    assert len(res.data["singular_values"]) == 6
    assert res.data["hull_diagnostics"]["rank_augmented"] is False

    prov = res.data["ts_state_space"]["provenance"]["ts_derivation"]
    assert prov["n_varying_entries"] == 6
    assert prov["n_constant_entries"] == 24
    assert prov["centered_mean_augmented"] is True

    ts_obj = TSStateSpace.from_dict(res.data["ts_state_space"])
    expected_C = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]], dtype=np.float64)
    expected_D = np.zeros((2, 1), dtype=np.float64)
    const_A_zeros = [
        (0, 0), (0, 2), (0, 3),
        (1, 0), (1, 1),
        (2, 0), (2, 1), (2, 2),
        (3, 0), (3, 1),
    ]

    for r_idx, v in enumerate(ts_obj.vertices):
        A_r = np.asarray(v["A"], dtype=np.float64)
        B_r = np.asarray(v["B"], dtype=np.float64)
        C_r = np.asarray(v["C"], dtype=np.float64)
        D_r = np.asarray(v["D"], dtype=np.float64)

        # Integradores e zeros estruturais bit-a-bit idênticos
        assert A_r[0, 1] == 1.0, f"Regra {r_idx}: A[0,1]={A_r[0, 1]} != 1.0 em {hull_type}"
        assert A_r[2, 3] == 1.0, f"Regra {r_idx}: A[2,3]={A_r[2, 3]} != 1.0 em {hull_type}"
        for i, j in const_A_zeros:
            assert A_r[i, j] == 0.0, f"Regra {r_idx}: A[{i},{j}]={A_r[i, j]} != 0.0 em {hull_type}"
        assert B_r[0, 0] == 0.0
        assert B_r[2, 0] == 0.0
        assert np.array_equal(C_r, expected_C)
        assert np.array_equal(D_r, expected_D)


def test_t_tsmod_08_v12_pendulum_16_cno_well_conditioned_physical_vertices() -> None:
    """Pêndulo invertido 15x15 sob CNO: sem coluna extra, sem fallback, cond(W) < 10 e vértices físicos."""
    spec = _pendulum_16_spec()
    res = derive_ts_femt(
        state_bounds=spec["state_bounds"],  # type: ignore[arg-type]
        A_expr=spec["A_expr"],  # type: ignore[arg-type]
        B_expr=spec["B_expr"],  # type: ignore[arg-type]
        C_expr=spec["C_expr"],  # type: ignore[arg-type]
        D_expr=spec["D_expr"],  # type: ignore[arg-type]
        grid_points=[15, 15],
        svd_tol=1e-6,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=512,
    )
    assert res.status == "success", f"Falha: {res.error}"
    assert res.data is not None

    hd = res.data["hull_diagnostics"]
    assert hd["rank_augmented"] is False
    assert hd["fallback_used"] is False
    W_cno = np.asarray(res.data["W_nodal"], dtype=np.float64)
    cond_W = float(np.linalg.cond(W_cno))
    assert cond_W < 10.0, f"cond(W_cno)={cond_W:.3f} >= 10"
    assert abs(hd["cond_W"] - cond_W) <= 1e-12

    ts_obj = TSStateSpace.from_dict(res.data["ts_state_space"])
    for r_idx, v in enumerate(ts_obj.vertices):
        A_r = np.asarray(v["A"], dtype=np.float64)
        assert 18.0 <= A_r[3, 2] <= 26.0, f"Regra {r_idx}: A[3,2]={A_r[3, 2]} fora de [18, 26]"
        assert -3.0 <= A_r[1, 2] <= -0.5, f"Regra {r_idx}: A[1,2]={A_r[1, 2]} fora de [-3, -0.5]"


@pytest.mark.parametrize("trunc_rank", [1, 2, 3])
def test_t_tsmod_08_v12_rank_augmented_false_under_aggressive_truncation(trunc_rank: int) -> None:
    """Garantia estrutural de rank_augmented == False mesmo sob truncamento agressivo."""
    spec = _pendulum_16_spec()
    res = derive_ts_femt(
        state_bounds=spec["state_bounds"],  # type: ignore[arg-type]
        A_expr=spec["A_expr"],  # type: ignore[arg-type]
        B_expr=spec["B_expr"],  # type: ignore[arg-type]
        C_expr=spec["C_expr"],  # type: ignore[arg-type]
        D_expr=spec["D_expr"],  # type: ignore[arg-type]
        grid_points=[11, 11],
        rank=trunc_rank,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=128,
    )
    assert res.status == "success", f"Falha em rank={trunc_rank}: {res.error}"
    assert res.data is not None
    assert res.data["svd_rank"] == trunc_rank
    assert res.data["num_rules"] == trunc_rank + 1
    assert res.data["hull_diagnostics"]["rank_augmented"] is False
    assert res.data["hull_diagnostics"]["rank_before"] == trunc_rank + 1
    assert res.data["hull_diagnostics"]["rank_after"] == trunc_rank + 1


def test_t_tsmod_08_v12_degenerate_lti_m_var_zero() -> None:
    """Caso degenerado puramente LTI (M_var == 0) gera exatamente 1 regra exata sem erro."""
    # 1. Teste direto em femt_svd_decompose
    S_const = np.broadcast_to(np.array([[-1.0, 2.0], [0.0, -3.0]], dtype=np.float64), (25, 2, 2)).copy()
    svd_lti = femt_svd_decompose(S_const)
    assert svd_lti.rank == 0
    assert svd_lti.U_raw.shape == (25, 1)
    assert svd_lti.C_raw.shape == (1, 4)
    assert svd_lti.singular_values.size == 0
    assert svd_lti.eckart_young_frobenius_error == 0.0
    assert svd_lti.eckart_young_spectral_error == 0.0
    assert np.allclose(svd_lti.U_raw.T @ svd_lti.U_raw, np.eye(1), atol=1e-14)
    assert np.allclose((svd_lti.U_raw @ svd_lti.C_raw).reshape(25, 2, 2), S_const, atol=1e-14)

    # Aceita rank=0 e rank=1; rejeita rank=2
    assert femt_svd_decompose(S_const, rank=0).rank == 0
    assert femt_svd_decompose(S_const, rank=1).rank == 0
    with pytest.raises(Exception):
        femt_svd_decompose(S_const, rank=2)

    # 2. Pipeline completo derive_ts_femt quando expressão é numericamente constante no grid
    res = derive_ts_femt(
        state_bounds={"x1": [-1.0, 1.0], "x2": [-1.0, 1.0]},
        A_expr=[["-1.0 + 0.0 * x1", "sin(x1)^2 + cos(x1)^2"], [0.0, -2.5]],
        B_expr=[[0.0], [1.0]],
        grid_points=9,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=64,
    )
    assert res.status == "success", f"Falha em M_var == 0: {res.error}"
    assert res.data is not None
    assert res.data["num_rules"] == 1
    assert res.data["svd_rank"] == 0
    assert res.data["n_varying_entries"] == 0
    hd = res.data["hull_diagnostics"]
    assert hd["rank_augmented"] is False
    assert hd["rank_before"] == 1
    assert hd["rank_after"] == 1
    assert hd["cond_T"] == 1.0
    assert hd["cond_W"] == 1.0
    assert hd["fallback_used"] is False
    assert np.allclose(np.asarray(res.data["W_nodal"]), np.ones((9, 1)), atol=1e-15)
    assert res.data["fidelity_certificate"]["grid_rel_l2_error"] <= 1e-14
    assert res.data["fidelity_certificate"]["val_rel_l2_error"] <= 1e-14


def test_t_tsmod_08_v12_centered_eckart_young_and_orthonormality_with_large_constants() -> None:
    """Erro centrado de Eckart–Young–Mirsky e ortonormalidade de U_raw mesmo com entradas constantes enormes."""
    rng = np.random.default_rng(20261126)
    n_nodes = 60
    # 10 colunas constantes grandes (~1e4) + 5 colunas variantes pequenas (~1e-1)
    X_const = np.broadcast_to(rng.uniform(-1e4, 1e4, size=(1, 10)), (n_nodes, 10)).copy()
    X_var = 0.1 * rng.standard_normal((n_nodes, 5))
    X_full = np.hstack([X_const, X_var])

    svd_res = femt_svd_decompose(X_full, rank=2)
    assert svd_res.rank == 2
    assert svd_res.singular_values.size == 5  # SVD somente no subespaço variante (M_var = 5 < M = 15)
    assert svd_res.U_raw.shape == (n_nodes, 3)
    assert svd_res.C_raw.shape == (3, 15)

    # Ortonormalidade de U_raw e ortogonalidade de U_delta à média
    assert np.allclose(svd_res.U_raw.T @ svd_res.U_raw, np.eye(3), atol=1e-13)
    assert np.max(np.abs(np.mean(svd_res.U_raw[:, 1:], axis=0))) <= 1e-14

    # Erro exato de Eckart–Young–Mirsky centrado
    rec = svd_res.U_raw @ svd_res.C_raw
    expected_frob = math.sqrt(float(np.sum(svd_res.singular_values[2:] ** 2)))
    expected_spec = float(svd_res.singular_values[2])
    assert abs(svd_res.eckart_young_frobenius_error - expected_frob) <= 1e-14
    assert abs(svd_res.eckart_young_spectral_error - expected_spec) <= 1e-14
    assert abs(float(np.linalg.norm(X_full - rec, ord="fro")) - expected_frob) <= 1e-11
    assert abs(float(np.linalg.norm(X_full - rec, ord=2)) - expected_spec) <= 1e-11


def test_t_tsmod_08_v12_export_ts_derivation_script_python_and_matlab_pendulum_16(
    tmp_path: pathlib.Path,
) -> None:
    """Compatibilidade integral da FEMT v1.2.0 com export_ts_derivation_script (Python executável e MATLAB)."""
    import subprocess
    import sys

    from control_lab.io.ts_derivation import export_ts_derivation_script

    spec = _pendulum_16_spec()
    res = derive_ts_femt(
        state_bounds=spec["state_bounds"],  # type: ignore[arg-type]
        A_expr=spec["A_expr"],  # type: ignore[arg-type]
        B_expr=spec["B_expr"],  # type: ignore[arg-type]
        C_expr=spec["C_expr"],  # type: ignore[arg-type]
        D_expr=spec["D_expr"],  # type: ignore[arg-type]
        grid_points=[9, 9],
        svd_tol=1e-6,
        hull_type="CNO",
        mesh_kind="kuhn_delaunay",
        n_val_points=128,
    )
    assert res.status == "success", f"Falha: {res.error}"
    ts_obj = TSStateSpace.from_dict(res.data["ts_state_space"])

    # Exportação Python standalone e execução verificando reprodução exata dos vértices
    py_script = export_ts_derivation_script(ts_obj, "python")
    assert "from control_lab" not in py_script
    py_path = tmp_path / "derive_pendulum_femt.py"
    py_path.write_text(py_script, encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(py_path)], cwd=tmp_path, check=True)
    with np.load(tmp_path / "ts_vertices.npz", allow_pickle=False) as out:
        for key in ("A", "B", "C", "D"):
            np.testing.assert_allclose(out[key], [v[key] for v in ts_obj.vertices], atol=2e-9, rtol=0.0)

    # Exportação MATLAB
    m_script = export_ts_derivation_script(ts_obj, "matlab")
    assert "ts_vertices.mat" in m_script
    assert "function " in m_script

