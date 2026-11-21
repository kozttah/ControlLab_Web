"""E2E regression suite for CL-UX-DIR-001 modular workbench refactor (WP-UX-REFACTOR-04-F9-BROWSER-AUDIT).

Verifies end-to-end UX and scientific invariants in real browsers (Chromium + Firefox):
1. 3-zone App Shell, Workspace Dock, Guided '+ Novo' modal (TF without JSON),
   1-click SISO routing, collapsible R-27 Inspector Drawer, and Section 2 Semantic Dictionary.
2. SISO click datatips on Bode, Nyquist, and Root Locus (freezing all closed-loop poles on branches
   and clearing via #btn-siso-rl-clear-tip) plus R-23 chart export and preview lock.
3. Tab 4 (MIMO σ + RGA slider), Tab 5 (Fuzzy surface + IEEE 1855 FML export), Tab 6 (Monaco-style
   LMI editor, bilinear BMI detection, bmat formatting, save/load, 5-dimension certificate,
   spectrum SVG, CVXPY export), and zero horizontal overflow across all 6 tabs at 1280x800 & 390x844.
"""

import json

from scripts.browser_harness import browser_harness
from scripts.gatecd_browser import mount_ui, wait_committed

ALL_TAB_IDS = [
    "identification",
    "siso_frequency",
    "statespace",
    "mimo_frequency",
    "fuzzy_ts",
    "optimization_lmi",
]


def test_ux_3zone_shell_dock_guided_modal_and_inspector_r27(browser_harness):
    """Test 1: 3-zone shell, Workspace Dock, R-27 Inspector Drawer, Semantic Dictionary, and '+ Novo' modal."""
    page = mount_ui(browser_harness, "e2e-ux-3zone-dock", {"width": 1280, "height": 800})

    dock_aside = page.locator("#workspace-dock-aside")
    inspector_drawer = page.locator("#inspector-drawer")
    toggle_inspector = page.locator("#btn-toggle-inspector")

    # 1. Dock visible, Inspector hidden by default
    assert dock_aside.is_visible()
    assert not inspector_drawer.is_visible()
    assert toggle_inspector.get_attribute("aria-expanded") == "false"

    # Commit LQR so R-27 telemetry is populated, then open Inspector Drawer
    page.locator('[data-action="commit-lqr"]').click()
    wait_committed(page)

    toggle_inspector.click()
    inspector_drawer.wait_for(state="visible")
    assert toggle_inspector.get_attribute("aria-expanded") == "true"

    telemetry_text = page.locator("#inspector-telemetry-slot").inner_text()
    assert "rCARE=" in telemetry_text
    assert "proj_rev=" in telemetry_text
    assert "model_rev=" in telemetry_text
    assert "SHA-256" in telemetry_text

    canonical_json_text = page.locator("#inspector-json-pre").inner_text()
    parsed_json = json.loads(canonical_json_text)
    assert parsed_json["kind"] == "StateSpace"

    page.locator("#btn-close-inspector").click()
    inspector_drawer.wait_for(state="hidden")
    assert toggle_inspector.get_attribute("aria-expanded") == "false"

    # 2. Verify Section 2 Semantic Translation Dictionary labels on primary UI buttons
    all_btn_texts = page.locator("button").all_inner_texts()
    for btn_text in all_btn_texts:
        assert "core.reuse_model" not in btn_text, f"Raw internal label leaked: {btn_text}"
        assert "IdentifiedModel Pendente" not in btn_text, f"Raw internal label leaked: {btn_text}"

    assert page.locator('[data-action="reuse-model"]').inner_text() == "Converter / Registrar Modelo"
    assert page.locator('[data-action="register-pending-identified"]').inner_text() == "Validar Modelo na Sessão"
    assert page.locator('[data-action="id-load-const-pe"]').inner_text() == "Dataset Entrada Constante (Sem Excitação)"
    assert page.locator('[data-action="build-report"]').inner_text() == "Relatório Científico (R-27)"

    # 3. Guided '+ Novo' modal -> TransferFunction num="2", den="1, 3, 2" without JSON
    page.locator("#btn-open-new-object-modal").click()
    new_modal = page.locator("#workspace-new-object-modal")
    new_modal.wait_for(state="visible")

    page.locator("#new-tf-id").fill("tf-ux-e2e")
    page.locator("#new-tf-num").fill("2")
    page.locator("#new-tf-den").fill("1, 3, 2")
    page.locator("#new-tf-dt").fill("")
    page.locator("#btn-new-tf-submit").click()
    new_modal.wait_for(state="hidden")

    # Confirm rendered in #workspace-dock-aside with human-readable summary
    dock_text = dock_aside.inner_text()
    assert "tf-ux-e2e" in dock_text
    assert "G(s) = 2 / (s^2 + 3·s + 2)" in dock_text

    # Route to SISO via 1-click dock button
    dock_item = page.locator('[data-dock-item-key="tf-ux-e2e#1"]')
    dock_item.wait_for(state="visible")
    dock_item.locator('[data-dock-action="route-siso"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")
    page.locator("#siso-workspace-panel").wait_for(state="visible")

    selected_id = page.evaluate(
        "() => app.shell.getTypedWorkspace().getEffectiveSelection('frequencyPlant')?.ref.id"
    )
    assert selected_id == "tf-ux-e2e"
    assert "tf-ux-e2e" in page.locator("#siso-loop-diagram-bar").inner_text()

    browser_harness.record(
        "e2e-ux-3zone-dock",
        {
            "dock_visible": True,
            "inspector_default_hidden": True,
            "inspector_r27_telemetry_verified": True,
            "semantic_dictionary_verified": True,
            "guided_tf_created_and_routed": selected_id,
        },
    )


def test_ux_siso_click_datatips_and_r23_chart_export(browser_harness):
    """Test 2: SISO click datatips (Bode, Nyquist, Root Locus frozen poles) and R-23 chart export."""
    page = mount_ui(browser_harness, "e2e-ux-siso-datatips", {"width": 1280, "height": 800})

    page.locator('button[data-tab-id="siso_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")
    page.locator("#siso-workspace-panel").wait_for(state="visible")

    # Register a 2nd-order SISO plant G(s) = 1 / (s^2 + 2s + 2)
    tf_2nd_order = {
        "schema_version": "1.0.0",
        "id": "tf-siso-datatip-2nd",
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
        "provenance": {"algorithm": "test", "library": "control_lab", "seed": None},
    }
    page.evaluate(
        """async (dto) => {
            await app.shell.getTypedWorkspace().registerTypedObject(dto, {
                selectRole: "frequencyPlant",
                persistToIndexedDB: true,
            });
        }""",
        tf_2nd_order,
    )

    page.locator("#siso-w-min").fill("0.05")
    page.locator("#siso-w-max").fill("50")
    page.locator("#siso-n-points").fill("60")
    page.locator('[data-action="siso-eval-bode"]').click()

    bode_svg = page.locator("#siso-bode-chart-slot svg.bode-chart")
    bode_svg.wait_for(state="visible", timeout=30000)
    nyquist_svg = page.locator("#siso-nyquist-chart-slot svg.nyquist-chart")
    nyquist_svg.wait_for(state="visible")

    page.locator("#siso-rl-kmax").fill("50")
    page.locator('[data-action="siso-eval-rl"]').click()
    rl_svg = page.locator("#siso-rl-chart-slot svg.root-locus-chart")
    rl_svg.wait_for(state="visible", timeout=30000)

    # 1. Click on Bode SVG -> datatip shows ω, Mag (dB), Fase (°)
    bode_svg.scroll_into_view_if_needed()
    bode_box = bode_svg.bounding_box()
    assert bode_box is not None and bode_box["width"] > 100
    page.mouse.click(
        bode_box["x"] + bode_box["width"] * 0.45,
        bode_box["y"] + bode_box["height"] * 0.4,
    )
    bode_tip = page.locator("#siso-bode-datatip")
    bode_tip.wait_for(state="visible")
    bode_tip_text = bode_tip.inner_text()
    assert "ω" in bode_tip_text
    assert "Mag" in bode_tip_text and "dB" in bode_tip_text
    assert "Fase" in bode_tip_text and "°" in bode_tip_text
    assert bode_svg.locator('g[data-layer="datatip"]').count() == 1

    # 2. Click on Nyquist SVG -> datatip shows ω and L(jω)
    nyquist_svg.scroll_into_view_if_needed()
    nyq_box = nyquist_svg.bounding_box()
    assert nyq_box is not None and nyq_box["width"] > 100
    page.mouse.click(
        nyq_box["x"] + nyq_box["width"] * 0.55,
        nyq_box["y"] + nyq_box["height"] * 0.55,
    )
    nyq_tip = page.locator("#siso-nyquist-datatip")
    nyq_tip.wait_for(state="visible")
    nyq_tip_text = nyq_tip.inner_text()
    assert "ω" in nyq_tip_text
    assert "L(jω)" in nyq_tip_text
    assert nyquist_svg.locator('g[data-layer="datatip"]').count() == 1

    # 3. Click on Root Locus SVG -> datatip shows K & freezes all closed-loop poles; clear button clears it
    rl_svg.scroll_into_view_if_needed()
    rl_box = rl_svg.bounding_box()
    assert rl_box is not None and rl_box["width"] > 100
    page.mouse.click(
        rl_box["x"] + rl_box["width"] * 0.45,
        rl_box["y"] + rl_box["height"] * 0.35,
    )
    rl_tip = page.locator("#siso-rl-datatip")
    rl_tip.wait_for(state="visible")
    rl_tip_text = rl_tip.inner_text()
    assert "K =" in rl_tip_text
    assert "Ramo 1" in rl_tip_text and "Ramo 2" in rl_tip_text
    assert rl_svg.locator('g[data-layer="frozen-poles-datatip"]').count() == 1
    assert rl_svg.locator("g[data-frozen-pole-branch]").count() == 2

    page.locator("#btn-siso-rl-clear-tip").click()
    rl_tip.wait_for(state="hidden")
    assert rl_svg.locator('g[data-layer="frozen-poles-datatip"]').count() == 0

    # 4. R-23 Chart Export (allowed when committed, blocked during slider drag Fast-Preview)
    bode_export_bar = page.locator('[data-export-bar-for="siso-bode-chart-slot"]')
    bode_export_bar.wait_for(state="visible")
    svg_export_btn = bode_export_bar.locator('[data-action="export-chart-svg"]')
    assert svg_export_btn.is_enabled()

    with page.expect_download() as dl_info:
        svg_export_btn.click()
    download = dl_info.value
    assert download.suggested_filename.endswith(".svg")
    svg_path = download.path()
    assert svg_path is not None and "<svg" in svg_path.read_text(encoding="utf-8")

    # Drag #siso-gain-slider -> Fast-Preview disables SISO export bar buttons (R-23)
    slider = page.locator("#siso-gain-slider")
    slider.scroll_into_view_if_needed()
    s_box = slider.bounding_box()
    assert s_box is not None and s_box["width"] >= 44 and s_box["height"] >= 44
    page.mouse.move(s_box["x"] + s_box["width"] * 0.2, s_box["y"] + s_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(s_box["x"] + s_box["width"] * 0.55, s_box["y"] + s_box["height"] / 2, steps=10)
    page.wait_for_function(
        "() => document.querySelector('#siso-tuner-status')?.textContent?.includes('Pré-visualizando')",
        timeout=10000,
    )
    assert svg_export_btn.is_disabled()

    page.mouse.up()
    page.wait_for_function(
        """() => {
            const btn = document.querySelector('[data-export-bar-for="siso-bode-chart-slot"] [data-action="export-chart-svg"]');
            const model = app.shell.getSisoWorkspace().getBodeChartModel();
            return Boolean(btn && !btn.disabled && model?.series_semantics === 'numeric_verified');
        }""",
        timeout=20000,
    )

    browser_harness.record(
        "e2e-ux-siso-datatips-r23",
        {
            "bode_tip": bode_tip_text,
            "nyquist_tip": nyq_tip_text,
            "rl_tip": rl_tip_text,
            "r23_svg_download_filename": download.suggested_filename,
            "r23_preview_export_blocked": True,
        },
    )


def test_ux_mimo_fuzzy_lmi_monaco_and_viewport_responsiveness(browser_harness):
    """Test 3: Tabs 4 (MIMO), 5 (Fuzzy), 6 (LMI Monaco DSL + 5D cert + CVXPY) and 6-tab viewport responsiveness."""
    page = mount_ui(browser_harness, "e2e-ux-mimo-fuzzy-lmi", {"width": 1280, "height": 800})

    # 1. Tab 4 (mimo_frequency)
    page.locator('button[data-tab-id="mimo_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'mimo_frequency'")
    page.locator("#mimo-workspace-panel").wait_for(state="visible")

    page.locator('[data-action="mimo-load-example"]').click()
    page.wait_for_function(
        "() => document.querySelector('#mimo-active-plant-info')?.textContent?.includes('ss-mimo-distillation-2x2')"
    )
    page.locator("#mimo-n-points").fill("16")
    page.locator('[data-action="mimo-analyze"]').click()

    mimo_svg = page.locator("#mimo-sigma-chart-slot svg")
    mimo_svg.wait_for(state="visible", timeout=30000)

    rga_slider = page.locator("#mimo-rga-omega-slider")
    assert rga_slider.is_enabled()
    rga_slider.fill("0")
    rga_slider.dispatch_event("input")
    omega_label_0 = page.locator("#mimo-rga-omega-label").inner_text()
    rga_html_0 = page.locator("#mimo-rga-heatmap-slot").inner_html()
    assert "mimo-rga-table" in rga_html_0

    max_idx = rga_slider.get_attribute("max") or "15"
    rga_slider.fill(max_idx)
    rga_slider.dispatch_event("input")
    omega_label_max = page.locator("#mimo-rga-omega-label").inner_text()
    rga_html_max = page.locator("#mimo-rga-heatmap-slot").inner_html()
    assert omega_label_max != omega_label_0
    assert rga_html_max != rga_html_0

    # 2. Tab 5 (fuzzy_ts)
    page.locator('button[data-tab-id="fuzzy_ts"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'fuzzy_ts'")
    page.locator("#fuzzy-workspace-panel").wait_for(state="visible")

    page.locator("#fuzzy-surface-n-points").fill("9")
    page.locator('[data-action="fuzzy-eval-surface"]').click()
    page.locator("#fuzzy-surface-chart-slot svg").wait_for(state="visible", timeout=30000)

    page.locator('[data-action="fuzzy-export-fml"]').click()
    export_modal = page.locator("#controllab-export-modal")
    export_modal.wait_for(state="visible", timeout=20000)
    assert "<fuzzySystem" in page.locator("#export-modal-content").inner_text()
    page.locator("#export-modal-close").click()
    export_modal.wait_for(state="hidden")

    # 3. Tab 6 (optimization_lmi)
    page.locator('button[data-tab-id="optimization_lmi"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'optimization_lmi'")
    page.locator("#lmi-workspace-panel").wait_for(state="visible")

    editor = page.locator("#lmi-code-editor")
    starter_dsl = editor.input_value()
    assert "param alpha = 0.5" in starter_dsl

    # Enter bilinear expression A*Q + B*K*Q < 0 -> bilinear warning
    editor.fill("var Q sym(n)\nQ > 0\nA*Q + B*K*Q < 0")
    alert_text = page.locator("#lmi-parsed-alert").inner_text()
    assert "K*Q" in alert_text or "BMI" in alert_text or "bilinear" in alert_text.lower()
    assert page.locator("#lmi-syntax-badge").inner_text() == "Aviso Bilinear (BMI)"

    # Select regional_pole_placement and hinf_brl -> bmat block matrix formatted
    page.select_option("#lmi-template-select", "regional_pole_placement")
    assert page.locator("#lmi-parsed-math table.lmi-bmat-grid").count() >= 1

    page.select_option("#lmi-template-select", "hinf_brl")
    assert page.locator("#lmi-parsed-math table.lmi-bmat-grid").count() >= 1

    # Save/load condition
    page.select_option("#lmi-template-select", "decay_rate")
    assert "param alpha = 0.5" in editor.input_value()
    page.locator("#lmi-preset-name").fill("Condicao Decay E2E")
    page.locator("#btn-lmi-save-dsl").click()

    page.select_option("#lmi-template-select", "quadratic_stabilization")
    assert "param alpha = 0.5" not in editor.input_value()

    page.select_option("#lmi-saved-select", "lmi-preset-1")
    assert "param alpha = 0.5" in editor.input_value()

    # Run Resolver LMI -> 5-dimension certificate + spectrum SVG
    page.locator('[data-action="lmi-solve"]').click()
    page.locator("#lmi-spectrum-chart-slot svg").wait_for(state="visible", timeout=45000)

    cert_text = page.locator("#lmi-certificate-panel").inner_text()
    cert_text_cf = cert_text.casefold()
    for dim_label in (
        "1. Solver Status",
        "2. Auditoria Factibilidade",
        "3. Certificado Dual",
        "4. Condicionamento κ",
        "5. Validade Controlador",
    ):
        assert dim_label.casefold() in cert_text_cf, f"Missing 5D cert dimension: {dim_label} in {cert_text!r}"

    # CVXPY export modal
    page.locator('[data-action="lmi-export-cvxpy"]').click()
    export_modal.wait_for(state="visible", timeout=20000)
    assert "import cvxpy" in page.locator("#export-modal-content").inner_text()
    page.locator("#export-modal-close").click()
    export_modal.wait_for(state="hidden")

    # 4. Zero horizontal overflow across ALL 6 tabs in 1280x800 desktop and 390x844 mobile
    overflow_report = {}
    for width, height in ((1280, 800), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        vp_key = f"{width}x{height}"
        overflow_report[vp_key] = {}
        for tab_id in ALL_TAB_IDS:
            page.locator(f'button[data-tab-id="{tab_id}"]').click()
            page.wait_for_function(f"() => app.shell.getActiveTab() === '{tab_id}'")
            metrics = page.evaluate(
                "() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })"
            )
            overflow_report[vp_key][tab_id] = metrics
            assert metrics["scrollWidth"] <= metrics["innerWidth"] + 1, (
                f"Horizontal overflow at {vp_key} on tab '{tab_id}': "
                f"scrollWidth={metrics['scrollWidth']} > innerWidth={metrics['innerWidth']}"
            )

    browser_harness.record(
        "e2e-ux-mimo-fuzzy-lmi-responsive",
        {
            "mimo_rga_omega_0": omega_label_0,
            "mimo_rga_omega_max": omega_label_max,
            "fuzzy_surface_rendered": True,
            "lmi_5d_certificate_verified": True,
            "overflow_report": overflow_report,
        },
    )


def test_ux_high_contrast_aaa_and_compact_legacy_drawer(browser_harness):
    """Test 4: High-Contrast AAA theme propagation (DOM + scientific SVG charts), 1-click 4-chart SISO, and compact legacy RPC drawer."""
    page = mount_ui(browser_harness, "e2e-ux-high-contrast-aaa", {"width": 1280, "height": 800})

    # Ensure we are on Tab 3 (statespace) even if a previous test left a location.hash
    page.locator('button[data-tab-id="statespace"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'statespace'")

    # Commit LQR first so StateSpace pole-zero SVG and KPI values are rendered
    page.locator('[data-action="commit-lqr"]').click()
    wait_committed(page)

    # 1. Switch to High-Contrast theme via #theme-toggle-btn
    page.locator("#theme-toggle-btn").click()
    theme_attrs = page.evaluate(
        """() => {
            const appEl = document.querySelector('#controllab-app') || document.body.firstElementChild;
            return {
                app: appEl?.getAttribute('data-theme'),
                html: document.documentElement.getAttribute('data-theme'),
                body: document.body.getAttribute('data-theme'),
            };
        }"""
    )
    assert theme_attrs["app"] == "high_contrast"
    assert theme_attrs["html"] == "high_contrast"
    assert theme_attrs["body"] == "high_contrast"

    # 2. Verify high-contrast dark background and light text on h1, h2, .kpi-value, and .lmi-math-expr
    styles_ss = page.evaluate(
        """() => {
            const h1 = document.querySelector('h1');
            const h2 = document.querySelector('#controllab-tab-heading');
            const kpi = document.querySelector('.kpi-value');
            const appEl = document.querySelector('#controllab-app') || document.body.firstElementChild;
            const cardEl = document.querySelector('.panel-card');
            return {
                h1Color: h1 ? getComputedStyle(h1).color : null,
                h2Color: h2 ? getComputedStyle(h2).color : null,
                kpiColor: kpi ? getComputedStyle(kpi).color : null,
                appBg: appEl ? getComputedStyle(appEl).backgroundColor : null,
                cardBg: cardEl ? getComputedStyle(cardEl).backgroundColor : null,
            };
        }"""
    )
    assert styles_ss["h1Color"] == "rgb(248, 250, 252)"
    assert styles_ss["h2Color"] == "rgb(248, 250, 252)"
    assert styles_ss["kpiColor"] == "rgb(248, 250, 252)"
    assert styles_ss["h1Color"] != "rgb(15, 23, 42)"
    assert styles_ss["appBg"] in ("rgb(5, 8, 15)", "rgb(13, 19, 34)")
    assert styles_ss["cardBg"] in ("rgb(5, 8, 15)", "rgb(13, 19, 34)")

    # 3. Verify rendered SVG chart (#pz-chart-slot svg rect) uses high-contrast dark surface (#0B0F17 or #141B29)
    pz_rect_fills = page.evaluate(
        """() => Array.from(document.querySelectorAll('#pz-chart-slot svg rect')).map(
            (r) => (r.getAttribute('fill') || '').toUpperCase()
        )"""
    )
    assert any(f in ("#0B0F17", "#141B29") for f in pz_rect_fills), (
        f"Expected dark high-contrast SVG surface in #pz-chart-slot, got {pz_rect_fills}"
    )

    # Check .lmi-math-expr computed color on Tab 6 (optimization_lmi)
    page.locator('button[data-tab-id="optimization_lmi"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'optimization_lmi'")
    lmi_expr_color = page.evaluate(
        """() => {
            const el = document.querySelector('.lmi-math-expr');
            return el ? getComputedStyle(el).color : null;
        }"""
    )
    assert lmi_expr_color == "rgb(248, 250, 252)"
    assert lmi_expr_color != "rgb(15, 23, 42)"

    # 4. In Tab 2 (siso_frequency), clicking #btn-siso-eval-all renders all 4 SISO charts in a single click
    page.locator('button[data-tab-id="siso_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")
    page.locator("#siso-workspace-panel").wait_for(state="visible")

    tf_siso_hc = {
        "schema_version": "1.0.0",
        "id": "tf-siso-hc-e2e",
        "revision": 1,
        "kind": "TransferFunction",
        "dt": None,
        "variable": "s",
        "poly_order": "descending",
        "input_names": ["u1"],
        "output_names": ["y1"],
        "num": [[{"shape": [1], "dtype": "float64", "order": "C", "data": [2.0]}]],
        "den": [[{"shape": [3], "dtype": "float64", "order": "C", "data": [1.0, 2.0, 2.0]}]],
        "units": {"time": "s", "inputs": ["V"], "outputs": ["V"]},
        "provenance": {"algorithm": "test", "library": "control_lab", "seed": None},
    }
    page.evaluate(
        """async (dto) => {
            await app.shell.getTypedWorkspace().registerTypedObject(dto, {
                selectRole: "frequencyPlant",
                persistToIndexedDB: true,
            });
        }""",
        tf_siso_hc,
    )

    page.locator("#siso-n-points").fill("40")
    page.locator('#btn-siso-eval-all[data-action="siso-eval-all"]').click()

    page.locator("#siso-bode-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-nyquist-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-rl-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-time-chart-slot svg").wait_for(state="visible", timeout=30000)

    siso_bode_fills = page.evaluate(
        """() => Array.from(document.querySelectorAll('#siso-bode-chart-slot svg rect')).map(
            (r) => (r.getAttribute('fill') || '').toUpperCase()
        )"""
    )
    assert any(f in ("#0B0F17", "#141B29") for f in siso_bode_fills)

    # 5. Legacy RPC drawer (#legacy-rpc-inspector-details) is compact by default (max-height <= 220px) and #btn-toggle-advanced-rpc toggles .expanded
    drawer_initial = page.evaluate(
        """() => {
            const el = document.querySelector('#legacy-rpc-inspector-details');
            const cs = el ? getComputedStyle(el) : null;
            return {
                hasExpanded: el ? el.classList.contains('expanded') : null,
                maxHeightPx: cs ? parseFloat(cs.maxHeight) : null,
                ariaExpanded: document.querySelector('#btn-toggle-advanced-rpc')?.getAttribute('aria-expanded'),
            };
        }"""
    )
    assert drawer_initial["hasExpanded"] is False
    assert drawer_initial["maxHeightPx"] is not None and drawer_initial["maxHeightPx"] <= 220
    assert drawer_initial["ariaExpanded"] == "false"

    page.locator("#btn-toggle-advanced-rpc").click()
    drawer_expanded = page.evaluate(
        """() => {
            const el = document.querySelector('#legacy-rpc-inspector-details');
            const cs = el ? getComputedStyle(el) : null;
            return {
                hasExpanded: el ? el.classList.contains('expanded') : null,
                maxHeight: cs ? cs.maxHeight : null,
                ariaExpanded: document.querySelector('#btn-toggle-advanced-rpc')?.getAttribute('aria-expanded'),
            };
        }"""
    )
    assert drawer_expanded["hasExpanded"] is True
    assert drawer_expanded["maxHeight"] == "none"
    assert drawer_expanded["ariaExpanded"] == "true"

    page.locator("#btn-toggle-advanced-rpc").click()
    assert page.evaluate(
        "() => document.querySelector('#legacy-rpc-inspector-details')?.classList.contains('expanded')"
    ) is False

    browser_harness.record(
        "e2e-ux-high-contrast-aaa",
        {
            "theme_attrs": theme_attrs,
            "styles_ss": styles_ss,
            "lmi_expr_color": lmi_expr_color,
            "pz_rect_fills": pz_rect_fills[:4],
            "siso_4_charts_single_click": True,
            "drawer_initial": drawer_initial,
            "drawer_expanded": drawer_expanded,
        },
    )


def test_ux_workbench_mockup_fidelity_topbar_and_2col_grids(browser_harness):
    """Test 5: Topbar global buttons (.ctrlab/.pvm with R-23 lock), SISO 2x2 grid + advanced details, MIMO/Fuzzy/LMI 2-column desktop layouts, and zero horizontal overflow."""
    page = mount_ui(browser_harness, "e2e-ux-workbench-mockup-fidelity", {"width": 1280, "height": 800})

    # Ensure we start on Tab 3 (statespace) before any LQR commit
    page.locator('button[data-tab-id="statespace"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'statespace'")

    btn_open_ctrlab = page.locator("#btn-header-open-ctrlab")
    btn_export_ctrlab = page.locator("#btn-header-export-ctrlab")
    btn_export_pvm = page.locator("#btn-header-export-pvm")

    # 1. Global Topbar buttons visible across tabs; #btn-header-export-pvm disabled before LQR commit (R-23) and enabled after LQR commit
    assert btn_open_ctrlab.is_visible()
    assert btn_export_ctrlab.is_visible()
    assert btn_export_pvm.is_visible()
    assert btn_export_pvm.is_disabled()
    assert btn_export_ctrlab.is_disabled()

    for tab_id in ALL_TAB_IDS:
        page.locator(f'button[data-tab-id="{tab_id}"]').click()
        page.wait_for_function(f"() => app.shell.getActiveTab() === '{tab_id}'")
        assert btn_open_ctrlab.is_visible(), f"#btn-header-open-ctrlab not visible on {tab_id}"
        assert btn_export_ctrlab.is_visible(), f"#btn-header-export-ctrlab not visible on {tab_id}"
        assert btn_export_pvm.is_visible(), f"#btn-header-export-pvm not visible on {tab_id}"

    page.locator('button[data-tab-id="statespace"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'statespace'")
    page.locator('[data-action="commit-lqr"]').click()
    wait_committed(page)

    assert btn_export_pvm.is_enabled()
    assert btn_export_ctrlab.is_enabled()

    # 2. Tab 2 (siso_frequency): #siso-advanced-params-details is present and .siso-charts-grid renders a 2-column grid at 1280x800 after clicking #btn-siso-eval-all
    page.locator('button[data-tab-id="siso_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")
    page.locator("#siso-workspace-panel").wait_for(state="visible")

    siso_details = page.locator("#siso-advanced-params-details")
    assert siso_details.is_visible()
    assert siso_details.get_attribute("open") is not None

    tf_siso_fidelity = {
        "schema_version": "1.0.0",
        "id": "tf-siso-fidelity-e2e",
        "revision": 1,
        "kind": "TransferFunction",
        "dt": None,
        "variable": "s",
        "poly_order": "descending",
        "input_names": ["u1"],
        "output_names": ["y1"],
        "num": [[{"shape": [1], "dtype": "float64", "order": "C", "data": [2.0]}]],
        "den": [[{"shape": [3], "dtype": "float64", "order": "C", "data": [1.0, 2.0, 2.0]}]],
        "units": {"time": "s", "inputs": ["V"], "outputs": ["V"]},
        "provenance": {"algorithm": "test", "library": "control_lab", "seed": None},
    }
    page.evaluate(
        """async (dto) => {
            await app.shell.getTypedWorkspace().registerTypedObject(dto, {
                selectRole: "frequencyPlant",
                persistToIndexedDB: true,
            });
        }""",
        tf_siso_fidelity,
    )

    page.locator("#siso-n-points").fill("40")
    page.locator("#btn-siso-eval-all").click()
    page.locator("#siso-bode-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-nyquist-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-rl-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-time-chart-slot svg").wait_for(state="visible", timeout=30000)

    siso_grid_metrics = page.evaluate(
        """() => {
            const grid = document.querySelector('.siso-charts-grid');
            const bode = document.querySelector('#siso-bode-chart-slot');
            const nyquist = document.querySelector('#siso-nyquist-chart-slot');
            const rl = document.querySelector('#siso-rl-chart-slot');
            const step = document.querySelector('#siso-time-chart-slot');
            const cs = grid ? getComputedStyle(grid) : null;
            return {
                display: cs?.display,
                gridTemplateColumns: cs?.gridTemplateColumns,
                bodeLeft: bode?.getBoundingClientRect().left ?? 0,
                nyquistLeft: nyquist?.getBoundingClientRect().left ?? 0,
                rlLeft: rl?.getBoundingClientRect().left ?? 0,
                stepLeft: step?.getBoundingClientRect().left ?? 0,
            };
        }"""
    )
    assert siso_grid_metrics["display"] == "grid"
    assert siso_grid_metrics["nyquistLeft"] > siso_grid_metrics["bodeLeft"]
    assert siso_grid_metrics["stepLeft"] > siso_grid_metrics["rlLeft"]

    # 3. Tab 4 (mimo_frequency): .mimo-workbench-grid renders Singular Values card and RGA heatmap card side-by-side at 1280x800
    page.locator('button[data-tab-id="mimo_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'mimo_frequency'")
    page.locator("#mimo-workspace-panel").wait_for(state="visible")

    mimo_grid_metrics = page.evaluate(
        """() => {
            const grid = document.querySelector('.mimo-workbench-grid');
            const sigmaSlot = document.querySelector('#mimo-sigma-chart-slot');
            const rgaCard = document.querySelector('.mimo-rga-card');
            return {
                display: grid ? getComputedStyle(grid).display : null,
                sigmaLeft: sigmaSlot?.getBoundingClientRect().left ?? 0,
                rgaLeft: rgaCard?.getBoundingClientRect().left ?? 0,
            };
        }"""
    )
    assert mimo_grid_metrics["display"] == "grid"
    assert mimo_grid_metrics["rgaLeft"] > mimo_grid_metrics["sigmaLeft"]

    # 4. Tab 5 (fuzzy_ts): .fuzzy-workbench-grid renders Membership Function card and Surface card side-by-side at 1280x800
    page.locator('button[data-tab-id="fuzzy_ts"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'fuzzy_ts'")
    page.locator("#fuzzy-workspace-panel").wait_for(state="visible")

    fuzzy_grid_metrics = page.evaluate(
        """() => {
            const grid = document.querySelector('.fuzzy-workbench-grid');
            const mfCard = document.querySelector('.fuzzy-mf-panel');
            const surfCard = document.querySelector('.fuzzy-surface-panel');
            return {
                display: grid ? getComputedStyle(grid).display : null,
                mfLeft: mfCard?.getBoundingClientRect().left ?? 0,
                surfLeft: surfCard?.getBoundingClientRect().left ?? 0,
            };
        }"""
    )
    assert fuzzy_grid_metrics["display"] == "grid"
    assert fuzzy_grid_metrics["surfLeft"] > fuzzy_grid_metrics["mfLeft"]

    # 5. Tab 6 (optimization_lmi): both .lmi-editor-split and .lmi-results-split render side-by-side in 2 columns at 1280x800
    page.locator('button[data-tab-id="optimization_lmi"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'optimization_lmi'")
    page.locator("#lmi-workspace-panel").wait_for(state="visible")

    lmi_grid_metrics = page.evaluate(
        """() => {
            const editorSplit = document.querySelector('.lmi-editor-split');
            const editorCard = document.querySelector('.lmi-editor-card');
            const mathCard = document.querySelector('.lmi-math-card');
            const resultsSplit = document.querySelector('.lmi-results-split');
            const certPanel = document.querySelector('#lmi-certificate-panel');
            const specSlot = document.querySelector('#lmi-spectrum-chart-slot');
            return {
                editorDisplay: editorSplit ? getComputedStyle(editorSplit).display : null,
                editorLeft: editorCard?.getBoundingClientRect().left ?? 0,
                mathLeft: mathCard?.getBoundingClientRect().left ?? 0,
                resultsDisplay: resultsSplit ? getComputedStyle(resultsSplit).display : null,
                certLeft: certPanel?.getBoundingClientRect().left ?? 0,
                specLeft: specSlot?.getBoundingClientRect().left ?? 0,
            };
        }"""
    )
    assert lmi_grid_metrics["editorDisplay"] == "grid"
    assert lmi_grid_metrics["mathLeft"] > lmi_grid_metrics["editorLeft"]
    assert lmi_grid_metrics["resultsDisplay"] == "grid"
    assert lmi_grid_metrics["specLeft"] > lmi_grid_metrics["certLeft"]

    # 6. Zero horizontal overflow across all 6 tabs at 1280x800 and 390x844
    overflow_metrics = {}
    for width, height in ((1280, 800), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        vp_key = f"{width}x{height}"
        overflow_metrics[vp_key] = {}
        for tab_id in ALL_TAB_IDS:
            page.locator(f'button[data-tab-id="{tab_id}"]').click()
            page.wait_for_function(f"() => app.shell.getActiveTab() === '{tab_id}'")
            m = page.evaluate(
                "() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })"
            )
            overflow_metrics[vp_key][tab_id] = m
            assert m["scrollWidth"] <= m["innerWidth"] + 1, (
                f"Horizontal overflow at {vp_key} on tab '{tab_id}': "
                f"scrollWidth={m['scrollWidth']} > innerWidth={m['innerWidth']}"
            )

    browser_harness.record(
        "e2e-ux-workbench-mockup-fidelity",
        {
            "siso_grid_metrics": siso_grid_metrics,
            "mimo_grid_metrics": mimo_grid_metrics,
            "fuzzy_grid_metrics": fuzzy_grid_metrics,
            "lmi_grid_metrics": lmi_grid_metrics,
            "overflow_metrics": overflow_metrics,
        },
    )


def test_ux_phase1_workspace_csv_legend_siso_comp_and_fuzzy_reset(browser_harness):
    """Test 6: Phase 1 Ergonomics — Workspace Dock examples/clear, CSV upload, Ident legend, SISO C(s) modal, and Fuzzy clear/reset."""
    page = mount_ui(browser_harness, "e2e-ux-phase1", {"width": 1280, "height": 800})

    # 1. Workspace Dock: load mass_spring_damper, clear workspace, and restore double_integrator
    dock_aside = page.locator("#workspace-dock-aside")
    page.select_option("#dock-example-select", "mass_spring_damper")
    page.locator("#btn-dock-load-example").click()
    page.wait_for_function(
        "() => document.querySelector('#workspace-dock-aside')?.textContent?.includes('mass-spring-damper')"
    )
    assert "mass-spring-damper" in dock_aside.inner_text()

    page.locator("#btn-dock-clear-workspace").click()
    page.wait_for_function(
        "() => app.shell.getTypedWorkspace().listRegisteredObjects().length === 0"
    )
    assert "mass-spring-damper" not in dock_aside.inner_text()

    page.select_option("#dock-example-select", "double_integrator")
    page.locator("#btn-dock-load-example").click()
    page.wait_for_function(
        "() => document.querySelector('#workspace-dock-aside')?.textContent?.includes('double-integrator')"
    )
    assert "double-integrator" in dock_aside.inner_text()

    # 2. CSV Upload: #new-obj-csv-file in '+ Novo' modal and #id-csv-file-input in Tab 1
    page.locator("#btn-open-new-object-modal").click()
    new_modal = page.locator("#workspace-new-object-modal")
    new_modal.wait_for(state="visible")
    page.locator("#btn-new-mode-csv").click()
    modal_csv_input = page.locator("#new-obj-csv-file")
    assert modal_csv_input.count() == 1
    assert ".csv" in (modal_csv_input.get_attribute("accept") or "")
    csv_payload = b"t,u,y\n0.0,1.0,0.0\n0.1,1.0,0.22\n0.2,1.0,0.48\n0.3,1.0,0.71\n"
    modal_csv_input.set_input_files(
        [{"name": "modal_ensaio.csv", "mimeType": "text/csv", "buffer": csv_payload}]
    )
    page.wait_for_function(
        "() => document.querySelector('#new-csv-content')?.value?.includes('0.71')"
    )
    page.locator("#new-object-modal-close").click()
    new_modal.wait_for(state="hidden")

    page.locator('button[data-tab-id="identification"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'identification'")
    page.locator("#identification-workspace-panel").wait_for(state="visible")

    id_csv_file = page.locator("#id-csv-file-input")
    assert id_csv_file.count() == 1
    assert ".csv" in (id_csv_file.get_attribute("accept") or "")
    id_csv_file.set_input_files(
        [{"name": "id_bancada.csv", "mimeType": "text/csv", "buffer": csv_payload}]
    )
    page.wait_for_function(
        "() => document.querySelector('#id-csv-input')?.value?.includes('0.71')"
    )
    assert "0.71" in page.locator("#id-csv-input").input_value()

    # 3. Identification Legend: load PRBS benchmark and fit ARX -> distinct legend labels & colors
    page.locator('[data-action="id-load-prbs"]').click()
    page.wait_for_function(
        """() => {
            const tw = app.shell.getTypedWorkspace();
            return tw.getSelectedRef('dataset')?.id === 'ds-b-arx-prbs-train'
                && tw.getSelectedRef('valDataset')?.id === 'ds-b-arx-prbs-val';
        }""",
        timeout=25000,
    )
    page.locator("#btn-id-fit-arx").click()
    id_svg = page.locator("#id-response-chart-slot svg")
    id_svg.wait_for(state="visible", timeout=30000)

    legend_info = page.evaluate(
        """() => {
            const texts = Array.from(document.querySelectorAll('#id-response-chart-slot svg text[data-legend-channel]'));
            return texts.map((el) => ({
                channel: el.getAttribute('data-legend-channel'),
                label: (el.textContent || '').trim(),
                fill: (el.getAttribute('fill') || '').toUpperCase(),
            }));
        }"""
    )
    labels_joined = " | ".join(item["label"] for item in legend_info)
    assert "y Medido" in labels_joined, f"Expected 'y Medido' in legend: {legend_info}"
    assert "ŷ" in labels_joined and (
        "ŷ Simulação Livre" in labels_joined or "ŷ Previsão 1-Passo" in labels_joined
    ), f"Expected ŷ prediction label in legend: {legend_info}"
    distinct_colors = {item["fill"] for item in legend_info if item["fill"]}
    assert len(distinct_colors) >= 2, f"Expected distinct legend colors, got {legend_info}"

    # 4. SISO Dynamic Compensator C(s): load mass_spring_damper, open modal, apply TF (s+2)/(s+10), eval all 4 charts
    page.select_option("#dock-example-select", "mass_spring_damper")
    page.locator("#btn-dock-load-example").click()
    page.wait_for_function(
        "() => document.querySelector('#workspace-dock-aside')?.textContent?.includes('mass-spring-damper')"
    )
    page.locator('button[data-tab-id="siso_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'siso_frequency'")
    page.locator("#siso-workspace-panel").wait_for(state="visible")

    page.locator("#btn-siso-edit-compensator").click()
    comp_modal = page.locator("#siso-compensator-modal")
    comp_modal.wait_for(state="visible")
    page.locator("#siso-comp-num").fill("1, 2")
    page.locator("#siso-comp-den").fill("1, 10")
    page.locator("#btn-siso-apply-comp").click()
    comp_modal.wait_for(state="hidden")

    loop_bar_text = page.locator("#siso-loop-diagram-bar").inner_text()
    assert "s + 2" in loop_bar_text and "s + 10" in loop_bar_text, (
        f"Expected dynamic compensator in #siso-loop-diagram-bar, got: {loop_bar_text}"
    )

    page.locator("#siso-n-points").fill("40")
    page.locator("#btn-siso-eval-all").click()
    page.locator("#siso-bode-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-nyquist-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-rl-chart-slot svg").wait_for(state="visible", timeout=30000)
    page.locator("#siso-time-chart-slot svg").wait_for(state="visible", timeout=30000)

    # 5. Fuzzy Clear & Reset: clear system -> minimal skeleton (1 term, 0 rules), reset -> 9-rule PD starter
    page.locator('button[data-tab-id="fuzzy_ts"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'fuzzy_ts'")
    page.locator("#fuzzy-workspace-panel").wait_for(state="visible")

    page.locator("#btn-fuzzy-clear-system").click()
    assert page.locator('[data-action="fuzzy-remove-term"]').count() == 1
    assert "0 regras" in page.locator("#fuzzy-coverage-status").inner_text()

    page.locator("#btn-fuzzy-reset-starter").click()
    assert page.locator('[data-action="fuzzy-remove-term"]').count() == 3
    assert "9 regras" in page.locator("#fuzzy-coverage-status").inner_text()

    browser_harness.record(
        "e2e-ux-phase1",
        {
            "dock_examples_and_clear": True,
            "csv_upload_verified": True,
            "ident_legend": legend_info,
            "siso_compensator_bar": loop_bar_text,
            "fuzzy_clear_and_reset_verified": True,
        },
    )


def test_ux_phase2_lqg_observer_mimo_decoupler_and_hinf(browser_harness):
    """Test 7: Phase 2 Advanced Synthesis — Tab 3 (Observer/Kalman/LQG) and Tab 4 (MIMO SVD Decoupler, Closed-Loop, H-inf)."""
    page = mount_ui(browser_harness, "e2e-ux-phase2", {"width": 1280, "height": 800})

    # 1. Tab 3 (statespace): Observer / Kalman / LQG
    page.locator('button[data-tab-id="statespace"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'statespace'")
    page.locator("#statespace-workspace-panel").wait_for(state="visible")

    page.locator("#btn-obs-synthesize").click()
    page.wait_for_function(
        """() => {
            const el = document.querySelector('#obs-results-summary');
            const txt = el?.textContent || '';
            return txt.includes('Ganho do Observador L:') && txt.includes('Ganho de Regulação K:');
        }""",
        timeout=30000,
    )
    obs_summary_text = page.locator("#obs-results-summary").inner_text()
    assert "Ganho do Observador L:" in obs_summary_text
    assert "Ganho de Regulação K:" in obs_summary_text

    btn_obs_sim = page.locator("#btn-obs-simulate")
    page.wait_for_function("() => !document.querySelector('#btn-obs-simulate')?.disabled")
    btn_obs_sim.click()
    obs_svg = page.locator("#obs-sim-chart-slot svg")
    obs_svg.wait_for(state="visible", timeout=30000)

    btn_obs_reg = page.locator("#btn-obs-register-ctrl")
    page.wait_for_function("() => !document.querySelector('#btn-obs-register-ctrl')?.disabled")
    dock_before = len(
        page.evaluate("() => app.shell.getTypedWorkspace().listRegisteredObjects().map(o => o.id)")
    )
    btn_obs_reg.click()
    page.wait_for_function(
        f"() => app.shell.getTypedWorkspace().listRegisteredObjects().length > {dock_before}",
        timeout=15000,
    )
    dock_text_after_lqg = page.locator("#workspace-dock-aside").inner_text()
    assert "DynamicController" in dock_text_after_lqg or "lqg" in dock_text_after_lqg.lower()

    # 2. Tab 4 (mimo_frequency): SVD Decoupler, Closed-Loop Step, H-inf Synthesis
    page.locator('button[data-tab-id="mimo_frequency"]').click()
    page.wait_for_function("() => app.shell.getActiveTab() === 'mimo_frequency'")
    page.locator("#mimo-workspace-panel").wait_for(state="visible")

    page.locator('[data-action="mimo-load-example"]').click()
    page.wait_for_function(
        "() => document.querySelector('#mimo-active-plant-info')?.textContent?.includes('ss-mimo-distillation-2x2')"
    )

    page.locator("#mimo-decoupler-omega").fill("0.1, 1.0, 10.0")
    assert page.locator("#mimo-decoupler-mode").input_value() == "auto"
    page.locator("#btn-mimo-design-decoupler").click()
    page.wait_for_function(
        """() => {
            const summary = document.querySelector('#mimo-decoupler-summary');
            if (!summary) return false;
            const txt = summary.textContent || '';
            return (
                txt.includes('Ordem do desacoplador')
                && txt.includes('(automática)')
                && summary.querySelector('table[aria-label="Comparação por frequência do desacoplador"]') !== null
                && summary.querySelector('table[aria-label="RGA pós-desacoplamento"]') !== null
            );
        }""",
        timeout=30000,
    )
    per_freq_table = page.locator('#mimo-decoupler-summary table[aria-label="Comparação por frequência do desacoplador"]')
    rga_post_table = page.locator('#mimo-decoupler-summary table[aria-label="RGA pós-desacoplamento"]')
    assert per_freq_table.is_visible()
    assert per_freq_table.locator("tbody tr").count() == 3
    assert rga_post_table.is_visible()
    assert rga_post_table.locator("tbody tr").count() >= 2
    decoupler_text_auto = page.locator("#mimo-decoupler-summary").inner_text()
    assert "Ordem do desacoplador" in decoupler_text_auto
    assert "(automática)" in decoupler_text_auto
    assert "κ(G)" in decoupler_text_auto

    # Explicit order "2" (Ordem 2) -> verifies "2 (manual)"
    page.select_option("#mimo-decoupler-mode", "2")
    page.locator("#btn-mimo-design-decoupler").click()
    page.wait_for_function(
        """() => {
            const txt = document.querySelector('#mimo-decoupler-summary')?.textContent || '';
            return txt.includes('2 (manual)');
        }""",
        timeout=30000,
    )
    decoupler_text = page.locator("#mimo-decoupler-summary").inner_text()
    assert "2 (manual)" in decoupler_text
    assert per_freq_table.is_visible()
    assert per_freq_table.locator("tbody tr").count() == 3
    assert rga_post_table.is_visible()

    page.locator("#btn-mimo-simulate-cl").click()
    cl_svg = page.locator("#mimo-cl-chart-slot svg")
    cl_svg.wait_for(state="visible", timeout=30000)

    page.locator("#btn-mimo-design-hinf").click()
    page.wait_for_function(
        """() => {
            const txt = document.querySelector('#mimo-hinf-summary')?.textContent || '';
            return txt.includes('γ atingido:') && txt.includes('Planta Generalizada P(s):');
        }""",
        timeout=45000,
    )
    hinf_summary_text = page.locator("#mimo-hinf-summary").inner_text()
    assert "γ atingido:" in hinf_summary_text
    assert "n_states=" in hinf_summary_text
    hinf_svg = page.locator("#mimo-hinf-chart-slot svg")
    hinf_svg.wait_for(state="visible", timeout=30000)

    # 3. Zero horizontal overflow at 1280x800 and 390x844 on Tab 3 and Tab 4
    overflow_phase2 = {}
    for width, height in ((1280, 800), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        vp_key = f"{width}x{height}"
        overflow_phase2[vp_key] = {}
        for tab_id in ("statespace", "mimo_frequency"):
            page.locator(f'button[data-tab-id="{tab_id}"]').click()
            page.wait_for_function(f"() => app.shell.getActiveTab() === '{tab_id}'")
            m = page.evaluate(
                "() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })"
            )
            overflow_phase2[vp_key][tab_id] = m
            assert m["scrollWidth"] <= m["innerWidth"] + 1, (
                f"Horizontal overflow at {vp_key} on tab '{tab_id}': "
                f"scrollWidth={m['scrollWidth']} > innerWidth={m['innerWidth']}"
            )

    browser_harness.record(
        "e2e-ux-phase2",
        {
            "obs_summary": obs_summary_text,
            "decoupler_summary": decoupler_text,
            "hinf_summary": hinf_summary_text,
            "overflow_phase2": overflow_phase2,
        },
    )



