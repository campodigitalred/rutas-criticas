"""Repositorios de acceso a datos (patrón Repository) sobre SQLite.

Cada repositorio encapsula el CRUD de una entidad con consultas parametrizadas
(sin interpolación de cadenas → sin inyección SQL). Devuelven ``dict`` planos.
La misma interfaz es válida contra PostgreSQL cambiando el conector.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .database import Database, new_id, row_to_dict, rows_to_dicts, utcnow


class RepositoryError(Exception):
    """Error de acceso a datos (no encontrado, violación de restricción)."""


class NotFound(RepositoryError):
    pass


class _BaseRepo:
    def __init__(self, db: Database):
        self.db = db

    def _insert(self, table: str, data: Dict[str, Any]) -> None:
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        self.db.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            tuple(data.values()),
        )

    def _update(self, table: str, entity_id: str, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE {table} SET {sets} WHERE id = ?",
            (*fields.values(), entity_id),
        )


# --------------------------------------------------------------------------- #
class OrganizationRepository(_BaseRepo):
    def create(self, name: str, org_id: Optional[str] = None) -> dict:
        oid = org_id or new_id()
        self._insert("organization", {"id": oid, "name": name, "created_at": utcnow()})
        self.db.commit()
        return self.get(oid)

    def get(self, org_id: str) -> Optional[dict]:
        return row_to_dict(self.db.execute("SELECT * FROM organization WHERE id = ?", (org_id,)).fetchone())

    def list(self) -> List[dict]:
        return rows_to_dicts(self.db.execute("SELECT * FROM organization ORDER BY created_at").fetchall())


class UserRepository(_BaseRepo):
    def create(self, organization_id: str, email: str, full_name: str,
               role: str = "consultor", password_hash: Optional[str] = None) -> dict:
        uid = new_id()
        self._insert("app_user", {
            "id": uid, "organization_id": organization_id, "email": email,
            "full_name": full_name, "role": role, "password_hash": password_hash,
            "created_at": utcnow(),
        })
        self.db.commit()
        return self.get(uid)

    def get(self, user_id: str) -> Optional[dict]:
        return row_to_dict(self.db.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone())

    def get_by_email(self, email: str) -> Optional[dict]:
        return row_to_dict(self.db.execute("SELECT * FROM app_user WHERE email = ?", (email,)).fetchone())

    def list(self, organization_id: str) -> List[dict]:
        return rows_to_dicts(self.db.execute(
            "SELECT * FROM app_user WHERE organization_id = ? ORDER BY full_name", (organization_id,)
        ).fetchall())


class ProjectRepository(_BaseRepo):
    _UPDATABLE = {"name", "objective", "budget_estimated", "currency",
                  "deadline_hard", "start_date", "status", "owner_id"}

    def create(self, organization_id: str, name: str, **opts) -> dict:
        pid = new_id()
        now = utcnow()
        row = {
            "id": pid, "organization_id": organization_id, "name": name,
            "owner_id": opts.get("owner_id"),
            "objective": opts.get("objective"),
            "budget_estimated": opts.get("budget_estimated"),
            "currency": opts.get("currency", "MXN"),
            "deadline_hard": opts.get("deadline_hard"),
            "start_date": opts.get("start_date"),
            "status": opts.get("status", "draft"),
            "created_at": now, "updated_at": now,
        }
        self._insert("project", row)
        self.db.commit()
        return self.get(pid)

    def get(self, project_id: str) -> Optional[dict]:
        return row_to_dict(self.db.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone())

    def list(self, organization_id: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
        clauses, params = [], []
        if organization_id:
            clauses.append("organization_id = ?"); params.append(organization_id)
        if status:
            clauses.append("status = ?"); params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return rows_to_dicts(self.db.execute(
            f"SELECT * FROM project {where} ORDER BY created_at DESC", tuple(params)
        ).fetchall())

    def update(self, project_id: str, **fields) -> dict:
        if self.get(project_id) is None:
            raise NotFound(f"Proyecto no encontrado: {project_id}")
        allowed = {k: v for k, v in fields.items() if k in self._UPDATABLE}
        allowed["updated_at"] = utcnow()
        self._update("project", project_id, allowed)
        self.db.commit()
        return self.get(project_id)

    def delete(self, project_id: str) -> None:
        self.db.execute("DELETE FROM project WHERE id = ?", (project_id,))
        self.db.commit()


class TaskRepository(_BaseRepo):
    _UPDATABLE = {"name", "description", "duration_days", "optimistic_days",
                  "most_likely_days", "pessimistic_days", "cost_estimated",
                  "progress_pct", "status", "is_milestone", "wbs_code", "parent_id"}

    def create(self, project_id: str, name: str, task_id: Optional[str] = None, **opts) -> dict:
        tid = task_id or new_id()
        now = utcnow()
        row = {
            "id": tid, "project_id": project_id, "parent_id": opts.get("parent_id"),
            "wbs_code": opts.get("wbs_code"), "name": name,
            "description": opts.get("description"),
            "duration_days": opts.get("duration_days", 0),
            "optimistic_days": opts.get("optimistic_days"),
            "most_likely_days": opts.get("most_likely_days"),
            "pessimistic_days": opts.get("pessimistic_days"),
            "cost_estimated": opts.get("cost_estimated", 0),
            "progress_pct": opts.get("progress_pct", 0),
            "status": opts.get("status", "todo"),
            "is_milestone": 1 if opts.get("is_milestone") else 0,
            "created_at": now, "updated_at": now,
        }
        self._insert("task", row)
        self.db.commit()
        return self.get(tid)

    def get(self, task_id: str) -> Optional[dict]:
        return row_to_dict(self.db.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone())

    def list(self, project_id: str) -> List[dict]:
        return rows_to_dicts(self.db.execute(
            "SELECT * FROM task WHERE project_id = ? ORDER BY created_at", (project_id,)
        ).fetchall())

    def update(self, task_id: str, **fields) -> dict:
        if self.get(task_id) is None:
            raise NotFound(f"Tarea no encontrada: {task_id}")
        allowed = {k: v for k, v in fields.items() if k in self._UPDATABLE}
        if "is_milestone" in allowed:
            allowed["is_milestone"] = 1 if allowed["is_milestone"] else 0
        allowed["updated_at"] = utcnow()
        self._update("task", task_id, allowed)
        self.db.commit()
        return self.get(task_id)

    def delete(self, task_id: str) -> None:
        self.db.execute("DELETE FROM task WHERE id = ?", (task_id,))
        self.db.commit()


class DependencyRepository(_BaseRepo):
    def create(self, project_id: str, predecessor_id: str, successor_id: str,
               dep_type: str = "FS", lag_days: float = 0.0) -> dict:
        did = new_id()
        self._insert("task_dependency", {
            "id": did, "project_id": project_id, "predecessor_id": predecessor_id,
            "successor_id": successor_id, "dep_type": dep_type, "lag_days": lag_days,
        })
        self.db.commit()
        return self.get(did)

    def get(self, dep_id: str) -> Optional[dict]:
        return row_to_dict(self.db.execute("SELECT * FROM task_dependency WHERE id = ?", (dep_id,)).fetchone())

    def list(self, project_id: str) -> List[dict]:
        return rows_to_dicts(self.db.execute(
            "SELECT * FROM task_dependency WHERE project_id = ?", (project_id,)
        ).fetchall())

    def delete(self, dep_id: str) -> None:
        self.db.execute("DELETE FROM task_dependency WHERE id = ?", (dep_id,))
        self.db.commit()


class ResourceRepository(_BaseRepo):
    def create(self, organization_id: str, name: str, kind: str = "person",
               capacity_per_day: float = 1.0, cost_per_day: float = 0.0,
               skills: Optional[str] = None) -> dict:
        rid = new_id()
        self._insert("resource", {
            "id": rid, "organization_id": organization_id, "name": name, "kind": kind,
            "capacity_per_day": capacity_per_day, "cost_per_day": cost_per_day, "skills": skills,
        })
        self.db.commit()
        return self.get(rid)

    def get(self, resource_id: str) -> Optional[dict]:
        return row_to_dict(self.db.execute("SELECT * FROM resource WHERE id = ?", (resource_id,)).fetchone())

    def list(self, organization_id: str) -> List[dict]:
        return rows_to_dicts(self.db.execute(
            "SELECT * FROM resource WHERE organization_id = ? ORDER BY name", (organization_id,)
        ).fetchall())

    def assign(self, task_id: str, resource_id: str, units: float = 1.0,
               allocation_pct: float = 100.0) -> dict:
        aid = new_id()
        self._insert("task_assignment", {
            "id": aid, "task_id": task_id, "resource_id": resource_id,
            "units": units, "allocation_pct": allocation_pct,
        })
        self.db.commit()
        return row_to_dict(self.db.execute("SELECT * FROM task_assignment WHERE id = ?", (aid,)).fetchone())

    def assignments_by_project(self, project_id: str) -> List[dict]:
        return rows_to_dicts(self.db.execute(
            """SELECT ta.* FROM task_assignment ta
               JOIN task t ON t.id = ta.task_id
               WHERE t.project_id = ?""",
            (project_id,),
        ).fetchall())


class ScenarioRepository(_BaseRepo):
    def create(self, project_id: str, name: str, is_baseline: bool = False,
               params: Optional[str] = None) -> dict:
        sid = new_id()
        self._insert("scenario", {
            "id": sid, "project_id": project_id, "name": name,
            "is_baseline": 1 if is_baseline else 0, "params": params, "created_at": utcnow(),
        })
        self.db.commit()
        return self.get(sid)

    def get(self, scenario_id: str) -> Optional[dict]:
        return row_to_dict(self.db.execute("SELECT * FROM scenario WHERE id = ?", (scenario_id,)).fetchone())

    def list(self, project_id: str) -> List[dict]:
        return rows_to_dicts(self.db.execute(
            "SELECT * FROM scenario WHERE project_id = ? ORDER BY created_at", (project_id,)
        ).fetchall())

    def get_baseline(self, project_id: str) -> Optional[dict]:
        return row_to_dict(self.db.execute(
            "SELECT * FROM scenario WHERE project_id = ? AND is_baseline = 1", (project_id,)
        ).fetchone())

    def ensure_baseline(self, project_id: str) -> dict:
        existing = self.get_baseline(project_id)
        return existing or self.create(project_id, "Línea base", is_baseline=True)


class CpmResultRepository(_BaseRepo):
    def replace_for_scenario(self, scenario_id: str, results: List[dict]) -> None:
        """Reemplaza todos los resultados CPM de un escenario (recálculo)."""
        self.db.execute("DELETE FROM cpm_result WHERE scenario_id = ?", (scenario_id,))
        now = utcnow()
        for r in results:
            self._insert("cpm_result", {
                "id": new_id(), "scenario_id": scenario_id, "task_id": r["task_id"],
                "early_start": r.get("early_start"), "early_finish": r.get("early_finish"),
                "late_start": r.get("late_start"), "late_finish": r.get("late_finish"),
                "total_slack": r.get("total_slack"), "free_slack": r.get("free_slack"),
                "is_critical": 1 if r.get("is_critical") else 0,
                "pert_expected": r.get("pert_expected"), "pert_variance": r.get("pert_variance"),
                "computed_at": now,
            })
        self.db.commit()

    def list(self, scenario_id: str) -> List[dict]:
        return rows_to_dicts(self.db.execute(
            "SELECT * FROM cpm_result WHERE scenario_id = ?", (scenario_id,)
        ).fetchall())
