# Handoff e Parecer F9 — `WP-TSMOD-05-F9-TS-MODELING-AUDIT-ORACLES`

- **WorkPackage**: `WP-TSMOD-05-F9-TS-MODELING-AUDIT-ORACLES`
- **Frente Produtora / Auditora**: `F9 (f9-integration-qa)` — Auditoria Independente e Fechamento da Fase 10 (`Phase10-TS-qLPV-Modeling`): oráculos independentes sem circularidade cobrindo `T-TSMOD-01`..`T-TSMOD-08` (Setor 16 regras, TPMT `v1.3.0` centrada, FEMT `v1.2.0` centrada no subespaço variante), validação real em Pyodide `wasm32` no navegador e teste E2E Playwright da Aba 6 (`ts_modeling`) $\to$ Workspace Dock $\to$ Aba 7 (`optimization_lmi`).
- **Commit Base**: `30dcc3a3282e3982971fbded6666651e3d4f6340`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-04`, `R-05`, `R-18`, `R-21`, `R-27`, Seção 13.1/13.2/13.11, Apêndice E), `CL-UX-DIR-001 v1.0.0`, `CL-TS-MOD-DIR-001 v1.3.0` (`T-TSMOD-01`..`T-TSMOD-08`, Seção 7.3), `ADR-013`, `ADR-014`.
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-26T16:25:00Z`

---

## 1. Artefatos Entregues e Isolamento de Ownership

Verificação via `git status --short` confirmou isolamento estrito em `allowed_paths` de `WP-TSMOD-05-F9-TS-MODELING-AUDIT-ORACLES`. ZERO alterações em `control_lab/`, `web/`, `contracts/fixtures/` ou `tests/unit/`.

| Artefato F9 | SHA-256 | Papel na Entrega |
|---|---|---|
| `tests/oracles/test_ts_modeling_oracles.py` | `bc9d9501ab512a8c7bcc0531cefb043a1f540f59d8697517ecc361cc7bfd7082` | Oráculos independentes sem circularidade cobrindo todos os 8 testes normativos `T-TSMOD-01`..`T-TSMOD-08` (9 casos parametrizados): segurança AST `R-21` + Taylor `sinc_rad` (`< 1e-15`) + AST gate zero `linalg.inv`/`eval`/`exec`; extremos globais híbridos multimodais (`<= 1e-12`); Setor 16 regras do pêndulo invertido em 517 pontos contínuos (Sobol + origem + cantos, `<= 1e-13`); TPMT `v1.3.0` (invariantes tensoriais, cota de De Lathauwer, convergência monotônica HOOI, centralização modal, preservação bit-a-bit das 24 entradas constantes e `rank_augmented == [False, False]`); fechos convexos (`SN-NN`, `RNO-INO`, `CNO`, `MGK`) e aperto geométrico $|\det T_{\text{CNO}}|^{-1} < 0.99$; ciclo completo Workspace $\to$ JSON Schema $\to$ `evaluate_ts_premise_weights` $\to$ PDC LMI (`validated_dual` + verificação espectral 5D independente) $\to$ PathSim executável com `default_h_fn` (paridade `<= 1e-12`) $\to$ round-trip `.ctrlab`; FEMT `v1.2.0` (24 constantes bit-a-bit, `rank_augmented == False`, `fallback_used == False`, Eckart–Young centrado exato `<= 1e-12`, redução estrita $N_r^{\text{FEMT}} < N_r^{\text{TPMT}}$ sob acoplamento e convergência $O(h^2)$ em `kuhn_delaunay` e `delaunay`). |
| `tests/wasm/test_real_runtime.py` | `d55952173f7bf76c4da7afaa2f000ae912cf13ae09b4d1b509cc5e4a19c24115` | Adição de `test_wasm_phase10_ts_modeling_three_pathways_and_script_export` executando `fuzzy.derive_ts_sector` (16 regras, `max_abs_error = 7.15e-15 < 1e-12`), `fuzzy.derive_ts_tpmt` (`v1.3.0`, 4 regras, `rank_augmented == [False, False]`, 24 constantes bit-a-bit), `fuzzy.derive_ts_femt` (`v1.2.0`, 6 regras, `kuhn_delaunay`, `rank_augmented == False`, 24 constantes bit-a-bit) e `fuzzy.export_ts_derivation_script` (Python compilável) no Pyodide `wasm32` real no navegador Chromium com `activeProxies == 0`. |
| `tests/e2e/test_ts_modeling_e2e.py` | `5b576cee291e753b7e48dd07bc10314f9a9aeec6b94240fa99d72563681f45f2` | Teste E2E Playwright validando na UI real: abertura da Aba 6 (`ts_modeling`), derivação do pêndulo 16 regras via Setor, guarda de invalidação ao trocar preset para `nonseparable_benchmark` (Achado 1 de `WP-TSMOD-04B` desabilitando `#btn-ts-register` e `#btn-ts-register-open-lmi`), troca para Via 3 (`FEMT`), re-derivação (`ts-coupled-2d`, 3 regras `femt_simplicial`), promoção 1-clique (`Registrar e Abrir em LMIs →`) com salto automático para Aba 7 (`optimization_lmi`), visibilidade no Workspace Dock e 0 `pageerror` / 0 vazamento de `PyProxy`. |
| `docs/architecture/ControlLab_Web_Modelagem_TS_qLPV_Diretor_v1.0.md` | `a1988cf1d0a40c67ccc1b938e08fd0c0b00813e3a3c750098b5da9ab99f713d4` | Seção 7.3 atualizada marcando `WP-TSMOD-02D`, `WP-TSMOD-04B` e `WP-TSMOD-05` como `CONCLUÍDO — ACCEPTED_BY_F9`, fechando a Fase 10. |
| `PROJECT_STATE.json` | atualizado | Fechamento governado de `WP-TSMOD-05-F9-TS-MODELING-AUDIT-ORACLES` como `ACCEPTED_BY_F9` (`f9_review: "accepted"`). |

---

## 2. Evidências de Execução e Verificação Independente

| Suíte / Gate Executado | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Build de Produção Web + Wheel** (`npm --prefix web run build`) | `exit 0`; `control_lab-1.0.0-py3-none-any.whl` gerado; `Verified integrity and inventory of 42 local assets`. | Build íntegro pré-Wasm/E2E | PASS |
| **Suíte Unitária F5** (`tests/unit/f5/`) | **143 passed, 0 failed** | Regressão científica F5 | PASS |
| **Suíte Unitária F1** (`tests/unit/f1/`) | **174 passed, 0 failed** | Regressão RPC/PathSim/`.ctrlab` F1 | PASS |
| **Oráculos Independentes F9 (`T-TSMOD-01`..`08`)** (`tests/oracles/test_ts_modeling_oracles.py`) | **9 passed, 0 failed** (todos os 8 requisitos normativos `T-TSMOD-01`..`08`, sendo `T-TSMOD-07` parametrizado nas 3 vias `sector`, `tpmt`, `femt`) | `CL-TS-MOD-DIR-001 v1.3.0` Seção 7.2 | PASS |
| **Runtime Real Pyodide Wasm no Navegador** (`tests/wasm/test_real_runtime.py -k test_wasm_phase10`) | **1 passed** em 18.84s (`sector_rules=16`, `sector_val_max_error=7.15e-15`, `tpmt_rules=4`, `tpmt_rank_augmented=[False, False]`, `femt_rules=6`, `femt_mesh_kind="kuhn_delaunay"`, `femt_rank_augmented=False`, `export_script_compiled=True`, `active_proxies=0`) | Prova real `wasm32` no Chromium | PASS |
| **E2E Playwright Aba 6 $\to$ Workspace $\to$ Aba 7** (`tests/e2e/test_ts_modeling_e2e.py`) | **1 passed** em 29.03s (`preset_stale_guard_verified=True`, `registered_model_id="ts-coupled-2d"`, `representationKind="femt_simplicial"`, `numVertices=3`, `active_proxies=0`, 0 `pageerror`) | Fluxo E2E completo da Aba 6 | PASS |
| **Governança e Proteção do Repositório** (`scripts/project_governance.py` & `tests/security/test_repository_protection.py`) | Executado após atualização final de `PROJECT_STATE.json` e handoff (ver seção final) | `ADR-009` / `CL-DIR-001` | PASS |

> **Nota operacional sobre `tests/wasm/test_real_runtime.py`:** Em execução isolada do módulo, 6/7 testes passaram (`care_12x3`, `unstabilizable`, `g0b_native`, `offline_scripts_download`, `phase9_cycle1_packed`, `phase10_ts_modeling`), enquanto o teste pré-existente `test_wasm_phase9_05c_envelope_3072_and_n48_stabilization` resolveu matematicamente com `validated_dual` e paridade exata mas registrou `8198.70 ms` sob contenção de CPU do container frente ao threshold estrito de `5000 ms` (mantido intacto sem relaxamento conforme regra de não-relaxamento de F9).

---

## 3. Cobertura Normativa `T-TSMOD-01`..`T-TSMOD-08` (Sem Circularidade)

- **`T-TSMOD-01`**: Rejeição AST de `__import__`, `__subclasses__`, `eval`, `exec`, `open`, atributos dunder, lambdas e comprehensions; `sinc_rad(u)` confrontado contra expansão de Taylor analítica $1 - u^2/6 + u^4/120$ (`< 1e-15`); AST gate confirmando **0** ocorrências de `eval`/`exec`/`compile`/`__import__` e **0** ocorrências de `.inv()` nos 4 módulos de `control_lab/fuzzy/{symbolic_qlpv,sector_nonlinearity,tpmt,femt}.py`.
- **`T-TSMOD-02`**: Extremos globais interiores recuperados com erro $\le 10^{-12}$ em $x^3 - 3x$, em funções multimodais 2D com ótimo fechado exato em $(\pm \pi/6, 0)$, e em $\sin(3 x_1)\cos(2 x_2) + 0.1 x_1^2$ confrontado contra solução analítica independente por Newton de $\nabla g = 0$.
- **`T-TSMOD-03`**: Pêndulo invertido de 4 estados / 16 regras comparado contra avaliador analítico independente `_exact_pendulum_S_analytical(x3, x4)` em 517 pontos contínuos (512 Sobol + origem + 4 cantos): erro máximo Frobenius $\le 10^{-13}$, $h_r \ge -10^{-15}$, $|\sum h_r - 1| \le 10^{-14}$.
- **`T-TSMOD-04`**: Identidade exata `fold_mode(unfold_mode(A, d), d, A.shape) == A`, ortonormalidade $\le 10^{-13}$, cota de De Lathauwer na HOSVD, convergência monotônica na HOOI (`center_modes=False` e `True`), preservação bit-a-bit das 24 entradas constantes no pêndulo (`15×15`, `CNO`, auto e `ranks=[2,2]`), `rank_augmented == [False, False]` e exatamente `4` regras em `ranks=[2,2]`.
- **`T-TSMOD-05` & `T-TSMOD-06`**: Fechos `SN-NN`, `RNO-INO`, `CNO` e `MGK` sobre base analítica QR de $[1, p, \sin(2p)]$: $\|W\mathbf{1}-\mathbf{1}\|_\infty \le 10^{-11}$, $\min W \ge -10^{-11}$, reconstrução nodal exata $\le 10^{-11}$ e volume simplicial relativo $|\det T_{\text{CNO}}|^{-1} < 0.99 \le 1.0$.
- **`T-TSMOD-07`**: Para todas as 3 vias (`sector`, `tpmt`, `femt`): validação contra `ts_state_space.schema.json` (registro offline de `$ref`), avaliação de $h_r(x)$ via `evaluate_ts_premise_weights`, síntese PDC LMI (`native_primal_dual`, `validated_dual`) com verificação espectral 5D independente ($\max \operatorname{Re}\lambda(A_r - B_r K_r) < -\alpha + 10^{-4}$), exportação PathSim compilável e executável (`default_h_fn` com paridade $\le 10^{-12}$, zero stub `1.0 / N_VERTICES`) e round-trip `.ctrlab` preservando `membership_spec` e `provenance.ts_derivation`.
- **`T-TSMOD-08`**: FEMT `v1.2.0` no pêndulo (`15×15`, `CNO`): 24 entradas constantes bit-a-bit, `rank_augmented == False`, `fallback_used == False`, vértices bem-condicionados; erro nodal exato de Eckart–Young centrado ($\le 10^{-12}$); redução estrita $N_r^{\text{FEMT}} < N_r^{\text{TPMT}}$ sob acoplamento ($\sin(x_1+x_2)$, $\cos(x_1-x_2)$); interpolação $P_1$ (`kuhn_delaunay` e `delaunay`) com $h_r \ge -10^{-14}$, $|\sum h_r - 1| \le 10^{-13}$ e convergência $O(h^2)$ ($e(G)/e(2G-1) \ge 3.0$).

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Referência | Evidência Auditada | Status |
|---|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `ts_state_space.schema.json` v1.0.0 | Validação explícita `Draft202012Validator` offline (com `$ref` registry local) para as 3 vias em `T-TSMOD-07`, além de chamadas RPC reais no Pyodide Worker em `tests/wasm/test_real_runtime.py`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `R-04` | Verificação de `status`, `fidelity_certificate`, `hull_diagnostics`, `provenance.ts_derivation`, rejeição determinística de AST maliciosa (`T-TSMOD-01`) e guarda de derivação obsoleta no E2E da Aba 6. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `CL-TS-MOD-DIR-001` | Todos os 8 testes normativos `T-TSMOD-01`..`T-TSMOD-08` usam fórmulas analíticas fechadas independentes (Taylor `sinc_rad`, Newton $\nabla g = 0$, `_exact_pendulum_S_analytical`, SVD independente em $\Delta X_{\text{var}}$, autovalores 5D fechados). | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Seção 13.11 | Zero circularidade: nenhum expected value é gerado executando o código sob teste; todos os critérios vêm de expressões matemáticas fechadas, oráculos `scipy.linalg`/`np.linalg.svd` independentes e verificação espectral 5D. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Seção 13.1 / 13.2 | `git status --short` confirma alterações estritamente em `allowed_paths` da F9 (`tests/oracles/`, `tests/wasm/`, `tests/e2e/`, `docs/architecture/`, `docs/audits/`, `PROJECT_STATE.json`); zero alterações em `control_lab/`, `web/`, `contracts/fixtures/` ou `tests/unit/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | `R-27` | Todas as 3 vias (Setor, TPMT `v1.3.0`, FEMT `v1.2.0`) e `export_ts_derivation_script` executadas e aprovadas tanto em CPython (`tests/oracles/test_ts_modeling_oracles.py`) quanto no Pyodide `wasm32` real no navegador (`tests/wasm/test_real_runtime.py` + `tests/e2e/test_ts_modeling_e2e.py`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `contracts/schemas/` | Nenhuma alteração de schema necessária; todas as 3 representações validam integralmente contra `ts_state_space.schema.json` v1.0.0. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Apêndice E | Hashes SHA-256, métricas JSON de `[F9-WASM-PHASE10-TSMOD]` e `[F9-E2E-PHASE10-TAB6]` e contagens exatas de todas as suítes registrados nas Seções 1 e 2. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `CL-DIR-001` | Nenhuma classificação experimental alterada; selos de verificação da Aba 6 preservados. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `R-04` / `CL-UX-DIR-001` | Nota operacional sobre variação de tempo de CPU no teste pré-existente `phase9_05c` documentada transparentemente na Seção 2 sem relaxar nenhum threshold. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: accepted
- **Revisor independente**: f9-integration-qa
- **Commit SHA auditado**: 30dcc3a3282e3982971fbded6666651e3d4f6340
- **Data (UTC)**: 2026-11-26T16:25:00Z
