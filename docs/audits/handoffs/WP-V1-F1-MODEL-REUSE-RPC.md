# WP-V1-F1-MODEL-REUSE-RPC — reutilização canônica e contrato RPC

Base: `984651087e0248e57ba80e9bf36133d1737d6f73`, mais incremento F1 e testes independentes identificados em [review-summary.json](../model-reuse/review-summary.json). Data UTC: 2026-11-17. Norma: CL-DIR-001 §§4.1/4.4/5.2/13.3/13.11, R-03/R-06/R-27 e Apêndices B/C/E. Frente produtora `/root/f1_model_reuse_rpc`; revisor independente `/root/f9_model_reuse_qa`.

## 1. Entrega e contrato aprovado

`core.reuse_model` é uma adição ao envelope RPC `api_version=1.0`; seu resultado declara `reuse_version=1.0.0`. O [contrato aprovado pela F9](../../../contracts/operations/core.reuse_model.v1.md) define entrada inline/ref mutuamente exclusiva, alvo nativo/StateSpace, nova identidade determinística por conteúdo e proveniência, revisão inicial zero, dimensões, domínio e linhagem. Não há quebra de schema ou nova operação de commit/persistência.

A API científica `reuse_model` extrai o modelo de IdentifiedModel ou reutiliza modelos canônicos LTI/TS. A conversão de representação TF→SS usa a API existente, preserva canais, unidades e `dt`, inclusive atrasos discretos `z^-1`. TS nativo mantém sua semântica; conversão implícita para LTI é recusada. Nenhuma fonte/store é mutada e nenhuma revisão é substituída silenciosamente. Métricas, partições e hipóteses da identificação permanecem na linhagem, sem serem anunciadas como nova certificação estatística.

O escopo de referências CPython exige stores verificavelmente delimitados por projeto: chave tripla, bucket por projeto ou resolver de três argumentos. Mappings flat sem escopo são recusados. ID e revisão do objeto precisam corresponder à referência exata. Uma revisão histórica explicitamente presente continua válida para reprodução; concorrência global `project_revision` permanece responsabilidade da ponte F7.

## 2. Verificações executadas

| Verificação | Resultado | Evidência |
| --- | --- | --- |
| Aceite original `python3 -m pytest tests/unit/f1/ -v` | 116 passed, sem skips; 15 testes novos da frente | Execução do produtor comunicada e suíte incluída novamente no perfil core abaixo. |
| Oráculos F9 específicos | 15 passed em 1.07s, sem skips | `tests/oracles/test_model_reuse_independent.py`; resumo SHA em review-summary.json. |
| Worker RPC/Pyodide real em Firefox 153 | 2 passed em 28.77s, sem skips | [firefox-rpc.log](../model-reuse/firefox-rpc.log), [ARX](../model-reuse/model-reuse-arx_delay.json), [subespaços](../model-reuse/model-reuse-subspace.json). |
| CI matemático isolado core_no_sdp | 329 passed, zero skips, retorno 0 | [JSON](../model-reuse/core/B-core_no_sdp.json) e XML do Maestro. |
| CI matemático isolado sdp_available | 163 passed, zero skips, retorno 0 | [JSON](../model-reuse/sdp/B-sdp_available.json) e XML do Maestro. |
| Web com typecheck real | 53 passed | Execução do Maestro; fontes F7/F8 não alteradas nesta entrega. |
| Build científico/estático | 42 assets com integridade validada | [build.log](../model-reuse/build.log); manifesto SHA-256 abaixo. |
| Ouro/contratos congelados | 7 fixtures e checksums byte a byte iguais à base, 11 schemas e 4 exemplos válidos | `scripts/verify_fixtures.py` e inventário protegido em review-summary.json. |

As contagens das suítes se sobrepõem e não devem ser somadas como casos distintos. O primeiro ensaio dos novos oráculos continha uma hipótese errada de montagem do teste (matrizes A/B/C/D no topo do DTO); os testes foram corrigidos para o schema canônico preexistente `matrices`, sem modificar implementação ou tolerâncias científicas. Ausência de pytest no Python base foi tratada usando ambiente virtual existente com lock exato, sem instalação ou alteração de dependências versionadas nesta auditoria.

Os oráculos independentes usam `2/(s+3)`, matriz de transferência MIMO analítica, impulso com recorrência explícita preservando três amostras de atraso, ARX sem ruído com coeficientes plantados e subespaços de planta discreta conhecida. Realizações de subespaços são confrontadas por resposta H(z), sem exigir igualdade de matrizes em coordenadas diferentes. Negativos cobrem overrides, ambiguidade, NaN, dimensão inválida, referências ausentes/divergentes, objeto impostor, projeto diferente e fallback global indevido.

Os dois ensaios Wasm atravessam o **Worker de produto e o RPC real**, sem mock e sem substituição por uma chamada Python de probe. Cada um executa identificação, reutilização inline e consumo do StateSpace por LQR discreto. Erro máximo observado H(z): aproximadamente `3e-15` para ARX com atraso e `1.7e-15` para subespaços; resíduos DARE recalculados independentemente `4.28e-16` e `1.41e-16`, com polos fechados estáveis. Esses resultados não autorizam inferir qualidade de identificação fora dos exemplos ensaiados.

Manifesto do build testado: `bc3feced6a35544d0a657f5cc94d3cbbaa723598ff01209e7eabb8193c980b2c`. NumPy/SciPy no Wasm são as versões fixadas pelo runtime Pyodide 0.27.5; a auditoria identifica os bytes efetivamente testados, não presume equivalência por nome do pacote.

## 3. Limites de aceite e acompanhamento

1. **Registro/reidratação JS não faz parte desta entrega F1.** O Worker atual materializa `plant_ref`, mas não fornece um store Python genérico para `model_ref`; os exemplos browser deste pacote usam DTO canônico inline. A referência retornada não significa registro automático em WorkerModelStore. O teste verifica que uma chamada ref-only sem store falha explicitamente com instrução de enviar modelo inline. Rastrear `WP-V1-F7-MODEL-REF-REHYDRATION` antes de `WP-V1-F8-TYPED-WORKSPACE-INPUTS`.
2. **Atualização do cache entre releases precisa de pacote próprio.** A inspeção estática identificou que `scripts/build_web.mjs` não injeta fingerprint de release no script Service Worker, cujo evento install não é renovado por uma mudança somente na wheel. `handleFetch` serve a release ativa cacheada, sem consultar um manifesto novo. Os testes desta entrega usam contextos novos e não provam atualização de um navegador já provisionado. Rastrear `WP-AUDIT-FIX-F9-SW-RELEASE-VERSION`, com duas distribuições na mesma URL/prefixo, atualização segura, fallback offline e identidade determinística sem ciclo de hash.
3. O pacote não entrega a UI de identificação/reutilização, persistência multidomínio, cobertura de todos os métodos ou uma release estável. Acesso à funcionalidade por uma interface completa pertence aos próximos pacotes. A maturidade científica continua beta no escopo validado.

Critérios sugeridos para o pacote F7: mapear aliases declarados por operação (`model_ref→model` em core.reuse_model; `dataset_ref→dataset` nos ajustes de identificação; aliases de treino/validação quando declarados), com tipo, projeto, identidade e revisão exatos. Rejeitar inline+ref ambíguos antes da reidratação e remover a referência da cópia resolvida enviada ao Python. Sem resolver indiscriminadamente qualquer chave `*_ref`, sem fallback global, sem mutação da requisição original e sem vazamentos de PyProxy. Aceite F7 por typecheck e testes da frente, seguido de referências reais através do Worker/Pyodide pela F9.

## 4. Checklist de Handoff — Apêndice E

| Item | Questão | Resposta | Evidência | Auditoria F9 |
| --- | --- | --- | --- | --- |
| 1 | Contrato, dimensões, domínio e consumidores | SIM | Contrato aditivo aprovado antes do consumo; `dt`/canais/unidades preservados e consumo por DARE real no Worker. | CONFORME |
| 2 | Status, diagnósticos e proveniência | SIM | Result/RpcResponse tipados, erros sem modelo parcial, linhagem da identificação e política de identidade/revisão explícitas. | CONFORME |
| 3 | Caso analítico antes da otimização | SIM | Recorrência ARX/impulso, CT `2/(s+3)`, MIMO e H(z) de planta conhecida; nenhuma otimização nova. | CONFORME |
| 4 | Oráculo independente | SIM | F9 sem autoria funcional F1; respostas e DARE confrontados com equações independentes, sem gerar ouro por produção. | CONFORME |
| 5 | Ownership e ouro | SIM | Implementação restrita F1; testes/contrato/auditoria F9. Fixtures, checksums e tolerâncias congeladas intactos. | CONFORME |
| 6 | CPython e Pyodide no domínio anunciado | SIM/ESCOPO | 15 oráculos específicos CPython e dois testes Worker RPC reais; refs em CPython com store, DTO inline no Wasm; limite F7 explícito. | CONFORME |
| 7 | Versionamento, schema e revisão | SIM | Envelope 1.0 preservado; resultado 1.0.0, DTO canônico com nova identidade/revisão zero; revisão histórica exata permitida. | CONFORME |
| 8 | Logs, matrizes e benchmark | SIM/ESCOPO | Logs/JSON/XML, fonte SHA, build e matrizes plantadas nos testes; não há promessa de benchmark ou hardware novo. | CONFORME |
| 9 | Experimental e maturidade | SIM | Beta preservada, sem alterar classificação do solver educacional ou promover release estável. | CONFORME |
| 10 | Limitações e acompanhamento | SIM | Lacunas F7 de refs e F9 de atualização SW descritas com IDs e critérios, fora dos diretórios F1; contextos novos explicitados. | CONFORME |

## 5. Parecer F9

- Revisor independente: `/root/f9_model_reuse_qa`.
- Commit SHA auditado: `984651087e0248e57ba80e9bf36133d1737d6f73`, acrescido do incremento identificado em [review-summary.json](../model-reuse/review-summary.json).
- Data (UTC): 2026-11-17.
- Veredito F9: accepted
- Escopo de aceite: derivação canônica pura e RPC inline CPython/Pyodide, com referências CPython estritamente delimitadas por projeto, domínio/atrasos e linhagem preservados; sem registro/reidratação JS automática, sem homologação de atualização de cache entre releases ou de nova vertical UI.

Este parecer autoriza o Maestro a aceitar o pacote com o escopo acima e a registrar os dois acompanhamentos sem inferir que essas lacunas já foram corrigidas. O resultado dos novos jobs hospedados e a publicação do commit permanecem a confirmar após o push; este handoff não alega execução remota ainda inexistente.
