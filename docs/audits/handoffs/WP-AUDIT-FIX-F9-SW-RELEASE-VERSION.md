# Handoff F9 — WP-AUDIT-FIX-F9-SW-RELEASE-VERSION

**Parecer provisório: `blocked_by_gate`. WorkPackage permanece `PENDING`.**

R-22/R-28, T-SEC-01/T-RPC-01; CL-DIR-001 §11.2 e Apêndice E. Auditor independente: agente F9 reviewer, separado do produtor F9. Base examinada: `feb94a8c97410583881ca54fbd5132d35bc1469b`.

## Escopo e evidências independentes

O build incorpora SHA-256 determinístico do inventário no script do Service Worker. O inventário inclui wheel, bundles, ativos fixados, licenças e SBOM; exclui somente o próprio SW e o manifesto final para evitar ciclo. A geração preliminar de SBOM precede o fingerprint; o manifesto final inclui os bytes carimbados. A lógica runtime F7 não muda.

- `docs/audits/sw-release/reviewer/oracles.log`: 8 testes passaram, incluindo dois testes black-box escritos pelo auditor. Confirmam alteração wheel-only/SBOM, ausência de ciclo com manifesto, repetição idêntica, independência da ordem de criação e preservação de edição do corpo SW.
- `docs/audits/sw-release/reviewer/reproducibility.log`: dois builds completos, 42 ativos, manifestos e hashes idênticos.
- `docs/audits/sw-release/reviewer/baseline.json`: hashes prévios das sete fixtures ouro, arquivo de checksums e lock Pyodide. Os nove arquivos permanecem intactos.
- `docs/audits/sw-release/reviewer/checks.json`: snapshot provisório dos arquivos revisados. Deve ser atualizado após finalizar a regressão de navegador.

A regressão A/B gera releases em cópia temporária com marcador exclusivo na proveniência Python da wheel; exerce a aplicação, Worker e LQR reais, na mesma origem e prefixo `/ControlLab_Web/`. Não altera resultados ouro, tolerâncias ou código F1–F8 do repositório.

## Checklist do Apêndice E

| Item | Parecer provisório |
|---|---|
| 1. Contrato API F1/F9 e consumidores F7/F8 | Compatível: alteração restrita ao build/identidade do SW; contratos RPC permanecem iguais. Execução integrada aguardada. |
| 2. Status, diagnósticos, proveniência e falhas | Teste verifica cache ativo, proveniência Python e falhas de download/integridade/offline; aguarda conclusão nos dois motores. |
| 3. Testes analíticos | Passaram oráculos determinísticos de inventário, wheel-only e SBOM; sem mudança científica. |
| 4. Confronto independente | Auditor separado escreveu black-box e executou oráculos + dois builds completos; matriz navegador ainda pendente. |
| 5. Ownership e proteção dos expected | Apenas paths F9; nenhuma implementação F1–F8, fixture ouro, tolerância ou lock de runtime alterada. |
| 6. CPython/Pyodide no domínio anunciado | Build CPython validado; cálculo LQR no Pyodide real ainda depende da prova final Chromium/Firefox. |
| 7. Schema, migração e versão | Sem alteração de schema: comentário de identidade no SW, manifesto v1 preservado, IndexedDB sem migração. |
| 8. Logs, fixtures e resultados | Oráculos, hashes de baseline e dois builds anexados; faltam relatórios de ambos navegadores no SHA candidato. |
| 9. Maturidade experimental preservada | Nenhum gate ou método científico promovido por esta revisão. Build ou upload de pacote não equivale a liberação estável. |
| 10. Limites conhecidos e falhas | Chromium local indisponível: binário existente bloqueado por EPERM e download oficial negado pela política de rede. Exigir CI real no SHA revisado; sem skips/mocks. |

## Condições para aceite

O código candidato pode ser publicado para executar CI mantendo o WorkPackage `PENDING`. Esta auditoria ainda não autoriza `ACCEPTED_BY_F9`: são obrigatórios resultado real de Chromium no CI e Firefox, regressão completa A/B incluindo atualização falha/offline, preservação de projetos e execução Python coerente antes/depois da ativação. Registrar SHA candidato e URL imutável do run, revisar o diff final e atualizar este parecer somente após todas as provas.

Referência de ciclo nativo de update/waiting/activation: https://w3c.github.io/ServiceWorker/spec/service_worker/ .
