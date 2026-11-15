"""Exportação, importação passiva e avaliador estrutural `.pvm` v1.0.0 para PathView.

Normas (CL-DIR-001 Seções 9.3, 10.4, 12.2, 13.3, Apêndice D e Gate G-0D):
- Importação 100% passiva: nunca executa `codeContext.code`, `eval`, `exec` nem expressões
  Python em `params`.
- Registro oficial fixado e lowering escalar (`pvm_official`), com status transparente
  `external_pathview_verified: False` até validação externa em Gate G-0D.
- Topologia explícita sem fan-in proibido, com exposição de `x` para realimentação de
  estados quando `C != I`, `Adder` com sinais explícitos para `feedback_sign`,
  produto matricial `Function` para `K`/`N`, `Clip` opcional e controlador dinâmico
  completo em `StateSpace` oficial (nunca colapsado em ganho estático).
- `MatrixGain`, `DynamicController` e `Saturation` são somente a representação
  numérica legada interna. A saída oficial usa Source/StateSpace/Function/Adder/Clip/Scope
  e portas escalares; o adaptador valida parâmetros e conexões antes de reagrupá-los.
- `extract_lti_from_pvm` e `simulate_pvm_graph` usam essa projeção numérica validada,
  sem avaliar expressões importadas, e resolvem loops com `np.linalg.solve` (nunca `inv`).
- A exportação oficial discreta é recusada até correção independente do relógio
  de DiscreteStateSpace. O perfil explícito legacy_numeric serve apenas ao avaliador
  interno e nunca é apresentado como exportação PathView compatível.
"""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import scipy.integrate

from control_lab.core.controllers import (
    DynamicController,
    PDCController,
    StateFeedbackController,
)
from control_lab.core.interconnect import validate_interconnection
from control_lab.core.models import FuzzySystem, StateSpace, TSStateSpace
from control_lab.core.tensors import (
    check_dt_compatible,
    ensure_finite_float64,
    tensor_to_array,
    validate_non_empty_str,
)
from control_lab.diagnostics import (
    ControlLabError,
    DimensionMismatchError,
    HypothesisViolatedError,
    ImportUntrustedCodeError,
    NumericalInconclusiveError,
    Provenance,
    Result,
    SchemaUnsupportedError,
    UnsupportedModelError,
    ValidationError,
    WarningItem,
    build_provenance,
    ensure_json_finite,
    strict_json_dumps,
    strict_json_loads,
)
from control_lab.statespace.simulation import simulate_lti
from control_lab.io.pvm_official import (
    OFFICIAL_PARAMS, PATHVIEW_COMMIT, lower_to_official, restore_numeric_projection,
)

PATHVIEW_SPEC_VERSION: str = "1.0.0"
DEFAULT_PVM_TIMESTAMP: str = "2026-11-13T00:00:00Z"
DEFAULT_MAX_PVM_BYTES: int = 32 * 1024 * 1024

_PVM_ROOT_KEYS = frozenset(
    {"version", "metadata", "graph", "events", "codeContext", "simulationSettings"}
)
_SIM_SETTINGS_REQUIRED_KEYS = frozenset(
    {
        "duration",
        "dt",
        "solver",
        "adaptive",
        "atol",
        "rtol",
        "ftol",
        "dt_min",
        "dt_max",
        "ghostTraces",
        "plotResults",
    }
)
_NUMERIC_PARAM_KEYS = frozenset(
    {"A", "B", "C", "D", "Ac", "Bc", "Cc", "Dc", "gain", "initial_state", "u_min", "u_max", "value", "func", "initial_value", "min_val", "max_val"}
)

# Official constructor ABI pinned separately from the .pvm document version.
# Legacy numeric graphs are still accepted by the passive importer/evaluator;
# all new exports use official scalar channels via the versioned adapter.
PATHVIEW_BLOCK_REGISTRY: dict[str, Any] = {
    "spec_version": PATHVIEW_SPEC_VERSION,
    "pathview_version": "0.21.0",
    "pathview_commit": PATHVIEW_COMMIT,
    "adapter_version": "controllab.pathview.scalar.v1",
    "supported_external_domains": ["continuous"],
    "discrete_external_status": "unavailable_pending_clock_alignment",
    "external_pathview_verified": False,
    "gate_status": "PENDING_G0D",
    "blocks": {
        name: {"params": params, "external_verified": False}
        for name, params in OFFICIAL_PARAMS.items()
    },
    "unsupported_pending_dec_open_07": ["PDCController", "FuzzySystem", "TSStateSpace"],
}


def _is_real_number(val: Any) -> bool:
    return (
        isinstance(val, (int, float, np.integer, np.floating))
        and not isinstance(val, (bool, np.bool_))
        and math.isfinite(float(val))
    )


def _is_non_neg_int(val: Any) -> bool:
    return isinstance(val, (int, np.integer)) and not isinstance(val, (bool, np.bool_)) and int(val) >= 0


def _port(node_id: str, direction: str, index: int, name: str) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "direction": direction,
        "index": int(index),
        "name": name,
    }


def _format_np_array_code(var_name: str, arr: np.ndarray) -> str:
    arr64 = np.asarray(arr, dtype=np.float64)
    if arr64.ndim == 1:
        elems = ", ".join(repr(float(v)) for v in arr64.tolist())
        return f"{var_name} = np.array([{elems}], dtype=np.float64)"
    if arr64.ndim == 2:
        rows_s: list[str] = []
        for row in arr64.tolist():
            elems = ", ".join(repr(float(v)) for v in row)
            rows_s.append(f"[{elems}]")
        joined = ", ".join(rows_s)
        return f"{var_name} = np.array([{joined}], dtype=np.float64)"
    return f"{var_name} = np.array({arr64.tolist()!r}, dtype=np.float64)"


def _safe_strict_json_loads(raw: str | bytes | bytearray | memoryview, *, context: str = ".pvm") -> Any:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(
                message=f"Conteúdo {context} não é UTF-8 válido: {exc}",
                parameters={"context": context},
            ) from exc
        return strict_json_loads(text)
    return strict_json_loads(raw)


def _coerce_numeric_input(val: Any, *, ndim: int | None = None, name: str = "array") -> np.ndarray:
    if isinstance(val, Mapping) and {"shape", "dtype", "data"}.issubset(val.keys()):
        return tensor_to_array(val, expected_ndim=ndim, dtype="float64")
    return ensure_finite_float64(val, ndim=ndim, name=name)


def _parse_saturation_spec(
    scenario: Mapping[str, Any] | None,
    m: int,
) -> dict[str, Any] | None:
    if scenario is None or "saturation" not in scenario or scenario["saturation"] is None:
        return None
    raw_sat = scenario["saturation"]
    if not isinstance(raw_sat, Mapping):
        raise ValidationError("scenario['saturation'] deve ser um Mapping ou None.")

    enabled = raw_sat.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValidationError("scenario['saturation']['enabled'] deve ser booleano.")

    def _resolve_bound(keys: tuple[str, ...], default_scalar: float, label: str) -> np.ndarray:
        raw_val = None
        for k in keys:
            if k in raw_sat and raw_sat[k] is not None:
                raw_val = raw_sat[k]
                break
        if raw_val is None:
            return np.full((m,), default_scalar, dtype=np.float64)
        if _is_real_number(raw_val):
            return np.full((m,), float(raw_val), dtype=np.float64)
        vec = _coerce_numeric_input(raw_val, name=label)
        if vec.ndim == 2 and vec.shape in ((m, 1), (1, m)):
            vec = vec.reshape((m,))
        if vec.ndim != 1 or vec.shape != (m,):
            raise DimensionMismatchError(
                f"Limite de saturação {label} tem shape {vec.shape}, esperado ({m},)."
            )
        return vec

    u_min = _resolve_bound(("u_min", "min", "lower"), -1e6, "u_min")
    u_max = _resolve_bound(("u_max", "max", "upper"), 1e6, "u_max")
    if np.any(u_min > u_max):
        raise ValidationError(
            message="Limites de saturação inválidos: u_min deve ser <= u_max em todos os canais.",
            parameters={"u_min": u_min.tolist(), "u_max": u_max.tolist()},
        )
    return {
        "enabled": enabled,
        "u_min": [float(v) for v in u_min.tolist()],
        "u_max": [float(v) for v in u_max.tolist()],
    }


def _resolve_initial_state(scenario: Mapping[str, Any] | None, n: int) -> list[float]:
    if scenario is None:
        return [0.0] * n
    raw_x0 = scenario.get("initial_state", scenario.get("x0"))
    if raw_x0 is None:
        return [0.0] * n
    arr = _coerce_numeric_input(raw_x0, name="scenario.initial_state")
    if arr.ndim == 2 and arr.shape in ((n, 1), (1, n)):
        arr = arr.reshape((n,))
    elif arr.ndim != 1:
        raise DimensionMismatchError(
            f"scenario.initial_state deve ser 1D de tamanho {n}, recebido shape={arr.shape}."
        )
    if arr.shape != (n,):
        raise DimensionMismatchError(
            f"scenario.initial_state tem comprimento {arr.shape[0]}, esperado {n}."
        )
    return [float(v) for v in arr.tolist()]


def _resolve_reference_signal_spec(
    scenario: Mapping[str, Any] | None,
    dim: int,
    default_names: Sequence[str],
) -> dict[str, Any]:
    ref_cfg = scenario.get("reference") if scenario is not None else None
    if ref_cfg is not None and not isinstance(ref_cfg, Mapping):
        raise ValidationError("scenario['reference'] deve ser um Mapping.")
    sig_type = "step"
    raw_val: Any = None
    names = list(default_names)
    if isinstance(ref_cfg, Mapping):
        if "type" in ref_cfg and ref_cfg["type"] is not None:
            sig_type = str(ref_cfg["type"])
        if "value" in ref_cfg:
            raw_val = ref_cfg["value"]
        if "names" in ref_cfg and ref_cfg["names"] is not None:
            names = [str(x) for x in ref_cfg["names"]]

    if raw_val is None:
        val_vec = np.zeros((dim,), dtype=np.float64) if sig_type == "zero" else np.ones((dim,), dtype=np.float64)
    elif _is_real_number(raw_val):
        val_vec = np.full((dim,), float(raw_val), dtype=np.float64)
    else:
        val_vec = _coerce_numeric_input(raw_val, name="scenario.reference.value")
        if val_vec.ndim == 2 and val_vec.shape in ((dim, 1), (1, dim)):
            val_vec = val_vec.reshape((dim,))
        if val_vec.ndim != 1 or val_vec.shape != (dim,):
            raise DimensionMismatchError(
                f"scenario.reference.value tem shape {val_vec.shape}, esperado ({dim},)."
            )

    return {
        "dim": int(dim),
        "signal_type": sig_type,
        "value": [float(v) for v in val_vec.tolist()],
        "channel_names": names,
    }


def _validate_sim_number_or_str(
    val: Any,
    *,
    key: str,
    allow_empty: bool = False,
) -> tuple[str, float | None]:
    if isinstance(val, (bool, np.bool_)) or not isinstance(val, (str, int, float, np.integer, np.floating)):
        raise ValidationError(
            f"simulationSettings.{key} deve ser string numérica ou número finito, recebido {type(val).__name__}."
        )
    if isinstance(val, str):
        stripped = val.strip()
        if stripped == "":
            if allow_empty:
                return "", None
            raise ValidationError(f"simulationSettings.{key} não pode ser vazio.")
        if "\n" in val or "\r" in val:
            raise ValidationError(f"simulationSettings.{key} contém quebra de linha inválida.")
        try:
            num = float(stripped)
        except ValueError as exc:
            raise ValidationError(
                f"simulationSettings.{key} deve representar número finito válido, recebido {val!r}."
            ) from exc
        if not math.isfinite(num) or num <= 0.0:
            raise ValidationError(
                f"simulationSettings.{key} deve ser finito e > 0, recebido {val!r}."
            )
        return stripped, num

    num = float(val)
    if not math.isfinite(num) or num <= 0.0:
        raise ValidationError(f"simulationSettings.{key} deve ser finito e > 0, recebido {val!r}.")
    return str(num), num


def _build_simulation_settings(
    plant: StateSpace,
    scenario: Mapping[str, Any] | None,
) -> dict[str, Any]:
    sc = dict(scenario) if scenario is not None else {}
    sim_override = sc.get("simulationSettings")
    if sim_override is not None and not isinstance(sim_override, Mapping):
        raise ValidationError("scenario['simulationSettings'] deve ser Mapping.")
    ov = dict(sim_override) if sim_override is not None else {}

    def _pick(key: str, default: Any) -> Any:
        if key in ov:
            return ov[key]
        if key in sc:
            return sc[key]
        return default

    is_disc = plant.dt is not None
    default_dt = str(plant.dt) if is_disc else "0.01"
    default_solver = "Discrete" if is_disc else "RKCK54"
    default_adaptive = not is_disc

    dt_str, dt_num = _validate_sim_number_or_str(_pick("dt", default_dt), key="dt", allow_empty=False)
    assert dt_num is not None
    if is_disc:
        if not math.isclose(dt_num, float(plant.dt), rel_tol=1e-12, abs_tol=1e-15):
            raise DimensionMismatchError(
                f"simulationSettings.dt ({dt_str}) incompatível com plant.dt ({plant.dt})."
            )

    duration_str, _ = _validate_sim_number_or_str(_pick("duration", "10"), key="duration")
    atol_str, _ = _validate_sim_number_or_str(_pick("atol", "1e-6"), key="atol")
    rtol_str, _ = _validate_sim_number_or_str(_pick("rtol", "1e-4"), key="rtol")
    ftol_str, _ = _validate_sim_number_or_str(_pick("ftol", "1e-9"), key="ftol")
    dt_min_str, _ = _validate_sim_number_or_str(_pick("dt_min", ""), key="dt_min", allow_empty=True)
    dt_max_str, _ = _validate_sim_number_or_str(_pick("dt_max", ""), key="dt_max", allow_empty=True)

    raw_solver = _pick("solver", default_solver)
    if not isinstance(raw_solver, str) or not raw_solver.strip():
        raise ValidationError(f"simulationSettings.solver deve ser string não vazia, recebido {raw_solver!r}.")

    # The upstream converter interpolates this token into a Python import;
    # only real, pinned PathSim solver classes may cross the export boundary.
    supported_solvers = {
        "RKCK54", "RK4", "RKBS32", "RKDP54", "RKDP87", "RKF21", "RKF45", "RKF78", "RKV65",
        "SSPRK22", "SSPRK33", "SSPRK34", "EUF", "EUB", "DIRK2", "DIRK3",
        "ESDIRK32", "ESDIRK4", "ESDIRK43", "ESDIRK54", "ESDIRK85",
        "BDF", "BDF2", "BDF3", "BDF4", "BDF5", "BDF6",
        "GEAR", "GEAR21", "GEAR32", "GEAR43", "GEAR52A", "GEAR54",
    }
    if is_disc:
        supported_solvers.add("Discrete")  # Internal legacy numeric profile only.
    if raw_solver.strip() not in supported_solvers:
        raise ValidationError("simulationSettings.solver is not a supported PathSim solver class.")

    raw_adaptive = _pick("adaptive", default_adaptive)
    if not isinstance(raw_adaptive, (bool, np.bool_)):
        raise ValidationError(f"simulationSettings.adaptive deve ser booleano, recebido {raw_adaptive!r}.")

    raw_plot = _pick("plotResults", True)
    if not isinstance(raw_plot, (bool, np.bool_)):
        raise ValidationError(f"simulationSettings.plotResults deve ser booleano, recebido {raw_plot!r}.")

    raw_ghost = _pick("ghostTraces", 0)
    if isinstance(raw_ghost, (bool, np.bool_)) or not isinstance(raw_ghost, (int, np.integer)):
        raise ValidationError(
            f"simulationSettings.ghostTraces deve ser inteiro >= 0, recebido {raw_ghost!r}."
        )
    ghost_int = int(raw_ghost)
    if ghost_int < 0:
        raise ValidationError("simulationSettings.ghostTraces deve ser >= 0.")

    return {
        "duration": duration_str,
        "dt": dt_str,
        "solver": raw_solver.strip(),
        "adaptive": bool(raw_adaptive),
        "atol": atol_str,
        "rtol": rtol_str,
        "ftol": ftol_str,
        "dt_min": dt_min_str,
        "dt_max": dt_max_str,
        "ghostTraces": ghost_int,
        "plotResults": bool(raw_plot),
    }


def validate_pvm_structure(
    pvm: Mapping[str, Any],
    *,
    require_known_blocks: bool = False,
) -> dict[str, Any]:
    """Valida passivamente estrutura .pvm v1.0.0 contra pvm.schema.json e invariantes de grafo."""
    if not isinstance(pvm, Mapping):
        raise ValidationError("PVM deve ser um objeto JSON (Mapping).")

    clean = ensure_json_finite(dict(pvm), path="$")

    if "version" not in clean:
        raise ValidationError("Campo obrigatório ausente em PVM: 'version'.")
    version = clean["version"]
    if not isinstance(version, str):
        raise ValidationError("PVM.version deve ser string.")
    if version != PATHVIEW_SPEC_VERSION:
        raise SchemaUnsupportedError(
            message=f"Versão .pvm não suportada: {version!r} (suportada: {PATHVIEW_SPEC_VERSION!r}).",
            parameters={"version": version, "supported_version": PATHVIEW_SPEC_VERSION},
            next_step="Forneça um arquivo .pvm v1.0.0 compatível.",
        )

    keys = set(clean.keys())
    extra = keys - _PVM_ROOT_KEYS
    if extra:
        raise ValidationError(f"Campos extras proibidos na raiz do PVM: {sorted(extra)}")
    missing = _PVM_ROOT_KEYS - keys
    if missing:
        raise ValidationError(f"Campos obrigatórios ausentes na raiz do PVM: {sorted(missing)}")

    # metadata
    meta = clean["metadata"]
    if not isinstance(meta, Mapping):
        raise ValidationError("PVM.metadata deve ser objeto JSON.")
    for req_m in ("created", "modified", "name"):
        if req_m not in meta or not isinstance(meta[req_m], str) or not meta[req_m]:
            raise ValidationError(f"PVM.metadata.{req_m} deve ser string não vazia.")

    # events
    if not isinstance(clean["events"], list):
        raise ValidationError("PVM.events deve ser lista.")

    # codeContext (validação estrutural passiva: JAMAIS executa)
    cc = clean["codeContext"]
    if not isinstance(cc, Mapping) or "code" not in cc or not isinstance(cc["code"], str):
        raise ValidationError("PVM.codeContext deve conter campo string 'code'.")

    # simulationSettings
    sim = clean["simulationSettings"]
    if not isinstance(sim, Mapping):
        raise ValidationError("PVM.simulationSettings deve ser objeto JSON.")
    missing_sim = _SIM_SETTINGS_REQUIRED_KEYS - set(sim.keys())
    if missing_sim:
        raise ValidationError(
            f"Campos obrigatórios ausentes em PVM.simulationSettings: {sorted(missing_sim)}"
        )
    for str_or_num_key in ("duration", "dt", "atol", "rtol", "ftol", "dt_min", "dt_max"):
        v = sim[str_or_num_key]
        if isinstance(v, bool) or not isinstance(v, (str, int, float)):
            raise ValidationError(f"PVM.simulationSettings.{str_or_num_key} deve ser string ou número.")
    if not isinstance(sim["solver"], str) or not sim["solver"]:
        raise ValidationError("PVM.simulationSettings.solver deve ser string não vazia.")
    if not isinstance(sim["adaptive"], bool) or not isinstance(sim["plotResults"], bool):
        raise ValidationError("PVM.simulationSettings adaptive e plotResults devem ser booleanos.")
    if not _is_non_neg_int(sim["ghostTraces"]):
        raise ValidationError("PVM.simulationSettings.ghostTraces deve ser inteiro >= 0.")

    # graph
    graph = clean["graph"]
    if not isinstance(graph, Mapping) or "nodes" not in graph or "connections" not in graph:
        raise ValidationError("PVM.graph deve conter 'nodes' e 'connections'.")
    if not isinstance(graph["nodes"], list) or not isinstance(graph["connections"], list):
        raise ValidationError("PVM.graph.nodes e PVM.graph.connections devem ser listas.")
    if "annotations" in graph and not isinstance(graph["annotations"], list):
        raise ValidationError("PVM.graph.annotations deve ser uma lista.")

    node_map: dict[str, dict[str, Any]] = {}
    seen_positions: set[tuple[float, float]] = set()
    known_blocks = set(PATHVIEW_BLOCK_REGISTRY["blocks"].keys())

    for n_idx, node in enumerate(graph["nodes"]):
        if not isinstance(node, Mapping):
            raise ValidationError(f"graph.nodes[{n_idx}] deve ser objeto JSON.")
        for req_n in ("id", "type", "name", "position", "inputs", "outputs", "params"):
            if req_n not in node:
                raise ValidationError(f"Campo obrigatório ausente em graph.nodes[{n_idx}]: {req_n!r}")
        nid = validate_non_empty_str(node["id"], field_name=f"graph.nodes[{n_idx}].id")
        if nid in node_map:
            raise ValidationError(
                message=f"ID de nó duplicado em PVM: {nid!r}.",
                parameters={"node_id": nid},
            )
        ntype = validate_non_empty_str(node["type"], field_name=f"graph.nodes[{n_idx}].type")
        validate_non_empty_str(node["name"], field_name=f"graph.nodes[{n_idx}].name")
        if require_known_blocks and ntype not in known_blocks:
            raise UnsupportedModelError(
                f"Tipo de bloco desconhecido no registro PathView v{PATHVIEW_SPEC_VERSION}: {ntype!r}."
            )

        pos = node["position"]
        if not isinstance(pos, Mapping) or "x" not in pos or "y" not in pos:
            raise ValidationError(f"graph.nodes[{n_idx}].position requer 'x' e 'y'.")
        if not _is_real_number(pos["x"]) or not _is_real_number(pos["y"]):
            raise ValidationError(f"Posição do nó {nid!r} deve conter coordenadas numéricas finitas.")
        pos_pair = (float(pos["x"]), float(pos["y"]))
        if pos_pair in seen_positions:
            raise ValidationError(
                message=f"Sobreposição visual detectada: múltiplos nós na posição {pos_pair}.",
                parameters={"node_id": nid, "position": list(pos_pair)},
            )
        seen_positions.add(pos_pair)

        if not isinstance(node["params"], Mapping):
            raise ValidationError(f"graph.nodes[{n_idx}].params deve ser objeto JSON.")

        for dir_key, expected_dir in (("inputs", "input"), ("outputs", "output")):
            ports = node[dir_key]
            if not isinstance(ports, list):
                raise ValidationError(f"graph.nodes[{n_idx}].{dir_key} deve ser lista.")
            for p_idx, port in enumerate(ports):
                if not isinstance(port, Mapping):
                    raise ValidationError(f"Porta {nid}.{dir_key}[{p_idx}] deve ser objeto JSON.")
                for req_p in ("nodeId", "direction", "index"):
                    if req_p not in port:
                        raise ValidationError(
                            f"Campo obrigatório ausente em porta {nid}.{dir_key}[{p_idx}]: {req_p!r}"
                        )
                if port["nodeId"] != nid:
                    raise ValidationError(
                        f"Porta {nid}.{dir_key}[{p_idx}] tem nodeId={port['nodeId']!r} divergente de {nid!r}."
                    )
                if port["direction"] != expected_dir:
                    raise ValidationError(
                        f"Porta {nid}.{dir_key}[{p_idx}] tem direction={port['direction']!r}, esperado {expected_dir!r}."
                    )
                if not _is_non_neg_int(port["index"]) or int(port["index"]) != p_idx:
                    raise ValidationError(
                        f"Porta {nid}.{dir_key}[{p_idx}] deve ter index contíguo {p_idx}, recebido {port['index']!r}."
                    )
                if "name" in port and not isinstance(port["name"], str):
                    raise ValidationError(f"Porta {nid}.{dir_key}[{p_idx}].name deve ser string.")

        node_map[nid] = dict(node)

    seen_conn_ids: set[str] = set()
    seen_target_ports: set[tuple[str, int]] = set()
    for c_idx, conn in enumerate(graph["connections"]):
        if not isinstance(conn, Mapping):
            raise ValidationError(f"graph.connections[{c_idx}] deve ser objeto JSON.")
        for req_c in ("sourceNodeId", "sourcePortIndex", "targetNodeId", "targetPortIndex"):
            if req_c not in conn:
                raise ValidationError(f"Campo obrigatório ausente em graph.connections[{c_idx}]: {req_c!r}")
        if "id" in conn:
            if not isinstance(conn["id"], str) or not conn["id"].strip():
                raise ValidationError(
                    f"graph.connections[{c_idx}].id deve ser string não vazia quando presente, recebido {conn['id']!r}."
                )
            cid = conn["id"]
            if cid in seen_conn_ids:
                raise ValidationError(f"ID de conexão duplicado em PVM: {cid!r}")
            seen_conn_ids.add(cid)

        src_id = conn["sourceNodeId"]
        dst_id = conn["targetNodeId"]
        src_port = conn["sourcePortIndex"]
        dst_port = conn["targetPortIndex"]

        if not isinstance(src_id, str) or src_id not in node_map:
            raise ValidationError(f"Conexão [{c_idx}] referencia sourceNodeId inexistente: {src_id!r}.")
        if not isinstance(dst_id, str) or dst_id not in node_map:
            raise ValidationError(f"Conexão [{c_idx}] referencia targetNodeId inexistente: {dst_id!r}.")
        if not _is_non_neg_int(src_port) or int(src_port) >= len(node_map[src_id]["outputs"]):
            raise ValidationError(
                f"Conexão [{c_idx}] referencia porta de saída inválida {src_id}:{src_port!r}."
            )
        if not _is_non_neg_int(dst_port) or int(dst_port) >= len(node_map[dst_id]["inputs"]):
            raise ValidationError(
                f"Conexão [{c_idx}] referencia porta de entrada inválida {dst_id}:{dst_port!r}."
            )

        target_key = (dst_id, int(dst_port))
        if target_key in seen_target_ports:
            raise ValidationError(
                message=(
                    f"Fan-in proibido detectado em PVM: porta de entrada {dst_id}[{dst_port}] "
                    "recebe múltiplas conexões (Apêndice D)."
                ),
                parameters={"target_node_id": dst_id, "target_port_index": int(dst_port)},
                next_step="Use um bloco Adder com portas de entrada separadas para somar sinais.",
            )
        seen_target_ports.add(target_key)

    return clean


def make_pvm(
    plant: Any,
    controller: Any = None,
    scenario: Mapping[str, Any] | None = None,
    target_spec_version: str = "1.0.0",
    *,
    created_at: str | None = None,
    modified_at: str | None = None,
    name: str | None = None,
    return_result: bool = False,
    raise_on_error: bool = False,
    runtime_profile: str = "official",
) -> dict[str, Any] | Result:
    """Build an official continuous PathView graph, or an explicit internal legacy graph.

    ``runtime_profile="legacy_numeric"`` is a migration/testing facility for the
    passive numerical evaluator, not an external PathView export. The public
    ``export_pvm`` always uses the official default and rejects discrete plants
    until the upstream discrete scheduling mismatch has an independent fix.
    """
    prov: Provenance = build_provenance(
        "control_lab.io.make_pvm",
        model_revision=getattr(plant, "revision", None),
        target_spec_version=str(target_spec_version),
    )
    assumptions: dict[str, Any] = {
        "external_pathview_verified": False,
        "gate_pending": "G-0D",
        "code_executed": False,
    }
    diagnostics: dict[str, Any] = {
        "external_pathview_verified": False,
        "gate_pending": "G-0D",
        "block_registry_version": PATHVIEW_SPEC_VERSION,
    }
    warnings_out: list[WarningItem] = [
        WarningItem(
            code="EXTERNAL_PATHVIEW_NOT_VERIFIED",
            message=(
                "Exportação .pvm gerada para PathView 0.21.0 com registro oficial fixado; abertura e simulação "
                "externa no PathView real ainda pendentes de Gate G-0D."
            ),
            details={"external_pathview_verified": False, "gate": "G-0D"},
        )
    ]

    try:
        if not isinstance(target_spec_version, str) or target_spec_version != PATHVIEW_SPEC_VERSION:
            raise SchemaUnsupportedError(
                message=(
                    f"target_spec_version .pvm não suportada: {target_spec_version!r} "
                    f"(suportada: {PATHVIEW_SPEC_VERSION!r})."
                ),
                parameters={"target_spec_version": target_spec_version},
                next_step="Use target_spec_version='1.0.0'.",
            )

        if isinstance(plant, (TSStateSpace, FuzzySystem)) or isinstance(
            controller, (PDCController, FuzzySystem)
        ):
            raise UnsupportedModelError(
                message=(
                    "Exportação nativa .pvm para PDCController, TSStateSpace ou FuzzySystem ainda "
                    "não está disponível pois depende da validação real de blocos no PathView (DEC-OPEN-07)."
                ),
                parameters={
                    "plant_type": type(plant).__name__,
                    "controller_type": type(controller).__name__ if controller is not None else None,
                    "decision_ref": "DEC-OPEN-07",
                },
                next_step="Use generate_pathsim_script(plant, controller, scenario) como fallback CPython/PathSim.",
            )

        if not isinstance(plant, StateSpace):
            raise UnsupportedModelError(
                message=f"make_pvm suporta StateSpace; recebido {type(plant).__name__}.",
                parameters={"plant_type": type(plant).__name__},
                next_step="Converta TransferFunction via .to_state_space() antes de chamar make_pvm.",
            )

        if controller is not None and not isinstance(controller, (StateFeedbackController, DynamicController)):
            raise UnsupportedModelError(
                message=f"Controlador não suportado em make_pvm: {type(controller).__name__}.",
                parameters={"controller_type": type(controller).__name__},
            )

        if scenario is not None and not isinstance(scenario, Mapping):
            raise ValidationError("scenario deve ser um Mapping ou None.")
        sc = ensure_json_finite(dict(scenario), path="$.scenario") if scenario is not None else {}

        wiring = sc.get("wiring")
        if wiring is not None and not isinstance(wiring, Mapping):
            raise ValidationError("scenario['wiring'] deve ser um Mapping.")
        wiring_dict = dict(wiring) if wiring is not None else {}
        if "reference_map" in wiring_dict and wiring_dict["reference_map"] is not None:
            wiring_dict["reference_map"] = _coerce_numeric_input(
                wiring_dict["reference_map"], ndim=2, name="wiring.reference_map"
            )
        if "reference_map" in sc and "reference_map" not in wiring_dict and sc["reference_map"] is not None:
            wiring_dict["reference_map"] = _coerce_numeric_input(
                sc["reference_map"], ndim=2, name="scenario.reference_map"
            )
        sign_convention = sc.get("sign_convention")
        if sign_convention is not None and not isinstance(sign_convention, str):
            raise ValidationError("scenario['sign_convention'] deve ser string ou None.")

        if controller is not None:
            validate_interconnection(
                plant,
                controller,
                wiring=wiring_dict if wiring_dict else None,
                sign_convention=sign_convention,
                raise_on_error=True,
            )

        if not isinstance(runtime_profile, str) or runtime_profile not in {"official", "legacy_numeric"}:
            raise ValidationError("runtime_profile must be 'official' or 'legacy_numeric'.")
        if runtime_profile == "official" and plant.dt is not None:
            raise UnsupportedModelError(
                message=("Official PathView discrete export is unavailable: DiscreteStateSpace event "
                         "scheduling does not preserve ControlLab's simultaneous x[k+1] feedback update."),
                parameters={"domain": "discrete", "external_compatible": False,
                            "reason": "discrete_schedule_mismatch", "finding": "F9-WASM-PVM-001"},
                next_step="Use the internal discrete simulator; official export needs a separately verified clock-alignment adapter.",
            )
        if runtime_profile == "legacy_numeric":
            warnings_out = [WarningItem(
                code="LEGACY_NUMERIC_PVM_ONLY",
                message="Internal legacy numeric graph only; this graph is NOT compatible with official PathView export.",
                details={"external_compatible": False, "runtime_profile": "legacy_numeric"},
            )]
            assumptions.update({"runtime_profile": "legacy_numeric", "external_compatible": False})
            diagnostics.update({"runtime_profile": "legacy_numeric", "external_compatible": False})

        n, m, p = plant.n_states, plant.n_inputs, plant.n_outputs
        x_p0 = _resolve_initial_state(sc, n)
        sat_spec = _parse_saturation_spec(sc, m)
        sim_settings = _build_simulation_settings(plant, sc)

        created_ts = validate_non_empty_str(
            created_at if created_at is not None else sc.get("created_at", DEFAULT_PVM_TIMESTAMP),
            field_name="created_at",
        )
        modified_ts = validate_non_empty_str(
            modified_at if modified_at is not None else sc.get("modified_at", created_ts),
            field_name="modified_at",
        )

        nodes: list[dict[str, Any]] = []
        connections: list[dict[str, Any]] = []
        conn_counter = 0

        def _connect(src_id: str, src_port: int, dst_id: str, dst_port: int) -> None:
            nonlocal conn_counter
            conn_counter += 1
            connections.append(
                {
                    "id": f"conn_{conn_counter:03d}",
                    "sourceNodeId": src_id,
                    "sourcePortIndex": int(src_port),
                    "targetNodeId": dst_id,
                    "targetPortIndex": int(dst_port),
                }
            )

        def _make_plant_node(x_pos: float, y_pos: float, *, expose_state: bool) -> dict[str, Any]:
            nid = "plant_ss"
            outs = [_port(nid, "output", 0, "y")]
            if expose_state:
                outs.append(_port(nid, "output", 1, "x"))
            return {
                "id": nid,
                "type": "StateSpace",
                "name": plant.id,
                "position": {"x": float(x_pos), "y": float(y_pos)},
                "inputs": [_port(nid, "input", 0, "u")],
                "outputs": outs,
                "params": {
                    "A": [[float(v) for v in row] for row in plant.A.tolist()],
                    "B": [[float(v) for v in row] for row in plant.B.tolist()],
                    "C": [[float(v) for v in row] for row in plant.C.tolist()],
                    "D": [[float(v) for v in row] for row in plant.D.tolist()],
                    "initial_state": x_p0,
                    "dt": plant.dt,
                    "state_names": list(plant.state_names),
                    "input_names": list(plant.input_names),
                    "output_names": list(plant.output_names),
                    "expose_state": bool(expose_state),
                },
            }

        def _make_scope_node(x_pos: float, y_pos: float) -> dict[str, Any]:
            nid = "scope_y"
            return {
                "id": nid,
                "type": "Scope",
                "name": "OutputScope",
                "position": {"x": float(x_pos), "y": float(y_pos)},
                "inputs": [_port(nid, "input", 0, "y")],
                "outputs": [],
                "params": {
                    "dim": int(p),
                    "channel_names": list(plant.output_names),
                    "units": list(plant.units.get("outputs", [""] * p)),
                },
            }

        def _maybe_insert_saturation(upstream_id: str, upstream_port: int, x_pos: float, y_pos: float) -> tuple[str, int]:
            if sat_spec is None:
                return upstream_id, upstream_port
            sat_id = "actuator_sat"
            nodes.append(
                {
                    "id": sat_id,
                    "type": "Saturation",
                    "name": "ActuatorSaturation",
                    "position": {"x": float(x_pos), "y": float(y_pos)},
                    "inputs": [_port(sat_id, "input", 0, "in")],
                    "outputs": [_port(sat_id, "output", 0, "out")],
                    "params": {
                        "enabled": bool(sat_spec["enabled"]),
                        "u_min": list(sat_spec["u_min"]),
                        "u_max": list(sat_spec["u_max"]),
                        "dim": int(m),
                    },
                }
            )
            _connect(upstream_id, upstream_port, sat_id, 0)
            return sat_id, 0

        code_lines = [
            "import numpy as np",
            _format_np_array_code("A_plant", plant.A),
            _format_np_array_code("B_plant", plant.B),
            _format_np_array_code("C_plant", plant.C),
            _format_np_array_code("D_plant", plant.D),
            f"dt_plant = {plant.dt!r}",
            _format_np_array_code("x0_plant", np.asarray(x_p0, dtype=np.float64)),
        ]

        interconnection_kind = "open_loop"
        resolved_sign: str | None = None

        if controller is None:
            default_name = f"ControlLab_OpenLoop_{plant.id}"
            src_id = "src_u"
            ref_spec = _resolve_reference_signal_spec(sc, m, plant.input_names)
            nodes.append(
                {
                    "id": src_id,
                    "type": "Source",
                    "name": "InputSource",
                    "position": {"x": 100.0, "y": 200.0},
                    "inputs": [],
                    "outputs": [_port(src_id, "output", 0, "u_ext")],
                    "params": ref_spec,
                }
            )
            u_src_id, u_src_port = _maybe_insert_saturation(src_id, 0, 340.0, 200.0)
            plant_x = 580.0 if sat_spec is not None else 360.0
            scope_x = 820.0 if sat_spec is not None else 620.0
            expose_x = bool(sc.get("expose_state", False))
            nodes.append(_make_plant_node(plant_x, 200.0, expose_state=expose_x))
            nodes.append(_make_scope_node(scope_x, 200.0))
            _connect(u_src_id, u_src_port, "plant_ss", 0)
            _connect("plant_ss", 0, "scope_y", 0)

        elif isinstance(controller, StateFeedbackController):
            interconnection_kind = "state_feedback"
            resolved_sign = sign_convention if sign_convention is not None else controller.feedback_sign
            default_name = f"ControlLab_LQR_{plant.id}"

            ref_mat = controller.reference_matrix
            ref_names = controller.reference_names
            if ref_mat is None and wiring_dict.get("reference_map") is not None:
                ref_mat = _coerce_numeric_input(wiring_dict["reference_map"], ndim=2, name="reference_map")
            p_ref = int(ref_mat.shape[1]) if ref_mat is not None else m
            src_names = (
                list(ref_names)
                if ref_names is not None
                else ([f"r{i + 1}" for i in range(p_ref)] if ref_mat is not None else list(plant.input_names))
            )
            ref_spec = _resolve_reference_signal_spec(sc, p_ref, src_names)

            src_id = "src_ref"
            nodes.append(
                {
                    "id": src_id,
                    "type": "Source",
                    "name": "ReferenceSource",
                    "position": {"x": 80.0, "y": 200.0},
                    "inputs": [],
                    "outputs": [_port(src_id, "output", 0, "r")],
                    "params": ref_spec,
                }
            )

            ff_src_id, ff_src_port = src_id, 0
            if ref_mat is not None:
                gain_n_id = "gain_N"
                nodes.append(
                    {
                        "id": gain_n_id,
                        "type": "MatrixGain",
                        "name": "Prefilter_N",
                        "position": {"x": 280.0, "y": 200.0},
                        "inputs": [_port(gain_n_id, "input", 0, "r")],
                        "outputs": [_port(gain_n_id, "output", 0, "u_ff")],
                        "params": {
                            "gain": [[float(v) for v in row] for row in ref_mat.tolist()],
                            "shape": [int(ref_mat.shape[0]), int(ref_mat.shape[1])],
                            "role": "prefilter",
                            "label": "N",
                        },
                    }
                )
                _connect(src_id, 0, gain_n_id, 0)
                ff_src_id, ff_src_port = gain_n_id, 0

            adder_id = "sum_feedback"
            fb_sign_char = "-" if resolved_sign == "negative" else "+"
            nodes.append(
                {
                    "id": adder_id,
                    "type": "Adder",
                    "name": f"ControlSum_{resolved_sign}",
                    "position": {"x": 480.0, "y": 200.0},
                    "inputs": [
                        _port(adder_id, "input", 0, "u_ff"),
                        _port(adder_id, "input", 1, "Kx"),
                    ],
                    "outputs": [_port(adder_id, "output", 0, "u_cmd")],
                    "params": {
                        "signs": ["+", fb_sign_char],
                        "feedback_sign": resolved_sign,
                        "dim": int(m),
                    },
                }
            )
            _connect(ff_src_id, ff_src_port, adder_id, 0)

            u_src_id, u_src_port = _maybe_insert_saturation(adder_id, 0, 680.0, 200.0)
            plant_x = 880.0 if sat_spec is not None else 700.0
            scope_x = 1100.0 if sat_spec is not None else 940.0

            # Sempre expor porta 1 = x (indispensável quando C != I ou D != 0)
            nodes.append(_make_plant_node(plant_x, 200.0, expose_state=True))
            nodes.append(_make_scope_node(scope_x, 200.0))
            _connect(u_src_id, u_src_port, "plant_ss", 0)
            _connect("plant_ss", 0, "scope_y", 0)

            gain_k_id = "gain_K"
            nodes.append(
                {
                    "id": gain_k_id,
                    "type": "MatrixGain",
                    "name": "FeedbackGain_K",
                    "position": {"x": 680.0, "y": 420.0},
                    "inputs": [_port(gain_k_id, "input", 0, "x")],
                    "outputs": [_port(gain_k_id, "output", 0, "Kx")],
                    "params": {
                        "gain": [[float(v) for v in row] for row in controller.K.tolist()],
                        "shape": [int(controller.K.shape[0]), int(controller.K.shape[1])],
                        "role": "feedback_gain",
                        "label": "K",
                    },
                }
            )
            _connect("plant_ss", 1, gain_k_id, 0)
            _connect(gain_k_id, 0, adder_id, 1)

            code_lines.append(f"feedback_sign = {resolved_sign!r}")
            code_lines.append(_format_np_array_code("K_feedback", controller.K))
            if ref_mat is not None:
                code_lines.append(_format_np_array_code("N_prefilter", ref_mat))

        else:
            assert isinstance(controller, DynamicController)
            interconnection_kind = "dynamic_controller"
            resolved_sign = sign_convention if sign_convention is not None else controller.feedback_sign
            scheme = wiring_dict.get("scheme") or controller.resolved_scheme
            default_name = f"ControlLab_Dynamic_{scheme}_{plant.id}"

            # Mapear portas do DynamicController exatamente na ordem declarada em controller.ports
            in_ports_spec = controller.ports["inputs"]
            out_ports_spec = controller.ports["outputs"]

            u_out_indices = [idx for idx, pt in enumerate(out_ports_spec) if pt["role"] == "u"]
            if len(u_out_indices) != 1:
                raise UnsupportedModelError(
                    "Exportação .pvm exige exatamente uma porta de saída com role='u' no DynamicController."
                )
            u_port_idx = u_out_indices[0]

            ctrl_id = "ctrl_dynamic"
            ctrl_inputs = [
                _port(ctrl_id, "input", idx, str(pt["name"]))
                for idx, pt in enumerate(in_ports_spec)
            ]
            ctrl_outputs = [
                _port(ctrl_id, "output", idx, str(pt["name"]))
                for idx, pt in enumerate(out_ports_spec)
            ]
            ctrl_params: dict[str, Any] = {
                "Ac": [[float(v) for v in row] for row in controller.Ac.tolist()],
                "Bc": [[float(v) for v in row] for row in controller.Bc.tolist()],
                "Cc": [[float(v) for v in row] for row in controller.Cc.tolist()],
                "Dc": [[float(v) for v in row] for row in controller.Dc.tolist()],
                "initial_state": [float(v) for v in controller.initial_state.tolist()],
                "dt": controller.dt,
                "feedback_sign": resolved_sign,
                "ports": copy.deepcopy(controller.ports),
                "interconnection_scheme": scheme,
                "resolved_scheme": controller.resolved_scheme,
                "state_names": (
                    list(controller.state_names)
                    if controller.state_names is not None
                    else [f"xc{i + 1}" for i in range(controller.n_states)]
                ),
            }

            fb_sign_char = "-" if resolved_sign == "negative" else "+"
            s_val = -1.0 if resolved_sign == "negative" else 1.0

            if scheme in ("output_feedback", "observer_based"):
                y_in_indices = [idx for idx, pt in enumerate(in_ports_spec) if pt["role"] == "y"]
                if len(y_in_indices) != 1:
                    raise UnsupportedModelError(
                        "Exportação .pvm para output_feedback/observer_based exige uma única porta 'y'."
                    )
                y_port_idx = y_in_indices[0]
                ref_spec = _resolve_reference_signal_spec(sc, m, plant.input_names)

                nodes.append(
                    {
                        "id": "src_ref",
                        "type": "Source",
                        "name": "ReferenceSource",
                        "position": {"x": 100.0, "y": 200.0},
                        "inputs": [],
                        "outputs": [_port("src_ref", "output", 0, "r")],
                        "params": ref_spec,
                    }
                )
                nodes.append(
                    {
                        "id": "sum_feedback",
                        "type": "Adder",
                        "name": f"ControlSum_{resolved_sign}",
                        "position": {"x": 320.0, "y": 200.0},
                        "inputs": [
                            _port("sum_feedback", "input", 0, "r"),
                            _port("sum_feedback", "input", 1, "u_ctrl"),
                        ],
                        "outputs": [_port("sum_feedback", "output", 0, "u_cmd")],
                        "params": {
                            "signs": ["+", fb_sign_char],
                            "feedback_sign": resolved_sign,
                            "dim": int(m),
                        },
                    }
                )
                _connect("src_ref", 0, "sum_feedback", 0)
                u_src_id, u_src_port = _maybe_insert_saturation("sum_feedback", 0, 540.0, 200.0)
                plant_x = 760.0 if sat_spec is not None else 560.0
                scope_x = 980.0 if sat_spec is not None else 800.0
                nodes.append(_make_plant_node(plant_x, 200.0, expose_state=False))
                nodes.append(_make_scope_node(scope_x, 200.0))
                nodes.append(
                    {
                        "id": ctrl_id,
                        "type": "DynamicController",
                        "name": controller.id,
                        "position": {"x": 540.0, "y": 420.0},
                        "inputs": ctrl_inputs,
                        "outputs": ctrl_outputs,
                        "params": ctrl_params,
                    }
                )
                _connect(u_src_id, u_src_port, "plant_ss", 0)
                _connect("plant_ss", 0, "scope_y", 0)
                _connect("plant_ss", 0, ctrl_id, y_port_idx)
                _connect(ctrl_id, u_port_idx, "sum_feedback", 1)

            elif scheme == "error_feedback":
                e_in_indices = [idx for idx, pt in enumerate(in_ports_spec) if pt["role"] == "error"]
                if not e_in_indices:
                    e_in_indices = [idx for idx, pt in enumerate(in_ports_spec) if pt["role"] == "y"]
                if len(e_in_indices) != 1:
                    raise UnsupportedModelError(
                        "Exportação .pvm para error_feedback exige exatamente uma porta de entrada de erro."
                    )
                e_port_idx = e_in_indices[0]
                ref_spec = _resolve_reference_signal_spec(sc, p, plant.output_names)

                nodes.append(
                    {
                        "id": "src_ref",
                        "type": "Source",
                        "name": "ReferenceSource",
                        "position": {"x": 100.0, "y": 200.0},
                        "inputs": [],
                        "outputs": [_port("src_ref", "output", 0, "r")],
                        "params": ref_spec,
                    }
                )
                nodes.append(
                    {
                        "id": "sum_error",
                        "type": "Adder",
                        "name": f"ErrorSum_{resolved_sign}",
                        "position": {"x": 300.0, "y": 200.0},
                        "inputs": [
                            _port("sum_error", "input", 0, "r"),
                            _port("sum_error", "input", 1, "y"),
                        ],
                        "outputs": [_port("sum_error", "output", 0, "e")],
                        "params": {
                            "signs": ["+", fb_sign_char],
                            "feedback_sign": resolved_sign,
                            "dim": int(p),
                        },
                    }
                )
                nodes.append(
                    {
                        "id": ctrl_id,
                        "type": "DynamicController",
                        "name": controller.id,
                        "position": {"x": 520.0, "y": 200.0},
                        "inputs": ctrl_inputs,
                        "outputs": ctrl_outputs,
                        "params": ctrl_params,
                    }
                )
                _connect("src_ref", 0, "sum_error", 0)
                _connect("sum_error", 0, ctrl_id, e_port_idx)
                u_src_id, u_src_port = _maybe_insert_saturation(ctrl_id, u_port_idx, 740.0, 200.0)
                plant_x = 960.0 if sat_spec is not None else 760.0
                scope_x = 1180.0 if sat_spec is not None else 1000.0
                nodes.append(_make_plant_node(plant_x, 200.0, expose_state=False))
                nodes.append(_make_scope_node(scope_x, 200.0))
                _connect(u_src_id, u_src_port, "plant_ss", 0)
                _connect("plant_ss", 0, "scope_y", 0)
                _connect("plant_ss", 0, "sum_error", 1)

            elif scheme == "two_dof":
                y_in_indices = [idx for idx, pt in enumerate(in_ports_spec) if pt["role"] == "y"]
                r_in_indices = [idx for idx, pt in enumerate(in_ports_spec) if pt["role"] == "r"]
                if len(y_in_indices) != 1 or len(r_in_indices) != 1:
                    raise UnsupportedModelError(
                        "Exportação .pvm para two_dof exige exatamente uma porta 'y' e uma porta 'r'."
                    )
                y_port_idx = y_in_indices[0]
                r_port_idx = r_in_indices[0]
                p_ref = int(in_ports_spec[r_port_idx]["size"])
                ref_spec = _resolve_reference_signal_spec(sc, p_ref, [f"r{i + 1}" for i in range(p_ref)])

                nodes.append(
                    {
                        "id": "src_ref",
                        "type": "Source",
                        "name": "ReferenceSource",
                        "position": {"x": 100.0, "y": 200.0},
                        "inputs": [],
                        "outputs": [_port("src_ref", "output", 0, "r")],
                        "params": ref_spec,
                    }
                )
                nodes.append(
                    {
                        "id": ctrl_id,
                        "type": "DynamicController",
                        "name": controller.id,
                        "position": {"x": 340.0, "y": 200.0},
                        "inputs": ctrl_inputs,
                        "outputs": ctrl_outputs,
                        "params": ctrl_params,
                    }
                )
                _connect("src_ref", 0, ctrl_id, r_port_idx)
                u_src_id, u_src_port = _maybe_insert_saturation(ctrl_id, u_port_idx, 560.0, 200.0)
                plant_x = 780.0 if sat_spec is not None else 580.0
                scope_x = 1000.0 if sat_spec is not None else 820.0
                nodes.append(_make_plant_node(plant_x, 200.0, expose_state=False))
                nodes.append(_make_scope_node(scope_x, 200.0))

                sign_mat = s_val * np.eye(p, dtype=np.float64)
                sign_y_id = "gain_feedback_sign_y"
                nodes.append(
                    {
                        "id": sign_y_id,
                        "type": "MatrixGain",
                        "name": f"FeedbackSign_y_{resolved_sign}",
                        "position": {"x": 560.0, "y": 420.0},
                        "inputs": [_port(sign_y_id, "input", 0, "y")],
                        "outputs": [_port(sign_y_id, "output", 0, "y_signed")],
                        "params": {
                            "gain": [[float(v) for v in row] for row in sign_mat.tolist()],
                            "shape": [int(p), int(p)],
                            "role": "feedback_sign",
                            "label": f"{resolved_sign}_I",
                        },
                    }
                )
                _connect(u_src_id, u_src_port, "plant_ss", 0)
                _connect("plant_ss", 0, "scope_y", 0)
                _connect("plant_ss", 0, sign_y_id, 0)
                _connect(sign_y_id, 0, ctrl_id, y_port_idx)
            else:
                raise UnsupportedModelError(
                    f"Esquema de DynamicController não suportado para .pvm: {scheme!r}."
                )

            code_lines.extend(
                [
                    f"feedback_sign = {resolved_sign!r}",
                    f"controller_scheme = {scheme!r}",
                    _format_np_array_code("Ac", controller.Ac),
                    _format_np_array_code("Bc", controller.Bc),
                    _format_np_array_code("Cc", controller.Cc),
                    _format_np_array_code("Dc", controller.Dc),
                    _format_np_array_code("x0_controller", controller.initial_state),
                ]
            )

        if sat_spec is not None:
            code_lines.extend(
                [
                    f"saturation_enabled = {bool(sat_spec['enabled'])!r}",
                    _format_np_array_code("u_min", np.asarray(sat_spec["u_min"], dtype=np.float64)),
                    _format_np_array_code("u_max", np.asarray(sat_spec["u_max"], dtype=np.float64)),
                ]
            )

        resolved_name = validate_non_empty_str(
            name if name is not None else sc.get("name", default_name),
            field_name="name",
        )
        raw_events = sc.get("events", [])
        if not isinstance(raw_events, list):
            raise ValidationError("scenario['events'] deve ser uma lista.")

        pvm_doc: dict[str, Any] = {
            "version": PATHVIEW_SPEC_VERSION,
            "metadata": {
                "created": created_ts,
                "modified": modified_ts,
                "name": resolved_name,
                "generator": "ControlLab Web",
                "spec_version": PATHVIEW_SPEC_VERSION,
                "external_pathview_verified": False,
                "gate_pending": "G-0D",
                "interconnection_kind": interconnection_kind,
                "feedback_sign": resolved_sign,
                "plant_ref": {"id": plant.id, "revision": plant.revision},
                "controller_ref": (
                    {"id": controller.id, "revision": controller.revision}
                    if controller is not None
                    else None
                ),
            },
            "graph": {
                "nodes": nodes,
                "connections": connections,
                "annotations": [
                    {
                        "id": "ann_controllab_spec",
                        "text": (
                            f"ControlLab {interconnection_kind} | sign={resolved_sign} | "
                            "external_pathview_verified=False (Gate G-0D pendente)"
                        ),
                    }
                ],
            },
            "events": copy.deepcopy(raw_events),
            "codeContext": {"code": "\n".join(code_lines) + "\n"},
            "simulationSettings": sim_settings,
        }

        if runtime_profile == "legacy_numeric":
            pvm_doc["metadata"].update({"runtime_profile": "legacy_numeric", "external_compatible": False})
            pvm_doc["graph"]["annotations"][0]["text"] += " | INTERNAL LEGACY NUMERIC ONLY; NOT AN OFFICIAL PATHVIEW EXPORT"
            validated = validate_pvm_structure(pvm_doc, require_known_blocks=False)
        else:
            validated = validate_pvm_structure(lower_to_official(pvm_doc), require_known_blocks=True)
        diagnostics.update(
            {
                "node_count": len(validated["graph"]["nodes"]),
                "connection_count": len(validated["graph"]["connections"]),
                "interconnection_kind": interconnection_kind,
                "feedback_sign": resolved_sign,
                "saturation_enabled": bool(sat_spec["enabled"]) if sat_spec is not None else False,
            }
        )
        if not return_result:
            return validated

        return Result(
            status="warning",
            data={"pvm": validated},
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        if not return_result or raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=exc.to_typed_error(),
        )


def export_pvm(
    plant: Any,
    controller: Any = None,
    scenario: Mapping[str, Any] | None = None,
    target_spec_version: str = "1.0.0",
    *,
    output_path: str | Path | None = None,
    created_at: str | None = None,
    modified_at: str | None = None,
    name: str | None = None,
    raise_on_error: bool = False,
) -> Result:
    """Exporta `.pvm` v1.0.0 encapsulado em `Result` (opcionalmente gravando em disco)."""
    res = make_pvm(
        plant,
        controller=controller,
        scenario=scenario,
        target_spec_version=target_spec_version,
        created_at=created_at,
        modified_at=modified_at,
        name=name,
        return_result=True,
        raise_on_error=raise_on_error,
    )
    if res.status == "failure" or res.data is None:
        return res

    pvm_dict = res.data["pvm"]
    pvm_json = strict_json_dumps(pvm_dict, indent=2, sort_keys=True) + "\n"
    sha256 = hashlib.sha256(pvm_json.encode("utf-8")).hexdigest()
    data_out: dict[str, Any] = {
        "pvm": pvm_dict,
        "pvm_json": pvm_json,
        "sha256": sha256,
    }
    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(pvm_json, encoding="utf-8")
        data_out["output_path"] = str(out_p)

    return Result(
        status=res.status,
        data=data_out,
        assumptions=res.assumptions,
        diagnostics=res.diagnostics,
        provenance=res.provenance,
        warnings=res.warnings,
        error=None,
    )


def _scan_untrusted_param_strings(nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    suspects: list[dict[str, Any]] = []
    for node in nodes:
        nid = str(node["id"])
        params = node.get("params", {})
        for k, v in params.items():
            if k in _NUMERIC_PARAM_KEYS and isinstance(v, str):
                suspects.append({"node_id": nid, "param": k, "value": v})
            elif k in _NUMERIC_PARAM_KEYS and isinstance(v, list):
                for item in v:
                    if isinstance(item, str) or (
                        isinstance(item, list) and any(isinstance(sub, str) for sub in item)
                    ):
                        suspects.append({"node_id": nid, "param": k})
                        break
    return suspects


def import_pvm(
    source: Mapping[str, Any] | str | bytes | Path,
    *,
    max_bytes: int = DEFAULT_MAX_PVM_BYTES,
    raise_on_error: bool = False,
) -> Result:
    """Importação 100% passiva de `.pvm`: valida schema/grafo e JAMAIS executa `codeContext.code`."""
    prov: Provenance = build_provenance("control_lab.io.import_pvm")
    assumptions: dict[str, Any] = {
        "passive_import": True,
        "code_executed": False,
        "external_pathview_verified": False,
    }
    diagnostics: dict[str, Any] = {"code_executed": False}
    warnings_out: list[WarningItem] = []

    try:
        if max_bytes <= 0:
            raise ValidationError("max_bytes deve ser > 0.")

        if isinstance(source, Mapping):
            raw_obj: Any = ensure_json_finite(dict(source), path="$")
        elif isinstance(source, (bytes, bytearray, memoryview)):
            raw_bytes = bytes(source)
            if len(raw_bytes) > max_bytes:
                raise ResourceLimitError(
                    f"Arquivo .pvm excede limite de {max_bytes} bytes ({len(raw_bytes)} bytes)."
                )
            raw_obj = _safe_strict_json_loads(raw_bytes, context=".pvm")
        elif isinstance(source, Path):
            try:
                if not source.exists() or not source.is_file():
                    raise ValidationError(f"Arquivo .pvm não encontrado: {source}")
                size = source.stat().st_size
                if size > max_bytes:
                    raise ResourceLimitError(
                        f"Arquivo .pvm excede limite de {max_bytes} bytes ({size} bytes)."
                    )
                raw_bytes = source.read_bytes()
            except ControlLabError:
                raise
            except (OSError, ValueError) as exc:
                raise ValidationError(f"Falha ao ler arquivo .pvm: {exc}") from exc
            raw_obj = _safe_strict_json_loads(raw_bytes, context=".pvm")
        elif isinstance(source, str):
            if source.lstrip().startswith("{"):
                if len(source.encode("utf-8")) > max_bytes:
                    raise ResourceLimitError(f"Conteúdo JSON .pvm excede {max_bytes} bytes.")
                raw_obj = _safe_strict_json_loads(source, context=".pvm")
            else:
                try:
                    path = Path(source)
                    if not path.exists() or not path.is_file():
                        raise ValidationError("String fornecida a import_pvm não é JSON válido nem arquivo existente.")
                    size = path.stat().st_size
                    if size > max_bytes:
                        raise ResourceLimitError(
                            f"Arquivo .pvm excede limite de {max_bytes} bytes ({size} bytes)."
                        )
                    raw_bytes = path.read_bytes()
                except ControlLabError:
                    raise
                except (OSError, ValueError) as exc:
                    raise ValidationError(f"Falha ao ler arquivo .pvm: {exc}") from exc
                raw_obj = _safe_strict_json_loads(raw_bytes, context=".pvm")
        else:
            raise ValidationError(f"Tipo de entrada inválido para import_pvm: {type(source).__name__}")

        validated = validate_pvm_structure(raw_obj, require_known_blocks=False)
        code_text = validated["codeContext"]["code"]
        has_code = bool(code_text.strip())
        if has_code:
            warnings_out.append(
                WarningItem(
                    code="UNTRUSTED_CODE_CONTEXT_IGNORED",
                    message=(
                        "codeContext.code detectado na importação .pvm e deliberadamente NÃO executado "
                        "(política passiva T-IO-02)."
                    ),
                    details={"code_length": len(code_text), "code_executed": False},
                )
            )

        param_str_suspects = _scan_untrusted_param_strings(validated["graph"]["nodes"])
        if param_str_suspects:
            warnings_out.append(
                WarningItem(
                    code="UNTRUSTED_PARAM_EXPRESSION_IGNORED",
                    message=(
                        "Parâmetros textuais/expressões detectados em nós .pvm e NÃO avaliados "
                        "(sem eval/exec)."
                    ),
                    details={"suspects": param_str_suspects, "code_executed": False},
                )
            )

        block_types = sorted({str(n["type"]) for n in validated["graph"]["nodes"]})
        diagnostics.update(
            {
                "version": validated["version"],
                "n_nodes": len(validated["graph"]["nodes"]),
                "n_connections": len(validated["graph"]["connections"]),
                "has_code_context": has_code,
                "block_types": block_types,
                "untrusted_param_expressions": len(param_str_suspects),
            }
        )
        return Result(
            status="warning" if warnings_out else "success",
            data={
                "pvm": validated,
                "code_executed": False,
                "summary": {
                    "name": validated["metadata"]["name"],
                    "version": validated["version"],
                    "n_nodes": len(validated["graph"]["nodes"]),
                    "n_connections": len(validated["graph"]["connections"]),
                    "block_types": block_types,
                },
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=exc.to_typed_error(),
        )


def load_pvm(source: Mapping[str, Any] | str | bytes | Path, *, max_bytes: int = DEFAULT_MAX_PVM_BYTES) -> dict[str, Any]:
    """Carrega e valida passivamente um `.pvm`, retornando o dict validado (ou levantando ControlLabError)."""
    res = import_pvm(source, max_bytes=max_bytes, raise_on_error=True)
    assert res.data is not None
    return res.data["pvm"]


# ---------------------------------------------------------------------------
# Avaliador/Simulador estrutural de referência a partir do grafo .pvm
# ---------------------------------------------------------------------------


def _ensure_numeric_param(
    val: Any,
    *,
    node_id: str,
    param_name: str,
    ndim: int | None = None,
    shape: tuple[int, ...] | None = None,
) -> np.ndarray:
    if isinstance(val, str):
        raise ImportUntrustedCodeError(
            message=(
                f"Parâmetro {param_name!r} do nó {node_id!r} contém expressão textual não numérica; "
                "execução dinâmica proibida."
            ),
            parameters={"node_id": node_id, "param": param_name},
        )
    if isinstance(val, list):
        for item in val:
            if isinstance(item, str) or (isinstance(item, list) and any(isinstance(sub, str) for sub in item)):
                raise ImportUntrustedCodeError(
                    message=(
                        f"Parâmetro {param_name!r} do nó {node_id!r} contém elemento string; "
                        "avaliação via eval é proibida."
                    ),
                    parameters={"node_id": node_id, "param": param_name},
                )
    return ensure_finite_float64(val, ndim=ndim, shape=shape, name=f"{node_id}.{param_name}")


def _coerce_matrix_2d(
    val: Any,
    *,
    node_id: str,
    param_name: str,
    empty_shape: tuple[int, int] | None = None,
) -> np.ndarray:
    if isinstance(val, list) and len(val) == 0 and empty_shape is not None and empty_shape[0] == 0:
        return np.zeros(empty_shape, dtype=np.float64)
    return _ensure_numeric_param(val, node_id=node_id, param_name=param_name, ndim=2)


class _CompiledPVMNetwork:
    """Representação algébrico-dinâmica compilada puramente de graph.nodes/connections."""

    def __init__(self, validated_pvm: dict[str, Any]) -> None:
        validated_pvm = restore_numeric_projection(validated_pvm)
        self.pvm = validated_pvm
        nodes_list: list[dict[str, Any]] = validated_pvm["graph"]["nodes"]
        conns_list: list[dict[str, Any]] = validated_pvm["graph"]["connections"]

        self.nodes_by_id: dict[str, dict[str, Any]] = {str(n["id"]): n for n in nodes_list}
        self.node_order: list[str] = [str(n["id"]) for n in nodes_list]

        # Mapa de chegada: (dst_id, dst_port) -> (src_id, src_port)
        self.incoming: dict[tuple[str, int], tuple[str, int]] = {}
        for c in conns_list:
            self.incoming[(str(c["targetNodeId"]), int(c["targetPortIndex"]))] = (
                str(c["sourceNodeId"]),
                int(c["sourcePortIndex"]),
            )

        self.plant_nodes: list[dict[str, Any]] = []
        self.ctrl_nodes: list[dict[str, Any]] = []
        self.source_nodes: list[dict[str, Any]] = []
        self.scope_nodes: list[dict[str, Any]] = []
        self.sat_nodes: list[dict[str, Any]] = []
        self.parsed_params: dict[str, dict[str, Any]] = {}
        self.port_dims: dict[tuple[str, int], int] = {}

        resolved_dt: float | None = None
        has_dt_owner = False

        for nid in self.node_order:
            node = self.nodes_by_id[nid]
            ntype = str(node["type"])
            params = node["params"]

            if ntype == "Source":
                dim = params.get("dim")
                if not _is_non_neg_int(dim) or int(dim) < 1:
                    raise ValidationError(f"Source {nid!r} requer dim >= 1.")
                d_int = int(dim)
                val_arr = _ensure_numeric_param(
                    params.get("value", [0.0] * d_int),
                    node_id=nid,
                    param_name="value",
                    ndim=1,
                    shape=(d_int,),
                )
                self.parsed_params[nid] = {"dim": d_int, "value": val_arr}
                self.port_dims[(nid, 0)] = d_int
                self.source_nodes.append(node)

            elif ntype == "StateSpace":
                A = _coerce_matrix_2d(params["A"], node_id=nid, param_name="A", empty_shape=(0, 0))
                n_s = A.shape[0]
                if A.shape != (n_s, n_s):
                    raise DimensionMismatchError(f"StateSpace {nid!r}: A deve ser quadrada, recebido {A.shape}.")
                D = _coerce_matrix_2d(params["D"], node_id=nid, param_name="D")
                p_s, m_s = D.shape
                B = _coerce_matrix_2d(params["B"], node_id=nid, param_name="B", empty_shape=(n_s, m_s))
                if B.shape != (n_s, m_s):
                    raise DimensionMismatchError(f"StateSpace {nid!r}: B shape {B.shape} != ({n_s}, {m_s}).")
                C = _coerce_matrix_2d(params["C"], node_id=nid, param_name="C", empty_shape=(p_s, n_s))
                if C.shape != (p_s, n_s):
                    raise DimensionMismatchError(f"StateSpace {nid!r}: C shape {C.shape} != ({p_s}, {n_s}).")
                x0 = _ensure_numeric_param(
                    params.get("initial_state", [0.0] * n_s),
                    node_id=nid,
                    param_name="initial_state",
                    ndim=1,
                    shape=(n_s,),
                )
                dt_n = params.get("dt")
                if not has_dt_owner:
                    resolved_dt = dt_n
                    has_dt_owner = True
                else:
                    check_dt_compatible(resolved_dt, dt_n, label_a="pvm_node", label_b=nid)

                self.parsed_params[nid] = {
                    "A": A,
                    "B": B,
                    "C": C,
                    "D": D,
                    "x0": x0,
                    "dt": dt_n,
                    "n": n_s,
                    "m": m_s,
                    "p": p_s,
                }
                self.port_dims[(nid, 0)] = p_s
                if len(node["outputs"]) >= 2:
                    self.port_dims[(nid, 1)] = n_s
                self.plant_nodes.append(node)

            elif ntype == "DynamicController":
                Ac = _coerce_matrix_2d(params["Ac"], node_id=nid, param_name="Ac", empty_shape=(0, 0))
                nc = Ac.shape[0]
                if Ac.shape != (nc, nc):
                    raise DimensionMismatchError(f"DynamicController {nid!r}: Ac deve ser quadrada.")
                Dc = _coerce_matrix_2d(params["Dc"], node_id=nid, param_name="Dc")
                n_out, n_in = Dc.shape
                Bc = _coerce_matrix_2d(params["Bc"], node_id=nid, param_name="Bc", empty_shape=(nc, n_in))
                if Bc.shape != (nc, n_in):
                    raise DimensionMismatchError(
                        f"DynamicController {nid!r}: Bc shape {Bc.shape} != ({nc}, {n_in})."
                    )
                Cc = _coerce_matrix_2d(params["Cc"], node_id=nid, param_name="Cc", empty_shape=(n_out, nc))
                if Cc.shape != (n_out, nc):
                    raise DimensionMismatchError(
                        f"DynamicController {nid!r}: Cc shape {Cc.shape} != ({n_out}, {nc})."
                    )
                xc0 = _ensure_numeric_param(
                    params.get("initial_state", [0.0] * nc),
                    node_id=nid,
                    param_name="initial_state",
                    ndim=1,
                    shape=(nc,),
                )
                dt_c = params.get("dt")
                if not has_dt_owner:
                    resolved_dt = dt_c
                    has_dt_owner = True
                else:
                    check_dt_compatible(resolved_dt, dt_c, label_a="pvm_node", label_b=nid)

                ports_meta = params.get("ports")
                if not isinstance(ports_meta, Mapping):
                    raise ValidationError(f"DynamicController {nid!r} requer params.ports.")
                in_ports_m = ports_meta.get("inputs", [])
                out_ports_m = ports_meta.get("outputs", [])
                in_sizes = [int(pt["size"]) for pt in in_ports_m]
                out_sizes = [int(pt["size"]) for pt in out_ports_m]
                if sum(in_sizes) != Bc.shape[1]:
                    raise DimensionMismatchError(
                        f"DynamicController {nid!r}: soma das portas de entrada ({sum(in_sizes)}) != Bc.shape[1] ({Bc.shape[1]})."
                    )
                if sum(out_sizes) != Cc.shape[0]:
                    raise DimensionMismatchError(
                        f"DynamicController {nid!r}: soma das portas de saída ({sum(out_sizes)}) != Cc.shape[0] ({Cc.shape[0]})."
                    )
                for p_idx, sz in enumerate(out_sizes):
                    self.port_dims[(nid, p_idx)] = sz

                self.parsed_params[nid] = {
                    "Ac": Ac,
                    "Bc": Bc,
                    "Cc": Cc,
                    "Dc": Dc,
                    "x0": xc0,
                    "dt": dt_c,
                    "nc": nc,
                    "in_sizes": in_sizes,
                    "out_sizes": out_sizes,
                }
                self.ctrl_nodes.append(node)

            elif ntype == "MatrixGain":
                G = _ensure_numeric_param(params["gain"], node_id=nid, param_name="gain", ndim=2)
                self.parsed_params[nid] = {"G": G, "rows": G.shape[0], "cols": G.shape[1]}
                self.port_dims[(nid, 0)] = G.shape[0]

            elif ntype == "Adder":
                signs_raw = params.get("signs")
                if not isinstance(signs_raw, list) or len(signs_raw) < 1:
                    raise ValidationError(f"Adder {nid!r} requer lista não vazia 'signs'.")
                if len(signs_raw) != len(node["inputs"]):
                    raise DimensionMismatchError(
                        f"Adder {nid!r}: len(signs)={len(signs_raw)} difere de len(inputs)={len(node['inputs'])}."
                    )
                sign_vals: list[float] = []
                for s_ch in signs_raw:
                    if s_ch == "+":
                        sign_vals.append(1.0)
                    elif s_ch == "-":
                        sign_vals.append(-1.0)
                    else:
                        raise ValidationError(f"Adder {nid!r}: sinal inválido {s_ch!r} (use '+' ou '-').")
                self.parsed_params[nid] = {"sign_vals": sign_vals}

            elif ntype == "Saturation":
                enabled = params.get("enabled", True)
                if not isinstance(enabled, bool):
                    raise ValidationError(f"Saturation {nid!r}.enabled deve ser booleano.")
                u_min = _ensure_numeric_param(params["u_min"], node_id=nid, param_name="u_min", ndim=1)
                u_max = _ensure_numeric_param(params["u_max"], node_id=nid, param_name="u_max", ndim=1, shape=u_min.shape)
                if np.any(u_min > u_max):
                    raise ValidationError(f"Saturation {nid!r}: u_min > u_max.")
                self.parsed_params[nid] = {
                    "enabled": enabled,
                    "u_min": u_min,
                    "u_max": u_max,
                    "dim": int(u_min.shape[0]),
                }
                self.port_dims[(nid, 0)] = int(u_min.shape[0])
                self.sat_nodes.append(node)

            elif ntype == "Scope":
                dim = params.get("dim")
                if not _is_non_neg_int(dim) or int(dim) < 1:
                    raise ValidationError(f"Scope {nid!r} requer dim >= 1.")
                self.parsed_params[nid] = {"dim": int(dim)}
                self.scope_nodes.append(node)

            else:
                raise UnsupportedModelError(f"Tipo de bloco não suportado para avaliação: {ntype!r}.")

        # Resolver dimensões de saída de Adders (inferidas de suas entradas)
        changed = True
        while changed:
            changed = False
            for nid in self.node_order:
                node = self.nodes_by_id[nid]
                if node["type"] == "Adder" and (nid, 0) not in self.port_dims:
                    for i_idx in range(len(node["inputs"])):
                        src = self.incoming.get((nid, i_idx))
                        if src is not None and src in self.port_dims:
                            self.port_dims[(nid, 0)] = self.port_dims[src]
                            changed = True
                            break

        for nid in self.node_order:
            node = self.nodes_by_id[nid]
            if node["type"] == "Adder" and (nid, 0) not in self.port_dims:
                raise DimensionMismatchError(f"Não foi possível inferir dimensão do nó Adder {nid!r}.")

        # Validar compatibilidade dimensional de todas as portas e conexões
        for nid in self.node_order:
            node = self.nodes_by_id[nid]
            ntype = node["type"]
            pinfo = self.parsed_params[nid]
            expected_in_dims: list[int] = []
            if ntype == "Source":
                expected_in_dims = []
            elif ntype == "StateSpace":
                expected_in_dims = [pinfo["m"]]
            elif ntype == "DynamicController":
                expected_in_dims = list(pinfo["in_sizes"])
            elif ntype == "MatrixGain":
                expected_in_dims = [pinfo["cols"]]
            elif ntype == "Adder":
                expected_in_dims = [self.port_dims[(nid, 0)]] * len(node["inputs"])
            elif ntype == "Saturation":
                expected_in_dims = [pinfo["dim"]]
            elif ntype == "Scope":
                expected_in_dims = [pinfo["dim"]]

            for p_idx, exp_dim in enumerate(expected_in_dims):
                src = self.incoming.get((nid, p_idx))
                if src is None:
                    raise ValidationError(
                        f"Porta de entrada desconectada no grafo PVM: {nid}[{p_idx}]."
                    )
                if src not in self.port_dims:
                    raise DimensionMismatchError(f"Dimensão indefinida na origem {src}.")
                if self.port_dims[src] != exp_dim:
                    raise DimensionMismatchError(
                        message=(
                            f"Incompatibilidade dimensional na conexão {src[0]}:{src[1]} -> {nid}:{p_idx}: "
                            f"{self.port_dims[src]} != {exp_dim}."
                        ),
                        parameters={"source": list(src), "target": [nid, p_idx]},
                    )

        self.dt = resolved_dt
        self.has_enabled_saturation = any(self.parsed_params[n["id"]]["enabled"] for n in self.sat_nodes)

        # Estado aumentado: [x_plants..., x_ctrls...]
        self.state_slices: dict[str, slice] = {}
        self.n_plant_states = 0
        self.n_ctrl_states = 0
        offset = 0
        for pnode in self.plant_nodes:
            nid = str(pnode["id"])
            ns = self.parsed_params[nid]["n"]
            self.state_slices[nid] = slice(offset, offset + ns)
            offset += ns
            self.n_plant_states += ns
        for cnode in self.ctrl_nodes:
            nid = str(cnode["id"])
            nc = self.parsed_params[nid]["nc"]
            self.state_slices[nid] = slice(offset, offset + nc)
            offset += nc
            self.n_ctrl_states += nc
        self.n_states_total = offset

        # Entradas exógenas (Sources)
        self.source_slices: dict[str, slice] = {}
        r_off = 0
        for snode in self.source_nodes:
            nid = str(snode["id"])
            d_int = self.parsed_params[nid]["dim"]
            self.source_slices[nid] = slice(r_off, r_off + d_int)
            r_off += d_int
        self.n_ref_total = r_off

        # Sinais internos w (todas as portas de saída de todos os nós)
        self.sig_slices: dict[tuple[str, int], slice] = {}
        self.sat_sig_slices: list[tuple[str, slice, slice]] = []  # (node_id, w_out_slice, w_in_slice)
        s_off = 0
        for nid in self.node_order:
            node = self.nodes_by_id[nid]
            for p_idx in range(len(node["outputs"])):
                dim = self.port_dims[(nid, p_idx)]
                self.sig_slices[(nid, p_idx)] = slice(s_off, s_off + dim)
                s_off += dim
        self.n_signals = s_off

        # Montar matrizes globais de acoplamento:
        # w_all = L_ww w_all + L_wx x_aug + L_wr r + nl_sat_override
        self.L_ww = np.zeros((self.n_signals, self.n_signals), dtype=np.float64)
        self.L_wx = np.zeros((self.n_signals, self.n_states_total), dtype=np.float64)
        self.L_wr = np.zeros((self.n_signals, self.n_ref_total), dtype=np.float64)
        self.A_state = np.zeros((self.n_states_total, self.n_states_total), dtype=np.float64)
        self.B_sig = np.zeros((self.n_states_total, self.n_signals), dtype=np.float64)

        for nid in self.node_order:
            node = self.nodes_by_id[nid]
            ntype = node["type"]
            pinfo = self.parsed_params[nid]

            if ntype == "Source":
                ws = self.sig_slices[(nid, 0)]
                rs = self.source_slices[nid]
                self.L_wr[ws, rs] = np.eye(pinfo["dim"], dtype=np.float64)

            elif ntype == "StateSpace":
                xs = self.state_slices[nid]
                u_in_src = self.incoming[(nid, 0)]
                us = self.sig_slices[u_in_src]
                # x_dot / x_next = A x + B u
                if pinfo["n"] > 0:
                    self.A_state[xs, xs] = pinfo["A"]
                    self.B_sig[xs, us] = pinfo["B"]
                # port 0: y = C x + D u
                wy = self.sig_slices[(nid, 0)]
                if pinfo["n"] > 0:
                    self.L_wx[wy, xs] = pinfo["C"]
                self.L_ww[wy, us] = pinfo["D"]
                # port 1 (se existir): x = I x
                if (nid, 1) in self.sig_slices:
                    wx = self.sig_slices[(nid, 1)]
                    if pinfo["n"] > 0:
                        self.L_wx[wx, xs] = np.eye(pinfo["n"], dtype=np.float64)

            elif ntype == "DynamicController":
                xs = self.state_slices[nid]
                Ac, Bc, Cc, Dc = pinfo["Ac"], pinfo["Bc"], pinfo["Cc"], pinfo["Dc"]
                in_col_off = 0
                for p_idx, in_sz in enumerate(pinfo["in_sizes"]):
                    src_sig = self.sig_slices[self.incoming[(nid, p_idx)]]
                    if pinfo["nc"] > 0:
                        self.B_sig[xs, src_sig] += Bc[:, in_col_off : in_col_off + in_sz]
                    in_col_off += in_sz
                if pinfo["nc"] > 0:
                    self.A_state[xs, xs] = Ac

                out_row_off = 0
                for p_idx, out_sz in enumerate(pinfo["out_sizes"]):
                    wo = self.sig_slices[(nid, p_idx)]
                    if pinfo["nc"] > 0:
                        self.L_wx[wo, xs] = Cc[out_row_off : out_row_off + out_sz, :]
                    in_col_off = 0
                    for in_idx, in_sz in enumerate(pinfo["in_sizes"]):
                        src_sig = self.sig_slices[self.incoming[(nid, in_idx)]]
                        self.L_ww[wo, src_sig] += Dc[
                            out_row_off : out_row_off + out_sz,
                            in_col_off : in_col_off + in_sz,
                        ]
                        in_col_off += in_sz
                    out_row_off += out_sz

            elif ntype == "MatrixGain":
                wo = self.sig_slices[(nid, 0)]
                wi = self.sig_slices[self.incoming[(nid, 0)]]
                self.L_ww[wo, wi] = pinfo["G"]

            elif ntype == "Adder":
                wo = self.sig_slices[(nid, 0)]
                dim = self.port_dims[(nid, 0)]
                eye_d = np.eye(dim, dtype=np.float64)
                for p_idx, s_val in enumerate(pinfo["sign_vals"]):
                    wi = self.sig_slices[self.incoming[(nid, p_idx)]]
                    self.L_ww[wo, wi] += s_val * eye_d

            elif ntype == "Saturation":
                wo = self.sig_slices[(nid, 0)]
                wi = self.sig_slices[self.incoming[(nid, 0)]]
                if not pinfo["enabled"]:
                    self.L_ww[wo, wi] = np.eye(pinfo["dim"], dtype=np.float64)
                else:
                    self.sat_sig_slices.append((nid, wo, wi))

        # Saída observada (Scope ou porta y da primeira planta)
        if self.scope_nodes:
            out_chunks = [
                self.sig_slices[self.incoming[(str(sc["id"]), 0)]] for sc in self.scope_nodes
            ]
        elif self.plant_nodes:
            out_chunks = [self.sig_slices[(str(self.plant_nodes[0]["id"]), 0)]]
        else:
            raise ValidationError("Grafo PVM não possui Scope nem StateSpace para observação de saída.")

        self.n_outputs_total = sum(sl.stop - sl.start for sl in out_chunks)
        self.C_sig = np.zeros((self.n_outputs_total, self.n_signals), dtype=np.float64)
        y_off = 0
        for sl in out_chunks:
            dim = sl.stop - sl.start
            self.C_sig[y_off : y_off + dim, sl] = np.eye(dim, dtype=np.float64)
            y_off += dim

        # Sinal de entrada de controle u entrando na primeira planta (para retorno diagnóstico)
        if self.plant_nodes:
            first_plant_id = str(self.plant_nodes[0]["id"])
            self.plant_u_slice = self.sig_slices[self.incoming[(first_plant_id, 0)]]
        else:
            self.plant_u_slice = slice(0, 0)

    def default_x0(self) -> np.ndarray:
        if self.n_states_total == 0:
            return np.zeros((0,), dtype=np.float64)
        parts = [self.parsed_params[str(p["id"])]["x0"] for p in self.plant_nodes]
        parts.extend(self.parsed_params[str(c["id"])]["x0"] for c in self.ctrl_nodes)
        return np.concatenate(parts)

    def default_r_constant(self) -> np.ndarray:
        if self.n_ref_total == 0:
            return np.zeros((0,), dtype=np.float64)
        return np.concatenate([self.parsed_params[str(s["id"])]["value"] for s in self.source_nodes])

    def extract_linear_maps(self) -> dict[str, np.ndarray]:
        """Resolve (I - L_ww) w = L_wx x + L_wr r via np.linalg.solve (sem inv)."""
        if self.has_enabled_saturation:
            raise UnsupportedModelError(
                "Grafo .pvm possui bloco Saturation com enabled=True; use simulate_pvm_graph.",
                next_step="Desative a saturação para extração LTI exata ou execute simulate_pvm_graph.",
            )
        M = np.eye(self.n_signals, dtype=np.float64) - self.L_ww
        svals = np.linalg.svd(M, compute_uv=False)
        s_max = float(svals[0]) if svals.size > 0 else 1.0
        s_min = float(svals[-1]) if svals.size > 0 else 1.0
        if not np.all(np.isfinite(svals)) or s_min <= 1e-12 * max(1.0, s_max):
            raise HypothesisViolatedError(
                message=(
                    f"Loop algébrico do grafo .pvm é singular ou mal posto (sigma_min={s_min:.3e})."
                ),
                parameters={"min_singular_value": s_min, "max_singular_value": s_max},
            )
        rhs = np.hstack([self.L_wx, self.L_wr])
        W = np.linalg.solve(M, rhs)
        W_x = W[:, : self.n_states_total]
        W_r = W[:, self.n_states_total :]

        Acl = self.A_state + self.B_sig @ W_x
        Bcl = self.B_sig @ W_r
        Ccl = self.C_sig @ W_x
        Dcl = self.C_sig @ W_r
        return {
            "Acl": Acl,
            "Bcl": Bcl,
            "Ccl": Ccl,
            "Dcl": Dcl,
            "W_x": W_x,
            "W_r": W_r,
        }

    def build_nonlinear_evaluator(self) -> Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Constrói avaliador (x_next_or_dot, y, w_all) com blocos Saturation ativos."""
        sat_mask = np.zeros((self.n_signals,), dtype=bool)
        sat_mins: list[np.ndarray] = []
        sat_maxs: list[np.ndarray] = []
        sat_out_indices: list[int] = []
        sat_in_indices: list[int] = []

        for nid, wo, wi in self.sat_sig_slices:
            sat_mask[wo] = True
            pinfo = self.parsed_params[nid]
            sat_mins.append(pinfo["u_min"])
            sat_maxs.append(pinfo["u_max"])
            sat_out_indices.extend(range(wo.start, wo.stop))
            sat_in_indices.extend(range(wi.start, wi.stop))

        lin_idx = np.where(~sat_mask)[0]
        sat_out_idx = np.asarray(sat_out_indices, dtype=np.int64)
        sat_in_idx = np.asarray(sat_in_indices, dtype=np.int64)
        u_min_all = np.concatenate(sat_mins)
        u_max_all = np.concatenate(sat_maxs)

        M_ll = np.eye(lin_idx.size, dtype=np.float64) - self.L_ww[np.ix_(lin_idx, lin_idx)]
        svals = np.linalg.svd(M_ll, compute_uv=False)
        s_max = float(svals[0]) if svals.size > 0 else 1.0
        s_min = float(svals[-1]) if svals.size > 0 else 1.0
        if not np.all(np.isfinite(svals)) or s_min <= 1e-12 * max(1.0, s_max):
            raise HypothesisViolatedError("Subrede linear do grafo .pvm é singular.")

        rhs = np.hstack(
            [
                self.L_wx[lin_idx, :],
                self.L_wr[lin_idx, :],
                self.L_ww[np.ix_(lin_idx, sat_out_idx)],
            ]
        )
        W_l = np.linalg.solve(M_ll, rhs)
        c1 = self.n_states_total
        c2 = c1 + self.n_ref_total
        W_lx = W_l[:, :c1]
        W_lr = W_l[:, c1:c2]
        W_ls = W_l[:, c2:]

        # Mapear índices de sat_in_idx dentro de lin_idx
        lin_pos_lookup = {int(g_i): l_i for l_i, g_i in enumerate(lin_idx.tolist())}
        if any(int(idx) not in lin_pos_lookup for idx in sat_in_idx.tolist()):
            # Caso raro: saturação ligada diretamente em série com outra saturação
            raise UnsupportedModelError("Saturações em cascata direta sem nó intermediário não suportadas.")
        in_pos_in_lin = np.asarray([lin_pos_lookup[int(i)] for i in sat_in_idx.tolist()], dtype=np.int64)

        M_x = W_lx[in_pos_in_lin, :]
        M_r = W_lr[in_pos_in_lin, :]
        M_s = W_ls[in_pos_in_lin, :]
        has_sat_algebraic_loop = bool(np.max(np.abs(M_s)) > 1e-14) if M_s.size > 0 else False

        def _solve_sat_loop(u_base: np.ndarray) -> np.ndarray:
            m_sat = u_base.shape[0]
            # 1. Testar solução linear pura (conjunto ativo vazio) antes de iterar
            M_loop = np.eye(m_sat, dtype=np.float64) - M_s
            sv_loop = np.linalg.svd(M_loop, compute_uv=False)
            smax_l = float(sv_loop[0]) if sv_loop.size > 0 else 1.0
            smin_l = float(sv_loop[-1]) if sv_loop.size > 0 else 1.0
            if smin_l > 1e-12 * max(1.0, smax_l):
                w_lin = np.linalg.solve(M_loop, u_base)
                if np.all(w_lin >= u_min_all - 1e-13) and np.all(w_lin <= u_max_all + 1e-13):
                    w_cand = np.clip(w_lin, u_min_all, u_max_all)
                    if float(np.max(np.abs(np.clip(u_base + M_s @ w_cand, u_min_all, u_max_all) - w_cand))) <= 1e-11:
                        return w_cand

            # 2. Newton semissuave (conjunto ativo exato para sistema afim por partes)
            w_cur = np.clip(u_base, u_min_all, u_max_all)
            seen_masks: set[tuple[int, ...]] = set()
            for _ in range(max(32, 4 * m_sat + 8)):
                z = u_base + M_s @ w_cur
                w_clip = np.clip(z, u_min_all, u_max_all)
                if float(np.max(np.abs(w_clip - w_cur))) <= 1e-12:
                    return w_clip
                mask = tuple(
                    -1 if z[i] <= u_min_all[i] else (1 if z[i] >= u_max_all[i] else 0)
                    for i in range(m_sat)
                )
                if mask in seen_masks:
                    break
                seen_masks.add(mask)
                free_idx = np.asarray([i for i, mk in enumerate(mask) if mk == 0], dtype=np.int64)
                w_next = np.where(
                    np.asarray(mask) < 0,
                    u_min_all,
                    np.where(np.asarray(mask) > 0, u_max_all, 0.0),
                )
                if free_idx.size > 0:
                    fixed_idx = np.asarray([i for i, mk in enumerate(mask) if mk != 0], dtype=np.int64)
                    rhs_f = u_base[free_idx]
                    if fixed_idx.size > 0:
                        rhs_f = rhs_f + M_s[np.ix_(free_idx, fixed_idx)] @ w_next[fixed_idx]
                    J_ff = np.eye(free_idx.size, dtype=np.float64) - M_s[np.ix_(free_idx, free_idx)]
                    sv_ff = np.linalg.svd(J_ff, compute_uv=False)
                    if sv_ff.size == 0 or float(sv_ff[-1]) <= 1e-12 * max(1.0, float(sv_ff[0])):
                        break
                    w_next[free_idx] = np.linalg.solve(J_ff, rhs_f)
                w_cur = w_next
                z_chk = u_base + M_s @ w_cur
                if float(np.max(np.abs(np.clip(z_chk, u_min_all, u_max_all) - w_cur))) <= 1e-12:
                    return np.clip(z_chk, u_min_all, u_max_all)

            # 3. Fallback de ponto fixo (Picard puro quando contrativo, amortecido apenas se oscilar)
            w_pf = np.clip(u_base, u_min_all, u_max_all)
            prev_diff = float("inf")
            alpha = 1.0
            for it in range(500):
                w_raw = np.clip(u_base + M_s @ w_pf, u_min_all, u_max_all)
                diff = float(np.max(np.abs(w_raw - w_pf)))
                if diff <= 1e-11:
                    return w_raw
                if it > 0 and diff > 1.05 * prev_diff:
                    alpha = max(0.2, 0.5 * alpha)
                prev_diff = diff
                w_pf = (1.0 - alpha) * w_pf + alpha * w_raw

            raise NumericalInconclusiveError(
                "Loop algébrico com saturação não convergiu na avaliação do grafo .pvm."
            )

        def _eval(x_vec: np.ndarray, r_vec: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
            u_base = M_x @ x_vec + M_r @ r_vec
            if not has_sat_algebraic_loop:
                w_sat = np.clip(u_base, u_min_all, u_max_all)
            else:
                w_sat = _solve_sat_loop(u_base)

            w_lin = W_lx @ x_vec + W_lr @ r_vec + W_ls @ w_sat
            w_all = np.zeros((self.n_signals,), dtype=np.float64)
            w_all[lin_idx] = w_lin
            w_all[sat_out_idx] = w_sat
            x_rhs = self.A_state @ x_vec + self.B_sig @ w_all
            y_out = self.C_sig @ w_all
            return x_rhs, y_out, w_all

        return _eval


def extract_lti_from_pvm(pvm: Mapping[str, Any] | str | bytes | Path) -> StateSpace:
    """Reconstrói StateSpace linear de malha fechada exclusivamente a partir do grafo .pvm."""
    pvm_dict = load_pvm(pvm) if not isinstance(pvm, Mapping) else validate_pvm_structure(pvm)
    compiled = _CompiledPVMNetwork(pvm_dict)
    maps = compiled.extract_linear_maps()

    state_names: list[str] = []
    for pnode in compiled.plant_nodes:
        snames = pnode["params"].get("state_names")
        if isinstance(snames, list) and len(snames) == compiled.parsed_params[str(pnode["id"])]["n"]:
            state_names.extend(str(s) for s in snames)
        else:
            state_names.extend(f"xp{i + 1}" for i in range(compiled.parsed_params[str(pnode["id"])]["n"]))
    for cnode in compiled.ctrl_nodes:
        snames = cnode["params"].get("state_names")
        if isinstance(snames, list) and len(snames) == compiled.parsed_params[str(cnode["id"])]["nc"]:
            state_names.extend(str(s) for s in snames)
        else:
            state_names.extend(f"xc{i + 1}" for i in range(compiled.parsed_params[str(cnode["id"])]["nc"]))

    in_names: list[str] = []
    for snode in compiled.source_nodes:
        cnames = snode["params"].get("channel_names")
        d_int = compiled.parsed_params[str(snode["id"])]["dim"]
        if isinstance(cnames, list) and len(cnames) == d_int:
            in_names.extend(str(c) for c in cnames)
        else:
            in_names.extend(f"r{i + 1}" for i in range(d_int))

    out_names: list[str] = []
    if compiled.scope_nodes:
        for sc in compiled.scope_nodes:
            cnames = sc["params"].get("channel_names")
            d_int = compiled.parsed_params[str(sc["id"])]["dim"]
            if isinstance(cnames, list) and len(cnames) == d_int:
                out_names.extend(str(c) for c in cnames)
            else:
                out_names.extend(f"y{i + 1}" for i in range(d_int))
    elif compiled.plant_nodes:
        p0 = compiled.plant_nodes[0]
        p_dim = compiled.parsed_params[str(p0["id"])]["p"]
        out_names.extend(str(c) for c in p0["params"].get("output_names", [f"y{i + 1}" for i in range(p_dim)]))

    return StateSpace(
        A=maps["Acl"],
        B=maps["Bcl"],
        C=maps["Ccl"],
        D=maps["Dcl"],
        dt=compiled.dt,
        state_names=state_names,
        input_names=in_names,
        output_names=out_names,
        provenance={"source": "pvm_graph_extractor", "code_executed": False},
    )


def simulate_pvm_graph(
    pvm: Mapping[str, Any] | str | bytes | Path,
    t: Any,
    r: Any = None,
    x0: Any = None,
    *,
    method: str = "auto",
    rtol: float = 1e-9,
    atol: float = 1e-12,
    raise_on_error: bool = False,
) -> Result:
    """Simula grafo `.pvm` reconstruindo equações puramente da topologia e `params` (sem exec/eval)."""
    prov: Provenance = build_provenance("control_lab.io.simulate_pvm_graph")
    assumptions: dict[str, Any] = {
        "code_executed": False,
        "structural_graph_evaluation": True,
    }
    diagnostics: dict[str, Any] = {"code_executed": False}
    warnings_out: list[WarningItem] = []

    try:
        pvm_dict = load_pvm(pvm) if not isinstance(pvm, Mapping) else validate_pvm_structure(pvm)
        if pvm_dict["codeContext"]["code"].strip():
            warnings_out.append(
                WarningItem(
                    code="UNTRUSTED_CODE_CONTEXT_IGNORED",
                    message="simulate_pvm_graph ignorou codeContext.code e reconstruiu apenas de graph.nodes/connections.",
                    details={"code_executed": False},
                )
            )

        compiled = _CompiledPVMNetwork(pvm_dict)
        t_arr = ensure_finite_float64(t, ndim=1, name="t")
        N = t_arr.shape[0]
        if N < 1:
            raise ValidationError("Vetor de tempo t deve ter ao menos 1 amostra.")
        if N >= 2 and not np.all(np.diff(t_arr) > 0.0):
            raise ValidationError("Vetor de tempo t deve ser estritamente crescente.")

        # Resolver estado inicial x0
        if x0 is None:
            x0_full = compiled.default_x0()
        else:
            x0_arr = ensure_finite_float64(x0, name="x0")
            if x0_arr.ndim == 2 and 1 in x0_arr.shape:
                x0_arr = x0_arr.ravel()
            elif x0_arr.ndim != 1:
                raise DimensionMismatchError(f"x0 deve ser 1D, recebido shape={x0_arr.shape}.")
            if x0_arr.shape[0] == compiled.n_states_total:
                x0_full = x0_arr
            elif compiled.n_ctrl_states > 0 and x0_arr.shape[0] == compiled.n_plant_states:
                ctrl_x0 = np.concatenate([compiled.parsed_params[str(c["id"])]["x0"] for c in compiled.ctrl_nodes])
                x0_full = np.concatenate([x0_arr, ctrl_x0])
            else:
                raise DimensionMismatchError(
                    f"x0 tem dimensão {x0_arr.shape[0]}, esperado {compiled.n_states_total} "
                    f"(ou {compiled.n_plant_states} para estados da planta)."
                )

        # Resolver sinal de referência r
        m_ref = compiled.n_ref_total
        r_callable: Callable[[float], Any] | None = None
        if r is None:
            r_const = compiled.default_r_constant()
            r_arr = np.tile(r_const, (N, 1))
        elif callable(r):
            if compiled.dt is not None:
                raise ValidationError("Entrada r callable só é suportada em sistema contínuo.")
            r_callable = r

            def _eval_r(tau: float) -> np.ndarray:
                raw_r = r_callable(float(tau))
                if m_ref == 1 and _is_real_number(raw_r):
                    return np.array([float(raw_r)], dtype=np.float64)
                arr_r = ensure_finite_float64(raw_r, name="r(t)")
                if arr_r.ndim == 0 and m_ref == 1:
                    return arr_r.reshape((1,))
                if arr_r.ndim == 2 and arr_r.shape in ((m_ref, 1), (1, m_ref)):
                    return arr_r.reshape((m_ref,))
                if arr_r.ndim == 1 and arr_r.shape == (m_ref,):
                    return arr_r
                raise DimensionMismatchError(f"r({tau}) retornou shape inválido {arr_r.shape}, esperado ({m_ref},).")

            r_arr = np.vstack([_eval_r(float(tk)) for tk in t_arr])
        else:
            r_raw = ensure_finite_float64(r, name="r")
            if r_raw.ndim == 1:
                if m_ref != 1:
                    raise DimensionMismatchError(f"Entrada r 1D exige m_ref=1, grafo possui {m_ref}.")
                if r_raw.shape[0] != N:
                    raise DimensionMismatchError(f"len(r)={r_raw.shape[0]} difere de len(t)={N}.")
                r_arr = r_raw.reshape((N, 1))
            elif r_raw.ndim == 2:
                if r_raw.shape != (N, m_ref):
                    raise DimensionMismatchError(f"r tem shape {r_raw.shape}, esperado ({N}, {m_ref}).")
                r_arr = r_raw
            else:
                raise DimensionMismatchError(f"r deve ser 1D ou 2D, recebido {r_raw.ndim}D.")

        if not compiled.has_enabled_saturation:
            maps = compiled.extract_linear_maps()
            cl_ss = extract_lti_from_pvm(pvm_dict)
            sim_res = simulate_lti(
                cl_ss,
                t_arr,
                u=r_callable if r_callable is not None else r_arr,
                x0=x0_full,
                method=method,
                rtol=rtol,
                atol=atol,
                raise_on_error=True,
            )
            assert sim_res.data is not None
            x_traj = tensor_to_array(sim_res.data["x"], dtype="float64")
            y_traj = tensor_to_array(sim_res.data["y"], dtype="float64")
            W_x_u = maps["W_x"][compiled.plant_u_slice, :]
            W_r_u = maps["W_r"][compiled.plant_u_slice, :]
            u_traj = (x_traj @ W_x_u.T) + (r_arr @ W_r_u.T)
            used_method = f"pvm_linear.{sim_res.diagnostics['method_used']}"
        else:
            eval_fn = compiled.build_nonlinear_evaluator()
            n_tot = compiled.n_states_total
            x_traj = np.zeros((N, n_tot), dtype=np.float64)
            if n_tot > 0:
                x_traj[0, :] = x0_full
            y_traj = np.zeros((N, compiled.n_outputs_total), dtype=np.float64)
            m_u = compiled.plant_u_slice.stop - compiled.plant_u_slice.start
            u_traj = np.zeros((N, m_u), dtype=np.float64)

            if not isinstance(method, str) or not method.strip():
                raise ValidationError(f"method inválido em simulate_pvm_graph: {method!r}.")
            method_norm = method.strip().lower()

            if compiled.dt is not None:
                if method_norm not in ("auto", "discrete", "recurrence"):
                    raise UnsupportedModelError(
                        message=f"Método {method!r} não suportado para simulação discreta com saturação.",
                        parameters={"method": method, "dt": compiled.dt},
                    )
                if N >= 2:
                    diffs = np.diff(t_arr)
                    if not np.allclose(diffs, compiled.dt, rtol=1e-6, atol=1e-12):
                        raise HypothesisViolatedError(
                            f"Espaçamento de t incompatível com dt={compiled.dt} do grafo .pvm."
                        )
                used_method = "pvm_nonlinear_discrete_saturation"
                for k in range(N):
                    x_next, y_k, w_k = eval_fn(x_traj[k, :], r_arr[k, :])
                    y_traj[k, :] = y_k
                    u_traj[k, :] = w_k[compiled.plant_u_slice]
                    if k < N - 1 and n_tot > 0:
                        if not np.all(np.isfinite(x_next)) or float(np.max(np.abs(x_next))) > 1e150:
                            raise NumericalInconclusiveError("Divergência numérica na simulação discreta com saturação.")
                        x_traj[k + 1, :] = x_next
            else:
                if method_norm in ("expm", "zoh", "foh"):
                    raise UnsupportedModelError(
                        message=(
                            f"Método linear {method!r} não é aplicável em grafo .pvm com saturação ativa; "
                            "use 'auto', 'solve_ivp', 'rk45', 'dop853', 'radau' ou 'bdf'."
                        ),
                        parameters={"method": method, "saturation_enabled": True},
                    )
                ivp_map = {
                    "auto": "RK45",
                    "solve_ivp": "RK45",
                    "ivp": "RK45",
                    "rk45": "RK45",
                    "dop853": "DOP853",
                    "radau": "Radau",
                    "bdf": "BDF",
                }
                if method_norm not in ivp_map:
                    raise ValidationError(
                        f"method inválido em simulate_pvm_graph: {method!r}. "
                        "Use 'auto', 'solve_ivp', 'rk45', 'dop853', 'radau' ou 'bdf'."
                    )
                resolved_ivp = ivp_map[method_norm]
                used_method = f"pvm_nonlinear_saturation.{resolved_ivp}"

                def _interp_r(tau: float) -> np.ndarray:
                    if tau <= t_arr[0]:
                        return r_arr[0]
                    if tau >= t_arr[-1]:
                        return r_arr[-1]
                    idx = int(np.searchsorted(t_arr, tau, side="right")) - 1
                    idx = max(0, min(idx, N - 2))
                    alpha = (tau - float(t_arr[idx])) / (float(t_arr[idx + 1]) - float(t_arr[idx]))
                    return (1.0 - alpha) * r_arr[idx] + alpha * r_arr[idx + 1]

                if n_tot > 0 and N >= 2:
                    def _rhs(tau: float, x_vec: np.ndarray) -> np.ndarray:
                        r_t = _eval_r(tau) if r_callable is not None else _interp_r(float(tau))
                        x_dot, _, _ = eval_fn(x_vec, r_t)
                        return x_dot

                    sol = scipy.integrate.solve_ivp(
                        _rhs,
                        (float(t_arr[0]), float(t_arr[-1])),
                        x0_full,
                        method=resolved_ivp,
                        t_eval=t_arr,
                        rtol=float(rtol),
                        atol=float(atol),
                    )
                    if not sol.success or sol.y.shape != (n_tot, N) or not np.all(np.isfinite(sol.y)):
                        raise NumericalInconclusiveError(
                            f"Integrador {resolved_ivp} falhou na simulação não linear .pvm: {sol.message}"
                        )
                    x_traj = np.array(sol.y.T, dtype=np.float64)

                for k in range(N):
                    _, y_k, w_k = eval_fn(x_traj[k, :], r_arr[k, :])
                    y_traj[k, :] = y_k
                    u_traj[k, :] = w_k[compiled.plant_u_slice]

        x_plant = x_traj[:, : compiled.n_plant_states]
        x_ctrl = x_traj[:, compiled.n_plant_states :]
        assumptions.update(
            {
                "domain": "continuous" if compiled.dt is None else "discrete",
                "dt": compiled.dt,
                "saturation_enabled": compiled.has_enabled_saturation,
            }
        )
        diagnostics.update(
            {
                "method_used": used_method,
                "saturation_enabled": compiled.has_enabled_saturation,
                "n_samples": N,
                "n_plant_states": compiled.n_plant_states,
                "n_controller_states": compiled.n_ctrl_states,
                "n_total_states": compiled.n_states_total,
            }
        )
        return Result(
            status="warning" if warnings_out else "success",
            data={
                "t": t_arr,
                "x": x_traj,
                "x_plant": x_plant,
                "x_controller": x_ctrl,
                "u": u_traj,
                "r": r_arr,
                "y": y_traj,
                "dt": compiled.dt,
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=build_provenance(
                f"control_lab.io.simulate_pvm_graph.{used_method}",
                tolerances={"rtol": float(rtol), "atol": float(atol)},
            ),
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=exc.to_typed_error(),
        )


def generate_pathsim_script(
    plant: Any,
    controller: Any = None,
    scenario: Mapping[str, Any] | None = None,
    *,
    raise_on_error: bool = False,
) -> Result:
    """Gera script CPython/PathSim determinístico sem executá-lo (fallback oficial DEC-OPEN-07)."""
    prov: Provenance = build_provenance(
        "control_lab.io.generate_pathsim_script",
        model_revision=getattr(plant, "revision", None),
    )
    assumptions: dict[str, Any] = {
        "requires_explicit_user_execution": True,
        "code_executed": False,
    }
    diagnostics: dict[str, Any] = {
        "plant_type": type(plant).__name__,
        "controller_type": type(controller).__name__ if controller is not None else None,
        "code_executed": False,
    }
    warnings_out: list[WarningItem] = []

    try:
        sc = ensure_json_finite(dict(scenario), path="$.scenario") if scenario is not None else {}
        duration = float(sc.get("duration", 10.0))
        dt_sim = float(sc.get("dt", getattr(plant, "dt", None) or 0.01))
        lines: list[str] = [
            '"""Script de referência CPython/PathSim gerado pelo ControlLab Web (execução manual explícita)."""',
            "import numpy as np",
            "import scipy.integrate",
            "",
        ]

        if isinstance(plant, TSStateSpace):
            if controller is not None:
                if not isinstance(controller, PDCController):
                    raise UnsupportedModelError(
                        f"generate_pathsim_script não suporta ({type(plant).__name__}, {type(controller).__name__})."
                    )
                validate_interconnection(
                    plant,
                    controller,
                    wiring=sc.get("wiring"),
                    sign_convention=sc.get("sign_convention"),
                    premise_estimator=sc.get("premise_estimator"),
                    raise_on_error=True,
                )
            warnings_out.append(
                WarningItem(
                    code="DEC_OPEN_07_FALLBACK_SCRIPT",
                    message="Script CPython gerado como fallback para TSStateSpace/PDC (DEC-OPEN-07).",
                )
            )
            lines.append(f"# TSStateSpace kind={plant.kind!r}, dt={plant.dt!r}, vertices={plant.n_vertices}")
            lines.append(f"dt = {plant.dt!r}")
            lines.append("A_vertices = [")
            for v in plant.vertices:
                lines.append(f"    np.array({v['A'].tolist()!r}, dtype=np.float64),")
            lines.append("]")
            lines.append("B_vertices = [")
            for v in plant.vertices:
                lines.append(f"    np.array({v['B'].tolist()!r}, dtype=np.float64),")
            lines.append("]")
            if isinstance(controller, PDCController):
                sign_str = sc.get("sign_convention") or controller.feedback_sign
                s_val = -1.0 if sign_str == "negative" else 1.0
                lines.append(f"feedback_sign = {sign_str!r}")
                lines.append(f"sign_factor = {s_val!r}")
                lines.append("K_vertices = [")
                for k_mat in controller.K_i:
                    lines.append(f"    np.array({k_mat.tolist()!r}, dtype=np.float64),")
                lines.append("]")
                lines.extend(
                    [
                        "",
                        "def ts_pdc_rhs(x: np.ndarray, h: np.ndarray, u_ff: np.ndarray) -> np.ndarray:",
                        "    dx = np.zeros_like(x, dtype=np.float64)",
                        "    for i, (Ai, Bi) in enumerate(zip(A_vertices, B_vertices)):",
                        "        dx += h[i] * (Ai @ x + Bi @ u_ff)",
                        "        for j, Kj in enumerate(K_vertices):",
                        "            dx += h[i] * h[j] * (sign_factor * (Bi @ (Kj @ x)))",
                        "    return dx",
                    ]
                )
        elif isinstance(plant, FuzzySystem) or isinstance(controller, FuzzySystem):
            fz = plant if isinstance(plant, FuzzySystem) else controller
            assert isinstance(fz, FuzzySystem)
            warnings_out.append(
                WarningItem(
                    code="DEC_OPEN_07_FALLBACK_SCRIPT",
                    message="Script CPython gerado como fallback para FuzzySystem (DEC-OPEN-07).",
                )
            )
            lines.append(f"# FuzzySystem id={fz.id!r}, inference_type={fz.inference_type!r}, is_dynamic_model={fz.is_dynamic_model!r}")
            lines.append(f"fuzzy_spec = {fz.to_dict()!r}")
        elif isinstance(plant, StateSpace):
            pvm_res = make_pvm(plant, controller=controller, scenario=sc, return_result=True, raise_on_error=True)
            assert pvm_res.data is not None
            pvm_dict = pvm_res.data["pvm"]
            lines.append(pvm_dict["codeContext"]["code"].rstrip())
            lines.extend(
                [
                    "",
                    f"duration = {duration!r}",
                    f"dt_sim = {dt_sim!r}",
                    "t_grid = np.arange(0.0, duration + 0.5 * dt_sim, dt_sim)",
                ]
            )
        else:
            raise UnsupportedModelError(
                f"generate_pathsim_script não suporta modelo do tipo {type(plant).__name__}."
            )

        script = "\n".join(lines) + "\n"
        return Result(
            status="warning" if warnings_out else "success",
            data={
                "script": script,
                "language": "python",
                "requires_explicit_user_execution": True,
                "code_executed": False,
            },
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=None,
        )
    except ControlLabError as exc:
        if raise_on_error:
            raise
        return Result(
            status="failure",
            data=None,
            assumptions=assumptions,
            diagnostics=diagnostics,
            provenance=prov,
            warnings=tuple(warnings_out),
            error=exc.to_typed_error(),
        )
