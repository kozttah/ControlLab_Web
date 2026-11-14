"""Núcleo de Identificação de Sistemas — Frente F4 (CL-DIR-001 Seções 5.2, 10.2, 10.4, 13.6 e R-06).

Reexporta a API pública de identificação:
- `fit_arx`, `select_arx_order`: Identificação ARX por fatoração QR/SVD;
- `fit_oe`: Identificação Output-Error via Gauss-Newton / Trust-Region inicializada por ARX/IV;
- `fit_subspace`: Identificação por subespaços (MOESP / N4SID) via projeção LQ e SVD de Hankel;
- `predict`, `simulate`: Previsão de 1 passo à frente (`one_step_prediction`) e simulação livre (`free_simulation`);
- `compute_fit_percent`, `analyze_residuals`, `compute_information_criteria`, `validate_model`:
  Métricas FIT%, RMSE, AIC/BIC/FPE, análise estatística de resíduos com bandas de 95%/99% e validação holdout;
- `publish_identified_model`: Publicação para `TransferFunction` e `StateSpace` canônicos (R-06);
- `generate_prbs`, `check_persistence_of_excitation`, `preprocess_dataset`, `split_dataset`:
  Sinais PRBS determinísticos, diagnóstico de Persistência de Excitação (PE) e pré-processamento explícito.
"""

from control_lab.core.models import Dataset, IdentifiedModel, StateSpace, TransferFunction

from .arx import fit_arx, select_arx_order
from .oe import fit_oe
from .preprocessing import (
    DEFAULT_COND_WARN_THRESHOLD,
    DEFAULT_RANK_RTOL,
    check_persistence_of_excitation,
    generate_prbs,
    preprocess_dataset,
    resolve_dataset_inputs,
    split_dataset,
)
from .subspace import fit_subspace
from .validation import (
    analyze_residuals,
    compute_fit_percent,
    compute_information_criteria,
    predict,
    publish_identified_model,
    simulate,
    validate_model,
)

__all__ = [
    "DEFAULT_COND_WARN_THRESHOLD",
    "DEFAULT_RANK_RTOL",
    "Dataset",
    "IdentifiedModel",
    "StateSpace",
    "TransferFunction",
    "analyze_residuals",
    "check_persistence_of_excitation",
    "compute_fit_percent",
    "compute_information_criteria",
    "fit_arx",
    "fit_oe",
    "fit_subspace",
    "generate_prbs",
    "predict",
    "preprocess_dataset",
    "publish_identified_model",
    "resolve_dataset_inputs",
    "select_arx_order",
    "simulate",
    "split_dataset",
    "validate_model",
]
