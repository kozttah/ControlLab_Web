/**
 * Service Worker versionado (controllab-static-v1.0.0) com manifesto fixo de ativos,
 * instalação atômica em CacheStorage, operação 100% offline pós-provisionamento,
 * bloqueio de origens externas/CDN não permitidas e troca atômica de versão
 * (CL-DIR-001 Seções 11.2, 12.2, R-01, R-22, T-SEC-01).
 */

import { ControlLabBridgeError, sha256Hex } from "../bridge/protocol.ts";

export const SERVICE_WORKER_VERSION = "1.0.0" as const;
export const CACHE_NAME_PREFIX = "controllab-static-" as const;
export const DEFAULT_STATIC_CACHE_NAME = `${CACHE_NAME_PREFIX}v${SERVICE_WORKER_VERSION}`;

export interface StaticAssetEntry {
  url: string;
  kind: "html" | "js" | "wasm" | "pyodide" | "wheel" | "json" | "css";
  version: string;
  sha256?: string;
}

export const DEFAULT_STATIC_MANIFEST: readonly StaticAssetEntry[] = [
  { url: "/index.html", kind: "html", version: "1.0.0" },
  { url: "/app/main.js", kind: "js", version: "1.0.0" },
  { url: "/bridge/client.js", kind: "js", version: "1.0.0" },
  { url: "/worker/pyodide_worker.js", kind: "js", version: "1.0.0" },
  { url: "/pyodide/pyodide.js", kind: "pyodide", version: "0.27.5" },
  { url: "/pyodide/pyodide.asm.js", kind: "pyodide", version: "0.27.5" },
  { url: "/pyodide/pyodide.asm.wasm", kind: "wasm", version: "0.27.5" },
  { url: "/pyodide/pyodide-lock.json", kind: "json", version: "0.27.5" },
  {
    url: "/wheels/control_lab-1.0.0-py3-none-any.whl",
    kind: "wheel",
    version: "1.0.0",
  },
  {
    url: "/wheels/numpy-2.0.2-cp312-cp312-pyodide_2024_0_wasm32.whl",
    kind: "wheel",
    version: "2.0.2",
  },
  {
    url: "/wheels/scipy-1.14.1-cp312-cp312-pyodide_2024_0_wasm32.whl",
    kind: "wheel",
    version: "1.14.1",
  },
] as const;

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

export interface ServiceWorkerConfig {
  version?: string;
  origin?: string;
  allowedOrigins?: readonly string[];
  manifest?: readonly StaticAssetEntry[];
  offlineOnlyAfterProvisioning?: boolean;
  blockedTelemetryPaths?: readonly string[];
}

export interface InstallResult {
  cacheName: string;
  version: string;
  cachedUrls: string[];
  atomic: true;
}

export interface ActivateResult {
  activeCacheName: string;
  deletedCaches: string[];
  preservedCaches: string[];
}

export interface OfflineReadinessReport {
  cacheName: string;
  ready: boolean;
  missingUrls: string[];
  totalManifestAssets: number;
}

export function buildCacheName(version: string): string {
  if (typeof version !== "string" || !/^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?$/.test(version)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Versão de Service Worker inválida: ${String(version)}`,
    );
  }
  return `${CACHE_NAME_PREFIX}v${version}`;
}

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

export class ServiceWorkerController {
  private version: string;
  private cacheName: string;
  private readonly origin: string;
  private readonly allowedOrigins: Set<string>;
  private manifest: readonly StaticAssetEntry[];
  private readonly offlineOnlyAfterProvisioning: boolean;
  private readonly blockedTelemetryPatterns: RegExp[];
  private provisioned = false;

  constructor(config?: ServiceWorkerConfig) {
    this.version = config?.version ?? SERVICE_WORKER_VERSION;
    this.cacheName = buildCacheName(this.version);
    this.origin = config?.origin ?? "https://controllab.local";
    this.allowedOrigins = new Set([this.origin, ...(config?.allowedOrigins ?? [])]);
    this.manifest = config?.manifest ?? DEFAULT_STATIC_MANIFEST;
    this.offlineOnlyAfterProvisioning =
      config?.offlineOnlyAfterProvisioning ?? true;
    const defaultTelemetry = ["/telemetry", "/analytics", "/beacon", "/collect"];
    this.blockedTelemetryPatterns = [
      ...defaultTelemetry,
      ...(config?.blockedTelemetryPaths ?? []),
    ].map((p) => new RegExp(p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  }

  public get activeVersion(): string {
    return this.version;
  }

  public get activeCacheName(): string {
    return this.cacheName;
  }

  public get isProvisioned(): boolean {
    return this.provisioned;
  }

  public getManifest(): readonly StaticAssetEntry[] {
    return this.manifest;
  }

  public resolveAndValidateUrl(rawUrl: string): {
    url: URL;
    allowed: boolean;
    reason?: string;
  } {
    let parsed: URL;
    try {
      parsed = new URL(rawUrl, this.origin);
    } catch {
      return {
        url: new URL(this.origin),
        allowed: false,
        reason: `URL inválida: ${rawUrl}`,
      };
    }
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      return {
        url: parsed,
        allowed: false,
        reason: `Protocolo proibido: ${parsed.protocol}`,
      };
    }
    if (!this.allowedOrigins.has(parsed.origin)) {
      return {
        url: parsed,
        allowed: false,
        reason: `Origem externa/CDN não permitida na política offline: ${parsed.origin}`,
      };
    }
    for (const pat of this.blockedTelemetryPatterns) {
      if (pat.test(parsed.pathname)) {
        return {
          url: parsed,
          allowed: false,
          reason: `Endpoint de telemetria bloqueado: ${parsed.pathname}`,
        };
      }
    }
    return { url: parsed, allowed: true };
  }

  /**
   * Instalação atômica do manifesto em CacheStorage.
   * Qualquer erro em qualquer ativo aborta e remove o cache parcial criado.
   */
  public async install(
    cacheStorage: CacheStorageLike,
    fetchFn: FetchFunction,
  ): Promise<InstallResult> {
    const targetCacheName = this.cacheName;
    const stagingCacheName = `${targetCacheName}__staging`;
    const stagingEntries: Array<{ requestUrl: string; response: Response }> = [];

    try {
      for (const asset of this.manifest) {
        const check = this.resolveAndValidateUrl(asset.url);
        if (!check.allowed) {
          throw new ControlLabBridgeError(
            "IMPORT_UNTRUSTED_CODE",
            `Ativo '${asset.url}' violou política de origem do Service Worker: ${check.reason}`,
            { parameters: { url: asset.url, origin: check.url.origin } },
          );
        }

        const canonicalUrl = check.url.toString();
        const req = new Request(canonicalUrl, { method: "GET" });
        const resp = await fetchFn(req);
        if (!resp.ok) {
          throw new ControlLabBridgeError(
            "SOLVER_UNAVAILABLE",
            `Falha ao provisionar ativo '${asset.url}' (HTTP ${resp.status}).`,
            { parameters: { url: asset.url, status: resp.status } },
          );
        }

        if (asset.sha256) {
          const buf = new Uint8Array(await resp.clone().arrayBuffer());
          const actualSha = sha256Hex(buf);
          if (actualSha !== asset.sha256.toLowerCase()) {
            throw new ControlLabBridgeError(
              "IMPORT_UNTRUSTED_CODE",
              `Hash SHA-256 divergente para ativo '${asset.url}'.`,
              {
                parameters: {
                  url: asset.url,
                  expected: asset.sha256,
                  actual: actualSha,
                },
              },
            );
          }
        }

        stagingEntries.push({
          requestUrl: canonicalUrl,
          response: resp,
        });
      }

      // Escreve em cache staging e depois promove atomicamente para targetCacheName
      const stagingCache = await cacheStorage.open(stagingCacheName);
      for (const entry of stagingEntries) {
        await stagingCache.put(new Request(entry.requestUrl), entry.response.clone());
      }

      const targetCache = await cacheStorage.open(targetCacheName);
      for (const entry of stagingEntries) {
        await targetCache.put(new Request(entry.requestUrl), entry.response);
      }
      await cacheStorage.delete(stagingCacheName);

      this.provisioned = true;
      return {
        cacheName: targetCacheName,
        version: this.version,
        cachedUrls: stagingEntries.map((e) => e.requestUrl),
        atomic: true,
      };
    } catch (err: unknown) {
      await cacheStorage.delete(stagingCacheName).catch(() => false);
      await cacheStorage.delete(targetCacheName).catch(() => false);
      throw err;
    }
  }

  /**
   * Limpeza atômica de versões antigas de cache com prefixo `controllab-static-`.
   */
  public async activate(cacheStorage: CacheStorageLike): Promise<ActivateResult> {
    const allKeys = await cacheStorage.keys();
    const deletedCaches: string[] = [];
    const preservedCaches: string[] = [];

    for (const key of allKeys) {
      if (key.startsWith(CACHE_NAME_PREFIX) && key !== this.cacheName) {
        const deleted = await cacheStorage.delete(key);
        if (deleted) {
          deletedCaches.push(key);
        }
      } else {
        preservedCaches.push(key);
      }
    }

    return {
      activeCacheName: this.cacheName,
      deletedCaches,
      preservedCaches,
    };
  }

  /**
   * Atualização atômica de versão: instala o novo manifesto primeiro;
   * apenas se todos os novos ativos forem validados e cacheados é que ativa e remove a versão antiga.
   */
  public async upgradeVersion(
    newVersion: string,
    newManifest: readonly StaticAssetEntry[],
    cacheStorage: CacheStorageLike,
    fetchFn: FetchFunction,
  ): Promise<{ install: InstallResult; activate: ActivateResult }> {
    const prevVersion = this.version;
    const prevCacheName = this.cacheName;
    const prevManifest = this.manifest;
    const prevProvisioned = this.provisioned;

    this.version = newVersion;
    this.cacheName = buildCacheName(newVersion);
    this.manifest = newManifest;

    try {
      const installRes = await this.install(cacheStorage, fetchFn);
      const activateRes = await this.activate(cacheStorage);
      return { install: installRes, activate: activateRes };
    } catch (err: unknown) {
      this.version = prevVersion;
      this.cacheName = prevCacheName;
      this.manifest = prevManifest;
      this.provisioned = prevProvisioned;
      throw err;
    }
  }

  public async checkOfflineReadiness(
    cacheStorage: CacheStorageLike,
  ): Promise<OfflineReadinessReport> {
    const hasCache = await cacheStorage.has(this.cacheName);
    if (!hasCache) {
      return {
        cacheName: this.cacheName,
        ready: false,
        missingUrls: this.manifest.map((a) => a.url),
        totalManifestAssets: this.manifest.length,
      };
    }
    const cache = await cacheStorage.open(this.cacheName);
    const missingUrls: string[] = [];
    for (const asset of this.manifest) {
      const check = this.resolveAndValidateUrl(asset.url);
      const hit = await cache.match(new Request(check.url.toString()));
      if (!hit) {
        missingUrls.push(asset.url);
      }
    }
    return {
      cacheName: this.cacheName,
      ready: missingUrls.length === 0,
      missingUrls,
      totalManifestAssets: this.manifest.length,
    };
  }

  /**
   * Política de fetch offline:
   * 1. Bloqueia origens externas/CDN não permitidas e endpoints de telemetria (HTTP 403, 0 requisições de rede).
   * 2. Resolve ativos do cache versionado ativo sem tocar rede externa.
   * 3. Em modo offline pós-provisionamento, falha com HTTP 503 se recurso não estiver em cache.
   */
  public async handleFetch(
    request: Request | string,
    cacheStorage: CacheStorageLike,
    networkFetchFn?: FetchFunction,
  ): Promise<Response> {
    const reqObj =
      typeof request === "string"
        ? new Request(new URL(request, this.origin).toString())
        : request;

    const check = this.resolveAndValidateUrl(reqObj.url);
    if (!check.allowed) {
      return new Response(
        JSON.stringify({
          error: {
            code: "IMPORT_UNTRUSTED_CODE",
            message: check.reason ?? "Requisição externa bloqueada.",
            url: reqObj.url,
          },
        }),
        {
          status: 403,
          statusText: "Forbidden",
          headers: {
            "Content-Type": "application/json",
            "X-ControlLab-Policy": "blocked-external-origin",
          },
        },
      );
    }

    if (reqObj.method !== "GET" && reqObj.method !== "HEAD") {
      return new Response(
        JSON.stringify({
          error: {
            code: "VALIDATION_ERROR",
            message: `Método HTTP não suportado offline: ${reqObj.method}`,
          },
        }),
        {
          status: 405,
          statusText: "Method Not Allowed",
          headers: { "Content-Type": "application/json" },
        },
      );
    }

    const canonicalReq = new Request(check.url.toString(), {
      method: reqObj.method,
    });
    const cache = await cacheStorage.open(this.cacheName);
    const cached = await cache.match(canonicalReq);
    if (cached) {
      const headers = new Headers(cached.headers);
      headers.set("X-ControlLab-Cache", "HIT");
      headers.set("X-ControlLab-Cache-Version", this.version);
      return new Response(cached.body, {
        status: cached.status,
        statusText: cached.statusText,
        headers,
      });
    }

    if (this.offlineOnlyAfterProvisioning && this.provisioned) {
      return new Response(
        JSON.stringify({
          error: {
            code: "SOLVER_UNAVAILABLE",
            message: `Ativo não provisionado para operação offline: ${check.url.pathname}`,
          },
        }),
        {
          status: 503,
          statusText: "Service Unavailable",
          headers: {
            "Content-Type": "application/json",
            "X-ControlLab-Cache": "MISS-OFFLINE",
          },
        },
      );
    }

    if (networkFetchFn) {
      return networkFetchFn(canonicalReq);
    }

    return new Response(
      JSON.stringify({
        error: {
          code: "SOLVER_UNAVAILABLE",
          message: `Recurso indisponível offline: ${check.url.pathname}`,
        },
      }),
      {
        status: 503,
        statusText: "Service Unavailable",
        headers: { "Content-Type": "application/json" },
      },
    );
  }
}

export function createServiceWorkerController(
  config?: ServiceWorkerConfig,
): ServiceWorkerController {
  return new ServiceWorkerController(config);
}

// ---------------------------------------------------------------------------
// Auto-registro seguro quando carregado como Service Worker real no navegador
// ---------------------------------------------------------------------------

interface ServiceWorkerGlobalLike {
  location?: { origin?: string };
  caches?: CacheStorageLike;
  fetch?: FetchFunction;
  skipWaiting?: () => Promise<void>;
  clients?: { claim?: () => Promise<void> };
  addEventListener?: (
    type: string,
    listener: (event: unknown) => void,
  ) => void;
}

export function attachServiceWorker(
  scope: ServiceWorkerGlobalLike,
  config?: ServiceWorkerConfig,
): ServiceWorkerController {
  const origin = config?.origin ?? scope.location?.origin ?? "https://controllab.local";
  const controller = new ServiceWorkerController({
    ...config,
    origin,
  });

  const cachesApi = scope.caches;
  const fetchApi = scope.fetch;

  if (typeof scope.addEventListener === "function" && cachesApi) {
    scope.addEventListener("install", (rawEv: unknown) => {
      const ev = rawEv as { waitUntil?: (p: Promise<unknown>) => void };
      if (typeof ev.waitUntil === "function" && fetchApi) {
        ev.waitUntil(
          controller
            .install(cachesApi, fetchApi)
            .then(() => scope.skipWaiting?.()),
        );
      }
    });

    scope.addEventListener("activate", (rawEv: unknown) => {
      const ev = rawEv as { waitUntil?: (p: Promise<unknown>) => void };
      if (typeof ev.waitUntil === "function") {
        ev.waitUntil(
          controller
            .activate(cachesApi)
            .then(() => scope.clients?.claim?.()),
        );
      }
    });

    scope.addEventListener("fetch", (rawEv: unknown) => {
      const ev = rawEv as {
        request?: Request;
        respondWith?: (r: Promise<Response>) => void;
      };
      if (ev.request && typeof ev.respondWith === "function") {
        ev.respondWith(controller.handleFetch(ev.request, cachesApi, fetchApi));
      }
    });
  }

  return controller;
}

const maybeSwGlobal = globalThis as unknown as ServiceWorkerGlobalLike & {
  ServiceWorkerGlobalScope?: unknown;
};
if (
  typeof maybeSwGlobal.ServiceWorkerGlobalScope !== "undefined" &&
  typeof maybeSwGlobal.skipWaiting === "function" &&
  maybeSwGlobal.caches !== undefined
) {
  attachServiceWorker(maybeSwGlobal);
}
