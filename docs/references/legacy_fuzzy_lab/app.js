/*
 * Laboratório Virtual de Controle Fuzzy — implementação nativa.
 * Planta reconstruída de CarController.cs / RefController.cs.
 * Controlador Mamdani reconstruído de FuzzySets.cs.
 * Nenhuma dependência de Unity, Three.js, Pyodide ou Monaco.
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const TAU = 2 * Math.PI;
  const EPS = 1e-10;
  const META = {
    e1: { label: 'EA · Erro angular', symbol: 'EA', unit: 'rad' },
    e2: { label: 'EP · Erro de posição', symbol: 'EP', unit: 'm' },
    s1: { label: 'VA · Velocidade angular', symbol: 'VA', unit: 'rad/s' },
    s2: { label: 'VEL · Velocidade linear', symbol: 'VEL', unit: 'm/s' }
  };
  const VAR_KEYS = ['e1', 'e2', 's1', 's2'];
  const SPRITE_PATHS = {
    robot: 'desenhos/robo1.png',
    ref: 'desenhos/robo2.png',
    topTile: 'desenhos/cubo_cima.png',
    sideTile: 'desenhos/cubo_lado.png',
    tower: 'desenhos/torre.png'
  };

  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const finite = (x, fallback = 0) =>
    Number.isFinite(Number(x)) ? Number(x) : fallback;

  const wrapAngle = (a) => {
    let v = (a + Math.PI) % TAU;
    if (v < 0) v += TAU;
    return v - Math.PI;
  };

  const fmt = (x, n = 2) =>
    Number.isFinite(x) ? x.toFixed(n) : '—';


  const escapeHtml = (value) => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');

  function displaySetName(variable, index) {
    const raw = variable?.setNames?.[index];
    const name = typeof raw === 'string' ? raw.trim() : '';
    return name || `Conjunto ${index + 1}`;
  }

  function makeSets(shape, min, max, count) {
    const n = clamp(Math.round(count), 1, 12);
    const span = Math.max(1e-6, max - min);
    const step = n === 1 ? span : span / (n - 1);
    const sets = [];

    for (let i = 0; i < n; i++) {
      const c = n === 1 ? (min + max) / 2 : min + i * step;

      if (shape === 'gauss') {
        sets.push([c, Math.max(span / 20, step / 1.55)]);
      } else if (shape === 'trap') {
        if (n === 1) {
          sets.push([
            min,
            min + span * .25,
            min + span * .75,
            max
          ]);
        } else if (i === 0) {
          sets.push([min, min, min + step * .35, min + step]);
        } else if (i === n - 1) {
          sets.push([max - step, max - step * .35, max, max]);
        } else {
          sets.push([
            c - step * .55,
            c - step * .25,
            c + step * .25,
            c + step * .55
          ]);
        }
      } else {
        if (n === 1) {
          sets.push([min, c, max]);
        } else if (i === 0) {
          sets.push([min, min, min + step]);
        } else if (i === n - 1) {
          sets.push([max - step, max, max]);
        } else {
          sets.push([c - step, c, c + step]);
        }
      }
    }

    return sets;
  }

  function makeBaseConfig() {
    const cfg = {
      schemaVersion: 1,
      source: 'student-empty',
      gains: {
        e1: 1,
        e2: 1,
        omega: 1,
        velocity: 1
      },
      variables: {
        e1: {
          min: -Math.PI,
          max: Math.PI,
          shape: 'tri',
          sets: [],
          setNames: []
        },
        // Distância é não negativa; o intervalo [-5,5] do C#
        // foi preservado como opção, não como default semântico.
        e2: {
          min: 0,
          max: 5,
          shape: 'tri',
          sets: [],
          setNames: []
        },
        s1: {
          min: -5,
          max: 5,
          shape: 'tri',
          sets: [],
          setNames: []
        },
        s2: {
          min: -5,
          max: 5,
          shape: 'tri',
          sets: [],
          setNames: []
        }
      },
      sNorm: 'max',
      tNorm: 'min',
      implication: 'min',
      fuzzification: 'singleton',
      fuzzificationParams: {
        gaussSigma: 0.1,
        triHalfWidth: 0.1,
        samples: 11
      },
      defuzzification: 'cg',
      resolution: 51,
      rules: []
    };

    return cfg;
  }

  function makeEmptyConfig() {
    return makeBaseConfig();
  }

  function normalizeConfig(raw) {
    const demo = makeEmptyConfig();
    const cfg = raw && typeof raw === 'object' ? raw : demo;

    if (!cfg.variables) cfg.variables = demo.variables;

    if (!cfg.gains) {
      cfg.gains = {
        e1: 1,
        e2: 1,
        omega: 1,
        velocity: 1
      };
    }

    for (const key of ['e1', 'e2', 'omega', 'velocity']) {
      cfg.gains[key] = clamp(
        finite(cfg.gains[key], 1),
        0.01,
        100
      );
    }

    for (const key of VAR_KEYS) {
      const fallback = demo.variables[key];
      const v = cfg.variables[key] || fallback;

      v.min = finite(v.min, fallback.min);
      v.max = finite(v.max, fallback.max);

      if (v.max <= v.min) {
        v.min = fallback.min;
        v.max = fallback.max;
      }

      v.shape = ['tri', 'trap', 'gauss'].includes(v.shape)
        ? v.shape
        : 'tri';

      if (!Array.isArray(v.sets)) {
        v.sets = makeSets(v.shape, v.min, v.max, 5);
      }

      v.sets = v.sets.map((p) =>
        Array.isArray(p) ? p.map((z) => finite(z, 0)) : []
      );

      if (!Array.isArray(v.setNames)) v.setNames = [];
      v.setNames = v.sets.map((_, i) =>
        typeof v.setNames[i] === 'string' ? v.setNames[i] : ''
      );

      cfg.variables[key] = v;
    }

    cfg.sNorm = ['max', 'prob', 'eins'].includes(cfg.sNorm)
      ? cfg.sNorm : 'max';

    cfg.tNorm = ['min', 'prod', 'eins'].includes(cfg.tNorm)
      ? cfg.tNorm : 'min';

    cfg.implication = ['min', 'prod'].includes(cfg.implication)
      ? cfg.implication : 'min';

    cfg.fuzzification = ['singleton', 'gauss', 'tri'].includes(
      cfg.fuzzification
    ) ? cfg.fuzzification : 'singleton';

    if (!cfg.fuzzificationParams || typeof cfg.fuzzificationParams !== 'object') {
      cfg.fuzzificationParams = { ...demo.fuzzificationParams };
    }
    cfg.fuzzificationParams.gaussSigma = clamp(
      finite(cfg.fuzzificationParams.gaussSigma, 0.1),
      1e-4,
      10
    );
    cfg.fuzzificationParams.triHalfWidth = clamp(
      finite(cfg.fuzzificationParams.triHalfWidth, 0.1),
      1e-4,
      10
    );
    cfg.fuzzificationParams.samples = clamp(
      Math.round(finite(cfg.fuzzificationParams.samples, 11)),
      3,
      101
    );

    cfg.defuzzification = ['cg', 'mom', 'som', 'lom'].includes(
      cfg.defuzzification
    ) ? cfg.defuzzification : 'cg';

    cfg.resolution = [31, 51, 71].includes(Number(cfg.resolution))
      ? Number(cfg.resolution)
      : 51;

    if (!Array.isArray(cfg.rules)) cfg.rules = [];

    cfg.rules = cfg.rules
      .filter((r) =>
        Array.isArray(r) &&
        r.length === 4 &&
        r.every((n) => Number.isInteger(Number(n)))
      )
      .map((r) => r.map(Number))
      .filter((r) =>
        r[0] >= 0 && r[0] < cfg.variables.e1.sets.length &&
        r[1] >= 0 && r[1] < cfg.variables.e2.sets.length &&
        r[2] >= 0 && r[2] < cfg.variables.s1.sets.length &&
        r[3] >= 0 && r[3] < cfg.variables.s2.sets.length
      );

    return cfg;
  }

  function loadConfig() {
    // O laboratório sempre inicia sem solução pronta.
    // Continuidade entre sessões é feita explicitamente por FML/XML.
    return makeEmptyConfig();
  }

  const state = {
    config: loadConfig(),
    selectedVariable: 'e1',

    lastFires: [],
    lastFuzzy: {
      omega: 0,
      velocity: 0,
      mass: 0
    },

    currentZ: [0, 0, 0, 2.62, -0.02],
    currentTime: 0,
    currentU: [0, 0],

    batch: {
      records: [],
      playing: false,
      startedAt: 0,
      playhead: 0,
      index: 0,
      raf: 0
    },

    online: {
      running: false,
      raf: 0,
      lastFrame: null,
      accumulator: 0,
      dt: 1 / 60,

      z: [0, 0, 0, 2.62, -0.02],
      time: 0,
      history: [],
      dataRevision: 0,
      lastPlotAt: 0,

      lastControl: [0, 0],
      manualTarget: [0, 0],
      manualActual: [0, 0],
      refManualTarget: [0, 0],
      refManualActual: [0, 0],
      refTheta: 0,

      disturbance: null,
      refMode: 'manual',
      controlMode: 'fuzzy'
    },

    challenge: {
      selected: 'simple',
      geometry: null,
      running: false,
      paused: false,
      completed: false,
      raf: 0,
      lastFrame: null,
      accumulator: 0,
      dt: 1 / 60,
      time: 0,
      student: [0, 0, 0],
      reference: [0, 0, 0],
      controller: null,
      speed: 1.8,
      lookahead: 1.2,
      prevStudentS: 0,
      studentProgress: 0,
      validDistance: 0,
      forwardDistance: 0,
      offtrackDistance: 0,
      lastStudentInside: true,
      lastControl: [0, 0],
      lastRefControl: [0, 0],
      camera: { x: 0, y: 0, halfH: 5 },
      score: 0
    },

    draggingMembership: false,
    draggingReference: false,

    sprites: {},
    plotlyReady: false,
    plotlyPromise: null,
    mathjaxPromise: null
  };

  // Membership functions.
  // Degenerate end triangles/trapezoids are treated as shoulders.
  function trimf(a, b, c, x) {
    if (x < a || x > c) return 0;

    if (Math.abs(x - b) < EPS) return 1;

    if (x < b) {
      return Math.abs(b - a) < EPS
        ? 1
        : clamp((x - a) / (b - a), 0, 1);
    }

    return Math.abs(c - b) < EPS
      ? 1
      : clamp((c - x) / (c - b), 0, 1);
  }

  function trapmf(a, b, c, d, x) {
    if (x < a || x > d) return 0;

    if (x >= b && x <= c) return 1;

    if (x < b) {
      return Math.abs(b - a) < EPS
        ? 1
        : clamp((x - a) / (b - a), 0, 1);
    }

    return Math.abs(d - c) < EPS
      ? 1
      : clamp((d - x) / (d - c), 0, 1);
  }

  function gaussmf(c, sigma, x) {
    const s = Math.max(Math.abs(sigma), 1e-8);
    const q = (x - c) / s;

    return Math.exp(-0.5 * q * q);
    // Convenção IEEE 1855/JFML: param1 = centro, param2 = sigma.
  }

  function membership(set, shape, x) {
    if (shape === 'gauss') {
      return gaussmf(set[0], set[1], x);
    }

    if (shape === 'trap') {
      return trapmf(set[0], set[1], set[2], set[3], x);
    }

    return trimf(set[0], set[1], set[2], x);
  }

  function memberships(value, variable) {
    const x = clamp(value, variable.min, variable.max);

    return variable.sets.map((p) =>
      membership(p, variable.shape, x)
    );
  }

  function tNorm(a, b, kind = state.config.tNorm) {
    a = clamp(a, 0, 1);
    b = clamp(b, 0, 1);

    if (kind === 'prod') return a * b;

    if (kind === 'eins') {
      return (a * b) /
        Math.max(EPS, 2 - (a + b - a * b));
    }

    return Math.min(a, b);
  }

  function sNorm(a, b, kind = state.config.sNorm) {
    a = clamp(a, 0, 1);
    b = clamp(b, 0, 1);

    if (kind === 'prob') return a + b - a * b;

    if (kind === 'eins') {
      return (a + b) / Math.max(EPS, 1 + a * b);
    }

    return Math.max(a, b);
  }

  function implication(a, b, kind = state.config.implication) {
    return kind === 'prod' ? a * b : Math.min(a, b);
  }

  function computeFiring(e1, e2, cfg = state.config) {
    // Normalização explícita das entradas; K=1 reproduz
    // diretamente os universos do C#.
    e1 *= cfg.gains.e1;
    e2 *= cfg.gains.e2;

    const v1 = cfg.variables.e1;
    const v2 = cfg.variables.e2;

    if (
      !cfg.rules.length ||
      !v1.sets.length ||
      !v2.sets.length
    ) {
      return [];
    }

    if (cfg.fuzzification === 'singleton') {
      const m1 = memberships(e1, v1);
      const m2 = memberships(e2, v2);

      return cfg.rules.map((r) =>
        tNorm(
          m1[r[0]] || 0,
          m2[r[1]] || 0,
          cfg.tNorm
        )
      );
    }

    // Modus Ponens Generalizado: aproximação sup-star amostrada.
    // Os parâmetros do fuzzificador são configuráveis na interface.
    const fp = cfg.fuzzificationParams || {
      gaussSigma: 0.1,
      triHalfWidth: 0.1,
      samples: 11
    };
    const sigma = Math.max(Math.abs(fp.gaussSigma), 1e-4);
    const halfWidth = Math.max(Math.abs(fp.triHalfWidth), 1e-4);
    const sampleCount = clamp(Math.round(fp.samples || 11), 3, 101);
    const radius = cfg.fuzzification === 'gauss' ? 2 * sigma : halfWidth;

    const left1 = Math.max(v1.min, e1 - radius);
    const right1 = Math.min(v1.max, e1 + radius);
    const left2 = Math.max(v2.min, e2 - radius);
    const right2 = Math.min(v2.max, e2 + radius);

    const samples1 = [];
    const samples2 = [];

    for (let i = 0; i < sampleCount; i++) {
      const alpha = sampleCount > 1 ? i / (sampleCount - 1) : 0;
      const x1 = left1 + (right1 - left1) * alpha;
      const x2 = left2 + (right2 - left2) * alpha;

      const degree1 = cfg.fuzzification === 'gauss'
        ? gaussmf(e1, sigma, x1)
        : trimf(e1 - halfWidth, e1, e1 + halfWidth, x1);

      const degree2 = cfg.fuzzification === 'gauss'
        ? gaussmf(e2, sigma, x2)
        : trimf(e2 - halfWidth, e2, e2 + halfWidth, x2);

      samples1.push([x1, degree1, memberships(x1, v1)]);
      samples2.push([x2, degree2, memberships(x2, v2)]);
    }

    return cfg.rules.map((r) => {
      let sup = 0;

      for (const a of samples1) {
        for (const b of samples2) {
          const fuzzyInput = tNorm(
            a[1],
            b[1],
            cfg.tNorm
          );

          const antecedent = tNorm(
            a[2][r[0]] || 0,
            b[2][r[1]] || 0,
            cfg.tNorm
          );

          const value = tNorm(
            fuzzyInput,
            antecedent,
            cfg.tNorm
          );

          if (value > sup) sup = value;
        }
      }

      return sup;
    });
  }

    function evaluateFuzzy(e1, e2, cfg = state.config, gridOverride = null) {
    const fires = computeFiring(e1, e2, cfg);

    if (
      !cfg.rules.length ||
      !fires.length ||
      !cfg.variables.s1.sets.length ||
      !cfg.variables.s2.sets.length
    ) {
      return {
        omega: 0,
        velocity: 0,
        fires,
        mass: 0,
        max: 0,
        status: 'Base de regras ou conjuntos de saída vazios: saída neutra.'
      };
    }

    const outW = cfg.variables.s1;
    const outV = cfg.variables.s2;

    const n = clamp(
      Number(gridOverride || cfg.resolution),
      11,
      101
    );

    const gridW = Array.from(
      { length: n },
      (_, i) => outW.min + (outW.max - outW.min) * i / (n - 1)
    );

    const gridV = Array.from(
      { length: n },
      (_, i) => outV.min + (outV.max - outV.min) * i / (n - 1)
    );

    const memW = gridW.map((w) => memberships(w, outW));
    const memV = gridV.map((v) => memberships(v, outV));

    let mass = 0;
    let sumW = 0;
    let sumV = 0;
    let maxMu = 0;

    const maxima = [];

    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        let aggregate = 0;

        for (let k = 0; k < cfg.rules.length; k++) {
          const rule = cfg.rules[k];

          const consequent = tNorm(
            memW[i][rule[2]] || 0,
            memV[j][rule[3]] || 0,
            cfg.tNorm
          );

          const implied = implication(
            fires[k] || 0,
            consequent,
            cfg.implication
          );

          aggregate = k === 0
            ? implied
            : sNorm(aggregate, implied, cfg.sNorm);
        }

        if (aggregate > maxMu + 1e-12) {
          maxMu = aggregate;
          maxima.length = 0;
          maxima.push([i, j]);
        } else if (Math.abs(aggregate - maxMu) < 1e-12) {
          maxima.push([i, j]);
        }

        mass += aggregate;
        sumW += aggregate * gridW[i];
        sumV += aggregate * gridV[j];
      }
    }

    if (mass <= EPS || !Number.isFinite(mass)) {
      return {
        omega: 0,
        velocity: 0,
        fires,
        mass: 0,
        max: maxMu,
        status: 'Massa de pertinência nula: saída neutra aplicada.'
      };
    }

    let omega;
    let velocity;

    if (cfg.defuzzification === 'cg') {
      omega = sumW / mass;
      velocity = sumV / mass;
    } else {
      const selected = maxima.length
        ? maxima
        : [[Math.floor(n / 2), Math.floor(n / 2)]];

      if (cfg.defuzzification === 'som') {
        omega = gridW[
          Math.min(...selected.map((p) => p[0]))
        ];

        velocity = gridV[
          Math.min(...selected.map((p) => p[1]))
        ];
      } else if (cfg.defuzzification === 'lom') {
        omega = gridW[
          Math.max(...selected.map((p) => p[0]))
        ];

        velocity = gridV[
          Math.max(...selected.map((p) => p[1]))
        ];
      } else {
        omega = selected.reduce(
          (acc, p) => acc + gridW[p[0]],
          0
        ) / selected.length;

        velocity = selected.reduce(
          (acc, p) => acc + gridV[p[1]],
          0
        ) / selected.length;
      }
    }

    return {
      // Desnormalização independente das duas saídas
      // e saturação física do comando.
      omega: clamp(
        (Number.isFinite(omega) ? omega : 0) *
        cfg.gains.omega,
        -5,
        5
      ),

      velocity: clamp(
        (Number.isFinite(velocity) ? velocity : 0) *
        cfg.gains.velocity,
        -5,
        5
      ),

      fires,
      mass,
      max: maxMu,
      status: 'Inferência calculada.'
    };
  }

  function referenceTarget(t, mode) {
    if (mode === 'circular') {
      return [
        1.25 + 3.25 * Math.cos(t),
        0.25 + 3.25 * Math.sin(t)
      ];
    }

    if (mode === 'retangular') {
      const q = ((t % 8) + 8) % 8;

      if (q < 2) {
        return [-2 + 3.25 * q, -3];
      }

      if (q < 4) {
        return [4.5, -3 + 3.25 * (q - 2)];
      }

      if (q < 6) {
        return [4.5 - 3.25 * (q - 4), 3.5];
      }

      return [-2, 3.5 - 3.25 * (q - 6)];
    }

    return null;
  }

  function refDerivative(z, t, mode) {
    if (mode === 'circular') {
      const target = referenceTarget(t, mode);
      const kp = 2;

      return [
        kp * (target[0] - z[3]),
        kp * (target[1] - z[4])
      ];
    }

    if (mode === 'retangular') {
      const target = referenceTarget(t, mode);
      const kp = 6;

      return [
        kp * (target[0] - z[3]),
        kp * (target[1] - z[4])
      ];
    }

    return [0, 0];
  }

  function plantDerivative(z, t, u, refMode) {
    const rd = refDerivative(z, t, refMode);

    return [
      u[0] * Math.cos(z[2]),
      u[0] * Math.sin(z[2]),
      u[1],
      rd[0],
      rd[1]
    ];
  }

  function rk4(z, t, h, u, refMode) {
    const add = (a, b, scale) =>
      a.map((v, i) => v + scale * b[i]);

    const k1 = plantDerivative(z, t, u, refMode);

    const k2 = plantDerivative(
      add(z, k1, h / 2),
      t + h / 2,
      u,
      refMode
    );

    const k3 = plantDerivative(
      add(z, k2, h / 2),
      t + h / 2,
      u,
      refMode
    );

    const k4 = plantDerivative(
      add(z, k3, h),
      t + h,
      u,
      refMode
    );

    const out = z.map(
      (v, i) =>
        v + h * (
          k1[i] +
          2 * k2[i] +
          2 * k3[i] +
          k4[i]
        ) / 6
    );

    out[2] = wrapAngle(out[2]);

    return constrainStateToTrack(out);
  }

  function errorsOf(z) {
    const dx = z[3] - z[0];
    const dy = z[4] - z[1];

    return {
      e1: wrapAngle(Math.atan2(dy, dx) - z[2]),
      e2: Math.hypot(dx, dy)
    };
  }

  function controlOf(z, mode, cfg = state.config) {
    if (mode === 'manual') return [0, 0];

    const e = errorsOf(z);
    const fuzzy = evaluateFuzzy(e.e1, e.e2, cfg);

    return [
      clamp(fuzzy.velocity, -5, 5),
      clamp(fuzzy.omega, -5, 5)
    ];
  }

  function recordOf(z, t, u, fuzzy = null) {
    const e = errorsOf(z);

    return {
      t,
      x: z[0],
      y: z[1],
      theta: z[2],
      rx: z[3],
      ry: z[4],
      e1: e.e1,
      e2: e.e2,
      v: u[0],
      w: u[1],
      mass: fuzzy ? fuzzy.mass : 0
    };
  }

  function readBatchParameters() {
    const dt = clamp(
      finite($('batchDt').value, 1 / 60),
      0.001,
      0.2
    );

    const tf = clamp(
      finite($('batchTf').value, 20),
      0.1,
      600
    );

    return {
      z: constrainStateToTrack([
        finite($('batchX0').value),
        finite($('batchY0').value),
        finite($('batchTheta0').value),
        finite($('batchRefX').value, 2.62),
        finite($('batchRefY').value, -0.02)
      ]),

      mode: $('batchRefMode').value,
      controlMode: $('batchControlMode').value,
      dt,
      tf
    };
  }

  function runBatch() {
    stopReplay();

    const p = readBatchParameters();
    const records = [];

    let z = p.z.slice();
    let t = 0;
    let guard = 0;

    while (t < p.tf - 1e-12 && guard < 650000) {
      const h = Math.min(p.dt, p.tf - t);

      const e = errorsOf(z);
      const fuzzy = evaluateFuzzy(e.e1, e.e2, state.config);

      let u = p.controlMode === 'manual'
        ? [0, 0]
        : [
            clamp(fuzzy.velocity, -5, 5),
            clamp(fuzzy.omega, -5, 5)
          ];

      records.push(recordOf(z, t, u, fuzzy));

      state.lastFires = fuzzy.fires;
      state.lastFuzzy = fuzzy;

      z = rk4(z, t, h, u, p.mode);

      t += h;
      guard++;
    }

    const eFinal = errorsOf(z);
    const fFinal = evaluateFuzzy(
      eFinal.e1,
      eFinal.e2
    );

    const uFinal = p.controlMode === 'manual'
      ? [0, 0]
      : [fFinal.velocity, fFinal.omega];

    records.push(recordOf(z, p.tf, uFinal, fFinal));

    state.batch.records = records;
    state.batch.index = 0;
    state.batch.playhead = 0;

    state.currentZ = z.slice();
    state.currentTime = p.tf;
    state.currentU = uFinal.slice();

    $('batchStatus').textContent =
      `${records.length} amostras · ${fmt(p.tf, 2)} s · RK4`;

    $('batchStatus').classList.add('web');

    $('replayScrubber').disabled = false;
    $('replayScrubber').min = 0;
    $('replayScrubber').max = records.length - 1;
    $('replayScrubber').value = 0;

    $('replayPlay').disabled = false;
    $('replayPause').disabled = false;
    $('exportOfflinePng').disabled = false;

    updateReplayAt(0);
    drawOfflinePlots(records);
    updateDiagnostics();

    $('globalStatus').textContent =
      'Batch calculado · pronto para replay';
  }

  function updateReplayAt(index) {
    const records = state.batch.records;

    if (!records.length) return;

    const i = clamp(
      Math.round(index),
      0,
      records.length - 1
    );

    state.batch.index = i;

    const r = records[i];

    state.currentZ = [
      r.x,
      r.y,
      r.theta,
      r.rx,
      r.ry
    ];

    state.currentTime = r.t;
    state.currentU = [r.v, r.w];

    $('replayScrubber').value = i;
    $('replayTime').textContent = `${fmt(r.t, 2)} s`;
    $('hudTime').textContent = `${fmt(r.t, 2)} s`;

    updateHUD(
      state.currentZ,
      r.t,
      state.currentU
    );

    drawWorld(
      state.currentZ,
      r.t,
      $('batchRefMode').value
    );

    state.lastFires = records.length
      ? computeFiring(r.e1, r.e2)
      : [];

    updateDiagnostics();
    refreshRuleHighlights();
  }

  function stopReplay() {
    state.batch.playing = false;

    if (state.batch.raf) {
      cancelAnimationFrame(state.batch.raf);
    }

    state.batch.raf = 0;
  }

  function playReplay() {
    if (
      !state.batch.records.length ||
      state.batch.playing
    ) {
      return;
    }

    if (
      state.batch.index >=
      state.batch.records.length - 1
    ) {
      updateReplayAt(0);
    }

    state.batch.playing = true;
    state.batch.startedAt = performance.now();

    state.batch.playhead =
      state.batch.records[state.batch.index].t;

    const speed = () =>
      finite($('replaySpeed').value, 1);

    const frame = (now) => {
      if (!state.batch.playing) return;

      const elapsed =
        Math.max(0, (now - state.batch.startedAt) / 1000) *
        speed();

      const targetT =
        state.batch.playhead + elapsed;

      const records = state.batch.records;

      let i = state.batch.index;

      while (
        i < records.length - 1 &&
        records[i + 1].t <= targetT
      ) {
        i++;
      }

      updateReplayAt(i);

      if (i >= records.length - 1) {
        stopReplay();
        return;
      }

      state.batch.raf = requestAnimationFrame(frame);
    };

    state.batch.raf = requestAnimationFrame(frame);
  }

  function drawOfflinePlots(records) {
    if (!records || !records.length) return;

    drawLinePlot($('offlineStatePlot'), [
      {
        name: 'x',
        color: '#62a0ea',
        values: records.map((r) => [r.t, r.x])
      },
      {
        name: 'y',
        color: '#2ecc71',
        values: records.map((r) => [r.t, r.y])
      },
      {
        name: 'θ',
        color: '#e5a84b',
        values: records.map((r) => [r.t, r.theta])
      }
    ], 't (s)');

    drawLinePlot($('offlineErrorPlot'), [
      {
        name: 'eθ',
        color: '#e5a84b',
        values: records.map((r) => [r.t, r.e1])
      },
      {
        name: 'd',
        color: '#2ecc71',
        values: records.map((r) => [r.t, r.e2])
      }
    ], 't (s)');

    drawLinePlot($('offlineControlPlot'), [
      {
        name: 'v',
        color: '#2ecc71',
        values: records.map((r) => [r.t, r.v])
      },
      {
        name: 'ω',
        color: '#62a0ea',
        values: records.map((r) => [r.t, r.w])
      }
    ], 't (s)');

    drawLinePlot($('offlineInputPlot'), [
      {
        name: 'EA',
        color: '#e5a84b',
        values: records.map((r) => [r.t, r.e1])
      },
      {
        name: 'EP',
        color: '#c678dd',
        values: records.map((r) => [r.t, r.e2])
      }
    ], 't (s)');
  }

  function exportOfflinePlotsPng() {
    if (!state.batch.records.length) {
      alert('Execute primeiro uma simulação offline.');
      return;
    }

    // Redesenha para garantir que os canvases tenham conteúdo atual.
    drawOfflinePlots(state.batch.records);

    const sources = [
      ['offlineStatePlot', 'Estados da planta'],
      ['offlineErrorPlot', 'Referência e distância'],
      ['offlineControlPlot', 'Entradas de controle'],
      ['offlineInputPlot', 'Erros de controle']
    ];
    const tileW = 900;
    const tileH = 430;
    const pad = 44;
    const titleH = 78;
    const out = document.createElement('canvas');
    out.width = tileW * 2 + pad * 3;
    out.height = titleH + tileH * 2 + pad * 3;
    const ctx = out.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.fillStyle = '#111111';
    ctx.font = 'bold 28px sans-serif';
    ctx.fillText('Laboratório Virtual de Controle Fuzzy — Simulação Offline', pad, 42);
    ctx.font = '18px sans-serif';

    sources.forEach(([id, label], i) => {
      const src = $(id);
      const col = i % 2;
      const row = Math.floor(i / 2);
      const x = pad + col * (tileW + pad);
      const y = titleH + pad + row * (tileH + pad);
      ctx.fillStyle = '#111111';
      ctx.fillText(label, x, y - 12);
      ctx.drawImage(src, x, y, tileW, tileH);
    });

    out.toBlob((blob) => {
      if (!blob) return;
      downloadBlob(blob, 'simulacao_offline_fuzzy.png');
      $('globalStatus').textContent = 'Gráficos offline exportados em PNG';
    }, 'image/png');
  }

    function fitCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.max(1, window.devicePixelRatio || 1);

    const width = Math.max(
      1,
      Math.round(rect.width * dpr)
    );

    const height = Math.max(
      1,
      Math.round(rect.height * dpr)
    );

    if (
      canvas.width !== width ||
      canvas.height !== height
    ) {
      canvas.width = width;
      canvas.height = height;
    }

    const ctx = canvas.getContext('2d');

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    return {
      ctx,
      width: rect.width,
      height: rect.height,
      dpr
    };
  }

  function drawLinePlot(canvas, series, xLabel = 't') {
    if (!canvas || !series || !series.length) return;

    const {
      ctx,
      width: w,
      height: h
    } = fitCanvas(canvas);

    ctx.clearRect(0, 0, w, h);

    ctx.fillStyle = '#202020';
    ctx.fillRect(0, 0, w, h);

    const pad = {
      l: 38,
      r: 12,
      t: 12,
      b: 29
    };

    const pw = w - pad.l - pad.r;
    const ph = h - pad.t - pad.b;

    const all = series
      .flatMap((s) => s.values)
      .filter((p) =>
        Number.isFinite(p[0]) &&
        Number.isFinite(p[1])
      );

    if (!all.length) return;

    const xMin = Math.min(...all.map((p) => p[0]));
    const xMax = Math.max(...all.map((p) => p[0]));

    let yMin = Math.min(...all.map((p) => p[1]));
    let yMax = Math.max(...all.map((p) => p[1]));

    if (Math.abs(yMax - yMin) < 1e-8) {
      yMax += 1;
      yMin -= 1;
    }

    const yPad = (yMax - yMin) * .08;

    yMin -= yPad;
    yMax += yPad;

    const X = (x) =>
      pad.l +
      (x - xMin) /
      Math.max(1e-9, xMax - xMin) *
      pw;

    const Y = (y) =>
      pad.t +
      (1 - (y - yMin) / (yMax - yMin)) *
      ph;

    ctx.strokeStyle = '#3a3a3a';
    ctx.lineWidth = 1;
    ctx.fillStyle = '#999';
    ctx.font = '10px sans-serif';

    for (let i = 0; i <= 4; i++) {
      const y = pad.t + ph * i / 4;

      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(w - pad.r, y);
      ctx.stroke();

      const val =
        yMax - (yMax - yMin) * i / 4;

      ctx.fillText(
        fmt(val, 1),
        3,
        y + 3
      );
    }

    ctx.strokeStyle = '#606060';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, h - pad.b);
    ctx.lineTo(w - pad.r, h - pad.b);
    ctx.stroke();

    series.forEach((s) => {
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.6;
      ctx.beginPath();

      let started = false;

      for (const p of s.values) {
        if (
          !Number.isFinite(p[0]) ||
          !Number.isFinite(p[1])
        ) {
          continue;
        }

        if (!started) {
          ctx.moveTo(X(p[0]), Y(p[1]));
          started = true;
        } else {
          ctx.lineTo(X(p[0]), Y(p[1]));
        }
      }

      ctx.stroke();
    });

    ctx.fillStyle = '#aaa';
    ctx.textAlign = 'center';

    ctx.fillText(
      xLabel,
      pad.l + pw / 2,
      h - 4
    );

    ctx.textAlign = 'left';

    let lx = pad.l;

    for (const s of series) {
      ctx.fillStyle = s.color;
      ctx.fillRect(lx, 3, 8, 2);

      ctx.fillStyle = '#bdbdbd';
      ctx.fillText(s.name, lx + 11, 9);

      lx += 50;
    }
  }

  function loadImage(key, src) {
    return new Promise((resolve) => {
      const img = new Image();

      img.onload = () => {
        state.sprites[key] = img;
        resolve(true);
      };

      img.onerror = () => {
        state.sprites[key] = null;

        console.warn(
          `Sprite indisponível: ${src}; fallback vetorial ativado.`
        );

        resolve(false);
      };

      img.src = src;
    });
  }


  const CHALLENGE_TRACKS = {
    simple: {
      name: 'Simples · Oval',
      halfWidth: 1.10,
      wallGap: 0.48,
      maxSpeed: 3.5,
      defaultSpeed: 1.8,
      defaultLookahead: 1.25,
      knots: [
        [-5.0, 0.0], [-4.2, 2.9], [0.0, 4.15], [4.2, 2.9],
        [5.0, 0.0], [4.2, -2.9], [0.0, -4.15], [-4.2, -2.9]
      ]
    },
    medium: {
      name: 'Média · Técnica',
      halfWidth: 1.00,
      wallGap: 0.46,
      maxSpeed: 3.0,
      defaultSpeed: 1.6,
      defaultLookahead: 1.15,
      knots: [
        [-5.0, -0.4], [-4.3, 2.7], [-1.8, 4.15], [0.4, 2.75],
        [3.0, 3.95], [5.05, 2.0], [4.65, -0.9], [2.25, -3.35],
        [-0.75, -2.95], [-3.65, -3.9], [-5.0, -1.75]
      ]
    },
    hard: {
      name: 'Difícil · Sinuosa',
      halfWidth: 0.92,
      wallGap: 0.44,
      maxSpeed: 2.4,
      defaultSpeed: 1.35,
      defaultLookahead: 1.0,
      knots: [
        [-5.15, 0.1], [-4.35, 3.3], [-1.95, 4.4], [-0.05, 2.25],
        [2.45, 4.05], [5.05, 2.45], [4.15, 0.05], [2.05, -0.75],
        [3.55, -3.75], [0.65, -4.35], [-1.05, -2.05], [-4.35, -3.2]
      ]
    }
  };
  const challengeGeometryCache = new Map();

  function catmullRomPoint(p0, p1, p2, p3, t) {
    const t2 = t * t;
    const t3 = t2 * t;
    return [0, 1].map((i) => 0.5 * (
      2 * p1[i] +
      (-p0[i] + p2[i]) * t +
      (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t2 +
      (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t3
    ));
  }

  function buildChallengeGeometry(key) {
    if (challengeGeometryCache.has(key)) {
      return challengeGeometryCache.get(key);
    }
    const def = CHALLENGE_TRACKS[key];
    const knots = def.knots;
    const points = [];
    const perSpan = 32;
    for (let i = 0; i < knots.length; i++) {
      for (let j = 0; j < perSpan; j++) {
        points.push(catmullRomPoint(
          knots[(i - 1 + knots.length) % knots.length],
          knots[i],
          knots[(i + 1) % knots.length],
          knots[(i + 2) % knots.length],
          j / perSpan
        ));
      }
    }
    const segments = [];
    let length = 0;
    for (let i = 0; i < points.length; i++) {
      const a = points[i];
      const b = points[(i + 1) % points.length];
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const len = Math.max(EPS, Math.hypot(dx, dy));
      segments.push({
        a, b, dx, dy, len,
        s0: length,
        tx: dx / len,
        ty: dy / len,
        nx: -dy / len,
        ny: dx / len
      });
      length += len;
    }
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const geometry = {
      key,
      def,
      points,
      segments,
      length,
      bounds: {
        minX: Math.min(...xs), maxX: Math.max(...xs),
        minY: Math.min(...ys), maxY: Math.max(...ys)
      }
    };
    challengeGeometryCache.set(key, geometry);
    return geometry;
  }

  function challengePointAtS(geometry, s) {
    const L = geometry.length;
    let target = ((s % L) + L) % L;
    let seg = geometry.segments[geometry.segments.length - 1];
    for (const candidate of geometry.segments) {
      if (target >= candidate.s0 && target <= candidate.s0 + candidate.len) {
        seg = candidate;
        break;
      }
    }
    const u = clamp((target - seg.s0) / seg.len, 0, 1);
    return {
      x: seg.a[0] + u * seg.dx,
      y: seg.a[1] + u * seg.dy,
      tx: seg.tx, ty: seg.ty,
      nx: seg.nx, ny: seg.ny,
      s: target
    };
  }

  function projectChallengePoint(geometry, x, y) {
    let best = null;
    for (const seg of geometry.segments) {
      const px = x - seg.a[0];
      const py = y - seg.a[1];
      const u = clamp((px * seg.dx + py * seg.dy) / (seg.len * seg.len), 0, 1);
      const qx = seg.a[0] + u * seg.dx;
      const qy = seg.a[1] + u * seg.dy;
      const ex = x - qx;
      const ey = y - qy;
      const d2 = ex * ex + ey * ey;
      if (!best || d2 < best.d2) {
        best = {
          d2,
          distance: Math.sqrt(d2),
          signed: ex * seg.nx + ey * seg.ny,
          x: qx, y: qy,
          tx: seg.tx, ty: seg.ty,
          nx: seg.nx, ny: seg.ny,
          s: (seg.s0 + u * seg.len) % geometry.length
        };
      }
    }
    return best;
  }

  function challengeWallHalfWidth(geometry) {
    return geometry.def.halfWidth + geometry.def.wallGap;
  }

  function constrainChallengePose(pose, geometry) {
    const out = pose.slice();
    const pr = projectChallengePoint(geometry, out[0], out[1]);
    const limit = challengeWallHalfWidth(geometry) - 0.30;
    if (pr && pr.distance > limit) {
      const sign = pr.signed >= 0 ? 1 : -1;
      out[0] = pr.x + sign * pr.nx * limit;
      out[1] = pr.y + sign * pr.ny * limit;
    }
    out[2] = wrapAngle(out[2]);
    return out;
  }

  function integrateChallengePose(pose, v, w, dt) {
    const thetaMid = pose[2] + 0.5 * w * dt;
    return [
      pose[0] + v * Math.cos(thetaMid) * dt,
      pose[1] + v * Math.sin(thetaMid) * dt,
      wrapAngle(pose[2] + w * dt)
    ];
  }

  function challengeReferenceControl() {
    const c = state.challenge;
    const g = c.geometry;
    const p = c.reference;
    const pr = projectChallengePoint(g, p[0], p[1]);
    const target = challengePointAtS(g, pr.s + c.lookahead);
    const desired = Math.atan2(target.y - p[1], target.x - p[0]);
    const e = wrapAngle(desired - p[2]);
    const w = clamp(3.2 * e, -4.5, 4.5);
    return { v: c.speed, w, target, projection: pr };
  }

  function challengeStudentControl() {
    const c = state.challenge;
    const z = [
      c.student[0], c.student[1], c.student[2],
      c.reference[0], c.reference[1]
    ];
    const fuzzy = evaluateFuzzy(
      errorsOf(z).e1,
      errorsOf(z).e2,
      c.controller || state.config
    );
    return {
      v: clamp(fuzzy.velocity, -5, 5),
      w: clamp(fuzzy.omega, -5, 5),
      fuzzy
    };
  }

  function challengeScore() {
    const c = state.challenge;
    if (!c.geometry) return 0;
    const L = c.geometry.length;
    const coverage = clamp(c.validDistance / L, 0, 1);
    const difficulty = 1 + 0.60 * (c.speed / c.geometry.def.maxSpeed);
    const nominal = L / Math.max(0.1, c.speed);
    const timeFactor = Math.exp(-0.35 * c.time / Math.max(1, nominal));
    return Math.round(1000 * coverage * difficulty * timeFactor);
  }

  function resetChallengeState(keepSelection = true) {
    const c = state.challenge;
    c.running = false;
    c.paused = false;
    c.completed = false;
    if (c.raf) cancelAnimationFrame(c.raf);
    c.raf = 0;
    c.lastFrame = null;
    c.accumulator = 0;
    c.time = 0;
    c.geometry = buildChallengeGeometry(c.selected);
    const g = c.geometry;
    const start = challengePointAtS(g, 0);
    const refStart = challengePointAtS(g, 1.65);
    c.student = [start.x, start.y, Math.atan2(start.ty, start.tx)];
    c.reference = [refStart.x, refStart.y, Math.atan2(refStart.ty, refStart.tx)];
    c.prevStudentS = 0;
    c.studentProgress = 0;
    c.validDistance = 0;
    c.forwardDistance = 0;
    c.offtrackDistance = 0;
    c.lastStudentInside = true;
    c.lastControl = [0, 0];
    c.lastRefControl = [0, 0];
    c.controller = null;
    c.score = 0;
    c.camera = {
      x: (c.student[0] + c.reference[0]) / 2,
      y: (c.student[1] + c.reference[1]) / 2,
      halfH: 4.6
    };
    updateChallengeHud();
    drawChallenge();
  }

  function updateChallengeHud() {
    const c = state.challenge;
    if (!c.geometry) return;
    const progress = 100 * clamp(c.studentProgress / c.geometry.length, 0, 1);
    const validRatio = c.forwardDistance > EPS
      ? 100 * clamp(c.validDistance / c.forwardDistance, 0, 1)
      : 100;
    c.score = challengeScore();
    $('challengeTime').textContent = `${fmt(c.time, 2)} s`;
    $('challengeProgress').textContent = `${fmt(progress, 1)}%`;
    $('challengeValid').textContent = `${fmt(validRatio, 1)}%`;
    $('challengeScore').textContent = String(c.score);
    $('challengeRefSpeed').textContent = `${fmt(c.speed, 1)} m/s`;
    $('challengeTrackName').textContent = c.geometry.def.name;
    $('challengeLength').textContent = `${fmt(c.geometry.length, 1)} m`;
    $('challengeValidDistance').textContent = `${fmt(c.validDistance, 1)} m`;
    $('challengeFinalScore').textContent = String(c.score);
    $('challengeTrackState').textContent = c.lastStudentInside
      ? 'Dentro da pista'
      : 'Fora da faixa válida';
    $('challengeTrackState').style.color = c.lastStudentInside ? '#8ee0ae' : '#f2c77c';
    if (c.completed) {
      $('challengeLapTime').textContent = `${fmt(c.time, 2)} s`;
      $('challengeResultText').textContent =
        `Volta completa · ${fmt(validRatio, 1)}% do progresso foi realizado dentro da faixa válida.`;
    } else {
      $('challengeLapTime').textContent = '—';
    }
  }

  function updateChallengeCamera() {
    const c = state.challenge;
    const canvas = $('challengeCanvas');
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return;
    const aspect = rect.width / rect.height;
    const cx = (c.student[0] + c.reference[0]) / 2;
    const cy = (c.student[1] + c.reference[1]) / 2;
    const dx = Math.abs(c.student[0] - c.reference[0]);
    const dy = Math.abs(c.student[1] - c.reference[1]);
    const targetHalfH = clamp(
      Math.max(3.3, dy / 2 + 2.2, (dx / 2 + 2.2) / Math.max(.4, aspect)),
      3.3,
      7.8
    );
    c.camera.x += 0.08 * (cx - c.camera.x);
    c.camera.y += 0.08 * (cy - c.camera.y);
    c.camera.halfH += 0.08 * (targetHalfH - c.camera.halfH);
  }

  function drawChallengeWallTile(ctx, image, x, y, theta) {
    const size = 0.58;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(theta);
    if (image && image.complete && image.naturalWidth) {
      ctx.drawImage(image, -size / 2, -size / 2, size, size);
    } else {
      ctx.fillStyle = '#74787c';
      ctx.fillRect(-size / 2, -size / 2, size, size);
      ctx.strokeStyle = '#565b5e';
      ctx.lineWidth = .025;
      ctx.strokeRect(-size / 2, -size / 2, size, size);
    }
    ctx.restore();
  }

  function challengePath(ctx, geometry) {
    ctx.beginPath();
    geometry.points.forEach((p, i) => {
      if (i === 0) ctx.moveTo(p[0], p[1]);
      else ctx.lineTo(p[0], p[1]);
    });
    ctx.closePath();
  }

  function drawChallenge() {
    const canvas = $('challengeCanvas');
    const c = state.challenge;
    if (!canvas || !c.geometry) return;
    const { ctx, width: w, height: h } = fitCanvas(canvas);
    if (w < 1 || h < 1) return;
    updateChallengeCamera();
    const halfH = c.camera.halfH;
    const scale = h / (2 * halfH);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#26383b';
    ctx.fillRect(0, 0, w, h);
    ctx.save();
    ctx.translate(w / 2, h / 2);
    ctx.scale(scale, -scale);
    ctx.translate(-c.camera.x, -c.camera.y);

    const worldHalfW = w / scale / 2;
    const worldHalfH = h / scale / 2;
    ctx.fillStyle = '#293d40';
    ctx.fillRect(c.camera.x - worldHalfW, c.camera.y - worldHalfH, 2 * worldHalfW, 2 * worldHalfH);
    ctx.strokeStyle = 'rgba(210,230,230,.07)';
    ctx.lineWidth = .015;
    for (let gx = Math.floor(c.camera.x - worldHalfW); gx <= c.camera.x + worldHalfW; gx++) {
      ctx.beginPath(); ctx.moveTo(gx, c.camera.y - worldHalfH); ctx.lineTo(gx, c.camera.y + worldHalfH); ctx.stroke();
    }
    for (let gy = Math.floor(c.camera.y - worldHalfH); gy <= c.camera.y + worldHalfH; gy++) {
      ctx.beginPath(); ctx.moveTo(c.camera.x - worldHalfW, gy); ctx.lineTo(c.camera.x + worldHalfW, gy); ctx.stroke();
    }

    // Base do corredor físico, seguida pela faixa válida de pontuação.
    challengePath(ctx, c.geometry);
    ctx.strokeStyle = '#5e6669';
    ctx.lineWidth = 2 * (challengeWallHalfWidth(c.geometry) + .20);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
    challengePath(ctx, c.geometry);
    ctx.strokeStyle = '#ece4d2';
    ctx.lineWidth = 2 * c.geometry.def.halfWidth;
    ctx.stroke();

    // Linha central vetorial.
    challengePath(ctx, c.geometry);
    ctx.strokeStyle = 'rgba(72,155,123,.72)';
    ctx.lineWidth = .055;
    ctx.setLineDash([.22, .20]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Muros com os mesmos sprites das demais abas. Colocados fora da
    // faixa válida para permitir pequena excursão sem permitir atalhos.
    const wallHalf = challengeWallHalfWidth(c.geometry);
    const tiles = [];
    const spacing = .55;
    for (let s = 0; s < c.geometry.length; s += spacing) {
      const p = challengePointAtS(c.geometry, s);
      const theta = Math.atan2(p.ty, p.tx);
      for (const sign of [-1, 1]) {
        tiles.push({
          x: p.x + sign * p.nx * wallHalf,
          y: p.y + sign * p.ny * wallHalf,
          theta
        });
      }
    }
    tiles.sort((a, b) => b.y - a.y);
    tiles.forEach((tile) => drawChallengeWallTile(
      ctx,
      state.sprites.topTile,
      tile.x,
      tile.y,
      tile.theta
    ));

    // Look-ahead da referência.
    const rc = challengeReferenceControl();
    ctx.strokeStyle = 'rgba(99,201,155,.55)';
    ctx.lineWidth = .035;
    ctx.beginPath();
    ctx.moveTo(c.reference[0], c.reference[1]);
    ctx.lineTo(rc.target.x, rc.target.y);
    ctx.stroke();
    ctx.fillStyle = '#63c99b';
    ctx.beginPath(); ctx.arc(rc.target.x, rc.target.y, .10, 0, TAU); ctx.fill();

    drawRobot(ctx, 'robot', c.student[0], c.student[1], c.student[2], '#b93a32');
    drawRobot(ctx, 'ref', c.reference[0], c.reference[1], c.reference[2], '#e8c49d');
    ctx.restore();
  }

  function drawChallengePreview(key) {
    const id = {
      simple: 'challengePreviewSimple',
      medium: 'challengePreviewMedium',
      hard: 'challengePreviewHard'
    }[key];
    const canvas = $(id);
    if (!canvas) return;
    const { ctx, width: w, height: h } = fitCanvas(canvas);
    if (w < 1 || h < 1) return;
    const g = buildChallengeGeometry(key);
    const pad = 16;
    const bw = g.bounds.maxX - g.bounds.minX + 2 * (g.def.halfWidth + g.def.wallGap);
    const bh = g.bounds.maxY - g.bounds.minY + 2 * (g.def.halfWidth + g.def.wallGap);
    const scale = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh);
    const cx = (g.bounds.minX + g.bounds.maxX) / 2;
    const cy = (g.bounds.minY + g.bounds.maxY) / 2;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#26383b'; ctx.fillRect(0, 0, w, h);
    ctx.save(); ctx.translate(w / 2, h / 2); ctx.scale(scale, -scale); ctx.translate(-cx, -cy);
    challengePath(ctx, g); ctx.strokeStyle = '#626b6f'; ctx.lineWidth = 2 * (g.def.halfWidth + g.def.wallGap); ctx.stroke();
    challengePath(ctx, g); ctx.strokeStyle = '#ece4d2'; ctx.lineWidth = 2 * g.def.halfWidth; ctx.stroke();
    challengePath(ctx, g); ctx.strokeStyle = '#63c99b'; ctx.lineWidth = .06; ctx.setLineDash([.25,.22]); ctx.stroke(); ctx.setLineDash([]);
    ctx.restore();
  }

  function selectChallengeTrack(key) {
    const c = state.challenge;
    c.selected = key;
    c.geometry = buildChallengeGeometry(key);
    const def = c.geometry.def;
    document.querySelectorAll('.track-card').forEach((card) => {
      card.classList.toggle('active', card.dataset.track === key);
    });
    $('challengeSpeed').max = String(def.maxSpeed);
    $('challengeSpeed').value = String(def.defaultSpeed);
    $('challengeSpeedValue').textContent = `${def.defaultSpeed.toFixed(1)} m/s`;
    $('challengeSpeedHint').textContent = `Velocidade máxima validada para esta pista: ${def.maxSpeed.toFixed(1)} m/s.`;
    $('challengeLookahead').value = String(def.defaultLookahead);
    c.speed = def.defaultSpeed;
    c.lookahead = def.defaultLookahead;
    resetChallengeState();
  }

  function updateChallengeStep() {
    const c = state.challenge;
    const dt = c.dt;
    const refU = challengeReferenceControl();
    const stuU = challengeStudentControl();
    c.reference = constrainChallengePose(
      integrateChallengePose(c.reference, refU.v, refU.w, dt),
      c.geometry
    );
    c.student = constrainChallengePose(
      integrateChallengePose(c.student, stuU.v, stuU.w, dt),
      c.geometry
    );
    c.lastRefControl = [refU.v, refU.w];
    c.lastControl = [stuU.v, stuU.w];
    c.time += dt;

    const pr = projectChallengePoint(c.geometry, c.student[0], c.student[1]);
    const L = c.geometry.length;
    let ds = pr.s - c.prevStudentS;
    if (ds < -L / 2) ds += L;
    if (ds > L / 2) ds -= L;
    const maxReasonable = (Math.abs(stuU.v) + 1.0) * dt * 2.5 + .05;
    if (Math.abs(ds) > maxReasonable) ds = 0;
    c.prevStudentS = pr.s;
    c.studentProgress += ds;
    const forward = Math.max(0, ds);
    c.forwardDistance += forward;
    c.lastStudentInside = pr.distance <= c.geometry.def.halfWidth;
    if (c.lastStudentInside) c.validDistance += forward;
    else c.offtrackDistance += forward;
    c.score = challengeScore();

    if (c.studentProgress >= L * .995 && c.time > 2) {
      c.studentProgress = L;
      c.completed = true;
      c.running = false;
      $('challengeResultText').textContent = 'Volta completa.';
      $('globalStatus').textContent = `Desafio concluído · score ${c.score}`;
    }
    updateChallengeHud();
  }

  function startChallenge() {
    const c = state.challenge;
    if (c.running) return;
    if (c.completed || !c.controller) {
      try {
        validateFmlExportConfig(state.config);
      } catch (err) {
        $('challengeResultText').textContent = `Controlador incompleto: ${err.message}`;
        $('globalStatus').textContent = 'Complete o controlador fuzzy antes do desafio.';
        return;
      }
      resetChallengeState();
      c.controller = JSON.parse(JSON.stringify(state.config));
      c.speed = clamp(finite($('challengeSpeed').value, c.geometry.def.defaultSpeed), .4, c.geometry.def.maxSpeed);
      c.lookahead = clamp(finite($('challengeLookahead').value, c.geometry.def.defaultLookahead), .4, 3);
    }
    c.running = true;
    c.paused = false;
    c.lastFrame = null;
    c.accumulator = 0;
    $('challengeResultText').textContent = 'Tentativa em andamento; o controlador está congelado.';
    $('globalStatus').textContent = `Desafio em andamento · ${c.geometry.def.name}`;
    const frame = (now) => {
      if (!c.running) return;
      if (c.lastFrame == null) c.lastFrame = now;
      const elapsed = clamp((now - c.lastFrame) / 1000, 0, .12);
      c.lastFrame = now;
      c.accumulator += elapsed;
      let steps = 0;
      while (c.accumulator >= c.dt && steps < 12 && c.running) {
        updateChallengeStep();
        c.accumulator -= c.dt;
        steps++;
      }
      drawChallenge();
      if (c.running) c.raf = requestAnimationFrame(frame);
    };
    c.raf = requestAnimationFrame(frame);
  }

  function pauseChallenge() {
    const c = state.challenge;
    if (!c.running) return;
    c.running = false;
    c.paused = true;
    if (c.raf) cancelAnimationFrame(c.raf);
    c.raf = 0;
    c.lastFrame = null;
    $('challengeResultText').textContent = 'Tentativa pausada; o controlador continua congelado.';
  }

  function initChallengeUi() {
    ['simple','medium','hard'].forEach(drawChallengePreview);
    selectChallengeTrack(state.challenge.selected);
  }

  function worldCanvasMetrics() {
    const rect = $('worldCanvas').getBoundingClientRect();

    return {
      w: rect.width,
      h: rect.height,
      scale: rect.height / 10,
      worldW: rect.width / (rect.height / 10)
    };
  }

  const WALL_XS = [
    -2.65, -2.212, -1.771, -1.333,
    -.879, -.441, 0, .438, .888,
    1.326, 1.767, 2.205, 2.659,
    3.097, 3.538, 3.976, 4.431,
    4.872, 5.31
  ];

  const WALL_YS = Array.from(
    { length: 17 },
    (_, i) => -3.26 + i * .45
  );

  // Limites internos da pista, inferidos a partir da geometria visual
  // dos sprites de parede e usados tanto para o preenchimento da área
  // trafegável quanto para restringir a movimentação dos dois carrinhos.
  const TRACK_INNER_BOUNDS = {
    left: -2.335,
    right: 4.995,
    bottom: -3.405,
    top: 4.105
  };
  const TRACK_COLLISION_MARGIN = 0.38;

  function clampPointToTrack(x, y, margin = TRACK_COLLISION_MARGIN) {
    return [
      clamp(x, TRACK_INNER_BOUNDS.left + margin, TRACK_INNER_BOUNDS.right - margin),
      clamp(y, TRACK_INNER_BOUNDS.bottom + margin, TRACK_INNER_BOUNDS.top - margin)
    ];
  }

  function constrainStateToTrack(z) {
    const out = z.slice();
    [out[0], out[1]] = clampPointToTrack(out[0], out[1]);
    [out[3], out[4]] = clampPointToTrack(out[3], out[4]);
    if (out.length > 2) {
      out[2] = wrapAngle(out[2]);
    }
    return out;
  }

  function drawTile(
    ctx,
    image,
    x,
    y,
    color = '#84979a'
  ) {
    const size = .63;

    if (
      image &&
      image.complete &&
      image.naturalWidth
    ) {
      ctx.drawImage(
        image,
        x - size / 2,
        y - size / 2,
        size,
        size
      );
    } else {
      ctx.fillStyle = color;

      ctx.fillRect(
        x - size / 2,
        y - size / 2,
        size,
        size
      );

      ctx.strokeStyle = '#63777a';
      ctx.lineWidth = .025;

      ctx.strokeRect(
        x - size / 2,
        y - size / 2,
        size,
        size
      );

      ctx.beginPath();

      ctx.moveTo(x - size / 2, y);
      ctx.lineTo(x + size / 2, y);

      ctx.moveTo(x, y - size / 2);
      ctx.lineTo(x, y + size / 2);

      ctx.stroke();
    }
  }

  function drawFallbackRobot(ctx, color) {
    ctx.fillStyle = '#16191b';

    ctx.beginPath();

    if (ctx.roundRect) {
      ctx.roundRect(-.36, -.42, .72, .84, .12);
    } else {
      ctx.rect(-.36, -.42, .72, .84);
    }

    ctx.fill();

    ctx.fillStyle = color;
    ctx.beginPath();

    if (ctx.roundRect) {
      ctx.roundRect(-.29, -.35, .58, .7, .1);
    } else {
      ctx.rect(-.29, -.35, .58, .7);
    }

    ctx.fill();

    ctx.fillStyle = '#5979e8';
    ctx.fillRect(-.19, .08, .38, .18);

    ctx.fillStyle = '#f3d5a2';
    ctx.beginPath();
    ctx.arc(0, .29, .055, 0, TAU);
    ctx.fill();

    ctx.fillStyle = '#111';

    ctx.fillRect(-.43, -.25, .09, .22);
    ctx.fillRect(.34, -.25, .09, .22);
  }

  function drawRobot(
    ctx,
    key,
    x,
    y,
    theta,
    fallbackColor
  ) {
    ctx.save();

    ctx.translate(x, y);
    ctx.rotate(theta + Math.PI / 2);

    const img = state.sprites[key];

    if (
      img &&
      img.complete &&
      img.naturalWidth
    ) {
      ctx.drawImage(
        img,
        -.45,
        -.45,
        .9,
        .9
      );
    } else {
      drawFallbackRobot(ctx, fallbackColor);
    }

    ctx.restore();
  }

  function drawWorld(z, t, refMode = 'manual') {
    const canvas = $('worldCanvas');

    const {
      ctx,
      width: w,
      height: h
    } = fitCanvas(canvas);

    // A aba de teoria/configuração pode deixar este Canvas oculto.
    // Nesse caso getBoundingClientRect() retorna 0 × 0; não há nada a desenhar.
    if (w < 1 || h < 1) return;

    ctx.clearRect(0, 0, w, h);
    ctx.imageSmoothingEnabled = false;

    ctx.fillStyle = '#26383b';
    ctx.fillRect(0, 0, w, h);

    const scale = h / 10;
    const worldW = w / scale;

    ctx.save();

    ctx.translate(w / 2, h / 2);
    ctx.scale(scale, -scale);

    // Fundo vetorial: o sprite de fundo referenciado
    // pela cena não está presente no Assets.zip.
    const gradient = ctx.createRadialGradient(
      1.0, 1.0, 1,
      0, 0,
      worldW * .62
    );

    gradient.addColorStop(0, '#405659');
    gradient.addColorStop(1, '#25373a');

    ctx.fillStyle = gradient;
    ctx.fillRect(-worldW / 2, -5, worldW, 10);

    ctx.strokeStyle = 'rgba(195,220,220,.09)';
    ctx.lineWidth = .012;

    for (
      let gx = Math.floor(-worldW / 2);
      gx <= worldW / 2;
      gx++
    ) {
      ctx.beginPath();
      ctx.moveTo(gx, -5);
      ctx.lineTo(gx, 5);
      ctx.stroke();
    }

    for (let gy = -5; gy <= 5; gy++) {
      ctx.beginPath();
      ctx.moveTo(-worldW / 2, gy);
      ctx.lineTo(worldW / 2, gy);
      ctx.stroke();
    }

    // Faixa geral da área da pista e piso interno trafegável.
    ctx.fillStyle = 'rgba(15,23,24,.22)';
    ctx.fillRect(-2.98, -3.95, 8.65, 8.65);

    // Piso da pista aceitável: bege/off-white para contrastar com a
    // região externa da cena e indicar visualmente a área permitida.
    ctx.fillStyle = 'rgba(234, 227, 212, 0.82)';
    ctx.fillRect(
      TRACK_INNER_BOUNDS.left,
      TRACK_INNER_BOUNDS.bottom,
      TRACK_INNER_BOUNDS.right - TRACK_INNER_BOUNDS.left,
      TRACK_INNER_BOUNDS.top - TRACK_INNER_BOUNDS.bottom
    );
    ctx.strokeStyle = 'rgba(120, 108, 88, 0.45)';
    ctx.lineWidth = .015;
    ctx.strokeRect(
      TRACK_INNER_BOUNDS.left,
      TRACK_INNER_BOUNDS.bottom,
      TRACK_INNER_BOUNDS.right - TRACK_INNER_BOUNDS.left,
      TRACK_INNER_BOUNDS.top - TRACK_INNER_BOUNDS.bottom
    );

    // Limites montados por prefabs cubo_cima/cubo_lado.
    // Parede superior.
    WALL_XS.forEach((x) => {
      drawTile(
        ctx,
        state.sprites.topTile,
        x,
        4.42,
        '#829598'
      );
    });

    // Os cubos laterais se sobrepõem ligeiramente. Como o Canvas está
    // com o eixo y invertido para reproduzir as coordenadas do Unity,
    // eles precisam ser pintados de cima para baixo na tela (ordem
    // inversa em coordenadas de mundo) para preservar a perspectiva
    // original do sprite cubo_lado.
    [...WALL_YS].reverse().forEach((y) => {
      drawTile(
        ctx,
        state.sprites.sideTile,
        -2.65,
        y,
        '#85979a'
      );

      drawTile(
        ctx,
        state.sprites.sideTile,
        5.31,
        y,
        '#85979a'
      );
    });

    // Parede inferior desenhada por último entre os limites para que os
    // dois cubos laterais mais baixos fiquem por trás dela, como no layout
    // visual original do Unity.
    WALL_XS.forEach((x) => {
      drawTile(
        ctx,
        state.sprites.topTile,
        x,
        -3.72,
        '#829598'
      );
    });

    // Eixos e marcação de referência.
    ctx.strokeStyle = 'rgba(230,240,240,.3)';
    ctx.lineWidth = .018;

    ctx.beginPath();

    ctx.moveTo(-worldW / 2, 0);
    ctx.lineTo(worldW / 2, 0);

    ctx.moveTo(0, -5);
    ctx.lineTo(0, 5);

    ctx.stroke();

    const dx = z[3] - z[0];
    const dy = z[4] - z[1];

    ctx.strokeStyle = 'rgba(46,204,113,.55)';
    ctx.lineWidth = .025;
    ctx.setLineDash([.12, .09]);

    ctx.beginPath();
    ctx.moveTo(z[0], z[1]);
    ctx.lineTo(z[3], z[4]);
    ctx.stroke();

    ctx.setLineDash([]);

    ctx.strokeStyle = '#b0f0cb';
    ctx.lineWidth = .025;

    ctx.beginPath();
    ctx.arc(z[3], z[4], .24, 0, TAU);
    ctx.stroke();

    ctx.beginPath();

    ctx.moveTo(z[3] - .35, z[4]);
    ctx.lineTo(z[3] + .35, z[4]);

    ctx.moveTo(z[3], z[4] - .35);
    ctx.lineTo(z[3], z[4] + .35);

    ctx.stroke();

    // Orientação da referência: no modo manual, usa a orientação
    // pilotada; nos modos automáticos, usa a direção do movimento.
    let refHeading = refMode === 'manual'
      ? state.online.refTheta
      : 0;

    const rd = refDerivative(z, t, refMode);

    if (refMode !== 'manual' && Math.hypot(rd[0], rd[1]) > 1e-5) {
      refHeading = Math.atan2(rd[1], rd[0]);
    }

    drawRobot(
      ctx,
      'ref',
      z[3],
      z[4],
      refHeading,
      '#2eae77'
    );

    drawRobot(
      ctx,
      'robot',
      z[0],
      z[1],
      z[2],
      '#b43d43'
    );

    // Indicador do heading do robô.
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = .025;

    ctx.beginPath();

    ctx.moveTo(z[0], z[1]);

    ctx.lineTo(
      z[0] + .7 * Math.cos(z[2]),
      z[1] + .7 * Math.sin(z[2])
    );

    ctx.stroke();

    ctx.restore();
  }

  function updateHUD(z, t, u) {
    const e = errorsOf(z);

    $('hudTime').textContent = `${fmt(t, 2)} s`;
    $('hudTheta').textContent = `${fmt(z[2], 2)} rad`;

    $('hudE1').textContent = fmt(e.e1, 2);
    $('hudE2').textContent = fmt(e.e2, 2);

    $('hudV').textContent = fmt(u[0], 2);
    $('hudW').textContent = fmt(u[1], 2);

    $('metricPosition').textContent =
      `(${fmt(z[0])}, ${fmt(z[1])})`;

    $('metricReference').textContent =
      `(${fmt(z[3])}, ${fmt(z[4])})`;

    $('metricErrorAngle').textContent =
      `${fmt(e.e1)} rad`;

    $('metricErrorDistance').textContent =
      `${fmt(e.e2)} m`;
  }

  async function ensurePlotly() {
    if (window.Plotly) {
      state.plotlyReady = true;
      return true;
    }

    if (state.plotlyPromise) {
      return state.plotlyPromise;
    }

    state.plotlyPromise = new Promise((resolve) => {
      const script = document.createElement('script');

      script.src =
        'https://cdn.plot.ly/plotly-2.35.2.min.js';

      script.async = true;

      script.onload = () => {
        state.plotlyReady = true;
        resolve(true);
      };

      script.onerror = () => {
        state.plotlyReady = false;
        resolve(false);
      };

      document.head.appendChild(script);
    });

    return state.plotlyPromise;
  }

  function ensureLiveFallbackCanvas(div) {
    if (!div.querySelector('canvas')) {
      div.textContent = '';

      const c = document.createElement('canvas');

      c.style.width = '100%';
      c.style.height = '260px';

      div.appendChild(c);
    }

    return div.querySelector('canvas');
  }

  function updateLivePlots() {
    const hist = state.online.history;

    if (!hist.length) return;

    const now = state.online.time;
    const start = Math.max(0, now - 10);

    const recent = hist
      .filter((r) => r.t >= start)
      .slice(-600);

    // Janela móvel + limite de memória/renderização.
    if (window.Plotly && state.plotlyReady) {
      const x = recent.map((r) => r.t).slice(-600);

      const tracesState = [
        {
          x: x.slice(),
          y: recent.map((r) => r.x).slice(-600),
          name: 'x',
          mode: 'lines',
          line: {
            color: '#62a0ea',
            width: 1.5
          }
        },
        {
          x: x.slice(),
          y: recent.map((r) => r.y).slice(-600),
          name: 'y',
          mode: 'lines',
          line: {
            color: '#2ecc71',
            width: 1.5
          }
        },
        {
          x: x.slice(),
          y: recent.map((r) => r.e1).slice(-600),
          name: 'eθ',
          mode: 'lines',
          line: {
            color: '#e5a84b',
            width: 1.3,
            dash: 'dot'
          }
        },
        {
          x: x.slice(),
          y: recent.map((r) => r.e2).slice(-600),
          name: 'd',
          mode: 'lines',
          line: {
            color: '#c678dd',
            width: 1.3,
            dash: 'dot'
          }
        }
      ];

      const tracesControl = [
        {
          x: x.slice(),
          y: recent.map((r) => r.v).slice(-600),
          name: 'v',
          mode: 'lines',
          line: {
            color: '#2ecc71',
            width: 1.5
          }
        },
        {
          x: x.slice(),
          y: recent.map((r) => r.w).slice(-600),
          name: 'ω',
          mode: 'lines',
          line: {
            color: '#62a0ea',
            width: 1.5
          }
        }
      ];

      const layout = (title) => ({
        title: {
          text: title,
          font: {
            size: 11,
            color: '#ddd'
          }
        },

        paper_bgcolor: '#202020',
        plot_bgcolor: '#202020',

        font: {
          color: '#bbb',
          size: 10
        },

        margin: {
          l: 42,
          r: 12,
          t: 35,
          b: 35
        },

        xaxis: {
          title: 't (s)',
          gridcolor: '#383838',
          range: [start, Math.max(10, now)]
        },

        yaxis: {
          gridcolor: '#383838',
          zerolinecolor: '#555'
        },

        legend: {
          orientation: 'h',
          y: 1.14
        },

        datarevision: ++state.online.dataRevision,
        uirevision: 'fuzzy-live'
      });

      Plotly.react(
        'liveStatePlot',
        tracesState,
        layout('Estados e erros'),
        {
          responsive: true,
          displayModeBar: false
        }
      );

      Plotly.react(
        'liveControlPlot',
        tracesControl,
        layout('Comandos aplicados'),
        {
          responsive: true,
          displayModeBar: false
        }
      );
    } else {
      const c1 = ensureLiveFallbackCanvas(
        $('liveStatePlot')
      );

      const c2 = ensureLiveFallbackCanvas(
        $('liveControlPlot')
      );

      drawLinePlot(c1, [
        {
          name: 'x',
          color: '#62a0ea',
          values: recent.map((r) => [r.t, r.x])
        },
        {
          name: 'y',
          color: '#2ecc71',
          values: recent.map((r) => [r.t, r.y])
        },
        {
          name: 'eθ',
          color: '#e5a84b',
          values: recent.map((r) => [r.t, r.e1])
        },
        {
          name: 'd',
          color: '#c678dd',
          values: recent.map((r) => [r.t, r.e2])
        }
      ]);

      drawLinePlot(c2, [
        {
          name: 'v',
          color: '#2ecc71',
          values: recent.map((r) => [r.t, r.v])
        },
        {
          name: 'ω',
          color: '#62a0ea',
          values: recent.map((r) => [r.t, r.w])
        }
      ]);
    }
  }

  function updateManualReference(dt) {
    const o = state.online;
    if (o.refMode !== 'manual') return;

    const maxDv = 3.0 * dt;
    const maxDw = 4.0 * dt;
    o.refManualActual[0] += clamp(
      o.refManualTarget[0] - o.refManualActual[0],
      -maxDv,
      maxDv
    );
    o.refManualActual[1] += clamp(
      o.refManualTarget[1] - o.refManualActual[1],
      -maxDw,
      maxDw
    );

    const v = clamp(o.refManualActual[0], -5, 5);
    const w = clamp(o.refManualActual[1], -5, 5);
    o.refTheta = wrapAngle(o.refTheta + dt * w);
    o.z[3] += dt * v * Math.cos(o.refTheta);
    o.z[4] += dt * v * Math.sin(o.refTheta);
    [o.z[3], o.z[4]] = clampPointToTrack(o.z[3], o.z[4]);
  }

    function updateOnlineStep() {
    const o = state.online;

    const dt = o.dt;
    const z = o.z;

    updateManualReference(dt);

    const e = errorsOf(z);
    const fuzzy = evaluateFuzzy(e.e1, e.e2, state.config);

    let u;

    if (o.controlMode === 'manual') {
      // Rampa de comando limitada:
      // recurso de operação didática, fora do modelo Unity.
      const maxDv = 3.0 * dt;
      const maxDw = 4.0 * dt;

      o.manualActual[0] += clamp(
        o.manualTarget[0] - o.manualActual[0],
        -maxDv,
        maxDv
      );

      o.manualActual[1] += clamp(
        o.manualTarget[1] - o.manualActual[1],
        -maxDw,
        maxDw
      );

      u = o.manualActual.slice();
    } else {
      u = [fuzzy.velocity, fuzzy.omega];
    }

    if (
      o.disturbance &&
      o.time <= o.disturbance.until
    ) {
      u[0] += o.disturbance.dv;
      u[1] += o.disturbance.dw;
    } else {
      o.disturbance = null;
    }

    u[0] = clamp(u[0], -5, 5);
    u[1] = clamp(u[1], -5, 5);

    const next = rk4(
      z,
      o.time,
      dt,
      u,
      o.refMode
    );

    o.z = next;
    o.time += dt;
    o.lastControl = u.slice();

    const record = recordOf(
      next,
      o.time,
      u,
      fuzzy
    );

    o.history.push(record);

    if (o.history.length > 12000) {
      o.history.splice(
        0,
        o.history.length - 12000
      );
    }

    state.currentZ = next.slice();
    state.currentTime = o.time;
    state.currentU = u.slice();

    state.lastFires = fuzzy.fires;
    state.lastFuzzy = fuzzy;

    $('onlineClock').textContent =
      `${fmt(o.time, 2)} s`;

    $('onlineRefX').value =
      next[3].toFixed(3);

    $('onlineRefY').value =
      next[4].toFixed(3);

    $('onlineRefRange').value = String(
      clamp(next[3], -5, 7)
    );

    updateHUD(next, o.time, u);
    updateDiagnostics();
    refreshRuleHighlights();
  }

  function startOnline() {
    const o = state.online;

    if (o.running) return;

    o.running = true;
    o.lastFrame = null;
    o.accumulator = 0;

    $('onlineStatus').textContent = 'Executando';
    $('onlineStatus').classList.add('web');

    $('globalStatus').textContent =
      'Simulação online em execução';

    const frame = async (now) => {
      if (!o.running) return;

      if (o.lastFrame == null) {
        o.lastFrame = now;
      }

      const elapsed = clamp(
        (now - o.lastFrame) / 1000,
        0,
        .12
      );

      o.lastFrame = now;
      o.accumulator += elapsed;

      let steps = 0;

      while (
        o.accumulator >= o.dt &&
        steps < 12
      ) {
        updateOnlineStep();
        o.accumulator -= o.dt;
        steps++;
      }

      // Se a aba ficou suspensa, descarta o excesso
      // em vez de executar um salto numérico enorme.
      if (
        steps === 12 &&
        o.accumulator > o.dt * 12
      ) {
        o.accumulator = 0;
      }

      drawWorld(
        o.z,
        o.time,
        o.refMode
      );

      if (now - o.lastPlotAt > 250) {
        o.lastPlotAt = now;
        updateLivePlots();
      }

      o.raf = requestAnimationFrame(frame);
    };

    o.raf = requestAnimationFrame(frame);
  }

  function pauseOnline() {
    const o = state.online;

    o.running = false;

    if (o.raf) {
      cancelAnimationFrame(o.raf);
    }

    o.raf = 0;
    o.lastFrame = null;

    $('onlineStatus').textContent = 'Pausada';
    $('onlineStatus').classList.remove('web');

    $('globalStatus').textContent =
      'Simulação online pausada';
  }

  function resetOnline() {
    pauseOnline();

    const o = state.online;

    o.dt = clamp(
      finite($('onlineDt').value, 1 / 60),
      .002,
      .05
    );

    o.z = constrainStateToTrack([
      finite($('onlineX0').value),
      finite($('onlineY0').value),
      finite($('onlineTheta0').value),
      finite($('onlineRefX').value, 2.62),
      finite($('onlineRefY').value, -.02)
    ]);

    o.time = 0;
    o.history = [];
    o.dataRevision++;

    o.manualActual = [0, 0];
    o.manualTarget = [0, 0];
    o.refManualActual = [0, 0];
    o.refManualTarget = [0, 0];
    o.refTheta = finite($('onlineThetaRef0')?.value, 0);
    o.disturbance = null;

    state.currentZ = o.z.slice();
    state.currentTime = 0;
    state.currentU = [0, 0];
    state.lastFires = [];

    $('onlineClock').textContent = '0.00 s';

    updateHUD(o.z, 0, [0, 0]);

    drawWorld(
      o.z,
      0,
      o.refMode
    );

    updateLivePlots();

    $('globalStatus').textContent =
      'Planta online resetada';
  }

  function applyDisturbance() {
    const o = state.online;

    o.disturbance = {
      dv: finite($('distV').value),
      dw: finite($('distW').value),

      until: o.time + clamp(
        finite($('distDuration').value, 1),
        .05,
        30
      )
    };
  }

  function updateDiagnostics() {
    const z = state.currentZ;
    const e = errorsOf(z);

    const f = evaluateFuzzy(
      e.e1,
      e.e2,
      state.config
    );

    state.lastFuzzy = f;

    $('diagE1').textContent = fmt(e.e1, 3);
    $('diagE2').textContent = fmt(e.e2, 3);
    $('diagW').textContent = fmt(f.omega, 3);
    $('diagV').textContent = fmt(f.velocity, 3);

    $('diagStatus').textContent = f.status;

    state.lastFires = f.fires;

    refreshRuleHighlights();
  }

  function refreshRuleHighlights() {
    const body = $('ruleTableBody');

    if (!body) return;

    const fires = state.lastFires || [];

    body.querySelectorAll('tr[data-index]').forEach((tr) => {
      const i = Number(tr.dataset.index);
      const mu = fires[i] || 0;

      tr.classList.toggle(
        'active',
        mu > 1e-4
      );

      const cell = tr.querySelector('[data-mu]');

      if (cell) {
        cell.textContent = fmt(mu, 3);
      }
    });
  }

  function persistConfig() {
    $('globalStatus').textContent =
      'Configuração alterada · salve em FML/XML para guardar';
  }

  function scheduleSave() {
    persistConfig();
  }

  function xmlEscape(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&apos;');
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function fmlId(text, fallback = 'item') {
    let id = String(text ?? '').trim();
    if (!id) id = fallback;
    id = id.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    id = id.replace(/[^A-Za-z0-9_.-]+/g, '_');
    if (!/^[A-Za-z_]/.test(id)) id = `_${id}`;
    return id || fallback;
  }

  function fmlTermNames(variable, variableId) {
    const used = new Set();
    return variable.sets.map((_, i) => {
      const label = displaySetName(variable, i).trim() || `Conjunto ${i + 1}`;
      const localId = fmlId(label, `Conjunto_${i + 1}`);
      const base = `${fmlId(variableId, 'VAR')}__${localId}`;
      let name = base;
      let suffix = 2;
      while (used.has(name)) name = `${base}_${suffix++}`;
      used.add(name);
      return name;
    });
  }

  function shapeToFml(shape, params) {
    if (shape === 'gauss') {
      return `<gaussianShape param1="${params[0]}" param2="${params[1]}"/>`;
    }
    if (shape === 'trap') {
      return `<trapezoidShape param1="${params[0]}" param2="${params[1]}" param3="${params[2]}" param4="${params[3]}"/>`;
    }
    return `<triangularShape param1="${params[0]}" param2="${params[1]}" param3="${params[2]}"/>`;
  }

  function fmlAndMethod(value) {
    if (value === 'prod') return 'PROD';
    if (value === 'eins') return 'EPROD';
    return 'MIN';
  }

  function fmlOrMethod(value) {
    if (value === 'prob') return 'PROBOR';
    if (value === 'eins') return 'ESUM';
    return 'MAX';
  }

  function fmlDefuzzifier(value) {
    if (value === 'mom') return 'MOM';
    if (value === 'som') return 'LM';
    if (value === 'lom') return 'RM';
    return 'COG';
  }

  function fromFmlAndMethod(value) {
    const v = String(value || '').toUpperCase();
    if (v === 'PROD') return 'prod';
    if (v === 'EPROD') return 'eins';
    return 'min';
  }

  function fromFmlOrMethod(value) {
    const v = String(value || '').toUpperCase();
    if (v === 'PROBOR') return 'prob';
    if (v === 'ESUM') return 'eins';
    return 'max';
  }

  function fromFmlDefuzzifier(value) {
    const v = String(value || '').toUpperCase();
    if (v === 'MOM') return 'mom';
    if (v === 'LM') return 'som';
    if (v === 'RM') return 'lom';
    return 'cg';
  }

  function validateFmlExportConfig(cfg) {
    for (const key of VAR_KEYS) {
      const v = cfg.variables[key];
      if (!v || !Array.isArray(v.sets) || v.sets.length < 1) {
        throw new Error(`A variável ${VAR_META[key].short} precisa ter pelo menos um conjunto fuzzy.`);
      }
      v.sets.forEach((set) => validateSet(set, v.shape, v.min, v.max));
    }
    if (!Array.isArray(cfg.rules) || cfg.rules.length < 1) {
      throw new Error('A base Mamdani precisa conter pelo menos uma regra para gerar um FML completo.');
    }
    cfg.rules.forEach((rule, i) => {
      if (!Array.isArray(rule) || rule.length < 4) {
        throw new Error(`A regra ${i + 1} está incompleta.`);
      }
      rule.forEach((idx, j) => {
        const key = VAR_KEYS[j];
        if (!Number.isInteger(idx) || idx < 0 || idx >= cfg.variables[key].sets.length) {
          throw new Error(`A regra ${i + 1} referencia um conjunto inexistente em ${VAR_META[key].short}.`);
        }
      });
    });
  }

  function buildFmlXml() {
    const cfg = state.config;
    validateFmlExportConfig(cfg);
    const termNames = {};
    VAR_KEYS.forEach((key) => {
      const variableId = { e1: 'EA', e2: 'EP', s1: 'VA', s2: 'VEL' }[key];
      termNames[key] = fmlTermNames(cfg.variables[key], variableId);
    });

    const metadata = {
      app: 'FuzzyLabWeb',
      schemaVersion: 3,
      standardIntent: 'IEEE 1855-2016',
      gains: cfg.gains,
      sNorm: cfg.sNorm,
      tNorm: cfg.tNorm,
      implication: cfg.implication,
      fuzzification: cfg.fuzzification,
      fuzzificationParams: cfg.fuzzificationParams,
      defuzzification: cfg.defuzzification,
      resolution: cfg.resolution,
      variableKeys: { EA: 'e1', EP: 'e2', VA: 's1', VEL: 's2' },
      setLabels: Object.fromEntries(VAR_KEYS.map((key) => [key, cfg.variables[key].sets.map((_, i) => displaySetName(cfg.variables[key], i))]))
    };

    const metaComment = JSON.stringify(metadata).replaceAll('--', '—');
    const variableInfo = [
      ['e1', 'EA', 'input', 'rad'],
      ['e2', 'EP', 'input', 'm'],
      ['s1', 'VA', 'output', 'rad/s'],
      ['s2', 'VEL', 'output', 'm/s']
    ];

    const varsXml = variableInfo.map(([key, name, type, unit]) => {
      const v = cfg.variables[key];
      const extra = type === 'output'
        ? ` accumulation="${fmlOrMethod(cfg.sNorm)}" defuzzifier="${fmlDefuzzifier(cfg.defuzzification)}" defaultValue="0"`
        : '';
      const terms = v.sets.map((set, i) =>
        `      <fuzzyTerm name="${xmlEscape(termNames[key][i])}" complement="false">\n        ${shapeToFml(v.shape, set)}\n      </fuzzyTerm>`
      ).join('\n');
      return `    <fuzzyVariable name="${name}" domainleft="${v.min}" domainright="${v.max}" scale="${xmlEscape(unit)}" type="${type}"${extra}>\n${terms}\n    </fuzzyVariable>`;
    }).join('\n');

    const rulesXml = cfg.rules.map((rule, i) => {
      const [a, b, c, d] = rule;
      return `    <rule name="R${i + 1}" connector="and" andMethod="${fmlAndMethod(cfg.tNorm)}" weight="1">\n      <antecedent>\n        <clause><variable>EA</variable><term>${xmlEscape(termNames.e1[a])}</term></clause>\n        <clause><variable>EP</variable><term>${xmlEscape(termNames.e2[b])}</term></clause>\n      </antecedent>\n      <consequent>\n        <then>\n          <clause><variable>VA</variable><term>${xmlEscape(termNames.s1[c])}</term></clause>\n          <clause><variable>VEL</variable><term>${xmlEscape(termNames.s2[d])}</term></clause>\n        </then>\n      </consequent>\n    </rule>`;
    }).join('\n');

    return `<?xml version="1.0" encoding="UTF-8"?>\n<!-- FuzzyLabMetadata: ${metaComment} -->\n<fuzzySystem xmlns="http://www.ieee1855.org" name="FuzzyLabController">\n  <knowledgeBase>\n${varsXml}\n  </knowledgeBase>\n  <mamdaniRuleBase name="RuleBase1" activationMethod="${fmlAndMethod(cfg.implication)}" andMethod="${fmlAndMethod(cfg.tNorm)}" orMethod="${fmlOrMethod(cfg.sNorm)}">\n${rulesXml}\n  </mamdaniRuleBase>\n</fuzzySystem>\n`;
  }

  function exportFml() {
    try {
      const xml = buildFmlXml();
      downloadBlob(
        new Blob([xml], { type: 'application/xml;charset=utf-8' }),
        'controlador_fuzzy.fml.xml'
      );
      $('globalStatus').textContent = 'Configuração FML/XML exportada';
    } catch (err) {
      console.error(err);
      alert(`Não foi possível exportar o FML/XML:\n${err.message}`);
      $('globalStatus').textContent = 'Controlador FML incompleto';
    }
  }

  function elementsByLocalName(root, name) {
    return Array.from(root.getElementsByTagName('*')).filter(
      (el) => el.localName?.toLowerCase() === name.toLowerCase()
    );
  }

  function firstChildByLocalName(root, name) {
    return Array.from(root.children || []).find(
      (el) => el.localName?.toLowerCase() === name.toLowerCase()
    ) || null;
  }

  function textOfChild(root, name) {
    return firstChildByLocalName(root, name)?.textContent?.trim() || '';
  }

  function parseFmlShape(term) {
    const shape = Array.from(term.children || [])[0];
    if (!shape) throw new Error('Termo FML sem função de pertinência.');
    const n = shape.localName.toLowerCase();
    const a = (...names) => {
      for (const name of names) {
        if (shape.hasAttribute(name)) return finite(shape.getAttribute(name));
      }
      return 0;
    };
    if (n.includes('gaussian')) {
      return { shape: 'gauss', params: [a('param1', 'Param1'), Math.abs(a('param2', 'Param2')) || 1e-3] };
    }
    if (n.includes('trapezoid')) {
      return { shape: 'trap', params: [a('param1', 'Param1'), a('param2', 'Param2'), a('param3', 'Param3'), a('param4', 'Param4')] };
    }
    if (n.includes('triangular')) {
      return { shape: 'tri', params: [a('param1', 'Param1'), a('param2', 'Param2'), a('param3', 'Param3')] };
    }
    throw new Error(`Função de pertinência FML não suportada: ${shape.localName}`);
  }

  function parseFmlXml(xmlText) {
    const doc = new DOMParser().parseFromString(xmlText, 'application/xml');
    const parserError = elementsByLocalName(doc, 'parsererror')[0];
    if (parserError) throw new Error('O arquivo não contém XML válido.');

    const variables = elementsByLocalName(doc, 'fuzzyVariable');
    if (!variables.length) throw new Error('Nenhuma fuzzyVariable foi encontrada no arquivo.');

    const cfg = makeEmptyConfig();
    const keyByName = { EA: 'e1', EP: 'e2', VA: 's1', VEL: 's2' };
    const nameMaps = {};

    for (const fv of variables) {
      const rawName = fv.getAttribute('name') || '';
      const key = keyByName[rawName.toUpperCase()];
      if (!key) continue;
      const v = cfg.variables[key];
      v.min = finite(fv.getAttribute('domainleft') ?? fv.getAttribute('domainLeft'), v.min);
      v.max = finite(fv.getAttribute('domainright') ?? fv.getAttribute('domainRight'), v.max);
      const terms = Array.from(fv.children || []).filter(
        (el) => el.localName?.toLowerCase() === 'fuzzyterm'
      );
      v.sets = [];
      v.setNames = [];
      nameMaps[key] = new Map();
      let commonShape = null;
      terms.forEach((term, i) => {
        const parsed = parseFmlShape(term);
        if (commonShape && commonShape !== parsed.shape) {
          throw new Error(`A variável ${rawName} mistura tipos de funções de pertinência; o laboratório usa um tipo por variável.`);
        }
        commonShape = parsed.shape;
        validateSet(parsed.params, parsed.shape, v.min, v.max);
        v.sets.push(parsed.params);
        const termName = term.getAttribute('name') || `Conjunto ${i + 1}`;
        v.setNames.push(termName.startsWith('Conjunto ') ? '' : termName);
        nameMaps[key].set(termName, i);
      });
      if (commonShape) v.shape = commonShape;
    }

    for (const key of VAR_KEYS) {
      if (!nameMaps[key]) nameMaps[key] = new Map();
    }

    const ruleBase = elementsByLocalName(doc, 'mamdaniRuleBase')[0];
    if (ruleBase) {
      cfg.tNorm = fromFmlAndMethod(ruleBase.getAttribute('andMethod'));
      cfg.sNorm = fromFmlOrMethod(ruleBase.getAttribute('orMethod'));
      cfg.implication = fromFmlAndMethod(ruleBase.getAttribute('activationMethod'));
    }
    const outputVar = variables.find((fv) => String(fv.getAttribute('type') || '').toLowerCase() === 'output');
    if (outputVar) {
      cfg.sNorm = fromFmlOrMethod(outputVar.getAttribute('accumulation') || fmlOrMethod(cfg.sNorm));
      cfg.defuzzification = fromFmlDefuzzifier(outputVar.getAttribute('defuzzifier'));
    }

    const metadataMatch = xmlText.match(/<!--\s*FuzzyLabMetadata:\s*([\s\S]*?)-->/i);
    if (metadataMatch) {
      try {
        const md = JSON.parse(metadataMatch[1].trim());
        if (md.gains) cfg.gains = { ...cfg.gains, ...md.gains };
        if (['max', 'prob', 'eins'].includes(md.sNorm)) cfg.sNorm = md.sNorm;
        if (['min', 'prod', 'eins'].includes(md.tNorm)) cfg.tNorm = md.tNorm;
        if (['min', 'prod'].includes(md.implication)) cfg.implication = md.implication;
        if (['singleton', 'gauss', 'tri'].includes(md.fuzzification)) cfg.fuzzification = md.fuzzification;
        if (md.fuzzificationParams && typeof md.fuzzificationParams === 'object') {
          cfg.fuzzificationParams = { ...cfg.fuzzificationParams, ...md.fuzzificationParams };
        }
        if (['cg', 'mom', 'som', 'lom'].includes(md.defuzzification)) cfg.defuzzification = md.defuzzification;
        if ([31, 51, 71].includes(Number(md.resolution))) cfg.resolution = Number(md.resolution);
        if (md.setLabels && typeof md.setLabels === 'object') {
          for (const key of VAR_KEYS) {
            const labels = md.setLabels[key];
            if (Array.isArray(labels) && labels.length === cfg.variables[key].sets.length) {
              cfg.variables[key].setNames = labels.map((x) => String(x ?? ''));
            }
          }
        }
      } catch (err) {
        console.warn('Metadados FuzzyLab ignorados:', err);
      }
    }

    const ruleEls = elementsByLocalName(doc, 'rule');
    cfg.rules = [];
    for (const ruleEl of ruleEls) {
      const clauses = elementsByLocalName(ruleEl, 'clause');
      const selected = {};
      for (const clause of clauses) {
        const varName = textOfChild(clause, 'variable').toUpperCase();
        const termName = textOfChild(clause, 'term');
        const key = keyByName[varName];
        if (!key) continue;
        const idx = nameMaps[key].get(termName);
        if (idx !== undefined) selected[key] = idx;
      }
      if (['e1', 'e2', 's1', 's2'].every((k) => Number.isInteger(selected[k]))) {
        cfg.rules.push([selected.e1, selected.e2, selected.s1, selected.s2]);
      }
    }
    cfg.source = 'fml-import';
    return normalizeConfig(cfg);
  }

  async function importFmlFile(file) {
    if (!file) return;
    try {
      const text = await file.text();
      state.config = parseFmlXml(text);
      state.selectedVariable = 'e1';
      renderConfig();
      $('globalStatus').textContent = `FML carregado: ${file.name}`;
    } catch (err) {
      console.error(err);
      alert(`Não foi possível carregar o FML/XML:\n${err.message}`);
      $('globalStatus').textContent = 'Falha ao carregar FML/XML';
    }
  }

  function updateVariableForm() {
    const v =
      state.config.variables[state.selectedVariable];

    $('varMin').value = v.min;
    $('varMax').value = v.max;
    $('varShape').value = v.shape;
    $('varCount').value = v.sets.length;

    $('variableButtons')
      .querySelectorAll('button')
      .forEach((b) => {
        b.classList.toggle(
          'active',
          b.dataset.var === state.selectedVariable
        );
      });

    renderMembershipParams();
    drawMembershipChart();
  }

  function renderMembershipParams() {
    const v =
      state.config.variables[state.selectedVariable];

    const shape = v.shape;

    const labels = shape === 'tri'
      ? ['a', 'b', 'c']
      : (
          shape === 'trap'
            ? ['a', 'b', 'c', 'd']
            : ['c', 'σ']
        );

    const box = $('membershipParams');

    box.innerHTML = '';

    v.sets.forEach((set, i) => {
      const row = document.createElement('div');
      row.className = 'param-row';

      const name = document.createElement('input');
      name.type = 'text';
      name.className = 'set-name-input';
      name.value = v.setNames?.[i] || '';
      name.placeholder = `Conjunto ${i + 1}`;
      name.title = 'Nome linguístico opcional do conjunto';
      name.setAttribute('aria-label', `Nome do conjunto ${i + 1}`);
      name.addEventListener('input', () => {
        if (!Array.isArray(v.setNames)) v.setNames = [];
        v.setNames[i] = name.value;
        drawMembershipChart();
        renderRuleTable();
        scheduleSave();
      });

      row.appendChild(name);

      labels.forEach((label, j) => {
        const inp = document.createElement('input');

        inp.type = 'number';
        inp.step = 'any';
        inp.value = set[j] ?? 0;

        inp.setAttribute(
          'aria-label',
          `Conjunto ${i}, parâmetro ${label}`
        );

        inp.title = label;

        inp.addEventListener('change', () => {
          set[j] = finite(inp.value, set[j]);

          validateSet(
            set,
            shape,
            v.min,
            v.max
          );

          drawMembershipChart();
          scheduleSave();
          updateDiagnostics();
          refreshSurfaces();
        });

        row.appendChild(inp);
      });

      for (
        let j = labels.length;
        j < 4;
        j++
      ) {
        const blank = document.createElement('span');
        blank.textContent = '';
        row.appendChild(blank);
      }

      box.appendChild(row);
    });
  }

  function validateSet(set, shape, min, max) {
    if (shape === 'gauss') {
      set[0] = clamp(set[0], min, max);
      set[1] = Math.max(1e-5, Math.abs(set[1]));
    } else {
      const p = shape === 'tri' ? 3 : 4;

      for (let i = 0; i < p; i++) {
        set[i] = clamp(
          finite(set[i]),
          min,
          max
        );
      }

      for (let i = 1; i < p; i++) {
        if (set[i] < set[i - 1]) {
          set[i] = set[i - 1];
        }
      }

      if (
        shape === 'tri' &&
        set[0] === set[2]
      ) {
        set[0] = Math.max(min, set[0] - 1e-4);
        set[2] = Math.min(max, set[2] + 1e-4);
      }

      if (
        shape === 'trap' &&
        set[0] === set[3]
      ) {
        set[0] = Math.max(min, set[0] - 1e-4);
        set[3] = Math.min(max, set[3] + 1e-4);
      }
    }
  }

  function drawMembershipChart() {
    const canvas = $('mfCanvas');

    const {
      ctx,
      width: w,
      height: h
    } = fitCanvas(canvas);

    ctx.clearRect(0, 0, w, h);

    ctx.fillStyle = '#1d1d1d';
    ctx.fillRect(0, 0, w, h);

    const v =
      state.config.variables[state.selectedVariable];

    const pad = {
      l: 38,
      r: 12,
      t: 16,
      b: 30
    };

    const pw = w - pad.l - pad.r;
    const ph = h - pad.t - pad.b;

    const X = (x) =>
      pad.l +
      (x - v.min) /
      (v.max - v.min) *
      pw;

    const Y = (mu) =>
      pad.t + (1 - mu) * ph;

    ctx.font = '10px sans-serif';
    ctx.fillStyle = '#999';
    ctx.strokeStyle = '#3e3e3e';

    for (let i = 0; i <= 4; i++) {
      const y = pad.t + ph * i / 4;

      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(w - pad.r, y);
      ctx.stroke();

      ctx.fillText(
        (1 - i / 4).toFixed(2),
        4,
        y + 3
      );
    }

    ctx.strokeStyle = '#777';

    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, h - pad.b);
    ctx.lineTo(w - pad.r, h - pad.b);
    ctx.stroke();

    const hue = [
      205, 145, 35, 285, 5, 185,
      65, 245, 325, 95, 15, 265
    ];

    v.sets.forEach((set, i) => {
      ctx.beginPath();

      for (let j = 0; j <= 250; j++) {
        const x =
          v.min + (v.max - v.min) * j / 250;

        const mu = membership(
          set,
          v.shape,
          x
        );

        if (j === 0) {
          ctx.moveTo(X(x), Y(mu));
        } else {
          ctx.lineTo(X(x), Y(mu));
        }
      }

      ctx.strokeStyle =
        `hsl(${hue[i % hue.length]},75%,65%)`;

      ctx.lineWidth = 2;
      ctx.stroke();

      const center = v.shape === 'gauss'
        ? set[0]
        : (
            v.shape === 'tri'
              ? set[1]
              : (set[1] + set[2]) / 2
          );

      ctx.fillStyle = ctx.strokeStyle;

      ctx.beginPath();
      ctx.arc(X(center), Y(1), 3, 0, TAU);
      ctx.fill();

      ctx.fillStyle = '#c7c7c7';

      ctx.fillText(
        displaySetName(v, i),
        X(center) + 4,
        14 + (i % 2) * 11
      );
    });

    const err = errorsOf(state.currentZ);

    const val =
      state.selectedVariable === 'e1'
        ? err.e1 * state.config.gains.e1
        : state.selectedVariable === 'e2'
          ? err.e2 * state.config.gains.e2
          : (
              state.selectedVariable === 's1'
                ? state.currentU[1] /
                  state.config.gains.omega
                : state.currentU[0] /
                  state.config.gains.velocity
            );

    if (val >= v.min && val <= v.max) {
      ctx.strokeStyle = '#fff';
      ctx.setLineDash([4, 3]);

      ctx.beginPath();
      ctx.moveTo(X(val), pad.t);
      ctx.lineTo(X(val), h - pad.b);
      ctx.stroke();

      ctx.setLineDash([]);
    }

    ctx.fillStyle = '#aaa';
    ctx.textAlign = 'center';

    ctx.fillText(
      `${META[state.selectedVariable].symbol} (${META[state.selectedVariable].unit})`,
      pad.l + pw / 2,
      h - 5
    );

    ctx.textAlign = 'left';
  }

  function drawSurface(canvas, which) {
    const {
      ctx,
      width: w,
      height: h
    } = fitCanvas(canvas);

    ctx.clearRect(0, 0, w, h);

    ctx.fillStyle = '#1e1e1e';
    ctx.fillRect(0, 0, w, h);

    const v1 = state.config.variables.e1;
    const v2 = state.config.variables.e2;

    const cols = 19;
    const rows = 15;

    const cellW = (w - 50) / cols;
    const cellH = (h - 42) / rows;

    const vals = [];

    const outMin =
      state.config.variables[
        which === 'w' ? 's1' : 's2'
      ].min;

    const outMax =
      state.config.variables[
        which === 'w' ? 's1' : 's2'
      ].max;

    let vmin = Infinity;
    let vmax = -Infinity;

    for (let j = 0; j < rows; j++) {
      const row = [];

      const e2 =
        v2.max -
        j * (v2.max - v2.min) / (rows - 1);

      for (let i = 0; i < cols; i++) {
        const e1 =
          v1.min +
          i * (v1.max - v1.min) / (cols - 1);

        const f = evaluateFuzzy(
          e1,
          e2,
          state.config,
          21
        );

        const value =
          which === 'w'
            ? f.omega
            : f.velocity;

        row.push(value);

        vmin = Math.min(vmin, value);
        vmax = Math.max(vmax, value);
      }

      vals.push(row);
    }

    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const norm = clamp(
          (vals[j][i] - outMin) /
          Math.max(EPS, outMax - outMin),
          0,
          1
        );

        const hue = 215 - norm * 170;

        ctx.fillStyle =
          `hsl(${hue},55%,${24 + norm * 28}%)`;

        ctx.fillRect(
          36 + i * cellW,
          10 + j * cellH,
          cellW + .5,
          cellH + .5
        );
      }
    }

    ctx.strokeStyle = '#666';

    ctx.strokeRect(
      36,
      10,
      cols * cellW,
      rows * cellH
    );

    ctx.fillStyle = '#aaa';
    ctx.font = '10px sans-serif';

    ctx.fillText(
      'EA →',
      w / 2 - 12,
      h - 4
    );

    ctx.save();

    ctx.translate(11, h / 2);
    ctx.rotate(-Math.PI / 2);

    ctx.textAlign = 'center';
    ctx.fillText('EP ↑', 0, 0);

    ctx.restore();

    ctx.fillStyle = '#ddd';

    ctx.fillText(
      `${which === 'w' ? 'ω' : 'v'} ∈ [${fmt(vmin, 1)}, ${fmt(vmax, 1)}]`,
      w - 110,
      h - 5
    );
  }

  function refreshSurfaces() {
    drawSurface($('surfaceW'), 'w');
    drawSurface($('surfaceV'), 'v');
  }

  function renderRuleTable() {
    const body = $('ruleTableBody');

    body.innerHTML = '';

    const options = (key, selected) => {
      const n = state.config.variables[key].sets.length;

      const variable = state.config.variables[key];
      return Array.from(
        { length: n },
        (_, i) =>
          `<option value="${i}" ${
            i === selected ? 'selected' : ''
          }>${escapeHtml(displaySetName(variable, i))}</option>`
      ).join('');
    };

    state.config.rules.forEach((rule, index) => {
      const tr = document.createElement('tr');

      tr.dataset.index = index;

      tr.innerHTML = `
        <td>${index + 1}</td>
        <td><select data-col="0">${options('e1', rule[0])}</select></td>
        <td><select data-col="1">${options('e2', rule[1])}</select></td>
        <td><select data-col="2">${options('s1', rule[2])}</select></td>
        <td><select data-col="3">${options('s2', rule[3])}</select></td>
        <td data-mu>0.000</td>
        <td><button class="btn danger small" title="Remover regra">×</button></td>
      `;

      tr.querySelectorAll('select').forEach((sel) => {
        sel.addEventListener('change', () => {
          rule[Number(sel.dataset.col)] =
            Number(sel.value);

          scheduleSave();
          updateDiagnostics();
          refreshSurfaces();
        });
      });

      tr.querySelector('button').addEventListener(
        'click',
        () => {
          state.config.rules.splice(index, 1);

          renderRuleTable();
          scheduleSave();
          updateDiagnostics();
          refreshSurfaces();
        }
      );

      body.appendChild(tr);
    });

    $('ruleStatus').textContent =
      `${state.config.rules.length} regra(s)`;

    $('ruleHint').textContent =
      state.config.rules.length
        ? 'Os seletores usam os nomes linguísticos dos conjuntos (ou a numeração automática). Regras com μ > 0 são realçadas durante a simulação.'
        : 'Base vazia. Gere os conjuntos de pertinência e adicione regras. Sem regras, a inferência retorna comando neutro.';

    refreshRuleHighlights();
  }

    function refreshConfigOptions() {
    $('gainE1').value = state.config.gains.e1;
    $('gainE2').value = state.config.gains.e2;
    $('gainW').value = state.config.gains.omega;
    $('gainV').value = state.config.gains.velocity;

    $('sNorm').value = state.config.sNorm;
    $('tNorm').value = state.config.tNorm;
    $('implication').value = state.config.implication;
    $('fuzzification').value = state.config.fuzzification;
    $('fuzzGaussSigma').value = state.config.fuzzificationParams.gaussSigma;
    $('fuzzTriHalfWidth').value = state.config.fuzzificationParams.triHalfWidth;
    $('fuzzSamples').value = state.config.fuzzificationParams.samples;
    $('defuzzification').value =
      state.config.defuzzification;

    $('centroidResolution').value =
      String(state.config.resolution);
  }

  function renderConfig() {
    updateVariableForm();
    refreshConfigOptions();
    renderRuleTable();
    updateDiagnostics();
    refreshSurfaces();
  }

  function applyVariableSettings() {
    const v =
      state.config.variables[state.selectedVariable];

    const min = finite($('varMin').value, v.min);
    const max = finite($('varMax').value, v.max);

    if (!(max > min)) {
      alert(
        'O limite superior precisa ser maior que o inferior.'
      );

      updateVariableForm();
      return;
    }

    v.min = min;
    v.max = max;

    if (v.sets.length) {
      v.sets.forEach((p) =>
        validateSet(p, v.shape, min, max)
      );
    }

    scheduleSave();
    drawMembershipChart();
    renderMembershipParams();
    updateDiagnostics();
    refreshSurfaces();
  }

  function changeShape() {
    const v =
      state.config.variables[state.selectedVariable];

    const shape = $('varShape').value;

    const count = Math.max(
      1,
      Math.min(
        12,
        Number($('varCount').value) || 5
      )
    );

    v.shape = shape;

    v.sets = makeSets(
      shape,
      v.min,
      v.max,
      count
    );
    v.setNames = Array(count).fill('');

    renderMembershipParams();
    drawMembershipChart();
    renderRuleTable();

    scheduleSave();
    updateDiagnostics();
    refreshSurfaces();
  }

  function addSelectedRule() {
    const keys = ['e1', 'e2', 's1', 's2'];

    if (
      keys.some(
        (k) => state.config.variables[k].sets.length === 0
      )
    ) {
      alert(
        'Defina ao menos um conjunto em cada variável antes de adicionar regras.'
      );

      return;
    }

    const idx = keys.map((k) => {
      const v = state.config.variables[k];

      const val =
        k === 'e1'
          ? errorsOf(state.currentZ).e1
          : k === 'e2'
            ? errorsOf(state.currentZ).e2
            : k === 's1'
              ? state.currentU[1]
              : state.currentU[0];

      const mu = memberships(val, v);

      return mu.indexOf(Math.max(...mu));
    });

    state.config.rules.push(idx);

    renderRuleTable();
    scheduleSave();
    updateDiagnostics();
    refreshSurfaces();
  }

  function addAllRules() {
    const a = state.config.variables.e1.sets.length;
    const b = state.config.variables.e2.sets.length;
    const c = state.config.variables.s1.sets.length;
    const d = state.config.variables.s2.sets.length;

    if (!a || !b || !c || !d) {
      alert(
        'Gere os conjuntos de pertinência das quatro variáveis primeiro.'
      );

      return;
    }

    const next = [];

    for (let i = 0; i < a; i++) {
      for (let j = 0; j < b; j++) {
        const k = Math.round(
          i * Math.max(0, c - 1) /
          Math.max(1, a - 1)
        );

        const l = Math.round(
          j * Math.max(0, d - 1) /
          Math.max(1, b - 1)
        );

        next.push([i, j, k, l]);
      }
    }

    state.config.rules = next;

    renderRuleTable();
    scheduleSave();
    updateDiagnostics();
    refreshSurfaces();
  }

  function clearController() {
    state.config = makeEmptyConfig();
    state.selectedVariable = 'e1';
    state.lastFires = [];
    renderConfig();
    $('batchControlMode').value = 'fuzzy';
    $('onlineControlMode').value = 'fuzzy';
    $('diagStatus').textContent =
      'Controlador vazio. Gere pertinências e regras para ativar a inferência.';
    $('globalStatus').textContent = 'Controlador limpo';
  }

  function membershipCanvasPointer(ev) {
    const canvas = $('mfCanvas');

    const v =
      state.config.variables[state.selectedVariable];

    const rect = canvas.getBoundingClientRect();

    const x =
      v.min +
      clamp(
        (ev.clientX - rect.left - 38) /
        Math.max(1, rect.width - 50),
        0,
        1
      ) *
      (v.max - v.min);

    if (!state.draggingMembership) {
      state.draggingMembership = true;
    }

    const params = v.sets;

    if (!params.length) return;

    let nearest = 0;
    let distance = Infinity;

    params.forEach((set, i) => {
      const c =
        v.shape === 'gauss'
          ? set[0]
          : v.shape === 'tri'
            ? set[1]
            : (set[1] + set[2]) / 2;

      const d = Math.abs(c - x);

      if (d < distance) {
        distance = d;
        nearest = i;
      }
    });

    const set = params[nearest];

    if (v.shape === 'gauss') {
      set[0] = x;
    } else if (v.shape === 'tri') {
      const left = set[1] - set[0];
      const right = set[2] - set[1];

      set[1] = x;

      set[0] = clamp(
        x - left,
        v.min,
        x
      );

      set[2] = clamp(
        x + right,
        x,
        v.max
      );
    } else {
      const left = set[1] - set[0];
      const right = set[3] - set[2];

      const half = Math.max(
        .02 * (v.max - v.min),
        (set[2] - set[1]) / 2
      );

      set[1] = clamp(
        x - half,
        v.min,
        x
      );

      set[2] = clamp(
        x + half,
        x,
        v.max
      );

      set[0] = clamp(
        set[1] - left,
        v.min,
        set[1]
      );

      set[3] = clamp(
        set[2] + right,
        set[2],
        v.max
      );
    }

    validateSet(
      set,
      v.shape,
      v.min,
      v.max
    );

    renderMembershipParams();
    drawMembershipChart();

    scheduleSave();
    updateDiagnostics();
  }

  function activateTab(tab) {
    document.querySelectorAll('nav button').forEach((b) => {
      b.classList.toggle(
        'active',
        b.dataset.tab === tab
      );
    });

    document
      .querySelectorAll('main > section.tab')
      .forEach((s) => s.classList.remove('active'));

    $('offlineControls').classList.toggle(
      'hidden',
      tab !== 'offline'
    );

    $('onlineControls').classList.toggle(
      'hidden',
      tab !== 'online'
    );

    $('offlinePlots').classList.toggle(
      'hidden',
      tab !== 'offline'
    );

    $('onlinePlots').classList.toggle(
      'hidden',
      tab !== 'online'
    );

    $('simWorkspace').classList.toggle(
      'active',
      tab === 'offline' || tab === 'online'
    );

    if (tab !== 'challenge' && state.challenge.running) {
      pauseChallenge();
    }

    if (tab === 'challenge') {
      $('challenge').classList.add('active');
      requestAnimationFrame(() => {
        ['simple','medium','hard'].forEach(drawChallengePreview);
        drawChallenge();
      });
    } else if (tab === 'config') {
      $('config').classList.add('active');
      renderConfig();
    } else if (tab === 'theory') {
      $('theory').classList.add('active');
    } else if (tab === 'offline' || tab === 'online') {
      $('simWorkspace').classList.add('active');

      if (tab === 'online') {
        $('workspaceTitle').textContent =
          'Simulação em tempo real / online';

        $('workspaceSub').textContent =
          'Integração contínua com relógio monotônico, referência ao vivo e strip charts.';

        state.online.refMode =
          $('onlineRefMode').value;

        state.online.controlMode =
          $('onlineControlMode').value;

        ensurePlotly().then(() => updateLivePlots());
      } else {
        $('workspaceTitle').textContent =
          'Simulação offline / batch';

        $('workspaceSub').textContent =
          'Integração RK4, histórico completo e replay temporal da trajetória.';

        if (state.batch.records.length) {
          drawWorld(
            state.currentZ,
            state.currentTime,
            $('batchRefMode').value
          );

          drawOfflinePlots(state.batch.records);
        }
      }
    }

    requestAnimationFrame(() => {
      if (tab === 'offline' || tab === 'online') {
        drawWorld(
          state.currentZ,
          state.currentTime,
          tab === 'online'
            ? state.online.refMode
            : $('batchRefMode').value
        );
      }
      if (tab === 'challenge') drawChallenge();

      if (tab === 'config') {
        drawMembershipChart();
        refreshSurfaces();
      }
    });
  }

  function loadMathJax() {
    if (
      window.MathJax &&
      window.MathJax.typesetPromise
    ) {
      window.MathJax.typesetPromise();

      return Promise.resolve(true);
    }

    if (state.mathjaxPromise) {
      return state.mathjaxPromise;
    }

    window.MathJax = {
      tex: {
        inlineMath: [
          ['\\(', '\\)']
        ],
        displayMath: [
          ['\\[', '\\]']
        ]
      },

      options: {
        skipHtmlTags: [
          'script',
          'noscript',
          'style',
          'textarea',
          'pre',
          'code'
        ]
      }
    };

    state.mathjaxPromise = new Promise((resolve) => {
      const script = document.createElement('script');

      script.src =
        'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js';

      script.async = true;

      script.onload = () => {
        if (window.MathJax.typesetPromise) {
          window.MathJax
            .typesetPromise()
            .then(() => resolve(true));
        } else {
          resolve(false);
        }
      };

      script.onerror = () => {
        $('globalStatus').textContent =
          'MathJax indisponível sem conexão; equações permanecem em TeX.';

        resolve(false);
      };

      document.head.appendChild(script);
    });

    return state.mathjaxPromise;
  }

  function canvasToWorld(clientX, clientY) {
    const rect = $('worldCanvas').getBoundingClientRect();

    const scale = rect.height / 10;

    return [
      (clientX - rect.left - rect.width / 2) / scale,
      (rect.height / 2 - (clientY - rect.top)) / scale
    ];
  }

  function setLiveReference(clientX, clientY) {
    const [wx, wy] = canvasToWorld(
      clientX,
      clientY
    );
    const [x, y] = clampPointToTrack(wx, wy);

    state.online.z[3] = x;
    state.online.z[4] = y;

    $('onlineRefX').value = x.toFixed(3);
    $('onlineRefY').value = y.toFixed(3);

    $('onlineRefRange').value = String(
      clamp(x, -5, 7)
    );

    if (!state.online.running) {
      state.currentZ = state.online.z.slice();

      drawWorld(
        state.online.z,
        state.online.time,
        state.online.refMode
      );

      updateHUD(
        state.online.z,
        state.online.time,
        state.online.lastControl
      );
    }
  }

  function initEvents() {
    document
      .querySelectorAll('nav button')
      .forEach((b) => {
        b.addEventListener(
          'click',
          () => activateTab(b.dataset.tab)
        );
      });

    document.querySelectorAll('.track-card').forEach((card) => {
      card.addEventListener('click', () => {
        if (state.challenge.running) return;
        selectChallengeTrack(card.dataset.track);
      });
    });

    $('challengeSpeed').addEventListener('input', (e) => {
      const def = state.challenge.geometry?.def || CHALLENGE_TRACKS[state.challenge.selected];
      state.challenge.speed = clamp(finite(e.target.value, def.defaultSpeed), .4, def.maxSpeed);
      $('challengeSpeedValue').textContent = `${state.challenge.speed.toFixed(1)} m/s`;
      if (!state.challenge.running && !state.challenge.controller) updateChallengeHud();
    });

    $('challengeLookahead').addEventListener('change', (e) => {
      state.challenge.lookahead = clamp(finite(e.target.value, 1.2), .4, 3);
      e.target.value = state.challenge.lookahead;
    });

    $('challengeStart').addEventListener('click', startChallenge);
    $('challengePause').addEventListener('click', pauseChallenge);
    $('challengeReset').addEventListener('click', () => {
      resetChallengeState();
      $('challengeResultText').textContent = 'Nova tentativa pronta. O controlador será congelado ao iniciar.';
      $('globalStatus').textContent = 'Desafio pronto para nova tentativa.';
    });

    $('runBatch').addEventListener(
      'click',
      runBatch
    );

    $('exportOfflinePng').addEventListener(
      'click',
      exportOfflinePlotsPng
    );

    $('resetBatch').addEventListener('click', () => {
      stopReplay();

      state.batch.records = [];
      $('exportOfflinePng').disabled = true;

      state.currentZ = [
        0, 0, 0, 2.62, -.02
      ];

      state.currentTime = 0;
      state.currentU = [0, 0];

      $('batchX0').value = 0;
      $('batchY0').value = 0;
      $('batchTheta0').value = 0;

      $('batchRefX').value = 2.62;
      $('batchRefY').value = -.02;

      $('batchTf').value = 20;
      $('batchDt').value = '0.0166667';

      $('batchRefMode').value = 'manual';

      $('replayScrubber').value = 0;
      $('replayScrubber').max = 0;
      $('replayScrubber').disabled = true;

      $('replayPlay').disabled = true;
      $('replayPause').disabled = true;

      $('batchStatus').textContent =
        'Nenhuma simulação calculada';

      drawWorld(
        state.currentZ,
        0,
        'manual'
      );

      updateHUD(
        state.currentZ,
        0,
        [0, 0]
      );
    });

    $('replayScrubber').addEventListener(
      'input',
      (e) => {
        stopReplay();
        updateReplayAt(Number(e.target.value));
      }
    );

    $('replayPlay').addEventListener(
      'click',
      playReplay
    );

    $('replayPause').addEventListener(
      'click',
      stopReplay
    );

    $('onlineStart').addEventListener(
      'click',
      () => {
        state.online.refMode =
          $('onlineRefMode').value;

        state.online.controlMode =
          $('onlineControlMode').value;

        startOnline();
      }
    );

    $('onlinePause').addEventListener(
      'click',
      pauseOnline
    );

    $('onlineReset').addEventListener(
      'click',
      resetOnline
    );

    $('applyDisturbance').addEventListener(
      'click',
      applyDisturbance
    );

    $('onlineRefMode').addEventListener(
      'change',
      (e) => {
        state.online.refMode = e.target.value;
        state.online.refManualTarget = [0, 0];
        state.online.refManualActual = [0, 0];
      }
    );

    $('onlineControlMode').addEventListener(
      'change',
      (e) => {
        state.online.controlMode = e.target.value;
        state.online.manualTarget = [0, 0];
        state.online.manualActual = [0, 0];
      }
    );

    $('onlineRefX').addEventListener(
      'change',
      (e) => {
        state.online.z[3] = finite(e.target.value);
      }
    );

    $('onlineRefY').addEventListener(
      'change',
      (e) => {
        state.online.z[4] = finite(e.target.value);
      }
    );

    $('onlineRefRange').addEventListener(
      'input',
      (e) => {
        state.online.z[3] = finite(e.target.value);

        $('onlineRefX').value =
          state.online.z[3].toFixed(3);
      }
    );

    $('onlineDt').addEventListener(
      'change',
      (e) => {
        state.online.dt = clamp(
          finite(e.target.value, 1 / 60),
          .002,
          .05
        );
      }
    );

    $('worldCanvas').addEventListener(
      'pointerdown',
      (e) => {
        if (
          document.querySelector('nav button.active')
            ?.dataset.tab !== 'online' ||
          state.online.refMode !== 'manual'
        ) {
          return;
        }

        state.draggingReference = true;

        $('worldCanvas').setPointerCapture?.(
          e.pointerId
        );

        setLiveReference(
          e.clientX,
          e.clientY
        );
      }
    );

    $('worldCanvas').addEventListener(
      'pointermove',
      (e) => {
        if (state.draggingReference) {
          setLiveReference(
            e.clientX,
            e.clientY
          );
        }
      }
    );

    $('worldCanvas').addEventListener(
      'pointerup',
      () => {
        state.draggingReference = false;
      }
    );

    $('worldCanvas').addEventListener(
      'pointercancel',
      () => {
        state.draggingReference = false;
      }
    );

    const manualButtons = [
      ['manualLeft', [0, 2]],
      ['manualForward', [5, 0]],
      ['manualRight', [0, -2]]
    ];

    manualButtons.forEach(([id, command]) => {
      const el = $(id);

      const down = (e) => {
        e.preventDefault();

        state.online.manualTarget =
          command.slice();
      };

      const up = () => {
        state.online.manualTarget = [0, 0];
      };

      el.addEventListener('pointerdown', down);
      el.addEventListener('pointerup', up);
      el.addEventListener('pointerleave', up);
      el.addEventListener('pointercancel', up);
    });

    $('manualStop').addEventListener(
      'click',
      () => {
        state.online.manualTarget = [0, 0];
        state.online.manualActual = [0, 0];
      }
    );

    function keyboardManualRecipients() {
      return {
        plant: state.online.controlMode === 'manual',
        reference: state.online.refMode === 'manual'
      };
    }

    function setKeyboardAxis(axis, value) {
      const targets = keyboardManualRecipients();
      if (targets.plant) state.online.manualTarget[axis] = value;
      if (targets.reference) state.online.refManualTarget[axis] = value;
      return targets.plant || targets.reference;
    }

    window.addEventListener('keydown', (e) => {
      if (
        document.querySelector('nav button.active')?.dataset.tab !== 'online'
      ) {
        return;
      }

      const tag = e.target?.tagName?.toLowerCase();
      if (
        ['input', 'select', 'textarea', 'button'].includes(tag) ||
        e.target?.isContentEditable
      ) {
        return;
      }

      let handled = false;
      if (e.key === 'ArrowUp') handled = setKeyboardAxis(0, 5);
      else if (e.key === 'ArrowDown') handled = setKeyboardAxis(0, -5);
      else if (e.key === 'ArrowLeft') handled = setKeyboardAxis(1, 2);
      else if (e.key === 'ArrowRight') handled = setKeyboardAxis(1, -2);

      if (handled) e.preventDefault();
    });

    window.addEventListener('keyup', (e) => {
      if (['ArrowUp', 'ArrowDown'].includes(e.key)) {
        setKeyboardAxis(0, 0);
      }
      if (['ArrowLeft', 'ArrowRight'].includes(e.key)) {
        setKeyboardAxis(1, 0);
      }
    });

    window.addEventListener('blur', () => {
      state.online.manualTarget = [0, 0];
      state.online.refManualTarget = [0, 0];
    });

    $('variableButtons')
      .querySelectorAll('button')
      .forEach((b) => {
        b.addEventListener('click', () => {
          state.selectedVariable = b.dataset.var;
          updateVariableForm();
        });
      });

    $('applyUniverse').addEventListener(
      'click',
      applyVariableSettings
    );

    $('regenerateMfs').addEventListener(
      'click',
      () => {
        const v =
          state.config.variables[state.selectedVariable];

        applyVariableSettings();

        const count = clamp(
          Math.round(finite($('varCount').value, 5)),
          1,
          12
        );

        v.sets = makeSets(
          v.shape,
          v.min,
          v.max,
          count
        );
        v.setNames = Array(count).fill('');

        renderMembershipParams();
        drawMembershipChart();
        renderRuleTable();

        scheduleSave();
        updateDiagnostics();
        refreshSurfaces();
      }
    );

    $('varShape').addEventListener(
      'change',
      changeShape
    );

    $('varCount').addEventListener(
      'change',
      changeShape
    );

    $('mfCanvas').addEventListener(
      'pointerdown',
      (e) => {
        state.draggingMembership = false;

        $('mfCanvas').setPointerCapture?.(
          e.pointerId
        );

        membershipCanvasPointer(e);
      }
    );

    $('mfCanvas').addEventListener(
      'pointermove',
      (e) => {
        if (
          e.buttons &&
          state.draggingMembership
        ) {
          membershipCanvasPointer(e);
        }
      }
    );

    $('mfCanvas').addEventListener(
      'pointerup',
      () => {
        state.draggingMembership = false;
      }
    );

    $('mfCanvas').addEventListener(
      'pointercancel',
      () => {
        state.draggingMembership = false;
      }
    );

    $('addRule').addEventListener(
      'click',
      addSelectedRule
    );

    $('addAllRules').addEventListener(
      'click',
      addAllRules
    );

    $('clearRules').addEventListener(
      'click',
      () => {
        state.config.rules = [];

        renderRuleTable();
        scheduleSave();
        updateDiagnostics();
        refreshSurfaces();
      }
    );

    $('saveConfig').addEventListener(
      'click',
      exportFml
    );

    $('loadConfigFile').addEventListener('click', () => {
      $('configFileInput').click();
    });

    $('configFileInput').addEventListener('change', (e) => {
      importFmlFile(e.target.files?.[0]);
      e.target.value = '';
    });

    $('clearController').addEventListener(
      'click',
      clearController
    );

    $('refreshSurface').addEventListener(
      'click',
      refreshSurfaces
    );

    [
      ['gainE1', 'e1'],
      ['gainE2', 'e2'],
      ['gainW', 'omega'],
      ['gainV', 'velocity']
    ].forEach(([id, key]) => {
      $(id).addEventListener(
        'change',
        (e) => {
          state.config.gains[key] = clamp(
            finite(e.target.value, 1),
            0.01,
            100
          );

          e.target.value =
            state.config.gains[key];

          scheduleSave();
          updateDiagnostics();
          refreshSurfaces();
        }
      );
    });

    [
      ['sNorm', 'sNorm'],
      ['tNorm', 'tNorm'],
      ['implication', 'implication'],
      ['fuzzification', 'fuzzification'],
      ['defuzzification', 'defuzzification']
    ].forEach(([id, key]) => {
      $(id).addEventListener(
        'change',
        (e) => {
          state.config[key] = e.target.value;

          scheduleSave();
          updateDiagnostics();
          refreshSurfaces();
        }
      );
    });

    [
      ['fuzzGaussSigma', 'gaussSigma', 1e-4, 10],
      ['fuzzTriHalfWidth', 'triHalfWidth', 1e-4, 10]
    ].forEach(([id, key, lo, hi]) => {
      $(id).addEventListener('change', (e) => {
        state.config.fuzzificationParams[key] = clamp(
          finite(e.target.value, 0.1),
          lo,
          hi
        );
        e.target.value = state.config.fuzzificationParams[key];
        scheduleSave();
        updateDiagnostics();
        refreshSurfaces();
      });
    });

    $('fuzzSamples').addEventListener('change', (e) => {
      state.config.fuzzificationParams.samples = clamp(
        Math.round(finite(e.target.value, 11)),
        3,
        101
      );
      e.target.value = state.config.fuzzificationParams.samples;
      scheduleSave();
      updateDiagnostics();
      refreshSurfaces();
    });

    $('centroidResolution').addEventListener(
      'change',
      (e) => {
        state.config.resolution =
          Number(e.target.value);

        scheduleSave();
        updateDiagnostics();
      }
    );

    window.addEventListener('resize', () => {
      drawWorld(
        state.currentZ,
        state.currentTime,
        state.online.refMode
      );

      if ($('config').classList.contains('active')) {
        drawMembershipChart();
        refreshSurfaces();
      }

      if (state.batch.records.length) {
        drawOfflinePlots(state.batch.records);
      }

      if (state.online.history.length) {
        updateLivePlots();
      }

      ['simple','medium','hard'].forEach(drawChallengePreview);
      drawChallenge();
    });
  }

  function initialize() {
    VAR_KEYS.forEach((key) => {
      state.config.variables[key].sets.forEach((p) => {
        validateSet(
          p,
          state.config.variables[key].shape,
          state.config.variables[key].min,
          state.config.variables[key].max
        );
      });
    });

    $('ruleStatus').textContent =
      `${state.config.rules.length} regras`;


    $('batchRefX').value = '2.62';
    $('batchRefY').value = '-0.02';

    $('onlineRefX').value = '2.62';
    $('onlineRefY').value = '-0.02';

    state.online.z = [
      0, 0, 0, 2.62, -0.02
    ];

    state.currentZ = state.online.z.slice();

    initEvents();
    initChallengeUi();

    updateVariableForm();
    renderRuleTable();
    updateDiagnostics();

    Promise.all(
      Object.entries(SPRITE_PATHS).map(
        ([key, path]) => loadImage(key, path)
      )
    ).then(() => {
      drawWorld(
        state.currentZ,
        0,
        'manual'
      );

      $('globalStatus').textContent =
        'Sprites carregados · pronto para simular';
    });

    drawWorld(
      state.currentZ,
      0,
      'manual'
    );

    updateHUD(
      state.currentZ,
      0,
      [0, 0]
    );

    activateTab('theory');
  }

  // API opcional para testes numéricos
  // no console do navegador.
  window.FuzzyLab = {
    trimf,
    trapmf,
    gaussmf,

    evaluate: (e1, e2) =>
      evaluateFuzzy(e1, e2),

    rk4: (z, t, h, u, mode = 'manual') =>
      rk4(z, t, h, u, mode),

    exportXml: () => buildFmlXml(),
    importXml: (text) => {
      state.config = parseFmlXml(text);
      state.selectedVariable = 'e1';
      renderConfig();
      return state.config;
    },

    get config() {
      return state.config;
    }
  };

  initialize();

})();

