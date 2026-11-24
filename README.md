# ControlLab Web

**Identificação, análise, síntese e verificação de sistemas de controle no navegador, com cálculo local em Python/Pyodide e interface TypeScript.**

[![CI](https://github.com/kozttah/ControlLab_Web/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kozttah/ControlLab_Web/actions/workflows/ci.yml)
[![Especificação](https://img.shields.io/badge/Documento_Diretor-CL--DIR--001_v1.0.0-0f172a)](./ControlLab_Web_Documento_Diretor_v1.0.md)
[![UX & Design](https://img.shields.io/badge/Design_Diretor-CL--UX--DIR--001_+_ADR--014-1d4ed8)](./docs/architecture/ControlLab_Web_Design_Diretor_v1.0.md)
[![Status](https://img.shields.io/badge/Produto-Beta_(120%2F120_WPs)-d97706)](./PROJECT_STATE.json)
[![Licença](https://img.shields.io/badge/Licen%C3%A7a-MIT-059669)](./LICENSE)

O ControlLab Web reúne um motor científico em `NumPy`/`SciPy`, modelos canônicos, diagnósticos numéricos, síntese baseada em LMIs/SDP e arquivos portáteis para ensino, pesquisa e engenharia de controle. O cálculo no navegador é executado em um Web Worker Pyodide, sem backend científico remoto obrigatório. O mesmo pacote `control_lab` pode ser utilizado diretamente em CPython local.

A especificação normativa é o [Documento Diretor CL-DIR-001](./ControlLab_Web_Documento_Diretor_v1.0.md), complementado pelas [decisões de arquitetura (`ADR-009` a `ADR-015`)](./docs/architecture/), pelo [Documento Diretor de Design e UX (`CL-UX-DIR-001`)](./docs/architecture/ControlLab_Web_Design_Diretor_v1.0.md) e pelo [Documento Diretor da DSL de LMIs (`CL-LMI-DSL-DIR-001`)](./docs/architecture/ControlLab_Web_LMI_DSL_Design_Diretor_v1.0.md). O [PROJECT_STATE.json](./PROJECT_STATE.json) registra os gates, os WorkPackages e seus pareceres independentes de aceite.

## Testar no navegador

**[Abrir ControlLab Web — versão beta](https://kozttah.github.io/ControlLab_Web/)**

O endereço permite utilizar todas as seis bancadas da plataforma sem instalar Python ou Node.js. Na primeira abertura, o navegador precisa baixar e inicializar o motor Pyodide e seus pacotes; esse carregamento pode demorar alguns segundos. Aguarde o indicador **Motor: ready** antes de confirmar um cálculo. Todo o processamento ocorre no próprio dispositivo e os projetos ficam no armazenamento local do navegador; exporte o arquivo `.ctrlab` para guardar ou transferir seu workspace completo (incluindo sistemas lineares, politópicos, Takagi-Sugeno, datasets e condições LMI).

A versão publicada é destinada a uso e validação em estágio beta, preservando os limites documentados abaixo. Atualizações na branch `main` são publicadas automaticamente no GitHub Pages após a aprovação de todos os jobs **A–G** do CI, reutilizando exatamente o mesmo artefato estático verificado. O modo offline depende de provisionamento completo do Service Worker, e limpar os dados do navegador remove o cache e os projetos locais.

## Estado atual

**Referência em 24/11/2026:** **120 de 120 WorkPackages aprovados pela auditoria independente F9 (`ACCEPTED_BY_F9`, 0 pendentes)**, cobrindo os quatro gates da Fase 0 e as Fases 1–9 (incluindo os 6 ciclos da arquitetura **Native SDP v2.0 — `ADR-015`**, com vetorização simétrica `svec`, salvaguarda de estagnação `1b'` e `BROWSER_ENVELOPE` recalibrado para `1.792 / 3.072` variáveis). O produto mantém explicitamente o selo **beta**: a aprovação dos WorkPackages valida cada capacidade dentro do domínio auditado, sem declarar certificação integral para casos fora das hipóteses documentadas.

| Gate / Marco | Resultado | Capacidade verificada |
| --- | --- | --- |
| **G-0A** | `ACCEPTED_BY_F9` | CARE/LQR 12×3, paridade CPython/Pyodide, recuperação do Worker e controle de PyProxy. |
| **G-0B** | `ACCEPTED_BY_F9` | Solver SDP nativo escalável no Wasm, escada A–D, auditoria primal/dual 5D e exportadores CVXPY/YALMIP em Chromium e Firefox. |
| **G-0C** | `ACCEPTED_BY_F9` | Arraste DOM real com Fast-Preview/commit (`R-23`), teclado, viewport mobile `390×844`, validação dimensional e gráficos científicos exportáveis (SVG/PNG). |
| **G-0D** | `ACCEPTED_BY_F9` | Round-trip `.ctrlab`, exportação `.pvm` passiva (estático/dinâmico/saturação) e scripts PathSim `0.31.0`, validados em PathView `0.21.0` / PathSim `0.31.0`. |
| **Fases 1–8** | `ACCEPTED_BY_F9` | 6 bancadas completas, arquitetura **Workspace-First (`ADR-014`)**, DSL LMI v2.0 direta + observadores TS não medidos, ANFIS, $\mathcal{H}_\infty$ DGKF estável (`ADR-012`) e scripts PathSim (`ADR-013`). |
| **Fase 9 (`ADR-015`)** | `ACCEPTED_BY_F9` | Solver SDP Nativo v2.0 (6 ciclos): `F_k_packed` *zero-copy*, cone LP 1D, workspace *in-place*, HSDE + Gondzio + estagnação `1b'`, Fujisawa F1/F2 + isometria `svec` (`F2`/`F3_blas`), fusão simétrica DSL + `recover` na Aba 6, decomposição cordal, Schur esparso `splu` e Gram cônico esparso `A_cone_csc` — envelope recalibrado **`1.792 / 3.072` variáveis** (`n=28` em `0.77s`, `n=56` denso em `8.20s`, `n=72` esparso em `7.71s` no Chromium Wasm). |

A [execução CI dessa referência (#45083984167)](https://github.com/kozttah/ControlLab_Web/actions/runs/45083984167) concluiu **todos os 9 jobs (A–H)** com sucesso:

- **A — Python static:** `ruff`, `mypy`, `pip check` e sanidade do pacote `control_lab`.
- **B — CPython math (`core_no_sdp`):** **569 testes aprovados, 0 skips** (ambiente enxuto `requirements-core.lock`, sem `clarabel`, `cvxpy`, `pathview` ou `pathsim`).
- **B — CPython math (`sdp_available`):** **378 testes aprovados, 0 skips** (incluindo oráculos independentes Clarabel/CVXPY).
- **C — Web contracts and unit:** **152 testes aprovados** (`typecheck` rigoroso com `erasableSyntaxOnly` + 20 arquivos de teste).
- **D — Real browser Wasm:** **14 testes aprovados** em navegador real com Pyodide.
- **E — Browser integration and external gate:** **32 testes aprovados em Chromium** (incluindo 14 testes E2E de UX/responsividade e interoperabilidade externa) + **1 suíte em Firefox**.
- **F — Browser security:** **8 testes aprovados** (isolamento offline real, CSP e passividade de artefatos).
- **G — Artifacts and release gate:** **55 testes aprovados** (verificação de integridade dos 42 assets locais e reprodutibilidade do build).
- **H — Publish beta GitHub Pages:** publicação automática do artefato verificado.

*(Nota: as contagens de testes entre perfis se sobrepõem parcialmente e não devem ser somadas como casos distintos.)*

Evidências detalhadas estão nos [handoffs F9](./docs/audits/handoffs/), no [relatório dos gates da Fase 0](./docs/audits/RELATORIO_STATUS_GATES_FASE0.md) e no [fechamento CI](./docs/audits/CI_RECONCILIATION_2026-11-17.md). Relatórios de auditorias anteriores são preservados como histórico.

## Arquitetura da bancada — Workspace-First (`ADR-014`) e 6 abas

![Arquitetura modular](./controllab_v1_assets/arquitetura_v1.png)

A interface segue a diretriz **Workspace-First** formalizada na [ADR-014](./docs/architecture/ADR-014-workspace-centralized-system-definition.md) e incorporada como **Pilar 5** do [Documento Diretor de Design (`CL-UX-DIR-001`)](./docs/architecture/ControlLab_Web_Design_Diretor_v1.0.md):

- **Workspace Dock persistente (`+ Novo` / `Editar`):** ponto único de criação, edição versionada (`#r1 → #r2`) e inspeção de todos os ativos da sessão:
  - **Função de Transferência (`tf`)** contínua ou discreta;
  - **Espaço de Estados / Planta Generalizada (`ss`)** com suporte opcional aos canais exógenos e de desempenho (`Bw, Dyw, Cz, Dzu, Dzw`), persistidos em `provenance.generalized_channels` em conformidade estrita com `state_space.schema.json`;
  - **Sistema Politópico Incerto (`polytopic`)** com número **ilimitado** de vértices `(A[i], B[i], C[i], D[i])`, gerador auxiliar `±δ%` e registro canônico `TSStateSpace(kind="polytopic_uncertain")`;
  - **Sistema Takagi-Sugeno (`ts`)** com número **ilimitado** de regras, editor de premissas `[z_min, z_max]` com classificação **Medida / Não Medida** e funções de ponderação analíticas `h_i(z)` com validação convexa em tempo real ($\sum h_i(z) = 1$, $h_i(z) \ge 0$, sem `eval`), registrando `ts_measured` ou `ts_partially_observed`;
  - **Séries Temporais CSV (`csv`)** com particionamento treino/holdout;
  - **Exemplos prontos** (Integrador Duplo, Massa-Mola-Amortecedor, 1ª Ordem, Planta MIMO 2×2, Dataset PRBS, Politópico 2 Vértices e TS com Premissa Não Medida) e persistência integral em `.ctrlab`.
- **Abas de projeto focadas em parâmetros de projeto:** cada uma das 6 abas seleciona um sistema já definido no Workspace (com atalhos diretos **Editar Sistema no Workspace…** e **+ Novo Sistema**) e concentra exclusivamente os parâmetros de síntese e análise daquela disciplina:

| Aba | Bancada e fluxo integrado no navegador | Núcleo científico (`control_lab`) |
| --- | --- | --- |
| **1. Identificação** | Upload/seleção de CSV, particionamento treino/holdout, comparação de estruturas, gráficos de validação/resíduos (ACF/CCF, FIT) e registro/reutilização do modelo no Workspace (`core.reuse_model`). | ARX, OE, Subespaços (MOESP/N4SID), pré-processamento, excitação persistente (PE) e diagnóstico de resíduos. |
| **2. Frequência SISO** | Diagrama de Bode, Lugar das Raízes, resposta ao degrau com *datatips*, margens de estabilidade, projeto de compensadores (Lead, Lag, PID) com Fast-Preview (`R-23`) e commit autoritativo. | Resposta em frequência, margens, *root locus*, discretização e síntese SISO. |
| **3. Espaço de Estados** | Cartões de KPIs e badges PBH, edição de pesos `Q, R, x0` com slider interativo (`R-23`), atalho para edição da planta no Workspace, observadores/Kalman (LQG), simulação temporal e exportação `.pvm`. | PBH/posto, Lyapunov/Sylvester, CARE/DARE, LQR, observadores, Kalman/LQG e simulação LTI. |
| **4. Frequência MIMO** | Valores singulares ($\bar{\sigma}, \underline{\sigma}$), matriz RGA, curvas de sensibilidade ($S, T, KS$), pesos $W_S, W_U, W_T$ e síntese $\mathcal{H}_\infty$ com exportação `.pvm` de `DynamicController`. | RGA, valores singulares, sensibilidades MIMO e subclasse estável $\mathcal{H}_\infty$ DGKF 2-Riccati com certificado Hamiltoniano exato ([ADR-012](./docs/architecture/ADR-012-hinf-riccati-stable-subclass.md)). |
| **5. Fuzzy, TS & ANFIS** | Editor visual de funções de pertinência e regras Mamdani/TS, superfície de controle, treinamento **ANFIS** interativo, importação/exportação FML (`IEEE 1855-2016`, perfil suportado) e exportação de script **PathSim `0.31.0`** ([ADR-013](./docs/architecture/ADR-013-pvm-nonlinear-boundary-and-pathsim-export.md)). | Inferência Mamdani/TS, parser/exporter FML, ANFIS e semântica tipada TS/PDC (`ADR-006`). |
| **6. LMIs & SDPs** | Seleção de sistema do Workspace (LTI, Generalizada, Politópico ou TS), conjuntos de índices DSL, gerador de observadores TS para premissas não medidas (`dA[k]`, `dC[k]`), editor **DSL v2.0** estilo Monaco com leitura matemática interpretada, fusão simétrica automática ($\Upsilon_{ij} + \Upsilon_{ji} \prec 0$), exibição genérica de variáveis recuperadas (`recover`), alerta BMI, tabela de progresso de iterações + botão **Cancelar**, **Certificado de Auditoria 5D**, espectro de autovalores e exportação **CVXPY (`.py`) / YALMIP (`.m`)**. | Compilador direto para SDP empacotado *zero-copy* (`F_k_packed`), solver primal-dual nativo v2.0 (HSDE + Gondzio + F1/F2 + Cordal + `splu`), verificador espectral independente 5D e templates de controle robusto/TS. |

## Solver SDP nativo escalável no navegador (`ADR-010` & `ADR-015`)

As decisões [ADR-010](./docs/architecture/ADR-010-native-sdp-and-offline-exports.md) e [ADR-015](./docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md) definem o **solver primal-dual nativo v2.0 em NumPy/SciPy** como backend SDP padrão no Pyodide (sem exigir binários C++/Rust de Clarabel/CVXPY no bundle Wasm). Casos estruturalmente diagonais/LP utilizam `scipy.optimize.linprog`/HiGHS. CVXPY e Clarabel permanecem disponíveis como oráculos e backends opcionais em CPython local.

- **Envelope operacional calibrado no navegador (`BROWSER_ENVELOPE`):**
  - **Faixa rápida (`fast_max_variables = 1792`, `< 10s`):** até **1.792 variáveis** escalares de decisão ($n \le 56$ em estabilização/factibilidade geral, $n \le 44$ em síntese $\mathcal{H}_\infty$ e até `64` blocos LMI expandidos; no Chromium Pyodide Wasm: `n=28` em **`0.765s`**, `n=56` com `A` 100% densa em **`8.20s`** / `754 MiB`);
  - **Teto estendido (`max_variables = 3072`, `max_block_dimension = 96`, `max_cone_entries = 131072`):** até **3.072 variáveis** ($n \le 76$ estados; no Chromium Pyodide Wasm: `n=64` acoplada em **`8.59s`** / `1.16 GiB`, `n=72` esparsa `splu` em **`7.71s`** / `1.61 GiB`, `n=72` acoplada em **`14.85s`** / `1.71 GiB`), preservando **`> 1,5 GiB` de margem** abaixo do teto OOM `wasm32` (`~n=96`), com progresso iterativo exibido na tela (`Iter`, `Gap`, `Res. Primal`, `Res. Dual`, `λ_min`, `Tempo (ms)`) e **cancelamento cooperativo**.
- **Auditoria obrigatória em 5 dimensões:** toda solução passa pelo verificador espectral independente no problema original (viabilidade primal/dual, complementaridade, condicionamento, proximidade de fronteira e validade do controlador recuperado). Problemas acima do envelope (`RESOURCE_LIMIT`) ou mal condicionados geram diagnóstico explícito e exportação direta para **CVXPY (`.py`)** ou **YALMIP (`.m`)** com laços quantificados.
- **Arquitetura v2.0 (Fase 9 — `ADR-015`) e referências científicas incorporadas:**
  - **Transporte *zero-copy* `F_k_packed`, workspace *in-place* e cone LP 1D:** `Int32Array`/`Float64Array` via `Transferable` → Pyodide `memoryview`/`np.frombuffer`, buffers reutilizados (`H, W, S, dX, dZ`) e caminho vetorial 1D unificado para blocos PSD `1×1`.
  - **Gram Cônico Esparso Pré-Solver (`A_cone_csc` + `G_cone_sp`):** construção `scipy.sparse.csc_matrix` com verificação de posto cheio $O(\text{nnz})$ via dominância diagonal de Gershgorin ou `splu` simétrica sem materializar matrizes densas `(total_entries, m)`.
  - **HSDE (Ye–Todd–Mizuno 1994; de Klerk–Roos–Terlaky 1998) + Múltiplos Corretores de Gondzio (1996):** embedding homogêneo autodual em fase única com certificados Farkas primal/dual e corretores $O(m^2)$ reutilizando a mesma fatoração de Cholesky.
  - **Fujisawa, Kojima & Nakata (1997) / Fujisawa et al. (IEEE IPDPS 2014):** seleção adaptativa das fórmulas esparsas **F1/F2** na montagem do complemento de Schur sem temporários densos `(m, n, n)` + remoção simbólica pré-solver de colunas redundantes em `F_k` e fusão simétrica automática ($\Upsilon_{ij} + \Upsilon_{ji} \prec 0$, Tuan et al. 2001 / Sala & Ariño 2007).
  - **Decomposição Cordal por Cliques Maximais & Schur Esparso Adaptativo (`splu`):** cliques maximais, árvore de cliques (`scipy.sparse.csgraph`) e completação PSD exata de máxima entropia sem `linalg.inv` (Vandenberghe & Andersen 2015; Garstka, Cannon & Goulart, IFAC 2020) + fatoração esparsa adaptativa via `scipy.sparse.linalg.splu` (SuperLU, Demmel et al. 1999) quando a densidade simbólica de `H` é `< 25%` e `m ≥ 60`.
  - **Equilibração de Ruiz (Goulart & Chen 2024, Clarabel §2.4–2.6) & `warm_start_x` (Ding et al., SpecBM):** escalonamento simétrico multi-varredura com recorte `[1e-4, 1e4]` e desescalonamento exato primal/dual antes da auditoria independente.

A API didática em `control_lab/experimental/sdp_educational/` permanece isolada e experimental.

## Interoperabilidade PathView / PathSim e limites auditados

- **`.pvm` passivo (PathView `0.21.0`):** exporta plantas `StateSpace`, realimentação de estados (`StateFeedbackController`), saturação de atuador e controladores dinâmicos contínuos/discretos (`DynamicController`, incluindo controladores MIMO $\mathcal{H}_\infty$), mantendo estritamente a passividade exigida por `R-21` ([ADR-013](./docs/architecture/ADR-013-pvm-nonlinear-boundary-and-pathsim-export.md)).
- **Scripts Python PathSim `0.31.0`:** exportação determinística e passiva (`io.export_pathsim_script` / botão na Aba 5) para simulação offline de `FuzzySystem` (Mamdani/TS) e `TSStateSpace(kind="ts_measured") + PDCController`, auditada contra `scipy.integrate.solve_ivp` (`erro < 1e-4`). O bloqueio de segurança `ADR-006` para `polytopic_uncertain + PDCController` (`HYPOTHESIS_VIOLATED`) é preservado integralmente.
- **Limites conhecidos da versão beta:** eventos externos e simulação multirate estão fora do domínio homologado; a validação YALMIP é estrutural/sintática (sem execução MATLAB no CI); as medições de desempenho usam o ambiente de container (`DEC-OPEN-03`); e os testes de acessibilidade/60 FPS verificam as jornadas auditadas sem constituir certificação externa formal completa.

## Decisões de Arquitetura (ADRs)

| ADR | Decisão | Documento |
| --- | --- | --- |
| **ADR-009** | Governança em arquivos/CI (`project_governance.py`, `ci_gate.py`, handoffs F9) para repositório em conta pessoal. | [`ADR-009`](./docs/architecture/ADR-009-personal-repository-governance.md) |
| **ADR-010** | Solver SDP primal-dual nativo escalável no Pyodide (envelope calibrado `1792 / 3072`), auditoria 5D e exportações offline CVXPY/YALMIP. | [`ADR-010`](./docs/architecture/ADR-010-native-sdp-and-offline-exports.md) |
| **ADR-011** | Licença MIT para código/documentação originais do ControlLab Web, preservando licenças de terceiros. | [`ADR-011`](./docs/architecture/ADR-011-mit-license-and-third-party-notices.md) |
| **ADR-012** | Promoção da subclasse contínua regular $\mathcal{H}_\infty$ DGKF 2-Riccati a estável com certificado Hamiltoniano exato e oráculo BRL Clarabel. | [`ADR-012`](./docs/architecture/ADR-012-hinf-riccati-stable-subclass.md) |
| **ADR-013** | Fronteira linear/saturação do `.pvm` (PathView `0.21.0`) e exportação determinística de scripts PathSim `0.31.0` para Fuzzy e TS+PDC. | [`ADR-013`](./docs/architecture/ADR-013-pvm-nonlinear-boundary-and-pathsim-export.md) |
| **ADR-014** | Arquitetura **Workspace-First**: definição centralizada de sistemas (TF, SS/Generalizada, Politópico e TS sem limites artificiais) no Workspace Dock. | [`ADR-014`](./docs/architecture/ADR-014-workspace-centralized-system-definition.md) |
| **ADR-015** | Solver SDP Nativo v2.0 (Fase 9): `F_k_packed` *zero-copy*, LP 1D, Gram esparso `A_cone_csc`, HSDE + Gondzio, Fujisawa F1/F2, fusão simétrica DSL, decomposição cordal e Schur esparso `splu`. | [`ADR-015`](./docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md) |

## Executar localmente

Os comandos abaixo partem da raiz do repositório em shell POSIX. O CI de referência utiliza **Python 3.12.14** e **Node.js 24.22.1** (`web/package.json` admite Node 24.x). Use um ambiente virtual Python dedicado:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r scripts/requirements-ci.lock
npm --prefix web ci
npm --prefix web run build
python -m http.server 8000 --directory web/dist
```

Abra **http://localhost:8000**. O build gera a distribuição estática em `web/dist/`, incluindo a wheel científica, bundles, Pyodide, manifesto de integridade, SBOM e informações de dependências. O servidor HTTP apenas entrega arquivos estáticos; todo o cálculo roda no navegador.

O build baixa os assets listados em [`scripts/pyodide-assets.lock.json`](./scripts/pyodide-assets.lock.json) e valida seus hashes SHA-256. O cache padrão é `~/.cache/controllab-build` (configurável via `CONTROLLAB_ASSET_CACHE`). No navegador, aguarde a inicialização do motor e o provisionamento verificado antes de depender do modo offline.

## Verificação e CI

No ambiente virtual científico acima (antes de instalar dependências de navegador):

```bash
python scripts/verify_fixtures.py
python scripts/project_governance.py
python scripts/ci_math.py sdp_available
npm --prefix web run typecheck
npm --prefix web test
python scripts/build_release.py --verify
python scripts/check_reproducible.py
```

O perfil `sdp_available` exige correspondência exata com `scripts/requirements-ci.lock`. Para `core_no_sdp`, crie outro ambiente virtual instalando exclusivamente `scripts/requirements-core.lock` antes de rodar `python scripts/ci_math.py core_no_sdp`. Ambos os perfis exigem **zero skips**.

Para testes reais de navegador, Wasm e interoperabilidade externa, utilize um **ambiente virtual separado**:

```bash
python3.12 -m venv .venv-browser
. .venv-browser/bin/activate
python -m pip install -r scripts/requirements-ci.lock
python -m pip install -r scripts/requirements-browser.lock
python -m playwright install --with-deps chromium firefox
npm --prefix web ci
npm --prefix web run build
python -m pytest tests/wasm/ tests/e2e/ tests/security/ tests/performance/ -v
CONTROLLAB_BROWSER=firefox python -m pytest tests/wasm/ tests/e2e/ -v
```

As dependências PathView/PathSim fazem parte apenas do lock de provas externas (`requirements-browser.lock`) e não são empacotadas no bundle entregue ao navegador. `CONTROLLAB_CHROMIUM` e `CONTROLLAB_FIREFOX` permitem apontar para executáveis já provisionados.

O [workflow A–H](./.github/workflows/ci.yml) executa análise estática, os dois perfis matemáticos, testes web, Wasm, integração/E2E, segurança, artefatos reproduzíveis e publicação no GitHub Pages. Fixtures ouro e tolerâncias científicas nunca devem ser alteradas para forçar testes a passarem.

## Organização do repositório e contribuição

O [AGENTS.md](./AGENTS.md) define o protocolo de orquestração e o [CODEOWNERS](./CODEOWNERS) isola as oito frentes produtoras (`F1`–`F8`) da auditoria independente (`F9`):

| Frente | Responsabilidade | Diretórios principais |
| --- | --- | --- |
| **F1** | Core canônico, diagnósticos e I/O (`.ctrlab`, `.pvm`, PathSim) | `control_lab/core/`, `control_lab/diagnostics/`, `control_lab/io/` |
| **F2** | Álgebra e controle em espaço de estados | `control_lab/statespace/` |
| **F3** | Domínio da frequência SISO e MIMO ($\mathcal{H}_\infty$ DGKF) | `control_lab/frequency/` |
| **F4** | Identificação de sistemas | `control_lab/identification/` |
| **F5** | Controle Fuzzy, IEEE 1855 FML, TS e ANFIS | `control_lab/fuzzy/` |
| **F6** | Otimização, LMIs/SDP nativo escalável e solver educacional | `control_lab/optimization/`, `control_lab/experimental/sdp_educational/` |
| **F7** | Runtime Web, protocolo RPC, Pyodide Worker e IndexedDB | `web/bridge/`, `web/worker/`, `web/storage/` |
| **F8** | Interface TypeScript (Workspace-First, 6 abas, DSL v2.0, gráficos) | `web/app/`, `web/features/`, `web/charts/` |
| **F9** | Contratos finais, fixtures ouro, oráculos, E2E/Wasm, CI e auditoria | `contracts/`, `scripts/`, `tests/oracles/`, `tests/wasm/`, `tests/e2e/`, `docs/` |

Consulte também [`pyproject.toml`](./pyproject.toml), [`web/package.json`](./web/package.json) e [`docs/legal/DEPENDENCIES.md`](./docs/legal/DEPENDENCIES.md). Contribuições devem respeitar isolamento de frentes, tipos e revisões canônicas, convenção de sinal, verificação independente no motor Python e o checklist de 10 itens do Apêndice E.

## Licença e autoria

O código e a documentação originais do ControlLab Web são disponibilizados sob a [licença MIT](./LICENSE), com copyright de Víctor Campos e dos contribuidores do projeto. Ela permite uso, modificação, redistribuição e uso comercial, exigindo a preservação dos avisos de copyright e de permissão nas cópias ou porções substanciais do software.

O software é fornecido **no estado em que se encontra, sem garantia**, inclusive de funcionamento, adequação a uma finalidade ou suporte, nos termos da licença e da legislação aplicável. A maturidade beta e as limitações científicas documentadas continuam válidas.

Se utilizar o projeto em ensino ou pesquisa, agradecemos a citação indicada em [CITATION.cff](./CITATION.cff). Esse é um pedido voluntário, não uma condição adicional da MIT. Bibliotecas e recursos de terceiros mantêm suas [próprias licenças e avisos](./docs/legal/THIRD_PARTY_LICENSES.md); a licença MIT do projeto não os relicencia. A decisão e o escopo estão registrados na [ADR-011](./docs/architecture/ADR-011-mit-license-and-third-party-notices.md).
