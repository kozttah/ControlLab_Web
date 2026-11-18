# Produtor F9 — WP-AUDIT-FIX-F9-ARX-REGENERATION

Data: 2026-11-18. Base: `181bba0f864f9ea3bb02f136227d664aa3913e07`.
Produtor: `/root/f9_arx_finish`, retomando implementação F9 anterior.
Estado: pronto para auditoria independente; este documento não constitui autoaceite.
Norma: CL-DIR-001 §§10.2/10.4/13.11, Apêndice E; R-23/R-24 e T-ID-01/T-ID-03.

## Problema e entrega

O teste de regeneração ARX comparava resultados calculados GELSD/BLAS por igualdade
exata, contrariando a variação dos últimos bits admitida na proveniência congelada.
O helper F9 compara somente os campos calculados explicitamente enumerados com
os critérios já congelados, e acrescenta certificados independentes em Decimal
60 dígitos: Gram positivo definido, estacionariedade de mínimos quadrados,
espectro Gram por Jacobi, polinômio dos polos, recorrências de predição/simulação
e FIT reconstruído. Não importa o estimador de produção, SciPy ou o gerador.

A inspeção independente identificou que coerção NumPy poderia ocultar strings
numéricas ou nesting antes da normalização. Corrigiu-se o helper com uma passagem
estrutural anterior a qualquer coerção: tipos Python, chaves e comprimentos
recursivos devem coincidir. Depois dos testes numéricos, somente folhas calculadas
na cópia da candidata são normalizadas; todo o restante permanece exatamente igual
ao ouro. Isso mantém shape/dtype/order, dados de entrada, ruído, splits, PRBS,
proveniência, rank, schema e tolerâncias sem exceções silenciosas.

`NUMERICAL_CERTIFICATE.md` explicita os orçamentos de erro, a derivação Gram/Weyl,
escala, condição aproximada 81.35 e domínio. O envelope `gamma(m+8*n)` é uma
majoração backward declarada para esta fixture, não uma contagem universal das
operações GELSD nem uma alegação de enclosure intervalar. Dois kernels reais,
Haswell e Sandybridge, permitem verificar a diferença observada sem fabricar
novas referências. O domínio continua CPython QA; não há nova capacidade Wasm.

## Validação e integridade

- `producer/focused.log`: **85 passaram**, zero falhas/skips, incluindo 12 casos
  do produtor e os adversariais independentes do revisor.
- Ruff check e format check do helper e dos testes do produtor: **PASS**.
- `git diff --check`: **PASS**.
- `producer/source-checks.json`: hashes das fontes do produtor e confirmação
  byte a byte de sete fixtures, checksums e lock Pyodide, todos iguais à base.
- O Maestro executou os dois perfis isolados com seus locks exatos sob Haswell
  e Sandybridge. Os relatórios `maestro/*/B-*.json` registram **387/387** em
  `core_no_sdp` e **221/221** em `sdp_available`, em cada kernel; zero skips e
  código de retorno zero. O revisor deve confrontar estes resultados diretamente.

Os testes do produtor verificam ausência de mutação dos argumentos, rejeição de
violação dos quatro limites congelados e igualdade estrita de entradas. Os testes
independentes acrescentam ULP positivo, incoerência dentro dos limites congelados,
SVD com traço preservado, tipos/nesting/shape/order/rank/metadados incorretos e
NaN/Inf. Nenhum teste foi removido ou marcado skip.

## Checklist do produtor — Apêndice E

| Item | Evidência e alcance |
| --- | --- |
| 1. Contrato e consumidores | Nenhuma API de produção muda; helper F9 é chamado apenas pelo teste de regeneração ARX. |
| 2. Diagnósticos e falhas | Helper retorna resíduos, envelopes e condição; falhas têm asserts específicos; tipos e finitude são verificados antes da coerção. |
| 3. Analítico | Certificados OLS/Gram/polos/recorrência/FIT documentados; nenhuma otimização científica introduzida. |
| 4. Independência | Referência preservada e Decimal independentes de GELSD/estimador; revisor separado escreve e executa adversariais próprios. |
| 5. Ownership/ouro | Somente scripts, oráculos e auditorias F9; bytes e limites congelados intactos. |
| 6. CPython/Pyodide | Entrega é QA CPython; quatro combinações perfil/kernel passam; nenhuma alegação nova sobre Wasm. |
| 7. Schema/migração | Schema/fixture e produção não mudam; estrutura estrita verificada antes e depois das comparações. |
| 8. Evidências | Logs, hashes e diagnósticos preservados em producer/, reviewer/ e maestro/. |
| 9. Maturidade | Gates, maturidade beta, UI e classificações experimentais permanecem como na base. |
| 10. Limites conhecidos | Fixture ARX fixa, bem condicionada, float64; envelope backward não é prova intervalar geral; dois kernels no mesmo host. |

## Congelamento

Fontes e testes do produtor estão congelados para a auditoria independente. Não
foram feitos commits, alterações em PROJECT_STATE ou registros de orçamento pelo
produtor. Parecer final e publicação cabem ao revisor F9 e ao Maestro.
