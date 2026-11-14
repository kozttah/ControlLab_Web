/** Test-only CPython adapter for the actual F1 dispatcher, NOT Pyodide/Wasm. */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const cwd = fileURLToPath(new URL("../../../", import.meta.url));
export const cpythonLoader = async () => ({
  pyodide: {
    runPythonAsync: async () => { throw new Error("No Python string execution from bridge"); },
    toPy: (value) => ({ __isPyProxy: true, toJs: () => value, destroy() {} }),
    pyimport: (name) => {
      if (name !== "control_lab.core.rpc") throw new Error(`Wrong dispatcher module: ${name}`);
      return {
        dispatch: (proxy) => {
          const result = spawnSync("python3", ["-c", "import sys,json; from control_lab.core.rpc import dispatch; print(json.dumps(dispatch(json.load(sys.stdin)),allow_nan=False))"], {
            cwd, input: JSON.stringify(proxy.toJs()), encoding: "utf8", timeout: 30000,
            maxBuffer: 4 * 1024 * 1024,
          });
          if (result.error || result.status !== 0) throw new Error(result.stderr || String(result.error));
          return JSON.parse(result.stdout);
        },
        destroy() {},
      };
    },
  },
  libVersions: {},
});
