"""Vetorização simétrica isométrica (svec/smat) compatível com Clarabel PSDTriangleConeT.

Convenção (Seção 6.1 do Documento Diretor CL-DIR-001):
Para uma matriz simétrica M de dimensão n x n, svec(M) empacota o triângulo superior
em ordem column-major (j = 0..n-1, i = 0..j), multiplicando os elementos fora da
diagonal (i < j) por sqrt(2):
    svec(M) = [M_{0,0}, sqrt(2)*M_{0,1}, M_{1,1}, sqrt(2)*M_{0,2}, sqrt(2)*M_{1,2}, M_{2,2}, ...]

Esta convenção é isométrica para o produto interno de Frobenius:
    <svec(U), svec(V)> == Tr(U^T V)
e coincide com o cone `PSDTriangleConeT(n)` do solver Clarabel.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from control_lab.core.tensors import ensure_finite_float64
from control_lab.diagnostics import DimensionMismatchError, ValidationError

_SQRT2: float = math.sqrt(2.0)
_INV_SQRT2: float = 1.0 / _SQRT2
DEFAULT_SYMMETRY_TOL: float = 1e-10


def svec_dim(n: int) -> int:
    """Retorna a dimensão vetorizada n*(n+1)//2 para matriz simétrica n x n."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValidationError(
            message=f"Dimensão n de bloco simétrico deve ser inteiro >= 1, recebido {n!r}.",
            parameters={"n": repr(n)},
        )
    return (n * (n + 1)) // 2


def smat_dim(length: int) -> int:
    """Infere a ordem matricial n a partir do comprimento L = n*(n+1)//2 de svec."""
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise DimensionMismatchError(
            message=f"Comprimento de vetor svec deve ser inteiro >= 1, recebido {length!r}.",
            parameters={"length": repr(length)},
        )
    disc = 1 + 8 * length
    root = math.isqrt(disc)
    if root * root != disc or (root - 1) % 2 != 0:
        raise DimensionMismatchError(
            message=f"Comprimento {length} não corresponde a n*(n+1)/2 para nenhum inteiro n >= 1.",
            parameters={"length": length},
        )
    return (root - 1) // 2


def symmetry_error_rel(M: np.ndarray) -> float:
    """Calcula erro relativo de simetria ||M - M^T||_F / (1 + ||M||_F)."""
    if M.size == 0:
        return 0.0
    return float(np.linalg.norm(M - M.T, "fro") / (1.0 + np.linalg.norm(M, "fro")))


def is_diagonal_matrix(M: np.ndarray, *, tol: float = 0.0) -> bool:
    """Teste estrutural exato por padrão; tol > 0 serve apenas para inspeção aproximada.

    Redução de cone PSD a LP deve sempre usar tol=0.0.
    """
    if M.ndim != 2 or M.shape[0] != M.shape[1]:
        return False
    n = M.shape[0]
    if n <= 1:
        return True
    off_diag = M - np.diag(np.diag(M))
    return bool(np.max(np.abs(off_diag)) <= tol)


def svec(M: Any, *, sym_tol: float = DEFAULT_SYMMETRY_TOL, name: str = "M") -> np.ndarray:
    """Vetoriza matriz simétrica n x n no formato triangular superior escalado por sqrt(2)."""
    arr = ensure_finite_float64(M, ndim=2, name=name)
    n, m = arr.shape
    if n != m or n < 1:
        raise DimensionMismatchError(
            message=f"svec({name}) requer matriz quadrada n x n (n >= 1), recebido shape={arr.shape}.",
            parameters={"name": name, "shape": list(arr.shape)},
        )

    sym_err = symmetry_error_rel(arr)
    if sym_err > sym_tol:
        raise ValidationError(
            message=(
                f"svec({name}) exige matriz simétrica (||M - M^T||_F / (1 + ||M||_F) = {sym_err:.3e} > {sym_tol:.1e})."
            ),
            parameters={"name": name, "symmetry_error": sym_err, "sym_tol": sym_tol},
            next_step=f"Simetrize a matriz {name} ou corrija os termos assimétricos antes da vetorização.",
        )

    M_sym = 0.5 * (arr + arr.T)
    tri_len = svec_dim(n)
    out = np.empty((tri_len,), dtype=np.float64)
    idx = 0
    for j in range(n):
        for i in range(j):
            out[idx] = _SQRT2 * M_sym[i, j]
            idx += 1
        out[idx] = M_sym[j, j]
        idx += 1
    return out


def smat(v: Any, n: int | None = None, *, name: str = "v") -> np.ndarray:
    """Reconstrói matriz simétrica n x n a partir de vetor svec(M) escalado por sqrt(2)."""
    vec = ensure_finite_float64(v, ndim=1, name=name)
    if n is None:
        order = smat_dim(int(vec.shape[0]))
    else:
        expected_len = svec_dim(n)
        if vec.shape[0] != expected_len:
            raise DimensionMismatchError(
                message=f"smat({name}, n={n}) esperava comprimento {expected_len}, recebido {vec.shape[0]}.",
                parameters={"n": n, "expected_length": expected_len, "actual_length": int(vec.shape[0])},
            )
        order = n

    mat = np.zeros((order, order), dtype=np.float64)
    idx = 0
    for j in range(order):
        for i in range(j):
            val = _INV_SQRT2 * vec[idx]
            mat[i, j] = val
            mat[j, i] = val
            idx += 1
        mat[j, j] = vec[idx]
        idx += 1
    return mat


def symmetric_basis_matrices(n: int) -> tuple[np.ndarray, ...]:
    """Retorna a base simétrica canônica de S^n em ordem column-major do triângulo superior.

    Cada matriz E_{ij} (i == j) ou E_{ij} + E_{ji} (i < j) corresponde a uma coordenada
    escalar independente x_k = M_{ij} de uma variável matricial simétrica.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValidationError(f"Ordem simétrica n deve ser inteiro >= 1, recebido {n!r}.")
    basis: list[np.ndarray] = []
    for j in range(n):
        for i in range(j + 1):
            B = np.zeros((n, n), dtype=np.float64)
            if i == j:
                B[i, j] = 1.0
            else:
                B[i, j] = 1.0
                B[j, i] = 1.0
            B.setflags(write=False)
            basis.append(B)
    return tuple(basis)
