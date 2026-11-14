"""Independent build supply-chain and prefix contract checks (no browser claims)."""
from pathlib import Path
import hashlib
import json
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[2]


def test_independent_runtime_lock_has_complete_transitive_closure():
    lock = json.loads((ROOT / 'scripts/pyodide-assets.lock.json').read_text())
    assert lock['version'] == '0.27.5'
    assert set(lock['roots']) == {'numpy', 'scipy', 'micropip'}
    packages = lock['packages']
    closure = set()
    def visit(name):
        if name in closure:
            return
        closure.add(name)
        assert name in packages, 'unlocked transitive dependency: ' + name
        for dependency in packages[name]['depends']:
            visit(dependency)
    for name in lock['roots']:
        visit(name)
    assert closure == set(packages)
    assets = {entry['path']: entry for entry in lock['assets']}
    assert len(assets) == len(lock['assets'])
    runtime = {'pyodide.js', 'pyodide.mjs', 'pyodide.asm.js', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json'}
    assert {'pyodide/' + name for name in runtime} <= set(assets)
    for name, package in packages.items():
        entry = assets['pyodide/' + package['file_name']]
        assert entry['sha256'] == package['sha256'], name
    for path, entry in assets.items():
        assert '..' not in Path(path).parts and not Path(path).is_absolute()
        assert len(entry['sha256']) == 64
        int(entry['sha256'], 16)
        assert entry['size'] > 0
        assert urlparse(entry['url']).scheme == 'https'
        assert '/v0.27.5/full/' in entry['url']


def test_independent_f8_prefix_paths_have_planned_build_targets():
    source = (ROOT / 'web/app/main.ts').read_text()
    paths = ['worker/pyodide_worker.js', 'service_worker.js', 'pyodide/', 'wheels/control_lab-1.0.0-py3-none-any.whl']
    for prefix in ('https://user.github.io/', 'https://user.github.io/ControlLab_Web/'):
        module = prefix + 'app/main.js'
        base = urljoin(module, '../')
        assert base == prefix
        for path in paths:
            assert '"' + path + '"' in source
            assert urljoin(base, path).startswith(prefix)
    build = (ROOT / 'scripts/build_web.mjs').read_text()
    for path in ('app/main.js', 'worker/pyodide_worker.js', 'service_worker.js'):
        assert path in build


def test_independent_corrupt_cached_runtime_fails_before_network(tmp_path):
    import importlib.util
    import pytest
    spec = importlib.util.spec_from_file_location('f9_independent_release_builder', ROOT / 'scripts/build_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    digest = hashlib.sha256(b'authentic pinned bytes').hexdigest()
    (tmp_path / digest).write_bytes(b'corrupted cache')
    with pytest.raises(ValueError, match='Cache integrity mismatch'):
        module.fetch_locked({'sha256': digest, 'path': 'pyodide/runtime', 'url': 'https://invalid.example/never-fetch'}, tmp_path)
