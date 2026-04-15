from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict

import psycopg
from psycopg.rows import dict_row


def conn_kwargs(cfg: Dict[str, Any], autocommit: bool = False) -> Dict[str, Any]:
    return {
        "host": cfg.get("host", "localhost"),
        "port": int(cfg.get("port", 5432)),
        "dbname": cfg.get("dbname"),
        "user": cfg.get("user", "postgres"),
        "password": cfg.get("password", ""),
        "autocommit": autocommit,
    }


class PostgresClient:
    def __init__(self, cfg: Dict[str, Any], schema: str) -> None:
        self.cfg = cfg
        self.schema = schema

    @contextmanager
    def connection(self):
        conn = psycopg.connect(**conn_kwargs(self.cfg), row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    def health(self) -> Dict[str, Any]:
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("select current_database() as db, now() as ts")
                    row = cur.fetchone()
            return {"ok": True, "db": row.get("db"), "schema": self.schema, "ts": str(row.get("ts"))}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "schema": self.schema}
