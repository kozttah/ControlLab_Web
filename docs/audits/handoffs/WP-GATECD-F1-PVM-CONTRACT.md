# Handoff F9 — WP-GATECD-F1-PVM-CONTRACT

## 1. Cabeçalho

Frente F1, requisitos R-02/R-04/R-20/R-21, CL-DIR-001 Seções4,9,14.1 e Apêndices C–E. Dependência WP-AUDIT2-FIX-F1-IO-RPC aceita. Caminhos permitidos da entrega control_lab/io/ e tests/unit/f1/.

- Contratos: RPC1.0, StateSpace, StateFeedbackController/DynamicController e PVM1.0.0.
- Entradas/saídas: planta, controlador e configuração de saturação → Result e bytes PVM passivos.
- Hipóteses: dimensões compatíveis e loop algébrico bem posto para ambos os sinais; limite desta tarefa: contrato CPython.
- Fixtures: matrizes analíticas no teste e ouro existente intacto; bloqueadores deste contrato: nenhum.
- Evidência esperada: logs/hashes abaixo; risco: sinais e feedthrough mitigados por derivação independente; maturidade: beta sem promoção global.

## 2. Implementação e aceite

O backend canônico existente suporta as duas classes de controlador e saturação. Esta entrega amplia regressões RPC e troca a alegação global de gate pendente por identificação do gate de validação e escopo por arquivo. A importação permanece passiva.

Comando de aceite pytest tests/unit/f1/ -v. Produtor aprovou101 testes e o revisor repetiu101 testes, ambos sem skips. Python do ambiente /workspace/scratch/ba21e63c86f4/f9-ci-sdp/bin/python.

## 3. Checklist do Apêndice E

| Item | Critério | Resposta | Evidência | Veredito |
| --- | --- | --- | --- | --- |
| 1 | API e consumidores | SIM | Contrato RPC1.0 io.export_pvm e core.validate_interconnection preservado. Teste RPC cobre controladores estático/dinâmico e saturação off/on. | CONFORME |
| 2 | Status e proveniência | SIM | Warning EXTERNAL_PATHVIEW_NOT_VERIFIED e external_pathview_verified=False preservam a condição de cada arquivo. validation_gate/validation_scope são metadados extensíveis. | CONFORME |
| 3 | Testes analíticos | SIM | Matriz aumentada derivada por eliminação escalar com Dp=.4, Dc=.3 e ambos os sinais. Dc=2.5/sinal positivo rejeita loop singular. | CONFORME |
| 4 | Confronto independente | SIM | Revisor F9 repetiu101 testes, inspecionou derivação analítica e não alterou o produtor. O ensaio externo dos downloads UI será fechado no WP-GATECD-F9-E2E. | CONFORME |
| 5 | Ownership e ouro | SIM | Diff produtor restrito a control_lab/io/pvm.py e tests/unit/f1/test_io_ctrlab_and_pvm.py. Fixtures ouro e tolerâncias não foram modificadas. O teste aditivo de manifesto F9 em tests/oracles pertence a outra frente, não ao produtor F1. | CONFORME |
| 6 | Domínio CPython/Pyodide | SIM | Aceite deste contrato em CPython, com os mesmos adaptadores disponíveis no wheel. O gate de integração Pyodide da UI é responsabilidade do WP-GATECD-F9-E2E. | CONFORME |
| 7 | Schemas | SIM | Sem alteração de schema publicado. Metadados próprios do ControlLab usam campos extensíveis. PVM continua version1.0.0. | CONFORME |
| 8 | Logs e matrizes | SIM | Logs completos f1-producer.log e f1-review.log em docs/audits/gatecd. Matrizes e referências analíticas estão no teste novo. | CONFORME |
| 9 | Maturidade | SIM | Sem promoção de solver ou método experimental. A anotação do arquivo informa execução externa específica ainda requerida. | CONFORME |
| 10 | Limitações | SIM | Esta revisão de contrato não equivale ao fechamento global de G-0D. Saturação/dinâmica via UI e trajetória PathView/PathSim pertencem ao pacote de E2E. | CONFORME |

## 4. Identidade e limites

Aceite limitado ao contrato e às regressões CPython. A integração browser é verificada separadamente pelos pacotes de UI e E2E.

- SHA-256 de control_lab/io/pvm.py — b085546e2ba9684351d3a8ccbff4f50d664c17b63dae2c4cb962ee09c7994aca
- SHA-256 de tests/unit/f1/test_io_ctrlab_and_pvm.py — fbbc3b7d7a2651ef842bfb517b8a318e851506ae1571ef569ae035fd313d5828

## 5. Parecer independente

- Revisor independente: /root/f9_gate_review
- Produtor: /root/f1_gate_close
- Commit SHA auditado (base): 58d101d2d3296026af39c388f799e5577e38b027, acrescido dos arquivos identificados acima.
- Data (UTC): 2026-11-17
- Parecer F9: accepted
- Escopo de aceite: cpython_canonical_pvm_rpc_contract
