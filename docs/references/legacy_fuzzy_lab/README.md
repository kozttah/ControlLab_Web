# Laboratório Virtual de Controle Fuzzy — Web nativa

Conversão do laboratório Unity para HTML, CSS e JavaScript puros, usando Canvas 2D e os sprites PNG originais.

## Executar localmente

O projeto é inteiramente client-side. Em navegadores que permitem arquivos locais, basta abrir `index.html`.

Se o navegador bloquear algum recurso local, execute um servidor simples na pasta do projeto:

```bash
python3 -m http.server 8000
```

Depois acesse `http://localhost:8000`.

Não é necessário npm, Unity, Three.js, Pyodide, Monaco ou backend.

## Arquivos principais

- `index.html` — interface e organização das quatro abas.
- `teoria.html` — conteúdo da aba inicial **Modelo Matemático e Teoria**. Este é o arquivo que o professor deve editar para adaptar o material às aulas.
- `app.js` — planta, RK4, inferência fuzzy, editor de pertinências/regras, importação/exportação FML/XML, gráficos e simulações offline/online.
- `desenhos/` — sprites PNG originais do laboratório.
- `RELATORIO_TECNICO.md` — engenharia reversa e decisões da conversão.

## Fluxo didático

- A primeira aba é **Modelo Matemático e Teoria** e carrega `teoria.html` em um `iframe`.
- A segunda aba é **Configuração Fuzzy e Regras**.
- O controlador começa vazio em toda nova abertura: não há conjuntos de pertinência nem regras pré-carregadas.
- Os universos de discurso e as opções de inferência permanecem preenchidos como estrutura do laboratório, mas não constituem uma solução fuzzy pronta.
- Cada conjunto nebuloso pode receber um nome linguístico. Se o campo ficar vazio, a interface usa automaticamente `Conjunto 1`, `Conjunto 2`, etc.
- Os seletores da base de regras mostram esses nomes, mantendo índices internos numéricos.

## FML / XML

O botão **Salvar FML / XML** gera um documento XML com a estrutura pública do Fuzzy Markup Language: `fuzzySystem`, `knowledgeBase`, `fuzzyVariable`, `fuzzyTerm`, `mamdaniRuleBase`, regras, antecedentes e consequentes.

A representação segue a estrutura do IEEE 1855-2016. Os operadores disponíveis no laboratório são mapeados para os identificadores normativos (`MIN`, `PROD`, `EPROD`, `MAX`, `PROBOR`, `ESUM`, `COG`, `MOM`, `LM` e `RM`). Rótulos linguísticos amigáveis podem conter espaços; na exportação eles são convertidos para identificadores XML/FML válidos e os rótulos originais são preservados no comentário `FuzzyLabMetadata` para round-trip no aplicativo. O exportador recusa configurações incompletas (variáveis sem termos ou base sem regras).

O botão **Carregar FML / XML** reabre os arquivos exportados pelo laboratório. O importador também aceita documentos FML Mamdani que utilizem as variáveis `EA`, `EP`, `VA` e `VEL` e as funções triangular, trapezoidal e gaussiana.

## Exportação dos gráficos

Depois de executar uma simulação offline, o botão **Exportar gráficos como PNG** gera uma única figura em alta resolução com os quatro gráficos organizados em uma grade 2 × 2.

## Dependências externas opcionais

O MathJax 3 da página `teoria.html` é carregado por CDN. Se não houver conexão, o restante da aplicação continua funcionando e as expressões TeX permanecem visíveis como texto-fonte.


## Revisão: fuzzificação e pilotagem manual

- Os parâmetros do fuzzificador não singleton agora são configuráveis em Configuração Fuzzy & Regras: sigma da Gaussiana, meia-largura da triangular e número de amostras do GMP.
- No modo online, as setas pilotam o carrinho de referência quando a referência está em modo manual; pilotam a planta quando o atuador está em manual; se ambos estiverem manuais, o mesmo comando é aplicado aos dois.

## Aba Desafio

A aba **Desafio** usa o controlador fuzzy atualmente configurado em três pistas fechadas de dificuldade crescente: Simples (oval), Média (curvas alternadas) e Difícil (sinuosa). Ao iniciar uma tentativa, o controlador do aluno é congelado até o término ou reset.

A referência é conduzida automaticamente por um controlador geométrico com *look-ahead* sobre a linha central da pista. Cada pista possui uma velocidade máxima pré-validada para esse controlador; o aluno escolhe a velocidade desejada dentro da faixa permitida.

A pista é definida vetorialmente por uma spline fechada. A faixa bege/off-white é a região válida para pontuação. Os muros físicos ficam um pouco além dela: uma pequena excursão fora da faixa faz o aluno deixar de acumular distância válida, mas os muros impedem atalhos pelo interior/exterior da pista.

A pontuação considera o progresso longitudinal válido, e não a distância euclidiana do robô. Assim, zigue-zagues ou giros no mesmo local não aumentam artificialmente o resultado. O score atual é normalizado pelo comprimento da pista, recebe um multiplicador associado à velocidade de referência escolhida e um fator temporal exponencial suave. A câmera segue os dois carrinhos e ajusta o zoom automaticamente para mantê-los enquadrados.
