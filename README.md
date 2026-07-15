# Campo Crítico

> Plataforma web y móvil de **Agencia Campo Digital** que transforma ideas y proyectos
> (agro, desarrollo rural, transformación digital) en **Rutas Críticas** (CPM/PERT)
> visuales, automatizadas e inteligentes.

Convierte una idea preliminar o un proyecto estructurado en un mapa de ruta exacto con
tiempos, dependencias, cuellos de botella y asignación de recursos — con soporte offline
para técnicos en zonas rurales sin señal.

---

## Módulos

| # | Módulo | Estado en este repo |
|---|---|---|
| A | Ingreso inteligente (IA de desglose EDT, formulario estructurado) | ✅ Implementado (LLM + heurístico offline) |
| B | **Motor de Ruta Crítica CPM/PERT** | ✅ Implementado y probado |
| C | Interfaz visual (Red PERT, Gantt, Kanban) | ✅ Implementado (Wizard IA + Red + Gantt + Kanban) |
| D | Recursos y simulación "¿Qué pasaría si…?" | Endpoint + esquema |
| E | Exportación (PDF/PNG/XLSX/MS Project/P6) y EVM | Especificado |

## Estructura

```
rutas-criticas/
├── docs/
│   ├── ARCHITECTURE.md   # Especificación completa (módulos, stack, diseño, offline)
│   ├── DATA_MODEL.md     # Modelo entidad-relación (Mermaid + notas)
│   └── API.md            # Endpoints REST
├── db/
│   └── schema.sql        # Esquema PostgreSQL
├── backend/              # FastAPI + motor CPM/PERT (Python)
│   ├── app/cpm/engine.py # Núcleo del algoritmo
│   ├── app/main.py       # API
│   └── tests/            # 10 pruebas del motor (pytest)
└── frontend/             # Prototipo React (Vite)
    └── src/
        ├── lib/cpm.js                       # Motor CPM/PERT en JS (offline/tiempo real)
        └── components/CriticalPathView.jsx  # Vista de Ruta Crítica (Red PERT + Gantt)
```

## Asistente IA de desglose (Módulo A)

Convierte una idea en texto libre en una EDT/WBS validada, lista para el motor CPM.
Arquitectura de proveedores intercambiables:

- **`OpenAICompatibleProvider`** — llama a un LLM real (config por entorno
  `CAMPO_LLM_API_KEY`, `CAMPO_LLM_BASE_URL`, `CAMPO_LLM_MODEL`).
- **`HeuristicProvider`** — genera la EDT **sin conexión** con plantillas de dominio
  (censo/datos, software, capacitación, agrícola, genérico) y detección de plazo
  («3 meses» → 90 días). Es el respaldo cuando no hay red/API key.

El orquestador (`backend/app/ai/breakdown.py`) valida la salida contra el esquema,
la pasa por el motor CPM (**rechaza ciclos y referencias colgantes**) y **escala las
duraciones** para caber en el horizonte objetivo. Devuelve la EDT + vista previa de
ruta crítica.

- Endpoints: `POST /api/v1/ai/breakdown`, `POST /api/v1/ai/transcribe` (interfaz Whisper).
- Frontend: `frontend/src/components/IdeaIntakeWizard.jsx` (idea → EDT editable → ruta),
  con espejo JS del generador en `frontend/src/lib/aiBreakdown.js`.
- Núcleo puro (dataclasses, sin dependencias externas) → verificable con `pytest`.

## Interfaz visual e interactiva (Módulo C)

Tres vistas del mismo proyecto, todas dependency-free (React + SVG + CSS del sistema
de diseño) con recálculo en el cliente:

- **Diagrama de Red (PERT)** — nodos por capas y aristas de dependencia con etiqueta de tipo/lag.
- **Gantt dinámico** — barras arrastrables (ajustar duración) que recalculan la ruta al instante.
- **Kanban de ejecución** — seguimiento diario con **arrastrar y soltar nativo** (HTML5) entre
  columnas de estado (Por hacer / En progreso / Bloqueada / Completada), control de avance por
  tarjeta y resaltado del camino crítico.

La cabecera del Kanban muestra la **salud del proyecto** calculada por el núcleo de métricas
de ejecución (`backend/app/execution/metrics.py`, espejo JS en `frontend/src/lib/execution.js`):
avance real ponderado por duración, avance del camino crítico, avance planeado a la fecha
(`as_of_day`), varianza de cronograma y una señal (`on_track` / `at_risk` / `behind`…). Una
tarea crítica bloqueada eleva la salud al menos a `at_risk`.

- Endpoint: `POST /api/v1/execution/summary`.
- Núcleo puro (dataclasses) → verificable con `pytest`; paridad Python ↔ JavaScript verificada.

## El motor CPM/PERT (núcleo)

Implementado **dos veces con paridad de resultados**: en Python (`backend/app/cpm/engine.py`)
para el servidor y en JavaScript (`frontend/src/lib/cpm.js`) para el recálculo en tiempo real
y el modo offline. Ambos calculan:

- Tiempos tempranos (ES/EF) y tardíos (LS/LF) — pases hacia adelante y atrás.
- Holgura total y holgura libre.
- Camino crítico (holgura total = 0), resaltado por color **y** borde.
- Dependencias generalizadas **FS, SS, FF, SF** con *lag/lead*.
- Estadística **PERT**: valor esperado `(o+4m+p)/6`, varianza `((p−o)/6)²`, σ del proyecto
  y probabilidad de cumplir una fecha meta (aproximación normal).
- Detección de ciclos y referencias inválidas.

### Backend

```bash
cd backend
pip install -r requirements.txt
pytest -v                       # 29/29 pruebas (motor CPM + asistente IA + ejecución)
uvicorn app.main:app --reload   # API en http://localhost:8000/docs
```

Endpoints implementados:
- `POST /api/v1/ai/breakdown` — idea en texto → EDT validada + ruta crítica.
- `POST /api/v1/ai/transcribe` — nota de voz → texto (interfaz Whisper).
- `POST /api/v1/cpm/preview` — recálculo sin persistir (Gantt en tiempo real).
- `POST /api/v1/execution/summary` — resumen de ejecución/salud para el Kanban.
- `POST /api/v1/scenarios/simulate` — modo "¿Qué pasaría si…?".
- `GET /health`.

Para activar el LLM real:
```bash
export CAMPO_LLM_API_KEY=sk-...      # sin esto, usa el heurístico offline
export CAMPO_LLM_MODEL=gpt-4o-mini   # opcional
```

### Frontend

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

## Diseño

Paleta agro + tecnología: verdes profundos (`#14432A`, `#2E7D4F`), azules digitales
(`#1E6FD9`), grises limpios y rojo de camino crítico (`#E4572E`). Responsivo,
*mobile-first*, accesibilidad AA y modo offline limitado (IndexedDB/SQLite).

Ver detalle en [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
