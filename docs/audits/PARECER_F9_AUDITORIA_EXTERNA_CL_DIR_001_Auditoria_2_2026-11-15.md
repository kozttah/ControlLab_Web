# Parecer técnico F9 — Auditoria externa 2 (CL-DIR-001)

**Relatório examinado integralmente:** AUD-EXT-CL-DIR-001-2026-11-15, revisão 2, `docs/audit/AUDITORIA_EXTERNA_CL_DIR_001_Auditoria_2_2026-11-15.md` (871 linhas; blob `6a71dd8ecabd6d3e5213e461baa394f81ca5058c`).
**Base atual conferida:** `50ba04d16633e9cd96c3b90a7668466c30ee9ca7`; o único commit posterior ao SHA auditado `60d5c5c8cd49d7a91b4d7d77b94582182565df59` acrescenta os dois relatórios, sem modificar produção.
**Norma única:** CL-DIR-001 v1.0.0, SHA256 `f7f10b1a19eb6a145959693937e1c67c97717e6a93e2a690f0045c2f96768102`.
**Decisão de produto:** permanece NOT_APPROVED_FOR_STABLE_WEB_RELEASE. Nenhum gate global é promovido.

## Localização e método

A auditoria nova está em `docs/audit/` (singular); a pasta `docs/audits/` contém a auditoria anterior já processada. A escolha usa o histórico Git e o identificador/data do relatório, não o mtime de arquivos restaurados. Ambos os originais foram preservados. O checkout local foi sincronizado por objetos autenticados do GitHub com conferência de todos os blobs e do OID de árvore/commit. Como o Git HTTPS não possuía credencial, a leitura autenticada do conector foi usada; nenhum push ou mutação remota foi efetuado. A branch local de trabalho é `f9/audit2-triage-first-fix`, com base no main atual.

Os seis achados ativos foram confrontados com o código atual, a norma e os probes anexos. Para AUD-019/020/021 foram chamados os métodos reais de exportação F8 com acessores somente-leitura e um resultado LQR CPython genuíno. Isto é uma reprodução unitária dos métodos, **não** uma nova captura E2E de browser; a integração por download continua pendente. O Python convertido/injetado não foi executado: somente conversão oficial e parsing AST.

## Matriz completa dos achados ativos

| ID | Severidade | Classificação F9 | Prova atual e norma | Encaminhamento |
|---|---|---|---|---|
| AUD-016 | MÉDIO | CONFIRMED | Na base, `tests/integration/test_governance_and_ownership.py:232-289` exige vereditos antigos e nove corretivos; `:459-494` exige cabeçalhos fixos. A reprodução do teste falha em `:246` (AUD-016-before.log). §§10.5/13.11/15.2 e Apêndice E exigem invariantes/evidência, não fotografia eterna. | WP-AUDIT2-FIX-F9-GOV; correção imediata desta rodada. |
| AUD-017 | MÉDIO | CONFIRMED | `tests/unit/f1/test_core_rpc_and_immutability.py:842-851` usa backend auto e exige indisponível. O perfil SDP real falha na asserção `:850` porque houve success legítimo (AUD-017-sdp-before.log). `control_lab/core/rpc.py:1812-1831` não apresenta defeito matemático demonstrado. R-02/R-12/R-23. | WP-AUDIT2-FIX-F1-OPTIONAL-SDP-TEST, em ambos os perfis. Não corrigir produção certa para satisfazer suposição ambiental. |
| AUD-018 | ALTO | CONFIRMED | Leitura atual `/branches/main`: protected=false, protection.enabled=false, checks off/vazios. `/rulesets` retorna 403 por plano/private (AUD-018-server.json). `CODEOWNERS:11-18` declara expressamente dependência de servidor. §15.1 obriga proteção efetiva. | WP-AUDIT2-FIX-F9-PROTECTION; bloqueio externo explícito. Não alterar plano, visibilidade, permissões ou servidor nesta rodada. |
| AUD-019 | ALTO | CONFIRMED | `web/app/main.ts:647-659` serializa JSON e nomeia .ctrlab.json; `web/app/shell.ts:676-775` retorna layout. Bytes do método real começam por `{`, e load_ctrlab retorna failure/VALIDATION_ERROR. Prova ui-probes.json. §9.1/G-0D exigem ZIP nativo e reabertura. | F1 fornece RPC aprovado; F8 consome; F9 testa os bytes efetivamente baixados. |
| AUD-020 | CRÍTICO | CONFIRMED | `web/app/main.ts:629-642` chama exportPvm paralelo; `web/app/shell.ts:923-943` emite MatrixGain. Método real produz 5 nós/5 arestas; conversor oficial mantém 3 Connection(), omitindo o ganho. Prova ui-pvm.json e converted-ui-pvm.py.txt; nenhuma execução do artefato defeituoso. §9.3/T-PVM-01/02: a malha entregue não é A−BK. | Contenção F8, RPC F1, consumidor canônico F8 e E2E F9. G-0D bloqueado pelo produto. |
| AUD-021 | ALTO | CONFIRMED | `web/app/shell.ts:988-990` interpola project_id em comentário Python. ID com LF introduziu exatamente um Call(print) adicional no AST convertido, sem execução (ui-probes.json). §§9.3/12.2/R-21/22/27 distinguem exportação de importação passiva. | Contenção e saneamento no consumidor F8, depois I/O canônico e teste AST do download. |

Nenhum dos seis achados ativos foi descartado. Não há DISPUTED_WITH_EVIDENCE entre os achados ativos, pois o código de produção é idêntico ao auditado e as reproduções procedem.

## Matriz histórica, sem dupla contagem

A revisão 2 também menciona os quinze achados antigos. Para um **desvio atual** já inexistente, DISPUTED_WITH_EVIDENCE abaixo concorda com a conclusão CORRIGIDO do auditor, sem disputar o relatório. Não se criam tarefas duplicadas para pontos já resolvidos.

| IDs | Classificação do desvio atual | Evidência técnica preservada |
|---|---|---|
| AUD-001 | DISPUTED_WITH_EVIDENCE | `web/worker/pyodide_worker.ts:989-1025` exige runtime/ponte/entrypoint reais; indisponibilidade não gera solução. Provas: `tests/unit/f7/rpc_remediation.test.ts:25,47,109` e `tests/wasm/test_real_runtime.py:77` (`test_unstabilizable_plant_through_real_rpc`). |
| AUD-002 | DISPUTED_WITH_EVIDENCE | `web/worker/pyodide_worker.ts:1007-1025` importa core.rpc em vez de calcular resultado fixo; `control_lab/core/rpc.py:1954` faz dispatch. `tests/wasm/test_real_runtime.py:13` confronta CARE12x3 CPython/Pyodide. Confirmação independente do CI D/G: relatório externo, linha 94. |
| AUD-003 | CONFIRMED, parcial | Build/locks reais em scripts/build_release.py; regressão Job B é AUD-016; E/G bloqueados são controles a preservar. |
| AUD-004 | DISPUTED_WITH_EVIDENCE | `web/worker/service_worker.ts:195-210,284-291` verifica hash antes de entregar cache; `tests/security/offline_browser.py:49::test_offline_real_calculation_after_reload` verifica recarga e cálculo reais. |
| AUD-005 | DISPUTED_WITH_EVIDENCE | `control_lab/core/tensors.py:534::readonly_copy`, getters de models.py e revisões monotônicas; `tests/unit/f1/test_core_rpc_and_immutability.py:167::test_arrays_cannot_change_model_revision_content` e `:316::test_with_revision_monotonicity_and_metadata_only_rules` tentam mutações e revisões inválidas. |
| AUD-006 | DISPUTED_WITH_EVIDENCE | `control_lab/optimization/modeling/canonical.py:45-73` mantém bytes/shape e bloqueio estrutural; `tests/oracles/test_sdp_remediation_independent.py:40::test_f9_sdp_snapshot_survives_input_getter_and_structure_mutation` confronta F0+F1=diag(3,4) e JSON invariável após mutações. |
| AUD-007 | DISPUTED_WITH_EVIDENCE | `control_lab/optimization/modeling/canonical.py:130,143` usa tolerância diagonal zero; backend scipy_linprog.py:72 recusa bloco não diagonal. `tests/oracles/test_sdp_remediation_independent.py:86::test_f9_any_nonzero_off_diagonal_prevents_exact_lp` verifica até nextafter(0,1); determinante exato −ε²<0 não autoriza LP. |
| AUD-008 | DISPUTED_WITH_EVIDENCE | `control_lab/optimization/verification/verifier.py:184-186` usa norma espectral 2. `tests/oracles/test_sdp_remediation_independent.py:101::test_f9_spectral_residual_matches_diagonal_analytic_values` confronta diag(100,100,−1), resíduo 1/101. |
| AUD-009 | DISPUTED_WITH_EVIDENCE | `control_lab/fuzzy/fml.py:88,116,148,527` valida operadores/formas; `tests/oracles/test_fml_remediation_independent.py:70::test_f9_fml_invalid_semantics_are_not_repaired` e `:74::test_f9_fml_roundtrip_matches_analytic_partition` rejeitam entrada incompatível e confrontam partição analítica. |
| AUD-010 | DISPUTED_WITH_EVIDENCE, escopo original | `tests/wasm/test_real_runtime.py:13`, `tests/e2e/test_revision_recovery.py:6,20,43` e `tests/security/offline_browser.py:49` exercitam runtime/revisões/recovery/offline; confirmação independente CI no relatório externo:102. Isso não demonstra download DOM; AUD-019/020/021 permanecem confirmados. |
| AUD-011 | CONFIRMED, parcial | Produtor F1 verificado, consumidor F8 incorreto: encaminhamento AUD-019/020, sem reabrir algoritmo correto. |
| AUD-012 | CONFIRMED, parcial | Ownership textual conforme; proteção servidor ausente: AUD-018. |
| AUD-013 | CONFIRMED, parcial | Handoffs existem; parser/governança e produto integrado pendentes: AUD-016/019/020. |
| AUD-014 | DISPUTED_WITH_EVIDENCE | `scripts/run_web_tests.mjs:288,433` exige compilador e executa testes Node. Relatório externo:33,106 confirma TS5.8.3/50 testes e CI C; `tests/integration/test_run_web_tests_fail_closed.test.mjs:185::test_acceptance_runner_requires_tsc_and_tests` testa as falhas de compilação/ausência. |
| AUD-015 | DISPUTED_WITH_EVIDENCE | `scripts/run_web_tests.mjs:288,419` falha fechado sem compilador ou testes. `tests/integration/test_run_web_tests_fail_closed.test.mjs:185::test_acceptance_runner_requires_tsc_and_tests` testa esses caminhos; resultado local desta rodada: oito testes Node aprovados. |

Os números de linha de produção/histórico referem-se à base 50ba04d. A correção desta rodada altera apenas governança F9; as referências históricas de browser são inspeção de código e confirmação da auditoria externa, não alegação de nova execução desses browsers nesta sessão.

## Escalonamento e condicionamento

Sete pacotes novos têm prioridade máxima. Ordem de pré-requisitos: governança F9 → testes/contratos F1 → contenção/consumidores F8 → E2E F9. A proteção de servidor é um pacote F9 separado com bloqueio externo, para não tornar uma correção local impossível de concluir nem simular enforcement. A contenção F8 não depende da implementação RPC: pode ser executada assim que a F9 terminar, embora a fila ordene as frentes como solicitado.

- WP-AUDIT2-FIX-F9-GOV: AUD-016.
- WP-AUDIT2-FIX-F9-PROTECTION: AUD-018, depende de ação do responsável/servidor.
- WP-AUDIT2-FIX-F1-OPTIONAL-SDP-TEST: AUD-017.
- WP-AUDIT2-FIX-F1-IO-RPC: fornecedor de contrato para AUD-019/020/021.
- WP-AUDIT2-FIX-F8-CONTAIN-EXPORT: contenção AUD-020/021.
- WP-AUDIT2-FIX-F8-NATIVE-IO: resolução integrada AUD-019/020/021.
- WP-AUDIT2-FIX-F9-DOWNLOAD-E2E: prova final dos artefatos entregues ao usuário.

G-0C/G-0D mantêm status PENDING e recebem bloqueadores da UI. G-0B mantém indisponibilidade Wasm factual. A proteção ausente impede liberação estável. O aceite anterior F8 de compilação/testes locais é preservado em seu escopo, mas recebe integration_status=CONDITIONED_BY_AUDIT2 e novos bloqueadores; o WP histórico de produto F8 continua reaberto. F1/F5/F6 e adaptadores PathView corretos não são reabertos.

Três aceites históricos CPython anteriores ao formato de handoff recebem registro explícito `legacy_cpython_local.v1` com caminhos de testes existentes e exclusão de release; não se inventa um novo parecer retrospectivo. O validador novo exige esse registro/evidência, sem contagem fixa de tarefas, e exige dossiê completo para os corretivos. Limites globais pendentes em um dossiê aceito localmente não são reinterpretados como falha do checklist daquele escopo.

## Execução desta rodada

O primeiro pacote selecionado é WP-AUDIT2-FIX-F9-GOV. O pacote foi corrigido e aceito no escopo de governança local: 265 testes Python e oito Node aprovados, zero skipped. Os testes/handoff e a identidade da base estão registrados em `docs/audits/handoffs/WP-AUDIT2-FIX-F9-GOV.md`. Os outros seis pacotes permanecem PENDING. Não há push nem configuração remota; E/G continuam bloqueados enquanto os requisitos não forem demonstrados.
