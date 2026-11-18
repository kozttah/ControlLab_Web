# Typed references at the Worker boundary

Producer F7 handoff for `WP-V1-F7-MODEL-REF-REHYDRATION`, 2026-11-18.
Base: `31227da6fe93ba142058e741c8dbcd4c5637b89e`. Normative source:
CL-DIR-001 §§8.1–8.4/13.9 and Appendix E; R-02/R-03/R-06/R-28,
T-RPC-01/T-RPC-02/T-SEC-01. Independent F9 acceptance is required.

## Transport contract

`materializePayloadReferences` is shared by `PyodideWorkerRuntime` and
`MockWorkerAdapter`. It runs after binary buffer rehydration and before the safe
`toPy({request, payload})` data bridge. The outer `payload` supplied to the Python
dispatcher is canonical. Scientific functions, computations, validation and DTO
restoration stay in Python; no scientific algorithm was added to TypeScript.

Only the following operation-specific **top-level** sources are interpreted.
An alias group permits at most one supplied field, including explicitly supplied
null fields. Every group is checked for ambiguity before any store lookup.

| Operation | Accepted inline source / reference aliases | Canonical target | Referenced DTO kinds |
| --- | --- | --- | --- |
| `core.reuse_model` | `model` / `model_ref` | `model` | StateSpace, TransferFunction, IdentifiedModel, and the three TS discriminants below |
| `identification.fit_arx`, `fit_oe`, `fit_subspace` | `dataset` / `dataset_ref`; independently `val_dataset` / `val_dataset_ref` | `dataset`, `val_dataset` | Dataset |
| `identification.validate_model` | `model` or `plant` / `model_ref` or `plant_ref` | `model` | StateSpace, TransferFunction, IdentifiedModel |
| `identification.validate_model` | `val_dataset` or `dataset` / `val_dataset_ref` or `dataset_ref`; independently `train_dataset` / `train_dataset_ref` | `val_dataset`, `train_dataset` | Dataset |
| Declared state-space operations below | `plant` or `model` / `plant_ref` or `model_ref` | `plant` | StateSpace |
| Declared frequency/MIMO operations below | `plant` or `model` / `plant_ref` or `model_ref` | `plant` | StateSpace, TransferFunction |
| `core.interconnect`, `core.validate_interconnection` | `plant` / `plant_ref` | `plant` | StateSpace, TransferFunction, TS discriminants |
| `fuzzy.evaluate`, `fuzzy.evaluate_surface`, `fuzzy.export_fml` | `system`, `plant` or `model` / `system_ref`, `plant_ref` or `model_ref` | `system` | FuzzySystem |
| `io.export_pvm` | `plant` or `model` / `plant_ref` or `model_ref` | `plant` | StateSpace, TransferFunction |
| `optimization.solve`, `verify`, `export_cvxpy`, `export_yalmip`, when using a declared state-space template | `plant` or `model` / `plant_ref` or `model_ref` | `plant` | StateSpace |
| Same optimization operations with `ts_pdc_stabilization` | `ts_model` or `plant` / `ts_model_ref` or `plant_ref` | `ts_model` | TS discriminants |

State-space operations are explicitly enumerated in the helper: `design_lqr`,
`design_lqi`, `design_pole_placement`, `design_observer`, `design_kalman`,
`design_lqg`, `analyze`, `check_pbh`, `gramians`, `solve_care`, `solve_dare`,
`solve_lyapunov`, `discretize_zoh`, `simulate_lti`, all under `statespace.`.
Frequency operations are `frequency.eval_response`, `bode`, `stability_margins`,
`root_locus`, `step_response`, `singular_values`, plus `mimo.singular_values`,
`mimo.rga`, `mimo.sensitivity`. This is an allowlist, not prefix matching.
State-space optimization templates are `quadratic_stabilization`,
`continuous_stabilization`, `decay_rate`, `lqr_lmi`, `regional_pole_placement`.
`hinf_brl` consumes its own raw matrix fields and does not receive plant aliases.

TS DTO `kind` is `ts_measured`, `polytopic_uncertain` or
`ts_partially_observed`, as specified by the canonical schema. `TSStateSpace` is
a Python class name, not a serialized discriminator. TS-to-LTI conversion is
never performed by the bridge. The Python reuse contract rejects unsupported
representation changes normally.

Source arrays are also checked for ambiguity: a dataset source in a fitting
operation may not coexist with raw `u/y/t`; a plant source in state-space
operations or the declared state-space SDP templates may not coexist with raw
`A/B/C/D`. Independent parameters such as `Q/R`, frequency `omega`, and simulation
time `t` remain valid with the corresponding plant source. Raw arrays alone are
unchanged and continue to be validated scientifically in Python.

## Identity, type and failure behavior

A consumed reference must contain exactly `{id, revision}`: a nonblank string ID
and a safe integer revision >=0. Extra fields, including a `project_id` override,
are rejected. Lookup uses only the request's project and the exact ID/revision.
After lookup, both entry metadata and the stored DTO must agree on project,
ID/revision and kind. In particular, key-delimiter collisions cannot expose a
different project's entry, and an impostor DTO stored under another identity or
declared kind cannot be forwarded.

Historical revisions explicitly present remain usable. There is no latest-version
fallback, no other-project/global lookup, and no automatic registration. A missing
revision or identity mismatch produces `VALIDATION_ERROR`; a DTO kind incompatible
with a declared source produces `UNSUPPORTED_MODEL`. Error responses remain typed,
finite RPC v1.0 responses with null result, existing diagnostics and provenance.
Inline DTOs keep their existing Python scientific validation.

The helper clones inputs and stored values. Consumed reference fields are removed,
as are alternate inline alias names, so `core.reuse_model` receives exactly its
inline `model` and any caller-supplied `target_kind`, rather than simultaneous
`model` plus `model_ref`. Unknown fields are retained for normal downstream
contract validation. No recursive `*_ref` resolution occurs: source provenance,
lineage, nested user data and unrelated reference names remain data.

The caller must explicitly register any returned derived/identified model before
using its returned reference. `controller_ref` and arbitrary new reference names
are outside this resolver's allowlist; no support is inferred from a suffix.
The preexisting project revision/cancellation checks, transfer ownership,
snapshot/restart mechanism, LRU and PyProxy cleanup remain unchanged.

## Producer verification

```sh
npm --prefix web run typecheck
node scripts/run_web_tests.mjs --scope f7
```

Result: **63 passed, zero failures/skips**, including **31 new reference tests**.
`git diff --check` passed. Direct tests exercise alias destinations, all reusable
serialized kinds, ambiguity before lookup, null/extra/malformed fields, raw source
conflicts, missing/exact historical revisions, cross-project and delimiter
collisions, impostor DTO identity/kind, no mutation/registration, legacy consumers,
unknown/nested references, Worker proxy cleanup and honest Mock unsupported status.

The initial suite exposed old lifecycle/entrypoint/buffer test requests containing
an example `plant_ref` that was never registered. These transport-only setups now
provide a source inline (or source matrices read from unchanged gold) so they reach
their intended lifecycle/binary/entrypoint boundary. Their assertions were not
weakened. Dedicated registered-reference recovery tests remain intact.

Injected Node transport doubles do not prove scientific/Wasm availability. The
Mock uses the same resolver but still rejects unsupported scientific operations,
including model reuse, instead of manufacturing scientific success. Independent
F9 must exercise registration, referenced identification/reuse, explicit derived
registration, LQR/frequency consumption, failure cases and recovery in real
Worker/Pyodide.

## Appendix E producer checklist

| Item | Producer evidence / scope |
| --- | --- |
| 1. Contract | Existing RPC v1.0, canonical DTOs and core reuse contract; operation-specific aliases match dispatcher destinations. |
| 2. Status/diagnostics/provenance | Typed validation/type failures; provenance is data; canonical payload forwarded through the existing safe bridge. |
| 3. Analytic tests | No numerical algorithm added; transport invariants tested before scientific dispatch. |
| 4. Independence | Separate F9 reviewer authors and executes real Worker/Pyodide proofs; producer doubles explicitly scoped. |
| 5. Ownership/gold | Only F7 bridge/worker/unit paths edited by producer; no scientific module, fixture or oracle tolerance modified. |
| 6. CPython/Pyodide | Producer verifies transport/typecheck and lifecycle units; real Wasm integration is the independent F9 responsibility. |
| 7. Schema/migration | No schema or migration; reference envelopes remain `{id, revision}` and derived results require explicit registration. |
| 8. Logs/results | Acceptance output retained by Maestro/F9; 63 passing F7 tests and new table/invariants documented here. |
| 9. Maturity | No scientific capability, solver or gate is promoted by unit doubles. |
| 10. Limitations | Allowlist only; historical exact revisions supported; no automatic result registration, generic suffix lookup or implicit TS reduction. |

This producer checklist does not constitute independent F9 acceptance.
