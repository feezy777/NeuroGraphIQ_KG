from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.utils.io_utils import read_json, read_jsonl


def _slice_rows(path: Path, limit: int = 0) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    if limit and limit > 0:
        return rows[:limit]
    return rows


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = read_json(path)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {"value": data}


def load_preview_bundle(preview_root: str | Path, limit: int = 0) -> dict[str, Any]:
    root = Path(preview_root)
    summary = read_json(root / "major_preview_summary.json")
    files = summary.get("files", {})
    reports_dir = Path(summary.get("paths", {}).get("reports", root / "exports" / "reports"))
    staging_dir = Path(summary.get("paths", {}).get("staging", root / "staging"))

    regions_path = Path(files.get("major_regions_validated", root / "validated" / "major_regions.validated.jsonl"))
    circuits_path = Path(files.get("major_circuits_validated", root / "validated" / "major_circuits.validated.jsonl"))
    connections_path = Path(files.get("major_connections_validated", root / "validated" / "major_connections.validated.jsonl"))
    cross_pass_path = Path(
        files.get("major_connections_cross_pass", staging_dir / "major_connections.crosschecked.cross_pass.jsonl")
    )
    cross_fail_derived_path = Path(
        files.get(
            "major_connections_cross_fail_derived",
            staging_dir / "major_connections.crosschecked.cross_fail_only_derived.jsonl",
        )
    )
    cross_fail_direct_path = Path(
        files.get(
            "major_connections_cross_fail_direct",
            staging_dir / "major_connections.crosschecked.cross_fail_only_direct.jsonl",
        )
    )
    cross_fail_both_low_support_path = Path(
        files.get(
            "major_connections_cross_fail_both_low_support",
            staging_dir / "major_connections.crosschecked.cross_fail_both_low_support.jsonl",
        )
    )
    rejected_regions_path = Path(files.get("major_regions_rejected", root / "rejected" / "major_regions.rejected.jsonl"))
    rejected_circuits_path = Path(
        files.get("major_circuits_rejected", root / "rejected" / "major_circuits.rejected.jsonl")
    )
    rejected_connections_path = Path(
        files.get("major_connections_rejected", root / "rejected" / "major_connections.rejected.jsonl")
    )

    return {
        "summary": summary,
        "preview": {
            "major_regions": _slice_rows(regions_path, limit),
            "major_circuits": _slice_rows(circuits_path, limit),
            "major_connections": _slice_rows(connections_path, limit),
            "cross_pass_connections": _slice_rows(cross_pass_path, limit),
            "cross_fail_only_derived": _slice_rows(cross_fail_derived_path, limit),
            "cross_fail_only_direct": _slice_rows(cross_fail_direct_path, limit),
            "cross_fail_both_low_support": _slice_rows(cross_fail_both_low_support_path, limit),
            "rejected_regions": _slice_rows(rejected_regions_path, limit),
            "rejected_circuits": _slice_rows(rejected_circuits_path, limit),
            "rejected_connections": _slice_rows(rejected_connections_path, limit),
        },
        "reports": {
            "crosscheck": _safe_json(reports_dir / "major_crosscheck_report.json"),
            "validation": _safe_json(reports_dir / "major_validation_report.json"),
            "coverage": _safe_json(reports_dir / "major_region_coverage_report.json"),
            "mismatch": _safe_json(reports_dir / "major_mismatch_report.json"),
            "traversal": _safe_json(reports_dir / "major_seed_traversal_report.json"),
            "uncovered": _safe_json(reports_dir / "major_uncovered_regions.json"),
            "ontology_gate": _safe_json(reports_dir / "ontology_gate_report.json"),
        },
    }
