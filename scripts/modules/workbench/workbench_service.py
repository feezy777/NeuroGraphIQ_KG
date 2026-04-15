from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .common.id_utils import make_id
from .common.log_bus import LogBus
from .common.models import FileStatus, ReviewRecord, TaskType, utc_now_iso
from .common.state_store import StateStore
from .config.config_service import ConfigService
from .extraction.extraction_service import ExtractionService
from .files.file_service import FileService
from .ingestion.ingestion_service import IngestionService
from .normalization.normalization_service import NormalizationService
from .parsing.parsing_service import ParsingService
from .tasks.task_service import TaskService


class WorkbenchService:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = str(Path(root_dir).resolve())
        self.store = StateStore(self.root_dir)
        self.log_bus = LogBus(max_entries=5000)
        self.log_bus.set_sink(self.store.append_task_log)
        for event in self.store.consume_internal_events():
            self.log_bus.emit(
                "-",
                "REPOSITORY",
                event.get("message", ""),
                level=event.get("level", "info"),
                event_type=event.get("event_type", "repository_event"),
                detail_json=event.get("detail_json", {}),
            )

        self.config_service = ConfigService(self.root_dir)
        self.file_service = FileService(self.root_dir, self.store)
        self.task_service = TaskService(self.store, self.log_bus)
        self.parsing_service = ParsingService()
        self.normalization_service = NormalizationService()
        self.extraction_service = ExtractionService()
        self.ingestion_service = IngestionService()

    def status_payload(self) -> Dict[str, Any]:
        runtime = self.config_service.get_runtime()
        deepseek = runtime.get("deepseek", {})
        return {
            "app": "brain_region_workbench_phase1",
            "root_dir": self.root_dir,
            "runtime": runtime,
            "file_count": len(self.store.list_files()),
            "task_count": len(self.store.list_tasks()),
            "repository_backend": "postgres" if getattr(self.store, "_pg_enabled", False) else "json",
            "deepseek_configured": bool(deepseek.get("enabled")) and bool(deepseek.get("api_key")),
            "last_logs": self.log_bus.recent(20),
        }

    # file + parse + normalize
    def upload_file(self, source_path: str, original_name: str, initiator: str = "user") -> Dict[str, Any]:
        file_payload = self.file_service.create_record_from_upload(source_path, original_name)
        file_id = file_payload["file_id"]
        self.log_bus.emit(
            "-",
            "FILE",
            f"upload_success file_id={file_id} file={original_name} type={file_payload['file_type']}",
            event_type="file_upload_succeeded",
        )

        if file_payload.get("metadata", {}).get("is_rule_file"):
            self.log_bus.emit("-", "FILE", f"rule_file_skip_extract file_id={file_id}", event_type="file_rule_skip")
            return {"file": self.file_service.get_file(file_id), "auto_started": {"parse": False}}

        runtime = self.config_service.get_runtime()
        auto_parse = bool(runtime.get("pipeline", {}).get("auto_parse_on_upload", True))
        if auto_parse:
            parse_result = self.trigger_parse(file_id, initiator=initiator)
            return {"file": self.file_service.get_file(file_id), "auto_started": {"parse": True}, "parse_result": parse_result}
        return {"file": self.file_service.get_file(file_id), "auto_started": {"parse": False}}

    def trigger_parse(self, file_id: str, initiator: str = "user") -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        if not file_payload:
            return {"success": False, "error": "file_not_found"}

        task = self.task_service.create_task(
            TaskType.PARSE,
            initiator=initiator,
            input_objects={"file_id": file_id},
            parameters={"file_type": file_payload.get("file_type", "")},
        )
        self.task_service.start_task(task["task_id"])
        self.store.update_file(file_id, status=FileStatus.PARSING.value, latest_parse_task_id=task["task_id"], updated_at=utc_now_iso())
        self.log_bus.emit(task["task_id"], "PARSING", f"start file_id={file_id}", event_type="parse_started")
        try:
            parsed = self.parsing_service.parse_file(file_payload)
            doc = parsed["document"]
            chunks = parsed["chunks"]
            self.store.put_parsed_document(doc, chunks)
            next_status = FileStatus.PARSED_SUCCESS.value if doc.parse_status == "parsed_success" else FileStatus.PARSED_FAILED.value
            self.store.update_file(file_id, status=next_status, updated_at=utc_now_iso())
            self.task_service.finish_task(task["task_id"], {"chunks": len(chunks), "parser": doc.parser_name})
            self.log_bus.emit(
                task["task_id"],
                "PARSING",
                f"finish status={next_status} chunks={len(chunks)}",
                event_type="parse_succeeded" if next_status == FileStatus.PARSED_SUCCESS.value else "parse_failed",
            )
            if next_status == FileStatus.PARSED_SUCCESS.value:
                norm = self.trigger_normalize(file_id, initiator)
                return {"success": True, "task_id": task["task_id"], "normalize": norm}
            return {"success": False, "task_id": task["task_id"], "error": "parse_failed"}
        except Exception as exc:
            self.store.update_file(file_id, status=FileStatus.PARSED_FAILED.value, updated_at=utc_now_iso())
            self.task_service.fail_task(task["task_id"], str(exc))
            self.log_bus.emit(task["task_id"], "PARSING", f"failed reason={exc}", level="error", event_type="parse_failed")
            return {"success": False, "task_id": task["task_id"], "error": str(exc)}

    def trigger_normalize(self, file_id: str, initiator: str = "user") -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        parsed_payload = self.store.get_parsed_document(file_id)
        task = self.task_service.create_task(
            TaskType.PARSE,
            initiator=initiator,
            input_objects={"file_id": file_id},
            parameters={"phase": "normalize"},
            model_or_rule_version="normalize-v1",
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(task["task_id"], "NORMALIZE", f"start file_id={file_id}", event_type="normalize_started")
        if not parsed_payload.get("document"):
            self.task_service.fail_task(task["task_id"], "parsed_document_missing")
            self.log_bus.emit(
                task["task_id"],
                "NORMALIZE",
                "failed parsed_document_missing",
                level="error",
                event_type="normalize_failed",
            )
            return {"success": False, "task_id": task["task_id"], "error": "parsed_document_missing"}

        normalized_payload = self.normalization_service.build_normalized_payload(file_payload, parsed_payload)
        metadata = file_payload.get("metadata", {})
        metadata["normalized_payload"] = normalized_payload
        self.store.update_file(file_id, metadata=metadata, updated_at=utc_now_iso())
        self.task_service.finish_task(task["task_id"], {"layers": list(normalized_payload.keys())})
        self.log_bus.emit(task["task_id"], "NORMALIZE", f"finish file_id={file_id}", event_type="normalize_succeeded")
        return {"success": True, "task_id": task["task_id"], "normalized_payload": normalized_payload}

    def _persist_region_version_and_store(
        self,
        file_id: str,
        method: str,
        lane: str,
        rows: List[Any],
        *,
        prompt_text: str = "",
        prompt_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        items = [self.store._to_dict(r) for r in rows]
        version_id = make_id("rrv")
        version = {
            "version_id": version_id,
            "file_id": file_id,
            "method": method,
            "lane": lane,
            "title": f"{method} · {utc_now_iso()[:19]}",
            "prompt_text": (prompt_text or "")[:20000],
            "prompt_meta": prompt_meta or {},
            "items": items,
            "item_count": len(items),
            "created_at": utc_now_iso(),
        }
        self.store.put_region_result_version(version)
        self.store.put_region_candidates(file_id, rows, lane=lane)
        return {"version_id": version_id, "item_count": len(items)}

    # region extraction
    def trigger_extract_regions(
        self,
        file_id: str,
        mode: str = "local",
        initiator: str = "user",
        profile_key: str = "",
        inline_deepseek_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        parsed = self.store.get_parsed_document(file_id)
        if not parsed.get("document"):
            return {"success": False, "error": "parsed_document_missing"}

        task = self.task_service.create_task(
            TaskType.EXTRACT_REGION,
            initiator=initiator,
            input_objects={"file_id": file_id},
            parameters={"mode": mode},
        )
        self.task_service.start_task(task["task_id"])
        self.store.update_file(
            file_id,
            status=FileStatus.EXTRACTING_REGIONS.value,
            latest_extract_task_id=task["task_id"],
            updated_at=utc_now_iso(),
        )
        self.log_bus.emit(
            task["task_id"],
            "EXTRACT",
            f"start file_id={file_id} mode={mode}",
            event_type="extract_region_started",
        )

        deepseek_cfg = self.config_service.resolve_effective_deepseek(
            profile_key=profile_key or None,
            inline_override=inline_deepseek_override,
        )
        try:
            if mode == "deepseek":
                self.log_bus.emit(task["task_id"], "EXTRACT", "[DEEPSEEK] request_start", event_type="deepseek_request_started")
            result = self.extraction_service.run_region_extraction(file_payload, parsed, mode, deepseek_cfg)
            rows = result["candidates"]
            lane = "deepseek" if mode == "deepseek" else "local"
            rmethod = "file_deepseek" if mode == "deepseek" else "file_local"
            ver = self._persist_region_version_and_store(
                file_id,
                rmethod,
                lane,
                rows,
                prompt_meta={"mode": mode, "source": "file"},
            )
            self.store.update_file(file_id, status=FileStatus.EXTRACTION_SUCCESS.value, updated_at=utc_now_iso())
            self.task_service.finish_task(task["task_id"], {"candidate_regions": len(rows), "mode": mode})
            if mode == "deepseek":
                self.log_bus.emit(
                    task["task_id"],
                    "EXTRACT",
                    f"[DEEPSEEK] request_success model={result.get('llm_model', '')}",
                    event_type="deepseek_request_succeeded",
                )
            self.log_bus.emit(
                task["task_id"],
                "EXTRACT",
                f"finish file_id={file_id} regions={len(rows)}",
                event_type="extract_region_succeeded",
            )
            return {"success": True, "task_id": task["task_id"], "count": len(rows), **ver}
        except Exception as exc:
            self.store.update_file(file_id, status=FileStatus.EXTRACTION_FAILED.value, updated_at=utc_now_iso())
            self.task_service.fail_task(task["task_id"], str(exc))
            self.log_bus.emit(
                task["task_id"],
                "EXTRACT",
                f"failed reason={exc}",
                level="error",
                event_type="extract_region_failed",
            )
            return {"success": False, "task_id": task["task_id"], "error": str(exc)}

    def generate_regions_from_text(
        self,
        text: str,
        mode: str,
        file_id: str,
        profile_key: str = "",
        inline_deepseek_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        if not file_payload:
            return {"success": False, "error": "file_not_found"}
        text = (text or "").strip()
        if not text:
            return {"success": False, "error": "text_required"}
        deepseek_cfg = self.config_service.resolve_effective_deepseek(
            profile_key=profile_key or None,
            inline_override=inline_deepseek_override,
        )
        parsed = self.extraction_service.build_synthetic_parsed_from_text(text, file_id)
        result = self.extraction_service.run_region_extraction(file_payload, parsed, mode, deepseek_cfg)
        rows = result["candidates"]
        lane = "deepseek" if mode == "deepseek" else "local"
        rmethod = "text_deepseek" if mode == "deepseek" else "text_local"
        ver = self._persist_region_version_and_store(
            file_id,
            rmethod,
            lane,
            rows,
            prompt_text=text[:12000],
            prompt_meta={"mode": mode, "input_kind": "text"},
        )
        self.store.update_file(file_id, status=FileStatus.EXTRACTION_SUCCESS.value, updated_at=utc_now_iso())
        return {"success": True, "count": len(rows), **ver, "method": result.get("method")}

    def generate_regions_direct(
        self,
        params: Dict[str, Any],
        profile_key: str = "",
        inline_deepseek_override: Optional[Dict[str, Any]] = None,
        file_id: str = "",
    ) -> Dict[str, Any]:
        if not file_id:
            return {"success": False, "error": "file_id_required"}
        file_payload = self.file_service.get_file(file_id)
        if not file_payload:
            return {"success": False, "error": "file_not_found"}
        p = dict(params or {})
        if not p.get("topic"):
            p["topic"] = "脑区"
        deepseek_cfg = self.config_service.resolve_effective_deepseek(
            profile_key=profile_key or None,
            inline_override=inline_deepseek_override,
        )
        parsed = self.extraction_service.build_synthetic_parsed_from_text(f"[direct] topic={p.get('topic')}", file_id)
        pd_id = parsed["document"]["parsed_document_id"]
        rows = self.extraction_service.run_direct_deepseek_regions(file_payload, pd_id, p, deepseek_cfg)
        prompt = self.extraction_service.build_region_prompt("direct_generate", p)
        ver = self._persist_region_version_and_store(
            file_id,
            "direct_deepseek",
            "deepseek",
            rows,
            prompt_text=prompt,
            prompt_meta=p,
        )
        self.store.update_file(file_id, status=FileStatus.EXTRACTION_SUCCESS.value, updated_at=utc_now_iso())
        return {"success": True, "count": len(rows), **ver, "method": "direct_deepseek"}

    def list_region_result_versions(self, file_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.store.list_region_result_versions(file_id=file_id)

    def get_region_result_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_region_result_version(version_id)

    def delete_region_result_version(self, version_id: str) -> bool:
        return self.store.delete_region_result_version(version_id)

    def save_generated_candidates(
        self,
        entity_type: str,
        file_id: str,
        candidates: List[Dict[str, Any]],
        lane: str = "local",
    ) -> Dict[str, Any]:
        if entity_type == "region":
            self.store.put_region_candidates(file_id, candidates, lane=lane)
            return {"success": True, "count": len(candidates)}
        if entity_type == "circuit":
            self.store.put_circuit_candidates(file_id, candidates, lane=lane)
            return {"success": True, "count": len(candidates)}
        if entity_type == "connection":
            self.store.put_connection_candidates(file_id, candidates, lane=lane)
            return {"success": True, "count": len(candidates)}
        return {"success": False, "error": "invalid_type"}

    def generate_circuits_from_text(
        self,
        text: str,
        mode: str,
        file_id: str,
        profile_key: str = "",
        inline_deepseek_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        _ = (text, mode, file_id, profile_key, inline_deepseek_override)
        return {"success": False, "error": "circuit_text_generate_not_implemented"}

    def generate_connections_from_text(
        self,
        text: str,
        mode: str,
        file_id: str,
        profile_key: str = "",
        inline_deepseek_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        _ = (text, mode, file_id, profile_key, inline_deepseek_override)
        return {"success": False, "error": "connection_text_generate_not_implemented"}

    def trigger_extract_circuits(
        self,
        file_id: str,
        mode: str = "local",
        initiator: str = "user",
        profile_key: str = "",
        inline_deepseek_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        parsed = self.store.get_parsed_document(file_id)
        if not parsed.get("document"):
            return {"success": False, "error": "parsed_document_missing"}

        task = self.task_service.create_task(
            TaskType.EXTRACT_CIRCUIT,
            initiator=initiator,
            input_objects={"file_id": file_id},
            parameters={"mode": mode},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "EXTRACT",
            f"start circuit_extract file_id={file_id} mode={mode}",
            event_type="extract_circuit_started",
        )
        deepseek_cfg = self.config_service.resolve_effective_deepseek(
            profile_key=profile_key or None,
            inline_override=inline_deepseek_override,
        )
        try:
            region_candidates = self.store.list_region_candidates(file_id, lane=None)
            result = self.extraction_service.run_circuit_extraction(file_payload, parsed, mode, deepseek_cfg, region_candidates)
            rows = result["candidates"]
            self.store.put_circuit_candidates(file_id, rows)
            self.task_service.finish_task(task["task_id"], {"candidate_circuits": len(rows), "mode": mode})
            self.log_bus.emit(
                task["task_id"],
                "EXTRACT",
                f"finish circuit_extract file_id={file_id} circuits={len(rows)}",
                event_type="extract_circuit_succeeded",
            )
            return {"success": True, "task_id": task["task_id"], "count": len(rows)}
        except Exception as exc:
            self.task_service.fail_task(task["task_id"], str(exc))
            self.log_bus.emit(
                task["task_id"],
                "EXTRACT",
                f"circuit_extract_failed reason={exc}",
                level="error",
                event_type="extract_circuit_failed",
            )
            return {"success": False, "task_id": task["task_id"], "error": str(exc)}

    def trigger_extract_connections(
        self,
        file_id: str,
        mode: str = "local",
        initiator: str = "user",
        profile_key: str = "",
        inline_deepseek_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        parsed = self.store.get_parsed_document(file_id)
        if not parsed.get("document"):
            return {"success": False, "error": "parsed_document_missing"}

        task = self.task_service.create_task(
            TaskType.EXTRACT_CONNECTION,
            initiator=initiator,
            input_objects={"file_id": file_id},
            parameters={"mode": mode},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "EXTRACT",
            f"start connection_extract file_id={file_id} mode={mode}",
            event_type="extract_connection_started",
        )
        deepseek_cfg = self.config_service.resolve_effective_deepseek(
            profile_key=profile_key or None,
            inline_override=inline_deepseek_override,
        )
        try:
            region_candidates = self.store.list_region_candidates(file_id, lane=None)
            result = self.extraction_service.run_connection_extraction(file_payload, parsed, mode, deepseek_cfg, region_candidates)
            rows = result["candidates"]
            self.store.put_connection_candidates(file_id, rows)
            self.task_service.finish_task(task["task_id"], {"candidate_connections": len(rows), "mode": mode})
            self.log_bus.emit(
                task["task_id"],
                "EXTRACT",
                f"finish connection_extract file_id={file_id} connections={len(rows)}",
                event_type="extract_connection_succeeded",
            )
            return {"success": True, "task_id": task["task_id"], "count": len(rows)}
        except Exception as exc:
            self.task_service.fail_task(task["task_id"], str(exc))
            self.log_bus.emit(
                task["task_id"],
                "EXTRACT",
                f"connection_extract_failed reason={exc}",
                level="error",
                event_type="extract_connection_failed",
            )
            return {"success": False, "task_id": task["task_id"], "error": str(exc)}

    # review
    def list_region_candidates(self, file_id: str = "") -> List[Dict[str, Any]]:
        return self.store.list_region_candidates(file_id)

    def list_circuit_candidates(self, file_id: str = "") -> List[Dict[str, Any]]:
        return self.store.list_circuit_candidates(file_id)

    def list_connection_candidates(self, file_id: str = "") -> List[Dict[str, Any]]:
        return self.store.list_connection_candidates(file_id)

    def update_region_candidate(self, candidate_id: str, patch: Dict[str, Any], reviewer: str = "user") -> Dict[str, Any]:
        before = self.store.get_region_candidate(candidate_id)
        if not before:
            return {"success": False, "error": "candidate_not_found"}
        allowed = {
            "en_name_candidate",
            "cn_name_candidate",
            "alias_candidates",
            "laterality_candidate",
            "region_category_candidate",
            "granularity_candidate",
            "parent_region_candidate",
            "ontology_source_candidate",
            "confidence",
            "review_note",
        }
        safe_patch = {k: v for k, v in patch.items() if k in allowed}
        safe_patch["updated_at"] = utc_now_iso()
        after = self.store.update_region_candidate(candidate_id, **safe_patch)
        record = ReviewRecord(
            id=make_id("review"),
            candidate_region_id=candidate_id,
            reviewer=reviewer,
            action="edit",
            before_json=before,
            after_json=after,
            note=patch.get("review_note", ""),
        )
        self.store.append_review_record(record)
        self.log_bus.emit("-", "REVIEW", f"edit candidate_id={candidate_id}", event_type="candidate_edit")
        return {"success": True, "candidate": after}

    def review_region_candidate(self, candidate_id: str, action: str, reviewer: str, note: str = "") -> Dict[str, Any]:
        before = self.store.get_region_candidate(candidate_id)
        if not before:
            return {"success": False, "error": "candidate_not_found"}
        if action not in {"approve", "reject"}:
            return {"success": False, "error": "invalid_action"}

        task = self.task_service.create_task(
            TaskType.REVIEW_REGION,
            initiator=reviewer,
            input_objects={"candidate_id": candidate_id},
            parameters={"action": action},
        )
        self.task_service.start_task(task["task_id"])
        new_status = "reviewed" if action == "approve" else "rejected"
        after = self.store.update_region_candidate(
            candidate_id,
            status=new_status,
            review_note=note,
            updated_at=utc_now_iso(),
        )
        self.store.append_review_record(
            ReviewRecord(
                id=task["task_id"].replace("task_", "review_"),
                candidate_region_id=candidate_id,
                reviewer=reviewer,
                action=action,
                before_json=before,
                after_json=after,
                note=note,
            )
        )
        self.task_service.finish_task(task["task_id"], {"candidate_id": candidate_id, "status": new_status})
        self.log_bus.emit(
            task["task_id"],
            "REVIEW",
            f"{action} candidate_id={candidate_id} status={new_status}",
            event_type="candidate_reviewed",
        )
        return {"success": True, "candidate": after, "task_id": task["task_id"]}

    def update_circuit_candidate(self, circuit_id: str, patch: Dict[str, Any], reviewer: str = "user") -> Dict[str, Any]:
        before = self.store.get_circuit_candidate(circuit_id)
        if not before:
            return {"success": False, "error": "candidate_circuit_not_found"}
        allowed = {
            "en_name_candidate",
            "cn_name_candidate",
            "alias_candidates",
            "description_candidate",
            "circuit_kind_candidate",
            "loop_type_candidate",
            "cycle_verified_candidate",
            "confidence_circuit",
            "granularity_candidate",
            "review_note",
            "nodes",
        }
        safe_patch = {k: v for k, v in patch.items() if k in allowed}
        safe_patch["updated_at"] = utc_now_iso()
        after = self.store.update_circuit_candidate(circuit_id, **safe_patch)
        self.log_bus.emit("-", "REVIEW", f"edit circuit_candidate_id={circuit_id}", event_type="candidate_circuit_edit")
        return {"success": True, "candidate": after}

    def review_circuit_candidate(self, circuit_id: str, action: str, reviewer: str, note: str = "") -> Dict[str, Any]:
        before = self.store.get_circuit_candidate(circuit_id)
        if not before:
            return {"success": False, "error": "candidate_circuit_not_found"}
        if action not in {"approve", "reject"}:
            return {"success": False, "error": "invalid_action"}
        task = self.task_service.create_task(
            TaskType.REVIEW_CIRCUIT,
            initiator=reviewer,
            input_objects={"candidate_circuit_id": circuit_id},
            parameters={"action": action},
        )
        self.task_service.start_task(task["task_id"])
        new_status = "reviewed" if action == "approve" else "rejected"
        after = self.store.update_circuit_candidate(circuit_id, status=new_status, review_note=note, updated_at=utc_now_iso())
        self.task_service.finish_task(task["task_id"], {"candidate_circuit_id": circuit_id, "status": new_status})
        self.log_bus.emit(
            task["task_id"],
            "REVIEW",
            f"{action} circuit_candidate_id={circuit_id} status={new_status}",
            event_type="candidate_circuit_reviewed",
        )
        return {"success": True, "candidate": after, "task_id": task["task_id"]}

    def update_connection_candidate(self, connection_id: str, patch: Dict[str, Any], reviewer: str = "user") -> Dict[str, Any]:
        before = self.store.get_connection_candidate(connection_id)
        if not before:
            return {"success": False, "error": "candidate_connection_not_found"}
        allowed = {
            "en_name_candidate",
            "cn_name_candidate",
            "alias_candidates",
            "description_candidate",
            "granularity_candidate",
            "connection_modality_candidate",
            "source_region_ref_candidate",
            "target_region_ref_candidate",
            "confidence",
            "direction_label",
            "review_note",
        }
        safe_patch = {k: v for k, v in patch.items() if k in allowed}
        safe_patch["updated_at"] = utc_now_iso()
        after = self.store.update_connection_candidate(connection_id, **safe_patch)
        self.log_bus.emit("-", "REVIEW", f"edit connection_candidate_id={connection_id}", event_type="candidate_connection_edit")
        return {"success": True, "candidate": after}

    def review_connection_candidate(self, connection_id: str, action: str, reviewer: str, note: str = "") -> Dict[str, Any]:
        before = self.store.get_connection_candidate(connection_id)
        if not before:
            return {"success": False, "error": "candidate_connection_not_found"}
        if action not in {"approve", "reject"}:
            return {"success": False, "error": "invalid_action"}
        task = self.task_service.create_task(
            TaskType.REVIEW_CONNECTION,
            initiator=reviewer,
            input_objects={"candidate_connection_id": connection_id},
            parameters={"action": action},
        )
        self.task_service.start_task(task["task_id"])
        new_status = "reviewed" if action == "approve" else "rejected"
        after = self.store.update_connection_candidate(connection_id, status=new_status, review_note=note, updated_at=utc_now_iso())
        self.task_service.finish_task(task["task_id"], {"candidate_connection_id": connection_id, "status": new_status})
        self.log_bus.emit(
            task["task_id"],
            "REVIEW",
            f"{action} connection_candidate_id={connection_id} status={new_status}",
            event_type="candidate_connection_reviewed",
        )
        return {"success": True, "candidate": after, "task_id": task["task_id"]}

    # commit
    def commit_regions(self, file_id: str, reviewer: str = "user") -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        if not file_payload:
            return {"success": False, "error": "file_not_found"}
        candidates = self.store.get_region_candidates(file_id)
        approved = [c for c in candidates if c.get("status") in {"approved", "reviewed", "ready_for_unverified", "staged"}]
        if not approved:
            return {"success": False, "error": "no_reviewed_candidates"}

        task = self.task_service.create_task(
            TaskType.STAGE_UNVERIFIED,
            initiator=reviewer,
            input_objects={"file_id": file_id},
            parameters={"approved_count": len(approved)},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "STAGE",
            f"start stage_to_unverified file_id={file_id} reviewed={len(approved)}",
            event_type="stage_to_unverified_started",
        )

        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        try:
            result = self.ingestion_service.stage_regions_to_unverified(file_payload, approved, unverified_cfg)
        except Exception as exc:
            self.task_service.fail_task(task["task_id"], str(exc))
            self.log_bus.emit(
                task["task_id"],
                "STAGE",
                f"failed reason={exc}",
                level="error",
                event_type="stage_to_unverified_failed",
                detail_json={"error": str(exc)},
            )
            return {"success": False, "task_id": task["task_id"], "error": str(exc)}

        for row in result.get("details", []):
            cid = row.get("candidate_id", "")
            if row.get("status") == "success" and cid:
                self.store.update_region_candidate(cid, status="staged", updated_at=utc_now_iso())
                self.log_bus.emit(
                    task["task_id"],
                    "STAGE",
                    f"success candidate_id={cid} unverified_region_id={row.get('unverified_region_id', '')}",
                    event_type="stage_to_unverified_succeeded",
                )
            elif cid:
                self.store.update_region_candidate(cid, review_note=row.get("reason", ""), updated_at=utc_now_iso())
                self.log_bus.emit(
                    task["task_id"],
                    "STAGE",
                    f"failed candidate_id={cid} reason={row.get('reason')}",
                    level="error",
                    event_type="stage_to_unverified_failed",
                    detail_json={"candidate_id": cid, "reason": row.get("reason", "")},
                )

        failed_count = int(result.get("summary", {}).get("failed_count", 0))
        file_status = FileStatus.PENDING_REVIEW.value
        self.store.update_file(file_id, status=file_status, latest_commit_task_id=task["task_id"], updated_at=utc_now_iso())
        if failed_count == 0:
            self.task_service.finish_task(task["task_id"], result.get("summary", {}))
        else:
            self.task_service.fail_task(task["task_id"], f"stage_to_unverified_failed failed_count={failed_count}")
        self.log_bus.emit(
            task["task_id"],
            "STAGE",
            f"finish stage_to_unverified status={result.get('status')} file_status={file_status}",
            event_type="stage_to_unverified_finished",
        )
        if failed_count > 0:
            return {"success": False, "task_id": task["task_id"], "error": "stage_to_unverified_failed", "result": result}
        return {"success": True, "task_id": task["task_id"], "result": result}

    def commit_circuits(self, file_id: str, reviewer: str = "user") -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        if not file_payload:
            return {"success": False, "error": "file_not_found"}
        candidates = self.store.get_circuit_candidates(file_id)
        approved = [c for c in candidates if c.get("status") in {"approved", "reviewed", "ready_for_unverified", "staged"}]
        if not approved:
            return {"success": False, "error": "no_reviewed_circuits"}

        task = self.task_service.create_task(
            TaskType.STAGE_CIRCUIT_UNVERIFIED,
            initiator=reviewer,
            input_objects={"file_id": file_id},
            parameters={"approved_count": len(approved)},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_BATCH",
            f"batch_stage_started file_id={file_id} total={len(approved)}",
            event_type="batch_stage_started",
            detail_json={"entity": "circuit", "file_id": file_id, "total": len(approved)},
        )
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_STAGE",
            f"start stage_circuit_to_unverified file_id={file_id} reviewed={len(approved)}",
            event_type="stage_circuit_to_unverified_started",
        )
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        try:
            result = self.ingestion_service.stage_circuits_to_unverified(file_payload, approved, unverified_cfg)
        except Exception as exc:
            self.task_service.fail_task(task["task_id"], str(exc))
            self.log_bus.emit(
                task["task_id"],
                "CIRCUIT_STAGE",
                f"failed reason={exc}",
                level="error",
                event_type="stage_circuit_to_unverified_failed",
                detail_json={"error": str(exc)},
            )
            return {"success": False, "task_id": task["task_id"], "error": str(exc)}

        for row in result.get("details", []):
            cid = row.get("candidate_circuit_id", "")
            if row.get("status") == "success" and cid:
                self.store.update_circuit_candidate(cid, status="staged", updated_at=utc_now_iso())
                self.log_bus.emit(
                    task["task_id"],
                    "CIRCUIT_STAGE",
                    f"success candidate_circuit_id={cid} unverified_circuit_id={row.get('unverified_circuit_id','')}",
                    event_type="stage_circuit_to_unverified_succeeded",
                )
            elif cid:
                self.store.update_circuit_candidate(cid, review_note=row.get("reason", ""), updated_at=utc_now_iso())
                self.log_bus.emit(
                    task["task_id"],
                    "CIRCUIT_STAGE",
                    f"failed candidate_circuit_id={cid} reason={row.get('reason')}",
                    level="error",
                    event_type="stage_circuit_to_unverified_failed",
                    detail_json={"candidate_circuit_id": cid, "reason": row.get("reason", "")},
                )

        failed_count = int(result.get("summary", {}).get("failed_count", 0))
        if failed_count == 0:
            self.task_service.finish_task(task["task_id"], result.get("summary", {}))
        else:
            self.task_service.fail_task(task["task_id"], f"stage_circuit_to_unverified_failed failed_count={failed_count}")
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_BATCH",
            f"batch_stage_finished file_id={file_id} success={result.get('summary', {}).get('success_count', 0)} failed={failed_count}",
            event_type="batch_stage_finished",
            detail_json={"entity": "circuit", "summary": result.get("summary", {})},
        )
        if failed_count > 0:
            return {"success": False, "task_id": task["task_id"], "error": "stage_circuit_to_unverified_failed", "result": result}
        return {"success": True, "task_id": task["task_id"], "result": result}

    def commit_connections(self, file_id: str, reviewer: str = "user") -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        if not file_payload:
            return {"success": False, "error": "file_not_found"}
        candidates = self.store.get_connection_candidates(file_id)
        approved = [c for c in candidates if c.get("status") in {"approved", "reviewed", "ready_for_unverified", "staged"}]
        if not approved:
            return {"success": False, "error": "no_reviewed_connections"}

        task = self.task_service.create_task(
            TaskType.STAGE_CONNECTION_UNVERIFIED,
            initiator=reviewer,
            input_objects={"file_id": file_id},
            parameters={"approved_count": len(approved)},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_BATCH",
            f"batch_stage_started file_id={file_id} total={len(approved)}",
            event_type="batch_stage_started",
            detail_json={"entity": "connection", "file_id": file_id, "total": len(approved)},
        )
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_STAGE",
            f"start stage_connection_to_unverified file_id={file_id} reviewed={len(approved)}",
            event_type="stage_connection_to_unverified_started",
        )
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        try:
            result = self.ingestion_service.stage_connections_to_unverified(file_payload, approved, unverified_cfg)
        except Exception as exc:
            self.task_service.fail_task(task["task_id"], str(exc))
            self.log_bus.emit(
                task["task_id"],
                "CONNECTION_STAGE",
                f"failed reason={exc}",
                level="error",
                event_type="stage_connection_to_unverified_failed",
                detail_json={"error": str(exc)},
            )
            return {"success": False, "task_id": task["task_id"], "error": str(exc)}

        for row in result.get("details", []):
            cid = row.get("candidate_connection_id", "")
            if row.get("status") == "success" and cid:
                self.store.update_connection_candidate(cid, status="staged", updated_at=utc_now_iso())
                self.log_bus.emit(
                    task["task_id"],
                    "CONNECTION_STAGE",
                    f"success candidate_connection_id={cid} unverified_connection_id={row.get('unverified_connection_id','')}",
                    event_type="stage_connection_to_unverified_succeeded",
                )
            elif cid:
                self.store.update_connection_candidate(cid, review_note=row.get("reason", ""), updated_at=utc_now_iso())
                self.log_bus.emit(
                    task["task_id"],
                    "CONNECTION_STAGE",
                    f"failed candidate_connection_id={cid} reason={row.get('reason')}",
                    level="error",
                    event_type="stage_connection_to_unverified_failed",
                    detail_json={"candidate_connection_id": cid, "reason": row.get("reason", "")},
                )

        failed_count = int(result.get("summary", {}).get("failed_count", 0))
        if failed_count == 0:
            self.task_service.finish_task(task["task_id"], result.get("summary", {}))
        else:
            self.task_service.fail_task(task["task_id"], f"stage_connection_to_unverified_failed failed_count={failed_count}")
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_BATCH",
            f"batch_stage_finished file_id={file_id} success={result.get('summary', {}).get('success_count', 0)} failed={failed_count}",
            event_type="batch_stage_finished",
            detail_json={"entity": "connection", "summary": result.get("summary", {})},
        )
        if failed_count > 0:
            return {"success": False, "task_id": task["task_id"], "error": "stage_connection_to_unverified_failed", "result": result}
        return {"success": True, "task_id": task["task_id"], "result": result}

    def list_unverified_regions(self, file_id: str = "") -> List[Dict[str, Any]]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        return self.ingestion_service.list_unverified_regions(unverified_cfg, source_file_id=file_id)

    def list_unverified_circuits(self, file_id: str = "") -> List[Dict[str, Any]]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        return self.ingestion_service.list_unverified_circuits(unverified_cfg, source_file_id=file_id)

    def list_unverified_connections(self, file_id: str = "") -> List[Dict[str, Any]]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        return self.ingestion_service.list_unverified_connections(unverified_cfg, source_file_id=file_id)

    def validate_unverified_region(self, unverified_region_id: str, reviewer: str = "user") -> Dict[str, Any]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})

        task = self.task_service.create_task(
            TaskType.VALIDATE_UNVERIFIED,
            initiator=reviewer,
            input_objects={"unverified_region_id": unverified_region_id},
            parameters={"validation_type": "rule"},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "VALIDATION",
            f"start unverified_region_id={unverified_region_id}",
            event_type="validation_started",
            detail_json={"unverified_region_id": unverified_region_id, "validation_type": "rule"},
        )
        result = self.ingestion_service.validate_unverified_region(
            unverified_region_id=unverified_region_id,
            unverified_cfg=unverified_cfg,
            validator_name="rule_basic_validator",
            validation_type="rule",
        )
        if result.get("success"):
            self.task_service.finish_task(task["task_id"], result)
            self.log_bus.emit(
                task["task_id"],
                "VALIDATION",
                f"succeeded unverified_region_id={unverified_region_id}",
                event_type="validation_succeeded",
                detail_json=result,
            )
        else:
            self.task_service.fail_task(task["task_id"], result.get("error") or result.get("message", "validation_failed"))
            self.log_bus.emit(
                task["task_id"],
                "VALIDATION",
                f"failed unverified_region_id={unverified_region_id} reason={result.get('error') or result.get('message', '')}",
                level="error",
                event_type="validation_failed",
                detail_json=result,
            )
        return {"task_id": task["task_id"], **result}

    def promote_unverified_region(self, unverified_region_id: str, reviewer: str = "user") -> Dict[str, Any]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        production_cfg = runtime.get("database", {}).get("production_db", {})

        task = self.task_service.create_task(
            TaskType.PROMOTE_FINAL,
            initiator=reviewer,
            input_objects={"unverified_region_id": unverified_region_id},
            parameters={},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "PROMOTE",
            f"start unverified_region_id={unverified_region_id}",
            event_type="promote_to_final_started",
            detail_json={"unverified_region_id": unverified_region_id},
        )
        result = self.ingestion_service.promote_unverified_region(
            unverified_region_id=unverified_region_id,
            unverified_cfg=unverified_cfg,
            production_cfg=production_cfg,
        )
        if result.get("success"):
            source_candidate_id = result.get("source_candidate_region_id", "")
            if source_candidate_id:
                self.store.update_region_candidate(source_candidate_id, status="committed", updated_at=utc_now_iso())
            self.task_service.finish_task(task["task_id"], result)
            self.log_bus.emit(
                task["task_id"],
                "PROMOTE",
                f"succeeded unverified_region_id={unverified_region_id} table={result.get('promotion', {}).get('table', '')}",
                event_type="promote_to_final_succeeded",
                detail_json=result,
            )
        else:
            self.task_service.fail_task(task["task_id"], result.get("error", "promote_failed"))
            self.log_bus.emit(
                task["task_id"],
                "PROMOTE",
                f"failed unverified_region_id={unverified_region_id} reason={result.get('error', '')}",
                level="error",
                event_type="promote_to_final_failed",
                detail_json=result,
            )
        return {"task_id": task["task_id"], **result}

    def validate_unverified_circuit(self, unverified_circuit_id: str, reviewer: str = "user") -> Dict[str, Any]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        production_cfg = runtime.get("database", {}).get("production_db", {})
        production_cfg = {**production_cfg, "_unverified_ref": unverified_cfg}

        task = self.task_service.create_task(
            TaskType.VALIDATE_CIRCUIT_UNVERIFIED,
            initiator=reviewer,
            input_objects={"unverified_circuit_id": unverified_circuit_id},
            parameters={"validation_type": "rule"},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_VALIDATION",
            f"start unverified_circuit_id={unverified_circuit_id}",
            event_type="circuit_validation_started",
            detail_json={"unverified_circuit_id": unverified_circuit_id, "validation_type": "rule"},
        )
        result = self.ingestion_service.validate_unverified_circuit(
            unverified_circuit_id=unverified_circuit_id,
            unverified_cfg=unverified_cfg,
            production_cfg=production_cfg,
            validator_name="rule_circuit_validator",
            validation_type="rule",
        )
        if result.get("success"):
            self.task_service.finish_task(task["task_id"], result)
            self.log_bus.emit(
                task["task_id"],
                "CIRCUIT_VALIDATION",
                f"succeeded unverified_circuit_id={unverified_circuit_id}",
                event_type="circuit_validation_succeeded",
                detail_json=result,
            )
        else:
            self.task_service.fail_task(task["task_id"], result.get("error") or result.get("message", "circuit_validation_failed"))
            self.log_bus.emit(
                task["task_id"],
                "CIRCUIT_VALIDATION",
                f"failed unverified_circuit_id={unverified_circuit_id} reason={result.get('error') or result.get('message','')}",
                level="error",
                event_type="circuit_validation_failed",
                detail_json=result,
            )
        return {"task_id": task["task_id"], **result}

    def promote_unverified_circuit(self, unverified_circuit_id: str, reviewer: str = "user") -> Dict[str, Any]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        production_cfg = runtime.get("database", {}).get("production_db", {})

        task = self.task_service.create_task(
            TaskType.PROMOTE_CIRCUIT_FINAL,
            initiator=reviewer,
            input_objects={"unverified_circuit_id": unverified_circuit_id},
            parameters={},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_PROMOTE",
            f"start unverified_circuit_id={unverified_circuit_id}",
            event_type="promote_circuit_started",
            detail_json={"unverified_circuit_id": unverified_circuit_id},
        )
        result = self.ingestion_service.promote_unverified_circuit(
            unverified_circuit_id=unverified_circuit_id,
            unverified_cfg=unverified_cfg,
            production_cfg=production_cfg,
        )
        if result.get("success"):
            source_candidate_id = result.get("source_candidate_circuit_id", "")
            if source_candidate_id:
                self.store.update_circuit_candidate(source_candidate_id, status="committed", updated_at=utc_now_iso())
            self.task_service.finish_task(task["task_id"], result)
            self.log_bus.emit(
                task["task_id"],
                "CIRCUIT_PROMOTE",
                f"succeeded unverified_circuit_id={unverified_circuit_id} table={result.get('promotion',{}).get('table','')}",
                event_type="promote_circuit_succeeded",
                detail_json=result,
            )
            self._emit_evidence_events(task["task_id"], "CIRCUIT_EVIDENCE", result)
        else:
            self.task_service.fail_task(task["task_id"], result.get("error", "promote_circuit_failed"))
            self.log_bus.emit(
                task["task_id"],
                "CIRCUIT_PROMOTE",
                f"failed unverified_circuit_id={unverified_circuit_id} reason={result.get('error','')}",
                level="error",
                event_type="promote_circuit_failed",
                detail_json=result,
            )
            if "evidence" in str(result.get("error", "")) or "evidence" in str(result.get("detail", {})):
                self.log_bus.emit(
                    task["task_id"],
                    "CIRCUIT_EVIDENCE",
                    f"evidence_lookup_failed unverified_circuit_id={unverified_circuit_id}",
                    level="error",
                    event_type="evidence_lookup_failed",
                    detail_json=result,
                )
        return {"task_id": task["task_id"], **result}

    def validate_unverified_connection(self, unverified_connection_id: str, reviewer: str = "user") -> Dict[str, Any]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        production_cfg = runtime.get("database", {}).get("production_db", {})
        production_cfg = {**production_cfg, "_unverified_ref": unverified_cfg}
        task = self.task_service.create_task(
            TaskType.VALIDATE_CONNECTION_UNVERIFIED,
            initiator=reviewer,
            input_objects={"unverified_connection_id": unverified_connection_id},
            parameters={"validation_type": "rule"},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_VALIDATION",
            f"start unverified_connection_id={unverified_connection_id}",
            event_type="connection_validation_started",
            detail_json={"unverified_connection_id": unverified_connection_id, "validation_type": "rule"},
        )
        result = self.ingestion_service.validate_unverified_connection(
            unverified_connection_id=unverified_connection_id,
            unverified_cfg=unverified_cfg,
            production_cfg=production_cfg,
            validator_name="rule_connection_validator",
            validation_type="rule",
        )
        if result.get("success"):
            self.task_service.finish_task(task["task_id"], result)
            self.log_bus.emit(
                task["task_id"],
                "CONNECTION_VALIDATION",
                f"succeeded unverified_connection_id={unverified_connection_id}",
                event_type="connection_validation_succeeded",
                detail_json=result,
            )
        else:
            self.task_service.fail_task(task["task_id"], result.get("error") or result.get("message", "connection_validation_failed"))
            self.log_bus.emit(
                task["task_id"],
                "CONNECTION_VALIDATION",
                f"failed unverified_connection_id={unverified_connection_id} reason={result.get('error') or result.get('message','')}",
                level="error",
                event_type="connection_validation_failed",
                detail_json=result,
            )
        return {"task_id": task["task_id"], **result}

    def promote_unverified_connection(self, unverified_connection_id: str, reviewer: str = "user") -> Dict[str, Any]:
        runtime = self.config_service.get_runtime()
        unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
        production_cfg = runtime.get("database", {}).get("production_db", {})
        task = self.task_service.create_task(
            TaskType.PROMOTE_CONNECTION_FINAL,
            initiator=reviewer,
            input_objects={"unverified_connection_id": unverified_connection_id},
            parameters={},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_PROMOTE",
            f"start unverified_connection_id={unverified_connection_id}",
            event_type="promote_connection_started",
            detail_json={"unverified_connection_id": unverified_connection_id},
        )
        result = self.ingestion_service.promote_unverified_connection(
            unverified_connection_id=unverified_connection_id,
            unverified_cfg=unverified_cfg,
            production_cfg=production_cfg,
        )
        if result.get("success"):
            source_candidate_id = result.get("source_candidate_connection_id", "")
            if source_candidate_id:
                self.store.update_connection_candidate(source_candidate_id, status="committed", updated_at=utc_now_iso())
            self.task_service.finish_task(task["task_id"], result)
            self.log_bus.emit(
                task["task_id"],
                "CONNECTION_PROMOTE",
                f"succeeded unverified_connection_id={unverified_connection_id} table={result.get('promotion',{}).get('table','')}",
                event_type="promote_connection_succeeded",
                detail_json=result,
            )
            self._emit_evidence_events(task["task_id"], "CONNECTION_EVIDENCE", result)
        else:
            self.task_service.fail_task(task["task_id"], result.get("error", "promote_connection_failed"))
            self.log_bus.emit(
                task["task_id"],
                "CONNECTION_PROMOTE",
                f"failed unverified_connection_id={unverified_connection_id} reason={result.get('error','')}",
                level="error",
                event_type="promote_connection_failed",
                detail_json=result,
            )
            if "evidence" in str(result.get("error", "")) or "evidence" in str(result.get("detail", {})):
                self.log_bus.emit(
                    task["task_id"],
                    "CONNECTION_EVIDENCE",
                    f"evidence_lookup_failed unverified_connection_id={unverified_connection_id}",
                    level="error",
                    event_type="evidence_lookup_failed",
                    detail_json=result,
                )
        return {"task_id": task["task_id"], **result}

    def batch_validate_unverified_circuits(self, reviewer: str = "user", file_id: str = "", ids: List[str] | None = None) -> Dict[str, Any]:
        targets = list(ids or [])
        if not targets:
            targets = [x.get("id", "") for x in self.list_unverified_circuits(file_id=file_id)]
        targets = [x for x in targets if x]
        if not targets:
            return {"success": False, "error": "no_unverified_circuits"}
        task = self.task_service.create_task(
            TaskType.VALIDATE_CIRCUIT_UNVERIFIED,
            initiator=reviewer,
            input_objects={"file_id": file_id, "ids": targets},
            parameters={"batch": True},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_BATCH",
            f"batch_validate_started total={len(targets)}",
            event_type="batch_validate_started",
            detail_json={"entity": "circuit", "targets": targets},
        )
        results: List[Dict[str, Any]] = []
        for target_id in targets:
            runtime = self.config_service.get_runtime()
            unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
            production_cfg = runtime.get("database", {}).get("production_db", {})
            production_cfg = {**production_cfg, "_unverified_ref": unverified_cfg}
            item = self.ingestion_service.validate_unverified_circuit(
                unverified_circuit_id=target_id,
                unverified_cfg=unverified_cfg,
                production_cfg=production_cfg,
                validator_name="rule_circuit_validator",
                validation_type="rule",
            )
            results.append({"id": target_id, **item})
            if not item.get("success"):
                self.log_bus.emit(
                    task["task_id"],
                    "CIRCUIT_BATCH",
                    f"batch_item_failed action=validate id={target_id}",
                    level="error",
                    event_type="batch_item_failed",
                    detail_json={"entity": "circuit", "action": "validate", "id": target_id, "detail": item},
                )
        summary = self._summarize_batch_results(results)
        if summary["failed_count"] == 0:
            self.task_service.finish_task(task["task_id"], summary)
        else:
            self.task_service.fail_task(task["task_id"], f"batch_validate_failed failed_count={summary['failed_count']}")
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_BATCH",
            f"batch_validate_finished total={summary['total']} success={summary['success_count']} failed={summary['failed_count']}",
            event_type="batch_validate_finished",
            detail_json={"entity": "circuit", "summary": summary},
        )
        return {"success": summary["failed_count"] == 0, "task_id": task["task_id"], "summary": summary, "items": results}

    def batch_promote_unverified_circuits(self, reviewer: str = "user", file_id: str = "", ids: List[str] | None = None) -> Dict[str, Any]:
        targets = list(ids or [])
        if not targets:
            targets = [x.get("id", "") for x in self.list_unverified_circuits(file_id=file_id)]
        targets = [x for x in targets if x]
        if not targets:
            return {"success": False, "error": "no_unverified_circuits"}
        task = self.task_service.create_task(
            TaskType.PROMOTE_CIRCUIT_FINAL,
            initiator=reviewer,
            input_objects={"file_id": file_id, "ids": targets},
            parameters={"batch": True},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_BATCH",
            f"batch_promote_started total={len(targets)}",
            event_type="batch_promote_started",
            detail_json={"entity": "circuit", "targets": targets},
        )
        results: List[Dict[str, Any]] = []
        for target_id in targets:
            runtime = self.config_service.get_runtime()
            unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
            production_cfg = runtime.get("database", {}).get("production_db", {})
            item = self.ingestion_service.promote_unverified_circuit(
                unverified_circuit_id=target_id,
                unverified_cfg=unverified_cfg,
                production_cfg=production_cfg,
            )
            results.append({"id": target_id, **item})
            if item.get("success"):
                source_candidate_id = item.get("source_candidate_circuit_id", "")
                if source_candidate_id:
                    self.store.update_circuit_candidate(source_candidate_id, status="committed", updated_at=utc_now_iso())
                self._emit_evidence_events(task["task_id"], "CIRCUIT_EVIDENCE", item)
            else:
                self.log_bus.emit(
                    task["task_id"],
                    "CIRCUIT_BATCH",
                    f"batch_item_failed action=promote id={target_id}",
                    level="error",
                    event_type="batch_item_failed",
                    detail_json={"entity": "circuit", "action": "promote", "id": target_id, "detail": item},
                )
                if "evidence" in str(item.get("error", "")) or "evidence" in str(item.get("detail", {})):
                    self.log_bus.emit(
                        task["task_id"],
                        "CIRCUIT_EVIDENCE",
                        f"evidence_lookup_failed batch_promote id={target_id}",
                        level="error",
                        event_type="evidence_lookup_failed",
                        detail_json={"id": target_id, "detail": item},
                    )
        summary = self._summarize_batch_results(results)
        if summary["failed_count"] == 0:
            self.task_service.finish_task(task["task_id"], summary)
        else:
            self.task_service.fail_task(task["task_id"], f"batch_promote_failed failed_count={summary['failed_count']}")
        self.log_bus.emit(
            task["task_id"],
            "CIRCUIT_BATCH",
            f"batch_promote_finished total={summary['total']} success={summary['success_count']} failed={summary['failed_count']}",
            event_type="batch_promote_finished",
            detail_json={"entity": "circuit", "summary": summary},
        )
        return {"success": summary["failed_count"] == 0, "task_id": task["task_id"], "summary": summary, "items": results}

    def batch_validate_unverified_connections(
        self,
        reviewer: str = "user",
        file_id: str = "",
        ids: List[str] | None = None,
    ) -> Dict[str, Any]:
        targets = list(ids or [])
        if not targets:
            targets = [x.get("id", "") for x in self.list_unverified_connections(file_id=file_id)]
        targets = [x for x in targets if x]
        if not targets:
            return {"success": False, "error": "no_unverified_connections"}
        task = self.task_service.create_task(
            TaskType.VALIDATE_CONNECTION_UNVERIFIED,
            initiator=reviewer,
            input_objects={"file_id": file_id, "ids": targets},
            parameters={"batch": True},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_BATCH",
            f"batch_validate_started total={len(targets)}",
            event_type="batch_validate_started",
            detail_json={"entity": "connection", "targets": targets},
        )
        results: List[Dict[str, Any]] = []
        for target_id in targets:
            runtime = self.config_service.get_runtime()
            unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
            production_cfg = runtime.get("database", {}).get("production_db", {})
            production_cfg = {**production_cfg, "_unverified_ref": unverified_cfg}
            item = self.ingestion_service.validate_unverified_connection(
                unverified_connection_id=target_id,
                unverified_cfg=unverified_cfg,
                production_cfg=production_cfg,
                validator_name="rule_connection_validator",
                validation_type="rule",
            )
            results.append({"id": target_id, **item})
            if not item.get("success"):
                self.log_bus.emit(
                    task["task_id"],
                    "CONNECTION_BATCH",
                    f"batch_item_failed action=validate id={target_id}",
                    level="error",
                    event_type="batch_item_failed",
                    detail_json={"entity": "connection", "action": "validate", "id": target_id, "detail": item},
                )
        summary = self._summarize_batch_results(results)
        if summary["failed_count"] == 0:
            self.task_service.finish_task(task["task_id"], summary)
        else:
            self.task_service.fail_task(task["task_id"], f"batch_validate_failed failed_count={summary['failed_count']}")
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_BATCH",
            f"batch_validate_finished total={summary['total']} success={summary['success_count']} failed={summary['failed_count']}",
            event_type="batch_validate_finished",
            detail_json={"entity": "connection", "summary": summary},
        )
        return {"success": summary["failed_count"] == 0, "task_id": task["task_id"], "summary": summary, "items": results}

    def batch_promote_unverified_connections(
        self,
        reviewer: str = "user",
        file_id: str = "",
        ids: List[str] | None = None,
    ) -> Dict[str, Any]:
        targets = list(ids or [])
        if not targets:
            targets = [x.get("id", "") for x in self.list_unverified_connections(file_id=file_id)]
        targets = [x for x in targets if x]
        if not targets:
            return {"success": False, "error": "no_unverified_connections"}
        task = self.task_service.create_task(
            TaskType.PROMOTE_CONNECTION_FINAL,
            initiator=reviewer,
            input_objects={"file_id": file_id, "ids": targets},
            parameters={"batch": True},
        )
        self.task_service.start_task(task["task_id"])
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_BATCH",
            f"batch_promote_started total={len(targets)}",
            event_type="batch_promote_started",
            detail_json={"entity": "connection", "targets": targets},
        )
        results: List[Dict[str, Any]] = []
        for target_id in targets:
            runtime = self.config_service.get_runtime()
            unverified_cfg = runtime.get("database", {}).get("unverified_db", {})
            production_cfg = runtime.get("database", {}).get("production_db", {})
            item = self.ingestion_service.promote_unverified_connection(
                unverified_connection_id=target_id,
                unverified_cfg=unverified_cfg,
                production_cfg=production_cfg,
            )
            results.append({"id": target_id, **item})
            if item.get("success"):
                source_candidate_id = item.get("source_candidate_connection_id", "")
                if source_candidate_id:
                    self.store.update_connection_candidate(source_candidate_id, status="committed", updated_at=utc_now_iso())
                self._emit_evidence_events(task["task_id"], "CONNECTION_EVIDENCE", item)
            else:
                self.log_bus.emit(
                    task["task_id"],
                    "CONNECTION_BATCH",
                    f"batch_item_failed action=promote id={target_id}",
                    level="error",
                    event_type="batch_item_failed",
                    detail_json={"entity": "connection", "action": "promote", "id": target_id, "detail": item},
                )
                if "evidence" in str(item.get("error", "")) or "evidence" in str(item.get("detail", {})):
                    self.log_bus.emit(
                        task["task_id"],
                        "CONNECTION_EVIDENCE",
                        f"evidence_lookup_failed batch_promote id={target_id}",
                        level="error",
                        event_type="evidence_lookup_failed",
                        detail_json={"id": target_id, "detail": item},
                    )
        summary = self._summarize_batch_results(results)
        if summary["failed_count"] == 0:
            self.task_service.finish_task(task["task_id"], summary)
        else:
            self.task_service.fail_task(task["task_id"], f"batch_promote_failed failed_count={summary['failed_count']}")
        self.log_bus.emit(
            task["task_id"],
            "CONNECTION_BATCH",
            f"batch_promote_finished total={summary['total']} success={summary['success_count']} failed={summary['failed_count']}",
            event_type="batch_promote_finished",
            detail_json={"entity": "connection", "summary": summary},
        )
        return {"success": summary["failed_count"] == 0, "task_id": task["task_id"], "summary": summary, "items": results}

    def _summarize_batch_results(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(items)
        success_count = sum(1 for x in items if x.get("success"))
        failed_items = [x for x in items if not x.get("success")]
        reason_counts: Dict[str, int] = {}
        retryable_ids: List[str] = []
        for item in failed_items:
            reason = item.get("error") or item.get("message") or item.get("detail", {}).get("message") or "unknown_error"
            reason = str(reason)
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            item_id = item.get("id", "")
            if item_id:
                retryable_ids.append(item_id)
        return {
            "total": total,
            "success_count": success_count,
            "failed_count": total - success_count,
            "failed_reason_groups": reason_counts,
            "retryable_ids": retryable_ids,
        }

    def _emit_evidence_events(self, run_id: str, module: str, result: Dict[str, Any]) -> None:
        evidence = ((result or {}).get("promotion") or {}).get("evidence") or {}
        for event in evidence.get("events", []):
            event_type = event.get("event_type", "evidence_event")
            message = event.get("message", "")
            level = "error" if event_type.endswith("_failed") else "info"
            self.log_bus.emit(
                run_id,
                module,
                message,
                level=level,
                event_type=event_type,
                detail_json=event.get("detail", {}),
            )

    # helper payload
    def file_workspace_bundle(self, file_id: str) -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        parsed = self.store.get_parsed_document(file_id)
        return {
            "file": file_payload,
            "parsed": parsed,
            "normalized": file_payload.get("metadata", {}).get("normalized_payload", {}),
            "region_candidates": self.store.get_region_candidates(file_id),
            "circuit_candidates": self.store.get_circuit_candidates(file_id),
            "connection_candidates": self.store.get_connection_candidates(file_id),
            "review_records": self.store.list_review_records(),
            "unverified_regions": self.list_unverified_regions(file_id),
            "unverified_circuits": self.list_unverified_circuits(file_id),
            "unverified_connections": self.list_unverified_connections(file_id),
        }
