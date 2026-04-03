from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OntologyBaseline:
    version_id: str
    source_path: str
    loaded_at: str
    classes: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    enums: dict[str, list[str]] = field(default_factory=dict)
    mapping_snapshot: dict[str, Any] = field(default_factory=dict)
    parse_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "source_path": self.source_path,
            "loaded_at": self.loaded_at,
            "classes": self.classes,
            "relations": self.relations,
            "enums": self.enums,
            "mapping_snapshot": self.mapping_snapshot,
            "parse_errors": self.parse_errors,
        }


@dataclass(slots=True)
class OntologyImportResult:
    success: bool
    message: str
    baseline: OntologyBaseline | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "baseline": self.baseline.to_dict() if self.baseline else None,
        }


@dataclass(slots=True)
class GateDecision:
    allow_preprocess: bool
    allow_preview: bool
    allow_fine_process: bool
    allow_load: bool
    block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_preprocess": self.allow_preprocess,
            "allow_preview": self.allow_preview,
            "allow_fine_process": self.allow_fine_process,
            "allow_load": self.allow_load,
            "block_reason": self.block_reason,
        }


@dataclass(slots=True)
class FileListItemViewModel:
    file_id: str
    filename: str
    file_type: str
    label: str
    score: str
    blocked_on_load: bool
    status: str
    last_processed_at: str
    linked_ontology_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "label": self.label,
            "score": self.score,
            "blocked_on_load": self.blocked_on_load,
            "status": self.status,
            "last_processed_at": self.last_processed_at,
            "linked_ontology_version": self.linked_ontology_version,
        }


@dataclass(slots=True)
class PreprocessReportViewModel:
    blocked: bool
    block_reason: str
    overview: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    auto_fix_plan: list[dict[str, Any]] = field(default_factory=list)
    manual_fix_plan: list[dict[str, Any]] = field(default_factory=list)
    change_log: list[str] = field(default_factory=list)
    paths: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "overview": self.overview,
            "issues": self.issues,
            "auto_fix_plan": self.auto_fix_plan,
            "manual_fix_plan": self.manual_fix_plan,
            "change_log": self.change_log,
            "paths": self.paths,
            "raw": self.raw,
        }


@dataclass(slots=True)
class MajorReportSummaryViewModel:
    blocked: bool
    block_reason: str
    available: bool
    summary_cards: list[dict[str, Any]] = field(default_factory=list)
    navigation: list[dict[str, Any]] = field(default_factory=list)
    panes: dict[str, Any] = field(default_factory=dict)
    traversal_summary: dict[str, Any] = field(default_factory=dict)
    uncovered_regions: list[str] = field(default_factory=list)
    run_info: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "available": self.available,
            "summary_cards": self.summary_cards,
            "navigation": self.navigation,
            "panes": self.panes,
            "traversal_summary": self.traversal_summary,
            "uncovered_regions": self.uncovered_regions,
            "run_info": self.run_info,
            "raw": self.raw,
        }


@dataclass(slots=True)
class ActionHelpViewModel:
    action_id: str
    title: str
    source: str
    purpose: str
    preconditions: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    context_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "title": self.title,
            "source": self.source,
            "purpose": self.purpose,
            "preconditions": self.preconditions,
            "inputs": self.inputs,
            "risks": self.risks,
            "next_steps": self.next_steps,
            "context_snapshot": self.context_snapshot,
        }


@dataclass(slots=True)
class CircuitTraversalViewModel:
    available: bool
    run_id: str
    summary: dict[str, Any] = field(default_factory=dict)
    uncovered_regions: list[str] = field(default_factory=list)
    seed_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "run_id": self.run_id,
            "summary": self.summary,
            "uncovered_regions": self.uncovered_regions,
            "seed_rows": self.seed_rows,
        }
