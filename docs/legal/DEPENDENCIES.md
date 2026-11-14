# Inventário e licença

A licença do projeto permanece **NOASSERTION**, conforme DEC-OPEN-05; este pipeline não concede licença de software. A distribuição não está aprovada para release.

O inventário gerado `sbom.json` registra versões, origens e metadados npm. `release-manifest.json` registra hashes SHA-256 e tamanhos de todos os arquivos publicados, exceto o próprio manifesto (evitando autorreferência). `scripts/pyodide-assets.lock.json` fixa os bytes reais da distribuição 0.27.5; essa versão é uma escolha de compatibilidade com Python 3.12, não uma alegação de versão mais recente. Os hashes dos pacotes são também confrontados com o lock oficial Pyodide.

Componentes entregues: Pyodide 0.27.5, NumPy 2.0.2, SciPy 1.14.1, OpenBLAS 0.3.26, micropip 0.8.0, packaging 24.2. Os arquivos de licença encontrados dentro dos wheels/ZIPs distribuídos são preservados em `legal/third-party/`, com nome de origem e bytes intactos. Campos de licença permanecem NOASSERTION até classificação jurídica, evitando inferir uma licença única para pacotes que incorporam terceiros. O loader Pyodide e a stdlib incorporam componentes adicionais; o inventário não equivale a uma auditoria jurídica completa ou a clearance de vulnerabilidades.

Fontes fixadas: https://cdn.jsdelivr.net/pyodide/v0.27.5/full/pyodide-lock.json e arquivos individuais do mesmo diretório, registrados no lock. Licenças npm são provenientes do package-lock; esbuild e TypeScript são ferramentas de build, não módulos carregados pelo app. Clarabel/CVXPY são dependências CPython opcionais de teste, não fornecidas no Wasm. Plotly não é dependência deste bundle. IEEE 1855-2016 não tem seu texto redistribuído; interoperabilidade FML não concede direitos sobre o padrão. PathView externo ainda requer validação de versão e licenças próprias.

Pendências de release: revisão independente do inventário/licenças, scanner de vulnerabilidades e dependências, gates Wasm/offline, segurança CSP/ZIP/XML/XSS em navegador real, integração PathView. A ausência destas evidências bloqueia Jobs D–G; um build bem sucedido não libera o produto.
