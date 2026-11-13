/**
 * Guardião determinístico de PyProxy dentro do Web Worker:
 * PyProxyRegistry + withPyProxy + bloqueio estrito de egresso via postMessage
 * (CL-DIR-001 Seções 8.1, 13.9, 14.1 G-0A).
 */

import { ControlLabBridgeError, isPyProxyLike } from "../bridge/protocol.ts";

export interface PyProxyLike {
  destroy(options?: { message?: string }): void;
  toJs?: (options?: Record<string, unknown>) => unknown;
  type?: string;
  $$?: unknown;
  __isPyProxy?: boolean;
}

export interface PyProxyRecord {
  id: number;
  label: string;
  createdAt: number;
}

export interface PyProxyRegistryStats {
  activeProxies: number;
  totalCreated: number;
  totalDestroyed: number;
  activeLabels: string[];
}

export function isPyProxy(value: unknown): value is PyProxyLike {
  return isPyProxyLike(value);
}

export class PyProxyRegistry {
  private readonly active = new Map<PyProxyLike, PyProxyRecord>();
  private nextId = 0;
  private totalCreated = 0;
  private totalDestroyed = 0;

  public get activeProxies(): number {
    return this.active.size;
  }

  public getActiveCount(): number {
    return this.active.size;
  }

  public track<T extends PyProxyLike>(proxy: T, label = "pyproxy"): T {
    if (
      (typeof proxy !== "object" && typeof proxy !== "function") ||
      proxy === null ||
      typeof proxy.destroy !== "function"
    ) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Objeto passado a PyProxyRegistry.track ('${label}') não possui método destroy().`,
      );
    }
    if (!this.active.has(proxy)) {
      this.nextId += 1;
      this.totalCreated += 1;
      this.active.set(proxy, {
        id: this.nextId,
        label,
        createdAt: Date.now(),
      });
    }
    return proxy;
  }

  public isTracked(value: unknown): boolean {
    if ((typeof value !== "object" && typeof value !== "function") || value === null) {
      return false;
    }
    return this.active.has(value as PyProxyLike);
  }

  public release(proxy: PyProxyLike): boolean {
    const rec = this.active.get(proxy);
    if (!rec) {
      return false;
    }
    this.active.delete(proxy);
    this.totalDestroyed += 1;
    proxy.destroy();
    return true;
  }

  public destroyAll(): number {
    let destroyedCount = 0;
    const errors: unknown[] = [];
    for (const [proxy] of Array.from(this.active.entries())) {
      this.active.delete(proxy);
      this.totalDestroyed += 1;
      destroyedCount += 1;
      try {
        proxy.destroy();
      } catch (err: unknown) {
        errors.push(err);
      }
    }
    if (errors.length > 0) {
      throw new ControlLabBridgeError(
        "INTERNAL_ERROR",
        `Falha ao destruir ${errors.length} PyProxy(s) durante limpeza.`,
        { details: { errorCount: errors.length } },
      );
    }
    return destroyedCount;
  }

  public getStats(): PyProxyRegistryStats {
    const labels: string[] = [];
    for (const rec of this.active.values()) {
      labels.push(rec.label);
    }
    return {
      activeProxies: this.active.size,
      totalCreated: this.totalCreated,
      totalDestroyed: this.totalDestroyed,
      activeLabels: labels,
    };
  }
}

export async function withPyProxy<T extends PyProxyLike, R>(
  registry: PyProxyRegistry,
  factoryOrProxy: T | (() => T | Promise<T>),
  fn: (proxy: T, signal?: AbortSignal) => R | Promise<R>,
  options?: { label?: string; signal?: AbortSignal },
): Promise<R> {
  if (options?.signal?.aborted) {
    throw new ControlLabBridgeError(
      "CANCELLED",
      "Operação cancelada antes da aquisição de PyProxy.",
      { parameters: { label: options.label ?? "pyproxy" } },
    );
  }

  const rawProxy =
    typeof factoryOrProxy === "function"
      ? await (factoryOrProxy as () => T | Promise<T>)()
      : factoryOrProxy;
  const proxy = registry.track(rawProxy, options?.label ?? "pyproxy");

  let abortError: ControlLabBridgeError | null = null;
  const onAbort = () => {
    abortError = new ControlLabBridgeError(
      "CANCELLED",
      "Execução com PyProxy cancelada via AbortSignal.",
      { parameters: { label: options?.label ?? "pyproxy" } },
    );
  };

  if (options?.signal) {
    options.signal.addEventListener("abort", onAbort, { once: true });
    if (options.signal.aborted) {
      onAbort();
    }
  }

  try {
    if (abortError !== null) {
      throw abortError;
    }
    const result = await fn(proxy, options?.signal);
    if (options?.signal?.aborted || abortError !== null) {
      throw (
        abortError ??
        new ControlLabBridgeError(
          "CANCELLED",
          "Operação cancelada durante execução com PyProxy.",
        )
      );
    }
    return result;
  } finally {
    if (options?.signal) {
      options.signal.removeEventListener("abort", onAbort);
    }
    registry.release(proxy);
  }
}

export async function withPyProxies<R>(
  registry: PyProxyRegistry,
  factories: Array<{ label: string; create: () => PyProxyLike | Promise<PyProxyLike> }>,
  fn: (proxies: PyProxyLike[], signal?: AbortSignal) => R | Promise<R>,
  options?: { signal?: AbortSignal },
): Promise<R> {
  if (options?.signal?.aborted) {
    throw new ControlLabBridgeError(
      "CANCELLED",
      "Operação cancelada antes da criação dos PyProxies.",
    );
  }
  const acquired: PyProxyLike[] = [];
  try {
    for (const item of factories) {
      if (options?.signal?.aborted) {
        throw new ControlLabBridgeError(
          "CANCELLED",
          "Operação cancelada durante aquisição de PyProxies.",
        );
      }
      const p = await item.create();
      registry.track(p, item.label);
      acquired.push(p);
    }
    const res = await fn(acquired, options?.signal);
    if (options?.signal?.aborted) {
      throw new ControlLabBridgeError(
        "CANCELLED",
        "Operação cancelada durante execução com PyProxies.",
      );
    }
    return res;
  } finally {
    for (let i = acquired.length - 1; i >= 0; i -= 1) {
      try {
        registry.release(acquired[i]);
      } catch {
        // Continua liberando demais proxies em cascata
      }
    }
  }
}

export function assertNoPyProxy(
  value: unknown,
  registry?: PyProxyRegistry,
  path = "$",
  seen: WeakSet<object> = new WeakSet<object>(),
): void {
  if (value === null || value === undefined) {
    return;
  }
  const t = typeof value;
  if (t !== "object" && t !== "function") {
    return;
  }

  if (isPyProxy(value) || registry?.isTracked(value)) {
    throw new ControlLabBridgeError(
      "INTERNAL_ERROR",
      `Violação de isolamento do Worker: PyProxy detectado em '${path}' não pode sair via postMessage.`,
      {
        parameters: { path },
        next_step: "Converta o PyProxy com .toJs() e destrua-o dentro do Worker antes de enviar a resposta.",
      },
    );
  }

  if (value instanceof ArrayBuffer || ArrayBuffer.isView(value)) {
    return;
  }

  const obj = value as object;
  if (seen.has(obj)) {
    return;
  }
  seen.add(obj);

  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i += 1) {
      assertNoPyProxy(value[i], registry, `${path}[${i}]`, seen);
    }
    return;
  }

  if (value instanceof Map) {
    let idx = 0;
    for (const [k, v] of value.entries()) {
      assertNoPyProxy(k, registry, `${path}.MapKey[${idx}]`, seen);
      assertNoPyProxy(v, registry, `${path}.MapVal[${idx}]`, seen);
      idx += 1;
    }
    return;
  }

  if (value instanceof Set) {
    let idx = 0;
    for (const item of value.values()) {
      assertNoPyProxy(item, registry, `${path}.Set[${idx}]`, seen);
      idx += 1;
    }
    return;
  }

  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    assertNoPyProxy(v, registry, `${path}.${k}`, seen);
  }
}

export function safeWorkerPostMessage(
  postFn: (message: unknown, transfer?: ArrayBuffer[]) => void,
  message: unknown,
  transferables?: ArrayBuffer[],
  registry?: PyProxyRegistry,
): void {
  assertNoPyProxy(message, registry, "$.postMessage");
  if (transferables && transferables.length > 0) {
    postFn(message, transferables);
  } else {
    postFn(message);
  }
}
