import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  validateRpcRequest,
  validateRpcResponse,
  type RpcRequest,
} from "../../../web/bridge/protocol.ts";
import {
  checkWorkerNetworkPolicy,
  PyodideWorkerRuntime,
  type PyodideLoaderFn,
} from "../../../web/worker/pyodide_worker.ts";
import type { PyProxyLike } from "../../../web/worker/pyproxy_guard.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONTRACTS = path.resolve(HERE, "../../../contracts");
const readJson = (p: string) => JSON.parse(fs.readFileSync(p, "utf8"));

// ---- BUG-2: allowlist ------------------------------------------------------

test("F7-SEC-ALLOWLIST: http: externo é recusado, localhost http permitido", () => {
  const o = "https://controllab.local";
  const allow = new Set([o, "http://evil.example", "http://localhost:8080"]);
  const ext = checkWorkerNetworkPolicy("http://evil.example/x.js", o, allow, true);
  assert.equal(ext.allowed, false);
  const loc = checkWorkerNetworkPolicy("http://localhost:8080/x.js", o, allow, true);
  assert.equal(loc.allowed, true);
});

test("F7-SEC-ALLOWLIST: config.allowedOrigins na mensagem init não amplia a allowlist", async () => {
  const messages: unknown[] = [];
  let loaderCalled = false;
  const pyodideLoader: PyodideLoaderFn = async () => {
    loaderCalled = true;
    throw new Error("loader não deveria ser chamado");
  };
  const rt = new PyodideWorkerRuntime({
    pyodideLoader,
    postMessage: (m) => messages.push(m),
  });
  await rt.handleMessage({
    kind: "init",
    msg_id: "m1",
    config: {
      indexURL: "https://cdn.evil.example/pyodide/",
      allowedOrigins: ["https://cdn.evil.example"],
    },
  } as never);
  assert.equal(loaderCalled, false);
  assert.ok(JSON.stringify(messages).includes("init_error"));
  assert.ok(JSON.stringify(messages).includes("IMPORT_UNTRUSTED_CODE"));
});

// ---- BUG-1: entrypoint -----------------------------------------------------

async function runWith(
  pyodide: Record<string, unknown>,
): Promise<{ status: string; code?: string }> {
  const messages: any[] = [];
  const rt = new PyodideWorkerRuntime({
    pyodideLoader: async () => ({
      pyodide: { runPythonAsync: async () => null, ...pyodide } as never,
      libVersions: {},
    }),
    postMessage: (m) => messages.push(m),
  });
  await rt.handleMessage({ kind: "init", msg_id: "m0", config: {} } as never);
  const req = readJson(
    path.join(CONTRACTS, "examples", "rpc_request_lqr.json"),
  ) as RpcRequest;
  await rt.handleMessage({ kind: "rpc_request", request: req } as never);
  const r = messages.find((m) => m.kind === "rpc_response");
  assert.ok(r, "sem rpc_response");
  return { status: r.response.status, code: r.response.error?.code };
}

test("F7-ENTRYPOINT: sem toPy retorna erro estruturado e nunca chama runPythonAsync", async () => {
  let ran = 0;
  const out = await runWith({
    runPythonAsync: async () => {
      ran += 1;
      return null;
    },
  });
  assert.equal(out.status, "failure");
  assert.equal(out.code, "SOLVER_UNAVAILABLE");
  assert.equal(ran, 0);
});

test("F7-ENTRYPOINT: sem pyimport retorna erro estruturado sem executar código", async () => {
  let ran = 0;
  const proxy: PyProxyLike = { __isPyProxy: true, toJs: () => ({}), destroy: () => undefined };
  const out = await runWith({
    toPy: () => proxy,
    runPythonAsync: async () => {
      ran += 1;
      return null;
    },
  });
  assert.equal(out.code, "SOLVER_UNAVAILABLE");
  assert.equal(ran, 0);
});

// ---- OBS-3: conformidade com os schemas ------------------------------------

test("F7-SCHEMA: protocol.ts aceita exemplos e rejeita violações dos schemas rpc_*", () => {
  const reqSchema = readJson(path.join(CONTRACTS, "schemas", "rpc_request.schema.json"));
  const resSchema = readJson(path.join(CONTRACTS, "schemas", "rpc_response.schema.json"));
  const req = readJson(path.join(CONTRACTS, "examples", "rpc_request_lqr.json"));
  const res = readJson(path.join(CONTRACTS, "examples", "rpc_response_lqr.json"));
  assert.doesNotThrow(() => validateRpcRequest(req));
  assert.doesNotThrow(() => validateRpcResponse(res));

  for (const [schema, ex, validate] of [
    [reqSchema, req, validateRpcRequest],
    [resSchema, res, validateRpcResponse],
  ] as const) {
    assert.equal(schema.additionalProperties, false);
    for (const key of schema.required as string[]) {
      const copy = { ...ex };
      delete copy[key];
      assert.throws(() => validate(copy), `campo obrigatório '${key}' deveria ser exigido`);
    }
    assert.throws(() => validate({ ...ex, campo_extra: 1 }));
    assert.throws(() => validate({ ...ex, api_version: "2.0" }));
  }
});
