# ADR-010 — SDP nativo NumPy/SciPy e exportação offline

Decisão aprovada pelo coordenador do projeto nesta sessão. Estado aceito.

O backend padrão Pyodide é native_primal_dual, com núcleo Nesterov–Todd/Mehrotra promovido da implementação educacional. LPs estruturalmente diagonais usam scipy.optimize.linprog/HiGHS. Em CPython os backends opcionais Clarabel/CVXPY continuam suportados. O bundle base não exige wheels binários SDP adicionais.

O núcleo comum reside em optimization/backends/native_core.py. A API educacional delega ao núcleo preservando sua classificação experimental e seu histórico didático. A nova API de produção tem maturidade beta e auditoria espectral obrigatória, com as cinco dimensões de status preservadas.

O envelope denso recomendado limita 128 variáveis, dimensão máxima de bloco 48 e 16384 entradas cônicas, incluindo desigualdades. São limites operacionais iniciais para controlar memória/latência, sujeitos a medição. Acima deles, o backend recusa a execução com RESOURCE_LIMIT e recomenda execução offline. Condicionamento inadequado, auditoria inconclusiva ou certificado/gap não validado também recomendam CVXPY/YALMIP com MOSEK, Clarabel, SeDuMi ou SDPT3.

Os exportadores determinísticos geram o mesmo problema canônico, suas matrizes, igualdades, desigualdades, restrições PSD e recuperação de ganhos por sistemas lineares. A interface oferece os scripts do problema atual mesmo sem uma solução confirmada. Os scripts exportados ainda requerem validação primal/dual e de malha fechada pelo usuário ao serem executados fora do aplicativo.

G-0B passa a exigir a escada T-SDP-A1/A2/A3/B1/C1/D1/D2 no runtime Pyodide com native_primal_dual, certificados auditados e exportações sintaticamente válidas para contingências mal-condicionadas/acima do envelope. Mantém-se a matriz de dois navegadores da Seção 14.1. Uma prova em um navegador deve ser registrada como evidência parcial, sem aceite automático do gate.

Esta ADR substitui a exigência de empacotamento binário Wasm da Seção 6.2/14.1 e a exclusão do núcleo promovido de auto. O adaptador educacional permanece experimental. R-13/ADR-008 seguem aplicáveis à interface didática.

## Referências Algorítmicas do Solver SDP Nativo

Na Fase 5 (`WP-PHASE5-01-F6-SCALABLE-NATIVE-SDP`, `WP-PHASE5-03-F6F8-UPDATE-BROWSER-ENVELOPE` e `WP-PHASE5-05-SCALABLE-CHORDAL-COO-CANCEL`), o núcleo `native_core.py`, a camada canônica `canonical.py` e o compilador/interface LMI (`lmi_dsl_compiler.ts` / `lmi_view.ts`) foram otimizados e recalibrados via benchmark de estresse real em navegador para operar com um **`BROWSER_ENVELOPE` em duas faixas**:

- **Faixa rápida interativa (`fast_max_variables = 448`, `< 10s`)**: correspondente na UI a $n \le 28$ estados em factibilidade/estabilização geral e $n \le 20$ em síntese $\mathcal{H}_\infty$, com resposta interativa no navegador.
- **Faixa estendida no navegador (`max_variables = 1024`, `max_block_dimension = 64`, `max_cone_entries = 65536`)**: habilita problemas maiores diretamente no Web Worker Pyodide com log de iterações em tempo real, timeout estendido de 5 minutos (`300_000 ms`) e botão **Cancelar** (`#btn-lmi-cancel-solve`) para interromper a resolução a qualquer momento, mantendo a recomendação de exportação offline CVXPY/YALMIP acima do limite rígido (`max_variables = 1024`).

O solver incorpora técnicas de cinco referências da literatura sem abrir mão de certificados duais auditados independentemente no problema original:

- **Fujisawa et al. (IEEE IPDPS 2014, `https://doi.org/10.1109/IPDPS.2014.121`)**: exploração de esparsidade em matrizes de restrição `F_k` na congruência de Nesterov–Todd e na montagem vetorizada (BLAS) do complemento de Schur `H`, combinada com fatoração de Cholesky regularizada única por iteração Mehrotra (reutilizada nos passos preditor e corretor com refino iterativo e estimativa de condicionamento $O(m)$).
- **Yurtsever, Tropp, Fercoq, Udell, Cevher (SIAM J. Matrix Anal. Appl. 2021, `https://web.stanford.edu/~udell/doc/yurtsever21_scalable.pdf` — SketchyCGAL §7.1.1)**: equilibração/escalonamento por bloco via norma de Frobenius com desescalonamento exato dos multiplicadores duais antes da verificação independente no problema original. Registra-se explicitamente que o *sketching* de posto baixo de 1ª ordem (CGAL/SketchyCGAL) não substitui o método de pontos interiores (IPM) de 2ª ordem em LMIs de Lyapunov/estabilização de posto cheio que exigem certificado dual estrito (`1e-8`).
- **Ding et al. (`https://arxiv.org/abs/2312.11801` — SpecBM / USBS)**: suporte a `warm_start_x` interior para pular a Fase I em varreduras paramétricas (ex.: taxa de decaimento $\alpha$ ou minimização $\mathcal{H}_\infty$/BRL), com recuo automático (*fallback*) para Fase I caso o ponto inicial não seja estritamente factível e manutenção integral da validação independente primal/dual.
- **Goulart & Chen (2024, `https://arxiv.org/abs/2405.12762`, Clarabel §2.4, §2.5, §2.6)**: equilibração de Ruiz multi-varredura com recorte de fatores de escala no intervalo `[1e-4, 1e4]` (escalonamento simétrico de blocos e variáveis em `_ruiz_equilibrate_blocks`) com desescalonamento exato primal (`x` via `d_ruiz`) e dual (`Z_b = e_b * Z'_b`) antes da verificação independente no problema original; transporte esparso em formato COO (`F_k_sparse`) entre `lmi_dsl_compiler.ts` e `SDPBlock.from_dict` (mantendo retrocompatibilidade 100% com `F_k` denso).
- **Garstka, Cannon & Goulart (IFAC 2020, `https://doi.org/10.1016/j.ifacol.2020.12.1255`)**: decomposição de blocos PSD por componentes conexas do padrão de esparsidade agregada (`_decompose_sparse_psd_blocks`) em subblocos menores, com reconstrução exata dos multiplicadores duais originais (`reassemble_duals`) antes da auditoria espectral e de complementaridade.

### Benchmark de Estresse Real (Chromium Pyodide Wasm vs. CPython vs. Clarabel)

Medição independente de estabilização LTI contínua (`continuous_stabilization_lmi`) com o núcleo `native_primal_dual` otimizado em Chromium + Pyodide Wasm real versus CPython e referência `clarabel_direct`:

| Dimensão ($n$, variáveis) | CPython (`native_primal_dual`) | Pyodide Wasm (Chromium) | Clarabel (`clarabel_direct`) | Certificado Independente | Envelope Interativo (`< 10s`) |
|---|---|---|---|---|---|
| `n=16` (`152 vars`) | `495.8ms` | `808.1ms` (13 it) | `50.5ms` | `validated_dual` | Dentro do envelope |
| `n=20` (`230 vars`) | `776.6ms` | `1793.6ms` (13 it) | `86.6ms` | `validated_dual` | Dentro do envelope |
| `n=24` (`324 vars`) | `1667.5ms` | `4105.7ms` (13 it) | `163.9ms` | `validated_dual` | Dentro do envelope |
| `n=26` (`377 vars`) | `2167.6ms` | `6459.9ms` (13 it) | `218.1ms` | `validated_dual` | Dentro do envelope |
| `n=28` (`434 vars`) | `3221.4ms` | `9721.2ms` (14 it) | `273.0ms` | `validated_dual` | Limite interativo (`max_variables=448`) |
| `n=30` (`495 vars`) | `4293.8ms` | `16424.9ms` (15 it) | `359.9ms` | `validated_dual` | Acima de `< 10s` — exportação offline recomendada |

## Evolução Concluída — Fase 9 (`ADR-015` — Native SDP v2.0, `ACCEPTED_BY_F9`, **118/118 WPs**)

A escalabilidade do solver `native_primal_dual` na **Fase 9 (`Phase9-Native-SDP-Scalability-v2`)**, formalizada na [`ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`](ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md), foi integralmente implementada e auditada pela Frente F9 em 5 ciclos sequenciais, preservando 100% da execução *zero-install* em NumPy/SciPy puro no Pyodide e a auditoria 5D independente no problema original sem relaxamento de tolerâncias:

1. **Ciclo 1 (`WP-PHASE9-01A..01D` — `ACCEPTED_BY_F9`):** transporte *zero-copy* empacotado (`F_k_packed` via `TypedArray`/`Transferable` → Pyodide `memoryview`/`np.frombuffer`), buffers *in-place* pré-alocados no laço IPM (`H, W, S, dX, dZ`) e caminho vetorial 1D unificado para blocos PSD `1x1`.
2. **Ciclo 2 (`WP-PHASE9-02`, `WP-PHASE9-02B` — `ACCEPTED_BY_F9`):** Embedding Homogêneo Autodual (HSDE) em fase única com certificados Farkas primal/dual e múltiplos corretores de centralidade de Gondzio reutilizando a fatoração de Cholesky ($O(m^2)$).
3. **Ciclo 3 (`WP-PHASE9-03`, `WP-PHASE9-03B`, `WP-PHASE9-03C` — `ACCEPTED_BY_F9`):** montagem esparsa do complemento de Schur pelas fórmulas F1/F2 de Fujisawa, remoção simbólica de colunas redundantes em `F_k`, fusão simétrica automática ($\Upsilon_{ij} + \Upsilon_{ji} \prec 0$) no compilador `lmi_dsl_compiler.ts` e exibição genérica de variáveis recuperadas (`recover`) na Aba 6.
4. **Ciclo 4 (`WP-PHASE9-04`, `WP-PHASE9-04B` — `ACCEPTED_BY_F9`):** decomposição cordal por cliques maximais com árvore de cliques e completação PSD exata de máxima entropia (`scipy.sparse.csgraph`, sem `linalg.inv`) + fatoração esparsa adaptativa de Schur via `scipy.sparse.linalg.splu` (quando densidade simbólica $< 25\%$ e $m \ge 60$).
5. **Ciclo 5 (`WP-PHASE9-05A`, `WP-PHASE9-05B`, `WP-PHASE9-05C` — `ACCEPTED_BY_F9`):** substituição da materialização densa pré-solver `A_cone` e do produto BLAS `A_col_scaled.T @ A_col_scaled` em `native_core.py` por `scipy.sparse.csc_matrix` (`G_cone_sp`) com verificação de posto cheio via dominância diagonal $O(\text{nnz})$ de Gershgorin ou `scipy.sparse.linalg.splu` simétrica (recaída para SVD densa apenas sob deficiência real de posto), eliminando o gargalo de memória/latência pré-IPM acima de `1.000` variáveis e recalibrando o **`BROWSER_ENVELOPE` para `1792` rápido / `3072` estendido (`max_block_dimension = 96`, `max_cone_entries = 131072`)**.

### Benchmark Comparativo Fase 5 vs. Fase 9 v2.0 (CPython vs. Chromium Pyodide Wasm vs. Clarabel)

Medição independente reproduzível com a *wheel* de produção (`web/dist/wheels/control_lab-1.0.0-py3-none-any.whl`):

| Problema / Dimensão | Fase 5 CPython | Fase 9 v2 CPython (Ganho) | Fase 5 Chromium Wasm | Fase 9 v2 Chromium Wasm (Ganho) | Clarabel (`clarabel_direct`) | Certificado Independente |
|---|---|---|---|---|---|---|
| `stab n=16` (`152 vars`, F1/F2) | `495.8ms` | **`59.5ms`** (`8.3×`) | `808.1ms` (13 it) | **`152.3ms`** (6 it, `5.3×`) | `44.8ms` | `validated_dual` (`Δobj = 0.0`) |
| `stab n=20` (`230 vars`, F1/F2) | `776.6ms` | **`99.3ms`** (`7.8×`) | `1793.6ms` (13 it) | **`220.2ms`** (6 it, `8.1×`) | `74.8ms` | `validated_dual` (`Δobj = 0.0`) |
| `stab n=24` (`324 vars`, F1/F2) | `1667.5ms` | **`158.6ms`** (`10.5×`) | `4105.7ms` (13 it) | **`410.4ms`** (6 it, `10.0×`) | `150.9ms` | `validated_dual` (`Δobj = 0.0`) |
| `stab n=28` (`434 vars`, F1/F2) | `3221.4ms` | **`244.1ms`** (`13.2×`) | `9721.2ms` (14 it) | **`765.4ms`** (6 it, `12.7×`) | `263.4ms` | `validated_dual` (`Δobj = 0.0`) |
| `chordal_banded_d20` (`dim=20 → clique_max=4`, 9 cliques, `39 vars`) | — | **`73.2ms`** (10 it) | — | **`144.1ms`** (10 it) | `13.9ms` (`Δobj = 8.9e-10`) | `validated_dual` (`λ_min(Z) ≥ -1e-8`) |
| `sparse_schur_m159` (`m=159`, `splu` vs. `dense`) | — | **`177.4ms`** (`splu`) vs. `239.0ms` (`dense`) | — | **`371.3ms`** (`splu`) vs. `387.7ms` (`dense`) | `47.6ms` (`Δobj = 1.7e-8`) | `validated_dual` (`sparse_splu`) |

### Escalonamento de Alta Ordem em Worker Isolado (Chromium + Pyodide Wasm, `n = 28..80`)

Com a matriz cônica esparsa `A_cone_csc` + Gram esparso `G_cone_sp` (`WP-PHASE9-05A`), medições isoladas em *fresh Web Worker* no **Chromium + Pyodide Wasm** demonstraram:

| Caso de Estresse (`fresh worker`) | Variáveis (`m`) | Dimensão de Bloco | Modo Schur | Tempo Chromium Wasm | Heap Linear `wasm32` | Certificado 5D | Enquadramento no Novo Envelope |
|---|---|---|---|---|---|---|---|
| `stab n=28` (acoplada) | `434` | `28` | `dense_cholesky` | **`0.77s`** | `< 200 MiB` | `validated_dual` | Faixa rápida (`≤ 1792 vars`) |
| `fresh_denseA_n56` (`A` 100% densa, pior caso) | `1,708` | `56` | `dense_cholesky` | **`8.20s`** | `754 MiB` | `validated_dual` | Limite da faixa rápida (`fast_max_variables = 1792`, `< 10s`) |
| `fresh_chain_n64` (cadeia acoplada) | `2,208` | `64` | `dense_cholesky` | **`8.59s`** | `1,157 MiB` | `validated_dual` | Faixa estendida (`1793..3072 vars`) |
| `fresh_diag_n72` (diagonal / fracamente acoplada) | `2,700` | `72` | `sparse_splu` | **`7.71s`** | `1,608 MiB` | `validated_dual` | Faixa estendida (`1793..3072 vars`) |
| `fresh_chain_n72` (cadeia acoplada) | `2,772` | `72` | `dense_cholesky` | **`14.85s`** | `1,706 MiB` | `validated_dual` | Faixa estendida (`≤ 3072 vars`, folga `> 1.5 GiB` sob OOM) |
| `fresh_diag_n80` (acima do teto conservador) | `3,320` | `80` | `sparse_splu` | **`11.79s`** | `2,424 MiB` | `validated_dual` | Acima de `max_variables = 3072` (`RESOURCE_LIMIT` por margem de heap) |
| Teto OOM `wasm32` (`~n=96`) | `4,656` | `96` | — | OOM | `> 3.5 GiB` | — | Bloqueado preventivamente (`RESOURCE_LIMIT` + exportação offline) |

### Novo `BROWSER_ENVELOPE` Calibrado (`WP-PHASE9-05A..05C`)

Com base nas medições empíricas de latência e heap `wasm32` acima, o `BROWSER_ENVELOPE` normativo em `control_lab/optimization/backends/native.py` e `web/features/views/lmi_view.ts` passa a ser:

- **`fast_max_variables = 1792`** (era `448`): cobre $n \le 56$ estados em estabilização/factibilidade geral, $n \le 44$ em síntese $\mathcal{H}_\infty$ (BRL) e até `64` blocos LMI expandidos em **`< 10s`** mesmo para matrizes `A` 100% densas (`8.20s` em `n=56`).
- **`max_variables = 3072`** (era `1024`): cobre plantas de até $n = 76$ estados diretamente no Web Worker Pyodide com progresso iterativo e botão **Cancelar**, preservando **`> 1.5 GiB` de margem de segurança** abaixo do teto de memória linear `wasm32` (`~3.5–4.0 GiB` em torno de `n=96`, `4,656` variáveis).
- **`max_block_dimension = 96`** (era `64`) e **`max_cone_entries = 131072`** (era `65536`): acomodam blocos LMI/BRL dilatados de ordem superior dentro do teto de `3.072` variáveis, recusando casos maiores com `RESOURCE_LIMIT` limpo e recomendação explícita de exportação offline **CVXPY / YALMIP**.





