# Reavaliação independente F9 dos sete baselines — 2026-11-17

Fonte CL-DIR-001, Apêndices C/E, ADR-009/010. Base `9161586a554debd144c6861464e7b8f6f4534953`, mais diff do teste de portabilidade em WP-CI-F9-FIXTURE-PORTABILITY. Revisor `/root/f9_baseline_reassessment`, sem autoria de implementação científica nesta rodada.

## Parecer individual

| WorkPackage | Decisão F9 | Handoff individual |
| --- | --- | --- |
| `WP-00-F9-BOOTSTRAP` | `accepted` | [WP-00-F9-BOOTSTRAP-reassessment-2026-11-17.md](WP-00-F9-BOOTSTRAP-reassessment-2026-11-17.md) |
| `WP-01-F1-CORE-MODELS` | `accepted` | [WP-01-F1-CORE-MODELS-reassessment-2026-11-17.md](WP-01-F1-CORE-MODELS-reassessment-2026-11-17.md) |
| `WP-03-F6-SDP-MODELING-AND-GATE0B` | `accepted` | [WP-03-F6-SDP-MODELING-AND-GATE0B-reassessment-2026-11-17.md](WP-03-F6-SDP-MODELING-AND-GATE0B-reassessment-2026-11-17.md) |
| `WP-04-F7-RPC-BRIDGE-WORKER` | `accepted` | [WP-04-F7-RPC-BRIDGE-WORKER-reassessment-2026-11-17.md](WP-04-F7-RPC-BRIDGE-WORKER-reassessment-2026-11-17.md) |
| `WP-06-F8-UI-MVP-LQR` | `accepted` | [WP-06-F8-UI-MVP-LQR-reassessment-2026-11-17.md](WP-06-F8-UI-MVP-LQR-reassessment-2026-11-17.md) |
| `WP-09-F5-FUZZY-FML-ANFIS` | `accepted` | [WP-09-F5-FUZZY-FML-ANFIS-reassessment-2026-11-17.md](WP-09-F5-FUZZY-FML-ANFIS-reassessment-2026-11-17.md) |
| `WP-10-F6-SDP-EDUCATIONAL-SOLVER` | `accepted` | [WP-10-F6-SDP-EDUCATIONAL-SOLVER-reassessment-2026-11-17.md](WP-10-F6-SDP-EDUCATIONAL-SOLVER-reassessment-2026-11-17.md) |

Os sete aceites têm domínio explícito e devem ser aplicados em ordem de dependências. Não editar status por mera inferência dos remediation_wps. A regressão CI do teste de igualdade exata foi auditada por revisor separado e confirmada nesta rodada por42 testes. O aceite bootstrap inclui esse diff, sem alegar execução remota nova. Maestro deve concluir os perfis CI locais antes de publicação; a execução remota anterior falha permanece fato histórico.

## Execuções novas

- Python120 aprovados em3.03s, sem skips, em [acceptance-python.log](../reassessment/acceptance-python.log). Distribuição bootstrap12, core15, modelagem29, FML56, educacional8. Um teste parametrizado pode cobrir vários itens A–D.
- Web53 aprovados, sem skips, incluindo tsc real, em [acceptance-web.log](../reassessment/acceptance-web.log). Execução única para F7 e F8.
- Sondas independentes e governança48 aprovadas em2.43s, em [independent-python.log](../reassessment/independent-python.log).
- Node21 aprovados em2.69s, em [independent-node.log](../reassessment/independent-node.log).
- Confirmação suplementar da correção CI42 aprovados em0.89s, em [ci-portability-confirmation.log](../reassessment/ci-portability-confirmation.log). Este número inclui12 testes bootstrap já contados nos120; não somar como casos distintos.
- `scripts/verify_fixtures.py` aprovou11 schemas,7 fixtures SHA-256 e4 exemplos; inventário [protected-sha256.json](../reassessment/protected-sha256.json), diff de fixtures vazio.
- `scripts/project_governance.py` aprovou estado original26/33; estado final deve ser novamente verificado pelo Maestro.

Ambiente Python3.12.14, NumPy2.3.5, SciPy1.17.0, pytest9.2.0, CVXPY1.9.3, Clarabel0.11.1, Node24.22.1. Python depende do target previamente provisionado `/workspace/scratch/ba21e63c86f4/testdeps`; a invocação foi `PYTHONPATH=... python3 -m pytest`. Ausência inicial de pytest no runtime padrão foi resolvida usando esse target sem alterar código, dependências versionadas ou testes. Houve uma tentativa de coleta com nome de arquivo inexistente `test_core_rpc_remediation_independent.py`, corrigida antes da execução real de48 testes; o erro de preparo não foi contado como teste executado. Aviso AnyIO/pytest10 é externo.

## Evidência consumida e limites

Esta rodada repetiu aceites/sondas CPython e Node. As provas Chromium/Firefox/Pyodide, gate SDP nativo e UI real são evidências existentes inspecionadas em [relatório dos gates](../RELATORIO_STATUS_GATES_FASE0.md), [revisão independente anterior](../gatecd/REVIEWER_FINDINGS.md) e seus logs; não são novas execuções atribuídas a este revisor. A tentativa browser nova do Maestro foi bloqueada no socket Chromium por EPERM ambiental e deve ser registrada separadamente, sem transformá-la em resultado científico falso.

F5 mantém aceite CPython/perfil FML suportado. Educacional mantém API experimental isolada e escopo local; backend nativo beta é promovido separadamente por ADR-010. MATLAB não foi executado. .ctrlab da tela exige workspace LQR confirmado, embora exportação .pvm dinâmica funcione antes de LQR. Hardware container DEC-OPEN-03 e eventos/multirate fora do domínio permanecem explícitos. Nenhum schema, fixture ouro, tolerância científica, implementação ou PROJECT_STATE foi alterado por este revisor. Pareceres históricos preservados.
