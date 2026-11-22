# ADR-013 — Fronteira passiva do formato `.pvm` e exportação oficial de scripts PathSim `0.31.0` para modelos não lineares/fuzzy

Data: 2026-11-22. Decisão do coordenador e auditoria independente F9: consolidar a fronteira verificada entre exportação nativa passiva `.pvm` (PathView `0.21.0`) e geração determinística passiva de scripts executáveis **PathSim `0.31.0`** para `FuzzySystem` e `TSStateSpace + PDCController`, preservando integralmente o requisito de segurança `R-21` e o bloqueio de `ADR-006`. Estado: aceito. Esta ADR resolve integralmente `DEC-OPEN-07` (`CL-DIR-001` Seção 17).

## Decisão em duas partes (validada em PathView `0.21.0` + PathSim `0.31.0`)

A inspeção do registro oficial fixado do PathView `0.21.0` e ensaios reais ponta a ponta em `tests/unit/f1/test_dec_open_07_pathsim.py` estabelecem uma fronteira clara e definitiva:

### 1. Escopo nativo do formato passivo `.pvm` (`controllab.pathview.scalar.v1` / `clocked.v2`)

A exportação `.pvm` (`control_lab.io.make_pvm` / `export_pvm` / RPC `io.export_pvm`) cobre oficialmente todos os blocos lineares e de saturação redutíveis ao registro oficial do PathView `0.21.0`:

- Plantas `StateSpace` (contínuas e discretas de taxa única), em malha aberta ou fechada com saturação opcional;
- `StateFeedbackController` (LQR / realimentação de estados com pré-filtro opcional $N$);
- `DynamicController` contínuo ou discreto, incluindo compensadores SISO, observadores/LQG e **controladores dinâmicos MIMO $H_\infty$** sintetizados via `design_hinf_mixed_sensitivity` (`ADR-012`).

A cadeia completa `make_pvm` → `pathview.converter.generate_python` (PathView `0.21.0` sem modificações) → simulação em PathSim `0.31.0` foi validada para controlador dinâmico MIMO $H_\infty$ contra integração independente `scipy.integrate.solve_ivp` (`DOP853`, `rtol=1e-10`, `atol=1e-12`) com erro máximo `< 1e-4`.

### 2. Exclusão de sistemas não lineares/fuzzy do `.pvm` passivo e exportação oficial PathSim `0.31.0`

`FuzzySystem` (Mamdani e Takagi-Sugeno, saída simples ou múltipla), `TSStateSpace` e `PDCController` permanecem **explicitamente fora** do `.pvm` nativo (`UnsupportedModelError` em `make_pvm`, preservando a chave `unsupported_pending_dec_open_07` em `PATHVIEW_BLOCK_REGISTRY` com referência `dec_open_07_decision: "ADR-013"`).

**Justificativa de segurança (`R-21`)**: incorporar regras fuzzy, funções de pertinência arbitrárias ou interpolação não linear $h_i(x)$ dentro de um arquivo `.pvm` exigiria embutir expressões/código Python executável em `codeContext` ou parâmetros dinâmicos, violando a regra inegociável de que arquivos importados (`.pvm` / `.ctrlab`) são estritamente passivos (`code_executed=False`) e jamais executam código Python embutido.

Em substituição, a via oficial para simulação externa desses modelos passa a ser o gerador determinístico e passivo de scripts **PathSim `0.31.0`**:

- **API Python**: `control_lab.io.generate_pathsim_script(plant, controller=None, scenario=None)` (`control_lab/io/pvm.py`) retorna `Result` com `code_executed=False` e `requires_explicit_user_execution=True`, produzindo código Python autossuficiente (zero dependência de `control_lab` no script gerado):
  - Para `TSStateSpace(kind="ts_measured")` (+ `PDCController` opcional): gera `ts_pdc_rhs` e `run_pathsim_simulation` sobre `pathsim.blocks.ODE` + `RKCK54` + `Scope`, validado em PathSim `0.31.0` real contra `scipy.integrate.solve_ivp` (`max_err < 1e-4`).
  - Para `FuzzySystem` (Mamdani e TS): gera avaliador NumPy puro completo (`eval_fuzzy_point`) e `run_pathsim_simulation` sobre `Source` + `Function` + `Scope`, validado em PathSim `0.31.0` real contra `control_lab.fuzzy.evaluate` (`max_err < 1e-4` em Mamdani/TS e `< 1e-10` em multi-saída).
- **Contrato RPC**: `io.export_pathsim_script` registrado em `control_lab/core/rpc.py` (`SUPPORTED_OPERATIONS` e `core.capabilities`), validado contra `rpc_response.schema.json`, aceitando modelos inline ou por referência no store, sempre emitindo `code_executed=False`, `requires_explicit_user_execution=True` e `media_type="text/x-python"`.
- **Interface Web (Aba 5 — Fuzzy)**: botão `#btn-fuzzy-export-pathsim` (`web/features/views/fuzzy_view.ts`) conectado a `io.export_pathsim_script`, abrindo o modal passivo `#controllab-export-modal` com aviso explícito de execução manual (`ADR-013`) e download do arquivo `.py`.

## Invariantes de segurança e bloqueios preservados

1. **`R-21` preservado integralmente**: nenhum script gerado é executado durante a exportação ou importação no navegador ou no backend (`code_executed=False`, `requires_explicit_user_execution=True`).
2. **`ADR-006` preservado integralmente**: a combinação `TSStateSpace(kind="polytopic_uncertain") + PDCController` continua estritamente bloqueada com `HYPOTHESIS_VIOLATED` tanto em `make_pvm` quanto em `generate_pathsim_script` e `io.export_pathsim_script`, pois premissas incertas não medidas não podem ser escalonadas por lei PDC dependente de $h_i(x)$.
3. **Sem modificação de contratos ouro**: os schemas em `contracts/schemas/` e fixtures ouro em `contracts/fixtures/` permanecem inalterados e íntegros.
