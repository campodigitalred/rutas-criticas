"""Módulo D — Gestión de recursos de Campo Crítico.

Calcula el perfil de carga diaria por recurso (personal / maquinaria) a partir
del cronograma temprano (CPM) y detecta la sobreasignación.
"""
from .allocation import (
    Assignment,
    ResourceDef,
    ResourceLoadResult,
    compute_resource_load,
    resource_load_from_dict,
)

__all__ = [
    "Assignment",
    "ResourceDef",
    "ResourceLoadResult",
    "compute_resource_load",
    "resource_load_from_dict",
]
