# Handoff e Parecer F9 — `WP-PHASE7-02-F1-PVM-PATHSIM-DEC07`

- **WorkPackage**: `WP-PHASE7-02-F1-PVM-PATHSIM-DEC07`
- **Frente Produtora**: `F1 (f1-core-io)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `da3bf814f10324aa2dbd81583ce03c8ad14a3431`
- **Decisão Arquitetural Associada**: `docs/architecture/ADR-013-pvm-nonlinear-boundary-and-pathsim-export.md` (`DEC-OPEN-07`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-22T20:22:56Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Todos os arquivos alterados ou criados pela Frente F1 pertencem estritamente a `allowed_paths` (`control_lab/io/`, `control_lab/core/`, `tests/unit/f1/`):

| Arquivo F1 Auditado | SHA-256 | Observações |
|---|---|---|
| `control_lab/io/pvm.py` | `5a4e2ec2113761ef9730d27115d58ca0b5ed3746ff214678a5fb7268cc4951bc` | Geradores determinísticos passivos PathSim `0.31.0` (`_emit_ts_pdc_pathsim_script`, `_emit_fuzzy_pathsim_script`, `generate_pathsim_script`), registro `dec_open_07_decision: "ADR-013"` e preservação estrita da fronteira passiva `.pvm` (`R-21`) e bloqueio `polytopic_uncertain + PDC` (`ADR-006`). |
| `control_lab/core/rpc.py` | `082e8e2f2409a9d209183f050ee196701b611626bc6a272bf56ea056de98b8c6` | Novo RPC `io.export_pathsim_script` registrado em `SUPPORTED_OPERATIONS`, `_DISPATCH_TABLE` e `core.capabilities`, validando payload estrito (inline ou `*_ref` no store) e garantindo `code_executed=False` e `requires_explicit_user_execution=True`. |
| `tests/unit/f1/test_dec_open_07_pathsim.py` | `9010d882e0d25b616a592ceb6cfcbb09ed4c5d95c74e3391aec3eef479f42926` | Validação real ponta a ponta em PathView `0.21.0` + PathSim `0.31.0`: TS-PDC vs `solve_ivp` (`<1e-4`), Fuzzy Mamdani/TS/multi-saída vs `fuzzy.evaluate` (`<1e-4`), MIMO $H_\infty$ `DynamicController` via `.pvm` → PathView → PathSim vs `solve_ivp` (`<1e-4`), contrato RPC e bloqueio `HYPOTHESIS_VIOLATED`. |

### Verificação Estática de Segurança (`R-21`)
- Zero ocorrências de `eval(` ou `exec(` em `control_lab/io/pvm.py` e `control_lab/core/rpc.py`.
- Fronteira passiva `.pvm` preservada: `make_pvm` continua rejeitando `TSStateSpace`, `FuzzySystem` e `PDCController` com `UnsupportedModelError`.
- Scripts gerados por `generate_pathsim_script` e `io.export_pathsim_script` jamais são executados durante geração/exportação (`code_executed=False`, `requires_explicit_user_execution=True`), e o script Fuzzy gerado não importa `control_lab` (verificado por AST).
- Zero alterações em `contracts/fixtures/*` ou `contracts/schemas/*`.

---

## 2. Evidência de Execução Independente (F9)

1. **Suíte Unitária F1 (`T-IO-01`, `T-PVM-01`)**:
   - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f1/ -v` → **`136/136` PASSED** (`0` failed, `0` skipped), incluindo todos os cenários reais de `tests/unit/f1/test_dec_open_07_pathsim.py` contra `pathview 0.21.0` e `pathsim 0.31.0`.
2. **Validação de Schema e Fixtures Ouro**:
   - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py` → 11 schemas Draft 2020-12 válidos; 7/7 fixtures ouro OK; 4/4 exemplos OK.
   - Resposta de `io.export_pathsim_script` validada contra `contracts/schemas/rpc_response.schema.json`.
3. **Build Wheel e Execução Real em Navegador (Pyodide Wasm)**:
   - `npm --prefix web run build` empacota `control_lab-1.0.0-py3-none-any.whl` com `io.export_pathsim_script`; validado em Chromium real (`tests/e2e/test_ux_refactor_cl_ux_dir_001.py`, `13/13` PASSED).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `io.export_pathsim_script` validado contra `rpc_response.schema.json` e consumido pela F8 (`web/features/views/fuzzy_view.ts`). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Tanto `generate_pathsim_script` quanto `io.export_pathsim_script` retornam `Result`/`RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance`, `warnings` e erros tipados (`HYPOTHESIS_VIOLATED`, `VALIDATION_ERROR`, `UNSUPPORTED_MODEL`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Trajetórias PathSim `0.31.0` confrontadas com integração de referência independente `scipy.integrate.solve_ivp` (`DOP853`, `rtol=1e-10`) e `control_lab.fuzzy.evaluate`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Simulação real no motor externo não modificado `pathview 0.21.0` + `pathsim 0.31.0` comparada a `solve_ivp` independente (erro `<1e-4`), e avaliador NumPy puro confrontado com `fuzzy.evaluate`. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações estritamente restritas a `control_lab/io/pvm.py`, `control_lab/core/rpc.py` e `tests/unit/f1/test_dec_open_07_pathsim.py`; fixtures ouro intactas. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | A geração passiva de scripts funciona identicamente em CPython e Pyodide Wasm (confirmado em E2E Chromium na Aba 5); a execução do script gerado é explicitamente offline em CPython/PathSim (`ADR-013`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhum breaking change em schemas; contrato aditivo de operação RPC e fronteira `.pvm`/PathSim formalizados na `ADR-013`. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Evidência completa (`136/136` F1, hashes SHA-256, versões fixadas `pathview 0.21.0` / `pathsim 0.31.0` e margens `<1e-4`) documentada neste handoff e na `ADR-013`. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | A exportação de script PathSim emite aviso explícito `DEC_OPEN_07_FALLBACK_SCRIPT` e `requires_explicit_user_execution=True` sem mascarar execução externa como simulação nativa `.pvm`. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `TSStateSpace`/`FuzzySystem`/`PDCController` em `make_pvm` emitem `UnsupportedModelError` com `next_step`; `polytopic_uncertain + PDC` bloqueado com `HYPOTHESIS_VIOLATED` (`ADR-006`). | CONFORME |
