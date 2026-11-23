import test from "node:test";
import assert from "node:assert/strict";

import { MockWorkerAdapter } from "../../../web/bridge/mock_adapter.ts";
import {
  ControlLabBridgeError,
  ensureFiniteJson,
  extractTensorsToBinaryBuffers,
  RPC_API_VERSION,
  validateRpcRequest,
  type BufferTensorRef,
  type PackedSparseCooPayload,
  type RealTensor,
  type RpcRequest,
  type RpcResponse,
} from "../../../web/bridge/protocol.ts";
import { PyodideEngineClient } from "../../../web/bridge/pyodide_client.ts";
import { InMemoryIDBFactory } from "../../../web/storage/indexeddb_store.ts";
import {
  createMessageChannelWorkerTransport,
  PyodideWorkerRuntime,
  type PyodideLoaderFn,
  type WorkerInboundMessage,
  type WorkerOutboundMessage,
} from "../../../web/worker/pyodide_worker.ts";
import type { PyProxyLike } from "../../../web/worker/pyproxy_guard.ts";

function makePackedSdpRequest(
  requestId: string,
  revision: number,
  packed: PackedSparseCooPayload,
  extraPayload?: Record<string, unknown>,
): RpcRequest {
  return {
    api_version: RPC_API_VERSION,
    request_id: requestId,
    project_id: "proj-packed-sdp",
    project_revision: revision,
    operation: "optimization.solve",
    payload: {
      problem: {
        name: "packed_sparse_test",
        c: [1.0, 0.5],
        blocks: [
          {
            name: "blk_0",
            F0: {
              shape: [2, 2],
              dtype: "float64",
              order: "C",
              data: [1.0, 0.0, 0.0, 1.0],
            },
            n_vars: 2,
            F_k_packed: packed,
          },
        ],
      },
      ...extraPayload,
    },
    options: {},
    timeout_policy: { hard_timeout_ms: 5000 },
  };
}

test("F7-PACKED-01: extractTensorsToBinaryBuffers extracts F_k_packed TypedArrays zero-copy and rejects NaN/Inf", () => {
  const kIdx = new Int32Array([0, 0, 1]);
  const rows = new Int32Array([0, 1, 1]);
  const cols = new Int32Array([0, 0, 1]);
  const vals = new Float64Array([-1.5, 0.25, -2.0]);

  const payload = {
    problem: {
      blocks: [
        {
          name: "blk_0",
          F0: { shape: [2, 2], dtype: "float64", order: "C", data: [1, 0, 0, 1] },
          F_k_packed: {
            k_idx: kIdx,
            rows,
            cols,
            vals,
          },
        },
      ],
    },
  };

  // ensureFiniteJson accepts Int32Array/Float64Array inside F_k_packed without copying to JS arrays
  const sanitized = ensureFiniteJson(payload, "$.payload");
  const sanitizedBlock = (
    (sanitized.problem as Record<string, unknown>).blocks as Array<Record<string, unknown>>
  )[0];
  const sanitizedPacked = sanitizedBlock.F_k_packed as PackedSparseCooPayload;
  assert.equal(sanitizedPacked.k_idx, kIdx);
  assert.equal(sanitizedPacked.rows, rows);
  assert.equal(sanitizedPacked.cols, cols);
  assert.equal(sanitizedPacked.vals, vals);

  // Extract with packedSparseOnly=false (also extracts dense F0 for backward compatibility)
  const extracted = extractTensorsToBinaryBuffers(payload, "req-1");
  const outBlock = (
    (extracted.replaced.problem as Record<string, unknown>).blocks as Array<Record<string, unknown>>
  )[0];
  const outF0 = outBlock.F0 as BufferTensorRef;
  const outPacked = outBlock.F_k_packed as Record<string, BufferTensorRef>;

  // Dense F0 remains backward-compatible (not marked packed_sparse)
  assert.equal(typeof outF0.buffer_ref, "string");
  assert.deepEqual(outF0.shape, [2, 2]);
  assert.equal(extracted.buffers[outF0.buffer_ref].packed_sparse, undefined);

  // Packed fields become canonical BufferTensorRefs backed by the exact original ArrayBuffers (zero copy)
  assert.deepEqual(outPacked.k_idx.shape, [3]);
  assert.equal(outPacked.k_idx.dtype, "int32");
  assert.equal(outPacked.k_idx.order, "C");
  assert.equal(extracted.buffers[outPacked.k_idx.buffer_ref].buffer, kIdx.buffer);
  assert.equal(extracted.buffers[outPacked.k_idx.buffer_ref].packed_sparse, true);

  assert.equal(extracted.buffers[outPacked.rows.buffer_ref].buffer, rows.buffer);
  assert.equal(extracted.buffers[outPacked.cols.buffer_ref].buffer, cols.buffer);

  assert.deepEqual(outPacked.vals.shape, [3]);
  assert.equal(outPacked.vals.dtype, "float64");
  assert.equal(extracted.buffers[outPacked.vals.buffer_ref].buffer, vals.buffer);
  assert.equal(extracted.buffers[outPacked.vals.buffer_ref].packed_sparse, true);

  assert.ok(extracted.transferList.includes(kIdx.buffer));
  assert.ok(extracted.transferList.includes(rows.buffer));
  assert.ok(extracted.transferList.includes(cols.buffer));
  assert.ok(extracted.transferList.includes(vals.buffer));

  // Subarray view with non-zero byteOffset slices cleanly instead of transferring whole slab
  const slab = new ArrayBuffer(64);
  const subK = new Int32Array(slab, 0, 2);
  subK.set([0, 1]);
  const subR = new Int32Array(slab, 8, 2);
  subR.set([1, 0]);
  const subC = new Int32Array(slab, 16, 2);
  subC.set([0, 1]);
  const subV = new Float64Array(slab, 32, 2);
  subV.set([3.25, -4.5]);

  const extractedSub = extractTensorsToBinaryBuffers(
    { F_k_packed: { k_idx: subK, rows: subR, cols: subC, vals: subV } },
    "sub",
    { packedSparseOnly: true },
  );
  const subPackedRefs = extractedSub.replaced.F_k_packed as Record<string, BufferTensorRef>;
  assert.notEqual(extractedSub.buffers[subPackedRefs.k_idx.buffer_ref].buffer, slab);
  assert.equal(extractedSub.buffers[subPackedRefs.k_idx.buffer_ref].byte_length, 8);
  assert.deepEqual(
    Array.from(new Int32Array(extractedSub.buffers[subPackedRefs.k_idx.buffer_ref].buffer)),
    [0, 1],
  );
  assert.deepEqual(
    Array.from(new Float64Array(extractedSub.buffers[subPackedRefs.vals.buffer_ref].buffer)),
    [3.25, -4.5],
  );

  // TensorDescriptor inside F_k_packed is also extracted as packed_sparse
  const extractedTd = extractTensorsToBinaryBuffers(
    {
      F_k_packed: {
        k_idx: { shape: [2], dtype: "int32", order: "C", data: [0, 1] },
        rows: { shape: [2], dtype: "int32", order: "C", data: [0, 1] },
        cols: { shape: [2], dtype: "int32", order: "C", data: [0, 1] },
        vals: { shape: [2], dtype: "float64", order: "C", data: [2.0, -3.0] },
      },
    },
    "td",
    { packedSparseOnly: true },
  );
  const tdRefs = extractedTd.replaced.F_k_packed as Record<string, BufferTensorRef>;
  assert.equal(extractedTd.buffers[tdRefs.vals.buffer_ref].packed_sparse, true);
  assert.deepEqual(
    Array.from(new Float64Array(extractedTd.buffers[tdRefs.vals.buffer_ref].buffer)),
    [2.0, -3.0],
  );

  // Empty packed arrays (nnz = 0) succeed cleanly
  const emptyExtracted = extractTensorsToBinaryBuffers(
    {
      F_k_packed: {
        k_idx: new Int32Array(0),
        rows: new Int32Array(0),
        cols: new Int32Array(0),
        vals: new Float64Array(0),
      },
    },
    "empty",
    { packedSparseOnly: true },
  );
  assert.equal(Object.keys(emptyExtracted.buffers).length, 4);

  // Rejects NaN and +/-Infinity in vals
  for (const badVal of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
    assert.throws(
      () =>
        extractTensorsToBinaryBuffers(
          {
            F_k_packed: {
              k_idx: new Int32Array([0]),
              rows: new Int32Array([0]),
              cols: new Int32Array([0]),
              vals: new Float64Array([badVal]),
            },
          },
          "bad",
        ),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
    );
    assert.throws(
      () =>
        ensureFiniteJson(
          {
            F_k_packed: {
              k_idx: new Int32Array([0]),
              rows: new Int32Array([0]),
              cols: new Int32Array([0]),
              vals: new Float64Array([badVal]),
            },
          },
          "$.payload",
        ),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
    );
  }

  // Raw TypedArrays outside F_k_packed remain strictly rejected
  assert.throws(
    () => ensureFiniteJson({ A: new Float64Array([1.0, 2.0]) }, "$.payload"),
    (err: unknown) =>
      err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
  );
});

test("F7-PACKED-02: PyodideWorkerRuntime forwards F_k_packed buffers zero-copy as Uint8Array views while rehydrating regular TensorDescriptor buffers", async () => {
  const capturedToPyEnvelopes: Array<Record<string, unknown>> = [];

  const spyLoader: PyodideLoaderFn = async () => ({
    pyodide: {
      version: "test-packed-worker",
      runPythonAsync: async () => undefined,
      toPy: (input: unknown): PyProxyLike => {
        capturedToPyEnvelopes.push(input as Record<string, unknown>);
        return {
          __isPyProxy: true,
          toJs: () => input,
          destroy() {},
        };
      },
      pyimport: (name: string) => {
        if (name !== "control_lab.core.rpc") {
          throw new Error(`Unexpected module: ${name}`);
        }
        return {
          dispatch: (proxy: PyProxyLike): RpcResponse => {
            const env = proxy.toJs?.() as {
              request: RpcRequest;
              payload: Record<string, unknown>;
              buffers?: Record<string, Uint8Array>;
            };
            if (env.request.operation === "core.capabilities") {
              return {
                api_version: RPC_API_VERSION,
                request_id: env.request.request_id,
                project_id: env.request.project_id,
                project_revision: env.request.project_revision,
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
            return {
              api_version: RPC_API_VERSION,
              request_id: env.request.request_id,
              project_id: env.request.project_id,
              project_revision: env.request.project_revision,
              status: "success",
              result: {
                received_buffer_keys: Object.keys(env.buffers ?? {}).sort(),
              },
              assumptions: {},
              diagnostics: {},
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

  const outbound: WorkerOutboundMessage[] = [];
  const runtime = new PyodideWorkerRuntime({
    pyodideLoader: spyLoader,
    postMessage: (msg) => {
      outbound.push(msg as WorkerOutboundMessage);
    },
  });

  await runtime.handleMessage({ kind: "init", msg_id: "init-1" });
  assert.equal(outbound[0].kind, "init_ok");
  // Capabilities call has no packed buffers -> envelope MUST NOT include `buffers` key
  assert.equal("buffers" in capturedToPyEnvelopes[0], false);

  // Prepare wire message with BOTH F_k_packed BufferTensorRefs AND a regular dense BufferTensorRef
  const kBuf = new Int32Array([0, 1]).buffer;
  const rBuf = new Int32Array([0, 1]).buffer;
  const cBuf = new Int32Array([0, 1]).buffer;
  const vBuf = new Float64Array([-1.25, 2.5]).buffer;
  const qBuf = new Float64Array([1.0, 0.0, 0.0, 1.0]).buffer;

  const inboundMsg: WorkerInboundMessage = {
    kind: "rpc_request",
    request: {
      api_version: RPC_API_VERSION,
      request_id: "req-mixed-1",
      project_id: "proj-packed",
      project_revision: 1,
      operation: "optimization.solve",
      payload: {
        Q: { shape: [2, 2], dtype: "float64", order: "C", buffer_ref: "dense-Q" },
        problem: {
          blocks: [
            {
              name: "b0",
              F_k_packed: {
                k_idx: { shape: [2], dtype: "int32", order: "C", buffer_ref: "pk-k" },
                rows: { shape: [2], dtype: "int32", order: "C", buffer_ref: "pk-r" },
                cols: { shape: [2], dtype: "int32", order: "C", buffer_ref: "pk-c" },
                vals: { shape: [2], dtype: "float64", order: "C", buffer_ref: "pk-v" },
              },
            },
          ],
        },
      },
      options: {},
      timeout_policy: { hard_timeout_ms: 5000 },
    },
    buffers: {
      "dense-Q": {
        buffer_ref: "dense-Q",
        shape: [2, 2],
        dtype: "float64",
        order: "C",
        buffer: qBuf,
        byte_length: qBuf.byteLength,
      },
      "pk-k": {
        buffer_ref: "pk-k",
        shape: [2],
        dtype: "int32",
        order: "C",
        buffer: kBuf,
        byte_length: kBuf.byteLength,
        packed_sparse: true,
      },
      "pk-r": {
        buffer_ref: "pk-r",
        shape: [2],
        dtype: "int32",
        order: "C",
        buffer: rBuf,
        byte_length: rBuf.byteLength,
        packed_sparse: true,
      },
      "pk-c": {
        buffer_ref: "pk-c",
        shape: [2],
        dtype: "int32",
        order: "C",
        buffer: cBuf,
        byte_length: cBuf.byteLength,
        packed_sparse: true,
      },
      "pk-v": {
        buffer_ref: "pk-v",
        shape: [2],
        dtype: "float64",
        order: "C",
        buffer: vBuf,
        byte_length: vBuf.byteLength,
        packed_sparse: true,
      },
    },
  };

  await runtime.handleMessage(inboundMsg);
  const rpcOut = outbound[1];
  assert.equal(rpcOut.kind, "rpc_response");
  if (rpcOut.kind !== "rpc_response") throw new Error("unreachable");
  assert.equal(rpcOut.response.status, "success");

  const env = capturedToPyEnvelopes[1];
  const envPayload = env.payload as Record<string, unknown>;
  const envBuffers = env.buffers as Record<string, Uint8Array>;

  // Regular dense Q was rehydrated into RealTensor (backward-compatible)
  const rehydratedQ = envPayload.Q as RealTensor;
  assert.deepEqual(rehydratedQ, {
    shape: [2, 2],
    dtype: "float64",
    order: "C",
    data: [1.0, 0.0, 0.0, 1.0],
  });
  assert.equal("dense-Q" in envBuffers, false);

  // Packed sparse F_k_packed kept BufferTensorRefs (NOT expanded into JS number[])
  const block0 = (
    (envPayload.problem as Record<string, unknown>).blocks as Array<Record<string, unknown>>
  )[0];
  const fk = block0.F_k_packed as Record<string, BufferTensorRef>;
  assert.deepEqual(fk.k_idx, { shape: [2], dtype: "int32", order: "C", buffer_ref: "pk-k" });
  assert.deepEqual(fk.vals, { shape: [2], dtype: "float64", order: "C", buffer_ref: "pk-v" });

  // Buffers envelope carries zero-copy Uint8Array views backed by the exact ArrayBuffers
  assert.ok(envBuffers["pk-k"] instanceof Uint8Array);
  assert.ok(envBuffers["pk-r"] instanceof Uint8Array);
  assert.ok(envBuffers["pk-c"] instanceof Uint8Array);
  assert.ok(envBuffers["pk-v"] instanceof Uint8Array);
  assert.equal(envBuffers["pk-k"].buffer, kBuf);
  assert.equal(envBuffers["pk-r"].buffer, rBuf);
  assert.equal(envBuffers["pk-c"].buffer, cBuf);
  assert.equal(envBuffers["pk-v"].buffer, vBuf);

  assert.deepEqual(
    Array.from(new Int32Array(envBuffers["pk-k"].buffer)),
    [0, 1],
  );
  assert.deepEqual(
    Array.from(new Float64Array(envBuffers["pk-v"].buffer)),
    [-1.25, 2.5],
  );
  assert.equal(runtime.pyproxyRegistry.activeProxies, 0);
});

test("F7-PACKED-03: PyodideEngineClient round-trip transfers exact ArrayBuffers of k_idx, rows, cols, vals and delivers Uint8Array views to Pyodide", async () => {
  let capturedTransferList: ArrayBuffer[] | undefined;
  let capturedWireMsg: WorkerInboundMessage | undefined;
  let workerReceivedBuffers: Record<string, Uint8Array> | undefined;
  let workerReceivedPacked: Record<string, BufferTensorRef> | undefined;

  const loader: PyodideLoaderFn = async () => ({
    pyodide: {
      version: "test-packed-roundtrip",
      runPythonAsync: async () => undefined,
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
            const env = proxy.toJs?.() as {
              request: RpcRequest;
              payload: Record<string, unknown>;
              buffers?: Record<string, Uint8Array>;
            };
            if (env.request.operation === "core.capabilities") {
              return {
                api_version: RPC_API_VERSION,
                request_id: env.request.request_id,
                project_id: env.request.project_id,
                project_revision: env.request.project_revision,
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
            workerReceivedBuffers = env.buffers;
            const block0 = (
              (env.payload.problem as Record<string, unknown>).blocks as Array<
                Record<string, unknown>
              >
            )[0];
            workerReceivedPacked = block0.F_k_packed as Record<string, BufferTensorRef>;

            const valsRef = workerReceivedPacked.vals.buffer_ref;
            const valsView = new Float64Array(
              env.buffers![valsRef].buffer,
              env.buffers![valsRef].byteOffset,
              env.buffers![valsRef].byteLength / 8,
            );

            return {
              api_version: RPC_API_VERSION,
              request_id: env.request.request_id,
              project_id: env.request.project_id,
              project_revision: env.request.project_revision,
              status: "success",
              result: {
                nnz: valsView.length,
                vals_sum: valsView[0] + valsView[1] + valsView[2],
              },
              assumptions: {},
              diagnostics: {},
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
    storeOptions: { idbFactory: new InMemoryIDBFactory(), dbName: "packed_rt_1" },
    workerFactory: () => {
      const created = createMessageChannelWorkerTransport({ pyodideLoader: loader });
      const origPostMessage = created.worker.postMessage.bind(created.worker);
      created.worker.postMessage = (msg: unknown, transfer?: ArrayBuffer[]) => {
        if (
          typeof msg === "object" &&
          msg !== null &&
          (msg as { kind?: string }).kind === "rpc_request"
        ) {
          capturedWireMsg = msg as WorkerInboundMessage;
          capturedTransferList = transfer ? [...transfer] : undefined;
        }
        origPostMessage(msg, transfer);
      };
      return created;
    },
  });

  try {
    await client.init();

    const kIdx = new Int32Array([0, 1, 1]);
    const rows = new Int32Array([0, 0, 1]);
    const cols = new Int32Array([0, 1, 1]);
    const vals = new Float64Array([-1.0, 0.5, -2.5]);

    const kBuf = kIdx.buffer;
    const rBuf = rows.buffer;
    const cBuf = cols.buffer;
    const vBuf = vals.buffer;

    const req = makePackedSdpRequest("opt-packed-1", 1, {
      k_idx: kIdx,
      rows,
      cols,
      vals,
    });

    const resp = await client.execute(req);
    assert.equal(resp.status, "success");
    assert.equal(resp.result?.nnz, 3);
    assert.equal(resp.result?.vals_sum, -3.0);

    // Verify transfer list passed to postMessage held the EXACT 4 ArrayBuffers
    assert.ok(capturedTransferList !== undefined);
    assert.equal(capturedTransferList.length, 4);
    assert.ok(capturedTransferList.includes(kBuf));
    assert.ok(capturedTransferList.includes(rBuf));
    assert.ok(capturedTransferList.includes(cBuf));
    assert.ok(capturedTransferList.includes(vBuf));

    // Verify true zero-copy detachment on the sender side after MessageChannel transfer
    assert.equal(kBuf.byteLength, 0);
    assert.equal(rBuf.byteLength, 0);
    assert.equal(cBuf.byteLength, 0);
    assert.equal(vBuf.byteLength, 0);

    // Verify wire message replaced TypedArrays with BufferTensorRefs
    assert.ok(capturedWireMsg && capturedWireMsg.kind === "rpc_request");
    assert.ok(workerReceivedPacked !== undefined);
    assert.ok(workerReceivedBuffers !== undefined);
    assert.equal(Object.keys(workerReceivedBuffers).length, 4);
    for (const field of ["k_idx", "rows", "cols", "vals"] as const) {
      const refId = workerReceivedPacked[field].buffer_ref;
      assert.ok(workerReceivedBuffers[refId] instanceof Uint8Array);
    }

    // Reusing detached TypedArray is rejected with VALIDATION_ERROR
    assert.throws(
      () =>
        validateRpcRequest(
          makePackedSdpRequest("opt-packed-reuse", 2, {
            k_idx: kIdx,
            rows: new Int32Array([0]),
            cols: new Int32Array([0]),
            vals: new Float64Array([1.0]),
          }),
        ),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
    );

    // preserveSenderCopy: true keeps caller's TypedArrays intact while still transferring
    const kKeep = new Int32Array([0, 1, 1]);
    const rKeep = new Int32Array([0, 0, 1]);
    const cKeep = new Int32Array([0, 1, 1]);
    const vKeep = new Float64Array([2.0, 3.0, 4.0]);
    const respKeep = await client.execute(
      makePackedSdpRequest("opt-packed-keep", 2, {
        k_idx: kKeep,
        rows: rKeep,
        cols: cKeep,
        vals: vKeep,
      }),
      { preserveSenderCopy: true },
    );
    assert.equal(respKeep.status, "success");
    assert.equal(respKeep.result?.vals_sum, 9.0);
    assert.equal(kKeep.buffer.byteLength, 12);
    assert.equal(vKeep.buffer.byteLength, 24);
    assert.equal(vKeep[0], 2.0);

    const stats = await client.getWorkerStats();
    assert.equal(stats.pyproxy.activeProxies, 0);
  } finally {
    client.dispose();
  }
});

test("F7-PACKED-04: MockWorkerAdapter handles F_k_packed TypedArrays cleanly without crashing", async () => {
  const mock = new MockWorkerAdapter({
    storeOptions: { idbFactory: new InMemoryIDBFactory(), dbName: "packed_mock_1" },
    fixtures: {
      "B-SDP-A-D": {
        fixture_id: "B-SDP-A-D",
        provenance: { oracle: "test", lib_versions: { numpy: "2.4.6" } },
        tolerances: {},
        data: {
          cases: {
            "T-SDP-C1": {
              level: "C",
              expected: {
                solver_status: "optimal",
                audit_feasibility: "feasible",
                certificate_status: "validated_dual",
              },
            },
          },
        },
      },
    },
  });

  try {
    await mock.init();
    const req = makePackedSdpRequest(
      "mock-packed-1",
      1,
      {
        k_idx: new Int32Array([0, 1]),
        rows: new Int32Array([0, 1]),
        cols: new Int32Array([0, 1]),
        vals: new Float64Array([-1.0, -2.0]),
      },
      { case_id: "T-SDP-C1" },
    );

    const resp = await mock.execute(req);
    assert.equal(resp.status, "success");
    assert.equal(resp.result?.solver_status, "optimal");

    // Non-finite vals in F_k_packed is rejected even in MockWorkerAdapter
    await assert.rejects(
      () =>
        mock.execute(
          makePackedSdpRequest("mock-packed-nan", 2, {
            k_idx: new Int32Array([0]),
            rows: new Int32Array([0]),
            cols: new Int32Array([0]),
            vals: new Float64Array([Number.NaN]),
          }),
        ),
      (err: unknown) =>
        err instanceof ControlLabBridgeError && err.code === "VALIDATION_ERROR",
    );
  } finally {
    mock.dispose();
  }
});
