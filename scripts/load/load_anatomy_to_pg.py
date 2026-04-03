from __future__ import annotations

from pathlib import Path

from scripts.utils.db import cursor
from scripts.utils.io_utils import read_records, write_json
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def run_load_anatomy(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict:
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)
    counts = {"organism": 0, "anatomical_system": 0, "organ": 0, "brain_division": 0}

    with cursor() as (_, cur):
        for item in records:
            entity = item.get("entity_type")
            if entity == "organism":
                cur.execute(
                    """
                    insert into organism (
                        organism_id, organism_code, en_name, cn_name, alias, description, species, data_source, status, remark
                    )
                    values (
                        %(organism_id)s, %(organism_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s,
                        %(species)s, %(data_source)s, %(status)s, %(remark)s
                    )
                    on conflict (organism_id) do update set
                        organism_code = excluded.organism_code,
                        en_name = excluded.en_name,
                        cn_name = excluded.cn_name,
                        alias = excluded.alias,
                        description = excluded.description,
                        species = excluded.species,
                        data_source = excluded.data_source,
                        status = excluded.status,
                        remark = excluded.remark
                    """,
                    item,
                )
                counts["organism"] += 1
            elif entity == "anatomical_system":
                cur.execute(
                    """
                    insert into anatomical_system (
                        system_id, organism_id, system_code, en_name, cn_name, alias, description, data_source, status, remark
                    )
                    values (
                        %(system_id)s, %(organism_id)s, %(system_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s,
                        %(data_source)s, %(status)s, %(remark)s
                    )
                    on conflict (system_id) do update set
                        organism_id = excluded.organism_id,
                        system_code = excluded.system_code,
                        en_name = excluded.en_name,
                        cn_name = excluded.cn_name,
                        alias = excluded.alias,
                        description = excluded.description,
                        data_source = excluded.data_source,
                        status = excluded.status,
                        remark = excluded.remark
                    """,
                    item,
                )
                counts["anatomical_system"] += 1
            elif entity == "organ":
                cur.execute(
                    """
                    insert into organ (
                        organ_id, system_id, organ_code, en_name, cn_name, alias, description, data_source, status, remark
                    )
                    values (
                        %(organ_id)s, %(system_id)s, %(organ_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s,
                        %(data_source)s, %(status)s, %(remark)s
                    )
                    on conflict (organ_id) do update set
                        system_id = excluded.system_id,
                        organ_code = excluded.organ_code,
                        en_name = excluded.en_name,
                        cn_name = excluded.cn_name,
                        alias = excluded.alias,
                        description = excluded.description,
                        data_source = excluded.data_source,
                        status = excluded.status,
                        remark = excluded.remark
                    """,
                    item,
                )
                counts["organ"] += 1
            elif entity == "brain_division":
                cur.execute(
                    """
                    insert into brain_division (
                        division_id, organ_id, division_code, en_name, cn_name, alias, description,
                        division_type, data_source, status, remark
                    )
                    values (
                        %(division_id)s, %(organ_id)s, %(division_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s,
                        %(division_type)s, %(data_source)s, %(status)s, %(remark)s
                    )
                    on conflict (division_id) do update set
                        organ_id = excluded.organ_id,
                        division_code = excluded.division_code,
                        en_name = excluded.en_name,
                        cn_name = excluded.cn_name,
                        alias = excluded.alias,
                        description = excluded.description,
                        division_type = excluded.division_type,
                        data_source = excluded.data_source,
                        status = excluded.status,
                        remark = excluded.remark
                    """,
                    item,
                )
                counts["brain_division"] += 1

    output = Path(output_path)
    report = {
        "stage": "load_anatomy",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "counts": counts,
        "status": "success",
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Load anatomy entities into PostgreSQL.")
    args = parser.parse_args()
    report = run_load_anatomy(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"load_anatomy done: {report['counts']}")


if __name__ == "__main__":
    main()
