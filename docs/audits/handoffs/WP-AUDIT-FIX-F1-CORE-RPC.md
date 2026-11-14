# Dossiê de Handoff e Auditoria F9 — `WP-AUDIT-FIX-F1-CORE-RPC`

**Template normativo:** [`HANDOFF_TEMPLATE_APENDICE_E.md`](../../architecture/HANDOFF_TEMPLATE_APENDICE_E.md)  
**Fonte normativa única:** [`ControlLab_Web_Documento_Diretor_v1.0.md`](../../../ControlLab_Web_Documento_Diretor_v1.0.md) (`CL-DIR-001`, v1.0.0 — Seções 7.2, 8.2, 13.3, 13.11 e Apêndice E)

---

## 1. Cabeçalho da Tarefa (Apêndice E)

| Campo Obrigatório | Valor / Referência |
| :--- | :--- |
| **WorkPackage ID** | `WP-AUDIT-FIX-F1-CORE-RPC` |
| **Frente F** | `f1-core-io` (Fase `Audit-Remediation`) |
| **Módulo / caminhos permitidos (`allowed_paths`)** | `control_lab/core/`, `control_lab/diagnostics/`, `control_lab/io/`, `tests/unit/f1/` |
| **Contratos consumidos** | `rpc_request.schema.json`, `rpc_response.schema.json`, `CL-DIR-001` §7.2, §8.2, §13.3 |
| **Entradas / saídas** | Entrada: `RpcRequest` (dict/JSON/JsProxy, buffers opcionais); Saída: `RpcResponse` tipado (`dispatch` / `dispatch_rpc` em `control_lab/core/rpc.py`). |
| **Hipótese matemática** | Dispatcher sem mutação da entrada, erros tipados (ex.: `HYPOTHESIS_VIOLATED` para planta não estabilizável), validação estrita de tensores/buffers e valores não finitos. |
| **Limite da implementação** | Validado apenas em CPython local; Pyodide/Wasm e ponte F7 não verificados. |
| **Testes de aceite** | `pytest tests/unit/f1 tests/unit/f2 tests/unit/f3 tests/unit/f4 tests/unit/f5 tests/oracles tests/integration -q`; `python scripts/verify_fixtures.py`; `node --test tests/integration/*.test.mjs`. |
| **Fixtures** | `contracts/fixtures/` inalteradas. |
| **Dependências** | `WP-AUDIT-FIX-F9-GOV` (`ACCEPTED_BY_F9`). |
| **Bloqueadores** | Nenhum no escopo; release Web depende de `F7-RPC-BRIDGE`, `F9-BUILD-CI`, `F9-WASM-GATES`. |
| **Evidência / PR esperado** | Alterações não commitadas sobre `HEAD` `e825d234e6f242664e4e108056fc41864a46bb22`. |
| **Risco** | Baixo/Médio (superfície RPC grande, ~2000 linhas). |
| **Nível de maturidade pretendido** | `stable` apenas no escopo CPython local. |

---

## 2. Entregáveis Produzidos

1. `control_lab/core/rpc.py` (novo): dispatcher RPC (`dispatch`, `dispatch_rpc`), validação de envelope, reidratação de buffers, handlers por domínio.
2. Ajustes em `control_lab/core/{__init__,controllers,interconnect,models,tensors}.py` e `control_lab/diagnostics/errors.py`.
3. `tests/unit/f1/test_core_rpc_and_immutability.py` (novo).

---

## 3. Checklist de Handoff de 10 Itens (Apêndice E — `CL-DIR-001`)

| # | Pergunta Normativa (Apêndice E — `CL-DIR-001`) | Resposta (`SIM` / `NÃO` / `PARCIAL` / `N/A`) | Evidência Objetiva (arquivo, linha, teste, comando, SHA) | Auditoria F9 |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8?** | `SIM` | `dispatch` validado contra `rpc_request`/`rpc_response` schemas; `tests/oracles` + `verify_fixtures.py` OK; 121 passed. | `CONFORME` |
| **2** | **Saída contém status, diagnósticos e proveniência, inclusive casos de falha?** | `SIM` | Sondas F9: respostas de falha trazem `status`, `error` tipado, `diagnostics`, `provenance`. | `CONFORME` |
| **3** | **Testes analíticos foram escritos antes da otimização prematura?** | `SIM` | `tests/unit/f1/test_core_rpc_and_immutability.py` e oráculos analíticos pré-existentes. | `CONFORME` |
| **4** | **Existe confronto independente da implementação, em vez de autorreferência?** | `SIM` | Sondas adversariais F9 independentes (planta não estabilizável → `HYPOTHESIS_VIOLATED`; B nulo; `buffer_ref` não reidratado, tensor com `data` truncado, NaN → `VALIDATION_ERROR`); oráculos F9 inalterados. | `CONFORME` |
| **5** | **O PR respeita ownership e não modificou mocks/expected values para esconder defeito?** | `SIM` | `git status`: apenas `control_lab/core/`, `control_lab/diagnostics/`, `tests/unit/f1/`; sem alterações em `contracts/fixtures/`, `tests/oracles/`, `PROJECT_STATE.json`. | `CONFORME` |
| **6** | **O mesmo teste funciona em CPython e Pyodide no domínio anunciado?** | `N/A` | Escopo `cpython_local_only`; Pyodide não verificado (`F9-WASM-GATES`). | `CONFORME` |
| **7** | **Alterações de schema tiveram migração/versão e revisão F9?** | `N/A` | Nenhuma alteração em `contracts/`. | `CONFORME` |
| **8** | **Logs, matrizes de fixture e resultados de benchmark foram anexados?** | `SIM` | Logs na Seção 4; benchmarks Wasm permanecem em `F9-WASM-GATES`. | `CONFORME` |
| **9** | **Um método experimental permanece visualmente classificado como tal?** | `SIM` | Nenhuma promoção de maturidade; SDP educacional permanece `experimental`; Web permanece `NOT_APPROVED_FOR_STABLE_WEB_RELEASE`. | `CONFORME` |
| **10** | **Qualquer limitação conhecida tem issue e mensagens de falha adequadas?** | `SIM` | Limitações mapeadas em `F7-RPC-BRIDGE`, `F9-BUILD-CI`, `F9-WASM-GATES`; falhas com `next_step`/código tipado. | `CONFORME` |

---

## 4. Registro de Ambiente, SHA e Saída de Execução

- **Commit SHA auditado (`HEAD`):** `e825d234e6f242664e4e108056fc41864a46bb22` (+ alterações F1 não commitadas)
- **Data (UTC):** `2026-11-14`
- **Toolchain:** CPython 3.11.2 (`/home/antigravity/.venv_controllab/bin/python`), Node v24.x

```text
 M control_lab/core/__init__.py
 M control_lab/core/controllers.py
 M control_lab/core/interconnect.py
 M control_lab/core/models.py
 M control_lab/core/tensors.py
 M control_lab/diagnostics/errors.py
?? control_lab/core/rpc.py
?? tests/unit/f1/test_core_rpc_and_immutability.py
```

- `pytest tests/unit/f1 tests/unit/f2 tests/unit/f3 tests/unit/f4 tests/unit/f5 tests/oracles tests/integration -q`: `121 passed in 7.93s`.
- `python scripts/verify_fixtures.py`: schemas, 3 fixtures ouro (SHA-256) e 4 exemplos OK.
- `node --test tests/integration/*.test.mjs`: `pass 8, fail 0`.
- **Sondas independentes de `control_lab/core/rpc.py::dispatch`:**
  - Imutabilidade: request deep-copiado antes/depois, igual (`True`).
  - `design_lqr` com `B=0` e com par (A=diag(1,2), B=[1,0]) não estabilizável: `failure` / `HYPOTHESIS_VIOLATED`.
  - `buffer_ref` não reidratado, tensor `shape [2,2]` com 3 elementos, `NaN`: `failure` / `VALIDATION_ERROR`.
- Nota: falhas de baseline de `tests/unit/f6` por ausência de `clarabel`/`cvxpy` são pré-existentes e não relacionadas a este WP (F6 fora do escopo executado).

---

## 5. Parecer Independente da Frente F9

- **Veredito F9 (`accepted` | `changes_requested` | `blocked_by_gate` | `rejected_with_evidence`):** `accepted`
- **Escopo aprovado (`acceptance_scope`):** `cpython_local_only`
- **Revisor independente:** `f9-integration-qa`
- **Commit SHA auditado:** `e825d234e6f242664e4e108056fc41864a46bb22`
- **Data (UTC):** `2026-11-14`
- **Testes e artefatos validados independentemente pela F9:** `control_lab/core/rpc.py`, `tests/unit/f1/test_core_rpc_and_immutability.py`, suíte `121 passed`, `scripts/verify_fixtures.py`, `node --test` (8 passed), sondas adversariais da Seção 4.
- **Pendências / Bloqueadores remanescentes:** Nenhum bloqueador dentro do escopo deste WP. Permanecem como bloqueadores de release Web: `WP-AUDIT-FIX-F7-RPC-BRIDGE`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F9-WASM-GATES` (mantido `NOT_APPROVED_FOR_STABLE_WEB_RELEASE`).
