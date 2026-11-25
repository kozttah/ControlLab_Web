# Handoff e Parecer F9 — `WP-TSMOD-02-F5-TPMT-ENGINE`

- **WorkPackage**: `WP-TSMOD-02-F5-TPMT-ENGINE`
- **Frente Produtora**: `F5 (f5-fuzzy-ts)` — Motor de Transformação do Produto Tensorial (TPMT: HOSVD, HOOI, SN-NN, RNO-INO, CNO, MGK)
- **Commit Base**: `93c590937f1bb0c288876a46128b02fb5dfd5998`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-04`, `R-05`, `R-21`, `R-27`, Apêndice E), `ADR-006`, `CL-TS-MOD-DIR-001 v1.0.0` (Seções 4, 5 e `T-TSMOD-04`..`06`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-25T09:17:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Verificação via `git status --short` e `git diff --check` confirmou isolamento estrito de propriedade da Frente F5 (`control_lab/fuzzy/` e `tests/unit/f5/`), sem qualquer alteração em `contracts/`, `tests/oracles/`, `tests/security/`, `web/` ou outras frentes produtoras.

| Artefato F5 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/fuzzy/tpmt.py` | `cc7beafffccd2987823ad67cc276dc1cc7b2dd8ecd71d6b07ff057c80a2285ed` | Álgebra tensorial 0-indexed (`unfold_mode`, `fold_mode`, `mode_product`, `mode_inverse_product`, `reconstruct_tensor`), decomposições `hosvd_sampled_func` e `hooi_sampled_func` (sem Kronecker explícito), reamostragem 1D (`resample_basis_1d`), fechos convexos (`sn_nn_matrix` via Sherman–Morrison, `rno_ino_matrix`, `cno_matrix` via `ConvexHull` + `SLSQP` com gradiente analítico, `mgk_matrix` com auditoria `NN_VIOLATED`) e pipeline completo `derive_ts_tpmt` com guarda de envelope Wasm e certificado de fidelidade. |
| `control_lab/fuzzy/ts_bridge.py` | `478ddfe27bef6641863e54a2c8313d21c8b4bfa14c1c889bdef094a84dd06f86` | Suporte a `representation_kind == "tpmt_interpolated"` em `evaluate_ts_premise_weights(...)` com interpolação linear 1D por eixo, clamping seguro nos limites do domínio preservando SN e NN, e suporte a entrada por mapeamento de premissas ou vetor completo de estados. |
| `control_lab/fuzzy/__init__.py` | `1c177636c277a9b553fb58013bfddabb2fe9f8517dd6aa4279931cdf5566f1d7` | Reexportação da API pública TPMT (`unfold_mode`, `fold_mode`, `mode_product`, `mode_inverse_product`, `reconstruct_tensor`, `hosvd_sampled_func`, `hooi_sampled_func`, `resample_basis_1d`, `sn_nn_matrix`, `rno_ino_matrix`, `cno_matrix`, `mgk_matrix`, `derive_ts_tpmt`, `HOSVDResult`, `HOOIResult`, limites Wasm). |
| `tests/unit/f5/test_tpmt_engine.py` | `47664232d56deba1c7360e7c649e46914e6e9cb2069c6d41df9e7910a40d8245` | Cobertura unitária normativa de `T-TSMOD-04`, `T-TSMOD-05`, `T-TSMOD-06`, pipeline `derive_ts_tpmt` + schema JSON Draft 2020-12 + `evaluate_ts_premise_weights` e guardas de envelope Wasm. |

---

## 2. Verificações Independentes e Oráculos Executados pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de propriedade** (`git status --short`, `git diff --check`) | Apenas 4 arquivos em `control_lab/fuzzy/` e `tests/unit/f5/`; `git diff --check` exit `0`. | Ownership F5 (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Segurança AST / Zero `inv`** (`R-21` / `CL-DIR-001`) | Inspeção AST em `tpmt.py` e `ts_bridge.py`: **0** ocorrências de `eval`, `exec`, `compile`, `getattr`, `__import__`, `.inv()` ou `from ... import inv`. | `R-21` / Zero `linalg.inv` | PASS |
| **Oráculo Tensorial Independente (`T-TSMOD-04`)** | Bijeção exata `fold_mode(unfold_mode(T, d), d, T.shape) == T` e conferência de `mode_product` vs `np.einsum` em tensores 4D `(3,5,7,2)` e 5D `(2,3,5,4,6)`. HOSVD em 4D/5D assimétricos: `max ||U^T U - I||_F = 5.21e-15 <= 1e-13`; cota de De Lathauwer conferida contra `np.linalg.svd` independente (`diff <= 1e-12`). HOOI em tensor 5D `(7,8,9,2,2)` posto `[3,3,3]`: redução estritamente monotônica `41.9987 -> 40.4445` em 50 iterações. | `<= 1e-13`, cota De Lathauwer, monotonicidade HOOI (`T-TSMOD-04`) | PASS |
| **Oráculo de Fechos Convexos (`T-TSMOD-05`)** | `sn_nn_matrix`: validado em `1 in col(U)` (`rank_augmented=False`, `err <= 1e-11`) e `1 not in col(U)` (`rank_augmented=True`, fatia nula preservando reconstrução exata). `rno_ino_matrix` e `cno_matrix` para `r = 2, 3, 4`: `max ||W 1 - 1||_inf = 8.88e-16 <= 1e-11`, `min(W) = -9.72e-13 >= -1e-11`, `max rec_err = 8.50e-15 <= 1e-10(1 + ||S^D||_F)`, `fallback=False` em todos os casos (`r=4` CNO atingiu `|det(T)| = 25.8009`). | `<= 1e-11`, `>= -1e-11`, invariância `<= 1e-10` (`T-TSMOD-05`) | PASS |
| **Aperto Geométrico `test_uni2.m` (`T-TSMOD-06`)** | Benchmark uniciclo `B(theta) = [cos(theta) 0; sin(theta) 0; 0 1]`: `|det(T_rno)| = 8.0171` (volume `0.1247` vs SN-NN), `|det(T_cno)| = 8.0177` (volume `0.1247` vs SN-NN), ambos superando amplamente SN-NN (`|det(I)| = 1.0`). | `CNO`/`RNO-INO` mais apertado que `SN-NN` (`T-TSMOD-06`) | PASS |
| **Pipeline `derive_ts_tpmt` 2D & 3D + Schema + Clamping** | Sistema 2D ativo em 4 estados (`x1, x4` lineares excluídos -> `active_variables=['x2', 'x3']`) com erro fora da grade `2.32e-04`; sistema 3D ativo em 5 estados (`x1, x5` lineares excluídos -> `active_variables=['x2', 'x3', 'x4']`, 8 regras, `val_rel_l2=4.98e-04`). Ambos validados contra `contracts/schemas/ts_state_space.schema.json` (Draft 2020-12). `evaluate_ts_premise_weights` fora da grade e fora do domínio preservou SN e NN via clamping (`min >= -1e-12`, `|sum - 1| <= 1e-12`). | Schema Draft 2020-12, detecção de variáveis ativas, clamping SN-NN | PASS |
| **Integração `ADR-006` / `R-05`** | `TSStateSpace` TPMT com `x2` não medido (`ts_partially_observed`) bloqueia `make_pdc_spec(architecture='pdc')` com `HYPOTHESIS_VIOLATED` e permite `robust_single_gain`; `ts_measured` permite `pdc`. | `R-05` / `ADR-006` | PASS |
| **Guarda de Pré-Alocação Wasm** | `derive_ts_tpmt` com `grid_points=[100_000, 100_000]` ($10^{10}$ nós) rejeitado em **0.60 ms** com `RESOURCE_LIMIT` antes de alocar qualquer tensor. | Envelope Wasm (`CL-TS-MOD-DIR-001` Seção 4.5) | PASS |
| **Regressão completa (`pytest`)** | `/home/antigravity/.venv/bin/pytest tests/unit/f5/ tests/oracles/ tests/security --ignore=tests/security/test_real_browser_security.py -q`: **427 passed, 0 failed, 0 skipped** em `56.15s` (`exit 0`). | Sem regressões | PASS |

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `TSStateSpace.to_dict()` derivado por `derive_ts_tpmt` validado estritamente contra `contracts/schemas/ts_state_space.schema.json` (Draft 2020-12) e round-trip `TSStateSpace.from_dict()` + integração com `evaluate_ts_premise_weights` e `make_pdc_spec`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `derive_ts_tpmt` e `evaluate_ts_premise_weights` retornam `Result` padronizado com `status`, `assumptions`, `diagnostics`, `provenance`, `warnings` e `error` tipado (`ValidationError`, `DimensionMismatchError`, `ResourceLimitError`, `NumericalInconclusiveError`, `HypothesisViolatedError`) sem fallback silencioso (`R-04`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `test_tpmt_engine.py` valida identidades algébricas (`fold`/`unfold`, `mode_inverse_product`), ortonormalidade HOSVD, cota de De Lathauwer, monotonicidade HOOI, aumento de posto SN-NN com fatia nula e invariância exata de reconstrução nos fechos convexos. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Oráculos independentes executados pela F9: conferência de `mode_product` vs `np.einsum`, cota de De Lathauwer via `np.linalg.svd` independente em 4D/5D assimétricos, aperto geométrico `|det(T)|` em `r=2,3,4` e `test_uni2.m`, reconstrução fora da grade de sistemas qLPV 2D/3D e teste de pré-alocação com $10^{10}$ nós. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | `git status --short` confirma alterações exclusivas em `control_lab/fuzzy/` e `tests/unit/f5/`; zero modificações em `contracts/fixtures/` ou `tests/oracles/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Implementação 100% Python + NumPy/SciPy (`scipy.linalg`, `scipy.interpolate.PchipInterpolator`, `scipy.optimize.minimize`, `scipy.spatial.ConvexHull`, `scipy.stats.qmc`), sem YALMIP nem dependências nativas fora do Pyodide (`R-27`). Validação em Wasm será consolidada em `WP-TSMOD-05-F9`. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma alteração de schema; `TSStateSpace` com `representation_kind="tpmt_interpolated"` adere integralmente a `ts_state_space.schema.json` v1.0.0 existente. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256 dos 4 artefatos, métricas dos oráculos independentes (`5.21e-15`, `|det T_cno|=25.8009` em `r=4`, `8.0177` em `test_uni2.m`, `0.60 ms` no guarda Wasm) e resultado de regressão (`427 passed`) registrados neste parecer. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Não introduz métodos experimentais; `control_lab/experimental/sdp_educational/` permanece inalterado e isolado. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Limites de envelope Wasm (`D > 5`, nós `> 250_000`, elementos `> 10_000_000`, regras `> 256`), matrizes singulares/mal-condicionadas (`cond > 1e12`), sistemas LTI constantes e violação de NN em `MGK` (`NN_VIOLATED`) emitem erros/alertas tipados com `next_step` claro. | CONFORME |

---

## 4. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit Base Auditado**: `93c590937f1bb0c288876a46128b02fb5dfd5998`
- **Data (UTC)**: `2026-11-25T09:17:00Z`
