# Handoff F9 — WP-ADR010-F6-F8-F9-NATIVE-SDP

## 1. Cabeçalho

Promoção do solver primal-dual NumPy/SciPy, templates LQR/BRL/TS e exportadores CVXPY/YALMIP sob ADR-010.

Escopo Aceite CPython e Pyodide em Chromium 153.0.8010.0 e Firefox 153.0. Envelope inicial de 128 variáveis, blocos de ordem até 48 e 16384 entradas cônicas. MATLAB/YALMIP foi validado por montagem canônica e inspeção estrutural do código gerado. Não havia runtime MATLAB/YALMIP nesta sessão, portanto o .m não foi executado. O script CVXPY foi executado com Clarabel, incluindo recuperação de ganho e desigualdade de malha fechada. A governança permite beta auditado com limites explícitos. A liberação global depende dos demais gates existentes.. Fonte CL-DIR-001 com decisões explícitas ADR-009/ADR-010 do coordenador. Execução F6/F8/F9 sequencial no contexto principal por instrução da sessão Codex.

## 2. Contratos e implementação

Comandos de aceite pytest, npm --prefix web test e python3 scripts/project_governance.py. O pytest usa --import-mode=importlib para coletar os dois testes preexistentes de mesmo basename. Assets e wheel reais são verificados pelo harness de navegador. Os logs registram um aviso de depreciação anyio/pytest, sem erros ou skips. Os scripts são exportados do problema atual e não exigem commit de resultado LQR. Fontes auditadas identificadas por SHA-256 no artefato da entrega.

## 3. Checklist do Apêndice E

| Item | Evidência |
| --- | --- |
| 1 | RPC versionado e capacidades reais incluem optimization.export_cvxpy/yalmip e native_primal_dual. A integração mínima ajusta o dispatcher F1 e o anúncio do Worker F7 para viabilizar F6/F8. |
| 2 | Result preserva as cinco dimensões, status de condicionamento e diagnósticos de contingência offline. |
| 3 | Escada A1/A2/A3/B1/C1/D1/D2, LQR-LMI e TS/PDC 4 estados/3 regras têm testes locais e/ou Wasm em tests/unit/f6/test_native_sdp_and_exports.py e tests/wasm/test_real_runtime.py. |
| 4 | Verificador espectral fora do solver reconstitui primal, dual e gap. Exportação CVXPY confrontada com solver dedicado, e LQR-LMI confrontada com desigualdade analítica. |
| 5 | Nenhuma alteração em contracts/fixtures/ ou tests/oracles/. Expectativas de backend nos testes de consumidores foram atualizadas pela mudança explícita ADR-010. |
| 6 | Runtime real Pyodide em Chromium e Firefox passou a escada e as contingências. Mesmo hash de release nos dois relatórios g0b-*.json. |
| 7 | Campos de governança aditivos e duas operações RPC aditivas. API educacional preservada por adaptador ao núcleo comum. |
| 8 | Logs integrais pytest/npm/build/Firefox e hashes de fontes em docs/audits/adr009-010. 359 Python, 51 web, 4 Firefox e 97 perfil CPython sem Clarabel aprovados. |
| 9 | API educacional mantém experimental. Backend nativo e UI usam beta, com auditoria obrigatória e envelope explícito. |
| 10 | Limites de dimensão/condicionamento/gap produzem recomendação CVXPY/YALMIP. Ausência de runtime MATLAB registrada. Outros gates de release seguem independentes. |

## 4. Evidências e limites

Aceite CPython e Pyodide em Chromium 153.0.8010.0 e Firefox 153.0. Envelope inicial de 128 variáveis, blocos de ordem até 48 e 16384 entradas cônicas. MATLAB/YALMIP foi validado por montagem canônica e inspeção estrutural do código gerado. Não havia runtime MATLAB/YALMIP nesta sessão, portanto o .m não foi executado. O script CVXPY foi executado com Clarabel, incluindo recuperação de ganho e desigualdade de malha fechada. A governança permite beta auditado com limites explícitos. A liberação global depende dos demais gates existentes.

## 5. Parecer F9

- Revisor independente: verificação F9 sequencial no contexto principal, conforme instrução explícita da sessão. A independência numérica reside no verificador espectral separado do solver.
- Commit SHA auditado (base): 3ce128a6d8a18ad1eeb18ee83b666df6708d30d0, acrescido do diff ADR-009/010 desta entrega.
- Data (UTC): 2026-11-17
- Parecer F9: accepted
