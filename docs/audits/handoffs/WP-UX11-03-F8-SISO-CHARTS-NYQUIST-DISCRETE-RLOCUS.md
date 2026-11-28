# Handoff e Parecer F9 — `WP-UX11-03-F8-SISO-CHARTS-NYQUIST-DISCRETE-RLOCUS`

- **WorkPackage**: `WP-UX11-03-F8-SISO-CHARTS-NYQUIST-DISCRETE-RLOCUS`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `d092c55b70d0e8561acaab2863b4e9bca0d5774a`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-28T03:37:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

A auditoria independente F9 verificou via `git status --short` e `git diff --stat` que todas as modificações produzidas pela frente `F8` permanecem estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/features/views/siso_view.ts`, `web/features/views/statespace_view.ts`, `web/charts/scientific_chart.ts`, `web/charts/overlays.ts`, `web/app/styles.css`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/charts/overlays.ts` | `82447d84d95fe24f7a1d060efb1327fd040741a4c39f2ffbaaad4d1f18411b17` | Mapeamento exato `z = exp(s·dt)` de regiões de 2ª ordem no plano z: espiral logarítmica de amortecimento constante `ζ`, arco de frequência natural constante `ω_n`, círculo de raio espectral `|z| = exp(-(4/T_s)·dt)`, avaliação de polos em `evaluatePolesAgainstOverlay` via `s = ln(z)/dt`, e rótulo obrigatório `[Heurístico]` com rejeição de classificação `exact`. |
| `web/charts/scientific_chart.ts` | `6d8580083a82fd0fbaec78f605b7366abe4859e0c065179d536b95b405ee66d3` | Anotações no Diagrama de Nyquist (círculo unitário `|L(jω)|=1`, arco de Margem de Fase `MF`, segmento de Margem de Ganho `MG` até `(-1, 0)`, e vetor interativo de distância `d = hypot(re + 1, im)` e sensibilidade `|S(jω)| = 1/d`), além de centralização na origem com aspecto 1:1 (`rx === ry`) e normalização de overlays discretos em `renderRootLocusSvg` e `renderPoleZeroSvg` para `dt !== null`. |
| `web/features/views/siso_view.ts` | `53457bb74b52a63fe13a5dec14305867ba5d7d4ea3477b1ee82c199d7262f011` | Refatoração da Aba 2 para layout empilhado full-width (`.siso-workbench-stack`, `.siso-controls-bar`, `.siso-results-stage`, `.siso-charts-grid`), preservação integral de todos os IDs e do bloqueio R-23 de exportação, exibição de `d = |L + 1|` e `|S(jω)| = 1/d` no datatip de Nyquist e repasse de margens/overlays discretos. |
| `web/app/styles.css` | `b5f9163fc8f839652f6757c270111c1c35e1b40eb32441f798abce3d141d56d1` | Estilos responsivos da bancada SISO full-width empilhada (`.siso-workbench-stack`, `.siso-controls-bar`, `.siso-tuner-main-row`, `.siso-advanced-grid`, `.siso-results-stage`) com breakpoint 2×2 em `900px`. |
| `tests/unit/f8/siso_nyquist_discrete_rlocus.test.ts` | `4d1c04139b5aa92c590a9f0ad96ac5752e91e7f8ef9b6aee0c0a312c8d06dae2` | Testes unitários dedicados cobrindo anotações de Nyquist, distância `d` e `|S(jω)|`, aspecto 1:1 centralizado no plano z (Root Locus e Polo-Zero), geometria e avaliação de overlays discretos de 2ª ordem com `[Heurístico]` e layout/IDs/R-23 da Aba 2. |
| `tests/unit/f8/modern_ui_chart_export.test.ts` | `dc9401be3a2147e662c574eb4fc9f3d4a5e79ce34f06b91f92f3d3c3eceafdd9` | Atualização de asserção de layout para reconhecer `.siso-workbench-stack` na Aba 2. |

Nenhum arquivo em `control_lab/`, `contracts/fixtures/`, `contracts/schemas/`, `web/bridge/`, `web/worker/` ou `web/storage/` foi modificado.

---

## 2. Verificação Matemática e de UX Independente (F9)

1. **Overlays Discretos de 2ª Ordem (`web/charts/overlays.ts`)**:
   - **Espiral de amortecimento constante `ζ`**: confirmada fórmula exata `z(θ) = exp(-(ζ / sqrt(1 - ζ²)) * |θ|) * exp(jθ)` para `θ ∈ [-π, π]`, fechando no eixo real negativo em `θ = ±π`.
   - **Arco de frequência natural constante `ω_n`**: confirmada fórmula exata `z(ζ) = exp(-ζ·ω_n·dt ± j·ω_n·dt·sqrt(1 - ζ²))` para `ζ ∈ [0, 1]` sob condição de Nyquist `ω_n·dt ≤ π`.
   - **Círculo de tempo de acomodação `T_s`**: confirmado raio espectral `|z| = exp(-(4 / T_s)·dt)` centrado na origem.
   - **Avaliação de polos discretos (`evaluatePolesAgainstOverlay`)**: verificada inversão exata `s = ln(z)/dt = (ln|z| + j·atan2(im, re))/dt`, tratamento de polos instáveis (`|z| >= 1`) e polos deadbeat na origem (`|z| <= 1e-15`).
   - **Classificação epistêmica**: todos os overlays de 2ª ordem trazem `[Heurístico]` no rótulo padrão e bloqueiam `classification === "exact"` via `validateOverlayClassification`.
2. **Aspecto 1:1 e Centralização no Plano z (`web/charts/scientific_chart.ts`)**:
   - `computeCenteredDiscreteBounds` garante `xMin = -xHalf`, `xMax = +xHalf`, `yMin = -yHalf`, `yMax = +yHalf` com `xHalf / yHalf = plotW / plotH`, resultando em `cx = padLeft + plotW / 2`, `cy = padTop + plotH / 2` e `rx === ry` exatos em `renderRootLocusSvg` e `renderPoleZeroSvg` sempre que `dt !== null`.
   - `normalizeOverlayForDomain` converte automaticamente overlays contínuos de 2ª ordem para o plano z quando renderizados em gráficos discretos.
3. **Diagrama de Nyquist (`web/charts/scientific_chart.ts` e `web/features/views/siso_view.ts`)**:
   - Círculo unitário `|L(jω)| = 1` (`data-nyquist-annotation="unit-circle"`), arco de Margem de Fase `MF` ao longo de `|L| = 1` de `-π` até `-π + PM` (`data-nyquist-annotation="phase-margin"`), e segmento de Margem de Ganho `MG` no eixo real negativo de `(-1/K_gm, 0)` até `(-1, 0)` (`data-nyquist-annotation="gain-margin"`).
   - Clique/inspeção em `inspectNyquistAtSvgPoint` e `renderNyquistSvg` calcula exatamente `d = Math.hypot(re + 1, im)` e `|S(jω)| = 1 / d` (com proteção para `d <= 1e-12` retornando `Infinity`), exibindo o vetor tracejado até `(-1, 0)` (`data-nyquist-annotation="distance-vector"`) e os valores no datatip acessível da Aba 2.
4. **Layout Full-Width da Aba 2 e Gate R-23 (`web/features/views/siso_view.ts`, `web/app/styles.css`)**:
   - Empilhamento vertical `.siso-workbench-stack` com barra de controles horizontal `.siso-controls-bar` e palco full-width `.siso-results-stage` / `.siso-charts-grid` (2×2 a partir de `900px`). Todos os IDs existentes e os 4 pares de botões de exportação SVG/PNG iniciando bloqueados (`disabled aria-disabled="true"`, R-23) foram preservados.

---

## 3. Evidência de Execução Independente F9

- `npm --prefix web run typecheck`: **PASS** (`0` erros).
- `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f8`: **PASS** (`[typecheck] PASS (f8, 43 arquivo(s) TS)`, `97/97` testes aprovados em `16` arquivos, `0` falhas, `0` skips).
- `npm --prefix web run build`: **PASS** (`control_lab-1.0.0-py3-none-any.whl` empacotado e `42` assets locais verificados).

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações restritas a `web/charts/overlays.ts`, `web/charts/scientific_chart.ts`, `web/features/views/siso_view.ts`, `web/app/styles.css`, `tests/unit/f8/modern_ui_chart_export.test.ts` e `tests/unit/f8/siso_nyquist_discrete_rlocus.test.ts`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | Confirmado via `git status --short`: zero alterações em `contracts/`. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Contratos de visualização F8 consomem os modelos derivados de `RpcResponse`/`Result<T>` preservando `model_revision`, `project_revision`, `provenance` e `series_semantics`. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Fórmulas analíticas exatas (`z = exp(s·dt)`, `hypot(re + 1, im)`, `1/d`, aspecto 1:1 `rx === ry`) verificadas com tolerância `< 1e-12` / `< 1e-6` nos testes unitários. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `createSecondOrderRegionOverlay` e `validateOverlayClassification` validam finitude, faixa de `ζ ∈ [0, 1)`, domínio contínuo vs discreto (`dt > 0`) e lançam `ControlLabBridgeError("VALIDATION_ERROR", ...)` em violações. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Testados polos instáveis (`|z| > 1`), polos fora da região de amortecimento/raio espectral, divisão segura em `d <= 1e-12` (`|S| = ∞`) e rejeição de `classification: "exact"` em overlays de 2ª ordem. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Camada `F8` opera exclusivamente sobre estruturas tipadas JS/SVG; nenhuma alteração em `web/bridge/` ou `web/worker/`. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Mantidos `aria-label`, `<title>`, `<desc>`, `aria-live="polite"` no datatip de Nyquist, rótulo obrigatório `[Heurístico]` e bloqueio inicial R-23 nos 4 pares de exportação SVG/PNG da Aba 2. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente a este pacote F8; nenhum módulo F6 foi modificado. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `97/97` testes unitários da frente F8 aprovados (`0` falhas, `0` skips), `typecheck` e `build` aprovados. | CONFORME |

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `d092c55b70d0e8561acaab2863b4e9bca0d5774a`
- **Data (UTC)**: `2026-11-28T03:37:00Z`
