/**
 * Motor simbólico determinístico em TypeScript para expressões LPV/qLPV da Aba 6
 * (`CL-TS-MOD-DIR-001` Seções 3.1, 3.4, 4.1, 5.2, 6.1 e `R-21`).
 *
 * Regras inegociáveis de segurança e compatibilidade:
 * - Proibição absoluta de avaliação dinâmica de código (`R-21`).
 * - Parser recursivo descendente puro sobre AST tipada (`erasableSyntaxOnly` + `verbatimModuleSyntax`).
 * - Suporta `+`, `-`, `*`, `/`, `^`, `**`, constantes `pi` e `e`, funções elementares e
 *   as primitivas suaves `sinc_rad(u)` e `cos1m_div_u(u)` (expansão de Taylor perto de 0).
 */

export type QlpvAstNode =
  | { readonly kind: "number"; readonly value: number; readonly raw: string }
  | { readonly kind: "const"; readonly name: "pi" | "e"; readonly value: number }
  | { readonly kind: "var"; readonly name: string }
  | { readonly kind: "unary"; readonly op: "+" | "-"; readonly operand: QlpvAstNode }
  | {
      readonly kind: "binary";
      readonly op: "+" | "-" | "*" | "/" | "^";
      readonly left: QlpvAstNode;
      readonly right: QlpvAstNode;
    }
  | { readonly kind: "call"; readonly func: string; readonly arg: QlpvAstNode };

interface Token {
  readonly kind: "number" | "ident" | "op" | "lparen" | "rparen" | "eof";
  readonly text: string;
  readonly pos: number;
}

export const SUPPORTED_QLPV_FUNCTIONS: ReadonlySet<string> = new Set([
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
]);

const RESERVED_CONSTANTS: Readonly<Record<string, "pi" | "e">> = {
  pi: "pi",
  e: "e",
};

/** Avalia `sin(u)/u` com expansão suave de Taylor C^infinito em |u| < 1e-4. */
export function sincRad(u: number): number {
  if (Math.abs(u) < 1e-4) {
    const u2 = u * u;
    return 1.0 - u2 / 6.0 + (u2 * u2) / 120.0;
  }
  return Math.sin(u) / u;
}

/** Avalia `(1 - cos(u))/u` com expansão suave de Taylor em |u| < 1e-4. */
export function cos1mDivU(u: number): number {
  if (Math.abs(u) < 1e-4) {
    const u2 = u * u;
    return u * (0.5 - u2 / 24.0 + (u2 * u2) / 720.0);
  }
  return (1.0 - Math.cos(u)) / u;
}

function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const n = source.length;
  while (i < n) {
    const ch = source[i];
    if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r") {
      i += 1;
      continue;
    }
    if (ch === "(") {
      tokens.push({ kind: "lparen", text: "(", pos: i });
      i += 1;
      continue;
    }
    if (ch === ")") {
      tokens.push({ kind: "rparen", text: ")", pos: i });
      i += 1;
      continue;
    }
    if (ch === "*" && source[i + 1] === "*") {
      tokens.push({ kind: "op", text: "^", pos: i });
      i += 2;
      continue;
    }
    if (ch === "+" || ch === "-" || ch === "*" || ch === "/" || ch === "^") {
      tokens.push({ kind: "op", text: ch, pos: i });
      i += 1;
      continue;
    }
    const rest = source.slice(i);
    const numMatch = /^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/.exec(rest);
    if (numMatch) {
      tokens.push({ kind: "number", text: numMatch[0], pos: i });
      i += numMatch[0].length;
      continue;
    }
    const idMatch = /^[A-Za-z_][A-Za-z0-9_]*/.exec(rest);
    if (idMatch) {
      const ident = idMatch[0];
      if (ident.startsWith("__") || source[i + ident.length] === ".") {
        throw new Error(`Identificador ou acesso a atributo não permitido: '${ident}'.`);
      }
      tokens.push({ kind: "ident", text: ident, pos: i });
      i += ident.length;
      continue;
    }
    throw new Error(`Caractere inválido '${ch}' na posição ${i + 1}.`);
  }
  tokens.push({ kind: "eof", text: "", pos: n });
  return tokens;
}

class QlpvParser {
  private readonly tokens: Token[];
  private idx = 0;

  constructor(tokens: Token[]) {
    this.tokens = tokens;
  }

  private peek(): Token {
    return this.tokens[this.idx] ?? { kind: "eof", text: "", pos: 0 };
  }

  private consume(): Token {
    const tok = this.peek();
    this.idx += 1;
    return tok;
  }

  public parseRoot(): QlpvAstNode {
    const node = this.parseAddSub();
    const trailing = this.peek();
    if (trailing.kind !== "eof") {
      throw new Error(`Token inesperado '${trailing.text}' na posição ${trailing.pos + 1}.`);
    }
    return node;
  }

  private parseAddSub(): QlpvAstNode {
    let left = this.parseMulDiv();
    while (this.peek().kind === "op" && (this.peek().text === "+" || this.peek().text === "-")) {
      const op = this.consume().text as "+" | "-";
      const right = this.parseMulDiv();
      left = { kind: "binary", op, left, right };
    }
    return left;
  }

  private parseMulDiv(): QlpvAstNode {
    let left = this.parseUnary();
    while (this.peek().kind === "op" && (this.peek().text === "*" || this.peek().text === "/")) {
      const op = this.consume().text as "*" | "/";
      const right = this.parseUnary();
      left = { kind: "binary", op, left, right };
    }
    return left;
  }

  private parseUnary(): QlpvAstNode {
    if (this.peek().kind === "op" && (this.peek().text === "+" || this.peek().text === "-")) {
      const op = this.consume().text as "+" | "-";
      const operand = this.parseUnary();
      if (op === "+") return operand;
      return { kind: "unary", op: "-", operand };
    }
    return this.parsePower();
  }

  private parsePower(): QlpvAstNode {
    const base = this.parsePrimary();
    if (this.peek().kind === "op" && this.peek().text === "^") {
      this.consume();
      const exp = this.parseUnary();
      return { kind: "binary", op: "^", left: base, right: exp };
    }
    return base;
  }

  private parsePrimary(): QlpvAstNode {
    const tok = this.peek();
    if (tok.kind === "number") {
      this.consume();
      const val = Number(tok.text);
      if (!Number.isFinite(val)) {
        throw new Error(`Número não finito '${tok.text}'.`);
      }
      return { kind: "number", value: val, raw: tok.text };
    }
    if (tok.kind === "ident") {
      this.consume();
      if (this.peek().kind === "lparen") {
        this.consume();
        if (!SUPPORTED_QLPV_FUNCTIONS.has(tok.text)) {
          throw new Error(
            `Função '${tok.text}' não suportada. Use sin, cos, tan, exp, log, sqrt, abs, tanh, sinc_rad ou cos1m_div_u.`,
          );
        }
        if (this.peek().kind === "rparen") {
          throw new Error(`Função '${tok.text}()' requer exatamente 1 argumento.`);
        }
        const arg = this.parseAddSub();
        if (this.peek().kind !== "rparen") {
          throw new Error(`Esperado ')' após argumento de '${tok.text}(...)'.`);
        }
        this.consume();
        return { kind: "call", func: tok.text, arg };
      }
      if (Object.hasOwn(RESERVED_CONSTANTS, tok.text)) {
        const cname = RESERVED_CONSTANTS[tok.text];
        return { kind: "const", name: cname, value: cname === "pi" ? Math.PI : Math.E };
      }
      return { kind: "var", name: tok.text };
    }
    if (tok.kind === "lparen") {
      this.consume();
      const inner = this.parseAddSub();
      if (this.peek().kind !== "rparen") {
        throw new Error(`Parêntese '(' na posição ${tok.pos + 1} não foi fechado.`);
      }
      this.consume();
      return inner;
    }
    throw new Error(
      tok.kind === "eof"
        ? "Expressão vazia ou incompleta."
        : `Token inesperado '${tok.text}' na posição ${tok.pos + 1}.`,
    );
  }
}

function astEquals(a: QlpvAstNode, b: QlpvAstNode): boolean {
  if (a.kind !== b.kind) return false;
  switch (a.kind) {
    case "number":
      return b.kind === "number" && a.value === b.value;
    case "const":
      return b.kind === "const" && a.name === b.name;
    case "var":
      return b.kind === "var" && a.name === b.name;
    case "unary":
      return b.kind === "unary" && a.op === b.op && astEquals(a.operand, b.operand);
    case "binary":
      return (
        b.kind === "binary" &&
        a.op === b.op &&
        astEquals(a.left, b.left) &&
        astEquals(a.right, b.right)
      );
    case "call":
      return b.kind === "call" && a.func === b.func && astEquals(a.arg, b.arg);
  }
}

function rewriteSinOverArg(node: QlpvAstNode): { node: QlpvAstNode; rewritten: boolean } {
  if (node.kind === "binary" && node.op === "/") {
    const leftRw = rewriteSinOverArg(node.left);
    const rightRw = rewriteSinOverArg(node.right);
    if (
      leftRw.node.kind === "call" &&
      leftRw.node.func === "sin" &&
      astEquals(leftRw.node.arg, rightRw.node)
    ) {
      return {
        node: { kind: "call", func: "sinc_rad", arg: leftRw.node.arg },
        rewritten: true,
      };
    }
    if (leftRw.node.kind === "binary" && leftRw.node.op === "*") {
      if (
        leftRw.node.right.kind === "call" &&
        leftRw.node.right.func === "sin" &&
        astEquals(leftRw.node.right.arg, rightRw.node)
      ) {
        return {
          node: {
            kind: "binary",
            op: "*",
            left: leftRw.node.left,
            right: { kind: "call", func: "sinc_rad", arg: leftRw.node.right.arg },
          },
          rewritten: true,
        };
      }
      if (
        leftRw.node.left.kind === "call" &&
        leftRw.node.left.func === "sin" &&
        astEquals(leftRw.node.left.arg, rightRw.node)
      ) {
        return {
          node: {
            kind: "binary",
            op: "*",
            left: { kind: "call", func: "sinc_rad", arg: leftRw.node.left.arg },
            right: leftRw.node.right,
          },
          rewritten: true,
        };
      }
    }
    return {
      node: { kind: "binary", op: "/", left: leftRw.node, right: rightRw.node },
      rewritten: leftRw.rewritten || rightRw.rewritten,
    };
  }
  if (node.kind === "unary") {
    const sub = rewriteSinOverArg(node.operand);
    return { node: { kind: "unary", op: node.op, operand: sub.node }, rewritten: sub.rewritten };
  }
  if (node.kind === "binary") {
    const l = rewriteSinOverArg(node.left);
    const r = rewriteSinOverArg(node.right);
    return {
      node: { kind: "binary", op: node.op, left: l.node, right: r.node },
      rewritten: l.rewritten || r.rewritten,
    };
  }
  if (node.kind === "call") {
    const sub = rewriteSinOverArg(node.arg);
    return { node: { kind: "call", func: node.func, arg: sub.node }, rewritten: sub.rewritten };
  }
  return { node, rewritten: false };
}

function precedence(node: QlpvAstNode): number {
  if (node.kind === "binary") {
    if (node.op === "+" || node.op === "-") return 1;
    if (node.op === "*" || node.op === "/") return 2;
    if (node.op === "^") return 4;
  }
  if (node.kind === "unary") return 3;
  return 5;
}

/** Serializa uma AST de volta para string matemática legível e corretamente parentizada. */
export function serializeQlpvAst(node: QlpvAstNode): string {
  switch (node.kind) {
    case "number":
      return node.raw;
    case "const":
      return node.name;
    case "var":
      return node.name;
    case "unary": {
      const inner = serializeQlpvAst(node.operand);
      return precedence(node.operand) < precedence(node) ? `${node.op}(${inner})` : `${node.op}${inner}`;
    }
    case "call":
      return `${node.func}(${serializeQlpvAst(node.arg)})`;
    case "binary": {
      const p = precedence(node);
      const lStr = serializeQlpvAst(node.left);
      const rStr = serializeQlpvAst(node.right);
      const leftWrapped =
        precedence(node.left) < p || (node.op === "^" && node.left.kind === "unary")
          ? `(${lStr})`
          : lStr;
      const rightNeedsWrap =
        precedence(node.right) < p ||
        ((node.op === "-" || node.op === "/") && precedence(node.right) === p);
      const rightWrapped = rightNeedsWrap ? `(${rStr})` : rStr;
      return node.op === "^"
        ? `${leftWrapped}^${rightWrapped}`
        : `${leftWrapped} ${node.op} ${rightWrapped}`;
    }
  }
}

export function collectAstVariables(node: QlpvAstNode, out?: string[]): string[] {
  const acc = out ?? [];
  switch (node.kind) {
    case "var":
      if (!acc.includes(node.name)) acc.push(node.name);
      break;
    case "unary":
      collectAstVariables(node.operand, acc);
      break;
    case "binary":
      collectAstVariables(node.left, acc);
      collectAstVariables(node.right, acc);
      break;
    case "call":
      collectAstVariables(node.arg, acc);
      break;
    default:
      break;
  }
  return acc;
}

/** Substitui variáveis na AST preservando precedência algébrica exata (sem regex frágil). */
export function substituteAstVariables(
  node: QlpvAstNode,
  substitutions: Readonly<Record<string, QlpvAstNode>>,
): QlpvAstNode {
  switch (node.kind) {
    case "var":
      return Object.hasOwn(substitutions, node.name) ? substitutions[node.name] : node;
    case "unary":
      return {
        kind: "unary",
        op: node.op,
        operand: substituteAstVariables(node.operand, substitutions),
      };
    case "binary":
      return {
        kind: "binary",
        op: node.op,
        left: substituteAstVariables(node.left, substitutions),
        right: substituteAstVariables(node.right, substitutions),
      };
    case "call":
      return {
        kind: "call",
        func: node.func,
        arg: substituteAstVariables(node.arg, substitutions),
      };
    default:
      return node;
  }
}

/** Avalia numericamente uma AST sobre um dicionário de variáveis escalares. */
export function evalQlpvAst(node: QlpvAstNode, env: Readonly<Record<string, number>>): number {
  switch (node.kind) {
    case "number":
    case "const":
      return node.value;
    case "var": {
      const val = env[node.name];
      if (typeof val !== "number" || !Number.isFinite(val)) {
        throw new Error(`Variável '${node.name}' sem valor finito definido.`);
      }
      return val;
    }
    case "unary": {
      const v = evalQlpvAst(node.operand, env);
      return node.op === "-" ? -v : v;
    }
    case "binary": {
      const l = evalQlpvAst(node.left, env);
      const r = evalQlpvAst(node.right, env);
      switch (node.op) {
        case "+":
          return l + r;
        case "-":
          return l - r;
        case "*":
          return l * r;
        case "/":
          return l / r;
        case "^":
          return Math.pow(l, r);
      }
    }
    case "call": {
      const u = evalQlpvAst(node.arg, env);
      switch (node.func) {
        case "sin":
          return Math.sin(u);
        case "cos":
          return Math.cos(u);
        case "tan":
          return Math.tan(u);
        case "asin":
          return Math.asin(u);
        case "acos":
          return Math.acos(u);
        case "atan":
          return Math.atan(u);
        case "sinh":
          return Math.sinh(u);
        case "cosh":
          return Math.cosh(u);
        case "tanh":
          return Math.tanh(u);
        case "exp":
          return Math.exp(u);
        case "log":
          return Math.log(u);
        case "sqrt":
          return Math.sqrt(u);
        case "abs":
          return Math.abs(u);
        case "sign":
          return Math.sign(u);
        case "sinc_rad":
          return sincRad(u);
        case "cos1m_div_u":
          return cos1mDivU(u);
        default:
          throw new Error(`Função desconhecida: ${node.func}`);
      }
    }
  }
}

export interface ParsedQlpvExpression {
  readonly ok: boolean;
  readonly source: string;
  readonly ast: QlpvAstNode | null;
  readonly activeVariables: string[];
  readonly hasSinOverArg: boolean;
  readonly suggestedSincSource: string | null;
  readonly error: string | null;
}

export function parseQlpvExpr(rawSource: string | number): ParsedQlpvExpression {
  const source = String(rawSource).trim();
  if (source.length === 0) {
    return {
      ok: false,
      source,
      ast: null,
      activeVariables: [],
      hasSinOverArg: false,
      suggestedSincSource: null,
      error: "Expressão vazia (use '0' para entradas nulas).",
    };
  }
  try {
    const ast = new QlpvParser(tokenize(source)).parseRoot();
    const vars = collectAstVariables(ast);
    const rw = rewriteSinOverArg(ast);
    return {
      ok: true,
      source,
      ast,
      activeVariables: vars,
      hasSinOverArg: rw.rewritten,
      suggestedSincSource: rw.rewritten ? serializeQlpvAst(rw.node) : null,
      error: null,
    };
  } catch (err: unknown) {
    return {
      ok: false,
      source,
      ast: null,
      activeVariables: [],
      hasSinOverArg: false,
      suggestedSincSource: null,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

export interface SectorCellDiagnostic {
  readonly matrixName: string;
  readonly row: number;
  readonly col: number;
  readonly kind: "syntax" | "undeclared_var" | "direct_state_or_ext" | "nonlinear_in_premise";
  readonly message: string;
}

/**
 * Audita estruturalmente as matrizes S(z) da Via 1 (Seção 3.1):
 * 1. Sintaxe válida;
 * 2. Isolamento: apenas constantes e {z_1, ..., z_nn} (sem x_i ou w_ext residuais);
 * 3. Afinidade / multilinearidade por coordenada z_k.
 */
export function auditSectorMatrices(
  matrices: Readonly<Record<string, ReadonlyArray<ReadonlyArray<string>>>>,
  premiseNames: readonly string[],
  stateAndExtNames: readonly string[],
  premiseBounds?: Readonly<Record<string, readonly [number, number]>>,
): SectorCellDiagnostic[] {
  const diagnostics: SectorCellDiagnostic[] = [];
  const premiseSet = new Set(premiseNames);
  const stateExtSet = new Set(stateAndExtNames);

  for (const [mName, rows] of Object.entries(matrices)) {
    for (let r = 0; r < rows.length; r += 1) {
      const row = rows[r] ?? [];
      for (let c = 0; c < row.length; c += 1) {
        const parsed = parseQlpvExpr(row[c] ?? "");
        if (!parsed.ok || !parsed.ast) {
          diagnostics.push({
            matrixName: mName,
            row: r,
            col: c,
            kind: "syntax",
            message: `${mName}(${r + 1},${c + 1}): ${parsed.error ?? "erro de sintaxe"}`,
          });
          continue;
        }
        for (const v of parsed.activeVariables) {
          if (!premiseSet.has(v)) {
            if (stateExtSet.has(v)) {
              diagnostics.push({
                matrixName: mName,
                row: r,
                col: c,
                kind: "direct_state_or_ext",
                message: `${mName}(${r + 1},${c + 1}) referencia '${v}' diretamente. Na Via 1 (Setor), absorva '${v}' em uma variável premissa z_k = g_k(...) ou use as Vias 2/3 (TPMT/FEMT).`,
              });
            } else {
              diagnostics.push({
                matrixName: mName,
                row: r,
                col: c,
                kind: "undeclared_var",
                message: `${mName}(${r + 1},${c + 1}) usa identificador não declarado '${v}'.`,
              });
            }
          }
        }
        if (
          diagnostics.some((d) => d.matrixName === mName && d.row === r && d.col === c) ||
          parsed.activeVariables.length === 0
        ) {
          continue;
        }
        // Teste determinístico de colinearidade em cada z_k ativo na célula
        const baseEnv: Record<string, number> = {};
        for (let idx = 0; idx < premiseNames.length; idx += 1) {
          const pn = premiseNames[idx];
          const b = premiseBounds?.[pn];
          baseEnv[pn] = b ? 0.37 * b[0] + 0.63 * b[1] : 0.35 + 0.17 * idx;
        }
        for (const zk of parsed.activeVariables) {
          const b = premiseBounds?.[zk] ?? [-0.8, 1.2];
          const zLo = b[0];
          const zHi = b[1] > b[0] + 1e-9 ? b[1] : b[0] + 1.0;
          const zMid = 0.5 * (zLo + zHi);
          const fLo = evalQlpvAst(parsed.ast, { ...baseEnv, [zk]: zLo });
          const fHi = evalQlpvAst(parsed.ast, { ...baseEnv, [zk]: zHi });
          const fMid = evalQlpvAst(parsed.ast, { ...baseEnv, [zk]: zMid });
          if (!Number.isFinite(fLo) || !Number.isFinite(fHi) || !Number.isFinite(fMid)) {
            diagnostics.push({
              matrixName: mName,
              row: r,
              col: c,
              kind: "nonlinear_in_premise",
              message: `${mName}(${r + 1},${c + 1}) gera valor não finito sobre o intervalo de '${zk}'.`,
            });
            break;
          }
          const scale = 1.0 + Math.abs(fLo) + Math.abs(fHi) + Math.abs(fMid);
          if (Math.abs(fMid - 0.5 * (fLo + fHi)) > 1e-10 * scale) {
            diagnostics.push({
              matrixName: mName,
              row: r,
              col: c,
              kind: "nonlinear_in_premise",
              message: `${mName}(${r + 1},${c + 1}) depende de forma não-afim de '${zk}' (ex.: potência, divisão ou função trigonométrica de ${zk}). Mova a não-linearidade para a definição de ${zk}.`,
            });
            break;
          }
        }
      }
    }
  }
  return diagnostics;
}

export interface DirectMatricesInspection {
  readonly activeVariables: string[];
  readonly linearOnlyStates: string[];
  readonly errors: string[];
}

/**
 * Inspeciona matrizes diretas S(x, w_ext) das Vias 2 (TPMT) e 3 (FEMT),
 * extraindo na ordem canônica as variáveis não-lineares ativas p = (p_1, ..., p_D).
 */
export function inspectDirectQlpvMatrices(
  matrices: Readonly<Record<string, ReadonlyArray<ReadonlyArray<string>>>>,
  stateNames: readonly string[],
  externalNames: readonly string[],
): DirectMatricesInspection {
  const allowedOrder = [...stateNames, ...externalNames];
  const allowedSet = new Set(allowedOrder);
  const foundSet = new Set<string>();
  const errors: string[] = [];

  for (const [mName, rows] of Object.entries(matrices)) {
    for (let r = 0; r < rows.length; r += 1) {
      const row = rows[r] ?? [];
      for (let c = 0; c < row.length; c += 1) {
        const parsed = parseQlpvExpr(row[c] ?? "");
        if (!parsed.ok) {
          errors.push(`${mName}(${r + 1},${c + 1}): ${parsed.error ?? "erro de sintaxe"}`);
          continue;
        }
        for (const v of parsed.activeVariables) {
          if (!allowedSet.has(v)) {
            errors.push(
              `${mName}(${r + 1},${c + 1}): variável '${v}' não declarada nos estados ou sinais externos.`,
            );
          } else {
            foundSet.add(v);
          }
        }
      }
    }
  }

  const activeVariables = allowedOrder.filter((v) => foundSet.has(v));
  const linearOnlyStates = stateNames.filter((s) => !foundSet.has(s));
  return { activeVariables, linearOnlyStates, errors };
}

/** Converte matrizes S(z) em S(x, w_ext) substituindo cada z_k por sua AST g_k(x, w_ext). */
export function expandSectorMatrixToDirect(
  matrix: ReadonlyArray<ReadonlyArray<string>>,
  premises: ReadonlyArray<{ readonly name: string; readonly expression: string }>,
): string[][] {
  const subs: Record<string, QlpvAstNode> = {};
  for (const p of premises) {
    const parsed = parseQlpvExpr(p.expression);
    if (parsed.ok && parsed.ast) {
      subs[p.name] = parsed.ast;
    }
  }
  return matrix.map((row) =>
    row.map((cell) => {
      const parsed = parseQlpvExpr(cell);
      if (!parsed.ok || !parsed.ast) return cell;
      return serializeQlpvAst(substituteAstVariables(parsed.ast, subs));
    }),
  );
}
