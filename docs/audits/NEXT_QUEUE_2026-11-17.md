# Próxima fila vertical — proposta F9, 2026-11-17

Fonte consultada: main `9161586a554debd144c6861464e7b8f6f4534953`, CL-DIR-001 §14.2, §15.3, R-03/R-06/R-07/R-19/R-26/R-27, Apêndices C/E. Documento de planejamento por inspeção estática; não é aceite de implementação nem evidência de execução de novas funcionalidades. Não modifica fixtures ouro, tolerâncias, governança ou PROJECT_STATE.

## Diagnóstico verificável

- Os quatro gates da Fase 0 possuem aceite, com domínio documentado em `docs/audits/RELATORIO_STATUS_GATES_FASE0.md`. Isso não homologa automaticamente as demais verticais de §14.2.
- `web/app/main.ts`, handler `execute-tool`, registra o StateSpace do workspace LQR e envia `plant_ref` a todas as cards; o resultado genérico abre um modal JSON. A arquitetura de cards e as APIs já existem.
- `web/features/tool_catalog.ts`, card `identification.fit_arx`, oferece apenas na/nb/nk. `control_lab/core/rpc.py::_handle_identification` exige dataset/dataset_ref ou vetores u/y. Não há seleção/importação de dataset nesse fluxo de execução. A card ARX isolada não constitui uma vertical utilizável de identificação.
- O RPC já oferece ARX/OE/subespaços/validação e os respectivos módulos científicos têm implementação. ARX retorna `IdentifiedModel.model` do tipo TransferFunction; `TransferFunction.to_state_space()` existe em `control_lab/core/models.py`. Não foi encontrada operação RPC pública de conversão TF→SS na lista SUPPORTED_OPERATIONS; a UI não deve recriar essa álgebra em TypeScript.
- O RPC já oferece LQG/Kalman/observador/root_locus/margens/RGA/sensibilidade/FML. O catálogo não oferece cards para vários desses métodos. Não se propõe reimplementar os backends aceitos em CPython.
- A card fuzzy só oferece grid/profile, enquanto `_handle_fuzzy` exige FuzzySystem. O plant_ref atualmente fornecido é StateSpace do LQR.
- Os E2E existentes comprovam a vertical LQR, seus arquivos, revisões e interação. Não há E2E de identificação→reutilização em LQR/SISO nos arquivos `tests/e2e/` inspecionados.
- O projeto `.ctrlab` homologado pela UI cobre workspace LQR com opções PVM. O plano abaixo não anuncia round-trip genérico de todos os datasets/modelos/abas.

## Pré-requisitos da rodada

Corrigir CI de reprodutibilidade de fixture e concluir reavaliação dos pacotes históricos. Os IDs abaixo são novos escopos de integração, não substitutos para WPs históricos. Registrar como PENDING somente com dependências existentes e critérios explícitos. Nenhum deles está implementado ou aceito por este documento.

## Fila inicial proposta

### WP-V1-F1-MODEL-REUSE-RPC

- Frente: `f1-core-io`.
- Dependencies: `WP-01-F1-CORE-MODELS`, `WP-AUDIT-FIX-F1-CORE-RPC`.
- Allowed paths: `control_lab/core/`, `control_lab/diagnostics/`, `tests/unit/f1/`.
- Requirements: R-03, R-06, R-27; fases 1/4; T-CORE-01 e regressões T-CORE-02/T-CORE-03.
- Entrega: operação RPC explicitamente versionada para obter modelo canônico reutilizável de IdentifiedModel e conversão TF→StateSpace usando API científica existente. Retornar Result com dt, dimensões, referência/proveniência e política de nova identidade/revisão. Não converter silenciosamente domínio ou atrasos. F9 aprova qualquer alteração de contrato antes do consumo.
- Aceite: exemplos ARX SISO com atraso e subespaços, preservação da resposta e dt, entradas inválidas e obsolescência; equivalência analítica independente. Evitar comparação de matrizes de realizações diferentes como critério de equivalência.
- Acceptance cmd existente: `pytest tests/unit/f1/ -v`. Acrescentar testes específicos a essa suíte; o comando atual sozinho não demonstra a entrega futura.

### WP-V1-F8-TYPED-WORKSPACE-INPUTS

- Frente: `f8-ui-charts`.
- Dependencies: `WP-06-F8-UI-MVP-LQR`, `WP-V1-F1-MODEL-REUSE-RPC`.
- Allowed paths: `web/app/`, `web/features/`, `tests/unit/f8/`.
- Requirements: R-03, R-06, R-26, R-27; fases 1/4; T-CORE-01/T-RPC-01.
- Entrega: seleção explícita de objetos tipados na sessão e composição de payload por ferramenta, substituindo a injeção indiscriminada do StateSpace LQR. Validar dataset/model/system e referência/revisão; impedir execução sem insumos compatíveis. Usar APIs de registro F7 existentes. Mantém escopo de persistência atual até pacote específico de persistência multidomínio.
- Aceite: cada ferramenta recebe apenas referências do tipo correto, erros visíveis para ausência/dimensão incompatível, seleção por teclado, nenhuma revisão antiga sobrescreve seleção atual. Cards não implementadas devem permanecer honestamente indisponíveis.
- Acceptance cmd existente: `npm --prefix web run typecheck && node scripts/run_web_tests.mjs --scope f8`. Acrescentar testes unitários de composição e seleção.

### WP-V1-F8-IDENTIFICATION-VERTICAL

- Frente: `f8-ui-charts`.
- Dependencies: `WP-V1-F8-TYPED-WORKSPACE-INPUTS`, `WP-08-F4-IDENTIFICATION`.
- Allowed paths: `web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`.
- Requirements: R-06, R-18, R-26, R-27; fase 4; T-ID-01/T-ID-02/T-ID-03.
- Entrega: importar/selecionar dataset numérico passivo com dt/unidades e partição treino/holdout explícita; ARX e método de subespaços já disponível; resultados y medido/predito/simulado e resíduos, FIT distinguindo previsão e simulação, avisos de PE/condicionamento; ação de reutilizar modelo em LQR e SISO sem cópia manual.
- Aceite: exemplo determinístico com coeficientes plantados e holdout não usado no ajuste; dataset constante sinalizado; ARX com atraso e subespaços reutilizados com dt/proveniência conservados. Nenhuma estabilidade/qualidade inferida só pelo FIT. Backend F4 permanece intacto; defeito científico descoberto gera pacote F4 próprio.
- Acceptance cmd existente: `npm --prefix web run typecheck && node scripts/run_web_tests.mjs --scope f8`. Os novos testes unitários devem cobrir o fluxo e suas falhas.

### WP-V1-F8-SISO-VERTICAL

- Frente: `f8-ui-charts`.
- Dependencies: `WP-V1-F8-TYPED-WORKSPACE-INPUTS`, `WP-07-F3-FREQ-SISO-MIMO`.
- Allowed paths: `web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`.
- Requirements: R-07, R-18, R-26, R-27; fase 3; T-FREQ-01/T-FREQ-02/T-UI-01.
- Entrega: Bode/Nyquist/margens/root locus e edição de compensador usando APIs existentes, plots e tabelas acessíveis em vez de apenas JSON; overlays rotulados exato/heurístico; preview transitório e commit autoritativo; atraso/Padé apenas por escolha explícita.
- Aceite: primeira ordem analítica e múltiplas travessias; rejeição de canal não SISO ou seleção explícita; controlador/ganho e sinal preservados; report/proveniência e resultados comitados consistentes. O catálogo atual anuncia margens, mas a operação selecionada eval_response não deve ser tomada como prova de que margens já foram calculadas.
- Acceptance cmd existente: `npm --prefix web run typecheck && node scripts/run_web_tests.mjs --scope f8`; adicionar testes para os novos modelos de gráfico/estado.

### WP-V1-F9-ID-SISO-BROWSER-AUDIT

- Frente: `f9-integration-qa`.
- Dependencies: `WP-V1-F8-IDENTIFICATION-VERTICAL`, `WP-V1-F8-SISO-VERTICAL`.
- Allowed paths: `tests/e2e/`, `tests/wasm/`, `tests/oracles/`, `tests/integration/`, `scripts/`, `docs/audits/`.
- Requirements: R-02, R-06, R-07, R-23, R-26; T-ID-01..03, T-FREQ-01..02, T-RPC-01..02, T-UI-01, T-SEC-01.
- Entrega: testes DOM reais de dataset→ARX/subespaços→LQR/SISO, curvas e resíduos, preview/commit, teclado/mobile, erros, referências/revisões e execução offline; CPython/Pyodide comparados ao oráculo independente. Rodar Chromium e Firefox disponíveis sobre o mesmo build e preservar evidência por navegador.
- Acceptance cmds existentes: `npm --prefix web run build && pytest tests/wasm/ tests/e2e/ -v`, repetindo `CONTROLLAB_BROWSER=firefox pytest tests/wasm/ tests/e2e/ -v`; `python3 scripts/project_governance.py`.
- Acrescentar novos arquivos E2E dentro dessas suítes. Os testes existentes não cobrem automaticamente as novas verticais. Não alterar ouro/tolerâncias. Parecer independente por pacote produtor com os dez itens do Apêndice E.

## Próximos recortes após essa rodada

1. Fase 1: persistência multidomínio completa (F1 contrato/ZIP, F7 IndexedDB/restauração, F8 UI, F9 revisão de schema/migração). Só propor mudança de schema após inventário do envelope atualmente suportado; não incluir genericamente no aceite LQR atual.
2. Fase 2: UI de observadores/Kalman/LQG, covariâncias e domínio explícitos, curvas de estimação e controle; reutilizar `statespace.design_*` já existentes e auditar interconexão dinâmica.
3. Fase 5: import/export FML passivo, inferência e superfícies com objeto FuzzySystem real; MIMO RGA/sensibilidade com inputs/saídas e singularidade; TS/premissas semanticamente tipados. Pacotes separados por vertical, com frontend F8 e correção backend somente na frente proprietária se houver evidência.
4. Fase 6: UX de modelagem/templates LMI e diagnóstico espectral/certificado por cinco dimensões; expandir o fluxo além do solver/exportadores já homologados, sem duplicar ADR-010.
5. Fase 7 e release: inventário de Definition of Done por algoritmo e níveis de maturidade, benchmarks por hardware (DEC-OPEN-03), offline/atualização e licenças. Definir WPs executáveis após esse inventário. Nenhum recurso vira Estável somente por haver gate Fase 0 aprovado.

## Limites desta proposta

Nenhum teste foi executado para validar funcionalidades futuras. Não há promoção de status, criação de baseline numérica ou alteração do escopo da release. Comandos listados existem no repositório; testes adicionais exigidos ainda devem ser escritos pelas frentes. F9 mantém independência e pode devolver changes_requested quando a evidência não cobrir o domínio anunciado.
