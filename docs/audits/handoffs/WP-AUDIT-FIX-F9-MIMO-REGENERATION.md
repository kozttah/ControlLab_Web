# Handoff F9 — WP-AUDIT-FIX-F9-MIMO-REGENERATION

Parecer F9: accepted

Revisor independente: `/root/f9_mimo_audit`, separado do produtor `/root/f9_mimo_producer`. Data: 2026-11-18. CL-DIR-001 §§10.2/10.4/13.11 e Apêndices C/E; R-23/R-24; regressões T-MIMO-01/T-MIMO-02/T-FREQ-02 e adendo explícito T-PVM-01 de QA CPython.

Fonte auditada: base `4c908f97fe955ca41db6f5d582a56493198ea78c` mais os sete arquivos identificados por SHA-256 em `docs/audits/mimo-regeneration/reviewer/checks.json` e `maestro/SUMMARY.json`. Este aceite cobre a regeneração numérica das fixtures fixas abaixo; não antecipa o resultado do CI hospedado nem a publicação do futuro commit.

## Problema, escopo e integridade

A igualdade exata anterior misturava integridade dos bytes congelados com resultados calculados por bibliotecas numéricas. A falha MIMO preservada de CI inclui cinco frequências geradas diferentes de um ULP e 87 folhas de respostas derivadas. O auditor reproduziu **a candidata CI completa, exatamente**, em um processo com `NPY_DISABLE_CPU_FEATURES=AVX512F,AVX2,FMA3`; desabilitar somente AVX512F também reproduziu a candidata nesta máquina. Isso confirma relevância do despacho numérico NumPy no ambiente examinado, sem atribuir uma causa universal exclusivamente a BLAS/libm.

O mesmo confronto revelou dez diferenças adicionais, de no máximo `5.551115123125783e-17`, apenas nas saídas x/u/y PVM. O adendo de escopo foi registrado pelo Maestro em PROJECT_STATE e FOLLOWUP **antes** da implementação PVM, dentro dos mesmos paths F9. Essa correção correlata impede que o mesmo laço de regeneração apenas avance de uma comparação exata frágil para outra. Não se abriu uma nova funcionalidade de controle ou simulação.

Os onze arquivos protegidos do baseline — sete fixtures ouro, manifesto de checksums, lock Pyodide, gerador e certificado ARX preexistente — mantêm seus hashes. Nenhuma matriz, valor esperado congelado ou tolerância científica foi alterada. O diff de `test_release_fixtures.py` adiciona apenas duas importações e duas seleções de certificado, sem editar os critérios dos testes científicos produção-versus-ouro.

## Revisão matemática independente

O auditor leu os helpers e a derivação em `implementation/NUMERICAL_CERTIFICATE.md`. Eles não chamam `control_lab`, SciPy, o simulador/estimador de produção ou o gerador para fabricar referências. Usam Decimal com 80 dígitos, conversão exata dos float64 e fórmulas analíticas próprias. Tipos, chaves, comprimentos e finitude são verificados antes de coerção ou normalização; uma cópia recebe somente a normalização das folhas explicitamente enumeradas para confrontar todo o restante exatamente.

Para a grade MIMO, confrontam-se zero e os 61 pontos `10^(-3+k/10)`, com endpoints, ordem, positividade e incremento logarítmico. O orçamento absoluto do expoente `gamma(3)*(3+k/10)` considera divisão, multiplicação e soma; sua exponenciação propaga-se por `w_ref*(exp(ln(10)*delta_e)-1)`, mais a hipótese explícita de precisão transcendental. Não se reutiliza `response_atol` para a frequência e não se toma o maior erro observado como limiar.

Para G/S/T/RGA, o confronto usa aritmética complexa Decimal e adjugata 2×2; `det(M)=5.5` e `abs(det((1+jw)I+M))²=w^4+26w²+132.25` afastam singularidade no domínio. O espectro de `M.T M` é reconstruído por `(57±sqrt(1313))/8`, sem eigensolver. A RGA analítica e os dois casos singulares preservados são verificados. As respostas são certificadas em sua **própria grade** e comparadas ao ouro por limites de derivadas, incluindo a variação admissível da grade. S+T, o residual declarado e todos os atols congelados permanecem verificações obrigatórias adicionais.

Os três cruzamentos são confrontados com a cúbica nominal em w², isolando três raízes distintas em intervalos disjuntos por bisseção Decimal. Ordem, completude, distância à referência, residual do polinômio e `crossing_atol` são exigidos. A documentação distingue coeficientes decimais nominais de seus valores float64 congelados e declara o envelope backward escalonado usado no confronto.

O certificado PVM separado verifica CARE/ganho da planta diagonal fixa e as soluções escalares por regimes, com referência constante, saturação ligada/desligada e C=I/C≠I. Recalcula a comutação e sua continuidade; propaga o erro do switch congelado e do argumento de exp para x, a propriedade não expansiva do clip para u e Cx para y. Confere ainda a ODE contra a derivada analítica e as equações nos valores candidatos. A referência independente de x impede que danos coordenados em x/u/y passem apenas por autoconsistência. **Somente x/u/y podem variar**: t, switch_times, parâmetros, matrizes, flags históricos PathView e metadados permanecem exatos.

Os orçamentos de dois ULPs para transcendentais e gamma de pequenas cadeias são **critérios de precisão declarados para estas fixtures condicionadas e configurações suportadas**, conforme §10.2. Não são uma garantia universal IEEE/libm/LAPACK nem um enclosure intervalar com arredondamento dirigido. Uma implementação numérica que ultrapasse o envelope deverá falhar, sem normalização para obter verde.

## Evidências de execução conferidas pelo auditor

- `reviewer/independent-focused.log`: **95 testes independentes passaram** — 51 MIMO e 44 PVM. Foram escritos por agente distinto do autor dos helpers. Cobrem candidata CI e diferenças PVM observadas; limites congelados; grade errada, endpoints/ordem; resultados incoerentes mesmo in-atol; dano coordenado S/T ou x/u/y; singularidade/rank; schemas, tipos, shapes, ordem, campos extras, proveniência, maturidade e NaN/Inf. As candidatas mudam somente em memória.
- `reviewer/*configuration.json` e `configuration_probe.py`: processos novos confirmaram kernels efetivos NumPy/SciPy via ctypes e registraram CPU features/libc/versões. Haswell e Sandybridge com despacho padrão regeneram os valores congelados; variantes sem AVX512 reproduzem a candidata MIMO CI e as dez folhas PVM diferentes. Ambos os certificados passam. São múltiplas configurações numéricas **no mesmo host**, não computadores distintos.
- `maestro/SUMMARY.json` e seis pares JSON/JUnit: o auditor abriu todos os relatórios, conferiu source hashes, testes sem failures/errors/skips, 138 casos novos MIMO/PVM em cada execução e fechamento exato dos locks. **525 testes core e 359 SDP passaram em cada uma das três configurações** Haswell, Sandybridge e Haswell com AVX512F/AVX2/FMA3 desabilitados: **2.652 execuções de teste**, não 2.652 casos distintos.
- `implementation/producer/focused.log`: produtor registra 168 testes focados aprovados, incluindo 30 preexistentes, 43 novos do produtor e 95 do auditor, na configuração que reproduz a falha CI.
- `reviewer/baseline.json`, `checks.json` e `fixtures.log`: onze hashes protegidos intactos; 11 schemas, sete fixtures e quatro exemplos validados. Os sete source hashes finais coincidem com os usados na matriz de seis execuções.

## Checklist do Apêndice E

| Item | Evidência e parecer |
| --- | --- |
| 1. Contrato e consumidores | CONFORME: APIs/RPC e consumidores F1–F8 não mudam. A comparação implementa o contrato numérico das fixtures e sua grade declarada; critérios científicos congelados continuam obrigatórios. |
| 2. Status, diagnósticos e proveniência | CONFORME: assertivas identificam estrutura, grade, fórmula, raiz, trajetória e equações inválidas; os helpers retornam resíduos e envelopes. Proveniência e parâmetros são exatos; os relatórios identificam configurações reais. |
| 3. Testes analíticos | CONFORME: grade Decimal, fórmulas 2×2, espectro fechado, identidades, raízes isoladas, ODE por regimes, CARE, clip e Cx confrontados independentemente. |
| 4. Independência | CONFORME: auditor distinto do produtor inspecionou matemática e fontes, escreveu 95 adversariais, reproduziu candidatas reais e verificou seis JSON/JUnit; não usa funções científicas de produção como oráculo. |
| 5. Ownership e ouro | CONFORME: implementação restrita a scripts e oráculos F9, com documentos de auditoria e governança explícita do adendo. Onze arquivos protegidos, gerador e tolerâncias preexistentes intactos. |
| 6. CPython/Pyodide no domínio anunciado | CONFORME: domínio é QA de regeneração das duas fixtures CPython, demonstrado em dois perfis isolados e três configurações numéricas reais. Não se infere nova capacidade Wasm ou aceite oficial PathView. |
| 7. Schema e migração | CONFORME: não há mudança de schema/API ou migração. Validação pré-coerção rejeita alteração de tipos, chaves, comprimentos, shapes/dtypes/ordem e campos fora da whitelist. |
| 8. Logs e resultados | CONFORME: baseline, sete hashes fonte, diagnósticos, candidata negativa preservada, cinco probes de configuração, logs focados e seis JSON/JUnit estão arquivados. |
| 9. Maturidade experimental | CONFORME: nenhum gate, solver, UI ou produto é promovido. Flags históricos PVM são preservados, sem fabricar uma verificação PathView nova nem modificar decisões atuais dos gates. |
| 10. Limitações e falhas | CONFORME: domínio fixo/condicionado, hipóteses transcendentais, ausência de intervalo formal e configurações no mesmo host estão declarados. Negativos rejeitam dano científico, estrutural e metadados; a execução hospedada posterior permanece obrigatória. |

## Decisão e condição de publicação

Os achados de portabilidade MIMO/logspace e o adendo PVM correlato estão resolvidos no **escopo QA das fixtures CPython** identificado acima. O Maestro pode atualizar este WorkPackage, registrar a tarefa e publicar o commit de conclusão. As tentativas negativas anteriores permanecem preservadas como evidência histórica, não devem ser reclassificadas como aprovações.

O workflow hospedado do commit final e a publicação do Pages devem ser acompanhados separadamente. Este parecer não afirma que uma execução ainda não iniciada passou, não autoriza reruns até obter verde, não amplia o envelope para problemas gerais e não altera maturidade ou gates existentes.
