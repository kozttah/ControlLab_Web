# Handoff e Parecer F9 — `WP-PHASE4-01-F8-DSL-DIRECT-SDP-COMPILER`

- **WorkPackage**: `WP-PHASE4-01-F8-DSL-DIRECT-SDP-COMPILER`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `4b9cff3`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-22T02:02:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Todos os artefatos produzidos pela frente `F8` encontram-se estritamente dentro de `allowed_paths` (`web/features/`, `tests/unit/f8/`, `docs/architecture/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/features/views/lmi_dsl_compiler.ts` | `e566b5bfd5645185dbd180f7006d48c5b04c4d61fd6a5d9113c26b537cebb28c` | Compilador determinístico direto DSL v2.0 -> `CanonicalSDPProblem` JSON (`ExprEvaluator` + `AffineMatrix`, sem `eval`/`new Function`, simetrização `F0`/`F_k`, margem estrita `<`/`>` explícita, rejeição bilinear, `bmat` com `*`, `He`, `macro`, `forall i`, `forall i, j where j > i`). |
| `web/features/views/lmi_view.ts` | `96f4125e4bd40ea43e5d0aa70f9695df1b4727aa5c6f115f216e821d8c3514c3` | Integração do compilador direto em `buildRpcPayload()` enviando `{ problem }` diretamente para `optimization.solve` e recuperação de ganho `K = Y Q⁻¹`, `K[i] = Y[i] P[i]⁻¹` e variáveis escalares a partir de `result.variables`. |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | `efc380beb71edcb315e9ddc69a3874a9c4d9c874ea345d6128c3e52cce4c3eae` | Testes unitários e de integração CPython (`cpythonLoader`) validando ausência de `eval`/`new Function`, simetria de `F0`/`F_k`, compilação de LTI/politópico/TS PDC/H∞ BRL generalizado, rejeição bilinear e recuperação de `K[1], K[2]`. |
| `docs/architecture/ControlLab_Web_LMI_DSL_Design_Diretor_v1.0.md` | `7eaf1b85a6ef8d95dccf59a5ea00a929601307eca356b7fd3b2d7e5c5d0b6b5b` | Atualização do Design Diretor LMI/DSL v2.0 documentando o compilador direto `DSL -> CanonicalSDPProblem`. |

Nenhum arquivo de `contracts/fixtures/`, `tests/oracles/`, `control_lab/` ou `web/worker/` foi alterado pelo produtor.

---

## 2. Evidência de Execução Independente F9

- **Typecheck**: `npm --prefix web run typecheck` -> `PASS` (`0` erros).
- **Testes Web (`--scope all`)**: `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all` -> `PASS` (`142/142` testes aprovados em `19` arquivos, `0` falhas, `0` skips).
- **Build de Produção**: `npm --prefix web run build` -> `PASS` (`control_lab-1.0.0-py3-none-any.whl` + `42` assets locais verificados).
- **Integridade de Fixtures e Governança**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py` -> `PASS` (`11` schemas Draft 2020-12 válidos + `7` fixtures ouro íntegras).
  - `python3 scripts/project_governance.py` -> `PASS`.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações da `F8` restritas a `web/features/views/`, `tests/unit/f8/` e `docs/architecture/`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado com `11/11` schemas e `7/7` fixtures ouro intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | `LmiView` envia `{ problem }` para `optimization.solve` e consome `RpcResponse` completo com certificado 5D e `provenance`. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Compilador apenas constrói o problema SDP canônico com margem estrita explícita (`strictMargin = 1e-4` ou `param eps`); verificação numérica permanece no motor Python `F6`. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Incompatibilidades dimensionais, `inv()` em variável não-constante, divisão por variável e termos bilineares (`Y*Q`) lançam erro capturado e convertido em `ControlLabBridgeError("VALIDATION_ERROR", ...)`. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Rejeição bilinear testada tanto no parser quanto diretamente no avaliador do compilador (com `bilinearWarnings` limpo); casos LTI, politópico, TS PDC e H∞ BRL testados contra CPython real. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Payload `{ problem }` é JSON puro (`number[]` C-order `float64`), sem `PyProxy` ou execução dinâmica (`eval`/`new Function` ausentes). | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | `LmiView` preserva acessibilidade, painel de certificado, recuperação de `K` / `K[i]` e suíte `142/142` aprovada. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | `LmiView` exibe as 5 dimensões independentes no painel `#lmi-certificate-panel` a partir de `optimization.solve`. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `142/142` testes web (`node scripts/run_web_tests.mjs --scope all`) e `9/9` E2E Chromium aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit Base**: `4b9cff337fc87b54dab1ef65576e75ebe027e0d3`
- **Commit SHA auditado**: `4b9cff337fc87b54dab1ef65576e75ebe027e0d3`
- **Data (UTC)**: `2026-11-22T02:02:00Z`
