# Handoff e Parecer F9 — `WP-TSMOD-06-F8-LMI-PDC-SIM-EXPORT`

- **WorkPackage**: `WP-TSMOD-06-F8-LMI-PDC-SIM-EXPORT`
- **Frente Produtora**: `F8 (f8-ui-charts)` — Registro em 1 clique de `PDCController`/`StateFeedbackController` no Workspace e exportação de script de simulação PathSim `0.31.0` (`ADR-013`) na Aba 7 (`LMIs`)
- **Commit Base**: `5d2afe839246c193132506d2e8fc662ec4b15826`
- **Referências Normativas**: `CL-DIR-001 v1.0.0` (`R-04`, `R-18`, `R-21`, Seção 13.1/13.2, Apêndice E), `ADR-006`, `ADR-013`, `CL-TS-MOD-DIR-001 v1.3.0` (`T-TSMOD-07`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-26T19:31:00Z`

---

## 1. Artefatos Auditados e Isolamento de Ownership

| Artefato F8 | SHA-256 | Papel na Entrega |
|---|---|---|
| `web/features/views/lmi_view.ts` | `05d1df10e66f4972c0336597fd1b249acfe191667359d18f6a91eab04c4b1eba` | Extração determinística dos ganhos recuperados (`K` para `StateSpace` LTI e `K[1]..K[N_r]` para `TSStateSpace`), detecção coerente de `feedback_sign`, botões `#btn-lmi-register-controller` e `#btn-lmi-export-pathsim` com invalidação automática se DSL ou sistema selecionado mudarem após a solução, e invocação passiva de `io.export_pathsim_script` (`code_executed=false`, bloqueio de `polytopic_uncertain` conforme `ADR-006`/`ADR-013`). |
| `tests/unit/f8/ts_modeling_view.test.ts` | `2177d8eb37e4368bbd411ab6de5b8e61aac244b665ab1e842fc126111c6acce8` | Teste ponta a ponta Aba 6 (derivação TS) -> Aba 7 (síntese PDC LMI) -> registro de `PDCController` no Workspace e exportação de script `PathSim 0.31.0` com verificação de estabilidade Hurwitz de malha fechada. |

---

## 2. Verificações Independentes Executadas pela F9

| Verificação Independente F9 | Resultado Medido | Critério Normativo | Status |
|---|---|---|---|
| **Isolamento de ownership** (`git status --short`) | Apenas `web/features/views/lmi_view.ts` e `tests/unit/f8/ts_modeling_view.test.ts` na camada F8. ZERO alterações em `control_lab/`, `contracts/` ou `tests/oracles/`. | Ownership F8 (`CL-DIR-001` Seção 13.1/13.2) | PASS |
| **Segurança estática (`R-21`)** | **0** ocorrências de `eval(` ou `new Function`; `io.export_pathsim_script` verifica `code_executed === false`. | `R-21` / `ADR-013` | PASS |
| **Typecheck TypeScript** (`npm --prefix web run typecheck`) | `exit 0`, 0 erros. | Aceite do WorkPackage | PASS |
| **Testes F8 + Build Web** (`node --test tests/unit/f8/ts_modeling_view.test.ts && npm --prefix web run build`) | `exit 0`; wheel e 42 ativos locais verificados (`Verified integrity and inventory of 42 local assets`). | Aceite do WorkPackage | PASS |

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Referência | Evidência Auditada | Status |
|---|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `controller.schema.json` / `rpc_response.schema.json` | `PDCController` e `StateFeedbackController` validados contra o motor Python real e `io.export_pathsim_script`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `R-04` | Proveniência explícita nos controladores registrados, invalidação pós-edição e bloqueio de `polytopic_uncertain` (`ADR-006`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | `T-TSMOD-07` | Estabilidade Hurwitz de $A_i - B_i K_i$ e presença de `ts_pdc_rhs`/`default_h_fn` verificadas em teste automatizado. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Seção 13.11 | Confronto direto contra o backend Python real (`control_lab.core.rpc.dispatch_rpc`) e autovalores de malha fechada. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Seção 13.1 / 13.2 | Edições restritas a `lmi_view.ts` e `ts_modeling_view.test.ts`; zero modificações em `contracts/` ou `tests/oracles/`. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | `R-27` | Bundle compilado e verificado em `npm --prefix web run build` com 42 ativos locais íntegros. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | `contracts/schemas/` | Nenhuma alteração de schema necessária. | N/A |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Apêndice E | Hashes SHA-256 e resultados de `typecheck`, testes F8 e `build` registrados neste handoff. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | `CL-DIR-001` | Classificação visual existente preservada integralmente. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | `ADR-006` / `ADR-013` | `polytopic_uncertain` permanece bloqueado para exportação PDC em `PathSim`, e botões desabilitam ao editar DSL/sistema após a solução. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: accepted
- **Revisor independente**: f9-integration-qa
- **Commit SHA auditado**: 5d2afe839246c193132506d2e8fc662ec4b15826
- **Data (UTC)**: 2026-11-26T19:31:00Z
