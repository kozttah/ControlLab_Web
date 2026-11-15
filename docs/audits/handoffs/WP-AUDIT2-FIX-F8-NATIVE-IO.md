# Dossiê F9 — WP-AUDIT2-FIX-F8-NATIVE-IO

## Cabeçalho

| Campo | Evidência |
|---|---|
| Frente e requisitos | F8, R-02/R-19/R-20/R-21. Integração referente a AUD-019, AUD-020 e AUD-021. |
| Caminhos e dependências | web/app/, web/features/, tests/unit/f8/. WP-AUDIT2-FIX-F1-IO-RPC e WP-AUDIT2-FIX-F8-CONTAIN-EXPORT aceitos. |
| Entradas/saídas | Exportar revisão LQR confirmada pelos RPCs io.export_ctrlab e io.export_pvm. Reabrir os bytes ZIP por io.import_ctrlab e reconstruir o workspace a partir do Experiment canônico. |
| Hipóteses e limite | A tela trabalha com feedback estático de estado LQR. Exige workspace LQR compatível gravado no Experiment para reabertura. Registra erro tipado nos demais casos. |
| Aceite, risco e maturidade | Typecheck e suíte unitária F8. Riscos de troca assíncrona de revisão, perda de sinal/proveniência e arquivo incompatível. Escopo de integração nativa da UI, com prova Chromium no caso abaixo. WP-AUDIT2-FIX-F9-DOWNLOAD-E2E abrange a matriz de downloads, conversor oficial e PathSim. |

## Checklist do Apêndice E

| Item | Evidência |
|---|---|
| 1. Contrato | F8 consome os RPCs F1 aprovados. O modal baixa os bytes retornados, preservando extensão, hash e MIME. O input encaminha o conteúdo para importação passiva. |
| 2. Status, diagnóstico e proveniência | O ZIP do navegador contém planta, controlador e manifesto com sinal, unidades, revisão e proveniência verificados contra o snapshot. A importação oferece diagnóstico para projeto incompatível com o workspace LQR. |
| 3. Referência analítica | A F9 derivou A−BK das matrizes do arquivo .ctrlab e verificou a dinâmica projetada a partir dos bytes PVM do mesmo commit no navegador. Execução da suíte normativa de I/O F1 incluiu estático, dinâmico e integridade/passividade. |
| 4. Independência | Chromium/Pyodide real, evento de download do navegador, load_ctrlab em CPython sobre os bytes recebidos, novo mount da UI e importação via input de arquivo. A comparação é feita com o estado anterior à exportação. |
| 5. Ownership e ouro | Os quatro arquivos alterados pertencem à F8. git diff HEAD -- contracts/fixtures tests/oracles e git diff --check retornaram zero. A F9 verificou a operação real, independente do transporte sintético usado nos testes Node da F8. |
| 6. Runtime | O Worker executou Pyodide com NumPy/SciPy locais. CPython reabriu os mesmos bytes. Também passou test_preview_is_never_persisted_then_real_commit em Chromium/Pyodide/IndexedDB. |
| 7. Schema | F8 adotou io_rpc.schema.json v1.0.0 sem modificar o contrato. A igualdade estrutural de K tolera diferenças legítimas na ordem de chaves JSON entre CPython, Pyodide e JavaScript. |
| 8. Logs | docs/architecture/audit-logs/WP-AUDIT2-FIX-F8-NATIVE-IO.log contém ambientes, comandos, saídas e a fonte do confronto independente. Sem meta de desempenho neste pacote. |
| 9. Limites de maturidade | A exportação PVM usa o serializador oficial da F1. O aceite deste caso real não libera todos os modelos nem os gates de release. |
| 10. Limitações e concorrência | Preview e pending_commit impedem exportar. O importador trava edição e segunda importação até concluir a persistência. O modal verifica projeto, revisão e request antes do download. O WP-F9 de download verifica o conversor oficial e as demais combinações. |

## 5. Parecer independente

- Revisor independente: f9-integration-qa
- Commit SHA auditado (base): 98855bfd0cc308264fba41a1c0063bf7084bb9dd
- Data (UTC): 2026-11-15
- Testes: typecheck e 19 F8, 11 oráculos Node, 43 testes F1 de I/O, um teste de preview real e uma prova independente de download duplo e reabertura por upload. O teste de preview emitiu um aviso de depreciação do plugin pytest/anyio.
- Parecer F9: accepted
