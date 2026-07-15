/**
 * Almacén offline — cola de mutaciones persistente + detección de conectividad.
 *
 * En zonas rurales sin señal, los cambios (estado/avance de tareas, notas de
 * campo) se encolan localmente y se sincronizan al recuperar conexión. La cola
 * persiste en localStorage (navegador) o en memoria (SSR/pruebas).
 */

const QUEUE_KEY = "cc_mutation_queue_v1";
const SNAPSHOT_KEY = "cc_snapshot_v1";

/** Backend de almacenamiento con degradación a memoria. */
function pickStorage() {
  try {
    if (typeof localStorage !== "undefined") {
      const k = "__cc_test__";
      localStorage.setItem(k, "1");
      localStorage.removeItem(k);
      return localStorage;
    }
  } catch (_) {
    /* localStorage no disponible */
  }
  const mem = new Map();
  return {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v)),
    removeItem: (k) => mem.delete(k),
  };
}

let _counter = 0;
/** Genera un id de mutación único (idempotencia en la sincronización). */
export function newMutationId() {
  _counter += 1;
  const rnd = Math.random().toString(36).slice(2, 8);
  return `m_${Date.now()}_${_counter}_${rnd}`;
}

export class OfflineStore {
  constructor(storage = pickStorage()) {
    this.storage = storage;
  }

  _read(key, fallback) {
    const raw = this.storage.getItem(key);
    if (!raw) return fallback;
    try {
      return JSON.parse(raw);
    } catch (_) {
      return fallback;
    }
  }
  _write(key, value) {
    this.storage.setItem(key, JSON.stringify(value));
  }

  /** Snapshot del estado del servidor (base para detectar conflictos). */
  getSnapshot() {
    return this._read(SNAPSHOT_KEY, null);
  }
  setSnapshot(state) {
    this._write(SNAPSHOT_KEY, state);
  }

  getPending() {
    return this._read(QUEUE_KEY, []);
  }

  /**
   * Encola una mutación de campo. Colapsa ediciones repetidas del mismo
   * (entidad, campo) para no acumular ruido: conserva la última con su base.
   */
  enqueue({ entity_type = "task", entity_id, field, value, op = "set", base_ts }) {
    const queue = this.getPending();
    const ts = Date.now();
    // La base es el ts del campo en el último snapshot conocido (lo que el
    // cliente "sabía" al editar). Permite detectar cambios ajenos concurrentes.
    if (base_ts == null) {
      const snap = this.getSnapshot();
      base_ts = Number(snap?.entities?.[entity_id]?.fields?.[field]?.ts ?? 0);
    }
    if (op === "set") {
      const existing = queue.find(
        (m) => m.op === "set" && m.entity_id === entity_id && m.field === field
      );
      if (existing) {
        existing.value = value;
        existing.ts = ts; // conserva base_ts original (primera divergencia)
        this._write(QUEUE_KEY, queue);
        return existing;
      }
    }
    const mutation = {
      mutation_id: newMutationId(),
      entity_type,
      entity_id,
      op,
      field,
      value,
      ts,
      base_ts,
    };
    queue.push(mutation);
    this._write(QUEUE_KEY, queue);
    return mutation;
  }

  /** Elimina de la cola las mutaciones ya aplicadas/rechazadas por el servidor. */
  markSettled(mutationIds) {
    const settled = new Set(mutationIds);
    const remaining = this.getPending().filter((m) => !settled.has(m.mutation_id));
    this._write(QUEUE_KEY, remaining);
    return remaining;
  }

  clear() {
    this.storage.removeItem(QUEUE_KEY);
  }

  pendingCount() {
    return this.getPending().length;
  }
}

/* ------------------------- Detección de conectividad ---------------------- */
export function isOnline() {
  return typeof navigator === "undefined" ? true : navigator.onLine !== false;
}

/** Suscribe a cambios de conectividad; devuelve función para desuscribir. */
export function onConnectivityChange(cb) {
  if (typeof window === "undefined") return () => {};
  const on = () => cb(true);
  const off = () => cb(false);
  window.addEventListener("online", on);
  window.addEventListener("offline", off);
  return () => {
    window.removeEventListener("online", on);
    window.removeEventListener("offline", off);
  };
}
