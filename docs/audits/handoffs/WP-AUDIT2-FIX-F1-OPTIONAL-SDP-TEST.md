# Dossiê F9 — WP-AUDIT2-FIX-F1-OPTIONAL-SDP-TEST

## Cabeçalho

| Campo | Evidência |
|---|---|
| Frente, requisitos e achado | F1, R-02, R-19, R-20 e R-21, AUD-017. |
| Escopo | Testes de regressão do despacho RPC real, em CPython nos perfis core_no_sdp e sdp_available. Caminhos autorizados: control_lab/core/, control_lab/diagnostics/ e tests/unit/f1/. |
| Contrato e dados | optimization.solve recebe SDP canônico B1 ou planta A, B, taxa α e sinal de D1. optimization.verify recebe solução primal e certificado dual. Ambos devolvem o envelope RPC v1. |
| Hipótese | Caso B1 tem ótimo analítico de fronteira. D1 exige Q definida positiva e autovalores de malha fechada à esquerda de −α. |
| Dependência | WP-AUDIT2-FIX-F9-GOV, ACCEPTED_BY_F9. |
| Testes e fixture | pytest tests/unit/f1/ -v, T-SDP-B1 e T-SDP-D1, B-SDP-A-D.json. |
| Risco e maturidade | Risco de confundir ausência de solver com falha de descoberta. O teste identifica Clarabel independentemente do despacho. Aceite restrito a CPython local. A maturidade Web depende de WP-AUDIT-FIX-F9-WASM-GATES. |

## Checklist do Apêndice E

| Item | Evidência examinada pela F9 |
|---|---|
| 1. Contrato compartilhado | O teste envia a requisição real ao dispatcher e valida a resposta por rpc_response.schema.json, contrato já disponível para F7/F8. |
| 2. Status, diagnóstico e proveniência | Schema aplicado em ambos os perfis. No perfil core, status failure, erro SOLVER_UNAVAILABLE e result nulo. No perfil SDP, success, solver_status optimal e verificação independente. A suíte F1 cobre os campos de proveniência. |
| 3. Testes analíticos | B1 confronta x e objetivo com −1. D1 verifica positividade de Q e espectro com ganho reconstruído de Q e Y. Este pacote só modifica teste. |
| 4. Confronto independente | optimization.verify recebe as variáveis primais e duais, recalcula o certificado e fornece resíduos de cone primal, cone dual, estacionariedade e gap. A F9 também executou a suíte de fixtures com o oráculo independente. |
| 5. Ownership e integridade | O diff produtor afeta apenas tests/unit/f1/test_core_rpc_and_immutability.py. git diff HEAD -- contracts/fixtures tests/oracles está vazio. Não há mocks nem skips nos dois novos casos. |
| 6. Domínio anunciado | Dois ambientes CPython reais. Pyodide está fora do aceite local deste pacote, com gate Web registrado separadamente. |
| 7. Schemas | N/A. Diff restrito ao teste consumidor. |
| 8. Logs e matrizes | Saídas integrais e versões em docs/architecture/audit-logs/WP-AUDIT2-FIX-F1-OPTIONAL-SDP-TEST.log. Matrizes em contracts/fixtures/B-SDP-A-D.json. Sem objetivo de desempenho. |
| 9. Método experimental | N/A. Sem mudança de método, interface ou rótulo de maturidade. |
| 10. Limitações | AUD-017 registra a distinção dos perfis. A ausência de Clarabel precisa produzir SOLVER_UNAVAILABLE sem ganho. Execução em navegador permanece sujeita ao WP de gates Wasm. |

## 5. Parecer independente

- Revisor independente: f9-integration-qa
- Commit SHA auditado (base): af8ef6c42489a8361c6a2e33384c08066a560139
- Blob Git do teste auditado sobre a base: 8f41d59e4816ff9edcd1b499ea39b327b7c1d7ff
- Data (UTC): 2026-11-15
- Resultado por perfil: 88 testes F1 aprovados, incluindo B1 e D1, e 12 testes da suíte de fixtures aprovados. Zero skips.
- Parecer F9: accepted
