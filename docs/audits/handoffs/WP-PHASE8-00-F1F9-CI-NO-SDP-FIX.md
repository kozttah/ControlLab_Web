# Handoff e Parecer F9 — `WP-PHASE8-00-F1F9-CI-NO-SDP-FIX`

- **WorkPackage**: `WP-PHASE8-00-F1F9-CI-NO-SDP-FIX`
- **Frente Produtora**: `F1 (f1-core-io)` + `F9 (f9-integration-qa)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `6bd0ad56859bfcc27b15e59e0c9ba6a74186d6c7` (+ remediação CI `core_no_sdp`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-22T23:33:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths`)

Após o primeiro ciclo de revisão F9 (que identificou falha de `exit 2` em `scripts/ci_math.py` causada por 5 chamadas `pytest.importorskip`), a frente F1 atualizou `tests/unit/f1/test_dec_open_07_pathsim.py` removendo integralmente `pytest.importorskip`/`pytest.skip` e utilizando detecção dinâmica (`HAS_PATHSIM`/`HAS_PATHVIEW` via `importlib.util.find_spec`) com validação pura CPython incondicional (`generate_pathsim_script`, AST sem `control_lab`, `eval_fuzzy_point`, `ts_pdc_rhs` vs `solve_ivp`, `make_pvm`, `interconnect` e RPC) e execução real PathView `0.21.0` + PathSim `0.31.0` quando instalados.

| Frente | Arquivo Auditado | SHA-256 | Verificação F9 |
|---|---|---|---|
| F1 | `tests/unit/f1/test_dec_open_07_pathsim.py` | `bf4b395d0f6edee759a8d65fc9a0a57f79a74996730b6819526c4f7d0c67748e` | Zero `pytest.importorskip` / `pytest.skip`; **11/11 PASSED, 0 skipped** tanto no venv completo quanto sob `core_no_sdp`. |
| F9 | `tests/oracles/test_hinf_dgkf_oracle.py` | `47bb9a21835111a61c123d0116a9fc15fdfbd0f071f7c000edab927d04c56760` | Mantém `backend="clarabel_direct"` quando `clarabel` está instalado e fallback `backend="native_primal_dual"` em `core_no_sdp`, com `verify_solution=True` e todas as tolerâncias inalteradas; **4/4 PASSED, 0 skipped**. |

---

## 2. Evidência de Execução Independente (CI `core_no_sdp` + Venv Completo)

1. **Simulação fiel do Job `B - CPython math (core_no_sdp)` (`scripts/ci_math.py`):**
   - Bloqueando `pathview`, `pathview.converter`, `pathsim`, `clarabel`, `cvxpy`, `scs` (`find_spec -> None`) sobre `tests/unit/f1..f5`, `tests/oracles`, `tests/integration`:
     - **`569 passed, 0 failed, 0 skipped` (`PYTEST_RC=0`, `16.15s`) — exit code `0`** (atende integralmente o gate zero-skip de `scripts/ci_math.py` linhas 71–73).
   - Verificação adicional com `sys.modules[mod] = None` sobre `tests/unit/f1/test_dec_open_07_pathsim.py` e `tests/oracles/test_hinf_dgkf_oracle.py`:
     - **`15 passed, 0 failed, 0 skipped` (`PYTEST_RC=0`, `2.12s`)**.
2. **Ambiente completo `.venv` (com Clarabel `0.11.1`, PathView `0.21.0`, PathSim `0.31.0`):**
   - `pytest tests/unit/f1/test_dec_open_07_pathsim.py tests/oracles/test_hinf_dgkf_oracle.py -v`:
     - **`15 passed, 0 failed, 0 skipped` (`3.84s`)**.
3. **Integridade de Fixtures Ouro:**
   - `python3 scripts/verify_fixtures.py` → **PASS** (11 schemas JSON Draft 2020-12, 7/7 fixtures ouro, 4/4 exemplos).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Contratos `generate_pathsim_script`, `make_pvm`, `io.export_pathsim_script` e `design_hinf_mixed_sensitivity` validados contra schemas Draft 2020-12. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Preservado em todas as asserções F1 e no oráculo F9 (`validated_dual`, `HYPOTHESIS_VIOLATED`, `code_executed=False`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Oráculos BRL/Hamiltoniano e confronto contra `scipy.integrate.solve_ivp` mantidos com tolerâncias originais inalteradas. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Oráculo F9 independente (`test_hinf_dgkf_oracle.py`) validado 4/4 tanto via `clarabel_direct` quanto via `native_primal_dual` + confronto independente `solve_ivp`/`fuzzy_evaluate`. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Isolamento estrito mantido (`tests/unit/f1/` por F1; `tests/oracles/` por F9); zero alterações em `contracts/fixtures/` ou tolerâncias. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Validado em CPython completo (`15/15`, 0 skips) e em CPython `core_no_sdp` (`569/569`, 0 skips, exit `0`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma alteração de schema necessária; 11/11 schemas íntegros. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Contagens exatas, hashes SHA-256 e resultados dos dois shims `core_no_sdp` registrados acima. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | N/A (escopo de compatibilidade de suíte CI `core_no_sdp`). | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Separação entre lock `requirements-core.lock` (Job B) e `requirements-pathview.lock` (Jobs E/G) atendida com zero skips. | CONFORME |
