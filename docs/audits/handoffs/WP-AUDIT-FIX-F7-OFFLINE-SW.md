# Dossiê de Handoff e Auditoria F9 — WP-AUDIT-FIX-F7-OFFLINE-SW

## 1. Cabeçalho da tarefa — Apêndice E

WP-AUDIT-FIX-F7-OFFLINE-SW, requisitos R-01/R-22, AUD-004, REM-10. Frente produtora F7, ownership web/bridge, web/worker, web/storage e tests/unit/f7. Auditor independente resume_audit, sem autoria de produto. Contratos consumidos RPC1.0, release-manifest schema1 e lock Pyodide0.27.5. Entradas são manifesto e recursos locais, saídas são cache versionado SHA256, relatório de integridade e capacidade observada. Hipótese matemática para prova CARE estabilizante e Lyapunov contínua escalar. Dependência BUILD-CI aceita. Aceite npm --prefix web run typecheck && node scripts/run_web_tests.mjs --scope f7. Normativo T-SEC-01. Risco de distribuição médio, maturidade beta. Release global permanece bloqueada pelo WP-AUDIT-FIX-F9-WASM-GATES.

## 2. Implementação, revisão e limites

O manifesto completo pós-build é validado por SHA256 e tamanho. O SW verifica stdlib, loaders, Wasm, wheel e fechamento transitivo NumPy/SciPy/OpenBLAS/micropip/packaging. Instala em cache único e promove um ponteiro somente após integridade. Mantém a release anterior em falha, isola escopos e aguarda clientes anteriores antes de ativar. Readiness lê novamente cada byte e recusa corrupção. Fetch falha fechado para recursos ausentes, corrompidos, telemetria e origens externas.

As provas reais encontraram falhas de instalação micropip0.8.0 e conversão Python None. O produtor passou a instalar wheel por loadPackage e normalizar None somente na fronteira PyProxy, preservando validação JS e destruição de proxies. Na primeira revisão desta retomada, Chromium confirmou recarga e cálculo mas a capacidade offline_ready era falsa, porque DedicatedWorkerNavigator não expõe serviceWorker. F9 emitiu changes_requested. A versão final verifica o SW pela janela no PyodideEngineClient após handshake científico, exclui workerFactory e exige URLs de worker/runtime/pacotes correspondentes à release. O teste original passou após essa correção.

Cada nova publicação deve alterar os bytes de service_worker.js para disparar o ciclo nativo install/waiting/activate. Alterar apenas o manifesto mantém a versão anterior íntegra no cliente existente. offline_ready é um atestado no instante de init, e checkOfflineReadiness fornece a verificação corrente. Após corrupção posterior, o snapshot já retornado pode continuar true, enquanto readiness retorna false e o SW recusa servir os bytes. O badge F8 conserva indicação prudente de offline não verificado. Firefox, outros dispositivos, E2E completo, CSP/security abrangente e PathView externo pertencem a WASM-GATES. Este aceite cobre o cenário Chromium descrito e não promove G-0A/B/C/D.

## 3. Checklist de Handoff de 10 Itens — Apêndice E

| # | Pergunta normativa | Resposta | Evidência | Auditoria F9 |
| :--- | :--- | :--- | :--- | :--- |
| **1** | API contratada F1/F9 disponível aos consumidores | SIM no escopo declarado | RPC real no Worker, handshake científico e aceite F7; sem schema alterado | CONFORME |
| **2** | Status, diagnósticos e proveniência | SIM no escopo declarado | Falha de hash/ausência informa readiness e bloqueia fetch503; resposta RPC tem versões e algoritmo | CONFORME |
| **3** | Teste analítico antes de otimização | SIM no escopo declarado | CARE integrador duplo com solução P=[[6,2],[2,3]], K=[2,3] e polos -2,-1 | CONFORME |
| **4** | Oráculo independente | SIM no escopo declarado | Chromium/Wasm executa wheel distribuída offline contra solução analítica; Lyapunov escalar X=1 | CONFORME |
| **5** | Ownership e expected íntegros | SIM no escopo declarado | Produto apenas F7, auditoria F9; sete gold e checksums byte idênticos HEAD, oráculos anteriores intactos | CONFORME |
| **6** | Domínio CPython/Pyodide | SIM no escopo declarado | 68 oráculos CPython aprovados; CARE e Lyapunov analíticos no Pyodide real; paridade ampla reservada WASM-GATES | CONFORME |
| **7** | Migração/versionamento de schema | SIM no escopo declarado | Schema anterior idêntico; manifesto consome versão1 existente | CONFORME |
| **8** | Logs e fixtures anexados | SIM no escopo declarado | Log integral anexo com hashes de patch e sete gold; benchmark de desempenho fora deste pacote | CONFORME |
| **9** | Maturidade experimental visível | SIM no escopo declarado | UI beta/gates pendentes preservados; badge offline conservador F8 | CONFORME |
| **10** | Limitações e bloqueios rastreados | SIM no escopo declarado | WASM-GATES e G-0A/B/C/D abertos; política de atualização e snapshot descritos abaixo | CONFORME |

## 4. Registro de Ambiente, SHA e Saída de Execução

Node24.22.1, Python3.12.14, pytest9.2.0, Chromium Headless153.0.8010.0 instalado pelo pacote @sparticuz/chromium153.0.0. Chromium desktop exige sockets indisponíveis neste ambiente; o headless padrão executou com Playwright. A distribuição científica executada usa Python3.12.7/Pyodide0.27.5/NumPy2.0.2/SciPy1.14.1.

Aceite exato aprovado com32 testes F7 e typecheck. Regressão completa Web50 testes aprovados. Oráculos CPython68 aprovados no comando do Maestro, anexado. Prova Wasm Node1 aprovada, usando somente recursos materializados a partir do cache reiniciado. Prova Chromium1 aprovada em /dist/, com32 assets verificados, cache HTTP limpo, servidor encerrado e conexão recusada, recarga atendida pelo Service Worker, offline_ready true após init e CARE K=[2,3], P=[6,2,2,3], polos[-2,-1]. Nenhuma requisição externa observada. Corrupção de CSS produz readiness false e HTTP503. Zero skips e zero falhas finais. Aviso anyio/pytest é depreciação.

Manifesto final SHA256 `af49b9196748c4a9438840dc46b3227a2143c8f4d63fc12bd5ef20c9bf7a0bde`. [Log integral](../../architecture/audit-logs/WP-AUDIT-FIX-F7-OFFLINE-SW.log). Sete fixtures ouro, checksums e tolerâncias anteriores preservados.

## 5. Parecer formal da Frente F9

- **Veredito F9:** `accepted` no escopo da operação offline verificada.
- **Revisor independente:** `f9-integration-qa`, agente `resume_audit`, distinto de `resume_producer`.
- **Commit SHA auditado:** base local `6003485d1a95721b8785667e8a8fcd69b82c74a2` mais patch SHA256 por arquivo no log; base remota `4ec8fc02173f8271ec84c7782e26517a28ea22a8`.
- **Data (UTC):** `2026-11-15`.
- **Escopo aprovado:** `chromium153_real_offline_reload_care_and_node_wasm_cache_only`.
- **Release:** NOT_APPROVED_FOR_STABLE_WEB_RELEASE; gates globais continuam sob auditoria do WP WASM-GATES.
- **Fechamento:** atualização de estado, orçamento e publicação reservados ao Maestro.
