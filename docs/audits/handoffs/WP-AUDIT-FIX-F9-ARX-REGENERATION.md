# Handoff F9 — WP-AUDIT-FIX-F9-ARX-REGENERATION

Parecer F9: accepted

Revisor independente: `/root/f9_arx_audit`, separado do produtor `/root/f9_arx_finish`. Data: 2026-11-18. CL-DIR-001 §§10.2/10.4/13.11 e Apêndice E; R-23/R-24, regressões T-ID-01/T-ID-03.

Fonte auditada: base `181bba0f864f9ea3bb02f136227d664aa3913e07` mais o diff identificado pelos quatro SHA-256 em `docs/audits/arx-regeneration/reviewer/checks.json` e `docs/audits/arx-regeneration/maestro/SUMMARY.json`. Este aceite autoriza registrar `ACCEPTED_BY_F9` para o escopo CPython abaixo; não declara antecipadamente o CI do futuro commit de conclusão.

## Resultado e confronto independente

O teste de regeneração ARX deixa de exigir identidade binária dos resultados calculados por BLAS. Mantém as tolerâncias já congeladas para coeficientes, polos, predições e FIT, com `rtol=0`; os valores singulares recebem confronto com o espectro Gram calculado independentemente. Tipos, chaves, comprimentos, entradas, PRBS, ruído, parâmetros plantados, divisões treino/validação, rank, shape/dtype/order, metadados, proveniência e tolerâncias continuam exatos. Os bytes ouro continuam verificados separadamente por SHA-256.

O helper não usa o estimador de produção, GELSD, SciPy ou o gerador para fabricar referências. Reconstrói em Decimal de 60 dígitos o Gram, a estacionariedade de mínimos quadrados, as recorrências e o FIT. O espectro Gram é obtido por Jacobi 4x4 independente, com verificação do residual fora da diagonal. Polos passam também pelo residual do polinômio ARX.

O revisor confrontou a derivação dimensional em `docs/audits/arx-regeneration/NUMERICAL_CERTIFICATE.md`: a formação arredondada do Gram teria `abs(DeltaG) <= gamma(m) abs(Phi).T abs(Phi)`, daí `||DeltaG||2 <= gamma(m)||Phi||F²`; Weyl limita a perturbação espectral. O envelope declarado `gamma(m+8*n)` majora essa escala com reserva para o pequeno bloco de parâmetros. Trata-se de critério backward específico da fixture bem condicionada, com escala e precisão declaradas, conforme §10.2. **Não é uma garantia universal de erro interno GELSD ou um enclosure intervalar formal.** A condição Gram observada é aproximadamente 81,35. As tolerâncias congeladas continuam limites obrigatórios adicionais.

A revisão encontrou uma falha estrutural na versão inicial do helper: strings numéricas e listas de dados aninhadas eram convertidas para float e depois ocultadas pela normalização. O produtor acrescentou validação recursiva de toda a estrutura **antes** de qualquer coerção; o auditor adicionou negativos próprios para esses casos, bool/int em componentes float, comprimentos, metadados, limites existentes e resultados incoerentes mesmo dentro das tolerâncias. Nenhuma fixture foi alterada para corrigir esse achado.

## Evidências de execução

- `reviewer/haswell-certificate.json` e `reviewer/sandybridge-certificate.json`, relativos a `docs/audits/arx-regeneration/`: processos separados confirmaram por `ctypes` os kernels efetivos Haswell e Sandybridge de NumPy e SciPy/OpenBLAS. São dois kernels reais no mesmo host, **não dois computadores distintos**. Os resultados derivados têm SHA-256 diferentes, enquanto entradas/metadados são exatamente os congelados; ambas as candidatas passam o certificado sem alteração dos argumentos.
- `reviewer/haswell-focused.log` e `reviewer/sandybridge-focused.log`: **85/85 testes passaram em cada kernel**, sem skips. Incluem 30 casos preexistentes da suíte de fixtures e 55 novos casos ARX, dos quais os adversariais do auditor foram escritos separadamente do helper.
- `maestro/SUMMARY.json` e respectivos JSON/JUnit: o auditor abriu os quatro relatórios, conferiu contagens, ausência de failures/errors/skips e hashes das fontes. Os ambientes isolados correspondem exatamente aos locks: `core_no_sdp` com 21 distribuições e `sdp_available` com 34 distribuições. **387 testes no perfil core e 221 no perfil SDP passaram em cada um dos dois kernels**: 1.216 execuções de teste ao todo, não 1.216 casos distintos.
- `reviewer/fixtures.log` e `reviewer/checks.json`: 11 schemas, sete fixtures e quatro exemplos aprovados; sete fixtures, manifesto de checksums e lock Pyodide permanecem com os nove hashes do baseline. O gerador `scripts/generate_release_fixtures.py` foi comparado byte a byte à base e não mudou. O diff do teste existente adiciona somente a importação e a seleção do certificado ARX; nenhum limiar numérico preexistente foi editado.

## Checklist do Apêndice E

| Item | Evidência e parecer |
| --- | --- |
| 1. Contrato e consumidores | CONFORME: não há mudança de API F1/F9, RPC ou consumidores F7/F8; o contrato da fixture ARX e o domínio do gerador permanecem os existentes. Comparação e validação estrutural aprovadas nos perfis exatos. |
| 2. Status, diagnósticos e proveniência | CONFORME: asserts nomeiam falhas estruturais e certificados; o helper retorna resíduos, envelopes, dimensão e condição para auditoria. Proveniência e parâmetros da fixture são exatos; JSONs registram versões e kernels efetivos. Nenhum Result de produção muda. |
| 3. Testes analíticos | CONFORME: Gram/Jacobi Decimal, estacionariedade, positividade, polinômio dos polos, recorrências e FIT independentes foram confrontados com limites dimensionados; a comparação com os critérios congelados continua obrigatória. |
| 4. Independência | CONFORME: auditor diferente do autor leu a matemática e a implementação, escreveu adversariais próprios, reproduziu a diferença real entre kernels e executou 85 testes em cada um. As referências não são obtidas do estimador de produção. |
| 5. Ownership e ouro | CONFORME: alteração funcional restrita a scripts e testes/oráculos F9, com documentos de auditoria. Nove hashes protegidos e bytes do gerador intactos; nenhuma tolerância de fixture ou oráculo preexistente foi modificada. |
| 6. CPython/Pyodide no domínio anunciado | CONFORME: este certificado é QA do gerador CPython. Os dois perfis isolados e os dois kernels reais foram aprovados. O helper não é embarcado como capacidade científica nova no Pyodide; não se infere nova prova Wasm deste teste. |
| 7. Schema, migração e versão | CONFORME: nenhum schema/API muda; validação recursiva rejeita tipo, shape/dtype/order, nesting, comprimentos e metadados incorretos. Não há migração. |
| 8. Logs e resultados | CONFORME: logs do auditor, diagnóstico dos certificados, configs reais BLAS, baseline e quatro JSON/JUnit do comando de aceite estão arquivados; os quatro hashes fonte vinculam resultados e diff auditado. |
| 9. Maturidade experimental | CONFORME: nenhuma maturidade de solver, funcionalidade UI ou Gate é promovida; a plataforma mantém sua classificação anterior. Este aceite refere-se exclusivamente à portabilidade da regeneração ARX. |
| 10. Limitações e falhas | CONFORME: os limites fixture-specific, ausência de intervalo formal, dois kernels no mesmo host e necessidade do CI hospedado posterior estão declarados. Negativos cobrem NaN/Inf, dano científico além do ouro, certificados incoerentes, SVD com traço preservado, estrutura, rank e proveniência. |

## Decisão e limites de publicação

O achado `F9-CI-ARX-PORTABILITY` está resolvido no escopo da fixture CPython `B-ARX-PRBS`: resultados calculados portáveis são confrontados numericamente e certificados, enquanto ouro, entradas e critérios congelados permanecem intactos. A base e as quatro fontes auditadas estão identificadas por hashes em `reviewer/checks.json`.

O Maestro pode atualizar o WorkPackage, registrar a tarefa e publicar o commit de conclusão. O workflow hospedado desse commit deve continuar sendo acompanhado para verificar regressões e publicação; este parecer não o substitui. Não há autorização deste handoff para enfraquecer outros geradores, generalizar o envelope a matrizes mal condicionadas ou declarar release estável.
