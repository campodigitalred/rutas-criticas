/**
 * ResourceView — Gestión de recursos y sobreasignación (Módulo D).
 *
 * Asigna personal / maquinaria a las tareas y muestra el histograma de carga
 * diaria por recurso (posicionado en el cronograma temprano del CPM), resaltando
 * los días de sobreasignación y generando alertas automáticas.
 *
 * Usa el núcleo determinista ../lib/resourceLoad.js (paridad exacta con el backend).
 */
import React, { useMemo, useState } from "react";
import { computeResourceLoad } from "../lib/resourceLoad.js";

/** Recursos de ejemplo de Agencia Campo Digital. */
const DEFAULT_RESOURCES = [
  { id: "BRIG", name: "Brigada de campo", capacity_per_day: 1, kind: "person" },
  { id: "ANLT", name: "Analista de datos", capacity_per_day: 1, kind: "person" },
  { id: "DRON", name: "Dron / maquinaria", capacity_per_day: 1, kind: "machinery" },
];

const KIND_ICON = { person: "👷", machinery: "🚜", material: "📦" };

/** Heurística: asigna cada tarea a un recurso según su nombre/fase. */
function defaultAssignments(tasks) {
  const map = {};
  tasks.forEach((t) => {
    const s = `${t.name ?? ""}`.toLowerCase();
    let rid = "BRIG";
    if (/dato|digitaliz|validaci|análisis|analisis|informe|captura/.test(s)) rid = "ANLT";
    else if (/dron|maquinaria|riego|imagen|satelital|vuelo/.test(s)) rid = "DRON";
    map[t.id] = { resource_id: rid, units: 1 };
  });
  return map;
}

function LoadStrip({ profile }) {
  const days = profile.load_by_day;
  const cap = profile.capacity_per_day;
  const W = 520;
  const H = 90;
  const barW = W / Math.max(days.length, 1);
  const maxLoad = Math.max(profile.peak_load, cap, 1);
  const capY = H - (cap / maxLoad) * H;
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H + 16}`} className="cc-loadstrip">
      {days.map((load, d) => {
        const h = (load / maxLoad) * H;
        const over = load > cap + 1e-9;
        return (
          <rect
            key={d}
            x={d * barW + 0.5}
            y={H - h}
            width={Math.max(barW - 1, 1)}
            height={h}
            fill={over ? "var(--cc-critical)" : "var(--cc-green-600)"}
          >
            <title>{`Día ${d}: ${load} / ${cap}`}</title>
          </rect>
        );
      })}
      {/* Línea de capacidad */}
      <line x1="0" y1={capY} x2={W} y2={capY} stroke="var(--cc-gray-900)" strokeWidth="1" strokeDasharray="4 3" />
      <text x="2" y={capY - 3} fontSize="9" fill="var(--cc-gray-500)">cap. {cap}/día</text>
      <text x="2" y={H + 12} fontSize="9" fill="var(--cc-gray-500)">día 0</text>
      <text x={W - 20} y={H + 12} fontSize="9" fill="var(--cc-gray-500)">{days.length}</text>
    </svg>
  );
}

export default function ResourceView({ tasks, deps }) {
  const [resources, setResources] = useState(DEFAULT_RESOURCES);
  const [assignments, setAssignments] = useState(() => defaultAssignments(tasks));

  const load = useMemo(() => {
    const asgList = tasks
      .filter((t) => assignments[t.id])
      .map((t) => ({
        task_id: t.id,
        resource_id: assignments[t.id].resource_id,
        units: assignments[t.id].units,
      }));
    return computeResourceLoad(
      tasks.map((t) => ({ id: t.id, duration: t.duration })),
      deps,
      resources,
      asgList
    );
  }, [tasks, deps, resources, assignments]);

  function setResourceCapacity(rid, capacity) {
    setResources((prev) =>
      prev.map((r) => (r.id === rid ? { ...r, capacity_per_day: Number(capacity) } : r))
    );
  }
  function assignTask(taskId, resource_id) {
    setAssignments((prev) => ({ ...prev, [taskId]: { ...prev[taskId], resource_id } }));
  }

  const profilesById = Object.fromEntries(load.profiles.map((p) => [p.resource_id, p]));

  return (
    <div>
      {/* Alertas de sobreasignación */}
      {load.has_overallocation ? (
        load.alerts.map((a) => (
          <div className="cc-alert-danger" key={a.resource_id}>
            ⚠️ <strong>{a.resource_name}</strong>: pico {a.peak_load} vs capacidad {a.capacity_per_day}/día.
            Sobreasignado {a.overallocated_day_count} día(s) — ventanas{" "}
            {a.windows.map((w) => `[${w.start}–${w.end}]`).join(", ")}.
          </div>
        ))
      ) : (
        <div className="cc-alert-ok">✅ Sin sobreasignación: la carga de todos los recursos está dentro de su capacidad.</div>
      )}

      {/* Perfiles de carga por recurso */}
      <h3 className="cc-section-title">Carga diaria por recurso (horizonte {load.horizon_days} días)</h3>
      <div className="cc-resource-grid">
        {resources.map((r) => {
          const prof = profilesById[r.id];
          const over = prof?.overallocated_days.length > 0;
          return (
            <div className={`cc-resource-card ${over ? "over" : ""}`} key={r.id}>
              <div className="cc-resource-head">
                <span>{KIND_ICON[r.kind]} <strong>{r.name}</strong></span>
                <label className="cc-cap-label">
                  Capacidad
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={r.capacity_per_day}
                    onChange={(e) => setResourceCapacity(r.id, e.target.value)}
                  />
                </label>
              </div>
              {prof ? (
                <>
                  <LoadStrip profile={prof} />
                  <div className="cc-resource-meta">
                    Pico: <strong style={{ color: over ? "var(--cc-critical)" : "var(--cc-green-600)" }}>{prof.peak_load}</strong>
                    {" · "}Persona-días: {prof.total_person_days}
                  </div>
                </>
              ) : (
                <p className="cc-hint">Sin asignaciones.</p>
              )}
            </div>
          );
        })}
      </div>

      {/* Tabla de asignaciones */}
      <h3 className="cc-section-title">Asignación de tareas</h3>
      <table className="cc-edt-table">
        <thead>
          <tr>
            <th>Tarea</th>
            <th>Recurso asignado</th>
            <th>Ventana (CPM)</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => {
            return (
              <tr key={t.id}>
                <td><strong>{t.id}</strong> · {t.name ?? t.id} <span className="cc-kanban-dur">{t.duration}d</span></td>
                <td>
                  <select
                    className="cc-input"
                    value={assignments[t.id]?.resource_id ?? ""}
                    onChange={(e) => assignTask(t.id, e.target.value)}
                    style={{ width: 200 }}
                  >
                    {resources.map((r) => (
                      <option key={r.id} value={r.id}>{KIND_ICON[r.kind]} {r.name}</option>
                    ))}
                  </select>
                </td>
                <td className="cc-hint" style={{ margin: 0 }}>ES–EF según cronograma temprano</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="cc-hint">
        Reasigna tareas a distintos recursos (o aumenta la capacidad) para resolver la sobreasignación;
        la carga se recalcula al instante. Las tareas se posicionan en su inicio temprano (CPM).
      </p>
    </div>
  );
}
