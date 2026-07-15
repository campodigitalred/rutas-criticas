"""Modelos ORM SQLAlchemy — mapeo de producción para PostgreSQL.

Mapeo declarativo (SQLAlchemy 2.0) que refleja ``db/schema.sql``. Es la ruta de
**despliegue en producción**: en el sandbox se usa la capa de repositorios sobre
``sqlite3`` (verificable sin dependencias), pero en producción estos modelos
operan contra **PostgreSQL** (tipos UUID/JSONB/ENUM nativos).

Uso:
    from sqlalchemy import create_engine
    from app.db.models_orm import Base
    engine = create_engine(os.environ["DATABASE_URL"])  # postgresql+psycopg://...
    Base.metadata.create_all(engine)   # o gestionar con Alembic

Requiere ``pip install sqlalchemy psycopg[binary]`` (ver requirements.txt).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Tipos enumerados (coinciden con los CREATE TYPE del esquema PostgreSQL).
user_role = ENUM("consultor", "director", "aliado", "admin", name="user_role", create_type=False)
project_status = ENUM("draft", "planning", "executing", "closed", name="project_status", create_type=False)
task_status = ENUM("todo", "in_progress", "blocked", "done", name="task_status", create_type=False)
dependency_type = ENUM("FS", "SS", "FF", "SF", name="dependency_type", create_type=False)
resource_kind = ENUM("person", "machinery", "material", name="resource_kind", create_type=False)
constraint_kind = ENUM("budget", "deadline", "geo", "connectivity", "regulatory", name="constraint_kind", create_type=False)
intake_source = ENUM("text", "voice", name="intake_source", create_type=False)
intake_status = ENUM("pending", "generated", "accepted", name="intake_status", create_type=False)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts()

    users: Mapped[list["AppUser"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(user_role, nullable=False, default="consultor")
    password_hash: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()

    organization: Mapped["Organization"] = relationship(back_populates="users")


class Project(Base):
    __tablename__ = "project"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[Optional[str]] = mapped_column(Text)
    budget_estimated: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    deadline_hard: Mapped[Optional[date]] = mapped_column(Date)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(project_status, nullable=False, default="draft")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    dependencies: Mapped[list["TaskDependency"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class IdeaIntake(Base):
    __tablename__ = "idea_intake"
    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(intake_source, nullable=False, default="text")
    ai_wbs: Mapped[Optional[dict]] = mapped_column(JSONB)
    ai_status: Mapped[str] = mapped_column(intake_status, nullable=False, default="pending")
    created_at: Mapped[datetime] = _ts()


class Task(Base):
    __tablename__ = "task"
    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), index=True)
    wbs_code: Mapped[Optional[str]] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    duration_days: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    optimistic_days: Mapped[Optional[float]] = mapped_column(Numeric(8, 2))
    most_likely_days: Mapped[Optional[float]] = mapped_column(Numeric(8, 2))
    pessimistic_days: Mapped[Optional[float]] = mapped_column(Numeric(8, 2))
    cost_estimated: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(task_status, nullable=False, default="todo")
    is_milestone: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("progress_pct BETWEEN 0 AND 100", name="ck_progress_range"),)

    project: Mapped["Project"] = relationship(back_populates="tasks")


class TaskDependency(Base):
    __tablename__ = "task_dependency"
    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    predecessor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True)
    successor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True)
    dep_type: Mapped[str] = mapped_column(dependency_type, nullable=False, default="FS")
    lag_days: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("predecessor_id <> successor_id", name="no_self_loop"),
        UniqueConstraint("predecessor_id", "successor_id", "dep_type", name="uq_dependency"),
    )

    project: Mapped["Project"] = relationship(back_populates="dependencies")


class Resource(Base):
    __tablename__ = "resource"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(resource_kind, nullable=False, default="person")
    capacity_per_day: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=1)
    cost_per_day: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    skills: Mapped[Optional[str]] = mapped_column(Text)


class TaskAssignment(Base):
    __tablename__ = "task_assignment"
    id: Mapped[uuid.UUID] = _pk()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource.id", ondelete="CASCADE"), nullable=False)
    units: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=1)
    allocation_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=100)

    __table_args__ = (UniqueConstraint("task_id", "resource_id", name="uq_assignment"),)


class Scenario(Base):
    __tablename__ = "scenario"
    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_baseline: Mapped[bool] = mapped_column(default=False, nullable=False)
    params: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts()

    project: Mapped["Project"] = relationship(back_populates="scenarios")


class ScenarioOverride(Base):
    __tablename__ = "scenario_override"
    id: Mapped[uuid.UUID] = _pk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), nullable=False)
    duration_delta_days: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    cost_delta: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    note: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("scenario_id", "task_id", name="uq_override"),)


class CpmResult(Base):
    __tablename__ = "cpm_result"
    id: Mapped[uuid.UUID] = _pk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), nullable=False)
    early_start: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    early_finish: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    late_start: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    late_finish: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    total_slack: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    free_slack: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    is_critical: Mapped[bool] = mapped_column(default=False, nullable=False)
    pert_expected: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    pert_variance: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    computed_at: Mapped[datetime] = _ts()

    __table_args__ = (UniqueConstraint("scenario_id", "task_id", name="uq_cpm_result"),)
