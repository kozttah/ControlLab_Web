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

## Evolução Planejada (ADR-015 — Fase 9)

A continuidade de escalabilidade do solver `native_primal_dual` na **Fase 9 (`Phase9-Native-SDP-Scalability-v2`)** é formalizada na [`ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`](ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md), preservando integralmente a execução 100% *zero-install* em NumPy/SciPy puro no Pyodide (rejeitando servidor local `localhost`, forks binários Wasm externos, `wasm64`/COOP-COEP e solvers paralelos de 1ª ordem) e mantendo inegociável a auditoria 5D independente no problema original sem relaxamento de tolerâncias. A evolução divide-se em 4 ciclos sequenciais:

1. **Ciclo 1 (`WP-PHASE9-01A..01D`):** transporte *zero-copy* empacotado (`F_k_packed` via `TypedArray`/`Transferable` → Pyodide `memoryview`/`np.frombuffer`), buffers *in-place* pré-alocados no laço IPM (`H, W, S, dX, dZ`) e caminho vetorial 1D unificado para blocos PSD `1x1`.
2. **Ciclo 2 (`WP-PHASE9-02`, `WP-PHASE9-02B`):** Embedding Homogêneo Autodual (HSDE) em fase única com certificados Farkas primal/dual e múltiplos corretores de centralidade de Gondzio reutilizando a fatoração de Cholesky ($O(m^2)$).
3. **Ciclo 3 (`WP-PHASE9-03`, `WP-PHASE9-03B`, `WP-PHASE9-03C`):** montagem esparsa do complemento de Schur pelas fórmulas F1/F2 de Fujisawa, remoção simbólica de colunas redundantes em `F_k` e fusão simétrica automática ($\Upsilon_{ij} + \Upsilon_{ji} \prec 0$) no compilador `lmi_dsl_compiler.ts`.
4. **Ciclo 4 (`WP-PHASE9-04`, `WP-PHASE9-04B`):** decomposição cordal por cliques maximais com fusão em árvore de cliques (`scipy.sparse.csgraph`) + fatoração esparsa adaptativa de Schur via `scipy.sparse.linalg.splu` (quando densidade simbólica $< 30\%$) e recalibração formal do `BROWSER_ENVELOPE` em navegador real.



