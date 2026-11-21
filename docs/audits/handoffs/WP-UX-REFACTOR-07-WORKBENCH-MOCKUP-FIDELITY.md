# Handoff e Parecer F9 — `WP-UX-REFACTOR-07-WORKBENCH-MOCKUP-FIDELITY`

- **WorkPackage**: `WP-UX-REFACTOR-07-WORKBENCH-MOCKUP-FIDELITY`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `fb638acca0044e53a1e7b6e7d25c048a49e79ba5`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-21T14:39:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações da frente produtora `F8` ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/app/main.ts` | `2039c11803ca157cd4fc389aad487e67fcb049243510e3c9cdf2e1b9895f576b` | Adição dos atalhos globais de projeto na Topbar (`#btn-header-open-ctrlab`, `#btn-header-export-ctrlab` e `#btn-header-export-pvm`) visíveis em todas as 6 abas, sincronizados com o bloqueio de exportação `R-23` (`exportGuard.allowed` / `shell.canExportPvm()`) e encaminhamento de clique sem duplicar os IDs `#ctrlab-file-input`, `#btn-export-ctrlab` e `#btn-export-pvm`. |
| `web/app/styles.css` | `82a89a2ba1ec9553ce40b5aa821743f8e744f6f0f3793bc8bf3a60d55b4e1a01` | Refinamento de densidade e grades de bancada em 2 colunas no desktop (`>= 960px` / `>= 1024px`) para `.siso-charts-grid`, `.mimo-workbench-grid`, `.fuzzy-workbench-grid`, `.lmi-editor-split`, `.lmi-results-split`, `.lqr-matrix-grids`, `.id-params-grid` e `.siso-params-compact-grid`, com colapso responsivo para 1 coluna em mobile (`390×844`) sem overflow horizontal. |
| `web/features/views/fuzzy_view.ts` | `eac1068856810ddee4a87724955492627960dc982f8d10837482369bb6b2dbba` | Aplicação da classe `.fuzzy-workbench-grid` organizando lado a lado o editor visual de funções de pertinência (`.fuzzy-mf-panel`) e o painel de superfície de controle (`.fuzzy-surface-panel`). |
| `web/features/views/identification_view.ts` | `0fc2cd411d14d6d7aee08a7c95c8504b2aa8c6e6b19eb9946c140876279c45c0` | Grade compacta `.id-params-grid` / `.id-param-field` para parâmetros ARX e Subespaços MOESP/N4SID com botões diretos de 1 clique `#btn-id-fit-arx`, `#btn-id-fit-subspace` e `#btn-id-validate-holdout` no card da Etapa 2. |
| `web/features/views/lmi_view.ts` | `bcd1b74c800920a4ee63ab6932948104858a3d7784e0b23c33e491be42a38a47` | Divisão em 2 colunas `.lmi-results-split` posicionando o Certificado de Auditoria Independente em 5 Dimensões (`#lmi-certificate-panel`) e o Espectro de Autovalores LMI (`#lmi-spectrum-chart-slot`) lado a lado abaixo de `.lmi-editor-split`. |
| `web/features/views/siso_view.ts` | `7285dbaaab2ca149e444139e210ddc38a1aaa7ca4ecf7a74a53a22c3a8d293ef` | Encapsulamento recolhível dos parâmetros avançados de grade, atraso Padé, Lugar das Raízes e degrau sob `<details id="siso-advanced-params-details" class="siso-advanced-details" open>` com grade compacta `.siso-params-compact-grid`, preservando todos os IDs e `data-action` filhos. |
| `web/features/views/statespace_view.ts` | `5a8c0fb37af0025be9b7efdb617e25728672b08cb11742e89e8b7f0803ac5a44` | Vinculação direta dos gatilhos `#btn-export-pvm` e `#btn-export-ctrlab` para suportar acionamento tanto na Aba 3 quanto via atalhos globais da Topbar, mantendo a grade compacta `.lqr-matrix-grids` e `.lqr-export-card`. |
| `tests/unit/f8/shell_dock_ux.test.ts` | `2cc88cacc9e16094f8a8450999cea6736562b8e1695d7d00b869e13e32d058e7` | Teste unitário verificando os botões globais da Topbar (`#btn-header-open-ctrlab`, `#btn-header-export-ctrlab`, `#btn-header-export-pvm`), bloqueio e desbloqueio `R-23`, unicidade de IDs e integridade dos containers `.lmi-results-split`, `.mimo-workbench-grid`, `.fuzzy-workbench-grid`, `.siso-charts-grid` e `#siso-advanced-params-details`. |

Nenhum arquivo em `contracts/fixtures/`, `contracts/schemas/`, `tests/oracles/` ou `control_lab/` foi alterado pela frente produtora.

---

## 2. Evidência de Execução Independente F9

- **Typecheck e Testes Web**:
  - `npm --prefix web run typecheck`: `PASS` (`46` arquivos TypeScript, `0` erros).
  - `PATH="/home/antigravity/.venv/bin:$PATH" node scripts/run_web_tests.mjs --scope all`: `PASS` (`122/122` testes aprovados em `14` arquivos, `0` falhas, `0` skips).
- **Build de Produção**:
  - `npm --prefix web run build`: `PASS` (wheel `control_lab-1.0.0-py3-none-any.whl` construída e `42` assets locais verificados).
- **Suíte E2E em Navegador Real (Playwright Chromium contra `web/dist`)**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/e2e/test_ux_refactor_cl_ux_dir_001.py tests/e2e/test_gatecd_interactions.py tests/e2e/test_id_siso_verticals.py -v`: `PASS` (`12/12` testes aprovados), comprovando a visibilidade dos botões globais da Topbar (`#btn-header-open-ctrlab`, `#btn-header-export-ctrlab`, `#btn-header-export-pvm`) em todas as 6 abas, o bloqueio `R-23` antes do commit LQR e habilitação após commit, a presença de `#siso-advanced-params-details` e renderização 2×2 de `.siso-charts-grid`, o alinhamento lado a lado em 2 colunas de `.mimo-workbench-grid`, `.fuzzy-workbench-grid`, `.lmi-editor-split` e `.lmi-results-split` em `1280×800`, e zero overflow horizontal em `1280×800` e `390×844`.
- **Integridade de Fixtures Ouro e Schemas**:
  - `PATH="/home/antigravity/.venv/bin:$PATH" python3 scripts/verify_fixtures.py`: `PASS` (`11` schemas JSON Draft 2020-12 válidos e `7` fixtures ouro íntegras).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Alterações da F8 restritas exclusivamente a `web/app/main.ts`, `web/app/styles.css`, `web/features/views/{fuzzy,identification,lmi,siso,statespace}_view.ts` e `tests/unit/f8/shell_dock_ux.test.ts`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | `python3 scripts/verify_fixtures.py` aprovado com `11/11` schemas e `7/7` fixtures ouro intactas. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Todas as chamadas das 6 bancadas consomem os envelopes `RpcResponse` v1.0 do motor Python sem suprimir diagnósticos, avisos ou proveniência. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Nenhuma rotina numérica ou tolerância foi modificada; as alterações são estritamente de layout, ergonomia de bancada e atalhos globais de projeto. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Invariantes de domínio e erros tipados (`ControlLabBridgeError`) permanecem integralmente verificados nas 6 bancadas. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Cobertos pelos `122` testes unitários web e pela suíte E2E Playwright (`12/12`, incluindo rejeição MIMO na bancada SISO, detecção bilinear BMI e bloqueio `R-23` em preview). | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Suíte completa `F7+F8` (`122/122`) e suíte E2E em navegador real aprovadas sem vazamento de `PyProxy`. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Comprovado em Chromium real (`web/dist`): os botões globais `#btn-header-export-ctrlab` e `#btn-header-export-pvm` permanecem desabilitados (`disabled` + `aria-disabled="true"`) antes da confirmação e durante `Fast-Preview`, habilitando-se apenas após commit confirmado (`R-23`), com alvos `>= 44px` e zero overflow em `1280×800` e `390×844`. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | `LmiView` preserva as 5 dimensões independentes do certificado ADR-010 em `#lmi-certificate-panel` posicionado lado a lado com `#lmi-spectrum-chart-slot` em `.lmi-results-split`. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | `122/122` testes unitários web (`--scope all`) e `12/12` testes E2E Playwright (`test_ux_refactor_cl_ux_dir_001.py`, `test_gatecd_interactions.py`, `test_id_siso_verticals.py`) aprovados com `0` falhas e `0` skips. | CONFORME |

---

## 4. Notas de Auditoria

- A verificação em navegador real comprovou a fidelidade 1:1 das 6 bancadas ao Mockup `CL-UX-DIR-001`, incluindo os atalhos globais de projeto na Topbar (`.ctrlab`/`.pvm`) protegidos por `R-23`, o recolhimento de parâmetros avançados SISO em `#siso-advanced-params-details` com grade 2×2 `.siso-charts-grid`, e os layouts de 2 colunas lado a lado em `.mimo-workbench-grid`, `.fuzzy-workbench-grid`, `.lmi-editor-split` e `.lmi-results-split`.

---

## 5. Assinatura da Auditoria Independente F9

- **Veredito F9**: accepted
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `fb638acca0044e53a1e7b6e7d25c048a49e79ba5`
- **Data (UTC)**: `2026-11-21T14:39:00Z`
