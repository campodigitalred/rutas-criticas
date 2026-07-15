"""API FastAPI de Campo Crítico.

Expone el núcleo del motor CPM/PERT. Los endpoints de persistencia (proyectos,
tareas, recursos) se documentan en docs/API.md; aquí se implementan los cálculos
sin estado que alimentan la interfaz (recálculo en tiempo real y simulación).
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .cpm import CPMEngine, CPMError, Dependency, Task
from .cpm.engine import compute_from_dict
from .schemas import (
    CPMRequest,
    CPMResponse,
    SimulationRequest,
    SimulationResponse,
)

app = FastAPI(
    title="Campo Crítico API",
    version="0.1.0",
    description="Motor de Rutas Críticas (CPM/PERT) — Agencia Campo Digital.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajustar en producción
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["infra"])
def health() -> dict:
    return {"status": "ok", "service": "campo-critico-api"}


@app.post("/api/v1/cpm/preview", response_model=CPMResponse, tags=["cpm"])
def cpm_preview(req: CPMRequest) -> CPMResponse:
    """Calcula la ruta crítica sin persistir. Ideal para el Gantt en tiempo real."""
    try:
        result = compute_from_dict(req.model_dump())
    except CPMError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return CPMResponse(**result)


def _build_engine(tasks, dependencies, overrides=None) -> CPMEngine:
    delta = {o.task_id: o.duration_delta_days for o in (overrides or [])}
    engine_tasks = [
        Task(
            id=t.id,
            duration=t.duration + delta.get(t.id, 0.0),
            optimistic=t.optimistic,
            most_likely=t.most_likely,
            pessimistic=t.pessimistic,
        )
        for t in tasks
    ]
    engine_deps = [
        Dependency(d.predecessor, d.successor, d.dep_type, d.lag) for d in dependencies
    ]
    return CPMEngine(engine_tasks, engine_deps)


@app.post("/api/v1/scenarios/simulate", response_model=SimulationResponse, tags=["simulation"])
def simulate(req: SimulationRequest) -> SimulationResponse:
    """Modo '¿Qué pasaría si...?': compara la red base con un escenario perturbado."""
    try:
        baseline = _build_engine(req.tasks, req.dependencies).compute()
        scenario = _build_engine(req.tasks, req.dependencies, req.overrides).compute()
    except CPMError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    delay = scenario.project_duration - baseline.project_duration
    budget_impact = (
        max(0.0, delay) * req.cost_per_day_delay
        + sum(o.cost_delta for o in req.overrides)
    )
    prob = (
        scenario.probability_of_meeting(req.target_duration)
        if req.target_duration is not None
        else None
    )
    return SimulationResponse(
        baseline_duration=baseline.project_duration,
        scenario_duration=scenario.project_duration,
        delay_days=round(delay, 4),
        critical_path_baseline=baseline.critical_path,
        critical_path_scenario=scenario.critical_path,
        budget_impact=round(budget_impact, 2),
        probability_on_time=round(prob, 4) if prob is not None else None,
    )
