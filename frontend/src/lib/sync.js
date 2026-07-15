/**
 * Motor de sincronización — espejo en JavaScript de backend/app/sync/engine.py.
 * Resolución last-write-wins a nivel de campo. Determinista: paridad exacta con
 * el backend. Se usa para aplicar la cola offline de forma optimista en el
 * cliente y para previsualizar la fusión antes/después de sincronizar.
 */

const EPS = 1e-9;

export class SyncError extends Error {}

export function emptyState() {
  return { entities: {} };
}

function fieldTs(entity, field) {
  const fs = entity.fields?.[field];
  return fs ? Number(fs.ts) : 0;
}

function entityLastTs(entity) {
  const tss = Object.values(entity.fields || {}).map((f) => Number(f.ts));
  tss.push(Number(entity.deleted_ts || 0));
  return tss.length ? Math.max(...tss) : 0;
}

function validate(m) {
  if (m.entity_id == null) throw new SyncError("Mutación sin entity_id.");
  if (m.ts == null) throw new SyncError("Mutación sin ts.");
  const op = m.op ?? "set";
  if (op === "set" && m.field == null) throw new SyncError("Mutación 'set' sin field.");
}

/** Aplica las mutaciones al estado (sin mutar la entrada). */
export function applyMutations(state, mutations) {
  const entities = JSON.parse(JSON.stringify((state || {}).entities || {}));
  const applied = [];
  const rejected = [];
  const conflicts = [];

  const ordered = [...mutations].sort((a, b) => {
    const dt = Number(a.ts || 0) - Number(b.ts || 0);
    return dt !== 0 ? dt : String(a.mutation_id || "").localeCompare(String(b.mutation_id || ""));
  });

  for (const m of ordered) {
    validate(m);
    const eid = String(m.entity_id);
    const op = m.op ?? "set";
    const ts = Number(m.ts);
    const baseTs = Number(m.base_ts || 0);
    const mutId = String(m.mutation_id ?? "");

    let entity = entities[eid];
    if (!entity) {
      entity = { id: eid, type: m.entity_type ?? "unknown", deleted: false, deleted_ts: 0, fields: {} };
      entities[eid] = entity;
    }

    if (op === "set") {
      const { field, value } = m;
      const serverTs = fieldTs(entity, field);
      const serverValue = field in entity.fields ? entity.fields[field].value : null;
      const concurrent = serverTs > baseTs + EPS;
      const clientWins = ts > serverTs + EPS;

      if (concurrent) {
        const resolution = clientWins ? "client_wins" : "server_wins";
        conflicts.push({
          mutation_id: mutId, entity_type: entity.type, entity_id: eid, field,
          client_value: value, server_value: serverValue, client_ts: ts, server_ts: serverTs, resolution,
        });
        if (clientWins) {
          entity.fields[field] = { value, ts };
          applied.push({ mutation_id: mutId, entity_id: eid, op: "set", field, value, ts });
        } else {
          rejected.push({ mutation_id: mutId, entity_id: eid, field, reason: "server_wins" });
        }
      } else if (clientWins) {
        entity.fields[field] = { value, ts };
        applied.push({ mutation_id: mutId, entity_id: eid, op: "set", field, value, ts });
      } else {
        rejected.push({ mutation_id: mutId, entity_id: eid, field, reason: "stale" });
      }
    } else if (op === "delete") {
      const lastTs = entityLastTs(entity);
      const concurrent = lastTs > baseTs + EPS;
      const clientWins = ts > lastTs + EPS;
      if (concurrent) {
        const resolution = clientWins ? "client_wins" : "server_wins";
        conflicts.push({
          mutation_id: mutId, entity_type: entity.type, entity_id: eid, field: null,
          client_value: "<deleted>", server_value: "<modified>", client_ts: ts, server_ts: lastTs, resolution,
        });
        if (clientWins) {
          entity.deleted = true;
          entity.deleted_ts = ts;
          applied.push({ mutation_id: mutId, entity_id: eid, op: "delete", field: null, value: null, ts });
        } else {
          rejected.push({ mutation_id: mutId, entity_id: eid, reason: "server_wins" });
        }
      } else {
        entity.deleted = true;
        entity.deleted_ts = ts;
        applied.push({ mutation_id: mutId, entity_id: eid, op: "delete", field: null, value: null, ts });
      }
    } else {
      throw new SyncError(`Operación desconocida: ${op}`);
    }
  }

  const newState = { entities };
  return { applied, rejected, conflicts, server_state: newState, server_ts: highWaterMark(newState) };
}

export function highWaterMark(state) {
  let hw = 0;
  for (const ent of Object.values((state || {}).entities || {})) {
    hw = Math.max(hw, entityLastTs(ent));
  }
  return hw;
}

/** Construye el estado del servidor a partir de una lista de tareas (para snapshot). */
export function stateFromTasks(tasks, ts = 0) {
  const entities = {};
  tasks.forEach((t) => {
    const fields = {};
    ["status", "progress_pct", "duration", "name"].forEach((f) => {
      if (t[f] !== undefined) fields[f] = { value: t[f], ts };
    });
    entities[t.id] = { id: t.id, type: "task", deleted: false, deleted_ts: 0, fields };
  });
  return { entities };
}
