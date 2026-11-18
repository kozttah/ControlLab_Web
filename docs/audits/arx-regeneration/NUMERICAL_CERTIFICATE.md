# Certificado independente da regeneração ARX

WP-AUDIT-FIX-F9-ARX-REGENERATION; F9; CL-DIR-001 §§10.2, 10.4 e 13.11,
R-23/R-24, regressões T-ID-01/T-ID-03. Base `181bba0f864f9ea3bb02f136227d664aa3913e07`.
Data: 2026-11-18. Este documento descreve um verificador de uma fixture CPython
específica, não um novo estimador de produção nem um certificado intervalar geral.

## Domínio e preservação do ouro

O teste anterior exigia igualdade de dicionários também nos campos calculados por
GELSD/BLAS. A fixture já permite variação dos últimos bits, mantendo critérios
numéricos congelados. O gerador e seus dados não mudam. O helper
`scripts/arx_regeneration_certificate.py` não importa `control_lab`, SciPy nem o
gerador: ele recebe uma candidata regenerada e a referência congelada.

Antes de qualquer conversão ou normalização, verifica recursivamente tipos Python,
chaves e comprimentos de listas, e rejeita NaN/Inf. Assim strings numéricas, bools,
nested data, dimensões transmitidas por broadcasting ou listas truncadas não podem
ser ocultadas pela conversão NumPy. Após as comparações abaixo, substitui somente
folhas calculadas numa **cópia** da candidata e exige igualdade recursiva exata do
restante. Nenhum argumento é modificado.

São folhas calculadas permitidas: `expected.theta.data`, `expected.poles.real/imag`,
`expected.singular_values.data`, os quatro FIT e as quatro `predictions.*.*.data`.
Entradas `t/u/y/clean_y/innovations`, parâmetros plantados, ruído, PRBS, splits,
rank, shape/dtype/order, schema, proveniência e tolerâncias permanecem exatos.
As sete fixtures e seus checksums continuam protegidos pelo verificador SHA-256.

| Grandeza candidata versus ouro | Critério já congelado |
| --- | --- |
| Coeficientes estimados | `theta_atol = 1e-10`, `rtol=0` |
| Polos, componentes real e imaginária | `pole_atol = 1e-9`, `rtol=0` |
| Predições/simulações | `prediction_atol = 1e-9`, `rtol=0` |
| FIT percentual | `fit_atol = 1e-8`, `rtol=0` |

Não se usa o critério mais largo dos parâmetros plantados como limite do estimador.
Valores singulares não recebem um `atol` inventado: são confrontados com o espectro
independente descrito abaixo. Os certificados são **adicionais** à comparação com
ouro; uma candidata próxima mas incoerente também deve ser rejeitada.

## Aritmética independente e escala de arredondamento

Reconstrói-se, dos dados preservados, a regressão de treinamento de 510 linhas e
4 colunas: `Phi[k] = [-y[k-1], -y[k-2], u[k-1], u[k-2]]`, alvo `y[k]`.
Cada float64 é convertido exatamente por `Decimal.from_float`, com contexto de
60 dígitos. Produtos internos, resíduos, normas e as recorrências são calculados
em Decimal. Não se chama o estimador QR de produção, GELSD, `numpy.linalg`,
`scipy.linalg` ou uma referência retornada pelo próprio gerador.

Para float64, define-se `u = eps/2` e `gamma(q) = q*u/(1-q*u)`. A expressão vem do
modelo usual de arredondamento por operação e da acumulação de erros relativos.
O envelope escolhido para os certificados normal/Gram é `gamma(m+8*n)`, aqui
`gamma(542) ≈ 6.02e-14`: contém a escala de redução em 510 amostras e uma reserva
dimensionada pelo pequeno bloco de quatro parâmetros. **O termo `8*n` não é uma
contagem de operações nem um teorema universal de erro do LAPACK GELSD.** Trata-se
do envelope backward declarado para esta fixture bem condicionada, verificado
contra dois kernels BLAS reais e contra corrupções adversariais. A independência
vem do cálculo Decimal dos invariantes, não de uma suposição de que GELSD é exato.

Não se afirma arredondamento dirigido ou enclosure intervalar formal. Inputs e
escala são fixos, o Gram tem condição aproximada 81.35, e as contas Decimal têm
dezenas de dígitos de margem em relação a esses limites float64. Generalização a
outros problemas, escalas ou matrizes mal condicionadas exige nova revisão F9.

## Estacionariedade e unicidade de mínimos quadrados

Calcula-se `G = Phi.T Phi`, residual `r = Phi theta - y` e gradiente `g = Phi.T r`
inteiramente em Decimal. Exige-se Gram positivo definido e rank exatamente 4.
O limite de estacionariedade é

`||g||2 <= gamma(m+8*n) * (||Phi||F² ||theta||2 + ||Phi||F ||y||2)`.

A escala contém os dois termos efetivamente envolvidos na equação normal, em vez
de um limiar absoluto universal. Como `G` é positivo definido, a função quadrática
é estritamente convexa. Além disso, `||theta-theta_OLS||2 <= ||g||2/lambda_min(G)`:
o residual calculado controla a distância ao único ótimo. A candidata ainda deve
satisfazer o `theta_atol` congelado. Isso rejeita alteração de coeficiente que
esteja dentro de `theta_atol`, mas não represente o ajuste dos dados congelados.

## Valores singulares por Gram/Jacobi independente

Diagonaliza-se o Gram 4x4 por rotações Jacobi em Decimal, escolhendo o maior termo
fora da diagonal e terminando quando ele é no máximo `1e-45 * max(abs(G))`.
Exige-se convergência em até 200 rotações e verifica-se a soma absoluta de termos
fora da diagonal por linha. Pelo limite de Gershgorin, o resíduo espectral da matriz
diagonalizada é no máximo quatro vezes esse cutoff, irrelevante na escala float64
desta fixture. A precisão Decimal é finita; este argumento não transforma o
programa num pacote de aritmética intervalar certificada.

Os quatro valores singulares candidatos devem ser positivos e decrescentes.
Se `lambda_i` é o espectro Gram independente, exige-se para cada i:

`abs(sigma_i² - lambda_i) <= gamma(m+8*n) * ||Phi||F²`.

Uma justificativa da escala é a formação direta do Gram em float64: o modelo de
produto interno fornece `abs(DeltaG) <= gamma(m) * abs(Phi).T abs(Phi)`.
Consequentemente, `||DeltaG||2 <= gamma(m) * ||Phi||F²`; pela desigualdade de Weyl,
essa mesma quantidade limita a perturbação dos autovalores do Gram simétrico.
O verificador usa a referência Decimal em vez de formar esse Gram arredondado,
mas permite explicitamente essa escala de erro de redução. O envelope declarado
`gamma(m+8*n)` majora `gamma(m)` e reserva arredondamento do pequeno bloco de
quatro parâmetros, incluindo conversões e quadrado dos valores singulares. É um
critério de aceitação backward desta fixture, não uma prova de que toda sequência
interna de transformações de qualquer implementação GELSD respeita esse envelope.
Isso distingue a derivação dimensional da escala de erro de uma alegação indevida
de garantia de algoritmo externo.

Isso verifica **todo o espectro**, não somente traço/Frobenius. Uma corrupção
coordenada que preserve `sum(sigma_i²)` é rejeitada. A distância ao valor singular
de referência independente é limitada pelo mesmo orçamento dividido por
`sigma_i + sqrt(lambda_i)`, que é positivo neste domínio. Não há uso de tolerância
de coeficiente, polo ou FIT como substituto de um critério SVD inexistente.

## Polos, recorrência e FIT

Cada polo candidato deve satisfazer `z² + a1*z + a2 = 0`, com residual limitado por
`gamma(8) * (abs(z)² + abs(a1*z) + abs(a2))`. A fixture possui polos reais simples;
o teste também preserva a ordenação e compara ambas as componentes com o ouro.
O orçamento cobre os produtos/somas da avaliação nesta escala; não é critério
geral de localização de raízes quase múltiplas.

Para cada split, reproduz-se em Decimal a predição de um passo usando os dados
medidos, e a simulação livre usando as próprias saídas anteriores. As primeiras
duas amostras permanecem condições iniciais. Há quatro produtos e três somas em
cada atualização: orçamento local `gamma(7) * sum(abs(termos))`. Na simulação livre,
ele é amplificado pela soma finita dos módulos da resposta impulsiva da recorrência
de erro `e[k] = -a1*e[k-1] - a2*e[k-2] + delta[k]`. Adiciona-se margem de conversão
float64 `eps * max(1,max(abs(predicao)))`, que também domina termos de segunda
ordem de arredondamento neste domínio estável e fixo. No modo de um passo, a
amplificação é um. Cada predição candidata deve passar este certificado **e** o
limite congelado `prediction_atol` contra o ouro.

Recalcula-se `FIT = 100*(1-N/D)`, com `N=||y-yhat||2`,
`D=||y-mean(y)||2 > 0`, a partir da recorrência independente. Se `E` é o orçamento
de predição e `l` o número de amostras após as condições iniciais, usa-se

`100 * [sqrt(l)*E/D + gamma(8*l+32)*(1+N/D)*(1+||y||2/D)]`.

O primeiro termo propaga o erro vetorial de predição pela desigualdade triangular;
o segundo cobre reduções, centralização, normas e conversão do FIT. Também se
exige a comparação com o `fit_atol` congelado. Não se confia em FIT fornecido pelo
gerador para validar as predições do próprio gerador.

## Diagnóstico observado e limites

NumPy 2.3.5/SciPy 1.17.0, execução inicial deste helper:

| Certificado | Erro observado | Envelope |
| --- | --- | --- |
| Norma do gradiente normal | `5.382088902981674e-13` | `2.572846781851467e-10` |
| Maior erro de `sigma²` versus Gram | `1.0856320367667396e-12` | `1.504492455897903e-10` |

Os relatórios independentes registram as configurações efetivas Haswell e
Sandybridge, versões e resultados. São dois kernels no mesmo host, não uma
alegação de dois computadores distintos. Negativos incluem violações dos limites
congelados, resultados incoerentes ainda dentro desses limites, SVD com traço
preservado, rank/estrutura/entrada/metadados incorretos e NaN/Inf. O helper é
somente QA CPython da fixture ARX; não promove capacidade Pyodide, maturidade
experimental, solver ou gate.
