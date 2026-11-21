# Documento Diretor da Bancada de LMIs e da Linguagem DSL (`CL-LMI-DSL-DIR-001 v1.0.0`)

**Subordinação Normativa:** Subordinado ao [`docs/architecture/ControlLab_Web_Design_Diretor_v1.0.md`](ControlLab_Web_Design_Diretor_v1.0.md) (`CL-UX-DIR-001 v1.0.0`) e ao `CL-DIR-001 v1.0.0` (ADR-010).  
**Escopo:** Arquitetura de UX/UI da **Aba 6 (`LMIs, SDPs e Síntese Robusta`)** e especificação formal da **DSL Declarativa de LMIs v2.0** com suporte a Sistemas Lineares (LTI e Planta Generalizada), Sistemas Politópicos Incertos, Modelos Takagi-Sugeno (TS) com premissas medidas/não medidas e Quantificadores/Domínios de Índices (`forall`).

---

## 1. Diagnóstico e Motivação da Evolução (v1.0 → v2.0)

A versão inicial da DSL (`lmi_dsl_parser.ts` v1.0) atende sistemas LTI nominais com matrizes fixas $(A, B, C, D)$ e condições matriciais únicas (como $A Q + Q A^T + B Y + Y^T B^T < 0$). Contudo, em síntese robusta e controle não linear convexo surgem três necessidades estruturais que uma condição matricial estática não cobre:

1. **Desacoplamento entre a Definição do Modelo e as Condições LMI:**
   - Antes de escrever as desigualdades matriciais, o usuário precisa visualizar e configurar qual é a **estrutura matemática da planta** sob análise:
     - **LTI Nominal ou Planta Generalizada:** além de $(A, B, C, D)$, canais de perturbação exógena $(B_w, D_{yw})$ e saída de desempenho ponderada $(C_z, D_{zu}, D_{zw})$ para formulações $\mathcal{H}_2 / \mathcal{H}_\infty$ via Bounded Real Lemma;
     - **Sistema Politópico Incerto:** politopo convexo de $N_v$ vértices $\mathcal{P} = \text{co}\{(A_i, B_i, B_{w,i}, C_i, D_i, C_{z,i}, D_{zu,i}, D_{zw,i})\}_{i=1}^{N_v}$ e qual símbolo de índice (ex.: `i`) indexa os vértices na DSL;
     - **Modelo Takagi-Sugeno (TS):** $N_r$ regras locais lineares ponderadas por funções de pertinência normalizadas $h_i(z(t)) \ge 0$, $\sum_{i=1}^{N_r} h_i(z(t)) = 1$, com indicação explícita das **funções de pertinência** e de quais **variáveis premissas $z(t)$ são medidas vs. não medidas** (essencial para síntese de controladores PDC e observadores TS com premissas estimadas $\hat{z}(t)$).
2. **Necessidade de Quantificadores e Relações entre Índices sem Loops Imperativos Arbitrários (`forall` declarativo):**
   - Em vez de permitir laços `for` imperativos arbitrários (que dificultam a interpretação matemática legível e a validação estática no navegador), a DSL deve oferecer **declarações explícitas de conjuntos de índices** (`index`) e **quantificadores de domínio estruturados** (`forall`), tais como:
     - $\forall i \in \{1,\dots,N\}$ (`forall i`);
     - $\forall i < j$ ou $\forall j > i$ (`forall i, j where j > i`) — indispensável para condições PDC relaxadas de Tuan/Tanaka ($\Upsilon_{ii} < 0$ e $\frac{2}{N-1}\Upsilon_{ii} + \Upsilon_{ij} + \Upsilon_{ji} < 0$, $\forall i < j$);
     - Múltiplos índices independentes (ex.: vértice da planta $i$, regra do controlador $j$, vértice do observador $k$).
3. **Interpretabilidade Bilateral (Leitura Matemática Tipográfica $\leftrightarrow$ Compilação Determinística para o Solver / CVXPY / YALMIP):**
   - Toda condição escrita com índices na DSL deve ser:
     1. **Renderizada em notação matemática legível** na coluna direita (ex.: exibindo $\forall i \in \{1..N_v\}$ e $\forall i, j \in \{1..N_r\},\; j > i$ ao lado dos blocos `bmat`);
     2. **Expandida deterministicamente** pelo parser em um conjunto finito de restrições LMI concretas sobre as matrizes dos vértices/regras do modelo ativo, permitindo testar a factibilidade diretamente no solver Python/Wasm (`native_primal_dual`) e exportar o código exato com laços `for` em **CVXPY** e **YALMIP**.

---

## 2. Arquitetura Visual da Aba 6 (`LMIs, SDPs e Síntese Robusta`)

A bancada da Aba 6 passa a ser organizada em **4 zonas sequenciais**:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ ZONA 1: Barra de Ações & Persistência (.lmi / Templates / Resolver / Exportar CVXPY/M)  │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ ZONA 2: Quadro de Caracterização do Sistema e Conjuntos de Índices (NOVO)               │
│  [ Classe do Sistema: (•) Linear / Planta Gen.  ( ) Politópico Incerto  ( ) Modelo TS ] │
│  ┌───────────────────────────────────────┬────────────────────────────────────────────┐ │
│  │ Matrizes & Canais Ativos do Modelo    │ Vértices / Premissas TS & Índices da DSL   │ │
│  │ • Dinâmica base: A (n×n), B (n×m)     │ • Nº de vértices/regras N = 4              │ │
│  │ • Saída medida: C (p×n), D (p×m)      │ • Índice principal de vértice/regra: [ i ] │ │
│  │ • [x] Canal exógeno w: Bw, Dyw        │ • Índices adicionais da DSL: [ j, k ]      │ │
│  │ • [x] Canal desempenho z: Cz, Dzu, Dzw│ • (Se TS) Premissas medidas: x1 (x2 não)   │ │
│  │ • Resumo dimensional e edição rápida  │ • (Se TS) Funções de pertinência h_i(z)    │ │
│  └───────────────────────────────────────┴────────────────────────────────────────────┘ │
├──────────────────────────────────────────┬──────────────────────────────────────────────┤
│ ZONA 3A: Editor DSL de LMIs (Monaco)     │ ZONA 3B: Leitura Matemática Interpretada     │
│  1│ system polytopic N=4 index i         │  [Sistema Politópico: N=4, índices i, j∈1..4]│
│  2│ index j in 1..N                      │  [var Q: sym(2×2)] [var Y_i: rect(1×2), i=1..4]│
│  3│ var Q sym(n)                         │                                              │
│  4│ var Y[i] rect(m, n)                  │  (1) Q ≻ 0                                   │
│  5│ Q > 0                                │  (2) ∀ i ∈ {1..4}:                           │
│  6│ forall i:                            │      Aᵢ Q + Q Aᵢᵀ + Bᵢ Yᵢ + Yᵢᵀ Bᵢᵀ ≺ 0     │
│  7│   A[i]*Q + Q*A[i]' + B[i]*Y[i]       │  (3) ∀ i, j ∈ {1..4}, j > i:                 │
│  8│     + Y[i]'*B[i]' < 0                │      Mᵢⱼ + Mⱼᵢ ≺ 0  (6 pares expandidos)     │
│  9│ recover K[i] = Y[i] * inv(Q)         │  Recuperação: Kᵢ = Yᵢ Q⁻¹ (i = 1..4)        │
├──────────────────────────────────────────┼──────────────────────────────────────────────┤
│ ZONA 4A: Certificado 5 Dimensões ADR-010 │ ZONA 4B: Espectro de Autovalores λ_min(F_b)  │
└──────────────────────────────────────────┴──────────────────────────────────────────────┘
```

---

## 3. Especificação do Quadro de Caracterização do Sistema (Zona 2)

Antes do editor de LMIs, o painel **`#lmi-system-characterization-card`** apresenta e permite configurar o sistema conectado à bancada:

### 3.1. Modo 1 — Sistema Linear (LTI Nominal ou Planta Generalizada)
- **Origem:** Herda a planta `StateSpace` ativa da sessão (ou permite edição/extensão local dos canais generalizados).
- **Matrizes Base:** $A \in \mathbb{R}^{n \times n}$, $B \in \mathbb{R}^{n \times m}$, $C \in \mathbb{R}^{p \times n}$, $D \in \mathbb{R}^{p \times m}$ (com indicação explícita de tempo contínuo $\dot{x}$ ou discreto $x_{k+1}$).
- **Extensão Opcional para Planta Generalizada ($P(s)$):**
  - Checkbox **`Habilitar canal de perturbação exógena w ($n_w$)`**: habilita e exibe as matrizes $B_w \in \mathbb{R}^{n \times n_w}$ e $D_{yw} \in \mathbb{R}^{p \times n_w}$ (com preenchimento padrão editável, ex.: $B_w = I$ ou coluna de perturbação);
  - Checkbox **`Habilitar canal de saída de desempenho z ($n_z$)`**: habilita e exibe as matrizes $C_z \in \mathbb{R}^{n_z \times n}$, $D_{zu} \in \mathbb{R}^{n_z \times m}$ e $D_{zw} \in \mathbb{R}^{n_z \times n_w}$;
  - **Símbolos disponíveis na DSL:** `A, B, C, D, Bw, Dyw, Cz, Dzu, Dzw` e dimensões `n, m, p, nw, nz`.

### 3.2. Modo 2 — Sistema Politópico Incerto ($\mathcal{P} = \text{co}\{G_1, \dots, G_{N_v}\}$)
- **Configurações Exibidas:**
  1. **Número de Vértices ($N_v \ge 2$):** seletor/input numérico (ex.: $N_v = 2, 4, \dots$) ou importação de `PolytopicUncertainStateSpace` registrado no Workspace;
  2. **Variável de Índice dos Vértices na DSL:** campo de texto curto (padrão `i`, permitindo `v`, `k`, etc.) que define como os vértices são referenciados no código (`A[i]`, `B[i]`, `Bw[i]`, `Cz[i]`, etc.);
  3. **Inspeção/Edição dos Vértices:** seletor rápido `Vértice 1 .. Vértice N_v` (ou gerador de caixa de incerteza paramétrica $\pm \delta\%$ sobre a planta nominal) mostrando as matrizes $(A_i, B_i, C_i, D_i)$ e opcionais $(B_{w,i}, C_{z,i}, D_{zu,i}, D_{zw,i})$ de cada vértice.

### 3.3. Modo 3 — Modelo Takagi-Sugeno (TS — Não Linear / Quase-LPV)
- **Configurações Exibidas:**
  1. **Número de Regras Locais ($N_r \ge 2$)** e **Índice Principal na DSL** (padrão `i`, mais segundo índice automático `j` para produtos cruzados $h_i(z) h_j(z)$);
  2. **Submodelos Lineares Locais $(A_i, B_i, C_i, D_i)$** (e canais generalizados opcionais $B_{w,i}, C_{z,i}, \dots$);
  3. **Quadro de Variáveis Premissas $z(t) = [z_1(t), \dots, z_q(t)]^T$ e Status de Medição:**
     - Lista cada variável premissa (ex.: $z_1 = x_1$, $z_2 = x_2$) com uma chave explícita **`[Medida]`** vs. **`[Não Medida / Estimada $\hat{z}$]`**;
     - Quando todas as premissas são medidas (`ts_measured`), habilita templates PDC padrão ($u = \sum_{i=1}^{N_r} h_i(x) K_i x$);
     - Quando há premissas não medidas (`ts_partially_observed`), exibe alerta estrutural e habilita variáveis de acoplamento/Lipschitz ($\gamma_L$) para síntese de observadores TS e controladores baseados em estados/premissas estimadas ($\hat{x}, \hat{z}$);
  4. **Resumo Visual das Funções de Pertinência $h_i(z)$:**
     - Exibe as expressões/curvas das funções de pertinência normalizadas ($h_i(z) \in [0, 1]$, $\sum_i h_i(z) = 1$) e permite importar diretamente a estrutura de pertinências da **Aba 5 (`Controle Fuzzy, TS e ANFIS`)** em 1 clique.

### 3.4. Declaração de Variáveis de Índice Adicionais
- Em qualquer modo, o usuário pode declarar **variáveis de índice extras** (ex.: `j`, `k`, `l`) vinculadas ao intervalo `1..N` (ou a um intervalo customizado `1..M`), que ficam imediatamente disponíveis para indexar variáveis de decisão (`P[i]`, `Y[i]`, `L[j]`) e blocos `forall` na DSL.

---

## 4. Especificação da Gramática da DSL de LMIs v2.0 (Sem `eval`, 100% Determinística)

A DSL v2.0 mantém compatibilidade total com os scripts v1.0 e adiciona 4 construções declarativas:

### 4.1. Declaração de Contexto e Índices (`system` e `index`)
```text
# Define ou confirma o modo do sistema e os índices (sincronizado com a Zona 2)
system polytopic vertices=4 index=i
# ou: system ts rules=2 index=i,j premises=measured
# ou: system lti generalized=true

index i in 1..N
index j in 1..N
```

### 4.2. Variáveis de Decisão Simples e Indexadas (`var`)
Além de variáveis comuns (como `var Q sym(n)` para Lyapunov quadrática comum), a DSL v2.0 suporta **famílias indexadas de variáveis de decisão**:
```text
var Q sym(n)                 # Matriz única comum (ex: Lyapunov comum)
var P[i] sym(n)              # Uma matriz simétrica P_i para cada i em 1..N (Lyapunov dependente de parâmetro)
var Y[i] rect(m, n)          # Ganho auxiliar PDC Y_i para cada regra/vértice i
var L_obs[i] rect(n, p)      # Ganho de observador L_i por regra/vértice
var gamma scalar             # Escalar de desempenho (ex: norma Hinf gamma ou gama^2)
```

### 4.3. Expressões Matriciais Indexadas e Símbolos Abreviados (`sym`, `He`)
- **Indexação de Matrizes do Sistema:** `A[i]`, `B[i]`, `C[i]`, `D[i]`, `Bw[i]`, `Cz[i]`, `Dzu[i]`, `Dzw[i]`, `Dyw[i]`.
- **Operador Simetrizador `He(X)` (Hermitiano / Simétrico):**
  - `He(A[i]*Q + B[i]*Y[i])` é expandido simbolicamente pelo parser para `A[i]*Q + Q*A[i]' + B[i]*Y[i] + Y[i]'*B[i]'`, reduzindo drasticamente erros de digitação em LMIs grandes e em blocos de Schur.
- **Atalho de Simetria em Blocos `bmat` (`*`):**
  - Dentro de `bmat([M11, M12; *, M22])`, o símbolo `*` abaixo da diagonal é automaticamente substituído pela transposta do bloco simétrico correspondente (`M12'`), padrão clássico da literatura de LMIs.

### 4.4. Quantificadores Estruturados de Índices (`forall`)
Para substituir laços `for` imperativos por uma sintaxe matemática legível e verificável, a DSL v2.0 introduz o bloco `forall`:

| Sintaxe na DSL | Significado Matemático | Expansão Determinística ($N=3$) |
|---|---|---|
| `forall i:` | $\forall i \in \{1,\dots,N\}$ | $(i=1), (i=2), (i=3)$ — $N$ LMIs |
| `forall i, j:` | $\forall (i,j) \in \{1,\dots,N\}^2$ | Todos os $N^2 = 9$ pares |
| `forall i, j where j > i:` | $\forall i \in \{1,\dots,N\},\; \forall j > i$ | $(1,2), (1,3), (2,3)$ — $\frac{N(N-1)}{2}$ LMIs |
| `forall i, j where j >= i:` | $\forall i \le j$ | $6$ pares (inclui diagonal) |
| `forall i, j where i != j:` | $\forall i \neq j$ | $N(N-1) = 6$ pares fora da diagonal |

**Exemplo 1 — Estabilização Robusta Politópica com Ganho Único ou Ganho por Vértice:**
```text
system polytopic vertices=4 index=i
var Q sym(n)
var Y rect(m, n)
Q > 0

forall i:
  He(A[i]*Q + B[i]*Y) < 0

recover K = Y * inv(Q)
```

**Exemplo 2 — Controle Fuzzy Takagi-Sugeno (PDC) com Relaxação de Soma Dupla ($\forall i$ e $\forall j > i$):**
```text
system ts rules=3 index=i,j premises=measured
var Q sym(n)
var Y[i] rect(m, n)
Q > 0

# Definicao de macro local opcional para o bloco cruzado M(i, j):
macro M(i, j) = A[i]*Q + Q*A[i]' + B[i]*Y[j] + Y[j]'*B[i]'

# (1) Condicoes diagonais: para todo i
forall i:
  M(i, i) < 0

# (2) Condicoes de acoplamento entre regras: para todo i e todo j > i
forall i, j where j > i:
  M(i, j) + M(j, i) < 0

forall i:
  recover K[i] = Y[i] * inv(Q)
```

**Exemplo 3 — Síntese $\mathcal{H}_\infty$ Politópica (Bounded Real Lemma com Planta Generalizada):**
```text
system polytopic vertices=2 index=i generalized=true
var Q sym(n)
var Y rect(m, n)
var gamma_sq scalar
minimize gamma_sq
Q > 0

forall i:
  bmat([He(A[i]*Q + B[i]*Y), Bw[i], (Cz[i]*Q + Dzu[i]*Y)'; *, -gamma_sq*I, Dzw[i]'; *, *, -I]) < 0

recover K = Y * inv(Q)
```

---

## 5. Compilação, Leitura Matemática e Limites de Envelope Wasm (ADR-010)

1. **Painel de Leitura Matemática Interpretada (Zona 3B):**
   - Exibe um cabeçalho de contexto resumindo o sistema e a cardinalidade da expansão:
     - Ex.: *"Sistema Takagi-Sugeno ($N_r = 3$ regras, premissas medidas) → **6 blocos LMI** compilados ($1$ de positividade + $3$ para $\forall i$ + $3$ para $\forall j > i$)."*
   - Formata os índices como subscritos tipográficos ($A_i, B_i, Y_j, K_i$), os quantificadores como $\forall i \in \{1..N\}$ e $\forall i, j \in \{1..N\},\; j > i$, `He(...)` como $\text{He}(\cdot)$ e os blocos `bmat` com substituição visual ou indicação explícita de `*` simétrico.
2. **Validação de Envelope e Compilação para o Solver (`F6` / `F8`):**
   - O compilador da DSL expande os blocos `forall` sobre os $N$ vértices/regras registrados na Zona 2 e monta o descritor canônico SDP (ou aciona o template correspondente em `control_lab/optimization/`).
   - Se o número total de variáveis escalares de decisão ($\sum \dim$) ou de blocos LMI exceder o envelope interativo do solver Wasm (`n > 12` ou `> 32` blocos LMI), a interface exibe o banner pedagógico do **ADR-010** e mantém a **exportação de scripts CVXPY (`.py`) e YALMIP (`.m`) 100% funcional** (gerando os laços `for i in range(N):` e `for j in range(i + 1, N):` limpos no código exportado).

---

## 6. Fila Planejada de WorkPackages para Implementação Futura (Fase 3 — Aba 6 & DSL v2.0)

Quando esta frente for iniciada, ela deverá ser executada nos seguintes pacotes modulares:

1. **`WP-LMI-V2-01-DSL-PARSER-QUANTIFIERS` (`f8-ui-charts`)**:
   - Estender [`web/features/views/lmi_dsl_parser.ts`](../../web/features/views/lmi_dsl_parser.ts) para suportar `system`, `index`, variáveis indexadas `var Y[i]`, matrizes generalizadas (`Bw, Cz, Dzu, Dzw, Dyw`), `He(...)`, simetria `*` em `bmat`, `macro M(i, j)` e quantificadores `forall i` / `forall i, j where j > i`, com contagem exata de blocos expandidos e zero uso de `eval`.
2. **`WP-LMI-V2-02-SYSTEM-CHARACTERIZATION-UI` (`f8-ui-charts`)**:
   - Implementar a **Zona 2 (`#lmi-system-characterization-card`)** em [`web/features/views/lmi_view.ts`](../../web/features/views/lmi_view.ts) com os 3 modos (Linear / Planta Generalizada, Politópico Incerto com $N_v$ vértices e índice configurável, e Takagi-Sugeno com funções de pertinência e seleção de premissas medidas vs. não medidas) + sincronização bidirecional com o editor DSL.
3. **`WP-LMI-V2-03-BACKEND-COMPILER-AND-EXPORTERS` (`f6-optimization-lmi` / `f1-core-io`)**:
   - Conectar a expansão multi-vértice / multi-regra (`forall`) ao solver Python `optimization.solve` e aos exportadores `optimization.export_cvxpy` / `optimization.export_yalmip` (gerando laços `for i` e `for j > i` nativos em Python/MATLAB).
4. **`WP-LMI-V2-04-F9-AUDIT` (`f9-integration-qa`)**:
   - Auditoria independente em navegador real validando sistemas LTI generalizados, politópicos e Takagi-Sugeno na Aba 6.
