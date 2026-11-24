/**
 * Compilador Direto Determinístico DSL v2.0 -> CanonicalSDPProblem JSON (Tab 6 — `WP-PHASE4-01-F8-DSL-DIRECT-SDP-COMPILER`)
 * seguindo CL-LMI-DSL-DIR-001 v1.0.0 e CL-DIR-001 Seção 6.1.
 *
 * Segurança & Regras:
 * - Zero execução dinâmica de código (sem eval ou construtor Function dinâmico).
 * - Parser descendente recursivo + avaliador matricial afim puro em TypeScript.
 * - Compila qualquer LMI válida da DSL v2.0 (LTI, decaimento α, alocação regional,
 *   LQR via Schur, H∞ BRL / planta generalizada com `*`, politópico `forall i`,
 *   Takagi-Sugeno PDC `forall i` + `forall i, j where j > i`, macros `He(X)`)
 *   diretamente em um `CanonicalSDPProblem` JSON compatível com `CanonicalSDPProblem.from_dict`.
 */

import type { PackedSparseCooPayload } from "../../bridge/protocol.ts";
import type {
  LmiDslParseResult,
  LmiDslQuantifier,
  LmiDslVariable,
} from "./lmi_dsl_parser.ts";

export interface LmiVertexMatrices {
  A: number[][];
  B: number[][];
  C?: number[][];
  D?: number[][];
  Bw?: number[][];
  Dyw?: number[][];
  Cz?: number[][];
  Dzu?: number[][];
  Dzw?: number[][];
}

export interface LmiDeltaVertexMatrices {
  dA: number[][];
  dC?: number[][];
}

export interface LmiCompileContext {
  A: number[][];
  B: number[][];
  C: number[][];
  D: number[][];
  Bw?: number[][];
  Dyw?: number[][];
  Cz?: number[][];
  Dzu?: number[][];
  Dzw?: number[][];
  Q_cost?: number[][];
  R_cost?: number[][];
  vertices?: LmiVertexMatrices[];
  deltaVertices?: LmiDeltaVertexMatrices[];
  params?: Record<string, number>;
  strictMargin?: number;
  name?: string;
  format?: LmiSdpBlockFormat;
}

export interface CanonicalTensor1D {
  shape: [number];
  dtype: "float64";
  order: "C";
  data: number[];
}

export interface CanonicalTensor2D {
  shape: [number, number];
  dtype: "float64";
  order: "C";
  data: number[];
}

export type LmiSdpBlockFormat = "packed" | "sparse" | "dense";

export interface LmiCompileOptions {
  format?: LmiSdpBlockFormat;
}

export interface PackedSparseCooTypedArrays extends PackedSparseCooPayload {
  k_idx: Int32Array;
  rows: Int32Array;
  cols: Int32Array;
  vals: Float64Array;
}

export interface CanonicalSDPBlockJson {
  name: string;
  dim: number;
  n_vars: number;
  F0: CanonicalTensor2D;
  F_k_packed?: PackedSparseCooTypedArrays;
  F_k_sparse?: Record<string, [number, number, number][]>;
  F_k?: CanonicalTensor2D[];
}

export interface CanonicalVariableMapEntry {
  name: string;
  var_id: number;
  shape: [number, number];
  symmetric: boolean;
  offset: number;
  size: number;
  coords: [number, number][];
}

export interface CanonicalSDPProblemJson {
  name: string;
  n_vars: number;
  c: CanonicalTensor1D;
  c0: number;
  blocks: CanonicalSDPBlockJson[];
  variable_map: Record<string, CanonicalVariableMapEntry>;
  recovery_plan: null;
}

export interface LmiFusionStats {
  originalBlocks: number;
  fusedBlocks: number;
  eliminatedSymmetricPairs: number;
}

export interface LmiCompileResult {
  problem: CanonicalSDPProblemJson;
  nVars: number;
  blockCount: number;
  variableNames: string[];
  fusionStats: LmiFusionStats;
}

interface AffineMatrix {
  rows: number;
  cols: number;
  constMat: Float64Array;
  terms: Map<number, Float64Array>;
  scalarZero?: boolean;
  scalableIdentity?: {
    constCoeff: number;
    terms: Map<number, number>;
  };
}

interface Token {
  type: "num" | "id" | "op" | "lparen" | "rparen" | "lbracket" | "rbracket" | "comma" | "semi" | "quote" | "dotT" | "star";
  val: string;
  pos: number;
}

function tokenizeExpr(expr: string): Token[] {
  const tokens: Token[] = [];
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
    if (ch === ";") {
      tokens.push({ type: "semi", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === "'") {
      tokens.push({ type: "quote", val: ch, pos: i });
      i += 1;
      continue;
    }
    if (ch === "*" && (tokens.length === 0 || ["comma", "semi", "lbracket"].includes(tokens[tokens.length - 1].type))) {
      // Standalone '*' inside bmat cell
      const nextNonSpace = expr.slice(i + 1).trimStart()[0];
      if (nextNonSpace === "," || nextNonSpace === ";" || nextNonSpace === "]") {
        tokens.push({ type: "star", val: "*", pos: i });
        i += 1;
        continue;
      }
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

function makeZeroAffine(rows: number, cols: number): AffineMatrix {
  return {
    rows,
    cols,
    constMat: new Float64Array(rows * cols),
    terms: new Map<number, Float64Array>(),
  };
}

function makeConstantAffine(mat: number[][], label = "matriz"): AffineMatrix {
  const rows = mat.length;
  const cols = mat[0]?.length ?? 0;
  if (rows < 1 || cols < 1) {
    throw new Error(`Matriz '${label}' vazia ou com dimensão inválida.`);
  }
  const constMat = new Float64Array(rows * cols);
  for (let r = 0; r < rows; r += 1) {
    if (mat[r].length !== cols) {
      throw new Error(`Matriz '${label}' possui linhas com tamanhos inconsistentes.`);
    }
    for (let c = 0; c < cols; c += 1) {
      const v = Number(mat[r][c]);
      if (!Number.isFinite(v)) {
        throw new Error(`Matriz '${label}' contém valor não finito em (${r}, ${c}).`);
      }
      constMat[r * cols + c] = v;
    }
  }
  return { rows, cols, constMat, terms: new Map<number, Float64Array>() };
}

function makeScalarAffine(val: number): AffineMatrix {
  const constMat = new Float64Array(1);
  constMat[0] = val;
  return {
    rows: 1,
    cols: 1,
    constMat,
    terms: new Map<number, Float64Array>(),
    ...(val === 0 ? { scalarZero: true } : {}),
  };
}

function makeIdentityAffine(dim: number): AffineMatrix {
  const constMat = new Float64Array(dim * dim);
  for (let i = 0; i < dim; i += 1) {
    constMat[i * dim + i] = 1.0;
  }
  return { rows: dim, cols: dim, constMat, terms: new Map<number, Float64Array>() };
}

function materializeScalableIdentity(
  ident: NonNullable<AffineMatrix["scalableIdentity"]>,
  dim: number,
): AffineMatrix {
  const out = makeZeroAffine(dim, dim);
  for (let i = 0; i < dim; i += 1) {
    out.constMat[i * dim + i] = ident.constCoeff;
  }
  for (const [k, coeff] of ident.terms.entries()) {
    if (coeff === 0) continue;
    const arr = new Float64Array(dim * dim);
    for (let i = 0; i < dim; i += 1) {
      arr[i * dim + i] = coeff;
    }
    out.terms.set(k, arr);
  }
  return out;
}

function cloneAffine(a: AffineMatrix): AffineMatrix {
  const terms = new Map<number, Float64Array>();
  for (const [k, arr] of a.terms.entries()) {
    terms.set(k, new Float64Array(arr));
  }
  return {
    rows: a.rows,
    cols: a.cols,
    constMat: new Float64Array(a.constMat),
    terms,
    ...(a.scalarZero ? { scalarZero: true } : {}),
    ...(a.scalableIdentity
      ? {
          scalableIdentity: {
            constCoeff: a.scalableIdentity.constCoeff,
            terms: new Map(a.scalableIdentity.terms),
          },
        }
      : {}),
  };
}

function scaleAffine(alpha: number, a: AffineMatrix): AffineMatrix {
  const out = makeZeroAffine(a.rows, a.cols);
  for (let i = 0; i < a.constMat.length; i += 1) {
    out.constMat[i] = alpha * a.constMat[i];
  }
  if (alpha !== 0) {
    for (const [k, arr] of a.terms.entries()) {
      const scaled = new Float64Array(arr.length);
      for (let i = 0; i < arr.length; i += 1) {
        scaled[i] = alpha * arr[i];
      }
      out.terms.set(k, scaled);
    }
  }
  if (a.scalarZero || alpha === 0) {
    out.scalarZero = true;
  }
  if (a.scalableIdentity) {
    const scaledTerms = new Map<number, number>();
    if (alpha !== 0) {
      for (const [k, v] of a.scalableIdentity.terms.entries()) {
        scaledTerms.set(k, alpha * v);
      }
    }
    out.scalableIdentity = {
      constCoeff: alpha * a.scalableIdentity.constCoeff,
      terms: scaledTerms,
    };
  }
  return out;
}

function transposeAffine(a: AffineMatrix): AffineMatrix {
  if (a.scalableIdentity) {
    return cloneAffine(a);
  }
  const out = makeZeroAffine(a.cols, a.rows);
  for (let r = 0; r < a.rows; r += 1) {
    for (let c = 0; c < a.cols; c += 1) {
      out.constMat[c * a.rows + r] = a.constMat[r * a.cols + c];
    }
  }
  for (const [k, arr] of a.terms.entries()) {
    const t = new Float64Array(a.rows * a.cols);
    for (let r = 0; r < a.rows; r += 1) {
      for (let c = 0; c < a.cols; c += 1) {
        t[c * a.rows + r] = arr[r * a.cols + c];
      }
    }
    out.terms.set(k, t);
  }
  if (a.scalarZero) out.scalarZero = true;
  return out;
}

function addAffine(aRaw: AffineMatrix, bRaw: AffineMatrix, signB: 1 | -1 = 1): AffineMatrix {
  if (aRaw.scalarZero && !bRaw.scalarZero) {
    return signB === 1 ? cloneAffine(bRaw) : scaleAffine(-1, bRaw);
  }
  if (bRaw.scalarZero && !aRaw.scalarZero) {
    return cloneAffine(aRaw);
  }
  if (aRaw.scalarZero && bRaw.scalarZero) {
    return makeScalarAffine(0);
  }

  let a = aRaw;
  let b = bRaw;
  if (a.scalableIdentity && !b.scalableIdentity) {
    if (b.rows !== b.cols) {
      throw new Error(`Identidade 'I' não pode ser somada a matriz não quadrada (${b.rows}×${b.cols}).`);
    }
    a = materializeScalableIdentity(a.scalableIdentity, b.rows);
  } else if (b.scalableIdentity && !a.scalableIdentity) {
    if (a.rows !== a.cols) {
      throw new Error(`Identidade 'I' não pode ser somada a matriz não quadrada (${a.rows}×${a.cols}).`);
    }
    b = materializeScalableIdentity(b.scalableIdentity, a.rows);
  } else if (a.scalableIdentity && b.scalableIdentity) {
    const terms = new Map(a.scalableIdentity.terms);
    for (const [k, v] of b.scalableIdentity.terms.entries()) {
      terms.set(k, (terms.get(k) ?? 0) + signB * v);
    }
    return {
      rows: 1,
      cols: 1,
      constMat: new Float64Array([a.scalableIdentity.constCoeff + signB * b.scalableIdentity.constCoeff]),
      terms: new Map<number, Float64Array>(),
      scalableIdentity: {
        constCoeff: a.scalableIdentity.constCoeff + signB * b.scalableIdentity.constCoeff,
        terms,
      },
    };
  }

  if (a.rows !== b.rows || a.cols !== b.cols) {
    throw new Error(
      `Incompatibilidade de dimensões na soma/subtração: (${a.rows}×${a.cols}) vs (${b.rows}×${b.cols}).`,
    );
  }

  const out = makeZeroAffine(a.rows, a.cols);
  for (let i = 0; i < out.constMat.length; i += 1) {
    out.constMat[i] = a.constMat[i] + signB * b.constMat[i];
  }
  for (const [k, arr] of a.terms.entries()) {
    out.terms.set(k, new Float64Array(arr));
  }
  for (const [k, arrB] of b.terms.entries()) {
    const existing = out.terms.get(k);
    if (existing) {
      for (let i = 0; i < existing.length; i += 1) {
        existing[i] += signB * arrB[i];
      }
    } else {
      const next = new Float64Array(arrB.length);
      for (let i = 0; i < arrB.length; i += 1) {
        next[i] = signB * arrB[i];
      }
      out.terms.set(k, next);
    }
  }
  return out;
}

function mulAffine(a: AffineMatrix, b: AffineMatrix): AffineMatrix {
  if (a.scalableIdentity && b.scalableIdentity) {
    if (a.scalableIdentity.terms.size > 0 && b.scalableIdentity.terms.size > 0) {
      throw new Error("Termo bilinear detectado: produto entre duas expressões escalares com variáveis de decisão.");
    }
    if (a.scalableIdentity.terms.size === 0) {
      const alpha = a.scalableIdentity.constCoeff;
      const terms = new Map<number, number>();
      for (const [k, v] of b.scalableIdentity.terms.entries()) terms.set(k, alpha * v);
      return {
        rows: 1,
        cols: 1,
        constMat: new Float64Array([alpha * b.scalableIdentity.constCoeff]),
        terms: new Map<number, Float64Array>(),
        scalableIdentity: { constCoeff: alpha * b.scalableIdentity.constCoeff, terms },
      };
    }
    const beta = b.scalableIdentity.constCoeff;
    const terms = new Map<number, number>();
    for (const [k, v] of a.scalableIdentity.terms.entries()) terms.set(k, beta * v);
    return {
      rows: 1,
      cols: 1,
      constMat: new Float64Array([beta * a.scalableIdentity.constCoeff]),
      terms: new Map<number, Float64Array>(),
      scalableIdentity: { constCoeff: beta * a.scalableIdentity.constCoeff, terms },
    };
  }

  // Scalar * ScalableIdentity (e.g., gamma_sq * I)
  if (!a.scalableIdentity && a.rows === 1 && a.cols === 1 && b.scalableIdentity) {
    if (a.terms.size > 0 && b.scalableIdentity.terms.size > 0) {
      throw new Error("Termo bilinear detectado: produto entre duas variáveis de decisão.");
    }
    if (a.terms.size === 0) {
      return scaleAffine(a.constMat[0], b);
    }
    const beta = b.scalableIdentity.constCoeff;
    const terms = new Map<number, number>();
    for (const [k, arr] of a.terms.entries()) {
      terms.set(k, beta * arr[0]);
    }
    return {
      rows: 1,
      cols: 1,
      constMat: new Float64Array([beta * a.constMat[0]]),
      terms: new Map<number, Float64Array>(),
      scalableIdentity: { constCoeff: beta * a.constMat[0], terms },
    };
  }
  if (a.scalableIdentity && !b.scalableIdentity && b.rows === 1 && b.cols === 1) {
    return mulAffine(b, a);
  }

  // Materialize scalableIdentity if multiplied by concrete matrix
  if (a.scalableIdentity && !b.scalableIdentity) {
    const matA = materializeScalableIdentity(a.scalableIdentity, b.rows);
    return mulAffine(matA, b);
  }
  if (!a.scalableIdentity && b.scalableIdentity) {
    const matB = materializeScalableIdentity(b.scalableIdentity, a.cols);
    return mulAffine(a, matB);
  }

  // Scalar * Matrix or Matrix * Scalar
  if (a.rows === 1 && a.cols === 1 && !(b.rows === 1 && b.cols === 1)) {
    if (a.terms.size === 0) {
      return scaleAffine(a.constMat[0], b);
    }
    if (b.terms.size > 0) {
      throw new Error("Termo bilinear detectado: produto entre escalar variável e matriz variável.");
    }
    const out = scaleAffine(a.constMat[0], b);
    for (const [k, arrA] of a.terms.entries()) {
      const coeff = arrA[0];
      const mat = new Float64Array(b.constMat.length);
      for (let i = 0; i < b.constMat.length; i += 1) {
        mat[i] = coeff * b.constMat[i];
      }
      out.terms.set(k, mat);
    }
    return out;
  }
  if (b.rows === 1 && b.cols === 1 && !(a.rows === 1 && a.cols === 1)) {
    if (b.terms.size === 0) {
      return scaleAffine(b.constMat[0], a);
    }
    if (a.terms.size > 0) {
      throw new Error("Termo bilinear detectado: produto entre matriz variável e escalar variável.");
    }
    const out = scaleAffine(b.constMat[0], a);
    for (const [k, arrB] of b.terms.entries()) {
      const coeff = arrB[0];
      const mat = new Float64Array(a.constMat.length);
      for (let i = 0; i < a.constMat.length; i += 1) {
        mat[i] = coeff * a.constMat[i];
      }
      out.terms.set(k, mat);
    }
    return out;
  }

  if (a.cols !== b.rows) {
    throw new Error(
      `Incompatibilidade de dimensões no produto matricial: (${a.rows}×${a.cols}) * (${b.rows}×${b.cols}).`,
    );
  }
  if (a.terms.size > 0 && b.terms.size > 0) {
    throw new Error(
      "Termo bilinear detectado (produto entre duas expressões com variáveis de decisão). Aplique mudança de variáveis para manter o problema afim.",
    );
  }

  const M = a.rows;
  const K = a.cols;
  const N = b.cols;
  const matMul = (left: Float64Array, right: Float64Array): Float64Array => {
    const res = new Float64Array(M * N);
    for (let r = 0; r < M; r += 1) {
      for (let p = 0; p < K; p += 1) {
        const lVal = left[r * K + p];
        if (lVal === 0) continue;
        for (let c = 0; c < N; c += 1) {
          res[r * N + c] += lVal * right[p * N + c];
        }
      }
    }
    return res;
  };

  const out: AffineMatrix = {
    rows: M,
    cols: N,
    constMat: matMul(a.constMat, b.constMat),
    terms: new Map<number, Float64Array>(),
  };
  if (a.terms.size === 0) {
    for (const [k, arrB] of b.terms.entries()) {
      out.terms.set(k, matMul(a.constMat, arrB));
    }
  } else {
    for (const [k, arrA] of a.terms.entries()) {
      out.terms.set(k, matMul(arrA, b.constMat));
    }
  }
  return out;
}

function invertConstantMatrix(a: AffineMatrix): AffineMatrix {
  if (a.terms.size > 0 || a.scalableIdentity) {
    throw new Error("inv(X) só é permitido para matrizes constantes conhecidas (sem variáveis de decisão).");
  }
  if (a.rows !== a.cols) {
    throw new Error(`inv(X) requer matriz quadrada, recebido (${a.rows}×${a.cols}).`);
  }
  const n = a.rows;
  const aug: number[][] = Array.from({ length: n }, (_, i) => {
    const row: number[] = [];
    for (let j = 0; j < n; j += 1) row.push(a.constMat[i * n + j]);
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
    if (maxAbs <= 1e-13) {
      throw new Error("Matriz singular encontrada em inv(...).");
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

  const invMat = new Float64Array(n * n);
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < n; j += 1) {
      invMat[i * n + j] = aug[i][n + j];
    }
  }
  return { rows: n, cols: n, constMat: invMat, terms: new Map<number, Float64Array>() };
}

function traceAffine(a: AffineMatrix): AffineMatrix {
  if (a.rows !== a.cols) {
    throw new Error(`trace(X) requer matriz quadrada, recebido (${a.rows}×${a.cols}).`);
  }
  const n = a.rows;
  let cSum = 0;
  for (let i = 0; i < n; i += 1) cSum += a.constMat[i * n + i];
  const terms = new Map<number, Float64Array>();
  for (const [k, arr] of a.terms.entries()) {
    let s = 0;
    for (let i = 0; i < n; i += 1) s += arr[i * n + i];
    if (s !== 0) terms.set(k, new Float64Array([s]));
  }
  return { rows: 1, cols: 1, constMat: new Float64Array([cSum]), terms };
}

function symmetrizeSquareInPlace(arr: Float64Array, dim: number): void {
  for (let r = 0; r < dim; r += 1) {
    for (let c = r + 1; c < dim; c += 1) {
      const avg = 0.5 * (arr[r * dim + c] + arr[c * dim + r]);
      arr[r * dim + c] = avg;
      arr[c * dim + r] = avg;
    }
  }
}

function areSymmetrizedArraysEqual(
  arrA: Float64Array | undefined,
  arrB: Float64Array | undefined,
  dim: number,
  tol: number,
): boolean {
  for (let r = 0; r < dim; r += 1) {
    const rOff = r * dim;
    for (let c = r; c < dim; c += 1) {
      const va = arrA
        ? r === c
          ? arrA[rOff + c]
          : 0.5 * (arrA[rOff + c] + arrA[c * dim + r])
        : 0;
      const vb = arrB
        ? r === c
          ? arrB[rOff + c]
          : 0.5 * (arrB[rOff + c] + arrB[c * dim + r])
        : 0;
      if (Math.abs(va - vb) > tol) return false;
    }
  }
  return true;
}

function areSymmetrizedAffinesEqual(
  a: AffineMatrix,
  b: AffineMatrix,
  tol = 1e-12,
): boolean {
  if (a.rows !== b.rows || a.cols !== b.cols || a.rows !== a.cols) {
    return false;
  }
  const dim = a.rows;
  if (!areSymmetrizedArraysEqual(a.constMat, b.constMat, dim, tol)) {
    return false;
  }
  for (const [k, arrA] of a.terms.entries()) {
    if (!areSymmetrizedArraysEqual(arrA, b.terms.get(k), dim, tol)) {
      return false;
    }
  }
  for (const [k, arrB] of b.terms.entries()) {
    if (a.terms.has(k)) continue;
    if (!areSymmetrizedArraysEqual(undefined, arrB, dim, tol)) {
      return false;
    }
  }
  return true;
}

function float64ToTensor2D(arr: Float64Array, rows: number, cols: number): CanonicalTensor2D {
  return {
    shape: [rows, cols],
    dtype: "float64",
    order: "C",
    data: Array.from(arr),
  };
}

function resolveDimToken(
  rawTok: string,
  dims: { n: number; m: number; p: number; nw: number; nz: number },
  params: ReadonlyMap<string, number>,
): number {
  const t = rawTok.trim();
  if (t === "n") return dims.n;
  if (t === "m") return dims.m;
  if (t === "p") return dims.p;
  if (t === "nw") return dims.nw;
  if (t === "nz") return dims.nz;
  if (params.has(t)) {
    const v = params.get(t)!;
    if (Number.isInteger(v) && v >= 1) return v;
  }
  const num = Number(t);
  if (Number.isInteger(num) && num >= 1) return num;
  throw new Error(`Dimensão de variável inválida '${rawTok}'.`);
}

function expandQuantifierBindings(
  q: LmiDslQuantifier | undefined,
  N: number,
  indexRanges?: ReadonlyMap<string, { start: number; end: number }>,
): Array<Record<string, number>> {
  if (!q || q.vars.length === 0) return [{}];
  const getRange = (v: string): { start: number; end: number } => {
    return indexRanges?.get(v) ?? { start: 1, end: N };
  };
  const bindings: Array<Record<string, number>> = [];
  if (q.vars.length === 1) {
    const v0 = q.vars[0];
    const r0 = getRange(v0);
    for (let i = r0.start; i <= r0.end; i += 1) {
      bindings.push({ [v0]: i });
    }
    return bindings;
  }
  const [v0, v1] = q.vars;
  const r0 = getRange(v0);
  const r1 = getRange(v1);
  const norm = (q.condition ?? "").replace(/\s+/g, "").toLowerCase();
  const l0 = v0.toLowerCase();
  const l1 = v1.toLowerCase();
  for (let i = r0.start; i <= r0.end; i += 1) {
    for (let j = r1.start; j <= r1.end; j += 1) {
      let ok = true;
      if (norm === `${l1}>${l0}` || norm === `${l0}<${l1}`) ok = j > i;
      else if (norm === `${l1}>=${l0}` || norm === `${l0}<=${l1}`) ok = j >= i;
      else if (norm === `${l0}>${l1}` || norm === `${l1}<${l0}`) ok = i > j;
      else if (norm === `${l0}>=${l1}` || norm === `${l1}<=${l0}`) ok = i >= j;
      else if (norm === `${l0}!=${l1}` || norm === `${l1}!=${l0}`) ok = i !== j;
      if (ok) {
        bindings.push({ [v0]: i, [v1]: j });
      }
    }
  }
  return bindings;
}

class ExprEvaluator {
  private readonly tokens: Token[];
  private pos = 0;
  private readonly binding: Record<string, number>;
  private readonly ctx: LmiCompileContext;
  private readonly varMap: ReadonlyMap<string, AffineMatrix>;
  private readonly paramMap: ReadonlyMap<string, number>;
  private readonly nVerts: number;

  constructor(
    expr: string,
    binding: Record<string, number>,
    ctx: LmiCompileContext,
    varMap: ReadonlyMap<string, AffineMatrix>,
    paramMap: ReadonlyMap<string, number>,
    nVerts: number,
  ) {
    this.tokens = tokenizeExpr(expr);
    this.binding = binding;
    this.ctx = ctx;
    this.varMap = varMap;
    this.paramMap = paramMap;
    this.nVerts = nVerts;
  }

  private peek(offset = 0): Token | undefined {
    return this.tokens[this.pos + offset];
  }

  private consume(): Token {
    const t = this.tokens[this.pos];
    if (!t) throw new Error("Fim inesperado da expressão.");
    this.pos += 1;
    return t;
  }

  private expect(type: Token["type"], msg: string): Token {
    const t = this.peek();
    if (!t || t.type !== type) {
      throw new Error(`${msg} (encontrado '${t?.val ?? "EOF"}').`);
    }
    this.pos += 1;
    return t;
  }

  public parseTopExpr(): AffineMatrix {
    const val = this.parseAddExpr();
    if (this.pos < this.tokens.length) {
      throw new Error(`Token inesperado '${this.tokens[this.pos].val}' na expressão.`);
    }
    return val;
  }

  private parseAddExpr(): AffineMatrix {
    let left = this.parseMulExpr();
    while (this.peek()?.type === "op" && (this.peek()?.val === "+" || this.peek()?.val === "-")) {
      const op = this.consume().val as "+" | "-";
      const right = this.parseMulExpr();
      left = addAffine(left, right, op === "+" ? 1 : -1);
    }
    return left;
  }

  private parseMulExpr(): AffineMatrix {
    let left = this.parseUnaryExpr();
    while (
      this.peek()?.type === "op" &&
      (this.peek()?.val === "*" || this.peek()?.val === "@" || this.peek()?.val === "/")
    ) {
      const op = this.consume().val;
      const right = this.parseUnaryExpr();
      if (op === "/") {
        if (right.rows !== 1 || right.cols !== 1 || right.terms.size > 0 || right.scalableIdentity) {
          throw new Error("Divisão só é suportada por escalar constante não nulo.");
        }
        const denom = right.constMat[0];
        if (denom === 0) throw new Error("Divisão por zero na expressão LMI.");
        left = scaleAffine(1 / denom, left);
      } else {
        left = mulAffine(left, right);
      }
    }
    return left;
  }

  private parseUnaryExpr(): AffineMatrix {
    const t = this.peek();
    if (t?.type === "op" && (t.val === "+" || t.val === "-")) {
      this.consume();
      const inner = this.parseUnaryExpr();
      return t.val === "-" ? scaleAffine(-1, inner) : inner;
    }
    return this.parsePostfixExpr();
  }

  private parsePostfixExpr(): AffineMatrix {
    let val = this.parsePrimary();
    while (this.peek()?.type === "quote" || this.peek()?.type === "dotT") {
      this.consume();
      val = transposeAffine(val);
    }
    return val;
  }

  private parsePrimary(): AffineMatrix {
    const t = this.peek();
    if (!t) throw new Error("Expressão incompleta.");

    if (t.type === "num") {
      this.consume();
      return makeScalarAffine(Number(t.val));
    }

    if (t.type === "lparen") {
      this.consume();
      const inner = this.parseAddExpr();
      this.expect("rparen", "Esperado ')' para fechar parênteses");
      return inner;
    }

    if (t.type === "id") {
      const id = this.consume().val;

      // Function call: bmat(...), He(...), I(...), eye(...), zeros(...), trace(...), tr(...), inv(...)
      if (this.peek()?.type === "lparen") {
        return this.parseFunctionCall(id);
      }

      // Indexed symbol: X[i] or X[1]
      if (this.peek()?.type === "lbracket") {
        this.consume();
        const idxTokens: string[] = [];
        while (this.peek() && this.peek()!.type !== "rbracket") {
          const tok = this.consume();
          if (tok.type === "comma") continue;
          idxTokens.push(tok.val);
        }
        this.expect("rbracket", `Esperado ']' após índice de '${id}'`);
        const resolvedIndices = idxTokens.map((tok) => this.resolveIndexToken(tok));
        return this.resolveIndexedSymbol(id, resolvedIndices);
      }

      return this.resolvePlainSymbol(id);
    }

    throw new Error(`Token inesperado '${t.val}' na expressão.`);
  }

  private resolveIndexToken(tok: string): number {
    if (Object.prototype.hasOwnProperty.call(this.binding, tok)) {
      return this.binding[tok];
    }
    const n = Number(tok);
    if (Number.isInteger(n) && n >= 1) return n;
    throw new Error(`Índice '${tok}' não resolvido (fora de escopo 'forall').`);
  }

  private resolvePlainSymbol(id: string): AffineMatrix {
    if (id === "I") {
      return {
        rows: 1,
        cols: 1,
        constMat: new Float64Array([1]),
        terms: new Map<number, Float64Array>(),
        scalableIdentity: { constCoeff: 1, terms: new Map<number, number>() },
      };
    }
    if (Object.prototype.hasOwnProperty.call(this.binding, id)) {
      return makeScalarAffine(this.binding[id]);
    }
    if (this.paramMap.has(id)) {
      return makeScalarAffine(this.paramMap.get(id)!);
    }
    const v = this.varMap.get(id);
    if (v) return cloneAffine(v);

    const sysMat = this.lookupSystemMatrix(id, undefined);
    if (sysMat) return makeConstantAffine(sysMat, id);

    throw new Error(`Símbolo '${id}' não declarado (nem variável, nem parâmetro, nem matriz do sistema).`);
  }

  private resolveIndexedSymbol(id: string, indices: number[]): AffineMatrix {
    const key = `${id}[${indices.join(",")}]`;
    const v = this.varMap.get(key);
    if (v) return cloneAffine(v);

    if (indices.length === 1) {
      const sysMat = this.lookupSystemMatrix(id, indices[0]);
      if (sysMat) return makeConstantAffine(sysMat, key);
    }
    throw new Error(`Símbolo indexado '${key}' não encontrado.`);
  }

  private lookupSystemMatrix(id: string, vertexIndex1Based: number | undefined): number[][] | null {
    if (id === "dA" || id === "dC") {
      if (vertexIndex1Based === undefined) return null;
      const deltas = this.ctx.deltaVertices;
      if (!deltas || deltas.length === 0) {
        if (id === "dC") {
          const p = this.ctx.C.length;
          const n = this.ctx.A.length;
          return Array.from({ length: p }, () => Array(n).fill(0));
        }
        throw new Error(`deltaVertices não fornecido no contexto para '${id}[${vertexIndex1Based}]'.`);
      }
      if (vertexIndex1Based < 1 || vertexIndex1Based > deltas.length) {
        throw new Error(`Índice ${vertexIndex1Based} fora do intervalo 1..${deltas.length} para '${id}'.`);
      }
      const dv = deltas[vertexIndex1Based - 1];
      if (id === "dA") return dv.dA;
      if (dv.dC) return dv.dC;
      const p = this.ctx.C.length;
      const n = this.ctx.A.length;
      return Array.from({ length: p }, () => Array(n).fill(0));
    }

    const getFromSource = (
      src: Partial<LmiVertexMatrices> & Pick<LmiCompileContext, "Q_cost" | "R_cost">,
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
      const vert = this.ctx.vertices?.[vertexIndex1Based - 1];
      if (vert) {
        const fromVert = getFromSource(vert, id);
        if (fromVert) return fromVert;
      }
    }

    const fromNominal = getFromSource(this.ctx, id);
    if (fromNominal) return fromNominal;
    return null;
  }

  private parseFunctionCall(fnName: string): AffineMatrix {
    this.expect("lparen", `Esperado '(' após '${fnName}'`);
    if (fnName === "bmat") {
      return this.parseBmatCall();
    }

    const args: AffineMatrix[] = [];
    if (this.peek()?.type !== "rparen") {
      args.push(this.parseAddExpr());
      while (this.peek()?.type === "comma") {
        this.consume();
        args.push(this.parseAddExpr());
      }
    }
    this.expect("rparen", `Esperado ')' após argumentos de '${fnName}'`);

    const lower = fnName.toLowerCase();
    if (lower === "he") {
      if (args.length !== 1) throw new Error("He(X) requer exatamente 1 argumento.");
      const x = args[0];
      if (x.rows !== x.cols) {
        throw new Error(`He(X) requer matriz quadrada, recebido (${x.rows}×${x.cols}).`);
      }
      return addAffine(x, transposeAffine(x), 1);
    }
    if (lower === "trace" || lower === "tr") {
      if (args.length !== 1) throw new Error(`${fnName}(X) requer exatamente 1 argumento.`);
      return traceAffine(args[0]);
    }
    if (lower === "inv") {
      if (args.length !== 1) throw new Error("inv(X) requer exatamente 1 argumento.");
      return invertConstantMatrix(args[0]);
    }
    if (fnName === "I" || lower === "eye") {
      if (args.length === 0) return this.resolvePlainSymbol("I");
      if (args.length !== 1 || args[0].terms.size > 0) {
        throw new Error(`${fnName}(d) requer dimensão escalar constante.`);
      }
      const d = Math.round(args[0].constMat[0]);
      if (d < 1) throw new Error(`Dimensão inválida em ${fnName}(${d}).`);
      return makeIdentityAffine(d);
    }
    if (lower === "zeros") {
      if (args.length === 1 && args[0].terms.size === 0) {
        const d = Math.round(args[0].constMat[0]);
        return makeZeroAffine(d, d);
      }
      if (args.length === 2 && args[0].terms.size === 0 && args[1].terms.size === 0) {
        const r = Math.round(args[0].constMat[0]);
        const c = Math.round(args[1].constMat[0]);
        return makeZeroAffine(r, c);
      }
      throw new Error("zeros(r, c) requer dimensões constantes.");
    }
    throw new Error(`Função desconhecida '${fnName}' na expressão LMI.`);
  }

  private parseBmatCall(): AffineMatrix {
    this.expect("lbracket", "Esperado '[' dentro de bmat([...])");
    type CellEntry = { kind: "star" } | { kind: "expr"; val: AffineMatrix };
    const grid: CellEntry[][] = [];

    const parseCell = (): CellEntry => {
      if (this.peek()?.type === "star") {
        this.consume();
        return { kind: "star" };
      }
      return { kind: "expr", val: this.parseAddExpr() };
    };

    if (this.peek()?.type === "lbracket") {
      // Nested form: [[a, b], [c, d]]
      while (this.peek()?.type === "lbracket") {
        this.consume();
        const row: CellEntry[] = [];
        row.push(parseCell());
        while (this.peek()?.type === "comma") {
          this.consume();
          row.push(parseCell());
        }
        this.expect("rbracket", "Esperado ']' fechando linha de bmat");
        grid.push(row);
        if (this.peek()?.type === "comma") {
          this.consume();
        }
      }
    } else {
      // Semicolon-separated form: [a, b; c, d]
      let currentRow: CellEntry[] = [];
      currentRow.push(parseCell());
      while (this.peek()?.type === "comma" || this.peek()?.type === "semi") {
        const sep = this.consume();
        if (sep.type === "semi") {
          grid.push(currentRow);
          currentRow = [];
        }
        currentRow.push(parseCell());
      }
      grid.push(currentRow);
    }

    this.expect("rbracket", "Esperado ']' fechando bmat([...])");
    this.expect("rparen", "Esperado ')' fechando bmat(...)");

    const numRows = grid.length;
    if (numRows === 0) throw new Error("bmat() vazio.");
    const numCols = grid[0].length;
    for (let r = 0; r < numRows; r += 1) {
      if (grid[r].length !== numCols) {
        throw new Error(`Linha ${r + 1} de bmat() tem ${grid[r].length} colunas, esperado ${numCols}.`);
      }
    }

    const rowHeights: Array<number | null> = Array(numRows).fill(null);
    const colWidths: Array<number | null> = Array(numCols).fill(null);

    const setRowH = (r: number, h: number) => {
      if (rowHeights[r] !== null && rowHeights[r] !== h) {
        throw new Error(`Inconsistência de altura na linha ${r + 1} de bmat(): ${rowHeights[r]} vs ${h}.`);
      }
      rowHeights[r] = h;
    };
    const setColW = (c: number, w: number) => {
      if (colWidths[c] !== null && colWidths[c] !== w) {
        throw new Error(`Inconsistência de largura na coluna ${c + 1} de bmat(): ${colWidths[c]} vs ${w}.`);
      }
      colWidths[c] = w;
    };

    // Infer dimensions iteratively from concrete blocks and symmetric '*' mirrors
    for (let pass = 0; pass < numRows + numCols + 2; pass += 1) {
      for (let r = 0; r < numRows; r += 1) {
        for (let c = 0; c < numCols; c += 1) {
          const cell = grid[r][c];
          if (cell.kind === "expr") {
            const m = cell.val;
            if (m.scalarZero || m.scalableIdentity) {
              if (m.scalableIdentity) {
                if (rowHeights[r] !== null && colWidths[c] === null) setColW(c, rowHeights[r]!);
                if (colWidths[c] !== null && rowHeights[r] === null) setRowH(r, colWidths[c]!);
              }
              continue;
            }
            setRowH(r, m.rows);
            setColW(c, m.cols);
          } else {
            // '*' mirrors (c, r)
            if (r < numCols && c < numRows) {
              if (colWidths[r] !== null && rowHeights[r] === null) setRowH(r, colWidths[r]!);
              if (rowHeights[c] !== null && colWidths[c] === null) setColW(c, rowHeights[c]!);
              if (rowHeights[r] !== null && colWidths[r] === null) setColW(r, rowHeights[r]!);
              if (colWidths[c] !== null && rowHeights[c] === null) setRowH(c, colWidths[c]!);
            }
          }
        }
      }
    }

    for (let r = 0; r < numRows; r += 1) {
      if (rowHeights[r] === null) rowHeights[r] = 1;
    }
    for (let c = 0; c < numCols; c += 1) {
      if (colWidths[c] === null) colWidths[c] = 1;
    }

    const rH = rowHeights as number[];
    const cW = colWidths as number[];

    // Resolve all cells into concrete AffineMatrix
    const resolved: AffineMatrix[][] = Array.from({ length: numRows }, () => Array(numCols));
    for (let r = 0; r < numRows; r += 1) {
      for (let c = 0; c < numCols; c += 1) {
        const cell = grid[r][c];
        if (cell.kind === "expr") {
          const m = cell.val;
          if (m.scalarZero) {
            resolved[r][c] = makeZeroAffine(rH[r], cW[c]);
          } else if (m.scalableIdentity) {
            if (rH[r] !== cW[c]) {
              throw new Error(
                `Bloco (${r + 1},${c + 1}) de bmat() usa identidade I, mas dimensões inferidas são (${rH[r]}×${cW[c]}).`,
              );
            }
            resolved[r][c] = materializeScalableIdentity(m.scalableIdentity, rH[r]);
          } else {
            resolved[r][c] = m;
          }
        }
      }
    }

    for (let r = 0; r < numRows; r += 1) {
      for (let c = 0; c < numCols; c += 1) {
        if (grid[r][c].kind === "star") {
          if (c >= numRows || r >= numCols || !resolved[c][r]) {
            throw new Error(`Atalho '*' inválido em bmat() na posição (${r + 1}, ${c + 1}).`);
          }
          resolved[r][c] = transposeAffine(resolved[c][r]);
        }
      }
    }

    const totalRows = rH.reduce((acc, v) => acc + v, 0);
    const totalCols = cW.reduce((acc, v) => acc + v, 0);
    const out = makeZeroAffine(totalRows, totalCols);

    let rOffset = 0;
    for (let r = 0; r < numRows; r += 1) {
      let cOffset = 0;
      for (let c = 0; c < numCols; c += 1) {
        const blk = resolved[r][c];
        for (let br = 0; br < blk.rows; br += 1) {
          for (let bc = 0; bc < blk.cols; bc += 1) {
            out.constMat[(rOffset + br) * totalCols + (cOffset + bc)] = blk.constMat[br * blk.cols + bc];
          }
        }
        for (const [k, arr] of blk.terms.entries()) {
          let target = out.terms.get(k);
          if (!target) {
            target = new Float64Array(totalRows * totalCols);
            out.terms.set(k, target);
          }
          for (let br = 0; br < blk.rows; br += 1) {
            for (let bc = 0; bc < blk.cols; bc += 1) {
              target[(rOffset + br) * totalCols + (cOffset + bc)] = arr[br * blk.cols + bc];
            }
          }
        }
        cOffset += cW[c];
      }
      rOffset += rH[r];
    }
    return out;
  }
}

export function serializeCanonicalSdpForJson(
  problem: CanonicalSDPProblemJson,
): Record<string, unknown> {
  return {
    ...problem,
    blocks: problem.blocks.map((blk) => {
      if (!blk.F_k_packed) {
        return { ...blk };
      }
      return {
        ...blk,
        F_k_packed: {
          k_idx: Array.from(blk.F_k_packed.k_idx),
          rows: Array.from(blk.F_k_packed.rows),
          cols: Array.from(blk.F_k_packed.cols),
          vals: Array.from(blk.F_k_packed.vals),
        },
      };
    }),
  };
}

export function compileLmiDslToCanonicalSdp(
  parsed: LmiDslParseResult,
  ctx: LmiCompileContext,
  options?: LmiCompileOptions,
): LmiCompileResult {
  const blockFormat: LmiSdpBlockFormat = options?.format ?? ctx.format ?? "packed";
  if (!parsed.valid) {
    throw new Error(parsed.errors[0]?.message ?? "DSL LMI inválida para compilação.");
  }
  if (parsed.bilinearWarnings.length > 0) {
    throw new Error(parsed.bilinearWarnings[0].message);
  }

  const n = ctx.A.length;
  const m = ctx.B[0]?.length ?? 1;
  const p = ctx.C.length;
  const nw = ctx.Bw?.[0]?.length ?? ctx.Dzw?.[0]?.length ?? 1;
  const nz = ctx.Cz?.length ?? ctx.Dzu?.length ?? ctx.Dzw?.length ?? p;
  const dims = { n, m, p, nw, nz };

  const paramMap = new Map<string, number>();
  for (const prm of parsed.params) {
    paramMap.set(prm.name, prm.value);
  }
  if (ctx.params) {
    for (const [k, v] of Object.entries(ctx.params)) {
      if (Number.isFinite(v)) paramMap.set(k, v);
    }
  }

  const strictMargin = ctx.strictMargin ?? paramMap.get("eps") ?? 1e-4;
  const systemN = Math.max(1, ctx.vertices?.length ?? parsed.effectiveSystemN);
  const deltaN = Math.max(1, ctx.deltaVertices?.length ?? systemN);
  const indexRanges = new Map<string, { start: number; end: number }>();
  for (const decl of parsed.indices) {
    let resolvedEnd: number;
    if (/^\d+$/.test(decl.rangeEndExpr)) {
      resolvedEnd = decl.resolvedEnd;
    } else if (decl.rangeEndExpr.toUpperCase() === "K" && ctx.deltaVertices && ctx.deltaVertices.length > 0) {
      resolvedEnd = deltaN;
    } else if (paramMap.has(decl.rangeEndExpr)) {
      resolvedEnd = Math.round(paramMap.get(decl.rangeEndExpr)!);
    } else {
      resolvedEnd = systemN;
    }
    indexRanges.set(decl.name, { start: decl.rangeStart, end: Math.max(decl.rangeStart, resolvedEnd) });
  }

  // Allocate decision variables
  const variableMap: Record<string, CanonicalVariableMapEntry> = {};
  const varAffines = new Map<string, AffineMatrix>();
  const variableNames: string[] = [];
  let offset = 0;
  let nextVarId = 0;

  const allocateSingleVar = (varName: string, spec: LmiDslVariable) => {
    let rows = 1;
    let cols = 1;
    let symmetric = false;
    const coords: [number, number][] = [];

    if (spec.kind === "sym") {
      const d = resolveDimToken(spec.rowsExpr, dims, paramMap);
      rows = d;
      cols = d;
      symmetric = true;
      for (let i = 0; i < d; i += 1) {
        for (let j = i; j < d; j += 1) {
          coords.push([i, j]);
        }
      }
    } else if (spec.kind === "rect") {
      rows = resolveDimToken(spec.rowsExpr, dims, paramMap);
      cols = resolveDimToken(spec.colsExpr, dims, paramMap);
      symmetric = false;
      for (let i = 0; i < rows; i += 1) {
        for (let j = 0; j < cols; j += 1) {
          coords.push([i, j]);
        }
      }
    } else {
      rows = 1;
      cols = 1;
      symmetric = true;
      coords.push([0, 0]);
    }

    const size = coords.length;
    variableMap[varName] = {
      name: varName,
      var_id: nextVarId,
      shape: [rows, cols],
      symmetric,
      offset,
      size,
      coords,
    };
    variableNames.push(varName);
    nextVarId += 1;

    const aff = makeZeroAffine(rows, cols);
    for (let k = 0; k < size; k += 1) {
      const [r, c] = coords[k];
      const basis = new Float64Array(rows * cols);
      basis[r * cols + c] = 1.0;
      if (symmetric && r !== c) {
        basis[c * cols + r] = 1.0;
      }
      aff.terms.set(offset + k, basis);
    }
    varAffines.set(varName, aff);
    offset += size;
  };

  for (const v of parsed.variables) {
    if (v.indexedBy && v.indexedBy.length > 0) {
      if (v.indexedBy.length === 1) {
        const r = indexRanges.get(v.indexedBy[0]) ?? { start: 1, end: systemN };
        for (let idx = r.start; idx <= r.end; idx += 1) {
          allocateSingleVar(`${v.name}[${idx}]`, v);
        }
      } else {
        const r0 = indexRanges.get(v.indexedBy[0]) ?? { start: 1, end: systemN };
        const r1 = indexRanges.get(v.indexedBy[1]) ?? { start: 1, end: systemN };
        for (let i = r0.start; i <= r0.end; i += 1) {
          for (let j = r1.start; j <= r1.end; j += 1) {
            allocateSingleVar(`${v.name}[${i},${j}]`, v);
          }
        }
      }
    } else {
      allocateSingleVar(v.name, v);
    }
  }

  const nVars = offset;
  if (nVars < 1) {
    throw new Error("Nenhuma variável de decisão declarada na DSL LMI.");
  }

  const evalExpr = (expr: string, binding: Record<string, number>): AffineMatrix => {
    const ev = new ExprEvaluator(expr, binding, ctx, varAffines, paramMap, systemN);
    return ev.parseTopExpr();
  };

  // Objective
  const cVec = new Float64Array(nVars);
  let c0 = 0;
  if (parsed.objective) {
    const objAff = evalExpr(parsed.objective.expr, {});
    if (objAff.rows !== 1 || objAff.cols !== 1 || objAff.scalableIdentity) {
      throw new Error(`Função objetivo '${parsed.objective.expr}' deve ser escalar.`);
    }
    const sign = parsed.objective.sense === "maximize" ? -1 : 1;
    c0 = sign * objAff.constMat[0];
    for (const [k, arr] of objAff.terms.entries()) {
      cVec[k] = sign * arr[0];
    }
  }

  // Constraints -> PSD blocks
  const blocks: CanonicalSDPBlockJson[] = [];
  let blockCounter = 0;
  let originalBlocks = 0;
  let eliminatedSymmetricPairs = 0;

  for (const con of parsed.constraints) {
    const bindings = expandQuantifierBindings(con.quantifier, systemN, indexRanges);

    // Check if eligible for automatic symmetric double-sum fusion (Tuan et al. 2001; Sala & Ariño 2007):
    // Doubly-quantified constraint (v0, v1) with identical index bounds and no asymmetric guard.
    let canCheckSymmetricFusion = false;
    let symVar0 = "";
    let symVar1 = "";
    if (con.quantifier && con.quantifier.vars.length === 2 && !con.quantifier.condition) {
      const [v0, v1] = con.quantifier.vars;
      const r0 = indexRanges.get(v0) ?? { start: 1, end: systemN };
      const r1 = indexRanges.get(v1) ?? { start: 1, end: systemN };
      if (r0.start === r1.start && r0.end === r1.end && r0.end > r0.start) {
        canCheckSymmetricFusion = true;
        symVar0 = v0;
        symVar1 = v1;
      }
    }
    const upperTriangleCache = canCheckSymmetricFusion ? new Map<string, AffineMatrix>() : null;

    for (const binding of bindings) {
      const lhs = evalExpr(con.lhsRaw, binding);
      const rhs = evalExpr(con.rhsRaw, binding);

      let diff: AffineMatrix;
      if (con.operator === "<" || con.operator === "<=") {
        diff = addAffine(rhs, lhs, -1);
      } else if (con.operator === ">" || con.operator === ">=") {
        diff = addAffine(lhs, rhs, -1);
      } else {
        // '==' -> two PSD blocks diff >= 0 and -diff >= 0
        diff = addAffine(lhs, rhs, -1);
      }

      if (diff.scalableIdentity || diff.scalarZero) {
        throw new Error(`Restrição na linha ${con.line} não possui dimensão matricial definida.`);
      }
      if (diff.rows !== diff.cols) {
        throw new Error(
          `Restrição LMI na linha ${con.line} deve ser quadrada, obtido (${diff.rows}×${diff.cols}).`,
        );
      }

      const blocksForThisBinding = con.operator === "==" ? 2 : 1;
      originalBlocks += blocksForThisBinding;

      if (upperTriangleCache) {
        const iVal = binding[symVar0];
        const jVal = binding[symVar1];
        if (iVal < jVal) {
          upperTriangleCache.set(`${iVal},${jVal}`, diff);
        } else if (iVal > jVal) {
          const mirrorDiff = upperTriangleCache.get(`${jVal},${iVal}`);
          if (mirrorDiff && areSymmetrizedAffinesEqual(diff, mirrorDiff)) {
            eliminatedSymmetricPairs += 1;
            continue;
          }
        }
      }

      const dim = diff.rows;
      const pushBlock = (matAff: AffineMatrix, suffix: string) => {
        const f0 = new Float64Array(matAff.constMat);
        if (con.isStrict) {
          for (let d = 0; d < dim; d += 1) {
            f0[d * dim + d] -= strictMargin;
          }
        }
        symmetrizeSquareInPlace(f0, dim);

        const bindTag = Object.entries(binding)
          .map(([k, v]) => `${k}=${v}`)
          .join(",");
        const blkName = `lmi_${blockCounter}${bindTag ? `_${bindTag}` : ""}${suffix}`;
        blockCounter += 1;

        const sortedKs = Array.from(matAff.terms.keys()).sort((a, b) => a - b);

        if (blockFormat === "packed") {
          let cap = Math.max(16, sortedKs.length * dim);
          let kBuf = new Int32Array(cap);
          let rBuf = new Int32Array(cap);
          let cBuf = new Int32Array(cap);
          let vBuf = new Float64Array(cap);
          let nnz = 0;

          const ensureCap = (needed: number): void => {
            if (needed <= cap) return;
            let nextCap = cap;
            while (nextCap < needed) nextCap *= 2;
            const nk = new Int32Array(nextCap);
            nk.set(kBuf.subarray(0, nnz));
            kBuf = nk;
            const nr = new Int32Array(nextCap);
            nr.set(rBuf.subarray(0, nnz));
            rBuf = nr;
            const nc = new Int32Array(nextCap);
            nc.set(cBuf.subarray(0, nnz));
            cBuf = nc;
            const nv = new Float64Array(nextCap);
            nv.set(vBuf.subarray(0, nnz));
            vBuf = nv;
            cap = nextCap;
          };

          for (let ki = 0; ki < sortedKs.length; ki += 1) {
            const k = sortedKs[ki];
            const term = matAff.terms.get(k)!;
            for (let r = 0; r < dim; r += 1) {
              const rOff = r * dim;
              for (let c = 0; c < dim; c += 1) {
                const val =
                  r === c
                    ? term[rOff + c]
                    : 0.5 * (term[rOff + c] + term[c * dim + r]);
                if (Math.abs(val) > 0) {
                  ensureCap(nnz + 1);
                  kBuf[nnz] = k;
                  rBuf[nnz] = r;
                  cBuf[nnz] = c;
                  vBuf[nnz] = val;
                  nnz += 1;
                }
              }
            }
          }

          const k_idx = nnz === kBuf.length ? kBuf : kBuf.slice(0, nnz);
          const rows = nnz === rBuf.length ? rBuf : rBuf.slice(0, nnz);
          const cols = nnz === cBuf.length ? cBuf : cBuf.slice(0, nnz);
          const vals = nnz === vBuf.length ? vBuf : vBuf.slice(0, nnz);

          blocks.push({
            name: blkName,
            dim,
            n_vars: nVars,
            F0: float64ToTensor2D(f0, dim, dim),
            F_k_packed: { k_idx, rows, cols, vals },
          });
        } else if (blockFormat === "sparse") {
          const f_k_sparse: Record<string, [number, number, number][]> = {};
          for (let ki = 0; ki < sortedKs.length; ki += 1) {
            const k = sortedKs[ki];
            const term = matAff.terms.get(k)!;
            const entries: [number, number, number][] = [];
            for (let r = 0; r < dim; r += 1) {
              const rOff = r * dim;
              for (let c = 0; c < dim; c += 1) {
                const val =
                  r === c
                    ? term[rOff + c]
                    : 0.5 * (term[rOff + c] + term[c * dim + r]);
                if (Math.abs(val) > 0) {
                  entries.push([r, c, val]);
                }
              }
            }
            if (entries.length > 0) {
              f_k_sparse[String(k)] = entries;
            }
          }
          blocks.push({
            name: blkName,
            dim,
            n_vars: nVars,
            F0: float64ToTensor2D(f0, dim, dim),
            F_k_sparse: f_k_sparse,
          });
        } else {
          const f_k: CanonicalTensor2D[] = [];
          for (let k = 0; k < nVars; k += 1) {
            const term = matAff.terms.get(k);
            const sym = new Float64Array(dim * dim);
            if (term) {
              for (let r = 0; r < dim; r += 1) {
                const rOff = r * dim;
                for (let c = 0; c < dim; c += 1) {
                  sym[rOff + c] =
                    r === c
                      ? term[rOff + c]
                      : 0.5 * (term[rOff + c] + term[c * dim + r]);
                }
              }
            }
            f_k.push(float64ToTensor2D(sym, dim, dim));
          }
          blocks.push({
            name: blkName,
            dim,
            n_vars: nVars,
            F0: float64ToTensor2D(f0, dim, dim),
            F_k: f_k,
          });
        }
      };

      pushBlock(diff, "");
      if (con.operator === "==") {
        pushBlock(scaleAffine(-1, diff), "_eq_neg");
      }
    }
  }

  if (blocks.length === 0) {
    throw new Error("Nenhuma restrição LMI compilada.");
  }

  const problem: CanonicalSDPProblemJson = {
    name: ctx.name ?? `dsl_${parsed.inferredTemplate}`,
    n_vars: nVars,
    c: {
      shape: [nVars],
      dtype: "float64",
      order: "C",
      data: Array.from(cVec),
    },
    c0,
    blocks,
    variable_map: variableMap,
    recovery_plan: null,
  };

  return {
    problem,
    nVars,
    blockCount: blocks.length,
    variableNames,
    fusionStats: {
      originalBlocks,
      fusedBlocks: blocks.length,
      eliminatedSymmetricPairs,
    },
  };
}
