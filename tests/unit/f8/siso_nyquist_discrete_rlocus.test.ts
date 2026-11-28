import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  createSecondOrderRegionOverlay,
  evaluatePolesAgainstOverlay,
  generateOverlaySvgPath,
  type ChartViewport,
} from "../../../web/charts/overlays.ts";
import {
  buildNyquistChartModel,
  buildPoleZeroChartModel,
  buildRootLocusChartModel,
  inspectNyquistAtSvgPoint,
  renderNyquistSvg,
  renderPoleZeroSvg,
  renderRootLocusSvg,
} from "../../../web/charts/scientific_chart.ts";
import { renderSisoViewHtml } from "../../../web/features/views/siso_view.ts";

test("WP-UX11-03: Nyquist SVG renderiza círculo unitário, MG, MF e vetor de distância até (-1,0) com d e |S(jω)| exatos", () => {
  const model = buildNyquistChartModel({
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    dt: null,
    omega: [0.1, 1.0, 2.5, 10.0],
    re: [0.8, -0.5, -0.4, -0.05],
    im: [-0.2, -0.8660254, -0.3, -0.02],
    margins: {
      gain_margin: 2.5,
      gain_margin_db: 7.9588,
      phase_margin_deg: 60,
      w_gc: 1.0,
      w_pc: 2.5,
    },
  });

  // 1. Sem ponto selecionado: contém círculo unitário, MF e MG, sem distance-vector
  const baseSvg = renderNyquistSvg(model, { decimals: 3 });
  assert.ok(baseSvg.includes('data-nyquist-annotation="unit-circle"'), "Deve desenhar círculo unitário |L(jω)|=1");
  assert.ok(baseSvg.includes('data-nyquist-annotation="phase-margin"'), "Deve desenhar arco de Margem de Fase");
  assert.ok(baseSvg.includes('data-nyquist-annotation="gain-margin"'), "Deve desenhar segmento de Margem de Ganho");
  assert.ok(baseSvg.includes("MF = "), "Deve rotular Margem de Fase");
  assert.ok(baseSvg.includes("MG = "), "Deve rotular Margem de Ganho");
  assert.equal(baseSvg.includes('data-nyquist-annotation="distance-vector"'), false);

  // 2. Inspeção de ponto clicado: calcula d = hypot(re + 1, im) e |S(jω)| = 1 / d
  const tipProbe = inspectNyquistAtSvgPoint(model, 250, 250);
  assert.ok(tipProbe !== null);
  const expectedD = Math.hypot(tipProbe.re + 1, tipProbe.im);
  const expectedS = 1 / expectedD;
  assert.ok(Math.abs(tipProbe.distance_to_minus_one - expectedD) < 1e-12);
  assert.ok(Math.abs(tipProbe.sensitivity_mag - expectedS) < 1e-12);

  // 3. Renderização com ponto selecionado inclui vetor de distância até (-1, 0)
  const selectedSvg = renderNyquistSvg(model, {
    decimals: 3,
    selectedSampleIndex: tipProbe.sampleIndex,
  });
  assert.ok(selectedSvg.includes('data-layer="datatip"'));
  assert.ok(selectedSvg.includes('data-nyquist-annotation="distance-vector"'));
  assert.ok(selectedSvg.includes(`data-distance="${expectedD.toFixed(6)}"`));
  assert.ok(selectedSvg.includes("d = "), "Deve rotular distância d próximo ao ponto médio do vetor");
});

test("WP-UX11-03: Root Locus e Mapa Polo-Zero discretos (dt = 0.1) centralizam círculo unitário |z|=1 com aspecto 1:1 (rx === ry)", () => {
  const discreteRl = buildRootLocusChartModel({
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    dt: 0.1,
    gains: [0, 0.5, 1.0, 2.0],
    branches: [
      { real: [0.8, 0.6, 0.4, 0.2], imag: [0.0, 0.2, 0.35, 0.5] },
      { real: [0.8, 0.6, 0.4, 0.2], imag: [0.0, -0.2, -0.35, -0.5] },
    ],
    open_loop_poles: { real: [0.8, 0.8], imag: [0, 0] },
    open_loop_zeros: null,
    overlays: [
      createSecondOrderRegionOverlay({ zetaMin: 0.5, dt: 0.1, classification: "heuristic" }),
    ],
  });

  const rlSvg = renderRootLocusSvg(discreteRl, { widthPx: 640, heightPx: 420 });
  assert.ok(rlSvg.includes('data-unit-circle="true"'), "Root Locus discreto deve desenhar círculo unitário");
  assert.ok(rlSvg.includes("Re(z)") && rlSvg.includes("Im(z)"), "Eixos devem ser rotulados no plano z");

  const ellipseMatch = rlSvg.match(
    /<ellipse cx="([^"]+)" cy="([^"]+)" rx="([^"]+)" ry="([^"]+)"[^>]*data-unit-circle="true"/,
  );
  assert.ok(ellipseMatch !== null, "Elemento ellipse do círculo unitário deve existir");
  const cx = Number(ellipseMatch[1]);
  const cy = Number(ellipseMatch[2]);
  const rx = Number(ellipseMatch[3]);
  const ry = Number(ellipseMatch[4]);

  // Plot box: padLeft=64, padRight=24 -> plotW=552, centerX = 64 + 276 = 340
  // padTop=36, padBottom=48 -> plotH=336, centerY = 36 + 168 = 204
  assert.ok(Math.abs(cx - 340) < 1e-3, `Centro X esperado 340, obtido ${cx}`);
  assert.ok(Math.abs(cy - 204) < 1e-3, `Centro Y esperado 204, obtido ${cy}`);
  assert.ok(Math.abs(rx - ry) < 1e-6, `Aspecto 1:1 violado: rx=${rx}, ry=${ry}`);
  assert.ok(rx > 100 && rx < 168, `Raio do círculo unitário deve caber confortavelmente no viewport: rx=${rx}`);

  // Comparação: Root Locus contínuo não desenha data-unit-circle
  const contRl = buildRootLocusChartModel({
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    dt: null,
    gains: [0, 1],
    branches: [{ real: [-2, -3], imag: [0, 0] }],
    open_loop_poles: { real: [-2], imag: [0] },
  });
  const contSvg = renderRootLocusSvg(contRl);
  assert.equal(contSvg.includes('data-unit-circle="true"'), false);
  assert.ok(contSvg.includes("Re(s)") && contSvg.includes("Im(s)"));

  // Mapa Polo-Zero discreto também centraliza com 1:1
  const discretePz = buildPoleZeroChartModel({
    dt: 0.1,
    model_revision: 1,
    project_revision: 1,
    provenance: null,
    series_semantics: "numeric_verified",
    open_loop_poles: { real: [0.9, 0.7], imag: [0, 0] },
    committed_closed_loop_poles: { real: [0.5, 0.5], imag: [0.3, -0.3] },
    overlays: [
      createSecondOrderRegionOverlay({ zetaMin: 0.5, maxSettlingTimeS: 2.0, dt: 0.1 }),
    ],
  });
  const pzSvg = renderPoleZeroSvg(discretePz, { widthPx: 640, heightPx: 400 });
  const pzMatch = pzSvg.match(
    /<ellipse cx="([^"]+)" cy="([^"]+)" rx="([^"]+)" ry="([^"]+)"[^>]*data-unit-circle="true"/,
  );
  assert.ok(pzMatch !== null, "PoleZero discreto deve desenhar círculo unitário");
  const pzRx = Number(pzMatch[3]);
  const pzRy = Number(pzMatch[4]);
  assert.ok(Math.abs(pzRx - pzRy) < 1e-6, `PoleZero discreto deve manter 1:1: rx=${pzRx}, ry=${pzRy}`);
});

test("WP-UX11-03: Overlays discretos de 2ª ordem (dt=0.1, ζ=0.5, ω_n=2.0, T_s=2.0) geram espiral/ω_n/raio espectral exatos e avaliam polos z", () => {
  const dt = 0.1;
  const overlay = createSecondOrderRegionOverlay({
    zetaMin: 0.5,
    wnMin: 2.0,
    maxSettlingTimeS: 2.0,
    dt,
    classification: "heuristic",
  });

  assert.equal(overlay.domain, "discrete");
  assert.equal(overlay.classification, "heuristic");
  assert.ok(overlay.label.includes("[Heurístico]"), "Overlay deve carregar rótulo [Heurístico]");
  assert.equal(overlay.parameters.dt, dt);

  const vp: ChartViewport = {
    widthPx: 640,
    heightPx: 420,
    padLeftPx: 64,
    padRightPx: 24,
    padTopPx: 36,
    padBottomPx: 48,
    xMin: -2.05357,
    xMax: 2.05357,
    yMin: -1.25,
    yMax: 1.25,
  };

  const graphic = generateOverlaySvgPath(overlay, vp);
  assert.ok(graphic.pathD.length > 200, "Path discreto deve conter amostragem densa da espiral logarítmica, ω_n e círculo T_s");
  assert.ok(graphic.pathD.includes(" A "), "Path deve incluir arco circular para o raio espectral de T_s");
  assert.equal(graphic.classification, "heuristic");
  assert.ok(graphic.ariaDescription.includes("[Heurístico]"));

  // Polo dentro da região: s = -3 + j*2 => ω_n = 3.606 >= 2.0, ζ = 0.832 >= 0.5, |z| = exp(-0.3) = 0.7408 <= exp(-0.2) = 0.8187
  const zInsideRe = Math.exp(-3 * dt) * Math.cos(2 * dt);
  const zInsideIm = Math.exp(-3 * dt) * Math.sin(2 * dt);
  const evalInside = evaluatePolesAgainstOverlay(
    { real: [zInsideRe, zInsideRe], imag: [zInsideIm, -zInsideIm] },
    overlay,
  );
  assert.equal(evalInside.satisfied, true, "Polos dentro da região z-plane devem satisfazer o overlay");
  assert.equal(evalInside.violatingIndices.length, 0);

  // Polo fora da região (baixo amortecimento ζ = 0.124 < 0.5 e |z| = 0.951 > 0.8187)
  const zLowDampRe = Math.exp(-0.5 * dt) * Math.cos(4 * dt);
  const zLowDampIm = Math.exp(-0.5 * dt) * Math.sin(4 * dt);
  const evalOutside = evaluatePolesAgainstOverlay(
    { real: [zInsideRe, zLowDampRe], imag: [zInsideIm, zLowDampIm] },
    overlay,
  );
  assert.equal(evalOutside.satisfied, false);
  assert.deepEqual(evalOutside.violatingIndices, [1]);

  // Polo instável |z| > 1
  const evalUnstable = evaluatePolesAgainstOverlay(
    { real: [1.1], imag: [0.1] },
    overlay,
  );
  assert.equal(evalUnstable.satisfied, false);
  assert.deepEqual(evalUnstable.violatingIndices, [0]);
});

test("WP-UX11-03: Tab 2 (siso_view.ts) renderiza layout full-width empilhado (.siso-workbench-stack), preserva todos os IDs e R-23", () => {
  const html = renderSisoViewHtml();
  assert.ok(html.includes('class="siso-workbench-stack"'), "Deve usar .siso-workbench-stack");
  assert.ok(html.includes('class="siso-controls-bar"'), "Deve ter barra horizontal de controles .siso-controls-bar");
  assert.ok(html.includes('class="siso-results-stage"'), "Deve ter palco full-width .siso-results-stage");
  assert.ok(html.includes('class="siso-charts-grid"'), "Deve preservar .siso-charts-grid");
  assert.equal(html.includes('class="workspace-two-col"'), false, "Não deve comprimir Tab 2 em .workspace-two-col");

  const requiredIds = [
    "siso-workspace-panel",
    "siso-loop-diagram-bar",
    "siso-gain-slider",
    "btn-siso-eval-all",
    "btn-siso-eval-bode",
    "btn-siso-eval-rl",
    "btn-siso-eval-step",
    "siso-advanced-params-details",
    "siso-bode-chart-slot",
    "siso-nyquist-chart-slot",
    "siso-rl-chart-slot",
    "siso-time-chart-slot",
  ];
  for (const id of requiredIds) {
    assert.ok(html.includes(`id="${id}"`), `Elemento obrigatório #${id} ausente no HTML da Aba 2`);
  }

  // Export bars dos 4 gráficos SISO devem iniciar bloqueadas (R-23)
  const svgExportMatches = html.match(/data-action="export-chart-svg"[^>]*disabled aria-disabled="true"/g) ?? [];
  assert.equal(svgExportMatches.length, 4, "Devem existir 4 botões de exportação SVG bloqueados inicialmente (R-23)");
  const pngExportMatches = html.match(/data-action="export-chart-png"[^>]*disabled aria-disabled="true"/g) ?? [];
  assert.equal(pngExportMatches.length, 4, "Devem existir 4 botões de exportação PNG bloqueados inicialmente (R-23)");

  const css = readFileSync("web/app/styles.css", "utf-8");
  assert.ok(css.includes(".siso-workbench-stack"), "styles.css deve estilizar .siso-workbench-stack");
  assert.ok(css.includes("@media (min-width: 900px)"), "styles.css deve definir breakpoint 2x2 em 900px");
});
