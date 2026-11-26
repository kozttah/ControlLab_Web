# Handoff e Parecer F9 — `WP-TSMOD-02C-F5-FEMT-CENTERED-SUBSPACE`

- **WorkPackage**: `WP-TSMOD-02C-F5-FEMT-CENTERED-SUBSPACE`
- **Frente Produtora**: `F5 (f5-fuzzy-ts)` — Refinamento Algébrico da FEMT (`v1.2.0`): Restrição ao Subespaço Variante $\mathcal{I}_{\text{var}}$, Extração da Média Amostral, SVD Centrada sobre $\Delta X_{\text{var}}$ e Aumento pelo Elemento Médio (Peso Uniforme $\frac{1}{N_g}\mathbf{1}_{N_g}$)
- **Commit Base**: `6983d4131eae8f603876e1f3c1dae2df139e4448`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-04`, `R-05`, `R-21`, `R-27`, Apêndice E), `CL-TS-MOD-DIR-001 v1.2.0` (Seções 5.1, 5.2, 5.3, 6 e 7; `T-TSMOD-05`, `T-TSMOD-08`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-26T12:03:34Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Verificação via `git status --short` e `git diff --stat` confirmou isolamento estrito de propriedade da Frente F5: **apenas** `control_lab/fuzzy/femt.py` e `tests/unit/f5/test_femt_engine.py` foram modificados. ZERO alterações em `tpmt.py`, `sector_nonlinearity.py`, `ts_derivation.py`, `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/`, `tests/security/`, `web/` ou outras frentes produtoras.

| Artefato F5 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/fuzzy/femt.py` | `9eecd8435ec5ea0679cd411fc50c96c4d969976911dcf7545252bed100b170ed` | Refinamento `v1.2.0` de `femt_svd_decompose` e `derive_ts_femt` (100% NumPy/SciPy puro, zero `linalg.inv`, zero `eval`/`exec`): partição estrutural $\mathcal{I}_{\text{const}} \sqcup \mathcal{I}_{\text{var}}$ (AST via `_build_ast_varying_mask` + variação numérica), extração da média amostral $\bar{x}_{\text{var}}$, SVD econômica centrada apenas sobre $(\Delta X_{\text{var}})^T$, reortogonalização de $U_\Delta$ contra $\mathbf{1}_{N_g}$ e aumento ortonormal com $u_0 = \frac{1}{\sqrt{N_g}}\mathbf{1}_{N_g}$, pré-condicionamento RMS invariante a $N_g$ garantindo `rank_augmented == False` em `sn_nn_matrix`, atualização de vértices via `scipy.linalg.solve`, remontagem bit-a-bit de `S_const_flat` e tratamento do caso degenerado puramente LTI (`M_var == 0`). |
| `tests/unit/f5/test_femt_engine.py` | `1400ce0a5fd1a333267f5678d77f77ac7a39557e6dd48b24bf2ad945a7829d8f` | Cobertura unitária normativa `T-TSMOD-08 (v1.2.0)`: preservação bit-a-bit das 24 entradas constantes do pêndulo invertido de 4 estados (`pendulum_16`) nos 4 fechos (`SN-NN`, `RNO-INO`, `CNO`, `MGK`), condicionamento e vértices físicos em `CNO`, `rank_augmented == False` sob truncamento agressivo (`rank = 1, 2, 3`), caso degenerado LTI (`M_var == 0`), Eckart–Young centrado com constantes grandes (`~1e4`) e compatibilidade ponta a ponta com `export_ts_derivation_script` (Python standalone executável + MATLAB). |

---

## 2. Verificações Independentes e Oráculos Executados pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de ownership** (`git status --short`, `git diff --stat`) | Apenas 2 arquivos modificados (`control_lab/fuzzy/femt.py`, `tests/unit/f5/test_femt_engine.py`); ZERO alterações em `tpmt.py`, `sector_nonlinearity.py`, `ts_derivation.py`, `contracts/`, `tests/oracles/`. | Ownership F5 (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Segurança AST / Zero `linalg.inv`** (`R-21` / `CL-DIR-001`) | Inspeção AST independente em `control_lab/fuzzy/femt.py`: **0** ocorrências de `eval`, `exec`, `compile`, `.inv()` ou `from ... import inv`. | `R-21` / Zero `linalg.inv` | PASS |
| **Oráculo Independente — Eckart–Young Centrado (`pendulum_16`, 15×15)** | Confronto de `femt_svd_decompose(S_nodes, rank=r)` para $r \in \{1, 2, 3, 4, 5\}$ ($N_g = 225$, $M = 30$, $M_{\text{var}} = 6$, $M_{\text{const}} = 24$) contra `np.linalg.svd(Delta_var_T)` independente: `max | ||X_T - U_raw @ C_raw||_F - sqrt(sum(s_d[r:]**2)) | = 3.184e-15`, `max | ||X_T - U_raw @ C_raw||_2 - s_d[r] | <= 1e-12`, `ortho_err <= 2.699e-15`, `max |mean(U_delta)| = 5.785e-17`. | Erro nodal exato de Eckart–Young centrado (`CL-TS-MOD-DIR-001 v1.2.0` Seção 5.2 / `T-TSMOD-08`) | PASS |
| **Oráculo Independente — `pendulum_16` (15×15, `CNO`)** | `num_rules = 6`, `svd_rank = 5`, `M_var = 6`, `M_const = 24`, `rank_augmented = False`, `fallback_used = False`, `cond_W = 3.2477`, `cond_T = 6.6140`, `max |S_r[const] - S_const| = 0.0`, `grid_rel_l2 = 9.563e-11`, `val_rel_l2 = 4.786e-04`, Schema Draft 2020-12 válido, replay do script Python exportado (`export_ts_derivation_script`) com `max_replay_err = 5.329e-14 < 1e-12`. | `T-TSMOD-08 (v1.2.0)` + `T-TSMOD-05` + `TSStateSpace` v1.0.0 | PASS |
| **Oráculo Independente — `pendulum_16` (15×15, `SN-NN`)** | `num_rules = 6`, `svd_rank = 5`, `M_var = 6`, `M_const = 24`, `rank_augmented = False`, `fallback_used = False`, `cond_W = 7.5630`, `cond_T = 18.4262`, `max |S_r[const] - S_const| = 0.0`, `grid_rel_l2 = 9.563e-11`, `val_rel_l2 = 4.786e-04`, Schema Draft 2020-12 válido, replay do script Python exportado com `max_replay_err = 1.776e-13 < 1e-12`. | `T-TSMOD-08 (v1.2.0)` + `T-TSMOD-05` + `TSStateSpace` v1.0.0 | PASS |
| **Execução `acceptance_cmd`** | `pytest tests/unit/f5/test_femt_engine.py tests/unit/f1/test_ts_derivation_scripts.py -v`: **45 passed in 19.41s** (`exit 0`). | Aceite do WorkPackage | PASS |
| **Regressão Expandida (`F5` + `F1 RPC` + `Oracles`)** | `pytest tests/unit/f5/ tests/unit/f1/test_ts_derivation_rpc.py tests/oracles/ -q`: **465 passed in 89.68s** (`exit 0`, 0 failed, 0 skipped). | Sem regressões | PASS |

---

## 3. Revisão Matemática (`CL-TS-MOD-DIR-001 v1.2.0` Seções 5.1, 5.2, 5.3 e 7)

- **Partição $\mathcal{I}_{\text{const}} \sqcup \mathcal{I}_{\text{var}}$**: `_build_ast_varying_mask` identifica variáveis ativas na AST em todos os blocos `(A, B, C, D, Bw, Dyw, Cz, Dzu, Dzw)` e intersecta com o critério numérico `max_q |delta_full[q, j]| > 1e-14 * (1 + |mean_full[j]|)`, fixando `S_const_flat[~ast_varying_mask] = X_T[0, ~ast_varying_mask]`.
- **Extração da média e SVD sobre o delta**: `femt_svd_decompose` extrai `mean_full` e executa `np.linalg.svd(Delta_var_T, full_matrices=False)` estritamente sobre as $M_{\text{var}}$ colunas variantes.
- **Reortogonalização e aumento ortonormal**: $U_\Delta$ é reortogonalizado contra $\mathbf{1}_{N_g}$ (com re-ortonormalização QR caso `||U_delta^T U_delta - I||_F > 1e-13`) e aumentado com $u_0 = \frac{1}{\sqrt{N_g}}\mathbf{1}_{N_g}$ (equivalente ao peso uniforme $\frac{1}{N_g}\mathbf{1}_{N_g}$).
- **Fecho convexo sem coluna extra**: o pré-condicionamento RMS invariante a $N_g$ ($\tilde{U}_\Delta = \sqrt{N_g} U_\Delta$, $\tilde{C}_\Delta = C_\Delta / \sqrt{N_g}$) produz analiticamente $U_{\text{SN}} = [\mathbf{1} - \sum_k \tilde{u}_{\Delta, k}, \tilde{U}_\Delta]$ com soma de linha unitária exata, assegurando `rank_augmented == False` em `sn_nn_matrix`; todas as atualizações de vértices usam `scipy.linalg.solve` (zero `linalg.inv`) exclusivamente em $\mathcal{I}_{\text{var}}$, seguidas de remontagem bit-a-bit de `S_const_flat`.
- **Caso degenerado LTI (`M_var == 0`)**: tratado explicitamente em `femt_svd_decompose` (`rank = 0`, `U_raw = u0`, `C_raw = sqrt(N_g) * mean_full`) e em `derive_ts_femt` (`N_r = 1`, `W_nodal = 1_{N_g x 1}`, `C_final = S_const_flat`).

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Referência | Evidência Auditada | Status |
|---|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `ts_state_space.schema.json` v1.0.0 | `TSStateSpace.to_dict()` de `derive_ts_femt` (`CNO` e `SN-NN` em `pendulum_16` 15×15) validado contra `contracts/schemas/ts_state_space.schema.json` (Draft 2020-12) + compatibilidade integral com `export_ts_derivation_script` (`max_replay_err = 5.329e-14`) e `test_ts_derivation_rpc.py`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `R-04` | `derive_ts_femt` retorna `Result` padronizado com `status`, `assumptions` (`centered_mean_augmented=True`, `zero_linalg_inv=True`), `diagnostics` (`n_varying_entries`, `n_constant_entries`, `hull_diagnostics`, `fidelity_certificate`), `provenance.ts_derivation` e erros tipados sem fallback silencioso. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `T-TSMOD-08` | `test_femt_engine.py` verifica identidades analíticas de Eckart–Young centrado, ortonormalidade de `U_raw`, ortogonalidade de `U_delta` à média, preservação bit-a-bit de constantes em todos os 4 fechos, `rank_augmented == False` sob truncamento agressivo e caso LTI `M_var == 0`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Seção 13.11 | Oráculos independentes executados pela F9 no pêndulo invertido de 4 estados (`pendulum_16`, 15×15): confronto de `femt_svd_decompose` contra `np.linalg.svd(Delta_var_T)` (`|diff| <= 3.184e-15`), verificação independente de `max |S_r[const] - S_const| == 0.0`, `rank_augmented == False`, `fallback_used == False` e replay standalone em subprocesso isolado (`python -I`, erro `5.329e-14` em `CNO` e `1.776e-13` em `SN-NN`). | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Seção 13.1 / 13.2 | `git status --short` e `git diff --stat` confirmam alterações restritas a `control_lab/fuzzy/femt.py` e `tests/unit/f5/test_femt_engine.py`; ZERO modificações em `tpmt.py`, `sector_nonlinearity.py`, `ts_derivation.py`, `contracts/fixtures/` ou `tests/oracles/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | `R-27` | Código 100% Python + NumPy/SciPy (`np.linalg.svd`, `np.linalg.qr`, `scipy.linalg.solve`), sem dependências externas fora do Pyodide `wasm32`; validação no runtime Pyodide Wasm será consolidada em `WP-TSMOD-05-F9`. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `ts_state_space.schema.json` | Nenhuma alteração de schema necessária; metadados `n_varying_entries`, `n_constant_entries` e `centered_mean_augmented` são registrados em `provenance.ts_derivation` mantendo aderência total ao schema v1.0.0. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Apêndice E | Hashes SHA-256 dos 2 artefatos, métricas independentes do `pendulum_16` (`cond_W = 3.2477`, `max_const_diff = 0.0`, `max_replay_err = 5.329e-14`, Eckart–Young `|diff| <= 3.184e-15`), `acceptance_cmd` (`45 passed`) e regressão (`465 passed`) registrados neste parecer. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `CL-DIR-001` | Não introduz nem altera métodos experimentais; `control_lab/experimental/sdp_educational/` permanece isolado e inalterado. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `R-04` / Envelope Wasm | Guardas de envelope Wasm (`RESOURCE_LIMIT`), validação de `rank` fora do intervalo em `M_var == 0` e `M_var > 0`, e alertas `NN_VIOLATED` (em `MGK`) preservam mensagens tipadas com `next_step` acionável. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: accepted
- **Revisor independente**: f9-integration-qa
- **Commit SHA auditado**: 6983d4131eae8f603876e1f3c1dae2df139e4448
- **Data (UTC)**: 2026-11-26T12:03:34Z
