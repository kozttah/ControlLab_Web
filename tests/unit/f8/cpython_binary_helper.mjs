/** Test-only CPython binary-buffer dispatcher helper for F8 unit tests. */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const cwd = fileURLToPath(new URL("../../../", import.meta.url));

export function dispatchPythonWithBinaryBuffers(req, rawWireBuffers) {
  const buffersB64 = {};
  for (const [ref, wb] of Object.entries(rawWireBuffers)) {
    buffersB64[ref] = Buffer.from(wb.buffer).toString("base64");
  }
  const pyScript = [
    "import sys, json, base64",
    "from control_lab.core.rpc import dispatch",
    "env = json.load(sys.stdin)",
    "bufs = {k: memoryview(base64.b64decode(v)) for k, v in env['buffers_b64'].items()}",
    "resp = dispatch(env['request'], buffers=bufs)",
    "print(json.dumps(resp, allow_nan=False))",
  ].join("; ");
  const out = spawnSync("python3", ["-c", pyScript], {
    cwd,
    input: JSON.stringify({ request: req, buffers_b64: buffersB64 }),
    encoding: "utf8",
    timeout: 30000,
    maxBuffer: 8 * 1024 * 1024,
  });
  if (out.error || out.status !== 0) {
    throw new Error(out.stderr || String(out.error));
  }
  return JSON.parse(out.stdout);
}

export function compareCanonicalSdpFromDictSolve(packedJson, sparseJson) {
  const pyScript = [
    "import sys, json",
    "import numpy as np",
    "from control_lab.optimization.modeling.canonical import CanonicalSDPProblem",
    "from control_lab.optimization import solve",
    "data = json.load(sys.stdin)",
    "p_packed = CanonicalSDPProblem.from_dict(data['packed'])",
    "p_sparse = CanonicalSDPProblem.from_dict(data['sparse'])",
    "r_packed = solve(p_packed, raise_on_error=True)",
    "r_sparse = solve(p_sparse, raise_on_error=True)",
    "x_p = r_packed.data['x']['data'] if isinstance(r_packed.data['x'], dict) else np.asarray(r_packed.data['x']).tolist()",
    "x_s = r_sparse.data['x']['data'] if isinstance(r_sparse.data['x'], dict) else np.asarray(r_sparse.data['x']).tolist()",
    "print(json.dumps({'cert_p': r_packed.data['certificate_status'], 'cert_s': r_sparse.data['certificate_status'], 'max_diff': float(np.max(np.abs(np.asarray(x_p) - np.asarray(x_s))))}))",
  ].join("; ");
  const out = spawnSync("python3", ["-c", pyScript], {
    cwd,
    input: JSON.stringify({ packed: packedJson, sparse: sparseJson }),
    encoding: "utf8",
    timeout: 30000,
    maxBuffer: 8 * 1024 * 1024,
  });
  if (out.error || out.status !== 0) {
    throw new Error(out.stderr || String(out.error));
  }
  return JSON.parse(out.stdout);
}
