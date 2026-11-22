# ADR-014 — Definição Centralizada de Sistemas Dinâmicos no Workspace (Workspace-First)

- **Status:** `ACCEPTED`
- **Data:** `2026-11-22`
- **Autoridade:** `project_coordinator`
- **Documentos Relacionados:** `CL-DIR-001 v1.0.0`, [`ControlLab_Web_Design_Diretor_v1.0.md`](ControlLab_Web_Design_Diretor_v1.0.md) (`CL-UX-DIR-001`), [`ControlLab_Web_LMI_DSL_Design_Diretor_v1.0.md`](ControlLab_Web_LMI_DSL_Design_Diretor_v1.0.md) (`CL-LMI-DSL-DIR-001`), [`ADR-006`](../../ControlLab_Web_Documento_Diretor_v1.0.md), [`ADR-010`](ADR-010-native-sdp-and-offline-exports.md), [`ADR-013`](ADR-013-pvm-nonlinear-boundary-and-pathsim-export.md).

---

## 1. Contexto e Problema

Durante a evolução incremental das bancadas (Fases UX-1 a UX-7), a definição e a edição de modelos dinâmicos ficaram fragmentadas entre múltiplos locais da interface:

1. **Duplicação de editores de sistema entre abas:** a Aba 6 (`LMIs, SDPs e Síntese Robusta`) mantinha seu próprio editor embutido de classe do sistema (`#lmi-sys-class-select`), canais generalizados (`Bw, Dyw, Cz, Dzu, Dzw`), vértices politópicos, regras Takagi-Sugeno (TS), premissas e funções de ponderação $h_i(z)$, desconectado do ciclo de revisões imutáveis do **Workspace Dock**. De modo semelhante, a Aba 3 (`Espaço de Estados & LQR`) misturava visualmente a edição da planta com os parâmetros de projeto do controlador ($Q, R, x_0$).
2. **Tetos artificiais de cardinalidade na Aba 6:** o editor embutido da Aba 6 impunha tetos rígidos de **8 vértices** para sistemas politópicos incertos e **6 regras** para sistemas Takagi-Sugeno, impedindo a modelagem de sistemas multi-vértice maiores (por exemplo, $2^q$ regras para $q \ge 3$ não-linearidades setoriais, ou politopos com $N_v \ge 9$ vértices destinados à exportação CVXPY/YALMIP sob `ADR-010`).
3. **Quebra da fonte única de verdade (SSOT):** editar um sistema apenas localmente dentro da Aba 6 não registrava nova revisão imutável no `TypedObjectWorkspace`, não atualizava o Workspace Dock e dificultava o reuso entre bancadas e a serialização canônica no arquivo `.ctrlab`.

---

## 2. Decisão Arquitetural Normativa (Workspace-First)

Fica estabelecido o princípio arquitetural **Workspace-First (Pilar 5 de `CL-UX-DIR-001`)**:

### 2.1 Fonte Única de Definição e Edição de Sistemas (Workspace Dock)
**Todas** as definições e edições de sistemas/plantas dinâmicas da sessão são criadas e editadas exclusivamente no **Workspace Dock** (`#workspace-dock-aside`), por meio do modal unificado **`+ Novo` / `Editar`** (`#workspace-new-object-modal`), gerando objetos canônicos imutáveis com incremento monotônico de `revision`:

1. **Função de Transferência (`TransferFunction`):** polinômios `num(s)/den(s)` ou `num(z)/den(z)` com tempo de amostragem opcional `dt`.
2. **Espaço de Estados Linear e Planta Generalizada (`StateSpace`):** matrizes base $(A, B, C, D)$ e, opcionalmente, canais generalizados de perturbação exógena $w$ (`Bw`, `Dyw`) e saída de desempenho $z$ (`Cz`, `Dzu`, `Dzw`) persistidos em `provenance.generalized_channels`.
3. **Sistema Politópico Incerto (`polytopic_uncertain`):** número **ilimitado** ($N_v \ge 2$, sem teto artificial de 8 vértices) de vértices editáveis $(A_i, B_i, C_i, D_i)$ com adição/remoção dinâmica e gerador opcional de caixa paramétrica $\pm \delta\%$.
4. **Sistema Takagi-Sugeno (`ts_measured` e `ts_partially_observed`):**
   - Número **ilimitado** ($N_r \ge 2$, sem teto artificial de 6 regras) de regras locais editáveis $(A_i, B_i, C_i, D_i)$;
   - Lista dinâmica de variáveis premissas $z_k$ com domínio explícito $[z_{\min}, z_{\max}]$ e classificação **Medida** vs. **Não Medida / Estimada** (derivando automaticamente `kind = "ts_measured"` quando todas as premissas são medidas ou `kind = "ts_partially_observed"` quando há ao menos uma premissa não medida, preservando a semântica de `ADR-006`);
   - Editor de funções analíticas de ponderação setorial $h_i(z)$ com validador determinístico de soma convexa ($h_i(z) \ge 0$ e $\sum_i h_i(z) = 1$ no domínio $\Omega$, sem `eval`/`new Function`).
5. **Séries Temporais (`Dataset`):** importação CSV / tabular e particionamento cronológico treino/holdout.

Cada sistema listado no Workspace Dock oferece ações rápidas contextuais (`Editar`, `→ SISO`, `→ SS/LQR`, `→ MIMO`, `→ LMIs`).

### 2.2 Separação Estrita nas Abas de Projeto (Abas 1 a 6)
As **Abas 1 a 6** consomem sistemas registrados no Workspace e concentram **estritamente parâmetros de análise e projeto**:

- **Aba 1 (`identification`):** seleciona `Dataset` do Workspace; configura pré-processamento, ordem e algoritmo (`ARX`/`OE`/`MOESP`) e registra `IdentifiedModel`.
- **Aba 2 (`siso_frequency`):** seleciona planta SISO do Workspace; projeta compensador $C(s)$, atraso de transporte $\tau$ e grade $\omega$.
- **Aba 3 (`statespace`):** exibe barra da planta ativa do Workspace (`#ss-workspace-plant-bar`) com atalhos de 1 clique **`Editar Planta no Workspace…`** (`#btn-ss-edit-plant-workspace`) e **`+ Nova Planta`** (`#btn-ss-new-plant-workspace`), destacando os parâmetros de projeto da aba (`Q`, `R`, `x0`, método CARE/DARE, observador/LQG e comparador de experimentos).
- **Aba 4 (`mimo_frequency`):** seleciona planta MIMO do Workspace; configura faixa $\omega$, ponderações $W_S, W_U, W_T$ e síntese $H_\infty$ (`ADR-012`).
- **Aba 5 (`fuzzy_ts`):** configura regras Fuzzy Mamdani/TS, pertinências, FML IEEE 1855, treinamento ANFIS e exportação PathSim (`ADR-013`).
- **Aba 6 (`optimization_lmi`):** seleciona qualquer sistema do Workspace via **`#lmi-workspace-system-select`** (LTI, Planta Generalizada, Politópico Incerto ou TS), exibe um resumo somente leitura (**`#lmi-selected-system-summary`**) e disponibiliza atalhos de 1 clique **`Editar Sistema no Workspace…`** (`#btn-lmi-edit-system-workspace`) e **`+ Novo Sistema`** (`#btn-lmi-new-system-workspace`). Permanecem na Aba 6 exclusivamente os controles de projeto LMI: conjuntos de índices da DSL (`i, j, k`), painel de perturbações `dA[k]`/`dC[k]` e gerador de observador TS para premissas não medidas (`#lmi-ts-unmeasured-panel`), editor DSL v2.0, compilador direto, solver SDP com cancelamento e certificado 5D (`ADR-010`) e exportadores CVXPY/YALMIP.

---

## 3. Conformidade com Schemas Canônicos (`contracts/schemas/`)

A arquitetura Workspace-First preserva integralmente os JSON Schemas canônicos v1.0.0 sem alterar `contracts/schemas/` nem `contracts/fixtures/`:

1. **`state_space.schema.json`:**
   - Raiz (`additionalProperties: false`) e `matrices` (`A, B, C, D`, `additionalProperties: false`) permanecem 100% conformes.
   - Os canais generalizados opcionais (`enable_w`, `enable_z`, `Bw`, `Dyw`, `Cz`, `Dzu`, `Dzw`) são armazenados em `provenance.generalized_channels`, aproveitando `provenance: { "type": "object", "additionalProperties": true }`.
2. **`ts_state_space.schema.json`:**
   - `kind` assume estritamente `"polytopic_uncertain"`, `"ts_measured"` ou `"ts_partially_observed"`.
   - `vertices[]` aceita qualquer quantidade $N \ge 1$ de vértices (`vertex_id, A, B, C, D`), sem limite superior artificial.
   - `premise_availability` (`additionalProperties: false`) preenche `mode` (`"all_measured"`, `"partially_observed"`, `"unknown_uncertain"`), `measured_premises`, `unmeasured_premises` e `estimator_required_for_pdc`.
   - `domain.bounds` armazena `[z_min, z_max]` por premissa; `membership_spec.functions[]` e `membership_spec.sum_to_one_domain` persistem as expressões analíticas $h_i(z)$ e o resultado da validação convexa.

---

## 4. Persistência Round-Trip `.ctrlab` e Invariantes de Segurança

1. **Round-trip `.ctrlab`:** `ControlLabShell.exportCtrlab` serializa todos os modelos registrados no `TypedObjectWorkspace` (incluindo `StateSpace` com `provenance.generalized_channels`, `polytopic_uncertain`, `ts_measured` e `ts_partially_observed`) no vetor `project.models`, junto com o estado de projeto LMI da Aba 6. `ControlLabShell.importCtrlab` restaura todos os modelos no Workspace Dock e reconecta a seleção da Aba 6 preservando revisões, vértices, premissas e expressões $h_i(z)$.
2. **Imutabilidade e versionamento:** toda edição via `Editar` / `Editar Sistema no Workspace…` / `Editar Planta no Workspace…` cria uma nova revisão monotônica (`revision + 1`), jamais mutando silenciosamente uma revisão anterior em uso por resultados auditados (`R-27`).
3. **Segurança passiva (`R-21`):** a avaliação das funções analíticas $h_i(z)$ usa exclusivamente analisador recursivo determinístico sem `eval` ou `new Function`, e toda exportação/importação `.ctrlab` / `.lmi` permanece estritamente passiva (`code_executed=False`).
