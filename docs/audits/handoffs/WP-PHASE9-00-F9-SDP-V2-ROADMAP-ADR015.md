# Handoff e Parecer F9 — `WP-PHASE9-00-F9-SDP-V2-ROADMAP-ADR015`

- **WorkPackage**: `WP-PHASE9-00-F9-SDP-V2-ROADMAP-ADR015`
- **Frente Produtora**: `F9 (f9-integration-qa)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **ADR Formalizada**: `ADR-015` (`docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md`, complemento direto da `ADR-010`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-23T03:35:00Z`

---

## 1. Escopo Auditado e Inventário SHA-256 (`allowed_paths`)

A Frente F9 atuou exclusivamente nos `allowed_paths` autorizados (`docs/architecture/`, `docs/audits/`, `PROJECT_STATE.json`), sem modificar código de produção (`control_lab/`, `web/`), `contracts/` ou testes unitários `tests/unit/f1..f8/`:

| Artefato F9 | SHA-256 | Papel no Pacote |
|---|---|---|
| `docs/architecture/ADR-015-native-sdp-v2-memory-hsde-sparsity-roadmap.md` | `8b5f658117afc3269fa27d1699cdaacb7ecc787b8062d05c7a37fe811fddee78` | Formaliza `ADR-015` (`ACCEPTED`, `2026-11-22`, `project_coordinator`), documentando racional de rejeição de servidor local/clarabel.wasm/wasm64+COOP-COEP/ADMM-SCS, 5 pilares arquiteturais, 4 ciclos de execução, invariante 5D/oráculo `clarabel_direct` e 12 referências científicas com DOIs/arXiv. |
| `docs/architecture/ADR-010-native-sdp-and-offline-exports.md` | `9423774e79e37c5683378346c0b943a756296d60ffc8592ea409ecfa1eaa53c5` | Adiciona seção `## Evolução Planejada (ADR-015 — Fase 9)` vinculada à `ADR-015` e resumindo os 4 ciclos sem alterar decisões históricas de `G-0B` ou do `BROWSER_ENVELOPE` atual. |
| `PROJECT_STATE.json` | — | Registra `ADR-015` em `architecture_decisions` e adiciona os 12 WorkPackages da fase `Phase9-Native-SDP-Scalability-v2` (`114` WPs totais, `103` aceitos, `11` pendentes com DAG acíclico validado). |
| `docs/audits/handoffs/WP-PHASE9-00-F9-SDP-V2-ROADMAP-ADR015.md` | — | Este parecer formal F9 com checklist de 10 itens do Apêndice E. |

---

## 2. Registro da Fila Fase 9 (`Phase9-Native-SDP-Scalability-v2`)

Foram registrados 12 WorkPackages no grafo de dependências de `PROJECT_STATE.json`:

1. `WP-PHASE9-00-F9-SDP-V2-ROADMAP-ADR015` (`f9-integration-qa`) — `ACCEPTED_BY_F9`
2. `WP-PHASE9-01A-F6-INPLACE-WORKSPACE-PACKED-COO` (`f6-optimization-lmi`) — `PENDING`
3. `WP-PHASE9-01B-F7-TYPEDARRAY-WORKER-BRIDGE` (`f7-worker-bridge`) — `PENDING`
4. `WP-PHASE9-01C-F8-PACKED-COO-COMPILER` (`f8-ui-charts`) — `PENDING`
5. `WP-PHASE9-01D-F9-CYCLE1-MEMORY-AUDIT` (`f9-integration-qa`) — `PENDING`
6. `WP-PHASE9-02-F6-HSDE-GONDZIO-SOLVER` (`f6-optimization-lmi`) — `PENDING`
7. `WP-PHASE9-02B-F9-HSDE-ORACLE-AUDIT` (`f9-integration-qa`) — `PENDING`
8. `WP-PHASE9-03-F6-FUJISAWA-F1F2-PREPROCESS` (`f6-optimization-lmi`) — `PENDING`
9. `WP-PHASE9-03B-F8-DSL-SYMMETRIC-FUSION` (`f8-ui-charts`) — `PENDING`
10. `WP-PHASE9-03C-F9-F1F2-BENCHMARK-AUDIT` (`f9-integration-qa`) — `PENDING`
11. `WP-PHASE9-04-F6-CHORDAL-CLIQUES-SPARSE-SCHUR` (`f6-optimization-lmi`) — `PENDING`
12. `WP-PHASE9-04B-F9-CHORDAL-ENVELOPE-RECALIBRATION` (`f9-integration-qa`) — `PENDING`

---

## 3. Evidência de Governança

```text
python3 scripts/project_governance.py
-> {"accepted": 103, "corrective_packages": 24, "work_packages": 114} (exit 0)
```

---

## 4. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | Contrato de roadmap `ADR-015` define explicitamente fronteiras de ownership entre `F6` (`control_lab/optimization/`), `F7` (`web/bridge/`, `web/worker/`), `F8` (`web/features/`) e `F9` (`tests/oracles/`, `tests/wasm/`, `tests/e2e/`), preservando retrocompatibilidade com `F_k` e `F_k_sparse`. | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `ADR-015` preserva as 5 dimensões de status de `control_lab/optimization/verification/`, certificados Farkas explícitos para infactibilidade/ilimitabilidade (Ciclo 2) e recomendação de exportação offline CVXPY/YALMIP (`ADR-010`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Cada ciclo da Fase 9 vincula explicitamente a entrega de `F6`/`F7`/`F8` a um WorkPackage auditor `F9` (`01D`, `02B`, `03C`, `04B`) com oráculos independentes antes de qualquer recalibração do `BROWSER_ENVELOPE`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | `ADR-015` fixa como invariante inegociável a paridade contra o oráculo `clarabel_direct` (`tests/oracles/`) e auditoria 5D no problema original não escalonado/não decomposto sem relaxamento de tolerâncias. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações estritamente restritas a `docs/architecture/`, `docs/audits/` e `PROJECT_STATE.json`; nenhum arquivo em `contracts/fixtures/`, `tests/oracles/`, `control_lab/` ou `web/` foi tocado. | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Todos os 4 ciclos especificam exclusivamente Python puro + NumPy/SciPy (incluindo `scipy.sparse.csgraph` e `scipy.sparse.linalg.splu`) disponíveis no bundle Pyodide padrão, com gates obrigatórios em CPython e Chromium/Pyodide real. | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma alteração de schema canônico em `contracts/schemas/`; `ADR-015` registrada em `PROJECT_STATE.json` e vinculada à `ADR-010`, validada por `scripts/project_governance.py`. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Inventário SHA-256 dos documentos arquiteturais, tabela dos 4 ciclos, 12 referências bibliográficas com DOIs/arXiv e saída exata de `scripts/project_governance.py` anexados. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Nenhuma alteração de classificação experimental; `control_lab/experimental/sdp_educational/` permanece isolado sob `ADR-008`/`ADR-010` e o envelope `BROWSER_ENVELOPE` só poderá ser recalibrado mediante evidência real no `WP-PHASE9-04B`. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Limitações estruturais de `wasm32` (memória linear, *single-threaded*, hospedagem estática sem COOP/COEP) e alternativas rejeitadas estão documentadas com transparência na `ADR-015`, mantendo exportação offline CVXPY/YALMIP. | CONFORME |

---

## 5. Parecer Formal da Frente F9

- **Veredito F9**: `accepted`
- **Revisor independente**: `f9-integration-qa`
- **Commit SHA auditado**: `bdc74e987356274c9a56c411f2ac35ce3b801770`
- **Data (UTC)**: `2026-11-23T03:35:00Z`
- **Justificativa**: `ADR-015` formaliza de maneira tecnicamente completa, referenciada e governada o roadmap Fase 9 (`Phase9-Native-SDP-Scalability-v2`) como complemento direto da `ADR-010`, preservando 100% o modelo *zero-install* NumPy/SciPy em Pyodide e a invariante de verificação 5D independente no problema original. Todos os 12 WorkPackages e a decisão `ADR-015` foram validados em `PROJECT_STATE.json` via `scripts/project_governance.py`.
