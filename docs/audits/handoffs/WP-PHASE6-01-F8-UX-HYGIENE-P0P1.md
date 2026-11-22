# Handoff e Parecer F9 — `WP-PHASE6-01-F8-UX-HYGIENE-P0P1` (Rodada 2 — `accepted`)

- **WorkPackage**: `WP-PHASE6-01-F8-UX-HYGIENE-P0P1`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `610bb6501640918b0e319f3324c86c600ebd5273` (+ alterações F8 revisadas na Rodada 2)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-22T19:08:32Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Todas as 10 modificações produtoras da frente F8 permaneceram estritamente dentro de `allowed_paths` (`web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`), sem tocar em `contracts/`, `control_lab/`, `web/bridge/`, `web/worker/`, `web/storage/`, `tests/oracles/` ou `tests/e2e/`:

| Arquivo Auditado (F8) | SHA-256 (Rodada 2 — Aprovado) | Papel no Pacote |
|---|---|---|
| `web/app/main.ts` | `0812d37b730c9c1d2550f0d48e82655b2a6318be0b28986b488471fb945386a3` | Separação `.status-dot` / `.status-badge-text` no `#engine-status-badge`; remoção de sufixos `(F2)`–`(F6)` em `#controllab-tab-heading`. |
| `web/app/styles.css` | `d8168396520985516e7fd7aed80f7901a425078926cce36e9cd5906503afea3f` | Top Bar compacta (`@media (min-width: 1100px)`), contenção do `<select>` do Dock, drawer RPC recolhido (`44px`), checkboxes `20×20` com rótulos `>=44px`, toolbar LMI compacta e regras `.chart-container:empty` **escopadas** a `#identification-workspace-panel`, `#siso-workspace-panel` e `#controllab-charts-panel` (correção `F9-UX6-01`, linhas 733–744). |
| `web/app/workspace_dock.ts` | `636037906001e6c74c0fe6a0f0fa9b58e2089dd226afe015fa4c918e92121a78` | Nomes amigáveis no Dock (`formatDockObjectDisplayName`) preservando ID técnico em `.dock-item-ref` e classe `.dock-preset-select`. |
| `web/charts/scientific_chart.ts` | `25cae5a2e0a8540a7b2275cd5296d9b437f29ef387c06961fd28084c3070b6f2` | `formatAxisTickLabel` (clamp `|v| < 1e-12 -> 0`) e `formatChartHeadingTitle` (título SVG limpo preservando `data-series-semantics` e cabeçalho CSV). |
| `web/features/views/identification_view.ts` | `b83b7f9d4db575d2094786583229bc0f9b78fa08077aa3d69bee13b0b83c9b9a` | Remoção de numeração duplicada nas pílulas `#id-pipeline-bar`. |
| `web/features/views/siso_view.ts` | `eb6f70a65e2c4a145da94c028f69f58358576ce16a50f7f2c6dfbea8aae7ec08` | Classe `.checkbox-touch-label` em `#siso-use-pade`. |
| `web/features/views/statespace_view.ts` | `c8d6c2fec9f1588911b19b8eae3ff6557e881fcb5755cdc3a7d19804e82072f4` | Hierarquia calma em `#btn-lqr-cancel` (`.btn-danger-outline`), `#btn-reset-worker` (`.btn-subtle`) e `.checkbox-touch-label` em `#pvm-saturation-enabled`. |
| `web/features/views/fuzzy_view.ts` | `293f92975999fdac6e67e6e3c7e134e3f3f97b8878517e14e6cd4419b4e7a84f` | Remoção de `fuzzy.fit_anfis` do `<h4>` do card ANFIS. |
| `web/features/views/lmi_view.ts` | `7d5fab81678c2a214eb079fbd76af43fcabc68ef173a8312f552fde24b14c9fe` | Remoção de `(ADR-010)` e `(Zona 2)` nos títulos, checkboxes sem `.touch-control` (rótulo `.lmi-check-label` `>=44px`), certificado 5D bilíngue preservando tokens canônicos em `<code class="cert-token">`. |
| `tests/unit/f8/shell_dock_ux.test.ts` | `e75fde0f341ee5cb52f2412597783be0f9a8d3aa1cec2de097dbd7cf3d42530b` | Cobertura unitária dos requisitos de higiene P0+P1 + guarda anti-regressão contra regra global `.chart-container:empty` (`F9-UX6-01`). |

Segurança estática verificada na Rodada 2: zero ocorrências de `eval(`, `new Function` ou `document.write(` nos 10 arquivos (`STATIC_SECURITY_OK`); zero duplicação científica; invariantes R-23, R-26 e R-27 preservados.

---

## 2. Verificação da Correção de `F9-UX6-01` (Rodada 1 → Rodada 2)

- **Defeito da Rodada 1**: `web/app/styles.css` (SHA-256 anterior `fdc6eecb108a975d07186ce734e90721ea8eb87614beb57fc36e6ff0db81c082`) aplicava `.chart-container:empty { display: none; }` globalmente, ocultando `#lmi-spectrum-chart-slot` na Aba 6 (`specLeft = 0 < certLeft = 324.375`) e `#mimo-sigma-chart-slot` na Aba 4 (`sigmaLeft = 0`).
- **Correção verificada na Rodada 2**:
  - `web/app/styles.css` (linhas 733–737) escopou estritamente `display: none` para `#identification-workspace-panel .chart-container:empty`, `#siso-workspace-panel .chart-container:empty` e `#controllab-charts-panel .chart-container:empty`.
  - `tests/unit/f8/shell_dock_ux.test.ts` (linhas 1027–1030) adicionou asserções explícitas pelos 3 seletores escopados e regex negativa `!/^(?:^|\n)\s*\.chart-container:empty\s*\{/`.
- **Métricas reais confirmadas em Chromium (`web/dist`, pós-rebuild)**:
  - **Aba 6 (`optimization_lmi`, `1280×800`)**: `#lmi-spectrum-chart-slot` permanece `display: block`, `specLeft = 798.98px > certLeft = 324.38px` (coluna 2 preservada).
  - **Aba 4 (`mimo_frequency`, `1280×800`)**: `#mimo-sigma-chart-slot` permanece `display: block`, `sigmaLeft = 335.77px` (`> 0` e `< rgaLeft = 883.17px`, coluna 1 preservada).
  - **Abas 1 e 2 (`identification`, `siso_frequency`)**: cards vazios de Identificação permanecem `display: none` (`["none", "none"]`) e `.siso-charts-grid` vazia permanece `display: none`.
  - **Top Bar**: altura `76px` em `1440×900` e `1280×800`.
  - **Workspace Dock**: `#dock-example-select` contido (`selectRight = 269px <= dockRight = 282px`, folga `13px`).
  - **Zero overflow horizontal**: `scrollWidth <= innerWidth` em todas as 6 abas em `1440×900`, `1280×800` e `390×844`.

---

## 3. Evidência de Execução Independente dos Gates (Rodada 2)

| Gate / Comando | Resultado | Observações |
|---|---|---|
| `npm --prefix web run typecheck` | **PASS** (exit 0) | `tsc -p tsconfig.json --noEmit` limpo. |
| `npm --prefix web run build` | **PASS** (exit 0) | Wheel `control_lab-1.0.0-py3-none-any.whl` reconstruído e 42 ativos verificados. |
| `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all` | **PASS** (`150/150`) | 20 arquivos de teste, 0 falhas, 0 skips (`126.7s`). |
| `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_ux_refactor_cl_ux_dir_001.py tests/e2e/test_id_siso_verticals.py tests/wasm/test_real_runtime.py -v` | **PASS** (`22/22`) | 13/13 UX (`CL-UX-DIR-001`, incluindo `test_ux_workbench_mockup_fidelity_topbar_and_2col_grids`), 5/5 verticais ID/SISO e 4/4 Wasm real (`202.15s`, 0 falhas, 0 skips). |
| `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py` | **PASS** (exit 0) | 11 schemas Draft 2020-12 válidos; 7/7 fixtures ouro com SHA-256 íntegro; 4 exemplos válidos. |
| `python3 scripts/project_governance.py` | **PASS** (exit 0) | Validado após atualização de `PROJECT_STATE.json` (`95/95` aceitos). |

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios — Rodada 2)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | 10 arquivos F8 estritamente em `web/app/`, `web/features/`, `web/charts/` e `tests/unit/f8/`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `verify_fixtures.py` aprovado (11 schemas Draft 2020-12 + 7/7 fixtures ouro íntegras). | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Contratos RPC e motor científico intocados; `tests/wasm/test_real_runtime.py` 4/4 aprovado. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma tolerância numérica ou de teste alterada; `formatAxisTickLabel` atua apenas na formatação de rótulos de eixo (`|v| < 1e-12 -> 0`) sem mutar dados ou CSV. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Preservados integralmente (`150/150` testes web e `5/5` verticais ID/SISO aprovados). | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Ticks `1 + 4.44e-16` verificados em `shell_dock_ux.test.ts`; planta não-estabilizável, BMI e `RESOURCE_LIMIT` verificados em E2E/Wasm real (`22/22`). | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Confirmado em `tests/wasm/test_real_runtime.py` (`4/4 passed`). | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | R-23, WCAG 2.2 AA, alvos táteis `>=44px`, layout 2 colunas em Abas 4 e 6 (`F9-UX6-01` sanado) e zero overflow em `1440×900`/`1280×800`/`390×844` validados em Chromium real. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | As 5 dimensões permanecem separadas na UI LMI com rótulos amigáveis + `<code class="cert-token">` preservando os tokens canônicos. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `150/150` web tests + `22/22` pytest E2E/Wasm real + `typecheck` + `build` + `verify_fixtures.py` + `project_governance.py` aprovados com 0 falhas e 0 skips. | CONFORME |

---

## 5. Parecer F9 e Assinatura da Auditoria Independente

- **Parecer F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `610bb6501640918b0e319f3324c86c600ebd5273`
- **Data (UTC)**: `2026-11-22T19:08:32Z`
- **WorkPackage**: `WP-PHASE6-01-F8-UX-HYGIENE-P0P1`
- **Justificativa**: A F8 sanou integralmente o defeito `F9-UX6-01` escopando `.chart-container:empty { display: none; }` aos painéis `#identification-workspace-panel`, `#siso-workspace-panel` e `#controllab-charts-panel` em `web/app/styles.css` e adicionando guarda unitária em `tests/unit/f8/shell_dock_ux.test.ts`. A reauditoria independente F9 confirmou em navegador real Chromium a preservação da grade 2 colunas nas Abas 4 (`sigmaLeft=335.77 < rgaLeft=883.17`) e 6 (`specLeft=798.98 > certLeft=324.38`), ocultação dos cards vazios nas Abas 1/2, Top Bar compacta (`76px`), Dock contido (`13px` de folga), zero overflow em `1440×900`/`1280×800`/`390×844`, `150/150` web tests e `22/22` testes E2E + Wasm real sem falhas ou skips.
