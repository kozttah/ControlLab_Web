# Handoff e Parecer F9 — `WP-PHASE2-D2-F1-RPC-MULTIFREQ`

- **WorkPackage**: `WP-PHASE2-D2-F1-RPC-MULTIFREQ`
- **Frente Produtora**: `F1 (f1-core-io)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `5bb4d7a07f45dbd24fd54cebccd45284e69e83e0`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-21T17:39:30Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As entregas da frente `F1` ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`control_lab/core/`, `tests/unit/f1/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `control_lab/core/rpc.py` | `e1fbd4857906cd873d64f2d2f86e5a648738501c69e87b409c2963a623e6d699` | Atualização do handler `mimo.design_decoupler` para validar e repassar `omega_targets`, `omega_target` (escalar ou lista), `realization_mode` (padrão `"auto"`) e `order` (`0..6`). |
| `tests/unit/f1/test_rpc_mimo_synthesis.py` | `147d877258d638c954cc8def1f1c4304e4f213b6cae61931aa13c2b7236995e3` | Testes unitários RPC para `mimo.design_decoupler` com `omega_targets` multi-frequência e seleção automática/explícita de ordem. |

Nenhum arquivo fora de `control_lab/core/` e `tests/unit/f1/` foi modificado pela frente `F1`.

---

## 2. Evidência de Execução Independente F9

- **Testes Unitários F1 + F3**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f1/ tests/unit/f3/ -v`: `PASS` (`144 passed in 11.16s`, `0` falhas, `0` skips).
- **Integridade de Contratos e Governança**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py`: `PASS` (`11` schemas e `7` golden fixtures).
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/integration/test_audit2_governance.py tests/integration/test_governance_and_ownership.py -v`: `PASS` (`20 passed in 10.57s`).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações da F1 restritas exclusivamente a `control_lab/core/rpc.py` e `tests/unit/f1/test_rpc_mimo_synthesis.py`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado com `11/11` schemas e `7/7` fixtures ouro intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | `mimo.design_decoupler` retorna `RpcResponse` v1.0 com `per_frequency`, `omega_targets`, `order_used`, `order_mode`, `provenance` e `warnings`. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma tolerância alterada; validação de entrada preserva precisão `float64`. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Rejeita booleanos, arrays vazios, valores não finitos e `order` fora de `0..6` com `ValidationError` tipado. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Coberto por `test_rpc_mimo_synthesis_validation_errors`, `test_rpc_mimo_design_decoupler_multifrequency` e `test_rpc_mimo_design_decoupler_multifrequency_auto_order`. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Conversão via `_to_python_native` e `_coerce_array` antes da execução e serialização validada em Chromium + Pyodide Wasm (`14/14` E2E). | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Não aplicável diretamente à F1 (coberto por `WP-PHASE2-D3-F8-MULTIFREQ-UI` e `WP-PHASE2-D4-F9-AUDIT`). | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável à F1. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `144/144` testes unitários F1+F3 aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Notas de Auditoria

- O despacho RPC aceita `omega_targets` e `omega_target` de forma coerente com os envelopes canônicos de `T-CORE-01`, mantendo retrocompatibilidade com chamadas existentes.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `5bb4d7a07f45dbd24fd54cebccd45284e69e83e0`
- **Data (UTC)**: `2026-11-21T17:39:30Z`
