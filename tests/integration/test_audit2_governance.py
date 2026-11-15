"""AUD-016: evolving records, real evidence and negative Appendix E checks.

These are governance guards for partial T-PVM-01/02, T-UI-01 and T-SEC-01
evidence. They do not claim to execute those scientific/browser scenarios.
"""

import copy
import json
from pathlib import Path

import pytest

from scripts.project_governance import (
    GovernanceError,
    select_next_work_package,
    validate_handoff_text,
    validate_state,
    validate_transition,
)

SHA = "a" * 40


def dossier(wp_id="WP-AUDIT2-FIX-F9-TEST", *, numbered=False):
    rows = "\n".join(
        f"| {i}. Item | Prova analítica e log {i}; gate de produto permanece pendente. |"
        for i in range(1, 11)
    )
    if numbered:
        rows = "\n".join(
            f"| **{i}** | Pergunta | SIM | Evidência {i} | CONFORME |" for i in range(1, 11)
        )
    heading = "3. Checklist de Handoff" if numbered else "Checklist do Apêndice E"
    review = (
        (
            f"## 5. Parecer Independente\n- **Veredito F9:** `accepted`\n"
            f"- Revisor independente: f9-integration-qa\n- Commit SHA auditado: {SHA}\n- Data (UTC): 2026-11-15\n"
        )
        if numbered
        else ""
    )
    decision = "" if numbered else "**Decisão: `accepted`**, no escopo local anunciado.\n"
    return f"# {wp_id} — F9\n{decision}\nBase remota: {SHA}\n## {heading}\n| Item | Evidência |\n|---|---|\n{rows}\n{review}"


@pytest.fixture
def state():
    return {
        "document_id": "CL-DIR-001",
        "gates": {
            name: {"status": "PENDING", "audit_verdict": "BLOCKED", "blocking_wps": []}
            for name in ("G-0A", "G-0B", "G-0C", "G-0D")
        },
        "audit_reference": {"confirmed_findings": ["AUD-016"]},
        "work_packages": [
            {
                "wp_id": "WP-AUDIT2-FIX-F9-TEST",
                "status": "PENDING",
                "dependencies": [],
                "findings": ["AUD-016"],
            }
        ],
    }


def accept(state, root):
    wp = state["work_packages"][0]
    (root / "handoff.md").write_text(dossier(wp["wp_id"]))
    wp.update(
        status="ACCEPTED_BY_F9",
        f9_review="accepted",
        acceptance_scope="local_governance_only",
        handoff_ref="handoff.md",
    )


def test_semantic_governance_accepts_queue_growth_and_factual_verdict_updates(state, tmp_path):
    validate_state(state, tmp_path)
    for index in range(12):
        state["work_packages"].append(
            {
                "wp_id": f"WP-AUDIT{index + 3}-FIX-F1-NEW",
                "status": "PENDING",
                "findings": [],
                "dependencies": [state["work_packages"][0]["wp_id"]],
            }
        )
    state["gates"]["G-0B"]["audit_verdict"] = "UNAVAILABLE_IN_PROVISIONED_WASM"
    state["gates"]["G-0D"]["audit_verdict"] = (
        "CONTINUOUS_AND_SINGLE_RATE_DISCRETE_EXTERNAL_INTEROP_VERIFIED_GATE_PENDING"
    )
    assert validate_state(state, tmp_path)["work_packages"] == 13


@pytest.mark.parametrize("numbered", [False, True])
def test_handoff_formats_require_same_ten_evidenced_items(numbered):
    text = dossier(numbered=numbered)
    validate_handoff_text(text, "WP-AUDIT2-FIX-F9-TEST", require_identity=True)
    for number in range(1, 11):
        prefix = f"| **{number}** |" if numbered else f"| {number}. Item |"
        missing = "\n".join(line for line in text.splitlines() if not line.startswith(prefix))
        with pytest.raises(GovernanceError, match="1..10"):
            validate_handoff_text(missing, "WP-AUDIT2-FIX-F9-TEST")
    # Append duplicate inside the checklist rather than after a review heading.
    duplicate = text.replace(
        "|---|---|",
        "|---|---|\n"
        + (
            "| **1** | Pergunta | SIM | Evidência | CONFORME |"
            if numbered
            else "| 1. Item | Evidência |"
        ),
    )
    with pytest.raises(GovernanceError, match="duplicate"):
        validate_handoff_text(duplicate, "WP-AUDIT2-FIX-F9-TEST")


def test_acceptance_without_evidence_is_rejected(state, tmp_path):
    wp = state["work_packages"][0]
    wp.update(status="ACCEPTED_BY_F9", f9_review="accepted", acceptance_scope="local")
    with pytest.raises(GovernanceError, match="handoff missing"):
        validate_state(state, tmp_path)
    wp["handoff_ref"] = "missing.md"
    with pytest.raises(GovernanceError, match="Invalid evidence"):
        validate_state(state, tmp_path)
    accept(state, tmp_path)
    validate_state(state, tmp_path)
    wp["f9_review"] = "pending"
    with pytest.raises(GovernanceError, match="F9 review"):
        validate_state(state, tmp_path)


def test_template_accepted_word_and_pending_item_are_not_acceptance():
    text = dossier()
    for invalid in [
        text.replace("Decisão: `accepted`", "Decisão: `changes_requested`"),
        text.replace("Prova analítica e log 6; gate de produto permanece pendente.", "PENDENTE"),
        text.replace(SHA, "SHA PENDENTE"),
    ]:
        with pytest.raises(GovernanceError):
            validate_handoff_text(invalid, "WP-AUDIT2-FIX-F9-TEST")


def test_cycles_and_unknown_dependencies_are_rejected(state, tmp_path):
    root_id = state["work_packages"][0]["wp_id"]
    for dependency in ["NONEXISTENT", root_id]:
        changed = copy.deepcopy(state)
        changed["work_packages"][0]["dependencies"] = [dependency]
        with pytest.raises(GovernanceError):
            validate_state(changed, tmp_path)


def test_unavailable_gate_cannot_be_promoted(state, tmp_path):
    accept(state, tmp_path)
    gate = state["gates"]["G-0B"]
    gate.update(
        status="ACCEPTED_BY_F9",
        f9_review="accepted",
        decision="pass",
        acceptance_scope="production_sdp",
        assessed_commit=SHA,
        evidence_ref="handoff.md",
        audit_verdict="UNAVAILABLE_IN_PROVISIONED_WASM",
    )
    with pytest.raises(GovernanceError, match="not a pass"):
        validate_state(state, tmp_path)
    gate["audit_verdict"] = "PASS"
    with pytest.raises(GovernanceError, match="two browsers"):
        validate_state(state, tmp_path)
    gate["validation"] = {"production_sdp_wasm": True, "browsers": ["Chromium", "Firefox"]}
    validate_state(state, tmp_path)


def test_gate_transition_requires_history_on_reopening(state, tmp_path):
    accept(state, tmp_path)
    before = copy.deepcopy(state)
    before["gates"]["G-0A"].update(
        status="ACCEPTED_BY_F9",
        f9_review="accepted",
        decision="pass",
        acceptance_scope="case_fixture",
        assessed_commit=SHA,
        evidence_ref="handoff.md",
        audit_verdict="PASS",
    )
    validate_state(before, tmp_path)
    with pytest.raises(GovernanceError, match="history"):
        validate_transition(before, state, tmp_path)
    state["gates"]["G-0A"].update(
        historical_acceptance={"status": "ACCEPTED_BY_F9"},
        blocking_findings=["AUD-020"],
        audit_ref="handoff.md",
    )
    validate_transition(before, state, tmp_path)


def test_external_blocker_is_not_silently_selected(state):
    first = state["work_packages"][0]
    blocked = {
        "wp_id": "WP-AUDIT2-FIX-F9-SERVER",
        "status": "PENDING",
        "dependencies": [],
        "external_blockers": ["owner action required"],
    }
    state["work_packages"].insert(0, blocked)
    assert select_next_work_package(state) is first


def test_confirmed_findings_and_evidence_path_must_resolve(state, tmp_path):
    changed = copy.deepcopy(state)
    changed["audit_reference"]["confirmed_findings"].append("AUD-021")
    with pytest.raises(GovernanceError, match="no corrective"):
        validate_state(changed, tmp_path)
    accept(state, tmp_path)
    state["work_packages"][0]["handoff_ref"] = "../escape.md"
    with pytest.raises(GovernanceError, match="Invalid evidence"):
        validate_state(state, tmp_path)


def test_actual_repository_governance_and_audit2_first_selection():
    root = Path(__file__).resolve().parents[2]
    actual = json.loads((root / "PROJECT_STATE.json").read_text())
    validate_state(actual, root)
    chosen = select_next_work_package(actual)
    # The current package may already be accepted by the final handoff.
    if actual["work_packages"][0]["status"] == "PENDING":
        assert chosen["wp_id"] == actual["work_packages"][0]["wp_id"]
    else:
        assert chosen is None or not chosen.get("external_blockers")


def test_historical_parent_does_not_authorize_new_acceptance(state, tmp_path):
    accept(state, tmp_path)
    parent = {
        "wp_id": "HISTORICAL",
        "status": "CHANGES_REQUESTED",
        "historical_acceptance": {"status": "ACCEPTED_BY_F9"},
    }
    state["work_packages"].append(parent)
    state["work_packages"][0].update(
        dependencies=["HISTORICAL"], release_blocker_wps=["HISTORICAL"]
    )
    with pytest.raises(GovernanceError, match="unresolved dependency"):
        validate_state(state, tmp_path)


@pytest.mark.parametrize("claim", ["release_status", "audit_verdict"])
def test_stable_claim_cannot_bypass_pending_gates(state, tmp_path, claim):
    if claim == "release_status":
        state["release_status"] = "stable"
    else:
        state["audit_reference"]["verdict"] = "APPROVED_FOR_STABLE_WEB_RELEASE"
    with pytest.raises(GovernanceError, match="every mandatory gate"):
        validate_state(state, tmp_path)


def test_external_blockage_cannot_be_pending_in_standard_agent_queue(state, tmp_path):
    blocked = state["work_packages"][0]
    blocked["external_blockers"] = ["server administration unavailable"]
    with pytest.raises(GovernanceError, match="external blockers require blocked status"):
        validate_state(state, tmp_path)
    blocked.update(status="BLOCKED_BY_GATE", f9_review="blocked_by_gate")
    ready = {"wp_id": "WP-AUDIT2-FIX-F1-READY", "status": "PENDING", "dependencies": []}
    state["work_packages"].append(ready)
    validate_state(state, tmp_path)
    accepted = {w["wp_id"] for w in state["work_packages"] if w["status"] == "ACCEPTED_BY_F9"}
    standard_selection = next(
        w
        for w in state["work_packages"]
        if w["status"] == "PENDING" and all(dep in accepted for dep in w.get("dependencies", []))
    )
    assert standard_selection is ready
    assert select_next_work_package(state) is standard_selection
