from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.io_utils import read_jsonl, read_records, write_json, write_jsonl
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def validate_major_connection_record(
    record: dict[str, Any],
    seen_ids: set[str],
    seen_keys: set[tuple[str, str, str, str]],
    valid_region_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    conn_id = str(record.get("major_connection_id") or "").strip()
    source = str(record.get("source_major_region_id") or "").strip()
    target = str(record.get("target_major_region_id") or "").strip()
    modality = str(record.get("connection_modality") or "").strip().lower()
    relation_type = str(record.get("relation_type") or "").strip()

    if not conn_id:
        errors.append("missing_major_connection_id")
    elif not conn_id.startswith("CONN_MAJOR_"):
        errors.append("invalid_major_connection_id_prefix")
    elif conn_id in seen_ids:
        errors.append("duplicate_major_connection_id")
    else:
        seen_ids.add(conn_id)

    if not source:
        errors.append("missing_source_major_region_id")
    if not target:
        errors.append("missing_target_major_region_id")
    if source and target and source == target:
        errors.append("self_loop_not_allowed")
    if source and source not in valid_region_ids:
        errors.append("unknown_source_major_region_id")
    if target and target not in valid_region_ids:
        errors.append("unknown_target_major_region_id")

    if modality not in {"structural", "functional", "effective", "unknown"}:
        errors.append("invalid_connection_modality")
    if relation_type not in {
        "direct_structural_connection",
        "indirect_pathway_connection",
        "same_circuit_member",
    }:
        errors.append("invalid_relation_type")

    key = (source, target, modality, relation_type)
    if key in seen_keys:
        errors.append("duplicate_connection_key")
    else:
        seen_keys.add(key)

    status = str(record.get("validation_status") or "")
    if status not in {"cross_pass_unverified", "cross_fail_unverified"}:
        errors.append("invalid_validation_status")

    confidence = record.get("confidence")
    if confidence is not None:
        try:
            numeric = float(confidence)
        except (TypeError, ValueError):
            errors.append("invalid_confidence")
        else:
            if not (0 <= numeric <= 1):
                errors.append("confidence_out_of_range")
    return errors


def run_validate_major_connections(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
    valid_region_ids: set[str] | None = None,
) -> dict[str, Any]:
    config = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)

    if valid_region_ids is None:
        region_path = (
            config.get("validation", {}).get("major_region_reference_path")
            or config.get("major_region_reference_path")
            or ""
        )
        if region_path:
            valid_region_ids = {
                str(item.get("major_region_id") or "").strip()
                for item in read_jsonl(region_path)
                if str(item.get("major_region_id") or "").strip()
            }
        else:
            valid_region_ids = set()

    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str, str]] = set()
    validated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for record in records:
        errors = validate_major_connection_record(record, seen_ids, seen_keys, valid_region_ids)
        if errors:
            item = dict(record)
            item["errors"] = errors
            rejected.append(item)
        else:
            validated.append(record)

    output_dir = Path(output_path)
    validated_dir = output_dir / "validated"
    rejected_dir = output_dir / "rejected"
    validated_path = validated_dir / "major_connections.validated.jsonl"
    rejected_path = rejected_dir / "major_connections.rejected.jsonl"
    write_jsonl(validated_path, validated)
    write_jsonl(rejected_path, rejected)

    report = {
        "stage": "validate_major_connections",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "validated_records": len(validated),
        "rejected_records": len(rejected),
        "validated_path": str(validated_path),
        "rejected_path": str(rejected_path),
        "first_error_sample": rejected[0] if rejected else None,
    }
    write_json(output_dir / "major_connections.validation_report.json", report)
    return report


def main() -> None:
    parser = build_common_parser("Validate major connections.")
    args = parser.parse_args()
    report = run_validate_major_connections(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(
        "validate_major_connections done: "
        f"{report['validated_records']} validated, {report['rejected_records']} rejected"
    )


if __name__ == "__main__":
    main()
