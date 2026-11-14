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
    "G": ("tests/wasm", "tests/e2e", "tests/security", "tests/performance"),
}


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
    report.write_text(
        json.dumps(
            {
                "job": args.job,
                "status": "passed" if status == 0 else "blocked",
                "returncode": status,
            },
            indent=2,
        )
        + "\n"
    )
    return status


if __name__ == "__main__":
    sys.exit(main())
