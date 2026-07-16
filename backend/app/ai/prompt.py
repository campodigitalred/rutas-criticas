"""Construcción del prompt para el desglose de ideas en EDT/WBS."""
from __future__ import annotations

import json

SYSTEM_PROMPT = """\
Eres un planificador experto de proyectos de Agencia Campo Digital, especializada en
tecnología, agricultura, desarrollo rural y transformación digital.

Tu tarea: descomponer la idea o proyecto del usuario en una Estructura de Desglose del
Trabajo (EDT/WBS) accionable, con estimaciones PERT de tres puntos y dependencias lógicas.

Reglas:
- Devuelve EXCLUSIVAMENTE un objeto JSON válido, sin texto adicional ni markdown.
- Genera entre 4 y 12 tareas concretas y verificables (no objetivos vagos).
- Agrupa las tareas por fase (p.ej. "Planeación", "Campo", "Datos", "Cierre").
- Considera el contexto rural: conectividad intermitente, logística de campo, clima,
  capacitación de brigadas y validación de datos.
- Estimaciones en días: optimistic <= most_likely <= pessimistic, todas > 0.
- Dependencias con tipo FS (fin-inicio), SS (inicio-inicio), FF (fin-fin) o SF
  (inicio-fin) y lag_days (puede ser 0 o negativo para adelantos).
- El grafo de dependencias NO debe tener ciclos.
- Usa temp_id cortos y únicos (T1, T2, ...).

Formato JSON de salida:
{
  "summary": "resumen breve del proyecto",
  "tasks": [
    {"temp_id": "T1", "name": "...", "phase": "...", "description": "...",
     "optimistic_days": 3, "most_likely_days": 5, "pessimistic_days": 9,
     "cost_estimated": 0, "is_milestone": false}
  ],
  "dependencies": [
    {"predecessor": "T1", "successor": "T2", "dep_type": "FS", "lag_days": 0}
  ]
}
"""


def build_user_prompt(raw_text: str, target_horizon_days: float | None) -> str:
    parts = [f"Idea / proyecto a desglosar:\n\"\"\"\n{raw_text.strip()}\n\"\"\""]
    if target_horizon_days:
        parts.append(
            f"\nHorizonte objetivo: aproximadamente {target_horizon_days:.0f} días. "
            "Ajusta el alcance y las duraciones para que el camino crítico quepa "
            "razonablemente en ese plazo."
        )
    parts.append("\nDevuelve solo el JSON con la EDT.")
    return "\n".join(parts)


def build_messages(raw_text: str, target_horizon_days: float | None) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(raw_text, target_horizon_days)},
    ]


def example_output() -> str:
    """Ejemplo de salida bien formada (útil para docs y pruebas)."""
    return json.dumps(
        {
            "summary": "Digitalización del censo de productores de la región norte.",
            "tasks": [
                {
                    "temp_id": "T1",
                    "name": "Diseño del instrumento de censo",
                    "phase": "Planeación",
                    "optimistic_days": 5,
                    "most_likely_days": 8,
                    "pessimistic_days": 14,
                    "cost_estimated": 0,
                    "is_milestone": False,
                }
            ],
            "dependencies": [],
        },
        ensure_ascii=False,
        indent=2,
    )
