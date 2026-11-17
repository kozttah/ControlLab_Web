/**
 * Contrato declarativo ToolDescriptor, registro dinâmico de ferramentas e
 * renderizador declarativo integrado com CapabilityDescriptor e selos de maturidade
 * (CL-DIR-001 Seções 5.1, 7.1, 7.3, 13.10).
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping e erasableSyntaxOnly.
 */

import {
  ControlLabBridgeError,
  ensureFiniteJson,
  isPlainObject,
  OPERATION_NAME_RE,
  type CapabilityDescriptor,
  type MaturityLevel,
} from "../bridge/protocol.ts";
import {
  createTouchTargetMetadata,
  escapeHtml,
  type TouchTargetMetadata,
} from "./accessibility.ts";

export const PROJECT_TAB_IDS = [
  "identification",
  "siso_frequency",
  "statespace",
  "mimo_frequency",
  "fuzzy_ts",
  "optimization_lmi",
] as const;

export type ProjectTabId = (typeof PROJECT_TAB_IDS)[number];

export const PROJECT_TAB_METADATA: Record<
  ProjectTabId,
  { id: ProjectTabId; label: string; shortLabel: string; ownerFront: string }
> = {
  identification: {
    id: "identification",
    label: "1. Identificação de Sistemas",
    shortLabel: "Identificação",
    ownerFront: "F4",
  },
  siso_frequency: {
    id: "siso_frequency",
    label: "2. Frequência SISO",
    shortLabel: "SISO",
    ownerFront: "F3",
  },
  statespace: {
    id: "statespace",
    label: "3. Espaço de Estados",
    shortLabel: "Espaço de Estados",
    ownerFront: "F2",
  },
  mimo_frequency: {
    id: "mimo_frequency",
    label: "4. Frequência MIMO",
    shortLabel: "MIMO",
    ownerFront: "F3",
  },
  fuzzy_ts: {
    id: "fuzzy_ts",
    label: "5. Controle Fuzzy, TS e ANFIS",
    shortLabel: "Fuzzy / TS",
    ownerFront: "F5",
  },
  optimization_lmi: {
    id: "optimization_lmi",
    label: "6. LMIs, SDPs e Síntese Robusta",
    shortLabel: "LMIs / SDP",
    ownerFront: "F6",
  },
};

export const RESULT_VERIFICATION_INDICATORS = [
  "numeric_verified",
  "preview",
  "approximate",
  "experimental",
] as const;

export type ResultVerificationIndicator =
  (typeof RESULT_VERIFICATION_INDICATORS)[number];

export const INTERACTION_MODES = [
  "immediate",
  "drag_preview_then_commit",
  "batch_async",
  "readonly_inspection",
] as const;

export type InteractionMode = (typeof INTERACTION_MODES)[number];

export type ParameterFieldType =
  | "number"
  | "integer"
  | "boolean"
  | "string"
  | "select"
  | "matrix"
  | "vector"
  | "json";

export interface ParameterFieldSchema {
  name: string;
  label: string;
  type: ParameterFieldType;
  required?: boolean;
  default_value?: unknown;
  min?: number;
  max?: number;
  step?: number;
  options?: ReadonlyArray<{ value: string; label: string }>;
  shape_hint?: string;
  unit?: string;
  description?: string;
}

export interface ToolExample {
  id: string;
  title: string;
  description: string;
  fixture_id?: string;
  parameters: Record<string, unknown>;
}

export interface ToolLimits {
  max_states?: number;
  max_samples?: number;
  hard_timeout_ms: number;
  notes: string;
}

export interface ToolDescriptor {
  id: string;
  title: string;
  description: string;
  tab: ProjectTabId;
  input_types: readonly string[];
  parameter_schema: readonly ParameterFieldSchema[];
  operation: string;
  output_types: readonly string[];
  visualizations: readonly string[];
  requirements: readonly string[];
  interaction_mode: InteractionMode;
  maturity: MaturityLevel;
  required_backend?: string;
  limits: ToolLimits;
  examples: readonly ToolExample[];
  default_indicator: ResultVerificationIndicator;
}

export interface EffectiveMaturityStatus {
  maturity: MaturityLevel;
  available: boolean;
  badgeLabel: string;
  reason?: string;
}

const MATURITY_BADGE_LABELS: Record<MaturityLevel, string> = {
  stable: "Estável",
  beta: "Beta",
  experimental: "Experimental",
  unavailable_wasm: "Indisponível em WASM",
};

const INDICATOR_LABELS: Record<ResultVerificationIndicator, string> = {
  numeric_verified: "Verificado Numericamente (Python/Fixture)",
  preview: "Preview Transitório (Não Comitado)",
  approximate: "Aproximado / Suficiente",
  experimental: "Experimental (Sujeito a Validação)",
};

export function getMaturityBadgeLabel(maturity: MaturityLevel): string {
  return MATURITY_BADGE_LABELS[maturity];
}

export function getVerificationIndicatorLabel(
  indicator: ResultVerificationIndicator,
): string {
  return INDICATOR_LABELS[indicator];
}

export function validateToolDescriptor(raw: ToolDescriptor): ToolDescriptor {
  if (typeof raw.id !== "string" || raw.id.trim().length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "ToolDescriptor.id deve ser string não vazia.",
    );
  }
  if (typeof raw.title !== "string" || raw.title.trim().length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `ToolDescriptor('${raw.id}').title deve ser string não vazia.`,
    );
  }
  if (!PROJECT_TAB_IDS.includes(raw.tab)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `ToolDescriptor('${raw.id}').tab inválido: '${String(raw.tab)}'.`,
    );
  }
  if (typeof raw.operation !== "string" || !OPERATION_NAME_RE.test(raw.operation)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `ToolDescriptor('${raw.id}').operation inválido: '${String(raw.operation)}'.`,
    );
  }
  if (!Number.isInteger(raw.limits?.hard_timeout_ms) || raw.limits.hard_timeout_ms < 1) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `ToolDescriptor('${raw.id}').limits.hard_timeout_ms deve ser inteiro >= 1.`,
    );
  }
  return {
    ...raw,
    input_types: [...raw.input_types],
    parameter_schema: raw.parameter_schema.map((p) => ({ ...p })),
    output_types: [...raw.output_types],
    visualizations: [...raw.visualizations],
    requirements: [...raw.requirements],
    limits: { ...raw.limits },
    examples: raw.examples.map((ex) => ({
      ...ex,
      parameters: ensureFiniteJson(ex.parameters, `$.examples['${ex.id}']`),
    })),
  };
}

/**
 * Resolve o estado efetivo de maturidade e disponibilidade combinando o descritor
 * declarativo da ferramenta com `CapabilityDescriptor` do motor F7.
 */
export function resolveEffectiveMaturity(
  descriptor: ToolDescriptor,
  capabilities: CapabilityDescriptor | null,
): EffectiveMaturityStatus {
  if (!capabilities) {
    return {
      maturity: descriptor.maturity,
      available: false,
      badgeLabel: getMaturityBadgeLabel(descriptor.maturity),
      reason: "Capacidades do motor ainda não verificadas.",
    };
  }

  // 1. Verifica backend explícito declarado pelo descritor (ex.: clarabel_cvxpy)
  if (descriptor.required_backend) {
    const backendInfo = capabilities.backends[descriptor.required_backend];
    if (!isPlainObject(backendInfo) || backendInfo.available !== true) {
      return {
        maturity: "unavailable_wasm", available: false,
        badgeLabel: getMaturityBadgeLabel("unavailable_wasm"),
        reason: `Backend '${descriptor.required_backend}' sem disponibilidade confirmada no ambiente atual.`,
      };
    }
    if (isPlainObject(backendInfo)) {
      const backendMat = backendInfo.maturity;
      if (backendMat === "unavailable_wasm") {
        return {
          maturity: "unavailable_wasm",
          available: false,
          badgeLabel: getMaturityBadgeLabel("unavailable_wasm"),
          reason: `Backend '${descriptor.required_backend}' indisponível no ambiente WASM atual (ver Gate G-0B). Exporte o script CPython para execução local.`,
        };
      }
    }
  }

  // 2. Verifica mapa de maturidade por operação no CapabilityDescriptor
  const capMaturity: MaturityLevel | undefined = capabilities.maturity[descriptor.operation];
  if (capMaturity === "unavailable_wasm") {
    return {
      maturity: "unavailable_wasm",
      available: false,
      badgeLabel: getMaturityBadgeLabel("unavailable_wasm"),
      reason: `Operação '${descriptor.operation}' marcada como unavailable_wasm pelas capacidades do motor '${capabilities.engine_kind}'.`,
    };
  }

  const effectiveMaturity = capMaturity ?? descriptor.maturity;

  // 3. Verifica se o runtime conhece a operação quando capability explicitamente lista operações
  const isListed = capabilities.operations.includes(descriptor.operation);
  if (!isListed) {
    return {
      maturity: effectiveMaturity,
      available: false,
      badgeLabel: getMaturityBadgeLabel(effectiveMaturity),
      reason: `Operação '${descriptor.operation}' não suportada no runtime '${capabilities.runtime_id}'.`,
    };
  }

  return {
    maturity: effectiveMaturity,
    available: true,
    badgeLabel: getMaturityBadgeLabel(effectiveMaturity),
    reason: undefined,
  };
}

export type ToolRegistryListener = () => void;

/**
 * Registro dinâmico de ToolDescriptors.
 * Permite registrar novas ferramentas científicas sem alterar o roteamento global.
 */
export class ToolDescriptorRegistry {
  private readonly descriptors = new Map<string, ToolDescriptor>();
  private readonly listeners = new Set<ToolRegistryListener>();

  constructor(initialDescriptors?: readonly ToolDescriptor[]) {
    if (initialDescriptors) {
      for (const desc of initialDescriptors) {
        this.register(desc);
      }
    }
  }

  public register(descriptor: ToolDescriptor): void {
    const validated = validateToolDescriptor(descriptor);
    this.descriptors.set(validated.id, validated);
    this.notify();
  }

  public unregister(id: string): boolean {
    const removed = this.descriptors.delete(id);
    if (removed) {
      this.notify();
    }
    return removed;
  }

  public get(id: string): ToolDescriptor | null {
    return this.descriptors.get(id) ?? null;
  }

  public has(id: string): boolean {
    return this.descriptors.has(id);
  }

  public listAll(): ToolDescriptor[] {
    return Array.from(this.descriptors.values());
  }

  public listByTab(tab: ProjectTabId): ToolDescriptor[] {
    return this.listAll().filter((d) => d.tab === tab);
  }

  public listTabs(): ProjectTabId[] {
    return [...PROJECT_TAB_IDS];
  }

  public subscribe(listener: ToolRegistryListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const fn of this.listeners) {
      try {
        fn();
      } catch {
        // Isolar falhas de assinantes
      }
    }
  }
}

export interface LocalParameterValidationResult {
  valid: boolean;
  errors: Record<string, string>;
  sanitized: Record<string, unknown>;
}

function validateNumericMatrixOrVector(
  value: unknown,
  field: ParameterFieldSchema,
): { ok: true; value: unknown } | { ok: false; message: string } {
  if (isPlainObject(value) && Array.isArray(value.shape) && Array.isArray(value.data)) {
    for (let i = 0; i < value.data.length; i += 1) {
      const n = value.data[i];
      if (typeof n !== "number" || !Number.isFinite(n)) {
        return {
          ok: false,
          message: `Campo '${field.label}' contém valor não finito na posição ${i}.`,
        };
      }
    }
    return { ok: true, value: ensureFiniteJson(value, `$.params.${field.name}`) };
  }
  if (Array.isArray(value)) {
    try {
      return { ok: true, value: ensureFiniteJson(value, `$.params.${field.name}`) };
    } catch (err: unknown) {
      return {
        ok: false,
        message: err instanceof Error ? err.message : String(err),
      };
    }
  }
  return {
    ok: false,
    message: `Campo '${field.label}' exige array numérico ou descritor tensorial finito.`,
  };
}

export function validateLocalParameters(
  descriptor: ToolDescriptor,
  rawValues: Record<string, unknown>,
): LocalParameterValidationResult {
  const errors: Record<string, string> = {};
  const sanitized: Record<string, unknown> = {};

  for (const field of descriptor.parameter_schema) {
    const raw =
      field.name in rawValues ? rawValues[field.name] : field.default_value;

    if (raw === undefined || raw === null || raw === "") {
      if (field.required) {
        errors[field.name] = `Campo obrigatório '${field.label}' não informado.`;
      }
      continue;
    }

    switch (field.type) {
      case "number": {
        if (typeof raw !== "number" || !Number.isFinite(raw)) {
          errors[field.name] = `Campo '${field.label}' exige número real finito.`;
          continue;
        }
        if (field.min !== undefined && raw < field.min) {
          errors[field.name] = `Campo '${field.label}' deve ser >= ${field.min}.`;
          continue;
        }
        if (field.max !== undefined && raw > field.max) {
          errors[field.name] = `Campo '${field.label}' deve ser <= ${field.max}.`;
          continue;
        }
        sanitized[field.name] = raw;
        break;
      }
      case "integer": {
        if (typeof raw !== "number" || !Number.isInteger(raw) || !Number.isFinite(raw)) {
          errors[field.name] = `Campo '${field.label}' exige número inteiro finito.`;
          continue;
        }
        if (field.min !== undefined && raw < field.min) {
          errors[field.name] = `Campo '${field.label}' deve ser >= ${field.min}.`;
          continue;
        }
        if (field.max !== undefined && raw > field.max) {
          errors[field.name] = `Campo '${field.label}' deve ser <= ${field.max}.`;
          continue;
        }
        sanitized[field.name] = raw;
        break;
      }
      case "boolean": {
        if (typeof raw !== "boolean") {
          errors[field.name] = `Campo '${field.label}' exige booleano.`;
          continue;
        }
        sanitized[field.name] = raw;
        break;
      }
      case "string":
      case "select": {
        if (typeof raw !== "string") {
          errors[field.name] = `Campo '${field.label}' exige texto.`;
          continue;
        }
        if (
          field.type === "select" &&
          field.options &&
          !field.options.some((opt) => opt.value === raw)
        ) {
          errors[field.name] = `Valor '${raw}' não pertence às opções válidas de '${field.label}'.`;
          continue;
        }
        sanitized[field.name] = raw;
        break;
      }
      case "matrix":
      case "vector": {
        const res = validateNumericMatrixOrVector(raw, field);
        if (!res.ok) {
          errors[field.name] = res.message;
          continue;
        }
        sanitized[field.name] = res.value;
        break;
      }
      case "json": {
        try {
          sanitized[field.name] = ensureFiniteJson(raw, `$.params.${field.name}`);
        } catch (err: unknown) {
          errors[field.name] =
            err instanceof Error ? err.message : String(err);
        }
        break;
      }
    }
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
    sanitized,
  };
}

export interface RenderedParameterControl {
  name: string;
  label: string;
  type: ParameterFieldType;
  required: boolean;
  value: unknown;
  error: string | null;
  unit?: string;
  shape_hint?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: ReadonlyArray<{ value: string; label: string }>;
  touchTarget: TouchTargetMetadata;
  ariaAttributes: Record<string, string>;
}

export interface RenderedToolViewModel {
  toolId: string;
  title: string;
  description: string;
  tab: ProjectTabId;
  operation: string;
  interaction_mode: InteractionMode;
  maturity: EffectiveMaturityStatus;
  indicator: ResultVerificationIndicator;
  indicatorLabel: string;
  canExecute: boolean;
  disabledReason: string | null;
  controls: RenderedParameterControl[];
  validation: LocalParameterValidationResult;
  requirements: readonly string[];
  visualizations: readonly string[];
  limits: ToolLimits;
  examples: readonly ToolExample[];
  executeButtonTouchTarget: TouchTargetMetadata;
  toHtml(): string;
}

/**
 * Renderizador declarativo agnóstico a framework DOM que gera ViewModels acessíveis
 * e HTML higienizado a partir de qualquer `ToolDescriptor`.
 */
export class ToolDescriptorRenderer {
  public render(
    descriptor: ToolDescriptor,
    options?: {
      capabilities?: CapabilityDescriptor | null;
      parameterValues?: Record<string, unknown>;
      activeIndicator?: ResultVerificationIndicator;
    },
  ): RenderedToolViewModel {
    const capabilities = options?.capabilities ?? null;
    const rawValues = options?.parameterValues ?? {};
    const maturity = resolveEffectiveMaturity(descriptor, capabilities);
    const validation = validateLocalParameters(descriptor, rawValues);
    const indicator =
      options?.activeIndicator ??
      (maturity.maturity === "experimental"
        ? "experimental"
        : descriptor.default_indicator);

    const canExecute = maturity.available && validation.valid;
    const disabledReason = !maturity.available
      ? (maturity.reason ?? "Ferramenta indisponível no ambiente atual.")
      : !validation.valid
        ? "Existem erros de validação local nos parâmetros."
        : null;

    const controls: RenderedParameterControl[] = descriptor.parameter_schema.map(
      (field) => {
        const val =
          field.name in rawValues ? rawValues[field.name] : field.default_value;
        const err = validation.errors[field.name] ?? null;
        return {
          name: field.name,
          label: field.label,
          type: field.type,
          required: field.required === true,
          value: val,
          error: err,
          unit: field.unit,
          shape_hint: field.shape_hint,
          min: field.min,
          max: field.max,
          step: field.step,
          options: field.options ? field.options.map((opt) => ({ ...opt })) : undefined,
          touchTarget: createTouchTargetMetadata({
            ariaLabel: field.unit ? `${field.label} (${field.unit})` : field.label,
            role: field.type === "boolean" ? "checkbox" : "textbox",
          }),
          ariaAttributes: {
            "aria-label": field.label,
            "aria-invalid": err ? "true" : "false",
            ...(field.required ? { "aria-required": "true" } : {}),
          },
        };
      },
    );

    const executeButtonTouchTarget = createTouchTargetMetadata({
      ariaLabel: `Executar ${descriptor.title}`,
      role: "button",
      widthPx: 140,
      heightPx: 44,
    });

    return {
      toolId: descriptor.id,
      title: descriptor.title,
      description: descriptor.description,
      tab: descriptor.tab,
      operation: descriptor.operation,
      interaction_mode: descriptor.interaction_mode,
      maturity,
      indicator,
      indicatorLabel: getVerificationIndicatorLabel(indicator),
      canExecute,
      disabledReason,
      controls,
      validation,
      requirements: [...descriptor.requirements],
      visualizations: [...descriptor.visualizations],
      limits: { ...descriptor.limits },
      examples: descriptor.examples,
      executeButtonTouchTarget,
      toHtml: () =>
        renderToolViewModelToHtml({
          toolId: descriptor.id,
          title: descriptor.title,
          description: descriptor.description,
          tab: descriptor.tab,
          operation: descriptor.operation,
          interaction_mode: descriptor.interaction_mode,
          maturity,
          indicator,
          indicatorLabel: getVerificationIndicatorLabel(indicator),
          canExecute,
          disabledReason,
          controls,
          validation,
          requirements: descriptor.requirements,
          visualizations: descriptor.visualizations,
          limits: descriptor.limits,
          examples: descriptor.examples,
          executeButtonTouchTarget,
        }),
    };
  }
}

function renderToolViewModelToHtml(vm: Omit<RenderedToolViewModel, "toHtml">): string {
  const safeId = escapeHtml(vm.toolId);
  const safeTitle = escapeHtml(vm.title);
  const safeDesc = escapeHtml(vm.description);
  const safeOp = escapeHtml(vm.operation);
  const safeMaturity = escapeHtml(vm.maturity.maturity);
  const safeMaturityLabel = escapeHtml(vm.maturity.badgeLabel);
  const safeIndicator = escapeHtml(vm.indicator);
  const safeIndicatorLabel = escapeHtml(vm.indicatorLabel);

  const reqHtml = vm.requirements
    .map((r) => `<li>${escapeHtml(r)}</li>`)
    .join("");

  const controlsHtml = vm.controls
    .map((c) => {
      const safeParamName = escapeHtml(c.name);
      const cid = `tool-${safeId}-${safeParamName}`;
      const errHtml = c.error
        ? `<span class="field-error" role="alert">${escapeHtml(c.error)}</span>`
        : "";
      const valStr =
        typeof c.value === "string" || typeof c.value === "number" || typeof c.value === "boolean"
          ? String(c.value)
          : c.value !== undefined
            ? JSON.stringify(c.value)
            : "";

      let controlHtml: string;
      if (c.type === "select" && c.options && c.options.length > 0) {
        const optsHtml = c.options
          .map((opt) => {
            const selectedAttr = String(c.value) === opt.value ? " selected" : "";
            return `<option value="${escapeHtml(opt.value)}"${selectedAttr}>${escapeHtml(opt.label)}</option>`;
          })
          .join("");
        controlHtml = `<select id="${cid}" class="touch-control" style="min-height:${c.touchTarget.minTouchTargetPx}px" data-tool-id="${safeId}" data-param-name="${safeParamName}" data-param-type="${escapeHtml(c.type)}" aria-invalid="${c.error ? "true" : "false"}">${optsHtml}</select>`;
      } else if (c.type === "boolean") {
        const checkedAttr = c.value === true ? " checked" : "";
        controlHtml = `<input id="${cid}" type="checkbox" class="touch-control" style="min-width:${c.touchTarget.minTouchTargetPx}px;min-height:${c.touchTarget.minTouchTargetPx}px" data-tool-id="${safeId}" data-param-name="${safeParamName}" data-param-type="boolean"${checkedAttr} aria-invalid="${c.error ? "true" : "false"}" />`;
      } else if (c.type === "number" || c.type === "integer") {
        const minAttr = c.min !== undefined ? ` min="${c.min}"` : "";
        const maxAttr = c.max !== undefined ? ` max="${c.max}"` : "";
        const stepAttr =
          c.step !== undefined
            ? ` step="${c.step}"`
            : c.type === "integer"
              ? ' step="1"'
              : ' step="any"';
        controlHtml = `<input id="${cid}" type="number" class="touch-control" style="min-height:${c.touchTarget.minTouchTargetPx}px" data-tool-id="${safeId}" data-param-name="${safeParamName}" data-param-type="${escapeHtml(c.type)}"${minAttr}${maxAttr}${stepAttr} value="${escapeHtml(valStr)}" aria-invalid="${c.error ? "true" : "false"}" />`;
      } else if (c.type === "matrix" || c.type === "vector" || c.type === "json") {
        const placeholderAttr = c.shape_hint
          ? ` placeholder="${escapeHtml(c.shape_hint)}"`
          : "";
        const shapeAttr = c.shape_hint
          ? ` data-shape-hint="${escapeHtml(c.shape_hint)}"`
          : "";
        controlHtml = `<textarea id="${cid}" class="touch-control" style="min-height:${c.touchTarget.minTouchTargetPx}px" data-tool-id="${safeId}" data-param-name="${safeParamName}" data-param-type="${escapeHtml(c.type)}"${placeholderAttr}${shapeAttr} aria-invalid="${c.error ? "true" : "false"}">${escapeHtml(valStr)}</textarea>`;
      } else {
        controlHtml = `<input id="${cid}" type="text" class="touch-control" style="min-height:${c.touchTarget.minTouchTargetPx}px" data-tool-id="${safeId}" data-param-name="${safeParamName}" data-param-type="${escapeHtml(c.type)}" value="${escapeHtml(valStr)}" aria-invalid="${c.error ? "true" : "false"}" />`;
      }

      const shapeHintHtml = c.shape_hint
        ? ` <small class="shape-hint">[${escapeHtml(c.shape_hint)}]</small>`
        : "";

      return [
        `<div class="tool-field" data-field="${safeParamName}">`,
        `<label for="${cid}">${escapeHtml(c.label)}${c.unit ? ` (${escapeHtml(c.unit)})` : ""}${shapeHintHtml}</label>`,
        controlHtml,
        errHtml,
        `</div>`,
      ].join("");
    })
    .join("");

  const unavailableBanner = !vm.maturity.available
    ? `<div class="maturity-banner unavailable" role="status">${escapeHtml(vm.maturity.reason ?? "Indisponível em WASM")}</div>`
    : "";

  return [
    `<article class="tool-card" data-tool-id="${safeId}" data-operation="${safeOp}" data-maturity="${safeMaturity}">`,
    `<header class="tool-card-header">`,
    `<h3>${safeTitle}</h3>`,
    `<div class="tool-badges">`,
    `<span class="badge badge-maturity badge-${safeMaturity}" data-maturity-badge="${safeMaturity}">${safeMaturityLabel}</span>`,
    `<span class="badge badge-indicator badge-${safeIndicator}" data-verification-indicator="${safeIndicator}">${safeIndicatorLabel}</span>`,
    `</div>`,
    `</header>`,
    `<p class="tool-description">${safeDesc}</p>`,
    unavailableBanner,
    `<div class="tool-controls">${controlsHtml}</div>`,
    `<section class="tool-requirements" aria-label="Requisitos e hipóteses"><ul>${reqHtml}</ul></section>`,
    `<footer class="tool-actions">`,
    `<button type="button" class="btn-primary touch-control" data-action="execute-tool" data-tool-id="${safeId}" style="min-width:${vm.executeButtonTouchTarget.minTouchTargetPx}px;min-height:${vm.executeButtonTouchTarget.minTouchTargetPx}px" ${vm.canExecute ? "" : 'disabled aria-disabled="true"'}>Executar (${safeOp})</button>`,
    ...(vm.operation === "optimization.solve" ? [
      `<button type="button" class="touch-control" data-action="export-sdp" data-format="cvxpy" data-tool-id="${safeId}">Exportar Python / CVXPY</button>`,
      `<button type="button" class="touch-control" data-action="export-sdp" data-format="yalmip" data-tool-id="${safeId}">Exportar MATLAB / YALMIP</button>`,
    ] : []),
    vm.disabledReason ? `<p class="disabled-reason">${escapeHtml(vm.disabledReason)}</p>` : "",
    `</footer>`,
    `</article>`,
  ].join("\n");
}
