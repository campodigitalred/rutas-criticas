"""Pruebas de la simulación Monte Carlo (Módulo D)."""
import pytest

from app.cpm import Dependency
from app.simulation import SimTask, run_montecarlo
from app.simulation.montecarlo import SimulationError, sample_pert
import random


def _diamond():
    tasks = [
        SimTask("A", optimistic=2, most_likely=3, pessimistic=4),
        SimTask("B", optimistic=3, most_likely=4, pessimistic=5),
        SimTask("C", optimistic=1, most_likely=2, pessimistic=3),
        SimTask("D", optimistic=4, most_likely=5, pessimistic=6),
    ]
    deps = [
        Dependency("A", "B"), Dependency("A", "C"),
        Dependency("B", "D"), Dependency("C", "D"),
    ]
    return tasks, deps


def test_sample_pert_within_bounds():
    rng = random.Random(1)
    for _ in range(1000):
        v = sample_pert(rng, 2, 5, 10)
        assert 2 <= v <= 10


def test_sample_pert_degenerate_range():
    rng = random.Random(1)
    assert sample_pert(rng, 5, 5, 5) == 5


def test_reproducible_with_seed():
    tasks, deps = _diamond()
    a = run_montecarlo(tasks, deps, iterations=1000, seed=42)
    b = run_montecarlo(tasks, deps, iterations=1000, seed=42)
    assert a.mean == b.mean
    assert a.percentiles == b.percentiles
    assert a.criticality_index == b.criticality_index


def test_different_seeds_differ():
    tasks, deps = _diamond()
    a = run_montecarlo(tasks, deps, iterations=1000, seed=1)
    b = run_montecarlo(tasks, deps, iterations=1000, seed=2)
    assert a.mean != b.mean


def test_fixed_durations_have_zero_variance():
    tasks = [SimTask("A", duration=3), SimTask("B", duration=4)]
    deps = [Dependency("A", "B")]
    r = run_montecarlo(tasks, deps, iterations=500, seed=1)
    assert r.std_dev == 0
    assert r.min == r.max == r.baseline_duration == 7


def test_percentiles_are_ordered():
    tasks, deps = _diamond()
    r = run_montecarlo(tasks, deps, iterations=2000, seed=7)
    p = r.percentiles
    assert p["p10"] <= p["p25"] <= p["p50"] <= p["p80"] <= p["p90"] <= p["p95"]
    assert r.min <= p["p10"]
    assert p["p95"] <= r.max


def test_mean_close_to_baseline():
    tasks, deps = _diamond()
    r = run_montecarlo(tasks, deps, iterations=5000, seed=7)
    # La media simulada debe rondar la duración base (PERT esperado).
    assert r.mean == pytest.approx(r.baseline_duration, abs=1.0)


def test_criticality_index_diamond():
    tasks, deps = _diamond()
    r = run_montecarlo(tasks, deps, iterations=3000, seed=7)
    ci = r.criticality_index
    # A (único inicio) y D (único fin) están en todos los caminos => siempre críticos.
    assert ci["A"] == 1.0
    assert ci["D"] == 1.0
    # La rama B (más larga) es crítica con más frecuencia que la rama C.
    assert ci["B"] > ci["C"]


def test_linear_chain_all_critical():
    tasks = [
        SimTask("A", optimistic=2, most_likely=3, pessimistic=6),
        SimTask("B", optimistic=1, most_likely=2, pessimistic=4),
    ]
    deps = [Dependency("A", "B")]
    r = run_montecarlo(tasks, deps, iterations=1000, seed=3)
    assert r.criticality_index["A"] == 1.0
    assert r.criticality_index["B"] == 1.0


def test_probability_on_time_monotonic():
    tasks, deps = _diamond()
    r_low = run_montecarlo(tasks, deps, iterations=2000, seed=7, target_duration=5)
    r_high = run_montecarlo(tasks, deps, iterations=2000, seed=7, target_duration=100)
    assert r_low.probability_on_time <= r_high.probability_on_time
    assert r_high.probability_on_time == 1.0
    assert 0.0 <= r_low.probability_on_time <= 1.0


def test_budget_impact():
    tasks = [
        SimTask("A", optimistic=2, most_likely=3, pessimistic=8, cost=1000),
        SimTask("B", optimistic=2, most_likely=4, pessimistic=10, cost=2000),
    ]
    deps = [Dependency("A", "B")]
    r = run_montecarlo(tasks, deps, iterations=2000, seed=7, cost_per_day_delay=500)
    assert r.expected_cost is not None
    # El costo esperado debe ser >= costo base (3000) por la penalización de retraso.
    assert r.expected_cost >= 3000
    assert r.cost_p80 >= r.expected_cost - 1  # p80 no menor que la media (dist. sesgada)


def test_histogram_counts_sum_to_iterations():
    tasks, deps = _diamond()
    r = run_montecarlo(tasks, deps, iterations=1500, seed=7, histogram_bins=15)
    assert sum(b["count"] for b in r.histogram) == 1500


def test_empty_tasks_raise():
    with pytest.raises(SimulationError):
        run_montecarlo([], [], iterations=100)
