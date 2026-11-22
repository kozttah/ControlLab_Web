# Handoff e Parecer F9 — `WP-PHASE5-01-F6-SCALABLE-NATIVE-SDP`

- **WorkPackage**: `WP-PHASE5-01-F6-SCALABLE-NATIVE-SDP`
- **Frente Produtora**: `F6 (f6-optimization-lmi)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `c9b45a5322744eee544931f2a1f492b2d9e39f3f`
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-22T16:01:33Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Todas as modificações da frente F6 ficaram estritamente restritas aos caminhos autorizados (`control_lab/optimization/`, `tests/unit/f6/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `control_lab/optimization/backends/native_core.py` | `54efb8bcb47ef825587730e26d9a0cbca379cfeb482ee90314708bf2775c7f60` | Núcleo primal-dual Nesterov–Todd/Mehrotra escalável: fatoração única de Schur (`_factor_symmetric_system` / `_solve_factored_symmetric`) com Jacobi + Cholesky regularizado + refino iterativo + condicionamento $O(m)$; congruência NT esparsa e montagem BLAS (Fujisawa et al., IEEE IPDPS 2014); equilibração por bloco com desescalonamento exato de duais (`_unscale_duals`, Yurtsever et al., SIMAX 2021 §7.1.1); suporte a `warm_start_x` interior com fallback para Fase I (Ding et al., arXiv:2312.11801). |
| `control_lab/optimization/backends/native.py` | `dccc2792d074acddcb887796ce735558ee3df59e1c34511414981ff49c2dfe9c` | Ampliação do `BROWSER_ENVELOPE` para 256 variáveis, dimensão máxima de bloco 64 e 32768 entradas cônicas; declaração `warm_start=True` em `capabilities()`. |
| `tests/unit/f6/test_scalable_native_sdp.py` | `29acdab45445a5a947ee6b968f20f2752a69aca06d9b1e19299b9bc2ac9f202c` | Suíte unitária validando paridade cruzada com `clarabel_direct` em $n=10, 16$, equilibração multi-escala ($10^{-3}$ a $10^{3}$), desescalonamento exato em objetivo não-nulo, warm-start em varredura de taxa de decaimento e $\mathcal{H}_\infty$/BRL + fallback + validação de erro, e acurácia de Schur/congruência esparsa. |

Nenhum arquivo de `contracts/fixtures/`, `contracts/schemas/` ou `tests/oracles/` foi modificado.

---

## 2. Verificação Independente dos Critérios do Pacote

1. **Zero `linalg.inv`**:
   - Verificado por inspeção estática (`grep -rn "linalg\.inv" control_lab/optimization/backends/native_core.py control_lab/optimization/backends/native.py`) e pelo teste arquitetural `test_architectural_invariants_no_linalg_inv_and_no_experimental_import`: zero chamadas a `inv()` (apenas comentários explicativos). Todas as resoluções usam `scipy.linalg.cho_factor`, `cho_solve`, `solve_triangular`, `svd` e `lstsq`.
2. **Fatoração Única de Schur por Iteração Mehrotra + Congruência NT Esparsa (Fujisawa et al., IEEE IPDPS 2014)**:
   - `_factor_symmetric_system(H)` fatora `H` uma única vez por iteração com escalonamento de Jacobi, Cholesky regularizado e estimativa de condicionamento $O(m)$ pela diagonal de $L$, reutilizada tanto no passo preditor (`dz_aff`) quanto no passo corretor (`dz`) via `_solve_factored_symmetric` com até 2 passos de refino iterativo.
   - `_InternalConeBlock.__post_init__` pré-computa `_sparse_terms` para matrizes `F_k` com $0 < \text{nnz} \le \min(0.25 n^2, n)$ ($n \ge 4$) e usa congruência esparsa seguida de montagem BLAS `cols.T @ cols`.
3. **Equilibração de Blocos e Desescalonamento Exato dos Duais (Yurtsever et al., SIMAX 2021, §7.1.1)**:
   - Cada bloco é escalonado por $s_b = \max(\|F_0\|_F, \max_k \|F_k\|_F)$ e todos os multiplicadores duais (tanto na rota de otimalidade Fase II quanto na rota de certificado de Farkas Fase I) passam por `_unscale_duals` ($Z_b = Z'_b / s_b$) antes da recuperação de multiplicadores de igualdade e da auditoria independente no problema original não escalonado.
4. **Warm-Start Interior com Fallback Seguro (Ding et al., arXiv:2312.11801)**:
   - `warm_start_x` validado em `NativeSolverConfig.from_options` e `solve_native_raw`: rejeita comprimento inválido ou valores não finitos com `VALIDATION_ERROR`, pula Fase I quando estritamente interior (resíduo de igualdade $\le 10^{-8}$ e autovalor/folga $> 10^{-8}$), recua graciosamente para Fase I quando infactível, e mantém `certificate_status == "validated_dual"` na auditoria independente.
5. **Paridade Cruzada com Clarabel e Suíte Completa F6**:
   - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f6/ -v`: **73 passed in 6.20s** (zero falhas, zero skips).
   - Paridade validada contra `clarabel_direct` em estabilização LTI ($n=10, 16$), plantas mal-condicionadas multi-escala e objetivos não-nulos com blocos de escalas diferindo em $10^6$.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações da F6 estritamente em `control_lab/optimization/backends/{native_core.py,native.py}` e `tests/unit/f6/test_scalable_native_sdp.py`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `verify_fixtures.py` e `sha256sum -c checksums.sha256` aprovados com 7/7 fixtures ouro íntegras e 11 schemas válidos. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | `solve()` e `recover_controller()` preservam integralmente o envelope `Result<T>` com `independent_audit=True`. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Auditoria independente valida `validated_dual` e `verified_under_assumptions` sem afrouxamento de tolerâncias; paridade com Clarabel em `1e-6`. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `warm_start_x` inválido lança `VALIDATION_ERROR`; problemas acima do `BROWSER_ENVELOPE` lançam `RESOURCE_LIMIT` recomendando exportação offline. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Testados: plantas multi-escala $10^{-3}\dots 10^3$, warm-start infactível com fallback, dimensões/NaN inválidos, problemas acima do envelope e escada A–D completa. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Validado em runtime Pyodide real via `tests/wasm/test_real_runtime.py` (4/4 passed). | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Não aplicável à frente F6; sem regressões em `node scripts/run_web_tests.mjs --scope all` (148/148 passed). | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | As 5 dimensões permanecem estritamente separadas e auditadas independentemente após o desescalonamento exato dos duais. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `pytest tests/unit/f6/ -v`: 73 passed, 0 failed, 0 skipped (incluindo T-SDP-A1..D2 e novos testes escaláveis). | CONFORME |

---

## 4. Parecer F9 e Assinatura da Auditoria Independente

- **Parecer F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `c9b45a5322744eee544931f2a1f492b2d9e39f3f`
- **Data (UTC)**: `2026-11-22T16:01:33Z`
- **WorkPackage**: `WP-PHASE5-01-F6-SCALABLE-NATIVE-SDP`
- **Justificativa**: O núcleo SDP nativo foi aprimorado com fatoração única de Schur por iteração Mehrotra, congruência NT esparsa, equilibração por bloco com desescalonamento exato e warm-start interior, mantendo zero uso de `linalg.inv`, separação estrita das cinco dimensões de status e paridade verificada contra Clarabel. Todos os 10 itens do Apêndice E foram verificados em conformidade.
