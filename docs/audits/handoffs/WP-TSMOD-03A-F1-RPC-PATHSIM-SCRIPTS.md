# WP-TSMOD-03A-F1-RPC-PATHSIM-SCRIPTS — Auditoria independente F9

- Parecer F9: accepted
- Revisor independente: `f9-integration-qa`
- Commit base auditado: `aca3d6f78c884e34dabd6addc1d6c936b6d59c2c`
- Data UTC: 25/11/2026
- Fonte normativa: CL-DIR-001, CL-TS-MOD-DIR-001 v1.1.0 e ADR-013.
- Escopo: R-04, R-18, R-21 e R-27. Parcela de T-TSMOD-07 relativa a RPC, round-trip e PathSim, além do transporte e da avaliação simplicial de T-TSMOD-08. A ponte TypeScript/Worker, a interface e a auditoria integrada de síntese pertencem a `WP-TSMOD-03B`, `WP-TSMOD-04` e `WP-TSMOD-05`.

## Evidências independentes

Dados reproduzíveis dos ensaios em CPython, usando ambos os estados no domínio `[-1,1]` e saída `C=[1,0]`, `D=0`:

- Setor. Definir `z1=sinc_rad(x1)` e `z2=x1*x2` e usar `A=[[-1.4,.2*z1],[.25*z2,-1.1]]`, `B=[[1+.25*z2],[.15]]`. As faixas analíticas são `[sin(1),1]` e `[-1,1]`. Os pesos esperados são produtos das pertinências afins, com o bit zero no extremo superior.
- TPMT e FEMT. Usar `A=[[-1.4+.2*x1*x2,.1],[.2*sin(x1+x2),-1.1]]`, `B=[[1+.25*x2],[.15]]`, grade `[5,6]`, SN–NN e 64 pontos de validação. Na TPMT, calcular a interpolação linear a partir dos dois nós vizinhos em cada eixo e tomar os produtos em ordem lexicográfica. Na FEMT, localizar o ponto por enumeração dos triângulos e resolver o sistema baricêntrico com coordenada afim acrescida. A malha Kuhn usa a diagonal do canto inferior esquerdo ao superior direito em cada célula. A malha Delaunay usa os triângulos serializados.
- Comparar pesos nos pontos `(0,0),(.31,-.27),(.13,.13),(.73,.55),(-1.2,1.4),(1.15,-1.27)`. Para o setor, os dois pontos exteriores usados devem ser rejeitados. Para TPMT e FEMT, o oráculo aplica saturação de cada eixo. Nas quatro representações, `min(h) >= -1e-14` e `max(abs(sum(h)-1)) <= 1e-13` nos pontos aceitos.
- Usar `K_j=[.13+.09*j,.28-.04*j]` para a regra de índice zero-base `j`, realimentação negativa, `u_ff=.07*cos(t)`, `x(0)=[.72,-.41]`, duração 1,1 s e passo de 0,01 s. Oráculo de dinâmica: `A(h)@x + B(h)@(u_ff-K(h)@x)`, integrado com SciPy DOP853 (`rtol=1e-10`, `atol=1e-12`). O código emitido foi executado explicitamente em PathSim 0.31.0, em malha fechada e com o avaliador padrão gerado para cada modelo.

| Caso | Regras | Erro máximo nos pesos | Erro máximo na trajetória |
|---|---:|---:|---:|
| Setor com singularidade removível | 4 | `5.551e-17` | `3.787e-11` |
| TPMT 2D | 16 | `1.110e-16` | `1.785e-7` |
| FEMT Kuhn–Freudenthal | 4 | `4.441e-16` | `1.936e-8` |
| FEMT Delaunay explícita | 4 | `5.551e-16` | `5.595e-8` |

O maior erro de trajetória ficou abaixo do critério `1e-4` do ADR-013 em todos os casos. Em ensaio adicional com `z2=ext*x2`, `ext(t)=.55*cos(t)`, `u_ff=.17`, `x(0)=[.47,-.6]` e duração de 0,5 s em malha aberta, o erro em relação à ODE analítica foi `9.723e-11`. A ausência do sinal externo gerou erro explícito com identificação da premissa. O despacho do setor rejeitou expressão com acesso a atributo como `VALIDATION_ERROR`.

Nos quatro casos principais, a F9 validou os envelopes RPC e todos os modelos TS com os schemas Draft 2020-12, verificou ZIP determinístico e comparou o modelo completo antes e após a restauração do `.ctrlab`, incluindo `membership_spec` e `provenance.ts_derivation`. Confirmou também `code_executed=false` e execução manual explícita nos exportadores.

Foram executados, em processos isolados sem o pacote ControlLab no caminho de importação, **sete scripts Python** que recalculam e salvam `A,B,C,D`. Além dos quatro casos principais, a F9 incluiu TPMT HOOI com reamostragem PCHIP, fecho CNO e canais generalizados, FEMT Delaunay 1D e setor com premissa externa. A saída `.npz` foi comparada às matrizes dos modelos. Maior diferença absoluta `3.737e-13`. O replay fixa as escolhas da derivação exportada, incluindo os operadores de projeção das bases TPMT/FEMT.

Para MATLAB, a F9 verificou estruturalmente a função da planta e a gravação `.mat`, leu os operadores e a indexação da fonte emitida e confrontou a ordenação dos cantos setoriais e o cálculo de `A` em memória column-major em TPMT e nas duas malhas FEMT. Maior diferença absoluta `3.997e-15`. O runtime MATLAB/Octave estava indisponível para executar o `.m`.

Em **Firefox 153.0 com Pyodide 0.27.5 real**, o teste independente executou a fronteira Python desta entrega com os módulos do candidato, ativos locais e NumPy/SciPy. Passaram derivação por RPC, round-trip, geração passiva de PathSim e de ambas as linguagens e execução explícita do replay Python com confronto dos quatro blocos para setor, TPMT, FEMT Kuhn e FEMT Delaunay. A execução do PathSim ocorreu em CPython, conforme ADR-013.

## Checklist do Apêndice E

| Item | Evidência | Resultado |
|---|---|---|
| 1 | Cinco operações canônicas registradas com contratos para o consumidor F7. Requisições e respostas exercitadas com validação dos schemas, inclusive exportações por modelo e por referência na suíte F1. | CONFORME |
| 2 | Envelopes com status, diagnósticos, proveniência e erro tipado. Quatro modos de derivação, falhas de linguagem, referência e expressão inválida cobertos. | CONFORME |
| 3 | A evidência usa oráculos analíticos de setor, interpolação e dinâmica e mede a exatidão antes de considerar desempenho. | CONFORME |
| 4 | Pesos contra fórmulas independentes e trajetórias PathSim contra SciPy DOP853. Replay Python isolado e ordem MATLAB verificada separadamente. | CONFORME |
| 5 | Implementação e testes exclusivamente em `control_lab/core/`, `control_lab/io/` e `tests/unit/f1/`. `git diff --check` aprovado. Sete hashes de fixtures ouro confirmados por `scripts/verify_fixtures.py`. Nenhuma alteração em exemplos, oráculos ou tolerâncias. | CONFORME |
| 6 | Mesma fronteira científica e de I/O comprovada em CPython e no Pyodide real em Firefox. PathSim é o executor externo CPython. Integração do Worker e da UI segue nos pacotes declarados na fila. | CONFORME |
| 7 | Sem alteração de schema ou migração. As três representações canônicas e a proveniência da derivação sobreviveram ao ZIP e à restauração. | CONFORME |
| 8 | Entradas de oráculo, versões, erros medidos, regressões e hashes dos arquivos F1 registrados neste handoff. | CONFORME |
| 9 | A entrega acrescenta o contrato e a exportação das três vias descritas no Documento Diretor. | N/A |
| 10 | Sinais externos precisam ser fornecidos explicitamente como valores constantes ou funções de tempo. Validação MATLAB estrutural e de ordenação nesta sessão. T-TSMOD-07 integral é acompanhado por `WP-TSMOD-05`. | CONFORME |

## Regressão e integridade do candidato

O aceite F1 foi executado a partir do comando definido em `PROJECT_STATE.json` e com os equivalentes locais de `pytest` e CPython. A suíte com PathSim 0.31.0 e PathView 0.21.0 instalados obteve **174 aprovados**, sem falhas ou pulos. As verificações complementares obtiveram 682 aprovados no perfil Python core, 457 no perfil SDP e 159 na suíte web. As suítes Python de CI usaram OpenBLAS com perfil de CPU explícito. Um resultado limítrofe já existente no baseline para TPMT/CNO reproduziu o mesmo peso `-1.539218135660863e-12` em runtime com seleção padrão de núcleo BLAS, ante a asserção `-1e-12`. Em perfil isolado com `OPENBLAS_CORETYPE=Haswell` e `OPENBLAS_NUM_THREADS=1`, o teste passou com a tolerância original. O código F5 e o teste já existente permaneceram sem alterações.

Hashes SHA-256 dos arquivos F1 na versão auditada:

```text
a1d956bd2ca1352d3d394ef0392a5eb9577761e881a212f02a3b680ddd885130  control_lab/core/rpc.py
484a05e2f42f5bd7bdfe0a63a7b8dd6b71cc6f3911b23bbfdbef7aeea57ef5d8  control_lab/io/pvm.py
058076516a1e41a681af39ff0dc41d5059643162a05fede1cb8f8e88e62c2639  control_lab/io/ts_derivation.py
d0a9a00755eb85c80b97915f773002013ba97b2727e5058861abf91c121cca43  tests/unit/f1/test_ts_derivation_rpc.py
803a06bb2c39b91c7d77db5c619db0cef6e73e8476ddb2616e1af36658586537  tests/unit/f1/test_ts_derivation_scripts.py
```
