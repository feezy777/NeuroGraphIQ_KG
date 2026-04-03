from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.load.load_major_connections_to_pg import map_evidence_to_db
from scripts.utils.db import cursor
from scripts.utils.io_utils import read_records, write_json
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def run_load_evidences(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)
    evidences: list[dict[str, Any]] = []
    for record in records:
        record_evidence = record.get("evidence") if isinstance(record.get("evidence"), list) else []
        evidences.extend(item for item in record_evidence if isinstance(item, dict))

    with cursor() as (_, cur):
        for evidence in evidences:
            payload = map_evidence_to_db(evidence)
            cur.execute(
                """
                insert into evidence (
                    evidence_id, evidence_code, en_name, cn_name, alias, description, evidence_text,
                    source_title, pmid, doi, section, publication_year, journal,
                    evidence_type, data_source, status, remark
                )
                values (
                    %(evidence_id)s, %(evidence_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s, %(evidence_text)s,
                    %(source_title)s, %(pmid)s, %(doi)s, %(section)s, %(publication_year)s, %(journal)s,
                    %(evidence_type)s, %(data_source)s, %(status)s, %(remark)s
                )
                on conflict (evidence_id) do update set
                    evidence_code = excluded.evidence_code,
                    en_name = excluded.en_name,
                    cn_name = excluded.cn_name,
                    alias = excluded.alias,
                    description = excluded.description,
                    evidence_text = excluded.evidence_text,
                    source_title = excluded.source_title,
                    pmid = excluded.pmid,
                    doi = excluded.doi,
                    section = excluded.section,
                    publication_year = excluded.publication_year,
                    journal = excluded.journal,
                    evidence_type = excluded.evidence_type,
                    data_source = excluded.data_source,
                    status = excluded.status,
                    remark = excluded.remark
                """,
                payload,
            )

    output = Path(output_path)
    report = {
        "stage": "load_evidences",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "upserted_evidence_rows": len(evidences),
        "status": "success",
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Load evidence rows from validated connections.")
    args = parser.parse_args()
    report = run_load_evidences(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"load_evidences done: {report['upserted_evidence_rows']}")


if __name__ == "__main__":
    main()
