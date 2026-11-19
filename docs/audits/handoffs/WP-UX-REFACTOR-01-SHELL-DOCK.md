# Handoff e Parecer F9 — `WP-UX-REFACTOR-01-SHELL-DOCK`

- **WorkPackage**: `WP-UX-REFACTOR-01-SHELL-DOCK`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `52212db1a6c9410c57b1b97fd8eed471361f3086`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-19T15:22:06Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações da frente produtora `F8` ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/app/main.ts` | `c23f26ac6fdf77db3c6988346196a23a3bf56880b09f241fa84bd4623678672c` | Integração do App Shell de 3 zonas (`.app-workbench-shell` com `WorkspaceDockController`, `#controllab-main` e `InspectorDrawerController`), título editável de projeto no cabeçalho, classe `.tab-identification` e aplicação do Dicionário de Tradução Semântica (`CL-UX-DIR-001` Seção 2) preservando `data-action`, `#id` e invariante R-23. |
| `web/app/styles.css` | `06e88c4ebca7aaf2c43fbc988ee817648adf10dcf88f80c82b375dcffd567adf` | Layout responsivo 3-zonas (`.app-workbench-shell`, `.dock-collapsed`, `.inspector-open`), `.controllab-main.tab-identification` em `1fr`, ajuste de `.workspace-two-col` (`minmax(250px, 0.85fr) minmax(360px, 1.35fr)`) com empilhamento em `<= 1120px` e `<= 1400px` (com `.inspector-open`), `statespace` empilhado em `<= 1380px` (com `.inspector-open`), alvos `>= 44×44px` e contraste WCAG 2.2 AA (`standard_aa` e `high_contrast`). |
| `web/app/workspace_dock.ts` | `58f4cffb51c948ef80b7fabaeec73eba7362d204ecda571f58e9c17d1f759c2d` | Dock esquerdo persistente e recolhível (`#workspace-dock-aside`) agrupando *Séries Temporais (Dados)*, *Plantas & Modelos* e *Controladores Projetados*, com resumos matemáticos (`G(s)`, `n×m SS`, `dt`), roteamento 1-clique (`→ Identificação`, `→ SISO`, `→ SS/LQR`) e modal guiado `+ Novo` (TF `num/den`, StateSpace matricial, Dataset CSV). |
| `web/app/inspector_drawer.ts` | `5db5b8c929fc616fe35afa68e5ba516d3bb4dfaa65a056cfc00f4b089bf52532` | Gaveta recolhível direita (`#inspector-drawer`) fechada por padrão (`hidden`), concentrando telemetria científica R-27 (`proj_rev`, `model_rev`, `rCARE`, `sym(P)`, `J*`, `seed`, backend, `T_warm`, hashes SHA-256) e visualizador/copiador de payload JSON canônico. |
| `tests/unit/f8/shell_dock_ux.test.ts` | `fed36176b4c13b0ce0274573d76d32dceaf591ccd26c22d43450b3b55f92ff52` | Suíte unitária F8 verificando layout 3-zonas, categorias do Workspace Dock, roteamento 1-clique, `.tab-identification`, modal guiado `+ Novo` (TF, SS, CSV), Inspetor R-27 oculto por padrão, dicionário semântico e invariante R-23. |

Nenhum arquivo em `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/` ou nos diretórios Python (`control_lab/`) foi modificado pelo produtor. Os checksums SHA-256 das 7 fixtures ouro permanecem intactos.

---

## 2. Evidência de Execução Independente F9

- **Typecheck e Testes Web**:
  - `npm --prefix web run typecheck`: `PASS` (`39` arquivos incluídos pelo `tsconfig.json`, `0` erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f8`: `PASS` (`45/45` testes aprovados em `7` arquivos, `0` falhas, `0` skips).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: `PASS` (`111/111` testes aprovados em `12` arquivos, `0` falhas, `0` skips).
- **Build de Produção**:
  - `npm --prefix web run build`: `PASS` (Vite build completa, wheel `control_lab-1.0.0-py3-none-any.whl` empacotada, `42` assets locais verificados).
- **Suíte E2E em Navegador Real (Chromium + Firefox + Pyodide/Wasm)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_gatecd_interactions.py tests/e2e/test_id_siso_verticals.py -v` (Chromium `151.0.7922.34`): `PASS` (`7/7` testes aprovados em `81.89s`).
  - `CONTROLLAB_BROWSER=firefox PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_gatecd_interactions.py -v` (Firefox `153.0`): `PASS` (`2/2` testes aprovados em `111.36s`).
  - Verificação Playwright multi-viewport (`1100×800`, `1280×800` e `390×844`, com `#inspector-drawer` aberto e fechado, em **Chromium** e **Firefox**): `PASS` (`scrollWidth <= innerWidth` em todos os cenários; `.workspace-results-col` e `#pz-chart-slot` com largura `>= 372 px` em `1100×800` e `>= 473 px` em `1280×800`; alvos de toque `>= 44×44 px` no dock/header/modal; restauração de foco via `Escape` no modal `+ Novo` confirmada).
- **Integridade de Fixtures Ouro e Schemas**:
  - `/home/antigravity/.venv/bin/python scripts/verify_fixtures.py`: `PASS` (`11` schemas JSON Draft 2020-12 válidos e `7` fixtures ouro íntegras).
  - `(cd contracts/fixtures && sha256sum -c checksums.sha256)`: `PASS` (`7/7` fixtures OK).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Modificações da F8 restritas exclusivamente a `web/app/main.ts`, `web/app/styles.css`, `web/app/workspace_dock.ts`, `web/app/inspector_drawer.ts` e `tests/unit/f8/shell_dock_ux.test.ts` (além do registro F9 em `docs/audits/handoffs/` e `PROJECT_STATE.json`). | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `verify_fixtures.py` e `sha256sum -c checksums.sha256` aprovados com todas as `7/7` fixtures e `11` schemas intactos. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Nenhuma alteração no protocolo RPC; modal `+ Novo` e roteamentos do `WorkspaceDockController` usam exclusivamente `TypedObjectWorkspace`, `IdentificationWorkspace` e `ControlLabShell` sobre envelopes canônicos RPC v1.0. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Sem importação Python nem duplicação de síntese numérica em `workspace_dock.ts` ou `inspector_drawer.ts`; apenas formatação de exibição e delegação integral ao motor científico Python. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Validadores de polinômio/matriz/`dt` no modal `+ Novo` lançam `ControlLabBridgeError("VALIDATION_ERROR", ...)` e a validação canônica completa permanece no `TypedObjectWorkspace` e no motor Python. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Coberto na suíte E2E real (dataset constante T-ID-02 em `test_identification_vertical_dom_dataset_to_arx_and_subspace`, erro `DIMENSION_MISMATCH` em `test_keyboard_mobile_dimensions_and_temporal_x_u_dom`, rejeição MIMO e bloqueio de exportação R-23). | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Suíte completa `F7+F8` (`111/111` testes web) e E2E reais em Chromium (`7/7`) e Firefox (`2/2`) aprovadas sem vazamentos de `PyProxy`. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Layout 3-zonas, Workspace Dock recolhível, Inspetor R-27 oculto por padrão, dicionário semântico, contraste WCAG 2.2 AA, alvos `>= 44 px`, restauração de foco no modal `+ Novo`, bloqueio R-23 e responsividade sem overflow em `1100×800`, `1280×800` e `390×844` validados em Chromium e Firefox. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente à frente F8; sem interferência nas interfaces de otimização. | N/A |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `45/45` (`--scope f8`), `111/111` (`--scope all`), `7/7` E2E Chromium e `2/2` E2E Firefox aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Notas de Auditoria

- A rodada inicial de auditoria F9 identificou colapso de largura (`0 px`) de `.workspace-results-col` na Aba 1 (`identification`) em `1100×800` e `50.7 px` em `1280×800`, tendo emitido `changes_requested`. Após a correção F8 (`.tab-identification` em `1fr` e ajuste de `.workspace-two-col` com breakpoints `<= 1120px`, `<= 1380px` e `<= 1400px`), todos os ensaios unitários, de build, layout multi-viewport e E2E em navegador real passaram integralmente.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `52212db1a6c9410c57b1b97fd8eed471361f3086`
- **Data (UTC)**: `2026-11-19T15:22:06Z`
