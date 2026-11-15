"""T-SEC-01 browser regression for the built release.

Run npm --prefix web run build, install Playwright and its chromium-headless-shell,
then run python -m pytest -s tests/security/offline_browser.py. An installed
Chromium can be selected with CONTROLLAB_CHROMIUM. This focused check can run
independently of the full security and Wasm release-gate suites.
"""

import json
import os
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "web" / "dist"


class StaticRelease(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Browser HTTP cache must not substitute for the service worker.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_):
        pass


READINESS = """() => new Promise((resolve, reject) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => reject(Error("service worker readiness timeout")), 30000);
    channel.port1.onmessage = event => {
        clearTimeout(timer);
        channel.port1.close();
        resolve(event.data);
    };
    navigator.serviceWorker.controller.postMessage(
        {type: "controllab.checkOfflineReadiness"}, [channel.port2]
    );
})"""


def test_offline_real_calculation_after_reload():
    manifest = json.loads((DIST / "release-manifest.json").read_bytes())
    paths = {asset["path"] for asset in manifest["assets"]}
    # Serve under a prefix, exactly as a project under GitHub Pages.
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(StaticRelease, directory=DIST.parent)
    )
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("CONTROLLAB_CHROMIUM")
            )
            with browser.new_context() as context:
                external = []
                context.on(
                    "request",
                    lambda request: external.append(request.url)
                    if urlsplit(request.url).scheme in {"http", "https"}
                    and not request.url.startswith(origin + "/")
                    else None,
                )
                page = context.new_page()
                page.goto(f"{origin}/dist/")
                page.evaluate("""() => new Promise((resolve, reject) => {
                    if (navigator.serviceWorker.controller) return resolve(true);
                    const timer = setTimeout(() => reject(Error("SW control timeout")), 90000);
                    navigator.serviceWorker.addEventListener("controllerchange", () => {
                        clearTimeout(timer);
                        resolve(true);
                    }, {once: true});
                })""")
                report = page.evaluate(READINESS)
                assert report["ready"], report
                assert report["totalManifestAssets"] == len(paths)
                cache = report["cacheName"]
                cache_paths = page.evaluate(
                    """async name => (await (await caches.open(name)).keys())
                        .map(key => new URL(key.url).pathname)""",
                    cache,
                )
                assert {"/dist/" + path for path in paths} <= set(cache_paths)

                server.shutdown()
                server.server_close()
                worker.join()
                context.new_cdp_session(page).send("Network.clearBrowserCache")
                context.set_offline(True)
                navigation = page.reload()
                assert navigation and navigation.ok and navigation.from_service_worker
                with pytest.raises(ConnectionRefusedError):
                    socket.create_connection(("127.0.0.1", server.server_port), timeout=1)
                assert page.evaluate(READINESS)["ready"]
                scientific = page.evaluate(
                    """async () => {
                        const {mountControlLabApp} = await import("./app/main.js");
                        const app = mountControlLabApp(document.createElement("div"));
                        try {
                            const caps = await app.client.init();
                            const response = await app.client.execute({
                                api_version: "1.0",
                                request_id: "offline-care-regression",
                                project_id: "offline-probe",
                                project_revision: 0,
                                operation: "statespace.design_lqr",
                                payload: {
                                    A: [[0, 1], [0, 0]], B: [[0], [1]],
                                    Q: [[4, 0], [0, 5]], R: [[1]]
                                },
                                options: {method: "care"},
                                timeout_policy: {hard_timeout_ms: 30000},
                            }, {commitOnSuccess: false});
                            return {caps, response};
                        } finally { app.destroy(); }
                    }"""
                )
                caps = scientific["caps"]
                assert caps["engine_kind"] == "pyodide" and caps["offline_ready"], caps
                assert {"pyodide", "numpy", "scipy"} <= caps["lib_versions"].keys()
                rpc = scientific["response"]
                assert rpc["status"] == "success", rpc
                # Analytic stabilizing CARE solution for the double integrator.
                result = rpc["result"]
                assert result["K"]["data"] == pytest.approx([2.0, 3.0], abs=1e-10, rel=0)
                assert result["P"]["data"] == pytest.approx([6, 2, 2, 3], abs=1e-10, rel=0)
                assert sorted(result["closed_loop_poles"]["real"]) == pytest.approx(
                    [-2, -1], abs=1e-10, rel=0
                )
                assert result["closed_loop_poles"]["imag"] == pytest.approx([0, 0], abs=1e-10)
                assert not external, external

                page.evaluate(
                    """async name => {
                        const cache = await caches.open(name);
                        const key = new URL("app/styles.css", location.href);
                        const original = await cache.match(key);
                        const bytes = new Uint8Array(await original.arrayBuffer());
                        bytes[0] ^= 1;
                        await cache.put(key, new Response(bytes, {headers: original.headers}));
                    }""",
                    cache,
                )
                damaged = page.evaluate(READINESS)
                assert not damaged["ready"] and any(
                    path.endswith("app/styles.css") for path in damaged["corruptUrls"]
                ), damaged
                corrupt_status = page.evaluate(
                    """async () => (await fetch('./app/styles.css')).status"""
                )
                assert corrupt_status == 503
                print(json.dumps({
                    "chromium": browser.version, "cache_assets_verified": len(paths),
                    "offline_navigation_from_service_worker": navigation.from_service_worker,
                    "offline_ready_before_corruption": caps["offline_ready"],
                    "offline_ready_after_corruption": damaged["ready"],
                    "corrupt_asset_http_status": corrupt_status,
                    "lib_versions": caps["lib_versions"], "K": result["K"]["data"],
                    "P": result["P"]["data"], "external_requests": external,
                }, sort_keys=True))
            browser.close()
    finally:
        if worker.is_alive():
            server.shutdown()
            server.server_close()
            worker.join()
