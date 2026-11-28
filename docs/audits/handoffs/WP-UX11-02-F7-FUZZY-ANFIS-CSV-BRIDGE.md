# Handoff e Parecer F9 — `WP-UX11-02-F7-FUZZY-ANFIS-CSV-BRIDGE`

- **WorkPackage**: `WP-UX11-02-F7-FUZZY-ANFIS-CSV-BRIDGE`
- **Frente Produtora**: `F7 (f7-worker-bridge)` — Contrato RPC Python/TypeScript e bridge de worker para ANFIS multi-I/O (`n_mfs` e `mf_type` por entrada, `y`/`y_val` 1D ou 2D, `output_names`, `X_val`, `early_stopping_patience`, `seed`, `rcond`) e avaliação de superfícies Fuzzy `N × M` (`input_axes`, `fixed_inputs`, `output_name`)
- **Commit Base**: `3eb555a8e377929a9dc3ffd01ef5d602194d6877`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-02`, `R-13`, `R-20`, Seções 13.1, 13.2, 13.11 e Apêndice E), `CL-UX-DIR-001 v1.0.0` (Seção 9.4), testes normativos `T-RPC-01`, `T-ANFIS-01`
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-28`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Verificação via `git status --short` e `git diff --stat` confirmou aderência estrita aos `allowed_paths` do WorkPackage (`control_lab/core/rpc.py`, `web/bridge/client.ts`, `web/bridge/protocol.ts`, `web/worker/pyodide_worker.ts`, `tests/unit/f1/test_rpc_anfis.py`, `tests/unit/f7/`), além do alinhamento prévio de metadados pendentes do WP em `PROJECT_STATE.json` realizado pelo orquestrador. ZERO alterações em `contracts/`, `tests/oracles/` ou outras frentes.

| Artefato Auditado | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/core/rpc.py` | `a087ff143e60448c01aee6ccd637890c7aa561d9884aac0b9f73a67499575caf` | Extensão retrocompatível de `_handle_fuzzy` para `fuzzy.fit_anfis` (`y`/`y_val` 1D ou 2D, `mf_type` string ou sequência, `output_names`, `X_val`, `early_stopping_patience`, `seed`, `rcond` com validação tipada rejeitando `bool` e dimensões inválidas) e `fuzzy.evaluate_surface` (`output_name: str | None`). |
| `web/bridge/protocol.ts` | `005dd1ad6ad844bd9ad7ec944e14e27b0de75b5ff42a812d50d8d39432c22597` | Definição dos tipos estritos `FuzzySystemRef`, `FuzzyFitAnfisPayload` e `FuzzyEvaluateSurfacePayload` em conformidade com `erasableSyntaxOnly` e `verbatimModuleSyntax`. |
| `web/bridge/client.ts` | `b011ed0bdac32ded82ebeb39e5a8ba2e76ef644e90376603e7087a0a372be525` | Adição de `FuzzyRpcContext`, métodos tipados `fitAnfis` e `evaluateFuzzySurface` em `ControlLabEngineClient` e `BaseEngineClient` (herdados pelos clientes Pyodide/Mock) com `timeout_policy` padrão e reexportação de tipos. |
| `tests/unit/f1/test_rpc_anfis.py` | `12c391434fa0cc9d8a6573dfb7c0b115bed0f55a10d80fa8476b29358eb91f26` | Cobertura unitária RPC com validação contra `rpc_response.schema.json` para ANFIS multi-saída (`n_mfs`/`mf_type` heterogêneos + registro em `store`), superfície `3×2` com `fixed_inputs` e `output_name`, e rejeição tipada de `y` 3D, `mf_type` inválido e `output_name` inválido/inexistente. |
| `tests/unit/f7/fuzzy_anfis_bridge.test.ts` | `c3da6d3c85271de75d702a3c2fe971611a1cedd424ccfddc12a8fe0c52ea8ff4` | Teste round-trip de ponta a ponta na bridge F7 (`PyodideEngineClient` + `createMessageChannelWorkerTransport` + `InMemoryIDBFactory`) cobrindo `fitAnfis` multi-I/O `3×2`, `registerObject`, `evaluateFuzzySurface` com `output_name`/`fixed_inputs` e falha tipada `VALIDATION_ERROR`. |

---

## 2. Verificações Independentes e Evidências Executadas pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de ownership** (`git status --short`, `git diff --stat`) | Apenas os arquivos permitidos em `allowed_paths` modificados/criados (`control_lab/core/rpc.py`, `web/bridge/client.ts`, `web/bridge/protocol.ts`, `tests/unit/f1/test_rpc_anfis.py`, `tests/unit/f7/fuzzy_anfis_bridge.test.ts`), mais alinhamento pendente em `PROJECT_STATE.json`. ZERO alterações em `contracts/` ou `tests/oracles/`. | Ownership (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Inspeção AST — Zero `eval`/`exec`/`compile` builtin** | Scan AST independente em `control_lab/core/rpc.py`: **0** chamadas builtin a `eval`, `exec` ou `compile`. Coerções tipadas rejeitam `bool` para `seed`/`early_stopping_patience`/`max_epochs` e tipos inválidos de `mf_type`/`output_name`. | Segurança e rigor contratual (`R-02`) | PASS |
| **Validação Independente contra `rpc_response.schema.json` + Retrocompatibilidade** | Validação offline com `jsonschema.Draft202012Validator` sobre `contracts/schemas/rpc_response.schema.json` confirmou: (1) retrocompatibilidade para `y` 1D, `mf_type` string e `output_names`/`output_name` omitidos; (2) encaminhamento multi-I/O `3×2` (`n_mfs=[2,2,2]`, `mf_type=["gaussian","bell","gaussian"]`, `X_val`/`y_val`, `seed`, `early_stopping_patience`, `rcond`); (3) `evaluate_surface` com `output_name` omitido (`u1`) e explícito (`u2`); (4) falhas tipadas (`VALIDATION_ERROR`/`DIMENSION_MISMATCH`) para `seed=True`, `early_stopping_patience=False`, `mf_type=123`, `y` 3D e `output_name=42`. | `T-RPC-01`, `T-ANFIS-01`, `R-02`, `R-13` | PASS |
| **Typecheck TypeScript Estrito (`erasableSyntaxOnly`)** | `npm --prefix web run typecheck` (`tsc -p tsconfig.json --noEmit` com `strict: true`, `erasableSyntaxOnly: true`, `verbatimModuleSyntax: true`): **PASS (0 erros)**. | Rigor de tipos TS (`R-20`) | PASS |
| **Testes F7 Worker/Bridge** | `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope f7`: **typecheck PASS (24 TS)** + **83 passed, 0 failed, 0 skipped** em 10 arquivos de teste (incluindo `fuzzy_anfis_bridge.test.ts`). | Aceite F7 (`T-RPC-01`) | PASS |
| **Testes F1 RPC ANFIS + F5 Multi-I/O** | `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f1/test_rpc_anfis.py tests/unit/f5/test_anfis_fuzzy_multiio.py -q`: **17 passed in 3.35s** (`exit 0`). | Aceite F1/F5 (`T-RPC-01`, `T-ANFIS-01`) | PASS |
| **Build Web e Integridade de Assets** | `npm --prefix web run build`: wheel `control_lab-1.0.0-py3-none-any.whl` empacotado com sucesso; `Verified integrity and inventory of 42 local assets.` (`exit 0`). | Empacotamento Pyodide/Web | PASS |
| **Lint Python (`ruff`)** | `ruff check tests/unit/f1/test_rpc_anfis.py`: **0 erros**. Em `control_lab/core/rpc.py`: apenas 1 `F401` pré-existente na linha 22 (`NumericalInconclusiveError`, fora do diff deste WP). | Qualidade estática | PASS |

---

## 3. Revisão Contratual e Arquitetural

- **Retrocompatibilidade RPC (`control_lab/core/rpc.py`)**: chamadas legadas de `fuzzy.fit_anfis` com `y` 1D, `n_mfs` escalar, `mf_type` string e `output_name` único (ou omitido) continuam operando sem quebra; o mesmo vale para `fuzzy.evaluate_surface` sem `output_name`, que seleciona a primeira saída (`u1`) mantendo `surfaces` e `Z`.
- **Bridge Tipada (`web/bridge/protocol.ts` e `web/bridge/client.ts`)**: `FuzzyFitAnfisPayload` e `FuzzyEvaluateSurfacePayload` modelam fielmente o contrato RPC de `control_lab/core/rpc.py` sem introduzir construções não-apagáveis (`erasableSyntaxOnly: true`). A implementação em `BaseEngineClient` garante disponibilidade uniforme para os adaptadores Pyodide e Mock sobre `this.execute(...)`.

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Referência | Evidência Auditada | Status |
|---|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `R-02` / `rpc_response.schema.json` | Contratos `FuzzyFitAnfisPayload`, `FuzzyEvaluateSurfacePayload`, `fitAnfis` e `evaluateFuzzySurface` expostos por `web/bridge/protocol.ts` e `web/bridge/client.ts` e validados de ponta a ponta em `tests/unit/f7/fuzzy_anfis_bridge.test.ts` e `tests/unit/f1/test_rpc_anfis.py`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `R-04` / `R-13` | Todas as respostas RPC de sucesso e falha (`VALIDATION_ERROR`, `DIMENSION_MISMATCH`) validadas contra `contracts/schemas/rpc_response.schema.json`, contendo `status`, `assumptions`, `diagnostics`, `provenance`, `warnings` e `error` tipado. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `T-RPC-01`, `T-ANFIS-01` | Testes unitários em `tests/unit/f1/test_rpc_anfis.py` e `tests/unit/f7/fuzzy_anfis_bridge.test.ts` validam o comportamento funcional multi-I/O, superfícies `3×2` e rejeições tipadas antes de qualquer otimização. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Seção 13.11 | F9 executou validação independente com `Draft202012Validator` sobre `contracts/schemas/rpc_response.schema.json` cobrindo compatibilidade 1D, multi-I/O `3×2`, `evaluate_surface` com e sem `output_name`, rejeição de tipos inválidos e scan AST independente sem `eval`/`exec`. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Seção 13.1 / 13.2 | `git status --short` e `git diff --stat` confirmam alterações restritas aos `allowed_paths` do WP; ZERO modificações em `contracts/fixtures/` ou `tests/oracles/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | `R-27` | `control_lab/core/rpc.py` usa apenas Python padrão + NumPy/SciPy empacotados no wheel `control_lab-1.0.0-py3-none-any.whl` (`npm --prefix web run build` PASS); bridge testada via `createMessageChannelWorkerTransport` com runtime CPython e validada para empacotamento Pyodide. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `contracts/schemas/` | Nenhuma alteração nos arquivos JSON Schema de `contracts/schemas/` foi necessária; todas as respostas continuam estritamente válidas sob `rpc_response.schema.json` v1.0. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Apêndice E | Hashes SHA-256 dos 5 artefatos, resultados de `typecheck` (PASS), `run_web_tests --scope f7` (83/83 PASS), `pytest` F1+F5 (17/17 PASS), `npm --prefix web run build` (42 assets verificados) e validação independente de schema registrados neste documento. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `CL-DIR-001` / `ADR-006` | O WP não modifica métodos experimentais (`control_lab/experimental/sdp_educational/` intocado) e preserva integralmente os metadados `is_dynamic_model=False` retornados pelo motor ANFIS (`ADR-006`). | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `R-04` / `R-13` | Dimensões inválidas de `y`/`y_val`/`X_val`, `mf_type` inválido, `bool` em `seed`/`early_stopping_patience` e `output_name` inválido/inexistente em `evaluate_surface` retornam erros tipados acionáveis (`VALIDATION_ERROR` / `DIMENSION_MISMATCH`). | CONFORME |

---

## 5. Parecer Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: f9-integration-qa
- **Commit SHA auditado**: 3eb555a8e377929a9dc3ffd01ef5d602194d6877
- **Data (UTC)**: 2026-11-28
