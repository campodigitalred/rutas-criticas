import React, { useState } from "react";
import IdeaIntakeWizard from "./components/IdeaIntakeWizard";
import CriticalPathView from "./components/CriticalPathView";
import SyncStatusBar from "./components/SyncStatusBar";
import LoginView from "./components/LoginView";
import { OfflineSyncProvider } from "./context/OfflineSyncContext.jsx";
import { AuthProvider, useAuth } from "./context/AuthContext.jsx";
import { PERMISSIONS, ROLE_LABELS } from "./lib/authClient.js";
import "./theme.css";

/** Cabecera con identidad del usuario, rol y cierre de sesión. */
function UserBadge() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <div className="cc-userbadge">
      <div className="cc-userinfo">
        <span className="cc-username">{user.full_name || user.email}</span>
        <span className="cc-rolechip">{ROLE_LABELS[user.role] || user.role}{user.demo ? " · demo" : ""}</span>
      </div>
      <button className="cc-btn ghost" onClick={logout}>Cerrar sesión</button>
    </div>
  );
}

/**
 * Flujo de Campo Crítico (autenticado):
 *   1. Ingreso inteligente (IdeaIntakeWizard) — idea -> EDT.
 *   2. Ruta crítica (CriticalPathView) — Gantt + red PERT + Kanban + simulación +
 *      recursos + dashboard, con sincronización offline.
 */
function Workspace() {
  const { can, user } = useAuth();
  const [plan, setPlan] = useState(null);
  const canPlan = can(PERMISSIONS.PROJECT_WRITE); // aliado (solo campo) no planifica

  const header = (
    <header className="cc-header">
      <div className="cc-brand">
        <div className="cc-logo">CC</div>
        <div>
          <h1>Campo Crítico</h1>
          <p>Agencia Campo Digital</p>
        </div>
      </div>
      <UserBadge />
    </header>
  );

  if (!plan) {
    return (
      <div className="cc-app">
        {header}
        {canPlan ? (
          <IdeaIntakeWizard onAccept={setPlan} />
        ) : (
          <div className="cc-card" style={{ maxWidth: 720, margin: "0 auto" }}>
            <h2>Bienvenido, {ROLE_LABELS[user.role]}</h2>
            <p className="sub">
              Tu rol se enfoca en la <strong>ejecución en campo</strong>: seguimiento de tareas y
              avance. Un director o consultor debe crear la ruta del proyecto para que aparezca aquí.
            </p>
          </div>
        )}
      </div>
    );
  }

  return (
    <OfflineSyncProvider key={plan.tasks.map((t) => t.id).join("-")} initialTasks={plan.tasks}>
      <div>
        <div className="cc-app" style={{ paddingBottom: 0 }}>{header}</div>
        <div style={{ maxWidth: 1120, margin: "0 auto", padding: "0 24px" }}>
          {canPlan && (
            <button className="cc-btn ghost" onClick={() => setPlan(null)}>← Nueva idea</button>
          )}
          <SyncStatusBar />
        </div>
        <CriticalPathView initialTasks={plan.tasks} initialDeps={plan.deps} />
      </div>
    </OfflineSyncProvider>
  );
}

function Gate() {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <Workspace /> : <LoginView />;
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
