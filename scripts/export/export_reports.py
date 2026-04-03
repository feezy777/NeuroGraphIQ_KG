from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.io_utils import ensure_dir, read_json, write_csv_rows, write_json
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def _collect_report_files(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*.json") if p.name.endswith(".report.json") or "validation_report" in p.name)


def run_export_reports(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    _ = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    input_dir = Path(input_path)
    report_files = _collect_report_files(input_dir)

    summary_rows: list[dict[str, Any]] = []
    for report_file in report_files:
        report = read_json(report_file)
        summary_rows.append(
            {
                "stage": report.get("stage", report_file.name),
                "input_records": report.get("input_records"),
                "validated_records": report.get("validated_records"),
                "rejected_records": report.get("rejected_records"),
                "upserted_records": report.get("upserted_records"),
                "upserted_connections": report.get("upserted_connections"),
                "triple_count": report.get("triple_count"),
                "status": report.get("status", "n/a"),
                "path": str(report_file),
            }
        )

    output_dir = ensure_dir(output_path)
    csv_path = output_dir / "major_pipeline_summary.csv"
    json_path = output_dir / "major_pipeline_summary.json"
    write_csv_rows(csv_path, summary_rows)
    write_json(json_path, summary_rows)

    report = {
        "stage": "export_reports",
        "run_id": resolved_run_id,
        "report_files": len(report_files),
        "summary_csv_path": str(csv_path),
        "summary_json_path": str(json_path),
        "status": "success",
    }
    write_json(output_dir / "export_reports.report.json", report)
    return report


def main() -> None:
    parser = build_common_parser("Export pipeline summary reports.")
    args = parser.parse_args()
    report = run_export_reports(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"export_reports done: {report['report_files']} report files summarized")


if __name__ == "__main__":
    main()
