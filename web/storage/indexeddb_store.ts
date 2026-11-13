/**
 * Armazenamento transacional IndexedDB para projetos, objetos científicos,
 * snapshots confirmados e experimentos, com driver em memória transacional testável
 * e injeção de IDBFactory (CL-DIR-001 Seções 8.2, 13.9, R-16, R-19, T-RPC-01, T-RPC-02).
 *
 * Zero dependências de Node.js (100% compatível com navegador / Web Worker).
 */

import {
  computeCanonicalSha256,
  ControlLabBridgeError,
  ensureFiniteJson,
  isPlainObject,
  validateRpcResponse,
  type RpcResponse,
} from "../bridge/protocol.ts";

export const IDB_DEFAULT_DB_NAME = "controllab_web_projects" as const;
export const IDB_SCHEMA_VERSION = 1 as const;
export const IDB_STORES = [
  "projects",
  "objects",
  "snapshots",
  "experiments",
] as const;
export type StoreName = (typeof IDB_STORES)[number];

export interface IDBRequestLike<T = unknown> {
  readonly result: T;
  readonly error: { name: string; message: string } | null;
  onsuccess: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

export interface IDBOpenDBRequestLike extends IDBRequestLike<IDBDatabaseLike> {
  onupgradeneeded: ((ev: unknown) => void) | null;
  onblocked?: ((ev: unknown) => void) | null;
}

export interface IDBIndexLike {
  getAll(query?: unknown): IDBRequestLike<unknown[]>;
}

export interface IDBObjectStoreLike {
  get(key: unknown): IDBRequestLike<unknown>;
  put(value: unknown, key?: unknown): IDBRequestLike<unknown>;
  delete(key: unknown): IDBRequestLike<undefined>;
  clear(): IDBRequestLike<undefined>;
  getAll(query?: unknown): IDBRequestLike<unknown[]>;
  index(name: string): IDBIndexLike;
  createIndex(
    name: string,
    keyPath: string | string[],
    options?: { unique?: boolean },
  ): IDBIndexLike;
}

export interface IDBTransactionLike {
  oncomplete: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onabort: ((ev: unknown) => void) | null;
  readonly error: { name: string; message: string } | null;
  objectStore(name: string): IDBObjectStoreLike;
  abort(): void;
}

export interface IDBDatabaseLike {
  readonly name: string;
  readonly version: number;
  readonly objectStoreNames: { contains(name: string): boolean };
  createObjectStore(
    name: string,
    options?: { keyPath?: string | string[] },
  ): IDBObjectStoreLike;
  transaction(
    storeNames: string | string[],
    mode?: "readonly" | "readwrite",
  ): IDBTransactionLike;
  close(): void;
}

export interface IDBFactoryLike {
  open(name: string, version?: number): IDBOpenDBRequestLike;
  deleteDatabase(name: string): IDBRequestLike<undefined>;
}

// ---------------------------------------------------------------------------
// Driver InMemoryIDBFactory transacional para testes headless em Node 24
// ---------------------------------------------------------------------------

interface InMemoryIndexDef {
  name: string;
  keyPath: string | string[];
  unique: boolean;
}

interface InMemoryStoreSchema {
  keyPath: string | string[] | null;
  indexes: Map<string, InMemoryIndexDef>;
  records: Map<string, unknown>;
}

interface InMemoryDatabaseState {
  version: number;
  stores: Map<string, InMemoryStoreSchema>;
}

function serializeIdbKey(key: unknown): string {
  if (Array.isArray(key)) {
    return JSON.stringify(key.map((part) => serializeIdbKey(part)));
  }
  return `${typeof key}:${String(key)}`;
}

function extractKeyPath(
  value: unknown,
  keyPath: string | string[],
): unknown {
  if (Array.isArray(keyPath)) {
    return keyPath.map((kp) => extractKeyPath(value, kp));
  }
  if (!isPlainObject(value)) {
    return undefined;
  }
  const parts = keyPath.split(".");
  let cur: unknown = value;
  for (const part of parts) {
    if (!isPlainObject(cur) && (typeof cur !== "object" || cur === null)) {
      return undefined;
    }
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

function cloneRecord<T>(val: T): T {
  if (typeof globalThis.structuredClone === "function") {
    return globalThis.structuredClone(val);
  }
  return JSON.parse(JSON.stringify(val)) as T;
}

function keyMatchesQuery(candidateKey: unknown, query: unknown): boolean {
  if (query === undefined || query === null) {
    return true;
  }
  return serializeIdbKey(candidateKey) === serializeIdbKey(query);
}

class InMemoryIDBRequest<T = unknown> implements IDBRequestLike<T> {
  public result!: T;
  public error: { name: string; message: string } | null = null;
  public onsuccess: ((ev: unknown) => void) | null = null;
  public onerror: ((ev: unknown) => void) | null = null;
}

class InMemoryIDBOpenDBRequest
  extends InMemoryIDBRequest<IDBDatabaseLike>
  implements IDBOpenDBRequestLike
{
  public onupgradeneeded: ((ev: unknown) => void) | null = null;
  public onblocked: ((ev: unknown) => void) | null = null;
}

class InMemoryIDBIndex implements IDBIndexLike {
  private readonly storeName: string;
  private readonly indexDef: InMemoryIndexDef;
  private readonly tx: InMemoryIDBTransaction;

  constructor(
    storeName: string,
    indexDef: InMemoryIndexDef,
    tx: InMemoryIDBTransaction,
  ) {
    this.storeName = storeName;
    this.indexDef = indexDef;
    this.tx = tx;
  }

  public getAll(query?: unknown): IDBRequestLike<unknown[]> {
    const req = new InMemoryIDBRequest<unknown[]>();
    this.tx.enqueue(() => {
      const store = this.tx.getWorkingStore(this.storeName);
      const results: unknown[] = [];
      for (const rec of store.records.values()) {
        const idxKey = extractKeyPath(rec, this.indexDef.keyPath);
        if (idxKey !== undefined && keyMatchesQuery(idxKey, query)) {
          results.push(cloneRecord(rec));
        }
      }
      req.result = results;
      req.onsuccess?.({ target: req });
    });
    return req;
  }
}

class InMemoryIDBObjectStore implements IDBObjectStoreLike {
  private readonly storeName: string;
  private readonly tx: InMemoryIDBTransaction;

  constructor(storeName: string, tx: InMemoryIDBTransaction) {
    this.storeName = storeName;
    this.tx = tx;
  }

  public get(key: unknown): IDBRequestLike<unknown> {
    const req = new InMemoryIDBRequest<unknown>();
    this.tx.enqueue(() => {
      const store = this.tx.getWorkingStore(this.storeName);
      const serialized = serializeIdbKey(key);
      const hit = store.records.get(serialized);
      req.result = hit === undefined ? undefined : cloneRecord(hit);
      req.onsuccess?.({ target: req });
    });
    return req;
  }

  public put(value: unknown, explicitKey?: unknown): IDBRequestLike<unknown> {
    const req = new InMemoryIDBRequest<unknown>();
    this.tx.enqueue(() => {
      this.tx.assertWritable(this.storeName);
      const store = this.tx.getWorkingStore(this.storeName);
      const key =
        explicitKey !== undefined
          ? explicitKey
          : store.keyPath !== null
            ? extractKeyPath(value, store.keyPath)
            : undefined;
      if (key === undefined) {
        const err = {
          name: "DataError",
          message: `Chave ausente para store '${this.storeName}'.`,
        };
        req.error = err;
        this.tx.fail(err);
        req.onerror?.({ target: req });
        return;
      }
      const serialized = serializeIdbKey(key);
      const cloned = cloneRecord(value);

      for (const idxDef of store.indexes.values()) {
        if (idxDef.unique) {
          const newIdxKey = extractKeyPath(cloned, idxDef.keyPath);
          if (newIdxKey !== undefined) {
            const newIdxSer = serializeIdbKey(newIdxKey);
            for (const [k, existingRec] of store.records.entries()) {
              if (k === serialized) continue;
              const existingIdx = extractKeyPath(existingRec, idxDef.keyPath);
              if (
                existingIdx !== undefined &&
                serializeIdbKey(existingIdx) === newIdxSer
              ) {
                const err = {
                  name: "ConstraintError",
                  message: `Violação de índice único '${idxDef.name}' em '${this.storeName}'.`,
                };
                req.error = err;
                this.tx.fail(err);
                req.onerror?.({ target: req });
                return;
              }
            }
          }
        }
      }

      store.records.set(serialized, cloned);
      req.result = key;
      req.onsuccess?.({ target: req });
    });
    return req;
  }

  public delete(key: unknown): IDBRequestLike<undefined> {
    const req = new InMemoryIDBRequest<undefined>();
    this.tx.enqueue(() => {
      this.tx.assertWritable(this.storeName);
      const store = this.tx.getWorkingStore(this.storeName);
      store.records.delete(serializeIdbKey(key));
      req.result = undefined;
      req.onsuccess?.({ target: req });
    });
    return req;
  }

  public clear(): IDBRequestLike<undefined> {
    const req = new InMemoryIDBRequest<undefined>();
    this.tx.enqueue(() => {
      this.tx.assertWritable(this.storeName);
      const store = this.tx.getWorkingStore(this.storeName);
      store.records.clear();
      req.result = undefined;
      req.onsuccess?.({ target: req });
    });
    return req;
  }

  public getAll(query?: unknown): IDBRequestLike<unknown[]> {
    const req = new InMemoryIDBRequest<unknown[]>();
    this.tx.enqueue(() => {
      const store = this.tx.getWorkingStore(this.storeName);
      const out: unknown[] = [];
      for (const rec of store.records.values()) {
        if (query !== undefined && query !== null && store.keyPath !== null) {
          const recKey = extractKeyPath(rec, store.keyPath);
          if (!keyMatchesQuery(recKey, query)) continue;
        }
        out.push(cloneRecord(rec));
      }
      req.result = out;
      req.onsuccess?.({ target: req });
    });
    return req;
  }

  public index(name: string): IDBIndexLike {
    const store = this.tx.getWorkingStore(this.storeName);
    const idx = store.indexes.get(name);
    if (!idx) {
      throw new Error(`Índice '${name}' não encontrado na store '${this.storeName}'.`);
    }
    return new InMemoryIDBIndex(this.storeName, idx, this.tx);
  }

  public createIndex(
    name: string,
    keyPath: string | string[],
    options?: { unique?: boolean },
  ): IDBIndexLike {
    const store = this.tx.getWorkingStore(this.storeName);
    const def: InMemoryIndexDef = {
      name,
      keyPath,
      unique: options?.unique === true,
    };
    store.indexes.set(name, def);
    return new InMemoryIDBIndex(this.storeName, def, this.tx);
  }
}

class InMemoryIDBTransaction implements IDBTransactionLike {
  public oncomplete: ((ev: unknown) => void) | null = null;
  public onerror: ((ev: unknown) => void) | null = null;
  public onabort: ((ev: unknown) => void) | null = null;
  public error: { name: string; message: string } | null = null;

  private readonly dbState: InMemoryDatabaseState;
  private readonly scope: Set<string>;
  private readonly mode: "readonly" | "readwrite" | "versionchange";
  private readonly stagedStores: Map<string, InMemoryStoreSchema>;
  private aborted = false;
  private finished = false;
  private pendingOps = 0;
  private scheduledFinalize = false;

  constructor(
    dbState: InMemoryDatabaseState,
    storeNames: string[],
    mode: "readonly" | "readwrite" | "versionchange",
  ) {
    this.dbState = dbState;
    this.scope = new Set(storeNames);
    this.mode = mode;
    this.stagedStores = new Map();

    for (const name of this.scope) {
      const orig = dbState.stores.get(name);
      if (!orig) {
        throw new Error(`ObjectStore '${name}' não existe.`);
      }
      const copiedRecords = new Map<string, unknown>();
      for (const [k, v] of orig.records.entries()) {
        copiedRecords.set(k, cloneRecord(v));
      }
      this.stagedStores.set(name, {
        keyPath: orig.keyPath,
        indexes: new Map(orig.indexes),
        records: copiedRecords,
      });
    }
    this.scheduleFinalizeCheck();
  }

  public addVersionStore(
    name: string,
    keyPath: string | string[] | null,
  ): InMemoryObjectStoreWrapper {
    const schema: InMemoryStoreSchema = {
      keyPath,
      indexes: new Map(),
      records: new Map(),
    };
    this.stagedStores.set(name, schema);
    this.scope.add(name);
    return new InMemoryObjectStoreWrapper(name, this);
  }

  public getWorkingStore(name: string): InMemoryStoreSchema {
    if (!this.scope.has(name)) {
      throw new Error(`Store '${name}' fora do escopo da transação.`);
    }
    const store = this.stagedStores.get(name);
    if (!store) {
      throw new Error(`Store '${name}' não encontrada.`);
    }
    return store;
  }

  public assertWritable(name: string): void {
    if (this.mode === "readonly") {
      throw new Error(`Transação readonly não permite escrita em '${name}'.`);
    }
    if (this.aborted || this.finished) {
      throw new Error("Transação já finalizada/abortada.");
    }
  }

  public objectStore(name: string): IDBObjectStoreLike {
    if (!this.scope.has(name)) {
      throw new Error(`Store '${name}' não pertence à transação.`);
    }
    return new InMemoryIDBObjectStore(name, this);
  }

  public enqueue(fn: () => void): void {
    if (this.aborted || this.finished) {
      return;
    }
    this.pendingOps += 1;
    queueMicrotask(() => {
      if (this.aborted || this.finished) {
        this.pendingOps -= 1;
        this.scheduleFinalizeCheck();
        return;
      }
      try {
        fn();
      } catch (err: unknown) {
        this.fail({
          name: "TransactionError",
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        this.pendingOps -= 1;
        this.scheduleFinalizeCheck();
      }
    });
  }

  public fail(err: { name: string; message: string }): void {
    if (this.aborted || this.finished) {
      return;
    }
    this.error = err;
    this.aborted = true;
    this.finished = true;
    // Descarta stagedStores sem alterar dbState.stores (rollback atômico)
    queueMicrotask(() => {
      this.onerror?.({ target: this });
      this.onabort?.({ target: this });
    });
  }

  public abort(): void {
    if (this.aborted || this.finished) {
      return;
    }
    this.error = { name: "AbortError", message: "Transação abortada explicitamente." };
    this.aborted = true;
    this.finished = true;
    queueMicrotask(() => {
      this.onabort?.({ target: this });
    });
  }

  private scheduleFinalizeCheck(): void {
    if (this.scheduledFinalize || this.aborted || this.finished) {
      return;
    }
    this.scheduledFinalize = true;
    queueMicrotask(() => {
      this.scheduledFinalize = false;
      if (this.aborted || this.finished || this.pendingOps > 0) {
        return;
      }
      // Commit atômico de todas as stores modificadas na transação
      if (this.mode !== "readonly") {
        for (const [name, staged] of this.stagedStores.entries()) {
          this.dbState.stores.set(name, staged);
        }
      }
      this.finished = true;
      this.oncomplete?.({ target: this });
    });
  }
}

class InMemoryObjectStoreWrapper extends InMemoryIDBObjectStore {}

class InMemoryIDBDatabase implements IDBDatabaseLike {
  public readonly name: string;
  public readonly version: number;
  private readonly state: InMemoryDatabaseState;
  private upgradeTx: InMemoryIDBTransaction | null = null;
  private closed = false;

  constructor(name: string, state: InMemoryDatabaseState) {
    this.name = name;
    this.version = state.version;
    this.state = state;
  }

  public setUpgradeTx(tx: InMemoryIDBTransaction | null): void {
    this.upgradeTx = tx;
  }

  public get objectStoreNames(): { contains(name: string): boolean } {
    const state = this.state;
    const tx = this.upgradeTx;
    return {
      contains(storeName: string): boolean {
        if (tx !== null) {
          try {
            tx.getWorkingStore(storeName);
            return true;
          } catch {
            return state.stores.has(storeName);
          }
        }
        return state.stores.has(storeName);
      },
    };
  }

  public createObjectStore(
    name: string,
    options?: { keyPath?: string | string[] },
  ): IDBObjectStoreLike {
    if (!this.upgradeTx) {
      throw new Error("createObjectStore só é permitido em onupgradeneeded.");
    }
    return this.upgradeTx.addVersionStore(name, options?.keyPath ?? null);
  }

  public transaction(
    storeNames: string | string[],
    mode: "readonly" | "readwrite" = "readonly",
  ): IDBTransactionLike {
    if (this.closed) {
      throw new Error(`Banco '${this.name}' já está fechado.`);
    }
    const list = Array.isArray(storeNames) ? storeNames : [storeNames];
    return new InMemoryIDBTransaction(this.state, list, mode);
  }

  public close(): void {
    this.closed = true;
  }
}

export class InMemoryIDBFactory implements IDBFactoryLike {
  private readonly databases = new Map<string, InMemoryDatabaseState>();

  public open(name: string, version = 1): IDBOpenDBRequestLike {
    const req = new InMemoryIDBOpenDBRequest();
    queueMicrotask(() => {
      let dbState = this.databases.get(name);
      const isNew = !dbState;
      if (!dbState) {
        dbState = { version: 0, stores: new Map() };
        this.databases.set(name, dbState);
      }
      if (!isNew && version < dbState.version) {
        req.error = {
          name: "VersionError",
          message: `Versão solicitada (${version}) menor que atual (${dbState.version}).`,
        };
        req.onerror?.({ target: req });
        return;
      }

      const needsUpgrade = isNew || version > dbState.version;
      if (needsUpgrade) {
        dbState.version = version;
        const db = new InMemoryIDBDatabase(name, dbState);
        const upgradeTx = new InMemoryIDBTransaction(
          dbState,
          Array.from(dbState.stores.keys()),
          "versionchange",
        );
        db.setUpgradeTx(upgradeTx);
        req.result = db;
        try {
          req.onupgradeneeded?.({ target: req });
          // Commit upgrade schema immediately after synchronous onupgradeneeded handler
          for (const storeName of IDB_STORES) {
            try {
              const staged = upgradeTx.getWorkingStore(storeName);
              dbState.stores.set(storeName, staged);
            } catch {
              // Store não criada neste upgrade
            }
          }
          // Commit quaisquer stores criadas
          for (const k of Array.from((upgradeTx as unknown as { stagedStores: Map<string, InMemoryStoreSchema> }).stagedStores.keys())) {
            dbState.stores.set(k, upgradeTx.getWorkingStore(k));
          }
          db.setUpgradeTx(null);
          req.onsuccess?.({ target: req });
        } catch (err: unknown) {
          db.setUpgradeTx(null);
          req.error = {
            name: "UpgradeError",
            message: err instanceof Error ? err.message : String(err),
          };
          req.onerror?.({ target: req });
        }
      } else {
        const db = new InMemoryIDBDatabase(name, dbState);
        req.result = db;
        req.onsuccess?.({ target: req });
      }
    });
    return req;
  }

  public deleteDatabase(name: string): IDBRequestLike<undefined> {
    const req = new InMemoryIDBRequest<undefined>();
    queueMicrotask(() => {
      this.databases.delete(name);
      req.result = undefined;
      req.onsuccess?.({ target: req });
    });
    return req;
  }
}

// ---------------------------------------------------------------------------
// Tipos de Persistência e IndexedDBProjectStore
// ---------------------------------------------------------------------------

export interface StoredProjectRecord {
  project_id: string;
  committed_revision: number;
  last_request_id: string | null;
  last_committed_result: RpcResponse | null;
  active_object_refs: Array<{ object_id: string; revision: number }>;
  updated_at: string;
  metadata?: Record<string, unknown>;
}

export interface StoredObjectRecord {
  storage_key: string;
  project_id: string;
  object_id: string;
  revision: number;
  kind: string;
  value: Record<string, unknown>;
  content_hash: string;
  created_at: string;
}

export interface StoredExperimentRecord {
  experiment_key: string;
  project_id: string;
  experiment_id: string;
  request_id: string;
  project_revision: number;
  operation: string;
  response: RpcResponse;
  created_at: string;
}

export interface StoredProjectSnapshot {
  snapshot_key: string;
  schema_version: string;
  project_id: string;
  project_revision: number;
  confirmed: boolean;
  objects: StoredObjectRecord[];
  experiments: StoredExperimentRecord[];
  committed_result: RpcResponse | null;
  pinned: boolean;
  content_hash: string;
  created_at: string;
}

export interface PortableProjectSnapshot {
  format: "controllab_snapshot";
  schema_version: "1.0.0";
  project_id: string;
  project_revision: number;
  objects: StoredObjectRecord[];
  experiments: StoredExperimentRecord[];
  committed_result: RpcResponse | null;
  content_hash: string;
  exported_at: string;
}

export interface CommitProjectRevisionInput {
  project_id: string;
  project_revision: number;
  request_id?: string | null;
  committed_result?: RpcResponse | null;
  objects?: Array<{
    object_id: string;
    revision: number;
    kind?: string;
    value: Record<string, unknown>;
  }>;
  experiment?: {
    experiment_id: string;
    operation: string;
    response: RpcResponse;
  };
  pinned?: boolean;
  require_strictly_greater?: boolean;
  metadata?: Record<string, unknown>;
}

export interface CommitProjectRevisionOutput {
  committed: boolean;
  project: StoredProjectRecord;
  snapshot: StoredProjectSnapshot;
}

export interface IndexedDBProjectStoreOptions {
  dbName?: string;
  idbFactory?: IDBFactoryLike | IDBFactory;
  useInMemoryFallback?: boolean;
}

function makeObjectStorageKey(
  projectId: string,
  objectId: string,
  revision: number,
): string {
  return `${projectId}::${objectId}::${revision}`;
}

function makeSnapshotKey(projectId: string, revision: number): string {
  return `${projectId}::${revision}`;
}

function makeExperimentKey(projectId: string, experimentId: string): string {
  return `${projectId}::${experimentId}`;
}

function idbReqToPromise<T>(req: IDBRequestLike<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () =>
      reject(
        new ControlLabBridgeError(
          "INTERNAL_ERROR",
          `Erro em operação IndexedDB: ${req.error?.message ?? "desconhecido"}`,
          { parameters: { idbError: req.error?.name ?? "UnknownError" } },
        ),
      );
  });
}

function resolveDefaultIdbFactory(
  opts?: IndexedDBProjectStoreOptions,
): IDBFactoryLike {
  if (opts?.idbFactory) {
    return opts.idbFactory as unknown as IDBFactoryLike;
  }
  const globalIdb = (globalThis as { indexedDB?: IDBFactory }).indexedDB;
  if (globalIdb && typeof globalIdb.open === "function") {
    return globalIdb as unknown as IDBFactoryLike;
  }
  if (opts?.useInMemoryFallback !== false) {
    return new InMemoryIDBFactory();
  }
  throw new ControlLabBridgeError(
    "SOLVER_UNAVAILABLE",
    "IndexedDB não está disponível neste ambiente e fallback em memória foi desabilitado.",
  );
}

export class IndexedDBProjectStore {
  private readonly dbName: string;
  private readonly factory: IDBFactoryLike;
  private dbPromise: Promise<IDBDatabaseLike> | null = null;
  private openDb: IDBDatabaseLike | null = null;

  constructor(options?: IndexedDBProjectStoreOptions) {
    this.dbName = options?.dbName ?? IDB_DEFAULT_DB_NAME;
    this.factory = resolveDefaultIdbFactory(options);
  }

  public async open(): Promise<IDBDatabaseLike> {
    if (this.openDb) {
      return this.openDb;
    }
    if (this.dbPromise) {
      return this.dbPromise;
    }
    this.dbPromise = new Promise<IDBDatabaseLike>((resolve, reject) => {
      const req = this.factory.open(this.dbName, IDB_SCHEMA_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("projects")) {
          db.createObjectStore("projects", { keyPath: "project_id" });
        }
        if (!db.objectStoreNames.contains("objects")) {
          const objStore = db.createObjectStore("objects", {
            keyPath: "storage_key",
          });
          objStore.createIndex("by_project", "project_id", { unique: false });
          objStore.createIndex("by_object", ["project_id", "object_id"], {
            unique: false,
          });
        }
        if (!db.objectStoreNames.contains("snapshots")) {
          const snapStore = db.createObjectStore("snapshots", {
            keyPath: "snapshot_key",
          });
          snapStore.createIndex("by_project", "project_id", { unique: false });
        }
        if (!db.objectStoreNames.contains("experiments")) {
          const expStore = db.createObjectStore("experiments", {
            keyPath: "experiment_key",
          });
          expStore.createIndex("by_project", "project_id", { unique: false });
        }
      };
      req.onsuccess = () => {
        this.openDb = req.result;
        resolve(this.openDb);
      };
      req.onerror = () => {
        this.dbPromise = null;
        reject(
          new ControlLabBridgeError(
            "INTERNAL_ERROR",
            `Falha ao abrir IndexedDB '${this.dbName}': ${req.error?.message ?? "desconhecido"}`,
          ),
        );
      };
    });
    return this.dbPromise;
  }

  public close(): void {
    if (this.openDb) {
      this.openDb.close();
      this.openDb = null;
    }
    this.dbPromise = null;
  }

  private async runTransaction<T>(
    storeNames: StoreName[],
    mode: "readonly" | "readwrite",
    fn: (tx: IDBTransactionLike) => Promise<T>,
  ): Promise<T> {
    const db = await this.open();
    const tx = db.transaction(storeNames, mode);
    const completionPromise = new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () =>
        reject(
          new ControlLabBridgeError(
            "INTERNAL_ERROR",
            `Transação IndexedDB falhou: ${tx.error?.message ?? "erro desconhecido"}`,
          ),
        );
      tx.onabort = () =>
        reject(
          new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Transação IndexedDB abortada: ${tx.error?.message ?? "abortada"}`,
          ),
        );
    });

    let result: T;
    try {
      result = await fn(tx);
    } catch (err: unknown) {
      try {
        tx.abort();
      } catch {
        // já abortada/concluída
      }
      await completionPromise.catch(() => undefined);
      throw err;
    }
    await completionPromise;
    return result;
  }

  public async putObject(
    projectId: string,
    objectId: string,
    revision: number,
    value: Record<string, unknown>,
    options?: { kind?: string; createdAt?: string },
  ): Promise<StoredObjectRecord> {
    if (typeof projectId !== "string" || projectId.length === 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "projectId inválido em putObject.",
      );
    }
    if (typeof objectId !== "string" || objectId.length === 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "objectId inválido em putObject.",
      );
    }
    if (!Number.isInteger(revision) || revision < 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `revision deve ser inteiro >= 0, recebido ${String(revision)}.`,
      );
    }

    const cleanValue = ensureFiniteJson(value, "$.object.value");
    const kind =
      options?.kind ??
      (typeof cleanValue.kind === "string" && cleanValue.kind.length > 0
        ? cleanValue.kind
        : "GenericObject");
    const content_hash = computeCanonicalSha256(cleanValue);
    const record: StoredObjectRecord = {
      storage_key: makeObjectStorageKey(projectId, objectId, revision),
      project_id: projectId,
      object_id: objectId,
      revision,
      kind,
      value: cleanValue,
      content_hash,
      created_at: options?.createdAt ?? new Date().toISOString(),
    };

    await this.runTransaction(["objects"], "readwrite", async (tx) => {
      const store = tx.objectStore("objects");
      await idbReqToPromise(store.put(record));
    });
    return record;
  }

  public async getObject(
    projectId: string,
    objectId: string,
    revision: number,
  ): Promise<StoredObjectRecord | null> {
    return this.runTransaction(["objects"], "readonly", async (tx) => {
      const store = tx.objectStore("objects");
      const raw = await idbReqToPromise(
        store.get(makeObjectStorageKey(projectId, objectId, revision)),
      );
      return (raw as StoredObjectRecord | undefined) ?? null;
    });
  }

  public async listObjects(projectId: string): Promise<StoredObjectRecord[]> {
    return this.runTransaction(["objects"], "readonly", async (tx) => {
      const store = tx.objectStore("objects");
      const rows = (await idbReqToPromise(
        store.index("by_project").getAll(projectId),
      )) as StoredObjectRecord[];
      rows.sort((a, b) =>
        a.object_id === b.object_id
          ? a.revision - b.revision
          : a.object_id.localeCompare(b.object_id),
      );
      return rows;
    });
  }

  public async getProject(
    projectId: string,
  ): Promise<StoredProjectRecord | null> {
    return this.runTransaction(["projects"], "readonly", async (tx) => {
      const raw = await idbReqToPromise(
        tx.objectStore("projects").get(projectId),
      );
      return (raw as StoredProjectRecord | undefined) ?? null;
    });
  }

  public async listProjects(): Promise<StoredProjectRecord[]> {
    return this.runTransaction(["projects"], "readonly", async (tx) => {
      const rows = (await idbReqToPromise(
        tx.objectStore("projects").getAll(),
      )) as StoredProjectRecord[];
      rows.sort((a, b) => a.project_id.localeCompare(b.project_id));
      return rows;
    });
  }

  public async listExperiments(
    projectId: string,
  ): Promise<StoredExperimentRecord[]> {
    return this.runTransaction(["experiments"], "readonly", async (tx) => {
      const rows = (await idbReqToPromise(
        tx.objectStore("experiments").index("by_project").getAll(projectId),
      )) as StoredExperimentRecord[];
      rows.sort((a, b) => a.project_revision - b.project_revision);
      return rows;
    });
  }

  /**
   * Executa commit transacional atômico condicionado à monotonicidade de `project_revision`.
   * Qualquer tentativa de comitar revisão obsoleta (< committed_revision) aborta a transação
   * sem alterar nenhuma store.
   */
  public async commitProjectRevision(
    input: CommitProjectRevisionInput,
  ): Promise<CommitProjectRevisionOutput> {
    if (typeof input.project_id !== "string" || input.project_id.length === 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "project_id inválido em commitProjectRevision.",
      );
    }
    if (
      !Number.isInteger(input.project_revision) ||
      input.project_revision < 0
    ) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `project_revision deve ser inteiro >= 0, recebido ${String(input.project_revision)}.`,
      );
    }

    let validatedResult: RpcResponse | null = null;
    if (input.committed_result !== undefined && input.committed_result !== null) {
      validatedResult = validateRpcResponse(input.committed_result);
      if (validatedResult.project_id !== input.project_id) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `project_id da resposta (${validatedResult.project_id}) difere do projeto (${input.project_id}).`,
        );
      }
      if (validatedResult.project_revision !== input.project_revision) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          `project_revision da resposta (${validatedResult.project_revision}) difere da revisão alvo (${input.project_revision}).`,
        );
      }
      if (validatedResult.status === "failure") {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Resposta com status='failure' não pode ser comitada como estado confirmado.",
        );
      }
    }

    const now = new Date().toISOString();

    return this.runTransaction(
      ["projects", "objects", "snapshots", "experiments"],
      "readwrite",
      async (tx) => {
        const projectsStore = tx.objectStore("projects");
        const objectsStore = tx.objectStore("objects");
        const snapshotsStore = tx.objectStore("snapshots");
        const experimentsStore = tx.objectStore("experiments");

        const existingProjRaw = await idbReqToPromise(
          projectsStore.get(input.project_id),
        );
        const existingProj = existingProjRaw as StoredProjectRecord | undefined;

        if (existingProj !== undefined) {
          if (input.project_revision < existingProj.committed_revision) {
            throw new ControlLabBridgeError(
              "VALIDATION_ERROR",
              `Commit rejeitado: revisão obsoleta ${input.project_revision} < revisão comitada ${existingProj.committed_revision}.`,
              {
                parameters: {
                  project_id: input.project_id,
                  requested_revision: input.project_revision,
                  committed_revision: existingProj.committed_revision,
                },
                details: { reason: "STALE_REVISION" },
              },
            );
          }
          if (
            input.require_strictly_greater === true &&
            input.project_revision <= existingProj.committed_revision
          ) {
            throw new ControlLabBridgeError(
              "VALIDATION_ERROR",
              `Commit rejeitado: revisão ${input.project_revision} não avança revisão atual ${existingProj.committed_revision}.`,
              {
                parameters: {
                  project_id: input.project_id,
                  requested_revision: input.project_revision,
                  committed_revision: existingProj.committed_revision,
                },
                details: { reason: "NON_ADVANCING_REVISION" },
              },
            );
          }
        }

        // Persistir objetos novos dentro da mesma transação
        if (input.objects) {
          for (const objInput of input.objects) {
            const cleanVal = ensureFiniteJson(
              objInput.value,
              `$.objects['${objInput.object_id}']`,
            );
            const kind =
              objInput.kind ??
              (typeof cleanVal.kind === "string" && cleanVal.kind.length > 0
                ? cleanVal.kind
                : "GenericObject");
            const objRec: StoredObjectRecord = {
              storage_key: makeObjectStorageKey(
                input.project_id,
                objInput.object_id,
                objInput.revision,
              ),
              project_id: input.project_id,
              object_id: objInput.object_id,
              revision: objInput.revision,
              kind,
              value: cleanVal,
              content_hash: computeCanonicalSha256(cleanVal),
              created_at: now,
            };
            await idbReqToPromise(objectsStore.put(objRec));
          }
        }

        // Persistir experimento dentro da mesma transação
        if (input.experiment) {
          const validExpResp = validateRpcResponse(input.experiment.response);
          const expRec: StoredExperimentRecord = {
            experiment_key: makeExperimentKey(
              input.project_id,
              input.experiment.experiment_id,
            ),
            project_id: input.project_id,
            experiment_id: input.experiment.experiment_id,
            request_id: validExpResp.request_id,
            project_revision: input.project_revision,
            operation: input.experiment.operation,
            response: validExpResp,
            created_at: now,
          };
          await idbReqToPromise(experimentsStore.put(expRec));
        }

        // Ler estado completo de objetos e experimentos do projeto dentro da transação
        const allObjects = (await idbReqToPromise(
          objectsStore.index("by_project").getAll(input.project_id),
        )) as StoredObjectRecord[];
        allObjects.sort((a, b) =>
          a.object_id === b.object_id
            ? a.revision - b.revision
            : a.object_id.localeCompare(b.object_id),
        );

        const allExperiments = (await idbReqToPromise(
          experimentsStore.index("by_project").getAll(input.project_id),
        )) as StoredExperimentRecord[];
        allExperiments.sort((a, b) => a.project_revision - b.project_revision);

        // Construir refs mais recentes por object_id
        const latestByObj = new Map<string, number>();
        for (const obj of allObjects) {
          const prev = latestByObj.get(obj.object_id);
          if (prev === undefined || obj.revision > prev) {
            latestByObj.set(obj.object_id, obj.revision);
          }
        }
        const activeObjectRefs = Array.from(latestByObj.entries()).map(
          ([object_id, revision]) => ({ object_id, revision }),
        );

        const effectiveResult =
          validatedResult ?? existingProj?.last_committed_result ?? null;
        const effectiveRequestId =
          input.request_id ??
          validatedResult?.request_id ??
          existingProj?.last_request_id ??
          null;

        const projectRecord: StoredProjectRecord = {
          project_id: input.project_id,
          committed_revision: input.project_revision,
          last_request_id: effectiveRequestId,
          last_committed_result: effectiveResult,
          active_object_refs: activeObjectRefs,
          updated_at: now,
          metadata:
            input.metadata !== undefined
              ? ensureFiniteJson(input.metadata, "$.metadata")
              : existingProj?.metadata,
        };
        await idbReqToPromise(projectsStore.put(projectRecord));

        const snapshotPayloadForHash = {
          project_id: input.project_id,
          project_revision: input.project_revision,
          objects: allObjects,
          experiments: allExperiments,
          committed_result: effectiveResult,
        };

        const snapshot: StoredProjectSnapshot = {
          snapshot_key: makeSnapshotKey(
            input.project_id,
            input.project_revision,
          ),
          schema_version: "1.0.0",
          project_id: input.project_id,
          project_revision: input.project_revision,
          confirmed: true,
          objects: allObjects,
          experiments: allExperiments,
          committed_result: effectiveResult,
          pinned: input.pinned ?? true,
          content_hash: computeCanonicalSha256(snapshotPayloadForHash),
          created_at: now,
        };
        await idbReqToPromise(snapshotsStore.put(snapshot));

        return {
          committed: true,
          project: projectRecord,
          snapshot,
        };
      },
    );
  }

  public async getSnapshot(
    projectId: string,
    revision: number,
  ): Promise<StoredProjectSnapshot | null> {
    return this.runTransaction(["snapshots"], "readonly", async (tx) => {
      const raw = await idbReqToPromise(
        tx.objectStore("snapshots").get(makeSnapshotKey(projectId, revision)),
      );
      return (raw as StoredProjectSnapshot | undefined) ?? null;
    });
  }

  public async getLatestConfirmedSnapshot(
    projectId: string,
  ): Promise<StoredProjectSnapshot | null> {
    return this.runTransaction(["snapshots"], "readonly", async (tx) => {
      const rows = (await idbReqToPromise(
        tx.objectStore("snapshots").index("by_project").getAll(projectId),
      )) as StoredProjectSnapshot[];
      let best: StoredProjectSnapshot | null = null;
      for (const snap of rows) {
        if (!snap.confirmed) continue;
        if (best === null || snap.project_revision > best.project_revision) {
          best = snap;
        }
      }
      return best;
    });
  }

  public async getAllLatestConfirmedSnapshots(): Promise<
    StoredProjectSnapshot[]
  > {
    return this.runTransaction(["snapshots"], "readonly", async (tx) => {
      const rows = (await idbReqToPromise(
        tx.objectStore("snapshots").getAll(),
      )) as StoredProjectSnapshot[];
      const bestByProject = new Map<string, StoredProjectSnapshot>();
      for (const snap of rows) {
        if (!snap.confirmed) continue;
        const prev = bestByProject.get(snap.project_id);
        if (!prev || snap.project_revision > prev.project_revision) {
          bestByProject.set(snap.project_id, snap);
        }
      }
      return Array.from(bestByProject.values()).sort((a, b) =>
        a.project_id.localeCompare(b.project_id),
      );
    });
  }

  public async exportPortableSnapshot(
    projectId: string,
  ): Promise<PortableProjectSnapshot> {
    const snap = await this.getLatestConfirmedSnapshot(projectId);
    if (snap) {
      return {
        format: "controllab_snapshot",
        schema_version: "1.0.0",
        project_id: snap.project_id,
        project_revision: snap.project_revision,
        objects: snap.objects,
        experiments: snap.experiments,
        committed_result: snap.committed_result,
        content_hash: computeCanonicalSha256({
          project_id: snap.project_id,
          project_revision: snap.project_revision,
          objects: snap.objects,
          experiments: snap.experiments,
          committed_result: snap.committed_result,
        }),
        exported_at: new Date().toISOString(),
      };
    }

    const project = await this.getProject(projectId);
    const objects = await this.listObjects(projectId);
    const experiments = await this.listExperiments(projectId);
    const rev = project?.committed_revision ?? 0;
    const committedResult = project?.last_committed_result ?? null;
    return {
      format: "controllab_snapshot",
      schema_version: "1.0.0",
      project_id: projectId,
      project_revision: rev,
      objects,
      experiments,
      committed_result: committedResult,
      content_hash: computeCanonicalSha256({
        project_id: projectId,
        project_revision: rev,
        objects,
        experiments,
        committed_result: committedResult,
      }),
      exported_at: new Date().toISOString(),
    };
  }

  public async importPortableSnapshot(
    rawSnapshot: unknown,
  ): Promise<CommitProjectRevisionOutput> {
    if (!isPlainObject(rawSnapshot)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Snapshot portátil deve ser um objeto JSON.",
      );
    }
    const clean = ensureFiniteJson(rawSnapshot, "$.snapshot");
    if (clean.format !== "controllab_snapshot") {
      throw new ControlLabBridgeError(
        "SCHEMA_UNSUPPORTED",
        `Formato de snapshot não suportado: ${String(clean.format)}`,
      );
    }
    if (
      typeof clean.schema_version !== "string" ||
      !/^1\.0\.\d+$/.test(clean.schema_version)
    ) {
      throw new ControlLabBridgeError(
        "SCHEMA_UNSUPPORTED",
        `schema_version não suportada no snapshot: ${String(clean.schema_version)}`,
      );
    }
    const project_id = clean.project_id;
    const project_revision = clean.project_revision;
    if (typeof project_id !== "string" || project_id.length === 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Snapshot.project_id inválido.",
      );
    }
    if (typeof project_revision !== "number" || !Number.isInteger(project_revision) || project_revision < 0) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Snapshot.project_revision inválido.",
      );
    }
    if (!Array.isArray(clean.objects) || !Array.isArray(clean.experiments)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        "Snapshot deve conter arrays 'objects' e 'experiments'.",
      );
    }

    const objects = clean.objects as StoredObjectRecord[];
    const experiments = clean.experiments as StoredExperimentRecord[];
    const committedResult =
      clean.committed_result === null || clean.committed_result === undefined
        ? null
        : validateRpcResponse(clean.committed_result);

    if (typeof clean.content_hash === "string") {
      const expectedHash = computeCanonicalSha256({
        project_id,
        project_revision,
        objects,
        experiments,
        committed_result: committedResult,
      });
      if (clean.content_hash.toLowerCase() !== expectedHash) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Integridade de snapshot comprometida: content_hash SHA-256 divergente.",
          {
            parameters: {
              expected: expectedHash,
              actual: clean.content_hash,
            },
          },
        );
      }
    }

    const res = await this.commitProjectRevision({
      project_id,
      project_revision,
      committed_result: committedResult,
      objects: objects.map((o) => ({
        object_id: o.object_id,
        revision: o.revision,
        kind: o.kind,
        value: o.value,
      })),
    });

    if (experiments.length > 0) {
      await this.runTransaction(["experiments"], "readwrite", async (tx) => {
        const expStore = tx.objectStore("experiments");
        for (const exp of experiments) {
          const validResp = validateRpcResponse(exp.response);
          await idbReqToPromise(
            expStore.put({
              ...exp,
              response: validResp,
            }),
          );
        }
      });
    }

    return res;
  }
}
