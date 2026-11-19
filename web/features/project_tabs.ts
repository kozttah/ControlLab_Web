/**
 * Gerenciador declarativo das 6 abas do ControlLab Web via ToolDescriptorRegistry
 * e ToolDescriptorRenderer, consumindo exclusivamente ControlLabEngineClient (F7)
 * (CL-DIR-001 Seções 5.2–5.7, 7.1, 13.10).
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping e erasableSyntaxOnly.
 */

import type { ControlLabEngineClient } from "../bridge/client.ts";
import {
  ControlLabBridgeError,
  generateUuid,
  isPlainObject,
  RPC_API_VERSION,
  type CapabilityDescriptor,
  type RpcRequest,
  type RpcResponse,
} from "../bridge/protocol.ts";
import {
  PROJECT_TAB_IDS,
  PROJECT_TAB_METADATA,
  ToolDescriptorRegistry,
  ToolDescriptorRenderer,
  type ProjectTabId,
  type RenderedToolViewModel,
  type ResultVerificationIndicator,
  type ToolDescriptor,
} from "../app/tool_descriptor.ts";
import { createDefaultToolRegistry } from "./tool_catalog.ts";
import type { FeedbackSign } from "./lqr_workspace.ts";
import type { TypedObjectWorkspace } from "./typed_workspace.ts";

export interface TabToolExecutionRecord {
  toolId: string;
  operation: string;
  request_id: string;
  project_revision: number;
  response: RpcResponse;
  indicator: ResultVerificationIndicator;
  executed_at: string;
}

export interface ProjectTabViewModel {
  tabId: ProjectTabId;
  label: string;
  shortLabel: string;
  ownerFront: string;
  tools: RenderedToolViewModel[];
  lastExecutionByTool: Record<string, TabToolExecutionRecord>;
}

export class ProjectTabsController {
  private readonly client: ControlLabEngineClient;
  private readonly registry: ToolDescriptorRegistry;
  private readonly renderer: ToolDescriptorRenderer;
  private typedWorkspace?: TypedObjectWorkspace;
  private readonly parameterState = new Map<string, Record<string, unknown>>();
  private readonly lastExecutions = new Map<string, TabToolExecutionRecord>();
  private activeTab: ProjectTabId = "statespace";
  private readonly listeners = new Set<() => void>();

  constructor(options: {
    client: ControlLabEngineClient;
    registry?: ToolDescriptorRegistry;
    renderer?: ToolDescriptorRenderer;
    typedWorkspace?: TypedObjectWorkspace;
    initialTab?: ProjectTabId;
  }) {
    this.client = options.client;
    this.registry = options.registry ?? createDefaultToolRegistry();
    this.renderer = options.renderer ?? new ToolDescriptorRenderer();
    this.typedWorkspace = options.typedWorkspace;
    if (options.initialTab) {
      this.activeTab = options.initialTab;
    }
    this.registry.subscribe(() => {
      this.notify();
    });
  }

  public setTypedWorkspace(workspace: TypedObjectWorkspace): void {
    this.typedWorkspace = workspace;
  }

  public getTypedWorkspace(): TypedObjectWorkspace | undefined {
    return this.typedWorkspace;
  }

  public getRegistry(): ToolDescriptorRegistry {
    return this.registry;
  }

  public getActiveTab(): ProjectTabId {
    return this.activeTab;
  }

  public setActiveTab(tab: ProjectTabId): void {
    if (!PROJECT_TAB_IDS.includes(tab)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Aba de projeto desconhecida: '${String(tab)}'.`,
      );
    }
    this.activeTab = tab;
    this.notify();
  }

  public registerTool(descriptor: ToolDescriptor): void {
    this.registry.register(descriptor);
  }

  public setToolParameters(
    toolId: string,
    values: Record<string, unknown>,
  ): void {
    const prev = this.parameterState.get(toolId) ?? {};
    this.parameterState.set(toolId, { ...prev, ...values });
    this.notify();
  }

  public getToolParameters(toolId: string): Record<string, unknown> {
    return { ...(this.parameterState.get(toolId) ?? {}) };
  }

  public getCapabilities(): CapabilityDescriptor | null {
    try {
      return this.client.getCapabilities();
    } catch {
      return null;
    }
  }

  public getTabViewModel(tabId: ProjectTabId = this.activeTab): ProjectTabViewModel {
    const meta = PROJECT_TAB_METADATA[tabId];
    const caps = this.getCapabilities();
    const descriptors = this.registry.listByTab(tabId);
    const tools = descriptors.map((desc) => {
      const exec = this.lastExecutions.get(desc.id);
      const indicator: ResultVerificationIndicator =
        exec && exec.response.status !== "failure"
          ? desc.maturity === "experimental"
            ? "experimental"
            : desc.default_indicator
          : desc.default_indicator;
      return this.renderer.render(desc, {
        capabilities: caps,
        parameterValues: this.parameterState.get(desc.id),
        activeIndicator: indicator,
      });
    });

    const lastExecutionByTool: Record<string, TabToolExecutionRecord> = {};
    for (const desc of descriptors) {
      const rec = this.lastExecutions.get(desc.id);
      if (rec) {
        lastExecutionByTool[desc.id] = rec;
      }
    }

    return {
      tabId,
      label: meta.label,
      shortLabel: meta.shortLabel,
      ownerFront: meta.ownerFront,
      tools,
      lastExecutionByTool,
    };
  }

  public getAllTabsViewModels(): ProjectTabViewModel[] {
    return PROJECT_TAB_IDS.map((tab) => this.getTabViewModel(tab));
  }

  public async executeTool(
    toolId: string,
    context: {
      project_id: string;
      project_revision: number;
      extraPayload?: Record<string, unknown>;
      options?: Record<string, unknown>;
      commitOnSuccess?: boolean;
      feedbackSign?: FeedbackSign;
      /**
       * Quando `false`, a execução é transitória: não vira `lastExecutionByTool`
       * da aba (ex.: preview SISO). O registro só ocorre via `recordCommittedExecution`.
       */
      recordExecution?: boolean;
    },
  ): Promise<TabToolExecutionRecord> {
    const desc = this.registry.get(toolId);
    if (!desc) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `ToolDescriptor não registrado: '${toolId}'.`,
      );
    }

    const caps = this.getCapabilities();
    const vm = this.renderer.render(desc, {
      capabilities: caps,
      parameterValues: this.parameterState.get(toolId),
    });

    if (!vm.maturity.available) {
      throw new ControlLabBridgeError(
        "SOLVER_UNAVAILABLE",
        vm.maturity.reason ??
          `Ferramenta '${desc.title}' indisponível no ambiente WASM atual.`,
        {
          parameters: {
            tool_id: desc.id,
            operation: desc.operation,
            maturity: vm.maturity.maturity,
          },
          next_step:
            "Exporte o problema/script para CPython local ou utilize uma ferramenta estável.",
        },
      );
    }

    if (!vm.validation.valid) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Parâmetros inválidos para '${desc.title}': ${Object.values(vm.validation.errors).join("; ")}`,
        {
          parameters: vm.validation.errors,
        },
      );
    }

    let effectiveExtraPayload = context.extraPayload
      ? { ...context.extraPayload }
      : {};
    if (this.typedWorkspace) {
      const plan = await this.typedWorkspace.prepareToolExecution(
        desc.operation,
        vm.validation.sanitized,
        {
          extraPayload: context.extraPayload,
          feedbackSign: context.feedbackSign,
        },
      );
      effectiveExtraPayload = plan.extraPayload;
    }

    const req: RpcRequest = {
      api_version: RPC_API_VERSION,
      request_id: `tool-${desc.id}-${generateUuid()}`,
      project_id: context.project_id,
      project_revision: context.project_revision,
      operation: desc.operation,
      payload: {
        ...vm.validation.sanitized,
        ...effectiveExtraPayload,
      },
      options: { ...(context.options ?? {}) },
      timeout_policy: {
        hard_timeout_ms: desc.limits.hard_timeout_ms,
        cancel_on_supersede: true,
      },
    };

    const response = await this.client.execute(req, {
      commitOnSuccess: context.commitOnSuccess ?? true,
    });
    if (
      this.typedWorkspace &&
      (response.status === "success" || response.status === "warning") &&
      response.result
    ) {
      if (
        desc.operation.startsWith("identification.fit_") &&
        isPlainObject(response.result.identified_model)
      ) {
        this.typedWorkspace.recordIdentifiedModelResult(
          response.result.identified_model,
          response,
        );
      } else if (
        desc.operation === "core.reuse_model" &&
        isPlainObject(response.result.model)
      ) {
        this.typedWorkspace.recordReuseResult(response);
      }
    }
    const record: TabToolExecutionRecord = {
      toolId: desc.id,
      operation: desc.operation,
      request_id: req.request_id,
      project_revision: req.project_revision,
      response,
      indicator:
        vm.maturity.maturity === "experimental"
          ? "experimental"
          : desc.default_indicator,
      executed_at: new Date().toISOString(),
    };
    if (context.recordExecution !== false) {
      this.lastExecutions.set(desc.id, record);
    }
    this.notify();
    return record;
  }

  /**
   * Registra explicitamente uma execução já comitada de forma autoritativa
   * (após `client.commitProject`), tornando-a visível em `lastExecutionByTool`.
   */
  public recordCommittedExecution(record: TabToolExecutionRecord): void {
    if (!this.registry.get(record.toolId)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `ToolDescriptor não registrado: '${record.toolId}'.`,
      );
    }
    this.lastExecutions.set(record.toolId, record);
    this.notify();
  }

  public getLastExecution(toolId: string): TabToolExecutionRecord | undefined {
    return this.lastExecutions.get(toolId);
  }

  public subscribe(listener: () => void): () => void {
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
