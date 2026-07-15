/**
 * SimulationView — Modo Simulación / Análisis de riesgo (Módulo D).
 *
 * Ejecuta una simulación Monte Carlo (../lib/montecarlo.js) sobre las duraciones
 * inciertas (Beta-PERT) para estimar la distribución de la fecha final, la
 * probabilidad de cumplir el plazo, el índice de criticidad de cada tarea y el
 * impacto en el presupuesto.
 *
 * Incluye el escenario "¿Qué pasaría si…?": aplicar un retraso (p.ej. lluvias)
 * a una tarea y ver cómo se desplaza la distribución y el presupuesto.
 */
import React, { useMemo, useState } from "react";
import { runMonteCarlo } from "../lib/montecarlo.js";

/** Deriva una dispersión PERT razonable si la tarea solo tiene duración fija. */
function withSpread(task) {
  if (
    task.optimistic != null &&
    task.most_likely != null &&
    task.pessimistic != null
  ) {
    return task;
  }
  const d = task.duration ?? 0;
  return {
    ...task,
    optimistic: Math.max(0.5, Math.round(d * 0.85 * 10) / 10),
    most_likely: d,
    pessimistic: Math.max(d + 0.5, Math.round(d * 1.6 * 10) / 10),
  };
}

/** Aplica un retraso (delta días) a las estimaciones de una tarea. */
function applyDelay(tasks, taskId, delta) {
  if (!taskId || !delta) return tasks;
  return tasks.map((t) =>
    t.id === taskId
      ? {
          ...t,
          optimistic: t.optimistic + delta,
          most_likely: t.most_likely + delta,
          pessimistic: t.pessimistic + delta,
        }
      : t
  );
}

function Histogram({ histogram, markers }) {
  const maxCount = Math.max(...histogram.map((b) => b.count), 1);
  const W = 560;
  const H = 160;
  const barW = W / histogram.length;
  const lo = histogram[0].start;
  const hi = histogram[histogram.length - 1].end;
  const xOf = (val) => ((val - lo) / (hi - lo || 1)) * W;
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H + 28}`} className="cc-hist">
      {histogram.map((b, i) => {
        const h = (b.count / maxCount) * H;
        return (
          <rect
            key={i}
            x={i * barW + 1}
            y={H - h}
            width={barW - 2}
            height={h}
            fill="var(--cc-blue-300)"
            rx="1"
          >
            <title>{`${b.start}–${b.end} días: ${b.count}`}</title>
          </rect>
        );
      })}
      {markers.map((m) => (
        <g key={m.label}>
          <line x1={xOf(m.value)} y1="0" x2={xOf(m.value)} y2={H} stroke={m.color} strokeWidth="2" strokeDasharray={m.dash || ""} />
          <text x={xOf(m.value)} y={H + 12} fontSize="10" fill={m.color} textAnchor="middle">
            {m.label}
          </text>
          <text x={xOf(m.value)} y={H + 24} fontSize="9" fill="var(--cc-gray-500)" textAnchor="middle">
            {Math.round(m.value)}d
          </text>
        </g>
      ))}
    </svg>
  );
}

function CriticalityTable({ index, criticalPath }) {
  const rows = Object.entries(index).sort((a, b) => b[1] - a[1]);
  const criticalSet = new Set(criticalPath);
  return (
    <table className="cc-edt-table">
      <thead>
        <tr>
          <th>Tarea</th>
          <th>Índice de criticidad</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([id, ci]) => {
          // Riesgo "casi crítico": alta criticidad pero fuera del camino determinista.
          const nearCritical = !criticalSet.has(id) && ci >= 0.3;
          return (
            <tr key={id}>
              <td><strong>{id}</strong></td>
              <td style={{ width: "60%" }}>
                <div className="cc-ci-bar">
                  <div
                    className="cc-ci-fill"
                    style={{
                      width: `${ci * 100}%`,
                      background: ci >= 0.6 ? "var(--cc-critical)" : ci >= 0.3 ? "var(--cc-slack)" : "var(--cc-green-600)",
                    }}
                  />
                </div>
              </td>
              <td>
                {(ci * 100).toFixed(0)}%
                {nearCritical && <span className="cc-crit-badge" style={{ marginLeft: 6 }}>casi crítica</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function SimulationView({ tasks, deps, result }) {
  const [iterations, setIterations] = useState(3000);
  const [seed, setSeed] = useState(7);
  const [target, setTarget] = useState("");
  const [costPerDay, setCostPerDay] = useState(0);
  const [delayTask, setDelayTask] = useState("");
  const [delayDays, setDelayDays] = useState(15);

  const simTasks = useMemo(() => tasks.map(withSpread), [tasks]);
  const targetNum = target === "" ? null : Number(target);

  const baseSim = useMemo(
    () =>
      runMonteCarlo(simTasks, deps, {
        iterations,
        seed,
        targetDuration: targetNum,
        costPerDayDelay: Number(costPerDay) || 0,
      }),
    [simTasks, deps, iterations, seed, targetNum, costPerDay]
  );

  const scenarioSim = useMemo(() => {
    if (!delayTask || !delayDays) return null;
    const perturbed = applyDelay(simTasks, delayTask, Number(delayDays));
    return runMonteCarlo(perturbed, deps, {
      iterations,
      seed,
      targetDuration: targetNum,
      costPerDayDelay: Number(costPerDay) || 0,
    });
  }, [simTasks, deps, delayTask, delayDays, iterations, seed, targetNum, costPerDay]);

  const p = baseSim.percentiles;
  const markers = [
    { label: "P50", value: p.p50, color: "var(--cc-green-600)" },
    { label: "P80", value: p.p80, color: "var(--cc-slack)" },
    { label: "P90", value: p.p90, color: "var(--cc-critical)" },
  ];
  if (targetNum != null) markers.push({ label: "Meta", value: targetNum, color: "var(--cc-blue-600)", dash: "4 3" });

  return (
    <div>
      <div className="cc-sim-controls">
        <label>Iteraciones
          <select className="cc-input" value={iterations} onChange={(e) => setIterations(Number(e.target.value))}>
            <option value={1000}>1 000</option>
            <option value={3000}>3 000</option>
            <option value={10000}>10 000</option>
          </select>
        </label>
        <label>Semilla
          <input className="cc-input" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} style={{ width: 80 }} />
        </label>
        <label>Plazo meta (días)
          <input className="cc-input" type="number" placeholder="—" value={target} onChange={(e) => setTarget(e.target.value)} style={{ width: 90 }} />
        </label>
        <label>Costo/día de retraso
          <input className="cc-input" type="number" min="0" value={costPerDay} onChange={(e) => setCostPerDay(e.target.value)} style={{ width: 110 }} />
        </label>
      </div>

      <div className="cc-stats" style={{ marginBottom: 8 }}>
        <div className="cc-stat"><div className="label">Base (determinista)</div><div className="value">{Math.round(baseSim.baseline_duration)} d</div></div>
        <div className="cc-stat"><div className="label">Media simulada</div><div className="value">{baseSim.mean} d</div></div>
        <div className="cc-stat"><div className="label">P80 (recomendado)</div><div className="value" style={{ color: "var(--cc-slack)" }}>{Math.round(p.p80)} d</div></div>
        <div className="cc-stat"><div className="label">P90</div><div className="value" style={{ color: "var(--cc-critical)" }}>{Math.round(p.p90)} d</div></div>
        {baseSim.probability_on_time != null && (
          <div className="cc-stat"><div className="label">Prob. cumplir meta</div><div className="value">{(baseSim.probability_on_time * 100).toFixed(0)}%</div></div>
        )}
        {baseSim.expected_cost != null && (
          <div className="cc-stat"><div className="label">Costo esperado</div><div className="value" style={{ fontSize: 18 }}>${baseSim.expected_cost.toLocaleString()}</div></div>
        )}
      </div>

      <h3 className="cc-section-title">Distribución de la duración del proyecto</h3>
      <Histogram histogram={baseSim.histogram} markers={markers} />

      {/* Escenario "¿Qué pasaría si…?" */}
      <div className="cc-whatif">
        <h3 className="cc-section-title">¿Qué pasaría si…?</h3>
        <div className="cc-sim-controls">
          <label>Retrasar la tarea
            <select className="cc-input" value={delayTask} onChange={(e) => setDelayTask(e.target.value)} style={{ width: 220 }}>
              <option value="">— selecciona —</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>{t.id} · {t.name ?? t.id}</option>
              ))}
            </select>
          </label>
          <label>en (días)
            <input className="cc-input" type="number" value={delayDays} onChange={(e) => setDelayDays(e.target.value)} style={{ width: 80 }} />
          </label>
          <span className="cc-hint" style={{ margin: 0 }}>Ej.: “las lluvias retrasan la fase de campo 15 días”.</span>
        </div>

        {scenarioSim && (
          <div className="cc-stats" style={{ marginTop: 4 }}>
            <div className="cc-stat"><div className="label">Nueva media</div><div className="value">{scenarioSim.mean} d</div></div>
            <div className="cc-stat critical">
              <div className="label">Desplazamiento (media)</div>
              <div className="value">+{(scenarioSim.mean - baseSim.mean).toFixed(1)} d</div>
            </div>
            <div className="cc-stat"><div className="label">Nuevo P80</div><div className="value" style={{ color: "var(--cc-slack)" }}>{Math.round(scenarioSim.percentiles.p80)} d</div></div>
            {scenarioSim.probability_on_time != null && (
              <div className="cc-stat"><div className="label">Prob. cumplir meta</div><div className="value">{(scenarioSim.probability_on_time * 100).toFixed(0)}%</div></div>
            )}
            {scenarioSim.expected_cost != null && (
              <div className="cc-stat critical">
                <div className="label">Impacto presupuestal</div>
                <div className="value" style={{ fontSize: 18 }}>+${(scenarioSim.expected_cost - baseSim.expected_cost).toLocaleString()}</div>
              </div>
            )}
          </div>
        )}
      </div>

      <h3 className="cc-section-title">Índice de criticidad por tarea</h3>
      <p className="cc-hint" style={{ marginTop: 0 }}>
        Fracción de iteraciones en que la tarea cae en el camino crítico. Una tarea con alto índice
        pero fuera del camino determinista es un riesgo “casi crítico” a vigilar.
      </p>
      <CriticalityTable index={baseSim.criticality_index} criticalPath={result?.critical_path ?? []} />
    </div>
  );
}
