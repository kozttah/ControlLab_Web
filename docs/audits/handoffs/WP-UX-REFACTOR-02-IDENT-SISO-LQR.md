# Handoff e Parecer F9 — `WP-UX-REFACTOR-02-IDENT-SISO-LQR`

- **WorkPackage**: `WP-UX-REFACTOR-02-IDENT-SISO-LQR`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `02f5a0062b08fe8699ffe1f114adb3d8c6212751`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-19T16:08:06Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações da frente produtora `F8` ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/app/main.ts` | `c8d5dc0b2b72f6bbeefbd272fe3378fa4cdd632273e3c2c1523e78c2a3ab59fe` | Orquestrador enxuto do App Shell conectando `IdentificationView`, `SisoView` e `StatespaceView`, preservando `ControlLabShell`, `WorkspaceDockController`, `InspectorDrawerController`, abas declarativas, guarda R-23 nos botões de exportação SVG/PNG e persistência de `#tab=`. |
| `web/app/styles.css` | `e3ab1b04783c36c300a5b5bf8b02058279c30d0143caac7bca7c6ed71a9cee99` | Estilos responsivos e WCAG 2.2 AA para a barra guiada 3-etapas (`.id-pipeline-bar`), quadro comparativo de modelos (`.id-model-card`), diagrama de blocos SISO (`.siso-loop-diagram-bar`), guarda MIMO (`.mimo-guard-callout`), barra de datatips (`.chart-datatip-bar`), cards KPI LQR (`.lqr-kpi-cards` empilhados em mobile) e filtros matriciais. |
| `web/charts/scientific_chart.ts` | `70d95eb2f9203297bb6bd2dce5a1214c7ee60d501e5236c75e28fed4b21dff14` | Adição de `inspectBodeAtSvgPoint`, `inspectNyquistAtSvgPoint` e `inspectRootLocusAtSvgPoint` realizando exclusivamente lookup geométrico do ponto mais próximo sobre modelos já computados pelo motor Python, além de camadas SVG `<g data-layer="datatip">` e `<g data-layer="frozen-poles-datatip">` congelando todos os polos em malha fechada no ganho `K`. |
| `web/features/views/identification_view.ts` | `3dc131e17f672221e52bdf07b8c8dc2bcbabb5b8b6c8c4273f8c060a2fabb18f` | Bancada modular da Aba 1 (`IdentificationView`): barra guiada 3 etapas (`#id-pipeline-bar`), estimadores rápidos ARX e Subespaços (MOESP/N4SID), quadro multi-modelo (`#id-models-session-list`) com checkboxes comparativos e distinção explícita Simulação Livre (Holdout) vs Previsão 1-Passo (Holdout), banner didático PE e promoção em 1 clique para SISO e SS/LQR. |
| `web/features/views/siso_view.ts` | `d520985695cdb40e909066e9cca1b00ecbe58c8b00faf59cad565db1eaa9c98f` | Bancada modular da Aba 2 (`SisoView`): diagrama de blocos da malha no cabeçalho (`#siso-loop-diagram-bar`), tuner `C(s)=K` (`#siso-gain-slider`) com Fast-Preview vs commit Python, guarda MIMO (`#siso-mimo-guard-callout`) com redirecionamento 1-clique para Aba 4 e datatips clicáveis em Bode (`#siso-bode-datatip`), Nyquist (`#siso-nyquist-datatip`) e Root Locus (`#siso-rl-datatip` + `Aplicar K`). |
| `web/features/views/statespace_view.ts` | `f5c4ff394b3c39af64449fb2ce645869bd5d187d9be924cb909370109287fb8a` | Bancada modular da Aba 3 (`StatespaceView`): cartões KPI (`#lqr-kpi-cards`), badges PBH e Riccati CARE/DARE (`#lqr-pbh-badges`), editor matricial interativo com abas de filtro (`Todas \| Planta \| Pesos`) mantendo todas as células no DOM, presets clássicos, modal JSON documentado (`#lqr-json-modal`) e preservação integral dos seletores E2E (`#lqr-q-slider`, `#lqr-json-advanced`, `#pvm-export-options`). |
| `tests/unit/f8/views_ident_siso_lqr.test.ts` | `d46afaea9eaa0c55f7caf23e1b9e761e743228b331c9f8d215f3a315829ae96c` | Suíte unitária F8 verificando datatips geométricos e congelamento de polos em Root Locus, `IdentificationView` com motor Python real, `SisoView` (guarda MIMO, diagrama de malha, datatips e slider) e `StatespaceView` (KPIs, PBH, filtros matriciais e modal JSON). |

Nenhum arquivo em `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/` ou nos diretórios Python (`control_lab/`) foi modificado pelo produtor. Os checksums SHA-256 das 7 fixtures ouro permanecem intactos e não há duplicação de síntese científica ou importação Python em `web/charts/` ou `web/features/views/`.

---

## 2. Evidência de Execução Independente F9

- **Typecheck e Testes Web**:
  - `npm --prefix web run typecheck`: `PASS` (`0` erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f8`: `PASS` (`49/49` testes aprovados em `8` arquivos, `0` falhas, `0` skips).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: `PASS` (`115/115` testes aprovados em `13` arquivos, `0` falhas, `0` skips).
- **Build de Produção**:
  - `npm --prefix web run build`: `PASS` (Vite build completa, wheel `control_lab-1.0.0-py3-none-any.whl` empacotada, `42` assets locais verificados).
- **Suíte E2E em Navegador Real (Chromium + Firefox + Pyodide/Wasm)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_gatecd_interactions.py tests/e2e/test_id_siso_verticals.py -v` (Chromium `151.0.7922.34`): `PASS` (`7/7` testes aprovados em `94.59s`).
  - `CONTROLLAB_BROWSER=firefox PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_gatecd_interactions.py -v` (Firefox `153.0`): `PASS` (`2/2` testes aprovados em `115.93s`).
  - Verificação Playwright dedicada contra `web/dist` em **Chromium `151.0.7922.34`**:
    - **Aba 1 (`identification`)**: barra 3-etapas (`#id-pipeline-bar`) transitando estados; quadro `#id-models-session-list` com `ARX(2,2,1)` e `MOESP(n=2)` e tabela comparativa `Simulação Livre (Holdout)` vs `Previsão 1-Passo (Holdout)`; layout sem overflow (`scrollWidth === innerWidth`) em `1280×800` (`resWidth=540`), `1100×800` (`resWidth=716`) e `390×844` (`resWidth=306`).
    - **Aba 2 (`siso_frequency`)**: cliques reais nos SVGs de Bode, Nyquist e Root Locus atualizaram `#siso-bode-datatip` (`ω = 0.7067 rad/s | Mag = -6.2833 dB | Fase = -43.2877°`), `#siso-nyquist-datatip` (`ω = 1.8679 rad/s | L(jω) = -0.0921 - j·0.2310`) e `#siso-rl-datatip` (`Polos congelados em K = 18.4207: Ramo 1: -1.0000 - j4.4069 | Ramo 2: -1.0000 + j4.4069`) com `<g data-layer="frozen-poles-datatip">` renderizando os `2` polos em malha fechada.
    - **Aba 3 (`statespace`)**: `#lqr-kpi-cards`, `#lqr-pbh-badges` (`Controlável (PBH)`, `Observável (PBH)`, `CARE (Contínuo)`), filtros matriciais (`#btn-lqr-filter-plant`, `#btn-lqr-filter-weights`, `#btn-lqr-filter-all`) mantendo células no DOM, modal JSON (`#lqr-json-modal`) com restauração de foco via `Escape` e navegação por teclado/mobile `390×844` sem overflow (`scrollWidth=390`).
- **Integridade de Fixtures Ouro e Schemas**:
  - `/home/antigravity/.venv/bin/python scripts/verify_fixtures.py`: `PASS` (`11` schemas JSON Draft 2020-12 válidos e `7` fixtures ouro íntegras).
  - `(cd contracts/fixtures && sha256sum -c checksums.sha256)`: `PASS` (`7/7` fixtures OK).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações da F8 restritas exclusivamente a `web/app/main.ts`, `web/app/styles.css`, `web/charts/scientific_chart.ts`, `web/features/views/identification_view.ts`, `web/features/views/siso_view.ts`, `web/features/views/statespace_view.ts` e `tests/unit/f8/views_ident_siso_lqr.test.ts` (além dos artefatos F9 em `docs/audits/handoffs/` e `PROJECT_STATE.json`). | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `verify_fixtures.py` e `sha256sum -c checksums.sha256` aprovados com `7/7` fixtures ouro e `11/11` schemas JSON intactos. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | As três bancadas modulares (`IdentificationView`, `SisoView`, `StatespaceView`) operam exclusivamente sobre `IdentificationWorkspace`, `SisoWorkspace`, `LqrWorkspace` e `TabsController` consumindo envelopes RPC v1.0 do motor Python. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Verificado que `inspectBodeAtSvgPoint`, `inspectNyquistAtSvgPoint` e `inspectRootLocusAtSvgPoint` em `scientific_chart.ts` executam somente lookup geométrico euclidiano/log-pixel sobre amostras já calculadas pelo Python, sem importação Python nem duplicação matemática nas views F8. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Validado `dt` positivo/contínuo, dimensões matriciais `(n, m, p)` e parsing numérico com `ControlLabBridgeError("VALIDATION_ERROR", ...)` em `StatespaceView`, detecção MIMO 1×1 com guarda explícito em `SisoView` e tratamento tipado de erros em `IdentificationView`. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Coberto na suíte unitária F8 (`views_ident_siso_lqr.test.ts`) e na suíte E2E real: entrada constante sem excitação (T-ID-02), planta MIMO 2×2 rejeitada na Aba 2 com redirecionamento à Aba 4, múltiplas frequências de cruzamento (T-FREQ-02) e `DIMENSION_MISMATCH` em `Q`. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Suíte completa `F7+F8` (`115/115` testes web), `7/7` E2E Chromium e `2/2` E2E Firefox aprovadas sem vazamentos de `PyProxy`. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Verificado em navegador real: `Fast-Preview` vs `Confirmado` em `SisoView` e `StatespaceView` com bloqueio R-23, datatips interativos com botões de limpar/aplicar, regiões `aria-live="polite"`, filtros matriciais preservando células no DOM, modal JSON com `Escape` restaurando foco e zero overflow em `1280×800`, `1100×800` e `390×844`. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente à frente F8; sem alterações em `control_lab/optimization/`. | N/A |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `49/49` (`--scope f8`), `115/115` (`--scope all`), `7/7` E2E Chromium, `2/2` E2E Firefox e verificação Playwright UX contra `web/dist` aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Notas de Auditoria

- A verificação em Chromium real contra `web/dist` confirmou o funcionamento integral da modularização proposta no `CL-UX-DIR-001` para as Bancadas 1, 2 e 3, mantendo total compatibilidade retroativa com os seletores e contratos auditados nos gates `G-0C` e `G-0D`.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `02f5a0062b08fe8699ffe1f114adb3d8c6212751`
- **Data (UTC)**: `2026-11-19T16:08:06Z`
