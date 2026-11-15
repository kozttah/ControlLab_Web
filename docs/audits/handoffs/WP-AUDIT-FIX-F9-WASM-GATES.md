# WP-AUDIT-FIX-F9-WASM-GATES — handoff F9

## Cabeçalho do trabalho

- Documento: CL-DIR-001, versão 1.0.0; requisitos R-01, R-02, R-09, R-12, R-14, R-17, R-18, R-20, R-22, R-23, R-24.
- Frente: F9 integração/QA; revisão final por agente F9 independente.
- Base remota: `402da0d07d445855c149da7cc1ec41a3a691c26d`. Todos os textos locais foram comparados à árvore remota antes do trabalho pelo Maestro; Git HTTPS não tinha credencial e a sincronização/publicação usa o conector GitHub. Binários históricos não alterados.
- Dependência aceita: WP-AUDIT-FIX-F7-OFFLINE-SW.
- Caminhos usados: `scripts/`, `tests/{oracles,wasm,e2e,security,performance,metamorphic}/`, `.github/workflows/`, `docs/audits/`, `PROJECT_STATE.json` (Maestro).
- Contratos consumidos: RPC 1.0, tensores com `shape`/`order` explícitos, Result, snapshot IndexedDB, manifesto de release e fixtures assinadas B-CARE-02/B-CARE-12x3/B-PVM-LQR.
- Entradas: wheel e estáticos do build real, matrizes congeladas, entradas maliciosas e versão oficial PathView fixada.
- Saídas: suítes reais coletadas por pytest, medições e evidências JSON/log, pareceres dos gates, pipeline que bloqueia release sem aceite F9.
- Hipóteses: CARE contínua estabilizável com Q/R adequadas; no teste metamórfico transformação inversível e `x_tilde_0 = T x0`; nenhuma inferência de estabilidade a partir de mera importação de solver ou JSON `.pvm` válido.
- Maturidade pretendida: infraestrutura de validação; nenhuma promoção automática do produto a estável.

## Implementação e evidências

`browser_harness.py` serve os bytes do build sob HTTP local, verifica SHA-256/tamanho de cada ativo e usa Chromium real. O RPC passa pelo Worker de produção e wheel distribuído; APIs Python sem RPC usam um Worker de teste separado com o mesmo wheel. Esse Worker de teste executa exclusivamente probes confiáveis da suíte; não integra o fluxo do usuário.

- T-CARE-02: P/K contra fixture congelada e CPython; resíduo CARE recalculado independentemente e estabilidade espectral. A decodificação respeita ordem C/F dos tensores.
- T-CARE-03: planta não estabilizável falha com HYPOTHESIS_VIOLATED, sem ganho falso.
- T-CARE-04: congruência de P, transformação de K, custo com x0 transformado e polos; mesma identidade analítica em CPython/Pyodide.
- T-RPC-01: 20 revisões simultâneas, apenas revisão 19 confirmada no IndexedDB.
- T-RPC-02: cancelamento/terminação, reinicialização e snapshot confirmado recuperado; comparação exclui apenas timestamp de exportação.
- T-UI-01 parcial: API do workspace no navegador, 20 previews sem alteração persistida, seguida de commit real com revisão e ganho alterados. Não representa cobertura completa de arraste DOM, teclado/mobile ou a11y.
- T-SEC-01: teste Chromium offline anterior preservado sem alterar seu oráculo, agora coletado pela suíte; servidor desligado e cache HTTP limpo, reload por ServiceWorker e cálculo CARE; corrupção invalida readiness e retorna 503.
- Segurança: ZIP traversal e FML XXE falham com códigos tipados; importação de `.pvm` estruturalmente válido com codeContext malicioso retorna warning sem execução; CSP real com runtime pronto e cálculo UI, eventos de violação `script-src` e `connect-src`.
- Performance: 1 primeiro RPC e 10 RPCs aquecidos CARE12x3; init medido separadamente, mediana/p95/desvio, heartbeat de UI, CPU/RAM/SO/threads/browser e snapshot de heap quando disponível. Não há meta de notebook/hardware aprovada; snapshot de heap não é RSS pico do navegador. A inicialização é no ambiente local servido, sem alegação de download frio de internet.

Os Jobs D/E/F/G instalam dependências de automação versionadas em `scripts/requirements-browser.lock`, Chromium e o build completo. Os artefatos de `reports/` são preservados no CI. D/F medem o escopo real; E/G exigem também gates de produto aceitos e continuam bloqueados. O teste antigo de ausência de suítes usa agora raiz temporária ausente em vez de supor que o repositório continuará sem suítes; nenhuma tolerância científica foi modificada.

## Gates e limitações obrigatórias

**Parecer do pacote: `blocked_by_gate`.** Testes de fallback honestos podem passar sem que uma capacidade seja aprovada.

- **G-0B / F9-WASM-SDP-001 (F6/F9):** ensaio executado no Python Emscripten provisionado retorna `inconclusive`, CVXPY/Clarabel ausentes e backends indisponíveis. Isto não é um load real bem-sucedido nem prova de resolução SDP em dois navegadores. A matriz de dois browsers e os testes SDP-D1/D2 no backend de produção continuam sem demonstração. Mensagem: `SDP backend unavailable on WASM`; o solver educacional permanece experimental.
- **G-0D / F9-WASM-PVM-001 (F1/F9):** conversor e registro oficiais PathView v0.21.0, commit `4afdcc461ed63aa4231930170d20774428d51e8d`, demonstram perda de blocos/conexões em quatro exportações. Ver [dossiê oficial](../pathview/README.md) e `scripts/probe_pathview_official.py`. LQR C=I/C≠I perdem MatrixGain; saturação e controlador dinâmico também usam tipos ausentes. Não se executou código importado de terceiros. Abertura gráfica oficial e equivalência de trajetórias T-PVM-01/02 não foram aprovadas. Nenhum módulo F1 foi corrigido silenciosamente.
- **G-0A/G-0C:** evidências novas são incrementais; nenhum gate global foi promovido. Proxies/RSS completo/mobile/teclado exigem ensaios adicionais antes de release estável.

## Checklist do Apêndice E

| Item | Evidência / decisão |
|---|---|
| 1. API/contrato | RPC e wheel reais; fixture CPython e produto F7/F8 consumidores; contratos sem alteração. |
| 2. Status/diagnóstico/proveniência | Falhas PBH e SDP indisponível preservam envelopes e versões; JSON anexado. |
| 3. Analítico antes de otimização | CARE02 e identidades de congruência são analíticas; nenhuma otimização científica nesta rodada. |
| 4. Independência | Fixture congelada, resíduo/espectro NumPy e fonte/conversor externo oficial PathView. |
| 5. Ownership/oráculos | Módulos F1–F8, fixtures ouro e tolerâncias preservados; somente ajuste estrutural do teste missing-suites. |
| 6. CPython/Pyodide | CARE12x3 e similaridade demonstradas; SDP/PathView e cobertura global permanecem bloqueados. |
| 7. Schema/migração | Nenhum schema científico/RPC alterado; nenhuma migração necessária. |
| 8. Logs/dados/benchmarks | `docs/audits/wasm-gates/`, fixtures existentes assinadas e dossiê PathView; ambiente e manifest hash nos JSON. |
| 9. Experimental | Nenhum rótulo de produção promovido; unavailable SDP não substituído por solver didático. |
| 10. Limitações/seguimento | Findings F9-WASM-SDP-001 e F9-WASM-PVM-001 em PROJECT_STATE e neste parecer; responsáveis F6/F9 e F1/F9; release bloqueada explicitamente. |

## Verificação final

O comando `acceptance_cmd` completo passou na segunda tentativa: **80 testes pytest, TypeScript typecheck e 50 testes Node**, zero falhas/skips/xfail no resultado final. Ver `docs/audits/wasm-gates/acceptance-attempt-2.log`. A primeira tentativa teve 79 pytest passados e uma falha de seletor do próprio teste CSP (buscava letra K no conteúdo numérico); foi corrigido para o elemento com aria-label e estado Confirmado, com prova adicional pelos eventos CSP. Nenhuma função de produção nem tolerância foi alterada para isso.

Execução local: `CONTROLLAB_CHROMIUM=/tmp/chromium` e PATH com o venv Python de teste, Chromium **153.0.8010.0**, Node **24.22.1**. Ruff format nos nove arquivos de teste/harness/gate alterados e `pip check` passaram. Comparação dos **62 módulos Python** do wheel distribuído com fontes CPython: zero divergências (`wheel-source-identity.json`). SHA-256 do wheel: `6f97f0f2b8c48b8d59c0213309a3b7a9d76735a609720404374d1ba5efa4a102`.

A revisão independente e o probe PathView são evidência adicional à suíte verde; **aceitação do WorkPackage não é autorizada** enquanto persistirem G-0B/G-0D. Parecer `blocked_by_gate`. Não registrar tarefa concluída no budget governor.
