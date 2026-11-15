# Validação independente do adaptador PathView oficial

WorkPackage: `WP-AUDIT-FIX-F1-PVM-OFFICIAL`. Normas: CL-DIR-001 §9.3, T-PVM-01, T-PVM-02, T-IO-01/02 e checklist do Apêndice E.

## Reprodução

```bash
python -m venv /tmp/controllab-pathview-audit
/tmp/controllab-pathview-audit/bin/python -m pip install -r scripts/requirements-pathview.lock
/tmp/controllab-pathview-audit/bin/python scripts/audit_pvm_official.py --output /tmp/pvm-audit-result
```

Opcionalmente, `--upstream /caminho/pathview` compara o subconjunto do registro usado com um checkout oficial no commit `4afdcc461ed63aa4231930170d20774428d51e8d`; `--wheels /caminho/wheels` registra hashes dos wheels de dependências baixados.

O script exige PathView 0.21.0 e PathSim 0.31.0 e confere os hashes Git dos fontes oficiais `converter.py` e `buses.py` antes do ensaio. O registro do wheel PathView difere do registro do commit fixado apenas no parâmetro `carrier` de `Splitter`, bloco não usado pelo exportador. Todos os blocos efetivamente emitidos foram comparados ao registro upstream no ensaio registrado.

## Independência científica

O conversor oficial produz Python a partir de arquivos `.pvm` recém-gerados pela suíte; esse Python é executado pelo PathSim real, sem alterar o registro nem substituir blocos. Nenhum `.pvm` de terceiros é executado. A referência não chama `extract_lti_from_pvm`, `simulate_pvm_graph` ou o compilador interno ControlLab: usa equações explícitas, resolução independente do loop algébrico e integração SciPy com tolerâncias `rtol=1e-11`, `atol=1e-12` e passo máximo 0,001 s. O ensaio PathSim usa o solver emitido `RKCK54`, com passo fixo 0,001 s e 501 amostras por caso contínuo. O limite independente `2e-6` desta nova comparação não altera nenhuma tolerância científica existente.

Oito casos contínuos cobrem realimentação positiva/negativa, C=I e C≠I, D≠0, mapa de referência retangular e planta MIMO, saturação com a mesma não linearidade na referência, controlador dinâmico com Dp/Dc não nulos e estado inicial próprio, e controlador com zero estados. Além das saídas, são comparados os estados finais da planta e do controlador dinâmico quando presentes. Os `.csv` contêm tempo, saídas externas e saídas de referência; os `.pvm` registram todas as matrizes e as conexões; os `.py.txt` preservam o código emitido pelo conversor oficial.

## Contraevidência discreta preservada

`discrete-pre-fix/` e `trajectory-assay-initial.json` preservam a falha observada na primeira versão candidata. Para A=0,8, B=0,2, K=0,5, referência 0,3 e x0=1, a recorrência correta é `x[k+1]=0,7x[k]+0,06`. O grafo discreto emitido produziu y(0,1)=0,86, enquanto a referência exige 0,76: erro absoluto 0,1. A ordem dos eventos do `DiscreteStateSpace` externo não preservou a atualização simultânea da malha ControlLab.

A correção adotada recusa exportação oficial discreta com `UNSUPPORTED_MODEL` e razão `discrete_schedule_mismatch`; o perfil explícito `legacy_numeric` permanece apenas para migração e simulação passiva interna, com `external_compatible=false`. O último item de `trajectory-assay.json` testa essa recusa honesta. Seu `passed=true` indica que a restrição foi aplicada; **não indica equivalência discreta validada**. Uma futura implementação discreta exige novo ensaio independente.

## Evidências e limites

- `trajectory-assay.json`: versões, hashes de fontes/dependências, erros máximos e decisões de cada caso.
- `ownership-audit.json`: preservação de fixtures, oráculos e produção de outras frentes.
- Os testes oficiais de UI e Pyodide, executados separadamente pelo Maestro, têm seus próprios relatórios.

O aceite deste WorkPackage trata da correção produtora dentro do escopo contínuo demonstrado. Não promove automaticamente o gate global G-0D, cujos pré-requisitos de integração e persistência continuam sujeitos à F9, nem altera o bloqueio SDP G-0B.
