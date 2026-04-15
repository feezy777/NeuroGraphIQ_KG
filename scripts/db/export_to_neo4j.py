from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row

from scripts.modules.workbench.config.runtime_config import db_config, load_runtime


ROOT_DIR = Path(__file__).resolve().parents[2]
ALLOWED_GRANULARITIES = ("major", "sub", "allen", "all")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class RegionSpec:
    granularity: str
    label: str
    table: str
    id_col: str
    parent_col: str
    parent_label: str
    parent_id_col: str
    hierarchy_rel: str


@dataclass(frozen=True)
class ConnectionSpec:
    granularity: str
    label: str
    table: str
    id_col: str
    source_col: str
    target_col: str
    region_label: str
    region_id_col: str


@dataclass(frozen=True)
class CircuitSpec:
    granularity: str
    label: str
    table: str
    id_col: str
    node_table: str
    node_circuit_col: str
    node_region_col: str
    region_label: str
    region_id_col: str
    circuit_connection_table: str
    circuit_connection_circuit_col: str
    circuit_connection_connection_col: str
    connection_label: str
    connection_id_col: str


REGION_SPECS: Dict[str, RegionSpec] = {
    "major": RegionSpec(
        granularity="major",
        label="MajorRegion",
        table="major_brain_region",
        id_col="major_region_id",
        parent_col="",
        parent_label="",
        parent_id_col="",
        hierarchy_rel="",
    ),
    "sub": RegionSpec(
        granularity="sub",
        label="SubRegion",
        table="sub_brain_region",
        id_col="sub_region_id",
        parent_col="parent_major_region_id",
        parent_label="MajorRegion",
        parent_id_col="major_region_id",
        hierarchy_rel="SUB_REGION_OF",
    ),
    "allen": RegionSpec(
        granularity="allen",
        label="AllenRegion",
        table="allen_brain_region",
        id_col="allen_region_id",
        parent_col="parent_sub_region_id",
        parent_label="SubRegion",
        parent_id_col="sub_region_id",
        hierarchy_rel="ALLEN_REGION_OF",
    ),
}

CONNECTION_SPECS: Dict[str, ConnectionSpec] = {
    "major": ConnectionSpec(
        granularity="major",
        label="MajorConnection",
        table="major_connection",
        id_col="major_connection_id",
        source_col="source_major_region_id",
        target_col="target_major_region_id",
        region_label="MajorRegion",
        region_id_col="major_region_id",
    ),
    "sub": ConnectionSpec(
        granularity="sub",
        label="SubConnection",
        table="sub_connection",
        id_col="sub_connection_id",
        source_col="source_sub_region_id",
        target_col="target_sub_region_id",
        region_label="SubRegion",
        region_id_col="sub_region_id",
    ),
    "allen": ConnectionSpec(
        granularity="allen",
        label="AllenConnection",
        table="allen_connection",
        id_col="allen_connection_id",
        source_col="source_allen_region_id",
        target_col="target_allen_region_id",
        region_label="AllenRegion",
        region_id_col="allen_region_id",
    ),
}

CIRCUIT_SPECS: Dict[str, CircuitSpec] = {
    "major": CircuitSpec(
        granularity="major",
        label="MajorCircuit",
        table="major_circuit",
        id_col="major_circuit_id",
        node_table="major_circuit_node",
        node_circuit_col="major_circuit_id",
        node_region_col="major_region_id",
        region_label="MajorRegion",
        region_id_col="major_region_id",
        circuit_connection_table="major_circuit_connection",
        circuit_connection_circuit_col="major_circuit_id",
        circuit_connection_connection_col="major_connection_id",
        connection_label="MajorConnection",
        connection_id_col="major_connection_id",
    ),
    "sub": CircuitSpec(
        granularity="sub",
        label="SubCircuit",
        table="sub_circuit",
        id_col="sub_circuit_id",
        node_table="sub_circuit_node",
        node_circuit_col="sub_circuit_id",
        node_region_col="sub_region_id",
        region_label="SubRegion",
        region_id_col="sub_region_id",
        circuit_connection_table="sub_circuit_connection",
        circuit_connection_circuit_col="sub_circuit_id",
        circuit_connection_connection_col="sub_connection_id",
        connection_label="SubConnection",
        connection_id_col="sub_connection_id",
    ),
    "allen": CircuitSpec(
        granularity="allen",
        label="AllenCircuit",
        table="allen_circuit",
        id_col="allen_circuit_id",
        node_table="allen_circuit_node",
        node_circuit_col="allen_circuit_id",
        node_region_col="allen_region_id",
        region_label="AllenRegion",
        region_id_col="allen_region_id",
        circuit_connection_table="allen_circuit_connection",
        circuit_connection_circuit_col="allen_circuit_id",
        circuit_connection_connection_col="allen_connection_id",
        connection_label="AllenConnection",
        connection_id_col="allen_connection_id",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export NeuroGraphIQ production schema (Postgres) into Neo4j."
    )
    parser.add_argument(
        "--granularity",
        choices=ALLOWED_GRANULARITIES,
        default="all",
        help="Import scope: major|sub|allen|all",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print import counts, do not write to Neo4j.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="UNWIND batch size for Neo4j writes.",
    )
    parser.add_argument(
        "--root-dir",
        default=str(ROOT_DIR),
        help="Repository root containing configs/local/runtime.local.yaml",
    )
    return parser.parse_args()


def _must_identifier(value: str, field: str) -> str:
    if not value or not IDENT_RE.match(value):
        raise ValueError(f"invalid_identifier:{field}:{value}")
    return value


def _selected_granularities(raw: str) -> List[str]:
    if raw == "all":
        return ["major", "sub", "allen"]
    return [raw]


def _pg_conn_kwargs(cfg: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "host": cfg.get("host", "localhost"),
        "port": int(cfg.get("port", 5432)),
        "dbname": cfg.get("dbname"),
        "user": cfg.get("user", "postgres"),
        "password": cfg.get("password", ""),
        "row_factory": dict_row,
    }


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in value.items()}
    return value


def _normalize_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: _normalize_value(v) for k, v in row.items()}


def _fetch_rows(conn: psycopg.Connection, sql: str, params: Sequence[Any] | None = None) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchall()
    return [_normalize_row(r) for r in rows]


def _fetch_count(conn: psycopg.Connection, sql: str, params: Sequence[Any] | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
    if not row:
        return 0
    return int(row.get("cnt", 0))


def _chunks(rows: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _counter_dict() -> Dict[str, int]:
    return {
        "nodes_created": 0,
        "relationships_created": 0,
        "properties_set": 0,
        "constraints_added": 0,
    }


def _merge_counters(base: Dict[str, int], update: Dict[str, int]) -> None:
    for k, v in update.items():
        base[k] = base.get(k, 0) + int(v)


def _summary_to_counter_dict(summary: Any) -> Dict[str, int]:
    counters = summary.counters
    return {
        "nodes_created": int(counters.nodes_created),
        "relationships_created": int(counters.relationships_created),
        "properties_set": int(counters.properties_set),
        "constraints_added": int(counters.constraints_added),
    }


class Neo4jWriter:
    def __init__(self, uri: str, user: str, password: str, database: str, batch_size: int) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "neo4j driver not installed. Run: pip install -r requirements.txt"
            ) from exc
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        self._batch_size = max(1, int(batch_size))

    def close(self) -> None:
        self._driver.close()

    def check_connectivity(self) -> None:
        self._driver.verify_connectivity()

    def run_query(self, query: str, params: Dict[str, Any] | None = None) -> Dict[str, int]:
        with self._driver.session(database=self._database) as session:
            result = session.run(query, params or {})
            summary = result.consume()
        return _summary_to_counter_dict(summary)

    def run_batched(self, query: str, rows: List[Dict[str, Any]]) -> Dict[str, int]:
        totals = _counter_dict()
        if not rows:
            return totals
        now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        with self._driver.session(database=self._database) as session:
            for batch in _chunks(rows, self._batch_size):
                result = session.run(query, {"rows": batch, "updated_at": now_iso})
                summary = result.consume()
                _merge_counters(totals, _summary_to_counter_dict(summary))
        return totals


def _node_merge_query(label: str, id_col: str) -> str:
    return f"""
UNWIND $rows AS row
MERGE (n:{label} {{{id_col}: row.{id_col}}})
SET n += row
"""


def _region_hierarchy_query(
    child_label: str,
    child_id_col: str,
    parent_label: str,
    parent_id_col: str,
    rel_type: str,
) -> str:
    return f"""
UNWIND $rows AS row
MATCH (child:{child_label} {{{child_id_col}: row.child_id}})
MATCH (parent:{parent_label} {{{parent_id_col}: row.parent_id}})
MERGE (child)-[rel:{rel_type}]->(parent)
SET rel.updated_at = $updated_at
"""


def _connection_region_query(
    connection_label: str,
    connection_id_col: str,
    region_label: str,
    region_id_col: str,
    rel_type: str,
) -> str:
    return f"""
UNWIND $rows AS row
MATCH (c:{connection_label} {{{connection_id_col}: row.connection_id}})
MATCH (r:{region_label} {{{region_id_col}: row.region_id}})
MERGE (c)-[rel:{rel_type}]->(r)
SET rel.updated_at = $updated_at
"""


def _circuit_node_query(
    circuit_label: str,
    circuit_id_col: str,
    region_label: str,
    region_id_col: str,
) -> str:
    return f"""
UNWIND $rows AS row
MATCH (c:{circuit_label} {{{circuit_id_col}: row.circuit_id}})
MATCH (r:{region_label} {{{region_id_col}: row.region_id}})
MERGE (c)-[rel:HAS_NODE {{node_order: row.node_order}}]->(r)
SET rel.role_label = row.role_label,
    rel.updated_at = $updated_at
"""


def _circuit_connection_query(
    circuit_label: str,
    circuit_id_col: str,
    connection_label: str,
    connection_id_col: str,
) -> str:
    return f"""
UNWIND $rows AS row
MATCH (c:{circuit_label} {{{circuit_id_col}: row.circuit_id}})
MATCH (conn:{connection_label} {{{connection_id_col}: row.connection_id}})
MERGE (c)-[rel:INCLUDES_CONNECTION {{edge_order: row.edge_order}}]->(conn)
SET rel.updated_at = $updated_at
"""


def _build_constraints(levels: List[str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for lvl in levels:
        r = REGION_SPECS[lvl]
        c = CONNECTION_SPECS[lvl]
        cc = CIRCUIT_SPECS[lvl]
        out.extend(
            [
                {"label": r.label, "id_col": r.id_col},
                {"label": c.label, "id_col": c.id_col},
                {"label": cc.label, "id_col": cc.id_col},
            ]
        )
    return out


def _collect_counts(conn: psycopg.Connection, schema: str, levels: List[str]) -> Dict[str, Any]:
    counts: Dict[str, Any] = {
        "regions": {},
        "region_hierarchy_edges": {},
        "connections": {},
        "connection_edges": {},
        "circuits": {},
        "circuit_edges": {},
    }
    for lvl in levels:
        rs = REGION_SPECS[lvl]
        counts["regions"][lvl] = _fetch_count(conn, f"select count(*) as cnt from {schema}.{rs.table}")
        if rs.parent_col:
            counts["region_hierarchy_edges"][rs.hierarchy_rel] = _fetch_count(
                conn,
                f"""
select count(*) as cnt
from {schema}.{rs.table}
where {rs.parent_col} is not null
  and {rs.parent_col} <> ''
""",
            )

        cs = CONNECTION_SPECS[lvl]
        conn_count = _fetch_count(conn, f"select count(*) as cnt from {schema}.{cs.table}")
        src_count = _fetch_count(
            conn,
            f"""
select count(*) as cnt
from {schema}.{cs.table}
where {cs.source_col} is not null
  and {cs.source_col} <> ''
""",
        )
        tgt_count = _fetch_count(
            conn,
            f"""
select count(*) as cnt
from {schema}.{cs.table}
where {cs.target_col} is not null
  and {cs.target_col} <> ''
""",
        )
        counts["connections"][lvl] = conn_count
        counts["connection_edges"][f"{lvl}.SOURCE_REGION"] = src_count
        counts["connection_edges"][f"{lvl}.TARGET_REGION"] = tgt_count

        ccs = CIRCUIT_SPECS[lvl]
        circuit_count = _fetch_count(conn, f"select count(*) as cnt from {schema}.{ccs.table}")
        has_node_count = _fetch_count(conn, f"select count(*) as cnt from {schema}.{ccs.node_table}")
        include_conn_count = _fetch_count(
            conn,
            f"select count(*) as cnt from {schema}.{ccs.circuit_connection_table}",
        )
        counts["circuits"][lvl] = circuit_count
        counts["circuit_edges"][f"{lvl}.HAS_NODE"] = has_node_count
        counts["circuit_edges"][f"{lvl}.INCLUDES_CONNECTION"] = include_conn_count
    return counts


def _import_regions(
    conn: psycopg.Connection,
    writer: Neo4jWriter,
    schema: str,
    levels: List[str],
) -> Dict[str, int]:
    totals = _counter_dict()
    for lvl in levels:
        spec = REGION_SPECS[lvl]
        rows = _fetch_rows(conn, f"select * from {schema}.{spec.table}")
        query = _node_merge_query(spec.label, spec.id_col)
        _merge_counters(totals, writer.run_batched(query, rows))
    return totals


def _import_region_hierarchy(
    conn: psycopg.Connection,
    writer: Neo4jWriter,
    schema: str,
    levels: List[str],
) -> Dict[str, int]:
    totals = _counter_dict()
    for lvl in levels:
        spec = REGION_SPECS[lvl]
        if not spec.parent_col:
            continue
        rows = _fetch_rows(
            conn,
            f"""
select
  {spec.id_col} as child_id,
  {spec.parent_col} as parent_id
from {schema}.{spec.table}
where {spec.parent_col} is not null
  and {spec.parent_col} <> ''
""",
        )
        query = _region_hierarchy_query(
            child_label=spec.label,
            child_id_col=spec.id_col,
            parent_label=spec.parent_label,
            parent_id_col=spec.parent_id_col,
            rel_type=spec.hierarchy_rel,
        )
        _merge_counters(totals, writer.run_batched(query, rows))
    return totals


def _import_connections(
    conn: psycopg.Connection,
    writer: Neo4jWriter,
    schema: str,
    levels: List[str],
) -> Dict[str, int]:
    totals = _counter_dict()
    for lvl in levels:
        spec = CONNECTION_SPECS[lvl]
        rows = _fetch_rows(conn, f"select * from {schema}.{spec.table}")
        _merge_counters(totals, writer.run_batched(_node_merge_query(spec.label, spec.id_col), rows))

        source_rows = _fetch_rows(
            conn,
            f"""
select
  {spec.id_col} as connection_id,
  {spec.source_col} as region_id
from {schema}.{spec.table}
where {spec.source_col} is not null
  and {spec.source_col} <> ''
""",
        )
        target_rows = _fetch_rows(
            conn,
            f"""
select
  {spec.id_col} as connection_id,
  {spec.target_col} as region_id
from {schema}.{spec.table}
where {spec.target_col} is not null
  and {spec.target_col} <> ''
""",
        )
        _merge_counters(
            totals,
            writer.run_batched(
                _connection_region_query(
                    connection_label=spec.label,
                    connection_id_col=spec.id_col,
                    region_label=spec.region_label,
                    region_id_col=spec.region_id_col,
                    rel_type="SOURCE_REGION",
                ),
                source_rows,
            ),
        )
        _merge_counters(
            totals,
            writer.run_batched(
                _connection_region_query(
                    connection_label=spec.label,
                    connection_id_col=spec.id_col,
                    region_label=spec.region_label,
                    region_id_col=spec.region_id_col,
                    rel_type="TARGET_REGION",
                ),
                target_rows,
            ),
        )
    return totals


def _import_circuits(
    conn: psycopg.Connection,
    writer: Neo4jWriter,
    schema: str,
    levels: List[str],
) -> Dict[str, int]:
    totals = _counter_dict()
    for lvl in levels:
        spec = CIRCUIT_SPECS[lvl]
        rows = _fetch_rows(conn, f"select * from {schema}.{spec.table}")
        _merge_counters(totals, writer.run_batched(_node_merge_query(spec.label, spec.id_col), rows))

        node_rows = _fetch_rows(
            conn,
            f"""
select
  {spec.node_circuit_col} as circuit_id,
  {spec.node_region_col} as region_id,
  coalesce(node_order, 1) as node_order,
  coalesce(role_label, '') as role_label
from {schema}.{spec.node_table}
where {spec.node_region_col} is not null
  and {spec.node_region_col} <> ''
""",
        )
        for row in node_rows:
            row["node_order"] = int(row.get("node_order", 1))
            row["role_label"] = row.get("role_label", "") or ""

        _merge_counters(
            totals,
            writer.run_batched(
                _circuit_node_query(
                    circuit_label=spec.label,
                    circuit_id_col=spec.id_col,
                    region_label=spec.region_label,
                    region_id_col=spec.region_id_col,
                ),
                node_rows,
            ),
        )

        include_rows = _fetch_rows(
            conn,
            f"""
select
  {spec.circuit_connection_circuit_col} as circuit_id,
  {spec.circuit_connection_connection_col} as connection_id,
  coalesce(edge_order, -1) as edge_order
from {schema}.{spec.circuit_connection_table}
where {spec.circuit_connection_connection_col} is not null
  and {spec.circuit_connection_connection_col} <> ''
""",
        )
        for row in include_rows:
            row["edge_order"] = int(row.get("edge_order", -1))
        _merge_counters(
            totals,
            writer.run_batched(
                _circuit_connection_query(
                    circuit_label=spec.label,
                    circuit_id_col=spec.id_col,
                    connection_label=spec.connection_label,
                    connection_id_col=spec.connection_id_col,
                ),
                include_rows,
            ),
        )
    return totals


def _ensure_constraints(writer: Neo4jWriter, levels: List[str]) -> Dict[str, int]:
    totals = _counter_dict()
    for item in _build_constraints(levels):
        label = _must_identifier(item["label"], "label")
        id_col = _must_identifier(item["id_col"], "id_col")
        constraint_name = _must_identifier(f"uniq_{label.lower()}_{id_col.lower()}", "constraint_name")
        query = (
            f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{id_col} IS UNIQUE"
        )
        _merge_counters(totals, writer.run_query(query))
    return totals


def _read_neo4j_env() -> Dict[str, str]:
    cfg = {
        "uri": os.getenv("NEO4J_URI", "").strip(),
        "user": os.getenv("NEO4J_USER", "").strip(),
        "password": os.getenv("NEO4J_PASSWORD", "").strip(),
        "database": os.getenv("NEO4J_DATABASE", "neo4j").strip() or "neo4j",
    }
    missing = [k for k in ("uri", "user", "password") if not cfg[k]]
    if missing:
        raise ValueError(
            f"missing_neo4j_env:{','.join(missing)}. "
            "Required env: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD (optional NEO4J_DATABASE)."
        )
    return cfg


def main() -> int:
    args = parse_args()
    levels = _selected_granularities(args.granularity)
    root_dir = Path(args.root_dir).resolve()

    runtime = load_runtime(str(root_dir))
    production_cfg = db_config(runtime, "production_db")
    schema = _must_identifier(str(production_cfg.get("schema", "neurokg")), "schema")
    dbname = str(production_cfg.get("dbname", "")).strip()
    if not dbname:
        raise ValueError("missing_production_db_name")

    report: Dict[str, Any] = {
        "mode": "dry-run" if args.dry_run else "write",
        "root_dir": str(root_dir),
        "postgres": {
            "host": production_cfg.get("host", "localhost"),
            "port": int(production_cfg.get("port", 5432)),
            "dbname": dbname,
            "schema": schema,
        },
        "granularity": levels,
    }

    with psycopg.connect(**_pg_conn_kwargs(production_cfg)) as pg_conn:
        counts = _collect_counts(pg_conn, schema, levels)
        report["counts"] = counts

        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        neo_cfg = _read_neo4j_env()
        report["neo4j"] = {
            "uri": neo_cfg["uri"],
            "database": neo_cfg["database"],
            "user": neo_cfg["user"],
        }

        writer = Neo4jWriter(
            uri=neo_cfg["uri"],
            user=neo_cfg["user"],
            password=neo_cfg["password"],
            database=neo_cfg["database"],
            batch_size=args.batch_size,
        )
        try:
            writer.check_connectivity()
            write_stats: Dict[str, Any] = {}
            write_stats["constraints"] = _ensure_constraints(writer, levels)
            write_stats["regions"] = _import_regions(pg_conn, writer, schema, levels)
            write_stats["region_hierarchy"] = _import_region_hierarchy(pg_conn, writer, schema, levels)
            write_stats["connections"] = _import_connections(pg_conn, writer, schema, levels)
            write_stats["circuits"] = _import_circuits(pg_conn, writer, schema, levels)
            report["write_stats"] = write_stats
        finally:
            writer.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[export_to_neo4j] failed: {exc}", file=sys.stderr)
        sys.exit(1)
