-- ============================================================================
-- Campo Crítico — Esquema PostgreSQL
-- Agencia Campo Digital
-- Rutas Críticas (CPM/PERT) para proyectos de desarrollo rural / agro-tech.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Tipos enumerados
-- ---------------------------------------------------------------------------
CREATE TYPE user_role        AS ENUM ('consultor', 'director', 'aliado', 'admin');
CREATE TYPE project_status    AS ENUM ('draft', 'planning', 'executing', 'closed');
CREATE TYPE task_status       AS ENUM ('todo', 'in_progress', 'blocked', 'done');
CREATE TYPE dependency_type   AS ENUM ('FS', 'SS', 'FF', 'SF'); -- Finish-Start, Start-Start, Finish-Finish, Start-Finish
CREATE TYPE resource_kind     AS ENUM ('person', 'machinery', 'material');
CREATE TYPE constraint_kind   AS ENUM ('budget', 'deadline', 'geo', 'connectivity', 'regulatory');
CREATE TYPE intake_source     AS ENUM ('text', 'voice');
CREATE TYPE intake_status     AS ENUM ('pending', 'generated', 'accepted');

-- ---------------------------------------------------------------------------
-- Organización y usuarios
-- ---------------------------------------------------------------------------
CREATE TABLE organization (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app_user (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    email            TEXT NOT NULL UNIQUE,
    full_name        TEXT NOT NULL,
    role             user_role NOT NULL DEFAULT 'consultor',
    password_hash    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Proyectos
-- ---------------------------------------------------------------------------
CREATE TABLE project (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    owner_id         UUID REFERENCES app_user(id) ON DELETE SET NULL,
    name             TEXT NOT NULL,
    objective        TEXT,
    budget_estimated NUMERIC(14,2),
    currency         CHAR(3) DEFAULT 'MXN',
    deadline_hard    DATE,                 -- fecha límite improrrogable
    start_date       DATE,
    status           project_status NOT NULL DEFAULT 'draft',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE project_member (
    project_id  UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role        user_role NOT NULL DEFAULT 'consultor',
    PRIMARY KEY (project_id, user_id)
);

-- Ingreso inteligente (Módulo A): idea libre / voz -> EDT por IA
CREATE TABLE idea_intake (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    raw_text    TEXT NOT NULL,
    source      intake_source NOT NULL DEFAULT 'text',
    ai_wbs      JSONB,                     -- EDT propuesta por la IA
    ai_status   intake_status NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE project_constraint (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    kind        constraint_kind NOT NULL,
    description TEXT,
    params      JSONB
);

CREATE TABLE stakeholder (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    role        TEXT,
    influence   TEXT CHECK (influence IN ('low','medium','high')),
    contact     TEXT
);

-- ---------------------------------------------------------------------------
-- Tareas (nodos del DAG) y dependencias (aristas)
-- ---------------------------------------------------------------------------
CREATE TABLE task (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    parent_id         UUID REFERENCES task(id) ON DELETE CASCADE,  -- jerarquía EDT/WBS
    wbs_code          TEXT,
    name              TEXT NOT NULL,
    description       TEXT,
    duration_days     NUMERIC(8,2) NOT NULL DEFAULT 0,
    optimistic_days   NUMERIC(8,2),   -- PERT o
    most_likely_days  NUMERIC(8,2),   -- PERT m
    pessimistic_days  NUMERIC(8,2),   -- PERT p
    cost_estimated    NUMERIC(14,2) DEFAULT 0,
    progress_pct      INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    status            task_status NOT NULL DEFAULT 'todo',
    is_milestone      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_task_project ON task(project_id);
CREATE INDEX idx_task_parent  ON task(parent_id);

CREATE TABLE task_dependency (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    predecessor_id  UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    successor_id    UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    dep_type        dependency_type NOT NULL DEFAULT 'FS',
    lag_days        NUMERIC(8,2) NOT NULL DEFAULT 0,   -- negativo = lead
    CONSTRAINT no_self_loop CHECK (predecessor_id <> successor_id),
    UNIQUE (predecessor_id, successor_id, dep_type)
);
CREATE INDEX idx_dep_pred ON task_dependency(predecessor_id);
CREATE INDEX idx_dep_succ ON task_dependency(successor_id);

-- ---------------------------------------------------------------------------
-- Recursos y asignaciones (Módulo D)
-- ---------------------------------------------------------------------------
CREATE TABLE resource (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    kind             resource_kind NOT NULL DEFAULT 'person',
    capacity_per_day NUMERIC(8,2) NOT NULL DEFAULT 1,  -- p.ej. 1.0 = jornada completa
    cost_per_day     NUMERIC(14,2) DEFAULT 0,
    skills           TEXT
);

CREATE TABLE task_assignment (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    resource_id     UUID NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    units           NUMERIC(8,2) NOT NULL DEFAULT 1,   -- unidades/día
    allocation_pct  NUMERIC(5,2) NOT NULL DEFAULT 100,
    UNIQUE (task_id, resource_id)
);

-- ---------------------------------------------------------------------------
-- Escenarios de simulación "¿Qué pasaría si...?" (Módulo D)
-- ---------------------------------------------------------------------------
CREATE TABLE scenario (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_baseline BOOLEAN NOT NULL DEFAULT FALSE,
    params      JSONB,   -- iteraciones Monte Carlo, semilla, etc.
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Solo un baseline por proyecto
CREATE UNIQUE INDEX uq_scenario_baseline
    ON scenario(project_id) WHERE is_baseline;

CREATE TABLE scenario_override (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id         UUID NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
    task_id             UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    duration_delta_days NUMERIC(8,2) DEFAULT 0,   -- p.ej. +15 por lluvias
    cost_delta          NUMERIC(14,2) DEFAULT 0,
    note                TEXT,
    UNIQUE (scenario_id, task_id)
);

-- ---------------------------------------------------------------------------
-- Resultados del motor CPM/PERT (cache de cálculo por escenario)
-- ---------------------------------------------------------------------------
CREATE TABLE cpm_result (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id    UUID NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
    task_id        UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    early_start    NUMERIC(10,2),
    early_finish   NUMERIC(10,2),
    late_start     NUMERIC(10,2),
    late_finish    NUMERIC(10,2),
    total_slack    NUMERIC(10,2),
    free_slack     NUMERIC(10,2),
    is_critical    BOOLEAN NOT NULL DEFAULT FALSE,
    pert_expected  NUMERIC(10,2),
    pert_variance  NUMERIC(10,4),
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scenario_id, task_id)
);
CREATE INDEX idx_cpm_scenario ON cpm_result(scenario_id);

-- ---------------------------------------------------------------------------
-- Vista de ayuda: carga de recursos por tarea (detección de sobreasignación)
-- ---------------------------------------------------------------------------
CREATE VIEW v_resource_load AS
SELECT r.id                AS resource_id,
       r.name              AS resource_name,
       r.capacity_per_day,
       ta.task_id,
       t.name              AS task_name,
       ta.units,
       (ta.units > r.capacity_per_day) AS is_overallocated
FROM task_assignment ta
JOIN resource r ON r.id = ta.resource_id
JOIN task     t ON t.id = ta.task_id;
