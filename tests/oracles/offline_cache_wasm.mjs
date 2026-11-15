// Requires a fresh "npm --prefix web run build". Run with node --test tests/oracles/offline_cache_wasm.mjs.
// Simulates CacheStorage lifecycle in Node, then uses the shipped Pyodide/Wasm and worker dispatcher.
// Browser registration, navigation and ServiceWorker interception need the separate Chromium proof.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { InMemoryCacheStorage, ServiceWorkerController } from "../../web/dist/service_worker.js";

const dist = fileURLToPath(new URL("../../web/dist/", import.meta.url));
const scope = new URL("https://offline.invalid/ControlLab_Web/");
const wheelPath = "wheels/control_lab-1.0.0-py3-none-any.whl";

test("real cached wheel solves a continuous Lyapunov equation after controller restart", async (t) => {
  const storage = new InMemoryCacheStorage();
  const installer = new ServiceWorkerController(scope.href);
  await installer.install(storage, async (request) => {
    const url = new URL(request.url);
    assert.equal(url.origin, scope.origin);
    assert.ok(url.pathname.startsWith(scope.pathname));
    return new Response(await readFile(path.join(dist, url.pathname.slice(scope.pathname.length))));
  });
  await installer.activate(storage);

  const restarted = new ServiceWorkerController(scope.href);
  const report = await restarted.checkOfflineReadiness(storage);
  assert.equal(report.ready, true, JSON.stringify(report));
  const fromCache = (asset) => restarted.handleFetch(new Request(new URL(asset, scope)), storage);
  assert.equal((await fromCache("./")).status, 200);
  assert.equal((await fromCache("missing.js")).status, 503);
  assert.equal((await fromCache("https://external.invalid/wheel.whl")).status, 403);

  const manifest = await (await fromCache("release-manifest.json")).json();
  assert.equal(report.totalManifestAssets, manifest.assets.length);
  const temp = await mkdtemp(path.join(tmpdir(), "controllab-offline-wasm-"));
  t.after(() => rm(temp, { recursive: true, force: true }));
  // Under Node, Pyodide reads its bootstrap and locked packages from a directory.
  // Only bytes from post-restart cache hits enter this isolated directory.
  for (const entry of manifest.assets.filter(({ path }) => path.startsWith("pyodide/") || path === "worker/pyodide_worker.js")) {
    const hit = await fromCache(entry.path);
    assert.equal(hit.status, 200, entry.path);
    const bytes = new Uint8Array(await hit.arrayBuffer());
    assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256, entry.path);
    const target = path.join(temp, entry.path);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, bytes);
  }
  const pyodideDir = path.join(temp, "pyodide") + path.sep;
  const { loadPyodide } = await import(pathToFileURL(path.join(pyodideDir, "pyodide.mjs")));
  const { PyodideWorkerRuntime } = await import(pathToFileURL(path.join(temp, "worker/pyodide_worker.js")));
  const requested = [];
  t.mock.method(globalThis, "fetch", async (input) => {
    const request = input instanceof Request ? input : new Request(input);
    requested.push(request.url);
    return restarted.handleFetch(request, storage);
  });
  // Adapt only the loader directory for Node. The real worker provisions its own packages and wheel.
  Object.defineProperty(globalThis, "loadPyodide", {
    configurable: true,
    value: ({ indexURL }) => {
      assert.equal(indexURL, new URL("pyodide/", scope).href);
      return loadPyodide({ indexURL: pyodideDir, packageCacheDir: pyodideDir });
    },
  });
  t.after(() => { delete globalThis.loadPyodide; });
  const messages = [];
  const worker = new PyodideWorkerRuntime({ origin: scope.origin, postMessage: (msg) => messages.push(msg) });
  const wheelURL = new URL(wheelPath, scope).href;
  await worker.handleMessage({
    kind: "init",
    msg_id: "restart",
    config: { indexURL: new URL("pyodide/", scope).href, packages: ["numpy", "scipy", wheelURL] },
  });
  const init = messages.at(-1);
  assert.equal(init.kind, "init_ok", JSON.stringify(init));
  assert.ok(init.capabilities.operations.includes("statespace.solve_lyapunov"));
  assert.deepEqual(requested, [wheelURL]);

  const request = {
    api_version: "1.0", request_id: "lyapunov-offline", project_id: "audit-f9", project_revision: 0,
    operation: "statespace.solve_lyapunov", payload: { A: [[-2]], Q: [[4]] }, options: {},
    timeout_policy: { hard_timeout_ms: 30000 },
  };
  await worker.handleMessage({ kind: "rpc_request", request });
  const { kind, response } = messages.at(-1);
  assert.equal(kind, "rpc_response");
  assert.equal(response.status, "success", JSON.stringify(response));
  assert.equal(response.request_id, request.request_id);
  // -2X + X(-2) + 4 = 0 has the unique X = 1, exactly representable in binary64.
  assert.deepEqual(response.result.X.data, [1]);
  assert.deepEqual(response.result.X.shape, [1, 1]);
  t.diagnostic(JSON.stringify({ wasm: init.capabilities.lib_versions, assets: report.totalManifestAssets,
    fetchesAfterRestart: requested, algorithm: response.provenance.algorithm, X: response.result.X }));
});
