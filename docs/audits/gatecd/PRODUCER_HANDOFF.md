# Entrega produtora — WP-GATECD-F9-E2E

Entrega submetida à auditoria independente `/root/f9_gate_review`. A decisão formal e a atualização do ledger pertencem ao revisor e ao Maestro.

## 1. Identificação

Base `58d101d2d3296026af39c388f799e5577e38b027`, acrescida dos diffs F1/F8/F9 identificados em `source-sha256.json`. Fonte normativa CL-DIR-001, Seções 7, 9, 13.11, 14.1 e Apêndices C/E, com ADR-009 e ADR-010 vigentes. Requisitos T-UI-01, T-IO-01/02, T-PVM-01/02 e repetição T-SDP-A1..D2 nos dois motores.

Caminhos produzidos pela F9 são `scripts/gatecd_browser.py`, `scripts/build_release.py`, `tests/e2e/test_gatecd_interactions.py`, `tests/e2e/test_gatecd_pvm.py`, teste do contrato de manifesto em `tests/oracles/test_build_pipeline.py` e evidências nesta pasta. F1/F8 implementaram os arquivos de seus respectivos domínios.

## 2. Resultados observados

| Execução | Resultado |
| --- | --- |
| `pytest -q` completo em Chromium | 372 aprovados, zero skips, 225,69 s |
| `npm --prefix web test` | 53 aprovados, zero skips |
| `node --test tests/integration/*.test.mjs tests/oracles/*.test.mjs` | 21 aprovados |
| `python3 scripts/project_governance.py` | Aprovado no estado provisório do Maestro |
| `pytest tests/wasm/ tests/e2e/ -q` em Firefox | 19 aprovados, zero skips, 729,15 s |
| `python scripts/check_reproducible.py` | Duas builds com manifestos e todos os hashes idênticos |
| `python scripts/verify_fixtures.py` | Schemas, fixtures ouro e exemplos validados |

Os avisos são uma depreciação do plugin AnyIO/pytest e a ordem de importação do harness como plugin pytest. Não houve falha de execução ou teste ignorado. O Firefox apresentou custo de inicialização/execução maior neste container. As medições não homologam hardware de referência.

O manifesto de release comum aos dois motores tem SHA-256 `57cb668376871e915f213707194e51c9d76504ab6a90cdfa493b01eaed77279d`. Chromium `153.0.8010.0` e Firefox `153.0` executaram os mesmos assets verificados. A build preserva o inventário schema 1 consumido pelo Service Worker, com metadados consultivos de atestação externa. A decisão de release fica no ledger, sem ciclo de hash entre a build e suas evidências.

## 3. Checklist de entrega do Apêndice E

| Item | Evidência submetida |
| --- | --- |
| 1. Contrato | PVM usa `io.export_pvm` e validação canônica F1. A matriz SDP usa o motor nativo aprovado em ADR-010. O inventário schema 1 do manifesto preserva o consumidor F7. |
| 2. Status, diagnósticos e proveniência | Erro dimensional é apresentado como `DIMENSION_MISMATCH`, o estado confirmado anterior é preservado, preview é visível e não persistente. Artefatos contêm o hash e a versão da build. |
| 3. Testes antes da promoção | Os quatro novos testes usam eventos reais, capturam o arquivo do botão e confrontam a dinâmica antes de qualquer decisão de gate. |
| 4. Independência | PathView 0.21.0 converte o arquivo baixado. PathSim 0.31.0 executa o grafo. Uma referência própria `solve_ivp` resolve as equações de planta, clipping e loop algébrico de saída, sem chamar o simulador/exportador do ControlLab para gerar a referência. |
| 5. Ownership e oráculos | Nenhum arquivo de F1/F8 foi editado pelo produtor F9. Fixtures ouro e tolerâncias existentes permanecem intactas. A inspeção do grafo compara todas as arestas/portas expandidas, incluindo fan-out e aliases resolvidos do PathSim. |
| 6. CPython/Pyodide | Toda a suíte foi executada; os novos fluxos de UI e Wasm também passaram em Firefox. O SDP nativo foi repetido nos dois motores. |
| 7. Compatibilidade | Metadados novos de PVM são aditivos. O manifesto mantém schema 1; a atestação externa é consultiva e não é buscada pelo Service Worker. F7 auditou essa compatibilidade em modo somente leitura. |
| 8. Anexos | Logs integrais, manifesto, hashes de fontes e arquivos `.pvm`/`.ctrlab` efetivamente baixados estão em `chromium/` e `firefox/`. |
| 9. Maturidade | A interface anuncia beta. A build verifica integridade; aprovação científica e de release é uma decisão F9 externa. |
| 10. Domínio | Foram exercitados saturação pós-LQR e `DynamicController` de saída com Dp/Dc e estado inicial não nulos. Exportação dinâmica `.pvm` funciona sem síntese LQR. O `.ctrlab` da tela mantém o workspace LQR e preserva suas opções de exportação dinâmica. |

## 4. Matriz dos novos ensaios

- Mouse real com 20 movimentos em `#lqr-q-slider`, comparando o projeto persistido antes/durante/depois, bloqueio de exportação durante preview e commit autoritativo ao soltar.
- Teclado Home/ArrowRight nas seis abas, Tab até o slider, commit por seta, erro dimensional por Enter, Escape no modal com restauração de foco.
- Viewport 390×844 com o CSS efetivamente embarcado, uma coluna e ausência de overflow horizontal global. Curvas x/u possuem polylines e tabela acessível com dados reais.
- LQR com limite ±0,25 e x0=[2,0], de modo que o clipping é efetivamente ativado. Download e reexportação após reabrir o ZIP são comparados com a referência do mesmo atuador não linear.
- DynamicController com planta Dp=0,4, controlador Dc=0,3 e z0=-0,8, exportado antes de qualquer síntese LQR. Alternância dinâmico/LQR/dinâmico preserva o DTO. Após uma síntese LQR para tornar o ZIP exportável, o arquivo reabre as opções e reexporta o controlador dinâmico.

A referência usa a tolerância existente `ERROR_LIMIT=2e-6`, sem ajuste de oráculo. As simulações observadas ficaram próximas à precisão de máquina. Os relatórios numéricos por motor incluem os máximos de erro de u/y e estados finais de planta/controlador.

## 5. Próxima etapa de auditoria

O revisor independente repetirá os ensaios e verificará a abertura/renderização dos arquivos reais no PathView oficial, além da conversão/simulação já coberta. A decisão final de G-0C/G-0D deve referenciar os artefatos testados e as limitações documentadas.
