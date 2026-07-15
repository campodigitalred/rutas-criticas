# Campo Crítico — API REST

Base URL: `/api/v1` · Formato: JSON · Auth: `Authorization: Bearer <JWT>`

Convenciones: `200/201` éxito, `400` validación, `401/403` auth, `404` no existe,
`409` conflicto (p. ej. ciclo en dependencias), `422` cálculo imposible.

---

## Autenticación

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/auth/register` | Alta de organización + usuario admin. |
| `POST` | `/auth/login` | Devuelve `access_token` (JWT) y `refresh_token`. |
| `POST` | `/auth/refresh` | Renueva el token. |
| `GET`  | `/auth/me` | Perfil del usuario autenticado. |

## Proyectos

| Método | Ruta | Descripción |
|---|---|---|
| `GET`    | `/projects` | Lista proyectos (filtros: `status`, `owner`). |
| `POST`   | `/projects` | Crea un proyecto (formulario estructurado, Módulo A). |
| `GET`    | `/projects/{id}` | Detalle con tareas, dependencias y recursos. |
| `PATCH`  | `/projects/{id}` | Actualiza campos (nombre, presupuesto, deadline…). |
| `DELETE` | `/projects/{id}` | Elimina el proyecto. |
| `GET`    | `/projects/{id}/members` · `POST` · `DELETE` | Gestión de miembros. |
| `GET`    | `/projects/{id}/constraints` · `POST` | Restricciones (geo, conectividad…). |
| `GET`    | `/projects/{id}/stakeholders` · `POST` | Stakeholders. |

## Ingreso inteligente (Módulo A — IA)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/ai/breakdown` | Recibe `{ raw_text, source }` → devuelve EDT/WBS propuesta (tareas + dependencias sugeridas). |
| `POST` | `/ai/transcribe` | Sube audio (multipart) → texto (Whisper). |
| `POST` | `/projects/{id}/intake` | Guarda la idea y su EDT generada. |
| `POST` | `/projects/{id}/intake/{intakeId}/accept` | Convierte la EDT aceptada en `task` + `task_dependency`. |

**Ejemplo — `POST /ai/breakdown`**
```json
// Request
{ "raw_text": "Digitalizar el censo de productores de la región norte en 3 meses", "source": "text" }

// Response 200
{
  "wbs": [
    { "temp_id": "T1", "name": "Diseño del instrumento de censo", "duration_days": 10,
      "optimistic_days": 7, "most_likely_days": 10, "pessimistic_days": 18 },
    { "temp_id": "T2", "name": "Capacitación de brigadas de campo", "duration_days": 5 },
    { "temp_id": "T3", "name": "Levantamiento en campo (región norte)", "duration_days": 40 },
    { "temp_id": "T4", "name": "Validación y limpieza de datos", "duration_days": 15 }
  ],
  "dependencies": [
    { "predecessor": "T1", "successor": "T2", "dep_type": "FS", "lag_days": 0 },
    { "predecessor": "T2", "successor": "T3", "dep_type": "FS", "lag_days": 0 },
    { "predecessor": "T3", "successor": "T4", "dep_type": "SS", "lag_days": 10 }
  ]
}
```

## Tareas y dependencias

| Método | Ruta | Descripción |
|---|---|---|
| `GET`    | `/projects/{id}/tasks` | Lista tareas (árbol EDT). |
| `POST`   | `/projects/{id}/tasks` | Crea tarea. |
| `PATCH`  | `/tasks/{taskId}` | Edita (duración, PERT, progreso, fechas por drag&drop). |
| `DELETE` | `/tasks/{taskId}` | Elimina. |
| `GET`    | `/projects/{id}/dependencies` | Lista dependencias. |
| `POST`   | `/projects/{id}/dependencies` | Crea dependencia `{predecessor_id, successor_id, dep_type, lag_days}`. Rechaza ciclos → `409`. |
| `DELETE` | `/dependencies/{depId}` | Elimina. |

## Motor CPM / PERT (Módulo B — core)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/projects/{id}/cpm/compute` | Ejecuta el cálculo CPM/PERT del escenario base. Persiste `cpm_result`. |
| `GET`  | `/projects/{id}/cpm` | Devuelve el último resultado calculado. |
| `POST` | `/cpm/preview` | **Sin persistir** — recibe el grafo completo y devuelve ES/EF/LS/LF, holguras, camino crítico y métricas PERT. Ideal para recálculo en tiempo real desde el Gantt drag&drop. |

**Ejemplo — `POST /cpm/preview`**
```json
// Request
{
  "tasks": [
    { "id": "A", "duration": 3 },
    { "id": "B", "duration": 4 },
    { "id": "C", "duration": 2 },
    { "id": "D", "duration": 5 }
  ],
  "dependencies": [
    { "predecessor": "A", "successor": "B", "dep_type": "FS", "lag": 0 },
    { "predecessor": "A", "successor": "C", "dep_type": "FS", "lag": 0 },
    { "predecessor": "B", "successor": "D", "dep_type": "FS", "lag": 0 },
    { "predecessor": "C", "successor": "D", "dep_type": "FS", "lag": 0 }
  ]
}

// Response 200
{
  "project_duration": 12,
  "critical_path": ["A", "B", "D"],
  "tasks": {
    "A": { "early_start": 0, "early_finish": 3,  "late_start": 0, "late_finish": 3,  "total_slack": 0, "free_slack": 0, "is_critical": true },
    "B": { "early_start": 3, "early_finish": 7,  "late_start": 3, "late_finish": 7,  "total_slack": 0, "free_slack": 0, "is_critical": true },
    "C": { "early_start": 3, "early_finish": 5,  "late_start": 5, "late_finish": 7,  "total_slack": 2, "free_slack": 2, "is_critical": false },
    "D": { "early_start": 7, "early_finish": 12, "late_start": 7, "late_finish": 12, "total_slack": 0, "free_slack": 0, "is_critical": true }
  }
}
```

## Seguimiento de ejecución — Kanban (Módulo C)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/execution/summary` | Resumen de ejecución para el tablero Kanban: corre el CPM y devuelve avance real (ponderado por duración), avance del camino crítico, conteos por estado, avance planeado a la fecha, varianza de cronograma y salud del proyecto. |

Estados de tarea: `todo` · `in_progress` · `blocked` · `done`.
Salud: `not_started` · `in_progress` · `on_track` · `at_risk` · `behind` · `done`.

**Ejemplo — `POST /execution/summary`**
```json
// Request
{
  "tasks": [
    { "id": "T1", "duration": 8,  "status": "done",        "progress_pct": 100 },
    { "id": "T2", "duration": 5,  "status": "done",        "progress_pct": 100 },
    { "id": "T3", "duration": 20, "status": "in_progress", "progress_pct": 30 },
    { "id": "T5", "duration": 10, "status": "blocked",     "progress_pct": 0 }
  ],
  "dependencies": [
    { "predecessor": "T1", "successor": "T2", "dep_type": "FS", "lag": 0 },
    { "predecessor": "T2", "successor": "T3", "dep_type": "FS", "lag": 0 },
    { "predecessor": "T3", "successor": "T5", "dep_type": "FS", "lag": 0 }
  ],
  "as_of_day": 20
}

// Response 200
{
  "total_tasks": 4,
  "status_counts": { "todo": 0, "in_progress": 1, "blocked": 1, "done": 2 },
  "overall_progress": 44.19,
  "critical_progress": 44.19,
  "blocked_count": 1,
  "critical_blocked": true,
  "project_duration": 43.0,
  "critical_path": ["T1", "T2", "T3", "T5"],
  "as_of_day": 20.0,
  "planned_progress": 46.51,
  "schedule_variance_pct": -2.32,
  "health": "at_risk"
}
```

> Las fechas y el camino crítico provienen del motor CPM. Nótese que aunque la
> varianza de cronograma es pequeña (−2.32 pp), la salud es `at_risk` porque una
> **tarea crítica está bloqueada** (T5): esa condición eleva la salud al menos a
> `at_risk`.

## Recursos y sobreasignación (Módulo D)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/resources/load` | **(sin estado)** Perfil de carga diaria por recurso (posicionando las tareas en su inicio temprano CPM) + alertas de sobreasignación por ventanas. |
| `GET`  | `/resources` · `POST` | Catálogo de personal/maquinaria (persistencia). |
| `POST` | `/tasks/{taskId}/assignments` | Asigna recurso a tarea (persistencia). |
| `GET`  | `/projects/{id}/resource-load` | Versión persistida del histograma de carga. |

**Ejemplo — `POST /resources/load`**
```json
// Request
{
  "tasks": [ { "id": "A", "duration": 10 }, { "id": "B", "duration": 10 } ],
  "dependencies": [],
  "resources": [ { "id": "BRIG", "name": "Brigada Norte", "capacity_per_day": 1 } ],
  "assignments": [
    { "task_id": "A", "resource_id": "BRIG", "units": 1 },
    { "task_id": "B", "resource_id": "BRIG", "units": 1 }
  ]
}

// Response 200 — A y B se traslapan (ambas inician el día 0) → sobreasignación
{
  "horizon_days": 10,
  "project_duration": 10.0,
  "has_overallocation": true,
  "alerts": [
    {
      "resource_id": "BRIG", "resource_name": "Brigada Norte",
      "peak_load": 2.0, "capacity_per_day": 1.0,
      "overallocated_day_count": 10,
      "windows": [ { "start": 0, "end": 9 } ],
      "message": "Brigada Norte sobreasignado: pico 2.0 vs capacidad 1.0 en 10 día(s)."
    }
  ],
  "profiles": [ { "resource_id": "BRIG", "peak_load": 2.0, "load_by_day": [2,2,2,2,2,2,2,2,2,2], "…": "…" } ]
}
```

## Simulación "¿Qué pasaría si...?" (Módulo D)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/simulation/montecarlo` | **(sin estado)** Simulación Monte Carlo sobre distribuciones Beta-PERT: distribución de la duración, percentiles, probabilidad de cumplir el plazo, **índice de criticidad** por tarea, histograma e impacto presupuestal. Reproducible con `seed`. |
| `POST` | `/scenarios/simulate` | What-if determinista: aplica *overrides* de duración/costo y compara la red base vs. el escenario. |
| `GET`  | `/projects/{id}/scenarios` · `POST` | Lista/crea escenarios (persistencia). |
| `POST` | `/scenarios/{sid}/overrides` | Aplica perturbaciones (p. ej. `+15` días a la fase de campo). |

**Ejemplo — `POST /simulation/montecarlo`**
```json
// Request
{
  "tasks": [
    { "id": "T1", "optimistic": 5,  "most_likely": 8,  "pessimistic": 14 },
    { "id": "T2", "optimistic": 3,  "most_likely": 5,  "pessimistic": 8 },
    { "id": "T3", "optimistic": 15, "most_likely": 22, "pessimistic": 40 }
  ],
  "dependencies": [
    { "predecessor": "T1", "successor": "T2" },
    { "predecessor": "T2", "successor": "T3" }
  ],
  "iterations": 5000, "seed": 7, "target_duration": 45, "cost_per_day_delay": 500
}

// Response 200 (valores reales con seed=7, 5000 iteraciones)
{
  "iterations": 5000, "seed": 7,
  "baseline_duration": 37.5,
  "mean": 37.56, "std_dev": 4.91, "min": 25.56, "max": 53.8,
  "percentiles": { "p10": 31.33, "p25": 33.88, "p50": 37.21, "p80": 41.92, "p90": 44.36, "p95": 46.02 },
  "probability_on_time": 0.9186,
  "criticality_index": { "T1": 1.0, "T2": 1.0, "T3": 1.0 },
  "histogram": [ { "start": 25.56, "end": 26.97, "count": 14 }, "…" ],
  "expected_cost": 1017.95, "cost_p80": 2208.67
}
```

> El **índice de criticidad** revela tareas “casi críticas”: si una tarea fuera del
> camino determinista aparece con índice alto (p.ej. 0.4), es un riesgo a vigilar.
| `POST` | `/scenarios/{sid}/simulate` | Recalcula impacto: nueva fecha final, delta de presupuesto, camino crítico y (opcional) Monte Carlo → probabilidad de cumplir el hito. |
| `GET`  | `/scenarios/{sid}/compare?vs=baseline` | Comparativa base vs. escenario. |

## Exportación y reportes (Módulo E)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/reporting/evm` | **(sin estado)** Dashboard de Valor Ganado: BAC/PV/EV/AC, SV/CV, SPI/CPI, EAC/ETC/VAC/TCPI, % avance/gastado, salud y curva S. |
| `POST` | `/export/csv` | Exporta la ruta crítica a CSV (compatible con Excel). |
| `POST` | `/export/msproject` | Exporta a MS Project (MSPDI XML). |
| `POST` | `/export/p6` | Exporta a Primavera P6 (XER). |
| `GET`  | `/projects/{id}/export/pdf` · `/png` | PDF ejecutivo / diagrama PNG (render en cliente; `window.print()` y `<svg>`→canvas). |

**Ejemplo — `POST /reporting/evm`**
```json
// Request
{
  "tasks": [
    { "id": "T1", "duration": 8,  "planned_cost": 1000, "progress_pct": 100, "actual_cost": 1100 },
    { "id": "T2", "duration": 20, "planned_cost": 5000, "progress_pct": 30,  "actual_cost": 1800 },
    { "id": "T3", "duration": 10, "planned_cost": 2000, "progress_pct": 0,   "actual_cost": 0 }
  ],
  "dependencies": [
    { "predecessor": "T1", "successor": "T2" },
    { "predecessor": "T2", "successor": "T3" }
  ],
  "as_of_day": 15
}

// Response 200 (valores verificados)
{
  "bac": 8000.0, "pv": 2750.0, "ev": 2500.0, "ac": 2900.0,
  "sv": -250.0, "cv": -400.0, "spi": 0.9091, "cpi": 0.8621,
  "eac": 9280.0, "etc": 6380.0, "vac": -1280.0, "tcpi": 1.0784,
  "percent_complete": 31.25, "percent_spent": 36.25,
  "health": "at_risk",
  "pv_curve": [ { "day": 0, "pv": 0.0 }, { "day": 15, "pv": 2750.0, "ev": 2500.0, "ac": 2900.0 }, "…" ]
}
```

> Interpretación: `SPI 0.91` (algo atrasado) y `CPI 0.86` (sobrecosto) → salud `at_risk`;
> `EAC 9280 > BAC 8000` proyecta un sobrecosto de `VAC −1280` si la tendencia continúa.
> Los exportadores (`/export/*`) aceptan el mismo cuerpo de `tasks`/`dependencies` (más
> `project_name`, `project_id`, `start_date`) y devuelven el archivo con `Content-Disposition`.

## Sincronización offline

Para zonas rurales sin señal: los cambios se encolan localmente como *mutaciones*
y se envían al recuperar conexión. El servidor las fusiona con resolución de
conflictos **última-escritura-gana a nivel de campo** (LWW).

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/sync` | **(sin estado)** Aplica la cola de mutaciones al `server_state` y devuelve `applied`, `rejected`, `conflicts` y el estado fusionado con su marca de agua (`server_ts`). |
| `GET`  | `/projects/{id}/snapshot` | Snapshot completo del proyecto para cache local (persistencia). |

Estado del servidor: `{"entities": {"<id>": {"id","type","deleted","deleted_ts","fields": {"<campo>": {"value","ts"}}}}}`.
Mutación: `{mutation_id, entity_type, entity_id, op ("set"|"delete"), field, value, ts, base_ts}`
donde `base_ts` es el `ts` del campo que el cliente tenía al editar (para detectar cambios ajenos).

Reglas: **conflicto** cuando `server_ts > base_ts` (alguien más cambió el campo desde la base del
cliente); se resuelve por LWW (gana el `ts` mayor; empate → servidor) y se registra para revisión.
Sin conflicto y mutación más vieja → descartada como `stale`.

**Ejemplo — `POST /sync`**
```json
// Request — el servidor ya tenía progress_pct=40 (ts 80); el cliente editó offline
{
  "server_state": {
    "entities": {
      "T1": { "id": "T1", "type": "task", "deleted": false, "deleted_ts": 0,
        "fields": { "progress_pct": {"value": 40, "ts": 80}, "status": {"value": "todo", "ts": 50} } }
    }
  },
  "mutations": [
    { "mutation_id": "m1", "entity_id": "T1", "op": "set", "field": "progress_pct", "value": 90, "ts": 120, "base_ts": 50 },
    { "mutation_id": "m2", "entity_id": "T1", "op": "set", "field": "status", "value": "in_progress", "ts": 115, "base_ts": 50 }
  ]
}

// Response 200
{
  "applied": [
    { "mutation_id": "m2", "entity_id": "T1", "op": "set", "field": "status", "value": "in_progress", "ts": 115 },
    { "mutation_id": "m1", "entity_id": "T1", "op": "set", "field": "progress_pct", "value": 90, "ts": 120 }
  ],
  "rejected": [],
  "conflicts": [
    { "entity_id": "T1", "field": "progress_pct", "server_value": 40, "client_value": 90,
      "server_ts": 80, "client_ts": 120, "resolution": "client_wins" }
  ],
  "server_state": { "entities": { "T1": { "…": "…" } } },
  "server_ts": 120.0
}
```

> `status` se aplica limpiamente (nadie lo tocó desde la base); `progress_pct` genera un
> **conflicto** (el servidor lo cambió a 40 tras la base del cliente) resuelto por LWW a favor del
> cliente (120 > 80). El frontend cachea el snapshot y la cola en IndexedDB/localStorage y
> sincroniza al volver la señal (ver `frontend/src/lib/offlineStore.js` y `sync.js`).
