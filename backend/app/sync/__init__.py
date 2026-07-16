"""Sincronización offline de Campo Crítico.

Los técnicos en campo trabajan sin señal: los cambios se encolan localmente como
*mutaciones* y, al recuperar conectividad, se envían al servidor. El motor de
sincronización aplica esas mutaciones al estado del servidor con resolución de
conflictos **última-escritura-gana a nivel de campo** (last-write-wins), marcando
los conflictos para revisión.
"""
from .engine import (
    SyncError,
    apply_mutations,
    empty_state,
    high_water_mark,
)

__all__ = [
    "SyncError",
    "apply_mutations",
    "empty_state",
    "high_water_mark",
]
