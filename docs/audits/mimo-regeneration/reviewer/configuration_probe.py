"""Reproduce generator candidates and record effective numerical configurations.

This is diagnostic evidence, never a generator of replacement gold values.
"""
import ctypes
import hashlib
import importlib.util
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
import numpy as np
import scipy

spec = importlib.util.spec_from_file_location("independent_release_generator", ROOT / "scripts/generate_release_fixtures.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def differences(left, right, prefix=""):
    out = []
    if type(left) is not type(right):
        return [{"path": prefix, "type_change": True}]
    if isinstance(left, dict):
        assert left.keys() == right.keys()
        for key in left:
            out.extend(differences(left[key], right[key], prefix + "." + key))
    elif isinstance(left, list):
        assert len(left) == len(right)
        for index, (a, b) in enumerate(zip(left, right)):
            out.extend(differences(a, b, prefix + f"[{index}]"))
    elif left != right:
        out.append({"path": prefix, "actual": left, "frozen": right})
    return out


def blas(package, suffix):
    parent = Path(package.__file__).parent.parent / (package.__name__ + ".libs")
    library_path = next(parent.glob("*openblas*.so"))
    library = ctypes.CDLL(str(library_path))
    functions = {}
    for method in ("get_corename", "get_config"):
        fn = getattr(library, "scipy_openblas_" + method + suffix)
        fn.restype = ctypes.c_char_p
        functions[method] = fn().decode()
    return functions


actual, frozen = module.mimo(), json.loads((ROOT / "contracts/fixtures/B-MIMO-2x2.json").read_text())
delta = differences(actual, frozen)
pvm_actual = module.pvm()
pvm_frozen = json.loads((ROOT / "contracts/fixtures/B-PVM-LQR.json").read_text())
pvm_delta = differences(pvm_actual, pvm_frozen)
report = {
    "python": sys.version,
    "platform": platform.platform(),
    "libc": platform.libc_ver(),
    "numpy": np.__version__, "scipy": scipy.__version__,
    "environment": {key: os.environ.get(key) for key in ("OPENBLAS_CORETYPE", "OPENBLAS_NUM_THREADS", "NPY_DISABLE_CPU_FEATURES")},
    "cpu_features": np._core._multiarray_umath.__cpu_features__,
    "blas": {"numpy": blas(np, "64_"), "scipy": blas(scipy, "")},
    "candidate_sha256": hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest(),
    "candidate_equals_preserved_ci": actual == json.loads((ROOT / "docs/audits/mimo-regeneration/candidate-from-ci.json").read_text()),
    "grid_differences": [d for d in delta if d["path"].startswith(".data.omega")],
    "mimo_different_leaves": len(delta),
    "pvm_different_leaves": len(pvm_delta),
    "pvm_first_differences": pvm_delta[:6],
}
try:
    from scripts.mimo_regeneration_certificate import assert_mimo_regeneration_matches_frozen_gold
except ModuleNotFoundError:
    report["certificate"] = "not yet implemented"
else:
    report["certificate"] = assert_mimo_regeneration_matches_frozen_gold(actual, frozen)
try:
    from scripts.pvm_regeneration_certificate import assert_pvm_regeneration_matches_frozen_gold
except ModuleNotFoundError:
    report["pvm_certificate"] = "not yet implemented"
else:
    report["pvm_certificate"] = assert_pvm_regeneration_matches_frozen_gold(pvm_actual, pvm_frozen)
print(json.dumps(report, indent=2))
