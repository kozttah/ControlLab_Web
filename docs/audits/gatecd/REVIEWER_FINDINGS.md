# Revisão independente F9 — fechamento Gates0B/0C/0D

Base 58d101d2d3296026af39c388f799e5577e38b027, diff identificado por source-sha256.json. Revisor /root/f9_gate_review, distinto dos produtores F1/F8/F9. Data UTC 2026-11-17.

## Provas repetidas

| Prova independente | Resultado | Log |
| --- | --- | --- |
| CPython unidade/integração/oráculos | 343 aprovados | reviewer-python.log |
| Web npm/typecheck | 53 aprovados | reviewer-web.log |
| Contrato F1 completo | 101 aprovados | f1-review.log |
| Pipeline de build/manifesto | 4 aprovados | reviewer-manifest.log |
| Novos4E2E +4Wasm em Chromium 153 | 8 aprovados, 70.69s | reviewer-chromium.log |
| Abertura na UI oficial PathView 0.21 dos4PVM baixados | 4 imports renderizados, sem erro JS | reviewer-official-pathview-ui.json |
| G0B nativo em Firefox 153 | 1 aprovado, 60.95s | reviewer-firefox.log |
| Aceite específico IO/PVM | 47 aprovados, 1.68s | reviewer-io.log |

O produtor distinto executou pytest completo372/372, npm53/53, Node 21/21 e Wasm+E2E19/19 em Firefox; logs producer-*.log. Não se atribui essa execução completa ao revisor. Todos os testes executados passaram sem skips; avisos registrados são depreciação AnyIO/pytest e ordem do plugin, sem erro do produto.

## Revisão do comportamento

O arraste real do slider em20 passos mantém o snapshot IndexedDB confirmado durante preview e só compromete a nova revisão ao soltar. Exportação fica bloqueada enquanto preview/pending. Teclado percorre as seis abas, alcança o slider, confirma por seta/Enter e restaura foco após Escape. Mobile 390x844 usa CSS efetivamente embarcado e uma coluna sem overflow global. Q inválida3x3 gera DIMENSION_MISMATCH visível; curvas x/u possuem polylines e tabela acessível.

Os arquivos saturado e dinâmico foram baixados do botão real antes de serem processados pelo conversor oficial. O caso saturado usa x0=[2,0] e limites±.25, com clipping efetivamente ativado. O dinâmico usa Dp=.4,Dc=.3,z0=-.8 e realimentação negativa, antes de qualquer síntese LQR. O confronto resolve a ODE e o loop algébrico próprios, não chama o simulador ControlLab como referência; compara u/y ao longo de501 amostras, estados finais e todas as arestas/portas do grafo. A tolerância existente 2e-6 permaneceu intacta; erros observados próximos à precisão de máquina. Reabertura ZIP preserva as opções e produz bytes PVM idênticos em cada caso.

A UI oficial PathView foi aberta com servidor do pacote0.21 sem modificação, usando importação de arquivo pelo DOM. Todos os nós/blocos dos quatro arquivos importados renderizaram com geometria não nula e sem pageerror. O campo global_g0d_approval=False desse probe significa que sua prova de importação isolada não decide o gate; a decisão consolidada está nos handoffs e PROJECT_STATE.

## Correções exigidas durante a revisão

F8 corrigiu token de corrida na exportação ZIP e preservação do DTO latente ao alternar modos; testes de regressão adicionados. O manifesto de build abandonou alegações globais pendentes obsoletas, mantendo inventário schema 1 e atestação externa; F7 verificou somente leitura install/activate/readiness. Nenhuma correção silenciosa foi feita nos arquivos de outra frente.

## Integridade e limites

Nenhuma fixture ouro ou tolerância foi adulterada. O diff de tests/oracles só adiciona teste de contrato do manifesto; referências científicas anteriores permanecem intactas. Imports continuam passivos, e external_pathview_verified=False em novos arquivos não é reescrito como aprovação universal por arquivo.

A build comum tem SHA-256 57cb668376871e915f213707194e51c9d76504ab6a90cdfa493b01eaed77279d e foi reproduzida duas vezes pelo produtor. O manifesto integrity_only/schema 1 preserva compatibilidade e release_approved=False; aprovação de release global é separada. ADR009 aceita limitação externa da conta pessoal por governança em arquivo/CI; ADR010 governa SDP nativo e fallback offline. MATLAB/YALMIP não foi executado, somente validação estrutural/sintática. .pvm dinâmico não exige LQR; .ctrlab da tela ainda exige workspace LQR confirmado e preserva suas opções dinâmicas. Multirate/eventos externos fora do domínio e DEC-OPEN-03 de hardware preservados.
