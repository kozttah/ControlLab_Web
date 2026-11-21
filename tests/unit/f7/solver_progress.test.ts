import test from "node:test";
import assert from "node:assert/strict";

import type { SolverProgressEvent } from "../../../web/bridge/client.ts";
import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import { RPC_API_VERSION, type RpcRequest, type RpcResponse } from "../../../web/bridge/protocol.ts";
import { PyodideEngineClient } from "../../../web/bridge/pyodide_client.ts";
import { InMemoryIDBFactory } from "../../../web/storage/indexeddb_store.ts";
import {
  createMessageChannelWorkerTransport,
  type PyodideLoaderFn,
} from "../../../web/worker/pyodide_worker.ts";
import type { PyProxyLike } from "../../../web/worker/pyproxy_guard.ts";

test("F7-PROGRESS-01: PyodideEngineClient forwards worker progress messages to subscribeProgress without interfering with RpcResponse", async () => {
  const globalsMap = new Map<string, unknown>();
  let callbackInstalled = false;
  let callbackCleared = false;

  const progressLoader: PyodideLoaderFn = async () => ({
    pyodide: {
      version: "test-progress-double",
      globals: {
        get: (name: string) => globalsMap.get(name),
        set: (name: string, value: unknown) => {
          globalsMap.set(name, value);
        },
        delete: (name: string) => {
          globalsMap.delete(name);
        },
      },
      runPythonAsync: async (code: string) => {
        if (code.includes("set_progress_callback")) {
          callbackInstalled = true;
        }
        if (code.includes("clear_progress_callback")) {
          callbackCleared = true;
        }
        return undefined;
      },
      toPy: (input: unknown): PyProxyLike => ({
        __isPyProxy: true,
        toJs: () => input,
        destroy() {},
      }),
      pyimport: (name: string) => {
        if (name !== "control_lab.core.rpc") {
          throw new Error(`Unexpected module: ${name}`);
        }
        return {
          dispatch: (proxy: PyProxyLike): RpcResponse => {
            const { request } = proxy.toJs?.() as { request: RpcRequest };
            if (request.operation === "core.capabilities") {
              return {
                api_version: RPC_API_VERSION,
                request_id: request.request_id,
                project_id: request.project_id,
                project_revision: request.project_revision,
                status: "success",
                result: {
                  supported_operations: ["core.capabilities", "optimization.solve"],
                },
                assumptions: {},
                diagnostics: {},
                provenance: { algorithm: "core.capabilities", lib_versions: {} },
                warnings: [],
                error: null,
              };
            }

            const emitFn = globalsMap.get("__controllab_emit_progress") as
              | ((rawJson: string) => void)
              | undefined;
            assert.equal(typeof emitFn, "function");
            emitFn!(
              JSON.stringify({
                iter: 1,
                max_iters: 80,
                gap: 1.25e-2,
                primal_res: 3.4e-4,
                dual_res: 5.6e-4,
                min_eig: 0.12,
                alpha: 0.98,
                elapsed_ms: 4.5,
              }),
            );
            emitFn!(
              JSON.stringify({
                iter: 2,
                max_iters: 80,
                gap: 1.0e-9,
                primal_res: 1.0e-11,
                dual_res: 1.0e-11,
                min_eig: 0.45,
                alpha: 1.0,
                elapsed_ms: 9.2,
              }),
            );

            return {
              api_version: RPC_API_VERSION,
              request_id: request.request_id,
              project_id: request.project_id,
              project_revision: request.project_revision,
              status: "success",
              result: {
                status: "optimal",
                objective_value: 2.5,
              },
              assumptions: {},
              diagnostics: { certificate_status: "validated_dual" },
              provenance: { algorithm: "optimization.solve", lib_versions: {} },
              warnings: [],
              error: null,
            };
          },
          destroy() {},
        };
      },
    },
    libVersions: { numpy: "2.4.6" },
  });

  const client = new PyodideEngineClient({
    storeOptions: { idbFactory: new InMemoryIDBFactory(), dbName: "progress_test_1" },
    workerFactory: () =>
      createMessageChannelWorkerTransport({ pyodideLoader: progressLoader }),
  });

  const received: SolverProgressEvent[] = [];
  const unsubscribe = client.subscribeProgress((ev) => {
    received.push(ev);
  });

  try {
    await client.init();
    const resp = await client.execute({
      api_version: RPC_API_VERSION,
      request_id: "opt-prog-1",
      project_id: "proj-prog",
      project_revision: 1,
      operation: "optimization.solve",
      payload: { template: "lqr_lmi" },
      options: {},
      timeout_policy: { hard_timeout_ms: 5000 },
    });

    assert.equal(resp.status, "success");
    assert.equal(resp.request_id, "opt-prog-1");
    assert.equal(resp.result?.status, "optimal");
    assert.equal(callbackInstalled, true);
    assert.equal(callbackCleared, true);
    assert.equal(globalsMap.has("__controllab_emit_progress"), false);

    assert.equal(received.length, 2);
    assert.equal(received[0].request_id, "opt-prog-1");
    assert.equal(received[0].progress.iter, 1);
    assert.equal(received[0].progress.max_iters, 80);
    assert.equal(received[1].progress.iter, 2);
    assert.equal(received[1].progress.gap, 1.0e-9);

    const stats = await client.getWorkerStats();
    assert.equal(stats.pyproxy.activeProxies, 0);

    // Unsubscribe stops further events
    unsubscribe();
    await client.execute({
      api_version: RPC_API_VERSION,
      request_id: "opt-prog-2",
      project_id: "proj-prog",
      project_revision: 2,
      operation: "optimization.solve",
      payload: { template: "lqr_lmi" },
      options: {},
      timeout_policy: { hard_timeout_ms: 5000 },
    });
    assert.equal(received.length, 2);
  } finally {
    client.dispose();
  }
});

test("F7-PROGRESS-02: MockWorkerAdapter exposes subscribeProgress cleanly", async () => {
  const mock = new MockWorkerAdapter({
    storeOptions: { idbFactory: new InMemoryIDBFactory(), dbName: "progress_mock_test" },
  });
  const events: SolverProgressEvent[] = [];
  const unsub = mock.subscribeProgress((ev) => events.push(ev));
  try {
    await mock.init();
    const resp = await mock.execute({
      api_version: RPC_API_VERSION,
      request_id: "mock-prog-1",
      project_id: "proj-mock",
      project_revision: 1,
      operation: "worker.ping",
      payload: {},
      options: {},
      timeout_policy: { hard_timeout_ms: 5000 },
    });
    assert.equal(resp.status, "success");
    assert.equal(events.length, 0);
  } finally {
    unsub();
    mock.dispose();
  }
});
