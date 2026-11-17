# Handoff F9 — WP-AUDIT2-FIX-F9-PROTECTION

## 1. Cabeçalho

Governança de conta pessoal aprovada pelo coordenador em ADR-009.

Escopo Governança em arquivos/CI, com limitação de enforcement de servidor aceita explicitamente.. Fonte CL-DIR-001 com decisões explícitas ADR-009/ADR-010 do coordenador. Execução F6/F8/F9 sequencial no contexto principal por instrução da sessão Codex.

## 2. Contratos e implementação

Aceite por pytest tests/security/test_repository_protection.py -v e scripts/project_governance.py. A liberação global continua condicionada aos gates científicos. Nenhuma alegação de proteção de servidor é introduzida.

## 3. Checklist do Apêndice E

| Item | Evidência |
| --- | --- |
| 1 | Contratos de governança validados por scripts/project_governance.py. |
| 2 | Status e restrição externa constam de release_governance e accepted_external_constraints. |
| 3 | Testes de rejeição de estados inválidos em tests/security/test_repository_protection.py. |
| 4 | F9 verifica os registros sem depender da alegação de proteção remota. |
| 5 | Controle local/CI não altera fixtures ou tolerâncias científicas. |
| 6 | N/A. Decisão de governança não depende de runtime numérico. |
| 7 | Campos aditivos com preservação do bloqueio histórico e decisão ADR-009. |
| 8 | Evidência em ADR-009 e logs da suíte ADR-009/010. |
| 9 | N/A. Sem promoção de método experimental nesta decisão. |
| 10 | A limitação de bypass por proprietário é expressa na ADR-009. |

## 4. Evidências e limites

Governança em arquivos/CI, com limitação de enforcement de servidor aceita explicitamente.

## 5. Parecer F9

- Revisor independente: verificação F9 sequencial no contexto principal, conforme instrução explícita da sessão. A independência numérica reside no verificador espectral separado do solver.
- Commit SHA auditado (base): 3ce128a6d8a18ad1eeb18ee83b666df6708d30d0, acrescido do diff ADR-009/010 desta entrega.
- Data (UTC): 2026-11-17
- Parecer F9: accepted
