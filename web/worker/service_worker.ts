/** Cache de releases estáticas de CL-DIR-001 §11.2. O manifesto da build inclui
 * o próprio bundle SW, portanto seus hashes são lidos depois do empacotamento. */
import { ControlLabBridgeError, isPlainObject } from "../bridge/protocol.ts";

const MANIFEST = "release-manifest.json";
const LOCK = "pyodide/pyodide-lock.json";
const PYODIDE_VERSION = "0.27.5";
const REQUIRED_ASSETS = [
  "index.html", "app/main.js", "app/styles.css", "service_worker.js",
  "worker/pyodide_worker.js", "pyodide/pyodide.js", "pyodide/pyodide.mjs",
  "pyodide/pyodide.asm.js", "pyodide/pyodide.asm.wasm", "pyodide/python_stdlib.zip",
  LOCK, "wheels/control_lab-1.0.0-py3-none-any.whl",
];

interface Asset { path: string; sha256: string; size: number }
interface Release {
  name: string;
  digest: string;
  assets: Map<string, Asset>;
}
export interface OfflineReadinessReport {
  cacheName: string | null;
  ready: boolean;
  missingUrls: string[];
  corruptUrls: string[];
  totalManifestAssets: number;
}
export interface CacheLike {
  match(request: Request | string): Promise<Response | undefined>;
  put(request: Request | string, response: Response): Promise<void>;
  delete?(request: Request | string): Promise<boolean>;
  keys?(): Promise<readonly Request[]>;
}

export interface CacheStorageLike {
  open(cacheName: string): Promise<CacheLike>;
  has(cacheName: string): Promise<boolean>;
  delete(cacheName: string): Promise<boolean>;
  keys(): Promise<string[]>;
  match?(request: Request | string): Promise<Response | undefined>;
}

export type FetchFunction = (
  input: Request | string,
  init?: RequestInit,
) => Promise<Response>;

export class InMemoryCache implements CacheLike {
  private readonly entries = new Map<string, Response>();

  public async match(request: Request | string): Promise<Response | undefined> {
    const key = typeof request === "string" ? request : request.url;
    const hit = this.entries.get(key);
    return hit ? hit.clone() : undefined;
  }

  public async put(request: Request | string, response: Response): Promise<void> {
    const key = typeof request === "string" ? request : request.url;
    this.entries.set(key, response.clone());
  }

  public async delete(request: Request | string): Promise<boolean> {
    const key = typeof request === "string" ? request : request.url;
    return this.entries.delete(key);
  }

  public async keys(): Promise<readonly Request[]> {
    return Array.from(this.entries.keys(), (u) => new Request(u));
  }
}

export class InMemoryCacheStorage implements CacheStorageLike {
  private readonly caches = new Map<string, InMemoryCache>();

  public async open(cacheName: string): Promise<CacheLike> {
    let cache = this.caches.get(cacheName);
    if (!cache) {
      cache = new InMemoryCache();
      this.caches.set(cacheName, cache);
    }
    return cache;
  }

  public async has(cacheName: string): Promise<boolean> {
    return this.caches.has(cacheName);
  }

  public async delete(cacheName: string): Promise<boolean> {
    return this.caches.delete(cacheName);
  }

  public async keys(): Promise<string[]> {
    return Array.from(this.caches.keys());
  }

  public async match(request: Request | string): Promise<Response | undefined> {
    for (const cache of this.caches.values()) {
      const hit = await cache.match(request);
      if (hit) {
        return hit;
      }
    }
    return undefined;
  }
}

function invalid(reason: string): never {
  throw new ControlLabBridgeError("IMPORT_UNTRUSTED_CODE", reason);
}

async function digest(bytes: ArrayBuffer): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function parseManifest(bytes: ArrayBuffer): Map<string, Asset> {
  const value: unknown = JSON.parse(new TextDecoder().decode(bytes));
  if (!isPlainObject(value) || value.schema_version !== 1 || value.product_version !== "1.0.0" ||
      value.pyodide_version !== PYODIDE_VERSION || !Array.isArray(value.assets)) {
    invalid("Manifesto de release incompatível.");
  }
  const assets = new Map<string, Asset>();
  for (const row of value.assets) {
    if (!isPlainObject(row) || typeof row.path !== "string" || !/^[a-zA-Z0-9_./+-]+$/.test(row.path) ||
        row.path.split("/").some((part) => part === "" || part === "." || part === "..") ||
        row.path === MANIFEST || assets.has(row.path) || typeof row.sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(row.sha256) || typeof row.size !== "number" ||
        !Number.isSafeInteger(row.size) || row.size <= 0) {
      invalid("Caminho, hash ou tamanho inválido ou duplicado no manifesto.");
    }
    assets.set(row.path, { path: row.path, sha256: row.sha256, size: row.size });
  }
  for (const path of REQUIRED_ASSETS) {
    if (!assets.has(path)) invalid(`Ativo obrigatório ausente: ${path}`);
  }
  return assets;
}

function validateTransitivePackages(lock: unknown, assets: Map<string, Asset>): void {
  if (!isPlainObject(lock) || !isPlainObject(lock.info) || lock.info.version !== PYODIDE_VERSION ||
      !isPlainObject(lock.packages)) invalid("Lock Pyodide inválido.");
  const queue = ["numpy", "scipy", "micropip"];
  const visited = new Set<string>();
  while (queue.length) {
    const name = queue.pop()!;
    if (visited.has(name)) continue;
    visited.add(name);
    const pkg = lock.packages[name];
    if (!isPlainObject(pkg) || typeof pkg.file_name !== "string" || !/^[\w.+-]+$/.test(pkg.file_name) ||
        !Array.isArray(pkg.depends) || !pkg.depends.every((dep) => typeof dep === "string") ||
        typeof pkg.sha256 !== "string" || assets.get(`pyodide/${pkg.file_name}`)?.sha256 !== pkg.sha256) {
      invalid(`Dependência Pyodide ausente ou divergente no manifesto: ${name}`);
    }
    queue.push(...pkg.depends);
  }
}

async function matches(response: Response, asset: Asset): Promise<boolean> {
  if (!response.ok || response.redirected || response.status !== 200) return false;
  const bytes = await response.arrayBuffer();
  return bytes.byteLength === asset.size && await digest(bytes) === asset.sha256;
}

export class ServiceWorkerController {
  readonly scope: URL;
  private readonly cachePrefix: string;
  private readonly metadata: string;

  constructor(scopeUrl: string) {
    this.scope = new URL(scopeUrl);
    if (!this.scope.pathname.endsWith("/") || this.scope.search || this.scope.hash) invalid("Escopo inválido.");
    this.cachePrefix = `controllab-static:${encodeURIComponent(this.scope.href)}:`;
    this.metadata = this.cachePrefix + "meta";
  }

  private url(path: string): string { return new URL(path, this.scope).href; }

  private async getRelease(storage: CacheStorageLike, pointer: "active" | "pending"): Promise<Release> {
    if (!await storage.has(this.metadata)) invalid("Cache de release ausente.");
    const meta = await storage.open(this.metadata);
    const name = await (await meta.match(this.url(pointer)))?.text();
    const suffix = name?.slice(this.cachePrefix.length);
    if (!name || !name.startsWith(this.cachePrefix) || !suffix ||
        !/^[0-9a-f]{64}:[0-9a-f-]{36}$/.test(suffix) || !await storage.has(name)) invalid("Release indisponível.");
    const hash = suffix.slice(0, 64);
    const cache = await storage.open(name);
    const manifest = await cache.match(this.url(MANIFEST));
    if (!manifest?.ok) invalid("Manifesto local ausente.");
    const bytes = await manifest.arrayBuffer();
    if (await digest(bytes) !== hash) invalid("Manifesto local com SHA-256 divergente.");
    return { name, digest: hash, assets: parseManifest(bytes) };
  }

  private async verifyRelease(storage: CacheStorageLike, release: Release): Promise<OfflineReadinessReport> {
    const cache = await storage.open(release.name);
    const missingUrls: string[] = [];
    const corruptUrls: string[] = [];
    await Promise.all(Array.from(release.assets.values()).map(async (asset) => {
      const response = await cache.match(this.url(asset.path));
      if (!response) missingUrls.push(asset.path);
      else if (!await matches(response, asset)) corruptUrls.push(asset.path);
    }));
    if (!missingUrls.includes(LOCK) && !corruptUrls.includes(LOCK)) {
      try {
        const response = await cache.match(this.url(LOCK));
        validateTransitivePackages(await response?.json(), release.assets);
      } catch { corruptUrls.push(LOCK); }
    }
    return {
      cacheName: release.name, ready: !missingUrls.length && !corruptUrls.length,
      missingUrls, corruptUrls, totalManifestAssets: release.assets.size,
    };
  }

  public async checkOfflineReadiness(storage: CacheStorageLike): Promise<OfflineReadinessReport> {
    try {
      return await this.verifyRelease(storage, await this.getRelease(storage, "active"));
    } catch {
      return { cacheName: null, ready: false, totalManifestAssets: 0, missingUrls: [], corruptUrls: [MANIFEST] };
    }
  }

  public async install(storage: CacheStorageLike, fetchFn: FetchFunction): Promise<string> {
    const download = async (path: string): Promise<Response> => {
      const url = this.url(path);
      const response = await fetchFn(new Request(url, {
        mode: "same-origin", credentials: "same-origin", cache: "no-store", redirect: "error",
      }));
      if (response.status !== 200 || response.redirected || (response.url && response.url !== url)) {
        throw new ControlLabBridgeError("SOLVER_UNAVAILABLE", `Falha no provisionamento local: ${path}`);
      }
      return response;
    };
    const manifest = await download(MANIFEST);
    const bytes = await manifest.clone().arrayBuffer();
    const assets = parseManifest(bytes);
    const hash = await digest(bytes);
    // CacheStorage não oferece rename. Um único put troca o ponteiro de release.
    // Um identificador exclusivo protege releases ativas até em reinstalações de bytes idênticos.
    const name = `${this.cachePrefix}${hash}:${crypto.randomUUID()}`;
    try {
      const cache = await storage.open(name);
      await cache.put(this.url(MANIFEST), manifest);
      for (const asset of assets.values()) {
        const response = await download(asset.path);
        if (!await matches(response.clone(), asset)) invalid(`SHA-256/tamanho divergente: ${asset.path}`);
        if (asset.path === LOCK) validateTransitivePackages(await response.clone().json(), assets);
        await cache.put(this.url(asset.path), response);
      }
      const meta = await storage.open(this.metadata);
      await meta.put(this.url("pending"), new Response(name));
      return name;
    } catch (error) {
      await storage.delete(name);
      throw error;
    }
  }

  public async hasPendingPromotion(storage: CacheStorageLike): Promise<boolean> {
    if (!await storage.has(this.metadata)) return false;
    const meta = await storage.open(this.metadata);
    const pending = await (await meta.match(this.url("pending")))?.text();
    if (!pending) return false;
    const active = await (await meta.match(this.url("active")))?.text();
    return pending !== active;
  }

  public async activate(storage: CacheStorageLike): Promise<string> {
    const release = await this.getRelease(storage, "pending");
    const report = await this.verifyRelease(storage, release);
    if (!report.ready) invalid("Cache candidato incompleto ou corrompido.");
    const meta = await storage.open(this.metadata);
    await meta.put(this.url("active"), new Response(release.name));
    for (const name of await storage.keys()) {
      if (name.startsWith(this.cachePrefix) && name !== this.metadata && name !== release.name) {
        await storage.delete(name);
      }
    }
    return release.name;
  }

  public async handleFetch(request: Request, storage: CacheStorageLike): Promise<Response> {
    const url = new URL(request.url);
    if (url.origin !== this.scope.origin || !url.pathname.startsWith(this.scope.pathname) ||
        /\/(telemetry|analytics|beacon|collect)(?:\/|$)/i.test(url.pathname)) return new Response(null, { status: 403 });
    if (request.method !== "GET" && request.method !== "HEAD") return new Response(null, { status: 405 });
    try {
      const release = await this.getRelease(storage, "active");
      const path = url.pathname.slice(this.scope.pathname.length) || "index.html";
      const asset = release.assets.get(path);
      if (!asset && path !== MANIFEST) return new Response(null, { status: 503 });
      // Parâmetros de navegação não alteram os bytes estáticos.
      const cached = await (await storage.open(release.name)).match(this.url(path));
      if (!cached || (asset && !await matches(cached.clone(), asset))) return new Response(null, { status: 503 });
      const headers = new Headers(cached.headers);
      headers.set("X-ControlLab-Cache", "HIT");
      headers.set("X-ControlLab-Release", release.digest);
      // Preservar a URL da resposta original para resolução de imports e streaming Wasm.
      if (request.method === "GET") return cached;
      return new Response(null, { status: cached.status, headers });
    } catch {
      return new Response(null, { status: 503 });
    }
  }
}

export function attachServiceWorker(scope: ServiceWorkerGlobalScope): ServiceWorkerController {
  const controller = new ServiceWorkerController(scope.registration.scope);
  let promoted = false;
  let activationInFlight: Promise<void> | null = null;
  const ensureActivatedIfNeeded = async (): Promise<void> => {
    if (promoted) return;
    const reg = scope.registration;
    if (reg.installing || reg.waiting || reg.active?.state !== "activated") {
      return;
    }
    if (!activationInFlight) {
      activationInFlight = (async () => {
        try {
          if (await controller.hasPendingPromotion(scope.caches)) {
            await controller.activate(scope.caches);
          }
          promoted = true;
        } finally {
          activationInFlight = null;
        }
      })();
    }
    await activationInFlight;
  };
  scope.addEventListener("install", (event) => {
    event.waitUntil(controller.install(scope.caches, scope.fetch.bind(scope)));
  });
  scope.addEventListener("activate", (event) => {
    // Aguardar o fim dos clientes antigos pela política nativa de waiting/activate.
    event.waitUntil(
      controller.activate(scope.caches).then(() => {
        promoted = true;
        return scope.clients.claim();
      }),
    );
  });
  scope.addEventListener("fetch", (event) => {
    event.respondWith(
      ensureActivatedIfNeeded().then(() => controller.handleFetch(event.request, scope.caches)),
    );
  });
  scope.addEventListener("message", (event) => {
    const port = event.ports[0];
    if (port && event.data?.type === "controllab.checkOfflineReadiness") {
      event.waitUntil(
        ensureActivatedIfNeeded()
          .then(() => controller.checkOfflineReadiness(scope.caches))
          .then((report) => port.postMessage(report)),
      );
    }
  });
  return controller;
}

if (typeof ServiceWorkerGlobalScope !== "undefined" && globalThis instanceof ServiceWorkerGlobalScope) {
  attachServiceWorker(globalThis as unknown as ServiceWorkerGlobalScope);
}
