# Relatório técnico — Engenharia reversa do Laboratório de Controle Fuzzy

**Escopo:** migração do projeto Unity 2D `labFuzzy` para HTML5 Canvas 2D + JavaScript nativo.

**Arquivos de origem examinados:** `Assets.zip` (scripts C#, cena `SampleScene.unity`, prefabs, metadados e sprites) e `labFuzzy_webgl.zip` (build WebGL compilado).

## 1. Resultado executivo

A planta do laboratório é um **robô móvel cinemático do tipo uniciclo**. Apesar dos nomes `CarController` e `robo1`, não há equações de força, massa, inércia, atrito, escorregamento ou dinâmica de motor. O vetor de estado tem três componentes, e as entradas são as velocidades linear e angular.

O controlador programado em `FuzzySets.cs` é um sistema **Mamdani com duas entradas e duas saídas**, mas a cena anexada não contém uma configuração fuzzy pronta: os arrays estáticos de pertinência começam sem parâmetros e `ruleBase` começa `null`. O comportamento inicial do C# é, portanto, controle manual por eixos do Unity. A aplicação web inclui um preset didático inicial de 25 regras para que a bancada seja imediatamente experimentável; ele é novo e está identificado como tal na interface. O botão **“Modo original Unity (sem regras)”** remove as pertinências e as regras, reproduzindo a condição de configuração vazia.

A versão web mantém o modelo cinemático, os universos e os operadores Mamdani, mas corrige erros concretos de fuzzificação, defuzzificação, persistência e interface. Também usa RK4 explícito, como solicitado, em lugar do método trapezoidal configurado no Unity.

## 2. Inventário dos arquivos

### 2.1 Scripts C#

| Arquivo | Papel identificado |
|---|---|
| `CarController.cs` | Estado do robô, cálculo dos erros, lei de controle e chamada do integrador |
| `RefController.cs` | Referência manual, circular e retangular |
| `FuzzySets.cs` | Funções de pertinência, operadores fuzzy, inferência, modus ponens, defuzzificação e persistência da configuração em memória |
| `PertController.cs` | Edição das pertinências, criação dos painéis de parâmetros e atualização dos gráficos |
| `FileHandler.cs` | Serialização textual e recuperação da configuração do controlador |
| `TabController.cs` | Alternância dos painéis de interface |
| `UIGridRenderer.cs` | Desenho de grades de visualização na UI do Unity |
| `UILinePlotRenderer.cs` | Renderização de séries temporais na UI do Unity |
| `Libraries/ODE.cs` | Métodos de integração explícitos/implícitos e solucionadores Newton/Broyden |
| `Libraries/Interpolation.cs` | Coleção genérica de interpoladores unidimensionais; não participa do caminho principal da planta/controlador desta cena |

As DLLs de Math.NET Numerics são dependências da biblioteca numérica C#; não são necessárias na implementação JavaScript.

### 2.2 Cena e prefabs

A cena principal é `Assets/Scenes/SampleScene.unity`. Os três prefabs diretamente relevantes à parametrização são `ParInputTri.prefab`, `ParInputTrap.prefab` e `ParInputGauss.prefab`. Os prefabs de ambiente são `cubo_cima.prefab` e `cubo_lado.prefab`.

A pasta real dos sprites chama-se `Assets/PixeArt/`, e não `desenhos/`. A versão web copia os cinco PNGs originais para sua pasta `desenhos/`:

| PNG | Dimensão | Uso observado |
|---|---:|---|
| `robo1.png` | 30 × 30 px | Robô controlado |
| `robo2.png` | 30 × 30 px | Referência |
| `cubo_cima.png` | 21 × 21 px | Tiles horizontais das paredes |
| `cubo_lado.png` | 21 × 21 px | Tiles laterais |
| `torre.png` | 48 × 48 px | Recurso gráfico disponível; não aparece como SpriteRenderer na composição principal analisada |

Os metadados dos sprites indicam `Pixels Per Unit = 100` e pivô central `(0.5, 0.5)`. Logo, uma imagem de robô com 30 px, transformada por escala `(3,3,1)`, ocupa aproximadamente `0,9 × 0,9` unidade de mundo. Os tiles de 21 px com escala 3 ocupam aproximadamente `0,63 × 0,63` unidade.

### 2.3 Build original

O segundo ZIP é uma build Unity WebGL convencional: página HTML de bootstrap, CSS, loader/framework JavaScript, arquivo `.data` e módulo `.wasm`. O build inclui aproximadamente 11,3 MB de `.data` e 20,0 MB de `.wasm`, além do loader/framework. Os binários compilados são úteis para confirmar o empacotamento e a apresentação geral, mas não substituem os scripts C# e a cena como fonte de verdade para equações e hierarquias. A nova aplicação não carrega Unity nem os binários WebGL.

## 3. Planta física e sinais

### 3.1 Estados e entradas

O estado implementado em `CarController.F` é

\[
\mathbf{x}=\begin{bmatrix}x&y&\theta\end{bmatrix}^{T},
\qquad
\mathbf{u}=\begin{bmatrix}v&\omega\end{bmatrix}^{T}.
\]

As equações são

\[
\boxed{\dot x=v\cos\theta,\qquad
       \dot y=v\sin\theta,\qquad
       \dot\theta=\omega.}
\]

Não existe estado de velocidade, corrente, posição de motor ou dinâmica mecânica adicional. Os comandos são saturados a `[-5,5]` na versão web, coerentemente com os universos de saída originais.

### 3.2 Erros usados pelo fuzzy

Se a referência estiver em \((x_r,y_r)\), então

\[
\begin{aligned}
\Delta x &= x_r-x,\qquad \Delta y=y_r-y,\\
e_1 &= \operatorname{wrap}_{[-\pi,\pi]}
       \left(\operatorname{atan2}(\Delta y,\Delta x)-\theta\right),\\
e_2 &= \sqrt{(\Delta x)^2+(\Delta y)^2}.
\end{aligned}
\]

`EA` é o erro angular e `EP` é a distância euclidiana. O segundo sinal é não negativo. No C# o universo inicial de EP é `[-5,5]`, embora a variável seja uma distância; a configuração didática web usa `[0,5]` por coerência física, mantendo o intervalo C# editável.

### 3.3 Parâmetros iniciais e integração original

| Item | Valor recuperado |
|---|---:|
| Estado numérico inicial do robô | `(0, 0, 0)` |
| Posição inicial da referência | `(2.62, -0.02)` |
| Orientação visual inicial dos sprites | `−90°` |
| Passo fixo do Unity | `1/60 s` |
| `CarController.ode_op` | `6` |
| Método efetivamente selecionado | Trapezoidal multi-passo |
| Faixa das saídas fuzzy | `[-5,5]` para VA e VEL |

O estado inicial do modelo é `θ=0`, embora a arte dos dois robôs esteja inicialmente rotacionada em `−90°`. Isso é compensação da orientação-base do desenho, não um estado físico diferente. No Canvas a rotação do modelo é separada da rotação-base do sprite: o PNG é desenhado com `θ − π/2`.

### 3.4 Referências

`RefController.cs` possui três modos:

- **Manual:** velocidade e velocidade angular são associadas aos eixos de entrada do Unity. Na versão web, o alvo manual pode ser movido clicando/arrastando no Canvas e também pelos campos numéricos.
- **Circular:** ponto desejado `x_d = 1.25 + 3.25 cos(t)`, `y_d = 0.25 + 3.25 sin(t)`; o objeto de referência segue esse ponto com ganho proporcional `kp=2`.
- **Retangular:** trajetória desejada com período de 8 s, vértices `(-2,-3)`, `(4.5,-3)`, `(4.5,3.5)` e `(-2,3.5)`, percorrida com velocidade nominal 3,25 unidades/s; o seguimento usa `kp=6`.

A referência automática não teletransporta o sprite ao ponto desejado: o C# define sua velocidade por `kp × erro` e deixa o Rigidbody2D evoluir. A versão web integra a mesma dinâmica de primeira ordem junto com a planta pelo RK4.

## 4. Cena 2D e hierarquia visual

### 4.1 Câmera

A câmera principal está em `(0,0,-10)`, é ortográfica e usa tamanho vertical 5. Portanto, a altura lógica visível é 10 unidades de mundo, enquanto a largura depende da razão de aspecto. A versão web preserva a altura de 10 unidades e calcula a largura a partir do tamanho real do Canvas.

### 4.2 Robôs

| GameObject | Sprite | Posição de cena | Escala local | Rotação inicial |
|---|---|---:|---:|---:|
| `robo1` | `robo1.png` | `(0,0,0)` | `(3,3,1)` | `−90°` |
| `robo2` | `robo2.png` | `(2.62,−0.02,0)` | `(3,3,1)` | `−90°` |

Ambos os SpriteRenderers estão na sorting layer de índice 1, ordem 0. O `CarController` altera a posição do primeiro objeto a partir do estado numérico e corrige a rotação incrementalmente. O `RefController` atua sobre o segundo objeto por meio do Rigidbody2D. A ordem visual web desenha o fundo, paredes, referência e robô controlado, de modo que o robô controlado aparece à frente do alvo.

### 4.3 Paredes e tiles

A parede superior possui raiz aproximadamente em `(-0.011, 2.14, 0)` e uma sequência de tiles filhos `cubo_cima`; a composição visível fica por volta de `y=4.42`. A parede inferior tem raiz em `(0,-6,0)` e tiles ao redor de `y=-3.72`. As laterais são montadas com `cubo_lado`, aproximadamente em `x=-2.65` e `x=5.31`, com centros distribuídos verticalmente. As duas raízes de parede possuem `Rigidbody2D` com `m_BodyType=2` (Static) e `BoxCollider2D`; as peças visuais são filhos/prefab instances. O robô de referência possui Rigidbody2D dinâmico e collider, enquanto o robô controlado é atualizado diretamente pelo `CarController`.

Na versão web os tiles são desenhados com transformações do Canvas, mantendo a dimensão aproximada de 0,63 unidade derivada do PNG, PPU e escala 3. O background denominado na cena não pôde ser recuperado no ZIP de assets: o SpriteRenderer referencia um GUID de sprite não localizado no pacote. O objeto `fundo` está centrado em `(1.2818,0.3231)`, escala `(7.840344,8.012656,1)` e usa tonalidade `(0.4941,0.6431,0.6431)`, mas seu GUID de sprite não resolve para um PNG no pacote. Por isso, o fundo é vetorial, com grade e cores escuras. Os sprites de robô e parede são os PNGs originais; caso um PNG falhe, há desenho vetorial de contingência.

## 5. Controlador fuzzy recuperado

### 5.1 Variáveis linguísticas

| Código | Interpretação | Universo padrão no C# |
|---|---|---:|
| EA | Erro angular | `[-π,π]` |
| EP | Erro de posição/distância | `[-5,5]` |
| VA | Velocidade angular `ω` | `[-5,5]` |
| VEL | Velocidade linear `v` | `[-5,5]` |

### 5.2 Formatos de pertinência

`PertController.cs` declara três formatos:

- Triangular: três parâmetros `[a,b,c]`.
- Trapezoidal: quatro parâmetros `[a,b,c,d]`.
- Gaussiana: dois parâmetros `[centro, sigma]`.

O código C# original usava \(\exp(-((x-c)/\sigma)^2)\), sem o fator `1/2` no expoente. Na versão web, a gaussiana foi ajustada para a convenção IEEE 1855/JFML, \(\exp[-\tfrac12((x-c)/\sigma)^2]\), de modo que o segundo parâmetro corresponda diretamente a \(\sigma\) na exportação FML. `singleton` não é um quarto formato de pertinência: é uma opção de fuzzificação do sinal de entrada.

### 5.3 Operadores e inferência

| Etapa | Opções originais |
|---|---|
| S-norma | Máximo; soma probabilística `a+b−ab`; soma de Einstein `(a+b)/(1+ab)` |
| T-norma | Mínimo; produto `ab`; produto de Einstein `ab/(2−a−b+ab)` |
| Implicação | Mínimo; produto |
| Fuzzificação | Singleton; gaussiana; triangular |
| Defuzzificação | Centroide (CG); média dos máximos (MOM); menor máximo (SOM); maior máximo (LOM) |

A regra serializada tem a ordem `[EA_i, EP_j, VA_k, VEL_l]`. A conjunção dos antecedentes e a conjunção dos consequentes usam a T-norma; a implicação relaciona o disparo e o consequente; e as regras são agregadas por S-norma.

Para o centroide, `FuzzySets.Deffuz` avalia uma grade `51 × 51` no espaço de saída. O resultado do fuzzy é `[VA, VEL]`, isto é, `[ω,v]`. `CarController` troca deliberadamente as posições ao compor a entrada do modelo, que espera `[v,ω]`. A auditoria não encontrou inversão de índices na matriz de regras: a ordem usada em `AdicionaRegra`, `UpdateTextoRegras` e `Inferencia` é coerente.

## 6. Diagnóstico de defeitos e correções

### 6.1 Defeitos confirmados

| ID | Local | Problema no C# | Correção na versão web |
|---|---|---|---|
| FZ-01 | `FuzzySets.cs`, linha 625 | Na fuzzificação triangular, a função de pertinência da segunda entrada usa `err1` para construir o triângulo, em vez de `err2`. | A pertinência fuzzy da segunda entrada é centrada em `err2`. |
| FZ-02 | `FuzzySets.cs`, linha 669 | O centroide divide por `massa` sem verificar `massa=0`; nenhuma regra coberta pode gerar `NaN`/`Infinity`. | Massa nula ou não finita retorna comando neutro `[ω,v]=[0,0]`, com diagnóstico visível. |
| FZ-03 | `FuzzySets.cs`, em `Inferencia()` (alocação de `pert_regras`) | `ruleBase.Count` é acessado antes da verificação de `ruleBase == null`; a verificação posterior não protege o acesso. Lista vazia também leva a `pert_regras[0]`. | Base nula/vazia é tratada antes de qualquer indexação; saída neutra segura. |
| FZ-04 | `FileHandler.cs`, linha 92 | `SerializaDados` grava `FormatoE1` no campo `FormatoE2`. O desserializador lê corretamente um campo separado para E2, logo formatos diferentes podem ser corrompidos na ida e volta. | Configuração web usa objeto JSON versionado e salva os formatos de cada variável explicitamente. |
| FZ-05 | `PertController.cs`, linhas 323, 364 e 405 | Nos painéis EP, VA e VEL, o campo “superior” recebe `inferior.ToString()`. A interface exibe valor incorreto ao reabrir os painéis. | Limites inferior e superior são apresentados de seus próprios campos de estado. |
| FZ-06 | `Trimf`, `Trapmf`, `Gaussmf` e entrada UI | Parâmetros degenerados não são validados; larguras nulas podem gerar divisões por zero e `σ=0` torna a gaussiana indefinida. Campos são convertidos diretamente por `float.Parse`. | Ordenação/validação, limites finitos e `σ>0`; valores são normalizados antes de persistir. |
| FZ-07 | `Inferencia()` e índices das regras | Índices de regra não são conferidos contra o número de pertinências existente. Uma configuração inconsistente pode acessar posições inexistentes. | Regras inválidas são descartadas ao carregar; a UI impede adicionar regra quando não há conjuntos. |
| FZ-08 | `PertE1/E2` + `Deffuz` | Fora da cobertura dos conjuntos, todas as pertinências podem ser zero; com centroide isso culmina na divisão por zero. | Entradas são saturadas ao universo de discurso e a massa nula possui fallback neutro explícito. |
| ODE-01 | `ODE.cs`, linha 263 | `TrapezoidalStep()` de um passo implementa `xₙ₊₁ = xₙ + h(fₙ₊₁+fₙ)` sem o fator `1/2`. | A versão web usa RK4 e não depende deste método defeituoso. A rotina trapezoidal multi-passo chamada pela cena tem `/2` corretamente. |
| ODE-02 | `ODE.cs`, linha 383 | O último passo de `GaussLegendre3()` chama `GaussLegendreStep()` (Gauss–Legendre de dois estágios, 4ª ordem), e não `GaussLegendre3Step()` (três estágios, 6ª ordem). | A nova aplicação usa RK4 explícito; o erro não é herdado. |
| ODE-03 | `ODE.cs`, Newton/Broyden | Laços iterativos sem limite máximo de iterações e sem proteção sistemática contra não finitude, Jacobiana singular ou denominador de atualização de Broyden próximo de zero. | RK4 explícito não utiliza esses solucionadores; o loop online também limita passos por quadro e atraso acumulado. |

### 6.2 Riscos/inconsistências adicionais

- O integrador multi-passo calcula `n` por arredondamento de `(tf−t0)/dt`. Para horizontes não múltiplos do passo, o arredondamento pode produzir uma malha de tamanho inadequado; a versão batch usa `h=min(dt,tf−t)` no último passo e atinge exatamente `tf`.
- O arquivo salvo pelo `FileHandler` é um formato texto posicional, embora o comentário o chame de JSON. A leitura depende da ordem exata das linhas e dimensões; a web usa JSON com `schemaVersion` e validação de índices.
- A lista nula e a lista vazia têm comportamentos diferentes no C#: `null` seleciona o controle manual em `CarController`, mas uma lista vazia entra na rotina fuzzy e falha. A versão web elimina a ambiguidade: base vazia retorna saída neutra; modo manual é uma seleção explícita da interface.
- A cena original usa eixos/inputs do Unity para controlar tanto o robô como a referência manual. No browser isso foi substituído por controles explícitos, pointer interaction e rampas; a rampa de atuação é uma conveniência didática e não faz parte das equações originais.

### 6.3 O que não foi classificado como bug

Não encontrei evidência de inversão dos índices `[EA,EP,VA,VEL]`. A inversão final `[ω,v] → [v,ω]` feita por `CarController` é intencional e necessária para a ordem de entradas da planta. Também não classifiquei como bug a rotação inicial `−90°` do sprite: ela compensa a orientação-base do desenho.

## 7. Implementação web entregue

| Componente | Implementação |
|---|---|
| Renderização | HTML5 Canvas 2D nativo, contexto 2D, transformações afins e sprites PNG originais |
| Nitidez | Canvas dimensionado com `devicePixelRatio` |
| Câmera | Altura lógica de 10 unidades, equivalente a orthographic size 5 |
| Fallback gráfico | Robôs e tiles vetoriais quando imagens falham; fundo vetorial porque o sprite não está no ZIP |
| Offline/batch | RK4 com passo final adaptativo, registro completo, gráficos e replay com scrubber/velocidades 1×, 2×, 4× e 8× |
| Online | Relógio `performance.now()`, acumulador de passo fixo, rAF, janela de histórico de 10 s |
| Gráficos online | `Plotly.react` com `datarevision`; séries limitadas por `slice(-N)`. Fallback Canvas se o CDN estiver indisponível |
| Controlador | Mamdani 2×2, formas triangular/trapezoidal/gaussiana, operadores de norma, implicação, fuzzificação e defuzzificação |
| Configuração | Edição numérica e arraste dos centros das pertinências, edição da tabela de regras, regras ativas e superfície de controle |
| Escalas | Ganhos configuráveis de normalização EA/EP e desnormalização VA/VEL; valor unitário reproduz o domínio sem escala adicional |
| Persistência | `localStorage` com chave `fuzzy_lab_config` |
| Anti-cache | Carregamento de `app.js` no final de `index.html` com `?t=` + `Date.now()` |
| Teoria | MathJax 3 carregado sob demanda para as expressões matemáticas |

## 8. Diferenças intencionais em relação à bancada original

1. A integração web é RK4, conforme requisito da conversão, enquanto o Unity seleciona trapezoidal multi-passo. Os resultados não serão numericamente idênticos passo a passo; para uma planta cinemática suave e passo de 1/60 s, RK4 oferece boa precisão e não herda os problemas dos solucionadores implícitos.
2. O preset inicial de 25 regras é exclusivamente didático. A cena não contém pertinências ou regras persistidas. É possível voltar a uma base vazia pelo botão próprio.
3. EP começa em `[0,5]`, pois é uma distância. O universo original `[-5,5]` pode ser restaurado pelo editor.
4. Os ganhos de escala são controles explícitos novos, com valor 1 por padrão. No projeto analisado, a escala estava implícita nos limites dos universos.
5. A interação de referência e os comandos manuais foram adaptados à web. O modo manual do Canvas usa clique/arraste para posicionar o alvo; as setas e os botões comandam o robô em malha aberta com rampa.
6. O sprite de fundo ausente é substituído por um cenário vetorial. As cinco imagens originais disponíveis foram preservadas em `desenhos/`.

## 9. Execução e verificação

A aplicação não exige compilação nem instalação de dependências. Na pasta do projeto, execute:

```bash
python3 -m http.server 8000
```

Abra `http://localhost:8000` no navegador. O servidor local é recomendado em vez de abrir o arquivo por `file://`, para que os caminhos relativos dos PNGs funcionem de forma uniforme.

A sintaxe de `app.js` foi verificada com `node --check`. MathJax e Plotly são carregados por CDN quando suas funcionalidades são abertas; se não houver conexão, o Canvas de gráficos continua disponível, e as equações permanecem em TeX. A física, o fuzzy e as simulações são executados localmente em JavaScript.

### 10. Validação executada na conversão

Foram realizadas as seguintes verificações locais:

- `node --check app.js`: sintaxe JavaScript aprovada.
- Verificação estática do HTML: 103 IDs únicos; os 99 IDs referenciados pelo JavaScript estão presentes no documento.
- Teste isolado do motor numérico: preset com 25 regras; avaliação fuzzy finita para uma condição de teste; RK4 reproduz corretamente os incrementos esperados de translação e rotação em passo de 0,1 s.
- Testes de robustez: saturação dos ganhos/saídas e retorno seguro quando a base de regras está vazia.
- Verificação do carregador anti-cache: `app.js?t=` seguido de `Date.now()`.
- Verificação HTTP local dos arquivos principais e dos sprites: respostas `200 OK`.

Não foi possível concluir uma regressão visual automatizada em navegador gráfico neste ambiente de execução. Assim, a validação acima cobre sintaxe, estrutura DOM, motor numérico e entrega HTTP, mas não substitui a conferência visual final em Safari, Chrome e Firefox. Recomendo conferir especialmente o enquadramento da cena e os painéis responsivos nos dispositivos usados pelos alunos.
