# F9 — Follow-up de regeneração ARX entre implementações BLAS

**Estado: achado aberto; sem alteração de fixture, gerador, teste ou tolerância neste WorkPackage de Service Worker.** Proposta de pacote separado: `WP-AUDIT-FIX-F9-ARX-REGENERATION`. O Maestro registra a fila em `PROJECT_STATE.json`.

## Evidência e alcance

Candidato `89fb4e048cb787027adb239d35448b42e09d3368`, [run 44197401222](https://github.com/kozttah/ControlLab_Web/actions/runs/44197401222), job B SDP `134442312299`: falhou `test_generator_independent_and_new_gold_deterministic` em `tests/oracles/test_release_fixtures.py` na igualdade exata do dicionário regenerado `B-ARX-PRBS`. A mesma fonte científica e fixture haviam passado no candidato anterior; somente o lock de automação de navegador e diagnóstico do teste A/B mudaram entre os candidatos.

O auditor buscou o log diretamente e identificou 1.477 pares numéricos diferentes, com maior diferença absoluta de `2.1316282072803006e-14`, entre os resultados derivados do ajuste LAPACK, polos e predições. Exemplos: primeiro coeficiente `-0.8988322394071179` versus `-0.8988322394071188`; valor singular `37.1916107110404` versus `37.19161071104038`. Os dados de entrada, PRBS, metadados, tolerâncias e proveniência não aparecem diferentes. O sumário independente está em `reviewer/arx-ci2-diagnostic.json`; o log original permanece vinculado ao job imutável.

A fixture declara explicitamente `IEEE-754 float64 CPU; BLAS last-bit variation permitted by tolerances`. O gerador usa `scipy.linalg.lstsq(..., lapack_driver='gelsd')`, enquanto a produção usa QR independente. A igualdade exata aplicada a campos calculados contradiz esse contrato de portabilidade. A inferência de variação entre rotinas/hosts BLAS é compatível com as diferenças observadas; não foi demonstrado defeito científico no modelo ou no solver de produção.

O SHA-256 congelado de `contracts/fixtures/B-ARX-PRBS.json` continua `6fc72bebb5237aca36994b0fc71e06f6444fa9a1b163be79180764f07a18acc1`. Todas as sete fixtures, o manifesto de checksums e o lock Pyodide permanecem iguais ao baseline do auditor. A comparação científica produção-versus-ouro e suas tolerâncias continuam intactas.

## Tratamento diagnóstico neste ciclo

Admite-se uma única reexecução diagnóstica do job B SDP no mesmo SHA, registrando também a tentativa negativa. Não permite nova geração do ouro, mudança de hashes, afrouxamento de tolerância, exclusão de teste ou reruns sucessivos até obter verde. Se a repetição falhar, o ciclo permanece bloqueado até correção auditada em pacote separado. Um resultado verde posterior não encerra este achado de portabilidade.

A única repetição autorizada concluiu com sucesso no mesmo SHA, job `134449383224`, tentativa 2 do run: **166 passaram**, inclusive o teste de regeneração. O auditor buscou diretamente os logs e preservou o extrato em `reviewer/arx-ci2-retry.log`. Nenhum teste, fixture ou tolerância foi editado entre tentativas. O resultado confirma a intermitência observada; este follow-up continua aberto.

## Entrega exigida no pacote próprio

1. Restringir qualquer comparação numérica a campos calculados explicitamente enumerados. Entradas, PRBS, ruído, divisões treino/validação, parâmetros do gerador, schema, shape/dtype/order, metadados, rank, tolerâncias e proveniência mantêm igualdade exata. Bytes congelados continuam verificados por checksum.
2. Comparar coeficientes, polos, predições e FIT com os respectivos critérios **já congelados** (`theta_atol`, `pole_atol`, `prediction_atol`, `fit_atol`), com `rtol=0` onde definido. Não usar `planted_coefficient_atol` como substituto do critério mais estrito do estimador.
3. Reconstruir independentemente a regressão a partir dos dados preservados e verificar resíduo/ótimo de mínimos quadrados, recorrências de previsão/simulação, polos e FIT. Não confiar apenas em campos de diagnóstico fornecidos pelo gerador e não chamar o estimador de produção para fabricar a referência.
4. Tratar valores singulares explicitamente: a fixture não possui tolerância SVD específica. Exigir certificado/invariante independente e justificar o limite de arredondamento com dimensões, normas e precisão IEEE-754, sob revisão F9. Não reaproveitar arbitrariamente uma tolerância de outra grandeza ou acrescentar um `atol` global.
5. Acrescentar negativos que rejeitem coeficiente/polo/predição/FIT além dos limites existentes, certificado incoerente mesmo com campos próximos, rank errado, alteração de entrada/schema/shape/metadados/tolerância e NaN/Inf. Incluir caso positivo com perturbação de último bit apenas nos campos permitidos.
6. Demonstrar o mesmo teste em CPython com mais de uma configuração/host BLAS, preservando fixtures/checksums. Arquivar versões NumPy/SciPy, configuração BLAS, resultados e histórico de falhas. O teste DARE já distingue campos calculados e entradas, mas não é autorização para normalização genérica ARX.

## Checklist de handoff do futuro pacote (Apêndice E)

| Item | Prova exigida |
|---|---|
| 1. Contrato | Sem mudança de API de produção; comparação consistente com contrato da fixture. |
| 2. Diagnósticos/proveniência | Registrar BLAS/versões/campos e falhas específicas, sem ocultar tentativa negativa. |
| 3. Analítico | Certificados de regressão, recorrência, polos e SVD/invariantes. |
| 4. Independência | Revisão por agente diferente do autor e certificados sem solver de produção como oráculo. |
| 5. Ownership/ouro | Apenas F9; hashes, expected congelados e tolerâncias imutáveis. |
| 6. Domínio | Escopo deste gerador é CPython; não alegar aceite Wasm por este teste. |
| 7. Schema | Sem alteração do schema/fixture; qualquer exceção exige revisão explícita. |
| 8. Evidências | Logs positivos/negativos e comparação entre hosts/configurações BLAS. |
| 9. Maturidade | Não promover gate/produto pela correção de um teste de regeneração. |
| 10. Limites | Resolver este achado com negativos e manter eventuais limites numéricos rastreados. |
