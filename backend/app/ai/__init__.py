"""Módulo A — Asistente IA de Desglose de Campo Crítico.

Transforma una idea en texto libre (o voz transcrita) en una Estructura de
Desglose del Trabajo (EDT/WBS) validada, lista para el motor CPM/PERT.
"""
from .breakdown import BreakdownService, breakdown_idea
from .providers import HeuristicProvider, LLMProvider, OpenAICompatibleProvider
from .schemas import (
    BreakdownRequest,
    BreakdownResult,
    WBSDependency,
    WBSTask,
)

__all__ = [
    "BreakdownService",
    "breakdown_idea",
    "HeuristicProvider",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "BreakdownRequest",
    "BreakdownResult",
    "WBSDependency",
    "WBSTask",
]
