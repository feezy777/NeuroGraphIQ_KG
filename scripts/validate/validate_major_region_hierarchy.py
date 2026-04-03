from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.io_utils import read_records, write_json, write_jsonl
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def validate_major_region_record(record: dict[str, Any], seen_ids: set[str], seen_codes: set[str]) -> list[str]:
    errors: list[str] = []
    region_id = str(record.get("major_region_id") or "").strip()
    region_code = str(record.get("region_code") or "").strip()
    if not region_id:
        errors.append("missing_major_region_id")
    elif not region_id.startswith("REG_MAJOR_"):
        errors.append("invalid_major_region_id_prefix")
    elif region_id in seen_ids:
        errors.append("duplicate_major_region_id")
    else:
        seen_ids.add(region_id)

    if not region_code:
        errors.append("missing_region_code")
    elif region_code in seen_codes:
        errors.append("duplicate_region_code")
    else:
        seen_codes.add(region_code)

    if not record.get("en_name"):
        errors.append("missing_en_name")
    laterality = str(record.get("laterality") or "")
    if laterality not in {"left", "right", "midline", "bilateral"}:
        errors.append("invalid_laterality")
    return errors


def run_validate_major_regions(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)

    seen_ids: set[str] = set()
    seen_codes: set[str] = set()
    validated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for record in records:
        errors = validate_major_region_record(record, seen_ids, seen_codes)
        if errors:
            item = dict(record)
            item["errors"] = errors
            rejected.append(item)
        else:
            validated.append(record)

    output_dir = Path(output_path)
    validated_dir = output_dir / "validated"
    rejected_dir = output_dir / "rejected"
    validated_path = validated_dir / "major_regions.validated.jsonl"
    rejected_path = rejected_dir / "major_regions.rejected.jsonl"
    write_jsonl(validated_path, validated)
    write_jsonl(rejected_path, rejected)

    report = {
        "stage": "validate_major_regions",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "validated_records": len(validated),
        "rejected_records": len(rejected),
        "validated_path": str(validated_path),
        "rejected_path": str(rejected_path),
        "first_error_sample": rejected[0] if rejected else None,
    }
    write_json(output_dir / "major_regions.validation_report.json", report)
    return report


def main() -> None:
    parser = build_common_parser("Validate major region records.")
    args = parser.parse_args()
    report = run_validate_major_regions(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(
        "validate_major_regions done: "
        f"{report['validated_records']} validated, {report['rejected_records']} rejected"
    )


if __name__ == "__main__":
    main()
