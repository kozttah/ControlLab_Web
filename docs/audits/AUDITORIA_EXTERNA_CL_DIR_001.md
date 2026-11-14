# Auditoria Externa Independente - ControlLab Web

**Identificador do relatório:** AUD-EXT-CL-DIR-001-2026-11-14  
**Data:** 14/11/2026 (America/Sao_Paulo)  
**Fonte normativa única:** `ControlLab_Web_Documento_Diretor_v1.0.md`, CL-DIR-001, versão 1.0.0, raiz do snapshot.  
**Snapshot auditado:** ZIP `ControlLab_Web-main.zip`, comentário de arquivo indicando commit `e4b166af612e7abb55f98dcb38fbfc295fbd32b1`. O comentário não equivale a validação criptográfica do commit remoto.  
**SHA-256 do ZIP:** `bfb281fc4f68938d33fd9e1f4d5346f6b7cd4fbaee8beb141f86f6622880aa6b`.  
**SHA-256 do documento normativo:** `f7f10b1a19eb6a145959693937e1c67c97717e6a93e2a690f0045c2f96768102`.  
**Regra operacional:** somente leitura do projeto. Nenhuma alteração, criação, exclusão, commit, push ou publicação no repositório. Relatórios e probes ficam fora da árvore auditada.

## 1. Sumário Executivo e Veredito Global por Gate e por Frente

**Veredito: NÃO APROVADO para liberação estável no navegador nem para fechamento dos gates.** O núcleo científico em CPython tem cobertura local substancial e as 146 verificações Python passaram. Isso não elimina defeitos reproduzidos nem comprova os ambientes externos. O risco mais grave é o caminho chamado Pyodide devolver e confirmar uma solução LQR pré-computada para uma planta não estabilizável, atribuindo-a ao SciPy sem executar Python.

Foram identificados **15 achados: 3 CRÍTICOS, 9 ALTOS e 3 MÉDIOS**. Os 11 WorkPackages constam como `ACCEPTED_BY_F9`; os quatro gates constam como `PENDING`. É correto mantê-los pendentes: este relatório não afirma que PROJECT_STATE já os aprovou. A discrepância é entre aceites amplos/rótulos stable e evidência efetivamente disponível, com defeitos presentes em entregas aceitas.

### 1.1. Método, execução e limites de evidência

O ZIP foi inspecionado antes da extração, com verificação de confinamento dos caminhos. Foram extraídos 153 arquivos regulares; criou-se cópia separada para testes. O acesso remoto anteriormente não disponibilizou o repositório, portanto este parecer se limita ao snapshot anexado. Não há histórico `.git`, PRs, branches nem configuração de proteção do GitHub no material; não se infere autoria, revisão ou bypass de proteção a partir de um ZIP. O espelho em docs foi conferido contra o documento da raiz; só o da raiz é normativo.

A inspeção abrangeu PROJECT_STATE, CODEOWNERS, schemas/exemplos/fixtures, gerador e oráculos, fontes e testes F1-F8, scripts e documentação de integração. Foram examinados corpos de funções críticas, relações matemáticas, decisões de status/capacidade, validação de entradas e mecanismos de importação. Foi feita varredura AST de todo `control_lab/` para chamadas inv/pinv/eval/exec e inspeção textual do caminho web. Os arquivos de laboratório legado em docs/references são material de referência, não evidência de que o runtime atual opere em browser. Esta é auditoria de evidências e implementação, não prova formal de ausência de todos os defeitos.

| Verificação executada | Resultado observado | Limite |
|:--|:--|:--|
| `python3 -m pytest -q` na cópia | 146 passed; 1 warning do plugin anyio/pytest; 5,67 s | CPython Linux; não Pyodide |
| `npm --prefix web test`, antes de instalar tsc | 36 passed; 0 skipped no Node | O runner pulou typecheck inteiro por falta de tsc |
| Mesma aceitação com TypeScript instalado | Typecheck falhou com 5 erros; unitários não executados nessa tentativa | TS 5.9.3 é permitido por ^5.8.0 |
| Probes externos Python | Mutações sem revisão; FML silencioso; escala PSD divergente; fallback LP não exato | Casos completos descritos nos achados |
| Probe externo Node | Planta não estabilizável recebeu LQR fixo success e committed=true | Sem loader Pyodide, usando cliente default |
| Integridade da fonte | Todos os 153 arquivos extraídos idênticos aos bytes do ZIP após a auditoria | Nenhuma alteração na árvore auditada |

Ambiente: Python 3.12.14; NumPy 2.3.5; SciPy 1.17.0; pytest 9.2.0; jsonschema 4.26.0; Clarabel 0.11.1; CVXPY 1.9.3; Node 24.22.1; TypeScript 5.9.3; Linux x86_64. As dependências de teste foram instaladas fora da fonte auditada. Esses números não são benchmark cold/warm nem representatividade de hardware de aluno. Não foram executados browser real, Pyodide/Wasm, PathView oficial ou teste de rede real offline; suas ausências são explicitadas, não tratadas como passes.

### 1.2. Gates

| Gate | Declarado | Veredito externo | Evidência necessária para aprovação |
|:--|:--|:--|:--|
| G-0A | PENDING | BLOQUEADO | Remover fallback falso; Worker/dispatcher reais; CARE 12x3 recalculada em CPython/Pyodide com versões, resíduos, cold/warm, restart e proxies |
| G-0B | PENDING | NÃO DEMONSTRADO | DSL/verificador/solvers CPython exercitados; falta load e solução PSD reais em dois browsers. Backend web continua unavailable_wasm |
| G-0C | PENDING | BLOQUEADO | Corrigir typecheck; construir artefato; UI com engine real, revisões/erros/cancelamento; depende G-0A |
| G-0D | PENDING | BLOQUEADO PARA ACEITE EXTERNO | ctrlab local tem testes fortes; falta abrir/simular .pvm no PathView oficial e fechar persistência UI real; depende G-0C |

G-0B pendente não bloqueia trabalho na DSL, auditor ou solver didático (Seção 13.8). Não se recomenda converter indisponibilidade Wasm em sucesso do solver educacional. A manutenção explícita de `clarabel_cvxpy: unavailable_wasm` no Worker é adequada; disponibilidade nativa em CPython não é prova web.

### 1.3. Frentes e estado declarado versus observado

| Frente | WPs declarados aceitos | Estado real observado | Decisão de auditoria |
|:--|:--|:--|:--|
| F1 | WP-01, WP-05 | Tipos/interconexões/ctrlab implementados; imutabilidade/revisão vulneráveis; PVM local sem aceitação externa | Reabrir invariantes; preservar testes locais; integração PVM pendente |
| F2 | WP-02 | CARE/DARE/PBH/LQR/LQI/observadores/simulação com boa cobertura CPython; rCARE e metamórfico corretos | Aceite local sustentado nos casos testados; produção Wasm não demonstrada |
| F3 | WP-07 | Frequência SISO/MIMO, RGA e S+T com testes analíticos | Aceite local sustentado; vertical web e Wasm pendentes |
| F4 | WP-08 | ARX/OE/subespaços, holdout, FIT separado, PE/posto com testes locais | Aceite local sustentado; sem prova de vertical browser |
| F5 | WP-09 | Inferência/ANFIS/TS, FML passivo; parser muda semântica de entradas inválidas | Solicitar correções FML antes de aceitar perfil fiel |
| F6 | WP-03, WP-10 | DSL/svec/status/certificados/A-D implementados; mutabilidade, redução LP e escala PSD divergentes | Reabrir invariantes/modelagem; didático segue experimental; G-0B aberto |
| F7 | WP-04 | Estado/revisão/transferências/proxies unitariamente exercitados; runtime padrão falso e offline incompleto | Reabrir aceite integrado; bloquear resultados autoritativos sem Python |
| F8 | WP-06 | Preview/pending_commit, gráficos e a11y em DOM simulado; cinco erros TS no conjunto | Reabrir aceite de compilação/integração; exigir engine real |
| F9 | WP-00 e aceites transversais | Ouro com validações legítimas; faltam CI/handoffs/evidência externa e ownership completo | Recompor trilha de evidências e reauditar WPs afetados |

### 1.4. Conformidades relevantes nos seis eixos

**Governança e anti-circularidade.** Os diretórios científicos e web seguem a divisão principal F1-F8. Fixtures têm SHA-256, matrizes explícitas e proveniência. O gerador `scripts/generate_golden_fixtures.py:1-9` não importa control_lab: B-CARE-02 tem solução fechada P=[[6,2],[2,3]], K=[2,3]; B-SDP-A-D tem exemplos analíticos, certificados e candidatos de controle verificados. B-CARE-12x3 usa a mesma rotina SciPy CARE consumida pela implementação, logo esse confronto sozinho não é um segundo algoritmo independente. Há, porém, conferência matemática externa por resíduos/simetria/PSD/estabilidade/PBH e custo integrado (`tests/oracles/test_golden_fixtures.py:430-507`, F2:173-233), que afasta a acusação de mera gravação circular sem validação. Recomenda-se outro algoritmo CARE na F9 para reduzir falha comum; não há evidência de adulteração das fixtures por produtores no ZIP. Integridade por hash não prova independência de autoria.

**Tolerâncias e skips.** Não foram encontrados decoradores pytest skip/xfail ativos nem testes Node explicitamente pulados. As tolerâncias de CARE analítica/12x3 e similaridade são coerentes com os resíduos/condicionamento exercitados; 1e-4 no custo integrado corresponde a quadratura trapezoidal, não à tolerância CARE. Não foi observada evidência de tolerância alterada para mascarar erro. A omissão de typecheck por falta de ferramenta (AUD-015) é uma forma distinta de aceite incompleto, invisível ao skipped do Node. CVXPY+Clarabel e Clarabel direto são dois adaptadores do mesmo solver, não dois solvers matematicamente independentes; casos analíticos e certificados permanecem essenciais.

**Modelos e interconexões.** Construção valida dimensões, finitude, dt e metadados de unidades. K/sinal e mapa N m×p são explícitos. `core/interconnect.py:239-295` restringe get_closed_loop_matrix; `:609-628` resolve I-s Dc Dp e monta estado aumentado; `controllers.py:1140-1250` verifica semântica TS/premissas/revisão. Há termos duplos h_i h_j em TSClosedLoop, sem substituição geral por média congelada. Os testes locais correspondentes passaram. A falha de imutabilidade pós-construção é separada e material.

**Rigor numérico.** A varredura AST não identificou inv/pinv/eval/exec em chamadas de produção do pacote científico. O inv em `tests/unit/f3/test_frequency_siso_and_mimo.py:474` é referência de teste, não síntese/solução do motor. `statespace/_utils.py:533-611` implementa exatamente as normas Frobenius e somas de termos de CARE/DARE/Lyapunov; PBH precede ganho em `equations.py:523-570`. T-CARE-04 transforma obrigatoriamente x0 nos dois regimes de condicionamento. RGA recusa não quadrada/singular (`frequency/mimo/analysis.py:380-478`). F4 separa one_step_prediction/free_simulation e FIT, detectando falta de PE/posto; não foi encontrado desvio concreto nesses casos examinados.

**SDP e certificados.** svec tem sqrt(2) fora da diagonal e isometria (`modeling/svec.py:79-111`); DSL rejeita produtos bilineares e desigualdades estritas sem estratégia (`tests/unit/f6/test_sdp_modeling_and_verification.py:113-190`). O verificador possui as cinco dimensões, reconstitui primal, dual, estacionariedade/gap/complementaridade. Farkas usa soma <Fk,Z> menos E^T nu/H^T lambda nula e constante <F0,Z>+d^T nu+h^T lambda estritamente negativa (`verification/verifier.py:381-478`). Sem certificado retorna inconclusive (`:701-729`); direção recessiva exige ponto factível. Não foi observado uso de flag do solver como prova de infactibilidade. Os defeitos AUD-006/007/008 afetam invariantes/redução/escala, não invalidam essa constatação específica. A classificação numérica continua dependente das tolerâncias; não é prova exata universal, especialmente em weak infeasibility.

**I/O, bridge e UI.** ctrlab verifica nomes normalizados, limites compactados/descompactados, duplicidades/symlinks, hashes/versão e leitura passiva; testes de ZIP bomb/traversal passaram. PVM não executa codeContext recebido; FML bloqueia DTD/entidades/expansões e limita tamanho/profundidade. Não foi demonstrada exploração de execução de código por importação. Portas e C!=I têm testes internos; exportação informa a pendência PathView. O coordenador descarta revisões antigas e os guards testam destroy de PyProxy em sucesso/erro/cancelamento; Fast-Preview não persiste e pending_commit protege o fluxo local. A comprovação em Worker/Pyodide/browser real ainda falta, e AUD-001 compromete a autoridade do resultado.

## 2. Tabela/Lista de Achados de Auditoria

Os locais abaixo são caminhos relativos à raiz do snapshot. Intervalos indicam trechos inspecionados; arquivos ausentes são descritos como ausência e ancorados no consumidor/configuração existente. A frente responsável segue o ownership normativo/CODEOWNERS; colaboradores são explicitados sem autorizar escrita cruzada. Severidade de gate também pode representar evidência de integração indispensável ainda ausente, não necessariamente defeito no algoritmo local.

| ID | Severidade | Frente | Achado |
|:--|:--|:--|:--|
| AUD-001 | CRÍTICO | F7 | LQR pré-computado é confirmado como cálculo SciPy sem runtime Python |
| AUD-002 | CRÍTICO | F7 | Caminho padrão não cria Worker científico real e entrypoint Python inexiste |
| AUD-003 | ALTO | F9 | Snapshot não contém pipeline reprodutível de build/distribuição e Jobs A-G |
| AUD-004 | ALTO | F7 | Manifesto offline não cobre o fechamento de dependências e SW não é registrado |
| AUD-005 | ALTO | F1 | Imutabilidade científica pode ser burlada por APIs públicas e colisão de revisão |
| AUD-006 | ALTO | F6 | Problema SDP canônico também expõe armazenamento mutável |
| AUD-007 | ALTO | F6 | Fallback LP classifica matrizes aproximadamente diagonais como redução exata |
| AUD-008 | MÉDIO | F6 | Resíduo PSD relativo usa norma de Frobenius no lugar da norma 2 normativa |
| AUD-009 | ALTO | F5 | Importação FML reinterpreta silenciosamente operadores e parâmetros inválidos |
| AUD-010 | ALTO | F9 | Testes intitulados paridade real/offline não exercitam os ambientes exigidos |
| AUD-011 | CRÍTICO | F9 | T-PVM-01/02 não demonstram curvas no PathView oficial |
| AUD-012 | MÉDIO | F9 | CODEOWNERS não implementa ownership completo nem exclusividade das fixtures F9 |
| AUD-013 | ALTO | F9 | Aceites F9 e rótulos stable não possuem pacote de evidências suficiente no snapshot |
| AUD-014 | ALTO | F8 | TypeScript não compila: contratos F7/F8 e narrowing incoerentes |
| AUD-015 | MÉDIO | F9 | Runner permite aceite verde sem compilador TypeScript |

### AUD-001 - LQR pré-computado é confirmado como cálculo SciPy sem runtime Python

**ID:** AUD-001  
**Severidade:** CRÍTICO (Bloqueador de Gate)  
**Frente Responsável:** F7  
**Requisito / Teste Violado:** R-01, R-02, R-09, R-17, R-27, R-28; Seções 4.4, 8.3 e 14.1/G-0A  
**Arquivo(s) e Linhas Afetadas:** `web/worker/pyodide_worker.ts:354-385`; `web/worker/pyodide_worker.ts:574-591`; `web/worker/pyodide_worker.ts:1007-1176`  
**WorkPackages Afetados:** WP-04-F7-RPC-BRIDGE-WORKER, WP-06-F8-UI-MVP-LQR  

**Diagnóstico Técnico/Matemático:** O init sem loader passa a initialized=true; as capabilities anunciam numpy_scipy disponível/stable e offline_ready=true. executeFallbackDesignLqr seleciona valores pelo número de estados: para n=2 devolve K=[2,3], P=[[6,2],[2,3]], polos [-2,-1], custo 13, rCARE=0 e proveniência scipy.linalg.solve_continuous_are. Não calcula a partir de A/B/Q/R/x0/sinal. A reprodução externa enviou A=diag(1,2), B=0, Q=I, R=1, x0=[1,0], sinal positivo. Essa planta é não estabilizável: A+B K=A tem polos [1,2]. Mesmo assim recebeu success, hipóteses verdadeiras, sinal negativo e diagnostics.committed=true. Para outras ordens são produzidos polos artificiais sem P/K. Não é mera ausência de gate: é falsa resposta científica observada.

**Ação Corretiva Recomendada:** Eliminar o fallback científico de PyodideEngineClient/Worker. Sem runtime e entrypoint verificados, retornar SOLVER_UNAVAILABLE, não comitar e anunciar capacidade indisponível. Reservar fixtures exclusivamente ao MockWorkerAdapter explicitamente identificado como mock; não atribuir algoritmo/versões não executados.

**Critério de Aceite:** Adicionar teste de regressão F7 com a planta não estabilizável acima e com duas plantas/pesos distintos de mesma ordem. Sem Pyodide, ambos devem falhar sem ganho/polos inventados e sem commit; com engine real, T-CARE-03 deve rejeitar a planta. Executar npm --prefix web test e T-RPC-01; F9 deve executar também G-0A real.

### AUD-002 - Caminho padrão não cria Worker científico real e entrypoint Python inexiste

**ID:** AUD-002  
**Severidade:** CRÍTICO (Bloqueador de Gate)  
**Frente Responsável:** F7  
**Requisito / Teste Violado:** ADR-001; R-01, R-02, R-16; Seções 8.1, 13.9 e 14.1/G-0A/G-0C  
**Arquivo(s) e Linhas Afetadas:** `web/bridge/pyodide_client.ts:193-207`; `web/app/main.ts:71-82`; `web/worker/pyodide_worker.ts:556-579`; `web/worker/pyodide_worker.ts:957-985`; `PROJECT_STATE.json:171-172`  
**WorkPackages Afetados:** WP-04-F7-RPC-BRIDGE-WORKER, WP-06-F8-UI-MVP-LQR  

**Diagnóstico Técnico/Matemático:** mountControlLabApp cria PyodideEngineClient() sem workerUrl. spawnWorkerTransport só instancia new Worker quando workerUrl é fornecido; no caminho padrão usa MessageChannel e runtime na mesma thread. Não há importação/bootstrap de loadPyodide no bundle. Quando um runtime Python genuíno é fornecido, a execução depende de control_lab.web_rpc.dispatch, mas nenhum control_lab/web_rpc.py integra o ZIP. PROJECT_STATE reconhece essa ausência como follow-up do WP-04 aceito. MessageChannel não isola a execução científica síncrona em outra thread.

**Ação Corretiva Recomendada:** F7 deve fornecer URL/default de Worker real, bootstrap local do Pyodide e handshake que só finalize após importar e testar o dispatcher. F1 deve implementar o dispatcher em caminho de sua propriedade (por exemplo control_lab/core/rpc.py), ou F9 deve aprovar explicitamente ownership do entrypoint raiz antes da implementação; F7 atualiza o módulo consumido. Não há autorização implícita para F7 escrever no pacote científico de outra frente.

**Critério de Aceite:** Teste browser real deve demonstrar Worker separado, import do mesmo pacote científico de CPython, B-CARE-02 e B-CARE-12x3 recalculados, evento de UI atendido durante cálculo, cancelamento/reinício e erro tipado se dispatcher faltar. npm/pytest unitários são pré-requisitos, não substitutos do Job D.

### AUD-003 - Snapshot não contém pipeline reprodutível de build/distribuição e Jobs A-G

**ID:** AUD-003  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F9  
**Requisito / Teste Violado:** R-02, R-22, R-23, R-24; Seções 11.2, 12.2, 15.1-15.3  
**Arquivo(s) e Linhas Afetadas:** `web/package.json:1-13`; `web/tsconfig.json:1-28`; `pyproject.toml:1-47`; `CODEOWNERS:22-23`; `web/app/index.html:18-19`  
**WorkPackages Afetados:** WP-00-F9-BOOTSTRAP, WP-04-F7-RPC-BRIDGE-WORKER, WP-06-F8-UI-MVP-LQR  

**Diagnóstico Técnico/Matemático:** O pacote web só declara typecheck/test; tsconfig impõe noEmit e imports .ts. index.html solicita /app/main.js, inexistente na árvore. Não existem .github/workflows/, artefatos JS/Wasm/wheels, lockfiles congelados, release-manifest.json, SBOM ou docs/legal no ZIP. Há requisitos de versão abertos (>= no Python e ^ no TypeScript). A ausência de binários versionados não é isoladamente defeito; o problema é também não haver receita de build/provisionamento que gere os recursos e comprove a distribuição. Não há evidência dos Jobs A-G normativos. O snapshot não comprova configuração remota de branch protection, portanto isso permanece não verificável.

**Ação Corretiva Recomendada:** F9 deve adicionar build reproduzível e CI por escopo, congelar toolchain/dependências efetivamente distribuídas, construir wheel e JS com imports resolvidos, gerar manifesto de hashes/SBOM/licenças e provisionar assets locais. F8 fornece entry HTML/CSS válido e F7 fornece worker/bootstrap. Não exigir commit de binários se pipeline e artefato auditável os produzirem.

**Critério de Aceite:** De checkout limpo, um comando documentado deve gerar site estático completo; Job C deve compilar sem erros, Job B executar matemática, Job D abrir browser com Wasm, Job E persistência/integração e Jobs F/G segurança/hashes/offline. Registrar ambiente, SHA e resultados como artefatos.

### AUD-004 - Manifesto offline não cobre o fechamento de dependências e SW não é registrado

**ID:** AUD-004  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F7  
**Requisito / Teste Violado:** R-01, R-22; T-SEC-01; Seções 11.2 e 12.2  
**Arquivo(s) e Linhas Afetadas:** `web/worker/service_worker.ts:21-47`; `web/worker/service_worker.ts:389-426`; `web/app/index.html:7-19`; `web/app/main.ts:71-82`  
**WorkPackages Afetados:** WP-04-F7-RPC-BRIDGE-WORKER  

**Diagnóstico Técnico/Matemático:** O manifesto default lista 11 URLs, mas omite styles.css e módulos importados por main/client/worker (shell, tool_descriptor, protocol, pyodide_client, mock_adapter, features, charts, storage e pyproxy_guard, entre outros). Também não comprova a lista real dos arquivos transitivos do Pyodide. Não há chamada navigator.serviceWorker.register na árvore web. checkOfflineReadiness apenas percorre as URLs do manifesto; não testa completude transitiva nem que bytes cacheados sejam executáveis. O status offline_ready do Worker é constante, não depende desse provisionamento.

**Ação Corretiva Recomendada:** Gerar manifesto a partir do build e do inventário Pyodide efetivo; incluir CSS, módulos, biblioteca padrão/pacotes necessários e hashes. Registrar SW com escopo correto. Derivar offline_ready do provisionamento confirmado; manter atualização atômica e política de versões.

**Critério de Aceite:** T-SEC-01 em browser: instalar artefato real, calcular LQR, fechar/reabrir aba com rede bloqueada, editar A/Q e recalcular, conferir resultado e registrar todas as requisições. Apagar uma dependência transitiva deve tornar readiness falsa ou impedir capacidade offline; nenhuma resposta de placeholder pode contar como asset válido.

### AUD-005 - Imutabilidade científica pode ser burlada por APIs públicas e colisão de revisão

**ID:** AUD-005  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F1  
**Requisito / Teste Violado:** R-03, R-19; T-CORE-01; Seções 4.1 e 8.2; Apêndice B  
**Arquivo(s) e Linhas Afetadas:** `control_lab/core/models.py:169-180`; `control_lab/core/models.py:220-234`; `control_lab/core/models.py:333-334`; `control_lab/core/models.py:660-665`; `control_lab/core/controllers.py:299-301`; `control_lab/core/controllers.py:698-712`; `control_lab/core/controllers.py:1062-1065`  
**WorkPackages Afetados:** WP-01-F1-CORE-MODELS, WP-05-F1-IO-CTRLAB-PVM  

**Diagnóstico Técnico/Matemático:** Os getters devolvem o próprio ndarray interno, que possui memória própria. setflags(write=False) só bloqueia a escrita inicial: p.A.setflags(write=True); p.A[0,0]=NaN modifica o objeto validado, preservando id/revision. O mesmo foi reproduzido com ctrl.K, alterado para [999,3]. Além disso, p.with_revision(p.revision,A=nova_A) aceita conteúdo diferente com a mesma identidade/revisão; com revision=4, A=0 e A=100 coexistem sob a mesma chave. Revisões históricas deixam de identificar conteúdo científico. O teste atual só tenta atribuição direta e incremento padrão, sem esses casos. Result, em contraste, copia dados em leitura e não apresentou essa falha nos probes.

**Ação Corretiva Recomendada:** Não expor armazenamento interno mutável: retornar cópia defensiva ou view sobre backing imutável apropriado. Aplicar a todas as matrizes/polinômios/controladores/vértices, incluindo estruturas aninhadas. Rejeitar mesma revisão ou revisão menor quando houver alteração científica; operações que só acrescentem hash sem mudar conteúdo podem preservar revisão explicitamente.

**Critério de Aceite:** Ampliar pytest F1/T-CORE-01 com setflags(write=True), mutação de arrays retornados e evolução com revisão igual/menor para todos os tipos. O estado anterior, hash, id/revision e controladores dependentes devem continuar coerentes; NaN/Inf não pode ser introduzido após validação pela API pública.

### AUD-006 - Problema SDP canônico também expõe armazenamento mutável

**ID:** AUD-006  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F6  
**Requisito / Teste Violado:** R-11, R-14; Seção 6.1  
**Arquivo(s) e Linhas Afetadas:** `control_lab/optimization/modeling/canonical.py:73-112`; `control_lab/optimization/modeling/canonical.py:126-147`; `control_lab/optimization/modeling/canonical.py:149-165`; `control_lab/optimization/modeling/canonical.py:316-346`  
**WorkPackages Afetados:** WP-03-F6-SDP-MODELING-AND-GATE0B, WP-10-F6-SDP-EDUCATIONAL-SOLVER  

**Diagnóstico Técnico/Matemático:** SDPBlock.F0/F_terms/get_Fk e CanonicalSDPProblem.c/E/d/H/h devolvem referências aos arrays internos. No probe, F0=I foi alterado com setflags para [[1,10],[0,1]]. evaluate passou a devolver [[1,5],[5,1]] pela simetrização, sem nova validação e sem invalidar is_diagonal já calculado. Solver e auditor podem observar dados diferentes do problema originalmente aprovado, e a seleção do fallback LP pode ficar obsoleta.

**Ação Corretiva Recomendada:** Congelar efetivamente dados/bases do problema e retornar cópias ou buffers imutáveis; impedir alteração posterior de atributos estruturais e de blocos compartilhados. Recalcular propriedades apenas a partir de modelo validado; não usar simetrização como reparo de mutação indevida.

**Critério de Aceite:** Adicionar pytest F6 com mutação dos getters, mapas e blocos após canonicalização. evaluate, assinatura do modelo e seleção de backend devem permanecer inalterados, ou uma alteração deve exigir novo CanonicalSDPProblem validado. Reexecutar bateria A-D.

### AUD-007 - Fallback LP classifica matrizes aproximadamente diagonais como redução exata

**ID:** AUD-007  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F6  
**Requisito / Teste Violado:** R-11, R-12, R-14; Seções 6.1 e 6.2  
**Arquivo(s) e Linhas Afetadas:** `control_lab/optimization/modeling/svec.py:68-76`; `control_lab/optimization/modeling/canonical.py:90-112`; `control_lab/optimization/backends/scipy_linprog.py:72-98`  
**WorkPackages Afetados:** WP-03-F6-SDP-MODELING-AND-GATE0B  

**Diagnóstico Técnico/Matemático:** is_diagonal_matrix usa tolerância absoluta 1e-14; esse flag habilita o backend LP, que descarta todos os termos fora da diagonal. A norma admite LP somente por redução exata no sistema canônico. Probe: F(x)=[[x,1e-15],[1e-15,0]], min x. O determinante é -1e-30 para todo x, logo não há ponto PSD exato. O código classifica diagonal, resolve min x sujeito apenas a x>=0 e retorna x=0, solver_status=optimal, approximately_feasible, validated_dual e warning. O warning de condicionamento observado não torna a redução estrutural exata. Não se conclui que todo pequeno resíduo invalida uma solução numérica; o defeito é eliminar dados não nulos para decidir a classe do problema.

**Ação Corretiva Recomendada:** Separar teste de diagonalidade estrutural do diagnóstico de proximidade. Para fallback exato exigir zero fora da diagonal em F0 e todos Fk, ou transformação exata explicitamente certificada; aproximação opcional deve criar outro modelo com proveniência/erro, sem claim de redução exata.

**Critério de Aceite:** Adicionar pytest F6 com o bloco acima e variações de escala. ScipyLinprogBackend deve recusar com unsupported_psd qualquer off-diagonal não nulo, inclusive abaixo de 1e-14. Casos realmente diagonais seguem aprovados; comparar com backend SDP sem silenciar condicionamento.

### AUD-008 - Resíduo PSD relativo usa norma de Frobenius no lugar da norma 2 normativa

**ID:** AUD-008  
**Severidade:** MÉDIO (Contrato/Invariante Incompleto)  
**Frente Responsável:** F6  
**Requisito / Teste Violado:** R-14; Seção 6.3 (resíduos normalizados)  
**Arquivo(s) e Linhas Afetadas:** `control_lab/optimization/verification/verifier.py:182-190`  
**WorkPackages Afetados:** WP-03-F6-SDP-MODELING-AND-GATE0B  

**Diagnóstico Técnico/Matemático:** A norma fixa v_b/(1+||F0||_2+sum |xk| ||Fk||_2), mas _audit_primal_point soma normas Frobenius. Para F0=diag(100,100,-1), x=0 e F1=0, v=1: código relata 0,007021244586351119; expressão normativa dá 1/101=0,009900990099009901. Em blocos maiores isso reduz o valor reportado e altera o limiar efetivo por dimensão. CARE e Lyapunov usam corretamente Frobenius, pois suas fórmulas normativas são outras.

**Ação Corretiva Recomendada:** Usar norma espectral 2 na escala dos blocos PSD. Se um diagnóstico adicional em Frobenius for útil, nomeá-lo separadamente; não substituir a métrica normativa.

**Critério de Aceite:** Adicionar pytest com matriz diagonal de norma 2 diferente da Frobenius, validar valor exato 1/101 e casos multi-bloco com x não nulo. Revalidar classificações perto do limiar e registrar tolerâncias por fixture.

### AUD-009 - Importação FML reinterpreta silenciosamente operadores e parâmetros inválidos

**ID:** AUD-009  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F5  
**Requisito / Teste Violado:** R-10, R-21; T-FML-02; Seções 5.6 e 9.4  
**Arquivo(s) e Linhas Afetadas:** `control_lab/fuzzy/fml.py:82-116`; `control_lab/fuzzy/fml.py:494-522`; `control_lab/fuzzy/fml.py:703-711`; `control_lab/fuzzy/fml.py:802-817`  
**WorkPackages Afetados:** WP-09-F5-FUZZY-FML-ANFIS  

**Diagnóstico Técnico/Matemático:** _from_fml_and devolve min para qualquer token desconhecido; _from_fml_or devolve max. Parâmetros triangulares/trapezoidais são ordenados; sigma gaussiano passa por abs e, se zero, vira 1e-3; bell usa abs e pisos 1e-6. Probe de XML TS com andMethod="UNSUPPORTED" e gaussianShape param2="0" retorna success, warnings=[] e modelo com and=min e sigma=0,001. Assim um arquivo fora do perfil/semanticamente inválido ganha significado novo sem consentimento ou aviso. O bloqueio XXE/DTD foi inspecionado e seus testes passaram: este achado trata de fidelidade científica, não de execução de XML.

**Ação Corretiva Recomendada:** Rejeitar operador não suportado e parâmetros inválidos antes de construir FuzzySystem. Se houver modo de migração/reparo legado, torná-lo explícito e registrar cada mudança em warnings/provenance; padrão estrito não deve corrigir silenciosamente. Validar o perfil e rejeitar estruturas de regra que não possam ser representadas fielmente.

**Critério de Aceite:** Ampliar pytest F5/T-FML-02 com operador desconhecido, sigma zero/negativo, vértices fora de ordem e estrutura não suportada. Esperar failure com código tipado, ou warning apenas em modo de reparo autorizado. Manter equivalência numérica em grade para round-trip válido.

### AUD-010 - Testes intitulados paridade real/offline não exercitam os ambientes exigidos

**ID:** AUD-010  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F9  
**Requisito / Teste Violado:** R-17, R-22, R-23; T-SEC-01, T-RPC-02, T-UI-01; Seções 8.3, 10.1, 12.2 e 15.2  
**Arquivo(s) e Linhas Afetadas:** `tests/unit/f7/rpc_bridge_worker.test.ts:767-830`; `tests/unit/f7/rpc_bridge_worker.test.ts:1149-1204`; `tests/unit/f8/ui_mvp_lqr.test.ts:352-417`; `PROJECT_STATE.json:164-172`  
**WorkPackages Afetados:** WP-04-F7-RPC-BRIDGE-WORKER, WP-06-F8-UI-MVP-LQR  

**Diagnóstico Técnico/Matemático:** T-SEC-01 usa InMemoryCacheStorage e um fetch que devolve comentário JS fictício para todo asset, inclusive Wasm/wheel; confirma cache HIT, sem importar/rodar cálculo em navegador. F7-PARITY-01 usa o PyodideEngineClient sem runtime Python, portanto compara o Mock com o fallback fixo de AUD-001. Os testes F8 usam ambiente DOM simulado; não comprovam mobile/teclado/navegador real ou FPS medido. Esses unitários são úteis para estado/contrato, mas suas descrições e associação aos gates superestimam o que provam. Não foi detectada troca de expected values em função sob teste: o falso positivo nasce da substituição do ambiente de execução.

**Ação Corretiva Recomendada:** F9 deve criar testes independentes em tests/wasm/, tests/e2e/ e tests/security/ usando artefato real e asserts científicos. As frentes F7/F8 mantêm seus unitários e ajustam os rótulos para o escopo efetivo; F9 não deve alterar tolerâncias desses testes para esconder defeitos. Paridade deve usar entradas variadas e evidência de que o Python foi invocado.

**Critério de Aceite:** Job D: B-CARE-12x3 em Chromium/Firefox; Job E: 20 revisões, hard terminate e recuperação de IndexedDB real; Job F: T-SEC-01 com rede bloqueada e novo cálculo. Teste deve falhar se dispatcher for removido ou se respostas forem fixas, mesmo mantendo schemas válidos.

### AUD-011 - T-PVM-01/02 não demonstram curvas no PathView oficial

**ID:** AUD-011  
**Severidade:** CRÍTICO (Bloqueador de Gate)  
**Frente Responsável:** F9  
**Requisito / Teste Violado:** R-20; T-PVM-01, T-PVM-02; Seções 9.3 e 14.1/G-0D; Apêndice D  
**Arquivo(s) e Linhas Afetadas:** `control_lab/io/pvm.py:80-92`; `control_lab/io/pvm.py:1254-1284`; `tests/unit/f1/test_io_ctrlab_and_pvm.py:774-885`; `tests/unit/f1/test_io_ctrlab_and_pvm.py:963-1065`; `PROJECT_STATE.json:197-200`  
**WorkPackages Afetados:** WP-05-F1-IO-CTRLAB-PVM  

**Diagnóstico Técnico/Matemático:** O registro de blocos declara external_pathview_verified=False; a exportação retorna warning e metadata gate_pending=G-0D. Os testes verificam grafo/schema e simulação/extração por funções do próprio pacote, não a importação e geração de Python no aplicativo PathView oficial. São bons testes algébricos locais, porém não validam o registro real de blocos/portas/arrays/callbacks da versão-alvo. C!=I está tratado localmente com porta de x separada e controladores dinâmicos têm estados internos; não foi provado que o aplicativo externo os aceita. O estado PENDING de G-0D é correto; o bloqueio é de aceitação externa, sem acusação de gate falsamente aprovado.

**Ação Corretiva Recomendada:** F9 deve fixar versão/build do PathView-alvo e executar aceitação independente dos arquivos gerados por F1. Manter exportador explicitamente experimental/desativado como integração aprovada até a evidência. Corrigir eventuais incompatibilidades exclusivamente via F1; oferecer fallback PathSim com aviso se necessário.

**Critério de Aceite:** Abrir .pvm no PathView oficial, comprovar importação, diagrama, geração de Python e simulação; comparar x/u/y e estados internos para C=I, C!=I, m!=p, ambos sinais e controlador dinâmico com Dp/Dc não nulos. Repetir saturação com referência não linear equivalente. Anexar versão, arquivos, curvas, tolerâncias, SHA e parecer F9.

### AUD-012 - CODEOWNERS não implementa ownership completo nem exclusividade das fixtures F9

**ID:** AUD-012  
**Severidade:** MÉDIO (Contrato/Invariante Incompleto)  
**Frente Responsável:** F9  
**Requisito / Teste Violado:** R-23, R-24; Seções 13.2, 13.11, 15.1; Apêndice E  
**Arquivo(s) e Linhas Afetadas:** `CODEOWNERS:1-23`; `CODEOWNERS:17-18`; `AGENTS.md:9-17`; `PROJECT_STATE.json:49-61`  
**WorkPackages Afetados:** WP-00-F9-BOOTSTRAP  

**Diagnóstico Técnico/Matemático:** Nenhuma regra cobre tests/unit/f1..f8, scripts/, tests/metamorphic/, tests/performance/, testes de integração ou configurações compartilhadas web. A regra /contracts/ lista F9 e F1 e não há override para /contracts/fixtures/: não expressa a exclusividade de F9 exigida para valores ouro. A árvore dos módulos de produção está alinhada ao mapa F1-F8; o ZIP sem histórico Git/PRs não permite atribuir autoria real ou provar alteração cruzada. Também não permite confirmar se @f1-... são identidades elegíveis nem se revisão F9 é obrigatória no servidor.

**Ação Corretiva Recomendada:** F9 deve completar as regras unitárias/compartilhadas e criar override exclusivo de fixtures; proteger aprovação de contratos/valores ouro pela revisão F9 e por CI de caminhos/hashes. Confirmar identidades e regras de branch no GitHub antes de alegar enforcement. CODEOWNERS sozinho não impede escrita nem substitui branch protection.

**Critério de Aceite:** Teste de governança deve resolver cada caminho e comparar com mapa normativo; alterações em contracts/fixtures por produtor devem exigir revisão F9 e nunca passar só pela aprovação do autor produtor. Auditar amostra de PRs/commits com evidência de autoria e revisão independente.

### AUD-013 - Aceites F9 e rótulos stable não possuem pacote de evidências suficiente no snapshot

**ID:** AUD-013  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F9  
**Requisito / Teste Violado:** R-23, R-24; Seções 10.5, 13.11, 14.1, 15.3; Apêndice E  
**Arquivo(s) e Linhas Afetadas:** `PROJECT_STATE.json:49-62`; `PROJECT_STATE.json:80-85`; `PROJECT_STATE.json:164-172`; `PROJECT_STATE.json:218-227`; `web/worker/pyodide_worker.ts:367-386`  
**WorkPackages Afetados:** WP-00-F9-BOOTSTRAP, WP-01-F1-CORE-MODELS, WP-03-F6-SDP-MODELING-AND-GATE0B, WP-04-F7-RPC-BRIDGE-WORKER, WP-05-F1-IO-CTRLAB-PVM, WP-06-F8-UI-MVP-LQR, WP-09-F5-FUZZY-FML-ANFIS, WP-10-F6-SDP-EDUCATIONAL-SOLVER  

**Diagnóstico Técnico/Matemático:** Os 11 WPs têm ACCEPTED_BY_F9 e f9_review="accepted", mas o snapshot não inclui handoffs por WP, commit/PR de revisão, checklist de 10 itens, logs de paridade Wasm, benchmarks cold/warm, release-manifest ou matriz de evidências independente. O campo textual accepted não comprova independência. Gates permanecem PENDING e isso é correto; entretanto operações anunciam stable e disponibilidade mesmo sem runtime. A conclusão não é que nenhuma revisão ocorreu: é que sua execução e seu escopo não são auditáveis com os artefatos entregues. Pendências conhecidas do dispatcher/PathView não têm WPs de remediação executáveis.

**Ação Corretiva Recomendada:** F9 deve registrar para cada WP escopo local vs integrado, evidências/ambiente/SHA, parecer e bloqueadores. Aceites dos WPs com defeitos reproduzidos devem ser reabertos; WPs científicos aprovados localmente podem conservar seu histórico, mas sem equivaler a produção stable. Criar WPs de integração/gates e issues dos achados, com dependências e critérios verificáveis.

**Critério de Aceite:** Cada accepted deve apontar para artefatos reprodutíveis, não apenas string; todos os itens do Apêndice E devem ter resposta com evidência ou limitação. CI valida requisitos/testes/gates e impede stable no alvo sem prova Wasm. Gates só mudam após relatório pass revisado; esta auditoria não altera PROJECT_STATE.json.

### AUD-014 - TypeScript não compila: contratos F7/F8 e narrowing incoerentes

**ID:** AUD-014  
**Severidade:** ALTO (Violação Matemática/Segurança)  
**Frente Responsável:** F8  
**Requisito / Teste Violado:** R-16, R-17, R-18, R-24; Seções 7.1, 13.10 e 15.2/Job C  
**Arquivo(s) e Linhas Afetadas:** `tests/unit/f8/ui_mvp_lqr.test.ts:171-176`; `web/app/main.ts:745-749`; `web/app/shell.ts:11-15`; `web/app/tool_descriptor.ts:280-295`; `web/bridge/client.ts:128-155`  
**WorkPackages Afetados:** WP-06-F8-UI-MVP-LQR  

**Diagnóstico Técnico/Matemático:** Com TypeScript 5.9.3, permitido por ^5.8.0, npm --prefix web test falha antes dos unitários com cinco erros: TS2353 simulatedLatencyMs não existe em MockWorkerAdapterOptions; TS2339 getCommittedRevision não está na interface ControlLabEngineClient; TS2459 ExecutionMetrics é importado de client.ts sem export; dois TS2367 comparam union já estreitada com unavailable_wasm. Sem tsc, Node remove tipos e os 36 unitários passam. Portanto o comando de aceite de WP-06 não é verde quando o typecheck é efetivamente instalado. Métodos existentes na classe concreta não suprem ausência na interface.

**Ação Corretiva Recomendada:** F8 deve corrigir os usos de seu código/teste e o fluxo de narrowing; usar nome de opção correto e importar tipo da origem pública apropriada. Se getCommittedRevision precisa fazer parte do contrato público, F7 deve acrescentá-lo na interface e testar consumidores, em alteração própria. Rever available para operação ausente do catálogo: a condição atual dependia de comparação inalcançável.

**Critério de Aceite:** Instalação limpa das dependências declaradas seguida de npm --prefix web run typecheck e npm --prefix web test deve concluir sem os cinco erros. Adicionar teste para operação não anunciada por capabilities; não silenciar com any, @ts-ignore ou afrouxamento de strict.

### AUD-015 - Runner permite aceite verde sem compilador TypeScript

**ID:** AUD-015  
**Severidade:** MÉDIO (Contrato/Invariante Incompleto)  
**Frente Responsável:** F9  
**Requisito / Teste Violado:** R-24; Seções 10.5, 15.2/Job C e 15.3  
**Arquivo(s) e Linhas Afetadas:** `scripts/run_web_tests.mjs:73-98`; `scripts/run_web_tests.mjs:103-108`; `web/package.json:6-12`  
**WorkPackages Afetados:** WP-00-F9-BOOTSTRAP, WP-04-F7-RPC-BRIDGE-WORKER, WP-06-F8-UI-MVP-LQR  

**Diagnóstico Técnico/Matemático:** Se tsc não é encontrado, o runner só avisa e continua com node --test. Isso ocorreu na primeira execução: 36 passed, zero skipped reportados pelo Node, apesar de o typecheck inteiro ter sido pulado. Depois de instalar TypeScript, a mesma base falhou com os erros de AUD-014. O número skipped=0 não cobre esse estágio omitido. O runner também sai com sucesso se não achar arquivos de teste, sem distinguir escopo vazio de configuração quebrada.

**Ação Corretiva Recomendada:** F9 deve fazer o comando de aceite/CI falhar se compilador ou suíte obrigatória estiver ausente; se houver modo rápido deliberado, usar outro comando com nome e relatório explícitos, que não conte como aceite. Instalar dependências de desenvolvimento antes da execução e fixar toolchain.

**Critério de Aceite:** Teste do runner sob PATH sem tsc deve retornar código não zero para escopo TS ativo; diretórios de testes obrigatórios vazios também devem falhar. Com dependências presentes, executar typecheck e os 36 testes. Registrar separadamente resultado de compilação e unitários.

## 3. Auditoria de Cobertura dos Testes Normativos (Apêndice C)

Todos os **32 IDs** do catálogo são aplicáveis porque os módulos correspondentes já existem e/ou seus WPs foram aceitos. Os 32 possuem teste local com ID/nome ou referência reconhecível. Isso não implica que cubram todo o cenário exigido.

**Legenda:** CONFORME = caso literal demonstrado localmente por assert pertinente; PARCIAL = há parte válida mas falta requisito ambiental/semântico ou invariante do escopo solicitado; AUSENTE = nenhuma implementação de teste para o cenário; FALSO POSITIVO = teste verde não demonstra a propriedade anunciada e há evidência objetiva do desencontro. CONFORME local não aprova maturidade stable no navegador. T-CORE-01 passa no exemplo dimensional literal, mas foi marcado PARCIAL pela exigência ampliada de imutabilidade desta auditoria. T-CARE-02 permanece PARCIAL pela paridade CPython/Pyodide, ainda que a referência CPython esteja correta.

**Contagem:** CONFORME: 24, PARCIAL: 7, AUSENTE: 0, FALSO POSITIVO: 1.

| Teste | Status | Evidência / Limitação |
|:--|:--|:--|
| T-CORE-01 | PARCIAL | `tests/unit/f1/test_core_models_and_interconnect.py:293`. Dimensões inválidas, dt, NaN/Inf e construção sem objeto parcial: conforme ao caso literal do catálogo. Invariante ampliado de imutabilidade/revisão falha nos probes (AUD-005); não declarar conformidade integral do modelo. |
| T-CORE-02 | CONFORME | `tests/unit/f1/test_core_models_and_interconnect.py:352`. A-BK e A+BK analíticos; N não quadrado m!=p e incompatibilidades. Conformidade local; o fallback web viola essa semântica fora deste teste (AUD-001). |
| T-CORE-03 | CONFORME | `tests/unit/f1/test_core_models_and_interconnect.py:429`. Estado aumentado derivado com Dp/Dc não nulos, solução de loop e rejeição de singularidade; restrição de get_closed_loop_matrix aos controladores estáticos. |
| T-TS-01 | CONFORME | `tests/unit/f1/test_core_models_and_interconnect.py:581; tests/unit/f1/test_core_models_and_interconnect.py:1038; tests/unit/f5/test_f5_fuzzy_ts.py:670`. Bloqueia PDC em polytopic_uncertain sem estimador; exige premissas para parcialmente observado. TS medido usa termos duplos. Conformidade do contrato, não certificação de qualquer observador fornecido por usuário. |
| T-CARE-01 | CONFORME | `tests/unit/f2/test_care_lqr.py:102`. B-CARE-02 analítico: P, K, polos, resíduo e sinal. Valores ouro não são saída da função sob teste. |
| T-CARE-02 | PARCIAL | `tests/unit/f2/test_care_lqr.py:173; tests/oracles/test_golden_fixtures.py:430`. CARE 12x3 passa em CPython com fixture/resíduos/PBH/custo integrado. Não há paridade Pyodide observada, nem cold/warm/Job D: requisito cross-platform permanece aberto. |
| T-CARE-03 | CONFORME | `tests/unit/f2/test_care_lqr.py:237`. Modos não estabilizáveis/não detectáveis e Q/R inválidas são rejeitados por PBH no motor Python; fallback web contorna o motor (AUD-001). |
| T-CARE-04 | CONFORME | `tests/unit/f2/test_care_lqr.py:331`. Transforma x0_t1=T_good@x0 e x0_t2=T_bad@x0; testa P/K, custo/polos, caso bem condicionado e aviso no mal condicionado. C-07 respeitado. |
| T-FREQ-01 | CONFORME | `tests/unit/f3/test_frequency_siso_and_mimo.py:56`. G(s)=1/(s+a), Bode e degrau analíticos com a parametrizado. |
| T-FREQ-02 | CONFORME | `tests/unit/f3/test_frequency_siso_and_mimo.py:158`. Casos com 3 cruzamentos de ganho e 2 de fase; contagens e avaliação independente por polinômios. Escopo das grades testadas; não prova universal de completude para toda TF. |
| T-MIMO-01 | CONFORME | `tests/unit/f3/test_frequency_siso_and_mimo.py:308; tests/unit/f3/test_frequency_siso_and_mimo.py:421`. RGA quadrada/inversível, somas e S+T=I; invariância unitária e convenções de malha. inv em referência de teste, não no motor. |
| T-MIMO-02 | CONFORME | `tests/unit/f3/test_frequency_siso_and_mimo.py:369`. Singularidade DC e planta não quadrada produzem diagnóstico undefined/recusa; não usa pseudoinversa como RGA clássica. |
| T-ID-01 | CONFORME | `tests/unit/f4/test_identification.py:96`. ARX sem ruído contra coeficientes plantados por gerador recursivo do teste. |
| T-ID-02 | CONFORME | `tests/unit/f4/test_identification.py:138`. Entrada constante, colinear e PRBS de período insuficiente: warning de PE/posto; não forja covariância. |
| T-ID-03 | CONFORME | `tests/unit/f4/test_identification.py:193`. Holdout sintético, FIT/polos/estatística; previsão de um passo e simulação livre identificadas separadamente. |
| T-FML-01 | CONFORME | `tests/unit/f5/test_f5_fuzzy_ts.py:134`. Duas regras TS confrontadas com avaliação manual e ponderação. |
| T-FML-02 | PARCIAL | `tests/unit/f5/test_f5_fuzzy_ts.py:314; tests/unit/f5/test_f5_fuzzy_ts.py:419`. Round-trip em grade passa no perfil exercitado e ataques XXE são bloqueados. Operadores/parâmetros inválidos são reinterpretados silenciosamente, fora da cobertura (AUD-009). |
| T-SDP-A1 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:229; tests/unit/f6/test_educational_solver_levels_a_to_d.py:108`. x>=1/min x: fronteira, objetivo/primal/dual; também solver didático experimental. |
| T-SDP-A2 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:254; tests/unit/f6/test_sdp_modeling_and_verification.py:272; tests/unit/f6/test_sdp_modeling_and_verification.py:641`. x>=2/x<=1, Farkas auditado quando disponível; ausência/invalidade de certificado produz inconclusive. Não inferir infactibilidade de mero flag. |
| T-SDP-A3 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:285`. Direção recessiva, ponto factível e ausência de certificado; ilimitado auditado ou inconclusive. |
| T-SDP-B1 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:320`. Bloco [[1,x],[x,1]], x=-1; ótimo na fronteira e recusa LP para não-diagonal evidente. AUD-007 cobre lacuna de classificação para termos pequenos. |
| T-SDP-C1 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:360; tests/unit/f6/test_educational_solver_levels_a_to_d.py:271`. Slater 3x3, primal/dual/gap e referência analítica; suíte construída/weak infeasibility. Residual normalizado geral ainda precisa AUD-008. |
| T-SDP-D1 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:395; tests/unit/f6/test_educational_solver_levels_a_to_d.py:349`. Q SPD, recuperação por solve, espectro/alpha e solução explícita; sinais positivos/negativos. |
| T-SDP-D2 | CONFORME | `tests/unit/f6/test_sdp_modeling_and_verification.py:440; tests/unit/f6/test_sdp_modeling_and_verification.py:859; tests/unit/f6/test_educational_solver_levels_a_to_d.py:384`. BRL generalizado nos backends e comparação didático/Clarabel; gamma e ganho. Grade Hinf é rotulada não rigorosa; ótimo via dual/gap e teste de gamma abaixo do ótimo da fixture. Não confundir CVXPY/Clarabel e Clarabel direto com dois algoritmos independentes. |
| T-RPC-01 | CONFORME | `tests/unit/f7/rpc_bridge_worker.test.ts:272`. 20 revisões e só revisão atual comita no coordenador Node/MessageChannel. Propriedade de estado exercitada; não comprova runtime Python ou browser real. |
| T-RPC-02 | PARCIAL | `tests/unit/f7/rpc_bridge_worker.test.ts:531`. Cancelamento/rehidratação exercitados com stores in-memory e transporte simulado; falta terminate de Worker e IndexedDB reais com Pyodide. |
| T-IO-01 | CONFORME | `tests/unit/f1/test_io_ctrlab_and_pvm.py:456; tests/unit/f1/test_io_ctrlab_and_pvm.py:481; tests/unit/f1/test_io_ctrlab_and_pvm.py:525; tests/unit/f1/test_io_ctrlab_and_pvm.py:584`. Traversal sem criação de arquivos, symlink/Unicode/colisões, ZIP bomb/limites, integridade e versão. Inspeção de importação passiva compatível com testes locais. |
| T-IO-02 | CONFORME | `tests/unit/f1/test_io_ctrlab_and_pvm.py:673`. codeContext malicioso é lido como dados; hooks de eval/exec não executam conteúdo. Código Python determinístico de exportação não é confundido com código importado confiável. |
| T-PVM-01 | PARCIAL | `tests/unit/f1/test_io_ctrlab_and_pvm.py:774; tests/unit/f1/test_io_ctrlab_and_pvm.py:886`. Grafo/portas, C!=I, m!=p, sinais e saturação verificados internamente. Curvas no PathView oficial AUSENTES; o teste explicita external_pathview_verified=False. |
| T-PVM-02 | PARCIAL | `tests/unit/f1/test_io_ctrlab_and_pvm.py:963; tests/unit/f1/test_io_ctrlab_and_pvm.py:1067`. Controlador dinâmico/estado aumentado/feedthrough testados no simulador interno. Importação e curvas/estados no aplicativo externo AUSENTES. |
| T-UI-01 | PARCIAL | `tests/unit/f8/ui_mvp_lqr.test.ts:183; tests/unit/f8/ui_mvp_lqr.test.ts:352`. Fast-Preview sem persistência e pending_commit são cobertos em DOM simulado, mas resultado científico é mock/fallback e typecheck falha. Falta fluxo final com engine/browser reais. |
| T-SEC-01 | FALSO POSITIVO | `tests/unit/f7/rpc_bridge_worker.test.ts:767`. Teste verde de placeholders em CacheStorage in-memory é apresentado como offline real. Não há cálculo Pyodide offline nem navegador; recursos transitivos/SW não fechados (AUD-004/AUD-010). |

### 3.1. Subcenários normativos sem evidência, apesar de haver ID local

- T-CARE-02/G-0A: benchmark em Pyodide real, tempos cold/warm, restart e memória/proxies - AUSENTES no snapshot.
- T-RPC-02: terminate de Worker real, reconstrução de objetos Python e IndexedDB nativo em browser - AUSENTES.
- T-UI-01/G-0C: teste do gesto real com cálculo Python, edição durante cálculo, cancelamento e apresentação acessível em dispositivo - AUSENTE; mecanismos locais são parciais.
- T-PVM-01/02/G-0D: importação, geração de código e curvas na distribuição oficial do PathView - AUSENTES. Simulador próprio não é esse oráculo externo.
- T-SEC-01: cálculo científico após recarga sem rede, com recursos realmente cacheados e inspeção de requests - AUSENTE; unitário atual é falso positivo para esse propósito.
- G-0B: resolver PSD/BRL/infactível em Pyodide com dois browsers e registrar limites/memória - AUSENTE. `run_gate_0b_assay` em CPython explicitamente avisa que não aprova o gate final.

### 3.2. Testes de regressão adicionais a incorporar

Os nomes abaixo são propostas de novos testes, não IDs já existentes. A propriedade científica é o critério; os nomes podem seguir a convenção da frente.

| Proposta | Frente autora | Propriedade indispensável |
|:--|:--|:--|
| `test_no_python_runtime_no_scientific_success` | F7 | Sem runtime, SOLVER_UNAVAILABLE, nenhuma falsa proveniência/commit |
| `test_unstabilizable_plant_through_real_rpc` | F9 | Planta A=diag(1,2), B=0 falha via Python; ganho fixo não passa |
| `test_arrays_cannot_change_model_revision_content` | F1 | setflags/mutação não altera modelo; mesma revisão não aceita edição |
| `test_canonical_sdp_deep_immutability` | F6 | Bases/custos/constraints não mudam após validação |
| `test_lp_requires_exact_structural_diagonal` | F6 | Off-diagonal 1e-15 recusa fallback LP |
| `test_psd_violation_uses_spectral_norm` | F6 | diag(100,100,-1) relata 1/101 |
| `test_fml_invalid_parameters_are_not_silently_repaired` | F5 | Sigma zero/operador desconhecido falham em modo estrito |
| `test_acceptance_runner_requires_tsc_and_tests` | F9 | Pré-requisito ausente implica falha de aceite |
| `test_offline_real_calculation_after_reload` | F9 | Assets executáveis completos, recarga offline e novo LQR |

## 4. Plano de Remediação Priorizado para o Maestro (PROJECT_STATE.json)

Este plano é uma instrução proposta ao Antigravity. **Não foi executada nenhuma edição de estado ou código.** Os identificadores REM abaixo são novos WPs sugeridos, externos ao snapshot; o Maestro deve criá-los no fluxo normal de governança. Dependência satisfeita significa evidência aceita pela F9, não apenas execução sem exceção.

### 4.1. Ordem exata e dependências

| Ordem | WP proposto / dono | Escopo e achados | Depende de | Critério de saída |
|:--|:--|:--|:--|:--|
| 1 | REM-01 / F9 | Registrar auditoria, reabrir aceites afetados, mapear ownership/evidências (AUD-012/013) | Nenhuma | Issues e responsáveis; gates seguem PENDING; sem alegação stable web |
| 2 | REM-02 / F7 | Remover fallback falso e capacidades inventadas (AUD-001) | REM-01 | Falha honesta sem runtime; teste de planta não estabilizável não comita |
| 3 | REM-03 / F9 | Tornar typecheck e suítes obrigatórios (AUD-015) | REM-01 | Runner falha fechado sem tsc/testes; CI instala toolchain fixada |
| 4 | REM-04 / F1 | Imutabilidade/revisões; contrato do dispatcher sob ownership aprovado (AUD-005; parte AUD-002) | REM-01 | pytest F1 e probes corrigidos; API do dispatcher revisada F9 |
| 5 | REM-05 / F6 | Congelar SDP, diagonalidade exata e norma 2 (AUD-006/007/008) | REM-04 | A-D e novos casos adversariais aprovados |
| 6 | REM-06 / F5 | FML estrito e sem reparo silencioso (AUD-009) | REM-04 | XML inválido recusa; round-trip válido conserva saída |
| 7 | REM-07 / F7 | Expor contrato público necessário a F8, Worker real, bootstrap/dispatcher (AUD-002; colaboração AUD-014) | REM-02, REM-04 | Testes reais de execução/cancelamento; nenhuma computação na thread UI |
| 8 | REM-08 / F8 | Corrigir cinco erros TS e disponibilidade de ferramenta (AUD-014) | REM-03, REM-07 | Typecheck estrito + unitários; sem any/ignores para esconder contrato |
| 9 | REM-09 / F9 | Build estático, wheels/assets, manifesto/SBOM/licenças e Jobs A-G (AUD-003) | REM-05, REM-06, REM-08 | Artefato de checkout limpo com hashes/versões; servidor estático abre app |
| 10 | REM-10 / F7 | Registro SW e fechamento offline real (AUD-004) | REM-09 | Manifesto transitivo/hashes; readiness comprovada, atualização atômica |
| 11 | REM-11 / F9 | Testes Wasm reais e evidência G-0A (AUD-010/013) | REM-07, REM-09, REM-10 | Mesmo pacote CARE 12x3 em CPython/Pyodide; relatório pass revisado |
| 12 | REM-12 / F6 + F9 | Ensaio browser G-0B e decisão de backend | REM-05, REM-09, REM-11 | Dois browsers PSD/BRL auditados ou indisponibilidade Wasm documentada |
| 13 | REM-13 / F9 com F8/F7 | E2E G-0C, T-RPC-02, T-UI-01 e T-SEC-01 (AUD-010) | REM-08, REM-10, REM-11 | Sem mocks científicos; revisões, falhas, cancelamento, recarga offline reais |
| 14 | REM-14 / F9 com F1 | PathView oficial e persistência G-0D (AUD-011) | REM-13, REM-04 | Arquivos/curvas/estados externos e round-trip documentados |
| 15 | REM-15 / F9 | Reauditoria final e atualização de maturidade/estado | REM-12, REM-13, REM-14 | Checklist E, matriz R/T/F, manifesto, relatório de gate e parecer independente |

REM-12 pode registrar G-0B não aprovado e manter backend indisponível sem impedir a vertical LQR; apenas o SDP local de produção continua bloqueado. A ordem acima prioriza contenção da resposta falsa antes de ampliar infraestrutura. Ela não autoriza produtores a tocar em paths F9 nem F9 a corrigir silenciosamente código científico. Se a integração exigir novo caminho compartilhado, F9 aprova ownership/contrato antes da implementação.

### 4.2. Tratamento recomendado do estado existente

- **Reabrir com changes_requested** WP-01 (invariantes), WP-03 (SDP), WP-04 (runtime/segurança de resultado), WP-06 (compilação/integração), WP-09 (FML). WP-10 deve registrar dependência corretiva em WP-03 e conservar maturity experimental.
- **WP-05:** conservar evidência de I/O/álgebra local; registrar integração externa blocked_by_gate, com WP de G-0D obrigatório. Não reinterpretar o teste interno como passe externo.
- **WP-02/WP-07/WP-08:** preservar aceites científicos locais que passaram, explicitando que não aprovam distribuição stable/Wasm. Corrigir apenas se novos testes concretos mostrarem falha.
- **WP-00/F9:** reabrir governança/CI/ownership e separar aceite de bootstrap de aceite de release. Não apagar histórico de aceites anteriores; acrescentar decisão de reauditoria e evidência do motivo.
- **Gates G-0A..D:** manter PENDING no arquivo até os relatórios próprios. No painel de auditoria, G-0A/C/D podem exibir bloqueadores e G-0B ausência de demonstração, sem inventar enums novos no schema do estado.
- Cada correção necessita de teste da frente, handoff com 10 respostas do Apêndice E e parecer F9 com caminho/artefato/SHA. Testes aprovados em Node com fallback não contam como evidência Python; testes em CPython não contam como Wasm; simulador PVM local não conta como PathView.

### 4.3. Instrução estruturada para ingestão pelo Antigravity

O bloco JSON a seguir é metadado do relatório, não patch do repositório. Nenhum caminho está implicitamente autorizado a escrita pela auditoria. O Maestro aplica mudanças somente em seu próprio fluxo de desenvolvimento.

```json
{
  "report_id": "AUD-EXT-CL-DIR-001-2026-11-14",
  "normative_document": {
    "id": "CL-DIR-001",
    "version": "1.0.0",
    "path": "ControlLab_Web_Documento_Diretor_v1.0.md"
  },
  "snapshot_commit_claim": "e4b166af612e7abb55f98dcb38fbfc295fbd32b1",
  "read_only_audit": true,
  "repository_modified": false,
  "verdict": "NOT_APPROVED_FOR_STABLE_WEB_RELEASE",
  "gates": {
    "G-0A": "BLOCKED",
    "G-0B": "NOT_DEMONSTRATED",
    "G-0C": "BLOCKED",
    "G-0D": "BLOCKED_EXTERNAL_ACCEPTANCE"
  },
  "test_results": {
    "python_passed": 146,
    "node_unit_passed_without_typecheck": 36,
    "typescript_errors": 5,
    "browser_executed": false,
    "pathview_executed": false
  },
  "findings": [
    {
      "id": "AUD-001",
      "severity": "CRÍTICO (Bloqueador de Gate)",
      "front": "F7",
      "requirements": "R-01, R-02, R-09, R-17, R-27, R-28; Seções 4.4, 8.3 e 14.1/G-0A",
      "files": [
        "web/worker/pyodide_worker.ts:354-385",
        "web/worker/pyodide_worker.ts:574-591",
        "web/worker/pyodide_worker.ts:1007-1176"
      ],
      "affected_work_packages": [
        "WP-04-F7-RPC-BRIDGE-WORKER",
        "WP-06-F8-UI-MVP-LQR"
      ],
      "title": "LQR pré-computado é confirmado como cálculo SciPy sem runtime Python",
      "diagnosis": "O init sem loader passa a initialized=true; as capabilities anunciam numpy_scipy disponível/stable e offline_ready=true. executeFallbackDesignLqr seleciona valores pelo número de estados: para n=2 devolve K=[2,3], P=[[6,2],[2,3]], polos [-2,-1], custo 13, rCARE=0 e proveniência scipy.linalg.solve_continuous_are. Não calcula a partir de A/B/Q/R/x0/sinal. A reprodução externa enviou A=diag(1,2), B=0, Q=I, R=1, x0=[1,0], sinal positivo. Essa planta é não estabilizável: A+B K=A tem polos [1,2]. Mesmo assim recebeu success, hipóteses verdadeiras, sinal negativo e diagnostics.committed=true. Para outras ordens são produzidos polos artificiais sem P/K. Não é mera ausência de gate: é falsa resposta científica observada.",
      "corrective_action": "Eliminar o fallback científico de PyodideEngineClient/Worker. Sem runtime e entrypoint verificados, retornar SOLVER_UNAVAILABLE, não comitar e anunciar capacidade indisponível. Reservar fixtures exclusivamente ao MockWorkerAdapter explicitamente identificado como mock; não atribuir algoritmo/versões não executados.",
      "acceptance_criteria": "Adicionar teste de regressão F7 com a planta não estabilizável acima e com duas plantas/pesos distintos de mesma ordem. Sem Pyodide, ambos devem falhar sem ganho/polos inventados e sem commit; com engine real, T-CARE-03 deve rejeitar a planta. Executar npm --prefix web test e T-RPC-01; F9 deve executar também G-0A real.",
      "dependencies": []
    },
    {
      "id": "AUD-002",
      "severity": "CRÍTICO (Bloqueador de Gate)",
      "front": "F7",
      "requirements": "ADR-001; R-01, R-02, R-16; Seções 8.1, 13.9 e 14.1/G-0A/G-0C",
      "files": [
        "web/bridge/pyodide_client.ts:193-207",
        "web/app/main.ts:71-82",
        "web/worker/pyodide_worker.ts:556-579",
        "web/worker/pyodide_worker.ts:957-985",
        "PROJECT_STATE.json:171-172"
      ],
      "affected_work_packages": [
        "WP-04-F7-RPC-BRIDGE-WORKER",
        "WP-06-F8-UI-MVP-LQR"
      ],
      "title": "Caminho padrão não cria Worker científico real e entrypoint Python inexiste",
      "diagnosis": "mountControlLabApp cria PyodideEngineClient() sem workerUrl. spawnWorkerTransport só instancia new Worker quando workerUrl é fornecido; no caminho padrão usa MessageChannel e runtime na mesma thread. Não há importação/bootstrap de loadPyodide no bundle. Quando um runtime Python genuíno é fornecido, a execução depende de control_lab.web_rpc.dispatch, mas nenhum control_lab/web_rpc.py integra o ZIP. PROJECT_STATE reconhece essa ausência como follow-up do WP-04 aceito. MessageChannel não isola a execução científica síncrona em outra thread.",
      "corrective_action": "F7 deve fornecer URL/default de Worker real, bootstrap local do Pyodide e handshake que só finalize após importar e testar o dispatcher. F1 deve implementar o dispatcher em caminho de sua propriedade (por exemplo control_lab/core/rpc.py), ou F9 deve aprovar explicitamente ownership do entrypoint raiz antes da implementação; F7 atualiza o módulo consumido. Não há autorização implícita para F7 escrever no pacote científico de outra frente.",
      "acceptance_criteria": "Teste browser real deve demonstrar Worker separado, import do mesmo pacote científico de CPython, B-CARE-02 e B-CARE-12x3 recalculados, evento de UI atendido durante cálculo, cancelamento/reinício e erro tipado se dispatcher faltar. npm/pytest unitários são pré-requisitos, não substitutos do Job D.",
      "dependencies": [
        "AUD-001"
      ]
    },
    {
      "id": "AUD-003",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F9",
      "requirements": "R-02, R-22, R-23, R-24; Seções 11.2, 12.2, 15.1-15.3",
      "files": [
        "web/package.json:1-13",
        "web/tsconfig.json:1-28",
        "pyproject.toml:1-47",
        "CODEOWNERS:22-23",
        "web/app/index.html:18-19"
      ],
      "affected_work_packages": [
        "WP-00-F9-BOOTSTRAP",
        "WP-04-F7-RPC-BRIDGE-WORKER",
        "WP-06-F8-UI-MVP-LQR"
      ],
      "title": "Snapshot não contém pipeline reprodutível de build/distribuição e Jobs A-G",
      "diagnosis": "O pacote web só declara typecheck/test; tsconfig impõe noEmit e imports .ts. index.html solicita /app/main.js, inexistente na árvore. Não existem .github/workflows/, artefatos JS/Wasm/wheels, lockfiles congelados, release-manifest.json, SBOM ou docs/legal no ZIP. Há requisitos de versão abertos (>= no Python e ^ no TypeScript). A ausência de binários versionados não é isoladamente defeito; o problema é também não haver receita de build/provisionamento que gere os recursos e comprove a distribuição. Não há evidência dos Jobs A-G normativos. O snapshot não comprova configuração remota de branch protection, portanto isso permanece não verificável.",
      "corrective_action": "F9 deve adicionar build reproduzível e CI por escopo, congelar toolchain/dependências efetivamente distribuídas, construir wheel e JS com imports resolvidos, gerar manifesto de hashes/SBOM/licenças e provisionar assets locais. F8 fornece entry HTML/CSS válido e F7 fornece worker/bootstrap. Não exigir commit de binários se pipeline e artefato auditável os produzirem.",
      "acceptance_criteria": "De checkout limpo, um comando documentado deve gerar site estático completo; Job C deve compilar sem erros, Job B executar matemática, Job D abrir browser com Wasm, Job E persistência/integração e Jobs F/G segurança/hashes/offline. Registrar ambiente, SHA e resultados como artefatos.",
      "dependencies": [
        "AUD-014",
        "AUD-015"
      ]
    },
    {
      "id": "AUD-004",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F7",
      "requirements": "R-01, R-22; T-SEC-01; Seções 11.2 e 12.2",
      "files": [
        "web/worker/service_worker.ts:21-47",
        "web/worker/service_worker.ts:389-426",
        "web/app/index.html:7-19",
        "web/app/main.ts:71-82"
      ],
      "affected_work_packages": [
        "WP-04-F7-RPC-BRIDGE-WORKER"
      ],
      "title": "Manifesto offline não cobre o fechamento de dependências e SW não é registrado",
      "diagnosis": "O manifesto default lista 11 URLs, mas omite styles.css e módulos importados por main/client/worker (shell, tool_descriptor, protocol, pyodide_client, mock_adapter, features, charts, storage e pyproxy_guard, entre outros). Também não comprova a lista real dos arquivos transitivos do Pyodide. Não há chamada navigator.serviceWorker.register na árvore web. checkOfflineReadiness apenas percorre as URLs do manifesto; não testa completude transitiva nem que bytes cacheados sejam executáveis. O status offline_ready do Worker é constante, não depende desse provisionamento.",
      "corrective_action": "Gerar manifesto a partir do build e do inventário Pyodide efetivo; incluir CSS, módulos, biblioteca padrão/pacotes necessários e hashes. Registrar SW com escopo correto. Derivar offline_ready do provisionamento confirmado; manter atualização atômica e política de versões.",
      "acceptance_criteria": "T-SEC-01 em browser: instalar artefato real, calcular LQR, fechar/reabrir aba com rede bloqueada, editar A/Q e recalcular, conferir resultado e registrar todas as requisições. Apagar uma dependência transitiva deve tornar readiness falsa ou impedir capacidade offline; nenhuma resposta de placeholder pode contar como asset válido.",
      "dependencies": [
        "AUD-002",
        "AUD-003"
      ]
    },
    {
      "id": "AUD-005",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F1",
      "requirements": "R-03, R-19; T-CORE-01; Seções 4.1 e 8.2; Apêndice B",
      "files": [
        "control_lab/core/models.py:169-180",
        "control_lab/core/models.py:220-234",
        "control_lab/core/models.py:333-334",
        "control_lab/core/models.py:660-665",
        "control_lab/core/controllers.py:299-301",
        "control_lab/core/controllers.py:698-712",
        "control_lab/core/controllers.py:1062-1065"
      ],
      "affected_work_packages": [
        "WP-01-F1-CORE-MODELS",
        "WP-05-F1-IO-CTRLAB-PVM"
      ],
      "title": "Imutabilidade científica pode ser burlada por APIs públicas e colisão de revisão",
      "diagnosis": "Os getters devolvem o próprio ndarray interno, que possui memória própria. setflags(write=False) só bloqueia a escrita inicial: p.A.setflags(write=True); p.A[0,0]=NaN modifica o objeto validado, preservando id/revision. O mesmo foi reproduzido com ctrl.K, alterado para [999,3]. Além disso, p.with_revision(p.revision,A=nova_A) aceita conteúdo diferente com a mesma identidade/revisão; com revision=4, A=0 e A=100 coexistem sob a mesma chave. Revisões históricas deixam de identificar conteúdo científico. O teste atual só tenta atribuição direta e incremento padrão, sem esses casos. Result, em contraste, copia dados em leitura e não apresentou essa falha nos probes.",
      "corrective_action": "Não expor armazenamento interno mutável: retornar cópia defensiva ou view sobre backing imutável apropriado. Aplicar a todas as matrizes/polinômios/controladores/vértices, incluindo estruturas aninhadas. Rejeitar mesma revisão ou revisão menor quando houver alteração científica; operações que só acrescentem hash sem mudar conteúdo podem preservar revisão explicitamente.",
      "acceptance_criteria": "Ampliar pytest F1/T-CORE-01 com setflags(write=True), mutação de arrays retornados e evolução com revisão igual/menor para todos os tipos. O estado anterior, hash, id/revision e controladores dependentes devem continuar coerentes; NaN/Inf não pode ser introduzido após validação pela API pública.",
      "dependencies": []
    },
    {
      "id": "AUD-006",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F6",
      "requirements": "R-11, R-14; Seção 6.1",
      "files": [
        "control_lab/optimization/modeling/canonical.py:73-112",
        "control_lab/optimization/modeling/canonical.py:126-147",
        "control_lab/optimization/modeling/canonical.py:149-165",
        "control_lab/optimization/modeling/canonical.py:316-346"
      ],
      "affected_work_packages": [
        "WP-03-F6-SDP-MODELING-AND-GATE0B",
        "WP-10-F6-SDP-EDUCATIONAL-SOLVER"
      ],
      "title": "Problema SDP canônico também expõe armazenamento mutável",
      "diagnosis": "SDPBlock.F0/F_terms/get_Fk e CanonicalSDPProblem.c/E/d/H/h devolvem referências aos arrays internos. No probe, F0=I foi alterado com setflags para [[1,10],[0,1]]. evaluate passou a devolver [[1,5],[5,1]] pela simetrização, sem nova validação e sem invalidar is_diagonal já calculado. Solver e auditor podem observar dados diferentes do problema originalmente aprovado, e a seleção do fallback LP pode ficar obsoleta.",
      "corrective_action": "Congelar efetivamente dados/bases do problema e retornar cópias ou buffers imutáveis; impedir alteração posterior de atributos estruturais e de blocos compartilhados. Recalcular propriedades apenas a partir de modelo validado; não usar simetrização como reparo de mutação indevida.",
      "acceptance_criteria": "Adicionar pytest F6 com mutação dos getters, mapas e blocos após canonicalização. evaluate, assinatura do modelo e seleção de backend devem permanecer inalterados, ou uma alteração deve exigir novo CanonicalSDPProblem validado. Reexecutar bateria A-D.",
      "dependencies": []
    },
    {
      "id": "AUD-007",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F6",
      "requirements": "R-11, R-12, R-14; Seções 6.1 e 6.2",
      "files": [
        "control_lab/optimization/modeling/svec.py:68-76",
        "control_lab/optimization/modeling/canonical.py:90-112",
        "control_lab/optimization/backends/scipy_linprog.py:72-98"
      ],
      "affected_work_packages": [
        "WP-03-F6-SDP-MODELING-AND-GATE0B"
      ],
      "title": "Fallback LP classifica matrizes aproximadamente diagonais como redução exata",
      "diagnosis": "is_diagonal_matrix usa tolerância absoluta 1e-14; esse flag habilita o backend LP, que descarta todos os termos fora da diagonal. A norma admite LP somente por redução exata no sistema canônico. Probe: F(x)=[[x,1e-15],[1e-15,0]], min x. O determinante é -1e-30 para todo x, logo não há ponto PSD exato. O código classifica diagonal, resolve min x sujeito apenas a x>=0 e retorna x=0, solver_status=optimal, approximately_feasible, validated_dual e warning. O warning de condicionamento observado não torna a redução estrutural exata. Não se conclui que todo pequeno resíduo invalida uma solução numérica; o defeito é eliminar dados não nulos para decidir a classe do problema.",
      "corrective_action": "Separar teste de diagonalidade estrutural do diagnóstico de proximidade. Para fallback exato exigir zero fora da diagonal em F0 e todos Fk, ou transformação exata explicitamente certificada; aproximação opcional deve criar outro modelo com proveniência/erro, sem claim de redução exata.",
      "acceptance_criteria": "Adicionar pytest F6 com o bloco acima e variações de escala. ScipyLinprogBackend deve recusar com unsupported_psd qualquer off-diagonal não nulo, inclusive abaixo de 1e-14. Casos realmente diagonais seguem aprovados; comparar com backend SDP sem silenciar condicionamento.",
      "dependencies": [
        "AUD-006"
      ]
    },
    {
      "id": "AUD-008",
      "severity": "MÉDIO (Contrato/Invariante Incompleto)",
      "front": "F6",
      "requirements": "R-14; Seção 6.3 (resíduos normalizados)",
      "files": [
        "control_lab/optimization/verification/verifier.py:182-190"
      ],
      "affected_work_packages": [
        "WP-03-F6-SDP-MODELING-AND-GATE0B"
      ],
      "title": "Resíduo PSD relativo usa norma de Frobenius no lugar da norma 2 normativa",
      "diagnosis": "A norma fixa v_b/(1+||F0||_2+sum |xk| ||Fk||_2), mas _audit_primal_point soma normas Frobenius. Para F0=diag(100,100,-1), x=0 e F1=0, v=1: código relata 0,007021244586351119; expressão normativa dá 1/101=0,009900990099009901. Em blocos maiores isso reduz o valor reportado e altera o limiar efetivo por dimensão. CARE e Lyapunov usam corretamente Frobenius, pois suas fórmulas normativas são outras.",
      "corrective_action": "Usar norma espectral 2 na escala dos blocos PSD. Se um diagnóstico adicional em Frobenius for útil, nomeá-lo separadamente; não substituir a métrica normativa.",
      "acceptance_criteria": "Adicionar pytest com matriz diagonal de norma 2 diferente da Frobenius, validar valor exato 1/101 e casos multi-bloco com x não nulo. Revalidar classificações perto do limiar e registrar tolerâncias por fixture.",
      "dependencies": []
    },
    {
      "id": "AUD-009",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F5",
      "requirements": "R-10, R-21; T-FML-02; Seções 5.6 e 9.4",
      "files": [
        "control_lab/fuzzy/fml.py:82-116",
        "control_lab/fuzzy/fml.py:494-522",
        "control_lab/fuzzy/fml.py:703-711",
        "control_lab/fuzzy/fml.py:802-817"
      ],
      "affected_work_packages": [
        "WP-09-F5-FUZZY-FML-ANFIS"
      ],
      "title": "Importação FML reinterpreta silenciosamente operadores e parâmetros inválidos",
      "diagnosis": "_from_fml_and devolve min para qualquer token desconhecido; _from_fml_or devolve max. Parâmetros triangulares/trapezoidais são ordenados; sigma gaussiano passa por abs e, se zero, vira 1e-3; bell usa abs e pisos 1e-6. Probe de XML TS com andMethod=\"UNSUPPORTED\" e gaussianShape param2=\"0\" retorna success, warnings=[] e modelo com and=min e sigma=0,001. Assim um arquivo fora do perfil/semanticamente inválido ganha significado novo sem consentimento ou aviso. O bloqueio XXE/DTD foi inspecionado e seus testes passaram: este achado trata de fidelidade científica, não de execução de XML.",
      "corrective_action": "Rejeitar operador não suportado e parâmetros inválidos antes de construir FuzzySystem. Se houver modo de migração/reparo legado, torná-lo explícito e registrar cada mudança em warnings/provenance; padrão estrito não deve corrigir silenciosamente. Validar o perfil e rejeitar estruturas de regra que não possam ser representadas fielmente.",
      "acceptance_criteria": "Ampliar pytest F5/T-FML-02 com operador desconhecido, sigma zero/negativo, vértices fora de ordem e estrutura não suportada. Esperar failure com código tipado, ou warning apenas em modo de reparo autorizado. Manter equivalência numérica em grade para round-trip válido.",
      "dependencies": []
    },
    {
      "id": "AUD-010",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F9",
      "requirements": "R-17, R-22, R-23; T-SEC-01, T-RPC-02, T-UI-01; Seções 8.3, 10.1, 12.2 e 15.2",
      "files": [
        "tests/unit/f7/rpc_bridge_worker.test.ts:767-830",
        "tests/unit/f7/rpc_bridge_worker.test.ts:1149-1204",
        "tests/unit/f8/ui_mvp_lqr.test.ts:352-417",
        "PROJECT_STATE.json:164-172"
      ],
      "affected_work_packages": [
        "WP-04-F7-RPC-BRIDGE-WORKER",
        "WP-06-F8-UI-MVP-LQR"
      ],
      "title": "Testes intitulados paridade real/offline não exercitam os ambientes exigidos",
      "diagnosis": "T-SEC-01 usa InMemoryCacheStorage e um fetch que devolve comentário JS fictício para todo asset, inclusive Wasm/wheel; confirma cache HIT, sem importar/rodar cálculo em navegador. F7-PARITY-01 usa o PyodideEngineClient sem runtime Python, portanto compara o Mock com o fallback fixo de AUD-001. Os testes F8 usam ambiente DOM simulado; não comprovam mobile/teclado/navegador real ou FPS medido. Esses unitários são úteis para estado/contrato, mas suas descrições e associação aos gates superestimam o que provam. Não foi detectada troca de expected values em função sob teste: o falso positivo nasce da substituição do ambiente de execução.",
      "corrective_action": "F9 deve criar testes independentes em tests/wasm/, tests/e2e/ e tests/security/ usando artefato real e asserts científicos. As frentes F7/F8 mantêm seus unitários e ajustam os rótulos para o escopo efetivo; F9 não deve alterar tolerâncias desses testes para esconder defeitos. Paridade deve usar entradas variadas e evidência de que o Python foi invocado.",
      "acceptance_criteria": "Job D: B-CARE-12x3 em Chromium/Firefox; Job E: 20 revisões, hard terminate e recuperação de IndexedDB real; Job F: T-SEC-01 com rede bloqueada e novo cálculo. Teste deve falhar se dispatcher for removido ou se respostas forem fixas, mesmo mantendo schemas válidos.",
      "dependencies": [
        "AUD-001",
        "AUD-002",
        "AUD-003",
        "AUD-004"
      ]
    },
    {
      "id": "AUD-011",
      "severity": "CRÍTICO (Bloqueador de Gate)",
      "front": "F9",
      "requirements": "R-20; T-PVM-01, T-PVM-02; Seções 9.3 e 14.1/G-0D; Apêndice D",
      "files": [
        "control_lab/io/pvm.py:80-92",
        "control_lab/io/pvm.py:1254-1284",
        "tests/unit/f1/test_io_ctrlab_and_pvm.py:774-885",
        "tests/unit/f1/test_io_ctrlab_and_pvm.py:963-1065",
        "PROJECT_STATE.json:197-200"
      ],
      "affected_work_packages": [
        "WP-05-F1-IO-CTRLAB-PVM"
      ],
      "title": "T-PVM-01/02 não demonstram curvas no PathView oficial",
      "diagnosis": "O registro de blocos declara external_pathview_verified=False; a exportação retorna warning e metadata gate_pending=G-0D. Os testes verificam grafo/schema e simulação/extração por funções do próprio pacote, não a importação e geração de Python no aplicativo PathView oficial. São bons testes algébricos locais, porém não validam o registro real de blocos/portas/arrays/callbacks da versão-alvo. C!=I está tratado localmente com porta de x separada e controladores dinâmicos têm estados internos; não foi provado que o aplicativo externo os aceita. O estado PENDING de G-0D é correto; o bloqueio é de aceitação externa, sem acusação de gate falsamente aprovado.",
      "corrective_action": "F9 deve fixar versão/build do PathView-alvo e executar aceitação independente dos arquivos gerados por F1. Manter exportador explicitamente experimental/desativado como integração aprovada até a evidência. Corrigir eventuais incompatibilidades exclusivamente via F1; oferecer fallback PathSim com aviso se necessário.",
      "acceptance_criteria": "Abrir .pvm no PathView oficial, comprovar importação, diagrama, geração de Python e simulação; comparar x/u/y e estados internos para C=I, C!=I, m!=p, ambos sinais e controlador dinâmico com Dp/Dc não nulos. Repetir saturação com referência não linear equivalente. Anexar versão, arquivos, curvas, tolerâncias, SHA e parecer F9.",
      "dependencies": [
        "AUD-002",
        "AUD-003",
        "AUD-010"
      ]
    },
    {
      "id": "AUD-012",
      "severity": "MÉDIO (Contrato/Invariante Incompleto)",
      "front": "F9",
      "requirements": "R-23, R-24; Seções 13.2, 13.11, 15.1; Apêndice E",
      "files": [
        "CODEOWNERS:1-23",
        "CODEOWNERS:17-18",
        "AGENTS.md:9-17",
        "PROJECT_STATE.json:49-61"
      ],
      "affected_work_packages": [
        "WP-00-F9-BOOTSTRAP"
      ],
      "title": "CODEOWNERS não implementa ownership completo nem exclusividade das fixtures F9",
      "diagnosis": "Nenhuma regra cobre tests/unit/f1..f8, scripts/, tests/metamorphic/, tests/performance/, testes de integração ou configurações compartilhadas web. A regra /contracts/ lista F9 e F1 e não há override para /contracts/fixtures/: não expressa a exclusividade de F9 exigida para valores ouro. A árvore dos módulos de produção está alinhada ao mapa F1-F8; o ZIP sem histórico Git/PRs não permite atribuir autoria real ou provar alteração cruzada. Também não permite confirmar se @f1-... são identidades elegíveis nem se revisão F9 é obrigatória no servidor.",
      "corrective_action": "F9 deve completar as regras unitárias/compartilhadas e criar override exclusivo de fixtures; proteger aprovação de contratos/valores ouro pela revisão F9 e por CI de caminhos/hashes. Confirmar identidades e regras de branch no GitHub antes de alegar enforcement. CODEOWNERS sozinho não impede escrita nem substitui branch protection.",
      "acceptance_criteria": "Teste de governança deve resolver cada caminho e comparar com mapa normativo; alterações em contracts/fixtures por produtor devem exigir revisão F9 e nunca passar só pela aprovação do autor produtor. Auditar amostra de PRs/commits com evidência de autoria e revisão independente.",
      "dependencies": []
    },
    {
      "id": "AUD-013",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F9",
      "requirements": "R-23, R-24; Seções 10.5, 13.11, 14.1, 15.3; Apêndice E",
      "files": [
        "PROJECT_STATE.json:49-62",
        "PROJECT_STATE.json:80-85",
        "PROJECT_STATE.json:164-172",
        "PROJECT_STATE.json:218-227",
        "web/worker/pyodide_worker.ts:367-386"
      ],
      "affected_work_packages": [
        "WP-00-F9-BOOTSTRAP",
        "WP-01-F1-CORE-MODELS",
        "WP-03-F6-SDP-MODELING-AND-GATE0B",
        "WP-04-F7-RPC-BRIDGE-WORKER",
        "WP-05-F1-IO-CTRLAB-PVM",
        "WP-06-F8-UI-MVP-LQR",
        "WP-09-F5-FUZZY-FML-ANFIS",
        "WP-10-F6-SDP-EDUCATIONAL-SOLVER"
      ],
      "title": "Aceites F9 e rótulos stable não possuem pacote de evidências suficiente no snapshot",
      "diagnosis": "Os 11 WPs têm ACCEPTED_BY_F9 e f9_review=\"accepted\", mas o snapshot não inclui handoffs por WP, commit/PR de revisão, checklist de 10 itens, logs de paridade Wasm, benchmarks cold/warm, release-manifest ou matriz de evidências independente. O campo textual accepted não comprova independência. Gates permanecem PENDING e isso é correto; entretanto operações anunciam stable e disponibilidade mesmo sem runtime. A conclusão não é que nenhuma revisão ocorreu: é que sua execução e seu escopo não são auditáveis com os artefatos entregues. Pendências conhecidas do dispatcher/PathView não têm WPs de remediação executáveis.",
      "corrective_action": "F9 deve registrar para cada WP escopo local vs integrado, evidências/ambiente/SHA, parecer e bloqueadores. Aceites dos WPs com defeitos reproduzidos devem ser reabertos; WPs científicos aprovados localmente podem conservar seu histórico, mas sem equivaler a produção stable. Criar WPs de integração/gates e issues dos achados, com dependências e critérios verificáveis.",
      "acceptance_criteria": "Cada accepted deve apontar para artefatos reprodutíveis, não apenas string; todos os itens do Apêndice E devem ter resposta com evidência ou limitação. CI valida requisitos/testes/gates e impede stable no alvo sem prova Wasm. Gates só mudam após relatório pass revisado; esta auditoria não altera PROJECT_STATE.json.",
      "dependencies": []
    },
    {
      "id": "AUD-014",
      "severity": "ALTO (Violação Matemática/Segurança)",
      "front": "F8",
      "requirements": "R-16, R-17, R-18, R-24; Seções 7.1, 13.10 e 15.2/Job C",
      "files": [
        "tests/unit/f8/ui_mvp_lqr.test.ts:171-176",
        "web/app/main.ts:745-749",
        "web/app/shell.ts:11-15",
        "web/app/tool_descriptor.ts:280-295",
        "web/bridge/client.ts:128-155"
      ],
      "affected_work_packages": [
        "WP-06-F8-UI-MVP-LQR"
      ],
      "title": "TypeScript não compila: contratos F7/F8 e narrowing incoerentes",
      "diagnosis": "Com TypeScript 5.9.3, permitido por ^5.8.0, npm --prefix web test falha antes dos unitários com cinco erros: TS2353 simulatedLatencyMs não existe em MockWorkerAdapterOptions; TS2339 getCommittedRevision não está na interface ControlLabEngineClient; TS2459 ExecutionMetrics é importado de client.ts sem export; dois TS2367 comparam union já estreitada com unavailable_wasm. Sem tsc, Node remove tipos e os 36 unitários passam. Portanto o comando de aceite de WP-06 não é verde quando o typecheck é efetivamente instalado. Métodos existentes na classe concreta não suprem ausência na interface.",
      "corrective_action": "F8 deve corrigir os usos de seu código/teste e o fluxo de narrowing; usar nome de opção correto e importar tipo da origem pública apropriada. Se getCommittedRevision precisa fazer parte do contrato público, F7 deve acrescentá-lo na interface e testar consumidores, em alteração própria. Rever available para operação ausente do catálogo: a condição atual dependia de comparação inalcançável.",
      "acceptance_criteria": "Instalação limpa das dependências declaradas seguida de npm --prefix web run typecheck e npm --prefix web test deve concluir sem os cinco erros. Adicionar teste para operação não anunciada por capabilities; não silenciar com any, @ts-ignore ou afrouxamento de strict.",
      "dependencies": [
        "AUD-015"
      ]
    },
    {
      "id": "AUD-015",
      "severity": "MÉDIO (Contrato/Invariante Incompleto)",
      "front": "F9",
      "requirements": "R-24; Seções 10.5, 15.2/Job C e 15.3",
      "files": [
        "scripts/run_web_tests.mjs:73-98",
        "scripts/run_web_tests.mjs:103-108",
        "web/package.json:6-12"
      ],
      "affected_work_packages": [
        "WP-00-F9-BOOTSTRAP",
        "WP-04-F7-RPC-BRIDGE-WORKER",
        "WP-06-F8-UI-MVP-LQR"
      ],
      "title": "Runner permite aceite verde sem compilador TypeScript",
      "diagnosis": "Se tsc não é encontrado, o runner só avisa e continua com node --test. Isso ocorreu na primeira execução: 36 passed, zero skipped reportados pelo Node, apesar de o typecheck inteiro ter sido pulado. Depois de instalar TypeScript, a mesma base falhou com os erros de AUD-014. O número skipped=0 não cobre esse estágio omitido. O runner também sai com sucesso se não achar arquivos de teste, sem distinguir escopo vazio de configuração quebrada.",
      "corrective_action": "F9 deve fazer o comando de aceite/CI falhar se compilador ou suíte obrigatória estiver ausente; se houver modo rápido deliberado, usar outro comando com nome e relatório explícitos, que não conte como aceite. Instalar dependências de desenvolvimento antes da execução e fixar toolchain.",
      "acceptance_criteria": "Teste do runner sob PATH sem tsc deve retornar código não zero para escopo TS ativo; diretórios de testes obrigatórios vazios também devem falhar. Com dependências presentes, executar typecheck e os 36 testes. Registrar separadamente resultado de compilação e unitários.",
      "dependencies": []
    }
  ],
  "normative_coverage": [
    {
      "test_id": "T-CORE-01",
      "status": "PARCIAL",
      "location": "tests/unit/f1/test_core_models_and_interconnect.py:293"
    },
    {
      "test_id": "T-CORE-02",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_core_models_and_interconnect.py:352"
    },
    {
      "test_id": "T-CORE-03",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_core_models_and_interconnect.py:429"
    },
    {
      "test_id": "T-TS-01",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_core_models_and_interconnect.py:581; tests/unit/f1/test_core_models_and_interconnect.py:1038; tests/unit/f5/test_f5_fuzzy_ts.py:670"
    },
    {
      "test_id": "T-CARE-01",
      "status": "CONFORME",
      "location": "tests/unit/f2/test_care_lqr.py:102"
    },
    {
      "test_id": "T-CARE-02",
      "status": "PARCIAL",
      "location": "tests/unit/f2/test_care_lqr.py:173; tests/oracles/test_golden_fixtures.py:430"
    },
    {
      "test_id": "T-CARE-03",
      "status": "CONFORME",
      "location": "tests/unit/f2/test_care_lqr.py:237"
    },
    {
      "test_id": "T-CARE-04",
      "status": "CONFORME",
      "location": "tests/unit/f2/test_care_lqr.py:331"
    },
    {
      "test_id": "T-FREQ-01",
      "status": "CONFORME",
      "location": "tests/unit/f3/test_frequency_siso_and_mimo.py:56"
    },
    {
      "test_id": "T-FREQ-02",
      "status": "CONFORME",
      "location": "tests/unit/f3/test_frequency_siso_and_mimo.py:158"
    },
    {
      "test_id": "T-MIMO-01",
      "status": "CONFORME",
      "location": "tests/unit/f3/test_frequency_siso_and_mimo.py:308; tests/unit/f3/test_frequency_siso_and_mimo.py:421"
    },
    {
      "test_id": "T-MIMO-02",
      "status": "CONFORME",
      "location": "tests/unit/f3/test_frequency_siso_and_mimo.py:369"
    },
    {
      "test_id": "T-ID-01",
      "status": "CONFORME",
      "location": "tests/unit/f4/test_identification.py:96"
    },
    {
      "test_id": "T-ID-02",
      "status": "CONFORME",
      "location": "tests/unit/f4/test_identification.py:138"
    },
    {
      "test_id": "T-ID-03",
      "status": "CONFORME",
      "location": "tests/unit/f4/test_identification.py:193"
    },
    {
      "test_id": "T-FML-01",
      "status": "CONFORME",
      "location": "tests/unit/f5/test_f5_fuzzy_ts.py:134"
    },
    {
      "test_id": "T-FML-02",
      "status": "PARCIAL",
      "location": "tests/unit/f5/test_f5_fuzzy_ts.py:314; tests/unit/f5/test_f5_fuzzy_ts.py:419"
    },
    {
      "test_id": "T-SDP-A1",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:229; tests/unit/f6/test_educational_solver_levels_a_to_d.py:108"
    },
    {
      "test_id": "T-SDP-A2",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:254; tests/unit/f6/test_sdp_modeling_and_verification.py:272; tests/unit/f6/test_sdp_modeling_and_verification.py:641"
    },
    {
      "test_id": "T-SDP-A3",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:285"
    },
    {
      "test_id": "T-SDP-B1",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:320"
    },
    {
      "test_id": "T-SDP-C1",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:360; tests/unit/f6/test_educational_solver_levels_a_to_d.py:271"
    },
    {
      "test_id": "T-SDP-D1",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:395; tests/unit/f6/test_educational_solver_levels_a_to_d.py:349"
    },
    {
      "test_id": "T-SDP-D2",
      "status": "CONFORME",
      "location": "tests/unit/f6/test_sdp_modeling_and_verification.py:440; tests/unit/f6/test_sdp_modeling_and_verification.py:859; tests/unit/f6/test_educational_solver_levels_a_to_d.py:384"
    },
    {
      "test_id": "T-RPC-01",
      "status": "CONFORME",
      "location": "tests/unit/f7/rpc_bridge_worker.test.ts:272"
    },
    {
      "test_id": "T-RPC-02",
      "status": "PARCIAL",
      "location": "tests/unit/f7/rpc_bridge_worker.test.ts:531"
    },
    {
      "test_id": "T-IO-01",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_io_ctrlab_and_pvm.py:456; tests/unit/f1/test_io_ctrlab_and_pvm.py:481; tests/unit/f1/test_io_ctrlab_and_pvm.py:525; tests/unit/f1/test_io_ctrlab_and_pvm.py:584"
    },
    {
      "test_id": "T-IO-02",
      "status": "CONFORME",
      "location": "tests/unit/f1/test_io_ctrlab_and_pvm.py:673"
    },
    {
      "test_id": "T-PVM-01",
      "status": "PARCIAL",
      "location": "tests/unit/f1/test_io_ctrlab_and_pvm.py:774; tests/unit/f1/test_io_ctrlab_and_pvm.py:886"
    },
    {
      "test_id": "T-PVM-02",
      "status": "PARCIAL",
      "location": "tests/unit/f1/test_io_ctrlab_and_pvm.py:963; tests/unit/f1/test_io_ctrlab_and_pvm.py:1067"
    },
    {
      "test_id": "T-UI-01",
      "status": "PARCIAL",
      "location": "tests/unit/f8/ui_mvp_lqr.test.ts:183; tests/unit/f8/ui_mvp_lqr.test.ts:352"
    },
    {
      "test_id": "T-SEC-01",
      "status": "FALSO POSITIVO",
      "location": "tests/unit/f7/rpc_bridge_worker.test.ts:767"
    }
  ],
  "remediation_order": [
    "REM-01",
    "REM-02",
    "REM-03",
    "REM-04",
    "REM-05",
    "REM-06",
    "REM-07",
    "REM-08",
    "REM-09",
    "REM-10",
    "REM-11",
    "REM-12",
    "REM-13",
    "REM-14",
    "REM-15"
  ],
  "do_not_auto_approve_gates": true
}
```

### 4.4. Registro final de evidência e integridade

O veredito combina inspeção estática, 146 testes Python executados, 36 testes Node executados antes de typecheck, compilação real com cinco erros e probes adversariais independentes descritos em AUD-001/005/006/007/008/009. Não se utiliza nenhuma fonte normativa além do documento CL-DIR-001 da raiz; README, AGENTS, estado e comentários do código foram tratados como declarações a auditar, não como autorização para reduzir critérios.

A comparação final byte a byte dos 153 arquivos com as entradas do ZIP confirmou que a árvore auditada permaneceu intacta. O relatório não modificou PROJECT_STATE, fixtures, tolerâncias, testes, contratos, código ou histórico Git. As recomendações são externas, para avaliação e implementação pelo Maestro e pelas frentes responsáveis.
