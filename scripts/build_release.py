"""Pinned static release assembly. No browser/offline approval is inferred from a build."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web/dist"
LOCK = ROOT / "scripts/pyodide-assets.lock.json"
EPOCH = 1735689600


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def fetch_locked(asset, cache):
    target = cache / asset["sha256"]
    if not target.exists():
        with urllib.request.urlopen(asset["url"], timeout=120) as response:
            data = response.read()
        if digest(data) != asset["sha256"]:
            raise ValueError(f"Upstream integrity mismatch: {asset['path']}")
        target.write_bytes(data)
    if digest(target.read_bytes()) != asset["sha256"]:
        raise ValueError(f"Cache integrity mismatch: {target}")
    return target


def assemble():
    lock = json.loads(LOCK.read_text())
    cache = Path(os.environ.get("CONTROLLAB_ASSET_CACHE", Path.home() / ".cache/controllab-build"))
    cache.mkdir(parents=True, exist_ok=True)
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    for asset in lock["assets"]:
        destination = DIST / asset["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fetch_locked(asset, cache), destination)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source"
        source.mkdir()
        shutil.copytree(
            ROOT / "control_lab",
            source / "control_lab",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for name in ("pyproject.toml", "README.md"):
            shutil.copyfile(ROOT / name, source / name)
        env = {**os.environ, "SOURCE_DATE_EPOCH": str(EPOCH), "PYTHONHASHSEED": "0"}
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                directory,
                str(source),
            ],
            check=True,
            env=env,
        )
        wheel = next(Path(directory).glob("*.whl"))
        target = DIST / "wheels" / wheel.name
        target.parent.mkdir()
        with (
            zipfile.ZipFile(wheel) as original,
            zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as normalized,
        ):
            for name in sorted(original.namelist()):
                info = zipfile.ZipInfo(name, (2025, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                normalized.writestr(info, original.read(name))
    shutil.copyfile(ROOT / "web/app/index.html", DIST / "index.html")
    (DIST / "app").mkdir()
    shutil.copyfile(ROOT / "web/app/styles.css", DIST / "app/styles.css")
    shutil.copytree(ROOT / "docs/legal", DIST / "legal")
    for archive in sorted((DIST / "pyodide").iterdir()):
        if not zipfile.is_zipfile(archive):
            continue
        with zipfile.ZipFile(archive) as source:
            for name in source.namelist():
                if Path(name).name.lower().startswith(("license", "copying", "notice")):
                    destination = DIST / "legal/third-party" / archive.name / name
                    if ".." in Path(name).parts or Path(name).is_absolute():
                        raise ValueError("Unsafe license archive path")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.read(name))


def manifest():
    lock = json.loads(LOCK.read_text())
    components = [
        {
            "type": "library",
            "name": "control-lab",
            "version": "1.0.0",
            "licenses": [{"license": {"name": "NOASSERTION"}}],
            "hashes": [
                {
                    "alg": "SHA-256",
                    "content": digest(
                        (DIST / "wheels/control_lab-1.0.0-py3-none-any.whl").read_bytes()
                    ),
                }
            ],
        }
    ]
    for component in lock["components"]:
        entry = {
            "type": "library",
            "name": component["name"],
            "version": component["version"],
            "licenses": [{"license": {"name": component["license"]}}],
            "externalReferences": [{"type": "distribution", "url": component["source"]}],
        }
        if component["name"] in lock["packages"]:
            entry["hashes"] = [
                {"alg": "SHA-256", "content": lock["packages"][component["name"]]["sha256"]}
            ]
        components.append(entry)
    npm = json.loads((ROOT / "web/package-lock.json").read_text())["packages"]
    tools = [
        {
            "type": "library",
            "name": name.removeprefix("node_modules/"),
            "version": value["version"],
            "licenses": [{"license": {"name": value.get("license", "NOASSERTION")}}],
        }
        for name, value in sorted(npm.items())
        if name
    ]
    json_write(
        DIST / "sbom.json",
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {
                "tools": {"components": tools},
                "properties": [
                    {
                        "name": "controllab:ci-lock-sha256",
                        "value": digest((ROOT / "scripts/requirements-ci.lock").read_bytes()),
                    },
                    {
                        "name": "controllab:clearance",
                        "value": "Pending legal/vulnerability audit; native SDP packages not distributed in browser",
                    },
                ],
            },
            "components": components,
        },
    )
    assets = [
        {
            "path": p.relative_to(DIST).as_posix(),
            "size": p.stat().st_size,
            "sha256": digest(p.read_bytes()),
        }
        for p in sorted(DIST.rglob("*"))
        if p.is_file() and p.name != "release-manifest.json"
    ]
    json_write(
        DIST / "release-manifest.json",
        {
            "schema_version": 1,
            "product_version": "1.0.0",
            "source_date_epoch": EPOCH,
            "pyodide_version": lock["version"],
            "release_approved": False,
            "web_maturity": "experimental",
            "browser_offline_validated": False,
            "blocked_gates": [
                "G-0A",
                "G-0B",
                "G-0C",
                "G-0D",
                "browser-wasm",
                "browser-integration",
                "browser-security",
            ],
            "assets": assets,
        },
    )
    verify()


def verify():
    data = json.loads((DIST / "release-manifest.json").read_text())
    expected = {x["path"] for x in data["assets"]}
    actual = {p.relative_to(DIST).as_posix() for p in DIST.rglob("*") if p.is_file()} - {
        "release-manifest.json"
    }
    if expected != actual:
        raise ValueError("Inventory mismatch")
    for asset in data["assets"]:
        path = DIST / asset["path"]
        if digest(path.read_bytes()) != asset["sha256"] or path.stat().st_size != asset["size"]:
            raise ValueError(f"Release integrity mismatch: {path}")
    for asset in json.loads(LOCK.read_text())["assets"]:
        if digest((DIST / asset["path"]).read_bytes()) != asset["sha256"]:
            raise ValueError(f"Runtime lock mismatch: {asset['path']}")
    print(f"Verified {len(expected)} local assets; browser offline gate remains pending.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--manifest", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.manifest:
        manifest()
    elif args.verify:
        verify()
    else:
        assemble()
