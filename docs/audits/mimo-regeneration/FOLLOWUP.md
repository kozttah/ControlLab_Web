# F9 — Portabilidade da regeneração MIMO e da grade logarítmica

**Resolução em 2026-11-18:** `WP-AUDIT-FIX-F9-MIMO-REGENERATION`, incluindo o adendo PVM correlato, recebeu parecer independente `accepted` no [handoff F9](../handoffs/WP-AUDIT-FIX-F9-MIMO-REGENERATION.md). Os certificados de grade, respostas MIMO e trajetórias PVM estão documentados em `implementation/NUMERICAL_CERTIFICATE.md`; seis combinações de ambientes/configurações completaram 2.652 execuções de teste sem falhas ou skips. Ouro, gerador e tolerâncias congeladas permanecem intactos. Os relatos, requisitos e limites de repetição abaixo preservam o histórico das fontes anteriores à correção; o CI hospedado e a publicação do commit corrigido continuam sendo verificações separadas obrigatórias.

Estado: **achado aberto**. Pacote proposto: `WP-AUDIT-FIX-F9-MIMO-REGENERATION`. Este documento não implementa a correção nem altera fixture, gerador, teste ou tolerância.

## Adendo explícito de escopo — PVM correlato, 2026-11-18

Na execução deste pacote, a F9 reproduziu integralmente `candidate-from-ci.json` com a configuração efetiva `NPY_DISABLE_CPU_FEATURES=AVX512F,AVX2,FMA3` e kernel OpenBLAS Haswell. A mesma configuração revelou dez diferenças em `B-PVM-LQR`, apenas nas folhas calculadas `cases[i].expected.x/u/y`, com erro máximo `5.551e-17`; entradas, grade temporal, tempos de troca, metadados e tolerâncias permaneceram exatos. A evidência é `reviewer/pvm-simd-differences.json`. Isso alcança outra comparação exata no mesmo laço e comando de aceite, após o ramo MIMO.

O Maestro e a revisão F9 aprovaram tratar esse achado concreto no **mesmo WorkPackage**, dentro dos mesmos `allowed_paths`, com regressão `T-PVM-01`. Exige-se verificador PVM separado, sem normalização genérica: somente dados calculados de x/u/y podem variar; todos os demais campos permanecem exatos. O certificado deve reconstruir independentemente, em alta precisão, a solução por regimes da ODE diagonal, saturação e continuidade, `u=clip(v-Kx)`, `y=Cx` e condições CARE/ganho, preservando os critérios congelados de trajetória, equação e ganho. Positivos da configuração real e negativos científicos/estruturais independentes são obrigatórios. Gerador, ouro, checksums, schemas e fontes científicas de produção não mudam. Este adendo é QA de regeneração CPython e não promove a maturidade PathView ou os gates históricos.

## Evidência independente e alcance

Em `6369aa79b7280a2c534474d9860f1ef855f97c29`, [run 44332821471](https://github.com/kozttah/ControlLab_Web/actions/runs/44332821471), job B SDP `134901467320`, falhou somente `test_generator_independent_and_new_gold_deterministic`: **220 testes passaram e um falhou**. A falha está na igualdade exata do dicionário regenerado `B-MIMO-2x2`. O certificado ARX recentemente acrescentado foi ultrapassado com sucesso pelo mesmo teste antes da comparação MIMO. As comparações científicas produção-versus-ouro `test_t_mimo_01_full_grid_production`, `test_t_mimo_02_singular_cases_are_undefined` e holdout ARX passaram explicitamente nos logs.

O auditor buscou os logs primários diretamente, reconstruiu as duas representações completas do diff com `ast.literal_eval` e confirmou que uma coincide exatamente com o JSON ouro. A outra foi preservada em `candidate-from-ci.json`. O relatório `CI_FAILURE_DIAGNOSTIC.json` enumera todas as **92 folhas numéricas diferentes** e inclui as fórmulas independentes verificadas. O extrato `CI_FAILURE.log` e o job original permitem rastrear a falha.

Cinco diferenças são na **entrada gerada `data.omega.data`**, cada uma de **um ULP**, maior diferença absoluta `5.684341886080802e-14`. Exemplos: `316.2277660168379` versus `316.22776601683796` e `50.118723362727245` versus `50.11872336272725`. As outras 87 folhas estão em `G.real/imag`, valores singulares e `S/T.real/imag`; a maior diferença relativa observada é `6.85786801858699e-16` e a maior distância é seis ULP. RGA, dados de A/B/C/D, metadados, proveniência, tolerâncias e os demais campos coincidem.

Isso difere do achado ARX anterior, no qual as entradas eram exatamente iguais. A inferência compatível é variação de últimos bits em operações numéricas de geração da grade e dos resultados, envolvendo potencialmente NumPy/CPU/libm/BLAS. **Não foi demonstrada uma biblioteca ou instrução BLAS específica como causa exclusiva.** Não há evidência desta falha de que a reidratação de referências F7 ou os cálculos científicos de produção estejam incorretos.

## Integridade e confronto analítico

O SHA-256 da fixture MIMO permanece `23d42ef684bcb5c4fe484ef24a624ae50020c883de986a617d21981bf5ff29ed`. O auditor reconferiu os nove hashes protegidos da rodada F7, e comparou gerador, oráculo e certificado ARX byte a byte com a base anterior à F7. Nenhuma implementação de `control_lab`, fixture, oráculo ou gerador científico mudou no commit F7. Os limites congelados continuam `response_atol=1e-11`, `identity_atol=1e-11`, `singular_values_atol=1e-11` e `crossing_atol=1e-7`.

Como diagnóstico independente, o auditor verificou os valores reconstruídos do CI na **mesma grade gerada do candidato**, sem chamar algoritmos de produção: partes real/imaginária de `G=M/(1+jw)`, adjugata 2x2 para `S` e `T`, autovalores fechados de `M.T M` para os valores singulares e `S+T=I`. Os maiores erros foram `4.45e-16` (G), `1.78e-16` (S), `1.25e-16` (T), `8.89e-16` (valores singulares) e `2.29e-16` (identidade). Todos estão abaixo dos respectivos critérios já congelados. Isso sustenta o diagnóstico numérico, mas **não é a implementação nem o aceite do futuro certificado da grade**.

## Tratamento nesta rodada

A F9 recomenda **uma única execução diagnóstica adicional**, preservando também a tentativa negativa. A forma direta é reexecutar o job B SDP no **mesmo SHA**. O objetivo é avaliar a intermitência entre hosts/configurações do CI; não equivale a repetir até obter verde. Um resultado positivo posterior não encerra este achado.

Como alternativa proporcional, o Maestro pode usar a execução normal do **commit final contendo apenas metadados/documentação deste achado** como essa única execução diagnóstica, **em substituição**, nunca em adição, ao rerun do SHA original. Nesse caso deve verificar por hashes que produção F7, `control_lab`, gerador, oráculos, fixtures, locks e tooling de runtime permanecem exatamente os da fonte `6369aa79b7280a2c534474d9860f1ef855f97c29`. Registrar os dois SHAs e a identidade das fontes científicas; não descrever commits diferentes como o mesmo SHA. Esta alternativa permite persistir a fila e as evidências sem executar duas cargas extras de CI. Se já houver rerun diagnóstico solicitado, essa alternativa não cria direito a outra tentativa.

Não se autoriza nesta rodada F7 modificar o teste, o gerador, a grade, as fixtures ou as tolerâncias para forçar aprovação. Se a única repetição também falhar, o CI e a publicação dependente permanecem bloqueados até correção auditada em pacote próprio. O handoff F7 deve continuar distinguindo seu aceite funcional de transporte das condições do pipeline completo; nenhuma execução negativa pode ser omitida.

## Entrega exigida no pacote próprio

1. Preservar os bytes ouro e checksums. Entradas de matrizes, schema, tipos, ordem, shapes, parâmetros do modelo, metadados, proveniência, tolerâncias e campos não explicitamente calculados permanecem exatos. Validar estrutura e finitude **antes** de coerção ou normalização.
2. Tratar a grade logarítmica como questão explícita, não como saída qualquer. Confrontar a fórmula e os parâmetros declarados de `logspace(-3,3,61)` e o ponto zero, verificar endpoints, positividade, ordem e espaçamento. Definir uma referência independente de alta precisão e justificar por operações, escala e IEEE-754 o limite de representação/arredondamento do expoente e de sua exponenciação. Não reaproveitar `response_atol` para frequência, não usar `allclose` global nem simplesmente aceitar o maior erro observado.
3. Alternativamente, se for adotada grade canônica de entrada em float64, demonstrar sua relação com a especificação matemática e preservar os bytes ouro. Não copiar resultados esperados do código de produção nem normalizar silenciosamente a grade depois de calcular saídas em outra grade. Qualquer alteração do gerador precisa ser explícita e revisada pela F9.
4. Enumerar os campos calculados permitidos e compará-los com os respectivos limites já congelados: resposta G/S/T e RGA, valores singulares, residual de identidade e cruzamentos quando aplicáveis. Não usar um limite de grandeza distinta como substituto de um critério ausente.
5. Reconstituir independentemente as fórmulas 2x2, RGA analítica, espectro de `M.T M`, condições de invertibilidade/fechamento, `S+T=I` e equação polinomial dos múltiplos cruzamentos. Não aceitar apenas diagnósticos fornecidos pelo gerador nem fabricar referência chamando as funções científicas de produção. Tornar explícito como o erro admitido da grade se propaga para a comparação das respostas.
6. Acrescentar negativos que rejeitem grade trocada/desordenada/corrompida além do envelope, saídas próximas porém incoerentes, violação dos limites existentes, rank/singularidades indevidamente reinterpretados, metadados/shape/dtype/ordem incorretos, campos extras e NaN/Inf. Incluir os cinco pontos e demais diferenças reais preservados desta falha como regressão positiva certificada, sem alterar o ouro.
7. Demonstrar a regeneração em ambos os perfis isolados (`core_no_sdp` e `sdp_available`) e em mais de uma configuração/host numérico, registrando versões, kernels efetivos e hipóteses da grade. Dois kernels no mesmo host não devem ser descritos como dois computadores. Incluir o verificador de integridade e auditor independente distinto do autor.

## Checklist do futuro handoff — Apêndice E

| Item | Prova exigida |
| --- | --- |
| 1. Contrato | Comparação consistente com a fixture e a grade declarada, sem mudar API de produção. |
| 2. Diagnósticos/proveniência | Campos, ambiente, grade e erros específicos registrados; tentativa negativa preservada. |
| 3. Analítico | Grade de alta precisão, fórmulas 2x2, espectro, identidades e cruzamentos confrontados independentemente. |
| 4. Independência | Auditor separado do autor; referências não obtidas das funções de produção. |
| 5. Ownership/ouro | Apenas F9; fixtures/checksums e limites congelados intactos, sem normalização genérica. |
| 6. Domínio | Certificado CPython da fixture; não inferir novo aceite Wasm ou de modelo geral. |
| 7. Schema | Tipos, chaves, shapes, ordem e metadados permanecem estritos; sem migração silenciosa. |
| 8. Evidências | Logs positivos/negativos, valores do CI preservados e ambientes reproduzíveis identificados. |
| 9. Maturidade | Nenhum gate ou produto promovido pela correção de um teste de regeneração. |
| 10. Limites | Orçamentos de arredondamento e propagação da grade documentados; nenhuma alegação universal sem prova. |
