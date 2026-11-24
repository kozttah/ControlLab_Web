# ADR-015 — Escalabilidade do Solver SDP Nativo v2.0 (Memória `wasm32`, HSDE, Esparsidade F1/F2 e Decomposição Cordal)

- **Status:** `ACCEPTED`
- **Data:** `2026-11-22`
- **Autoridade:** `project_coordinator`
- **Relação Normativa:** Complemento direto da [`ADR-010`](ADR-010-native-sdp-and-offline-exports.md) (`CL-DIR-001 v1.0.0`, Seções 6.2, 13.11 e 14.1).
- **Escopo:** Evolução arquitetural da Fase 9 (`Phase9-Native-SDP-Scalability-v2`) para o núcleo SDP primal-dual nativo em Python/NumPy/SciPy (`control_lab/optimization/backends/native_core.py`), transporte Worker/Pyodide (`web/bridge/`, `web/worker/`) e compilador LMI DSL (`web/features/lmi/`).

---

## 1. Contexto e Motivação

Sob a [`ADR-010`](ADR-010-native-sdp-and-offline-exports.md) e as entregas da Fase 5 (`WP-PHASE5-01..05`), o ControlLab Web atingiu execução 100% no navegador (*zero-install*, hospedagem estática em GitHub Pages sobre Pyodide Wasm) com o solver `native_primal_dual` (Nesterov–Todd/Mehrotra + Ruiz + componentes conexas), estabelecendo um envelope interativo de até `448` variáveis (`< 10s`, $n \le 28$ estados em estabilização contínua) e teto estendido de `1024` variáveis / bloco `64` / `65536` entradas cônicas.

Contudo, problemas avançados de controle robusto — em particular sistemas politópicos incertos com muitos vértices ($N_v \ge 9$), sistemas Takagi–Sugeno com múltiplas regras e somas duplas ($\sum_i \sum_j h_i h_j \Upsilon_{ij} \prec 0$), e síntese $\mathcal{H}_\infty$/observadores de ordem mais alta liberados pela [`ADR-014`](ADR-014-workspace-centralized-system-definition.md) — ainda sofrem quatro gargalos estruturais no runtime `wasm32` (limite linear de 2–4 GB, *single-threaded*):

1. **Pressão e fragmentação de memória no transporte e no laço IPM:** listas JSON de tripletos esparsos geram explosão de objetos `PyFloat`/`PyList` em `wasm32`, e alocações repetidas de temporários densos `(m, n, n)` ou matrizes de trabalho a cada iteração Mehrotra fragmentam o heap Wasm; além disso, blocos PSD `1x1` (desigualdades escalares/LP) ainda pagam sobrecusto desnecessário de fatoração matricial.
2. **Custo duplo de inicialização Fase I + Fase II e certificados de infactibilidade:** resolver problemas infactíveis ou mal-inicializados com Fase I separada dobra o custo computacional e oferece menor rigor numérico do que um embedding homogêneo autodual único.
3. **Montagem densa do complemento de Schur `H` e redundância simbólica:** matrizes de base `F_k` em LMIs de controle possuem esparsidade extrema (muitas vezes posto $\le 2$ ou baixo `nnz`) e formulações TS frequentemente introduzem restrições simétricas duplicadas ou colunas linearmente dependentes antes da montagem.
4. **Blocos PSD grandes, conexos porém esparsos (padrões em banda/seta/acoplados):** a decomposição atual por componentes conexas (`_decompose_sparse_psd_blocks`) não divide blocos conexos esparsos, e a fatoração densa $O(m^3)$ do complemento de Schur domina o tempo quando a matriz `H` resultante é simbolicamente esparsa.

---

## 2. Alternativas Rejeitadas e Racional Documentado

O ControlLab Web **mantém estritamente** o princípio arquitetural de **aplicação 100% *zero-install*, hospedada estaticamente e baseada em um único solver nativo NumPy/SciPy (`native_core.py`)** dentro do Pyodide. As quatro alternativas a seguir foram avaliadas e **explicitamente rejeitadas**:

1. **Ponte de Servidor Local (*Local Companion Bridge* em `localhost` CPython):**
   - *Rejeitada:* quebra o princípio *zero-install* de hospedagem estática pura e adiciona fricção de instalação, segurança CORS/loopback e suporte multi-SO. Usuários dispostos a executar Python/MATLAB localmente já contam com os exportadores determinísticos CVXPY e YALMIP (com MOSEK, Clarabel, SeDuMi e SDPT3) previstos na `ADR-010`, sem acoplamento de servidor local.
2. **Compilação de Solvers Externos em Rust/C++ para Wasm (ex.: forks `clarabel.wasm`):**
   - *Rejeitada:* introduz acoplamento rígido a *toolchains* binárias externas (Rust/Emscripten/ABI Pyodide), risco de *lock-in* de licenciamento/manutenção *upstream*, aumento significativo do peso do bundle estático e quebra da auditabilidade em Python puro (`control_lab/optimization/backends/native_core.py`). `clarabel_direct` em CPython permanece exclusivamente como **oráculo independente** (`tests/oracles/`).
3. **`wasm64` e *Wasm Threads* via *shims* COOP/COEP (`coi-serviceworker`):**
   - *Rejeitada:* GitHub Pages não permite configurar cabeçalhos HTTP `Cross-Origin-Opener-Policy` / `Cross-Origin-Embedder-Policy` nativamente; depender de *shims* via Service Worker (`coi-serviceworker`) introduz ciclos frágeis de recarregamento forçado, conflitos com o Service Worker offline do próprio aplicativo e incompatibilidade entre navegadores/políticas corporativas.
4. **Manutenção de uma Segunda Família de Solver de 1ª Ordem (ADMM / SCS):**
   - *Rejeitada:* métodos de 1ª ordem (splitting/ADMM/SCS) sofrem convergência lenta para precisão estrita (`1e-8`) em LMIs de Lyapunov/estabilização mal-condicionadas, introduzem semântica divergente de tolerâncias/status e duplicam o custo de manutenção e auditoria científica. Toda otimização de escalabilidade permanece dentro de um **único solver IPM primal-dual de 2ª ordem**.

---

## 3. Cinco Pilares Arquiteturais (v2.0)

A arquitetura **Native SDP v2.0** apoia-se em cinco pilares complementares, implementados 100% em TypeScript padrão + Python/NumPy/SciPy (já presentes no Pyodide base):

1. **Pilar 1 — Memória `wasm32` Zero-Copy, Workspace *In-Place* e Cone LP 1D Unificado:**
   - Transporte empacotado em `TypedArray` (`Int32Array`/`Float64Array`, formato `F_k_packed`) transferido com *zero-copy* via Web Worker `Transferable` (`ArrayBuffer`) → Pyodide Buffer Protocol (`memoryview` / `np.frombuffer`), eliminando listas JSON de tripletos e a explosão de objetos `PyFloat` na memória linear `wasm32`.
   - Pré-alocação e reutilização *in-place* dos buffers de trabalho do IPM (`H`, `W`, `S`, `dX`, `dZ` via operações `out=...`) para conter a fragmentação do heap `wasm32` ao longo das iterações Mehrotra.
   - Caminho unificado de cone LP vetorial 1D para todos os blocos PSD `1x1` dentro do mesmo IPM primal-dual, eliminando chamadas escalares a `eigh`/`cholesky` sem criar um segundo solver.
2. **Pilar 2 — Embedding Homogêneo Autodual (HSDE) e Múltiplos Corretores de Gondzio:**
   - Formulação em fase única via *Homogeneous Self-Dual Embedding* (HSDE) com variáveis homogêneas $(\tau, \kappa)$, eliminando a execução separada de Fase I + Fase II e fornecendo certificados rigorosos de infactibilidade primal e dual (lema de Farkas) diretamente da convergência $\tau \to 0, \kappa > 0$.
   - Múltiplos corretores de centralidade de Gondzio reutilizando a **mesma** fatoração de Cholesky da iteração ($O(m^2)$ por corretor adicional frente a $O(m^3)$ da fatoração), reduzindo o número total de iterações e fatorações densas.
3. **Pilar 3 — Montagem Esparsa F1/F2 de Fujisawa para o Complemento de Schur:**
   - Seleção adaptativa por bloco entre as fórmulas esparsas **F1** e **F2** (Fujisawa, Kojima & Nakata) explorando `F_k` com baixo `nnz` e posto $\le 2$ típico de LMIs de controle, sem jamais alocar tensores densos intermediários `(m, n, n)`.
4. **Pilar 4 — Pré-processamento Simbólico e Fusão Simétrica de Somas Duplas:**
   - Eliminação simbólica pré-solver de colunas nulas, duplicadas ou linearmente dependentes em `F_k` (com recuperação exata do vetor primal/dual completo pós-resolução).
   - Fusão automática de somas duplas simétricas em LMIs politópicas e Takagi–Sugeno ($\Upsilon_{ij} + \Upsilon_{ji} \prec 0$ para $i < j$) diretamente no compilador `lmi_dsl_compiler.ts`, reduzindo quase pela metade o número de blocos PSD gerados sem perda de suficiência (relaxações de Tuan et al. / Sala & Ariño).
5. **Pilar 5 — Decomposição Cordal, Schur Esparso (`splu`) e Gram Cônico Esparso (`A_cone_csc`):**
   - Decomposição cordal de blocos PSD conexos esparsos por extensão cordal, enumeração de cliques maximais, fusão controlada na árvore de cliques (*clique-tree merging*) e acoplamento de sobreposições usando apenas Python puro + `scipy.sparse.csgraph`, com reconstrução exata dos multiplicadores duais no bloco original antes da auditoria 5D.
   - Fatoração adaptativa esparsa do complemento de Schur via `scipy.sparse.linalg.splu` (SuperLU nativo do SciPy/Pyodide) com ordenações redutoras de preenchimento (`MMD_AT_PLUS_A` / `COLAMD`) quando a densidade simbólica de `H` for `< 25%` e `m ≥ 60`, com recuo transparente (*fallback*) para Cholesky denso nos demais casos.
   - Construção pré-solver esparsa `scipy.sparse.csc_matrix` (`A_cone_csc` + Gram `G_cone_sp`) com verificação de posto cheio $O(\text{nnz})$ via Gershgorin ou `splu` simétrica sem materializar matrizes densas `(total_entries, m)`, habilitando a recalibração segura do `BROWSER_ENVELOPE` para **`1792` rápido / `3072` estendido** (`max_block_dimension = 96`, `max_cone_entries = 131072`).

---

## 4. Plano de Execução em 5 Ciclos (`Phase9-Native-SDP-Scalability-v2`, **118/118 WPs `ACCEPTED_BY_F9`**)

| Ciclo | WorkPackages | Frentes | Status | Trilha de Commits & Evidência Medida |
|---|---|---|---|---|
| **Ciclo 0 (Roadmap)** | `WP-PHASE9-00-F9-SDP-V2-ROADMAP-ADR015` | `F9` | **IMPLEMENTED & ACCEPTED BY F9** | `d20acb8` — Formalização da `ADR-015`, adendo em `ADR-010` e registro dos WPs da Fase 9 em `PROJECT_STATE.json`. |
| **Ciclo 1 (Memória `wasm32` Zero-Copy & Cone LP 1D)** | `WP-PHASE9-01A` (`F6`), `WP-PHASE9-01B` (`F7`), `WP-PHASE9-01C` (`F8`), `WP-PHASE9-01D` (`F9`) | `F6`, `F7`, `F8`, `F9` | **IMPLEMENTED & ACCEPTED BY F9** | `d20acb8` — `F_k_packed` (`Int32Array`/`Float64Array`) via `Transferable` → `memoryview`/`np.frombuffer`, buffers *in-place* (`H, W, S, dX, dZ`), cone LP 1D unificado e auditoria F9 em Chromium Wasm. |
| **Ciclo 2 (HSDE & Gondzio)** | `WP-PHASE9-02` (`F6`), `WP-PHASE9-02B` (`F9`) | `F6`, `F9` | **IMPLEMENTED & ACCEPTED BY F9** | `f776cfb` — HSDE em fase única com certificados Farkas primal/dual e múltiplos corretores de centralidade de Gondzio ($O(m^2)$ sobre a mesma Cholesky); oráculo F9 contra `clarabel_direct` e `T-SDP-A2`/`T-SDP-A3`. |
| **Ciclo 3 (Fujisawa F1/F2 & Pré-processamento / Fusão Simétrica)** | `WP-PHASE9-03` (`F6`), `WP-PHASE9-03B` (`F8`), `WP-PHASE9-03C` (`F9`) | `F6`, `F8`, `F9` | **IMPLEMENTED & ACCEPTED BY F9** | `60c1867` — Fórmulas esparsas F1/F2 de Fujisawa, remoção simbólica de colunas redundantes em `F_k`, fusão simétrica $\Upsilon_{ij} + \Upsilon_{ji} \prec 0$ em `lmi_dsl_compiler.ts` e exibição genérica de `recover` na Aba 6. |
| **Ciclo 4 (Decomposição Cordal & Schur Esparso `splu`)** | `WP-PHASE9-04` (`F6`), `WP-PHASE9-04B` (`F9`) | `F6`, `F9` | **IMPLEMENTED & ACCEPTED BY F9** | `1ba1bb5` — Cliques maximais + árvore de cliques + completação PSD exata (sem `linalg.inv`) e `scipy.sparse.linalg.splu` adaptativo (`n=28` em `0.77s` no Chromium Pyodide Wasm). |
| **Ciclo 5 (Gram Cônico Esparso CSC & Recalibração `1792/3072`)** | `WP-PHASE9-05A` (`F6`), `WP-PHASE9-05B` (`F8`), `WP-PHASE9-05C` (`F9`) | `F6`, `F8`, `F9` | **IMPLEMENTED & ACCEPTED BY F9** | Fechamento **118/118 WPs**: `A_cone_csc` + `G_cone_sp` (Gershgorin / `splu` simétrica), recalibração empírica do `BROWSER_ENVELOPE` para `1792 / 3072 / 96 / 131072` e validação real em Chromium Pyodide Wasm (`n=48..80`). |

### Evidência Medida de Encerramento (CPython vs. Chromium Pyodide Wasm vs. Clarabel)

Medição independente com a *wheel* final da Fase 9 e **`BROWSER_ENVELOPE` recalibrado (`fast_max_variables = 1792`, `max_variables = 3072`, `max_block_dimension = 96`, `max_cone_entries = 131072`)**:

- **Ganho Fase 5 → Fase 9 v2.0 em `continuous_stabilization_lmi` (`n=16..28`, `152..434 vars`):**
  - `n=16` (`152 vars`): CPython `59.5ms` (era `495.8ms`, **`8.3×`**) | Chromium Wasm `152.3ms` (era `808.1ms`, **`5.3×`**) | Clarabel `44.8ms` | `validated_dual`
  - `n=20` (`230 vars`): CPython `99.3ms` (era `776.6ms`, **`7.8×`**) | Chromium Wasm `220.2ms` (era `1793.6ms`, **`8.1×`**) | Clarabel `74.8ms` | `validated_dual`
  - `n=24` (`324 vars`): CPython `158.6ms` (era `1667.5ms`, **`10.5×`**) | Chromium Wasm `410.4ms` (era `4105.7ms`, **`10.0×`**) | Clarabel `150.9ms` | `validated_dual`
  - `n=28` (`434 vars`): CPython `244.1ms` (era `3221.4ms`, **`13.2×`**) | Chromium Wasm `765.4ms` (era `9721.2ms`, **`12.7×`**) | Clarabel `263.4ms` | `validated_dual`
- **Decomposição Cordal (`chordal_banded_d20`, `dim=20 → clique_max_dim=4`, 9 cliques):** CPython `73.2ms` | Chromium Wasm `144.1ms` | Clarabel `13.9ms` (`|Δobj| = 8.89e-10`) | `validated_dual` no bloco original `20×20`.
- **Schur Esparso `splu` (`sparse_schur_m159`, `m=159`):** CPython `177.4ms` (`splu`) vs. `239.0ms` (`dense`) | Chromium Wasm `371.3ms` (`splu`) vs. `387.7ms` (`dense`) | Clarabel `47.6ms` (`|Δobj| = 1.73e-8`) | `validated_dual`.
- **Escalonamento em Alta Ordem no Chromium + Pyodide Wasm (*fresh worker*, `n=56..80`):**
  - `fresh_denseA_n56` (`1,708 vars`, `dim=56`, `A` 100% densa, `dense_cholesky`): **`8.20s`** (`754 MiB` heap Wasm, `validated_dual`) → fundamenta `fast_max_variables = 1792` (`n ≤ 56` estabilização / `n ≤ 44` $\mathcal{H}_\infty$ em `< 10s`);
  - `fresh_chain_n64` (`2,208 vars`, `dim=64`, `dense_cholesky`): **`8.59s`** (`1,157 MiB` heap Wasm, `validated_dual`);
  - `fresh_diag_n72` (`2,700 vars`, `dim=72`, `sparse_splu`): **`7.71s`** (`1,608 MiB` heap Wasm, `validated_dual`);
  - `fresh_chain_n72` (`2,772 vars`, `dim=72`, `dense_cholesky`): **`14.85s`** (`1,706 MiB` heap Wasm, `validated_dual`);
  - `fresh_diag_n80` (`3,320 vars`, `dim=80`, `sparse_splu`): **`11.79s`** (`2,424 MiB` heap Wasm, `validated_dual`);
  - Teto OOM `wasm32` observado em torno de `n=96` (`4,656 vars`, `> 3.5 GiB`) → `max_variables = 3072` ($n \le 76$) preserva **`> 1.5 GiB` de margem de segurança** no navegador.

---

## 5. Invariante Inegociável de Verificação Científica

Em **todos** os 5 ciclos da Fase 9, sem exceção:

1. **Auditoria Independente 5D no Problema Original:** toda solução produzida após empacotamento `F_k_packed`, escalonamento de Ruiz, Gram cônico esparso `A_cone_csc`, HSDE, pré-processamento simbólico, fusão simétrica ou decomposição cordal **DEVE** ser desescalonada e reconstruída integralmente no espaço original não escalonado e não decomposto antes de passar pela verificação independente de 5 dimensões em `control_lab/optimization/verification/`.
2. **Paridade Estrita com o Oráculo Independente:** toda entrega é confrontada pela Frente `F9` contra o oráculo independente `clarabel_direct` (`tests/oracles/`) e contra a escada normativa `T-SDP-A1..D2` (`G-0B`) **sem qualquer relaxamento de tolerâncias** (`1e-8` / critérios da `ADR-010` e `CL-DIR-001`).
3. **Retrocompatibilidade:** o transporte denso `F_k` e o transporte COO JSON `F_k_sparse` permanecem suportados durante e após a introdução do caminho rápido `F_k_packed`, garantindo que scripts, fixtures ouro e testes legados continuem 100% funcionais.

---

## 6. Referências Científicas e Técnicas

1. **Pyodide Buffer Protocol & Web Worker `Transferable`:** *Pyodide Type Translations — Buffer Protocol (`memoryview` / `np.frombuffer`)* e especificação WHATWG HTML `Transferable` (`ArrayBuffer` / `Int32Array` / `Float64Array`). Base para transporte *zero-copy* entre TypeScript (`web/worker/`) e NumPy em `wasm32`.
2. **Ye, Y., Todd, M. J., & Mizuno, S. (1994).** *An $O(\sqrt{n}L)$-Iteration Homogeneous and Self-Dual Linear Programming Algorithm.* Mathematics of Operations Research, 19(1), 53–67. DOI: `10.1287/moor.19.1.53`.
3. **de Klerk, E., Roos, C., & Terlaky, T. (1998).** *Initialization in Semidefinite Programming via a Self-Dual Skew-Symmetric Embedding.* Operations Research Letters, 20(5), 213–221. DOI: `10.1016/S0167-6377(97)00018-7`.
4. **Sturm, J. F. (1999).** *Using SeDuMi 1.02, a MATLAB Toolbox for Optimization over Symmetric Cones.* Optimization Methods and Software, 11(1–4), 625–653. DOI: `10.1080/10556789908805766`.
5. **Goulart, P. J., & Chen, Y. (2024).** *Clarabel: An Interior-Point Solver for Conic Programs with Quadratic Objectives.* `arXiv:2405.12762`.
6. **Gondzio, J. (1996).** *Multiple Centrality Corrections in a Primal-Dual Method for Linear Programming.* Computational Optimization and Applications, 6, 137–156. DOI: `10.1007/BF00249643`.
7. **Fujisawa, K., Kojima, M., & Nakata, K. (1997).** *Exploiting Sparsity in Primal-Dual Interior-Point Methods for Semidefinite Programming.* Mathematical Programming, 79(1–3), 235–253. DOI: `10.1007/BF02614319` (base teórica estendida pelas otimizações de montagem paralela/BLAS de Fujisawa et al., IEEE IPDPS 2014, DOI: `10.1109/IPDPS.2014.121`).
8. **Tuan, H. D., Apkarian, P., Narikiyo, T., & Yamamoto, Y. (2001).** *Parameterized Linear Matrix Inequality Techniques in Fuzzy Control System Design.* IEEE Transactions on Fuzzy Systems, 9(2), 324–332. DOI: `10.1109/91.919253`.
9. **Sala, A., & Ariño, C. (2007).** *Asymptotically Necessary and Sufficient Conditions for Stability and Performance in Fuzzy Control: Applications of Polya's Theorem.* Fuzzy Sets and Systems, 158(24), 2671–2686. DOI: `10.1016/j.fss.2007.06.016`.
10. **Vandenberghe, L., & Andersen, M. S. (2015).** *Chordal Graphs and Semidefinite Optimization.* Foundations and Trends in Optimization, 1(4), 241–433. DOI: `10.1561/2400000006`.
11. **Garstka, M., Cannon, M., & Goulart, P. (2020).** *A Clique Graph Based Merging Strategy for Decomposable SDPs.* IFAC-PapersOnLine (IFAC World Congress 2020), 53(2), 7355–7361. DOI: `10.1016/j.ifacol.2020.12.1255`.
12. **Demmel, J. W., Eisenstat, S. C., Gilbert, J. R., Li, X. S., & Liu, J. W. H. (1999).** *A Supernodal Approach to Sparse Partial Pivoting.* SIAM Journal on Matrix Analysis and Applications, 20(3), 720–755. DOI: `10.1137/S0895479895291765`.
