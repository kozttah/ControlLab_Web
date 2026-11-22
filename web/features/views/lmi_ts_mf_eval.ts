/**
 * Avaliador Analítico Determinístico e Validador de Soma Convexa para Funções de Ponderação TS h_i(z)
 * (`WP-PHASE4-05-F8-TS-SECTOR-MF-EXPRESSIONS`).
 *
 * Segurança & Regras:
 * - Zero `eval`, zero `new Function`.
 * - Parser descendente recursivo puro em TypeScript compatível com `erasableSyntaxOnly` e `verbatimModuleSyntax`.
 * - Suporta números (incluindo notação científica), constantes `pi` e `e`, variáveis de premissa,
 *   operadores `+`, `-`, `*`, `/`, `^`, unários `+`/`-`, parênteses e funções analíticas:
 *   `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sinh`, `cosh`, `tanh`, `exp`, `log`, `sqrt`, `abs`, `min`, `max`.
 */

export interface TsPremiseDomain {
  name: string;
  min: number;
  max: number;
}

export interface TsWeightFunctionDef {
  label: string;
  expression: string;
}

export interface TsConvexityValidationResult {
  valid: boolean;
  message: string;
  minWeight: number;
  maxSumError: number;
  counterexample?: Record<string, number>;
}

type MathAstNode =
  | { kind: "num"; value: number }
  | { kind: "var"; name: string }
  | { kind: "unary"; op: "+" | "-"; arg: MathAstNode }
  | { kind: "binary"; op: "+" | "-" | "*" | "/" | "^"; left: MathAstNode; right: MathAstNode }
  | { kind: "call"; fn: string; args: MathAstNode[] };

interface MathToken {
  type: "num" | "id" | "op" | "lparen" | "rparen" | "comma";
  val: string;
  pos: number;
}

const UNARY_FUNCTIONS: Record<string, (x: number) => number> = {
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  sinh: Math.sinh,
  cosh: Math.cosh,
  tanh: Math.tanh,
  exp: Math.exp,
  log: (x: number): number => {
    if (x <= 0) {
      throw new Error(`Argumento inválido para log(${x}): esperado > 0.`);
    }
    return Math.log(x);
  },
  sqrt: (x: number): number => {
    if (x < 0) {
      throw new Error(`Argumento inválido para sqrt(${x}): esperado >= 0.`);
    }
    return Math.sqrt(x);
  },
  abs: Math.abs,
};

const BINARY_FUNCTIONS: Record<string, (a: number, b: number) => number> = {
  min: Math.min,
  max: Math.max,
};

function tokenizeMathExpr(expr: string): MathToken[] {
  const tokens: MathToken[] = [];
  let i = 0;
  const len = expr.length;
  while (i < len) {
    const ch = expr[i];
    if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r") {
      i += 1;
      continue;
    }
    if (ch === "(") {
      tokens.push({ type: "lparen", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === ")") {
      tokens.push({ type: "rparen", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === ",") {
      tokens.push({ type: "comma", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === "+" || ch === "-" || ch === "*" || ch === "/" || ch === "^") {
      tokens.push({ type: "op", val: ch, pos: i });
      i += 1;
      continue;
    }
    const numMatch = /^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/.exec(expr.slice(i));
    if (numMatch) {
      tokens.push({ type: "num", val: numMatch[0], pos: i });
      i += numMatch[0].length;
      continue;
    }
    const idMatch = /^[A-Za-z_][A-Za-z0-9_]*/.exec(expr.slice(i));
    if (idMatch) {
      tokens.push({ type: "id", val: idMatch[0], pos: i });
      i += idMatch[0].length;
      continue;
    }
    throw new Error(`Caractere inesperado '${ch}' na posição ${i}.`);
  }
  return tokens;
}

class MathExprParser {
  private readonly tokens: MathToken[];
  private pos = 0;

  constructor(tokens: MathToken[]) {
    this.tokens = tokens;
  }

  private peek(): MathToken | undefined {
    return this.tokens[this.pos];
  }

  private consume(): MathToken {
    const tok = this.tokens[this.pos];
    if (!tok) {
      throw new Error("Fim inesperado da expressão.");
    }
    this.pos += 1;
    return tok;
  }

  public parse(): MathAstNode {
    if (this.tokens.length === 0) {
      throw new Error("Expressão vazia.");
    }
    const node = this.parseAddSub();
    if (this.pos < this.tokens.length) {
      const extra = this.tokens[this.pos];
      throw new Error(`Token inesperado '${extra.val}' na posição ${extra.pos}.`);
    }
    return node;
  }

  private parseAddSub(): MathAstNode {
    let left = this.parseMulDiv();
    while (true) {
      const tok = this.peek();
      if (tok && tok.type === "op" && (tok.val === "+" || tok.val === "-")) {
        this.consume();
        const right = this.parseMulDiv();
        left = { kind: "binary", op: tok.val, left, right };
      } else {
        break;
      }
    }
    return left;
  }

  private parseMulDiv(): MathAstNode {
    let left = this.parseUnary();
    while (true) {
      const tok = this.peek();
      if (tok && tok.type === "op" && (tok.val === "*" || tok.val === "/")) {
        this.consume();
        const right = this.parseUnary();
        left = { kind: "binary", op: tok.val, left, right };
      } else {
        break;
      }
    }
    return left;
  }

  private parseUnary(): MathAstNode {
    const tok = this.peek();
    if (tok && tok.type === "op" && (tok.val === "+" || tok.val === "-")) {
      this.consume();
      const arg = this.parseUnary();
      return { kind: "unary", op: tok.val, arg };
    }
    return this.parsePower();
  }

  private parsePower(): MathAstNode {
    const base = this.parsePrimary();
    const tok = this.peek();
    if (tok && tok.type === "op" && tok.val === "^") {
      this.consume();
      // Right-associative power, allowing unary exponent such as 2^-1
      const exponent = this.parseUnary();
      return { kind: "binary", op: "^", left: base, right: exponent };
    }
    return base;
  }

  private parsePrimary(): MathAstNode {
    const tok = this.peek();
    if (!tok) {
      throw new Error("Expressão incompleta.");
    }
    if (tok.type === "num") {
      this.consume();
      const val = Number(tok.val);
      if (!Number.isFinite(val)) {
        throw new Error(`Número inválido '${tok.val}'.`);
      }
      return { kind: "num", value: val };
    }
    if (tok.type === "lparen") {
      this.consume();
      const inner = this.parseAddSub();
      const close = this.peek();
      if (!close || close.type !== "rparen") {
        throw new Error("Parêntese ')' esperado.");
      }
      this.consume();
      return inner;
    }
    if (tok.type === "id") {
      this.consume();
      const next = this.peek();
      if (next && next.type === "lparen") {
        this.consume();
        const args: MathAstNode[] = [];
        const maybeClose = this.peek();
        if (!maybeClose || maybeClose.type !== "rparen") {
          while (true) {
            args.push(this.parseAddSub());
            const sep = this.peek();
            if (sep && sep.type === "comma") {
              this.consume();
              continue;
            }
            break;
          }
        }
        const close = this.peek();
        if (!close || close.type !== "rparen") {
          throw new Error(`Parêntese ')' esperado após argumentos de '${tok.val}'.`);
        }
        this.consume();
        if (Object.prototype.hasOwnProperty.call(UNARY_FUNCTIONS, tok.val)) {
          if (args.length !== 1) {
            throw new Error(`Função '${tok.val}' espera 1 argumento.`);
          }
        } else if (Object.prototype.hasOwnProperty.call(BINARY_FUNCTIONS, tok.val)) {
          if (args.length !== 2) {
            throw new Error(`Função '${tok.val}' espera 2 argumentos.`);
          }
        } else {
          throw new Error(`Função desconhecida '${tok.val}'.`);
        }
        return { kind: "call", fn: tok.val, args };
      }
      if (tok.val === "pi") {
        return { kind: "num", value: Math.PI };
      }
      if (tok.val === "e") {
        return { kind: "num", value: Math.E };
      }
      return { kind: "var", name: tok.val };
    }
    throw new Error(`Token inesperado '${tok.val}' na posição ${tok.pos}.`);
  }
}

function evalAstNode(node: MathAstNode, env: Record<string, number>): number {
  switch (node.kind) {
    case "num":
      return node.value;
    case "var": {
      if (!Object.prototype.hasOwnProperty.call(env, node.name)) {
        throw new Error(`Variável desconhecida '${node.name}'.`);
      }
      const val = env[node.name];
      if (!Number.isFinite(val)) {
        throw new Error(`Valor não finito para variável '${node.name}'.`);
      }
      return val;
    }
    case "unary": {
      const v = evalAstNode(node.arg, env);
      return node.op === "-" ? -v : v;
    }
    case "binary": {
      const l = evalAstNode(node.left, env);
      const r = evalAstNode(node.right, env);
      let out: number;
      switch (node.op) {
        case "+":
          out = l + r;
          break;
        case "-":
          out = l - r;
          break;
        case "*":
          out = l * r;
          break;
        case "/":
          if (r === 0) {
            throw new Error("Divisão por zero.");
          }
          out = l / r;
          break;
        case "^":
          out = Math.pow(l, r);
          break;
      }
      if (!Number.isFinite(out)) {
        throw new Error("Resultado numérico não finito (NaN/Infinity).");
      }
      return out;
    }
    case "call": {
      if (Object.prototype.hasOwnProperty.call(UNARY_FUNCTIONS, node.fn)) {
        const argVal = evalAstNode(node.args[0], env);
        const out = UNARY_FUNCTIONS[node.fn](argVal);
        if (!Number.isFinite(out)) {
          throw new Error(`Resultado não finito em '${node.fn}(${argVal})'.`);
        }
        return out;
      }
      if (Object.prototype.hasOwnProperty.call(BINARY_FUNCTIONS, node.fn)) {
        const a = evalAstNode(node.args[0], env);
        const b = evalAstNode(node.args[1], env);
        const out = BINARY_FUNCTIONS[node.fn](a, b);
        if (!Number.isFinite(out)) {
          throw new Error(`Resultado não finito em '${node.fn}(${a}, ${b})'.`);
        }
        return out;
      }
      throw new Error(`Função desconhecida '${node.fn}'.`);
    }
  }
}

export function compileMathExpression(
  expression: string,
): (env: Record<string, number>) => number {
  const trimmed = expression.trim();
  const tokens = tokenizeMathExpr(trimmed);
  const ast = new MathExprParser(tokens).parse();
  return (env: Record<string, number>): number => {
    const val = evalAstNode(ast, env);
    if (!Number.isFinite(val)) {
      throw new Error("Resultado numérico não finito (NaN/Infinity).");
    }
    return val;
  };
}

export function evaluateMathExpression(
  expression: string,
  env: Record<string, number>,
): number {
  return compileMathExpression(expression)(env);
}

function formatPoint(point: Record<string, number>): string {
  const entries = Object.entries(point);
  if (entries.length === 0) return "{}";
  return `(${entries.map(([k, v]) => `${k}=${Number(v.toFixed(4))}`).join(", ")})`;
}

function formatCompactNumber(val: number): string {
  if (!Number.isFinite(val)) return String(val);
  return Number(val.toFixed(6)).toString();
}

function buildAxisSamples(min: number, max: number, count: number): number[] {
  if (min === max || count <= 1) {
    return [min];
  }
  const pts: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const t = i / (count - 1);
    pts.push(min + (max - min) * t);
  }
  return pts;
}

export function validateConvexMembershipFunctions(
  premises: TsPremiseDomain[],
  functions: TsWeightFunctionDef[],
  gridSamplesPerAxis?: number,
): TsConvexityValidationResult {
  if (functions.length === 0) {
    return {
      valid: false,
      message: "Defina ao menos uma função de ponderação h_i(z).",
      minWeight: Number.NaN,
      maxSumError: Number.NaN,
    };
  }

  const seenNames = new Set<string>();
  const normalizedPremises: TsPremiseDomain[] = [];
  for (const p of premises) {
    const name = p.name.trim();
    if (!name) {
      return {
        valid: false,
        message: "Todas as variáveis de premissa devem possuir um nome válido.",
        minWeight: Number.NaN,
        maxSumError: Number.NaN,
      };
    }
    if (seenNames.has(name)) {
      return {
        valid: false,
        message: `Variável de premissa duplicada: '${name}'.`,
        minWeight: Number.NaN,
        maxSumError: Number.NaN,
      };
    }
    seenNames.add(name);
    if (!Number.isFinite(p.min) || !Number.isFinite(p.max)) {
      return {
        valid: false,
        message: `Domínio inválido para '${name}': z_min e z_max devem ser finitos.`,
        minWeight: Number.NaN,
        maxSumError: Number.NaN,
      };
    }
    if (p.min > p.max) {
      return {
        valid: false,
        message: `Domínio inválido para '${name}': z_min (${p.min}) > z_max (${p.max}).`,
        minWeight: Number.NaN,
        maxSumError: Number.NaN,
      };
    }
    normalizedPremises.push({ name, min: p.min, max: p.max });
  }

  const compiled: Array<{ label: string; evalFn: (env: Record<string, number>) => number }> = [];
  for (const fn of functions) {
    const label = fn.label.trim() || "h_i";
    try {
      compiled.push({ label, evalFn: compileMathExpression(fn.expression) });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        valid: false,
        message: `Erro de sintaxe em ${label}: ${msg}`,
        minWeight: Number.NaN,
        maxSumError: Number.NaN,
      };
    }
  }

  const maxTotalPoints = 125;
  const dim = normalizedPremises.length;
  let samplesPerAxis = 1;
  if (dim > 0 && dim <= 2) {
    samplesPerAxis = Math.max(2, Math.floor(gridSamplesPerAxis ?? 11));
  } else if (dim >= 3) {
    const bounded = Math.max(2, Math.floor(Math.pow(maxTotalPoints, 1 / dim)));
    const requested =
      gridSamplesPerAxis !== undefined ? Math.max(2, Math.floor(gridSamplesPerAxis)) : bounded;
    samplesPerAxis = Math.min(requested, bounded);
  }

  const axisGrids = normalizedPremises.map((p) =>
    buildAxisSamples(p.min, p.max, samplesPerAxis),
  );

  // Build deterministic Cartesian product capped at 125 points when dim >= 3
  const points: Record<string, number>[] = [];
  if (dim === 0) {
    points.push({});
  } else {
    const current: Record<string, number> = {};
    const cap = dim >= 3 ? maxTotalPoints : Number.POSITIVE_INFINITY;
    const visit = (axisIdx: number): void => {
      if (points.length >= cap) return;
      if (axisIdx === dim) {
        points.push({ ...current });
        return;
      }
      const pName = normalizedPremises[axisIdx].name;
      for (const val of axisGrids[axisIdx]) {
        current[pName] = val;
        visit(axisIdx + 1);
        if (points.length >= cap) return;
      }
    };
    visit(0);
  }

  let minWeight = Number.POSITIVE_INFINITY;
  let maxSumError = 0;
  let firstNegViolation: { label: string; value: number; point: Record<string, number> } | null =
    null;
  let firstSumViolation: { sum: number; point: Record<string, number> } | null = null;

  for (const pt of points) {
    let sum = 0;
    for (const fn of compiled) {
      let val: number;
      try {
        val = fn.evalFn(pt);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          valid: false,
          message: `Erro ao avaliar ${fn.label} em ${formatPoint(pt)}: ${msg}`,
          minWeight: Number.isFinite(minWeight) ? minWeight : Number.NaN,
          maxSumError,
          counterexample: { ...pt },
        };
      }
      if (val < minWeight) minWeight = val;
      if (val < -1e-9 && !firstNegViolation) {
        firstNegViolation = { label: fn.label, value: val, point: { ...pt } };
      }
      sum += val;
    }
    const sumErr = Math.abs(sum - 1);
    if (sumErr > maxSumError) maxSumError = sumErr;
    if (sumErr > 1e-6 && !firstSumViolation) {
      firstSumViolation = { sum, point: { ...pt } };
    }
  }

  if (firstNegViolation) {
    return {
      valid: false,
      message: `Peso negativo em ${firstNegViolation.label} = ${formatCompactNumber(firstNegViolation.value)} < 0 no ponto ${formatPoint(firstNegViolation.point)}.`,
      minWeight,
      maxSumError,
      counterexample: firstNegViolation.point,
    };
  }

  if (firstSumViolation) {
    return {
      valid: false,
      message: `Soma não convexa: ∑h_i(z) = ${formatCompactNumber(firstSumViolation.sum)} ≠ 1 no ponto ${formatPoint(firstSumViolation.point)}.`,
      minWeight,
      maxSumError,
      counterexample: firstSumViolation.point,
    };
  }

  return {
    valid: true,
    message: "Soma convexa válida em Ω: h_i(z) ≥ 0 e ∑h_i(z) = 1",
    minWeight,
    maxSumError,
  };
}
