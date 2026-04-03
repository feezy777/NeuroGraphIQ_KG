from __future__ import annotations

from scripts.desktop.models import GateDecision
from scripts.desktop.view_models import (
    build_file_list_view_model,
    build_major_results_view_model,
    build_preprocess_report_view_model,
)


def test_build_file_list_view_model_filters_fail() -> None:
    listing = {
        "files": [
            {"file_id": "f1", "filename": "a.xlsx", "file_type": "xlsx", "overall_label": "PASS", "status": "processed"},
            {"file_id": "f2", "filename": "b.xlsx", "file_type": "xlsx", "overall_label": "FAIL", "status": "processed", "blocked_on_load": True},
        ],
        "stats": {"total": 2},
    }
    vm = build_file_list_view_model(listing, filter_key="fail")
    assert len(vm["items"]) == 1
    assert vm["items"][0]["file_id"] == "f2"


def test_build_preprocess_report_view_model_structures_overview() -> None:
    gate = GateDecision(True, True, True, True, "")
    bundle = {
        "file": {
            "filename": "brain.xlsx",
            "overall_label": "WARN",
            "blocked_on_load": False,
            "original_path": "orig.xlsx",
            "normalized_path": "norm.json",
            "processed_path": "proc.jsonl",
            "report_path": "report.json",
        },
        "report": {
            "overall_label": "WARN",
            "score": 72,
            "summary_cn": "存在轻微问题。",
            "issues": [{"severity": "WARN", "code": "dup", "message": "dup rows", "suggestion": "dedupe"}],
            "auto_fix_plan": [{"action": "trim", "reason": "normalize", "risk": "low"}],
            "manual_fix_plan": [{"action": "review", "reason": "check", "priority": "medium"}],
            "normalized_change_log": ["trim_whitespace"],
            "auto_applied_count": 1,
            "manual_required_count": 1,
            "gate_decision": {"allow_fine_process": True},
        },
    }
    vm = build_preprocess_report_view_model(file_record={"filename": "brain.xlsx"}, report_bundle=bundle, gate=gate)
    assert vm["blocked"] is False
    assert vm["overview"]["label"] == "WARN"
    assert vm["overview"]["issue_count"] == 1
    assert vm["issues"][0]["code"] == "dup"
    assert vm["auto_fix_plan"][0]["action"] == "trim"


def test_build_major_results_view_model_summarizes_bundle() -> None:
    gate = GateDecision(True, True, True, True, "")
    bundle = {
        "summary": {"run_id": "run_x", "status": "success", "paths": {"reports": "r", "log": "l"}},
        "preview": {
            "major_regions": [{"major_region_id": "R1"}],
            "major_circuits": [{"major_circuit_id": "C1"}],
            "cross_pass_connections": [{"major_connection_id": "P1"}],
            "cross_fail_only_derived": [{"major_connection_id": "F1"}],
            "cross_fail_only_direct": [],
            "cross_fail_both_low_support": [],
            "rejected_regions": [],
            "rejected_circuits": [],
            "rejected_connections": [],
        },
        "reports": {
            "crosscheck": {
                "cross_pass_records": 1,
                "cross_fail_only_derived_records": 1,
                "cross_fail_only_direct_records": 0,
                "cross_fail_both_low_support_records": 0,
                "derived_records": 1,
                "direct_records": 1,
            },
            "coverage": {"region_count": 4, "uncovered_regions": ["R3", "R4"]},
            "traversal": {"value": [{"seed_region_id": "R1", "built_instances": 1}]},
            "uncovered": {"uncovered_regions": ["R3", "R4"], "uncovered_region_count": 2},
            "mismatch": {"out_of_catalog_region_ids": ["RX"], "uncovered_regions": ["R3", "R4"]},
            "ontology_gate": {"gate_decision": {"allow_load": True}},
        },
    }
    vm = build_major_results_view_model(bundle=bundle, gate=gate, preview_root="preview_root")
    assert vm["available"] is True
    assert vm["run_info"]["run_id"] == "run_x"
    assert any(card["title"] == "Coverage" for card in vm["summary_cards"])
    assert vm["panes"]["cross_fail_connections"]["rows"][0]["crosscheck_bucket"] == "only_derived"
    assert "traversal_report" in vm["panes"]
