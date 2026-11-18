# Producer handoff — WP-AUDIT-FIX-F9-MIMO-REGENERATION

F9 producer, 2026-11-18. Base `4c908f97fe955ca41db6f5d582a56493198ea78c`.
CL-DIR-001 §§10.2/10.4/13.11 and Appendices C/E, R-23/R-24;
T-MIMO-01/T-MIMO-02/T-FREQ-02 and the explicitly approved T-PVM-01 addendum.
This producer report is **ready for independent review**, not self-acceptance.

## Final behavior

The regeneration test now delegates only its MIMO and PVM cases to independent
fixture-specific certificates. The ARX/DARE tests and scientific production
modules remain unchanged. MIMO validates the known logarithmic grid against an
80-digit mathematical reference and propagates its admitted rounding into
closed-form G/S/T/RGA and singular-value checks. Multiple crossings are isolated
independently from the cubic magnitude equation. PVM independently reconstructs
the two scalar ODEs, piecewise saturation switches, control/output equations and
CARE/gain identities. No production solver/simulator or generator creates the
helper's numerical reference.

Both certificates reject malformed structure and nonfinite data before any
coercion/normalization. All matrices, scientific criteria, metadata and
unreviewed fields stay exact. MIMO permits only named calculated/grid leaves;
PVM permits only x/u/y data. In particular, PVM time and switch fields are exact.
All existing frozen atols are still additional mandatory limits. The original
negative CI candidate remains unchanged and is a positive regression input.

`NUMERICAL_CERTIFICATE.md` documents exponent/exp propagation, matrix/response
condition and grid derivatives, root isolation/backward error, scalar ODE
continuity and error propagation. The two-ULP transcendental assumption and
fixture-specific gamma envelopes are explicit; neither IEEE/libm universality
nor directed interval guarantees are asserted.

## Validation

- Producer focused suite under the real CI-reproducing SIMD-disabled/Haswell
  configuration: **168 passed in 2.27 s**, zero failures/skips. This includes
  30 existing fixture cases, 43 producer cases and 95 independent-auditor cases.
- Ruff check, format and `git diff --check`: passed.
- Maestro exact-lock profiles: core **525/525** and SDP **359/359** in each of
  Haswell, Sandybridge and Haswell with AVX512F/AVX2/FMA3 disabled: **2,652 test
  executions**, not 2,652 distinct tests, zero skips. The Maestro's summary and
  JSON/JUnit files record source hashes and exact-lock closure.
- Independent probes reproduce all 92 MIMO differences of the primary CI
  candidate and ten PVM output-leaf differences. Both certificates accept these
  real variants, while their structural/mathematical adversaries reject damage.
- Seven gold fixtures, checksum manifest, pinned Pyodide assets lock, fixture
  generator and prior ARX certificate retain their protected hashes. No frozen
  value, tolerance, generator source or F1–F8 implementation was modified.

## Appendix E producer checklist

| Item | Producer evidence and scope |
| --- | --- |
| 1. Contract | No product API/RPC/schema change. The comparisons implement the already declared fixture precision and known-grid semantics. |
| 2. Diagnostics/provenance | Named assertion failures and returned residual/grid/error diagnostics; frozen metadata/provenance exact; actual CPU/kernel flags recorded. |
| 3. Analytic reference | Decimal grid, 2x2 formulas, closed-form spectrum/RGA, cubic roots and scalar piecewise ODE references, without production calls. |
| 4. Independence | Separate F9 auditor wrote 95 adversarial tests, reproduced actual variants and reviews the math and six-profile evidence. |
| 5. Ownership/gold | Only scripts/tests-oracles/audit documents changed by producer; gold, locks, generator, existing atols and scientific production untouched. |
| 6. Domain | CPython fixture QA only, verified in the two exact optional-dependency profiles; no new Wasm/PathView capability claimed. |
| 7. Schema/migration | No schema migration; recursive types/keys/list lengths plus exact shapes/dtypes/orders reject malformed normalization inputs. |
| 8. Evidence | Focused producer log, source hashes, independent configuration probes and Maestro six-profile JSON/JUnit reports. |
| 9. Maturity | No solver/UI/gate/product maturity promoted. Historical PathView fixture flags remain unchanged. |
| 10. Limits | Fixed conditioned fixtures, declared two-ULP transcendental support envelope and one host with multiple real numerical configurations; no universal solver/libm guarantee. |

The independent F9 handoff must grant final acceptance. The hosted CI of the
completion commit must still be checked; passing local profiles is not a claim
that an unexecuted hosted run or Pages publication succeeded.
