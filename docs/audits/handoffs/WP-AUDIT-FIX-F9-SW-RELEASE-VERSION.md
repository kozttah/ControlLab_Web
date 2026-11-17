# Handoff F9 — WP-AUDIT-FIX-F9-SW-RELEASE-VERSION

Parecer F9: accepted

**Parecer final independente: `accepted`.** O Maestro pode registrar `ACCEPTED_BY_F9` para este WorkPackage.

R-22/R-28, T-SEC-01/T-RPC-01; CL-DIR-001 §11.2 e Apêndice E. Auditor F9 reviewer separado do produtor F9. Base: `feb94a8c97410583881ca54fbd5132d35bc1469b`. Fonte final auditada: **`89fb4e048cb787027adb239d35448b42e09d3368`**. [CI 44197401222, tentativa 2](https://github.com/kozttah/ControlLab_Web/actions/runs/44197401222/attempts/2): concluído com sucesso, SHA e resultado confirmados diretamente pelo auditor na API GitHub. Dependências BUILD-CI e F7-OFFLINE-SW continuam aceitas.

## Resultado e contrato

O build incorpora SHA-256 determinístico do inventário no script do Service Worker. O inventário inclui wheel, bundles, ativos fixados, licenças e SBOM; exclui somente o próprio SW e o manifesto final para evitar ciclo. O SBOM preliminar precede o fingerprint e o manifesto final inclui os bytes carimbados. A lógica runtime F7 permanece intacta.

As releases A/B foram construídas em cópia temporária, alterando somente um marcador de proveniência Python na wheel. A aplicação, Worker, RPC e cálculo LQR reais confirmaram a versão efetivamente executada. Não houve Worker de teste substituindo a aplicação, mock, skip ou alteração de resultado científico. Os testes mantêm a mesma origem e prefixo `/ControlLab_Web/`.

- A/A-repeat: os 43 arquivos totais (42 ativos inventariados e o manifesto) são idênticos. Dois builds completos adicionais foram executados independentemente pelo auditor e seus manifestos/hashes coincidem.
- A/B: somente wheel, SBOM, manifesto e bytes do Service Worker mudam; bundles JavaScript permanecem iguais. Fingerprint muda também em alteração exclusiva de metadado SBOM. Alterar o manifesto final não cria ciclo.
- Cliente A continua executando Python A enquanto B aguarda; outro cliente aberto nesse período também carrega A. Após fechar os clientes A, B ativa e cliente novo executa Python B, inclusive depois de reload offline.
- Falhas reais de download HTTP, integridade e indisponibilidade de transporte preservam o cache A verificado, cálculos A e projetos/objetos/snapshots. O teste compara persistência antes de novo commit para não mascarar perda de dados. Nenhuma falha produz falso estado B pronto.

## Evidências verificadas

| Execução | Resultado |
|---|---|
| Auditor: build pipeline + oráculos de fingerprint, incluindo dois black-box próprios | 8 passaram; `reviewer/oracles.log` |
| Auditor: dois builds completos das mesmas entradas | Manifestos e todos os hashes idênticos; `reviewer/reproducibility.log` |
| Auditor: Firefox 153 A/B real | 1 passou em 185,22 s; `reviewer/firefox.log` e `.json` |
| Produtor: Firefox 153 E2E completo, driver 1.58, candidato anterior | 13 passaram, zero falhas/erros/skips, 731,36 s; `firefox-suite.json` e `.log` |
| Produtor: Playwright 1.62 / Firefox 153 A/B | 1 passou em 186,04 s; `firefox-pinned-release.json` e `.log` |
| CI final G, job 134442312194, logs buscados pelo auditor | Chromium 151.0.7922.34, 33 passaram sem skips; `reviewer/chromium-ci.json` e `.log` |
| CI final E, job 134442312305, logs buscados pelo auditor | Chromium E2E 13 passaram; Firefox 153 A/B 1 passou em 178,46 s; `reviewer/browser-ci2.log` e `firefox-ci2.json` |
| CI final B SDP, única repetição diagnóstica, job 134449383224 | 166 passaram, inclusive regeneração ARX; `reviewer/arx-ci2-retry.log` |
| Maestro: Python unit/oráculos e web | 373 Python e 53 web passaram; `MAESTRO_VALIDATION.md` |
| Auditor: governança e fixtures | Governança aprovada; 11 schemas, sete fixtures e exemplos verificados; `reviewer/governance.log` e `fixtures.log` |

A API confirmou todos os jobs finais A–G e publicação **beta** H com sucesso. A maturidade do produto e os estados dos Gates G-0A..D não são alterados por este aceite. Artefato construído ou publicado não é promoção estável.

## Checklist do Apêndice E

| Item | Parecer e fundamento |
|---|---|
| 1. Contrato API F1/F9 e consumidores F7/F8 | **Conforme.** API RPC e contratos de manifesto/readiness preservados; aplicação F7/F8 real consome releases coerentes nos dois motores. |
| 2. Status, diagnósticos, proveniência e falhas | **Conforme.** Readiness/cache, proveniência Python e falhas download/integridade/offline foram confrontados com cálculos novos e persistência antes/depois de reload. Firefox incompatível falha explicitamente; timeout mostra registro/estado. |
| 3. Testes analíticos | **Conforme.** Oráculos determinísticos para wheel-only, SBOM, ausência de ciclo, ordem de criação e edição de SW; LQR real confere ganho conhecido. Nenhuma otimização científica foi introduzida. |
| 4. Confronto independente | **Conforme.** Auditor separado escreveu black-box, executou oráculos, dois builds e Firefox A/B e buscou diretamente logs CI Chromium/Firefox e B diagnóstico. Sete hashes de fonte/testes/tooling foram conferidos contra o SHA auditado. |
| 5. Ownership e proteção dos expected | **Conforme.** Mudanças somente F9. Diff desde baseline não toca `control_lab/`, fixtures, app/bridge/worker F1–F8 ou lock Pyodide. Nove hashes protegidos foram novamente conferidos ao encerrar; nenhuma tolerância ou ouro alterado. |
| 6. CPython/Pyodide no domínio anunciado | **Conforme.** Build/verificadores em CPython e cálculo científico no Worker Pyodide real em Chromium/Firefox. Nenhuma inferência de disponibilidade Wasm a partir de um teste CPython isolado. |
| 7. Schema, migração e versão | **Conforme.** Manifesto v1 e schema IndexedDB preservados; identidade determinística acrescida como comentário no SW. Projetos existentes são preservados; sem migração necessária. |
| 8. Logs, fixtures e resultados | **Conforme.** Matriz com versões, hashes A/B, cache ativo, falhas e persistência anexados. Build reproduzido, fixtures assinadas verificadas e histórico negativo mantido. Benchmark científico não foi alterado por este WP de build. |
| 9. Maturidade experimental preservada | **Conforme.** Nenhum método, Gate ou produto foi promovido a estável; publicação mantém classificação beta. |
| 10. Limites e rastreamento | **Conforme com achado separado.** Chromium local indisponível foi suprido por CI real no SHA auditado. Incompatibilidade Firefox 146 foi resolvida com runtime oficial compatível. Fragilidade independente da regeneração ARX está documentada para `WP-AUDIT-FIX-F9-ARX-REGENERATION`; este aceite não a declara corrigida. |

## Histórico negativo e limites preservados

1. O primeiro candidato `12d7580f1575e958003495ecd0d94ec08671f2ce` passou Chromium, mas CI Firefox 146 não registrou Service Worker module. Firefox introduziu esse suporte na versão 147 ([notas oficiais](https://www.firefox.com/en-US/firefox/147.0/releasenotes/), [MDN](https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Releases/147), bug 1360870). A evidência negativa está em `reviewer/firefox-ci-attempt1.log`. Corrigiu-se somente tooling F9: Playwright 1.62 fornece Firefox 153. Sem preferência experimental, aumento de timeout ou mudança de runtime de produção.
2. Na tentativa inicial do CI final, B SDP detectou comparação exata entre regeneração ARX e ouro, com diferenças derivadas de no máximo `2.1316282072803006e-14`. O contrato congelado já admite variação de último bit BLAS. Uma única repetição diagnóstica **no mesmo SHA**, sem alteração de teste, dados ou tolerância, passou 166 testes. A falha inicial não foi apagada: `reviewer/arx-ci2-diagnostic.json` e [follow-up específico](../sw-release/ARX_REGENERATION_FOLLOWUP.md) exigem correção futura com campos numéricos nomeados, certificados independentes e negativos. Não houve reruns sucessivos ou afrouxamento de limite para fechar o SW.
3. Download local do Chromium oficial foi negado pela política de rede e o binário antigo não executou por EPERM. Não se contornou a restrição nem se alegou matriz local: a evidência Chromium válida é a execução GitHub Actions, vinculada ao SHA final.

Referência do ciclo nativo update/waiting/activate: https://w3c.github.io/ServiceWorker/spec/service_worker/ .
