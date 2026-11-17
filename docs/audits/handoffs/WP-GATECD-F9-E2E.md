# Handoff F9 — WP-GATECD-F9-E2E

## 1. Cabeçalho

- WorkPackage ID: WP-GATECD-F9-E2E; frente: f9-integration-qa; requisitos: R-18, R-19, R-20, R-21, R-23, R-24.
- Módulos/caminhos permitidos: tests/e2e/, tests/wasm/, tests/security/, tests/performance/, tests/metamorphic/, tests/oracles/, scripts/, docs/, PROJECT_STATE.json.
- Contratos consumidos: F1/F9 RPC 1.0, StateSpace, StateFeedbackController/DynamicController, Experiment, PVM 1.0.0 e manifesto schema 1.
- Entradas: planta, x0, controlador/ganhos e limites de atuador; saídas: Result diagnosticado, DOM, ZIP e PVM passivos com proveniência.
- Hipótese matemática: dimensões compatíveis, realimentação explícita, interconexão bem posta; saturação é não linear e confrontada com ODE própria.
- Limite: domínio contínuo/estático/dinâmico e discreto de taxa única previamente coberto, não multirate/eventos externos.
- Testes de aceite: pytest && npm --prefix web test && python3 scripts/project_governance.py; fixtures: matrizes analíticas dos testes e fixtures ouro existentes intactas.
- Dependências aceitas: WP-GATECD-F8-UI-EXPORT; bloqueadores atuais deste escopo: nenhum.
- Evidência esperada: logs e bytes em docs/audits/gatecd/, hashes de fontes e parecer independente.
- Risco: corridas de UI, clipping/loop algébrico e divergência de consumidor externo mitigados por testes reais; maturidade pretendida: beta auditado nos Gates0B/C/D.

## 2. Implementação e resultados

A implementação respeita a divisão F1/F8/F9. Entrega produtora e comandos integrais: docs/audits/gatecd/PRODUCER_HANDOFF.md. Verificação independente e limites: docs/audits/gatecd/REVIEWER_FINDINGS.md.

## 3. Checklist do Apêndice E

| Item | Critério | Resposta | Evidência | Veredito |
| --- | --- | --- | --- | --- |
| 1 | API e consumidores | SIM | RPC 1.0 io.export_pvm/core.validate_interconnection e contratos canônicos preservados; testes F1, F8 e Worker real cobrem consumidores. | CONFORME |
| 2 | Status e proveniência | SIM | DIMENSION_MISMATCH visível sem destruir snapshot; preview transitório, tokens de revisão/configuração e proveniência/hash presentes; external_pathview_verified=False identifica cada novo arquivo. | CONFORME |
| 3 | Testes analíticos | SIM | Eliminação escalar ± com Dp/Dc e loop singular em F1; referência independente solve_ivp usa equações da planta, controlador e clipping, incluindo estados iniciais não nulos. | CONFORME |
| 4 | Confronto independente | SIM | F9 revisor distinto repetiu343 testes CPython, 53 web e 8 testes críticos browser; PathView 0.21/PathSim 0.31 processam os bytes realmente baixados e a UI oficial abre os quatro arquivos. | CONFORME |
| 5 | Ownership e ouro | SIM | Diff F1/F8 restrito aos CODEOWNERS; F9 altera scripts/testes/evidências. Nenhuma fixture ouro ou tolerância existente foi alterada. Teste de manifesto em tests/oracles é aditivo. | CONFORME |
| 6 | CPython e Pyodide | SIM | Produtor: pytest372/372, Firefox Wasm+E2E 19/19, Node 21/21. Revisor repete domínio crítico em Chromium e G0B em Firefox. Logs e versões estão em gatecd/. | CONFORME |
| 7 | Schemas | SIM | Sem mudança de versão pública: PVM 1.0.0, manifesto schema 1. Export options são parâmetros extensíveis no Experiment; arquivo legado sem campo usa defaults. F7 confirmou compatibilidade somente leitura. | CONFORME |
| 8 | Logs e fixtures | SIM | gatecd/ contém logs completos, fonte/hash, manifesto reproduzível e downloads .pvm/.ctrlab dos dois motores. Relatórios registram curvas u/y, estado final e topologia integral. | CONFORME |
| 9 | Maturidade | SIM | UI beta preservada. Manifesto integrity_only com release_approved=False; atestação de gate externa. ADR009/010 respeitadas sem alegar release estável. | CONFORME |
| 10 | Limitações | SIM | Dinâmico .pvm funciona sem LQR; .ctrlab persiste workspace LQR e opções, não workspace genérico dinâmico. Multirate/eventos externos continuam fora do domínio. MATLAB não executado; YALMIP validado estruturalmente. DEC-OPEN-03 mantém limite de hardware. | CONFORME |

## 4. Identidade, histórico e domínio

Base auditada 58d101d acrescida do diff identificado em docs/audits/gatecd/source-sha256.json. Manifesto da build: 57cb668376871e915f213707194e51c9d76504ab6a90cdfa493b01eaed77279d. Os bloqueios anteriores permanecem no histórico do ledger e nos relatórios históricos arquivados; este parecer substitui apenas a decisão de escopo agora comprovada.

## 5. Parecer independente

- Revisor independente: /root/f9_gate_review
- Produtores: /root/f1_gate_close, /root/f8_gate_close e /root/f9_gate_tests
- Commit SHA auditado (base):58d101d2d3296026af39c388f799e5577e38b027; hashes incrementais anexados.
- Data (UTC):2026-11-17
- Parecer F9: accepted
- Escopo de aceite: real_dom_two_browser_wasm_and_downloaded_pvm_external_interop
