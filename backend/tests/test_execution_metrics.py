"""Pruebas del núcleo de métricas de ejecución (Módulo C — Kanban)."""
import pytest

from app.cpm import Dependency
from app.execution import (
    ExecutionTask,
    compute_execution_summary,
)
from app.execution.metrics import ExecutionError


def _diamond(statuses):
    """Red en diamante A->(B,C)->D. Camino crítico A-B-D, duración 12.

    statuses: dict id -> (status, progress_pct)
    """
    durs = {"A": 3, "B": 4, "C": 2, "D": 5}
    tasks = [
        ExecutionTask(id=tid, duration=durs[tid], status=statuses[tid][0], progress_pct=statuses[tid][1])
        for tid in "ABCD"
    ]
    deps = [
        Dependency("A", "B"), Dependency("A", "C"),
        Dependency("B", "D"), Dependency("C", "D"),
    ]
    return tasks, deps


def test_all_todo_not_started():
    tasks, deps = _diamond({"A": ("todo", 0), "B": ("todo", 0), "C": ("todo", 0), "D": ("todo", 0)})
    s = compute_execution_summary(tasks, deps)
    assert s.overall_progress == 0
    assert s.critical_progress == 0
    assert s.health == "not_started"
    assert s.critical_path == ["A", "B", "D"]
    assert s.project_duration == 12


def test_weighted_overall_and_critical_progress():
    # A y B terminadas, C sin iniciar, D al 40%.
    tasks, deps = _diamond({"A": ("done", 100), "B": ("done", 100), "C": ("todo", 0), "D": ("in_progress", 40)})
    s = compute_execution_summary(tasks, deps)
    # global ponderado: (3*100 + 4*100 + 2*0 + 5*40) / 14 = 900/14
    assert s.overall_progress == pytest.approx(64.29, abs=0.01)
    # camino crítico A,B,D: (3*100 + 4*100 + 5*40) / 12 = 900/12 = 75
    assert s.critical_progress == pytest.approx(75.0, abs=0.01)


def test_status_counts_and_blocked():
    tasks, deps = _diamond({"A": ("done", 100), "B": ("blocked", 20), "C": ("in_progress", 50), "D": ("todo", 0)})
    s = compute_execution_summary(tasks, deps)
    assert s.status_counts == {"todo": 1, "in_progress": 1, "blocked": 1, "done": 1}
    assert s.blocked_count == 1
    # B es crítica y está bloqueada.
    assert s.critical_blocked is True


def test_critical_blocked_forces_at_risk():
    tasks, deps = _diamond({"A": ("done", 100), "B": ("blocked", 30), "C": ("done", 100), "D": ("todo", 0)})
    s = compute_execution_summary(tasks, deps)  # sin as_of_day
    assert s.health == "at_risk"


def test_planned_progress_on_track():
    # Al día 7: A,B,C deberían estar completas y D por iniciar (planeado ~64.29%).
    tasks, deps = _diamond({"A": ("done", 100), "B": ("done", 100), "C": ("done", 100), "D": ("todo", 0)})
    s = compute_execution_summary(tasks, deps, as_of_day=7)
    assert s.planned_progress == pytest.approx(64.29, abs=0.01)
    assert s.overall_progress == pytest.approx(64.29, abs=0.01)
    assert s.schedule_variance_pct == pytest.approx(0.0, abs=0.01)
    assert s.health == "on_track"


def test_behind_when_actual_below_planned():
    tasks, deps = _diamond({"A": ("done", 100), "B": ("in_progress", 25), "C": ("todo", 0), "D": ("todo", 0)})
    s = compute_execution_summary(tasks, deps, as_of_day=7)
    # real (28.57) muy por debajo de lo planeado (64.29) -> atrasado.
    assert s.overall_progress == pytest.approx(28.57, abs=0.01)
    assert s.schedule_variance_pct < -15
    assert s.health == "behind"


def test_done_when_all_complete():
    tasks, deps = _diamond({"A": ("done", 100), "B": ("done", 100), "C": ("done", 100), "D": ("done", 100)})
    s = compute_execution_summary(tasks, deps, as_of_day=12)
    assert s.overall_progress == 100
    assert s.health == "done"


def test_done_status_normalizes_progress_to_100():
    # 'done' con progress_pct bajo se normaliza a 100.
    t = ExecutionTask(id="X", duration=5, status="done", progress_pct=10)
    assert t.progress_pct == 100.0


def test_invalid_status_rejected():
    with pytest.raises(ExecutionError):
        ExecutionTask(id="X", duration=5, status="pausado", progress_pct=0)


def test_invalid_progress_rejected():
    with pytest.raises(ExecutionError):
        ExecutionTask(id="X", duration=5, status="in_progress", progress_pct=150)


def test_summary_from_dict_roundtrip():
    from app.execution import summary_from_dict

    payload = {
        "tasks": [
            {"id": "A", "duration": 3, "status": "done", "progress_pct": 100},
            {"id": "B", "duration": 4, "status": "in_progress", "progress_pct": 50},
            {"id": "C", "duration": 2, "status": "todo", "progress_pct": 0},
            {"id": "D", "duration": 5, "status": "todo", "progress_pct": 0},
        ],
        "dependencies": [
            {"predecessor": "A", "successor": "B"},
            {"predecessor": "A", "successor": "C"},
            {"predecessor": "B", "successor": "D"},
            {"predecessor": "C", "successor": "D"},
        ],
        "as_of_day": 5,
    }
    out = summary_from_dict(payload)
    assert out["total_tasks"] == 4
    assert out["critical_path"] == ["A", "B", "D"]
    assert 0 < out["overall_progress"] < 100
    assert out["health"] in {"on_track", "at_risk", "behind", "in_progress", "not_started"}
