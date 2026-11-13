"""DSL afim pequena e rigorosa para modelagem LMI/SDP (CL-DIR-001 Seção 5.7 e 6.1).

Regras obrigatórias:
- Toda expressão é estritamente afim: E(x) = C_0 + sum_k x_k C_k.
- Qualquer produto bilinear ou não-afim entre variáveis de decisão é rejeitado com ValidationError.
- Desigualdades estritas (<, >) são rejeitadas com ValidationError; cones PSD são não estritos (>= 0)
  e requerem margem explícita (ex.: eps * I) quando estrita positividade for desejada.
- bmat() valida dimensões e rejeita blocos vazios ou incompatíveis.
"""

from __future__ import annotations

import itertools
from typing import Any, Mapping, Sequence

import numpy as np

from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import DimensionMismatchError, ValidationError

from .svec import DEFAULT_SYMMETRY_TOL, is_diagonal_matrix, symmetry_error_rel

_VAR_ID_COUNTER = itertools.count(1)


def _is_scalar_number(val: Any) -> bool:
    return isinstance(val, (int, float, np.integer, np.floating)) and not isinstance(val, (bool, np.bool_))


def _coerce_constant_matrix(value: Any, *, name: str = "constant") -> np.ndarray:
    """Converte entrada constante em matriz float64 2D finita (sem booleanos/complexos/NaN)."""
    if isinstance(value, AffineExpr):
        if not value.is_constant:
            raise ValidationError("Operação esperava constante, mas recebeu expressão com variáveis.")
        return value.const.copy()
    if _is_scalar_number(value):
        fval = float(value)
        if not np.isfinite(fval):
            raise ValidationError(f"Escalar {name} não é finito: {value!r}.")
        return np.array([[fval]], dtype=np.float64)
    arr = ensure_finite_float64(value, name=name)
    if arr.ndim == 0:
        return arr.reshape((1, 1))
    if arr.ndim == 1:
        raise DimensionMismatchError(
            message=(
                f"Entrada matricial {name} recebeu array 1D de shape {arr.shape}; "
                "use shape 2D explícito (n, 1) ou (1, n) para evitar ambiguidade em expressões LMI."
            ),
            parameters={"name": name, "shape": list(arr.shape)},
            next_step="Converta o vetor 1D para matriz coluna (n, 1) ou linha (1, n) com reshape.",
        )
    if arr.ndim != 2:
        raise DimensionMismatchError(
            message=f"Entrada {name} deve ser 2D, recebido {arr.ndim}D (shape={arr.shape}).",
            parameters={"name": name, "shape": list(arr.shape)},
        )
    if arr.shape[0] < 1 or arr.shape[1] < 1:
        raise ValidationError(
            message=f"Matriz constante {name} não pode possuir dimensão nula: shape={arr.shape}.",
            parameters={"name": name, "shape": list(arr.shape)},
        )
    return arr


def _normalize_var_shape(shape: int | Sequence[int] | None) -> tuple[int, int]:
    if shape is None:
        return (1, 1)
    if isinstance(shape, bool):
        raise ValidationError("shape de sdpvar não pode ser booleano.")
    if isinstance(shape, (int, np.integer)):
        n = int(shape)
        if n < 1:
            raise DimensionMismatchError(f"Dimensão de sdpvar deve ser >= 1, recebido {n}.")
        return (n, 1)
    if isinstance(shape, (tuple, list)):
        if len(shape) == 0:
            return (1, 1)
        if len(shape) == 1:
            d0 = shape[0]
            if isinstance(d0, bool) or not isinstance(d0, (int, np.integer)) or int(d0) < 1:
                raise DimensionMismatchError(f"Dimensão inválida em sdpvar: {shape!r}.")
            return (int(d0), 1)
        if len(shape) == 2:
            r, c = shape[0], shape[1]
            if (
                isinstance(r, bool)
                or isinstance(c, bool)
                or not isinstance(r, (int, np.integer))
                or not isinstance(c, (int, np.integer))
                or int(r) < 1
                or int(c) < 1
            ):
                raise DimensionMismatchError(f"Shape inválido para sdpvar: {shape!r}. Esperado (r >= 1, c >= 1).")
            return (int(r), int(c))
        raise DimensionMismatchError(f"sdpvar suporta apenas até 2 dimensões, recebido {shape!r}.")
    raise ValidationError(f"shape inválido para sdpvar: {shape!r}.")


class AffineExpr:
    """Expressão matricial afim E(x) = C_0 + sum_{(var_id, local_idx)} x_{var_id, local_idx} * C_k."""

    __array_ufunc__ = None

    def __init__(
        self,
        const: np.ndarray,
        terms: Mapping[tuple[int, int], np.ndarray] | None = None,
        variables: Mapping[int, SDPVar] | None = None,
    ) -> None:
        c_arr = np.array(const, dtype=np.float64, copy=True)
        if c_arr.ndim != 2 or c_arr.shape[0] < 1 or c_arr.shape[1] < 1:
            raise DimensionMismatchError(f"AffineExpr requer shape 2D não vazio, recebido {c_arr.shape}.")
        if not np.all(np.isfinite(c_arr)):
            raise ValidationError("Termo constante de AffineExpr contém NaN ou Inf.")
        c_arr.setflags(write=False)

        clean_terms: dict[tuple[int, int], np.ndarray] = {}
        active_var_ids: set[int] = set()
        if terms is not None:
            for key, mat in terms.items():
                m_arr = np.array(mat, dtype=np.float64, copy=True)
                if m_arr.shape != c_arr.shape:
                    raise DimensionMismatchError(
                        f"Coeficiente {key} tem shape {m_arr.shape}, esperado {c_arr.shape}."
                    )
                if not np.all(np.isfinite(m_arr)):
                    raise ValidationError(f"Coeficiente {key} contém NaN ou Inf.")
                if np.any(m_arr != 0.0):
                    m_arr.setflags(write=False)
                    clean_terms[key] = m_arr
                    active_var_ids.add(key[0])

        clean_vars: dict[int, SDPVar] = {}
        if variables is not None:
            for vid in active_var_ids:
                if vid not in variables:
                    raise ValidationError(f"Variável var_id={vid} ausente no registro de AffineExpr.")
                clean_vars[vid] = variables[vid]

        self._const = c_arr
        self._terms = clean_terms
        self._variables = clean_vars

    @property
    def const(self) -> np.ndarray:
        return self._const

    @property
    def terms(self) -> dict[tuple[int, int], np.ndarray]:
        return dict(self._terms)

    @property
    def variables(self) -> dict[int, SDPVar]:
        return dict(self._variables)

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self._const.shape[0]), int(self._const.shape[1]))

    @property
    def ndim(self) -> int:
        return 2

    @property
    def size(self) -> int:
        return int(self._const.size)

    @property
    def is_constant(self) -> bool:
        return len(self._terms) == 0

    @property
    def has_variables(self) -> bool:
        return len(self._terms) > 0

    @property
    def is_scalar(self) -> bool:
        return self.shape == (1, 1)

    @property
    def T(self) -> AffineExpr:
        return self.transpose()

    def transpose(self) -> AffineExpr:
        new_terms = {k: mat.T for k, mat in self._terms.items()}
        return AffineExpr(self._const.T, new_terms, self._variables)

    def trace(self) -> AffineExpr:
        r, c = self.shape
        if r != c:
            raise DimensionMismatchError(
                message=f"trace() requer matriz quadrada, recebido shape={self.shape}.",
                parameters={"shape": list(self.shape)},
            )
        tr_c = np.array([[float(np.trace(self._const))]], dtype=np.float64)
        new_terms: dict[tuple[int, int], np.ndarray] = {}
        for k, mat in self._terms.items():
            tr_val = float(np.trace(mat))
            if tr_val != 0.0:
                new_terms[k] = np.array([[tr_val]], dtype=np.float64)
        return AffineExpr(tr_c, new_terms, self._variables)

    def is_symmetric(self, *, tol: float = DEFAULT_SYMMETRY_TOL) -> bool:
        r, c = self.shape
        if r != c:
            return False
        if symmetry_error_rel(self._const) > tol:
            return False
        for mat in self._terms.values():
            if symmetry_error_rel(mat) > tol:
                return False
        return True

    def is_diagonal(self, *, tol: float = 1e-14) -> bool:
        if self.shape[0] != self.shape[1]:
            return False
        if not is_diagonal_matrix(self._const, tol=tol):
            return False
        for mat in self._terms.values():
            if not is_diagonal_matrix(mat, tol=tol):
                return False
        return True

    def evaluate(self, values: Mapping[int | str | SDPVar, Any]) -> np.ndarray:
        """Avalia numericamente E(x) dado um mapeamento de variáveis para seus valores."""
        out = self._const.copy()
        by_name: dict[str, np.ndarray] = {}
        by_id: dict[int, np.ndarray] = {}
        for k, v in values.items():
            arr = np.asarray(v, dtype=np.float64)
            if isinstance(k, SDPVar):
                by_id[k.var_id] = arr
            elif isinstance(k, int) and not isinstance(k, bool):
                by_id[k] = arr
            elif isinstance(k, str):
                by_name[k] = arr
            else:
                raise ValidationError(f"Chave inválida em evaluate(): {k!r}")

        var_vectors: dict[int, np.ndarray] = {}
        for vid, var in self._variables.items():
            if vid in by_id:
                raw_val = by_id[vid]
            elif var.name in by_name:
                raw_val = by_name[var.name]
            else:
                raise ValidationError(f"Valor ausente para variável {var.name!r} (var_id={vid}).")
            var_vectors[vid] = var.flatten_value(raw_val)

        for (vid, local_idx), mat in self._terms.items():
            out = out + float(var_vectors[vid][local_idx]) * mat
        return out

    def _as_expr(self, other: Any) -> AffineExpr:
        if isinstance(other, AffineExpr):
            return other
        c_mat = _coerce_constant_matrix(other, name="operand")
        return AffineExpr(c_mat)

    def _add_impl(self, other: AffineExpr, *, sign: float) -> AffineExpr:
        if self.shape != other.shape:
            raise DimensionMismatchError(
                message=f"Incompatibilidade de dimensões na soma/subtração afim: {self.shape} vs {other.shape}.",
                parameters={"lhs_shape": list(self.shape), "rhs_shape": list(other.shape)},
            )
        new_const = self._const + sign * other._const
        new_terms: dict[tuple[int, int], np.ndarray] = {k: v.copy() for k, v in self._terms.items()}
        for k, v in other._terms.items():
            if k in new_terms:
                new_terms[k] = new_terms[k] + sign * v
            else:
                new_terms[k] = sign * v
        merged_vars = {**self._variables, **other._variables}
        return AffineExpr(new_const, new_terms, merged_vars)

    def __pos__(self) -> AffineExpr:
        return self

    def __neg__(self) -> AffineExpr:
        return AffineExpr(-self._const, {k: -v for k, v in self._terms.items()}, self._variables)

    def __add__(self, other: Any) -> AffineExpr:
        return self._add_impl(self._as_expr(other), sign=1.0)

    def __radd__(self, other: Any) -> AffineExpr:
        return self._as_expr(other)._add_impl(self, sign=1.0)

    def __sub__(self, other: Any) -> AffineExpr:
        return self._add_impl(self._as_expr(other), sign=-1.0)

    def __rsub__(self, other: Any) -> AffineExpr:
        return self._as_expr(other)._add_impl(self, sign=-1.0)

    def _mul_impl(self, other: AffineExpr) -> AffineExpr:
        if self.has_variables and other.has_variables:
            raise ValidationError(
                message="Produto bilinear ou não-afim entre duas variáveis de decisão é proibido em LMIs/SDPs canônicos.",
                parameters={"lhs_shape": list(self.shape), "rhs_shape": list(other.shape)},
                next_step="Mantenha todas as expressões estritamente afins em relação às variáveis de decisão.",
            )
        if self.is_constant and other.is_constant:
            if self.is_scalar:
                return AffineExpr(float(self._const[0, 0]) * other._const)
            if other.is_scalar:
                return AffineExpr(self._const * float(other._const[0, 0]))
            if self.shape != other.shape:
                raise DimensionMismatchError(f"Shapes incompatíveis em multiplicação: {self.shape} vs {other.shape}.")
            return AffineExpr(self._const * other._const)

        if self.is_constant:
            const_expr, var_expr = self, other
        else:
            const_expr, var_expr = other, self

        if const_expr.is_scalar:
            s = float(const_expr._const[0, 0])
            return AffineExpr(
                s * var_expr._const,
                {k: s * mat for k, mat in var_expr._terms.items()},
                var_expr._variables,
            )
        if var_expr.is_scalar:
            C = const_expr._const
            scalar_const = float(var_expr._const[0, 0])
            new_terms = {k: C * float(mat[0, 0]) for k, mat in var_expr._terms.items()}
            return AffineExpr(C * scalar_const, new_terms, var_expr._variables)

        if const_expr.shape != var_expr.shape:
            raise DimensionMismatchError(
                f"Incompatibilidade de shapes em multiplicação elemento-a-elemento: {const_expr.shape} vs {var_expr.shape}."
            )
        C = const_expr._const
        return AffineExpr(
            C * var_expr._const,
            {k: C * mat for k, mat in var_expr._terms.items()},
            var_expr._variables,
        )

    def __mul__(self, other: Any) -> AffineExpr:
        return self._mul_impl(self._as_expr(other))

    def __rmul__(self, other: Any) -> AffineExpr:
        return self._as_expr(other)._mul_impl(self)

    def __truediv__(self, other: Any) -> AffineExpr:
        rhs = self._as_expr(other)
        if rhs.has_variables:
            raise ValidationError(
                message="Divisão por variável de decisão é não-afim e proibida em LMIs/SDPs canônicos.",
                next_step="Divida apenas por constantes numéricas não nulas.",
            )
        if not rhs.is_scalar:
            raise DimensionMismatchError(f"Divisão suporta apenas divisor escalar (1, 1), recebido {rhs.shape}.")
        denom = float(rhs._const[0, 0])
        if denom == 0.0:
            raise ValidationError("Divisão por zero em expressão afim.")
        inv = 1.0 / denom
        return AffineExpr(
            inv * self._const,
            {k: inv * mat for k, mat in self._terms.items()},
            self._variables,
        )

    def __rtruediv__(self, other: Any) -> AffineExpr:
        if self.has_variables:
            raise ValidationError("Divisão por variável de decisão (c / x) é não-afim e proibida.")
        return self._as_expr(other).__truediv__(self)

    def __pow__(self, exponent: Any) -> AffineExpr:
        if self.has_variables:
            raise ValidationError(
                message="Potenciação de variável de decisão é não-afim/polinomial e proibida em LMIs canônicos.",
                parameters={"exponent": repr(exponent)},
            )
        if not _is_scalar_number(exponent):
            raise ValidationError("Expoente deve ser número real finito.")
        return AffineExpr(np.power(self._const, float(exponent)))

    def _matmul_impl(self, other: AffineExpr) -> AffineExpr:
        if self.has_variables and other.has_variables:
            raise ValidationError(
                message="Produto matricial bilinear (expr1 @ expr2) entre variáveis de decisão é proibido.",
                parameters={"lhs_shape": list(self.shape), "rhs_shape": list(other.shape)},
                next_step="Use mudança de variáveis (ex.: Y = K @ Q) para manter a LMI afim.",
            )
        if self.shape[1] != other.shape[0]:
            raise DimensionMismatchError(
                message=f"Dimensões incompatíveis em produto matricial @: {self.shape} @ {other.shape}.",
                parameters={"lhs_shape": list(self.shape), "rhs_shape": list(other.shape)},
            )
        if self.is_constant and other.is_constant:
            return AffineExpr(self._const @ other._const)
        if self.is_constant:
            L = self._const
            return AffineExpr(
                L @ other._const,
                {k: L @ mat for k, mat in other._terms.items()},
                other._variables,
            )
        R = other._const
        return AffineExpr(
            self._const @ R,
            {k: mat @ R for k, mat in self._terms.items()},
            self._variables,
        )

    def __matmul__(self, other: Any) -> AffineExpr:
        return self._matmul_impl(self._as_expr(other))

    def __rmatmul__(self, other: Any) -> AffineExpr:
        return self._as_expr(other)._matmul_impl(self)

    def __getitem__(self, key: Any) -> AffineExpr:
        c_slice = np.asarray(self._const[key], dtype=np.float64)
        if c_slice.ndim == 0:
            c_slice = c_slice.reshape((1, 1))
        elif c_slice.ndim == 1:
            c_slice = c_slice.reshape((-1, 1)) if self.shape[1] == 1 else c_slice.reshape((1, -1))
        if c_slice.ndim != 2 or c_slice.shape[0] < 1 or c_slice.shape[1] < 1:
            raise DimensionMismatchError(f"Slicing inválido em AffineExpr resultou em shape={c_slice.shape}.")
        target_shape = c_slice.shape
        new_terms: dict[tuple[int, int], np.ndarray] = {}
        for k, mat in self._terms.items():
            sl = np.asarray(mat[key], dtype=np.float64).reshape(target_shape)
            if np.any(sl != 0.0):
                new_terms[k] = sl
        return AffineExpr(c_slice, new_terms, self._variables)

    def __bool__(self) -> bool:
        raise ValidationError(
            "Expressão afim não possui valor booleano; passe restrições para compile()."
        )

    def __gt__(self, other: Any) -> Any:
        raise ValidationError(
            message=(
                "Desigualdade estrita '>' não é suportada diretamente em programação cônica semidefinida; "
                "use '>=' com margem explícita (ex.: F >= eps * np.eye(n))."
            ),
            next_step="Substitua '>' por '>=' com margem positiva eps*I.",
        )

    def __lt__(self, other: Any) -> Any:
        raise ValidationError(
            message=(
                "Desigualdade estrita '<' não é suportada diretamente em programação cônica semidefinida; "
                "use '<=' com margem explícita (ex.: F <= -eps * np.eye(n))."
            ),
            next_step="Substitua '<' por '<=' com margem negativa -eps*I.",
        )

    def __ge__(self, other: Any) -> LMIBlockConstraint | LinearIneqConstraint:
        if _is_scalar_number(other) and float(other) == 0.0:
            diff = self
        else:
            diff = self - self._as_expr(other)
        r, c = diff.shape
        if r == c:
            return LMIBlockConstraint(diff)
        return LinearIneqConstraint(-diff)

    def __le__(self, other: Any) -> LMIBlockConstraint | LinearIneqConstraint:
        if _is_scalar_number(other) and float(other) == 0.0:
            diff = -self
        else:
            diff = self._as_expr(other) - self
        r, c = diff.shape
        if r == c:
            return LMIBlockConstraint(diff)
        return LinearIneqConstraint(-diff)

    def __eq__(self, other: Any) -> LinearEqConstraint:  # type: ignore[override]
        if _is_scalar_number(other) and float(other) == 0.0:
            diff = self
        else:
            diff = self - self._as_expr(other)
        return LinearEqConstraint(diff)

    def __repr__(self) -> str:
        return f"AffineExpr(shape={self.shape}, n_terms={len(self._terms)})"


class SDPVar(AffineExpr):
    """Variável matricial ou escalar de decisão para LMIs/SDPs canônicos."""

    def __init__(
        self,
        shape: int | Sequence[int] | None = (1, 1),
        *,
        name: str | None = None,
        symmetric: bool = False,
    ) -> None:
        r, c = _normalize_var_shape(shape)
        if not isinstance(symmetric, bool):
            raise ValidationError("Parâmetro symmetric de sdpvar deve ser booleano.")
        if symmetric and r != c:
            raise DimensionMismatchError(
                message=f"Variável simétrica exige matriz quadrada (n, n), recebido shape=({r}, {c}).",
                parameters={"shape": [r, c], "symmetric": symmetric},
            )

        vid = next(_VAR_ID_COUNTER)
        if name is None:
            resolved_name = f"x_{vid}"
        else:
            if not isinstance(name, str) or not name.strip():
                raise ValidationError("Nome de sdpvar deve ser string não vazia.")
            resolved_name = name.strip()

        self._var_id = vid
        self._name = resolved_name
        self._var_shape = (r, c)
        self._symmetric = symmetric

        coords: list[tuple[int, int]] = []
        basis_terms: dict[tuple[int, int], np.ndarray] = {}
        if symmetric:
            idx = 0
            for j in range(r):
                for i in range(j + 1):
                    B = np.zeros((r, r), dtype=np.float64)
                    if i == j:
                        B[i, j] = 1.0
                    else:
                        B[i, j] = 1.0
                        B[j, i] = 1.0
                    basis_terms[(vid, idx)] = B
                    coords.append((i, j))
                    idx += 1
        else:
            idx = 0
            for i in range(r):
                for j in range(c):
                    B = np.zeros((r, c), dtype=np.float64)
                    B[i, j] = 1.0
                    basis_terms[(vid, idx)] = B
                    coords.append((i, j))
                    idx += 1

        self._coords = tuple(coords)
        self._local_size = len(coords)
        const0 = np.zeros((r, c), dtype=np.float64)
        super().__init__(const0, basis_terms, {vid: self})

    @property
    def var_id(self) -> int:
        return self._var_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def symmetric(self) -> bool:
        return self._symmetric

    @property
    def local_size(self) -> int:
        return self._local_size

    @property
    def coord_map(self) -> tuple[tuple[int, int], ...]:
        return self._coords

    def reconstruct(self, x_slice: Sequence[float] | np.ndarray) -> np.ndarray:
        """Reconstrói a matriz (r, c) a partir do segmento local de variáveis escalares."""
        vec = ensure_finite_float64(x_slice, ndim=1, shape=(self._local_size,), name=f"{self._name}.slice")
        mat = np.zeros(self._var_shape, dtype=np.float64)
        if self._symmetric:
            for idx, (i, j) in enumerate(self._coords):
                val = float(vec[idx])
                mat[i, j] = val
                mat[j, i] = val
        else:
            for idx, (i, j) in enumerate(self._coords):
                mat[i, j] = float(vec[idx])
        return mat

    def flatten_value(self, value: Any) -> np.ndarray:
        """Converte uma matriz numérica compatível (r, c) no vetor local de coordenadas."""
        if _is_scalar_number(value) and self._var_shape == (1, 1):
            return np.array([float(value)], dtype=np.float64)
        arr = ensure_finite_float64(value, ndim=2, shape=self._var_shape, name=self._name)
        if self._symmetric:
            if symmetry_error_rel(arr) > DEFAULT_SYMMETRY_TOL:
                raise ValidationError(f"Valor para variável simétrica {self._name!r} não é simétrico.")
            arr = 0.5 * (arr + arr.T)
        return np.array([float(arr[i, j]) for (i, j) in self._coords], dtype=np.float64)

    def __repr__(self) -> str:
        return f"SDPVar(name={self._name!r}, shape={self._var_shape}, symmetric={self._symmetric})"


def sdpvar(
    shape: int | Sequence[int] | None = (1, 1),
    *,
    name: str | None = None,
    symmetric: bool = False,
) -> SDPVar:
    """Cria variável de decisão matricial ou escalar afim."""
    return SDPVar(shape=shape, name=name, symmetric=symmetric)


class LMIBlockConstraint:
    """Restrição de bloco semidefinido positivo F(x) >= 0 (F(x) simétrica)."""

    kind: str = "lmi_psd"

    def __init__(self, expr: AffineExpr, *, name: str | None = None, sym_tol: float = DEFAULT_SYMMETRY_TOL) -> None:
        if not isinstance(expr, AffineExpr):
            raise ValidationError("LMIBlockConstraint espera AffineExpr.")
        r, c = expr.shape
        if r != c:
            raise DimensionMismatchError(
                message=f"Bloco LMI/PSD requer matriz quadrada, recebido shape={expr.shape}.",
                parameters={"shape": [r, c]},
            )
        if not expr.is_symmetric(tol=sym_tol):
            raise ValidationError(
                message=(
                    "Bloco LMI/PSD F(x) >= 0 exige que o termo constante e todos os coeficientes matriciais "
                    "sejam simétricos (F_k == F_k^T)."
                ),
                parameters={"shape": [r, c], "sym_tol": sym_tol},
                next_step="Simetrize explicitamente a expressão (ex.: 0.5 * (M + M.T)) antes de criar a LMI.",
            )
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValidationError("Nome da restrição LMI deve ser string não vazia.")
        self.expr = expr
        self.name = name.strip() if name is not None else None
        self.dim = r
        self.is_diagonal = expr.is_diagonal()

    def __bool__(self) -> bool:
        raise ValidationError("Restrição LMI não pode ser convertida em bool.")

    def __repr__(self) -> str:
        return f"LMIBlockConstraint(dim={self.dim}, name={self.name!r})"


class LinearEqConstraint:
    """Restrição de igualdade linear expr(x) == 0 -> E x = d."""

    kind: str = "linear_eq"

    def __init__(self, expr: AffineExpr, *, name: str | None = None) -> None:
        if not isinstance(expr, AffineExpr):
            raise ValidationError("LinearEqConstraint espera AffineExpr.")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValidationError("Nome da restrição de igualdade deve ser string não vazia.")
        self.expr = expr
        self.name = name.strip() if name is not None else None

    def __bool__(self) -> bool:
        raise ValidationError("Restrição LinearEq não pode ser convertida em bool.")

    def __repr__(self) -> str:
        return f"LinearEqConstraint(shape={self.expr.shape}, name={self.name!r})"


class LinearIneqConstraint:
    """Restrição de desigualdade linear elemento-a-elemento expr(x) <= 0 -> H x <= h."""

    kind: str = "linear_ineq"

    def __init__(self, expr: AffineExpr, *, name: str | None = None) -> None:
        if not isinstance(expr, AffineExpr):
            raise ValidationError("LinearIneqConstraint espera AffineExpr.")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValidationError("Nome da restrição de desigualdade deve ser string não vazia.")
        self.expr = expr
        self.name = name.strip() if name is not None else None

    def __bool__(self) -> bool:
        raise ValidationError("Restrição LinearIneq não pode ser convertida em bool.")

    def __repr__(self) -> str:
        return f"LinearIneqConstraint(shape={self.expr.shape}, name={self.name!r})"


def psd(expr: AffineExpr, *, name: str | None = None) -> LMIBlockConstraint:
    """Cria explicitamente um bloco PSD F(x) >= 0."""
    return LMIBlockConstraint(expr, name=name)


def linear_eq(lhs: Any, rhs: Any = 0.0, *, name: str | None = None) -> LinearEqConstraint:
    """Cria restrição de igualdade linear lhs == rhs."""
    if isinstance(lhs, AffineExpr):
        if _is_scalar_number(rhs) and float(rhs) == 0.0 and lhs.shape != (1, 1):
            expr = lhs
        else:
            expr = lhs - lhs._as_expr(rhs)
    elif isinstance(rhs, AffineExpr):
        if _is_scalar_number(lhs) and float(lhs) == 0.0 and rhs.shape != (1, 1):
            expr = -rhs
        else:
            expr = rhs._as_expr(lhs) - rhs
    else:
        raise ValidationError("linear_eq requer ao menos uma AffineExpr.")
    return LinearEqConstraint(expr, name=name)


def linear_ineq(lhs: Any, rhs: Any = 0.0, *, name: str | None = None) -> LinearIneqConstraint:
    """Cria restrição de desigualdade linear elemento-a-elemento lhs <= rhs."""
    if isinstance(lhs, AffineExpr):
        if _is_scalar_number(rhs) and float(rhs) == 0.0 and lhs.shape != (1, 1):
            expr = lhs
        else:
            expr = lhs - lhs._as_expr(rhs)
    elif isinstance(rhs, AffineExpr):
        if _is_scalar_number(lhs) and float(lhs) == 0.0 and rhs.shape != (1, 1):
            expr = -rhs
        else:
            expr = rhs._as_expr(lhs) - rhs
    else:
        raise ValidationError("linear_ineq requer ao menos uma AffineExpr.")
    return LinearIneqConstraint(expr, name=name)


def trace(expr: Any) -> AffineExpr | float:
    """Calcula o traço de uma AffineExpr quadrada ou matriz NumPy."""
    if isinstance(expr, AffineExpr):
        return expr.trace()
    arr = _coerce_constant_matrix(expr, name="trace.input")
    if arr.shape[0] != arr.shape[1]:
        raise DimensionMismatchError(f"trace() requer matriz quadrada, recebido {arr.shape}.")
    return float(np.trace(arr))


def bmat(blocks: Sequence[Sequence[Any]]) -> AffineExpr:
    """Monta matriz de blocos afins validando dimensões e rejeitando blocos vazios."""
    if isinstance(blocks, (str, bytes, Mapping)) or not isinstance(blocks, Sequence) or len(blocks) == 0:
        raise ValidationError("bmat() exige sequência 2D não vazia de blocos.")

    n_rows = len(blocks)
    n_cols: int | None = None
    parsed: list[list[AffineExpr | str]] = []
    row_heights: list[int | None] = [None] * n_rows
    col_widths: list[int | None] = []

    for i, row in enumerate(blocks):
        if isinstance(row, (str, bytes, Mapping)) or not isinstance(row, Sequence) or len(row) == 0:
            raise ValidationError(f"bmat() linha {i} deve ser sequência não vazia de blocos.")
        if n_cols is None:
            n_cols = len(row)
            col_widths = [None] * n_cols
        elif len(row) != n_cols:
            raise DimensionMismatchError(
                message=f"bmat() todas as linhas devem ter {n_cols} colunas; linha {i} tem {len(row)}.",
                parameters={"row": i, "expected_cols": n_cols, "actual_cols": len(row)},
            )

        parsed_row: list[AffineExpr | str] = []
        for j, cell in enumerate(row):
            if cell is None:
                raise ValidationError(f"bmat() não aceita bloco None em ({i}, {j}); use np.zeros((r, c)) ou 0 explícito.")
            if isinstance(cell, (list, tuple)) and len(cell) == 0:
                raise ValidationError(f"bmat() rejeita bloco vazio em ({i}, {j}).")
            if isinstance(cell, AffineExpr):
                r_ij, c_ij = cell.shape
                parsed_row.append(cell)
            elif _is_scalar_number(cell) and float(cell) == 0.0:
                # Zero escalar pode adaptar-se a (row_heights[i], col_widths[j]) caso definido por vizinhos
                parsed_row.append("__ZERO_PLACEHOLDER__")
                continue
            else:
                mat = _coerce_constant_matrix(cell, name=f"bmat[{i},{j}]")
                r_ij, c_ij = mat.shape
                parsed_row.append(AffineExpr(mat))

            if row_heights[i] is None:
                row_heights[i] = r_ij
            elif row_heights[i] != r_ij:
                raise DimensionMismatchError(
                    message=f"Incompatibilidade de altura na linha {i} de bmat: {row_heights[i]} vs {r_ij} na coluna {j}.",
                    parameters={"row": i, "col": j, "expected_rows": row_heights[i], "actual_rows": r_ij},
                )
            if col_widths[j] is None:
                col_widths[j] = c_ij
            elif col_widths[j] != c_ij:
                raise DimensionMismatchError(
                    message=f"Incompatibilidade de largura na coluna {j} de bmat: {col_widths[j]} vs {c_ij} na linha {i}.",
                    parameters={"row": i, "col": j, "expected_cols": col_widths[j], "actual_cols": c_ij},
                )
        parsed.append(parsed_row)

    assert n_cols is not None
    # Resolver placeholders '0' ou inferir (1, 1) se toda uma linha/coluna tiver dimensão indeterminada -> erro!
    for i in range(n_rows):
        if row_heights[i] is None:
            raise ValidationError(
                f"bmat() linha {i} não possui nenhum bloco com número de linhas determinado (linha só de zeros)."
            )
    for j in range(n_cols):
        if col_widths[j] is None:
            raise ValidationError(
                f"bmat() coluna {j} não possui nenhum bloco com número de colunas determinado (coluna só de zeros)."
            )

    resolved_grid: list[list[AffineExpr]] = []
    all_vars: dict[int, SDPVar] = {}
    all_keys: set[tuple[int, int]] = set()
    for i in range(n_rows):
        rh = row_heights[i]
        assert rh is not None
        r_cells: list[AffineExpr] = []
        for j in range(n_cols):
            cw = col_widths[j]
            assert cw is not None
            cell = parsed[i][j]
            if isinstance(cell, str):
                expr_ij = AffineExpr(np.zeros((rh, cw), dtype=np.float64))
            else:
                expr_ij = cell
            r_cells.append(expr_ij)
            all_vars.update(expr_ij.variables)
            all_keys.update(expr_ij.terms.keys())
        resolved_grid.append(r_cells)

    const_block = np.block([[cell.const for cell in row] for row in resolved_grid])
    new_terms: dict[tuple[int, int], np.ndarray] = {}
    for key in sorted(all_keys):
        coeff_block = np.block(
            [
                [
                    cell.terms.get(key, np.zeros(cell.shape, dtype=np.float64))
                    for cell in row
                ]
                for row in resolved_grid
            ]
        )
        if np.any(coeff_block != 0.0):
            new_terms[key] = coeff_block

    return AffineExpr(const_block, new_terms, all_vars)
