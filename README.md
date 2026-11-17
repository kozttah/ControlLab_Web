# ControlLab Web

**Identificação, análise, síntese e verificação de sistemas de controle no navegador, com cálculo local em Python/Pyodide e interface TypeScript.**

[![CI](https://github.com/kozttah/ControlLab_Web/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kozttah/ControlLab_Web/actions/workflows/ci.yml)
[![Especificação](https://img.shields.io/badge/Documento_Diretor-CL--DIR--001_v1.0.0-0f172a)](./ControlLab_Web_Documento_Diretor_v1.0.md)
[![Status](https://img.shields.io/badge/Produto-Beta-d97706)](./PROJECT_STATE.json)
[![Licença](https://img.shields.io/badge/Licen%C3%A7a-MIT-059669)](./LICENSE)

O ControlLab Web reúne um motor científico em `NumPy`/`SciPy`, modelos canônicos, diagnósticos numéricos e arquivos portáteis para ensino, pesquisa e engenharia de controle. O cálculo no navegador é executado em um Web Worker Pyodide, sem backend científico remoto obrigatório. O mesmo pacote `control_lab` pode ser utilizado em CPython local.

A especificação normativa é o [Documento Diretor CL-DIR-001](./ControlLab_Web_Documento_Diretor_v1.0.md), complementado pelas [decisões de arquitetura](./docs/architecture/). O [PROJECT_STATE.json](./PROJECT_STATE.json) registra os gates, os WorkPackages e seus escopos de aceite.

## Estado atual

**Referência em 17/11/2026:** commit [`f1528bb`](https://github.com/kozttah/ControlLab_Web/commit/f1528bb6fe89b4d1a8c1b684f6bea29008de362a), com **34 WorkPackages aceitos e 5 pendentes**. Os quatro gates da Fase 0 foram aprovados pela F9 no domínio documentado. O produto permanece **beta**; a aprovação dos gates não declara todos os recursos da especificação como uma release estável.

| Gate | Resultado | Capacidade verificada |
| --- | --- | --- |
| **G-0A** | `ACCEPTED_BY_F9` | CARE/LQR 12×3, paridade CPython/Pyodide, recuperação do Worker e controle de PyProxy. |
| **G-0B** | `ACCEPTED_BY_F9` | Solver SDP nativo no Wasm, escada A–D, auditoria primal/dual e exportadores CVXPY/YALMIP em Chromium e Firefox. |
| **G-0C** | `ACCEPTED_BY_F9` | Arraste DOM real com Fast-Preview/commit, teclado, viewport mobile, validação dimensional e curvas temporais de estados/entradas. |
| **G-0D** | `ACCEPTED_BY_F9` | Round-trip `.ctrlab`, downloads `.pvm` estáticos/dinâmicos e saturação, com abertura e comparação de trajetórias no PathView/PathSim. |

A [execução CI dessa referência](https://github.com/kozttah/ControlLab_Web/actions/runs/44078018770) concluiu os oito jobs com sucesso, incluindo os dois perfis matemáticos, Wasm, segurança, integração e artefatos. O badge acima acompanha a `main` atual; essa execução é uma evidência vinculada ao commit indicado. Os perfis matemáticos passaram com 298 testes sem SDP opcional e 147 com SDP, sem skips. As contagens se sobrepõem entre suítes e não devem ser somadas como casos distintos.

Evidências e limites estão no [relatório dos gates](./docs/audits/RELATORIO_STATUS_GATES_FASE0.md), no [fechamento CI e reconciliação](./docs/audits/CI_RECONCILIATION_2026-11-17.md) e nos [handoffs F9](./docs/audits/handoffs/). Relatórios de auditorias anteriores são preservados como histórico.

## O que já pode ser demonstrado pela interface

- **LQR:** configuração de planta e pesos, pré-visualização transitória durante o arraste do slider e confirmação pelo motor Python. O preview não é salvo como resultado científico confirmado.
- **Resultados:** ganho, polos, curvas temporais de estados `x` e entradas `u`, erros dimensionais visíveis, navegação por teclado e layout mobile nos cenários auditados.
- **Projetos `.ctrlab`:** salvar e reabrir o workspace LQR confirmado, preservando matrizes, revisões e opções de exportação, incluindo saturação e o DTO de controlador dinâmico.
- **Simulação externa `.pvm`:** exportar realimentação de estados contínua/discreta, saturação de atuador e `DynamicController`, com validação de dimensões, sinal e bem-postura. A exportação dinâmica pode ser feita sem síntese LQR prévia; o fluxo ZIP da tela ainda exige um workspace LQR confirmado.
- **Contingência SDP:** obter scripts Python/CVXPY (`.py`) ou MATLAB/YALMIP (`.m`) do problema atual, inclusive antes de confirmar uma solução.
- **Execução local/offline:** cálculo no dispositivo após distribuição e provisionamento completo dos recursos, com integridade dos assets verificada. A instalação/build inicial pode precisar de rede.

A interoperabilidade foi auditada com **PathView 0.21.0 / PathSim 0.31.0**. Eventos externos e simulação multirate estão fora do domínio homologado. A validação YALMIP foi estrutural/sintática; não houve execução MATLAB nesta auditoria. As provas de desempenho usam o hardware do container, conforme `DEC-OPEN-03`, sem homologação de notebook de referência. Acessibilidade WCAG 2.2 AA e interatividade a 60 FPS são metas da especificação; os testes de teclado/mobile e de preview não constituem certificação integral dessas metas.

## Motor científico e escopo de evolução

![Arquitetura modular](./controllab_v1_assets/arquitetura_v1.png)

O projeto organiza seis áreas de projeto e a integração com simulador externo. A tabela distingue os módulos científicos existentes dos fluxos completos de UI que ainda serão integrados e homologados. A existência de uma operação Python/RPC ou de uma card não equivale ao aceite de toda a vertical no navegador.

| Área | Núcleo científico / API | Situação da interface e próximos incrementos |
| --- | --- | --- |
| **Identificação** | ARX, OE, subespaços, pré-processamento, PE e validação/resíduos. | Seleção de dataset, treino/holdout, gráficos e reutilização em LQR/SISO estão na próxima fila. |
| **Frequência SISO** | Resposta em frequência, margens, lugar das raízes e compensadores. | Fluxo com gráficos, overlays, edição e commit ainda será completado e homologado. |
| **Espaço de estados** | PBH/posto, Lyapunov/Sylvester, CARE/DARE, LQR, observadores, Kalman/LQG e simulação LTI. | Vertical LQR auditada. A UI ampliada de observadores/LQG faz parte das etapas seguintes. |
| **Frequência MIMO** | RGA, valores singulares e funções de sensibilidade, com hipóteses e diagnósticos. | Integração visual e seleção de entradas/saídas exigem homologação própria. |
| **Fuzzy / TS / ANFIS** | Inferência, perfil FML suportado, ANFIS e modelos TS/PDC tipados. | Aceite FML mantém escopo CPython/perfil suportado. A vertical visual completa ainda será homologada. |
| **LMIs / SDP** | Modelagem canônica afim, templates de controle, solver nativo e verificador independente. | Motor Wasm e exportadores auditados; a experiência ampliada de modelagem/templates continua no roadmap. |
| **PathView / PathSim** | Adaptadores `.pvm`, controladores estáticos/dinâmicos e importação passiva. | Downloads e cenários externos descritos acima aprovados em G-0D. |

### SDP no navegador e execução offline

A [ADR-010](./docs/architecture/ADR-010-native-sdp-and-offline-exports.md) define o **solver primal-dual nativo NumPy/SciPy** como backend SDP padrão do Pyodide. Casos estruturalmente diagonais/LP usam `scipy.optimize.linprog`/HiGHS. CVXPY/Clarabel permanecem opcionais em CPython local; o bundle Wasm base não depende de empacotar seus binários C++/Rust.

Cada solução é submetida ao verificador espectral independente, preservando as cinco dimensões de status. Condicionamento inadequado, gap/certificado não validado, resultado inconclusivo ou tamanho acima do envelope recomendado geram diagnóstico e recomendação de execução offline em CVXPY ou YALMIP com solver dedicado.

O envelope denso inicial do backend nativo limita 128 variáveis, dimensão máxima de bloco 48 e 16.384 entradas cônicas. Esses são limites operacionais, sujeitos a medição. A API de produção é beta; a API didática em `control_lab/experimental/sdp_educational/` permanece experimental.

## Executar localmente

Os comandos abaixo partem da raiz do repositório e usam shell POSIX. O CI de referência utiliza **Python 3.12.14** e **Node.js 24.22.1**; `web/package.json` admite Node 24.x. Use um ambiente Python virtual dedicado.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r scripts/requirements-ci.lock
npm --prefix web ci
npm --prefix web run build
python -m http.server 8000 --directory web/dist
```

Abra **http://localhost:8000**. O build gera a distribuição estática em `web/dist/`, incluindo a wheel científica, bundles, Pyodide, manifesto de integridade, SBOM e informações de dependências. O servidor HTTP só entrega arquivos; o cálculo roda no navegador. O diretório gerado pode ser servido por hospedagem estática com contexto seguro para Service Worker; `localhost` serve para desenvolvimento.

O build baixa os assets listados em [`scripts/pyodide-assets.lock.json`](./scripts/pyodide-assets.lock.json) e verifica seus hashes SHA-256. O cache padrão é `~/.cache/controllab-build`; `CONTROLLAB_ASSET_CACHE` permite selecionar outro diretório. Um cache completo evita novos downloads desses assets no build. No navegador, aguarde a inicialização do motor e o provisionamento verificado antes de depender do modo offline. A disponibilidade offline não é inferida apenas da primeira abertura da página.

## Verificação e CI

No ambiente virtual científico acima, antes de adicionar dependências browser:

```bash
python scripts/verify_fixtures.py
python scripts/project_governance.py
python scripts/ci_math.py sdp_available
npm --prefix web run typecheck
npm --prefix web test
python scripts/build_release.py --verify
python scripts/check_reproducible.py
```

O perfil `sdp_available` exige correspondência exata com `scripts/requirements-ci.lock`. Para `core_no_sdp`, crie outro ambiente virtual e instale exclusivamente `scripts/requirements-core.lock` antes de executar `python scripts/ci_math.py core_no_sdp`. Não misture dependências opcionais/browser nesses ambientes: o verificador deve rejeitar pacotes adicionais.

Para testes reais de navegador/interoperabilidade, use **outro ambiente**, mantendo o ambiente matemático isolado:

```bash
python3.12 -m venv .venv-browser
. .venv-browser/bin/activate
python -m pip install -r scripts/requirements-ci.lock
python -m pip install -r scripts/requirements-browser.lock
python -m playwright install --with-deps chromium firefox
npm --prefix web ci
npm --prefix web run build
python -m pytest tests/wasm/ tests/e2e/ tests/security/ tests/performance/ -v
CONTROLLAB_BROWSER=firefox python -m pytest tests/wasm/ tests/e2e/ -v
```

A instalação de dependências de sistema pelo Playwright pode exigir privilégios administrativos. As dependências oficiais PathView/PathSim estão incluídas no lock browser para as provas externas; elas não são distribuídas ao usuário da aplicação. O teste offline de segurança seleciona Chromium explicitamente, mesmo quando outros testes são configurados para Firefox. `CONTROLLAB_CHROMIUM` e `CONTROLLAB_FIREFOX` permitem apontar para executáveis compatíveis já provisionados.

O [workflow A–G](./.github/workflows/ci.yml) executa análise estática, dois perfis matemáticos, testes web, Wasm, integração, segurança e artefatos reproduzíveis. O manifesto de build é de integridade (`release_approved=false`); o aceite de capacidade fica nos registros externos F9. Ouro e tolerâncias científicas não devem ser alterados para fazer testes passarem.

## Próxima fila de trabalho

A fila abaixo está registrada como `PENDING` na referência de estado indicada no início. Os critérios completos, dependências e testes adicionais estão no [plano vertical](./docs/audits/NEXT_QUEUE_2026-11-17.md).

| Ordem / dependência | WorkPackage | Entrega prevista |
| --- | --- | --- |
| Próximo elegível | `WP-V1-F1-MODEL-REUSE-RPC` | Reutilização tipada de modelos identificados e conversão TF→StateSpace pelo RPC. |
| Após reutilização RPC | `WP-V1-F8-TYPED-WORKSPACE-INPUTS` | Seleção de insumos tipados e composição correta de payload por ferramenta. |
| Após entradas tipadas | `WP-V1-F8-IDENTIFICATION-VERTICAL` | Dataset, ARX/subespaços, resíduos e reutilização em LQR/SISO. |
| Após entradas tipadas | `WP-V1-F8-SISO-VERTICAL` | Gráficos, margens, compensadores e preview/commit SISO. |
| Após as duas verticais | `WP-V1-F9-ID-SISO-BROWSER-AUDIT` | Homologação independente dos fluxos em Chromium e Firefox. |

As fases seguintes do Documento Diretor incluem persistência multidomínio, UI de observadores/LQG, fuzzy/MIMO, experiência LMI ampliada e preparação da release 1.0. Os backends existentes serão reutilizados; novos aceites exigem evidência do fluxo completo e de seu domínio.

## Organização do repositório e contribuição

O [AGENTS.md](./AGENTS.md) define o papel do Maestro, e o [CODEOWNERS](./CODEOWNERS) separa as oito frentes produtoras da auditoria independente F9. As frentes F1–F9 são equipes de trabalho; as fases 1–7 são etapas do produto.

| Frente | Responsabilidade | Diretórios principais |
| --- | --- | --- |
| **F1** | Core, diagnósticos e I/O | `control_lab/core/`, `control_lab/diagnostics/`, `control_lab/io/` |
| **F2** | Espaço de estados | `control_lab/statespace/` |
| **F3** | Frequência SISO/MIMO | `control_lab/frequency/` |
| **F4** | Identificação | `control_lab/identification/` |
| **F5** | Fuzzy/TS/ANFIS | `control_lab/fuzzy/` |
| **F6** | Otimização, LMIs/SDP e experimental | `control_lab/optimization/`, `control_lab/experimental/sdp_educational/` |
| **F7** | Worker, RPC e armazenamento | `web/bridge/`, `web/worker/`, `web/storage/` |
| **F8** | UI e gráficos | `web/app/`, `web/features/`, `web/charts/` |
| **F9** | Contratos finais, oráculos, CI e auditoria | `contracts/`, `scripts/`, `tests/oracles/`, `tests/wasm/`, `tests/e2e/`, `docs/audits/` |

Os testes estão em `tests/`; decisões arquiteturais em `docs/architecture/`; evidências e handoffs em `docs/audits/`. O pacote e sua configuração estão em [`pyproject.toml`](./pyproject.toml), e o frontend em [`web/package.json`](./web/package.json).

A [ADR-009](./docs/architecture/ADR-009-personal-repository-governance.md) aceita a restrição externa da conta pessoal do GitHub. A qualidade e o bloqueio de release são verificados em arquivos/CI por `project_governance.py`, `ci_gate.py` e pareceres F9, sem pressupor proteção de branch disponível no servidor.

Contribuições devem respeitar ownership, tipos e revisões canônicas, convenção de sinal e hipóteses numéricas explícitas. Resultados confirmados vêm do motor Python e passam por verificação independente. Cada entrega recebe testes aplicáveis e handoff com os dez itens do Apêndice E, preservando fixtures ouro e tolerâncias. Consulte também as [informações de dependências](./docs/legal/DEPENDENCIES.md).

## Licença e autoria

O código e a documentação originais do ControlLab Web são disponibilizados sob a [licença MIT](./LICENSE), com copyright de Víctor Campos e dos contribuidores do projeto. Ela permite uso, modificação, redistribuição e uso comercial, exigindo a preservação dos avisos de copyright e de permissão nas cópias ou porções substanciais do software.

O software é fornecido **no estado em que se encontra, sem garantia**, inclusive de funcionamento, adequação a uma finalidade ou suporte, nos termos da licença e da legislação aplicável. A maturidade beta e as limitações científicas documentadas continuam válidas.

Se utilizar o projeto em ensino ou pesquisa, agradecemos a citação indicada em [CITATION.cff](./CITATION.cff). Esse é um pedido voluntário, não uma condição adicional da MIT. Bibliotecas e recursos de terceiros mantêm suas [próprias licenças e avisos](./docs/legal/THIRD_PARTY_LICENSES.md); a licença MIT do projeto não os relicencia. A decisão e o escopo estão registrados na [ADR-011](./docs/architecture/ADR-011-mit-license-and-third-party-notices.md).
