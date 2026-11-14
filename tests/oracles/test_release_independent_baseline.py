"""Independent F9 integrity of immutable originals and full seven-fixture inventory.

Accepted source preservation was audited once (121/121 SHA256) and recorded in
WP-AUDIT-FIX-F9-BUILD-CI.log; legitimate future source changes remain possible.
"""
from pathlib import Path
import hashlib
import json
import math
import pytest

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_GOLDENS = {'contracts/fixtures/B-CARE-02.json': 'f08f9fe28302c1704554460eb660a00c2911b75272358872672bbbb5068e516f',
 'contracts/fixtures/B-CARE-12x3.json': '0bacb2e43ebfb4a7803cd223de8c219deda4876a180175af30f20cd07f8686a4',
 'contracts/fixtures/B-SDP-A-D.json': '4377341309c5df1df3c814e3f1a3d38ea3783232c3f4ae84e201f829e5f33076'}

@pytest.mark.parametrize("relative,digest", ORIGINAL_GOLDENS.items())
def test_independent_original_golden_bytes(relative, digest):
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest, relative


def test_independent_seven_fixture_inventory_and_full_finite_tensors():
    directory = ROOT / "contracts/fixtures"
    names = {"B-CARE-02.json", "B-CARE-12x3.json", "B-SDP-A-D.json",
             "B-DARE-12x3.json", "B-ARX-PRBS.json", "B-MIMO-2x2.json", "B-PVM-LQR.json"}
    assert {p.name for p in directory.glob("*.json")} == names
    entries = {}
    for line in (directory / "checksums.sha256").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        digest, name = line.split()
        assert name not in entries, "duplicate checksum entry"
        assert name in names
        entries[name] = digest
    assert set(entries) == names
    def walk(value):
        if isinstance(value, dict):
            if {"shape", "dtype", "order", "data"} <= value.keys():
                assert value["dtype"] == "float64"
                assert value["order"] in ("C", "F")
                assert math.prod(value["shape"]) == len(value["data"])
                assert all(type(v) in (int, float) and math.isfinite(v) for v in value["data"])
            for nested in value.values(): walk(nested)
        elif isinstance(value, list):
            for nested in value: walk(nested)
        elif isinstance(value, float):
            assert math.isfinite(value)
    for name in sorted(names):
        payload = (directory / name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entries[name]
        fixture = json.loads(payload, parse_constant=lambda s: pytest.fail("nonfinite JSON: " + s))
        assert fixture["fixture_id"] == name[:-5]
        walk(fixture)
