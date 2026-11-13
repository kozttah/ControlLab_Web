"""Testes oráculo independentes da Frente F9 para contratos e fixtures ouro.

Escopo normativo (CL-DIR-001 Seções 10.2, 10.4, 13.11, 15.2 e Apêndices A–D):
- Validação estrutural de pyproject.toml;
- Validação de todos os schemas JSON v1.0.0 e exemplos normativos em contracts/;
- Verificação de integridade SHA-256 das fixtures ouro;
- Verificação matemática/analítica/espectral independente de B-CARE-02, B-CARE-12x3 e B-SDP-A-D.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import scipy.linalg
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = ROOT / "contracts"
SCHEMAS_DIR = CONTRACTS_DIR / "schemas"
FIXTURES_DIR = CONTRACTS_DIR / "fixtures"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"


def _strict_json_load(path: Path) -> Any:
    def _reject_non_finite(token: str) -> Any:
        raise ValueError(f"Constante JSON não finita proibida encontrada: {token!r}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_non_finite)


def _tensor_to_array(tensor: dict[str, Any]) -> np.ndarray:
    shape = tuple(tensor["shape"])
    order = tensor["order"]
    arr = np.array(tensor["data"], dtype=np.float64).reshape(shape, order=order)
    assert np.all(np.isfinite(arr)), "Tensor contém NaN ou Inf"
    return arr


def _complex_pair_to_array(pair: dict[str, list[float]]) -> np.ndarray:
    real = np.asarray(pair["real"], dtype=np.float64)
    imag = np.asarray(pair["imag"], dtype=np.float64)
    assert real.shape == imag.shape
    return real + 1j * imag


def _sort_complex(vals: np.ndarray) -> np.ndarray:
    order = np.lexsort((np.imag(vals), np.real(vals)))
    return vals[order]


def _care_residual_rel(
    A: np.ndarray, B: np.ndarray, Q: np.ndarray, R: np.ndarray, P: np.ndarray
) -> float:
    R_inv_BT_P = np.linalg.solve(R, B.T @ P)
    E = A.T @ P + P @ A - P @ B @ R_inv_BT_P + Q
    denom = (
        1.0
        + np.linalg.norm(A.T @ P, "fro")
        + np.linalg.norm(P @ A, "fro")
        + np.linalg.norm(P @ B @ R_inv_BT_P, "fro")
        + np.linalg.norm(Q, "fro")
    )
    return float(np.linalg.norm(E, "fro") / denom)


def _symmetry_error_rel(M: np.ndarray) -> float:
    return float(np.linalg.norm(M - M.T, "fro") / (1.0 + np.linalg.norm(M, "fro")))


@pytest.fixture(scope="module")
def schema_registry() -> tuple[Registry, dict[str, dict[str, Any]]]:
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = _strict_json_load(path)
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        res = Resource.from_contents(schema)
        resources.append((schema.get("$id", path.name), res))
        resources.append((path.name, res))
    return Registry().with_resources(resources), schemas


def _validate(
    instance: Any,
    schema_name: str,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    registry, schemas = schema_registry
    validator = Draft202012Validator(schemas[schema_name], registry=registry)
    validator.validate(instance)


# ---------------------------------------------------------------------------
# 1. Validação estrutural de pyproject.toml
# ---------------------------------------------------------------------------
def test_pyproject_toml_structure() -> None:
    pyproject_path = ROOT / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml ausente"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    build_sys = data["build-system"]
    assert any(req.startswith("setuptools>=61.0") for req in build_sys["requires"])

    proj = data["project"]
    assert proj["name"] == "control-lab"
    assert proj["requires-python"] == ">=3.11"
    deps_joined = " ".join(proj["dependencies"])
    assert "numpy" in deps_joined
    assert "scipy" in deps_joined

    extras = proj["optional-dependencies"]
    for group in ("dev", "test", "oracles"):
        group_str = " ".join(extras[group])
        assert "pytest" in group_str
        assert "jsonschema" in group_str

    sdp_str = " ".join(extras["sdp"])
    assert "clarabel" in sdp_str
    assert "cvxpy-base" in sdp_str

    find_cfg = data["tool"]["setuptools"]["packages"]["find"]
    assert "control_lab*" in find_cfg["include"]

    pytest_cfg = data["tool"]["pytest"]["ini_options"]
    assert pytest_cfg["testpaths"] == ["tests"]
    assert pytest_cfg["pythonpath"] == ["."]


# ---------------------------------------------------------------------------
# 2. Validação de schemas JSON, exemplos normativos e casos negativos
# ---------------------------------------------------------------------------
def test_all_expected_schemas_exist_and_are_valid(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    _, schemas = schema_registry
    expected_schemas = {
        "tensor.schema.json",
        "result.schema.json",
        "state_space.schema.json",
        "controller.schema.json",
        "ts_state_space.schema.json",
        "rpc_request.schema.json",
        "rpc_response.schema.json",
        "ctrlab_manifest.schema.json",
        "pvm.schema.json",
        "golden_fixture.schema.json",
    }
    assert expected_schemas.issubset(set(schemas.keys()))


@pytest.mark.parametrize(
    ("example_file", "schema_file"),
    [
        ("rpc_request_lqr.json", "rpc_request.schema.json"),
        ("rpc_response_lqr.json", "rpc_response.schema.json"),
        ("statespace_example.json", "state_space.schema.json"),
        ("pvm_skeleton.json", "pvm.schema.json"),
    ],
)
def test_normative_examples_validate(
    example_file: str,
    schema_file: str,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    ex_path = EXAMPLES_DIR / example_file
    assert ex_path.exists(), f"Exemplo normativo ausente: {ex_path}"
    payload = _strict_json_load(ex_path)
    _validate(payload, schema_file, schema_registry)


def test_rpc_response_rejects_illustrative_strings_and_invalid_errors(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    resp = _strict_json_load(EXAMPLES_DIR / "rpc_response_lqr.json")
    # Strings ilustrativas em arrays numéricos devem ser rejeitadas pelo schema de tensor
    bad_poles = {"real": ["fixture-dependent"], "imag": ["fixture-dependent"]}
    with pytest.raises(ValidationError):
        _validate(bad_poles, "tensor.schema.json", schema_registry)

    # Todas as 12 categorias da Seção 8.4 devem ser aceitas em resposta de falha
    categories = [
        "VALIDATION_ERROR",
        "DIMENSION_MISMATCH",
        "UNSUPPORTED_MODEL",
        "HYPOTHESIS_VIOLATED",
        "NUMERICAL_INCONCLUSIVE",
        "SOLVER_UNAVAILABLE",
        "RESOURCE_LIMIT",
        "CANCELLED",
        "WORKER_RESTARTED",
        "SCHEMA_UNSUPPORTED",
        "IMPORT_UNTRUSTED_CODE",
        "INTERNAL_ERROR",
    ]
    for code in categories:
        err_resp = dict(resp)
        err_resp["status"] = "failure"
        err_resp["result"] = None
        err_resp["error"] = {"code": code, "message": f"Erro simulado {code}"}
        _validate(err_resp, "rpc_response.schema.json", schema_registry)

    # status="failure" com error=null deve falhar validação
    bad_fail = dict(resp)
    bad_fail["status"] = "failure"
    bad_fail["error"] = None
    with pytest.raises(ValidationError):
        _validate(bad_fail, "rpc_response.schema.json", schema_registry)

    # Categoria de erro inventada deve falhar validação
    bad_code = dict(resp)
    bad_code["status"] = "failure"
    bad_code["error"] = {"code": "UNKNOWN_CUSTOM_ERROR", "message": "Invalido"}
    with pytest.raises(ValidationError):
        _validate(bad_code, "rpc_response.schema.json", schema_registry)


def test_controller_ts_and_manifest_schemas_positive_and_negative(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    sf_ctrl = {
        "schema_version": "1.0.0",
        "id": "ctrl-sf-1",
        "revision": 1,
        "kind": "StateFeedbackController",
        "feedback_sign": "negative",
        "K": {"shape": [1, 2], "dtype": "float64", "order": "C", "data": [2.0, 3.0]},
        "state_coordinates": ["x1", "x2"],
        "reference_map": None,
        "dt": None,
        "provenance": {"algorithm": "analytical"},
    }
    _validate(sf_ctrl, "controller.schema.json", schema_registry)

    dyn_ctrl = {
        "schema_version": "1.0.0",
        "id": "ctrl-dyn-1",
        "revision": 1,
        "kind": "DynamicController",
        "feedback_sign": "negative",
        "dt": None,
        "Ac": {"shape": [1, 1], "dtype": "float64", "order": "C", "data": [-1.0]},
        "Bc": {"shape": [1, 1], "dtype": "float64", "order": "C", "data": [1.0]},
        "Cc": {"shape": [1, 1], "dtype": "float64", "order": "C", "data": [2.0]},
        "Dc": {"shape": [1, 1], "dtype": "float64", "order": "C", "data": [0.5]},
        "ports": {
            "inputs": [{"name": "y", "role": "y", "size": 1}],
            "outputs": [{"name": "u", "role": "u", "size": 1}],
        },
        "initial_state": {"shape": [1], "dtype": "float64", "order": "C", "data": [0.0]},
        "provenance": {"algorithm": "lqg"},
    }
    _validate(dyn_ctrl, "controller.schema.json", schema_registry)

    pdc_ctrl = {
        "schema_version": "1.0.0",
        "id": "ctrl-pdc-1",
        "revision": 1,
        "kind": "PDCController",
        "feedback_sign": "positive",
        "K_i": [
            {"shape": [1, 2], "dtype": "float64", "order": "C", "data": [-2.0, -3.0]},
            {"shape": [1, 2], "dtype": "float64", "order": "C", "data": [-4.0, -5.0]},
        ],
        "membership_ref": {
            "model_id": "ts-plant-1",
            "model_revision": 1,
            "membership_version": "1.0.0",
        },
        "measurement_requirements": {
            "required_premise_variables": ["x1"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_measured"],
        },
        "dt": None,
        "provenance": {"algorithm": "lmi_pdc"},
    }
    _validate(pdc_ctrl, "controller.schema.json", schema_registry)

    for ts_kind, avail_mode in [
        ("ts_measured", "all_measured"),
        ("polytopic_uncertain", "unknown_uncertain"),
        ("ts_partially_observed", "partially_observed"),
    ]:
        ts_obj = {
            "schema_version": "1.0.0",
            "id": f"ts-{ts_kind}",
            "revision": 1,
            "kind": ts_kind,
            "dt": None,
            "membership_spec": {
                "version": "1.0.0",
                "premise_variables": ["x1"],
                "sum_to_one_domain": True,
            },
            "premise_availability": {
                "mode": avail_mode,
                "measured_premises": ["x1"] if avail_mode == "all_measured" else [],
                "unmeasured_premises": [] if avail_mode == "all_measured" else ["x1"],
                "estimator_required_for_pdc": avail_mode != "all_measured",
            },
            "domain": {"bounds": {"x1": [-1.0, 1.0]}},
            "vertices": [
                {
                    "vertex_id": "v1",
                    "A": {"shape": [2, 2], "dtype": "float64", "order": "C", "data": [0.0, 1.0, -1.0, -2.0]},
                    "B": {"shape": [2, 1], "dtype": "float64", "order": "C", "data": [0.0, 1.0]},
                    "C": {"shape": [1, 2], "dtype": "float64", "order": "C", "data": [1.0, 0.0]},
                    "D": {"shape": [1, 1], "dtype": "float64", "order": "C", "data": [0.0]},
                }
            ],
            "state_names": ["x1", "x2"],
            "input_names": ["u"],
            "output_names": ["y"],
            "units": {"time": "s"},
            "provenance": {"source": "test"},
        }
        _validate(ts_obj, "ts_state_space.schema.json", schema_registry)

    manifest = {
        "format": "ctrlab",
        "schema_version": "1.0.0",
        "app_version": "1.0.0",
        "created_at": "2026-11-13T12:00:00Z",
        "project_id": "proj-001",
        "project_revision": 1,
        "hashes": {"models.json": "a" * 64},
        "capabilities": {"required_features": ["statespace.care"]},
    }
    _validate(manifest, "ctrlab_manifest.schema.json", schema_registry)

    bad_manifest = dict(manifest)
    bad_manifest["hashes"] = {"models.json": "not-a-sha256"}
    with pytest.raises(ValidationError):
        _validate(bad_manifest, "ctrlab_manifest.schema.json", schema_registry)


# ---------------------------------------------------------------------------
# 3. Integridade SHA-256 e schema de todas as fixtures ouro
# ---------------------------------------------------------------------------
def test_golden_fixtures_checksums_and_schema(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    checksum_path = FIXTURES_DIR / "checksums.sha256"
    assert checksum_path.exists(), "checksums.sha256 ausente"

    entries: dict[str, str] = {}
    for raw_line in checksum_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        digest, fname = line.split(None, 1)
        entries[fname.strip()] = digest

    expected_files = {"B-CARE-02.json", "B-CARE-12x3.json", "B-SDP-A-D.json"}
    assert expected_files.issubset(set(entries.keys()))

    for fname, expected_digest in entries.items():
        fpath = FIXTURES_DIR / fname
        assert fpath.exists(), f"Fixture ausente: {fpath}"
        actual_digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
        assert actual_digest == expected_digest, f"SHA-256 inválido em {fname}"
        fixture = _strict_json_load(fpath)
        _validate(fixture, "golden_fixture.schema.json", schema_registry)


# ---------------------------------------------------------------------------
# 4. Oráculo matemático independente: B-CARE-02 (analítica 2x1)
# ---------------------------------------------------------------------------
def test_oracle_b_care_02_analytical() -> None:
    fixture = _strict_json_load(FIXTURES_DIR / "B-CARE-02.json")
    tols = fixture["tolerances"]
    data = fixture["data"]
    exp = data["expected"]

    A = _tensor_to_array(data["A"])
    B = _tensor_to_array(data["B"])
    Q = _tensor_to_array(data["Q"])
    R = _tensor_to_array(data["R"])
    x0 = _tensor_to_array(data["x0"])

    P_exp = _tensor_to_array(exp["P"])
    K_exp = _tensor_to_array(exp["K"])
    poles_exp = _complex_pair_to_array(exp["closed_loop_poles"])

    assert A.shape == (2, 2) and B.shape == (2, 1)
    assert data["feedback_sign"] == "negative"

    # Verificação algébrica exata fechada (P=[[6,2],[2,3]], K=[2,3], polos={-2,-1})
    np.testing.assert_allclose(P_exp, np.array([[6.0, 2.0], [2.0, 3.0]]), atol=tols["P_atol"])
    np.testing.assert_allclose(K_exp, np.array([[2.0, 3.0]]), atol=tols["K_atol"])
    np.testing.assert_allclose(
        _sort_complex(poles_exp),
        np.array([-2.0 + 0j, -1.0 + 0j]),
        atol=tols["poles_atol"],
    )

    # Simetria, SPD, rCARE, ganho K = R^{-1} B^T P, estabilidade e custo
    assert _symmetry_error_rel(P_exp) <= tols["symmetry_error_max"]
    assert np.min(np.linalg.eigvalsh(P_exp)) > 0.0
    assert _care_residual_rel(A, B, Q, R, P_exp) <= tols["rCARE_max"]

    K_from_P = np.linalg.solve(R, B.T @ P_exp)
    np.testing.assert_allclose(K_from_P, K_exp, atol=tols["K_atol"])

    Acl = A - B @ K_exp
    eigs_cl = _sort_complex(np.linalg.eigvals(Acl))
    assert np.max(np.real(eigs_cl)) < 0.0
    np.testing.assert_allclose(eigs_cl, _sort_complex(poles_exp), atol=tols["poles_atol"])

    cost = float((x0.T @ P_exp @ x0)[0, 0])
    assert math.isclose(cost, exp["optimal_cost"], abs_tol=tols["cost_atol"])
    assert math.isclose(cost, 13.0, abs_tol=tols["cost_atol"])

    # Confronto independente com SciPy CARE
    P_scipy = scipy.linalg.solve_continuous_are(A, B, Q, R)
    np.testing.assert_allclose(P_scipy, P_exp, atol=tols["P_atol"])


# ---------------------------------------------------------------------------
# 5. Oráculo matemático independente: B-CARE-12x3
# ---------------------------------------------------------------------------
def test_oracle_b_care_12x3_numerical() -> None:
    fixture = _strict_json_load(FIXTURES_DIR / "B-CARE-12x3.json")
    tols = fixture["tolerances"]
    data = fixture["data"]
    exp = data["expected"]

    A = _tensor_to_array(data["A"])
    B = _tensor_to_array(data["B"])
    C = _tensor_to_array(data["C"])
    D = _tensor_to_array(data["D"])
    Q = _tensor_to_array(data["Q"])
    R = _tensor_to_array(data["R"])
    x0 = _tensor_to_array(data["x0"])

    P_exp = _tensor_to_array(exp["P"])
    K_exp = _tensor_to_array(exp["K"])
    poles_cl_exp = _complex_pair_to_array(exp["closed_loop_poles"])

    n, m = 12, 3
    assert A.shape == (n, n)
    assert B.shape == (n, m)
    assert C.shape[1] == n and D.shape == (C.shape[0], m)
    assert Q.shape == (n, n) and R.shape == (m, m) and x0.shape == (n, 1)

    # Q e R devem ser SPD
    assert _symmetry_error_rel(Q) <= 1e-14
    assert _symmetry_error_rel(R) <= 1e-14
    assert np.min(np.linalg.eigvalsh(Q)) > 0.0
    assert np.min(np.linalg.eigvalsh(R)) > 0.0

    # A deve conter pelo menos um modo instável Re(lambda) > 0
    eigs_open = np.linalg.eigvals(A)
    assert np.max(np.real(eigs_open)) > 0.0

    # Teste PBH independente de estabilizabilidade (A, B) e detectabilidade (A, Q^{1/2})
    Q_half = scipy.linalg.sqrtm(Q)
    Q_half = np.real_if_close(Q_half)
    eye_n = np.eye(n, dtype=np.complex128)
    for lam in eigs_open:
        if np.real(lam) >= -1e-9:
            pbh_ctrl = np.hstack([lam * eye_n - A, B])
            svals_ctrl = np.linalg.svd(pbh_ctrl, compute_uv=False)
            assert np.sum(svals_ctrl > 1e-8) == n, f"(A,B) falhou PBH em lambda={lam}"

            pbh_obs = np.vstack([lam * eye_n - A, Q_half])
            svals_obs = np.linalg.svd(pbh_obs, compute_uv=False)
            assert np.sum(svals_obs > 1e-8) == n, f"(A,Q^1/2) falhou PBH em lambda={lam}"

    # Oráculo independente SciPy CARE
    P_ref = scipy.linalg.solve_continuous_are(A, B, Q, R)
    K_ref = np.linalg.solve(R, B.T @ P_ref)

    np.testing.assert_allclose(P_exp, P_ref, rtol=tols["P_rel_tol"], atol=1e-12)
    np.testing.assert_allclose(K_exp, K_ref, rtol=tols["K_rel_tol"], atol=1e-12)

    # Resíduo CARE, simetria, positividade e estabilidade de malha fechada
    r_care = _care_residual_rel(A, B, Q, R, P_exp)
    sym_err = _symmetry_error_rel(P_exp)
    assert r_care <= tols["rCARE_max"]
    assert sym_err <= tols["symmetry_error_max"]
    assert np.min(np.linalg.eigvalsh(P_exp)) > 0.0

    Acl = A - B @ K_exp
    eigs_cl = _sort_complex(np.linalg.eigvals(Acl))
    assert np.max(np.real(eigs_cl)) < 0.0
    np.testing.assert_allclose(eigs_cl, _sort_complex(poles_cl_exp), atol=tols["poles_atol"])

    cost = float((x0.T @ P_exp @ x0)[0, 0])
    assert math.isclose(cost, exp["optimal_cost"], rel_tol=tols["cost_rel_tol"])


# ---------------------------------------------------------------------------
# 6. Oráculo matemático e espectral independente: B-SDP-A-D (Níveis A–D)
# ---------------------------------------------------------------------------
def _eval_lmi_block(block: dict[str, Any], x: list[float]) -> np.ndarray:
    F0 = _tensor_to_array(block["F0"])
    F_list = [_tensor_to_array(Fk) for Fk in block["F_k"]]
    res = F0.copy()
    for xk, Fk in zip(x, F_list, strict=True):
        res = res + float(xk) * Fk
    return 0.5 * (res + res.T)


def test_oracle_b_sdp_levels_a_to_d() -> None:
    fixture = _strict_json_load(FIXTURES_DIR / "B-SDP-A-D.json")
    tols = fixture["tolerances"]
    cases = fixture["data"]["cases"]

    # --- T-SDP-A1: min x, x >= 1 ---
    c_a1 = cases["T-SDP-A1"]
    x_a1 = c_a1["expected"]["x_opt"]
    assert math.isclose(x_a1[0], 1.0, abs_tol=tols["primal_tol"])
    F_a1 = _eval_lmi_block(c_a1["canonical_sdp"]["blocks"][0], x_a1)
    assert np.min(np.linalg.eigvalsh(F_a1)) >= -tols["psd_tol"]
    Z_a1 = _tensor_to_array(c_a1["expected"]["dual_Z"][0])
    F1_a1 = _tensor_to_array(c_a1["canonical_sdp"]["blocks"][0]["F_k"][0])
    F0_a1 = _tensor_to_array(c_a1["canonical_sdp"]["blocks"][0]["F0"])
    assert np.min(np.linalg.eigvalsh(Z_a1)) >= -tols["dual_tol"]
    assert math.isclose(float(np.trace(F1_a1.T @ Z_a1)), c_a1["canonical_sdp"]["c"][0], abs_tol=tols["dual_tol"])
    dual_obj_a1 = -float(np.trace(F0_a1.T @ Z_a1))
    assert math.isclose(c_a1["expected"]["obj_opt"], dual_obj_a1, abs_tol=tols["gap_tol"])

    # --- T-SDP-A2: x >= 2, x <= 1 (infactível forte com certificado Farkas Z) ---
    c_a2 = cases["T-SDP-A2"]
    blk_a2 = c_a2["canonical_sdp"]["blocks"][0]
    F0_a2 = _tensor_to_array(blk_a2["F0"])
    F_k_a2 = [_tensor_to_array(Fk) for Fk in blk_a2["F_k"]]
    Z_farkas = _tensor_to_array(c_a2["expected"]["farkas_Z"][0])
    assert _symmetry_error_rel(Z_farkas) <= tols["dual_tol"]
    assert np.min(np.linalg.eigvalsh(Z_farkas)) >= -tols["dual_tol"]
    for Fk in F_k_a2:
        assert abs(float(np.trace(Fk.T @ Z_farkas))) <= tols["dual_tol"]
    assert float(np.trace(F0_a2.T @ Z_farkas)) < -tols["strict_margin"]

    # --- T-SDP-A3: min x, x <= 2 (ilimitado com direção recessiva) ---
    c_a3 = cases["T-SDP-A3"]
    blk_a3 = c_a3["canonical_sdp"]["blocks"][0]
    x0_a3 = c_a3["expected"]["feasible_x0"]
    d_a3 = c_a3["expected"]["recession_direction"]
    c_vec_a3 = np.asarray(c_a3["canonical_sdp"]["c"], dtype=np.float64)
    F_x0_a3 = _eval_lmi_block(blk_a3, x0_a3)
    assert np.min(np.linalg.eigvalsh(F_x0_a3)) >= -tols["psd_tol"]
    F_lin_d = sum(float(dk) * _tensor_to_array(Fk) for dk, Fk in zip(d_a3, blk_a3["F_k"], strict=True))
    assert np.min(np.linalg.eigvalsh(F_lin_d)) >= -tols["psd_tol"]
    assert float(c_vec_a3 @ np.asarray(d_a3, dtype=np.float64)) < -tols["strict_margin"]

    # --- T-SDP-B1: [[1, x], [x, 1]] >= 0, min x -> x* = -1 na fronteira ---
    c_b1 = cases["T-SDP-B1"]
    x_b1 = c_b1["expected"]["x_opt"]
    assert math.isclose(x_b1[0], -1.0, abs_tol=tols["primal_tol"])
    blk_b1 = c_b1["canonical_sdp"]["blocks"][0]
    F_b1 = _eval_lmi_block(blk_b1, x_b1)
    eigs_b1 = np.sort(np.linalg.eigvalsh(F_b1))
    np.testing.assert_allclose(eigs_b1, np.array([0.0, 2.0]), atol=tols["psd_tol"])
    Z_b1 = _tensor_to_array(c_b1["expected"]["dual_Z"][0])
    F0_b1 = _tensor_to_array(blk_b1["F0"])
    F1_b1 = _tensor_to_array(blk_b1["F_k"][0])
    assert np.min(np.linalg.eigvalsh(Z_b1)) >= -tols["dual_tol"]
    assert math.isclose(float(np.trace(F1_b1.T @ Z_b1)), c_b1["canonical_sdp"]["c"][0], abs_tol=tols["dual_tol"])
    assert abs(float(np.trace(F_b1.T @ Z_b1))) <= tols["gap_tol"]
    assert math.isclose(-float(np.trace(F0_b1.T @ Z_b1)), c_b1["expected"]["obj_opt"], abs_tol=tols["gap_tol"])

    # --- T-SDP-C1: SDP com Slater estrito e gap primal-dual nulo ---
    c_c1 = cases["T-SDP-C1"]
    blk_c1 = c_c1["canonical_sdp"]["blocks"][0]
    F_slater = _eval_lmi_block(blk_c1, c_c1["expected"]["slater_x"])
    assert np.min(np.linalg.eigvalsh(F_slater)) > tols["strict_margin"]
    x_c1 = c_c1["expected"]["x_opt"]
    F_c1 = _eval_lmi_block(blk_c1, x_c1)
    assert np.min(np.linalg.eigvalsh(F_c1)) >= -tols["psd_tol"]
    Z_c1 = _tensor_to_array(c_c1["expected"]["dual_Z"][0])
    assert np.min(np.linalg.eigvalsh(Z_c1)) >= -tols["dual_tol"]
    F0_c1 = _tensor_to_array(blk_c1["F0"])
    for ck, Fk_dict in zip(c_c1["canonical_sdp"]["c"], blk_c1["F_k"], strict=True):
        Fk = _tensor_to_array(Fk_dict)
        assert math.isclose(float(np.trace(Fk.T @ Z_c1)), ck, abs_tol=tols["dual_tol"])
    primal_obj_c1 = float(np.dot(c_c1["canonical_sdp"]["c"], x_c1) + c_c1["canonical_sdp"]["c0"])
    dual_obj_c1 = float(-np.trace(F0_c1.T @ Z_c1) + c_c1["canonical_sdp"]["c0"])
    assert abs(primal_obj_c1 - dual_obj_c1) <= tols["gap_tol"]
    assert abs(float(np.trace(F_c1.T @ Z_c1))) <= tols["gap_tol"]

    # --- T-SDP-D1: Estabilização contínua com taxa alpha > 0 ---
    c_d1 = cases["T-SDP-D1"]
    assert c_d1["feedback_sign"] == "positive"
    A_d1 = _tensor_to_array(c_d1["A"])
    B_d1 = _tensor_to_array(c_d1["B"])
    alpha_d1 = float(c_d1["alpha"])
    Q_d1 = _tensor_to_array(c_d1["Q_lmi"])
    Y_d1 = _tensor_to_array(c_d1["Y"])
    K_d1 = _tensor_to_array(c_d1["K"])

    assert _symmetry_error_rel(Q_d1) <= tols["psd_tol"]
    assert np.min(np.linalg.eigvalsh(Q_d1)) > tols["strict_margin"]
    K_rec_d1 = np.linalg.solve(Q_d1.T, Y_d1.T).T
    np.testing.assert_allclose(K_rec_d1, K_d1, atol=tols["gain_tol"])

    lmi_d1 = (A_d1 @ Q_d1 + B_d1 @ Y_d1) + (A_d1 @ Q_d1 + B_d1 @ Y_d1).T + 2.0 * alpha_d1 * Q_d1
    lmi_d1 = 0.5 * (lmi_d1 + lmi_d1.T)
    assert np.max(np.linalg.eigvalsh(lmi_d1)) < -tols["strict_margin"]

    eigs_d1 = np.linalg.eigvals(A_d1 + B_d1 @ K_d1)
    assert np.max(np.real(eigs_d1)) < -alpha_d1 - tols["strict_margin"]

    # --- T-SDP-D2: BRL H-infinito generalizado ---
    c_d2 = cases["T-SDP-D2"]
    assert c_d2["feedback_sign"] == "positive"
    A_d2 = _tensor_to_array(c_d2["A"])
    B1_d2 = _tensor_to_array(c_d2["B1"])
    B2_d2 = _tensor_to_array(c_d2["B2"])
    C1_d2 = _tensor_to_array(c_d2["C1"])
    D11_d2 = _tensor_to_array(c_d2["D11"])
    D12_d2 = _tensor_to_array(c_d2["D12"])
    gamma_d2 = float(c_d2["gamma"])
    Q_d2 = _tensor_to_array(c_d2["Q_lmi"])
    Y_d2 = _tensor_to_array(c_d2["Y"])
    K_d2 = _tensor_to_array(c_d2["K"])

    assert gamma_d2 > 0.0
    assert _symmetry_error_rel(Q_d2) <= tols["psd_tol"]
    assert np.min(np.linalg.eigvalsh(Q_d2)) > tols["strict_margin"]
    K_rec_d2 = np.linalg.solve(Q_d2.T, Y_d2.T).T
    np.testing.assert_allclose(K_rec_d2, K_d2, atol=tols["gain_tol"])

    Z_blk = A_d2 @ Q_d2 + B2_d2 @ Y_d2
    W_blk = C1_d2 @ Q_d2 + D12_d2 @ Y_d2
    nw = B1_d2.shape[1]
    nz = C1_d2.shape[0]
    brl = np.block([
        [Z_blk + Z_blk.T, B1_d2, W_blk.T],
        [B1_d2.T, -gamma_d2 * np.eye(nw), D11_d2.T],
        [W_blk, D11_d2, -gamma_d2 * np.eye(nz)],
    ])
    brl = 0.5 * (brl + brl.T)
    assert np.max(np.linalg.eigvalsh(brl)) < -tols["strict_margin"]

    Acl_d2 = A_d2 + B2_d2 @ K_d2
    assert np.max(np.real(np.linalg.eigvals(Acl_d2))) < -tols["strict_margin"]

    # Verificação espectral amostral independente de ||T_wz||_inf < gamma
    Ccl_d2 = C1_d2 + D12_d2 @ K_d2
    eye_nx = np.eye(A_d2.shape[0], dtype=np.complex128)
    omegas = np.logspace(-3, 3, 500)
    peak_sv = max(
        float(np.linalg.svd(Ccl_d2 @ np.linalg.solve(1j * w * eye_nx - Acl_d2, B1_d2) + D11_d2, compute_uv=False)[0])
        for w in omegas
    )
    assert peak_sv < gamma_d2
