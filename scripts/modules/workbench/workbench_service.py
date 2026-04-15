from __future__ import annotations

import json
from dataclasses import asdict
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
from .validation.ontology_rules import engine_from_runtime, merge_candidate_ontology_note, refresh_engine
from .validation.validation_service import ValidationService


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
        self.ontology_rule_engine = engine_from_runtime(self.root_dir, self.config_service.get_runtime())
        self.validation_service = ValidationService(self.ontology_rule_engine)

    def ontology_rules_status(self) -> Dict[str, Any]:
        rt = self.config_service.get_runtime()
        cfg = (rt.get("pipeline") or {}).get("ontology_rules") or {}
        eng = self.ontology_rule_engine
        return {
            "config_enabled": bool(cfg.get("enabled")),
            "path": cfg.get("path", ""),
            "loaded": bool(eng and eng.enabled),
            "load_error": eng.load_error if eng else "",
            "rules_version": eng.rules_version if eng else "",
            "stage_policy": cfg.get("stage_policy", "warn"),
        }

    def refresh_ontology_rules(self) -> Dict[str, Any]:
        refresh_engine(self.ontology_rule_engine, self.config_service.get_runtime())
        self.validation_service.set_ontology_engine(self.ontology_rule_engine)
        return self.ontology_rules_status()

    def import_ontology_rules_from_upload(self, temp_path: str, original_filename: str) -> Dict[str, Any]:
        """Parse OWL/RDF from a temp file, write to pipeline.ontology_rules.path, reload engine."""
        from pathlib import Path

        from .validation.owl_ruleset_convert import build_ruleset, load_graph_from_path, write_ruleset_json

        src = Path(temp_path)
        if not src.is_file():
            return {"success": False, "error": "temp_file_missing"}

        try:
            g = load_graph_from_path(src)
        except Exception as exc:
            return {"success": False, "error": f"rdf_parse_failed:{exc}"}

        hint = (original_filename or src.name).strip() or "upload.owl"
        ruleset = build_ruleset(g, source_hint=hint)

        rt = self.config_service.get_runtime()
        rel = ((rt.get("pipeline") or {}).get("ontology_rules") or {}).get("path") or "artifacts/ontology/ruleset.json"
        out_path = (Path(self.root_dir) / str(rel).replace("\\", "/")).resolve()
        try:
            write_ruleset_json(out_path, ruleset)
        except Exception as exc:
            return {"success": False, "error": f"write_failed:{exc}"}

        self.refresh_ontology_rules()
        try:
            rel_out = str(out_path.relative_to(Path(self.root_dir)))
        except ValueError:
            rel_out = str(out_path)

        self.log_bus.emit(
            "-",
            "CONFIG",
            f"ontology_imported file={hint} -> {rel_out} terms={len(ruleset.get('termMap') or {})}",
            event_type="ontology_rules_imported",
            detail_json={"output_path": rel_out, "rules_version": ruleset.get("version", "")},
        )

        return {
            "success": True,
            "output_path": rel_out,
            "term_map_count": len(ruleset.get("termMap") or {}),
            "parent_rules_count": len(ruleset.get("parentRules") or {}),
            "rules_version": ruleset.get("version", ""),
            "ontology_rules": self.ontology_rules_status(),
        }

    def get_ontology_rules_bundle(self) -> Dict[str, Any]:
        """Return resolved path, load status, and full ruleset dict for the rules center UI."""
        rt = self.config_service.get_runtime()
        rel = ((rt.get("pipeline") or {}).get("ontology_rules") or {}).get("path") or "artifacts/ontology/ruleset.json"
        abs_path = (Path(self.root_dir) / str(rel).replace("\\", "/")).resolve()
        status = self.ontology_rules_status()
        ruleset: Dict[str, Any] = {}
        load_source = "none"

        eng = self.ontology_rule_engine
        if eng.enabled and eng.raw:
            ruleset = dict(eng.raw)
            load_source = "engine"
        elif abs_path.is_file():
            try:
                ruleset = json.loads(abs_path.read_text(encoding="utf-8"))
                load_source = "file"
            except Exception as exc:
                ruleset = {"_parse_error": str(exc)}
                load_source = "error"

        try:
            resolved_rel = str(abs_path.relative_to(Path(self.root_dir)))
        except ValueError:
            resolved_rel = str(abs_path)

        return {
            "status": status,
            "resolved_path": resolved_rel,
            "load_source": load_source,
            "ruleset": ruleset,
        }

    def _ontology_stage_context(self) -> Optional[Dict[str, Any]]:
        rt = self.config_service.get_runtime()
        cfg = (rt.get("pipeline") or {}).get("ontology_rules") or {}
        if not cfg.get("enabled") or not self.ontology_rule_engine.enabled:
            return None
        return {"engine": self.ontology_rule_engine, "stage_policy": cfg.get("stage_policy", "warn")}

    def _apply_ontology_notes_after_extract(self, rows: List[Dict[str, Any]], entity: str) -> None:
        rt = self.config_service.get_runtime()
        if not rt.get("pipeline", {}).get("auto_validate_on_extract"):
            return
        eng = self.ontology_rule_engine
        if not eng.enabled:
            return
        for row in rows:
            if entity == "region":
                ev = eng.evaluate_region(row)
            elif entity == "circuit":
                ev = eng.evaluate_circuit(row)
            else:
                ev = eng.evaluate_connection(row)
            if not ev.get("issues"):
                continue
            oc = eng.ontology_check_payload(ev, entity)
            note = merge_candidate_ontology_note(row.get("review_note", ""), oc)
            cid = row.get("id", "")
            if not cid:
                continue
            if entity == "region":
                self.store.update_region_candidate(cid, review_note=note, updated_at=utc_now_iso())
            elif entity == "circuit":
                self.store.update_circuit_candidate(cid, review_note=note, updated_at=utc_now_iso())
            else:
                self.store.update_connection_candidate(cid, review_note=note, updated_at=utc_now_iso())

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
            "ontology_rules": self.ontology_rules_status(),
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
            rt = self.config_service.get_runtime()
            rev2 = rt.get("pipeline", {}).get("region_extraction_v2", {})

            def _v2_log(msg: str, detail: Optional[Dict[str, Any]] = None) -> None:
                self.log_bus.emit(
                    task["task_id"],
                    "EXTRACT",
                    msg,
                    detail_json=detail or {},
                    event_type="region_pipeline_v2",
                )

            def _deepseek_batched_log(msg: str, detail: Optional[Dict[str, Any]] = None) -> None:
                self.log_bus.emit(
                    task["task_id"],
                    "EXTRACT",
                    msg,
                    detail_json=detail or {},
                    event_type="deepseek_batched_pipeline",
                )

            def _extract_emit(msg: str, detail: Optional[Dict[str, Any]] = None) -> None:
                if mode == "deepseek":
                    _deepseek_batched_log(msg, detail)
                elif rev2.get("enabled") and rev2.get("log_layers", True):
                    _v2_log(msg, detail)

            extract_emit: Optional[Any] = _extract_emit
            if mode != "deepseek" and not (rev2.get("enabled") and rev2.get("log_layers", True)):
                extract_emit = None

            result = self.extraction_service.run_region_extraction(
                file_payload,
                parsed,
                mode,
                deepseek_cfg,
                pipeline_config=rt.get("pipeline", {}),
                root_dir=self.root_dir,
                log_emit=extract_emit,
            )
            rows = result["candidates"]
            lane = "deepseek" if mode == "deepseek" else "local"
            rmethod = "file_deepseek" if mode == "deepseek" else "file_local"
            pm: Dict[str, Any] = {"mode": mode, "source": "file"}
            if result.get("deepseek_batch_summary"):
                pm["deepseek_batch_summary"] = result["deepseek_batch_summary"]
            ver = self._persist_region_version_and_store(
                file_id,
                rmethod,
                lane,
                rows,
                prompt_meta=pm,
            )
            self._apply_ontology_notes_after_extract(rows, "region")
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
            ok_payload: Dict[str, Any] = {"success": True, "task_id": task["task_id"], "count": len(rows), **ver}
            if result.get("deepseek_batch_summary"):
                ok_payload["deepseek_batch_summary"] = result["deepseek_batch_summary"]
            return ok_payload
        except Exception as exc:
            err = str(exc)
            err_type = "extract_failed"
            if err.startswith("deepseek_request_failed") or err.startswith("deepseek_http_"):
                err_type = "deepseek_transport_failed"
            elif err.startswith("deepseek_empty_result"):
                err_type = "deepseek_empty_result"
            elif err.startswith("deepseek_api_key_missing"):
                err_type = "deepseek_api_key_missing"
            elif err.startswith("deepseek_disabled"):
                err_type = "deepseek_disabled"
            self.store.update_file(file_id, status=FileStatus.EXTRACTION_FAILED.value, updated_at=utc_now_iso())
            self.task_service.fail_task(task["task_id"], err)
            self.log_bus.emit(
                task["task_id"],
                "EXTRACT",
                f"failed reason={err}",
                level="error",
                event_type="extract_region_failed",
                detail_json={"error_type": err_type, "mode": mode},
            )
            return {"success": False, "task_id": task["task_id"], "error": err, "error_type": err_type}

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
        try:
            parsed = self.extraction_service.build_synthetic_parsed_from_text(text, file_id)
            rt = self.config_service.get_runtime()
            result = self.extraction_service.run_region_extraction(
                file_payload,
                parsed,
                mode,
                deepseek_cfg,
                pipeline_config=rt.get("pipeline", {}),
                root_dir=self.root_dir,
                log_emit=None,
            )
            rows = result["candidates"]
            lane = "deepseek" if mode == "deepseek" else "local"
            rmethod = "text_deepseek" if mode == "deepseek" else "text_local"
            pm_text: Dict[str, Any] = {"mode": mode, "input_kind": "text"}
            if result.get("deepseek_batch_summary"):
                pm_text["deepseek_batch_summary"] = result["deepseek_batch_summary"]
            ver = self._persist_region_version_and_store(
                file_id,
                rmethod,
                lane,
                rows,
                prompt_text=text[:12000],
                prompt_meta=pm_text,
            )
            self._apply_ontology_notes_after_extract(rows, "region")
            self.store.update_file(file_id, status=FileStatus.EXTRACTION_SUCCESS.value, updated_at=utc_now_iso())
            out_text: Dict[str, Any] = {"success": True, "count": len(rows), **ver, "method": result.get("method")}
            if result.get("deepseek_batch_summary"):
                out_text["deepseek_batch_summary"] = result["deepseek_batch_summary"]
            return out_text
        except Exception as exc:
            err = str(exc)
            err_type = "extract_failed"
            if err.startswith("deepseek_request_failed") or err.startswith("deepseek_http_"):
                err_type = "deepseek_transport_failed"
            elif err.startswith("deepseek_empty_result"):
                err_type = "deepseek_empty_result"
            elif err.startswith("deepseek_api_key_missing"):
                err_type = "deepseek_api_key_missing"
            elif err.startswith("deepseek_disabled"):
                err_type = "deepseek_disabled"
            self.store.update_file(file_id, status=FileStatus.EXTRACTION_FAILED.value, updated_at=utc_now_iso())
            return {"success": False, "error": err, "error_type": err_type}

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

    def apply_region_result_version_to_candidates(self, file_id: str, version_id: str) -> Dict[str, Any]:
        """将某次抽取快照写回当前文件的候选表（覆盖同 file_id+lane），供审核中心使用。"""
        if not self.file_service.get_file(file_id):
            return {"success": False, "error": "file_not_found"}
        ver = self.store.get_region_result_version(version_id)
        if not ver:
            return {"success": False, "error": "version_not_found"}
        vf = (ver.get("file_id") or "").strip()
        if vf and vf != file_id:
            return {"success": False, "error": "version_file_mismatch"}
        raw = ver.get("items") or []
        if not raw:
            return {"success": False, "error": "version_empty"}
        lane = ver.get("lane") or "local"
        items: List[Dict[str, Any]] = []
        for it in raw:
            d = dict(it) if isinstance(it, dict) else {}
            d.setdefault("status", "pending_review")
            items.append(d)
        self.store.put_region_candidates(file_id, items, lane=lane)
        self.log_bus.emit(
            "-",
            "REVIEW",
            f"apply_snapshot file_id={file_id} version_id={version_id} lane={lane} count={len(items)}",
            event_type="snapshot_applied_to_candidates",
        )
        return {"success": True, "count": len(items), "lane": lane, "version_id": version_id}

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
            self._apply_ontology_notes_after_extract(rows, "circuit")
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
            self._apply_ontology_notes_after_extract(rows, "connection")
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
    def list_region_candidates(self, file_id: str = "", lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        return self.store.list_region_candidates(file_id, lane=lane)

    def list_circuit_candidates(self, file_id: str = "", lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        return self.store.list_circuit_candidates(file_id, lane=lane)

    def list_connection_candidates(self, file_id: str = "", lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        return self.store.list_connection_candidates(file_id, lane=lane)

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
        upd: Dict[str, Any] = {"status": new_status, "updated_at": utc_now_iso()}
        if note:
            upd["review_note"] = note
        after = self.store.update_region_candidate(candidate_id, **upd)
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

    def batch_review_region_candidates(
        self,
        candidate_ids: List[str],
        action: str,
        reviewer: str = "user",
        note: str = "",
    ) -> Dict[str, Any]:
        if action not in {"approve", "reject"}:
            return {"success": False, "error": "invalid_action"}
        ids = [i for i in candidate_ids if i]
        if not ids:
            return {"success": False, "error": "no_candidate_ids"}
        ok: List[str] = []
        failed: List[Dict[str, Any]] = []
        for cid in ids:
            r = self.review_region_candidate(cid, action=action, reviewer=reviewer, note=note)
            if r.get("success"):
                ok.append(cid)
            else:
                failed.append({"id": cid, "error": r.get("error", "unknown")})
        return {
            "success": len(failed) == 0,
            "updated": len(ok),
            "failed_count": len(failed),
            "ok_ids": ok,
            "failed": failed,
        }

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
    def commit_regions(
        self,
        file_id: str,
        reviewer: str = "user",
        candidate_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        file_payload = self.file_service.get_file(file_id)
        if not file_payload:
            return {"success": False, "error": "file_not_found"}
        candidates = self.store.list_region_candidates(file_id, lane=None)
        approved = [c for c in candidates if c.get("status") in {"approved", "reviewed", "ready_for_unverified", "staged"}]
        if candidate_ids:
            id_set = set(candidate_ids)
            approved = [c for c in approved if c.get("id") in id_set]
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
            result = self.ingestion_service.stage_regions_to_unverified(
                file_payload, approved, unverified_cfg, ontology_context=self._ontology_stage_context()
            )
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
            result = self.ingestion_service.stage_circuits_to_unverified(
                file_payload, approved, unverified_cfg, ontology_context=self._ontology_stage_context()
            )
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
            result = self.ingestion_service.stage_connections_to_unverified(
                file_payload, approved, unverified_cfg, ontology_context=self._ontology_stage_context()
            )
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

    def run_file_ontology_validation(self, file_id: str, mode: str = "local") -> Dict[str, Any]:
        """Run ValidationService against all region/circuit/connection candidates for a file."""
        regions = self.store.list_region_candidates(file_id, lane=None)
        circuits = self.store.get_circuit_candidates(file_id)
        connections = self.store.get_connection_candidates(file_id)
        candidates = {
            "region_candidates": regions,
            "candidate_circuits": circuits,
            "candidate_connections": connections,
        }
        run = self.validation_service.run_validation(file_id, candidates, mode=mode)
        return {"validation": asdict(run)}

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
