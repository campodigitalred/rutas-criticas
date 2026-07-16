"""Módulo E — Exportación y reportes de Campo Crítico.

* ``evm``       — Dashboard de Valor Ganado (Earned Value Management).
* ``exporters`` — Exportadores a MS Project (MSPDI XML), Primavera P6 (XER) y CSV.
"""
from .evm import EVMResult, EVMTask, compute_evm, evm_from_dict
from .exporters import (
    export_csv_from_dict,
    export_msproject_from_dict,
    export_p6_xer_from_dict,
    to_csv,
    to_msproject_xml,
    to_p6_xer,
)

__all__ = [
    "EVMResult",
    "EVMTask",
    "compute_evm",
    "evm_from_dict",
    "to_csv",
    "to_msproject_xml",
    "to_p6_xer",
    "export_csv_from_dict",
    "export_msproject_from_dict",
    "export_p6_xer_from_dict",
]
