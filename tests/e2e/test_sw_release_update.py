"""Two immutable builds exercise a provisioned product Worker, not a probe worker.

The only source mutation is a provenance marker in an isolated temporary copy.
Both releases execute the real index, application, bridge and Python LQR.
"""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "/ControlLab_Web/"


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    fixture = tmp_path_factory.mktemp("real-sw-releases")
    source = fixture / "source"
    source.mkdir()
    for name in [
        "control_lab",
        "scripts",
        "docs/legal",
        "web/app",
        "web/worker",
        "web/bridge",
        "web/storage",
        "web/features",
        "web/charts",
    ]:
        shutil.copytree(ROOT / name, source / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in [
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "web/package.json",
        "web/package-lock.json",
    ]:
        shutil.copy2(ROOT / name, source / name)
    (source / "web/node_modules").symlink_to(ROOT / "web/node_modules", target_is_directory=True)
    provenance = source / "control_lab/diagnostics/provenance.py"
    original = provenance.read_text()
    env = dict(os.environ, PYTHON=sys.executable)
    built = {}
    for label in ["A", "A-repeat", "B"]:
        marker = "A" if label.startswith("A") else "B"
        provenance.write_text(
            original.replace(
                "    if extra_libs is not None:",
                f'    versions["sw_release_probe"] = "{marker}"\n    if extra_libs is not None:',
                1,
            )
        )
        subprocess.run(
            ["node", str(source / "scripts/build_web.mjs")], cwd=source, env=env, check=True
        )
        destination = fixture / label
        (source / "web/dist").rename(destination)
        built[label] = destination

    def inventory(folder):
        return {
            str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*")
            if p.is_file()
        }

    a, repeat, b = map(inventory, (built["A"], built["A-repeat"], built["B"]))
    assert a == repeat, "Repeated builds of identical inputs must be byte-identical"
    changed = {name for name in a if a[name] != b[name]}
    wheel = next(name for name in a if name.endswith(".whl") and "control_lab" in name)
    assert changed == {wheel, "sbom.json", "release-manifest.json", "service_worker.js"}, changed
    return built, {
        "deterministic_assets": len(a),
        "changed_assets": sorted(changed),
        "wheel": wheel,
        "A": a["release-manifest.json"],
        "B": b["release-manifest.json"],
    }


class SwitchingSite(SimpleHTTPRequestHandler):
    def do_GET(self):
        # Firefox's context offline switch does not cover every SW network fetch.
        # Remove the real HTTP transport too; no request interception or mock SW.
        if self.server.release_state.get("failure") == "offline":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        path = urlsplit(self.path).path
        if path == "/observer":
            body = b"<!doctype html><title>Uncontrolled update observer</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return
        if not path.startswith(PREFIX):
            self.send_error(404)
            return
        if path.endswith(self.server.release_state["wheel"]):
            failure = self.server.release_state.get("failure")
            if failure == "download":
                self.send_error(503, "Intentional candidate wheel download failure")
                return
            if failure == "integrity":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Intentional corrupt candidate wheel")
                return
        super().do_GET()

    def translate_path(self, path):
        relative = urlsplit(path).path.removeprefix(PREFIX)
        return str(self.server.release_state["root"] / relative)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_):
        pass


READINESS = """() => new Promise((resolve, reject) => {
 const channel = new MessageChannel();
 const timeout = setTimeout(() => reject(Error('readiness timeout')), 30000);
 channel.port1.onmessage = event => {clearTimeout(timeout); channel.port1.close(); resolve(event.data);};
 navigator.serviceWorker.controller.postMessage({type:'controllab.checkOfflineReadiness'}, [channel.port2]);
})"""

PROJECTS = """() => new Promise((resolve, reject) => {
 const request = indexedDB.open('controllab_web_projects');
 request.onerror = () => reject(request.error);
 request.onsuccess = () => {
   const db = request.result;
   const tx = db.transaction(['projects', 'objects', 'snapshots'], 'readonly');
   const result = {};
   for (const store of ['projects', 'objects', 'snapshots']) {
     const query = tx.objectStore(store).getAll();
     query.onsuccess = () => { result[store] = query.result; };
   }
   tx.oncomplete = () => { db.close(); resolve(result); };
   tx.onerror = () => reject(tx.error);
 };
})"""


def calculate(page, expected):
    page.wait_for_function(
        "() => document.querySelector('#engine-status-badge')?.textContent.includes('Motor: ready')"
    )
    page.locator('[data-action="commit-lqr"]').click()
    page.wait_for_function(
        "() => document.querySelector('#lqr-status-text')?.textContent === 'Confirmado'"
    )
    assert json.loads(
        page.locator('#lqr-k-display pre[aria-label="Matriz de ganho K"]').inner_text()
    ) == [["1.0000", "1.7321"]]
    page.locator('[data-action="export-gains"]').click()
    gains = json.loads(page.locator("#export-modal-content").inner_text())
    assert gains["provenance"]["lib_versions"]["sw_release_probe"] == expected
    page.locator("#export-modal-close").click()
    return gains


def update(page):
    return page.evaluate("""async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      const settled = new Promise(resolve => {
        registration.addEventListener('updatefound', () => {
          const candidate = registration.installing;
          candidate.addEventListener('statechange', () => {
            if (candidate.state === 'installed' || candidate.state === 'redundant') resolve(candidate.state);
          });
        }, {once: true});
      });
      try { await registration.update(); } catch (error) { return 'network-error'; }
      return Promise.race([settled, new Promise((_, reject) => setTimeout(() => reject(Error('update lifecycle timeout')), 120000))]);
    }""")


def test_provisioned_client_updates_python_atomically_and_preserves_projects(releases):
    built, evidence = releases
    server = ThreadingHTTPServer(("127.0.0.1", 0), SwitchingSite)
    server.release_state = {"root": built["A"], "wheel": evidence["wheel"]}
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
            if kind == "firefox":
                assert int(browser.version.split(".")[0]) >= 147, (
                    "Product uses module Service Workers, supported from Firefox147; "
                    f"installed engine is {browser.version}. Use the pinned official browser runtime."
                )
            with browser.new_context() as context:
                page = context.new_page()
                page.set_default_timeout(120000)
                browser_errors = []
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: browser_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                page.goto(origin + PREFIX)
                calculate(page, "A")
                print("SW lifecycle: product Python A ready", flush=True)
                assert (
                    "falha ao registrar SW" not in page.locator("#engine-status-badge").inner_text()
                ), browser_errors
                page.evaluate("""async () => {
                  const timeout = new Promise((_, reject) => setTimeout(async () => {
                    const registrations = await navigator.serviceWorker.getRegistrations();
                    reject(Error('initial SW readiness timeout: ' + JSON.stringify({
                      userAgent: navigator.userAgent,
                      badge: document.querySelector('#engine-status-badge')?.textContent,
                      registrations: registrations.map(r => ({scope:r.scope,
                        installing:r.installing?.state, waiting:r.waiting?.state, active:r.active?.state}))
                    })));
                  }, 120000));
                  await Promise.race([navigator.serviceWorker.ready, timeout]);
                  if (!navigator.serviceWorker.controller) await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, {once:true}));
                }""")
                print("SW lifecycle: A controlled", flush=True)
                ready_a = page.evaluate(READINESS)
                assert ready_a["ready"] and evidence["A"] in ready_a["cacheName"]
                projects_a = page.evaluate(PROJECTS)
                assert projects_a["projects"] and projects_a["objects"] and projects_a["snapshots"]
                observer = context.new_page()
                observer.goto(origin + "/observer")
                failures = []
                server.release_state["root"] = built["B"]
                for failure in ["download", "integrity", "offline"]:
                    server.release_state["failure"] = failure
                    context.set_offline(failure == "offline")
                    print(f"SW lifecycle: rejecting candidate B ({failure})", flush=True)
                    outcome = update(page)
                    assert outcome in {"redundant", "network-error"}, (failure, outcome)
                    assert page.evaluate(
                        "async () => !(await navigator.serviceWorker.getRegistration()).waiting"
                    )
                    reloaded = page.reload()
                    assert reloaded.ok and reloaded.from_service_worker
                    # Inspect persisted records before any new commit can mask data loss.
                    assert page.evaluate(PROJECTS) == projects_a
                    calculate(page, "A")
                    ready = page.evaluate(READINESS)
                    assert ready["ready"] and ready["cacheName"] == ready_a["cacheName"]
                    projects_a = page.evaluate(PROJECTS)
                    failures.append(
                        {
                            "failure": failure,
                            "candidate": outcome,
                            "active_python": "A",
                            "offline_reload": True,
                        }
                    )
                    context.set_offline(False)
                server.release_state["failure"] = None
                print("SW lifecycle: valid B installation", flush=True)
                assert update(page) == "installed"
                assert page.evaluate(
                    "async () => !!(await navigator.serviceWorker.getRegistration()).waiting"
                )
                calculate(page, "A")
                assert page.evaluate(READINESS)["cacheName"] == ready_a["cacheName"]
                # A second client opened while B waits must still load A's Python.
                old_new = context.new_page()
                old_new.set_default_timeout(120000)
                old_new.goto(origin + PREFIX)
                calculate(old_new, "A")
                projects_before_activation = old_new.evaluate(PROJECTS)
                page.close()
                old_new.close()
                observer.wait_for_function(
                    """async prefix => {
                  const r = await navigator.serviceWorker.getRegistration(prefix);
                  return r && !r.waiting && r.active?.state === 'activated';
                }""",
                    arg=origin + PREFIX,
                    timeout=120000,
                )
                print("SW lifecycle: B activated", flush=True)
                fresh = context.new_page()
                fresh.set_default_timeout(120000)
                fresh.goto(origin + PREFIX)
                assert fresh.evaluate(PROJECTS) == projects_before_activation
                calculate(fresh, "B")
                ready_b = fresh.evaluate(READINESS)
                assert ready_b["ready"] and evidence["B"] in ready_b["cacheName"]
                assert ready_a["cacheName"] != ready_b["cacheName"]
                context.set_offline(True)
                server.release_state["failure"] = "offline"
                reloaded = fresh.reload()
                assert reloaded.ok and reloaded.from_service_worker
                calculate(fresh, "B")
                report = dict(
                    evidence,
                    browser=browser.version,
                    kind=kind,
                    failures=failures,
                    waiting_python="A",
                    activated_python="B",
                    offline_python="B",
                    projects_preserved=True,
                    A_cache=ready_a["cacheName"],
                    B_cache=ready_b["cacheName"],
                )
                print(json.dumps(report, sort_keys=True))
                output = os.getenv("CONTROLLAB_SW_RELEASE_REPORT")
                if output:
                    Path(output).write_text(json.dumps(report, indent=2) + "\n")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
