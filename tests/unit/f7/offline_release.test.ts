/** Unit tests for storage, integrity and SW lifecycle. Browser computation is audited by F9. */
import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { InMemoryCacheStorage, ServiceWorkerController } from "../../../web/worker/service_worker.ts";

const base = "https://example.org/lab/";
const manifestPath = "release-manifest.json";
const lockPath = "pyodide/pyodide-lock.json";
const hash = (s: string) => crypto.createHash("sha256").update(s).digest("hex");

function testRelease(revision = "A") {
  const bodies = new Map<string, string>();
  const packages: Record<string, { file_name: string; depends: string[]; sha256: string }> = {};
  for (const [name, deps] of Object.entries({ numpy: [], scipy: ["numpy", "openblas"], openblas: [], micropip: ["packaging"], packaging: [] })) {
    const filename = name + ".whl";
    bodies.set("pyodide/" + filename, name);
    packages[name] = { file_name: filename, depends: deps, sha256: hash(name) };
  }
  for (const path of ["index.html", "app/main.js", "app/styles.css", "service_worker.js", "worker/pyodide_worker.js",
    "pyodide/pyodide.mjs", "pyodide/pyodide.js", "pyodide/python_stdlib.zip", "pyodide/pyodide.asm.js",
    "pyodide/pyodide.asm.wasm", "wheels/control_lab-1.0.0-py3-none-any.whl"]) bodies.set(path, path + revision);
  bodies.set(lockPath, JSON.stringify({ info: { version: "0.27.5" }, packages }));
  const assets = Array.from(bodies, ([path, body]) => ({ path, sha256: hash(body), size: body.length }));
  const manifest = { schema_version: 1, product_version: "1.0.0", pyodide_version: "0.27.5", assets };
  bodies.set(manifestPath, JSON.stringify(manifest));
  const requests: string[] = [];
  const download = async (request: Request | string) => {
    assert.ok(request instanceof Request);
    assert.ok(request.url.startsWith(base));
    assert.equal(request.redirect, "error");
    requests.push(request.url);
    const body = bodies.get(request.url.slice(base.length));
    return body === undefined ? new Response(null, { status: 404 }) : new Response(body);
  };
  return { download, bodies, assets, manifest, requests };
}

test("F7 offline: prefix, reload, HEAD, no misses reach the network, scope isolation", async () => {
  const storage = new InMemoryCacheStorage();
  const sw = new ServiceWorkerController(base);
  const release = testRelease();
  await storage.open("unrelated-cache");
  const sibling = "https://example.org/class/";
  const other = new ServiceWorkerController(sibling);
  const siblingCache = await other.install(storage, (req) => release.download(new Request(
    (req as Request).url.replace(sibling, base), { redirect: "error" })));
  await other.activate(storage);
  const cache = await sw.install(storage, release.download);
  assert.equal((await sw.checkOfflineReadiness(storage)).ready, false);
  await sw.activate(storage);
  assert.ok(await storage.has(siblingCache));
  assert.ok(await storage.has("unrelated-cache"));
  const restart = new ServiceWorkerController(base);
  assert.deepEqual(await restart.checkOfflineReadiness(storage), {
    cacheName: cache, ready: true, missingUrls: [], corruptUrls: [], totalManifestAssets: release.assets.length,
  });
  for (const [path, body] of release.bodies) {
    assert.equal(await (await restart.handleFetch(new Request(base + path), storage)).text(), body);
  }
  assert.equal(await (await restart.handleFetch(new Request(base + "?engine=pyodide"), storage)).text(), "index.htmlA");
  const head = await restart.handleFetch(new Request(base, { method: "HEAD" }), storage);
  assert.equal(head.status, 200);
  assert.equal(await head.text(), "");
  for (const [url, status] of [[base + "missing", 503], ["https://cdn.example.org/lib.js", 403],
    [base + "telemetry/collect", 403], [sibling, 403]] as const) {
    assert.equal((await restart.handleFetch(new Request(url), storage)).status, status);
  }
  assert.equal((await restart.handleFetch(new Request(base, { method: "POST" }), storage)).status, 405);
  assert.equal(release.requests.length, 2 * release.bodies.size);
});

test("F7 offline: rollback preserves active and same-version updates switch only on activation", async () => {
  const storage = new InMemoryCacheStorage();
  const sw = new ServiceWorkerController(base);
  const original = await sw.install(storage, testRelease().download);
  await sw.activate(storage);
  const damaged = testRelease("B");
  damaged.bodies.set("index.html", "index.htmlX");
  await assert.rejects(() => sw.install(storage, damaged.download), /SHA-256/);
  assert.equal((await sw.checkOfflineReadiness(storage)).cacheName, original);
  damaged.bodies.delete("index.html");
  await assert.rejects(() => sw.install(storage, damaged.download), /provisionamento/);
  const next = await sw.install(storage, testRelease("B").download);
  assert.equal(await (await sw.handleFetch(new Request(base), storage)).text(), "index.htmlA");
  const poisoned = await storage.open(next);
  await poisoned.put(base + lockPath, new Response("{}"));
  await assert.rejects(() => sw.activate(storage), /corrompido/);
  assert.equal((await sw.checkOfflineReadiness(storage)).ready, true);
  const recovered = await sw.install(storage, testRelease("B").download);
  await sw.activate(storage);
  assert.deepEqual((await storage.keys()).filter((name) => !name.endsWith(":meta")), [recovered]);
  assert.equal(await (await sw.handleFetch(new Request(base), storage)).text(), "index.htmlB");
});

test("F7 offline: missing, corrupt and altered manifest cannot attest readiness or serve damaged code", async () => {
  const storage = new InMemoryCacheStorage();
  const sw = new ServiceWorkerController(base);
  const name = await sw.install(storage, testRelease().download);
  await sw.activate(storage);
  const cache = await storage.open(name);
  await cache.delete?.(base + "pyodide/openblas.whl");
  await cache.put(base + "app/main.js", new Response("app/main.jsX"));
  const report = await sw.checkOfflineReadiness(storage);
  assert.equal(report.ready, false);
  assert.deepEqual(report.missingUrls, ["pyodide/openblas.whl"]);
  assert.deepEqual(report.corruptUrls, ["app/main.js"]);
  assert.equal((await sw.handleFetch(new Request(base + "app/main.js"), storage)).status, 503);
  await cache.put(base + manifestPath, new Response("{}"));
  assert.equal((await sw.checkOfflineReadiness(storage)).ready, false);
  assert.equal((await sw.handleFetch(new Request(base), storage)).status, 503);
});

test("F7 offline: reject manifest escapes, duplicates, missing hashes and incomplete transitive closure", async () => {
  for (const path of ["../x", "/app", "https://external.invalid", "%2e%2e/x", "app/./x", "app/main.js", "app/scripts?a=1"]) {
    const release = testRelease();
    release.manifest.assets.push({ path, sha256: hash("x"), size: 1 });
    release.bodies.set(manifestPath, JSON.stringify(release.manifest));
    await assert.rejects(() => new ServiceWorkerController(base).install(new InMemoryCacheStorage(), release.download));
    assert.equal(release.requests.length, 1);
  }
  const missingHash = testRelease();
  missingHash.assets[0].sha256 = "";
  missingHash.bodies.set(manifestPath, JSON.stringify(missingHash.manifest));
  await assert.rejects(() => new ServiceWorkerController(base).install(new InMemoryCacheStorage(), missingHash.download));
  for (const path of ["pyodide/python_stdlib.zip", "pyodide/openblas.whl"]) {
    const release = testRelease();
    release.manifest.assets = release.assets.filter((asset) => asset.path !== path);
    release.bodies.set(manifestPath, JSON.stringify(release.manifest));
    await assert.rejects(() => new ServiceWorkerController(base).install(new InMemoryCacheStorage(), release.download));
  }
});
