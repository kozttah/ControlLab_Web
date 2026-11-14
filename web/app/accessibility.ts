/**
 * Utilitários de acessibilidade WCAG 2.2 AA, cálculo programático de contraste,
 * navegação por teclado (tablist/slider), metadados de toque (>= 44px),
 * pilha de restauração de foco, região aria-live e formatação numérica não mutável
 * (CL-DIR-001 Seções 7.3, 13.10, R-26).
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping e erasableSyntaxOnly.
 */

import { ControlLabBridgeError } from "../bridge/protocol.ts";

export const MIN_TOUCH_TARGET_PX = 44 as const;
export const WCAG_AA_NORMAL_TEXT_RATIO = 4.5 as const;
export const WCAG_AA_LARGE_TEXT_RATIO = 3.0 as const;
export const WCAG_AA_UI_COMPONENT_RATIO = 3.0 as const;

export interface RgbColor {
  r: number;
  g: number;
  b: number;
}

export type ContrastTargetKind = "normal_text" | "large_text" | "ui_component";

export type AccessibilityThemeMode = "standard_aa" | "high_contrast";

export interface AccessibilityThemeTokens {
  mode: AccessibilityThemeMode;
  background: string;
  surface: string;
  surfaceAlt: string;
  textPrimary: string;
  textSecondary: string;
  border: string;
  accent: string;
  accentText: string;
  focusRing: string;
  statusSuccessBg: string;
  statusSuccessFg: string;
  statusWarningBg: string;
  statusWarningFg: string;
  statusErrorBg: string;
  statusErrorFg: string;
  statusInfoBg: string;
  statusInfoFg: string;
  chartOpenLoop: string;
  chartClosedLoop: string;
  chartPreview: string;
  chartGrid: string;
  chartAxis: string;
  chartOverlayExact: string;
  chartOverlaySufficient: string;
  chartOverlayHeuristic: string;
}

export const STANDARD_AA_THEME: AccessibilityThemeTokens = {
  mode: "standard_aa",
  background: "#F8FAFC",
  surface: "#FFFFFF",
  surfaceAlt: "#EFF4F9",
  textPrimary: "#0F172A",
  textSecondary: "#334155",
  border: "#64748B",
  accent: "#1D4ED8",
  accentText: "#FFFFFF",
  focusRing: "#0F172A",
  statusSuccessBg: "#ECFDF5",
  statusSuccessFg: "#065F46",
  statusWarningBg: "#FFFBEB",
  statusWarningFg: "#92400E",
  statusErrorBg: "#FEF2F2",
  statusErrorFg: "#991B1B",
  statusInfoBg: "#EFF6FF",
  statusInfoFg: "#1E40AF",
  chartOpenLoop: "#B45309",
  chartClosedLoop: "#1D4ED8",
  chartPreview: "#6D28D9",
  chartGrid: "#CBD5E1",
  chartAxis: "#1E293B",
  chartOverlayExact: "#047857",
  chartOverlaySufficient: "#1D4ED8",
  chartOverlayHeuristic: "#B45309",
};

export const HIGH_CONTRAST_THEME: AccessibilityThemeTokens = {
  mode: "high_contrast",
  background: "#000000",
  surface: "#0B0F17",
  surfaceAlt: "#141B29",
  textPrimary: "#FFFFFF",
  textSecondary: "#E2E8F0",
  border: "#E2E8F0",
  accent: "#93C5FD",
  accentText: "#000000",
  focusRing: "#FACC15",
  statusSuccessBg: "#052E16",
  statusSuccessFg: "#86EFAC",
  statusWarningBg: "#451A03",
  statusWarningFg: "#FDE047",
  statusErrorBg: "#450A0A",
  statusErrorFg: "#FCA5A5",
  statusInfoBg: "#172554",
  statusInfoFg: "#BAE6FD",
  chartOpenLoop: "#FBBF24",
  chartClosedLoop: "#60A5FA",
  chartPreview: "#F472B6",
  chartGrid: "#475569",
  chartAxis: "#F8FAFC",
  chartOverlayExact: "#4ADE80",
  chartOverlaySufficient: "#93C5FD",
  chartOverlayHeuristic: "#FBBF24",
};

export function getThemeTokens(mode: AccessibilityThemeMode): AccessibilityThemeTokens {
  return mode === "high_contrast" ? HIGH_CONTRAST_THEME : STANDARD_AA_THEME;
}

export function parseColorToRgb(color: string): RgbColor {
  const trimmed = color.trim();
  if (trimmed.startsWith("#")) {
    const hex = trimmed.slice(1);
    if (/^[0-9a-fA-F]{3}$/.test(hex)) {
      return {
        r: parseInt(hex[0] + hex[0], 16),
        g: parseInt(hex[1] + hex[1], 16),
        b: parseInt(hex[2] + hex[2], 16),
      };
    }
    if (/^[0-9a-fA-F]{6}$/.test(hex)) {
      return {
        r: parseInt(hex.slice(0, 2), 16),
        g: parseInt(hex.slice(2, 4), 16),
        b: parseInt(hex.slice(4, 6), 16),
      };
    }
  }
  const rgbMatch = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*[\d.]+\s*)?\)$/i.exec(
    trimmed,
  );
  if (rgbMatch) {
    const r = Number(rgbMatch[1]);
    const g = Number(rgbMatch[2]);
    const b = Number(rgbMatch[3]);
    if (r <= 255 && g <= 255 && b <= 255) {
      return { r, g, b };
    }
  }
  throw new ControlLabBridgeError(
    "VALIDATION_ERROR",
    `Cor inválida para cálculo de contraste WCAG: '${color}'.`,
    { parameters: { color } },
  );
}

function linearizeChannel(channel255: number): number {
  const c = Math.min(255, Math.max(0, channel255)) / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function relativeLuminance(color: string | RgbColor): number {
  const rgb = typeof color === "string" ? parseColorToRgb(color) : color;
  const rLin = linearizeChannel(rgb.r);
  const gLin = linearizeChannel(rgb.g);
  const bLin = linearizeChannel(rgb.b);
  return 0.2126 * rLin + 0.7152 * gLin + 0.0722 * bLin;
}

export function contrastRatio(fg: string | RgbColor, bg: string | RgbColor): number {
  const l1 = relativeLuminance(fg);
  const l2 = relativeLuminance(bg);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

export function requiredContrastRatio(targetKind: ContrastTargetKind): number {
  switch (targetKind) {
    case "normal_text":
      return WCAG_AA_NORMAL_TEXT_RATIO;
    case "large_text":
      return WCAG_AA_LARGE_TEXT_RATIO;
    case "ui_component":
      return WCAG_AA_UI_COMPONENT_RATIO;
  }
}

export function meetsWcagAA(
  fg: string | RgbColor,
  bg: string | RgbColor,
  targetKind: ContrastTargetKind = "normal_text",
): boolean {
  const ratio = contrastRatio(fg, bg);
  return ratio >= requiredContrastRatio(targetKind);
}

export interface TouchTargetMetadata {
  minTouchTargetPx: number;
  widthPx: number;
  heightPx: number;
  ariaLabel: string;
  role: string;
}

export function createTouchTargetMetadata(options: {
  ariaLabel: string;
  role: string;
  widthPx?: number;
  heightPx?: number;
}): TouchTargetMetadata {
  const widthPx = Math.max(MIN_TOUCH_TARGET_PX, options.widthPx ?? MIN_TOUCH_TARGET_PX);
  const heightPx = Math.max(MIN_TOUCH_TARGET_PX, options.heightPx ?? MIN_TOUCH_TARGET_PX);
  return {
    minTouchTargetPx: MIN_TOUCH_TARGET_PX,
    widthPx,
    heightPx,
    ariaLabel: options.ariaLabel,
    role: options.role,
  };
}

export function validateTouchTarget(dims: {
  widthPx: number;
  heightPx: number;
}): { valid: boolean; minTouchTargetPx: number; reason?: string } {
  if (
    !Number.isFinite(dims.widthPx) ||
    !Number.isFinite(dims.heightPx) ||
    dims.widthPx < MIN_TOUCH_TARGET_PX ||
    dims.heightPx < MIN_TOUCH_TARGET_PX
  ) {
    return {
      valid: false,
      minTouchTargetPx: MIN_TOUCH_TARGET_PX,
      reason: `Área de toque (${dims.widthPx}x${dims.heightPx}px) inferior ao mínimo WCAG 2.2 / tablet (${MIN_TOUCH_TARGET_PX}x${MIN_TOUCH_TARGET_PX}px).`,
    };
  }
  return { valid: true, minTouchTargetPx: MIN_TOUCH_TARGET_PX };
}

export interface AccessibleTabItem {
  id: string;
  label: string;
  disabled?: boolean;
}

export interface TablistKeyResult {
  nextIndex: number;
  activeTabId: string;
  handled: boolean;
  preventDefault: boolean;
  escaped: boolean;
}

export function handleTablistKeyDown(
  key: string,
  tabs: readonly AccessibleTabItem[],
  currentIndex: number,
  options?: { orientation?: "horizontal" | "vertical" },
): TablistKeyResult {
  if (tabs.length === 0) {
    return {
      nextIndex: -1,
      activeTabId: "",
      handled: false,
      preventDefault: false,
      escaped: false,
    };
  }

  const safeIdx =
    currentIndex >= 0 && currentIndex < tabs.length ? currentIndex : 0;
  const orientation = options?.orientation ?? "horizontal";
  const nextKey = orientation === "horizontal" ? "ArrowRight" : "ArrowDown";
  const prevKey = orientation === "horizontal" ? "ArrowLeft" : "ArrowUp";

  const findNextEnabled = (startIdx: number, step: 1 | -1): number => {
    for (let offset = 1; offset <= tabs.length; offset += 1) {
      const candidate = (startIdx + step * offset + tabs.length) % tabs.length;
      if (!tabs[candidate].disabled) {
        return candidate;
      }
    }
    return safeIdx;
  };

  if (key === nextKey) {
    const nextIndex = findNextEnabled(safeIdx, 1);
    return {
      nextIndex,
      activeTabId: tabs[nextIndex].id,
      handled: true,
      preventDefault: true,
      escaped: false,
    };
  }

  if (key === prevKey) {
    const nextIndex = findNextEnabled(safeIdx, -1);
    return {
      nextIndex,
      activeTabId: tabs[nextIndex].id,
      handled: true,
      preventDefault: true,
      escaped: false,
    };
  }

  if (key === "Home") {
    const firstEnabled = tabs.findIndex((t) => !t.disabled);
    const nextIndex = firstEnabled >= 0 ? firstEnabled : safeIdx;
    return {
      nextIndex,
      activeTabId: tabs[nextIndex].id,
      handled: true,
      preventDefault: true,
      escaped: false,
    };
  }

  if (key === "End") {
    let lastEnabled = safeIdx;
    for (let i = tabs.length - 1; i >= 0; i -= 1) {
      if (!tabs[i].disabled) {
        lastEnabled = i;
        break;
      }
    }
    return {
      nextIndex: lastEnabled,
      activeTabId: tabs[lastEnabled].id,
      handled: true,
      preventDefault: true,
      escaped: false,
    };
  }

  if (key === "Escape") {
    return {
      nextIndex: safeIdx,
      activeTabId: tabs[safeIdx].id,
      handled: true,
      preventDefault: true,
      escaped: true,
    };
  }

  return {
    nextIndex: safeIdx,
    activeTabId: tabs[safeIdx].id,
    handled: false,
    preventDefault: false,
    escaped: false,
  };
}

export function getTabAriaAttributes(
  tabId: string,
  panelId: string,
  selected: boolean,
): Record<string, string> {
  return {
    id: `tab-${tabId}`,
    role: "tab",
    "aria-selected": selected ? "true" : "false",
    "aria-controls": panelId,
    tabindex: selected ? "0" : "-1",
  };
}

export function getTabPanelAriaAttributes(
  panelId: string,
  tabId: string,
  hidden: boolean,
): Record<string, string> {
  return {
    id: panelId,
    role: "tabpanel",
    "aria-labelledby": `tab-${tabId}`,
    tabindex: "0",
    ...(hidden ? { hidden: "true", "aria-hidden": "true" } : {}),
  };
}

export interface AccessibleSliderConfig {
  min: number;
  max: number;
  step: number;
  largeStep?: number;
  value: number;
  label: string;
  unit?: string;
}

export interface SliderKeyResult {
  nextValue: number;
  committed: boolean;
  cancelled: boolean;
  handled: boolean;
  preventDefault: boolean;
}

function clampAndRoundStep(val: number, min: number, max: number, step: number): number {
  const clamped = Math.min(max, Math.max(min, val));
  if (step <= 0 || !Number.isFinite(step)) {
    return clamped;
  }
  const decimals = Math.max(0, Math.min(12, (step.toString().split(".")[1] ?? "").length));
  return Number(clamped.toFixed(decimals));
}

export function handleSliderKeyDown(
  key: string,
  config: AccessibleSliderConfig,
): SliderKeyResult {
  const largeStep = config.largeStep ?? config.step * 10;

  switch (key) {
    case "ArrowRight":
    case "ArrowUp":
      return {
        nextValue: clampAndRoundStep(config.value + config.step, config.min, config.max, config.step),
        committed: true,
        cancelled: false,
        handled: true,
        preventDefault: true,
      };
    case "ArrowLeft":
    case "ArrowDown":
      return {
        nextValue: clampAndRoundStep(config.value - config.step, config.min, config.max, config.step),
        committed: true,
        cancelled: false,
        handled: true,
        preventDefault: true,
      };
    case "PageUp":
      return {
        nextValue: clampAndRoundStep(config.value + largeStep, config.min, config.max, config.step),
        committed: true,
        cancelled: false,
        handled: true,
        preventDefault: true,
      };
    case "PageDown":
      return {
        nextValue: clampAndRoundStep(config.value - largeStep, config.min, config.max, config.step),
        committed: true,
        cancelled: false,
        handled: true,
        preventDefault: true,
      };
    case "Home":
      return {
        nextValue: config.min,
        committed: true,
        cancelled: false,
        handled: true,
        preventDefault: true,
      };
    case "End":
      return {
        nextValue: config.max,
        committed: true,
        cancelled: false,
        handled: true,
        preventDefault: true,
      };
    case "Escape":
      return {
        nextValue: config.value,
        committed: false,
        cancelled: true,
        handled: true,
        preventDefault: true,
      };
    case "Enter":
      return {
        nextValue: config.value,
        committed: true,
        cancelled: false,
        handled: true,
        preventDefault: true,
      };
    default:
      return {
        nextValue: config.value,
        committed: false,
        cancelled: false,
        handled: false,
        preventDefault: false,
      };
  }
}

export function getSliderAriaAttributes(
  config: AccessibleSliderConfig,
  decimals = 3,
): Record<string, string> {
  const formatted = formatNumericDisplay(config.value, decimals);
  const valueText = config.unit ? `${formatted} ${config.unit}` : formatted;
  return {
    role: "slider",
    tabindex: "0",
    "aria-label": config.label,
    "aria-valuemin": String(config.min),
    "aria-valuemax": String(config.max),
    "aria-valuenow": String(config.value),
    "aria-valuetext": valueText,
  };
}

export interface FocusTargetLike {
  id: string;
  focus?: () => void;
}

interface ModalFocusEntry {
  modalId: string;
  target: FocusTargetLike;
}

/**
 * Pilha determinística de restauração de foco para modais e painéis sobrepostos (WCAG 2.2 AA).
 */
export class FocusRestorer {
  private readonly stack: ModalFocusEntry[] = [];
  private activeFocusId: string | null = null;

  public getActiveFocusId(): string | null {
    return this.activeFocusId;
  }

  public setActiveFocusId(id: string | null): void {
    this.activeFocusId = id;
  }

  public pushModalTrigger(
    target: FocusTargetLike | string,
    modalId: string,
  ): void {
    const resolved: FocusTargetLike =
      typeof target === "string" ? { id: target } : target;
    this.stack.push({ modalId, target: resolved });
  }

  public popAndRestoreFocus(modalId?: string): FocusTargetLike | null {
    if (this.stack.length === 0) {
      return null;
    }
    let popped: ModalFocusEntry | undefined;
    if (modalId !== undefined) {
      for (let i = this.stack.length - 1; i >= 0; i -= 1) {
        if (this.stack[i].modalId === modalId) {
          popped = this.stack.splice(i, 1)[0];
          break;
        }
      }
    } else {
      popped = this.stack.pop();
    }
    if (!popped) {
      return null;
    }
    this.activeFocusId = popped.target.id;
    try {
      popped.target.focus?.();
    } catch {
      // Elementos removidos do DOM não devem derrubar a restauração lógica
    }
    return popped.target;
  }

  public peekStack(): ReadonlyArray<{ modalId: string; targetId: string }> {
    return this.stack.map((item) => ({
      modalId: item.modalId,
      targetId: item.target.id,
    }));
  }

  public clear(): void {
    this.stack.length = 0;
  }
}

export type LivePoliteness = "polite" | "assertive";
export type AnnouncementCategory =
  | "status"
  | "error"
  | "pending_commit"
  | "committed"
  | "preview"
  | "export_blocked";

export interface LiveAnnouncement {
  id: number;
  message: string;
  politeness: LivePoliteness;
  category: AnnouncementCategory;
  timestamp: string;
}

export type LiveAnnouncementListener = (announcement: LiveAnnouncement) => void;

export class AriaLiveAnnouncer {
  private seq = 0;
  private politeText = "";
  private assertiveText = "";
  private readonly history: LiveAnnouncement[] = [];
  private readonly listeners = new Set<LiveAnnouncementListener>();

  public announce(
    message: string,
    politeness: LivePoliteness = "polite",
    category: AnnouncementCategory = "status",
  ): LiveAnnouncement {
    this.seq += 1;
    const entry: LiveAnnouncement = {
      id: this.seq,
      message,
      politeness,
      category,
      timestamp: new Date().toISOString(),
    };
    if (politeness === "assertive") {
      this.assertiveText = message;
    } else {
      this.politeText = message;
    }
    this.history.push(entry);
    for (const listener of this.listeners) {
      try {
        listener(entry);
      } catch {
        // Ignorar falha isolada de assinante de live region
      }
    }
    return entry;
  }

  public getCurrentText(politeness: LivePoliteness): string {
    return politeness === "assertive" ? this.assertiveText : this.politeText;
  }

  public getHistory(): readonly LiveAnnouncement[] {
    return [...this.history];
  }

  public subscribe(listener: LiveAnnouncementListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  public clear(): void {
    this.politeText = "";
    this.assertiveText = "";
    this.history.length = 0;
  }
}

export interface NumericFormatOptions {
  scientificThreshold?: number;
  trimTrailingZeros?: boolean;
}

/**
 * Formata um float64 para exibição com número configurável de casas decimais
 * SEM jamais mutar o valor numérico float64 armazenado nos tensores/modelos.
 */
export function formatNumericDisplay(
  val: number,
  decimals = 4,
  options?: NumericFormatOptions,
): string {
  if (typeof val !== "number") {
    return String(val);
  }
  if (Number.isNaN(val)) {
    return "NaN";
  }
  if (!Number.isFinite(val)) {
    return val > 0 ? "Infinity" : "-Infinity";
  }
  const safeDecimals = Number.isInteger(decimals)
    ? Math.min(15, Math.max(0, decimals))
    : 4;

  const normalized = Object.is(val, -0) || Math.abs(val) === 0 ? 0 : val;
  const absVal = Math.abs(normalized);
  const sciThreshold = options?.scientificThreshold ?? 1e-4;

  let formatted: string;
  if (absVal > 0 && (absVal < sciThreshold || absVal >= 1e7)) {
    formatted = normalized.toExponential(Math.max(1, Math.min(8, safeDecimals)));
  } else {
    formatted = normalized.toFixed(safeDecimals);
    if (options?.trimTrailingZeros === true && formatted.includes(".")) {
      formatted = formatted.replace(/\.?0+$/, "");
      if (formatted === "-0") {
        formatted = "0";
      }
    }
  }
  return formatted;
}

export function formatMatrixDisplay(
  data: readonly number[],
  rows: number,
  cols: number,
  decimals = 4,
): string[][] {
  const out: string[][] = [];
  for (let r = 0; r < rows; r += 1) {
    const row: string[] = [];
    for (let c = 0; c < cols; c += 1) {
      const idx = r * cols + c;
      row.push(idx < data.length ? formatNumericDisplay(data[idx], decimals) : "—");
    }
    out.push(row);
  }
  return out;
}

export function escapeHtml(raw: string): string {
  return raw
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
