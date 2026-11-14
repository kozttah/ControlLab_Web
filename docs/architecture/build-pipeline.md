# Build e CI — WP-AUDIT-FIX-F9-BUILD-CI

## Contrato e reprodução

Ambiente de referência: Python 3.12.14, Node 24.22.1, setuptools 84.2.1, TypeScript 5.8.3, esbuild 0.25.5. Instalar `python -m pip install -r scripts/requirements-ci.lock` e `npm --prefix web ci`. Os requisitos Python fixam a resolução CPython usada em CI; os requisitos públicos da biblioteca preservam as faixas científicas, permitindo o NumPy/SciPy da distribuição Wasm selecionada. Os pacotes opcionais CVXPY/Clarabel CPython não são prometidos em Pyodide.

`npm --prefix web run build` monta wheel real, bundles ESM e recursos estáticos em `web/dist/`. O wheel é produzido por setuptools em árvore temporária, com `SOURCE_DATE_EPOCH=1735689600`, membros ordenados, datas/permissões fixadas. Não usa resultados científicos para gerar fixtures. `python scripts/check_reproducible.py` executa duas compilações e compara o manifesto completo; cada entrada compara SHA-256 e tamanho do arquivo. O manifesto omite o próprio hash para evitar autorreferência. O ambiente deve ser o mesmo nas duas execuções; não se promete identidade de compactação entre runtimes Python/zlib arbitrários.

Entradas: `web/app/main.ts`, `web/worker/pyodide_worker.ts`, `web/worker/service_worker.ts`, HTML/CSS F8, `control_lab`, pyproject e locks. Saídas: `index.html` na raiz; `app/main.js`, `app/styles.css`; `worker/pyodide_worker.js`; `service_worker.js` na raiz; `wheels/control_lab-1.0.0-py3-none-any.whl`; recursos Pyodide em `pyodide/`. Os bundles conservam `import.meta.url` e importação dinâmica do loader local; o layout serve também sob prefixo, conforme contrato F8. O Service Worker fonte mantém seu manifesto antigo até WP-AUDIT-FIX-F7-OFFLINE-SW: o inventário deste build será entrada para esse WP, sem alterar ownership F7.

## Provisionamento e integridade

O lock `scripts/pyodide-assets.lock.json` fixa Pyodide 0.27.5, Python Wasm 3.12.7, ABI 2024_0. Inclui loader JS/MJS, asm.js, Wasm, stdlib e lock oficial, mais a clausura transitiva NumPy 2.0.2, SciPy 1.14.1, OpenBLAS 0.3.26, micropip 0.8.0 e packaging 24.2. São 11 arquivos upstream reais e 36.678.144 bytes. Os hashes dos pacotes conferem com o lock oficial; os demais hashes são dos bytes baixados. `scripts/lock_pyodide.py` é uma operação explícita de manutenção; builds normais nunca regeneram pins.

O primeiro build exige rede para arquivos ausentes do cache. O cache padrão fica em `~/.cache/controllab-build`; `CONTROLLAB_ASSET_CACHE` pode escolher outro diretório. Cada leitura de cache verifica SHA-256; divergências falham sem substituição silenciosa. Uma árvore de cache completa permite montar o inventário sem download. Isso demonstra suficiência dos ativos locais e integridade, não execução offline no navegador. `python scripts/build_release.py --verify` rejeita arquivo alterado, ausente ou extra e confere novamente o lock runtime. O processo ainda não substitui assinatura/autenticidade do manifesto por infraestrutura de release.

`sbom.json` usa CycloneDX 1.6 e registra componentes distribuídos, hashes dos wheels, origens e ferramentas npm; os avisos de licença presentes nos ZIPs/wheels são copiados com seus bytes intactos. Licença do projeto e classificações não verificadas permanecem NOASSERTION. A avaliação jurídica e de vulnerabilidades continua pendente em `docs/legal/DEPENDENCIES.md`.

## Jobs A–G e maturidade

| Job | Execução | Limite explícito |
|---|---|---|
| A | ruff format dos novos scripts/teste build; mypy pragmático dos scripts; import RPC/NumPy/SciPy; pip check | Não reformata nem reivindica tipagem integral dos módulos científicos F1–F8 |
| B | Matriz de venvs isolados: core_no_sdp executa todos F1–F5 + oráculos/integração; sdp_available executa todos F6 + oráculos; ambos verificam fixtures | Pré-condições opcionais assertadas, nenhum teste científico excluído/pulado; propriedades/metamórficos de navegador pendentes |
| C | TS typecheck, testes F7/F8 e integração/oráculos Node | Doubles/mocks não provam Wasm |
| D | suites reais `tests/wasm` + `tests/performance` | Falha código 2 se ausentes |
| E | suite `tests/e2e` | Falha código 2 se ausente; PathView oficial pendente |
| F | npm audit + suite `tests/security` | Falha código 2 se ausente; auditoria Python/segurança completa pendente |
| G | dois builds, verificação de hashes, upload dos artefatos, depois gates reais | Artefatos gerados mesmo com release bloqueado; falha código 2 por suites faltantes |

Todos preservam logs via `pipefail` + `tee` e upload `always`; D–G registram também JSON de bloqueio. Suites obrigatórias vazias, puladas ou xfail não aprovam os gates. Actions usam SHAs de commit imutáveis resolvidos nas refs oficiais GitHub em 2026-11-14 (checkout v4, setup-python v5, setup-node v4, upload-artifact v4); os controles de branch/ruleset e a execução remota do workflow exigem configuração do servidor e não são comprovados por esta entrega local.

O manifesto declara `release_approved=false`, `web_maturity=experimental`, `browser_offline_validated=false` e gates pendentes G-0A/B/C/D, browser-Wasm/integração/segurança. Este WP entrega infraestrutura de build, não aprovação Web stable. Os WPs Wasm e Offline devem fornecer execução em Chromium/Firefox, paridade numérica, cache transitivo íntegro e ensaio real sem rede; a auditoria independente F9 decide o aceite.

## Matriz matemática e dependências opcionais

O teste F1 `test_rpc_multidomain_integration_against_approved_fixtures` exige explicitamente ambiente sem Clarabel para testar `SOLVER_UNAVAILABLE`. Essa pré-condição é preservada sem alterar F1 nem excluir o teste. Job B cria um venv limpo por perfil e usa `scripts/ci_math.py`:

- `core_no_sdp`: `scripts/requirements-core.lock`, `find_spec("clarabel")` e `find_spec("cvxpy")` obrigatoriamente ausentes; todos os arquivos Python em F1–F5, oráculos e integração executam completos.
- `sdp_available`: `scripts/requirements-ci.lock`, ambos módulos presentes e `clarabel_direct`/`clarabel_cvxpy` com `available=true`; todos os arquivos Python F6 e os mesmos oráculos executam completos.

O harness exige venv sem user-site e rejeita qualquer skip/xfail/coleção vazia, preservando JUnit e JSON de pré-condições/resultados. F7/F8 TypeScript continuam inteiros em C. Executar a união cega de F1–F6 em um único ambiente não satisfaz essas pré-condições conflitantes. A matriz executa cada arquivo no ambiente que seu contrato requer.

Os dois locks foram conferidos contra `importlib.metadata` de venvs reais: core tem 21 distribuições/18 arestas de dependência ativas; SDP tem 34 distribuições/43 arestas. Todos os pacotes instalados, inclusive pip 25.0.1, têm pin exato. O lock SDP inclui os transitivos efetivamente observados CFFI 2.1.1, pycparser 3.12, cloudpickle 3.1.2 e joblib 1.6.0. `scripts/check_python_lock.py` rejeita pacote extra/ausente, versão divergente ou requisito transitivo ativo sem pin compatível; o harness B executa essa verificação antes dos testes. Estes locks fixam a resolução Python 3.12/Linux de referência; hashes dos wheels nativos Python ainda não integram esses arquivos, enquanto npm e ativos Pyodide possuem hashes próprios.
