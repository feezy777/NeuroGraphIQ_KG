from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.constants import DIV_NON_LOBE_DIVISION_BRAIN_ID, ORG_HUMAN_ID
from scripts.utils.db import cursor
from scripts.utils.io_utils import read_records, write_json
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def map_major_region_to_db(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "major_region_id": record.get("major_region_id"),
        "organism_id": record.get("organism_id") or ORG_HUMAN_ID,
        "division_id": record.get("division_id") or DIV_NON_LOBE_DIVISION_BRAIN_ID,
        "region_code": record.get("region_code"),
        "en_name": record.get("en_name"),
        "cn_name": record.get("cn_name"),
        "alias": record.get("alias") or [],
        "description": record.get("description"),
        "laterality": record.get("laterality"),
        "region_category": record.get("region_category"),
        "ontology_source": record.get("ontology_source"),
        "data_source": record.get("data_source"),
        "status": record.get("status"),
        "remark": record.get("remark"),
    }


def run_load_major_regions(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)
    upserted = 0

    with cursor() as (_, cur):
        for record in records:
            payload = map_major_region_to_db(record)
            cur.execute(
                """
                insert into major_brain_region (
                    major_region_id, organism_id, division_id, region_code, en_name, cn_name, alias, description,
                    laterality, region_category, ontology_source, data_source, status, remark
                )
                values (
                    %(major_region_id)s, %(organism_id)s, %(division_id)s, %(region_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s,
                    %(laterality)s, %(region_category)s, %(ontology_source)s, %(data_source)s, %(status)s, %(remark)s
                )
                on conflict (major_region_id) do update set
                    organism_id = excluded.organism_id,
                    division_id = excluded.division_id,
                    region_code = excluded.region_code,
                    en_name = excluded.en_name,
                    cn_name = excluded.cn_name,
                    alias = excluded.alias,
                    description = excluded.description,
                    laterality = excluded.laterality,
                    region_category = excluded.region_category,
                    ontology_source = excluded.ontology_source,
                    data_source = excluded.data_source,
                    status = excluded.status,
                    remark = excluded.remark
                """,
                payload,
            )
            upserted += 1

    output = Path(output_path)
    report = {
        "stage": "load_major_regions",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "upserted_records": upserted,
        "status": "success",
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Load validated major regions to PostgreSQL.")
    args = parser.parse_args()
    report = run_load_major_regions(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"load_major_regions done: {report['upserted_records']}")


if __name__ == "__main__":
    main()
