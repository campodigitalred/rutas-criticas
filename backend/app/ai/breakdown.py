"""Orquestador del asistente IA de desglose.

Pipeline:
  1. Selección de proveedor (LLM si está configurado; si no, heurístico offline).
  2. Generación de la EDT en bruto (dict).
  3. Validación estricta contra los esquemas Pydantic (WBSTask / WBSDependency).
  4. Validación del grafo con el motor CPM/PERT (detecta ciclos y referencias
     colgantes) y cálculo de la vista previa de ruta crítica.
  5. (Opcional) Escalado de duraciones para caber en el horizonte objetivo.
"""
from __future__ import annotations

from typing import List, Optional

from ..cpm import CPMEngine, CPMError, Dependency, Task
from .providers import (
    HeuristicProvider,
    LLMProvider,
    LLMProviderError,
    OpenAICompatibleProvider,
    detect_horizon_days,
)
from .schemas import (
    BreakdownRequest,
    BreakdownResult,
    CriticalPathPreview,
    WBSDependency,
    WBSTask,
    WBSValidationError,
)


class BreakdownService:
    """Convierte texto libre en una EDT validada + vista previa de ruta crítica."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        fallback: Optional[LLMProvider] = None,
    ):
        # Por defecto: intenta LLM, cae a heurístico offline.
        self.provider = provider or OpenAICompatibleProvider()
        self.fallback = fallback or HeuristicProvider()

    # ------------------------------------------------------------------ #
    def run(self, req: BreakdownRequest) -> BreakdownResult:
        warnings: List[str] = []

        # 1-2. Generación con selección de proveedor + respaldo.
        raw, provider_name = self._generate(req, warnings)

        # 3. Validación estricta del contrato.
        tasks, deps = self._validate_schema(raw)

        # 4. Validación del grafo + vista previa CPM.
        preview = self._cpm_preview(tasks, deps, warnings)

        # 5. Escalado opcional al horizonte objetivo.
        horizon = req.target_horizon_days or detect_horizon_days(req.raw_text)
        if horizon and preview and preview.project_duration_days > 0:
            tasks, preview = self._fit_to_horizon(tasks, deps, horizon, warnings)

        summary = raw.get("summary") or "Desglose de proyecto"
        return BreakdownResult(
            summary=summary,
            detected_horizon_days=horizon,
            provider=provider_name,
            tasks=tasks,
            dependencies=deps,
            preview=preview,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ #
    def _generate(self, req: BreakdownRequest, warnings: List[str]):
        provider = self.provider
        # Si el proveedor primario es un LLM sin configurar, usa el respaldo.
        if isinstance(provider, OpenAICompatibleProvider) and not provider.is_configured:
            warnings.append("LLM no configurado; se usó el generador heurístico offline.")
            return self.fallback.generate(req.raw_text, req.target_horizon_days), self.fallback.name
        try:
            return provider.generate(req.raw_text, req.target_horizon_days), provider.name
        except LLMProviderError as exc:
            warnings.append(f"Proveedor primario falló ({exc}); se usó el respaldo heurístico.")
            return self.fallback.generate(req.raw_text, req.target_horizon_days), self.fallback.name

    def _validate_schema(self, raw: dict):
        try:
            tasks = [WBSTask(**t) for t in raw.get("tasks", [])]
            deps = [WBSDependency(**d) for d in raw.get("dependencies", [])]
        except (WBSValidationError, TypeError, ValueError) as exc:
            raise CPMError(f"La EDT generada no cumple el esquema: {exc}") from exc
        if not tasks:
            raise CPMError("La EDT generada no contiene tareas.")
        ids = {t.temp_id for t in tasks}
        if len(ids) != len(tasks):
            raise CPMError("Hay temp_id duplicados en la EDT.")
        for d in deps:
            if d.predecessor not in ids or d.successor not in ids:
                raise CPMError(
                    f"Dependencia con tarea inexistente: {d.predecessor}->{d.successor}"
                )
        return tasks, deps

    def _cpm_preview(
        self, tasks: List[WBSTask], deps: List[WBSDependency], warnings: List[str]
    ) -> Optional[CriticalPathPreview]:
        engine_tasks = [
            Task(
                id=t.temp_id,
                optimistic=t.optimistic_days,
                most_likely=t.most_likely_days,
                pessimistic=t.pessimistic_days,
            )
            for t in tasks
        ]
        engine_deps = [
            Dependency(d.predecessor, d.successor, d.dep_type, d.lag_days) for d in deps
        ]
        # Deja que el CPMError (ciclos, refs inválidas) se propague: la EDT no sirve.
        result = CPMEngine(engine_tasks, engine_deps).compute()
        if not result.critical_path:
            warnings.append("No se pudo determinar un camino crítico único.")
        return CriticalPathPreview(
            project_duration_days=result.project_duration,
            critical_path=result.critical_path,
            pert_std_dev=result.pert_std_dev,
        )

    def _fit_to_horizon(
        self,
        tasks: List[WBSTask],
        deps: List[WBSDependency],
        horizon: float,
        warnings: List[str],
    ):
        preview = self._cpm_preview(tasks, deps, warnings)
        current = preview.project_duration_days if preview else 0
        if current <= 0:
            return tasks, preview
        factor = horizon / current
        # Solo reescalamos si la diferencia es significativa (>5%).
        if abs(factor - 1.0) <= 0.05:
            return tasks, preview
        scaled: List[WBSTask] = []
        for t in tasks:
            scaled.append(
                WBSTask(
                    temp_id=t.temp_id,
                    name=t.name,
                    description=t.description,
                    phase=t.phase,
                    optimistic_days=round(max(0.5, t.optimistic_days * factor), 1),
                    most_likely_days=round(max(0.5, t.most_likely_days * factor), 1),
                    pessimistic_days=round(max(0.5, t.pessimistic_days * factor), 1),
                    cost_estimated=t.cost_estimated,
                    is_milestone=t.is_milestone,
                )
            )
        new_preview = self._cpm_preview(scaled, deps, warnings)
        verb = "comprimió" if factor < 1 else "expandió"
        warnings.append(
            f"El plan base duraba {current:.0f} días; se {verb} al horizonte de "
            f"{horizon:.0f} días (factor {factor:.2f})."
        )
        return scaled, new_preview


def breakdown_idea(req: BreakdownRequest) -> BreakdownResult:
    """Función de conveniencia con el servicio por defecto."""
    return BreakdownService().run(req)
