# Reavaliação F9 — WP-09-F5-FUZZY-FML-ANFIS

## 1. Cabeçalho da tarefa

- Fonte normativa CL-DIR-001 v1.0.0, Apêndices C/E e ADR-009/010.
- Data UTC 2026-11-17; revisor independente `/root/f9_baseline_reassessment`, sem autoria dos módulos auditados.
- Requisitos R-05, R-10; frente produtora `f5-fuzzy-ts`.
- Escopo original `Implementar inferência Mamdani/TS, parser/exportador IEEE 1855-2016 FML (anti-XXE), ANFIS e especificações PDC`.
- Caminhos originais `control_lab/fuzzy/`, `tests/unit/f5/`; esta reavaliação escreve somente documentos/logs F9, sem alteração funcional ou de PROJECT_STATE.
- Dependências WP-01-F1-CORE-MODELS. O Maestro deve aplicar os novos aceites na ordem das dependências.
- Contratos/entradas/saídas Mamdani/TS, perfil IEEE1855-2016 FML, ANFIS e especificações PDC.
- Hipótese e confronto independente T-FML-01/02 e T-TS-01;19 sondas independentes confrontam y=x/y=2x, XML malicioso e perfis/coeficientes inválidos.
- Domínio de aceite CPython local e perfil FML explicitamente suportado. Não é homologação IEEE1855 completa nem aceite de vertical fuzzy browser.
- Risco de confusão entre aceitação de backend/baseline e homologação global mitigado por escopo explícito. A release permanece beta.

## 2. Evidências executadas e consumidas

Comando original `pytest tests/unit/f5/ -v` executado nesta reavaliação pelo entrypoint equivalente `python3 -m pytest` com ambiente abaixo quando Python. Resultado 56 testes fuzzy/FML, zero falhas/skips. As suítes Python de aceite foram agrupadas em uma execução de120 casos e a suíte web comum executada uma única vez, sem dupla contagem F7/F8.

- [Aceites Python](../reassessment/acceptance-python.log) —120 passed,3.03s.
- [Aceite web](../reassessment/acceptance-web.log) —53 passed, typecheck real aprovado.
- [Sondas independentes e governança Python](../reassessment/independent-python.log) —48 passed,2.43s.
- [Sondas independentes Node](../reassessment/independent-node.log) —21 passed,2.69s.
- [Relatório dos gates](../RELATORIO_STATUS_GATES_FASE0.md), [revisão independente dos navegadores](../gatecd/REVIEWER_FINDINGS.md) e logs referenciados — evidências previamente executadas, inspecionadas nesta rodada; não se atribui uma nova execução browser a esta reavaliação.
- [Inventário de integridade](../reassessment/protected-sha256.json). `scripts/verify_fixtures.py` aprovou11 schemas,7 fixtures e4 exemplos. `git diff -- contracts/fixtures/` vazio.

Ambiente efetivamente executado Python3.12.14, NumPy2.3.5, SciPy1.17.0, pytest9.2.0, CVXPY1.9.3 e Clarabel0.11.1; Node24.22.1. Dependências previamente provisionadas via `PYTHONPATH=/workspace/scratch/ba21e63c86f4/testdeps`. Aviso externo AnyIO/pytest10 de depreciação não impediu execução. Nenhuma alteração de lockfile.

## 3. Checklist de Handoff — Apêndice E

| Item | Questão | Resposta | Evidência | Auditoria F9 |
| --- | --- | --- | --- | --- |
| 1 | Contrato aprovado e consumidores? | SIM | Mamdani/TS, perfil IEEE1855-2016 FML, ANFIS e especificações PDC; schemas e testes consumidores aprovados nos logs vinculados. | CONFORME |
| 2 | Status, diagnóstico e proveniência? | SIM | Contratos Result e falhas tipadas nos aceites; sem retorno parcial válido em casos inválidos. | CONFORME |
| 3 | Referência analítica antes de otimização? | SIM | Testes analíticos normativos preexistentes preservados; esta rodada não introduz otimização. | CONFORME |
| 4 | Confronto independente? | SIM | T-FML-01/02 e T-TS-01;19 sondas independentes confrontam y=x/y=2x, XML malicioso e perfis/coeficientes inválidos. | CONFORME |
| 5 | Ownership e expected preservados? | SIM | Esta entrega muda apenas docs F9; inventário SHA e diff vazio de fixtures. Nenhum valor ouro ou tolerância científica modificado. | CONFORME |
| 6 | CPython/Pyodide no domínio anunciado? | SIM/ESCOPO | CPython local e perfil FML explicitamente suportado. Não é homologação IEEE1855 completa nem aceite de vertical fuzzy browser. Evidência Pyodide dos gates consumida nos casos aplicáveis; teste local não é apresentado como execução Wasm nova. | CONFORME |
| 7 | Schema, migração e revisão? | N/A | Nenhum schema/API foi alterado por esta reavaliação; contratos versionados existentes validados. | N/A |
| 8 | Logs, matrizes e benchmark? | SIM | Logs desta rodada e matrizes congeladas vinculados; provas browser e benchmark dos gates permanecem nos dossiês originais, com hardware container DEC-OPEN-03. | CONFORME |
| 9 | Maturidade experimental preservada? | SIM | CPython local e perfil FML explicitamente suportado. Não é homologação IEEE1855 completa nem aceite de vertical fuzzy browser. Nenhuma promoção global de release/métodos. | CONFORME |
| 10 | Limitações e acompanhamento? | SIM | DTD/XXE, operadores e shapes desconhecidos são rejeitados; PDC exige premissa mensurável. Validação vertical Wasm completa ficará em novo WP. Falha CI geral rastreada em WP-CI-F9-FIXTURE-PORTABILITY e não omitida desta revisão. | CONFORME |

## 4. Limites e história

DTD/XXE, operadores e shapes desconhecidos são rejeitados; PDC exige premissa mensurável. Validação vertical Wasm completa ficará em novo WP.

Os pareceres originais e de auditorias externas permanecem imutáveis. Os remediações aceitas foram confrontadas com os aceites originais e não utilizadas isoladamente como substituto de execução. Aprovação deste escopo não anuncia toda vertical científica como pronta nem supera o gate CI vigente.

## 5. Parecer F9

- Revisor independente: `/root/f9_baseline_reassessment`
- Data (UTC): 2026-11-17

- Veredito F9: accepted
- Commit SHA auditado: `9161586a554debd144c6861464e7b8f6f4534953`.
- Escopo: CPython local e perfil FML explicitamente suportado. Não é homologação IEEE1855 completa nem aceite de vertical fuzzy browser.
