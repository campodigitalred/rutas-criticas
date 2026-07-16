/**
 * IdeaIntakeWizard — Módulo A (Ingreso Inteligente) de Campo Crítico.
 *
 * Paso 1: el usuario describe una idea en texto libre (o dicta una nota de voz).
 * Paso 2: el asistente propone una EDT/WBS editable con estimaciones PERT y una
 *         vista previa de la ruta crítica; al confirmar, se entrega el plan a
 *         `CriticalPathView`.
 *
 * En producción, `generate()` debería llamar a `POST /api/v1/ai/breakdown`
 * (que usa un LLM real cuando CAMPO_LLM_API_KEY está configurada). Aquí se usa
 * el generador heurístico del cliente (../lib/aiBreakdown) para funcionar en el
 * prototipo y sin conexión.
 */
import React, { useState } from "react";
import { breakdownIdea, wbsToCriticalPathInput } from "../lib/aiBreakdown";
import { computeCPM } from "../lib/cpm.js";
import "../theme.css";

/** Recalcula la vista previa CPM a partir de las tareas/dependencias actuales. */
function recomputePreview(tasks, deps) {
  try {
    const r = computeCPM(
      tasks.map((t) => ({
        id: t.temp_id,
        optimistic: t.optimistic_days,
        most_likely: t.most_likely_days,
        pessimistic: t.pessimistic_days,
      })),
      deps.map((d) => ({
        predecessor: d.predecessor,
        successor: d.successor,
        dep_type: d.dep_type,
        lag: d.lag_days,
      }))
    );
    return {
      project_duration_days: r.project_duration,
      critical_path: r.critical_path,
      pert_std_dev: r.pert_std_dev,
    };
  } catch {
    return { project_duration_days: 0, critical_path: [], pert_std_dev: 0 };
  }
}

const EXAMPLES = [
  "Queremos digitalizar el censo de productores de la región norte en 3 meses.",
  "Construir una plataforma web y app móvil para asistencia técnica rural en 4 meses.",
  "Programa de capacitación a brigadas de campo en agricultura de precisión, 6 semanas.",
  "Ciclo de siembra y cosecha de maíz con riego tecnificado.",
];

export default function IdeaIntakeWizard({ onAccept }) {
  const [step, setStep] = useState("idea");
  const [text, setText] = useState("");
  const [horizon, setHorizon] = useState("");
  const [breakdown, setBreakdown] = useState(null);

  function generate() {
    const target = horizon ? Number(horizon) : null;
    // Producción: const res = await fetch('/api/v1/ai/breakdown', {...})
    const res = breakdownIdea(text, target);
    setBreakdown(res);
    setStep("review");
  }

  function updateTask(idx, field, value) {
    setBreakdown((prev) => {
      const tasks = prev.tasks.map((t, i) =>
        i === idx ? { ...t, [field]: Number(value) } : t
      );
      // Recalcula la ruta crítica en vivo al editar una estimación.
      return { ...prev, tasks, preview: recomputePreview(tasks, prev.dependencies) };
    });
  }

  function accept() {
    onAccept?.(wbsToCriticalPathInput(breakdown));
  }

  if (step === "idea") {
    return (
      <div className="cc-wizard">
        <div className="cc-card">
          <h2>Asistente IA de desglose</h2>
          <p className="sub">
            Describe tu idea o proyecto. El asistente la convertirá en una Estructura de
            Desglose del Trabajo (EDT) con tiempos, dependencias y ruta crítica.
          </p>
          <textarea
            className="cc-textarea"
            placeholder="Ej.: Queremos digitalizar el censo de productores de la región norte en 3 meses…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="cc-chips">
            {EXAMPLES.map((ex) => (
              <span key={ex} className="cc-chip" onClick={() => setText(ex)}>
                {ex.length > 48 ? ex.slice(0, 47) + "…" : ex}
              </span>
            ))}
          </div>
          <div className="cc-field-row">
            <label style={{ fontSize: 13, color: "var(--cc-gray-500)" }}>
              Horizonte objetivo (días, opcional):
            </label>
            <input
              className="cc-input"
              type="number"
              min="1"
              placeholder="p.ej. 90"
              value={horizon}
              onChange={(e) => setHorizon(e.target.value)}
            />
            <button
              className="cc-btn primary"
              disabled={text.trim().length < 5}
              onClick={generate}
              style={{ marginLeft: "auto" }}
            >
              Generar EDT →
            </button>
          </div>
          <p className="cc-hint">
            🎙️ Las notas de voz se transcriben con <code>/api/v1/ai/transcribe</code> (Whisper)
            y alimentan este mismo flujo.
          </p>
        </div>
      </div>
    );
  }

  // Paso de revisión
  const p = breakdown.preview;
  return (
    <div className="cc-wizard">
      <div className="cc-card">
        <h2>EDT propuesta</h2>
        <p className="sub">{breakdown.summary}</p>

        <div className="cc-stats" style={{ marginBottom: 8 }}>
          <div className="cc-stat">
            <div className="label">Duración estimada</div>
            <div className="value">{Math.round(p.project_duration_days)} d</div>
          </div>
          <div className="cc-stat critical">
            <div className="label">Ruta crítica</div>
            <div className="value" style={{ fontSize: 16 }}>{p.critical_path.join(" → ")}</div>
          </div>
          <div className="cc-stat">
            <div className="label">σ PERT</div>
            <div className="value">{p.pert_std_dev} d</div>
          </div>
          <div className="cc-stat">
            <div className="label">Fuente</div>
            <div className="value" style={{ fontSize: 16 }}>
              {breakdown.provider === "llm" ? "IA (LLM)" : "Heurístico"}
            </div>
          </div>
        </div>

        {breakdown.detected_horizon_days && (
          <p className="sub">Horizonte objetivo detectado: {Math.round(breakdown.detected_horizon_days)} días.</p>
        )}
        {breakdown.warnings.map((w, i) => (
          <div className="cc-warning" key={i}>⚠️ {w}</div>
        ))}

        <table className="cc-edt-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Tarea</th>
              <th>Fase</th>
              <th title="Optimista">O</th>
              <th title="Más probable">M</th>
              <th title="Pesimista">P</th>
              <th title="Duración esperada PERT">Esperada</th>
            </tr>
          </thead>
          <tbody>
            {breakdown.tasks.map((t, i) => {
              const exp = ((t.optimistic_days + 4 * t.most_likely_days + t.pessimistic_days) / 6).toFixed(1);
              const isCritical = p.critical_path.includes(t.temp_id);
              return (
                <tr key={t.temp_id} style={isCritical ? { background: "#fdece6" } : undefined}>
                  <td><strong>{t.temp_id}</strong></td>
                  <td>
                    {t.name}
                    {t.is_milestone && " 🏁"}
                  </td>
                  <td>{t.phase && <span className="cc-phase-tag">{t.phase}</span>}</td>
                  <td><input type="number" min="0.5" step="0.5" value={t.optimistic_days} onChange={(e) => updateTask(i, "optimistic_days", e.target.value)} /></td>
                  <td><input type="number" min="0.5" step="0.5" value={t.most_likely_days} onChange={(e) => updateTask(i, "most_likely_days", e.target.value)} /></td>
                  <td><input type="number" min="0.5" step="0.5" value={t.pessimistic_days} onChange={(e) => updateTask(i, "pessimistic_days", e.target.value)} /></td>
                  <td><strong style={isCritical ? { color: "var(--cc-critical)" } : undefined}>{exp} d</strong></td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div className="cc-actions">
          <button className="cc-btn ghost" onClick={() => setStep("idea")}>← Editar idea</button>
          <button className="cc-btn primary" onClick={accept}>Usar esta ruta crítica →</button>
        </div>
      </div>
    </div>
  );
}
