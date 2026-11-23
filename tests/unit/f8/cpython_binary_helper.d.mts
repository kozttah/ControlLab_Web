import type { RpcRequest, RpcResponse } from "../../../web/bridge/protocol.ts";

export declare function dispatchPythonWithBinaryBuffers(
  req: RpcRequest,
  rawWireBuffers: Record<string, { buffer: ArrayBuffer }>,
): RpcResponse;

export declare function compareCanonicalSdpFromDictSolve(
  packedJson: Record<string, unknown>,
  sparseJson: unknown,
): { cert_p: string; cert_s: string; max_diff: number };
