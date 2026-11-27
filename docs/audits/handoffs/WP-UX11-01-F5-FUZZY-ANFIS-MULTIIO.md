# Handoff e Parecer F9 — `WP-UX11-01-F5-FUZZY-ANFIS-MULTIIO`

- **WorkPackage**: `WP-UX11-01-F5-FUZZY-ANFIS-MULTIIO`
- **Frente Produtora**: `F5 (f5-fuzzy-ts)` — Suporte multi-saída (`M >= 1`), `n_mfs` e `mf_type` heterogêneos por entrada no ANFIS (`fit_anfis`) e validação `N × M` (avaliação pontual, superfície por fatia 2D com `output_name`/`fixed_inputs` e round-trip IEEE 1855-2016 FML) no motor Fuzzy
- **Commit Base**: `032ec55e017281feba82273e6fae3fd9b54baf1d`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-02`, `R-13`, `R-14`, `ADR-006`, Seções 5.1, 5.6, 13.7, 13.11 e Apêndice E), `CL-UX-DIR-001 v1.0.0` (Seção 9.4), testes normativos `T-FZ-01`, `T-FZ-02`, `T-ANFIS-01`
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-27`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Verificação via `git status --short` e `git diff --stat` confirmou isolamento estrito dentro de `allowed_paths` da Frente F5: **apenas** `control_lab/fuzzy/anfis.py`, `control_lab/fuzzy/inference.py`, `control_lab/fuzzy/fml.py` e `tests/unit/f5/test_anfis_fuzzy_multiio.py` foram modificados/criados. ZERO alterações em `contracts/`, `tests/oracles/`, `tests/unit/f1/`, `web/` ou outras frentes produtoras.

| Artefato F5 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/fuzzy/anfis.py` | `f3196e65b366ea643aed8ca4808d4a823cd5e6354f0f804bdc84ef73cd570b4c` | Extensão de `fit_anfis` para `Y` multi-saída `(N, M_out)` com `output_names`, grade cartesiana heterogênea `n_mfs: int | Sequence[int]` (2..10, guarda `MAX_ANFIS_RULES = 512`), `mf_type: str | Sequence[str]` (`gaussian`/`bell`), resolução simultânea de consequentes por QR/SVD (`_solve_consequents_qr_svd`, zero `linalg.inv`), retropropagação multi-saída para premissas compartilhadas, métricas agregadas e por saída (`rmse_*_per_output`, `fit_*_per_output`), preservação integral de `M=1` e marcação `is_dynamic_model=False` (`ADR-006`). |
| `control_lab/fuzzy/inference.py` | `857a6fddf0e7379d7e059175c11010f5d9321f45848cf55d81081f5d5596bc79` | Adição do parâmetro `output_name: str | None = None` em `evaluate_surface` com validação de eixos distintos e saída existente, retornando `outputs`, `output_name` e `Z` (fatia da saída selecionada) preservando retrocompatibilidade de `surfaces`, além de limpeza de import não utilizado e tipagem estática. |
| `control_lab/fuzzy/fml.py` | `4dd38555d50395210c58687679e7a91744f8288a7d075a8ef93cc1855d300a6f` | Limpeza de variáveis/imports não utilizados e guarda de tipo (`w_str is None`) em `import_fml`, mantendo conformidade estrita com IEEE 1855-2016 e `mypy` limpo. |
| `tests/unit/f5/test_anfis_fuzzy_multiio.py` | `25faa7460441adbaf1a46e94436b5d545c837552963a67b3ce6d4e791ad76a76` | Cobertura unitária para `fit_anfis` multi-saída (`2×2`, `3×2`), `n_mfs` e `mf_type` heterogêneos, guarda de explosão de regras (`> 512`), retrocompatibilidade `M=1`, `evaluate_surface` com `fixed_inputs` e `output_name`, e round-trip `export_fml`/`import_fml` para sistemas `N × M`. |

---

## 2. Verificações Independentes e Oráculos Executados pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de ownership** (`git status --short`, `git diff --stat`) | Apenas os 4 caminhos permitidos de F5 tocados (`anfis.py`, `inference.py`, `fml.py`, `tests/unit/f5/test_anfis_fuzzy_multiio.py`); ZERO alterações em `contracts/`, `tests/oracles/` ou outras frentes. | Ownership F5 (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Inspeção AST — Zero `linalg.inv` / `eval` / `exec`** | Scan AST independente em `anfis.py`, `inference.py` e `fml.py`: **0** ocorrências de `.inv()`, `from ... import inv`, `eval`, `exec` ou `compile` builtin. | `CL-DIR-001` Seção 5.1 / 13.7 (`zero inv`) | PASS |
| **Oráculo Independente — Gradientes por Diferenças Finitas (`2×2`, `gaussian` + `bell`)** | Confronto de `grad_c`, `grad_s` (`grad_a`) e `grad_b` contra diferenças finitas centrais (`eps=1e-6`) sobre $E = \frac{1}{2N}\sum_{n,k}(\hat{y}_{n,k}-y_{n,k})^2$ com consequentes fixos via QR (`rank=18`): `max_abs_err = 2.325e-12`, `max_rel_err = 2.325e-12`. | Consistência analítica do backward pass multi-saída | PASS |
| **Oráculo Independente — Recuperação Afim Exata `2×2` + `ADR-006`** | Alvo $y_1 = 2x_1 - 3x_2 + 1$, $y_2 = -0.5x_1 + 4x_2 - 2$ com `n_mfs=[2, 3]` e `mf_type=["gaussian", "bell"]`: `rmse_train = 1.863e-15`, `rmse_val = 1.852e-15` (`y1 = 2.032e-15`, `y2 = 1.652e-15`), erro em ponto não visto `8.882e-16 < 1e-10`; `is_dynamic_model == False` em `fuzzy_system` e `assumptions`. | `T-ANFIS-01` + `ADR-006` (`RMSE < 1e-10`) | PASS |
| **Oráculo Independente — Guarda de Explosão de Regras e Retrocompatibilidade `M=1`** | `n_mfs=[4, 4, 4, 4, 4]` (`1024 > 512`) retorna `status="failure"` com `code="VALIDATION_ERROR"`; `M=1` (`y` 1D) preserva `y_pred_train` como lista de `float` e atinge `rmse_val = 1.371e-15`. | Envelope de regras (`<= 512`) e compatibilidade `M=1` | PASS |
| **Oráculo Independente — `evaluate_surface` e Round-Trip FML `3×2`** | Sistema `3×2` (`n_mfs=[2, 2, 3]`, `["gaussian", "bell", "gaussian"]`, `rmse_val = 2.016e-15`): `evaluate_surface(..., input_axes=["e", "temp"], fixed_inputs={"de": 0.42}, output_name="u_heater")` coincide bit-a-bit com `evaluate()` em toda a grade (`max_diff = 0.000e+00`), rejeita `output_name` inexistente (`VALIDATION_ERROR`); `export_fml` (`16048` bytes) + `import_fml` preserva avaliação nos 15 pontos de teste com `max_rt_diff = 0.000e+00`. | `T-FZ-01`, `T-FZ-02` e IEEE 1855-2016 FML | PASS |
| **Execução `acceptance_cmd`** | `pytest tests/unit/f5/ -q`: **153 passed in 13.12s** (`exit 0`). | Aceite do WorkPackage | PASS |
| **Regressão Expandida (`F5` + `F1 RPC ANFIS` + `Oracles FML`)** | `pytest tests/unit/f5/ tests/unit/f1/test_rpc_anfis.py tests/oracles/test_fml_remediation_independent.py -q`: **176 passed in 13.50s** (`exit 0`, 0 failed, 0 skipped). | Sem regressões | PASS |
| **Qualidade Estática (`ruff` + `mypy`)** | `ruff check` nos 4 arquivos tocados: **0 erros** (nota: 7 erros pré-existentes em arquivos F5 não tocados por este WP: `symbolic_qlpv.py`, `tpmt.py`, `ts_bridge.py`, `test_fml_strict_import.py`). `mypy control_lab/fuzzy/anfis.py control_lab/fuzzy/inference.py control_lab/fuzzy/fml.py`: **Success: no issues found in 3 source files**. | Lint e tipagem estática | PASS |

---

## 3. Revisão Matemática e Algorítmica

- **Mínimos quadrados multi-saída sem `inv` (`_solve_consequents_qr_svd`)**: a matriz regressora $\Phi \in \mathbb{R}^{N \times R(n_{\text{in}}+1)}$ é fatorada uma única vez para todas as $M_{\text{out}}$ saídas via QR reduzida ($\Phi = QR$, resolvendo $R\Theta = Q^T Y$ por substituição triangular `np.linalg.solve`) quando $\Phi$ tem posto completo, com fallback automático por SVD truncada (`s_inv[:, None] * (U.T @ Y)`) sob deficiência de posto, emitindo `ANFIS_RANK_DEFICIENT_REGRESSOR`.
- **Retropropagação heterogênea multi-saída**: o gradiente exato de $E = \frac{1}{2N}\sum_{n=1}^{N}\sum_{k=1}^{M_{\text{out}}}(\hat{y}_{n,k} - y_{n,k})^2$ em relação às ativações $w_{n,r}$ é $\frac{\partial E}{\partial w_{n,r}} = \frac{1}{N \sum_q w_{n,q}} \sum_{k=1}^{M_{\text{out}}} (\hat{y}_{n,k} - y_{n,k})(f_{n,r,k} - \hat{y}_{n,k})$, propagado pela T-norma produto ($\frac{\partial w_{n,r}}{\partial \mu_{d,m}} = w_{n,r}/\mu_{d,m}$) para derivadas gaussianas ($c, \sigma$) e Generalized Bell ($a, b, c$) por entrada, validado por diferenças finitas com erro máximo `2.325e-12`.
- **Superfície `N × M` e FML IEEE 1855-2016**: `evaluate_surface` permite selecionar a fatia 2D fixando as demais entradas via `fixed_inputs` e escolhendo `output_name`, expondo `Z` e `outputs` de forma retrocompatível com `surfaces`; `export_fml`/`import_fml` serializam e restauram integralmente sistemas Takagi-Sugeno `3×2` com pertinências mistas.

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Referência | Evidência Auditada | Status |
|---|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `R-02` / `Result` / `test_rpc_anfis.py` | `fit_anfis`, `evaluate_surface`, `export_fml` e `import_fml` retornam `Result` padronizado e compatível com a camada RPC F1 (`tests/unit/f1/test_rpc_anfis.py` incluído nos **176 passed**), preservando retrocompatibilidade integral para `M=1` e expondo campos multi-saída (`output_names`, `n_outputs`, `mfs_per_input`, `mf_types_per_input`, `rmse_*_per_output`, `Z`). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `R-04` / `R-14` | `fit_anfis` e `evaluate_surface` retornam `Result` com `status` (`success`/`warning`/`failure`), `assumptions` (`is_dynamic_model=False`, `consequent_solver`), `diagnostics` (`regressor_rank`, `condition_number`, `n_rules`, `n_inputs`, `n_outputs`, `overfitting_flag`), `provenance` e `error` tipado (`VALIDATION_ERROR`, `DIMENSION_MISMATCH`) em entradas inválidas ou explosão de regras. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `T-FZ-01`, `T-FZ-02`, `T-ANFIS-01` | `tests/unit/f5/test_anfis_fuzzy_multiio.py` valida recuperação exata de mapeamentos afins multi-saída (`RMSE < 1e-10`), heterogeneidade de `n_mfs`/`mf_type`, guarda `> 512` regras, fatias 2D de sistemas `3×2` e round-trip FML IEEE 1855-2016. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Seção 13.11 | F9 executou oráculos independentes: verificação de gradientes analíticos vs diferenças finitas centrais (`max_abs_err = 2.325e-12`), recuperação afim `2×2` (`rmse_val = 1.852e-15`, erro em ponto não visto `8.882e-16`), verificação cruzada de `evaluate_surface` contra `evaluate()` em toda a grade `3×2` (`max_diff = 0.000e+00`) e round-trip FML `3×2` (`max_rt_diff = 0.000e+00`). | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Seção 13.1 / 13.2 | `git status --short` e `git diff --stat` confirmam alterações restritas aos 4 arquivos permitidos de F5; ZERO modificações em `contracts/fixtures/`, `tests/oracles/` ou outras frentes. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | `R-27` | Implementação 100% Python + NumPy puro (`np.linalg.qr`, `np.linalg.svd`, `np.linalg.solve`, `np.einsum`), sem dependências nativas fora do runtime Pyodide `wasm32`. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `contracts/schemas/` | Nenhuma alteração em `contracts/schemas/` foi necessária; `FuzzySystem.to_dict()` e o envelope `Result` preservam a estrutura contratual vigente com extensão aditiva retrocompatível. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Apêndice E | Hashes SHA-256 dos 4 artefatos, métricas independentes de gradiente (`2.325e-12`), recuperação afim (`1.852e-15`), `evaluate_surface` (`0.000e+00`), round-trip FML (`0.000e+00`), `acceptance_cmd` (`153 passed`), regressão (`176 passed`), `ruff` (0 erros nos arquivos tocados) e `mypy` (`0 issues`) registrados neste parecer. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `CL-DIR-001` / `ADR-006` | `fit_anfis` mantém `is_dynamic_model=False` e `static_io_approximator=True` (`ADR-006`) e não altera nem expõe métodos experimentais (`control_lab/experimental/sdp_educational/` inalterado). | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `R-04` / `R-13` | Explosão combinatória de regras (`R > 512`), `n_mfs` fora de `2..10`, `mf_type`/`output_names` incompatíveis e `output_name` inexistente em `evaluate_surface` retornam erros tipados acionáveis; deficiência de posto e risco de overfitting emitem `WarningItem` explícitos (`ANFIS_RANK_DEFICIENT_REGRESSOR`, `ANFIS_OVERFITTING_RISK`). | CONFORME |

---

## 5. Parecer Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: f9-integration-qa
- **Commit SHA auditado**: 032ec55e017281feba82273e6fae3fd9b54baf1d
- **Data (UTC)**: 2026-11-27
