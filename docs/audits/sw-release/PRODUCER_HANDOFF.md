# Producer handoff — WP-AUDIT-FIX-F9-SW-RELEASE-VERSION

Date: 2026-11-17. Producer: F9 integration tooling; independent F9 review required before acceptance. Requirements R-22/R-28, regressions T-SEC-01/T-RPC-01, CL-DIR-001 §§11.2/13.11/15.3 and Appendix E.

## Scope and release identity

Only F9 build, oracle, E2E and CI paths change. `build_web.mjs` first creates the deterministic SBOM, stamps the bundled Service Worker, then creates/verifies the final manifest. `stamp_service_worker.mjs` hashes a sorted path/size/SHA-256 inventory of every distributed file except `service_worker.js` and `release-manifest.json`. Including the SBOM covers licensing and build-tool metadata updates. Excluding the two recursive inputs prevents a hash cycle; changes to the SW body still change its own bytes. The stamp is idempotent and contains no clock, random ID or absolute build path. Fixed Pyodide assets and their licenses remain byte-for-byte unchanged.

## Real product regression

`tests/e2e/test_sw_release_update.py` builds A twice and B once in an isolated source copy. Only the temporary Python provenance module receives an A/B marker; repository scientific sources are never edited. All 43 distributed files (42 manifested assets plus the manifest itself) are compared across repeated A builds. Across A/B only the wheel, SBOM, manifest and stamped SW may change. The real application index, UI, bridge and Worker calculate the analytic double-integrator LQR (`K=[1,sqrt(3)]`). Exported gains report provenance from that actual Python calculation, proving which Python wheel ran.

A provisioned A client attempts B with failed download, corrupt wheel and unavailable transport. Each case requires A's active cache, actual Python A recalculation and persisted IndexedDB projects/objects/snapshots to survive. Valid B must wait while two A clients remain open and both execute A. Closing both permits native activation; a new client must retain saved project records and compute using Python B. An offline reload with unavailable HTTP transport must compute B again. No skipWaiting, runtime test hook, request interception or replacement Worker is used.

The first Firefox test exposed that Playwright's offline context switch alone does not disconnect every Service Worker fetch. The fixture now closes actual server connections while offline in addition to the browser switch. This strengthens the outage test without changing product runtime or acceptance expectations.

CI E runs the full E2E suite in Chromium and this A/B regression separately in Firefox, using officially installed engines. Distinct JSON/XML/log artifacts preserve both runs. CI G retains the full mandatory Chromium suite. Local Chromium availability is tracked by the Maestro; no Firefox result is represented as Chromium evidence.

## Appendix E checklist (producer evidence, not independent acceptance)

1. **Contracts:** existing RPC and release-manifest contracts unchanged; real UI/bridge consumes normal LQR/gains contracts.
2. **Status/provenance:** ready/active cache diagnostics and exported real Python provenance asserted on success and after failed updates.
3. **Analytic tests:** gain display compared with independent analytic double-integrator result; no scientific optimization added.
4. **Independent confrontation:** separate F9 reviewer black-box oracles and full reproducibility run; browser engine enforces native SW lifecycle.
5. **Ownership/fixtures:** F9 paths only; no golden fixture, oracle tolerance, locked runtime asset or F1–F8 source changes. Temporary provenance marker explicitly isolated.
6. **CPython/Pyodide:** CPython assembles deterministic wheel; real Pyodide application recalculates LQR A/B. This change introduces no scientific operation.
7. **Schemas:** none changed; no migration needed. Persisted project records asserted across failure and activation.
8. **Evidence:** oracle tests, build reproducibility evidence and per-engine lifecycle reports accompany review; JSON contains release hashes and actual engine version.
9. **Maturity:** no experimental method or product maturity claim changed.
10. **Limitations:** release waits until all controlled clients close by design; local Chromium restriction requires official CI evidence before final F9 acceptance. WorkPackage remains pending until independent review and both engines pass.

## Commands

```sh
python -m pytest tests/oracles/test_build_pipeline.py tests/oracles/test_sw_release_fingerprint.py tests/oracles/test_sw_release_independent.py -q
CONTROLLAB_SW_RELEASE_REPORT=reports/chromium-sw-release.json python -m pytest tests/e2e/test_sw_release_update.py -v -s
CONTROLLAB_BROWSER=firefox CONTROLLAB_SW_RELEASE_REPORT=reports/firefox-sw-release.json python -m pytest tests/e2e/test_sw_release_update.py -v -s
python scripts/check_reproducible.py
```

Environment overrides `CONTROLLAB_ASSET_CACHE`, `PYTHON` and browser executable paths select existing verified local dependencies; they do not alter the release or weaken browser requirements.

## Producer verification result

- Build/oracle suite: **8 passed** (existing build pipeline, producer fingerprint oracle and independent black-box oracles).
- Firefox 153.0 real two-release regression: **1 passed in 182.01 s**. `firefox-producer.json` records deterministic A/A, wheel-only B, failed download/integrity/offline candidate states, active A preservation, waiting A, activated B, offline B and persisted projects.
- Ruff lint/format on new producer Python tests, Node syntax check and `git diff --check`: passed.
- Chromium: awaiting official CI run and independent F9 conclusion; no local claim of approval.
