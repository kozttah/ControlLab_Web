# Handoff e Parecer F9 — `WP-UX-REFACTOR-04-F9-BROWSER-AUDIT`

- **WorkPackage**: `WP-UX-REFACTOR-04-F9-BROWSER-AUDIT`
- **Frente Produtora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `9513a6df03cc657712638eec3dc6f8888b1c1b34`
- **Veredito F9**: accepted (com ressalva ambiental no Firefox, ver Seção 4)
- **Data da Auditoria (UTC)**: `2026-11-20T22:15:00Z`

---

## 1. Escopo

Nova suíte `tests/e2e/test_ux_refactor_cl_ux_dir_001.py` (SHA-256 `e8ab14c1c8a5981bcc4977a1beec56b43800bef99ff6eed3480287e132033f4f`, 3 testes) cobrindo a UX modular CL-UX-DIR-001 contra `web/dist`. Nenhum arquivo de `web/` foi alterado nesta entrega.

## 2. Evidências Executadas

- Chromium: `pytest tests/e2e/test_ux_refactor_cl_ux_dir_001.py` — `3 passed`.
- Chromium: `pytest tests/wasm/ tests/e2e/` — `34 passed` em `377.81s`.
- Firefox (`CONTROLLAB_BROWSER=firefox`): `pytest tests/wasm/ tests/e2e/` — `32 passed, 2 failed, 1 error` em `1823.78s`. Os 3 testes novos passaram. Falhas: `test_id_siso_verticals.py::test_tab_isolation_and_url_hash_persistence` e `test_sw_release_update.py::test_provisioned_client_updates_python_atomically_and_preserves_projects`.
- Governança: `pytest tests/integration/test_audit2_governance.py tests/integration/test_governance_and_ownership.py` — `20 passed`.

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Arquivos alterados dentro dos `allowed_paths` da frente? | Apenas `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`, este handoff e `PROJECT_STATE.json`. | CONFORME |
| 2 | Nenhum `contracts/fixtures/*` ou `contracts/schemas/*` modificado? | Nenhum arquivo de `contracts/` alterado nesta entrega. | CONFORME |
| 3 | Saídas científicas retornam envelopes completos? | N/A de escopo: suíte apenas observa a UI; nenhuma função científica alterada. | N/A |
| 4 | Tolerâncias numéricas conforme Seção 3.5? | Nenhuma tolerância ou oráculo alterado. | CONFORME |
| 5 | Invariantes de domínio verificados? | Sem alteração de código científico; E2E existentes de domínio seguem passando no Chromium. | CONFORME |
| 6 | Casos degenerados testados? | Matriz E2E/WASM completa passou no Chromium (34/34). | CONFORME |
| 7 | Nenhum PyProxy cruza postMessage? | Testes WASM/E2E passaram no Chromium sem requisições externas. | CONFORME |
| 8 | UI: Fast-Preview vs Confirmado, acessibilidade e bloqueio de exportação cobertos? | Novos testes E2E verificam datatips Bode/Nyquist/Root Locus, editor LMI e ausência de regressão; suíte existente cobre R-23. | CONFORME |
| 9 | Otimização: dimensões do certificado separadas? | Cobertas pelos testes E2E existentes de LMI; sem alteração em F6. | CONFORME |
| 10 | Testes da frente e normativos passam? | Chromium 34/34 e governança 20/20; Firefox com ressalva da Seção 4. | CONFORME |

---

## 4. Notas de Auditoria — Ressalva Firefox

As 2 falhas do Firefox são pré-existentes e ambientais: reproduzidas de forma idêntica no commit `52212db` (anterior a qualquer WP de refatoração UX), com `Page.goto` expirando (120 s) em `probe.html` (carregamento do Pyodide no Firefox deste ambiente). Não decorrem da refatoração CL-UX-DIR-001. Permanecem como débito a investigar fora deste WP.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `9513a6df03cc657712638eec3dc6f8888b1c1b34`
- **Data (UTC)**: `2026-11-20T22:15:00Z`
