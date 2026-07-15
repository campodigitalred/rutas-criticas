import React, { useState } from "react";
import IdeaIntakeWizard from "./components/IdeaIntakeWizard";
import CriticalPathView from "./components/CriticalPathView";
import "./theme.css";

/**
 * Flujo de Campo Crítico:
 *   1. Ingreso inteligente (IdeaIntakeWizard) — idea -> EDT.
 *   2. Ruta crítica (CriticalPathView) — Gantt + red PERT sobre la EDT aceptada.
 */
export default function App() {
  const [plan, setPlan] = useState(null); // { tasks, deps } | null

  if (!plan) {
    return (
      <div className="cc-app">
        <header className="cc-header">
          <div className="cc-brand">
            <div className="cc-logo">CC</div>
            <div>
              <h1>Campo Crítico</h1>
              <p>Agencia Campo Digital</p>
            </div>
          </div>
        </header>
        <IdeaIntakeWizard onAccept={setPlan} />
      </div>
    );
  }

  return (
    <div>
      <div style={{ maxWidth: 1120, margin: "0 auto", padding: "16px 24px 0" }}>
        <button className="cc-btn ghost" onClick={() => setPlan(null)}>
          ← Nueva idea
        </button>
      </div>
      {/* key fuerza remount para reinicializar el estado interno con el nuevo plan */}
      <CriticalPathView
        key={plan.tasks.map((t) => t.id).join("-")}
        initialTasks={plan.tasks}
        initialDeps={plan.deps}
      />
    </div>
  );
}
