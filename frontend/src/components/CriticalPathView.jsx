/**
 * CriticalPathView — Prototipo de la Ruta Crítica de Campo Crítico.
 *
 * Muestra dos vistas del mismo proyecto, recalculando la ruta crítica en tiempo
 * real con el motor CPM/PERT del cliente (../lib/cpm.js):
 *   1. Gantt dinámico  — barras arrastrables (ajustar duración) que recalculan la ruta.
 *   2. Diagrama de Red (PERT) — nodos por capas con las aristas de dependencia.
 *
 * El camino crítico se resalta de forma inequívoca (color + borde). No requiere
 * librerías externas más allá de React: usa SVG y CSS del sistema de diseño.
 */
import React, { useMemo, useRef, useState } from "react";
import { computeCPM } from "../lib/cpm";
import KanbanView from "./KanbanView";
import SimulationView from "./SimulationView";
import ResourceView from "./ResourceView";
import DashboardView from "./DashboardView";
import { useOfflineSync } from "../context/OfflineSyncContext.jsx";
import "../theme.css";

const DAY_PX = 26; // ancho de un día en el Gantt

/** Datos de ejemplo: digitalizar el censo de productores de la región norte. */
const DEMO_TASKS = [
  { id: "T1", name: "Diseño del instrumento de censo", duration: 8 },
  { id: "T2", name: "Capacitación de brigadas", duration: 5 },
  { id: "T3", name: "Levantamiento en campo (norte)", duration: 20 },
  { id: "T4", name: "Digitalización de formularios", duration: 12 },
  { id: "T5", name: "Validación y limpieza de datos", duration: 10 },
  { id: "T6", name: "Informe y entrega", duration: 4 },
];

/** Estado/avance por defecto para una tarea que llega sin datos de ejecución. */
const withExecutionDefaults = (t) => ({
  status: "todo",
  progress_pct: 0,
  ...t,
});

const DEMO_DEPS = [
  { predecessor: "T1", successor: "T2", dep_type: "FS", lag: 0 },
  { predecessor: "T2", successor: "T3", dep_type: "FS", lag: 0 },
  { predecessor: "T3", successor: "T4", dep_type: "SS", lag: 5 },
  { predecessor: "T3", successor: "T5", dep_type: "FS", lag: 0 },
  { predecessor: "T4", successor: "T5", dep_type: "FS", lag: 0 },
  { predecessor: "T5", successor: "T6", dep_type: "FS", lag: 0 },
];

function StatCard({ label, value, critical }) {
  return (
    <div className={`cc-stat ${critical ? "critical" : ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

function Legend() {
  return (
    <div className="cc-legend">
      <span><i className="cc-swatch" style={{ background: "var(--cc-critical)" }} /> Ruta crítica</span>
      <span><i className="cc-swatch" style={{ background: "var(--cc-green-600)" }} /> Tarea con holgura</span>
      <span><i className="cc-swatch" style={{ background: "var(--cc-slack)" }} /> Holgura total</span>
    </div>
  );
}

/* ------------------------------- Vista Gantt ------------------------------ */
function GanttView({ tasks, result, onDurationChange }) {
  const drag = useRef(null);
  const maxDay = Math.max(result.project_duration, 1);

  function startResize(e, task) {
    e.preventDefault();
    drag.current = { id: task.id, startX: e.clientX, startDuration: task.duration };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", stop);
  }
  function onMove(e) {
    if (!drag.current) return;
    const deltaDays = Math.round((e.clientX - drag.current.startX) / DAY_PX);
    const next = Math.max(1, drag.current.startDuration + deltaDays);
    onDurationChange(drag.current.id, next);
  }
  function stop() {
    drag.current = null;
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", stop);
  }

  return (
    <div>
      {tasks.map((task) => {
        const r = result.tasks[task.id];
        return (
          <div className="cc-gantt-row" key={task.id}>
            <div className="cc-gantt-label" title={task.name}>{task.id} · {task.name}</div>
            <div className="cc-gantt-track">
              <div
                className={`cc-gantt-bar ${r.is_critical ? "critical" : ""}`}
                style={{ left: r.early_start * DAY_PX, width: Math.max(r.duration * DAY_PX, 18) }}
                title={`ES ${r.early_start} · EF ${r.early_finish} · holgura ${r.total_slack}`}
              >
                {task.duration}d
                <span className="handle" onMouseDown={(e) => startResize(e, task)} />
              </div>
              {r.total_slack > 0 && (
                <div
                  className="cc-gantt-slack"
                  style={{ left: r.early_finish * DAY_PX, width: r.total_slack * DAY_PX }}
                  title={`Holgura total: ${r.total_slack} días`}
                />
              )}
            </div>
          </div>
        );
      })}
      <div className="cc-axis">
        {Array.from({ length: Math.ceil(maxDay) + 1 }).map((_, d) => (
          <span key={d} style={{ width: DAY_PX, flex: `0 0 ${DAY_PX}px` }}>{d}</span>
        ))}
      </div>
      <p className="cc-hint">
        Arrastra el borde derecho de una barra para cambiar su duración: la ruta crítica se
        recalcula al instante (motor CPM en el cliente).
      </p>
    </div>
  );
}

/* --------------------------- Vista de Red (PERT) -------------------------- */
function NetworkView({ tasks, deps, result }) {
  // Asignar cada tarea a una "capa" según su Early Start para posicionar los nodos.
  const layers = useMemo(() => {
    const byStart = {};
    tasks.forEach((t) => {
      const es = result.tasks[t.id].early_start;
      (byStart[es] = byStart[es] || []).push(t.id);
    });
    const keys = Object.keys(byStart).map(Number).sort((a, b) => a - b);
    return keys.map((k) => byStart[k]);
  }, [tasks, result]);

  const NODE_W = 150, NODE_H = 64, GAP_X = 90, GAP_Y = 26;
  const pos = {};
  layers.forEach((layer, col) => {
    layer.forEach((id, row) => {
      pos[id] = { x: col * (NODE_W + GAP_X) + 20, y: row * (NODE_H + GAP_Y) + 20 };
    });
  });
  const width = layers.length * (NODE_W + GAP_X) + 40;
  const maxRows = Math.max(...layers.map((l) => l.length), 1);
  const height = maxRows * (NODE_H + GAP_Y) + 40;
  const criticalSet = new Set(result.critical_path);
  const isCriticalEdge = (d) =>
    criticalSet.has(d.predecessor) && criticalSet.has(d.successor);

  return (
    <svg width={width} height={height} style={{ minWidth: "100%" }}>
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="var(--cc-gray-500)" />
        </marker>
        <marker id="arrow-crit" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="var(--cc-critical)" />
        </marker>
      </defs>

      {deps.map((d, i) => {
        const a = pos[d.predecessor], b = pos[d.successor];
        if (!a || !b) return null;
        const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2;
        const x2 = b.x, y2 = b.y + NODE_H / 2;
        const crit = isCriticalEdge(d);
        const mx = (x1 + x2) / 2;
        return (
          <g key={i}>
            <path
              d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
              fill="none"
              stroke={crit ? "var(--cc-critical)" : "var(--cc-gray-500)"}
              strokeWidth={crit ? 2.5 : 1.5}
              markerEnd={`url(#${crit ? "arrow-crit" : "arrow"})`}
            />
            <text x={mx} y={(y1 + y2) / 2 - 4} fontSize="10" fill="var(--cc-gray-500)" textAnchor="middle">
              {d.dep_type}{d.lag ? `+${d.lag}` : ""}
            </text>
          </g>
        );
      })}

      {tasks.map((t) => {
        const p = pos[t.id];
        const r = result.tasks[t.id];
        const crit = r.is_critical;
        return (
          <g key={t.id} transform={`translate(${p.x},${p.y})`}>
            <rect
              width={NODE_W} height={NODE_H} rx="10"
              fill={crit ? "#fdece6" : "var(--cc-gray-100)"}
              stroke={crit ? "var(--cc-critical)" : "var(--cc-green-600)"}
              strokeWidth={crit ? 2.5 : 1.5}
            />
            <text x="10" y="18" fontSize="12" fontWeight="700" fill="var(--cc-gray-900)">
              {t.id} · {t.duration}d
            </text>
            <text x="10" y="34" fontSize="10" fill="var(--cc-gray-500)">
              {t.name.length > 22 ? t.name.slice(0, 21) + "…" : t.name}
            </text>
            <text x="10" y="52" fontSize="10" fill={crit ? "var(--cc-critical)" : "var(--cc-gray-500)"}>
              ES {r.early_start} · EF {r.early_finish} · H {r.total_slack}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------- Componente ------------------------------- */
export default function CriticalPathView({
  initialTasks = DEMO_TASKS,
  initialDeps = DEMO_DEPS,
}) {
  const [tasks, setTasks] = useState(() => initialTasks.map(withExecutionDefaults));
  const [deps] = useState(initialDeps);
  const [view, setView] = useState("gantt");
  const { recordMutation } = useOfflineSync();

  // Recálculo memoizado del motor CPM ante cualquier cambio de duración.
  const result = useMemo(() => {
    try {
      return computeCPM(tasks, deps);
    } catch (e) {
      return { project_duration: 0, critical_path: [], tasks: {}, error: e.message };
    }
  }, [tasks, deps]);

  function handleDurationChange(id, duration) {
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, duration } : t)));
  }

  function handleStatusChange(id, status) {
    setTasks((prev) =>
      prev.map((t) =>
        t.id === id
          ? { ...t, status, progress_pct: status === "done" ? 100 : t.progress_pct }
          : t
      )
    );
    // Encola el cambio para sincronización offline.
    recordMutation(id, "status", status);
    if (status === "done") recordMutation(id, "progress_pct", 100);
  }

  function handleProgressChange(id, progress_pct) {
    let newStatus = null;
    setTasks((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t;
        // El avance ajusta el estado de forma coherente.
        let status = t.status;
        if (progress_pct >= 100) status = "done";
        else if (progress_pct > 0 && status === "todo") status = "in_progress";
        else if (progress_pct < 100 && status === "done") status = "in_progress";
        newStatus = status !== t.status ? status : null;
        return { ...t, progress_pct, status };
      })
    );
    recordMutation(id, "progress_pct", progress_pct);
    if (newStatus) recordMutation(id, "status", newStatus);
  }

  return (
    <div className="cc-app">
      <header className="cc-header">
        <div className="cc-brand">
          <div className="cc-logo">CC</div>
          <div>
            <h1>Campo Crítico</h1>
            <p>Ruta Crítica · Agencia Campo Digital</p>
          </div>
        </div>
      </header>

      <div className="cc-stats">
        <StatCard label="Duración proyecto" value={`${result.project_duration} días`} />
        <StatCard label="Tareas críticas" value={result.critical_path.length} critical />
        <StatCard label="Camino crítico" value={result.critical_path.join(" → ") || "—"} critical />
        <StatCard label="σ PERT (días)" value={result.pert_std_dev ?? 0} />
      </div>

      <div className="cc-tabs">
        <button className={`cc-tab ${view === "gantt" ? "active" : ""}`} onClick={() => setView("gantt")}>
          Gantt dinámico
        </button>
        <button className={`cc-tab ${view === "network" ? "active" : ""}`} onClick={() => setView("network")}>
          Diagrama de Red (PERT)
        </button>
        <button className={`cc-tab ${view === "kanban" ? "active" : ""}`} onClick={() => setView("kanban")}>
          Kanban de ejecución
        </button>
        <button className={`cc-tab ${view === "simulation" ? "active" : ""}`} onClick={() => setView("simulation")}>
          Simulación (riesgo)
        </button>
        <button className={`cc-tab ${view === "resources" ? "active" : ""}`} onClick={() => setView("resources")}>
          Recursos
        </button>
        <button className={`cc-tab ${view === "dashboard" ? "active" : ""}`} onClick={() => setView("dashboard")}>
          Dashboard / EVM
        </button>
      </div>

      {(view === "gantt" || view === "network") && <Legend />}

      <div className="cc-panel">
        {result.error ? (
          <p style={{ color: "var(--cc-critical)" }}>Error: {result.error}</p>
        ) : view === "gantt" ? (
          <GanttView tasks={tasks} result={result} onDurationChange={handleDurationChange} />
        ) : view === "network" ? (
          <NetworkView tasks={tasks} deps={deps} result={result} />
        ) : view === "kanban" ? (
          <KanbanView
            tasks={tasks}
            deps={deps}
            result={result}
            onStatusChange={handleStatusChange}
            onProgressChange={handleProgressChange}
          />
        ) : view === "simulation" ? (
          <SimulationView tasks={tasks} deps={deps} result={result} />
        ) : view === "resources" ? (
          <ResourceView tasks={tasks} deps={deps} />
        ) : (
          <DashboardView tasks={tasks} deps={deps} />
        )}
      </div>
    </div>
  );
}
