"""Servicios de persistencia: unen los repositorios con los núcleos verificados.

* Crear un proyecto a partir de una EDT (tareas + dependencias) del asistente IA.
* Recalcular la ruta crítica (motor CPM) y **persistir** los resultados.
* Construir el snapshot de sincronización desde la BD y aplicar la cola offline
  (motor de sync) persistiendo los cambios de campo en las tareas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from ..cpm import CPMEngine, Dependency, Task
from ..sync import apply_mutations
from .database import Database
from .repository import (
    CpmResultRepository,
    DependencyRepository,
    ProjectRepository,
    ScenarioRepository,
    TaskRepository,
)

# Campos de tarea sincronizables vía mutaciones offline.
_SYNCABLE_FIELDS = {"status", "progress_pct", "name", "duration_days"}
_FIELD_ALIASES = {"duration": "duration_days"}


def _iso_to_ts(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
def create_project_with_wbs(
    db: Database,
    organization_id: str,
    name: str,
    tasks: List[dict],
    dependencies: List[dict],
    **project_opts,
) -> dict:
    """Crea un proyecto con su EDT y una línea base. Devuelve ids y mapeo temp→db.

    ``tasks``: [{temp_id|id, name, duration_days|duration, optimistic_days?, ...}]
    ``dependencies``: [{predecessor, successor, dep_type?, lag_days|lag?}]
    """
    projects = ProjectRepository(db)
    task_repo = TaskRepository(db)
    deps = DependencyRepository(db)
    scenarios = ScenarioRepository(db)

    project = projects.create(organization_id, name, **project_opts)
    pid = project["id"]

    id_map: Dict[str, str] = {}
    for t in tasks:
        temp = str(t.get("temp_id") or t.get("id"))
        created = task_repo.create(
            pid,
            name=t.get("name", temp),
            description=t.get("description"),
            duration_days=t.get("duration_days", t.get("duration", 0)) or 0,
            optimistic_days=t.get("optimistic_days", t.get("optimistic")),
            most_likely_days=t.get("most_likely_days", t.get("most_likely")),
            pessimistic_days=t.get("pessimistic_days", t.get("pessimistic")),
            cost_estimated=t.get("cost_estimated", t.get("planned_cost", 0)) or 0,
            is_milestone=t.get("is_milestone", False),
            wbs_code=t.get("wbs_code"),
        )
        id_map[temp] = created["id"]

    for d in dependencies:
        pre = id_map.get(str(d["predecessor"]))
        suc = id_map.get(str(d["successor"]))
        if pre and suc:
            deps.create(pid, pre, suc, d.get("dep_type", "FS"),
                        d.get("lag_days", d.get("lag", 0)) or 0)

    baseline = scenarios.ensure_baseline(pid)
    return {"project": project, "baseline_scenario_id": baseline["id"], "id_map": id_map}


def recompute_and_store_cpm(db: Database, project_id: str, scenario_id: Optional[str] = None) -> dict:
    """Corre el motor CPM sobre las tareas/dependencias persistidas y guarda el resultado."""
    task_repo = TaskRepository(db)
    dep_repo = DependencyRepository(db)
    scenarios = ScenarioRepository(db)
    cpm_repo = CpmResultRepository(db)

    tasks = task_repo.list(project_id)
    deps = dep_repo.list(project_id)

    engine_tasks = [
        Task(
            id=t["id"],
            duration=t["duration_days"] or 0,
            optimistic=t["optimistic_days"],
            most_likely=t["most_likely_days"],
            pessimistic=t["pessimistic_days"],
        )
        for t in tasks
    ]
    engine_deps = [
        Dependency(d["predecessor_id"], d["successor_id"], d["dep_type"], d["lag_days"])
        for d in deps
    ]
    result = CPMEngine(engine_tasks, engine_deps).compute()

    scenario = (
        scenarios.get(scenario_id) if scenario_id else scenarios.ensure_baseline(project_id)
    )
    rows = [
        {
            "task_id": tid,
            "early_start": r.early_start, "early_finish": r.early_finish,
            "late_start": r.late_start, "late_finish": r.late_finish,
            "total_slack": r.total_slack, "free_slack": r.free_slack,
            "is_critical": r.is_critical,
            "pert_expected": r.pert_expected, "pert_variance": r.pert_variance,
        }
        for tid, r in result.tasks.items()
    ]
    cpm_repo.replace_for_scenario(scenario["id"], rows)
    return {
        "scenario_id": scenario["id"],
        "project_duration": result.project_duration,
        "critical_path": result.critical_path,
        "pert_std_dev": result.pert_std_dev,
        "results": rows,
    }


def build_snapshot(db: Database, project_id: str) -> dict:
    """Construye el ``server_state`` de sincronización desde las tareas persistidas."""
    tasks = TaskRepository(db).list(project_id)
    entities = {}
    for t in tasks:
        ts = _iso_to_ts(t["updated_at"])
        fields = {
            "status": {"value": t["status"], "ts": ts},
            "progress_pct": {"value": t["progress_pct"], "ts": ts},
            "name": {"value": t["name"], "ts": ts},
            "duration_days": {"value": t["duration_days"], "ts": ts},
        }
        entities[t["id"]] = {
            "id": t["id"], "type": "task", "deleted": False, "deleted_ts": 0.0, "fields": fields,
        }
    return {"entities": entities}


def apply_sync_to_db(db: Database, project_id: str, mutations: List[dict]) -> dict:
    """Aplica la cola de mutaciones offline y persiste los cambios en las tareas."""
    task_repo = TaskRepository(db)
    snapshot = build_snapshot(db, project_id)
    result = apply_mutations(snapshot, mutations)

    # Persistir cada mutación aplicada de tipo 'set' en su tarea.
    pending: Dict[str, dict] = {}
    for a in result["applied"]:
        if a["op"] != "set":
            continue
        field = _FIELD_ALIASES.get(a["field"], a["field"])
        if field not in _SYNCABLE_FIELDS:
            continue
        pending.setdefault(a["entity_id"], {})[field] = a["value"]

    for task_id, fields in pending.items():
        if task_repo.get(task_id):
            task_repo.update(task_id, **fields)

    return result
