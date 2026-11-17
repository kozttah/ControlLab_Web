# LICENSE-MIT-2026-11-17 — adoção MIT e preservação de terceiros

Base auditada: `fd9ebe7adebc4a9924cce216b7831b0799dfd69a` mais o incremento de licenciamento desta entrega. Data UTC: 2026-11-17. Norma: CL-DIR-001, DEC-OPEN-05 e ADR-011. Autoridade: pedido explícito do coordenador para avaliar MIT e incluir licença padrão, autoria e ausência de garantia.

## Entrega e evidências

Produtor: `/root/f9_license_implementation`. Inventário independente das dependências: `/root/f9_license_inventory`. Revisor separado: `/root/f9_independent_review`. O Maestro integra os registros e ajusta links de documentos para funcionarem no repositório e na cópia estática.

MIT aplica-se ao código e à documentação originais, com texto padrão em LICENSE e copyright de Víctor Campos e contribuidores. A citação acadêmica de CITATION.cff é voluntária. Bibliotecas mantêm seus termos, incluindo MPL-2.0 de Pyodide/micropip; os avisos e acesso aos fontes correspondentes acompanham a distribuição. O inventário distingue o bundle Wasm dos ambientes CPython e ferramentas externas, incluindo a exceção de runtime GCC quando presente nos wheels CPython.

- Testes `tests/oracles/test_build_pipeline.py`: cinco aprovados pelo produtor e repetidos independentemente pelo revisor, incluindo wheel real, METADATA, licença incorporada, notice upstream byte a byte e SBOM sem relicenciamento de terceiros.
- Ruff dos dois arquivos Python alterados e mypy do build aprovados.
- Dois builds reproduzíveis com hashes idênticos e 42 assets íntegros. O build foi repetido pelo Maestro após os últimos ajustes de links legais.
- Revisor verificou License-Expression MIT, License-File LICENSE, bytes da licença e RECORD da wheel; os avisos de terceiros foram preservados.
- Governança: 39 WorkPackages, 34 aceitos e cinco pendentes; nenhuma promoção de pacote ou gate nesta decisão.
- Fixtures ouro, tolerâncias, módulos científicos e bytes/hashes fixados no lock Pyodide intactos. Documentos Diretor raiz/espelho idênticos.

## Checklist de Handoff — Apêndice E

| Item | Questão | Resposta | Evidência | Auditoria F9 |
| --- | --- | --- | --- | --- |
| 1 | Contratos e consumidores | SIM | APIs científicas e RPC intactas; alteração em licença/metadados e distribuição. | CONFORME |
| 2 | Diagnósticos e proveniência | SIM | ADR-011 e inventário delimitam autoria, versões e direitos dos componentes. | CONFORME |
| 3 | Referência antes da implementação | SIM | Textos de licença e fontes oficiais versionadas examinados antes da decisão. | CONFORME |
| 4 | Verificação independente | SIM | Inventariante e revisor separados do produtor; cinco testes de packaging repetidos pelo revisor. | CONFORME |
| 5 | Ownership e ouro | SIM | Arquivos de governança F9; ownership de LICENSE/CITATION registrado; ouro e tolerâncias intactos. | CONFORME |
| 6 | CPython/Pyodide | ESCOPO | Wheel CPython e distribuição Wasm verificadas por metadados, hashes e avisos; nenhuma nova homologação numérica anunciada. | CONFORME |
| 7 | Schema e migração | N/A | Nenhum schema científico ou de projeto foi alterado; PEP 639 usado nos metadados de licença. | N/A |
| 8 | Artefatos reproduzíveis | SIM | Dois builds idênticos, 42 assets e licença na wheel/distribuição; arquivos de terceiros preservados. | CONFORME |
| 9 | Maturidade | SIM | Produto beta e release_approved=false preservados. Licença não altera classificação científica. | CONFORME |
| 10 | Limites e acompanhamento | SIM | MIT não relicencia terceiros; inventário não declara auditoria jurídica exaustiva ou clearance de vulnerabilidades. | CONFORME |

## 5. Parecer F9

- Revisor independente: `/root/f9_independent_review`.
- Commit SHA auditado: `fd9ebe7adebc4a9924cce216b7831b0799dfd69a` mais incremento de licenciamento identificado nesta entrega.
- Data (UTC): 2026-11-17.
- Veredito F9: accepted
- Escopo: adoção MIT para material original e empacotamento dos avisos de terceiros das versões examinadas. A decisão não configura mudança de visibilidade do repositório, publicação Pages ou release estável.
