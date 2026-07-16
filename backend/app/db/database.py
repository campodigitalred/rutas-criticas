"""Gestión de conexión y esquema de la base de datos (SQLite).

Capa de persistencia real de Campo Crítico. Usa ``sqlite3`` de la biblioteca
estándar (base de datos SQL embebida real), de modo que el acceso a datos es
verificable sin dependencias externas.

En producción, la misma capa de repositorios apunta a **PostgreSQL** (ver
``db/schema.sql`` y los modelos SQLAlchemy en ``app/db/models_orm.py``); el SQL
utilizado es estándar y portable, salvo detalles de tipo documentados.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_PATH = Path(__file__).with_name("schema_sqlite.sql")


def new_id() -> str:
    """Identificador único (UUID4 hex) generado por la aplicación."""
    return uuid.uuid4().hex


def utcnow() -> str:
    """Timestamp ISO-8601 en UTC (segundos)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    """Envuelve una conexión SQLite con claves foráneas y filas tipo dict."""

    def __init__(self, path: str = ":memory:"):
        self.path = path
        # ``check_same_thread=False``: uvicorn ejecuta los endpoints síncronos en
        # un pool de hilos; la conexión (singleton por proceso) debe poder usarse
        # entre hilos. WAL permite lecturas concurrentes y serializa escrituras.
        # Para alta concurrencia, migrar a PostgreSQL (ver app/db/models_orm.py).
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def init_schema(self, schema_path: Optional[Path] = None) -> None:
        sql = (schema_path or SCHEMA_PATH).read_text(encoding="utf-8")
        self._conn.executescript(sql)
        self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # Context manager --------------------------------------------------- #
    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        self.close()


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None


def rows_to_dicts(rows) -> list:
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Fábrica para la app (una BD por proceso; ruta configurable por entorno)
# --------------------------------------------------------------------------- #
_DB_SINGLETON: Optional[Database] = None


def get_database() -> Database:
    """Devuelve la BD del proceso, creándola e inicializando el esquema una vez.

    Ruta configurable con ``CAMPO_DB_PATH`` (default: ``campo_critico.db``).
    Dependencia FastAPI para inyectar en los endpoints.
    """
    global _DB_SINGLETON
    if _DB_SINGLETON is None:
        path = os.getenv("CAMPO_DB_PATH", "campo_critico.db")
        _DB_SINGLETON = Database(path)
        _DB_SINGLETON.init_schema()
    return _DB_SINGLETON
