# ADR-009 — Governança de repositório pessoal

Decisão aprovada pelo coordenador do projeto nesta sessão. Estado aceito.

A conta pessoal e seu plano não oferecem proteção de branch/rulesets de servidor para este repositório. AUD-018 passa a restrição externa aceita. A governança adotada exige validação de PROJECT_STATE.json por scripts/project_governance.py, bloqueio de release por scripts/ci_gate.py, auditoria F9 e dossiês dos dez itens do Apêndice E antes do aceite. O gate de release continua exigindo todos os gates científicos aprovados. A evidência histórica protected=false permanece preservada.

O controle em arquivos/CI depende da execução desses controles e dos responsáveis com permissão de escrita. Um proprietário pode contornar o fluxo no GitHub. Essa limitação foi aceita explicitamente pelo coordenador. As regras em arquivos não são evidência de proteção do servidor.

Esta decisão substitui a exigência de proteção do servidor de AUD-018 e do WP-AUDIT2-FIX-F9-PROTECTION. Ela não aprova os demais gates de produto.
