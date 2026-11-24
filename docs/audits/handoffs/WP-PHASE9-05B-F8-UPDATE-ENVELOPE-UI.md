# Handoff e Parecer F9 — `WP-PHASE9-05B-F8-UPDATE-ENVELOPE-UI`

- **WorkPackage**: `WP-PHASE9-05B-F8-UPDATE-ENVELOPE-UI`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base**: `f97551017443779a613032f4fc8cc8ab0b250c57`
- **ADR / Referência**: `ADR-010`, `ADR-015` & `CL-UX-DIR-001`
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T13:10:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Escopo F8 (`web/features/views/lmi_view.ts`, `tests/unit/f8/lmi_dsl_v2.test.ts`) verificado via `git status -s` e `git diff --stat`: nenhuma alteração fora de `allowed_paths`, zero uso de `eval` ou `new Function`, zero imports Python/Node proibidos no frontend e sincronização exata com `control_lab/optimization/backends/native.py`.

| Artefato F8 | SHA-256 | Papel na Entrega |
|---|---|---|
| `web/features/views/lmi_view.ts` | `6e76419b83f5a65f9943a9e9670d5313cf57d2601bda9ec35d6b1f94a7b4cb44` | Atualização de `BROWSER_ENVELOPE` para `{ fast_max_variables: 1792, max_variables: 3072, max_block_dimension: 96, max_cone_entries: 131072 }` e limiares da faixa rápida na Aba 6 (`n <= 56` geral, `n <= 44` $\mathcal{H}_\infty$, `expandedBlockCount <= 64`). |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | `f1fe51ac0ac678ed44d9b40acfb43edd2949254cfb9e12eb6f0e505c0a93c6a8` | Testes unitários cobrindo a faixa rápida (`n=56` estabilização, `n=44` $\mathcal{H}_\infty$, `64` blocos LMI), faixa estendida (`65` blocos, `n=60` geral, `n=46` $\mathcal{H}_\infty$ com aviso de execução longa e botão `Cancelar`) e teto rígido (`n=80`, `3.240 > 3.072` variáveis com recomendação `Exportar CVXPY / YALMIP`). |

---

## 2. Evidências Executadas pela F9

| Verificação Independente | Resultado | Status |
|---|---|---|
| `npm --prefix web run typecheck` | `tsc -p tsconfig.json --noEmit` (`exit 0`) | PASS |
| `npm --prefix web run build` | Bundle `web/dist/` + `42` local assets verificados por SHA-256 (`exit 0`) | PASS |
| `node scripts/run_web_tests.mjs --scope all` | **159 passed, 0 failed, 0 skipped** (`21` arquivos de teste, `exit 0`) | PASS |
| Real Chromium Wasm + E2E (`tests/wasm/test_real_runtime.py` + `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`) | **21 passed, 0 failed, 0 skipped** em `153.91s` (`exit 0`) | PASS |

---

## 3. Coerência de Envelope Backend (F6) ↔ Interface (F8)

| Parâmetro | `native.py` (`F6`) | `lmi_view.ts` (`F8`) | Comportamento na Aba 6 |
|---|---|---|---|
| `fast_max_variables` | `1792` | `1792` | Sem banner (`hidden`) para `n <= 56` geral, `n <= 44` $\mathcal{H}_\infty$ e `<= 64` blocos |
| `max_variables` | `3072` | `3072` | Banner `.lmi-envelope-extended` em `1793..3072` com log iterativo e botão `Cancelar` |
| `max_block_dimension` | `96` | `96` | Banner `.lmi-envelope-hard-limit` acima de `96` com atalho `Exportar CVXPY / YALMIP` |
| `max_cone_entries` | `131072` | `131072` | Banner `.lmi-envelope-hard-limit` acima de `131072` com atalho `Exportar CVXPY / YALMIP` |

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `BROWSER_ENVELOPE` em `lmi_view.ts` coincide exatamente com `optimization.capabilities` no Worker Pyodide real (`test_real_runtime.py`). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Banners `.lmi-envelope-extended` e `.lmi-envelope-hard-limit`, log de iterações, botão `Cancelar` e painel de certificado 5D validados. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Estimativa de variáveis e transições exatas de fronteira (`64 -> 65` blocos, `n=56 -> 60`, `n=44 -> 46` $\mathcal{H}_\infty$, `n=80`) cobertas em `lmi_dsl_v2.test.ts`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Confrontado em navegador Chromium real (`15` testes E2E + `6` testes Wasm) contra o motor Python/Pyodide empacotado em `web/dist/`. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações restritas a `web/features/views/lmi_view.ts` e `tests/unit/f8/lmi_dsl_v2.test.ts`; zero mutação de fixtures ouro. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Validado em Node (`159 passed`) e no bundle real Chromium + Pyodide Wasm (`21 passed`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Contratos JSON intactos (`verify_fixtures.py` PASS em todos os 11 schemas). | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, resultados de build (`42` assets) e suítes Web/E2E anexados neste parecer. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Selos `stable`/`beta`/`experimental` e isolamento do solver educacional preservados (`test_tool_descriptor` PASS). | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Banner de limite rígido informa explicitamente `max_variables=3072`, `max_block_dimension=96`, `max_cone_entries=131072` e orienta `Exportar CVXPY / YALMIP`. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `f97551017443779a613032f4fc8cc8ab0b250c57`
- **Data (UTC)**: `2026-11-24T13:10:00Z`
