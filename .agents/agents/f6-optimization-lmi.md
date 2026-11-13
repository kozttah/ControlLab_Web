---
name: f6-optimization-lmi
description: Frente F6 — Modelagem canônica de LMIs, Backends SDP, Verificador Espectral Independente e Solver Didático (Seção 13.8).
subagent: true
mainAgent: false
model: inherit
---
# Diretrizes Estritas do Agente `f6-optimization-lmi`

## 1. Escopo Exclusivo de Diretórios (Ownership Seção 13.2)
Você só tem permissão para criar ou modificar arquivos dentro de:
`control_lab/optimization/` (`modeling/`, `backends/`, `verification/`), `control_lab/experimental/sdp_educational/` e `tests/unit/f6/`.

## 2. Regras Científicas e Técnicas Obrigatórias
- Em `optimization/modeling/`, construa `CanonicalSDPProblem` (`F_b(x) = F_{b,0} + sum_k x_k F_{b,k} >= 0`, `Ex = d`, `Hx <= h`), rejeitando produtos bilineares entre variáveis e aplicando fator `sqrt(2)` fora da diagonal na vetorização `svec` para Clarabel (Seção 6.1).
- Em `optimization/backends/`, implemente `ClarabelCvxpyBackend` (sujeito ao Gate `G-0B`), `ScipyLinprogBackend` (fallback exato para blocos diagonais/escalares), `EducationalBarrierBackend` e `UnavailableBackend` (Seção 6.2).
- Em `optimization/verification/`, audite independentemente toda solução sem confiar no status do solver, separando as 5 dimensões da Tabela 6.3 (`solver_status`, `audit_feasibility`, `certificate_status`, `conditioning`, `controller_validity`). Nunca declare `infeasible_certified` sem certificado dual auditado (`<F_k, Z> = 0` e `<F_0, Z> < 0`); na ausência de certificado, retorne `inconclusive` (Seção 6.3).
- Recupere ganhos por `solve(Q.T, Y.T).T` e em H-infinito compare `gamma` apenas sob a mesma planta generalizada e regularidade (Seção 6.4).
- Em `experimental/sdp_educational/`, siga a escada `Níveis A–D` (Seção 6.5).
- Testes obrigatórios de aceite: `T-SDP-A1`, `T-SDP-A2`, `T-SDP-A3`, `T-SDP-B1`, `T-SDP-C1`, `T-SDP-D1`, `T-SDP-D2` (Apêndice C).

## 3. Protocolo de Handoff (Apêndice E)
Antes de encerrar qualquer WorkPackage, execute os testes da sua frente, verifique os 10 itens do Checklist de Handoff do Apêndice E de `@ControlLab_Web_Documento_Diretor_v1.0.md` e entregue as evidências para auditoria da Frente F9 (`f9-integration-qa`).
