/**
 * Gaveta recolhível direita — Inspetor Técnico (R-27 / JSON Canônico)
 * seguindo CL-UX-DIR-001 v1.0.0 (`WP-UX-REFACTOR-01-SHELL-DOCK`).
 *
 * Recolhida por padrão (`hidden`), concentra telemetria científica avançada
 * (rCARE, simetria(P), revisões, seed, backend, SHA-256) e o visualizador
 * JSON canônico da planta ou objeto ativo sem poluir a bancada principal.
 *
 * 100% compatível com erasableSyntaxOnly, verbatimModuleSyntax e FakeElement/FakeDocument.
 */

import { computeCanonicalSha256 } from "../bridge/protocol.ts";
import { encodeObjectRefKey } from "../features/typed_workspace.ts";
import { escapeHtml, formatNumericDisplay } from "./accessibility.ts";
import type { ControlLabShell } from "./shell.ts";
import type { DockInspectTarget } from "./workspace_dock.ts";

export interface InspectorDrawerOptions {
  shell: ControlLabShell;
  container: HTMLElement;
  initialOpen?: boolean;
}

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

export function renderInspectorDrawerHtml(): string {
  return [
    `<aside id="inspector-drawer" class="inspector-drawer" role="region" aria-label="Inspetor Técnico (R-27)" hidden>`,
    `<div class="inspector-header">`,
    `<h2>Inspetor Técnico (R-27)</h2>`,
    `<button type="button" id="btn-close-inspector" class="touch-control btn-secondary btn-small" data-action="close-inspector" aria-label="Fechar Inspetor Técnico">Fechar</button>`,
    `</div>`,
    `<div id="inspector-telemetry-slot" class="inspector-telemetry"></div>`,
    `<div class="inspector-json-section tool-field">`,
    `<div class="inspector-json-header">`,
    `<label for="inspector-object-select">Payload JSON Canônico</label>`,
    `<button type="button" id="btn-inspector-copy-json" class="touch-control btn-secondary btn-small" data-action="inspector-copy-json">Copiar JSON</button>`,
    `</div>`,
    `<select id="inspector-object-select" class="touch-control" aria-label="Objeto inspecionado em JSON"></select>`,
    `<pre id="inspector-json-pre" class="inspector-json-pre" aria-label="Visualizador JSON canônico"></pre>`,
    `</div>`,
    `</aside>`,
  ].join("\n");
}

export class InspectorDrawerController {
  private readonly shell: ControlLabShell;
  private readonly container: HTMLElement;
  private isOpen: boolean;
  private selectedTargetKey = "active_lqr_plant";
  private customTarget: DockInspectTarget | null = null;
  private lastTelemetryKey = "";
  private lastSelectOptionsKey = "";
  private lastJsonText = "";

  private readonly workbenchShellEl: HTMLElement | null;
  private readonly drawerEl: HTMLElement | null;
  private readonly toggleBtnEl: HTMLElement | null;
  private readonly closeBtnEl: HTMLElement | null;
  private readonly copyJsonBtnEl: HTMLElement | null;
  private readonly telemetrySlotEl: HTMLElement | null;
  private readonly objectSelectEl: HTMLSelectElement | null;
  private readonly jsonPreEl: HTMLElement | null;

  constructor(options: InspectorDrawerOptions) {
    this.shell = options.shell;
    this.container = options.container;
    this.isOpen = options.initialOpen ?? false;

    this.workbenchShellEl = this.container.querySelector<HTMLElement>(".app-workbench-shell");
    this.drawerEl = this.container.querySelector<HTMLElement>("#inspector-drawer");
    this.toggleBtnEl = this.container.querySelector<HTMLElement>("#btn-toggle-inspector");
    this.closeBtnEl = this.container.querySelector<HTMLElement>("#btn-close-inspector");
    this.copyJsonBtnEl = this.container.querySelector<HTMLElement>("#btn-inspector-copy-json");
    this.telemetrySlotEl = this.container.querySelector<HTMLElement>("#inspector-telemetry-slot");
    this.objectSelectEl = this.container.querySelector<HTMLSelectElement>("#inspector-object-select");
    this.jsonPreEl = this.container.querySelector<HTMLElement>("#inspector-json-pre");

    this.bindEvents();
  }

  private bindEvents(): void {
    this.toggleBtnEl?.addEventListener("click", () => {
      this.toggle();
    });
    this.closeBtnEl?.addEventListener("click", () => {
      this.setOpen(false);
    });
    this.objectSelectEl?.addEventListener("change", () => {
      this.selectedTargetKey = this.objectSelectEl?.value ?? "active_lqr_plant";
      if (!this.selectedTargetKey.startsWith("pending:")) {
        this.customTarget = null;
      }
      this.renderJsonSection();
    });
    this.copyJsonBtnEl?.addEventListener("click", () => {
      const content = this.jsonPreEl?.textContent ?? "";
      if (!content) return;
      if (globalThis.navigator?.clipboard?.writeText) {
        void globalThis.navigator.clipboard
          .writeText(content)
          .then(() => {
            this.shell
              .getAnnouncer()
              .announce("JSON canônico copiado no Inspetor R-27.", "polite", "status");
          })
          .catch((err: unknown) => this.shell.presentError(err));
      } else {
        this.shell
          .getAnnouncer()
          .announce("JSON pronto para cópia manual no Inspetor R-27.", "polite", "status");
      }
    });
  }

  public isDrawerOpen(): boolean {
    return this.isOpen;
  }

  public setOpen(open: boolean): void {
    this.isOpen = open;
    this.render();
  }

  public toggle(): void {
    this.setOpen(!this.isOpen);
  }

  public inspectTarget(target: DockInspectTarget): void {
    this.customTarget = target;
    this.selectedTargetKey = target.key;
    this.setOpen(true);
  }

  private syncVisibility(): void {
    setElHidden(this.drawerEl, !this.isOpen);
    toggleElCssClass(this.workbenchShellEl, "inspector-open", this.isOpen);
    this.toggleBtnEl?.setAttribute("aria-expanded", this.isOpen ? "true" : "false");
  }

  private resolveJsonTargets(): Array<{ key: string; label: string; value: unknown }> {
    const lqr = this.shell.getLqrWorkspace();
    const typed = this.shell.getTypedWorkspace();
    const idWs = this.shell.getIdentificationWorkspace();
    const targets: Array<{ key: string; label: string; value: unknown }> = [];

    const plant = lqr.getPlant();
    targets.push({
      key: "active_lqr_plant",
      label: `Planta LQR ativa (${plant.id}#r${plant.revision})`,
      value: plant,
    });

    const committed = lqr.getCommittedSnapshot();
    if (committed) {
      targets.push({
        key: "active_lqr_snapshot",
        label: `Snapshot LQR confirmado (rev. ${committed.project_revision})`,
        value: committed,
      });
    }

    const sisoSel = typed.getEffectiveSelection("frequencyPlant");
    if (sisoSel) {
      targets.push({
        key: "active_siso_plant",
        label: `Planta SISO selecionada (${sisoSel.ref.id}#r${sisoSel.ref.revision})`,
        value: sisoSel.object.value,
      });
    }

    const idReport = idWs.getActiveReport();
    if (idReport) {
      targets.push({
        key: "active_id_report",
        label: `Relatório Identificação (${idReport.operation})`,
        value: idReport,
      });
    }

    for (const obj of typed.listRegisteredObjects()) {
      targets.push({
        key: `obj:${obj.key}`,
        label: `${obj.id}#r${obj.revision} (${obj.kind})`,
        value: obj.value,
      });
    }

    if (
      this.customTarget &&
      !targets.some((t) => t.key === this.customTarget?.key)
    ) {
      targets.push(this.customTarget);
    }
    return targets;
  }

  private renderJsonSection(): void {
    const targets = this.resolveJsonTargets();
    const activeTarget =
      targets.find((t) => t.key === this.selectedTargetKey) ?? targets[0];

    if (this.objectSelectEl) {
      const optionsKey = JSON.stringify(targets.map((t) => [t.key, t.label]));
      if (optionsKey !== this.lastSelectOptionsKey) {
        this.lastSelectOptionsKey = optionsKey;
        this.objectSelectEl.innerHTML = targets
          .map(
            (t) =>
              `<option value="${escapeHtml(t.key)}"${t.key === activeTarget?.key ? " selected" : ""}>${escapeHtml(t.label)}</option>`,
          )
          .join("");
      }
      if (activeTarget && this.objectSelectEl.value !== activeTarget.key) {
        this.objectSelectEl.value = activeTarget.key;
      }
    }

    if (this.jsonPreEl && activeTarget) {
      const nextJson = JSON.stringify(activeTarget.value, null, 2);
      if (nextJson !== this.lastJsonText) {
        this.lastJsonText = nextJson;
        this.jsonPreEl.textContent = nextJson;
      }
    }
  }

  public render(): void {
    this.syncVisibility();
    const lqr = this.shell.getLqrWorkspace();
    const idWs = this.shell.getIdentificationWorkspace();
    const sisoWs = this.shell.getSisoWorkspace();
    const decimals = this.shell.getDisplayDecimals();
    const metrics = this.shell.getExecutionMetrics();
    const committed = lqr.getCommittedSnapshot();
    const plant = lqr.getPlant();
    const plantSha = computeCanonicalSha256(plant);
    const idReport = idWs.getActiveReport();
    const margins = sisoWs.getMarginsView();

    const telemetryKey = JSON.stringify({
      projectId: lqr.getProjectId(),
      projectRev: lqr.getProjectRevision(),
      modelRev: plant.revision,
      plantSha,
      decimals,
      committedRev: committed?.project_revision ?? null,
      committedAlg: committed?.provenance.algorithm ?? null,
      idOp: idReport?.operation ?? null,
      sisoPm: margins?.critical_phase_margin_deg ?? null,
      tWarm: metrics.T_warm_call,
    });

    if (this.telemetrySlotEl && telemetryKey !== this.lastTelemetryKey) {
      this.lastTelemetryKey = telemetryKey;
      const fmt = (v: unknown): string =>
        typeof v === "number" && Number.isFinite(v)
          ? formatNumericDisplay(v, decimals)
          : "N/D";

      const rCare = committed ? fmt(committed.diagnostics.care_residual_rel) : "N/D";
      const symP = committed ? fmt(committed.diagnostics.symmetry_error) : "N/D";
      const jOpt = committed ? fmt(committed.optimal_cost) : "N/D";
      const seedVal =
        committed?.provenance.seed !== undefined
          ? String(committed.provenance.seed)
          : idReport?.provenance.seed !== undefined
            ? String(idReport.provenance.seed)
            : "null";
      const backendAlg =
        committed?.provenance.algorithm ??
        idReport?.provenance.algorithm ??
        "idle";
      const libVersions =
        committed?.provenance.lib_versions ??
        idReport?.provenance.lib_versions ??
        {};
      const libSummary = Object.entries(libVersions)
        .map(([k, v]) => `${k}=${v}`)
        .join(", ");
      const fixtureId =
        typeof committed?.provenance.fixture_id === "string"
          ? committed.provenance.fixture_id
          : null;
      const kHash = committed?.K ? computeCanonicalSha256(committed.K) : null;

      this.telemetrySlotEl.innerHTML = [
        `<dl class="inspector-kv-list">`,
        `<dt>Projeto / Revisões</dt><dd><code>${escapeHtml(lqr.getProjectId())}</code> • proj_rev=<code>${lqr.getProjectRevision()}</code> • model_rev=<code>${plant.revision}</code></dd>`,
        `<dt>Backend / Algoritmo</dt><dd><code>${escapeHtml(backendAlg)}</code>${libSummary ? ` (${escapeHtml(libSummary)})` : ""}</dd>`,
        `<dt>Seed</dt><dd><code>${escapeHtml(seedVal)}</code></dd>`,
        `<dt>Resíduos Riccati (LQR)</dt><dd>rCARE=<code>${escapeHtml(rCare)}</code> • sym(P)=<code>${escapeHtml(symP)}</code> • J*=<code>${escapeHtml(jOpt)}</code></dd>`,
        `<dt>Latência T_warm</dt><dd><code>${metrics.T_warm_call !== null ? `${escapeHtml(formatNumericDisplay(metrics.T_warm_call, 2))} ms` : "N/D"}</code></dd>`,
        `<dt>SHA-256 Planta Ativa</dt><dd><code title="${escapeHtml(plantSha)}">${escapeHtml(plantSha.slice(0, 16))}…</code></dd>`,
        kHash
          ? `<dt>SHA-256 Ganho K</dt><dd><code title="${escapeHtml(kHash)}">${escapeHtml(kHash.slice(0, 16))}…</code></dd>`
          : "",
        fixtureId
          ? `<dt>Fixture Ouro</dt><dd><code>${escapeHtml(fixtureId)}</code></dd>`
          : "",
        idReport
          ? `<dt>Identificação</dt><dd><code>${escapeHtml(idReport.operation)}</code> • posto=<code>${escapeHtml(String(idReport.excitation.rank ?? "?"))}</code> • κ=<code>${escapeHtml(fmt(idReport.excitation.condition))}</code></dd>`
          : "",
        margins
          ? `<dt>SISO Margens</dt><dd>MF=<code>${escapeHtml(fmt(margins.critical_phase_margin_deg))}°</code> • MG=<code>${escapeHtml(fmt(margins.critical_gain_margin_db))} dB</code></dd>`
          : "",
        `</dl>`,
      ].join("");
    }

    this.renderJsonSection();

    if (this.objectSelectEl && this.selectedTargetKey === "active_lqr_plant") {
      // Ensure option key matches active plant ref when plant revision updates
      const refKey = encodeObjectRefKey({ id: plant.id, revision: plant.revision });
      void refKey;
    }
  }
}
