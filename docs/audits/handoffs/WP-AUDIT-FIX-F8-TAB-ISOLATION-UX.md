# Handoff e Parecer F9 — `WP-AUDIT-FIX-F8-TAB-ISOLATION-UX`

- **WorkPackage**: `WP-AUDIT-FIX-F8-TAB-ISOLATION-UX`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `a6f2b086dc6805b4b6637e6d1967a1203edc8fbc`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-19T11:51:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações da frente produtora `F8` ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/app/`, `web/features/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/app/main.ts` | `56d1be46e7f3b67d0eb20c74daab9d411563f46073696a15bdd7294590fb2bce` | Isolamento visual estrito por aba (ocultação de `.lqr-interactive-bar`, `#pvm-export-options`, `#lqr-k-display`, `#lqr-diagnostics-panel`, `#time-chart-slot`, `#experiments-compare-panel` quando `activeTab !== "statespace"` e visibilidade de `#pz-chart-slot` / `#pz-table-slot` apenas em `identification` e `statespace`), sincronização `location.hash` (`#tab=<id>`) com restauração na inicialização (`statespace` como default sem hash), editor matricial numérico interativo (`A, B, C, D, dt, Q, R, x0` + presets clássicos) na Aba 3 e construtor guiado para `TransferFunction` / `StateSpace` em `#typed-workspace-panel` mantendo campos JSON anotados. |
| `web/app/styles.css` | `61065bd882aed5b8311a65e7c152bce77850e03f5dcecbe0fe3ae1086c8b736f` | Regras CSS de isolamento de painéis por aba, layout dos editores matriciais/numéricos e anotações de formato JSON preservando contraste WCAG 2.2 AA e responsividade mobile. |
| `tests/unit/f8/tab_isolation_ux.test.ts` | `96443937a4e5a8482b9cd3145713e9fcdff8be6901cfd0b823013622f82b0e57` | Suíte unitária F8 cobrindo isolamento estrito por aba, ordenação de `#typed-workspace-panel`, persistência de aba via `location.hash` (`#tab=...`), editor matricial LQR, presets, hints JSON e construtor guiado `TransferFunction`. |

Nenhum arquivo em `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/` ou nos diretórios Python (`control_lab/`) foi modificado pelo produtor. Os checksums SHA-256 das 7 fixtures ouro permanecem intactos.

Além disso, a frente independente `F9` atualizou `tests/e2e/test_id_siso_verticals.py` para:
- Na função `test_siso_mimo_rejection_and_isolation`, navegar explicitamente para `[data-tab-id="statespace"]` antes de interagir com `[data-action="commit-lqr"]` e `#lqr-q-slider`.
- Adicionar `test_tab_isolation_and_url_hash_persistence` verificando em navegador real (Playwright/Chromium sobre build de produção) que na Aba 1 (`identification`) `#identification-workspace-panel` está visível e `#statespace-workspace-panel` está oculto (`not is_visible()`), na Aba 2 (`siso_frequency`) `#siso-workspace-panel` está visível e `#statespace-workspace-panel` está oculto (`not is_visible()`), e que a troca de aba atualiza `location.hash` (`#tab=...`) e a recarga com `#tab=identification` restaura diretamente a Aba 1.

---

## 2. Evidência de Execução Independente F9

- **Typecheck e Testes Web Completos**:
  - `npm --prefix web run typecheck`: `PASS` (33 arquivos TS, 0 erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" PYTHON=/home/antigravity/.venv/bin/python node scripts/run_web_tests.mjs --scope all`: `PASS` (`106/106` testes aprovados em 10 arquivos, `0` falhas, `0` skips).
- **Build de Produção**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" PYTHON=/home/antigravity/.venv/bin/python npm --prefix web run build`: `PASS` (Vite build completa, wheel `control_lab-1.0.0-py3-none-any.whl` empacotada, 42 assets locais inventariados).
- **Suíte E2E em Navegador Real (Chromium + Pyodide/Wasm)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" /home/antigravity/.venv/bin/pytest tests/e2e/ -v`: `PASS` (`18/18` testes aprovados em `271.96s`, incluindo `test_siso_mimo_rejection_and_isolation` e `test_tab_isolation_and_url_hash_persistence`).
- **Integridade de Fixtures Ouro e Schemas**:
  - `/home/antigravity/.venv/bin/python scripts/verify_fixtures.py`: `PASS` (11 schemas JSON Draft 2020-12 válidos e 7 fixtures ouro íntegras).
  - `(cd contracts/fixtures && sha256sum -c checksums.sha256)`: `PASS` (`7/7` fixtures OK).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Modificações da F8 restritas a `web/app/main.ts`, `web/app/styles.css` e `tests/unit/f8/tab_isolation_ux.test.ts` (mais inclusão do WP em `PROJECT_STATE.json`). | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `verify_fixtures.py` e `sha256sum -c checksums.sha256` aprovados com todas as 7 fixtures intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Nenhuma alteração no protocolo RPC; todas as chamadas continuam usando envelopes canônicos RPC v1.0. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Editores matriciais e construtores enviam matrizes/polinômios canônicos ao motor Python sem cálculo científico duplicado nem relaxamento de tolerâncias. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Validação estrita mantida nos construtores de `StateSpace` e `TransferFunction` e nos workspaces de cada aba. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Coberto na suíte unitária e E2E (rejeição MIMO na Aba 2, validação de dimensões e erros tipados). | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Suíte F7 (`106/106` web tests) e E2E (`18/18`) aprovadas com zero vazamentos de `PyProxy`. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Isolamento estrito de painéis por aba, `location.hash` sincronizado, navegação por teclado, `aria-selected`, bloqueio de exportação em preview e responsividade mobile validados em DOM e E2E real. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente à frente F8; sem interferência nas interfaces de otimização. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `106/106` testes web e `18/18` testes E2E aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Assinatura da Auditoria Independente F9

- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `a6f2b086dc6805b4b6637e6d1967a1203edc8fbc`
- **Data (UTC)**: `2026-11-19T11:51:00Z`
- **Parecer F9**: accepted
