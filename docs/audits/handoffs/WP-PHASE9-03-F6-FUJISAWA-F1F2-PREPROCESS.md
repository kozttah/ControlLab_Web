# Handoff e Parecer F9 — `WP-PHASE9-03-F6-FUJISAWA-F1F2-PREPROCESS`

- **WorkPackage**: `WP-PHASE9-03-F6-FUJISAWA-F1F2-PREPROCESS`
- **Frente Produtora**: `F6 (f6-optimization-lmi)`
- **Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base**: `f776cfb4c6f9a2b295e3e572794c32329cbc2b0a`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T04:56:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Escopo F6 (`control_lab/optimization/`, `tests/unit/f6/`) verificado via `git status -s` e `git diff --stat`: nenhuma alteração fora de `allowed_paths`, zero chamadas a `linalg.inv`, zero relaxamento de tolerâncias, zero `pytest.skip` ou `importorskip`.

| Artefato F6 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/optimization/backends/native_core.py` | `4a7b77e3e484e7fa85b21bcf6aeee1052d49e343fd4db65c8243fa7298436aaa` | Fórmulas esparsas F1/F2 de Fujisawa–Kojima–Nakata (1997) na montagem do complemento de Schur (sem alocar `_F_cols` denso em blocos F1/F2), diagnósticos `schur_assembly_modes`, e pré-processamento simbólico de colunas `F_k` (eliminação de colunas nulas e fusão de colunas duplicadas/colineares com reconstrução exata primal/dual antes da auditoria 5D). |
| `control_lab/optimization/backends/solve.py` | `fc8aee6d043c1ab7b13d0f0ab870ab91212baf08fdfb15a4dd5d8634f3e023b2` | Propagação retrocompatível de `schur_assembly_modes` e `preprocessing_summary` em `Result.diagnostics`. |
| `tests/unit/f6/test_phase9_cycle3_f1f2_preprocess.py` | `ee74dac730a273eaa1d2589e13229a3ea09d4ce0b1624e6dcfe8c592e81f8b7b` | Testes unitários F6 cobrindo precisão F1/F2 vs F3 (`< 1e-12`), pré-processamento simbólico (colunas nulas/duplicadas/ilimitadas/infactíveis), paridade com `clarabel_direct` e invariante AST zero `linalg.inv`. |

---

## 2. Evidências Executadas pela F9

| Verificação Independente | Resultado | Status |
|---|---|---|
| Auditoria estática (`linalg.inv`, `pytest.skip`, `importorskip`, tolerâncias) | Zero ocorrências proibidas; zero relaxamento de tolerâncias | PASS |
| Oráculo independente F9 (`tests/oracles/test_phase9_cycle3_f1f2_oracle.py`) | **4 passed, 0 failed, 0 skipped** (`n=12, 16, 20` F1/F2 vs `F3_blas` e `clarabel_direct` `< 1e-6`, + pré-processamento simbólico com `verify()` no problema original não-reduzido) | PASS |
| Suite completa `sdp_available` (`pytest tests/unit/f6 tests/oracles -q`) | **430 passed, 0 failed, 0 skipped** em `63.41s` (`exit 0`) | PASS |
| Gate simulado `core_no_sdp` (`tests/unit/f1..f5`, `tests/oracles`, `tests/integration`) | **593 passed, 0 failed, 0 skipped** em `47.98s` (`exit 0`) | PASS |
| Pyodide Wasm + E2E em Chromium real (`tests/wasm/test_real_runtime.py` + `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`) | **20 passed, 0 failed, 0 skipped** em `188.51s` (`exit 0`) | PASS |

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Validada via `solve(...)`, `verify(...)`, `solve_native_raw(...)` e pipeline Worker/Pyodide real (`test_real_runtime.py` e Tab 6 E2E). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `Result.diagnostics` expõe `schur_assembly_modes` e `preprocessing_summary`, preservando `solver_status`, `certificate_status` e `audit_feasibility` em casos ótimos, infactíveis e ilimitados. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | F1/F2 comparado matriz-a-matriz contra referência densa F3 (`< 1e-12`) e autovalores de malha fechada `Re(eig(A+BK)) < -0.20` verificados independentemente. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Paridade `< 1e-6` verificada contra `F3_blas` e contra o oráculo independente `clarabel_direct`, além de auditoria 5D independente `verify()` no problema original não-reduzido. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações estritas em `control_lab/optimization/` e `tests/unit/f6/`; fixtures ouro intactas (`verify_fixtures.py` PASS). | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Validado em CPython (`430 passed` `sdp_available`, `593 passed` `core_no_sdp`) e em Chromium + Pyodide Wasm real (`20 passed`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `verify_fixtures.py` confirma 11 schemas Draft 2020-12 válidos; campos extras em `diagnostics` são retrocompatíveis. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, resultados de testes e tempos de execução registrados neste handoff e no parecer `WP-PHASE9-03C-F9-F1F2-BENCHMARK-AUDIT.md`. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `control_lab/experimental/sdp_educational/` permanece isolado como experimental sem promoção indevida. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Ciclo 4 (`WP-PHASE9-04-F6-CHORDAL-CLIQUES-SPARSE-SCHUR` e `WP-PHASE9-04B-F9-PHASE9-RELEASE-BENCHMARK`) permanece planejado em `PROJECT_STATE.json`. | CONFORME |

---

## 4. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Data (UTC)**: `2026-11-24T04:56:00Z`
