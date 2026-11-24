# Handoff e Parecer F9 — `WP-PHASE9-04-F6-CHORDAL-CLIQUES-SPARSE-SCHUR`

- **WorkPackage**: `WP-PHASE9-04-F6-CHORDAL-CLIQUES-SPARSE-SCHUR`
- **Frente Produtora**: `F6 (f6-optimization-lmi)`
- **Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base**: `60c1867d2c4115d5feaa00af79d66bb374225b8a`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T05:20:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Escopo F6 (`control_lab/optimization/`, `tests/unit/f6/`) verificado via `git status -s` e `git diff --stat`: nenhuma alteração fora de `allowed_paths`, zero chamadas a `linalg.inv`, zero relaxamento de tolerâncias, zero `pytest.skip` ou `importorskip`.

| Artefato F6 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/optimization/backends/native_core.py` | `4df54aab9b024d9231686c99c321f67a9a209c9d1259f35d2a93f1b9cbff5f53` | Decomposição cordal por cliques maximais + fusão em árvore de cliques (`scipy.sparse.csgraph`) e completação PSD exata de máxima entropia sem `linalg.inv` (Vandenberghe & Andersen 2015; Garstka, Cannon & Goulart, IFAC 2020), mais fatoração esparsa adaptativa de Schur via `scipy.sparse.linalg.splu` (SuperLU) para `m >= 60` e densidade simbólica `< 25%` com recuo transparente para Cholesky denso. |
| `control_lab/optimization/backends/solve.py` | `2d98b1e0fbae474d392d57bb5188d15ffd1f1f79ae07daa10121b1ef86dcb6b3` | Propagação retrocompatível de `chordal_summary` e `schur_factorization_mode` em `Result.diagnostics`. |
| `tests/unit/f6/test_phase9_cycle4_chordal_sparse_schur.py` | `241c0e299a7ed44ba4477de70547399eb5111bc5d403810a6aba7231217e418c` | 10 testes unitários F6 cobrindo blocos PSD em banda (`dim=12, 20`), cadeia acoplada (`dim=16`), bypass denso, completação PSD posto-deficiente, certificado Farkas infactível, Schur esparso `splu` vs `dense_cholesky`/`clarabel_direct` e invariante AST zero `linalg.inv`. |

---

## 2. Evidências Executadas pela F9

| Verificação Independente | Resultado | Status |
|---|---|---|
| Auditoria estática (`linalg.inv`, `pytest.skip`, `importorskip`, tolerâncias) | Zero ocorrências proibidas; zero relaxamento de tolerâncias | PASS |
| Oráculo independente F9 (`tests/oracles/test_phase9_cycle4_chordal_oracle.py`) | **4 passed, 0 failed, 0 skipped** (`dim=16, 24` cordal com `verify()` 5D no bloco original e paridade `< 1e-6` vs `clarabel_direct`; `m=89` `sparse_splu` `< 1e-8` vs denso e `< 1e-6` vs Clarabel; bypass denso) | PASS |
| Suite completa `sdp_available` (`pytest tests/unit/f6 tests/oracles -q`) | **444 passed, 0 failed, 0 skipped** em `72.53s` (`exit 0`) | PASS |
| Gate simulado `core_no_sdp` (`tests/unit/f1..f5`, `tests/oracles`, `tests/integration`) | **597 passed, 0 failed, 0 skipped** em `59.76s` (`exit 0`) | PASS |
| Pyodide Wasm + E2E em Chromium real (`tests/wasm/test_real_runtime.py` + `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`) | **20 passed, 0 failed, 0 skipped** em `213.46s` (`exit 0`) | PASS |

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Validada via `solve(...)`, `verify(...)`, `solve_native_raw(...)` e pipeline Worker/Pyodide real (`test_real_runtime.py` e Tab 6 E2E). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `Result.diagnostics` expõe `chordal_summary` e `schur_factorization_mode`, preservando `solver_status`, `certificate_status` (`validated_dual` e `validated_infeasibility`) e `audit_feasibility`. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Completação PSD `_chordal_psd_complete` validada contra matriz PSD de posto deficiente conhecida (`atol=1e-12`, `eigvalsh >= -1e-10`) e bloco infactível com certificado Farkas. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Paridade `< 1e-6` verificada contra `use_chordal=False` e contra o oráculo independente `clarabel_direct`; `sparse_splu` validado `< 1e-8` vs `dense_cholesky` e `< 1e-6` vs `clarabel_direct`; auditoria 5D `verify()` executada no problema original não decomposto. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações estritas em `control_lab/optimization/` e `tests/unit/f6/`; fixtures ouro intactas (`verify_fixtures.py` PASS). | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Validado em CPython (`444 passed` `sdp_available`, `597 passed` `core_no_sdp`) e em Chromium + Pyodide Wasm real (`20 passed` + benchmark cordal `dim=20` e `splu` `m=159` com `validated_dual`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `verify_fixtures.py` confirma 11 schemas Draft 2020-12 válidos; novos campos em `diagnostics` são aditivos e retrocompatíveis. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, resultados dos gates e benchmark CPython/Chromium Wasm anexados neste handoff, em `WP-PHASE9-04B-F9-CHORDAL-ENVELOPE-RECALIBRATION.md` e em `ADR-010`/`ADR-015`. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `control_lab/experimental/sdp_educational/` permanece isolado como experimental sem promoção indevida. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Limites operacionais de `BROWSER_ENVELOPE` (`448` rápido / `1024` estendido) e recomendações offline CVXPY/YALMIP preservados com mensagens estruturadas (`RESOURCE_LIMIT`). | CONFORME |

---

## 4. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Data (UTC)**: `2026-11-24T05:20:00Z`
