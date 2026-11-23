# Handoff e Parecer F9 — `WP-PHASE9-01C-F8-PACKED-COO-COMPILER`

- **WorkPackage**: `WP-PHASE9-01C-F8-PACKED-COO-COMPILER`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **ADR / Referência**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-23T04:20:00Z`

---

## 1. Escopo Auditado e Inventário SHA-256 (`allowed_paths`)

Alterações estritamente isoladas em `web/features/` e `tests/unit/f8/`:

| Artefato F8 | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/features/views/lmi_dsl_compiler.ts` | `eeafac340f1870fecef2fe2e3fa6291d8887eac0053f0d192f76e308b7c3b80f` | Compilador LMI DSL empacota blocos esparsos diretamente em `F_k_packed` (`Int32Array` para `k_idx`/`rows`/`cols` e `Float64Array` para `vals`), eliminando explosão de objetos JSON no envio ao Worker sem uso de `eval`/`new Function`. |
| `web/features/views/lmi_view.ts` | `faa9c725ebd17436e1824592321d2056f42f35a61914d70cc5a1a330d184df98` | Materializa payload fresco a partir da fonte do problema (`prepareProblemSource` / `materializePayloadFromSource`) em `solveLmi()`, `verifyCertificate()` e `exportScript()`, evitando reutilização de `ArrayBuffer` já transferido (*detached*) entre Solve → Verify → Export CVXPY/YALMIP. |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | `d188aab14bb63703ffb8d75cd9ee34a15bcbcffd1513d2ef86a69be24eea0387` | Valida emissão `F_k_packed`, paridade numérica com compilação esparsa/densa, guarda estática zero `eval`/`new Function` e integração binária CPython. |
| `tests/unit/f8/views_mimo_fuzzy_lmi.test.ts` | `97d4ecae8e8b0339e85639a7929a299a834002e3e46af1b5131eddaf6cbf2ba1` | Atualiza asserções de `LmiView` para o fluxo Solve → Verify → Export com materialização limpa de `F_k_packed`. |
| `tests/unit/f8/cpython_binary_helper.mjs` / `.d.mts` | `32c5e2ccd448342b6ed05548e570e64b8304439f75316be0e081edc4beb7344e` / `0e2d468a2ea24b77cb320057dc5e72818a3ec38ce3cc6f077148887c4e8816b0` | Auxiliar de teste F8 para ponte binária de `F_k_packed` contra CPython nos testes de unidade web. |

---

## 2. Evidências de Verificação Independente (F9)

- **Ownership e Segurança**: alterações estritamente em `web/features/` e `tests/unit/f8/`; guarda estática auditada pela F9 confirma zero `eval(` e zero `new Function`.
- **`npm --prefix web run typecheck` e `npm --prefix web run build`**: PASS (`exit 0`, 55 arquivos TS, 42 assets verificados).
- **`node scripts/run_web_tests.mjs --scope all`**: **157 passed, 0 failed, 0 skipped** (`exit 0`).
- **Chromium + Pyodide Wasm + E2E real (`tests/wasm/test_real_runtime.py` + `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`)**: **19 passed, 0 failed, 0 skipped** (`exit 0`). Fluxo real na Aba 6 (`Resolver LMI` `121.19 ms` → `Auditar Certificado` `70.11 ms` → `Exportar CVXPY` sintaxe Python compilável) executado sem qualquer erro de `ArrayBuffer` destacado, com `activeProxies === 0` e zero alertas/erros de página.

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `lmi_dsl_compiler.ts` produz `F_k_packed` conforme contrato `ADR-015` consumido diretamente por F7 (`extractTensorsToBinaryBuffers`), F1 (`dispatch_rpc`) e F6 (`SDPBlock.from_dict`). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | Painel 5D (`#lmi-certificate-panel`), progresso de iterações, cancelamento e erros tipados preservados integralmente após Solve e Verify. | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Paridade exata de blocos compilados, guarda zero `eval`/`new Function` e ausência de erro de buffer destacado validados em `tests/unit/f8/` e E2E real. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Fluxo completo compilador DSL → Worker Pyodide → auditoria 5D → exportação CVXPY verificado em Chromium real (`tests/wasm/test_real_runtime.py` e `tests/e2e/test_ux_refactor_cl_ux_dir_001.py`). | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Apenas `web/features/views/` e `tests/unit/f8/` modificados; nenhum arquivo de `control_lab/`, `web/bridge/`, `contracts/fixtures/` ou `tests/oracles/` tocado pela F8. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Compilação e execução validadas em Node/CPython (`157 passed`) e em Chromium + Pyodide Wasm real (`19 passed`, `ui_solve_ms=121.19`, `ui_verify_ms=70.11`). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma alteração incompatível em `.ctrlab` ou schemas canônicos; persistência `.ctrlab` de LMIs confirmada em `test_ux_phase5_ctrlab_lmi_persistence`. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Hashes SHA-256, `157 passed` web, `19 passed` Chromium Wasm + E2E e tempos reais de UI Solve/Verify anexados. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Selos de maturidade, banners de exportação offline (`ADR-010`) e isolamento experimental mantidos intactos. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Detecção de termos bilineares (BMI), cancelamento pelo usuário e exportação offline CVXPY/YALMIP mantêm mensagens claras e determinísticas. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **Data (UTC)**: `2026-11-23T04:20:00Z`
- **Justificativa**: A F8 concluiu a emissão direta de `F_k_packed` (`Int32Array`/`Float64Array`) em `lmi_dsl_compiler.ts` e garantiu rematerialização segura de buffers em `lmi_view.ts`, permitindo o fluxo real `Resolver LMI → Auditar Certificado → Exportar CVXPY` em Chromium + Pyodide sem qualquer erro de `ArrayBuffer` destacado e com 100% de aprovação nos `157` testes web e `19` testes Wasm/E2E.
