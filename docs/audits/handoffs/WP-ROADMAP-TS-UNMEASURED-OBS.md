# Parecer F9 — `WP-ROADMAP-TS-UNMEASURED-OBS`

- **WorkPackage:** `WP-ROADMAP-TS-UNMEASURED-OBS`
- **Frentes Auditadas:** `f5-fuzzy-ts`, `f6-optimization-lmi`, `f8-ui-charts`
- **Auditor Independente:** `f9-integration-qa`
- **Veredito F9**: accepted

---

## 1. Resumo Executivo

As entregas científicas e de compilação DSL v2.0 das frentes F5, F6 e F8 para observadores Takagi-Sugeno com premissas não mensuradas (DMVT direto nas não linearidades (x), h(x)$ e fatoração algébrica exata do gradiente) foram auditadas de forma independente pela F9 após a correção do overflow horizontal mobile em `web/app/styles.css` pela F8.

Todos os portões de verificação passaram integralmente:
- `npm --prefix web run typecheck` (0 erros)
- `node scripts/run_web_tests.mjs --scope all` (143/143 testes em 19 arquivos)
- `npm --prefix web run build` (`control_lab-1.0.0-py3-none-any.whl` + 42 assets locais verificados)
- `pytest tests/unit/f5/ tests/unit/f6/ tests/e2e/test_ux_refactor_cl_ux_dir_001.py -v` (138/138 passaram, incluindo todos os 10 ensaios E2E em Chromium + Pyodide Wasm e responsividade `1280x800` e `390x844` na Aba 6 com `#lmi-ts-unmeasured-panel` visível)
- `python3 scripts/verify_fixtures.py` (11 schemas JSON Draft 2020-12 + 7 golden fixtures verificados)
- `python3 scripts/project_governance.py`

*(Nota de auditoria E2E: durante a re-auditoria, a F9 corrigiu uma condição de corrida pré-existente no Passo 2 de `test_ux_phase4_lmi_dsl_direct_sdp_compiler_solve` em `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`, onde `wait_for_function` resolvia imediatamente com o texto do Passo 1 antes da conclusão do solve LTI customizado, além de ajustar o timeout do Passo 3 para `90000` ms.)*

---

## 2. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Isolamento de ownership (`allowed_paths`) | F5 (`control_lab/fuzzy/`, `tests/unit/f5/`), F6 (`control_lab/optimization/`, `tests/unit/f6/`), F8 (`web/features/views/`, `web/app/styles.css`, `tests/unit/f8/`); F9 apenas `tests/e2e/`, `docs/audits/handoffs/`, `PROJECT_STATE.json`. | CONFORME |
| 2 | Não-circularidade matemática & fixtures intactas | `ts_observer.py` e `ts_unmeasured_observer_lmi` aplicam DMVT / fatoração de gradiente diretamente sobre (x), h(x)$ e verificam autovalores de  - L_i(C_i + \Delta C_k)$ independentemente; `verify_fixtures.py` 11/11 schemas e 7/7 fixtures OK. | CONFORME |
| 3 | Saídas científicas `Result<T>` / `RpcResponse` | Validado em testes unitários F5/F6 e em Chromium + Pyodide Wasm reais (10/10 E2E) com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`. | CONFORME |
| 4 | Tolerâncias numéricas & zero `eval`/`new Function` | `grep -rnE 'eval\s*\(|new\s+Function'` retornou 0 ocorrências em F8; tolerâncias da Seção 3.5 preservadas e auditadas independentemente. | CONFORME |
| 5 | Invariantes de domínio e `typecheck` | `npm --prefix web run typecheck` retornou 0 erros; validação de dimensões $ e sintaxe DSL v2.0 verificadas. | CONFORME |
| 6 | Casos degenerados / mal-condicionados | Cobertos por `tests/unit/f5/test_ts_unmeasured_observer.py`, `tests/unit/f6/test_ts_unmeasured_observer_lmi.py`, `143/143` em `run_web_tests.mjs` e `10/10` E2E. | CONFORME |
| 7 | Zero `PyProxy` em `postMessage` & build produção | `npm --prefix web run build` (`control_lab-1.0.0-py3-none-any.whl` + 42 assets) e execução real em Pyodide Wasm Worker aprovados. | CONFORME |
| 8 | UI F8: `Fast-Preview`, WCAG 2.2 AA e responsividade | `test_ux_phase3_lmi_v2_system_char_and_forall_quantifiers` passou em Chromium (`scrollWidth <= 390` em `390x844` na Aba 6 com `#lmi-ts-unmeasured-panel` visível após correção CSS em `web/app/styles.css`). | CONFORME |
| 9 | F6: Certificado 5D independente (ADR-010) | Certificado 5D (`validated_dual`/`feasible`) + recuperação de `L[1]`, `L[2]` e `K[1]`, `K[2]` validados em `#lmi-certificate-panel` e `#lmi-recovered-gain`. | CONFORME |
| 10 | Todos os testes unitários e E2E sem skips | `143/143` (`web --scope all`), `138/138` (`pytest F5 + F6 + E2E Chromium`), `verify_fixtures.py` e `project_governance.py` aprovados com 0 falhas e 0 skips. | CONFORME |

---

## 3. Hashes SHA-256 dos Artefatos Auditados

| Arquivo | SHA-256 |
|---------|---------|
| `control_lab/fuzzy/__init__.py` | `0213337fcfc4cae8d7093ba42c753949204364020958e314354eff137352e3ca` |
| `control_lab/fuzzy/ts_observer.py` | `d8971e022ecc34541281e99d316efaae3f5d50b061b27697a6bde5209b1863b2` |
| `control_lab/optimization/__init__.py` | `8ebd8c275eb4fb6e927c652d2f28cc099f524e93a83d8da99ffd4cd07e03325b` |
| `control_lab/optimization/modeling/__init__.py` | `00e519943076e07c2fd3d2394687b530e3362f4d5cbd0e2f3cb5bfc425378977` |
| `control_lab/optimization/modeling/templates.py` | `1556332f5092b1c4ce81a4e463934834facd0bc9f67d891e3cd972da7376c4a0` |
| `web/app/styles.css` | `ddfa080c5c5dd6b0ffb53fb2c909b1e60a1b7a537b93903bdedf427e6bcbfeda` |
| `web/features/views/lmi_dsl_compiler.ts` | `d8ead6921b9d83b3a40b429c5de0cfafff502be8a858bf048bfc3f0b6ebe96c7` |
| `web/features/views/lmi_dsl_parser.ts` | `62740bc667307c6781989b974f5705a59faecb9865d67f843bc5128c94fb5109` |
| `web/features/views/lmi_view.ts` | `d167cad7f1b2a3b4bb47a6f6f71b32a6944966b194c548969a437b9797451317` |
| `tests/unit/f5/test_ts_unmeasured_observer.py` | `355d08bfba7e2a09a130781d9861899055a4dea2396cbce2aed081e570536799` |
| `tests/unit/f6/test_ts_unmeasured_observer_lmi.py` | `3e1f1a6de15541ab1d1af3d71220f2a214d3420ee6cdab609876892350c56cdd` |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | `54f8f21eb61e81606c7bad71b14e63548a54a3938ffddf03e95ee1128a252c06` |
| `tests/e2e/test_ux_refactor_cl_ux_dir_001.py` | `ed7a91e810aabf4572803871dde0ccd56dc2b2ca8ad30aaba4c37949fa9134fa` |

---

## 4. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit Base**: `0723cfc2e3d26084bac063467abf5db35f518c47`
- **Data (UTC)**: `2026-11-22T02:38:30Z`
