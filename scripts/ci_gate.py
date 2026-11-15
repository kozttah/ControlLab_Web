"""Run mandatory suites; a missing suite is a blocked gate, never a pass."""

import argparse
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "D": ("tests/wasm", "tests/performance"),
    "E": ("tests/e2e",),
    "F": ("tests/security",),
    "G": ("tests/wasm", "tests/e2e", "tests/security", "tests/performance", "tests/metamorphic"),
}


def unresolved_release_gates(state):
    """A passing fallback test does not approve the missing production capability."""
    return [
        name
        for name in ("G-0A", "G-0B", "G-0C", "G-0D")
        if state.get("gates", {}).get(name, {}).get("status") != "ACCEPTED_BY_F9"
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job", choices=SUITES)
    args = parser.parse_args()
    suites = SUITES[args.job]
    reports = Path(os.environ.get("CONTROLLAB_CI_REPORTS", ROOT / "reports"))
    reports.mkdir(exist_ok=True)
    report = reports / f"job-{args.job}.json"
    missing = [name for name in suites if not list((ROOT / name).glob("test_*.py"))]
    if missing:
        report.write_text(
            json.dumps({"job": args.job, "status": "blocked", "missing_suites": missing}, indent=2)
            + "\n"
        )
        print(
            f"BLOCKED Job {args.job}: required real suites missing: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *suites,
            "-v",
            "-rA",
            f"--junitxml={reports / f'{args.job}.xml'}",
        ],
        cwd=ROOT,
        check=False,
    )
    status = result.returncode
    xml = reports / f"{args.job}.xml"
    if status == 0:
        tree = ET.parse(xml)
        cases = tree.findall(".//testcase")
        if not cases or any(case.find("skipped") is not None for case in cases):
            print(
                "BLOCKED: mandatory gates cannot pass through empty/skipped/xfail suites",
                file=sys.stderr,
            )
            status = 2
    blockers = []
    if status == 0 and args.job in {"E", "G"}:
        state = json.loads((ROOT / "PROJECT_STATE.json").read_text())
        blockers = unresolved_release_gates(state)
        if args.job == "E":
            blockers = [name for name in blockers if name == "G-0D"]
        if blockers:
            print(
                "BLOCKED: mandatory product gates lack F9 acceptance: " + ", ".join(blockers),
                file=sys.stderr,
            )
            status = 2
    report.write_text(
        json.dumps(
            {
                "job": args.job,
                "status": "passed" if status == 0 else "blocked",
                "returncode": status,
                "blocking_gates": blockers,
            },
            indent=2,
        )
        + "\n"
    )
    return status


if __name__ == "__main__":
    sys.exit(main())
