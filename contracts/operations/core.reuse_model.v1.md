# core.reuse_model — contrato aditivo v1.0.0

Fonte normativa CL-DIR-001 §§4.1/4.4/5.2, R-03/R-06/R-27. WorkPackage `WP-V1-F1-MODEL-REUSE-RPC`. Proposta F1 revisada e aprovada pela F9 em 2026-11-17. O envelope RPC existente continua `api_version: "1.0"`; esta adição não altera schemas de objetos científicos ou o formato do envelope. A resposta declara `reuse_version: "1.0.0"`.

## Requisição

`operation: "core.reuse_model"`, `options: {}`. O payload contém **exatamente uma** fonte:

- `model`: DTO canônico inline StateSpace, TransferFunction ou IdentifiedModel, ou modelo TS canônico suportado para extração nativa;
- `model_ref: {id, revision}`: identidade e revisão exatas de um objeto no store Python fornecido explicitamente ao dispatcher.

O único outro campo permitido é `target_kind: "native" | "StateSpace"`, com padrão `native`. Campos adicionais, opções desconhecidas, fontes simultâneas, overrides de `dt`, `id` ou `revision`, tipos incompatíveis e dados não finitos são rejeitados com erro tipado e sem modelo parcial.

`native` extrai o modelo estimado de um IdentifiedModel, ou deriva uma cópia tipada de um modelo canônico. `StateSpace` realiza a conversão explícita da representação TF usando a API científica Python existente, ou preserva a representação de estado existente. Não discretiza, não contínua um modelo discreto, não elimina atrasos `z^-1`, não transforma um TS em LTI e não executa conteúdo de proveniência. Nenhuma realização mínima é inferida ou redução de ordem efetuada implicitamente.

## Resposta

O campo `result` do RpcResponse contém:

| Campo | Semântica |
| --- | --- |
| `reuse_version` | Versão deste contrato, `1.0.0`. |
| `model` | DTO canônico derivado, com matrizes/canais/unidades e domínio preservados. |
| `model_ref` | `{id, revision}` do DTO resultante, sem prometer que ele já está registrado. |
| `source_ref` | Identidade/revisão da fonte recebida, incluindo o wrapper IdentifiedModel quando aplicável. |
| `source_model_ref` | Identidade/revisão do modelo científico de origem, anterior à derivação. |
| `dt` | Tempo de amostragem original, inclusive `null` para contínuo. |
| `dimensions` | `{n_states, n_inputs, n_outputs}`. `n_states` é `null` em TF nativa; não se inventa ordem de estado para essa representação. |
| `identity_policy` | `derived_new_identity_revision_zero`. |
| `derivation` | Fonte, tipo, alvo, mudança de representação e responsabilidade de registro descritos abaixo. |

`derivation` contém `source_ref`, `source_model_ref`, `source_kind`, `source_model_kind`, `target_kind`, `representation_changed`, `time_domain_changed: false` e `registration_required: true`.

O novo ID é determinístico para a mesma fonte canônica completa e o mesmo alvo/versão, incluindo sua identidade e proveniência relevante. DTOs inline com mesma identidade mas conteúdo diferente não podem produzir o mesmo ID derivado. O resultado possui identidade diferente da origem e revisão inicial **0**, compatível com os construtores e stores existentes. A operação não altera a fonte, revisões ou stores e não efetua commit de projeto. Repetir a mesma derivação pode produzir a mesma identidade; isso não equivale a uma edição do modelo original.

A proveniência do modelo conserva a linhagem e os dados da identificação (dataset, algoritmo, partições, métricas, hipóteses e diagnósticos) quando aplicáveis. Esses diagnósticos pertencem à identificação de origem: reutilização não certifica qualidade estatística nova. O Result/RpcResponse registra o algoritmo de derivação e seus avisos, incluindo alertas de condicionamento de uma conversão.

## Referências e limite atual de transporte

No CPython, `dispatch(request, store=...)` exige identidade **e revisão** correspondentes ao objeto recuperado, com isolamento de projeto. Stores aceitos usam chave `(project_id, id, revision)`, bucket explícito por projeto ou resolver de três argumentos `(project_id, id, revision)`. Mappings flat sem escopo explícito são rejeitados. Referências ausentes/divergentes e um objeto impostor com a mesma revisão são rejeitados. Uma revisão histórica explicitamente presente no store pode ser reutilizada: não há substituição silenciosa pela revisão mais recente nem persistência automática. A concorrência de `project_revision` do fluxo UI permanece responsabilidade da ponte F7, e o dispatcher não promete possuir um snapshot global de projeto.

No Worker/Pyodide desta entrega, a operação é exercitada pelo **RPC real com DTO inline**. A ponte JS existente não reidrata genericamente `model_ref` para o store Python. Portanto, uma referência isolada sem store resolvível falha explicitamente; o cliente não deve tratar o `model_ref` retornado como registro já realizado. Essa lacuna pertence à F7 e fica rastreada no handoff para um WorkPackage próprio antes da vertical de inputs tipados F8. Não há promessa de registro automático em WorkerModelStore, migração ou persistência multidomínio nesta operação F1.

## Verificação independente

F9 confronta TF contínua com `2/(s+3)`, atraso discreto com recorrência explícita, ARX sem ruído com coeficientes plantados e subespaços com o operador de transferência de uma planta conhecida. Realizações diferentes são comparadas por respostas, não por igualdade de matrizes em coordenadas distintas. Testes negativos cobrem ambiguidade, domínio/identidade sobrescritos, dimensões inválidas, NaN, revisão obsoleta, objeto de identidade incorreta e projeto diferente. Testes no navegador atravessam Worker RPC, identificação, reutilização inline e consumo por LQR discreto, preservando a limitação de referências acima.
