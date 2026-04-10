from __future__ import annotations

from pathlib import Path

import psycopg

from scripts.modules.workbench.config.runtime_config import db_config, load_runtime


ROOT_DIR = Path(__file__).resolve().parents[2]


def _conn_kwargs(cfg: dict) -> dict:
    return {
        "host": cfg.get("host", "localhost"),
        "port": int(cfg.get("port", 5432)),
        "dbname": cfg.get("dbname", "postgres"),
        "user": cfg.get("user", "postgres"),
        "password": cfg.get("password", ""),
        "autocommit": True,
    }


def create_database_if_missing(admin_cfg: dict, db_name: str) -> None:
    with psycopg.connect(**_conn_kwargs(admin_cfg)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            exists = cur.fetchone()
            if exists:
                print(f"[DB][BOOTSTRAP] database exists db={db_name}")
                return
            cur.execute(f'CREATE DATABASE "{db_name}"')
            print(f"[DB][BOOTSTRAP] database created db={db_name}")


def apply_sql(db_cfg: dict, sql_path: Path) -> None:
    sql_text = sql_path.read_text(encoding="utf-8")
    conn_cfg = _conn_kwargs(db_cfg)
    conn_cfg["autocommit"] = False
    with psycopg.connect(**conn_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)
        conn.commit()
    print(f"[DB][BOOTSTRAP] schema applied db={db_cfg.get('dbname')} file={sql_path.name}")


def apply_sql_dir(db_cfg: dict, sql_dir: Path, continue_on_error: bool = False) -> None:
    for sql_path in sorted(sql_dir.glob("*.sql")):
        try:
            apply_sql(db_cfg, sql_path)
        except Exception:
            if not continue_on_error:
                raise
            print(f"[DB][BOOTSTRAP] skip file db={db_cfg.get('dbname')} file={sql_path.name}")


def has_formal_region_tables(db_cfg: dict, schema: str) -> bool:
    conn_cfg = _conn_kwargs(db_cfg)
    conn_cfg["autocommit"] = True
    required = {"major_brain_region", "sub_brain_region", "allen_brain_region"}
    with psycopg.connect(**conn_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema=%s
                """,
                (schema,),
            )
            existing = {r[0] for r in cur.fetchall()}
    return required.issubset(existing)


def main() -> None:
    runtime = load_runtime(str(ROOT_DIR))
    admin_cfg = db_config(runtime, "admin_db")
    workbench_cfg = db_config(runtime, "workbench_db")
    unverified_cfg = db_config(runtime, "unverified_db")
    production_cfg = db_config(runtime, "production_db")

    for target in (workbench_cfg, unverified_cfg, production_cfg):
        create_database_if_missing(admin_cfg, target.get("dbname"))

    apply_sql_dir(workbench_cfg, ROOT_DIR / "sql" / "schema" / "workbench")
    for cfg, path, label in (
        (unverified_cfg, ROOT_DIR / "sql" / "schema" / "unverified", "unverified"),
    ):
        try:
            apply_sql_dir(cfg, path, continue_on_error=True)
        except Exception as exc:
            print(f"[DB][BOOTSTRAP] skip {label} schema apply reason={exc}")

    try:
        prod_schema = production_cfg.get("schema", "neurokg")
        if has_formal_region_tables(production_cfg, prod_schema):
            print(
                f"[DB][BOOTSTRAP] skip production schema apply reason=formal tables exist in {production_cfg.get('dbname')}.{prod_schema}"
            )
        else:
            apply_sql_dir(production_cfg, ROOT_DIR / "sql" / "schema" / "production", continue_on_error=True)
    except Exception as exc:
        print(f"[DB][BOOTSTRAP] skip production schema apply reason={exc}")

    print("[DB][BOOTSTRAP] completed")


if __name__ == "__main__":
    main()
