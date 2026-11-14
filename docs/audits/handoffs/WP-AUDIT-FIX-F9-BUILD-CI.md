# Dossiê de Handoff e Auditoria F9 — WP-AUDIT-FIX-F9-BUILD-CI

## 1. Cabeçalho da tarefa — Apêndice E

| Campo obrigatório | Valor / referência |
| :--- | :--- |
| WorkPackage ID | WP-AUDIT-FIX-F9-BUILD-CI |
| Requisitos / achados | R-02, R-20, R-22, R-23, R-24; AUD-003, AUD-011; REM-09 |
| Frente produtora | F9 build/CI e F9 fixtures, autores distintos do auditor |
| Ownership produtor | pyproject.toml, web/package{,-lock}.json, scripts/, .github/workflows/, quatro novas contracts/fixtures, manifesto aditivo, verify_fixtures, tests/oracles, docs/legal e docs/architecture |
| Ownership auditor | Somente três testes novos test_build_independent_assets.py, test_release_independent_baseline.py, test_release_independent_math.py; este dossiê e log F9. Nenhum ajuste científico, expected ou tolerância pelo auditor |
| Contratos consumidos | Schemas JSON v1.0.0 existentes; RPC/Result F1/F9; contrato de URLs F8; lock oficial Pyodide 0.27.5; CycloneDX 1.6 |
| Entradas / saídas | Fontes TS/Python e dependências fixadas → wheel, app JS/CSS, Worker ESM, SW raiz, Wasm/stdlib/wheels locais, manifesto SHA256, SBOM e avisos de licença; dados completos → quatro fixtures independentes |
| Hipótese matemática | ZOH exato e DARE estabilizante; ARX LS com holdout cronológico; resposta MIMO invertível na grade e casos singulares separados; LQR negativo de estado completo e saturação explícita |
| Limite | Build estático e matemática CPython locais. Não demonstra browser real, Pyodide executado, cálculo offline, CSP em execução, benchmark browser ou PathView oficial |
| Testes de aceite | `pytest tests/oracles/ -v && npm --prefix web run build && npm --prefix web run typecheck && npm --prefix web test` |
| Fixtures / T | Sete fixtures §10.4; T-CARE-02, T-FREQ-02, T-ID-03, T-MIMO-01/02, T-PVM-01 no domínio local; T-SEC-01 e paridade Wasm pendentes |
| Dependências | F9-GOV, F1-CORE-RPC, F7-RPC-BRIDGE, F5-FML, F6-SDP e F8-TS-UI aceitos na base em seus escopos locais |
| Bloqueadores | WP-AUDIT-FIX-F7-OFFLINE-SW, WP-AUDIT-FIX-F9-WASM-GATES, G-0A/B/C/D, aceite PathView externo, revisão jurídica/vulnerabilidades |
| Base / evidência | Base remota main `7b134cd2f2f4e061408b385e2a29e65b1a0beee3`, árvore `e8e35bbefa94912da165d738dc9c1c369727ea7c`; representação local HEAD `e3ca967fd920a52674787c295fd5e8ed10a0789e`; patch final identificado no log por SHA256 |
| Risco / maturidade | Médio para embalagem local, alto para release enquanto gates abertos; `experimental`, `release_approved=false`, sem promoção stable Web |

## 2. Escopo e independência

Os produtores forneceram assets upstream reais, builds deterministas, CI A–G e quatro fixtures. O auditor recebeu FIXTURES_READY e IMPLEMENTATION_READY combinados antes de executar o aceite. A evidência de preservação dos 121 arquivos aceitos de F1–F8, schemas, exemplos e oráculos anteriores está registrada por SHA256 no log; esse freeze foi verificação única desta auditoria. Ele não se tornou um teste permanente que impediria mudanças futuras legítimas. Os três hashes originais das fixtures permanecem testes normativos permanentes.

As novas referências foram produzidas fora de `control_lab`. O auditor escreveu confrontos próprios para os problemas exatos: DARE por exponencial de bloco ZOH e solução SciPy/resíduo explícito; ARX por NumPy least-squares e recorrências separadas para todos os arrays/FIT de treino e validação; MIMO por solve/SVD/inversa na grade inteira e brentq para as três travessias; PVM por integração DOP853 de estado completo contra as fórmulas analíticas do autor, nos quatro casos C/saturação. Não há geração de expected pela produção.

`checksums.sha256` mantém suas três linhas originais e acrescenta quatro. A única alteração no teste ouro anterior é exigir inventário fechado de sete nomes; nenhuma tolerância, expected ou schema anterior foi alterado. A ausência de licença de projeto permanece NOASSERTION. O inventário CycloneDX não é clearance jurídico ou de vulnerabilidades.

### Achados e resolução

**F9-BUILD-01 — CI B em ambiente com SDP opcional.** O primeiro workflow rodava a suíte inteira em um lock que instalava Clarabel/CVXPY. O auditor executou `pytest tests/unit tests/oracles tests/integration -v`: **262 passed, 1 failed**. O teste F1 `test_rpc_multidomain_operations_dispatch_real_engines`, linha 850, exige failure na condição descrita como «sem Clarabel», enquanto o backend instalado resolve e retorna success legítimo. O teste e a ciência F1 são bytes idênticos à base. O auditor emitiu changes_requested, sem corrigir F1 nem relaxar assertion. A correção de infraestrutura solicitada separa os domínios core sem SDP opcional e full SDP disponível, com pré-condições verificadas e cobertura de todos os arquivos científicos, sem deselect/skip/xfail. Após FINAL_IMPLEMENTATION_READY, o auditor executou as duas venvs isoladas com PYTHONPATH vazio e user-site desabilitado: **core 220/220**, **SDP 112/112**, zero skip/xfail. Core confirma Clarabel/CVXPY ausentes; SDP confirma ambos presentes e backends direct/CVXPY disponíveis. Os perfis cobrem todos os 11 arquivos científicos Python preexistentes, com 68 oráculos repetidos intencionalmente nos dois domínios (332 execuções, 264 casos únicos). Nenhuma assertion ou arquivo F1–F8 foi alterado. F9-BUILD-01 resolvido. Os locks finais fixam inclusive pip e transitivos: core 21 distribuições/18 arestas ativas; SDP 34 distribuições/43 arestas, ambos pip check e verificação exaustiva de metadata aprovados.

## 3. Checklist de Handoff de 10 Itens — Apêndice E

| # | Pergunta normativa | Resposta produtor / escopo | Evidência objetiva | Auditoria F9 |
| :--- | :--- | :--- | :--- | :--- |
| **1** | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | SIM, no escopo local | Sete fixtures/schema, APIs reais nos testes do produtor, contrato URLs F8 e wheel fonte idêntica | CONFORME |
| **2** | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | SIM, no escopo local | Manifesto explicitamente não aprovado, proveniência das sete gold, gates D–G exit2 com JSON blocked, RGA singular e cache adulterado falham claramente | CONFORME |
| **3** | Testes analíticos foram escritos antes da otimização prematura? | SIM, no escopo local | Referências CARE originais, RGA/adjugata e solução PVM analíticas; sem otimização científica nova | CONFORME |
| **4** | Existe confronto independente da implementação, em vez de autorreferência? | SIM, no escopo local | Quatro cross-oracles do segundo autor, hashes upstream e schema CycloneDX oficial | CONFORME |
| **5** | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | SIM, no escopo local | 121/121 preservados na inspeção única; três gold byte iguais; só quatro adições; diff revisado | CONFORME |
| **6** | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | N/A, domínio Wasm não anunciado | Pyodide/Wasm não executado; não se anuncia aceite nesse domínio; paridade fica em WASM-GATES | N/A |
| **7** | Alterações de schema tiveram migração/versão e revisão F9? | N/A, sem mudança de schema | Nenhum schema/contrato anterior mudou; SBOM segue CycloneDX1.6 validado oficialmente | N/A |
| **8** | Logs, matrizes de fixture e resultados de benchmark foram anexados? | SIM, no escopo local | Log integral, matrizes/sinais completos, SHA de patch e assets, duas compilações; benchmark browser não alegado | CONFORME |
| **9** | Um método experimental permanece visualmente classificado como tal? | SIM, no escopo local | Manifesto experimental/releasefalse/offlinefalse; catálogo F8 preservado; G-0A..D pendentes | CONFORME |
| **10** | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | SIM, no escopo local | F9-BUILD-01 documentado; WPs Offline/Wasm, AUD-011/G-0D, licenças/vulnerabilidades pendentes; gates não verdes | CONFORME |

## 4. Registro de Ambiente, SHA e Saída de Execução

Linux x86_64 glibc 2.41; Python 3.12.14; NumPy 2.3.5; SciPy 1.17.0; pytest 9.2.0; jsonschema 4.26.0; Clarabel 0.11.1; CVXPY 1.9.3; build 1.6.1; wheel 0.48.0; setuptools 84.2.1; Node 24.22.1; TypeScript 5.8.3; esbuild 0.25.5; ruff 0.11.13; mypy 1.15.0. As dependências nativas de auditoria não são confundidas com a distribuição Wasm: Pyodide 0.27.5/Python 3.12.7, NumPy 2.0.2, SciPy 1.14.1, OpenBLAS 0.3.26, micropip 0.8.0, packaging 24.2.

[Log integral](../../architecture/audit-logs/WP-AUDIT-FIX-F9-BUILD-CI.log). As saídas incluem o aceite inicial e final, falha diagnóstica CI B, duas compilações independentes, hashes completos, clean npm ci offline em diretório vazio, verificação de cada asset/wheel/aviso, ruff/mypy/importabilidade e os bloqueios esperados D–G. O aviso anyio/pytest é depreciação; a inspeção do schema registra também depreciação de RefResolver. Nenhum skip foi usado para aprovar funcionalidade.

A inspeção independente confirmou 32 arquivos distribuídos, incluindo 11 arquivos upstream reais (36.678.144 bytes), wheel de fontes atuais, bundles ESM sem importação Node/TS residual, inventário SHA256 exaustivo e licenças extraídas sem alteração de bytes. O schema CycloneDX oficial foi obtido do repositório CycloneDX/specification no GitHub após HTTP403 de cyclonedx.org; URLs e hashes dos três schemas estão no log.

Resultados finais independentes após o último READY e pins finais:

| Evidência local | Resultado |
| :--- | :--- |
| Acceptance EXATO em core venv limpa | 68 oráculos; build 32 assets; typecheck; 46 testes Node; todos exit 0, zero skip |
| CI B core_no_sdp | 220 passed, zero skip; 21 distribuições/18 arestas; pré-condição SDP ausente |
| CI B sdp_available | 112 passed, zero skip; 34 distribuições/43 arestas; backends direct/CVXPY disponíveis |
| CI A aplicável localmente | ruff 7 arquivos; mypy 6 scripts; importabilidade; pip check em ambas venvs; todos aprovados |
| CI C complementar | Node integration/oracles 21/21, zero skip |
| Reprodução final independente | Duas compilações, manifesto idêntico e SHA/tamanho idênticos dos 32 arquivos |
| Instalação npm limpa | `npm ci --offline` em diretório vazio contendo apenas os dois arquivos package; exit 0 |
| Gates D/E/F/G | Cada comando real retorna 2 com JSON blocked por suites reais ausentes; resultado esperado, sem CI global verde |
| Integridade adicional | Cache runtime corrompido recusado antes da rede; manifesto rejeita asset adulterado/extra; 7 schemas/hash fixtures válidos |
| Supply chain e escopo | Actions com SHA40; sete jobs preservam logs; todos os arquivos científicos cobertos pela união dos perfis; fontes anteriores preservadas |

Hashes finais: wheel `6f97f0f2b8c48b8d59c0213309a3b7a9d76735a609720404374d1ba5efa4a102`; manifesto `e4d6cd88fe2df2ae6b1375aa80d2eed38b3923683dcf812fc877bacb7fe0e895`. O log assina também lock, SBOM, novas fixtures e arquivos do patch. A reprodutibilidade foi demonstrada no mesmo ambiente Python/zlib de referência. O lock nativo Python fixa todas as versões/metadados transitivos, mas ainda não contém hashes dos wheels CPython; essa limitação é explícita na documentação, sem promessa de clearance supply-chain completo.

Não houve execução do workflow no GitHub nem configuração de branch protection/rulesets nesta auditoria. A aprovação local da infraestrutura não é execução remota de CI. Não se comprovou navegador, cálculo offline após reload, sandbox/CSP, 60 FPS ou PathView oficial. Os assets locais completos são entrada para OFFLINE-SW/WASM-GATES, sem promover seus gates.

## 5. Parecer Independente da Frente F9

- **Veredito F9:** `accepted` — restrito ao escopo local desta entrega; F9-BUILD-01 corrigido e reavaliado independentemente.
- **Escopo aprovado (`acceptance_scope`):** `local_reproducible_static_build_and_independent_cpython_goldens_only`.
- **Revisor independente:** `f9-integration-qa`, agente `f9_build_auditor`, distinto dos dois produtores.
- **Commit SHA auditado:** representação local `e3ca967fd920a52674787c295fd5e8ed10a0789e` mais patch final assinado no log; base remota `7b134cd2f2f4e061408b385e2a29e65b1a0beee3`, árvore `e8e35bbefa94912da165d738dc9c1c369727ea7c`.
- **Data (UTC):** `2026-11-14`.
- **Release:** NOT_APPROVED_FOR_STABLE_WEB_RELEASE; nenhum gate promovido.
- **Fechamento:** PROJECT_STATE, orçamento, commit, push e confirmação remota reservados ao Maestro; não executados pelo auditor.
