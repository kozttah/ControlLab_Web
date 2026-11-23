# Handoff e Parecer F9 — `WP-PHASE9-01E-F1-RPC-PACKED-BUFFERS`

- **WorkPackage**: `WP-PHASE9-01E-F1-RPC-PACKED-BUFFERS`
- **Frente Produtora**: `F1 (f1-core-io)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-23T04:20:00Z`

---

## 1. Escopo Auditado e Inventário SHA-256 (`allowed_paths`)

Alterações estritamente isoladas em `control_lab/core/rpc.py` e `tests/unit/f1/`:

| Artefato F1 | SHA-256 | Papel no Pacote |
|---|---|---|
| `control_lab/core/rpc.py` | `c2b6a132b0a8384527a3fe4a51f7d071c45aa4f2f43892a5df196c85696a2b53` | Aceita chave opcional `buffers` no envelope Worker `{request, payload, ?store, ?buffers}` e aplica caminho zero-copy em `_rehydrate_buffers` para subárvores sob `F_k_packed`, retornando `np.ndarray` diretamente via `np.frombuffer` com validação de shape/dtype/finitude em C sem expansão para listas Python; tensores fora de `F_k_packed` mantêm `TensorDescriptor` canônico. |
| `tests/unit/f1/test_rpc_packed_buffers.py` | `0632baae4b03e8bd6fdbaae6f57b53cea6f08c4965fed88bfa89006ae27b2a40` | Prova `np.shares_memory` (zero-copy) em `F_k_packed`, compatibilidade de tensores comuns, rejeição de `NaN`/`Inf` (`VALIDATION_ERROR`), rejeição de buffers truncados/incompatíveis (`DIMENSION_MISMATCH`) e arrays vazios (`nnz = 0`). |

---

## 2. Evidências de Verificação Independente (F9)

- **Ownership**: nenhum arquivo fora de `control_lab/core/rpc.py` e `tests/unit/f1/` alterado pela F1; zero `eval`/`new Function`, zero `pytest.skip`/`importorskip`.
- **Gate `core_no_sdp` simulado (`f1..f5`, `oracles`, `integration`)**: **583 passed, 0 failed, 0 skipped** (`exit 0`).
- **Oráculo independente F9 (`tests/oracles/test_phase9_cycle1_oracle.py`)**: `dispatch_rpc` com envelope `{request, payload, buffers}` (`memoryview`) em `optimization.solve` e `optimization.verify` atingiu paridade `< 1e-8` contra denso/esparso e `< 1e-5` contra `clarabel_direct`.
- **Chromium + Pyodide Wasm real (`tests/wasm/test_real_runtime.py`)**: `8/8` `ArrayBuffer`s transferidos zero-copy via Worker → `dispatch_rpc` em `120.7 ms`, `activeProxies === 0`, paridade `max |Δx| = 5.15e-14`.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Envelope Worker `{request, payload, ?store, ?buffers}` e `BufferTensorRef` sob `F_k_packed` validados em `test_rpc_packed_buffers.py`, `tests/oracles/test_phase9_cycle1_oracle.py` e consumidor real F7/Pyodide. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Entradas inválidas (não-Mapping, `NaN`/`Inf`, buffer truncado, contagem divergente) retornam `RpcResponse` com `status="failure"` e erros tipados (`VALIDATION_ERROR`, `DIMENSION_MISMATCH`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Invariantes de memória compartilhada (`np.shares_memory`), shapes, finitude e casos vazios (`nnz=0`) verificados por testes unitários e oráculo F9 antes do aceite. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Oráculo independente F9 (`tests/oracles/test_phase9_cycle1_oracle.py`) confronta resultados de `dispatch_rpc` zero-copy com `F_k` denso, `F_k_sparse`, `verify()` 5D e `clarabel_direct`. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Escopo estrito em `control_lab/core/rpc.py` e `tests/unit/f1/`; `contracts/fixtures/` intactos (`verify_fixtures.py` PASS). | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Wheel reconstruído e validado em CPython (`583 passed`) e Chromium + Pyodide real (`test_wasm_phase9_cycle1_packed_zero_copy_transfer_and_solve` PASS, `max |Δx| = 5.15e-14`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma quebra de `rpc_request.schema.json`/`rpc_response.schema.json`; chave `buffers` é extensão retrocompatível do envelope interno do Worker revisada pela F9. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, contagem de testes (`583 passed`), medição real Pyodide (`120.7 ms`, `0` PyProxy leaks) e integridade de fixtures anexados. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Nenhuma alteração na classificação de maturidade ou isolamento experimental (`ADR-008`/`ADR-010`). | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Erros de alinhamento de bytes, shape incorreto e valores não finitos emitem mensagens tipadas claras com `buffer_ref`, `dtype` e `byte_length`. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **Data (UTC)**: `2026-11-23T04:20:00Z`
- **Justificativa**: A F1 entregou suporte zero-copy seguro e retrocompatível para `buffers` de `F_k_packed` no dispatcher RPC canônico, mantendo validação estrita em C (shape, alinhamento, finitude) e provando paridade de máquina (`5.15e-14`) entre CPython e Pyodide Wasm real sem vazamentos de `PyProxy`.
