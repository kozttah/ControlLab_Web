"""Testes unitários F5 para ANFIS heterogêneo/multi-saída, evaluate_surface multi-saída e round-trip FML N×M."""

from __future__ import annotations

import numpy as np
import pytest

from control_lab.core.models import FuzzySystem
from control_lab.fuzzy import (
    evaluate,
    evaluate_surface,
    export_fml,
    fit_anfis,
    import_fml,
)


# ---------------------------------------------------------------------------
# 1. ANFIS heterogêneo (n_mfs por entrada + mf_type por entrada)
# ---------------------------------------------------------------------------


def test_fit_anfis_heterogeneous_mfs_and_mixed_mf_types() -> None:
    """fit_anfis suporta n_mfs=[2, 3] e mf_type=['gaussian', 'bell'] com aliases."""
    rng = np.random.default_rng(101)
    X_tr = rng.uniform(-1.5, 1.5, size=(120, 2))
    y_tr = np.sin(X_tr[:, 0]) + 0.5 * np.square(X_tr[:, 1]) - 0.3 * X_tr[:, 0] * X_tr[:, 1]

    X_va = rng.uniform(-1.4, 1.4, size=(40, 2))
    y_va = np.sin(X_va[:, 0]) + 0.5 * np.square(X_va[:, 1]) - 0.3 * X_va[:, 0] * X_va[:, 1]

    res = fit_anfis(
        X_tr,
        y_tr,
        X_val=X_va,
        y_val=y_va,
        n_mfs=[2, 3],
        mf_type=["gaussmf", "gbellmf"],
        max_epochs=25,
        learning_rate=0.02,
        input_names=["u1", "u2"],
        output_name="z",
        seed=101,
    )
    assert res.status in ("success", "warning")
    assert res.data is not None
    assert res.data["mfs_per_input"] == [2, 3]
    assert res.data["mf_types_per_input"] == ["gaussian", "bell"]
    assert res.data["output_names"] == ["z"]
    assert res.data["n_outputs"] == 1
    assert res.diagnostics["n_rules"] == 6
    assert res.data["fit_val_pct"] > 90.0
    assert res.data["rmse_val"] < 0.15

    # Backward-compatible 1D y_pred quando M_out == 1
    assert isinstance(res.data["y_pred_train"], list)
    assert isinstance(res.data["y_pred_train"][0], float)
    assert len(res.data["y_pred_train"]) == X_tr.shape[0]
    assert isinstance(res.data["y_pred_val"], list)
    assert isinstance(res.data["y_pred_val"][0], float)
    assert len(res.data["y_pred_val"]) == X_va.shape[0]

    fs = FuzzySystem.from_dict(res.data["fuzzy_system"])
    assert fs.inference_type == "ts"
    assert fs.is_dynamic_model is False
    assert len(fs.input_variables) == 2
    assert len(fs.input_variables[0]["terms"]) == 2
    assert len(fs.input_variables[1]["terms"]) == 3
    assert all(t["mf"] == "gaussian" for t in fs.input_variables[0]["terms"])
    assert all(t["mf"] == "bell" for t in fs.input_variables[1]["terms"])
    assert len(fs.rules) == 6

    # Avaliação via FuzzySystem deve coincidir com y_pred_val
    for idx in range(10):
        ev = evaluate(fs, X_va[idx])
        assert ev.status == "success" and ev.data is not None
        assert ev.data["output"] == pytest.approx(res.data["y_pred_val"][idx], abs=1e-10)


def test_fit_anfis_scalar_2d_column_backward_compatible() -> None:
    """y com shape (N, 1) mantém M_out == 1 e y_pred 1D compatível com legado."""
    x = np.linspace(-2.0, 2.0, 50)
    y_col = (1.5 * x - 0.3 * np.square(x) + 0.2).reshape(-1, 1)

    res = fit_anfis(x, y_col, n_mfs=3, mf_type="bell", max_epochs=15, seed=11)
    assert res.status in ("success", "warning")
    assert res.data is not None
    assert res.data["n_outputs"] == 1
    assert res.data["output_names"] == ["y"]
    assert isinstance(res.data["y_pred_train"][0], float)
    assert isinstance(res.data["y_pred_val"][0], float)
    assert res.data["fit_val_pct"] > 95.0
    assert res.data["rmse_val"] == pytest.approx(res.data["metrics"]["val_rmse"])
    assert res.data["history"]["best_epoch"] == res.data["training_history"]["best_epoch"]


# ---------------------------------------------------------------------------
# 2. ANFIS multi-saída (N × 2 e N × 3)
# ---------------------------------------------------------------------------


def test_fit_anfis_multi_output_2d_and_fuzzy_system_equivalence() -> None:
    """fit_anfis com Y (N × 2), n_mfs heterogêneo e mf_type misto produz FuzzySystem coerente."""
    rng = np.random.default_rng(202)
    X_tr = rng.uniform(-1.5, 1.5, size=(160, 2))
    Y_tr = np.column_stack(
        [
            np.sin(X_tr[:, 0]) + 0.4 * X_tr[:, 1],
            0.6 * np.square(X_tr[:, 0]) - np.cos(0.8 * X_tr[:, 1]) + 0.5,
        ]
    )
    X_va = rng.uniform(-1.4, 1.4, size=(40, 2))
    Y_va = np.column_stack(
        [
            np.sin(X_va[:, 0]) + 0.4 * X_va[:, 1],
            0.6 * np.square(X_va[:, 0]) - np.cos(0.8 * X_va[:, 1]) + 0.5,
        ]
    )

    res = fit_anfis(
        X_tr,
        Y_tr,
        X_val=X_va,
        y_val=Y_va,
        n_mfs=[3, 2],
        mf_type=["gaussian", "bell"],
        max_epochs=25,
        learning_rate=0.02,
        input_names=["x1", "x2"],
        output_names=["torque", "flux"],
        seed=202,
    )
    assert res.status in ("success", "warning")
    assert res.data is not None
    assert res.data["n_outputs"] == 2
    assert res.data["output_names"] == ["torque", "flux"]
    assert res.data["mfs_per_input"] == [3, 2]
    assert res.data["mf_types_per_input"] == ["gaussian", "bell"]

    # Métricas por saída
    for onm in ("torque", "flux"):
        assert res.data["fit_val_pct_per_output"][onm] > 90.0
        assert res.data["rmse_val_per_output"][onm] < 0.15
        assert res.data["fit_train_pct_per_output"][onm] > 90.0
        assert res.data["rmse_train_per_output"][onm] < 0.15

    # y_pred_val é 2D (N_va, 2)
    y_pred_va = res.data["y_pred_val"]
    assert len(y_pred_va) == X_va.shape[0]
    assert isinstance(y_pred_va[0], list) and len(y_pred_va[0]) == 2

    # FuzzySystem multi-saída
    fs = FuzzySystem.from_dict(res.data["fuzzy_system"])
    assert fs.inference_type == "ts"
    assert fs.is_dynamic_model is False
    assert [v["name"] for v in fs.output_variables] == ["torque", "flux"]
    assert len(fs.rules) == 6
    for rule in fs.rules:
        assert set(rule["consequents"].keys()) == {"torque", "flux"}

    # Avaliação via evaluate coincide com y_pred_val para todas as saídas
    for idx in range(12):
        ev = evaluate(fs, X_va[idx])
        assert ev.status == "success" and ev.data is not None
        assert ev.data["outputs"]["torque"] == pytest.approx(y_pred_va[idx][0], abs=1e-10)
        assert ev.data["outputs"]["flux"] == pytest.approx(y_pred_va[idx][1], abs=1e-10)


def test_fit_anfis_multi_output_3_outputs_default_names() -> None:
    """fit_anfis com Y (N × 3) sem output_names gera ['y1', 'y2', 'y3'] e alta precisão."""
    rng = np.random.default_rng(303)
    X = rng.uniform(-1.0, 1.0, size=(150, 2))
    Y = np.column_stack(
        [
            2.0 * X[:, 0] - 0.5 * X[:, 1] + 0.3,
            np.square(X[:, 0]) + 0.4 * X[:, 1],
            -X[:, 0] + np.sin(X[:, 1]),
        ]
    )

    res = fit_anfis(X, Y, n_mfs=[2, 2], mf_type="gaussian", max_epochs=20, seed=303)
    assert res.status in ("success", "warning")
    assert res.data is not None
    assert res.data["n_outputs"] == 3
    assert res.data["output_names"] == ["y1", "y2", "y3"]
    assert len(res.data["y_pred_val"][0]) == 3
    for onm in ("y1", "y2", "y3"):
        assert res.data["fit_val_pct_per_output"][onm] > 95.0


# ---------------------------------------------------------------------------
# 3. Erros de validação em fit_anfis
# ---------------------------------------------------------------------------


def test_fit_anfis_validation_errors() -> None:
    """Valida erros tipados para output_names, mf_type, explosão de regras (>512) e ndim de y."""
    rng = np.random.default_rng(404)
    X2 = rng.uniform(-1.0, 1.0, size=(20, 2))
    Y2 = rng.uniform(-1.0, 1.0, size=(20, 2))

    # output_names com comprimento incompatível
    r1 = fit_anfis(X2, Y2, output_names=["only_one"])
    assert r1.status == "failure" and r1.error is not None
    assert r1.error.code == "DIMENSION_MISMATCH"

    # output_names duplicados
    r2 = fit_anfis(X2, Y2, output_names=["dup", "dup"])
    assert r2.status == "failure" and r2.error is not None
    assert r2.error.code == "VALIDATION_ERROR"

    # mf_type com comprimento incompatível
    r3 = fit_anfis(X2, Y2, mf_type=["gaussian", "bell", "gaussian"])
    assert r3.status == "failure" and r3.error is not None
    assert r3.error.code == "DIMENSION_MISMATCH"

    # mf_type com nome inválido
    r4 = fit_anfis(X2, Y2, mf_type=["gaussian", "triangular"])
    assert r4.status == "failure" and r4.error is not None
    assert r4.error.code == "VALIDATION_ERROR"

    # Explosão de regras: prod([8, 8, 9]) = 576 > 512
    X3 = rng.uniform(-1.0, 1.0, size=(20, 3))
    y3 = rng.uniform(-1.0, 1.0, size=(20,))
    r5 = fit_anfis(X3, y3, n_mfs=[8, 8, 9])
    assert r5.status == "failure" and r5.error is not None
    assert r5.error.code == "VALIDATION_ERROR"
    assert "512" in r5.error.message

    # y com ndim inválido (3D)
    y_3d = rng.uniform(-1.0, 1.0, size=(20, 2, 1))
    r6 = fit_anfis(X2, y_3d)
    assert r6.status == "failure" and r6.error is not None
    assert r6.error.code == "DIMENSION_MISMATCH"

    # y_val com número de saídas incompatível
    r7 = fit_anfis(X2, Y2, X_val=X2[:5], y_val=y3[:5])
    assert r7.status == "failure" and r7.error is not None
    assert r7.error.code == "DIMENSION_MISMATCH"

    # bool dentro de n_mfs
    r8 = fit_anfis(X2, y3, n_mfs=[True, 2])
    assert r8.status == "failure" and r8.error is not None
    assert r8.error.code == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 4. evaluate + evaluate_surface em sistemas 3-input × 2-output (Mamdani e TS)
# ---------------------------------------------------------------------------


def _build_3in_2out_mamdani() -> FuzzySystem:
    return FuzzySystem(
        inference_type="mamdani",
        input_variables=[
            {
                "name": "e",
                "universe": [-2.0, 2.0],
                "terms": [
                    {"name": "Neg", "mf": "triangular", "params": [-2.0, -2.0, 0.5]},
                    {"name": "Pos", "mf": "triangular", "params": [-0.5, 2.0, 2.0]},
                ],
            },
            {
                "name": "de",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "Slow", "mf": "gaussian", "params": [-0.5, 0.6]},
                    {"name": "Mid", "mf": "gaussian", "params": [0.0, 0.5]},
                    {"name": "Fast", "mf": "gaussian", "params": [0.5, 0.6]},
                ],
            },
            {
                "name": "load",
                "universe": [0.0, 10.0],
                "terms": [
                    {"name": "Light", "mf": "trapezoidal", "params": [0.0, 0.0, 3.0, 6.0]},
                    {"name": "Heavy", "mf": "bell", "params": [3.0, 2.0, 8.0]},
                ],
            },
        ],
        output_variables=[
            {
                "name": "u_force",
                "universe": [-10.0, 10.0],
                "terms": [
                    {"name": "Low", "mf": "triangular", "params": [-10.0, -5.0, 0.0]},
                    {"name": "High", "mf": "triangular", "params": [0.0, 5.0, 10.0]},
                ],
            },
            {
                "name": "u_damp",
                "universe": [0.0, 5.0],
                "terms": [
                    {"name": "Soft", "mf": "triangular", "params": [0.0, 1.0, 2.5]},
                    {"name": "Stiff", "mf": "triangular", "params": [2.0, 4.0, 5.0]},
                ],
            },
        ],
        rules=[
            {
                "name": "R1",
                "antecedents": {"e": "Neg", "de": "Slow", "load": "Light"},
                "consequents": {"u_force": "Low", "u_damp": "Soft"},
            },
            {
                "name": "R2",
                "antecedents": {"e": "Neg", "de": "Mid", "load": "Heavy"},
                "consequents": {"u_force": "Low", "u_damp": "Stiff"},
            },
            {
                "name": "R3",
                "antecedents": {"e": "Pos", "de": "Fast", "load": "Heavy"},
                "consequents": {"u_force": "High", "u_damp": "Stiff"},
            },
            {
                "name": "R4",
                "antecedents": {"e": "Pos", "de": "Slow", "load": "Light"},
                "consequents": {"u_force": "High", "u_damp": "Soft"},
            },
        ],
        operators={"and": "min", "or": "max", "implication": "min", "aggregation": "max", "defuzzification": "centroid"},
    )


def _build_3in_2out_ts() -> FuzzySystem:
    return FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "x1",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "L", "mf": "gaussian", "params": [-0.8, 0.7]},
                    {"name": "H", "mf": "gaussian", "params": [0.8, 0.7]},
                ],
            },
            {
                "name": "x2",
                "universe": [0.0, 4.0],
                "terms": [
                    {"name": "A", "mf": "bell", "params": [1.2, 2.0, 0.5]},
                    {"name": "B", "mf": "bell", "params": [1.2, 2.0, 2.0]},
                    {"name": "C", "mf": "bell", "params": [1.2, 2.0, 3.5]},
                ],
            },
            {
                "name": "x3",
                "universe": [-2.0, 2.0],
                "terms": [
                    {"name": "N", "mf": "triangular", "params": [-2.0, -2.0, 2.0]},
                    {"name": "P", "mf": "triangular", "params": [-2.0, 2.0, 2.0]},
                ],
            },
        ],
        output_variables=[
            {
                "name": "y_a",
                "universe": [-20.0, 20.0],
                "terms": [
                    {"name": "F1", "type": "linear", "params": [1.0, 0.5, -0.2, 0.1]},
                    {"name": "F2", "type": "linear", "params": [-0.5, 1.2, 0.4, -0.3]},
                    {"name": "F3", "type": "constant", "params": [2.5]},
                ],
            },
            {
                "name": "y_b",
                "universe": [-20.0, 20.0],
                "terms": [
                    {"name": "G1", "type": "linear", "params": [0.3, -0.4, 1.1, 0.5]},
                    {"name": "G2", "type": "linear", "params": [0.8, 0.2, -0.6, 1.0]},
                    {"name": "G3", "type": "constant", "params": [-1.5]},
                ],
            },
        ],
        rules=[
            {"name": "R1", "antecedents": {"x1": "L", "x2": "A", "x3": "N"}, "consequents": {"y_a": "F1", "y_b": "G1"}},
            {"name": "R2", "antecedents": {"x1": "L", "x2": "B", "x3": "P"}, "consequents": {"y_a": "F2", "y_b": "G2"}},
            {"name": "R3", "antecedents": {"x1": "H", "x2": "C", "x3": "P"}, "consequents": {"y_a": "F3", "y_b": "G3"}},
            {"name": "R4", "antecedents": {"x1": "H", "x2": "A", "x3": "N"}, "consequents": {"y_a": "F2", "y_b": "G1"}},
        ],
        operators={"and": "prod", "or": "probor", "defuzzification": "wtaver"},
    )


@pytest.mark.parametrize("kind", ["mamdani", "ts"])
def test_evaluate_surface_3in_2out_with_output_name_and_fixed_inputs(kind: str) -> None:
    """evaluate_surface suporta output_name, input_axes e fixed_inputs em sistemas 3×2 Mamdani e TS."""
    fs = _build_3in_2out_mamdani() if kind == "mamdani" else _build_3in_2out_ts()
    in_names = [v["name"] for v in fs.input_variables]
    out_names = [v["name"] for v in fs.output_variables]
    ax0, ax1, fixed_ax = in_names[0], in_names[2], in_names[1]
    fixed_val = 0.25 if kind == "mamdani" else 1.5

    # Default output_name=None seleciona a primeira saída para Z
    surf_default = evaluate_surface(
        fs,
        input_axes=[ax0, ax1],
        fixed_inputs={fixed_ax: fixed_val},
        n_points=5,
        grid_resolution=51,
    )
    assert surf_default.status in ("success", "warning")
    assert surf_default.data is not None
    assert surf_default.data["output_name"] == out_names[0]
    assert surf_default.data["Z"] == surf_default.data["surfaces"][out_names[0]]
    assert surf_default.data["outputs"] == surf_default.data["surfaces"]
    assert set(surf_default.data["outputs"].keys()) == set(out_names)

    # output_name explícito seleciona a segunda saída para Z
    surf_second = evaluate_surface(
        fs,
        input_axes=[ax0, ax1],
        fixed_inputs={fixed_ax: fixed_val},
        output_name=out_names[1],
        n_points=5,
        grid_resolution=51,
    )
    assert surf_second.status in ("success", "warning")
    assert surf_second.data is not None
    assert surf_second.data["output_name"] == out_names[1]
    assert surf_second.data["Z"] == surf_second.data["surfaces"][out_names[1]]

    # Verifica ponto exato contra evaluate(...)
    x0_grid = surf_second.data["grids"][ax0]
    x1_grid = surf_second.data["grids"][ax1]
    pt = {ax0: x0_grid[2], ax1: x1_grid[3], fixed_ax: fixed_val}
    ev = evaluate(fs, pt, grid_resolution=51)
    assert ev.data is not None
    assert surf_second.data["Z"][2][3] == pytest.approx(ev.data["outputs"][out_names[1]], abs=1e-12)
    assert surf_default.data["Z"][2][3] == pytest.approx(ev.data["outputs"][out_names[0]], abs=1e-12)

    # Curva 1D com output_name explícito
    curve_1d = evaluate_surface(
        fs,
        input_axes=[ax0],
        fixed_inputs={fixed_ax: fixed_val, ax1: x1_grid[1]},
        output_name=out_names[1],
        n_points=5,
        grid_resolution=51,
    )
    assert curve_1d.status in ("success", "warning")
    assert curve_1d.data is not None
    assert curve_1d.data["output_name"] == out_names[1]
    assert len(curve_1d.data["Z"]) == 5
    assert curve_1d.data["Z"] == curve_1d.data["outputs"][out_names[1]]

    # output_name inválido falha com VALIDATION_ERROR
    bad_out = evaluate_surface(fs, output_name="nonexistent_output", n_points=3)
    assert bad_out.status == "failure" and bad_out.error is not None
    assert bad_out.error.code == "VALIDATION_ERROR"

    # input_axes duplicado falha com VALIDATION_ERROR
    dup_ax = evaluate_surface(fs, input_axes=[ax0, ax0], n_points=3)
    assert dup_ax.status == "failure" and dup_ax.error is not None
    assert dup_ax.error.code == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 5. Round-trip FML (export_fml / import_fml) em sistemas 3-input × 2-output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["mamdani", "ts"])
def test_fml_roundtrip_3in_2out_mamdani_and_ts(kind: str) -> None:
    """export_fml / import_fml preserva saídas em sistema 3×2 com MFs heterogêneas."""
    fs = _build_3in_2out_mamdani() if kind == "mamdani" else _build_3in_2out_ts()
    exp = export_fml(fs)
    assert exp.status == "success" and exp.data is not None
    assert exp.diagnostics["n_inputs"] == 3
    assert exp.diagnostics["n_outputs"] == 2

    imp = import_fml(exp.data["fml_xml"])
    assert imp.status == "success" and imp.data is not None
    restored = FuzzySystem.from_dict(imp.data["fuzzy_system"])
    assert len(restored.input_variables) == 3
    assert len(restored.output_variables) == 2

    rng = np.random.default_rng(505)
    for _ in range(12):
        pt = {
            v["name"]: float(rng.uniform(v["universe"][0], v["universe"][1]))
            for v in fs.input_variables
        }
        r_orig = evaluate(fs, pt, grid_resolution=51)
        r_rest = evaluate(restored, pt, grid_resolution=51)
        assert r_orig.data is not None and r_rest.data is not None
        for v in fs.output_variables:
            onm = v["name"]
            assert r_rest.data["outputs"][onm] == pytest.approx(r_orig.data["outputs"][onm], abs=1e-11)


def test_fml_roundtrip_anfis_3in_2out_heterogeneous() -> None:
    """Round-trip FML de modelo ANFIS 3-input × 2-output com MFs heterogêneas e mistas."""
    rng = np.random.default_rng(606)
    X = rng.uniform(-1.0, 1.0, size=(160, 3))
    Y = np.column_stack(
        [
            0.8 * X[:, 0] - 0.5 * X[:, 1] + 0.4 * np.square(X[:, 2]),
            np.sin(X[:, 0]) + 0.3 * X[:, 1] * X[:, 2],
        ]
    )
    anfis_res = fit_anfis(
        X,
        Y,
        n_mfs=[2, 3, 2],
        mf_type=["gaussian", "bell", "gauss"],
        max_epochs=15,
        input_names=["p1", "p2", "p3"],
        output_names=["out_a", "out_b"],
        seed=606,
    )
    assert anfis_res.status in ("success", "warning")
    assert anfis_res.data is not None
    fs = FuzzySystem.from_dict(anfis_res.data["fuzzy_system"])

    exp = export_fml(fs)
    assert exp.status == "success" and exp.data is not None
    imp = import_fml(exp.data["fml_xml"])
    assert imp.status == "success" and imp.data is not None
    restored = FuzzySystem.from_dict(imp.data["fuzzy_system"])

    for idx in range(10):
        r_orig = evaluate(fs, X[idx])
        r_rest = evaluate(restored, X[idx])
        assert r_orig.data is not None and r_rest.data is not None
        assert r_rest.data["outputs"]["out_a"] == pytest.approx(r_orig.data["outputs"]["out_a"], abs=1e-11)
        assert r_rest.data["outputs"]["out_b"] == pytest.approx(r_orig.data["outputs"]["out_b"], abs=1e-11)
