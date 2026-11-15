"""F9 real-browser harness. No mock engine or downloaded oracle values.

The released app/worker is used for RPC. A separate test-only module Worker
executes Python probes against the exact shipped wheel for APIs without RPC.
Missing runtimes fail setup; they are never skipped or converted into a pass.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"
EVIDENCE = ROOT / "reports" / "browser"


class ReleaseHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/probe.html":
            body = (
                b'<!doctype html><html lang="en"><title>F9 test harness</title><body></body></html>'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_):
        pass


class BrowserHarness:
    def __init__(self, page, origin, version):
        self.page, self.origin, self.version = page, origin, version

    def record(self, name, value):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / (name + ".json")).write_text(
            json.dumps(
                {
                    "browser": self.version,
                    "browser_kind": os.getenv("CONTROLLAB_BROWSER", "chromium"),
                    "release_manifest_sha256": hashlib.sha256(
                        (DIST / "release-manifest.json").read_bytes()
                    ).hexdigest(),
                    "evidence": value,
                },
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )

    def rpc(self, request, commit=False):
        return self.page.evaluate(
            "async ({request, commit}) => app.client.execute(request, {commitOnSuccess: commit})",
            {"request": request, "commit": commit},
        )

    def python(self, source):
        return self.page.evaluate("source => runPythonProbe(source)", source)


@pytest.fixture(scope="module")
def browser_harness():
    assert (DIST / "release-manifest.json").is_file(), "Build required: npm --prefix web run build"
    manifest = json.loads((DIST / "release-manifest.json").read_text())
    for asset in manifest["assets"]:
        contents = (DIST / asset["path"]).read_bytes()
        assert (
            len(contents) == asset["size"]
            and hashlib.sha256(contents).hexdigest() == asset["sha256"]
        )
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(ReleaseHandler, directory=DIST))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as p:
            browser_kind = os.getenv("CONTROLLAB_BROWSER", "chromium")
            executable = (
                os.getenv("CONTROLLAB_CHROMIUM")
                if browser_kind == "chromium"
                else os.getenv("CONTROLLAB_FIREFOX")
            )
            browser = getattr(p, browser_kind).launch(executable_path=executable)
            context = browser.new_context(viewport={"width": 1100, "height": 800})
            page = context.new_page()
            page.set_default_timeout(120000)
            page.goto(origin + "/probe.html")
            external = []
            page.on(
                "request",
                lambda req: external.append(req.url)
                if not req.url.startswith(origin + "/") and req.url.startswith(("http:", "https:"))
                else None,
            )
            page.evaluate("""async () => {
                const {mountControlLabApp} = await import('/app/main.js');
                const node = document.createElement('div'); document.body.append(node);
                globalThis.app = mountControlLabApp(node, {project_id: 'f9-browser-project'});
                globalThis.events = [];
                app.client.subscribe(event => events.push(event));
                const initStart=performance.now(); await app.client.init(); globalThis.f9InitMs=performance.now()-initStart;
                globalThis.request = (revision=0, project='f9-test') => ({
                    api_version:'1.0', request_id:crypto.randomUUID(), project_id:project,
                    project_revision:revision, operation:'statespace.design_lqr',
                    payload:{A:[[0,1],[0,0]],B:[[0],[1]],Q:[[4,0],[0,5]],R:[[1]]},
                    options:{method:'care'}, timeout_policy:{hard_timeout_ms:30000}
                });
                globalThis.runPythonProbe = async source => {
                    if (!globalThis.probeWorker) {
                        const code = `import {loadPyodide} from '${location.origin}/pyodide/pyodide.mjs';
                            let py;
                            self.onmessage=async event=>{try {
                                if(!py){py=await loadPyodide({indexURL:'${location.origin}/pyodide/'});
                                    await py.loadPackage(['numpy','scipy','${location.origin}/wheels/control_lab-1.0.0-py3-none-any.whl']);}
                                const result=await py.runPythonAsync(event.data);
                                self.postMessage({result});
                            } catch(error) {self.postMessage({error:String(error)});}};`;
                        const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));
                        globalThis.probeWorker=new Worker(url,{type:'module'}); URL.revokeObjectURL(url);
                    }
                    return await new Promise((resolve,reject)=>{
                        const timer=setTimeout(()=>reject(Error('Python probe timeout')),120000);
                        probeWorker.onmessage=e=>{clearTimeout(timer); if(e.data.error)reject(Error(e.data.error));else resolve(JSON.parse(e.data.result));};
                        probeWorker.onerror=e=>{clearTimeout(timer);reject(Error(e.message));};
                        probeWorker.postMessage(source);
                    });
                };
            }""")
            harness = BrowserHarness(page, origin, browser.version)
            yield harness
            assert not external, external
            page.evaluate("() => {app.destroy(); globalThis.probeWorker?.terminate();}")
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def care_request(fixture, project="f9-care", revision=0):
    data = fixture["data"]
    return {
        "api_version": "1.0",
        "request_id": f"{project}-{revision}",
        "project_id": project,
        "project_revision": revision,
        "operation": "statespace.design_lqr",
        "payload": {key: data[key] for key in ("A", "B", "Q", "R")},
        "options": {"method": "care"},
        "timeout_policy": {"hard_timeout_ms": 30000},
    }
