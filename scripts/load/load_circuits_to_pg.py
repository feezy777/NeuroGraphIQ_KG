from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.db import cursor
from scripts.utils.io_utils import read_records, write_json
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def run_load_circuits(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)
    upserted_circuits = 0
    upserted_nodes = 0
    upserted_edges = 0

    with cursor() as (_, cur):
        for record in records:
            cur.execute(
                """
                insert into major_circuit (
                    major_circuit_id, circuit_code, en_name, cn_name, alias, description,
                    circuit_kind, loop_type, cycle_verified, confidence_circuit,
                    validation_status_circuit, node_count, connection_count,
                    data_source, status, remark
                )
                values (
                    %(major_circuit_id)s, %(circuit_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s,
                    %(circuit_kind)s, %(loop_type)s, %(cycle_verified)s, %(confidence_circuit)s,
                    %(validation_status_circuit)s, %(node_count)s, %(connection_count)s,
                    %(data_source)s, %(status)s, %(remark)s
                )
                on conflict (major_circuit_id) do update set
                    circuit_code = excluded.circuit_code,
                    en_name = excluded.en_name,
                    cn_name = excluded.cn_name,
                    alias = excluded.alias,
                    description = excluded.description,
                    circuit_kind = excluded.circuit_kind,
                    loop_type = excluded.loop_type,
                    cycle_verified = excluded.cycle_verified,
                    confidence_circuit = excluded.confidence_circuit,
                    validation_status_circuit = excluded.validation_status_circuit,
                    node_count = excluded.node_count,
                    connection_count = excluded.connection_count,
                    data_source = excluded.data_source,
                    status = excluded.status,
                    remark = excluded.remark
                """,
                record,
            )
            upserted_circuits += 1

            nodes = [str(n) for n in record.get("node_ids", []) if n]
            cur.execute("delete from major_circuit_node where major_circuit_id = %s", (record["major_circuit_id"],))
            for idx, node in enumerate(nodes, start=1):
                cur.execute(
                    """
                    insert into major_circuit_node (major_circuit_id, major_region_id, node_order, role_label)
                    values (%s, %s, %s, %s)
                    on conflict (major_circuit_id, major_region_id) do update set
                        node_order = excluded.node_order,
                        role_label = excluded.role_label
                    """,
                    (record["major_circuit_id"], node, idx, "node"),
                )
                upserted_nodes += 1

            connection_ids = [str(cid) for cid in record.get("connection_ids", []) if cid]
            if not connection_ids:
                nodes = [str(n) for n in record.get("node_ids", []) if n]
                derived_ids: list[str] = []
                for idx in range(len(nodes) - 1):
                    cur.execute(
                        """
                        select major_connection_id
                        from major_connection
                        where source_major_region_id = %s
                          and target_major_region_id = %s
                        order by major_connection_id
                        limit 1
                        """,
                        (nodes[idx], nodes[idx + 1]),
                    )
                    row = cur.fetchone()
                    if row:
                        derived_ids.append(str(row[0]))
                connection_ids = derived_ids
            cur.execute(
                "delete from major_circuit_connection where major_circuit_id = %s",
                (record["major_circuit_id"],),
            )
            for idx, conn_id in enumerate(connection_ids, start=1):
                cur.execute(
                    """
                    insert into major_circuit_connection (major_circuit_id, major_connection_id, edge_order)
                    values (%s, %s, %s)
                    on conflict (major_circuit_id, major_connection_id) do update set
                        edge_order = excluded.edge_order
                    """,
                    (record["major_circuit_id"], conn_id, idx),
                )
                upserted_edges += 1

    output = Path(output_path)
    report = {
        "stage": "load_major_circuits",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "upserted_circuits": upserted_circuits,
        "upserted_nodes": upserted_nodes,
        "upserted_edges": upserted_edges,
        "status": "success",
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Load validated major circuits into PostgreSQL.")
    args = parser.parse_args()
    report = run_load_circuits(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"load_major_circuits done: {report['upserted_circuits']}")


if __name__ == "__main__":
    main()
