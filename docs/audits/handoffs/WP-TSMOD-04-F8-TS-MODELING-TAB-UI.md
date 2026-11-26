# Handoff & Auditoria Independente F9 — `WP-TSMOD-04-F8-TS-MODELING-TAB-UI`

## 1. Escopo Auditado e Isolamento de Propriedade (`CL-TS-MOD-DIR-001 v1.1.0` & `CL-UX-DIR-001 v1.0.0`)

Auditoria independente conduzida pela Frente `F9 (f9-integration-qa)` sobre a reimplementação integral da Aba 6 (`ts_modeling` — `6. Obtenção de Modelos TS (Setor, TPMT & FEMT)`) entregue pela Frente `F8 (f8-ui-charts)` para o pacote `WP-TSMOD-04-F8-TS-MODELING-TAB-UI`.

- **Verificação estrita de ownership (`AGENTS.md` §2 e §2.1):** Fora a reabertura administrativa em `PROJECT_STATE.json` e a substituição deste relatório em `docs/audits/handoffs/WP-TSMOD-04-F8-TS-MODELING-TAB-UI.md`, o `git status` / `git diff` comprova que **somente** caminhos sob responsabilidade da `F8` foram criados ou editados:
  - `web/features/ts_modeling/symbolic_qlpv_ast.ts` (novo parser recursivo descendente e avaliador AST seguro zero-`eval`)
  - `web/features/views/ts_modeling_view.ts` (bancada completa de 4 zonas, edição customizada livre LPV/qLPV, Vias 1/2/3, comparador, inspetor de vértices, promoção ao Workspace Dock e recarga de receita)
  - `web/charts/ts_modeling_charts.ts` (5 modelos e renderizadores SVG determinísticos WCAG 2.2 AA + avaliadores contínuos 1D, Delaunay 2D e Kuhn–Delaunay $O(D \log D)$)
  - `web/app/main.ts`, `web/app/workspace_dock.ts`, `web/app/styles.css` e `web/app/tool_descriptor.ts` (7 abas com `ts_modeling` na posição 6 e `optimization_lmi` na posição 7, roteamento bidirecional `→ LMIs` e `→ Receita TS`)
  - `tests/unit/f8/ts_modeling_view.test.ts`
- Nenhum arquivo de `contracts/`, `control_lab/`, `tests/unit/f1/`, `tests/unit/f5/`, `tests/unit/f7/` ou `tests/oracles/` foi modificado.

---

## 2. Verificação Normativa das 4 Zonas e Segurança (`R-04`, `R-05`, `R-21`, `R-27`, `T-TSMOD-*`)

1. **Navegação Global de 7 Abas (`CL-TS-MOD-DIR-001` §1.2):** `PROJECT_TAB_IDS` possui exatamente 7 abas na ordem normativa (`fuzzy_ts` em `5.`, `ts_modeling` em `6. Obtenção de Modelos TS (Setor, TPMT & FEMT)` e `optimization_lmi` em `7. LMIs, SDPs e Síntese Robusta`).
2. **Zona 1 & Zona 2 — Entrada Livre de Sistemas LPV/qLPV Customizados (`CL-TS-MOD-DIR-001` §2, `ADR-014`):**
   - Além dos 4 exemplos didáticos (`pendulum_16`, `pendulum_2d`, `nonseparable_benchmark`, `external_lpv`), o usuário dispõe de **Limpar / Novo Sistema** (`custom`) e gaveta **JSON qLPV** bidirecional.
   - Suporte completo a domínio contínuo e discreto (`dt > 0`), redimensionamento livre de `(n, m, p)` e canais generalizados `(Bw, Dyw, Cz, Dzu, Dzw)` com dimensões `(nw, nz)`, adição/remoção de sinais externos `w_ext`, limites compactos `[min, max]`, unidades e flags individuais de medição com inferência imediata entre `ts_measured` e `ts_partially_observed`.
3. **Zona 3 — Três Vias Complementares (`CL-TS-MOD-DIR-001` §3, §4, §5):**
   - **Via 1 (Não-Linearidade de Setor):** tabela editável de premissas `z_k = g_k(x, w_ext)` (adicionar/remover/editar), detecção automática de `sin(E)/E` com conversão em 1 clique para `sinc_rad(E)`, busca híbrida global de `[z_min, z_max]` via RPC `fuzzy.analyze_sector_premises`, override manual seguro (rejeitando estreitamento de intervalo que viole $w_{k,j} \ge 0$), edição célula a célula de `A(z), B(z), C(z), D(z)` (+ canais generalizados) e diagnóstico imediato de isolamento de variáveis e afinidade multilinear (respaldado pela validação autoritativa do backend Python em `derive_ts_sector`, conforme `R-05`).
   - **Via 2 (TPMT):** edição direta de `S(x, w_ext)` (com atalho algébrico `Copiar S(z) → S(x,w)` preservando precedência na AST), extração automática das variáveis não-lineares ativas `p = (p_1, ..., p_D)` poupando estados puramente lineares, cálculo preventivo do envelope de memória Wasm (`D`, `N_g`, elementos do tensor e MB estimados), tabela individual por dimensão (`G_d`, posto `R_d`, fecho `CNO`/`RNO-INO`/`SN-NN`/`MGK`, grade fina `linear`/`pchip`) e seleção `HOSVD`/`HOOI`.
   - **Via 3 (FEMT):** edição direta de `S(x, w_ext)`, discretização nodal `G_d` por eixo ativo, posto global `R` (automático Eckart–Young ou manual), fecho convexo global (`CNO`, `RNO-INO`, `SN-NN`, `MGK`) e malha simplicial $P_1$ (`kuhn_delaunay` ou `delaunay`).
4. **Zona 4A & Zona 4B — Certificado, Inspetor, Gráficos WCAG AA e Ciclo Workspace (`CL-TS-MOD-DIR-001` §6, `CL-UX-DIR-001`):**
   - Exibição honesta do `fidelity_certificate` (`EXACT_ANALYTICAL_SECTOR`, `EXACT_ON_GRID_TPMT`, `EXACT_NODAL_FEMT`, `APPROXIMATE_*`), erro relativo na grade e fora da grade, erro máximo $\|\Delta S\|_F$, $\min h_r$, $\max|\sum_r h_r - 1|$, cota de De Lathauwer (TPMT) e erro nodal de Eckart–Young (FEMT).
   - Comparativo direto entre vias na planta atual (`#btn-ts-compare`), confirmando redução estrita de regras $N_r(\text{FEMT}) < N_r(\text{TPMT})$ em plantas com não-linearidades acopladas (`T-TSMOD-08`).
   - Inspetor interativo das matrizes vértices `(A_r, B_r, C_r, D_r)` e expressão de `h_r` por regra.
   - 5 gráficos SVG acessíveis (`role="img"`, `<title>`, `<desc>`, tabelas acessíveis `<details>` e exportação `[SVG]`): (1) pertinências 1D, (2) superfície/malha simplicial 2D (`delaunay` e `kuhn_delaunay`), (3) comparador de bases `U` vs `W`, (4) scree plot logarítmico de valores singulares e (5) mapa de calor real fora da grade de $\|S(p) - \hat{S}_{\text{TS}}(p)\|_F$ avaliado nos centros deslocados de subcélulas sobre $\Omega$.
   - Promoção em 1 clique ao `TypedObjectWorkspace` (`#btn-ts-register` e `#btn-ts-register-open-lmi`), botão `→ Receita TS` no `WorkspaceDockController`, recarga completa de receita (incluindo reconstrução pura a partir de `provenance.ts_derivation` nativo sem depender de rascunho de UI) e exportação passiva (`code_executed: false`) de scripts Python e MATLAB.
5. **Segurança `R-21` (`T-TSMOD-01`):** Varredura estática independente e oráculo dinâmico F9 confirmaram **zero** ocorrências de `eval`, `Function(...)` ou `new Function` em `symbolic_qlpv_ast.ts`, `ts_modeling_view.ts` e `ts_modeling_charts.ts`, rejeição determinística de atributos/dunders (`__import__`, `x1.__class__`, `window.location`) e escape sistemático via `escapeHtml` em todas as interpolações HTML.

---

## 3. Evidências Reproduzíveis de Execução Independente F9

1. **Typecheck estrito do frontend (`tsc --noEmit`):**
   - Comando: `npm --prefix web run typecheck` -> **PASS (exit 0)**.
2. **Suíte unitária/integração F8 + Empacotamento Web/Wheel de Produção:**
   - Comando: `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f8 && npm --prefix web run build`
   - Resultado: **`[typecheck] PASS (f8, 42 arquivo(s) TS)`**, **`89/89` testes F8 aprovados (`0` falhas)** — incluindo `tests/unit/f8/ts_modeling_view.test.ts` exercitando o motor Python real `control_lab.core.rpc` — e **`Verified integrity and inventory of 42 local assets`**.
3. **Oráculos Independentes F9 para `symbolic_qlpv_ast.ts` e `ts_modeling_charts.ts`:**
   - Continuidade $C^\infty$ de `sincRad(u)` em $u \in \{0, \pm 10^{-12}, \pm 10^{-8}, 9.999\times 10^{-5}, 1.0001\times 10^{-4}\}$ com erro $< 10^{-15}$;
   - Interpolação baricêntrica $P_1$ Kuhn–Delaunay 3D (`evaluateKuhnDelaunayWeights`): partição de unidade $|\sum_r h_r(p) - 1| \le 10^{-14}$, $h_r(p) \ge 0$ e reprodução exata de funções afins em pontos arbitrários fora da grade;
   - Rejeição determinística de expressões maliciosas e bloqueio de `user_bounds` estreitados que violariam não-negatividade.
4. **Regressão Científica Python, Contratos, Oráculos e Segurança:**
   - Comando: `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f5 tests/unit/f1 tests/oracles tests/security --ignore=tests/security/test_real_browser_security.py -q`
   - Resultado: **`623 passed in 83.90s`**.

### Hashes SHA-256 dos Artefatos Auditados

```text
14c27ad8ad5b15d499245cce9a33cdebf5813d3444ce21f787fad0a328ccf3cc  web/features/ts_modeling/symbolic_qlpv_ast.ts
878016af041634f2dc89cc28db32db2efc65ef91a89dd5eb174be25844d1c9ad  web/features/views/ts_modeling_view.ts
be508237a14024f456cd552848192649f7a552f3d939712e31cbdae5246aad02  web/charts/ts_modeling_charts.ts
d5c0330af65cffde4b7dc2575518d6b850fd8d95c331e4bcd8496543e7368a3c  web/app/main.ts
6a6768c1580b29c81eddc91b71488e53a3d3df3ee2eba839b2967149456d59fe  web/app/workspace_dock.ts
1a8125ae777edcfeef39d3d877fa097d8cea2fa26d8224ef4ae5b5064ec2dd72  web/app/styles.css
be890cd7d74f99a2ff0909c4a483938d20117c3cc04339d744ad4e63d4e75cae  web/app/tool_descriptor.ts
6f02a762779c3bae0f70627ecb9c4e595e36007fb72d0c2210ac2a8415809d44  tests/unit/f8/ts_modeling_view.test.ts
e5ce5bd26663b4d93fe81a45ab539fb5c9a870469fedc90633c5743fab5a79c4  web/dist/release-manifest.json
```

---

## 4. Checklist de Handoff do Apêndice E (10 Itens)

| # | Item Normativo (Apêndice E) | Regra / Escopo | Evidência Objetiva Verificada pela F9 | Status |
| :---: | :--- | :--- | :--- | :---: |
| 1 | Contratos tipados e schemas JSON respeitados | `R-18`, `ADR-014` | Consumo tipado via `supportsTsModeling`, registro de `TSStateSpace` (`ts_measured` e `ts_partially_observed`) no `TypedObjectWorkspace` e recarga integral de `provenance.ts_derivation`. | CONFORME |
| 2 | Diagnósticos estruturados, avisos e proveniência (`R-27`) | `R-04`, `R-27` | Erros tipados `ControlLabBridgeError` apresentados via `shell.presentError`, avisos do backend listados na Zona 4A e receita completa gravada em `provenance.ts_derivation`. | CONFORME |
| 3 | Tolerâncias explícitas e invariantes matemáticos verificados | `T-TSMOD-01..08` | `sincRad(0)=1` suave (`< 1e-15`), partição convexa baricêntrica $P_1$ (`\|∑h_r - 1\| <= 1e-14`, `h_r >= 0`), bloqueio de `user_bounds` estreitados e mapa de calor real de `\|\|S(p) - S_TS(p)\|\|_F` fora da grade. | CONFORME |
| 4 | Não-circularidade científica e validação contra oráculo independente | Seção 13.11, `R-05` | `ts_modeling_view.test.ts` confronta a UI contra o motor Python real (`control_lab.core.rpc`) e a F9 validou `sincRad`, AST e `evaluateKuhnDelaunayWeights` contra fórmulas analíticas fechadas independentes. | CONFORME |
| 5 | Isolamento estrito de propriedade entre frentes (`F1`–`F9`) | `AGENTS.md` §2 | Modificações restritas exclusivamente a `web/features/`, `web/charts/`, `web/app/` e `tests/unit/f8/`; `contracts/`, `control_lab/` e `tests/oracles/` intactos. | CONFORME |
| 6 | Execução limpa das suítes de aceitação e regressão | `CL-DIR-001` §15 | `typecheck` (0 erros), `89/89` testes unitários/integração F8 aprovados, `npm --prefix web run build` íntegro (42 ativos) e `623` testes Python (`f5`, `f1`, `oracles`, `security`) aprovados. | CONFORME |
| 7 | Compatibilidade retroativa de serialização e exportação passiva | `ADR-010`, `ADR-013`, `R-21` | Exportação de scripts Python e MATLAB exige `code_executed === false`, preserva `membership_spec` discriminado (`sector_nonlinearity`, `tpmt_interpolated`, `femt_simplicial`) e mantém round-trip de receitas. | CONFORME |
| 8 | Reprodutibilidade documental (comandos, métricas e hashes) | Apêndice E.8 | Todos os comandos executados, contagens de testes (`89` Web F8 + `623` Python) e hashes SHA-256 dos módulos auditados e do manifesto de build constam na Seção 3 deste parecer. | CONFORME |
| 9 | Honestidade visual de verificação e acessibilidade WCAG 2.2 AA | `CL-UX-DIR-001`, `R-05` | Selos `EXACT_*` vs `APPROXIMATE_*` fiéis ao `fidelity_certificate`, paleta com contraste >= 3:1, `aria-label`/`<title>`/`<desc>` e tabelas acessíveis em todos os 5 cards gráficos. | CONFORME |
| 10 | Limites computacionais Wasm e degradação graciosa documentados | `CL-TS-MOD-DIR-001` §4.5 | Zona 3 calcula preventivamente `D`, `N_g` e MB do tensor/matriz empilhada, alerta acima do teto Wasm (`D > 5`, `N_g > 250k`, `> 10^7` escalares) e oferece exportação offline Python/MATLAB; E2E browser completo segue escopo de `WP-TSMOD-05`. | CONFORME |

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: f9-integration-qa
- **Commit SHA auditado**: c022b3ac77bf6902c8d28eee53c7c5a9462a55d3
- **Data (UTC)**: 2026-11-26T09:46:37Z
