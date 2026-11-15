# Dossiê F9 — WP-AUDIT2-FIX-F8-CONTAIN-EXPORT

## Cabeçalho

| Campo | Evidência |
|---|---|
| Frente e requisitos | F8, R-02/R-19/R-20/R-21. Contenção de AUD-020 e AUD-021. Dependência WP-AUDIT2-FIX-F9-GOV aceita. |
| Ownership | web/app/, web/features/, tests/unit/f8/. Diff restrito a main.ts, shell.ts e ui_mvp_lqr.test.ts. |
| Entradas, contrato e saída | Ação de exportação PVM a partir de um estado da UI. Sem artefato em qualquer estado. O guard de exportação protege a revisão e, para estado elegível, o shell emite erro tipado UNSUPPORTED_MODEL. |
| Hipótese, limite e maturidade | O gerador TypeScript paralelo foi removido. O pacote contém o risco até a adoção do adaptador oficial. Sem alegação de equivalência matemática do download Web ou de abertura externa no PathView. |
| Aceite e evidências | Typecheck e runner F8, T-PVM-01/T-IO-02 tratados por contenção na fronteira de exportação e sem mudança dos serializadores F1. Log completo em docs/architecture/audit-logs/WP-AUDIT2-FIX-F8-CONTAIN-EXPORT.log. |
| Risco e continuidade | Prematura reativação do download. O botão tem aviso e bloqueio, e a chamada direta também falha. Integração: WP-AUDIT2-FIX-F8-NATIVE-IO. |

## Checklist do Apêndice E

| Item | Verificação F9 |
|---|---|
| 1. API/consumidores | O método público exportPvm retorna never e o único handler trata o erro sem abrir modal com payload PVM. O novo RPC de I/O está reservado ao próximo pacote. |
| 2. Status e diagnóstico | O botão apresenta indisponibilidade acessível via disabled, aria-disabled e aria-describedby. Commit válido recebe UNSUPPORTED_MODEL. Nenhum resultado científico ou proveniência é inventado. |
| 3. Testes analíticos | N/A neste pacote de contenção. O teste específico cobre CR/LF, aspas e Unicode em metadados e exige ausência de documento gerado. |
| 4. Independência | F9 revisou o diff (remoção do grafo e do gerador TypeScript), executou os 19 testes F8 e executou separadamente 11 probes independentes de capacidades, estados e persistência. |
| 5. Ownership e ouro | git diff --check e git diff HEAD -- contracts/fixtures tests/oracles retornaram zero. Os testes da antiga funcionalidade PVM verificam agora a contenção solicitada. Os valores de referência e tolerâncias das suítes científicas não sofreram alterações. |
| 6. CPython/Pyodide | N/A para esta restrição de UI TypeScript anterior ao motor. A prova facultativa adicional Chromium deste ambiente foi impedida no início do processo pelo bloqueio de socket. Este parecer não declara execução real de navegador. |
| 7. Schema | Nenhuma modificação nos contratos ou formatos persistidos. |
| 8. Logs/fixtures | O log inclui versões, SHA de base, blobs de produção, testes e resultados completos de F8/F9. Sem novas matrizes ou meta de desempenho. |
| 9. Maturidade | A UI anuncia indisponibilidade. A contenção não promove o exportador a stable. |
| 10. Limitações | Os achados AUD-020/021 continuam dependentes da integração nativa e do E2E de download. Não há novo lowering científico no navegador. |

## 5. Parecer independente

- Revisor independente: f9-integration-qa
- Commit SHA auditado (base): d98eba61aafbd13a4fbc0e95093c5a6d6db88fdb
- Data (UTC): 2026-11-15
- Resultados: typecheck aprovado, 19/19 F8 e 11/11 oráculos Node aprovados, zero skips.
- Parecer F9: accepted
