# Handoff e Parecer F9 — `WP-PHASE9-02-F6-HSDE-GONDZIO-SOLVER`

- **WorkPackage**: `WP-PHASE9-02-F6-HSDE-GONDZIO-SOLVER`
- **Frente Produtora**: `F6 (f6-optimization-lmi)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `d20acb8d3363a7990e67e5db7f1a7f059372419b`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T04:27:00Z`

---

## 1. Escopo Auditado e Inventário SHA-256 (`allowed_paths`)

Alterações estritamente isoladas ao escopo da Frente F6 (`control_lab/optimization/`, `control_lab/experimental/sdp_educational/`, `tests/unit/f6/`):

| Artefato F6 | SHA-256 | Papel no Pacote |
|---|---|---|
| `control_lab/optimization/backends/native_core.py` | `2108a4bd08add51ef91deee7fb99e15aedd0cf4161fa18bbd38743a7afb6a198` | Implementação do Embedding Homogêneo Autodual (HSDE) em passagem única (Ye-Todd-Mizuno / de Klerk-Roos-Terlaky / Sturm / Goulart-Chen), certificados Farkas primal/dual, múltiplos corretores de centralidade de Gondzio reutilizando a fatoração Cholesky de Schur (`O(m^2)` por corretor), `progress_callback` e cancelamento cooperativo (`cancel_check` / `ContextVar`), com zero chamadas `linalg.inv`. |
| `control_lab/optimization/backends/native.py` | `8ab4d9323d1e1ab076be63438a951b2d1cbe4721d5b5815f4e161d20e706d40a` | Atualização da matriz de capacidades do `NativePrimalDualBackend` expondo `cancellation=True` sem alterar `BROWSER_ENVELOPE`. |
| `control_lab/optimization/backends/solve.py` | `33bd25d2f788ca9aa322415ad9715b89d3bdc8f60d348eeb9c22f53426bdedf4` | Propagação de `hsde_summary` e `hsde_certificate` no bloco `diagnostics` da resposta canônica `solve(...)`. |
| `control_lab/experimental/sdp_educational/solver.py` | `e462a7793ac0db71319fa8e00cf8e3c288c4abd7c2fc2cac2e5d031342e7dc04` | Preservação do modo educacional experimental (`use_hsde=False` por padrão, mantendo isolamento sob `ADR-008`/`ADR-010`). |
| `tests/unit/f6/test_phase9_cycle2_hsde_gondzio.py` | `cfab91d0aa9981c947cc0bb73292dc7a88d133a2840930c6dea5bb18f548eac2` | 10 testes unitários cobrindo HSDE em passagem única (`n=4,8,12,16`, `CTRL_BRL_D2_MIN`, misto PSD+LP), infactibilidade Farkas, ilimitação, corretores de Gondzio, `warm_start_x`, `progress_callback`, `cancel_check` e guarda AST zero-`linalg.inv`. |
| `tests/unit/f6/test_scalable_native_sdp.py` | `342e9c5c44bed0409f1d86589fd5ee20847f6b49198aa78f3b90d3fc80bd8966` | Atualização das asserções de *warm-start* para verificar o *bypass* limpo do caminho padrão HSDE quando `warm_start_x` é estritamente factível e *fallback* seguro quando infactível. |

---

## 2. Evidências de Verificação Independente (F9)

- **Ownership e Invariantes**: zero arquivos fora de `control_lab/optimization/`, `control_lab/experimental/sdp_educational/` e `tests/unit/f6/`; zero chamadas `linalg.inv`; zero relaxamento de tolerâncias; zero `pytest.skip`/`pytest.importorskip`.
- **Unitários F6 Ciclo 2 (`tests/unit/f6/test_phase9_cycle2_hsde_gondzio.py`)**: **10 passed, 0 failed, 0 skipped**.
- **Suite `sdp_available` (`tests/unit/f6/` + `tests/oracles/`)**: **410 passed, 0 failed, 0 skipped** (`exit 0`).
- **Suite simulada `core_no_sdp`** (`tests/unit/f1..f5`, `tests/oracles`, `tests/integration` com `pathview`, `pathsim`, `clarabel`, `cvxpy`, `scs` bloqueados): **589 passed, 0 failed, 0 skipped** (`exit 0`).
- **Oráculo independente F9 (`tests/oracles/test_phase9_cycle2_hsde_oracle.py`)**: **6 passed, 0 failed, 0 skipped** — paridade `< 1e-5` vs `clarabel_direct` em estabilização `n=8, 12`, `CTRL_BRL_D2_MIN` e misto PSD+LP; terminação rápida (`4` iterações) em LMIs estritamente infactíveis (`primal_infeasible` + Farkas) e (`3` iterações) em objetivos ilimitados (`dual_infeasible`).
- **Pyodide Wasm real em Chromium (`tests/wasm/test_real_runtime.py`)**: **5 passed, 0 failed, 0 skipped** (`exit 0`) com `control_lab-1.0.0-py3-none-any.whl` reconstruído via `npm --prefix web run build`.
- **Integridade de fixtures (`scripts/verify_fixtures.py`)**: **PASS** (11 schemas + 7 fixtures ouro íntegras).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `solve(...)` mantém o contrato canônico de entrada/saída, adicionando `hsde_summary` e `hsde_certificate` em `diagnostics` sem quebrar consumidores F1/F7/F8. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Casos factíveis, infactíveis (`primal_infeasible` / `validated_infeasibility` / `violated`) e ilimitados (`dual_infeasible` / `validated_unboundedness`) emitem diagnósticos completos, incluindo métricas Farkas (`farkas_dual_residual_rel`, `farkas_objective`) e contadores de Gondzio. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Invariantes de estabilidade em malha fechada (`Re(eig(A+BK)) < -alpha`), autovalores PSD, certificados Farkas, cancelamento e guarda AST zero-`linalg.inv` validados em `tests/unit/f6/` e `tests/oracles/`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Paridade estrita contra `clarabel_direct` (`|Δobj| < 1e-5` em factíveis e concordância de status em infactíveis/ilimitados) + auditoria 5D independente `verify(prob, sol)` no problema original não escalonado. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Apenas caminhos permitidos de F6 foram alterados; `contracts/fixtures/`, `control_lab/optimization/verification/` e `tests/oracles/` permaneceram intocados pela F6; `verify_fixtures.py` PASS. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | 100% Python puro + NumPy/SciPy; validado em CPython (`410 passed` em `sdp_available`, `589 passed` em `core_no_sdp`) e Chromium + Pyodide real (`5 passed` em `tests/wasm/test_real_runtime.py`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Campos adicionais em `diagnostics` (`hsde_summary`, `hsde_certificate`) e `capabilities.cancellation=True` são estritamente aditivos e retrocompatíveis, revisados pela F9 sob `ADR-015`. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, redução comprovada de fatorações Cholesky (HSDE < Fase I+II), ativação de corretores Gondzio em `CTRL_BRL_D2_MIN`, e contagens exatas de testes anexados. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `control_lab/experimental/sdp_educational/solver.py` mantém `maturity="experimental"`, `experimental=True` e `use_hsde=False` por padrão sob `ADR-008`/`ADR-010`. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Escalonamento para esparsidade de Schur (Fujisawa) e decomposição cordal permanecem rastreados nos Ciclos 3–4 da `ADR-015`; `BROWSER_ENVELOPE` mantido conservador até `WP-PHASE9-04B`. | CONFORME |

---

## 4. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit base auditado**: `d20acb8d3363a7990e67e5db7f1a7f059372419b`
- **Data (UTC)**: `2026-11-24T04:27:00Z`
- **Justificativa**: A entrega `WP-PHASE9-02-F6-HSDE-GONDZIO-SOLVER` cumpre integralmente os requisitos do Ciclo 2 da `ADR-015` (HSDE em passagem única com certificados Farkas primal/dual e múltiplos corretores de Gondzio reutilizando a fatoração de Schur), com redução real de fatorações Cholesky, detecção rápida de infactibilidade/ilimitação, paridade estrita contra `clarabel_direct`, zero `linalg.inv` e 100% de aprovação em CPython (`sdp_available` e `core_no_sdp`) e Pyodide Wasm real.
