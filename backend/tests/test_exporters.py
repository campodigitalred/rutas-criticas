"""Pruebas de los exportadores (MS Project, Primavera P6, CSV) — Módulo E."""
import csv
import io
import xml.etree.ElementTree as ET

import pytest

from app.reporting import to_csv, to_msproject_xml, to_p6_xer

NS = "http://schemas.microsoft.com/project"


def _payload():
    return {
        "project_name": "Censo Norte",
        "tasks": [
            {"id": "T1", "name": "Diseño", "duration": 8, "planned_cost": 1000, "progress_pct": 100},
            {"id": "T2", "name": "Campo", "duration": 20, "planned_cost": 5000, "progress_pct": 30},
            {"id": "T3", "name": "Cierre", "duration": 0, "is_milestone": True},
        ],
        "dependencies": [
            {"predecessor": "T1", "successor": "T2", "dep_type": "FS", "lag": 2},
            {"predecessor": "T2", "successor": "T3", "dep_type": "SS"},
        ],
    }


# ------------------------------- MS Project -------------------------------- #
def test_msproject_wellformed_and_task_count():
    xml = to_msproject_xml(_payload())
    root = ET.fromstring(xml)
    assert root.tag == f"{{{NS}}}Project"
    tasks = root.findall(f"{{{NS}}}Tasks/{{{NS}}}Task")
    assert len(tasks) == 3


def test_msproject_dependency_type_mapping():
    xml = to_msproject_xml(_payload())
    root = ET.fromstring(xml)
    # Encontrar la tarea T2 y verificar su PredecessorLink FS (Type=1).
    links_type = []
    for task in root.findall(f"{{{NS}}}Tasks/{{{NS}}}Task"):
        for link in task.findall(f"{{{NS}}}PredecessorLink"):
            links_type.append(link.find(f"{{{NS}}}Type").text)
    # Una FS (1) y una SS (3).
    assert "1" in links_type
    assert "3" in links_type


def test_msproject_milestone_and_lag():
    xml = to_msproject_xml(_payload())
    root = ET.fromstring(xml)
    milestones = [
        t.find(f"{{{NS}}}Milestone").text
        for t in root.findall(f"{{{NS}}}Tasks/{{{NS}}}Task")
    ]
    assert "1" in milestones  # T3 es hito
    # Lag de 2 días -> 2*8*60*10 = 9600 décimas de minuto en alguna liga.
    lags = [
        link.find(f"{{{NS}}}LinkLag").text
        for t in root.findall(f"{{{NS}}}Tasks/{{{NS}}}Task")
        for link in t.findall(f"{{{NS}}}PredecessorLink")
    ]
    assert "9600" in lags


# ------------------------------- Primavera P6 ------------------------------ #
def test_p6_xer_structure():
    xer = to_p6_xer(_payload())
    lines = xer.splitlines()
    assert lines[0].startswith("ERMHDR")
    assert "%T\tPROJECT" in lines
    assert "%T\tTASK" in lines
    assert "%T\tTASKPRED" in lines
    assert lines[-1] == "%E"


def test_p6_xer_task_and_pred_rows():
    xer = to_p6_xer(_payload())
    lines = xer.splitlines()
    task_rows = _rows_of_table(lines, "TASK")
    pred_rows = _rows_of_table(lines, "TASKPRED")
    assert len(task_rows) == 3
    assert len(pred_rows) == 2
    # Mapeo de tipos: debe aparecer PR_FS y PR_SS.
    joined = "\n".join("\t".join(r) for r in pred_rows)
    assert "PR_FS" in joined
    assert "PR_SS" in joined


def _rows_of_table(lines, table_name):
    rows = []
    in_table = False
    for ln in lines:
        if ln.startswith("%T\t"):
            in_table = ln == f"%T\t{table_name}"
        elif in_table and ln.startswith("%R\t"):
            rows.append(ln.split("\t")[1:])
    return rows


# ---------------------------------- CSV ------------------------------------ #
def test_csv_header_and_rows():
    out = to_csv(_payload())
    reader = list(csv.reader(io.StringIO(out)))
    header = reader[0]
    assert "Tarea" in header and "Holgura total" in header and "Crítica" in header
    assert len(reader) == 4  # encabezado + 3 tareas


def test_csv_predecessor_annotation():
    out = to_csv(_payload())
    # La columna de predecesoras debe anotar el tipo y el lag (FS+2).
    assert "T1(FS+2)" in out
    assert "T2(SS)" in out


def test_empty_tasks_raise():
    with pytest.raises(ValueError):
        to_csv({"tasks": []})
