"""Release identity must follow Python and inventory updates, without hash cycles."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def stamp(dist):
    return subprocess.check_output(
        ["node", str(ROOT / "scripts/stamp_service_worker.mjs"), str(dist)], text=True
    ).strip()


def test_release_identity_is_deterministic_and_tracks_wheel_and_sbom(tmp_path):
    (tmp_path / "service_worker.js").write_text("self.addEventListener('install', () => {});\n")
    (tmp_path / "release-manifest.json").write_text("{}")
    (tmp_path / "sbom.json").write_text(json.dumps({"license": "MIT"}))
    (tmp_path / "app").mkdir()
    (tmp_path / "app/main.js").write_text("export const ready = true;\n")
    wheel = tmp_path / "control_lab.whl"
    wheel.write_bytes(b"python release A")
    first = stamp(tmp_path)
    worker_a = (tmp_path / "service_worker.js").read_bytes()
    assert first == stamp(tmp_path)
    assert worker_a == (tmp_path / "service_worker.js").read_bytes()
    # The manifest contains the worker's hash and cannot feed that hash back.
    (tmp_path / "release-manifest.json").write_text('{"worker_hash":"changed"}')
    assert stamp(tmp_path) == first
    wheel.write_bytes(b"python release B")
    second = stamp(tmp_path)
    assert second != first
    assert (tmp_path / "service_worker.js").read_bytes() != worker_a
    # Inventory metadata is cached too: a license/tooling-only update counts.
    (tmp_path / "sbom.json").write_text(json.dumps({"license": "MIT", "tool": "new"}))
    assert stamp(tmp_path) != second
    assert (tmp_path / "service_worker.js").read_text().count("release fingerprint") == 1
