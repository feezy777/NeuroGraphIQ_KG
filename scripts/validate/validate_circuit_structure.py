from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.io_utils import read_jsonl, read_records, write_json, write_jsonl
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def validate_circuit_record(record: dict[str, Any], seen_ids: set[str], valid_region_ids: set[str]) -> list[str]:
    errors: list[str] = []
    circuit_id = str(record.get("major_circuit_id") or "").strip()
    nodes = [str(n) for n in record.get("node_ids", []) if n]
    if not circuit_id:
        errors.append("missing_major_circuit_id")
    elif not circuit_id.startswith("CIR_MAJOR_"):
        errors.append("invalid_major_circuit_id_prefix")
    elif circuit_id in seen_ids:
        errors.append("duplicate_major_circuit_id")
    else:
        seen_ids.add(circuit_id)

    if len(nodes) < 2:
        errors.append("insufficient_nodes")
    for node in nodes:
        if node not in valid_region_ids:
            errors.append(f"unknown_node_{node}")
    if str(record.get("circuit_kind") or "") not in {"structural", "functional", "inferred", "unknown"}:
        errors.append("invalid_circuit_kind")
    return errors


def run_validate_circuit_structure(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
    valid_region_ids: set[str] | None = None,
) -> dict[str, Any]:
    config = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)

    region_path = (
        config.get("validation", {}).get("major_region_reference_path")
        or config.get("major_region_reference_path")
        or ""
    )
    if valid_region_ids is None:
        valid_region_ids = set()
    if region_path and not valid_region_ids:
        valid_region_ids = {
            str(item.get("major_region_id") or "").strip()
            for item in read_jsonl(region_path)
            if str(item.get("major_region_id") or "").strip()
        }

    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for record in records:
        errors = validate_circuit_record(record, seen_ids, valid_region_ids)
        if errors:
            item = dict(record)
            item["errors"] = errors
            rejected.append(item)
        else:
            validated.append(record)

    output_dir = Path(output_path)
    validated_dir = output_dir / "validated"
    rejected_dir = output_dir / "rejected"
    validated_path = validated_dir / "major_circuits.validated.jsonl"
    rejected_path = rejected_dir / "major_circuits.rejected.jsonl"
    write_jsonl(validated_path, validated)
    write_jsonl(rejected_path, rejected)

    report = {
        "stage": "validate_major_circuits",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "validated_records": len(validated),
        "rejected_records": len(rejected),
        "validated_path": str(validated_path),
        "rejected_path": str(rejected_path),
        "first_error_sample": rejected[0] if rejected else None,
    }
    write_json(output_dir / "major_circuits.validation_report.json", report)
    return report


def main() -> None:
    parser = build_common_parser("Validate major circuit structure.")
    args = parser.parse_args()
    report = run_validate_circuit_structure(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(
        "validate_major_circuits done: "
        f"{report['validated_records']} validated, {report['rejected_records']} rejected"
    )


if __name__ == "__main__":
    main()
