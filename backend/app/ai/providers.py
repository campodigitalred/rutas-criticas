"""Proveedores de generación de EDT.

Dos implementaciones intercambiables:

* ``OpenAICompatibleProvider`` — llama a un endpoint de chat compatible con la API
  de OpenAI (configurable por variables de entorno). Uso en producción.
* ``HeuristicProvider`` — genera la EDT de forma determinista y **sin conexión**,
  a partir de plantillas de dominio (agro / rural / digital) y detección de plazos.
  Es el respaldo cuando no hay red o no hay API key configurada, y el motor de las
  pruebas.

Ambos devuelven un ``dict`` con el mismo formato (``summary``, ``tasks``,
``dependencies``) que el orquestador valida contra los esquemas Pydantic.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional, Protocol, runtime_checkable

# --------------------------------------------------------------------------- #
# Interfaz
# --------------------------------------------------------------------------- #
@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def generate(self, raw_text: str, target_horizon_days: Optional[float]) -> dict:
        """Devuelve un dict con las claves summary, tasks, dependencies."""
        ...


class LLMProviderError(Exception):
    """Fallo al obtener o parsear la respuesta del proveedor."""


# --------------------------------------------------------------------------- #
# Proveedor LLM (compatible OpenAI)
# --------------------------------------------------------------------------- #
class OpenAICompatibleProvider:
    """Cliente para un endpoint /chat/completions compatible con OpenAI.

    Configuración por entorno:
      CAMPO_LLM_API_KEY   (obligatoria para activarlo)
      CAMPO_LLM_BASE_URL  (default https://api.openai.com/v1)
      CAMPO_LLM_MODEL     (default gpt-4o-mini)
    """

    name = "llm"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or os.getenv("CAMPO_LLM_API_KEY")
        self.base_url = (base_url or os.getenv("CAMPO_LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.getenv("CAMPO_LLM_MODEL", "gpt-4o-mini")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate(self, raw_text: str, target_horizon_days: Optional[float]) -> dict:
        if not self.is_configured:
            raise LLMProviderError("CAMPO_LLM_API_KEY no configurada.")
        # Importación diferida: httpx solo se necesita en este camino.
        import httpx

        from .prompt import build_messages

        payload = {
            "model": self.model,
            "messages": build_messages(raw_text, target_horizon_days),
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - se normaliza a error de dominio
            raise LLMProviderError(f"Fallo al invocar el LLM: {exc}") from exc
        return _extract_json(content)


def _extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON del texto (tolera fences de markdown)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise LLMProviderError("La respuesta del LLM no contiene JSON válido.")


# --------------------------------------------------------------------------- #
# Proveedor heurístico (offline)
# --------------------------------------------------------------------------- #
# Palabras clave -> plantilla de dominio.
_DOMAIN_KEYWORDS = {
    "data_collection": ["censo", "encuesta", "levantamiento", "padrón", "padron", "registro de productores"],
    "software": ["digitaliz", "plataforma", "app", "aplicación", "aplicacion", "sistema", "software", "portal", "tablero"],
    "training": ["capacit", "formación", "formacion", "taller", "escuela de campo", "adiestr"],
    "agri_field": ["riego", "cultivo", "siembra", "cosecha", "parcela", "invernadero", "suelo"],
}

# Detección de horizonte temporal en el texto ("3 meses", "6 semanas"...).
_TIME_UNITS = {
    "día": 1, "dia": 1, "días": 1, "dias": 1,
    "semana": 7, "semanas": 7,
    "mes": 30, "meses": 30,
    "año": 365, "ano": 365, "años": 365, "anos": 365,
}
_TIME_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(días|dias|día|dia|semanas|semana|meses|mes|años|anos|año|ano)",
    re.IGNORECASE,
)


def detect_horizon_days(text: str) -> Optional[float]:
    m = _TIME_RE.search(text)
    if not m:
        return None
    qty = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    return qty * _TIME_UNITS.get(unit, 1)


def _detect_domain(text: str) -> str:
    low = text.lower()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(k in low for k in keywords):
            return domain
    return "generic"


def _t(temp_id, name, phase, o, m, p, milestone=False):
    return {
        "temp_id": temp_id,
        "name": name,
        "phase": phase,
        "optimistic_days": o,
        "most_likely_days": m,
        "pessimistic_days": p,
        "cost_estimated": 0,
        "is_milestone": milestone,
    }


def _dep(pre, suc, dep_type="FS", lag=0):
    return {"predecessor": pre, "successor": suc, "dep_type": dep_type, "lag_days": lag}


def _template_data_collection():
    tasks = [
        _t("T1", "Diseño del instrumento de recolección", "Planeación", 5, 8, 14),
        _t("T2", "Cartografía y muestreo del territorio", "Planeación", 3, 5, 9),
        _t("T3", "Capacitación de brigadas de campo", "Preparación", 3, 5, 8),
        _t("T4", "Levantamiento en campo", "Campo", 15, 22, 40),
        _t("T5", "Digitalización y captura de datos", "Datos", 8, 12, 20),
        _t("T6", "Validación y limpieza de datos", "Datos", 6, 10, 16),
        _t("T7", "Informe de resultados y entrega", "Cierre", 3, 4, 7, milestone=True),
    ]
    deps = [
        _dep("T1", "T2"), _dep("T1", "T3"), _dep("T3", "T4"),
        _dep("T2", "T4"), _dep("T4", "T5", "SS", 5), _dep("T4", "T6"),
        _dep("T5", "T6"), _dep("T6", "T7"),
    ]
    return "Proyecto de recolección/censo de datos en territorio rural.", tasks, deps


def _template_software():
    tasks = [
        _t("T1", "Levantamiento de requerimientos", "Descubrimiento", 4, 6, 10),
        _t("T2", "Diseño UX/UI y arquitectura", "Diseño", 5, 8, 13),
        _t("T3", "Desarrollo backend y API", "Construcción", 12, 18, 30),
        _t("T4", "Desarrollo frontend", "Construcción", 10, 16, 26),
        _t("T5", "Modo offline y sincronización", "Construcción", 5, 8, 14),
        _t("T6", "Pruebas y control de calidad", "Calidad", 5, 8, 13),
        _t("T7", "Despliegue y capacitación", "Cierre", 3, 5, 8, milestone=True),
    ]
    deps = [
        _dep("T1", "T2"), _dep("T2", "T3"), _dep("T2", "T4"),
        _dep("T3", "T4", "SS", 3), _dep("T3", "T5"), _dep("T4", "T6"),
        _dep("T5", "T6"), _dep("T6", "T7"),
    ]
    return "Proyecto de desarrollo de plataforma/aplicación digital.", tasks, deps


def _template_training():
    tasks = [
        _t("T1", "Diagnóstico de necesidades de capacitación", "Planeación", 3, 5, 8),
        _t("T2", "Diseño curricular y materiales", "Diseño", 5, 8, 13),
        _t("T3", "Selección y convocatoria de participantes", "Logística", 3, 5, 9),
        _t("T4", "Impartición de talleres", "Ejecución", 8, 12, 20),
        _t("T5", "Evaluación de aprendizaje", "Evaluación", 3, 4, 7),
        _t("T6", "Informe y certificación", "Cierre", 2, 3, 5, milestone=True),
    ]
    deps = [
        _dep("T1", "T2"), _dep("T1", "T3"), _dep("T2", "T4"),
        _dep("T3", "T4"), _dep("T4", "T5", "SS", 2), _dep("T5", "T6"),
    ]
    return "Programa de capacitación/formación.", tasks, deps


def _template_agri_field():
    tasks = [
        _t("T1", "Análisis de suelo y planeación agronómica", "Planeación", 3, 5, 9),
        _t("T2", "Preparación del terreno", "Preparación", 4, 7, 12),
        _t("T3", "Instalación de sistema de riego", "Infraestructura", 5, 8, 15),
        _t("T4", "Siembra", "Producción", 3, 5, 8),
        _t("T5", "Manejo del cultivo (labores)", "Producción", 20, 30, 50),
        _t("T6", "Cosecha", "Cierre", 5, 8, 14, milestone=True),
    ]
    deps = [
        _dep("T1", "T2"), _dep("T2", "T3"), _dep("T2", "T4"),
        _dep("T3", "T4", "FF", 0), _dep("T4", "T5"), _dep("T5", "T6"),
    ]
    return "Proyecto agrícola de campo (ciclo productivo).", tasks, deps


def _template_generic():
    tasks = [
        _t("T1", "Definición de alcance y objetivos", "Inicio", 2, 4, 7),
        _t("T2", "Planeación detallada y recursos", "Planeación", 3, 5, 9),
        _t("T3", "Ejecución — fase 1", "Ejecución", 8, 14, 24),
        _t("T4", "Ejecución — fase 2", "Ejecución", 8, 14, 24),
        _t("T5", "Seguimiento y control de calidad", "Control", 4, 6, 10),
        _t("T6", "Cierre y entrega", "Cierre", 2, 3, 5, milestone=True),
    ]
    deps = [
        _dep("T1", "T2"), _dep("T2", "T3"), _dep("T3", "T4", "SS", 4),
        _dep("T3", "T5"), _dep("T4", "T5"), _dep("T5", "T6"),
    ]
    return "Proyecto genérico por fases.", tasks, deps


_TEMPLATES = {
    "data_collection": _template_data_collection,
    "software": _template_software,
    "training": _template_training,
    "agri_field": _template_agri_field,
    "generic": _template_generic,
}


class HeuristicProvider:
    """Genera una EDT sin conexión a partir de plantillas de dominio."""

    name = "heuristic"

    def generate(self, raw_text: str, target_horizon_days: Optional[float]) -> dict:
        domain = _detect_domain(raw_text)
        summary, tasks, deps = _TEMPLATES[domain]()
        first_line = raw_text.strip().splitlines()[0][:140]
        return {
            "summary": f"{summary} (a partir de: “{first_line}”)",
            "tasks": tasks,
            "dependencies": deps,
        }
