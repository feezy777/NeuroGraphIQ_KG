from __future__ import annotations

import psycopg2
import pytest

from scripts.services.runtime_config import apply_runtime_env, load_runtime_config
from scripts.services.schema_service import rebuild_schema
from scripts.utils.db import cursor, db_config


def _db_ready() -> bool:
    try:
        conn = psycopg2.connect(**db_config())
    except Exception:
        return False
    conn.close()
    return True


@pytest.mark.integration
def test_schema_rebuild_and_seed() -> None:
    runtime = load_runtime_config()
    apply_runtime_env(runtime)
    if not _db_ready():
        pytest.skip("PostgreSQL is not available for integration test.")

    stats = rebuild_schema()
    assert stats["table_count"] == 36
    assert stats["major_region_id_type"] == "text"
    assert stats["id_column_count"] == stats["id_text_column_count"]

    with cursor() as (_, cur):
        cur.execute("select organism_id from organism where organism_id='ORG_HUMAN'")
        assert cur.fetchone() is not None
        cur.execute("select division_id from brain_division where division_id='DIV_NON_LOBE_DIVISION_BRAIN'")
        assert cur.fetchone() is not None

