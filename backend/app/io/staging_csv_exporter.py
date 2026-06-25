"""Export ParseResult to human-readable staging CSVs and import_run_manifest.json."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.parsers.aal3_parser import PARSER_VERSION
from app.parsers.base_parser import ParseResult
from app.utils.hash_utils import sha256_file


def _json_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _json_cell(row.get(k)) for k in fieldnames})


def _hemisphere_stats(regions: list[dict]) -> dict[str, int]:
    stats = {"L": 0, "R": 0, "bilateral": 0, "unknown": 0}
    for r in regions:
        h = (r.get("hemisphere") or "unknown").lower()
        if h in ("l",):
            stats["L"] += 1
        elif h in ("r",):
            stats["R"] += 1
        elif h in ("bilateral", "bi"):
            stats["bilateral"] += 1
        else:
            stats["unknown"] += 1
    return stats


def _spatial_filled_count(regions: list[dict]) -> int:
    n = 0
    for r in regions:
        if r.get("coordinates_mni"):
            n += 1
    return n


def build_manifest(
    *,
    run_id: str,
    result: ParseResult,
    nii_path: str | None,
    xml_path: str | None,
    out_dir: Path,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    summary = result.summary()
    errors = sum(1 for q in result.quality_report if q.get("severity") == "error")
    warnings = sum(1 for q in result.quality_report if q.get("severity") == "warning")
    resource = result.resource_info or {}

    input_files: dict[str, Any] = {}
    if nii_path:
        p = Path(nii_path)
        if p.is_file():
            input_files["nii"] = {"path": str(p.resolve()), "sha256": sha256_file(p)}
    if xml_path:
        p = Path(xml_path)
        if p.is_file():
            input_files["xml"] = {"path": str(p.resolve()), "sha256": sha256_file(p)}

    return {
        "run_id": run_id,
        "resource_type": resource.get("resource_type", "aal3"),
        "granularity": resource.get("granularity", "macro"),
        "parser_name": "aal3_parser",
        "parser_version": resource.get("parser_version", PARSER_VERSION),
        "resource_version": resource.get("version"),
        "out_dir": str(out_dir.resolve()),
        "input_files": input_files,
        "counts": {
            "regions": summary.get("regions", 0),
            "terms": summary.get("terms", 0),
            "mappings": summary.get("mappings", 0),
            "connections": summary.get("connections", 0),
            "quality_issues": summary.get("quality_issues", 0),
        },
        "by_hemisphere": _hemisphere_stats(result.region_records),
        "spatial_filled": _spatial_filled_count(result.region_records),
        "quality": {"errors": errors, "warnings": warnings},
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
    }


def export_staging_csvs(
    result: ParseResult,
    out_dir: str | Path,
    *,
    run_id: str,
    nii_path: str | None = None,
    xml_path: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    """Write regions/terms/mappings/quality/import_log CSVs and manifest; return manifest dict."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    region_fields = [
        "label_index",
        "original_name",
        "abbr",
        "full_name",
        "hemisphere",
        "granularity",
        "coordinates_mni",
        "bounding_box",
        "source_id",
        "parent_region",
        "ontology_id",
        "extra_attrs",
    ]
    term_fields = [
        "term",
        "definition",
        "synonyms",
        "ontology_id",
        "ontology_source",
        "parent_term",
        "source_url",
        "extra_attrs",
    ]
    mapping_fields = [
        "source_name",
        "source_atlas",
        "target_name",
        "target_atlas",
        "mapping_type",
        "confidence",
        "evidence",
        "extra_attrs",
    ]
    quality_fields = [
        "check_type",
        "severity",
        "message",
        "affected_id",
        "affected_field",
        "auto_fixable",
    ]
    log_fields = ["step", "level", "message"]

    _write_csv(out / "regions.csv", region_fields, result.region_records)
    _write_csv(out / "terms.csv", term_fields, result.term_records)
    _write_csv(out / "mappings.csv", mapping_fields, result.mapping_candidates)
    _write_csv(out / "quality_report.csv", quality_fields, result.quality_report)
    _write_csv(out / "import_log.csv", log_fields, result.import_log)

    t0 = started_at or datetime.now(timezone.utc)
    t1 = finished_at or datetime.now(timezone.utc)
    manifest = build_manifest(
        run_id=run_id,
        result=result,
        nii_path=nii_path,
        xml_path=xml_path,
        out_dir=out,
        started_at=t0,
        finished_at=t1,
    )
    with open(out / "import_run_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    return manifest
