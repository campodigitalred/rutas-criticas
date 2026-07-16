"""Pruebas del núcleo de carga y sobreasignación de recursos (Módulo D)."""
import pytest

from app.cpm import Dependency, Task
from app.resources import (
    Assignment,
    ResourceDef,
    compute_resource_load,
)
from app.resources.allocation import ResourceError


def test_overlapping_tasks_overallocate_shared_resource():
    # A y B sin dependencia -> ambas inician en el día 0 (se traslapan).
    tasks = [Task("A", 5), Task("B", 5)]
    deps = []
    resources = [ResourceDef("R1", "Brigada de campo", capacity_per_day=1)]
    assignments = [
        Assignment("A", "R1", units=1),
        Assignment("B", "R1", units=1),
    ]
    res = compute_resource_load(tasks, deps, resources, assignments)
    assert res.has_overallocation is True
    prof = res.profiles[0]
    assert prof.peak_load == 2          # dos tareas simultáneas
    # Días 0..4 sobreasignados.
    assert prof.overallocated_days[0]["day"] == 0
    assert len(prof.overallocated_days) == 5
    assert res.alerts[0]["windows"] == [{"start": 0, "end": 4}]


def test_sequential_tasks_do_not_overallocate():
    # A -> B (fin-inicio): no se traslapan.
    tasks = [Task("A", 5), Task("B", 5)]
    deps = [Dependency("A", "B")]
    resources = [ResourceDef("R1", "Brigada", capacity_per_day=1)]
    assignments = [Assignment("A", "R1", 1), Assignment("B", "R1", 1)]
    res = compute_resource_load(tasks, deps, resources, assignments)
    assert res.has_overallocation is False
    assert res.profiles[0].peak_load == 1
    assert res.alerts == []


def test_capacity_respected_no_alert():
    tasks = [Task("A", 5), Task("B", 5)]
    resources = [ResourceDef("R1", "Cuadrilla", capacity_per_day=2)]
    assignments = [Assignment("A", "R1", 1), Assignment("B", "R1", 1)]
    res = compute_resource_load(tasks, [], resources, assignments)
    # Carga pico 2 == capacidad 2 -> sin sobreasignación.
    assert res.has_overallocation is False
    assert res.profiles[0].peak_load == 2


def test_total_person_days():
    tasks = [Task("A", 4)]
    resources = [ResourceDef("R1", "Tecnico", capacity_per_day=1)]
    assignments = [Assignment("A", "R1", 1)]
    res = compute_resource_load(tasks, [], resources, assignments)
    assert res.profiles[0].total_person_days == 4


def test_multiple_resources_independent():
    tasks = [Task("A", 3), Task("B", 3)]
    resources = [
        ResourceDef("R1", "Persona", capacity_per_day=1),
        ResourceDef("R2", "Dron", capacity_per_day=1, kind="machinery"),
    ]
    assignments = [Assignment("A", "R1", 1), Assignment("B", "R2", 1)]
    res = compute_resource_load(tasks, [], resources, assignments)
    assert res.has_overallocation is False
    assert {p.resource_id for p in res.profiles} == {"R1", "R2"}


def test_non_consecutive_overallocation_windows():
    # Tres tareas: A y C comparten recurso y se traslapan con B en medio libre.
    tasks = [Task("A", 2), Task("B", 2), Task("C", 2)]
    deps = [Dependency("A", "B"), Dependency("B", "C")]
    # A[0,2], B[2,4], C[4,6]; asignamos R1 a A y C (no se traslapan) -> sin alerta.
    resources = [ResourceDef("R1", "R", capacity_per_day=1)]
    assignments = [Assignment("A", "R1", 1), Assignment("C", "R1", 1)]
    res = compute_resource_load(tasks, deps, resources, assignments)
    assert res.has_overallocation is False


def test_invalid_resource_reference():
    tasks = [Task("A", 3)]
    resources = [ResourceDef("R1", "R")]
    with pytest.raises(ResourceError):
        compute_resource_load(tasks, [], resources, [Assignment("A", "ZZZ", 1)])


def test_invalid_task_reference():
    tasks = [Task("A", 3)]
    resources = [ResourceDef("R1", "R")]
    with pytest.raises(ResourceError):
        compute_resource_load(tasks, [], resources, [Assignment("ZZZ", "R1", 1)])
