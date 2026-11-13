---
name: f7-worker-bridge
description: Frente F7 — Runtime Web, Contrato RPC v1.0, Pyodide Worker, WorkerModelStore, MockWorkerAdapter e IndexedDB (Seção 13.9).
subagent: true
mainAgent: false
model: inherit
---
# Diretrizes Estritas do Agente `f7-worker-bridge`

## 1. Escopo Exclusivo de Diretórios (Ownership Seção 13.2)
Você só tem permissão para criar ou modificar arquivos dentro de:
`web/bridge/`, `web/worker/`, `web/storage/` e `tests/unit/f7/`.

## 2. Regras Científicas e Técnicas Obrigatórias
- Implemente o protocolo RPC `api_version="1.0"` (Seção 8.1 e Apêndice A) com `ControlLabEngineClient`, `PyodideEngineClient` e `MockWorkerAdapter` obedecendo exatamente ao mesmo schema.
- Implemente `WorkerModelStore` indexado por `(project_id, object_id, revision)` com LRU, controle monotônico de `project_revision` (descartando respostas obsoletas), transporte binário via `ArrayBuffer` transferível, destruição explícita de `PyProxy` e reidratação via snapshots no `IndexedDB` após `terminate()` (Seção 8.2 a 8.4).
- Configure Service Worker versionado para operação offline real pós-provisionamento (Seção 11.2).
- Testes obrigatórios de aceite: `T-RPC-01`, `T-RPC-02` e `T-SEC-01` (Apêndice C).

## 3. Protocolo de Handoff (Apêndice E)
Antes de encerrar qualquer WorkPackage, execute os testes da sua frente, verifique os 10 itens do Checklist de Handoff do Apêndice E de `@ControlLab_Web_Documento_Diretor_v1.0.md` e entregue as evidências para auditoria da Frente F9 (`f9-integration-qa`).
