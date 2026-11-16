# Relatório Consolidado de Auditoria de Estado e Liberação de Gates — Fase 0 (`CL-DIR-001`)

- **Documento normativo:** `CL-DIR-001` v1.0.0 (`ControlLab_Web_Documento_Diretor_v1.0.md`)
- **Commit auditado (HEAD `origin/main`):** `3ce128a6d8a18ad1eeb18ee83b666df6708d30d0` (`feat(f9-integration-qa): conclui WP-AUDIT2-FIX-F9-DOWNLOAD-E2E [auditado F9]`)
- **Papéis executores:** Maestro (`AGENTS.md`) e Frente Independente `f9-integration-qa`
- **Data da auditoria (UTC):** `2026-11-16`
- **Release estática verificada (manifest SHA-256):** `94c136ae68b292fab61d8b8f638f690fe2fafcc4559472b7121379ba6dd0b693`
- **Runtime Wasm/Browser validado ao vivo:** Chromium `156.0.8078.79` + Pyodide `0.27.5` (`Python 3.12.7`, `NumPy 2.0.2`, `SciPy 1.14.1`), `PathView 0.21.0`, `PathSim 0.31.0`

---

## 1. Resumo Executivo e Decisão de Gates (Fase 0)

| Gate | Descrição (`CL-DIR-001` §14.1) | Status em `PROJECT_STATE.json` | Equivalência Protocolar | Parecer F9 / Resumo Objetivo |
| :--- | :--- | :--- | :--- | :--- |
| **`G-0A`** | Núcleo Python/Pyodide & Benchmark `B-CARE-12x3` | **`ACCEPTED_BY_F9`** (`decision: "pass"`) | **PASSED / LIBERADO** | Todos os critérios §14.1 cumpridos em CPython e Chromium/Pyodide real (`r_CARE = 1.11e-15 <= 1e-9`, erro rel. P/K `<= 2.42e-15`, cold/warm separados, heartbeat UI `98 ticks`, Worker cancel+restart, zero vazamento de `PyProxy`). Restrição declarada `DEC-OPEN-03`: host de container sem homologação de notebook de referência. |
| **`G-0B`** | Capacidade Real de SDP em Wasm (`cvxpy-base + clarabel`) | **`PENDING`** (`UNAVAILABLE_IN_PROVISIONED_WASM`) | **PENDING (Bloqueado)** | `cvxpy-base` e `clarabel` não estão provisionados em `scripts/pyodide-assets.lock.json`; runtime Emscripten reporta honestamente `overall_passed=false`, `maturity="unavailable_wasm"` e `"SDP backend unavailable on WASM"`. Apenas 1 navegador testado (mínimo normativo: 2). |
| **`G-0C`** | Contrato RPC v1.0 & UI Mínima | **`PENDING`** (`CONDITIONAL_...`) | **PENDING (Parcial / Avançado)** | Paridade `MockWorkerAdapter`/`PyodideEngineClient`, monotonicidade de 20 revisões (`rev=19`), recuperação de Worker, `Fast-Preview` programático não persistido + commit, CSP real, offline reload CARE e I/O nativo UI aprovados em Chromium. Lacunas estritas de E2E em navegador real: arraste real de slider DOM, navegação por teclado, viewport mobile (`<= 900px`), fluxos de erro dimensional na UI e curvas temporais `x/u` (atualmente cobertos apenas em testes Node/TS). |
| **`G-0D`** | Persistência `.ctrlab` & Equivalência PathView `.pvm` | **`PENDING`** (`CONDITIONAL_...`) | **PENDING (Parcial / Avançado)** | Round-trip binário `.ctrlab` + reabertura UI, importação passiva segura, invariância AST de metadados e trajetórias oficiais `PathView 0.21.0`/`PathSim 0.31.0` de downloads reais LQR (`C=I`, `C!=I`, discreto `dt=0.05`, erro máx. `<= 3.33e-16`) aprovados. Lacunas estritas: pré-requisito `G-0C` pendente, caso de saturação do atuador pós-LQR via download UI não exposto/exercitado em E2E, e controlador dinâmico (`T-PVM-02`) não exposto pela UI LQR (`canonicalController()` em `web/app/shell.ts`). |

> **Nota de conformidade de schema (`scripts/project_governance.py`):** O schema normativo de `PROJECT_STATE.json` admite exclusivamente `STATUSES = {"PENDING", "ACCEPTED_BY_F9", "CHANGES_REQUESTED", "BLOCKED_BY_GATE", "BLOCKED_NEEDS_ARGON", "REJECTED_WITH_EVIDENCE"}` e os gates em `scripts/ci_gate.py` e `tests/oracles/test_release_gate_state.py` verificam `status == "ACCEPTED_BY_F9"` em conjunto com `f9_review == "accepted"` e `decision == "pass"`. Portanto, a liberação formal do Gate **`G-0A`** equivalente a `"PASSED"` é registrada como `"status": "ACCEPTED_BY_F9"`, `"f9_review": "accepted"`, `"decision": "pass"`.

O estado global de release do produto permanece **`NOT_APPROVED_FOR_STABLE_WEB_RELEASE`**, condicionado aos Gates `G-0B`–`G-0D` e ao bloqueador externo de governança de servidor **`AUD-018`** (`WP-AUDIT2-FIX-F9-PROTECTION`: branch protection desabilitada / rulesets indisponíveis por plano no GitHub).

---

## 2. Sincronização, Estado de Fila e Verificação Cruzada dos WorkPackages

### 2.1 Estado da fila em `PROJECT_STATE.json` (29 WorkPackages)
- `python3 scripts/project_governance.py` -> saída `{"accepted": 19, "corrective_packages": 18, "work_packages": 29}` (exit `0`).
- **19 `ACCEPTED_BY_F9`:** todos os 19 pacotes possuem evidência em disco (`handoff_ref` conforme Apêndice E ou `legacy_acceptance_evidence` válido em CPython local):
  1. `WP-AUDIT2-FIX-F9-GOV` (`docs/audits/handoffs/WP-AUDIT2-FIX-F9-GOV.md`)
  2. `WP-AUDIT2-FIX-F1-OPTIONAL-SDP-TEST` (`docs/audits/handoffs/WP-AUDIT2-FIX-F1-OPTIONAL-SDP-TEST.md`)
  3. `WP-AUDIT2-FIX-F1-IO-RPC` (`docs/audits/handoffs/WP-AUDIT2-FIX-F1-IO-RPC.md`)
  4. `WP-AUDIT2-FIX-F8-CONTAIN-EXPORT` (`docs/audits/handoffs/WP-AUDIT2-FIX-F8-CONTAIN-EXPORT.md`)
  5. `WP-AUDIT2-FIX-F8-NATIVE-IO` (`docs/audits/handoffs/WP-AUDIT2-FIX-F8-NATIVE-IO.md`)
  6. `WP-AUDIT2-FIX-F9-DOWNLOAD-E2E` (`docs/audits/handoffs/WP-AUDIT2-FIX-F9-DOWNLOAD-E2E.md`)
  7. `WP-AUDIT-FIX-F9-GOV` (`docs/audits/handoffs/WP-AUDIT-FIX-F9-GOV.md`)
  8. `WP-AUDIT-FIX-F1-CORE-RPC` (`docs/audits/handoffs/WP-AUDIT-FIX-F1-CORE-RPC.md`)
  9. `WP-AUDIT-FIX-F7-RPC-BRIDGE` (`docs/audits/handoffs/WP-AUDIT-FIX-F7-RPC-BRIDGE.md`)
  10. `WP-AUDIT-FIX-F6-SDP` (`docs/audits/handoffs/WP-AUDIT-FIX-F6-SDP.md`)
  11. `WP-AUDIT-FIX-F5-FML` (`docs/audits/handoffs/WP-AUDIT-FIX-F5-FML.md`)
  12. `WP-AUDIT-FIX-F8-TS-UI` (`docs/audits/handoffs/WP-AUDIT-FIX-F8-TS-UI.md`)
  13. `WP-AUDIT-FIX-F9-BUILD-CI` (`docs/audits/handoffs/WP-AUDIT-FIX-F9-BUILD-CI.md`)
  14. `WP-AUDIT-FIX-F7-OFFLINE-SW` (`docs/audits/handoffs/WP-AUDIT-FIX-F7-OFFLINE-SW.md`)
  15. `WP-AUDIT-FIX-F1-PVM-OFFICIAL` (`docs/audits/handoffs/WP-AUDIT-FIX-F1-PVM-OFFICIAL.md`)
  16. `WP-AUDIT-FIX-F1-PVM-DISCRETE-CLOCK` (`docs/audits/handoffs/WP-AUDIT-FIX-F1-PVM-DISCRETE-CLOCK.md`)
  17. `WP-02-F2-CARE-LQR` (`tests/unit/f2/test_care_lqr.py`, escopo `cpython_local_only`)
  18. `WP-07-F3-FREQ-SISO-MIMO` (`tests/unit/f3/test_frequency_siso_and_mimo.py`, escopo `cpython_local_only`)
  19. `WP-08-F4-IDENTIFICATION` (`tests/unit/f4/test_identification.py`, escopo `cpython_local_only`)
- **7 `CHANGES_REQUESTED`:** `WP-00-F9-BOOTSTRAP`, `WP-01-F1-CORE-MODELS`, `WP-03-F6-SDP-MODELING-AND-GATE0B`, `WP-04-F7-RPC-BRIDGE-WORKER`, `WP-06-F8-UI-MVP-LQR`, `WP-09-F5-FUZZY-FML-ANFIS`, `WP-10-F6-SDP-EDUCATIONAL-SOLVER` (todos reabertos pela Auditoria Externa 1 e já remediados por pacotes `WP-AUDIT-FIX-*` acima).
- **3 `BLOCKED_BY_GATE`:** `WP-05-F1-IO-CTRLAB-PVM` (bloqueado em `G-0D`), `WP-AUDIT-FIX-F9-WASM-GATES` (bloqueado em `G-0B` / `G-0D`), `WP-AUDIT2-FIX-F9-PROTECTION` (bloqueado por servidor externo `AUD-018`).

### 2.2 Resultados das suítes executadas diretamente no commit `3ce128a6`

| Suíte / Verificação | Comando | Resultado Observado |
| :--- | :--- | :--- |
| Governança & Invariantes | `python3 scripts/project_governance.py` | **PASS** (`accepted=19`, `corrective=18`, `total=29`) |
| TypeScript & Testes Unitários Web (F7/F8) | `npm --prefix web run typecheck && npm --prefix web test` | **PASS** (`24` arquivos `.ts` sem erros; **`51/51`** testes unitários) |
| Integração & Oráculos Node | `node --test tests/integration/*.test.mjs tests/oracles/*.test.mjs` | **PASS** (**`21/21`**) |
| Unidade Python F1 (Core/Diagnostics/IO) | `pytest tests/unit/f1 -v` | **PASS** (**`97 passed`**) |
| Unidades F2–F6, Oráculos e Integração | `pytest tests/unit/f2 tests/unit/f3 tests/unit/f4 tests/unit/f5 tests/unit/f6 tests/oracles tests/integration -v` | **PASS** (**`224 passed`**) |
| Perfil CI `core_no_sdp` (`scripts/requirements-core.lock`) | `python scripts/ci_math.py core_no_sdp` | **PASS** (**`277 passed, 0 skipped`**) |
| Perfil CI `sdp_available` (`scripts/requirements-ci.lock`) | `python scripts/ci_math.py sdp_available` | **PASS** (**`113 passed, 0 skipped`**) |
| Fixtures Ouro, Schemas & Assets | `python scripts/verify_fixtures.py` | **PASS** (`11` schemas Draft 2020-12, `7` fixtures ouro SHA-256 + schema, `4` exemplos, `32` assets locais) |
| Build & Reprodutibilidade | `python scripts/build_release.py --verify && python scripts/check_reproducible.py` | **PASS** (2 builds independentes com manifest e hashes idênticos) |
| Suítes Reais Browser / Wasm / E2E / Sec / Perf / Meta | `CONTROLLAB_CHROMIUM=/usr/bin/chromium pytest tests/wasm/ tests/e2e/ tests/security/ tests/performance/ tests/metamorphic/ -v` | **PASS** (**`19 passed, 0 failed, 0 skipped`** em `210.08 s`, `1` aviso depreciação `anyio`) |
| Auditoria direta de `PyProxy` em Chromium/Pyodide | Probe `app.client` com 2 chamadas `B-CARE-12x3` | **PASS** (`before: activeProxies=0, created=2, destroyed=2` → `after: activeProxies=0, created=6, destroyed=6, activeLabels=[]`) |

---

## 3. Auditoria Detalhada dos Gates da Fase 0 (`CL-DIR-001` §6, §14.1 e Apêndice C)

### 3.1 Gate `G-0A` — Núcleo Python/Pyodide & Benchmark `B-CARE-12x3` → **LIBERADO (`ACCEPTED_BY_F9` / `decision: "pass"`)**

| Critério Normativo (`CL-DIR-001` §14.1 & Apêndice C) | Evidência Verificada no Commit `3ce128a6` | Situação |
| :--- | :--- | :--- |
| Tipos mínimos `StateSpace`, `Result`, proveniência e imutabilidade | `tests/unit/f1/` (`97 passed`), `T-CORE-01..03`; imutabilidade de revisão e arrays read-only verificadas | **CONFORME** |
| Worker Pyodide `0.27.5` real com NumPy `2.0.2` / SciPy `1.14.1` e wheel idêntico ao CPython | `wheel-source-identity.json` confirma 62 módulos sem divergência; manifest SHA-256 `94c136ae...` verificado no harness | **CONFORME** |
| Paridade numérica CPython ↔ Pyodide em `B-CARE-12x3` (`T-CARE-02`) com $r_{\text{CARE}} \le 10^{-9}$ | `test_care_12x3_cpython_pyodide_parity`: `P_relative_error = 2.246921173006027e-15`, `K_relative_error = 2.4176488128604944e-15`, `independent_rCARE = 1.1066184246108006e-15 <= 1e-9`, autovalores de malha fechada estritamente negativos | **CONFORME** |
| Rejeição PBH não estabilizável (`T-CARE-03`) e congruência por similaridade (`T-CARE-04`) no Wasm | `test_unstabilizable_plant_through_real_rpc` retorna `status="failure"`, `HYPOTHESIS_VIOLATED`, `result=null`; `test_wasm_similarity.py` valida `J = 4.75` vs `4.749999999999998` | **CONFORME** |
| Tempos cold e warm medidos separadamente + responsividade da UI | `test_care_12x3_cold_warm_and_ui_heartbeat`: `runtime_init_ms = 7354.4 ms` (`T_init_pyodide = 2393.4 ms`, `T_import_packages = 1623.0 ms`), `first_rpc_ms = 142.6 ms` (`T_first_call = 141.7 ms`), `median_warm_ms = 20.65 ms`, `p95_warm_ms = 40.45 ms`, `variation_std_ms = 9.23 ms`, `ticks = 98 > 0` | **CONFORME** *(com restrição explícita `DEC-OPEN-03`: hardware container host; sem meta de notebook de referência aprovada)* |
| Cancelamento/reinício de Worker com recuperação do último snapshot confirmado e sem vazamento de `PyProxy` | `test_worker_cancel_restart_recovers_confirmed_snapshot` preserva snapshot e emite `worker_recovered`; probe ao vivo no Chromium confirma `activeProxies == 0` e `totalCreated == totalDestroyed == 6` após RPCs reais | **CONFORME** |

**Parecer F9 para `G-0A`:** **Aprovado (`ACCEPTED_BY_F9`, `decision: "pass"`).**

---

### 3.2 Gate `G-0B` — Capacidade Real de SDP em Wasm (`cvxpy-base + clarabel`) → **MANTIDO `PENDING`**

| Critério Normativo (`CL-DIR-001` §14.1 & Apêndice C) | Evidência Verificada no Commit `3ce128a6` | Situação |
| :--- | :--- | :--- |
| Modelagem canônica (`sdpvar/bmat/svec`), fallback LP estruturalmente diagonal e verificador primal/dual independente (`T-SDP-A1..D2`) em CPython | `scripts/ci_math.py sdp_available` (`113 passed, 0 skipped`) e `core_no_sdp` (`277 passed, 0 skipped`, validando `SOLVER_UNAVAILABLE` sem ganho falso) | **CONFORME (CPython)** |
| Carregamento e resolução de cones PSD no runtime Pyodide/Wasm (`cvxpy-base` + `clarabel`) | `scripts/pyodide-assets.lock.json` não inclui `cvxpy-base` nem `clarabel`; `test_g0b_runtime_reports_unavailable_honestly` confirma `platform="emscripten"`, `cvxpy_present=false`, `clarabel_present=false`, `overall_passed=false`, `maturity="unavailable_wasm"` e `"SDP backend unavailable on WASM"` | **NÃO DEMONSTRADO (WASM)** |
| Matriz mínima em **pelo menos 2 navegadores** distintos (`scripts/project_governance.py` linha 221) | Apenas Chromium `156.0.8078.79` (e `153.0.8010.0` em log anterior) foi executado | **PENDENTE (< 2 browsers)** |

**Parecer F9 para `G-0B`:** **Mantido `PENDING` (`UNAVAILABLE_IN_PROVISIONED_WASM`).** Os pacotes locais `WP-AUDIT-FIX-F6-SDP` e `WP-AUDIT-FIX-F9-BUILD-CI` já estão `ACCEPTED_BY_F9`; o bloqueio reside exclusivamente em `WP-AUDIT-FIX-F9-WASM-GATES` / achado `F9-WASM-SDP-001`.

---

### 3.3 Gate `G-0C` — Contrato RPC v1.0 & UI Mínima → **MANTIDO `PENDING` (Avançado / Lacunas E2E Estritas)**

| Critério Normativo (`CL-DIR-001` §14.1 & Apêndice C) | Evidência Verificada no Commit `3ce128a6` | Situação |
| :--- | :--- | :--- |
| Equivalência de contrato entre `MockWorkerAdapter` e `PyodideEngineClient` (`F7-PARITY-01`, códigos de erro tipados, `WorkerModelStore`) | Suíte F7/Web (`51/51` testes Node/TS) + `test_unstabilizable_plant_through_real_rpc` em Pyodide real | **CONFORME** |
| Controle monotônico de `project_revision`, descarte de respostas obsoletas e recuperação após cancelamento (`T-RPC-01/02`) | `test_twenty_revisions_only_current_commits` (`rev=19`, apenas 1 `request_committed`) e `test_worker_cancel_restart_recovers_confirmed_snapshot` no Chromium/Pyodide real | **CONFORME** |
| `Fast-Preview` nunca persiste nem atualiza `K` confirmado até commit real (`T-UI-01`), CSP real e funcionamento offline pós-reload (`T-SEC-01`) | `test_preview_is_never_persisted_then_real_commit` (`before_rev=1`, `during_rev=1`, `after_rev=2`), `test_shipped_csp_blocks_inline_and_external_without_breaking_runtime` e `test_offline_real_calculation_after_reload` | **CONFORME (API do controlador)** |
| Exercício DOM real completo de `Fast-Preview` (arraste real em `#lqr-q-slider`), erros dimensionais na UI, renderização de curvas temporais `x/u`, navegação por teclado e responsividade mobile (`<= 900px`) em navegador real | `test_preview_is_never_persisted_then_real_commit` invoca `lqr.pointerDown/Move/Up` via `page.evaluate`, e curvas `x/u`, teclado, mobile e erros dimensionais são testados apenas em JSDOM/Node (`tests/unit/f8/ui_mvp_lqr.test.ts`), sem ensaio E2E real no Playwright | **LACUNA ESTRITA E2E** |

**Parecer F9 para `G-0C`:** **Mantido `PENDING`** com veredito factual atualizado (`CONDITIONAL_RPC_OFFLINE_AND_NATIVE_IO_VERIFIED_DOM_DRAG_MOBILE_KEYBOARD_E2E_PENDING`). Os 8 WorkPackages remediados (`WP-AUDIT-FIX-F7-RPC-BRIDGE`, `WP-AUDIT-FIX-F8-TS-UI`, `WP-AUDIT-FIX-F9-BUILD-CI`, `WP-AUDIT-FIX-F7-OFFLINE-SW`, `WP-AUDIT2-FIX-F1-IO-RPC`, `WP-AUDIT2-FIX-F8-CONTAIN-EXPORT`, `WP-AUDIT2-FIX-F8-NATIVE-IO`, `WP-AUDIT2-FIX-F9-DOWNLOAD-E2E`) e os achados `AUD-001..003/010/014/019..021` foram saneados; resta fechar a cobertura E2E completa de UI em `WP-AUDIT-FIX-F9-WASM-GATES`.

---

### 3.4 Gate `G-0D` — Persistência `.ctrlab` & Equivalência Dinâmica PathView `.pvm` → **MANTIDO `PENDING` (Pré-requisito `G-0C`, Saturação UI & `T-PVM-02`)**

| Critério Normativo (`CL-DIR-001` §14.1 & Apêndice C) | Evidência Verificada no Commit `3ce128a6` | Situação |
| :--- | :--- | :--- |
| Gate pré-requisito `G-0C` aceito (`CL-DIR-001` §14.1) | `G-0C` ainda `PENDING` | **PENDENTE** |
| Round-trip binário `.ctrlab` ZIP, importação passiva segura e reabertura fiel pela UI (`T-IO-01/02`) | `test_native_downloads.py` baixa ZIP real via UI `#btn-export-ctrlab` → reabre em CPython `load_ctrlab` e via `#ctrlab-file-input` preservando matrizes, `dt`, unidades e `project_revision`; `test_passive_zip_fml_pvm_in_pyodide` bloqueia traversal (`VALIDATION_ERROR`), XXE (`IMPORT_UNTRUSTED_CODE`) e `codeContext` sem execução | **CONFORME** |
| Equivalência dinâmica de downloads `.pvm` reais da UI com conversor `PathView 0.21.0` e integrador `PathSim 0.31.0` + proteção AST contra injeção por metadados (`T-PVM-01`) | `test_native_downloads.py`: `identity-negative` (`501` amostras, erro máx. `3.330669e-16`), `partial-positive` (`501` amostras, erro máx. `3.330669e-16`), `clocked-negative` (`dt=0.05`, `97` amostras, erro máx. `y=2.220446e-16`, `u=0.0`, `x=0.0`), `test_project_metadata_preserves_converted_ast` com AST idêntica pós-conversão | **CONFORME (LQR estático contínuo/discreto)** |
| Comparação com saturação do atuador ativada após LQR não saturado via modelo exportado pela UI (`CL-DIR-001` §14.1) | Coberto em ensaios Python/PathView internos (`tests/unit/f1/`), porém não há controle na UI LQR nem ensaio E2E de download `.pvm` com saturação ativada | **LACUNA ESTRITA E2E** |
| Controlador dinâmico (`T-PVM-02`) exportável a partir do fluxo UI E2E | `canonicalController()` em `web/app/shell.ts` emite apenas `StateFeedbackController`; `DynamicController` verificado em `tests/unit/f1/`, porém fora da tela LQR atual (`WP-AUDIT2-FIX-F9-DOWNLOAD-E2E.md`) | **LACUNA ESTRITA UI/E2E** |

**Parecer F9 para `G-0D`:** **Mantido `PENDING`** com veredito factual atualizado (`CONDITIONAL_CTRLAB_AND_PVM_LQR_DOWNLOADS_VERIFIED_G0C_SATURATION_AND_T_PVM_02_UI_PENDING`).

---

## 4. Bloqueio de Governança de Servidor (`AUD-018`) e Próximos Passos

1. **`G-0B` (`WP-AUDIT-FIX-F9-WASM-GATES` / `F9-WASM-SDP-001`):** Provisionar wheels Wasm/Pyodide reais e assinados para `cvxpy-base` + `clarabel` em `scripts/pyodide-assets.lock.json` e executar a matriz completa `T-SDP-A1..D2` em **>= 2 navegadores**.
2. **`G-0C` (`WP-AUDIT-FIX-F9-WASM-GATES`):** Adicionar teste Playwright real cobrindo arraste de slider DOM (`#lqr-q-slider`), navegação por teclado, viewport mobile (`<= 900px`), rejeição visual de dimensões inválidas e verificação visual/estrutural dos plots `x/u` no navegador.
3. **`G-0D` (`WP-AUDIT-FIX-F9-WASM-GATES` + pré-requisito `G-0C`):** Expor parâmetro de saturação do atuador (ou fluxo dedicado) e controlador dinâmico (`DynamicController`, `T-PVM-02`) no exportador UI, validando os bytes baixados com `PathView`/`PathSim` após aprovação de `G-0C`.
4. **`AUD-018` (`WP-AUDIT2-FIX-F9-PROTECTION`):** Ação administrativa externa do proprietário do repositório para habilitar branch protection em `main`, status checks obrigatórios e aprovação independente `@f9-integration-qa`, viabilizando a futura promoção de release estável.
