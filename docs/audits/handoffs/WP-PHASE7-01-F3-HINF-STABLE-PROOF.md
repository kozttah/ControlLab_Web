# Handoff e Parecer F9 — `WP-PHASE7-01-F3-HINF-STABLE-PROOF`

- **WorkPackage**: `WP-PHASE7-01-F3-HINF-STABLE-PROOF`
- **Frente Produtora**: `F3 (f3-frequency)`
- **Frente Revisora / Auditoria Independente**: `F9 (f9-integration-qa)`
- **Commit Base Auditado**: `da3bf814f10324aa2dbd81583ce03c8ad14a3431`
- **Decisão Arquitetural Associada**: `docs/architecture/ADR-012-hinf-riccati-stable-subclass.md` (`DEC-OPEN-06`)
- **Veredito F9**: `accepted`
- **Data da Auditoria (UTC)**: `2026-11-22T20:22:56Z`

---

## 1. Escopo Auditado e Isolamento de Propriedade (`allowed_paths` / `CODEOWNERS`)

Todos os arquivos alterados pela Frente F3 pertencem estritamente a `allowed_paths` (`control_lab/frequency/`, `tests/unit/f3/`):

| Arquivo F3 Auditado | SHA-256 | Observações |
|---|---|---|
| `control_lab/frequency/mimo/synthesis.py` | `f124605c4509f167073f1b6ff8cf79f69e11a6174c35fce23c537a9d5aa3ffe2` | Solver 2-Riccati DGKF com seleção `balanced=False/True`, refinamento Newton-Kleinman, checagem espectral $H_X, H_Y$ e $\rho(X_\infty Y_\infty) < \gamma^2$, prova Hamiltoniana BRL exata (Bruinsma-Steinbuch 1990) e rejeição explícita fora da subclasse regular contínua. |
| `tests/unit/f3/test_mimo_synthesis_hinf.py` | `16838d7a878d647bdb1e8af6d70900b13d69b98e4a9ed71d582b988974feba5b` | Testes de certificação SISO estável, MIMO 2×2, estabilização SISO/MIMO instável, rejeições fora da subclasse (discreto, não quadrado, $D_{12}$ singular, peso integrador) e oráculos analíticos Hamiltonianos. |

### Verificação Estática de Higiene e Segurança
- Zero chamadas a `linalg.inv` em todo o pacote `control_lab/frequency/` (verificado via inspeção estática e teste `test_no_explicit_linalg_inv_in_frequency_package`; ocorrência textual na linha 163 é apenas comentário `# M = G0^{-1} via solve (sem np.linalg.inv)`).
- Zero ocorrências de `eval(` ou `exec(`.
- Zero alterações em `contracts/fixtures/*` ou `contracts/schemas/*`.

---

## 2. Evidência de Execução Independente (F9)

1. **Suíte Unitária F3 (`T-MIMO-01`)**:
   - `PATH="/home/antigravity/.venv/bin:$PATH" pytest tests/unit/f3/ -v` → **`22/22` PASSED** (`0` failed, `0` skipped).
2. **Oráculo Independente F9 (`tests/oracles/test_hinf_dgkf_oracle.py`)**:
   - Reconstrução independente de $T_{zw} = \mathcal{F}_\ell(P, K)$ sem importar helpers internos de `synthesis.py`.
   - Oráculo SDP/LMI BRL via Clarabel (`backend="clarabel_direct"`): `certificate_status == "validated_dual"` + verificação direta em coordenadas originais $P_{\text{orig}} \succ 0$ e $\operatorname{BRL}(P_{\text{orig}}) \prec 0$ para $\gamma_{\text{check}} = 1.01\,\gamma_{\text{achieved}}$.
   - Oráculo Hamiltoniano independente + estabilidade Hurwitz ($\max\operatorname{Re}(\lambda) < -10^{-6}$) + identidade $S(j\omega)+T(j\omega)=I$ ($<10^{-10}$) + paridade em frequência ($<10^{-9}$).
   - Resultado: **`4/4` PASSED** (`siso_stable`, `siso_unstable`, `mimo_2x2_coupled_stable`, `mimo_2x2_coupled_unstable`).
3. **Wasm/Pyodide Real (`tests/wasm/test_real_runtime.py`) e E2E Chromium (`tests/e2e/test_ux_refactor_cl_ux_dir_001.py`)**:
   - `4/4` Wasm PASSED; `13/13` E2E Chromium PASSED (incluindo Aba 4 síntese $H_\infty$).

---

## 3. Checklist do Apêndice E (10 Itens Obrigatórios)

| # | Item do Apêndice E | Evidência Auditada | Status |
|---|---|---|---|
| 1 | API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8? | `design_hinf_mixed_sensitivity` mantém contrato `Result<T>`, consumido via RPC `frequency.mimo.design_hinf` e exibido na Aba 4 (`web/features/views/mimo_view.ts`, `tests/unit/f8/mimo_synthesis_hinf.test.ts`). | CONFORME |
| 2 | Saída contém status, diagnósticos e proveniência, inclusive casos de falha? | `Result` retorna `status`, `diagnostics` (com todos os 9 campos de certificação Riccati/Hamiltoniana/subclasse), `assumptions`, `provenance` e `error` tipado em caso de falha (`raise_on_error=False`). | CONFORME |
| 3 | Testes analíticos foram escritos antes da otimização prematura? | Oráculos analíticos (ressonador de 2ª ordem com norma exata $1/(2\zeta\sqrt{1-\zeta^2})$ e passa-alta $s/(s+1)$ com norma $1$) verificam o BRL Hamiltoniano em `test_hamiltonian_exact_hinf_norm_analytical_oracles`. | CONFORME |
| 4 | Existe confronto independente da implementação, em vez de autorreferência? | Validado pelo oráculo F9 independente `tests/oracles/test_hinf_dgkf_oracle.py` via Clarabel BRL LMI (`validated_dual`) e Hamiltoniano reconstruído independentemente. | CONFORME |
| 5 | O PR respeita ownership e não modificou mocks/expected values para esconder defeito? | Alterações estritamente limitadas a `control_lab/frequency/mimo/synthesis.py` e `tests/unit/f3/test_mimo_synthesis_hinf.py`; `verify_fixtures.py` íntegro (11 schemas + 7/7 fixtures ouro). | CONFORME |
| 6 | O mesmo teste funciona em CPython e Pyodide no domínio anunciado? | Síntese executa com NumPy/SciPy puros em CPython (`22/22` F3, `4/4` oráculo) e no bundle wheel Pyodide Wasm (`npm --prefix web run build` + `13/13` E2E Chromium). | CONFORME |
| 7 | Alterações de schema tiveram migração/versão e revisão F9? | Nenhuma alteração destrutiva de schema; campos adicionais aditivos em `Result.data` e `Result.diagnostics` formalizados na `ADR-012`. | CONFORME |
| 8 | Logs, matrizes de fixture e resultados de benchmark foram anexados? | Evidências de execução (`22/22` F3, `4/4` Clarabel BRL oracle), SHA-256 e critérios quantitativos anexados neste handoff e na `ADR-012`. | CONFORME |
| 9 | Um método experimental permanece visualmente classificado como tal? | Apenas a subclasse regular contínua `continuous_regular_dgkf_mixed_sensitivity` com prova Hamiltoniana ativa é classificada como `stable` (`ADR-012`); métodos fora da subclasse são rejeitados. | CONFORME |
| 10 | Qualquer limitação conhecida tem issue e mensagens de falha adequadas? | Exclusões (discreto, não quadrado, $D_{12}/D_{21}$ singular, pesos não Hurwitz, $P(s)$ genérico) rejeitadas com exceções tipadas (`UnsupportedModelError`, `DimensionMismatchError`, `ValidationError`) e documentadas na `ADR-012`. | CONFORME |
