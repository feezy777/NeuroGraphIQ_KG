from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.db import cursor
from scripts.utils.id_utils import evidence_id
from scripts.utils.io_utils import read_records, write_json
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def map_major_connection_to_db(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "major_connection_id": record.get("major_connection_id"),
        "connection_code": record.get("connection_code"),
        "en_name": record.get("en_name"),
        "cn_name": record.get("cn_name"),
        "alias": record.get("alias") or [],
        "description": record.get("description"),
        "connection_modality": record.get("connection_modality") or "unknown",
        "relation_type": record.get("relation_type") or "indirect_pathway_connection",
        "source_major_region_id": record.get("source_major_region_id"),
        "target_major_region_id": record.get("target_major_region_id"),
        "confidence": record.get("confidence"),
        "validation_status": record.get("validation_status"),
        "direction_label": record.get("direction_label"),
        "extraction_method": record.get("extraction_method"),
        "data_source": record.get("data_source"),
        "status": record.get("status"),
        "remark": record.get("remark"),
    }


def map_evidence_to_db(record: dict[str, Any]) -> dict[str, Any]:
    evidence_text = str(record.get("evidence_text") or "")
    ev_id = str(record.get("evidence_id") or "").strip() or evidence_id(evidence_text or str(record))
    return {
        "evidence_id": ev_id,
        "evidence_code": record.get("evidence_code") or ev_id,
        "en_name": record.get("en_name") or ev_id,
        "cn_name": record.get("cn_name"),
        "alias": record.get("alias") or [],
        "description": record.get("description"),
        "evidence_text": evidence_text,
        "source_title": record.get("source_title"),
        "pmid": record.get("pmid"),
        "doi": record.get("doi"),
        "section": record.get("section"),
        "publication_year": record.get("publication_year"),
        "journal": record.get("journal"),
        "evidence_type": record.get("evidence_type") or "manual_note",
        "data_source": record.get("data_source") or "deepseek",
        "status": record.get("status") or "active",
        "remark": record.get("remark"),
    }


def _major_region_exists(cur: Any, region_ids: set[str]) -> set[str]:
    if not region_ids:
        return set()
    cur.execute(
        """
        select major_region_id
        from major_brain_region
        where major_region_id = any(%s)
        """,
        (list(region_ids),),
    )
    return {item[0] for item in cur.fetchall()}


def _upsert_connection(cur: Any, payload: dict[str, Any]) -> str:
    cur.execute(
        """
        insert into major_connection (
            major_connection_id, connection_code, en_name, cn_name, alias, description, connection_modality,
            relation_type,
            source_major_region_id, target_major_region_id, confidence, validation_status, direction_label,
            extraction_method, data_source, status, remark
        )
        values (
            %(major_connection_id)s, %(connection_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s, %(connection_modality)s,
            %(relation_type)s,
            %(source_major_region_id)s, %(target_major_region_id)s, %(confidence)s, %(validation_status)s, %(direction_label)s,
            %(extraction_method)s, %(data_source)s, %(status)s, %(remark)s
        )
        on conflict (major_connection_id) do update set
            connection_code = excluded.connection_code,
            en_name = excluded.en_name,
            cn_name = excluded.cn_name,
            alias = excluded.alias,
            description = excluded.description,
            connection_modality = excluded.connection_modality,
            relation_type = excluded.relation_type,
            source_major_region_id = excluded.source_major_region_id,
            target_major_region_id = excluded.target_major_region_id,
            confidence = excluded.confidence,
            validation_status = excluded.validation_status,
            direction_label = excluded.direction_label,
            extraction_method = excluded.extraction_method,
            data_source = excluded.data_source,
            status = excluded.status,
            remark = excluded.remark
        returning major_connection_id
        """,
        payload,
    )
    return str(cur.fetchone()[0])


def _upsert_evidence(cur: Any, payload: dict[str, Any]) -> str:
    cur.execute(
        """
        insert into evidence (
            evidence_id, evidence_code, en_name, cn_name, alias, description, evidence_text,
            source_title, pmid, doi, section, publication_year, journal, evidence_type, data_source, status, remark
        )
        values (
            %(evidence_id)s, %(evidence_code)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s, %(evidence_text)s,
            %(source_title)s, %(pmid)s, %(doi)s, %(section)s, %(publication_year)s, %(journal)s, %(evidence_type)s, %(data_source)s, %(status)s, %(remark)s
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
        returning evidence_id
        """,
        payload,
    )
    return str(cur.fetchone()[0])


def run_load_major_connections(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)

    region_ids = {
        str(region_id)
        for item in records
        for region_id in (item.get("source_major_region_id"), item.get("target_major_region_id"))
        if region_id
    }
    upserted_connections = 0
    upserted_evidence = 0
    linked_evidence = 0
    rejected_records = 0

    with cursor() as (_, cur):
        existing_regions = _major_region_exists(cur, region_ids)
        for record in records:
            source = str(record.get("source_major_region_id") or "")
            target = str(record.get("target_major_region_id") or "")
            if source not in existing_regions or target not in existing_regions:
                rejected_records += 1
                continue
            payload = map_major_connection_to_db(record)
            connection_id_value = _upsert_connection(cur, payload)
            upserted_connections += 1

            evidences = record.get("evidence") if isinstance(record.get("evidence"), list) else []
            for evidence in evidences:
                evidence_payload = map_evidence_to_db(evidence)
                evidence_id_value = _upsert_evidence(cur, evidence_payload)
                upserted_evidence += 1
                cur.execute(
                    """
                    insert into major_connection_evidence (
                        major_connection_id, evidence_id, support_score, support_note
                    )
                    values (%s, %s, %s, %s)
                    on conflict (major_connection_id, evidence_id) do update set
                        support_score = excluded.support_score,
                        support_note = excluded.support_note
                    """,
                    (
                        connection_id_value,
                        evidence_id_value,
                        evidence.get("support_score"),
                        evidence.get("support_note"),
                    ),
                )
                linked_evidence += 1

    output = Path(output_path)
    report = {
        "stage": "load_major_connections",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "upserted_connections": upserted_connections,
        "upserted_evidence_rows": upserted_evidence,
        "linked_evidence_rows": linked_evidence,
        "rejected_records": rejected_records,
        "status": "success",
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Load validated major connections and evidence to PostgreSQL.")
    args = parser.parse_args()
    report = run_load_major_connections(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"load_major_connections done: {report['upserted_connections']}")


if __name__ == "__main__":
    main()
