# Handoff e Parecer F9 — `WP-ROADMAP-SW-FIREFOX-CI`

- **WorkPackage**: `WP-ROADMAP-SW-FIREFOX-CI`
- **Frente Produtora**: `F7 (f7-worker-bridge)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `0665965ceb97df3acd8c55c157f6e0f2b6f65981`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-22T12:39:41Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações da frente produtora ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/app/`, `web/worker/`, `tests/e2e/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/worker/service_worker.ts` | `1b1b298d69d6efc3d563b4e70a6abb49aed2067371a258c6ef6ef1d6ad9da36d` | Adição de `hasPendingPromotion(storage)` em `ServiceWorkerController` e `ensureActivatedIfNeeded()` em `attachServiceWorker(scope)`. A promoção pendente só ocorre quando `!reg.installing && !reg.waiting && reg.active?.state === "activated"`, preservando o isolamento atômico de clientes antigos e executando `controller.activate(scope.caches)` com verificação integral de `SHA-256` e tamanho de cada ativo antes de atualizar o ponteiro `active`. Zero mocks ou bypasses. |

Nenhum arquivo em `contracts/fixtures/`, `contracts/schemas/`, `control_lab/`, `web/features/` ou `web/charts/` foi modificado neste pacote.

---

## 2. Evidência de Execução Independente F9

- **Typecheck, Testes Unitários Web e Build**:
  - `npm --prefix web run typecheck`: `PASS` (`0` erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: `PASS` (`148/148` testes aprovados em `20` arquivos, `0` falhas, `0` skips).
  - `npm --prefix web run build`: `PASS` (`42` assets locais verificados).
- **Suíte E2E de Service Worker em Dois Navegadores Reais (Playwright contra `web/dist`)**:
  - Chromium (`PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_sw_release_update.py -v`): `PASS` (`1/1` aprovado em `106.39s`).
  - Firefox (`CONTROLLAB_BROWSER=firefox CONTROLLAB_FIREFOX=/home/antigravity/.cache/ms-playwright/firefox-1538/firefox/firefox PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_sw_release_update.py -v`): `PASS` (`1/1` aprovado em `312.46s`).
- **Integridade de Fixtures Ouro, Schemas e Governança**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py`: `PASS` (`11` schemas JSON Draft 2020-12 válidos e `7` fixtures ouro íntegras).
  - `python3 scripts/project_governance.py`: `PASS` (`{"accepted": 88, "corrective_packages": 24, "work_packages": 88}`).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alteração produtora restrita a `web/worker/service_worker.ts` (`allowed_paths`: `web/app/`, `web/worker/`, `tests/e2e/`); artefatos F9 restritos a `docs/audits/handoffs/WP-ROADMAP-SW-FIREFOX-CI.md` e `PROJECT_STATE.json`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado com `11/11` schemas e `7/7` fixtures ouro intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Não altera contratos científicos; suíte unitária web (`148/148`) e E2E SW em Chromium e Firefox validam integridade integral. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma tolerância numérica ou oráculo científico foi alterado. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `ServiceWorkerController` preserva rejeição fechada (`ControlLabBridgeError("IMPORT_UNTRUSTED_CODE", ...)` e `"SOLVER_UNAVAILABLE"`) em qualquer divergência de manifesto, tamanho, `SHA-256` ou dependência Pyodide. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | `hasPendingPromotion` e `ensureActivatedIfNeeded()` retornam sem promover quando `reg.installing`, `reg.waiting` ou `reg.active?.state !== "activated"`, preservando isolamento de clientes antigos; `activate()` valida `verifyRelease` completo antes de mover o ponteiro `active`. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | `148/148` testes unitários web e testes E2E em Chromium e Firefox aprovados sem vazamentos de `PyProxy` nem chamadas externas. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Não aplicável diretamente (`F7`), sem regressões na suíte `F8` (`148/148` testes unitários web aprovados). | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente (`F7`), sem alterações em `F6`. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `148/148` testes unitários web (`--scope all`) e `T-PWA-01` (`test_sw_release_update.py`) em Chromium e Firefox aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Notas de Auditoria

- Com a conclusão e aprovação de `WP-ROADMAP-SW-FIREFOX-CI`, todos os `88` WorkPackages do repositório encontram-se no estado `ACCEPTED_BY_F9`.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `0665965ceb97df3acd8c55c157f6e0f2b6f65981`
- **Data (UTC)**: `2026-11-22T12:39:41Z`
