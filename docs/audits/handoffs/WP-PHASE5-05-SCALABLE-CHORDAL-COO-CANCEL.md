# Handoff e Parecer F9 — `WP-PHASE5-05-SCALABLE-CHORDAL-COO-CANCEL`

- **WorkPackage**: `WP-PHASE5-05-SCALABLE-CHORDAL-COO-CANCEL`
- **Frentes Produtoras**: `F6 (f6-optimization-lmi)` + `F8 (f8-ui-charts)` + `F9 (f9-integration-qa)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `a14c02179d1d6b546134242a2d4d1bd91b9f61e7`
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-22T17:28:54Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Todas as alterações ficaram estritamente restritas aos `allowed_paths` autorizados do pacote (`control_lab/optimization/`, `tests/unit/f6/`, `web/features/`, `web/app/`, `tests/unit/f8/`, `docs/architecture/`, `docs/audits/`, `PROJECT_STATE.json`), sem qualquer modificação em `contracts/fixtures/*`, `contracts/schemas/*` ou `tests/oracles/*`:

| Arquivo Auditado | Frente | SHA-256 | Papel no Pacote |
|---|---|---|---|
| `control_lab/optimization/modeling/canonical.py` | F6 | `99c75344bc5640c6ded95ee37fc8c70e2b7057b6eb5047916c4c241d703ff257` | Suporte a transporte esparso COO `F_k_sparse` em `SDPBlock.from_dict` com validação rigorosa (limites, finitude, inteiros não-booleanos, simetrização `0.5*(M+M.T)`) mantendo 100% de retrocompatibilidade com `F_k` denso. |
| `control_lab/optimization/backends/native_core.py` | F6 | `c4d3184297372990fcda6f3ee09b65627afa191c78c029802547a759864be08b` | Decomposição de blocos PSD por componentes conexas de esparsidade agregada (`_decompose_sparse_psd_blocks`) com remontagem exata de duais (`reassemble_duals`) e equilibração de Ruiz multi-varredura com recorte `[1e-4, 1e4]` (`_ruiz_equilibrate_blocks`) com desescalonamento exato primal/dual antes da auditoria independente. |
| `control_lab/optimization/backends/native.py` | F6 | `c38f6584e5fd5e2fc33004d718bd24c4b2f5f408ecd1107bf0738c1feb122109` | Atualização do `BROWSER_ENVELOPE` em duas faixas: `fast_max_variables=448`, `max_variables=1024`, `max_block_dimension=64`, `max_cone_entries=65536`. |
| `tests/unit/f6/test_scalable_native_sdp.py` | F6 | `9b4d1f3a233fcf56c15864db14335dfa7cbfdd7311e4435b9adab531eac30b62` | Novos testes unitários: equivalência e validação `F_k_sparse` COO, decomposição 24×24 em 4 subblocos 6×6 (comparada com Clarabel) e equilibração de Ruiz em LMI rígida `1e-4..1e4` (`validated_dual`). |
| `tests/unit/f6/test_native_sdp_and_exports.py` | F6 | `a3374ed8aec31fe5a275306217c13c057655ac08251201ea350bfe5feba7301c` | Atualização dos testes do envelope de navegador para o modelo de duas faixas (`fast_max_variables=448` / `max_variables=1024`). |
| `web/features/views/lmi_dsl_compiler.ts` | F8 | `c4f9d12ed417f3cb526fb15f757ce03877517efb49a95c7219f304a992528e9c` | Emissão de blocos em formato esparso COO (`F_k_sparse` + `dim` + `F0`) pelo compilador direto DSL v2.0. |
| `web/features/views/lmi_view.ts` | F8 | `65efba7bbb2a0aadd35d8d18875ebbc8bee768fb92474679ecd6d7e6309571eb` | Botão **Cancelar** (`#btn-lmi-cancel-solve`) conectado a `client.cancel(reqId, { reason: "user_cancelled_lmi" })`, timeout de 5 min (`300_000 ms`) para `optimization.solve` e banners diferenciados para faixa estendida (`> 448` até `1024`) e limite rígido (`> 1024`). |
| `web/app/styles.css` | F8 | `57ca2cf982fa1599dfb16213b493110cb99b9392b3ae78026a0042b2c8d8a28a` | Estilos para `#btn-lmi-cancel-solve` e banners `.lmi-envelope-extended` / `.lmi-envelope-hard-limit`. |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | F8 | `35a87400764d3d2b66f2affc4ffacff8f70fd8d34605fe204dad7448de53fddc` | Cobertura unitária F8 para emissão `F_k_sparse` COO, botão Cancelar `#btn-lmi-cancel-solve`, `timeout_policy=300000ms` e faixas do `BROWSER_ENVELOPE`. |
| `docs/architecture/ADR-010-native-sdp-and-offline-exports.md` | F9 | `54087bb26ed7f8bbbdbd820df624ad7081b6e08404cc6efb6870bbd3273b911a` | Inclusão das referências Goulart & Chen (2024, Clarabel §2.4–§2.6) e Garstka, Cannon & Goulart (IFAC 2020), equilibração Ruiz, decomposição de esparsidade agregada, transporte COO `F_k_sparse` e `BROWSER_ENVELOPE` em duas faixas (`448`/`1024`). |
| `docs/audits/handoffs/WP-PHASE5-05-SCALABLE-CHORDAL-COO-CANCEL.md` | F9 | *(este relatório)* | Parecer formal independente F9 e checklist de 10 itens do Apêndice E. |
| `PROJECT_STATE.json` | F9 | *(atualizado no fechamento)* | Registro de aceite `ACCEPTED_BY_F9` para `WP-PHASE5-05-SCALABLE-CHORDAL-COO-CANCEL` (`93/93` aceitos). |

---

## 2. Evidência de Execução Independente dos Gates

### 2.1. Typecheck e Build Web (Rebuild do Wheel Pyodide)
```
npm --prefix web run typecheck
-> tsc -p tsconfig.json --noEmit: SUCESSO (código 0)

PATH="/home/antigravity/.venv/bin:$PATH" PYTHON=/home/antigravity/.venv/bin/python npm --prefix web run build
-> Successfully built control_lab-1.0.0-py3-none-any.whl
-> Verified integrity and inventory of 42 local assets.
```

### 2.2. Suíte Unitária F6 + Gate G-0B em Runtime Real Chromium/Pyodide Wasm + E2E CL-UX-DIR-001
```
PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f6/ tests/wasm/test_real_runtime.py tests/e2e/test_ux_refactor_cl_ux_dir_001.py -v
-> tests/unit/f6/: 76 passed (incluindo COO F_k_sparse, decomposição 24x24 4 subsistemas, Ruiz 1e-4..1e4 e escada T-SDP-A1..D2)
-> tests/wasm/test_real_runtime.py: 4 passed (CARE 12x3, unstabilizable RPC, G-0B native runtime + envelope 1024 + offline scripts)
-> tests/e2e/test_ux_refactor_cl_ux_dir_001.py: 13 passed (fluxos completos no Chromium real)
-> Total: 93 passed in 160.20s (0 failed, 0 skipped)
```

### 2.3. Suíte Web Completa (F7 + F8)
```
PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all
-> [typecheck] PASS (all, 54 arquivo(s) TS)
-> 149 passed, 0 failed, 0 skipped (20 arquivos de teste, incluindo WP-PHASE5-05-F8 Cancelar + timeout 300000ms)
```

### 2.4. Integridade de Fixtures Ouro e Governança
```
PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py
-> 11 schemas JSON Draft 2020-12 válidos; 7/7 fixtures ouro OK (SHA-256 + schema); 4 exemplos OK

python3 scripts/project_governance.py
-> {"accepted": 93, "corrective_packages": 24, "work_packages": 93}
```

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações estritamente contidas em `control_lab/optimization/`, `tests/unit/f6/`, `web/features/`, `web/app/`, `tests/unit/f8/`, `docs/architecture/`, `docs/audits/handoffs/` e `PROJECT_STATE.json`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | 7/7 fixtures ouro íntegras (SHA-256 + JSON Schema Draft 2020-12); `tests/oracles/` inalterado. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Validado em CPython (`tests/unit/f6/`, 76/76) e em Chromium Pyodide Wasm (`tests/wasm/test_real_runtime.py`, 4/4). | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Tolerâncias normativas preservadas; tanto a equilibração Ruiz (`[1e-4, 1e4]`) quanto a decomposição de blocos PSD desescalam/remontam primal e dual antes da auditoria independente no problema original, atingindo `validated_dual` com paridade frente ao Clarabel. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | `SDPBlock.from_dict` valida índices `(r, c)`, chaves `k`, finitude e `n_vars` com `ValidationError`/`DimensionMismatchError`; `native.py` aplica `BROWSER_ENVELOPE` (`max_variables=1024`) retornando `RESOURCE_LIMIT` acima do limite. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Testados: LMI rígida `1e-4..1e4` (Ruiz), entradas inválidas/NaN/OOB em `F_k_sparse`, bloco 24×24 decomposto em 4×6×6, planta não-estabilizável e problema acima de `1024` variáveis (`RESOURCE_LIMIT` no Wasm real). | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Confirmado em execução real do Web Worker Pyodide (`tests/wasm/test_real_runtime.py`, 4/4 passed) e suíte F7/F8 (149/149 passed). | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Suíte web completa (149/149 passed) + 13/13 E2E em Chromium confirmam botão `#btn-lmi-cancel-solve`, timeout `300_000 ms`, banners de faixa estendida/limite rígido e ausência de regressões de acessibilidade/R-23. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Separação das 5 dimensões preservada em `tests/unit/f6/` (76/76) e `tests/wasm/test_real_runtime.py` (4/4). | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | 93/93 pytest (F6 + Wasm real + E2E Chromium) + 149/149 web tests + `typecheck` + `build` + `verify_fixtures.py` + `project_governance.py` (`93/93`) aprovados com zero falhas e zero skips. | CONFORME |

---

## 4. Parecer F9 e Assinatura da Auditoria Independente

- **Parecer F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `a14c02179d1d6b546134242a2d4d1bd91b9f61e7`
- **Data (UTC)**: `2026-11-22T17:28:54Z`
- **WorkPackage**: `WP-PHASE5-05-SCALABLE-CHORDAL-COO-CANCEL`
- **Justificativa**: As evoluções coordenadas de F6 (equilibração de Ruiz multi-varredura `[1e-4, 1e4]` inspirada em Clarabel §2.4–§2.6, decomposição por componentes conexas de esparsidade agregada inspirada em Garstka/Cannon/Goulart IFAC 2020 com reconstrução dual exata, suporte a `F_k_sparse` COO retrocompatível e `BROWSER_ENVELOPE` em duas faixas `448`/`1024`), F8 (emissão `F_k_sparse` COO no compilador DSL, botão `#btn-lmi-cancel-solve` com cancelamento cooperativo, timeout de 5 min e banners de duas faixas) e F9 (atualização da ADR-010 e auditoria independente) foram validadas em CPython, Node, Pyodide Wasm real e E2E Chromium com 100% de aprovação (`93/93` pytest, `149/149` web tests, `93/93` WPs aceitos).
