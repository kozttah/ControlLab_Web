"""Representação canônica de problemas SDP/LMI, compilador da DSL e exportador CPython.

Formato canônico (CL-DIR-001 Seção 6.1):
    min_{x in R^K}   c^T x + c_0
    sujeito a        F_b(x) = F_{b,0} + sum_{k=0}^{K-1} x_k F_{b,k} >= 0   (blocos PSD simétricos, b = 0..B-1)
                     E x = d                                               (igualdades lineares)
                     H x <= h                                              (desigualdades lineares)
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.core.tensors import array_to_tensor, ensure_finite_float64, tensor_to_array
from control_lab.diagnostics import (
    DimensionMismatchError,
    ValidationError,
    ensure_json_finite,
    strict_json_dumps,
    strict_json_loads,
)

from .dsl import (
    AffineExpr,
    LMIBlockConstraint,
    LinearEqConstraint,
    LinearIneqConstraint,
    SDPVar,
    _is_scalar_number,
)
from .svec import DEFAULT_SYMMETRY_TOL, is_diagonal_matrix, symmetry_error_rel


class SDPBlock:
    """Bloco simétrico semidefinido positivo F_b(x) = F_{b,0} + sum_k x_k F_{b,k} >= 0."""

    def __init__(
        self,
        name: str,
        F0: Any,
        F_k: Sequence[Any] | Mapping[int, Any],
        *,
        n_vars: int | None = None,
        sym_tol: float = DEFAULT_SYMMETRY_TOL,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Nome do bloco SDP deve ser string não vazia.")
        self._name = name.strip()

        F0_arr = ensure_finite_float64(F0, ndim=2, name=f"block[{self._name}].F0")
        nb, nb2 = F0_arr.shape
        if nb != nb2 or nb < 1:
            raise DimensionMismatchError(
                message=f"Bloco PSD {self._name!r} deve ser quadrado n x n (n >= 1), recebido {F0_arr.shape}.",
                parameters={"block": self._name, "shape": list(F0_arr.shape)},
            )
        sym0 = symmetry_error_rel(F0_arr)
        if sym0 > sym_tol:
            raise ValidationError(
                message=f"F0 do bloco {self._name!r} não é simétrica (erro={sym0:.3e} > {sym_tol:.1e}).",
                parameters={"block": self._name, "symmetry_error": sym0},
            )
        F0_sym = 0.5 * (F0_arr + F0_arr.T)
        F0_sym.setflags(write=False)

        terms: dict[int, np.ndarray] = {}
        if isinstance(F_k, Mapping):
            if n_vars is None:
                raise ValidationError("n_vars é obrigatório quando F_k é fornecido como Mapping esparso.")
            resolved_n_vars = int(n_vars)
            items = F_k.items()
        elif isinstance(F_k, Sequence) and not isinstance(F_k, (str, bytes)):
            resolved_n_vars = len(F_k) if n_vars is None else int(n_vars)
            if len(F_k) != resolved_n_vars:
                raise DimensionMismatchError(
                    f"Bloco {self._name!r}: len(F_k)={len(F_k)} difere de n_vars={resolved_n_vars}."
                )
            items = enumerate(F_k)
        else:
            raise ValidationError("F_k deve ser Sequence ou Mapping[int, matrix].")

        if resolved_n_vars < 1:
            raise ValidationError("SDPBlock requer n_vars >= 1.")

        diag_flag = is_diagonal_matrix(F0_sym)
        for k, raw_fk in items:
            if isinstance(k, bool) or not isinstance(k, int) or k < 0 or k >= resolved_n_vars:
                raise ValidationError(f"Índice de variável inválido em bloco {self._name!r}: {k!r}.")
            fk_arr = ensure_finite_float64(raw_fk, ndim=2, shape=(nb, nb), name=f"block[{self._name}].F_k[{k}]")
            sym_k = symmetry_error_rel(fk_arr)
            if sym_k > sym_tol:
                raise ValidationError(
                    message=f"F_k[{k}] do bloco {self._name!r} não é simétrica (erro={sym_k:.3e} > {sym_tol:.1e}).",
                    parameters={"block": self._name, "var_index": k, "symmetry_error": sym_k},
                )
            fk_sym = 0.5 * (fk_arr + fk_arr.T)
            if np.any(fk_sym != 0.0):
                if diag_flag and not is_diagonal_matrix(fk_sym):
                    diag_flag = False
                fk_sym.setflags(write=False)
                terms[k] = fk_sym

        self._dim = nb
        self._n_vars = resolved_n_vars
        self._F0 = F0_sym
        self._F_terms = terms
        self._is_diagonal = diag_flag

    @property
    def name(self) -> str:
        return self._name

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def n_vars(self) -> int:
        return self._n_vars

    @property
    def F0(self) -> np.ndarray:
        return self._F0

    @property
    def F_terms(self) -> dict[int, np.ndarray]:
        return dict(self._F_terms)

    @property
    def is_diagonal(self) -> bool:
        return self._is_diagonal

    def get_Fk(self, k: int) -> np.ndarray:
        if k in self._F_terms:
            return self._F_terms[k]
        z = np.zeros((self._dim, self._dim), dtype=np.float64)
        z.setflags(write=False)
        return z

    @property
    def F_k(self) -> tuple[np.ndarray, ...]:
        return tuple(self.get_Fk(k) for k in range(self._n_vars))

    def evaluate(self, x: Sequence[float] | np.ndarray) -> np.ndarray:
        x_vec = ensure_finite_float64(x, ndim=1, shape=(self._n_vars,), name="x")
        res = self._F0.copy()
        for k, fk in self._F_terms.items():
            xk = float(x_vec[k])
            if xk != 0.0:
                res = res + xk * fk
        return 0.5 * (res + res.T)

    def evaluate_linear(self, d: Sequence[float] | np.ndarray) -> np.ndarray:
        d_vec = ensure_finite_float64(d, ndim=1, shape=(self._n_vars,), name="d")
        res = np.zeros((self._dim, self._dim), dtype=np.float64)
        for k, fk in self._F_terms.items():
            dk = float(d_vec[k])
            if dk != 0.0:
                res = res + dk * fk
        return 0.5 * (res + res.T)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "dim": self._dim,
            "F0": array_to_tensor(self._F0, dtype="float64", order="C"),
            "F_k": [array_to_tensor(self.get_Fk(k), dtype="float64", order="C") for k in range(self._n_vars)],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, n_vars: int | None = None) -> SDPBlock:
        if not isinstance(data, Mapping):
            raise ValidationError("SDPBlock serializado deve ser dict.")
        if "name" not in data or "F0" not in data or "F_k" not in data:
            raise ValidationError("SDPBlock requer campos 'name', 'F0' e 'F_k'.")
        F0_raw = data["F0"]
        F0 = tensor_to_array(F0_raw, expected_ndim=2, dtype="float64") if isinstance(F0_raw, Mapping) else F0_raw
        fk_list = []
        for item in data["F_k"]:
            fk_list.append(tensor_to_array(item, expected_ndim=2, dtype="float64") if isinstance(item, Mapping) else item)
        return cls(name=str(data["name"]), F0=F0, F_k=fk_list, n_vars=n_vars)


class CanonicalSDPProblem:
    """Problema SDP/LMI canônico desacoplado de qualquer solver específico."""

    def __init__(
        self,
        *,
        c: Any,
        c0: float = 0.0,
        blocks: Sequence[SDPBlock] = (),
        E: Any = None,
        d: Any = None,
        H: Any = None,
        h: Any = None,
        variable_map: Mapping[str, Any] | None = None,
        constraint_map: Mapping[str, Any] | None = None,
        scaling: Mapping[str, Any] | None = None,
        recovery_plan: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        name: str = "canonical_sdp",
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Nome do CanonicalSDPProblem deve ser string não vazia.")
        self._name = name.strip()

        c_arr = ensure_finite_float64(c, ndim=1, name="c")
        n_vars = int(c_arr.shape[0])
        if n_vars < 1:
            raise ValidationError("CanonicalSDPProblem requer pelo menos 1 variável de decisão (n_vars >= 1).")
        c_arr.setflags(write=False)

        if not _is_scalar_number(c0) or not math.isfinite(float(c0)):
            raise ValidationError(f"Termo constante c0 deve ser escalar finito, recebido {c0!r}.")
        self._c = c_arr
        self._c0 = float(c0)
        self._n_vars = n_vars

        parsed_blocks: list[SDPBlock] = []
        for idx, blk in enumerate(blocks):
            if not isinstance(blk, SDPBlock):
                raise ValidationError(f"blocks[{idx}] deve ser instância de SDPBlock.")
            if blk.n_vars != n_vars:
                raise DimensionMismatchError(
                    f"Bloco {blk.name!r} tem n_vars={blk.n_vars}, esperado {n_vars}."
                )
            parsed_blocks.append(blk)
        self._blocks = tuple(parsed_blocks)

        if E is None and d is None:
            E_arr = np.zeros((0, n_vars), dtype=np.float64)
            d_arr = np.zeros((0,), dtype=np.float64)
        elif E is not None and d is not None:
            E_arr = ensure_finite_float64(E, ndim=2, name="E")
            if E_arr.shape[1] != n_vars:
                raise DimensionMismatchError(f"Matriz E deve ter {n_vars} colunas, recebido shape={E_arr.shape}.")
            d_arr = ensure_finite_float64(d, ndim=1, shape=(E_arr.shape[0],), name="d")
        else:
            raise ValidationError("Matrizes E e d de igualdade devem ser fornecidas em par.")

        if H is None and h is None:
            H_arr = np.zeros((0, n_vars), dtype=np.float64)
            h_arr = np.zeros((0,), dtype=np.float64)
        elif H is not None and h is not None:
            H_arr = ensure_finite_float64(H, ndim=2, name="H")
            if H_arr.shape[1] != n_vars:
                raise DimensionMismatchError(f"Matriz H deve ter {n_vars} colunas, recebido shape={H_arr.shape}.")
            h_arr = ensure_finite_float64(h, ndim=1, shape=(H_arr.shape[0],), name="h")
        else:
            raise ValidationError("Matrizes H e h de desigualdade devem ser fornecidas em par.")

        for arr in (E_arr, d_arr, H_arr, h_arr):
            arr.setflags(write=False)

        self._E = E_arr
        self._d = d_arr
        self._H = H_arr
        self._h = h_arr

        if variable_map is None:
            self._variable_map: dict[str, Any] = {
                "x": {
                    "name": "x",
                    "shape": [n_vars, 1],
                    "symmetric": False,
                    "offset": 0,
                    "size": n_vars,
                    "coords": [[i, 0] for i in range(n_vars)],
                }
            }
        else:
            self._variable_map = ensure_json_finite(dict(variable_map), path="$.variable_map")

        if constraint_map is None:
            self._constraint_map: dict[str, Any] = {
                "blocks": [
                    {"index": i, "name": blk.name, "dim": blk.dim, "is_diagonal": blk.is_diagonal}
                    for i, blk in enumerate(self._blocks)
                ],
                "n_eq": int(self._E.shape[0]),
                "n_ineq": int(self._H.shape[0]),
            }
        else:
            self._constraint_map = ensure_json_finite(dict(constraint_map), path="$.constraint_map")

        self._scaling = (
            ensure_json_finite(dict(scaling), path="$.scaling")
            if scaling is not None
            else {"normalized": False, "block_scales": [1.0] * len(self._blocks)}
        )
        self._recovery_plan = (
            ensure_json_finite(dict(recovery_plan), path="$.recovery_plan")
            if recovery_plan is not None
            else {}
        )
        self._metadata = (
            ensure_json_finite(dict(metadata), path="$.metadata")
            if metadata is not None
            else {}
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def n_vars(self) -> int:
        return self._n_vars

    @property
    def c(self) -> np.ndarray:
        return self._c

    @property
    def c0(self) -> float:
        return self._c0

    @property
    def blocks(self) -> tuple[SDPBlock, ...]:
        return self._blocks

    @property
    def E(self) -> np.ndarray:
        return self._E

    @property
    def d(self) -> np.ndarray:
        return self._d

    @property
    def H(self) -> np.ndarray:
        return self._H

    @property
    def h(self) -> np.ndarray:
        return self._h

    @property
    def n_blocks(self) -> int:
        return len(self._blocks)

    @property
    def n_eq(self) -> int:
        return int(self._E.shape[0])

    @property
    def n_ineq(self) -> int:
        return int(self._H.shape[0])

    @property
    def variable_map(self) -> dict[str, Any]:
        return copy.deepcopy(self._variable_map)

    @property
    def constraint_map(self) -> dict[str, Any]:
        return copy.deepcopy(self._constraint_map)

    @property
    def scaling(self) -> dict[str, Any]:
        return copy.deepcopy(self._scaling)

    @property
    def recovery_plan(self) -> dict[str, Any]:
        return copy.deepcopy(self._recovery_plan)

    @property
    def metadata(self) -> dict[str, Any]:
        return copy.deepcopy(self._metadata)

    def all_blocks_diagonal(self) -> bool:
        return all(blk.is_diagonal for blk in self._blocks)

    def evaluate_objective(self, x: Sequence[float] | np.ndarray) -> float:
        x_vec = ensure_finite_float64(x, ndim=1, shape=(self._n_vars,), name="x")
        return float(np.dot(self._c, x_vec) + self._c0)

    def evaluate_blocks(self, x: Sequence[float] | np.ndarray) -> list[np.ndarray]:
        x_vec = ensure_finite_float64(x, ndim=1, shape=(self._n_vars,), name="x")
        return [blk.evaluate(x_vec) for blk in self._blocks]

    def evaluate_equalities(self, x: Sequence[float] | np.ndarray) -> np.ndarray:
        x_vec = ensure_finite_float64(x, ndim=1, shape=(self._n_vars,), name="x")
        if self._E.shape[0] == 0:
            return np.zeros((0,), dtype=np.float64)
        return self._E @ x_vec - self._d

    def evaluate_inequalities(self, x: Sequence[float] | np.ndarray) -> np.ndarray:
        x_vec = ensure_finite_float64(x, ndim=1, shape=(self._n_vars,), name="x")
        if self._H.shape[0] == 0:
            return np.zeros((0,), dtype=np.float64)
        return self._H @ x_vec - self._h

    def reconstruct_variable(self, var_name: str, x: Sequence[float] | np.ndarray) -> np.ndarray:
        if var_name not in self._variable_map:
            raise ValidationError(
                message=f"Variável {var_name!r} não encontrada em variable_map.",
                parameters={"var_name": var_name, "available": sorted(self._variable_map.keys())},
            )
        x_vec = ensure_finite_float64(x, ndim=1, shape=(self._n_vars,), name="x")
        meta = self._variable_map[var_name]
        offset = int(meta["offset"])
        size = int(meta["size"])
        r, c_dim = int(meta["shape"][0]), int(meta["shape"][1])
        symmetric = bool(meta["symmetric"])
        coords = meta["coords"]
        sl = x_vec[offset : offset + size]
        mat = np.zeros((r, c_dim), dtype=np.float64)
        for idx, (i, j) in enumerate(coords):
            val = float(sl[idx])
            mat[int(i), int(j)] = val
            if symmetric:
                mat[int(j), int(i)] = val
        return mat

    def reconstruct_variables(self, x: Sequence[float] | np.ndarray) -> dict[str, np.ndarray]:
        x_vec = ensure_finite_float64(x, ndim=1, shape=(self._n_vars,), name="x")
        return {vname: self.reconstruct_variable(vname, x_vec) for vname in self._variable_map}

    def estimate_data_scale_ratio(self) -> float:
        """Razão entre maior e menor magnitude não nula dos dados canônicos."""
        mags: list[float] = []
        for arr in (self._c, self._E, self._d, self._H, self._h):
            if arr.size > 0:
                nz = np.abs(arr[arr != 0.0])
                if nz.size > 0:
                    mags.append(float(np.max(nz)))
                    mags.append(float(np.min(nz)))
        for blk in self._blocks:
            for mat in (blk.F0, *blk.F_terms.values()):
                nz = np.abs(mat[mat != 0.0])
                if nz.size > 0:
                    mags.append(float(np.max(nz)))
                    mags.append(float(np.min(nz)))
        if not mags:
            return 1.0
        max_m = max(mags)
        min_m = min(mags)
        return float(max_m / min_m) if min_m > 0.0 else 1.0

    def to_dict(self) -> dict[str, Any]:
        return ensure_json_finite(
            {
                "schema_version": "1.0.0",
                "name": self._name,
                "n_vars": self._n_vars,
                "c": array_to_tensor(self._c, dtype="float64", order="C"),
                "c0": self._c0,
                "blocks": [blk.to_dict() for blk in self._blocks],
                "E": array_to_tensor(self._E, dtype="float64", order="C") if self._E.shape[0] > 0 else None,
                "d": array_to_tensor(self._d, dtype="float64", order="C") if self._d.shape[0] > 0 else None,
                "H": array_to_tensor(self._H, dtype="float64", order="C") if self._H.shape[0] > 0 else None,
                "h": array_to_tensor(self._h, dtype="float64", order="C") if self._h.shape[0] > 0 else None,
                "variable_map": self._variable_map,
                "constraint_map": self._constraint_map,
                "scaling": self._scaling,
                "recovery_plan": self._recovery_plan,
                "metadata": self._metadata,
            }
        )

    def to_json(self, *, indent: int | None = None, sort_keys: bool = True) -> str:
        return strict_json_dumps(self.to_dict(), indent=indent, sort_keys=sort_keys)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CanonicalSDPProblem:
        if not isinstance(payload, Mapping):
            raise ValidationError("CanonicalSDPProblem serializado deve ser dict.")
        c_raw = payload["c"]
        c_arr = tensor_to_array(c_raw, expected_ndim=1, dtype="float64") if isinstance(c_raw, Mapping) else c_raw
        n_vars = int(np.asarray(c_arr).shape[0])
        blocks = [SDPBlock.from_dict(b, n_vars=n_vars) for b in payload.get("blocks", ())]
        E_raw = payload.get("E")
        d_raw = payload.get("d")
        H_raw = payload.get("H")
        h_raw = payload.get("h")
        E = tensor_to_array(E_raw, expected_ndim=2, dtype="float64") if isinstance(E_raw, Mapping) else E_raw
        d = tensor_to_array(d_raw, expected_ndim=1, dtype="float64") if isinstance(d_raw, Mapping) else d_raw
        H = tensor_to_array(H_raw, expected_ndim=2, dtype="float64") if isinstance(H_raw, Mapping) else H_raw
        h = tensor_to_array(h_raw, expected_ndim=1, dtype="float64") if isinstance(h_raw, Mapping) else h_raw
        return cls(
            c=c_arr,
            c0=float(payload.get("c0", 0.0)),
            blocks=blocks,
            E=E,
            d=d,
            H=H,
            h=h,
            variable_map=payload.get("variable_map"),
            constraint_map=payload.get("constraint_map"),
            scaling=payload.get("scaling"),
            recovery_plan=payload.get("recovery_plan"),
            metadata=payload.get("metadata"),
            name=str(payload.get("name", "canonical_sdp")),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> CanonicalSDPProblem:
        return cls.from_dict(strict_json_loads(raw))

    @classmethod
    def from_fixture_case(cls, case: Mapping[str, Any]) -> CanonicalSDPProblem:
        """Constrói CanonicalSDPProblem a partir de um caso da fixture B-SDP-A-D.json."""
        if not isinstance(case, Mapping) or "canonical_sdp" not in case:
            raise ValidationError("Caso de fixture deve conter campo 'canonical_sdp'.")
        csdp = case["canonical_sdp"]
        c_arr = ensure_finite_float64(csdp["c"], ndim=1, name="canonical_sdp.c")
        n_vars = int(c_arr.shape[0])
        blocks: list[SDPBlock] = []
        for idx, b in enumerate(csdp["blocks"]):
            F0 = tensor_to_array(b["F0"], expected_ndim=2, dtype="float64")
            F_k = [tensor_to_array(fk, expected_ndim=2, dtype="float64") for fk in b["F_k"]]
            blocks.append(SDPBlock(name=str(b.get("name", f"block_{idx}")), F0=F0, F_k=F_k, n_vars=n_vars))
        return cls(
            c=c_arr,
            c0=float(csdp.get("c0", 0.0)),
            blocks=blocks,
            name=str(case.get("test_id", "fixture_case")),
            metadata={
                "test_id": case.get("test_id"),
                "level": case.get("level"),
                "description": case.get("description"),
            },
        )

    def export_cpython_script(self, backend: str = "clarabel_direct") -> str:
        """Exporta script CPython autônomo reproduzível para resolver este CanonicalSDPProblem.

        Não executa nem interpreta código dinâmico; gera apenas texto Python determinístico
        com dados finitos serializados para execução local pelo usuário (contingência G-0B).
        """
        if backend not in ("clarabel_direct", "clarabel_cvxpy"):
            raise ValidationError(
                f"backend de exportação CPython inválido: {backend!r}. Use 'clarabel_direct' ou 'clarabel_cvxpy'."
            )
        serialized = self.to_dict()
        payload_json = json.dumps(serialized, indent=2, ensure_ascii=False, allow_nan=False)

        header = [
            "#!/usr/bin/env python3",
            f'"""Script CPython autônomo exportado por ControlLab Web para o problema {self._name!r}."""',
            "",
            "import json",
            "import math",
            "import numpy as np",
            "import scipy.sparse as sp",
            "",
            f"PROBLEM_PAYLOAD = json.loads({json.dumps(payload_json)})",
            "",
            "def _tensor_to_array(t):",
            "    return np.array(t['data'], dtype=np.float64).reshape(tuple(t['shape']), order=t['order'])",
            "",
            "def svec(M):",
            "    n = M.shape[0]",
            "    s2 = math.sqrt(2.0)",
            "    out = []",
            "    for j in range(n):",
            "        for i in range(j):",
            "            out.append(s2 * 0.5 * (M[i, j] + M[j, i]))",
            "        out.append(M[j, j])",
            "    return np.array(out, dtype=np.float64)",
            "",
            "def smat(v, n):",
            "    inv_s2 = 1.0 / math.sqrt(2.0)",
            "    M = np.zeros((n, n), dtype=np.float64)",
            "    idx = 0",
            "    for j in range(n):",
            "        for i in range(j):",
            "            val = inv_s2 * v[idx]",
            "            M[i, j] = val",
            "            M[j, i] = val",
            "            idx += 1",
            "        M[j, j] = v[idx]",
            "        idx += 1",
            "    return M",
            "",
            "c = _tensor_to_array(PROBLEM_PAYLOAD['c'])",
            "c0 = float(PROBLEM_PAYLOAD['c0'])",
            "n_vars = int(PROBLEM_PAYLOAD['n_vars'])",
            "blocks = PROBLEM_PAYLOAD['blocks']",
            "E = _tensor_to_array(PROBLEM_PAYLOAD['E']) if PROBLEM_PAYLOAD['E'] is not None else np.zeros((0, n_vars))",
            "d = _tensor_to_array(PROBLEM_PAYLOAD['d']) if PROBLEM_PAYLOAD['d'] is not None else np.zeros((0,))",
            "H = _tensor_to_array(PROBLEM_PAYLOAD['H']) if PROBLEM_PAYLOAD['H'] is not None else np.zeros((0, n_vars))",
            "h = _tensor_to_array(PROBLEM_PAYLOAD['h']) if PROBLEM_PAYLOAD['h'] is not None else np.zeros((0,))",
            "",
        ]

        if backend == "clarabel_direct":
            body = [
                "import clarabel",
                "",
                "A_rows = []",
                "b_parts = []",
                "cones = []",
                "if E.shape[0] > 0:",
                "    A_rows.append(E)",
                "    b_parts.append(d)",
                "    cones.append(clarabel.ZeroConeT(E.shape[0]))",
                "if H.shape[0] > 0:",
                "    A_rows.append(H)",
                "    b_parts.append(h)",
                "    cones.append(clarabel.NonnegativeConeT(H.shape[0]))",
                "for blk in blocks:",
                "    F0 = _tensor_to_array(blk['F0'])",
                "    Fk_list = [_tensor_to_array(fk) for fk in blk['F_k']]",
                "    A_blk = -np.column_stack([svec(fk) for fk in Fk_list])",
                "    A_rows.append(A_blk)",
                "    b_parts.append(svec(F0))",
                "    cones.append(clarabel.PSDTriangleConeT(F0.shape[0]))",
                "",
                "A_mat = sp.csc_matrix(np.vstack(A_rows)) if A_rows else sp.csc_matrix((0, n_vars))",
                "b_vec = np.concatenate(b_parts) if b_parts else np.zeros((0,), dtype=np.float64)",
                "P_mat = sp.csc_matrix((n_vars, n_vars))",
                "settings = clarabel.DefaultSettings()",
                "settings.verbose = False",
                "solver = clarabel.DefaultSolver(P_mat, c, A_mat, b_vec, cones, settings)",
                "sol = solver.solve()",
                "print('status:', sol.status)",
                "print('x:', sol.x)",
                "print('obj_val:', sol.obj_val + c0 if np.isfinite(sol.obj_val) else None)",
            ]
        else:
            body = [
                "import cvxpy as cp",
                "",
                "x = cp.Variable(n_vars)",
                "cons = []",
                "if E.shape[0] > 0:",
                "    cons.append(E @ x == d)",
                "if H.shape[0] > 0:",
                "    cons.append(H @ x <= h)",
                "for blk in blocks:",
                "    F0 = _tensor_to_array(blk['F0'])",
                "    expr = F0",
                "    for k, fk_t in enumerate(blk['F_k']):",
                "        fk = _tensor_to_array(fk_t)",
                "        if np.any(fk != 0.0):",
                "            expr = expr + x[k] * fk",
                "    cons.append(expr >> 0)",
                "",
                "prob = cp.Problem(cp.Minimize(c @ x + c0), cons)",
                "prob.solve(solver=cp.CLARABEL, verbose=False)",
                "print('status:', prob.status)",
                "print('x:', x.value)",
                "print('obj_val:', prob.value)",
            ]

        return "\n".join(header + body) + "\n"


def compile(
    objective: AffineExpr | float | int | None = None,
    constraints: Sequence[LMIBlockConstraint | LinearEqConstraint | LinearIneqConstraint] = (),
    *,
    sense: str = "minimize",
    name: str | None = None,
    scaling: Mapping[str, Any] | None = None,
    recovery_plan: Mapping[str, Any] | None = None,
    variables: Sequence[SDPVar] | None = None,
    metadata: Mapping[str, Any] | None = None,
    sym_tol: float = DEFAULT_SYMMETRY_TOL,
) -> CanonicalSDPProblem:
    """Compila objetivo afim e restrições LMI/lineares no CanonicalSDPProblem."""
    if sense not in ("minimize", "maximize"):
        raise ValidationError(f"sense deve ser 'minimize' ou 'maximize', recebido {sense!r}.")

    if objective is None:
        obj_expr = AffineExpr(np.zeros((1, 1), dtype=np.float64))
    elif _is_scalar_number(objective):
        fobj = float(objective)
        if not math.isfinite(fobj):
            raise ValidationError(f"Objetivo constante não finito: {objective!r}.")
        obj_expr = AffineExpr(np.array([[fobj]], dtype=np.float64))
    elif isinstance(objective, AffineExpr):
        if objective.shape != (1, 1):
            raise DimensionMismatchError(
                message=f"Função objetivo deve ser escalar (1, 1), recebido shape={objective.shape}.",
                parameters={"objective_shape": list(objective.shape)},
            )
        obj_expr = objective
    else:
        raise ValidationError(
            f"objective deve ser AffineExpr (1, 1), escalar numérico ou None, recebido {type(objective).__name__}."
        )

    if isinstance(constraints, (str, bytes, Mapping)) or not isinstance(constraints, Sequence):
        raise ValidationError("constraints deve ser sequência de restrições LMI/lineares.")

    # Coletar variáveis e validar tipos de restrição
    vars_found: dict[int, SDPVar] = {}
    vars_found.update(obj_expr.variables)

    lmi_cons: list[LMIBlockConstraint] = []
    eq_cons: list[LinearEqConstraint] = []
    ineq_cons: list[LinearIneqConstraint] = []

    for idx, con in enumerate(constraints):
        if isinstance(con, LMIBlockConstraint):
            lmi_cons.append(con)
            vars_found.update(con.expr.variables)
        elif isinstance(con, LinearEqConstraint):
            eq_cons.append(con)
            vars_found.update(con.expr.variables)
        elif isinstance(con, LinearIneqConstraint):
            ineq_cons.append(con)
            vars_found.update(con.expr.variables)
        else:
            raise ValidationError(
                message=(
                    f"Restrição inválida em constraints[{idx}]: {type(con).__name__}. "
                    "Esperado LMIBlockConstraint, LinearEqConstraint ou LinearIneqConstraint."
                ),
                parameters={"index": idx, "type": type(con).__name__},
            )

    if variables is not None:
        for v in variables:
            if not isinstance(v, SDPVar):
                raise ValidationError(f"Item inválido em variables: {type(v).__name__}, esperado SDPVar.")
            vars_found[v.var_id] = v

    if len(vars_found) == 0:
        raise ValidationError(
            message="Nenhuma variável de decisão (sdpvar) encontrada no objetivo ou restrições.",
            next_step="Declare ao menos uma variável com sdpvar() em objective ou constraints.",
        )

    ordered_vars = [vars_found[vid] for vid in sorted(vars_found.keys())]
    seen_names: set[str] = set()
    variable_map: dict[str, Any] = {}
    key_to_global: dict[tuple[int, int], int] = {}
    offset = 0

    for var in ordered_vars:
        if var.name in seen_names:
            raise ValidationError(
                message=f"Nomes duplicados de variáveis SDPVar no mesmo problema: {var.name!r}.",
                parameters={"duplicate_name": var.name},
                next_step="Atribua nomes distintos a cada sdpvar() do problema.",
            )
        seen_names.add(var.name)
        for local_idx in range(var.local_size):
            key_to_global[(var.var_id, local_idx)] = offset + local_idx
        variable_map[var.name] = {
            "name": var.name,
            "var_id": var.var_id,
            "shape": [var.shape[0], var.shape[1]],
            "symmetric": var.symmetric,
            "offset": offset,
            "size": var.local_size,
            "coords": [[int(i), int(j)] for (i, j) in var.coord_map],
        }
        offset += var.local_size

    n_vars = offset

    # Objetivo: sempre canonizado para minimização c^T x + c0
    sign_obj = 1.0 if sense == "minimize" else -1.0
    c_vec = np.zeros((n_vars,), dtype=np.float64)
    c0_val = sign_obj * float(obj_expr.const[0, 0])
    for key, mat in obj_expr.terms.items():
        c_vec[key_to_global[key]] = sign_obj * float(mat[0, 0])

    # Blocos PSD
    normalize_blocks = bool(scaling.get("normalize_blocks", False)) if scaling is not None else False
    block_scales: list[float] = []
    blocks: list[SDPBlock] = []
    block_meta: list[dict[str, Any]] = []

    for b_idx, con in enumerate(lmi_cons):
        b_name = con.name or f"lmi_{b_idx}"
        F0 = con.expr.const
        F_terms_global: dict[int, np.ndarray] = {}
        max_norm = float(np.linalg.norm(F0, "fro"))
        for key, mat in con.expr.terms.items():
            gk = key_to_global[key]
            F_terms_global[gk] = mat
            max_norm = max(max_norm, float(np.linalg.norm(mat, "fro")))

        b_scale = 1.0
        if normalize_blocks and max_norm > 0.0:
            b_scale = max_norm
            F0_scaled = F0 / b_scale
            F_terms_scaled = {gk: mat / b_scale for gk, mat in F_terms_global.items()}
        else:
            F0_scaled = F0
            F_terms_scaled = F_terms_global

        block_scales.append(float(b_scale))
        blk = SDPBlock(b_name, F0_scaled, F_terms_scaled, n_vars=n_vars, sym_tol=sym_tol)
        blocks.append(blk)
        block_meta.append(
            {
                "index": b_idx,
                "name": b_name,
                "dim": blk.dim,
                "is_diagonal": blk.is_diagonal,
                "scale": float(b_scale),
            }
        )

    # Igualdades lineares: expr(x) == 0 -> C_0 + sum_k x_k C_k == 0 -> E x = d (E_row = C_k_entry, d_entry = -C_0_entry)
    eq_rows: list[np.ndarray] = []
    d_vals: list[float] = []
    eq_names: list[str] = []
    for e_idx, con in enumerate(eq_cons):
        r, c_dim = con.expr.shape
        ename = con.name or f"eq_{e_idx}"
        for i in range(r):
            for j in range(c_dim):
                row = np.zeros((n_vars,), dtype=np.float64)
                for key, mat in con.expr.terms.items():
                    val = float(mat[i, j])
                    if val != 0.0:
                        row[key_to_global[key]] = val
                eq_rows.append(row)
                d_vals.append(-float(con.expr.const[i, j]))
                eq_names.append(f"{ename}[{i},{j}]")

    E_mat = np.vstack(eq_rows) if eq_rows else None
    d_vec = np.array(d_vals, dtype=np.float64) if d_vals else None

    # Desigualdades lineares: expr(x) <= 0 -> C_0 + sum_k x_k C_k <= 0 -> H x <= h (H_row = C_k_entry, h_entry = -C_0_entry)
    ineq_rows: list[np.ndarray] = []
    h_vals: list[float] = []
    ineq_names: list[str] = []
    for h_idx, con in enumerate(ineq_cons):
        r, c_dim = con.expr.shape
        hname = con.name or f"ineq_{h_idx}"
        for i in range(r):
            for j in range(c_dim):
                row = np.zeros((n_vars,), dtype=np.float64)
                for key, mat in con.expr.terms.items():
                    val = float(mat[i, j])
                    if val != 0.0:
                        row[key_to_global[key]] = val
                ineq_rows.append(row)
                h_vals.append(-float(con.expr.const[i, j]))
                ineq_names.append(f"{hname}[{i},{j}]")

    H_mat = np.vstack(ineq_rows) if ineq_rows else None
    h_vec = np.array(h_vals, dtype=np.float64) if h_vals else None

    constraint_map: dict[str, Any] = {
        "blocks": block_meta,
        "eq_names": eq_names,
        "ineq_names": ineq_names,
        "n_eq": len(d_vals),
        "n_ineq": len(h_vals),
    }

    scaling_info: dict[str, Any] = {
        "normalized": normalize_blocks,
        "block_scales": block_scales,
        "original_sense": sense,
        "objective_sign": sign_obj,
    }
    if scaling is not None:
        for sk, sv in scaling.items():
            if sk not in scaling_info:
                scaling_info[sk] = sv

    return CanonicalSDPProblem(
        c=c_vec,
        c0=c0_val,
        blocks=blocks,
        E=E_mat,
        d=d_vec,
        H=H_mat,
        h=h_vec,
        variable_map=variable_map,
        constraint_map=constraint_map,
        scaling=scaling_info,
        recovery_plan=recovery_plan,
        metadata=metadata,
        name=name or "compiled_sdp",
    )
