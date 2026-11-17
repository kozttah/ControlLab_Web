"""Real project-site entry, worker and offline calculation under a Pages prefix."""

import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "web/dist"
PREFIX = "/ControlLab_Web/"


class ProjectSite(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_):
        pass


def test_pages_entry_lqr_and_service_worker_stay_under_repository_prefix(tmp_path):
    """Root-relative regressions fail because only /ControlLab_Web/ is served."""
    assert (DIST / "release-manifest.json").is_file(), "Build the static release first"
    (tmp_path / "ControlLab_Web").symlink_to(DIST, target_is_directory=True)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(ProjectSite, directory=tmp_path)
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            kind = os.getenv("CONTROLLAB_BROWSER", "chromium")
            executable = os.getenv(
                "CONTROLLAB_CHROMIUM" if kind == "chromium" else "CONTROLLAB_FIREFOX"
            )
            browser = getattr(playwright, kind).launch(executable_path=executable)
            with browser.new_context() as context:
                requests = []
                failures = []
                context.on("request", lambda request: requests.append(request.url))
                context.on(
                    "response",
                    lambda response: failures.append((response.status, response.url))
                    if response.status >= 400 and urlsplit(response.url).path != "/favicon.ico"
                    else None,
                )
                page = context.new_page()
                page.set_default_timeout(120000)
                navigation = page.goto(origin + PREFIX)
                assert navigation and navigation.ok
                page.wait_for_function(
                    "() => document.querySelector('#engine-status-badge')?.textContent.includes('Motor: ready')"
                )
                page.locator('[data-action="commit-lqr"]').click()
                page.wait_for_function(
                    "() => document.querySelector('#lqr-status-text')?.textContent === 'Confirmado'"
                )
                gain = page.locator('#lqr-k-display pre[aria-label="Matriz de ganho K"]')
                # Analytic double integrator, Q=I, R=1, shown to four decimals.
                assert json.loads(gain.inner_text()) == [["1.0000", "1.7321"]]
                assert page.locator('#time-chart-slot svg[data-chart-kind="time_response"]').count() == 1
                registration = page.evaluate("""async () => {
                    const registration = await navigator.serviceWorker.ready;
                    if (!navigator.serviceWorker.controller) {
                        await new Promise(resolve => navigator.serviceWorker.addEventListener(
                            'controllerchange', resolve, {once:true}));
                    }
                    return {scope:registration.scope, script:registration.active.scriptURL};
                }""")
                assert registration == {
                    "scope": origin + PREFIX,
                    "script": origin + PREFIX + "service_worker.js",
                }
                context.set_offline(True)
                reloaded = page.reload()
                assert reloaded and reloaded.ok and reloaded.from_service_worker
                page.wait_for_function(
                    "() => document.querySelector('#engine-status-badge')?.textContent.includes('Motor: ready')"
                )
                page.locator('[data-action="commit-lqr"]').click()
                page.wait_for_function(
                    "() => document.querySelector('#lqr-status-text')?.textContent === 'Confirmado'"
                )
                assert json.loads(gain.inner_text()) == [["1.0000", "1.7321"]]
                app_requests = [
                    url for url in requests
                    if urlsplit(url).scheme in {"http", "https"}
                    and urlsplit(url).path != "/favicon.ico"
                ]
                assert app_requests and all(url.startswith(origin + PREFIX) for url in app_requests)
                assert not failures, failures
                print(json.dumps({
                    "browser": browser.version, "kind": kind, "prefix": PREFIX,
                    "requests": len(app_requests), "service_worker": registration,
                    "offline_reload": reloaded.from_service_worker,
                    "displayed_K": json.loads(gain.inner_text()),
                }, sort_keys=True))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
