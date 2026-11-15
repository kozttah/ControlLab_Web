# Parecer F9 — bloqueio do WP-AUDIT2-FIX-F9-PROTECTION

Data: 2026-11-15. Base conferida: f9277ce68cbd2f2f428c422e6da6eafc54f0a1cd.
Veredito F9: blocked_by_gate. Achado AUD-018 permanece aberto.

## Causa e correção da fila

AGENTS.md seleciona pelo status PENDING e pelas dependências aceitas. Cadastrar proteção de servidor como PENDING, mesmo com external_blockers, fez outro agente selecioná-la legitimamente e encerrar a rodada sem implementação possível. O erro estava no registro da fila. O helper que ignorava external_blockers não tornava a regra textual dos outros agentes equivalente.

O status passa para BLOCKED_BY_GATE, com f9_review=blocked_by_gate, mantendo dependências, evidências e requisitos originais. Esse pacote não bloqueia o aceite local dos pacotes F1/F8; continua bloqueando a liberação estável pelo registro release_governance. Nada foi aceito nem foi promovido a pass.

## Aceitação ainda indisponível

O arquivo tests/security/test_repository_protection.py indicado no acceptance_cmd ainda não foi implementado. O cadastro anterior descrevia uma entrega futura; não constitui teste executável atual. Isso agora aparece explicitamente em acceptance_test_status=NOT_IMPLEMENTED e resume_conditions. Nenhuma suíte de proteção foi declarada executada.

A evidência anterior registrava protected=false. A conexão GitHub disponível não possui administração e não basta para comprovar regras atuais ou enforcement. Nenhuma configuração de servidor, plano, visibilidade ou permissão foi alterada. A retomada exige implementação do teste e evidência autorizada de proteção/checks/revisão e dos ensaios exigidos, seguida de reavaliação F9.

## Regressão e próximo pacote

O validador rejeita qualquer novo registro PENDING com external_blockers. A regressão test_external_blockage_cannot_be_pending_in_standard_agent_queue reproduz a seleção mínima de AGENTS.md, sem depender de um seletor especial, e a confronta com o helper.

Na fila real corrigida, essa mesma regra seleciona WP-AUDIT2-FIX-F1-OPTIONAL-SDP-TEST. Os demais pacotes e gates preservam seus estados. A correção é administrativa F9, sem consumo de outro WorkPackage, sem alterações científicas, fixtures ou tolerâncias. Publicação direta em main, sem nova branch.

## Verificação desta correção

Vinte testes focados de governança aprovados. Perfil core_no_sdp completo: 266 testes aprovados, zero skipped, código de saída 0; lock e fixtures verificados pelo runner scripts/ci_math.py. Ruff F sem erros e git diff --check limpo. A regra literal de seleção escolheu o pacote F1 acima. Esses resultados não são execução do teste de proteção ausente nem prova de enforcement do servidor.
