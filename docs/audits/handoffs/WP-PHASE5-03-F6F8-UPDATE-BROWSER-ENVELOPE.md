# Handoff e Parecer F9 — `WP-PHASE5-03-F6F8-UPDATE-BROWSER-ENVELOPE`

- **WorkPackage**: `WP-PHASE5-03-F6F8-UPDATE-BROWSER-ENVELOPE`
- **Frentes Produtoras**: `F6 (f6-optimization-lmi)` + `F8 (f8-ui-charts)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `40c7ae54bd5dcfa72c2ee8e2b64e5380d65c8a4f`
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-22T16:23:08Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Todas as alterações produtoras ficaram estritamente restritas aos `allowed_paths` declarados no pacote (`control_lab/optimization/`, `tests/unit/f6/`, `web/features/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `control_lab/optimization/backends/native.py` | `90ffbc1292020d38175742a7fd8f97275c88ccfe05a61874c246cadfc0384ce6` | Atualização de `BROWSER_ENVELOPE["max_variables"]` de `256` para `448` (mantendo `max_block_dimension=64` e `max_cone_entries=32768`), calibrado pelo benchmark de estresse em Chromium Pyodide Wasm (`n=28`, 434 variáveis em `9.72s < 10s`, `validated_dual`). |
| `tests/unit/f6/test_native_sdp_and_exports.py` | `7d5957af787bd03a1dd53d04401a080b796a0863d829ed4367131a61072270fe` | Atualização de `test_browser_envelope_448_and_n24_stabilization` verificando `BROWSER_ENVELOPE` com `max_variables=448` e estabilização LTI `n=24` (`n_vars=324`, `256 < 324 <= 448`) com certificado `validated_dual`. |
| `web/features/views/lmi_view.ts` | `b7da4202144e35a9571db3b87d5216fcb8e3717011c0176a2e24e9f1b77abd48` | Sincronização de `BROWSER_ENVELOPE.max_variables = 448` na UI LMI, atualização do limiar `maxNForMode` (`isHinf ? 20 : 28`) e texto do banner de aviso `#lmi-envelope-banner` (`n ≤ 28 geral, n ≤ 20 H∞`). |
| `tests/unit/f8/lmi_dsl_v2.test.ts` | `9c133b69415e9ac909bbf8aafdbcd61544ac747c2536e5bfaf06e0f12d96fca9` | Atualização da suíte unitária F8 (`WP-PHASE3-S3-F8`) validando `n=24` oculto dentro do envelope, `n=30` (`> 28`) exibindo `max_variables=448` e `n=22` (`> 20`) exibindo aviso em síntese $\mathcal{H}_\infty$. |

Nenhum arquivo de `contracts/fixtures/`, `contracts/schemas/` ou `tests/oracles/` foi modificado.

---

## 2. Verificação Independente dos Critérios do Pacote

1. **Paridade de Envelope Backend (F6) ↔ UI (F8)**:
   - `control_lab/optimization/backends/native.py` e `web/features/views/lmi_view.ts` declaram o mesmo envelope `{"max_variables": 448, "max_block_dimension": 64, "max_cone_entries": 32768}`.
   - A UI alerta acima de `n > 28` (geral), `n > 20` ($\mathcal{H}_\infty$), `nVars > 448` ou `expandedBlockCount > 32`, preservando a recomendação explícita de exportação offline CVXPY/YALMIP.
2. **Qualidade e Regressão F6 + F8**:
   - `npm --prefix web run typecheck`: aprovado (código 0).
   - `npm --prefix web run build`: aprovado (wheel `control_lab-1.0.0-py3-none-any.whl` reconstruído com `native.py` atualizado e 42 ativos locais verificados).
   - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f6/ -v`: **73 passed, 0 failed, 0 skipped** (incluindo `test_browser_envelope_448_and_n24_stabilization` e toda a escada T-SDP-A1..D2).
   - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: **148 passed, 0 failed, 0 skipped** (20 arquivos de teste).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações produtoras restritas a `control_lab/optimization/backends/native.py`, `tests/unit/f6/test_native_sdp_and_exports.py`, `web/features/views/lmi_view.ts` e `tests/unit/f8/lmi_dsl_v2.test.ts`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `verify_fixtures.py` aprovado com 11 schemas Draft 2020-12 válidos e 7/7 fixtures ouro com SHA-256 íntegro. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | `solve()` em `native.py` e fluxos RPC em `lmi_view.ts` mantêm o contrato `Result<T>` / `RpcResponse` inalterado. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhum afrouxamento de tolerância; `n=24` (`324 vars`) e `n=28` (`434 vars`) atingem `certificate_status == "validated_dual"` na auditoria independente. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Problemas acima de `BROWSER_ENVELOPE` (`max_variables=448`) continuam lançando `RESOURCE_LIMIT` com recomendação de exportação offline. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Validados: `n=30` (`465 vars > 448`) e `n=22` em $\mathcal{H}_\infty$ acionam banner de aviso na UI; `max_variables + 1` falha com `RESOURCE_LIMIT` no backend e no runtime Wasm. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Validado em runtime Pyodide real via `tests/wasm/test_real_runtime.py` (4/4 passed). | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Suíte web completa (`148/148 passed`) confirma manutenção integral de R-23, acessibilidade WCAG 2.2 AA e semântica de envelope na Aba 6 (LMI). | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | As 5 dimensões permanecem estritamente separadas e auditadas independentemente em `test_native_sdp_and_exports.py` e no runtime Wasm. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | 73/73 F6 + 148/148 web tests + 4/4 Wasm real runtime aprovados com zero falhas e zero skips. | CONFORME |

---

## 4. Parecer F9 e Assinatura da Auditoria Independente

- **Parecer F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `40c7ae54bd5dcfa72c2ee8e2b64e5380d65c8a4f`
- **Data (UTC)**: `2026-11-22T16:23:08Z`
- **WorkPackage**: `WP-PHASE5-03-F6F8-UPDATE-BROWSER-ENVELOPE`
- **Justificativa**: A atualização coordenada de `BROWSER_ENVELOPE` para `max_variables=448` (`n <= 28` geral / `n <= 20` $\mathcal{H}_\infty$) entre F6 (`native.py`) e F8 (`lmi_view.ts`) está respaldada por benchmark real em Chromium Pyodide Wasm (`< 10s` até `n=28` com `validated_dual`) e passou integralmente nos testes unitários, typecheck, build de wheel e checklist de 10 itens do Apêndice E.
