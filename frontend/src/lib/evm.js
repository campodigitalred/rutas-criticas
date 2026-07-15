/**
 * Valor Ganado (EVM) — espejo en JavaScript del núcleo Python
 * (backend/app/reporting/evm.py). Alimenta el dashboard de control con
 * recálculo en el cliente / offline. Determinista: paridad exacta con el backend.
 */
import { computeCPM } from "./cpm.js";

const r2 = (x) => (x == null ? x : Math.round(x * 100) / 100);
const r4 = (x) => (x == null ? x : Math.round(x * 10000) / 10000);

function plannedFraction(es, ef, day) {
  const dur = ef - es;
  if (dur <= 0) return day >= ef ? 1 : 0;
  return Math.max(0, Math.min(1, (day - es) / dur));
}

export const EVM_HEALTH_META = {
  not_started: { label: "Sin iniciar", color: "var(--cc-gray-500)" },
  in_progress: { label: "En progreso", color: "var(--cc-blue-600)" },
  on_track: { label: "En control", color: "var(--cc-green-600)" },
  at_risk: { label: "En riesgo", color: "var(--cc-slack)" },
  behind: { label: "Desviado", color: "var(--cc-critical)" },
  done: { label: "Completado", color: "var(--cc-green-600)" },
};

/**
 * @param {Array} tasks [{id, duration, planned_cost, progress_pct, actual_cost}]
 * @param {Array} deps  [{predecessor, successor, dep_type?, lag?}]
 * @param {number|null} asOfDay
 */
export function computeEVM(tasks, deps = [], asOfDay = null) {
  if (!tasks.length) {
    return { bac: 0, ev: 0, ac: 0, pv: null, percent_complete: 0, percent_spent: 0, health: "not_started", pv_curve: [] };
  }
  const result = computeCPM(
    tasks.map((t) => ({ id: t.id, duration: t.duration })),
    deps
  );
  const by = (t) => result.tasks[t.id];

  const bac = tasks.reduce((a, t) => a + (t.planned_cost || 0), 0);
  const ev = tasks.reduce((a, t) => a + (t.planned_cost || 0) * ((t.progress_pct || 0) / 100), 0);
  const ac = tasks.reduce((a, t) => a + (t.actual_cost || 0), 0);

  let pv = null;
  if (asOfDay != null) {
    pv = tasks.reduce((a, t) => a + (t.planned_cost || 0) * plannedFraction(by(t).early_start, by(t).early_finish, asOfDay), 0);
  }

  const cv = ev - ac;
  const sv = pv != null ? ev - pv : null;
  const cpi = ac > 0 ? ev / ac : null;
  const spi = pv != null && pv > 0 ? ev / pv : null;
  const eac = cpi != null && cpi > 0 ? bac / cpi : null;
  const etc = eac != null ? eac - ac : null;
  const vac = eac != null ? bac - eac : null;
  const tcpi = bac - ac !== 0 ? (bac - ev) / (bac - ac) : null;
  const percent_complete = bac > 0 ? (ev / bac) * 100 : 0;
  const percent_spent = bac > 0 ? (ac / bac) * 100 : 0;

  const indices = [spi, cpi].filter((x) => x != null);
  let health;
  if (!indices.length) health = percent_complete > 0 ? "in_progress" : "not_started";
  else {
    const worst = Math.min(...indices);
    if (percent_complete >= 100) health = "done";
    else if (worst >= 0.95) health = "on_track";
    else if (worst >= 0.85) health = "at_risk";
    else health = "behind";
  }

  const horizon = Math.max(1, Math.ceil(result.project_duration));
  const pv_curve = [];
  for (let day = 0; day <= horizon; day++) {
    const pvDay = tasks.reduce((a, t) => a + (t.planned_cost || 0) * plannedFraction(by(t).early_start, by(t).early_finish, day), 0);
    const point = { day, pv: r2(pvDay) };
    if (asOfDay != null && day === Math.round(asOfDay)) {
      point.ev = r2(ev);
      point.ac = r2(ac);
    }
    pv_curve.push(point);
  }

  return {
    as_of_day: asOfDay,
    project_duration: r4(result.project_duration),
    bac: r2(bac), ev: r2(ev), ac: r2(ac), pv: r2(pv),
    sv: r2(sv), cv: r2(cv), spi: r4(spi), cpi: r4(cpi),
    eac: r2(eac), etc: r2(etc), vac: r2(vac), tcpi: r4(tcpi),
    percent_complete: r2(percent_complete),
    percent_spent: r2(percent_spent),
    health,
    pv_curve,
  };
}
