# Campo Crítico — Modelo de datos (Entidad–Relación)

Base de datos relacional (**PostgreSQL**). El grafo de tareas se modela con la tabla
`task_dependency` (aristas dirigidas), que junto con `task` (nodos) forma el **DAG** sobre el
que corre el motor CPM/PERT.

## Diagrama ER (Mermaid)

```mermaid
erDiagram
    ORGANIZATION ||--o{ USER : emplea
    ORGANIZATION ||--o{ PROJECT : posee
    USER ||--o{ PROJECT : dirige
    USER }o--o{ PROJECT : "colabora (project_member)"

    PROJECT ||--o{ TASK : contiene
    PROJECT ||--o{ CONSTRAINT : define
    PROJECT ||--o{ STAKEHOLDER : involucra
    PROJECT ||--o{ SCENARIO : simula
    PROJECT ||--o{ IDEA_INTAKE : "se origina en"

    TASK ||--o{ TASK_DEPENDENCY : "predecesora (from)"
    TASK ||--o{ TASK_DEPENDENCY : "sucesora (to)"
    TASK ||--o{ TASK_ASSIGNMENT : asigna
    TASK ||--o{ CPM_RESULT : "produce"

    RESOURCE ||--o{ TASK_ASSIGNMENT : "se asigna en"
    ORGANIZATION ||--o{ RESOURCE : posee

    SCENARIO ||--o{ SCENARIO_OVERRIDE : ajusta
    TASK ||--o{ SCENARIO_OVERRIDE : "afectada por"
    SCENARIO ||--o{ CPM_RESULT : "calcula"

    ORGANIZATION {
        uuid   id PK
        text   name
        timestamptz created_at
    }
    USER {
        uuid   id PK
        uuid   organization_id FK
        text   email UK
        text   full_name
        text   role  "consultor|director|aliado|admin"
        timestamptz created_at
    }
    PROJECT {
        uuid   id PK
        uuid   organization_id FK
        uuid   owner_id FK
        text   name
        text   objective
        numeric budget_estimated
        char    currency
        date   deadline_hard   "fecha improrrogable"
        date   start_date
        text   status "draft|planning|executing|closed"
        timestamptz created_at
        timestamptz updated_at
    }
    IDEA_INTAKE {
        uuid   id PK
        uuid   project_id FK
        text   raw_text        "idea libre / transcripción de voz"
        text   source "text|voice"
        jsonb  ai_wbs          "EDT propuesta por la IA"
        text   ai_status "pending|generated|accepted"
        timestamptz created_at
    }
    CONSTRAINT {
        uuid   id PK
        uuid   project_id FK
        text   kind "budget|deadline|geo|connectivity|regulatory"
        text   description
        jsonb  params
    }
    STAKEHOLDER {
        uuid   id PK
        uuid   project_id FK
        text   name
        text   role
        text   influence "low|medium|high"
        text   contact
    }
    TASK {
        uuid   id PK
        uuid   project_id FK
        uuid   parent_id FK  "jerarquía EDT/WBS (nullable)"
        text   wbs_code      "1.2.3"
        text   name
        text   description
        numeric duration_days      "duración determinista"
        numeric optimistic_days    "PERT o"
        numeric most_likely_days   "PERT m"
        numeric pessimistic_days   "PERT p"
        numeric cost_estimated
        integer progress_pct
        text   status "todo|in_progress|blocked|done"
        boolean is_milestone
        timestamptz created_at
        timestamptz updated_at
    }
    TASK_DEPENDENCY {
        uuid   id PK
        uuid   project_id FK
        uuid   predecessor_id FK
        uuid   successor_id FK
        text   dep_type "FS|SS|FF|SF"
        numeric lag_days  "puede ser negativo (lead)"
    }
    RESOURCE {
        uuid   id PK
        uuid   organization_id FK
        text   name
        text   kind "person|machinery|material"
        numeric capacity_per_day "unidades/día"
        numeric cost_per_day
        text   skills
    }
    TASK_ASSIGNMENT {
        uuid   id PK
        uuid   task_id FK
        uuid   resource_id FK
        numeric units          "unidades asignadas/día"
        numeric allocation_pct
    }
    SCENARIO {
        uuid   id PK
        uuid   project_id FK
        text   name "base|¿lluvias 15d?|…"
        boolean is_baseline
        jsonb  params  "config Monte Carlo, semilla…"
        timestamptz created_at
    }
    SCENARIO_OVERRIDE {
        uuid   id PK
        uuid   scenario_id FK
        uuid   task_id FK
        numeric duration_delta_days
        numeric cost_delta
        text   note
    }
    CPM_RESULT {
        uuid   id PK
        uuid   scenario_id FK
        uuid   task_id FK
        numeric early_start
        numeric early_finish
        numeric late_start
        numeric late_finish
        numeric total_slack
        numeric free_slack
        boolean is_critical
        numeric pert_expected
        numeric pert_variance
        timestamptz computed_at
    }
```

## Notas de diseño

- **DAG e integridad:** `task_dependency` no puede crear ciclos. Se valida en la capa de
  aplicación (motor CPM detecta ciclos) y opcionalmente con un *trigger* o una consulta recursiva
  (`WITH RECURSIVE`) antes de insertar.
- **Jerarquía EDT:** `task.parent_id` modela la estructura de desglose; las hojas son las tareas
  planificables y las ramas son agregados (resumen).
- **Escenarios:** el escenario `is_baseline = true` es el plan real. Las simulaciones
  ("¿qué pasaría si…?") se representan con `SCENARIO` + `SCENARIO_OVERRIDE` sin tocar las tareas
  base, y sus resultados se guardan en `CPM_RESULT` para comparar.
- **EVM / avance:** `task.progress_pct`, `cost_estimated` y `task_assignment` alimentan el cálculo
  de PV/EV/AC en el dashboard.
- **Offline:** cada tabla mutable lleva `updated_at`; el cliente encola cambios y sincroniza por
  *last-write-wins* a nivel de campo.

Ver el DDL completo en [`db/schema.sql`](../db/schema.sql).
