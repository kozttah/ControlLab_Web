# Pré-requisitos de runtime identificados na auditoria de reutilização

Fonte: `984651087e0248e57ba80e9bf36133d1737d6f73` e incremento de WP-V1-F1-MODEL-REUSE-RPC, CL-DIR-001 §§8/11.2/13.9/15.3. Inspeção do Maestro confirmada independentemente pela F9 em 2026-11-17. Estes são requisitos de trabalho futuro; não são funcionalidades implementadas ou aceites de runtime nesta rodada.

## WP-AUDIT-FIX-F9-SW-RELEASE-VERSION

Frente F9. Achado `F9-RUNTIME-SW-001`, requisitos R-22/R-28 e regressões T-SEC-01/T-RPC-01. Prioridade antes dos incrementos de interface.

`scripts/build_web.mjs` empacota o Service Worker somente a partir de suas fontes TypeScript e dependências. Uma alteração exclusiva da wheel Python pode mudar o manifesto/artefatos sem mudar os bytes de `service_worker.js`. `web/worker/service_worker.ts` provisiona durante o evento install e atende pelo cache ativo, sem atualizar o manifesto no caminho de fetch. O registro com `updateViaCache: 'none'` não torna diferente um script cujos bytes permaneceram iguais. Assim, a publicação de um novo build não garante atualização automática de clientes já provisionados. Os testes desta rodada usaram contextos novos e não demonstram atualização de uma instalação anterior.

Entrega exigida:

1. Incorporar no build um identificador determinístico da release que altere os bytes/identidade do Service Worker quando os assets relevantes mudarem, inclusive uma mudança apenas da wheel. Evitar ciclo de hash com o próprio SW e o manifesto. Preservar os hashes fixados dos assets Pyodide e suas licenças.
2. Dois builds das mesmas entradas devem manter todos os hashes idênticos. Não usar timestamp corrente ou identificador aleatório.
3. Acrescentar regressão em navegador real com releases A/B servidas na mesma origem e prefixo `/ControlLab_Web/`, incluindo cliente A já provisionado, atualização B e cliente novo. Confirmar que a versão Python efetivamente carregada corresponde à release ativa e não mistura recursos A/B.
4. Respeitar o ciclo waiting/activate e os clientes abertos. Falha no download, integridade inválida ou modo offline durante atualização deve preservar a release A utilizável, sem falso selo de atualização ou perda de projetos.
5. Verificar em Chromium e Firefox, com evidências por build/navegador. Se for indispensável mudar lógica runtime de `web/worker/`, propor um pacote F7 próprio antes de editar diretório alheio.

Paths F9: `scripts/`, `tests/oracles/`, `tests/e2e/`, `.github/workflows/`, `docs/audits/`, `docs/architecture/`. O comando de aceite inclui build, oráculos de build e E2E; os testes novos A/B acima são obrigatórios, e passar somente a suíte antiga não atende ao achado.

## WP-V1-F7-MODEL-REF-REHYDRATION

Frente F7. Requisitos R-02/R-03/R-06/R-28 e T-RPC-01/T-RPC-02/T-SEC-01. Depende do modelo reutilizável F1 e do pré-requisito de atualização de release acima.

`PyodideWorkerRuntime.handleRpcRequest` resolve atualmente apenas `plant_ref` no WorkerModelStore. O entrypoint Python recebe `{request, payload}` sem store Python. Logo, `core.reuse_model` funciona no Worker com `payload.model` inline, mas `payload.model_ref` isolado não é materializado e deve falhar explicitamente. O mesmo inventário de aliases precisa ser confrontado com as entradas de identificação, antes da UI de datasets/modelos tipados.

Entrega exigida:

1. Materializar `model_ref → model` para `core.reuse_model`, com identidade/revisão/tipo e projeto exatos. Documentar e testar os aliases necessários às operações de identificação, incluindo `dataset_ref → dataset` e `val_dataset_ref → val_dataset`/`train_dataset_ref → train_dataset` nos destinos realmente aceitos pelo dispatcher. Não resolver recursivamente campos arbitrários com sufixo `_ref` dentro de proveniência ou dados do usuário.
2. Rejeitar fonte inline e referência simultâneas antes de materializar. Após resolução de uma referência legítima, enviar um payload canônico sem criar a ambiguidade inline/ref proibida pelo contrato F1. Não substituir silenciosamente uma revisão obsoleta por outra, nem procurar em outro projeto ou store global.
3. Preservar isolamento, referências registradas, transporte binário, cancelamento/obsolescência e destruição de PyProxy. Registro do resultado continua explícito pelo chamador; a operação científica não altera o projeto automaticamente.
4. Acrescentar testes unitários F7 positivos/negativos e prova independente F9 no Worker/Pyodide real: registrar fonte, reutilizar por referência, registrar modelo derivado e consumi-lo em LQR/frequência. Incluir modelos identificados por ARX com atraso, subespaços e dataset referenciado, sem mocks como prova de disponibilidade Wasm.

Paths F7: `web/bridge/`, `web/worker/`, `web/storage/`, `tests/unit/f7/`. Aceite produtor: typecheck e testes F7. A F9 produz as provas independentes Wasm dentro de seu ownership, revisa o contrato e o checklist completo antes do aceite.

## Ordem da fila e limites

PROJECT_STATE registra ambos como PENDING, antes de WP-V1-F8-TYPED-WORKSPACE-INPUTS. A ordem é atualização determinística de release, reidratação F7 e depois entradas tipadas F8. A identificação/SISO e sua homologação seguem as dependências existentes. A inspeção acima não modifica o Service Worker, o build ou a UI na entrega F1 atual, nem promove os gates a um escopo maior que o já auditado.
