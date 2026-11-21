# Fila de Evolução Funcional, Ergonomia de Bancada e Síntese Avançada — `CL-UX-DIR-001 v1.1` (2026-11-21)

**Base normativa:** [`docs/architecture/ControlLab_Web_Design_Diretor_v1.0.md`](../architecture/ControlLab_Web_Design_Diretor_v1.0.md) (`CL-UX-DIR-001`) e `CL-DIR-001 v1.0.0`.  
**Estado de partida:** `54/54` WorkPackages aceitos pela F9 no commit `dad9086`.

---

## 1. Melhorias Imediatas de Ergonomia e Fluxo de Bancada (Fase 1 — Curto Prazo — `F8` / `F3`)

### 1.1. Gerenciamento do Workspace Dock: Botão `Limpar Workspace` e Menu/Botão `Carregar Exemplo...`
- **Situação atual:** À medida que o usuário importa datasets, estima modelos ARX/Subespaços e promove plantas para SISO/LQR, o **Workspace Dock** ([`web/app/workspace_dock.ts`](../../web/app/workspace_dock.ts)) acumula muitos objetos na sessão sem opção de limpeza rápida. Por outro lado, manter o carregamento rápido de plantas/datasets de exemplo é essencial para testes ágeis.
- **Solução planejada:**
  - Adicionar no cabeçalho/rodapé do **Workspace Dock** (`#workspace-dock-aside`):
    1. **Botão `Limpar Workspace` (`#btn-dock-clear-workspace`)**: remove todos os objetos registrados na sessão (datasets, plantas identificadas/customizadas e controladores salvos) e reseta as seleções tipadas de forma limpa;
    2. **Botão / Seletor `Carregar Exemplo...` (`#btn-dock-load-example` / `#dock-example-select`)**: restaura ou carrega em 1 clique sistemas canônicos prontos para teste rápido (Integrador Duplo 2×1, Massa-Mola-Amortecedor, Pêndulo Linearizado, Planta MIMO 2×2 Acoplada, Dataset PRBS de Identificação e Controlador PD Fuzzy), mantendo a facilidade de teste atual mesmo após limpar o workspace;
    3. **Botão individual `×` (Remover item)** em cada card do Workspace Dock para excluir apenas um objeto específico sem precisar limpar toda a sessão.

### 1.2. Importação de Arquivo `.csv` por Botão no Workspace (`+ Novo`) e na Aba 1 (`Identificação`)
- **Situação atual:** Tanto o modal `+ Novo` (`Dataset CSV` em [`web/app/workspace_dock.ts`](../../web/app/workspace_dock.ts)) quanto o card da Etapa 1 na Aba 1 ([`web/features/views/identification_view.ts`](../../web/features/views/identification_view.ts)) exigem que o usuário digite ou cole o texto CSV manualmente em um `<textarea>`.
- **Solução planejada:**
  - Adicionar botão **`Carregar arquivo .csv...`** (`<input type="file" accept=".csv,.txt">`) tanto no modal `+ Novo` (aba *Série Temporal CSV*) quanto no card **1. Dados & Partição** da Aba 1 (`#id-csv-file-input`).
  - Ao selecionar o arquivo local, ler o conteúdo passivamente via `FileReader` / `file.text()`, preencher o `<textarea>` de pré-visualização, validar o cabeçalho (`t, u, y` ou `t, u1..um, y1..yp`) e oferecer opção de importar e particionar imediatamente.

### 1.3. Correção da Legenda e Cores Distintas no Gráfico de Validação da Aba 1 (`Identificação`)
- **Causa-raiz diagnosticada:**
  - Em [`web/charts/scientific_chart.ts`](../../web/charts/scientific_chart.ts) (`buildIdentificationResponseChartModel`, linhas 291–325), os 3 canais principais (`y Medido (Holdout)`, `ŷ Previsão 1-Passo (Holdout)` e `ŷ Simulação Livre (Holdout)`) são criados com `group: "y"`.
  - Em `renderTimeResponseSvg` (linhas 1866–1908), todas as séries com `group === "y"` recebem a **mesma cor** (`theme.chartClosedLoop`) e a legenda do gráfico exibe um texto fixo genérico de Espaço de Estados (`— Saída (y) | -- Entrada (u) | ·· Estado (x)`), sem distinguir a **Saída Medida do Dataset ($y_{\text{medido}}$)** da **Saída Prevista pelo Modelo ($\hat{y}$ — Simulação Livre / Previsão 1-Passo)**!
- **Solução planejada:**
  - Fazer `renderTimeResponseSvg` renderizar a legenda dinâmica a partir dos rótulos reais de `model.channels` (`ch.label`) quando houver múltiplas séries de saída, atribuindo cores e tracejados contrastantes e explícitos:
    - **Saída do Conjunto de Dados ($y$ medido):** traço sólido espesso (`theme.chartOpenLoop` / cinza-azulado escuro ou ciano no alto contraste);
    - **Saída Prevista pelo Modelo — Simulação Livre ($\hat{y}_{\text{sim}}$):** traço sólido/tracejado em destaque (`theme.chartClosedLoop` / azul primário);
    - **Saída Prevista pelo Modelo — Previsão 1-Passo ($\hat{y}_{1\text{-passo}}$):** traço pontilhado distinto (`theme.chartOverlayExact` / verde esmeralda);
    - **Resíduo ($e = y - \hat{y}$):** traço fino secundário.

### 1.4. Editor de Compensador Dinâmico $C(s)$ / $C(z)$ na Aba 2 (`Projeto SISO`)
- **Situação atual:** A bancada SISO ([`web/features/views/siso_view.ts`](../../web/features/views/siso_view.ts) e [`web/features/siso_workspace.ts`](../../web/features/siso_workspace.ts)) só permite variar um ganho escalar puro $C(s) = K$, embora o motor Python ([`control_lab/frequency/siso/design.py`](../../control_lab/frequency/siso/design.py)) já possua `design_lead`, `design_lag`, `design_lead_lag`, `design_pid` e convolução polinomial `_series_tf(C, G)`.
- **Solução planejada:**
  - Tornar o bloco **`C(s)`** no diagrama de malha do topo e um novo botão **`Editar Compensador C(s)...`** (`#btn-siso-edit-compensator`) interativos, abrindo um modal/painel com 3 modos complementares (editáveis a qualquer momento pelo usuário):
    1. **Função de Transferência Direta (`num / den`)**: campos de coeficientes do numerador e denominador (igual ao construtor guiado do `+ Novo`), ex.: `num = 2, 4`, `den = 1, 10`;
    2. **Polos, Zeros e Ganho ($K, z_i, p_i$)**: botões **`+ Adicionar Zero`** e **`+ Adicionar Polo`** (reais ou pares complexos conjugados, incluindo integrador puro em $s=0$) com edição/remoção individual;
    3. **Estrutura Clássica (PID / Avanço-Atraso Lead-Lag)**: síntese assistida via `control_lab/frequency/siso/design.py` que preenche o `C(s)` resultante para ajuste fino posterior.
  - Conectar $L(s) = C(s)G(s)$ em todas as chamadas de Bode, Nyquist, Margens, Lugar das Raízes e Resposta ao Degrau em Malha Fechada ($T(s) = \frac{C(s)G(s)}{1 \pm C(s)G(s)}$), mantendo o slider de ganho $K$ como multiplicador global em tempo real do compensador $C(s)$.

### 1.5. Botão de Limpar / Resetar / Excluir Sistema e Termos na Aba 5 (`Controle Fuzzy, TS e ANFIS`)
- **Situação atual:** Em [`web/features/views/fuzzy_view.ts`](../../web/features/views/fuzzy_view.ts), a bancada inicializa com `fuzzy-pd-starter` (3 termos em `erro`, 3 em `derivada`, 5 em `controle` e 9 regras). Mesmo trocando entre Mamdani e Takagi-Sugeno, não há botão para **apagar/resetar o sistema fuzzy**, **remover uma variável**, **excluir um termo de pertinência (`- Termo`)** ou **limpar a base de regras**, impedindo o usuário de construir um conjunto do zero ou substituir o sistema ativo.
- **Solução planejada:**
  - Adicionar na barra de ferramentas da Aba 5 os botões:
    - **`Novo / Limpar Sistema Fuzzy`** (`#btn-fuzzy-clear-system`): apaga o sistema atual (ou reinicia com template mínimo editável vazio) e remove o registro antigo do Workspace se desejado;
    - **`Restaurar Exemplo PD`** (`#btn-fuzzy-reset-starter`): recarrega o controlador PD canônico quando o usuário quiser um exemplo;
    - Botão **`Excluir Termo`** (`data-action="fuzzy-remove-term"`) ao lado de cada função de pertinência (`N, Z, P...`), botão **`+ Variável` / `Remover Variável`** e botão **`Limpar Regras`** na matriz de regras.

---

## 2. Expansão de Síntese e Controle Avançado (Fase 2 — Médio/Longo Prazo — `F2` / `F3` / `F6` / `F8`)

### 2.1. Aba 3 (`Espaço de Estados`) — Sintonia de Observador de Estados / Filtro de Kalman e Controle por Realimentação de Estados Estimados (LQG / $u = -K\hat{x}$)
- **Base existente no motor Python (`F2`):**
  - [`control_lab/statespace/design.py`](../../control_lab/statespace/design.py) e [`control_lab/core/rpc.py`](../../control_lab/core/rpc.py) **já implementam e expõem via RPC**:
    - `statespace.design_observer` (alocação de polos do observador de Luenberger $A - LC$, dual de $(A^T, C^T)$ com verificação PBH de detectabilidade);
    - `statespace.design_kalman` (filtro de Kalman contínuo/discreto via CARE/DARE dual com covariâncias $Q_n, R_n$ e ganho $L$);
    - `statespace.design_lqg` (combinação do regulador ótimo $K$ com o estimador de Kalman $L$, retornando o `DynamicController` completo em espaço de estados e a matriz aumentada de malha fechada $2n \times 2n$ pelo princípio da separação).
- **O que falta construir na Bancada da Aba 3 (`statespace_view.ts`):**
  - Adicionar na coluna de síntese da Aba 3 o quadro **"Observador de Estados / Filtro de Kalman & Controle LQG ($u = -K\hat{x}$)"** com dois modos de sintonia do estimador $L$:
    1. **Filtro de Kalman (Estocástico)**: edição/escala das covariâncias de ruído de processo $Q_n$ e ruído de medição $R_n$;
    2. **Observador de Luenberger (Alocação de Polos)**: escolha dos polos desejados do observador (ou fator de velocidade $2\times$–$10\times$ mais rápido que os polos de $A - BK$).
  - Exibir lado a lado:
    - Ganho do controlador $K$, Ganho do observador $L$, Polos de regulação $\lambda(A - BK)$ e Polos de estimação $\lambda(A - LC)$ (com cores/símbolos distintos no Mapa Polo-Zero);
    - Simulação temporal comparando os estados reais $x(t)$ vs. estados estimados $\hat{x}(t)$ (com erro inicial de estimação $e(0) = x(0) - \hat{x}(0) \neq 0$) e a resposta em malha fechada realimentando $\hat{x}(t)$;
    - Registro direto do controlador dinâmico LQG (`DynamicController`) no Workspace Dock e exportação `.pvm`.

### 2.2. Aba 4 (`Frequência MIMO`) — Quadro de Síntese Multivariável: Desacoplador por SVD + Ajuste Realizável e Ensaios em Malha Fechada
- **Objetivo:** Adicionar abaixo do quadro atual de análise ($\sigma(\omega)$ e RGA) um **Quadro de Síntese e Teste em Malha Fechada MIMO** com duas abordagens práticas:
  1. **Projeto de Desacoplador via SVD em Pontos de Frequência + Aproximação Realizável ($D(s)$)**:
     - Seleção de frequência(s) alvo $\omega_0$ (ou faixa de cruzamento $[\omega_1, \omega_2]$) onde se calcula a decomposição em valores singulares de $G(j\omega_0) = U \Sigma V^H$ (ou alinhamento de fase/quadros de rotação reais) e se aproxima a matriz de pré-compensação/desacoplamento $W_1(s)$ por funções de transferência próprias e realizáveis de baixa ordem (ganho estático, 1ª ordem ou avanço-atraso canal a canal) tais que $G_{\text{des}}(s) = G(s) W_1(s)$ seja aproximadamente diagonal ($\Lambda(G_{\text{des}}) \approx I$);
     - Visualização imediata do **novo Heatmap RGA** e dos **valores singulares da planta desacoplada** $G(s)W_1(s)$.
  2. **Síntese Descentralizada / Distribuída e Ensaio em Malha Fechada MIMO**:
     - Com a planta desacoplada (ou usando o pareamento sugerido pela RGA), permitir definir controladores SISO diagonais $K_{\text{diag}}(s) = \text{diag}(c_1(s), \dots, c_m(s))$ (ou controlador multivariável distribuído/com acoplamento cruzado);
     - Simular a **Resposta Temporal ao Degrau Multivariável (canal a canal)** em malha fechada ($r_1 \to y_1, y_2$ e $r_2 \to y_1, y_2$) evidenciando a redução da interação cruzada (acoplamento entre canais) com e sem o desacoplador, além de atualizar $S_o(j\omega)$, $T_o(j\omega)$ e $K S_o(j\omega)$.

### 2.3. Aba 4 / Aba 6 — Quadro de Síntese $\mathcal{H}_\infty$ com Planta Generalizada ($P(s)$, Pesos $W_S, W_U, W_T$)
- **Objetivo:** Oferecer uma bancada guiada de **Síntese Robusta $\mathcal{H}_\infty$ (Sensibilidade Mista $S / KS / T$)** baseada em Planta Generalizada $P(s)$:
  - Definição visual dos filtros de ponderação na frequência:
    - $W_1(s) = W_S(s)$ (peso de desempenho / rejeição de perturbação em baixa frequência: ganho DC alto, banda passante $\omega_B$, pico $M_S$);
    - $W_2(s) = W_U(s)$ (peso de esforço de controle / limitação de atuador);
    - $W_3(s) = W_T(s)$ (peso de robustez a incerteza multiplicativa / ruído em alta frequência).
  - Construção automática da planta generalizada $P(s)$ (2 portas: $[w; u] \to [z; y]$ com $z = [W_S e;\; W_U u;\; W_T y]^T$) e síntese do controlador $\mathcal{H}_\infty$ (via formulação LMI/Riccati de sensibilidade mista no motor Python / exportação reprodutível CVXPY / `python-control` / YALMIP quando fora do envelope Wasm), plotando os valores singulares de malha fechada $\bar{\sigma}(S(j\omega))$ contra o gabarito inverso $1/|W_S(j\omega)|$ e $\bar{\sigma}(T(j\omega))$ contra $1/|W_T(j\omega)|$.
