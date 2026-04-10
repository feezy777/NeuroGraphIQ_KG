from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import psycopg

from scripts.modules.workbench.config.runtime_config import db_config, load_runtime


ROOT_DIR = Path(__file__).resolve().parents[2]

REQUIRED_PACKAGES = ["flask", "yaml", "psycopg", "pypdf", "openpyxl"]

WORKBENCH_REQUIRED_TABLES: Dict[str, List[str]] = {
    "uploaded_file": [
        "id",
        "file_name",
        "file_type",
        "upload_status",
        "version",
        "checksum",
        "path",
        "latest_parse_task_id",
        "latest_extract_task_id",
        "latest_validate_task_id",
        "latest_map_task_id",
        "latest_ingest_task_id",
        "latest_commit_task_id",
    ],
    "parsed_document": ["id", "file_id", "parser_name", "parser_version", "document_json"],
    "content_chunk": ["id", "chunk_id", "file_id", "chunk_type", "chunk_text"],
    "candidate_region": ["id", "file_id", "granularity_candidate", "status", "region_category_candidate", "ontology_source_candidate"],
    "extraction_run": ["id", "file_id", "task_type", "status", "started_at", "finished_at"],
    "task_log_v2": ["id", "run_id", "level", "event_type", "message", "detail_json", "created_at"],
    "review_record": ["id", "candidate_region_id", "reviewer", "action", "before_json", "after_json"],
}

PRODUCTION_REQUIRED_TABLES: Dict[str, List[str]] = {
    "major_brain_region": ["major_region_id", "region_code", "en_name", "cn_name", "laterality", "region_category", "ontology_source", "data_source", "status"],
    "sub_brain_region": ["sub_region_id", "parent_major_region_id", "region_code", "en_name", "cn_name", "laterality", "region_category", "ontology_source", "data_source", "status"],
    "allen_brain_region": ["allen_region_id", "parent_sub_region_id", "region_code", "en_name", "cn_name", "laterality", "region_category", "ontology_source", "data_source", "status"],
}


def _conn_kwargs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "host": cfg.get("host", "localhost"),
        "port": int(cfg.get("port", 5432)),
        "dbname": cfg.get("dbname"),
        "user": cfg.get("user", "postgres"),
        "password": cfg.get("password", ""),
    }


def _pkg_check() -> Dict[str, Any]:
    rows = []
    missing = []
    for pkg in REQUIRED_PACKAGES:
        ok = importlib.util.find_spec(pkg) is not None
        rows.append({"package": pkg, "installed": ok})
        if not ok:
            missing.append(pkg)
    return {"items": rows, "missing": missing}


def _table_columns(cur: psycopg.Cursor, schema: str, table: str) -> List[str]:
    cur.execute(
        """
        select column_name
        from information_schema.columns
        where table_schema=%s and table_name=%s
        order by ordinal_position
        """,
        (schema, table),
    )
    return [r[0] for r in cur.fetchall()]


def _schema_check(cfg: Dict[str, Any], required: Dict[str, List[str]]) -> Dict[str, Any]:
    dbname = cfg.get("dbname")
    schema = cfg.get("schema", "public")
    result: Dict[str, Any] = {
        "db": dbname,
        "schema": schema,
        "connected": False,
        "error": "",
        "missing_tables": [],
        "missing_columns": {},
        "existing_tables": [],
    }
    try:
        with psycopg.connect(**_conn_kwargs(cfg)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select table_name
                    from information_schema.tables
                    where table_schema=%s
                    order by table_name
                    """,
                    (schema,),
                )
                tables = [r[0] for r in cur.fetchall()]
                result["existing_tables"] = tables
                result["connected"] = True

                for table, cols in required.items():
                    if table not in tables:
                        result["missing_tables"].append(table)
                        continue
                    existing_cols = _table_columns(cur, schema, table)
                    miss = [c for c in cols if c not in existing_cols]
                    if miss:
                        result["missing_columns"][table] = miss
    except Exception as exc:  # pragma: no cover
        result["error"] = str(exc)
    return result


def _fk_check_workbench(cfg: Dict[str, Any]) -> Dict[str, Any]:
    schema = cfg.get("schema", "workbench")
    out = {"fk_to_uploaded_file": 0, "fk_to_file_record": 0, "details": []}
    try:
        with psycopg.connect(**_conn_kwargs(cfg)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select conname, conrelid::regclass::text as child_table, confrelid::regclass::text as parent_table
                    from pg_constraint
                    where contype='f'
                      and (confrelid::regclass::text = %s or confrelid::regclass::text = %s)
                    order by conrelid::regclass::text, conname
                    """,
                    (f"{schema}.uploaded_file", f"{schema}.file_record"),
                )
                rows: List[Tuple[str, str, str]] = cur.fetchall()
        out["details"] = [{"constraint": r[0], "child_table": r[1], "parent_table": r[2]} for r in rows]
        out["fk_to_uploaded_file"] = sum(1 for r in rows if r[2] == f"{schema}.uploaded_file")
        out["fk_to_file_record"] = sum(1 for r in rows if r[2] == f"{schema}.file_record")
    except Exception as exc:  # pragma: no cover
        out["error"] = str(exc)
    return out


def main() -> None:
    runtime = load_runtime(str(ROOT_DIR))
    wb_cfg = db_config(runtime, "workbench_db")
    uv_cfg = db_config(runtime, "unverified_db")
    prod_cfg = db_config(runtime, "production_db")

    report = {
        "root_dir": str(ROOT_DIR),
        "python": {"executable": __import__("sys").executable},
        "packages": _pkg_check(),
        "workbench": _schema_check(wb_cfg, WORKBENCH_REQUIRED_TABLES),
        "unverified": _schema_check(
            uv_cfg,
            {
                "unverified_file_runs": ["run_id", "file_id", "task_id", "overall_label", "status"],
                "unverified_file_payloads": ["id", "run_id", "file_id", "task_id"],
                "unverified_region": ["id", "source_candidate_region_id", "source_file_id", "granularity", "validation_status", "promotion_status"],
                "unverified_region_validation": ["id", "unverified_region_id", "validation_type", "status", "score", "detail_json"],
                "promotion_record": ["id", "unverified_region_id", "target_table", "target_region_id", "region_code", "status"],
            },
        ),
        "production": _schema_check(prod_cfg, PRODUCTION_REQUIRED_TABLES),
        "workbench_fk": _fk_check_workbench(wb_cfg),
    }

    summary = {
        "missing_packages": report["packages"]["missing"],
        "workbench_missing_tables": report["workbench"]["missing_tables"],
        "workbench_missing_columns": report["workbench"]["missing_columns"],
        "production_missing_tables": report["production"]["missing_tables"],
        "production_missing_columns": report["production"]["missing_columns"],
        "fk_to_file_record": report["workbench_fk"].get("fk_to_file_record", 0),
        "fk_to_uploaded_file": report["workbench_fk"].get("fk_to_uploaded_file", 0),
    }
    report["summary"] = summary

    out_path = ROOT_DIR / "artifacts" / "workbench" / "db_doctor_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[DB_DOCTOR] summary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[DB_DOCTOR] report={out_path}")


if __name__ == "__main__":
    main()
