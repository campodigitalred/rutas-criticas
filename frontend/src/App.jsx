import React, { useState } from "react";
import IdeaIntakeWizard from "./components/IdeaIntakeWizard";
import CriticalPathView from "./components/CriticalPathView";
import SyncStatusBar from "./components/SyncStatusBar";
import { OfflineSyncProvider } from "./context/OfflineSyncContext.jsx";
import "./theme.css";

/**
 * Flujo de Campo Crítico:
 *   1. Ingreso inteligente (IdeaIntakeWizard) — idea -> EDT.
 *   2. Ruta crítica (CriticalPathView) — Gantt + red PERT + Kanban + simulación +
 *      recursos + dashboard, con sincronización offline (SyncStatusBar).
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
    <OfflineSyncProvider key={plan.tasks.map((t) => t.id).join("-")} initialTasks={plan.tasks}>
      <div>
        <div style={{ maxWidth: 1120, margin: "0 auto", padding: "16px 24px 0" }}>
          <button className="cc-btn ghost" onClick={() => setPlan(null)}>
            ← Nueva idea
          </button>
          <SyncStatusBar />
        </div>
        <CriticalPathView initialTasks={plan.tasks} initialDeps={plan.deps} />
      </div>
    </OfflineSyncProvider>
  );
}
