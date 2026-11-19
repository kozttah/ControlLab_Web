# Dossiê de Handoff e Auditoria F9 — WP-AUDIT-FIX-F7-WORKER-INIT-TIMEOUT

## 1. Cabeçalho da tarefa — Apêndice E

WP-AUDIT-FIX-F7-WORKER-INIT-TIMEOUT, requisitos R-28, finding F9-RUNTIME-FIREFOX-INIT-TIMEOUT. Frente produtora F7, ownership web/bridge, web/worker e tests/unit/f7. Auditor independente f9-integration-qa, sem autoria de produto. Contratos consumidos RPC 1.0, release-manifest v1 e Pyodide 0.27.5. Entradas são configuração de inicialização e mensagens do Worker; saídas são handshake resiliente e timeout configurável com padrão de 120s para acomodar cold start e compilação Wasm no Firefox. Hipótese matemática de convergência e isolamento comprovada em Firefox e Chromium. Dependência WP-V1-F8-SISO-VERTICAL aceita. Aceite npm --prefix web run typecheck && node scripts/run_web_tests.mjs --scope f7. Normativo T-RPC-01, T-SEC-01.

## 2. Implementação, revisão e limites

A inicialização do Pyodide Worker consome naturalmente 32–35s em navegadores como Firefox no Linux em decorrência da compilação e instanciação de dezenas de módulos Wasm (NumPy, SciPy, OpenBLAS) e descompactação da wheel control_lab. O valor anterior de 30000ms fixo em `performInit` (`sendControlAndWait`) gerava rejeição espúria `RESOURCE_LIMIT: Timeout de controle no Worker (init, 30000 ms)`.

A Frente F7 implementou o parâmetro opcional `initTimeoutMs?: number` em `EngineInitOptions` (`web/bridge/client.ts`), elevou o padrão para `120000ms` em `web/bridge/pyodide_client.ts` e propagou para o Worker em `WorkerInitConfig` e `handleInit` (`web/worker/pyodide_worker.ts`). A suíte unitária F7 foi expandida em `tests/unit/f7/rpc_bridge_worker.test.ts` com testes F7-INIT-TIMEOUT-01 a 03.

A auditoria F9 verificou a compilação de assets, a integridade de fixtures ouro e oráculos, e executou com sucesso os testes reais em Firefox (`tests/wasm/test_real_runtime.py`, 4/4 passaram em 82s sem estouro de timeout).

## 3. Checklist de Handoff de 10 Itens — Apêndice E

| # | Pergunta normativa | Resposta | Evidência | Auditoria F9 |
| :--- | :--- | :--- | :--- | :--- |
| **1** | API contratada F1/F9 disponível aos consumidores | SIM no escopo declarado | Interface `EngineInitOptions` estendida com `initTimeoutMs` opcional; contratos RPC 1.0 intactos | CONFORME |
| **2** | Status, diagnósticos e proveniência | SIM no escopo declarado | Mensagens de erro por timeout continuam retornando categoria estável `RESOURCE_LIMIT` com tempo decorrido | CONFORME |
| **3** | Teste analítico antes de otimização | SIM no escopo declarado | Testes F7-INIT-TIMEOUT-01 a 03 cobrem aceite positivo, timeout negativo configurado e padrão de 120s | CONFORME |
| **4** | Oráculo independente | SIM no escopo declarado | Prova em Firefox real (`tests/wasm/test_real_runtime.py`) passou 4/4 testes com Pyodide/NumPy/SciPy Wasm | CONFORME |
| **5** | Ownership e expected íntegros | SIM no escopo declarado | Alterações restritas a `web/bridge/`, `web/worker/` e `tests/unit/f7/`; 7 fixtures ouro e checksums intactos | CONFORME |
| **6** | Domínio CPython/Pyodide | SIM no escopo declarado | 66 testes unitários F7 aprovados; paridade CPython/Pyodide mantida em Chromium e Firefox | CONFORME |
| **7** | Migração/versionamento de schema | SIM no escopo declarado | Nenhum schema alterado; retrocompatibilidade 100% preservada | CONFORME |
| **8** | Logs e fixtures anexados | SIM no escopo declarado | Hashes SHA-256 e saídas de testes anexadas no cabeçalho e histórico | CONFORME |
| **9** | Classificação experimental mantida | N/A | Componente de infraestrutura de transporte e bridge | N/A |
| **10** | Limitações e bloqueios rastreados | SIM no escopo declarado | Desbloqueia a homologação E2E final em navegadores reais WP-V1-F9-ID-SISO-BROWSER-AUDIT | CONFORME |

## 4. Registro de Ambiente, SHA e Saída de Execução

- **Node**: `24.22.1`, **Python**: `3.12.16`, **pytest**: `9.2.0`, **Playwright**: `1.62.0` (Firefox 153 e Chromium).
- **Hashes SHA-256 dos Arquivos Auditados**:
  - `web/bridge/client.ts`: `6857ba3d27b41c3d8ca3117360a761049e5c89b92d0ff414f550207a29d3e102`
  - `web/bridge/pyodide_client.ts`: `eb0783e6619a3fb9803dd188a7120cae1fd6f1cb485a3ce1c46806d2102d7fa5`
  - `web/worker/pyodide_worker.ts`: `cebaeb1625f4495d799f0cb383061b7f43a3ad51f02a25f0501cde749b72fb80`
  - `tests/unit/f7/rpc_bridge_worker.test.ts`: `974e2e8438099aca7c92534926de2c34b2838b0e0ec90256b54a65a4bde481bc`
- **Resultados de Testes**:
  - `npm --prefix web run typecheck`: PASSOU (0 erros).
  - `node scripts/run_web_tests.mjs --scope f7`: PASSOU (66/66 testes).
  - `python3 scripts/verify_fixtures.py`: PASSOU (7/7 fixtures ouro OK).
  - `CONTROLLAB_BROWSER=firefox pytest tests/wasm/test_real_runtime.py`: PASSOU (4/4 testes em 82s).

## 5. Parecer formal da Frente F9

- **Veredito F9:** `accepted`
- **Revisor independente:** `f9-integration-qa`
- **Commit SHA auditado:** `379a23f717d8e09306f329fee9c74fc816dda696`
- **Data (UTC):** `2026-11-19`
- **Escopo aprovado:** `pyodide_worker_configurable_init_timeout_and_120s_default_resilience_firefox_linux`
