"""Modelos Pydantic para la API de Campo Crítico."""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

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
