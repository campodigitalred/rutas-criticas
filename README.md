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
| D | Recursos y simulación "¿Qué pasaría si…?" | ✅ Implementado (Monte Carlo + sobreasignación) |
| E | Exportación (CSV/MS Project/P6, PNG/PDF) y Dashboard EVM | ✅ Implementado |

## Estructura

```
rutas-criticas/
├── docs/
│   ├── ARCHITECTURE.md   # Especificación completa (módulos, stack, diseño, offline)
│   ├── DATA_MODEL.md     # Modelo entidad-relación (Mermaid + notas)
│   └── API.md            # Endpoints REST
├── db/
│   └── schema.sql        # Esquema PostgreSQL
├── backend/              # FastAPI + núcleos Python
│   ├── app/cpm/          # Motor CPM/PERT (núcleo)
│   ├── app/ai/           # Asistente IA de desglose
│   ├── app/execution/    # Métricas de ejecución (Kanban)
│   ├── app/simulation/   # Monte Carlo
│   ├── app/resources/    # Carga y sobreasignación de recursos
│   ├── app/reporting/    # EVM y exportadores (MS Project/P6/CSV)
│   ├── app/sync/         # Sincronización offline (LWW a nivel de campo)
│   ├── app/db/           # Persistencia: repositorios sqlite3 + ORM PostgreSQL
│   ├── app/main.py       # API
│   └── tests/            # 90 pruebas (pytest)
└── frontend/             # Prototipo React (Vite)
    └── src/
        ├── lib/          # Motores en JS (cpm, ai, execution, montecarlo, evm, sync…)
        └── components/   # Wizard, Ruta Crítica, Kanban, Simulación, Recursos, Dashboard
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

## Persistencia

Acceso a datos real con una **capa de repositorios** (`backend/app/db/`) que ejecuta SQL
parametrizado. En este repositorio corre sobre **`sqlite3`** (biblioteca estándar → verificable
sin dependencias), y en **producción** apunta a **PostgreSQL** mediante los modelos ORM
SQLAlchemy (`app/db/models_orm.py`) que reflejan `db/schema.sql`.

- `schema_sqlite.sql` refleja el esquema PostgreSQL (UUID→TEXT, enums→CHECK, JSONB→TEXT…), con
  **claves foráneas en cascada** y restricciones (`progress` 0–100, sin auto-dependencia, un solo
  baseline por proyecto).
- Repositorios: Organization, User, Project, Task, Dependency, Resource, Scenario, CpmResult.
- Servicios que **unen persistencia y núcleos**: crear proyecto desde una EDT, **recalcular y
  guardar** la ruta crítica (`cpm_result`), construir el snapshot y **aplicar la sincronización
  offline persistiendo los cambios**.
- Endpoints REST de CRUD + `/cpm/compute`, `/snapshot`, `/sync` por proyecto.

```bash
# Producción: apuntar a PostgreSQL
export DATABASE_URL=postgresql+psycopg://user:pass@host/campo_critico
python -c "from sqlalchemy import create_engine; from app.db.models_orm import Base; \
Base.metadata.create_all(create_engine('$DATABASE_URL'))"   # o Alembic
```

## Exportación y reportes (Módulo E)

**Dashboard de Valor Ganado (EVM)** (`backend/app/reporting/evm.py`): combina el cronograma
CPM con costos, avance y costo real para calcular **BAC/PV/EV/AC**, variaciones **SV/CV**,
índices **SPI/CPI**, proyecciones **EAC/ETC/VAC/TCPI**, % avance/gastado y una **señal de salud**,
más la **curva S** (PV planeado vs. EV/AC a la fecha). La vista `DashboardView` la grafica y
recalcula en vivo al editar los costos.

**Exportadores profesionales** (`backend/app/reporting/exporters.py`), deterministas y sin
dependencias externas:
- **MS Project (MSPDI XML)** — con mapeo de dependencias FS/SS/FF/SF y *lag*.
- **Primavera P6 (XER)** — tablas PROJECT/TASK/TASKPRED.
- **CSV** — compatible con Excel (ES/EF/holgura/crítica/predecesoras/costo).
- **PNG** del gráfico (SVG→canvas) e **impresión a PDF** (`window.print()`) desde el cliente.

- Endpoints: `POST /api/v1/reporting/evm`, `/export/csv`, `/export/msproject`, `/export/p6`.
- Espejos JS (`evm.js`, `exporters.js`) con **paridad exacta**; incluyen la descarga en navegador.

## Recursos y simulación de riesgo (Módulo D)

**Simulación Monte Carlo** (`backend/app/simulation/montecarlo.py`): muestrea las duraciones
desde distribuciones **Beta-PERT** y corre el CPM miles de veces para estimar la distribución
de la fecha final, los **percentiles** (P50/P80/P90 → compromisos realistas), la **probabilidad
de cumplir un plazo**, el **índice de criticidad** de cada tarea (detecta cuellos de botella
“casi críticos” invisibles a un CPM determinista) y el **impacto presupuestal**. Reproducible
con `seed`. La vista `SimulationView` incluye el escenario *“¿Qué pasaría si…?”* (p.ej. *las
lluvias retrasan la fase de campo 15 días*) mostrando el desplazamiento de la distribución y el costo.

**Gestión de recursos** (`backend/app/resources/allocation.py`): posiciona las tareas en su
inicio temprano (CPM), acumula la carga diaria por recurso (personal/maquinaria) y **detecta la
sobreasignación** (carga > capacidad), agrupándola en ventanas y generando alertas. La vista
`ResourceView` permite reasignar tareas y ajustar capacidades para resolver los conflictos.

- Endpoints: `POST /api/v1/simulation/montecarlo`, `POST /api/v1/resources/load`.
- Espejos JS: `montecarlo.js` (PRNG con semilla; converge a la misma distribución) y
  `resourceLoad.js` (paridad exacta con el backend).
- Núcleos puros → verificables con `pytest`.

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
pytest -v                       # 90/90 pruebas (cores + persistencia)
uvicorn app.main:app --reload   # API en http://localhost:8000/docs
```

Endpoints implementados:
- `POST /api/v1/ai/breakdown` — idea en texto → EDT validada + ruta crítica.
- `POST /api/v1/ai/transcribe` — nota de voz → texto (interfaz Whisper).
- `POST /api/v1/cpm/preview` — recálculo sin persistir (Gantt en tiempo real).
- `POST /api/v1/execution/summary` — resumen de ejecución/salud para el Kanban.
- `POST /api/v1/simulation/montecarlo` — análisis de riesgo Monte Carlo.
- `POST /api/v1/resources/load` — carga de recursos + alertas de sobreasignación.
- `POST /api/v1/reporting/evm` — dashboard de Valor Ganado (EVM).
- `POST /api/v1/export/{csv,msproject,p6}` — exportadores profesionales.
- `POST /api/v1/scenarios/simulate` — modo "¿Qué pasaría si…?" determinista.
- `POST /api/v1/sync` — sincronización offline (fusión con LWW a nivel de campo).
- **Persistencia**: `POST /projects`, `/projects/from-wbs`, `GET/PATCH/DELETE /projects/{id}`,
  `GET/POST /projects/{id}/tasks`, `PATCH/DELETE /tasks/{id}`, `/projects/{id}/dependencies`,
  `POST /projects/{id}/cpm/compute`, `GET /projects/{id}/snapshot`, `POST /projects/{id}/sync`.
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
