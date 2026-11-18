# Handoff e Parecer F9 — `WP-V1-F8-TYPED-WORKSPACE-INPUTS`

- **WorkPackage**: `WP-V1-F8-TYPED-WORKSPACE-INPUTS`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `747f9b548f3fa88fbb13bf951f1d0f297019f5a0`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-18T21:36:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações do produtor `F8` ficaram estritamente restritas aos diretórios autorizados em `allowed_paths` (`web/app/`, `web/features/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/features/typed_workspace.ts` | `ca79fc73633289aa6f2367205493b2de3bb2e8cae0d3a6c0faaf02f009d2ef31` | `TypedObjectWorkspace`, validação canônica de DTOs (`Dataset`, `TransferFunction`, `StateSpace`, `IdentifiedModel`, `FuzzySystem`, e discriminantes TS `ts_measured`, `polytopic_uncertain`, `ts_partially_observed`), composição de payload por operação, navegação por teclado, proteção contra sobrescrita por revisão antiga (síncrona/assíncrona) e fluxo `core.reuse_model` com registro explícito. |
| `web/features/project_tabs.ts` | `2ec292c76e8fe3cb2fddfca605715a32c24cec7fed262f001eeb538875e69d21` | Integração de `ProjectTabsController.executeTool` com `TypedObjectWorkspace.prepareToolExecution` e captura de modelos pendentes (`recordIdentifiedModelResult` / `recordReuseResult`) sem auto-registro. |
| `web/features/tool_catalog.ts` | `91c6e8b4f44d50f2919474ee971083a2643366b0533df3c51453499626af3f3f` | Descritores declarativos para `identification.fit_subspace`, `identification.validate_model`, entradas opcionais em `fuzzy.evaluate_surface` e template `ts_pdc_stabilization` / `regional_pole_placement` (`radius`, `premise_estimator`) em `optimization.solve`. |
| `web/app/shell.ts` | `3e67d3199c7f6983b74a67e07433b64684792749a2cbceca27300273a9ae0cec` | Instanciação de `TypedObjectWorkspace`, espelhamento da planta ativa do LQR, `applySelectedPlantToLqr()`, reidratação pós-recuperação de Worker (`ready` / `worker_recovered`), contexto explícito de `project_id`/`project_revision` em `exportSdpScript` e preservação de `"io-import"` / `0` em `fileRequest` para `io.import_ctrlab`. |
| `web/app/main.ts` | `c5b2bdec0d76d060f1ed3aa9342fefe6fe6f80e33239d37dfab58807c8711408` | Painel `#typed-workspace-panel` com registro JSON canônico, seletores `<select data-action="select-typed-ref" data-role="...">` operáveis por teclado e DOM, botões de derivação `core.reuse_model` e registro explícito de pendentes, remoção da injeção indiscriminada de `plant_ref` em `execute-tool` / `export-sdp`, e preservação de campos numéricos opcionais em branco sem `NaN`. |
| `tests/unit/f8/typed_workspace_inputs.test.ts` | `4a8b5765808e91314c4821aa48a8b14836a5f8805094d2c08fed61894a84a388` | 5 suítes unitárias cobrindo `T-CORE-01` e `T-RPC-01`, validação estrutural/dimensional de DTOs, bloqueio de ausência/incompatibilidade de tipos, teclado + corrida assíncrona de revisões, fluxo `fit_arx -> registerPendingIdentifiedModel -> core.reuse_model -> registerPendingDerivedModel -> SISO/LQR` e DOM `mountControlLabApp`. |

Nenhum arquivo em `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/`, `control_lab/` ou `web/worker/` foi modificado pelo produtor (`contracts/fixtures/checksums.sha256` permanece intacto com SHA-256 `4b7a39a4ad5d8eb6b48d2d28d8e8a3673e38105bce057909dbdb29884ef0cc7a`).

---

## 2. Verificação Independente dos Critérios do Pacote (`docs/audits/NEXT_QUEUE_2026-11-17.md`)

1. **Remoção da injeção indiscriminada do `StateSpace` LQR (`R-03`, `R-06`, `T-RPC-01`)**:
   - Em `web/app/main.ts`, o handler `execute-tool` deixou de injetar `extraPayload: { plant_ref: { id: plant.id, revision: plant.revision } }` indiscriminadamente e passou a delegar a `tabsCtrl.executeTool`, que consulta `typedWorkspace.prepareToolExecution(desc.operation, vm.validation.sanitized, ...)`.
   - Ferramentas de identificação (`identification.fit_arx`, `identification.fit_oe`, `identification.fit_subspace`) exigem `dataset_ref` (e `val_dataset_ref` opcional) do tipo `Dataset`; `identification.validate_model` exige `model_ref` (`IdentifiedModel`/`TransferFunction`/`StateSpace`) e `val_dataset_ref` (`Dataset`); `fuzzy.evaluate` exige `system_ref` (`FuzzySystem`); `optimization.solve` com `ts_pdc_stabilization` exige `ts_model_ref` (`ts_measured`, `polytopic_uncertain` ou `ts_partially_observed`).
2. **Validação estrita de DTOs canônicos e discriminantes TS (`T-CORE-01`)**:
   - `validateTypedCanonicalDto` valida dimensões, `dtype: "float64"`, `order: "C"`, monotonia temporal `Dataset.t`, compatibilidade de amostras `[N, m]`/`[N, p]`, domínio `dt`/`variable` em `TransferFunction`, variáveis/regras em `FuzzySystem`, e discriminantes reais de `TSStateSpace` (`ts_measured`, `polytopic_uncertain`, `ts_partially_observed`), rejeitando o discriminante inválido `"TSStateSpace"` com `UNSUPPORTED_MODEL`.
3. **Fluxo explícito `core.reuse_model` sem auto-registro (`R-26`, `R-27`)**:
   - Resultados de `identification.fit_*` e `core.reuse_model` ficam em estado pendente (`registration_required: true`) até ação explícita do usuário (`registerPendingIdentifiedModel` / `registerPendingDerivedModel`), habilitando consumo subsequente em `frequency.*`, `statespace.*` e aplicação direta ao workspace LQR (`applySelectedPlantToLqr`) sem cópia manual de matrizes.
4. **Teclado, revisões e fronteira de escopo**:
   - `selectRef` bloqueia sobrescrita de revisão mais recente por revisão antiga do mesmo `id` (tanto síncrona quanto em corrida assíncrona fora de ordem via `selectionVersionByRole`).
   - `handleRoleKeyNavigation` permite seleção completa por teclado (`ArrowDown`, `ArrowUp`, `Home`, `End`).
   - Cards sem handler no runtime ativo (ex.: `fuzzy.evaluate` e `identification.fit_subspace` no `MockWorkerAdapter`) permanecem honestamente indisponíveis (`maturity.available === false`).
   - O escopo de persistência `.ctrlab` foi mantido inalterado conforme a fronteira normativa do pacote.

---

## 3. Evidência de Execução (Node/TypeScript + Navegador Real Playwright/Pyodide Wasm)

- **Typecheck e Testes Unitários Web (`f8` e `all`)**:
  - `npm --prefix web run typecheck`: `PASS` (0 erros).
  - `node scripts/run_web_tests.mjs --scope f8`: `PASS` (`26/26` testes em 2 arquivos).
  - `PATH="/home/antigravity/.venv/bin:$PATH" PYTHON=/home/antigravity/.venv/bin/python node scripts/run_web_tests.mjs --scope all`: `PASS` (`89/89` testes em 7 arquivos).
- **Integridade de Fixtures e Schemas**:
  - `python3 scripts/verify_fixtures.py`: `PASS` (todas as 9 fixtures ouro conferem com `checksums.sha256` e todos os schemas Draft 2020-12 são válidos).
- **Suíte Real de Navegador (`tests/wasm/` + `tests/e2e/`) e Probe F9 Dedicado**:
  - `pytest tests/wasm/ tests/e2e/ -v`: `26/26` testes aprovados em Chromium real com Worker Pyodide Wasm e wheel local `control_lab-1.0.0-py3-none-any.whl` (incluindo `test_offline_scripts_download_without_committed_solution`).
  - Probe real-browser F9 sobre `web/dist/` confirmou no Chromium `151.0.7922.34` com Pyodide Wasm:
    1. Tentativa de `identification.fit_arx` sem `Dataset` falha fechado na UI exibindo alerta `VALIDATION_ERROR` em `#controllab-error-slot` sem enviar `StateSpace` LQR.
    2. Registro de dois objetos `Dataset` (`ds-browser-1#1` e `ds-browser-2#2`) via `#typed-object-json` + `#btn-register-typed-object` e seleção de `ds-browser-2#2` via tecla `ArrowDown` em `#typed-select-dataset`.
    3. Execução de `identification.fit_arx` no Worker Pyodide gerando `IdentifiedModel` pendente (`idmod-cff540cf0018#0`, `registered: false`), seguido de registro explícito via `#btn-register-pending-identified`.
    4. Derivação via `#btn-reuse-model` (`target_kind: "StateSpace"`) gerando `StateSpace` discreto pendente (`dt: 0.1`, `registered: false`), seguido de registro explícito via `#btn-register-pending-derived`.
    5. Consumo do `StateSpace` derivado em `siso.bode_nyquist` (`domain: "discrete"`, `dt: 0.1`) e aplicação direta ao workspace LQR via `#btn-apply-selected-to-lqr`.

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | `git status --short` lista exclusivamente `web/app/main.ts`, `web/app/shell.ts`, `web/features/project_tabs.ts`, `web/features/tool_catalog.ts`, `web/features/typed_workspace.ts` e `tests/unit/f8/typed_workspace_inputs.test.ts`, todos dentro de `["web/app/", "web/features/", "tests/unit/f8/"]`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado; `contracts/fixtures/checksums.sha256` intacto (`4b7a39a4ad5d8eb6b48d2d28d8e8a3673e38105bce057909dbdb29884ef0cc7a`); zero diff em `contracts/` e `tests/oracles/`. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | `TypedObjectWorkspace.reuseModel` e `ProjectTabsController.executeTool` trafegam exclusivamente envelopes `RpcRequest`/`RpcResponse` v1.0 validados, preservando `provenance`, `diagnostics`, `assumptions` e `warnings` do motor Python/Worker. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma tolerância científica foi relaxada ou alterada; a UI valida dimensões, tipos finitos e monotonia temporal estrita antes do envio RPC. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `validateTypedCanonicalDto`, `selectRef` e `prepareToolExecution` validam `dt`, variável (`s`, `z`, `z^-1`), shapes de tensores e compatibilidade de `kind`, lançando `ControlLabBridgeError` com códigos normativos (`VALIDATION_ERROR`, `DIMENSION_MISMATCH`, `UNSUPPORTED_MODEL`). | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Testados em `tests/unit/f8/typed_workspace_inputs.test.ts`: discriminante inválido `"TSStateSpace"`, `Dataset` com comprimentos incompatíveis, `TransferFunction` contínua com variável discreta, vértices TS heterogêneos, execução sem insumo registrado e tentativa de downgrade por revisão antiga síncrona/assíncrona. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Toda comunicação com o Worker ocorre pelos métodos formais da F7 (`registerObject`, `getObject`, `execute`, `exportProject`) com clones JSON finitos; suíte `F7-PYPROXY-01/02` (`89/89`) e suíte Wasm (`26/26`) aprovadas. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Seletores tipados possuem `<label>`, `aria-label`, classe `.touch-control`, navegação por teclado (`ArrowDown`/`ArrowUp`/`Home`/`End`), restauração de foco na re-renderização, anúncios `aria-live` e preservação integral do bloqueio de exportação LQR durante `Fast-Preview`. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não é entrega da `F6`, mas a integração da aba `optimization_lmi` (`optimization.solve` e `export-sdp`) preserva integralmente o contrato de 5 dimensões da `F6` e a seleção tipada de `plant_ref` (LTI) ou `ts_model_ref` (TS PDC). | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `T-CORE-01` e `T-RPC-01` aprovados; `node scripts/run_web_tests.mjs --scope f8` (`26/26`), `--scope all` (`89/89`) e `pytest tests/wasm/ tests/e2e/` (`26/26`) passaram com zero falhas e zero skips. | CONFORME |

---

## 5. Assinatura da Auditoria Independente F9

- **Revisor independente**: `f9-integration-qa` (executado em passe de auditoria isolado conforme protocolo de contingência de quota de subagente do `AGENTS.md`, com verificação independente por hashes SHA-256, `scripts/verify_fixtures.py`, `run_web_tests.mjs --scope all` e probe Playwright + Pyodide Wasm real sobre o bundle compilado `web/dist/`).
- **Commit SHA auditado**: `747f9b548f3fa88fbb13bf951f1d0f297019f5a0`
- **Data (UTC)**: `2026-11-18T21:36:00Z`
- **Parecer F9**: accepted
