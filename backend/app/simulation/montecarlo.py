"""Simulación Monte Carlo de la ruta crítica (análisis de riesgo).

Para cada iteración se muestrea la duración de cada tarea desde una distribución
**Beta-PERT** (derivada de las estimaciones optimista/más-probable/pesimista) y se
corre el motor CPM. Con el conjunto de resultados se estima:

* La distribución de la duración total del proyecto (media, desviación, percentiles).
* La probabilidad de cumplir un plazo objetivo.
* El **índice de criticidad** de cada tarea (fracción de iteraciones en que la
  tarea cae en el camino crítico) — clave para detectar cuellos de botella
  "casi críticos" que un CPM determinista no revela.
* El impacto en el presupuesto (costo base + penalización por retraso).

Núcleo puro: usa solo la biblioteca estándar (`random`, `math`) para ser
verificable y reproducible (semilla), sin numpy.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..cpm import CPMEngine, Dependency, Task


class SimulationError(ValueError):
    """Datos de simulación inválidos."""


@dataclass
class SimTask:
    """Tarea con incertidumbre para la simulación.

    Si se dan las tres estimaciones PERT se muestrea; en caso contrario se usa
    ``duration`` como valor fijo (varianza cero).
    """

    id: str
    duration: float = 0.0
    optimistic: Optional[float] = None
    most_likely: Optional[float] = None
    pessimistic: Optional[float] = None
    cost: float = 0.0

    @property
    def has_spread(self) -> bool:
        return (
            self.optimistic is not None
            and self.most_likely is not None
            and self.pessimistic is not None
            and self.pessimistic > self.optimistic
        )

    def expected(self) -> float:
        if None not in (self.optimistic, self.most_likely, self.pessimistic):
            return (self.optimistic + 4 * self.most_likely + self.pessimistic) / 6.0
        return self.duration


def sample_pert(rng: random.Random, o: float, m: float, p: float, lam: float = 4.0) -> float:
    """Muestrea de una distribución Beta-PERT en [o, p] con moda ~ m.

    alpha = 1 + lam·(m−o)/(p−o) ; beta = 1 + lam·(p−m)/(p−o)
    """
    if p <= o:
        return o
    # Acotar la moda dentro del rango para evitar parámetros degenerados.
    m = min(max(m, o), p)
    alpha = 1 + lam * (m - o) / (p - o)
    beta = 1 + lam * (p - m) / (p - o)
    x = rng.betavariate(alpha, beta)
    return o + x * (p - o)


def _percentile(sorted_vals: List[float], q: float) -> float:
    """Percentil q∈[0,100] por interpolación lineal sobre datos ordenados."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (q / 100.0) * (len(sorted_vals) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_vals[int(rank)]
    frac = rank - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


@dataclass
class MonteCarloResult:
    iterations: int
    seed: Optional[int]
    baseline_duration: float
    mean: float
    std_dev: float
    min: float
    max: float
    percentiles: Dict[str, float]          # p10,p25,p50,p80,p90,p95
    probability_on_time: Optional[float]    # fracción <= target_duration
    target_duration: Optional[float]
    criticality_index: Dict[str, float]     # id -> fracción crítica
    histogram: List[dict]                    # bins para graficar
    expected_cost: Optional[float] = None
    cost_p80: Optional[float] = None


def run_montecarlo(
    tasks: List[SimTask],
    dependencies: List[Dependency],
    iterations: int = 2000,
    seed: Optional[int] = None,
    target_duration: Optional[float] = None,
    cost_per_day_delay: float = 0.0,
    histogram_bins: int = 20,
) -> MonteCarloResult:
    if not tasks:
        raise SimulationError("No hay tareas para simular.")
    if iterations < 1:
        raise SimulationError("iterations debe ser >= 1.")

    rng = random.Random(seed)

    # Línea base determinista (duraciones esperadas).
    base_engine = CPMEngine(
        [Task(id=t.id, duration=t.expected()) for t in tasks], dependencies
    )
    baseline = base_engine.compute()
    base_cost = sum(t.cost for t in tasks)

    durations: List[float] = []
    costs: List[float] = []
    crit_counts: Dict[str, int] = {t.id: 0 for t in tasks}

    for _ in range(iterations):
        sampled = []
        for t in tasks:
            if t.has_spread:
                d = sample_pert(rng, t.optimistic, t.most_likely, t.pessimistic)
            else:
                d = t.expected()
            sampled.append(Task(id=t.id, duration=d))
        result = CPMEngine(sampled, dependencies).compute()
        durations.append(result.project_duration)
        for tid in result.critical_path:
            crit_counts[tid] += 1
        if cost_per_day_delay or base_cost:
            delay = max(0.0, result.project_duration - baseline.project_duration)
            costs.append(base_cost + delay * cost_per_day_delay)

    durations_sorted = sorted(durations)
    n = len(durations)
    mean = sum(durations) / n
    variance = sum((d - mean) ** 2 for d in durations) / n
    std_dev = math.sqrt(variance)

    percentiles = {
        f"p{q}": round(_percentile(durations_sorted, q), 4)
        for q in (10, 25, 50, 80, 90, 95)
    }

    prob_on_time = None
    if target_duration is not None:
        prob_on_time = round(
            sum(1 for d in durations if d <= target_duration + 1e-9) / n, 4
        )

    criticality = {tid: round(c / n, 4) for tid, c in crit_counts.items()}

    histogram = _build_histogram(durations_sorted, histogram_bins)

    expected_cost = cost_p80 = None
    if costs:
        expected_cost = round(sum(costs) / len(costs), 2)
        cost_p80 = round(_percentile(sorted(costs), 80), 2)

    return MonteCarloResult(
        iterations=iterations,
        seed=seed,
        baseline_duration=round(baseline.project_duration, 4),
        mean=round(mean, 4),
        std_dev=round(std_dev, 4),
        min=round(durations_sorted[0], 4),
        max=round(durations_sorted[-1], 4),
        percentiles=percentiles,
        probability_on_time=prob_on_time,
        target_duration=target_duration,
        criticality_index=criticality,
        histogram=histogram,
        expected_cost=expected_cost,
        cost_p80=cost_p80,
    )


def _build_histogram(sorted_vals: List[float], bins: int) -> List[dict]:
    lo, hi = sorted_vals[0], sorted_vals[-1]
    if hi <= lo:
        return [{"start": round(lo, 2), "end": round(hi, 2), "count": len(sorted_vals)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in sorted_vals:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    return [
        {
            "start": round(lo + i * width, 2),
            "end": round(lo + (i + 1) * width, 2),
            "count": counts[i],
        }
        for i in range(bins)
    ]


# --------------------------------------------------------------------------- #
# (De)serialización para la API
# --------------------------------------------------------------------------- #
def run_montecarlo_from_dict(payload: dict) -> dict:
    tasks = [
        SimTask(
            id=str(t["id"]),
            duration=float(t.get("duration", 0) or 0),
            optimistic=_opt(t, "optimistic"),
            most_likely=_opt(t, "most_likely"),
            pessimistic=_opt(t, "pessimistic"),
            cost=float(t.get("cost", 0) or 0),
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
    r = run_montecarlo(
        tasks,
        deps,
        iterations=int(payload.get("iterations", 2000)),
        seed=payload.get("seed"),
        target_duration=payload.get("target_duration"),
        cost_per_day_delay=float(payload.get("cost_per_day_delay", 0) or 0),
        histogram_bins=int(payload.get("histogram_bins", 20)),
    )
    return {
        "iterations": r.iterations,
        "seed": r.seed,
        "baseline_duration": r.baseline_duration,
        "mean": r.mean,
        "std_dev": r.std_dev,
        "min": r.min,
        "max": r.max,
        "percentiles": r.percentiles,
        "probability_on_time": r.probability_on_time,
        "target_duration": r.target_duration,
        "criticality_index": r.criticality_index,
        "histogram": r.histogram,
        "expected_cost": r.expected_cost,
        "cost_p80": r.cost_p80,
    }


def _opt(d: dict, key: str) -> Optional[float]:
    v = d.get(key)
    return float(v) if v is not None else None
