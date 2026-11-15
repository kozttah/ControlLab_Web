"""Version 1 semantic checks for PROJECT_STATE and Appendix E handoffs.

These checks enforce records and references; they do not replace scientific F9
review, demonstrate a browser capability, or configure GitHub protection.
Historical evidence is accepted in both numbered and descriptive Markdown.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = {"G-0A", "G-0B", "G-0C", "G-0D"}
STATUSES = {
    "PENDING",
    "ACCEPTED_BY_F9",
    "CHANGES_REQUESTED",
    "BLOCKED_BY_GATE",
    "BLOCKED_NEEDS_ARGON",
    "REJECTED_WITH_EVIDENCE",
}
SHA = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{40}(?![0-9a-fA-F])")


class GovernanceError(AssertionError):
    """A governance record violates a required invariant."""


def require(condition, message):
    if not condition:
        raise GovernanceError(message)


def plain(text):
    return text.replace("**", "").replace("`", "").strip()


def sections(text):
    matches = list(re.finditer(r"^##\s+(.+)$", text, re.MULTILINE))
    return [
        (m.group(1), text[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)])
        for i, m in enumerate(matches)
    ]


def validate_handoff_text(text, wp_id, *, require_identity=False):
    """Require an explicit decision, all ten evidenced items and source identity.

    A global gate being pending in an evidence/limitations paragraph is not the
    same as a checklist item being pending. Template choices are not decisions.
    """
    if require_identity:
        require(wp_id in text.splitlines()[0], f"Handoff identity mismatch: {wp_id}")
    parts = sections(text)
    checklists = [body for title, body in parts if "checklist" in title.casefold()]
    require(len(checklists) == 1, f"{wp_id}: exactly one Appendix E checklist required")
    rows = {}
    for line in checklists[0].splitlines():
        if not line.startswith("|"):
            continue
        cells = [plain(c) for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        match = re.match(r"^(\d+)(?:[.)\s]|$)", cells[0])
        if not match:
            continue
        number = int(match.group(1))
        require(number not in rows, f"{wp_id}: duplicate checklist item {number}")
        require(len(cells) >= 2, f"{wp_id}: malformed checklist item {number}")
        evidence = cells[3] if len(cells) >= 5 else cells[1]
        require(
            bool(evidence) and evidence not in {"...", "—", "-"},
            f"{wp_id}: missing evidence for item {number}",
        )
        require(
            not re.match(
                r"^(?:PENDENTE|PENDING|FALHA|FAILED|TODO|TBD)(?:\s*$|\s*[:—-])", evidence, re.I
            ),
            f"{wp_id}: unresolved checklist item {number}",
        )
        if len(cells) >= 5:
            require(cells[-1] in {"CONFORME", "N/A"}, f"{wp_id}: invalid item verdict {number}")
        rows[number] = evidence
    require(set(rows) == set(range(1, 11)), f"{wp_id}: checklist must contain exactly items 1..10")
    review_sections = [body for title, body in parts if re.match(r"5\.\s", title)]
    decision_text = review_sections[0] if review_sections else text
    decision_lines = [plain(line) for line in decision_text.splitlines()]
    decision = re.compile(
        r"^(?:-\s*)?(?:Veredito F9(?:\s*\([^)]*\))?|Decisão|Parecer F9)\s*:\s*accepted(?:\b|$)",
        re.I,
    )
    require(
        any(decision.match(line) for line in decision_lines),
        f"{wp_id}: explicit accepted decision required",
    )
    require(
        SHA.search(decision_text if review_sections else text),
        f"{wp_id}: audited source SHA required",
    )
    if review_sections:
        for field in ("Revisor independente", "Commit SHA auditado", "Data (UTC)"):
            require(field in decision_text, f"{wp_id}: missing reviewer metadata {field}")


def evidence_file(root, reference):
    require(isinstance(reference, str) and bool(reference.strip()), "Missing evidence reference")
    path = (root / reference).resolve()
    require(
        path.is_relative_to(root.resolve()) and path.is_file(),
        f"Invalid evidence file: {reference}",
    )
    return path


def corrective(wp):
    return bool(re.match(r"^WP-AUDIT\d*-FIX-", wp["wp_id"]))


def validate_state(state, root=ROOT):
    root = Path(root)
    require(state.get("document_id") == "CL-DIR-001", "Unknown normative document")
    require(set(state.get("gates", {})) == GATES, "Missing or unknown mandatory gate")
    wps = state.get("work_packages", [])
    require(isinstance(wps, list) and bool(wps), "WorkPackage queue required")
    by_id = {w["wp_id"]: w for w in wps}
    require(len(by_id) == len(wps), "Duplicate WorkPackage ID")
    visited, visiting = set(), set()

    def visit(wp_id):
        require(wp_id in by_id, f"Missing dependency: {wp_id}")
        require(wp_id not in visiting, f"Dependency cycle at {wp_id}")
        if wp_id in visited:
            return
        visiting.add(wp_id)
        for dependency in by_id[wp_id].get("dependencies", []):
            visit(dependency)
        visiting.remove(wp_id)
        visited.add(wp_id)

    for wp in wps:
        require(wp.get("status") in STATUSES, f"Unknown WP status: {wp['wp_id']}")
        require(
            not (wp["status"] == "PENDING" and wp.get("external_blockers")),
            f"{wp['wp_id']}: external blockers require blocked status, not PENDING",
        )
        visit(wp["wp_id"])
        for field in ("release_blocker_wps", "remediation_wps"):
            for reference in wp.get(field, []):
                require(reference in by_id, f"Unknown {field} reference: {reference}")
        if wp["status"] != "ACCEPTED_BY_F9":
            continue
        require(wp.get("f9_review") == "accepted", f"{wp['wp_id']}: F9 review missing")
        require(bool(wp.get("acceptance_scope")), f"{wp['wp_id']}: acceptance scope missing")
        if wp.get("handoff_ref"):
            path = evidence_file(root, wp["handoff_ref"])
            validate_handoff_text(
                path.read_text(encoding="utf-8"), wp["wp_id"], require_identity=True
            )
        else:
            # Explicit migration of pre-handoff local accepts: this is release
            # debt, never permission to grant a new implicit product acceptance.
            legacy = wp.get("legacy_acceptance_evidence", {})
            require(
                legacy.get("format") == "legacy_cpython_local.v1", f"{wp['wp_id']}: handoff missing"
            )
            require(
                wp["acceptance_scope"] == "cpython_local_only"
                and bool(wp.get("release_blocker_wps")),
                f"{wp['wp_id']}: legacy acceptance cannot authorize release",
            )
            require(bool(legacy.get("evidence_refs")), f"{wp['wp_id']}: legacy evidence missing")
            for reference in legacy["evidence_refs"]:
                evidence_file(root, reference)
        for dependency in wp.get("dependencies", []):
            parent = by_id[dependency]
            if parent["status"] != "ACCEPTED_BY_F9":
                require(
                    wp.get("legacy_acceptance_evidence", {}).get("format")
                    == "legacy_cpython_local.v1"
                    and parent.get("historical_acceptance", {}).get("status") == "ACCEPTED_BY_F9"
                    and bool(wp.get("release_blocker_wps")),
                    f"{wp['wp_id']}: acceptance with unresolved dependency {dependency}",
                )

    for gate_id, gate in state["gates"].items():
        require(gate.get("status") in STATUSES, f"Unknown gate status: {gate_id}")
        require(
            isinstance(gate.get("audit_verdict"), str) and bool(gate["audit_verdict"]),
            f"{gate_id}: factual verdict missing",
        )
        for reference in gate.get("blocking_wps", []):
            require(reference in by_id, f"Unknown gate blocker: {reference}")
        if gate["status"] != "ACCEPTED_BY_F9":
            continue
        require(
            gate.get("f9_review") == "accepted" and gate.get("decision") == "pass",
            f"{gate_id}: formal pass required",
        )
        require(
            bool(gate.get("acceptance_scope")) and SHA.fullmatch(gate.get("assessed_commit", "")),
            f"{gate_id}: scope/source identity missing",
        )
        evidence_file(root, gate.get("evidence_ref"))
        require(
            not re.search(
                r"UNAVAILABLE|PENDING|FAIL|BLOCKED|INCONCLUSIVE|CONDITIONAL|NOT_DEMONSTRATED",
                gate["audit_verdict"],
                re.I,
            ),
            f"{gate_id}: unavailable/conditional capability is not a pass",
        )
        require(
            all(by_id[x]["status"] == "ACCEPTED_BY_F9" for x in gate.get("blocking_wps", [])),
            f"{gate_id}: unresolved blocking WorkPackage",
        )
        if gate_id == "G-0B":
            proof = gate.get("validation", {})
            require(
                proof.get("production_sdp_wasm") is True
                and len(set(proof.get("browsers", []))) >= 2,
                "G-0B: production SDP proof in at least two browsers required",
            )
    covered = {finding for wp in wps if corrective(wp) for finding in wp.get("findings", [])}
    require(
        set(state.get("audit_reference", {}).get("confirmed_findings", [])) <= covered,
        "Confirmed finding has no corrective WorkPackage",
    )
    stable_claim = (
        state.get("release_status") == "stable"
        or state.get("audit_reference", {}).get("verdict") == "APPROVED_FOR_STABLE_WEB_RELEASE"
    )
    if stable_claim:
        require(
            all(gate["status"] == "ACCEPTED_BY_F9" for gate in state["gates"].values()),
            "Stable release requires every mandatory gate to pass",
        )
        release = state.get("release_governance", {})
        require(release.get("status") == "VERIFIED", "Stable release requires server evidence")
        evidence_file(root, release.get("evidence_ref"))
    return {
        "work_packages": len(wps),
        "accepted": sum(w["status"] == "ACCEPTED_BY_F9" for w in wps),
        "corrective_packages": sum(corrective(w) for w in wps),
    }


def select_next_work_package(state):
    by_id = {w["wp_id"]: w for w in state["work_packages"]}
    return next(
        (
            w
            for w in state["work_packages"]
            if w["status"] == "PENDING"
            and not w.get("external_blockers")
            and all(by_id[d]["status"] == "ACCEPTED_BY_F9" for d in w.get("dependencies", []))
        ),
        None,
    )


def validate_transition(previous, current, root=ROOT):
    validate_state(current, root)
    for name, old in previous["gates"].items():
        new = current["gates"][name]
        if old["status"] == "ACCEPTED_BY_F9" and new["status"] != "ACCEPTED_BY_F9":
            require(
                new.get("historical_acceptance", {}).get("status") == "ACCEPTED_BY_F9"
                and bool(new.get("blocking_findings")),
                f"{name}: lost acceptance history",
            )
            evidence_file(Path(root), new.get("audit_ref"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(
        json.dumps(
            validate_state(json.loads((args.root / "PROJECT_STATE.json").read_text()), args.root),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
