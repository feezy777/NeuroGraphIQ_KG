from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.db import cursor
from scripts.utils.io_utils import ensure_dir, write_csv_rows, write_json
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def run_export_major_triples(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = input_path
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)

    triples: list[dict[str, Any]] = []
    with cursor() as (_, cur):
        cur.execute("select region_code, en_name from major_brain_region where region_code is not null")
        for region_code, en_name in cur.fetchall():
            subject = f"neurokg:{region_code}"
            triples.append({"subject": subject, "predicate": "rdf:type", "object": "neurokg:MajorBrainRegion"})
            if en_name:
                triples.append({"subject": subject, "predicate": "rdfs:label", "object": en_name})

        cur.execute(
            """
            select
                mc.connection_code,
                src.region_code as source_code,
                tgt.region_code as target_code,
                mc.connection_modality
            from major_connection mc
            join major_brain_region src on src.major_region_id = mc.source_major_region_id
            join major_brain_region tgt on tgt.major_region_id = mc.target_major_region_id
            """
        )
        for connection_code, source_code, target_code, modality in cur.fetchall():
            source = f"neurokg:{source_code}"
            target = f"neurokg:{target_code}"
            connection = f"neurokg:{connection_code}"
            triples.append({"subject": source, "predicate": "neurokg:connectedTo", "object": target})
            triples.append({"subject": connection, "predicate": "rdf:type", "object": "neurokg:MajorConnection"})
            triples.append({"subject": connection, "predicate": "neurokg:sourceRegion", "object": source})
            triples.append({"subject": connection, "predicate": "neurokg:targetRegion", "object": target})
            triples.append({"subject": connection, "predicate": "neurokg:connectionModality", "object": modality})

    output_dir = ensure_dir(output_path)
    csv_path = output_dir / "major_triples.csv"
    json_path = output_dir / "major_triples.json"
    write_csv_rows(csv_path, triples)
    write_json(json_path, triples)

    report = {
        "stage": "export_major_triples",
        "run_id": resolved_run_id,
        "triple_count": len(triples),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "status": "success",
    }
    write_json(output_dir / "major_triples.report.json", report)
    return report


def main() -> None:
    parser = build_common_parser("Export major triples from PostgreSQL.")
    args = parser.parse_args()
    report = run_export_major_triples(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"export_major_triples done: {report['triple_count']}")


if __name__ == "__main__":
    main()
