/** F7 worker/bridge round-trip tests for multi-I/O ANFIS & fuzzy.evaluate_surface. */
import test from "node:test";
import assert from "node:assert/strict";

import {
  type ControlLabEngineClient,
  type FuzzyEvaluateSurfacePayload,
  type FuzzyFitAnfisPayload,
} from "../../../web/bridge/client.ts";
import { PyodideEngineClient } from "../../../web/bridge/pyodide_client.ts";
import { InMemoryIDBFactory } from "../../../web/storage/indexeddb_store.ts";
import { createMessageChannelWorkerTransport } from "../../../web/worker/pyodide_worker.ts";
import { cpythonLoader } from "./cpython_runtime.mjs";

function makeClient(dbName: string): PyodideEngineClient {
  return new PyodideEngineClient({
    storeOptions: {
      idbFactory: new InMemoryIDBFactory(),
      dbName,
    },
    workerFactory: () =>
      createMessageChannelWorkerTransport({
        pyodideLoader: cpythonLoader,
      }),
  });
}

function buildMultiIoDataset(): { X: number[][]; y: number[][] } {
  const X: number[][] = [];
  const y: number[][] = [];
  const grid = [-1.0, -0.35, 0.35, 1.0];
  for (const x1 of grid) {
    for (const x2 of grid) {
      for (const x3 of grid) {
        const u1 = 1.4 * x1 - 0.7 * x2 + 0.25 * x3 + 0.1 * x1 * x2;
        const u2 = -0.8 * x1 + 1.1 * x3 + 0.5 - 0.15 * x2 * x3;
        X.push([x1, x2, x3]);
        y.push([u1, u2]);
      }
    }
  }
  return { X, y };
}

test("F7 bridge round-trip: fuzzy.fit_anfis multi-I/O + fuzzy.evaluate_surface with output_name & fixed_inputs", async () => {
  const client: ControlLabEngineClient = makeClient("f7_fuzzy_anfis_bridge_roundtrip");
  try {
    const caps = await client.init();
    assert.ok(caps.operations.includes("fuzzy.fit_anfis"));
    assert.ok(caps.operations.includes("fuzzy.evaluate_surface"));
    assert.equal(typeof client.fitAnfis, "function");
    assert.equal(typeof client.evaluateFuzzySurface, "function");

    const { X, y } = buildMultiIoDataset();
    const fitPayload: FuzzyFitAnfisPayload = {
      X,
      y,
      n_mfs: [2, 2, 2],
      mf_type: ["gaussian", "bell", "gaussian"],
      input_names: ["x1", "x2", "x3"],
      output_names: ["u1", "u2"],
      max_epochs: 6,
      learning_rate: 0.015,
      validation_split: 0.2,
      seed: 17,
    };

    const fitResp = await client.fitAnfis!(
      {
        request_id: "req-anfis-mimo-1",
        project_id: "proj-anfis-bridge",
        project_revision: 1,
      },
      fitPayload,
    );
    assert.equal(fitResp.status, "success");
    assert.ok(fitResp.result);

    const fuzzySystem = fitResp.result.fuzzy_system as Record<string, unknown>;
    assert.equal(fuzzySystem.kind, "FuzzySystem");
    assert.equal(fuzzySystem.inference_type, "ts");

    const inputVars = fuzzySystem.input_variables as Array<{ name: string; terms: Array<{ mf: string }> }>;
    const outputVars = fuzzySystem.output_variables as Array<{ name: string }>;
    assert.deepEqual(
      inputVars.map((v) => v.name),
      ["x1", "x2", "x3"],
    );
    assert.deepEqual(
      inputVars.map((v) => v.terms[0]?.mf),
      ["gaussian", "bell", "gaussian"],
    );
    assert.deepEqual(
      outputVars.map((v) => v.name),
      ["u1", "u2"],
    );

    const sysId = String(fuzzySystem.id);
    const sysRev = Number(fuzzySystem.revision);
    await client.registerObject("proj-anfis-bridge", sysId, sysRev, fuzzySystem, {
      kind: "FuzzySystem",
    });

    const surfacePayloadU2: FuzzyEvaluateSurfacePayload = {
      system_ref: { id: sysId, revision: sysRev },
      input_axes: ["x1", "x3"],
      fixed_inputs: { x2: 0.2 },
      output_name: "u2",
      n_points: 5,
    };
    const surfRespU2 = await client.evaluateFuzzySurface!(
      {
        request_id: "req-surface-u2",
        project_id: "proj-anfis-bridge",
        project_revision: 2,
      },
      surfacePayloadU2,
    );
    assert.equal(surfRespU2.status, "success");
    assert.ok(surfRespU2.result);
    assert.equal(surfRespU2.result.output_name, "u2");
    assert.deepEqual(surfRespU2.result.axes, ["x1", "x3"]);

    const surfaces = surfRespU2.result.surfaces as Record<string, number[][]>;
    assert.deepEqual(surfRespU2.result.Z, surfaces.u2);
    assert.notEqual(JSON.stringify(surfaces.u1), JSON.stringify(surfaces.u2));
    assert.equal((surfRespU2.result.Z as number[][]).length, 5);
    assert.equal((surfRespU2.result.Z as number[][])[0]?.length, 5);

    const badSurfaceResp = await client.evaluateFuzzySurface!(
      {
        request_id: "req-surface-bad-output",
        project_id: "proj-anfis-bridge",
        project_revision: 3,
      },
      {
        system_ref: { id: sysId, revision: sysRev },
        input_axes: ["x1", "x3"],
        output_name: "does_not_exist",
        n_points: 5,
      },
    );
    assert.equal(badSurfaceResp.status, "failure");
    assert.equal(badSurfaceResp.error?.code, "VALIDATION_ERROR");
  } finally {
    client.dispose();
  }
});
