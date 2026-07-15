"""API FastAPI de Campo Crítico.

Expone el núcleo del motor CPM/PERT. Los endpoints de persistencia (proyectos,
tareas, recursos) se documentan en docs/API.md; aquí se implementan los cálculos
sin estado que alimentan la interfaz (recálculo en tiempo real y simulación).
"""
from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .ai import BreakdownService
from .ai.schemas import BreakdownRequest, BreakdownResult
from .cpm import CPMEngine, CPMError, Dependency, Task
from .cpm.engine import compute_from_dict
from .execution import summary_from_dict
from .execution.metrics import ExecutionError
from .resources import resource_load_from_dict
from .resources.allocation import ResourceError
from .simulation import run_montecarlo_from_dict
from .simulation.montecarlo import SimulationError
from .schemas import (
    CPMRequest,
    CPMResponse,
    ExecutionSummaryRequest,
    ExecutionSummaryResponse,
    MonteCarloRequest,
    MonteCarloResponse,
    ResourceLoadRequest,
    ResourceLoadResponse,
    SimulationRequest,
    SimulationResponse,
    TranscriptionResponse,
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


# --------------------------------------------------------------------------- #
# Módulo A — Asistente IA de desglose
# --------------------------------------------------------------------------- #
_breakdown_service = BreakdownService()


@app.post("/api/v1/ai/breakdown", response_model=BreakdownResult, tags=["ai"])
def ai_breakdown(req: BreakdownRequest) -> BreakdownResult:
    """Descompone una idea en texto libre en una EDT/WBS validada.

    Usa un LLM si está configurado (CAMPO_LLM_API_KEY) y cae a un generador
    heurístico offline en caso contrario. La EDT resultante se valida contra el
    esquema y contra el motor CPM (rechaza ciclos) y devuelve una vista previa
    de la ruta crítica.
    """
    try:
        return _breakdown_service.run(req)
    except CPMError as exc:
        # EDT inválida (ciclo, referencias colgantes, esquema).
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/ai/transcribe", response_model=TranscriptionResponse, tags=["ai"])
async def ai_transcribe(file: UploadFile = File(...)) -> TranscriptionResponse:
    """Transcribe una nota de voz a texto (interfaz).

    En producción delega a un motor de speech-to-text (p.ej. Whisper). Aquí se
    expone el contrato; el binario de audio se recibe como multipart/form-data.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Transcripción no habilitada en este entorno. Configure un backend "
            "de speech-to-text (Whisper) para activar /ai/transcribe."
        ),
    )


# --------------------------------------------------------------------------- #
# Módulo C — Seguimiento de ejecución (Kanban)
# --------------------------------------------------------------------------- #
@app.post(
    "/api/v1/execution/summary",
    response_model=ExecutionSummaryResponse,
    tags=["execution"],
)
def execution_summary(req: ExecutionSummaryRequest) -> ExecutionSummaryResponse:
    """Resumen de ejecución para el tablero Kanban.

    A partir del estado/avance de las tareas y la red de dependencias, corre el
    motor CPM y calcula: avance real ponderado por duración, avance del camino
    crítico, conteos por estado, avance planeado a la fecha (`as_of_day`),
    varianza de cronograma y una señal de salud del proyecto.
    """
    try:
        result = summary_from_dict(req.model_dump())
    except CPMError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ExecutionSummaryResponse(**result)


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


@app.post("/api/v1/simulation/montecarlo", response_model=MonteCarloResponse, tags=["simulation"])
def montecarlo(req: MonteCarloRequest) -> MonteCarloResponse:
    """Simulación Monte Carlo (análisis de riesgo).

    Muestrea las duraciones desde distribuciones Beta-PERT y corre el CPM en cada
    iteración para estimar la distribución de la fecha final, la probabilidad de
    cumplir el plazo, el índice de criticidad por tarea y el impacto presupuestal.
    """
    try:
        result = run_montecarlo_from_dict(req.model_dump())
    except CPMError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SimulationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return MonteCarloResponse(**result)


# --------------------------------------------------------------------------- #
# Módulo D — Carga de recursos y sobreasignación
# --------------------------------------------------------------------------- #
@app.post("/api/v1/resources/load", response_model=ResourceLoadResponse, tags=["resources"])
def resource_load(req: ResourceLoadRequest) -> ResourceLoadResponse:
    """Perfil de carga diaria por recurso y alertas de sobreasignación.

    Posiciona las tareas en su inicio temprano (CPM), acumula las unidades
    asignadas por día y por recurso, y reporta los días/ventanas donde la carga
    supera la capacidad (p.ej. una brigada asignada a dos frentes que se traslapan).
    """
    try:
        result = resource_load_from_dict(req.model_dump())
    except CPMError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ResourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ResourceLoadResponse(**result)
