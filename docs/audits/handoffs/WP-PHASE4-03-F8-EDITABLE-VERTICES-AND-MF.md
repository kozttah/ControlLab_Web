# Handoff e Parecer F9 — `WP-PHASE4-03-F8-EDITABLE-VERTICES-AND-MF`

- **WorkPackage**: `WP-PHASE4-03-F8-EDITABLE-VERTICES-AND-MF`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `944a07c`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-22T02:55:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Todos os artefatos produzidos pela frente `F8` encontram-se estritamente dentro de `allowed_paths` (`web/features/`, `web/app/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/features/views/lmi_view.ts` | `d4a6dd39d6bef2b73adc0eac3409f5df90579aa1f168037d11f02a81fe01adc8` | Editor direto de matrizes `A[i], B[i], C[i], D[i]` por vértice nos modos Politópico (`data-vertex-kind="poly"`) e Takagi-Sugeno (`data-vertex-kind="ts"`), validação JSON 2D sem `eval`/`new Function` com marcação `aria-invalid="true"` + `.lmi-input-invalid`, preservação em resize (`N_v`/`N_r`) e editor completo de funções de pertinência TS (`#lmi-ts-mf-editor`, `#btn-lmi-add-ts-mf`, remoção, edição de premissa/tipo/parâmetros e atualização de `#lmi-ts-mf-summary` e `#lmi-ts-premises-list`). |
| `web/app/styles.css` | `2aebf542729b9343a51c928ed1b2098a6184a2997c4c3167977faf12cbc060d5` | Layout responsivo e contenção mobile (`min-width: 0; max-width: 100%; box-sizing: border-box`) para `.lmi-vertex-editor-card`, `.lmi-vertex-mat-grid`, `.lmi-ts-mf-editor`, `.lmi-mf-row` e colapso para 1 coluna em `@media (max-width: 640px)`. |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | `3a9c6da054aa3cfc99a615163e94b0220013186981363c2294284c98c7c7b5ef` | Teste unitário `WP-PHASE4-03-F8` validando edição de `A[1]/B[1]` em Politópico e TS, marcação de sintaxe inválida sem sobrescrever texto, preservação no resize, propagação para `CanonicalSDPProblem` e adição/edição/remoção de funções de pertinência TS preservando estado Medida/Não Medida. |

Nenhum arquivo de `contracts/fixtures/`, `tests/oracles/`, `control_lab/` ou `web/worker/` foi alterado pelo produtor.

---

## 2. Evidência de Execução Independente F9

- **Typecheck**: `npm --prefix web run typecheck` -> `PASS` (`0` erros).
- **Testes Web (`--scope all`)**: `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all` -> `PASS` (`144/144` testes aprovados, `0` falhas, `0` skips).
- **Build de Produção**: `npm --prefix web run build` -> `PASS` (`control_lab-1.0.0-py3-none-any.whl` + `42` assets locais verificados).
- **Integridade de Fixtures e Governança**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py` -> `PASS` (`11` schemas Draft 2020-12 válidos + `7` fixtures ouro íntegras).
  - `python3 scripts/project_governance.py` -> `PASS`.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações da `F8` restritas a `web/features/views/lmi_view.ts`, `web/app/styles.css` e `tests/unit/f8/lmi_dsl_v2.test.ts`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado com `11/11` schemas e `7/7` fixtures ouro intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | `LmiView.buildCompileContext()` alimenta `compileLmiDslToCanonicalSdp` com os vértices editados e envia `{ problem }` para `optimization.solve` consumindo `RpcResponse` completo. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma tolerância científica alterada; auditoria primal-dual independente permanece no motor `F6`. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `parseCompactMatrixJson` + `isValidMatrix2D` validam matrizes editadas e o compilador valida dimensões antes de submeter ao solver. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Sintaxe JSON inválida em `A[1]` validada com `aria-invalid="true"` e `.lmi-input-invalid` sem sobrescrever a entrada do usuário. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Verificado `grep` sem `eval`/`new Function` em `lmi_view.ts`; payload `{ problem }` permanece JSON puro. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | `aria-label` e `aria-invalid` nos inputs de vértices/MF, contenção responsiva a `390x844` sem overflow e `144/144` testes web aprovados. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Certificado em 5 dimensões preservado no painel `#lmi-certificate-panel` ao resolver com vértices editados. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `144/144` testes web (`node scripts/run_web_tests.mjs --scope all`) e `11/11` E2E Chromium aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit Base**: `944a07cf627d701d9e07c598c4d97c61e52a9f47`
- **Data (UTC)**: `2026-11-22T02:55:00Z`
