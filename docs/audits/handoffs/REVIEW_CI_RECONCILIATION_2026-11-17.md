# Revisão independente — WP-CI-F9-FIXTURE-PORTABILITY e reconciliação dos sete baselines

Data UTC 2026-11-17. Revisor `/root/f9_independent_review`. Fonte normativa CL-DIR-001, Apêndices C/E, §§10.2/10.4/13.11/15.2, ADR-009/010. Base `9161586a554debd144c6861464e7b8f6f4534953`, acrescida somente do diff do teste de portabilidade, SHA256 `04792e7ca4c523f92f41d44e941e5b2745c967d3299e1d69eacdb35de2f68754`. Revisor não é autor da correção funcional nem da reavaliação original. A normalização documental do handoff CI foi autorizada pelo Maestro depois da revisão técnica.

## Evidência independente executada

1. Leitura integral de AGENTS.md, diretrizes F9, CODEOWNERS, Apêndice E, gerador independente e diff completo do oráculo.
2. `python -m pytest tests/oracles/test_release_fixtures.py -q` no runtime isolado `/workspace/scratch/ba21e63c86f4/f9-ci-sdp/bin/python`: **30 passed em0.85s**, sem skips. Uma execução preliminar anterior teve29 testes antes da inclusão do caso NaN, sem contagem aditiva.
3. `python scripts/verify_fixtures.py`: **11 schemas, sete fixtures SHA256 e quatro exemplos aprovados**.
4. Todos os sete JSON e `checksums.sha256` em `contracts/fixtures/` comparados byte a byte com `git show 9161586:<path>`: idênticos. Ouro, tolerâncias científicas, geradores e fontes científicas não sofreram alterações nesta correção.
5. Os sete handoffs individuais `*-reassessment-2026-11-17.md` e o handoff CI foram validados por `validate_handoff_text(..., require_identity=True)`: identidade, decisão, fonte e tabela de dez itens aprovados.
6. Inspeção dos logs da reavaliação:120 aceites Python,53 web,48 sondas independentes Python e21 Node passaram. Os42 testes suplementares de release/fixtures sobrepõem12 casos bootstrap, portanto não são somados como cobertura distinta. Esses comandos foram executados pelo reavaliador, não atribuídos a nova execução deste revisor.

## Resultado técnico

O teste anterior exigia igualdade exata de saídas LAPACK embora a proveniência congelada já permitisse variação BLAS pelos critérios numéricos. A correção usa uma lista explícita de campos DARE calculados e tolerâncias já existentes, mantendo o restante exatamente igual. A/B discretizadas são resultados de ZOH, enquanto matrizes contínuas, pesos, condição inicial e metadados determinísticos permanecem exatos. Não há aumento dos valores de tolerância.

O certificado regenerado é confrontado novamente com equação DARE, simetria, positividade, estabilidade, fórmula do ganho, polos e custo. Mutações fora do domínio aceito, NaN, metadados, formas e tolerâncias adulteradas falham. A integridade SHA permanece separada e rejeita até espaço adicional sem mudança de valor numérico. Nenhum resultado foi regenerado a partir de control_lab. Os demais geradores continuam sob igualdade exata nesta correção focalizada.

Concordo com os sete pareceres de reavaliação no domínio anunciado, em ordem de dependências. Os aceites originais foram novamente executados e apoiados por sondas independentes, não inferidos apenas dos remediation_wps. WP09 é CPython/perfil FML suportado; WP10 permanece experimental local. Os gates browser são evidências anteriores inspecionadas, sem alegação de nova execução nesta rodada.

## Checklist de Handoff — Apêndice E

| Item | Questão | Resposta | Evidência | Auditoria F9 |
| --- | --- | --- | --- | --- |
| 1 | Contratos e consumidores | SIM | API e schemas sem mudança; sete handoffs validados, aceites originais e sondas consumidores aprovados. | CONFORME |
| 2 | Status/diagnósticos/proveniência | SIM | Nenhuma implementação Result modificada; teste preserva metadados e rejeita certificados/campos inválidos. | CONFORME |
| 3 | Referência analítica | SIM | Gerador independente e reconstrução equação DARE; testes analíticos preservados. | CONFORME |
| 4 | Independência | SIM | Revisor sem autoria da correção; execução independente30testes; SHA separado da comparação numérica. | CONFORME |
| 5 | Ownership e ouro | SIM | Apenas teste F9 e governança/docs; sete fixtures e manifesto byte a byte intactos, tolerâncias não relaxadas. | CONFORME |
| 6 | CPython/Pyodide | ESCOPO | Teste offline CPython corrigido; fontes científicas/wheel sem alteração; evidência Pyodide anterior corretamente identificada. | CONFORME |
| 7 | Schema/migração | N/A | Nenhuma mudança de contrato/schema/API. | N/A |
| 8 | Logs/matrizes/benchmarks | SIM | Contagens e comandos independentes acima, logs de reavaliação vinculados; matrizes congeladas preservadas. | CONFORME |
| 9 | Experimental | SIM | WP10 permanece experimental e WP09 não vira vertical browser estável; release continua beta. | CONFORME |
| 10 | Limitações | SIM | GitHubActions da nova publicação deve confirmar portabilidade; tentativa browser atual bloqueada por ambiente não é convertida em aprovação nova. | CONFORME |

## 5. Parecer F9

- Revisor independente: `/root/f9_independent_review`.
- Commit SHA auditado: `9161586a554debd144c6861464e7b8f6f4534953` mais diff do oráculo identificado acima.
- Data (UTC): 2026-11-17.
- Veredito F9: accepted
- Escopo: correção local de portabilidade DARE e concordância com os pareceres individuais de reavaliação histórica, sem homologação global de release estável.

O estado final PROJECT_STATE deve conservar os pareceres anteriores, aplicar aceites com dependências satisfeitas e referenciar os handoffs individuais. A fila nova representa planejamento PENDING, não funcionalidades entregues. O Maestro deve validar PROJECT_STATE final e concluir os perfis CI locais antes de publicação. A execução hospedada anterior com uma falha continua sendo fato histórico até nova execução publicada. Nenhuma alegação de CI hospedado verde é emitida por este documento.

## Revisão do estado final e próxima fila

O revisor executou novamente `python scripts/project_governance.py` após a edição de PROJECT_STATE:39 pacotes,34 aceitos,18 corretivos, governança aprovada. A contagem direta confirmou34 ACCEPTED_BY_F9 e5 PENDING. Os sete registros antigos foram comparados à base9161586 e estão integralmente preservados no último elemento de previous_assessments, desconsiderando apenas a lista vazia auxiliar adicionada. Todos os aceites usam handoffs individuais e dependências satisfeitas. O próximo selecionado automaticamente é `WP-V1-F1-MODEL-REUSE-RPC`.

Os cinco pacotes futuros mantêm estado PENDING, ownership e dependências coerentes, critérios específicos e exigência explícita de novos testes. A proposta resulta de inspeção de lacunas da UI/RPC e não duplica os backends científicos já implementados. A execução das suítes atuais sozinha não poderá comprovar essas entregas futuras.

Foram inspecionados os artefatos novos dos perfis CI locais com locks congelados: `reassessment/core/B-core_no_sdp.json` informa298 testes,0skips,returncode0; `reassessment/sdp/B-sdp_available.json` informa147testes,0skips,returncode0. A separação opcional CVXPY/Clarabel está correta em cada perfil. Resultados locais não garantem ainda a execução hospedada.

O Maestro comunicou nova sonda G-0B Firefox aprovada e execução global Firefox em andamento. A falha EPERM ao iniciar Chromium nesta sessão é ambiental e exclusiva dessa nova tentativa; as provas anteriores dos gates continuam identificadas como históricas. A nova sonda Firefox isolada não é apresentada como execução integral dos browsers por este revisor. Resultado global e logs finais deverão constar do relatório do Maestro antes de publicar.
