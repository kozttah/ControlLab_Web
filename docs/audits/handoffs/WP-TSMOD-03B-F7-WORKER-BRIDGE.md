# WP-TSMOD-03B-F7-WORKER-BRIDGE — Auditoria independente F9

- **Parecer F9:** accepted
- **Revisor independente:** `f9-integration-qa`
- **Commit base auditado:** `525c82362d3c0f1f5daca2b47461ed75ea8f8623`; candidato identificado pelos hashes abaixo.
- **Data UTC:** 25/11/2026
- **Escopo:** R-18, R-20 e R-21 do CL-DIR-001 e a fronteira RPC, Worker e arquivos do T-TSMOD-07 do CL-TS-MOD-DIR-001 v1.1.0. T-RPC-01, T-RPC-02 e T-SEC-01 foram reexecutados.

## Evidências reproduzíveis

O comando de aceite `npm --prefix web run test:unit:f7 && npm --prefix web run build` passou com **82 testes F7** e integridade verificada dos **42 ativos locais**. A suíte web completa passou com **167 testes**. O alias `test:unit:f7` usa o executor pré-existente com `--scope f7` e foi acrescentado à configuração de testes sob ownership F9.

A suíte `tests/wasm/test_ts_modeling_worker.py` passou com **9 testes em cada navegador**, Chromium 153.0.8010.0 e Firefox 153.0, com Pyodide e Worker de produção. A matriz reconstrói uma planta afim de dois estados a partir de quatro configurações (setor, TPMT, FEMT Kuhn–Freudenthal e FEMT Delaunay). O oráculo fornece (A(x)) e (B(x)) analíticos em quatro pontos fixos do domínio ([-1,1]^2). Os modelos e envelopes seguem os schemas existentes, e a mesma comparação é executada em CPython.

| Caso | Erro máximo no Worker em ambos os navegadores | Erro máximo em CPython |
| --- | ---: | ---: |
| Setor | `4.441e-16` | `4.441e-16` |
| TPMT | `4.885e-15` | `7.550e-15` |
| FEMT Kuhn–Freudenthal | `3.997e-15` | `1.776e-15` |
| FEMT Delaunay | `3.997e-15` | `2.665e-15` |

Os testes confirmam o round-trip integral em `.ctrlab` para os quatro modelos, a geração passiva de PathSim e os scripts de derivação Python e MATLAB por valor e por referência registrada. O limite de recursos rejeita grades acima do envelope e receitas de reconstrução excessivas antes do cálculo. A resposta informa como reduzir a grade ou seguir com a derivação offline. Os estágios de progresso são monotônicos, de `validating` a `computing` e `completed` em operações bem-sucedidas.

O ensaio de cancelamento inicia uma FEMT de 301 × 301 nós depois de confirmar a revisão 3. A revisão 4 retorna `CANCELLED` sem gravar estado. Com COOP/COEP e memória compartilhada, o Worker permanece o mesmo e a operação concorrente de outro projeto termina com sucesso. Sem isolamento, como no GitHub Pages, o prazo de graça pode levar à recuperação por reinício. Nos ensaios dessa configuração, o Worker reiniciou e o cliente executou com sucesso a próxima solicitação. Em ambos os modos, o contador de PyProxy ficou em zero após o teste.

Em Chromium real, **6 testes adicionais passaram** em `tests/e2e/test_revision_recovery.py` e `tests/security/test_real_browser_security.py`. Eles verificam 20 revisões concorrentes, recuperação do snapshot confirmado, separação entre prévia e commit, cálculo offline real após provisionamento, passividade de arquivos e CSP do artefato. A síntese PDC pela UI faz parte da integração T-TSMOD-07 prevista para os próximos pacotes.

## Checklist de handoff do Apêndice E

| Item | Evidência | Veredito |
| --- | --- | --- |
| 1 | Cinco operações tipadas exercitadas através do cliente real e validadas contra os contratos RPC e TS. O cliente expõe `supportsTsModeling` para consumo tipado pela F8. | CONFORME |
| 2 | Sucesso com identificação, diagnósticos e proveniência. Falhas tipadas por limite de recursos e cancelamento. Verificação separada da etapa de progresso. | CONFORME |
| 3 | Plantas afins com solução analítica no domínio definem o aceite numérico. | CONFORME |
| 4 | Confronto dos modelos reconstruídos contra as equações explícitas de `A(x)` e `B(x)`. Navegadores reais usam o Worker de produção. | CONFORME |
| 5 | Implementação limitada a `web/bridge/` e `web/worker/` e testes da F7 em `tests/unit/f7/`. F9 acrescentou o alias em `web/package.json` e o oráculo em `tests/wasm/`. Sete hashes de fixtures ouro conferidos e tolerâncias existentes intactas. | CONFORME |
| 6 | As quatro reconstruções analíticas foram verificadas em CPython e em Pyodide real nos dois navegadores. | CONFORME |
| 7 | A validação manteve o schema RPC v1.0 e o schema TS existentes e comprovou restauração integral de modelos. | CONFORME |
| 8 | Comandos, casos, versões, métricas e hashes do build e dos arquivos revisados constam neste parecer. | CONFORME |
| 9 | Exemplos simulados trazem proveniência de mock e marcação explícita `verified: false`. | CONFORME |
| 10 | O guard retorna limites acionáveis. A interrupção cooperativa depende de checkpoints do runtime e de isolamento. Os testes cobrem a via de recuperação sem memória compartilhada. O fluxo de interface e síntese será examinado por `WP-TSMOD-04` e `WP-TSMOD-05`. | CONFORME |

## Integridade do candidato

```text
94bdf236c7d9cdfc6ce7ca5a8a7646ab9aac966a2861ec3d53bac0bede862435  tests/unit/f7/ts_modeling_client.test.ts
3a695d2b9f31932a35c32f3a14dd1267bcc5802ae9a7449a576a3f2f018dda8a  tests/unit/f7/ts_modeling_worker.test.ts
e882eed202d1c796d8eb7b25f8710b74954e36a0b6528c0d1e799ef9cb41d68c  tests/wasm/test_ts_modeling_worker.py
799e8a937dced3787d2feb5c091317ea35bd3b851b981303a8867e82f4283c60  web/bridge/client.ts
8df9f2eb93341a133ec184f4e43ed4ad56e343975e0e8ff972dcf5a2bd3d44e3  web/bridge/mock_adapter.ts
56b354f6b725d0d82ee198f347636a38893c1bb90c76a9378014ac1b8d41c946  web/bridge/mock_ts_modeling.ts
48511b5316802fe292df2e1fc8e4f01fa4a3fb5c906280399ad4326f01a2af47  web/bridge/pyodide_client.ts
e5e03efc4e4706c258acd8c36f6b464280b80b0fa1ba863536152a0230d2a7e9  web/bridge/ts_modeling.ts
f85e74e4d3076d81491d49da2de03d0714918c5f4b69bf1aff32d3d26c0e96cc  web/package.json
b7aebe5cf2ce2efdb46264d3410951b5582ec77be30cf1ba256869a4196363d8  web/worker/payload_references.ts
3e6fc32a57753c03e7fd480c1dbae3418203ea5a972d9492f644105fc948c540  web/worker/pyodide_worker.ts
d6472f80d22debe19d0d5d490392e827c6ce33d6d7fdd78bd7d126951b8d319b  web/worker/ts_modeling_envelope.ts
79e56250d3746748780b53d329c919ec1f939a46a856c3ee56ca79028e6e4963  web/dist/release-manifest.json
d9ca767a8d8d8f1459a32afb787d372534fcfbbc1cefc17332c0a2da3192295f  web/dist/worker/pyodide_worker.js
```
