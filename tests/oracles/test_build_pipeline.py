"""Independent structural/integrity checks for build closure and fail-closed gates."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

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
