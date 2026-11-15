# Reauditoria Externa Independente - ControlLab Web

**Relatório:** AUD-EXT-CL-DIR-001-2026-11-15, revisão 2.  
**Data:** 15/11/2026 (America/Sao_Paulo).  
**Fonte normativa única:** `ControlLab_Web_Documento_Diretor_v1.0.md`, CL-DIR-001 v1.0.0, raiz do repositório.  
**Repositório:** https://github.com/kozttah/ControlLab_Web  
**Branch/commit auditado:** `main` / `60d5c5c8cd49d7a91b4d7d77b94582182565df59`.  
**Comparação anterior:** `e4b166af612e7abb55f98dcb38fbfc295fbd32b1` (ZIP auditado em 14/11/2026).  
**SHA-256 da norma:** `f7f10b1a19eb6a145959693937e1c67c97717e6a93e2a690f0045c2f96768102`; conteúdo idêntico ao da primeira auditoria.  
**Operação:** somente leitura do GitHub; nenhuma alteração, issue, comentário, PR, commit, push, permissão ou configuração realizada.

## 1. Sumário Executivo e Veredito Global por Gate e por Frente

**Houve melhora substancial: 11 dos 15 achados anteriores foram corrigidos no seu escopo e quatro foram parcialmente resolvidos. A liberação estável do produto web ainda não deve ser aprovada.** A razão principal deixou de ser uma solução LQR inventada: esse caminho foi removido e há execução científica real no navegador. O bloqueio mais grave agora é a exportação que o usuário recebe: a UI continua gerando seu próprio `.pvm` incompatível, embora o exportador Python corrigido passe nos ensaios oficiais.

Esta rodada detalha **seis achados ativos: um CRÍTICO, três ALTOS e dois MÉDIOS** (AUD-016 a AUD-021). Quatro são novos pontos localizados e dois aprofundam/confirmam pendências anteriores: AUD-018 continua AUD-012 e AUD-020 localiza a persistência de AUD-011 na UI. A contagem não soma esses mesmos problemas duas vezes. Não se recomenda reabrir as correções matemáticas de F1/F5/F6 que passaram; deve-se corrigir seus consumidores e as lacunas restantes.

### 1.1. Aquisição, método e limites

O acesso autenticado ao GitHub funcionou. A árvore do commit contém 499 entradas, sendo 433 blobs. Foram materializados e conferidos por Git blob SHA-1 **432 blobs**, incluindo todas as fontes, testes, contratos, fixtures, logs e evidências textuais. Foi dispensada apenas a cópia binária do PDF da auditoria antiga, cujo conteúdo já está representado pelo Markdown e pelos artefatos anteriores. Os arquivos que não mudaram desde o ZIP anterior foram reutilizados somente após igualdade do SHA de blob com a árvore atual. Essa verificação evita confundir a cópia antiga com o estado remoto.

Os testes/build e novos probes foram executados em materializações locais fora de qualquer checkout Git do projeto. A suíte principal usa uma cópia de execução separada; verificações adicionais também leram os arquivos materializados. Nenhum blob versionado foi alterado e nenhum comando de mutação remota foi chamado. O inventário e hashes foram reconferidos no final. A auditoria cobre os 22 WPs atuais, os 32 testes do catálogo, os seis eixos originais e os caminhos implementados, com maior profundidade nos defeitos anteriores, nas correções e na integração web/I/O nova.

Foram lidos código, schemas, PROJECT_STATE, handoffs, oráculos/geradores, scripts de build/CI, evidências de browser e PathView, além dos logs do workflow do próprio SHA auditado. Declarações em comentários ou handoffs não foram aceitas isoladamente como prova: foram confrontadas com código, logs e probes. A revisão de autoria humana/agentica é limitada ao histórico e às evidências disponíveis; um nome de agente num dossiê não constitui identidade GitHub ou assinatura criptográfica de independência.

**Limite importante de execução:** Chromium local falhou antes de iniciar por restrição do ambiente a socket local (`process_singleton_posix`, Operation not permitted). A tentativa alternativa de obter o headless shell não concluiu com arquivo íntegro. Portanto os testes browser desta rodada foram **verificados pelos logs reais da CI no mesmo SHA e pelo código do harness**, não declarados como nova execução local bem-sucedida. A tentativa local resultou em 14 erros de setup e uma falha de setup offline; não são contados como defeitos do produto, passes, skips ou prova contra os resultados de CI. Conversão/simulação oficial PathView/PathSim em CPython foi reexecutada localmente.

### 1.2. Resultados executados e CI observada

| Verificação | Resultado | Interpretação |
|:--|:--|:--|
| Build estático local | PASS; 32 assets locais verificados | Wheel, JS, Pyodide, manifesto e componentes provisionados com hashes. |
| Typecheck + unitários web locais | 50 passed; 0 skipped; TS 5.8.3 | O estágio TypeScript foi realmente executado; AUD-014/015 corrigidos. |
| Suíte nativa ampla local (295 casos) | 292 passed; 3 failed | Uma falha real de governança (AUD-016); uma suposição de dependência opcional (AUD-017); uma ausência de índice Git na materialização, não defeito do código. |
| Regressões FML/SDP independentes + F6 | 35 passed | Correções de imutabilidade, LP estrutural, norma 2 e parser estrito confirmadas. |
| Probes adversariais antigos | PASS nas correções exercidas | Mesma revisão rejeitada; mutação isolada; off-diagonal recusado; resíduo 1/101; FML inválido e PBH não estabilizável rejeitados. |
| PathView/PathSim oficial, discreto | 39/39 passed; max erro 1,2765899448652362e-12 | 13 modelos × três configurações, contra recorrência independente; limite 1e-10. |
| PathView/PathSim oficial, regressão | 9/9 passed; max erro 3,753094279801417e-9 | Oito contínuos e um discreto; limite 2e-6; código F1, não download da UI. |
| Download de projeto da UI, probe | JSON rejeitado pelo load_ctrlab | Não é o ZIP nativo; AUD-019. |
| Download PVM da UI, conversor oficial | 5 conexões viram 3; ganho omitido | MatrixGain ausente do registro; realimentação perdida; AUD-020. |
| ID com LF, inspeção do exportado | AST ganhou instrução Python extra | Texto preservado como instrução pelo conversor; não foi executado; AUD-021. |

As três falhas da execução nativa ampla foram mantidas no registro, sem mudar teste/estado para fazê-las passar. O teste de ownership exige `git ls-files`; como a aquisição se deu por blobs autenticados e não por clone, essa chamada não tem índice local. Repetimos a verificação de ownership sobre a lista oficial de 433 paths da API e obtivemos zero divergências. A falha de ausência de Git não deve ser confundida com AUD-016 nem usada para alegar CI limpa. Já a asserção de solver ausente falha quando se junta F1 e os extras SDP: a CI separa esses perfis, e essa distinção está explicitada em AUD-017.

Ambiente local de referência: Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0, pytest 9.2.0, Clarabel 0.11.1, CVXPY 1.9.3, PathView 0.21.0, PathSim 0.31.0, Playwright 1.58.0, Node 24.22.1 e TypeScript 5.8.3. Os locks do projeto foram utilizados para montar o ambiente de teste. A execução local ampla recebeu um aviso de depreciação anyio/pytest; não é falha científica.

**Workflow remoto examinado:** [CL-DIR-001 A-G / run 43711325008](https://github.com/kozttah/ControlLab_Web/actions/runs/43711325008), vinculado ao SHA auditado. Conclusão global: failure. As contagens abaixo têm sobreposição de casos entre jobs; não devem ser somadas como testes únicos.

| Job | Conclusão | Evidência relevante |
|:--|:--|:--|
| A — Python estático | success | Importabilidade/checagens estáticas do pipeline. |
| B — core_no_sdp | failure | 250 passed, 1 failed: governança exige veredito antigo de G-0B. |
| B — sdp_available | success | 113 passed; backends reais disponíveis. |
| C — Web | success | Typecheck, 50 unitários web e 21 testes adicionais de integração/oráculos Node. |
| D — Wasm | success | 8 testes reais browser/Wasm/performance. |
| E — Integração | failure intencional de gate | 3 testes browser passaram; wrapper retorna exit 2 porque G-0D não tem aceite. |
| F — Segurança | success | 3 testes browser incluindo offline/CSP/importação passiva. |
| G — Release | failure intencional de gate | 15 testes passaram; wrapper retorna exit 2 por G-0A/B/C/D pendentes. |

A falha B é regressão de teste a corrigir. Os bloqueios E/G são controles que estão funcionando e não devem ser removidos para obter um workflow verde artificial. O estado global deve continuar bloqueado enquanto as evidências de produto e o parecer formal não atenderem aos critérios.

### 1.3. Veredito por gate

| Gate | Declarado atualmente | Veredito desta auditoria | Pendência para encerramento |
|:--|:--|:--|:--|
| G-0A | PENDING / BLOCKED | Evidência essencial muito ampliada; sem aceite global | CARE 12x3/PBH/RPC reais demonstrados em CI; completar dossiê formal de domínio suportado, proxies/memória/reinício e matriz de execução. |
| G-0B | PENDING / UNAVAILABLE_IN_PROVISIONED_WASM | Fallback honesto; SDP de produção Wasm não aprovado | CVXPY/Clarabel não provisionados. Não há resolução PSD/BRL auditada em dois navegadores; não promover solver didático. |
| G-0C | PENDING / BLOCKED | PARCIAL; produto ainda não integrado integralmente | Typecheck/engine/preview reais existem. Completar gesto DOM/mobile/teclado e fluxos de arquivos reais. |
| G-0D | PENDING / interop contínua e discreta verificada, gate pendente | BLOQUEADO pelo caminho entregue pela UI | F1 interopera nos casos testados; downloads F8 ainda são PVM legado e JSON de layout, não a exportação/ciclo nativo exigidos. |

G-0B não deve bloquear o desenvolvimento de DSL, verificador ou LQR por si só (Seção 13.8). O backend permanece indisponível com razão transparente. A governança de uma eventual release de escopo reduzido precisa declarar a funcionalidade excluída e a decisão F9; não consiste em marcar o teste de indisponibilidade como aprovação do backend.

### 1.4. Veredito por frente e maturidade declarada

PROJECT_STATE contém 22 WPs: 13 ACCEPTED_BY_F9, sete CHANGES_REQUESTED e dois BLOCKED_BY_GATE. Dez corretivos foram aceitos; o pacote corretivo global Wasm/gates permanece bloqueado. Os WPs históricos reabertos preservam sua decisão anterior, o que é adequado para rastreabilidade; aceite corretivo não deve apagar esse histórico nem promover automaticamente o produto.

| Frente | Evidência atual | Estado real desta rodada |
|:--|:--|:--|
| F1 | Tipos/RPC/immutabilidade e dois adaptadores PVM corretivos aceitos | Correções técnicas sustentadas. Core/ctrlab/PVM funcionam nas baterias; teste multidomínio assume ausência de SDP (AUD-017). |
| F2 | WP-02 aceito local; CARE real também em CI Wasm | Cálculo científico sustentado nos domínios exercidos; gate global não substituído por um caso. |
| F3 | WP-07 aceito local; novas fixtures completas | RGA/sensibilidade e cruzamentos com oráculos; sem nova violação concreta nas rotinas examinadas. |
| F4 | WP-08 aceito local; PRBS/holdout congelados | PE/posto e métricas separadas sustentados; integração completa das ferramentas browser não é inferida. |
| F5 | Correção FML aceita; oráculo F9 independente | Parser estrito e round-trip corrigidos; ANFIS/TS permanecem com domínios explícitos. |
| F6 | Correção SDP aceita; solver didático experimental | Imutabilidade, redução LP e norma 2 corretas; dual/Farkas independentes preservados; SDP Wasm indisponível. |
| F7 | Worker/RPC/offline corretivos aceitos | Sem falso fallback, capacidades observadas, beta e SW com integridade. Evidência browser real existe. |
| F8 | Correção TypeScript aceita; histórico WP-06 reaberto | Compila e interage com engine; exportações nativas continuam desconectadas e há injeção via metadado. |
| F9 | Handoffs, oráculos/fixtures/locks/CI reais | Grande avanço; falta proteção efetiva e testes de governança atualizados, além de testar o arquivo efetivo baixado da UI. |

### 1.5. Comparação explícita dos 15 achados anteriores

| Achado anterior | Situação | Fundamentação |
|:--|:--|:--|
| AUD-001 | CORRIGIDO | Fallback removido; cliente sem Worker/runtime falha sem resultado e sem commit. Testes F7 e PBH via dispatcher real passaram. |
| AUD-002 | CORRIGIDO | Worker default configurado na app, bootstrap local e core.rpc.dispatch efetivos. CI D/G exercita o produto no Pyodide real. |
| AUD-003 | PARCIAL | Build reproduzível/locks/manifesto/SBOM/workflows existem e build local concluiu. CI atual tem falha B e bloqueios E/G; ver AUD-016/017. |
| AUD-004 | CORRIGIDO | SW registrado, manifesto/hash/fechamento transitivo e readiness reais; CI F passa offline após reload, fonte do teste examinada. |
| AUD-005 | CORRIGIDO | Getters com cópia defensiva e revisão monotônica. Repetição dos probes: objeto intacto e edição na mesma revisão rejeitada. |
| AUD-006 | CORRIGIDO | SDP em bytes/shape imutáveis; mutação de getter não muda o problema; regressões independentes presentes. |
| AUD-007 | CORRIGIDO | Diagonalidade estrutural exige off-diagonal exatamente zero; bloco 1e-15 é recusado como unsupported_psd. |
| AUD-008 | CORRIGIDO | Escala PSD usa norma 2; probe diag(100,100,-1) devolve exatamente 1/101. |
| AUD-009 | CORRIGIDO | FML estrito recusa operador/sigma inválidos; testes F5/F9 preservam round-trip e perfil suportado. |
| AUD-010 | CORRIGIDO NO ESCOPO ORIGINAL | Doubles locais foram identificados; há CI com Worker/Pyodide, IDB e offline reais. Restam lacunas específicas de gesto DOM/exports, explicitadas nesta auditoria. |
| AUD-011 | PARCIAL | Produtor Python e testes PathView externos corrigidos; rota de download F8 ainda emite representação incompatível (AUD-020). |
| AUD-012 | PARCIAL | Cobertura textual de ownership corrigida; branch main continua desprotegida (AUD-018). |
| AUD-013 | PARCIAL | Handoffs, hashes, logs, revisão independente e limites agora existem. Falta fechar gates e a integração real de arquivos da UI; testes de governança não acompanham os novos dossiês. |
| AUD-014 | CORRIGIDO | TypeScript 5.8.3 compila; 50 testes Node locais passaram; C remoto confirma. |
| AUD-015 | CORRIGIDO | Runner falha fechado sem tsc/suíte; testes específicos de controle e CI passam, sem omissão silenciosa do typecheck. |

### 1.6. Conferência dos seis eixos técnicos e matemáticos

**Governança/anti-circularidade:** CODEOWNERS agora cobre todas as frentes e os 433 paths, com override exclusivo de fixtures/exemplos para F9. Os três JSON ouro antigos são idênticos byte a byte à primeira auditoria. As novas fixtures B-DARE-12x3, B-ARX-PRBS, B-MIMO-2x2 e B-PVM-LQR têm dados completos, hashes e confrontos independentes em `tests/oracles/test_release_independent_math.py`. O gerador não importa control_lab. CARE/DARE utilizam SciPy também na implementação; essa igualdade de biblioteca não basta sozinha como segundo algoritmo. Resíduos, estabilidade, PBH, recorrências, integrações e soluções fechadas fornecem verificações matemáticas adicionais. Nos novos ensaios PathView, o esperado é calculado por recorrência/eliminação algébrica e ODE independente, não pelo simulador PVM sob teste. Não se encontrou indício de alteração de ouro/tolerâncias para acomodar falha produtora. O ajuste histórico de asserções estruturais de portas e o classificador de tempo discreto estão documentados, preservam logs anteriores e não relaxam os limites de estado/saída.

**Modelos canônicos/interconexões:** os getters retornam cópias defensivas e a evolução científica rejeita mesma revisão ou revisão regressiva. Probes anteriores não alteraram estado interno. Construção mantém dimensão/dt/finitude/unidades; Result continua defensivo. get_closed_loop_matrix recusa controladores dinâmicos/PDC; interconnect resolve o loop I-s Dc Dp com fatoração e rejeita singularidade. TS medido/incerto/parcialmente observado continuam distintos e PDC sem premissas é bloqueado. A validação geral preserva termos duplos h_i h_j. Não se certifica qualquer observador de premissas simplesmente por receber uma referência a ele.

**Motor científico:** a varredura AST de todos os módulos Python de produção não encontrou chamadas inv/pinv/eval/exec. Inv em oráculos é distinguido de inv em síntese. CARE/Lyapunov continuam usando as fórmulas normalizadas exatas da Seção 10.2; PBH precede o ganho e o teste de similaridade transforma x0=T x0 em CPython e no teste Wasm. RGA continua restrita a quadrada/não singular, com undefined diagnosticado. F4 mantém FIT de previsão de um passo separado de simulação livre, holdout e diagnóstico de PE/posto. Nenhuma nova falha matemática foi demonstrada nessas rotinas pelas baterias examinadas.

**Otimização:** CanonicalSDP/SDPBlock agora armazenam bytes e shapes imutáveis, sem permitir reativar escrita sobre bases compartilhadas. A diagonalidade é estrutural/exata e o bloco [[x,1e-15],[1e-15,0]] é recusado pelo fallback LP. O resíduo PSD usa norma 2: diag(100,100,-1) devolve 1/101. svec mantém sqrt(2) fora da diagonal, DSL rejeita bilinearidade, as cinco dimensões de status continuam separadas. A lógica Farkas verifica cones, equação adjunta e contradição estrita; flag sem certificado continua inconclusive. Aprovação CPython/Clarabel não é extrapolada para Wasm. A escada A-D não promove o solver didático a produção.

**I/O/segurança/bridge/UI:** importações ctrlab/PVM/FML permanecem passivas, com limites, traversal/ZIP bomb/XXE e guards. O Worker importa `control_lab.core.rpc`, confirma capacidades e não emite mais números inventados. Revisões obsoletas não comitam; há recuperação com IDB real nos testes browser. O SW agora possui manifesto/hash, fechamento transitivo e teste real offline na CI. As falhas atuais são de saída/integração: o shell ainda monta layouts paralelos de PVM/ctrlab e interpola texto no Python exportado. T-IO-02 de importação não prova a segurança de exportação, nem o teste unitário do exportador Python comprova o botão da UI.

**Cobertura normativa:** todos os 32 IDs estão localizados. Nesta rodada a classificação é 29 CONFORME no escopo/ambiente indicado e três PARCIAL. A remoção do antigo falso positivo offline reflete evidência real de CI; não é uma redefinição de offline. Os conformes CPython não significam que todas as funcionalidades estejam stable em cada navegador.

## 2. Tabela/Lista de Achados de Auditoria

A numeração continua a auditoria anterior para não colidir com AUD-001..015 já referenciados pelo Maestro. Achados de integração se atribuem ao dono do consumidor, preservando o ownership de F1/F8/F9. Nenhum estado foi alterado pelo auditor.

| ID | Severidade | Frente | Achado |
|:--|:--|:--|:--|
| AUD-016 | MÉDIO | F9 | Teste de governança congelou estados antigos e quebra o Job B atual |
| AUD-017 | MÉDIO | F1 | Teste F1 pressupõe ausência de solver opcional mesmo quando ele está instalado |
| AUD-018 | ALTO | F9 | main continua sem proteção de branch efetiva no GitHub |
| AUD-019 | ALTO | F8 | UI oferece layout JSON de projeto, não o contêiner .ctrlab reabrível normativo |
| AUD-020 | CRÍTICO | F8 | Botão .pvm ignora o exportador corrigido e perde a realimentação no PathView |
| AUD-021 | ALTO | F8 | Metadado project_id pode introduzir instrução Python no código exportado |

### AUD-016 - Teste de governança congelou estados antigos e quebra o Job B atual

**ID:** AUD-016  

**Severidade:** MÉDIO (Contrato/Invariante Incompleto)  

**Frente Responsável:** F9  

**Requisito / Teste Violado:** R-23, R-24; Seções 10.5, 13.11, 14.1 e 15.2/Job B; Apêndice E  

**Arquivo(s) e Linhas Afetadas:** `tests/integration/test_governance_and_ownership.py:232-261`; `tests/integration/test_governance_and_ownership.py:459-487`; `PROJECT_STATE.json:46-61`; `PROJECT_STATE.json:84-96`  

**Relação com auditoria anterior:** Novo desvio observado após a remediação; mantém AUD-003 parcialmente aberto.  

**Diagnóstico Técnico/Matemático:** O teste exige G-0B=NOT_DEMONSTRATED e G-0D=BLOCKED_EXTERNAL_ACCEPTANCE, embora o estado atual registre corretamente indisponibilidade Wasm observada e interop externa parcial verificada. A primeira asserção divergente causa falha local e no GitHub Actions: Job B/core_no_sdp, 250 passed e 1 failed, run 43711325008. A mesma função exige exatamente 9 WPs corretivos; há 11, pois dois WPs PathView foram adicionados. Depois desses pontos, o validador espera cabeçalhos numerados que os dois novos handoffs não possuem. Ambos contêm decisão accepted, escopo, evidências e os dez itens do Apêndice E: o erro é incompatibilidade do validador, não ausência desses conteúdos. Fixar apenas o primeiro literal deixa falhas latentes e mantém o risco de testar um retrato histórico em vez das invariantes.

**Ação Corretiva Recomendada:** Trocar o teste de fotografia por invariantes: referências existentes, dependências acíclicas, aceite com evidência, gates monotônicos e maturidade compatível. Versões/estados permitidos devem ser validados por semântica e schema do estado, não por uma contagem histórica fixa. Harmonizar o formato dos handoffs e seu parser sem relaxar a obrigação dos dez itens e da decisão explícita. Não alterar estados verdadeiros para satisfazer asserts antigos.

**Critério de Aceite:** Executar scripts/ci_math.py core_no_sdp no ambiente isolado e congelado: Job B deve ficar verde no mesmo estado factual. Testes negativos devem continuar rejeitando aceite sem evidência, pendências mascaradas e dependências ausentes/cíclicas. Cobrir expansão de fila e atualização legítima de veredito sem exigir que gates já estejam aprovados.

### AUD-017 - Teste F1 pressupõe ausência de solver opcional mesmo quando ele está instalado

**ID:** AUD-017  

**Severidade:** MÉDIO (Contrato/Invariante Incompleto)  

**Frente Responsável:** F1  

**Requisito / Teste Violado:** R-02, R-12, R-23; Seções 5.1, 6.2, 10.1 e 15.2  

**Arquivo(s) e Linhas Afetadas:** `tests/unit/f1/test_core_rpc_and_immutability.py:738-851`; `control_lab/core/rpc.py:1812-1831`  

**Relação com auditoria anterior:** Novo problema de portabilidade do teste; comportamento científico observado está correto.  

**Diagnóstico Técnico/Matemático:** O teste multidomínio executa optimization.solve com backend auto e exige failure/SOLVER_UNAVAILABLE para uma LMI não diagonal. Com Clarabel/CVXPY instalados, a implementação resolve corretamente e retorna success, causando falha em test_core_rpc_and_immutability.py:850. Isso foi reproduzido com os locks de CI/PathView/browser instalados. O perfil oficial core_no_sdp da CI separa ambientes e essa falha não ocorreu nele; o Job B/sdp_available também passa. Portanto não é evidência de cálculo incorreto nem falha desse job. É uma suposição ambiental não explicitada no teste que torna o comando de aceite F1/pytest geral incompatível com a instalação all/SDP.

**Ação Corretiva Recomendada:** Separar o cenário de indisponibilidade do cenário com backend presente. Usar seleção explícita de backend indisponível ou ambiente de teste declarado para a falha, e testar sucesso auditado quando a capacidade existir. Preservar o teste end-to-end do dispatcher e do verificador; não mascarar um solver real por expected values fixos.

**Critério de Aceite:** Executar o comando F1 em ambientes core_no_sdp e sdp_available: a hipótese de cada teste deve ser explícita e os dois cenários devem passar sem skip oportunista. No cenário disponível verificar primal/dual/gap; no indisponível exigir SOLVER_UNAVAILABLE, sem controlador falso.

### AUD-018 - main continua sem proteção de branch efetiva no GitHub

**ID:** AUD-018  

**Severidade:** ALTO (Violação Matemática/Segurança)  

**Frente Responsável:** F9  

**Requisito / Teste Violado:** R-23, R-24; Seções 13.2, 13.11 e 15.1; Apêndice E  

**Arquivo(s) e Linhas Afetadas:** `CODEOWNERS:11-18`; `.github/workflows/ci.yml:1-25`  

**Relação com auditoria anterior:** Continuação de AUD-012, agora confirmada por evidência autenticada de servidor.  

**Diagnóstico Técnico/Matemático:** A consulta autenticada GET /repos/kozttah/ControlLab_Web/branches/main retornou protected=false e protection.enabled=false, required_status_checks com enforcement_level=off e lista vazia. O mesmo commit ainda era HEAD ao final da aquisição. A consulta de rulesets devolveu 403 com mensagem de limitação do plano/repositório privado, portanto não foi possível inspecionar rulesets alternativos. O mapeamento textual CODEOWNERS foi corrigido e uma conferência independente contra os 433 caminhos de blobs retornou zero divergências, com ouro exclusivo da F9. Isso não configura enforcement no servidor: a CI atual falha, mas a branch não exige checks/revisão. Não se infere daí autoria indevida ou bypass já ocorrido.

**Ação Corretiva Recomendada:** Configurar proteção efetiva de main, com checks obrigatórios e revisão F9/Code Owner nas alterações normativas, usando identidades elegíveis. Resolver a indisponibilidade do recurso por decisão do responsável pelo repositório; esta auditoria não muda plano, visibilidade, permissões ou configurações. Um procedimento manual pode ser registrado como mitigação temporária, mas não deve ser apresentado como o enforcement mandatário da Seção 15.1.

**Critério de Aceite:** Apresentar leitura da API mostrando proteção aplicável e required checks/reviews; demonstrar em branch de teste que mudança de fixture sem revisão F9 e merge com check obrigatório falho são bloqueados. Não basta um teste local que analise texto de CODEOWNERS.

### AUD-019 - UI oferece layout JSON de projeto, não o contêiner .ctrlab reabrível normativo

**ID:** AUD-019  

**Severidade:** ALTO (Violação Matemática/Segurança)  

**Frente Responsável:** F8  

**Requisito / Teste Violado:** R-19; T-IO-01/round-trip integrado; Seções 9.1, 14.1/G-0D e 15.3  

**Arquivo(s) e Linhas Afetadas:** `web/app/main.ts:647-659`; `web/app/shell.ts:676-775`; `control_lab/core/rpc.py:1834-1880`  

**Relação com auditoria anterior:** Novo achado de integração; aprofunda o bloqueio G-0D e o escopo de AUD-013.  

**Diagnóstico Técnico/Matemático:** O botão Exportar .ctrlab chama shell.exportCtrlLab(), que monta um objeto com format=controllab_ctrlab_export, portable_snapshot e archive_layout. main.ts serializa esse objeto como application/json e filename *.ctrlab.json. Não há compactação ZIP nem fluxo de reabertura de arquivo correspondente na interface. O probe externo inicializou o cliente com dispatcher CPython real, confirmou LQR e capturou exatamente esse pacote. load_ctrlab(bytes_do_download_JSON) retornou failure/VALIDATION_ERROR. O título JSON/Layout é uma ressalva real e não se afirma que o arquivo seja um ZIP malformado: o problema é que o formato nativo obrigatório não está entregue no fluxo do usuário. O I/O Python .ctrlab possui testes fortes e não apresentou esse defeito; o consumidor web ainda o contorna.

**Ação Corretiva Recomendada:** F1 deve fornecer operações RPC tipadas para exportar/importar o contêiner por seus serializers/validadores existentes, com bytes transferíveis e erros honestos. F8 deve consumir essas operações e implementar salvar/reabrir o arquivo real .ctrlab. Se o JSON auxiliar for mantido, apresentá-lo como outro formato, sem contar como cumprimento do backup nativo.

**Critério de Aceite:** Teste browser deve capturar o download efetivo do botão, exigir ZIP íntegro com manifest.json/modelos/controladores/experimentos, importar pelo mesmo caminho de produto e comparar matrizes, unidades, revisões, sinais e proveniência. Python load_ctrlab deve aceitar esses mesmos bytes. Traversal, ZIP bomb e preview/pending_commit continuam bloqueados.

### AUD-020 - Botão .pvm ignora o exportador corrigido e perde a realimentação no PathView

**ID:** AUD-020  

**Severidade:** CRÍTICO (Bloqueador de Gate)  

**Frente Responsável:** F8  

**Requisito / Teste Violado:** R-02, R-04, R-20; T-PVM-01, T-PVM-02 no fluxo integrado; Seções 9.3, 14.1/G-0D; Apêndice D  

**Arquivo(s) e Linhas Afetadas:** `web/app/main.ts:629-642`; `web/app/shell.ts:780-1003`; `web/app/shell.ts:923-943`; `tests/e2e/test_revision_recovery.py:43-70`  

**Relação com auditoria anterior:** AUD-011 permanece parcialmente aberto na rota de usuário; nova causa localizada em F8.  

**Diagnóstico Técnico/Matemático:** F1 corrigiu o adaptador oficial e seus ensaios externos passam. O download real da UI, entretanto, chama o gerador paralelo ControlLabShell.exportPvm(), que continua emitindo MatrixGain e portas vetoriais abstratas. O probe chamou esse mesmo método após LQR real, sem fixture de resultado. O arquivo possui 5 nós e 5 conexões. No conversor oficial PathView 0.21.0, MatrixGain não é registrado; o Python gerado contém apenas 3 Connection(...) e nenhum K_lqr. As duas arestas do ganho desaparecem: a dinâmica executável não é a malha A-BK. Além disso, initial_state e os sinais de Adder não usam os parâmetros oficiais que F1 já traduziu; o conversor mostrado gera Adder() e StateSpace sem initial_value. A UI mantém aviso de gate pendente, o que é correto, mas o arquivo continua inadequado ao objetivo de exportação. Os novos testes de PathView avaliam make_pvm/export_pvm Python, não o arquivo entregue pelo botão. Esse desencontro explica por que 39/39 + 9/9 ensaios do produtor não encerram a integração do produto.

**Ação Corretiva Recomendada:** Remover o gerador PVM paralelo da UI e consumir o exportador F1 corrigido por uma operação RPC versionada. Até integrar e validar o download, desabilitar essa exportação de produto ou apresentá-la explicitamente como diagnóstico não executável, sem substituí-la por sucesso local de schema. F8 não deve copiar o lowering de F1 para TypeScript.

**Critério de Aceite:** Teste E2E deve baixar o arquivo real da UI para os casos C=I, C!=I, m!=p, sinal positivo/negativo e discreto suportado; o conversor oficial deve preservar todos os blocos/portas necessários e a simulação oficial deve reproduzir x/u/y e estados iniciais. Para controlador dinâmico exposto, testar também estados internos/feedthrough. O teste deve falhar com o download atual mesmo quando o exportador Python isolado passa.

### AUD-021 - Metadado project_id pode introduzir instrução Python no código exportado

**ID:** AUD-021  

**Severidade:** ALTO (Violação Matemática/Segurança)  

**Frente Responsável:** F8  

**Requisito / Teste Violado:** R-21, R-22, R-27; Seções 9.3 e 12.2; Apêndice D  

**Arquivo(s) e Linhas Afetadas:** `web/app/shell.ts:988-990`; `web/app/main.ts:629-642`  

**Relação com auditoria anterior:** Novo achado de segurança na exportação, distinto da importação passiva T-IO-02.  

**Diagnóstico Técnico/Matemático:** exportPvm interpola committed.project_id sem escape em um comentário de codeContext.code. A API aceita ID não vazio com quebra de linha. Usando project_id contendo external-audit-ui\nprint("AUDIT_METADATA_INJECTION")\n#, o artefato ganhou uma linha print executável fora do comentário. ast.parse confirmou um nó Expr adicional; o conversor oficial preserva o bloco USER-DEFINED CODE. A reprodução não executou esse Python e não utilizou payload destrutivo ou rede. A condição de exploração é um projeto/API com ID controlado por entrada não confiável; não se afirma execução automática por ControlLab ou pela simples importação passiva. O risco aparece na execução externa de um arquivo que o usuário espera conter somente código derivado de dados científicos confiáveis. O aviso genérico de não executar na importação não sanitiza o código gerado.

**Ação Corretiva Recomendada:** Concentrar exportação no gerador científico aprovado e tratar metadados como dados: serialização segura, comentários com cada linha prefixada ou rejeição tipada dos caracteres não representáveis. Nunca interpolar texto livre em posição executável. Auditar outros campos textuais e exportações de scripts; não afrouxar a importação passiva.

**Critério de Aceite:** Teste com IDs contendo CR/LF, aspas, Unicode e tokens Python deve demonstrar que o AST do arquivo só contém instruções previstas pelo gerador. O arquivo pode ser recusado com erro tipado ou preservar o texto como literal/comentário, mas não pode ganhar nova instrução. Repetir no código produzido pelo conversor oficial, sem executar conteúdo não confiável.

### 2.1. Reproduções mínimas, sem execução de conteúdo não confiável

**LQR falso e invariantes anteriores:** a planta A=diag(1,2), B=0, Q=I, R=1 agora retorna failure/HYPOTHESIS_VIOLATED via dispatcher. setflags em array obtido por getter não muda o modelo; with_revision(4,A=nova_A) de um modelo revisão 4 é rejeitado. SDPBlock não muda quando seu getter é atacado. F0=diag(100,100,-1) dá 1/101. FML com andMethod desconhecido/sigma=0 retorna failure/VALIDATION_ERROR. Esses resultados sustentam o encerramento dos achados técnicos correspondentes.

**Arquivo PVM efetivamente oferecido pela UI:** inicializar `ControlLabShell` com `PyodideEngineClient` injetado com o adaptador CPython de teste, confirmar LQR real e chamar o mesmo `shell.exportPvm()` usado em main.ts:631. O JSON contém `MatrixGain`. Passar o arquivo, sem alteração, a `pathview.converter.generate_python(..., load_registry(...))` da distribuição 0.21.0 gera três conexões, não cinco. Foi inspecionado o código convertido; a instrução do ganho está ausente. Não foi necessário executar esse artefato incorreto para demonstrar a perda da realimentação.

**Arquivo de projeto oferecido pela UI:** após o mesmo commit real, `await shell.exportCtrlLab()` produz o conteúdo de `*.ctrlab.json`. O importador `load_ctrlab` rejeita esses bytes com VALIDATION_ERROR. Um layout lógico não substitui o ZIP nativo ou o teste de reabertura da Seção 9.1.

**Metadado no código exportado:** `project_id = "external-audit-ui\nprint("AUDIT_METADATA_INJECTION")\n#"` é um ID não vazio que percorre o fluxo. O texto exportado contém a linha print fora do comentário; a AST contém Expr adicional. A conversão oficial mantém o bloco. Apenas parsing/conversão foram feitos; não se executou a instrução injetada. A correção não deve depender de o conteúdo benigno deste probe ser print.

## 3. Auditoria de Cobertura dos Testes Normativos (Apêndice C)

CONFORME significa que o caso literal foi demonstrado por assert adequado na fonte de execução indicada. PARCIAL significa que a camada local/produtora tem prova, mas falta a obrigação integrada do produto. AUSENTE significa inexistência de teste/evidência para o caso inteiro; FALSO POSITIVO é um teste verde que não demonstra o anunciado. Há subcenários ainda ausentes mesmo quando o ID tem cobertura parcial. O relatório distingue reexecução local de logs de CI e não soma ambos como repetições independentes de autoria.

**Contagem:** 29 CONFORME, 3 PARCIAL, 0 AUSENTE por ID e 0 FALSO POSITIVO por ID. T-PVM-01/02 e T-UI-01 são os parciais. Isso não aprova G-0A..D ou todos os subcenários de plataforma.

| Teste | Status | Evidência / Limitação |
|:--|:--|:--|
| T-CORE-01 | CONFORME | `tests/unit/f1/test_core_models_and_interconnect.py:293; tests/unit/f1/test_core_rpc_and_immutability.py:167`. Caso dimensional literal e invariantes ampliados de arrays/revisão corrigidos. Probes e testes de imutabilidade passaram. |
| T-CORE-02 | CONFORME | `tests/unit/f1/test_core_models_and_interconnect.py:352`. A-BK e A+BK analíticos; N não quadrado m!=p e incompatibilidades. O fallback web apontado na primeira auditoria foi removido; a revisão atual usa o dispatcher científico real. |
| T-CORE-03 | CONFORME | `tests/unit/f1/test_core_models_and_interconnect.py:429`. Estado aumentado derivado com Dp/Dc não nulos, solução de loop e rejeição de singularidade; restrição de get_closed_loop_matrix aos controladores estáticos. |
| T-TS-01 | CONFORME | `tests/unit/f1/test_core_models_and_interconnect.py:581; tests/unit/f1/test_core_models_and_interconnect.py:1038; tests/unit/f5/test_f5_fuzzy_ts.py:670`. Bloqueia PDC em polytopic_uncertain sem estimador; exige premissas para parcialmente observado. TS medido usa termos duplos. Conformidade do contrato, não certificação de qualquer observador fornecido por usuário. |
| T-CARE-01 | CONFORME | `tests/unit/f2/test_care_lqr.py:102`. B-CARE-02 analítico: P, K, polos, resíduo e sinal. Valores ouro não são saída da função sob teste. |
| T-CARE-02 | CONFORME | `tests/unit/f2/test_care_lqr.py:173; tests/wasm/test_real_runtime.py:13`. Fixture CPython e paridade Pyodide com resíduo/espectro examinados em CI D/G do SHA auditado. Não foi uma repetição local de browser. |
| T-CARE-03 | CONFORME | `tests/unit/f2/test_care_lqr.py:237; tests/wasm/test_real_runtime.py:77`. PBH Python e RPC real rejeitam hipótese violada sem ganho; fallback fixo removido. |
| T-CARE-04 | CONFORME | `tests/unit/f2/test_care_lqr.py:331; tests/metamorphic/test_wasm_similarity.py:20`. x_tilde_0=T@x0, congruência, ganho/custo/polos; CPython e evidência Wasm em G. C-07 respeitado. |
| T-FREQ-01 | CONFORME | `tests/unit/f3/test_frequency_siso_and_mimo.py:56`. G(s)=1/(s+a), Bode e degrau analíticos com a parametrizado. |
| T-FREQ-02 | CONFORME | `tests/unit/f3/test_frequency_siso_and_mimo.py:158`. Casos com 3 cruzamentos de ganho e 2 de fase; contagens e avaliação independente por polinômios. Escopo das grades testadas; não prova universal de completude para toda TF. |
| T-MIMO-01 | CONFORME | `tests/unit/f3/test_frequency_siso_and_mimo.py:308; tests/unit/f3/test_frequency_siso_and_mimo.py:421`. RGA quadrada/inversível, somas e S+T=I; invariância unitária e convenções de malha. inv em referência de teste, não no motor. |
| T-MIMO-02 | CONFORME | `tests/unit/f3/test_frequency_siso_and_mimo.py:369`. Singularidade DC e planta não quadrada produzem diagnóstico undefined/recusa; não usa pseudoinversa como RGA clássica. |
| T-ID-01 | CONFORME | `tests/unit/f4/test_identification.py:96`. ARX sem ruído contra coeficientes plantados por gerador recursivo do teste. |
| T-ID-02 | CONFORME | `tests/unit/f4/test_identification.py:138`. Entrada constante, colinear e PRBS de período insuficiente: warning de PE/posto; não forja covariância. |
| T-ID-03 | CONFORME | `tests/unit/f4/test_identification.py:193`. Holdout sintético, FIT/polos/estatística; previsão de um passo e simulação livre identificadas separadamente. |
| T-FML-01 | CONFORME | `tests/unit/f5/test_f5_fuzzy_ts.py:134`. Duas regras TS confrontadas com avaliação manual e ponderação. |
| T-FML-02 | CONFORME | `tests/unit/f5/test_f5_fuzzy_ts.py:314; tests/unit/f5/test_f5_fuzzy_ts.py:419; tests/oracles/test_fml_remediation_independent.py:70`. Round-trip no perfil suportado, rejeição estrita de inválidos e ataques XML. Novo probe inválido retorna failure/VALIDATION_ERROR. |
| T-SDP-A1 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:229; tests/unit/f6/test_educational_solver_levels_a_to_d.py:108`. x>=1/min x: fronteira, objetivo/primal/dual; também solver didático experimental. |
| T-SDP-A2 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:254; tests/unit/f6/test_sdp_modeling_and_verification.py:272; tests/unit/f6/test_sdp_modeling_and_verification.py:641`. x>=2/x<=1, Farkas auditado quando disponível; ausência/invalidade de certificado produz inconclusive. Não inferir infactibilidade de mero flag. |
| T-SDP-A3 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:285`. Direção recessiva, ponto factível e ausência de certificado; ilimitado auditado ou inconclusive. |
| T-SDP-B1 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:320`. Bloco analítico/fronteira e recusa LP; diagonalidade estrutural reforçada inclusive para off-diagonal 1e-15 e valores subnormais. |
| T-SDP-C1 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:360; tests/unit/f6/test_educational_solver_levels_a_to_d.py:271`. Slater/primal/dual/gap e casos construídos; norma 2 do resíduo corrigida. Escopo CPython; G-0B produção Wasm segue não aprovado. |
| T-SDP-D1 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:395; tests/unit/f6/test_educational_solver_levels_a_to_d.py:349`. Q SPD, recuperação por solve, espectro/alpha e solução explícita; sinais positivos/negativos. |
| T-SDP-D2 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:440; tests/unit/f6/test_sdp_modeling_and_verification.py:859; tests/unit/f6/test_educational_solver_levels_a_to_d.py:384`. BRL generalizado nos backends e comparação didático/Clarabel; gamma e ganho. Grade Hinf é rotulada não rigorosa; ótimo via dual/gap e teste de gamma abaixo do ótimo da fixture. Não confundir CVXPY/Clarabel e Clarabel direto com dois algoritmos independentes. |
| T-RPC-01 | CONFORME | `tests/e2e/test_revision_recovery.py:6`. 20 revisões em Worker/Pyodide de browser; um único commit da revisão atual. CI E/G do mesmo SHA examinada. |
| T-RPC-02 | CONFORME | `tests/e2e/test_revision_recovery.py:20`. Cancelamento/forceTerminate, reinício e snapshot IndexedDB confirmados em browser; comparação exclui apenas timestamp de exportação. |
| T-IO-01 | CONFORME | `tests/unit/f1/test_io_ctrlab_and_pvm.py:456; tests/unit/f1/test_io_ctrlab_and_pvm.py:481; tests/unit/f1/test_io_ctrlab_and_pvm.py:525; tests/unit/f1/test_io_ctrlab_and_pvm.py:584`. Traversal/ZIP bomb/limites/hash/revisão no importador nativo; também importação maliciosa Pyodide em CI F. Não valida por si o download JSON da UI. |
| T-IO-02 | CONFORME | `tests/unit/f1/test_io_ctrlab_and_pvm.py:673`. Importação PVM continua passiva em CPython/Pyodide, inclusive codeContext malicioso. Não confundir isso com a injeção no exportador UI de AUD-021. |
| T-PVM-01 | PARCIAL | `scripts/audit_pvm_official.py; scripts/audit_pvm_discrete.py; web/app/shell.ts:784`. F1 passa em conversor/PathSim oficiais, incluindo ambos sinais/C!=I/MIMO/saturação e 39 confrontos discretos. Arquivo baixado pela UI perde ganho/conexões (AUD-020). |
| T-PVM-02 | PARCIAL | `scripts/audit_pvm_official.py; scripts/audit_pvm_discrete.py; tests/wasm/test_pvm_discrete_clock.py:55`. Dinâmica, feedthrough, estado inicial e relógio conjunto aprovados no produtor e fonte Wasm. O fechamento do fluxo UI/arquivo externo ainda não é demonstrado. |
| T-UI-01 | PARCIAL | `tests/e2e/test_revision_recovery.py:43; tests/unit/f8/ui_mvp_lqr.test.ts:183`. Preview/pending_commit agora chega a engine real e novo ganho/revisão. Teste browser chama métodos pointerDown/Move/Up diretamente, não arraste DOM completo/mobile/teclado; exportações não estão integradas. |
| T-SEC-01 | CONFORME | `tests/security/offline_browser.py:49; tests/security/test_real_browser_security.py:55`. SW/readiness, servidor parado, cache HTTP limpo, recarga/recalcular CARE e corrupção, além de CSP. CI F/G passou; limitação de repetição local explicitada. |

### 3.1. Lacunas que não podem ser ocultadas pelo agregado

- O teste browser de preview chama métodos do controlador (`pointerDown`, `pointerMove`, `pointerUp`) em JavaScript. Isso exercita persistência e engine, mas não o gesto de ponteiro real no DOM, teclado e dispositivos móveis da Seção 7.3/G-0C. Esses subcenários seguem sem evidência completa.

- As evidências PathView atuais derivam de arquivos gerados por F1/scripts. Falta usar os arquivos efetivamente baixados dos botões F8; o probe mostra divergência material entre esses dois caminhos. Um teste E2E não deve substituir o download por uma nova chamada Python para fazer a comparação passar.

- Não há ciclo de salvar/reabrir o contêiner ZIP nativo pela UI. Testar `exportProject()`/snapshot IndexedDB é útil para T-RPC-02, mas não prova round-trip de arquivo `.ctrlab`.

- O runtime de produção Wasm continua sem Clarabel/CVXPY; o teste de indisponibilidade está correto, mas não demonstra T-SDP-D1/D2 no backend browser nem G-0B em dois navegadores.

- As medições de performance informam separadamente init, primeiro RPC e dez aquecidos com mediana/p95/desvio/heartbeat. O próprio teste registra heap JS como snapshot e não RSS pico completo; não se pode convertê-lo em garantia de limite de memória de toda a sessão ou de ausência de vazamento de proxies.

- A CI de browser usa Chromium. A matriz de segundo navegador de G-0B não foi exercida com um backend SDP disponível; compatibilidade ampla Firefox/mobile não é inferida.

### 3.2. O que deve ser preservado na remediação

Manter as oito entradas de integridade do conjunto ouro atual (sete fixtures JSON e checksums), as três fixtures históricas intactas e os valores/tolerâncias independentes novos. Não substituir referências científicas pelas saídas dos exports da UI. Os ensaios oficiais de 39+9 casos são valiosos e devem continuar como testes do produtor; acrescentar a comparação do artefato da UI para cobrir o consumidor, sem enfraquecer os testes existentes. Os logs de tentativas falhas/diagnóstico devem continuar preservados e claramente distinguidos dos passes finais.

## 4. Plano de Remediação Priorizado para o Maestro (PROJECT_STATE.json)

Plano externo, não executado no repositório. Os IDs RA2 abaixo são propostas de WPs novos. Aceites prévios de correções matemáticas devem ser preservados no domínio que foi demonstrado. Não marcar antigos achados integralmente resolvidos se o caminho de usuário ainda os reproduz; não reabrir solver/modelo corretos para corrigir um gerador UI paralelo.

### 4.1. Ordem exata e dependências

| Ordem | WP proposto / dono | Escopo e achados | Depende de | Critério de saída |
|:--|:--|:--|:--|:--|
| 1 | RA2-01 / F8 | Conter exportação PVM incorreta e injeção de metadado; AUD-020/021 | Nenhuma | Desabilitar caminho inseguro ou corrigi-lo sem anunciar integração pronta; teste de LF não gera instrução. |
| 2 | RA2-02 / F9 | Atualizar invariantes de governança/parser de handoff; AUD-016 | Nenhuma | Job B/core verde com estado verdadeiro; negativos de aceite sem evidência continuam falhando. |
| 3 | RA2-03 / F1 | Tornar teste de dependência opcional explícito; AUD-017 | Nenhuma | F1 passa nos perfis com/sem SDP; valida cálculo real no perfil disponível. |
| 4 | RA2-04 / F1 | Expor I/O aprovado via RPC, PVM oficial e ctrlab ZIP | RA2-01 | Operações versionadas, bytes, importação passiva e diagnósticos; nenhum serializer científico duplicado em JS. |
| 5 | RA2-05 / F8 | Consumir I/O F1, remover geradores paralelos; AUD-019/020/021 | RA2-04 | Download real .pvm e .ctrlab, reabertura de ZIP com invariantes; metadados seguros. |
| 6 | RA2-06 / F9 | E2E dos arquivos baixados e oráculo externo oficial | RA2-05 | Arquivo da UI aceita load_ctrlab; PVM da UI preserva conexões/estado e reproduz trajetórias PathView/PathSim. |
| 7 | RA2-07 / F9/gestor | Resolver proteção efetiva de main; AUD-018 | Nenhuma | Servidor exige checks/revisão F9 ou limitação permanece bloqueador formal, sem alegação de enforcement. |
| 8 | RA2-08 / F8 com F9 | Completar interação DOM/mobile/teclado/acessibilidade | RA2-05 | Gesto real, Escape/blur/troca de aba e revisão coerente; preview nunca persistente. |
| 9 | RA2-09 / F7 com F9 | Completar dossiê de proxies/memória/restart e matriz G-0A | RA2-02 | Medições e testes do domínio aprovado; sem promover snapshot heap a RSS/garantia universal. |
| 10 | RA2-10 / F6 com F9 | Decisão explícita de capacidade G-0B | RA2-03 | Backend PSD real em dois browsers ou indisponibilidade mantida com escopo de produto documentado. |
| 11 | RA2-11 / F9 | Reexecutar CI por perfis e formalizar G-0A/C/D | RA2-02/03/06/07/08/09 | Dossiês por SHA, fontes/wheel/assets idênticos, matriz normativa atualizada e decisão pass/conditional/fail. |
| 12 | RA2-12 / F9 | Reauditoria final de release e atualização de estado | RA2-10/11 | Nenhum PENDING vira aceite por mero teste de fallback; release somente no escopo explicitamente demonstrado. |

F1 implementa/adapta seu dispatcher/serializadores; F8 adapta seus consumidores. F9 aprova contratos, conserva oráculos e registra evidências, sem consertar produção científica de outra frente silenciosamente. Configuração de assinatura/plano/visibilidade do GitHub não foi autorizada pela auditoria; a indisponibilidade de proteção deve ser tratada pelo responsável como decisão explícita de governança, não simulada por texto local.

### 4.2. Recomendações para o estado atual

- Registrar os 11 achados anteriores corrigidos com referências à evidência e ao commit, mantendo histórico. Para AUD-003/011/012/013 usar resolução parcial e apontar os novos itens pertinentes, sem repetir o mesmo defeito como duas tarefas independentes.

- Preservar os aceites dos corretivos F1-CORE-RPC, F5-FML e F6-SDP e as provas do produtor PVM. Acrescentar WPs do consumidor F8 e de I/O RPC; um teste do exportador Python aprovado não libera o botão que não o chama.

- Reavaliar o aceite de compilação/UX F8 como parcial de integração, embora o typecheck esteja corrigido. Não atribuir a F1 o código paralelo que permanece em shell.ts.

- Manter todos os gates globais PENDING até relatório próprio. G-0B pode continuar indisponível honestamente; G-0D permanece bloqueado pela integração de arquivos, mesmo com os ótimos resultados externos do produtor.

- Corrigir o teste de governança para validar essa evolução legítima do estado, sem transformar os estados atuais em constantes eternas. Os dois novos handoffs têm checklist/evidência; o parser deve reconhecer o conteúdo ou exigir formato único explicitamente versionado.

- Não remover os bloqueios E/G para tornar a CI verde: primeiro suprir evidências e decisões. Distinguir falha do teste B de bloqueio de produto. Os locks/perfis precisam continuar verificando tanto ambiente core quanto ambiente com SDP.

### 4.3. Dados estruturados para ingestão pelo Antigravity

O bloco seguinte é metadado deste relatório, não patch do repositório. Os campos descrevem evidência e propostas; não autorizam escrita cruzada entre frentes.

```json
{
  "report_id": "AUD-EXT-CL-DIR-001-2026-11-15",
  "revision": 2,
  "normative_document": {
    "id": "CL-DIR-001",
    "version": "1.0.0",
    "path": "ControlLab_Web_Documento_Diretor_v1.0.md",
    "sha256": "f7f10b1a19eb6a145959693937e1c67c97717e6a93e2a690f0045c2f96768102"
  },
  "repository": "kozttah/ControlLab_Web",
  "commit": "60d5c5c8cd49d7a91b4d7d77b94582182565df59",
  "previous_commit": "e4b166af612e7abb55f98dcb38fbfc295fbd32b1",
  "repository_modified": false,
  "verdict": "NOT_APPROVED_FOR_STABLE_WEB_RELEASE",
  "previous_findings": [
    {
      "id": "AUD-001",
      "status": "CORRIGIDO",
      "evidence": "Fallback removido; cliente sem Worker/runtime falha sem resultado e sem commit. Testes F7 e PBH via dispatcher real passaram."
    },
    {
      "id": "AUD-002",
      "status": "CORRIGIDO",
      "evidence": "Worker default configurado na app, bootstrap local e core.rpc.dispatch efetivos. CI D/G exercita o produto no Pyodide real."
    },
    {
      "id": "AUD-003",
      "status": "PARCIAL",
      "evidence": "Build reproduzível/locks/manifesto/SBOM/workflows existem e build local concluiu. CI atual tem falha B e bloqueios E/G; ver AUD-016/017."
    },
    {
      "id": "AUD-004",
      "status": "CORRIGIDO",
      "evidence": "SW registrado, manifesto/hash/fechamento transitivo e readiness reais; CI F passa offline após reload, fonte do teste examinada."
    },
    {
      "id": "AUD-005",
      "status": "CORRIGIDO",
      "evidence": "Getters com cópia defensiva e revisão monotônica. Repetição dos probes: objeto intacto e edição na mesma revisão rejeitada."
    },
    {
      "id": "AUD-006",
      "status": "CORRIGIDO",
      "evidence": "SDP em bytes/shape imutáveis; mutação de getter não muda o problema; regressões independentes presentes."
    },
    {
      "id": "AUD-007",
      "status": "CORRIGIDO",
      "evidence": "Diagonalidade estrutural exige off-diagonal exatamente zero; bloco 1e-15 é recusado como unsupported_psd."
    },
    {
      "id": "AUD-008",
      "status": "CORRIGIDO",
      "evidence": "Escala PSD usa norma 2; probe diag(100,100,-1) devolve exatamente 1/101."
    },
    {
      "id": "AUD-009",
      "status": "CORRIGIDO",
      "evidence": "FML estrito recusa operador/sigma inválidos; testes F5/F9 preservam round-trip e perfil suportado."
    },
    {
      "id": "AUD-010",
      "status": "CORRIGIDO NO ESCOPO ORIGINAL",
      "evidence": "Doubles locais foram identificados; há CI com Worker/Pyodide, IDB e offline reais. Restam lacunas específicas de gesto DOM/exports, explicitadas nesta auditoria."
    },
    {
      "id": "AUD-011",
      "status": "PARCIAL",
      "evidence": "Produtor Python e testes PathView externos corrigidos; rota de download F8 ainda emite representação incompatível (AUD-020)."
    },
    {
      "id": "AUD-012",
      "status": "PARCIAL",
      "evidence": "Cobertura textual de ownership corrigida; branch main continua desprotegida (AUD-018)."
    },
    {
      "id": "AUD-013",
      "status": "PARCIAL",
      "evidence": "Handoffs, hashes, logs, revisão independente e limites agora existem. Falta fechar gates e a integração real de arquivos da UI; testes de governança não acompanham os novos dossiês."
    },
    {
      "id": "AUD-014",
      "status": "CORRIGIDO",
      "evidence": "TypeScript 5.8.3 compila; 50 testes Node locais passaram; C remoto confirma."
    },
    {
      "id": "AUD-015",
      "status": "CORRIGIDO",
      "evidence": "Runner falha fechado sem tsc/suíte; testes específicos de controle e CI passam, sem omissão silenciosa do typecheck."
    }
  ],
  "active_findings": [
    {
      "id": "AUD-016",
      "title": "Teste de governança congelou estados antigos e quebra o Job B atual",
      "severity": "MÉDIO (Contrato/Invariante Incompleto)",
      "front": "F9",
      "requirement": "R-23, R-24; Seções 10.5, 13.11, 14.1 e 15.2/Job B; Apêndice E",
      "files": [
        "tests/integration/test_governance_and_ownership.py:232-261",
        "tests/integration/test_governance_and_ownership.py:459-487",
        "PROJECT_STATE.json:46-61",
        "PROJECT_STATE.json:84-96"
      ],
      "diagnosis": "O teste exige G-0B=NOT_DEMONSTRATED e G-0D=BLOCKED_EXTERNAL_ACCEPTANCE, embora o estado atual registre corretamente indisponibilidade Wasm observada e interop externa parcial verificada. A primeira asserção divergente causa falha local e no GitHub Actions: Job B/core_no_sdp, 250 passed e 1 failed, run 43711325008. A mesma função exige exatamente 9 WPs corretivos; há 11, pois dois WPs PathView foram adicionados. Depois desses pontos, o validador espera cabeçalhos numerados que os dois novos handoffs não possuem. Ambos contêm decisão accepted, escopo, evidências e os dez itens do Apêndice E: o erro é incompatibilidade do validador, não ausência desses conteúdos. Fixar apenas o primeiro literal deixa falhas latentes e mantém o risco de testar um retrato histórico em vez das invariantes.",
      "action": "Trocar o teste de fotografia por invariantes: referências existentes, dependências acíclicas, aceite com evidência, gates monotônicos e maturidade compatível. Versões/estados permitidos devem ser validados por semântica e schema do estado, não por uma contagem histórica fixa. Harmonizar o formato dos handoffs e seu parser sem relaxar a obrigação dos dez itens e da decisão explícita. Não alterar estados verdadeiros para satisfazer asserts antigos.",
      "acceptance": "Executar scripts/ci_math.py core_no_sdp no ambiente isolado e congelado: Job B deve ficar verde no mesmo estado factual. Testes negativos devem continuar rejeitando aceite sem evidência, pendências mascaradas e dependências ausentes/cíclicas. Cobrir expansão de fila e atualização legítima de veredito sem exigir que gates já estejam aprovados.",
      "origin": "Novo desvio observado após a remediação; mantém AUD-003 parcialmente aberto."
    },
    {
      "id": "AUD-017",
      "title": "Teste F1 pressupõe ausência de solver opcional mesmo quando ele está instalado",
      "severity": "MÉDIO (Contrato/Invariante Incompleto)",
      "front": "F1",
      "requirement": "R-02, R-12, R-23; Seções 5.1, 6.2, 10.1 e 15.2",
      "files": [
        "tests/unit/f1/test_core_rpc_and_immutability.py:738-851",
        "control_lab/core/rpc.py:1812-1831"
      ],
      "diagnosis": "O teste multidomínio executa optimization.solve com backend auto e exige failure/SOLVER_UNAVAILABLE para uma LMI não diagonal. Com Clarabel/CVXPY instalados, a implementação resolve corretamente e retorna success, causando falha em test_core_rpc_and_immutability.py:850. Isso foi reproduzido com os locks de CI/PathView/browser instalados. O perfil oficial core_no_sdp da CI separa ambientes e essa falha não ocorreu nele; o Job B/sdp_available também passa. Portanto não é evidência de cálculo incorreto nem falha desse job. É uma suposição ambiental não explicitada no teste que torna o comando de aceite F1/pytest geral incompatível com a instalação all/SDP.",
      "action": "Separar o cenário de indisponibilidade do cenário com backend presente. Usar seleção explícita de backend indisponível ou ambiente de teste declarado para a falha, e testar sucesso auditado quando a capacidade existir. Preservar o teste end-to-end do dispatcher e do verificador; não mascarar um solver real por expected values fixos.",
      "acceptance": "Executar o comando F1 em ambientes core_no_sdp e sdp_available: a hipótese de cada teste deve ser explícita e os dois cenários devem passar sem skip oportunista. No cenário disponível verificar primal/dual/gap; no indisponível exigir SOLVER_UNAVAILABLE, sem controlador falso.",
      "origin": "Novo problema de portabilidade do teste; comportamento científico observado está correto."
    },
    {
      "id": "AUD-018",
      "title": "main continua sem proteção de branch efetiva no GitHub",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F9",
      "requirement": "R-23, R-24; Seções 13.2, 13.11 e 15.1; Apêndice E",
      "files": [
        "CODEOWNERS:11-18",
        ".github/workflows/ci.yml:1-25"
      ],
      "diagnosis": "A consulta autenticada GET /repos/kozttah/ControlLab_Web/branches/main retornou protected=false e protection.enabled=false, required_status_checks com enforcement_level=off e lista vazia. O mesmo commit ainda era HEAD ao final da aquisição. A consulta de rulesets devolveu 403 com mensagem de limitação do plano/repositório privado, portanto não foi possível inspecionar rulesets alternativos. O mapeamento textual CODEOWNERS foi corrigido e uma conferência independente contra os 433 caminhos de blobs retornou zero divergências, com ouro exclusivo da F9. Isso não configura enforcement no servidor: a CI atual falha, mas a branch não exige checks/revisão. Não se infere daí autoria indevida ou bypass já ocorrido.",
      "action": "Configurar proteção efetiva de main, com checks obrigatórios e revisão F9/Code Owner nas alterações normativas, usando identidades elegíveis. Resolver a indisponibilidade do recurso por decisão do responsável pelo repositório; esta auditoria não muda plano, visibilidade, permissões ou configurações. Um procedimento manual pode ser registrado como mitigação temporária, mas não deve ser apresentado como o enforcement mandatário da Seção 15.1.",
      "acceptance": "Apresentar leitura da API mostrando proteção aplicável e required checks/reviews; demonstrar em branch de teste que mudança de fixture sem revisão F9 e merge com check obrigatório falho são bloqueados. Não basta um teste local que analise texto de CODEOWNERS.",
      "origin": "Continuação de AUD-012, agora confirmada por evidência autenticada de servidor."
    },
    {
      "id": "AUD-019",
      "title": "UI oferece layout JSON de projeto, não o contêiner .ctrlab reabrível normativo",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F8",
      "requirement": "R-19; T-IO-01/round-trip integrado; Seções 9.1, 14.1/G-0D e 15.3",
      "files": [
        "web/app/main.ts:647-659",
        "web/app/shell.ts:676-775",
        "control_lab/core/rpc.py:1834-1880"
      ],
      "diagnosis": "O botão Exportar .ctrlab chama shell.exportCtrlLab(), que monta um objeto com format=controllab_ctrlab_export, portable_snapshot e archive_layout. main.ts serializa esse objeto como application/json e filename *.ctrlab.json. Não há compactação ZIP nem fluxo de reabertura de arquivo correspondente na interface. O probe externo inicializou o cliente com dispatcher CPython real, confirmou LQR e capturou exatamente esse pacote. load_ctrlab(bytes_do_download_JSON) retornou failure/VALIDATION_ERROR. O título JSON/Layout é uma ressalva real e não se afirma que o arquivo seja um ZIP malformado: o problema é que o formato nativo obrigatório não está entregue no fluxo do usuário. O I/O Python .ctrlab possui testes fortes e não apresentou esse defeito; o consumidor web ainda o contorna.",
      "action": "F1 deve fornecer operações RPC tipadas para exportar/importar o contêiner por seus serializers/validadores existentes, com bytes transferíveis e erros honestos. F8 deve consumir essas operações e implementar salvar/reabrir o arquivo real .ctrlab. Se o JSON auxiliar for mantido, apresentá-lo como outro formato, sem contar como cumprimento do backup nativo.",
      "acceptance": "Teste browser deve capturar o download efetivo do botão, exigir ZIP íntegro com manifest.json/modelos/controladores/experimentos, importar pelo mesmo caminho de produto e comparar matrizes, unidades, revisões, sinais e proveniência. Python load_ctrlab deve aceitar esses mesmos bytes. Traversal, ZIP bomb e preview/pending_commit continuam bloqueados.",
      "origin": "Novo achado de integração; aprofunda o bloqueio G-0D e o escopo de AUD-013."
    },
    {
      "id": "AUD-020",
      "title": "Botão .pvm ignora o exportador corrigido e perde a realimentação no PathView",
      "severity": "CRÍTICO (Bloqueador de Gate)",
      "front": "F8",
      "requirement": "R-02, R-04, R-20; T-PVM-01, T-PVM-02 no fluxo integrado; Seções 9.3, 14.1/G-0D; Apêndice D",
      "files": [
        "web/app/main.ts:629-642",
        "web/app/shell.ts:780-1003",
        "web/app/shell.ts:923-943",
        "tests/e2e/test_revision_recovery.py:43-70"
      ],
      "diagnosis": "F1 corrigiu o adaptador oficial e seus ensaios externos passam. O download real da UI, entretanto, chama o gerador paralelo ControlLabShell.exportPvm(), que continua emitindo MatrixGain e portas vetoriais abstratas. O probe chamou esse mesmo método após LQR real, sem fixture de resultado. O arquivo possui 5 nós e 5 conexões. No conversor oficial PathView 0.21.0, MatrixGain não é registrado; o Python gerado contém apenas 3 Connection(...) e nenhum K_lqr. As duas arestas do ganho desaparecem: a dinâmica executável não é a malha A-BK. Além disso, initial_state e os sinais de Adder não usam os parâmetros oficiais que F1 já traduziu; o conversor mostrado gera Adder() e StateSpace sem initial_value. A UI mantém aviso de gate pendente, o que é correto, mas o arquivo continua inadequado ao objetivo de exportação. Os novos testes de PathView avaliam make_pvm/export_pvm Python, não o arquivo entregue pelo botão. Esse desencontro explica por que 39/39 + 9/9 ensaios do produtor não encerram a integração do produto.",
      "action": "Remover o gerador PVM paralelo da UI e consumir o exportador F1 corrigido por uma operação RPC versionada. Até integrar e validar o download, desabilitar essa exportação de produto ou apresentá-la explicitamente como diagnóstico não executável, sem substituí-la por sucesso local de schema. F8 não deve copiar o lowering de F1 para TypeScript.",
      "acceptance": "Teste E2E deve baixar o arquivo real da UI para os casos C=I, C!=I, m!=p, sinal positivo/negativo e discreto suportado; o conversor oficial deve preservar todos os blocos/portas necessários e a simulação oficial deve reproduzir x/u/y e estados iniciais. Para controlador dinâmico exposto, testar também estados internos/feedthrough. O teste deve falhar com o download atual mesmo quando o exportador Python isolado passa.",
      "origin": "AUD-011 permanece parcialmente aberto na rota de usuário; nova causa localizada em F8."
    },
    {
      "id": "AUD-021",
      "title": "Metadado project_id pode introduzir instrução Python no código exportado",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F8",
      "requirement": "R-21, R-22, R-27; Seções 9.3 e 12.2; Apêndice D",
      "files": [
        "web/app/shell.ts:988-990",
        "web/app/main.ts:629-642"
      ],
      "diagnosis": "exportPvm interpola committed.project_id sem escape em um comentário de codeContext.code. A API aceita ID não vazio com quebra de linha. Usando project_id contendo external-audit-ui\\nprint(\"AUDIT_METADATA_INJECTION\")\\n#, o artefato ganhou uma linha print executável fora do comentário. ast.parse confirmou um nó Expr adicional; o conversor oficial preserva o bloco USER-DEFINED CODE. A reprodução não executou esse Python e não utilizou payload destrutivo ou rede. A condição de exploração é um projeto/API com ID controlado por entrada não confiável; não se afirma execução automática por ControlLab ou pela simples importação passiva. O risco aparece na execução externa de um arquivo que o usuário espera conter somente código derivado de dados científicos confiáveis. O aviso genérico de não executar na importação não sanitiza o código gerado.",
      "action": "Concentrar exportação no gerador científico aprovado e tratar metadados como dados: serialização segura, comentários com cada linha prefixada ou rejeição tipada dos caracteres não representáveis. Nunca interpolar texto livre em posição executável. Auditar outros campos textuais e exportações de scripts; não afrouxar a importação passiva.",
      "acceptance": "Teste com IDs contendo CR/LF, aspas, Unicode e tokens Python deve demonstrar que o AST do arquivo só contém instruções previstas pelo gerador. O arquivo pode ser recusado com erro tipado ou preservar o texto como literal/comentário, mas não pode ganhar nova instrução. Repetir no código produzido pelo conversor oficial, sem executar conteúdo não confiável.",
      "origin": "Novo achado de segurança na exportação, distinto da importação passiva T-IO-02."
    }
  ],
  "normative_coverage": [
    {
      "test_id": "T-CORE-01",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_core_models_and_interconnect.py:293; tests/unit/f1/test_core_rpc_and_immutability.py:167",
      "scope": "Caso dimensional literal e invariantes ampliados de arrays/revisão corrigidos. Probes e testes de imutabilidade passaram."
    },
    {
      "test_id": "T-CORE-02",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_core_models_and_interconnect.py:352",
      "scope": "A-BK e A+BK analíticos; N não quadrado m!=p e incompatibilidades. O fallback web apontado na primeira auditoria foi removido; a revisão atual usa o dispatcher científico real."
    },
    {
      "test_id": "T-CORE-03",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_core_models_and_interconnect.py:429",
      "scope": "Estado aumentado derivado com Dp/Dc não nulos, solução de loop e rejeição de singularidade; restrição de get_closed_loop_matrix aos controladores estáticos."
    },
    {
      "test_id": "T-TS-01",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_core_models_and_interconnect.py:581; tests/unit/f1/test_core_models_and_interconnect.py:1038; tests/unit/f5/test_f5_fuzzy_ts.py:670",
      "scope": "Bloqueia PDC em polytopic_uncertain sem estimador; exige premissas para parcialmente observado. TS medido usa termos duplos. Conformidade do contrato, não certificação de qualquer observador fornecido por usuário."
    },
    {
      "test_id": "T-CARE-01",
      "status": "CONFORME",
      "location": "tests/unit/f2/test_care_lqr.py:102",
      "scope": "B-CARE-02 analítico: P, K, polos, resíduo e sinal. Valores ouro não são saída da função sob teste."
    },
    {
      "test_id": "T-CARE-02",
      "status": "CONFORME",
      "location": "tests/unit/f2/test_care_lqr.py:173; tests/wasm/test_real_runtime.py:13",
      "scope": "Fixture CPython e paridade Pyodide com resíduo/espectro examinados em CI D/G do SHA auditado. Não foi uma repetição local de browser."
    },
    {
      "test_id": "T-CARE-03",
      "status": "CONFORME",
      "location": "tests/unit/f2/test_care_lqr.py:237; tests/wasm/test_real_runtime.py:77",
      "scope": "PBH Python e RPC real rejeitam hipótese violada sem ganho; fallback fixo removido."
    },
    {
      "test_id": "T-CARE-04",
      "status": "CONFORME",
      "location": "tests/unit/f2/test_care_lqr.py:331; tests/metamorphic/test_wasm_similarity.py:20",
      "scope": "x_tilde_0=T@x0, congruência, ganho/custo/polos; CPython e evidência Wasm em G. C-07 respeitado."
    },
    {
      "test_id": "T-FREQ-01",
      "status": "CONFORME",
      "location": "tests/unit/f3/test_frequency_siso_and_mimo.py:56",
      "scope": "G(s)=1/(s+a), Bode e degrau analíticos com a parametrizado."
    },
    {
      "test_id": "T-FREQ-02",
      "status": "CONFORME",
      "location": "tests/unit/f3/test_frequency_siso_and_mimo.py:158",
      "scope": "Casos com 3 cruzamentos de ganho e 2 de fase; contagens e avaliação independente por polinômios. Escopo das grades testadas; não prova universal de completude para toda TF."
    },
    {
      "test_id": "T-MIMO-01",
      "status": "CONFORME",
      "location": "tests/unit/f3/test_frequency_siso_and_mimo.py:308; tests/unit/f3/test_frequency_siso_and_mimo.py:421",
      "scope": "RGA quadrada/inversível, somas e S+T=I; invariância unitária e convenções de malha. inv em referência de teste, não no motor."
    },
    {
      "test_id": "T-MIMO-02",
      "status": "CONFORME",
      "location": "tests/unit/f3/test_frequency_siso_and_mimo.py:369",
      "scope": "Singularidade DC e planta não quadrada produzem diagnóstico undefined/recusa; não usa pseudoinversa como RGA clássica."
    },
    {
      "test_id": "T-ID-01",
      "status": "CONFORME",
      "location": "tests/unit/f4/test_identification.py:96",
      "scope": "ARX sem ruído contra coeficientes plantados por gerador recursivo do teste."
    },
    {
      "test_id": "T-ID-02",
      "status": "CONFORME",
      "location": "tests/unit/f4/test_identification.py:138",
      "scope": "Entrada constante, colinear e PRBS de período insuficiente: warning de PE/posto; não forja covariância."
    },
    {
      "test_id": "T-ID-03",
      "status": "CONFORME",
      "location": "tests/unit/f4/test_identification.py:193",
      "scope": "Holdout sintético, FIT/polos/estatística; previsão de um passo e simulação livre identificadas separadamente."
    },
    {
      "test_id": "T-FML-01",
      "status": "CONFORME",
      "location": "tests/unit/f5/test_f5_fuzzy_ts.py:134",
      "scope": "Duas regras TS confrontadas com avaliação manual e ponderação."
    },
    {
      "test_id": "T-FML-02",
      "status": "CONFORME",
      "location": "tests/unit/f5/test_f5_fuzzy_ts.py:314; tests/unit/f5/test_f5_fuzzy_ts.py:419; tests/oracles/test_fml_remediation_independent.py:70",
      "scope": "Round-trip no perfil suportado, rejeição estrita de inválidos e ataques XML. Novo probe inválido retorna failure/VALIDATION_ERROR."
    },
    {
      "test_id": "T-SDP-A1",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:229; tests/unit/f6/test_educational_solver_levels_a_to_d.py:108",
      "scope": "x>=1/min x: fronteira, objetivo/primal/dual; também solver didático experimental."
    },
    {
      "test_id": "T-SDP-A2",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:254; tests/unit/f6/test_sdp_modeling_and_verification.py:272; tests/unit/f6/test_sdp_modeling_and_verification.py:641",
      "scope": "x>=2/x<=1, Farkas auditado quando disponível; ausência/invalidade de certificado produz inconclusive. Não inferir infactibilidade de mero flag."
    },
    {
      "test_id": "T-SDP-A3",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:285",
      "scope": "Direção recessiva, ponto factível e ausência de certificado; ilimitado auditado ou inconclusive."
    },
    {
      "test_id": "T-SDP-B1",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:320",
      "scope": "Bloco analítico/fronteira e recusa LP; diagonalidade estrutural reforçada inclusive para off-diagonal 1e-15 e valores subnormais."
    },
    {
      "test_id": "T-SDP-C1",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:360; tests/unit/f6/test_educational_solver_levels_a_to_d.py:271",
      "scope": "Slater/primal/dual/gap e casos construídos; norma 2 do resíduo corrigida. Escopo CPython; G-0B produção Wasm segue não aprovado."
    },
    {
      "test_id": "T-SDP-D1",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:395; tests/unit/f6/test_educational_solver_levels_a_to_d.py:349",
      "scope": "Q SPD, recuperação por solve, espectro/alpha e solução explícita; sinais positivos/negativos."
    },
    {
      "test_id": "T-SDP-D2",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:440; tests/unit/f6/test_sdp_modeling_and_verification.py:859; tests/unit/f6/test_educational_solver_levels_a_to_d.py:384",
      "scope": "BRL generalizado nos backends e comparação didático/Clarabel; gamma e ganho. Grade Hinf é rotulada não rigorosa; ótimo via dual/gap e teste de gamma abaixo do ótimo da fixture. Não confundir CVXPY/Clarabel e Clarabel direto com dois algoritmos independentes."
    },
    {
      "test_id": "T-RPC-01",
      "status": "CONFORME",
      "location": "tests/e2e/test_revision_recovery.py:6",
      "scope": "20 revisões em Worker/Pyodide de browser; um único commit da revisão atual. CI E/G do mesmo SHA examinada."
    },
    {
      "test_id": "T-RPC-02",
      "status": "CONFORME",
      "location": "tests/e2e/test_revision_recovery.py:20",
      "scope": "Cancelamento/forceTerminate, reinício e snapshot IndexedDB confirmados em browser; comparação exclui apenas timestamp de exportação."
    },
    {
      "test_id": "T-IO-01",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_io_ctrlab_and_pvm.py:456; tests/unit/f1/test_io_ctrlab_and_pvm.py:481; tests/unit/f1/test_io_ctrlab_and_pvm.py:525; tests/unit/f1/test_io_ctrlab_and_pvm.py:584",
      "scope": "Traversal/ZIP bomb/limites/hash/revisão no importador nativo; também importação maliciosa Pyodide em CI F. Não valida por si o download JSON da UI."
    },
    {
      "test_id": "T-IO-02",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_io_ctrlab_and_pvm.py:673",
      "scope": "Importação PVM continua passiva em CPython/Pyodide, inclusive codeContext malicioso. Não confundir isso com a injeção no exportador UI de AUD-021."
    },
    {
      "test_id": "T-PVM-01",
      "status": "PARCIAL",
      "location": "scripts/audit_pvm_official.py; scripts/audit_pvm_discrete.py; web/app/shell.ts:784",
      "scope": "F1 passa em conversor/PathSim oficiais, incluindo ambos sinais/C!=I/MIMO/saturação e 39 confrontos discretos. Arquivo baixado pela UI perde ganho/conexões (AUD-020)."
    },
    {
      "test_id": "T-PVM-02",
      "status": "PARCIAL",
      "location": "scripts/audit_pvm_official.py; scripts/audit_pvm_discrete.py; tests/wasm/test_pvm_discrete_clock.py:55",
      "scope": "Dinâmica, feedthrough, estado inicial e relógio conjunto aprovados no produtor e fonte Wasm. O fechamento do fluxo UI/arquivo externo ainda não é demonstrado."
    },
    {
      "test_id": "T-UI-01",
      "status": "PARCIAL",
      "location": "tests/e2e/test_revision_recovery.py:43; tests/unit/f8/ui_mvp_lqr.test.ts:183",
      "scope": "Preview/pending_commit agora chega a engine real e novo ganho/revisão. Teste browser chama métodos pointerDown/Move/Up diretamente, não arraste DOM completo/mobile/teclado; exportações não estão integradas."
    },
    {
      "test_id": "T-SEC-01",
      "status": "CONFORME",
      "location": "tests/security/offline_browser.py:49; tests/security/test_real_browser_security.py:55",
      "scope": "SW/readiness, servidor parado, cache HTTP limpo, recarga/recalcular CARE e corrupção, além de CSP. CI F/G passou; limitação de repetição local explicitada."
    }
  ],
  "coverage_counts": {
    "CONFORME": 29,
    "PARCIAL": 3
  },
  "execution": {
    "web_unit_local": {
      "passed": 50,
      "skipped": 0,
      "typecheck": "PASS"
    },
    "native_aggregate_local": {
      "passed": 292,
      "failed": 3,
      "interpretation": [
        "AUD-016 governance mismatch",
        "AUD-017 optional solver environment assumption",
        "git inventory unavailable in API materialization, checked independently against 433 paths"
      ]
    },
    "focused_regressions_passed": 35,
    "official_pathview_discrete_cases_passed": 39,
    "official_pathview_regression_cases_passed": 9,
    "browser_local": "SETUP_BLOCKED_BY_ENVIRONMENT_NOT_A_PRODUCT_FAILURE",
    "browser_evidence": "GitHub Actions logs at audited SHA; D 8 pass, E 3 pass then gate block, F 3 pass, G 15 pass then gate block"
  },
  "ci_run_id": 43711325008,
  "branch_protected": false,
  "rulesets_inspection": "403 plan/private-repository feature limitation",
  "remediation": [
    {
      "order": 1,
      "proposed_wp": "RA2-01 / F8",
      "scope": "Conter exportação PVM incorreta e injeção de metadado; AUD-020/021",
      "dependencies": "Nenhuma",
      "acceptance": "Desabilitar caminho inseguro ou corrigi-lo sem anunciar integração pronta; teste de LF não gera instrução."
    },
    {
      "order": 2,
      "proposed_wp": "RA2-02 / F9",
      "scope": "Atualizar invariantes de governança/parser de handoff; AUD-016",
      "dependencies": "Nenhuma",
      "acceptance": "Job B/core verde com estado verdadeiro; negativos de aceite sem evidência continuam falhando."
    },
    {
      "order": 3,
      "proposed_wp": "RA2-03 / F1",
      "scope": "Tornar teste de dependência opcional explícito; AUD-017",
      "dependencies": "Nenhuma",
      "acceptance": "F1 passa nos perfis com/sem SDP; valida cálculo real no perfil disponível."
    },
    {
      "order": 4,
      "proposed_wp": "RA2-04 / F1",
      "scope": "Expor I/O aprovado via RPC, PVM oficial e ctrlab ZIP",
      "dependencies": "RA2-01",
      "acceptance": "Operações versionadas, bytes, importação passiva e diagnósticos; nenhum serializer científico duplicado em JS."
    },
    {
      "order": 5,
      "proposed_wp": "RA2-05 / F8",
      "scope": "Consumir I/O F1, remover geradores paralelos; AUD-019/020/021",
      "dependencies": "RA2-04",
      "acceptance": "Download real .pvm e .ctrlab, reabertura de ZIP com invariantes; metadados seguros."
    },
    {
      "order": 6,
      "proposed_wp": "RA2-06 / F9",
      "scope": "E2E dos arquivos baixados e oráculo externo oficial",
      "dependencies": "RA2-05",
      "acceptance": "Arquivo da UI aceita load_ctrlab; PVM da UI preserva conexões/estado e reproduz trajetórias PathView/PathSim."
    },
    {
      "order": 7,
      "proposed_wp": "RA2-07 / F9/gestor",
      "scope": "Resolver proteção efetiva de main; AUD-018",
      "dependencies": "Nenhuma",
      "acceptance": "Servidor exige checks/revisão F9 ou limitação permanece bloqueador formal, sem alegação de enforcement."
    },
    {
      "order": 8,
      "proposed_wp": "RA2-08 / F8 com F9",
      "scope": "Completar interação DOM/mobile/teclado/acessibilidade",
      "dependencies": "RA2-05",
      "acceptance": "Gesto real, Escape/blur/troca de aba e revisão coerente; preview nunca persistente."
    },
    {
      "order": 9,
      "proposed_wp": "RA2-09 / F7 com F9",
      "scope": "Completar dossiê de proxies/memória/restart e matriz G-0A",
      "dependencies": "RA2-02",
      "acceptance": "Medições e testes do domínio aprovado; sem promover snapshot heap a RSS/garantia universal."
    },
    {
      "order": 10,
      "proposed_wp": "RA2-10 / F6 com F9",
      "scope": "Decisão explícita de capacidade G-0B",
      "dependencies": "RA2-03",
      "acceptance": "Backend PSD real em dois browsers ou indisponibilidade mantida com escopo de produto documentado."
    },
    {
      "order": 11,
      "proposed_wp": "RA2-11 / F9",
      "scope": "Reexecutar CI por perfis e formalizar G-0A/C/D",
      "dependencies": "RA2-02/03/06/07/08/09",
      "acceptance": "Dossiês por SHA, fontes/wheel/assets idênticos, matriz normativa atualizada e decisão pass/conditional/fail."
    },
    {
      "order": 12,
      "proposed_wp": "RA2-12 / F9",
      "scope": "Reauditoria final de release e atualização de estado",
      "dependencies": "RA2-10/11",
      "acceptance": "Nenhum PENDING vira aceite por mero teste de fallback; release somente no escopo explicitamente demonstrado."
    }
  ],
  "do_not_auto_approve_gates": true
}
```

### 4.4. Fechamento da evidência

O HEAD remoto foi reconferido e permaneceu no SHA auditado. Os 432 blobs materializados foram comparados com os hashes da árvore autenticada; nenhum conteúdo versionado foi modificado. A norma da raiz continua byte a byte igual à versão usada na primeira auditoria. Os relatórios são externos ao repositório e não alteram PROJECT_STATE, fixtures, tolerâncias, código, CI ou configurações remotas.

O avanço científico e de infraestrutura é real e está documentado. A pendência decisiva é fechar o fluxo do usuário com os mesmos componentes que foram aprovados isoladamente: engine real, arquivo real, consumidor oficial e restauração real. A decisão de release deve ser baseada nesse caminho completo e no estado efetivo dos controles de governança.
