from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from scripts.utils.db import cursor


ProgressCallback = Callable[[dict[str, Any]], None]


def _emit(callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
    if callback:
        callback(payload)


def _sorted_sql_files(path: Path) -> list[Path]:
    return sorted(path.glob("*.sql"), key=lambda item: item.name)


def rebuild_schema(callback: ProgressCallback | None = None) -> dict[str, Any]:
    schema_files = _sorted_sql_files(Path("sql") / "schema")
    remaining_schema_files = [f for f in schema_files if f.name != "001_create_schema.sql"]
    seed_files = _sorted_sql_files(Path("sql") / "seeds")
    total_steps = 2 + len(remaining_schema_files) + len(seed_files)
    completed = 0

    with cursor() as (_, cur):
        _emit(
            callback,
            {
                "status": "running",
                "current_stage": "drop_schema",
                "completed_steps": completed,
                "total_steps": total_steps,
            },
        )
        cur.execute("drop schema if exists neurokg cascade")
        completed += 1

        _emit(
            callback,
            {
                "status": "running",
                "current_stage": "create_schema",
                "completed_steps": completed,
                "total_steps": total_steps,
            },
        )
        cur.execute((Path("sql") / "schema" / "001_create_schema.sql").read_text(encoding="utf-8"))
        completed += 1

        for sql_file in remaining_schema_files:
            _emit(
                callback,
                {
                    "status": "running",
                    "current_stage": f"schema::{sql_file.name}",
                    "completed_steps": completed,
                    "total_steps": total_steps,
                },
            )
            cur.execute(sql_file.read_text(encoding="utf-8"))
            completed += 1

        for seed_file in seed_files:
            _emit(
                callback,
                {
                    "status": "running",
                    "current_stage": f"seed::{seed_file.name}",
                    "completed_steps": completed,
                    "total_steps": total_steps,
                },
            )
            cur.execute(seed_file.read_text(encoding="utf-8"))
            completed += 1

    stats = schema_stats()
    _emit(
        callback,
        {
            "status": "succeeded",
            "current_stage": "done",
            "completed_steps": total_steps,
            "total_steps": total_steps,
            "stage_counts": stats,
        },
    )
    return stats


def schema_stats() -> dict[str, Any]:
    with cursor() as (_, cur):
        cur.execute("select count(*) from information_schema.tables where table_schema='neurokg'")
        table_count = int(cur.fetchone()[0])

        cur.execute("select count(*) from pg_indexes where schemaname='neurokg'")
        index_count = int(cur.fetchone()[0])

        cur.execute(
            """
            select count(*)
            from pg_trigger t
            join pg_class c on t.tgrelid = c.oid
            join pg_namespace n on c.relnamespace = n.oid
            where n.nspname = 'neurokg' and not t.tgisinternal
            """
        )
        trigger_count = int(cur.fetchone()[0])

        cur.execute(
            """
            select count(*)
            from information_schema.columns
            where table_schema='neurokg' and column_name like '%\\_id' escape '\\'
            """
        )
        id_column_count = int(cur.fetchone()[0])

        cur.execute(
            """
            select count(*)
            from information_schema.columns
            where table_schema='neurokg' and column_name like '%\\_id' escape '\\' and data_type='text'
            """
        )
        id_text_column_count = int(cur.fetchone()[0])

        cur.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_schema='neurokg' and table_name='major_brain_region' and column_name='major_region_id'
            """
        )
        major_region_id_type = cur.fetchone()

    return {
        "table_count": table_count,
        "index_count": index_count,
        "trigger_count": trigger_count,
        "id_column_count": id_column_count,
        "id_text_column_count": id_text_column_count,
        "major_region_id_type": major_region_id_type[1] if major_region_id_type else None,
    }
