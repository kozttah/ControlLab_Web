/**
 * Overlays semânticos de requisitos de projeto com classificação obrigatória
 * (`exact`, `sufficient`, `heuristic`, `estimated`) e validação estrita contra
 * falsas garantias em aproximações de 2ª ordem (CL-DIR-001 Seções 5.3, 6.4, 7.1, 7.3).
 *
 * 100% compatível com navegador, Node 24 TypeScript stripping e erasableSyntaxOnly.
 */

import { ControlLabBridgeError } from "../bridge/protocol.ts";

export const OVERLAY_CONFIDENCE_CLASSES = [
  "exact",
  "sufficient",
  "heuristic",
  "estimated",
] as const;

export type OverlayConfidenceClass =
  (typeof OVERLAY_CONFIDENCE_CLASSES)[number];

export const OVERLAY_KINDS = [
  "half_plane_decay",
  "discrete_spectral_radius",
  "second_order_damping",
  "second_order_natural_freq",
  "second_order_settling_time",
  "second_order_overshoot",
  "lmi_cross_region",
  "d_stability_disk",
  "sensitivity_bound",
] as const;

export type OverlayKind = (typeof OVERLAY_KINDS)[number];

const SECOND_ORDER_HEURISTIC_KINDS = new Set<OverlayKind>([
  "second_order_damping",
  "second_order_natural_freq",
  "second_order_settling_time",
  "second_order_overshoot",
]);

const CLASSIFICATION_LABELS: Record<OverlayConfidenceClass, string> = {
  exact: "Exato (espectral)",
  sufficient: "Condição Suficiente (LMI/conservadora)",
  heuristic: "Heurística de 2ª ordem (não exata em ordem superior)",
  estimated: "Estimado (aproximação dominante)",
};

const CLASSIFICATION_DASHARRAY: Record<OverlayConfidenceClass, string> = {
  exact: "",
  sufficient: "8 4",
  heuristic: "4 4",
  estimated: "2 3",
};

export interface OverlayGeometryHint {
  shape: "half_plane" | "disk" | "wedge" | "annulus" | "band";
  boundary_values: Record<string, number>;
}

export interface RequirementOverlay {
  id: string;
  label: string;
  kind: OverlayKind;
  classification: OverlayConfidenceClass;
  classification_label: string;
  domain: "continuous" | "discrete";
  parameters: Record<string, number>;
  mathematical_basis: string;
  caveats: readonly string[];
  stroke_dasharray: string;
  geometry_hint: OverlayGeometryHint;
}

export interface ChartViewport {
  widthPx: number;
  heightPx: number;
  padLeftPx: number;
  padRightPx: number;
  padTopPx: number;
  padBottomPx: number;
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

export function getOverlayClassificationLabel(
  classification: OverlayConfidenceClass,
): string {
  return CLASSIFICATION_LABELS[classification];
}

export function getOverlayDashArray(
  classification: OverlayConfidenceClass,
): string {
  return CLASSIFICATION_DASHARRAY[classification];
}

export function validateOverlayClassification(
  kind: OverlayKind,
  classification: OverlayConfidenceClass,
): void {
  if (!OVERLAY_CONFIDENCE_CLASSES.includes(classification)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Classificação de overlay inválida: '${String(classification)}'.`,
    );
  }
  if (SECOND_ORDER_HEURISTIC_KINDS.has(kind) && classification === "exact") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Overlay '${kind}' baseado em aproximação de 2ª ordem dominante NÃO pode ser classificado como 'exact'; use 'heuristic' ou 'estimated' (CL-DIR-001 Seção 5.3).`,
      {
        parameters: { kind, forbidden_classification: classification },
        next_step:
          "Use 'heuristic' ou 'estimated' para regiões ζ/ω_n/sobressinal/tempo de acomodação, e verifique critérios temporais na simulação efetiva.",
      },
    );
  }
  if (kind === "lmi_cross_region" && classification === "exact") {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "Overlay de condições LMI cruzadas (TS/PDC) é uma condição suficiente conservadora e não pode ser rotulado como 'exact'.",
      {
        parameters: { kind, forbidden_classification: classification },
        next_step: "Classifique o overlay como 'sufficient'.",
      },
    );
  }
}

export function createRequirementOverlay(input: {
  id: string;
  label: string;
  kind: OverlayKind;
  classification: OverlayConfidenceClass;
  domain: "continuous" | "discrete";
  parameters: Record<string, number>;
  mathematical_basis: string;
  caveats?: readonly string[];
  geometry_hint: OverlayGeometryHint;
}): RequirementOverlay {
  if (typeof input.id !== "string" || input.id.trim().length === 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      "RequirementOverlay.id deve ser string não vazia.",
    );
  }
  for (const [k, v] of Object.entries(input.parameters)) {
    if (typeof v !== "number" || !Number.isFinite(v)) {
      throw new ControlLabBridgeError(
        "VALIDATION_ERROR",
        `Parâmetro '${k}' do overlay '${input.id}' deve ser finito.`,
      );
    }
  }
  validateOverlayClassification(input.kind, input.classification);

  return {
    id: input.id,
    label: input.label,
    kind: input.kind,
    classification: input.classification,
    classification_label: getOverlayClassificationLabel(input.classification),
    domain: input.domain,
    parameters: { ...input.parameters },
    mathematical_basis: input.mathematical_basis,
    caveats: input.caveats ? [...input.caveats] : [],
    stroke_dasharray: getOverlayDashArray(input.classification),
    geometry_hint: {
      shape: input.geometry_hint.shape,
      boundary_values: { ...input.geometry_hint.boundary_values },
    },
  };
}

/**
 * Região espectral exata de taxa de decaimento contínua Re(λ) < -α
 * ou discreta |λ| < r.
 */
export function createHalfPlaneDecayOverlay(
  alpha: number,
  options?: { id?: string; label?: string },
): RequirementOverlay {
  if (typeof alpha !== "number" || !Number.isFinite(alpha)) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `alpha deve ser número finito em createHalfPlaneDecayOverlay, recebido ${String(alpha)}.`,
    );
  }
  return createRequirementOverlay({
    id: options?.id ?? `overlay-decay-${alpha}`,
    label: options?.label ?? `Decaimento espectral Re(λ) < -${alpha}`,
    kind: "half_plane_decay",
    classification: "exact",
    domain: "continuous",
    parameters: { alpha },
    mathematical_basis: `Condição espectral exata para polos de malha fechada LTI: max Re(λ) < -${alpha}.`,
    caveats: [
      "Garante taxa de decaimento modal assintótica; não limita sozinho overshoot transitório em sistemas com zeros próximos ou acoplamento não normal.",
    ],
    geometry_hint: {
      shape: "half_plane",
      boundary_values: { max_real: -alpha },
    },
  });
}

export function createDiscreteSpectralRadiusOverlay(
  radius: number,
  options?: { id?: string; label?: string },
): RequirementOverlay {
  if (typeof radius !== "number" || !Number.isFinite(radius) || radius <= 0) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Raio espectral discreto deve ser finito > 0, recebido ${String(radius)}.`,
    );
  }
  return createRequirementOverlay({
    id: options?.id ?? `overlay-discrete-radius-${radius}`,
    label: options?.label ?? `Estabilidade discreta |z| < ${radius}`,
    kind: "discrete_spectral_radius",
    classification: "exact",
    domain: "discrete",
    parameters: { radius },
    mathematical_basis: `Condição espectral exata no plano z: ρ(A_cl) < ${radius}.`,
    caveats: ["Válido para sistemas LTI discretos no tempo de amostragem declarado."],
    geometry_hint: {
      shape: "disk",
      boundary_values: { center_real: 0, center_imag: 0, radius },
    },
  });
}

/**
 * Região de 2ª ordem dominante (ζ, ω_n, sobressinal M_p ou T_s).
 * Estritamente rotulada como `heuristic` ou `estimated` (nunca `exact`).
 */
export function createSecondOrderRegionOverlay(params: {
  id?: string;
  label?: string;
  zetaMin?: number;
  wnMin?: number;
  maxOvershootPct?: number;
  maxSettlingTimeS?: number;
  classification?: "heuristic" | "estimated";
}): RequirementOverlay {
  const classification = params.classification ?? "heuristic";
  let zeta = params.zetaMin;
  if (zeta === undefined && params.maxOvershootPct !== undefined) {
    const mp = params.maxOvershootPct / 100;
    if (mp > 0 && mp < 1) {
      const lnMp = Math.log(mp);
      zeta = Math.sqrt((lnMp * lnMp) / (Math.PI * Math.PI + lnMp * lnMp));
    }
  }
  const effectiveZeta = zeta ?? 0.5;
  if (!Number.isFinite(effectiveZeta) || effectiveZeta < 0 || effectiveZeta >= 1) {
    throw new ControlLabBridgeError(
      "VALIDATION_ERROR",
      `Amortecimento ζ inválido para overlay de 2ª ordem: ${effectiveZeta}.`,
    );
  }

  let wn = params.wnMin;
  if (wn === undefined && params.maxSettlingTimeS !== undefined && params.maxSettlingTimeS > 0) {
    wn = 4 / (Math.max(1e-6, effectiveZeta) * params.maxSettlingTimeS);
  }
  const effectiveWn = wn ?? 1.0;

  const kind: OverlayKind =
    params.maxOvershootPct !== undefined
      ? "second_order_overshoot"
      : params.maxSettlingTimeS !== undefined
        ? "second_order_settling_time"
        : params.wnMin !== undefined
          ? "second_order_natural_freq"
          : "second_order_damping";

  const labelParts: string[] = [];
  if (params.zetaMin !== undefined || params.maxOvershootPct !== undefined) {
    labelParts.push(`ζ >= ${effectiveZeta.toFixed(2)}`);
  }
  if (params.wnMin !== undefined || params.maxSettlingTimeS !== undefined) {
    labelParts.push(`ω_n >= ${effectiveWn.toFixed(2)} rad/s`);
  }

  return createRequirementOverlay({
    id: params.id ?? `overlay-2nd-order-${kind}`,
    label:
      params.label ??
      `Região 2ª ordem (${labelParts.join(", ") || `ζ >= ${effectiveZeta.toFixed(2)}`})`,
    kind,
    classification,
    domain: "continuous",
    parameters: {
      zeta_min: effectiveZeta,
      wn_min: effectiveWn,
      ...(params.maxOvershootPct !== undefined
        ? { max_overshoot_pct: params.maxOvershootPct }
        : {}),
      ...(params.maxSettlingTimeS !== undefined
        ? { max_settling_time_s: params.maxSettlingTimeS }
        : {}),
    },
    mathematical_basis:
      "Aproximação geométrica de polo dominante de 2ª ordem sem zeros finitos nem saturação.",
    caveats: [
      "Não constitui garantia exata em sistemas de ordem > 2, com zeros próximos ou saturação de atuador.",
      "Critérios temporais efetivos (overshoot, T_s) devem ser conferidos na simulação numérica.",
    ],
    geometry_hint: {
      shape: "wedge",
      boundary_values: {
        zeta_min: effectiveZeta,
        wn_min: effectiveWn,
        theta_rad: Math.acos(effectiveZeta),
      },
    },
  });
}

export function createLmiCrossRegionOverlay(params: {
  id?: string;
  label?: string;
  alpha?: number;
  diskRadius?: number;
}): RequirementOverlay {
  const alpha = params.alpha ?? 0.2;
  const diskRadius = params.diskRadius ?? 10.0;
  return createRequirementOverlay({
    id: params.id ?? `overlay-lmi-cross-${alpha}-${diskRadius}`,
    label:
      params.label ??
      `Região LMI Suficiente (Re(λ) < -${alpha}, |λ| < ${diskRadius})`,
    kind: "lmi_cross_region",
    classification: "sufficient",
    domain: "continuous",
    parameters: { alpha, disk_radius: diskRadius },
    mathematical_basis:
      "Condição suficiente de D-estabilidade / decaimento por Lyapunov quadrática ou LMIs cruzadas.",
    caveats: [
      "Condição suficiente (conservadora): violação geométrica não prova impossibilidade por outra função de Lyapunov.",
    ],
    geometry_hint: {
      shape: "disk",
      boundary_values: { max_real: -alpha, radius: diskRadius },
    },
  });
}

export interface OverlayEvaluationResult {
  overlayId: string;
  satisfied: boolean;
  margin: number;
  classification: OverlayConfidenceClass;
  caveat: string;
  violatingIndices: number[];
}

export function evaluatePolesAgainstOverlay(
  poles: { real: readonly number[]; imag: readonly number[] },
  overlay: RequirementOverlay,
): OverlayEvaluationResult {
  const count = Math.min(poles.real.length, poles.imag.length);
  const violatingIndices: number[] = [];
  let minMargin = Number.POSITIVE_INFINITY;

  for (let i = 0; i < count; i += 1) {
    const re = poles.real[i];
    const im = poles.imag[i];
    let margin = 0;

    if (overlay.kind === "half_plane_decay") {
      const maxReal = overlay.geometry_hint.boundary_values.max_real ?? 0;
      margin = maxReal - re; // positivo quando re < maxReal
    } else if (
      overlay.kind === "discrete_spectral_radius" ||
      overlay.kind === "d_stability_disk"
    ) {
      const radius = overlay.geometry_hint.boundary_values.radius ?? 1;
      const cx = overlay.geometry_hint.boundary_values.center_real ?? 0;
      const cy = overlay.geometry_hint.boundary_values.center_imag ?? 0;
      const dist = Math.hypot(re - cx, im - cy);
      margin = radius - dist;
    } else if (overlay.kind === "lmi_cross_region") {
      const maxReal = overlay.geometry_hint.boundary_values.max_real ?? 0;
      const radius = overlay.geometry_hint.boundary_values.radius ?? Number.POSITIVE_INFINITY;
      margin = Math.min(maxReal - re, radius - Math.hypot(re, im));
    } else if (SECOND_ORDER_HEURISTIC_KINDS.has(overlay.kind)) {
      const zetaMin = overlay.parameters.zeta_min ?? 0;
      const wnMin = overlay.parameters.wn_min ?? 0;
      const wn = Math.hypot(re, im);
      const actualZeta = wn > 0 ? -re / wn : re < 0 ? 1 : -1;
      const zetaMargin = actualZeta - zetaMin;
      const wnMargin = wnMin > 0 ? wn - wnMin : 0;
      margin = Math.min(zetaMargin, wnMargin);
    } else {
      margin = -re;
    }

    if (margin < minMargin) {
      minMargin = margin;
    }
    if (margin < 0) {
      violatingIndices.push(i);
    }
  }

  return {
    overlayId: overlay.id,
    satisfied: violatingIndices.length === 0 && count > 0,
    margin: count > 0 ? minMargin : 0,
    classification: overlay.classification,
    caveat: overlay.caveats[0] ?? overlay.mathematical_basis,
    violatingIndices,
  };
}

function mapXToPx(x: number, vp: ChartViewport): number {
  const plotW = Math.max(1, vp.widthPx - vp.padLeftPx - vp.padRightPx);
  const span = Math.max(1e-12, vp.xMax - vp.xMin);
  return vp.padLeftPx + ((x - vp.xMin) / span) * plotW;
}

function mapYToPx(y: number, vp: ChartViewport): number {
  const plotH = Math.max(1, vp.heightPx - vp.padTopPx - vp.padBottomPx);
  const span = Math.max(1e-12, vp.yMax - vp.yMin);
  return vp.padTopPx + (1 - (y - vp.yMin) / span) * plotH;
}

export interface OverlaySvgGraphic {
  id: string;
  pathD: string;
  label: string;
  classification: OverlayConfidenceClass;
  classificationLabel: string;
  strokeDasharray: string;
  ariaDescription: string;
}

export function generateOverlaySvgPath(
  overlay: RequirementOverlay,
  vp: ChartViewport,
): OverlaySvgGraphic {
  const xLeft = vp.padLeftPx;
  const xRight = vp.widthPx - vp.padRightPx;
  const yTop = vp.padTopPx;
  const yBottom = vp.heightPx - vp.padBottomPx;

  let pathD = "";
  if (overlay.geometry_hint.shape === "half_plane") {
    const maxReal = overlay.geometry_hint.boundary_values.max_real ?? 0;
    const xLine = Math.min(xRight, Math.max(xLeft, mapXToPx(maxReal, vp)));
    // Região proibida à direita da reta Re(λ) = maxReal
    pathD = `M ${xLine.toFixed(2)} ${yTop.toFixed(2)} L ${xLine.toFixed(2)} ${yBottom.toFixed(2)}`;
  } else if (overlay.geometry_hint.shape === "disk") {
    const radius = overlay.geometry_hint.boundary_values.radius ?? 1;
    const cx = mapXToPx(overlay.geometry_hint.boundary_values.center_real ?? 0, vp);
    const cy = mapYToPx(overlay.geometry_hint.boundary_values.center_imag ?? 0, vp);
    const rx = Math.abs(mapXToPx(radius, vp) - mapXToPx(0, vp));
    const ry = Math.abs(mapYToPx(radius, vp) - mapYToPx(0, vp));
    const parts = [
      `M ${(cx + rx).toFixed(2)} ${cy.toFixed(2)}`,
      `A ${rx.toFixed(2)} ${ry.toFixed(2)} 0 1 0 ${(cx - rx).toFixed(2)} ${cy.toFixed(2)}`,
      `A ${rx.toFixed(2)} ${ry.toFixed(2)} 0 1 0 ${(cx + rx).toFixed(2)} ${cy.toFixed(2)} Z`,
    ];
    if (overlay.geometry_hint.boundary_values.max_real !== undefined) {
      const xLine = Math.min(
        xRight,
        Math.max(xLeft, mapXToPx(overlay.geometry_hint.boundary_values.max_real, vp)),
      );
      parts.push(`M ${xLine.toFixed(2)} ${yTop.toFixed(2)} L ${xLine.toFixed(2)} ${yBottom.toFixed(2)}`);
    }
    pathD = parts.join(" ");
  } else {
    // Wedge de amortecimento ζ >= zeta_min (linhas saindo da origem no semiplano esquerdo)
    const theta = overlay.geometry_hint.boundary_values.theta_rad ?? Math.PI / 3;
    const tanTheta = Math.tan(Math.min(Math.PI / 2 - 1e-3, Math.max(1e-3, theta)));
    const ox = mapXToPx(0, vp);
    const oy = mapYToPx(0, vp);
    const xEnd = vp.xMin < 0 ? vp.xMin : -1;
    const yEndPos = Math.abs(xEnd) * tanTheta;
    const xEndPx = mapXToPx(xEnd, vp);
    const yPosPx = mapYToPx(yEndPos, vp);
    const yNegPx = mapYToPx(-yEndPos, vp);
    pathD = `M ${xEndPx.toFixed(2)} ${yPosPx.toFixed(2)} L ${ox.toFixed(2)} ${oy.toFixed(2)} L ${xEndPx.toFixed(2)} ${yNegPx.toFixed(2)}`;
  }

  return {
    id: overlay.id,
    pathD,
    label: overlay.label,
    classification: overlay.classification,
    classificationLabel: overlay.classification_label,
    strokeDasharray: overlay.stroke_dasharray,
    ariaDescription: `${overlay.label} [${overlay.classification_label}]: ${overlay.mathematical_basis}`,
  };
}
