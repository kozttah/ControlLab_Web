# WP-AUDIT-FIX-F1-PVM-DISCRETE-CLOCK — parecer independente F9

**Decisão: `accepted`**, no escopo do adaptador discreto síncrono monofrequência demonstrado. O aceite do produtor não aprova gates globais ou uma release estável.

## Cabeçalho e escopo

- Norma: CL-DIR-001 v1.0.0, requisitos R-19/R-20/R-21; §9.3, §14.1, T-IO-01/T-IO-02/T-PVM-01/T-PVM-02 e Apêndice E.
- Origem: finding `F9-PVM-DISCRETE-001`; base remota `53e31974e4d56b73712629cf849de3e93bf3c537`; dependência aceita `WP-AUDIT-FIX-F1-PVM-OFFICIAL`.
- Produtor F1: `control_lab/io/`, `tests/unit/f1/`. F9: scripts de ensaio, testes Wasm e evidências em `docs/audits/pvm-discrete-clock/`. Nenhuma correção silenciosa da produção foi realizada pela F9.
- Contratos: `.pvm` 1.0.0, Result e tensores existentes; projeção discreta versionada `controllab.pathview.clocked.v2`; perfil contínuo v1 e legado numérico preservados.
- Hipótese matemática: todos os estados da planta e do controlador são amostrados antes de uma única atualização conjunta x[k+1]/z[k+1]; loops algébricos devem ser bem postos. Saturação é confrontada com a mesma saturação na referência.
- Entradas: matrizes numéricas e estados iniciais explícitos do ensaio independente, registros oficiais PathView/PathSim fixados, grafos recém-gerados e casos maliciosos de importação.
- Saídas: código `.pvm`, conversão oficial executável, séries reais/referência, comparações de todos os estados/entradas/saídas, testes de contrato/passividade e parecer F9.
- Limites: monofrequência; fontes constantes/zero/degrau no domínio já suportado; eventos personalizados e modelos/períodos incompatíveis mantêm falhas tipadas. A implementação não incorpora fork, callbacks com estado oculto ou trajetórias pré-computadas.

## Evidências e resultados

1. **86/86 testes F1 passaram**, incluindo recorrência analítica, estado inicial, estados dinâmicos, validação da projeção/clock/portas/conexões e importação passiva. Log produtor `f1-clock-acceptance-2.log` anexado pelo Maestro. A primeira tentativa falhou somente em expectativa antiga de recusa de uma capacidade agora implementada; não houve alteração de fixture/tolerância.
2. **39/39 execuções externas oficiais passaram**: 13 casos × passo T, T/4 e T/4 com grafo invertido, 24 atualizações por execução. Maior erro de y/u/todos os estados: **1,2765899448652362e-12**, limite independente 1e-10.
3. O contraexemplo original produz no PathSim oficial `1 → 0.76 → 0.592 → 0.4744 → 0.39208 → 0.334456`. A condição inicial em t=0 e o hold entre amostras também são verificados.
4. **9/9 regressões do ensaio histórico passaram**: oito contínuas e o discreto original, agora efetivamente simulado, sem substituir o esperado por uma declaração de indisponibilidade.
5. **73/73 testes de regressão passaram**, incluindo 69 de oráculos e quatro Wasm, com um aviso de depreciação do ambiente pytest/anyio, sem falhas/skips. O novo teste Wasm compara grafo CPython/Pyodide, todos os estados dinâmicos, u/y por recorrência independente, importação sem execução e adulteração de tau.
6. **Typecheck e 50/50 testes Node passaram**. O wheel reconstruído contém **64 módulos idênticos às fontes**, sem divergências; hash em `wheel-source-identity.json`.
7. **4/4 imports na UI oficial PathView 0.21.0 passaram** no Chromium 153, com nós esperados visíveis e sem pageerrors. Os hashes de `ui-import.json` conferem com os `.pvm` congelados.

Artefatos principais: `discrete-assay.json`, `f9-discrete-assay.log`, CSVs e `.pvm` por caso; `continuous-regression/trajectory-assay.json`; `ui-import.json`; `ownership-audit.json`; logs de regressão/build/Wasm copiados pelo Maestro. O script e os módulos produtores possuem hashes registrados. O registro upstream e os arquivos oficiais do conversor são fixados independentemente.

## Checklist de handoff — dez itens do Apêndice E

| Item | Evidência / parecer |
|---|---|
| 1. API/contrato para consumidores | Formato `.pvm` existente preservado; extensão v2 versionada e registro oficial; perfis v1/legado mantidos. Grafo e parâmetros iguais em CPython/Pyodide. |
| 2. Status, diagnósticos, proveniência | Exportação resulta em envelope existente; limites incompatíveis usam falhas tipadas; hashes, versões, entradas e estados completos registrados. |
| 3. Analítico antes de otimização | Recorrência escalar original e eliminação algébrica independentes; nenhuma otimização científica nesta entrega. |
| 4. Confronto independente | Conversor oficial + PathSim 0.31.0; referências explícitas de x/z/u/y não derivadas do compilador ControlLab nem dos callbacks exportados. |
| 5. Ownership e oráculos | Oito fixtures e doze arquivos de oráculos existentes intactos; 83 arquivos de produção fora de I/O intactos. Nenhuma tolerância ouro modificada. Teste Wasm anterior atualiza somente a expectativa da capacidade discreta e exige perfil v2. |
| 6. CPython/Pyodide no domínio anunciado | Recorrências e grafos verificados em ambas as plataformas; execução externa e UI usam versões oficiais fixadas. Sem alegação de backend SDP local aprovado. |
| 7. Schema/migração/revisão | Sem mudança de schema científico/RPC/.ctrlab. Projeção v2 explicitamente versionada; renderer/restore verificam toda expansão, com continuidade do v1 e legado. |
| 8. Logs, matrizes e benchmarks | Matrizes, estados, referências e séries completas anexadas; logs produtor/F9/regressões/UI/Wasm e wheel-source identity. Não se afirma aprovação de benchmark de desempenho nesta rodada. |
| 9. Maturidade experimental | Nenhuma promoção de produto/gate; `external_pathview_verified` global permanece conservador e SDP indisponível não é substituído por solver didático. |
| 10. Limitações e seguimento | Eventos externos e multirate continuam recusados; gates globais ainda pendentes. Finding discreto resolvido somente para o domínio monofrequência demonstrado, com evidência preservada do defeito anterior. |

## Observações de auditoria e encerramento

A indexação do próprio ensaio adaptativo exigiu corrigir a classificação de instantes kT sujeitos a arredondamento acumulado de poucos e-15 s. O log e a recomputação identificada do classificador inicial estão em `audit-diagnostics/`. A correção usa somente a tolerância temporal da grade já declarada; **nenhum limite de valores foi relaxado**. Casos T/4, sinais opostos, feedthrough, saturação, estados iniciais não nulos e inversão da ordem do grafo impedem que um erro de uma amostra seja ocultado.

Pode-se registrar este WorkPackage como `ACCEPTED_BY_F9` e contabilizar um ciclo concluído. O finding `F9-PVM-DISCRETE-001` está resolvido para exportação discreta monofrequência. G-0A/G-0B/G-0C/G-0D e `WP-AUDIT-FIX-F9-WASM-GATES` permanecem sujeitos à sua própria decisão e seus requisitos ainda não demonstrados.
