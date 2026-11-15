# WP-AUDIT2-FIX-F9-GOV — handoff e parecer F9

## 1. Contrato da tarefa

- WorkPackage ID: WP-AUDIT2-FIX-F9-GOV; Frente F9 (`f9-integration-qa`); requisitos R-23/R-24, §§10.5/13.11/15.2 e Apêndice E do CL-DIR-001.
- Achado: AUD-016 da Auditoria 2. Base auditada: `50ba04d16633e9cd96c3b90a7668466c30ee9ca7` (produção idêntica a 60d5c5c8cd49d7a91b4d7d77b94582182565df59).
- allowed_paths: scripts/, tests/integration/, docs/audits/, docs/architecture/, PROJECT_STATE.json; todos F9 no CODEOWNERS. Nenhum módulo produtor foi alterado.
- Contratos consumidos: PROJECT_STATE, evidência Markdown Appendix E e contratos existentes de status/gates; saída: validação ou GovernanceError explícito. Não há alteração de contrato F1/F7/F8.
- Hipótese matemática: nenhuma nova operação científica. Limite: validade estrutural/evidencial do registro não demonstra conformidade científica, proteção do servidor nem execução browser.
- Dependências: nenhuma. Bloqueadores deste escopo: nenhum. Bloqueadores do produto: AUD-017..021 e gates pendentes, explicitamente registrados.
- Fixtures: somente leitura; oito arquivos de contracts/fixtures/ e todos os oráculos, produção e norma comparados byte a byte com a base (112 arquivos ao todo).
- Risco: aceitar um registro sem evidência ou confundir aceite local com release. Mitigação: regressões negativas e escopo explícito. Maturidade pretendida: governança local validada; produto não estável.
- Evidência/PR esperado: diff local atômico, parecer de triagem completo, fila corretiva, logs e manifesto de fontes; sem publicação remota.

## 2. Alteração e aceite

O teste antigo falhou na base por exigir vereditos históricos e contagens fixas. O novo validador permite evolução factual e crescimento da fila, mantendo identidade de pacotes, aciclicidade, referências, decisão explícita, evidência e dez itens obrigatórios. Aceita os formatos reais de handoff sem exigir cabeçalhos numéricos particulares. Três registros CPython antigos sem handoff recebem migração legada explícita e limitada, preservando dívida de release.

Comando de acceptance_cmd executado no venv core_no_sdp travado:

```sh
python3 scripts/ci_math.py core_no_sdp --reports docs/audits/audit2/evidence/core && node --test tests/integration/*.test.mjs
```

Resultado: **265 passed, zero skipped**, perfil sem Clarabel/CVXPY verificado pelo runner; **8 testes Node passed, zero skipped**. Logs: `docs/audits/audit2/evidence/acceptance-core.log`, `acceptance-node.log`; JUnit e resumo JSON em `evidence/core/`. A revalidação final do estado aceito fica em `evidence/governance-final.log`.

A execução SDP que reproduziu AUD-017 falha como esperado e foi preservada em `AUD-017-sdp-before.log`; não faz parte do aceite deste pacote, e será corrigida exclusivamente pela F1 no pacote seguinte. Não se ocultou essa falha nem se mudou o algoritmo correto.

## 3. Checklist de Handoff — Apêndice E

| Item | Pergunta | Resposta | Evidência | Veredito |
|---|---|---|---|---|
| 1 | API/contrato aprovado e fornecido aos consumidores? | SIM, escopo F9 | validate_state/validate_handoff_text usados pelos testes de integração; sem novo RPC nem contrato produtor; docs/architecture/GOVERNANCE_VALIDATION_v1.md. | CONFORME |
| 2 | Status, diagnóstico, proveniência e falhas? | SIM | Erros GovernanceError explícitos; estado conserva escopos/bloqueios e base SHA; regressões negativas para evidência ausente, ciclos e gate indisponível. | CONFORME |
| 3 | Testes analíticos antes de otimização? | SIM | AUD-016-before.log reproduz falha original; novos casos sintéticos com expectativas lógicas independentes; nenhuma otimização numérica. | CONFORME |
| 4 | Confronto independente, sem autorreferência? | SIM, com limite de processo | Relatório externo integral, norma textual de dez itens e casos negativos construídos manualmente; revisão F9 sequencial nesta plataforma, sem alegar outro agente ou humano independente. | CONFORME |
| 5 | Ownership e ausência de adulteração? | SIM | Diff limitado a F9/estado; unchanged-source-sha256.json confronta 112 arquivos com Git HEAD, incluindo oito fixtures; nenhuma tolerância ou esperado científico mudou. | CONFORME |
| 6 | CPython/Pyodide no domínio anunciado? | N/A para script de governança host | Execução CPython no Job B; não é módulo de produto Wasm. Nenhuma paridade nova anunciada, gates Wasm mantidos. | N/A |
| 7 | Schema versionado/migração e revisão? | SIM | Validador v1 documentado; extensão aditiva dos registros e migração explícita legacy_cpython_local.v1; nenhum schema científico/RPC alterado. | CONFORME |
| 8 | Logs, matrizes e benchmarks? | SIM no escopo | Logs antes/depois, JUnit/JSON core e hashes anexos em docs/audits/audit2/evidence/; nenhuma matriz ouro ou benchmark científico novo necessário para parser/estado. | CONFORME |
| 9 | Experimental classificado? | N/A, sem método científico novo | Docs e estado negam promoção de método/produto; não há alteração visual nem algoritmo experimental nesta entrega. | N/A |
| 10 | Limitações com issue/mensagem? | SIM | Sete WPs da Auditoria 2 cadastrados; seis ainda PENDING; proteção externa e exportações defeituosas mantêm release bloqueado. Falhas lógicas geram diagnóstico explícito. | CONFORME |

## 4. Rastreabilidade normativa e bloqueios

T-PVM-01/02, T-UI-01 e T-SEC-01 recebem apenas guards de governança nesta entrega: evidência parcial não equivale a aceite integrado. Não foram executados novos cenários browser/download desses T-*. AUD-019/020/021 exigem produtor canônico F1, contenção/consumo F8 e prova final F9 dos bytes baixados. G-0C/G-0D continuam pendentes; G-0B mantém a indisponibilidade factual. AUD-018 continua exigindo ação/capacidade de servidor.

## 5. Parecer Independente

- Revisor independente: papel `f9-integration-qa`, em revisão sequencial explicitamente autorizada na plataforma externa; sem invocação de subagente e sem alegação de segregação física da autoria.
- Commit SHA auditado: `50ba04d16633e9cd96c3b90a7668466c30ee9ca7` mais o diff local identificado neste handoff (o SHA do commit resultante é fornecido na entrega).
- Data (UTC): 2026-11-15.
- Veredito F9: accepted
- Escopo: governança local da Auditoria 2 e correção exclusiva AUD-016; não constitui aceite de produto, CI remoto, proteção GitHub ou solução dos outros cinco achados.

Os dez itens foram revisados contra o Apêndice E, diff, testes e hashes. O pacote pode receber ACCEPTED_BY_F9 somente neste escopo; nenhum gate global é promovido. Commit local para PR, sem push.
