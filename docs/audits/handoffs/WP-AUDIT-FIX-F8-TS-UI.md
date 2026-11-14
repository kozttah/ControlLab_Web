# Dossiê de Handoff e Auditoria F9 — `WP-AUDIT-FIX-F8-TS-UI`

## 1. Cabeçalho da Tarefa

- **Fonte normativa:** CL-DIR-001 v1.0.0, §§4.4, 7.1/7.2, 13.10/13.11, Apêndices C/E; AGENTS.md §3.7.
- **Frente:** F8; requisitos R-01, R-16, R-17, R-18, R-22, R-24, R-26, R-27; REM-08/AUD-014 e achados vinculados no PROJECT_STATE.
- **Allowed paths:** `web/features/`, `web/charts/`, `web/app/`, `tests/unit/f8/`.
- **Contratos:** ControlLabEngineClient/F7, ToolDescriptor, RPC v1.0; entradas/saídas UI→RPC→estado apresentado, sem síntese científica na UI.
- **Dependências:** F9-GOV e F7-RPC-BRIDGE aceitas na base.
- **Acceptance:** `npm --prefix web run typecheck && npm --prefix web test`; T-UI-01; regressão `test_tool_descriptor_unlisted_operation_and_typecheck`.
- **Base remota:** `dcd9d27a8dbffa00689d60db65b33d61a04a0948`; árvore `5395cd4d3074f47ba38915d3b849948b3588c221`; HEAD local de trabalho `02b48b648ede066b6f5fbb74944785b0d53f8b3a`.
- **Estado requerido:** `BLOCKED_NEEDS_ARGON`; parecer F9 `changes_requested`.
- **Risco / maturidade:** revisão incompleta, nenhuma aprovação local ou Web; gates permanecem abertos.

## 2. Diagnóstico e destino do trabalho

F8 atingiu três tentativas falhas. AGENTS.md §3.7 determina interromper e registrar bloqueio; não foi realizada quarta tentativa. Na última execução houve typecheck aprovado, **43 testes aprovados e um reprovado**, sem skips. O teste de arquitetura usa `/\bcontrol_lab\b/` para detectar importação Python e acusou a URL legítima `wheels/control_lab-1.0.0-py3-none-any.whl` em `web/app/main.ts`. Essa correspondência lexical, por si só, não comprova importação Python na UI; o teste precisa ser corrigido preservando a intenção arquitetural e depois reexecutado sob autorização adequada. A F9 não fez essa correção nem aprovou o patch.

O Maestro destinou o patch não aceito à branch revisável [`work/wp-audit-fix-f8-ts-ui-blocked-20261114`](https://github.com/kozttah/ControlLab_Web/tree/work/wp-audit-fix-f8-ts-ui-blocked-20261114). A main receberá somente PROJECT_STATE com bloqueio e estes dois artefatos de diagnóstico; código F8 e sondas não aceitas não integram a publicação de diagnóstico. Este dossiê documenta a decisão de preservação; a publicação efetiva é verificada pelo Maestro.

As seis sondas F9 em `tests/oracles/ui_remediation_independent.test.mjs` foram escritas **mas não executadas**: operações não listadas, backend requerido ausente/indisponível, maturidade do catálogo, preview/pending/failure, preview/pending/inconclusive e entrada HTML/CSS. Não são evidência de conformidade. A disponibilidade com `required_backend` ausente continua pendente de auditoria independente. Há indicação para triagem de persistência de resposta `inconclusive` em F7/client, fora do ownership F8; não se registra reprovação científica F7 por execução nesta rodada, nem se reabre seu WP automaticamente.

Das três rodadas solicitadas, o ciclo 1/F5 foi aceito e publicado na base acima; o ciclo 2/F8 está bloqueado; o ciclo 3/F9-BUILD-CI não foi iniciado. O orçamento permanece em 10 tarefas registradas: não há `--record-task` para este bloqueio.

## 3. Checklist de Handoff de 10 Itens (Apêndice E)

| # | Item normativo | Evidência / limite atual | Auditoria F9 |
| :--- | :--- | :--- | :--- |
| **1** | API testada com contrato F1/F9 e fornecida aos consumidores? | Typecheck aprovado na tentativa 3; auditoria independente de contrato não concluída | PENDENTE |
| **2** | Status, diagnósticos e proveniência inclusive em falhas? | Teste do produtor para inconclusive consta aprovado; sonda F9 não executada; indicação F7 para triagem | PENDENTE |
| **3** | Analíticos antes de otimização prematura? | Fixtures existentes usadas pelos unitários; sem aprovação independente do patch | PENDENTE |
| **4** | Confronto independente sem autorreferência? | Seis sondas F9 escritas, nenhuma executada | PENDENTE |
| **5** | Ownership e expected values preservados? | Patch destinado a branch separada; verificação final completa não concluída | PENDENTE |
| **6** | Mesmo teste em CPython e Pyodide no domínio anunciado? | Nenhuma comprovação de browser/Pyodide nesta rodada; sem promoção Web | PENDENTE |
| **7** | Migração/versão/revisão de schemas quando alterados? | Não foi proposta mudança de schema; auditoria final interrompida | PENDENTE |
| **8** | Logs, fixtures e benchmarks anexados? | Transcrição parcial real de três tentativas no log; sem benchmark nem log integral disponível | PARCIAL |
| **9** | Experimental permanece identificado? | Revisão independente dos badges não concluída; sem aprovação de maturidade | PENDENTE |
| **10** | Limitações rastreadas com mensagens adequadas? | Bloqueio, teste lexical e verificações restantes registrados neste dossiê | PENDENTE |

## 4. Ambiente e evidências disponíveis

Execução Linux/Node v24.22.1/TypeScript 5.8.3, conforme ambiente do ciclo. PATH inclui `testdeps/bin` e `toolchain/node_modules/.bin` em `/workspace/scratch/ba21e63c86f4`; PYTHONPATH aponta a `testdeps`. As sessões do produtor foram 54485, 93300 e 83202; última transcrição no chunk `95cd37`. Não havia arquivo de log integral salvo; a [transcrição parcial](../../architecture/audit-logs/WP-AUDIT-FIX-F8-TS-UI.log) identifica explicitamente sua origem e seus limites. A F9 não reexecutou comandos científicos após o STOP.

## 5. Parecer Independente da Frente F9

- **Veredito F9:** `changes_requested`
- **Status correspondente:** `BLOCKED_NEEDS_ARGON`, por AGENTS.md §3.7.
- **Revisor independente:** `f9-integration-qa`, subagente `f9_audit_f6`, distinto do produtor F8.
- **Commit SHA auditado:** base `dcd9d27a8dbffa00689d60db65b33d61a04a0948` mais patch F8 não aprovado; revisão incompleta.
- **Data (UTC):** `2026-11-14`.
- **Próximos requisitos:** decisão do Maestro/usuário sobre nova tentativa; correção estrutural do teste lexical; acceptance 100%; execução das sondas F9 e conclusão do checklist. Nenhum gate ou release Web foi aprovado.
