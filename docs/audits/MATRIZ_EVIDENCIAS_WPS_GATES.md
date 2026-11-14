# Matriz Consolidada de Evidências — WorkPackages (`WP-00`..`WP-10`, `WP-AUDIT-FIX-*`) e Gates (`G-0A`..`G-0D`)

**Fonte normativa única:** [`ControlLab_Web_Documento_Diretor_v1.0.md`](../../ControlLab_Web_Documento_Diretor_v1.0.md) (`CL-DIR-001`, v1.0.0)  
**Base de auditoria:** [`AUDITORIA_EXTERNA_CL_DIR_001.md`](AUDITORIA_EXTERNA_CL_DIR_001.md) (`AUD-EXT-CL-DIR-001-2026-11-14`) e [`PARECER_F9_SOBRE_AUDITORIA_EXTERNA.md`](PARECER_F9_SOBRE_AUDITORIA_EXTERNA.md)  
**Template de Handoff Obrigatório:** [`HANDOFF_TEMPLATE_APENDICE_E.md`](../architecture/HANDOFF_TEMPLATE_APENDICE_E.md)  
**Histórico Git analisado:** `cfa5270` (2026-11-13) até `f1b9408` (2026-11-14)  
**Veredito global vigente:** `NOT_APPROVED_FOR_STABLE_WEB_RELEASE` (`PROJECT_STATE.json`)

---

## 1. Linha do Tempo de Commits e Proveniência Histórica (`cfa5270`..`f1b9408`)

| Commit | Data (UTC) | Evento / Escopo Registrado |
| :--- | :--- | :--- |
| `cfa5270` | 2026-11-13 | Bootstrap inicial (`setup_repo.py`, `AGENTS.md`, `CODEOWNERS` parcial, `PROJECT_STATE.json`, agentes `.agents/agents/f1..f9.md`) |
| `a9f973b` | 2026-11-13 | Criação de `README.md` |
| `f95ec4d` | 2026-11-13 | Entrega histórica `WP-00-F9-BOOTSTRAP` (`pyproject.toml`, 10 schemas, 4 exemplos, 3 fixtures ouro + `checksums.sha256`, `tests/oracles/`) |
| `08b6277` | 2026-11-13 | Entrega histórica `WP-01-F1-CORE-MODELS` (`control_lab/core/`, `diagnostics/`, `tests/unit/f1/`) |
| `676e1bc` | 2026-11-13 | Entrega histórica `WP-02-F2-CARE-LQR` (`control_lab/statespace/`, `tests/unit/f2/`) |
| `b989543` | 2026-11-13 | Entrega histórica `WP-03-F6-SDP-MODELING-AND-GATE0B` (`control_lab/optimization/`, `tests/unit/f6/`) |
| `f2c2226` | 2026-11-13 | Entrega histórica `WP-04-F7-RPC-BRIDGE-WORKER` (`web/bridge/`, `web/worker/`, `web/storage/`, `tests/unit/f7/`, `scripts/run_web_tests.mjs`) |
| `7e8d468` | 2026-11-13 | Entrega histórica `WP-05-F1-IO-CTRLAB-PVM` (`control_lab/io/`, `tests/unit/f1/test_io_ctrlab_and_pvm.py`) |
| `cd59cda` | 2026-11-13 | Ajuste F9 de `$id` dos 10 schemas em `contracts/schemas/` para `controllab-web.local` |
| `2e1ec08` | 2026-11-14 | Entrega histórica `WP-06-F8-UI-MVP-LQR` (`web/features/`, `web/charts/`, `web/app/`, `tests/unit/f8/`) |
| `fb7ba7a` | 2026-11-14 | Entrega histórica `WP-07-F3-FREQ-SISO-MIMO` (`control_lab/frequency/`, `tests/unit/f3/`) |
| `202ec9d` | 2026-11-14 | Entrega histórica `WP-08-F4-IDENTIFICATION` (`control_lab/identification/`, `tests/unit/f4/`) |
| `361a113` | 2026-11-14 | Inclusão de material legado de referência `docs/references/legacy_fuzzy_lab/` |
| `1c1c819` | 2026-11-14 | Entrega histórica `WP-09-F5-FUZZY-FML-ANFIS` (`control_lab/fuzzy/`, `tests/unit/f5/`) |
| `e4b166a` | 2026-11-14 | Entrega histórica `WP-10-F6-SDP-EDUCATIONAL-SOLVER` (`control_lab/experimental/sdp_educational/`, `tests/unit/f6/`) |
| `1a298c0` | 2026-11-14 | Registro do relatório independente [`AUDITORIA_EXTERNA_CL_DIR_001.md`](AUDITORIA_EXTERNA_CL_DIR_001.md) |
| `f1b9408` | 2026-11-14 | Triagem F9 ([`PARECER_F9_SOBRE_AUDITORIA_EXTERNA.md`](PARECER_F9_SOBRE_AUDITORIA_EXTERNA.md)) e escalonamento dos 9 `WP-AUDIT-FIX-*` em `PROJECT_STATE.json` |

---

## 2. Matriz de Evidências por WorkPackage Histórico (`WP-00`..`WP-10`)

> **Transparência de evidência (`AUD-013`):** Os commits históricos abaixo possuíam marcação `"ACCEPTED_BY_F9"` em `PROJECT_STATE.json`, mas **não** continham dossiês individuais do Apêndice E em disco nem prova de integração Wasm/navegador/PathView. Nenhum aceite anterior foi apagado: as aceitações originais permanecem preservadas em `historical_acceptance`, enquanto o estado vigente reflete o escopo realmente demonstrado.

| WP ID | Frente | Commit Histórico | Escopo Comprovado no Snapshot / Auditoria | Lacunas / Achados Confirmados | Decisão Formal Pós-Auditoria (`PROJECT_STATE.json`) | Remediação Obrigatória (`WP-AUDIT-FIX-*`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`WP-00-F9-BOOTSTRAP`** | `f9-integration-qa` | `f95ec4d` (+ `cd59cda`) | 10 JSON Schemas Draft 2020-12, 4 exemplos e 3 fixtures ouro (`B-CARE-02`, `B-CARE-12x3`, `B-SDP-A-D`) com SHA-256 e 12 testes oráculo em CPython. | Sem pipeline CI Jobs A–G, lockfiles/build (`AUD-003`), sem `CODEOWNERS` completo/exclusivo para fixtures (`AUD-012`), sem dossiês Apêndice E (`AUD-013`), `run_web_tests.mjs` fail-open (`AUD-015`) e faltam 4 fixtures §10.4 (`B-DARE-12x3`, `B-ARX-PRBS`, `B-MIMO-2x2`, `B-PVM-LQR`). | **`CHANGES_REQUESTED`** (`f9_review: changes_requested`; `historical_acceptance` preservado) | `WP-AUDIT-FIX-F9-GOV`, `WP-AUDIT-FIX-F9-BUILD-CI` |
| **`WP-01-F1-CORE-MODELS`** | `f1-core-io` | `08b6277` | Tipos canônicos, `Result`, `interconnect` e testes unitários F1 em `cpython_local_only`. | Getters devolvem `ndarray` mutável contornável via `.setflags(write=True)`; `with_revision(rev <= current)` aceita colisão (`AUD-005`); entrypoint Python RPC inexistente (`AUD-002`); sem dossiê Apêndice E (`AUD-013`). | **`CHANGES_REQUESTED`** (`f9_review: changes_requested`; `historical_acceptance` preservado) | `WP-AUDIT-FIX-F1-CORE-RPC` |
| **`WP-02-F2-CARE-LQR`** | `f2-statespace` | `676e1bc` | CARE/DARE/PBH/Lyapunov/LQR/LQI/observadores, rCARE e teste metamórfico `T-CARE-04` aprovados em **CPython local (`cpython_local_only`)**. | Integração Pyodide/Wasm, benchmarks cold/warm e UI/RPC real (`G-0A`) ausentes. Não equivale a `stable` Web. | **`ACCEPTED_BY_F9` (restrito a `cpython_local_only`)** (`f9_review: accepted`) | Bloqueadores de release Web: `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F9-WASM-GATES` |
| **`WP-03-F6-SDP-MODELING-AND-GATE0B`** | `f6-optimization-lmi` | `b989543` | DSL afim, `svec`, 5 dimensões do Verificador e testes A–D em CPython local. | `SDPBlock`/`CanonicalSDPProblem` expõem arrays/atributos mutáveis (`AUD-006`); fallback LP aceita off-diagonal `<= 1e-14` (`AUD-007`); resíduo PSD usa Frobenius em vez de norma 2 (`AUD-008`); sem prova Wasm `G-0B` nem dossiê (`AUD-013`). | **`CHANGES_REQUESTED`** (`f9_review: changes_requested`; `historical_acceptance` preservado) | `WP-AUDIT-FIX-F6-SDP`, `WP-AUDIT-FIX-F9-WASM-GATES` |
| **`WP-04-F7-RPC-BRIDGE-WORKER`** | `f7-worker-bridge` | `f2c2226` | Lógica de estado, revisões, coalescing, `MockWorkerAdapter` e `InMemoryIDBFactory` em Node 24 (`MessageChannel`). | **CRÍTICO:** `executeFallbackDesignLqr` inventa `K/P` sem Python e comita planta não estabilizável (`AUD-001`); caminho padrão usa `MessageChannel` sem Worker/loader real nem dispatcher Python (`AUD-002`); manifesto offline incompleto e `T-SEC-01` falso positivo (`AUD-004`, `AUD-010`); anuncia `stable`/`offline_ready: true` sem prova (`AUD-013`); aprovado sem `tsc` (`AUD-015`). | **`CHANGES_REQUESTED`** (`f9_review: changes_requested`; `historical_acceptance` preservado) | `WP-AUDIT-FIX-F7-RPC-BRIDGE`, `WP-AUDIT-FIX-F7-OFFLINE-SW`, `WP-AUDIT-FIX-F9-WASM-GATES` |
| **`WP-05-F1-IO-CTRLAB-PVM`** | `f1-core-io` | `7e8d468` | Contêiner `.ctrlab` (anti-traversal/ZIP bomb) e simulador interno `simulate_pvm_graph` em CPython local (`local_io_ctrlab_and_internal_pvm_only`). | **CRÍTICO:** Nenhuma importação, geração Python ou curva executada no PathView oficial (`AUD-011`, `external_pathview_verified=False`); `strict_json_loads` sem tratamento de `UnicodeDecodeError`; herda `AUD-005`/`AUD-013`. | **`BLOCKED_BY_GATE`** (`f9_review: blocked_by_gate`; `blocking_gate: G-0D`; `historical_acceptance` preservado) | `WP-AUDIT-FIX-F1-CORE-RPC`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F9-WASM-GATES` |
| **`WP-06-F8-UI-MVP-LQR`** | `f8-ui-charts` | `2e1ec08` | Shell, gráficos SVG/tabelas, `Fast-Preview` + `pending_commit` e a11y exercitados apenas em DOM simulado no Node. | TypeScript falha com 5 erros (`AUD-014`); usa fallback falso (`AUD-001`), sem Worker real (`AUD-002`), sem `/app/main.js` ou SW registrado (`AUD-003`, `AUD-004`), paridade simulada (`AUD-010`) e sem dossiê (`AUD-013`). | **`CHANGES_REQUESTED`** (`f9_review: changes_requested`; `historical_acceptance` preservado) | `WP-AUDIT-FIX-F8-TS-UI`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F9-WASM-GATES` |
| **`WP-07-F3-FREQ-SISO-MIMO`** | `f3-frequency` | `fb7ba7a` | Bode, Nyquist SISO, RL, compensadores, RGA, valores singulares e `S+T=I` aprovados em **CPython local (`cpython_local_only`)**. | Fixture `B-MIMO-2x2` (§10.4), integração RPC/UI e paridade Wasm pendentes. Não equivale a `stable` Web. | **`ACCEPTED_BY_F9` (restrito a `cpython_local_only`)** (`f9_review: accepted`) | Bloqueadores de release Web: `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F9-WASM-GATES` |
| **`WP-08-F4-IDENTIFICATION`** | `f4-identification` | `202ec9d` | ARX QR/SVD, OE, subespaços, holdout, FIT% separado e PE/posto aprovados em **CPython local (`cpython_local_only`)**. | Fixture `B-ARX-PRBS` (§10.4), integração RPC/UI e paridade Wasm pendentes. Não equivale a `stable` Web. | **`ACCEPTED_BY_F9` (restrito a `cpython_local_only`)** (`f9_review: accepted`) | Bloqueadores de release Web: `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F9-WASM-GATES` |
| **`WP-09-F5-FUZZY-FML-ANFIS`** | `f5-fuzzy-ts` | `1c1c819` | Inferência Mamdani/TS, ANFIS, bloqueio XXE/DTD e round-trip FML válido em CPython local. | Parser FML reinterpreta silenciosamente operadores desconhecidos, `sigma<=0`, vértices fora de ordem e `defaultvalue` malformado (`AUD-009`); sem dossiê (`AUD-013`). | **`CHANGES_REQUESTED`** (`f9_review: changes_requested`; `historical_acceptance` preservado) | `WP-AUDIT-FIX-F5-FML` |
| **`WP-10-F6-SDP-EDUCATIONAL-SOLVER`** | `f6-optimization-lmi` | `e4b166a` | Solver didático isolado em `experimental/sdp_educational/` aprovado na bateria local A–D (`experimental_solver_levels_a_to_d_cpython_local`, `maturity: experimental`). | Depende da correção estrutural de `WP-03` (`AUD-006`, `AUD-007`, `AUD-008`), de `OBS-F9-WP10-01` em `unavailable.py` (`capabilities()` reportando falso mesmo com `solver_fn`), de dossiê Apêndice E (`AUD-013`) e ensaio Wasm (`OBS-F9-WP10-03`). | **`CHANGES_REQUESTED`** (`f9_review: changes_requested`; `maturity: experimental`; `historical_acceptance` preservado) | `WP-AUDIT-FIX-F6-SDP`, `WP-AUDIT-FIX-F9-WASM-GATES` |

---

## 3. Cobertura dos 32 Testes Normativos (Apêndice C) no Baseline Auditado

Resumo auditado na triagem `f1b9408` (confrontado com `AUDITORIA_EXTERNA_CL_DIR_001.md` §3):
- **`CONFORME` (escopo local CPython/contrato): 24** (`T-CORE-02`, `T-CORE-03`, `T-TS-01`, `T-CARE-01`, `T-CARE-03`, `T-CARE-04`, `T-FREQ-01`, `T-FREQ-02`, `T-MIMO-01`, `T-MIMO-02`, `T-ID-01`, `T-ID-02`, `T-ID-03`, `T-FML-01`, `T-SDP-A1`, `T-SDP-A2`, `T-SDP-A3`, `T-SDP-B1`, `T-SDP-C1`, `T-SDP-D1`, `T-SDP-D2`, `T-RPC-01`, `T-IO-01`, `T-IO-02`)
- **`PARCIAL`: 7** (`T-CORE-01`, `T-CARE-02`, `T-FML-02`, `T-RPC-02`, `T-PVM-01`, `T-PVM-02`, `T-UI-01`)
- **`AUSENTE`: 0**
- **`FALSO POSITIVO`: 1** (`T-SEC-01` em `tests/unit/f7/rpc_bridge_worker.test.ts` usando `InMemoryCacheStorage` e fetch stub)

---

## 4. Matriz de Status e Bloqueadores dos Gates (`G-0A` a `G-0D`)

Todos os 4 gates mantêm `"status": "PENDING"` em `PROJECT_STATE.json` (conforme Seção 14.1 de `CL-DIR-001`):

| Gate | Descrição (`CL-DIR-001` §14.1) | `status` em `PROJECT_STATE.json` | `audit_verdict` | Achados Bloqueadores | WPs Corretivos Bloqueadores | Evidência Objetiva Exigida para Aprovação |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`G-0A`** | Núcleo Python/Pyodide e benchmark `B-CARE-12x3` | `PENDING` | **`BLOCKED`** | `AUD-001`, `AUD-002`, `AUD-003`, `AUD-010`, `AUD-013` | `WP-AUDIT-FIX-F1-CORE-RPC`, `WP-AUDIT-FIX-F7-RPC-BRIDGE`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F7-OFFLINE-SW`, `WP-AUDIT-FIX-F9-WASM-GATES` | Eliminar fallback LQR falso; carregar Pyodide + wheel real em Worker separado + `control_lab.core.rpc`; recalcular `B-CARE-02` e `B-CARE-12x3` em browser com paridade de resíduos/versões, métricas cold/warm e teste de restart/vazamento de `PyProxy`. |
| **`G-0B`** | Capacidade real de SDP no navegador via Pyodide | `PENDING` | **`NOT_DEMONSTRATED`** | `AUD-006`, `AUD-007`, `AUD-008`, `AUD-013` | `WP-AUDIT-FIX-F6-SDP`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F9-WASM-GATES` | Corrigir invariantes/diagonalidade/norma-2 em F6; carregar `cvxpy-base + clarabel` reais no Pyodide alvo em >= 2 navegadores resolvendo A/B/PSD 2×2/BRL ou registrar explicitamente `clarabel_cvxpy: unavailable_wasm` sem bloquear a vertical LQR. |
| **`G-0C`** | UI mínima e contrato RPC v1.0 com Mock e Engine real | `PENDING` | **`BLOCKED`** | `AUD-001`, `AUD-002`, `AUD-003`, `AUD-010`, `AUD-014` | `WP-AUDIT-FIX-F7-RPC-BRIDGE`, `WP-AUDIT-FIX-F8-TS-UI`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F7-OFFLINE-SW`, `WP-AUDIT-FIX-F9-WASM-GATES` | Compilar TS sem erros (`AUD-014`); gerar bundle estático (`/app/main.js`); UI conectada ao Worker real (`G-0A`); testar `Mock` vs engine real, 20+ revisões, cancelamento, `IndexedDB` real, a11y teclado/mobile e recálculo offline após reload (`T-SEC-01`). |
| **`G-0D`** | Persistência `.ctrlab` e equivalência dinâmica PathView `.pvm` | `PENDING` | **`BLOCKED_EXTERNAL_ACCEPTANCE`** | `AUD-011` | `WP-AUDIT-FIX-F1-CORE-RPC`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F9-WASM-GATES` | Depende de `G-0C`; abrir `.pvm` (`C=I`, `C!=I`, `m!=p`, controlador dinâmico e saturação) no **PathView oficial** com versão fixada, gerar código Python e comprovar equivalência de trajetórias/estados internos, além de round-trip `.ctrlab` sem execução automática de scripts. |

---

## 5. Escalonamento de Remediação (`WP-AUDIT-FIX-*` — `REM-01`..`REM-15`)

| Ordem | `WP_ID` | Frente | `REM` | Achados | Dependências | Dossiê Apêndice E |
| :-: | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `WP-AUDIT-FIX-F9-GOV` | `f9-integration-qa` | `REM-01, REM-03` | `AUD-012, AUD-013, AUD-015` | `[]` | [`docs/audits/handoffs/WP-AUDIT-FIX-F9-GOV.md`](handoffs/WP-AUDIT-FIX-F9-GOV.md) |
| 2 | `WP-AUDIT-FIX-F1-CORE-RPC` | `f1-core-io` | `REM-04` | `AUD-005, AUD-002` (+ `strict_json_loads`) | `WP-AUDIT-FIX-F9-GOV` | `docs/audits/handoffs/WP-AUDIT-FIX-F1-CORE-RPC.md` *(pendente)* |
| 3 | `WP-AUDIT-FIX-F7-RPC-BRIDGE` | `f7-worker-bridge` | `REM-02, REM-07` | `AUD-001, AUD-002, AUD-014, AUD-010, AUD-013` | `WP-AUDIT-FIX-F9-GOV, WP-AUDIT-FIX-F1-CORE-RPC` | `docs/audits/handoffs/WP-AUDIT-FIX-F7-RPC-BRIDGE.md` *(pendente)* |
| 4 | `WP-AUDIT-FIX-F6-SDP` | `f6-optimization-lmi` | `REM-05` | `AUD-006, AUD-007, AUD-008` (+ `OBS-F9-WP10-01`) | `WP-AUDIT-FIX-F1-CORE-RPC` | `docs/audits/handoffs/WP-AUDIT-FIX-F6-SDP.md` *(pendente)* |
| 5 | `WP-AUDIT-FIX-F5-FML` | `f5-fuzzy-ts` | `REM-06` | `AUD-009` | `WP-AUDIT-FIX-F1-CORE-RPC` | `docs/audits/handoffs/WP-AUDIT-FIX-F5-FML.md` *(pendente)* |
| 6 | `WP-AUDIT-FIX-F8-TS-UI` | `f8-ui-charts` | `REM-08` | `AUD-014, AUD-002, AUD-003, AUD-004, AUD-010, AUD-013` | `WP-AUDIT-FIX-F9-GOV, WP-AUDIT-FIX-F7-RPC-BRIDGE` | `docs/audits/handoffs/WP-AUDIT-FIX-F8-TS-UI.md` *(pendente)* |
| 7 | `WP-AUDIT-FIX-F9-BUILD-CI` | `f9-integration-qa` | `REM-09` | `AUD-003, AUD-011` (+ 4 fixtures §10.4) | `WP-AUDIT-FIX-F6-SDP, WP-AUDIT-FIX-F5-FML, WP-AUDIT-FIX-F8-TS-UI` | `docs/audits/handoffs/WP-AUDIT-FIX-F9-BUILD-CI.md` *(pendente)* |
| 8 | `WP-AUDIT-FIX-F7-OFFLINE-SW` | `f7-worker-bridge` | `REM-10` | `AUD-004` | `WP-AUDIT-FIX-F9-BUILD-CI` | `docs/audits/handoffs/WP-AUDIT-FIX-F7-OFFLINE-SW.md` *(pendente)* |
| 9 | `WP-AUDIT-FIX-F9-WASM-GATES` | `f9-integration-qa` | `REM-11..REM-15` | `AUD-010, AUD-011, AUD-013` | `WP-AUDIT-FIX-F7-OFFLINE-SW` | `docs/audits/handoffs/WP-AUDIT-FIX-F9-WASM-GATES.md` *(pendente)* |
