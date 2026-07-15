"""API FastAPI de Campo Crítico.

Expone el núcleo del motor CPM/PERT. Los endpoints de persistencia (proyectos,
tareas, recursos) se documentan en docs/API.md; aquí se implementan los cálculos
sin estado que alimentan la interfaz (recálculo en tiempo real y simulación).
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .ai import BreakdownService
from .ai.schemas import BreakdownRequest, BreakdownResult
from .cpm import CPMEngine, CPMError, Dependency, Task
from .cpm.engine import compute_from_dict
from .execution import summary_from_dict
from .execution.metrics import ExecutionError
from .reporting import (
    evm_from_dict,
    export_csv_from_dict,
    export_msproject_from_dict,
    export_p6_xer_from_dict,
)
from .reporting.evm import EVMError
from .resources import resource_load_from_dict
from .resources.allocation import ResourceError
from .simulation import run_montecarlo_from_dict
from .simulation.montecarlo import SimulationError
from .sync import apply_mutations
from .sync.engine import SyncError
from .db import (
    Database,
    DependencyRepository,
    OrganizationRepository,
    ProjectRepository,
    TaskRepository,
    apply_sync_to_db,
    build_snapshot,
    create_project_with_wbs,
    get_database,
    recompute_and_store_cpm,
)
from .db.repository import NotFound, RepositoryError
from .auth import AuthError, permissions_for
from .auth.deps import get_auth_service, get_current_user, require_permission
from .auth.rbac import (
    P_DEPENDENCY_WRITE,
    P_PROJECT_DELETE,
    P_PROJECT_READ,
    P_PROJECT_WRITE,
    P_TASK_EXECUTE,
    P_TASK_WRITE,
    P_USER_MANAGE,
)
from .auth.service import AuthService
from .schemas import (
    AuthResponse,
    CPMRequest,
    CPMResponse,
    CreateUserRequest,
    DependencyCreate,
    LoginRequest,
    OrganizationCreate,
    ProjectCreate,
    ProjectFromWBSRequest,
    ProjectSyncRequest,
    ProjectUpdate,
    RegisterRequest,
    TaskCreate,
    TaskUpdate,
    UserResponse,
    EVMRequest,
    EVMResponse,
    ExecutionSummaryRequest,
    ExecutionSummaryResponse,
    ExportRequest,
    MonteCarloRequest,
    MonteCarloResponse,
    ResourceLoadRequest,
    ResourceLoadResponse,
    SimulationRequest,
    SimulationResponse,
    SyncRequest,
    SyncResponse,
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


# --------------------------------------------------------------------------- #
# Módulo E — Dashboard EVM y exportadores
# --------------------------------------------------------------------------- #
@app.post("/api/v1/reporting/evm", response_model=EVMResponse, tags=["reporting"])
def reporting_evm(req: EVMRequest) -> EVMResponse:
    """Dashboard de Valor Ganado (EVM): BAC/PV/EV/AC, SPI/CPI, EAC/VAC, salud y curva S."""
    try:
        result = evm_from_dict(req.model_dump())
    except CPMError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except EVMError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return EVMResponse(**result)


@app.post("/api/v1/export/msproject", tags=["reporting"])
def export_msproject(req: ExportRequest) -> Response:
    """Exporta la ruta crítica a MS Project (MSPDI XML)."""
    try:
        xml = export_msproject_from_dict(req.model_dump())
    except (CPMError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": "attachment; filename=campo-critico.xml"},
    )


@app.post("/api/v1/export/p6", tags=["reporting"])
def export_p6(req: ExportRequest) -> Response:
    """Exporta la ruta crítica a Primavera P6 (XER)."""
    try:
        xer = export_p6_xer_from_dict(req.model_dump())
    except (CPMError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(
        content=xer,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=campo-critico.xer"},
    )


@app.post("/api/v1/export/csv", tags=["reporting"])
def export_csv(req: ExportRequest) -> Response:
    """Exporta la ruta crítica a CSV (compatible con Excel)."""
    try:
        data = export_csv_from_dict(req.model_dump())
    except (CPMError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=campo-critico.csv"},
    )


# --------------------------------------------------------------------------- #
# Sincronización offline
# --------------------------------------------------------------------------- #
@app.post("/api/v1/sync", response_model=SyncResponse, tags=["sync"])
def sync(req: SyncRequest) -> SyncResponse:
    """Aplica la cola de mutaciones offline al estado del servidor.

    Resuelve conflictos con *last-write-wins* a nivel de campo y devuelve las
    mutaciones aplicadas, las descartadas, los conflictos detectados (para
    revisión) y el estado del servidor fusionado con su nueva marca de agua.
    """
    payload = req.model_dump()
    try:
        result = apply_mutations(payload.get("server_state"), payload.get("mutations", []))
    except SyncError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return SyncResponse(**result)


# ==========================================================================> #
# AUTENTICACIÓN (JWT + RBAC)
# ==========================================================================> #
@app.post("/api/v1/auth/register", response_model=AuthResponse, tags=["auth"], status_code=201)
def auth_register(req: RegisterRequest, auth: AuthService = Depends(get_auth_service)) -> AuthResponse:
    """Alta de una organización y su usuario administrador; devuelve un token."""
    try:
        out = auth.register(req.organization_name, req.email, req.full_name, req.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AuthResponse(token=out["token"], user=out["user"])


@app.post("/api/v1/auth/login", response_model=AuthResponse, tags=["auth"])
def auth_login(req: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> AuthResponse:
    try:
        out = auth.authenticate(req.email, req.password)
    except AuthError:
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")
    return AuthResponse(token=out["token"], user=out["user"])


@app.get("/api/v1/auth/me", response_model=UserResponse, tags=["auth"])
def auth_me(user: dict = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=user["sub"], email=user["email"], full_name=user.get("name", ""),
        role=user["role"], organization_id=user["org"],
        permissions=sorted(permissions_for(user["role"])),
    )


@app.post("/api/v1/auth/users", tags=["auth"], status_code=201)
def auth_create_user(
    req: CreateUserRequest,
    user: dict = Depends(require_permission(P_USER_MANAGE)),
    auth: AuthService = Depends(get_auth_service),
) -> dict:
    """Crea un usuario en la organización del solicitante (requiere user:manage)."""
    try:
        return auth.create_user(user["org"], req.email, req.full_name, req.password, req.role)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==========================================================================> #
# PERSISTENCIA — proyectos, tareas y dependencias (BD)
# ==========================================================================> #
def _require(entity, label: str):
    if entity is None:
        raise HTTPException(status_code=404, detail=f"{label} no encontrado.")
    return entity


@app.post("/api/v1/organizations", tags=["persistence"], status_code=201)
def create_organization(req: OrganizationCreate, db: Database = Depends(get_database)) -> dict:
    return OrganizationRepository(db).create(req.name)


@app.post("/api/v1/projects", tags=["persistence"], status_code=201)
def create_project(req: ProjectCreate, db: Database = Depends(get_database),
                   _user: dict = Depends(require_permission(P_PROJECT_WRITE))) -> dict:
    try:
        return ProjectRepository(db).create(req.organization_id, req.name, **req.model_dump(exclude={"organization_id", "name"}))
    except Exception as exc:  # p.ej. FK inexistente
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/projects/from-wbs", tags=["persistence"], status_code=201)
def create_project_from_wbs(req: ProjectFromWBSRequest, db: Database = Depends(get_database),
                            _user: dict = Depends(require_permission(P_PROJECT_WRITE))) -> dict:
    """Crea un proyecto persistido a partir de una EDT (salida del asistente IA)."""
    payload = req.model_dump()
    try:
        out = create_project_with_wbs(
            db,
            organization_id=payload["organization_id"],
            name=payload["name"],
            tasks=payload["tasks"],
            dependencies=payload["dependencies"],
            objective=payload.get("objective"),
            budget_estimated=payload.get("budget_estimated"),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return out


@app.get("/api/v1/projects", tags=["persistence"])
def list_projects(organization_id: str | None = None, status: str | None = None,
                  db: Database = Depends(get_database),
                  _user: dict = Depends(require_permission(P_PROJECT_READ))) -> list:
    return ProjectRepository(db).list(organization_id, status)


@app.get("/api/v1/projects/{project_id}", tags=["persistence"])
def get_project(project_id: str, db: Database = Depends(get_database),
                _user: dict = Depends(require_permission(P_PROJECT_READ))) -> dict:
    projects = ProjectRepository(db)
    project = _require(projects.get(project_id), "Proyecto")
    return {
        "project": project,
        "tasks": TaskRepository(db).list(project_id),
        "dependencies": DependencyRepository(db).list(project_id),
    }


@app.patch("/api/v1/projects/{project_id}", tags=["persistence"])
def update_project(project_id: str, req: ProjectUpdate, db: Database = Depends(get_database),
                   _user: dict = Depends(require_permission(P_PROJECT_WRITE))) -> dict:
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        return ProjectRepository(db).update(project_id, **fields)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/v1/projects/{project_id}", tags=["persistence"], status_code=204)
def delete_project(project_id: str, db: Database = Depends(get_database),
                   _user: dict = Depends(require_permission(P_PROJECT_DELETE))) -> None:
    ProjectRepository(db).delete(project_id)


@app.get("/api/v1/projects/{project_id}/tasks", tags=["persistence"])
def list_tasks(project_id: str, db: Database = Depends(get_database),
               _user: dict = Depends(require_permission(P_PROJECT_READ))) -> list:
    return TaskRepository(db).list(project_id)


@app.post("/api/v1/projects/{project_id}/tasks", tags=["persistence"], status_code=201)
def create_task(project_id: str, req: TaskCreate, db: Database = Depends(get_database),
                _user: dict = Depends(require_permission(P_TASK_WRITE))) -> dict:
    _require(ProjectRepository(db).get(project_id), "Proyecto")
    try:
        return TaskRepository(db).create(project_id, req.name, **req.model_dump(exclude={"name"}))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.patch("/api/v1/tasks/{task_id}", tags=["persistence"])
def update_task(task_id: str, req: TaskUpdate, db: Database = Depends(get_database),
                _user: dict = Depends(require_permission(P_TASK_WRITE))) -> dict:
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        return TaskRepository(db).update(task_id, **fields)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.delete("/api/v1/tasks/{task_id}", tags=["persistence"], status_code=204)
def delete_task(task_id: str, db: Database = Depends(get_database),
                _user: dict = Depends(require_permission(P_TASK_WRITE))) -> None:
    TaskRepository(db).delete(task_id)


@app.get("/api/v1/projects/{project_id}/dependencies", tags=["persistence"])
def list_dependencies(project_id: str, db: Database = Depends(get_database),
                      _user: dict = Depends(require_permission(P_PROJECT_READ))) -> list:
    return DependencyRepository(db).list(project_id)


@app.post("/api/v1/projects/{project_id}/dependencies", tags=["persistence"], status_code=201)
def create_dependency(project_id: str, req: DependencyCreate, db: Database = Depends(get_database),
                      _user: dict = Depends(require_permission(P_DEPENDENCY_WRITE))) -> dict:
    """Crea una dependencia; rechaza ciclos revalidando el DAG con el motor CPM."""
    _require(ProjectRepository(db).get(project_id), "Proyecto")
    dep_repo = DependencyRepository(db)
    try:
        created = dep_repo.create(project_id, req.predecessor_id, req.successor_id, req.dep_type, req.lag_days)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Revalida que no se introdujo un ciclo; si lo hay, revierte.
    try:
        recompute_and_store_cpm(db, project_id)
    except CPMError as exc:
        dep_repo.delete(created["id"])
        raise HTTPException(status_code=409, detail=f"La dependencia crea un ciclo: {exc}")
    return created


@app.delete("/api/v1/dependencies/{dep_id}", tags=["persistence"], status_code=204)
def delete_dependency(dep_id: str, db: Database = Depends(get_database),
                      _user: dict = Depends(require_permission(P_DEPENDENCY_WRITE))) -> None:
    DependencyRepository(db).delete(dep_id)


@app.post("/api/v1/projects/{project_id}/cpm/compute", tags=["persistence"])
def compute_and_store(project_id: str, db: Database = Depends(get_database),
                      _user: dict = Depends(require_permission(P_PROJECT_READ))) -> dict:
    """Recalcula la ruta crítica sobre los datos persistidos y guarda cpm_result."""
    _require(ProjectRepository(db).get(project_id), "Proyecto")
    try:
        return recompute_and_store_cpm(db, project_id)
    except CPMError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/v1/projects/{project_id}/snapshot", tags=["persistence"])
def project_snapshot(project_id: str, db: Database = Depends(get_database),
                     _user: dict = Depends(require_permission(P_PROJECT_READ))) -> dict:
    """Snapshot del proyecto para cache offline (estado de sincronización)."""
    _require(ProjectRepository(db).get(project_id), "Proyecto")
    return build_snapshot(db, project_id)


@app.post("/api/v1/projects/{project_id}/sync", response_model=SyncResponse, tags=["persistence"])
def project_sync(project_id: str, req: ProjectSyncRequest, db: Database = Depends(get_database),
                 _user: dict = Depends(require_permission(P_TASK_EXECUTE))) -> SyncResponse:
    """Sincroniza la cola de mutaciones offline y persiste los cambios en la BD."""
    _require(ProjectRepository(db).get(project_id), "Proyecto")
    payload = req.model_dump()
    try:
        result = apply_sync_to_db(db, project_id, payload["mutations"])
    except SyncError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return SyncResponse(**result)
