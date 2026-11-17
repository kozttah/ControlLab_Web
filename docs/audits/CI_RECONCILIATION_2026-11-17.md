# Fechamento CI, reconciliação e próxima fila — 2026-11-17

Base `9161586a554debd144c6861464e7b8f6f4534953`, CL-DIR-001. Maestro com produtor F9, reavaliador F9 e revisor independente distintos. Fontes científicas, schemas, fixtures ouro, geradores e tolerâncias permanecem intactos.

## Correção e auditoria

O Job B/sdp_available remoto da base falhou na igualdade exata de uma fixture DARE regenerada. O teste agora separa integridade dos bytes congelados, metadados determinísticos e verificação numérica dos campos calculados. Usa exclusivamente tolerâncias preexistentes e recalcula certificado, ganho, estabilidade, polos e custo. Mutações de valores, formas, tolerâncias, metadados e bytes são rejeitadas.

Handoff [WP-CI-F9-FIXTURE-PORTABILITY](handoffs/WP-CI-F9-FIXTURE-PORTABILITY.md) e [revisão independente](handoffs/REVIEW_CI_RECONCILIATION_2026-11-17.md).

## Estado e fila

Os sete WPs históricos foram reavaliados contra aceites originais e sondas independentes, com handoffs individuais e histórico preservado em PROJECT_STATE. Não houve aceite inferido somente da conclusão de remediações. [Consolidado](handoffs/REASSESSMENT_BASELINE_2026-11-17.md).

Estado resultante: 39 pacotes, 34 ACCEPTED_BY_F9 e cinco PENDING. Os gates G-0A..D conservam seus pareceres e escopos anteriores. F5 mantém aceite CPython/perfil suportado e o solver educacional permanece experimental local. A versão de produto continua beta.

Cinco novos pacotes têm dependências, ownership, critérios e comandos registrados, conforme [plano detalhado](NEXT_QUEUE_2026-11-17.md). O próximo elegível é WP-V1-F1-MODEL-REUSE-RPC. Os demais tratam entradas tipadas, identificação, SISO e homologação browser independente. Nenhuma funcionalidade futura é apresentada como implementada.

## Validações desta rodada

- CI matemático isolado core_no_sdp: 298 passed, zero skips, lock exato. [JSON](reassessment/core/B-core_no_sdp.json).
- CI matemático isolado sdp_available: 147 passed, zero skips, lock exato. [JSON](reassessment/sdp/B-sdp_available.json).
- npm web: 53 passed e typecheck aprovado. [Log](reassessment/acceptance-web.log).
- Aceites históricos: 120 Python; sondas adicionais: 48 Python e 21 Node. As contagens sobrepõem suítes CI e não devem ser somadas como casos distintos.
- Governança após atualização: 39 pacotes, 34 aceitos. Cinco testes de governança e oito testes Node de integração novamente aprovados.
- Verificação de fixtures: sete hashes, 11 schemas e quatro exemplos aprovados; fixtures e manifesto byte a byte idênticos à base.
- Novo probe Firefox do gate G-0B: um teste aprovado, solver nativo Pyodide e exportadores offline.

## Ambiente e limitações

Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0 e Node 24.22.1. Os dois perfis matemáticos foram executados em ambientes separados com seus locks, sem contaminação por dependências browser. Uma tentativa inicial no ambiente SDP reutilizado foi corretamente recusada pelo verificador do lock devido a três pacotes browser adicionais; o perfil foi repetido em ambiente novo e exato.

Chromium nesta sessão não inicia por `socket() failed: Operation not permitted`, antes da execução de assertions browser. A tentativa completa inicial teve 364 testes aprovados, 23 erros de setup browser e uma falha de inicialização no teste offline. Esse resultado ambiental não é uma homologação completa. Firefox foi iniciado com seu executável provisionado; resultados finais da repetição ampliada são registrados abaixo. Evidências anteriores dos gates e jobs D/E/F/G aprovados na base continuam identificadas como históricas.

Publicação e confirmação da nova execução hospedada devem ser verificadas após o commit. O resultado local não implica CI hospedado verde nem release estável.

## Resultado final da repetição ampliada

`pytest -q` com Firefox 153 terminou com **387 passed e uma falha de inicialização ambiental**, em 469.41s, sem skips. A falha é exclusivamente `test_offline_real_calculation_after_reload`, cujo driver seleciona Chromium explicitamente e não encontra o executável Playwright esperado; selecionar o Chromium do sistema na tentativa anterior falha por socket EPERM. Não houve falha de assertion científica nos testes executados. [Log integral](reassessment/full-firefox.log) e [evidências Firefox](reassessment/firefox/). O build tem o mesmo manifesto SHA256 da auditoria anterior.

O resultado local completo não é declarado 100% aprovado. O teste Chromium offline precisa ser confirmado pelo CI hospedado após publicação. Demais Wasm/E2E, CSP/importações passivas, slider, teclado/mobile e downloads saturado/dinâmico executaram e passaram em Firefox nesta rodada.
