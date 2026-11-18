# Certificados independentes de regeneração MIMO e PVM

WP-AUDIT-FIX-F9-MIMO-REGENERATION, incluindo o adendo explícito PVM registrado
pelo Maestro em PROJECT_STATE/FOLLOWUP. F9, CL-DIR-001 §§10.2/10.4/13.11 e
Apêndices C/E. Base `4c908f97fe955ca41db6f5d582a56493198ea78c`, 2026-11-18.

## Domínio, independência e ouro

Os helpers são verificadores **das duas fixtures fixas CPython**, não novas
rotinas científicas do produto nem aritmética intervalar geral. Não importam
`control_lab`, SciPy, o estimador/simulador de produção ou o gerador para criar
referências. As referências usam Decimal com 80 dígitos e os números float64 são
convertidos exatamente por `Decimal.from_float`. PVM compartilha somente os
utilitários de estrutura, igualdade, conversão exata e gamma do módulo MIMO;
suas equações escalares são verificadas separadamente.

Uma comparação recursiva de tipos, chaves e comprimentos ocorre **antes** de
qualquer coerção ou normalização, rejeitando NaN/Inf, strings numéricas, bools,
listas aninhadas ou truncadas e metadados incompatíveis. Depois, somente folhas
enumeradas são substituídas numa cópia para verificar igualdade exata de todo o
restante. Nenhum argumento é alterado e nenhum arquivo ouro é escrito.

- MIMO: folhas permitidas `omega.data`, `expected.G/S/T/RGA.real/imag`,
  `expected.singular_values.data`, `expected.max_identity_residual` e
  `multiple_crossings.gain_crossings`.
- PVM: **somente** `cases[i].expected.x/u/y.data`. Todo `t`, `switch_times`,
  A/B/C/D/P/K/Q/R, x0, mapas de referência, r, flags PathView/maturidade,
  saturação, tipos/shapes/ordem, proveniência e tolerâncias permanecem exatos.

O gerador não muda. A integridade dos bytes das sete fixtures e do manifesto de
checksums continua verificada por SHA-256, separadamente destes certificados.
Os limites já congelados são obrigatórios: MIMO resposta `1e-11`, identidade
`1e-11`, valores singulares `1e-11`, cruzamentos `1e-7`; PVM trajetória `2e-8`,
equações `1e-12`, ganho `1e-12`. Nenhum deles é reescrito ou aumentado.

## Modelo de arredondamento declarado

Define-se `u=2^-53` e `gamma(q)=q*u/(1-q*u)` para acumulação de operações
float64. Os certificados confrontam resultados regenerados com referências de
80 dígitos e exigem ainda os limites congelados. Seus envelopes adicionais são
escalonados pelas expressões efetivamente avaliadas e pela dimensão fixa.

Para `pow`/`exp`/`log` adotamos um orçamento declarado de **dois ULPs float64**
além da propagação do erro dos argumentos. É uma hipótese de precisão das
implementações numéricas suportadas neste domínio, testada também sob a
configuração SIMD que reproduz a falha. IEEE-754 não obriga todo `np.power`,
libm ou kernel vetorial a satisfazê-la. Um backend que exceda o envelope falha
honestamente; o verificador não normaliza essa falha para obter verde.

Os envelopes `gamma(64)`, `gamma(32)` e `gamma(128)` abaixo são critérios
backward de precisão para as pequenas expressões desta fixture, não teoremas
universais sobre o número de operações internas do LAPACK/BLAS. Seu domínio,
escala, condicionamento, teste positivo real e negativos são parte da revisão
F9 conforme §10.2. A precisão Decimal deixa dezenas de dígitos de margem,
mas não é arredondamento dirigido/enclosure intervalar formal.

## Grade MIMO: referência matemática e erro do expoente

A grade tem 62 pontos: zero e `10^(-3+k/10)` para `k=0..60`. Zero e endpoints
float64 `0.001`/`1000` são exatos em relação às representações congeladas;
positividade e ordem estrita são exigidas.

`linspace(-3,3,61)` envolve a divisão `(3-(-3))/60`, multiplicação por k e soma
com -3. A subtração inicial e os inteiros são representáveis exatamente. Para
o expoente, usa-se o limite **absoluto**

`delta_e = gamma(3) * (3 + k/10)`.

Esse limite continua válido perto de zero, onde um erro relativo do expoente
seria inadequado por cancelamento. A referência Decimal calcula
`w_ref=exp(e_ref*ln(10))`. O erro de frequência permitido é

`delta_w = w_ref*(exp(ln(10)*delta_e)-1) + 2*ulp(float(w_ref))`.

O primeiro termo é a propagação exponencial do erro do argumento; o segundo
é a hipótese explícita de potência/conversão, e **não** `response_atol` nem o
maior desvio observado. Também se confronta `ln(w)/ln(10)` com o expoente e,
entre vizinhos, com o incremento 0.1. Para erro relativo r da conversão, o
orçamento inverso usa `-ln(1-r)/ln(10)`; os limites dos dois vizinhos somam-se
no teste de espaçamento.

A candidata preservada do CI, inclusive seus cinco pontos diferentes de um
ULP, passa este confronto matemático. A referência ouro também é confrontada
com a fórmula, evitando que apenas a proximidade entre dois arrays seja aceita.

## Respostas MIMO: fórmulas independentes e condicionamento

Para `M=[[2,1],[0.5,3]]`, `z=1+jw`, `G=M/z` e `H=zI+M`, usa-se adjugata 2x2:

`det(H)=11.5-w²+j7w`, `abs(det(H))²=w^4+26w²+132.25 > 0`.

As expressões Decimal calculam `S=z*adj(H)/det(H)` e
`T=M*adj(H)/det(H)`. Não se chama inversão/solve de produção. O determinante de
M é 5.5, a RGA é a constante analítica `[[12/11,-1/11],[-1/11,12/11]]`, e os
dois casos singulares preservados são confirmados por determinante zero e pelo
status `undefined` exato. Não se reinterpreta uma singularidade como sucesso.

Os valores singulares são obtidos sem eigensolver: os autovalores de `M.T M`
são `(57 +/- sqrt(1313))/8`, e seus sqrt são divididos por `sqrt(1+w²)`.
Positividade e ordem decrescente são exigidas em cada frequência.

As respostas complexas devem coincidir com essas referências dentro de
`gamma(64)*max(1,abs(ref))`. Na divisão complexa há até onze operações reais;
determinante, produtos de adjugata e numerador T somam poucas dezenas. O termo
unitário evita falso erro relativo perto dos zeros por cancelamento. A escala
do determinante é favorável: `(11.5+w²)² <= abs(det(H))²`. Mesmo quando sua
parte real cancela, o denominador complexo permanece bem condicionado nesta
grade. O envelope 64 cobre essas pequenas cadeias e a escala de seus termos;
não afirma estabilidade universal para uma matriz MIMO arbitrária.

Para valores singulares, exige-se
`gamma(32)*max(1,sigma_ref)`. A fórmula tem poucas somas/produtos/raízes; a
subtração `57-sqrt(1313)` permanece longe de zero (razão de condicionamento
menor que cinco). O critério exige que a saída regenerada alcance essa
precisão; não usa uma tolerância de ganho ou uma garantia presumida de LAPACK.

`S+T=I` é verificado diretamente nas saídas candidatas e pelo limite congelado
de identidade. O máximo residual declarado deve ser finito, não negativo,
menor que `identity_atol` e consistente com o residual recalculado, até
`gamma(8)` na escala unitária. Isso admite o arredondamento da soma/cancelamento
float64, mas rejeita um diagnóstico incoerente apenas por estar abaixo de 1e-11.

### Propagação explícita da grade na comparação com o ouro

As fórmulas são reconstruídas tanto em `w_candidato` como em `w_ouro`. Não se
normaliza a frequência antes de verificar respostas calculadas em outra grade.
Se `d=abs(w_candidato-w_ouro)`, `l=min(w)`, `h=max(w)`, usa-se

`|delta G_ij| <= d * max(abs(M_ij))/(1+l²)`.

Para H inversa, um limite de Frobenius ao longo do intervalo é

`L = sqrt(2h²+26.25)/sqrt(l^4+26l²+132.25)`.

De `dS/dw = j*(H^-1 - z H^-2)` segue
`||delta S||F <= d*(L+sqrt(1+h²)*L²)`; T tem derivada oposta. A RGA é constante.
Para sigma, a derivada é limitada por
`sigma0_max*h/(1+l²)^(3/2)`. Cada comparação candidata/ouro passa **ambos**:
o atol congelado da grandeza e a soma dos dois orçamentos de fórmula com esse
limite de propagação. O atol congelado nunca é ampliado.

## Cruzamentos múltiplos independentes

O módulo unitário de `11(s+1)/((s+0.1)(s²+0.2s+100))` dá, para `q=w²`,

`p(q)=q³-199.95q²+9877.0004q-21=0`.

O coeficiente float congelado é `-199.95000000000002`, resultado do cálculo de
coeficientes em float64; esse dado permanece exato por estrutura/igualdade.
A referência matemática usa a equação decimal nominal, permitindo verificar
independentemente o efeito do arredondamento dos coeficientes, sem copiá-los
como uma referência numérica autojustificada.

O programa isola raízes por 240 bisseções Decimal nos intervalos de q
`[0,1]`, `[81,100]`, `[100,121]`, cada qual com mudança de sinal. Uma cúbica tem
no máximo três raízes; essas três raízes distintas, com ordem estrita, são
portanto a lista completa. A largura restante é irrelevante na escala float64.

Cada frequência deve passar o `crossing_atol` congelado **e** o confronto com a
raiz isolada. Usa-se o orçamento backward `gamma(128)*sum(abs(termos de p))`,
propagado para w por `abs(2w*p'(w²))`, mais quatro ULPs de conversão da raiz.
Formação dos pequenos polinômios, potências/Horner e arredondamento dos
coeficientes contribuem com poucas dezenas de operações; 128 é um envelope
conservador declarado dessa verificação escalonada, não uma contagem garantida
do eigensolver companheiro que gerou as raízes. O residual p(w²) também é
avaliado independentemente e limitado. Uma lista próxima porém deslocada
dentro de 1e-7, uma raiz duplicada ou ordem errada não passa só pelo atol ouro.

## PVM: equações escalares e entradas congeladas

O adendo PVM cobre uma segunda manifestação da mesma configuração SIMD: dez
folhas de x/u/y variam nos últimos bits. Nenhum tempo, switch, matriz, parâmetro
ou flag varia e **nenhum deles pode ser normalizado pelo novo helper**.

O benchmark possui `A=diag(-1,-2)`, `B=R=P=K=I`, `Q=diag(3,5)`. O helper
verifica essas matrizes e recalcula `A.T P+P A-K.T R K+Q=0`, ganho e resíduo,
sem chamar CARE. Cada caso possui referência constante e `v=N*r`. O caso
`C!=I`/m!=p usa sua matriz C preservada; D é zero e os estados, não as saídas,
realimentam o controlador.

Sem saturação, para cada canal `a<0`,

`x(t)=e+(x0-e)*exp((a-1)t)`, `e=v/(1-a)` e `u=v-x`.

Se o controle inicial excede um limite, usa-se `u_sat=clip(v-x0)`,
`e_sat=-u_sat/a`, `threshold=v-u_sat` e

`t_star=ln((threshold-e_sat)/(x0-e_sat))/a`.

Antes da comutação: `x=e_sat+(x0-e_sat)*exp(a*t)`; depois:
`x=e+(threshold-e)*exp((a-1)*(t-t_star))`. A referência Decimal verifica a
continuidade no switch e que o equilíbrio final permanece no regime não
saturado (não há segunda comutação omitida nesta fixture). A derivada analítica
de cada regime permite verificar a equação `xdot=a*x+u` diretamente.

### Switch congelado e precisão de log

`switch_times` continua **exatamente** o dado congelado. Para confrontá-lo com
a fórmula independente, sejam n e d o numerador e denominador da razão do log.
Calculam-se envelopes relativos `r_n=gamma(4)*sum(abs(termos_n))/abs(n)` e
`r_d=gamma(2)*sum(abs(termos_d))/abs(d)`. Ambos devem ser menores que um.
A propagação no log é

`E_log = -ln(1-r_n)-ln(1-r_d)+2*ulp(float(ln(n/d)))`.

Dividindo por abs(a) e acrescentando `gamma(1)*abs(t_star)` obtém-se o orçamento
do switch usado na propagação de trajetória. Esse confronto não cria um atol
global de tempo nem permite editar um switch na candidata: a igualdade exata
prévia rejeita inclusive uma alteração de um ULP no campo armazenado.

### Trajetória, controle e saída

Para `x=e+c*exp(rate*(t-shift))`, propaga-se o erro do argumento por

`E_arg=gamma(4)*(abs(rate)*(abs(t)+abs(shift))+abs(arg)) + abs(rate)*E_switch`.

O erro da exponencial é `exp(arg)*(exp(E_arg)-1)+2*ulp(float(exp(arg)))`.
O orçamento de x soma `abs(c)*E_exp` e
`gamma(16)*max(1,abs(e)+abs(c)*exp(arg)+abs(x0)+abs(v))`. A reserva dimensiona
as divisões/subtrações dos equilíbrios/coeficientes e soma/produto finais da
pequena expressão escalar, com escala dos termos para incluir cancelamentos.
Ele não é tolerância de um integrador e não vale para dinâmica geral.

A função clip é não expansiva. Por isso o orçamento de u soma o erro de x e
`gamma(4)*max(1,abs(v)+abs(x))`. Verifica-se também a lei de controle contra
o x **candidato** e, quando saturado, os limites do atuador são estritos.
Para y, propagam-se os erros dos estados por `sum(abs(C_ji)*E_xi)` e acrescenta-se
o erro da pequena soma/produto Cx. Além da referência independente em Decimal,
a saída candidata deve satisfazer C vezes o x candidato. A referência analítica
de x impede que uma corrupção coordenada em x/u/y passe por mera autoconsistência.

O residual de ODE usa a derivada analítica e os x/u candidatos; passa tanto o
`equation_atol` congelado como o limite propagado `abs(a)*E_x+E_u`. Todas as
folhas x/u/y passam ainda `trajectory_atol` contra o ouro. As quatro trajetórias,
81 instantes e casos C=I/C!=I, saturação on/off são verificados integralmente.

## Evidência e limites

A candidata MIMO original do CI passa o certificado; campos estruturais e dados
númericos corrompidos são rejeitados por testes separados do autor. A combinação
`NPY_DISABLE_CPU_FEATURES=AVX512F,AVX2,FMA3` com OpenBLAS Haswell reproduz exatamente
as 92 diferenças MIMO e as dez folhas PVM relatadas. Os probes do auditor
registram kernels/flags efetivos e saídas diferentes. Outros dois testes usam
kernels Haswell e Sandybridge, no mesmo computador, sem alegar hosts distintos.

Os limites 2-ULP transcendentais, condicionamento desta grade/matriz e dinâmica
escalar fixa são hipóteses explícitas. O certificado falha se não forem atendidos.
Não há alegação de libm universal, certificado intervalar dirigido, novas
capacidades Wasm/PathView ou promoção de maturidade/gates.
