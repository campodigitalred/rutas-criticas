"""Métricas de ejecución para el tablero Kanban.

Toma la red de tareas (con estado y avance) + dependencias, corre el motor
CPM/PERT internamente para conocer el camino crítico y las fechas tempranas, y
calcula un resumen de salud del proyecto.

Es núcleo puro (dataclasses, sin dependencias externas) para ser verificable
sin conexión, igual que el motor CPM y el asistente IA.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..cpm import CPMEngine, Dependency, Task

VALID_STATUS = {"todo", "in_progress", "blocked", "done"}

# Tolerancias (en puntos porcentuales) para la señal de salud a partir de la
# varianza de cronograma (avance real - avance planeado).
_ON_TRACK_TOLERANCE = -5.0
_AT_RISK_TOLERANCE = -15.0


class ExecutionError(ValueError):
    """Datos de ejecución inválidos (estado desconocido, avance fuera de rango)."""


@dataclass
class ExecutionTask:
    id: str
    duration: float
    progress_pct: float = 0.0
    status: str = "todo"

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUS:
            raise ExecutionError(f"Estado inválido en {self.id}: {self.status!r}")
        if not (0 <= self.progress_pct <= 100):
            raise ExecutionError(f"progress_pct fuera de rango en {self.id}: {self.progress_pct}")
        # Normalización: 'done' implica 100%; 'todo' sin avance implica 0%.
        if self.status == "done":
            self.progress_pct = 100.0
        if self.status == "todo" and self.progress_pct == 0:
            self.progress_pct = 0.0

    @property
    def effective_duration(self) -> float:
        # Los hitos (duración 0) pesan un mínimo para no desaparecer del promedio.
        return self.duration if self.duration > 0 else 0.0


@dataclass
class ExecutionSummary:
    total_tasks: int
    status_counts: Dict[str, int]
    overall_progress: float          # % avance real, ponderado por duración
    critical_progress: float          # % avance del camino crítico
    blocked_count: int
    critical_blocked: bool            # ¿hay alguna tarea crítica bloqueada?
    project_duration: float
    critical_path: List[str]
    as_of_day: Optional[float] = None
    planned_progress: Optional[float] = None       # % que "debería" llevar a la fecha
    schedule_variance_pct: Optional[float] = None   # real - planeado
    health: str = "not_started"       # not_started|on_track|at_risk|behind|done


def _weighted_progress(items: List[tuple]) -> float:
    """items: lista de (duración, progreso_pct). Devuelve promedio ponderado."""
    total = sum(d for d, _ in items)
    if total <= 0:
        # Sin duración (p.ej. solo hitos): promedio simple.
        return round(sum(p for _, p in items) / len(items), 2) if items else 0.0
    return round(sum(d * p for d, p in items) / total, 2)


def compute_execution_summary(
    tasks: List[ExecutionTask],
    dependencies: List[Dependency],
    as_of_day: Optional[float] = None,
) -> ExecutionSummary:
    if not tasks:
        raise ExecutionError("No hay tareas para evaluar la ejecución.")

    # 1. Correr CPM para obtener camino crítico y fechas tempranas.
    engine_tasks = [Task(id=t.id, duration=t.duration) for t in tasks]
    result = CPMEngine(engine_tasks, dependencies).compute()
    by_id = {t.id: t for t in tasks}
    critical_set = set(result.critical_path)

    # 2. Conteos por estado.
    status_counts = {s: 0 for s in VALID_STATUS}
    for t in tasks:
        status_counts[t.status] += 1
    blocked_count = status_counts["blocked"]
    critical_blocked = any(
        by_id[tid].status == "blocked" for tid in critical_set if tid in by_id
    )

    # 3. Avance real (ponderado por duración) global y del camino crítico.
    overall = _weighted_progress([(t.duration, t.progress_pct) for t in tasks])
    crit_items = [
        (by_id[tid].duration, by_id[tid].progress_pct)
        for tid in critical_set
        if tid in by_id
    ]
    critical = _weighted_progress(crit_items) if crit_items else 0.0

    # 4. Avance planeado a la fecha (si se da as_of_day) y varianza de cronograma.
    planned: Optional[float] = None
    variance: Optional[float] = None
    if as_of_day is not None:
        planned_items = []
        for t in tasks:
            r = result.tasks[t.id]
            dur = r.duration
            if dur <= 0:
                # Hito: planeado 100% si ya pasó su fecha.
                pct = 100.0 if as_of_day >= r.early_finish else 0.0
            else:
                pct = max(0.0, min(1.0, (as_of_day - r.early_start) / dur)) * 100.0
            planned_items.append((t.duration, pct))
        planned = _weighted_progress(planned_items)
        variance = round(overall - planned, 2)

    # 5. Señal de salud.
    health = _health(overall, variance, critical_blocked)

    return ExecutionSummary(
        total_tasks=len(tasks),
        status_counts=status_counts,
        overall_progress=overall,
        critical_progress=critical,
        blocked_count=blocked_count,
        critical_blocked=critical_blocked,
        project_duration=result.project_duration,
        critical_path=result.critical_path,
        as_of_day=as_of_day,
        planned_progress=planned,
        schedule_variance_pct=variance,
        health=health,
    )


def _health(overall: float, variance: Optional[float], critical_blocked: bool) -> str:
    if overall >= 100:
        return "done"
    if critical_blocked:
        # Una tarea crítica bloqueada es siempre, al menos, un riesgo.
        if variance is None or variance >= _AT_RISK_TOLERANCE:
            return "at_risk"
        return "behind"
    if variance is None:
        return "in_progress" if overall > 0 else "not_started"
    if variance >= _ON_TRACK_TOLERANCE:
        return "on_track"
    if variance >= _AT_RISK_TOLERANCE:
        return "at_risk"
    return "behind"


# --------------------------------------------------------------------------- #
# (De)serialización para la API / frontend
# --------------------------------------------------------------------------- #
def summary_from_dict(payload: dict) -> dict:
    """Recibe el JSON de /execution/summary y devuelve el resumen serializable."""
    tasks = [
        ExecutionTask(
            id=str(t["id"]),
            duration=float(t.get("duration", 0) or 0),
            progress_pct=float(t.get("progress_pct", 0) or 0),
            status=str(t.get("status", "todo")),
        )
        for t in payload.get("tasks", [])
    ]
    deps = [
        Dependency(
            predecessor=str(d["predecessor"]),
            successor=str(d["successor"]),
            dep_type=str(d.get("dep_type", "FS")),
            lag=float(d.get("lag", 0) or 0),
        )
        for d in payload.get("dependencies", [])
    ]
    as_of = payload.get("as_of_day")
    as_of = float(as_of) if as_of is not None else None
    s = compute_execution_summary(tasks, deps, as_of)
    return {
        "total_tasks": s.total_tasks,
        "status_counts": s.status_counts,
        "overall_progress": s.overall_progress,
        "critical_progress": s.critical_progress,
        "blocked_count": s.blocked_count,
        "critical_blocked": s.critical_blocked,
        "project_duration": s.project_duration,
        "critical_path": s.critical_path,
        "as_of_day": s.as_of_day,
        "planned_progress": s.planned_progress,
        "schedule_variance_pct": s.schedule_variance_pct,
        "health": s.health,
    }
