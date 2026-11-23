# Handoff e Parecer F9 — `WP-PHASE9-01B-F7-TYPEDARRAY-WORKER-BRIDGE`

- **WorkPackage**: `WP-PHASE9-01B-F7-TYPEDARRAY-WORKER-BRIDGE`
- **Frente Produtora**: `F7 (f7-worker-bridge)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-23T04:20:00Z`

---

## 1. Escopo Auditado e Inventário SHA-256 (`allowed_paths`)

Alterações estritamente isoladas em `web/bridge/`, `web/worker/` e `tests/unit/f7/`:

| Artefato F7 | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/bridge/protocol.ts` | `5c70404aae5a938b9b8a5d6c51b6051300e267c81e7a3a32b570cc02a53d301a` | Estende `ensureFiniteJson`, `extractTensorsToBinaryBuffers` e `validateWireBinaryBuffer` para reconhecer `Int32Array`/`Float64Array` sob `F_k_packed` (`packed_sparse: true`), coletar `ArrayBuffer`s na `transferList` sem cópia estruturada (fatiando `subarray` com offset), e rejeitar `NaN`/`Inf` e `TypedArray`s fora de `F_k_packed`. |
| `web/bridge/pyodide_client.ts` | `7eb58964873d240b89068787237c57545cdb2712472d85e094bf212b3ab613fb` | Extrai e transfere `ArrayBuffer`s de `F_k_packed` via `postMessage(..., transferList)` em `execute()` mantendo fallback e cancelamento intactos. |
| `web/worker/pyodide_worker.ts` | `fdf9a9044ac1845c3e6835aee80a521f0c143ad158aba5429404d8c7a578b04e` | Encaminha buffers marcados como `packed_sparse` zero-copy como `Uint8Array` → Pyodide `memoryview` no envelope `{request, payload, buffers}` sob guarda `PyProxyRegistry` (garantindo destruição determinística e `activeProxies === 0`). |
| `tests/unit/f7/packed_sparse_transfer.test.ts` | `59faa53d1488eac14289a569feec9690c50c0858197fb134e6594967f0efce0a` | Testa extração zero-copy, subarrays, `TensorDescriptor` dentro de `F_k_packed`, rejeição de `NaN`/`Inf` e `TypedArray` fora de `F_k_packed`, e encaminhamento no Worker com 0 vazamentos de `PyProxy`. |

---

## 2. Evidências de Verificação Independente (F9)

- **Ownership e Segurança**: nenhum arquivo fora de `web/bridge/`, `web/worker/`, `tests/unit/f7/` alterado pela F7; zero `eval`/`new Function`.
- **`npm --prefix web run typecheck` e `npm --prefix web run build`**: PASS (`exit 0`, 55 arquivos TS, 42 assets locais íntegros).
- **`node scripts/run_web_tests.mjs --scope all`**: **157 passed, 0 failed, 0 skipped** (`exit 0`).
- **Chromium + Pyodide Wasm real (`tests/wasm/test_real_runtime.py`)**: `8/8` `ArrayBuffer`s de `F_k_packed` destacados (*detached*, `byteLength === 0`) após `postMessage` — prova direta de transferência zero-copy `Transferable` — com `activeProxies === 0` após execução e paridade `max |Δx| = 5.15e-14`.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Contrato `PackedSparseCooPayload` + `BufferTensorRef` + `WireBinaryBuffer.packed_sparse` validado em `tests/unit/f7/packed_sparse_transfer.test.ts` e integrado ao compilador F8 e dispatcher F1. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Erros de finitude (`NaN`/`Inf`), buffers inválidos e cancelamentos produzem `ControlLabBridgeError` / `RpcResponse` tipado preservando proveniência. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Invariantes de identidade de `ArrayBuffer` (zero-copy), fatiamento seguro de `subarray`, arrays vazios (`nnz=0`) e `PyProxyRegistry` cobertos antes da aceitação. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Teste F9 em Chromium real (`test_wasm_phase9_cycle1_packed_zero_copy_transfer_and_solve`) comprova *detachment* real dos 8 `ArrayBuffer`s, `activeProxies === 0` e paridade contra CPython. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Escopo estritamente restrito a `web/bridge/`, `web/worker/` e `tests/unit/f7/`; `contracts/fixtures/` e `tests/oracles/` intocados. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Transporte validado tanto em Node/MessageChannel (`run_web_tests.mjs`, `157 passed`) quanto em Chromium + Pyodide Worker real (`19 passed` em Wasm + E2E). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Flag opcional `packed_sparse?: boolean` em `WireBinaryBuffer` retrocompatível com transporte denso existente e revisada pela F9. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, saída `157 passed` do harness web e evidência JSON real do Chromium (`8/8` buffers destacados, `120.7 ms`, `activeProxies=0`) anexados. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Nenhuma alteração em selos de maturidade ou isolamento experimental (`ADR-008`/`ADR-010`). | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `TypedArray`s fora de `F_k_packed`, buffers corrompidos e valores não finitos são rejeitados com `VALIDATION_ERROR` descritivo. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **Data (UTC)**: `2026-11-23T04:20:00Z`
- **Justificativa**: A F7 entregou transporte binário `Transferable` verdadeiramente zero-copy para `F_k_packed` entre *main thread*, Web Worker e Pyodide `memoryview`, comprovado em Chromium real (`8/8` `ArrayBuffer`s destacados, `activeProxies === 0`, `120.7 ms`) sem regressões nos `157` testes web.
