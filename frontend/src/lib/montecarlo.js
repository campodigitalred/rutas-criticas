/**
 * Simulación Monte Carlo — espejo en JavaScript del núcleo Python
 * (backend/app/simulation/montecarlo.py). Permite el análisis de riesgo en el
 * cliente y sin conexión.
 *
 * Nota: el generador de números aleatorios NO es idéntico al de Python
 * (`random`), por lo que las muestras exactas difieren, pero la distribución
 * (media, percentiles, índice de criticidad) converge a los mismos valores. La
 * lógica de muestreo Beta-PERT y el uso del motor CPM son equivalentes.
 */
import { computeCPM } from "./cpm.js";

/* --------------------------- PRNG con semilla ----------------------------- */
/** mulberry32: PRNG determinista y reproducible en [0, 1). */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Muestra normal estándar (Box-Muller). */
function gauss(rng) {
  let u = 0;
  let v = 0;
  while (u === 0) u = rng();
  while (v === 0) v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** Muestra Gamma(shape, 1) — Marsaglia & Tsang. */
function randGamma(rng, shape) {
  if (shape < 1) {
    const u = rng();
    return randGamma(rng, shape + 1) * Math.pow(u, 1 / shape);
  }
  const d = shape - 1 / 3;
  const c = 1 / Math.sqrt(9 * d);
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let x;
    let v;
    do {
      x = gauss(rng);
      v = 1 + c * x;
    } while (v <= 0);
    v = v * v * v;
    const u = rng();
    if (u < 1 - 0.0331 * x * x * x * x) return d * v;
    if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
  }
}

/** Muestra Beta(a, b). */
function randBeta(rng, a, b) {
  const x = randGamma(rng, a);
  const y = randGamma(rng, b);
  return x / (x + y);
}

/** Muestra Beta-PERT en [o, p] con moda ~ m. */
export function samplePert(rng, o, m, p, lam = 4) {
  if (p <= o) return o;
  const mode = Math.min(Math.max(m, o), p);
  const alpha = 1 + (lam * (mode - o)) / (p - o);
  const beta = 1 + (lam * (p - mode)) / (p - o);
  return o + randBeta(rng, alpha, beta) * (p - o);
}

const expected = (t) =>
  t.optimistic != null && t.most_likely != null && t.pessimistic != null
    ? (t.optimistic + 4 * t.most_likely + t.pessimistic) / 6
    : t.duration ?? 0;

const hasSpread = (t) =>
  t.optimistic != null &&
  t.most_likely != null &&
  t.pessimistic != null &&
  t.pessimistic > t.optimistic;

function percentile(sorted, q) {
  if (!sorted.length) return 0;
  if (sorted.length === 1) return sorted[0];
  const rank = (q / 100) * (sorted.length - 1);
  const lo = Math.floor(rank);
  const hi = Math.ceil(rank);
  if (lo === hi) return sorted[lo];
  return sorted[lo] * (1 - (rank - lo)) + sorted[hi] * (rank - lo);
}

/**
 * Ejecuta la simulación Monte Carlo.
 * @param {Array} tasks   [{id, duration, optimistic?, most_likely?, pessimistic?, cost?}]
 * @param {Array} deps    [{predecessor, successor, dep_type?, lag?}]
 * @param {object} opts   { iterations, seed, targetDuration, costPerDayDelay, histogramBins }
 */
export function runMonteCarlo(tasks, deps = [], opts = {}) {
  const {
    iterations = 2000,
    seed = Math.floor(Math.random() * 1e9),
    targetDuration = null,
    costPerDayDelay = 0,
    histogramBins = 20,
  } = opts;

  const rng = mulberry32(seed);
  const baseline = computeCPM(
    tasks.map((t) => ({ id: t.id, duration: expected(t) })),
    deps
  );
  const baseCost = tasks.reduce((a, t) => a + (t.cost ?? 0), 0);

  const durations = [];
  const costs = [];
  const critCounts = Object.fromEntries(tasks.map((t) => [t.id, 0]));

  for (let i = 0; i < iterations; i++) {
    const sampled = tasks.map((t) => ({
      id: t.id,
      duration: hasSpread(t)
        ? samplePert(rng, t.optimistic, t.most_likely, t.pessimistic)
        : expected(t),
    }));
    const r = computeCPM(sampled, deps);
    durations.push(r.project_duration);
    r.critical_path.forEach((id) => (critCounts[id] += 1));
    if (costPerDayDelay || baseCost) {
      const delay = Math.max(0, r.project_duration - baseline.project_duration);
      costs.push(baseCost + delay * costPerDayDelay);
    }
  }

  const sorted = [...durations].sort((a, b) => a - b);
  const n = durations.length;
  const mean = durations.reduce((a, d) => a + d, 0) / n;
  const variance = durations.reduce((a, d) => a + (d - mean) ** 2, 0) / n;
  const round = (x) => Math.round(x * 10000) / 10000;

  const percentiles = {};
  [10, 25, 50, 80, 90, 95].forEach((q) => (percentiles[`p${q}`] = round(percentile(sorted, q))));

  const probability_on_time =
    targetDuration != null
      ? round(durations.filter((d) => d <= targetDuration + 1e-9).length / n)
      : null;

  const criticality_index = {};
  Object.entries(critCounts).forEach(([id, c]) => (criticality_index[id] = round(c / n)));

  let expected_cost = null;
  let cost_p80 = null;
  if (costs.length) {
    expected_cost = Math.round((costs.reduce((a, c) => a + c, 0) / costs.length) * 100) / 100;
    cost_p80 = Math.round(percentile([...costs].sort((a, b) => a - b), 80) * 100) / 100;
  }

  return {
    iterations,
    seed,
    baseline_duration: round(baseline.project_duration),
    mean: round(mean),
    std_dev: round(Math.sqrt(variance)),
    min: round(sorted[0]),
    max: round(sorted[n - 1]),
    percentiles,
    probability_on_time,
    target_duration: targetDuration,
    criticality_index,
    histogram: buildHistogram(sorted, histogramBins),
    expected_cost,
    cost_p80,
  };
}

function buildHistogram(sorted, bins) {
  const lo = sorted[0];
  const hi = sorted[sorted.length - 1];
  if (hi <= lo) return [{ start: lo, end: hi, count: sorted.length }];
  const width = (hi - lo) / bins;
  const counts = new Array(bins).fill(0);
  sorted.forEach((v) => {
    const idx = Math.min(Math.floor((v - lo) / width), bins - 1);
    counts[idx] += 1;
  });
  return counts.map((count, i) => ({
    start: Math.round((lo + i * width) * 100) / 100,
    end: Math.round((lo + (i + 1) * width) * 100) / 100,
    count,
  }));
}
