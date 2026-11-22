# Handoff e Parecer F9 — `WP-ROADMAP-CTRLAB-LMI-PERSISTENCE`

- **WorkPackage**: `WP-ROADMAP-CTRLAB-LMI-PERSISTENCE`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `04075f5`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-22T11:36:52Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As alterações da frente produtora `F8` e da auditoria independente `F9` ficaram restritas aos seus respectivos escopos de propriedade (`web/app/`, `web/features/`, `tests/unit/f8/` para `F8`; `tests/e2e/`, `docs/audits/handoffs/`, `PROJECT_STATE.json` para `F9`):

| Arquivo Auditado | Frente | SHA-256 | Papel no Pacote |
|---|---|---|---|
| `web/app/shell.ts` | `F8` | `e5c0373d85b05e90681d438d0f7723be6fedef1f1241162e8b255b89eccf7f13` | Registro de callbacks de persistência LMI (`registerLmiPersistence`), inclusão passiva de `parameters.lmi_state` em `exportCtrlLab()` via `structuredClone` e restauração segura (com `pendingRestoredLmiState` e fallback retrocompatível para `.ctrlab` legado sem `lmi_state`) em `importCtrlLab()`. |
| `web/features/views/lmi_view.ts` | `F8` | `73e9137f628e7c7e5d7c91dda908efce733babdfa3ea823b79275f97a396579a` | Implementação de `exportSerializableState()` e `restoreSerializableState(raw)` com sanitização estrita de tipos (`isPlainObject`, `sanitizeVertexList`, premissas, expressões `h_i(z)`, matrizes generalizadas `Bw`/`Cz`/`Dzu`/`Dzw`, observador TS `dA`/`dC`, `extraIndices`, `currentDsl`) e ressincronização completa de DOM/parser sem `eval` ou `new Function`. |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | `F8` | `93b53631bf6b8fc8eb8c9dde42168663f4d1f483f1dc58a034dfca5257c985c3` | Teste unitário/integrado `WP-ROADMAP-CTRLAB-LMI-PERSISTENCE` executando roundtrip `.ctrlab` via `control_lab.core.rpc` Python real (`cpythonLoader`) entre duas instâncias limpas de `mountControlLabApp`. |
| `tests/e2e/test_ux_refactor_cl_ux_dir_001.py` | `F9` | `edaba1303e8076a9df38a1d7b9954d01e2d3252d71fc6d7097038e2ddf8a9a27` | Adição de `test_ux_phase5_ctrlab_lmi_persistence` em navegador real Chromium contra `web/dist`: comita LQR na Aba 3, configura modo `ts`, edita `A[1]`, `h_1(z)` e `currentDsl` na Aba 6, exporta `.ctrlab` pelo botão da Topbar (`#btn-header-export-ctrlab` -> `#export-modal-download`), valida arquivo passivo via `load_ctrlab` (`code_executed === False`), recarrega UI limpa, importa via `#ctrlab-file-input` e comprova restauração integral da Aba 6. |

Nenhum arquivo de `control_lab/`, `contracts/fixtures/`, `contracts/schemas/` ou `tests/oracles/` foi modificado. Zero ocorrências de `eval` ou `new Function` em `web/app/shell.ts` e `web/features/views/lmi_view.ts`.

---

## 2. Evidência de Execução Independente F9

- **Typecheck e Testes Web**:
  - `npm --prefix web run typecheck`: `PASS` (`0` erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: `PASS` (`148/148` testes aprovados, `0` falhas, `0` skips).
- **Build de Produção**:
  - `npm --prefix web run build`: `PASS` (`control_lab-1.0.0-py3-none-any.whl` e `42` assets locais verificados).
- **Suíte E2E em Navegador Real (Playwright Chromium contra `web/dist`)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_ux_refactor_cl_ux_dir_001.py -v`: `PASS` (`13/13` testes aprovados em `104.84s`, `0` falhas, `0` skips).
- **Integridade de Fixtures Ouro e Governança**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py`: `PASS` (`11` schemas JSON Draft 2020-12 válidos e `7` fixtures ouro íntegras).
  - `python3 scripts/project_governance.py`: `PASS`.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações de `F8` restritas a `web/app/shell.ts`, `web/features/views/lmi_view.ts` e `tests/unit/f8/lmi_dsl_v2.test.ts`; alterações de `F9` restritas a `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`, `docs/audits/handoffs/WP-ROADMAP-CTRLAB-LMI-PERSISTENCE.md` e `PROJECT_STATE.json`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado com `11/11` schemas e `7/7` fixtures ouro intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Exportação e importação `.ctrlab` via `io.export_ctrlab` / `load_ctrlab` retornam `Result`/`RpcResponse` com `diagnostics.code_executed === False` e `hashes_verified === True`. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma tolerância alterada; dados persistidos preservam representação JSON canônica exata das matrizes, expressões e script DSL. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `restoreSerializableState` valida tipos, limites (`polyVerticesCount`, `polyDeltaPct`, `tsRulesCount`) e dimensões sem aceitar payload arbitrário ou executável. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Compatibilidade retroativa com `.ctrlab` legado sem `lmi_state` garantida por guarda `isPlainObject(parameters.lmi_state)` em `shell.ts` e `isPlainObject(raw)` em `lmi_view.ts`. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Payload `.ctrlab` serializado em JSON puro (`structuredClone`) e transferido via RPC binário padrão; zero `eval` / `new Function` em `shell.ts` e `lmi_view.ts`. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | `#btn-header-export-ctrlab` respeita bloqueio R-23 pré-commit e libera após `commit-lqr`; suíte E2E `13/13` aprovada em Chromium real. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente à camada de persistência; suíte E2E LMI 5D continua `PASS`. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `148/148` (`web --scope all`), `13/13` (`E2E Chromium`) e `verify_fixtures.py` aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit Base**: `04075f50fbce61ae6c17faa14b227ae0db7a5c2a`
- **Data (UTC)**: `2026-11-22T11:36:52Z`
