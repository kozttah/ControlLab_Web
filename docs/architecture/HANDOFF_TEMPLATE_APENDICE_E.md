# Formulário Padrão de Handoff e Auditoria F9 — Apêndice E (`CL-DIR-001`)

**Identificador normativo:** `CL-DIR-001` (v1.0.0) — Seções 10.5, 13.11, 13.12, 14.1, 15.2, 15.3 e Apêndice E  
**Guardiã independente:** Frente `F9` (`f9-integration-qa`)  
**Achados endereçados:** `AUD-013`, `AUD-012` (`REM-01`)  
**Local padrão dos dossiês por WorkPackage:** `docs/audits/handoffs/<WP_ID>.md`

---

## 1. Regras Inegociáveis de Governança e Evidência (`AUD-013`)

1. **Proibição de `ACCEPTED_BY_F9` sem artefato auditável:** Nenhum WorkPackage (`WP-*`) pode receber `"status": "ACCEPTED_BY_F9"` e `"f9_review": "accepted"` em `PROJECT_STATE.json` sem possuir um dossiê completo em `docs/audits/handoffs/<WP_ID>.md` referenciado via `"handoff_ref"`, com os **10 itens do Apêndice E** respondidos objetivamente e **evidência verificável de ambiente, versões, commit SHA e saída integral dos comandos de aceite**.
2. **Proibição de rótulo `stable` Web sem prova Wasm/Pyodide e CI:** Em conformidade com as Seções 10.5 e 15.2 de `CL-DIR-001`, nenhuma operação ou módulo pode anunciar `"maturity": "stable"` para execução no navegador sem (i) paridade CPython/Pyodide comprovada em ambiente Wasm real, (ii) execução da suíte aplicável em navegador (`Job D`/`E`/`F`), (iii) ausência de fallbacks sintéticos (`AUD-001`) e (iv) revisão independente F9.
3. **Escopo restrito de aceite local CPython:** Quando um WorkPackage científico for aprovado apenas em CPython nativo antes da integração Wasm/Web (ex.: `WP-02`, `WP-07`, `WP-08`), o dossiê e `PROJECT_STATE.json` DEVEM explicitar `"acceptance_scope": "cpython_local_only"` e listar os `release_blocker_wps` abertos; esse aceite local **não** equivale à liberação `stable` Web.
4. **Proibição de decisões informais ou alterações cruzadas silenciosas:** Decisões de produto que alterem contratos, semântica matemática, tolerâncias ou escopo exigem ADR formal e revisão cruzada F9 — nunca acordo implícito ou edição cruzada de módulos/mocks/fixtures ouro.
5. **Não-circularidade e preservação de oráculos:** A F9 nunca gera *expected values* diretamente a partir do código produtor sob teste e nunca altera fixtures ouro em `contracts/fixtures/` ou tolerâncias de `tests/oracles/` para forçar passagem de testes.

---

## 2. Formulário de Cabeçalho Obrigatório (Apêndice E)

Copie este bloco integralmente para `docs/audits/handoffs/<WP_ID>.md` e preencha todos os campos antes de submeter à auditoria independente F9:

```markdown
# Dossiê de Handoff e Auditoria F9 — <WP_ID>

## 1. Cabeçalho da Tarefa (Apêndice E)

| Campo Obrigatório | Valor / Referência |
| :--- | :--- |
| **WorkPackage ID** | `<WP_ID>` |
| **Requisito(s) R** | `<R-XX, ...>` |
| **Achado(s) / REM vinculado(s)** | `<AUD-XXX / REM-XX ou N/A>` |
| **Frente F** | `<f1-core-io | ... | f9-integration-qa>` |
| **Módulo / caminhos permitidos (`allowed_paths`)** | `<lista exata de diretórios/arquivos permitidos>` |
| **Contratos consumidos** | `<schemas JSON, protocolos RPC, tipos canônicos>` |
| **Entradas / saídas** | `<assinaturas, formatos, envelopes Result/RPC>` |
| **Hipótese matemática** | `<premissas, domínio de validade, invariantes numéricos>` |
| **Limite da implementação** | `<escopo exato provado vs não coberto (ex.: CPython local vs Wasm/Browser/PathView)>` |
| **Testes de aceite** | `<comando acceptance_cmd, testes unitários, regressão e IDs T-*>` |
| **Fixtures** | `<B-CARE-02, B-CARE-12x3, etc. ou N/A>` |
| **Dependências** | `<WP_IDs das dependências e seus status atuais>` |
| **Bloqueadores** | `<Gates G-0A..G-0D, WPs subsequentes, ou Nenhum>` |
| **Evidência / PR esperado** | `<commit SHA base/entrega, branch/PR, ambiente (OS/Python/Node/tsc/browser), logs>` |
| **Risco** | `<Baixo | Médio | Alto | Crítico — justificativa e mitigação>` |
| **Nível de maturidade pretendido** | `<stable | beta | experimental | unavailable_wasm>` (distinguindo CPython local vs Web/Wasm) |
```

---

## 3. Checklist de Handoff de 10 Itens (Apêndice E — Redação Normativa Integral)

Todos os 10 itens abaixo são obrigatórios. Respostas `"N/A"` exigem justificativa objetiva do porquê não se aplica ao WorkPackage.

| # | Pergunta Normativa (Apêndice E — `CL-DIR-001`) | Resposta Produtor (`SIM` / `NÃO` / `PARCIAL` / `N/A`) | Evidência Objetiva (arquivo, linha, teste, comando, SHA) | Auditoria F9 |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **2** | **Saída contém status, diagnósticos e proveniência, inclusive casos de falha?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **3** | **Testes analíticos foram escritos antes da otimização prematura?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **4** | **Existe confronto independente da implementação, em vez de autorreferência?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **5** | **O PR respeita ownership e não modificou mocks/expected values para esconder defeito?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **6** | **O mesmo teste funciona em CPython e Pyodide no domínio anunciado?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **7** | **Alterações de schema tiveram migração/versão e revisão F9?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **8** | **Logs, matrizes de fixture e resultados de benchmark foram anexados?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **9** | **Um método experimental permanece visualmente classificado como tal?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |
| **10** | **Qualquer limitação conhecida tem issue e mensagens de falha adequadas?** | `<...>` | `<...>` | `<CONFORME / PENDENTE / FALHA>` |

---

## 4. Registro de Ambiente, SHA e Saída de Execução (Obrigatório)

Todo dossiê deve anexar seção reproduzível contendo:
- **Commit SHA auditado** (`git rev-parse HEAD`) e `git status --short` comprovando estrita aderência a `allowed_paths`.
- **Ambiente exato**: SO/arquitetura, versão de Python, NumPy, SciPy, pytest, jsonschema, Clarabel/CVXPY (quando aplicável), Node.js, TypeScript (`tsc --version` ou ausência explícita documentada), navegador/Playwright/Pyodide/PathView (quando aplicável).
- **Comandos executados e saída integral** (`acceptance_cmd`, testes de regressão e testes normativos `T-*`).

---

## 5. Parecer Independente da Frente F9 (4 Vereditos Possíveis)

A seção final do dossiê é preenchida e assinada **exclusivamente** pela Frente `F9` (`f9-integration-qa`) após auditoria independente:

| Veredito F9 (`f9_review`) | Status Correspondente em `PROJECT_STATE.json` | Condições Normativas |
| :--- | :--- | :--- |
| **`accepted`** | `ACCEPTED_BY_F9` | Todos os critérios do WP atendidos; 10 itens do checklist auditados com evidência; se restrito a CPython local, `acceptance_scope: "cpython_local_only"` e `release_blocker_wps` declarados explicitamente. |
| **`changes_requested`** | `CHANGES_REQUESTED` | Falha técnica, matemática, contratual, de compilação/runner, ou ausência de evidência auditável. Lista correções e testes obrigatórios antes de nova submissão. |
| **`blocked_by_gate`** | `BLOCKED_BY_GATE` | Implementação local aceita no escopo interno, porém promoção/liberação bloqueada por gate externo (`G-0A`, `G-0B`, `G-0C` ou `G-0D`) ainda `PENDING`. |
| **`rejected_with_evidence`** | `REJECTED_WITH_EVIDENCE` (ou `CHANGES_REQUESTED` com evidência formal de rejeição) | Violação grave de ownership, alteração indevida de fixture ouro/tolerância, resposta científica falsa ou evidência contraditória comprovada com contraexemplo. |

```markdown
## 5. Parecer Independente da Frente F9

- **Veredito F9 (`accepted` | `changes_requested` | `blocked_by_gate` | `rejected_with_evidence`):** `<PENDENTE / ...>`
- **Escopo aprovado (`acceptance_scope`):** `<...>`
- **Revisor independente:** `f9-integration-qa`
- **Commit SHA auditado:** `<...>`
- **Data (UTC):** `<YYYY-MM-DD>`
- **Testes e artefatos validados independentemente pela F9:** `<...>`
- **Pendências / Bloqueadores remanescentes:** `<...>`
```
