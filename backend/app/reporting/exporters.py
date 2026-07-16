"""Exportadores profesionales de la ruta crítica.

Genera, de forma determinista y sin dependencias externas:

* **MS Project (MSPDI XML)** — abrible en Microsoft Project.
* **Primavera P6 (XER)** — formato de intercambio de P6 (versión simplificada).
* **CSV** — compatible con Excel / hojas de cálculo.

Todos parten del cálculo CPM (fechas tempranas/tardías, holguras, camino crítico)
para que las tareas exportadas conserven su programación.
"""
from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from ..cpm import CPMEngine, Dependency, Task

HOURS_PER_DAY = 8

# Mapeo de tipos de dependencia a los códigos de cada herramienta.
_MSP_TYPE = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}   # MS Project PredecessorLink.Type
_P6_TYPE = {"FS": "PR_FS", "SS": "PR_SS", "FF": "PR_FF", "SF": "PR_SF"}


@dataclass
class _Prepared:
    tasks: List[Task]
    result: object
    names: Dict[str, str]
    costs: Dict[str, float]
    progress: Dict[str, float]
    preds: Dict[str, List[Dependency]]     # successor_id -> [Dependency]
    milestones: Dict[str, bool]
    order: List[str]


def _prepare(payload: dict) -> Tuple[_Prepared, List[Dependency]]:
    raw_tasks = payload.get("tasks", [])
    if not raw_tasks:
        raise ValueError("No hay tareas para exportar.")
    tasks = [
        Task(
            id=str(t["id"]),
            duration=float(t.get("duration", 0) or 0),
            optimistic=_opt(t, "optimistic"),
            most_likely=_opt(t, "most_likely"),
            pessimistic=_opt(t, "pessimistic"),
        )
        for t in raw_tasks
    ]
    names = {str(t["id"]): str(t.get("name", t["id"])) for t in raw_tasks}
    costs = {str(t["id"]): float(t.get("planned_cost", t.get("cost", 0)) or 0) for t in raw_tasks}
    progress = {str(t["id"]): float(t.get("progress_pct", 0) or 0) for t in raw_tasks}
    milestones = {
        str(t["id"]): bool(t.get("is_milestone", False)) or float(t.get("duration", 0) or 0) == 0
        for t in raw_tasks
    }
    deps = [
        Dependency(
            predecessor=str(d["predecessor"]),
            successor=str(d["successor"]),
            dep_type=str(d.get("dep_type", "FS")),
            lag=float(d.get("lag", 0) or 0),
        )
        for d in payload.get("dependencies", [])
    ]
    result = CPMEngine(tasks, deps).compute()
    preds: Dict[str, List[Dependency]] = {t.id: [] for t in tasks}
    for d in deps:
        preds[d.successor].append(d)
    order = list(result.tasks.keys())
    return (
        _Prepared(tasks, result, names, costs, progress, preds, milestones, order),
        deps,
    )


def _opt(d: dict, key: str) -> Optional[float]:
    v = d.get(key)
    return float(v) if v is not None else None


# --------------------------------------------------------------------------- #
# MS Project (MSPDI XML)
# --------------------------------------------------------------------------- #
def to_msproject_xml(payload: dict) -> str:
    prep, _ = _prepare(payload)
    start_date = _parse_date(payload.get("start_date")) or datetime(2025, 1, 6)  # lunes
    project_name = str(payload.get("project_name", "Campo Crítico"))

    NS = "http://schemas.microsoft.com/project"
    ET.register_namespace("", NS)
    proj = ET.Element(f"{{{NS}}}Project")

    def sub(parent, tag, text):
        el = ET.SubElement(parent, f"{{{NS}}}{tag}")
        el.text = str(text)
        return el

    sub(proj, "Name", project_name)
    sub(proj, "StartDate", _iso(start_date))
    sub(proj, "DurationFormat", 7)         # 7 = días
    sub(proj, "CalendarUID", 1)

    tasks_el = ET.SubElement(proj, f"{{{NS}}}Tasks")
    uid = {tid: i + 1 for i, tid in enumerate(prep.order)}

    for i, tid in enumerate(prep.order):
        tr = prep.result.tasks[tid]
        t_el = ET.SubElement(tasks_el, f"{{{NS}}}Task")
        sub(t_el, "UID", uid[tid])
        sub(t_el, "ID", i + 1)
        sub(t_el, "Name", prep.names[tid])
        sub(t_el, "Active", 1)
        sub(t_el, "Manual", 0)
        sub(t_el, "Duration", _iso_duration(tr.duration))
        sub(t_el, "DurationFormat", 7)
        sub(t_el, "Start", _iso(start_date + timedelta(days=tr.early_start)))
        sub(t_el, "Finish", _iso(start_date + timedelta(days=tr.early_finish)))
        sub(t_el, "Milestone", 1 if prep.milestones[tid] else 0)
        sub(t_el, "PercentComplete", int(round(prep.progress[tid])))
        sub(t_el, "Critical", 1 if tr.is_critical else 0)
        sub(t_el, "TotalSlack", _iso_duration(tr.total_slack))
        for dep in prep.preds[tid]:
            link = ET.SubElement(t_el, f"{{{NS}}}PredecessorLink")
            sub(link, "PredecessorUID", uid[dep.predecessor])
            sub(link, "Type", _MSP_TYPE.get(dep.dep_type, 1))
            sub(link, "LinkLag", int(round(dep.lag * HOURS_PER_DAY * 60 * 10)))  # décimas de min
            sub(link, "LagFormat", 7)

    xml_bytes = ET.tostring(proj, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _iso_duration(days: float) -> str:
    """Duración MSPDI en ISO-8601 (horas), 8 h por día."""
    total_minutes = int(round(days * HOURS_PER_DAY * 60))
    h, m = divmod(total_minutes, 60)
    return f"PT{h}H{m}M0S"


def _parse_date(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Primavera P6 (XER, simplificado)
# --------------------------------------------------------------------------- #
def to_p6_xer(payload: dict) -> str:
    prep, deps = _prepare(payload)
    start_date = _parse_date(payload.get("start_date")) or datetime(2025, 1, 6)
    project_id = str(payload.get("project_id", "CC1"))
    project_name = str(payload.get("project_name", "Campo Crítico"))
    now = datetime(2025, 1, 6, 0, 0, 0)

    lines: List[str] = []
    lines.append(
        "\t".join(
            ["ERMHDR", "18.8", _xer_date(now), "Project", "CampoDigital",
             "CampoDigital", "USD", "Campo Crítico Export"]
        )
    )

    def table(name: str, fields: List[str], rows: List[List[str]]):
        lines.append(f"%T\t{name}")
        lines.append("%F\t" + "\t".join(fields))
        for row in rows:
            lines.append("%R\t" + "\t".join(_xer_val(v) for v in row))

    # PROJECT
    table(
        "PROJECT",
        ["proj_id", "proj_short_name", "plan_start_date", "last_recalc_date"],
        [[project_id, project_name, _xer_date(start_date), _xer_date(now)]],
    )

    # TASK
    task_fields = [
        "task_id", "proj_id", "task_code", "task_name", "task_type",
        "target_drtn_hr_cnt", "phys_complete_pct", "early_start_date",
        "early_end_date", "total_float_hr_cnt", "driving_path_flag",
    ]
    task_rows = []
    for tid in prep.order:
        tr = prep.result.tasks[tid]
        task_rows.append([
            tid, project_id, tid, prep.names[tid],
            "TT_Mile" if prep.milestones[tid] else "TT_Task",
            round(tr.duration * HOURS_PER_DAY, 2),
            round(prep.progress[tid], 2),
            _xer_date(start_date + timedelta(days=tr.early_start)),
            _xer_date(start_date + timedelta(days=tr.early_finish)),
            round(tr.total_slack * HOURS_PER_DAY, 2),
            "Y" if tr.is_critical else "N",
        ])
    table("TASK", task_fields, task_rows)

    # TASKPRED (dependencias)
    pred_fields = ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_type", "lag_hr_cnt"]
    pred_rows = []
    for i, d in enumerate(deps, start=1):
        pred_rows.append([
            i, d.successor, d.predecessor, project_id,
            _P6_TYPE.get(d.dep_type, "PR_FS"),
            round(d.lag * HOURS_PER_DAY, 2),
        ])
    table("TASKPRED", pred_fields, pred_rows)

    lines.append("%E")
    return "\n".join(lines) + "\n"


def _xer_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _xer_val(v) -> str:
    return "" if v is None else str(v)


# --------------------------------------------------------------------------- #
# CSV (Excel)
# --------------------------------------------------------------------------- #
def to_csv(payload: dict) -> str:
    prep, _ = _prepare(payload)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "ID", "Tarea", "Duración (d)", "Inicio temprano (ES)", "Fin temprano (EF)",
        "Inicio tardío (LS)", "Fin tardío (LF)", "Holgura total", "Crítica",
        "Predecesoras", "Avance %", "Costo planeado",
    ])
    for tid in prep.order:
        tr = prep.result.tasks[tid]
        preds = "; ".join(
            f"{d.predecessor}({d.dep_type}{('+' + str(_num(d.lag))) if d.lag else ''})"
            for d in prep.preds[tid]
        )
        writer.writerow([
            tid, prep.names[tid], _num(tr.duration), _num(tr.early_start),
            _num(tr.early_finish), _num(tr.late_start), _num(tr.late_finish),
            _num(tr.total_slack), "Sí" if tr.is_critical else "No",
            preds, _num(prep.progress[tid]), _num(prep.costs[tid]),
        ])
    return buf.getvalue()


def _num(x: float):
    return int(x) if float(x).is_integer() else round(x, 2)


# --------------------------------------------------------------------------- #
# Envoltorios para la API
# --------------------------------------------------------------------------- #
def export_msproject_from_dict(payload: dict) -> str:
    return to_msproject_xml(payload)


def export_p6_xer_from_dict(payload: dict) -> str:
    return to_p6_xer(payload)


def export_csv_from_dict(payload: dict) -> str:
    return to_csv(payload)
