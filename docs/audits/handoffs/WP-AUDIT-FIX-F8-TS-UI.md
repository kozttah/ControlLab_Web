# Dossiê de Handoff e Auditoria F9 — `WP-AUDIT-FIX-F8-TS-UI`

## 1. Cabeçalho da Tarefa (Apêndice E)

| Campo obrigatório | Valor / referência |
| :--- | :--- |
| WorkPackage ID | WP-AUDIT-FIX-F8-TS-UI |
| Requisitos / achados | R-01, R-16, R-17, R-18, R-22, R-24, R-26, R-27; REM-08/AUD-014 e vínculos no PROJECT_STATE |
| Frente / ownership produtor | F8: `web/features/`, `web/charts/`, `web/app/`, `tests/unit/f8/` |
| Ownership auditor | F9: `tests/oracles/`, `docs/audits/`, `docs/architecture/`; nenhuma correção em F7/F8 pelo auditor |
| Contratos consumidos | RPC v1.0 F1/F9, Result, ControlLabEngineClient F7, ToolDescriptor, schemas em contracts/schemas |
| Entradas / saídas | pointer/teclado/edição → preview efêmero → RPC completo → validação estrutural → commitProject atômico → snapshot/export guardado |
| Hipótese matemática | A UI consome resultado autoritativo e não sintetiza CARE/DARE; fixture B-CARE-02 analítica e B-CARE-12x3 certificada fornecem valores de teste |
| Limite da implementação | UI/DOM em Node, F7 real com IndexedDB em memória e respostas científicas controladas; regressão científica CPython separada. Sem prova navegador/Pyodide/Wasm/offline/60 FPS |
| Testes de aceite | `npm --prefix web run typecheck && npm --prefix web test`; T-UI-01 parcial local; probes F9 e regressões abaixo |
| Fixtures | B-CARE-02, B-CARE-12x3, B-SDP-A-D; referências e tolerâncias preservadas |
| Dependências | WP-AUDIT-FIX-F9-GOV e WP-AUDIT-FIX-F7-RPC-BRIDGE aceitas na base |
| Bloqueadores de release | WP-AUDIT-FIX-F9-BUILD-CI, WP-AUDIT-FIX-F7-OFFLINE-SW, WP-AUDIT-FIX-F9-WASM-GATES e G-0A/G-0B/G-0C/G-0D; exportação PathView depende de aceite externo |
| Evidência / SHA | HEAD local `f3049cf7c08786541d888489d69e35693d3b1bfa` mais patch identificado por SHA256 na seção 4; main recebida `946b002cfa7f340431cb3fef292f3701c36a958c`, árvore `ef4a948708529e5fd5c8320ec29b528d76ba0102`; sem commit/publicação pelo auditor |
| Risco / maturidade | Médio, mitigado por fail-closed e isolamento do preview; beta/experimental/unavailable_wasm; nenhuma promoção stable Web |

## 2. Entregáveis Produzidos

F8 impede operações não listadas e exige backend explicitamente disponível. Catálogo deixa de anunciar stable Web. Bootstrap usa URLs relativas à raiz publicada e compatíveis com prefixo GitHub: `app/main.js`, `app/styles.css`, `worker/pyodide_worker.js`, `service_worker.js`, `pyodide/`, `wheels/`. O build físico é obrigação do próximo ciclo F9.

O fluxo LQR usa `execute(commitOnSuccess:false)`, rejeita failure/inconclusive e respostas incompletas/divergentes antes da persistência e só chama `commitProject` após validação. K pode ser inline ou resolvido por referência F7; P opcional é validada quando presente. Planta e resposta são persistidas na mesma transação. Mock 12×3 bruto com referência não resolvível é recusado, com teste negativo explícito; doubles completos para sucesso usam os valores congelados da fixture e identificação honesta.

A F9 executou sondas próprias com o coordenador F7 e IndexedDBProjectStore reais sobre InMemoryIDBFactory. Trinta pointermoves não fazem RPC nem persistem; pending/failure/inconclusive/success inválido não geram projects, objects, snapshots, experiments nem committed_result exportável; success válido persiste e libera exportação. Isso demonstra a proteção F8 sem mascarar o comportamento genérico F7 fora deste escopo.

Histórico de bloqueio: a rodada anterior encerrou após três tentativas, com 43/44 e falso positivo lexical para URL wheel. Dossiê anterior e log registraram BLOCKED_NEEDS_ARGON/changes_requested e pedido de autorização. O usuário autorizou expressamente retomar sem limite de três tentativas e dispensou orçamento para concluir F8 e o terceiro ciclo; AGENTS e política não foram alterados. Após IMPLEMENTATION_READY o produtor congelou código, permitindo a presente auditoria. O log mantém integralmente a transcrição histórica parcial e acrescenta as execuções integrais atuais. O histórico do dossiê permanece no Git.

## 3. Checklist de Handoff de 10 Itens

| # | Pergunta normativa | Resposta produtor / escopo | Evidência objetiva | Auditoria F9 |
| :--- | :--- | :--- | :--- | :--- |
| **1** | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | SIM, escopo local | typecheck; 46 testes F7/F8; probe storage usa cliente e store F7 reais; 10 schemas validados | CONFORME |
| **2** | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | SIM | failure/inconclusive rejeitados; respostas controladas rotuladas; dois probes CPython validam schema/envelope | CONFORME |
| **3** | Testes analíticos foram escritos antes da otimização prematura? | SIM para referências; sem síntese UI | B-CARE-02 analítica já congelada e íntegra; sem nova otimização científica | CONFORME |
| **4** | Existe confronto independente da implementação, em vez de autorreferência? | SIM | 11 sondas UI F9, duas bridge/CPython; expectativas de persistência derivadas da norma e ganhos de fixture ouro | CONFORME |
| **5** | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | SIM | seis arquivos F8, teste F9 novo, docs F9; baseline 31/31 preservado incluindo contratos/oráculos aceitos/F7; doubles explicitamente completos e teste negativo do mock bruto | CONFORME |
| **6** | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | N/A para paridade nesta entrega local | Não se anuncia domínio Pyodide/Wasm aceito; regressão CPython passou; comprovação Web pertence a BUILD-CI/WASM-GATES | N/A |
| **7** | Alterações de schema tiveram migração/versão e revisão F9? | N/A, sem alteração de schema | 18 arquivos contracts preservados por SHA256; verificador de schemas/fixtures passou | N/A |
| **8** | Logs, matrizes de fixture e resultados de benchmark foram anexados? | SIM para evidência aplicável; benchmark N/A local | Log integral atual, SHA256 de baseline e patch; fixtures certificadas; nenhuma medição de FPS/offline alegada | CONFORME |
| **9** | Um método experimental permanece visualmente classificado como tal? | SIM | Catálogo sem stable; mock identificado como fixtures beta e Web/gates/offline como não verificados; sondas e testes de maturidade | CONFORME |
| **10** | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | SIM, rastreio local F8-LIM-01..04 abaixo | WPs de release abertos, indisponibilidade/backend e export guard com mensagens; log e testes negativos | CONFORME |

## 4. Registro de Ambiente, SHA e Saída de Execução

Ambiente efetivamente usado: Linux x86_64 glibc 2.41; Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0, pytest 9.2.0, jsonschema 4.26.0, Clarabel 0.11.1, CVXPY 1.9.3; Node v24.22.1, TypeScript 5.8.3. PATH e PYTHONPATH usam `testdeps` e `toolchain` sob `/workspace/scratch/ba21e63c86f4`. Navegador/Playwright/Pyodide/PathView não executados. A primeira sondagem metadata no processo controlador não carregava PYTHONPATH; suas ausências registradas no log são corrigidas por consulta posterior no ambiente dos comandos.

[Log integral e histórico](../../architecture/audit-logs/WP-AUDIT-FIX-F8-TS-UI.log). Resultado independente: acceptance 46/46, 0 fail/skip; Node F9 13/13 (11 UI e 2 CPython), 0 fail/skip; schemas/fixtures verificados; pytest oráculos + governança 45/45, um aviso de depreciação anyio/pytest; diff --check aprovado. Todos retornaram exit 0.

Arquivos auditados e SHA256 do patch congelado:

```text
664ea05b351010be39c28de814b23d8671dc642b96778926c4a5227cbdad7f5b  tests/unit/f8/ui_mvp_lqr.test.ts
738ec87bb64b4604e9d0e06cbfca699e0992933e2a5af6acdaa8d784c13ab33f  web/app/index.html
b4e2d7ce1bad0d461f70aebf0926d8c718a08b395a6162065d9e18231cb355b7  web/app/main.ts
a57860ebf891e9ee4f3246b17afa3a23e1fe01bd9bb48dbf29e74c004dccd848  web/app/tool_descriptor.ts
b24330a391e6a7f95d523e3626b2eea84473119b87459717d9cb78725d12a2cb  web/features/lqr_workspace.ts
1e77a2a3436b0ad5c27f788a6f4a5f9ca17bfeb626f5ae2372cdd949f83a2ede  web/features/tool_catalog.ts
3544ca23cca9e588c55343984aa943f647deeb7cca8c1a0ce2dca2699f9b4031  tests/oracles/ui_remediation_independent.test.mjs
```

O log inclui SHA/status do checkout e hashes individuais dos 31 arquivos baseline preservados. Esse conjunto identifica o código auditado antes do commit de fechamento do Maestro.

Registro local de limitações:

- **F8-LIM-01**: assets distribuíveis ainda dependem de WP-AUDIT-FIX-F9-BUILD-CI; contrato de URLs testado, existência do pacote final não atestada.
- **F8-LIM-02**: Wasm, navegador real, cache offline, desempenho/FPS e a11y instrumentada dependem de WP-AUDIT-FIX-F9-WASM-GATES; G-0A/G-0C não liberados.
- **F8-LIM-03**: backend SDP depende de G-0B; PathView/exportação externa depende de G-0D, sem aceite implícito neste WP.
- **F8-LIM-04**: F7 genérico ainda pode comitar inconclusive quando execute usa commitOnSuccess true; F8 agora impede esse caminho com false e commit explícito após validação. Não se reabre/edita F7 neste escopo, nem se declara sua semântica genérica corrigida.

## 5. Parecer Independente da Frente F9

- **Veredito F9:** `accepted`
- **Escopo aprovado (`acceptance_scope`):** `node_local_ui_f7_storage_controlled_and_cpython_regression_only`.
- **Revisor independente:** `f9-integration-qa`, agente `f9_resume_audit`, distinto de `f8_resume`.
- **Commit SHA auditado:** `f3049cf7c08786541d888489d69e35693d3b1bfa` mais os sete arquivos de patch assinados por SHA256 na seção 4.
- **Data (UTC):** `2026-11-14`.
- **Validação independente:** acceptance 46/46; F9 Node 13/13; Python oráculos/governança 45/45; hashes, schemas e ownership conformes.
- **Release blockers:** WP-AUDIT-FIX-F9-BUILD-CI, WP-AUDIT-FIX-F7-OFFLINE-SW e WP-AUDIT-FIX-F9-WASM-GATES, G-0A/G-0B/G-0C/G-0D. Aceite restrito à integração local; nenhuma liberação stable Web, Pyodide/offline, 60 FPS ou PathView.
- **Fechamento:** atualização de PROJECT_STATE, orçamento, commit e push reservados ao Maestro; não executados pelo auditor.
