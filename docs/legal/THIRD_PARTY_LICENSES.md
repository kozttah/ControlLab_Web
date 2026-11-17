# Inventário de licenças de terceiros

Revisão em 17/11/2026 para a adoção de MIT no código original do ControlLab Web. Fontes examinadas: `scripts/pyodide-assets.lock.json`, os bytes dos arquivos efetivamente montados em `web/dist/pyodide/`, licenças extraídas em `web/dist/legal/third-party/`, `web/package-lock.json` e metadados das distribuições CPython fixadas nos locks. A análise distingue execução, redistribuição e ferramentas de desenvolvimento.

## Conclusão de compatibilidade

As dependências examinadas não exigem que o código original independente do ControlLab seja licenciado sob GPL. MIT pode ser adotada para esse código, mantendo os direitos e as licenças dos componentes de terceiros. A distribuição completa do site é uma combinação de componentes sob licenças distintas, e não passa a ser integralmente MIT.

Pyodide e micropip usam MPL-2.0. O copyleft dessa licença aplica-se aos arquivos cobertos e às suas modificações; arquivos próprios independentes podem manter MIT. Ao distribuir as versões executáveis/minificadas, é necessário indicar onde obter o código-fonte correspondente, além de preservar os avisos e os direitos MPL. Essa distinção está descrita nas seções 3.1–3.4 da [MPL-2.0](https://www.mozilla.org/en-US/MPL/2.0/) e nas perguntas 8, 10 e 11 do [FAQ oficial da Mozilla](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).

## Componentes distribuídos no navegador

| Componente | Versão fixada | Licença principal | Evidência e obrigação de distribuição |
| --- | --- | --- | --- |
| Pyodide, loader e runtime | 0.27.5 | MPL-2.0, com componentes incorporados sob seus próprios termos | [LICENSE da versão](https://github.com/pyodide/pyodide/blob/0.27.5/LICENSE), [fonte correspondente](https://github.com/pyodide/pyodide/tree/0.27.5). Distribuir aviso MPL e informar acesso ao fonte. Não houve modificação dos assets fixados pelo ControlLab. |
| micropip | 0.8.0 | MPL-2.0 | Texto completo em `micropip-0.8.0.dist-info/LICENSE`, dentro do wheel fixado, e [fonte da versão](https://github.com/pyodide/micropip/tree/v0.8.0). Mesmas obrigações MPL para os arquivos cobertos. |
| CPython e biblioteca padrão | 3.12.7, incorporado ao Pyodide | PSF-2.0 e termos históricos/incorporados preservados pelo projeto Python | Versão em `runtime.python` do lock. [LICENSE correspondente](https://github.com/python/cpython/blob/v3.12.7/LICENSE) e [licenças/acknowledgements](https://docs.python.org/3.12/license.html). Preservar os termos e os copyrights aplicáveis. |
| NumPy | 2.0.2 | BSD-3-Clause, com avisos adicionais dos componentes internos | `numpy-2.0.2.dist-info/LICENSE.txt`, `numpy/random/LICENSE.md`, `numpy/_core/include/numpy/random/LICENSE.txt` e `numpy/ma/LICENSE` no wheel. [Fonte correspondente](https://github.com/numpy/numpy/tree/v2.0.2). Preservar todos esses avisos. |
| SciPy | 1.14.1 | BSD-3-Clause e licenças específicas de componentes internos | `scipy-1.14.1.dist-info/LICENSE.txt` e avisos de `_uarray`, PocketFFT, ARPACK e Qhull no wheel. [Fonte correspondente](https://github.com/scipy/scipy/tree/v1.14.1). Preservar textos e avisos incorporados, inclusive condições específicas do Qhull. |
| OpenBLAS | 0.3.26 | BSD-3-Clause, com componentes BLAS/LAPACK incorporados | [LICENSE correspondente](https://github.com/OpenMathLib/OpenBLAS/blob/v0.3.26/LICENSE), [fonte correspondente](https://github.com/OpenMathLib/OpenBLAS/tree/v0.3.26), [receita de build do pacote](https://github.com/pyodide/pyodide/tree/0.27.5/packages/openblas). Preservar copyright, condições, disclaimer e avisos dos componentes incorporados. |
| packaging | 24.2 | Apache-2.0 OR BSD-2-Clause | O wheel contém `licenses/LICENSE`, `LICENSE.APACHE` e `LICENSE.BSD`. [Fonte correspondente](https://github.com/pypa/packaging/tree/24.2). A opção BSD é compatível com a composição MIT; o build preserva os três textos. |

Os quatro wheels NumPy/SciPy/micropip/packaging já contêm textos de licença, extraídos sem alteração pelo build. A auditoria dos bytes detectou que `openblas-0.3.26.zip` e `python_stdlib.zip` **não contêm arquivo com basename LICENSE/COPYING/NOTICE**. O loader Pyodide também não possui um arquivo standalone de licença entre os assets listados no lock. Portanto, somente a extração automática desses arquivos não basta: a distribuição precisa acompanhar os textos e avisos adicionais em `legal/` e os caminhos para as fontes correspondentes. Esses avisos complementares não alteram os hashes dos assets fixados.

O runtime informa Emscripten 3.1.58. As receitas/fontes Pyodide e a documentação de licenças do Python são referências para os componentes incorporados ao runtime. Não se deve inferir, a partir da licença principal do pacote, que todo o binário está coberto por uma única licença; preservação dos avisos incorporados e reavaliação a cada atualização continuam necessárias. Este inventário não declara uma análise jurídica exaustiva de cada objeto vinculado ao runtime, nem uma auditoria de vulnerabilidades.

## Pacotes CPython opcionais e ferramentas de testes

Esses pacotes são instalados nos ambientes de desenvolvimento/CI ou no ambiente externo de interoperabilidade. Não são copiados para a wheel `control_lab` nem incluídos no bundle browser atual. As versões do ambiente científico estão em [`requirements-ci.lock`](https://github.com/kozttah/ControlLab_Web/blob/main/scripts/requirements-ci.lock); as do ambiente externo em [`requirements-pathview.lock`](https://github.com/kozttah/ControlLab_Web/blob/main/scripts/requirements-pathview.lock) e [`requirements-browser.lock`](https://github.com/kozttah/ControlLab_Web/blob/main/scripts/requirements-browser.lock).

| Grupo | Pacotes e versões examinadas | Licenças principais nos metadados/textos instalados |
| --- | --- | --- |
| Solvers opcionais | CVXPY 1.9.3, Clarabel 0.11.1, OSQP 1.1.3, QDLDL 0.1.9.post1, sparsediffpy 0.6.1 | Apache-2.0 |
| Solvers opcionais | highspy 1.16.0, SCS 3.3.1 | MIT |
| Numérico local | NumPy 2.3.5, SciPy 1.17.0 | BSD-3-Clause; wheels nativos incorporam avisos adicionais, descritos abaixo |
| Simuladores externos | PathSim 0.31.0, PathView 0.21.0 | MIT, conforme os textos/metadados das distribuições dessas versões; [PathSim](https://github.com/pathsim/pathsim), [PathView](https://github.com/pathsim/pathview) |
| Browser de teste | Playwright 1.58.0, pyee 13.0.1, greenlet 3.5.6 | Apache-2.0, MIT e MIT AND PSF-2.0, respectivamente; os navegadores executados como ferramentas externas têm seus próprios avisos |
| Gráficos do simulador externo | Matplotlib 3.10.8 | Licença Matplotlib baseada na licença PSF, com avisos próprios/incorporados; [termos oficiais](https://matplotlib.org/stable/project/license.html) |
| Ferramentas Python MIT | attrs 26.1.0; build 1.6.1; iniconfig 2.3.1; jsonschema 4.26.0; jsonschema-specifications 2025.9.1; mypy 1.15.0; mypy_extensions 1.1.0; pip 25.0.1; pluggy 1.7.0; pyproject_hooks 1.3.3; pytest 9.2.0; referencing 0.37.0; rpds-py 2026.9.1; ruff 0.11.13; setuptools 84.2.1; wheel 0.48.0 | MIT |
| Utilitários Python BSD | cloudpickle 3.1.2; joblib 1.6.0; Jinja2 3.1.6; MarkupSafe 3.0.4; pycparser 3.12 | BSD-3-Clause |
| Outros utilitários | cffi 2.1.1; Pygments 2.21.0; packaging 26.3; typing_extensions 4.16.0 | MIT-0; BSD-2-Clause; Apache-2.0 OR BSD-2-Clause; PSF-2.0, respectivamente |
| Servidor usado somente na auditoria externa | Flask 3.1.3, Werkzeug 3.1.9, Jinja2 3.1.6, MarkupSafe 3.0.4, itsdangerous 2.2.0; blinker 1.9.0, flask-cors 6.0.5; waitress 3.0.2 | BSD-3-Clause; MIT; ZPL-2.1, respectivamente |

Os textos completos `numpy-2.3.5.dist-info/LICENSE.txt` e `scipy-1.17.0.dist-info/LICENSE.txt` do ambiente CPython examinado incluem **libgfortran sob GPL com GCC Runtime Library Exception 3.1**. A presença da palavra GPL nesses avisos não implica que o ControlLab deva adotar GPL: a exceção permite combinar o runtime com módulos independentes nas condições indicadas. O runtime permanece sob sua própria licença; a exceção não o relicencia sob MIT nem elimina suas obrigações de redistribuição. [Texto oficial da exceção](https://gcc.gnu.org/onlinedocs/libstdc++/manual/license.html). Esses wheels CPython não são os wheels Wasm distribuídos, nos quais os mesmos avisos não foram encontrados. Uma futura distribuição de um ambiente CPython completo exige preservar também os avisos e obrigações desses binários.

As licenças principais da tabela foram conferidas nos metadados/textos das distribuições instaladas. Os pacotes externos podem incorporar fontes, fontes tipográficas, imagens e subdependências com avisos adicionais. Uma versão futura que passe a redistribuí-los, ou a embutir o frontend PathView, precisa de inventário dos bytes efetivamente distribuídos, em vez de reaproveitar somente os rótulos principais acima.

## Ferramentas JavaScript de build

[`web/package-lock.json`](https://github.com/kozttah/ControlLab_Web/blob/main/web/package-lock.json) fixa TypeScript **5.8.3**, sob **Apache-2.0**, e esbuild **0.25.5**, sob **MIT**, incluindo seus pacotes binários opcionais por plataforma sob MIT. Eles são ferramentas do build; o app não carrega TypeScript ou o executável esbuild como bibliotecas de runtime. O bundle produzido não depende de Plotly, Monaco, MathJax ou do frontend PathView.

## Regras para alterações futuras

1. A licença MIT do código original não substitui os textos de terceiros. Preservar avisos, copyrights e acesso ao fonte MPL na distribuição estática, inclusive quando minificada.
2. Não copiar arquivos MPL para novos arquivos próprios e classificá-los automaticamente como MIT. Modificações em arquivos cobertos continuam MPL.
3. Atualizações de versão, novas bibliotecas, novos assets ou redistribuição de ferramentas exigem nova conferência dos bytes e dos avisos. O SBOM e os hashes são inventário técnico, não concessão de direitos.
4. Nenhum texto normativo IEEE 1855 é redistribuído pelo projeto. Interoperabilidade FML não concede licença sobre o texto do padrão.
5. A preservação obrigatória dos avisos MIT é distinta do pedido opcional de citação acadêmica do projeto. Não há condição adicional de citação científica embutida na MIT padrão.
