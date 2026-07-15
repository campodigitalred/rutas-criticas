"""Carga de recursos y detección de sobreasignación.

A partir de la red de tareas (posicionadas en su inicio temprano por el motor
CPM), las asignaciones tarea→recurso y la capacidad diaria de cada recurso,
construye un histograma de carga por día y detecta los días en que un recurso
queda **sobreasignado** (carga > capacidad) — p.ej. la misma brigada de campo
asignada a dos levantamientos que se traslapan.

Núcleo puro (dataclasses + stdlib), verificable sin conexión.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List

from ..cpm import CPMEngine, Dependency, Task


class ResourceError(ValueError):
    """Datos de recursos inválidos."""


@dataclass
class ResourceDef:
    id: str
    name: str
    capacity_per_day: float = 1.0
    cost_per_day: float = 0.0
    kind: str = "person"  # person | machinery | material


@dataclass
class Assignment:
    task_id: str
    resource_id: str
    units: float = 1.0  # unidades/día que consume la tarea de ese recurso


@dataclass
class ResourceProfile:
    resource_id: str
    name: str
    capacity_per_day: float
    peak_load: float
    load_by_day: List[float]              # carga por día [0..horizon)
    overallocated_days: List[dict]         # [{day, load, capacity, over}]
    total_person_days: float


@dataclass
class ResourceLoadResult:
    horizon_days: int
    project_duration: float
    profiles: List[ResourceProfile]
    alerts: List[dict]                     # resumen accionable de sobreasignación
    has_overallocation: bool


def _active_days(early_start: float, early_finish: float, horizon: int) -> range:
    """Días enteros [ES, EF) en que la tarea está activa."""
    start = int(math.floor(early_start + 1e-9))
    end = int(math.ceil(early_finish - 1e-9))
    return range(max(0, start), min(max(start, end), horizon))


def compute_resource_load(
    tasks: List[Task],
    dependencies: List[Dependency],
    resources: List[ResourceDef],
    assignments: List[Assignment],
) -> ResourceLoadResult:
    if not tasks:
        raise ResourceError("No hay tareas para calcular la carga de recursos.")

    result = CPMEngine(tasks, dependencies).compute()
    res_by_id = {r.id: r for r in resources}
    for a in assignments:
        if a.resource_id not in res_by_id:
            raise ResourceError(f"Asignación a recurso inexistente: {a.resource_id}")
        if a.task_id not in result.tasks:
            raise ResourceError(f"Asignación a tarea inexistente: {a.task_id}")

    horizon = max(1, int(math.ceil(result.project_duration)))

    # Carga diaria por recurso.
    load: Dict[str, List[float]] = {r.id: [0.0] * horizon for r in resources}
    for a in assignments:
        tr = result.tasks[a.task_id]
        for day in _active_days(tr.early_start, tr.early_finish, horizon):
            load[a.resource_id][day] += a.units

    profiles: List[ResourceProfile] = []
    alerts: List[dict] = []
    for r in resources:
        daily = load[r.id]
        over_days = [
            {
                "day": d,
                "load": round(daily[d], 4),
                "capacity": r.capacity_per_day,
                "over": round(daily[d] - r.capacity_per_day, 4),
            }
            for d in range(horizon)
            if daily[d] > r.capacity_per_day + 1e-9
        ]
        peak = max(daily) if daily else 0.0
        profiles.append(
            ResourceProfile(
                resource_id=r.id,
                name=r.name,
                capacity_per_day=r.capacity_per_day,
                peak_load=round(peak, 4),
                load_by_day=[round(x, 4) for x in daily],
                overallocated_days=over_days,
                total_person_days=round(sum(daily), 4),
            )
        )
        if over_days:
            windows = _group_windows([d["day"] for d in over_days])
            alerts.append(
                {
                    "resource_id": r.id,
                    "resource_name": r.name,
                    "peak_load": round(peak, 4),
                    "capacity_per_day": r.capacity_per_day,
                    "overallocated_day_count": len(over_days),
                    "windows": windows,
                    "message": (
                        f"{r.name} sobreasignado: pico {round(peak, 2)} vs capacidad "
                        f"{r.capacity_per_day} en {len(over_days)} día(s)."
                    ),
                }
            )

    return ResourceLoadResult(
        horizon_days=horizon,
        project_duration=round(result.project_duration, 4),
        profiles=profiles,
        alerts=alerts,
        has_overallocation=bool(alerts),
    )


def _group_windows(days: List[int]) -> List[dict]:
    """Agrupa días consecutivos en ventanas {start, end}."""
    if not days:
        return []
    days = sorted(days)
    windows = []
    start = prev = days[0]
    for d in days[1:]:
        if d == prev + 1:
            prev = d
        else:
            windows.append({"start": start, "end": prev})
            start = prev = d
    windows.append({"start": start, "end": prev})
    return windows


# --------------------------------------------------------------------------- #
# (De)serialización para la API
# --------------------------------------------------------------------------- #
def resource_load_from_dict(payload: dict) -> dict:
    tasks = [
        Task(
            id=str(t["id"]),
            duration=float(t.get("duration", 0) or 0),
            optimistic=_opt(t, "optimistic"),
            most_likely=_opt(t, "most_likely"),
            pessimistic=_opt(t, "pessimistic"),
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
    resources = [
        ResourceDef(
            id=str(r["id"]),
            name=str(r.get("name", r["id"])),
            capacity_per_day=float(r.get("capacity_per_day", 1) or 1),
            cost_per_day=float(r.get("cost_per_day", 0) or 0),
            kind=str(r.get("kind", "person")),
        )
        for r in payload.get("resources", [])
    ]
    assignments = [
        Assignment(
            task_id=str(a["task_id"]),
            resource_id=str(a["resource_id"]),
            units=float(a.get("units", 1) or 1),
        )
        for a in payload.get("assignments", [])
    ]
    r = compute_resource_load(tasks, deps, resources, assignments)
    return {
        "horizon_days": r.horizon_days,
        "project_duration": r.project_duration,
        "has_overallocation": r.has_overallocation,
        "alerts": r.alerts,
        "profiles": [
            {
                "resource_id": p.resource_id,
                "name": p.name,
                "capacity_per_day": p.capacity_per_day,
                "peak_load": p.peak_load,
                "load_by_day": p.load_by_day,
                "overallocated_days": p.overallocated_days,
                "total_person_days": p.total_person_days,
            }
            for p in r.profiles
        ],
    }


def _opt(d: dict, key: str):
    v = d.get(key)
    return float(v) if v is not None else None
