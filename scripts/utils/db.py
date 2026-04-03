from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2


def db_config() -> dict:
    return {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "database": os.getenv("PGDATABASE", "neurographiq_kg_v2"),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", ""),
    }


def target_schema() -> str:
    return os.getenv("PGSCHEMA", "neurokg")


@contextmanager
def cursor(autocommit: bool = False) -> Iterator:
    conn = psycopg2.connect(**db_config())
    conn.autocommit = autocommit
    try:
        with conn.cursor() as cur:
            cur.execute(f"set search_path to {target_schema()}, public")
            yield conn, cur
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()
