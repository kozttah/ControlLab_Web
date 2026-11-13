/**
 * Repositório em RAM no Worker indexado por (project_id, object_id, revision)
 * com política LRU, orçamento explícito de memória, pinning de projeto ativo,
 * falha honesta RESOURCE_LIMIT pré-alocação e snapshot/reidratação pós-terminate()
 * (CL-DIR-001 Seções 8.2, 11.3, 13.9, R-16, R-28, T-RPC-02).
 */

import {
  ControlLabBridgeError,
  ensureFiniteJson,
  generateUuid,
  isPlainObject,
  isPyProxyLike,
} from "../bridge/protocol.ts";
import type { StoredProjectSnapshot } from "../storage/indexeddb_store.ts";

export interface ModelKey {
  project_id: string;
  object_id: string;
  revision: number;
}

export interface StoredModelEntry {
  key: string;
  project_id: string;
  object_id: string;
  revision: number;
  kind: string;
  value: Record<string, unknown>;
  byte_size: number;
  created_at: string;
  last_accessed_seq: number;
}

export interface WorkerModelStoreSnapshot {
  schema_version: "1.0.0";
  store_instance_id: string;
  pinned_projects: string[];
  active_project_id: string | null;
  entries: Array<{
    project_id: string;
    object_id: string;
    revision: number;
    kind: string;
    value: Record<string, unknown>;
    byte_size: number;
    created_at: string;
  }>;
  created_at: string;
}

export interface WorkerModelStoreStats {
  store_instance_id: string;
  entry_count: number;
  total_bytes: number;
  max_bytes: number;
  max_entries: number;
  pinned_projects: string[];
  active_project_id: string | null;
  hits: number;
  misses: number;
  evictions: number;
}

export interface WorkerModelStoreOptions {
  maxBytes?: number;
  maxEntries?: number;
}

export function makeCompositeModelKey(
  projectId: string,
  objectId: string,
  revision: number,
): string {
  if (typeof projectId !== "string" || projectId.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "project_id deve ser string não vazia em WorkerModelStore.",
    );
  }
  if (typeof objectId !== "string" || objectId.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "object_id deve ser string não vazia em WorkerModelStore.",
    );
  }
  if (!Number.isInteger(revision) || revision < 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `revision deve ser inteiro >= 0 em WorkerModelStore, recebido ${String(revision)}.`,
    );
  }
  return `${projectId}::${objectId}::${revision}`;
}

export function estimateSerializedBytes(value: unknown): number {
  const json = JSON.stringify(value);
  return new TextEncoder().encode(json).byteLength;
}

export class WorkerModelStore {
  public readonly storeInstanceId: string;
  private readonly maxBytes: number;
  private readonly maxEntries: number;
  private readonly entries = new Map<string, StoredModelEntry>();
  private readonly pinnedProjects = new Set<string>();
  private activeProjectId: string | null = null;
  private totalBytes = 0;
  private accessSeq = 0;
  private hits = 0;
  private misses = 0;
  private evictions = 0;

  constructor(options?: WorkerModelStoreOptions) {
    const maxBytes = options?.maxBytes ?? 64 * 1024 * 1024;
    const maxEntries = options?.maxEntries ?? 1024;
    if (!Number.isInteger(maxBytes) || maxBytes < 1) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `WorkerModelStore.maxBytes deve ser inteiro >= 1, recebido ${String(maxBytes)}.`,
      );
    }
    if (!Number.isInteger(maxEntries) || maxEntries < 1) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `WorkerModelStore.maxEntries deve ser inteiro >= 1, recebido ${String(maxEntries)}.`,
      );
    }
    this.storeInstanceId = `wms-${generateUuid()}`;
    this.maxBytes = maxBytes;
    this.maxEntries = maxEntries;
  }

  public pinProject(projectId: string): void {
    if (typeof projectId !== "string" || projectId.length === 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "projectId inválido em pinProject.",
      );
    }
    this.pinnedProjects.add(projectId);
  }

  public unpinProject(projectId: string): void {
    this.pinnedProjects.delete(projectId);
    if (this.activeProjectId === projectId) {
      this.activeProjectId = null;
    }
  }

  public setActiveProject(projectId: string | null): void {
    if (this.activeProjectId !== null && this.activeProjectId !== projectId) {
      this.pinnedProjects.delete(this.activeProjectId);
    }
    this.activeProjectId = projectId;
    if (projectId !== null) {
      this.pinnedProjects.add(projectId);
    }
  }

  public isProjectPinned(projectId: string): boolean {
    return this.pinnedProjects.has(projectId);
  }

  public getPinnedProjects(): string[] {
    return Array.from(this.pinnedProjects).sort();
  }

  public put(
    projectId: string,
    objectId: string,
    revision: number,
    value: Record<string, unknown>,
    options?: { kind?: string; byteSize?: number; createdAt?: string },
  ): StoredModelEntry {
    const compositeKey = makeCompositeModelKey(projectId, objectId, revision);
    if (isPyProxyLike(value)) {
      throw new ControlLabBridgeError(
        "INTERNAL_ERROR",
        "WorkerModelStore não aceita PyProxy; materialize valores finitos antes de armazenar.",
      );
    }
    if (!isPlainObject(value)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "WorkerModelStore.put espera um objeto JSON plano.",
      );
    }

    const cleanValue = ensureFiniteJson(value, "$.model_store.value");
    const kind =
      options?.kind ??
      (typeof cleanValue.kind === "string" && cleanValue.kind.length > 0
        ? cleanValue.kind
        : "GenericObject");
    const byteSize =
      options?.byteSize !== undefined
        ? options.byteSize
        : estimateSerializedBytes(cleanValue);

    if (!Number.isFinite(byteSize) || byteSize < 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `byteSize inválido em WorkerModelStore: ${String(byteSize)}.`,
      );
    }

    // Verifica antes de alocar ou evictar qualquer coisa se item único excede o teto total
    if (byteSize > this.maxBytes) {
      throw new ControlLabBridgeError(
        "RESOURCE_LIMIT",
        `Objeto '${objectId}@${revision}' (${byteSize} bytes) excede orçamento máximo de memória do WorkerModelStore (${this.maxBytes} bytes).`,
        {
          parameters: {
            project_id: projectId,
            object_id: objectId,
            revision,
            requested_bytes: byteSize,
            max_bytes: this.maxBytes,
          },
          next_step: "Reduza o tamanho do objeto ou aumente o orçamento do WorkerModelStore.",
        },
      );
    }

    const existing = this.entries.get(compositeKey);
    const existingBytes = existing ? existing.byte_size : 0;
    const neededAdditionalBytes = byteSize - existingBytes;
    const neededAdditionalEntries = existing ? 0 : 1;

    // Simular quais entradas não-pinadas seriam evictadas em ordem LRU
    // antes de mutar, garantindo atomicidade na falha RESOURCE_LIMIT.
    let projectedBytes = this.totalBytes + neededAdditionalBytes;
    let projectedCount = this.entries.size + neededAdditionalEntries;

    const toEvict: StoredModelEntry[] = [];
    if (projectedBytes > this.maxBytes || projectedCount > this.maxEntries) {
      // Ordena apenas entradas de projetos NÃO pinados em ordem LRU (Map mantém ordem de acesso)
      for (const entry of this.entries.values()) {
        if (entry.key === compositeKey) {
          continue;
        }
        if (this.pinnedProjects.has(entry.project_id)) {
          continue;
        }
        toEvict.push(entry);
        projectedBytes -= entry.byte_size;
        projectedCount -= 1;
        if (
          projectedBytes <= this.maxBytes &&
          projectedCount <= this.maxEntries
        ) {
          break;
        }
      }
    }

    if (projectedBytes > this.maxBytes || projectedCount > this.maxEntries) {
      let pinnedBytes = 0;
      let pinnedEntries = 0;
      for (const entry of this.entries.values()) {
        if (this.pinnedProjects.has(entry.project_id)) {
          pinnedBytes += entry.byte_size;
          pinnedEntries += 1;
        }
      }
      throw new ControlLabBridgeError(
        "RESOURCE_LIMIT",
        `Orçamento de memória do WorkerModelStore insuficiente sem evictar projeto ativo pinado (necessário ${byteSize} bytes; livre após evicção não-pinada=${this.maxBytes - (projectedBytes - byteSize)}/${this.maxBytes} bytes).`,
        {
          parameters: {
            project_id: projectId,
            object_id: objectId,
            revision,
            requested_bytes: byteSize,
            max_bytes: this.maxBytes,
            max_entries: this.maxEntries,
            pinned_bytes: pinnedBytes,
            pinned_entries: pinnedEntries,
            projected_bytes: projectedBytes,
            projected_entries: projectedCount,
          },
          next_step: "Desafixe projetos inativos ou libere revisões antigas antes de alocar.",
        },
      );
    }

    // Efetivar evicções LRU apenas de entradas não-pinadas
    for (const victim of toEvict) {
      this.entries.delete(victim.key);
      this.totalBytes -= victim.byte_size;
      this.evictions += 1;
    }

    if (existing) {
      this.entries.delete(compositeKey);
      this.totalBytes -= existing.byte_size;
    }

    this.accessSeq += 1;
    const stored: StoredModelEntry = {
      key: compositeKey,
      project_id: projectId,
      object_id: objectId,
      revision,
      kind,
      value: structuredClone(cleanValue),
      byte_size: byteSize,
      created_at: options?.createdAt ?? new Date().toISOString(),
      last_accessed_seq: this.accessSeq,
    };

    this.entries.set(compositeKey, stored);
    this.totalBytes += byteSize;
    return this.cloneEntry(stored);
  }

  public get(
    projectId: string,
    objectId: string,
    revision: number,
  ): StoredModelEntry | null {
    const key = makeCompositeModelKey(projectId, objectId, revision);
    const entry = this.entries.get(key);
    if (!entry) {
      this.misses += 1;
      return null;
    }
    this.hits += 1;
    // Atualiza ordem LRU (delete + set move para o fim do Map)
    this.entries.delete(key);
    this.accessSeq += 1;
    entry.last_accessed_seq = this.accessSeq;
    this.entries.set(key, entry);
    return this.cloneEntry(entry);
  }

  public peek(
    projectId: string,
    objectId: string,
    revision: number,
  ): StoredModelEntry | null {
    const key = makeCompositeModelKey(projectId, objectId, revision);
    const entry = this.entries.get(key);
    return entry ? this.cloneEntry(entry) : null;
  }

  public has(projectId: string, objectId: string, revision: number): boolean {
    const key = makeCompositeModelKey(projectId, objectId, revision);
    return this.entries.has(key);
  }

  public delete(
    projectId: string,
    objectId: string,
    revision: number,
  ): boolean {
    const key = makeCompositeModelKey(projectId, objectId, revision);
    const existing = this.entries.get(key);
    if (!existing) {
      return false;
    }
    this.entries.delete(key);
    this.totalBytes -= existing.byte_size;
    return true;
  }

  public evictProject(projectId: string): number {
    let removed = 0;
    for (const [k, entry] of Array.from(this.entries.entries())) {
      if (entry.project_id === projectId) {
        this.entries.delete(k);
        this.totalBytes -= entry.byte_size;
        removed += 1;
      }
    }
    return removed;
  }

  public listEntries(projectId?: string): StoredModelEntry[] {
    const out: StoredModelEntry[] = [];
    for (const entry of this.entries.values()) {
      if (projectId === undefined || entry.project_id === projectId) {
        out.push(this.cloneEntry(entry));
      }
    }
    return out;
  }

  public clear(): void {
    this.entries.clear();
    this.totalBytes = 0;
  }

  public getStats(): WorkerModelStoreStats {
    return {
      store_instance_id: this.storeInstanceId,
      entry_count: this.entries.size,
      total_bytes: this.totalBytes,
      max_bytes: this.maxBytes,
      max_entries: this.maxEntries,
      pinned_projects: this.getPinnedProjects(),
      active_project_id: this.activeProjectId,
      hits: this.hits,
      misses: this.misses,
      evictions: this.evictions,
    };
  }

  public exportSnapshot(projectId?: string): WorkerModelStoreSnapshot {
    const entries: WorkerModelStoreSnapshot["entries"] = [];
    for (const entry of this.entries.values()) {
      if (projectId !== undefined && entry.project_id !== projectId) {
        continue;
      }
      entries.push({
        project_id: entry.project_id,
        object_id: entry.object_id,
        revision: entry.revision,
        kind: entry.kind,
        value: structuredClone(entry.value),
        byte_size: entry.byte_size,
        created_at: entry.created_at,
      });
    }
    return {
      schema_version: "1.0.0",
      store_instance_id: this.storeInstanceId,
      pinned_projects: this.getPinnedProjects(),
      active_project_id: this.activeProjectId,
      entries,
      created_at: new Date().toISOString(),
    };
  }

  public rehydrateFromSnapshot(snapshot: WorkerModelStoreSnapshot): number {
    if (snapshot.schema_version !== "1.0.0") {
      throw new ControlLabBridgeError(
        "SCHEMA_UNSUPPORTED",
        `Versão de snapshot de WorkerModelStore não suportada: ${String(snapshot.schema_version)}`,
      );
    }
    if (snapshot.active_project_id !== null) {
      this.setActiveProject(snapshot.active_project_id);
    }
    for (const p of snapshot.pinned_projects) {
      this.pinProject(p);
    }
    let count = 0;
    for (const item of snapshot.entries) {
      this.put(item.project_id, item.object_id, item.revision, item.value, {
        kind: item.kind,
        byteSize: item.byte_size,
        createdAt: item.created_at,
      });
      count += 1;
    }
    return count;
  }

  public rehydrateFromIndexedDBSnapshot(
    idbSnapshot: StoredProjectSnapshot,
    options?: { pinProject?: boolean },
  ): number {
    if (options?.pinProject !== false || idbSnapshot.pinned) {
      this.pinProject(idbSnapshot.project_id);
    }
    let restored = 0;
    for (const obj of idbSnapshot.objects) {
      this.put(obj.project_id, obj.object_id, obj.revision, obj.value, {
        kind: obj.kind,
        createdAt: obj.created_at,
      });
      restored += 1;
    }
    return restored;
  }

  private cloneEntry(entry: StoredModelEntry): StoredModelEntry {
    return {
      ...entry,
      value: structuredClone(entry.value),
    };
  }
}
