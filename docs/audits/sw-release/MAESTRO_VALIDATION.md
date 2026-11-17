# Maestro validation — WP-AUDIT-FIX-F9-SW-RELEASE-VERSION

Date: 2026-11-17. Initial candidate: `12d7580f1575e958003495ecd0d94ec08671f2ce`; final audited source candidate: `89fb4e048cb787027adb239d35448b42e09d3368`.

- `npm --prefix web test`: **53 passed, zero failures/skips**.
- Exact CI SDP environment, `python -m pytest tests/unit tests/oracles -q`: **373 passed** (10.08 s).
- `python3 scripts/project_governance.py`: **PASS**, candidate remains 35 accepted of 41 until independent review.
- `git diff --check`: **PASS**.

Hosted evidence: https://github.com/kozttah/ControlLab_Web/actions/runs/44194955745 . This document does not itself grant acceptance; the independent F9 handoff records the final browser matrix and verdict.

Local Chromium is unavailable: the installed system binary is denied AF_UNIX sockets by the environment, and the official Playwright headless-shell download returns an explicit network-policy block. No alternative download route or sandbox bypass was attempted. Mandatory Chromium evidence therefore comes from the official hosted CI runtime on the exact candidate SHA. Local Firefox uses the installed real engine; its test fixture also interrupts actual HTTP responses to prove offline behavior of Service Worker requests.

An initial broad local collection of `tests/metamorphic` lacked the Playwright package in the exact scientific venv. This setup error is not reported as a test pass; the 373-test result above covers only unit/oracle suites. Browser-dependent suites are verified by the independent browser evidence and CI.

Final source CI: https://github.com/kozttah/ControlLab_Web/actions/runs/44197401222 . Chromium151 full E2E 13/13; combined G 33/33; dedicated Firefox153 A/B 1/1. Local Firefox full E2E 13/13 and pinned-driver A/B 1/1. The initial Firefox146 failure was corrected by pinning official Playwright1.62, without changing product code or timeout. The B SDP profile had one exact ARX regeneration comparison failure; its single diagnostic rerun on the same SHA passed, and Pages publication passed. The negative evidence and unresolved portability finding remain in ARX_REGENERATION_FOLLOWUP.md; no gold value or tolerance was changed.
