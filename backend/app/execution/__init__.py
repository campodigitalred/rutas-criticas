"""Módulo C — Seguimiento de ejecución (Kanban) de Campo Crítico.

Núcleo de métricas de ejecución: a partir del estado y avance de las tareas
(más el cálculo CPM de la red) produce un resumen accionable para el tablero
Kanban: % de avance ponderado por duración, avance del camino crítico, conteos
por estado, avance planeado a la fecha y una señal de salud del proyecto.
"""
from .metrics import (
    VALID_STATUS,
    ExecutionSummary,
    ExecutionTask,
    compute_execution_summary,
    summary_from_dict,
)

__all__ = [
    "VALID_STATUS",
    "ExecutionSummary",
    "ExecutionTask",
    "compute_execution_summary",
    "summary_from_dict",
]
