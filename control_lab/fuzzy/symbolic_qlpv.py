"""Motor simbólico determinístico qLPV, buscador híbrido de extremos e verificador de multilinearidade.

Implementa os requisitos normativos de `CL-TS-MOD-DIR-001` Seção 3 e `CL-DIR-001` (`R-21`):
- Parser recursivo descendente sobre AST tipada (ZERO `eval`, `exec`, `compile` ou `getattr` dinâmico);
- Primitivas suaves C^inf sem singularidade removível na origem: `sinc_rad(u)` e `cos1m_div_u(u)`;
- Detecção e reescrita segura do padrão `sin(E)/(E)` -> `sinc_rad(E)` com aviso informativo;
- Pipeline híbrido determinístico em 3 estágios (Aritmética Intervalar SUE + grade/Sobol + polimento multi-start);
- Verificador estrutural de isolamento de variáveis e multilinearidade afim em `z = (z_1, ..., z_nn)`.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import qmc

from control_lab.diagnostics import (
    DimensionMismatchError,
    HypothesisViolatedError,
    ValidationError,
    WarningItem,
)

MAX_EXPRESSION_LENGTH = 4096
MAX_AST_DEPTH = 64

RESERVED_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
}

SUPPORTED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "exp",
        "log",
        "sqrt",
        "abs",
        "sign",
        "sinc_rad",
        "cos1m_div_u",
    }
)

_FORBIDDEN_IDENTIFIERS: frozenset[str] = frozenset(
    {
        "import",
        "from",
        "lambda",
        "def",
        "class",
        "eval",
        "exec",
        "compile",
        "open",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "builtins",
        "__import__",
        "__builtins__",
        "__class__",
        "__subclasses__",
        "__globals__",
        "os",
        "sys",
        "subprocess",
        "True",
        "False",
        "None",
        "inf",
        "nan",
    }
)

_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Primitivas numéricas estáveis (C^infty na origem)
# ---------------------------------------------------------------------------


def sinc_rad(u: float | np.ndarray) -> float | np.ndarray:
    """Calcula sin(u)/u em radianos sem singularidade removível na origem.

    Para |u| < 1e-4 usa a expansão de Taylor `1 - u^2/6 + u^4/120` (erro < 1e-27).
    """
    if isinstance(u, np.ndarray):
        arr = np.asarray(u, dtype=np.float64)
        small = np.abs(arr) < 1e-4
        safe_u = np.where(small, 1.0, arr)
        u2 = arr * arr
        taylor = 1.0 - (u2 / 6.0) + (u2 * u2 / 120.0)
        direct = np.sin(safe_u) / safe_u
        return np.where(small, taylor, direct)
    val = float(u)
    if abs(val) < 1e-4:
        u2 = val * val
        return 1.0 - (u2 / 6.0) + (u2 * u2 / 120.0)
    return math.sin(val) / val


def cos1m_div_u(u: float | np.ndarray) -> float | np.ndarray:
    """Calcula (1 - cos(u))/u em radianos sem singularidade removível na origem.

    Para |u| < 1e-4 usa a expansão de Taylor `u/2 - u^3/24 + u^5/720` (erro < 1e-32).
    """
    if isinstance(u, np.ndarray):
        arr = np.asarray(u, dtype=np.float64)
        small = np.abs(arr) < 1e-4
        safe_u = np.where(small, 1.0, arr)
        u2 = arr * arr
        taylor = arr * (0.5 - (u2 / 24.0) + (u2 * u2 / 720.0))
        direct = (1.0 - np.cos(safe_u)) / safe_u
        return np.where(small, taylor, direct)
    val = float(u)
    if abs(val) < 1e-4:
        u2 = val * val
        return val * (0.5 - (u2 / 24.0) + (u2 * u2 / 720.0))
    return (1.0 - math.cos(val)) / val


# ---------------------------------------------------------------------------
# AST tipada imutável
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumberNode:
    value: float


@dataclass(frozen=True)
class ConstNode:
    name: str
    value: float


@dataclass(frozen=True)
class VarNode:
    name: str


@dataclass(frozen=True)
class UnaryOpNode:
    op: str
    operand: ExprNode


@dataclass(frozen=True)
class BinaryOpNode:
    op: str
    left: ExprNode
    right: ExprNode


@dataclass(frozen=True)
class CallNode:
    func: str
    arg: ExprNode


ExprNode = NumberNode | ConstNode | VarNode | UnaryOpNode | BinaryOpNode | CallNode


@dataclass(frozen=True)
class ParsedExpression:
    """Expressão simbólica validada, reescrita e pronta para avaliação segura."""

    source: str
    ast: ExprNode
    active_variables: tuple[str, ...]
    variable_counts: dict[str, int]
    is_sue: bool
    rewrites: tuple[WarningItem, ...] = ()

    def to_string(self) -> str:
        return format_ast(self.ast)


def format_ast(node: ExprNode) -> str:
    """Converte AST tipada em representação textual determinística."""
    if isinstance(node, NumberNode):
        return repr(float(node.value))
    if isinstance(node, ConstNode):
        return node.name
    if isinstance(node, VarNode):
        return node.name
    if isinstance(node, UnaryOpNode):
        inner = format_ast(node.operand)
        if isinstance(node.operand, BinaryOpNode):
            return f"{node.op}({inner})"
        return f"{node.op}{inner}"
    if isinstance(node, BinaryOpNode):
        return f"({format_ast(node.left)} {node.op} {format_ast(node.right)})"
    if isinstance(node, CallNode):
        return f"{node.func}({format_ast(node.arg)})"
    raise ValidationError(f"Nó AST não suportado: {type(node).__name__}")


# ---------------------------------------------------------------------------
# Lexer e Parser Recursivo Descendente Determinístico (ZERO eval/exec)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    kind: str  # NUMBER, IDENT, OP, LPAREN, RPAREN, COMMA, EOF
    value: str
    pos: int


def _tokenize(text: str) -> list[_Token]:
    if not isinstance(text, str):
        raise ValidationError("Expressão simbólica deve ser uma string.")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ValidationError(
            f"Expressão excede o limite de {MAX_EXPRESSION_LENGTH} caracteres.",
            parameters={"length": len(text), "max_length": MAX_EXPRESSION_LENGTH},
        )
    stripped = text.strip()
    if not stripped:
        raise ValidationError("Expressão simbólica não pode ser vazia.")

    tokens: list[_Token] = []
    n = len(stripped)
    i = 0
    while i < n:
        ch = stripped[i]
        if ch.isspace():
            i += 1
            continue

        # Números: inteiro, decimal ou notação científica (ex: 1.5e-3, .5)
        if ch.isdigit() or (ch == "." and i + 1 < n and stripped[i + 1].isdigit()):
            start = i
            has_dot = False
            while i < n and (stripped[i].isdigit() or (stripped[i] == "." and not has_dot)):
                if stripped[i] == ".":
                    has_dot = True
                i += 1
            # Notação científica opcional
            if i < n and stripped[i] in ("e", "E"):
                exp_start = i
                j = i + 1
                if j < n and stripped[j] in ("+", "-"):
                    j += 1
                if j < n and stripped[j].isdigit():
                    while j < n and stripped[j].isdigit():
                        j += 1
                    i = j
                else:
                    raise ValidationError(
                        f"Expoente científico malformado na posição {exp_start}.",
                        parameters={"expression": text, "position": exp_start},
                    )
            if i < n and (stripped[i] == "." or stripped[i].isalpha() or stripped[i] == "_"):
                raise ValidationError(
                    f"Token numérico inválido próximo a '{stripped[start:i+1]}' na posição {start}.",
                    parameters={"expression": text, "position": start},
                )
            tokens.append(_Token("NUMBER", stripped[start:i], start))
            continue

        # Identificadores (funções, constantes, variáveis)
        if ch.isalpha() or ch == "_":
            start = i
            while i < n and (stripped[i].isalnum() or stripped[i] == "_"):
                i += 1
            ident = stripped[start:i]
            if ident.startswith("_") or "__" in ident or ident in _FORBIDDEN_IDENTIFIERS:
                raise ValidationError(
                    f"Identificador proibido por política de segurança (R-21): {ident!r}.",
                    parameters={"expression": text, "identifier": ident, "position": start},
                )
            if not _IDENT_RE.match(ident):
                raise ValidationError(
                    f"Identificador inválido: {ident!r}.",
                    parameters={"expression": text, "identifier": ident, "position": start},
                )
            tokens.append(_Token("IDENT", ident, start))
            continue

        # Operadores
        if ch == "*" and i + 1 < n and stripped[i + 1] == "*":
            tokens.append(_Token("OP", "**", i))
            i += 2
            continue
        if ch in "+-*/^":
            tokens.append(_Token("OP", ch, i))
            i += 1
            continue
        if ch == "(":
            tokens.append(_Token("LPAREN", ch, i))
            i += 1
            continue
        if ch == ")":
            tokens.append(_Token("RPAREN", ch, i))
            i += 1
            continue
        if ch == ",":
            tokens.append(_Token("COMMA", ch, i))
            i += 1
            continue

        # Qualquer outro caractere ('.' fora de número, '[', ']', ';', '=', quotes, etc.) é bloqueado
        raise ValidationError(
            f"Caractere não permitido na expressão simbólica: {ch!r} na posição {i} (R-21).",
            parameters={"expression": text, "character": ch, "position": i},
        )

    tokens.append(_Token("EOF", "", n))
    return tokens


class _RecursiveDescentParser:
    def __init__(self, tokens: list[_Token], source: str) -> None:
        self._tokens = tokens
        self._source = source
        self._pos = 0
        self._depth = 0

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > MAX_AST_DEPTH:
            raise ValidationError(
                f"Profundidade máxima de expressão ({MAX_AST_DEPTH}) excedida.",
                parameters={"expression": self._source},
            )

    def _exit(self) -> None:
        self._depth -= 1

    def parse(self) -> ExprNode:
        node = self._parse_expr()
        if self._peek().kind != "EOF":
            tok = self._peek()
            raise ValidationError(
                f"Token inesperado {tok.value!r} na posição {tok.pos}.",
                parameters={"expression": self._source, "token": tok.value, "position": tok.pos},
            )
        return node

    def _parse_expr(self) -> ExprNode:
        self._enter()
        try:
            node = self._parse_term()
            while self._peek().kind == "OP" and self._peek().value in ("+", "-"):
                op = self._advance().value
                rhs = self._parse_term()
                node = BinaryOpNode(op, node, rhs)
            return node
        finally:
            self._exit()

    def _parse_term(self) -> ExprNode:
        self._enter()
        try:
            node = self._parse_unary()
            while self._peek().kind == "OP" and self._peek().value in ("*", "/"):
                op = self._advance().value
                rhs = self._parse_unary()
                node = BinaryOpNode(op, node, rhs)
            return node
        finally:
            self._exit()

    def _parse_unary(self) -> ExprNode:
        self._enter()
        try:
            if self._peek().kind == "OP" and self._peek().value in ("+", "-"):
                op = self._advance().value
                operand = self._parse_unary()
                if op == "+":
                    return operand
                return UnaryOpNode("-", operand)
            return self._parse_power()
        finally:
            self._exit()

    def _parse_power(self) -> ExprNode:
        self._enter()
        try:
            base = self._parse_primary()
            if self._peek().kind == "OP" and self._peek().value in ("^", "**"):
                self._advance()
                exponent = self._parse_unary()
                return BinaryOpNode("^", base, exponent)
            return base
        finally:
            self._exit()

    def _parse_primary(self) -> ExprNode:
        tok = self._peek()
        if tok.kind == "NUMBER":
            self._advance()
            val = float(tok.value)
            if not math.isfinite(val):
                raise ValidationError(
                    f"Literal numérico não finito: {tok.value!r}.",
                    parameters={"expression": self._source, "token": tok.value},
                )
            return NumberNode(val)

        if tok.kind == "IDENT":
            self._advance()
            name = tok.value
            if self._peek().kind == "LPAREN":
                if name not in SUPPORTED_FUNCTIONS:
                    raise ValidationError(
                        f"Função não permitida ou desconhecida: {name!r}. "
                        f"Permitidas: {sorted(SUPPORTED_FUNCTIONS)}.",
                        parameters={"expression": self._source, "function": name},
                    )
                self._advance()  # '('
                arg = self._parse_expr()
                if self._peek().kind == "COMMA":
                    raise ValidationError(
                        f"Função {name!r} aceita exatamente 1 argumento escalar.",
                        parameters={"expression": self._source, "function": name},
                    )
                if self._peek().kind != "RPAREN":
                    raise ValidationError(
                        f"Parêntese ')' esperado após argumento de {name!r} na posição {self._peek().pos}.",
                        parameters={"expression": self._source, "function": name},
                    )
                self._advance()  # ')'
                return CallNode(name, arg)

            if name in RESERVED_CONSTANTS:
                return ConstNode(name, RESERVED_CONSTANTS[name])
            if name in SUPPORTED_FUNCTIONS:
                raise ValidationError(
                    f"Função matemática {name!r} usada sem parênteses de chamada.",
                    parameters={"expression": self._source, "identifier": name},
                )
            return VarNode(name)

        if tok.kind == "LPAREN":
            self._advance()
            node = self._parse_expr()
            if self._peek().kind != "RPAREN":
                raise ValidationError(
                    f"Parêntese ')' esperado na posição {self._peek().pos}.",
                    parameters={"expression": self._source, "position": self._peek().pos},
                )
            self._advance()
            return node

        raise ValidationError(
            f"Expressão inesperada perto de {tok.value!r} na posição {tok.pos}.",
            parameters={"expression": self._source, "token": tok.value, "position": tok.pos},
        )


def _rewrite_removable_singularities(
    node: ExprNode,
    warnings_out: list[WarningItem],
) -> ExprNode:
    """Reescreve com segurança `sin(E)/(E)` -> `sinc_rad(E)` e `(1 - cos(E))/(E)` -> `cos1m_div_u(E)`."""
    if isinstance(node, (NumberNode, ConstNode, VarNode)):
        return node
    if isinstance(node, UnaryOpNode):
        return UnaryOpNode(node.op, _rewrite_removable_singularities(node.operand, warnings_out))
    if isinstance(node, CallNode):
        return CallNode(node.func, _rewrite_removable_singularities(node.arg, warnings_out))
    if isinstance(node, BinaryOpNode):
        left = _rewrite_removable_singularities(node.left, warnings_out)
        right = _rewrite_removable_singularities(node.right, warnings_out)
        if node.op == "/":
            # Padrão 1: sin(E) / E
            if isinstance(left, CallNode) and left.func == "sin" and left.arg == right:
                arg_str = format_ast(left.arg)
                warnings_out.append(
                    WarningItem(
                        code="REMOVABLE_SINGULARITY_REWRITTEN",
                        message=(
                            f"Padrão 'sin({arg_str})/({arg_str})' reescrito automaticamente "
                            f"para 'sinc_rad({arg_str})' para evitar singularidade 0/0 na origem."
                        ),
                        details={"original_pattern": "sin(E)/E", "rewritten_to": f"sinc_rad({arg_str})"},
                    )
                )
                return CallNode("sinc_rad", left.arg)
            # Padrão 2: (1 - cos(E)) / E
            if (
                isinstance(left, BinaryOpNode)
                and left.op == "-"
                and isinstance(left.left, NumberNode)
                and left.left.value == 1.0
                and isinstance(left.right, CallNode)
                and left.right.func == "cos"
                and left.right.arg == right
            ):
                arg_str = format_ast(left.right.arg)
                warnings_out.append(
                    WarningItem(
                        code="REMOVABLE_SINGULARITY_REWRITTEN",
                        message=(
                            f"Padrão '(1 - cos({arg_str}))/({arg_str})' reescrito automaticamente "
                            f"para 'cos1m_div_u({arg_str})' para evitar singularidade 0/0 na origem."
                        ),
                        details={
                            "original_pattern": "(1-cos(E))/E",
                            "rewritten_to": f"cos1m_div_u({arg_str})",
                        },
                    )
                )
                return CallNode("cos1m_div_u", left.right.arg)
        return BinaryOpNode(node.op, left, right)
    return node


def _collect_variable_counts(node: ExprNode, counts: dict[str, int], order: list[str]) -> None:
    if isinstance(node, VarNode):
        if node.name not in counts:
            order.append(node.name)
            counts[node.name] = 0
        counts[node.name] += 1
    elif isinstance(node, UnaryOpNode):
        _collect_variable_counts(node.operand, counts, order)
    elif isinstance(node, BinaryOpNode):
        _collect_variable_counts(node.left, counts, order)
        _collect_variable_counts(node.right, counts, order)
    elif isinstance(node, CallNode):
        _collect_variable_counts(node.arg, counts, order)


def parse_expression(expr: str | float | int | ParsedExpression) -> ParsedExpression:
    """Analisa uma expressão simbólica ou número escalar em uma AST tipada imutável."""
    if isinstance(expr, ParsedExpression):
        return expr
    if isinstance(expr, bool):
        raise ValidationError("Expressão simbólica não pode ser booleana.")
    if isinstance(expr, (int, float, np.integer, np.floating)):
        fval = float(expr)
        if not math.isfinite(fval):
            raise ValidationError(f"Constante numérica não finita: {expr!r}.")
        return ParsedExpression(
            source=repr(fval),
            ast=NumberNode(fval),
            active_variables=(),
            variable_counts={},
            is_sue=True,
            rewrites=(),
        )
    if not isinstance(expr, str):
        raise ValidationError(f"Tipo inválido para expressão simbólica: {type(expr).__name__}.")

    tokens = _tokenize(expr)
    raw_ast = _RecursiveDescentParser(tokens, expr).parse()
    rewrites: list[WarningItem] = []
    clean_ast = _rewrite_removable_singularities(raw_ast, rewrites)
    counts: dict[str, int] = {}
    order: list[str] = []
    _collect_variable_counts(clean_ast, counts, order)
    is_sue = all(c == 1 for c in counts.values())
    return ParsedExpression(
        source=expr.strip(),
        ast=clean_ast,
        active_variables=tuple(order),
        variable_counts=counts,
        is_sue=is_sue,
        rewrites=tuple(rewrites),
    )


def extract_active_variables(expr: str | float | int | ParsedExpression) -> tuple[str, ...]:
    """Retorna a tupla determinística de variáveis ativas na expressão."""
    return parse_expression(expr).active_variables


def is_single_use_expression(expr: str | float | int | ParsedExpression) -> bool:
    """Retorna True se cada variável ativa ocorrer no máximo uma vez na AST (SUE)."""
    return parse_expression(expr).is_sue


# ---------------------------------------------------------------------------
# Avaliação escalar e vetorizada (NumPy float64)
# ---------------------------------------------------------------------------


def _eval_scalar_node(node: ExprNode, env: Mapping[str, float]) -> float:
    if isinstance(node, NumberNode):
        return node.value
    if isinstance(node, ConstNode):
        return node.value
    if isinstance(node, VarNode):
        if node.name not in env:
            raise ValidationError(
                f"Variável {node.name!r} não fornecida no ambiente de avaliação.",
                parameters={"missing_variable": node.name, "available": sorted(env.keys())},
            )
        val = float(env[node.name])
        if not math.isfinite(val):
            raise ValidationError(f"Valor não finito para variável {node.name!r}: {val!r}.")
        return val
    if isinstance(node, UnaryOpNode):
        v = _eval_scalar_node(node.operand, env)
        return -v if node.op == "-" else v
    if isinstance(node, BinaryOpNode):
        lv = _eval_scalar_node(node.left, env)
        rv = _eval_scalar_node(node.right, env)
        if node.op == "+":
            res = lv + rv
        elif node.op == "-":
            res = lv - rv
        elif node.op == "*":
            res = lv * rv
        elif node.op == "/":
            if rv == 0.0:
                raise ValidationError("Divisão por zero detectada durante avaliação simbólica.")
            res = lv / rv
        elif node.op == "^":
            if not math.isfinite(rv):
                raise ValidationError("Expoente não finito na operação de potência.")
            if lv < 0.0 and not float(rv).is_integer():
                raise ValidationError(
                    f"Potência de base negativa ({lv}) com expoente não inteiro ({rv}) fora do domínio real."
                )
            if lv == 0.0 and rv < 0.0:
                raise ValidationError("Potência 0^p com expoente negativo (divisão por zero).")
            try:
                res = math.pow(lv, rv)
            except (ValueError, OverflowError) as exc:
                raise ValidationError(f"Erro numérico ao avaliar potência ({lv})**({rv}): {exc}") from exc
        else:
            raise ValidationError(f"Operador binário desconhecido: {node.op!r}")
        if not math.isfinite(res):
            raise ValidationError(f"Resultado não finito ({res}) na operação {node.op!r}.")
        return float(res)
    if isinstance(node, CallNode):
        x = _eval_scalar_node(node.arg, env)
        fn = node.func
        try:
            if fn == "sin":
                res = math.sin(x)
            elif fn == "cos":
                res = math.cos(x)
            elif fn == "tan":
                res = math.tan(x)
            elif fn == "asin":
                if x < -1.0 or x > 1.0:
                    raise ValidationError(f"Argumento fora do domínio de asin: {x}.")
                res = math.asin(x)
            elif fn == "acos":
                if x < -1.0 or x > 1.0:
                    raise ValidationError(f"Argumento fora do domínio de acos: {x}.")
                res = math.acos(x)
            elif fn == "atan":
                res = math.atan(x)
            elif fn == "sinh":
                res = math.sinh(x)
            elif fn == "cosh":
                res = math.cosh(x)
            elif fn == "tanh":
                res = math.tanh(x)
            elif fn == "exp":
                res = math.exp(x)
            elif fn == "log":
                if x <= 0.0:
                    raise ValidationError(f"Argumento fora do domínio de log (x <= 0): {x}.")
                res = math.log(x)
            elif fn == "sqrt":
                if x < 0.0:
                    raise ValidationError(f"Argumento fora do domínio de sqrt (x < 0): {x}.")
                res = math.sqrt(x)
            elif fn == "abs":
                res = abs(x)
            elif fn == "sign":
                res = 1.0 if x > 0.0 else (-1.0 if x < 0.0 else 0.0)
            elif fn == "sinc_rad":
                res = float(sinc_rad(x))
            elif fn == "cos1m_div_u":
                res = float(cos1m_div_u(x))
            else:
                raise ValidationError(f"Função não suportada: {fn!r}")
        except (ValueError, OverflowError) as exc:
            raise ValidationError(f"Erro numérico ao avaliar {fn}({x}): {exc}") from exc
        if not math.isfinite(res):
            raise ValidationError(f"Resultado não finito ({res}) em {fn}({x}).")
        return float(res)
    raise ValidationError(f"Nó AST não suportado: {type(node).__name__}")


def evaluate_scalar(
    expr: str | float | int | ParsedExpression,
    env: Mapping[str, float],
) -> float:
    """Avalia a expressão de forma escalar com validação estrita de domínio e finitude."""
    parsed = parse_expression(expr)
    return _eval_scalar_node(parsed.ast, env)


def _eval_vectorized_node(
    node: ExprNode,
    env: Mapping[str, np.ndarray],
    target_shape: tuple[int, ...],
) -> np.ndarray:
    if isinstance(node, NumberNode):
        return np.full(target_shape, node.value, dtype=np.float64)
    if isinstance(node, ConstNode):
        return np.full(target_shape, node.value, dtype=np.float64)
    if isinstance(node, VarNode):
        if node.name not in env:
            raise ValidationError(
                f"Variável {node.name!r} não fornecida na avaliação vetorizada.",
                parameters={"missing_variable": node.name},
            )
        return np.broadcast_to(env[node.name], target_shape).astype(np.float64, copy=False)
    if isinstance(node, UnaryOpNode):
        v = _eval_vectorized_node(node.operand, env, target_shape)
        return -v if node.op == "-" else v
    if isinstance(node, BinaryOpNode):
        lv = _eval_vectorized_node(node.left, env, target_shape)
        rv = _eval_vectorized_node(node.right, env, target_shape)
        with np.errstate(all="ignore"):
            if node.op == "+":
                res = lv + rv
            elif node.op == "-":
                res = lv - rv
            elif node.op == "*":
                res = lv * rv
            elif node.op == "/":
                if np.any(rv == 0.0):
                    raise ValidationError("Divisão por zero na avaliação vetorizada.")
                res = lv / rv
            elif node.op == "^":
                if not np.all(np.isfinite(rv)):
                    raise ValidationError("Expoente não finito na avaliação vetorizada.")
                neg_base = lv < 0.0
                if np.any(neg_base):
                    non_int = np.floor(rv) != rv
                    if np.any(neg_base & non_int):
                        raise ValidationError("Base negativa com expoente não inteiro na avaliação vetorizada.")
                if np.any((lv == 0.0) & (rv < 0.0)):
                    raise ValidationError("Potência 0^p com p < 0 na avaliação vetorizada.")
                res = np.power(lv, rv)
            else:
                raise ValidationError(f"Operador binário desconhecido: {node.op!r}")
        if not np.all(np.isfinite(res)):
            raise ValidationError(f"Resultado não finito (NaN/Inf) na operação {node.op!r}.")
        return np.asarray(res, dtype=np.float64)
    if isinstance(node, CallNode):
        x = _eval_vectorized_node(node.arg, env, target_shape)
        fn = node.func
        with np.errstate(all="ignore"):
            if fn == "sin":
                res = np.sin(x)
            elif fn == "cos":
                res = np.cos(x)
            elif fn == "tan":
                res = np.tan(x)
            elif fn == "asin":
                if np.any((x < -1.0) | (x > 1.0)):
                    raise ValidationError("Argumento fora de [-1, 1] em asin.")
                res = np.arcsin(x)
            elif fn == "acos":
                if np.any((x < -1.0) | (x > 1.0)):
                    raise ValidationError("Argumento fora de [-1, 1] em acos.")
                res = np.arccos(x)
            elif fn == "atan":
                res = np.arctan(x)
            elif fn == "sinh":
                res = np.sinh(x)
            elif fn == "cosh":
                res = np.cosh(x)
            elif fn == "tanh":
                res = np.tanh(x)
            elif fn == "exp":
                res = np.exp(x)
            elif fn == "log":
                if np.any(x <= 0.0):
                    raise ValidationError("Argumento <= 0 em log.")
                res = np.log(x)
            elif fn == "sqrt":
                if np.any(x < 0.0):
                    raise ValidationError("Argumento < 0 em sqrt.")
                res = np.sqrt(x)
            elif fn == "abs":
                res = np.abs(x)
            elif fn == "sign":
                res = np.sign(x)
            elif fn == "sinc_rad":
                res = sinc_rad(x)
            elif fn == "cos1m_div_u":
                res = cos1m_div_u(x)
            else:
                raise ValidationError(f"Função não suportada: {fn!r}")
        if not np.all(np.isfinite(res)):
            raise ValidationError(f"Resultado não finito (NaN/Inf) em {fn}.")
        return np.asarray(res, dtype=np.float64)
    raise ValidationError(f"Nó AST não suportado: {type(node).__name__}")


def evaluate_vectorized(
    expr: str | float | int | ParsedExpression,
    env: Mapping[str, np.ndarray | Sequence[float] | float],
) -> np.ndarray:
    """Avalia a expressão de forma vetorizada sobre arrays NumPy float64."""
    parsed = parse_expression(expr)
    arr_env: dict[str, np.ndarray] = {}
    shapes: list[tuple[int, ...]] = []
    for var_name in parsed.active_variables:
        if var_name not in env:
            raise ValidationError(
                f"Variável ativa {var_name!r} ausente na avaliação vetorizada.",
                parameters={"missing_variable": var_name},
            )
        arr = np.asarray(env[var_name], dtype=np.float64)
        if not np.all(np.isfinite(arr)):
            raise ValidationError(f"Valores não finitos na variável {var_name!r}.")
        arr_env[var_name] = arr
        shapes.append(arr.shape)

    if not shapes:
        # Expressão constante: herda shape de qualquer entrada presente no env, ou escalar ()
        if env:
            first_arr = np.asarray(next(iter(env.values())), dtype=np.float64)
            target_shape = first_arr.shape
        else:
            target_shape = ()
    else:
        try:
            target_shape = np.broadcast_shapes(*shapes)
        except ValueError as exc:
            raise DimensionMismatchError(f"Shapes incompatíveis nas variáveis de entrada: {shapes}") from exc

    return _eval_vectorized_node(parsed.ast, arr_env, target_shape)


# ---------------------------------------------------------------------------
# Estágio 1: Aritmética Intervalar Exata para Expressões de Uso Único (SUE)
# ---------------------------------------------------------------------------


def _interval_sin(lo: float, hi: float) -> tuple[float, float]:
    if hi - lo >= 2.0 * math.pi:
        return (-1.0, 1.0)
    vals = [math.sin(lo), math.sin(hi)]
    # Máximo em pi/2 + 2*k*pi
    k_max = math.ceil((lo - 0.5 * math.pi) / (2.0 * math.pi))
    if 0.5 * math.pi + 2.0 * math.pi * k_max <= hi:
        vals.append(1.0)
    # Mínimo em -pi/2 + 2*k*pi
    k_min = math.ceil((lo + 0.5 * math.pi) / (2.0 * math.pi))
    if -0.5 * math.pi + 2.0 * math.pi * k_min <= hi:
        vals.append(-1.0)
    return (min(vals), max(vals))


def _interval_cos(lo: float, hi: float) -> tuple[float, float]:
    if hi - lo >= 2.0 * math.pi:
        return (-1.0, 1.0)
    vals = [math.cos(lo), math.cos(hi)]
    # Máximo em 2*k*pi
    k_max = math.ceil(lo / (2.0 * math.pi))
    if 2.0 * math.pi * k_max <= hi:
        vals.append(1.0)
    # Mínimo em pi + 2*k*pi
    k_min = math.ceil((lo - math.pi) / (2.0 * math.pi))
    if math.pi + 2.0 * math.pi * k_min <= hi:
        vals.append(-1.0)
    return (min(vals), max(vals))


def _interval_eval(node: ExprNode, bounds: Mapping[str, tuple[float, float]]) -> tuple[float, float] | None:
    """Avalia intervalo exato quando aplicável; retorna None se requer fallback numérico."""
    if isinstance(node, NumberNode):
        return (node.value, node.value)
    if isinstance(node, ConstNode):
        return (node.value, node.value)
    if isinstance(node, VarNode):
        return bounds[node.name]
    if isinstance(node, UnaryOpNode):
        iv = _interval_eval(node.operand, bounds)
        if iv is None:
            return None
        return (-iv[1], -iv[0]) if node.op == "-" else iv
    if isinstance(node, BinaryOpNode):
        l_iv = _interval_eval(node.left, bounds)
        r_iv = _interval_eval(node.right, bounds)
        if l_iv is None or r_iv is None:
            return None
        a, b = l_iv
        c, d = r_iv
        if node.op == "+":
            return (a + c, b + d)
        if node.op == "-":
            return (a - d, b - c)
        if node.op == "*":
            prods = (a * c, a * d, b * c, b * d)
            return (min(prods), max(prods))
        if node.op == "/":
            if c <= 0.0 <= d:
                return None
            inv_c, inv_d = 1.0 / d, 1.0 / c
            prods = (a * inv_c, a * inv_d, b * inv_c, b * inv_d)
            return (min(prods), max(prods))
        if node.op == "^":
            # Expoente constante exato
            if c != d:
                return None
            p = c
            if p == 0.0:
                return (1.0, 1.0)
            if float(p).is_integer():
                pi_val = int(round(p))
                if pi_val > 0:
                    if pi_val % 2 == 0:
                        if a <= 0.0 <= b:
                            return (0.0, max(a**pi_val, b**pi_val))
                        vals = (a**pi_val, b**pi_val)
                        return (min(vals), max(vals))
                    return (a**pi_val, b**pi_val)
                # Negativo inteiro
                if a <= 0.0 <= b:
                    return None
                pos_iv = _interval_eval(BinaryOpNode("^", node.left, NumberNode(float(-pi_val))), bounds)
                if pos_iv is None or pos_iv[0] <= 0.0 <= pos_iv[1]:
                    return None
                return (1.0 / pos_iv[1], 1.0 / pos_iv[0])
            # Expoente real não inteiro
            if p > 0.0:
                if a < 0.0:
                    return None
                return (math.pow(a, p), math.pow(b, p))
            if a <= 0.0:
                return None
            return (math.pow(b, p), math.pow(a, p))
        return None
    if isinstance(node, CallNode):
        iv = _interval_eval(node.arg, bounds)
        if iv is None:
            return None
        a, b = iv
        fn = node.func
        if fn == "sin":
            return _interval_sin(a, b)
        if fn == "cos":
            return _interval_cos(a, b)
        if fn == "abs":
            if a <= 0.0 <= b:
                return (0.0, max(abs(a), abs(b)))
            vals = (abs(a), abs(b))
            return (min(vals), max(vals))
        if fn == "exp":
            try:
                return (math.exp(a), math.exp(b))
            except OverflowError:
                return None
        if fn == "log":
            if a <= 0.0:
                return None
            return (math.log(a), math.log(b))
        if fn == "sqrt":
            if a < 0.0:
                return None
            return (math.sqrt(a), math.sqrt(b))
        if fn == "tanh":
            return (math.tanh(a), math.tanh(b))
        if fn == "sinh":
            try:
                return (math.sinh(a), math.sinh(b))
            except OverflowError:
                return None
        if fn == "cosh":
            try:
                if a <= 0.0 <= b:
                    return (1.0, max(math.cosh(a), math.cosh(b)))
                vals = (math.cosh(a), math.cosh(b))
                return (min(vals), max(vals))
            except OverflowError:
                return None
        if fn == "atan":
            return (math.atan(a), math.atan(b))
        if fn == "asin":
            if a < -1.0 or b > 1.0:
                return None
            return (math.asin(a), math.asin(b))
        if fn == "acos":
            if a < -1.0 or b > 1.0:
                return None
            return (math.acos(b), math.acos(a))
        if fn == "sinc_rad":
            if max(abs(a), abs(b)) <= math.pi:
                sa, sb = float(sinc_rad(a)), float(sinc_rad(b))
                if a <= 0.0 <= b:
                    return (min(sa, sb), 1.0)
                return (min(sa, sb), max(sa, sb))
            return None
        return None
    return None


# ---------------------------------------------------------------------------
# Pipeline Híbrido Determinístico em 3 Estágios para Extremos Globais
# ---------------------------------------------------------------------------


def _select_distinct_candidates(
    points: np.ndarray,
    values: np.ndarray,
    *,
    k: int,
    find_max: bool,
    scale: np.ndarray,
) -> list[np.ndarray]:
    """Seleciona até `k` pontos candidatos distintos (mínimos ou máximos) com separação espacial."""
    order = np.argsort(-values if find_max else values)
    selected: list[np.ndarray] = []
    min_rel_dist = 1e-3
    safe_scale = np.where(scale > 0.0, scale, 1.0)

    for idx in order:
        cand = points[idx]
        if not selected:
            selected.append(cand)
        else:
            dists = [float(np.linalg.norm((cand - prev) / safe_scale)) for prev in selected]
            if min(dists) >= min_rel_dist:
                selected.append(cand)
        if len(selected) >= k:
            break

    # Se não houver k suficientemente distantes, completa com os melhores restantes
    if len(selected) < min(k, len(order)):
        for idx in order:
            cand = points[idx]
            if all(not np.allclose(cand, prev, atol=1e-12, rtol=1e-12) for prev in selected):
                selected.append(cand)
            if len(selected) >= k:
                break
    return selected


def _build_stage2_samples(
    lo: np.ndarray,
    hi: np.ndarray,
    *,
    sobol_samples: int = 16384,
) -> tuple[np.ndarray, float]:
    """Gera grade adaptativa + vértices + Sobol determinístico no subespaço ativo d."""
    d = int(lo.size)
    if d == 1:
        grid = np.linspace(lo[0], hi[0], 4097, dtype=np.float64)
        if lo[0] < 0.0 < hi[0]:
            grid = np.unique(np.concatenate([grid, np.array([0.0], dtype=np.float64)]))
        step = float((hi[0] - lo[0]) / 4096.0)
        return grid[:, None], step

    if d == 2:
        g1 = np.linspace(lo[0], hi[0], 257, dtype=np.float64)
        g2 = np.linspace(lo[1], hi[1], 257, dtype=np.float64)
        m1, m2 = np.meshgrid(g1, g2, indexing="ij")
        pts = np.stack([m1.ravel(), m2.ravel()], axis=-1)
        # Injeção de eixos coordenados se 0 estiver no domínio
        extra: list[np.ndarray] = []
        if lo[0] < 0.0 < hi[0]:
            extra.append(np.stack([np.zeros_like(g2), g2], axis=-1))
        if lo[1] < 0.0 < hi[1]:
            extra.append(np.stack([g1, np.zeros_like(g1)], axis=-1))
        if extra:
            pts = np.vstack([pts, *extra])
        return pts, float(np.max((hi - lo) / 256.0))

    if d == 3:
        g1 = np.linspace(lo[0], hi[0], 65, dtype=np.float64)
        g2 = np.linspace(lo[1], hi[1], 65, dtype=np.float64)
        g3 = np.linspace(lo[2], hi[2], 65, dtype=np.float64)
        m1, m2, m3 = np.meshgrid(g1, g2, g3, indexing="ij")
        pts = np.stack([m1.ravel(), m2.ravel(), m3.ravel()], axis=-1)
        return pts, float(np.max((hi - lo) / 64.0))

    # d >= 4: vértices 2^d (para d <= 10) + grade grossa + Sobol determinístico
    blocks: list[np.ndarray] = []
    if d <= 10:
        verts = np.array(list(itertools.product(*zip(lo.tolist(), hi.tolist()))), dtype=np.float64)
        blocks.append(verts)

    pts_per_axis = max(2, int(math.floor(16384 ** (1.0 / d))))
    if pts_per_axis >= 3 and (pts_per_axis**d) <= 20000:
        axes = [np.linspace(lo[i], hi[i], pts_per_axis, dtype=np.float64) for i in range(d)]
        meshes = np.meshgrid(*axes, indexing="ij")
        blocks.append(np.stack([m.ravel() for m in meshes], axis=-1))

    # Potência de 2 para Sobol sem aviso de balanceamento
    m_pow = max(1, int(math.ceil(math.log2(max(2, sobol_samples)))))
    sampler = qmc.Sobol(d=d, scramble=True, seed=42)
    unit_pts = sampler.random_base2(m=m_pow)
    if unit_pts.shape[0] > sobol_samples:
        unit_pts = unit_pts[:sobol_samples]
    sobol_pts = lo + unit_pts * (hi - lo)
    blocks.append(sobol_pts)

    # Ponto médio do hipercubo
    blocks.append((0.5 * (lo + hi))[None, :])
    return np.vstack(blocks), float(np.max(hi - lo) / 10.0)


def find_global_extrema(
    expr: str | float | int | ParsedExpression,
    bounds: Mapping[str, Sequence[float]],
    *,
    user_override: Sequence[float] | None = None,
    n_multistart: int = 8,
    sobol_samples: int = 16384,
    constant_tol: float = 1e-12,
) -> dict[str, Any]:
    """Determina extremos globais certificados `[z_min, z_max]` pelo pipeline híbrido em 3 estágios."""
    parsed = parse_expression(expr)
    warnings_list: list[WarningItem] = list(parsed.rewrites)
    active_vars = parsed.active_variables
    d = len(active_vars)

    # Validação de bounds das variáveis ativas
    clean_bounds: dict[str, tuple[float, float]] = {}
    for v in active_vars:
        if v not in bounds:
            raise ValidationError(
                f"Limite de domínio ausente para variável ativa {v!r}.",
                parameters={"missing_variable": v, "available_bounds": sorted(bounds.keys())},
            )
        pair = bounds[v]
        if not isinstance(pair, Sequence) or isinstance(pair, (str, bytes)) or len(pair) != 2:
            raise ValidationError(f"Limite inválido para {v!r}: esperado [min, max].")
        v_lo, v_hi = float(pair[0]), float(pair[1])
        if not (math.isfinite(v_lo) and math.isfinite(v_hi)) or v_lo > v_hi:
            raise ValidationError(
                f"Intervalo inválido para {v!r}: [{v_lo}, {v_hi}].",
                parameters={"variable": v, "bounds": [v_lo, v_hi]},
            )
        clean_bounds[v] = (v_lo, v_hi)

    # Caso d == 0 (constante)
    if d == 0:
        val = evaluate_scalar(parsed, {})
        warnings_list.append(
            WarningItem(
                code="DEGENERATE_CONSTANT_PREMISE",
                message=(
                    f"Expressão '{parsed.source}' é constante ({val:.6g}) no domínio; "
                    "substitua-a pelo valor escalar constante para economizar metade das regras."
                ),
                details={"value": val},
            )
        )
        return _finalize_extrema_result(
            parsed=parsed,
            computed_min=val,
            computed_max=val,
            argmin_point={},
            argmax_point={},
            stage1_ia_bounds=(val, val),
            method="constant",
            warnings_list=warnings_list,
            user_override=user_override,
            constant_tol=constant_tol,
        )

    # Estágio 1: Aritmética Intervalar exata quando SUE
    stage1_ia: tuple[float, float] | None = None
    if parsed.is_sue:
        ia_res = _interval_eval(parsed.ast, clean_bounds)
        if ia_res is not None and math.isfinite(ia_res[0]) and math.isfinite(ia_res[1]):
            stage1_ia = (float(ia_res[0]), float(ia_res[1]))

    # Verifica se todas as variáveis ativas têm intervalo degenerado (lo == hi)
    lo_arr = np.array([clean_bounds[v][0] for v in active_vars], dtype=np.float64)
    hi_arr = np.array([clean_bounds[v][1] for v in active_vars], dtype=np.float64)
    if np.all(hi_arr == lo_arr):
        pt = {active_vars[i]: float(lo_arr[i]) for i in range(d)}
        val = evaluate_scalar(parsed, pt)
        warnings_list.append(
            WarningItem(
                code="DEGENERATE_CONSTANT_PREMISE",
                message=(
                    f"Expressão '{parsed.source}' é constante ({val:.6g}) porque o domínio ativo é pontual."
                ),
                details={"value": val},
            )
        )
        return _finalize_extrema_result(
            parsed=parsed,
            computed_min=val,
            computed_max=val,
            argmin_point=pt,
            argmax_point=pt,
            stage1_ia_bounds=stage1_ia,
            method="degenerate_domain",
            warnings_list=warnings_list,
            user_override=user_override,
            constant_tol=constant_tol,
        )

    # Estágio 2: Varredura vetorizada densa no subespaço ativo
    pts, grid_step = _build_stage2_samples(lo_arr, hi_arr, sobol_samples=sobol_samples)
    env_vec = {active_vars[i]: pts[:, i] for i in range(d)}
    vals = evaluate_vectorized(parsed, env_vec)

    best_min_idx = int(np.argmin(vals))
    best_max_idx = int(np.argmax(vals))
    best_min_val = float(vals[best_min_idx])
    best_max_val = float(vals[best_max_idx])
    best_min_pt = pts[best_min_idx].copy()
    best_max_pt = pts[best_max_idx].copy()

    # Estágio 3: Polimento contínuo multi-start (M = n_multistart)
    scale = hi_arr - lo_arr
    min_cands = _select_distinct_candidates(pts, vals, k=n_multistart, find_max=False, scale=scale)
    max_cands = _select_distinct_candidates(pts, vals, k=n_multistart, find_max=True, scale=scale)

    def _scalar_obj(x_vec: np.ndarray, sign: float) -> float:
        xc = np.clip(x_vec, lo_arr, hi_arr)
        env_s = {active_vars[i]: float(xc[i]) for i in range(d)}
        try:
            return sign * _eval_scalar_node(parsed.ast, env_s)
        except ValidationError:
            return 1e300

    if d == 1:
        b_lo, b_hi = float(lo_arr[0]), float(hi_arr[0])
        win = max(2.0 * grid_step, 1e-9 * max(1.0, b_hi - b_lo))

        def _f1(x_s: float) -> float:
            try:
                return _eval_scalar_node(parsed.ast, {active_vars[0]: float(x_s)})
            except ValidationError:
                return 1e300

        def _nf1(x_s: float) -> float:
            try:
                return -_eval_scalar_node(parsed.ast, {active_vars[0]: float(x_s)})
            except ValidationError:
                return 1e300

        for cand in min_cands:
            c0 = float(cand[0])
            s_lo = max(b_lo, c0 - win)
            s_hi = min(b_hi, c0 + win)
            if s_hi > s_lo:
                res = minimize_scalar(_f1, bounds=(s_lo, s_hi), method="bounded", options={"xatol": 1e-13})
                x_opt = float(np.clip(res.x, b_lo, b_hi))
                f_opt = _f1(x_opt)
                if f_opt < best_min_val:
                    best_min_val = f_opt
                    best_min_pt = np.array([x_opt], dtype=np.float64)

        for cand in max_cands:
            c0 = float(cand[0])
            s_lo = max(b_lo, c0 - win)
            s_hi = min(b_hi, c0 + win)
            if s_hi > s_lo:
                res = minimize_scalar(_nf1, bounds=(s_lo, s_hi), method="bounded", options={"xatol": 1e-13})
                x_opt = float(np.clip(res.x, b_lo, b_hi))
                f_opt = _f1(x_opt)
                if f_opt > best_max_val:
                    best_max_val = f_opt
                    best_max_pt = np.array([x_opt], dtype=np.float64)
    else:
        box_bounds = [(float(lo_arr[i]), float(hi_arr[i])) for i in range(d)]

        for sign, cands in ((1.0, min_cands), (-1.0, max_cands)):
            for cand in cands:
                res = minimize(
                    _scalar_obj,
                    x0=cand,
                    args=(sign,),
                    method="L-BFGS-B",
                    bounds=box_bounds,
                    options={"ftol": 1e-15, "gtol": 1e-12, "maxiter": 200},
                )
                x_opt = np.clip(np.asarray(res.x, dtype=np.float64), lo_arr, hi_arr)
                f_opt = _scalar_obj(x_opt, 1.0)
                if not res.success:
                    res_p = minimize(
                        _scalar_obj,
                        x0=x_opt,
                        args=(sign,),
                        method="Powell",
                        bounds=box_bounds,
                        options={"xtol": 1e-12, "ftol": 1e-14, "maxiter": 200},
                    )
                    xp = np.clip(np.asarray(res_p.x, dtype=np.float64), lo_arr, hi_arr)
                    fp = _scalar_obj(xp, 1.0)
                    if (sign > 0 and fp < f_opt) or (sign < 0 and fp > f_opt):
                        x_opt, f_opt = xp, fp

                if sign > 0 and f_opt < best_min_val:
                    best_min_val = f_opt
                    best_min_pt = x_opt
                elif sign < 0 and f_opt > best_max_val:
                    best_max_val = f_opt
                    best_max_pt = x_opt

    # Combina garantia analítica da Aritmética Intervalar (SUE) com o polimento
    method = "hybrid_stage2_stage3"
    if stage1_ia is not None:
        ia_min, ia_max = stage1_ia
        if ia_min < best_min_val:
            best_min_val = ia_min
        if ia_max > best_max_val:
            best_max_val = ia_max
        method = "exact_interval_sue_plus_polish"

    argmin_dict = {active_vars[i]: float(best_min_pt[i]) for i in range(d)}
    argmax_dict = {active_vars[i]: float(best_max_pt[i]) for i in range(d)}

    if best_max_val - best_min_val <= constant_tol:
        warnings_list.append(
            WarningItem(
                code="DEGENERATE_CONSTANT_PREMISE",
                message=(
                    f"Premissa '{parsed.source}' é efetivamente constante no domínio "
                    f"(max - min = {best_max_val - best_min_val:.3e} <= {constant_tol:.1e}); "
                    "substitua-a pelo valor escalar constante para economizar metade das regras."
                ),
                details={"min": best_min_val, "max": best_max_val},
            )
        )

    return _finalize_extrema_result(
        parsed=parsed,
        computed_min=best_min_val,
        computed_max=best_max_val,
        argmin_point=argmin_dict,
        argmax_point=argmax_dict,
        stage1_ia_bounds=stage1_ia,
        method=method,
        warnings_list=warnings_list,
        user_override=user_override,
        constant_tol=constant_tol,
    )


def _finalize_extrema_result(
    *,
    parsed: ParsedExpression,
    computed_min: float,
    computed_max: float,
    argmin_point: dict[str, float],
    argmax_point: dict[str, float],
    stage1_ia_bounds: tuple[float, float] | None,
    method: str,
    warnings_list: list[WarningItem],
    user_override: Sequence[float] | None,
    constant_tol: float,
) -> dict[str, Any]:
    eff_min = float(computed_min)
    eff_max = float(computed_max)
    override_applied = False
    override_violates_positivity = False

    if user_override is not None:
        if not isinstance(user_override, Sequence) or isinstance(user_override, (str, bytes)) or len(user_override) != 2:
            raise ValidationError("user_override deve ser uma sequência [user_min, user_max] com 2 números.")
        u_min, u_max = float(user_override[0]), float(user_override[1])
        if not (math.isfinite(u_min) and math.isfinite(u_max)) or u_min > u_max:
            raise ValidationError(f"user_override inválido: [{u_min}, {u_max}].")
        override_applied = True
        if u_min > computed_min + 1e-12 or u_max < computed_max - 1e-12:
            override_violates_positivity = True
            warnings_list.append(
                WarningItem(
                    code="SECTOR_BOUNDS_OVERRIDE_NARROWER",
                    message=(
                        f"Override manual [{u_min:.6g}, {u_max:.6g}] é mais estreito que os extremos "
                        f"certificados [{computed_min:.6g}, {computed_max:.6g}]; "
                        "isso causará violação de não-negatividade (w_{k,j} < 0) no domínio."
                    ),
                    details={
                        "user_bounds": [u_min, u_max],
                        "computed_bounds": [computed_min, computed_max],
                    },
                )
            )
        eff_min, eff_max = u_min, u_max

    return {
        "expression": parsed.source,
        "rewritten_expression": parsed.to_string(),
        "active_variables": list(parsed.active_variables),
        "is_sue": parsed.is_sue,
        "min": eff_min,
        "max": eff_max,
        "computed_min": float(computed_min),
        "computed_max": float(computed_max),
        "argmin_point": argmin_point,
        "argmax_point": argmax_point,
        "stage1_ia_bounds": list(stage1_ia_bounds) if stage1_ia_bounds is not None else None,
        "method": method,
        "is_constant": bool((eff_max - eff_min) <= constant_tol),
        "override_applied": override_applied,
        "override_violates_positivity": override_violates_positivity,
        "warnings": [w.to_dict() for w in warnings_list],
        "_warning_items": tuple(warnings_list),
    }


# ---------------------------------------------------------------------------
# Verificador de Isolamento de Variáveis e Afinidade/Multilinearidade em z
# ---------------------------------------------------------------------------


def verify_matrix_multilinearity(
    matrices: Mapping[str, Sequence[Sequence[str | float | int | ParsedExpression]]],
    premise_names: Sequence[str],
    premise_bounds: Mapping[str, Sequence[float]],
    *,
    rel_tol: float = 1e-11,
) -> dict[str, Any]:
    """Verifica isolamento de variáveis e multilinearidade exata das matrizes qLPV em `z = (z_1, ..., z_nn)`.

    Retorna dicionário diagnóstico com:
    - `is_valid`: True se isolamento e multilinearidade passarem em todas as matrizes;
    - `isolation_violations`: lista de entradas que referenciam variáveis fora de `premise_names`;
    - `non_affine_entries`: lista de entradas `(matrix_name, row, col, premise, deviation)` não-afins;
    - `max_collinearity_deviation`: maior desvio relativo encontrado.
    """
    allowed_set = set(premise_names)
    p_names = list(premise_names)
    nn = len(p_names)

    # 1. Parse de todas as entradas e checagem de isolamento de variáveis
    parsed_mats: dict[str, list[list[ParsedExpression]]] = {}
    isolation_violations: list[dict[str, Any]] = []
    warnings_list: list[WarningItem] = []

    for mat_name, mat_rows in matrices.items():
        if not isinstance(mat_rows, Sequence) or isinstance(mat_rows, (str, bytes)) or len(mat_rows) == 0:
            raise ValidationError(f"Matriz simbólica {mat_name!r} deve ser uma lista 2D não vazia.")
        parsed_rows: list[list[ParsedExpression]] = []
        n_cols: int | None = None
        for i, row in enumerate(mat_rows):
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) == 0:
                raise ValidationError(f"Linha {i} da matriz {mat_name!r} deve ser sequência não vazia.")
            if n_cols is None:
                n_cols = len(row)
            elif len(row) != n_cols:
                raise DimensionMismatchError(
                    f"Matriz simbólica {mat_name!r} possui linhas de comprimentos distintos ({n_cols} vs {len(row)})."
                )
            p_row: list[ParsedExpression] = []
            for j, cell in enumerate(row):
                pe = parse_expression(cell)
                warnings_list.extend(pe.rewrites)
                illegal = [v for v in pe.active_variables if v not in allowed_set]
                if illegal:
                    isolation_violations.append(
                        {
                            "matrix_name": mat_name,
                            "row": i,
                            "col": j,
                            "expression": pe.source,
                            "illegal_variables": illegal,
                            "hint": (
                                f"Entrada {mat_name}[{i},{j}] referencia {illegal}, que não pertence às premissas "
                                f"declaradas {p_names}. Crie uma premissa z_k para essas variáveis ou use a Via 2 (TPMT)."
                            ),
                        }
                    )
                p_row.append(pe)
            parsed_rows.append(p_row)
        parsed_mats[mat_name] = parsed_rows

    if isolation_violations:
        return {
            "is_valid": False,
            "isolation_ok": False,
            "is_multilinear": False,
            "isolation_violations": isolation_violations,
            "non_affine_entries": [],
            "max_collinearity_deviation": float("inf"),
            "warnings": [w.to_dict() for w in warnings_list],
        }

    # 2. Checagem numérica determinística de multilinearidade em cada z_k
    lo_z = np.array([float(premise_bounds[nm][0]) for nm in p_names], dtype=np.float64)
    hi_z = np.array([float(premise_bounds[nm][1]) for nm in p_names], dtype=np.float64)

    # 5 contextos determinísticos de z_{-k} para evitar cancelamento acidental
    ctx_fracs = [0.0, 0.23, 0.5, 0.77, 1.0]
    non_affine_entries: list[dict[str, Any]] = []
    seen_entry_keys: set[tuple[str, int, int, str]] = set()
    max_dev_overall = 0.0

    for k, z_name in enumerate(p_names):
        zk_lo, zk_hi = float(lo_z[k]), float(hi_z[k])
        if abs(zk_hi - zk_lo) <= 1e-15:
            continue
        zk_mid = 0.5 * (zk_lo + zk_hi)
        zk_qtr = 0.25 * zk_lo + 0.75 * zk_hi

        for f_idx, frac in enumerate(ctx_fracs):
            # Varia a fração por coordenada para que z_{-k} não fique apenas na diagonal
            base_env: dict[str, float] = {}
            for l_idx, l_name in enumerate(p_names):
                if l_idx == k:
                    continue
                shifted = (frac + 0.17 * l_idx + 0.07 * f_idx) % 1.0
                base_env[l_name] = float(lo_z[l_idx] + shifted * (hi_z[l_idx] - lo_z[l_idx]))

            env_lo = {**base_env, z_name: zk_lo}
            env_hi = {**base_env, z_name: zk_hi}
            env_mid = {**base_env, z_name: zk_mid}
            env_qtr = {**base_env, z_name: zk_qtr}

            for mat_name, p_rows in parsed_mats.items():
                n_r = len(p_rows)
                n_c = len(p_rows[0])
                M_lo = np.empty((n_r, n_c), dtype=np.float64)
                M_hi = np.empty((n_r, n_c), dtype=np.float64)
                M_mid = np.empty((n_r, n_c), dtype=np.float64)
                M_qtr = np.empty((n_r, n_c), dtype=np.float64)

                for i in range(n_r):
                    for j in range(n_c):
                        pe = p_rows[i][j]
                        M_lo[i, j] = _eval_scalar_node(pe.ast, env_lo)
                        M_hi[i, j] = _eval_scalar_node(pe.ast, env_hi)
                        M_mid[i, j] = _eval_scalar_node(pe.ast, env_mid)
                        M_qtr[i, j] = _eval_scalar_node(pe.ast, env_qtr)

                diff_mid = M_mid - 0.5 * (M_lo + M_hi)
                diff_qtr = M_qtr - (0.25 * M_lo + 0.75 * M_hi)
                norm_s = float(np.linalg.norm(M_mid, ord="fro"))
                dev_frob = max(
                    float(np.linalg.norm(diff_mid, ord="fro")),
                    float(np.linalg.norm(diff_qtr, ord="fro")),
                )
                tol_frob = rel_tol * (1.0 + norm_s)
                if norm_s > 0.0:
                    max_dev_overall = max(max_dev_overall, dev_frob / (1.0 + norm_s))
                else:
                    max_dev_overall = max(max_dev_overall, dev_frob)

                if dev_frob > tol_frob:
                    for i in range(n_r):
                        for j in range(n_c):
                            cell_dev = max(abs(float(diff_mid[i, j])), abs(float(diff_qtr[i, j])))
                            cell_tol = rel_tol * (1.0 + abs(float(M_mid[i, j])))
                            if cell_dev > cell_tol:
                                key = (mat_name, i, j, z_name)
                                if key not in seen_entry_keys:
                                    seen_entry_keys.add(key)
                                    non_affine_entries.append(
                                        {
                                            "matrix_name": mat_name,
                                            "row": i,
                                            "col": j,
                                            "premise": z_name,
                                            "expression": p_rows[i][j].source,
                                            "collinearity_deviation": cell_dev,
                                        }
                                    )

    is_multilinear = len(non_affine_entries) == 0
    return {
        "is_valid": is_multilinear,
        "isolation_ok": True,
        "is_multilinear": is_multilinear,
        "isolation_violations": [],
        "non_affine_entries": non_affine_entries,
        "max_collinearity_deviation": float(max_dev_overall),
        "warnings": [w.to_dict() for w in warnings_list],
    }
