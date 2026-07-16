/**
 * Métricas de ejecución — espejo en JavaScript del núcleo Python
 * (backend/app/execution/metrics.py). Alimenta el tablero Kanban y su cabecera
 * de salud, recalculando en el cliente y en modo offline.
 */
import { computeCPM } from "./cpm.js";

export const VALID_STATUS = ["todo", "in_progress", "blocked", "done"];
export const STATUS_LABELS = {
  todo: "Por hacer",
  in_progress: "En progreso",
  blocked: "Bloqueada",
  done: "Completada",
};

const ON_TRACK_TOLERANCE = -5;
const AT_RISK_TOLERANCE = -15;

/** Normaliza el avance según el estado (done => 100). */
export function normalizedProgress(task) {
  if (task.status === "done") return 100;
  const p = Number(task.progress_pct ?? 0);
  return Math.max(0, Math.min(100, p));
}

function weightedProgress(items) {
  // items: [{ duration, progress }]
  const total = items.reduce((a, x) => a + x.duration, 0);
  if (total <= 0) {
    return items.length
      ? Math.round((items.reduce((a, x) => a + x.progress, 0) / items.length) * 100) / 100
      : 0;
  }
  const acc = items.reduce((a, x) => a + x.duration * x.progress, 0);
  return Math.round((acc / total) * 100) / 100;
}

function health(overall, variance, criticalBlocked) {
  if (overall >= 100) return "done";
  if (criticalBlocked) {
    if (variance === null || variance >= AT_RISK_TOLERANCE) return "at_risk";
    return "behind";
  }
  if (variance === null) return overall > 0 ? "in_progress" : "not_started";
  if (variance >= ON_TRACK_TOLERANCE) return "on_track";
  if (variance >= AT_RISK_TOLERANCE) return "at_risk";
  return "behind";
}

/**
 * Calcula el resumen de ejecución.
 * @param {Array<{id,duration,status,progress_pct}>} tasks
 * @param {Array<{predecessor,successor,dep_type?,lag?}>} dependencies
 * @param {number|null} asOfDay
 */
export function computeExecutionSummary(tasks, dependencies = [], asOfDay = null) {
  if (!tasks.length) {
    return {
      total_tasks: 0, status_counts: {}, overall_progress: 0, critical_progress: 0,
      blocked_count: 0, critical_blocked: false, project_duration: 0, critical_path: [],
      as_of_day: asOfDay, planned_progress: null, schedule_variance_pct: null, health: "not_started",
    };
  }

  const result = computeCPM(
    tasks.map((t) => ({ id: t.id, duration: t.duration })),
    dependencies
  );
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  const criticalSet = new Set(result.critical_path);

  const status_counts = { todo: 0, in_progress: 0, blocked: 0, done: 0 };
  tasks.forEach((t) => (status_counts[t.status] = (status_counts[t.status] ?? 0) + 1));
  const blocked_count = status_counts.blocked;
  const critical_blocked = [...criticalSet].some((id) => byId[id]?.status === "blocked");

  const overall = weightedProgress(
    tasks.map((t) => ({ duration: t.duration, progress: normalizedProgress(t) }))
  );
  const critItems = [...criticalSet]
    .filter((id) => byId[id])
    .map((id) => ({ duration: byId[id].duration, progress: normalizedProgress(byId[id]) }));
  const critical = critItems.length ? weightedProgress(critItems) : 0;

  let planned = null;
  let variance = null;
  if (asOfDay !== null && asOfDay !== undefined) {
    const plannedItems = tasks.map((t) => {
      const r = result.tasks[t.id];
      const dur = r.duration;
      let pct;
      if (dur <= 0) pct = asOfDay >= r.early_finish ? 100 : 0;
      else pct = Math.max(0, Math.min(1, (asOfDay - r.early_start) / dur)) * 100;
      return { duration: t.duration, progress: pct };
    });
    planned = weightedProgress(plannedItems);
    variance = Math.round((overall - planned) * 100) / 100;
  }

  return {
    total_tasks: tasks.length,
    status_counts,
    overall_progress: overall,
    critical_progress: critical,
    blocked_count,
    critical_blocked,
    project_duration: result.project_duration,
    critical_path: result.critical_path,
    as_of_day: asOfDay ?? null,
    planned_progress: planned,
    schedule_variance_pct: variance,
    health: health(overall, variance, critical_blocked),
  };
}

export const HEALTH_META = {
  not_started: { label: "Sin iniciar", color: "var(--cc-gray-500)" },
  in_progress: { label: "En progreso", color: "var(--cc-blue-600)" },
  on_track: { label: "En tiempo", color: "var(--cc-green-600)" },
  at_risk: { label: "En riesgo", color: "var(--cc-slack)" },
  behind: { label: "Atrasado", color: "var(--cc-critical)" },
  done: { label: "Completado", color: "var(--cc-green-600)" },
};
