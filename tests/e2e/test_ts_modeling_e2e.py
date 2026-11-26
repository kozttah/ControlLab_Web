"""E2E Playwright browser test for Tab 6 (ts_modeling: Sector, TPMT & FEMT) -> Workspace -> Tab 7 (LMIs).

Validates on real Chromium + Pyodide Wasm runtime:
- Tab 6 opening & visibility
- TS model derivation (Sector 16-rule pendulum)
- WP-TSMOD-04B Achado 1 stale-derivation guard when switching preset to `nonseparable_benchmark`
- Re-derivation via FEMT and 1-click registration + jump to Tab 7 (`optimization_lmi`)
- Registered TS model visibility in Workspace Dock and Tab 7 (LMIs)
"""

from __future__ import annotations

import json

from scripts.browser_harness import browser_harness
from scripts.gatecd_browser import mount_ui


def test_ts_modeling_tab6_derive_stale_guard_register_and_lmi_visibility(browser_harness) -> None:
    """E2E: Tab 6 derive -> preset switch invalidation guard -> FEMT re-derive -> Workspace -> Tab 7 LMIs."""
    page = mount_ui(browser_harness, "e2e-ts-modeling-tab6")
    page_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    # 1. Navigate to Tab 6 (ts_modeling)
    tab6_btn = page.locator('button[data-tab-id="ts_modeling"]')
    tab6_btn.click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'ts_modeling'", timeout=20000)
    assert tab6_btn.get_attribute("aria-selected") == "true"
    page.locator("#ts-zone-1-toolbar").wait_for(state="visible", timeout=15000)

    # Register button starts disabled before any derivation
    register_btn = page.locator("#btn-ts-register")
    register_lmi_btn = page.locator("#btn-ts-register-open-lmi")
    assert register_btn.is_disabled()
    assert register_lmi_btn.is_disabled()

    # 2. Derive default preset (pendulum_16 via Sector Nonlinearity)
    page.locator("#btn-ts-derive").click()
    page.wait_for_function(
        "() => !document.querySelector('#btn-ts-register')?.disabled",
        timeout=60000,
    )
    summary_text = page.locator("#ts-summary").inner_text()
    assert "16" in summary_text, f"Expected 16 rules in Tab 6 summary, got: {summary_text[:300]}"
    assert not register_btn.is_disabled()
    assert not register_lmi_btn.is_disabled()

    # 3. WP-TSMOD-04B Achado 1: switching preset to `nonseparable_benchmark` must invalidate & disable registration
    page.select_option("#ts-preset-select", "nonseparable_benchmark")
    page.wait_for_function(
        "() => Boolean(document.querySelector('#btn-ts-register')?.disabled)",
        timeout=10000,
    )
    assert register_btn.is_disabled(), "Register button must be disabled after preset switch without re-deriving"
    assert register_lmi_btn.is_disabled(), "Register-and-open-LMI button must be disabled after preset switch"

    # 4. Switch to Via 3 (FEMT), configure fast grid G=9, re-derive, and register + open in Tab 7 (LMIs)
    page.locator("#btn-ts-via-femt").click()
    page.wait_for_function(
        "() => document.querySelector('#btn-ts-via-femt')?.getAttribute('aria-pressed') === 'true'",
        timeout=10000,
    )
    page.locator("#ts-grid-points").fill("9")
    page.locator("#btn-ts-apply-uniform-grid").click()
    page.locator("#ts-val-points").fill("32")

    page.locator("#btn-ts-derive").click()
    page.wait_for_function(
        "() => !document.querySelector('#btn-ts-register-open-lmi')?.disabled",
        timeout=60000,
    )
    assert not register_lmi_btn.is_disabled()

    expected_model_id = page.locator("#ts-model-id-input").input_value().strip()
    assert expected_model_id

    # Click 'Registrar e Abrir em LMIs ->'
    register_lmi_btn.click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'optimization_lmi'", timeout=30000)
    assert page.locator('button[data-tab-id="optimization_lmi"]').get_attribute("aria-selected") == "true"

    # 5. Confirm registered TS model exists in Workspace Dock and is visible in Tab 7 (LMIs)
    workspace_check = page.evaluate(
        """(modelId) => {
            const tw = app.shell.getTypedWorkspace();
            const sel = tw.getEffectiveSelection('tsModel');
            const raw = sel?.object?.value ?? sel?.object ?? null;
            const lmiSelect = document.querySelector('#lmi-ts-model-select, #lmi-plant-select, [data-lmi-role="tsModel"]');
            const bodyText = document.body?.textContent || '';
            return {
                found: Boolean(sel && (sel.ref?.id === modelId || raw?.id === modelId)),
                selectedId: sel?.ref?.id ?? raw?.id ?? null,
                kind: raw?.kind ?? null,
                representationKind: raw?.membership_spec?.representation_kind ?? null,
                numVertices: Array.isArray(raw?.vertices) ? raw.vertices.length : 0,
                inPageText: bodyText.includes(modelId),
                lmiHasOption: lmiSelect ? Array.from(lmiSelect.querySelectorAll('option')).some(o => (o.value || o.textContent || '').includes(modelId)) : null,
            };
        }""",
        expected_model_id,
    )
    assert workspace_check["found"] is True, workspace_check
    assert workspace_check["kind"] in ("ts_measured", "ts_partially_observed"), workspace_check
    assert workspace_check["representationKind"] == "femt_simplicial", workspace_check
    assert workspace_check["numVertices"] >= 2, workspace_check
    assert workspace_check["inPageText"] is True, workspace_check

    worker_stats = page.evaluate("() => app.client.getWorkerStats()")
    assert worker_stats["pyproxy"]["activeProxies"] == 0, worker_stats
    assert not page_errors, f"Unexpected browser page errors: {page_errors}"

    evidence = {
        "preset_stale_guard_verified": True,
        "registered_model_id": expected_model_id,
        **workspace_check,
        "active_proxies": worker_stats["pyproxy"]["activeProxies"],
    }
    print(f"[F9-E2E-PHASE10-TAB6] {json.dumps(evidence)}")
    browser_harness.record("phase10-tab6-e2e", evidence)
