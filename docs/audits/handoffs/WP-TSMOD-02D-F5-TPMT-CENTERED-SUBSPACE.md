# Handoff e Parecer F9 — `WP-TSMOD-02D-F5-TPMT-CENTERED-SUBSPACE`

- **WorkPackage**: `WP-TSMOD-02D-F5-TPMT-CENTERED-SUBSPACE`
- **Frente Produtora**: `F5 (f5-fuzzy-ts)` — Refinamento Algébrico da TPMT (`v1.3.0`): Restrição ao Subespaço Variante $\mathcal{I}_{\text{var}}$, Centralização Modal $P_\perp^{(d)}$ na HOSVD/HOOI (`center_modes=True`), Aumento Ortonormal pelo Elemento Médio $u_0^{(d)} = \frac{1}{\sqrt{G_d}}\mathbf{1}_{G_d}$ e Remontagem Bit-a-Bit de $\mathcal{I}_{\text{const}}$
- **Commit Base**: `1af9e2252cebcf5e3f6726f9c249f1963250cc0e`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-04`, `R-05`, `R-21`, `R-27`, Apêndice E), `CL-TS-MOD-DIR-001 v1.3.0` (Seções 4.2 item 5, 4.5, 5.1, 6 e 7; `T-TSMOD-04`, `T-TSMOD-05`, `T-TSMOD-06`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-26T14:43:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Verificação via `git status --short` e `git diff --stat` confirmou isolamento estrito de propriedade da Frente F5: **apenas** `control_lab/fuzzy/tpmt.py` e `tests/unit/f5/test_tpmt_engine.py` foram modificados. ZERO alterações em `femt.py`, `sector_nonlinearity.py`, `ts_derivation.py`, `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/`, `tests/security/`, `web/` ou outras frentes produtoras.

| Artefato F5 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/fuzzy/tpmt.py` | `27922ab4ee9eb3e5467a9617e2c1a37368289a878c6db01703aef8f4bd5e1371` | Refinamento `v1.3.0` de `_centered_mode_basis`, `hosvd_sampled_func`, `hooi_sampled_func` e `derive_ts_tpmt` (100% NumPy/SciPy puro, zero `linalg.inv`, zero `eval`/`exec`): suporte retrocompatível a `center_modes=False` (padrão) e `center_modes=True` com projetor modal $P_\perp^{(d)} = I_{G_d} - \frac{1}{G_d}\mathbf{1}_{G_d}\mathbf{1}_{G_d}^T$, reortogonalização contra $\mathbf{1}_{G_d}$ e aumento ortonormal por $u_0^{(d)} = \frac{1}{\sqrt{G_d}}\mathbf{1}_{G_d}$; partição estrutural $\mathcal{I}_{\text{const}} \sqcup \mathcal{I}_{\text{var}}$ em `derive_ts_tpmt`, tensor compacto `S_var_tensor` (`ord_func=1`), pré-condicionamento RMS invariante a $G_d$ garantindo `rank_augmented == False` em todos os modos (inclusive sob `ranks=[2, 2]` e reamostragem 1D), atualizações via `scipy.linalg.solve` (`mode_inverse_product`), remontagem bit-a-bit de `S_const_flat` e tratamento explícito do caso degenerado LTI (`M_var == 0`). |
| `tests/unit/f5/test_tpmt_engine.py` | `8f883621edeb4424a8ad70c1ac91dca8f0f6f4fd7a06a77972cff15bf29be7e1` | Cobertura unitária normativa `T-TSMOD-04 (v1.3.0)`: preservação bit-a-bit das 24 entradas constantes do pêndulo invertido de 4 estados (`pendulum_16`) nos 4 fechos (`SN-NN`, `RNO-INO`, `CNO`, `MGK`), vértices físicos apertados sob `CNO`, truncamento agressivo `ranks=[2, 2]` com exatamente 4 regras e `rank_augmented == [False, False]`, convergência monotônica de `hooi_sampled_func(..., center_modes=True)` preservando $\mathbf{1}_{G_d} \in \operatorname{col}(U^{(d)})$, reamostragem 1D (`linear` e `pchip`), caso degenerado LTI (`M_var == 0`) e compatibilidade ponta a ponta com `export_ts_derivation_script` (Python standalone executável + MATLAB). |

---

## 2. Verificações Independentes e Oráculos Executados pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de ownership** (`git status --short`, `git diff --stat`) | Apenas 2 arquivos modificados (`control_lab/fuzzy/tpmt.py`, `tests/unit/f5/test_tpmt_engine.py`); ZERO alterações em `femt.py`, `sector_nonlinearity.py`, `ts_derivation.py`, `contracts/`, `tests/oracles/`. | Ownership F5 (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Segurança AST / Zero `linalg.inv`** (`R-21` / `CL-DIR-001`) | Inspeção AST independente em `control_lab/fuzzy/tpmt.py`: **0** ocorrências de `eval`, `exec`, `compile`, `.inv()` ou `from ... import inv`. | `R-21` / Zero `linalg.inv` | PASS |
| **Oráculo Independente — HOSVD & HOOI Centrados (`(11, 9, 5)` + 100.0)** | Retrocompatibilidade `center_modes=False` confirmada; com `center_modes=True` vs SVD direta de $P_\perp^{(d)} T_{(d)}$: `ortho_err_max = 1.058e-15`, `mean_perp_max = 1.108e-17`, `sv_diff_max = 8.771e-14`; HOOI centrado monotônico (`19.243224 -> 18.546523`) preservando $\mathbf{1}_{G_d} \in \operatorname{col}(U^{(d)})$ com resíduo `2.483e-16`. | `CL-TS-MOD-DIR-001 v1.3.0` Seção 4.2 item 5 / Seção 7 | PASS |
| **Oráculo Independente — `pendulum_16` (15×15, `CNO` e `SN-NN`)** | `CNO`: `num_rules = 12`, `axis_ranks = [6, 2]`, `M_var = 6`, `M_const = 24`, `rank_augmented = [False, False]`, `fallbacks = [False, False]`, `cond_T = [4.2119, 1.0]`, `max |S_r[const] - S_const| = 0.0`, `grid_rel_l2 = 9.563e-11`, `val_rel_l2 = 4.774e-04`, Schema Draft 2020-12 válido, replay Python (`python -I`) com `max_err = 8.171e-14 < 1e-12`. `SN-NN`: `num_rules = 12`, `rank_augmented = [False, False]`, `cond_T = [11.8141, 3.5781]`, `max_const_diff = 0.0`, `replay_err = 7.105e-14 < 1e-12`. | `T-TSMOD-04 (v1.3.0)` + `T-TSMOD-05` + `TSStateSpace` v1.0.0 | PASS |
| **Oráculo Independente — `pendulum_16` (`ranks=[2, 2]` HOSVD/HOOI e `resample_points=[25, 25]`)** | `CNO ranks=[2, 2]`: `num_rules = 4`, `rank_augmented = [False, False]`, `cond_T = [1.0, 1.0]`, `max_const_diff = 0.0`, `replay_err = 2.487e-14`. `HOOI CNO ranks=[2, 2]`: `num_rules = 4`, `rank_augmented = [False, False]`, `cond_T = [1.0, 1.2676]`, `max_const_diff = 0.0`, `replay_err = 4.263e-14`. `CNO resample=[25, 25]`: `num_rules = 12`, `rank_augmented = [False, False]`, `cond_T = [3.6927, 1.0]`, `max_const_diff = 0.0`, `replay_err = 5.684e-14`. Todos válidos no Schema Draft 2020-12. | `T-TSMOD-04 (v1.3.0)` + `T-TSMOD-06` | PASS |
| **Execução `acceptance_cmd`** | `pytest tests/unit/f5/test_tpmt_engine.py tests/unit/f5/test_femt_engine.py tests/unit/f1/test_ts_derivation_scripts.py -v`: **68 passed in 22.12s** (`exit 0`). | Aceite do WorkPackage | PASS |
| **Regressão Expandida (`F5` + `F1 RPC` + `Oracles`)** | `pytest tests/unit/f5/ tests/unit/f1/test_ts_derivation_rpc.py tests/oracles/ -q`: **476 passed in 74.03s** (`exit 0`, 0 failed, 0 skipped). | Sem regressões | PASS |

---

## 3. Revisão Matemática (`CL-TS-MOD-DIR-001 v1.3.0` Seção 4.2 item 5 e Seção 7)

- **Retrocompatibilidade e centralização modal (`_centered_mode_basis`, `hosvd_sampled_func`, `hooi_sampled_func`)**: o parâmetro `center_modes: bool = False` preserva integralmente o comportamento anterior quando `False`. Com `center_modes=True`, aplica-se o projetor $P_\perp^{(d)} = I_{G_d} - \frac{1}{G_d}\mathbf{1}_{G_d}\mathbf{1}_{G_d}^T$ ao desdobramento modal antes da SVD, reortogonalizando $U_\perp^{(d)}$ contra $\mathbf{1}_{G_d}$ (com re-ortonormalização QR se $\|U_\perp^T U_\perp - I\|_F > 10^{-13}$) e aumentando ortonormalmente com $u_0^{(d)} = \frac{1}{\sqrt{G_d}}\mathbf{1}_{G_d}$. Na HOOI com `center_modes=True`, cada subproblema de atualização modal invoca `_centered_mode_basis(Y_d, tol=0.0, rank=eff_ranks[d], mode=d)`, mantendo convergência monotônica não-crescente e $\mathbf{1}_{G_d} \in \operatorname{col}(U^{(d)})$ em todas as iterações.
- **Partição $\mathcal{I}_{\text{const}} \sqcup \mathcal{I}_{\text{var}}$ e tensor compacto `S_var_tensor`**: `_build_ast_varying_mask` cobre todos os blocos `(A, B, C, D, Bw, Dyw, Cz, Dzu, Dzw)` e intersecta com o critério numérico `max |delta_full| > 1e-14 * (1 + |mean_full|)`. As entradas variantes são empacotadas em `S_var_tensor` de forma `(G_1, ..., G_D, M_var)` e decompostas com `ord_func=1` e `center_modes=True`.
- **Pré-condicionamento RMS e fecho convexo sem coluna extra**: a matriz $M_{\text{sn}}$ com escala $\sqrt{G_d}$ transforma analiticamente $U_{\text{work}} = [u_0^{(d)}, U_\perp^{(d)}]$ em uma base com soma de linha unitária exata, atualizando `core_var` via `mode_inverse_product(core_var, M_sn, d)` (`scipy.linalg.solve`, zero `linalg.inv`). Isso assegura `rank_augmented == False` em todos os modos, inclusive sob truncamento manual `ranks=[2, 2]` e reamostragem 1D (`linear` ou `pchip`), com guarda explícita para o caso de reamostragem com posto deficiente preservando o replay em `ts_derivation.py`.
- **Remontagem bit-a-bit e caso degenerado LTI (`M_var == 0`)**: `S_const_flat[~ast_varying_mask] = X_T[0, ~ast_varying_mask]` é transmitido para todos os $N_r$ vértices, preenchendo-se apenas `varying_mask` com `core_var.reshape(n_rules, n_varying_entries)`. Quando `n_varying_entries == 0`, o pipeline produz exatamente $N_r = 1$ regra, $W^{(d)} = \mathbf{1}_{G_d \times 1}$, `rank_augmented = False` e vértice bit-a-bit idêntico a `S_const_flat`.

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Referência | Evidência Auditada | Status |
|---|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `ts_state_space.schema.json` v1.0.0 | `TSStateSpace.to_dict()` de `derive_ts_tpmt` (`CNO`, `SN-NN`, `ranks=[2, 2]`, `HOOI` e `resample_points=[25, 25]` em `pendulum_16` 15×15) validado contra `contracts/schemas/ts_state_space.schema.json` (Draft 2020-12) + compatibilidade integral com `export_ts_derivation_script` (`max_replay_err <= 8.171e-14`) e `test_ts_derivation_rpc.py`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `R-04` | `derive_ts_tpmt` retorna `Result` padronizado com `status`, `assumptions` (`centered_mean_augmented=True`, `zero_linalg_inv=True`), `diagnostics` (`n_varying_entries`, `n_constant_entries`, `axis_ranks`, `grid_rel_l2_error`, `val_rel_l2_error`), `provenance.ts_derivation` e erros tipados (`ValidationError`, `DimensionMismatchError`, `ResourceLimitError`, `NumericalInconclusiveError`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `T-TSMOD-04` | `test_tpmt_engine.py` verifica identidades analíticas da HOSVD/HOOI centradas, preservação bit-a-bit de constantes em todos os 4 fechos (`SN-NN`, `RNO-INO`, `CNO`, `MGK`), `rank_augmented == False` sob truncamento agressivo `ranks=[2, 2]` e reamostragem 1D (`linear`/`pchip`), além do caso LTI degenerado `M_var == 0`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Seção 13.11 | Oráculos independentes executados pela F9: confronto direto de `hosvd_sampled_func`/`hooi_sampled_func(..., center_modes=True)` contra SVD de $P_\perp^{(d)} T_{(d)}$ (`ortho_err <= 1.058e-15`, `sv_diff <= 8.771e-14`, `hooi_ones_res <= 2.483e-16`), verificação independente no `pendulum_16` (15×15) de `max |S_r[const] - S_const| == 0.0`, `rank_augmented == [False, False]`, `num_rules == 4` sob `ranks=[2, 2]` e replay standalone em subprocesso isolado (`python -I`, erro máximo `8.171e-14`). | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Seção 13.1 / 13.2 | `git status --short` e `git diff --stat` confirmam alterações restritas a `control_lab/fuzzy/tpmt.py` e `tests/unit/f5/test_tpmt_engine.py`; ZERO modificações em `femt.py`, `sector_nonlinearity.py`, `ts_derivation.py`, `contracts/fixtures/` ou `tests/oracles/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | `R-27` | Código 100% Python + NumPy/SciPy (`scipy_linalg.svd`, `np.linalg.qr`, `scipy_linalg.solve`), sem dependências externas fora do Pyodide `wasm32`; validação no runtime Pyodide Wasm será consolidada em `WP-TSMOD-05-F9`. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `ts_state_space.schema.json` | Nenhuma alteração de schema necessária; metadados `n_varying_entries`, `n_constant_entries` e `centered_mean_augmented` são registrados em `provenance.ts_derivation` mantendo aderência total ao schema v1.0.0. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Apêndice E | Hashes SHA-256 dos 2 artefatos, métricas independentes do `pendulum_16` (`CNO`, `SN-NN`, `ranks=[2, 2]`, `HOOI`, `resample_points=[25, 25]`), oráculo matemático HOSVD/HOOI centrado, `acceptance_cmd` (`68 passed`) e regressão (`476 passed`) registrados neste parecer. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `CL-DIR-001` | Não introduz nem altera métodos experimentais; `control_lab/experimental/sdp_educational/` permanece isolado e inalterado. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `R-04` / Envelope Wasm | Guardas de envelope Wasm (`RESOURCE_LIMIT` para `D`, nós, elementos e `N_r` tanto pré- quanto pós-decomposição), validação de `ranks` fora do intervalo, e alertas `NN_VIOLATED` (em `MGK`) preservam mensagens tipadas com `next_step` acionável. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: accepted
- **Revisor independente**: f9-integration-qa
- **Commit SHA auditado**: 1af9e2252cebcf5e3f6726f9c249f1963250cc0e
- **Data (UTC)**: 2026-11-26T14:43:00Z
