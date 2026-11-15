# Validação de governança v1 — AUD-016

O módulo `scripts/project_governance.py` valida registros do CL-DIR-001, não valores numéricos nem capacidades do navegador. É chamado pelos testes de integração do Job B; pode ser executado com `python3 scripts/project_governance.py`.

A fila pode crescer, e o veredito factual de um gate pendente pode mudar sem editar testes. IDs são únicos, referências precisam existir e dependências não podem formar ciclos. Achados confirmados precisam de pacotes corretivos. A seleção respeita a ordem da fila, dependências aceitas e bloqueadores externos explícitos.

Todo novo aceite exige escopo, revisão F9 accepted e arquivo de handoff identificado pelo WP. O parser aceita tabela numerada de cinco colunas ou tabela descritiva de duas colunas: ambas exigem exatamente os itens 1 a 10 com evidências, decisão accepted explícita e SHA de fonte. Opções do template não são uma decisão. Menções a gates globais pendentes não invalidam um aceite estritamente local; item do checklist sem evidência permanece inválido.

Três aceites históricos CPython sem handoff foram migrados explicitamente com `legacy_cpython_local.v1`, referências existentes de testes e bloqueadores de release. Essa dívida é visível no estado. A exceção de dependência reaberta aplica-se somente a esses registros legados, nunca a um novo aceite. Nenhum parecer retrospectivo foi inventado.

Aceitar gate exige evidência, identidade de fonte, escopo, decisão pass e remoção dos bloqueadores; indisponibilidade ou condicional não equivalem a pass. G-0B exige ainda declaração de SDP Wasm de produção em dois browsers. `validate_transition` exige preservar histórico e apontar auditoria ao reabrir gate aceito. Esses controles verificam o registro; a revisão técnica independente deve conferir a autenticidade e suficiência da prova.

Uma declaração de release stable exige todos os gates aceitos e registro de proteção verificada com evidência. A proteção efetiva de main depende do servidor. Este validador não configura proteção e não transforma CODEOWNERS em enforcement. Os T-PVM-01/02, T-UI-01 e T-SEC-01 continuam com seu escopo normativo: guards de registros não substituem execução científica nem download E2E. Exportações UI incorretas e metadados inseguros seguem bloqueando a integração conforme a Auditoria 2.
