# WP-CI-F9-FIXTURE-PORTABILITY — evidência do produtor F9

Data: 2026-11-17. Base: main `9161586a554debd144c6861464e7b8f6f4534953`.
Norma: CL-DIR-001 §§10.2, 10.4, 13.11, 15.2 e Apêndice E.
Escopo: `tests/oracles/test_release_fixtures.py`; nenhum módulo científico de F1–F8 alterado.
Parecer do produtor: pronto para auditoria independente; não constitui autoaceite F9.

## Problema e hipótese verificada

O job B CPython `sdp_available` da execução GitHub Actions 44072194300 falhou em
`test_generator_independent_and_new_gold_deterministic`, apesar de 130 testes aprovados.
O teste exigia igualdade exata de todo o dicionário da DARE regenerada, incluindo
resultados LAPACK, polos, custo e resíduos. O log mostra diferenças pequenas de
ponto flutuante, por exemplo custo 196.9078978341955 versus 196.90789783418427.
A própria proveniência congelada permite variação de últimos bits BLAS.
Não foi identificada uma biblioteca BLAS específica como causa conclusiva.
No runtime local Python 3.12 / NumPy 2.3.5 / SciPy 1.17.0, os quatro geradores
originalmente coincidem exatamente com as fixtures. A regressão adicionada simula
variação de 1e-14 sem depender de uma máquina específica.

## Correção e independência

Apenas os campos calculados da DARE explicitamente enumerados passam por comparação
numérica usando critérios já congelados: A/B por matrix_atol, P/K pelas tolerâncias
relativas existentes, polos/raio espectral por poles_atol. O custo x0ᵀPx0 herda o
critério relativo de P. Resíduo DARE, simetria e erro de quadratura devem ser finitos,
não negativos e menores que os limites congelados correspondentes.
O certificado é também recalculado independentemente das declarações do gerador:
resíduo DARE, simetria, positividade, ganho recuperado, estabilidade, polos e custo.
Metadados, dimensões, ordem/dtype, tolerâncias, entradas determinísticas e campos
não enumerados continuam sujeitos a igualdade exata. ARX, MIMO e PVM continuam
sob igualdade exata, preservando o escopo focalizado desta correção.

Integridade dos bytes continua independente da regeneração numérica. O verificador
SHA-256 rejeita agora em teste uma fixture com apenas espaço extra (sem alterar seus
valores numéricos). Testes de mutação rejeitam dano A/B/P/K, polos, resíduos, custo,
raio espectral, sinal, shape, NaN e alteração de tolerância. Fixtures, manifesto,
geradores e tolerâncias científicas não foram alterados.

## Validação do produtor

- `python3 -m pytest tests/oracles -q`: 86 passed, zero skips, uma advertência de plugin anyio/pytest9 externo.
- `python3 scripts/verify_fixtures.py`: sete hashes de fixtures, 11 schemas e quatro exemplos aprovados.
- `git diff -- contracts/fixtures`: vazio.
- `git diff --check`: aprovado.
- Runtime pytest instalado para execução local; isso não modifica dependências versionadas.
- A confirmação do CI hospedado exige executar novamente após a publicação; não é inferida do resultado local.

## Checklist de Handoff — 10 itens

| Item | Questão | Resposta | Evidência | Auditoria F9 |
| --- | --- | --- | --- | --- |
| 1 | Contrato e consumidores | SIM | Nenhuma API alterada; 30 testes release independentes e schemas/fixtures validados. | CONFORME |
| 2 | Status, diagnósticos, proveniência | SIM | Result não muda; asserts rejeitam metadados, NaN, certificados e formas inválidas. | CONFORME |
| 3 | Referência analítica | SIM | Gerador independente preexistente, equação DARE e ganho reconstruídos; nenhum algoritmo otimizado. | CONFORME |
| 4 | Confronto independente | SIM | Revisor executou teste final; resíduos, simetria, positividade, estabilidade, ganho, polos e custo recalculados sem solver de produção. | CONFORME |
| 5 | Ownership e ouro | SIM | Somente oráculo/docs F9; sete JSON ouro e checksums byte a byte idênticos à base9161586. Tolerâncias científicas congeladas intactas. | CONFORME |
| 6 | CPython/Pyodide | ESCOPO | Correção de teste de geração offline CPython; runtime Pyodide e wheel científicos sem alteração. Não constitui nova prova browser. | CONFORME |
| 7 | Schema/migração | N/A | Nenhuma modificação de schema/API/versionamento. | N/A |
| 8 | Logs, matrizes, benchmark | SIM | Comandos/contagens do produtor acima; execução independente30/30 e verificador11schemas/7fixtures/4exemplos. Matrizes congeladas preservadas. | CONFORME |
| 9 | Experimental | SIM | Maturidades de algoritmos/UI permanecem como na base. | CONFORME |
| 10 | Limitações | SIM | Outros geradores continuam exatos; GitHubActions da nova publicação deve confirmar correção remota. Aceite local não declara CI hospedado verde. | CONFORME |

## 5. Parecer F9

- Revisor independente: `/root/f9_independent_review`, sem autoria da correção funcional do teste.
- Commit SHA auditado: `9161586a554debd144c6861464e7b8f6f4534953` mais o diff de `tests/oracles/test_release_fixtures.py` identificado por SHA256 `04792e7ca4c523f92f41d44e941e5b2745c967d3299e1d69eacdb35de2f68754`.
- Data (UTC): 2026-11-17.
- Veredito F9: accepted
- Escopo: correção local de portabilidade numérica do teste de regeneração DARE, com integridade congelada e certificado independente; confirmação da execução hospedada após publicação continua obrigatória.

A revisão leu o diff completo e repetiu `python -m pytest tests/oracles/test_release_fixtures.py -q` no runtime isolado f9-ci-sdp, obtendo30 passed em0.85s. `scripts/verify_fixtures.py` aprovou11schemas/7fixtures/4exemplos e cada arquivo em `contracts/fixtures/` foi comparado byte a byte ao commitbase. Nenhuma mudança nos geradores ou nos módulos científicos foi necessária. Este parecer não substitui auditoria de uma release estável.
