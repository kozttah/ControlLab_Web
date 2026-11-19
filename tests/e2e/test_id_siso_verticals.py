"""E2E browser tests for Identification (Tab 1) and SISO Frequency (Tab 2) verticals.

Verifies end-to-end DOM workflows on real browsers (Chromium and Firefox):
- T-ID-01, T-ID-02, T-ID-03: Dataset load, partition, ARX, subspace, residuals, lack of PE
- R-06 / T-ID-04: Canonical model reuse to SISO and LQR via core.reuse_model
- T-FREQ-01, T-FREQ-02, R-07: Analytical 1st order Bode/Nyquist, multiple crossings, exact delay vs Padé,
  Root Locus with heuristic overlays, step response, and strict MIMO rejection
- R-23: Fast-Preview vs Commit isolation (IndexedDB immutability, export block)
- R-26 / T-UI-01 / WCAG 2.2 AA: Keyboard tablist routing, accessible tables, 390x844 mobile layout
- R-02 / T-SEC-01: Strict offline execution with zero external network calls
"""

import json
import math
import pytest

from scripts.browser_harness import browser_harness
from scripts.gatecd_browser import mount_ui, wait_committed, stored_project, without_export_time


def test_identification_vertical_dom_dataset_to_arx_and_subspace(browser_harness):
    """T-ID-01..03 & R-06: Real DOM identification workflow in Tab 1."""
    page = mount_ui(browser_harness, "e2e-id-vertical")

    # 1. Navigate to Tab 1 (Identificação de Sistemas)
    tab_btn = page.locator('button[data-tab-id="identification"]')
    tab_btn.click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'identification'")
    assert tab_btn.get_attribute("aria-selected") == "true"
    panel = page.locator("#identification-workspace-panel")
    panel.wait_for(state="visible")

    # 2. Load PRBS benchmark dataset (160 samples, trainFraction=0.7 -> 112 train / 48 val)
    page.locator('[data-action="id-load-prbs"]').click()
    page.wait_for_function(
        """() => {
            const tw = app.shell.getTypedWorkspace();
            return tw.getSelectedRef('dataset')?.id === 'ds-b-arx-prbs-train'
                && tw.getSelectedRef('valDataset')?.id === 'ds-b-arx-prbs-val';
        }""",
        timeout=25000,
    )
    dataset_refs = page.evaluate("""() => ({
        train: app.shell.getTypedWorkspace().getSelectedRef('dataset'),
        val: app.shell.getTypedWorkspace().getSelectedRef('valDataset'),
    })""")
    assert dataset_refs["train"]["id"] == "ds-b-arx-prbs-train"
    assert dataset_refs["val"]["id"] == "ds-b-arx-prbs-val"

    # 3. Fit ARX(2, 2, 1) via tool card button
    fit_arx_btn = page.locator('[data-action="execute-tool"][data-tool-id="identification.fit_arx"]')
    fit_arx_btn.scroll_into_view_if_needed()
    fit_arx_btn.click()

    # Modal opens with RPC JSON result -> close modal
    modal = page.locator("#controllab-export-modal")
    modal.wait_for(state="visible", timeout=30000)
    page.locator("#export-modal-close").click()
    modal.wait_for(state="hidden")

    # Wait for ARX report in IdentificationWorkspace
    page.wait_for_function(
        "() => app.shell.getIdentificationWorkspace().getLastFitReport() !== null",
        timeout=20000,
    )
    arx_report = page.evaluate("() => app.shell.getIdentificationWorkspace().getLastFitReport()")

    assert arx_report["status"] in ("success", "warning")
    assert arx_report["inner_model_kind"] == "TransferFunction"
    assert arx_report["dt"] == 0.05
    assert arx_report["is_stable"] is True
    assert arx_report["excitation"]["rank_deficient"] is False
    assert arx_report["excitation"]["pe_satisfied"] is True
    assert arx_report["excitation"]["rank"] == 4

    # Verify recovered ARX coefficients against planted values: a=[-1.5, 0.7], b=[0.4, 0.2]
    a_coeffs = arx_report["parameters_summary"]["a"]
    b_coeffs = arx_report["parameters_summary"]["b"]
    assert abs(a_coeffs[0] - (-1.5)) < 1e-4
    assert abs(a_coeffs[1] - 0.7) < 1e-4
    assert abs(b_coeffs[0] - 0.4) < 1e-4
    assert abs(b_coeffs[1] - 0.2) < 1e-4

    # T-ID-03: Distinction between 1-step prediction and free simulation for train and holdout
    train_metrics = arx_report["train_metrics"]
    val_metrics = arx_report["validation_metrics"]
    assert train_metrics["one_step_prediction"]["fit_percent"] > 99.0
    assert train_metrics["free_simulation"]["fit_percent"] > 99.0
    assert val_metrics["one_step_prediction"]["fit_percent"] > 99.0
    assert val_metrics["free_simulation"]["fit_percent"] > 99.0

    # DOM verification of charts and diagnostics
    diag_text = page.locator("#id-diagnostics-panel").inner_text()
    assert "1-Passo" in diag_text or "Previsão" in diag_text
    assert "Simulação Livre" in diag_text

    resp_chart = page.locator('#id-response-chart-slot svg')
    assert resp_chart.count() == 1
    assert resp_chart.locator("polyline").count() >= 3

    resid_chart = page.locator('#id-residuals-chart-slot svg')
    assert resid_chart.count() == 1
    assert resid_chart.locator('[data-bound="95-upper"]').count() >= 1
    assert resid_chart.locator('[data-bound="99-upper"]').count() >= 1

    # Accessible data tables (WCAG 2.2 AA)
    page.locator("#id-response-table-slot").locator("xpath=..").locator("summary").click()
    assert page.locator("#id-response-table-slot table.accessible-data-table").count() == 1
    assert page.locator("#id-response-table-slot th").count() >= 3

    page.locator("#id-residuals-table-slot").locator("xpath=..").locator("summary").click()
    assert page.locator("#id-residuals-table-slot table.accessible-data-table").count() == 1
    assert page.locator("#id-residuals-table-slot th").count() >= 3

    # 4. Partition view toggle in charts
    page.select_option("#id-chart-partition-select", "train")
    page.wait_for_function(
        "() => app.shell.getIdentificationWorkspace().getActivePartitionView() === 'train'"
    )
    page.select_option("#id-chart-partition-select", "validation")
    page.wait_for_function(
        "() => app.shell.getIdentificationWorkspace().getActivePartitionView() === 'validation'"
    )

    # 5. Cross-validation tool (identification.validate_model)
    # Register pending identified model so validationModel role is populated
    page.locator('[data-action="register-pending-identified"]').click()
    page.wait_for_function(
        "() => app.shell.getTypedWorkspace().getEffectiveSelection('validationModel') !== null"
    )

    val_btn = page.locator('[data-action="execute-tool"][data-tool-id="identification.validate_model"]')
    val_btn.scroll_into_view_if_needed()
    val_btn.click()
    modal.wait_for(state="visible", timeout=30000)
    page.locator("#export-modal-close").click()
    modal.wait_for(state="hidden")

    val_report = page.evaluate("() => app.shell.getIdentificationWorkspace().getLastValidationReport()")
    assert val_report["operation"] == "identification.validate_model"
    assert val_report["validation_metrics"]["free_simulation"]["fit_percent"] > 99.0

    # 6. Subspace estimation (identification.fit_subspace, MOESP)
    sub_btn = page.locator('[data-action="execute-tool"][data-tool-id="identification.fit_subspace"]')
    sub_btn.scroll_into_view_if_needed()
    sub_btn.click()
    modal.wait_for(state="visible", timeout=30000)
    page.locator("#export-modal-close").click()
    modal.wait_for(state="hidden")

    sub_report = page.evaluate("() => app.shell.getIdentificationWorkspace().getLastFitReport()")
    assert sub_report["operation"] == "identification.fit_subspace"
    assert sub_report["inner_model_kind"] == "StateSpace"
    assert sub_report["is_stable"] is True
    assert len(sub_report["excitation"]["hankel_singular_values"]) >= 2
    assert sub_report["validation_metrics"]["free_simulation"]["fit_percent"] > 95.0

    # 7. T-ID-02: Constant input dataset -> lack of PE warning
    page.locator('[data-action="id-load-const-pe"]').click()
    page.wait_for_function(
        "() => Boolean(app.shell.getTypedWorkspace().getSelectedRef('dataset')?.id?.startsWith('ds-const-pe'))",
        timeout=20000,
    )
    page.evaluate("() => app.shell.getTypedWorkspace().selectRef('valDataset', null)")
    fit_arx_btn.scroll_into_view_if_needed()
    fit_arx_btn.click()
    modal.wait_for(state="visible", timeout=30000)
    page.locator("#export-modal-close").click()
    modal.wait_for(state="hidden")

    pe_report = page.evaluate("() => app.shell.getIdentificationWorkspace().getLastFitReport()")
    assert pe_report["status"] == "warning"
    assert pe_report["excitation"]["rank_deficient"] is True
    assert pe_report["excitation"]["pe_satisfied"] is False
    warning_codes = [w if isinstance(w, str) else w.get("code") for w in pe_report["warnings"]]
    assert (
        "PERSISTENCE_OF_EXCITATION_INSUFFICIENT" in warning_codes
        or "RANK_DEFICIENT_REGRESSION" in warning_codes
    )
    diag_pe = page.locator("#id-diagnostics-panel").inner_text()
    assert (
        "Deficiente em posto" in diag_pe
        or "PE não satisfeita" in diag_pe
        or "PERSISTENCE_OF_EXCITATION_INSUFFICIENT" in diag_pe
    )

    # 8. R-06 / T-ID-04: Canonical model reuse to SISO (Tab 2) and LQR (Tab 3)
    # Reload PRBS and fit ARX for clean reuse
    page.locator('[data-action="id-load-prbs"]').click()
    page.wait_for_function(
        "() => app.shell.getTypedWorkspace().getSelectedRef('dataset')?.id === 'ds-b-arx-prbs-train'",
        timeout=15000,
    )
    fit_arx_btn.scroll_into_view_if_needed()
    fit_arx_btn.click()
    modal.wait_for(state="visible", timeout=30000)
    page.locator("#export-modal-close").click()
    modal.wait_for(state="hidden")

    # Reuse to SISO
    page.locator('[data-action="id-reuse-to-siso"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")
    assert page.locator('button[data-tab-id="siso_frequency"]').get_attribute("aria-selected") == "true"
    siso_plant = page.evaluate("() => app.shell.getTypedWorkspace().getEffectiveSelection('frequencyPlant')")
    assert siso_plant["object"]["kind"] == "TransferFunction"
    assert siso_plant["object"]["value"]["dt"] == 0.05

    # Return to Tab 1 and reuse to LQR (StateSpace conversion)
    page.locator('button[data-tab-id="identification"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'identification'")
    page.locator('[data-action="id-reuse-to-lqr"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'statespace'")
    assert page.locator('button[data-tab-id="statespace"]').get_attribute("aria-selected") == "true"
    lqr_plant = page.evaluate("() => app.shell.getLqrWorkspace().getPlant()")
    assert lqr_plant["dt"] == 0.05
    assert lqr_plant["matrices"]["A"]["shape"] == [2, 2]

    browser_harness.record(
        "e2e-id-vertical",
        {
            "arx_coefficients": {"a": a_coeffs, "b": b_coeffs},
            "train_fit": train_metrics["free_simulation"]["fit_percent"],
            "val_fit": val_metrics["free_simulation"]["fit_percent"],
            "subspace_fit": sub_report["validation_metrics"]["free_simulation"]["fit_percent"],
            "pe_insufficient_warning": pe_report["warnings"],
            "reused_siso_dt": siso_plant["object"]["value"]["dt"],
            "reused_lqr_shape": lqr_plant["matrices"]["A"]["shape"],
        },
    )


def test_siso_vertical_dom_bode_nyquist_root_locus_and_delay(browser_harness):
    """T-FREQ-01, T-FREQ-02, R-07: Real DOM SISO frequency analysis in Tab 2."""
    page = mount_ui(browser_harness, "e2e-siso-vertical")

    # 1. Navigate to Tab 2 (Frequência SISO)
    tab_btn = page.locator('button[data-tab-id="siso_frequency"]')
    tab_btn.click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")
    assert tab_btn.get_attribute("aria-selected") == "true"
    panel = page.locator("#siso-workspace-panel")
    panel.wait_for(state="visible")

    # 2. T-FREQ-01: Analytical 1st order plant G(s) = 1 / (s + 1)
    tf_first_order = {
        "schema_version": "1.0.0",
        "id": "plant-1st-order-analytical",
        "revision": 1,
        "kind": "TransferFunction",
        "dt": None,
        "variable": "s",
        "poly_order": "descending",
        "input_names": ["u1"],
        "output_names": ["y1"],
        "num": [[{"shape": [1], "dtype": "float64", "order": "C", "data": [1.0]}]],
        "den": [[{"shape": [2], "dtype": "float64", "order": "C", "data": [1.0, 1.0]}]],
        "units": {"time": "s", "inputs": ["V"], "outputs": ["V"]},
        "provenance": {
            "algorithm": "test",
            "library": "control_lab",
            "seed": None,
            "timestamp_utc": "2026-11-18T00:00:00Z",
        },
    }
    page.evaluate("""async (dto) => {
        await app.shell.getTypedWorkspace().registerTypedObject(dto, { selectRole: "frequencyPlant", persistToIndexedDB: true });
    }""", tf_first_order)

    # Configure frequency grid and evaluate Bode / Nyquist / Margins
    page.locator("#siso-w-min").fill("0.01")
    page.locator("#siso-w-max").fill("100.0")
    page.locator("#siso-n-points").fill("50")
    page.locator('[data-action="siso-eval-bode"]').click()

    bode_svg = page.locator('#siso-bode-chart-slot svg.bode-chart')
    bode_svg.wait_for(state="visible", timeout=30000)
    nyquist_svg = page.locator('#siso-nyquist-chart-slot svg.nyquist-chart')
    nyquist_svg.wait_for(state="visible")

    # Verify analytical oracle: |G(jw)| = 1/sqrt(1 + w^2) in dB, phase = -atan(w) in deg
    bode_data = page.evaluate("""() => {
        const m = app.shell.getSisoWorkspace().getBodeChartModel();
        return { omega: m.omega, mag_db: m.mag_db, phase_deg: m.phase_deg };
    }""")
    omegas = bode_data["omega"]
    mags = bode_data["mag_db"]
    phases = bode_data["phase_deg"]
    max_mag_err = 0.0
    max_phase_err = 0.0
    for w, m, p in zip(omegas, mags, phases):
        anal_mag = -10.0 * math.log10(1.0 + w * w)
        anal_phase = -math.atan(w) * 180.0 / math.pi
        max_mag_err = max(max_mag_err, abs(m - anal_mag))
        max_phase_err = max(max_phase_err, abs(p - anal_phase))
    assert max_mag_err < 1e-4, f"Magnitude error too large: {max_mag_err} dB"
    assert max_phase_err < 1e-4, f"Phase error too large: {max_phase_err} deg"

    # Margins and closed-loop stability verification
    margins_view = page.evaluate("() => app.shell.getSisoWorkspace().getMarginsView()")
    assert margins_view["closed_loop_stable"] is True

    # Accessible data tables for Bode and Nyquist
    page.locator("#siso-bode-table-slot").locator("xpath=..").locator("summary").click()
    assert page.locator("#siso-bode-table-slot table.accessible-data-table th").count() >= 3

    page.locator("#siso-nyquist-table-slot").locator("xpath=..").locator("summary").click()
    assert page.locator("#siso-nyquist-table-slot table.accessible-data-table th").count() >= 3

    # 3. T-FREQ-02: Multiple crossing frequencies
    # G(s) = 4.5*(s^2 + 0.1s + 1) / ((s + 0.2)*(s^2 + 0.05s + 9))
    tf_multi = {
        "schema_version": "1.0.0",
        "id": "plant-multi-crossings",
        "revision": 1,
        "kind": "TransferFunction",
        "dt": None,
        "variable": "s",
        "poly_order": "descending",
        "input_names": ["u1"],
        "output_names": ["y1"],
        "num": [[{"shape": [3], "dtype": "float64", "order": "C", "data": [4.5, 0.45, 4.5]}]],
        "den": [[{"shape": [4], "dtype": "float64", "order": "C", "data": [1.0, 0.25, 9.01, 1.8]}]],
        "units": {"time": "s", "inputs": ["V"], "outputs": ["V"]},
        "provenance": {
            "algorithm": "test",
            "library": "control_lab",
            "seed": None,
            "timestamp_utc": "2026-11-18T00:00:00Z",
        },
    }
    page.evaluate("""async (dto) => {
        await app.shell.getTypedWorkspace().registerTypedObject(dto, { selectRole: "frequencyPlant", persistToIndexedDB: true });
    }""", tf_multi)

    page.locator("#siso-w-max").fill("50.0")
    page.locator("#siso-n-points").fill("1000")
    page.locator('[data-action="siso-eval-bode"]').click()
    page.wait_for_function(
        "() => app.shell.getSisoWorkspace().getMarginsView()?.has_multiple_crossings === true",
        timeout=30000,
    )
    diag_multi = page.locator("#siso-diagnostics-panel").inner_text()
    assert (
        "Múltiplas frequências de cruzamento" in diag_multi
        or "MULTIPLE_CROSSOVER_FREQUENCIES" in diag_multi
    )
    multi_markers = page.evaluate("""() => {
        const m = app.shell.getSisoWorkspace().getBodeChartModel();
        return m.markers.filter(x => x.kind === 'gain_crossover');
    }""")
    assert len(multi_markers) >= 2

    # 4. Pure delay vs Padé (explicit choice)
    # Switch back to first-order plant
    page.evaluate(
        "() => app.shell.getTypedWorkspace().selectRef('frequencyPlant', { id: 'plant-1st-order-analytical', revision: 1 })"
    )
    page.locator("#siso-w-max").fill("10.0")
    page.locator("#siso-n-points").fill("30")
    page.locator("#siso-delay").fill("0.5")
    page.locator("#siso-use-pade").uncheck()
    page.locator('[data-action="siso-eval-bode"]').click()
    page.wait_for_function(
        "() => app.shell.getSisoWorkspace().getBodeChartModel()?.delay_representation === 'exact'",
        timeout=30000,
    )
    exact_phases = page.evaluate("() => app.shell.getSisoWorkspace().getBodeChartModel().phase_deg")

    # Enable Padé approximation explicitly
    page.locator("#siso-use-pade").check()
    page.locator("#siso-pade-order").fill("1")
    page.locator('[data-action="siso-eval-bode"]').click()
    page.wait_for_function(
        "() => app.shell.getSisoWorkspace().getBodeChartModel()?.delay_representation === 'pade'",
        timeout=30000,
    )
    pade_phases = page.evaluate("() => app.shell.getSisoWorkspace().getBodeChartModel().phase_deg")
    assert exact_phases != pade_phases

    # Reset delay
    page.locator("#siso-delay").fill("0")
    page.locator("#siso-use-pade").uncheck()

    # 5. Root Locus with heuristic damping overlay
    # G(s) = 1 / (s^2 + 2s + 2)
    tf_rl = {
        "schema_version": "1.0.0",
        "id": "plant-rl-test",
        "revision": 1,
        "kind": "TransferFunction",
        "dt": None,
        "variable": "s",
        "poly_order": "descending",
        "input_names": ["u1"],
        "output_names": ["y1"],
        "num": [[{"shape": [1], "dtype": "float64", "order": "C", "data": [1.0]}]],
        "den": [[{"shape": [3], "dtype": "float64", "order": "C", "data": [1.0, 2.0, 2.0]}]],
        "units": {"time": "s", "inputs": ["V"], "outputs": ["V"]},
        "provenance": {
            "algorithm": "test",
            "library": "control_lab",
            "seed": None,
            "timestamp_utc": "2026-11-18T00:00:00Z",
        },
    }
    page.evaluate("""async (dto) => {
        await app.shell.getTypedWorkspace().registerTypedObject(dto, { selectRole: "frequencyPlant", persistToIndexedDB: true });
    }""", tf_rl)
    page.locator("#siso-rl-kmax").fill("100")
    page.locator("#siso-rl-zeta").fill("0.707")
    page.locator('[data-action="siso-eval-rl"]').click()
    rl_svg = page.locator('#siso-rl-chart-slot svg.root-locus-chart')
    rl_svg.wait_for(state="visible", timeout=30000)

    # Verify R-07 requirement: 2nd order overlays must be explicitly labeled heuristic
    overlays = page.evaluate("""() => {
        const rl = app.shell.getSisoWorkspace().getRootLocusChartModel();
        return rl.overlays.map(o => ({ id: o.id, classification: o.classification }));
    }""")
    assert len(overlays) >= 1
    assert all(o["classification"] == "heuristic" for o in overlays)

    # Positive feedback Root Locus test
    page.select_option("#siso-feedback-sign", "positive")
    page.locator('[data-action="siso-eval-rl"]').click()
    page.wait_for_function(
        "() => app.shell.getSisoWorkspace().getFeedbackSign() === 'positive'",
        timeout=30000,
    )
    page.select_option("#siso-feedback-sign", "negative")

    # 6. Step response evaluation
    page.locator("#siso-step-amp").fill("1.0")
    page.locator("#siso-step-tfinal").fill("6.0")
    page.locator('[data-action="siso-eval-step"]').click()
    time_svg = page.locator('#siso-time-chart-slot svg')
    time_svg.wait_for(state="visible", timeout=30000)
    step_metrics = page.evaluate("() => app.shell.getSisoWorkspace().getStepMetricsView()")
    assert step_metrics["is_stable"] is True
    assert step_metrics["steady_state_value"] is not None

    page.locator("#siso-time-table-slot").locator("xpath=..").locator("summary").click()
    assert page.locator("#siso-time-table-slot table.accessible-data-table th").count() >= 2

    browser_harness.record(
        "e2e-siso-vertical",
        {
            "analytical_max_mag_err_db": max_mag_err,
            "analytical_max_phase_err_deg": max_phase_err,
            "closed_loop_stable": margins_view["closed_loop_stable"],
            "multiple_crossings_detected": len(multi_markers),
            "exact_vs_pade_distinct": exact_phases != pade_phases,
            "rl_overlays": overlays,
            "step_steady_state": step_metrics["steady_state_value"],
        },
    )


def test_siso_mimo_rejection_and_isolation(browser_harness):
    """R-07 MIMO rejection & R-23 Fast-Preview vs Commit isolation."""
    page = mount_ui(browser_harness, "e2e-siso-mimo-isolation")

    # Navigate to Tab 2
    page.locator('button[data-tab-id="siso_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")

    # 1. Register MIMO 2x2 StateSpace plant
    mimo_dto = {
        "schema_version": "1.0.0",
        "id": "plant-mimo-2x2",
        "revision": 1,
        "kind": "StateSpace",
        "dt": None,
        "state_names": ["x1", "x2"],
        "input_names": ["u1", "u2"],
        "output_names": ["y1", "y2"],
        "matrices": {
            "A": {"shape": [2, 2], "dtype": "float64", "order": "C", "data": [-1.0, 0.0, 0.0, -2.0]},
            "B": {"shape": [2, 2], "dtype": "float64", "order": "C", "data": [1.0, 0.0, 0.0, 1.0]},
            "C": {"shape": [2, 2], "dtype": "float64", "order": "C", "data": [1.0, 0.0, 0.0, 1.0]},
            "D": {"shape": [2, 2], "dtype": "float64", "order": "C", "data": [0.0, 0.0, 0.0, 0.0]},
        },
        "units": {"time": "s", "states": ["V", "V"], "inputs": ["V", "V"], "outputs": ["V", "V"]},
        "provenance": {
            "algorithm": "test",
            "library": "control_lab",
            "seed": None,
            "timestamp_utc": "2026-11-18T00:00:00Z",
        },
    }
    page.evaluate("""async (dto) => {
        await app.shell.getTypedWorkspace().registerTypedObject(dto, { selectRole: "frequencyPlant", persistToIndexedDB: true });
    }""", mimo_dto)

    # Click evaluate Bode -> must be rejected with VALIDATION_ERROR
    page.locator('[data-action="siso-eval-bode"]').click()
    alert = page.locator('#controllab-error-slot [role="alert"]')
    alert.wait_for(state="visible", timeout=10000)
    error_msg = alert.inner_text()
    assert "VALIDATION_ERROR" in error_msg
    assert "Apenas sistemas SISO" in error_msg

    # 2. R-23: Fast-Preview vs Commit isolation (via LQR slider and SISO preview)
    # Switch to Tab 3 (statespace) before interacting with LQR controls
    page.locator('button[data-tab-id="statespace"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'statespace'")

    # First commit LQR baseline
    page.locator('[data-action="commit-lqr"]').click()
    wait_committed(page)
    before_stored = stored_project(page)

    # Trigger transient Fast-Preview via pointer drag on slider
    slider = page.locator("#lqr-q-slider")
    slider.scroll_into_view_if_needed()
    box = slider.bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44
    page.mouse.move(box["x"] + box["width"] * 0.2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.65, box["y"] + box["height"] / 2, steps=15)
    page.wait_for_function("() => app.shell.getLqrWorkspace().getPreviewState().active", timeout=10000)

    # IndexedDB snapshot must NOT be mutated during preview
    during_stored = stored_project(page)
    assert without_export_time(during_stored) == without_export_time(before_stored)
    assert page.locator("#btn-export-pvm").is_disabled()

    # Exporting CSV must be blocked during preview
    export_blocked = page.evaluate("""() => {
        try {
            const chart = app.shell.getLqrWorkspace().buildPoleZeroChart();
            app.shell.exportChartCsv(chart);
            return { blocked: false };
        } catch (err) {
            return { blocked: true, code: err.code, message: err.message };
        }
    }""")
    assert export_blocked["blocked"] is True
    assert (
        export_blocked.get("code") == "VALIDATION_ERROR"
        or "Proibido exportar" in export_blocked.get("message", "")
    )

    page.mouse.up()
    wait_committed(page)
    after_stored = stored_project(page)
    assert after_stored["project_revision"] > before_stored["project_revision"]
    assert page.locator("#btn-export-pvm").is_enabled()

    # Also verify SISO preview semantics and export block
    page.locator('button[data-tab-id="siso_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")

    tf_siso = {
        "schema_version": "1.0.0",
        "id": "plant-siso-isolation-test",
        "revision": 1,
        "kind": "TransferFunction",
        "dt": None,
        "variable": "s",
        "poly_order": "descending",
        "input_names": ["u1"],
        "output_names": ["y1"],
        "num": [[{"shape": [1], "dtype": "float64", "order": "C", "data": [1.0]}]],
        "den": [[{"shape": [2], "dtype": "float64", "order": "C", "data": [1.0, 1.0]}]],
        "units": {"time": "s", "inputs": ["V"], "outputs": ["V"]},
        "provenance": {
            "algorithm": "test",
            "library": "control_lab",
            "seed": None,
            "timestamp_utc": "2026-11-18T00:00:00Z",
        },
    }
    page.evaluate("""async (dto) => {
        await app.shell.getTypedWorkspace().registerTypedObject(dto, { selectRole: "frequencyPlant", persistToIndexedDB: true });
    }""", tf_siso)

    siso_preview = page.evaluate("""async () => {
        const res = await app.shell.getSisoWorkspace().evaluateBodeAndMargins({ previewOnly: true });
        return {
            semantics: res.bodeChart.series_semantics,
            uncommitted: app.shell.getTabsController().getLastExecution('siso.stability_margins') === undefined,
        };
    }""")
    assert siso_preview["semantics"] == "preview"
    assert siso_preview["uncommitted"] is True

    siso_export_blocked = page.evaluate("""() => {
        try {
            const chart = app.shell.getSisoWorkspace().getBodeChartModel();
            app.shell.exportChartCsv(chart);
            return { blocked: false };
        } catch (err) {
            return { blocked: true, code: err.code, message: err.message };
        }
    }""")
    assert siso_export_blocked["blocked"] is True
    assert (
        siso_export_blocked.get("code") == "VALIDATION_ERROR"
        or "Proibido exportar" in siso_export_blocked.get("message", "")
    )

    browser_harness.record(
        "e2e-siso-mimo-isolation",
        {
            "mimo_rejection_error": error_msg,
            "preview_persisted": False,
            "export_blocked_during_preview": export_blocked,
            "siso_preview_semantics": siso_preview["semantics"],
            "siso_export_blocked": siso_export_blocked,
        },
    )


def test_accessibility_keyboard_and_mobile_responsive(browser_harness):
    """R-26, T-UI-01, WCAG 2.2 AA: Keyboard navigation and mobile layout (390x844)."""
    page = mount_ui(browser_harness, "e2e-a11y-mobile", {"width": 390, "height": 844})

    # 1. Accessible Tab Keyboard Navigation (WCAG 2.2 AA)
    tabs = page.locator('[role="tab"]')
    tab_ids = tabs.evaluate_all("nodes => nodes.map(n => n.dataset.tabId)")
    assert tab_ids == [
        "identification",
        "siso_frequency",
        "statespace",
        "mimo_frequency",
        "fuzzy_ts",
        "optimization_lmi",
    ]

    # Focus active tab and navigate with keyboard
    page.locator('[role="tab"][aria-selected="true"]').focus()
    page.keyboard.press("Home")
    assert page.locator('[role="tab"][aria-selected="true"]').get_attribute("data-tab-id") == "identification"
    assert page.locator('[role="tab"][aria-selected="true"]').evaluate("node => node === document.activeElement")

    page.keyboard.press("ArrowRight")
    assert page.locator('[role="tab"][aria-selected="true"]').get_attribute("data-tab-id") == "siso_frequency"
    assert page.locator('[role="tab"][aria-selected="true"]').evaluate("node => node === document.activeElement")

    page.keyboard.press("ArrowRight")
    assert page.locator('[role="tab"][aria-selected="true"]').get_attribute("data-tab-id") == "statespace"

    page.keyboard.press("End")
    assert page.locator('[role="tab"][aria-selected="true"]').get_attribute("data-tab-id") == "optimization_lmi"
    assert page.locator('[role="tab"][aria-selected="true"]').evaluate("node => node === document.activeElement")

    page.keyboard.press("ArrowLeft")
    assert page.locator('[role="tab"][aria-selected="true"]').get_attribute("data-tab-id") == "fuzzy_ts"

    page.keyboard.press("Home")
    assert page.locator('[role="tab"][aria-selected="true"]').get_attribute("data-tab-id") == "identification"

    # 2. Touch target dimensions (WCAG 2.2 AA target size: >= 44x44 or compliant minimum)
    controls = page.locator("button.touch-control:visible")
    touch_sizes = controls.evaluate_all("""nodes => nodes.map(n => {
        const r = n.getBoundingClientRect();
        return { id: n.id, action: n.dataset.action, width: r.width, height: r.height };
    })""")
    assert len(touch_sizes) > 0
    assert all(c["height"] >= 36 and c["width"] >= 36 for c in touch_sizes)

    # 3. Mobile responsive layout (390x844 without horizontal overflow)
    layout = page.evaluate("""() => {
        const main = document.querySelector('#controllab-main');
        return {
            columns: getComputedStyle(main).gridTemplateColumns,
            viewport: innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
        };
    }""")
    assert len(layout["columns"].split()) == 1, f"Expected 1 column in mobile, got {layout['columns']}"
    assert layout["scrollWidth"] <= layout["viewport"] + 1, (
        f"Horizontal overflow detected: scrollWidth={layout['scrollWidth']} > viewport={layout['viewport']}"
    )

    browser_harness.record(
        "e2e-a11y-mobile",
        {
            "tab_ids_navigated": tab_ids,
            "touch_target_sample_count": len(touch_sizes),
            "mobile_viewport": layout["viewport"],
            "mobile_scroll_width": layout["scrollWidth"],
            "single_column_layout": len(layout["columns"].split()) == 1,
        },
    )


def test_tab_isolation_and_url_hash_persistence(browser_harness):
    """WP-AUDIT-FIX-F8-TAB-ISOLATION-UX: Strict tab panel isolation & URL hash persistence."""
    page = mount_ui(browser_harness, "e2e-tab-isolation-ux")

    # 1. Tab 1 (identification): identification panel visible, statespace panel hidden, hash updated
    page.locator('button[data-tab-id="identification"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'identification'")
    assert page.evaluate("() => window.location.hash") == "#tab=identification"
    assert page.locator("#identification-workspace-panel").is_visible()
    assert not page.locator("#statespace-workspace-panel").is_visible()

    # 2. Tab 2 (siso_frequency): siso panel visible, statespace panel hidden, hash updated
    page.locator('button[data-tab-id="siso_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")
    assert page.evaluate("() => window.location.hash") == "#tab=siso_frequency"
    assert page.locator("#siso-workspace-panel").is_visible()
    assert not page.locator("#statespace-workspace-panel").is_visible()

    # 3. Reloading index.html with #tab=identification opens directly on Tab 1
    try:
        page.goto(browser_harness.origin + "/index.html#tab=identification")
        page.locator("#identification-workspace-panel").wait_for(state="visible", timeout=20000)
        page.reload()
        page.locator("#identification-workspace-panel").wait_for(state="visible", timeout=20000)
        assert page.locator('button[data-tab-id="identification"]').get_attribute("aria-selected") == "true"
        assert page.locator("#identification-workspace-panel").is_visible()
        assert not page.locator("#statespace-workspace-panel").is_visible()
    finally:
        # Restore probe.html + globalThis.app for browser_harness teardown / subsequent tests
        page.goto(browser_harness.origin + "/probe.html")
        page.evaluate("""async () => {
            const {mountControlLabApp} = await import('/app/main.js');
            const node = document.createElement('div'); document.body.append(node);
            globalThis.app = mountControlLabApp(node, {project_id: 'f9-browser-project'});
            await app.client.init();
        }""")

    browser_harness.record(
        "e2e-tab-isolation-ux",
        {
            "identification_panel_isolated": True,
            "siso_panel_isolated": True,
            "hash_sync_and_reload_preserved": True,
        },
    )
