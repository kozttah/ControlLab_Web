"""Independent structural/integrity checks for build closure and fail-closed gates."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def test_build_runtime_lock_closes_transitive_dependencies():
    lock = json.loads((ROOT / "scripts/pyodide-assets.lock.json").read_text())
    assert lock["version"] == "0.27.5"
    assets = {a["path"]: a for a in lock["assets"]}
    for name in (
        "pyodide.mjs",
        "pyodide.js",
        "pyodide.asm.js",
        "pyodide.asm.wasm",
        "python_stdlib.zip",
        "pyodide-lock.json",
    ):
        assert "pyodide/" + name in assets
    for package in lock["packages"].values():
        assert set(package["depends"]) <= set(lock["packages"])
        assert assets["pyodide/" + package["file_name"]]["sha256"] == package["sha256"]
    for asset in assets.values():
        assert len(asset["sha256"]) == 64
        assert asset["size"] > 0
        assert asset["url"].startswith("https://cdn.jsdelivr.net/pyodide/v0.27.5/full/")


def test_build_missing_browser_suites_fail_closed(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("f9_ci_gate_missing", ROOT / "scripts/ci_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("CONTROLLAB_CI_REPORTS", str(tmp_path / "reports"))
    for job in "DEFG":
        monkeypatch.setattr(sys, "argv", ["ci_gate.py", job])
        assert module.main() == 2
        assert "BLOCKED" in capsys.readouterr().err
        report = json.loads((tmp_path / "reports" / f"job-{job}.json").read_text())
        assert report["status"] == "blocked" and report["missing_suites"]


def test_build_rejects_tampered_asset_and_extra_inventory(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "release_builder", ROOT / "scripts/build_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DIST", tmp_path)
    monkeypatch.setattr(module, "LOCK", tmp_path / "runtime-lock.json")
    (tmp_path / "runtime-lock.json").write_text('{"assets": []}')
    data = (tmp_path / "runtime-lock.json").read_bytes()
    manifest = {
        "assets": [
            {
                "path": "runtime-lock.json",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ]
    }
    (tmp_path / "release-manifest.json").write_text(json.dumps(manifest))
    module.verify()
    (tmp_path / "runtime-lock.json").write_text('{"assets": [1]}')
    import pytest

    with pytest.raises(ValueError, match="integrity"):
        module.verify()
    (tmp_path / "extra").write_text("unlisted")
    with pytest.raises(ValueError, match="Inventory"):
        module.verify()


def test_integrity_manifest_defers_gate_decisions_to_external_f9_ledger():
    spec = importlib.util.spec_from_file_location(
        "release_manifest_contract", ROOT / "scripts/build_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assets = [{"path": "wheel.whl", "size": 3, "sha256": "0" * 64}]
    first = module.make_integrity_manifest({"version": "0.27.5"}, assets)
    assert first == module.make_integrity_manifest({"version": "0.27.5"}, assets)
    assert first["schema_version"] == 1 and first["build_profile"] == "integrity_only"
    assert first["release_approved"] is False
    assert first["gate_attestation"] == {
        "source": "PROJECT_STATE.json",
        "handoffs": "docs/audits/handoffs/",
        "required_gates": ["G-0A", "G-0B", "G-0C", "G-0D"],
        "embedded": False,
    }
    assert "blocked_gates" not in first and "browser_offline_validated" not in first
    assert first["assets"] == assets


def test_release_carries_original_license_without_relicensing_third_party(tmp_path, monkeypatch):
    """Exercise real wheel metadata and distribution notices without network assets."""
    from email.parser import BytesParser

    spec = importlib.util.spec_from_file_location(
        "release_license_artifacts", ROOT / "scripts/build_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "project"
    project.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copyfile(ROOT / name, project / name)
    (project / "control_lab").mkdir()
    (project / "control_lab/__init__.py").write_text('"""Packaging probe only."""\n')
    shutil.copytree(ROOT / "docs/legal", project / "docs/legal")
    (project / "web/app").mkdir(parents=True)
    for name in ("index.html", "styles.css"):
        (project / "web/app" / name).write_text("<!-- packaging probe -->")
    shutil.copyfile(ROOT / "web/package-lock.json", project / "web/package-lock.json")
    (project / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/requirements-ci.lock", project / "scripts/requirements-ci.lock")
    cache = tmp_path / "cache"
    cache.mkdir()
    archive = tmp_path / "upstream.zip"
    notice = b"Copyright independent upstream. MPL-2.0. Preserve this exact notice.\n"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("LICENSE", notice)
    blob = archive.read_bytes()
    checksum = hashlib.sha256(blob).hexdigest()
    (cache / checksum).write_bytes(blob)
    lock = {
        "version": "0.27.5",
        "packages": {},
        "components": [
            {
                "name": "upstream-probe",
                "version": "1",
                "license": "MPL-2.0",
                "source": "https://example.invalid/source",
            }
        ],
        "assets": [
            {
                "path": "pyodide/runtime.zip",
                "sha256": checksum,
                "size": len(blob),
                "url": "https://example.invalid/runtime.zip",
            }
        ],
    }
    lock_path = project / "scripts/pyodide-assets.lock.json"
    lock_path.write_text(json.dumps(lock))
    monkeypatch.setattr(module, "ROOT", project)
    monkeypatch.setattr(module, "DIST", project / "web/dist")
    monkeypatch.setattr(module, "LOCK", lock_path)
    monkeypatch.setenv("CONTROLLAB_ASSET_CACHE", str(cache))
    module.assemble()
    module.manifest()
    license_bytes = (ROOT / "LICENSE").read_bytes()
    assert (module.DIST / "legal/ControlLab-Web-MIT.txt").read_bytes() == license_bytes
    assert (module.DIST / "legal/third-party/runtime.zip/LICENSE").read_bytes() == notice
    assert (module.DIST / "pyodide/runtime.zip").read_bytes() == blob
    assert (module.DIST / "legal/licenses/Pyodide-MPL-2.0.txt").is_file()
    assert (module.DIST / "legal/THIRD_PARTY_NOTICES.md").is_file()
    wheel = next((module.DIST / "wheels").glob("*.whl"))
    with zipfile.ZipFile(wheel) as zipped:
        metadata_name = next(n for n in zipped.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(zipped.read(metadata_name))
        assert metadata["License-Expression"] == "MIT"
        assert metadata["License-File"] == "LICENSE"
        license_name = next(
            n for n in zipped.namelist() if n.endswith(".dist-info/licenses/LICENSE")
        )
        assert zipped.read(license_name) == license_bytes
    components = json.loads((module.DIST / "sbom.json").read_text())["components"]
    assert components[0]["licenses"] == [{"license": {"id": "MIT"}}]
    assert components[1]["licenses"] == [{"license": {"name": "MPL-2.0"}}]
