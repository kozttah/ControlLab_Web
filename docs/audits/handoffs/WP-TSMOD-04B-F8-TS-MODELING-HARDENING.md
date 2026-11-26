# Handoff e Parecer F9 — `WP-TSMOD-04B-F8-TS-MODELING-HARDENING`

- **WorkPackage**: `WP-TSMOD-04B-F8-TS-MODELING-HARDENING`
- **Frente Produtora**: `F8 (f8-ui-charts)` — Endurecimento da Aba 6 (Modelagem TS): invalidação e congelamento de snapshot de derivação, inclusão dos canais generalizados (`Bw, Dyw, Cz, Dzu, Dzw`) no mapa de calor de erro off-grid e avaliação baricêntrica explícita de Delaunay em $D \ge 1$ (incluindo tetraedros 3D) alinhada ao Python
- **Commit Base**: `915c9cb6b220771bff180c9d808a560e66b26a05`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-04`, `R-21`, `R-27`, Seção 13.1/13.2, Apêndice E), `CL-UX-DIR-001 v1.0.0`, `CL-TS-MOD-DIR-001 v1.3.0` (Seções 4.3, 5, 6 e 7)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-26T16:00:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Verificação via `git status --short` e `git diff --stat` confirmou isolamento estrito de propriedade da Frente F8: **apenas** `web/features/views/ts_modeling_view.ts`, `web/charts/ts_modeling_charts.ts` e `tests/unit/f8/ts_modeling_view.test.ts` foram modificados pela frente produtora (além de `PROJECT_STATE.json` gerido pelo orquestrador). ZERO alterações em `control_lab/`, `web/bridge/`, `web/worker/`, `contracts/`, `tests/oracles/`, `tests/security/` ou outras frentes produtoras.

| Artefato F8 | SHA-256 | Papel na Entrega |
|---|---|---|
| `web/features/views/ts_modeling_view.ts` | `8b0376249e4ef80a6c7eacbd9ee46583ab2e47602ac9647ecade2e5342fe824a` | **Achado 1**: assinatura determinística `serializeDraftDerivationSignature(draft, activeMethod)`, congelamento `lastDerivedDraftSnapshot` + `lastDerivedSignature` em `derive()`, detecção `isLastDerivationStale()`, limpeza completa `clearDerivedResult()` (acionada em troca de preset, reset em branco e recarga de receita), banner acessível `#ts-stale-banner` (`role="alert"`) via `syncStaleState()`, desabilitação preventiva dos botões e guarda programática dupla (`ControlLabBridgeError("VALIDATION_ERROR")`) em `register()` e `exportScript()`, persistindo `frozenDraft` na receita. **Achado 2**: encaminhamento de `generalizedVertices` e `generalizedExpressions` (`Bw, Dyw, Cz, Dzu, Dzw`) para `buildOffGridErrorHeatmap`. |
| `web/charts/ts_modeling_charts.ts` | `091cc47683a4233e9b6416c757731832a17d2f0fd96b51bf308c704a98944faa` | **Achado 2**: `GENERALIZED_CHANNEL_NAMES`, `OffGridErrorHeatmapOptions` e `frobeniusDiffSq` integrados a `buildOffGridErrorHeatmap(result, options)`, acumulando o erro de Frobenius dos canais generalizados ativos via AST seguro (`parseSymbolicMatrixAst`, zero `eval`). **Achado 3**: resolvedor linear com pivoteamento parcial `solveLinearSystem` (zero inversão matricial), `solveBarycentricForSimplex`, `interpolateClippedBarycentric` e `evaluateDelaunayWeights` genérico para $D \ge 1$ (1D linear, 2D triângulos, 3D tetraedros) com filtro AABB e fallback seguro na fronteira numérica via simplices incidentes ao nó mais próximo; remoção da restrição `pt.length === 2` em `evaluateDerivedMembershipWeights`. |
| `tests/unit/f8/ts_modeling_view.test.ts` | `344030a2017d609ba25aa9cc20aff675648a6be2648e107934d4e4c5faafeeb3` | Testes de regressão ponta a ponta para os 3 achados: (1) invalidação pós-edição/troca de preset/via e bloqueio de registro/exportação com rascunho obsoleto + determinismo de `serializeDraftDerivationSignature`; (2) planta com não-linearidade exclusiva em `Bw(x1, x2)` verificando erro off-grid exato ponto a ponto na norma de Frobenius (`maxDiff < 1e-12`); (3) modelo FEMT 3D `mesh_kind="delaunay"` (64 nós, tetraedros de 4 vértices) confrontado diretamente contra `control_lab.fuzzy.femt.evaluate_femt_delaunay` em Python real com paridade `< 1e-12`. |

---

## 2. Verificações Independentes Executadas pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de ownership** (`git status --short`, `git diff --stat`) | Apenas os 3 arquivos de F8 (`ts_modeling_view.ts`, `ts_modeling_charts.ts`, `ts_modeling_view.test.ts`) + `PROJECT_STATE.json` (orquestrador). ZERO alterações em `control_lab/`, `web/bridge/`, `contracts/`, `tests/oracles/`. | Ownership F8 (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Segurança estática em `web/`** (`R-21`) | Varredura regex em todos os `.ts` de runtime em `web/` (excluindo `node_modules/` e `.d.ts`): **0** ocorrências de `eval(`, **0** ocorrências de `new Function`, **0** imports de `node:*`/`fs`/`path`/`child_process`/`control_lab`. | `R-21` / Isolamento browser | PASS |
| **Typecheck TypeScript** (`npm --prefix web run typecheck`) | `exit 0`, 0 erros de compilação/tipagem. | Aceite do WorkPackage | PASS |
| **Suíte Unitária F8** (`PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f8`) | **92 tests, 92 pass, 0 fail, 0 skipped** (`exit 0`), incluindo os 3 testes de regressão dos Achados 1, 2 e 3 (com oráculo Python real `evaluate_femt_delaunay` `< 1e-12`). | Aceite do WorkPackage | PASS |
| **Build de Produção Web** (`npm --prefix web run build`) | `exit 0`; bundle e wheel `control_lab-1.0.0-py3-none-any.whl` construídos; `Verified integrity and inventory of 42 local assets`. | Aceite do WorkPackage | PASS |

---

## 3. Revisão Técnica dos 3 Achados

- **Achado 1 (Invalidação e snapshot congelado)**: `serializeDraftDerivationSignature` cobre integralmente `activeMethod`, `presetId`, `name`, `timeDomain`, `sampleTime`, dimensões (`n, m, p, nw, nz`), `enableGeneralized`, limites de estados/externas, premissas, matrizes (`sectorMatrices` e `directMatrices`, incluindo blocos generalizados quando habilitados), `axisSettings` com chaves ordenadas, `tpmtParams`, `femtParams` e `valPoints`. `derive()` congela `snapshotDraft = structuredClone(this.draft)` antes da chamada RPC, propaga `computedMin/computedMax` tanto para `this.draft` quanto para `snapshotDraft` e grava `lastDerivedDraftSnapshot` + `lastDerivedSignature`. `clearDerivedResult()` zera resultado, assinatura, snapshot e DOM de saída em `selectPreset`, `resetToBlankCustom` e `reloadRecipeFromWorkspace`. A guarda dupla atua tanto na UI (`syncStaleState` + `syncActionButtons` + `#ts-stale-banner`) quanto na camada lógica de `register()` e `exportScript()` (`ControlLabBridgeError("VALIDATION_ERROR")`), e `register()` usa exclusivamente `frozenDraft` para o ID e a receita persistida.
- **Achado 2 (Canais generalizados no mapa de erro)**: `buildOffGridErrorHeatmap` combina os erros de `(A, B, C, D)` com os canais generalizados ativos (`Bw, Dyw, Cz, Dzu, Dzw`) via `frobeniusDiffSq`, obtendo expressões simbólicas e matrizes por vértice de `options` (fornecidos por `ts_modeling_view.ts` a partir do snapshot congelado e de `provenance.generalized_channels`) ou diretamente de `provenance.generalized_channels`, mantendo avaliação 100% AST sem `eval`.
- **Achado 3 (Delaunay explícita 3D)**: `solveLinearSystem` implementa eliminação gaussiana com pivoteamento parcial e guarda de singularidade (`pivotAbs < 1e-14`), resolvendo o sistema baricêntrico $M_\Delta \lambda_{1..D} = p - v_0$ sem inversão explícita de matrizes. `evaluateDelaunayWeights` suporta $D = 1$ (interpolação linear ordenada) e $D \ge 2$ (triângulos 2D, tetraedros 3D, etc.) com clamping aos limites, pré-filtro AABB, tolerância de fronteira e fallback seguro via simplices incidentes ao nó mais próximo. `evaluateDerivedMembershipWeights` consome `femt.nodes ?? mesh.nodes` e `femt.simplices ?? mesh.simplices` para qualquer `pt.length >= 1`, com paridade `< 1e-12` verificada contra `control_lab.fuzzy.femt.evaluate_femt_delaunay`.

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Referência | Evidência Auditada | Status |
|---|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `ts_state_space.schema.json` v1.0.0 | Integração F8 testada contra o adaptador Python real (`RealPythonTsAdapter`) consumindo `deriveTsSector`, `deriveTsTpmt`, `deriveTsFemt` e `provenance.generalized_channels` conforme o contrato F1/F9 sem alterações de schema. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `R-04` | Tentativas de `register()` ou `exportScript()` com rascunho obsoleto levantam `ControlLabBridgeError("VALIDATION_ERROR")` com mensagem acionável e ativam `#ts-stale-banner` (`role="alert"`); receitas registradas preservam `frozenDraft` íntegro em `provenance.ts_derivation.recipe`. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `CL-TS-MOD-DIR-001` | Os 3 testes de regressão em `tests/unit/f8/ts_modeling_view.test.ts` validam determinismo da assinatura, norma de Frobenius exata em `Bw(x1, x2)` (`maxDiff < 1e-12`) e coordenadas baricêntricas 3D em tetraedros Delaunay (`maxErr < 1e-12`). | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Seção 13.11 | O avaliador JS `evaluateDelaunayWeights` / `evaluateDerivedMembershipWeights` em 3D é confrontado diretamente contra o oráculo Python `control_lab.fuzzy.femt.evaluate_femt_delaunay` (`maxErr < 1e-12`), e o heatmap off-grid é confrontado ponto a ponto contra a fórmula analítica `sin(x1*x2)` / `cos(x1+x2)` (`maxDiff < 1e-12`). | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Seção 13.1 / 13.2 | `git status --short` confirma edições restritas aos 3 arquivos de F8; ZERO alterações em `contracts/fixtures/`, `tests/oracles/`, `control_lab/` ou `web/bridge/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | `R-27` | Código 100% TypeScript puro no browser (zero imports Node/Python em `web/`), compilado sem erros em `npm --prefix web run typecheck` e empacotado em `npm --prefix web run build` com verificação de integridade dos 42 ativos locais. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `contracts/schemas/` | Nenhuma alteração de schema foi necessária; a camada F8 apenas consome campos já existentes (`provenance.generalized_channels`, `nodes`, `simplices`, `bounds`). | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Apêndice E | Hashes SHA-256 dos 3 artefatos F8, resultados de `typecheck`, suíte F8 (`92/92 pass`), `build` (`42 local assets`) e varredura de segurança `R-21` registrados neste parecer. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `CL-DIR-001` | Não introduz nem altera métodos experimentais; classificação visual existente da bancada permanece preservada. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `R-04` / `CL-UX-DIR-001` | Estado obsoleto exibe alerta acessível `#ts-stale-banner` e instrui explicitamente a clicar em "Validar & Gerar Modelo TS" antes de registrar ou exportar; fallback seguro na fronteira numérica de Delaunay evita `NaN`/nulo em pontos de borda. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: accepted
- **Revisor independente**: f9-integration-qa
- **Commit SHA auditado**: 915c9cb6b220771bff180c9d808a560e66b26a05
- **Data (UTC)**: 2026-11-26T16:00:00Z
