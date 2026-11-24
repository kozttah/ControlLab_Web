# Handoff e Parecer F9 — `WP-PHASE9-03C-F9-F1F2-BENCHMARK-AUDIT`

- **WorkPackage**: `WP-PHASE9-03C-F9-F1F2-BENCHMARK-AUDIT`
- **Frente Executora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **WorkPackages Produtores Auditados**: `WP-PHASE9-03-F6-FUJISAWA-F1F2-PREPROCESS` (F6) e `WP-PHASE9-03B-F8-DSL-SYMMETRIC-FUSION` (F8)
- **Commit Base**: `f776cfb4c6f9a2b295e3e572794c32329cbc2b0a`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T04:56:00Z`

---

## 1. Artefatos F9 Entregues (`allowed_paths`)

Alterações estritamente isoladas ao escopo F9 (`tests/oracles/`, `tests/e2e/`, `docs/audits/`, `PROJECT_STATE.json`):

| Artefato F9 | SHA-256 | Papel no Pacote |
|---|---|---|
| `tests/oracles/test_phase9_cycle3_f1f2_oracle.py` | `fe22a4ba660dec9b3cd56ff210c937425a4c11ad91e3e8c82bf5482ccca30827` | Oráculo independente F9 do Ciclo 3 (4 testes, 0 skips em `sdp_available` e `core_no_sdp`): montagem esparsa Fujisawa `F1`/`F2` em LMIs de estabilização `n=12, 16, 20` com paridade `< 1e-6` contra `F3_blas` e `clarabel_direct` (quando instalado), prova espectral de malha fechada e `verify()` 5D independente; pré-processamento simbólico (`eliminated_zero_vars >= 3`, `merged_duplicate_vars >= 2`) validado com `validated_dual` no problema ORIGINAL não-reduzido e paridade `< 1e-6` contra `clarabel_direct`. |
| `tests/e2e/test_ux_refactor_cl_ux_dir_001.py` | `0619a9aafbe5debb4801eafde9a98d9a550f0f6073e4519a79782d77d07df8cd` | Novo teste E2E em Chromium + Pyodide real (`test_ux_phase9_cycle3_generic_recover_and_symmetric_fusion`): valida renderização visível e finita de múltiplas diretivas `recover` (`P = inv(Q)`, `K = Y * inv(Q)`, `trP = trace(P)`) em `#lmi-recovered-gain` e fusão simétrica dupla politópica (`#lmi-fusion-badge` = `1 par simétrico fundido (5 → 4)`) resolvida com `validated_dual` em Pyodide Wasm. |
| `docs/audits/handoffs/WP-PHASE9-03-F6-FUJISAWA-F1F2-PREPROCESS.md` | *(registrado no commit)* | Parecer formal F9 com checklist de 10 itens do Apêndice E para a entrega F6. |
| `docs/audits/handoffs/WP-PHASE9-03B-F8-DSL-SYMMETRIC-FUSION.md` | *(registrado no commit)* | Parecer formal F9 com checklist de 10 itens do Apêndice E para a entrega F8. |
| `docs/audits/handoffs/WP-PHASE9-03C-F9-F1F2-BENCHMARK-AUDIT.md` | *(este documento)* | Relatório consolidado de auditoria independente F9 e evidências de todos os gates do Ciclo 3. |
| `PROJECT_STATE.json` | *(atualizado no commit)* | Promoção de `WP-PHASE9-03-F6-FUJISAWA-F1F2-PREPROCESS`, `WP-PHASE9-03B-F8-DSL-SYMMETRIC-FUSION` e `WP-PHASE9-03C-F9-F1F2-BENCHMARK-AUDIT` para `ACCEPTED_BY_F9` (`113/115` aceitos, `2` pendentes para o Ciclo 4). |

---

## 2. Evidências Executadas dos Gates F9

| Gate / Comando | Resultado Exato | Status |
|---|---|---|
| `npm --prefix web run typecheck` | `exit 0` (0 erros TypeScript) | PASS |
| `npm --prefix web run build` | Rebuild completo do wheel `control_lab-1.0.0-py3-none-any.whl` em `web/dist/` + 42 assets locais íntegros (`exit 0`) | PASS |
| `node scripts/run_web_tests.mjs --scope all` | **159 passed, 0 failed, 0 skipped** em 21 arquivos de teste (`177.4s`, `exit 0`) | PASS |
| Oráculo independente F9 (`pytest tests/oracles/test_phase9_cycle3_f1f2_oracle.py -v`) | **4 passed, 0 failed, 0 skipped** em `4.46s` (`exit 0`) | PASS |
| Gate simulado `core_no_sdp` (`tests/unit/f1..f5`, `tests/oracles`, `tests/integration` com `pathview`, `pathsim`, `clarabel`, `cvxpy`, `scs` bloqueados) | **593 passed, 0 failed, 0 skipped** em `47.98s` (`exit 0`) | PASS |
| Suite completa `sdp_available` (`pytest tests/unit/f6 tests/oracles -q`) | **430 passed, 0 failed, 0 skipped** em `63.41s` (`exit 0`) | PASS |
| Pyodide Wasm + E2E em Chromium real (`pytest tests/wasm/test_real_runtime.py tests/e2e/test_ux_refactor_cl_ux_dir_001.py -v`) | **20 passed, 0 failed, 0 skipped** em `188.51s` (`exit 0`) | PASS |
| Integridade de fixtures (`python3 scripts/verify_fixtures.py`) | 11 schemas Draft 2020-12 + 7 fixtures ouro + 4 exemplos RPC/PVM (`exit 0`) | PASS |
| Governança (`python3 scripts/project_governance.py`) | Validado após atualização de `PROJECT_STATE.json` (`exit 0`) | PASS |

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Contratos `solve`, `verify`, `lmi_dsl_compiler` e Worker Pyodide validados fim-a-fim em CPython, Node e Chromium + Pyodide real. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `schur_assembly_modes`, `preprocessing_summary`, `fusionStats`, `certificate_status` e avisos de recuperação auditados. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Oráculo F9 verifica independentemente autovalores de malha fechada, positividade espectral e resíduos 5D no problema original não-reduzido. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Comparação direta contra `F3_blas` e `clarabel_direct` (`< 1e-6`) sem qualquer relaxamento de tolerâncias, mais validação E2E real no navegador. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | F6, F8 e F9 estritamente dentro de seus respectivos `allowed_paths`; zero alteração em `contracts/fixtures/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Aprovado em CPython (`593 passed` `core_no_sdp`, `430 passed` `sdp_available`, 0 skips), Node (`159 passed`) e Chromium + Pyodide Wasm real (`20 passed`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `verify_fixtures.py` valida 11 schemas Draft 2020-12 sem regressão; extensões de diagnóstico da `ADR-015` são retrocompatíveis. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Contagens exatas de testes, tempos de execução e hashes SHA-256 registrados neste handoff. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `control_lab/experimental/sdp_educational/` permanece isolado como experimental. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Ciclo 4 (`WP-PHASE9-04-F6-CHORDAL-CLIQUES-SPARSE-SCHUR` e `WP-PHASE9-04B-F9-PHASE9-RELEASE-BENCHMARK`) permanece formalmente pendente em `PROJECT_STATE.json`. | CONFORME |

---

## 4. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Data (UTC)**: `2026-11-24T04:56:00Z`
- **Conclusão**: Ciclo 3 da Fase 9 (`WP-PHASE9-03-F6-FUJISAWA-F1F2-PREPROCESS`, `WP-PHASE9-03B-F8-DSL-SYMMETRIC-FUSION` e `WP-PHASE9-03C-F9-F1F2-BENCHMARK-AUDIT`) aprovado integralmente pela auditoria independente F9.
