"""Fallback diagnostics passing cannot silently release an unproven product."""

from scripts.ci_gate import unresolved_release_gates


def test_every_mandatory_product_gate_requires_explicit_f9_acceptance():
    names = ("G-0A", "G-0B", "G-0C", "G-0D")
    assert unresolved_release_gates({}) == list(names)
    accepted = {"gates": {name: {"status": "ACCEPTED_BY_F9"} for name in names}}
    assert unresolved_release_gates(accepted) == []
    for name in names:
        accepted["gates"][name]["status"] = "PENDING"
        assert unresolved_release_gates(accepted) == [name]
        accepted["gates"][name]["status"] = "ACCEPTED_BY_F9"
