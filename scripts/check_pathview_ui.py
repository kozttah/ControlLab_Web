"""Import F9-generated PVM cases in the unmodified official PathView UI.

Run after audit_pvm_official.py using the pinned audit/browser dependencies.
This checks file import and rendered nodes; independent simulation is performed
by audit_pvm_official.py. No imported Python/codeContext is executed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path
from threading import Thread

from pathview.app import create_app
from playwright.sync_api import sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    "static_negative_ci",
    "static_negative_cneq",
    "saturated_negative",
    "dynamic_nonzero_feedthrough",
)


class Quiet(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, default=ROOT / "docs/audits/pvm-official")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/audits/pvm-official/ui-import.json"
    )
    args = parser.parse_args()
    assert version("pathview") == "0.21.0"
    server = make_server(
        "127.0.0.1", 0, create_app(serve_static=True), threaded=True, request_handler=Quiet
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    reports = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("CONTROLLAB_CHROMIUM")
            )
            try:
                for name in CASES:
                    model = args.models / f"{name}.pvm"
                    graph = json.loads(model.read_text())["graph"]
                    context = browser.new_context(viewport={"width": 1500, "height": 1050})
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    # Exercise the app's existing input-file fallback: native OS
                    # File System Access pickers cannot be driven in headless CI.
                    page.add_init_script(
                        "delete window.showOpenFilePicker;delete window.showSaveFilePicker;"
                    )
                    page.goto(f"http://127.0.0.1:{server.server_port}")
                    page.get_by_text("New", exact=True).click()
                    page.get_by_role("button", name="Open/Import", exact=True).wait_for()
                    page.wait_for_timeout(500)
                    with page.expect_file_chooser() as chooser:
                        page.get_by_role("button", name="Open/Import", exact=True).click()
                    chooser.value.set_files(str(model.resolve()))
                    expected = {node["id"] for node in graph["nodes"]}
                    page.wait_for_function(
                        "ids => ids.every(id => Array.from(document.querySelectorAll('.svelte-flow__node')).some(e => e.getAttribute('data-id') === id))",
                        arg=sorted(expected),
                    )
                    nodes = page.locator(".svelte-flow__node").evaluate_all("""elements => elements.map(element => {
                        const box=element.getBoundingClientRect();
                        return {id:element.getAttribute('data-id'), text:element.innerText,
                            x:box.x,y:box.y,width:box.width,height:box.height};
                    })""")
                    selected = [node for node in nodes if node["id"] in expected]
                    assert len(selected) == len(expected), (name, nodes)
                    assert all(node["width"] > 0 and node["height"] > 0 for node in selected)
                    for node in graph["nodes"]:
                        rendered = next(actual for actual in selected if actual["id"] == node["id"])
                        assert node["name"] in rendered["text"] and node["type"] in rendered["text"]
                    assert not errors, (name, errors)
                    reports.append(
                        {
                            "case": name,
                            "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                            "input_nodes": len(expected),
                            "rendered_nodes": selected,
                            "page_errors": errors,
                            "import_passed": True,
                        }
                    )
                    context.close()
                report = {
                    "pathview": version("pathview"),
                    "chromium": browser.version,
                    "official_ui_modified": False,
                    "file_picker": "native input fallback (File System Access API disabled)",
                    "simulation_executed_in_this_check": False,
                    "cases": reports,
                    "global_g0d_approval": False,
                    "scope": "official UI file import/rendering only; full product gate prerequisites remain pending",
                }
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                print(
                    json.dumps(
                        {"cases": len(reports), "import_passed": True, "chromium": browser.version}
                    )
                )
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
