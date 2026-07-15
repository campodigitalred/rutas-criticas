"""Pruebas del motor CPM/PERT."""
import math

import pytest

from app.cpm import CPMEngine, CPMError, Dependency, Task


def _engine(tasks, deps):
    return CPMEngine(tasks, deps)


def test_classic_diamond_network_fs():
    """Red clásica en diamante A->(B,C)->D. Camino crítico A-B-D = 12."""
    tasks = [Task("A", 3), Task("B", 4), Task("C", 2), Task("D", 5)]
    deps = [
        Dependency("A", "B", "FS"),
        Dependency("A", "C", "FS"),
        Dependency("B", "D", "FS"),
        Dependency("C", "D", "FS"),
    ]
    res = _engine(tasks, deps).compute()

    assert res.project_duration == 12
    assert res.critical_path == ["A", "B", "D"]

    a, b, c, d = (res.tasks[x] for x in "ABCD")
    assert (a.early_start, a.early_finish) == (0, 3)
    assert (b.early_start, b.early_finish) == (3, 7)
    assert (c.early_start, c.early_finish) == (3, 5)
    assert (d.early_start, d.early_finish) == (7, 12)

    # C tiene 2 días de holgura; el resto es crítico.
    assert c.total_slack == 2
    assert c.is_critical is False
    assert a.is_critical and b.is_critical and d.is_critical
    assert a.total_slack == 0 and d.total_slack == 0


def test_linear_chain():
    tasks = [Task("T1", 5), Task("T2", 10), Task("T3", 3)]
    deps = [Dependency("T1", "T2"), Dependency("T2", "T3")]
    res = _engine(tasks, deps).compute()
    assert res.project_duration == 18
    assert res.critical_path == ["T1", "T2", "T3"]
    assert all(res.tasks[t].is_critical for t in ("T1", "T2", "T3"))


def test_fs_lag():
    """Lag positivo en FS retrasa el sucesor."""
    tasks = [Task("A", 4), Task("B", 6)]
    deps = [Dependency("A", "B", "FS", lag=2)]
    res = _engine(tasks, deps).compute()
    assert res.tasks["B"].early_start == 6   # EF(A)=4 + lag 2
    assert res.project_duration == 12


def test_start_to_start_with_lag():
    """SS con lag: B empieza 3 días después de que empieza A."""
    tasks = [Task("A", 10), Task("B", 4)]
    deps = [Dependency("A", "B", "SS", lag=3)]
    res = _engine(tasks, deps).compute()
    assert res.tasks["B"].early_start == 3
    assert res.tasks["B"].early_finish == 7
    # A domina la duración total (0..10).
    assert res.project_duration == 10


def test_finish_to_finish():
    """FF: B no puede terminar antes que A."""
    tasks = [Task("A", 8), Task("B", 3)]
    deps = [Dependency("A", "B", "FF")]
    res = _engine(tasks, deps).compute()
    assert res.tasks["A"].early_finish == 8
    assert res.tasks["B"].early_finish == 8   # empujado por FF
    assert res.tasks["B"].early_start == 5     # 8 - duración 3
    assert res.project_duration == 8


def test_start_to_finish():
    """SF (poco común): el fin del sucesor no puede ser antes del inicio del predecesor + lag."""
    tasks = [Task("A", 5), Task("B", 4)]
    deps = [Dependency("A", "B", "SF", lag=6)]
    res = _engine(tasks, deps).compute()
    # ES(A)=0, lag 6 -> EF(B) >= 6 -> ES(B) >= 2
    assert res.tasks["B"].early_finish == 6
    assert res.tasks["B"].early_start == 2


def test_cycle_detection():
    tasks = [Task("A", 1), Task("B", 1)]
    deps = [Dependency("A", "B"), Dependency("B", "A")]
    with pytest.raises(CPMError):
        _engine(tasks, deps).compute()


def test_invalid_dependency_reference():
    tasks = [Task("A", 1)]
    deps = [Dependency("A", "Z")]
    with pytest.raises(CPMError):
        _engine(tasks, deps).compute()


def test_pert_expected_and_variance():
    """PERT: te=(o+4m+p)/6, var=((p-o)/6)^2. Probabilidad sobre normal."""
    tasks = [
        Task("A", optimistic=2, most_likely=4, pessimistic=6),   # te=4, var=(4/6)^2
        Task("B", optimistic=3, most_likely=6, pessimistic=15),  # te=7, var=(12/6)^2=4
    ]
    deps = [Dependency("A", "B", "FS")]
    res = _engine(tasks, deps).compute()

    assert res.tasks["A"].pert_expected == pytest.approx(4.0)
    assert res.tasks["B"].pert_expected == pytest.approx(7.0)
    assert res.project_duration == pytest.approx(11.0)
    # Varianza del proyecto = suma sobre el camino crítico (A y B).
    expected_var = (4 / 6) ** 2 + (12 / 6) ** 2
    assert res.pert_variance == pytest.approx(expected_var, abs=1e-4)
    # Probabilidad de terminar exactamente en la media = 0.5.
    assert res.probability_of_meeting(11.0) == pytest.approx(0.5, abs=1e-6)
    assert res.probability_of_meeting(100.0) > 0.99


def test_free_slack():
    """En el diamante, C tiene holgura total y libre = 2."""
    tasks = [Task("A", 3), Task("B", 4), Task("C", 2), Task("D", 5)]
    deps = [
        Dependency("A", "B"), Dependency("A", "C"),
        Dependency("B", "D"), Dependency("C", "D"),
    ]
    res = _engine(tasks, deps).compute()
    assert res.tasks["C"].free_slack == 2
    assert res.tasks["A"].free_slack == 0
