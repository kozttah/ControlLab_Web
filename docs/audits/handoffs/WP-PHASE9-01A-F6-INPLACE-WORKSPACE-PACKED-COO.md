# Handoff e Parecer F9 — `WP-PHASE9-01A-F6-INPLACE-WORKSPACE-PACKED-COO`

- **WorkPackage**: `WP-PHASE9-01A-F6-INPLACE-WORKSPACE-PACKED-COO`
- **Frente Produtora**: `F6 (f6-optimization-lmi)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-23T04:20:00Z`

---

## 1. Escopo Auditado e Inventário SHA-256 (`allowed_paths`)

Alterações estritamente isoladas em `control_lab/optimization/` e `tests/unit/f6/`:

| Artefato F6 | SHA-256 | Papel no Pacote |
|---|---|---|
| `control_lab/optimization/modeling/canonical.py` | `2236184ed14978fd476af1de1e66f147cdf063ab7b975dfc3feecef952307d6b` | Ingestão vetorizada zero-copy de `F_k_packed` (`k_idx`/`rows`/`cols` `int32` + `vals` `float64` via `np.ndarray`, `memoryview`, `bytes`, `TensorDescriptor` ou `list`) com ordenação estável, soma de duplicatas, simetrização e imutabilidade profunda preservando 100% de retrocompatibilidade com `F_k` e `F_k_sparse`. |
| `control_lab/optimization/backends/native_core.py` | `74b3fd480a88f50a14bac4836b075904d5527e34b507ae622ffc786929e8216b` | Workspace pré-alocado reutilizável *in-place* nas iterações Mehrotra e fatoração simétrica de Schur + cone LP vetorial 1D unificado para blocos PSD `1x1` (caminhos denso e esparso) sem chamadas escalares a `eigvalsh`/`cholesky` e sem relaxamento de tolerâncias. |
| `tests/unit/f6/test_phase9_cycle1_packed_lp_inplace.py` | `7a8319d788e490270292299a7b92c4e3932883f9dca94583c8a5fd84d1eca173` | Cobertura completa de `F_k_packed`, rejeição de entradas malformadas, cone LP 1D (0 chamadas `eigvalsh` em `1x1`), buffers *in-place* e LMIs de estabilização `n=16` (152 vars) e `n=20` (230 vars) vs `clarabel_direct`. |

---

## 2. Evidências de Verificação Independente (F9)

- **Ownership e Tolerâncias**: zero arquivos modificados em `control_lab/optimization/verification/`, `contracts/fixtures/` ou `tests/oracles/`; nenhuma tolerância relaxada; zero `pytest.skip`/`importorskip`.
- **Suite `sdp_available` (`tests/unit/f6` + `tests/oracles`)**: **394 passed, 0 failed, 0 skipped** (`exit 0`).
- **Oráculo independente F9 (`tests/oracles/test_phase9_cycle1_oracle.py`)**: estabilização LMI (`n=12`, `n=16`) e problema misto (2 blocos PSD `4x4` + 24 blocos escalares `1x1` LP) passaram com `max |x_packed - x_dense| < 1e-8`, auditoria 5D `validated_dual` no problema original e paridade `|obj_native - obj_clarabel| < 1e-5` contra `clarabel_direct`.
- **Chromium + Pyodide Wasm real (`tests/wasm/test_real_runtime.py`)**: escada `G-0B` completa (`T-SDP-A1..D2`) + LMI `n=8` (44 vars) via `F_k_packed` em `120.7 ms` com `certificate_status="validated_dual"`, `max |Δx| = 5.15e-14`.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `SDPBlock.from_dict` / `CanonicalSDPProblem.from_dict` testados com `F_k`, `F_k_sparse` e `F_k_packed` em 6 representações de entrada e integrados ponta a ponta com F1/F7/F8. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Entradas inválidas em `F_k_packed` disparam `ValidationError`/`DimensionMismatchError`; soluções retornam as 5 dimensões canônicas (`solver_status`, `audit_feasibility`, `certificate_status`, condicionamento e validade do controlador). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Invariantes de simetrização, duplicatas, limites de índice, ausência de `eigvalsh` em `1x1`, reutilização de buffers *in-place* e estabilidade em malha fechada verificados em `tests/unit/f6/` e `tests/oracles/`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Paridade estrita contra o oráculo independente `clarabel_direct` (`|Δobj| < 1e-5`) e auditoria 5D independente (`verify(prob_dense, sol)`) no problema original não escalonado. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Apenas `control_lab/optimization/{modeling/canonical.py,backends/native_core.py}` e `tests/unit/f6/` tocados; `verify_fixtures.py` PASS e zero tolerâncias alteradas. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | 100% Python puro + NumPy/SciPy; validado em CPython (`394 passed` em `sdp_available`, `583 passed` em `core_no_sdp`) e Chromium + Pyodide real (`test_g0b_native_runtime_and_offline_scripts` + `test_wasm_phase9_cycle1_packed_zero_copy_transfer_and_solve` PASS). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `F_k_packed` é campo opcional retrocompatível de bloco SDP formalizado pela `ADR-015` e auditado pela F9 sem quebrar `F_k`/`F_k_sparse`. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, resultados `394 passed` (`sdp_available`), `583 passed` (`core_no_sdp`) e medição Pyodide (`120.7 ms`, `max |Δx| = 5.15e-14`) anexados. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `control_lab/experimental/sdp_educational/` permanece isolado sob `ADR-008`/`ADR-010`; `BROWSER_ENVELOPE` mantido inalterado até Ciclo 4 (`WP-PHASE9-04B`). | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Problemas fora do envelope ou mal condicionados preservam `offline_recommended` e exportação CVXPY/YALMIP (`ADR-010`); evolução HSDE/Fujisawa/cordal planejada nos Ciclos 2–4 (`ADR-015`). | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **Data (UTC)**: `2026-11-23T04:20:00Z`
- **Justificativa**: A entrega F6 cumpre integralmente os requisitos do Ciclo 1 da `ADR-015` (ingestão `F_k_packed` zero-copy, workspace pré-alocado *in-place* e cone LP vetorial 1D sem `eigvalsh` em `1x1`), preservando 100% da auditoria 5D no problema original e paridade estrita com `clarabel_direct` e Pyodide Wasm real sem qualquer relaxamento de tolerâncias.
