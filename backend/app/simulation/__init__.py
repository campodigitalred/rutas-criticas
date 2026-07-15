"""Módulo D — Simulación de riesgo (Monte Carlo) de Campo Crítico.

Simula la incertidumbre de las duraciones (distribución Beta-PERT) sobre el
motor CPM para estimar la distribución de la fecha final, la probabilidad de
cumplir un plazo, el índice de criticidad de cada tarea y el impacto en el
presupuesto.
"""
from .montecarlo import (
    MonteCarloResult,
    SimTask,
    run_montecarlo,
    run_montecarlo_from_dict,
    sample_pert,
)

__all__ = [
    "MonteCarloResult",
    "SimTask",
    "run_montecarlo",
    "run_montecarlo_from_dict",
    "sample_pert",
]
