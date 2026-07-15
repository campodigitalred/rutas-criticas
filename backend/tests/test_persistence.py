"""Pruebas de la capa de persistencia (repositorios + servicios sobre SQLite real)."""
import pytest

from app.db import (
    Database,
    DependencyRepository,
    NotFound,
    OrganizationRepository,
    ProjectRepository,
    ResourceRepository,
    ScenarioRepository,
    TaskRepository,
    apply_sync_to_db,
    build_snapshot,
    create_project_with_wbs,
    recompute_and_store_cpm,
)
from app.db.repository import CpmResultRepository


@pytest.fixture()
def db():
    database = Database(":memory:")
    database.init_schema()
    yield database
    database.close()


@pytest.fixture()
def org(db):
    return OrganizationRepository(db).create("Agencia Campo Digital")


# ------------------------------- CRUD básico ------------------------------- #
def test_schema_initializes_tables(db):
    names = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"organization", "project", "task", "task_dependency", "cpm_result"} <= names


def test_project_crud(db, org):
    repo = ProjectRepository(db)
    p = repo.create(org["id"], "Censo Norte", objective="Digitalizar censo", budget_estimated=500000)
    assert p["id"] and p["status"] == "draft"
    assert repo.get(p["id"])["name"] == "Censo Norte"
    updated = repo.update(p["id"], status="planning", name="Censo Norte 2025")
    assert updated["status"] == "planning" and updated["name"] == "Censo Norte 2025"
    assert len(repo.list(org["id"])) == 1
    repo.delete(p["id"])
    assert repo.get(p["id"]) is None


def test_update_missing_raises(db, org):
    with pytest.raises(NotFound):
        ProjectRepository(db).update("nope", status="closed")


def test_cascade_delete_removes_tasks(db, org):
    projects = ProjectRepository(db)
    tasks = TaskRepository(db)
    p = projects.create(org["id"], "P")
    tasks.create(p["id"], "T1", duration_days=5)
    tasks.create(p["id"], "T2", duration_days=3)
    assert len(tasks.list(p["id"])) == 2
    projects.delete(p["id"])
    # ON DELETE CASCADE (PRAGMA foreign_keys=ON) elimina las tareas.
    assert tasks.list(p["id"]) == []


def test_dependency_self_loop_rejected(db, org):
    projects = ProjectRepository(db)
    tasks = TaskRepository(db)
    deps = DependencyRepository(db)
    p = projects.create(org["id"], "P")
    t = tasks.create(p["id"], "T1", duration_days=2)
    with pytest.raises(Exception):
        deps.create(p["id"], t["id"], t["id"])  # CHECK predecessor <> successor


def test_task_progress_check_constraint(db, org):
    projects = ProjectRepository(db)
    tasks = TaskRepository(db)
    p = projects.create(org["id"], "P")
    with pytest.raises(Exception):
        tasks.create(p["id"], "T1", duration_days=2, progress_pct=150)


def test_resource_assignment(db, org):
    projects = ProjectRepository(db)
    tasks = TaskRepository(db)
    res = ResourceRepository(db)
    p = projects.create(org["id"], "P")
    t = tasks.create(p["id"], "Levantamiento", duration_days=10)
    r = res.create(org["id"], "Brigada", capacity_per_day=1)
    res.assign(t["id"], r["id"], units=1)
    assignments = res.assignments_by_project(p["id"])
    assert len(assignments) == 1 and assignments[0]["resource_id"] == r["id"]


# --------------------------- Servicios integrados -------------------------- #
def _wbs():
    tasks = [
        {"temp_id": "A", "name": "Diseño", "duration_days": 3},
        {"temp_id": "B", "name": "Campo", "duration_days": 4},
        {"temp_id": "C", "name": "Datos", "duration_days": 2},
        {"temp_id": "D", "name": "Cierre", "duration_days": 5},
    ]
    deps = [
        {"predecessor": "A", "successor": "B"},
        {"predecessor": "A", "successor": "C"},
        {"predecessor": "B", "successor": "D"},
        {"predecessor": "C", "successor": "D"},
    ]
    return tasks, deps


def test_create_project_with_wbs(db, org):
    tasks, deps = _wbs()
    out = create_project_with_wbs(db, org["id"], "Diamante", tasks, deps)
    pid = out["project"]["id"]
    assert len(TaskRepository(db).list(pid)) == 4
    assert len(DependencyRepository(db).list(pid)) == 4
    assert out["baseline_scenario_id"]
    # El mapeo temp->db permite resolver dependencias.
    assert set(out["id_map"].keys()) == {"A", "B", "C", "D"}


def test_recompute_and_store_cpm_persists_results(db, org):
    tasks, deps = _wbs()
    out = create_project_with_wbs(db, org["id"], "Diamante", tasks, deps)
    pid = out["project"]["id"]
    res = recompute_and_store_cpm(db, pid)
    # Diamante clásico A-B-D = 12 (mismos valores que las pruebas del motor).
    assert res["project_duration"] == 12
    id_map = out["id_map"]
    crit_ids = set(res["critical_path"])
    assert {id_map["A"], id_map["B"], id_map["D"]} == crit_ids
    # Persistidos en cpm_result.
    stored = CpmResultRepository(db).list(res["scenario_id"])
    assert len(stored) == 4
    critical_stored = [r for r in stored if r["is_critical"]]
    assert len(critical_stored) == 3


def test_snapshot_and_sync_persist_changes(db, org):
    tasks, deps = _wbs()
    out = create_project_with_wbs(db, org["id"], "Diamante", tasks, deps)
    pid = out["project"]["id"]
    task_a = out["id_map"]["A"]

    snap = build_snapshot(db, pid)
    assert task_a in snap["entities"]
    assert snap["entities"][task_a]["fields"]["status"]["value"] == "todo"

    # Mutación offline: A pasa a in_progress al 50% (ts alto -> gana).
    muts = [
        {"mutation_id": "m1", "entity_type": "task", "entity_id": task_a,
         "op": "set", "field": "status", "value": "in_progress", "ts": 9_999_999_999, "base_ts": 0},
        {"mutation_id": "m2", "entity_type": "task", "entity_id": task_a,
         "op": "set", "field": "progress_pct", "value": 50, "ts": 9_999_999_999, "base_ts": 0},
    ]
    result = apply_sync_to_db(db, pid, muts)
    assert len(result["applied"]) == 2
    # Los cambios quedaron persistidos en la tarea.
    persisted = TaskRepository(db).get(task_a)
    assert persisted["status"] == "in_progress"
    assert persisted["progress_pct"] == 50


def test_sync_conflict_server_wins_not_persisted(db, org):
    tasks, deps = _wbs()
    out = create_project_with_wbs(db, org["id"], "Diamante", tasks, deps)
    pid = out["project"]["id"]
    task_a = out["id_map"]["A"]

    # base_ts=0 pero el servidor tiene ts>0 (updated_at) -> concurrente.
    snap = build_snapshot(db, pid)
    server_ts = snap["entities"][task_a]["fields"]["status"]["ts"]
    assert server_ts > 0
    # Mutación con ts anterior al del servidor -> gana el servidor, no se persiste.
    muts = [{"mutation_id": "m1", "entity_type": "task", "entity_id": task_a,
             "op": "set", "field": "status", "value": "done", "ts": server_ts - 100, "base_ts": 0}]
    result = apply_sync_to_db(db, pid, muts)
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["resolution"] == "server_wins"
    assert TaskRepository(db).get(task_a)["status"] == "todo"  # sin cambios


def test_persistence_across_reconnect(tmp_path):
    # Verifica persistencia real en archivo: cerrar y reabrir conserva los datos.
    path = str(tmp_path / "campo.db")
    db1 = Database(path)
    db1.init_schema()
    org = OrganizationRepository(db1).create("Campo")
    p = ProjectRepository(db1).create(org["id"], "Persistente")
    db1.close()

    db2 = Database(path)
    reopened = ProjectRepository(db2).get(p["id"])
    assert reopened is not None and reopened["name"] == "Persistente"
    db2.close()
