/**
 * Avaliador Matricial e Escalar Puro para Diretivas `recover` da DSL LMI (Tab 6 — F8).
 *
 * Segurança & Regras:
 * - 100% TypeScript puro, zero execução dinâmica de código.
 * - Compatível com `erasableSyntaxOnly` e `verbatimModuleSyntax`.
 * - Avalia todas as diretivas `recover` em ordem de declaração, disponibilizando
 *   variáveis recém-recuperadas para expressões `recover` subsequentes (ex.: `recover P = inv(Q)`
 *   seguido de `recover alpha_eff = trace(P) / 2`).
 */

import type {
  LmiDslParseResult,
  LmiDslQuantifier,
} from "./lmi_dsl_parser.ts";
import type {
  LmiCompileContext,
  LmiVertexMatrices,
} from "./lmi_dsl_compiler.ts";

export interface DenseMatrixValue {
  rows: number;
  cols: number;
  data: number[];
}

export interface EvaluatedRecoveryEntry {
  label: string;
  formula: string;
  ok: boolean;
  value?: DenseMatrixValue;
  isScalar?: boolean;
  error?: string;
}

export interface RecoverEvalInput {
  parsed: LmiDslParseResult;
  compileCtx?: LmiCompileContext;
  solvedVariables: Record<string, DenseMatrixValue>;
}

interface EvalValue {
  rows: number;
  cols: number;
  data: number[];
  isScalar?: boolean;
  isZeroLiteral?: boolean;
  scalableIdentity?: number;
}

interface RecToken {
  type:
    | "num"
    | "id"
    | "op"
    | "lparen"
    | "rparen"
    | "lbracket"
    | "rbracket"
    | "comma"
    | "quote"
    | "dotT";
  val: string;
  pos: number;
}

function tokenizeRecoverExpr(expr: string): RecToken[] {
  const tokens: RecToken[] = [];
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
    if (ch === "[") {
      tokens.push({ type: "lbracket", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === "]") {
      tokens.push({ type: "rbracket", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === ",") {
      tokens.push({ type: "comma", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === "'") {
      tokens.push({ type: "quote", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === "+" || ch === "-" || ch === "*" || ch === "@" || ch === "/") {
      tokens.push({ type: "op", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (expr.slice(i, i + 2) === ".T" && (i + 2 >= len || !/[A-Za-z0-9_]/.test(expr[i + 2]))) {
      tokens.push({ type: "dotT", val: ".T", pos: i });
      i += 2;
      continue;
    }
    const numMatch = /^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(expr.slice(i));
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
    throw new Error(`Caractere inesperado '${ch}' na posição ${i} da expressão '${expr}'.`);
  }
  return tokens;
}

function makeScalarVal(v: number, isZeroLiteral = false): EvalValue {
  if (!Number.isFinite(v)) {
    throw new Error("Valor escalar não finito encontrado durante avaliação de recover.");
  }
  return {
    rows: 1,
    cols: 1,
    data: [v],
    isScalar: true,
    ...(isZeroLiteral ? { isZeroLiteral: true } : {}),
  };
}

function makeIdentityVal(dim: number, coeff = 1): EvalValue {
  if (!Number.isInteger(dim) || dim < 1) {
    throw new Error(`Dimensão inválida para identidade: ${dim}.`);
  }
  const data = new Array<number>(dim * dim).fill(0);
  for (let i = 0; i < dim; i += 1) {
    data[i * dim + i] = coeff;
  }
  return { rows: dim, cols: dim, data };
}

function makeZeroVal(rows: number, cols: number): EvalValue {
  if (!Number.isInteger(rows) || !Number.isInteger(cols) || rows < 1 || cols < 1) {
    throw new Error(`Dimensões inválidas para matriz nula: (${rows}×${cols}).`);
  }
  return { rows, cols, data: new Array<number>(rows * cols).fill(0) };
}

function matrix2DToEvalVal(mat: number[][], label: string): EvalValue {
  const rows = mat.length;
  const cols = mat[0]?.length ?? 0;
  if (rows < 1 || cols < 1) {
    throw new Error(`Matriz '${label}' vazia ou com dimensão inválida.`);
  }
  const data: number[] = [];
  for (let r = 0; r < rows; r += 1) {
    if (mat[r].length !== cols) {
      throw new Error(`Matriz '${label}' possui linhas com tamanhos inconsistentes.`);
    }
    for (let c = 0; c < cols; c += 1) {
      const v = Number(mat[r][c]);
      if (!Number.isFinite(v)) {
        throw new Error(`Matriz '${label}' contém valor não finito em (${r}, ${c}).`);
      }
      data.push(v);
    }
  }
  return { rows, cols, data };
}

function isScalarLike(val: EvalValue): boolean {
  return val.scalableIdentity === undefined && val.rows === 1 && val.cols === 1;
}

function scaleVal(alpha: number, val: EvalValue): EvalValue {
  if (!Number.isFinite(alpha)) {
    throw new Error("Fator escalar não finito em operação matricial.");
  }
  if (val.scalableIdentity !== undefined) {
    return {
      rows: 1,
      cols: 1,
      data: [alpha * val.scalableIdentity],
      scalableIdentity: alpha * val.scalableIdentity,
    };
  }
  return {
    rows: val.rows,
    cols: val.cols,
    data: val.data.map((x) => alpha * x),
    ...(val.isScalar ? { isScalar: true } : {}),
  };
}

function transposeVal(val: EvalValue): EvalValue {
  if (val.scalableIdentity !== undefined) {
    return { ...val, data: [...val.data] };
  }
  const out = new Array<number>(val.rows * val.cols);
  for (let r = 0; r < val.rows; r += 1) {
    for (let c = 0; c < val.cols; c += 1) {
      out[c * val.rows + r] = val.data[r * val.cols + c];
    }
  }
  return {
    rows: val.cols,
    cols: val.rows,
    data: out,
    ...(val.isScalar ? { isScalar: true } : {}),
  };
}

function addVal(aRaw: EvalValue, bRaw: EvalValue, signB: 1 | -1): EvalValue {
  if (aRaw.isZeroLiteral && !bRaw.isZeroLiteral) {
    return signB === 1 ? { ...bRaw, data: [...bRaw.data] } : scaleVal(-1, bRaw);
  }
  if (bRaw.isZeroLiteral && !aRaw.isZeroLiteral) {
    return { ...aRaw, data: [...aRaw.data] };
  }
  if (aRaw.isZeroLiteral && bRaw.isZeroLiteral) {
    return makeScalarVal(0, true);
  }

  let a = aRaw;
  let b = bRaw;
  if (a.scalableIdentity !== undefined && b.scalableIdentity !== undefined) {
    const coeff = a.scalableIdentity + signB * b.scalableIdentity;
    return { rows: 1, cols: 1, data: [coeff], scalableIdentity: coeff };
  }
  if (a.scalableIdentity !== undefined) {
    if (b.rows !== b.cols) {
      throw new Error(`Identidade 'I' não pode ser somada a matriz não quadrada (${b.rows}×${b.cols}).`);
    }
    a = makeIdentityVal(b.rows, a.scalableIdentity);
  } else if (b.scalableIdentity !== undefined) {
    if (a.rows !== a.cols) {
      throw new Error(`Identidade 'I' não pode ser somada a matriz não quadrada (${a.rows}×${a.cols}).`);
    }
    b = makeIdentityVal(a.rows, b.scalableIdentity);
  }

  if (a.rows !== b.rows || a.cols !== b.cols) {
    throw new Error(
      `Incompatibilidade de dimensões na soma/subtração: (${a.rows}×${a.cols}) vs (${b.rows}×${b.cols}).`,
    );
  }
  const data = new Array<number>(a.data.length);
  for (let i = 0; i < a.data.length; i += 1) {
    data[i] = a.data[i] + signB * b.data[i];
  }
  return {
    rows: a.rows,
    cols: a.cols,
    data,
    ...(a.isScalar && b.isScalar ? { isScalar: true } : {}),
  };
}

function mulVal(a: EvalValue, b: EvalValue): EvalValue {
  if (a.scalableIdentity !== undefined && b.scalableIdentity !== undefined) {
    const coeff = a.scalableIdentity * b.scalableIdentity;
    return { rows: 1, cols: 1, data: [coeff], scalableIdentity: coeff };
  }
  if (a.scalableIdentity !== undefined) {
    return scaleVal(a.scalableIdentity, b);
  }
  if (b.scalableIdentity !== undefined) {
    return scaleVal(b.scalableIdentity, a);
  }

  if (isScalarLike(a) && !isScalarLike(b)) {
    return scaleVal(a.data[0], b);
  }
  if (!isScalarLike(a) && isScalarLike(b)) {
    return scaleVal(b.data[0], a);
  }
  if (isScalarLike(a) && isScalarLike(b)) {
    return makeScalarVal(a.data[0] * b.data[0]);
  }

  if (a.cols !== b.rows) {
    throw new Error(
      `Incompatibilidade de dimensões no produto matricial: (${a.rows}×${a.cols}) * (${b.rows}×${b.cols}).`,
    );
  }
  const M = a.rows;
  const K = a.cols;
  const N = b.cols;
  const out = new Array<number>(M * N).fill(0);
  for (let r = 0; r < M; r += 1) {
    for (let p = 0; p < K; p += 1) {
      const lv = a.data[r * K + p];
      if (lv === 0) continue;
      for (let c = 0; c < N; c += 1) {
        out[r * N + c] += lv * b.data[p * N + c];
      }
    }
  }
  return { rows: M, cols: N, data: out };
}

export function invertDenseMatrix(mat: DenseMatrixValue): DenseMatrixValue {
  const n = mat.rows;
  if (n !== mat.cols) {
    throw new Error(`inv(M) requer matriz quadrada, recebido (${mat.rows}×${mat.cols}).`);
  }
  if (n < 1 || n > 32) {
    throw new Error(`inv(M) suporta matrizes quadradas de 1×1 até 32×32 (recebido ${n}×${n}).`);
  }
  if (n === 1) {
    const v = mat.data[0];
    if (!Number.isFinite(v) || Math.abs(v) <= 1e-13) {
      throw new Error("Matriz/escalar singular em inv(...) — pivô nulo.");
    }
    return { rows: 1, cols: 1, data: [1 / v] };
  }

  const aug: number[][] = Array.from({ length: n }, (_, i) => {
    const row: number[] = [];
    for (let j = 0; j < n; j += 1) row.push(mat.data[i * n + j]);
    for (let j = 0; j < n; j += 1) row.push(i === j ? 1 : 0);
    return row;
  });

  for (let col = 0; col < n; col += 1) {
    let pivotRow = col;
    let maxAbs = Math.abs(aug[col][col]);
    for (let r = col + 1; r < n; r += 1) {
      const cand = Math.abs(aug[r][col]);
      if (cand > maxAbs) {
        maxAbs = cand;
        pivotRow = r;
      }
    }
    if (!Number.isFinite(maxAbs) || maxAbs <= 1e-13) {
      throw new Error(`Matriz singular ou mal-condicionada em inv(...) (pivô ${maxAbs.toExponential(2)} na coluna ${col + 1}).`);
    }
    if (pivotRow !== col) {
      const tmp = aug[col];
      aug[col] = aug[pivotRow];
      aug[pivotRow] = tmp;
    }
    const pivot = aug[col][col];
    for (let j = 0; j < 2 * n; j += 1) aug[col][j] /= pivot;
    for (let r = 0; r < n; r += 1) {
      if (r === col) continue;
      const factor = aug[r][col];
      if (factor === 0) continue;
      for (let j = 0; j < 2 * n; j += 1) {
        aug[r][j] -= factor * aug[col][j];
      }
    }
  }

  const invData: number[] = [];
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < n; j += 1) {
      const v = aug[i][n + j];
      if (!Number.isFinite(v)) {
        throw new Error("Resultado não finito ao inverter matriz em inv(...).");
      }
      invData.push(v);
    }
  }
  return { rows: n, cols: n, data: invData };
}

class RecoverExprEvaluator {
  private readonly tokens: RecToken[];
  private pos = 0;
  private readonly binding: Record<string, number>;
  private readonly varMap: ReadonlyMap<string, DenseMatrixValue>;
  private readonly paramMap: ReadonlyMap<string, number>;
  private readonly compileCtx?: LmiCompileContext;
  private readonly nVerts: number;

  constructor(
    expr: string,
    binding: Record<string, number>,
    varMap: ReadonlyMap<string, DenseMatrixValue>,
    paramMap: ReadonlyMap<string, number>,
    compileCtx: LmiCompileContext | undefined,
    nVerts: number,
  ) {
    this.tokens = tokenizeRecoverExpr(expr);
    this.binding = binding;
    this.varMap = varMap;
    this.paramMap = paramMap;
    this.compileCtx = compileCtx;
    this.nVerts = nVerts;
  }

  private peek(offset = 0): RecToken | undefined {
    return this.tokens[this.pos + offset];
  }

  private consume(): RecToken {
    const t = this.tokens[this.pos];
    if (!t) throw new Error("Fim inesperado da expressão de recuperação.");
    this.pos += 1;
    return t;
  }

  private expect(type: RecToken["type"], msg: string): RecToken {
    const t = this.peek();
    if (!t || t.type !== type) {
      throw new Error(`${msg} (encontrado '${t?.val ?? "EOF"}').`);
    }
    this.pos += 1;
    return t;
  }

  public evaluate(): EvalValue {
    const res = this.parseAddExpr();
    if (this.pos < this.tokens.length) {
      throw new Error(`Token inesperado '${this.tokens[this.pos].val}' na expressão.`);
    }
    return res;
  }

  private parseAddExpr(): EvalValue {
    let left = this.parseMulExpr();
    while (this.peek()?.type === "op" && (this.peek()?.val === "+" || this.peek()?.val === "-")) {
      const op = this.consume().val as "+" | "-";
      const right = this.parseMulExpr();
      left = addVal(left, right, op === "+" ? 1 : -1);
    }
    return left;
  }

  private parseMulExpr(): EvalValue {
    let left = this.parseUnaryExpr();
    while (
      this.peek()?.type === "op" &&
      (this.peek()?.val === "*" || this.peek()?.val === "@" || this.peek()?.val === "/")
    ) {
      const op = this.consume().val;
      const right = this.parseUnaryExpr();
      if (op === "/") {
        if (!isScalarLike(right)) {
          throw new Error("Divisão '/' na expressão recover requer denominador escalar.");
        }
        const denom = right.data[0];
        if (!Number.isFinite(denom) || Math.abs(denom) <= 1e-15) {
          throw new Error("Divisão por zero na expressão recover.");
        }
        left = scaleVal(1 / denom, left);
      } else {
        left = mulVal(left, right);
      }
    }
    return left;
  }

  private parseUnaryExpr(): EvalValue {
    const t = this.peek();
    if (t?.type === "op" && (t.val === "+" || t.val === "-")) {
      this.consume();
      const inner = this.parseUnaryExpr();
      return t.val === "-" ? scaleVal(-1, inner) : inner;
    }
    return this.parsePostfixExpr();
  }

  private parsePostfixExpr(): EvalValue {
    let val = this.parsePrimary();
    while (this.peek()?.type === "quote" || this.peek()?.type === "dotT") {
      this.consume();
      val = transposeVal(val);
    }
    return val;
  }

  private parsePrimary(): EvalValue {
    const t = this.peek();
    if (!t) throw new Error("Expressão recover incompleta.");

    if (t.type === "num") {
      this.consume();
      const v = Number(t.val);
      return makeScalarVal(v, v === 0);
    }

    if (t.type === "lparen") {
      this.consume();
      const inner = this.parseAddExpr();
      this.expect("rparen", "Esperado ')' para fechar parênteses");
      return inner;
    }

    if (t.type === "id") {
      const id = this.consume().val;

      if (this.peek()?.type === "lparen") {
        return this.parseFunctionCall(id);
      }

      if (this.peek()?.type === "lbracket") {
        this.consume();
        const idxTokens: string[] = [];
        while (this.peek() && this.peek()!.type !== "rbracket") {
          const tok = this.consume();
          if (tok.type === "comma") continue;
          idxTokens.push(tok.val);
        }
        this.expect("rbracket", `Esperado ']' após índice de '${id}'`);
        const resolved = idxTokens.map((tok) => this.resolveIndexToken(tok));
        return this.resolveIndexedSymbol(id, resolved);
      }

      return this.resolvePlainSymbol(id);
    }

    throw new Error(`Token inesperado '${t.val}' na expressão recover.`);
  }

  private resolveIndexToken(tok: string): number {
    if (Object.prototype.hasOwnProperty.call(this.binding, tok)) {
      return this.binding[tok];
    }
    const n = Number(tok);
    if (Number.isInteger(n) && n >= 1) return n;
    throw new Error(`Índice '${tok}' não resolvido na expressão recover.`);
  }

  private resolvePlainSymbol(id: string): EvalValue {
    if (id === "I") {
      return { rows: 1, cols: 1, data: [1], scalableIdentity: 1 };
    }
    if (Object.prototype.hasOwnProperty.call(this.binding, id)) {
      return makeScalarVal(this.binding[id]);
    }
    const v = this.varMap.get(id);
    if (v) {
      return {
        rows: v.rows,
        cols: v.cols,
        data: [...v.data],
        ...(v.rows === 1 && v.cols === 1 ? { isScalar: true } : {}),
      };
    }
    if (this.paramMap.has(id)) {
      return makeScalarVal(this.paramMap.get(id)!);
    }
    const sysMat = this.lookupSystemMatrix(id, undefined);
    if (sysMat) return matrix2DToEvalVal(sysMat, id);

    throw new Error(`Símbolo '${id}' não encontrado na solução ou contexto do sistema.`);
  }

  private resolveIndexedSymbol(id: string, indices: number[]): EvalValue {
    const key = `${id}[${indices.join(",")}]`;
    const v = this.varMap.get(key);
    if (v) {
      return {
        rows: v.rows,
        cols: v.cols,
        data: [...v.data],
        ...(v.rows === 1 && v.cols === 1 ? { isScalar: true } : {}),
      };
    }
    if (indices.length === 1) {
      const sysMat = this.lookupSystemMatrix(id, indices[0]);
      if (sysMat) return matrix2DToEvalVal(sysMat, key);
    }
    throw new Error(`Símbolo indexado '${key}' não encontrado na solução ou contexto do sistema.`);
  }

  private lookupSystemMatrix(id: string, vertexIndex1Based: number | undefined): number[][] | null {
    const ctx = this.compileCtx;
    if (!ctx) return null;

    if (id === "dA" || id === "dC") {
      if (vertexIndex1Based === undefined) return null;
      const deltas = ctx.deltaVertices;
      if (!deltas || deltas.length === 0) {
        if (id === "dC") {
          const p = ctx.C.length;
          const n = ctx.A.length;
          return Array.from({ length: p }, () => Array(n).fill(0));
        }
        return null;
      }
      if (vertexIndex1Based < 1 || vertexIndex1Based > deltas.length) {
        throw new Error(`Índice ${vertexIndex1Based} fora do intervalo 1..${deltas.length} para '${id}'.`);
      }
      const dv = deltas[vertexIndex1Based - 1];
      if (id === "dA") return dv.dA;
      if (dv.dC) return dv.dC;
      const p = ctx.C.length;
      const n = ctx.A.length;
      return Array.from({ length: p }, () => Array(n).fill(0));
    }

    const getFromSource = (
      src: Partial<LmiVertexMatrices> & Partial<Pick<LmiCompileContext, "Q_cost" | "R_cost">>,
      sym: string,
    ): number[][] | undefined => {
      switch (sym) {
        case "A":
          return src.A;
        case "B":
        case "B2":
          return src.B;
        case "C":
          return src.C;
        case "D":
          return src.D;
        case "Bw":
        case "B1":
          return src.Bw;
        case "Dyw":
          return src.Dyw;
        case "Cz":
        case "C1":
          return src.Cz ?? src.C;
        case "Dzu":
        case "D12":
          return src.Dzu;
        case "Dzw":
        case "D11":
          return src.Dzw;
        case "Q_cost":
          return src.Q_cost;
        case "R_cost":
          return src.R_cost;
        default:
          return undefined;
      }
    };

    if (vertexIndex1Based !== undefined) {
      if (vertexIndex1Based < 1 || vertexIndex1Based > this.nVerts) {
        throw new Error(`Índice ${vertexIndex1Based} fora do intervalo 1..${this.nVerts} para '${id}'.`);
      }
      const vert = ctx.vertices?.[vertexIndex1Based - 1];
      if (vert) {
        const fromVert = getFromSource(vert, id);
        if (fromVert) return fromVert;
      }
    }

    return getFromSource(ctx, id) ?? null;
  }

  private parseFunctionCall(fnName: string): EvalValue {
    this.expect("lparen", `Esperado '(' após '${fnName}'`);
    const args: EvalValue[] = [];
    if (this.peek()?.type !== "rparen") {
      args.push(this.parseAddExpr());
      while (this.peek()?.type === "comma") {
        this.consume();
        args.push(this.parseAddExpr());
      }
    }
    this.expect("rparen", `Esperado ')' após argumentos de '${fnName}'`);

    const lower = fnName.toLowerCase();
    if (lower === "inv") {
      if (args.length !== 1) throw new Error("inv(M) requer exatamente 1 argumento.");
      const a = args[0];
      if (a.scalableIdentity !== undefined) {
        if (Math.abs(a.scalableIdentity) <= 1e-13) {
          throw new Error("Identidade escalar nula não é invertível em inv(...).");
        }
        return {
          rows: 1,
          cols: 1,
          data: [1 / a.scalableIdentity],
          scalableIdentity: 1 / a.scalableIdentity,
        };
      }
      const inv = invertDenseMatrix(a);
      return { ...inv, ...(inv.rows === 1 && inv.cols === 1 ? { isScalar: true } : {}) };
    }

    if (lower === "sqrt") {
      if (args.length !== 1 || !isScalarLike(args[0])) {
        throw new Error("sqrt(s) requer exatamente 1 argumento escalar.");
      }
      const v = args[0].data[0];
      if (v < -1e-12) {
        throw new Error(`sqrt(s) recebeu valor negativo (${v.toExponential(3)}).`);
      }
      return makeScalarVal(Math.sqrt(Math.max(0, v)));
    }

    if (lower === "abs") {
      if (args.length !== 1) throw new Error("abs(x) requer exatamente 1 argumento.");
      const a = args[0];
      if (a.scalableIdentity !== undefined) {
        const v = Math.abs(a.scalableIdentity);
        return { rows: 1, cols: 1, data: [v], scalableIdentity: v };
      }
      return {
        rows: a.rows,
        cols: a.cols,
        data: a.data.map((x) => Math.abs(x)),
        ...(a.isScalar ? { isScalar: true } : {}),
      };
    }

    if (lower === "trace" || lower === "tr") {
      if (args.length !== 1) throw new Error(`${fnName}(M) requer exatamente 1 argumento.`);
      const a = args[0];
      if (a.scalableIdentity !== undefined) {
        throw new Error(`${fnName}(I) requer dimensão explícita; use eye(n).`);
      }
      if (a.rows !== a.cols) {
        throw new Error(`${fnName}(M) requer matriz quadrada, recebido (${a.rows}×${a.cols}).`);
      }
      let sum = 0;
      for (let i = 0; i < a.rows; i += 1) {
        sum += a.data[i * a.cols + i];
      }
      return makeScalarVal(sum);
    }

    if (lower === "norm") {
      if (args.length !== 1) throw new Error("norm(M) requer exatamente 1 argumento.");
      const a = args[0];
      if (a.scalableIdentity !== undefined) {
        throw new Error("norm(I) requer dimensão explícita; use eye(n).");
      }
      let sumSq = 0;
      for (const v of a.data) sumSq += v * v;
      return makeScalarVal(Math.sqrt(sumSq));
    }

    if (lower === "diag") {
      if (args.length !== 1) throw new Error("diag(M) requer exatamente 1 argumento.");
      const a = args[0];
      if (a.scalableIdentity !== undefined) {
        throw new Error("diag(I) requer dimensão explícita; use eye(n).");
      }
      if (a.rows === 1 && a.cols === 1) {
        return { rows: 1, cols: 1, data: [a.data[0]], isScalar: true };
      }
      if (a.rows === 1 || a.cols === 1) {
        const n = Math.max(a.rows, a.cols);
        const out = new Array<number>(n * n).fill(0);
        for (let i = 0; i < n; i += 1) out[i * n + i] = a.data[i];
        return { rows: n, cols: n, data: out };
      }
      const d = Math.min(a.rows, a.cols);
      const out = new Array<number>(d);
      for (let i = 0; i < d; i += 1) out[i] = a.data[i * a.cols + i];
      return { rows: d, cols: 1, data: out };
    }

    if (lower === "he") {
      if (args.length !== 1) throw new Error("He(M) requer exatamente 1 argumento.");
      const a = args[0];
      if (a.scalableIdentity !== undefined) {
        return scaleVal(2, a);
      }
      if (a.rows !== a.cols) {
        throw new Error(`He(M) requer matriz quadrada, recebido (${a.rows}×${a.cols}).`);
      }
      return addVal(a, transposeVal(a), 1);
    }

    if (fnName === "I" || lower === "eye") {
      if (args.length === 0) return this.resolvePlainSymbol("I");
      if (args.length !== 1 || !isScalarLike(args[0])) {
        throw new Error(`${fnName}(d) requer dimensão escalar inteira positiva.`);
      }
      return makeIdentityVal(Math.round(args[0].data[0]), 1);
    }

    if (lower === "zeros") {
      if (args.length === 1 && isScalarLike(args[0])) {
        const d = Math.round(args[0].data[0]);
        return makeZeroVal(d, d);
      }
      if (args.length === 2 && isScalarLike(args[0]) && isScalarLike(args[1])) {
        return makeZeroVal(Math.round(args[0].data[0]), Math.round(args[1].data[0]));
      }
      throw new Error("zeros(r, c) requer dimensões escalares inteiras positivas.");
    }

    throw new Error(`Função desconhecida '${fnName}' na expressão recover.`);
  }
}

function expandRecoveryBindings(
  quantifier: LmiDslQuantifier | undefined,
  lhs: string,
  systemN: number,
  indexRanges: ReadonlyMap<string, { start: number; end: number }>,
): Array<Record<string, number>> {
  const getRange = (v: string): { start: number; end: number } => {
    return indexRanges.get(v) ?? { start: 1, end: systemN };
  };

  let vars: string[] = [];
  let condition: string | null = null;

  if (quantifier && quantifier.vars.length > 0) {
    vars = quantifier.vars;
    condition = quantifier.condition;
  } else {
    // Auto-detect symbolic indices in lhs such as `K[i]` or `F[i, j]`
    const idxMatch = /\[([^\]]+)\]/.exec(lhs);
    if (idxMatch) {
      const tokens = idxMatch[1]
        .split(",")
        .map((s) => s.trim())
        .filter((s) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(s));
      vars = tokens;
    }
  }

  if (vars.length === 0) return [{}];

  if (vars.length === 1) {
    const v0 = vars[0];
    const r0 = getRange(v0);
    const out: Array<Record<string, number>> = [];
    for (let i = r0.start; i <= r0.end; i += 1) {
      out.push({ [v0]: i });
    }
    return out;
  }

  const [v0, v1] = vars;
  const r0 = getRange(v0);
  const r1 = getRange(v1);
  const norm = (condition ?? "").replace(/\s+/g, "").toLowerCase();
  const l0 = v0.toLowerCase();
  const l1 = v1.toLowerCase();
  const out: Array<Record<string, number>> = [];
  for (let i = r0.start; i <= r0.end; i += 1) {
    for (let j = r1.start; j <= r1.end; j += 1) {
      let ok = true;
      if (norm === `${l1}>${l0}` || norm === `${l0}<${l1}`) ok = j > i;
      else if (norm === `${l1}>=${l0}` || norm === `${l0}<=${l1}`) ok = j >= i;
      else if (norm === `${l0}>${l1}` || norm === `${l1}<${l0}`) ok = i > j;
      else if (norm === `${l0}>=${l1}` || norm === `${l1}<=${l0}`) ok = i >= j;
      else if (norm === `${l0}!=${l1}` || norm === `${l1}!=${l0}`) ok = i !== j;
      if (ok) {
        out.push({ [v0]: i, [v1]: j });
      }
    }
  }
  return out;
}

function substituteIndexTokensInLabel(lhs: string, binding: Record<string, number>): string {
  const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([^\]]+)\s*\]$/.exec(lhs.trim());
  if (!m) return lhs.trim();
  const base = m[1];
  const parts = m[2]
    .split(",")
    .map((tok) => {
      const t = tok.trim();
      if (Object.prototype.hasOwnProperty.call(binding, t)) {
        return String(binding[t]);
      }
      return t;
    });
  return `${base}[${parts.join(",")}]`;
}

function inferMaxSolvedIndex(solvedVariables: Record<string, DenseMatrixValue>): number {
  let maxIdx = 0;
  for (const key of Object.keys(solvedVariables)) {
    const m = /\[(\d+(?:,\d+)*)\]$/.exec(key);
    if (!m) continue;
    for (const part of m[1].split(",")) {
      const n = Number(part);
      if (Number.isInteger(n) && n > maxIdx) maxIdx = n;
    }
  }
  return maxIdx;
}

export function evaluateAllRecoveries(input: RecoverEvalInput): EvaluatedRecoveryEntry[] {
  const { parsed, compileCtx, solvedVariables } = input;
  if (parsed.recoveries.length === 0) return [];

  const paramMap = new Map<string, number>();
  for (const prm of parsed.params) {
    paramMap.set(prm.name, prm.value);
  }
  if (compileCtx?.params) {
    for (const [k, v] of Object.entries(compileCtx.params)) {
      if (Number.isFinite(v)) paramMap.set(k, v);
    }
  }

  const maxSolvedIdx = inferMaxSolvedIndex(solvedVariables);
  const systemN = Math.max(
    1,
    compileCtx?.vertices?.length ?? 0,
    parsed.effectiveSystemN,
    maxSolvedIdx,
  );
  const deltaN = Math.max(1, compileCtx?.deltaVertices?.length ?? systemN);

  const indexRanges = new Map<string, { start: number; end: number }>();
  for (const decl of parsed.indices) {
    let resolvedEnd: number;
    if (/^\d+$/.test(decl.rangeEndExpr)) {
      resolvedEnd = decl.resolvedEnd;
    } else if (
      decl.rangeEndExpr.toUpperCase() === "K" &&
      compileCtx?.deltaVertices &&
      compileCtx.deltaVertices.length > 0
    ) {
      resolvedEnd = deltaN;
    } else if (paramMap.has(decl.rangeEndExpr)) {
      resolvedEnd = Math.round(paramMap.get(decl.rangeEndExpr)!);
    } else {
      resolvedEnd = systemN;
    }
    indexRanges.set(decl.name, {
      start: decl.rangeStart,
      end: Math.max(decl.rangeStart, resolvedEnd),
    });
  }

  const varMap = new Map<string, DenseMatrixValue>();
  for (const [k, v] of Object.entries(solvedVariables)) {
    varMap.set(k, { rows: v.rows, cols: v.cols, data: [...v.data] });
  }

  const results: EvaluatedRecoveryEntry[] = [];

  for (const rec of parsed.recoveries) {
    const bindings = expandRecoveryBindings(rec.quantifier, rec.lhs, systemN, indexRanges);
    for (const binding of bindings) {
      const label = substituteIndexTokensInLabel(rec.lhs, binding);
      try {
        const ev = new RecoverExprEvaluator(
          rec.rhs,
          binding,
          varMap,
          paramMap,
          compileCtx,
          systemN,
        );
        const evaluated = ev.evaluate();
        if (evaluated.scalableIdentity !== undefined) {
          const dim = compileCtx?.A.length ?? 1;
          const mat = makeIdentityVal(dim, evaluated.scalableIdentity);
          const value: DenseMatrixValue = { rows: mat.rows, cols: mat.cols, data: mat.data };
          varMap.set(label, value);
          results.push({
            label,
            formula: rec.rhs,
            ok: true,
            value,
            isScalar: value.rows === 1 && value.cols === 1,
          });
        } else {
          const value: DenseMatrixValue = {
            rows: evaluated.rows,
            cols: evaluated.cols,
            data: evaluated.data,
          };
          varMap.set(label, value);
          results.push({
            label,
            formula: rec.rhs,
            ok: true,
            value,
            isScalar: Boolean(evaluated.isScalar) || (value.rows === 1 && value.cols === 1),
          });
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        results.push({
          label,
          formula: rec.rhs,
          ok: false,
          error: msg,
        });
      }
    }
  }

  return results;
}
