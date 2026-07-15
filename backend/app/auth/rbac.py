"""Control de acceso basado en roles (RBAC) de Campo Crítico.

Roles: ``admin`` (gestión total), ``director`` (dirige proyectos), ``consultor``
(planifica y edita), ``aliado`` (aliado rural: lectura + ejecución de tareas en
campo). Cada rol tiene un conjunto de permisos; los endpoints exigen permisos.
"""
from __future__ import annotations

from typing import Dict, Set

ROLES = ("admin", "director", "consultor", "aliado")

# Permisos atómicos.
P_PROJECT_READ = "project:read"
P_PROJECT_WRITE = "project:write"
P_PROJECT_DELETE = "project:delete"
P_TASK_WRITE = "task:write"
P_TASK_EXECUTE = "task:execute"      # avanzar estado/porcentaje en campo
P_DEPENDENCY_WRITE = "dependency:write"
P_RESOURCE_WRITE = "resource:write"
P_REPORT_READ = "report:read"
P_USER_MANAGE = "user:manage"

_CONSULTOR: Set[str] = {
    P_PROJECT_READ, P_PROJECT_WRITE, P_TASK_WRITE, P_TASK_EXECUTE,
    P_DEPENDENCY_WRITE, P_RESOURCE_WRITE, P_REPORT_READ,
}
_DIRECTOR: Set[str] = _CONSULTOR | {P_PROJECT_DELETE, P_USER_MANAGE}
_ALIADO: Set[str] = {P_PROJECT_READ, P_TASK_EXECUTE, P_REPORT_READ}
_ADMIN: Set[str] = _DIRECTOR | {P_PROJECT_DELETE, P_USER_MANAGE}

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "admin": _ADMIN,
    "director": _DIRECTOR,
    "consultor": _CONSULTOR,
    "aliado": _ALIADO,
}


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def permissions_for(role: str) -> Set[str]:
    return set(ROLE_PERMISSIONS.get(role, set()))
