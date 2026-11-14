/** Explicit fixture-backed TEST DOUBLE for transport/lifecycle tests.
 * It does not execute Python and is never scientific/Wasm parity evidence.
 * Numerical references are read unchanged from F9's hash-checked gold fixture.
 */
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { sha256Hex, type RpcRequest, type RpcResponse } from "../../../web/bridge/protocol.ts";
import type { PyodideLoaderFn } from "../../../web/worker/pyodide_worker.ts";
import type { PyProxyLike } from "../../../web/worker/pyproxy_guard.ts";

const root = new URL("../../../", import.meta.url);
const raw = fs.readFileSync(fileURLToPath(new URL("contracts/fixtures/B-CARE-02.json", root)), "utf8");
const checksums = fs.readFileSync(fileURLToPath(new URL("contracts/fixtures/checksums.sha256", root)), "utf8");
const digest = checksums.split(/\r?\n/).find((line) => line.endsWith("B-CARE-02.json"))?.split(/\s+/)[0];
if (sha256Hex(raw) !== digest) throw new Error("F9 fixture integrity failure");
const fixture = JSON.parse(raw);

export function makeFixturePyodideLoader(hooks?: {
  created?: () => void;
  destroyed?: () => void;
  beforeDispatch?: (request: RpcRequest) => void;
}): PyodideLoaderFn {
  return async () => ({
    pyodide: {
      version: "test-double-no-wasm",
      runPythonAsync: async () => { throw new Error("Test double does not execute Python strings"); },
      toPy: (input: unknown): PyProxyLike => {
        hooks?.created?.();
        let destroyed = false;
        return { __isPyProxy: true, toJs: () => input, destroy: () => {
          if (!destroyed) { destroyed = true; hooks?.destroyed?.(); }
        } };
      },
      pyimport: (name) => {
        if (name !== "control_lab.core.rpc") throw new Error(`Unexpected module: ${name}`);
        return { dispatch: (proxy: PyProxyLike): RpcResponse => {
          const { request } = proxy.toJs?.() as { request: RpcRequest };
          hooks?.beforeDispatch?.(request);
          return {
            api_version: "1.0", request_id: request.request_id, project_id: request.project_id,
            project_revision: request.project_revision, status: "success",
            result: request.operation === "core.capabilities" ? {
              supported_operations: ["core.capabilities", "statespace.design_lqr"],
            } : {
              ...structuredClone(fixture.data.expected),
              controller_kind: "StateFeedbackController", feedback_sign: fixture.data.feedback_sign,
            },
            assumptions: {}, diagnostics: { test_double: true },
            provenance: { algorithm: "fixture_transport_test_double", lib_versions: { test_double: "1" } },
            warnings: [], error: null,
          };
        } };
      },
    },
    libVersions: { test_double: "1" }, downloadMs: 2, initMs: 3, importMs: 4,
  });
}

export const fixturePyodideLoader = makeFixturePyodideLoader();
