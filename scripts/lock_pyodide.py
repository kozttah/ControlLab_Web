"""Explicit maintainer update: download a fixed Pyodide release and pin actual bytes.

Review the resulting diff independently. Normal builds never refresh this lock.
"""

import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

VERSION = "0.27.5"
BASE = f"https://cdn.jsdelivr.net/pyodide/v{VERSION}/full/"
ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".cache/controllab-build"


def download(name):
    url = BASE + name
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    sha = hashlib.sha256(data).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / sha).write_bytes(data)
    return {"path": "pyodide/" + name, "url": url, "sha256": sha, "size": len(data)}


def main():
    lock_asset = download("pyodide-lock.json")
    upstream = json.loads((CACHE / lock_asset["sha256"]).read_text())
    names = set()

    def include(name):
        if name in names:
            return
        names.add(name)
        for dependency in upstream["packages"][name]["depends"]:
            include(dependency)

    for name in ("numpy", "scipy", "micropip"):
        include(name)
    files = ["pyodide.js", "pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip"]
    files += [upstream["packages"][name]["file_name"] for name in sorted(names)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        assets = list(pool.map(download, files)) + [lock_asset]
    for name in names:
        package = upstream["packages"][name]
        asset = next(a for a in assets if a["path"] == "pyodide/" + package["file_name"])
        if asset["sha256"] != package["sha256"]:
            raise ValueError(f"Pyodide upstream package hash mismatch: {name}")
    components = [{"name": "pyodide", "version": VERSION, "license": "NOASSERTION", "source": BASE}]
    components += [
        {
            "name": name,
            "version": upstream["packages"][name]["version"],
            "license": "NOASSERTION",
            "source": BASE + upstream["packages"][name]["file_name"],
        }
        for name in sorted(names)
    ]
    result = {
        "version": VERSION,
        "runtime": upstream["info"],
        "roots": ["numpy", "scipy", "micropip"],
        "packages": {name: upstream["packages"][name] for name in sorted(names)},
        "components": components,
        "assets": sorted(assets, key=lambda a: a["path"]),
    }
    (ROOT / "scripts/pyodide-assets.lock.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(f"Pinned {len(assets)} assets, {sum(a['size'] for a in assets)} bytes")


if __name__ == "__main__":
    main()
