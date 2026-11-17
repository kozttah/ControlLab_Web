# ADR-010 — SDP nativo NumPy/SciPy e exportação offline

Decisão aprovada pelo coordenador do projeto nesta sessão. Estado aceito.

O backend padrão Pyodide é native_primal_dual, com núcleo Nesterov–Todd/Mehrotra promovido da implementação educacional. LPs estruturalmente diagonais usam scipy.optimize.linprog/HiGHS. Em CPython os backends opcionais Clarabel/CVXPY continuam suportados. O bundle base não exige wheels binários SDP adicionais.

O núcleo comum reside em optimization/backends/native_core.py. A API educacional delega ao núcleo preservando sua classificação experimental e seu histórico didático. A nova API de produção tem maturidade beta e auditoria espectral obrigatória, com as cinco dimensões de status preservadas.

O envelope denso recomendado limita 128 variáveis, dimensão máxima de bloco 48 e 16384 entradas cônicas, incluindo desigualdades. São limites operacionais iniciais para controlar memória/latência, sujeitos a medição. Acima deles, o backend recusa a execução com RESOURCE_LIMIT e recomenda execução offline. Condicionamento inadequado, auditoria inconclusiva ou certificado/gap não validado também recomendam CVXPY/YALMIP com MOSEK, Clarabel, SeDuMi ou SDPT3.

Os exportadores determinísticos geram o mesmo problema canônico, suas matrizes, igualdades, desigualdades, restrições PSD e recuperação de ganhos por sistemas lineares. A interface oferece os scripts do problema atual mesmo sem uma solução confirmada. Os scripts exportados ainda requerem validação primal/dual e de malha fechada pelo usuário ao serem executados fora do aplicativo.

G-0B passa a exigir a escada T-SDP-A1/A2/A3/B1/C1/D1/D2 no runtime Pyodide com native_primal_dual, certificados auditados e exportações sintaticamente válidas para contingências mal-condicionadas/acima do envelope. Mantém-se a matriz de dois navegadores da Seção 14.1. Uma prova em um navegador deve ser registrada como evidência parcial, sem aceite automático do gate.

Esta ADR substitui a exigência de empacotamento binário Wasm da Seção 6.2/14.1 e a exclusão do núcleo promovido de auto. O adaptador educacional permanece experimental. R-13/ADR-008 seguem aplicáveis à interface didática.
