# F9 — relógio discreto síncrono no PathView oficial

WorkPackage `WP-AUDIT-FIX-F1-PVM-DISCRETE-CLOCK`, CL-DIR-001 v1.0.0, base remota `53e31974e4d56b73712629cf849de3e93bf3c537`.

## Resultado

**39/39 confrontos independentes aprovados**: 13 modelos, cada um executado com passo T, passo T/4 e passo T/4 com a ordem dos nós e conexões invertida. Cada execução cobre 24 atualizações, preserva o estado inicial e compara y, u e todos os estados da planta e do controlador. O maior erro absoluto observado foi **1,2765899448652362e-12**, com limite de valores **1e-10**. O limite não foi aumentado para acomodar resultados.

Os modelos incluem o contraexemplo escalar original, realimentação positiva, malha aberta, planta MIMO com referência retangular e C≠I/D≠0, saturação MIMO, controlador dinâmico de dois estados com Dp/Dc não nulos, realimentação de saída de ambos os sinais, realimentação de erro, duas ordens de portas [y,r]/[r,y] e controlador de estado vazio. Dois modelos adicionais conferem RK4 e a opção adaptativa do RKCK54.

O contraexemplo original agora produz `1, 0.76, 0.592, 0.4744, 0.39208, 0.334456` no PathSim oficial. A memória única `SampleHold(T,tau=T)` captura conjuntamente os desvios de todos os estados. As funções da planta e do controlador mantêm suas equações e estados completos; nenhum estado foi trocado por ganho estático ou trajetória pré-calculada.

As referências vêm de recorrências explícitas e eliminação independente dos loops algébricos. O ensaio **não** usa `simulate_pvm_graph`, o compilador numérico interno ou os callbacks exportados para gerar expected values. Uma `Scope` oficial adicional observa passivamente os registradores e as saídas já presentes no grafo, sem alterar suas equações. A comparação em T/4 verifica os valores de ambos os lados das fronteiras e o hold entre elas.

## Reprodução

```bash
python -m pip install -r scripts/requirements-pathview.lock
python scripts/audit_pvm_discrete.py
python scripts/audit_pvm_official.py --output docs/audits/pvm-discrete-clock/continuous-regression --work-package WP-AUDIT-FIX-F1-PVM-DISCRETE-CLOCK --source-base-commit 53e31974e4d56b73712629cf849de3e93bf3c537
```

O ensaio usa os pacotes oficiais **PathView 0.21.0 e PathSim 0.31.0**. Os hashes Git dos arquivos oficiais `converter.py` e `buses.py` são conferidos antes da execução. Cada tipo/parâmetro emitido é confrontado com o registro da distribuição oficial. Somente código recém-gerado dos modelos confiáveis do próprio ensaio é convertido/executado.

Os `.pvm`, Python convertido, CSVs com valores reais/referências e hashes dos três módulos produtores estão anexados. A regressão separada aprovou os oito casos contínuos anteriores e o caso discreto original; nenhuma evidência histórica em `docs/audits/pvm-official/` foi sobrescrita.

## Interface e Pyodide

O checker `scripts/check_pathview_ui.py` importou quatro arquivos congelados na UI oficial: escalar negativo, MIMO retangular, MIMO saturado e controlador dinâmico com feedthrough. Todos os nós esperados apareceram sem erros de página. Os SHA-256 dos arquivos conferem com `ui-import.json`.

Os quatro testes Wasm (dois contínuos e dois discretos) usam o wheel real reconstruído, com 64 módulos idênticos às fontes. Além da igualdade dos grafos CPython/Pyodide, os testes discretos comparam a recorrência de x/z/u/y, rejeitam a adulteração de `tau` e confirmam que `codeContext` recebido não é executado.

## Diagnóstico do próprio ensaio

O primeiro classificador de instantes adaptativos usava floor(t/T) corrigido por apenas oito ULPs. A acumulação de arredondamento dos instantes (`2,2e-15` a `5,3e-15` s perto de kT) excedeu essa correção em algumas fronteiras, causando expected values do índice anterior. A correção aplica **a mesma tolerância temporal de 1e-10 s já declarada para a grade**, somente para identificar pontos sobre kT. Os limites dos valores de estado/saída/entrada permaneceram 1e-10. Os instantes kT±T/4 continuam comparados em seus respectivos intervalos. O log inicial foi preservado; o CSV em `audit-diagnostics/` está explicitamente identificado como recomputação do classificador inicial sobre as amostras reais registradas. Isto não foi um defeito adicional do produtor.

## Limites e governança

Aceite restrito ao adaptador monofrequência demonstrado. Eventos externos personalizados e períodos incompatíveis continuam recusados com erro tipado. Não houve aprovação global de G-0A/G-0B/G-0C/G-0D, promoção do backend SDP ou alteração de `external_pathview_verified` para anunciar uma release completa.

`ownership-audit.json` comprova oito fixtures ouro, doze arquivos de oráculos, 83 arquivos de produção fora de `control_lab/io/` e 44 artefatos da evidência PathView anterior intactos. As equações da referência histórica `reference()` são idênticas por AST. A atualização no teste Wasm anterior altera somente a expectativa de capacidade discreta: em vez da antiga recusa, exige sucesso com o perfil versionado v2.
