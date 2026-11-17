# ADR-011 — Licença MIT do código original e avisos de terceiros

Data: 2026-11-17. Decisão do coordenador: adotar uma licença permissiva padrão, com preservação de autoria e ausência de garantia. Estado: aceito para o código original do ControlLab Web. Esta ADR resolve a escolha da licença própria em DEC-OPEN-05; o cumprimento das licenças de terceiros continua obrigatório a cada distribuição.

## Decisão

O código original e a documentação original do ControlLab Web são disponibilizados sob a licença MIT, cujo texto padrão integral está em `LICENSE`. Copyright (c) 2026 Víctor Campos and ControlLab Web contributors. Essa declaração não transfere nem reivindica a titularidade de componentes de terceiros ou de contribuições sobre as quais o projeto não detenha direitos.

A MIT permite uso, estudo, modificação, redistribuição e uso comercial, inclusive incorporação em produtos proprietários, desde que os avisos de copyright e de permissão sejam preservados nas cópias ou porções substanciais do software. O texto padrão contém ausência de garantia e limitação de responsabilidade; nenhuma garantia adicional de funcionamento, adequação ou suporte é oferecida pelo projeto. A aplicação dessas cláusulas depende da legislação aplicável.

A citação acadêmica indicada em `CITATION.cff` é um pedido voluntário. Não é condição adicional de licença, nem obrigação de atribuição em toda publicação ou interface. A obrigação MIT é preservar os avisos previstos no texto da licença.

## Dependências

Dependências não são relicenciadas como MIT pelo ControlLab. NumPy/SciPy, CPython, OpenBLAS, Pyodide, micropip e demais componentes mantêm seus titulares, textos e obrigações. O copyleft da MPL-2.0 de Pyodide/micropip incide sobre os arquivos cobertos e suas modificações; a combinação com o código separado do ControlLab não transforma este automaticamente em GPL ou MPL. Os avisos e acesso ao código-fonte das versões distribuídas devem acompanhar os binários cobertos.

O inventário versionado está em `docs/legal/THIRD_PARTY_LICENSES.md`. Textos preservados, fontes e instruções de redistribuição estão em `docs/legal/`. Os pacotes opcionais CPython, ferramentas de teste/build e o simulador externo são distinguidos do bundle Web. Introdução de nova dependência ou inclusão de código de terceiros exige revisar o inventário e a compatibilidade; esta decisão não é autorização geral para relicenciar componentes futuros.

## Distribuição e limites

Os metadados Python usam a expressão SPDX MIT e incluem o arquivo LICENSE na wheel; o pacote npm declara MIT. O SBOM identifica somente o componente próprio `control-lab` como MIT. O build mantém os avisos extraídos dos archives de terceiros e inclui os avisos e licenças adicionais documentados. Não substitui os metadados de terceiros por MIT nem modifica os bytes fixados dos assets Pyodide.

Esta ADR não concede certificação jurídica integral, clearance de vulnerabilidades ou promoção a release estável. Os gates, a maturidade beta, os critérios científicos e as licenças de terceiros permanecem independentes. A mudança de visibilidade do repositório e a publicação via GitHub Pages são ações separadas desta adoção de licença.
