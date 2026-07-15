"""Esquemas de la EDT/WBS generada por el asistente IA.

Los objetos aquí definidos son el *contrato* que debe cumplir la salida del LLM.
Se implementan como dataclasses puras (sin dependencias externas) para que el
núcleo del asistente sea verificable sin conexión, igual que el motor CPM. La
capa FastAPI puede consumir estas dataclasses directamente como modelos de
request/response.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

VALID_DEP_TYPES = {"FS", "SS", "FF", "SF"}


class WBSValidationError(ValueError):
    """La EDT propuesta no cumple el contrato."""


@dataclass
class WBSTask:
    """Una tarea (paquete de trabajo) propuesta por la IA."""

    temp_id: str
    name: str
    optimistic_days: float
    most_likely_days: float
    pessimistic_days: float
    description: Optional[str] = None
    phase: Optional[str] = None
    cost_estimated: float = 0.0
    is_milestone: bool = False

    def __post_init__(self) -> None:
        if not self.temp_id or not str(self.temp_id).strip():
            raise WBSValidationError("temp_id vacío.")
        if not self.name or len(self.name.strip()) < 2:
            raise WBSValidationError(f"Nombre de tarea inválido: {self.name!r}")
        self.optimistic_days = float(self.optimistic_days)
        self.most_likely_days = float(self.most_likely_days)
        self.pessimistic_days = float(self.pessimistic_days)
        if not (self.optimistic_days > 0 and self.most_likely_days > 0 and self.pessimistic_days > 0):
            raise WBSValidationError(f"Duraciones PERT deben ser > 0 en {self.temp_id}.")
        if not (self.optimistic_days <= self.most_likely_days <= self.pessimistic_days):
            raise WBSValidationError(
                f"Estimación PERT inválida en {self.temp_id}: debe cumplir o <= m <= p "
                f"(o={self.optimistic_days}, m={self.most_likely_days}, p={self.pessimistic_days})."
            )
        if self.cost_estimated < 0:
            raise WBSValidationError(f"cost_estimated negativo en {self.temp_id}.")

    @property
    def expected_days(self) -> float:
        """Duración esperada PERT: (o + 4m + p) / 6."""
        return (self.optimistic_days + 4 * self.most_likely_days + self.pessimistic_days) / 6.0


@dataclass
class WBSDependency:
    predecessor: str
    successor: str
    dep_type: str = "FS"
    lag_days: float = 0.0

    def __post_init__(self) -> None:
        if self.dep_type not in VALID_DEP_TYPES:
            raise WBSValidationError(f"Tipo de dependencia inválido: {self.dep_type!r}")
        if self.predecessor == self.successor:
            raise WBSValidationError("Una tarea no puede depender de sí misma.")
        self.lag_days = float(self.lag_days)


@dataclass
class CriticalPathPreview:
    """Vista previa del cálculo CPM sobre la EDT generada."""

    project_duration_days: float
    critical_path: List[str]
    pert_std_dev: float


@dataclass
class BreakdownRequest:
    raw_text: str
    source: str = "text"
    # Fecha límite en días desde el inicio (opcional). Si se indica, el plan se
    # escala para intentar caber dentro de este horizonte.
    target_horizon_days: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.raw_text or len(self.raw_text.strip()) < 5:
            raise WBSValidationError("raw_text demasiado corto (mínimo 5 caracteres).")
        if self.source not in ("text", "voice"):
            raise WBSValidationError("source debe ser 'text' o 'voice'.")
        if self.target_horizon_days is not None and self.target_horizon_days <= 0:
            raise WBSValidationError("target_horizon_days debe ser > 0.")


@dataclass
class BreakdownResult:
    """Salida del asistente: EDT validada + vista previa de ruta crítica."""

    summary: str
    provider: str
    tasks: List[WBSTask]
    dependencies: List[WBSDependency]
    detected_horizon_days: Optional[float] = None
    preview: Optional[CriticalPathPreview] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialización JSON-friendly para la API y el frontend."""
        return {
            "summary": self.summary,
            "provider": self.provider,
            "detected_horizon_days": self.detected_horizon_days,
            "tasks": [
                {
                    "temp_id": t.temp_id,
                    "name": t.name,
                    "description": t.description,
                    "phase": t.phase,
                    "optimistic_days": t.optimistic_days,
                    "most_likely_days": t.most_likely_days,
                    "pessimistic_days": t.pessimistic_days,
                    "expected_days": round(t.expected_days, 2),
                    "cost_estimated": t.cost_estimated,
                    "is_milestone": t.is_milestone,
                }
                for t in self.tasks
            ],
            "dependencies": [
                {
                    "predecessor": d.predecessor,
                    "successor": d.successor,
                    "dep_type": d.dep_type,
                    "lag_days": d.lag_days,
                }
                for d in self.dependencies
            ],
            "preview": (
                {
                    "project_duration_days": self.preview.project_duration_days,
                    "critical_path": self.preview.critical_path,
                    "pert_std_dev": self.preview.pert_std_dev,
                }
                if self.preview
                else None
            ),
            "warnings": self.warnings,
        }
