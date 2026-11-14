"""Job B: execute every scientific test in its declared optional-dependency environment."""

import argparse
import importlib.util
import json
from pathlib import Path
import site
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "core_no_sdp": [
        *[f"tests/unit/f{i}" for i in range(1, 6)],
        "tests/oracles",
        "tests/integration",
    ],
    "sdp_available": ["tests/unit/f6", "tests/oracles"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("--reports", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    if sys.prefix == sys.base_prefix or site.ENABLE_USER_SITE:
        raise RuntimeError("Job B requires an isolated venv without user-site packages")
    lock_name = (
        "requirements-ci.lock" if args.profile == "sdp_available" else "requirements-core.lock"
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_python_lock.py"),
            str(ROOT / "scripts" / lock_name),
        ],
        check=True,
    )
    present = {name: importlib.util.find_spec(name) is not None for name in ("clarabel", "cvxpy")}
    expected = args.profile == "sdp_available"
    if any(value != expected for value in present.values()):
        raise RuntimeError(f"Wrong Job B environment: {args.profile}, modules={present}")
    sys.path.insert(0, str(ROOT))
    capabilities = {}
    if expected:
        from control_lab.optimization.backends.capabilities import describe_solver_capabilities

        capabilities = describe_solver_capabilities("all")
        for name in ("clarabel_direct", "clarabel_cvxpy"):
            if not capabilities[name]["available"]:
                raise RuntimeError(f"Required backend unavailable: {name}")
    args.reports.mkdir(parents=True, exist_ok=True)
    xml_path = args.reports / f"B-{args.profile}.xml"
    subprocess.run([sys.executable, str(ROOT / "scripts/verify_fixtures.py")], cwd=ROOT, check=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *PROFILES[args.profile],
            "-v",
            "-rA",
            f"--junitxml={xml_path}",
        ],
        cwd=ROOT,
        check=False,
    )
    status = result.returncode
    cases = ET.parse(xml_path).findall(".//testcase") if xml_path.exists() else []
    if not cases or any(case.find("skipped") is not None for case in cases):
        status = status or 2
    (args.reports / f"B-{args.profile}.json").write_text(
        json.dumps(
            {
                "profile": args.profile,
                "python": sys.version,
                "optional_modules": present,
                "backend_available": {
                    name: value["available"] for name, value in capabilities.items()
                },
                "suites": PROFILES[args.profile],
                "tests": len(cases),
                "skipped": sum(case.find("skipped") is not None for case in cases),
                "returncode": status,
            },
            indent=2,
        )
        + "\n"
    )
    return status


if __name__ == "__main__":
    sys.exit(main())
