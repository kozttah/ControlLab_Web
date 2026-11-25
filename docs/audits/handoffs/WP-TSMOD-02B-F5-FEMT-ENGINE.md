# Handoff e Parecer F9 — `WP-TSMOD-02B-F5-FEMT-ENGINE`

- **WorkPackage**: `WP-TSMOD-02B-F5-FEMT-ENGINE`
- **Frente Produtora**: `F5 (f5-fuzzy-ts)` — Motor de Transformação por Elementos Finitos (FEMT: SVD Global Eckart–Young–Mirsky, Interpolação $P_1$ Baricêntrica `kuhn_delaunay` / `delaunay` e Salvaguarda CNO Escalável para $r \ge 7$)
- **Commit Base**: `e95a7bdd57b7f592cb50d5df5dcaf835bf6c09d9`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-04`, `R-05`, `R-21`, `R-27`, Apêndice E), `ADR-006`, `CL-TS-MOD-DIR-001 v1.0.0` (Seções 4.5, 5, 6 e `T-TSMOD-05`, `T-TSMOD-08`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-25T12:08:30Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Verificação via `git status --short` e `git diff --check` confirmou isolamento estrito de propriedade da Frente F5 (`control_lab/fuzzy/` e `tests/unit/f5/`), sem qualquer alteração em `contracts/`, `tests/oracles/`, `tests/security/`, `web/` ou outras frentes produtoras.

| Artefato F5 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/fuzzy/femt.py` | `b4ee8f83926b4acf1a2ef1e2240eb699369463f0a59593a77da14bd2ea41b3fd` | Motor FEMT em NumPy/SciPy puro (zero `linalg.inv`, zero `eval`/`exec`): `femt_svd_decompose` (SVD matricial econômica globalmente ótima com erros exatos de Eckart–Young–Mirsky), `evaluate_femt_kuhn_delaunay` ($O(D \log D)$ e memória $O(1)$ sem materializar simplices), `evaluate_femt_delaunay` (`scipy.spatial.Delaunay` + `scipy.linalg.solve` + clamping seguro), e pipeline `derive_ts_femt` com guardas pré-alocação Wasm (`RESOURCE_LIMIT`), auditoria nodal e fora dos nós (`ModelFidelityCertificate`) e serialização canônica `TSStateSpace`. |
| `control_lab/fuzzy/tpmt.py` | `fd1ec6bf596d46ec878714558d1ff42aaf570cfbed82ac23cd75b52c86658897` | Salvaguarda escalável para `cno_matrix` em posto global $r \ge 7$ (`_extract_directional_extremes` com extremos coordenados, diagonais pareadas e direções unitárias determinísticas na esfera em $\mathbb{R}^{r-1}$ evitando explosão combinatória do Qhull), vetorização do Jacobiano das restrições SLSQP e verificação integral de SN/NN em todas as linhas `U_arr @ T_cand` com fallback seguro para `RNO-INO`. |
| `control_lab/fuzzy/ts_bridge.py` | `a058d0034258ddba082341faabea0d35ebaf4168f420e8f4e7f0b46c2cdd39b8` | Suporte a `representation_kind == "femt_simplicial"` em `evaluate_ts_premise_weights(...)` tanto para `mesh_kind == "kuhn_delaunay"` quanto `"delaunay"`, com suporte a mapeamento de premissas, vetor de premissas ativas ou vetor completo de estados e clamping preservando partição de Ruspini. |
| `control_lab/fuzzy/__init__.py` | `64dd41334e8abee539a88361c2bb41c5ba33955901e5630a19c0e80fc60bbe54` | Reexportação da API pública FEMT (`FEMTSVDResult`, `femt_svd_decompose`, `evaluate_femt_kuhn_delaunay`, `evaluate_femt_delaunay`, `derive_ts_femt`, `SUPPORTED_FEMT_MESH_KINDS` e limites Wasm `MAX_FEMT_*`). |
| `tests/unit/f5/test_femt_engine.py` | `398010e6026625f8171c3fd004770491161434dcd119f5cc468f0f542c42e3ce` | Cobertura unitária normativa de `T-TSMOD-08` (a–e) e `T-TSMOD-05` (todos os fechos convexos + posto global $r \ge 7$, schema Draft 2020-12, AST gate zero `inv`/`eval` e guardas Wasm). |

---

## 2. Verificações Independentes e Oráculos Executados pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de propriedade** (`git status --short`, `git diff --check`) | Apenas 5 arquivos em `control_lab/fuzzy/` e `tests/unit/f5/`; `git diff --check` exit `0`. | Ownership F5 (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Segurança AST / Zero `inv`** (`R-21` / `CL-DIR-001`) | Inspeção AST independente em `femt.py`, `tpmt.py` e `ts_bridge.py`: **0** ocorrências de `eval`, `exec`, `compile`, `getattr`, `.inv()` ou `from ... import inv`. | `R-21` / Zero `linalg.inv` | PASS |
| **Oráculo `T-TSMOD-08(a)` — Eckart–Young–Mirsky** | Confronto de `femt_svd_decompose` e `derive_ts_femt` (com fecho `CNO`) para $R = 1, 2, 3, 4, 5$ em matriz qLPV `(121, 4, 3)` contra `np.linalg.svd` independente: `max_ey_frob_diff = 0.000e+00`, `max_ey_spec_diff = 0.000e+00`, `max_grid_frob_diff = 8.882e-16` (invariância nodal exata após `CNO`). | Erro nodal Frobenius $=\sqrt{\sum_{k>R}\sigma_k^2}$ e espectral $=\sigma_{R+1}$ (`T-TSMOD-08`) | PASS |
| **Oráculo `T-TSMOD-08(b)` — Redução estrita de regras vs TPMT** | Sistema 2D com termos acoplados $\sin(x_1+x_2)$ e $\cos(x_1-x_2)$: $N_r^{\text{FEMT}} = 3 < N_r^{\text{TPMT}} = 9$ com `grid_rel_l2_error = 3.522e-16`. Sistema 3D com $\sin(x_1+x_2+x_3)$: $N_r^{\text{FEMT}} = 2 < N_r^{\text{TPMT}} = 27$ com `grid_rel_l2_error <= 1e-12`. | $N_r^{\text{FEMT}} < N_r^{\text{TPMT}}$ e exatidão nodal $\le 10^{-12}$ (`T-TSMOD-08`) | PASS |
| **Oráculo `T-TSMOD-08(c)` — Interpolação $P_1$ baricêntrica & $O(h^2)$** | Testado em 1D, 2D e 3D em pontos interiores e fora da caixa (clamping) para `kuhn_delaunay` e `delaunay`: `min_w = 0.000e+00 >= -1e-14`, `max_sum_dev = 2.220e-16 <= 1e-13`, `max_node_err = 5.551e-17`. Convergência quadrática $O(h^2)$ avaliada sobre conjunto fixo independente de 2000 pontos ($G = 9 \to 17 \to 33$): `kuhn_delaunay` razões `(3.855, 3.976)` e `delaunay` razões `(3.917, 3.946)`. | $h_r(p) \ge -10^{-14}$, $|\sum h_r - 1| \le 10^{-13}$, exatidão nodal e ~4× redução de erro $O(h^2)$ (`T-TSMOD-08`) | PASS |
| **Oráculo `T-TSMOD-08(d)` & `T-TSMOD-05` — Posto alto $r \ge 7$ + Schema + `ts_bridge` + `ADR-006`** | `derive_ts_femt` com posto global exato `r = 8` em `CNO` completou em **1.230s** (`N_r = 8`, `used_directional_prefilter = True`, `used_convex_hull = False`, `grid_rel_l2 = 9.129e-16`, `min_w = -3.107e-17`, `sum_dev = 3.109e-15`); `cno_matrix` sintético `r = 9` (250 pontos) completou em **2.208s** (`min_w = -1.579e-17`, `sum_dev = 8.882e-16`). `TSStateSpace.to_dict()` validado 100% contra `contracts/schemas/ts_state_space.schema.json` (Draft 2020-12) para `kuhn_delaunay` e `delaunay`, com `evaluate_ts_premise_weights` (interior + clamping) e `make_pdc_spec` (`ADR-006`/`R-05`: `ts_partially_observed` bloqueia `pdc` com `HYPOTHESIS_VIOLATED` e permite `robust_single_gain`). | Posto $r \ge 7$ sem travar Qhull, Schema Draft 2020-12, `R-05`/`ADR-006` (`T-TSMOD-05`/`08`) | PASS |
| **Guarda de Pré-Alocação Wasm** | `derive_ts_femt` com `grid_points=[100_000, 100_000]` ($10^{10}$ nós) rejeitado em **0.43 ms** com `RESOURCE_LIMIT` antes de alocar qualquer array; bloqueios adicionais para `D > 5`, `delaunay` com `D > 3` ou `N_g > 50_000`, `N_g > 250_000` e `N_g * M > 10_000_000`. | Envelope Wasm (`CL-TS-MOD-DIR-001` Seção 4.5 / 5) | PASS |
| **Regressão completa (`pytest`)** | `/home/antigravity/.venv/bin/pytest tests/unit/f5/ tests/oracles/ tests/security --ignore=tests/security/test_real_browser_security.py -q`: **448 passed, 0 failed, 0 skipped** em `60.86s` (`exit 0`). | Sem regressões | PASS |

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `TSStateSpace.to_dict()` derivado por `derive_ts_femt` (tanto `kuhn_delaunay` quanto `delaunay`) validado estritamente contra `contracts/schemas/ts_state_space.schema.json` (Draft 2020-12) + round-trip `TSStateSpace.from_dict()` + integração com `evaluate_ts_premise_weights` e `make_pdc_spec`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `derive_ts_femt` e `evaluate_ts_premise_weights` retornam `Result` padronizado com `status`, `assumptions`, `diagnostics`, `provenance`, `warnings` e `error` tipado (`ValidationError`, `DimensionMismatchError`, `ResourceLimitError`, `HypothesisViolatedError`) sem fallback silencioso (`R-04`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `test_femt_engine.py` valida identidades de Eckart–Young–Mirsky, redução analítica de posto em sistemas acoplados 2D/3D, exatidão nodal, partição de Ruspini em 1D..4D e taxa de convergência $O(h^2)$. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Oráculos independentes executados pela F9: conferência de `femt_svd_decompose` e `derive_ts_femt` ($R=1..5$) contra `np.linalg.svd` independente, comparação direta `FEMT` vs `TPMT`, convergência $O(h^2)$ em conjunto fixo independente de 2000 pontos (`3.855/3.976` e `3.917/3.946`), benchmark `CNO` para `r=8` (`1.230s`) e `r=9` (`2.208s`), e teste de pré-alocação com $10^{10}$ nós (`0.43 ms`). | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | `git status --short` confirma alterações exclusivas em `control_lab/fuzzy/` e `tests/unit/f5/`; zero modificações em `contracts/fixtures/` ou `tests/oracles/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Implementação 100% Python + NumPy/SciPy (`scipy.linalg.solve`, `scipy.spatial.Delaunay`, `scipy.optimize.minimize`, `scipy.stats.qmc`), sem dependências externas fora do Pyodide (`R-27`). Validação em Wasm será consolidada em `WP-TSMOD-05-F9`. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma alteração de schema; `TSStateSpace` com `representation_kind="femt_simplicial"` adere integralmente a `ts_state_space.schema.json` v1.0.0 existente. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256 dos 5 artefatos, métricas dos oráculos independentes (`max_grid_frob_diff = 8.882e-16`, razões $O(h^2)$ `3.976`/`3.946`, `CNO r=8` em `1.230s`, guarda Wasm `0.43 ms`) e regressão (`448 passed`) registrados neste parecer. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Não introduz métodos experimentais; `control_lab/experimental/sdp_educational/` permanece inalterado e isolado. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Limites de envelope Wasm (`D > 5`, `delaunay` com `D > 3` ou `N_g > 50_000` recomendando `kuhn_delaunay`, `N_g > 250_000`, `N_g * M > 10_000_000`, `N_r > 256`), sistemas LTI constantes, domínios degenerados e `NN_VIOLATED` em `MGK` emitem erros/alertas tipados com `next_step` claro. | CONFORME |

---

## 4. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit Base Auditado**: `e95a7bdd57b7f592cb50d5df5dcaf835bf6c09d9`
- **Data (UTC)**: `2026-11-25T12:08:30Z`
