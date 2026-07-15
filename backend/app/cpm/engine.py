"""Motor CPM/PERT — núcleo de cálculo de Rutas Críticas de Campo Crítico.

Implementa:
  * Pase hacia adelante (Early Start / Early Finish).
  * Pase hacia atrás (Late Start / Late Finish).
  * Holgura total (total slack) y holgura libre (free slack).
  * Identificación del camino crítico (holgura total == 0).
  * Dependencias generalizadas: FS, SS, FF, SF con lag/lead.
  * Estadística PERT: valor esperado, varianza y probabilidad de cumplir una meta.

El motor es puro (sin dependencias de I/O ni de framework) para poder reutilizarse
tanto en el backend FastAPI como en pruebas y, potencialmente, compilarse a WASM.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

DependencyType = str  # "FS" | "SS" | "FF" | "SF"
VALID_DEP_TYPES = {"FS", "SS", "FF", "SF"}


class CPMError(Exception):
    """Error de dominio del motor CPM (ciclo, referencia inválida, etc.)."""


@dataclass
class Task:
    id: str
    duration: float = 0.0
    # Estimaciones PERT de tres puntos (opcionales). Si están presentes y no se
    # entrega `duration`, la duración esperada se deriva de ellas.
    optimistic: Optional[float] = None
    most_likely: Optional[float] = None
    pessimistic: Optional[float] = None

    def expected_duration(self) -> float:
        """Duración esperada. Usa PERT (o+4m+p)/6 si hay tres puntos."""
        if None not in (self.optimistic, self.most_likely, self.pessimistic):
            return (self.optimistic + 4 * self.most_likely + self.pessimistic) / 6.0
        return self.duration

    def variance(self) -> float:
        """Varianza PERT ((p - o)/6)^2, o 0 si no hay estimación de tres puntos."""
        if None not in (self.optimistic, self.pessimistic):
            return ((self.pessimistic - self.optimistic) / 6.0) ** 2
        return 0.0


@dataclass
class Dependency:
    predecessor: str
    successor: str
    dep_type: DependencyType = "FS"
    lag: float = 0.0

    def __post_init__(self) -> None:
        if self.dep_type not in VALID_DEP_TYPES:
            raise CPMError(f"Tipo de dependencia inválido: {self.dep_type!r}")


@dataclass
class TaskResult:
    id: str
    duration: float
    early_start: float = 0.0
    early_finish: float = 0.0
    late_start: float = 0.0
    late_finish: float = 0.0
    total_slack: float = 0.0
    free_slack: float = 0.0
    is_critical: bool = False
    pert_expected: float = 0.0
    pert_variance: float = 0.0


@dataclass
class CPMResult:
    project_duration: float
    critical_path: List[str]
    tasks: Dict[str, TaskResult] = field(default_factory=dict)
    pert_variance: float = 0.0          # varianza del proyecto (suma sobre camino crítico)
    pert_std_dev: float = 0.0

    def probability_of_meeting(self, target_duration: float) -> float:
        """Probabilidad (0..1) de terminar en <= target_duration segun PERT (normal)."""
        if self.pert_std_dev <= 0:
            return 1.0 if target_duration >= self.project_duration else 0.0
        z = (target_duration - self.project_duration) / self.pert_std_dev
        # CDF normal estándar mediante la función error.
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class CPMEngine:
    """Calcula la ruta crítica de una red de tareas con dependencias generalizadas."""

    def __init__(self, tasks: Iterable[Task], dependencies: Iterable[Dependency]):
        self.tasks: Dict[str, Task] = {t.id: t for t in tasks}
        self.dependencies: List[Dependency] = list(dependencies)
        self._validate()
        # Adyacencias: sucesores y predecesores por tarea.
        self._successors: Dict[str, List[Dependency]] = {tid: [] for tid in self.tasks}
        self._predecessors: Dict[str, List[Dependency]] = {tid: [] for tid in self.tasks}
        for dep in self.dependencies:
            self._successors[dep.predecessor].append(dep)
            self._predecessors[dep.successor].append(dep)

    # ------------------------------------------------------------------ #
    # Validación
    # ------------------------------------------------------------------ #
    def _validate(self) -> None:
        for dep in self.dependencies:
            if dep.predecessor not in self.tasks:
                raise CPMError(f"Dependencia refiere predecesor inexistente: {dep.predecessor}")
            if dep.successor not in self.tasks:
                raise CPMError(f"Dependencia refiere sucesor inexistente: {dep.successor}")

    def _topological_order(self) -> List[str]:
        """Orden topológico (Kahn). Lanza CPMError si hay ciclo."""
        indegree: Dict[str, int] = {tid: 0 for tid in self.tasks}
        for dep in self.dependencies:
            indegree[dep.successor] += 1
        queue = deque(sorted(t for t, d in indegree.items() if d == 0))
        order: List[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for dep in self._successors[node]:
                indegree[dep.successor] -= 1
                if indegree[dep.successor] == 0:
                    queue.append(dep.successor)
        if len(order) != len(self.tasks):
            remaining = [t for t in self.tasks if t not in order]
            raise CPMError(f"El grafo de dependencias contiene un ciclo: {remaining}")
        return order

    # ------------------------------------------------------------------ #
    # Cálculo
    # ------------------------------------------------------------------ #
    def compute(self) -> CPMResult:
        order = self._topological_order()
        dur = {tid: self.tasks[tid].expected_duration() for tid in self.tasks}

        es: Dict[str, float] = {tid: 0.0 for tid in self.tasks}
        ef: Dict[str, float] = {tid: 0.0 for tid in self.tasks}

        # ---- Pase hacia adelante -------------------------------------- #
        for tid in order:
            start = 0.0
            for dep in self._predecessors[tid]:
                p = dep.predecessor
                d_j = dur[tid]
                if dep.dep_type == "FS":       # EF_p + lag <= ES_j
                    candidate = ef[p] + dep.lag
                elif dep.dep_type == "SS":     # ES_p + lag <= ES_j
                    candidate = es[p] + dep.lag
                elif dep.dep_type == "FF":     # EF_p + lag <= EF_j -> ES_j = EF_p + lag - d_j
                    candidate = ef[p] + dep.lag - d_j
                else:                          # SF: ES_p + lag <= EF_j -> ES_j = ES_p + lag - d_j
                    candidate = es[p] + dep.lag - d_j
                start = max(start, candidate)
            es[tid] = start
            ef[tid] = start + dur[tid]

        project_duration = max(ef.values()) if ef else 0.0

        # ---- Pase hacia atrás ----------------------------------------- #
        lf: Dict[str, float] = {tid: project_duration for tid in self.tasks}
        ls: Dict[str, float] = {tid: project_duration for tid in self.tasks}
        for tid in reversed(order):
            d_i = dur[tid]
            succ = self._successors[tid]
            if not succ:
                lf[tid] = project_duration
            else:
                finish = math.inf
                for dep in succ:
                    s = dep.successor
                    if dep.dep_type == "FS":     # EF_i + lag <= ES_s -> LF_i = LS_s - lag
                        candidate = ls[s] - dep.lag
                    elif dep.dep_type == "SS":   # ES_i + lag <= ES_s -> LS_i = LS_s - lag
                        candidate = (ls[s] - dep.lag) + d_i     # convertir LS_i -> LF_i
                    elif dep.dep_type == "FF":   # EF_i + lag <= EF_s -> LF_i = LF_s - lag
                        candidate = lf[s] - dep.lag
                    else:                        # SF: ES_i + lag <= EF_s -> LS_i = LF_s - lag
                        candidate = (lf[s] - dep.lag) + d_i     # convertir LS_i -> LF_i
                    finish = min(finish, candidate)
                lf[tid] = finish
            ls[tid] = lf[tid] - d_i

        # ---- Holguras y camino crítico -------------------------------- #
        results: Dict[str, TaskResult] = {}
        eps = 1e-6
        for tid in self.tasks:
            total_slack = ls[tid] - es[tid]
            # Holgura libre: cuánto puede retrasarse sin afectar el ES temprano
            # de ningún sucesor (solo relaciones que empujan el inicio: FS/SS).
            free_slack = total_slack
            succ = self._successors[tid]
            if succ:
                free_candidates = []
                for dep in succ:
                    s = dep.successor
                    if dep.dep_type in ("FS", "FF"):
                        free_candidates.append(es[s] - ef[tid] - dep.lag)
                    else:  # SS, SF dependen del inicio
                        free_candidates.append(es[s] - es[tid] - dep.lag)
                free_slack = max(0.0, min(free_candidates)) if free_candidates else total_slack
            free_slack = min(free_slack, total_slack)
            task = self.tasks[tid]
            results[tid] = TaskResult(
                id=tid,
                duration=dur[tid],
                early_start=round(es[tid], 6),
                early_finish=round(ef[tid], 6),
                late_start=round(ls[tid], 6),
                late_finish=round(lf[tid], 6),
                total_slack=round(total_slack, 6),
                free_slack=round(max(0.0, free_slack), 6),
                is_critical=abs(total_slack) < eps,
                pert_expected=round(task.expected_duration(), 6),
                pert_variance=round(task.variance(), 6),
            )

        critical_path = self._extract_critical_path(order, results)
        proj_variance = sum(results[t].pert_variance for t in critical_path)

        return CPMResult(
            project_duration=round(project_duration, 6),
            critical_path=critical_path,
            tasks=results,
            pert_variance=round(proj_variance, 6),
            pert_std_dev=round(math.sqrt(proj_variance), 6),
        )

    def _extract_critical_path(
        self, order: List[str], results: Dict[str, TaskResult]
    ) -> List[str]:
        """Devuelve una ruta crítica coherente (una secuencia encadenada de tareas críticas)."""
        critical = [t for t in order if results[t].is_critical]
        if not critical:
            return []
        critical_set = set(critical)
        # Punto de partida: tarea crítica sin predecesor crítico.
        starts = [
            t for t in critical
            if not any(d.predecessor in critical_set for d in self._predecessors[t])
        ]
        start = starts[0] if starts else critical[0]
        path = [start]
        current = start
        while True:
            nxt = [
                d.successor for d in self._successors[current]
                if d.successor in critical_set and d.successor not in path
            ]
            if not nxt:
                break
            # Elegir el sucesor crítico que termina más tarde (avanza en la ruta).
            nxt.sort(key=lambda t: results[t].early_finish)
            current = nxt[-1]
            path.append(current)
        return path


# --------------------------------------------------------------------------- #
# Utilidades de (de)serialización para la API
# --------------------------------------------------------------------------- #
def compute_from_dict(payload: dict) -> dict:
    """Recibe el JSON de `/cpm/preview` y devuelve el resultado serializable."""
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
    result = CPMEngine(tasks, deps).compute()
    return {
        "project_duration": result.project_duration,
        "critical_path": result.critical_path,
        "pert_variance": result.pert_variance,
        "pert_std_dev": result.pert_std_dev,
        "tasks": {
            tid: {
                "duration": r.duration,
                "early_start": r.early_start,
                "early_finish": r.early_finish,
                "late_start": r.late_start,
                "late_finish": r.late_finish,
                "total_slack": r.total_slack,
                "free_slack": r.free_slack,
                "is_critical": r.is_critical,
                "pert_expected": r.pert_expected,
                "pert_variance": r.pert_variance,
            }
            for tid, r in result.tasks.items()
        },
    }


def _opt(d: dict, key: str) -> Optional[float]:
    v = d.get(key)
    return float(v) if v is not None else None
