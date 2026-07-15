/**
 * KanbanView — Vista Kanban de Ejecución (Módulo C) de Campo Crítico.
 *
 * Tablero de seguimiento diario de las tareas derivadas de la ruta crítica.
 * Columnas por estado (Por hacer / En progreso / Bloqueada / Completada) con
 * arrastrar y soltar nativo (HTML5, sin librerías externas). Las tarjetas del
 * camino crítico se resaltan y la cabecera muestra la salud del proyecto
 * calculada por el núcleo de métricas de ejecución (../lib/execution.js).
 */
import React, { useMemo, useState } from "react";
import {
  HEALTH_META,
  STATUS_LABELS,
  VALID_STATUS,
  computeExecutionSummary,
  normalizedProgress,
} from "../lib/execution.js";

function HealthBadge({ health }) {
  const meta = HEALTH_META[health] ?? HEALTH_META.not_started;
  return (
    <span className="cc-health" style={{ background: meta.color }}>
      {meta.label}
    </span>
  );
}

function ProgressBar({ pct, critical }) {
  return (
    <div className="cc-progress">
      <div
        className="cc-progress-fill"
        style={{
          width: `${pct}%`,
          background: critical ? "var(--cc-critical)" : "var(--cc-green-600)",
        }}
      />
    </div>
  );
}

function KanbanCard({ task, isCritical, onProgressChange, onDragStart }) {
  const pct = normalizedProgress(task);
  return (
    <div
      className={`cc-kanban-card ${isCritical ? "critical" : ""}`}
      draggable
      onDragStart={(e) => onDragStart(e, task.id)}
    >
      <div className="cc-kanban-card-head">
        <strong>{task.id}</strong>
        {isCritical && <span className="cc-crit-badge">CRÍTICA</span>}
        <span className="cc-kanban-dur">{task.duration}d</span>
      </div>
      <div className="cc-kanban-name">{task.name}</div>
      <ProgressBar pct={pct} critical={isCritical} />
      <div className="cc-kanban-progress-row">
        <input
          type="range"
          min="0"
          max="100"
          step="5"
          value={pct}
          disabled={task.status === "done"}
          onChange={(e) => onProgressChange(task.id, Number(e.target.value))}
        />
        <span>{pct}%</span>
      </div>
    </div>
  );
}

export default function KanbanView({ tasks, deps, result, onStatusChange, onProgressChange }) {
  const [asOfDay, setAsOfDay] = useState("");
  const [dragOver, setDragOver] = useState(null);

  const criticalSet = useMemo(
    () => new Set(result?.critical_path ?? []),
    [result]
  );

  const summary = useMemo(() => {
    const day = asOfDay === "" ? null : Number(asOfDay);
    return computeExecutionSummary(tasks, deps, day);
  }, [tasks, deps, asOfDay]);

  const byStatus = useMemo(() => {
    const groups = { todo: [], in_progress: [], blocked: [], done: [] };
    tasks.forEach((t) => (groups[t.status] ?? groups.todo).push(t));
    return groups;
  }, [tasks]);

  function handleDragStart(e, id) {
    e.dataTransfer.setData("text/plain", id);
    e.dataTransfer.effectAllowed = "move";
  }
  function handleDrop(e, status) {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/plain");
    if (id) onStatusChange(id, status);
    setDragOver(null);
  }

  return (
    <div>
      {/* Cabecera de salud de ejecución */}
      <div className="cc-exec-header">
        <div className="cc-exec-health">
          <HealthBadge health={summary.health} />
          <div>
            <div className="cc-exec-metric-label">Avance global</div>
            <div className="cc-exec-metric-value">{summary.overall_progress}%</div>
          </div>
          <div>
            <div className="cc-exec-metric-label">Avance camino crítico</div>
            <div className="cc-exec-metric-value" style={{ color: "var(--cc-critical)" }}>
              {summary.critical_progress}%
            </div>
          </div>
          {summary.blocked_count > 0 && (
            <div>
              <div className="cc-exec-metric-label">Bloqueadas</div>
              <div className="cc-exec-metric-value" style={{ color: "var(--cc-critical)" }}>
                {summary.blocked_count}
                {summary.critical_blocked && " ⚠️ crítica"}
              </div>
            </div>
          )}
        </div>
        <div className="cc-exec-asof">
          <label>Día del proyecto:</label>
          <input
            type="number"
            min="0"
            placeholder="hoy"
            className="cc-input"
            style={{ width: 80 }}
            value={asOfDay}
            onChange={(e) => setAsOfDay(e.target.value)}
          />
          {summary.planned_progress != null && (
            <span className="cc-exec-planned">
              Planeado: {summary.planned_progress}% · Var:{" "}
              <strong style={{ color: summary.schedule_variance_pct < 0 ? "var(--cc-critical)" : "var(--cc-green-600)" }}>
                {summary.schedule_variance_pct > 0 ? "+" : ""}
                {summary.schedule_variance_pct} pp
              </strong>
            </span>
          )}
        </div>
      </div>

      {/* Columnas */}
      <div className="cc-kanban">
        {VALID_STATUS.map((status) => (
          <div
            key={status}
            className={`cc-kanban-col ${dragOver === status ? "drag-over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(status);
            }}
            onDragLeave={() => setDragOver((s) => (s === status ? null : s))}
            onDrop={(e) => handleDrop(e, status)}
          >
            <div className="cc-kanban-col-head">
              {STATUS_LABELS[status]}
              <span className="cc-kanban-count">{byStatus[status].length}</span>
            </div>
            {byStatus[status].map((t) => (
              <KanbanCard
                key={t.id}
                task={t}
                isCritical={criticalSet.has(t.id)}
                onProgressChange={onProgressChange}
                onDragStart={handleDragStart}
              />
            ))}
            {byStatus[status].length === 0 && (
              <div className="cc-kanban-empty">Arrastra tarjetas aquí</div>
            )}
          </div>
        ))}
      </div>
      <p className="cc-hint">
        Arrastra las tarjetas entre columnas para actualizar su estado; ajusta el porcentaje con el
        deslizador. La salud del proyecto y el avance del camino crítico se recalculan al instante.
      </p>
    </div>
  );
}
