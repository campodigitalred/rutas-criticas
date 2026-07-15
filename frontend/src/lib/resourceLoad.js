/**
 * Carga de recursos — espejo en JavaScript del núcleo Python
 * (backend/app/resources/allocation.py). Determinista: produce resultados
 * idénticos al backend. Alimenta la vista de recursos y sus alertas de
 * sobreasignación, con recálculo en el cliente / offline.
 */
import { computeCPM } from "./cpm.js";

const round = (x) => Math.round(x * 10000) / 10000;

/** Días enteros [ES, EF) en que la tarea está activa. */
function activeDays(es, ef, horizon) {
  const start = Math.max(0, Math.floor(es + 1e-9));
  const end = Math.min(Math.max(start, Math.ceil(ef - 1e-9)), horizon);
  const days = [];
  for (let d = start; d < end; d++) days.push(d);
  return days;
}

function groupWindows(days) {
  if (!days.length) return [];
  const sorted = [...days].sort((a, b) => a - b);
  const windows = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === prev + 1) prev = sorted[i];
    else {
      windows.push({ start, end: prev });
      start = prev = sorted[i];
    }
  }
  windows.push({ start, end: prev });
  return windows;
}

/**
 * @param {Array} tasks        [{id, duration}]
 * @param {Array} deps         [{predecessor, successor, dep_type?, lag?}]
 * @param {Array} resources    [{id, name, capacity_per_day, kind?}]
 * @param {Array} assignments  [{task_id, resource_id, units}]
 */
export function computeResourceLoad(tasks, deps, resources, assignments) {
  const result = computeCPM(
    tasks.map((t) => ({ id: t.id, duration: t.duration })),
    deps
  );
  const horizon = Math.max(1, Math.ceil(result.project_duration));

  const load = Object.fromEntries(resources.map((r) => [r.id, new Array(horizon).fill(0)]));
  assignments.forEach((a) => {
    const tr = result.tasks[a.task_id];
    if (!tr || !load[a.resource_id]) return;
    activeDays(tr.early_start, tr.early_finish, horizon).forEach((d) => {
      load[a.resource_id][d] += a.units;
    });
  });

  const profiles = [];
  const alerts = [];
  resources.forEach((r) => {
    const daily = load[r.id];
    const overDays = [];
    for (let d = 0; d < horizon; d++) {
      if (daily[d] > r.capacity_per_day + 1e-9) {
        overDays.push({
          day: d,
          load: round(daily[d]),
          capacity: r.capacity_per_day,
          over: round(daily[d] - r.capacity_per_day),
        });
      }
    }
    const peak = daily.length ? Math.max(...daily) : 0;
    profiles.push({
      resource_id: r.id,
      name: r.name,
      capacity_per_day: r.capacity_per_day,
      kind: r.kind ?? "person",
      peak_load: round(peak),
      load_by_day: daily.map(round),
      overallocated_days: overDays,
      total_person_days: round(daily.reduce((a, x) => a + x, 0)),
    });
    if (overDays.length) {
      alerts.push({
        resource_id: r.id,
        resource_name: r.name,
        peak_load: round(peak),
        capacity_per_day: r.capacity_per_day,
        overallocated_day_count: overDays.length,
        windows: groupWindows(overDays.map((o) => o.day)),
        message: `${r.name} sobreasignado: pico ${round(peak)} vs capacidad ${r.capacity_per_day} en ${overDays.length} día(s).`,
      });
    }
  });

  return {
    horizon_days: horizon,
    project_duration: round(result.project_duration),
    has_overallocation: alerts.length > 0,
    alerts,
    profiles,
  };
}
