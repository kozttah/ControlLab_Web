# F9 — CI pós-publicação da fonte F7

Fonte: `6369aa79b7280a2c534474d9860f1ef855f97c29`; [run 44332821471](https://github.com/kozttah/ControlLab_Web/actions/runs/44332821471). Este complemento preserva a distinção entre aceite funcional F7 e aprovação do pipeline completo.

O auditor buscou diretamente os logs do job G `134901467036`: **36 testes passaram**, sem skips, em Chromium 151.0.7922.34. Os três novos casos `test_model_ref_rehydration.py`, os dois casos de reutilização anteriores e as regressões reais de revisões concorrentes/cancelamento/recuperação passaram explicitamente. O extrato primário está em `ci-source-g.log`. Isso confirma no CI a funcionalidade de referências, além das provas locais Firefox 153, sem promover um gate ou maturidade científica.

O job B SDP `134901467320` teve **220 aprovações e uma falha** na comparação exata da regeneração `B-MIMO-2x2`. Os testes científicos MIMO produção-versus-ouro e o certificado ARX passaram. A falha independente é preservada em `../mimo-regeneration/CI_FAILURE_DIAGNOSTIC.json`, `CI_FAILURE.log` e `candidate-from-ci.json`; requisitos da correção própria estão em `../mimo-regeneration/FOLLOWUP.md`.

O achado MIMO inclui cinco pontos de frequência gerados que diferem um ULP, além das respostas derivadas; portanto não se atribui exclusivamente a BLAS. Nenhuma fixture, tolerância ou fonte científica foi alterada no pacote F7. O pipeline completo **não recebe aprovação** enquanto houver job obrigatório em falha, e o Pages permanece condicionado ao gate automático.

Em coordenação com o Maestro, o commit final apenas de metadados/documentação desse achado poderá funcionar como **a única execução diagnóstica adicional**, em vez de reexecutar B no SHA original. Não foi solicitado rerun B pelo Maestro até esta decisão. Verificar os hashes dos 208 arquivos científicos/runtime/testes/contratos/tooling/CI preservados em `../mimo-regeneration/SOURCE_IDENTITY_BASELINE.json` e registrar ambos os SHAs; a fonte científica deve ser idêntica, mas os commits não serão descritos como o mesmo SHA. Se MIMO falhar novamente, não há autorização para novas tentativas até obter verde: a pendência e o bloqueio do pipeline devem permanecer explícitos.

Este complemento não altera o aceite dos oito hashes da entrega F7 nem concede aceite ao futuro pacote MIMO. O registro definitivo do resultado da execução diagnóstica pertence ao Maestro após sua conclusão.
