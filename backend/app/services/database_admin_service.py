"""Database administration for Workbench — list, validate, switch.

Boundaries:
  - Does NOT create or drop databases
  - Does NOT run migrations
  - Does NOT write final_* / kg_* or call LLM
  - Never returns passwords or full DATABASE_URL
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings, get_settings
from app.schemas.database_admin import DatabaseSchemaStatus

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DATABASE_PATH = BACKEND_ROOT / "data" / "runtime" / "database.local.json"

# MVP1 migrations 001–008 core tables (minimal set for workbench operations).
MVP1_REQUIRED_TABLES: tuple[str, ...] = (
    "atlas_resources",
    "resource_files",
    "import_batches",
    "import_batch_files",
    "import_batch_events",
    "raw_parse_runs",
    "raw_aal3_region_labels",
    "candidate_generation_runs",
    "candidate_brain_regions",
    "rule_validation_runs",
    "candidate_rule_validation_results",
    "candidate_review_records",
    "final_brain_regions",
    "promotion_records",
)

_DB_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


class DatabaseSwitchNotAllowedError(Exception):
    def __init__(self, database: str, status: DatabaseSchemaStatus, reason: str):
        self.database = database
        self.status = status
        self.reason = reason
        super().__init__(reason)


def _read_runtime_database() -> str | None:
    if not RUNTIME_DATABASE_PATH.exists():
        return None
    try:
        data = json.loads(RUNTIME_DATABASE_PATH.read_text("utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    db = data.get("postgres_db")
    return str(db).strip() if db else None


def _write_runtime_database(database: str) -> None:
    RUNTIME_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_DATABASE_PATH.write_text(
        json.dumps({"postgres_db": database}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_database_name(database_url: str) -> str:
    parsed = urlparse(database_url.replace("+psycopg_async", ""))
    path = (parsed.path or "").lstrip("/")
    return path.split("?")[0] if path else ""


def resolve_active_database_name(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    runtime_db = _read_runtime_database()
    if runtime_db:
        return runtime_db
    return parse_database_name(cfg.database_url) or cfg.postgres_db


def resolve_active_database_url(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    db = resolve_active_database_name(cfg)
    return cfg.build_database_url(database=db)


def build_admin_engine(database: str | None = None) -> AsyncEngine:
    cfg = get_settings()
    url = cfg.build_database_url(database=database) if database else resolve_active_database_url(cfg)
    return create_async_engine(url, pool_pre_ping=True)


async def _fetch_table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
        return {row[0] for row in result.fetchall()}


async def _has_resource_code_column(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'atlas_resources' "
                "AND column_name = 'resource_code' LIMIT 1"
            )
        )
        return result.first() is not None


async def _has_legacy_atlas_code_column(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'atlas_resources' "
                "AND column_name = 'atlas_code' LIMIT 1"
            )
        )
        return result.first() is not None


async def validate_database_schema(database: str) -> dict:
    """Validate MVP1 schema for one database. Read-only."""
    if not _DB_NAME_PATTERN.match(database):
        return {
            "database": database,
            "schema_status": DatabaseSchemaStatus.unreachable,
            "missing_tables": list(MVP1_REQUIRED_TABLES),
            "present_tables": [],
            "notes": ["invalid database name"],
        }

    engine = build_admin_engine(database)
    notes: list[str] = []
    try:
        tables = await _fetch_table_names(engine)
    except Exception as exc:
        logger.warning("database validate failed for %s: %s", database, exc)
        await engine.dispose()
        return {
            "database": database,
            "schema_status": DatabaseSchemaStatus.unreachable,
            "missing_tables": list(MVP1_REQUIRED_TABLES),
            "present_tables": [],
            "notes": ["connection failed"],
        }

    present = [t for t in MVP1_REQUIRED_TABLES if t in tables]
    missing = [t for t in MVP1_REQUIRED_TABLES if t not in tables]

    if not tables:
        status = DatabaseSchemaStatus.empty
    elif "atlas_resources" not in tables:
        status = DatabaseSchemaStatus.partial if present else DatabaseSchemaStatus.empty
    else:
        has_resource_code = await _has_resource_code_column(engine)
        has_legacy_code = await _has_legacy_atlas_code_column(engine)
        if has_resource_code and not missing:
            status = DatabaseSchemaStatus.mvp1_ready
        elif has_legacy_code or not has_resource_code:
            notes.append("legacy atlas_resources schema (atlas_code, no resource_code)")
            status = DatabaseSchemaStatus.legacy
        elif missing:
            status = DatabaseSchemaStatus.partial
        else:
            status = DatabaseSchemaStatus.mvp1_ready

    await engine.dispose()

    return {
        "database": database,
        "schema_status": status,
        "missing_tables": missing,
        "present_tables": present,
        "notes": notes,
    }


async def get_connection_status() -> dict:
    cfg = get_settings()
    current = resolve_active_database_name(cfg)
    validation = await validate_database_schema(current)
    engine = build_admin_engine(current)
    connected = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        connected = True
    except Exception:
        connected = False
    finally:
        await engine.dispose()

    return {
        "host": cfg.postgres_host,
        "port": cfg.postgres_port,
        "user": cfg.postgres_user,
        "current_database": current,
        "connected": connected,
        "schema_status": validation["schema_status"],
        "missing_tables": validation["missing_tables"],
        "notes": validation["notes"],
    }


async def list_postgres_databases() -> dict:
    cfg = get_settings()
    current = resolve_active_database_name(cfg)
    admin_engine = build_admin_engine("postgres")
    items: list[dict] = []
    try:
        async with admin_engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT datname FROM pg_database "
                    "WHERE datistemplate = false ORDER BY datname"
                )
            )
            names = [row[0] for row in result.fetchall()]
    except Exception as exc:
        logger.warning("list databases failed: %s", exc)
        await admin_engine.dispose()
        return {
            "host": cfg.postgres_host,
            "port": cfg.postgres_port,
            "current_database": current,
            "items": [],
        }
    finally:
        await admin_engine.dispose()

    for name in names:
        validation = await validate_database_schema(name)
        items.append(
            {
                "name": name,
                "schema_status": validation["schema_status"],
                "is_current": name == current,
                "missing_tables": validation["missing_tables"],
                "notes": validation["notes"],
            }
        )

    return {
        "host": cfg.postgres_host,
        "port": cfg.postgres_port,
        "current_database": current,
        "items": items,
    }


async def switch_database(database: str) -> dict:
    if not _DB_NAME_PATTERN.match(database):
        raise DatabaseSwitchNotAllowedError(
            database, DatabaseSchemaStatus.unreachable, "invalid database name"
        )

    previous = resolve_active_database_name()
    validation = await validate_database_schema(database)
    status = validation["schema_status"]
    if status != DatabaseSchemaStatus.mvp1_ready:
        raise DatabaseSwitchNotAllowedError(
            database,
            status,
            f"database {database!r} is not MVP1-ready (status={status.value})",
        )

    _write_runtime_database(database)

    from app.database import reload_database_engine

    await reload_database_engine(database)

    return {
        "ok": True,
        "previous_database": previous,
        "current_database": database,
        "schema_status": status,
        "message": f"switched to {database}",
    }
