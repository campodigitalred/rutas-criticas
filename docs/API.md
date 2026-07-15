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
| `GET`  | `/resources` · `POST` | Catálogo de personal/maquinaria. |
| `POST` | `/tasks/{taskId}/assignments` | Asigna recurso a tarea. |
| `GET`  | `/projects/{id}/resource-load` | Histograma de carga + alertas de sobreasignación. |

## Simulación "¿Qué pasaría si...?" (Módulo D)

| Método | Ruta | Descripción |
|---|---|---|
| `GET`  | `/projects/{id}/scenarios` · `POST` | Lista/crea escenarios. |
| `POST` | `/scenarios/{sid}/overrides` | Aplica perturbaciones (p. ej. `+15` días a la fase de campo). |
| `POST` | `/scenarios/{sid}/simulate` | Recalcula impacto: nueva fecha final, delta de presupuesto, camino crítico y (opcional) Monte Carlo → probabilidad de cumplir el hito. |
| `GET`  | `/scenarios/{sid}/compare?vs=baseline` | Comparativa base vs. escenario. |

## Exportación y reportes (Módulo E)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/projects/{id}/export/pdf` | PDF ejecutivo. |
| `GET` | `/projects/{id}/export/png` | Diagrama PNG. |
| `GET` | `/projects/{id}/export/xlsx` | Hoja de cálculo. |
| `GET` | `/projects/{id}/export/msproject` | XML compatible con MS Project. |
| `GET` | `/projects/{id}/export/p6` | XML/XER compatible con Primavera P6. |
| `GET` | `/projects/{id}/dashboard/evm` | Métricas EVM: PV, EV, AC, CPI, SPI, % avance, salud. |

## Sincronización offline

| Método | Ruta | Descripción |
|---|---|---|
| `GET`  | `/projects/{id}/snapshot` | Snapshot completo para cache local. |
| `POST` | `/projects/{id}/sync` | Envía cola de mutaciones offline; devuelve conflictos resueltos. |
