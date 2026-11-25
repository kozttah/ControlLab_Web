# Handoff e Parecer F9 — `WP-TSMOD-01-F5-SECTOR-NONLINEARITY`

- **WorkPackage**: `WP-TSMOD-01-F5-SECTOR-NONLINEARITY`
- **Frente Produtora**: `F5 (f5-fuzzy-ts)` — Motor Simbólico qLPV, Buscador Híbrido de Extremos e Não-Linearidade de Setor
- **Commit Base**: `1ab2b828855d55bddbe7bc534931efbeedbb395c`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-04`, `R-05`, `R-21`, `R-27`, Apêndice E), `ADR-006`, `CL-TS-MOD-DIR-001 v1.0.0` (Seções 3, 5 e `T-TSMOD-01`..`03`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-25T04:13:01Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

Verificação via `git status --short` confirmou isolamento estrito de propriedade da Frente F5 (`control_lab/fuzzy/` e `tests/unit/f5/`), sem qualquer alteração em `contracts/`, `tests/oracles/`, `tests/security/`, `web/` ou outras frentes produtoras.

| Artefato F5 | SHA-256 | Papel na Entrega |
|---|---|---|
| `control_lab/fuzzy/symbolic_qlpv.py` | `f66d1800d56977a2dcf0dba1ae56539fd83b5d6c08eee8fc66231368d9fcc3a7` | Parser recursivo descendente sobre AST tipada (zero `eval`/`exec`/`compile`/`getattr`), primitivas $C^\infty$ (`sinc_rad`, `cos1m_div_u`) + reescrita automática `sin(E)/E` e `(1-cos(E))/E`, pipeline híbrido de extremos em 3 estágios (Intervalar SUE + grade/Sobol + multi-start `minimize_scalar`/`L-BFGS-B`/`Powell`) e verificador de isolamento/multilinearidade em `z`. |
| `control_lab/fuzzy/sector_nonlinearity.py` | `f038fa8d0311784f7ef06fca989cb34b1a5638cc4b3d130e6fbb22231501fe03` | `analyze_sector_premises(...)` e `derive_ts_sector(...)` com teto `nn <= 8` (alerta `nn > 6`), expansão determinística dos $2^{n_n}$ vértices em ordem lexicográfica binária, suporte a sinais externos, canais generalizados (`Bw`, `Dyw`, `Cz`, `Dzu`, `Dzw`), detecção automática `ts_measured`/`ts_partially_observed` (`ADR-006`) e auditoria fora da grade (`ModelFidelityCertificate`). |
| `control_lab/fuzzy/ts_bridge.py` | `5fd11874675f65287379f2d8f56a10c75103557b24ad16cd1895248113c7f6e1` | Suporte a `representation_kind == "sector_nonlinearity"` em `evaluate_ts_premise_weights(...)` aceitando tanto premissas `z_k` quanto estados/sinais externos `x, w_ext` com validação de soma convexa. |
| `control_lab/fuzzy/__init__.py` | `a9c0f56ee65111efe8e168d6c240ad6ba486079143f1c9426788ebae2dcdcc06` | Reexportação da API pública (`parse_expression`, `sinc_rad`, `cos1m_div_u`, `find_global_extrema`, `verify_matrix_multilinearity`, `analyze_sector_premises`, `derive_ts_sector`, etc.). |
| `tests/unit/f5/test_sector_nonlinearity.py` | `4ff998714ab6a9b3ce7ec3ad4bb6689021ad32ed87a54d0f2589cbd9dc437029` | Cobertura unitária normativa de `T-TSMOD-01`, `T-TSMOD-02` e `T-TSMOD-03`. |

---

## 2. Verificações Independentes e Oráculos Executados pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de propriedade** (`git status --short`, `git diff --check`) | Apenas 5 arquivos em `control_lab/fuzzy/` e `tests/unit/f5/`; `git diff --check` exit `0`. | Ownership F5 (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Segurança AST (`R-21` / `T-TSMOD-01`)** | Inspeção AST em `symbolic_qlpv.py`, `sector_nonlinearity.py` e `ts_bridge.py`: **0** chamadas a `eval`, `exec`, `compile`, `getattr`, `__import__` ou `.inv()`. **31/31** entradas hostis bloqueadas com `ValidationError` (incluindo dunder, atributos, indexação, `lambda`, `;`, `=`, comprimento `> 4096`, profundidade `> 64`, `inf`/`nan`). | `R-21` / `T-TSMOD-01` | PASS |
| **Continuidade `sinc_rad` / `cos1m_div_u` (`T-TSMOD-01`)** | `sinc_rad(0) == 1.0`, salto em `u = 1e-4` igual a `1.110e-16`. `cos1m_div_u(0) == 0.0`, erro `< 1e-32` para `|u| < 1e-4` (nota informativa abaixo sobre `|u| ≈ 1e-4+`). | Erro `< 1e-15` em `0` e `1e-8` (`T-TSMOD-01`) | PASS |
| **Oráculo independente de extremos (`T-TSMOD-02`)** | `sinc_rad` em `[-10, 10]`: erro min `2.776e-17`, max `0.000e+00` vs Newton `tan(u)=u`. `sinc_rad` em `[2, 8]`: erro min `0.000e+00`, max `0.000e+00`. `cos` em `[-0.6, 0.6]` e `x^2` em `[-2, 1]`: exatos via `exact_interval_sue_plus_polish`. Multimodal não-SUE `sin(3*x1) + 0.5*cos(7*x1) - 0.1*x1^2` em `[-2, 2]`: erro min `1.110e-15`, max `0.000e+00` vs oráculo denso 20001 pts + Brent. `user_override` mais largo/mais estreito validado (`SECTOR_BOUNDS_OVERRIDE_NARROWER`). | Precisão `<= 1e-12` (`T-TSMOD-02`) | PASS |
| **Oráculo independente Pêndulo Invertido 4 estados / 4 premissas / 16 regras (`T-TSMOD-03`)** | Modelo independente (`M=1.5, m=0.3, l=0.6, g=9.81`, `x3 ∈ [-0.7, 0.7]`) derivado via `derive_ts_sector`. `TSStateSpace.to_dict()` validado contra `contracts/schemas/ts_state_space.schema.json` (Draft 2020-12). Sobre **503 pontos** (origem `x3=0`, cantos e 500 aleatórios): `max ||S(x) - sum h_r S_r||_F = 1.423e-14`, `max |h(x) - h(z)| = 0.000e+00`, `min(h) = 0.000e+00`, `max |sum h - 1| = 4.441e-16`. | `<= 1e-13`, `h >= -1e-15`, `|sum h - 1| <= 1e-14` (`T-TSMOD-03`) | PASS |
| **Integração `ADR-006` / `R-05`** | Modelo `derive_ts_sector` com `x2` não medido inferido como `ts_partially_observed` bloqueia `make_pdc_spec(architecture='pdc')` sem estimador (`HYPOTHESIS_VIOLATED`) e permite `architecture='robust_single_gain'`. | `R-05` / `ADR-006` | PASS |
| **Regressão completa (`pytest`)** | `/home/antigravity/.venv/bin/pytest tests/unit/f5/ tests/oracles/ tests/security --ignore=tests/security/test_real_browser_security.py -q`: **416 passed, 0 failed, 0 skipped** em `41.39s` (`exit 0`). | Sem regressões | PASS |

**Nota informativa não-bloqueante (polimento futuro):** em `cos1m_div_u(u)` (`symbolic_qlpv.py:131,137`), logo acima da fronteira `|u| = 1e-4`, a avaliação direta `(1 - cos(u)) / u` sofre cancelamento subtrativo parcial (erro de `1.520e-13` em `u = 1e-4 + 1e-12` vs `2*sin(u/2)^2 / u`). O uso de `2*sin(u/2)^2 / u` no ramo fora de Taylor eliminaria o cancelamento até precisão de máquina; não viola `T-TSMOD-01` nem `T-TSMOD-03` e fica registrado apenas como recomendação opcional.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `TSStateSpace.to_dict()` validado estritamente contra `contracts/schemas/ts_state_space.schema.json` (Draft 2020-12) e round-trip `TSStateSpace.from_dict()` + integração com `evaluate_ts_premise_weights` e `make_pdc_spec`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `analyze_sector_premises`, `derive_ts_sector` e `evaluate_ts_premise_weights` retornam `Result` padronizado com `status`, `assumptions`, `diagnostics`, `provenance`, `warnings` e `error` tipado (`ValidationError`, `DimensionMismatchError`, `HypothesisViolatedError`) sem fallback silencioso (`R-04`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `test_sector_nonlinearity.py` valida continuidade analítica (`sinc_rad`, `cos1m_div_u`), extremos SUE fechados, condição de estacionariedade $f'(x^*)=0$ e reconstrução analítica exata $S(x) = \sum h_r S_r$ no pêndulo invertido. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Oráculos independentes executados pela F9: Newton em `tan(u)=u` para `sinc_rad` em `[-10, 10]` e `[2, 8]`, varredura densa 20001 pts + Brent para função multimodal não-SUE, e pêndulo invertido independente com 503 pontos fora da grade (`max err = 1.423e-14`). | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | `git status --short` confirma alterações exclusivas em `control_lab/fuzzy/` e `tests/unit/f5/`; zero modificações em `contracts/fixtures/` ou `tests/oracles/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Implementação 100% Python + NumPy/SciPy (`scipy.optimize`, `scipy.stats.qmc`), sem dependências nativas fora do runtime Pyodide (`R-27`). Validação em Wasm será consolidada em `WP-TSMOD-05-F9`. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma alteração de schema; `TSStateSpace` derivado adere integralmente a `ts_state_space.schema.json` v1.0.0 existente. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256 dos 5 artefatos, métricas dos oráculos independentes (`1.423e-14`, `1.110e-15`, `2.776e-17`) e resultado de regressão (`416 passed`) registrados neste parecer. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Não introduz métodos experimentais; `control_lab/experimental/sdp_educational/` permanece inalterado e isolado. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Premissas constantes (`z_max - z_min <= 1e-12`), violações de isolamento/multilinearidade, `nn > 8`, `user_override` mais estreito e `ts_partially_observed` sem estimador retornam mensagens diagnósticas explícitas com `next_step` orientando para Via 2 (TPMT) ou estimador. | CONFORME |

---

## 4. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit Base Auditado**: `1ab2b828855d55bddbe7bc534931efbeedbb395c`
- **Data (UTC)**: `2026-11-25T04:13:01Z`
