"""Dashboard de Valor Ganado (Earned Value Management).

Combina el cronograma (motor CPM) con los costos presupuestados, el avance real
y el costo real de cada tarea para calcular las métricas estándar de EVM:

  BAC  Presupuesto al término (Budget At Completion)  = Σ costo planeado
  PV   Valor planeado (Planned Value) a la fecha       = Σ costo·fracción planeada
  EV   Valor ganado (Earned Value)                     = Σ costo·avance real
  AC   Costo real (Actual Cost)                         = Σ costo real

  SV = EV − PV     CV = EV − AC
  SPI = EV / PV    CPI = EV / AC
  EAC = BAC / CPI  ETC = EAC − AC   VAC = BAC − EAC
  TCPI = (BAC − EV) / (BAC − AC)

Núcleo puro (dataclasses + stdlib), verificable sin conexión.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..cpm import CPMEngine, Dependency, Task


class EVMError(ValueError):
    """Datos de EVM inválidos."""


@dataclass
class EVMTask:
    id: str
    duration: float
    planned_cost: float = 0.0      # presupuesto de la tarea (contribución al BAC)
    progress_pct: float = 0.0       # % avance real [0..100]
    actual_cost: float = 0.0        # costo real incurrido

    def __post_init__(self) -> None:
        if not (0 <= self.progress_pct <= 100):
            raise EVMError(f"progress_pct fuera de rango en {self.id}: {self.progress_pct}")
        if self.planned_cost < 0 or self.actual_cost < 0:
            raise EVMError(f"Costos negativos en {self.id}.")


@dataclass
class EVMResult:
    as_of_day: Optional[float]
    project_duration: float
    bac: float
    ev: float
    ac: float
    pv: Optional[float]
    sv: Optional[float]
    cv: float
    spi: Optional[float]
    cpi: Optional[float]
    eac: Optional[float]
    etc: Optional[float]
    vac: Optional[float]
    tcpi: Optional[float]
    percent_complete: float
    percent_spent: float
    health: str
    pv_curve: List[dict] = field(default_factory=list)   # [{day, pv, ev?, ac?}]


def _planned_fraction(early_start: float, early_finish: float, day: float) -> float:
    dur = early_finish - early_start
    if dur <= 0:
        return 1.0 if day >= early_finish else 0.0
    return max(0.0, min(1.0, (day - early_start) / dur))


def compute_evm(
    tasks: List[EVMTask],
    dependencies: List[Dependency],
    as_of_day: Optional[float] = None,
) -> EVMResult:
    if not tasks:
        raise EVMError("No hay tareas para el cálculo EVM.")

    result = CPMEngine(
        [Task(id=t.id, duration=t.duration) for t in tasks], dependencies
    ).compute()

    bac = sum(t.planned_cost for t in tasks)
    ev = sum(t.planned_cost * (t.progress_pct / 100.0) for t in tasks)
    ac = sum(t.actual_cost for t in tasks)

    # PV requiere una fecha de corte.
    pv: Optional[float] = None
    if as_of_day is not None:
        pv = sum(
            t.planned_cost
            * _planned_fraction(
                result.tasks[t.id].early_start, result.tasks[t.id].early_finish, as_of_day
            )
            for t in tasks
        )

    cv = ev - ac
    sv = (ev - pv) if pv is not None else None
    cpi = (ev / ac) if ac > 0 else None
    spi = (ev / pv) if (pv is not None and pv > 0) else None

    eac = (bac / cpi) if (cpi is not None and cpi > 0) else None
    etc = (eac - ac) if eac is not None else None
    vac = (bac - eac) if eac is not None else None
    tcpi = ((bac - ev) / (bac - ac)) if (bac - ac) != 0 else None

    percent_complete = (ev / bac * 100.0) if bac > 0 else 0.0
    percent_spent = (ac / bac * 100.0) if bac > 0 else 0.0

    health = _health(spi, cpi, percent_complete)

    pv_curve = _build_pv_curve(tasks, result, as_of_day, ev, ac)

    r = lambda x: round(x, 2) if isinstance(x, (int, float)) else x  # noqa: E731
    r4 = lambda x: round(x, 4) if isinstance(x, (int, float)) else x  # noqa: E731

    return EVMResult(
        as_of_day=as_of_day,
        project_duration=round(result.project_duration, 4),
        bac=r(bac),
        ev=r(ev),
        ac=r(ac),
        pv=r(pv) if pv is not None else None,
        sv=r(sv) if sv is not None else None,
        cv=r(cv),
        spi=r4(spi) if spi is not None else None,
        cpi=r4(cpi) if cpi is not None else None,
        eac=r(eac) if eac is not None else None,
        etc=r(etc) if etc is not None else None,
        vac=r(vac) if vac is not None else None,
        tcpi=r4(tcpi) if tcpi is not None else None,
        percent_complete=r(percent_complete),
        percent_spent=r(percent_spent),
        health=health,
        pv_curve=pv_curve,
    )


def _health(spi: Optional[float], cpi: Optional[float], percent_complete: float) -> str:
    indices = [x for x in (spi, cpi) if x is not None]
    if not indices:
        return "in_progress" if percent_complete > 0 else "not_started"
    worst = min(indices)
    if percent_complete >= 100:
        return "done"
    if worst >= 0.95:
        return "on_track"
    if worst >= 0.85:
        return "at_risk"
    return "behind"


def _build_pv_curve(
    tasks: List[EVMTask],
    result,
    as_of_day: Optional[float],
    ev: float,
    ac: float,
) -> List[dict]:
    """Curva S del valor planeado acumulado por día. En el día de corte añade EV y AC."""
    horizon = max(1, int(math.ceil(result.project_duration)))
    curve = []
    for day in range(horizon + 1):
        pv = sum(
            t.planned_cost
            * _planned_fraction(
                result.tasks[t.id].early_start, result.tasks[t.id].early_finish, day
            )
            for t in tasks
        )
        point = {"day": day, "pv": round(pv, 2)}
        if as_of_day is not None and day == int(round(as_of_day)):
            point["ev"] = round(ev, 2)
            point["ac"] = round(ac, 2)
        curve.append(point)
    return curve


# --------------------------------------------------------------------------- #
# (De)serialización para la API
# --------------------------------------------------------------------------- #
def evm_from_dict(payload: dict) -> dict:
    tasks = [
        EVMTask(
            id=str(t["id"]),
            duration=float(t.get("duration", 0) or 0),
            planned_cost=float(t.get("planned_cost", t.get("cost", 0)) or 0),
            progress_pct=float(t.get("progress_pct", 0) or 0),
            actual_cost=float(t.get("actual_cost", 0) or 0),
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
    r = compute_evm(tasks, deps, as_of)
    return {
        "as_of_day": r.as_of_day,
        "project_duration": r.project_duration,
        "bac": r.bac, "ev": r.ev, "ac": r.ac, "pv": r.pv,
        "sv": r.sv, "cv": r.cv, "spi": r.spi, "cpi": r.cpi,
        "eac": r.eac, "etc": r.etc, "vac": r.vac, "tcpi": r.tcpi,
        "percent_complete": r.percent_complete,
        "percent_spent": r.percent_spent,
        "health": r.health,
        "pv_curve": r.pv_curve,
    }
