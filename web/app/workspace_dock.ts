/**
 * Dock lateral esquerdo persistente (Workspace Dock) + Modal guiado "+ Novo"
 * seguindo CL-UX-DIR-001 v1.0.0 (`WP-UX-REFACTOR-01-SHELL-DOCK`).
 *
 * Agrupa os ativos da sessão em 3 categorias de engenharia:
 * 1. Séries Temporais (Dados) — Datasets
 * 2. Plantas & Modelos — StateSpace, TransferFunction, IdentifiedModel (+ TS)
 * 3. Controladores Projetados — Ganho LQR K / Compensador SISO
 *
 * 100% compatível com erasableSyntaxOnly, verbatimModuleSyntax e FakeElement/FakeDocument.
 */

import { ControlLabBridgeError, type RealTensor } from "../bridge/protocol.ts";
import type { CanonicalStateSpaceModel } from "../features/lqr_workspace.ts";
import {
  encodeObjectRefKey,
  type CanonicalObjectRef,
  type RegisteredTypedObject,
} from "../features/typed_workspace.ts";
import {
  escapeHtml,
  formatMatrixDisplay,
  formatNumericDisplay,
} from "./accessibility.ts";
import type { ControlLabShell } from "./shell.ts";

export type NewObjectModalMode = "tf" | "ss" | "csv";

export interface DockInspectTarget {
  key: string;
  label: string;
  value: unknown;
}

export interface WorkspaceDockOptions {
  shell: ControlLabShell;
  container: HTMLElement;
  onInspectObject?: (target: DockInspectTarget) => void;
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
    return `${n}×${m} SS (p=${p}) • ${domainStr}`;
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
    `<select id="dock-example-select" class="touch-control" aria-label="Selecionar sistema de exemplo">`,
    `<option value="double_integrator">Integrador Duplo 1/s² (SS)</option>`,
    `<option value="mass_spring_damper">Massa-Mola-Amortecedor (TF)</option>`,
    `<option value="first_order_delay">1ª Ordem Estável 2/(s+3) (TF)</option>`,
    `<option value="mimo_2x2">Planta MIMO 2×2 Acoplada (SS)</option>`,
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
    `<div class="panel-actions"><button type="button" id="btn-new-ss-submit" class="touch-control btn-primary" data-action="submit-new-ss">Criar Espaço de Estados</button></div>`,
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
  private collapsed: boolean;
  private modalMode: NewObjectModalMode = "tf";
  private lastRenderKey = "";

  private readonly workbenchShellEl: HTMLElement | null;
  private readonly dockAsideEl: HTMLElement | null;
  private readonly dockContentEl: HTMLElement | null;
  private readonly toggleBtnEl: HTMLElement | null;
  private readonly openModalBtnEl: HTMLElement | null;

  private readonly modalEl: HTMLElement | null;
  private readonly modalCloseBtnEl: HTMLElement | null;
  private readonly modalErrEl: HTMLElement | null;
  private readonly modeBtnTfEl: HTMLElement | null;
  private readonly modeBtnSsEl: HTMLElement | null;
  private readonly modeBtnCsvEl: HTMLElement | null;
  private readonly panelTfEl: HTMLElement | null;
  private readonly panelSsEl: HTMLElement | null;
  private readonly panelCsvEl: HTMLElement | null;

  private readonly tfIdEl: HTMLInputElement | null;
  private readonly tfNumEl: HTMLInputElement | null;
  private readonly tfDenEl: HTMLInputElement | null;
  private readonly tfDtEl: HTMLInputElement | null;

  private readonly ssPresetEl: HTMLSelectElement | null;
  private readonly ssIdEl: HTMLInputElement | null;
  private readonly ssDtEl: HTMLInputElement | null;
  private readonly ssAEl: HTMLTextAreaElement | null;
  private readonly ssBEl: HTMLTextAreaElement | null;
  private readonly ssCEl: HTMLTextAreaElement | null;
  private readonly ssDEl: HTMLTextAreaElement | null;

  private readonly csvIdEl: HTMLInputElement | null;
  private readonly csvTrainFracEl: HTMLInputElement | null;
  private readonly csvFileEl: HTMLInputElement | null;
  private readonly csvContentEl: HTMLTextAreaElement | null;

  constructor(options: WorkspaceDockOptions) {
    this.shell = options.shell;
    this.container = options.container;
    this.onInspectObject = options.onInspectObject;
    this.collapsed = options.initialCollapsed ?? false;

    this.workbenchShellEl = this.container.querySelector<HTMLElement>(".app-workbench-shell");
    this.dockAsideEl = this.container.querySelector<HTMLElement>("#workspace-dock-aside");
    this.dockContentEl = this.container.querySelector<HTMLElement>("#workspace-dock-content");
    this.toggleBtnEl = this.container.querySelector<HTMLElement>("#btn-toggle-workspace-dock");
    this.openModalBtnEl = this.container.querySelector<HTMLElement>("#btn-open-new-object-modal");

    this.modalEl = this.container.querySelector<HTMLElement>("#workspace-new-object-modal");
    this.modalCloseBtnEl = this.container.querySelector<HTMLElement>("#new-object-modal-close");
    this.modalErrEl = this.container.querySelector<HTMLElement>("#new-object-modal-error");
    this.modeBtnTfEl = this.container.querySelector<HTMLElement>("#btn-new-mode-tf");
    this.modeBtnSsEl = this.container.querySelector<HTMLElement>("#btn-new-mode-ss");
    this.modeBtnCsvEl = this.container.querySelector<HTMLElement>("#btn-new-mode-csv");
    this.panelTfEl = this.container.querySelector<HTMLElement>("#new-obj-panel-tf");
    this.panelSsEl = this.container.querySelector<HTMLElement>("#new-obj-panel-ss");
    this.panelCsvEl = this.container.querySelector<HTMLElement>("#new-obj-panel-csv");

    this.tfIdEl = this.container.querySelector<HTMLInputElement>("#new-tf-id");
    this.tfNumEl = this.container.querySelector<HTMLInputElement>("#new-tf-num");
    this.tfDenEl = this.container.querySelector<HTMLInputElement>("#new-tf-den");
    this.tfDtEl = this.container.querySelector<HTMLInputElement>("#new-tf-dt");

    this.ssPresetEl = this.container.querySelector<HTMLSelectElement>("#new-ss-preset");
    this.ssIdEl = this.container.querySelector<HTMLInputElement>("#new-ss-id");
    this.ssDtEl = this.container.querySelector<HTMLInputElement>("#new-ss-dt");
    this.ssAEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-a");
    this.ssBEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-b");
    this.ssCEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-c");
    this.ssDEl = this.container.querySelector<HTMLTextAreaElement>("#new-ss-d");

    if (this.ssAEl && !this.ssAEl.value) this.ssAEl.value = "[[0, 1], [0, 0]]";
    if (this.ssBEl && !this.ssBEl.value) this.ssBEl.value = "[[0], [1]]";
    if (this.ssCEl && !this.ssCEl.value) this.ssCEl.value = "[[1, 0]]";
    if (this.ssDEl && !this.ssDEl.value) this.ssDEl.value = "[[0]]";

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

    this.bindEvents();
  }

  private bindEvents(): void {
    this.toggleBtnEl?.addEventListener("click", () => {
      this.toggleCollapsed();
    });
    this.openModalBtnEl?.addEventListener("click", (ev) => {
      this.openNewObjectModal((ev.currentTarget as HTMLElement | null) ?? "btn-open-new-object-modal");
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
    this.clearModalError();
    this.syncModalPanels();
    this.shell.openModal("modal-new-object", trigger ?? "btn-open-new-object-modal");
    setElHidden(this.modalEl, false);
    this.tfIdEl?.focus();
  }

  public closeNewObjectModal(): void {
    if (this.shell.getOpenModalId() === "modal-new-object") {
      this.shell.closeModal("modal-new-object");
    }
    setElHidden(this.modalEl, true);
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
    setElHidden(this.panelCsvEl, this.modalMode !== "csv");

    const modeBtns: Array<[HTMLElement | null, boolean]> = [
      [this.modeBtnTfEl, this.modalMode === "tf"],
      [this.modeBtnSsEl, this.modalMode === "ss"],
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
      const dtRaw = this.tfDtEl?.value?.trim() ?? "";
      const dtVal = dtRaw === "" ? null : Number(dtRaw);
      if (dtVal !== null && (!Number.isFinite(dtVal) || dtVal <= 0)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "dt deve ser vazio (contínuo) ou número finito > 0.",
        );
      }
      const dto = {
        schema_version: "1.0.0",
        id,
        revision: 1,
        kind: "TransferFunction",
        dt: dtVal,
        variable: dtVal === null ? "s" : "z",
        poly_order: "descending",
        num: [[makeFloat64Tensor([numCoeffs.length], numCoeffs)]],
        den: [[makeFloat64Tensor([denCoeffs.length], denCoeffs)]],
        units: { time: "s", inputs: ["u1"], outputs: ["y1"] },
        provenance: { source: "workspace_dock_modal" },
      };
      await this.shell.getTypedWorkspace().registerTypedObject(dto, {
        selectRole: "frequencyPlant",
      });
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
      const m = B[0].length;
      const p = C.length;
      const dtRaw = this.ssDtEl?.value?.trim() ?? "";
      const dtVal = dtRaw === "" ? null : Number(dtRaw);
      if (dtVal !== null && (!Number.isFinite(dtVal) || dtVal <= 0)) {
        throw new ControlLabBridgeError(
          "VALIDATION_ERROR",
          "dt deve ser vazio (contínuo) ou número finito > 0.",
        );
      }
      const dto: CanonicalStateSpaceModel = {
        schema_version: "1.0.0",
        id,
        revision: 1,
        kind: "StateSpace",
        dt: dtVal,
        state_names: Array.from({ length: n }, (_, i) => `x${i + 1}`),
        input_names: Array.from({ length: m }, (_, i) => `u${i + 1}`),
        output_names: Array.from({ length: p }, (_, i) => `y${i + 1}`),
        matrices: {
          A: makeFloat64Tensor([n, A[0].length], A.flat()),
          B: makeFloat64Tensor([B.length, m], B.flat()),
          C: makeFloat64Tensor([p, C[0].length], C.flat()),
          D: makeFloat64Tensor([D.length, D[0].length], D.flat()),
        },
        units: {
          time: "s",
          states: Array.from({ length: n }, () => ""),
          inputs: Array.from({ length: m }, () => ""),
          outputs: Array.from({ length: p }, () => ""),
        },
        provenance: { source: "workspace_dock_modal" },
      };
      await this.shell.getTypedWorkspace().registerTypedObject(dto, {
        selectRole: "statespacePlant",
      });
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
    for (const role of ["statespacePlant", "frequencyPlant", "reuseSource"] as const) {
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
    const activeLqrPlant = lqr.getPlant();
    const committedLqr = lqr.getCommittedSnapshot();
    const lqrInvalidated = lqr.isControllerInvalidated();
    const sisoMargins = siso.getMarginsView();
    const sisoGain = siso.getCompensatorGain();

    const renderKey = JSON.stringify({
      decimals,
      datasets: datasets.map((d) => [d.key, d.summary]),
      models: models.map((m) => [m.key, m.summary]),
      pendingId: showPendingId ? pendingId?.model_ref : null,
      selDataset,
      selValDataset,
      selFreq,
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
                `<button type="button" class="dock-item-link" data-dock-action="inspect-object" data-object-key="${escapeHtml(ds.key)}">${escapeHtml(ds.id)} <small>#r${ds.revision}</small></button>`,
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
          `<button type="button" class="dock-item-link" data-dock-action="inspect-pending-identified" data-object-key="pending-id">${escapeHtml(pendingId.model_ref.id)} <small>#r${pendingId.model_ref.revision}</small></button>`,
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
              const badges = [
                isLqr ? `<span class="badge badge-exact">Ativo LQR</span>` : "",
                isSiso ? `<span class="badge badge-sufficient">Ativo SISO</span>` : "",
                m.kind === "IdentifiedModel"
                  ? `<span class="badge badge-stable">Pronto para projeto</span>`
                  : "",
              ]
                .filter(Boolean)
                .join(" ");
              const canRoute =
                m.kind === "StateSpace" ||
                m.kind === "TransferFunction" ||
                m.kind === "IdentifiedModel";
              const actionsHtml = canRoute
                ? [
                    `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="route-siso" data-object-key="${escapeHtml(m.key)}">→ SISO</button>`,
                    `<button type="button" class="touch-control btn-secondary btn-small" data-dock-action="route-lqr" data-object-key="${escapeHtml(m.key)}">→ SS/LQR</button>`,
                  ].join("")
                : "";
              const isRegistered = typed.getRegisteredObject({ id: m.id, revision: m.revision }) !== null;
              const removeBtnHtml = isRegistered
                ? `<button type="button" class="touch-control btn-secondary btn-small dock-remove-btn" data-action="dock-remove-item" data-obj-id="${escapeHtml(m.id)}" data-obj-rev="${m.revision}" aria-label="Remover ${escapeHtml(m.id)} revisão ${m.revision}" title="Remover item">×</button>`
                : "";
              return [
                `<div class="dock-item" data-dock-item-key="${escapeHtml(m.key)}">`,
                `<div class="dock-item-head">`,
                `<button type="button" class="dock-item-link" data-dock-action="inspect-object" data-object-key="${escapeHtml(m.key)}">${escapeHtml(m.id)} <small>#r${m.revision}</small></button>`,
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
          `<div class="dock-item-head"><strong>${escapeHtml(ctrlId)}</strong> ${statusBadge}</div>`,
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
