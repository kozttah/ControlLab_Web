# Fila de Refatoração Modular de UX/UI — `CL-UX-DIR-001 v1.0.0` (2026-11-19)

**Base normativa:** [`docs/architecture/ControlLab_Web_Design_Diretor_v1.0.md`](../architecture/ControlLab_Web_Design_Diretor_v1.0.md) (`CL-UX-DIR-001 v1.0.0`), subordinado ao `CL-DIR-001 v1.0.0`.  
**Estado de partida:** 46/46 WorkPackages anteriores (`WP-01`..`WP-AUDIT-FIX-F8-MODERN-UI-CHART-EXPORT`) aceitos pela F9 no commit `6982ecf`.

## Diagnóstico que Motivou a Nova Fila

Embora os contratos científicos, gates F0 (`G-0A`..`G-0D`) e verticais iniciais de Identificação/SISO/LQR funcionem e passem nos testes, a apresentação atual concentrada em [`web/app/main.ts`](../../web/app/main.ts) (~2.530 linhas) expõe termos internos de RPC/QA (`core.reuse_model`, `T-ID-*`, `Fast-Preview`, `rCARE`), mistura seleção genérica tipada com controles de domínio e ainda não reproduz a ergonomia esperada de ferramentas como MATLAB `ident`, `sisotool` e o laboratório Fuzzy legado.

## WorkPackages Registrados em `PROJECT_STATE.json`

1. **`WP-UX-REFACTOR-01-SHELL-DOCK`** (`f8-ui-charts`):
   - Extrair **Workspace Dock** esquerdo ([`web/app/workspace_dock.ts`](../../web/app/workspace_dock.ts)) e **Inspetor Técnico R-27 / JSON** recolhível ([`web/app/inspector_drawer.ts`](../../web/app/inspector_drawer.ts));
   - Limpar jargões internos da bancada principal aplicando o *Dicionário de Tradução Semântica* (`CL-UX-DIR-001` Seção 2);
   - Adicionar modal unificado `+ Novo` (TF por `num/den`, StateSpace matricial, Dataset CSV/Tabela) eliminando a necessidade de edição JSON inline na tela principal;
   - Preservar todos os invariantes (`R-23`, `R-26`, `R-27`, `T-UI-01`) e compatibilidade dos testes F8/E2E.

2. **`WP-UX-REFACTOR-02-IDENT-SISO-LQR`** (`f8-ui-charts`):
   - Desmontar as bancadas 1, 2 e 3 em módulos dedicados (`web/features/views/identification_view.ts`, `siso_view.ts`, `statespace_view.ts`);
   - **Aba 1 (`ident`):** barra guiada de 3 etapas, comparação multi-modelo por checkboxes, seletor explícito *Simulação Livre* vs *Previsão 1-Passo*, envio 1-clique (`→ SISO`, `→ SS/LQR`);
   - **Aba 2 (`sisotool`):** diagrama de malha clicável no cabeçalho, sintonizador `C(s)`, grid 2×2 e **datatips interativos ao clicar** (Bode: $\omega$/Mag/Fase; Nyquist: $\omega$/Re/Im; Lugar das Raízes: ganho $K$ e congelamento de todos os polos em malha fechada);
   - **Aba 3 (State-Space & LQR):** editor matricial compacto em abas (`A|B|C|D`, `Q|R|x0`), modal `JSON…` documentado, cards de KPI e comparador de experimentos.

3. **`WP-UX-REFACTOR-03-MIMO-FUZZY-LMI`** (`f8-ui-charts`):
   - Extrair bancadas 4, 5 e 6 (`mimo_view.ts`, `fuzzy_view.ts`, `lmi_view.ts` + `lmi_dsl_parser.ts`);
   - **Aba 4 (MIMO):** valores singulares $\sigma(G, S, T, KS)$ e heatmap RGA interativo por slider $\omega$;
   - **Aba 5 (Fuzzy/TS):** editor visual de pertinências (inspirado em `docs/references/legacy_fuzzy_lab/`), matriz de regras 2D, importação/exportação FML segura;
   - **Aba 6 (LMIs/SDP):** editor de texto estilo Monaco com template inicial, salvar/carregar `.lmi`, **interpretador matemático legível em tempo real** (parser seguro sem `eval`, detecção de termos bilineares `K*Q`), certificado em 5 dimensões e exportação CVXPY/YALMIP.

4. **`WP-UX-REFACTOR-04-F9-BROWSER-AUDIT`** (`f9-integration-qa`):
   - Auditoria independente F9 em Chromium e Firefox (desktop `1280×800` e mobile `390×844`) validando os 5 critérios de usabilidade da Seção 8 de `CL-UX-DIR-001` e toda a matriz normativa (`T-UI-01`, `T-ID-*`, `T-FREQ-*`, `T-SDP-*`, `R-23`, `R-26`, `R-27`).
