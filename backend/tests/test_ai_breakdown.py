"""Pruebas del asistente IA de desglose (Módulo A)."""
import pytest

from app.ai import BreakdownService, HeuristicProvider
from app.ai.providers import detect_horizon_days
from app.ai.schemas import BreakdownRequest
from app.cpm import CPMError


def _service():
    # Forzamos el proveedor heurístico como primario para pruebas deterministas.
    return BreakdownService(provider=HeuristicProvider(), fallback=HeuristicProvider())


def test_detect_horizon_days():
    assert detect_horizon_days("digitalizar el censo en 3 meses") == 90
    assert detect_horizon_days("entregar en 6 semanas") == 42
    assert detect_horizon_days("plazo de 45 días") == 45
    assert detect_horizon_days("un proyecto grande") is None


def test_breakdown_produces_valid_wbs_and_preview():
    req = BreakdownRequest(
        raw_text="Queremos digitalizar el censo de productores de la región norte."
    )
    result = _service().run(req)

    assert result.provider == "heuristic"
    assert len(result.tasks) >= 4
    # temp_id únicos
    ids = [t.temp_id for t in result.tasks]
    assert len(ids) == len(set(ids))
    # PERT válido en cada tarea: o <= m <= p
    for t in result.tasks:
        assert t.optimistic_days <= t.most_likely_days <= t.pessimistic_days
    # Vista previa CPM calculada
    assert result.preview is not None
    assert result.preview.project_duration_days > 0
    assert len(result.preview.critical_path) >= 1


def test_domain_detection_selects_software_template():
    req = BreakdownRequest(raw_text="Construir una plataforma web y app móvil para productores.")
    result = _service().run(req)
    names = " ".join(t.name.lower() for t in result.tasks)
    assert "backend" in names or "frontend" in names


def test_horizon_scaling_compresses_plan():
    # El texto pide 30 días; la plantilla base dura más, así que debe comprimirse.
    req = BreakdownRequest(
        raw_text="Levantamiento y censo de parcelas en 30 días.",
    )
    result = _service().run(req)
    assert result.detected_horizon_days == 30
    assert result.preview is not None
    # Tras el escalado, la duración queda cerca del horizonte (tolerancia por redondeo).
    assert result.preview.project_duration_days == pytest.approx(30, abs=6)
    assert any("horizonte" in w for w in result.warnings)


def test_explicit_target_horizon_overrides_detection():
    req = BreakdownRequest(
        raw_text="Programa de capacitación a brigadas.",
        target_horizon_days=20,
    )
    result = _service().run(req)
    assert result.detected_horizon_days == 20
    assert result.preview.project_duration_days == pytest.approx(20, abs=5)


def test_generated_graph_has_no_cycles():
    # Todas las plantillas deben producir un DAG válido (no lanzar CPMError).
    for text in [
        "censo de productores",
        "desarrollar un sistema digital",
        "taller de formación",
        "ciclo de siembra y cosecha",
        "iniciativa general de mejora",
    ]:
        result = _service().run(BreakdownRequest(raw_text=text))
        assert result.preview.project_duration_days > 0


def test_invalid_schema_from_provider_is_rejected():
    class BadProvider:
        name = "bad"

        def generate(self, raw_text, target_horizon_days):
            # p > ... pero o > m viola el orden PERT -> ValidationError -> CPMError
            return {
                "summary": "malo",
                "tasks": [
                    {
                        "temp_id": "X",
                        "name": "Tarea inválida",
                        "optimistic_days": 10,
                        "most_likely_days": 2,
                        "pessimistic_days": 3,
                    }
                ],
                "dependencies": [],
            }

    svc = BreakdownService(provider=BadProvider(), fallback=BadProvider())
    with pytest.raises(CPMError):
        svc.run(BreakdownRequest(raw_text="algo que produce EDT inválida"))


def test_cycle_from_provider_is_rejected():
    class CycleProvider:
        name = "cycle"

        def generate(self, raw_text, target_horizon_days):
            return {
                "summary": "ciclo",
                "tasks": [
                    {"temp_id": "A", "name": "A", "optimistic_days": 1, "most_likely_days": 2, "pessimistic_days": 3},
                    {"temp_id": "B", "name": "B", "optimistic_days": 1, "most_likely_days": 2, "pessimistic_days": 3},
                ],
                "dependencies": [
                    {"predecessor": "A", "successor": "B"},
                    {"predecessor": "B", "successor": "A"},
                ],
            }

    svc = BreakdownService(provider=CycleProvider(), fallback=CycleProvider())
    with pytest.raises(CPMError):
        svc.run(BreakdownRequest(raw_text="EDT con ciclo"))
