"""G-0C real pointer/keyboard/mobile interactions against the shipped module and CSS."""

import json

import numpy as np

from scripts.browser_harness import browser_harness


from scripts.gatecd_browser import mount_ui, wait_committed, stored_project, without_export_time


def test_real_slider_drag_keeps_preview_transient_then_commits(browser_harness):
    page = mount_ui(browser_harness, "gatecd-pointer")
    page.locator('[data-action="commit-lqr"]').click()
    wait_committed(page)
    before = stored_project(page)
    page.locator("#lqr-q-slider").scroll_into_view_if_needed()
    box = page.locator("#lqr-q-slider").bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44
    page.mouse.move(box["x"] + box["width"] * 0.2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.65, box["y"] + box["height"] / 2, steps=20)
    page.wait_for_function(
        "() => app.shell.getLqrWorkspace().getPreviewState().active", timeout=10000
    )
    during = stored_project(page)
    assert without_export_time(during) == without_export_time(before)
    assert page.locator("#btn-export-pvm").is_disabled()
    assert page.locator("#lqr-status-text").inner_text().startswith("Fast-Preview")
    assert page.locator("#pz-chart-slot svg").get_attribute("data-series-semantics") == "preview"
    page.mouse.up()
    wait_committed(page)
    after = stored_project(page)
    assert after["project_revision"] > before["project_revision"]
    assert after["committed_result"]["result"]["K"] != before["committed_result"]["result"]["K"]
    assert page.locator("#btn-export-pvm").is_enabled()
    assert page.locator("#lqr-status-text").inner_text() == "Confirmado"
    browser_harness.record(
        "gatecd-real-pointer",
        dict(
            before_revision=before["project_revision"],
            after_revision=after["project_revision"],
            preview_persisted=False,
            slider_bounds=box,
            pointer_steps=20,
            driver="Playwright mouse pointer events",
        ),
    )


def test_keyboard_mobile_dimensions_and_temporal_x_u_dom(browser_harness):
    page = mount_ui(browser_harness, "gatecd-keyboard", {"width": 390, "height": 844})
    tabs = page.locator('[role="tab"]')
    tab_ids = tabs.evaluate_all("nodes=>nodes.map(n=>n.dataset.tabId)")
    page.locator('[role="tab"][aria-selected="true"]').focus()
    page.keyboard.press("Home")
    assert (
        page.locator('[role="tab"][aria-selected="true"]').get_attribute("data-tab-id")
        == tab_ids[0]
    )
    visited = [tab_ids[0]]
    for expected in tab_ids[1:]:
        page.keyboard.press("ArrowRight")
        selected = page.locator('[role="tab"][aria-selected="true"]')
        assert selected.get_attribute("data-tab-id") == expected
        assert selected.evaluate("node=>node===document.activeElement")
        visited.append(expected)
    page.keyboard.press("Home")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    assert (
        page.locator('[role="tab"][aria-selected="true"]').get_attribute("data-tab-id")
        == "statespace"
    )
    for _ in range(20):
        page.keyboard.press("Tab")
        if page.locator("#lqr-q-slider").evaluate("node=>node===document.activeElement"):
            break
    else:
        raise AssertionError("Slider was unreachable by keyboard from the active tab")
    page.keyboard.press("ArrowRight")
    wait_committed(page)
    before = stored_project(page)
    assert before["committed_result"]
    chart = page.locator('#time-chart-slot svg[data-chart-kind="time_response"]')
    assert chart.count() == 1
    for prefix in ("x-", "u-"):
        channels = chart.locator(f'polyline[data-channel-id^="{prefix}"]')
        assert channels.count() > 0
        assert all(
            len(p.split()) > 1
            for p in channels.evaluate_all("nodes=>nodes.map(n=>n.getAttribute('points'))")
        )
    page.locator("#time-table-slot").locator("xpath=..").locator("summary").click()
    headers = page.locator("#time-table-slot th").all_text_contents()
    assert any("Estado" in h for h in headers) and any("Entrada" in h for h in headers)
    layout = page.evaluate("""() => {
        const main=document.querySelector('#controllab-main');
        return {columns:getComputedStyle(main).gridTemplateColumns,
                viewport:innerWidth,scroll:document.documentElement.scrollWidth,
                main:main.getBoundingClientRect().toJSON()};
    }""")
    assert len(layout["columns"].split()) == 1, layout
    assert layout["scroll"] <= layout["viewport"] + 1, layout
    # Enter activates the button after normal Tab navigation, with a dimension-invalid Q.
    invalid = {
        "Q": {
            "dtype": "float64",
            "shape": [3, 3],
            "order": "C",
            "data": np.eye(3).reshape(-1).tolist(),
        }
    }
    page.locator("#lqr-weights-json").fill(json.dumps(invalid))
    page.locator("#lqr-weights-json").focus()
    page.keyboard.press("Tab")
    assert page.locator("#btn-apply-weights").evaluate("node=>node===document.activeElement")
    page.keyboard.press("Enter")
    alert = page.locator('#controllab-error-slot [role="alert"]')
    alert.wait_for(state="visible")
    error_text = alert.inner_text()
    assert "DIMENSION_MISMATCH" in error_text, error_text
    assert without_export_time(stored_project(page)) == without_export_time(before)
    # Keyboard-triggered modal close returns focus to its trigger.
    page.locator("#btn-export-gains").focus()
    page.keyboard.press("Enter")
    page.locator("#controllab-export-modal").wait_for(state="visible")
    page.keyboard.press("Escape")
    assert page.locator("#btn-export-gains").evaluate("node=>node===document.activeElement")
    browser_harness.record(
        "gatecd-keyboard-mobile",
        dict(
            tabs_visited=visited,
            viewport=layout,
            keyboard_commit_revision=before["project_revision"],
            curves=["x", "u"],
            dimension_error=error_text,
            modal_focus_restored=True,
        ),
    )
