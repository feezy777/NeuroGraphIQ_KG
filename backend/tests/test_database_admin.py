"""Database admin tests (no PostgreSQL required for pure helpers)."""

from __future__ import annotations

import json

import pytest

from app.schemas.database_admin import DatabaseSchemaStatus
from app.services import database_admin_service


def test_parse_database_name_from_async_url():
    url = "postgresql+psycopg_async://postgres:secret@127.0.0.1:5432/neurographiq_kg_v3_mvp1_e2e"
    assert database_admin_service.parse_database_name(url) == "neurographiq_kg_v3_mvp1_e2e"


def test_resolve_active_database_prefers_runtime(tmp_path, monkeypatch):
    runtime_path = tmp_path / "database.local.json"
    runtime_path.write_text(json.dumps({"postgres_db": "neurographiq_kg_v3_mvp1_e2e"}), encoding="utf-8")
    monkeypatch.setattr(database_admin_service, "RUNTIME_DATABASE_PATH", runtime_path)

    name = database_admin_service.resolve_active_database_name()
    assert name == "neurographiq_kg_v3_mvp1_e2e"


def test_validate_rejects_invalid_database_name():
    import asyncio

    result = asyncio.run(database_admin_service.validate_database_schema("bad-name!"))
    assert result["schema_status"] == DatabaseSchemaStatus.unreachable
    assert "invalid database name" in result["notes"][0]


def test_mvp1_required_tables_include_core_tables():
    tables = database_admin_service.MVP1_REQUIRED_TABLES
    assert "atlas_resources" in tables
    assert "final_brain_regions" in tables
    assert "candidate_brain_regions" in tables


def test_switch_rejects_non_mvp1_database(tmp_path, monkeypatch):
    import asyncio

    runtime_path = tmp_path / "database.local.json"
    monkeypatch.setattr(database_admin_service, "RUNTIME_DATABASE_PATH", runtime_path)

    async def fake_validate(database: str):
        return {
            "database": database,
            "schema_status": DatabaseSchemaStatus.legacy,
            "missing_tables": [],
            "present_tables": ["atlas_resources"],
            "notes": ["legacy"],
        }

    monkeypatch.setattr(database_admin_service, "validate_database_schema", fake_validate)

    with pytest.raises(database_admin_service.DatabaseSwitchNotAllowedError) as exc:
        asyncio.run(database_admin_service.switch_database("neurographiq_kg_v3_wb"))

    assert exc.value.status == DatabaseSchemaStatus.legacy


def test_database_switch_not_allowed_error_fields():
    err = database_admin_service.DatabaseSwitchNotAllowedError(
        "db_x", DatabaseSchemaStatus.partial, "not ready"
    )
    assert err.database == "db_x"
    assert "not ready" in str(err)
