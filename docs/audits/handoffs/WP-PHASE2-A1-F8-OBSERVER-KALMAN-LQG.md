# Handoff e Parecer F9 — `WP-PHASE2-A1-F8-OBSERVER-KALMAN-LQG`

- **WorkPackage**: `WP-PHASE2-A1-F8-OBSERVER-KALMAN-LQG`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `8bfb994fab4a4e22a17531c714535dfb7bd93804`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-21T16:39:27Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações deste pacote ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/features/views/statespace_view.ts` | `b13ff8d8beffaf0b8f689978b4d51d63f9bb07ffe98840c0d43b164726613548` | Quadro Observador de Luenberger / Filtro de Kalman / LQG na Aba 3 (`#btn-obs-synthesize`, `#btn-obs-simulate`, `#btn-obs-register-ctrl`, `#obs-results-summary`, `#obs-sim-chart-slot`, tabela acessível e polos no mapa P-Z). |
| `web/app/shell.ts` | `54779176db2bd6cf985b00740ee16fe1b893ab891dfb8f4b29adff54eac4a1ba` | Integração do controlador LQG ativo na exportação `.pvm` e ciclo de renderização da Aba 3. |
| `web/features/typed_workspace.ts` | `d6dbdb874e29672c77d9dd3e2b577942fba3f4ac89642ce8ec0d7118eeda7113` | Suporte à resolução de referência para `statespace.design_kalman`, `statespace.design_lqg`, `statespace.design_observer` e `statespace.simulate_observer` + registro de `DynamicController`. |
| `web/app/workspace_dock.ts` | `cddae04b61c9a8206b598f9a0ee323fb806d6704cdfb454f6bf78883192cbd66` | Resumo legível no Workspace Dock para `DynamicController` registrado pela bancada LQG. |
| `tests/unit/f8/observer_kalman_lqg.test.ts` | `1e5a69641f303f954b7aa6af36790824998ae47b170f1b0ca3a19416b5466f6b` | Suíte unitária validando síntese Kalman/LQG, Luenberger, simulação $x(t)$ vs $\hat{x}(t)$ e registro no Workspace Dock com motor Python real. |

Nenhum arquivo em `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/` ou `control_lab/` foi alterado pela frente produtora.

---

## 2. Evidência de Execução Independente F9

- **Typecheck e Testes Web**:
  - `npm --prefix web run typecheck`: `PASS` (`49` arquivos TypeScript, `0` erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: `PASS` (`130/130` testes aprovados em `17` arquivos, `0` falhas, `0` skips).
- **Build de Produção**:
  - `npm --prefix web run build`: `PASS` (wheel `control_lab-1.0.0-py3-none-any.whl` construída e `42` assets locais verificados).
- **Validação em Navegador Real (Playwright Chromium contra `web/dist`)**:
  - Seção Tab 3 de `test_ux_phase2_lqg_observer_mimo_decoupler_and_hinf` aprovada ponta a ponta: `#btn-obs-synthesize` preencheu `#obs-results-summary` com `Ganho do Observador L:` e `Ganho de Regulação K:`, `#btn-obs-simulate` renderizou `#obs-sim-chart-slot svg` ($x(t)$ vs $\hat{x}(t)$) e `#btn-obs-register-ctrl` registrou `DynamicController` no `#workspace-dock-aside`.
- **Integridade de Fixtures Ouro e Schemas**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py`: `PASS`.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações restritas exclusivamente a `web/features/views/statespace_view.ts`, `web/app/{shell,workspace_dock}.ts`, `web/features/typed_workspace.ts` e `tests/unit/f8/observer_kalman_lqg.test.ts`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado com `11/11` schemas e `7/7` fixtures ouro intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | As chamadas `statespace.design_kalman`, `statespace.design_lqg`, `statespace.design_observer` e `statespace.simulate_observer` consomem envelopes `RpcResponse` v1.0 completos do motor Python. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma rotina numérica Python foi modificada; ganhos $K, L$ e polos são calculados no motor Python. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Validação de dimensões de $\hat{x}(0)$, polos e escalas $Q_n/R_n$ com erros tipados antes do envio RPC. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Cobertos pelos testes unitários em `observer_kalman_lqg.test.ts` e pela suíte `130/130`. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | `130/130` testes web e execução Pyodide Wasm em Chromium real sem vazamento de `PyProxy`. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Botões com `.touch-control`, regiões `role="region"` e tabela acessível `#obs-sim-table-slot`, bloqueio `R-23` preservado. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente à Aba 3 (`F8`). | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `130/130` testes unitários web aprovados com `0` falhas e `0` skips (`T-UI-01`, `T-SS-01`). | CONFORME |

---

## 4. Notas de Auditoria

- Bancada de Observador / Kalman / LQG na Aba 3 aprovada integralmente nos testes unitários (`observer_kalman_lqg.test.ts`) e no fluxo real em Chromium com Pyodide Wasm.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `8bfb994fab4a4e22a17531c714535dfb7bd93804`
- **Data (UTC)**: `2026-11-21T16:39:27Z`
