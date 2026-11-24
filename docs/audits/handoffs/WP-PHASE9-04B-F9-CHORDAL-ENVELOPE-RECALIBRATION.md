# Handoff e Parecer F9 — `WP-PHASE9-04B-F9-CHORDAL-ENVELOPE-RECALIBRATION`

- **WorkPackage**: `WP-PHASE9-04B-F9-CHORDAL-ENVELOPE-RECALIBRATION`
- **Frente**: `F9 (f9-integration-qa)` — Auditoria Final & Encerramento da Fase 9 (`ADR-015`, **115/115 WPs**)
- **Commit Base**: `60c1867d2c4115d5feaa00af79d66bb374225b8a`
- **ADR / Referência**: `ADR-010` & `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T05:20:00Z`

---

## 1. Artefatos Produzidos pela F9 e Isolamento de Ownership

Escopo F9 (`tests/oracles/`, `docs/architecture/`, `docs/audits/`, `PROJECT_STATE.json`, `README.md`) estritamente respeitado; nenhuma alteração em `control_lab/`, `web/`, `contracts/fixtures/` ou `tests/unit/f1..f8/`.

| Artefato F9 | SHA-256 | Papel na Entrega |
|---|---|---|
| `tests/oracles/test_phase9_cycle4_chordal_oracle.py` | `4c66165e7553135335fc3fe58fc3d9982f86cd4383516cc757f765fd66936c9d` | Oráculo independente F9 com **0 skips** em `core_no_sdp` e `sdp_available`: blocos PSD em banda (`dim=16, 24`, bw=2) com `verify()` 5D no bloco original e paridade `< 1e-6` vs Clarabel; Schur esparso `m=89` (`sparse_splu`, `< 1e-8` vs denso, `< 1e-6` vs Clarabel); bypass denso. |
| `docs/architecture/ADR-010-native-sdp-and-offline-exports.md` | `35fd54c69a538da0b4fcc8ec00876145cef2c14cf9235311265c43725c971406` | Tabela comparativa Fase 5 vs. Fase 9 v2.0 (CPython, Chromium Pyodide Wasm e Clarabel) e conclusão formal de recalibração dentro do `BROWSER_ENVELOPE` (`448` rápido / `1024` estendido). |
| `docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md` | `ea7e970a2eea4bd623e4ee80b9b22143baf233bbdccffa1cf01a2f2dc7f5c569` | Todos os 4 ciclos marcados como **IMPLEMENTED & ACCEPTED BY F9** com trilha de commits (`d20acb8`, `f776cfb`, `60c1867`) e benchmarks medidos em CPython e Chromium Pyodide Wasm. |
| `README.md` | `d13be28eb68a16e616476d8161a5bdd290d301722f9b4e723a84c5f5d4b91220` | Atualizado para **115/115 WPs `ACCEPTED_BY_F9`** (`0` pendentes), `ADR-015` na tabela de ADRs e resumo completo da arquitetura Native SDP v2.0 (34/34 links locais válidos). |
| `docs/audits/handoffs/WP-PHASE9-04-F6-CHORDAL-CLIQUES-SPARSE-SCHUR.md` | (este ciclo) | Parecer formal F9 com checklist de 10 itens do Apêndice E para a entrega F6. |

---

## 2. Benchmark Real Fase 5 vs. Fase 9 v2.0 (CPython vs. Chromium Pyodide Wasm vs. Clarabel)

Medido com a *wheel* final (`web/dist/wheels/control_lab-1.0.0-py3-none-any.whl`) contendo todos os 4 ciclos da Fase 9 (`BROWSER_ENVELOPE` preservado em `fast_max_variables=448`, `max_variables=1024`, `max_block_dimension=64`, `max_cone_entries=65536`):

| Caso | Fase 5 CPython | Fase 9 v2 CPython (Ganho) | Fase 5 Chromium Wasm | Fase 9 v2 Chromium Wasm (Ganho) | Clarabel (`clarabel_direct`) | Certificado 5D |
|---|---|---|---|---|---|---|
| `stab n=16` (`152 vars`) | `495.8ms` | **`59.5ms`** (`8.3×`) | `808.1ms` (13 it) | **`152.3ms`** (6 it, `5.3×`) | `44.8ms` | `validated_dual` (`Δobj=0.0`) |
| `stab n=20` (`230 vars`) | `776.6ms` | **`99.3ms`** (`7.8×`) | `1793.6ms` (13 it) | **`220.2ms`** (6 it, `8.1×`) | `74.8ms` | `validated_dual` (`Δobj=0.0`) |
| `stab n=24` (`324 vars`) | `1667.5ms` | **`158.6ms`** (`10.5×`) | `4105.7ms` (13 it) | **`410.4ms`** (6 it, `10.0×`) | `150.9ms` | `validated_dual` (`Δobj=0.0`) |
| `stab n=28` (`434 vars`) | `3221.4ms` | **`244.1ms`** (`13.2×`) | `9721.2ms` (14 it) | **`765.4ms`** (6 it, `12.7×`) | `263.4ms` | `validated_dual` (`Δobj=0.0`) |
| `chordal_banded_d20` (`dim=20→4`, 9 cliques) | — | **`73.2ms`** (10 it) | — | **`144.1ms`** (10 it) | `13.9ms` (`Δobj=8.9e-10`) | `validated_dual` |
| `sparse_schur_m159` (`m=159`, `splu` vs `dense`) | — | **`177.4ms`** vs `239.0ms` | — | **`371.3ms`** vs `387.7ms` | `47.6ms` (`Δobj=1.7e-8`) | `validated_dual` |

---

## 3. Gates de Verificação Executados pela F9

| Gate / Comando | Resultado | Status |
|---|---|---|
| `npm --prefix web run typecheck` | `tsc -p tsconfig.json --noEmit` (`exit 0`) | PASS |
| `npm --prefix web run build` | Wheel `control_lab-1.0.0-py3-none-any.whl` + `42` local assets verificados (`exit 0`) | PASS |
| `node scripts/run_web_tests.mjs --scope all` | **159 passed, 0 failed, 0 skipped** (`56` TS files, `21` test files) | PASS |
| Gate simulado `core_no_sdp` (`f1..f5`, `oracles`, `integration`) | **597 passed, 0 failed, 0 skipped** em `59.76s` (`exit 0`) | PASS |
| Suite completa `sdp_available` (`f6`, `oracles`) | **444 passed, 0 failed, 0 skipped** em `72.53s` (`exit 0`) | PASS |
| Real Chromium Wasm + E2E (`test_real_runtime.py` + `test_ux_refactor_cl_ux_dir_001.py`) | **20 passed, 0 failed, 0 skipped** em `213.46s` (`exit 0`) | PASS |
| `python3 scripts/verify_fixtures.py` | 11 schemas Draft 2020-12 + 7 fixtures ouro + 4 exemplos (`exit 0`) | PASS |
| Validação de links locais em `README.md` | `34/34` links válidos, `0` ausentes | PASS |
| `python3 scripts/project_governance.py` | `{"accepted": 115, ..., "work_packages": 115}` (`exit 0`) | PASS |

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Validada de ponta a ponta em CPython, Node (`159 passed`) e Chromium Pyodide Wasm real (`20 passed`). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Todos os cenários (`optimal`, `primal_infeasible`, `RESOURCE_LIMIT`) preservam as 5 dimensões de status e diagnósticos completos. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Oráculo F9 independente valida decomposição cordal e Schur esparso com reconstrução 5D no problema original. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Paridade estrita contra `clarabel_direct` (`< 1e-6`), `dense_cholesky` (`< 1e-8`) e `use_chordal=False` (`< 1e-6`), sem relaxar tolerâncias. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Ownership F6/F9 estritamente isolado; `contracts/fixtures/` intocados (`verify_fixtures.py` PASS). | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Todos os 4 ciclos da Fase 9 validados em CPython (`core_no_sdp` + `sdp_available`) e em Chromium Pyodide Wasm real. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | 11 schemas JSON Draft 2020-12 válidos e retrocompatíveis. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Benchmarks CPython vs Chromium Wasm vs Clarabel registrados em `ADR-010`, `ADR-015` e neste handoff. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `control_lab/experimental/sdp_educational/` permanece isolado como experimental. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Envelope operacional `448`/`1024` mantido explícito com exportação offline CVXPY/YALMIP para problemas acima do limite. | CONFORME |

---

## 5. Parecer Formal da Frente F9 — Encerramento da Fase 9

- **Veredito F9**: `accepted` (**115/115 WorkPackages `ACCEPTED_BY_F9`, 0 pendentes**)
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `60c1867d2c4115d5feaa00af79d66bb374225b8a`
- **Data (UTC)**: `2026-11-24T05:20:00Z`
