from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.transform.major_normalization import normalize_major_connection_record
from scripts.utils.io_utils import read_records, write_json, write_jsonl
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def _unwrap_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    if isinstance(payload, dict):
        return payload
    return record


def run_normalize_major_connections(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    records = read_records(input_path)
    normalized: list[dict[str, Any]] = []
    for record in records:
        normalized_record = normalize_major_connection_record(_unwrap_payload(record))
        normalized_record["run_id"] = resolved_run_id
        normalized.append(normalized_record)

    output = Path(output_path)
    count = write_jsonl(output, normalized)
    report = {
        "stage": "normalize_major_connections",
        "run_id": resolved_run_id,
        "input_records": len(records),
        "output_records": count,
        "output_path": str(output),
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Normalize major connection records.")
    args = parser.parse_args()
    report = run_normalize_major_connections(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"normalize_major_connections done: {report['output_records']}")


if __name__ == "__main__":
    main()
