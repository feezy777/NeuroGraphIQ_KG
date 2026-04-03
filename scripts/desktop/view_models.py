from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.desktop.models import (
    FileListItemViewModel,
    GateDecision,
    MajorReportSummaryViewModel,
    PreprocessReportViewModel,
)

MAJOR_NAVIGATION = [
    ("major_regions", "Major Regions"),
    ("major_circuits", "Circuit Candidates"),
    ("cross_pass_connections", "Cross Pass Connections"),
    ("cross_fail_connections", "Cross Fail Connections"),
    ("rejected_records", "Rejected"),
    ("crosscheck_report", "Crosscheck Report"),
    ("coverage_report", "Coverage Report"),
    ("traversal_report", "Traversal Report"),
    ("mismatch_report", "Mismatch Report"),
]


def gate_message(gate: GateDecision) -> str:
    mapping = {
        "ontology_not_imported": "Import ontology first, then run preprocess / preview / extract.",
        "ontology_parse_failed": "Ontology parsing failed, workflow is blocked by gate.",
        "preprocess_blocked": "Current stage is blocked by gate.",
    }
    return mapping.get(gate.block_reason, gate.block_reason or "")


def build_file_list_view_model(listing: dict[str, Any], filter_key: str = "all") -> dict[str, Any]:
    rows = listing.get("files", [])
    items: list[dict[str, Any]] = []
    for row in rows:
        label = str(row.get("overall_label") or "")
        if not label:
            label = "UNPROCESSED"
        item = FileListItemViewModel(
            file_id=str(row.get("file_id") or ""),
            filename=str(row.get("filename") or ""),
            file_type=str(row.get("file_type") or ""),
            label=label,
            score=str(row.get("score") or "-"),
            blocked_on_load=bool(row.get("blocked_on_load", False)),
            status=str(row.get("status") or ""),
            last_processed_at=str(row.get("last_processed_at") or row.get("last_validation_at") or ""),
            linked_ontology_version=str(row.get("linked_ontology_version") or ""),
        ).to_dict()
        items.append(item)

    key = str(filter_key or "all").lower()
    if key == "pass":
        items = [x for x in items if x["label"] == "PASS"]
    elif key == "warn":
        items = [x for x in items if x["label"] == "WARN"]
    elif key == "fail":
        items = [x for x in items if x["label"] == "FAIL"]
    elif key == "blocked":
        items = [x for x in items if x["blocked_on_load"]]

    return {"items": items, "stats": listing.get("stats", {})}


def build_file_preview_view_model(
    *,
    file_record: dict[str, Any] | None,
    preview_payload: dict[str, Any] | None,
    report_bundle: dict[str, Any] | None,
    gate: GateDecision,
) -> dict[str, Any]:
    record = file_record or {}
    report_file = (report_bundle or {}).get("file", {}) if isinstance(report_bundle, dict) else {}
    report = (report_bundle or {}).get("report", {}) if isinstance(report_bundle, dict) else {}

    if not gate.allow_preview:
        return {
            "blocked": True,
            "block_reason": gate.block_reason,
            "message": gate_message(gate),
            "meta": {
                "filename": str(record.get("filename") or ""),
                "file_type": str(record.get("file_type") or ""),
            },
        }

    payload = preview_payload or {}
    file_type = str(record.get("file_type") or payload.get("file_type") or "")
    meta = {
        "filename": str(record.get("filename") or ""),
        "file_type": file_type,
        "size_bytes": record.get("size_bytes", ""),
        "linked_ontology_version": str(record.get("linked_ontology_version") or ""),
        "preprocess_label": str(report_file.get("overall_label") or record.get("overall_label") or "UNPROCESSED"),
        "score": report_file.get("score", record.get("score", "")),
        "blocked_on_load": bool(report_file.get("blocked_on_load", record.get("blocked_on_load", False))),
        "page": payload.get("page", 1),
        "total_pages": payload.get("total_pages", 1),
        "total_rows": payload.get("total_rows", ""),
        "total_lines": payload.get("total_lines", ""),
        "chars": payload.get("chars", ""),
        "summary_cn": str(report.get("summary_cn") or ""),
    }
    if file_type in {"rdf", "owl", "xml"}:
        meta["ontology_hint"] = "Ontology file supports text preview and ontology summary."

    return {
        "blocked": False,
        "meta": meta,
        "mode": str(payload.get("mode") or ""),
        "payload": payload,
    }


def build_preprocess_report_view_model(
    *,
    file_record: dict[str, Any] | None,
    report_bundle: dict[str, Any] | None,
    gate: GateDecision,
) -> dict[str, Any]:
    record = file_record or {}
    bundle = report_bundle or {}
    report = bundle.get("report", {}) if isinstance(bundle, dict) else {}
    file_payload = bundle.get("file", {}) if isinstance(bundle, dict) else {}

    if not gate.allow_preview:
        return PreprocessReportViewModel(
            blocked=True,
            block_reason=gate.block_reason,
            overview={
                "title": str(record.get("filename") or file_payload.get("filename") or ""),
                "message": gate_message(gate),
            },
            raw=bundle if isinstance(bundle, dict) else {},
        ).to_dict()

    paths = [
        {"label": "Original", "value": str(file_payload.get("original_path") or record.get("original_path") or "")},
        {"label": "Normalized", "value": str(file_payload.get("normalized_path") or "")},
        {"label": "Processed", "value": str(file_payload.get("processed_path") or "")},
        {"label": "Report", "value": str(file_payload.get("report_path") or "")},
    ]
    overview = {
        "filename": str(file_payload.get("filename") or record.get("filename") or ""),
        "label": str(report.get("overall_label") or file_payload.get("overall_label") or "UNPROCESSED"),
        "score": report.get("score", file_payload.get("score", "-")),
        "summary_cn": str(report.get("summary_cn") or file_payload.get("summary_cn") or ""),
        "issue_count": len(report.get("issues", []) or []),
        "auto_applied_count": int(report.get("auto_applied_count", file_payload.get("auto_applied_count", 0)) or 0),
        "manual_required_count": int(report.get("manual_required_count", file_payload.get("manual_required_count", 0)) or 0),
        "gate_decision": dict(report.get("gate_decision", {})),
        "blocked_on_load": bool(report.get("blocked_on_load", file_payload.get("blocked_on_load", False))),
    }
    issues = []
    for item in report.get("issues", []) or []:
        issues.append(
            {
                "severity": str(item.get("severity") or ""),
                "code": str(item.get("code") or ""),
                "message": str(item.get("message") or ""),
                "suggestion": str(item.get("suggestion") or ""),
            }
        )

    auto_fix_plan = []
    for item in report.get("auto_fix_plan", []) or []:
        auto_fix_plan.append(
            {
                "action": str(item.get("action") or ""),
                "reason": str(item.get("reason") or ""),
                "risk": str(item.get("risk") or ""),
            }
        )

    manual_fix_plan = []
    for item in report.get("manual_fix_plan", []) or []:
        manual_fix_plan.append(
            {
                "action": str(item.get("action") or ""),
                "reason": str(item.get("reason") or ""),
                "priority": str(item.get("priority") or ""),
            }
        )

    return PreprocessReportViewModel(
        blocked=False,
        block_reason="",
        overview=overview,
        issues=issues,
        auto_fix_plan=auto_fix_plan,
        manual_fix_plan=manual_fix_plan,
        change_log=[str(x) for x in report.get("normalized_change_log", []) or []],
        paths=paths,
        raw=bundle if isinstance(bundle, dict) else {},
    ).to_dict()


def _as_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def build_major_results_view_model(
    *,
    bundle: dict[str, Any] | None,
    gate: GateDecision,
    preview_root: str,
) -> dict[str, Any]:
    if not gate.allow_preview:
        return MajorReportSummaryViewModel(
            blocked=True,
            block_reason=gate.block_reason,
            available=False,
            run_info={"message": gate_message(gate)},
        ).to_dict()

    if not bundle:
        return MajorReportSummaryViewModel(
            blocked=False,
            block_reason="",
            available=False,
            run_info={"message": "No successful major preview result found."},
        ).to_dict()

    summary = bundle.get("summary", {})
    preview = bundle.get("preview", {})
    reports = bundle.get("reports", {})

    cross_fail_rows: list[dict[str, Any]] = []
    for bucket_name, rows in (
        ("only_derived", preview.get("cross_fail_only_derived", [])),
        ("only_direct", preview.get("cross_fail_only_direct", [])),
        ("low_support", preview.get("cross_fail_both_low_support", [])),
    ):
        for row in rows or []:
            current = dict(row)
            current["crosscheck_bucket"] = bucket_name
            cross_fail_rows.append(current)

    rejected_rows: list[dict[str, Any]] = []
    for record_type, rows in (
        ("major_region", preview.get("rejected_regions", [])),
        ("major_circuit", preview.get("rejected_circuits", [])),
        ("major_connection", preview.get("rejected_connections", [])),
    ):
        for row in rows or []:
            current = dict(row)
            current["record_type"] = record_type
            rejected_rows.append(current)

    coverage = reports.get("coverage", {})
    mismatch = reports.get("mismatch", {})
    crosscheck = reports.get("crosscheck", {})
    traversal_payload = reports.get("traversal", {})
    uncovered_payload = reports.get("uncovered", {})
    ontology_gate = reports.get("ontology_gate", {})

    traversal_rows = _as_rows(traversal_payload)
    seed_region_count = int(
        (summary.get("metrics", {}).get("seed_traversal_summary", {}).get("seed_region_count", 0))
        or len(traversal_rows)
    )
    attempted_region_count = int(
        (summary.get("metrics", {}).get("seed_traversal_summary", {}).get("attempted_region_count", 0))
        or len(traversal_rows)
    )
    matched_region_count = int(
        (summary.get("metrics", {}).get("seed_traversal_summary", {}).get("matched_region_count", 0))
        or len([row for row in traversal_rows if int(row.get("built_instances", 0) or 0) > 0])
    )

    region_count = int(coverage.get("region_count", len(preview.get("major_regions", []) or [])) or 0)
    uncovered_regions = [str(x) for x in uncovered_payload.get("uncovered_regions", []) if str(x)]
    if not uncovered_regions:
        uncovered_regions = [str(x) for x in coverage.get("uncovered_regions", []) or []]
    uncovered_region_count = int(
        uncovered_payload.get("uncovered_region_count", 0)
        or summary.get("metrics", {}).get("seed_traversal_summary", {}).get("uncovered_region_count", 0)
        or len(uncovered_regions)
    )
    covered_regions = max(0, region_count - len(uncovered_regions))
    coverage_rate = round((covered_regions / region_count) * 100, 2) if region_count else 0.0

    summary_cards = [
        {"title": "Major Regions", "value": len(preview.get("major_regions", []) or [])},
        {"title": "Circuits", "value": len(preview.get("major_circuits", []) or [])},
        {"title": "Cross Pass", "value": len(preview.get("cross_pass_connections", []) or [])},
        {"title": "Cross Fail", "value": len(cross_fail_rows)},
        {"title": "Rejected", "value": len(rejected_rows)},
        {"title": "Coverage", "value": f"{coverage_rate}%"},
        {"title": "Uncovered", "value": uncovered_region_count},
    ]

    navigation = [
        {"pane_id": "major_regions", "title": "Major Regions", "count": len(preview.get("major_regions", []) or [])},
        {"pane_id": "major_circuits", "title": "Circuit Candidates", "count": len(preview.get("major_circuits", []) or [])},
        {"pane_id": "cross_pass_connections", "title": "Cross Pass Connections", "count": len(preview.get("cross_pass_connections", []) or [])},
        {"pane_id": "cross_fail_connections", "title": "Cross Fail Connections", "count": len(cross_fail_rows)},
        {"pane_id": "rejected_records", "title": "Rejected", "count": len(rejected_rows)},
        {
            "pane_id": "crosscheck_report",
            "title": "Crosscheck Report",
            "count": sum(
                int(crosscheck.get(key, 0) or 0)
                for key in (
                    "cross_pass_records",
                    "cross_fail_only_derived_records",
                    "cross_fail_only_direct_records",
                    "cross_fail_both_low_support_records",
                )
            ),
        },
        {"pane_id": "coverage_report", "title": "Coverage Report", "count": len(uncovered_regions)},
        {"pane_id": "traversal_report", "title": "Traversal Report", "count": attempted_region_count},
        {
            "pane_id": "mismatch_report",
            "title": "Mismatch Report",
            "count": len(mismatch.get("out_of_catalog_region_ids", []) or []) + len(mismatch.get("uncovered_regions", []) or []),
        },
    ]

    panes = {
        "major_regions": {"kind": "table", "rows": preview.get("major_regions", []) or []},
        "major_circuits": {"kind": "table", "rows": preview.get("major_circuits", []) or []},
        "cross_pass_connections": {"kind": "table", "rows": preview.get("cross_pass_connections", []) or []},
        "cross_fail_connections": {"kind": "table", "rows": cross_fail_rows},
        "rejected_records": {"kind": "table", "rows": rejected_rows},
        "crosscheck_report": {
            "kind": "summary",
            "cards": [
                {"title": "Pass", "value": int(crosscheck.get("cross_pass_records", 0) or 0)},
                {"title": "Only Derived Fail", "value": int(crosscheck.get("cross_fail_only_derived_records", 0) or 0)},
                {"title": "Only Direct Fail", "value": int(crosscheck.get("cross_fail_only_direct_records", 0) or 0)},
                {"title": "Low Support Fail", "value": int(crosscheck.get("cross_fail_both_low_support_records", 0) or 0)},
            ],
            "summary": [
                {"label": "Derived records", "value": int(crosscheck.get("derived_records", 0) or 0)},
                {"label": "Direct records", "value": int(crosscheck.get("direct_records", 0) or 0)},
            ],
        },
        "coverage_report": {
            "kind": "summary",
            "cards": [
                {"title": "Coverage", "value": f"{coverage_rate}%"},
                {"title": "Covered Regions", "value": covered_regions},
                {"title": "Uncovered Regions", "value": len(uncovered_regions)},
                {"title": "Total Regions", "value": region_count},
            ],
            "summary": [
                {"label": "Top Uncovered", "value": ", ".join(uncovered_regions[:12]) if uncovered_regions else "-"},
            ],
            "tables": {
                "uncovered_regions": [{"major_region_id": value} for value in uncovered_regions[:300]],
            },
        },
        "traversal_report": {
            "kind": "summary",
            "cards": [
                {"title": "Seed Regions", "value": seed_region_count},
                {"title": "Attempted", "value": attempted_region_count},
                {"title": "Matched", "value": matched_region_count},
                {"title": "Uncovered", "value": uncovered_region_count},
            ],
            "summary": [
                {
                    "label": "Coverage (matched/attempted)",
                    "value": f"{round((matched_region_count / attempted_region_count) * 100, 2) if attempted_region_count else 0.0}%",
                },
                {"label": "Uncovered IDs", "value": ", ".join(uncovered_regions[:12]) if uncovered_regions else "-"},
            ],
            "tables": {
                "uncovered_regions": [{"major_region_id": value} for value in uncovered_regions[:300]],
                "seed_rows": traversal_rows[:500],
            },
        },
        "mismatch_report": {
            "kind": "summary",
            "cards": [
                {"title": "Out of Catalog", "value": len(mismatch.get("out_of_catalog_region_ids", []) or [])},
                {"title": "Uncovered", "value": len(mismatch.get("uncovered_regions", []) or [])},
            ],
            "tables": {
                "out_of_catalog": [{"major_region_id": value} for value in mismatch.get("out_of_catalog_region_ids", []) or []],
                "uncovered_regions": [{"major_region_id": value} for value in mismatch.get("uncovered_regions", []) or []],
            },
        },
    }

    traversal_summary = {
        "seed_region_count": seed_region_count,
        "attempted_region_count": attempted_region_count,
        "matched_region_count": matched_region_count,
        "uncovered_region_count": uncovered_region_count,
    }

    run_info = {
        "run_id": str(summary.get("run_id") or ""),
        "status": str(summary.get("status") or ""),
        "preview_root": preview_root,
        "report_path": str(summary.get("paths", {}).get("reports", "")),
        "log_path": str(summary.get("paths", {}).get("log", "")),
        "seed_traversal_stats": traversal_summary,
        "ontology_gate_allow_load": bool(ontology_gate.get("gate_decision", {}).get("allow_load", True))
        if isinstance(ontology_gate, dict) and ontology_gate
        else True,
    }

    return MajorReportSummaryViewModel(
        blocked=False,
        block_reason="",
        available=True,
        summary_cards=summary_cards,
        navigation=navigation,
        panes=panes,
        traversal_summary=traversal_summary,
        uncovered_regions=uncovered_regions,
        run_info=run_info,
        raw=bundle,
    ).to_dict()


def preview_root_exists(path: str) -> bool:
    return bool(path and Path(path).exists())
