# G-0D — confronto com o conversor oficial PathView

WorkPackage: `WP-AUDIT-FIX-F9-WASM-GATES`. Fonte normativa: CL-DIR-001 §9.3, §14.1, T-PVM-01/T-PVM-02 e Apêndice E.

Versão consultada: PathView `0.21.0`, commit upstream `4afdcc461ed63aa4231930170d20774428d51e8d`.
Os arquivos oficiais `pathview/__init__.py`, `pathview/converter.py`, `pathview/buses.py` e `pathview/data/registry.json` foram obtidos do repositório oficial e seus Git blob SHA-1 conferidos antes de importar o conversor. Os hashes completos constam em `official-converter-probe.json`.

Reprodução, com um checkout separado do upstream fixado:

```bash
git clone https://github.com/pathsim/pathview.git /tmp/pathview-official
git -C /tmp/pathview-official checkout 4afdcc461ed63aa4231930170d20774428d51e8d
python scripts/probe_pathview_official.py --upstream /tmp/pathview-official --output /tmp/pathview-result
```

Saída esperada desta revisão: código 2, indicando gate bloqueado. O script gera os quatro modelos determinísticos e usa o conversor oficial sem modificar seu registro. Os `.py.txt` são apenas resultados da conversão para inspeção; nenhuma simulação gerada foi executada.

| Caso | Conexões no PVM | Chamadas Connection emitidas | Blocos ausentes no registro oficial |
|---|---:|---:|---|
| LQR, C=I | 5 | 3 | MatrixGain |
| LQR, C≠I | 5 | 3 | MatrixGain |
| LQR com saturação | 6 | 2 | MatrixGain, Saturation |
| Controlador dinâmico | 5 | 1 | DynamicController, MatrixGain |

O conversor oficial omite blocos desconhecidos e conexões incidentes. Além disso, parâmetros como `initial_state`, `signs` e `Source.value` não pertencem aos parâmetros aceitos pelo registro oficial. A redução de chamadas Connection está documentada juntamente com os modelos completos; a realimentação não é preservada.

**Decisão: G-0D fail; `external_pathview_verified=false`.** Não houve abertura na UI oficial nem comparação de trajetórias, portanto estes requisitos continuam explicitamente não demonstrados. A incompatibilidade de blocos e parâmetros já impede declarar equivalência. A correção pertence à frente F1 (`control_lab/io/pvm.py`) e exige um WorkPackage produtor seguido de nova revisão F9; esta auditoria não altera o exportador nem as fixtures ouro.

Fontes oficiais fixadas:

- https://github.com/pathsim/pathview/blob/4afdcc461ed63aa4231930170d20774428d51e8d/pathview/converter.py
- https://github.com/pathsim/pathview/blob/4afdcc461ed63aa4231930170d20774428d51e8d/pathview/buses.py
- https://github.com/pathsim/pathview/blob/4afdcc461ed63aa4231930170d20774428d51e8d/pathview/data/registry.json
- https://github.com/pathsim/pathview/blob/4afdcc461ed63aa4231930170d20774428d51e8d/docs/pvm-spec.md
