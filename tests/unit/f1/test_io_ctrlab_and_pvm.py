"""Testes unitários, contratuais, segurança e equivalência física da Frente F1 para WP-05-F1-IO-CTRLAB-PVM.

Cobre obrigatoriamente:
- T-IO-01: Segurança/integridade ZIP `.ctrlab` (anti-traversal, symlinks, colisões NFC/case-folded,
  anti-ZIP bomb inclusive header forjado, verificação SHA-256, schema_version futura e migração dry_run)
- T-IO-02: Importação 100% passiva `.pvm` (jamais executa `codeContext.code` nem `eval`/`exec`,
  emite aviso `UNTRUSTED_CODE_CONTEXT_IGNORED`, registra `code_executed: False`)
- T-PVM-01: Exportação `.pvm` v1.0.0 e equivalência física (`B-PVM-LQR`, `C=I`, `C!=I` com exposição
  explícita de `x`, `m!=p`, prefiltro `N`, `feedback_sign` negative/positive, saturação on/off)
- T-PVM-02: `DynamicController` (`Dp != 0, Dc != 0`, `output_feedback`, `error_feedback`, `two_dof`,
  `initial_state != 0`), estados aumentados e curvas equivalentes entre `.pvm` e `interconnect` + `simulate_lti`
- Round-trip bit-exact de `.ctrlab` com toda a hierarquia canônica, `datasets/*.csv` e `exports/*.pvm`
- Bloqueio transparente DEC-OPEN-07 para `PDCController` / `FuzzySystem` / `TSStateSpace` + fallback `generate_pathsim_script`
"""

from __future__ import annotations

import builtins
import copy
import io
import json
import math
from pathlib import Path
import stat
import zipfile

import numpy as np
import pytest
import scipy.integrate
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from control_lab.core import (
    Dataset,
    DynamicController,
    Experiment,
    FuzzySystem,
    IdentifiedModel,
    PDCController,
    StateFeedbackController,
    StateSpace,
    TSStateSpace,
    TransferFunction,
    interconnect,
    restore_model,
    serialize_model,
    tensor_to_array,
)
from control_lab.diagnostics import (
    DimensionMismatchError,
    HypothesisViolatedError,
    ImportUntrustedCodeError,
    ResourceLimitError,
    Result,
    SchemaUnsupportedError,
    UnsupportedModelError,
    ValidationError,
    build_provenance,
)
from control_lab.io import (
    PATHVIEW_BLOCK_REGISTRY,
    PATHVIEW_SPEC_VERSION,
    dataset_to_csv,
    export_ctrlab,
    export_ctrlab_bytes,
    export_pvm,
    extract_lti_from_pvm,
    generate_pathsim_script,
    import_pvm,
    inspect_ctrlab,
    load_ctrlab,
    load_ctrlab_objects,
    load_pvm,
    make_pvm,
    migrate_ctrlab_manifest,
    parse_csv_dataset,
    save_ctrlab,
    simulate_pvm_graph,
    validate_ctrlab_manifest,
    validate_pvm_structure,
)
from control_lab.statespace import simulate_lti

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
FIXTURES_DIR = ROOT / "contracts" / "fixtures"


@pytest.fixture(scope="module")
def schema_registry() -> tuple[Registry, dict[str, dict[str, Any]]]:
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        res = Resource.from_contents(schema)
        resources.append((schema.get("$id", path.name), res))
        resources.append((path.name, res))
    return Registry().with_resources(resources), schemas


def _assert_schema_valid(
    instance: dict[str, Any],
    schema_name: str,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    registry, schemas = schema_registry
    Draft202012Validator(schemas[schema_name], registry=registry).validate(instance)


def _make_full_project_items() -> dict[str, Any]:
    ss = StateSpace(
        A=[[0.0, 1.0], [-2.0, -3.0]],
        B=[[0.0], [1.0]],
        C=[[1.0, 0.5]],
        D=[[0.0]],
        dt=None,
        state_names=["pos", "vel"],
        input_names=["u_cmd"],
        output_names=["y_meas"],
        units={"time": "s", "states": ["m", "m/s"], "inputs": ["N"], "outputs": ["m"]},
        id="ss-plant-01",
        revision=2,
    )
    ss_disc = StateSpace(
        A=[[0.8, 0.1], [0.0, 0.9]],
        B=[[0.05], [0.2]],
        C=[[1.0, 0.0]],
        D=[[0.0]],
        dt=0.05,
        id="ss-disc-01",
        revision=1,
    )
    tf = TransferFunction(
        num=[[[1.0, 0.5], [2.0]], [[0.0], [3.0]]],
        den=[[[1.0, 2.0, 1.0], [1.0, 3.0]], [[1.0], [1.0, 4.0]]],
        dt=None,
        id="tf-mimo-01",
        revision=1,
    )
    t = np.linspace(0.0, 1.0, 11)
    u = np.column_stack([np.sin(t), np.cos(t)])
    y = np.column_stack([2.0 * u[:, 0] + 0.5 * u[:, 1]])
    ds = Dataset(
        t=t,
        u=u,
        y=y,
        dt=0.1,
        require_uniform=True,
        input_names=["u1", "u2"],
        output_names=["y1"],
        units={"time": "s", "inputs": ["V", "A"], "outputs": ["rad"]},
        id="ds-essay-01",
        revision=3,
    )
    id_mod = IdentifiedModel(
        model=ss_disc,
        algorithm="arx_qr",
        dataset_ref={"id": ds.id, "revision": ds.revision},
        partitions={"train_indices": [0, 1, 2, 3, 4, 5], "validation_indices": [6, 7, 8, 9, 10]},
        metrics={"fit_percent": 98.7, "rmse": 1e-4},
        noise_hypothesis={"type": "white_equation_error"},
        excitation_diagnostics={"pe_sufficient": True, "cond": 2.4},
        id="idmod-01",
        revision=1,
    )
    ts_mod = TSStateSpace(
        vertices=[
            {"vertex_id": "v1", "A": [[0.0, 1.0], [-1.0, -2.0]], "B": [[0.0], [1.0]], "C": [[1.0, 0.0]], "D": [[0.0]]},
            {"vertex_id": "v2", "A": [[0.0, 1.0], [-3.0, -4.0]], "B": [[0.0], [1.5]], "C": [[1.0, 0.0]], "D": [[0.0]]},
        ],
        kind="ts_measured",
        dt=None,
        membership_spec={"version": "1.0.0", "premise_variables": ["x1"], "sum_to_one_domain": True},
        premise_availability={"mode": "all_measured", "measured_premises": ["x1"], "unmeasured_premises": []},
        domain={"bounds": {"x1": [-2.0, 2.0]}},
        id="ts-meas-01",
        revision=1,
    )
    fuzzy = FuzzySystem(
        inference_type="ts",
        input_variables=[
            {
                "name": "e",
                "universe": [-1.0, 1.0],
                "terms": [
                    {"name": "neg", "type": "trimf", "params": [-1.0, -1.0, 1.0]},
                    {"name": "pos", "type": "trimf", "params": [-1.0, 1.0, 1.0]},
                ],
            }
        ],
        output_variables=[
            {
                "name": "u",
                "universe": [-5.0, 5.0],
                "terms": [
                    {"name": "low", "type": "constant", "params": [-2.0]},
                    {"name": "high", "type": "constant", "params": [2.0]},
                ],
            }
        ],
        rules=[
            {"antecedents": {"e": "neg"}, "consequents": {"u": "low"}, "weight": 1.0},
            {"antecedents": {"e": "pos"}, "consequents": {"u": "high"}, "weight": 1.0},
        ],
        id="fuzzy-01",
        revision=1,
    )
    sf_ctrl = StateFeedbackController(
        K=[[2.5, 1.75]],
        feedback_sign="negative",
        state_coordinates=["pos", "vel"],
        reference_map=[[3.25]],
        dt=None,
        id="ctrl-sf-01",
        revision=2,
    )
    dyn_ctrl = DynamicController(
        Ac=[[-2.0]],
        Bc=[[1.0, 0.5]],
        Cc=[[1.2]],
        Dc=[[0.3, 0.8]],
        feedback_sign="negative",
        dt=None,
        ports={
            "inputs": [{"name": "y", "role": "y", "size": 1}, {"name": "r", "role": "r", "size": 1}],
            "outputs": [{"name": "u", "role": "u", "size": 1}],
        },
        interconnection_scheme="two_dof",
        initial_state=[0.25],
        id="ctrl-dyn-01",
        revision=1,
    )
    pdc_ctrl = PDCController(
        K_i=[[[1.0, 2.0]], [[3.0, 4.0]]],
        feedback_sign="negative",
        membership_ref={"model_id": "ts-meas-01", "model_revision": 1, "membership_version": "1.0.0"},
        measurement_requirements={
            "required_premise_variables": ["x1"],
            "requires_full_state": True,
            "allowed_ts_kinds": ["ts_measured"],
        },
        id="ctrl-pdc-01",
        revision=1,
    )
    exp = Experiment(
        method="lqr_care",
        model_ref={"id": ss.id, "revision": ss.revision},
        controller_ref={"id": sf_ctrl.id, "revision": sf_ctrl.revision},
        parameters={"Q": [[1.0, 0.0], [0.0, 1.0]], "R": [[1.0]]},
        tolerances={"rCARE_max": 1e-12},
        results=Result(
            status="success",
            data={"K": [[2.5, 1.75]]},
            provenance=build_provenance("lqr_care", timestamp="2026-11-13T00:00:00Z"),
        ),
        id="exp-01",
        revision=1,
    )
    pvm = make_pvm(ss, sf_ctrl, name="Malha_001")
    return {
        "models": [ss, ss_disc, tf, ds, id_mod, ts_mod, fuzzy],
        "controllers": [sf_ctrl, dyn_ctrl, pdc_ctrl],
        "experiments": [exp],
        "pvm": pvm,
        "dataset": ds,
    }


def _rewrite_zip_with_modified_entry(
    base_zip_bytes: bytes,
    target_name: str,
    new_payload: bytes,
) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base_zip_bytes), "r") as zin, zipfile.ZipFile(
        out, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            data = new_payload if info.filename == target_name else zin.read(info.filename)
            zi = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    return out.getvalue()


# ---------------------------------------------------------------------------
# 1. Round-trip bit-exact & determinístico de .ctrlab + CSV + migração
# ---------------------------------------------------------------------------


def test_ctrlab_bit_exact_deterministic_roundtrip_all_types(
    tmp_path: Path,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    bundle = _make_full_project_items()
    svg_plot = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40"><line x1="0" y1="20" x2="100" y2="20"/></svg>'
    custom_csv = dataset_to_csv(bundle["dataset"])

    kwargs = dict(
        project_id="proj-controllab-01",
        project_revision=7,
        models=bundle["models"],
        controllers=bundle["controllers"],
        experiments=bundle["experiments"],
        datasets={"ensaio_001.csv": custom_csv},
        plots={"step.svg": svg_plot},
        exports={"malha_001.pvm": bundle["pvm"]},
    )

    bytes_a = export_ctrlab_bytes(**kwargs)
    bytes_b = export_ctrlab_bytes(**kwargs)
    assert bytes_a == bytes_b  # 100% determinístico

    out_file = tmp_path / "projeto.ctrlab"
    save_res = save_ctrlab(out_file, **kwargs)
    assert isinstance(save_res, Result)
    assert save_res.status == "success"
    _assert_schema_valid(save_res.to_dict(), "result.schema.json", schema_registry)
    _assert_schema_valid(save_res.data["manifest"], "ctrlab_manifest.schema.json", schema_registry)  # type: ignore[index]
    assert out_file.read_bytes() == bytes_a

    # inspect_ctrlab valida manifest + hashes sem mutar disco
    insp_res = inspect_ctrlab(out_file)
    assert insp_res.status == "success"
    _assert_schema_valid(insp_res.to_dict(), "result.schema.json", schema_registry)
    assert insp_res.data["hashes_verified"] is True  # type: ignore[index]
    assert "datasets/ensaio_001.csv" in insp_res.data["members"]  # type: ignore[index]
    assert "exports/malha_001.pvm" in insp_res.data["members"]  # type: ignore[index]

    # load_ctrlab retorna Result passivo (status warning pois malha_001.pvm tem codeContext não executado)
    load_res = load_ctrlab(out_file)
    assert load_res.status == "warning"
    _assert_schema_valid(load_res.to_dict(), "result.schema.json", schema_registry)
    assert load_res.data["code_executed"] is False  # type: ignore[index]
    assert any(
        (w["code"] if isinstance(w, dict) else w.code) == "UNTRUSTED_CODE_CONTEXT_IGNORED"
        for w in load_res.warnings
    )

    # load_ctrlab_objects restaura instâncias bit-a-bit idênticas
    loaded = load_ctrlab_objects(out_file)
    assert len(loaded["models"]) == len(bundle["models"])
    assert len(loaded["controllers"]) == len(bundle["controllers"])
    assert len(loaded["experiments"]) == len(bundle["experiments"])

    for orig, rest in zip(bundle["models"], loaded["models"]):
        assert type(rest) is type(orig)
        assert serialize_model(rest) == serialize_model(orig)
        if isinstance(orig, StateSpace):
            assert np.array_equal(rest.A, orig.A)
            assert np.array_equal(rest.B, orig.B)
            assert np.array_equal(rest.C, orig.C)
            assert np.array_equal(rest.D, orig.D)
        elif isinstance(orig, Dataset):
            assert np.array_equal(rest.t, orig.t)
            assert np.array_equal(rest.u, orig.u)
            assert np.array_equal(rest.y, orig.y)

    for orig, rest in zip(bundle["controllers"], loaded["controllers"]):
        assert type(rest) is type(orig)
        assert serialize_model(rest) == serialize_model(orig)

    for orig, rest in zip(bundle["experiments"], loaded["experiments"]):
        assert serialize_model(rest) == serialize_model(orig)

    # CSV dataset passivo preservado
    parsed_ds = loaded["datasets"]["datasets/ensaio_001.csv"]["dataset"]
    assert isinstance(parsed_ds, Dataset)
    np.testing.assert_allclose(parsed_ds.t, bundle["dataset"].t, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(parsed_ds.u, bundle["dataset"].u, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(parsed_ds.y, bundle["dataset"].y, rtol=0.0, atol=0.0)
    assert parsed_ds.units == bundle["dataset"].units

    # Exportação de projeto sem PVM resulta em status == "success" limpo
    clean_zip = export_ctrlab_bytes(
        project_id="proj-clean",
        models=[bundle["models"][0]],
        controllers=[bundle["controllers"][0]],
        experiments=[],
    )
    clean_res = load_ctrlab(clean_zip)
    assert clean_res.status == "success"
    assert clean_res.warnings == ()


def test_csv_passive_parser_rejects_formula_or_non_numeric_injection() -> None:
    bad_csv = "t,u1,y1\n0.0,=1+1,0.0\n0.1,1.0,2.0\n"
    with pytest.raises(ValidationError):
        parse_csv_dataset(bad_csv)

    bad_nan_csv = "t,u1,y1\n0.0,NaN,0.0\n0.1,1.0,2.0\n"
    with pytest.raises(ValidationError):
        parse_csv_dataset(bad_nan_csv)


def test_migrate_ctrlab_manifest_pure_and_dry_run(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    legacy_manifest = {
        "format": "ctrlab",
        "version": "0.9.0",
        "created_at": "2026-10-01T12:00:00Z",
        "project_id": "legacy-proj",
        "hashes": {"models.json": "a" * 64, "controllers.json": "b" * 64, "experiments.json": "c" * 64},
    }
    snapshot = copy.deepcopy(legacy_manifest)

    dry = migrate_ctrlab_manifest(legacy_manifest, target_version="1.0.0", dry_run=True)
    assert legacy_manifest == snapshot  # pura, sem mutar entrada
    assert dry["dry_run"] is True
    assert dry["needs_migration"] is True
    assert dry["valid"] is True
    assert len(dry["changes"]) >= 3
    _assert_schema_valid(dry["preview_manifest"], "ctrlab_manifest.schema.json", schema_registry)

    migrated = migrate_ctrlab_manifest(legacy_manifest, target_version="1.0.0", dry_run=False)
    assert legacy_manifest == snapshot
    _assert_schema_valid(migrated, "ctrlab_manifest.schema.json", schema_registry)
    assert migrated["schema_version"] == "1.0.0"
    assert migrated["provenance"]["migrated_from"] == "0.9.0"

    # Idempotente para 1.0.0
    dry_idemp = migrate_ctrlab_manifest(migrated, "1.0.0", dry_run=True)
    assert dry_idemp["needs_migration"] is False
    assert dry_idemp["changes"] == []

    # Versão futura desconhecida rejeitada com SchemaUnsupportedError
    future_manifest = copy.deepcopy(migrated)
    future_manifest["schema_version"] = "2.0.0"
    with pytest.raises(SchemaUnsupportedError):
        migrate_ctrlab_manifest(future_manifest, "1.0.0", dry_run=True)
    with pytest.raises(SchemaUnsupportedError):
        migrate_ctrlab_manifest(migrated, "2.0.0", dry_run=False)


# ---------------------------------------------------------------------------
# 2. T-IO-01: Segurança e integridade .ctrlab
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evil_member",
    [
        "../evil_outside.txt",
        "datasets/../../evil_outside.txt",
        "/tmp/evil_abs.txt",
        "C:\\evil_win.txt",
        "datasets\\..\\evil_backslash.txt",
        "./models.json",
        "datasets/bad\x00name.csv",
    ],
)
def test_t_io_01_ctrlab_rejects_path_traversal_without_creating_files(
    tmp_path: Path, evil_member: str
) -> None:
    work_dir = tmp_path / "sandbox"
    work_dir.mkdir()
    before_entries = set(work_dir.rglob("*"))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(evil_member, b"evil")
    raw = buf.getvalue()

    res = load_ctrlab(raw)
    assert res.status == "failure"
    assert res.error is not None
    assert res.error.code == "VALIDATION_ERROR"

    with pytest.raises(ValidationError):
        load_ctrlab(raw, raise_on_error=True)

    # Nenhum arquivo ou diretório foi criado no sistema de arquivos
    assert set(work_dir.rglob("*")) == before_entries
    assert not (tmp_path / "evil_outside.txt").exists()


def test_t_io_01_ctrlab_rejects_symlink_unicode_nfc_and_casefold_collisions() -> None:
    base_zip = export_ctrlab_bytes(project_id="sec-test")

    # 1) Symlink dentro do ZIP
    buf_sym = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zin, zipfile.ZipFile(buf_sym, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        sym_info = zipfile.ZipInfo("datasets/link.csv")
        sym_info.create_system = 3
        sym_info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zout.writestr(sym_info, b"/etc/passwd")
    with pytest.raises(ValidationError):
        load_ctrlab(buf_sym.getvalue(), raise_on_error=True)

    # 2) Colisão após normalização Unicode NFC (NFD vs NFC)
    buf_nfc = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zin, zipfile.ZipFile(buf_nfc, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        zout.writestr("datasets/caf\u00e9.csv", b"t,u1,y1\n0,1,2\n")
        zout.writestr("datasets/cafe\u0301.csv", b"t,u1,y1\n0,1,2\n")
    with pytest.raises(ValidationError):
        load_ctrlab(buf_nfc.getvalue(), raise_on_error=True)

    # 3) Colisão case-folded
    buf_cf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zin, zipfile.ZipFile(buf_cf, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        zout.writestr("Models.JSON", b"{}")
    with pytest.raises(ValidationError):
        load_ctrlab(buf_cf.getvalue(), raise_on_error=True)

    # 4) Entrada duplicada idêntica no ZIP
    buf_dup = io.BytesIO()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(buf_dup, "w") as zout:
            zout.writestr("manifest.json", b"{}")
            zout.writestr("manifest.json", b"{}")
    with pytest.raises(ValidationError):
        load_ctrlab(buf_dup.getvalue(), raise_on_error=True)


def test_t_io_01_ctrlab_anti_zip_bomb_including_forged_header() -> None:
    # 1) Bomba de compressão detectada pelos limites padrão (> 2 MiB com razão > 500x)
    buf_bomb = io.BytesIO()
    with zipfile.ZipFile(buf_bomb, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("manifest.json", b"{}")
        zf.writestr("payload.bin", b"A" * (3 * 1024 * 1024))
    res_bomb = load_ctrlab(buf_bomb.getvalue())
    assert res_bomb.status == "failure"
    assert res_bomb.error is not None
    assert res_bomb.error.code == "RESOURCE_LIMIT"

    # 2a) Bomba por razão de compressão mesmo abaixo de 64 MiB (e com limite customizado de razão)
    base_zip = export_ctrlab_bytes(project_id="forged-header")
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zin:
        valid_manifest_bytes = zin.read("manifest.json")
    buf_ratio = io.BytesIO()
    with zipfile.ZipFile(buf_ratio, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("manifest.json", valid_manifest_bytes)
        zf.writestr("big.bin", b"0" * 65536)
    with pytest.raises(ResourceLimitError):
        load_ctrlab(
            buf_ratio.getvalue(),
            max_compression_ratio=20.0,
            min_bytes_for_ratio=4096,
            raise_on_error=True,
        )

    # 2b) Cabeçalho forjado (file_size mentindo 10 bytes quando o stream real tem 64 KiB):
    # nunca descomprime 64 KiB em memória e rejeita com erro tipado (ValidationError/ResourceLimitError)
    raw_forged = bytearray(buf_ratio.getvalue())
    needle = (65536).to_bytes(4, "little")
    replacement = (10).to_bytes(4, "little")
    assert needle in raw_forged
    forged_bytes = bytes(raw_forged).replace(needle, replacement)
    with pytest.raises((ResourceLimitError, ValidationError)):
        load_ctrlab(
            forged_bytes,
            max_uncompressed_bytes=8192,
            max_member_bytes=8192,
            raise_on_error=True,
        )

    # 2c) Cabeçalho forjado diretamente no próprio manifest.json também rejeitado sem alocação excessiva
    buf_forged_m = io.BytesIO()
    with zipfile.ZipFile(buf_forged_m, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", b" " * 65536)
    raw_fm = bytes(buf_forged_m.getvalue()).replace(needle, replacement)
    with pytest.raises((ResourceLimitError, ValidationError)):
        load_ctrlab(raw_fm, max_member_bytes=4096, raise_on_error=True)

    # 3) Excesso de membros
    buf_many = io.BytesIO()
    with zipfile.ZipFile(buf_many, "w") as zf:
        for i in range(10):
            zf.writestr(f"f{i}.txt", b"x")
    with pytest.raises(ResourceLimitError):
        load_ctrlab(buf_many.getvalue(), max_members=5, raise_on_error=True)


def test_t_io_01_ctrlab_integrity_hashes_nan_and_future_schema_version() -> None:
    base_zip = export_ctrlab_bytes(
        project_id="integrity-test",
        models=[StateSpace([[-1.0]], [[1.0]], [[1.0]], [[0.0]])],
    )

    # 1) Adulteração de 1 byte em models.json quebrando SHA-256
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zf:
        models_raw = zf.read("models.json")
        manifest_obj = json.loads(zf.read("manifest.json").decode("utf-8"))
    tampered = _rewrite_zip_with_modified_entry(
        base_zip, "models.json", models_raw.replace(b"-1.0", b"-2.0")
    )
    res_tampered = load_ctrlab(tampered)
    assert res_tampered.status == "failure"
    assert res_tampered.error is not None
    assert res_tampered.error.code == "VALIDATION_ERROR"

    # 2) Versão futura desconhecida em manifest.json -> SchemaUnsupportedError
    future_manifest = copy.deepcopy(manifest_obj)
    future_manifest["schema_version"] = "2.0.0"
    future_zip = _rewrite_zip_with_modified_entry(
        base_zip,
        "manifest.json",
        json.dumps(future_manifest).encode("utf-8"),
    )
    res_future = load_ctrlab(future_zip)
    assert res_future.status == "failure"
    assert res_future.error is not None
    assert res_future.error.code == "SCHEMA_UNSUPPORTED"
    with pytest.raises(SchemaUnsupportedError):
        load_ctrlab(future_zip, raise_on_error=True)

    # 3) NaN no JSON interno -> ValidationError
    nan_zip = _rewrite_zip_with_modified_entry(
        base_zip,
        "models.json",
        models_raw.replace(b"-1.0", b"NaN"),
    )
    with pytest.raises(ValidationError):
        load_ctrlab(nan_zip, raise_on_error=True)


def test_ctrlab_passive_import_never_executes_embedded_scripts_or_svg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "EXECUTED_SENTINEL.txt"
    evil_py = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('pwned')\n"
    evil_svg = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    base_zip = export_ctrlab_bytes(
        project_id="passive-scripts",
        plots={"evil.svg": evil_svg},
    )
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zf:
        manifest_obj = json.loads(zf.read("manifest.json").decode("utf-8"))
    import hashlib

    py_bytes = evil_py.encode("utf-8")
    manifest_obj["hashes"]["artifacts/evil.py"] = hashlib.sha256(py_bytes).hexdigest()
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zin, zipfile.ZipFile(buf, "w") as zout:
        for info in zin.infolist():
            if info.filename == "manifest.json":
                zout.writestr("manifest.json", json.dumps(manifest_obj).encode("utf-8"))
            else:
                zout.writestr(info.filename, zin.read(info.filename))
        zout.writestr("artifacts/evil.py", py_bytes)

    def _forbid(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("exec/eval nunca deve ser chamado na importação passiva!")

    monkeypatch.setattr(builtins, "eval", _forbid)
    monkeypatch.setattr(builtins, "exec", _forbid)

    res = load_ctrlab(buf.getvalue())
    assert res.status == "warning"
    assert res.data["code_executed"] is False  # type: ignore[index]
    codes = {w["code"] if isinstance(w, dict) else w.code for w in res.warnings}
    assert "UNTRUSTED_EMBEDDED_FILE_IGNORED" in codes
    assert "UNTRUSTED_SVG_CONTENT_DETECTED" in codes
    assert not sentinel.exists()


# ---------------------------------------------------------------------------
# 3. T-IO-02: Importação 100% passiva .pvm (zero execução codeContext/eval)
# ---------------------------------------------------------------------------


def test_t_io_02_pvm_passive_import_never_executes_code_context_or_eval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    sentinel = tmp_path / "PVM_CODE_EXECUTED.txt"
    ss = StateSpace([[0.0, 1.0], [-2.0, -3.0]], [[0.0], [1.0]], [[1.0, 0.0]], [[0.0]])
    ctrl = StateFeedbackController([[1.0, 1.0]], feedback_sign="negative")
    pvm = make_pvm(ss, ctrl)
    pvm["codeContext"]["code"] = (
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('pwned')\n"
        "raise RuntimeError('MUST NEVER EXECUTE')\n"
    )
    pvm_file = tmp_path / "malicious.pvm"
    pvm_file.write_text(json.dumps(pvm), encoding="utf-8")

    def _forbid(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("exec/eval proibido durante importação/simulação .pvm!")

    monkeypatch.setattr(builtins, "eval", _forbid)
    monkeypatch.setattr(builtins, "exec", _forbid)

    res = import_pvm(pvm_file)
    assert res.status == "warning"
    _assert_schema_valid(res.to_dict(), "result.schema.json", schema_registry)
    assert res.data["code_executed"] is False  # type: ignore[index]
    assert res.diagnostics["code_executed"] is False
    assert res.assumptions["code_executed"] is False
    assert any(
        (w["code"] if isinstance(w, dict) else w.code) == "UNTRUSTED_CODE_CONTEXT_IGNORED"
        for w in res.warnings
    )
    assert not sentinel.exists()

    # Mesmo com código malicioso em codeContext, simulate_pvm_graph reconstrói apenas do grafo e não executa código
    t = np.linspace(0.0, 1.0, 21)
    sim = simulate_pvm_graph(pvm_file, t)
    assert sim.status in ("success", "warning")
    assert sim.diagnostics["code_executed"] is False
    assert not sentinel.exists()

    # Parâmetro string malicioso em params: import_pvm não avalia e simulate/extract bloqueia com ImportUntrustedCodeError
    pvm_expr = copy.deepcopy(pvm)
    for node in pvm_expr["graph"]["nodes"]:
        if node["id"] == "gain_K":
            node["params"]["func"] = "__import__('os').system('echo pwned')"
            break
    res_expr = import_pvm(pvm_expr)
    assert res_expr.status == "warning"
    assert any(
        (w["code"] if isinstance(w, dict) else w.code) == "UNTRUSTED_PARAM_EXPRESSION_IGNORED"
        for w in res_expr.warnings
    )
    with pytest.raises(ImportUntrustedCodeError):
        extract_lti_from_pvm(pvm_expr)


def test_t_io_02_pvm_rejects_nan_future_version_fanin_and_overlapping_positions() -> None:
    ss = StateSpace([[-1.0]], [[1.0]], [[1.0]], [[0.0]])
    pvm = make_pvm(ss)

    # NaN rejeitado
    bad_nan_json = json.dumps(pvm).replace("-1.0", "NaN")
    with pytest.raises(ValidationError):
        import_pvm(bad_nan_json, raise_on_error=True)

    # Versão futura rejeitada com SchemaUnsupportedError
    pvm_v2 = copy.deepcopy(pvm)
    pvm_v2["version"] = "2.0.0"
    res_v2 = import_pvm(pvm_v2)
    assert res_v2.status == "failure"
    assert res_v2.error is not None and res_v2.error.code == "SCHEMA_UNSUPPORTED"

    # Fan-in proibido rejeitado
    pvm_fanin = copy.deepcopy(pvm)
    pvm_fanin["graph"]["connections"].append(
        {
            "id": "conn_fanin",
            "sourceNodeId": "src_u",
            "sourcePortIndex": 0,
            "targetNodeId": "plant_ss",
            "targetPortIndex": 0,
        }
    )
    with pytest.raises(ValidationError):
        validate_pvm_structure(pvm_fanin)

    # Posição sobreposta rejeitada
    pvm_overlap = copy.deepcopy(pvm)
    pvm_overlap["graph"]["nodes"][1]["position"] = copy.deepcopy(
        pvm_overlap["graph"]["nodes"][0]["position"]
    )
    with pytest.raises(ValidationError):
        validate_pvm_structure(pvm_overlap)


# ---------------------------------------------------------------------------
# 4. T-PVM-01: Exportação .pvm, C=I vs C!=I, m!=p, sinais e saturação B-PVM-LQR
# ---------------------------------------------------------------------------


def test_t_pvm_01_b_pvm_lqr_c_eq_i_and_c_neq_i_and_prefilter_and_signs(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # Transparência Gate G-0D
    assert PATHVIEW_SPEC_VERSION == "1.0.0"
    assert PATHVIEW_BLOCK_REGISTRY["external_pathview_verified"] is False
    assert PATHVIEW_BLOCK_REGISTRY["gate_status"] == "PENDING_G0D"

    # Caso 1: B-CARE-02 (duplo integrador) com C = I e C != I
    fx = json.loads((FIXTURES_DIR / "B-CARE-02.json").read_text(encoding="utf-8"))
    d = fx["data"]
    A = tensor_to_array(d["A"])
    B = tensor_to_array(d["B"])
    K = tensor_to_array(d["expected"]["K"])
    x0 = tensor_to_array(d["x0"])

    # 1a) C = I
    plant_ci = StateSpace(A, B, np.eye(2), np.zeros((2, 1)), dt=None, id="b-pvm-lqr-ci", revision=1)
    # 1b) C != I (somente x1 observado na saída y, mas realimentação usa x completo [x1, x2])
    C_partial = np.array([[1.0, 0.0]])
    D_nonzero = np.array([[0.25]])
    plant_cneq = StateSpace(A, B, C_partial, D_nonzero, dt=None, id="b-pvm-lqr-cneq", revision=1)

    for sign in ("negative", "positive"):
        K_signed = K if sign == "negative" else -K
        ctrl = StateFeedbackController(K=K_signed, feedback_sign=sign, dt=None)

        for plant in (plant_ci, plant_cneq):
            exp_res = export_pvm(plant, ctrl, scenario={"initial_state": x0, "reference": {"type": "zero"}})
            assert exp_res.status == "warning"
            assert exp_res.diagnostics["external_pathview_verified"] is False
            assert exp_res.diagnostics["gate_pending"] == "G-0D"
            assert any(
                (w["code"] if isinstance(w, dict) else w.code) == "EXTERNAL_PATHVIEW_NOT_VERIFIED"
                for w in exp_res.warnings
            )
            _assert_schema_valid(exp_res.to_dict(), "result.schema.json", schema_registry)
            pvm = exp_res.data["pvm"]  # type: ignore[index]
            _assert_schema_valid(pvm, "pvm.schema.json", schema_registry)

            # ABI oficial: canais escalares y seguidos dos estados x, nunca realimentar apenas y.
            plant_node = next(n for n in pvm["graph"]["nodes"] if n["type"] == "StateSpace")
            assert len(plant_node["outputs"]) == plant.n_outputs + plant.n_states
            assert plant_node["outputs"][plant.n_outputs]["name"] == "x0"
            conn_to_k = next(c for c in pvm["graph"]["connections"] if c["targetNodeId"] == "gain_K")
            assert conn_to_k["sourceNodeId"] == "plant_ss"
            assert conn_to_k["sourcePortIndex"] == plant.n_outputs

            # Verificar sinais explícitos do Adder
            adder_node = next(n for n in pvm["graph"]["nodes"] if n["type"] == "Adder")
            expected_sign_char = "-" if sign == "negative" else "+"
            assert adder_node["params"]["operations"] == repr("+" + expected_sign_char)

            # Equivalência exata com interconnect + simulate_lti
            cl_expected = interconnect(plant, ctrl)
            cl_from_pvm = extract_lti_from_pvm(pvm)
            np.testing.assert_allclose(cl_from_pvm.A, cl_expected.A, atol=1e-13)
            np.testing.assert_allclose(cl_from_pvm.B, cl_expected.B, atol=1e-13)
            np.testing.assert_allclose(cl_from_pvm.C, cl_expected.C, atol=1e-13)
            np.testing.assert_allclose(cl_from_pvm.D, cl_expected.D, atol=1e-13)

            t = np.linspace(0.0, 5.0, 51)
            r_zero = np.zeros((t.size, 1))
            sim_pvm = simulate_pvm_graph(pvm, t, r=r_zero)
            sim_ref = simulate_lti(cl_expected, t, u=r_zero, x0=x0)
            np.testing.assert_allclose(
                tensor_to_array(sim_pvm.data["x"]),  # type: ignore[index]
                tensor_to_array(sim_ref.data["x"]),  # type: ignore[index]
                atol=1e-11,
            )
            np.testing.assert_allclose(
                tensor_to_array(sim_pvm.data["y"]),  # type: ignore[index]
                tensor_to_array(sim_ref.data["y"]),  # type: ignore[index]
                atol=1e-11,
            )

    # Caso 2: Planta não quadrada m != p com prefiltro N (shape m x p_ref)
    plant_nonsq = StateSpace(
        A=[[-1.0, 0.2], [0.0, -2.0]],
        B=[[1.0, 0.0], [0.0, 1.0]],  # m = 2
        C=[[1.0, 1.0]],               # p = 1
        D=[[0.0, 0.1]],
        dt=None,
    )
    N = np.array([[2.0], [1.5]])  # shape (m=2, p=1)
    ctrl_nonsq = StateFeedbackController(
        K=[[0.5, 0.1], [0.2, 0.8]],
        feedback_sign="negative",
        reference_map={"kind": "output_prefilter", "matrix": N, "reference_names": ["r_y"]},
    )
    pvm_ns = make_pvm(plant_nonsq, ctrl_nonsq)
    _assert_schema_valid(pvm_ns, "pvm.schema.json", schema_registry)
    assert any(n["id"] == "gain_N" and n["type"] == "Function" for n in pvm_ns["graph"]["nodes"])

    cl_ns_expected = interconnect(plant_nonsq, ctrl_nonsq)
    cl_ns_pvm = extract_lti_from_pvm(pvm_ns)
    np.testing.assert_allclose(cl_ns_pvm.A, cl_ns_expected.A, atol=1e-13)
    np.testing.assert_allclose(cl_ns_pvm.B, cl_ns_expected.B, atol=1e-13)
    np.testing.assert_allclose(cl_ns_pvm.C, cl_ns_expected.C, atol=1e-13)
    np.testing.assert_allclose(cl_ns_pvm.D, cl_ns_expected.D, atol=1e-13)

    t_ns = np.linspace(0.0, 4.0, 41)
    r_step = np.ones((t_ns.size, 1)) * 1.5
    sim_ns_pvm = simulate_pvm_graph(pvm_ns, t_ns, r=r_step, x0=[0.1, -0.2])
    sim_ns_ref = simulate_lti(cl_ns_expected, t_ns, u=r_step, x0=[0.1, -0.2])
    np.testing.assert_allclose(
        tensor_to_array(sim_ns_pvm.data["y"]),  # type: ignore[index]
        tensor_to_array(sim_ns_ref.data["y"]),  # type: ignore[index]
        atol=1e-11,
    )


def test_t_pvm_01_b_pvm_lqr_saturation_on_and_off(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    A = np.array([[0.0, 1.0], [0.0, 0.0]])
    B = np.array([[0.0], [1.0]])
    C = np.array([[1.0, 0.0]])
    D = np.array([[0.0]])
    K = np.array([[2.0, 3.0]])
    x0 = np.array([3.0, 0.0])  # u(0) = -2*3 = -6, fortemente saturado por [-1, 1]

    plant = StateSpace(A, B, C, D, dt=None, id="b-pvm-lqr", revision=1)
    ctrl = StateFeedbackController(K=K, feedback_sign="negative")

    # Saturação DESABILITADA (off) -> equivalente exato ao linear
    pvm_sat_off = make_pvm(
        plant,
        ctrl,
        scenario={
            "initial_state": x0,
            "saturation": {"enabled": False, "u_min": -1.0, "u_max": 1.0},
        },
    )
    _assert_schema_valid(pvm_sat_off, "pvm.schema.json", schema_registry)
    sat_node_off = next(n for n in pvm_sat_off["graph"]["nodes"] if n["id"] == "actuator_sat")
    assert sat_node_off["type"] == "Function"
    assert sat_node_off["controlLab"]["legacy_node"]["params"]["enabled"] is False

    t = np.linspace(0.0, 6.0, 121)
    r_zero = np.zeros((t.size, 1))
    sim_off = simulate_pvm_graph(pvm_sat_off, t, r=r_zero)
    sim_lin = simulate_lti(interconnect(plant, ctrl), t, u=r_zero, x0=x0)
    x_off = tensor_to_array(sim_off.data["x"])  # type: ignore[index]
    x_lin = tensor_to_array(sim_lin.data["x"])  # type: ignore[index]
    u_off = tensor_to_array(sim_off.data["u"])  # type: ignore[index]
    np.testing.assert_allclose(x_off, x_lin, atol=1e-11)
    assert float(np.max(np.abs(u_off))) > 5.0

    # Saturação HABILITADA (on) -> |u| <= 1.0 e confere com integrador independente solve_ivp
    pvm_sat_on = make_pvm(
        plant,
        ctrl,
        scenario={
            "initial_state": x0,
            "saturation": {"enabled": True, "u_min": -1.0, "u_max": 1.0},
        },
    )
    _assert_schema_valid(pvm_sat_on, "pvm.schema.json", schema_registry)
    sat_node_on = next(n for n in pvm_sat_on["graph"]["nodes"] if n["id"] == "actuator_sat")
    assert sat_node_on["type"] == "Clip"
    assert sat_node_on["controlLab"]["legacy_node"]["params"]["enabled"] is True

    with pytest.raises(UnsupportedModelError):
        extract_lti_from_pvm(pvm_sat_on)

    sim_on = simulate_pvm_graph(pvm_sat_on, t, r=r_zero, rtol=1e-9, atol=1e-12)
    assert sim_on.status == "warning"  # aviso passivo sobre codeContext.code não executado
    u_sat_traj = tensor_to_array(sim_on.data["u"])  # type: ignore[index]
    x_on = tensor_to_array(sim_on.data["x"])  # type: ignore[index]
    assert float(np.max(np.abs(u_sat_traj))) <= 1.0 + 1e-12

    # Referência independente direta da EDO saturada
    def _ref_rhs(_tau: float, x_v: np.ndarray) -> np.ndarray:
        u_cmd = -K @ x_v
        u_clipped = np.clip(u_cmd, -1.0, 1.0)
        return A @ x_v + B @ u_clipped

    sol_ref = scipy.integrate.solve_ivp(_ref_rhs, (0.0, 6.0), x0, method="RK45", t_eval=t, rtol=1e-9, atol=1e-12)
    assert sol_ref.success
    np.testing.assert_allclose(x_on, sol_ref.y.T, atol=1e-7)
    assert float(np.max(np.abs(x_on - x_off))) > 0.2


# ---------------------------------------------------------------------------
# 5. T-PVM-02: DynamicController (Dp != 0, Dc != 0, initial_state != 0, esquemas)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["output_feedback", "error_feedback", "two_dof_yr", "two_dof_ry"])
@pytest.mark.parametrize("feedback_sign", ["negative", "positive"])
def test_t_pvm_02_dynamic_controller_nonzero_feedthrough_and_initial_state(
    scheme: str,
    feedback_sign: str,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    plant = StateSpace(
        A=[[-1.2, 0.3], [-0.4, -2.5]],
        B=[[1.0], [0.5]],
        C=[[1.5, -0.5]],
        D=[[0.4]],  # Dp != 0
        dt=None,
        id="plant-dp",
        revision=1,
    )
    xp0 = np.array([0.5, -0.3], dtype=np.float64)
    xc0 = np.array([-0.8], dtype=np.float64)  # initial_state != 0

    if scheme == "output_feedback":
        ctrl = DynamicController(
            Ac=[[-3.0]],
            Bc=[[1.0]],
            Cc=[[1.2]],
            Dc=[[0.3]],  # Dc != 0
            feedback_sign=feedback_sign,
            ports={"inputs": [{"name": "y", "role": "y", "size": 1}], "outputs": [{"name": "u", "role": "u", "size": 1}]},
            interconnection_scheme="output_feedback",
            initial_state=xc0,
        )
    elif scheme == "error_feedback":
        ctrl = DynamicController(
            Ac=[[-2.5]],
            Bc=[[1.5]],
            Cc=[[0.9]],
            Dc=[[0.25]],
            feedback_sign=feedback_sign,
            ports={"inputs": [{"name": "e", "role": "error", "size": 1}], "outputs": [{"name": "u", "role": "u", "size": 1}]},
            interconnection_scheme="error_feedback",
            initial_state=xc0,
        )
    elif scheme == "two_dof_yr":
        ctrl = DynamicController(
            Ac=[[-2.8]],
            Bc=[[0.8, 1.4]],
            Cc=[[1.1]],
            Dc=[[0.2, 0.6]],
            feedback_sign=feedback_sign,
            ports={
                "inputs": [{"name": "y", "role": "y", "size": 1}, {"name": "r", "role": "r", "size": 1}],
                "outputs": [{"name": "u", "role": "u", "size": 1}],
            },
            interconnection_scheme="two_dof",
            initial_state=xc0,
        )
    else:  # two_dof com ordem invertida [r, y]
        ctrl = DynamicController(
            Ac=[[-2.8]],
            Bc=[[1.4, 0.8]],
            Cc=[[1.1]],
            Dc=[[0.6, 0.2]],
            feedback_sign=feedback_sign,
            ports={
                "inputs": [{"name": "r", "role": "r", "size": 1}, {"name": "y", "role": "y", "size": 1}],
                "outputs": [{"name": "u", "role": "u", "size": 1}],
            },
            interconnection_scheme="two_dof",
            initial_state=xc0,
        )

    pvm = make_pvm(plant, ctrl, scenario={"initial_state": xp0})
    _assert_schema_valid(pvm, "pvm.schema.json", schema_registry)

    # Controlador completo usa StateSpace oficial, preservando estado e feedthrough.
    dyn_nodes = [n for n in pvm["graph"]["nodes"] if n["id"] == "ctrl_dynamic"]
    assert len(dyn_nodes) == 1 and dyn_nodes[0]["type"] == "StateSpace"
    assert dyn_nodes[0]["params"]["initial_value"] == "np.array([-0.8], dtype=float)"
    assert dyn_nodes[0]["controlLab"]["legacy_node"]["params"]["initial_state"] == pytest.approx(xc0.tolist())

    # Equivalência estrutural exata de matrizes aumentadas
    cl_ref = interconnect(plant, ctrl)
    cl_pvm = extract_lti_from_pvm(pvm)
    assert cl_pvm.n_states == 3
    np.testing.assert_allclose(cl_pvm.A, cl_ref.A, atol=1e-13)
    np.testing.assert_allclose(cl_pvm.B, cl_ref.B, atol=1e-13)
    np.testing.assert_allclose(cl_pvm.C, cl_ref.C, atol=1e-13)
    np.testing.assert_allclose(cl_pvm.D, cl_ref.D, atol=1e-13)

    # Equivalência de trajetórias com initial_state != 0 e referência variante
    t = np.linspace(0.0, 3.0, 61)
    r_sig = 1.0 + 0.5 * np.sin(2.0 * t)
    sim_pvm = simulate_pvm_graph(pvm, t, r=r_sig)
    sim_ref = simulate_lti(cl_ref, t, u=r_sig, x0=np.concatenate([xp0, xc0]))

    x_pvm = tensor_to_array(sim_pvm.data["x"])  # type: ignore[index]
    x_plant_pvm = tensor_to_array(sim_pvm.data["x_plant"])  # type: ignore[index]
    x_ctrl_pvm = tensor_to_array(sim_pvm.data["x_controller"])  # type: ignore[index]
    y_pvm = tensor_to_array(sim_pvm.data["y"])  # type: ignore[index]
    x_ref = tensor_to_array(sim_ref.data["x"])  # type: ignore[index]
    y_ref = tensor_to_array(sim_ref.data["y"])  # type: ignore[index]

    np.testing.assert_allclose(x_pvm, x_ref, atol=1e-10)
    np.testing.assert_allclose(x_plant_pvm, x_ref[:, :2], atol=1e-10)
    np.testing.assert_allclose(x_ctrl_pvm, x_ref[:, 2:], atol=1e-10)
    np.testing.assert_allclose(y_pvm, y_ref, atol=1e-10)


def test_t_pvm_02_discrete_and_ill_posed_algebraic_loop_rejected() -> None:
    # Loop algébrico mal posto: 1 - (-1)*(-1)*(1) = 0 -> rejeitado antes de exportar
    plant_bad = StateSpace([[0.5]], [[1.0]], [[1.0]], [[1.0]], dt=0.1)
    ctrl_bad = DynamicController(
        Ac=[[0.2]],
        Bc=[[1.0]],
        Cc=[[1.0]],
        Dc=[[-1.0]],
        feedback_sign="negative",
        dt=0.1,
    )
    with pytest.raises(HypothesisViolatedError):
        make_pvm(plant_bad, ctrl_bad)

    # Discreto bem posto com saturação
    plant_d = StateSpace([[0.8]], [[0.2]], [[1.0]], [[0.1]], dt=0.1)
    ctrl_d = DynamicController(
        Ac=[[0.5]],
        Bc=[[0.4]],
        Cc=[[0.6]],
        Dc=[[0.2]],
        feedback_sign="negative",
        dt=0.1,
        initial_state=[0.3],
    )
    pvm_d = make_pvm(plant_d, ctrl_d, scenario={"initial_state": [1.0]})
    assert pvm_d["metadata"]["adapter_profile"] == "controllab.pathview.clocked.v2"
    legacy_d = make_pvm(plant_d, ctrl_d, scenario={"initial_state": [1.0]}, runtime_profile="legacy_numeric")
    assert legacy_d["metadata"]["external_compatible"] is False
    cl_d_ref = interconnect(plant_d, ctrl_d)
    cl_d_pvm = extract_lti_from_pvm(pvm_d)
    np.testing.assert_allclose(cl_d_pvm.A, cl_d_ref.A, atol=1e-13)
    t_d = np.arange(0, 10) * 0.1
    r_d = np.ones((10, 1))
    sim_d_pvm = simulate_pvm_graph(pvm_d, t_d, r=r_d)
    sim_d_ref = simulate_lti(cl_d_ref, t_d, u=r_d, x0=[1.0, 0.3])
    np.testing.assert_allclose(
        tensor_to_array(sim_d_pvm.data["x"]),  # type: ignore[index]
        tensor_to_array(sim_d_ref.data["x"]),  # type: ignore[index]
        atol=1e-12,
    )
    np.testing.assert_allclose(
        tensor_to_array(sim_d_pvm.data["y"]),  # type: ignore[index]
        tensor_to_array(sim_d_ref.data["y"]),  # type: ignore[index]
        atol=1e-12,
    )


# ---------------------------------------------------------------------------
# 6. DEC-OPEN-07: rejeição transparente em .pvm e fallback generate_pathsim_script
# ---------------------------------------------------------------------------


def test_dec_open_07_rejects_ts_pdc_fuzzy_in_pvm_and_provides_pathsim_script(
    tmp_path: Path,
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]],
) -> None:
    bundle = _make_full_project_items()
    ts_meas = next(m for m in bundle["models"] if isinstance(m, TSStateSpace))
    fuzzy = next(m for m in bundle["models"] if isinstance(m, FuzzySystem))
    pdc = next(c for c in bundle["controllers"] if isinstance(c, PDCController))
    ss = bundle["models"][0]
    tf = next(m for m in bundle["models"] if isinstance(m, TransferFunction))

    for bad_plant, bad_ctrl in (
        (ts_meas, pdc),
        (ts_meas, None),
        (fuzzy, None),
        (ss, pdc),
        (tf, None),
    ):
        with pytest.raises(UnsupportedModelError) as exc_info:
            make_pvm(bad_plant, bad_ctrl)
        if bad_plant is not tf:
            assert "DEC-OPEN-07" in exc_info.value.message
            assert "generate_pathsim_script" in (exc_info.value.next_step or "")

        res_exp = export_pvm(bad_plant, bad_ctrl)
        assert res_exp.status == "failure"
        assert res_exp.error is not None
        assert res_exp.error.code == "UNSUPPORTED_MODEL"

    # generate_pathsim_script funciona como fallback (e sem executar código!)
    res_ts_script = generate_pathsim_script(ts_meas, pdc)
    assert res_ts_script.status == "warning"
    _assert_schema_valid(res_ts_script.to_dict(), "result.schema.json", schema_registry)
    assert res_ts_script.data["requires_explicit_user_execution"] is True  # type: ignore[index]
    assert res_ts_script.data["code_executed"] is False  # type: ignore[index]
    assert "def ts_pdc_rhs" in res_ts_script.data["script"]  # type: ignore[index]

    res_fz_script = generate_pathsim_script(fuzzy)
    assert res_fz_script.status == "warning"
    assert "fuzzy_spec" in res_fz_script.data["script"]  # type: ignore[index]

    # Segurança: polytopic_uncertain + PDC continua bloqueado mesmo em generate_pathsim_script
    ts_poly = ts_meas.with_revision(
        kind="polytopic_uncertain",
        premise_availability={"mode": "unknown_uncertain", "measured_premises": [], "unmeasured_premises": ["x1"]},
    )
    res_poly = generate_pathsim_script(ts_poly, pdc)
    assert res_poly.status == "failure"
    assert res_poly.error is not None
    assert res_poly.error.code == "HYPOTHESIS_VIOLATED"

    # export_pvm para arquivo
    pvm_out = tmp_path / "exported.pvm"
    res_file = export_pvm(ss, bundle["controllers"][0], output_path=pvm_out)
    assert res_file.status == "warning"
    assert pvm_out.exists()
    loaded_back = load_pvm(pvm_out)
    assert loaded_back["version"] == "1.0.0"


def test_b_care_12x3_mimo_pvm_and_ctrlab_stream_and_tsv_and_zero_state_dyn(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # 1) B-CARE-12x3 MIMO (12 estados, 3 entradas, 3 saídas) em .pvm e .ctrlab
    fx12 = json.loads((FIXTURES_DIR / "B-CARE-12x3.json").read_text(encoding="utf-8"))
    d12 = fx12["data"]
    A12 = tensor_to_array(d12["A"])
    B12 = tensor_to_array(d12["B"])
    C12 = tensor_to_array(d12["C"])
    D12 = tensor_to_array(d12["D"])
    K12 = tensor_to_array(d12["expected"]["K"])
    x0_12 = tensor_to_array(d12["x0"])

    plant12 = StateSpace(A12, B12, C12, D12, dt=None, id="care-12x3", revision=1)
    N12 = np.array([[1.0, 0.2, 0.0], [0.0, 1.5, -0.3], [0.1, 0.0, 2.0]])
    ctrl12 = StateFeedbackController(K=K12, feedback_sign="negative", reference_map=N12)
    pvm12 = make_pvm(plant12, ctrl12, scenario={"initial_state": x0_12})
    _assert_schema_valid(pvm12, "pvm.schema.json", schema_registry)

    cl12_ref = interconnect(plant12, ctrl12)
    cl12_pvm = extract_lti_from_pvm(pvm12)
    np.testing.assert_allclose(cl12_pvm.A, cl12_ref.A, atol=1e-12)
    np.testing.assert_allclose(cl12_pvm.B, cl12_ref.B, atol=1e-12)
    np.testing.assert_allclose(cl12_pvm.C, cl12_ref.C, atol=1e-12)
    np.testing.assert_allclose(cl12_pvm.D, cl12_ref.D, atol=1e-12)

    t12 = np.linspace(0.0, 2.0, 21)
    r12 = np.column_stack([np.ones(21), 0.5 * np.ones(21), -0.2 * np.ones(21)])
    sim12_pvm = simulate_pvm_graph(pvm12, t12, r=r12)
    sim12_ref = simulate_lti(cl12_ref, t12, u=r12, x0=x0_12)
    np.testing.assert_allclose(
        tensor_to_array(sim12_pvm.data["y"]),  # type: ignore[index]
        tensor_to_array(sim12_ref.data["y"]),  # type: ignore[index]
        atol=1e-10,
    )

    # 2) DynamicController com 0 estados (estático em bloco dinâmico) e porta aux extra
    plant_s = StateSpace([[-1.0]], [[1.0]], [[1.0]], [[0.2]], dt=None)
    ctrl_static_dyn = DynamicController(
        Ac=np.zeros((0, 0)),
        Bc=np.zeros((0, 1)),
        Cc=np.zeros((2, 0)),
        Dc=[[0.4], [0.9]],
        feedback_sign="negative",
        ports={
            "inputs": [{"name": "y", "role": "y", "size": 1}],
            "outputs": [{"name": "u", "role": "u", "size": 1}, {"name": "aux", "role": "aux", "size": 1}],
        },
        interconnection_scheme="observer_based",
    )
    pvm_sd = make_pvm(plant_s, ctrl_static_dyn)
    _assert_schema_valid(pvm_sd, "pvm.schema.json", schema_registry)
    cl_sd_ref = interconnect(plant_s, ctrl_static_dyn)
    cl_sd_pvm = extract_lti_from_pvm(pvm_sd)
    np.testing.assert_allclose(cl_sd_pvm.A, cl_sd_ref.A, atol=1e-13)
    np.testing.assert_allclose(cl_sd_pvm.D, cl_sd_ref.D, atol=1e-13)

    # 3) Saturação discreta + leitura de .ctrlab via BytesIO e datasets/*.tsv
    plant_d = StateSpace([[0.9]], [[0.5]], [[1.0]], [[0.0]], dt=0.1)
    with pytest.raises(DimensionMismatchError):
        make_pvm(plant_d, StateFeedbackController([[0.8]], feedback_sign="negative", dt=None))
    ctrl_d = StateFeedbackController([[0.8]], feedback_sign="negative", dt=0.1)
    pvm_dsat = make_pvm(
        plant_d,
        ctrl_d,
        runtime_profile="legacy_numeric",
        scenario={"initial_state": [5.0], "saturation": {"enabled": True, "u_min": -1.0, "u_max": 1.0}},
    )
    sim_dsat = simulate_pvm_graph(pvm_dsat, np.arange(0, 6) * 0.1, r=np.zeros((6, 1)))
    u_dsat = tensor_to_array(sim_dsat.data["u"])  # type: ignore[index]
    assert np.all(np.abs(u_dsat) <= 1.0 + 1e-12)
    assert math.isclose(float(u_dsat[0, 0]), -1.0, abs_tol=1e-12)

    ds_obj = Dataset(t=[0.0, 0.1, 0.2], u=[[1.0], [2.0], [3.0]], y=[[0.5], [1.0], [1.5]], dt=0.1)
    tsv_text = dataset_to_csv(ds_obj, delimiter="\t")
    zip_bytes = export_ctrlab_bytes(
        project_id="stream-tsv",
        models=[plant12],
        controllers=[ctrl12],
        datasets={"ensaio.tsv": tsv_text},
        exports={"care12x3.pvm": pvm12},
    )
    stream = io.BytesIO(zip_bytes)
    insp = inspect_ctrlab(stream)
    assert insp.status == "success"
    stream.seek(0)
    loaded = load_ctrlab(stream)
    assert loaded.status == "warning"
    assert "datasets/ensaio.tsv" in loaded.data["datasets"]  # type: ignore[index]


def test_regression_bug_f1_io_01_corrupted_utf8_and_deflate_typed_errors() -> None:
    import hashlib

    # 1) import_pvm e load_pvm com bytes UTF-8 inválidos -> ValidationError / Result failure
    res_pvm_bad = import_pvm(b"\xff\xfe{}")
    assert res_pvm_bad.status == "failure"
    assert res_pvm_bad.error is not None
    assert res_pvm_bad.error.code == "VALIDATION_ERROR"
    with pytest.raises(ValidationError):
        load_pvm(b"\xff\xfe{}")

    # String path inválida com NUL byte -> ValidationError sem ValueError cru
    res_pvm_nul = import_pvm("bad\x00path.pvm")
    assert res_pvm_nul.status == "failure"
    assert res_pvm_nul.error is not None and res_pvm_nul.error.code == "VALIDATION_ERROR"

    # 2) parse_csv_dataset com UTF-8 inválido -> ValidationError
    with pytest.raises(ValidationError):
        parse_csv_dataset(b"\xff\xfe1,2,3\n")

    # 3) load_ctrlab / inspect_ctrlab com manifest.json em UTF-8 inválido -> Result failure (sem UnicodeDecodeError)
    bad_manifest_zip = io.BytesIO()
    with zipfile.ZipFile(bad_manifest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", b"\xff\xfe{}")
    for fn in (load_ctrlab, inspect_ctrlab):
        res_m = fn(bad_manifest_zip.getvalue())
        assert res_m.status == "failure"
        assert res_m.error is not None
        assert res_m.error.code == "VALIDATION_ERROR"

    # 4) load_ctrlab com models.json em UTF-8 inválido (SHA-256 válido) -> ValidationError
    base_zip = export_ctrlab_bytes(project_id="utf8-bad-member")
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zin:
        manifest_obj = json.loads(zin.read("manifest.json").decode("utf-8"))
        ctrl_bytes = zin.read("controllers.json")
        exp_bytes = zin.read("experiments.json")
    bad_models = b"\xff\xfe[]"
    manifest_obj["hashes"]["models.json"] = hashlib.sha256(bad_models).hexdigest()
    bad_models_zip = io.BytesIO()
    with zipfile.ZipFile(bad_models_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("manifest.json", json.dumps(manifest_obj).encode("utf-8"))
        zout.writestr("models.json", bad_models)
        zout.writestr("controllers.json", ctrl_bytes)
        zout.writestr("experiments.json", exp_bytes)
    res_bad_models = load_ctrlab(bad_models_zip.getvalue())
    assert res_bad_models.status == "failure"
    assert res_bad_models.error is not None and res_bad_models.error.code == "VALIDATION_ERROR"

    # 5) load_ctrlab com datasets/bad.csv em UTF-8 inválido -> ValidationError
    bad_csv_bytes = b"\xff\xfe0,1,2\n"
    manifest_obj_csv = copy.deepcopy(manifest_obj)
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zin:
        orig_models = zin.read("models.json")
    manifest_obj_csv["hashes"]["models.json"] = hashlib.sha256(orig_models).hexdigest()
    manifest_obj_csv["hashes"]["datasets/bad.csv"] = hashlib.sha256(bad_csv_bytes).hexdigest()
    bad_csv_zip = io.BytesIO()
    with zipfile.ZipFile(bad_csv_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("manifest.json", json.dumps(manifest_obj_csv).encode("utf-8"))
        zout.writestr("models.json", orig_models)
        zout.writestr("controllers.json", ctrl_bytes)
        zout.writestr("experiments.json", exp_bytes)
        zout.writestr("datasets/bad.csv", bad_csv_bytes)
    res_bad_csv = load_ctrlab(bad_csv_zip.getvalue())
    assert res_bad_csv.status == "failure"
    assert res_bad_csv.error is not None and res_bad_csv.error.code == "VALIDATION_ERROR"

    # 6) Fluxo DEFLATE corrompido (zlib.error) -> Result failure ValidationError (sem zlib.error cru)
    big_payload = b"ControlLab_Web_DEFLATE_Payload_" * 40
    zlib_zip_buf = io.BytesIO()
    with zipfile.ZipFile(zlib_zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("manifest.json", json.dumps(manifest_obj_csv).encode("utf-8"))
        zout.writestr("models.json", big_payload)
    corrupt_bytes = bytearray(zlib_zip_buf.getvalue())
    with zipfile.ZipFile(io.BytesIO(bytes(corrupt_bytes)), "r") as zchk:
        m_info = zchk.getinfo("models.json")
    # Corromper o corpo comprimido (após cabeçalho local) preservando o cabeçalho ZIP
    corrupt_pos = m_info.header_offset + 30 + len("models.json") + 6
    corrupt_bytes[corrupt_pos] ^= 0xFF
    corrupt_bytes[corrupt_pos + 1] ^= 0xAA
    res_corrupt = load_ctrlab(bytes(corrupt_bytes))
    assert res_corrupt.status == "failure"
    assert res_corrupt.error is not None and res_corrupt.error.code == "VALIDATION_ERROR"
    res_corrupt_insp = inspect_ctrlab(bytes(corrupt_bytes))
    assert res_corrupt_insp.status == "failure"
    assert res_corrupt_insp.error is not None and res_corrupt_insp.error.code == "VALIDATION_ERROR"


def test_regression_bug_f1_io_02_schema_strictness_and_regex_newline() -> None:
    base_zip = export_ctrlab_bytes(project_id="schema-strict")
    with zipfile.ZipFile(io.BytesIO(base_zip), "r") as zin:
        manifest = json.loads(zin.read("manifest.json").decode("utf-8"))

    # modified_at presente com None rejeitado
    m_mod_none = copy.deepcopy(manifest)
    m_mod_none["modified_at"] = None
    with pytest.raises(ValidationError):
        validate_ctrlab_manifest(m_mod_none)

    # schema_version com trailing \n rejeitado (regex \Z)
    m_nl_sv = copy.deepcopy(manifest)
    m_nl_sv["schema_version"] = "1.0.0\n"
    with pytest.raises(SchemaUnsupportedError):
        validate_ctrlab_manifest(m_nl_sv)
    with pytest.raises(SchemaUnsupportedError):
        migrate_ctrlab_manifest(m_nl_sv, "1.0.0")

    # hash SHA-256 com trailing \n rejeitado (regex \Z)
    m_nl_hash = copy.deepcopy(manifest)
    first_key = next(iter(m_nl_hash["hashes"]))
    m_nl_hash["hashes"][first_key] = m_nl_hash["hashes"][first_key] + "\n"
    with pytest.raises(ValidationError):
        validate_ctrlab_manifest(m_nl_hash)

    # created_at com trailing \n rejeitado
    m_nl_ts = copy.deepcopy(manifest)
    m_nl_ts["created_at"] = "2026-11-13T00:00:00Z\n"
    with pytest.raises(ValidationError):
        validate_ctrlab_manifest(m_nl_ts)

    # connection["id"]: None rejeitado em validate_pvm_structure
    ss = StateSpace([[-1.0]], [[1.0]], [[1.0]], [[0.0]])
    pvm = make_pvm(ss)
    pvm_conn_none = copy.deepcopy(pvm)
    pvm_conn_none["graph"]["connections"][0]["id"] = None
    with pytest.raises(ValidationError):
        validate_pvm_structure(pvm_conn_none)


def test_regression_bug_f1_io_03_contractive_algebraic_loop_with_saturation() -> None:
    # Caso exato reportado em BUG-F1-IO-03: 0 < Dc*Dp = 0.9 < 1 com Saturation ativa
    plant = StateSpace([[-1.0]], [[1.0]], [[1.0]], [[0.9]], dt=None, id="loop-09", revision=1)
    ctrl = DynamicController(
        Ac=[[-1.0]],
        Bc=[[1.0]],
        Cc=[[1.0]],
        Dc=[[1.0]],
        feedback_sign="positive",
        dt=None,
    )
    pvm = make_pvm(
        plant,
        ctrl,
        scenario={"saturation": {"enabled": True, "u_min": -1.0, "u_max": 1.0}},
    )

    # Caso A: r = 0.05 (inicia no regime linear contrativo u_sat = 0.5 e depois cruza para saturação u_sat = 1.0)
    t_a = np.linspace(0.0, 1.0, 51)
    r_a = np.full((t_a.size, 1), 0.05)
    sim_a = simulate_pvm_graph(pvm, t_a, r=r_a, rtol=1e-9, atol=1e-12)
    assert sim_a.status in ("success", "warning")
    x_a = tensor_to_array(sim_a.data["x"])  # type: ignore[index]
    u_a = tensor_to_array(sim_a.data["u"])  # type: ignore[index]

    def _ref_ode(r_val: float):
        def _rhs(_tau: float, x_v: np.ndarray) -> np.ndarray:
            xp, xc = float(x_v[0]), float(x_v[1])
            u_sat = float(np.clip((r_val + xp + xc) / 0.1, -1.0, 1.0))
            y_val = xp + 0.9 * u_sat
            return np.array([-xp + u_sat, -xc + y_val], dtype=np.float64)
        return _rhs

    sol_a = scipy.integrate.solve_ivp(
        _ref_ode(0.05), (0.0, 1.0), np.zeros(2), method="RK45", t_eval=t_a, rtol=1e-9, atol=1e-12
    )
    assert sol_a.success
    np.testing.assert_allclose(x_a, sol_a.y.T, atol=1e-7)
    assert math.isclose(float(u_a[0, 0]), 0.5, abs_tol=1e-11)
    assert math.isclose(float(u_a[-1, 0]), 1.0, abs_tol=1e-11)

    # Caso B: r = 0.25 (saturação imediata em +1.0 desde t=0)
    r_b = np.full((t_a.size, 1), 0.25)
    sim_b = simulate_pvm_graph(pvm, t_a, r=r_b, rtol=1e-9, atol=1e-12)
    x_b = tensor_to_array(sim_b.data["x"])  # type: ignore[index]
    u_b = tensor_to_array(sim_b.data["u"])  # type: ignore[index]
    sol_b = scipy.integrate.solve_ivp(
        _ref_ode(0.25), (0.0, 1.0), np.zeros(2), method="RK45", t_eval=t_a, rtol=1e-9, atol=1e-12
    )
    assert sol_b.success
    np.testing.assert_allclose(x_b, sol_b.y.T, atol=1e-7)
    assert np.allclose(u_b, 1.0, atol=1e-12)


def test_regression_bug_f1_io_04_invalid_scenario_and_simulate_method() -> None:
    plant = StateSpace([[0.0, 1.0], [-2.0, -3.0]], [[0.0], [1.0]], [[1.0, 0.0]], [[0.0]], dt=None)
    ctrl = StateFeedbackController([[1.0, 1.0]], feedback_sign="negative")

    for bad_scenario in (
        {"duration": "not_a_number"},
        {"dt": "abc"},
        {"atol": -1e-6},
        {"ghostTraces": True},
        {"ghostTraces": -2},
        {"adaptive": "yes"},
        {"plotResults": 1},
        {"solver": ""},
        {"solver": 123},
    ):
        with pytest.raises(ValidationError):
            make_pvm(plant, ctrl, scenario=bad_scenario)
        res_bad = make_pvm(plant, ctrl, scenario=bad_scenario, return_result=True)
        assert isinstance(res_bad, Result)
        assert res_bad.status == "failure"
        assert res_bad.error is not None
        assert res_bad.error.code == "VALIDATION_ERROR"

    # simulate_pvm_graph com saturação ativa valida method explicitamente
    pvm_sat = make_pvm(
        plant,
        ctrl,
        scenario={"initial_state": [2.0, 0.0], "saturation": {"enabled": True, "u_min": -0.5, "u_max": 0.5}},
    )
    t = np.linspace(0.0, 1.0, 11)

    res_bogus = simulate_pvm_graph(pvm_sat, t, method="bogus_method")
    assert res_bogus.status == "failure"
    assert res_bogus.error is not None and res_bogus.error.code == "VALIDATION_ERROR"

    for lin_method in ("expm", "zoh", "foh"):
        res_lin = simulate_pvm_graph(pvm_sat, t, method=lin_method)
        assert res_lin.status == "failure"
        assert res_lin.error is not None and res_lin.error.code == "UNSUPPORTED_MODEL"

    for ok_method in ("solve_ivp", "rk45", "dop853"):
        res_ok = simulate_pvm_graph(pvm_sat, t, method=ok_method)
        assert res_ok.status in ("success", "warning")


def test_regression_obs_f1_io_01_wiring_ndarray_and_zero_state_statespace(
    schema_registry: tuple[Registry, dict[str, dict[str, Any]]]
) -> None:
    # 1) wiring.reference_map com np.ndarray em scenario
    plant_ns = StateSpace([[-1.0, 0.2], [0.0, -2.0]], [[1.0, 0.0], [0.0, 1.0]], [[1.0, 0.0]], [[0.0, 0.0]])
    ctrl_sf = StateFeedbackController([[0.5, 0.1], [0.2, 0.8]], feedback_sign="negative")
    N_arr = np.array([[2.0], [1.5]])
    pvm_w = make_pvm(plant_ns, ctrl_sf, scenario={"wiring": {"reference_map": N_arr}})
    _assert_schema_valid(pvm_w, "pvm.schema.json", schema_registry)
    cl_w = extract_lti_from_pvm(pvm_w)
    cl_ref = interconnect(plant_ns, ctrl_sf, wiring={"reference_map": N_arr})
    np.testing.assert_allclose(cl_w.A, cl_ref.A, atol=1e-13)
    np.testing.assert_allclose(cl_w.B, cl_ref.B, atol=1e-13)

    # 2) StateSpace estático (n=0) em malha aberta e com DynamicController
    plant_static = StateSpace(
        A=np.zeros((0, 0)),
        B=np.zeros((0, 1)),
        C=np.zeros((1, 0)),
        D=[[2.5]],
        dt=None,
    )
    pvm_ol0 = make_pvm(plant_static)
    _assert_schema_valid(pvm_ol0, "pvm.schema.json", schema_registry)
    cl_ol0 = extract_lti_from_pvm(pvm_ol0)
    assert cl_ol0.n_states == 0
    np.testing.assert_allclose(cl_ol0.D, [[2.5]], atol=1e-13)

    t0 = np.linspace(0.0, 1.0, 11)
    r0 = np.linspace(0.0, 2.0, 11).reshape((-1, 1))
    sim_ol0 = simulate_pvm_graph(pvm_ol0, t0, r=r0)
    np.testing.assert_allclose(tensor_to_array(sim_ol0.data["y"]), 2.5 * r0, atol=1e-12)  # type: ignore[index]

    dyn_c = DynamicController(Ac=[[-2.0]], Bc=[[1.0]], Cc=[[0.5]], Dc=[[0.2]], feedback_sign="negative")
    pvm_cl0 = make_pvm(plant_static, dyn_c)
    _assert_schema_valid(pvm_cl0, "pvm.schema.json", schema_registry)
    cl_0_ref = interconnect(plant_static, dyn_c)
    cl_0_pvm = extract_lti_from_pvm(pvm_cl0)
    np.testing.assert_allclose(cl_0_pvm.A, cl_0_ref.A, atol=1e-13)
    np.testing.assert_allclose(cl_0_pvm.B, cl_0_ref.B, atol=1e-13)
    np.testing.assert_allclose(cl_0_pvm.C, cl_0_ref.C, atol=1e-13)
    np.testing.assert_allclose(cl_0_pvm.D, cl_0_ref.D, atol=1e-13)
    sim_cl0 = simulate_pvm_graph(pvm_cl0, t0, r=r0)
    sim_ref0 = simulate_lti(cl_0_ref, t0, u=r0)
    np.testing.assert_allclose(
        tensor_to_array(sim_cl0.data["y"]),  # type: ignore[index]
        tensor_to_array(sim_ref0.data["y"]),  # type: ignore[index]
        atol=1e-11,
    )


