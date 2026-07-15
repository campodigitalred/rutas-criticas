"""Motor de sincronización offline (last-write-wins a nivel de campo).

Modelo de estado del servidor (serializable a JSON):

    {
      "entities": {
        "<entity_id>": {
          "id": str, "type": str,
          "deleted": bool, "deleted_ts": float,
          "fields": { "<field>": { "value": <any>, "ts": float } }
        }
      }
    }

Una **mutación** del cliente:

    {
      "mutation_id": str,          # id único de la mutación (idempotencia)
      "entity_type": str,
      "entity_id": str,
      "op": "set" | "delete",
      "field": str,                # requerido para "set"
      "value": <any>,              # requerido para "set"
      "ts": float,                 # reloj lógico del cliente al editar
      "base_ts": float             # ts del campo que el cliente tenía al editar
    }

Reglas de resolución (para cada mutación, en orden de ``ts``):

* **Conflicto**: el servidor cambió el campo *después* de la base del cliente
  (``server_ts > base_ts``). Se resuelve por LWW y se registra para revisión.
* **LWW**: gana la escritura con ``ts`` mayor; en empate gana el servidor.
* Sin conflicto y mutación más nueva → se aplica limpiamente.
* Sin conflicto y mutación más vieja → se descarta como *stale*.

El motor es puro (stdlib) y no muta el estado de entrada.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

EPS = 1e-9


class SyncError(ValueError):
    """Mutación malformada o inválida."""


def empty_state() -> dict:
    return {"entities": {}}


def _field_ts(entity: dict, field: str) -> float:
    fs = entity.get("fields", {}).get(field)
    return float(fs["ts"]) if fs else 0.0


def _entity_last_ts(entity: dict) -> float:
    tss = [float(f["ts"]) for f in entity.get("fields", {}).values()]
    tss.append(float(entity.get("deleted_ts", 0.0)))
    return max(tss) if tss else 0.0


def apply_mutations(state: Optional[dict], mutations: List[dict]) -> dict:
    """Aplica las mutaciones al estado y devuelve el resultado de la sincronización.

    Devuelve ``{applied, rejected, conflicts, server_state, server_ts}``.
    No modifica el ``state`` recibido.
    """
    entities: Dict[str, dict] = copy.deepcopy((state or {}).get("entities", {}))
    applied: List[dict] = []
    rejected: List[dict] = []
    conflicts: List[dict] = []

    ordered = sorted(
        mutations, key=lambda m: (float(m.get("ts", 0) or 0), str(m.get("mutation_id", "")))
    )

    for m in ordered:
        _validate(m)
        eid = str(m["entity_id"])
        op = m.get("op", "set")
        ts = float(m["ts"])
        base_ts = float(m.get("base_ts", 0) or 0)
        mut_id = str(m.get("mutation_id", ""))

        entity = entities.get(eid)
        if entity is None:
            entity = {
                "id": eid,
                "type": m.get("entity_type", "unknown"),
                "deleted": False,
                "deleted_ts": 0.0,
                "fields": {},
            }
            entities[eid] = entity

        if op == "set":
            field = m["field"]
            value = m["value"]
            server_ts = _field_ts(entity, field)
            server_value = (
                entity["fields"][field]["value"] if field in entity["fields"] else None
            )
            concurrent = server_ts > base_ts + EPS
            client_wins = ts > server_ts + EPS

            if concurrent:
                resolution = "client_wins" if client_wins else "server_wins"
                conflicts.append(
                    {
                        "mutation_id": mut_id,
                        "entity_type": entity["type"],
                        "entity_id": eid,
                        "field": field,
                        "client_value": value,
                        "server_value": server_value,
                        "client_ts": ts,
                        "server_ts": server_ts,
                        "resolution": resolution,
                    }
                )
                if client_wins:
                    entity["fields"][field] = {"value": value, "ts": ts}
                    applied.append(_applied(mut_id, eid, "set", field, value, ts))
                else:
                    rejected.append(
                        {"mutation_id": mut_id, "entity_id": eid, "field": field, "reason": "server_wins"}
                    )
            else:
                if client_wins:
                    entity["fields"][field] = {"value": value, "ts": ts}
                    applied.append(_applied(mut_id, eid, "set", field, value, ts))
                else:
                    rejected.append(
                        {"mutation_id": mut_id, "entity_id": eid, "field": field, "reason": "stale"}
                    )

        elif op == "delete":
            last_ts = _entity_last_ts(entity)
            concurrent = last_ts > base_ts + EPS
            client_wins = ts > last_ts + EPS

            if concurrent:
                resolution = "client_wins" if client_wins else "server_wins"
                conflicts.append(
                    {
                        "mutation_id": mut_id,
                        "entity_type": entity["type"],
                        "entity_id": eid,
                        "field": None,
                        "client_value": "<deleted>",
                        "server_value": "<modified>",
                        "client_ts": ts,
                        "server_ts": last_ts,
                        "resolution": resolution,
                    }
                )
                if client_wins:
                    entity["deleted"] = True
                    entity["deleted_ts"] = ts
                    applied.append(_applied(mut_id, eid, "delete", None, None, ts))
                else:
                    rejected.append({"mutation_id": mut_id, "entity_id": eid, "reason": "server_wins"})
            else:
                entity["deleted"] = True
                entity["deleted_ts"] = ts
                applied.append(_applied(mut_id, eid, "delete", None, None, ts))

        else:
            raise SyncError(f"Operación desconocida: {op!r}")

    new_state = {"entities": entities}
    return {
        "applied": applied,
        "rejected": rejected,
        "conflicts": conflicts,
        "server_state": new_state,
        "server_ts": high_water_mark(new_state),
    }


def high_water_mark(state: dict) -> float:
    """Mayor timestamp presente en el estado (marca de agua para el próximo sync)."""
    hw = 0.0
    for ent in state.get("entities", {}).values():
        hw = max(hw, _entity_last_ts(ent))
    return hw


def _applied(mut_id, eid, op, field, value, ts) -> dict:
    return {
        "mutation_id": mut_id,
        "entity_id": eid,
        "op": op,
        "field": field,
        "value": value,
        "ts": ts,
    }


def _validate(m: dict) -> None:
    if "entity_id" not in m:
        raise SyncError("Mutación sin entity_id.")
    if "ts" not in m:
        raise SyncError("Mutación sin ts.")
    op = m.get("op", "set")
    if op == "set" and "field" not in m:
        raise SyncError("Mutación 'set' sin field.")
