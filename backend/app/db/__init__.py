"""Capa de persistencia de Campo Crítico.

Acceso a datos real mediante ``sqlite3`` (verificable sin dependencias externas)
con la misma interfaz de repositorios apta para PostgreSQL en producción.
"""
from .database import Database, get_database, new_id, utcnow
from .repository import (
    CpmResultRepository,
    DependencyRepository,
    NotFound,
    OrganizationRepository,
    ProjectRepository,
    RepositoryError,
    ResourceRepository,
    ScenarioRepository,
    TaskRepository,
    UserRepository,
)
from .service import (
    apply_sync_to_db,
    build_snapshot,
    create_project_with_wbs,
    recompute_and_store_cpm,
)

__all__ = [
    "Database",
    "get_database",
    "new_id",
    "utcnow",
    "OrganizationRepository",
    "UserRepository",
    "ProjectRepository",
    "TaskRepository",
    "DependencyRepository",
    "ResourceRepository",
    "ScenarioRepository",
    "CpmResultRepository",
    "RepositoryError",
    "NotFound",
    "create_project_with_wbs",
    "recompute_and_store_cpm",
    "build_snapshot",
    "apply_sync_to_db",
]
