/**
 * Parser declarativo determinístico para DSL LMI/SDP v2.0 (Tab 6 — `WP-LMI-V2-01-DSL-PARSER-QUANTIFIERS`)
 * seguindo CL-LMI-DSL-DIR-001 v1.0.0, CL-UX-DIR-001 v1.0.0 Seção 4.6 e CL-DIR-001 Seção 5.7 / ADR-010.
 *
 * Segurança:
 * - Analisador léxico/sintático 100% puro e determinístico em TypeScript.
 * - Estritamente SEM execução dinâmica de código, preservando `IMPORT_UNTRUSTED_CODE`.
 *
 * Funcionalidades v1.0 + v2.0:
 * - Declarações de sistema `system lti|polytopic|ts ...` e índices `index i in 1..N`.
 * - Declarações `var Q sym(n)`, `var P[i] sym(n)`, `var Y[i] rect(m, n)`, `var gamma scalar`, `param alpha = 0.5`.
 * - Macros determinísticas `macro M(i, j) = <expr>` com expansão segura em expressões.
 * - Operador `He(X)` e atalho de simetria `*` em blocos `bmat([[...], [...]])` ou `bmat([...; ...])`.
 * - Quantificadores estruturados `forall i:`, `forall i, j:`, `forall i, j where j > i:` com contagem exata de blocos expandidos.
 * - Matrizes de planta generalizada (`Bw, Dyw, Cz, Dzu, Dzw`) e indexadas (`A[i], B[i], Bw[i], ...`).
 * - Geradores determinísticos de scripts CVXPY e YALMIP com laços `for` para problemas quantificados.
 */

import { escapeHtml } from "../../app/accessibility.ts";

export type LmiBackendTemplateId =
  | "decay_rate"
  | "quadratic_stabilization"
  | "regional_pole_placement"
  | "hinf_brl"
  | "lqr_lmi"
  | "ts_pdc_stabilization"
  | "polytopic_robust"
  | "ts_pdc_relaxed"
  | "hinf_generalized_brl"
  | "canonical_sdp_json";

export interface LmiDslSystemSpec {
  systemClass: "lti" | "polytopic" | "ts";
  nCount: number | null;
  indices: string[];
  premises: "measured" | "unmeasured" | null;
  generalized: boolean;
  line: number;
}

export interface LmiDslIndexDecl {
  name: string;
  rangeStart: number;
  rangeEndExpr: string;
  resolvedEnd: number;
  line: number;
}

export interface LmiDslMacro {
  name: string;
  params: string[];
  body: string;
  line: number;
}

export interface LmiDslQuantifier {
  vars: string[];
  condition: string | null;
  cardinality: number;
  mathPrefix: string;
}

export interface LmiDslVariable {
  name: string;
  kind: "sym" | "rect" | "scalar";
  rowsExpr: string;
  colsExpr: string;
  shapeLabel: string;
  indexedBy?: string[];
  line: number;
}

export interface LmiDslParam {
  name: string;
  value: number;
  line: number;
}

export interface LmiDslConstraint {
  index: number;
  line: number;
  raw: string;
  operator: "<" | "<=" | ">" | ">=" | "==";
  isStrict: boolean;
  lhsRaw: string;
  rhsRaw: string;
  bmatRows: string[][] | null;
  quantifier?: LmiDslQuantifier;
  mathText: string;
  mathHtml: string;
}

export interface LmiDslRecovery {
  line: number;
  lhs: string;
  rhs: string;
  quantifier?: LmiDslQuantifier;
  mathText: string;
}

export interface LmiDslBilinearWarning {
  line: number;
  token: string;
  message: string;
  suggestion: string;
}

export interface LmiDslParseError {
  line: number;
  message: string;
}

export interface LmiDslParseOptions {
  systemClass?: "lti" | "polytopic" | "ts";
  systemN?: number;
  deltaCount?: number;
  indexName?: string;
  extraIndices?: string[];
  premisesMeasured?: boolean;
  generalized?: boolean;
}

export interface LmiDslParseResult {
  valid: boolean;
  lineCount: number;
  systemSpec: LmiDslSystemSpec | null;
  indices: LmiDslIndexDecl[];
  macros: LmiDslMacro[];
  effectiveSystemN: number;
  expandedBlockCount: number;
  variables: LmiDslVariable[];
  params: LmiDslParam[];
  objective: { sense: "minimize" | "maximize"; expr: string; mathText: string } | null;
  constraints: LmiDslConstraint[];
  recoveries: LmiDslRecovery[];
  bilinearWarnings: LmiDslBilinearWarning[];
  strictConeNotes: string[];
  errors: LmiDslParseError[];
  inferredTemplate: LmiBackendTemplateId;
  inferredAlpha: number | null;
  inferredRadius: number | null;
  inferredGamma: number | null;
  inferredFeedbackSign: "positive" | "negative";
  canonicalSdpOverride: Record<string, unknown> | null;
}

export interface LmiTemplatePreset {
  id: LmiBackendTemplateId;
  label: string;
  description: string;
  dsl: string;
}

export interface LmiQuantifiedExportContext {
  systemClass: "lti" | "polytopic" | "ts";
  n: number;
  m: number;
  p: number;
  systemN: number;
  generalized?: boolean;
  premisesMeasured?: boolean;
}

export const LMI_DSL_TEMPLATES: readonly LmiTemplatePreset[] = [
  {
    id: "decay_rate",
    label: "Decaimento α + Estabilização",
    description: "Estabilização quadrática com taxa exponencial Re(λ) < -α (u = +Kx).",
    dsl: [
      "# Template inicial: Estabilização quadrática com decaimento α",
      "# Edite os parâmetros ou condições LMI abaixo",
      "var Q sym(n)",
      "var Y rect(m, n)",
      "param alpha = 0.5",
      "Q > 0",
      "A*Q + Q*A' + B*Y + Y'*B' + 2*alpha*Q < 0",
      "recover K = Y * inv(Q)",
    ].join("\n"),
  },
  {
    id: "quadratic_stabilization",
    label: "Estabilização Quadrática (α = 0)",
    description: "Garante existência de Lyapunov quadrática V(x) = xᵀ P x.",
    dsl: [
      "# Estabilização quadrática clássica (α = 0)",
      "var Q sym(n)",
      "var Y rect(m, n)",
      "Q > 0",
      "A*Q + Q*A' + B*Y + Y'*B' < 0",
      "recover K = Y * inv(Q)",
    ].join("\n"),
  },
  {
    id: "regional_pole_placement",
    label: "Alocação Regional (Disco r + Semiplano α)",
    description: "D-estabilidade combinando disco |λ| < r e decaimento Re(λ) < -α.",
    dsl: [
      "# Região LMI: Disco de raio r e semiplano Re(λ) < -α",
      "var Q sym(n)",
      "var Y rect(m, n)",
      "param radius = 5.0",
      "param alpha = 0.4",
      "Q > 0",
      "bmat([[-radius*Q, A*Q + B*Y], [(A*Q + B*Y)', -radius*Q]]) < 0",
      "A*Q + Q*A' + B*Y + Y'*B' + 2*alpha*Q < 0",
      "recover K = Y * inv(Q)",
    ].join("\n"),
  },
  {
    id: "lqr_lmi",
    label: "LQR via LMI (Complemento de Schur)",
    description: "Custo quadrático garantido com matrizes de peso Q_cost e R_cost.",
    dsl: [
      "# Síntese LQR via Complemento de Schur (u = -Kx)",
      "var Q sym(n)",
      "var Y rect(m, n)",
      "Q > 0",
      "bmat([[A*Q + Q*A' - B*Y - Y'*B', Q, Y'], [Q, -inv(Q_cost), 0], [Y, 0, -inv(R_cost)]]) < 0",
      "recover K = Y * inv(Q)",
    ].join("\n"),
  },
  {
    id: "hinf_brl",
    label: "Síntese H∞ (Bounded Real Lemma)",
    description: "Minimização da norma H∞ ||T_zw||_∞ < γ via BRL clássico.",
    dsl: [
      "# Bounded Real Lemma H∞ (minimiza γ)",
      "var Q sym(n)",
      "var Y rect(m, n)",
      "var gamma scalar",
      "minimize gamma",
      "Q > 0",
      "gamma > 0",
      "bmat([[A*Q + Q*A' + B2*Y + Y'*B2', B1, (C1*Q + D12*Y)'], [B1', -gamma*I, D11'], [C1*Q + D12*Y, D11, -gamma*I]]) < 0",
      "recover K = Y * inv(Q)",
    ].join("\n"),
  },
  {
    id: "hinf_generalized_brl",
    label: "Síntese H∞ (Planta Generalizada v2.0)",
    description: "BRL com canais exógeno (Bw) e desempenho (Cz, Dzu, Dzw) + simetria *.",
    dsl: [
      "# Síntese H∞ via Planta Generalizada (canal w e z)",
      "system lti generalized=true",
      "var Q sym(n)",
      "var Y rect(m, n)",
      "var gamma_sq scalar",
      "minimize gamma_sq",
      "Q > 0",
      "gamma_sq > 0",
      "bmat([He(A*Q + B*Y), Bw, (Cz*Q + Dzu*Y)'; *, -gamma_sq*I, Dzw'; *, *, -I]) < 0",
      "recover K = Y * inv(Q)",
    ].join("\n"),
  },
  {
    id: "polytopic_robust",
    label: "Politópico Robusto (∀ i vértices v2.0)",
    description: "Estabilização quadrática robusta sobre politopo convexo de N vértices.",
    dsl: [
      "# Síntese Robusta Politópica (Lyapunov comum Q > 0)",
      "system polytopic vertices=2 index=i",
      "var Q sym(n)",
      "var Y rect(m, n)",
      "Q > 0",
      "forall i:",
      "  He(A[i]*Q + B[i]*Y) < 0",
      "recover K = Y * inv(Q)",
    ].join("\n"),
  },
  {
    id: "ts_pdc_stabilization",
    label: "Takagi-Sugeno PDC (Tanaka-Wang)",
    description: "Síntese PDC para modelo TSStateSpace (ts_measured) selecionado no Workspace.",
    dsl: [
      "# Síntese PDC Takagi-Sugeno (expansão dupla i=j e i<j)",
      "var Q sym(n)",
      "var Y_i rect(m, n)",
      "param alpha = 0.2",
      "Q > 0",
      "A_i*Q + Q*A_i' + B_i*Y_i + Y_i'*B_i' + 2*alpha*Q < 0",
      "recover K_i = Y_i * inv(Q)",
    ].join("\n"),
  },
  {
    id: "ts_pdc_relaxed",
    label: "Takagi-Sugeno PDC Relaxado (∀ i, ∀ j > i v2.0)",
    description: "Condição PDC relaxada de Tuan/Tanaka com macro M(i, j) e quantificadores.",
    dsl: [
      "# Síntese PDC Takagi-Sugeno Relaxada (DSL v2.0)",
      "system ts rules=2 index=i,j premises=measured",
      "var Q sym(n)",
      "var Y[i] rect(m, n)",
      "Q > 0",
      "macro M(i, j) = A[i]*Q + Q*A[i]' + B[i]*Y[j] + Y[j]'*B[i]'",
      "forall i:",
      "  M(i, i) < 0",
      "forall i, j where j > i:",
      "  M(i, j) + M(j, i) < 0",
      "forall i:",
      "  recover K[i] = Y[i] * inv(Q)",
    ].join("\n"),
  },
  {
    id: "canonical_sdp_json",
    label: "Problema SDP Canônico (JSON Direto)",
    description: "Especificação direta de CanonicalSDPProblem em JSON.",
    dsl: JSON.stringify(
      {
        name: "sdp_scalar_min",
        sense: "minimize",
        c: [1.0],
        blocks: [
          {
            F0: [[-2.0]],
            F_terms: { "0": [[1.0]] },
          },
        ],
        eq: { E: [], f: [] },
        ineq: { H: [], g: [] },
      },
      null,
      2,
    ),
  },
];

const SUBSCRIPT_MAP: Record<string, string> = {
  "0": "₀",
  "1": "₁",
  "2": "₂",
  "3": "₃",
  "4": "₄",
  "5": "₅",
  "6": "₆",
  "7": "₇",
  "8": "₈",
  "9": "₉",
  i: "ᵢ",
  j: "ⱼ",
  k: "ₖ",
  l: "ₗ",
  m: "ₘ",
  n: "ₙ",
  p: "ₚ",
  r: "ᵣ",
  s: "ₛ",
  t: "ₜ",
  u: "ᵤ",
  v: "ᵥ",
  x: "ₓ",
};

function toUnicodeSubscript(raw: string): string {
  const cleaned = raw.replace(/\s+/g, "");
  let out = "";
  for (const ch of cleaned) {
    out += SUBSCRIPT_MAP[ch] ?? ch;
  }
  return out;
}

function stripLineComment(line: string): string {
  const hashIdx = line.indexOf("#");
  const slashIdx = line.indexOf("//");
  let cut = line.length;
  if (hashIdx >= 0) cut = Math.min(cut, hashIdx);
  if (slashIdx >= 0) cut = Math.min(cut, slashIdx);
  return line.slice(0, cut).trim();
}

function getIndentWidth(rawLine: string): number {
  let width = 0;
  for (const ch of rawLine) {
    if (ch === " ") width += 1;
    else if (ch === "\t") width += 2;
    else break;
  }
  return width;
}

function splitTopLevelDelimiter(text: string, delimiter: string): string[] {
  const parts: string[] = [];
  let depthParen = 0;
  let depthBracket = 0;
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === "(") depthParen += 1;
    else if (ch === ")") depthParen = Math.max(0, depthParen - 1);
    else if (ch === "[") depthBracket += 1;
    else if (ch === "]") depthBracket = Math.max(0, depthBracket - 1);
    else if (ch === delimiter && depthParen === 0 && depthBracket === 0) {
      const piece = text.slice(start, i).trim();
      if (piece.length > 0) parts.push(piece);
      start = i + 1;
    }
  }
  const tail = text.slice(start).trim();
  if (tail.length > 0) parts.push(tail);
  return parts;
}

function extractBmatRows(lhsRaw: string): string[][] | null {
  const trimmed = lhsRaw.trim();
  const match = /^bmat\s*\(\s*\[([\s\S]*)\]\s*\)$/i.exec(trimmed);
  if (!match) return null;
  const inner = match[1].trim();
  if (inner.length === 0) return null;

  // Support semicolon-separated rows: bmat([M11, M12; *, M22])
  const semicolonRows = splitTopLevelDelimiter(inner, ";");
  if (semicolonRows.length > 1) {
    const rows: string[][] = [];
    for (const rStr of semicolonRows) {
      const rs = rStr.trim();
      const unwrapped = rs.startsWith("[") && rs.endsWith("]") ? rs.slice(1, -1) : rs;
      const cells = splitTopLevelDelimiter(unwrapped, ",");
      if (cells.length === 0) return null;
      rows.push(cells);
    }
    return rows;
  }

  // Standard nested list: bmat([[M11, M12], [*, M22]])
  const rowStrings = splitTopLevelDelimiter(inner, ",");
  if (rowStrings.length === 0) return null;

  const rows: string[][] = [];
  for (const rStr of rowStrings) {
    const rs = rStr.trim();
    if (!rs.startsWith("[") || !rs.endsWith("]")) {
      return null;
    }
    const cells = splitTopLevelDelimiter(rs.slice(1, -1), ",");
    if (cells.length === 0) return null;
    rows.push(cells);
  }
  return rows;
}

export function formatLmiMathExpression(expr: string): string {
  const trimmed = expr.trim();
  if (trimmed === "*") return "*";

  let out = trimmed;
  // Replace inv(X) -> X⁻¹ (handles single identifier or indexed identifier)
  out = out.replace(/\binv\s*\(\s*([A-Za-z0-9_]+(?:\[[A-Za-z0-9_,\s]+\])?)\s*\)/g, "$1⁻¹");
  // Replace trace(X) -> tr(X)
  out = out.replace(/\btrace\s*\(/g, "tr(");
  // Generalized plant matrices -> clean subscripted labels
  out = out.replace(/\bBw\b/g, "B_w");
  out = out.replace(/\bDyw\b/g, "D_yw");
  out = out.replace(/\bCz\b/g, "C_z");
  out = out.replace(/\bDzu\b/g, "D_zu");
  out = out.replace(/\bDzw\b/g, "D_zw");
  // Indexed symbols: A[i] -> Aᵢ, B_w[i] -> B_wᵢ, Y[j] -> Yⱼ
  out = out.replace(/([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([A-Za-z0-9_,\s]+)\s*\]/g, (_m, sym: string, idx: string) => {
    return `${sym}${toUnicodeSubscript(idx)}`;
  });
  // Replace transpose markers: .T and '
  out = out.replace(/\.T\b/g, "ᵀ");
  out = out.replace(/'/g, "ᵀ");
  // Greek identifiers
  out = out.replace(/\bgamma_sq\b/g, "γ²");
  out = out.replace(/\balpha\b/g, "α");
  out = out.replace(/\bgamma\b/g, "γ");
  out = out.replace(/\blambda\b/g, "λ");
  out = out.replace(/\beps(?:ilon)?\b/g, "ε");
  // Multiplication spacing: keep readability without noisy asterisks (except standalone *)
  out = out.replace(/\s*[@*]\s*/g, " ");
  out = out.replace(/\s+/g, " ").trim();
  return out;
}

function operatorToMathSymbol(op: LmiDslConstraint["operator"]): string {
  switch (op) {
    case "<":
      return "≺";
    case "<=":
      return "≼";
    case ">":
      return "≻";
    case ">=":
      return "≽";
    case "==":
      return "=";
  }
}

export function resolveShapeLabel(
  variable: LmiDslVariable,
  dims?: { n?: number; m?: number; p?: number; nw?: number; nz?: number },
): string {
  const idxSuffix = variable.indexedBy && variable.indexedBy.length > 0
    ? ` [${variable.indexedBy.join(",")}]`
    : "";
  if (variable.kind === "scalar") return `scalar (1×1)${idxSuffix}`;
  const sub = (token: string): string => {
    const t = token.trim();
    if (t === "n" && dims?.n !== undefined) return String(dims.n);
    if (t === "m" && dims?.m !== undefined) return String(dims.m);
    if (t === "p" && dims?.p !== undefined) return String(dims.p);
    if (t === "nw" && dims?.nw !== undefined) return String(dims.nw);
    if (t === "nz" && dims?.nz !== undefined) return String(dims.nz);
    return t;
  };
  const r = sub(variable.rowsExpr);
  const c = sub(variable.colsExpr);
  const base = variable.kind === "sym" ? `sym(${r}×${c})` : `rect(${r}×${c})`;
  return `${base}${idxSuffix}`;
}

function expandMacrosInExpr(
  expr: string,
  macros: ReadonlyMap<string, LmiDslMacro>,
  depth = 0,
): string {
  if (macros.size === 0 || depth >= 8) return expr;
  let result = "";
  let i = 0;
  let changed = false;

  while (i < expr.length) {
    const rest = expr.slice(i);
    const callStart = /^([A-Za-z_][A-Za-z0-9_]*)\s*\(/.exec(rest);
    if (callStart) {
      const fnName = callStart[1];
      const macro = macros.get(fnName);
      if (macro) {
        const openIdx = i + callStart[0].length - 1;
        let depthParen = 1;
        let closeIdx = openIdx + 1;
        while (closeIdx < expr.length && depthParen > 0) {
          if (expr[closeIdx] === "(") depthParen += 1;
          else if (expr[closeIdx] === ")") depthParen -= 1;
          closeIdx += 1;
        }
        if (depthParen === 0) {
          const argsRaw = expr.slice(openIdx + 1, closeIdx - 1);
          const args = splitTopLevelDelimiter(argsRaw, ",");
          if (args.length === macro.params.length) {
            let expandedBody = macro.body;
            for (let pIdx = 0; pIdx < macro.params.length; pIdx += 1) {
              const paramName = macro.params[pIdx];
              const argVal = args[pIdx];
              const pRe = new RegExp(`\\b${paramName}\\b`, "g");
              expandedBody = expandedBody.replace(pRe, argVal);
            }
            result += `(${expandedBody})`;
            i = closeIdx;
            changed = true;
            continue;
          }
        }
      }
    }
    result += expr[i];
    i += 1;
  }

  return changed ? expandMacrosInExpr(result, macros, depth + 1) : result;
}

function detectBilinearTerms(
  expr: string,
  declaredVars: ReadonlySet<string>,
  lineNum: number,
): LmiDslBilinearWarning[] {
  const warnings: LmiDslBilinearWarning[] = [];
  const seenTokens = new Set<string>();
  // Strip index brackets [i] before tokenizing so K[i]*Q -> K*Q and A[i]*Q -> A*Q
  const stripped = expr.replace(/\[[^\]]+\]/g, "");
  const tokenRe = /[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[*@^/]/g;
  const tokens: Array<{ type: "id" | "num" | "op"; val: string }> = [];
  let m: RegExpExecArray | null;
  while ((m = tokenRe.exec(stripped)) !== null) {
    const raw = m[0];
    if (raw === "*" || raw === "@" || raw === "^" || raw === "/") {
      tokens.push({ type: "op", val: raw });
    } else if (/^\d/.test(raw)) {
      tokens.push({ type: "num", val: raw });
    } else {
      tokens.push({ type: "id", val: raw });
    }
  }

  const isDecisionVar = (id: string): boolean => {
    if (declaredVars.has(id)) return true;
    return id === "K" || id === "P";
  };

  for (let i = 1; i < tokens.length - 1; i += 1) {
    const prev = tokens[i - 1];
    const op = tokens[i];
    const next = tokens[i + 1];
    if (op.type !== "op") continue;

    if ((op.val === "*" || op.val === "@") && prev.type === "id" && next.type === "id") {
      if (
        isDecisionVar(prev.val) &&
        isDecisionVar(next.val) &&
        !(prev.val === "Q" && next.val === "inv")
      ) {
        const pair = `${prev.val}${op.val}${next.val}`;
        if (!seenTokens.has(pair)) {
          seenTokens.add(pair);
          warnings.push({
            line: lineNum,
            token: pair,
            message: `Termo bilinear / não afim detectado (${pair}) na linha ${lineNum}: produto entre duas incógnitas torna o problema não convexo (BMI).`,
            suggestion:
              "Aplique a mudança de variáveis Y = K · Q (mantendo Q > 0 e a LMI afim em Q, Y) e recupere o ganho com `recover K = Y * inv(Q)`.",
          });
        }
      }
    } else if (op.val === "/" && next.type === "id" && isDecisionVar(next.val)) {
      const pair = `/${next.val}`;
      if (!seenTokens.has(pair)) {
        seenTokens.add(pair);
        warnings.push({
          line: lineNum,
          token: pair,
          message: `Divisão por variável (${pair}) na linha ${lineNum} é não afim e proibida em SDPs canônicos.`,
          suggestion: "Reescreva via complemento de Schur ou multiplicação por inverso constante.",
        });
      }
    } else if (op.val === "^" && prev.type === "id" && isDecisionVar(prev.val)) {
      const pair = `${prev.val}^${next.val}`;
      if (!seenTokens.has(pair)) {
        seenTokens.add(pair);
        warnings.push({
          line: lineNum,
          token: pair,
          message: `Potência de variável (${pair}) na linha ${lineNum} é não afim.`,
          suggestion: "Utilize complemento de Schur em bmat(...) para termos quadráticos.",
        });
      }
    }
  }
  return warnings;
}

interface LogicalStatement {
  line: number;
  indent: number;
  text: string;
}

function splitLogicalStatements(rawSource: string): LogicalStatement[] {
  const rawLines = rawSource.split(/\r?\n/);
  const statements: LogicalStatement[] = [];
  let buffer = "";
  let startLine = 1;
  let startIndent = 0;
  let parenDepth = 0;
  let bracketDepth = 0;

  for (let idx = 0; idx < rawLines.length; idx += 1) {
    const rawLine = rawLines[idx];
    const cleaned = stripLineComment(rawLine);
    if (cleaned.length === 0 && parenDepth === 0 && bracketDepth === 0) {
      continue;
    }
    if (buffer.length === 0) {
      startLine = idx + 1;
      startIndent = getIndentWidth(rawLine);
    }
    buffer = buffer.length > 0 ? `${buffer} ${cleaned}` : cleaned;
    for (const ch of cleaned) {
      if (ch === "(") parenDepth += 1;
      else if (ch === ")") parenDepth = Math.max(0, parenDepth - 1);
      else if (ch === "[") bracketDepth += 1;
      else if (ch === "]") bracketDepth = Math.max(0, bracketDepth - 1);
    }
    if (parenDepth === 0 && bracketDepth === 0) {
      if (buffer.trim().length > 0) {
        statements.push({ line: startLine, indent: startIndent, text: buffer.trim() });
      }
      buffer = "";
    }
  }
  if (buffer.trim().length > 0) {
    statements.push({ line: startLine, indent: startIndent, text: buffer.trim() });
  }
  return statements;
}

function computeQuantifierCardinality(
  vars: string[],
  condition: string | null,
  N: number,
  indexRanges?: ReadonlyMap<string, { start: number; end: number }>,
): number {
  const getSize = (v: string): number => {
    const r = indexRanges?.get(v);
    if (r) return Math.max(1, r.end - r.start + 1);
    return Math.max(1, N);
  };
  if (vars.length <= 1) {
    return vars.length === 1 ? getSize(vars[0]) : Math.max(1, N);
  }
  const n0 = getSize(vars[0]);
  const n1 = getSize(vars[1]);
  if (!condition) return n0 * n1;

  const safeN = Math.max(1, Math.min(n0, n1));
  const norm = condition.replace(/\s+/g, "").toLowerCase();
  const [v1, v2] = [vars[0].toLowerCase(), vars[1].toLowerCase()];
  if (
    norm === `${v2}>${v1}` ||
    norm === `${v1}<${v2}` ||
    norm === `${v1}>${v2}` ||
    norm === `${v2}<${v1}`
  ) {
    return (safeN * (safeN - 1)) / 2;
  }
  if (
    norm === `${v2}>=${v1}` ||
    norm === `${v1}<=${v2}` ||
    norm === `${v1}>=${v2}` ||
    norm === `${v2}<=${v1}`
  ) {
    return (safeN * (safeN + 1)) / 2;
  }
  if (norm === `${v1}!=${v2}` || norm === `${v2}!=${v1}`) {
    return safeN * (safeN - 1);
  }
  return n0 * n1;
}

function buildQuantifier(
  varsRaw: string,
  conditionRaw: string | undefined,
  systemN: number,
  indexRanges?: ReadonlyMap<string, { start: number; end: number }>,
): LmiDslQuantifier {
  const vars = varsRaw
    .split(",")
    .map((v) => v.trim())
    .filter((v) => v.length > 0);
  const condition = conditionRaw ? conditionRaw.trim() : null;
  const cardinality = computeQuantifierCardinality(vars, condition, systemN, indexRanges);
  const varList = vars.join(", ");
  const condSuffix = condition ? `, ${condition}` : "";

  let mathPrefix: string;
  const distinctRanges = vars.map((v) => indexRanges?.get(v) ?? { start: 1, end: systemN });
  const allSameRange =
    distinctRanges.length === 0 ||
    distinctRanges.every((r) => r.start === distinctRanges[0].start && r.end === distinctRanges[0].end);
  if (allSameRange) {
    const r0 = distinctRanges[0] ?? { start: 1, end: systemN };
    mathPrefix = `∀ ${varList} ∈ {${r0.start}..${r0.end}}${condSuffix}:`;
  } else {
    const parts = vars.map((v, idx) => `${v} ∈ {${distinctRanges[idx].start}..${distinctRanges[idx].end}}`);
    mathPrefix = `∀ ${parts.join(", ")}${condSuffix}:`;
  }
  return {
    vars,
    condition,
    cardinality,
    mathPrefix,
  };
}

function parseSystemDirective(lineTxt: string, line: number): LmiDslSystemSpec | null {
  const sysMatch = /^system\s+(lti|polytopic|ts)\b(.*)$/i.exec(lineTxt);
  if (!sysMatch) return null;
  const systemClass = sysMatch[1].toLowerCase() as "lti" | "polytopic" | "ts";
  const rest = sysMatch[2].trim();

  let nCount: number | null = null;
  const nMatch = /\b(?:vertices|rules|N)\s*[= ]\s*(\d+)\b/i.exec(rest);
  if (nMatch) {
    nCount = Math.max(1, Number(nMatch[1]));
  }

  let indices: string[] = [];
  const idxMatch = /\bindex\s*[= ]\s*([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)/i.exec(rest);
  if (idxMatch) {
    indices = idxMatch[1].split(",").map((s) => s.trim()).filter(Boolean);
  }

  let premises: "measured" | "unmeasured" | null = null;
  const premMatch = /\bpremises\s*=\s*(measured|unmeasured|partially_observed)\b/i.exec(rest);
  if (premMatch) {
    premises = premMatch[1].toLowerCase() === "measured" ? "measured" : "unmeasured";
  } else if (/\bunmeasured_observer\b/i.test(rest)) {
    premises = "unmeasured";
  }

  const generalized = /\bgeneralized\s*=\s*true\b/i.test(rest);

  return {
    systemClass,
    nCount,
    indices,
    premises,
    generalized,
    line,
  };
}

export function parseLmiDsl(
  rawSource: string,
  options?: LmiDslParseOptions,
): LmiDslParseResult {
  const lineCount = Math.max(1, rawSource.split(/\r?\n/).length);
  const trimmedWhole = rawSource.trim();

  // Check JSON CanonicalSDPProblem mode
  if (trimmedWhole.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmedWhole) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const obj = parsed as Record<string, unknown>;
        const blocksCount = Array.isArray(obj.blocks)
          ? obj.blocks.length
          : obj.canonical_sdp && typeof obj.canonical_sdp === "object" && Array.isArray((obj.canonical_sdp as Record<string, unknown>).blocks)
            ? ((obj.canonical_sdp as Record<string, unknown>).blocks as unknown[]).length
            : 0;
        return {
          valid: true,
          lineCount,
          systemSpec: null,
          indices: [],
          macros: [],
          effectiveSystemN: options?.systemN ?? 1,
          expandedBlockCount: Math.max(1, blocksCount),
          variables: [],
          params: [],
          objective: null,
          constraints: [
            {
              index: 1,
              line: 1,
              raw: "CanonicalSDPProblem JSON",
              operator: ">=",
              isStrict: false,
              lhsRaw: "F(x)",
              rhsRaw: "0",
              bmatRows: null,
              mathText: `SDP Canônico JSON (${blocksCount} bloco(s) PSD)`,
              mathHtml: `<span class="lmi-math-expr">SDP Canônico JSON (${blocksCount} bloco(s) PSD)</span>`,
            },
          ],
          recoveries: [],
          bilinearWarnings: [],
          strictConeNotes: [],
          errors: [],
          inferredTemplate: "canonical_sdp_json",
          inferredAlpha: null,
          inferredRadius: null,
          inferredGamma: null,
          inferredFeedbackSign: "positive",
          canonicalSdpOverride: obj,
        };
      }
    } catch {
      return {
        valid: false,
        lineCount,
        systemSpec: null,
        indices: [],
        macros: [],
        effectiveSystemN: options?.systemN ?? 1,
        expandedBlockCount: 0,
        variables: [],
        params: [],
        objective: null,
        constraints: [],
        recoveries: [],
        bilinearWarnings: [],
        strictConeNotes: [],
        errors: [{ line: 1, message: "JSON de CanonicalSDPProblem inválido." }],
        inferredTemplate: "canonical_sdp_json",
        inferredAlpha: null,
        inferredRadius: null,
        inferredGamma: null,
        inferredFeedbackSign: "positive",
        canonicalSdpOverride: null,
      };
    }
  }

  let systemSpec: LmiDslSystemSpec | null = null;
  const indices: LmiDslIndexDecl[] = [];
  const macroList: LmiDslMacro[] = [];
  const macroMap = new Map<string, LmiDslMacro>();

  const variables: LmiDslVariable[] = [];
  const params: LmiDslParam[] = [];
  let objective: LmiDslParseResult["objective"] = null;
  const constraints: LmiDslConstraint[] = [];
  const recoveries: LmiDslRecovery[] = [];
  const bilinearWarnings: LmiDslBilinearWarning[] = [];
  const strictConeNotes: string[] = [];
  const errors: LmiDslParseError[] = [];

  const declaredVarNames = new Set<string>();
  const statements = splitLogicalStatements(rawSource);

  // First pass: collect `system` directive so `effectiveSystemN` is known for `index` and `forall`
  for (const stmt of statements) {
    const parsedSys = parseSystemDirective(stmt.text, stmt.line);
    if (parsedSys) {
      systemSpec = parsedSys;
      break;
    }
  }

  const effectiveSystemN = Math.max(
    1,
    systemSpec?.nCount ?? options?.systemN ?? (systemSpec?.systemClass === "lti" ? 1 : 2),
  );
  const indexRanges = new Map<string, { start: number; end: number }>();

  let activeForall: { quantifier: LmiDslQuantifier; baseIndent: number; hasBody: boolean; line: number } | null = null;

  const finalizeActiveForall = () => {
    if (activeForall && !activeForall.hasBody) {
      errors.push({
        line: activeForall.line,
        message: `Bloco 'forall' na linha ${activeForall.line} não possui restrições ou recuperações indentadas.`,
      });
    }
    activeForall = null;
  };

  for (const stmt of statements) {
    let lineTxt = stmt.text;

    if (activeForall && stmt.indent <= activeForall.baseIndent) {
      finalizeActiveForall();
    }

    if (/^subject\s+to\b:?$/i.test(lineTxt)) {
      continue;
    }

    // system directive
    if (/^system\b/i.test(lineTxt)) {
      const parsedSys = parseSystemDirective(lineTxt, stmt.line);
      if (!parsedSys) {
        errors.push({
          line: stmt.line,
          message: `Diretiva 'system' inválida na linha ${stmt.line}: '${lineTxt}'. Use 'system lti|polytopic|ts ...'.`,
        });
      } else {
        systemSpec = parsedSys;
      }
      continue;
    }

    // index <var> in 1..N
    const indexMatch = /^index\s+([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)\s+in\s+(\d+)\s*\.\.\s*([A-Za-z0-9_]+)$/i.exec(
      lineTxt,
    );
    if (indexMatch) {
      const names = indexMatch[1].split(",").map((s) => s.trim()).filter(Boolean);
      const startNum = Number(indexMatch[2]);
      const endExpr = indexMatch[3].trim();
      const numericEnd = /^\d+$/.test(endExpr)
        ? Number(endExpr)
        : endExpr.toUpperCase() === "K" && options?.deltaCount !== undefined
          ? Math.max(1, options.deltaCount)
          : effectiveSystemN;
      const resolvedEnd = Math.max(startNum, numericEnd);
      for (const name of names) {
        indices.push({
          name,
          rangeStart: startNum,
          rangeEndExpr: endExpr,
          resolvedEnd,
          line: stmt.line,
        });
        indexRanges.set(name, { start: startNum, end: resolvedEnd });
      }
      continue;
    }
    if (/^index\b/i.test(lineTxt)) {
      errors.push({
        line: stmt.line,
        message: `Declaração 'index' inválida na linha ${stmt.line}: '${lineTxt}'. Use 'index i in 1..N'.`,
      });
      continue;
    }

    // macro M(i, j) = <expr>
    const macroMatch = /^macro\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*=\s*(.+)$/i.exec(lineTxt);
    if (macroMatch) {
      const name = macroMatch[1];
      const mParams = macroMatch[2]
        .split(",")
        .map((p) => p.trim())
        .filter((p) => p.length > 0);
      const body = macroMatch[3].trim();
      const macroObj: LmiDslMacro = { name, params: mParams, body, line: stmt.line };
      macroList.push(macroObj);
      macroMap.set(name, macroObj);
      continue;
    }

    // forall / for <vars> [where <cond>]: [inline body]
    const forallMatch = /^(?:forall|for)\s+(.+?)(?:\s+where\s+(.+?))?\s*:\s*(.*)$/i.exec(lineTxt);
    if (forallMatch) {
      const q = buildQuantifier(forallMatch[1], forallMatch[2], effectiveSystemN, indexRanges);
      const inlineBody = forallMatch[3].trim();
      if (inlineBody.length > 0) {
        // Process inline body with quantifier attached
        lineTxt = inlineBody;
        activeForall = { quantifier: q, baseIndent: stmt.indent, hasBody: false, line: stmt.line };
      } else {
        activeForall = { quantifier: q, baseIndent: stmt.indent, hasBody: false, line: stmt.line };
        continue;
      }
    }

    // var <name>[idx]? sym(n) | rect(m, n) | scalar | (r, c)
    const varMatch =
      /^var\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[\s*([A-Za-z0-9_,\s]+)\s*\])?\s+(sym\s*\(\s*([^)]+)\s*\)|rect\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)|scalar|\(\s*([^,]+)\s*,\s*([^)]+)\s*\))$/i.exec(
        lineTxt,
      );
    if (varMatch) {
      const name = varMatch[1];
      const idxRaw = varMatch[2];
      const indexedBy = idxRaw
        ? idxRaw.split(",").map((s) => s.trim()).filter(Boolean)
        : undefined;
      const spec = varMatch[3].toLowerCase();
      declaredVarNames.add(name);
      if (spec.startsWith("sym")) {
        const dim = varMatch[4].trim();
        variables.push({
          name,
          kind: "sym",
          rowsExpr: dim,
          colsExpr: dim,
          shapeLabel: `sym(${dim})`,
          ...(indexedBy ? { indexedBy } : {}),
          line: stmt.line,
        });
      } else if (spec === "scalar") {
        variables.push({
          name,
          kind: "scalar",
          rowsExpr: "1",
          colsExpr: "1",
          shapeLabel: "scalar",
          ...(indexedBy ? { indexedBy } : {}),
          line: stmt.line,
        });
      } else if (spec.startsWith("rect")) {
        const r = varMatch[5].trim();
        const c = varMatch[6].trim();
        variables.push({
          name,
          kind: "rect",
          rowsExpr: r,
          colsExpr: c,
          shapeLabel: `rect(${r}, ${c})`,
          ...(indexedBy ? { indexedBy } : {}),
          line: stmt.line,
        });
      } else {
        const r = varMatch[7].trim();
        const c = varMatch[8].trim();
        variables.push({
          name,
          kind: "rect",
          rowsExpr: r,
          colsExpr: c,
          shapeLabel: `rect(${r}, ${c})`,
          ...(indexedBy ? { indexedBy } : {}),
          line: stmt.line,
        });
      }
      continue;
    }
    if (/^var\b/i.test(lineTxt)) {
      errors.push({
        line: stmt.line,
        message: `Sintaxe de declaração 'var' inválida: '${lineTxt}'. Use 'var Q sym(n)', 'var Y[i] rect(m, n)' ou 'var gamma scalar'.`,
      });
      continue;
    }

    // param <name> = <value>
    const paramMatch = /^param\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)$/.exec(
      lineTxt,
    );
    if (paramMatch) {
      const val = Number(paramMatch[2]);
      if (!Number.isFinite(val)) {
        errors.push({ line: stmt.line, message: `Parâmetro '${paramMatch[1]}' não é finito.` });
      } else {
        params.push({ name: paramMatch[1], value: val, line: stmt.line });
      }
      continue;
    }
    if (/^param\b/i.test(lineTxt)) {
      errors.push({
        line: stmt.line,
        message: `Sintaxe de parâmetro inválida: '${lineTxt}'. Use 'param nome = valor_numérico'.`,
      });
      continue;
    }

    // minimize / maximize
    const objMatch = /^(minimize|maximize)\s+(.+)$/i.exec(lineTxt);
    if (objMatch) {
      const sense = objMatch[1].toLowerCase() as "minimize" | "maximize";
      const expr = objMatch[2].trim();
      bilinearWarnings.push(...detectBilinearTerms(expr, declaredVarNames, stmt.line));
      objective = {
        sense,
        expr,
        mathText: `${sense === "minimize" ? "min" : "max"} ${formatLmiMathExpression(expr)}`,
      };
      continue;
    }

    // recover K = ... or recover K[i] = ... [for i [where ...]]
    const recMatch = /^recover\s+([A-Za-z_][A-Za-z0-9_]*(?:\s*\[\s*[A-Za-z0-9_,\s]+\s*\])?)\s*=\s*(.+)$/i.exec(
      lineTxt,
    );
    if (recMatch) {
      const lhs = recMatch[1].trim();
      let rhs = recMatch[2].trim();
      let q = activeForall?.quantifier;
      const trailingForMatch =
        /^([\s\S]+?)\s+(?:forall|for)\s+([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)(?:\s+where\s+(.+))?$/i.exec(
          rhs,
        );
      if (trailingForMatch) {
        rhs = trailingForMatch[1].trim();
        if (!q) {
          q = buildQuantifier(
            trailingForMatch[2],
            trailingForMatch[3],
            effectiveSystemN,
            indexRanges,
          );
        }
      }
      const rhsExpanded = expandMacrosInExpr(rhs, macroMap);
      if (activeForall) {
        activeForall.hasBody = true;
      }
      const qPrefix = q ? `${q.mathPrefix} ` : "";
      recoveries.push({
        line: stmt.line,
        lhs,
        rhs: rhsExpanded,
        ...(q ? { quantifier: q } : {}),
        mathText: `${qPrefix}Recuperação: ${formatLmiMathExpression(lhs)} = ${formatLmiMathExpression(rhsExpanded)}`,
      });
      if (forallMatch) {
        activeForall = null;
      }
      continue;
    }

    // Constraint: LHS (<= | >= | < | > | ==) RHS
    const relMatch = /^([\s\S]+?)\s*(<=|>=|==|<|>)\s*([\s\S]+)$/.exec(lineTxt);
    if (relMatch) {
      const lhsRaw = relMatch[1].trim();
      const op = relMatch[2] as LmiDslConstraint["operator"];
      const rhsRaw = relMatch[3].trim();
      const isStrict = op === "<" || op === ">";
      if (isStrict && strictConeNotes.length === 0) {
        strictConeNotes.push(
          "Desigualdades estritas (< 0 / > 0) são compiladas no motor Python como cones não estritos com margem explícita ε·I.",
        );
      }

      const lhsExpanded = expandMacrosInExpr(lhsRaw, macroMap);
      const rhsExpanded = expandMacrosInExpr(rhsRaw, macroMap);
      bilinearWarnings.push(...detectBilinearTerms(lhsExpanded, declaredVarNames, stmt.line));
      bilinearWarnings.push(...detectBilinearTerms(rhsExpanded, declaredVarNames, stmt.line));

      const q = activeForall?.quantifier;
      if (activeForall) {
        activeForall.hasBody = true;
      }

      const opSym = operatorToMathSymbol(op);
      const rhsMath = formatLmiMathExpression(rhsExpanded);
      const bmatRows = extractBmatRows(lhsExpanded);

      let coreMathText: string;
      let coreMathHtml: string;
      if (bmatRows) {
        const formattedRows = bmatRows.map((row) =>
          row.map((cell) => formatLmiMathExpression(cell)),
        );
        coreMathText = `[ ${formattedRows.map((r) => r.join(", ")).join(" ; ")} ] ${opSym} ${rhsMath}`;
        const gridTrs = formattedRows
          .map(
            (r) =>
              `<tr>${r
                .map((c) =>
                  c === "*"
                    ? `<td class="lmi-bmat-sym" aria-label="Bloco simétrico">*</td>`
                    : `<td>${escapeHtml(c)}</td>`,
                )
                .join("")}</tr>`,
          )
          .join("");
        coreMathHtml = `<div class="lmi-bmat-wrap"><table class="lmi-bmat-grid" aria-label="Matriz de blocos LMI"><tbody>${gridTrs}</tbody></table><span class="lmi-bmat-rel">${escapeHtml(opSym)} ${escapeHtml(rhsMath)}</span></div>`;
      } else {
        const lhsMath = formatLmiMathExpression(lhsExpanded);
        coreMathText = `${lhsMath} ${opSym} ${rhsMath}`;
        coreMathHtml = `<span class="lmi-math-expr">${escapeHtml(coreMathText)}</span>`;
      }

      const mathText = q ? `${q.mathPrefix} ${coreMathText}` : coreMathText;
      const mathHtml = q
        ? `<span class="lmi-quantifier-badge">${escapeHtml(q.mathPrefix)}</span> ${coreMathHtml}`
        : coreMathHtml;

      constraints.push({
        index: constraints.length + 1,
        line: stmt.line,
        raw: lineTxt,
        operator: op,
        isStrict,
        lhsRaw: lhsExpanded,
        rhsRaw: rhsExpanded,
        bmatRows,
        ...(q ? { quantifier: q } : {}),
        mathText,
        mathHtml,
      });
      if (forallMatch) {
        activeForall = null;
      }
      continue;
    }

    errors.push({
      line: stmt.line,
      message: `Instrução não reconhecida na linha ${stmt.line}: '${lineTxt}'.`,
    });
    if (forallMatch) {
      activeForall = null;
    }
  }

  finalizeActiveForall();

  if (statements.length === 0) {
    errors.push({ line: 1, message: "Script LMI vazio. Adicione variáveis e restrições." });
  }

  const expandedBlockCount = constraints.reduce(
    (acc, c) => acc + (c.quantifier ? c.quantifier.cardinality : 1),
    0,
  );

  // Infer backend template + parameters
  const paramMap = new Map(params.map((p) => [p.name, p.value]));
  const fullText = statements.map((s) => s.text).join("\n");

  const inferredAlpha =
    paramMap.get("alpha") ??
    (fullText.includes("alpha") ? 0.5 : null);
  const inferredRadius =
    paramMap.get("radius") ?? paramMap.get("r") ?? null;
  const inferredGamma = paramMap.get("gamma") ?? paramMap.get("gamma_sq") ?? null;
  const inferredFeedbackSign: "positive" | "negative" = /-\s*(?:B|B2|B_i|B\[[^\]]+\])\s*\*\s*Y/.test(
    fullText,
  )
    ? "negative"
    : "positive";

  let inferredTemplate: LmiBackendTemplateId = "quadratic_stabilization";
  if (systemSpec?.systemClass === "ts" && (macroList.length > 0 || constraints.some((c) => Boolean(c.quantifier)))) {
    inferredTemplate = "ts_pdc_relaxed";
  } else if (systemSpec?.systemClass === "polytopic") {
    inferredTemplate = "polytopic_robust";
  } else if (
    systemSpec?.generalized ||
    /\b(?:Bw|Cz|Dzu|Dzw|Dyw)\b/.test(fullText)
  ) {
    inferredTemplate = "hinf_generalized_brl";
  } else if (/\b(?:A_i|B_i|Y_i)\b/.test(fullText) || /\bpdc\b/i.test(fullText)) {
    inferredTemplate = "ts_pdc_stabilization";
  } else if (/\b(?:B1|B2|C1|D11|D12)\b/.test(fullText)) {
    inferredTemplate = "hinf_brl";
  } else if (/\b(?:Q_cost|R_cost)\b/.test(fullText)) {
    inferredTemplate = "lqr_lmi";
  } else if (
    inferredRadius !== null ||
    /\b-radius\b|\b-r\s*\*\s*Q\b/.test(fullText)
  ) {
    inferredTemplate = "regional_pole_placement";
  } else if (inferredAlpha !== null && inferredAlpha > 0) {
    inferredTemplate = "decay_rate";
  }

  return {
    valid: errors.length === 0,
    lineCount,
    systemSpec,
    indices,
    macros: macroList,
    effectiveSystemN,
    expandedBlockCount,
    variables,
    params,
    objective,
    constraints,
    recoveries,
    bilinearWarnings,
    strictConeNotes,
    errors,
    inferredTemplate,
    inferredAlpha,
    inferredRadius,
    inferredGamma,
    inferredFeedbackSign,
    canonicalSdpOverride: null,
  };
}

function toPythonIndexedExpr(expr: string): string {
  return expr
    .replace(/([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([A-Za-z0-9_]+)\s*\]/g, "$1_list[$2]")
    .replace(/([A-Za-z0-9_\]]+)'/g, "$1.T");
}

function toMatlabIndexedExpr(expr: string): string {
  return expr.replace(/([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([A-Za-z0-9_]+)\s*\]/g, "$1{$2}");
}

export function generateQuantifiedCvxpySnippet(
  parseResult: LmiDslParseResult,
  sysContext: LmiQuantifiedExportContext,
): string {
  const N = Math.max(1, parseResult.effectiveSystemN || sysContext.systemN || 2);
  const { n, m } = sysContext;
  const lines: string[] = [
    `# ControlLab Web — Exportação CVXPY (DSL v2.0 Quantificada)`,
    `# Classe: ${sysContext.systemClass} | N=${N} | n=${n}, m=${m} | Blocos LMI expandidos: ${parseResult.expandedBlockCount}`,
    `import cvxpy as cp`,
    `import numpy as np`,
    ``,
    `N = ${N}`,
    `n, m = ${n}, ${m}`,
    `eps = 1e-6`,
    ``,
    `# Substitua pelas matrizes reais dos vértices/regras do modelo`,
    `A_list = [np.eye(n) * -1.0 for _ in range(N)]`,
    `B_list = [np.ones((n, m)) for _ in range(N)]`,
  ];

  if (sysContext.generalized || parseResult.systemSpec?.generalized) {
    lines.push(`Bw = np.eye(n)`);
    lines.push(`Cz = np.eye(n)`);
    lines.push(`Dzu = np.zeros((n, m))`);
    lines.push(`Dzw = np.zeros((n, n))`);
  }

  lines.push(``);
  for (const v of parseResult.variables) {
    const isIdx = Boolean(v.indexedBy && v.indexedBy.length > 0);
    if (v.kind === "sym") {
      if (isIdx) {
        lines.push(`${v.name}_list = [cp.Variable((n, n), symmetric=True) for _ in range(N)]`);
      } else {
        lines.push(`${v.name} = cp.Variable((n, n), symmetric=True)`);
      }
    } else if (v.kind === "scalar") {
      lines.push(`${v.name} = cp.Variable()`);
    } else {
      const rDim = v.rowsExpr === "n" ? "n" : "m";
      const cDim = v.colsExpr === "m" ? "m" : "n";
      if (isIdx) {
        lines.push(`${v.name}_list = [cp.Variable((${rDim}, ${cDim})) for _ in range(N)]`);
      } else {
        lines.push(`${v.name} = cp.Variable((${rDim}, ${cDim}))`);
      }
    }
  }

  lines.push(``, `constraints = []`);
  for (const c of parseResult.constraints) {
    const pyOp = c.operator === ">" || c.operator === ">=" ? ">>" : "<<";
    const lhsPy = toPythonIndexedExpr(c.lhsRaw);
    const rhsPy = c.rhsRaw === "0" ? (c.operator === ">" ? "eps * np.eye(n)" : c.operator === "<" ? "-eps * np.eye(n)" : "0") : toPythonIndexedExpr(c.rhsRaw);

    if (!c.quantifier) {
      lines.push(`constraints.append(${lhsPy} ${pyOp} ${rhsPy})`);
      continue;
    }

    const q = c.quantifier;
    if (q.vars.length === 1) {
      const v0 = q.vars[0];
      lines.push(`for ${v0} in range(N):`);
      lines.push(`    constraints.append(${lhsPy} ${pyOp} ${rhsPy})`);
    } else {
      const [v0, v1] = q.vars;
      const normCond = (q.condition ?? "").replace(/\s+/g, "").toLowerCase();
      lines.push(`for ${v0} in range(N):`);
      if (normCond === `${v1.toLowerCase()}>${v0.toLowerCase()}` || normCond === `${v0.toLowerCase()}<${v1.toLowerCase()}`) {
        lines.push(`    for ${v1} in range(${v0} + 1, N):`);
      } else if (normCond === `${v1.toLowerCase()}>=${v0.toLowerCase()}` || normCond === `${v0.toLowerCase()}<=${v1.toLowerCase()}`) {
        lines.push(`    for ${v1} in range(${v0}, N):`);
      } else {
        lines.push(`    for ${v1} in range(N):`);
        if (normCond === `${v0.toLowerCase()}!=${v1.toLowerCase()}` || normCond === `${v1.toLowerCase()}!=${v0.toLowerCase()}`) {
          lines.push(`        if ${v0} == ${v1}: continue`);
        }
      }
      lines.push(`        constraints.append(${lhsPy} ${pyOp} ${rhsPy})`);
    }
  }

  const objLine = parseResult.objective
    ? `prob = cp.Problem(cp.${parseResult.objective.sense === "maximize" ? "Maximize" : "Minimize"}(${parseResult.objective.expr}), constraints)`
    : `prob = cp.Problem(cp.Minimize(0), constraints)`;

  lines.push(
    ``,
    objLine,
    `prob.solve(solver=cp.SCS)`,
    `print("Status:", prob.status, "Valor:", prob.value)`,
  );
  return lines.join("\n");
}

export function generateQuantifiedYalmipSnippet(
  parseResult: LmiDslParseResult,
  sysContext: LmiQuantifiedExportContext,
): string {
  const N = Math.max(1, parseResult.effectiveSystemN || sysContext.systemN || 2);
  const { n, m } = sysContext;
  const lines: string[] = [
    `% ControlLab Web — Exportação YALMIP (DSL v2.0 Quantificada)`,
    `% Classe: ${sysContext.systemClass} | N=${N} | n=${n}, m=${m} | Blocos LMI expandidos: ${parseResult.expandedBlockCount}`,
    `yalmip('clear');`,
    `N = ${N};`,
    `n = ${n}; m = ${m};`,
    `eps_margin = 1e-6;`,
    ``,
    `% Substitua pelas matrizes reais dos vértices/regras do modelo`,
    `for i = 1:N`,
    `    A{i} = -eye(n);`,
    `    B{i} = ones(n, m);`,
    `end`,
    ``,
  ];

  for (const v of parseResult.variables) {
    const isIdx = Boolean(v.indexedBy && v.indexedBy.length > 0);
    if (v.kind === "sym") {
      if (isIdx) {
        lines.push(`for i = 1:N, ${v.name}{i} = sdpvar(n, n, 'symmetric'); end`);
      } else {
        lines.push(`${v.name} = sdpvar(n, n, 'symmetric');`);
      }
    } else if (v.kind === "scalar") {
      lines.push(`${v.name} = sdpvar(1, 1);`);
    } else {
      const rDim = v.rowsExpr === "n" ? "n" : "m";
      const cDim = v.colsExpr === "m" ? "m" : "n";
      if (isIdx) {
        lines.push(`for i = 1:N, ${v.name}{i} = sdpvar(${rDim}, ${cDim}, 'full'); end`);
      } else {
        lines.push(`${v.name} = sdpvar(${rDim}, ${cDim}, 'full');`);
      }
    }
  }

  lines.push(``, `Constraints = [];`);
  for (const c of parseResult.constraints) {
    const matOp = c.operator === ">" || c.operator === ">=" ? ">=" : "<=";
    const lhsMat = toMatlabIndexedExpr(c.lhsRaw);
    const rhsMat = c.rhsRaw === "0" ? (c.operator === ">" ? "eps_margin * eye(n)" : c.operator === "<" ? "-eps_margin * eye(n)" : "0") : toMatlabIndexedExpr(c.rhsRaw);

    if (!c.quantifier) {
      lines.push(`Constraints = [Constraints, ${lhsMat} ${matOp} ${rhsMat}];`);
      continue;
    }

    const q = c.quantifier;
    if (q.vars.length === 1) {
      const v0 = q.vars[0];
      lines.push(`for ${v0} = 1:N`);
      lines.push(`    Constraints = [Constraints, ${lhsMat} ${matOp} ${rhsMat}];`);
      lines.push(`end`);
    } else {
      const [v0, v1] = q.vars;
      const normCond = (q.condition ?? "").replace(/\s+/g, "").toLowerCase();
      lines.push(`for ${v0} = 1:N`);
      if (normCond === `${v1.toLowerCase()}>${v0.toLowerCase()}` || normCond === `${v0.toLowerCase()}<${v1.toLowerCase()}`) {
        lines.push(`    for ${v1} = (${v0} + 1):N`);
      } else if (normCond === `${v1.toLowerCase()}>=${v0.toLowerCase()}` || normCond === `${v0.toLowerCase()}<=${v1.toLowerCase()}`) {
        lines.push(`    for ${v1} = ${v0}:N`);
      } else {
        lines.push(`    for ${v1} = 1:N`);
      }
      lines.push(`        Constraints = [Constraints, ${lhsMat} ${matOp} ${rhsMat}];`);
      lines.push(`    end`);
      lines.push(`end`);
    }
  }

  const objArg = parseResult.objective ? parseResult.objective.expr : "[]";
  lines.push(
    ``,
    `ops = sdpsettings('solver', 'sdpt3', 'verbose', 1);`,
    `sol = optimize(Constraints, ${objArg}, ops);`,
    `disp(sol.info);`,
  );
  return lines.join("\n");
}
