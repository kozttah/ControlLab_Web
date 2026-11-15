# Parecer F9 independente — WP-AUDIT-FIX-F9-WASM-GATES

**Decisão: `blocked_by_gate`. Não autorizar `ACCEPTED_BY_F9`, incremento do orçamento de tarefas concluídas ou promoção de release estável.** A infraestrutura de testes tem regressões verdes, mas a validação normativa do pacote continua impedida pelos findings F9-WASM-PVM-001 e F9-WASM-SDP-001.

Revisor: agente `f9_independent_audit`, separado do implementador e do Maestro. Referência normativa exclusiva: CL-DIR-001 v1.0.0, §§9.3, 14.1, 15.2 e Apêndices C/E. Base remota informada e conferida pelo Maestro: `402da0d07d445855c149da7cc1ec41a3a691c26d`. Esta revisão não alterou módulos científicos, testes, contratos ou PROJECT_STATE; escreveu somente este parecer e executou verificações.

## Evidência examinada e execução independente

1. Li as diretrizes AGENTS/F9, a especificação normativa e os diffs finais dos testes, harness, pipeline e estado. Revisei e solicitei o fortalecimento de dois asserts inicialmente fracos: comparação do preview sem depender do timestamp `exported_at`, com confirmação de revisão/ganho, e comparação explícita dos polos no metamórfico. As fontes finais contêm as correções.
2. Conferi a execução final do comando de aceitação no log `docs/audits/wasm-gates/acceptance-attempt-2.log`: **80 testes pytest passaram em 83,19 s**, typecheck passou e **50 testes Node passaram**, sem skips ou falhas no resultado final. A tentativa anterior teve 79 passes e uma falha de seletor CSP; o log anterior foi preservado e o teste final usa o seletor acessível da matriz de ganho e eventos reais de violação CSP. Não se modificou código de produção para resolver essa falha.
3. Reexecutei independentemente o subconjunto científico/integração em Chromium real com o comando abaixo: **7 passes em 47,73 s**. O executável padrão deste agente não tinha pytest; usei o ambiente CI existente, sem alterar dependências ou tolerâncias.

```bash
CONTROLLAB_CHROMIUM=/tmp/chromium /workspace/scratch/ba21e63c86f4/f9-ci-sdp/bin/python -m pytest tests/wasm/test_real_runtime.py tests/e2e/test_revision_recovery.py tests/metamorphic/test_wasm_similarity.py -v
```

4. A execução independente reproduziu CARE 12×3 contra a fixture e CPython, falha PBH sem ganho falso, diagnóstico SDP indisponível, 20 revisões com um único commit atual, cancelamento/reinício com snapshot recuperado, preview não persistente seguido de ganho/revisão novos e congruência/custo/espectro sob similaridade. Ambiente: Python 3.12.14, pytest 9.2.0 e Chromium 153.0.8010.0.
5. Para CARE 12×3, observei erro relativo de P `2.246921173006027e-15`, erro relativo de K `2.4176488128604944e-15` e resíduo CARE recalculado `1.1066184246108006e-15`. As tolerâncias vêm da fixture existente. O resíduo e a estabilidade espectral são verificados por operações matriciais independentes do solver. O registro `wheel-source-identity.json` informa 62 módulos Python comparados sem discrepâncias entre fontes e wheel, SHA-256 `6f97f0f2b8c48b8d59c0213309a3b7a9d76735a609720404374d1ba5efa4a102`.
6. Executei novamente `scripts/probe_pathview_official.py` contra as quatro fontes oficiais fixadas e verificadas por Git blob SHA-1. Resultado: **exit 2** e G-0D `fail`. O conversor oficial PathView v0.21.0, commit `4afdcc461ed63aa4231930170d20774428d51e8d`, omite MatrixGain e suas conexões em ambos os casos LQR; Saturation e DynamicController também estão ausentes no registro oficial. Confirmei as contagens abaixo. Não houve execução da simulação gerada nem abertura gráfica oficial; nenhuma dessas etapas é alegada como aprovada.

| Caso | Conexões no PVM | Chamadas Connection geradas |
|---|---:|---:|
| LQR C=I | 5 | 3 |
| LQR C≠I | 5 | 3 |
| LQR com saturação | 6 | 2 |
| Controlador dinâmico | 5 | 1 |

7. Inspecionei `ci_gate.py` e isolei seu controle E/G em memória com resultado de suíte sintético bem-sucedido e JUnit não vazio. Mesmo assim, E retornou 2 por G-0D e G retornou 2 por G-0A/B/C/D não aceitos. Esta é uma verificação do bloqueio de orquestração; não constitui execução dos Jobs no GitHub Actions nem nova evidência científica. O bloqueio depende do estado explícito F9 e evita converter um diagnóstico de capacidade ausente em autorização de release.
8. Comparei hashes SHA-256 dos **105 arquivos rastreados** no baseline protegido. Todos os módulos F1–F8, fixtures ouro e oráculos científicos permanecem idênticos. A única diferença nesse conjunto é `tests/oracles/test_build_pipeline.py`, limitada ao teste estrutural de suítes ausentes: passou a usar ROOT temporário sem suítes, conservando a obrigação de retornar bloqueio. Não houve alteração de esperado científico, mock para mascarar defeito ou tolerância. `git diff --check` passou.

## Cobertura normativa e limites de aprovação

| Teste/requisito | Evidência final | Decisão de escopo |
|---|---|---|
| T-CARE-02 | Fixture congelada, CPython/Pyodide, P/K, resíduo e espectro | Demonstrado no Chromium local testado |
| T-CARE-03 | RPC real retorna HYPOTHESIS_VIOLATED e resultado nulo | Demonstrado no Chromium local testado |
| T-CARE-04 adicional | P/K transformados, x0 transformado, custo e polos | Demonstrado no domínio analítico exercido |
| T-RPC-01 | 20 revisões, um commit da revisão 19 | Demonstrado no fluxo testado |
| T-RPC-02 | Cancelamento/reinício e snapshot confirmado preservado | Demonstrado no fluxo testado |
| T-UI-01 | API do workspace em navegador, preview e commit real; clique de cálculo na UI CSP | Parcial: não substitui arraste DOM, mobile, teclado e a11y completos |
| T-SEC-01 | Teste anterior preservado e coletado: servidor parado, cache HTTP limpo, reload SW e CARE; corrupção retorna 503 | Regressão local demonstrada, sem promoção automática de release |
| T-PVM-01 / T-PVM-02 | Conversor oficial perde blocos e conexões; sem UI/trajetórias externas aprovadas | **Bloqueado — F9-WASM-PVM-001** |
| T-SDP-D1 / T-SDP-D2 no Wasm de produção | Backend Clarabel/CVXPY ausente no runtime provisionado | **Não demonstrado — F9-WASM-SDP-001** |
| G-0A / G-0C completos | Evidência incremental CARE/RPC/UI; proxies, RSS completo, mobile/teclado ainda não integralmente ensaiados | Manter estado global sem promoção |
| G-0B completo | Diagnóstico real de indisponibilidade em Emscripten; não houve load/resolução auditada em dois browsers | Manter SDP de produção indisponível |
| G-0D completo | Incompatibilidade real com registro/conversor oficial | Manter bloqueio e encaminhar correção à F1 |

As medições de desempenho registram inicialização do runtime servida localmente, primeiro RPC e dez RPCs aquecidos separadamente. Mediana/p95/desvio e heartbeat são evidência do ambiente medido; não aprovam desempenho em notebook de referência. O snapshot de heap JS não mede RSS pico completo nem estabelece ausência de vazamento de proxies.

## Checklist de Handoff — dez itens do Apêndice E

| Item | Verificação independente | Resultado |
|---|---|---|
| 1. API/contrato aprovado e consumidores | RPC real do produto e wheel, consumidores F7/F8 exercidos; contratos permanecem inalterados | Atendido no escopo testado |
| 2. Status, diagnósticos e proveniência | PBH falha tipada sem ganho; SDP ausente informa indisponibilidade; registros incluem versões e hash de manifesto | Atendido no escopo testado |
| 3. Analítico antes de otimização | CARE analítica/fixture e identidades de similaridade; nenhuma otimização científica nova | Atendido |
| 4. Confronto independente | Fixture congelada, cálculo independente de resíduo/espectro e conversor/registro oficial externos | Atendido; confronto externo encontrou bloqueio |
| 5. Ownership e integridade de oráculos | Hashes baseline e diff inspecionados; mudança estrutural justificada no teste de ausência de suítes | Atendido; ouro e tolerâncias preservados |
| 6. CPython/Pyodide no domínio anunciado | CARE/similaridade demonstrados; SDP produção e integração PathView não demonstrados | **Parcial; impede aceite integral** |
| 7. Schema/migração/revisão | Nenhum schema/RPC científico alterado nesta rodada | Não aplicável |
| 8. Logs, matrizes e benchmarks | Logs das duas tentativas e JSON em wasm-gates; matrizes nas fixtures congeladas e PVM de probe completo | Atendido para evidência disponível |
| 9. Classificação experimental | Nenhum módulo, capability ou rótulo promovido a estável; solver educacional não substitui produção indisponível | Atendido por preservação do escopo |
| 10. Limitações, issue e falhas adequadas | Findings internos F9-WASM-PVM-001/F9-WASM-SDP-001 registrados no estado/handoff com responsáveis e seguimento; E/G bloqueiam release | Atendido como registro interno; não se alega criação de issue GitHub |

## Encaminhamento obrigatório

Conservar o pacote como `BLOCKED_BY_GATE` / `blocked_by_gate`. O ajuste do exportador e do registro PathView pertence à F1 e deve ser um WorkPackage produtor próprio, com versão upstream fixada, portas/parâmetros corretos, preservação de realimentação/estados iniciais e posterior ensaio externo UI/trajectórias de todos os casos. F9 não deve corrigi-lo silenciosamente.

Para G-0B, provisionar um backend de produção versionado e executar a bateria completa de SDP em pelo menos dois navegadores, com verificação independente de PSD não diagonal, controle/BRL e casos de falha. O teste de indisponibilidade verde continua sendo diagnóstico de fallback e não aceite dessa capacidade.

O comando de aceitação está verde para as regressões implementadas. Isso não satisfaz, por si só, os requisitos externos e gates ausentes. O Maestro pode publicar o diagnóstico e a infraestrutura auditável; não deve usar a mensagem de conclusão aceita, incrementar o budget ou liberar a funcionalidade bloqueada.
