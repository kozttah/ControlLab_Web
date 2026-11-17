# Relatório Consolidado — Gates Fase 0 (CL-DIR-001)

Auditoria independente F9 em 2026-11-17, base 58d101d2d3296026af39c388f799e5577e38b027 e fontes incrementais em [source-sha256.json](gatecd/source-sha256.json). A auditoria aplica ADR-009 e ADR-010. Os produtores F1/F8/F9 são distintos do revisor /root/f9_gate_review. Manifesto SHA-256 57cb668376871e915f213707194e51c9d76504ab6a90cdfa493b01eaed77279d, comum a Chromium 153.0.8010.0 e Firefox 153.0, Pyodide 0.27.5, NumPy 2.0.2/SciPy 1.14.1.

## Decisão atual

| Gate | Decisão F9 | Evidência e domínio |
| --- | --- | --- |
| G-0A | ACCEPTED_BY_F9 / pass, preservado | B-CARE-12x3/Worker/PyProxy na auditoria anterior. As regressões atuais foram aprovadas. DEC-OPEN-03 mantém escopo de hardware container. |
| G-0B | ACCEPTED_BY_F9 / pass, renovado | ADR-010: oito casos da escada A–D com motor nativo NumPy/SciPy, verificação primal/dual independente e fallback CVXPY/YALMIP nos dois motores, mesma build. |
| G-0C | ACCEPTED_BY_F9 / pass | Arraste real no DOM em 20 passos, preview não persistido, commit real, teclado nas seis abas, foco de modal, mobile 390 × 844, rejeição dimensional visível e curvas x/u reais. Os ensaios anteriores de RPC, offline e cancelamento foram novamente aprovados. |
| G-0D | ACCEPTED_BY_F9 / pass | G-0C aceito. ZIP real/passivo com opções de exportação reabertas. PVM estático contínuo/discreto anterior e novos downloads saturado/dinâmico executados no PathView 0.21/PathSim 0.31 com ODE independente. Quatro novos arquivos também abertos/renderizados na UI oficial. |

O estado usa a enumeração normativa ACCEPTED_BY_F9 com f9_review=accepted e decision=pass. A decisão dos gates é de capacidade no domínio auditado e mantém maturidade beta. Não há promoção automática de release estável. O manifesto schema 1 é de integridade e conserva release_approved=False com atestação externa, sem ciclo de hash com o ledger.

## Resultados e independência

| Executor | Verificação | Resultado |
| --- | --- | --- |
| Produtor F9 | pytest completo em Chromium | 372 aprovados, zero skips, 225.69 s |
| Produtor F9 | Wasm/E2E Firefox | 19 aprovados, zero skips, 729.15 s |
| Produtor F9 | npm / Node integração-oráculos | 53 / 21 aprovados |
| Produtor F9 | fixtures e duas builds independentes | Integridade aprovada, hashes idênticos |
| Revisor F9 | CPython unidade/integração/oráculos | 343 aprovados |
| Revisor F9 | npm/typecheck / F1 / pipeline | 53 / 101 / 4 aprovados |
| Revisor F9 | quatro novos E2E + quatro Wasm Chromium | 8 aprovados, 70.69 s |
| Revisor F9 | G-0B Firefox / aceite IO específico | Logs reviewer-firefox.log e reviewer-io.log aprovados |
| Revisor F9 | UI oficial PathView | 4 imports, blocos renderizados e zero pageerror |

Logs integrais, versões, matrizes, curvas e downloads originais estão em [gatecd/](gatecd/). [Parecer independente](gatecd/REVIEWER_FINDINGS.md), [entrega produtora](gatecd/PRODUCER_HANDOFF.md) e [resultados estruturados](gatecd/producer-results.json) distinguem as execuções. Avisos de depreciação AnyIO/pytest e importação do plugin estão registrados, sem erros do produto.

## Lacunas fechadas e integridade científica

A exportação UI oferece saturação pós-LQR e DynamicController, incluindo validação canônica de interconexão antes do download. Tokens de projeto/modelo/configuração e fingerprint do modelo rejeitam resultados obsoletos. As opções são persistidas em Experiment.parameters, com compatibilidade de arquivo legado e proteção de corrida na exportação ZIP.

O caso saturado usa x0=[2,0], limites ±0.25 e clipping efetivamente ativado. O dinâmico é exportado antes de LQR, usa Dp=0.4, Dc=0.3 e z0=-0.8 e confronto próprio do loop algébrico de realimentação negativa. Os testes comparam 501 amostras u/y, estados finais e todas as arestas/portas do grafo. A reabertura ZIP reproduz os bytes PVM. A tolerância existente de 2e-6 permanece intacta. Os erros ficaram próximos à precisão de máquina. F1 também confronta ambos os sinais e rejeita loop singular analiticamente. Nenhuma fixture ouro ou tolerância de oráculo foi adulterada. O único diff em tests/oracles adiciona contrato do manifesto.

## Governança, fila e limites

ADR-009 reclassifica AUD-018 como restrição externa aceita da conta pessoal, mitigada por project_governance, ci_gate e handoffs F9, conforme registro já aceito. ADR-010 substitui a antiga exigência de wheels CVXPY/Clarabel Wasm pelo motor nativo auditado. Assim, as recomendações antigas de provisionar wheels binários e habilitar regras de servidor não são pendências atuais.

PROJECT_STATE registra 26/33 pacotes aceitos. Os 7 baselines CHANGES_REQUESTED permanecem com histórico factual. Os novos pacotes F1/F8/F9 e os antigos WP-AUDIT-FIX-F9-WASM-GATES e WP-05-F1-IO-CTRLAB-PVM possuem dossiês com os 10 itens do Apêndice E, dependências aceitas e provas que resolvem seus bloqueios. A aceitação anterior de auditorias externas não é reescrita: seus pareceres históricos permanecem imutáveis.

Dinâmico .pvm funciona sem LQR. O ZIP da tela ainda requer workspace LQR confirmado e preserva suas opções de controlador. A interface não anuncia um workspace dinâmico genérico. Multirate/eventos externos permanecem fora do domínio. MATLAB não foi executado. YALMIP possui validação estrutural/sintática. DEC-OPEN-03 mantém a ressalva de homologação de hardware de referência.

## Histórico preservado

O [relatório integral de 2026-11-16](gatecd/RELATORIO_STATUS_GATES_FASE0_2026-11-16_historico.md) conserva a auditoria de 3ce128a, métricas CARE e as lacunas então vigentes. O [dossiê anterior Wasm](gatecd/WP-AUDIT-FIX-F9-WASM-GATES_historico.md) e previous_assessments no ledger conservam os bloqueios originais. Esta decisão atual substitui somente o estado de capacidade comprovado pelas novas evidências.
