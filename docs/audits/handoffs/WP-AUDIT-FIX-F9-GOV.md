# Dossiê de Handoff e Auditoria F9 — `WP-AUDIT-FIX-F9-GOV`

**Template normativo:** [`HANDOFF_TEMPLATE_APENDICE_E.md`](../../architecture/HANDOFF_TEMPLATE_APENDICE_E.md)  
**Fonte normativa única:** [`ControlLab_Web_Documento_Diretor_v1.0.md`](../../../ControlLab_Web_Documento_Diretor_v1.0.md) (`CL-DIR-001`, v1.0.0 — Seções 10.5, 13.2, 13.11, 14.1, 15.1–15.3 e Apêndice E)

---

## 1. Cabeçalho da Tarefa (Apêndice E)

| Campo Obrigatório | Valor / Referência |
| :--- | :--- |
| **WorkPackage ID** | `WP-AUDIT-FIX-F9-GOV` |
| **Requisito(s) R** | `R-23`, `R-24` |
| **Achado(s) / REM vinculado(s)** | `AUD-012`, `AUD-013`, `AUD-015` (`REM-01`, `REM-03`) |
| **Frente F** | `f9-integration-qa` (Fase `Audit-Remediation`) |
| **Módulo / caminhos permitidos (`allowed_paths`)** | `CODEOWNERS`, `scripts/`, `tests/oracles/`, `tests/integration/`, `docs/audits/`, `docs/architecture/` *(nota: `PROJECT_STATE.json` preservado intacto nesta entrega para atualização pelo Maestro após auditoria da Etapa 4)* |
| **Contratos consumidos** | `CL-DIR-001` §13.2 (ownership), §13.11 (independência F9), §15.1–15.2 (Job C / branch protection), Apêndice E, `web/tsconfig.json`, `PROJECT_STATE.json` |
| **Entradas / saídas** | Entrada: árvore rastreada (`git ls-files`), `PROJECT_STATE.json`, `web/tsconfig.json`, `argv` (`--scope all\|f7\|f8`); Saída: `CODEOWNERS` completo, `scripts/run_web_tests.mjs` fail-closed (`parseCliArgs`, `resolveTscCommand`, `runWebTests`), template/matriz/dossiê Apêndice E e suítes `tests/integration/`. |
| **Hipótese matemática** | Governança determinística de ownership (`last-match-wins` com exclusividade `@f9-integration-qa` em `/contracts/fixtures/` e `/contracts/examples/`) e runner de aceite **fail-closed** (nunca aprova estágio omitido por ausência de compilador `tsc` ou diretórios de teste vazios); oráculos matemáticos e fixtures ouro preservados sem alteração. |
| **Limite da implementação** | (1) `CODEOWNERS` estabelece matriz normativa completa no repositório, porém enforcement remoto depende de Branch Protection/Ruleset e identidades válidas de equipe no GitHub (`AUD-012`); (2) `tsc` não está instalado nesta VM (`web/node_modules` não provisionado neste WP para respeitar isolamento de `web/package.json`), logo `npm --prefix web test` falha fechado como esperado e os fluxos verdes do runner foram validados com `tsc` mock isolado em diretório temporário; (3) os 5 erros TS de `AUD-014` em `F7`/`F8` e os WPs subsequentes permanecem abertos nos respectivos WPs (`WP-AUDIT-FIX-F7-RPC-BRIDGE`, `WP-AUDIT-FIX-F8-TS-UI`, `WP-AUDIT-FIX-F9-BUILD-CI`). |
| **Testes de aceite** | `pytest tests/oracles/ tests/integration/ -v && node --test tests/integration/*.test.mjs`; regressão obrigatória: `test_acceptance_runner_requires_tsc_and_tests`, `test_codeowners_covers_all_tracked_paths_and_fixtures_exclusive_to_f9`, `test_project_state_governance_and_handoff_invariants`, `test_appendix_e_handoff_template_and_evidence_matrix`, `test_accepted_dossier_validator_rejects_pending_and_template_false_positives`. |
| **Fixtures** | Oráculos preservados em `contracts/fixtures/`: `B-CARE-02.json`, `B-CARE-12x3.json`, `B-SDP-A-D.json`, `checksums.sha256` (validados via `tests/oracles/test_golden_fixtures.py`). |
| **Dependências** | `[]` (nenhuma dependência de WP anterior; é o WP raiz da remediação). |
| **Bloqueadores** | Nenhum para este WP de governança/runner. Desbloqueia `WP-AUDIT-FIX-F1-CORE-RPC`, `WP-AUDIT-FIX-F7-RPC-BRIDGE` e `WP-AUDIT-FIX-F8-TS-UI` após auditoria F9 da Etapa 4. |
| **Evidência / PR esperado** | Commit base `f1b9408d246ea2afab6375fe4db4a991fb1f60ab`; arquivos alterados/criados estritamente em `allowed_paths`; logs integrais de `pytest tests/oracles/ tests/integration/ -v`, `node --test tests/integration/*.test.mjs`, `python3 scripts/verify_fixtures.py` e `npm --prefix web test`. |
| **Risco** | Baixo/Médio — risco residual exclusivamente operacional caso branch protection ou handles de equipe no GitHub não estejam configurados no repositório remoto (`AUD-012`), mitigado por checagem estrutural em CI (`test_governance_and_ownership.py`). |
| **Nível de maturidade pretendido** | `stable` no escopo de governança/runner local (`CPython` + `Node 24`), sem declarar `stable` Web/Wasm para o produto (que permanece `NOT_APPROVED_FOR_STABLE_WEB_RELEASE` até fechamento de `G-0A`..`G-0D`). |

---

## 2. Entregáveis Produzidos

1. [`CODEOWNERS`](../../../CODEOWNERS) (`AUD-012`):
   - Cobertura integral de `F1`–`F8` e seus diretórios de testes unitários `/tests/unit/f1/`..`/tests/unit/f8/`.
   - Precedência *last-match-wins*: `/contracts/` e `/contracts/schemas/` (`@f9-integration-qa @f1-core-io`) precedem `/contracts/fixtures/` e `/contracts/examples/` (`@f9-integration-qa`), assegurando exclusividade absoluta da `F9` sobre fixtures ouro e exemplos.
   - Cobertura explícita de todas as suítes independentes `F9`, `scripts/`, `pyproject.toml`, `/.github/`, `/.agents/`, configurações compartilhadas `web/` (`package.json`, `package-lock.json`, `tsconfig.json`, `node-builtins.d.ts`), `docs/`, `PROJECT_STATE.json`, `AGENTS.md`, `CODEOWNERS`, `README.md`, `setup_repo.py`, `.gitignore`, `ControlLab_Web_Documento_Diretor_*` e `controllab_v1_assets/`.
   - Comentário normativo explícito documentando precedência *last-match-wins* e dependência de *branch protection* + equipes válidas no servidor GitHub (`AUD-012`).
2. [`scripts/run_web_tests.mjs`](../../../scripts/run_web_tests.mjs) (`AUD-015`):
   - Runner fail-closed com suporte exclusivo a `--scope all` (padrão), `--scope f7` e `--scope f8`; qualquer argumento, flag ou escopo inválido encerra com código != 0 (zero backdoors ou flags de skip).
   - Ausência de `tsc` (`web/node_modules/.bin/tsc`, `node_modules/.bin/tsc` ou `PATH`) falha explicitamente com `[typecheck] FAIL` em `stderr` e código != 0.
   - `--scope all` exige `web/tsconfig.json` e pelo menos 1 arquivo de teste em **cada** diretório obrigatório (`tests/unit/f7` e `tests/unit/f8`); `--scope f7` e `--scope f8` aplicam as flags estritas exatas de `web/tsconfig.json` aos arquivos do respectivo escopo (incluindo `web/node-builtins.d.ts`) sem falhar nos arquivos F8 não corrigidos de `AUD-014`; ausência de arquivos TS ou diretório de teste vazio/ausente falha com código != 0.
   - Registra linhas separadas `[typecheck] PASS|FAIL` e `[unit-tests] PASS|FAIL`; exporta `parseCliArgs`, `resolveTscCommand` e `runWebTests` com guarda `isMainModule` (`pathToFileURL(path.resolve(process.argv[1])).href`).
3. [`docs/architecture/HANDOFF_TEMPLATE_APENDICE_E.md`](../../architecture/HANDOFF_TEMPLATE_APENDICE_E.md) e [`docs/audits/MATRIZ_EVIDENCIAS_WPS_GATES.md`](../MATRIZ_EVIDENCIAS_WPS_GATES.md) (`AUD-013` / `REM-01`):
   - Formulário normativo completo do Apêndice E (cabeçalho, exatos 10 itens, 4 vereditos F9 e regra proibindo `ACCEPTED_BY_F9` ou `stable` Web sem dossiê em disco e evidência de ambiente/SHA).
   - Matriz histórica completa (`cfa5270`..`f1b9408`) para `WP-00`..`WP-10`, escopo efetivamente comprovado, decisões pós-auditoria e bloqueadores dos Gates `G-0A`..`G-0D`.
4. [`tests/integration/test_run_web_tests_fail_closed.test.mjs`](../../../tests/integration/test_run_web_tests_fail_closed.test.mjs) e [`tests/integration/test_governance_and_ownership.py`](../../../tests/integration/test_governance_and_ownership.py):
   - Testes independentes cobrindo `test_acceptance_runner_requires_tsc_and_tests`, parser fiel às regras glob/last-match-wins do GitHub `CODEOWNERS` sobre 100% de `git ls-files` e caminhos futuros, invariantes de `PROJECT_STATE.json` e integridade dos documentos do Apêndice E.

---

## 3. Checklist de Handoff de 10 Itens (Apêndice E — `CL-DIR-001`)

| # | Pergunta Normativa (Apêndice E — `CL-DIR-001`) | Resposta (`SIM` / `NÃO` / `PARCIAL` / `N/A`) | Evidência Objetiva (arquivo, linha, teste, comando, SHA) | Auditoria F9 |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8?** | `SIM` | API pública de `scripts/run_web_tests.mjs` (`parseCliArgs`, `resolveTscCommand`, `runWebTests`) e CLI `--scope all\|f7\|f8` alinhada à arbitragem §3.2 de `PARECER_F9_SOBRE_AUDITORIA_EXTERNA.md` e testada em `tests/integration/test_run_web_tests_fail_closed.test.mjs`. Contratos JSON e exemplos validados por `tests/oracles/test_golden_fixtures.py` (12 passed). | `CONFORME` |
| **2** | **Saída contém status, diagnósticos e proveniência, inclusive casos de falha?** | `SIM` | `runWebTests` emite linhas explícitas `[typecheck] PASS\|FAIL` e `[unit-tests] PASS\|FAIL` e retorna `{ exitCode, scope, typecheckStatus, unitTestsStatus, tsFiles, testFiles, stdout, stderr }` cobrindo ausência de `tsc`, argumentos inválidos, pastas vazias e falhas de compilação/teste. | `CONFORME` |
| **3** | **Testes analíticos foram escritos antes da otimização prematura?** | `SIM` | Especificações normativas de comportamento (regras glob/last-match-wins do GitHub `CODEOWNERS`, fail-closed do runner sem `tsc`, invariantes topológicas/ciclo de vida e validação estrita de dossiê `ACCEPTED_BY_F9` sem falso positivo de template via `_validate_accepted_dossier` + `test_accepted_dossier_validator_rejects_pending_and_template_false_positives`) formalizadas em `tests/integration/test_governance_and_ownership.py` e `tests/integration/test_run_web_tests_fail_closed.test.mjs`. | `CONFORME` |
| **4** | **Existe confronto independente da implementação, em vez de autorreferência?** | `SIM` | `test_codeowners_covers_all_tracked_paths_and_fixtures_exclusive_to_f9` confronta `CODEOWNERS` contra mapa normativo independente da Seção 13.2 e `git ls-files`; `test_acceptance_runner_requires_tsc_and_tests` executa o CLI real `scripts/run_web_tests.mjs` como subprocesso isolado sem `tsc` e com `tsc` mock verificando os argumentos exatos passados ao compilador; `test_accepted_dossier_validator_rejects_pending_and_template_false_positives` testa casos negativos sintéticos; `tests/oracles/test_golden_fixtures.py` permanece inalterado (12 passed). | `CONFORME` |
| **5** | **O PR respeita ownership e não modificou mocks/expected values para esconder defeito?** | `SIM` | Alterações estritamente restritas a `CODEOWNERS`, `scripts/run_web_tests.mjs`, `tests/integration/`, `docs/audits/` e `docs/architecture/` (conferido via `git status --short`). Zero modificações em `control_lab/`, `web/`, `tests/unit/f1..f8/`, `contracts/fixtures/`, `tests/oracles/test_golden_fixtures.py` ou `PROJECT_STATE.json`. | `CONFORME` |
| **6** | **O mesmo teste funciona em CPython e Pyodide no domínio anunciado?** | `N/A` | Escopo exclusivo de governança de repositório, `CODEOWNERS`, documentação do Apêndice E e runner Node/TypeScript em ambiente de build/CI (`CPython 3.11.2` + `Node v24.22.2`); não produz código científico destinado ao runtime Pyodide/Wasm. | `CONFORME` |
| **7** | **Alterações de schema tiveram migração/versão e revisão F9?** | `N/A` | Nenhuma alteração em `contracts/schemas/`, `contracts/fixtures/` ou `contracts/examples/`. Todos os 10 schemas Draft 2020-12 e checksums SHA-256 seguem validados sem alteração em `tests/oracles/test_golden_fixtures.py`. | `CONFORME` |
| **8** | **Logs, matrizes de fixture e resultados de benchmark foram anexados?** | `SIM` | Matriz histórica e status dos gates registrados em `docs/audits/MATRIZ_EVIDENCIAS_WPS_GATES.md`; registro completo de ambiente, versões, `HEAD` (`f1b9408d246ea2afab6375fe4db4a991fb1f60ab`), `git status --short` e saídas integrais desta execução do produtor anexados literalmente na Seção 4 deste dossiê; benchmarks numéricos Wasm permanecem bloqueados em `WP-AUDIT-FIX-F9-BUILD-CI`/`WP-AUDIT-FIX-F9-WASM-GATES` (`G-0A`). | `CONFORME` |
| **9** | **Um método experimental permanece visualmente classificado como tal?** | `SIM` | `MATRIZ_EVIDENCIAS_WPS_GATES.md` e `HANDOFF_TEMPLATE_APENDICE_E.md` mantêm `WP-10-F6-SDP-EDUCATIONAL-SOLVER` com `maturity: experimental`, `WP-05` com `BLOCKED_BY_GATE` (`G-0D`) e o veredito global `NOT_APPROVED_FOR_STABLE_WEB_RELEASE` sem nenhuma promoção `stable` Web indevida. | `CONFORME` |
| **10** | **Qualquer limitação conhecida tem issue e mensagens de falha adequadas?** | `SIM` | Todas as limitações estão explícitas e com falhas claras: (a) ausência de `tsc` na VM produz `[typecheck] FAIL` com código `!= 0` (em vez de aviso silencioso); (b) dependência de *branch protection* e equipes GitHub documentada no cabeçalho de `CODEOWNERS` (`AUD-012`); (c) erros TS de `AUD-014` e ausência de artefatos Wasm/PathView permanecem mapeados nos WPs `WP-AUDIT-FIX-F7-*`, `WP-AUDIT-FIX-F8-*`, `WP-AUDIT-FIX-F9-BUILD-CI` e `WP-AUDIT-FIX-F9-WASM-GATES`. | `CONFORME` |

---

## 4. Registro de Ambiente, SHA e Saída de Execução

- **Commit SHA base (`git rev-parse HEAD`):** `f1b9408d246ea2afab6375fe4db4a991fb1f60ab`
- **Data/hora da execução do produtor (UTC):** `2026-11-14T13:07:06Z`
- **Sistema Operacional / Arquitetura:** `Linux sandbox 6.12.105+ #1 SMP Sat Sep 19 19:37:41 UTC 2026 x86_64 GNU/Linux`
- **Toolchain observada:**
  - `Python`: `3.11.2` (`/home/antigravity/.venv_controllab/bin/python`)
  - `pytest`: `9.2.0`
  - `numpy`: `2.4.6`
  - `scipy`: `1.17.1`
  - `jsonschema`: `4.26.0`
  - `Node.js`: `v24.22.2` (`/usr/local/bin/node`)
  - `npm`: `11.21.2` (`/usr/local/bin/npm`)
  - `tsc`: ausente nesta VM (`web/node_modules/` não instalado conforme restrição do WP; verificado comportamento real fail-closed sem `tsc` + suíte isolada com `tsc` mock)

- **Escopo Git (`git rev-parse HEAD` + `git status --short`):**

```text
f1b9408d246ea2afab6375fe4db4a991fb1f60ab
 M CODEOWNERS
 M scripts/run_web_tests.mjs
?? docs/architecture/
?? docs/audits/MATRIZ_EVIDENCIAS_WPS_GATES.md
?? docs/audits/handoffs/
?? tests/integration/
```

- **Execução 1 — `pytest tests/oracles/ tests/integration/ -v`:**

```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0 -- /home/antigravity/.venv_controllab/bin/python
cachedir: .pytest_cache
rootdir: /home/antigravity/kozttah/ControlLab_Web
configfile: pyproject.toml
collecting ... collected 17 items

tests/oracles/test_golden_fixtures.py::test_pyproject_toml_structure PASSED [  5%]
tests/oracles/test_golden_fixtures.py::test_all_expected_schemas_exist_and_are_valid PASSED [ 11%]
tests/oracles/test_golden_fixtures.py::test_normative_examples_validate[rpc_request_lqr.json-rpc_request.schema.json] PASSED [ 17%]
tests/oracles/test_golden_fixtures.py::test_normative_examples_validate[rpc_response_lqr.json-rpc_response.schema.json] PASSED [ 23%]
tests/oracles/test_golden_fixtures.py::test_normative_examples_validate[statespace_example.json-state_space.schema.json] PASSED [ 29%]
tests/oracles/test_golden_fixtures.py::test_normative_examples_validate[pvm_skeleton.json-pvm.schema.json] PASSED [ 35%]
tests/oracles/test_golden_fixtures.py::test_rpc_response_rejects_illustrative_strings_and_invalid_errors PASSED [ 41%]
tests/oracles/test_golden_fixtures.py::test_controller_ts_and_manifest_schemas_positive_and_negative PASSED [ 47%]
tests/oracles/test_golden_fixtures.py::test_golden_fixtures_checksums_and_schema PASSED [ 52%]
tests/oracles/test_golden_fixtures.py::test_oracle_b_care_02_analytical PASSED [ 58%]
tests/oracles/test_golden_fixtures.py::test_oracle_b_care_12x3_numerical PASSED [ 64%]
tests/oracles/test_golden_fixtures.py::test_oracle_b_sdp_levels_a_to_d PASSED [ 70%]
tests/integration/test_governance_and_ownership.py::test_codeowners_covers_all_tracked_paths_and_fixtures_exclusive_to_f9 PASSED [ 76%]
tests/integration/test_governance_and_ownership.py::test_project_state_governance_and_handoff_invariants PASSED [ 82%]
tests/integration/test_governance_and_ownership.py::test_appendix_e_handoff_template_and_evidence_matrix PASSED [ 88%]
tests/integration/test_governance_and_ownership.py::test_accepted_dossier_validator_rejects_pending_and_template_false_positives PASSED [ 94%]
tests/integration/test_governance_and_ownership.py::test_acceptance_runner_requires_tsc_and_tests PASSED [100%]

============================== 17 passed in 3.53s ==============================
```

- **Execução 2 — `node --test tests/integration/*.test.mjs`:**

```text
▶ test_acceptance_runner_requires_tsc_and_tests
  ✔ parseCliArgs valida escopos e rejeita flags/argumentos inválidos (1.44793ms)
  ✔ CLI real falha fechado sem tsc no PATH (sem argumentos, --scope all, --scope f7, --scope f8) (543.554006ms)
  ✔ CLI real rejeita escopos e flags inválidas com código != 0 (301.272068ms)
  ✔ runWebTests falha com código != 0 para pasta de teste vazia/ausente, falta de TS ou falta de tsconfig (541.843091ms)
  ✔ runWebTests com tsc mock, TS válido e .test.mjs válido retorna 0 e registra [typecheck] PASS e [unit-tests] PASS (893.026418ms)
  ✔ falha de tsc interrompe antes dos testes unitários e falha de unitário reporta [typecheck] PASS + [unit-tests] FAIL (389.87154ms)
  ✔ resolveTscCommand respeita precedência web/node_modules/.bin -> node_modules/.bin -> PATH -> null (61.957571ms)
✔ test_acceptance_runner_requires_tsc_and_tests (2735.65547ms)
ℹ tests 8
ℹ suites 0
ℹ pass 8
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 2831.626608
```

- **Execução 3 — `python3 scripts/verify_fixtures.py`:**

```text
[F9-VERIFY] 10 schemas JSON Draft 2020-12 válidos.
[F9-VERIFY] Fixture B-CARE-02.json: SHA-256 OK + golden_fixture.schema.json OK.
[F9-VERIFY] Fixture B-CARE-12x3.json: SHA-256 OK + golden_fixture.schema.json OK.
[F9-VERIFY] Fixture B-SDP-A-D.json: SHA-256 OK + golden_fixture.schema.json OK.
[F9-VERIFY] Exemplo rpc_request_lqr.json validado contra rpc_request.schema.json.
[F9-VERIFY] Exemplo rpc_response_lqr.json validado contra rpc_response.schema.json.
[F9-VERIFY] Exemplo statespace_example.json validado contra state_space.schema.json.
[F9-VERIFY] Exemplo pvm_skeleton.json validado contra pvm.schema.json.
```

- **Execução 4 — `npm --prefix web test` (confirmação fail-closed sem `tsc`):**

```text
> controllab-web@1.0.0 test
> node ../scripts/run_web_tests.mjs

[typecheck] FAIL: tsc não encontrado em web/node_modules/.bin/tsc, node_modules/.bin/tsc ou PATH (escopo 'all', 21 arquivo(s) TS).
[unit-tests] FAIL: execução bloqueada (fail-closed) porque o compilador TypeScript está ausente.
EXIT_CODE_NPM_TEST=1
```

- **Reauditoria Independente F9 (`2026-11-14T13:09:10Z` UTC — Etapa 4 final):**
  - Isolamento verificado: `git diff -- contracts/ tests/oracles/ PROJECT_STATE.json control_lab/ web/ tests/unit/` vazio (0 alterações fora de `allowed_paths`).
  - `/home/antigravity/.venv_controllab/bin/pytest tests/oracles/ tests/integration/ -v`: `17 passed in 4.77s` (inclui `test_accepted_dossier_validator_rejects_pending_and_template_false_positives` e `test_appendix_e_handoff_template_and_evidence_matrix`).
  - `node --test tests/integration/*.test.mjs`: `8 passed, 0 failed, 0 skipped` (`3681.97ms`).
  - `/home/antigravity/.venv_controllab/bin/python3 scripts/verify_fixtures.py`: `10 schemas JSON Draft 2020-12 válidos`, `3` fixtures ouro (`B-CARE-02.json`, `B-CARE-12x3.json`, `B-SDP-A-D.json`) SHA-256 + schema OK, `4` exemplos validados.
  - `npm --prefix web test`: `EXIT_CODE_NPM_TEST=1`, `[typecheck] FAIL` e `[unit-tests] FAIL` confirmados ao vivo sem `tsc` na VM.

---

## 5. Parecer Independente da Frente F9

- **Veredito F9 (`accepted` | `changes_requested` | `blocked_by_gate` | `rejected_with_evidence`):** `accepted`
- **Escopo aprovado (`acceptance_scope`):** `governance_ci_runner_local`
- **Revisor independente:** `f9-integration-qa`
- **Commit SHA auditado:** `f1b9408d246ea2afab6375fe4db4a991fb1f60ab`
- **Data (UTC):** `2026-11-14`
- **Testes e artefatos validados independentemente pela F9:** `CODEOWNERS` (`AUD-012`), `scripts/run_web_tests.mjs` (`AUD-015`), `tests/integration/test_run_web_tests_fail_closed.test.mjs` (`8 passed`), `tests/integration/test_governance_and_ownership.py` (`5 passed`, incluindo `_validate_accepted_dossier` e `test_accepted_dossier_validator_rejects_pending_and_template_false_positives`), `docs/architecture/HANDOFF_TEMPLATE_APENDICE_E.md`, `docs/audits/MATRIZ_EVIDENCIAS_WPS_GATES.md`, `tests/oracles/test_golden_fixtures.py` (`12 passed`), `scripts/verify_fixtures.py`, `npm --prefix web test` (`exit=1`, fail-closed sem `tsc`).
- **Pendências / Bloqueadores remanescentes:** Nenhum bloqueador aberto dentro do escopo de `WP-AUDIT-FIX-F9-GOV`. Permanecem abertas apenas as dependências operacionais e entregas subsequentes já mapeadas no plano de remediação: (1) configuração remota de Branch Protection / Ruleset e identidades de equipe no repositório GitHub para enforcement no servidor do `CODEOWNERS` (`AUD-012`); (2) provisão de `tsc` e execução integral de typecheck/build nos WPs `WP-AUDIT-FIX-F7-RPC-BRIDGE`, `WP-AUDIT-FIX-F8-TS-UI` e `WP-AUDIT-FIX-F9-BUILD-CI` (`AUD-014`, `AUD-003`); e (3) remediações científicas/Web em `WP-AUDIT-FIX-F1-CORE-RPC`..`WP-AUDIT-FIX-F9-WASM-GATES` para fechamento dos Gates `G-0A`..`G-0D` e eventual promoção de maturidade Web (mantido `NOT_APPROVED_FOR_STABLE_WEB_RELEASE`).
