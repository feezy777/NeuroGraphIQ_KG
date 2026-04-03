from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from scripts.export.export_reports import run_export_reports
from scripts.extract.llm_extract_anatomy import run_extract_anatomy
from scripts.extract.llm_extract_circuits import run_extract_circuits
from scripts.extract.llm_extract_major_connections import run_extract_major_connections
from scripts.extract.llm_extract_major_regions import run_extract_major_regions
from scripts.load.load_anatomy_to_pg import run_load_anatomy
from scripts.load.load_circuits_to_pg import run_load_circuits
from scripts.load.load_major_connections_to_pg import run_load_major_connections
from scripts.load.load_major_regions_to_pg import run_load_major_regions
from scripts.services.ontology_gate import circuit_family_counts, relation_type_counts, run_ontology_gate
from scripts.utils.io_utils import ensure_dir, read_json, read_jsonl, write_json
from scripts.utils.logging_utils import build_logger
from scripts.utils.runtime import load_optional_config, resolve_run_id
from scripts.validate.validate_circuit_structure import run_validate_circuit_structure
from scripts.validate.validate_major_connection_table import run_validate_major_connections
from scripts.validate.validate_major_region_hierarchy import run_validate_major_regions


StageCallback = Callable[[dict[str, Any]], None]


def _report_counts(report: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "input_records",
        "output_records",
        "validated_records",
        "rejected_records",
        "upserted_records",
        "upserted_connections",
        "upserted_circuits",
        "cross_pass_records",
        "cross_fail_only_derived_records",
        "cross_fail_only_direct_records",
        "cross_fail_both_low_support_records",
        "first_error_sample",
    ]
    return {key: report.get(key) for key in keys if key in report}


def _emit(callback: StageCallback | None, event: dict[str, Any]) -> None:
    if callback:
        callback(event)


def _region_reports(
    regions: list[dict[str, Any]],
    circuits: list[dict[str, Any]],
    connections: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    region_ids = {str(item.get("major_region_id")) for item in regions if item.get("major_region_id")}
    coverage: dict[str, dict[str, int]] = {
        region_id: {"in_degree": 0, "out_degree": 0, "circuit_count": 0}
        for region_id in region_ids
    }
    out_of_catalog: set[str] = set()

    for conn in connections:
        source = str(conn.get("source_major_region_id") or "")
        target = str(conn.get("target_major_region_id") or "")
        if source in coverage:
            coverage[source]["out_degree"] += 1
        else:
            out_of_catalog.add(source)
        if target in coverage:
            coverage[target]["in_degree"] += 1
        else:
            out_of_catalog.add(target)

    for circuit in circuits:
        for node in [str(n) for n in circuit.get("node_ids", []) if n]:
            if node in coverage:
                coverage[node]["circuit_count"] += 1
            else:
                out_of_catalog.add(node)

    uncovered = [
        region_id
        for region_id, stats in coverage.items()
        if stats["in_degree"] == 0 and stats["out_degree"] == 0 and stats["circuit_count"] == 0
    ]
    coverage_report = {
        "region_count": len(region_ids),
        "coverage": coverage,
        "uncovered_regions": sorted(uncovered),
    }
    mismatch_report = {
        "out_of_catalog_region_ids": sorted(out_of_catalog),
        "uncovered_regions": sorted(uncovered),
    }
    return coverage_report, mismatch_report


def _run_stage(
    stage: str,
    stage_index: int,
    total_stages: int,
    fn: Callable[..., dict[str, Any]],
    callback: StageCallback | None,
    logger: Any,
    stage_metrics: list[dict[str, Any]],
    artifacts_dir: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    _emit(
        callback,
        {
            "status": "running",
            "current_stage": stage,
            "completed_steps": max(stage_index - 1, 0),
            "total_steps": total_stages,
        },
    )
    logger.info("Stage start: %s", stage)
    report = fn(**kwargs)
    stage_metrics.append({"stage": stage, **_report_counts(report)})
    write_json(artifacts_dir / f"{stage}.report.json", report)
    logger.info("Stage done: %s", stage)
    _emit(
        callback,
        {
            "status": "running",
            "current_stage": stage,
            "completed_steps": stage_index,
            "total_steps": total_stages,
            "stage_counts": _report_counts(report),
        },
    )
    return report


def run_major_preview(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
    callback: StageCallback | None = None,
) -> dict[str, Any]:
    resolved_run_id = resolve_run_id(run_id)
    config = load_optional_config(config_path) if config_path else {}
    excel_path = Path(input_path)
    output_root = ensure_dir(output_path)
    raw_dir = ensure_dir(output_root / "raw")
    staging_dir = ensure_dir(output_root / "staging")
    validated_dir = ensure_dir(output_root / "validated")
    rejected_dir = ensure_dir(output_root / "rejected")
    exports_dir = ensure_dir(output_root / "exports")
    exports_report_dir = ensure_dir(exports_dir / "reports")
    artifacts_dir = ensure_dir(output_root / "artifacts")
    logger = build_logger(f"major_preview_{resolved_run_id}", str(Path("logs") / f"{resolved_run_id}.log"))
    stage_metrics: list[dict[str, Any]] = []
    stage_names = [
        "extract_anatomy",
        "extract_major_regions",
        "validate_major_regions",
        "extract_major_circuits",
        "validate_major_circuits",
        "extract_major_connections",
        "validate_major_connections",
        "ontology_gate_major",
        "export_reports",
    ]
    current_stage = "init"

    try:
        current_stage = stage_names[0]
        anatomy_report = _run_stage(
            stage=stage_names[0],
            stage_index=1,
            total_stages=len(stage_names),
            fn=run_extract_anatomy,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            input_path=excel_path,
            output_path=raw_dir / "anatomy.raw.jsonl",
            config_path=config_path,
            run_id=resolved_run_id,
        )

        current_stage = stage_names[1]
        region_extract_report = _run_stage(
            stage=stage_names[1],
            stage_index=2,
            total_stages=len(stage_names),
            fn=run_extract_major_regions,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            input_path=excel_path,
            output_path=staging_dir / "major_regions.from_excel.jsonl",
            config_path=config_path,
            run_id=resolved_run_id,
        )

        current_stage = stage_names[2]
        region_validate_report = _run_stage(
            stage=stage_names[2],
            stage_index=3,
            total_stages=len(stage_names),
            fn=run_validate_major_regions,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            input_path=region_extract_report["output_path"],
            output_path=output_root,
            config_path=config_path,
            run_id=resolved_run_id,
        )

        validated_regions = read_jsonl(region_validate_report["validated_path"])
        valid_region_ids = {str(item.get("major_region_id")) for item in validated_regions if item.get("major_region_id")}
        if not valid_region_ids:
            raise ValueError("No validated major regions available.")

        current_stage = stage_names[3]
        circuit_extract_report = _run_stage(
            stage=stage_names[3],
            stage_index=4,
            total_stages=len(stage_names),
            fn=run_extract_circuits,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            input_path=region_validate_report["validated_path"],
            output_path=staging_dir / "major_circuits.raw.jsonl",
            config_path=config_path,
            run_id=resolved_run_id,
        )

        current_stage = stage_names[4]
        circuit_validate_report = _run_stage(
            stage=stage_names[4],
            stage_index=5,
            total_stages=len(stage_names),
            fn=run_validate_circuit_structure,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            input_path=circuit_extract_report["output_path"],
            output_path=output_root,
            config_path=config_path,
            run_id=resolved_run_id,
            valid_region_ids=valid_region_ids,
        )

        current_stage = stage_names[5]
        connection_extract_report = _run_stage(
            stage=stage_names[5],
            stage_index=6,
            total_stages=len(stage_names),
            fn=run_extract_major_connections,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            input_path=staging_dir,
            output_path=staging_dir / "major_connections.crosschecked.jsonl",
            config_path=config_path,
            run_id=resolved_run_id,
            circuits_path=circuit_validate_report["validated_path"],
            regions_path=region_validate_report["validated_path"],
        )

        current_stage = stage_names[6]
        connection_validate_report = _run_stage(
            stage=stage_names[6],
            stage_index=7,
            total_stages=len(stage_names),
            fn=run_validate_major_connections,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            input_path=connection_extract_report["output_path"],
            output_path=output_root,
            config_path=config_path,
            run_id=resolved_run_id,
            valid_region_ids=valid_region_ids,
        )

        current_stage = stage_names[7]
        ontology_path = (
            config.get("ontology", {}).get("path")
            or config.get("ontology_path")
            or str(Path("ontology") / "source" / "NeuroGraphIQ_KG.rdf")
        )
        ontology_report = _run_stage(
            stage=stage_names[7],
            stage_index=8,
            total_stages=len(stage_names),
            fn=run_ontology_gate,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            regions=validated_regions,
            circuits=read_jsonl(circuit_validate_report["validated_path"]),
            connections=read_jsonl(connection_validate_report["validated_path"]),
            ontology_path=ontology_path,
            ontology_config_dir=Path("configs") / "ontology",
            output_path=exports_report_dir / "ontology_gate_report.json",
            run_id=resolved_run_id,
        )

        current_stage = stage_names[8]
        _run_stage(
            stage=stage_names[8],
            stage_index=9,
            total_stages=len(stage_names),
            fn=run_export_reports,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=artifacts_dir,
            input_path=artifacts_dir,
            output_path=exports_dir,
            config_path=config_path,
            run_id=resolved_run_id,
        )

        validated_connections = read_jsonl(connection_validate_report["validated_path"])
        validated_circuits = read_jsonl(circuit_validate_report["validated_path"])
        coverage_report, mismatch_report = _region_reports(validated_regions, validated_circuits, validated_connections)

        cross_report = {
            "run_id": resolved_run_id,
            "cross_pass_records": connection_extract_report.get("cross_pass_records", 0),
            "cross_fail_only_derived_records": connection_extract_report.get("cross_fail_only_derived_records", 0),
            "cross_fail_only_direct_records": connection_extract_report.get("cross_fail_only_direct_records", 0),
            "cross_fail_both_low_support_records": connection_extract_report.get(
                "cross_fail_both_low_support_records", 0
            ),
            "derived_records": connection_extract_report.get("derived_records", 0),
            "direct_records": connection_extract_report.get("direct_records", 0),
            "support_summary": connection_extract_report.get("cross_summary", {}),
        }
        validation_report = {
            "run_id": resolved_run_id,
            "major_regions": read_json(output_root / "major_regions.validation_report.json"),
            "major_circuits": read_json(output_root / "major_circuits.validation_report.json"),
            "major_connections": read_json(output_root / "major_connections.validation_report.json"),
        }
        write_json(exports_report_dir / "major_crosscheck_report.json", cross_report)
        write_json(exports_report_dir / "major_validation_report.json", validation_report)
        write_json(exports_report_dir / "major_region_coverage_report.json", coverage_report)
        write_json(exports_report_dir / "major_mismatch_report.json", mismatch_report)
        seed_traversal_path_value = str(circuit_extract_report.get("seed_traversal_path", "")).strip()
        seed_traversal_path = Path(seed_traversal_path_value) if seed_traversal_path_value else None
        if seed_traversal_path and seed_traversal_path.exists():
            seed_traversal_report = read_json(seed_traversal_path)
        else:
            seed_traversal_report = []
        uncovered_regions_path_value = str(circuit_extract_report.get("uncovered_regions_path", "")).strip()
        uncovered_regions_path = Path(uncovered_regions_path_value) if uncovered_regions_path_value else None
        if uncovered_regions_path and uncovered_regions_path.exists():
            uncovered_regions_report = read_json(uncovered_regions_path)
        else:
            uncovered_regions_report = {
                "run_id": resolved_run_id,
                "region_count": len(validated_regions),
                "uncovered_region_count": len(coverage_report.get("uncovered_regions", [])),
                "uncovered_regions": coverage_report.get("uncovered_regions", []),
            }
        write_json(exports_report_dir / "major_seed_traversal_report.json", seed_traversal_report)
        write_json(exports_report_dir / "major_uncovered_regions.json", uncovered_regions_report)

        summary = {
            "run_id": resolved_run_id,
            "mode": "preview",
            "status": "success",
            "stages": stage_metrics,
            "paths": {
                "root": str(output_root),
                "raw": str(raw_dir),
                "staging": str(staging_dir),
                "validated": str(validated_dir),
                "rejected": str(rejected_dir),
                "exports": str(exports_dir),
                "reports": str(exports_report_dir),
                "artifacts": str(artifacts_dir),
                "log": str(Path("logs") / f"{resolved_run_id}.log"),
            },
            "files": {
                "anatomy_raw": str(Path(anatomy_report["output_path"])),
                "major_regions_validated": str(Path(region_validate_report["validated_path"])),
                "major_circuits_validated": str(Path(circuit_validate_report["validated_path"])),
                "major_connections_validated": str(Path(connection_validate_report["validated_path"])),
                "major_connections_cross_pass": str(staging_dir / "major_connections.crosschecked.cross_pass.jsonl"),
                "major_connections_cross_fail_derived": str(
                    staging_dir / "major_connections.crosschecked.cross_fail_only_derived.jsonl"
                ),
                "major_connections_cross_fail_direct": str(
                    staging_dir / "major_connections.crosschecked.cross_fail_only_direct.jsonl"
                ),
                "major_connections_cross_fail_both_low_support": str(
                    staging_dir / "major_connections.crosschecked.cross_fail_both_low_support.jsonl"
                ),
                "major_regions_rejected": str(Path(output_root / "rejected" / "major_regions.rejected.jsonl")),
                "major_circuits_rejected": str(Path(output_root / "rejected" / "major_circuits.rejected.jsonl")),
                "major_connections_rejected": str(Path(output_root / "rejected" / "major_connections.rejected.jsonl")),
                "major_circuit_family_recall": str(staging_dir / "major_circuits.raw.family_recall.json"),
                "major_circuit_instance_build": str(staging_dir / "major_circuits.raw.instance_build.jsonl"),
                "major_circuit_connection_decompose": str(staging_dir / "major_circuits.raw.connection_decompose.jsonl"),
                "major_circuit_seed_traversal": str(staging_dir / "major_circuits.raw.seed_traversal_report.json"),
                "major_circuit_uncovered_regions": str(staging_dir / "major_circuits.raw.uncovered_regions.json"),
                "major_ontology_gate_report": str(exports_report_dir / "ontology_gate_report.json"),
            },
            "metrics": {
                "circuit_family_counts": circuit_family_counts(validated_circuits),
                "relation_type_counts": relation_type_counts(validated_connections),
                "seed_traversal_summary": {
                    "seed_region_count": int(circuit_extract_report.get("seed_region_count", 0) or 0),
                    "attempted_region_count": int(circuit_extract_report.get("attempted_region_count", 0) or 0),
                    "matched_region_count": int(circuit_extract_report.get("matched_region_count", 0) or 0),
                    "uncovered_region_count": int(circuit_extract_report.get("uncovered_region_count", 0) or 0),
                },
                "ontology_gate_summary": ontology_report.get("ontology_gate_summary", {}),
            },
        }
        write_json(output_root / "major_preview_summary.json", summary)
        _emit(
            callback,
            {
                "status": "succeeded",
                "current_stage": stage_names[-1],
                "completed_steps": len(stage_names),
                "total_steps": len(stage_names),
                "artifact_paths": summary["paths"],
            },
        )
        return summary
    except Exception as exc:
        failure = {
            "run_id": resolved_run_id,
            "mode": "preview",
            "status": "failed",
            "failed_stage": current_stage,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "stages": stage_metrics,
        }
        write_json(output_root / "major_preview_summary.json", failure)
        logger.exception("Preview failed at stage: %s", current_stage)
        _emit(
            callback,
            {
                "status": "failed",
                "current_stage": current_stage,
                "completed_steps": len(stage_metrics),
                "total_steps": len(stage_names),
                "error_message": str(exc),
            },
        )
        raise


def run_major_load(
    preview_root: str | Path,
    config_path: str = "",
    run_id: str = "",
    callback: StageCallback | None = None,
) -> dict[str, Any]:
    resolved_run_id = resolve_run_id(run_id)
    root = Path(preview_root)
    summary_path = root / "major_preview_summary.json"
    summary = read_json(summary_path)
    if summary.get("status") != "success":
        raise ValueError(f"Preview summary is not successful: {summary_path}")
    ontology_gate_summary = summary.get("metrics", {}).get("ontology_gate_summary", {})
    if ontology_gate_summary and not bool(ontology_gate_summary.get("allow_load", True)):
        report_path = summary.get("files", {}).get("major_ontology_gate_report", "")
        raise ValueError(
            f"Load blocked by ontology gate. details={report_path or 'ontology_gate_report.json'}"
        )

    files = summary.get("files", {})
    load_artifacts = ensure_dir(root / "artifacts" / "load")
    logger = build_logger(f"major_load_{resolved_run_id}", str(Path("logs") / f"{resolved_run_id}.log"))
    stage_metrics: list[dict[str, Any]] = []
    stage_names = ["load_anatomy", "load_major_regions", "load_major_connections", "load_major_circuits"]
    current_stage = "init"

    try:
        current_stage = stage_names[0]
        _run_stage(
            stage=stage_names[0],
            stage_index=1,
            total_stages=len(stage_names),
            fn=run_load_anatomy,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=load_artifacts,
            input_path=files.get("anatomy_raw"),
            output_path=load_artifacts / "load_anatomy",
            config_path=config_path,
            run_id=resolved_run_id,
        )
        current_stage = stage_names[1]
        _run_stage(
            stage=stage_names[1],
            stage_index=2,
            total_stages=len(stage_names),
            fn=run_load_major_regions,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=load_artifacts,
            input_path=files.get("major_regions_validated"),
            output_path=load_artifacts / "load_major_regions",
            config_path=config_path,
            run_id=resolved_run_id,
        )
        current_stage = stage_names[2]
        _run_stage(
            stage=stage_names[2],
            stage_index=3,
            total_stages=len(stage_names),
            fn=run_load_major_connections,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=load_artifacts,
            input_path=files.get("major_connections_validated"),
            output_path=load_artifacts / "load_major_connections",
            config_path=config_path,
            run_id=resolved_run_id,
        )
        current_stage = stage_names[3]
        _run_stage(
            stage=stage_names[3],
            stage_index=4,
            total_stages=len(stage_names),
            fn=run_load_circuits,
            callback=callback,
            logger=logger,
            stage_metrics=stage_metrics,
            artifacts_dir=load_artifacts,
            input_path=files.get("major_circuits_validated"),
            output_path=load_artifacts / "load_major_circuits",
            config_path=config_path,
            run_id=resolved_run_id,
        )

        load_summary = {
            "run_id": resolved_run_id,
            "mode": "load",
            "status": "success",
            "stages": stage_metrics,
            "paths": {
                "preview_root": str(root),
                "load_artifacts": str(load_artifacts),
                "log": str(Path("logs") / f"{resolved_run_id}.log"),
            },
        }
        write_json(root / "major_load_summary.json", load_summary)
        _emit(
            callback,
            {
                "status": "succeeded",
                "current_stage": stage_names[-1],
                "completed_steps": len(stage_names),
                "total_steps": len(stage_names),
            },
        )
        return load_summary
    except Exception as exc:
        failure = {
            "run_id": resolved_run_id,
            "mode": "load",
            "status": "failed",
            "failed_stage": current_stage,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "stages": stage_metrics,
        }
        write_json(root / "major_load_summary.json", failure)
        logger.exception("Load failed at stage: %s", current_stage)
        _emit(
            callback,
            {
                "status": "failed",
                "current_stage": current_stage,
                "completed_steps": len(stage_metrics),
                "total_steps": len(stage_names),
                "error_message": str(exc),
            },
        )
        raise
