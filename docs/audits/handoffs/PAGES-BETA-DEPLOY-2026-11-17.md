# PAGES-BETA-DEPLOY-2026-11-17 — publicação beta no GitHub Pages

Base: `82d91e6ee25f30726ce0b5dec4a44902f970bd56` mais o incremento desta entrega. Data UTC: 2026-11-17. CL-DIR-001, §§14–15 e Apêndice E. Produtor: `/root/f9_pages_deploy`.

## Entrega

- Job H em `.github/workflows/ci.yml`, dependente de A–G do mesmo workflow/SHA. Somente a `main` do repositório original, em push ou dispatch, pode publicar. PRs, forks e dispatches de outras refs não recebem job de deploy.
- O job baixa o artefato `G-unapproved-static-artifacts` do próprio run, verifica inventário e hashes do runtime e envia somente `web/dist/`. Não há rebuild, checkout de outro SHA ou publicação de arquivos do repositório fora da distribuição.
- Publicação serializada em `github-pages`, com environment e URL de deployment. Um commit já superado pela `main` é ignorado antes de preparar o upload. Os privilégios Pages/OIDC ficam restritos ao job H; checkout sem persistência de credenciais.
- Ações oficiais Pages e download-artifact fixadas por commit, a partir das refs oficiais consultadas em 17/11/2026. `configure-pages` usa `enablement: false`: habilitar o site pela primeira vez exige Settings → Pages → Source: GitHub Actions. Não há PAT novo nem tentativa de usar GITHUB_TOKEN como administração do repositório.
- README com link `https://kozttah.github.io/ControlLab_Web/`, aviso beta, carregamento inicial Pyodide, persistência local e exportação `.ctrlab`.
- E2E real `tests/e2e/test_pages_prefix.py`: entrada HTML, CSS, Worker/Pyodide, LQR, Service Worker e recarga/cálculo offline sob o prefixo exato `/ControlLab_Web/`. Não existe fallback de assets na raiz do servidor de teste.

## Validação executada

1. `npm --prefix web run build`, com Python do ambiente isolado e cache de assets fixados: aprovado; 42 assets íntegros.
2. `python scripts/build_release.py --verify`: aprovado, mesmos 42 assets.
3. Teste E2E prefixado em Firefox 153: **1 passed em 30.88 s**, sem skip. O ganho mostrado para o integrador duplo com Q=I/R=1 é `[1.0000, 1.7321]`, antes e depois da recarga offline. Registro/scope SW e todos os requests de aplicação permaneceram no prefixo, sem HTTP >=400 de assets.
4. YAML carregado e dependências A–G, permissões e upload restrito conferidos. `git diff --check` aprovado.
5. Sem alteração de código científico, fixtures ouro, tolerâncias, contrato ou status de gate.

Comandos locais usaram `CONTROLLAB_BROWSER=firefox`, `CONTROLLAB_FIREFOX` para o executável provisionado, PYTHONPATH para dependências de teste já instaladas e Python do projeto. O build usa Node 24.22.1/Python 3.12.14. O ensaio local é em origem localhost segura para Service Worker; a publicação HTTPS real e sua URL precisam ser confirmadas após habilitação e execução do job H.

## Configuração administrativa informada pelo Maestro

O Maestro confirmou a habilitação na interface autenticada do GitHub em 17/11/2026: Settings → Pages exibiu o aviso `GitHub Pages source saved`, com Source **GitHub Actions** e HTTPS obrigatório ativo. Essa evidência resolve a configuração inicial externa ao workflow. Não é evidência de deploy concluído; o job H e a URL pública ainda precisam ser confirmados após a publicação do commit.

## Checklist de Handoff — Apêndice E

| Item | Questão | Resposta | Evidência | Auditoria |
| --- | --- | --- | --- | --- |
| 1 | Contratos e consumidores | SIM | APIs intactas; distribuição estática consumida pela entrada real e pelo Worker. | CONFORME |
| 2 | Status e proveniência | SIM | Deploy limitado ao SHA testado, artefato do próprio run e manifesto verificado; beta preservada. | CONFORME |
| 3 | Referência antes da entrega | SIM | LQR analítico integrador duplo e paths explícitos do project site. | CONFORME |
| 4 | Independência | SIM | Revisor independente repetiu E2E Firefox real:1 passed em31.68s,22 requests sob prefixo, LQR analítico e recarga offline aprovados. Pins oficiais e workflow confrontados separadamente por API/leitura. | CONFORME |
| 5 | Ownership e ouro | SIM | Workflow, E2E, README e handoff F9; ouro/tolerâncias intactos. | CONFORME |
| 6 | CPython/Pyodide | ESCOPO | Empacotamento verificado; navegador executa Pyodide real no prefixo online e offline. | CONFORME |
| 7 | Schema e migração | N/A | Nenhuma alteração de schema/API. | N/A |
| 8 | Artefatos e logs | SIM | Mesma distribuição testada em G é publicada; build 42 assets e E2E 1/1 registrados acima. | CONFORME |
| 9 | Experimental/beta | SIM | README conserva beta; release_approved=false não é promovido pelo workflow de Pages. | CONFORME |
| 10 | Limites e acompanhamento | SIM | Habilitação administrativa confirmada pelo Maestro; URL real só pode ser atestada após deploy bem sucedido. | CONFORME |

## Relato do produtor

Pronto para revisão independente F9 do workflow e da evidência local. A habilitação administrativa foi confirmada pelo Maestro, conforme a seção acima. Este handoff não declara o site publicado; a confirmação da URL após execução do job H fica a cargo do Maestro/coordenador. Nenhuma promoção de gate ou release estável é emitida por esta entrega.


## 5. Parecer F9

- Revisor independente: `/root/f9_independent_review`, sem autoria do workflow ou do teste.
- Commit SHA auditado: `82d91e6ee25f30726ce0b5dec4a44902f970bd56` mais o diff desta entrega, identificado abaixo.
- Data (UTC): 2026-11-17.
- Veredito F9: accepted
- Escopo: configuração de publicação beta restrita ao artefato aprovado pelo CI e teste local real do prefixo Pages; não constitui atestado de deploy remoto nem de disponibilidade atual da URL.

O revisor leu as regras AGENTS/F9/CODEOWNERS, a diferença do workflow, o teste e o README. Confirmou em chamadas independentes às refs oficiais GitHub que download-artifact v4, configure-pages v5, upload-pages-artifact v3 e deploy-pages v4 correspondem exatamente aos SHAs fixados. O job H usa checkout do próprio github.sha, depende de todos os jobs A–G do mesmo workflow e baixa o artefato por nome do próprio run. As permissões globais continuam contents:read; Pages/OIDC ficam somente em H. PR/fork/ref diferente não pode disparar o job. O teste de head e a serialização impedem substituir o site atual por execução antiga já superada. Nenhum PAT, código externo de PR ou segredo adicional é introduzido.

Verificações novas do revisor:

- YAML interpretado e asserts de dependências, permissões, serialização e caminhos de artefato aprovados.
- `python scripts/build_release.py --verify`:42 assets íntegros. Somente web/dist será publicado, incluindo avisos/licenças preservados. Ouro e lock de assets não têm diff.
- `CONTROLLAB_BROWSER=firefox CONTROLLAB_FIREFOX=<executável provisionado> python -m pytest tests/e2e/test_pages_prefix.py -v -s`: **1 passed em31.68s**, Firefox153.0, sem skip.22 requests de aplicação permaneceram sob `/ControlLab_Web/`; SW scope/script corretos, ganho mostrado `[1.0000,1.7321]` e recarga offline controlada pelo SW confirmados.
- `git diff --check`: aprovado. README distingue uso beta, inicialização/provisionamento e armazenamento local. Nenhum gate ou maturidade estável é promovido pelo deploy.

O Maestro informou ter observado a configuração Settings→Pages com Source:GitHubActions e HTTPS ativo; essa ação administrativa não foi repetida pelo revisor. O aceite acima cobre a configuração de workflow e a evidência local. Depois da publicação da alteração, o Maestro deverá confirmar todos os jobs, o deploy H e a aplicação no endereço HTTPS real. Falha de implantação ou de acesso remoto não poderá ser convertida em aprovação do site somente pelo teste localhost.

### Identidade dos arquivos revisados

- `.github/workflows/ci.yml` — SHA256 `459c522b2bb5e021448ed18527f027ae01ffa703ca8499eff4db8a503bb5bfb5`.
- `tests/e2e/test_pages_prefix.py` — SHA256 `ea4b1a0b956f1ae2858472d583a2ce48a28513aa8fa4cf2fc3ec9b848aaf9606`.
- `README.md` — SHA256 `63a4f30675eb603ae2ffe841b14ce9ef41dc284a8e3c0440886868270ae0ea14`.
