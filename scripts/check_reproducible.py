"""Build twice and compare every artifact via the deterministic release manifest."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "web/dist/release-manifest.json"


def main():
    subprocess.run(["npm", "--prefix", "web", "run", "build"], cwd=ROOT, check=True)
    first = MANIFEST.read_bytes()
    subprocess.run(["npm", "--prefix", "web", "run", "build"], cwd=ROOT, check=True)
    if first != MANIFEST.read_bytes():
        raise ValueError("Two builds produced different asset hashes/manifests")
    print("Reproducibility PASS: two builds, identical manifests and every asset hash.")


if __name__ == "__main__":
    main()
