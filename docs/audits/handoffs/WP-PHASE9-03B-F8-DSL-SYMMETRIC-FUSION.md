# Handoff e Parecer F9 — `WP-PHASE9-03B-F8-DSL-SYMMETRIC-FUSION`

- **WorkPackage**: `WP-PHASE9-03B-F8-DSL-SYMMETRIC-FUSION`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base**: `f776cfb4c6f9a2b295e3e572794c32329cbc2b0a`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`) e `CL-UX-DIR-001`
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T04:56:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Escopo F8 (`web/features/`, `tests/unit/f8/`) verificado via `git status -s` e `git diff --stat`: nenhuma alteração fora de `allowed_paths`, zero uso de `eval` ou `new Function`, zero bypass de validação.

| Artefato F8 | SHA-256 | Papel na Entrega |
|---|---|---|
| `web/features/views/lmi_dsl_compiler.ts` | `92ab9bdf0c109923feafb562ae90d52aac038bacb3d13fc96457a768bda3633a` | Detecção e fusão automática de pares simétricos em somas duplas politópicas/TS (`Upsilon_ij + Upsilon_ji < 0`, preservando blocos assimétricos sem fusão indevida) com `fusionStats` (`originalBlocks`, `fusedBlocks`, `eliminatedSymmetricPairs`). |
| `web/features/views/lmi_dsl_parser.ts` | `98c008f6cb1ec48a5e003a26ee0f62880b8dfb4f433cc0b9dec08814282236ce` | Suporte completo a múltiplas diretivas `recover` customizadas e metadados de fusão simétrica para exportadores CVXPY/YALMIP. |
| `web/features/views/lmi_recover_eval.ts` | `60232ed976d811b2fadb08607bac448e4e9b87b395b5dd90403d15b1697da0ae` | Avaliador seguro de expressões matriciais/escalares `recover` (`inv`, `trace`, multiplicação/adição, indexação `for i`) sem `eval` ou `new Function`. |
| `web/features/views/lmi_view.ts` | `913453fc9f9ff4bf37612472de532ba50da549c92448657b52986431fff3c431` | Badge `#lmi-fusion-badge` de fusão simétrica na Aba 6 e renderização genérica de todas as diretivas `recover` customizadas em `#lmi-recovered-gain`. |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | `6ac81dbb4a4d5270afad5a6bb6ba4f026820a8cf759e57d2f41d2576acdc3651` | Testes unitários F8 cobrindo fusão simétrica (`N_r=3, 4`), guarda contra fusão assimétrica, avaliação segura de `recover`, ausência de `eval`/`new Function` e solução validada via CPython. |

---

## 2. Evidências Executadas pela F9

| Verificação Independente | Resultado | Status |
|---|---|---|
| Auditoria estática (`eval(`, `new Function`, ownership F8) | Zero ocorrências proibidas; alterações restritas a `web/features/` e `tests/unit/f8/` | PASS |
| `npm --prefix web run typecheck` | Exit 0 (0 erros TypeScript) | PASS |
| `npm --prefix web run build` | Exit 0 (bundle + wheel `control_lab-1.0.0-py3-none-any.whl` + 42 assets locais íntegros) | PASS |
| `node scripts/run_web_tests.mjs --scope all` | **159 passed, 0 failed, 0 skipped** em 21 arquivos de teste (`exit 0`) | PASS |
| E2E Chromium + Pyodide real (`test_ux_phase9_cycle3_generic_recover_and_symmetric_fusion` em `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`) | **PASS** — `P = inv(Q)`, `K = Y * inv(Q)` e `trP = trace(P)` renderizados visivelmente com valores numéricos finitos em `#lmi-recovered-gain`; `#lmi-fusion-badge` exibe `1 par simétrico fundido (5 → 4)` e resolve com `validated_dual` em Pyodide Wasm | PASS |

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Fluxo completo DSL -> compilador COO -> Worker/Bridge F7 -> `optimization.solve` -> `verify` 5D validado em Node e Chromium + Pyodide real. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `#lmi-fusion-badge`, `#lmi-certificate-alert` e `#lmi-recovered-gain` exibem contagem exata de blocos fundidos, status de auditoria 5D e avisos explícitos se uma expressão `recover` falhar. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Fusão simétrica verifica equivalência algébrica (`(i,j)` vs `(j,i)`) e bloqueia fusão de blocos assimétricos; `recover` valida valores finitos de `P`, `K` e `trP`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Teste E2E independente da F9 executa DSL real na Aba 6 em Chromium + Pyodide Wasm e audita o DOM renderizado e o certificado `validated_dual`. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações restritas a `web/features/` e `tests/unit/f8/`; zero edição em `control_lab/`, `contracts/` ou testes F9. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | `run_web_tests.mjs --scope all` (**159 passed**) via CPython RPC e suite Chromium + Pyodide Wasm (**20 passed**) aprovados integralmente. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma quebra de schema; `verify_fixtures.py` valida 11 schemas Draft 2020-12 sem regressão. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, resultados de typecheck/build, contagens de testes e evidências E2E registrados. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Selos de maturidade e classificação experimental na UI permanecem inalterados. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Expressões `recover` não avaliáveis exibem `aviso na recuperação` explícito em `role="status"` sem silenciar erros. | CONFORME |

---

## 4. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Data (UTC)**: `2026-11-24T04:56:00Z`
