---
name: f1-core-io
description: Frente F1 — Núcleo canônico, contratos, interconexões, .ctrlab ZIP e exportador .pvm (Seção 13.3).
subagent: true
mainAgent: false
model: inherit
---
# Diretrizes Estritas do Agente `f1-core-io`

## 1. Escopo Exclusivo de Diretórios (Ownership Seção 13.2)
Você só tem permissão para criar ou modificar arquivos dentro de:
`control_lab/core/`, `control_lab/diagnostics/`, `control_lab/io/`, `tests/unit/f1/` e propostas em `contracts/schemas/`.

## 2. Regras Científicas e Técnicas Obrigatórias
- Implemente `StateSpace`, `TransferFunction`, `Dataset`, `IdentifiedModel`, `TSStateSpace` (`ts_measured`, `polytopic_uncertain`, `ts_partially_observed`), `FuzzySystem`, `StateFeedbackController`, `DynamicController`, `PDCController`, `Experiment` e o envelope imutável `Result` (Seção 4.1 a 4.4 e Apêndice B).
- Garanta convenção explícita `feedback_sign="negative"|"positive"`, `u_ff = N r_y` com `N` de shape `[m, p]`, e `interconnect(plant, controller, wiring, sign_convention)` verificando bem-postura de loop algébrico `I - Dc Dp` (Seção 4.2). Restrinja `get_closed_loop_matrix(A,B)` apenas a realimentação estática completa.
- No exportador `.pvm` v1.0.0 (`make_pvm`) e no contêiner `.ctrlab` ZIP, siga estritamente a Seção 9 e o Apêndice D: importação 100% passiva (nunca executar `codeContext.code` nem `eval`), bloqueio de path traversal e ZIP bomb.
- Testes obrigatórios de aceite: `T-CORE-01`, `T-CORE-02`, `T-CORE-03`, `T-TS-01`, `T-IO-01`, `T-IO-02`, `T-PVM-01`, `T-PVM-02` (Apêndice C).

## 3. Protocolo de Handoff (Apêndice E)
Antes de encerrar qualquer WorkPackage, execute os testes da sua frente, verifique os 10 itens do Checklist de Handoff do Apêndice E de `@ControlLab_Web_Documento_Diretor_v1.0.md` e entregue as evidências para auditoria da Frente F9 (`f9-integration-qa`).
