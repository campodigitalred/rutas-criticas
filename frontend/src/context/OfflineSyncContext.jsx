/**
 * OfflineSyncContext — estado global de sincronización offline.
 *
 * Expone:
 *   recordMutation(entityId, field, value)  → encola un cambio de campo.
 *   sync()                                    → fusiona la cola contra el servidor.
 *   simulateConnectivity(online)              → alterna en línea/desconectado (demo).
 *   { online, pending, conflicts, lastResult } estado observable.
 *
 * En producción, sync() haría `POST /api/v1/sync`. Aquí, para funcionar en el
 * prototipo/offline, aplica la cola con el motor cliente (../lib/sync.js) contra
 * el snapshot local, con paridad exacta respecto al backend.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { OfflineStore, isOnline, onConnectivityChange } from "../lib/offlineStore.js";
import { applyMutations, stateFromTasks } from "../lib/sync.js";

const OfflineSyncContext = createContext(null);

export function useOfflineSync() {
  return useContext(OfflineSyncContext) ?? NOOP;
}

const NOOP = {
  online: true,
  pending: 0,
  conflicts: [],
  lastResult: null,
  recordMutation: () => {},
  sync: () => {},
  simulateConnectivity: () => {},
  simulateServerEdit: null,
};

export function OfflineSyncProvider({ initialTasks = [], children }) {
  const storeRef = useRef(null);
  if (!storeRef.current) storeRef.current = new OfflineStore();
  const store = storeRef.current;

  const [online, setOnline] = useState(isOnline());
  const [forcedOffline, setForcedOffline] = useState(false);
  const [pending, setPending] = useState(store.pendingCount());
  const [conflicts, setConflicts] = useState([]);
  const [lastResult, setLastResult] = useState(null);

  // Inicializa el snapshot base a partir de las tareas del plan.
  useEffect(() => {
    if (initialTasks.length && !store.getSnapshot()) {
      store.setSnapshot(stateFromTasks(initialTasks, 1));
    }
  }, [initialTasks, store]);

  // Detección de conectividad real del navegador.
  useEffect(() => onConnectivityChange((v) => setOnline(v)), []);

  const effectiveOnline = online && !forcedOffline;

  const recordMutation = useCallback(
    (entityId, field, value) => {
      store.enqueue({ entity_id: entityId, field, value });
      setPending(store.pendingCount());
    },
    [store]
  );

  // Simulación de edición ajena en el servidor (para demostrar conflictos).
  const serverEditRef = useRef(null);
  const simulateServerEdit = useCallback((entityId, field, value) => {
    serverEditRef.current = { entityId, field, value };
  }, []);

  const sync = useCallback(() => {
    if (!effectiveOnline) return;
    let snapshot = store.getSnapshot() ?? stateFromTasks(initialTasks, 1);
    // Aplica una posible edición ajena "en el servidor" con ts alto (concurrente).
    if (serverEditRef.current) {
      const { entityId, field, value } = serverEditRef.current;
      snapshot = JSON.parse(JSON.stringify(snapshot));
      const ent = (snapshot.entities[entityId] = snapshot.entities[entityId] || {
        id: entityId, type: "task", deleted: false, deleted_ts: 0, fields: {},
      });
      ent.fields[field] = { value, ts: Date.now() + 1 }; // más nuevo que la base
      serverEditRef.current = null;
    }
    const result = applyMutations(snapshot, store.getPending());
    store.setSnapshot(result.server_state);
    store.markSettled(
      result.applied.map((a) => a.mutation_id).concat(result.rejected.map((r) => r.mutation_id))
    );
    setPending(store.pendingCount());
    setConflicts(result.conflicts);
    setLastResult({
      appliedCount: result.applied.length,
      rejectedCount: result.rejected.length,
      conflictCount: result.conflicts.length,
      at: new Date(),
    });
  }, [effectiveOnline, store, initialTasks]);

  const value = useMemo(
    () => ({
      online: effectiveOnline,
      pending,
      conflicts,
      lastResult,
      recordMutation,
      sync,
      simulateConnectivity: (v) => setForcedOffline(!v),
      simulateServerEdit,
    }),
    [effectiveOnline, pending, conflicts, lastResult, recordMutation, sync, simulateServerEdit]
  );

  return <OfflineSyncContext.Provider value={value}>{children}</OfflineSyncContext.Provider>;
}
