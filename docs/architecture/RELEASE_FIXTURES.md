# Fixtures independentes da entrega F9 BUILD-CI

Fonte normativa única: `ControlLab_Web_Documento_Diretor_v1.0.md` (CL-DIR-001), §§10.2, 10.4, 13.11 e 15; Apêndices C/E. Entrega do produtor F9 para revisão independente, sem decisão de aceite do próprio produtor.

## Reproduzir e verificar

Referência de geração: CPython **3.12.14**, NumPy **2.3.5**, SciPy **1.17.0**, CPU Linux IEEE-754 binary64. O gerador exige essas versões; não usa relógio, UUID, rede, nem importa `control_lab`. Matrizes e sinais completos são persistidos: nenhuma fixture depende somente de semente. Os valores de referência são CPython; estes arquivos não atestam paridade Pyodide/Wasm.

```bash
python scripts/generate_release_fixtures.py
python scripts/verify_fixtures.py
pytest tests/oracles/test_release_fixtures.py tests/oracles/test_golden_fixtures.py -v
```

`generate_release_fixtures.py` escreve **somente as quatro fixtures novas e o manifesto**. Antes de gravar, exige os SHA-256 originais das três anteriores. O manifesto preserva suas linhas originais e acrescenta as quatro novas. O gerador histórico `generate_golden_fixtures.py` continua sendo fonte histórica das três antigas e não é o comando de regeneração desta entrega: não deve ser executado para regravar ouro certificado. Não foi alterado. A revisão independente deve aprovar qualquer mudança de expected, versões ou tolerâncias antes de nova certificação.

`verify_fixtures.py` exige os sete nomes, rejeita entradas duplicadas, extras, faltantes, hashes divergentes e JSON fora do manifesto; verifica os schemas e exemplos existentes. Nenhum schema foi alterado.

## Oráculos e hipóteses

| Fixture | Construção independente e dados completos | Confronto de produção |
|---|---|---|
| B-DARE-12x3 | Matrizes contínuas da B-CARE-12x3 preservada. ZOH exato com `ts=0.05 s`, `Ad=exp(Ac ts)`, `Bd=∫exp(Ac s)Bc ds`. SciPy `cont2discrete` confrontado com `quad_vec` + `expm`. DARE por `solve_discrete_are`, ganho por sistema linear e resíduo calculado explicitamente. Q/R são pesos por amostra, sem alegar discretização do custo contínuo. | `discretize_zoh`, `solve_dare`; matriz, P/K, simetria, SPD, resíduo, espectro e estabilidade. Também `solve_care` contra B-CARE-12x3 original (T-CARE-02). |
| B-ARX-PRBS | 768 amostras, dt=0.1 s, ordem (na,nb,nk)=(2,2,1), `y[k]-.9y[k-1]+.2y[k-2]=.7u[k-1]+.15u[k-2]+e[k]`. PRBS LFSR 10 bits `x^10+x^3+1`, estado inicial de uns. Ruído de equação PCG64 seed 20261114, branco normal, primeiras duas inovações zero, filtrado por 1/A; escala para SNR de saída exatamente 35 dB. u/y/t, y sem ruído e todas as inovações armazenados. Treino [0,512), validação [512,768), sem sobreposição. | `fit_arx` contra LAPACK `gelsd` independente da QR produtora. Coeficientes plantados/estimados, posto 4, PE, polos, predição de um passo e simulação livre comparados com sequências e FIT ouro de treino/holdout (T-ID-03). |
| B-MIMO-2x2 | `G(s)=M/(s+1)`, M=[[2,1],[.5,3]], 62 frequências explícitas: DC e 61 pontos log de 10^-3 a 10^3 rad/s. RGA exata [[12/11,-1/11],[-1/11,12/11]]. Valores singulares por raízes dos autovalores de MᵀM, divididos por sqrt(1+w²). S/T por adjugata 2×2 explícita de `(1+jw)I+M`. Dois casos singulares separados (posto 1 e zero). | Resposta, todos os valores singulares, cada RGA e suas somas, S/T e identidade sobre a grade toda (T-MIMO-01). Singularidade deve retornar undefined com diagnóstico (T-MIMO-02). |
| B-PVM-LQR | A=diag(-1,-2), B=I, R=I, Q=diag(3,5); solução CARE exata P=I/K=I. Quatro casos: C=I e C=[1,2] (m=2≠p=1), cada qual com saturação desligada/ligada em ±0.2. N/r dimensionalmente explícitos; x0=[1,-.5], 81 tempos de 0 a 4 s. Trajetórias x/u/y e instantes de transição por exponenciais analíticas, sem simulador numérico. | Síntese LQR, exportador local, porta de estado completo e simulador interno comparados ao ouro, nunca a outro wrapper do próprio simulador (T-PVM-01, escopo local). |

No ARX, o FIT exclui as primeiras duas amostras de cada partição; essas amostras medidas inicializam a recorrência de simulação livre e o preditor. Denominador: norma de y menos sua média na região efetivamente avaliada. O ruído está na equação ARX, logo o ruído de saída é colorido por 1/A. O treino estima os quatro parâmetros uma vez; a validação nunca participa dessa estimação. Os polos do gerador são 0.4/0.5.

A fixture MIMO inclui ainda T-FREQ-02: TF auxiliar `11(s+1)/[(s+.1)(s²+.2s+100)]`. As três travessias de ganho são raízes positivas de `(z+.01)[(100-z)²+.04z]-121(z+1)=0`, z=w², aproximadamente 0.0461112036, 9.4393520020 e 10.5283668030 rad/s. O teste compara todas as três travessias produzidas e confere |G|=1 independentemente. Esse caso não muda o significado de RGA MIMO.

## Derivação PVM e convenções de sinais

Em todos os casos `feedback_sign=negative`: `u_raw=N r-Kx`; `xdot=A x+B u`; `y=Cx+Du`. N tem m linhas e p_ref colunas; r tem p_ref componentes. O controlador recebe x completo pela porta de estado, inclusive quando C tem apenas uma linha. Portanto C≠I e m≠p não autorizam substituir x por y.

Para cada canal, v=(Nr)i, ai∈{-1,-2}, Kii=1. Sem saturação, `xeq=v/(1-ai)` e `xi(t)=xeq+(xi0-xeq)exp[(ai-1)t]`. Com saturação inicial `us=clip(v-xi0)`, a primeira fase é `xs=-us/ai`, `xi(t)=xs+(xi0-xs)exp(ai t)`. A transição ocorre em `xi=v-us`, no instante `log[(v-us-xs)/(xi0-xs)]/ai`. Depois segue a solução sem saturação, contínua no instante de transição. Todos os casos selecionados entram no regime linear e permanecem nele; os tempos estão na fixture. `u=clip(v-x)` e y=Cx são avaliados diretamente sobre essa solução exata.

Esta prova é do **oráculo e simulador locais**. `external_pathview_verified=false` e `PENDING_G0D` são obrigatórios. Não foi aberto o aplicativo oficial, não se aprovou seu formato real, geração externa de Python, nem dinâmica do PathView oficial. T-PVM-02/controlador dinâmico e aceite externo ficam no WP-AUDIT-FIX-F9-WASM-GATES/G-0D.

## Tolerâncias e evidência numérica

Tolerâncias originais das três fixtures existentes permanecem intactas. As novas matrizes bem condicionadas usam binary64: erro absoluto 10^-12 para ZOH; erro relativo 10^-7 para P/K; resíduo DARE máximo 10^-9; identidade MIMO/resposta 10^-11; coeficientes ARX 10^-10 (comparação entre soluções LS do mesmo problema), predições 10^-9 e FIT 10^-8 ponto percentual. Erro do coeficiente estimado contra o plantado permite 0.03, explicitamente distinto da paridade LS, por existir ruído. A tolerância PVM 2×10^-8 inclui integração numérica local e transições de saturação; o ouro é analítico. São limiares por fixture, não limites universais; mudanças de BLAS/CPU podem variar últimos bits, sem exigir igualdade bit a bit de produção recalculada.

Resultados nesta referência: rDARE=2.48699×10^-15, rho(A−BK)=0.9816642869, erro máximo Bd/quadratura=1.38778×10^-17. ARX FIT treino: 98.78430456% (um passo), 98.23692408% (livre); holdout: 98.85678636% e 98.19240256%, posto 4. Testes do produtor: **26 passed** (14 novos + 12 anteriores), nenhum skip/xfail; schema/hash: sete fixtures válidas. O aviso do plugin anyio/pytest é de depreciação e não altera resultado. A revisão F9 separada deve confirmar essas evidências, escopo e tolerâncias.

## Checklist de handoff do Apêndice E

| Item | Evidência / limite |
|---|---|
| 1. API/contratos | Schema golden v1.0.0 existente e APIs canônicas exercitados; sete fixtures disponíveis aos consumidores. |
| 2. Status/diagnósticos/proveniência | Casos positivos exigem success/warning e proveniência; RGA singular exige inconclusive/undefined com diagnóstico; PVM conserva gate externo pendente. |
| 3. Analíticos | RGA/adjugata, polinômio de cruzamentos, ARX plantado e PVM exponencial explícitos, anteriores a qualquer otimização. |
| 4. Independência | Gerador sem importação control_lab; SciPy/álgebra/recorrências independentes, testes de produção consomem ouro congelado. |
| 5. Ownership | Somente quatro novas gold, manifesto, novo gerador, verifier, oráculos F9 e esta documentação; três gold e tolerâncias antigas preservadas. |
| 6. CPython/Pyodide | CPython comprovado; Pyodide/Wasm não executado. Não implica Done de algoritmo nem liberação stable Web. |
| 7. Schema/migração | Nenhum schema ou versão de contrato alterado. |
| 8. Evidências | Matrizes/sinais/resíduos/FIT completos nas fixtures; comandos e métricas acima, hashes no manifesto. |
| 9. Maturidade | Oráculos locais somente; não promove método experimental nem exporter para stable. |
| 10. Limitações | AUD-011 e G-0D permanecem; Wasm/paridade e aceite oficial PathView seguem WP-AUDIT-FIX-F9-WASM-GATES. Decisão final reservada ao auditor independente. |
