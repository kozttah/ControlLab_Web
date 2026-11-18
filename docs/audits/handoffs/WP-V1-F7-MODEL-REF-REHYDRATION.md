# Handoff F9 — WP-V1-F7-MODEL-REF-REHYDRATION

Parecer F9: accepted

Revisor independente: `/root/f9_model_refs`, separado do produtor `/root/f7_model_refs`. Data: 2026-11-18. CL-DIR-001 §§8.1–8.4/13.9/13.11 e Apêndices C/E; R-02/R-03/R-06/R-28; T-RPC-01/T-RPC-02/T-SEC-01.

Fonte auditada: base `31227da6fe93ba142058e741c8dbcd4c5637b89e` mais os arquivos identificados por SHA-256 em `docs/audits/model-ref-rehydration/checks.json`. O manifesto do build realmente executado é `9e1717cadc79f13029eb89816464a53b3fb6903903766997eb3604751a8e6d31`. Este aceite cobre o transporte de referências e suas provas locais Firefox/Pyodide; o CI do commit de conclusão deve ser acompanhado separadamente, sem inferir sua aprovação antecipada.

## Resultado e contrato

`materializePayloadReferences` é compartilhado pelo Worker real e pelo adaptador mock. Resolve somente aliases top-level explicitamente enumerados por operação; não procura recursivamente campos `_ref` em dados, proveniência ou operações desconhecidas. Os grupos de identificação correspondem aos destinos reais do dispatcher: dataset de treino da estimação, dataset de validação e os três grupos de `identification.validate_model`. `core.reuse_model` recebe somente o DTO `model` materializado e os demais campos originais permitidos, sem a referência consumida que criaria ambiguidade no contrato F1.

A resolução exige projeto, identidade, revisão e tipo exatos tanto na entrada do store quanto no DTO. Não existe fallback para outro projeto, revisão mais recente ou store global. Uma revisão histórica efetivamente armazenada continua válida. Metadados e discriminantes TS canônicos são confrontados com os tipos serializados reais, e não com o nome da classe Python. Grupos legados de planta, Fuzzy, interconexão e templates SDP têm tabela explícita em `web/worker/MODEL_REFERENCES.md`.

O preflight de todos os grupos rejeita fontes simultâneas antes de qualquer lookup, inclusive inline nulo mais referência, aliases concorrentes e dados/matrizes raw concorrentes onde o dispatcher admite essas alternativas. O payload do chamador e os objetos armazenados permanecem intactos; o DTO entregue ao Python é uma cópia. Nenhum cálculo científico é transferido para TypeScript e nenhum resultado científico é registrado automaticamente.

O mock usa a mesma validação de transporte e continua retornando indisponibilidade explícita para operações científicas que não implementa. Seus doubles não constituem evidência Wasm.

## Confronto independente e execução real

O auditor escreveu `tests/wasm/test_model_ref_rehydration.py` sem alterar os algoritmos científicos, o gerador ou as fixtures ouro. O teste usa a aplicação, `PyodideEngineClient`, Worker, wheel e RPC reais do build publicado localmente; não substitui o motor por mock nem usa um probe Worker como prova da resolução de referências.

Os dois casos positivos constroem dados sem ruído por equações plantadas: ARX com atraso de três amostras e modelo de estado de segunda ordem para subespaços. Cada fluxo registra explicitamente os datasets, estima por `dataset_ref`/`val_dataset_ref`, registra o `IdentifiedModel`, valida por referências de modelo/treino/holdout, reutiliza por `model_ref`, registra explicitamente o modelo derivado e o consome em frequência por `model_ref` e em LQR discreto por `plant_ref`.

As respostas em frequência são confrontadas com `0.4 z^-3/(1-0.7 z^-1)` e com o operador de transferência da planta de estado conhecida, em vez de igualdade de coordenadas de realizações. Os limites de `2e-10` de frequência e `1e-10` de residual DARE preservam os critérios da prova Wasm anterior de reutilização. Estabilidade e residual DARE são reconstituídos a partir das matrizes retornadas. A identidade derivada também é confrontada com o dispatcher CPython aplicado ao mesmo DTO materializado.

Registro automático é excluído por contagem do store antes/depois de estimação, validação e reutilização, além da falha explícita ao usar a referência derivada antes de registrá-la. Os datasets e o wrapper fonte são comparados com as cópias armazenadas. Uma referência aninhada inexistente na proveniência permanece dado passivo preservado. Q/R atravessam ArrayBuffers reais que ficam destacados no remetente, e P/K retornam por buffers binários reidratados. Após os fluxos, os contadores mostram zero PyProxy ativo, criação igual a destruição e nenhuma requisição ativa residual.

O caso ARX confirma um snapshot, encerra/recria o Worker, exige mudança do ID do Worker e igualdade do snapshot confirmado, e repete reutilização e identificação por referências reidratadas. Duas regressões E2E existentes e intactas demonstram, no mesmo build, vinte revisões concorrentes com apenas a atual comitada e cancelamento forçado com recuperação do snapshot.

Negativos reais cobrem projeto diferente, revisão ausente, tipo incorreto, divergência kind do store/DTO, inline+referência e inline nulo+referência, formato/keys/revisão inválidos e aliases de dataset/validação concorrentes. Um DTO impostor sob chave legítima é rejeitado. A revisão histórica 2 é consumida exatamente mesmo após registro da revisão 3. As verificações unitárias adicionais cobrem a colisão de delimitadores da chave composta e grupos contextuais fora do fluxo científico exercitado aqui.

## Evidências e revisão de alterações

- `docs/audits/model-ref-rehydration/model-ref-firefox.log/.xml`: **5 testes passaram em 47,77 s**, sem skips: três novos casos e duas provas Wasm preexistentes de reutilização inline.
- `docs/audits/model-ref-rehydration/model-ref-recovery.log/.xml`: **2 testes passaram em 43,30 s**, sem skips: revisões concorrentes e cancelamento/restart reais.
- `docs/audits/model-ref-rehydration/browser/`: sete relatórios JSON identificam Firefox 153.0 e o mesmo SHA-256 de manifesto, com resíduos científicos, referências, snapshots, erros tipados e estatísticas de PyProxy/store.
- `docs/audits/model-ref-rehydration/model-refs-f7.log`: typecheck e **63 testes F7 aprovados**, zero falhas/skips. `model-refs-web.log`: **84 testes web aprovados**, zero falhas/skips, conforme execução independente do Maestro.
- `docs/audits/model-ref-rehydration/baseline.json`, `checks.json` e `fixtures.log`: sete fixtures ouro, seus checksums e lock Pyodide mantêm os nove hashes protegidos; o verificador aprovou 11 schemas e quatro exemplos. Nenhuma tolerância de fixture/oráculo preexistente ou implementação científica de F1–F6 foi modificada.

O auditor revisou os ajustes dos testes antigos: o helper de lifecycle agora fornece planta inline; o teste de transporte binário fornece A/B da fixture congelada em memória; o teste de entrypoint ausente fornece matrizes raw válidas. Antes usavam referências de exemplo nunca registradas e dependiam de doubles permissivos. As asserções originais de transporte, cancelamento, destruição de proxies e recuperação permaneceram intactas. Os bytes do exemplo e da fixture não foram alterados.

A primeira execução de cinco casos teve quatro aprovações e uma falha exclusivamente no teste novo F9: ele buscava `dt` diretamente no wrapper `IdentifiedModel`, embora o contrato o armazene no modelo contido. Corrigiu-se somente a asserção para `identified_model.model.dt`, sem alteração de runtime, build, algoritmo ou tolerância. A repetição integral dos cinco casos passou. Uma advertência de plugin externo anyio/pytest foi registrada nos logs; não houve skip/xfail usado como aceite.

## Checklist do Apêndice E

| Item | Evidência e parecer |
| --- | --- |
| 1. API e consumidores | CONFORME: contrato F1 `core.reuse_model.v1` preservado; aliases e destinos Python confrontados, payload canônico testado e tabela F7 fornecida a consumidores. Registro continua explícito. |
| 2. Status, diagnósticos e proveniência | CONFORME: negativos reais retornam failure, erro tipado e resultado nulo; proveniência passiva preservada; relatórios registram store, Worker, manifesto e contadores de PyProxy. |
| 3. Referência analítica | CONFORME: equação ARX com atraso, planta de estado conhecida, transferência independente e residual DARE reconstruído, sem duplicar ciência em TypeScript. |
| 4. Independência | CONFORME: auditor separado escreveu os testes Wasm e confrontou registro/referência/consumo no produto real; doubles F7 são somente prova de contrato/transporte. |
| 5. Ownership e ouro | CONFORME: F7 alterou somente seus diretórios; F9 acrescentou testes Wasm e auditoria. Nove hashes protegidos intactos; testes antigos tiveram somente setup canônico corrigido, sem afrouxar asserções. |
| 6. CPython/Pyodide no domínio anunciado | CONFORME: os modelos derivados passam pela comparação de identidade com CPython e pelos operadores analíticos no Worker/Pyodide Firefox 153 real. Não se infere nova matriz de navegadores ou promoção de gate; CI posterior continua obrigatório para regressões hospedadas. |
| 7. Schema e versão | CONFORME: envelope RPC 1.0, schemas e DTOs científicos permanecem iguais; a mudança é reidratação de aliases documentada, sem migração de projeto. |
| 8. Logs e resultados | CONFORME: sete relatórios JSON de navegador, dois relatórios JUnit, logs de aceite F7/web, hashes de fontes e manifesto do único build estão arquivados. |
| 9. Maturidade experimental | CONFORME: nenhuma maturidade científica ou classificação de gate foi elevada; funcionalidades mock não são apresentadas como cálculos científicos disponíveis. |
| 10. Limitações e falhas | CONFORME: resolução top-level operação-específica, revisão ausente sem fallback e registro explícito documentados. A prova local usa Firefox; o CI do commit final deve demonstrar suas regressões Chromium e publicação sem antecipação neste parecer. |

## Decisão e limites

O Maestro pode registrar `ACCEPTED_BY_F9` para este WorkPackage, com a fonte identificada por base e hashes e escopo de referências tipadas no Worker/Pyodide demonstrado acima. A disponibilidade dos aliases não implica qualidade estatística nova do modelo identificado e não autoriza interpretar referências arbitrárias da proveniência. Bibliotecas científicas, schemas, fixtures e tolerâncias permanecem preservados.

O commit de conclusão e seus jobs hospedados devem ser acompanhados pelo Maestro. Este documento não afirma que um CI ainda não executado passou, não substitui a auditoria de release estável e não amplia o escopo dos gates existentes.
