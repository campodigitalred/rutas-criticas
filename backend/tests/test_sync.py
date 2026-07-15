"""Pruebas del motor de sincronización offline (last-write-wins a nivel de campo)."""
import pytest

from app.sync import apply_mutations, empty_state, high_water_mark
from app.sync.engine import SyncError


def _state_with(entity_id, field, value, ts, etype="task"):
    return {
        "entities": {
            entity_id: {
                "id": entity_id,
                "type": etype,
                "deleted": False,
                "deleted_ts": 0.0,
                "fields": {field: {"value": value, "ts": ts}},
            }
        }
    }


def _set(mid, eid, field, value, ts, base_ts=0.0, etype="task"):
    return {
        "mutation_id": mid,
        "entity_type": etype,
        "entity_id": eid,
        "op": "set",
        "field": field,
        "value": value,
        "ts": ts,
        "base_ts": base_ts,
    }


def test_clean_apply_on_empty_state():
    muts = [_set("m1", "T1", "status", "in_progress", ts=100)]
    res = apply_mutations(empty_state(), muts)
    assert len(res["applied"]) == 1
    assert res["conflicts"] == []
    assert res["server_state"]["entities"]["T1"]["fields"]["status"]["value"] == "in_progress"
    assert res["server_ts"] == 100


def test_clean_apply_when_field_unchanged_since_base():
    # Servidor tiene status@ts=50; el cliente basó su edición en ts=50 (sin cambio ajeno).
    state = _state_with("T1", "status", "todo", ts=50)
    muts = [_set("m1", "T1", "status", "done", ts=120, base_ts=50)]
    res = apply_mutations(state, muts)
    assert len(res["applied"]) == 1
    assert res["conflicts"] == []
    assert res["server_state"]["entities"]["T1"]["fields"]["status"]["value"] == "done"


def test_conflict_client_wins_by_lww():
    # El servidor cambió el campo a ts=80 (después de la base=50); el cliente edita a ts=120.
    state = _state_with("T1", "progress_pct", 40, ts=80)
    muts = [_set("m1", "T1", "progress_pct", 90, ts=120, base_ts=50)]
    res = apply_mutations(state, muts)
    assert len(res["conflicts"]) == 1
    c = res["conflicts"][0]
    assert c["resolution"] == "client_wins"
    assert c["server_value"] == 40 and c["client_value"] == 90
    # Aplicado porque el cliente es más nuevo.
    assert res["server_state"]["entities"]["T1"]["fields"]["progress_pct"]["value"] == 90
    assert len(res["applied"]) == 1


def test_conflict_server_wins_by_lww():
    # El servidor cambió a ts=200 (después de base=50); el cliente edita más viejo a ts=120.
    state = _state_with("T1", "progress_pct", 70, ts=200)
    muts = [_set("m1", "T1", "progress_pct", 30, ts=120, base_ts=50)]
    res = apply_mutations(state, muts)
    assert len(res["conflicts"]) == 1
    assert res["conflicts"][0]["resolution"] == "server_wins"
    # No se aplica; gana el servidor.
    assert res["server_state"]["entities"]["T1"]["fields"]["progress_pct"]["value"] == 70
    assert res["applied"] == []
    assert res["rejected"][0]["reason"] == "server_wins"


def test_stale_mutation_without_conflict_is_rejected():
    # base_ts == server_ts (sin cambio ajeno) pero el cliente es más viejo -> stale.
    state = _state_with("T1", "status", "done", ts=100)
    muts = [_set("m1", "T1", "status", "todo", ts=90, base_ts=100)]
    res = apply_mutations(state, muts)
    assert res["conflicts"] == []
    assert res["applied"] == []
    assert res["rejected"][0]["reason"] == "stale"
    assert res["server_state"]["entities"]["T1"]["fields"]["status"]["value"] == "done"


def test_field_level_independence():
    # Cambio ajeno en 'status' no debe provocar conflicto al editar 'progress_pct'.
    state = {
        "entities": {
            "T1": {
                "id": "T1", "type": "task", "deleted": False, "deleted_ts": 0.0,
                "fields": {
                    "status": {"value": "in_progress", "ts": 90},
                    "progress_pct": {"value": 20, "ts": 40},
                },
            }
        }
    }
    muts = [_set("m1", "T1", "progress_pct", 60, ts=100, base_ts=40)]
    res = apply_mutations(state, muts)
    assert res["conflicts"] == []
    assert res["server_state"]["entities"]["T1"]["fields"]["progress_pct"]["value"] == 60
    # 'status' intacto.
    assert res["server_state"]["entities"]["T1"]["fields"]["status"]["value"] == "in_progress"


def test_mutations_applied_in_ts_order():
    muts = [
        _set("m2", "T1", "status", "done", ts=200, base_ts=0),
        _set("m1", "T1", "status", "in_progress", ts=100, base_ts=0),
    ]
    res = apply_mutations(empty_state(), muts)
    # La última por ts (done@200) prevalece.
    assert res["server_state"]["entities"]["T1"]["fields"]["status"]["value"] == "done"


def test_delete_conflict_client_wins():
    # Alguien modificó la tarea (ts=80) después de la base; el borrado es más nuevo (ts=150).
    state = _state_with("T1", "status", "in_progress", ts=80)
    muts = [{"mutation_id": "d1", "entity_type": "task", "entity_id": "T1", "op": "delete", "ts": 150, "base_ts": 50}]
    res = apply_mutations(state, muts)
    assert len(res["conflicts"]) == 1
    assert res["conflicts"][0]["resolution"] == "client_wins"
    assert res["server_state"]["entities"]["T1"]["deleted"] is True


def test_does_not_mutate_input_state():
    state = _state_with("T1", "status", "todo", ts=50)
    original = state["entities"]["T1"]["fields"]["status"]["value"]
    apply_mutations(state, [_set("m1", "T1", "status", "done", ts=120, base_ts=50)])
    assert state["entities"]["T1"]["fields"]["status"]["value"] == original


def test_high_water_mark():
    state = _state_with("T1", "status", "done", ts=175)
    assert high_water_mark(state) == 175


def test_invalid_mutation_raises():
    with pytest.raises(SyncError):
        apply_mutations(empty_state(), [{"entity_id": "T1", "op": "set", "ts": 10}])  # sin field
    with pytest.raises(SyncError):
        apply_mutations(empty_state(), [{"entity_id": "T1", "op": "explode", "ts": 10, "field": "x", "value": 1}])
