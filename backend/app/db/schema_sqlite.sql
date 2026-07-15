-- ============================================================================
-- Campo Crítico — Esquema SQLite (espejo de db/schema.sql en PostgreSQL)
--
-- Conversiones: UUID -> TEXT (ids generados en la app), ENUM -> TEXT + CHECK,
-- TIMESTAMPTZ -> TEXT (ISO-8601), NUMERIC -> REAL, BOOLEAN -> INTEGER (0/1),
-- JSONB -> TEXT (JSON serializado). Requiere PRAGMA foreign_keys=ON.
-- ============================================================================

CREATE TABLE IF NOT EXISTS organization (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_user (
    id               TEXT PRIMARY KEY,
    organization_id  TEXT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    email            TEXT NOT NULL UNIQUE,
    full_name        TEXT NOT NULL,
    role             TEXT NOT NULL DEFAULT 'consultor'
                       CHECK (role IN ('consultor','director','aliado','admin')),
    password_hash    TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project (
    id               TEXT PRIMARY KEY,
    organization_id  TEXT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    owner_id         TEXT REFERENCES app_user(id) ON DELETE SET NULL,
    name             TEXT NOT NULL,
    objective        TEXT,
    budget_estimated REAL,
    currency         TEXT DEFAULT 'MXN',
    deadline_hard    TEXT,
    start_date       TEXT,
    status           TEXT NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft','planning','executing','closed')),
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_member (
    project_id  TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'consultor'
                  CHECK (role IN ('consultor','director','aliado','admin')),
    PRIMARY KEY (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS idea_intake (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    raw_text    TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'text' CHECK (source IN ('text','voice')),
    ai_wbs      TEXT,
    ai_status   TEXT NOT NULL DEFAULT 'pending'
                  CHECK (ai_status IN ('pending','generated','accepted')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_constraint (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('budget','deadline','geo','connectivity','regulatory')),
    description TEXT,
    params      TEXT
);

CREATE TABLE IF NOT EXISTS stakeholder (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    role        TEXT,
    influence   TEXT CHECK (influence IN ('low','medium','high')),
    contact     TEXT
);

CREATE TABLE IF NOT EXISTS task (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    parent_id         TEXT REFERENCES task(id) ON DELETE CASCADE,
    wbs_code          TEXT,
    name              TEXT NOT NULL,
    description       TEXT,
    duration_days     REAL NOT NULL DEFAULT 0,
    optimistic_days   REAL,
    most_likely_days  REAL,
    pessimistic_days  REAL,
    cost_estimated    REAL DEFAULT 0,
    progress_pct      INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    status            TEXT NOT NULL DEFAULT 'todo'
                        CHECK (status IN ('todo','in_progress','blocked','done')),
    is_milestone      INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_task_project ON task(project_id);
CREATE INDEX IF NOT EXISTS idx_task_parent  ON task(parent_id);

CREATE TABLE IF NOT EXISTS task_dependency (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    predecessor_id  TEXT NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    successor_id    TEXT NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    dep_type        TEXT NOT NULL DEFAULT 'FS' CHECK (dep_type IN ('FS','SS','FF','SF')),
    lag_days        REAL NOT NULL DEFAULT 0,
    CHECK (predecessor_id <> successor_id),
    UNIQUE (predecessor_id, successor_id, dep_type)
);
CREATE INDEX IF NOT EXISTS idx_dep_pred ON task_dependency(predecessor_id);
CREATE INDEX IF NOT EXISTS idx_dep_succ ON task_dependency(successor_id);

CREATE TABLE IF NOT EXISTS resource (
    id               TEXT PRIMARY KEY,
    organization_id  TEXT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'person'
                       CHECK (kind IN ('person','machinery','material')),
    capacity_per_day REAL NOT NULL DEFAULT 1,
    cost_per_day     REAL DEFAULT 0,
    skills           TEXT
);

CREATE TABLE IF NOT EXISTS task_assignment (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    resource_id     TEXT NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    units           REAL NOT NULL DEFAULT 1,
    allocation_pct  REAL NOT NULL DEFAULT 100,
    UNIQUE (task_id, resource_id)
);

CREATE TABLE IF NOT EXISTS scenario (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_baseline INTEGER NOT NULL DEFAULT 0,
    params      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_scenario_baseline
    ON scenario(project_id) WHERE is_baseline = 1;

CREATE TABLE IF NOT EXISTS scenario_override (
    id                  TEXT PRIMARY KEY,
    scenario_id         TEXT NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
    task_id             TEXT NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    duration_delta_days REAL DEFAULT 0,
    cost_delta          REAL DEFAULT 0,
    note                TEXT,
    UNIQUE (scenario_id, task_id)
);

CREATE TABLE IF NOT EXISTS cpm_result (
    id             TEXT PRIMARY KEY,
    scenario_id    TEXT NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
    task_id        TEXT NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    early_start    REAL,
    early_finish   REAL,
    late_start     REAL,
    late_finish    REAL,
    total_slack    REAL,
    free_slack     REAL,
    is_critical    INTEGER NOT NULL DEFAULT 0,
    pert_expected  REAL,
    pert_variance  REAL,
    computed_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (scenario_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_cpm_scenario ON cpm_result(scenario_id);

CREATE VIEW IF NOT EXISTS v_resource_load AS
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
