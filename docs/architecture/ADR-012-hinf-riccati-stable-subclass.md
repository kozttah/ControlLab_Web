# ADR-012 — Subclasse estável de síntese H∞ contínua via 2-Riccati DGKF com certificação Hamiltoniana e oráculo BRL independente

Data: 2026-11-22. Decisão do coordenador e auditoria independente F9: formalizar a subclasse matemática exata de síntese $H_\infty$ por equações algébricas de Riccati (DGKF) promovida à maturidade `stable` em `design_hinf_mixed_sensitivity`, mantendo rejeição explícita para problemas fora dessa subclasse. Estado: aceito. Esta ADR resolve integralmente `DEC-OPEN-06` (`CL-DIR-001` Seção 17).

## Decisão e escopo da subclasse `stable`

A subclasse `continuous_regular_dgkf_mixed_sensitivity` entra em maturidade `stable` sob todas as hipóteses cumulativas abaixo:

1. **Domínio temporal e estrutura da planta**: sistemas LTI contínuos (`dt=None`), quadrados ($p = m \ge 1$, SISO ou MIMO), estabilizáveis e detectáveis, formulados como problema padrão de sensibilidade mista $S/KS/T$ com planta generalizada $P(s)$ mapeando $[w;\, u] \mapsto [W_S S w;\, W_U K S w;\, W_T T w;\, w - G u]$.
2. **Regularidade DGKF e filtros de ponderação**: filtros $W_S(s), W_U(s), W_T(s)$ estritamente Hurwitz ($\operatorname{Re}(\lambda) < -10^{-12}$), $D_{12}$ de posto completo por coluna ($\sigma_{\min}(D_{12}) > 10^{-12}\max(1,\sigma_{\max}(D_{12}))$, exigindo $W_U$ bipróprio com ganho não-nulo em alta frequência) e $D_{21}$ de posto completo por linha.
3. **Síntese 2-Riccati com refinamento e certificados obrigatórios**: cada solução $\gamma$-subótima de `design_hinf_mixed_sensitivity` (`control_lab/frequency/mimo/synthesis.py`) exige:
   - Soluções simétricas semidefinidas positivas $X_\infty, Y_\infty \succeq 0$ das duas equações algébricas de Riccati contínuas indefinidas (seleção entre `balanced=False/True` + refinamento de Newton-Kleinman até 2 passos), com resíduos relativos `riccati_X_residual_rel < 1e-8` e `riccati_Y_residual_rel < 1e-8` (rejeição interna acima de `1e-6`).
   - Ausência de autovalores nos Hamiltonianos $H_X, H_Y$ sobre o eixo imaginário ($\min |\operatorname{Re}(\lambda)| \ge 10^{-8}$) e condição estrita de acoplamento espectral $\rho(X_\infty Y_\infty) < \gamma^2$ com margem registrada (`coupling_margin = gamma_achieved**2 - rho_XY > 0`).
   - Estabilidade interna estrita de $(A_{cl}, G K)$ e de $T_{zw} = \mathcal{F}_\ell(P, K)$ ($\max \operatorname{Re}(\lambda) < -10^{-7}$).
   - **Prova exata do Lema Real Limitado (BRL) em toda a reta $\omega \in [0, \infty)$** via matriz Hamiltoniana $H(\gamma)$ e algoritmo Bruinsma-Steinbuch (1990) (`hamiltonian_exact_verified = True`, `hamiltonian_min_abs_real > 1e-8`, `hinf_norm_exact <= gamma_achieved`), sem depender apenas de amostragem discreta em grade.

Todos os certificados (`riccati_X_residual_rel`, `riccati_Y_residual_rel`, `rho_XY`, `coupling_margin`, `hamiltonian_exact_verified`, `hamiltonian_min_abs_real`, `hinf_norm_exact`, `stable_subclass`, `maturity`) são emitidos tanto em `Result.data` quanto em `Result.diagnostics` e expostos na Aba 4 (`web/features/views/mimo_view.ts`).

## Verificação independente (F9 — não circular)

A promoção a `stable` é respaldada pelo oráculo independente `tests/oracles/test_hinf_dgkf_oracle.py`, que **não** importa nem reutiliza rotinas internas de `synthesis.py`:

1. Reconstrói independentemente $T_{zw}(s) = [W_S S;\, W_U K S;\, W_T T]$ a partir de $(G, K, W_S, W_U, W_T)$ e valida paridade com a avaliação direta em frequência ($< 10^{-9}$) e a identidade $S(j\omega) + T(j\omega) = I$ ($< 10^{-10}$).
2. **Oráculo SDP/LMI BRL via Clarabel (`backend="clarabel_direct"`)**: formula o Lema Real Limitado para $\gamma_{\text{check}} = 1.01\,\gamma_{\text{achieved}}$, obtém `certificate_status == "validated_dual"` e remapeia a matriz certificadora $P_{\text{orig}} = L P_s L^T$ para coordenadas originais não escalonadas verificando $P_{\text{orig}} \succ 0$ e $\operatorname{BRL}(P_{\text{orig}}) \prec 0$ diretamente.
3. **Oráculo Hamiltoniano independente**: verifica $\max\operatorname{Re}(\lambda(A_{cl})) < -10^{-6}$ e ausência de autovalores no eixo imaginário em $H(\gamma_{\text{check}})$ para plantas SISO estáveis, SISO instáveis ($1/(s-1)$) e MIMO $2\times 2$ acopladas estáveis e instáveis.

## Exclusões explícitas (fora da subclasse `stable`)

Os casos abaixo permanecem explicitamente excluídos de `design_hinf_mixed_sensitivity`, com rejeição tipada (`UnsupportedModelError`, `DimensionMismatchError`, `ValidationError` ou `NumericalInconclusiveError`):

- Síntese $H_\infty$ em tempo discreto (`dt != None`);
- Plantas não quadradas ($p \ne m$);
- Problemas singulares ($D_{12}$ ou $D_{21}$ com deficiência de posto, ex.: $W_U$ estritamente própria) ou pesos com polos em $j\omega$ / semiplano direito (ex.: integradores puros em $W_S$);
- Plantas generalizadas $P(s)$ arbitrárias fora da estrutura mista $S/KS/T$ ou restrições multiobjetivo/estruturadas — casos que devem ser direcionados à formulação LMI/SDP na Aba 6 (`control_lab.optimization`, `hinf_brl_lmi` / DSL LMI v2.0, `ADR-010`).

Esta ADR promove exclusivamente a subclasse definida acima; não altera o escopo de outras frentes nem declara release global estável fora dos gates normativos.
