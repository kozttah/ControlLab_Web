# Dossiê de Handoff e Auditoria F9 — `WP-AUDIT-FIX-F6-SDP`

**Fonte normativa única:** `ControlLab_Web_Documento_Diretor_v1.0.md` (`CL-DIR-001`, v1.0.0), §§6.1–6.5, 10.5, 13.8, 13.11 e Apêndices C/E.
**Template:** [`HANDOFF_TEMPLATE_APENDICE_E.md`](../../architecture/HANDOFF_TEMPLATE_APENDICE_E.md).
**Auditoria independente:** subagente `f9_audit_f6`, distinto do produtor `f6_implementation`.

## 1. Cabeçalho da Tarefa (Apêndice E)

| Campo Obrigatório | Valor / Referência |
| :--- | :--- |
| **WorkPackage ID** | `WP-AUDIT-FIX-F6-SDP` |
| **Requisito(s) R** | R-11, R-12, R-13, R-14, R-15 |
| **Achado(s) / REM vinculado(s)** | AUD-006, AUD-007, AUD-008; OBS-F9-WP10-01; REM-05 |
| **Frente F** | `f6-optimization-lmi`, fase `Audit-Remediation` |
| **Módulo / caminhos permitidos (`allowed_paths`)** | `control_lab/optimization/`, `control_lab/experimental/sdp_educational/`, `tests/unit/f6/` |
| **Contratos consumidos** | Formato canônico afim da §6.1; `Result` e `result.schema.json`; cinco dimensões de status da §6.3; fixtures F9 congeladas |
| **Entradas / saídas** | `SDPBlock`, `CanonicalSDPProblem`, `solve()`, `verify()` e descritores de backends; preservação da serialização JSON e dos contratos públicos existentes |
| **Hipótese matemática** | O problema canônico validado não muda após construção; redução PSD→LP exige diagonalidade exata; resíduo PSD usa norma espectral 2; presença de callable não prova capacidades adicionais de certificado |
| **Limite da implementação** | Evidência em CPython nativo. Backend educacional permanece experimental; não houve execução Pyodide/Wasm/browser nem liberação de backend SDP de produção Web |
| **Testes de aceite** | `pytest tests/unit/f6/ -v` (44 casos); nove sondas independentes F9; oráculos/governança (26 casos incluindo as nove sondas); T-SDP-A1/A2/A3/B1/C1/D1/D2 |
| **Fixtures** | B-SDP-A-D, B-CARE-02, B-CARE-12x3 e manifesto SHA-256 intactos; valores novos de regressão deduzidos por álgebra diagonal/determinante, sem gerar expected pela produção |
| **Dependências** | `WP-AUDIT-FIX-F1-CORE-RPC`, `ACCEPTED_BY_F9` na base remota |
| **Bloqueadores** | Nenhum dentro deste aceite CPython. Build/distribuição e paridade/gates Web continuam em `WP-AUDIT-FIX-F9-BUILD-CI` e `WP-AUDIT-FIX-F9-WASM-GATES` |
| **Evidência / PR esperado** | Base remota `2d5e8d2ad41f752849bcdcce0524515ada5cbe89`; diff de entrega F6 auditado antes do commit; log integral vinculado na Seção 4 |
| **Risco** | Médio: invariantes comuns à seleção de backend e à auditoria PSD; mitigado por testes A–D, serialização, sondas adversariais e preservação de oráculos |
| **Nível de maturidade pretendido** | Aceite `cpython_local_only`; solver educacional `experimental`; nenhuma promoção de maturidade Web nem aprovação G-0B |

**Seleção e orçamento:** primeiro WorkPackage `PENDING` com dependências aceitas, na ordem atual de `PROJECT_STATE.json`. A dispensa explícita anterior do limite diário cobria somente a rodada F7. O pedido atual literal, “Poderia fazer mais uma rodada?”, foi interpretado pelo Maestro como autorização de mais um único ciclo no mesmo contexto; esse entendimento foi informado ao usuário antes da execução. A política diária não foi alterada. O registro desta tarefa fica com o Maestro, após o parecer F9.

## 2. Entregáveis Produzidos

1. `control_lab/optimization/modeling/canonical.py`: matrizes canônicas armazenadas em bytes imutáveis e shapes em tuplas. Getters criam novas views, evitando tanto reativação de WRITEABLE quanto mudança da shape canônica via metadados de `ndarray.base`. `__slots__`, bloqueio de atribuição/exclusão e mapas recursivamente congelados protegem atributos estruturais e metadados. Getters de mapas e serialização devolvem cópias JSON independentes.
2. `control_lab/optimization/modeling/svec.py`: diagonalidade estrutural exata por padrão; `SDPBlock` usa `tol=0.0` explicitamente para decidir o fallback LP. Uma tolerância de inspeção opcional não participa da redução exata.
3. `control_lab/optimization/verification/verifier.py`: escala dos blocos PSD usa `||F0||₂ + Σ|xk|||Fk||₂`, com o termo unitário normativo. Normas de simetria e outros resíduos não foram trocadas arbitrariamente.
4. `control_lab/optimization/backends/unavailable.py` e `experimental/sdp_educational/solver.py`: registro explícito de capacidades da implementação educacional real. Callable desconhecido permanece conservador quanto a dual/certificados. O adaptador força `experimental=True`, `maturity=experimental`, `certified=False`, mesmo se um descritor tentar promovê-lo.
5. `tests/unit/f6/test_sdp_audit_remediation.py`: regressões do produtor para imutabilidade profunda, LP estruturalmente exato, norma 2 e descritores registrados; nenhuma fixture/tolerância de ouro alterada.
6. F9 acrescentou [`test_sdp_remediation_independent.py`](../../../tests/oracles/test_sdp_remediation_independent.py). As nove sondas próprias confrontam imutabilidade por entradas/getters/bases/mapas/atributos; acoplamentos não nulos de `1e-15`, `1e-30` e menor subnormal em F0/Fk; resíduos analíticos `1/101` e `7/9`; classificação perto do limiar; capacidades reais versus callable desconhecido.

**Independência matemática:** `det([[x,ε],[ε,0]]) = −ε² < 0` para ε≠0, de modo que eliminar o acoplamento não é uma redução exata, ainda que o determinante sofra underflow em float64. Para `F0=diag(100,100,−1)`, a norma espectral é 100 e a violação relativa é `1/101`. Para `F0=diag(4,−3)`, `F1=diag(1,−2)`, `x=2`, tem-se `F(x)=diag(6,−7)` e resíduo `7/(1+4+2·2)=7/9`. O limiar `psd_tol=0.008`, situado entre o antigo resíduo Frobenius e `1/101`, deve classificar o primeiro ponto como violado. Essas referências não foram obtidas executando o código auditado.

## 3. Checklist de Handoff de 10 Itens (Apêndice E)

| # | Pergunta Normativa (Apêndice E — CL-DIR-001) | Resposta Produtor | Evidência Objetiva | Auditoria F9 |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8?** | SIM | Bateria F6 valida envelopes Result/schema e contratos canônicos; serialização/round-trip preservados; alterações não mudam schemas RPC ou contrato F7/F8 | CONFORME |
| **2** | **Saída contém status, diagnósticos e proveniência, inclusive casos de falha?** | SIM | Testes A–D cobrem cinco dimensões de status, fake certificates, problemas infactíveis/ilimitados; LP não diagonal retorna SOLVER_UNAVAILABLE/unsupported_psd; solver educacional não se anuncia certificado automaticamente | CONFORME |
| **3** | **Testes analíticos foram escritos antes da otimização prematura?** | SIM | Fixtures A–D analíticas preexistentes preservadas; novas referências por determinante/autovalores diagonais; nenhuma nova heurística de otimização introduzida | CONFORME |
| **4** | **Existe confronto independente da implementação, em vez de autorreferência?** | SIM | Nove sondas F9 próprias, com números analíticos explícitos, confrontadas com o código produtor; bateria A–D também compara backends Clarabel direto/CVXPY e controles com Lyapunov/espectro | CONFORME |
| **5** | **O PR respeita ownership e não modificou mocks/expected values para esconder defeito?** | SIM | Seis arquivos F6 exclusivamente em allowed_paths; F9 somente sonda/dossiê/log; 16 arquivos protegidos de fixtures/schemas/oráculos anteriores com SHA-256 idêntico; nenhum expected/tolerância anterior alterado | CONFORME |
| **6** | **O mesmo teste funciona em CPython e Pyodide no domínio anunciado?** | N/A | Domínio anunciado deste aceite é exclusivamente CPython local. Paridade real Pyodide/Wasm e execução browser permanecem em F9-WASM-GATES; não foram simuladas nem declaradas comprovadas | N/A |
| **7** | **Alterações de schema tiveram migração/versão e revisão F9?** | N/A | Nenhum JSON Schema alterado. Novo parâmetro Python opcional solver_capabilities preserva chamadas anteriores; revisão independente verifica descritores sem mudar contratos serializados | N/A |
| **8** | **Logs, matrizes de fixture e resultados de benchmark foram anexados?** | SIM | Log integral e ambiente na Seção 4; matrizes completas mantidas em B-SDP-A-D e novas matrizes literais nas sondas. Durações são dos testes locais; não se alegam benchmarks Wasm ou latência de produto | CONFORME |
| **9** | **Um método experimental permanece visualmente classificado como tal?** | SIM | Descritor educacional força experimental/certified=False; testes impedem promoção por descriptor. Não houve promoção Web; rótulos nativos preexistentes dos backends de produção não foram usados para aprovar G-0B | CONFORME |
| **10** | **Qualquer limitação conhecida tem issue e mensagens de falha adequadas?** | SIM | Build/paridade/gates rastreados em F9-BUILD-CI e F9-WASM-GATES; weak infeasibility sem certificado continua inconclusive; unsupported_psd e ausência de solver têm razões estruturadas. WPs são registros de acompanhamento do projeto | CONFORME |

## 4. Registro de Ambiente, SHA e Saída de Execução

- **Commit SHA remoto base auditado:** `2d5e8d2ad41f752849bcdcce0524515ada5cbe89` + diff F6 desta entrega.
- **Tree SHA remoto base:** `4b42a14f5fee0dd8ca7381bf8e3837e9024d7afb`.
- **`git rev-parse HEAD` local:** `01ee2256bcd6603e832d442a78cdc1e98ac8b23e`, baseline de trabalho correspondente ao snapshot remoto, sem representar a história remota real.
- **Data (UTC):** `2026-11-14`.
- **Ambiente:** Linux `6.18.57`, x86_64, glibc `2.41`; Python `3.12.14`; NumPy `2.3.5`; SciPy `1.17.0`; pytest `9.2.0`; jsonschema `4.26.0`; Clarabel `0.11.1`; CVXPY `1.9.3`; Node `v24.22.1` (não requerido por este aceite F6). Browser/Pyodide/PathView não executados.
- **Dependências:** Clarabel/CVXPY foram instalados no runtime pelo Maestro, sem mudança de pyproject/lockfiles versionados; inventário exato consta no log.
- **Saída integral dos comandos e exit codes:** [`WP-AUDIT-FIX-F6-SDP.log`](../../architecture/audit-logs/WP-AUDIT-FIX-F6-SDP.log).

**Sincronização:** o terminal continua sem a autenticação do Git, enquanto o conector GitHub está autorizado. O Maestro verificou os hashes Git dos 160 arquivos texto locais contra a main remota acima, sem divergências. A publicação usará a árvore remota como base, parent no SHA remoto e atualização de main condicionada ao SHA esperado, sem force, preservando binários documentais não baixados. Isso é sincronização/publicação pelo conector, não evidência de execução literal de git pull/git push autenticados no terminal.

| Comando / verificação independente F9 | Resultado |
| :--- | :--- |
| `pytest tests/unit/f6/ -v` | 44 passed, 0 fail/skip; exit 0; 3.57 s |
| `python3 -m pytest tests/oracles/ tests/integration/ -v` | 26 passed, incluindo nove sondas F9; exit 0; 4.01 s |
| `python3 -m pytest tests/oracles/test_sdp_remediation_independent.py -v` | Nove sondas novamente aprovadas após acrescentar classificação perto do limiar; exit 0; 0.81 s |
| `python3 scripts/verify_fixtures.py` | 10 schemas, 3 fixtures SHA-256 e 4 exemplos aprovados; exit 0 |
| `git diff --check` | Sem erros de whitespace |
| Diff dos arquivos protegidos | Vazio: fixtures, schemas e oráculos anteriores intactos |
| Hashes dos 16 arquivos protegidos | Iguais aos hashes capturados antes da implementação; lista integral no log |

Os testes pytest emitiram somente um warning de depreciação do plugin externo anyio (`CallSpec2`), sem erro ou falha de teste. Não há skips/xfails usados para aceitar a funcionalidade.

**Rastreabilidade normativa:** `test_t_sdp_a1_feasible_boundary_all_backends` → A1; testes A2 de Farkas e ausência de certificado → A2; direção recessiva/inconclusive → A3; PSD 2×2 de fronteira → B1; Slater e dualidade → C1; estabilização/recuperação/espectro → D1; BRL H∞ com planta equivalente e γ → D2. A suíte educacional também executa níveis A–D, mantendo a maturidade experimental. Nenhuma aprovação desses casos nativos libera automaticamente SDP Wasm.

**Integridade principal congelada:**

| Arquivo | SHA-256 antes e depois |
| :--- | :--- |
| `contracts/fixtures/B-CARE-02.json` | `f08f9fe28302c1704554460eb660a00c2911b75272358872672bbbb5068e516f` |
| `contracts/fixtures/B-CARE-12x3.json` | `0bacb2e43ebfb4a7803cd223de8c219deda4876a180175af30f20cd07f8686a4` |
| `contracts/fixtures/B-SDP-A-D.json` | `4377341309c5df1df3c814e3f1a3d38ea3783232c3f4ae84e201f829e5f33076` |
| `contracts/fixtures/checksums.sha256` | `df4b383e36fd191457914e8c29b880c841d497248ccf4ab821433038bd47ce56` |
| `tests/oracles/test_golden_fixtures.py` | `9bbfffe8c45f2cd9b6ab66172dbad25dd948f4b468354c9b6d2ace52ac2846e4` |
| `tests/oracles/rpc_bridge_cpython.test.mjs` | `2999274053a4844030d58c5bcc652484eb9ea0eb704194e1b868fc14b44b8d3d` |

**Ownership:** cinco arquivos de implementação F6 alterados e um arquivo de regressões F6 criado; todos dentro de allowed_paths. F9 criou somente a sonda independente, este dossiê e o log. PROJECT_STATE e orçamento ficam sob fechamento do Maestro. As matrizes/valores/tolerâncias das fixtures e os contratos originais não foram modificados.

## 5. Parecer Independente da Frente F9

- **Veredito F9:** `accepted`
- **Escopo aprovado (`acceptance_scope`):** `cpython_local_only`.
- **Revisor independente:** `f9-integration-qa` — subagente `f9_audit_f6`, distinto da implementação F6.
- **Commit SHA auditado:** base remota `2d5e8d2ad41f752849bcdcce0524515ada5cbe89` + diff F6 auditado; baseline local `01ee2256bcd6603e832d442a78cdc1e98ac8b23e`. O Maestro criará o commit de publicação depois deste parecer.
- **Data (UTC):** `2026-11-14`.
- **Testes e artefatos validados independentemente pela F9:** 44 testes F6; 26 testes de oráculos/governança, incluindo nove sondas próprias; verificação de fixtures/schemas/exemplos; inspeção de imutabilidade/seleção LP/normalização/capacidades; hashes protegidos e ownership.
- **Pendências / Bloqueadores remanescentes:** `WP-AUDIT-FIX-F9-BUILD-CI` e `WP-AUDIT-FIX-F9-WASM-GATES`; solver didático permanece experimental. G-0A/G-0B/G-0C/G-0D continuam abertos, e mantém-se `NOT_APPROVED_FOR_STABLE_WEB_RELEASE`.

O aceite fecha as remediações desta entrega no domínio CPython demonstrado; não certifica automaticamente cada resultado de solver, não substitui o verificador independente nem comprova portabilidade WebAssembly.
