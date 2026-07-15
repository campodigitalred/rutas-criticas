"""Modelos Pydantic para la API de Campo Crítico."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

DepType = Literal["FS", "SS", "FF", "SF"]


class TaskIn(BaseModel):
    id: str
    duration: float = 0.0
    optimistic: Optional[float] = None
    most_likely: Optional[float] = None
    pessimistic: Optional[float] = None


class DependencyIn(BaseModel):
    predecessor: str
    successor: str
    dep_type: DepType = "FS"
    lag: float = 0.0


class CPMRequest(BaseModel):
    tasks: List[TaskIn]
    dependencies: List[DependencyIn] = Field(default_factory=list)


class TaskResultOut(BaseModel):
    duration: float
    early_start: float
    early_finish: float
    late_start: float
    late_finish: float
    total_slack: float
    free_slack: float
    is_critical: bool
    pert_expected: float
    pert_variance: float


class CPMResponse(BaseModel):
    project_duration: float
    critical_path: List[str]
    pert_variance: float
    pert_std_dev: float
    tasks: Dict[str, TaskResultOut]


class ScenarioOverrideIn(BaseModel):
    task_id: str
    duration_delta_days: float = 0.0
    cost_delta: float = 0.0
    note: Optional[str] = None


class SimulationRequest(BaseModel):
    """Escenario '¿Qué pasaría si...?': red base + perturbaciones."""
    tasks: List[TaskIn]
    dependencies: List[DependencyIn] = Field(default_factory=list)
    overrides: List[ScenarioOverrideIn] = Field(default_factory=list)
    target_duration: Optional[float] = None
    cost_per_day_delay: float = 0.0


class SimulationResponse(BaseModel):
    baseline_duration: float
    scenario_duration: float
    delay_days: float
    critical_path_baseline: List[str]
    critical_path_scenario: List[str]
    budget_impact: float
    probability_on_time: Optional[float] = None


class TranscriptionResponse(BaseModel):
    text: str
    language: Optional[str] = None
    duration_seconds: Optional[float] = None


# --------------------------------------------------------------------------- #
# Módulo C — Seguimiento de ejecución (Kanban)
# --------------------------------------------------------------------------- #
TaskStatus = Literal["todo", "in_progress", "blocked", "done"]


class ExecutionTaskIn(BaseModel):
    id: str
    duration: float = 0.0
    progress_pct: float = 0.0
    status: TaskStatus = "todo"


class ExecutionSummaryRequest(BaseModel):
    tasks: List[ExecutionTaskIn]
    dependencies: List[DependencyIn] = Field(default_factory=list)
    # Día del proyecto (0 = inicio) para evaluar avance planeado y salud.
    as_of_day: Optional[float] = None


class ExecutionSummaryResponse(BaseModel):
    total_tasks: int
    status_counts: Dict[str, int]
    overall_progress: float
    critical_progress: float
    blocked_count: int
    critical_blocked: bool
    project_duration: float
    critical_path: List[str]
    as_of_day: Optional[float] = None
    planned_progress: Optional[float] = None
    schedule_variance_pct: Optional[float] = None
    health: str


# --------------------------------------------------------------------------- #
# Módulo D — Simulación Monte Carlo
# --------------------------------------------------------------------------- #
class SimTaskIn(BaseModel):
    id: str
    duration: float = 0.0
    optimistic: Optional[float] = None
    most_likely: Optional[float] = None
    pessimistic: Optional[float] = None
    cost: float = 0.0


class MonteCarloRequest(BaseModel):
    tasks: List[SimTaskIn]
    dependencies: List[DependencyIn] = Field(default_factory=list)
    iterations: int = Field(2000, ge=1, le=100000)
    seed: Optional[int] = None
    target_duration: Optional[float] = None
    cost_per_day_delay: float = 0.0
    histogram_bins: int = Field(20, ge=1, le=100)


class MonteCarloResponse(BaseModel):
    iterations: int
    seed: Optional[int] = None
    baseline_duration: float
    mean: float
    std_dev: float
    min: float
    max: float
    percentiles: Dict[str, float]
    probability_on_time: Optional[float] = None
    target_duration: Optional[float] = None
    criticality_index: Dict[str, float]
    histogram: List[dict]
    expected_cost: Optional[float] = None
    cost_p80: Optional[float] = None


# --------------------------------------------------------------------------- #
# Módulo D — Carga de recursos
# --------------------------------------------------------------------------- #
class ResourceIn(BaseModel):
    id: str
    name: str
    capacity_per_day: float = 1.0
    cost_per_day: float = 0.0
    kind: Literal["person", "machinery", "material"] = "person"


class AssignmentIn(BaseModel):
    task_id: str
    resource_id: str
    units: float = 1.0


class ResourceLoadRequest(BaseModel):
    tasks: List[ExecutionTaskIn]
    dependencies: List[DependencyIn] = Field(default_factory=list)
    resources: List[ResourceIn]
    assignments: List[AssignmentIn] = Field(default_factory=list)


class ResourceLoadResponse(BaseModel):
    horizon_days: int
    project_duration: float
    has_overallocation: bool
    alerts: List[dict]
    profiles: List[dict]


# --------------------------------------------------------------------------- #
# Módulo E — Dashboard EVM y exportadores
# --------------------------------------------------------------------------- #
class EVMTaskIn(BaseModel):
    id: str
    duration: float = 0.0
    planned_cost: float = 0.0
    progress_pct: float = 0.0
    actual_cost: float = 0.0


class EVMRequest(BaseModel):
    tasks: List[EVMTaskIn]
    dependencies: List[DependencyIn] = Field(default_factory=list)
    as_of_day: Optional[float] = None


class EVMResponse(BaseModel):
    as_of_day: Optional[float] = None
    project_duration: float
    bac: float
    ev: float
    ac: float
    pv: Optional[float] = None
    sv: Optional[float] = None
    cv: float
    spi: Optional[float] = None
    cpi: Optional[float] = None
    eac: Optional[float] = None
    etc: Optional[float] = None
    vac: Optional[float] = None
    tcpi: Optional[float] = None
    percent_complete: float
    percent_spent: float
    health: str
    pv_curve: List[dict]


class ExportTaskIn(BaseModel):
    id: str
    name: Optional[str] = None
    duration: float = 0.0
    optimistic: Optional[float] = None
    most_likely: Optional[float] = None
    pessimistic: Optional[float] = None
    planned_cost: float = 0.0
    progress_pct: float = 0.0
    is_milestone: bool = False


class ExportRequest(BaseModel):
    tasks: List[ExportTaskIn]
    dependencies: List[DependencyIn] = Field(default_factory=list)
    project_name: str = "Campo Crítico"
    project_id: str = "CC1"
    start_date: Optional[str] = None


# --------------------------------------------------------------------------- #
# Sincronización offline
# --------------------------------------------------------------------------- #
class MutationIn(BaseModel):
    mutation_id: str
    entity_type: str = "task"
    entity_id: str
    op: Literal["set", "delete"] = "set"
    field: Optional[str] = None
    value: Optional[Any] = None
    ts: float
    base_ts: float = 0.0


class SyncRequest(BaseModel):
    # Estado del servidor conocido por el cliente (desde el último snapshot).
    server_state: Optional[Dict[str, Any]] = None
    mutations: List[MutationIn] = Field(default_factory=list)


class SyncResponse(BaseModel):
    applied: List[dict]
    rejected: List[dict]
    conflicts: List[dict]
    server_state: Dict[str, Any]
    server_ts: float


# --------------------------------------------------------------------------- #
# Persistencia — proyectos, tareas y dependencias
# --------------------------------------------------------------------------- #
class ProjectCreate(BaseModel):
    organization_id: str
    name: str
    objective: Optional[str] = None
    budget_estimated: Optional[float] = None
    currency: str = "MXN"
    deadline_hard: Optional[str] = None
    start_date: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    budget_estimated: Optional[float] = None
    currency: Optional[str] = None
    deadline_hard: Optional[str] = None
    start_date: Optional[str] = None
    status: Optional[Literal["draft", "planning", "executing", "closed"]] = None
    owner_id: Optional[str] = None


class WBSTaskCreate(BaseModel):
    temp_id: Optional[str] = None
    name: str
    duration_days: float = 0.0
    optimistic_days: Optional[float] = None
    most_likely_days: Optional[float] = None
    pessimistic_days: Optional[float] = None
    cost_estimated: float = 0.0
    is_milestone: bool = False


class WBSDependencyCreate(BaseModel):
    predecessor: str
    successor: str
    dep_type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag_days: float = 0.0


class ProjectFromWBSRequest(BaseModel):
    organization_id: str
    name: str
    objective: Optional[str] = None
    budget_estimated: Optional[float] = None
    tasks: List[WBSTaskCreate]
    dependencies: List[WBSDependencyCreate] = Field(default_factory=list)


class TaskCreate(BaseModel):
    name: str
    description: Optional[str] = None
    duration_days: float = 0.0
    optimistic_days: Optional[float] = None
    most_likely_days: Optional[float] = None
    pessimistic_days: Optional[float] = None
    cost_estimated: float = 0.0
    progress_pct: int = 0
    status: Literal["todo", "in_progress", "blocked", "done"] = "todo"
    is_milestone: bool = False


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    duration_days: Optional[float] = None
    optimistic_days: Optional[float] = None
    most_likely_days: Optional[float] = None
    pessimistic_days: Optional[float] = None
    cost_estimated: Optional[float] = None
    progress_pct: Optional[int] = None
    status: Optional[Literal["todo", "in_progress", "blocked", "done"]] = None
    is_milestone: Optional[bool] = None


class DependencyCreate(BaseModel):
    predecessor_id: str
    successor_id: str
    dep_type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag_days: float = 0.0


class OrganizationCreate(BaseModel):
    name: str


class ProjectSyncRequest(BaseModel):
    mutations: List[MutationIn] = Field(default_factory=list)
