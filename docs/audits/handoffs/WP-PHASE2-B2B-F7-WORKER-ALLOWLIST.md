# Handoff e Parecer F9 — `WP-PHASE2-B2B-F7-WORKER-ALLOWLIST`

- **WorkPackage**: `WP-PHASE2-B2B-F7-WORKER-ALLOWLIST`
- **Frente Produtora**: `F7 (f7-worker-bridge)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `8bfb994fab4a4e22a17531c714535dfb7bd93804`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-21T16:48:53Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações da frente produtora `F7` ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/worker/`, `web/bridge/`, `web/storage/`, `tests/unit/f7/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/worker/payload_references.ts` | `374229c5595123ba3e9be3424091db89be60f804ddd6d6c7d337f49746c4d144` | Inclusão explícita de `mimo.design_decoupler`, `mimo.simulate_closed_loop` e `mimo.design_hinf` na allowlist `PLANT_OPERATIONS` e resolução explícita de `decoupler_ref` e `controller_ref` em `mimo.simulate_closed_loop`. |
| `web/worker/MODEL_REFERENCES.md` | `87caad8adbfd10969e95fb2ee0aa96498375476491202cdb735e423c7fcb3722` | Documentação normativa atualizada da allowlist de referências para as operações `mimo.*` e referências opcionais `decoupler_ref`/`controller_ref`. |
| `tests/unit/f7/model_references.test.ts` | `e0bb1424eea21d1d9815ae9cb39a442b162b48b1fd38cb45251799b31f9a232b` | Testes unitários validando resolução de `plant_ref`/`model_ref`, `decoupler_ref`, `controller_ref` e rejeição fail-closed de ambiguidade. |

Nenhum arquivo em `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/` ou fora de `allowed_paths` foi alterado pela frente produtora.

---

## 2. Evidência de Execução Independente F9

- **Typecheck**:
  - `npm --prefix web run typecheck`: `PASS` (`49` arquivos TS, `0` erros).
- **Testes Unitários Web (F7 + F8)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: `PASS` (`131/131` testes aprovados em `17` arquivos, `0` falhas, `0` skips).
- **Integridade de Fixtures e Schemas**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py`: `PASS` (`11` schemas JSON Draft 2020-12 válidos e `7` fixtures ouro íntegras).
- **Validação E2E em Navegador Real (Chromium + Pyodide Wasm)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_ux_refactor_cl_ux_dir_001.py tests/e2e/test_gatecd_interactions.py tests/e2e/test_id_siso_verticals.py -v`: `PASS` (`14/14` testes aprovados, validando o fluxo real de `mimo.design_decoupler`, `mimo.simulate_closed_loop` e `mimo.design_hinf` no Worker Pyodide).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações da F7 restritas exclusivamente a `web/worker/payload_references.ts`, `web/worker/MODEL_REFERENCES.md` e `tests/unit/f7/model_references.test.ts`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado (`11/11` schemas e `7/7` fixtures ouro intactas). | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | A resolução de referências no Worker preserva integralmente o envelope `RpcResponse` v1.0 e não fabrica resultados científicos. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | O resolvedor de referências materializa DTOs canônicos sem mutar tolerâncias ou valores numéricos. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Referências inválidas, tipos incompatíveis (`kinds`) e payloads ambíguos (`decoupler` + `decoupler_ref`) falham fechados antes do despacho ao Pyodide. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | `tests/unit/f7/model_references.test.ts` testa explicitamente ambiguidade, referências ausentes/malformadas e incompatibilidade de tipo. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | `131/131` testes web aprovados, incluindo invariantes de `PyProxy` e transferência de buffers. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Não aplicável (frente produtora `F7`). | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável (frente produtora `F7`). | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `131/131` testes unitários web e `14/14` testes E2E em Chromium real aprovados com `0` skips (`T-BRG-01`). | CONFORME |

---

## 4. Notas de Auditoria

- Allowlist explícita em `web/worker/payload_references.ts` validada sem inferência por sufixo, resolvendo o bloqueio anterior observado no fluxo E2E de `mimo.design_decoupler` e `mimo.simulate_closed_loop`.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `8bfb994fab4a4e22a17531c714535dfb7bd93804`
- **Data (UTC)**: `2026-11-21T16:48:53Z`
