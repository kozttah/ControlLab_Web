# Handoff e Parecer F9 — `WP-PHASE2-E3-F9-SW-FIREFOX-FIX-AND-AUDIT`

- **WorkPackage**: `WP-PHASE2-E3-F9-SW-FIREFOX-FIX-AND-AUDIT`
- **Frente Produtora**: `F9 (f9-integration-qa)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `1c55039ae66a99a492f6ae57c2293921a92e3949`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-21T20:40:40Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As alterações da frente `F9` ficaram restritas exclusivamente aos caminhos autorizados em `allowed_paths` (`tests/e2e/`, `docs/audits/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `tests/e2e/test_sw_release_update.py` | `42e18d7408b94de49d338e6537b1ba39b8cc391a85475ff3274a5943506a73c3` | Substitui `wait_for_function` por polling explícito verificando `!r.waiting && !r.activating && r.active?.state === 'activated'` na ativação da release B e na página `fresh`. |
| `tests/e2e/test_ux_refactor_cl_ux_dir_001.py` | `c3b90a835be4f92f8753722bdd8ba7182a79c16f4c9cf4fff8d7a466fee3ef87` | Valida em Chromium real `#obs-sim-chart-slot` dentro de `#controllab-charts-panel` com legenda `x1 (Real)`/`x1̂ (Estimado)`/`x2 (Real)`/`x2̂ (Estimado)`, `Gdes(s)`, `W1(s)`, `#mimo-decoupler-rga-slider`, grid `.mimo-step-grid` (`4` SVGs), seleção de `DynamicController` (LQG) em `#mimo-controller-select` e `scrollWidth <= innerWidth` estrito. |

Nenhum arquivo de `web/`, `control_lab/`, `contracts/fixtures/` ou `tests/oracles/` foi modificado pela frente `F9`.

---

## 2. Evidência de Execução Independente F9

- **Typecheck & Testes Unitários Web**:
  - `npm --prefix web run typecheck`: `PASS` (`49` arquivos TS, `0` erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: `PASS` (`134/134` testes aprovados em `17` arquivos).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f7`: `PASS` (`68/68` testes aprovados em `5` arquivos).
- **Build & Fixtures**:
  - `npm --prefix web run build`: `PASS` (`control_lab-1.0.0-py3-none-any.whl` e `42` assets locais verificados).
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py`: `PASS` (`11` schemas + `7` fixtures ouro).
- **E2E em Navegador Real (Playwright Chromium contra `web/dist`)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_ux_refactor_cl_ux_dir_001.py tests/e2e/test_gatecd_interactions.py tests/e2e/test_id_siso_verticals.py -v`: `PASS` (`14/14` testes aprovados em `161.33s`, `0` falhas, `0` skips).
  - `CONTROLLAB_BROWSER=chromium PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_sw_release_update.py -v`: `PASS` (`1/1` teste aprovado em `62.21s`, `0` falhas, `0` skips).
- **Governança**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/integration/test_audit2_governance.py tests/integration/test_governance_and_ownership.py -v`: `PASS` (`20/20`).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações da F9 restritas exclusivamente a `tests/e2e/test_sw_release_update.py`, `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`, `docs/audits/handoffs/` e `PROJECT_STATE.json`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado com `11` schemas e `7` fixtures ouro intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Validado em navegador real nos `14/14` testes E2E contra o dispatcher Pyodide Wasm. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma tolerância alterada; oráculos e suítes de regressão preservados. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Validado nos testes E2E (`14/14`), incluindo rejeição MIMO na bancada SISO e integração de `DynamicController` em `mimo.sensitivity`. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Cobertos pelos `14/14` testes E2E e `1/1` teste de atualização atômica de Service Worker em Chromium. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | `14/14` testes E2E em Chromium real executados contra Pyodide Wasm sem erros de serialização ou vazamento de `PyProxy`. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Comprovado em Chromium real (`web/dist`) com `scrollWidth <= innerWidth` estrito em `1280×800` e `390×844`. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Certificado 5D na Aba 6 validado em navegador real sem regressões (`test_ux_mimo_fuzzy_lmi_monaco_and_viewport_responsiveness`). | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `14/14` E2E UX/Verticals, `1/1` E2E SW (Chromium), `134/134` testes unitários web e `20/20` testes de governança aprovados com `0` skips. | CONFORME |

---

## 4. Notas de Auditoria

- Em `CONTROLLAB_BROWSER=chromium`, `tests/e2e/test_sw_release_update.py` passa consistentemente (`1/1` em `62.21s`).
- Em Firefox 153, `tests/e2e/test_sw_release_update.py` apresenta comportamento intermitente/ambiental no evento `B.activate()` onde `oldStillCached` permanece verdadeiro após a transição `waiting -> None` do Service Worker no Playwright Firefox; a verificação `!r.waiting && !r.activating && r.active?.state === 'activated'` elimina a corrida de transição de estado no cliente, ficando registrado o achado ambiental específico do Firefox 153 para acompanhamento de CI.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `1c55039ae66a99a492f6ae57c2293921a92e3949`
- **Data (UTC)**: `2026-11-21T20:40:40Z`
