# WP-AUDIT-FIX-F1-PVM-OFFICIAL — parecer independente F9

**Decisão: `accepted`, restrita à correção produtora e ao domínio contínuo demonstrado.** O aceite não promove o gate global G-0D nem libera SDP de produção. A exportação oficial discreta permanece indisponível, com recusa tipada e contraevidência preservada.

## Cabeçalho e escopo

- Referência normativa: CL-DIR-001 v1.0.0, §9.3, §14.1, T-IO-01, T-IO-02, T-PVM-01, T-PVM-02 e Apêndice E; requisitos R-19/R-20/R-21 registrados no pacote.
- Origem: finding `F9-WASM-PVM-001`; base remota `0d788634fceddca4aa34ee04b00877df5aa43a7d`.
- Produtor: F1, apenas `control_lab/io/` e `tests/unit/f1/`. Auditor: agente F9 independente, com os ensaios oficiais de UI/Pyodide e a consolidação de regressões executados pelo Maestro.
- Dependências aceitas: `WP-AUDIT-FIX-F1-CORE-RPC` e `WP-AUDIT-FIX-F9-BUILD-CI`.
- Contratos consumidos: `.pvm` 1.0.0, modelos canônicos F1 e envelope Result; registro oficial PathView 0.21.0 fixado no commit `4afdcc461ed63aa4231930170d20774428d51e8d`.
- Entrada/saída: planta, controlador e cenário numéricos produzem grafo oficial, parâmetros Python derivados deterministicamente e metadados de disponibilidade. A importação permanece passiva.
- Hipóteses: dimensões compatíveis, convenção de realimentação explícita e loop algébrico bem posto. Para saturação, o confronto usa a mesma não linearidade. Nenhum ganho matricial é tratado como multiplicação escalar.
- Maturidade: adaptador contínuo verificado nos casos registrados; `external_pathview_verified=false` e `PENDING_G0D` globais preservados.

## Alteração examinada

O exportador padrão substitui tipos fictícios por `Source`, `Function`, `StateSpace`, `Adder`, `Clip` e `Scope` oficiais, com portas escalares. A planta expõe os canais de saída e, em seguida, os estados necessários à realimentação. Produtos matriciais K/N e os sinais são preservados; o controlador dinâmico mantém matrizes, feedthrough e estado inicial próprios.

A extensão numérica `controllab.pathview.scalar.v1` permite simulação passiva interna. Antes de usá-la, o adaptador confere expressões determinísticas, portas e conexões reais. Não executa expressões nem `codeContext.code` recebidos de importação. Grafos numéricos antigos continuam legíveis. O novo argumento Python explícito `runtime_profile="legacy_numeric"` é marcado como interno e `external_compatible=false`; `export_pvm` continua sempre no perfil oficial.

## Evidência científica e técnica

| Verificação | Resultado | Evidência |
|---|---|---|
| Aceitação F1, perfil core | 72/72 passaram; reexecução independente em 1,77 s | `../pvm-official/f1-acceptance-final.log` |
| Regressão final oráculos + Pyodide | 71/71 passaram, incluindo os dois casos novos do adaptador no Wasm; sem skips | `../pvm-official/final-regression.log` |
| TypeScript e testes Node | Typecheck aprovado e 50/50 testes passaram | `../pvm-official/web-regression.json` |
| Conversão e simulação externas | Oito casos contínuos passaram no conversor oficial e PathSim 0.31.0 | `../pvm-official/trajectory-assay.json`, `f9-external-final.log`, arquivos `.pvm`, `.py.txt` e `.csv` |
| Referência independente | Equações explícitas, loop algébrico resolvido separadamente e SciPy `solve_ivp`; erro máximo entre saídas/estados finais de `3.753094279801417e-9`, abaixo do novo limite `2e-6` | `scripts/audit_pvm_official.py` e `../pvm-official/README.md` |
| Interface oficial PathView | Quatro imports/renderizações passaram: C=I, C≠I, saturação e controlador dinâmico; sem erros de página | `../pvm-official/ui-import.json` e `ui-import.log` |
| Registro oficial fixado | Os seis tipos emitidos têm definições idênticas ao subconjunto upstream; hashes dos fontes e wheels registrados | `../pvm-official/official-registry-subset.json` e `trajectory-assay.json` |
| Preservação científica | Oito fixtures ouro intactas; nenhuma tolerância ou asserção numérica alterada; 83 arquivos de produção de outras frentes intactos | `../pvm-official/ownership-audit.json` |

O ensaio externo cobre realimentação positiva/negativa, C=I/C≠I com D≠0, referência retangular e MIMO, saturação, controlador dinâmico com Dp/Dc não nulos e estado inicial, e controlador com zero estados. O oráculo não chama o compilador ou simulador PVM interno. Somente modelos recém-gerados pela própria suíte são convertidos e executados externamente.

No navegador, os dois casos novos comprovam igualdade dos grafos/código gerado entre CPython e o wheel efetivamente carregado no Pyodide, importação passiva de codeContext malicioso e a mesma recusa discreta. Isso não afirma que PathSim foi executado dentro do Wasm.

## Adaptação estrutural independente do teste de oráculo

A primeira regressão consolidada revelou duas falhas em `tests/oracles/test_release_fixtures.py`: uma asserção antiga exigia a porta vetorial abstrata 1 para o estado. No ABI oficial, os canais y ocupam `[0,p)` e o estado x[j] ocupa `p+j`. A F9 alterou somente essa asserção estrutural, exigindo agora o mapa completo e sem duplicação `('plant_ss', p+j, j)` para os n canais que alimentam K.

Todos os valores esperados K/x/u/y, os dados das fixtures e suas tolerâncias foram preservados. A AST das asserções numéricas do arquivo foi comparada antes/depois e permaneceu idêntica. O arquivo isolado passou em 14/14 testes; a consolidação posterior passou em 71/71. O ajuste fortalece a conferência de canais em vez de omitir uma falha de dinâmica.

## Checklist do Apêndice E

| Item | Verificação e conclusão |
|---|---|
| 1. API/contratos | Schemas científicos/RPC existentes preservados; perfil legado é opção Python explícita. Grafo oficial conferido no consumidor PathView e regressões F7/F8 preservadas. |
| 2. Status/diagnósticos/proveniência | Result/warnings mantidos; discreto retorna `UNSUPPORTED_MODEL`, razão `discrete_schedule_mismatch`, sem falso sucesso. Versões/hashes constam nos artefatos. |
| 3. Analítico antes de otimização | Fixtures analíticas preexistentes mantidas; referência externa usa equações explícitas. Não houve otimização científica nesta rodada. |
| 4. Independência | Conversor/registro oficiais, PathSim real, referência SciPy independente e inspeção UI; nenhuma referência foi produzida pelo simulador PVM sob teste. |
| 5. Ownership/oráculos | F1 alterou somente seus quatro arquivos. F9 fez a adaptação estrutural de porta descrita acima; fixtures e asserções/tolerâncias numéricas intactas. |
| 6. CPython/Pyodide | Dois casos estático/dinâmico demonstram paridade de exportação, importação passiva e recusa discreta no wheel reconstruído. Simulações externas são do runtime CPython/PathSim fixado. |
| 7. Schema/migração | `.pvm` permanece 1.0.0; extensão por nó/metadados versionada e permitida pelo schema. Leitura numérica legada preservada; sem alteração de schema `.ctrlab`/RPC. |
| 8. Logs/matrizes/resultados | Entradas completas nos `.pvm`, código oficial emitido, trajetórias CSV, JSON com métricas/hashes e logs de aceitação/regressão anexados. |
| 9. Maturidade | Nenhuma promoção global a estável, de G-0D ou do solver educacional/SDP. Disponibilidade externa discreta explicitamente restrita. |
| 10. Limitações/seguimento | Contraevidência discreta preservada; follow-up interno `F9-PVM-DISCRETE-001` exige adaptação de relógio e novo confronto antes de habilitação. G-0D formal e G-0B continuam pendentes no estado do produto. |

## Limites do aceite e encaminhamento

`discrete-pre-fix/` e `trajectory-assay-initial.json` preservam a divergência discreta de 0,1 no primeiro candidato. O item discreto final com `passed=true` significa que a exportação foi recusada corretamente; **não significa paridade discreta aprovada**. A versão legada só atende migração/simulação interna e não deve ser distribuída como exportação PathView compatível.

A F9 autoriza `ACCEPTED_BY_F9` para este WorkPackage produtor no escopo contínuo acima. A decisão global G-0D continua separada, inclusive seus pré-requisitos G-0A/G-0C e evidências completas de integração/persistência. O pacote global `WP-AUDIT-FIX-F9-WASM-GATES` e o backend SDP G-0B não são encerrados por este parecer.
