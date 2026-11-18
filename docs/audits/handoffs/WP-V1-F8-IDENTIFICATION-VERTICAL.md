# Handoff e Parecer F9 — `WP-V1-F8-IDENTIFICATION-VERTICAL`

- **WorkPackage**: `WP-V1-F8-IDENTIFICATION-VERTICAL`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `18654f5bcb7a0c48df3a9c50c24f73e91f498e17`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-18T23:10:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações do produtor `F8` ficaram estritamente restritas aos diretórios autorizados em `allowed_paths` (`web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/features/identification_workspace.ts` | `fdc1a63a561ab8eef01c23a6f8265ac7ccdd0266594dc3e9f5981caa0496c98e` | `IdentificationWorkspace`, importação de `Dataset(t,u,y)` via CSV (`parseCsvToDatasetDto`) ou presets determinísticos PRBS / entrada constante (`buildBenchmarkArxDatasetDto`), particionamento disjunto em treino e validação (`splitDatasetDtoTrainHoldout`), orquestração RPC de `identification.fit_arx`, `identification.fit_subspace`, `identification.validate_model`, extração separada de métricas de previsão de 1 passo vs simulação livre para treino e holdout (`T-ID-03`), diagnóstico de posto/PE/condicionamento (`T-ID-02`), construção de gráficos e reutilização explícita via `core.reuse_model` para LQR (Aba 3) e SISO (Aba 2) (`R-06`, `T-ID-04`). |
| `web/charts/scientific_chart.ts` | `ca2072a1b50ce11900d9eea127f20b946ea9ecbb6449da3fb3dc85c487afebb0` | Modelos e renderização SVG determinística de resposta temporal comparativa (`buildIdentificationResponseChartModel`: $y$ medido, $\hat{y}$ previsão 1-passo, $\hat{y}$ simulação livre, resíduos e entrada $u$) e diagnóstico de correlação de resíduos (`ResidualCorrelationChartModel`, `buildResidualCorrelationChartModel`, `renderResidualCorrelationSvg`: autocorrelação $R_{\varepsilon\varepsilon}(\tau)$ e correlação cruzada $R_{u\varepsilon}(\tau)$ com bandas de confiança de 95% e 99%), além de tabelas acessíveis WCAG 2.2 AA e exportação CSV. |
| `web/features/tool_catalog.ts` | `c9cbbbdd9181a81c938d6493aa439b7235278551288f8e1ce4da5030710401ab` | Descritores declarativos da Aba 1 enriquecidos: `detrend` (`none`, `mean`, `linear`) em `identification.fit_arx`, seleção de algoritmo (`moesp`, `n4sid`) e `estimate_feedthrough` em `identification.fit_subspace`, e alinhamento de visualizações (`time_response`, `residuals_correlation`, `pole_zero_map`). |
| `web/app/shell.ts` | `fbc22bcfc2a8b9cca6de4361400d304853fbd1ce0f289d463021a0235ec23916` | Instanciação e integração de `IdentificationWorkspace` ao `ControlLabShell`, vinculada ao `TypedObjectWorkspace`, `ProjectTabsController`, `applySelectedPlantToLqr()` e roteamento de abas. |
| `web/app/main.ts` | `0b0bb73420c917c9f5ebae66384714a95932ee1596536862b40974c94d1d2d82` | Painel `#identification-workspace-panel` na Aba 1 com importação CSV, carregamento PRBS / entrada constante (`T-ID-02`), particionamento treino/holdout configurável, seletor de partição visualizada (`validation` vs `train`), painel `#id-diagnostics-panel` com métricas 1-passo vs simulação livre (`T-ID-03`), posto/$\kappa(\Phi)$/PE (`T-ID-02`), raio espectral $\rho(A)$ e estabilidade explícitos, gráficos SVG (`#id-response-chart-slot`, `#id-residuals-chart-slot`, `#pz-chart-slot`), tabelas acessíveis WCAG 2.2 AA e botões de reutilização direta em LQR e SISO. |
| `tests/unit/f8/identification_vertical.test.ts` | `a5d9cd8cf7905529dbe57eaf472019426b49468fd8c1eebd6b7eeedd8489ca8a` | 3 suítes unitárias e de integração cobrindo importação CSV, particionamento disjunto treino/holdout, `T-ID-01`, `T-ID-02`, `T-ID-03`, `T-ID-04`/`R-06` ponta a ponta contra o motor Python real (`control_lab.core.rpc.dispatch`) e DOM `mountControlLabApp`. |

Nenhum arquivo em `control_lab/identification/` (F4), `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/` ou `web/worker/` foi modificado pelo produtor (`contracts/fixtures/checksums.sha256` permanece intacto com SHA-256 `4b7a39a4ad5d8eb6b48d2d28d8e8a3673e38105bce057909dbdb29884ef0cc7a`).

---

## 2. Verificação Independente dos Critérios do Pacote (`docs/audits/NEXT_QUEUE_2026-11-17.md`)

1. **Importação/seleção de dataset numérico passivo com `dt`, unidades e partição treino/holdout disjunta (`T-ID-01`, `T-ID-03`)**:
   - `parseCsvToDatasetDto` valida monotonia temporal estrita ($t_k > t_{k-1}$), dimensões $[N, m]$ e $[N, p]$, estima `dt` sob amostragem uniforme e preserva nomes de canais e unidades.
   - `splitDatasetDtoTrainHoldout` particiona o dataset em subconjuntos disjuntos `train` ($0 \dots N_{\text{train}}-1$) e `validation` ($N_{\text{train}} \dots N-1$) com IDs distintos (`trainId !== valId`), registrando-os em `dataset` e `valDataset` e impedindo contaminação do ajuste pelo holdout.
2. **Estimação ARX com atraso (`nk`) e Subespaços (`MOESP`/`N4SID`) sem matemática científica duplicada em TypeScript (`T-ID-01`, `R-06`)**:
   - `IdentificationWorkspace.fitArx`, `fitSubspace` e `validateModel` delegam 100% da estimação, fatorações QR/SVD/LQ e estatísticas de resíduos ao motor Python F4 via `ControlLabEngineClient` (`identification.fit_arx`, `identification.fit_subspace`, `identification.validate_model`).
   - No benchmark determinístico PRBS (`na=2, nb=2, nk=1`, $dt=0.05\text{ s}$, $N_{\text{train}}=112$, $N_{\text{val}}=48$), `ARX_QR_SVD` recupera os coeficientes plantados $a = [-1.5, 0.7]$ e $b = [0.4, 0.2]$ com erro $< 10^{-14}$ e `fit_subspace` (`moesp`, ordem 2, horizonte 8) obtém `FIT% > 99.99%` em simulação livre no holdout.
3. **Separação estrita entre Previsão de 1 Passo e Simulação Livre, resíduos com bandas 95%/99% e avisos de PE/condicionamento (`T-ID-02`, `T-ID-03`, `R-26`, `R-27`)**:
   - O relatório e o DOM (`#id-diagnostics-panel`) apresentam separadamente `one_step_prediction` e `free_simulation` (FIT% e RMSE) tanto para Treino quanto para Validação/Holdout, além de AIC/BIC/FPE, raio espectral $\rho(A)$ e status de estabilidade explícito (jamais inferindo estabilidade apenas pelo FIT%).
   - Com dataset de entrada constante (`T-ID-02`), o motor retorna `status: "warning"`, `rank_deficient: true`, `pe_satisfied: false` e códigos `PERSISTENCE_OF_EXCITATION_INSUFFICIENT` e `RANK_DEFICIENT_REGRESSION`, renderizados de forma visível em `#id-diagnostics-panel` (`data-pe-status="insufficient"` e lista `data-testid="id-warnings-list"`).
   - Os gráficos SVG (`renderTimeResponseSvg` e `renderResidualCorrelationSvg`) exibem $y$ medido, $\hat{y}$ 1-passo, $\hat{y}$ simulação livre, resíduos $e(k)$, autocorrelação $R_{\varepsilon\varepsilon}(\tau)$ e correlação cruzada $R_{u\varepsilon}(\tau)$ com bandas de 95% e 99%, acompanhados de tabelas acessíveis WCAG 2.2 AA e exportação CSV.
4. **Reutilização direta do modelo identificado em LQR e SISO sem cópia manual (`R-06`, `T-ID-04`)**:
   - `IdentificationWorkspace.reuseIdentifiedModel` executa o fluxo explícito `registerPendingIdentifiedModel -> core.reuse_model (native | StateSpace) -> registerPendingDerivedModel`, selecionando o modelo derivado em `frequencyPlant` (Aba 2 SISO) ou aplicando o `StateSpace` discreto derivado diretamente ao workspace LQR (Aba 3) com preservação de `dt = 0.05` e `provenance`.

---

## 3. Evidência de Execução (Node/TypeScript, Oráculos Python F4 e Navegador Real Playwright/Pyodide Wasm)

- **Typecheck e Testes Unitários Web (`f8` e `all`)**:
  - `npm --prefix web run typecheck`: `PASS` (0 erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" PYTHON=/home/antigravity/.venv/bin/python node scripts/run_web_tests.mjs --scope f8`: `PASS` (`29/29` testes em 3 arquivos).
  - `PATH="/home/antigravity/.venv/bin:$PATH" PYTHON=/home/antigravity/.venv/bin/python node scripts/run_web_tests.mjs --scope all`: `PASS` (`92/92` testes em 8 arquivos).
- **Testes Unitários Python F4 e Integridade de Fixtures**:
  - `/home/antigravity/.venv/bin/pytest -q tests/unit/f4/test_identification.py`: `PASS` (`11/11` testes).
  - `/home/antigravity/.venv/bin/python scripts/verify_fixtures.py` e `sha256sum -c contracts/fixtures/checksums.sha256`: `PASS` (11 schemas JSON Draft 2020-12 válidos e todas as fixtures ouro intactas).
- **Suíte Real de Navegador (`tests/wasm/` + `tests/e2e/`) e Probe F9 Dedicado**:
  - `npm --prefix web run build && /home/antigravity/.venv/bin/pytest -q tests/wasm tests/e2e`: `26/26` testes aprovados em Chromium real com Worker Pyodide Wasm e wheel local `control_lab-1.0.0-py3-none-any.whl` (42 assets locais verificados).
  - Probe real-browser F9 no Chromium Headless `151.0.7922.34` servindo `web/dist/` com Worker Pyodide Wasm real comprovou:
    1. Particionamento do dataset PRBS na Aba 1 em `ds-b-arx-prbs-train#1` ($N=112$) e `ds-b-arx-prbs-val#1` ($N=48$).
    2. Execução de `identification.fit_arx` (`na=2, nb=2, nk=1`) no Worker Pyodide real recuperando $a = [-1.5, 0.7]$, $b = [0.4, 0.2]$, `dt = 0.05`, `train_one_step_fit = 100.0%`, `val_free_sim_fit = 100.0%`, `rank = 4/4`, `pe_satisfied = true`.
    3. Renderização no DOM real dos gráficos SVG (`time_response` com `y Medido (Holdout)`, `ŷ Previsão 1-Passo (Holdout)`, `ŷ Simulação Livre (Holdout)` e `residual_correlation` com `data-bound="95-upper"` e `data-bound="99-upper"`), mapa de polos discretos no círculo unitário e tabelas acessíveis WCAG 2.2 AA.
    4. Execução de `identification.validate_model` e `identification.fit_subspace` (`moesp`, ordem 2, horizonte 8, `inner_model_kind = "StateSpace"`, `val_free_sim_fit = 100.0%`) no Worker Pyodide real.
    5. Detecção de entrada constante (`T-ID-02`) no Worker Pyodide real com `status = "warning"`, `rank_deficient = true`, `pe_satisfied = false`, warnings `PERSISTENCE_OF_EXCITATION_INSUFFICIENT` e `RANK_DEFICIENT_REGRESSION`, e badge DOM `data-pe-status="insufficient"`.
    6. Reutilização direta via `core.reuse_model` no navegador real tanto para SISO (`siso.bode_nyquist` com `dt = 0.05`) quanto para LQR (`lqrPlant.id = "reuse-0a11ce84..."`, `dt = 0.05`, `A.shape = [2, 2]`), com zero requisições HTTP externas.

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | `git status --short` do produtor lista exclusivamente `web/app/main.ts`, `web/app/shell.ts`, `web/charts/scientific_chart.ts`, `web/features/tool_catalog.ts`, `web/features/identification_workspace.ts` e `tests/unit/f8/identification_vertical.test.ts`, todos dentro de `["web/app/", "web/features/", "web/charts/", "tests/unit/f8/"]` (mais atualização de `web/dist/` gerada pela build F9). | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `scripts/verify_fixtures.py` e `sha256sum -c checksums.sha256` aprovados; `contracts/fixtures/checksums.sha256` intacto (`4b7a39a4ad5d8eb6b48d2d28d8e8a3673e38105bce057909dbdb29884ef0cc7a`); zero diff em `contracts/`, `tests/oracles/` e `control_lab/identification/`. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | `IdentificationWorkspace` consome exclusivamente envelopes `RpcResponse` v1.0 do motor Python/Worker (`identification.fit_arx`, `identification.fit_subspace`, `identification.validate_model`, `core.reuse_model`), preservando `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma tolerância científica foi relaxada; a recuperação ARX em PRBS satisfaz erro $< 10^{-14}$ (muito abaixo do limite normativo de `T-ID-01`) e as bandas de confiança de resíduos (95% e 99%) vêm diretamente do motor Python F4. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `parseCsvToDatasetDto` e `splitDatasetDtoTrainHoldout` validam monotonia estrita de `t`, dimensões de canais, fração de treino em $(0.1, 0.9)$ e disjunção `trainId !== valId`, lançando `ControlLabBridgeError` (`VALIDATION_ERROR`, `DIMENSION_MISMATCH`, `UNSUPPORTED_MODEL`). `dt` e unidades são preservados na derivação `core.reuse_model` para SISO e LQR. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Testados em `tests/unit/f8/identification_vertical.test.ts` e no navegador real: dataset com entrada constante sem persistência de excitação (`T-ID-02`, `PERSISTENCE_OF_EXCITATION_INSUFFICIENT`, `RANK_DEFICIENT_REGRESSION`), CSV com tempo não estritamente crescente e tentativa de particionamento com `trainId === valId`. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Toda comunicação com o Worker Pyodide passa pelo cliente tipado F7 com clones JSON finitos; testes `F7-PYPROXY-01/02` (`92/92`) e suíte Wasm/E2E (`26/26`) aprovados com zero vazamentos. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Painel `#identification-workspace-panel` possui controles `.touch-control` com `<label>` e `aria-label`, região `#id-diagnostics-panel` com `aria-live="polite"`, anúncios `AriaLiveAnnouncer`, gráficos SVG com marcadores distintos por série e `<title>`, tabelas equivalentes acessíveis WCAG 2.2 AA (`buildAccessibleChartTable`) e preservação integral do bloqueio de exportação em `Fast-Preview`. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não é entrega da `F6`; o contrato de 5 dimensões da `F6` permanece intacto. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `T-ID-01`, `T-ID-02`, `T-ID-03` e `R-06`/`T-ID-04` aprovados; `node scripts/run_web_tests.mjs --scope f8` (`29/29`), `--scope all` (`92/92`), `pytest tests/unit/f4/test_identification.py` (`11/11`) e `pytest tests/wasm tests/e2e` (`26/26`) passaram com zero falhas e zero skips. | CONFORME |

---

## 5. Assinatura da Auditoria Independente F9

- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `18654f5bcb7a0c48df3a9c50c24f73e91f498e17`
- **Data (UTC)**: `2026-11-18T23:10:00Z`
- **Parecer F9**: accepted
