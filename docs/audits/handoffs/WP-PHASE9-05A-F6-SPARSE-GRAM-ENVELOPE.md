# Handoff e Parecer F9 — `WP-PHASE9-05A-F6-SPARSE-GRAM-ENVELOPE`

- **WorkPackage**: `WP-PHASE9-05A-F6-SPARSE-GRAM-ENVELOPE`
- **Frente Produtora**: `F6 (f6-optimization-lmi)`
- **Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base**: `f97551017443779a613032f4fc8cc8ab0b250c57`
- **ADR / Referência**: `ADR-010` & `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T13:10:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Escopo F6 (`control_lab/optimization/`, `tests/unit/f6/`) verificado via `git status -s` e `git diff --stat`: nenhuma alteração fora de `allowed_paths`, zero chamadas a `linalg.inv`, zero `eval`/`new Function`, zero relaxamento de tolerâncias e zero `pytest.skip` ou `importorskip`.

| Artefato F6 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/optimization/backends/native.py` | `7e642bac1da3472e1712ec089e6e663c7fceca167339978d906d6721decd7888` | Recalibração do `BROWSER_ENVELOPE` para `fast_max_variables=1792`, `max_variables=3072`, `max_block_dimension=96` e `max_cone_entries=131072`. |
| `control_lab/optimization/backends/native_core.py` | `9408fb7f98ef3fd499f7c4ed9c14f6d2df7a67270a927a305612026becc9386a` | Substituição da montagem densa pré-solver `A_cone` e produto BLAS `A_col_scaled.T @ A_col_scaled` por `scipy.sparse.csc_matrix` (`A_cone_csc` + `G_cone_sp`) com verificação de posto cheio via dominância diagonal $O(\text{nnz})$ de Gershgorin ou `scipy.sparse.linalg.splu` simétrica (recaída SVD apenas sob deficiência de posto), `N_eq = None` sem igualdades e salvaguarda de piso numérico `float64` em Fase II. |
| `tests/unit/f6/test_native_sdp_and_exports.py` | `347b1c0f26a4186550ed7e5c42bf941de6578b2d45780af9ee21327524e5fb65` | Asserção atualizada do `BROWSER_ENVELOPE` (`1792 / 3072 / 96 / 131072`) e validação `RESOURCE_LIMIT` em `max_variables + 1`. |
| `tests/unit/f6/test_phase9_cycle4_chordal_sparse_schur.py` | `d9494e24746df92292db4efbf71921e2c87555507fa70184c4549b52006e69bd` | Testes unitários de estabilização contínua `n=48` (`1.224` variáveis, acima do teto legado `1.024`) com paridade `< 1e-6` vs `clarabel_direct`, recuperação de controlador estabilizante, bloqueio `3073 -> RESOURCE_LIMIT` e recaída SVD para dependência linear de 3 colunas (`m=52`). |

---

## 2. Evidências Executadas pela F9

| Verificação Independente | Resultado | Status |
|---|---|---|
| Auditoria estática (`linalg.inv`, `eval`, `pytest.skip`, `importorskip`, tolerâncias) | Zero ocorrências proibidas; zero relaxamento de tolerâncias | PASS |
| Oráculo independente F9 (`tests/oracles/test_phase9_cycle4_chordal_oracle.py`) | **5 passed, 0 failed, 0 skipped** (incluindo `n=48`, `1.224` vars com `verify()` 5D, `validated_dual`, paridade `< 1e-6` vs `clarabel_direct` e `3073 -> RESOURCE_LIMIT`) | PASS |
| Suite completa `sdp_available` (`pytest tests/unit/f6 tests/oracles -q -rs`) | **447 passed, 0 failed, 0 skipped** em `45.19s` (`exit 0`) | PASS |
| Gate simulado `core_no_sdp` (`tests/unit/f1..f5`, `tests/oracles`, `tests/integration`) | **598 passed, 0 failed, 0 skipped** em `30.96s` (`exit 0`) | PASS |
| Real Chromium + Pyodide Wasm (`test_wasm_phase9_05c_envelope_3072_and_n48_stabilization`) | `n=48` (`1.224` vars) resolvido em **`3421.2ms` (`3.42s`)** com `validated_dual`, `Δobj = 0.0` vs CPython, `0` PyProxies ativos e `3073 -> RESOURCE_LIMIT` | PASS |

---

## 3. Benchmarks de Escalonamento em Worker Isolado (Chromium + Pyodide Wasm)

| Caso (`fresh worker`) | Variáveis | Dimensão | Modo Schur | Tempo Wasm | Heap Wasm | Certificado 5D |
|---|---|---|---|---|---|---|
| `test_real_runtime` `stab n=48` | `1,224` | `48` | `dense_cholesky` | **`3.42s`** | `< 500 MiB` | `validated_dual` |
| `fresh_denseA_n56` (100% densa `A`) | `1,708` | `56` | `dense_cholesky` | **`8.20s`** | `754 MiB` | `validated_dual` |
| `fresh_chain_n64` | `2,208` | `64` | `dense_cholesky` | **`8.59s`** | `1,157 MiB` | `validated_dual` |
| `fresh_diag_n72` | `2,700` | `72` | `sparse_splu` | **`7.71s`** | `1,608 MiB` | `validated_dual` |
| `fresh_chain_n72` | `2,772` | `72` | `dense_cholesky` | **`14.85s`** | `1,706 MiB` | `validated_dual` |
| `fresh_diag_n80` | `3,320` | `80` | `sparse_splu` | **`11.79s`** | `2,424 MiB` | `validated_dual` |

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Validada via `solve(...)`, `verify(...)`, `optimization.capabilities` e `optimization.solve` no Worker Pyodide real (`21/21` Wasm+E2E). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Soluções preservam as 5 dimensões de auditoria (`validated_dual`) e estouro `3073` retorna `status="failure"`, `code="RESOURCE_LIMIT"` e `offline_recommended=True`. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Estabilização `n=48` (`max Re(eig(A+BK)) < -alpha`) e dependência linear de 3 colunas (`m=52`, objetivo exato `51.0`) validados analiticamente. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Paridade `< 1e-6` confrontada contra `clarabel_direct` e auditoria espectral 5D independente `verify()` no problema original não escalonado. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações estritas em `control_lab/optimization/` e `tests/unit/f6/`; fixtures ouro intocadas (`verify_fixtures.py` PASS). | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Paridade `Δobj = 0.0` comprovada para `n=48` (`1.224` variáveis) entre CPython e Chromium Pyodide Wasm (`3.42s`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `verify_fixtures.py` confirma os 11 schemas JSON Draft 2020-12 sem quebra de contrato. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, contagens de testes e tabela de escalonamento `n=48..80` anexados neste handoff e em `ADR-010`/`ADR-015`. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `control_lab/experimental/sdp_educational/` permanece isolado como experimental. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Teto `max_variables=3072` mantém `> 1.5 GiB` de margem sob o OOM `wasm32` (`~n=96`), emitindo `RESOURCE_LIMIT` com instrução explícita CVXPY/YALMIP. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `f97551017443779a613032f4fc8cc8ab0b250c57`
- **Data (UTC)**: `2026-11-24T13:10:00Z`
