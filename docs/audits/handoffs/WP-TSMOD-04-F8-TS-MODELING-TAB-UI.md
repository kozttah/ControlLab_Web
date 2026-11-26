# Handoff e Parecer F9 — `WP-TSMOD-04-F8-TS-MODELING-TAB-UI`

- **WorkPackage**: `WP-TSMOD-04-F8-TS-MODELING-TAB-UI`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `11ead9400436f46f2bfe9e1d0c5a16e5b7f50403`
- **Veredito F9**: `ACCEPTED_BY_F9` (`accepted`)
- **Data da Auditoria (UTC)**: `2026-11-26T03:02:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Verificado via `git status --short`: as alterações da entrega de `F8` estão estritamente confinadas aos caminhos autorizados da frente (`web/features/`, `web/charts/`, `web/app/`, `tests/unit/f8/`):

| Arquivo Auditado | Status Git | SHA-256 | Papel no Pacote |
|---|---|---|---|
| `web/features/views/ts_modeling_view.ts` | `??` | `db80e729775f2ba12763818016dd2e8d233395988b4726ee0964b44993ad4a41` | Bancada guiada da Aba 6 (Via 1 Setor, Via 2 TPMT, Via 3 FEMT), presets didáticos (`pendulum_16`, `nonseparable_benchmark`), comparação FEMT vs TPMT, promoção ao Workspace Dock, atalho para LMIs, recarga via `provenance.ts_derivation` e exportação passiva Python/MATLAB. |
| `web/charts/ts_modeling_charts.ts` | `??` | `5dc62a8114a7200225e292ac755362834bead084137419f7dbb5348d2be55520` | Geradores e renderizadores SVG determinísticos e acessíveis (WCAG 2.2 AA): `h_r` 1D, malha 2D simplicial/tensorial, bases `U` vs `W`, scree log dos valores singulares, heatmap de erro off-grid e tabelas acessíveis alternativas. |
| `web/app/tool_descriptor.ts` | `M` | `be890cd7d74f99a2ff0909c4a483938d20117c3cc04339d744ad4e63d4e75cae` | Expansão de `PROJECT_TAB_IDS` e `PROJECT_TAB_METADATA` para 7 abas (`ts_modeling` na posição 6, `optimization_lmi` na posição 7). |
| `web/app/main.ts` | `M` | `9047cbd2fd093541adf544a85d7530754efd57ff20bac7ad5850f9190a1071bf` | Montagem, renderização e roteamento `onRouteToLmi` da `TsModelingView`. |
| `web/app/styles.css` | `M` | `e610f632232c19aafe5899b9208ff2be55cd1ee9cf7eb92da0197402ae07b0e7` | Estilos da bancada TS Modeling e grade de gráficos. |
| `tests/unit/f8/ts_modeling_view.test.ts` | `??` | `34bbdd82504da09e43ce9fa31c3ae544cb97132dd661ac13beab10318deda402` | Suíte unitária de `WP-TSMOD-04-F8-TS-MODELING-TAB-UI` (7 abas, Via 1/2/3, 5 gráficos SVG, Workspace Dock, atalho LMI, recarga, exportação passiva e verificação R-21). |
| `tests/unit/f8/shell_dock_ux.test.ts` | `M` | `89867804ab20f4879998f950eab4790e5fb93e71559c008c76182c0d60d6d294` | Atualização do mapeamento esperado de cabeçalhos para 7 abas. |
| `tests/unit/f8/ui_mvp_lqr.test.ts` | `M` | `3813a54958cb910974178234cf4b8f1b4cd30b76be4128430e6c144cef5e7bd1` | Atualização das asserções de `PROJECT_TAB_IDS.length === 7` e Aba 7 (`optimization_lmi`). |

Nenhum arquivo em `control_lab/`, `web/bridge/`, `web/worker/`, `contracts/fixtures/`, `contracts/schemas/` ou `tests/unit/f1..f7/` foi modificado.

---

## 2. Verificação Específica de Requisitos e Segurança (`R-21`, `WP-04`)

1. **Expansão de Abas (`web/app/tool_descriptor.ts`)**: `PROJECT_TAB_IDS` contém 7 itens, com `"ts_modeling"` na posição 6 (`"6. Obtenção de Modelos TS (Setor, TPMT & FEMT)"`, `ownerFront: "F5"`) e `"optimization_lmi"` na posição 7 (`"7. LMIs, SDPs e Síntese Robusta"`, `ownerFront: "F6"`).
2. **Segurança `R-21`**: Varredura automatizada em `web/features/views/ts_modeling_view.ts` e `web/charts/ts_modeling_charts.ts` confirmou `0` ocorrências de `eval(` e `0` ocorrências de `new Function`. Todas as inserções dinâmicas em `innerHTML` e SVG passam por `escapeHtml(...)` ou `formatNumericDisplay(...)`; `substitutePremises(...)` realiza substituição puramente textual.
3. **Requisitos Funcionais `WP-04`**:
   - Fluxo guiado de 4 passos cobrindo Via 1 (Setor), Via 2 (TPMT) e Via 3 (FEMT) com presets `pendulum_16` (4 premissas / 16 regras) e `nonseparable_benchmark` (2D não separável para comparação FEMT vs TPMT).
   - 5 gráficos SVG acessíveis (`role="img"`, `aria-label`, `<title>`, `<desc>`, paleta `TS_CHART_PALETTE` com contraste WCAG AA e tabelas alternativas): `h_r` 1D, malha 2D (`delaunay` / `kuhn_delaunay` / `tensorial`), bases `U` vs `W`, scree log dos valores singulares e heatmap de erro off-grid.
   - Promoção ao Workspace Dock (`register(false)`) e atalho "Registrar e Abrir em LMIs" (`register(true)` -> `onRouteToLmi` + `switchTab("optimization_lmi")`).
   - Recarga de receita via `provenance.ts_derivation` (`extractRecipeFromProvenance`, `reloadRecipe`).
   - Exportação passiva de scripts Python e MATLAB (`exportScript`, exigindo `res.code_executed === false`).
4. **Divergência de `acceptance_cmd`**: `web/package.json` não define o script `test:unit:f8` (define apenas `typecheck`, `test`, `test:unit:f7`, `build`). Em substituição equivalente, foi executado `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f8 && npm --prefix web run build`, com aprovação integral.

---

## 3. Evidência de Execução Independente F9

- **Testes Unitários Web (`f8`) + Typecheck + Build**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f8 && npm --prefix web run build`: `PASS` (`typecheck` `f8` com `41` arquivos TS OK; `89/89` testes aprovados em `15` arquivos, `0` falhas, `0` skips; wheel Python construído e `42` assets locais verificados).
  - `npm --prefix web run typecheck`: `PASS` (`0` erros).
- **Suítes Python (F1, F5, Oráculos e Segurança)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f5 tests/unit/f1 tests/oracles tests/security --ignore=tests/security/test_real_browser_security.py -q`: `PASS` (`623 passed in 96.98s`).
- **Integridade de Fixtures, Schemas e Governança**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py`: `PASS` (`11` schemas JSON Draft 2020-12 válidos e `7` fixtures ouro íntegras).
  - `python3 scripts/project_governance.py`: `PASS` (`{"accepted": 125, "corrective_packages": 24, "work_packages": 127}`).

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | `git status --short` confirma alterações restritas a `web/features/views/`, `web/charts/`, `web/app/` e `tests/unit/f8/`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `git status --short` limpo fora de F8; `verify_fixtures.py` valida `11/11` schemas e `7/7` fixtures ouro. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | `TsModelingView` consome exclusivamente `TsModelingEngineClient` (`unwrap()` validando `status`/`result`/`error`) e preserva `provenance.ts_derivation` ao registrar `TSStateSpace`. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhum cálculo numérico de oráculo alterado; suíte `tests/oracles` (`623 passed`) intacta. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `readParams()` valida inteiros/limites de grade, posto e pontos de validação lançando `ControlLabBridgeError("VALIDATION_ERROR", ...)`. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Coberto para exportação/registro sem derivação prévia, ausência de `provenance.ts_derivation` na recarga, fallback de gráficos quando `sector_nonlinearity` não possui malha/scree 2D e rejeição de scripts não passivos (`code_executed !== false`). | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Comunicação exclusivamente via `TsModelingEngineClient` tipado; `tests/unit/f8` e `tests/security` aprovados sem vazamento. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Botões de registro e exportação permanecem `disabled` + `aria-disabled="true"` até haver derivação; SVGs possuem `role="img"`, `aria-label`, `<title>`, `<desc>`, paleta AA e tabelas alternativas; regiões `aria-live="polite"` e `announcer` presentes. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente à Aba 6 (`F8`), porém `register(true)` preserva a integração e roteamento limpo para a Aba 7 (`optimization_lmi`). | N/A (CONFORME) |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `89/89` testes web `f8` (`node scripts/run_web_tests.mjs --scope f8`), `623/623` testes Python (`f1`, `f5`, `oracles`, `security`) e `npm --prefix web run build` aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: `ACCEPTED_BY_F9` (`accepted`)
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `11ead9400436f46f2bfe9e1d0c5a16e5b7f50403`
- **Data (UTC)**: `2026-11-26T03:02:00Z`
