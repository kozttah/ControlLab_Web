# AGENTS.md — Orquestrador Geral e Governança Multiagente (CL-DIR-001 v1.0.0)

## 1. Fonte Normativa Única
Toda implementação, contrato, estrutura de dados, teste e gate DEVE obedecer estritamente ao documento `@ControlLab_Web_Documento_Diretor_v1.0.md` (também espelhado em `@docs/ControlLab_Web_Documento_Diretor_v1.0.md`).

## 2. Arquitetura Operacional: 8 Frentes Produtoras (F1–F8) + 1 Frente Independente (F9)
Este repositório opera sob isolamento estrito de propriedade (Seção 13.1 e 13.2):
- **F1 (`f1-core-io`)**: `control_lab/core/`, `control_lab/diagnostics/`, `control_lab/io/`, `tests/unit/f1/` (propõe schemas em `contracts/`).
- **F2 (`f2-statespace`)**: `control_lab/statespace/`, `tests/unit/f2/`.
- **F3 (`f3-frequency`)**: `control_lab/frequency/siso/`, `control_lab/frequency/mimo/`, `tests/unit/f3/`.
- **F4 (`f4-identification`)**: `control_lab/identification/`, `tests/unit/f4/`.
- **F5 (`f5-fuzzy-ts`)**: `control_lab/fuzzy/`, `tests/unit/f5/`.
- **F6 (`f6-optimization-lmi`)**: `control_lab/optimization/`, `control_lab/experimental/sdp_educational/`, `tests/unit/f6/`.
- **F7 (`f7-worker-bridge`)**: `web/bridge/`, `web/worker/`, `web/storage/`, `tests/unit/f7/`.
- **F8 (`f8-ui-charts`)**: `web/features/`, `web/charts/`, `web/app/`, `tests/unit/f8/`.
- **F9 (`f9-integration-qa`)**: `contracts/` (aprovação final), `pyproject.toml`, `tests/oracles/`, `tests/metamorphic/`, `tests/wasm/`, `tests/e2e/`, `tests/performance/`, `tests/security/`, `.github/workflows/`, `scripts/`.

### Regras Inegociáveis de Ownership e Não-Circularidade (Seção 13.11 e Apêndice E)
1. Nenhum agente produtor (`F1`–`F8`) pode alterar `contracts/fixtures/` ou tolerâncias de `tests/oracles/` para forçar um teste a passar.
2. A `F9` NUNCA gera *expected values* de fixtures ouro executando diretamente o código sob teste sem validação analítica ou oráculo independente, e NUNCA conserta silenciosamente funções científicas de `F1`–`F8`.
3. Toda entrega de um WorkPackage de `F1`–`F8` passa pelo checklist de handoff de 10 itens do Apêndice E e recebe parecer da `F9` (`accepted`, `changes_requested`, `blocked_by_gate` ou `rejected_with_evidence`).

## 3. Protocolo de Execução e Governança de Créditos (Stateless Cloud Loop)
A cada execução na nuvem, siga estritamente estes passos:
1. Execute `python3 scripts/budget_governor.py --check`. Se o código de saída for `2` (orçamento diário atingido), encerre imediatamente a execução sem gastar tokens adicionais.
2. Leia `@PROJECT_STATE.json` e selecione o primeiro `WorkPackage` com `"status": "PENDING"` cujas `"dependencies"` estejam `"ACCEPTED_BY_F9"`.
3. Invoque o subagente correspondente à frente (`f1-core-io` a `f9-integration-qa` em `.agents/agents/`) via `invoke_subagent` (ou execute no contexto isolado daquela frente) restrito exclusivamente a `allowed_paths`.
4. Execute os comandos de verificação em `acceptance_cmd`.
5. Se a tarefa for de uma frente produtora (`F1`–`F8`), acione em seguida o subagente `f9-integration-qa` para auditar o checklist do Apêndice E e validar contra os testes normativos (`T-*` do Apêndice C).
6. Se aprovado (`ACCEPTED_BY_F9`), atualize `@PROJECT_STATE.json`, execute `python3 scripts/budget_governor.py --record-task` e faça commit/push atômico (`git add -A && git commit -m "feat(<front>): conclui <wp_id> [auditado F9]" && git push`).
7. Se um teste falhar após 3 tentativas, marque `"status": "BLOCKED_NEEDS_ARGON"` em `@PROJECT_STATE.json`, faça commit do diagnóstico e pare para não desperdiçar créditos em loop.
8. Repita o loop a partir do Passo 1 enquanto `python3 scripts/budget_governor.py --check` retornar código `0`.
