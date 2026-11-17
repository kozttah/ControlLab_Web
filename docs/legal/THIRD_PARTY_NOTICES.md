# Avisos de terceiros e acesso ao código-fonte

O arquivo `LICENSE` do repositório rege somente o código e a documentação originais do ControlLab Web. Componentes de terceiros mantêm seus avisos e licenças, mesmo quando distribuídos junto à aplicação. Preserve este diretório e os avisos extraídos em qualquer redistribuição do build.

## Runtime distribuído e fontes correspondentes

| Componente | Versão distribuída / fonte | Avisos preservados |
| --- | --- | --- |
| Pyodide | [0.27.5](https://github.com/pyodide/pyodide/tree/0.27.5), com [receitas e patches do build](https://github.com/pyodide/pyodide/tree/0.27.5/packages) | [Mozilla Public License 2.0](licenses/Pyodide-MPL-2.0.txt). Os fontes da versão indicada são disponibilizados sob MPL-2.0 para os arquivos cobertos. |
| CPython | [v3.12.7](https://github.com/python/cpython/tree/v3.12.7), com patches/receitas do Pyodide acima | [LICENSE upstream](licenses/CPython-3.12.7.txt), incluindo histórico PSF/BeOpen/CNRI/CWI. |
| OpenBLAS | [v0.3.26](https://github.com/OpenMathLib/OpenBLAS/tree/v0.3.26), com receita Pyodide | [BSD de três cláusulas](licenses/OpenBLAS-0.3.26.txt) e [LAPACK incorporado](licenses/OpenBLAS-LAPACK.txt). O ZIP distribuído não contém uma cópia própria desse arquivo. |
| Emscripten | [3.1.58](https://github.com/emscripten-core/emscripten/tree/3.1.58), usado no runtime Pyodide | [Avisos upstream MIT/UIUC-NCSA e componentes](licenses/Emscripten-3.1.58.txt), [COPYRIGHT musl dessa árvore](licenses/musl.txt). |
| libffi | [Commit f08493d249d2067c8b3207ba46693dd858f95db3](https://github.com/libffi/libffi/tree/f08493d249d2067c8b3207ba46693dd858f95db3), fixado no [build CPython do Pyodide 0.27.5](https://github.com/pyodide/pyodide/blob/0.27.5/cpython/Makefile) | [Licença MIT upstream](licenses/libffi.txt). |
| NumPy | [v2.0.2](https://github.com/numpy/numpy/tree/v2.0.2) com receita Pyodide | LICENSE e avisos incorporados extraídos do wheel, preservados em `legal/third-party/numpy-2.0.2-*/`. |
| SciPy | [v1.14.1](https://github.com/scipy/scipy/tree/v1.14.1) com receita Pyodide | LICENSE/COPYING e avisos incorporados extraídos do wheel, preservados em `legal/third-party/scipy-1.14.1-*/`. |
| micropip | [0.8.0](https://github.com/pyodide/micropip/tree/v0.8.0) | MPL-2.0, texto LICENSE extraído do wheel. Os fontes da versão indicada são disponibilizados sob MPL-2.0 para os arquivos cobertos. |
| packaging | [24.2](https://github.com/pypa/packaging/tree/24.2) | Textos Apache-2.0/BSD extraídos do wheel e preservados em `legal/third-party/packaging-24.2-*/`. |

As versões, URLs de distribuição e hashes exatos dos artefatos usados pelo build estão em `scripts/pyodide-assets.lock.json` e no `release-manifest.json` gerado. Os fontes upstream, as receitas e os patches Pyodide acima permitem identificar o código correspondente aos artefatos cobertos. O projeto não modificou os assets fixados; se uma redistribuição futura alterar arquivos cobertos pela MPL, essas alterações e as obrigações de fornecimento de fontes também precisam ser tratadas sob MPL-2.0.

O build copia integralmente os avisos encontrados nos archives. NumPy/SciPy e a distribuição Python podem incorporar outros componentes com termos próprios; os textos extraídos e os avisos upstream prevalecem sobre rótulos resumidos do inventário. O agrupamento acima não concede uma nova licença sobre o runtime inteiro, nem declara revisão jurídica exaustiva de todas as compilações possíveis.

## Ferramentas e componentes externos

Os pacotes opcionais CPython, ferramentas de CI/build e PathView/PathSim são distinguidos do runtime Web no [inventário](THIRD_PARTY_LICENSES.md). Seus instaladores preservam seus avisos próprios. Se forem redistribuídos junto ao produto no futuro, o distribuidor deverá levar esses avisos e obrigações para a nova distribuição. Gerar um arquivo `.pvm` interoperável ou exportar um script que importa CVXPY/YALMIP não relicencia esses programas nem concede direitos sobre solvers proprietários.

Textos adicionais foram obtidos dos arquivos LICENSE/COPYRIGHT das versões upstream indicadas, sem retirar os avisos de autoria e sem adaptar suas condições para MIT. A ausência de garantia no código próprio também não substitui os disclaimers dos terceiros.
