# Dossiê de Handoff e Auditoria F9 — `WP-AUDIT-FIX-F5-FML`

**Fonte normativa única:** `ControlLab_Web_Documento_Diretor_v1.0.md`, CL-DIR-001 v1.0.0, §§5.6, 9.4, 12.2, 13.7/13.11 e Apêndices C/E.
**Template:** [`HANDOFF_TEMPLATE_APENDICE_E.md`](../../architecture/HANDOFF_TEMPLATE_APENDICE_E.md).
**Auditor independente:** subagente `f9_audit_f6`, separado do produtor `f5_implementation`.

## 1. Cabeçalho da Tarefa (Apêndice E)

| Campo Obrigatório | Valor / Referência |
| :--- | :--- |
| **WorkPackage ID** | `WP-AUDIT-FIX-F5-FML` |
| **Requisito(s) R** | R-05, R-10, R-21 |
| **Achado(s) / REM vinculado(s)** | AUD-009 / REM-06 |
| **Frente F** | `f5-fuzzy-ts`, fase Audit-Remediation |
| **Módulo / caminhos permitidos (`allowed_paths`)** | `control_lab/fuzzy/`, `tests/unit/f5/` |
| **Contratos consumidos** | `FuzzySystem`, `Result`, `result.schema.json`; perfil FML IEEE-1855-2016 declarado; convenções TS e ADR-006 |
| **Entradas / saídas** | `import_fml(xml)` → Result com modelo canônico ou falha tipada; `export_fml(system)` → XML do perfil suportado; inferência numérica antes/depois do round-trip |
| **Hipótese matemática** | Operadores, ordem dos vértices, sigma e parâmetros devem manter seu significado; entrada inválida ou estrutura não representável é rejeitada sem reparo silencioso |
| **Limite da implementação** | Aceite CPython local e perfil FML suportado; não equivale à certificação de todo IEEE 1855 nem à execução browser/Pyodide/Wasm |
| **Testes de aceite** | `pytest tests/unit/f5/ -v` (56 casos); 19 sondas independentes F9; T-FML-01, T-FML-02 e T-TS-01 |
| **Fixtures** | Fixtures ouro anteriores intactas; XML analítico F9 versionado no teste independente; sem expected produzido pela implementação |
| **Dependências** | `WP-AUDIT-FIX-F1-CORE-RPC`, ACCEPTED_BY_F9 na base |
| **Bloqueadores** | Nenhum no escopo local após correções solicitadas pela F9; release Web depende de F9-BUILD-CI e F9-WASM-GATES |
| **Evidência / PR esperado** | Base remota `45e15567fd7be308a939590bb7770b724d594980`, diff F5 auditado antes do commit; log integral vinculado na Seção 4 |
| **Risco** | Médio: endurecimento pode recusar arquivos antes aceitos por reparo silencioso; falhas agora são estruturadas e modelos válidos têm confronto analítico e round-trip |
| **Nível de maturidade pretendido** | `cpython_local_only`; sem promoção Web ou fechamento de gates |

Este foi o primeiro pacote elegível no início deste ciclo. O pedido atual “Você poderia executar mais 3 rodadas?” foi interpretado pelo Maestro como autorização de três ciclos sequenciais no contexto da exceção ao limite diário; esse entendimento foi informado ao usuário. Não se atribui ao usuário uma nova citação explícita de dispensa. Esta é a primeira dessas três rodadas; política e registro do orçamento ficam sob fechamento do Maestro.

## 2. Entregáveis Produzidos e Revisão Científica

F5 alterou somente `control_lab/fuzzy/fml.py` e acrescentou `tests/unit/f5/test_fml_strict_import.py`. O importador/exportador passa a rejeitar operadores/desfuzzificação/perfis desconhecidos; números malformados ou não finitos; parâmetros triangulares/trapezoidais fora de ordem; sigma gaussiano e parâmetros bell inválidos; formas, cláusulas e bases não representáveis; duplicações ambíguas. Não se usam ordenação, valor absoluto ou pisos numéricos para reparar o significado científico dos dados recebidos.

A primeira revisão F9 identificou dois casos que ainda bloqueavam o aceite: `linearShape` em uma entrada era aceito, mas falhava posteriormente na inferência; `tskTerm order=1` com um único coeficiente era reescrito como constante. A F9 devolveu evidência ao Maestro; a produtora corrigiu os casos, sem edição cruzada da F9. Entrada linear não suportada agora falha no import; consequente TSK explícito de primeira ordem exige `n_inputs+1` coeficientes, incluindo bias. O exportador acrescenta bias zero explícito quando necessário para preservar consequentes homogêneos multivariáveis. Testes do produtor verificam ambas as convenções de bias e equivalência numérica.

A F9 criou [`test_fml_remediation_independent.py`](../../../tests/oracles/test_fml_remediation_independent.py), com 19 casos próprios. Para a referência analítica, as duas pertinências triangulares são `(1−x)/2` e `(1+x)/2` em `[-1,1]`, com consequentes −1/+1, logo a saída ponderada é exatamente `y=x`. Mais duas sondas verificam `y=2x` com consequentes explícitos de primeira ordem e bias na primeira/última posição. Expected e tolerância absoluta `1e-12` são deduzidos dessa álgebra, não gerados pela função auditada.

O XML inicial do harness F9 usava o alias `WA`, que está fora do perfil anunciado pela implementação. O harness foi corrigido para `WTAVER`, sem alterar expected matemático nem tolerância; os casos negativos foram então reexecutados sobre uma base válida, evitando falsos positivos por erro de preparação da própria auditoria.

## 3. Checklist de Handoff de 10 Itens (Apêndice E)

| # | Pergunta Normativa (Apêndice E — CL-DIR-001) | Resposta Produtor | Evidência Objetiva | Auditoria F9 |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8?** | SIM | 56 testes F5 com tipos canônicos, envelopes Result e perfil declarado; round-trip via FuzzySystem; contratos/schemas inalterados | CONFORME |
| **2** | **Saída contém status, diagnósticos e proveniência, inclusive casos de falha?** | SIM | Sondas verificam failure tipado, data=None e proveniência; entradas inválidas não geram modelo reparado. Segurança XML tem falha explícita | CONFORME |
| **3** | **Testes analíticos foram escritos antes da otimização prematura?** | SIM | Partições analíticas preexistentes e novas referências y=x/y=2x; sem alteração de algoritmo de otimização ou expected de ouro | CONFORME |
| **4** | **Existe confronto independente da implementação, em vez de autorreferência?** | SIM | 19 sondas F9 próprias: 14 variantes inválidas, partição analítica, DTD/limites, cláusulas duplicadas e duas convenções de bias em y=2x; sem importar helpers do produtor | CONFORME |
| **5** | **O PR respeita ownership e não modificou mocks/expected values para esconder defeito?** | SIM | Dois arquivos F5 no escopo; F9 somente sonda/dossiê/log; 21 arquivos protegidos de contracts/oráculos anteriores mantêm SHA-256 idêntico | CONFORME |
| **6** | **O mesmo teste funciona em CPython e Pyodide no domínio anunciado?** | N/A | Domínio aprovado exclusivamente CPython local. Paridade Pyodide/Wasm continua em F9-WASM-GATES e não foi afirmada por testes nativos | N/A |
| **7** | **Alterações de schema tiveram migração/versão e revisão F9?** | N/A | Nenhum schema alterado. O endurecimento aplica o perfil existente; não há migração de contrato ou reparo legado implícito | N/A |
| **8** | **Logs, matrizes de fixture e resultados de benchmark foram anexados?** | SIM | Log integral, ambiente e hashes na Seção 4; XML e referências analíticas no teste F9; durações são de testes, sem alegação de benchmark Web | CONFORME |
| **9** | **Um método experimental permanece visualmente classificado como tal?** | SIM | Nenhuma promoção de maturidade, inferência estática não é convertida em TS dinâmico sem hipóteses; T-TS-01 e ADR-006 continuam cobertos | CONFORME |
| **10** | **Qualquer limitação conhecida tem issue e mensagens de falha adequadas?** | SIM | Perfil não suportado e estruturas não representáveis têm erros tipados; build/paridade acompanhados nos WPs F9-BUILD-CI/F9-WASM-GATES; dois achados da revisão foram corrigidos e têm regressões | CONFORME |

## 4. Registro de Ambiente, SHA e Saída de Execução

- **Commit SHA remoto base auditado:** `45e15567fd7be308a939590bb7770b724d594980` + diff F5 desta entrega.
- **Tree SHA remoto base:** `eab14885cd5e68fc6983cf4c19089fbae702883f0`.
- **HEAD local:** `3e6d397e83f9be57629981f4e240b3d142973171`, snapshot equivalente para diff, sem representar a história remota.
- **Data (UTC):** `2026-11-14`.
- **Ambiente e versões exatas:** Linux x86_64; Python 3.12.14; versões efetivamente importadas e plataforma completas no início do log abaixo. Pytest/jsonschema/Clarabel/CVXPY foram reprovisionados em target scratch compartilhado; nenhuma dependência versionada do repositório foi alterada.
- **Comando de ambiente:** PATH inclui `/workspace/scratch/ba21e63c86f4/testdeps/bin`; PYTHONPATH é `/workspace/scratch/ba21e63c86f4/testdeps`.
- **Saída integral dos comandos, exit codes, ambiente e 21 hashes protegidos:** [`WP-AUDIT-FIX-F5-FML.log`](../../architecture/audit-logs/WP-AUDIT-FIX-F5-FML.log).

| Verificação F9 | Resultado observado |
| :--- | :--- |
| `pytest tests/unit/f5/ -v` | 56 passed, 0 fail/skip; exit 0; 1.03 s |
| `python3 -m pytest tests/oracles/ tests/integration/ -v` | 45 passed, incluindo 19 sondas F9 FML; exit 0; 3.94 s |
| `python3 scripts/verify_fixtures.py` | 10 schemas, 3 fixtures SHA-256 e 4 exemplos aprovados; exit 0 |
| `git diff --check` | Sem erros de whitespace |
| Diff de contracts e hashes protegidos | Contracts sem diff; 21 hashes de arquivos preexistentes idênticos ao baseline |

O warning de depreciação do plugin externo anyio (`CallSpec2`) não foi erro de teste; não houve skips/xfails usados para aceitar a funcionalidade. A falha CLI exit 127 informada pela produtora ocorreu antes da coleta por ausência do pytest no novo ambiente e foi resolvida por provisionamento, não por mudança de testes.

**Rastreabilidade:** T-FML-01 valida inferência manual de duas regras TS; T-FML-02 valida round-trip Mamdani/TS em grade e rejeição estrita de XML/semântica inválidos; T-TS-01 continua bloqueando PDC para premissas incertas não mensuráveis. As novas sondas F9 reforçam T-FML-02 com referências algébricas e casos de falha independentes.

**Sincronização operacional:** o Maestro confirmou os 164 arquivos texto do snapshot contra a main remota, usando o conector autorizado. O terminal segue sem credenciais Git. A publicação será pelo conector, com árvore remota como base, parent no SHA remoto e atualização condicionada ao SHA esperado, sem force; binários documentais não baixados serão preservados. Isso não é evidência de git pull/git push literal autenticado no terminal.

F9 não modificou código F5, estado, orçamento, fixtures, schemas ou tolerâncias. A proteção por hashes abrange contracts e todos os oráculos preexistentes; sua lista integral está no log. Nenhum expected de fixture ouro foi regenerado.

## 5. Parecer Independente da Frente F9

- **Veredito F9:** `accepted`
- **Escopo aprovado (`acceptance_scope`):** `cpython_local_only`.
- **Revisor independente:** `f9-integration-qa` — subagente `f9_audit_f6`, distinto da implementação F5.
- **Commit SHA auditado:** base remota `45e15567fd7be308a939590bb7770b724d594980` + diff F5 auditado; HEAD local `3e6d397e83f9be57629981f4e240b3d142973171`. O Maestro criará o commit de publicação após este parecer.
- **Data (UTC):** `2026-11-14`.
- **Testes e artefatos validados independentemente pela F9:** 56 testes F5; 45 oráculos/governança, incluindo 19 sondas próprias; verificação de fixtures/schemas/exemplos; inspeção de fidelidade semântica, erros tipados, proteção XML, ownership e hashes.
- **Pendências / Bloqueadores remanescentes:** `WP-AUDIT-FIX-F9-BUILD-CI` e `WP-AUDIT-FIX-F9-WASM-GATES`; nenhum gate G-0A/G-0B/G-0C/G-0D foi fechado, e a liberação stable Web continua sem aprovação.

O aceite cobre a remediação do perfil suportado no domínio CPython demonstrado. Não comprova execução Pyodide/Wasm nem suporte automático a todas as extensões ou revisões do padrão IEEE 1855.
