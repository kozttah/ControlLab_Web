/**
 * Parser declarativo determinístico para DSL LMI/SDP (Tab 6 — `WP-UX-REFACTOR-03-MIMO-FUZZY-LMI`)
 * seguindo CL-UX-DIR-001 v1.0.0 Seção 4.6 e CL-DIR-001 Seção 5.7 / ADR-010.
 *
 * Segurança:
 * - Analisador léxico/sintático 100% puro e determinístico em TypeScript.
 * - Estritamente SEM execução dinâmica de código, preservando `IMPORT_UNTRUSTED_CODE`.
 *
 * Funcionalidades:
 * - Declarações `var Q sym(n)`, `var Y rect(m, n)`, `var gamma scalar`, `param alpha = 0.5`.
 * - Expressões `minimize ...`, `recover K = Y * inv(Q)`, desigualdades LMI (`< 0`, `<= 0`, `> 0`, `>= 0`).
 * - Blocos matriciais `bmat([[...], [...]])` (incluindo múltiplas linhas) com renderização em grade visual HTML.
 * - Conversão matemática legível (`'` / `.T` -> `ᵀ`, `< 0` -> `≺ 0`, `> 0` -> `≻ 0`, `alpha` -> `α`, `gamma` -> `γ`, `inv(Q)` -> `Q⁻¹`).
 * - Detecção pedagógica de termos bilineares / não afins (ex.: `K*Q`) sugerindo mudança de variáveis `Y = K*Q`.
 * - Inferência de template para o backend Python (`decay_rate`, `quadratic_stabilization`,
 *   `regional_pole_placement`, `hinf_brl`, `lqr_lmi`, `ts_pdc_stabilization`, `canonical_sdp_json`).
 */

import { escapeHtml } from "../../app/accessibility.ts";

export type LmiBackendTemplateId =
  | "decay_rate"
  | "quadratic_stabilization"
  | "regional_pole_placement"
  | "hinf_brl"
  | "lqr_lmi"
  | "ts_pdc_stabilization"
  | "canonical_sdp_json";

export interface LmiDslVariable {
  name: string;
  kind: "sym" | "rect" | "scalar";
  rowsExpr: string;
  colsExpr: string;
  shapeLabel: string;
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
  mathText: string;
  mathHtml: string;
}

export interface LmiDslRecovery {
  line: number;
  lhs: string;
  rhs: string;
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

export interface LmiDslParseResult {
  valid: boolean;
  lineCount: number;
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
    description: "Minimização da norma H∞ ||T_zw||_∞ < γ via BRL generalizado.",
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

function stripLineComment(line: string): string {
  const hashIdx = line.indexOf("#");
  const slashIdx = line.indexOf("//");
  let cut = line.length;
  if (hashIdx >= 0) cut = Math.min(cut, hashIdx);
  if (slashIdx >= 0) cut = Math.min(cut, slashIdx);
  return line.slice(0, cut).trim();
}

function splitTopLevelCommas(text: string): string[] {
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
    else if (ch === "," && depthParen === 0 && depthBracket === 0) {
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

  const rowStrings = splitTopLevelCommas(inner);
  if (rowStrings.length === 0) return null;

  const rows: string[][] = [];
  for (const rStr of rowStrings) {
    const rs = rStr.trim();
    if (!rs.startsWith("[") || !rs.endsWith("]")) {
      return null;
    }
    const cells = splitTopLevelCommas(rs.slice(1, -1));
    if (cells.length === 0) return null;
    rows.push(cells);
  }
  return rows;
}

export function formatLmiMathExpression(expr: string): string {
  let out = expr.trim();
  // Replace inv(X) -> X⁻¹ (handles single identifier or simple group)
  out = out.replace(/\binv\s*\(\s*([A-Za-z0-9_]+)\s*\)/g, "$1⁻¹");
  // Replace trace(X) -> tr(X)
  out = out.replace(/\btrace\s*\(/g, "tr(");
  // Replace transpose markers: .T and '
  out = out.replace(/\.T\b/g, "ᵀ");
  out = out.replace(/'/g, "ᵀ");
  // Greek identifiers
  out = out.replace(/\balpha\b/g, "α");
  out = out.replace(/\bgamma\b/g, "γ");
  out = out.replace(/\blambda\b/g, "λ");
  out = out.replace(/\beps(?:ilon)?\b/g, "ε");
  // Multiplication spacing: keep readability without noisy asterisks
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
  dims?: { n?: number; m?: number; p?: number },
): string {
  if (variable.kind === "scalar") return "scalar (1×1)";
  const sub = (token: string): string => {
    const t = token.trim();
    if (t === "n" && dims?.n !== undefined) return String(dims.n);
    if (t === "m" && dims?.m !== undefined) return String(dims.m);
    if (t === "p" && dims?.p !== undefined) return String(dims.p);
    return t;
  };
  const r = sub(variable.rowsExpr);
  const c = sub(variable.colsExpr);
  return variable.kind === "sym" ? `sym(${r}×${c})` : `rect(${r}×${c})`;
}

function detectBilinearTerms(
  expr: string,
  declaredVars: ReadonlySet<string>,
  lineNum: number,
): LmiDslBilinearWarning[] {
  const warnings: LmiDslBilinearWarning[] = [];
  const seenTokens = new Set<string>();
  // Tokenize identifiers, numbers, and operators
  const tokenRe = /[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[*@^/]/g;
  const tokens: Array<{ type: "id" | "num" | "op"; val: string }> = [];
  let m: RegExpExecArray | null;
  while ((m = tokenRe.exec(expr)) !== null) {
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
    // Also treat classic gain K / P as unknown when multiplied with another unknown
    return id === "K" || id === "P";
  };

  for (let i = 1; i < tokens.length - 1; i += 1) {
    const prev = tokens[i - 1];
    const op = tokens[i];
    const next = tokens[i + 1];
    if (op.type !== "op") continue;

    if ((op.val === "*" || op.val === "@") && prev.type === "id" && next.type === "id") {
      if (
        (isDecisionVar(prev.val) && isDecisionVar(next.val)) &&
        !(prev.val === "Q" && next.val === "inv")
      ) {
        // Specifically flag unknown-unknown products (e.g. K*Q, Q*K, P*K, Q*Y, Q*Q)
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

function splitLogicalStatements(rawSource: string): Array<{ line: number; text: string }> {
  const rawLines = rawSource.split(/\r?\n/);
  const statements: Array<{ line: number; text: string }> = [];
  let buffer = "";
  let startLine = 1;
  let parenDepth = 0;
  let bracketDepth = 0;

  for (let idx = 0; idx < rawLines.length; idx += 1) {
    const cleaned = stripLineComment(rawLines[idx]);
    if (cleaned.length === 0 && parenDepth === 0 && bracketDepth === 0) {
      continue;
    }
    if (buffer.length === 0) {
      startLine = idx + 1;
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
        statements.push({ line: startLine, text: buffer.trim() });
      }
      buffer = "";
    }
  }
  if (buffer.trim().length > 0) {
    statements.push({ line: startLine, text: buffer.trim() });
  }
  return statements;
}

export function parseLmiDsl(rawSource: string): LmiDslParseResult {
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

  for (const stmt of statements) {
    const lineTxt = stmt.text;
    if (/^subject\s+to\b:?$/i.test(lineTxt)) {
      continue;
    }

    // var <name> sym(n) | rect(m, n) | scalar | (r, c)
    const varMatch =
      /^var\s+([A-Za-z_][A-Za-z0-9_]*)\s+(sym\s*\(\s*([^)]+)\s*\)|rect\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)|scalar|\(\s*([^,]+)\s*,\s*([^)]+)\s*\))$/i.exec(
        lineTxt,
      );
    if (varMatch) {
      const name = varMatch[1];
      const spec = varMatch[2].toLowerCase();
      declaredVarNames.add(name);
      if (spec.startsWith("sym")) {
        const dim = varMatch[3].trim();
        variables.push({
          name,
          kind: "sym",
          rowsExpr: dim,
          colsExpr: dim,
          shapeLabel: `sym(${dim})`,
          line: stmt.line,
        });
      } else if (spec === "scalar") {
        variables.push({
          name,
          kind: "scalar",
          rowsExpr: "1",
          colsExpr: "1",
          shapeLabel: "scalar",
          line: stmt.line,
        });
      } else if (spec.startsWith("rect")) {
        const r = varMatch[4].trim();
        const c = varMatch[5].trim();
        variables.push({
          name,
          kind: "rect",
          rowsExpr: r,
          colsExpr: c,
          shapeLabel: `rect(${r}, ${c})`,
          line: stmt.line,
        });
      } else {
        const r = varMatch[6].trim();
        const c = varMatch[7].trim();
        variables.push({
          name,
          kind: "rect",
          rowsExpr: r,
          colsExpr: c,
          shapeLabel: `rect(${r}, ${c})`,
          line: stmt.line,
        });
      }
      continue;
    }
    if (/^var\b/i.test(lineTxt)) {
      errors.push({
        line: stmt.line,
        message: `Sintaxe de declaração 'var' inválida: '${lineTxt}'. Use 'var Q sym(n)', 'var Y rect(m, n)' ou 'var gamma scalar'.`,
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

    // recover K = ...
    const recMatch = /^recover\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/i.exec(lineTxt);
    if (recMatch) {
      const lhs = recMatch[1];
      const rhs = recMatch[2].trim();
      recoveries.push({
        line: stmt.line,
        lhs,
        rhs,
        mathText: `Recuperação: ${lhs} = ${formatLmiMathExpression(rhs)}`,
      });
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

      bilinearWarnings.push(...detectBilinearTerms(lhsRaw, declaredVarNames, stmt.line));
      bilinearWarnings.push(...detectBilinearTerms(rhsRaw, declaredVarNames, stmt.line));

      const opSym = operatorToMathSymbol(op);
      const rhsMath = formatLmiMathExpression(rhsRaw);
      const bmatRows = extractBmatRows(lhsRaw);

      let mathText: string;
      let mathHtml: string;
      if (bmatRows) {
        const formattedRows = bmatRows.map((row) =>
          row.map((cell) => formatLmiMathExpression(cell)),
        );
        mathText = `[ ${formattedRows.map((r) => r.join(", ")).join(" ; ")} ] ${opSym} ${rhsMath}`;
        const gridTrs = formattedRows
          .map(
            (r) =>
              `<tr>${r.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`,
          )
          .join("");
        mathHtml = `<div class="lmi-bmat-wrap"><table class="lmi-bmat-grid" aria-label="Matriz de blocos LMI"><tbody>${gridTrs}</tbody></table><span class="lmi-bmat-rel">${escapeHtml(opSym)} ${escapeHtml(rhsMath)}</span></div>`;
      } else {
        const lhsMath = formatLmiMathExpression(lhsRaw);
        mathText = `${lhsMath} ${opSym} ${rhsMath}`;
        mathHtml = `<span class="lmi-math-expr">${escapeHtml(mathText)}</span>`;
      }

      constraints.push({
        index: constraints.length + 1,
        line: stmt.line,
        raw: lineTxt,
        operator: op,
        isStrict,
        lhsRaw,
        rhsRaw,
        bmatRows,
        mathText,
        mathHtml,
      });
      continue;
    }

    errors.push({
      line: stmt.line,
      message: `Instrução não reconhecida na linha ${stmt.line}: '${lineTxt}'.`,
    });
  }

  if (statements.length === 0) {
    errors.push({ line: 1, message: "Script LMI vazio. Adicione variáveis e restrições." });
  }

  // Infer backend template + parameters
  const paramMap = new Map(params.map((p) => [p.name, p.value]));
  const fullText = statements.map((s) => s.text).join("\n");

  const inferredAlpha =
    paramMap.get("alpha") ??
    (fullText.includes("alpha") ? 0.5 : null);
  const inferredRadius =
    paramMap.get("radius") ?? paramMap.get("r") ?? null;
  const inferredGamma = paramMap.get("gamma") ?? null;
  const inferredFeedbackSign: "positive" | "negative" = /-\s*(?:B|B2|B_i)\s*\*\s*Y/.test(
    fullText,
  )
    ? "negative"
    : "positive";

  let inferredTemplate: LmiBackendTemplateId = "quadratic_stabilization";
  if (/\b(?:A_i|B_i|Y_i)\b/.test(fullText) || /\bpdc\b/i.test(fullText)) {
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
