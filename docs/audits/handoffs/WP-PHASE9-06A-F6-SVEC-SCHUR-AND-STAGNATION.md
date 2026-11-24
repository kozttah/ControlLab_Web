# Handoff e Parecer F9 — `WP-PHASE9-06A-F6-SVEC-SCHUR-AND-STAGNATION`

- **WorkPackage**: `WP-PHASE9-06A-F6-SVEC-SCHUR-AND-STAGNATION`
- **Frente Produtora**: `F6 (f6-optimization-lmi)`
- **Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base**: `d820ffcd81cf0e09393b85d861842a8341a0715a`
- **ADR / Referência**: `ADR-010` & `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-24T19:12:05Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Escopo F6 (`control_lab/optimization/`, `tests/unit/f6/`) verificado via `git status -s` e `git diff --stat`: nenhuma alteração fora de `allowed_paths`, zero chamadas a `linalg.inv`, zero operações *in-place* `+= .swapaxes(...)`, zero `eval`/`new Function`, zero relaxamento de tolerâncias e zero `pytest.skip` ou `importorskip`.

| Artefato F6 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/optimization/backends/native_core.py` | `dd0668044f0feaad3a3727b8754b09fabf6ad7b08ceeb855c0eb39e74f38a0e8` | Implementação de `_get_svec_indices`, `_mat_to_svec`, `_svec_to_mat_into` (isometria de Todd–Toh–Tütüncü 1998), montagem `F2` com `F_svec_csr` `(n_act, d(d+1)/2)` + visões *zero-copy* `_F_svec_tail`, montagem `F3_blas` em coordenadas `svec` livre de aliasing *in-place* (substituindo `+= .swapaxes`), e contador `best_opt_stagnant` na salvaguarda `1b'` dos loops HSDE e primal-dual (Clarabel §2.6). |
| `tests/unit/f6/test_phase9_cycle4_chordal_sparse_schur.py` | `30b3bf07e26bb73fecc50ee76a82e864adc354597c40903fe749c46421848551` | Atualização de 1 linha da dimensão de buffer `cols` de `dim * dim` para `dim * (dim + 1) // 2` em `test_f2_presliced_tail_and_f3_chunked_congruence_exactness`, mantendo tolerâncias inalteradas. |
| `tests/unit/f6/test_phase9_cycle6_svec_stagnation.py` | `748b4a8f1a138d7973fd38f45cf25013dcb86026f74962facba52f9ec522a2d1` | Testes unitários da isometria `svec`, exatidão `F2`/`F3_blas` sem aliasing com `G_invT` assimétrica, convergência antecipada em `BlkDiag_24x8` rígido (`< 40` iterações) com paridade Clarabel `< 1e-6`, e guarda AST contra `linalg.inv` e `+= .swapaxes()`. |

---

## 2. Evidências Executadas pela F9

| Verificação Independente | Resultado | Status |
|---|---|---|
| Isolamento de ownership (`git status -s` & `git diff --stat`) | Apenas os 3 arquivos F6 acima modificados/adicionados (`199+ / 106-` linhas em 2 arquivos modificados + 1 arquivo de teste F6) | PASS |
| Auditoria estática (`linalg.inv`, `+= .swapaxes`, `pytest.skip`, `importorskip`, tolerâncias) | Zero ocorrências proibidas; zero relaxamento de tolerâncias | PASS |
| Suíte unitária F6 (`/home/antigravity/.venv/bin/pytest tests/unit/f6/ -q`) | **134 passed, 0 failed, 0 skipped** em `35.61s` (`exit 0`) | PASS |
| Oráculo independente F9 (`tests/oracles/test_phase9_cycle6_svec_stagnation_oracle.py`) | **3 passed, 0 failed, 0 skipped** em `8.83s` (`svec` + `F2`/`F3_blas` vs `tr(W F_i W F_j)` com `atol=1e-12`, `BlkDiag_24x8` em `16` iterações com `|Δobj| = 8.84e-7`, `denseA n=40, m=860` em `6` iterações com `|Δobj| = 0.0`) | PASS |
| Suíte completa de oráculos F9 (`/home/antigravity/.venv/bin/pytest tests/oracles/ -q -rs`) | **323 passed, 0 failed, 0 skipped** em `42.83s` (`exit 0`) | PASS |

---

## 3. Métricas Empíricas Verificadas pela F9 (CPython vs. Clarabel)

| Problema de Auditoria | Variáveis (`m`) | Iterações HSDE | Tempo Nativo | Tempo Clarabel | `|Δobj|` vs Clarabel | Certificado 5D |
|---|---|---|---|---|---|---|
| `BlkDiag_24x8` rígido (`24×8`, escala `1..16×`) | `96` | **`16`** (`< 40`, sem spin de `80`) | `687.6ms` (`raw 662.6ms`) | `81.8ms` | `8.842e-07` (`< 1e-6`) | `validated_dual` |
| `denseA` estabilização (`n=40`, `F2` `svec` ativo) | `860` | **`6`** | **`2653.9ms`** (`raw 2250.1ms`) | `2684.7ms` | **`0.000e+00`** | `validated_dual` |

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Validada via `solve(...)`, `verify(...)` e `recover_controller(...)` sem quebra de assinatura pública (`134/134` F6 + `323/323` oráculos). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Todos os envelopes mantêm `solver_status`, `certificate_status`, auditoria 5D e diagnósticos intactos, preservando `RESOURCE_LIMIT` e certificados Farkas. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Isometria exata de Frobenius `<A, B>_F = svec(A)^T svec(B)`, referência independente `tr(W F_i W F_j)` e alocação espectral `max Re(eig(A+BK)) < -0.20` verificados analiticamente. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Oráculo F9 `test_phase9_cycle6_svec_stagnation_oracle.py` confronta `_mat_to_svec`/`F2`/`F3_blas` contra implementação independente, `verify()` 5D e `clarabel_direct` (`< 1e-6`). | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações estritas em `control_lab/optimization/backends/native_core.py` e `tests/unit/f6/`; `contracts/fixtures/` intocados (`verify_fixtures.py` PASS). | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Implementação 100% Python/NumPy/SciPy pura, compatível com CPython e Pyodide Wasm no domínio `BROWSER_ENVELOPE` (`1792 / 3072`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma alteração de schema; 11 schemas JSON Draft 2020-12 íntegros (`verify_fixtures.py` PASS). | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, saídas de `pytest` (`134` F6 / `323` oráculos) e benchmarks `BlkDiag_24x8` / `denseA n=40` registrados neste handoff e em `ADR-015`. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `control_lab/experimental/sdp_educational/` permanece isolado como experimental. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Salvaguarda `1b'` restaura `best_opt_state` somente após atingir `<= 1e-9` (ou `<= 1e-8` sob `cond_H >= 1e10`) com `>= 3` iterações sem melhora `>= 10%`, mantendo `verify()` 5D obrigatório. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `d820ffcd81cf0e09393b85d861842a8341a0715a`
- **Data (UTC)**: `2026-11-24T19:12:05Z`
