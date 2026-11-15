# Dossiê F9 — WP-AUDIT2-FIX-F1-IO-RPC

## Cabeçalho da tarefa

| Campo | Evidência |
|---|---|
| Frente e requisitos | F1, R-02, R-19, R-20 e R-21. Suporte à remediação dos achados de integração AUD-019 a AUD-021. |
| Caminhos autorizados da F1 | control_lab/core/, control_lab/io/, control_lab/diagnostics/, tests/unit/f1/ e propostas em contracts/schemas/. |
| Contrato e entradas | RPC 1.0. io.export_pvm recebe planta canônica, controlador e cenário opcionais. io.export_ctrlab recebe projeto serializado. io.import_pvm e io.import_ctrlab recebem o conteúdo em bytes_base64. |
| Saídas | Exportação fornece bytes em base64, tamanho, SHA-256 e MIME. Importação devolve projeto ou documento com diagnósticos, avisos, proveniência e erro tipado no envelope RPC existente. |
| Hipóteses e limite | Os adaptadores nativos aprovados determinam a semântica e o formato. O pacote habilita a fronteira RPC em CPython. F8 e F9 ainda precisam testar os downloads e a reabertura pelo produto Web. |
| Testes, fixtures, dependências | pytest tests/unit/f1/ -v. T-IO-01, T-IO-02, T-PVM-01, T-PVM-02. B-PVM-LQR, oráculos independentes. WP-AUDIT2-FIX-F9-GOV e WP-AUDIT2-FIX-F1-OPTIONAL-SDP-TEST aceitos. |
| Risco e maturidade | A perda de realimentação, bytes ou metadados no transporte seria um defeito de interoperabilidade. Aceite CPython local com bloqueios de integração F8/E2E registrados em PROJECT_STATE.json, sem promoção de maturidade Web. |

## Checklist do Apêndice E

| Item | Evidência |
|---|---|
| 1. Contrato | A F9 aprovou contracts/schemas/io_rpc.schema.json v1.0.0 para consumo por F7/F8. Os testes validam requisições e respostas dos quatro métodos tanto contra o envelope comum como contra FileBytes, ImportedPvm ou ImportedCtrlab. |
| 2. Status e proveniência | Os testes confrontam avisos e diagnósticos do adaptador oficial, erros tipados e result nulo. A exportação e importação do projeto preservam project.provenance no manifesto. |
| 3. Ensaios analíticos | A suíte cobre estado aumentado, ganho estático e convenção de sinal. A F9 verificou adicionalmente a malha A−BK com matriz esperada explícita [[0,1],[-4,-3]] no PVM transportado. |
| 4. Confronto independente | A F9 leu o ZIP com zipfile, conferiu CRC, hashes, revisão, planta e controlador reabertos, e executou os oráculos matemáticos. A prova do transporte PVM usa tanto o grafo oficial como a matriz analítica. |
| 5. Ownership e integridade | O log registra os quatro arquivos de F1 e seus hashes Git. git diff HEAD -- contracts/fixtures tests/oracles e git diff --check retornaram zero. Novos testes estendem os existentes e preservam suas tolerâncias. |
| 6. Domínio | CPython nos perfis core e SDP. Pyodide, PathView externo e os botões Web ficam a cargo dos pacotes de integração e dos gates registrados. |
| 7. Revisão e migração | O schema adicional tem identificador versionado e estende o envelope RPC 1.0 com operações novas. Nenhum esquema persistido ou operação existente mudou de formato. A F9 revisou e aprovou a proposta com a inclusão de proveniência. |
| 8. Logs | docs/architecture/audit-logs/WP-AUDIT2-FIX-F1-IO-RPC.log contém ambiente, saídas integrais, fonte da prova F9 e identidades do código. A fixture B-PVM-LQR fornece a referência física. Benchmark de desempenho não integra este aceite. |
| 9. Métodos experimentais | Sem alteração de classificação visual ou solver. Avisos do adaptador e resultados de importação passiva seguem pelo RPC. |
| 10. Limitações | AUD-019, AUD-020 e AUD-021 seguem vinculados aos WPs do consumidor Web. O transporte verifica limites, integridade e códigos de erro, sem extrair arquivos em disco. |

## 5. Parecer independente

- Revisor independente: f9-integration-qa
- Commit SHA auditado (base): 7d5ecb19671574172e7bfcb31cbdf6bef47b63e9
- Data (UTC): 2026-11-15
- Resultados em cada perfil: 97 testes F1 e 16 testes de oráculos aprovados, sem skips. Provas adicionais de malha fechada, transporte e reabertura foram aprovadas.
- Parecer F9: accepted
