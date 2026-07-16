"""Pruebas del dashboard de Valor Ganado (EVM) — Módulo E."""
import pytest

from app.cpm import Dependency
from app.reporting import EVMTask, compute_evm
from app.reporting.evm import EVMError


def _chain():
    # A(0..10) -> B(10..20). Duración 20. Costos: A=1000, B=1000. BAC=2000.
    tasks = [
        EVMTask("A", duration=10, planned_cost=1000),
        EVMTask("B", duration=10, planned_cost=1000),
    ]
    deps = [Dependency("A", "B")]
    return tasks, deps


def test_bac_ev_ac_basics():
    tasks, deps = _chain()
    tasks[0].progress_pct = 100
    tasks[0].actual_cost = 1200   # A costó más de lo planeado
    tasks[1].progress_pct = 0
    r = compute_evm(tasks, deps, as_of_day=10)
    assert r.bac == 2000
    assert r.ev == 1000            # A completada al 100% de su presupuesto
    assert r.ac == 1200
    assert r.cv == -200            # sobrecosto
    assert r.cpi == pytest.approx(1000 / 1200, abs=1e-4)


def test_planned_value_and_spi():
    tasks, deps = _chain()
    # Al día 10, A debería estar 100% (PV incluye todo A) y B 0% -> PV=1000.
    tasks[0].progress_pct = 100
    tasks[0].actual_cost = 1000
    r = compute_evm(tasks, deps, as_of_day=10)
    assert r.pv == 1000
    assert r.ev == 1000
    assert r.sv == 0
    assert r.spi == pytest.approx(1.0, abs=1e-4)
    assert r.health == "on_track"


def test_behind_schedule_low_spi():
    tasks, deps = _chain()
    # Al día 10 A debería estar completa (PV=1000) pero solo va al 50%.
    tasks[0].progress_pct = 50
    tasks[0].actual_cost = 500
    r = compute_evm(tasks, deps, as_of_day=10)
    assert r.pv == 1000
    assert r.ev == 500
    assert r.spi == pytest.approx(0.5, abs=1e-4)
    assert r.health == "behind"


def test_eac_and_vac():
    tasks, deps = _chain()
    tasks[0].progress_pct = 100
    tasks[0].actual_cost = 1500   # CPI = 1000/1500 = 0.667
    r = compute_evm(tasks, deps, as_of_day=10)
    # EAC = BAC / CPI = 2000 / 0.667 = 3000
    assert r.eac == pytest.approx(3000, abs=1)
    assert r.vac == pytest.approx(-1000, abs=1)   # sobrecosto proyectado
    assert r.etc == pytest.approx(1500, abs=1)


def test_percent_complete_and_spent():
    tasks, deps = _chain()
    tasks[0].progress_pct = 100
    tasks[0].actual_cost = 1000
    r = compute_evm(tasks, deps, as_of_day=10)
    assert r.percent_complete == 50   # EV 1000 / BAC 2000
    assert r.percent_spent == 50


def test_pv_none_without_as_of():
    tasks, deps = _chain()
    r = compute_evm(tasks, deps, as_of_day=None)
    assert r.pv is None
    assert r.spi is None
    assert r.sv is None
    # Métricas de costo sí disponibles.
    assert r.bac == 2000


def test_pv_curve_monotonic_and_reaches_bac():
    tasks, deps = _chain()
    r = compute_evm(tasks, deps, as_of_day=10)
    pv_vals = [p["pv"] for p in r.pv_curve]
    assert pv_vals == sorted(pv_vals)          # no decreciente
    assert pv_vals[0] == 0
    assert pv_vals[-1] == pytest.approx(2000)   # al final, PV == BAC
    # El punto de corte incluye EV y AC.
    cut = [p for p in r.pv_curve if p["day"] == 10][0]
    assert "ev" in cut and "ac" in cut


def test_invalid_progress():
    with pytest.raises(EVMError):
        EVMTask("X", duration=5, progress_pct=120)


def test_zero_budget_graceful():
    tasks = [EVMTask("A", duration=5, planned_cost=0)]
    r = compute_evm(tasks, [], as_of_day=5)
    assert r.bac == 0
    assert r.percent_complete == 0
    assert r.cpi is None  # sin costo real
