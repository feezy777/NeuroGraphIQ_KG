from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Any

from scripts.desktop.models import GateDecision
from scripts.desktop.services.action_help_service import ActionHelpService
from scripts.desktop.services.file_service import FileService
from scripts.desktop.services.fine_process_router import FineProcessRouter
from scripts.desktop.services.ontology_service import OntologyService
from scripts.desktop.services.preprocess_service import PreprocessService
from scripts.desktop.services.preview_service import PreviewService
from scripts.desktop.state_store import DesktopStateStore
from scripts.desktop.view_models import (
    build_file_list_view_model,
    build_file_preview_view_model,
    build_major_results_view_model,
    build_preprocess_report_view_model,
)
from scripts.services.preview_reader import load_preview_bundle
from scripts.services.runtime_config import load_runtime_config, save_runtime_config

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FILE_CENTER_DIR = PROJECT_ROOT / "artifacts" / "ui_file_center"
DESKTOP_STATE_DIR = PROJECT_ROOT / "artifacts" / "desktop" / "state"
UI_RUNS_DIR = PROJECT_ROOT / "artifacts" / "ui_runs"


class DesktopController:
    def __init__(self) -> None:
        self._logs: deque[str] = deque(maxlen=400)
        self._state_store = DesktopStateStore(DESKTOP_STATE_DIR)
        self._ontology_service = OntologyService(state_store=self._state_store)
        self._file_service = FileService(FILE_CENTER_DIR)
        self._preview_service = PreviewService(FILE_CENTER_DIR)
        self._fine_router = FineProcessRouter()
        self._preprocess_service = PreprocessService(
            file_center_root=FILE_CENTER_DIR,
            runtime_provider=self.load_settings,
            gate_provider=self.gate_decision,
            log_handler=self.log,
        )
        self._action_help_service = ActionHelpService(runtime_provider=self.load_settings, log_handler=self.log)

    def shutdown(self) -> None:
        self._preprocess_service.shutdown()

    def log(self, message: str) -> None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._logs.appendleft(f"[{stamp}] {message}")

    def recent_logs(self) -> list[str]:
        return list(self._logs)

    def load_settings(self) -> dict[str, Any]:
        return load_runtime_config()

    def save_settings(self, overrides: dict[str, Any]) -> dict[str, Any]:
        current = load_runtime_config()
        merged = self._deep_merge(current, overrides or {})
        save_runtime_config(merged)
        self.log("runtime settings saved")
        return merged

    def import_ontology(self, path: str | Path) -> dict[str, Any]:
        result = self._ontology_service.import_ontology(path)
        if result.success:
            self.log(f"ontology imported version={result.baseline.version_id if result.baseline else '-'}")
        else:
            self.log(f"ontology import failed: {result.message}")
        return result.to_dict()

    def active_ontology(self) -> dict[str, Any] | None:
        baseline = self._ontology_service.active_baseline()
        return baseline.to_dict() if baseline else None

    def gate_decision(self) -> GateDecision:
        return self._ontology_service.gate_decision()

    def import_files(self, paths: list[str | Path]) -> dict[str, Any]:
        baseline = self._ontology_service.active_baseline()
        linked_version = baseline.version_id if baseline else ""
        imported = self._file_service.import_files(paths=paths, linked_ontology_version=linked_version)
        self.log(f"files imported count={len(imported)}")

        gate = self.gate_decision()
        queued: list[dict[str, Any]] = []
        if gate.allow_preprocess:
            queued = self._preprocess_service.enqueue_many([str(item.get("file_id") or "") for item in imported], trigger="auto")
        else:
            self.log(f"auto preprocess skipped: {gate.block_reason or 'ontology_not_ready'}")
        return {"files": imported, "queued_tasks": queued, "gate_decision": gate.to_dict()}

    def start_preprocess(self, file_ids: list[str] | None = None) -> list[dict[str, Any]]:
        gate = self.gate_decision()
        if not gate.allow_preprocess:
            self.log(f"manual preprocess blocked: {gate.block_reason}")
            raise PermissionError(gate.block_reason or "preprocess_blocked")

        target_ids = [str(x) for x in (file_ids or []) if str(x).strip()]
        if not target_ids:
            listing = self._file_service.list_files()
            target_ids = [str(item.get("file_id") or "") for item in listing.get("files", [])]
        return self._preprocess_service.enqueue_many(target_ids, trigger="manual")

    def list_files(self) -> dict[str, Any]:
        return self._file_service.list_files()

    def list_file_view_models(self, filter_key: str = "all") -> dict[str, Any]:
        return build_file_list_view_model(self._file_service.list_files(), filter_key=filter_key)

    def list_preprocess_tasks(self) -> list[dict[str, Any]]:
        return self._preprocess_service.list_tasks()

    def preview(self, file_id: str, page: int = 1, page_size: int = 200, mode: str = "auto") -> dict[str, Any]:
        gate = self.gate_decision()
        preview = self._preview_service.get_preview(
            file_id=file_id,
            page=page,
            page_size=page_size,
            mode=mode,
            gate_decision=gate,
        )
        state = self._state_store.load()
        state["last_preview_file_id"] = file_id
        self._state_store.save(state)
        return preview

    def report(self, file_id: str) -> dict[str, Any]:
        gate = self.gate_decision()
        return self._preview_service.get_report(file_id=file_id, gate_decision=gate)

    def get_file_preview_view_model(
        self,
        file_id: str,
        page: int = 1,
        page_size: int = 200,
        mode: str = "auto",
    ) -> dict[str, Any]:
        gate = self.gate_decision()
        file_record = self._file_service.get_file(file_id=file_id) or {}
        report_bundle: dict[str, Any] | None = None
        preview_payload: dict[str, Any] | None = None
        if gate.allow_preview and file_record:
            report_bundle = self._preview_service.get_report(file_id=file_id, gate_decision=gate)
            preview_payload = self._preview_service.get_preview(
                file_id=file_id,
                page=page,
                page_size=page_size,
                mode=mode,
                gate_decision=gate,
            )
        return build_file_preview_view_model(
            file_record=file_record,
            preview_payload=preview_payload,
            report_bundle=report_bundle,
            gate=gate,
        )

    def get_preprocess_report_view_model(self, file_id: str) -> dict[str, Any]:
        gate = self.gate_decision()
        file_record = self._file_service.get_file(file_id=file_id) or {}
        report_bundle: dict[str, Any] | None = None
        if gate.allow_preview and file_record:
            report_bundle = self._preview_service.get_report(file_id=file_id, gate_decision=gate)
        return build_preprocess_report_view_model(
            file_record=file_record,
            report_bundle=report_bundle,
            gate=gate,
        )

    def get_action_help_view_model(self, action_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        merged_context = self._build_help_context()
        if context:
            merged_context.update(context)
        return self._action_help_service.get_help(action_id=action_id, context=merged_context)

    def get_major_results_view_model(self, preview_root: str | Path | None = None, run_id: str = "") -> dict[str, Any]:
        gate = self.gate_decision()
        resolved_root = self._resolve_preview_root(preview_root=preview_root, run_id=run_id)
        if not resolved_root:
            return build_major_results_view_model(bundle=None, gate=gate, preview_root="")
        bundle = load_preview_bundle(resolved_root, limit=0)
        return build_major_results_view_model(bundle=bundle, gate=gate, preview_root=str(resolved_root))

    def get_circuit_traversal_view_model(self, run_id: str = "") -> dict[str, Any]:
        resolved_root = self._resolve_preview_root(preview_root=None, run_id=run_id)
        if not resolved_root:
            return {"available": False, "run_id": "", "summary": {}, "uncovered_regions": [], "seed_rows": []}
        bundle = load_preview_bundle(resolved_root, limit=0)
        reports = bundle.get("reports", {}) if isinstance(bundle, dict) else {}
        traversal = reports.get("traversal", {}) if isinstance(reports, dict) else {}
        uncovered = reports.get("uncovered", {}) if isinstance(reports, dict) else {}
        uncovered_regions = [str(x) for x in uncovered.get("uncovered_regions", []) if str(x)]
        if not uncovered_regions:
            uncovered_regions = [str(x) for x in traversal.get("uncovered_regions", []) if str(x)]
        return {
            "available": True,
            "run_id": resolved_root.name,
            "summary": {
                "seed_region_count": int(traversal.get("seed_region_count", 0) or 0),
                "attempted_region_count": int(traversal.get("attempted_region_count", 0) or 0),
                "matched_region_count": int(traversal.get("matched_region_count", 0) or 0),
                "uncovered_region_count": int(traversal.get("uncovered_region_count", len(uncovered_regions)) or 0),
            },
            "uncovered_regions": uncovered_regions,
            "seed_rows": traversal.get("seed_traversal_rows", []) or [],
        }

    def latest_successful_run_id(self) -> str:
        root = self._resolve_preview_root(preview_root=None, run_id="")
        if not root:
            return ""
        return root.name

    def route_for_fine_process(self, file_id: str) -> dict[str, Any]:
        gate = self.gate_decision()
        if not gate.allow_fine_process:
            return {
                "processor_type": "blocked",
                "status": "blocked",
                "gate_decision": gate.to_dict(),
                "input_contract": {},
                "output_contract": {},
            }
        record = self._file_service.get_file(file_id=file_id)
        routed = self._fine_router.route(record)
        routed["gate_decision"] = gate.to_dict()
        return routed

    def set_last_selected_file(self, file_id: str) -> None:
        self._state_store.update(last_selected_file_id=file_id)

    def get_last_selected_file(self) -> str:
        return str(self._state_store.load().get("last_selected_file_id") or "")

    def _resolve_preview_root(self, preview_root: str | Path | None, run_id: str) -> Path | None:
        if preview_root:
            candidate = Path(preview_root)
            if candidate.exists():
                return candidate
        if run_id:
            candidate = UI_RUNS_DIR / run_id
            if candidate.exists():
                return candidate
        if not UI_RUNS_DIR.exists():
            return None

        candidates: list[Path] = []
        for item in UI_RUNS_DIR.iterdir():
            if not item.is_dir():
                continue
            summary_path = item / "major_preview_summary.json"
            if not summary_path.exists():
                continue
            try:
                content = summary_path.read_text(encoding="utf-8")
            except Exception:
                continue
            if '"status": "success"' not in content:
                continue
            candidates.append(item)
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        out = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = DesktopController._deep_merge(out[key], value)
            else:
                out[key] = value
        return out

    def _build_help_context(self) -> dict[str, Any]:
        gate = self.gate_decision()
        selected_file_id = self.get_last_selected_file()
        selected_file = self._file_service.get_file(selected_file_id) if selected_file_id else {}
        latest_run_id = self.latest_successful_run_id()
        tasks = self.list_preprocess_tasks()
        latest_task = tasks[0] if tasks else {}
        return {
            "gate": gate.to_dict(),
            "selected_file_id": selected_file_id,
            "selected_file_type": selected_file.get("file_type", "") if isinstance(selected_file, dict) else "",
            "selected_file_status": selected_file.get("status", "") if isinstance(selected_file, dict) else "",
            "latest_preprocess_status": latest_task.get("status", ""),
            "latest_preprocess_stage": latest_task.get("current_stage", ""),
            "latest_major_run_id": latest_run_id,
            "has_active_ontology": self.active_ontology() is not None,
        }
