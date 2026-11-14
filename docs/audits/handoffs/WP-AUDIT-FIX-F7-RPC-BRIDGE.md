# Dossiê de Handoff e Auditoria F9 — `WP-AUDIT-FIX-F7-RPC-BRIDGE`

**Fonte normativa única:** `ControlLab_Web_Documento_Diretor_v1.0.md` (`CL-DIR-001`, v1.0.0), §§1.4, 8.1–8.4, 10.5, 13.9, 13.11 e Apêndices C/E.
**Template:** [`HANDOFF_TEMPLATE_APENDICE_E.md`](../../architecture/HANDOFF_TEMPLATE_APENDICE_E.md).
**Auditor independente:** subagente `f9_audit`, separado do produtor `f7_implementation`, sob os papéis de `.agents/agents/`.

## 1. Cabeçalho da Tarefa (Apêndice E)

| Campo Obrigatório | Valor / Referência |
| :--- | :--- |
| **WorkPackage ID** | `WP-AUDIT-FIX-F7-RPC-BRIDGE` |
| **Requisito(s) R** | R-01, R-02, R-09, R-16, R-17, R-27, R-28 |
| **Achado(s) / REM vinculado(s)** | AUD-001, AUD-002, AUD-014, AUD-010, AUD-013; REM-02, REM-07 |
| **Frente F** | `f7-worker-bridge`, fase `Audit-Remediation` |
| **Módulo / caminhos permitidos (`allowed_paths`)** | `web/bridge/`, `web/worker/`, `web/storage/`, `tests/unit/f7/` |
| **Contratos consumidos** | RPC `api_version=1.0`; `rpc_request.schema.json`, `rpc_response.schema.json`, `result.schema.json`; dispatcher F1 `control_lab.core.rpc.dispatch` |
| **Entradas / saídas** | `ControlLabEngineClient.execute(RpcRequest)` → `RpcResponse`; objetos canônicos por `plant_ref`/inline, snapshots e buffers transferíveis; init com capacidades observadas |
| **Hipótese matemática** | Somente o pacote Python calcula respostas científicas; uma planta não estabilizável não produz controlador; resultados/revisões não são inventados pela bridge |
| **Limite da implementação** | Aceite local em Node + dispatcher científico CPython. Transporte `MessageChannel`, proxies e IndexedDB em memória são doubles explicitamente identificados nos testes. Browser/Pyodide/Wasm, IndexedDB de navegador, cache offline real e distribuição da wheel não foram validados nesta rodada |
| **Testes de aceite** | `node scripts/run_web_tests.mjs --scope f7`: TypeScript estrito e 28 testes; T-RPC-01/02 no escopo unitário; regressões `test_no_python_runtime_no_scientific_success` e `test_unstabilizable_plant_through_real_rpc`; duas sondas independentes F9 |
| **Fixtures** | B-CARE-02 para confronto analítico; B-CARE-12x3 e B-SDP-A-D preservadas e verificadas pelos oráculos existentes. Nenhum expected/tolerância alterado |
| **Dependências** | `WP-AUDIT-FIX-F9-GOV` e `WP-AUDIT-FIX-F1-CORE-RPC`, ambas `ACCEPTED_BY_F9` na base |
| **Bloqueadores** | Nenhum no aceite local deste WP. Integração/distribuição e liberação Web dependem de `WP-AUDIT-FIX-F8-TS-UI`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F7-OFFLINE-SW` e `WP-AUDIT-FIX-F9-WASM-GATES` |
| **Evidência / PR esperado** | Base remota `5ca1f13a268c3b94c48369becc03d7de2246f4c7`, alterações F7 auditadas antes do commit; log integral e sondas versionados neste ciclo |
| **Risco** | Médio: inicialização/ponte e persistência compartilhadas; mitigado por falha fechada, schemas, fixture analítica, testes de corrida/snapshot e ausência de promoção Web |
| **Nível de maturidade pretendido** | `beta` no contrato Web, `unavailable_wasm` para solver SDP não demonstrado; nenhuma declaração `stable` ou `offline_ready=true` |

**Seleção:** este foi o primeiro WorkPackage com status `PENDING` e todas as dependências aceitas, na ordem de `PROJECT_STATE.json`. O usuário autorizou expressamente ignorar o limite diário somente nesta rodada, sem alteração da política de orçamento. A atualização de status e o registro do orçamento ficam com o Maestro após este parecer.

## 2. Entregáveis Produzidos

1. `web/worker/pyodide_worker.ts`: remove completamente `executeFallbackDesignLqr`; usa `control_lab.core.rpc`; importa `pyodide.mjs` local quando necessário, provisiona pacotes da distribuição e wheel pura por `micropip.install.callKwargs(..., {deps:false})`, libera os proxies e exige handshake `core.capabilities` antes de `ready`. Capacidades/versões deixam de ser constantes fictícias; respostas com identidade/revisão divergente são rejeitadas.
2. `web/bridge/pyodide_client.ts`: exige Web Worker real configurado por `workerUrl`, ou `workerFactory` explícita para testes; remove o fallback silencioso para MessageChannel. Uma falha de init limpa capacidades e retorna erro estruturado.
3. `web/bridge/client.ts`: expõe `getCommittedRevision()` e reexporta `ExecutionMetrics`; falha de inicialização retorna `failure`, `committed=false`, sem ganho nem proveniência numérica inventada.
4. `web/bridge/mock_adapter.ts`: rótulos `beta`/offline não comprovado e proveniência `mock.certified_fixture.care`, distinguindo fixture certificada de execução SciPy real.
5. `tests/unit/f7/`: testes anteriores adaptados ao handshake obrigatório e rotulados segundo a evidência efetiva; helpers de fixture e CPython somente de teste; novas regressões de runtime ausente, provisão, não estabilizabilidade e sensibilidade a Q/R/x0.
6. F9 acrescentou [`rpc_bridge_cpython.test.mjs`](../../../tests/oracles/rpc_bridge_cpython.test.mjs), que não importa helpers científicos do produtor: chama o dispatcher CPython real por um adaptador de transporte independente, valida JSON Schema e confronta K/P com os valores e tolerâncias analíticos congelados da B-CARE-02. O caso não estabilizável usa o critério PBH: com B=0 e A=diag(1,2), os modos instáveis são incontornavelmente não controláveis.

**Configuração de produção:** `workerUrl` deve apontar ao Worker module distribuído. O `indexURL` local deve conter a distribuição Pyodide (`pyodide.mjs`, Wasm e inventário/recursos correspondentes). Os pacotes padrão são `numpy`, `scipy` e `/wheels/control_lab-1.0.0-py3-none-any.whl`. Este WP implementa o carregamento e a falha fechada; o artefato de release/build desses recursos é responsabilidade do WP F9-BUILD-CI.

## 3. Checklist de Handoff de 10 Itens (Apêndice E)

| # | Pergunta Normativa (Apêndice E — CL-DIR-001) | Resposta Produtor | Evidência Objetiva | Auditoria F9 |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8?** | SIM | Typecheck estrito dos 13 arquivos TS F7; exemplos RPC e violações de schema nos testes; sondas F9 validam requests/responses pelo JSON Schema real; interface pública corrigida | CONFORME |
| **2** | **Saída contém status, diagnósticos e proveniência, inclusive casos de falha?** | SIM | Runtime ausente retorna SOLVER_UNAVAILABLE, result=null, committed=false; não estabilizável via CPython retorna HYPOTHESIS_VIOLATED; envelopes validados independentemente | CONFORME |
| **3** | **Testes analíticos foram escritos antes da otimização prematura?** | SIM | Fixture analítica B-CARE-02 e oráculos anteriores preservados; novas sondas verificam a álgebra conhecida. Nenhuma otimização ou matemática de F1–F6 foi modificada | CONFORME |
| **4** | **Existe confronto independente da implementação, em vez de autorreferência?** | SIM | F9 criou duas sondas próprias: K=[2,3], P=[[6,2],[2,3]] da fixture analítica congelada; A=diag(1,2), B=0 deve falhar por PBH. CPython real e schemas, sem expected gerado pela produção | CONFORME |
| **5** | **O PR respeita ownership e não modificou mocks/expected values para esconder defeito?** | SIM | Todos os nove arquivos produtores ficam em allowed_paths F7; artefatos F9 sob CODEOWNERS F9; fixtures/schemas/oráculo preexistente sem diff. Doubles de transporte estão explícitos, não são evidência científica | CONFORME |
| **6** | **O mesmo teste funciona em CPython e Pyodide no domínio anunciado?** | N/A | Domínio aprovado desta rodada é Node/CPython local, não Pyodide. A matemática real foi executada em CPython; paridade Wasm/browser pertence a F9-WASM-GATES e não foi declarada concluída | N/A |
| **7** | **Alterações de schema tiveram migração/versão e revisão F9?** | N/A | Nenhum schema, contrato versionado ou convenção matemática foi alterado | N/A |
| **8** | **Logs, matrizes de fixture e resultados de benchmark foram anexados?** | SIM | Log integral com exit codes vinculado na Seção 4; matrizes completas nas fixtures originais e hashes abaixo. Durações são dos testes locais; não há alegação de benchmark Wasm/latência de produto | CONFORME |
| **9** | **Um método experimental permanece visualmente classificado como tal?** | SIM | Mock/runtime deixam de anunciar stable/offline pronto; SDP local não demonstrado permanece unavailable_wasm. Nenhum gate nem maturidade científica de F1–F6 foi promovido | CONFORME |
| **10** | **Qualquer limitação conhecida tem issue e mensagens de falha adequadas?** | SIM | Limitações rastreadas nos WPs F8-TS-UI, F9-BUILD-CI, F7-OFFLINE-SW, F9-WASM-GATES; falhas de runtime/loader/entrypoint são explícitas e estruturadas. Estes WPs são os registros de acompanhamento do projeto | CONFORME |

## 4. Registro de Ambiente, SHA e Saída de Execução

- **Commit SHA remoto base auditado:** `5ca1f13a268c3b94c48369becc03d7de2246f4c7` + alterações F7 desta entrega.
- **Tree SHA remoto base:** `c4e9e174bd2e04987ac00df86cf5f90e53f74137`.
- **`git rev-parse HEAD` local:** `141322403b7f6bb5819553078898c49b3ad00ea5`, snapshot de trabalho apenas, sem representar a história remota.
- **Data (UTC):** `2026-11-14`.
- **Ambiente:** Linux `6.18.57`, x86_64, glibc `2.41`; Python `3.12.14`; NumPy `2.3.5`; SciPy `1.17.0`; pytest `9.2.0`; jsonschema `4.26.0`; Node `v24.22.1`; TypeScript `5.8.3`. Clarabel/CVXPY não instalados e não exigidos por este WP; navegador/Pyodide/PathView não executados.
- **Toolchain local:** TypeScript instalado fora do repositório, com `/workspace/scratch/ba21e63c86f4/toolchain/node_modules/.bin` acrescentado ao PATH. Nenhuma configuração/lockfile versionado foi alterado.
- **Saída integral dos comandos e exit codes:** [`WP-AUDIT-FIX-F7-RPC-BRIDGE.log`](../../architecture/audit-logs/WP-AUDIT-FIX-F7-RPC-BRIDGE.log).

**Sincronização operacional:** clone e `git pull origin main` no terminal não puderam autenticar, embora o conector GitHub estivesse autorizado. O Maestro recuperou um snapshot fixado no SHA remoto pelo conector e conferiu os hashes Git de todos os 153 arquivos texto sem divergências. Binários documentais/imagens não usados nos testes não foram baixados e serão preservados pelo uso da árvore remota como base. A publicação do ciclo será feita pelo conector, com parent no SHA remoto, árvore baseada na tree remota e atualização de `main` condicionada ao SHA esperado, sem force. Isso não altera o escopo científico nem substitui evidência de execução de um `git pull`/`git push` literal.

**Resumo da auditoria executada independentemente:**

| Comando | Resultado observado |
| :--- | :--- |
| `node scripts/run_web_tests.mjs --scope f7` | Typecheck estrito PASS, 13 arquivos TS; 28 testes PASS, 0 fail/cancelled/skipped/todo; exit 0 |
| `node --test tests/oracles/rpc_bridge_cpython.test.mjs` | 2 testes independentes PASS, 0 fail/cancelled/skipped/todo; exit 0 |
| `python3 scripts/verify_fixtures.py` | 10 schemas, 3 fixtures SHA-256 e 4 exemplos aprovados; exit 0 |
| `python3 -m pytest tests/oracles/ tests/integration/ -v` | 17 passed; exit 0; um warning de depreciação do plugin externo anyio (`CallSpec2`), sem erro de teste |
| `node --test tests/integration/test_run_web_tests_fail_closed.test.mjs` | 8 testes PASS, 0 fail/cancelled/skipped/todo; exit 0 |
| `git diff --check` | Sem erros de whitespace |
| `git diff --name-only HEAD -- contracts/fixtures/ contracts/schemas/ tests/oracles/test_golden_fixtures.py` | Saída vazia: arquivos protegidos intactos |

**Rastreabilidade normativa:** T-RPC-01 tem cenários de 25/24 revisões fora de ordem e só confirma a última; T-RPC-02 recupera snapshot confirmado após fechar/recriar transporte, com IndexedDB em memória. Essas são evidências unitárias da semântica e não aprovação do ensaio browser real. T-SEC-01 offline real continua no WP correspondente; o teste de cache foi renomeado para não alegar que um stub prova offline. O teste de bloqueio de CDN verifica apenas a política local do Worker runtime.

**Integridade congelada:**

| Arquivo | SHA-256 antes e depois |
| :--- | :--- |
| `contracts/fixtures/B-CARE-02.json` | `f08f9fe28302c1704554460eb660a00c2911b75272358872672bbbb5068e516f` |
| `contracts/fixtures/B-CARE-12x3.json` | `0bacb2e43ebfb4a7803cd223de8c219deda4876a180175af30f20cd07f8686a4` |
| `contracts/fixtures/B-SDP-A-D.json` | `4377341309c5df1df3c814e3f1a3d38ea3783232c3f4ae84e201f829e5f33076` |
| `contracts/fixtures/checksums.sha256` | `df4b383e36fd191457914e8c29b880c841d497248ccf4ab821433038bd47ce56` |
| `tests/oracles/test_golden_fixtures.py` | `9bbfffe8c45f2cd9b6ab66172dbad25dd948f4b468354c9b6d2ace52ac2846e4` |

**Ownership antes do fechamento pelo Maestro:** nove arquivos produtores foram alterados/criados exclusivamente em `web/bridge/`, `web/worker/`, `tests/unit/f7/`; nenhum em `web/storage/`. F9 acrescentou somente a sonda independente, este dossiê e o log. `PROJECT_STATE.json` não foi alterado por F7/F9 durante a auditoria. A lista exata e hashes de entrega podem ser obtidos pelo diff do commit final; a base remota identificada acima permite reproduzir a comparação.

## 5. Parecer Independente da Frente F9

- **Veredito F9:** `accepted`
- **Escopo aprovado (`acceptance_scope`):** `node_local_bridge_cpython_dispatcher_only`.
- **Revisor independente:** `f9-integration-qa` — subagente `f9_audit`, distinto do produtor F7.
- **Commit SHA auditado:** base remota `5ca1f13a268c3b94c48369becc03d7de2246f4c7` + diff de entrega F7 auditado; snapshot local `141322403b7f6bb5819553078898c49b3ad00ea5`. O commit de publicação será criado pelo Maestro após este parecer.
- **Data (UTC):** `2026-11-14`.
- **Testes e artefatos validados independentemente pela F9:** typecheck F7; 28 testes F7; duas sondas F9 com dispatcher CPython e schema; 17 testes de oráculos/governança; oito testes do runner; integridade de fixtures, schemas, tolerâncias e ownership; inspeção do loader, micropip, descarte de proxies e handshake de capacidades.
- **Pendências / Bloqueadores remanescentes:** distribuição/build F9, configuração UI F8, provisão offline transitiva e ensaios reais browser/Pyodide/Wasm nos respectivos WPs. Não há promoção a `stable` Web nem fechamento dos gates G-0A/G-0B/G-0C/G-0D; mantém-se `NOT_APPROVED_FOR_STABLE_WEB_RELEASE`.

O aceite refere-se à remediação e à semântica local demonstrada. Ele não transforma o adaptador de transporte CPython nem os doubles de MessageChannel/IndexedDB em evidência de execução WebAssembly ou de recuperação real em navegador.
