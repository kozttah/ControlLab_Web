# Handoff e Parecer F9 — `WP-V1-F8-SISO-VERTICAL`

- **WorkPackage**: `WP-V1-F8-SISO-VERTICAL`
- **Frente Produtora**: `F8 (f8-ui-charts)`
- **Frente Revisora**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `f09e3cbadf4588f813abc0dc37bff20c324695a2`
- **Veredito F9**: accepted
- **Data da Auditoria (UTC)**: `2026-11-19T02:15:00Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

As modificações da frente produtora `F8` ficaram estritamente restritas aos caminhos autorizados em `allowed_paths` (`web/app/`, `web/features/`, `web/charts/`, `tests/unit/f8/`):

| Arquivo Auditado | SHA-256 | Papel no Pacote |
|---|---|---|
| `web/features/siso_workspace.ts` | `1f2e0e046dcf3b163cb5bae72a2b15c65c45c4c9986f7a4ca46681b12a679ce3` | Controlador de domínio `SisoWorkspace`: resolução e validação estrita de plantas SISO (`TransferFunction` e `StateSpace`), orquestração RPC de `frequency.eval_response`, `frequency.bode`, `frequency.stability_margins`, `frequency.root_locus`, `frequency.step_response`, oráculo analítico de 1ª ordem (`analyticalFirstOrder`), formatação de marcadores de travessia, overlays de 2ª ordem rotulados como heurísticos e integração ao `ProjectTabsController`. |
| `web/charts/scientific_chart.ts` | `7db6f0bbdfdd2119e5a89cd5d4416c281f7e849a362f37ac3451a10ff05b57bb` | Modelos e renderizadores SVG determinísticos para resposta em frequência e controle linear: `BodeChartModel` e `renderBodeSvg` (módulos de magnitude e fase sincronizados com grid logarítmico), `NyquistChartModel` e `renderNyquistSvg` (plano complexo com ponto crítico -1+j0 e contorno fechado), `RootLocusChartModel` e `renderRootLocusSvg` (trajetória de polos, assíntotas, pontos de dispersão e cruzamentos imaginários), tabelas acessíveis WCAG 2.2 AA (`buildAccessibleChartTable`) e exportação CSV (`exportChartToCsv`). |
| `web/features/tool_catalog.ts` | `535f18092cf5a8d39129f5a5b1e019f8ac9eb8003f924a704fb2a8f076e5f240` | Catálogo declarativo com descritores da Aba 2 (`siso.bode_nyquist`, `siso.bode`, `siso.stability_margins`, `siso.root_locus`, `siso.step_response`) com parâmetros de grade (`w_min`, `w_max`, `n_points`, `delay`, `use_pade`, `pade_order`, `feedback_sign`, `k_max`, `damping_ratio`, `amplitude`, `t_final`). |
| `web/features/project_tabs.ts` | `913aeab864a9da7200f29d92226f926b6c01bac9314438c06156f99d4b6f8673` | Registro e controle de execução por ferramenta em abas, suportando flags de transição Fast-Preview vs Commit autoritativo (`recordExecution: false` em previews transitórios, `recordCommittedExecution` e `getLastExecution`). |
| `web/app/shell.ts` | `63198df732416d18422245b5fce6831758662b7a299cab2aaa8c42eb091115f4` | Instanciação e amarração de `SisoWorkspace` ao `ControlLabShell`, roteamento de eventos da Aba 2 (`siso_frequency`) e sincronização de plantas selecionadas em `frequencyPlant`. |
| `web/app/main.ts` | `47bdec4295ca04936b689d6474adc101267cfd355dc503c24f4b17e899d98836` | Montagem do painel `#siso-workspace-panel` na Aba 2, controles de faixa de frequência, atraso puro vs Padé, ganho de compensador e sinal de realimentação, painel de diagnósticos `#siso-diagnostics-panel`, slots de gráficos (`#siso-bode-chart-slot`, `#siso-nyquist-chart-slot`, `#siso-rl-chart-slot`, `#siso-time-chart-slot`), tabelas acessíveis equivalentes (WCAG 2.2 AA) e listeners interativos. |
| `tests/unit/f8/siso_vertical.test.ts` | `43836e6ad0f43ed6c8ed98d8f27e6375ba704de7410b13dfa3b772a447c0e118` | Suíte unitária e de integração normativa de F8 cobrindo T-FREQ-01, T-FREQ-02, T-UI-01, rejeição estrita de modelos MIMO sem canal SISO selecionado, atraso puro vs Padé explícito, isolamento entre Fast-Preview e Commit, e Lugar das Raízes com overlays heurísticos. |

Nenhum arquivo em `control_lab/frequency/` (F3), `contracts/fixtures/`, `contracts/schemas/` ou `tests/oracles/` foi alterado pelo produtor. O arquivo `contracts/fixtures/checksums.sha256` permanece estritamente íntegro e validado por hash SHA-256.

---

## 2. Verificação Independente dos Critérios do Pacote (`docs/audits/NEXT_QUEUE_2026-11-17.md`)

1. **T-FREQ-01: Planta analítica de 1ª ordem $G(s) = \frac{1}{s+1}$ com conferência de magnitude e fase**:
   - `SisoWorkspace.analyticalFirstOrder` avalia exatamente $|G(j\omega)| = \frac{1}{\sqrt{a^2 + \omega^2}}$ e $\angle G(j\omega) = -\text{atan2}(\omega, a)$ [graus].
   - Comparação contra a resposta numérica retornada por `frequency.eval_response` no motor Python real comprovou erro de magnitude $< 10^{-4}\text{ dB}$ e erro de fase $< 10^{-4}{^\circ}$ em toda a grade de frequências ($0.01$ a $100\text{ rad/s}$).
   - Estabilidade em malha fechada unitária verificada analiticamente ($1 + G(s) = 0 \implies s + 2 = 0 \implies \text{polo em } s = -2$) com confirmação de estabilidade e polo real negativo em `closed_loop_poles`.

2. **T-FREQ-02: Sistema com múltiplas frequências de cruzamento de ganho e aviso explícito**:
   - Planta de teste $G_1(s) = \frac{4.5(s^2 + 0.1s + 1)}{(s + 0.2)(s^2 + 0.05s + 9)}$ avaliada na faixa de $0.01$ a $50\text{ rad/s}$.
   - O motor detecta $\ge 2$ travessias de $0\text{ dB}$, definindo `has_multiple_crossings: true`, marcadores múltiplos `gain_crossover` em `BodeChartModel` e emitindo aviso explícito `MULTIPLE_CROSSOVER_FREQUENCIES` nos diagnósticos.

3. **Rejeição estrita de modelo MIMO sem seleção explícita de canal SISO**:
   - O método `assertStrictlySiso` inspeciona as dimensões da planta (`TransferFunction` com grade 2D ou `StateSpace` com matrizes $B$ e $C$).
   - Ao receber modelo MIMO ($2\times 2$), rejeita imediatamente com `ControlLabBridgeError` (`VALIDATION_ERROR`) com mensagem clara informando que a aba opera exclusivamente sobre canais SISO.

4. **Atraso puro vs Padé explícito**:
   - Por padrão (`use_pade: false`), atrasos de transporte $\tau > 0$ são avaliados de forma exata no domínio da frequência através do fator $e^{-j\omega\tau}$ (`delay_representation: "exact"`).
   - Aproximação de Padé (`delay_representation: "pade"`) é executada unicamente mediante seleção explícita (`use_pade: true`, ordem configurável), sem substituição silenciosa de atrasos puros.

5. **Fast-Preview transitório vs Commit autoritativo**:
   - Execuções em modo preview (`previewOnly: true`) marcam os gráficos como `preview` (`series_semantics: "preview"`).
   - A ferramenta não sobrescreve o snapshot autoritativo da aba em `lastExecutionByTool` durante o preview.
   - A exportação CSV é bloqueada com erro explícito enquanto houver apenas resultados preliminares pendentes de confirmação.

6. **Lugar das Raízes (Root Locus) e overlays heurísticos de 2ª ordem**:
   - Avaliação via RPC `frequency.root_locus` com suporte a realimentação negativa e positiva.
   - Extração de assíntotas, pontos de dispersão/breakaway e cruzamentos do eixo imaginário.
   - Overlays de amortecimento $\zeta$ e frequência natural $\omega_n$ rotulados estritamente como `heuristic` (`classification: "heuristic"`), vedando falsas garantias em ordens superiores a 2.

7. **Resposta ao degrau SISO e Acessibilidade WCAG 2.2 AA**:
   - Avaliação via RPC `frequency.step_response` extraindo métricas de regime permanente ($y_{ss}$, erro estacionário, tempo de acomodação $T_s$, tempo de subida $t_r$ e sobressinal $M_p$).
   - Todos os gráficos geram SVGs semânticos e tabelas equivalentes completas para leitores de tela em conformidade com WCAG 2.2 AA.

---

## 3. Evidência de Execução

- **Typecheck e Testes Unitários Web (`f8` e `all`)**:
  - `npm --prefix web run typecheck`: `PASS` (0 erros).
  - `node scripts/run_web_tests.mjs --scope f8`: `PASS` (`37/37` testes em 4 arquivos).
  - `node scripts/run_web_tests.mjs --scope all`: `PASS` (`100/100` testes em 9 arquivos).
- **Integridade de Fixtures e Schemas**:
  - `python scripts/verify_fixtures.py`: `PASS` (11 schemas JSON Draft 2020-12 válidos e 7 fixtures ouro íntegras).
  - `(cd contracts/fixtures && sha256sum -c checksums.sha256)`: `PASS` (todas as 7 fixtures conferidas).
- **Build de Produção e Suíte Wasm / E2E**:
  - `npm --prefix web run build`: `PASS` (Vite build completa, 42 assets locais inventariados).
  - `pytest -q tests/unit/f3 tests/wasm tests/e2e`: `PASS` (`38/38` testes aprovados em 292s).

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | Todos os arquivos alterados pertencem exclusivamente aos `allowed_paths` da frente no `CODEOWNERS`? | Modificações restritas a `web/app/`, `web/features/`, `web/charts/` e `tests/unit/f8/`. | CONFORME |
| 2 | Nenhum arquivo de `contracts/fixtures/*` ou `contracts/schemas/*` foi modificado pelo agente produtor? | Checksums conferidos com SHA-256 idêntico; zero modificações em fixtures ou tolerâncias de oráculos. | CONFORME |
| 3 | Todas as saídas científicas retornam `Result<T>` ou `RpcResponse` com `status`, `diagnostics`, `assumptions`, `provenance` e `warnings`? | Todas as chamadas de frequência usam envelopes canônicos RPC v1.0 com metadados completos preservados. | CONFORME |
| 4 | Tolerâncias numéricas seguem estritamente a Seção 3.5 ou estão justificadas no `provenance`? | Resposta analítica de 1ª ordem satisfaz tolerância rígida $< 10^{-4}\text{ dB}$ e $< 10^{-4}{^\circ}$. | CONFORME |
| 5 | Invariantes de domínio (`dt`, unidades, dimensões, convenção de sinal) são verificados e lançam erro tipado (Seção 7.4)? | Rejeição estrita de modelos MIMO com erro tipado `VALIDATION_ERROR`; suporte a domínios contínuo e discreto. | CONFORME |
| 6 | Casos degenerados ou mal-condicionados foram testados (incluindo tentativa que deve falhar/avisar)? | Testados: múltiplas travessias com aviso `MULTIPLE_CROSSOVER_FREQUENCIES` e rejeição de modelos MIMO 2x2. | CONFORME |
| 7 | Nenhum `PyProxy` cruza `postMessage` e todo buffer binário segue o protocolo de transferência da Seção 8.4? | Suíte F7 e testes de transporte executados com zero vazamentos e destruição garantida de proxies. | CONFORME |
| 8 | Se frente de UI (`F8`): estados `Fast-Preview` vs `Confirmado`, acessibilidade (WCAG 2.2 AA, teclado, `aria-live`) e bloqueio de exportação em preview estão cobertos? | Estados de preview isolados, exportação CSV bloqueada em preview, tabelas WCAG 2.2 AA e notificações em `aria-live`. | CONFORME |
| 9 | Se frente de Otimização (`F6`): `solver_status` está separado de `audit_feasibility`, `certificate_status`, `conditioning` e `controller_validity`? | Não aplicável diretamente à frente F8; sem violação das interfaces de otimização. | CONFORME |
| 10 | Todos os testes unitários da frente e testes normativos associados (`T-*`) passam localmente com zero skips indevidos? | T-FREQ-01, T-FREQ-02 e T-UI-01 passam localmente com zero falhas e zero skips em 100 testes totais da web suite. | CONFORME |

---

## 5. Assinatura da Auditoria Independente F9

- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `f09e3cbadf4588f813abc0dc37bff20c324695a2`
- **Data (UTC)**: `2026-11-19T02:15:00Z`
- **Parecer F9**: accepted
