/**
 * SyncStatusBar — barra de estado de sincronización offline.
 *
 * Muestra el estado de conexión, el número de cambios pendientes en la cola y
 * permite sincronizar. Tras sincronizar, lista los conflictos detectados y cómo
 * se resolvieron (última-escritura-gana). Incluye controles de demostración para
 * simular la pérdida de señal y una edición concurrente en el servidor.
 */
import React, { useState } from "react";
import { useOfflineSync } from "../context/OfflineSyncContext.jsx";

export default function SyncStatusBar() {
  const { online, pending, conflicts, lastResult, sync, simulateConnectivity, simulateServerEdit } = useOfflineSync();
  const [showConflicts, setShowConflicts] = useState(false);

  return (
    <div className="cc-sync-wrap">
      <div className="cc-syncbar">
        <span className={`cc-sync-dot ${online ? "online" : "offline"}`} />
        <strong>{online ? "En línea" : "Sin conexión"}</strong>
        <span className="cc-sync-pending">
          {pending} cambio{pending === 1 ? "" : "s"} pendiente{pending === 1 ? "" : "s"}
        </span>

        <div className="cc-sync-actions">
          <button
            className="cc-btn ghost"
            onClick={() => simulateConnectivity(!online)}
            title="Simular pérdida/recuperación de señal (modo rural)"
          >
            {online ? "Simular sin señal" : "Recuperar señal"}
          </button>
          {simulateServerEdit && (
            <button
              className="cc-btn ghost"
              onClick={() => simulateServerEdit("T1", "progress_pct", 55)}
              title="Simula que otro técnico cambió T1.progress_pct en el servidor"
            >
              Simular edición ajena
            </button>
          )}
          <button className="cc-btn primary" disabled={!online || pending === 0} onClick={sync}>
            Sincronizar
          </button>
        </div>
      </div>

      {lastResult && (
        <div className="cc-sync-result">
          Última sincronización: {lastResult.appliedCount} aplicado(s),{" "}
          {lastResult.rejectedCount} descartado(s),{" "}
          <button className="cc-linkish" onClick={() => setShowConflicts((s) => !s)}>
            {lastResult.conflictCount} conflicto(s)
          </button>{" "}
          · {lastResult.at.toLocaleTimeString()}
        </div>
      )}

      {showConflicts && conflicts.length > 0 && (
        <div className="cc-conflicts">
          <h4>Conflictos resueltos (última-escritura-gana)</h4>
          <table className="cc-edt-table">
            <thead>
              <tr>
                <th>Entidad</th>
                <th>Campo</th>
                <th>Servidor</th>
                <th>Cliente</th>
                <th>Resolución</th>
              </tr>
            </thead>
            <tbody>
              {conflicts.map((c, i) => (
                <tr key={i}>
                  <td><strong>{c.entity_id}</strong></td>
                  <td>{c.field ?? "—"}</td>
                  <td>{String(c.server_value)}</td>
                  <td>{String(c.client_value)}</td>
                  <td>
                    <span className={`cc-res-badge ${c.resolution}`}>
                      {c.resolution === "client_wins" ? "ganó cliente" : "ganó servidor"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
