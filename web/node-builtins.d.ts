// Minimal ambient declarations for Node built-in modules used by Node 24 unit tests
// in offline environments without @types/node. Keep runtime browser directories free
// of Node-only globals (process, Buffer).

declare module "node:test" {
  export interface TestContext {
    readonly name: string;
    skip(message?: string): void;
    todo(message?: string): void;
    test(name: string, fn: (t: TestContext) => void | Promise<void>): Promise<void>;
    test(name: string, options: TestOptions, fn: (t: TestContext) => void | Promise<void>): Promise<void>;
  }

  export type TestFn = (t: TestContext) => void | Promise<void>;

  export interface TestOptions {
    skip?: boolean | string;
    todo?: boolean | string;
    only?: boolean;
    timeout?: number;
    concurrency?: number | boolean;
  }

  export function test(name: string, fn: TestFn): Promise<void>;
  export function test(name: string, options: TestOptions, fn: TestFn): Promise<void>;
  export function describe(name: string, fn: () => void | Promise<void>): Promise<void>;
  export function describe(name: string, options: TestOptions, fn: () => void | Promise<void>): Promise<void>;
  export function suite(name: string, fn: () => void | Promise<void>): Promise<void>;
  export function suite(name: string, options: TestOptions, fn: () => void | Promise<void>): Promise<void>;
  export function it(name: string, fn: TestFn): Promise<void>;
  export function it(name: string, options: TestOptions, fn: TestFn): Promise<void>;
  export function before(fn: () => void | Promise<void>): void;
  export function after(fn: () => void | Promise<void>): void;
  export function beforeEach(fn: () => void | Promise<void>): void;
  export function afterEach(fn: () => void | Promise<void>): void;
  export default test;
}

declare module "node:assert/strict" {
  export function ok(value: unknown, message?: string | Error): asserts value;
  export function equal<T>(actual: unknown, expected: T, message?: string | Error): asserts actual is T;
  export function notEqual(actual: unknown, expected: unknown, message?: string | Error): void;
  export function strictEqual<T>(actual: unknown, expected: T, message?: string | Error): asserts actual is T;
  export function notStrictEqual(actual: unknown, expected: unknown, message?: string | Error): void;
  export function deepEqual(actual: unknown, expected: unknown, message?: string | Error): void;
  export function deepStrictEqual(actual: unknown, expected: unknown, message?: string | Error): void;
  export function notDeepStrictEqual(actual: unknown, expected: unknown, message?: string | Error): void;
  export function throws(fn: () => unknown, error?: unknown, message?: string | Error): void;
  export function rejects(
    block: (() => Promise<unknown>) | Promise<unknown>,
    error?: unknown,
    message?: string | Error,
  ): Promise<void>;
  export function doesNotThrow(fn: () => unknown, message?: string | Error): void;
  export function doesNotReject(
    block: (() => Promise<unknown>) | Promise<unknown>,
    message?: string | Error,
  ): Promise<void>;
  export function match(value: string, regexp: RegExp, message?: string | Error): void;
  export function doesNotMatch(value: string, regexp: RegExp, message?: string | Error): void;
  export function fail(message?: string | Error): never;

  const assertStrict: {
    ok: typeof ok;
    equal: typeof equal;
    notEqual: typeof notEqual;
    strictEqual: typeof strictEqual;
    notStrictEqual: typeof notStrictEqual;
    deepEqual: typeof deepEqual;
    deepStrictEqual: typeof deepStrictEqual;
    notDeepStrictEqual: typeof notDeepStrictEqual;
    throws: typeof throws;
    rejects: typeof rejects;
    doesNotThrow: typeof doesNotThrow;
    doesNotReject: typeof doesNotReject;
    match: typeof match;
    doesNotMatch: typeof doesNotMatch;
    fail: typeof fail;
  };
  export default assertStrict;
}

declare module "node:assert" {
  export * from "node:assert/strict";
  import assertStrict from "node:assert/strict";
  export default assertStrict;
}

declare module "node:path" {
  export function resolve(...paths: string[]): string;
  export function join(...paths: string[]): string;
  export function dirname(p: string): string;
  export function basename(p: string, ext?: string): string;
  export function extname(p: string): string;
  export function relative(from: string, to: string): string;
  export function isAbsolute(p: string): boolean;
  export function normalize(p: string): string;
  export const sep: string;
  export const posix: {
    resolve(...paths: string[]): string;
    join(...paths: string[]): string;
    dirname(p: string): string;
    basename(p: string, ext?: string): string;
    extname(p: string): string;
    relative(from: string, to: string): string;
    sep: string;
  };

  const pathObj: {
    resolve: typeof resolve;
    join: typeof join;
    dirname: typeof dirname;
    basename: typeof basename;
    extname: typeof extname;
    relative: typeof relative;
    isAbsolute: typeof isAbsolute;
    normalize: typeof normalize;
    sep: string;
    posix: typeof posix;
  };
  export default pathObj;
}

declare module "node:url" {
  export function fileURLToPath(url: string | URL): string;
  export function pathToFileURL(path: string): URL;
}

declare module "node:fs" {
  export interface Dirent {
    readonly name: string;
    isFile(): boolean;
    isDirectory(): boolean;
    isSymbolicLink(): boolean;
  }
  export function existsSync(path: string): boolean;
  export function readFileSync(path: string, encoding: "utf8" | "utf-8"): string;
  export function readFileSync(path: string): Uint8Array;
  export function writeFileSync(path: string, data: string | Uint8Array): void;
  export function mkdirSync(path: string, options?: { recursive?: boolean }): string | undefined;
  export function readdirSync(path: string): string[];
  export function readdirSync(path: string, options: { withFileTypes: true }): Dirent[];
  export function statSync(path: string): { isFile(): boolean; isDirectory(): boolean; size: number };

  const fsObj: {
    existsSync: typeof existsSync;
    readFileSync: typeof readFileSync;
    writeFileSync: typeof writeFileSync;
    mkdirSync: typeof mkdirSync;
    readdirSync: typeof readdirSync;
    statSync: typeof statSync;
  };
  export default fsObj;
}

declare module "node:fs/promises" {
  import type { Dirent } from "node:fs";
  export function readFile(path: string, encoding: "utf8" | "utf-8"): Promise<string>;
  export function readFile(path: string): Promise<Uint8Array>;
  export function writeFile(path: string, data: string | Uint8Array): Promise<void>;
  export function mkdir(path: string, options?: { recursive?: boolean }): Promise<string | undefined>;
  export function readdir(path: string): Promise<string[]>;
  export function readdir(path: string, options: { withFileTypes: true }): Promise<Dirent[]>;
  export function stat(path: string): Promise<{ isFile(): boolean; isDirectory(): boolean; size: number }>;
  export function rm(path: string, options?: { recursive?: boolean; force?: boolean }): Promise<void>;
}

declare module "node:crypto" {
  export interface Hash {
    update(data: string | Uint8Array): Hash;
    digest(encoding: "hex" | "base64"): string;
    digest(): Uint8Array;
  }
  export function createHash(algorithm: string): Hash;
  export function randomUUID(): string;
}
