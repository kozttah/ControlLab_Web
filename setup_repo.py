#!/usr/bin/env python3
"""
Script de bootstrap inicial do repositório ControlLab Web v1.0 (CL-DIR-001).
Cria a estrutura física da Seção 3.2, os 9 agentes (F1-F9), o Maestro (AGENTS.md),
o CODEOWNERS, o PROJECT_STATE.json (Seções 14 e 18) e o governador de cota (5%/dia + Burn Day).
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 1. Criar árvore de diretórios da Seção 3.2 do Documento Diretor v1.0
DIRS = [
    "control_lab/core",
    "control_lab/diagnostics",
    "control_lab/io",
    "control_lab/statespace",
    "control_lab/frequency/siso",
    "control_lab/frequency/mimo",
    "control_lab/identification",
    "control_lab/fuzzy",
    "control_lab/optimization/modeling",
    "control_lab/optimization/backends",
    "control_lab/optimization/verification",
    "control_lab/experimental/sdp_educational",
    "web/bridge",
    "web/worker",
    "web/storage",
    "web/features",
    "web/charts",
    "web/app",
    "contracts/schemas",
    "contracts/fixtures",
    "contracts/examples",
    "tests/unit/f1",
    "tests/unit/f2",
    "tests/unit/f3",
    "tests/unit/f4",
    "tests/unit/f5",
    "tests/unit/f6",
    "tests/unit/f7",
    "tests/unit/f8",
    "tests/metamorphic",
    "tests/oracles",
    "tests/wasm",
    "tests/e2e",
    "tests/performance",
    "tests/security",
    "docs/architecture/adr",
    "docs/science",
    "docs/user",
    "docs/developer",
    "docs/legal",
    "scripts",
    ".github/workflows",
    ".agents/agents",
]

for d in DIRS:
    p = ROOT / d
    p.mkdir(parents=True, exist_ok=True)
    if d.startswith("control_lab"):
        init_file = p / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""Pacote ControlLab Web v1.0."""\n', encoding="utf-8")

# Mover o Documento Diretor v1.0 para a raiz e para docs/architecture/ para acesso fácil
for fname in ["ControlLab_Web_Documento_Diretor_v1.0.md", "ControlLab_Web_Documento_Diretor_v1.0.pdf"]:
    src = ROOT / fname
    if src.exists():
        shutil.copy2(src, ROOT / "docs" / fname)

# 2. Criar CODEOWNERS refletindo a Seção 13.2
CODEOWNERS = """# Ownership estrito por Frente conforme Seção 13.2 de CL-DIR-001 (v1.0.0)
/control_lab/core/                         @f1-core-io
/control_lab/diagnostics/                  @f1-core-io
/control_lab/io/                           @f1-core-io
/control_lab/statespace/                   @f2-statespace
/control_lab/frequency/                    @f3-frequency
/control_lab/identification/               @f4-identification
/control_lab/fuzzy/                        @f5-fuzzy-ts
/control_lab/optimization/                 @f6-optimization-lmi
/control_lab/experimental/sdp_educational/ @f6-optimization-lmi
/web/bridge/                               @f7-worker-bridge
/web/worker/                               @f7-worker-bridge
/web/storage/                              @f7-worker-bridge
/web/features/                             @f8-ui-charts
/web/charts/                               @f8-ui-charts
/web/app/                                  @f8-ui-charts
/contracts/                                @f9-integration-qa @f1-core-io
/tests/oracles/                            @f9-integration-qa
/tests/e2e/                                @f9-integration-qa
/tests/wasm/                               @f9-integration-qa
/tests/security/                           @f9-integration-qa
/pyproject.toml                            @f9-integration-qa
/.github/workflows/                        @f9-integration-qa
"""
(ROOT / "CODEOWNERS").write_text(CODEOWNERS, encoding="utf-8")

# 3. Criar AGENTS.md (Maestro de Orquestração das 9 Frentes)
AGENTS_MD = """# AGENTS.md — Orquestrador Geral e Governança Multiagente (CL-DIR-001 v1.0.0)

## 1. Fonte Normativa Única
Toda implementação, contrato, estrutura de dados, teste e gate DEVE obedecer estritamente ao documento `@ControlLab_Web_Documento_Diretor_v1.0.md` (também espelhado em `@docs/ControlLab_Web_Documento_Diretor_v1.0.md`).

## 2. Arquitetura Operacional: 8 Frentes Produtoras (F1–F8) + 1 Frente Independente (F9)
Este repositório opera sob isolamento estrito de propriedade (Seção 13.1 e 13.2):
- **F1 (`f1-core-io`)**: `control_lab/core/`, `control_lab/diagnostics/`, `control_lab/io/`, `tests/unit/f1/` (propõe schemas em `contracts/`).
- **F2 (`f2-statespace`)**: `control_lab/statespace/`, `tests/unit/f2/`.
- **F3 (`f3-frequency`)**: `control_lab/frequency/siso/`, `control_lab/frequency/mimo/`, `tests/unit/f3/`.
- **F4 (`f4-identification`)**: `control_lab/identification/`, `tests/unit/f4/`.
- **F5 (`f5-fuzzy-ts`)**: `control_lab/fuzzy/`, `tests/unit/f5/`.
- **F6 (`f6-optimization-lmi`)**: `control_lab/optimization/`, `control_lab/experimental/sdp_educational/`, `tests/unit/f6/`.
- **F7 (`f7-worker-bridge`)**: `web/bridge/`, `web/worker/`, `web/storage/`, `tests/unit/f7/`.
- **F8 (`f8-ui-charts`)**: `web/features/`, `web/charts/`, `web/app/`, `tests/unit/f8/`.
- **F9 (`f9-integration-qa`)**: `contracts/` (aprovação final), `pyproject.toml`, `tests/oracles/`, `tests/metamorphic/`, `tests/wasm/`, `tests/e2e/`, `tests/performance/`, `tests/security/`, `.github/workflows/`, `scripts/`.

### Regras Inegociáveis de Ownership e Não-Circularidade (Seção 13.11 e Apêndice E)
1. Nenhum agente produtor (`F1`–`F8`) pode alterar `contracts/fixtures/` ou tolerâncias de `tests/oracles/` para forçar um teste a passar.
2. A `F9` NUNCA gera *expected values* de fixtures ouro executando diretamente o código sob teste sem validação analítica ou oráculo independente, e NUNCA conserta silenciosamente funções científicas de `F1`–`F8`.
3. Toda entrega de um WorkPackage de `F1`–`F8` passa pelo checklist de handoff de 10 itens do Apêndice E e recebe parecer da `F9` (`accepted`, `changes_requested`, `blocked_by_gate` ou `rejected_with_evidence`).

## 3. Protocolo de Execução e Governança de Créditos (Stateless Cloud Loop)
A cada execução na nuvem, siga estritamente estes passos:
1. Execute `python3 scripts/budget_governor.py --check`. Se o código de saída for `2` (orçamento diário atingido), encerre imediatamente a execução sem gastar tokens adicionais.
2. Leia `@PROJECT_STATE.json` e selecione o primeiro `WorkPackage` com `"status": "PENDING"` cujas `"dependencies"` estejam `"ACCEPTED_BY_F9"`.
3. Invoque o subagente correspondente à frente (`f1-core-io` a `f9-integration-qa` em `.agents/agents/`) via `invoke_subagent` (ou execute no contexto isolado daquela frente) restrito exclusivamente a `allowed_paths`.
4. Execute os comandos de verificação em `acceptance_cmd`.
5. Se a tarefa for de uma frente produtora (`F1`–`F8`), acione em seguida o subagente `f9-integration-qa` para auditar o checklist do Apêndice E e validar contra os testes normativos (`T-*` do Apêndice C).
6. Se aprovado (`ACCEPTED_BY_F9`), atualize `@PROJECT_STATE.json`, execute `python3 scripts/budget_governor.py --record-task` e faça commit/push atômico (`git add -A && git commit -m "feat(<front>): conclui <wp_id> [auditado F9]" && git push`).
7. Se um teste falhar após 3 tentativas, marque `"status": "BLOCKED_NEEDS_ARGON"` em `@PROJECT_STATE.json`, faça commit do diagnóstico e pare para não desperdiçar créditos em loop.
8. Repita o loop a partir do Passo 1 enquanto `python3 scripts/budget_governor.py --check` retornar código `0`.
"""
(ROOT / "AGENTS.md").write_text(AGENTS_MD, encoding="utf-8")

# 4. Criar os 9 Subagentes Nativos do Antigravity em .agents/agents/
SUBAGENTS = {
    "f1-core-io": {
        "desc": "Frente F1 — Núcleo canônico, contratos, interconexões, .ctrlab ZIP e exportador .pvm (Seção 13.3).",
        "paths": "`control_lab/core/`, `control_lab/diagnostics/`, `control_lab/io/`, `tests/unit/f1/` e propostas em `contracts/schemas/`.",
        "rules": """- Implemente `StateSpace`, `TransferFunction`, `Dataset`, `IdentifiedModel`, `TSStateSpace` (`ts_measured`, `polytopic_uncertain`, `ts_partially_observed`), `FuzzySystem`, `StateFeedbackController`, `DynamicController`, `PDCController`, `Experiment` e o envelope imutável `Result` (Seção 4.1 a 4.4 e Apêndice B).
- Garanta convenção explícita `feedback_sign="negative"|"positive"`, `u_ff = N r_y` com `N` de shape `[m, p]`, e `interconnect(plant, controller, wiring, sign_convention)` verificando bem-postura de loop algébrico `I - Dc Dp` (Seção 4.2). Restrinja `get_closed_loop_matrix(A,B)` apenas a realimentação estática completa.
- No exportador `.pvm` v1.0.0 (`make_pvm`) e no contêiner `.ctrlab` ZIP, siga estritamente a Seção 9 e o Apêndice D: importação 100% passiva (nunca executar `codeContext.code` nem `eval`), bloqueio de path traversal e ZIP bomb.
- Testes obrigatórios de aceite: `T-CORE-01`, `T-CORE-02`, `T-CORE-03`, `T-TS-01`, `T-IO-01`, `T-IO-02`, `T-PVM-01`, `T-PVM-02` (Apêndice C)."""
    },
    "f2-statespace": {
        "desc": "Frente F2 — Álgebra de sistemas e controle linear em espaço de estados: PBH, Lyapunov, CARE/DARE, LQR/LQG (Seção 13.4).",
        "paths": "`control_lab/statespace/` e `tests/unit/f2/`.",
        "rules": """- Implemente análise de estabilizabilidade/detectabilidade/controlabilidade/observabilidade (PBH/QR/SVD), simulação LTI, gramianos, Lyapunov/Sylvester, CARE/DARE (`solve_continuous_are`/`solve_discrete_are`), LQR/LQI, alocação de polos e observador/Kalman/LQG (`DynamicController`) (Seções 5.4 e 13.4).
- Jamais use `inv` explícita: recupere `K` via `solve` estável. Calcule sempre o resíduo normalizado `rCARE` (Seção 10.2), erro de simetria `||P - P.T||_F / (1 + ||P||_F)` e estabilidade espectral.
- No teste metamórfico de similaridade LQR (`T-CARE-04`), transforme obrigatoriamente a condição inicial `x_tilde_0 = T @ x0` para verificar invariância de `x0.T @ P @ x0` (Seção 10.2 e Apêndice F `C-07`).
- Testes obrigatórios de aceite: `T-CARE-01`, `T-CARE-02` (`B-CARE-12x3`), `T-CARE-03`, `T-CARE-04` (Apêndice C)."""
    },
    "f3-frequency": {
        "desc": "Frente F3 — Domínio da frequência SISO e MIMO: Bode, Lugar das Raízes, Compensadores, RGA, Valores Singulares (Seção 13.5).",
        "paths": "`control_lab/frequency/siso/`, `control_lab/frequency/mimo/` e `tests/unit/f3/`.",
        "rules": """- Implemente `frequency.eval_response`, `siso.root_locus` (com continuidade de ramos), `siso.design_lead_lag`/PID, múltiplas frequências de cruzamento e margens (Seção 5.3).
- Classifique overlays de requisitos como `exact`, `sufficient`, `heuristic` ou `estimated` (nunca prometa que aproximação de 2ª ordem é exata para ordem superior).
- Em MIMO (`control_lab/frequency/mimo/`), implemente `mimo.rga` (exclusivamente para `G` quadrada e não singular, retornando diagnóstico `undefined` em singularidades), `mimo.singular_values`, `mimo.sensitivity` (`S + T = I` com tolerância escalonada por `kappa(I+L)`) e `mimo.nyquist_generalized` (Seções 5.5 e 10.2).
- Testes obrigatórios de aceite: `T-FREQ-01`, `T-FREQ-02`, `T-MIMO-01`, `T-MIMO-02` e `B-MIMO-2x2` (Apêndice C)."""
    },
    "f4-identification": {
        "desc": "Frente F4 — Identificação de sistemas: ARX, OE, Subespaços (MOESP/N4SID) e validação estatística (Seção 13.6).",
        "paths": "`control_lab/identification/` e `tests/unit/f4/`.",
        "rules": """- Implemente `identification.fit_arx` (por QR/SVD), `fit_oe`, `fit_subspace`, `predict` (1 passo), `simulate` (livre), `validate_model` e `publish_identified_model` (Seção 5.2 e 13.6).
- Verifique sempre posto e número de condição da matriz de regressores (`rank_deficient` / aviso de PE insuficiente quando entrada for constante ou colinear).
- Calcule `FIT = 100 * (1 - ||y - y_hat||_2 / ||y - mean(y)||_2)` separando explicitamente treino e holdout/validação, e informe se é previsão de 1 passo ou simulação livre.
- Testes obrigatórios de aceite: `T-ID-01`, `T-ID-02`, `T-ID-03` e `B-ARX-PRBS` (Apêndice C)."""
    },
    "f5-fuzzy-ts": {
        "desc": "Frente F5 — Controle Fuzzy, IEEE 1855-2016 FML, ANFIS e semântica Takagi-Sugeno / PDC (Seção 13.7).",
        "paths": "`control_lab/fuzzy/` e `tests/unit/f5/`.",
        "rules": """- Implemente `fuzzy.evaluate` (Mamdani e TS), `fuzzy.export_fml`, `fuzzy.import_fml` (perfil IEEE 1855-2016 com proteção XXE e limites de payload), `fuzzy.fit_anfis`, `fuzzy.to_ts_state_space` e `fuzzy.make_pdc_spec` (Seções 5.6, 9.4 e 13.7).
- Respeite rigorosamente `ADR-006` e a Seção 4.3: nunca converta aproximador estático ANFIS em `TSStateSpace` dinâmico sem estados/dinâmica identificados, e bloqueie síntese/implementação `PDCController` quando `TSStateSpace.kind == "polytopic_uncertain"` (premissas não mensuráveis).
- Testes obrigatórios de aceite: `T-FML-01`, `T-FML-02` e `T-TS-01` (Apêndice C)."""
    },
    "f6-optimization-lmi": {
        "desc": "Frente F6 — Modelagem canônica de LMIs, Backends SDP, Verificador Espectral Independente e Solver Didático (Seção 13.8).",
        "paths": "`control_lab/optimization/` (`modeling/`, `backends/`, `verification/`), `control_lab/experimental/sdp_educational/` e `tests/unit/f6/`.",
        "rules": """- Em `optimization/modeling/`, construa `CanonicalSDPProblem` (`F_b(x) = F_{b,0} + sum_k x_k F_{b,k} >= 0`, `Ex = d`, `Hx <= h`), rejeitando produtos bilineares entre variáveis e aplicando fator `sqrt(2)` fora da diagonal na vetorização `svec` para Clarabel (Seção 6.1).
- Em `optimization/backends/`, implemente `ClarabelCvxpyBackend` (sujeito ao Gate `G-0B`), `ScipyLinprogBackend` (fallback exato para blocos diagonais/escalares), `EducationalBarrierBackend` e `UnavailableBackend` (Seção 6.2).
- Em `optimization/verification/`, audite independentemente toda solução sem confiar no status do solver, separando as 5 dimensões da Tabela 6.3 (`solver_status`, `audit_feasibility`, `certificate_status`, `conditioning`, `controller_validity`). Nunca declare `infeasible_certified` sem certificado dual auditado (`<F_k, Z> = 0` e `<F_0, Z> < 0`); na ausência de certificado, retorne `inconclusive` (Seção 6.3).
- Recupere ganhos por `solve(Q.T, Y.T).T` e em H-infinito compare `gamma` apenas sob a mesma planta generalizada e regularidade (Seção 6.4).
- Em `experimental/sdp_educational/`, siga a escada `Níveis A–D` (Seção 6.5).
- Testes obrigatórios de aceite: `T-SDP-A1`, `T-SDP-A2`, `T-SDP-A3`, `T-SDP-B1`, `T-SDP-C1`, `T-SDP-D1`, `T-SDP-D2` (Apêndice C)."""
    },
    "f7-worker-bridge": {
        "desc": "Frente F7 — Runtime Web, Contrato RPC v1.0, Pyodide Worker, WorkerModelStore, MockWorkerAdapter e IndexedDB (Seção 13.9).",
        "paths": "`web/bridge/`, `web/worker/`, `web/storage/` e `tests/unit/f7/`.",
        "rules": """- Implemente o protocolo RPC `api_version="1.0"` (Seção 8.1 e Apêndice A) com `ControlLabEngineClient`, `PyodideEngineClient` e `MockWorkerAdapter` obedecendo exatamente ao mesmo schema.
- Implemente `WorkerModelStore` indexado por `(project_id, object_id, revision)` com LRU, controle monotônico de `project_revision` (descartando respostas obsoletas), transporte binário via `ArrayBuffer` transferível, destruição explícita de `PyProxy` e reidratação via snapshots no `IndexedDB` após `terminate()` (Seção 8.2 a 8.4).
- Configure Service Worker versionado para operação offline real pós-provisionamento (Seção 11.2).
- Testes obrigatórios de aceite: `T-RPC-01`, `T-RPC-02` e `T-SEC-01` (Apêndice C)."""
    },
    "f8-ui-charts": {
        "desc": "Frente F8 — Interface TypeScript, Editores, 6 Abas de Projeto, Gráficos Plotly/Canvas, Overlays e Acessibilidade (Seção 13.10).",
        "paths": "`web/features/`, `web/charts/`, `web/app/` e `tests/unit/f8/`.",
        "rules": """- Desenvolva a interface declarativa baseada em `ToolDescriptor` (Seção 7.1) consumindo exclusivamente `ControlLabEngineClient` da F7 (proibido importar pacote Python ou duplicar síntese matemática na UI).
- No arraste a 60 FPS (`pointermove`), separe estritamente o estado efêmero de `Fast-Preview` do `committed_result`; em `pointerup`, exija `pending_commit` pelo motor Python antes de salvar no histórico/IndexedDB ou permitir exportação (Seção 7.2).
- Atenda aos requisitos de acessibilidade WCAG 2.2 AA (navegação por teclado, toque, contraste, tabelas acessíveis para gráficos) e exiba claramente os selos de maturidade (`stable`, `beta`, `experimental`, `unavailable_wasm`) e classificação de overlays (`exact`, `sufficient`, `heuristic`, `estimated`) (Seções 5.3 e 7.3).
- Teste obrigatório de aceite: `T-UI-01` (Apêndice C)."""
    },
    "f9-integration-qa": {
        "desc": "Frente F9 — Integração Independente, Guardiã de Contratos, Fixtures Ouro, Oráculos, Auditoria Matemática e CI (Seção 13.11).",
        "paths": "`contracts/`, `pyproject.toml`, `tests/oracles/`, `tests/metamorphic/`, `tests/wasm/`, `tests/e2e/`, `tests/performance/`, `tests/security/`, `docs/architecture/`, `scripts/` e `.github/workflows/`.",
        "rules": """- Você é a autoridade independente de qualidade e integração do projeto (Seção 13.11). Você NÃO produz código funcional dentro dos módulos de F1–F8 e NUNCA conserta silenciosamente bugs científicos de F1–F8.
- Sua missão é: (1) congelar schemas em `contracts/schemas/` e fixtures ouro assinadas por hash em `contracts/fixtures/` (`B-CARE-02`, `B-CARE-12x3`, `B-DARE-12x3`, `B-ARX-PRBS`, `B-MIMO-2x2`, `B-SDP-A-D`, `B-PVM-LQR` da Seção 10.4); (2) manter o pipeline CI (Jobs A–G da Seção 15.2); (3) executar os Gates `G-0A`, `G-0B`, `G-0C` e `G-0D` (Seção 14.1); e (4) auditar cada handoff de F1–F8 usando o checklist de 10 itens do Apêndice E, emitindo parecer formal (`accepted`, `changes_requested`, `blocked_by_gate` ou `rejected_with_evidence`)."""
    }
}

for name, info in SUBAGENTS.items():
    content = f"""---
name: {name}
description: {info["desc"]}
subagent: true
mainAgent: false
model: inherit
---
# Diretrizes Estritas do Agente `{name}`

## 1. Escopo Exclusivo de Diretórios (Ownership Seção 13.2)
Você só tem permissão para criar ou modificar arquivos dentro de:
{info["paths"]}

## 2. Regras Científicas e Técnicas Obrigatórias
{info["rules"]}

## 3. Protocolo de Handoff (Apêndice E)
Antes de encerrar qualquer WorkPackage, execute os testes da sua frente, verifique os 10 itens do Checklist de Handoff do Apêndice E de `@ControlLab_Web_Documento_Diretor_v1.0.md` e entregue as evidências para auditoria da Frente F9 (`f9-integration-qa`).
"""
    (ROOT / ".agents" / "agents" / f"{name}.md").write_text(content, encoding="utf-8")

# 5. Criar PROJECT_STATE.json seguindo a Ordem de Ignição da Seção 14.3, Seção 18 e Apêndice E
PROJECT_STATE = {
    "document_id": "CL-DIR-001",
    "spec_version": "1.0.0",
    "budget_policy": {
        "weekly_reset_weekday": "Thursday",
        "burn_day_weekday": "Wednesday",
        "daily_cruise_max_tasks": 1,
        "burn_day_max_tasks": 10,
        "default_model": "gemini-4-hydrogen-high",
        "escalation_model": "orchestrator-argon",
        "history": {}
    },
    "gates": {
        "G-0A": {"status": "PENDING", "description": "Núcleo Python/Pyodide e benchmark B-CARE-12x3 (Seção 14.1)"},
        "G-0B": {"status": "PENDING", "description": "Capacidade real de SDP no navegador via Pyodide (Seção 14.1)"},
        "G-0C": {"status": "PENDING", "description": "UI mínima e contrato RPC v1.0 com Mock e Engine real (Seção 14.1)"},
        "G-0D": {"status": "PENDING", "description": "Persistência .ctrlab e equivalência dinâmica PathView .pvm (Seção 14.1)"}
    },
    "work_packages": [
        {
            "wp_id": "WP-00-F9-BOOTSTRAP",
            "requirement_ids": ["R-23", "R-24"],
            "front": "f9-integration-qa",
            "phase": "Gate-0",
            "title": "Bootstrap pyproject.toml, schemas JSON iniciais em contracts/ e fixtures ouro B-CARE-02, B-CARE-12x3 e B-SDP-A-D",
            "allowed_paths": ["pyproject.toml", "contracts/", "tests/oracles/", "scripts/"],
            "dependencies": [],
            "acceptance_cmd": "pytest tests/oracles/test_golden_fixtures.py -v",
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-01-F1-CORE-MODELS",
            "requirement_ids": ["R-02", "R-03", "R-04", "R-05", "R-27"],
            "front": "f1-core-io",
            "phase": "Gate-0A",
            "title": "Implementar Result, StateSpace, TransferFunction, TSStateSpace (3 tipos) e hierarquia Controller (StateFeedback, Dynamic, PDC) com interconnect()",
            "allowed_paths": ["control_lab/core/", "control_lab/diagnostics/", "tests/unit/f1/"],
            "dependencies": ["WP-00-F9-BOOTSTRAP"],
            "acceptance_cmd": "pytest tests/unit/f1/test_core_models_and_interconnect.py -v",
            "normative_tests": ["T-CORE-01", "T-CORE-02", "T-CORE-03", "T-TS-01"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-02-F2-CARE-LQR",
            "requirement_ids": ["R-02", "R-09"],
            "front": "f2-statespace",
            "phase": "Gate-0A",
            "title": "Implementar PBH, Lyapunov, CARE/DARE e design_lqr com diagnóstico rCARE e teste metamórfico T-CARE-04 (x_tilde_0 = T x0)",
            "allowed_paths": ["control_lab/statespace/", "tests/unit/f2/"],
            "dependencies": ["WP-01-F1-CORE-MODELS"],
            "acceptance_cmd": "pytest tests/unit/f2/test_care_lqr.py -v",
            "normative_tests": ["T-CARE-01", "T-CARE-02", "T-CARE-03", "T-CARE-04"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-03-F6-SDP-MODELING-AND-GATE0B",
            "requirement_ids": ["R-11", "R-12", "R-14", "R-15"],
            "front": "f6-optimization-lmi",
            "phase": "Gate-0B",
            "title": "Implementar CanonicalSDPProblem (sdpvar/bmat/svec), Verificador Independente (5 dimensões de status) e ensaio do Gate G-0B",
            "allowed_paths": ["control_lab/optimization/", "tests/unit/f6/"],
            "dependencies": ["WP-01-F1-CORE-MODELS"],
            "acceptance_cmd": "pytest tests/unit/f6/test_sdp_modeling_and_verification.py -v",
            "normative_tests": ["T-SDP-A1", "T-SDP-A2", "T-SDP-A3", "T-SDP-B1", "T-SDP-C1", "T-SDP-D1", "T-SDP-D2"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-04-F7-RPC-BRIDGE-WORKER",
            "requirement_ids": ["R-01", "R-16", "R-17", "R-28"],
            "front": "f7-worker-bridge",
            "phase": "Gate-0C",
            "title": "Implementar protocolo RPC v1.0, WorkerModelStore, MockWorkerAdapter, PyodideEngineClient e snapshots IndexedDB",
            "allowed_paths": ["web/bridge/", "web/worker/", "web/storage/", "tests/unit/f7/"],
            "dependencies": ["WP-01-F1-CORE-MODELS", "WP-02-F2-CARE-LQR"],
            "acceptance_cmd": "npm --prefix web test",
            "normative_tests": ["T-RPC-01", "T-RPC-02", "T-SEC-01"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-05-F1-IO-CTRLAB-PVM",
            "requirement_ids": ["R-19", "R-20", "R-21"],
            "front": "f1-core-io",
            "phase": "Gate-0D",
            "title": "Implementar contêiner .ctrlab ZIP (importação passiva/anti-traversal) e exportador .pvm v1.0.0 para PathView",
            "allowed_paths": ["control_lab/io/", "tests/unit/f1/"],
            "dependencies": ["WP-02-F2-CARE-LQR"],
            "acceptance_cmd": "pytest tests/unit/f1/test_io_ctrlab_and_pvm.py -v",
            "normative_tests": ["T-IO-01", "T-IO-02", "T-PVM-01", "T-PVM-02"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-06-F8-UI-MVP-LQR",
            "requirement_ids": ["R-18", "R-26", "R-27"],
            "front": "f8-ui-charts",
            "phase": "Gate-0C",
            "title": "Implementar shell da aplicação, ToolDescriptor renderer, tela LQR com Fast-Preview + pending_commit e acessibilidade",
            "allowed_paths": ["web/features/", "web/charts/", "web/app/", "tests/unit/f8/"],
            "dependencies": ["WP-04-F7-RPC-BRIDGE-WORKER", "WP-05-F1-IO-CTRLAB-PVM"],
            "acceptance_cmd": "npm --prefix web test",
            "normative_tests": ["T-UI-01"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-07-F3-FREQ-SISO-MIMO",
            "requirement_ids": ["R-07", "R-08"],
            "front": "f3-frequency",
            "phase": "Fase-3-e-5",
            "title": "Implementar núcleo de frequência SISO (Bode, RL, margens, compensadores) e MIMO (RGA, valores singulares, S+T=I)",
            "allowed_paths": ["control_lab/frequency/", "tests/unit/f3/"],
            "dependencies": ["WP-01-F1-CORE-MODELS"],
            "acceptance_cmd": "pytest tests/unit/f3/ -v",
            "normative_tests": ["T-FREQ-01", "T-FREQ-02", "T-MIMO-01", "T-MIMO-02"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-08-F4-IDENTIFICATION",
            "requirement_ids": ["R-06"],
            "front": "f4-identification",
            "phase": "Fase-4",
            "title": "Implementar ARX por QR/SVD, previsão/simulação livre, FIT%, posto/PE e publicação de IdentifiedModel",
            "allowed_paths": ["control_lab/identification/", "tests/unit/f4/"],
            "dependencies": ["WP-01-F1-CORE-MODELS"],
            "acceptance_cmd": "pytest tests/unit/f4/ -v",
            "normative_tests": ["T-ID-01", "T-ID-02", "T-ID-03"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-09-F5-FUZZY-FML-ANFIS",
            "requirement_ids": ["R-05", "R-10"],
            "front": "f5-fuzzy-ts",
            "phase": "Fase-5",
            "title": "Implementar inferência Mamdani/TS, parser/exportador IEEE 1855-2016 FML (anti-XXE), ANFIS e especificações PDC",
            "allowed_paths": ["control_lab/fuzzy/", "tests/unit/f5/"],
            "dependencies": ["WP-01-F1-CORE-MODELS"],
            "acceptance_cmd": "pytest tests/unit/f5/ -v",
            "normative_tests": ["T-FML-01", "T-FML-02", "T-TS-01"],
            "status": "PENDING",
            "f9_review": "PENDING"
        },
        {
            "wp_id": "WP-10-F6-SDP-EDUCATIONAL-SOLVER",
            "requirement_ids": ["R-13"],
            "front": "f6-optimization-lmi",
            "phase": "Fase-6",
            "title": "Implementar solver didático isolado em experimental/sdp_educational/ e aprovar bateria escalonada Níveis A–D",
            "allowed_paths": ["control_lab/experimental/sdp_educational/", "tests/unit/f6/"],
            "dependencies": ["WP-03-F6-SDP-MODELING-AND-GATE0B"],
            "acceptance_cmd": "pytest tests/unit/f6/test_educational_solver_levels_a_to_d.py -v",
            "normative_tests": ["T-SDP-A1", "T-SDP-A2", "T-SDP-A3", "T-SDP-B1", "T-SDP-C1", "T-SDP-D1", "T-SDP-D2"],
            "status": "PENDING",
            "f9_review": "PENDING"
        }
    ]
}
(ROOT / "PROJECT_STATE.json").write_text(json.dumps(PROJECT_STATE, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# 6. Criar scripts/budget_governor.py (Controle de 5%/dia + Burn Day na véspera da renovação)
GOVERNOR_PY = """#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / "PROJECT_STATE.json"

def main():
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    policy = state["budget_policy"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    weekday_name = datetime.now(timezone.utc).strftime("%A")

    is_burn_day = (weekday_name.lower() == policy["burn_day_weekday"].lower())
    max_tasks = policy["burn_day_max_tasks"] if is_burn_day else policy["daily_cruise_max_tasks"]
    done_today = policy["history"].get(today_str, 0)

    if "--record-task" in sys.argv:
        policy["history"][today_str] = done_today + 1
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
        print(f"[GOVERNOR] WorkPackage registrado em {today_str} ({done_today + 1}/{max_tasks}).")
        return

    mode = "BURN_MODE (Véspera da Renovação - Carga Total!)" if is_burn_day else "CRUISE_MODE (Meta Diária ~5%)"
    remaining = max(0, max_tasks - done_today)
    print(f"[GOVERNOR] Data UTC: {today_str} ({weekday_name}) | Modo: {mode}")
    print(f"[GOVERNOR] WorkPackages concluídos hoje: {done_today}/{max_tasks} | Restantes hoje: {remaining}")

    if remaining <= 0:
        print("[GOVERNOR] STOP: Limite diário atingido. Encerre a sessão do agente imediatamente.")
        sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()
"""
gov_path = ROOT / "scripts" / "budget_governor.py"
gov_path.write_text(GOVERNOR_PY, encoding="utf-8")
gov_path.chmod(0o755)

print("✅ Estrutura do ControlLab Web v1.0 (F1-F8 + F9) gerada com sucesso!")