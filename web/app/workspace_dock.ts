/**
 * Dock lateral esquerdo persistente (Workspace Dock) + Modal guiado "+ Novo" / "Editar"
 * seguindo CL-UX-DIR-001 v1.0.0 (`WP-UX-REFACTOR-01-SHELL-DOCK`) e
 * ADR-014 (`WP-PHASE8-01-F8-WORKSPACE-SYSTEM-EDITOR` — Workspace-First System Definition).
 *
 * Agrupa os ativos da sessão em 3 categorias de engenharia:
 * 1. Séries Temporais (Dados) — Datasets
 * 2. Plantas & Modelos — StateSpace (nominal ou generalizado), TransferFunction,
 *    IdentifiedModel, Politópico Incerto (vértices ilimitados) e Takagi-Sugeno (regras ilimitadas)
 * 3. Controladores Projetados — Ganho LQR K / Compensador SISO / DynamicController
 *
 * 100% compatível com erasableSyntaxOnly, verbatimModuleSyntax e FakeElement/FakeDocument.
 */

import {
  ControlLabBridgeError,
  isPlainObject,
  type RealTensor,
} from "../bridge/protocol.ts";
import type { CanonicalStateSpaceModel } from "../features/lqr_workspace.ts";
import {
  encodeObjectRefKey,
  isTsModelKind,
  type CanonicalObjectRef,
  type RegisteredTypedObject,
} from "../features/typed_workspace.ts";
import { validateConvexMembershipFunctions } from "../features/views/lmi_ts_mf_eval.ts";
import {
  escapeHtml,
  formatMatrixDisplay,
  formatNumericDisplay,
} from "./accessibility.ts";
import type { ControlLabShell } from "./shell.ts";

export type NewObjectModalMode = "tf" | "ss" | "polytopic" | "ts" | "csv";

export interface GeneralizedChannelsSpec {
  enable_w: boolean;
  enable_z: boolean;
  Bw?: number[][];
  Dyw?: number[][];
  Cz?: number[][];
  Dzu?: number[][];
  Dzw?: number[][];
}

export interface DockInspectTarget {
  key: string;
  label: string;
  value: unknown;
}

export interface WorkspaceDockOptions {
  shell: ControlLabShell;
  container: HTMLElement;
  onInspectObject?: (target: DockInspectTarget) => void;
  onSystemRegistered?: (refKey: string, kind: string) => void;
  onRouteToLmi?: (refKey: string) => void;
  onRouteToTsModeling?: (refKey: string) => void;
  initialCollapsed?: boolean;
}

interface DockPresetSpec {
  id: string;
  label: string;
  A: number[][];
  B: number[][];
  C: number[][];
  D: number[][];
  dt: number | null;
}

interface ModalVertexRow {
  vertexId: string;
  aText: string;
  bText: string;
  cText: string;
  dText: string;
}

interface ModalPremiseRow {
  name: string;
  minText: string;
  maxText: string;
  measured: boolean;
}

interface ModalMfRow {
  id: string;
  expression: string;
}

interface EditingTargetState {
  id: string;
  revision: number;
  kind: string;
  isActiveLqrPlant: boolean;
}

const DOCK_SS_PRESETS: Record<string, DockPresetSpec> = {
  double_integrator: {
    id: "double_integrator",
    label: "Integrador Duplo (2×1)",
    A: [[0, 1], [0, 0]],
    B: [[0], [1]],
    C: [[1, 0]],
    D: [[0]],
    dt: null,
  },
  mass_spring_damper: {
    id: "mass_spring_damper",
    label: "Massa-Mola-Amortecedor (2×1)",
    A: [[0, 1], [-2, -0.5]],
    B: [[0], [1]],
    C: [[1, 0]],
    D: [[0]],
    dt: null,
  },
};

function setElHidden(el: Element | null | undefined, hidden: boolean): void {
  if (!el) return;
  if (hidden) el.setAttribute("hidden", "true");
  else el.removeAttribute("hidden");
}

function toggleElCssClass(
  el: Element | null | undefined,
  className: string,
  active: boolean,
): void {
  if (!el) return;
  const current = (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean);
  const has = current.includes(className);
  if (active && !has) {
    current.push(className);
    el.setAttribute("class", current.join(" "));
  } else if (!active && has) {
    el.setAttribute(
      "class",
      current.filter((c) => c !== className).join(" "),
    );
  }
}

function makeFloat64Tensor(shape: number[], data: number[]): RealTensor {
  return { shape, dtype: "float64", order: "C", data };
}

function tensorTo2D(raw: unknown): number[][] | null {
  if (!isPlainObject(raw) || !Array.isArray(raw.shape) || !Array.isArray(raw.data)) {
    return null;
  }
  const rows = Number(raw.shape[0] ?? 0);
  const cols = Number(raw.shape[1] ?? 0);
  if (!Number.isInteger(rows) || !Number.isInteger(cols) || rows < 1 || cols < 1) {
    return null;
  }
  const data = raw.data as unknown[];
  const out: number[][] = [];
  for (let r = 0; r < rows; r += 1) {
    const row: number[] = [];
    for (let c = 0; c < cols; c += 1) {
      row.push(Number(data[r * cols + c] ?? 0));
    }
    out.push(row);
  }
  return out;
}

function formatSubscript(num: number): string {
  const digits = ["₀", "₁", "₂", "₃", "₄", "₅", "₆", "₇", "₈", "₉"];
  return String(num)
    .split("")
    .map((ch) => digits[Number(ch)] ?? ch)
    .join("");
}

function readUploadedTextFile(file: File): Promise<string> {
  if (typeof file.text === "function") {
    return file.text();
  }
  if (typeof FileReader !== "undefined") {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
      reader.onerror = () => reject(reader.error ?? new Error("Falha ao ler arquivo CSV."));
      reader.readAsText(file);
    });
  }
  return Promise.reject(new Error("Leitura de arquivo não suportada neste ambiente."));
}

function parseCoeffList(raw: string, fieldLabel: string): number[] {
  const parts = raw
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  if (parts.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${fieldLabel} deve conter ao menos um coeficiente numérico.`,
    );
  }
  const nums = parts.map((p) => Number(p));
  if (nums.some((v) => !Number.isFinite(v))) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `${fieldLabel} contém coeficiente inválido ou não finito.`,
    );
  }
  return nums;
}

function parseMatrixText(raw: string, matrixName: string): number[][] {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Matriz ${matrixName} não pode estar vazia.`,
    );
  }
  if (trimmed.startsWith("[")) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Matriz ${matrixName} possui JSON inválido.`,
      );
    }
    if (
      !Array.isArray(parsed) ||
      parsed.length === 0 ||
      !parsed.every(
        (row) =>
          Array.isArray(row) &&
          row.length === (parsed[0] as unknown[]).length &&
          row.length > 0 &&
          row.every((v) => typeof v === "number" && Number.isFinite(v)),
      )
    ) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Matriz ${matrixName} deve ser uma matriz 2D retangular de números finitos.`,
      );
    }
    return parsed as number[][];
  }

  const rowStrings = trimmed
    .split(/[;\n]+/)
    .map((r) => r.trim())
    .filter((r) => r.length > 0);
  if (rowStrings.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Matriz ${matrixName} deve possuir ao menos uma linha.`,
    );
  }
  const matrix = rowStrings.map((rowStr) =>
    rowStr
      .split(/[\s,]+/)
      .map((c) => c.trim())
      .filter((c) => c.length > 0)
      .map((c) => Number(c)),
  );
  const cols = matrix[0]?.length ?? 0;
  if (
    cols === 0 ||
    matrix.some(
      (row) =>
        row.length !== cols || row.some((v) => !Number.isFinite(v)),
    )
  ) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Matriz ${matrixName} deve ter linhas de mesmo comprimento com valores finitos.`,
    );
  }
  return matrix;
}

function parseOptionalSampleTime(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const val = Number(trimmed);
  if (!Number.isFinite(val) || val <= 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "dt deve ser vazio (contínuo) ou número finito > 0.",
    );
  }
  return val;
}

function validateAndParseVertexRows(
  rows: readonly ModalVertexRow[],
  entityLabel: string,
): {
  n: number;
  m: number;
  p: number;
  vertices: Array<{
    vertex_id: string;
    A: RealTensor;
    B: RealTensor;
    C: RealTensor;
    D: RealTensor;
  }>;
} {
  if (rows.length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Adicione ao menos um ${entityLabel.toLowerCase()}.`,
    );
  }
  let nRef: number | null = null;
  let mRef: number | null = null;
  let pRef: number | null = null;
  const vertices: Array<{
    vertex_id: string;
    A: RealTensor;
    B: RealTensor;
    C: RealTensor;
    D: RealTensor;
  }> = [];

  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i];
    const tag = `${entityLabel} ${i + 1}`;
    const A = parseMatrixText(row.aText, `${tag} (A)`);
    const B = parseMatrixText(row.bText, `${tag} (B)`);
    const C = parseMatrixText(row.cText, `${tag} (C)`);
    const D = parseMatrixText(row.dText, `${tag} (D)`);

    const n = A.length;
    if (A[0].length !== n) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `${tag}: matriz A deve ser quadrada (n×n), recebido ${n}×${A[0].length}.`,
      );
    }
    if (B.length !== n) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `${tag}: matriz B deve ter ${n} linha(s), recebido ${B.length}.`,
      );
    }
    const m = B[0].length;
    if (C[0].length !== n) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `${tag}: matriz C deve ter ${n} coluna(s), recebido ${C[0].length}.`,
      );
    }
    const p = C.length;
    if (D.length !== p || D[0].length !== m) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `${tag}: matriz D deve ser ${p}×${m}, recebido ${D.length}×${D[0].length}.`,
      );
    }
    if (nRef === null) {
      nRef = n;
      mRef = m;
      pRef = p;
    } else if (n !== nRef || m !== mRef || p !== pRef) {
      throw new ControlLabBridgeError(
        "DIMENSION_MISMATCH",
        `${tag} possui dimensões (${n}, ${m}, ${p}), incompatíveis com (${nRef}, ${mRef}, ${pRef}) dos anteriores.`,
      );
    }

    const vid = row.vertexId.trim() || `v${i + 1}`;
    vertices.push({
      vertex_id: vid,
      A: makeFloat64Tensor([n, n], A.flat()),
      B: makeFloat64Tensor([n, m], B.flat()),
      C: makeFloat64Tensor([p, n], C.flat()),
      D: makeFloat64Tensor([p, m], D.flat()),
    });
  }

  return { n: nRef!, m: mRef!, p: pRef!, vertices };
}

function formatPolySummary(
  coeffs: readonly number[],
  variable: string,
  polyOrder: string,
  decimals: number,
): string {
  const ordered =
    polyOrder === "ascending" ? [...coeffs].reverse() : [...coeffs];
  const deg = ordered.length - 1;
  const terms: string[] = [];
  for (let i = 0; i < ordered.length; i += 1) {
    const c = ordered[i];
    if (Math.abs(c) < 1e-12) continue;
    const p = deg - i;
    const absC = Math.abs(c);
    const numStr =
      Number.isInteger(absC) && absC < 1e9
        ? String(absC)
        : formatNumericDisplay(absC, Math.min(decimals, 3));
    const sign = c < 0 ? (terms.length === 0 ? "-" : " - ") : (terms.length === 0 ? "" : " + ");
    if (p === 0) {
      terms.push(`${sign}${numStr}`);
    } else {
      const coeffPrefix = Math.abs(absC - 1) < 1e-9 ? "" : `${numStr}·`;
      const varPart = p === 1 ? variable : `${variable}^${p}`;
      terms.push(`${sign}${coeffPrefix}${varPart}`);
    }
  }
  return terms.length > 0 ? terms.join("") : "0";
}

export function extractGeneralizedChannels(
  provenance: unknown,
): GeneralizedChannelsSpec | null {
  if (!isPlainObject(provenance) || !isPlainObject(provenance.generalized_channels)) {
    return null;
  }
  const raw = provenance.generalized_channels as Record<string, unknown>;
  const enable_w = Boolean(raw.enable_w);
  const enable_z = Boolean(raw.enable_z);
  const asMat = (val: unknown): number[][] | undefined => {
    if (
      Array.isArray(val) &&
      val.length > 0 &&
      val.every(
        (r) =>
          Array.isArray(r) &&
          r.length === (val[0] as unknown[]).length &&
          r.length > 0 &&
          r.every((v) => typeof v === "number" && Number.isFinite(v)),
      )
    ) {
      return (val as number[][]).map((r) => [...r]);
    }
    return undefined;
  };
  return {
    enable_w,
    enable_z,
    ...(asMat(raw.Bw) ? { Bw: asMat(raw.Bw) } : {}),
    ...(asMat(raw.Dyw) ? { Dyw: asMat(raw.Dyw) } : {}),
    ...(asMat(raw.Cz) ? { Cz: asMat(raw.Cz) } : {}),
    ...(asMat(raw.Dzu) ? { Dzu: asMat(raw.Dzu) } : {}),
    ...(asMat(raw.Dzw) ? { Dzw: asMat(raw.Dzw) } : {}),
  };
}

export function formatDockObjectSummary(
  obj: RegisteredTypedObject,
  decimals = 3,
): string {
  const val = obj.value;
  const dtRaw = typeof val.dt === "number" ? val.dt : null;
  const domainStr = dtRaw !== null ? `dt=${dtRaw} s` : "contínuo";

  if (obj.kind === "TransferFunction") {
    const variable = typeof val.variable === "string" ? val.variable : "s";
    const polyOrder =
      typeof val.poly_order === "string" ? val.poly_order : "descending";
    const num = val.num as Array<Array<{ data?: number[] }>> | undefined;
    const den = val.den as Array<Array<{ data?: number[] }>> | undefined;
    const p = Array.isArray(num) ? num.length : 1;
    const m = Array.isArray(num?.[0]) ? num[0].length : 1;
    if (p === 1 && m === 1 && num?.[0]?.[0]?.data && den?.[0]?.[0]?.data) {
      const numStr = formatPolySummary(num[0][0].data, variable, polyOrder, decimals);
      const denStr = formatPolySummary(den[0][0].data, variable, polyOrder, decimals);
      const needsNumParens = num[0][0].data.filter((v) => Math.abs(v) > 1e-12).length > 1;
      const needsDenParens = den[0][0].data.filter((v) => Math.abs(v) > 1e-12).length > 1;
      const nFmt = needsNumParens ? `(${numStr})` : numStr;
      const dFmt = needsDenParens ? `(${denStr})` : denStr;
      return `G(${variable}) = ${nFmt} / ${dFmt} • ${domainStr}`;
    }
    return `TF ${p}×${m} • ${domainStr}`;
  }

  if (obj.kind === "StateSpace") {
    const matrices = val.matrices as Record<string, { shape?: number[] }> | undefined;
    const n = matrices?.A?.shape?.[0] ?? 0;
    const m = matrices?.B?.shape?.[1] ?? 0;
    const p = matrices?.C?.shape?.[0] ?? 0;
    const gen = extractGeneralizedChannels(val.provenance);
    const channels: string[] = [];
    if (gen?.enable_w) channels.push("w");
    if (gen?.enable_z) channels.push("z");
    const genTag = channels.length > 0 ? ` • Generalizada (${channels.join("/")})` : "";
    return `${n}×${m} SS (p=${p})${genTag} • ${domainStr}`;
  }

  if (obj.kind === "polytopic_uncertain") {
    const verts = Array.isArray(val.vertices) ? val.vertices : [];
    const v0 = verts[0] as Record<string, { shape?: number[] }> | undefined;
    const n = v0?.A?.shape?.[0] ?? 0;
    const m = v0?.B?.shape?.[1] ?? 0;
    const p = v0?.C?.shape?.[0] ?? 0;
    return `Politópico ${verts.length} vértices (${n}×${m}, p=${p}) • ${domainStr}`;
  }

  if (obj.kind === "ts_measured" || obj.kind === "ts_partially_observed") {
    const verts = Array.isArray(val.vertices) ? val.vertices : [];
    const v0 = verts[0] as Record<string, { shape?: number[] }> | undefined;
    const n = v0?.A?.shape?.[0] ?? 0;
    const m = v0?.B?.shape?.[1] ?? 0;
    const p = v0?.C?.shape?.[0] ?? 0;
    const premTag =
      obj.kind === "ts_partially_observed" ? "Premissa não medida" : "Premissas medidas";
    return `TS ${verts.length} regras (${n}×${m}, p=${p}) • ${premTag} • ${domainStr}`;
  }

  if (obj.kind === "Dataset") {
    const t = val.t as { shape?: number[] } | undefined;
    const u = val.u as { shape?: number[] } | undefined;
    const y = val.y as { shape?: number[] } | undefined;
    const nSamples = t?.shape?.[0] ?? 0;
    const m = u?.shape?.[1] ?? 1;
    const p = y?.shape?.[1] ?? 1;
    return `N=${nSamples} • ${m}×${p} • ${domainStr}`;
  }

  if (obj.kind === "IdentifiedModel") {
    const alg = typeof val.algorithm === "string" ? val.algorithm : "ID";
    const inner = val.model as Record<string, unknown> | undefined;
    const innerKind = typeof inner?.kind === "string" ? inner.kind : "Modelo";
    const innerDt = typeof inner?.dt === "number" ? inner.dt : dtRaw;
    const idDomain = innerDt !== null ? `dt=${innerDt} s` : "contínuo";
    return `${alg} → ${innerKind === "TransferFunction" ? "TF" : innerKind === "StateSpace" ? "SS" : innerKind} • ${idDomain}`;
  }

  return obj.summary;
}

export function formatDockObjectDisplayName(id: string): string {
  if (id === "plant-double-integrator" || id === "double-integrator") {
    return "Integrador Duplo 1/s²";
  }
  if (id === "ss-double_integrator") {
    return "Integrador Duplo (SS)";
  }
  if (id === "mass-spring-damper" || id === "ss-mass_spring_damper") {
    return "Massa-Mola-Amortecedor";
  }
  if (id === "first-order-stable") {
    return "1ª Ordem Estável 2/(s+3)";
  }
  if (id === "mimo-2x2-coupled" || id === "ss-mimo-distillation-2x2") {
    return "Planta MIMO 2×2 Acoplada";
  }
  if (id === "poly-2v-demo") {
    return "Politópico 2 Vértices (±15%)";
  }
  if (id === "ts-unmeasured-2r-demo") {
    return "Takagi-Sugeno 2 Regras (Não Medida)";
  }
  if (id.startsWith("ctrl-sf-") || id.startsWith("ctrl-lqr-") || id.startsWith("K_lqr_")) {
    return "Controlador LQR";
  }
  if (id.startsWith("ctrl-lqg-")) {
    return "Controlador LQG";
  }
  if (id.startsWith("ctrl-hinf-")) {
    return "Controlador H∞";
  }
  if (id === "ds-b-arx-prbs-train") {
    return "Dataset PRBS (Treino)";
  }
  if (id === "ds-b-arx-prbs-val") {
    return "Dataset PRBS (Holdout)";
  }
  if (id === "ds-b-arx-prbs") {
    return "Dataset PRBS (Benchmark)";
  }
  return id;
}

function renderDockCardTitleHtml(id: string, revision: number | null): string {
  const friendly = formatDockObjectDisplayName(id);
  const revSuffix = revision !== null ? `#r${revision}` : "";
  const techRef = `${id}${revSuffix}`;
  if (friendly !== id) {
    return `<span class="dock-item-name">${escapeHtml(friendly)}</span> <small class="dock-item-ref">${escapeHtml(techRef)}</small>`;
  }
  return `<span class="dock-item-name">${escapeHtml(id)}</span>${revSuffix ? ` <small class="dock-item-ref">${escapeHtml(revSuffix)}</small>` : ""}`;
}

export function renderWorkspaceDockHtml(): string {
  return [
    `<aside id="workspace-dock-aside" class="workspace-dock" aria-label="Workspace da Sessão">`,
    `<div class="dock-header">`,
    `<h2 class="dock-title">Workspace</h2>`,
    `<div class="dock-header-actions">`,
    `<button type="button" id="btn-dock-clear-workspace" class="touch-control btn-secondary btn-small" data-action="dock-clear-workspace" title="Limpar todos os objetos registrados da sessão">Limpar</button>`,
    `<button type="button" id="btn-open-new-object-modal" class="touch-control btn-primary btn-small" data-action="open-new-object-modal">+ Novo</button>`,
    `</div>`,
    `</div>`,
    `<div class="dock-examples-bar" aria-label="Exemplos rápidos">`,
    `<select id="dock-example-select" class="touch-control dock-preset-select" aria-label="Selecionar sistema de exemplo">`,
    `<option value="double_integrator">Integrador Duplo 1/s² (SS)</option>`,
    `<option value="mass_spring_damper">Massa-Mola-Amortecedor (TF)</option>`,
    `<option value="first_order_delay">1ª Ordem Estável 2/(s+3) (TF)</option>`,
    `<option value="mimo_2x2">Planta MIMO 2×2 Acoplada (SS)</option>`,
    `<option value="polytopic_2v">Politópico 2 Vértices ±15%</option>`,
    `<option value="ts_unmeasured_2r">Takagi-Sugeno 2 Regras com Premissa Não Medida</option>`,
    `<option value="prbs_dataset">Dataset PRBS Treino/Holdout</option>`,
    `</select>`,
    `<button type="button" id="btn-dock-load-example" class="touch-control btn-secondary btn-small" data-action="dock-load-example">Carregar Exemplo</button>`,
    `</div>`,
    `<div id="workspace-dock-content" class="dock-content"></div>`,
    `</aside>`,
  ].join("\n");
}

export function renderNewObjectModalHtml(): string {
  const presetOpts = Object.values(DOCK_SS_PRESETS)
    .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`)
    .join("");
  return [
    `<section id="workspace-new-object-modal" class="modal-dialog new-object-modal" role="dialog" aria-modal="true" aria-labelledby="new-object-modal-title" hidden>`,
    `<div class="modal-header">`,
    `<h2 id="new-object-modal-title">Novo Ativo no Workspace</h2>`,
    `<button type="button" id="new-object-modal-close" class="touch-control btn-secondary btn-small" data-action="close-new-object-modal">Fechar</button>`,
    `</div>`,
    `<div class="new-object-mode-bar" role="tablist" aria-label="Tipo de ativo">`,
    `<button type="button" id="btn-new-mode-tf" class="touch-control btn-primary btn-small" data-new-mode="tf">Função de Transferência</button>`,
    `<button type="button" id="btn-new-mode-ss" class="touch-control btn-secondary btn-small" data-new-mode="ss">Espaço de Estados</button>`,
    `<button type="button" id="btn-new-mode-polytopic" class="touch-control btn-secondary btn-small" data-new-mode="polytopic">Politópico Incerto</button>`,
    `<button type="button" id="btn-new-mode-ts" class="touch-control btn-secondary btn-small" data-new-mode="ts">Takagi-Sugeno (TS)</button>`,
    `<button type="button" id="btn-new-mode-csv" class="touch-control btn-secondary btn-small" data-new-mode="csv">Série Temporal (CSV)</button>`,
    `</div>`,
    `<div id="new-object-modal-error" class="field-error" role="alert" hidden></div>`,

    `<div id="new-obj-panel-tf" class="new-obj-panel">`,
    `<div class="typed-tf-builder-grid">`,
    `<div class="tool-field"><label for="new-tf-id">ID do modelo</label><input id="new-tf-id" type="text" class="touch-control" value="tf-planta" /></div>`,
    `<div class="tool-field"><label for="new-tf-num">Numerador (ordem decrescente)</label><input id="new-tf-num" type="text" class="touch-control" value="1" /></div>`,
    `<div class="tool-field"><label for="new-tf-den">Denominador (ordem decrescente)</label><input id="new-tf-den" type="text" class="touch-control" value="1, 1" /></div>`,
    `<div class="tool-field"><label for="new-tf-dt">dt (vazio = contínuo)</label><input id="new-tf-dt" type="number" min="0" step="any" placeholder="contínuo" class="touch-control" /></div>`,
    `</div>`,
    `<div class="panel-actions"><button type="button" id="btn-new-tf-submit" class="touch-control btn-primary" data-action="submit-new-tf">Criar Função de Transferência</button></div>`,
    `</div>`,

    `<div id="new-obj-panel-ss" class="new-obj-panel" hidden>`,
    `<div class="panel-actions">`,
    `<label for="new-ss-preset">Preset:</label>`,
    `<select id="new-ss-preset" class="touch-control"><option value="custom">Personalizado</option>${presetOpts}</select>`,
    `</div>`,
    `<div class="typed-tf-builder-grid">`,
    `<div class="tool-field"><label for="new-ss-id">ID da planta</label><input id="new-ss-id" type="text" class="touch-control" value="ss-planta" /></div>`,
    `<div class="tool-field"><label for="new-ss-dt">dt (vazio = contínuo)</label><input id="new-ss-dt" type="number" min="0" step="any" placeholder="contínuo" class="touch-control" /></div>`,
    `</div>`,
    `<div class="typed-tf-builder-grid">`,
    `<div class="tool-field"><label for="new-ss-a">Matriz A (JSON ou linhas com ;)</label><textarea id="new-ss-a" class="touch-control" rows="2">[[0, 1], [0, 0]]</textarea></div>`,
    `<div class="tool-field"><label for="new-ss-b">Matriz B</label><textarea id="new-ss-b" class="touch-control" rows="2">[[0], [1]]</textarea></div>`,
    `<div class="tool-field"><label for="new-ss-c">Matriz C</label><textarea id="new-ss-c" class="touch-control" rows="2">[[1, 0]]</textarea></div>`,
    `<div class="tool-field"><label for="new-ss-d">Matriz D</label><textarea id="new-ss-d" class="touch-control" rows="2">[[0]]</textarea></div>`,
    `</div>`,
    `<div class="lmi-sys-checks">`,
    `<label class="lmi-check-label"><input type="checkbox" id="new-ss-enable-w" /> Canal exógeno w (Bw, Dyw)</label>`,
    `<label class="lmi-check-label"><input type="checkbox" id="new-ss-enable-z" /> Canal desempenho z (Cz, Dzu, Dzw)</label>`,
    `</div>`,
    `<div id="new-ss-gen-panel" class="typed-tf-builder-grid" hidden>`,
    `<div class="tool-field"><label for="new-ss-bw">Matriz Bw</label><textarea id="new-ss-bw" class="touch-control" rows="2">[[0], [1]]</textarea></div>`,
    `<div class="tool-field"><label for="new-ss-dyw">Matriz Dyw</label><textarea id="new-ss-dyw" class="touch-control" rows="2">[[0]]</textarea></div>`,
    `<div class="tool-field"><label for="new-ss-cz">Matriz Cz</label><textarea id="new-ss-cz" class="touch-control" rows="2">[[1, 0], [0, 1]]</textarea></div>`,
    `<div class="tool-field"><label for="new-ss-dzu">Matriz Dzu</label><textarea id="new-ss-dzu" class="touch-control" rows="2">[[0], [0.1]]</textarea></div>`,
    `<div class="tool-field"><label for="new-ss-dzw">Matriz Dzw</label><textarea id="new-ss-dzw" class="touch-control" rows="2">[[0], [0]]</textarea></div>`,
    `</div>`,
    `<div class="panel-actions"><button type="button" id="btn-new-ss-submit" class="touch-control btn-primary" data-action="submit-new-ss">Criar Espaço de Estados</button></div>`,
    `</div>`,

    `<div id="new-obj-panel-polytopic" class="new-obj-panel" hidden>`,
    `<div class="typed-tf-builder-grid">`,
    `<div class="tool-field"><label for="new-poly-id">ID do sistema politópico</label><input id="new-poly-id" type="text" class="touch-control" value="poly-planta" /></div>`,
    `<div class="tool-field"><label for="new-poly-dt">dt (vazio = contínuo)</label><input id="new-poly-dt" type="number" min="0" step="any" placeholder="contínuo" class="touch-control" /></div>`,
    `<div class="tool-field"><label for="new-poly-delta">Incerteza ±δ (%)</label><input id="new-poly-delta" type="number" min="1" max="80" step="any" value="15" class="touch-control" /></div>`,
    `</div>`,
    `<div class="panel-actions">`,
    `<button type="button" id="btn-new-poly-gen-delta" class="touch-control btn-secondary btn-small" data-action="new-poly-gen-delta">Gerar ±δ% da planta ativa</button>`,
    `<button type="button" id="btn-new-poly-add-vertex" class="touch-control btn-secondary btn-small" data-action="new-poly-add-vertex">+ Adicionar Vértice</button>`,
    `</div>`,
    `<div id="new-poly-vertices-list" class="modal-dynamic-list"></div>`,
    `<div class="panel-actions"><button type="button" id="btn-new-poly-submit" class="touch-control btn-primary" data-action="submit-new-polytopic">Criar Sistema Politópico</button></div>`,
    `</div>`,

    `<div id="new-obj-panel-ts" class="new-obj-panel" hidden>`,
    `<div class="typed-tf-builder-grid">`,
    `<div class="tool-field"><label for="new-ts-id">ID do sistema Takagi-Sugeno</label><input id="new-ts-id" type="text" class="touch-control" value="ts-planta" /></div>`,
    `<div class="tool-field"><label for="new-ts-dt">dt (vazio = contínuo)</label><input id="new-ts-dt" type="number" min="0" step="any" placeholder="contínuo" class="touch-control" /></div>`,
    `</div>`,
    `<div class="modal-subsection">`,
    `<div class="lmi-ts-mf-header"><strong>Premissas e Universo de Discurso (Ω)</strong><button type="button" id="btn-new-ts-add-premise" class="touch-control btn-secondary btn-small" data-action="new-ts-add-premise">+ Adicionar Premissa</button></div>`,
    `<div id="new-ts-premises-list" class="modal-dynamic-list"></div>`,
    `</div>`,
    `<div class="modal-subsection">`,
    `<div class="lmi-ts-mf-header"><strong>Funções de Ponderação Convexa h_i(z)</strong><button type="button" id="btn-new-ts-add-mf" class="touch-control btn-secondary btn-small" data-action="new-ts-add-mf">+ Adicionar Função h_i(z)</button></div>`,
    `<div id="new-ts-mf-rows" class="modal-dynamic-list"></div>`,
    `<div id="new-ts-mf-validation" class="lmi-ts-mf-validation" role="status" aria-live="polite"></div>`,
    `</div>`,
    `<div class="modal-subsection">`,
    `<div class="lmi-ts-mf-header"><strong>Regras Locais (Submodelos A[i], B[i], C[i], D[i])</strong><button type="button" id="btn-new-ts-add-rule" class="touch-control btn-secondary btn-small" data-action="new-ts-add-rule">+ Adicionar Regra</button></div>`,
    `<div id="new-ts-rules-list" class="modal-dynamic-list"></div>`,
    `</div>`,
    `<div class="panel-actions"><button type="button" id="btn-new-ts-submit" class="touch-control btn-primary" data-action="submit-new-ts">Criar Sistema Takagi-Sugeno</button></div>`,
    `</div>`,

    `<div id="new-obj-panel-csv" class="new-obj-panel" hidden>`,
    `<div class="typed-tf-builder-grid">`,
    `<div class="tool-field"><label for="new-csv-id">ID da série temporal</label><input id="new-csv-id" type="text" class="touch-control" value="ds-ensaio" /></div>`,
    `<div class="tool-field"><label for="new-csv-train-fraction">Fração de treino (0.2–0.85)</label><input id="new-csv-train-fraction" type="number" min="0.2" max="0.85" step="0.05" value="0.7" class="touch-control" /></div>`,
    `</div>`,
    `<div class="tool-field"><label for="new-obj-csv-file">Carregar arquivo CSV (.csv / .txt)</label><input type="file" id="new-obj-csv-file" accept=".csv,.txt" class="touch-control" aria-label="Carregar arquivo CSV do computador" /></div>`,
    `<div class="tool-field"><label for="new-csv-content">Dados CSV (colunas t, u, y)</label><textarea id="new-csv-content" class="touch-control" rows="5">t,u,y\n0.00,1.0,0.00\n0.05,1.0,0.10\n0.10,1.0,0.25\n0.15,1.0,0.42\n0.20,1.0,0.58\n0.25,1.0,0.71\n0.30,1.0,0.82\n0.35,1.0,0.90\n0.40,1.0,0.95\n0.45,1.0,0.98</textarea></div>`,
    `<div class="panel-actions"><button type="button" id="btn-new-csv-submit" class="touch-control btn-primary" data-action="submit-new-csv">Importar Série &amp; Particionar</button></div>`,
    `</div>`,
    `</section>`,
  ].join("\n");
}

export class WorkspaceDockController {
  private readonly shell: ControlLabShell;
  private readonly container: HTMLElement;
  private readonly onInspectObject?: (target: DockInspectTarget) => void;
  private readonly onSystemRegistered?: (refKey: string, kind: string) => void;
  private readonly onRouteToLmi?: (refKey: string) => void;
  private readonly onRouteToTsModeling?: (refKey: string) => void;
  private collapsed: boolean;
  private modalMode: NewObjectModalMode = "tf";
  private editingTarget: EditingTargetState | null = null;
  private lastRenderKey = "";

  private polyVerticesState: ModalVertexRow[] = [];
  private tsPremisesState: ModalPremiseRow[] = [];
  private tsMfState: ModalMfRow[] = [];
  private tsRulesState: ModalVertexRow[] = [];
  private mfCounter = 2;

  private readonly workbenchShellEl: HTMLElement | null;
  private readonly dockAsideEl: HTMLElement | null;
  private readonly dockContentEl: HTMLElement | null;
  private readonly toggleBtnEl: HTMLElement | null;
  private readonly openModalBtnEl: HTMLElement | null;

  private readonly modalEl: HTMLElement | null;
  private readonly modalTitleEl: HTMLElement | null;
  private readonly modalCloseBtnEl: HTMLElement | null;
  private readonly modalErrEl: HTMLElement | null;
  private readonly modeBtnTfEl: HTMLElement | null;
  private readonly modeBtnSsEl: HTMLElement | null;
  private readonly modeBtnPolyEl: HTMLElement | null;
  private readonly modeBtnTsEl: HTMLElement | null;
  private readonly modeBtnCsvEl: HTMLElement | null;
  private readonly panelTfEl: HTMLElement | null;
  private readonly panelSsEl: HTMLElement | null;
  private readonly panelPolyEl: HTMLElement | null;
  private readonly panelTsEl: HTMLElement | null;
  private readonly panelCsvEl: HTMLElement | null;

  private readonly tfIdEl: HTMLInputElement | null;
  private readonly tfNumEl: HTMLInputElement | null;
  private readonly tfDenEl: HTMLInputElement | null;
  private readonly tfDtEl: HTMLInputElement | null;
  private readonly tfSubmitBtnEl: HTMLElement | null;

  private readonly ssPresetEl: HTMLSelectElement | null;
  private readonly ssIdEl: HTMLInputElement | null;
  private readonly ssDtEl: HTMLInputElement | null;
  private readonly ssAEl: HTMLTextAreaElement | null;
  private readonly ssBEl: HTMLTextAreaElement | null;
  private readonly ssCEl: HTMLTextAreaElement | null;
  private readonly ssDEl: HTMLTextAreaElement | null;
  private readonly ssEnableWEl: HTMLInputElement | null;
  private readonly ssEnableZEl: HTMLInputElement | null;
  private readonly ssGenPanelEl: HTMLElement | null;
  private readonly ssBwEl: HTMLTextAreaElement | null;
  private readonly ssDywEl: HTMLTextAreaElement | null;
  private readonly ssCzEl: HTMLTextAreaElement | null;
  private readonly ssDzuEl: HTMLTextAreaElement | null;
  private readonly ssDzwEl: HTMLTextAreaElement | null;
  private readonly ssSubmitBtnEl: HTMLElement | null;

  private readonly polyIdEl: HTMLInputElement | null;
  private readonly polyDtEl: HTMLInputElement | null;
  private readonly polyDeltaEl: HTMLInputElement | null;
  private readonly polyVerticesListEl: HTMLElement | null;
  private readonly polySubmitBtnEl: HTMLElement | null;

  private readonly tsIdEl: HTMLInputElement | null;
  private readonly tsDtEl: HTMLInputElement | null;
  private readonly tsPremisesListEl: HTMLElement | null;
  private readonly tsMfRowsEl: HTMLElement | null;
  private readonly tsMfValidationEl: HTMLElement | null;
  private readonly tsRulesListEl: HTMLElement | null;
  private readonly tsSubmitBtnEl: HTMLElement | null;

  private readonly csvIdEl: HTMLInputElement | null;
  private readonly csvTrainFracEl: HTMLInputElement | null;
  private readonly csvFileEl: HTMLInputElement | null;
  private readonly csvContentEl: HTMLTextAreaElement | null;

  constructor(options: WorkspaceDockOptions) {
    this.shell = options.shell;
    this.container = options.container;
    this.onInspectObject = options.onInspectObject;
    this.onSystemRegistered = options.onSystemRegistered;
    this.onRouteToLmi = options.onRouteToLmi;
    this.onRouteToTsModeling = options.onRouteToTsModeling;
    this.collapsed = options.initialCollapsed ?? false;

    this.workbenchShellEl = this.container.querySelector<HTMLElement>(".app-workbench-shell");
    this.dockAsideEl = this.container.querySelector<HTMLElement>("#workspace-dock-aside");
    this.dockContentEl = this.container.querySelector<HTMLElement>("#workspace-dock-content");
    this.toggleBtnEl = this.container.querySelector<HTMLElement>("#btn-toggle-workspace-dock");
    this.openModalBtnEl = this.container.querySelector<HTMLElement>("#btn-open-new-object-modal");

    this.modalEl = this.container.querySelector<HTMLElement>("#workspace-new-object-modal");
    this.modalTitleEl = this.container.querySelector<HTMLElement>("#new-object-modal-title");
    this.modalCloseBtnEl = this.container.querySelector<HTMLElement>("#new-object-modal-close");
    this.modalErrEl = this.container.querySelector<HTMLElement>("#new-object-modal-error");
    this.modeBtnTfEl = this.container.querySelector<HTMLElement>("#btn-new-mode-tf");
    this.modeBtnSsEl = this.container.querySelector<HTMLElement>("#btn-new-mode-ss");
    this.modeBtnPolyEl = this.container.querySelector<HTMLElement>("#btn-new-mode-polytopic");
    this.modeBtnTsEl = this.container.querySelector<HTMLElement>("#btn-new-mode-ts");
    this.modeBtnCsvEl = this.container.querySelector<HTMLElement>("#btn-new-mode-csv");
    this.panelTfEl = this.container.querySelector<HTMLElement>("#new-obj-panel-tf");
    this.panelSsEl = this.container.querySelector<HTMLElement>("#new-obj-panel-ss");
    this.panelPolyEl = this.container.querySelector<HTMLElement>("#new-obj-panel-polytopic");
    this.panelTsEl = this.container.querySelector<HTMLElement>("#new-obj-panel-ts");
    this.panelCsvEl = this.container.querySelector<HTMLElement>("#new-obj-panel-csv");

    this.tfIdEl = this.container.querySelector<HTMLInputElement>("#new-tf-id");
    this.tfNumEl = this.container.querySelector<HTMLInputElement>("#new-tf-num");
    this.tfDenEl = this.container.querySelector<HTMLInputElement>("#new-tf-den");
    this.tfDtEl = this.container.querySelector<HTMLInputElement>("#new-tf-dt");
    this.tfSubmitBtnEl = this.container.querySelector<HTMLElement>("#btn-new-tf-submit");

    this.ssPresetEl = this.container.querySelector<HTMLSelectElement>("#new-ss-preset");
    this.ssIdEl = this.container.querySelector<HTMLInputElement>("#new-ss-id");
    this.ssDtEl = this.container.querySelector<HTMLInputElement>("#new-ss-dt");
    this.ssAEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-a");
    this.ssBEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-b");
    this.ssCEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-c");
    this.ssDEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-d");
    this.ssEnableWEl = this.container.querySelector<HTMLInputElement>("#new-ss-enable-w");
    this.ssEnableZEl = this.container.querySelector<HTMLInputElement>("#new-ss-enable-z");
    this.ssGenPanelEl = this.container.querySelector<HTMLElement>("#new-ss-gen-panel");
    this.ssBwEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-bw");
    this.ssDywEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-dyw");
    this.ssCzEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-cz");
    this.ssDzuEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-dzu");
    this.ssDzwEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-dzw");
    this.ssSubmitBtnEl = this.container.querySelector<HTMLElement>("#btn-new-ss-submit");

    if (this.ssAEl && !this.ssAEl.value) this.ssAEl.value = "[[0, 1], [0, 0]]";
    if (this.ssBEl && !this.ssBEl.value) this.ssBEl.value = "[[0], [1]]";
    if (this.ssCEl && !this.ssCEl.value) this.ssCEl.value = "[[1, 0]]";
    if (this.ssDEl && !this.ssDEl.value) this.ssDEl.value = "[[0]]";
    if (this.ssBwEl && !this.ssBwEl.value) this.ssBwEl.value = "[[0], [1]]";
    if (this.ssDywEl && !this.ssDywEl.value) this.ssDywEl.value = "[[0]]";
    if (this.ssCzEl && !this.ssCzEl.value) this.ssCzEl.value = "[[1, 0], [0, 1]]";
    if (this.ssDzuEl && !this.ssDzuEl.value) this.ssDzuEl.value = "[[0], [0.1]]";
    if (this.ssDzwEl && !this.ssDzwEl.value) this.ssDzwEl.value = "[[0], [0]]";

    this.polyIdEl = this.container.querySelector<HTMLInputElement>("#new-poly-id");
    this.polyDtEl = this.container.querySelector<HTMLInputElement>("#new-poly-dt");
    this.polyDeltaEl = this.container.querySelector<HTMLInputElement>("#new-poly-delta");
    this.polyVerticesListEl = this.container.querySelector<HTMLElement>("#new-poly-vertices-list");
    this.polySubmitBtnEl = this.container.querySelector<HTMLElement>("#btn-new-poly-submit");

    this.tsIdEl = this.container.querySelector<HTMLInputElement>("#new-ts-id");
    this.tsDtEl = this.container.querySelector<HTMLInputElement>("#new-ts-dt");
    this.tsPremisesListEl = this.container.querySelector<HTMLElement>("#new-ts-premises-list");
    this.tsMfRowsEl = this.container.querySelector<HTMLElement>("#new-ts-mf-rows");
    this.tsMfValidationEl = this.container.querySelector<HTMLElement>("#new-ts-mf-validation");
    this.tsRulesListEl = this.container.querySelector<HTMLElement>("#new-ts-rules-list");
    this.tsSubmitBtnEl = this.container.querySelector<HTMLElement>("#btn-new-ts-submit");

    this.csvIdEl = this.container.querySelector<HTMLInputElement>("#new-csv-id");
    this.csvTrainFracEl = this.container.querySelector<HTMLInputElement>("#new-csv-train-fraction");
    this.csvFileEl = this.container.querySelector<HTMLInputElement>("#new-obj-csv-file");
    this.csvContentEl = this.container.querySelector<HTMLTextAreaElement>("#new-csv-content");
    if (this.csvContentEl && !this.csvContentEl.value) {
      this.csvContentEl.value = [
        "t,u,y",
        "0.00,1.0,0.00",
        "0.05,1.0,0.10",
        "0.10,1.0,0.25",
        "0.15,1.0,0.42",
        "0.20,1.0,0.58",
        "0.25,1.0,0.71",
        "0.30,1.0,0.82",
        "0.35,1.0,0.90",
        "0.40,1.0,0.95",
        "0.45,1.0,0.98",
      ].join("\n");
    }

    this.resetPolytopicDefaults();
    this.resetTsDefaults();
    this.bindEvents();
  }

  private getActivePlant2D(): { A: number[][]; B: number[][]; C: number[][]; D: number[][] } {
    const plant = this.shell.getLqrWorkspace().getPlant();
    return {
      A: tensorTo2D(plant.matrices.A) ?? [[0, 1], [-2, -1]],
      B: tensorTo2D(plant.matrices.B) ?? [[0], [1]],
      C: tensorTo2D(plant.matrices.C) ?? [[1, 0]],
      D: tensorTo2D(plant.matrices.D) ?? [[0]],
    };
  }

  private resetPolytopicDefaults(): void {
    const mats = this.getActivePlant2D();
    const scaleMat = (m: number[][], s: number): number[][] =>
      m.map((row) => row.map((v) => Number((v * s).toFixed(4))));
    this.polyVerticesState = [
      {
        vertexId: "v1",
        aText: JSON.stringify(scaleMat(mats.A, 0.85)),
        bText: JSON.stringify(mats.B),
        cText: JSON.stringify(mats.C),
        dText: JSON.stringify(mats.D),
      },
      {
        vertexId: "v2",
        aText: JSON.stringify(scaleMat(mats.A, 1.15)),
        bText: JSON.stringify(mats.B),
        cText: JSON.stringify(mats.C),
        dText: JSON.stringify(mats.D),
      },
    ];
    this.renderPolyVerticesList();
  }

  private resetTsDefaults(): void {
    const mats = this.getActivePlant2D();
    this.tsPremisesState = [
      { name: "z1", minText: "-1", maxText: "1", measured: true },
    ];
    this.tsMfState = [
      { id: "mf-1", expression: "(1 + sin(z1)) / 2" },
      { id: "mf-2", expression: "(1 - sin(z1)) / 2" },
    ];
    this.mfCounter = 2;
    this.tsRulesState = [
      {
        vertexId: "r1",
        aText: JSON.stringify(mats.A),
        bText: JSON.stringify(mats.B),
        cText: JSON.stringify(mats.C),
        dText: JSON.stringify(mats.D),
      },
      {
        vertexId: "r2",
        aText: JSON.stringify(mats.A),
        bText: JSON.stringify(mats.B),
        cText: JSON.stringify(mats.C),
        dText: JSON.stringify(mats.D),
      },
    ];
    this.renderTsModalSubforms();
  }

  private bindEvents(): void {
    this.toggleBtnEl?.addEventListener("click", () => {
      this.toggleCollapsed();
    });
    this.openModalBtnEl?.addEventListener("click", (ev) => {
      this.openNewSystemModal("tf", (ev.currentTarget as HTMLElement | null) ?? "btn-open-new-object-modal");
    });
    this.modalCloseBtnEl?.addEventListener("click", () => {
      this.closeNewObjectModal();
    });
    this.modalEl?.addEventListener("keydown", (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        this.closeNewObjectModal();
      }
    });
    this.modeBtnTfEl?.addEventListener("click", () => this.setModalMode("tf"));
    this.modeBtnSsEl?.addEventListener("click", () => this.setModalMode("ss"));
    this.modeBtnPolyEl?.addEventListener("click", () => this.setModalMode("polytopic"));
    this.modeBtnTsEl?.addEventListener("click", () => this.setModalMode("ts"));
    this.modeBtnCsvEl?.addEventListener("click", () => this.setModalMode("csv"));

    this.ssPresetEl?.addEventListener("change", () => {
      const preset = DOCK_SS_PRESETS[this.ssPresetEl?.value ?? ""];
      if (!preset) return;
      if (this.ssIdEl) this.ssIdEl.value = `ss-${preset.id}`;
      if (this.ssDtEl) this.ssDtEl.value = preset.dt === null ? "" : String(preset.dt);
      if (this.ssAEl) this.ssAEl.value = JSON.stringify(preset.A);
      if (this.ssBEl) this.ssBEl.value = JSON.stringify(preset.B);
      if (this.ssCEl) this.ssCEl.value = JSON.stringify(preset.C);
      if (this.ssDEl) this.ssDEl.value = JSON.stringify(preset.D);
    });

    const syncSsGenVisibility = (): void => {
      const show = Boolean(this.ssEnableWEl?.checked || this.ssEnableZEl?.checked);
      setElHidden(this.ssGenPanelEl, !show);
    };
    this.ssEnableWEl?.addEventListener("change", syncSsGenVisibility);
    this.ssEnableZEl?.addEventListener("change", syncSsGenVisibility);

    this.container
      .querySelector<HTMLElement>('[data-action="new-poly-gen-delta"]')
      ?.addEventListener("click", () => {
        this.generatePolytopicFromActivePlant();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="new-poly-add-vertex"]')
      ?.addEventListener("click", () => {
        const mats = this.getActivePlant2D();
        const idx = this.polyVerticesState.length + 1;
        this.polyVerticesState.push({
          vertexId: `v${idx}`,
          aText: JSON.stringify(mats.A),
          bText: JSON.stringify(mats.B),
          cText: JSON.stringify(mats.C),
          dText: JSON.stringify(mats.D),
        });
        this.renderPolyVerticesList();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="new-ts-add-premise"]')
      ?.addEventListener("click", () => {
        const nextIdx = this.tsPremisesState.length + 1;
        this.tsPremisesState.push({
          name: `z${nextIdx}`,
          minText: "-1",
          maxText: "1",
          measured: true,
        });
        this.renderTsPremisesList();
        this.renderTsConvexityStatus();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="new-ts-add-mf"]')
      ?.addEventListener("click", () => {
        const defaultPrem = this.tsPremisesState[0]?.name.trim() || "z1";
        const idx = this.tsMfState.length + 1;
        this.tsMfState.push({
          id: `mf-${++this.mfCounter}`,
          expression: idx === 1 ? `(1 + sin(${defaultPrem})) / 2` : "0",
        });
        this.renderTsMfRows();
        this.renderTsConvexityStatus();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="new-ts-add-rule"]')
      ?.addEventListener("click", () => {
        const mats = this.getActivePlant2D();
        const idx = this.tsRulesState.length + 1;
        this.tsRulesState.push({
          vertexId: `r${idx}`,
          aText: JSON.stringify(mats.A),
          bText: JSON.stringify(mats.B),
          cText: JSON.stringify(mats.C),
          dText: JSON.stringify(mats.D),
        });
        this.renderTsRulesList();
      });

    this.container
      .querySelector<HTMLElement>('[data-action="submit-new-tf"]')
      ?.addEventListener("click", () => {
        void this.submitNewTransferFunction();
      });
    this.container
      .querySelector<HTMLElement>('[data-action="submit-new-ss"]')
      ?.addEventListener("click", () => {
        void this.submitNewStateSpace();
      });
    this.container
      .querySelector<HTMLElement>('[data-action="submit-new-polytopic"]')
      ?.addEventListener("click", () => {
        void this.submitNewPolytopic();
      });
    this.container
      .querySelector<HTMLElement>('[data-action="submit-new-ts"]')
      ?.addEventListener("click", () => {
        void this.submitNewTs();
      });
    this.container
      .querySelector<HTMLElement>('[data-action="submit-new-csv"]')
      ?.addEventListener("click", () => {
        void this.submitNewCsvDataset();
      });

    this.csvFileEl?.addEventListener("change", () => {
      const files = (this.csvFileEl as unknown as { files?: FileList })?.files;
      const file = files?.[0];
      if (!file) return;
      void readUploadedTextFile(file)
        .then((txt) => {
          if (this.csvContentEl) {
            this.csvContentEl.value = txt;
          }
          this.shell
            .getAnnouncer()
            .announce(`Arquivo CSV '${file.name ?? "dataset.csv"}' carregado no formulário.`, "polite", "status");
        })
        .catch((err: unknown) => this.showModalError(err));
    });
  }

  private generatePolytopicFromActivePlant(): void {
    const mats = this.getActivePlant2D();
    const rawDelta = Number(this.polyDeltaEl?.value ?? "15");
    const deltaPct = Number.isFinite(rawDelta) ? Math.max(1, Math.min(80, rawDelta)) : 15;
    const delta = deltaPct / 100;
    const count = Math.max(2, this.polyVerticesState.length);
    const next: ModalVertexRow[] = [];
    for (let i = 0; i < count; i += 1) {
      const frac = count === 1 ? 0 : -1 + (2 * i) / (count - 1);
      const scale = 1 + frac * delta;
      const aScaled = mats.A.map((row) =>
        row.map((v) => Number((v * scale).toFixed(4))),
      );
      next.push({
        vertexId: `v${i + 1}`,
        aText: JSON.stringify(aScaled),
        bText: JSON.stringify(mats.B),
        cText: JSON.stringify(mats.C),
        dText: JSON.stringify(mats.D),
      });
    }
    this.polyVerticesState = next;
    this.renderPolyVerticesList();
  }

  private renderPolyVerticesList(): void {
    if (!this.polyVerticesListEl) return;
    const canRemove = this.polyVerticesState.length > 1;
    this.polyVerticesListEl.innerHTML = this.polyVerticesState
      .map((v, idx) =>
        [
          `<div class="lmi-vertex-editor-card" data-poly-vertex-idx="${idx}">`,
          `<div class="lmi-vertex-card-head">`,
          `<strong>Vértice ${idx + 1} (${escapeHtml(v.vertexId)})</strong>`,
          canRemove
            ? `<button type="button" class="touch-control btn-secondary btn-small" data-action="new-poly-remove-vertex" data-vertex-idx="${idx}" aria-label="Remover vértice ${idx + 1}">Remover</button>`
            : "",
          `</div>`,
          `<div class="lmi-vertex-mat-grid">`,
          `<label class="lmi-vertex-mat-field"><span>A[${idx + 1}]</span><input type="text" class="touch-control lmi-vertex-input" data-poly-idx="${idx}" data-poly-mat="A" value="${escapeHtml(v.aText)}" aria-label="Vértice ${idx + 1} matriz A" /></label>`,
          `<label class="lmi-vertex-mat-field"><span>B[${idx + 1}]</span><input type="text" class="touch-control lmi-vertex-input" data-poly-idx="${idx}" data-poly-mat="B" value="${escapeHtml(v.bText)}" aria-label="Vértice ${idx + 1} matriz B" /></label>`,
          `<label class="lmi-vertex-mat-field"><span>C[${idx + 1}]</span><input type="text" class="touch-control lmi-vertex-input" data-poly-idx="${idx}" data-poly-mat="C" value="${escapeHtml(v.cText)}" aria-label="Vértice ${idx + 1} matriz C" /></label>`,
          `<label class="lmi-vertex-mat-field"><span>D[${idx + 1}]</span><input type="text" class="touch-control lmi-vertex-input" data-poly-idx="${idx}" data-poly-mat="D" value="${escapeHtml(v.dText)}" aria-label="Vértice ${idx + 1} matriz D" /></label>`,
          `</div>`,
          `</div>`,
        ].join(""),
      )
      .join("");

    const inputs = Array.from(
      this.polyVerticesListEl.querySelectorAll<HTMLInputElement>("input[data-poly-mat]"),
    );
    for (const inp of inputs) {
      const idx = Number(inp.getAttribute("data-poly-idx"));
      const mat = inp.getAttribute("data-poly-mat");
      const sync = (): void => {
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.polyVerticesState.length) return;
        const row = this.polyVerticesState[idx];
        if (mat === "A") row.aText = inp.value;
        else if (mat === "B") row.bText = inp.value;
        else if (mat === "C") row.cText = inp.value;
        else if (mat === "D") row.dText = inp.value;
      };
      inp.addEventListener("input", sync);
      inp.addEventListener("change", sync);
    }

    const rmBtns = Array.from(
      this.polyVerticesListEl.querySelectorAll<HTMLElement>('[data-action="new-poly-remove-vertex"]'),
    );
    for (const btn of rmBtns) {
      btn.addEventListener("click", () => {
        if (this.polyVerticesState.length <= 1) return;
        const idx = Number(btn.getAttribute("data-vertex-idx"));
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.polyVerticesState.length) return;
        this.polyVerticesState.splice(idx, 1);
        this.renderPolyVerticesList();
      });
    }
  }

  private renderTsModalSubforms(): void {
    this.renderTsPremisesList();
    this.renderTsMfRows();
    this.renderTsConvexityStatus();
    this.renderTsRulesList();
  }

  private renderTsPremisesList(): void {
    if (!this.tsPremisesListEl) return;
    const canRemove = this.tsPremisesState.length > 1;
    this.tsPremisesListEl.innerHTML = this.tsPremisesState
      .map((p, idx) =>
        [
          `<div class="lmi-premise-row" data-ts-premise-idx="${idx}">`,
          `<label class="lmi-mf-field">Variável <input type="text" class="touch-control lmi-mf-input" data-ts-premise-field="name" data-ts-premise-idx="${idx}" value="${escapeHtml(p.name)}" aria-label="Nome da premissa ${idx + 1}" /></label>`,
          `<label class="lmi-mf-field">z_min <input type="number" step="any" class="touch-control lmi-mf-input" data-ts-premise-field="min" data-ts-premise-idx="${idx}" value="${escapeHtml(p.minText)}" aria-label="Limite inferior z_min da premissa ${idx + 1}" /></label>`,
          `<label class="lmi-mf-field">z_max <input type="number" step="any" class="touch-control lmi-mf-input" data-ts-premise-field="max" data-ts-premise-idx="${idx}" value="${escapeHtml(p.maxText)}" aria-label="Limite superior z_max da premissa ${idx + 1}" /></label>`,
          `<div class="lmi-premise-actions">`,
          `<label class="lmi-check-label"><input type="checkbox" data-ts-premise-field="measured" data-ts-premise-idx="${idx}"${p.measured ? " checked" : ""} /> Medida</label>`,
          canRemove
            ? `<button type="button" class="touch-control btn-secondary btn-small" data-action="new-ts-remove-premise" data-ts-premise-idx="${idx}" aria-label="Remover premissa ${idx + 1}">Remover</button>`
            : "",
          `</div>`,
          `</div>`,
        ].join(""),
      )
      .join("");

    const inputs = Array.from(
      this.tsPremisesListEl.querySelectorAll<HTMLInputElement>("input[data-ts-premise-field]"),
    );
    for (const inp of inputs) {
      const idx = Number(inp.getAttribute("data-ts-premise-idx"));
      const field = inp.getAttribute("data-ts-premise-field");
      if (!Number.isInteger(idx) || idx < 0 || idx >= this.tsPremisesState.length) continue;
      if (field === "measured") {
        inp.checked = this.tsPremisesState[idx].measured;
      }
      const onChange = (): void => {
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.tsPremisesState.length) return;
        const row = this.tsPremisesState[idx];
        if (field === "name") row.name = inp.value;
        else if (field === "min") row.minText = inp.value;
        else if (field === "max") row.maxText = inp.value;
        else if (field === "measured") row.measured = Boolean(inp.checked);
        this.renderTsConvexityStatus();
      };
      inp.addEventListener("input", onChange);
      inp.addEventListener("change", onChange);
    }

    const rmBtns = Array.from(
      this.tsPremisesListEl.querySelectorAll<HTMLElement>('[data-action="new-ts-remove-premise"]'),
    );
    for (const btn of rmBtns) {
      btn.addEventListener("click", () => {
        if (this.tsPremisesState.length <= 1) return;
        const idx = Number(btn.getAttribute("data-ts-premise-idx"));
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.tsPremisesState.length) return;
        this.tsPremisesState.splice(idx, 1);
        this.renderTsPremisesList();
        this.renderTsConvexityStatus();
      });
    }
  }

  private renderTsMfRows(): void {
    if (!this.tsMfRowsEl) return;
    const canRemove = this.tsMfState.length > 1;
    this.tsMfRowsEl.innerHTML = this.tsMfState
      .map((row, idx) => {
        const sub = formatSubscript(idx + 1);
        return [
          `<div class="lmi-mf-row" data-ts-mf-idx="${idx}">`,
          `<span class="lmi-mf-label">h${sub}(z) =</span>`,
          `<label class="lmi-mf-field"><span class="sr-only">Expressão analítica de h${sub}(z)</span><input type="text" class="touch-control lmi-mf-input" data-ts-mf-field="expression" data-ts-mf-idx="${idx}" value="${escapeHtml(row.expression)}" aria-label="Expressão analítica de h_${idx + 1}(z)" /></label>`,
          canRemove
            ? `<button type="button" class="touch-control btn-secondary btn-small lmi-mf-remove-btn" data-action="new-ts-remove-mf" data-ts-mf-idx="${idx}" aria-label="Remover função h_${idx + 1}(z)">Remover</button>`
            : "",
          `</div>`,
        ].join("");
      })
      .join("");

    const exprInputs = Array.from(
      this.tsMfRowsEl.querySelectorAll<HTMLInputElement>('input[data-ts-mf-field="expression"]'),
    );
    for (const inp of exprInputs) {
      const idx = Number(inp.getAttribute("data-ts-mf-idx"));
      const onEdit = (): void => {
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.tsMfState.length) return;
        this.tsMfState[idx].expression = inp.value;
        this.renderTsConvexityStatus();
      };
      inp.addEventListener("input", onEdit);
      inp.addEventListener("change", onEdit);
    }

    const rmBtns = Array.from(
      this.tsMfRowsEl.querySelectorAll<HTMLElement>('[data-action="new-ts-remove-mf"]'),
    );
    for (const btn of rmBtns) {
      btn.addEventListener("click", () => {
        if (this.tsMfState.length <= 1) return;
        const idx = Number(btn.getAttribute("data-ts-mf-idx"));
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.tsMfState.length) return;
        this.tsMfState.splice(idx, 1);
        this.renderTsMfRows();
        this.renderTsConvexityStatus();
      });
    }
  }

  private evaluateTsConvexity() {
    return validateConvexMembershipFunctions(
      this.tsPremisesState.map((p) => ({
        name: p.name,
        min: p.minText.trim() === "" ? Number.NaN : Number(p.minText),
        max: p.maxText.trim() === "" ? Number.NaN : Number(p.maxText),
      })),
      this.tsMfState.map((m, idx) => ({
        label: `h${formatSubscript(idx + 1)}(z)`,
        expression: m.expression,
      })),
    );
  }

  private renderTsConvexityStatus(): void {
    if (!this.tsMfValidationEl) return;
    const res = this.evaluateTsConvexity();
    toggleElCssClass(this.tsMfValidationEl, "is-valid", res.valid);
    toggleElCssClass(this.tsMfValidationEl, "is-invalid", !res.valid);
    const badgeCls = res.valid ? "badge-stable" : "badge-unstable";
    const badgeLabel = res.valid ? "Válido" : "Inválido";
    this.tsMfValidationEl.innerHTML = `<span class="badge ${badgeCls}">${badgeLabel}</span> <span>${escapeHtml(res.message)}</span>`;
  }

  private renderTsRulesList(): void {
    if (!this.tsRulesListEl) return;
    const canRemove = this.tsRulesState.length > 1;
    this.tsRulesListEl.innerHTML = this.tsRulesState
      .map((r, idx) =>
        [
          `<div class="lmi-vertex-editor-card" data-ts-rule-idx="${idx}">`,
          `<div class="lmi-vertex-card-head">`,
          `<strong>Regra ${idx + 1} (${escapeHtml(r.vertexId)})</strong>`,
          canRemove
            ? `<button type="button" class="touch-control btn-secondary btn-small" data-action="new-ts-remove-rule" data-rule-idx="${idx}" aria-label="Remover regra ${idx + 1}">Remover</button>`
            : "",
          `</div>`,
          `<div class="lmi-vertex-mat-grid">`,
          `<label class="lmi-vertex-mat-field"><span>A[${idx + 1}]</span><input type="text" class="touch-control lmi-vertex-input" data-ts-rule-idx="${idx}" data-ts-rule-mat="A" value="${escapeHtml(r.aText)}" aria-label="Regra ${idx + 1} matriz A" /></label>`,
          `<label class="lmi-vertex-mat-field"><span>B[${idx + 1}]</span><input type="text" class="touch-control lmi-vertex-input" data-ts-rule-idx="${idx}" data-ts-rule-mat="B" value="${escapeHtml(r.bText)}" aria-label="Regra ${idx + 1} matriz B" /></label>`,
          `<label class="lmi-vertex-mat-field"><span>C[${idx + 1}]</span><input type="text" class="touch-control lmi-vertex-input" data-ts-rule-idx="${idx}" data-ts-rule-mat="C" value="${escapeHtml(r.cText)}" aria-label="Regra ${idx + 1} matriz C" /></label>`,
          `<label class="lmi-vertex-mat-field"><span>D[${idx + 1}]</span><input type="text" class="touch-control lmi-vertex-input" data-ts-rule-idx="${idx}" data-ts-rule-mat="D" value="${escapeHtml(r.dText)}" aria-label="Regra ${idx + 1} matriz D" /></label>`,
          `</div>`,
          `</div>`,
        ].join(""),
      )
      .join("");

    const inputs = Array.from(
      this.tsRulesListEl.querySelectorAll<HTMLInputElement>("input[data-ts-rule-mat]"),
    );
    for (const inp of inputs) {
      const idx = Number(inp.getAttribute("data-ts-rule-idx"));
      const mat = inp.getAttribute("data-ts-rule-mat");
      const sync = (): void => {
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.tsRulesState.length) return;
        const row = this.tsRulesState[idx];
        if (mat === "A") row.aText = inp.value;
        else if (mat === "B") row.bText = inp.value;
        else if (mat === "C") row.cText = inp.value;
        else if (mat === "D") row.dText = inp.value;
      };
      inp.addEventListener("input", sync);
      inp.addEventListener("change", sync);
    }

    const rmBtns = Array.from(
      this.tsRulesListEl.querySelectorAll<HTMLElement>('[data-action="new-ts-remove-rule"]'),
    );
    for (const btn of rmBtns) {
      btn.addEventListener("click", () => {
        if (this.tsRulesState.length <= 1) return;
        const idx = Number(btn.getAttribute("data-rule-idx"));
        if (!Number.isInteger(idx) || idx < 0 || idx >= this.tsRulesState.length) return;
        this.tsRulesState.splice(idx, 1);
        this.renderTsRulesList();
      });
    }
  }

  public isCollapsed(): boolean {
    return this.collapsed;
  }

  public setCollapsed(collapsed: boolean): void {
    this.collapsed = collapsed;
    this.syncVisibility();
  }

  public toggleCollapsed(): void {
    this.setCollapsed(!this.collapsed);
  }

  public getModalMode(): NewObjectModalMode {
    return this.modalMode;
  }

  public setModalMode(mode: NewObjectModalMode): void {
    this.modalMode = mode;
    this.clearModalError();
    this.syncModalPanels();
  }

  public openNewObjectModal(trigger?: HTMLElement | string): void {
    this.openNewSystemModal("tf", trigger);
  }

  public openNewSystemModal(
    mode?: NewObjectModalMode,
    trigger?: HTMLElement | string,
  ): void {
    this.editingTarget = null;
    this.clearModalError();
    this.updateModalChromeForMode();
    if (mode === "polytopic") {
      this.resetPolytopicDefaults();
    } else if (mode === "ts") {
      this.resetTsDefaults();
    }
    this.modalMode = mode ?? "tf";
    this.syncModalPanels();
    this.shell.openModal("modal-new-object", trigger ?? "btn-open-new-object-modal");
    setElHidden(this.modalEl, false);
    this.focusActiveModalField();
  }

  public openEditSystemModal(
    refKey?: string,
    trigger?: HTMLElement | string,
  ): void {
    const activeLqrPlant = this.shell.getLqrWorkspace().getPlant();
    let targetObj: RegisteredTypedObject | null = null;
    if (refKey) {
      targetObj = this.findDockObjectByKey(refKey);
    }
    if (!targetObj) {
      const lqrKey = encodeObjectRefKey({
        id: activeLqrPlant.id,
        revision: activeLqrPlant.revision,
      });
      targetObj = this.findDockObjectByKey(lqrKey) ?? this.collectModelsAndPlants()[0] ?? null;
    }
    if (!targetObj) {
      this.openNewSystemModal("ss", trigger);
      return;
    }

    const val = targetObj.value;
    const isActiveLqr =
      targetObj.kind === "StateSpace" &&
      targetObj.id === activeLqrPlant.id &&
      targetObj.revision === activeLqrPlant.revision;

    this.editingTarget = {
      id: targetObj.id,
      revision: targetObj.revision,
      kind: targetObj.kind,
      isActiveLqrPlant: isActiveLqr,
    };
    this.clearModalError();

    if (targetObj.kind === "TransferFunction") {
      this.modalMode = "tf";
      if (this.tfIdEl) this.tfIdEl.value = targetObj.id;
      const num = val.num as Array<Array<{ data?: number[] }>> | undefined;
      const den = val.den as Array<Array<{ data?: number[] }>> | undefined;
      if (this.tfNumEl && num?.[0]?.[0]?.data) {
        this.tfNumEl.value = num[0][0].data.join(", ");
      }
      if (this.tfDenEl && den?.[0]?.[0]?.data) {
        this.tfDenEl.value = den[0][0].data.join(", ");
      }
      if (this.tfDtEl) {
        this.tfDtEl.value = typeof val.dt === "number" ? String(val.dt) : "";
      }
    } else if (targetObj.kind === "StateSpace") {
      this.modalMode = "ss";
      if (this.ssPresetEl) this.ssPresetEl.value = "custom";
      if (this.ssIdEl) this.ssIdEl.value = targetObj.id;
      if (this.ssDtEl) {
        this.ssDtEl.value = typeof val.dt === "number" ? String(val.dt) : "";
      }
      const mats = val.matrices as Record<string, unknown> | undefined;
      const A = tensorTo2D(mats?.A) ?? [[0, 1], [0, 0]];
      const B = tensorTo2D(mats?.B) ?? [[0], [1]];
      const C = tensorTo2D(mats?.C) ?? [[1, 0]];
      const D = tensorTo2D(mats?.D) ?? [[0]];
      if (this.ssAEl) this.ssAEl.value = JSON.stringify(A);
      if (this.ssBEl) this.ssBEl.value = JSON.stringify(B);
      if (this.ssCEl) this.ssCEl.value = JSON.stringify(C);
      if (this.ssDEl) this.ssDEl.value = JSON.stringify(D);

      const gen = extractGeneralizedChannels(val.provenance);
      const enW = Boolean(gen?.enable_w);
      const enZ = Boolean(gen?.enable_z);
      if (this.ssEnableWEl) this.ssEnableWEl.checked = enW;
      if (this.ssEnableZEl) this.ssEnableZEl.checked = enZ;
      setElHidden(this.ssGenPanelEl, !(enW || enZ));
      if (this.ssBwEl && gen?.Bw) this.ssBwEl.value = JSON.stringify(gen.Bw);
      if (this.ssDywEl && gen?.Dyw) this.ssDywEl.value = JSON.stringify(gen.Dyw);
      if (this.ssCzEl && gen?.Cz) this.ssCzEl.value = JSON.stringify(gen.Cz);
      if (this.ssDzuEl && gen?.Dzu) this.ssDzuEl.value = JSON.stringify(gen.Dzu);
      if (this.ssDzwEl && gen?.Dzw) this.ssDzwEl.value = JSON.stringify(gen.Dzw);
    } else if (targetObj.kind === "polytopic_uncertain") {
      this.modalMode = "polytopic";
      if (this.polyIdEl) this.polyIdEl.value = targetObj.id;
      if (this.polyDtEl) {
        this.polyDtEl.value = typeof val.dt === "number" ? String(val.dt) : "";
      }
      const prov = isPlainObject(val.provenance) ? val.provenance : {};
      if (this.polyDeltaEl && typeof prov.delta_pct === "number") {
        this.polyDeltaEl.value = String(prov.delta_pct);
      }
      const rawVerts = Array.isArray(val.vertices) ? val.vertices : [];
      this.polyVerticesState = rawVerts.map((v, idx) => {
        const vo = isPlainObject(v) ? v : {};
        return {
          vertexId: typeof vo.vertex_id === "string" ? vo.vertex_id : `v${idx + 1}`,
          aText: JSON.stringify(tensorTo2D(vo.A) ?? [[0, 1], [0, 0]]),
          bText: JSON.stringify(tensorTo2D(vo.B) ?? [[0], [1]]),
          cText: JSON.stringify(tensorTo2D(vo.C) ?? [[1, 0]]),
          dText: JSON.stringify(tensorTo2D(vo.D) ?? [[0]]),
        };
      });
      if (this.polyVerticesState.length === 0) {
        this.resetPolytopicDefaults();
      } else {
        this.renderPolyVerticesList();
      }
    } else if (targetObj.kind === "ts_measured" || targetObj.kind === "ts_partially_observed") {
      this.modalMode = "ts";
      if (this.tsIdEl) this.tsIdEl.value = targetObj.id;
      if (this.tsDtEl) {
        this.tsDtEl.value = typeof val.dt === "number" ? String(val.dt) : "";
      }
      const ms = isPlainObject(val.membership_spec) ? val.membership_spec : {};
      const pa = isPlainObject(val.premise_availability) ? val.premise_availability : {};
      const dom = isPlainObject(val.domain) ? val.domain : {};
      const bounds = isPlainObject(dom.bounds) ? (dom.bounds as Record<string, unknown>) : {};
      const unmeasuredSet = new Set(
        Array.isArray(pa.unmeasured_premises)
          ? (pa.unmeasured_premises as unknown[]).map((x) => String(x))
          : [],
      );
      const premVars = Array.isArray(ms.premise_variables)
        ? (ms.premise_variables as unknown[]).map((x) => String(x)).filter(Boolean)
        : Object.keys(bounds);
      this.tsPremisesState =
        premVars.length > 0
          ? premVars.map((name) => {
              const pair = Array.isArray(bounds[name]) ? (bounds[name] as unknown[]) : [-1, 1];
              return {
                name,
                minText: String(Number(pair[0] ?? -1)),
                maxText: String(Number(pair[1] ?? 1)),
                measured: !unmeasuredSet.has(name),
              };
            })
          : [{ name: "z1", minText: "-1", maxText: "1", measured: true }];

      const rawFns = Array.isArray(ms.functions) ? ms.functions : [];
      this.tsMfState =
        rawFns.length > 0
          ? rawFns.map((fn, idx) => {
              const fo = isPlainObject(fn) ? fn : {};
              return {
                id: typeof fo.id === "string" && fo.id.trim() ? fo.id : `mf-${idx + 1}`,
                expression: typeof fo.expression === "string" ? fo.expression : "0",
              };
            })
          : [
              { id: "mf-1", expression: `(1 + sin(${this.tsPremisesState[0].name})) / 2` },
              { id: "mf-2", expression: `(1 - sin(${this.tsPremisesState[0].name})) / 2` },
            ];
      this.mfCounter = Math.max(this.mfCounter, this.tsMfState.length + 1);

      const rawRules = Array.isArray(val.vertices) ? val.vertices : [];
      this.tsRulesState = rawRules.map((v, idx) => {
        const vo = isPlainObject(v) ? v : {};
        return {
          vertexId: typeof vo.vertex_id === "string" ? vo.vertex_id : `r${idx + 1}`,
          aText: JSON.stringify(tensorTo2D(vo.A) ?? [[0, 1], [0, 0]]),
          bText: JSON.stringify(tensorTo2D(vo.B) ?? [[0], [1]]),
          cText: JSON.stringify(tensorTo2D(vo.C) ?? [[1, 0]]),
          dText: JSON.stringify(tensorTo2D(vo.D) ?? [[0]]),
        };
      });
      if (this.tsRulesState.length === 0) {
        this.tsRulesState = [
          { vertexId: "r1", aText: "[[0, 1], [0, 0]]", bText: "[[0], [1]]", cText: "[[1, 0]]", dText: "[[0]]" },
        ];
      }
      this.renderTsModalSubforms();
    } else {
      this.editingTarget = null;
      this.modalMode = "ss";
    }

    this.updateModalChromeForMode();
    this.syncModalPanels();
    this.shell.openModal("modal-new-object", trigger ?? "btn-open-new-object-modal");
    setElHidden(this.modalEl, false);
    this.focusActiveModalField();
  }

  private updateModalChromeForMode(): void {
    const isEdit = this.editingTarget !== null;
    if (this.modalTitleEl) {
      this.modalTitleEl.textContent = isEdit
        ? `Editar ${this.editingTarget!.id} (rev ${this.editingTarget!.revision} → ${this.editingTarget!.revision + 1})`
        : "Novo Ativo no Workspace";
    }
    if (this.tfSubmitBtnEl) {
      this.tfSubmitBtnEl.textContent = isEdit
        ? "Salvar Nova Revisão (TF)"
        : "Criar Função de Transferência";
    }
    if (this.ssSubmitBtnEl) {
      this.ssSubmitBtnEl.textContent = isEdit
        ? "Salvar Nova Revisão (SS)"
        : "Criar Espaço de Estados";
    }
    if (this.polySubmitBtnEl) {
      this.polySubmitBtnEl.textContent = isEdit
        ? "Salvar Nova Revisão (Politópico)"
        : "Criar Sistema Politópico";
    }
    if (this.tsSubmitBtnEl) {
      this.tsSubmitBtnEl.textContent = isEdit
        ? "Salvar Nova Revisão (TS)"
        : "Criar Sistema Takagi-Sugeno";
    }
  }

  private focusActiveModalField(): void {
    if (this.modalMode === "tf") this.tfIdEl?.focus();
    else if (this.modalMode === "ss") this.ssIdEl?.focus();
    else if (this.modalMode === "polytopic") this.polyIdEl?.focus();
    else if (this.modalMode === "ts") this.tsIdEl?.focus();
    else this.csvIdEl?.focus();
  }

  public closeNewObjectModal(): void {
    this.editingTarget = null;
    if (this.shell.getOpenModalId() === "modal-new-object") {
      this.shell.closeModal("modal-new-object");
    }
    setElHidden(this.modalEl, true);
  }

  private resolveNextRevision(id: string): number {
    if (this.editingTarget && this.editingTarget.id === id) {
      return this.editingTarget.revision + 1;
    }
    let maxRev = 0;
    for (const item of this.shell.getTypedWorkspace().listRegisteredObjects()) {
      if (item.id === id && item.revision > maxRev) {
        maxRev = item.revision;
      }
    }
    const activePlant = this.shell.getLqrWorkspace().getPlant();
    if (activePlant.id === id && activePlant.revision > maxRev) {
      maxRev = activePlant.revision;
    }
    return maxRev + 1;
  }

  private showModalError(err: unknown): void {
    const msg = err instanceof Error ? err.message : String(err);
    if (this.modalErrEl) {
      this.modalErrEl.textContent = msg;
      setElHidden(this.modalErrEl, false);
    }
    this.shell.presentError(err);
  }

  private clearModalError(): void {
    if (this.modalErrEl) {
      this.modalErrEl.textContent = "";
      setElHidden(this.modalErrEl, true);
    }
  }

  private syncModalPanels(): void {
    setElHidden(this.panelTfEl, this.modalMode !== "tf");
    setElHidden(this.panelSsEl, this.modalMode !== "ss");
    setElHidden(this.panelPolyEl, this.modalMode !== "polytopic");
    setElHidden(this.panelTsEl, this.modalMode !== "ts");
    setElHidden(this.panelCsvEl, this.modalMode !== "csv");

    const modeBtns: Array<[HTMLElement | null, boolean]> = [
      [this.modeBtnTfEl, this.modalMode === "tf"],
      [this.modeBtnSsEl, this.modalMode === "ss"],
      [this.modeBtnPolyEl, this.modalMode === "polytopic"],
      [this.modeBtnTsEl, this.modalMode === "ts"],
      [this.modeBtnCsvEl, this.modalMode === "csv"],
    ];
    for (const [btn, active] of modeBtns) {
      toggleElCssClass(btn, "btn-primary", active);
      toggleElCssClass(btn, "btn-secondary", !active);
      btn?.setAttribute("aria-selected", active ? "true" : "false");
    }
  }

  private async submitNewTransferFunction(): Promise<void> {
    try {
      this.clearModalError();
      const id = (this.tfIdEl?.value?.trim() ?? "") || "tf-planta";
      const numCoeffs = parseCoeffList(this.tfNumEl?.value ?? "", "Numerador");
      const denCoeffs = parseCoeffList(this.tfDenEl?.value ?? "", "Denominador");
      if (denCoeffs.every((v) => v === 0)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Denominador da TransferFunction não pode ser identicamente nulo.",
        );
      }
      const dtVal = parseOptionalSampleTime(this.tfDtEl?.value ?? "");
      const revision = this.resolveNextRevision(id);
      const dto = {
        schema_version: "1.0.0",
        id,
        revision,
        kind: "TransferFunction",
        dt: dtVal,
        variable: dtVal === null ? "s" : "z",
        poly_order: "descending",
        num: [[makeFloat64Tensor([numCoeffs.length], numCoeffs)]],
        den: [[makeFloat64Tensor([denCoeffs.length], denCoeffs)]],
        units: { time: "s", inputs: ["u1"], outputs: ["y1"] },
        provenance: { source: "workspace_dock_modal" },
      };
      const reg = await this.shell.getTypedWorkspace().registerTypedObject(dto, {
        selectRole: "frequencyPlant",
      });
      this.onSystemRegistered?.(reg.key, reg.kind);
      this.closeNewObjectModal();
    } catch (err: unknown) {
      this.showModalError(err);
    }
  }

  private async submitNewStateSpace(): Promise<void> {
    try {
      this.clearModalError();
      const id = (this.ssIdEl?.value?.trim() ?? "") || "ss-planta";
      const A = parseMatrixText(this.ssAEl?.value ?? "", "A");
      const B = parseMatrixText(this.ssBEl?.value ?? "", "B");
      const C = parseMatrixText(this.ssCEl?.value ?? "", "C");
      const D = parseMatrixText(this.ssDEl?.value ?? "", "D");
      const n = A.length;
      if (A[0].length !== n) {
        throw new ControlLabBridgeError("DIMENSION_MISMATCH", `Matriz A deve ser quadrada (n×n).`);
      }
      if (B.length !== n) {
        throw new ControlLabBridgeError("DIMENSION_MISMATCH", `Matriz B deve ter ${n} linha(s).`);
      }
      const m = B[0].length;
      if (C[0].length !== n) {
        throw new ControlLabBridgeError("DIMENSION_MISMATCH", `Matriz C deve ter ${n} coluna(s).`);
      }
      const p = C.length;
      if (D.length !== p || D[0].length !== m) {
        throw new ControlLabBridgeError("DIMENSION_MISMATCH", `Matriz D deve ser ${p}×${m}.`);
      }
      const dtVal = parseOptionalSampleTime(this.ssDtEl?.value ?? "");

      const enableW = Boolean(this.ssEnableWEl?.checked);
      const enableZ = Boolean(this.ssEnableZEl?.checked);
      const provenance: Record<string, unknown> = { source: "workspace_dock_modal" };
      if (enableW || enableZ) {
        const genChannels: GeneralizedChannelsSpec = {
          enable_w: enableW,
          enable_z: enableZ,
        };
        let nw = 1;
        if (enableW) {
          const Bw = parseMatrixText(this.ssBwEl?.value ?? "", "Bw");
          if (Bw.length !== n) {
            throw new ControlLabBridgeError(
              "DIMENSION_MISMATCH",
              `Matriz Bw deve ter ${n} linha(s) (n=${n}), recebido ${Bw.length}.`,
            );
          }
          nw = Bw[0].length;
          genChannels.Bw = Bw;
          const dywRaw = this.ssDywEl?.value?.trim() ?? "";
          if (dywRaw.length > 0) {
            const Dyw = parseMatrixText(dywRaw, "Dyw");
            if (Dyw.length !== p || Dyw[0].length !== nw) {
              throw new ControlLabBridgeError(
                "DIMENSION_MISMATCH",
                `Matriz Dyw deve ser ${p}×${nw} (p×n_w), recebido ${Dyw.length}×${Dyw[0].length}.`,
              );
            }
            genChannels.Dyw = Dyw;
          } else {
            genChannels.Dyw = Array.from({ length: p }, () => Array(nw).fill(0));
          }
        }
        if (enableZ) {
          const Cz = parseMatrixText(this.ssCzEl?.value ?? "", "Cz");
          if (Cz[0].length !== n) {
            throw new ControlLabBridgeError(
              "DIMENSION_MISMATCH",
              `Matriz Cz deve ter ${n} coluna(s) (n=${n}), recebido ${Cz[0].length}.`,
            );
          }
          const nz = Cz.length;
          genChannels.Cz = Cz;
          const dzuRaw = this.ssDzuEl?.value?.trim() ?? "";
          if (dzuRaw.length > 0) {
            const Dzu = parseMatrixText(dzuRaw, "Dzu");
            if (Dzu.length !== nz || Dzu[0].length !== m) {
              throw new ControlLabBridgeError(
                "DIMENSION_MISMATCH",
                `Matriz Dzu deve ser ${nz}×${m} (n_z×m), recebido ${Dzu.length}×${Dzu[0].length}.`,
              );
            }
            genChannels.Dzu = Dzu;
          } else {
            genChannels.Dzu = Array.from({ length: nz }, () => Array(m).fill(0));
          }
          if (enableW) {
            const dzwRaw = this.ssDzwEl?.value?.trim() ?? "";
            if (dzwRaw.length > 0) {
              const Dzw = parseMatrixText(dzwRaw, "Dzw");
              if (Dzw.length !== nz || Dzw[0].length !== nw) {
                throw new ControlLabBridgeError(
                  "DIMENSION_MISMATCH",
                  `Matriz Dzw deve ser ${nz}×${nw} (n_z×n_w), recebido ${Dzw.length}×${Dzw[0].length}.`,
                );
              }
              genChannels.Dzw = Dzw;
            } else {
              genChannels.Dzw = Array.from({ length: nz }, () => Array(nw).fill(0));
            }
          }
        }
        provenance.generalized_channels = genChannels;
      }

      const wasActiveLqrEdit = Boolean(
        this.editingTarget?.isActiveLqrPlant && this.editingTarget.id === id,
      );
      const revision = this.resolveNextRevision(id);
      const dto: CanonicalStateSpaceModel = {
        schema_version: "1.0.0",
        id,
        revision,
        kind: "StateSpace",
        dt: dtVal,
        state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
        input_names: Array.from({ length: m }, (_, i) => `u${i + 1}`),
        output_names: Array.from({ length: p }, (_, i) => `y${i + 1}`),
        matrices: {
          A: makeFloat64Tensor([n, n], A.flat()),
          B: makeFloat64Tensor([n, m], B.flat()),
          C: makeFloat64Tensor([p, n], C.flat()),
          D: makeFloat64Tensor([p, m], D.flat()),
        },
        units: {
          time: "s",
          states: Array.from({ length: n }, () => ""),
          inputs: Array.from({ length: m }, () => ""),
          outputs: Array.from({ length: p }, () => ""),
        },
        provenance,
      };
      const reg = await this.shell.getTypedWorkspace().registerTypedObject(dto, {
        selectRole: "statespacePlant",
      });
      if (wasActiveLqrEdit) {
        this.shell.getLqrWorkspace().updatePlant(dto);
      }
      this.onSystemRegistered?.(reg.key, reg.kind);
      this.closeNewObjectModal();
    } catch (err: unknown) {
      this.showModalError(err);
    }
  }

  private async submitNewPolytopic(): Promise<void> {
    try {
      this.clearModalError();
      const id = (this.polyIdEl?.value?.trim() ?? "") || "poly-planta";
      const dtVal = parseOptionalSampleTime(this.polyDtEl?.value ?? "");
      const rawDelta = Number(this.polyDeltaEl?.value ?? "15");
      const deltaPct = Number.isFinite(rawDelta) ? rawDelta : 15;
      const { n, m, p, vertices } = validateAndParseVertexRows(
        this.polyVerticesState,
        "Vértice",
      );
      const revision = this.resolveNextRevision(id);
      const dto = {
        schema_version: "1.0.0",
        id,
        revision,
        kind: "polytopic_uncertain" as const,
        dt: dtVal,
        membership_spec: {
          version: "1.0.0",
          premise_variables: ["alpha"],
          sum_to_one_domain: true,
        },
        premise_availability: {
          mode: "unknown_uncertain" as const,
          measured_premises: [] as string[],
          unmeasured_premises: ["alpha"],
          estimator_required_for_pdc: true,
        },
        domain: {
          bounds: { alpha: [0, 1] },
        },
        vertices,
        state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
        input_names: Array.from({ length: m }, (_, i) => `u${i + 1}`),
        output_names: Array.from({ length: p }, (_, i) => `y${i + 1}`),
        units: {
          time: "s",
          states: Array.from({ length: n }, () => ""),
          inputs: Array.from({ length: m }, () => ""),
          outputs: Array.from({ length: p }, () => ""),
        },
        provenance: {
          source: "workspace_dock_modal",
          delta_pct: deltaPct,
        },
      };
      const reg = await this.shell.getTypedWorkspace().registerTypedObject(dto, {
        selectRole: "tsModel",
      });
      this.onSystemRegistered?.(reg.key, reg.kind);
      this.closeNewObjectModal();
    } catch (err: unknown) {
      this.showModalError(err);
    }
  }

  private async submitNewTs(): Promise<void> {
    try {
      this.clearModalError();
      const id = (this.tsIdEl?.value?.trim() ?? "") || "ts-planta";
      const dtVal = parseOptionalSampleTime(this.tsDtEl?.value ?? "");
      if (this.tsPremisesState.length === 0) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "Defina ao menos uma variável de premissa para o sistema Takagi-Sugeno.",
        );
      }

      const premiseVariables: string[] = [];
      const measuredPremises: string[] = [];
      const unmeasuredPremises: string[] = [];
      const bounds: Record<string, [number, number]> = {};
      const seenPremises = new Set<string>();

      for (let i = 0; i < this.tsPremisesState.length; i += 1) {
        const pRow = this.tsPremisesState[i];
        const name = pRow.name.trim();
        if (!name) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Premissa ${i + 1} deve possuir nome válido.`,
          );
        }
        if (seenPremises.has(name)) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Premissa duplicada: '${name}'.`,
          );
        }
        seenPremises.add(name);
        const lo = Number(pRow.minText);
        const hi = Number(pRow.maxText);
        if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo > hi) {
          throw new ControlLabBridgeError(
            "VALIDATION_ERROR",
            `Domínio inválido para premissa '${name}': z_min (${pRow.minText}) deve ser <= z_max (${pRow.maxText}).`,
          );
        }
        premiseVariables.push(name);
        bounds[name] = [lo, hi];
        if (pRow.measured) measuredPremises.push(name);
        else unmeasuredPremises.push(name);
      }

      const { n, m, p, vertices } = validateAndParseVertexRows(
        this.tsRulesState,
        "Regra",
      );
      const convex = this.evaluateTsConvexity();
      const hasUnmeasured = unmeasuredPremises.length > 0;
      const kind = hasUnmeasured
        ? ("ts_partially_observed" as const)
        : ("ts_measured" as const);
      const revision = this.resolveNextRevision(id);

      const dto = {
        schema_version: "1.0.0",
        id,
        revision,
        kind,
        dt: dtVal,
        membership_spec: {
          version: "1.0.0",
          premise_variables: premiseVariables,
          sum_to_one_domain: convex.valid,
          functions: this.tsMfState.map((mf, idx) => ({
            id: mf.id,
            label: `h_${idx + 1}(z)`,
            expression: mf.expression,
          })),
          convexity_message: convex.message,
        },
        premise_availability: {
          mode: hasUnmeasured ? ("partially_observed" as const) : ("all_measured" as const),
          measured_premises: measuredPremises,
          unmeasured_premises: unmeasuredPremises,
          estimator_required_for_pdc: hasUnmeasured,
        },
        domain: { bounds },
        vertices,
        state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
        input_names: Array.from({ length: m }, (_, i) => `u${i + 1}`),
        output_names: Array.from({ length: p }, (_, i) => `y${i + 1}`),
        units: {
          time: "s",
          states: Array.from({ length: n }, () => ""),
          inputs: Array.from({ length: m }, () => ""),
          outputs: Array.from({ length: p }, () => ""),
        },
        provenance: {
          source: "workspace_dock_modal",
        },
      };

      const reg = await this.shell.getTypedWorkspace().registerTypedObject(dto, {
        selectRole: "tsModel",
      });
      this.onSystemRegistered?.(reg.key, reg.kind);
      this.closeNewObjectModal();
    } catch (err: unknown) {
      this.showModalError(err);
    }
  }

  private async submitNewCsvDataset(): Promise<void> {
    try {
      this.clearModalError();
      const id = (this.csvIdEl?.value?.trim() ?? "") || "ds-ensaio";
      const fracRaw = Number(this.csvTrainFracEl?.value ?? "0.7");
      const trainFraction = Number.isFinite(fracRaw) ? fracRaw : 0.7;
      const csvText = this.csvContentEl?.value ?? "";
      await this.shell.getIdentificationWorkspace().importCsvDataset(csvText, {
        id,
        splitTrainHoldout: true,
        trainFraction,
      });
      this.closeNewObjectModal();
    } catch (err: unknown) {
      this.showModalError(err);
    }
  }

  private syncVisibility(): void {
    setElHidden(this.dockAsideEl, this.collapsed);
    toggleElCssClass(this.workbenchShellEl, "dock-collapsed", this.collapsed);
    this.toggleBtnEl?.setAttribute("aria-expanded", this.collapsed ? "false" : "true");
    setElHidden(this.modalEl, this.shell.getOpenModalId() !== "modal-new-object");
  }

  private collectModelsAndPlants(): RegisteredTypedObject[] {
    const typed = this.shell.getTypedWorkspace();
    const byKey = new Map<string, RegisteredTypedObject>();
    for (const role of ["statespacePlant", "frequencyPlant", "tsModel", "reuseSource"] as const) {
      for (const item of typed.listSelectableObjectsForRole(role)) {
        if (!byKey.has(item.key)) {
          byKey.set(item.key, item);
        }
      }
    }
    return Array.from(byKey.values());
  }

  private async handleDockAction(
    action: string,
    objectKey: string | null,
  ): Promise<void> {
    const typed = this.shell.getTypedWorkspace();
    const lqr = this.shell.getLqrWorkspace();
    const idWs = this.shell.getIdentificationWorkspace();

    try {
      if (action === "focus-lqr-controller") {
        this.shell.switchTab("statespace");
        return;
      }
      if (action === "focus-siso-controller") {
        this.shell.switchTab("siso_frequency");
        return;
      }
      if (!objectKey) return;

      if (action === "inspect-pending-identified") {
        const pending = typed.getPendingIdentifiedModel();
        if (pending) {
          this.onInspectObject?.({
            key: `pending:${pending.model_ref.id}#${pending.model_ref.revision}`,
            label: `${pending.model_ref.id}#r${pending.model_ref.revision} (IdentifiedModel)`,
            value: pending.model,
          });
        }
        return;
      }

      if (action === "route-pending-siso") {
        await idWs.reuseIdentifiedModel({
          targetKind: "native",
          registerIdentifiedIfPending: true,
          registerDerived: true,
          applyToDestination: "siso_frequency",
        });
        return;
      }

      if (action === "route-pending-lqr") {
        await idWs.reuseIdentifiedModel({
          targetKind: "StateSpace",
          registerIdentifiedIfPending: true,
          registerDerived: true,
          applyToDestination: "lqr",
        });
        return;
      }

      const obj = this.findDockObjectByKey(objectKey);
      if (!obj) return;
      const ref: CanonicalObjectRef = { id: obj.id, revision: obj.revision };

      if (action === "inspect-object") {
        this.onInspectObject?.({
          key: `obj:${obj.key}`,
          label: `${obj.id}#r${obj.revision} (${obj.kind})`,
          value: obj.value,
        });
        return;
      }

      if (action === "dock-edit-plant") {
        this.openEditSystemModal(obj.key);
        return;
      }

      if (action === "dock-route-lmi") {
        if (isTsModelKind(obj.kind)) {
          typed.selectRef("tsModel", ref, { allowHistoricalDowngrade: true });
        } else if (obj.kind === "StateSpace") {
          typed.selectRef("statespacePlant", ref, { allowHistoricalDowngrade: true });
        }
        this.onRouteToLmi?.(obj.key);
        this.shell.switchTab("optimization_lmi");
        return;
      }

      if (action === "dock-route-ts-modeling" && isTsModelKind(obj.kind)) {
        typed.selectRef("tsModel", ref, { allowHistoricalDowngrade: true });
        this.shell.switchTab("ts_modeling");
        this.onRouteToTsModeling?.(obj.key);
        return;
      }

      if (action === "route-identification" && obj.kind === "Dataset") {
        typed.selectRef("dataset", ref, { allowHistoricalDowngrade: true });
        this.shell.switchTab("identification");
        return;
      }

      if (action === "route-siso") {
        if (obj.kind === "TransferFunction" || obj.kind === "StateSpace") {
          typed.selectRef("frequencyPlant", ref, { allowHistoricalDowngrade: true });
          this.shell.switchTab("siso_frequency");
        } else if (obj.kind === "IdentifiedModel") {
          await typed.reuseModel({ sourceRef: ref, targetKind: "native" });
          await typed.registerPendingDerivedModel({ selectCompatible: true });
          this.shell.switchTab("siso_frequency");
        }
        return;
      }

      if (action === "route-lqr") {
        if (obj.kind === "StateSpace") {
          lqr.updatePlant(structuredClone(obj.value) as unknown as CanonicalStateSpaceModel);
          this.shell.switchTab("statespace");
        } else if (obj.kind === "TransferFunction" || obj.kind === "IdentifiedModel") {
          await typed.reuseModel({ sourceRef: ref, targetKind: "StateSpace" });
          await typed.registerPendingDerivedModel({ selectCompatible: true });
          this.shell.applySelectedPlantToLqr();
          this.shell.switchTab("statespace");
        }
      }
    } catch (err: unknown) {
      this.shell.presentError(err);
    }
  }

  private findDockObjectByKey(key: string): RegisteredTypedObject | null {
    const typed = this.shell.getTypedWorkspace();
    for (const item of typed.listRegisteredObjects()) {
      if (item.key === key) return item;
    }
    for (const item of this.collectModelsAndPlants()) {
      if (item.key === key) return item;
    }
    return null;
  }

  public render(): void {
    this.syncVisibility();
    if (!this.dockContentEl) return;

    const typed = this.shell.getTypedWorkspace();
    const lqr = this.shell.getLqrWorkspace();
    const siso = this.shell.getSisoWorkspace();
    const decimals = this.shell.getDisplayDecimals();

    const datasets = typed.listRegisteredObjects(["Dataset"]);
    const models = this.collectModelsAndPlants();
    const pendingId = typed.getPendingIdentifiedModel();
    const showPendingId =
      pendingId !== null && !pendingId.registered;

    const selDataset = typed.getEffectiveSelection("dataset")?.ref ?? null;
    const selValDataset = typed.getEffectiveSelection("valDataset")?.ref ?? null;
    const selFreq = typed.getEffectiveSelection("frequencyPlant")?.ref ?? null;
    const selTs = typed.getEffectiveSelection("tsModel")?.ref ?? null;
    const activeLqrPlant = lqr.getPlant();
    const committedLqr = lqr.getCommittedSnapshot();
    const lqrInvalidated = lqr.isControllerInvalidated();
    const sisoMargins = siso.getMarginsView();
    const sisoGain = siso.getCompensatorGain();

    const dynamicCtrls = typed.listRegisteredObjects(["DynamicController"]);

    const renderKey = JSON.stringify({
      decimals,
      datasets: datasets.map((d) => [d.key, d.summary]),
      models: models.map((m) => [m.key, m.summary, formatDockObjectSummary(m, decimals)]),
      dynamicCtrls: dynamicCtrls.map((c) => [c.key, c.summary]),
      pendingId: showPendingId ? pendingId?.model_ref : null,
      selDataset,
      selValDataset,
      selFreq,
      selTs,
      activeLqrId: [activeLqrPlant.id, activeLqrPlant.revision],
      committedRev: committedLqr?.project_revision ?? null,
      committedK: committedLqr?.K?.data ?? null,
      lqrInvalidated,
      sisoGain,
      sisoStable: sisoMargins?.closed_loop_stable ?? null,
    });
    if (renderKey === this.lastRenderKey) {
      return;
    }
    this.lastRenderKey = renderKey;

    const datasetsHtml =
      datasets.length === 0
        ? `<p class="dock-empty">Nenhuma série temporal carregada.</p>`
        : datasets
            .map((ds) => {
              const isTrain =
                selDataset?.id === ds.id && selDataset?.revision === ds.revision;
              const isVal =
                selValDataset?.id === ds.id && selValDataset?.revision === ds.revision;
              const badges = [
                isTrain ? `<span class="badge badge-exact">Treino</span>` : "",
                isVal ? `<span class="badge badge-sufficient">Holdout</span>` : "",
              ]
                .filter(Boolean)
                .join(" ");
              return [
                `<div class="dock-item" data-dock-item-key="${escapeHtml(ds.key)}">`,
                `<div class="dock-item-head">`,
                `<button type="button" class="dock-item-link" data-dock-action="inspect-object" data-object-key="${escapeHtml(ds.key)}" title="${escapeHtml(ds.id)}#r${ds.revision}">${renderDockCardTitleHtml(ds.id, ds.revision)}</button>`,
                badges,
                `<button type="button" class="touch-control btn-secondary btn-small dock-remove-btn" data-action="dock-remove-item" data-obj-id="${escapeHtml(ds.id)}" data-obj-rev="${ds.revision}" aria-label="Remover ${escapeHtml(ds.id)} revisão ${ds.revision}" title="Remover item">×</button>`,
                `</div>`,
                `<div class="dock-item-summary">${escapeHtml(formatDockObjectSummary(ds, decimals))}</div>`,
                `<div class="dock-item-actions">`,
                `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="route-identification" data-object-key="${escapeHtml(ds.key)}">→ Identificação</button>`,
                `</div>`,
                `</div>`,
              ].join("");
            })
            .join("");

    const pendingModelHtml = showPendingId && pendingId
      ? [
          `<div class="dock-item dock-item-pending" data-dock-item-key="pending-id">`,
          `<div class="dock-item-head">`,
          `<button type="button" class="dock-item-link" data-dock-action="inspect-pending-identified" data-object-key="pending-id" title="${escapeHtml(pendingId.model_ref.id)}#r${pendingId.model_ref.revision}">${renderDockCardTitleHtml(pendingId.model_ref.id, pendingId.model_ref.revision)}</button>`,
          `<span class="badge badge-approximate">Não validado em holdout</span>`,
          `</div>`,
          `<div class="dock-item-summary">${escapeHtml(pendingId.algorithm)} • aguardando validação</div>`,
          `<div class="dock-item-actions">`,
          `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="route-pending-siso" data-object-key="pending-id">→ SISO</button>`,
          `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="route-pending-lqr" data-object-key="pending-id">→ SS/LQR</button>`,
          `</div>`,
          `</div>`,
        ].join("")
      : "";

    const modelsHtml =
      models.length === 0 && !showPendingId
        ? `<p class="dock-empty">Nenhuma planta ou modelo na sessão.</p>`
        : pendingModelHtml +
          models
            .map((m) => {
              const isLqr =
                m.id === activeLqrPlant.id && m.revision === activeLqrPlant.revision;
              const isSiso =
                selFreq?.id === m.id && selFreq?.revision === m.revision;
              const isTsActive =
                selTs?.id === m.id && selTs?.revision === m.revision;
              const isTsKind = isTsModelKind(m.kind);
              const badges = [
                isLqr ? `<span class="badge badge-exact">Ativo LQR</span>` : "",
                isSiso ? `<span class="badge badge-sufficient">Ativo SISO</span>` : "",
                isTsActive ? `<span class="badge badge-stable">Ativo LMI/TS</span>` : "",
                m.kind === "IdentifiedModel"
                  ? `<span class="badge badge-stable">Pronto para projeto</span>`
                  : "",
              ]
                .filter(Boolean)
                .join(" ");

              const actionBtns: string[] = [];
              if (
                m.kind === "StateSpace" ||
                m.kind === "TransferFunction" ||
                m.kind === "IdentifiedModel"
              ) {
                actionBtns.push(
                  `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="route-siso" data-object-key="${escapeHtml(m.key)}">→ SISO</button>`,
                  `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="route-lqr" data-object-key="${escapeHtml(m.key)}">→ SS/LQR</button>`,
                );
              }
              if (m.kind === "StateSpace" || isTsKind) {
                actionBtns.push(
                  `<button type="button" class="touch-control btn-secondary btn-small" data-action="dock-route-lmi" data-dock-action="dock-route-lmi" data-object-key="${escapeHtml(m.key)}">→ LMIs</button>`,
                );
              }
              if (
                isTsKind &&
                isPlainObject(m.value) &&
                isPlainObject(m.value.provenance) &&
                isPlainObject(m.value.provenance.ts_derivation)
              ) {
                actionBtns.push(
                  `<button type="button" class="touch-control btn-secondary btn-small" data-action="dock-route-ts-modeling" data-dock-action="dock-route-ts-modeling" data-object-key="${escapeHtml(m.key)}">→ Receita TS</button>`,
                );
              }
              if (
                m.kind === "TransferFunction" ||
                m.kind === "StateSpace" ||
                isTsKind
              ) {
                actionBtns.push(
                  `<button type="button" class="touch-control btn-secondary btn-small" data-action="dock-edit-plant" data-dock-action="dock-edit-plant" data-object-key="${escapeHtml(m.key)}">Editar</button>`,
                );
              }
              const actionsHtml = actionBtns.join("");

              const isRegistered = typed.getRegisteredObject({ id: m.id, revision: m.revision }) !== null;
              const removeBtnHtml = isRegistered
                ? `<button type="button" class="touch-control btn-secondary btn-small dock-remove-btn" data-action="dock-remove-item" data-obj-id="${escapeHtml(m.id)}" data-obj-rev="${m.revision}" aria-label="Remover ${escapeHtml(m.id)} revisão ${m.revision}" title="Remover item">×</button>`
                : "";
              return [
                `<div class="dock-item" data-dock-item-key="${escapeHtml(m.key)}">`,
                `<div class="dock-item-head">`,
                `<button type="button" class="dock-item-link" data-dock-action="inspect-object" data-object-key="${escapeHtml(m.key)}" title="${escapeHtml(m.id)}#r${m.revision}">${renderDockCardTitleHtml(m.id, m.revision)}</button>`,
                badges,
                removeBtnHtml,
                `</div>`,
                `<div class="dock-item-summary">${escapeHtml(formatDockObjectSummary(m, decimals))}</div>`,
                actionsHtml ? `<div class="dock-item-actions">${actionsHtml}</div>` : "",
                `</div>`,
              ].join("");
            })
            .join("");

    const ctrlCards: string[] = [];
    if (committedLqr?.K) {
      const kFmt = formatMatrixDisplay(
        committedLqr.K.data,
        committedLqr.K.shape[0] ?? 1,
        committedLqr.K.shape[1] ?? committedLqr.K.data.length,
        decimals,
      )
        .map((row) => `[${row.join(", ")}]`)
        .join("; ");
      const statusBadge = lqrInvalidated
        ? `<span class="badge badge-approximate">Desatualizado</span>`
        : `<span class="badge badge-exact">Confirmado</span>`;
      const ctrlId = committedLqr.controller_ref?.id ?? `K_lqr_r${committedLqr.project_revision}`;
      const signLabel = committedLqr.feedback_sign === "negative" ? "u = -Kx" : "u = +Kx";
      ctrlCards.push(
        [
          `<div class="dock-item" data-dock-item-key="ctrl-lqr">`,
          `<div class="dock-item-head"><strong class="dock-item-title-block" title="${escapeHtml(ctrlId)}">${renderDockCardTitleHtml(ctrlId, null)}</strong> ${statusBadge}</div>`,
          `<div class="dock-item-summary">K = ${escapeHtml(kFmt)} • ${escapeHtml(signLabel)}</div>`,
          `<div class="dock-item-actions">`,
          `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="focus-lqr-controller">→ SS/LQR</button>`,
          `</div>`,
          `</div>`,
        ].join(""),
      );
    }
    if (sisoMargins !== null || sisoGain !== 1.0) {
      const stabBadge =
        sisoMargins?.closed_loop_stable === true
          ? `<span class="badge badge-exact">MF Estável</span>`
          : sisoMargins?.closed_loop_stable === false
            ? `<span class="badge badge-experimental">MF Instável</span>`
            : `<span class="badge badge-sufficient">SISO</span>`;
      ctrlCards.push(
        [
          `<div class="dock-item" data-dock-item-key="ctrl-siso">`,
          `<div class="dock-item-head"><strong>Compensador C(s)</strong> ${stabBadge}</div>`,
          `<div class="dock-item-summary">Ganho K = ${escapeHtml(formatNumericDisplay(sisoGain, decimals))}</div>`,
          `<div class="dock-item-actions">`,
          `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="focus-siso-controller">→ SISO</button>`,
          `</div>`,
          `</div>`,
        ].join(""),
      );
    }
    for (const dynCtrl of dynamicCtrls) {
      ctrlCards.push(
        [
          `<div class="dock-item" data-dock-item-key="${escapeHtml(dynCtrl.key)}">`,
          `<div class="dock-item-head">`,
          `<button type="button" class="dock-item-link" data-dock-action="inspect-object" data-object-key="${escapeHtml(dynCtrl.key)}" title="${escapeHtml(dynCtrl.id)}#r${dynCtrl.revision}">${renderDockCardTitleHtml(dynCtrl.id, dynCtrl.revision)}</button>`,
          `<span class="badge badge-exact">LQG / Dinâmico</span>`,
          `<button type="button" class="touch-control btn-secondary btn-small dock-remove-btn" data-action="dock-remove-item" data-obj-id="${escapeHtml(dynCtrl.id)}" data-obj-rev="${dynCtrl.revision}" aria-label="Remover ${escapeHtml(dynCtrl.id)} revisão ${dynCtrl.revision}" title="Remover item">×</button>`,
          `</div>`,
          `<div class="dock-item-summary">${escapeHtml(dynCtrl.summary)}</div>`,
          `<div class="dock-item-actions">`,
          `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="focus-lqr-controller">→ SS/LQR</button>`,
          `</div>`,
          `</div>`,
        ].join(""),
      );
    }
    const controllersHtml =
      ctrlCards.length > 0
        ? ctrlCards.join("")
        : `<p class="dock-empty">Nenhum controlador confirmado ainda.</p>`;

    this.dockContentEl.innerHTML = [
      `<section class="dock-group" data-dock-group="datasets" aria-label="Séries Temporais">`,
      `<h3 class="dock-group-title">Séries Temporais (Dados)</h3>`,
      datasetsHtml,
      `</section>`,
      `<section class="dock-group" data-dock-group="models" aria-label="Plantas e Modelos">`,
      `<h3 class="dock-group-title">Plantas &amp; Modelos</h3>`,
      modelsHtml,
      `</section>`,
      `<section class="dock-group" data-dock-group="controllers" aria-label="Controladores Projetados">`,
      `<h3 class="dock-group-title">Controladores Projetados</h3>`,
      controllersHtml,
      `</section>`,
    ].join("\n");

    const actionButtons = Array.from(
      this.dockContentEl.querySelectorAll<HTMLElement>("[data-dock-action]"),
    );
    for (const btn of actionButtons) {
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-dock-action");
        const key = btn.getAttribute("data-object-key");
        if (action) {
          void this.handleDockAction(action, key);
        }
      });
    }

    const removeButtons = Array.from(
      this.dockContentEl.querySelectorAll<HTMLElement>('[data-action="dock-remove-item"]'),
    );
    for (const btn of removeButtons) {
      btn.addEventListener("click", () => {
        const objId = btn.getAttribute("data-obj-id");
        const objRevRaw = btn.getAttribute("data-obj-rev");
        const objRev = objRevRaw !== null ? Number(objRevRaw) : NaN;
        if (objId && Number.isInteger(objRev)) {
          this.shell.getTypedWorkspace().removeRegisteredObject(objId, objRev);
        }
      });
    }
  }
}
