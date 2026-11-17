"""Independent F9 black-box checks of browser release update identity."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def _stamp(tree):
    subprocess.run(['node', str(ROOT / 'scripts/stamp_service_worker.mjs'), str(tree)], check=True, capture_output=True)
    return (tree / 'service_worker.js').read_bytes()


def _tree(root, reverse=False):
    root.mkdir()
    files = {
        'service_worker.js': b'self.addEventListener("fetch", () => {});\n',
        'release-manifest.json': b'{"sha256":"provisional"}',
        'sbom.spdx.json': b'{"packages":["numpy"]}',
        'main.js': b'console.log("release");',
        'runtime/core.whl': b'wheel A',
    }
    for name in sorted(files, reverse=reverse):
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(files[name])
    return root


def test_independent_identity_covers_wheel_and_sbom_without_manifest_cycle(tmp_path):
    tree = _tree(tmp_path / 'a')
    first = _stamp(tree)
    assert _stamp(tree) == first
    (tree / 'release-manifest.json').write_text('{"sha256":"final"}')
    assert _stamp(tree) == first
    (tree / 'runtime/core.whl').write_bytes(b'wheel B')
    second = _stamp(tree)
    assert second != first
    assert second.splitlines()[1:] == first.splitlines()[1:]
    (tree / 'sbom.spdx.json').write_text('{"packages":["scipy"]}')
    assert _stamp(tree) != second


def test_independent_rebuild_order_and_worker_edits(tmp_path):
    a = _tree(tmp_path / 'a')
    b = _tree(tmp_path / 'b', reverse=True)
    assert _stamp(a) == _stamp(b)
    old = _stamp(a)
    with (a / 'service_worker.js').open('ab') as handle:
        handle.write(b'// source revision\n')
    updated = _stamp(a)
    assert updated != old
    assert updated.startswith(old.splitlines(keepends=True)[0])
    assert updated.endswith(b'// source revision\n')
    assert _stamp(a) == updated
