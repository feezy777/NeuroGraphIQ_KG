from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from scripts.modules.workbench.workbench_service import WorkbenchService


ROOT_DIR = Path(__file__).resolve().parents[2]
SERVICE = WorkbenchService(str(ROOT_DIR))


def _ok(payload: Dict[str, Any]) -> Any:
    return jsonify({"ok": True, **payload})


def _bad(message: str, code: int = 400, **extra: Any) -> Any:
    return jsonify({"ok": False, "error": message, **extra}), code


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT_DIR / "webapp" / "templates"),
        static_folder=str(ROOT_DIR / "webapp" / "static"),
    )

    @app.get("/")
    def index() -> Any:
        return render_template("index.html")

    @app.get("/api/status")
    def api_status() -> Any:
        return _ok({"status": SERVICE.status_payload()})

    @app.get("/api/logs")
    def api_logs() -> Any:
        limit = int(request.args.get("limit", 200))
        return _ok({"logs": SERVICE.store.list_task_logs(limit=limit)})

    @app.get("/api/tasks/list")
    def api_task_list() -> Any:
        return _ok({"tasks": SERVICE.store.list_tasks()})

    @app.get("/api/tasks/<task_id>")
    def api_task_detail(task_id: str) -> Any:
        task = SERVICE.store.get_task(task_id)
        if not task:
            return _bad("task_not_found", 404)
        return _ok({"task": task, "logs": SERVICE.store.list_task_logs(run_id=task_id, limit=1000)})

    @app.get("/api/config")
    def api_get_config() -> Any:
        payload = SERVICE.config_service.get_model_center_payload()
        return _ok(payload)

    @app.post("/api/config")
    def api_update_config() -> Any:
        payload = request.get_json(silent=True) or {}
        updated = SERVICE.config_service.update_runtime(payload)
        SERVICE.log_bus.emit("-", "CONFIG", "runtime_config_updated")
        return _ok({"runtime": updated})

    @app.get("/api/files/list")
    def api_files_list() -> Any:
        return _ok({"files": SERVICE.file_service.list_files()})

    @app.post("/api/files/upload")
    def api_upload_file() -> Any:
        incoming = request.files.get("file")
        if not incoming:
            return _bad("file_missing")
        SERVICE.log_bus.emit("-", "FILE", f"upload_start file={incoming.filename or 'uploaded.bin'}", event_type="file_upload_started")

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            incoming.save(tmp.name)
            temp_path = tmp.name
        try:
            payload = SERVICE.upload_file(temp_path, incoming.filename or "uploaded.bin")
            return _ok(payload)
        except Exception as exc:
            SERVICE.log_bus.emit("-", "FILE", f"upload_failed reason={exc}", level="error", event_type="file_upload_failed")
            return _bad("upload_failed", 500, detail=str(exc))
        finally:
            Path(temp_path).unlink(missing_ok=True)

    @app.get("/api/files/<file_id>")
    def api_file_detail(file_id: str) -> Any:
        file_payload = SERVICE.file_service.get_file(file_id)
        if not file_payload:
            return _bad("file_not_found", 404)
        return _ok({"bundle": SERVICE.file_workspace_bundle(file_id)})

    @app.get("/api/files/<file_id>/parsed")
    def api_file_parsed(file_id: str) -> Any:
        return _ok({"parsed": SERVICE.store.get_parsed_document(file_id)})

    @app.delete("/api/files/<file_id>")
    def api_file_remove(file_id: str) -> Any:
        SERVICE.log_bus.emit("-", "FILE", f"remove_start file_id={file_id}", event_type="file_delete_started")
        ok = SERVICE.file_service.remove_file(file_id)
        if not ok:
            SERVICE.log_bus.emit(
                "-",
                "FILE",
                f"remove_failed file_id={file_id} reason=file_not_found",
                level="error",
                event_type="file_delete_failed",
            )
            return _bad("file_not_found", 404)
        SERVICE.log_bus.emit("-", "FILE", f"remove_success file_id={file_id}", event_type="file_deleted")
        return _ok({"file_id": file_id})

    @app.post("/api/files/<file_id>/reparse")
    def api_file_reparse(file_id: str) -> Any:
        SERVICE.log_bus.emit("-", "PARSING", f"reparse_requested file_id={file_id}", event_type="reparse_started")
        payload = SERVICE.trigger_parse(file_id)
        if not payload.get("success"):
            SERVICE.log_bus.emit(
                "-",
                "PARSING",
                f"reparse_failed file_id={file_id} reason={payload.get('error', 'unknown')}",
                level="error",
                event_type="reparse_failed",
            )
            return _bad("reparse_failed", 500, detail=payload)
        SERVICE.log_bus.emit("-", "PARSING", f"reparse_succeeded file_id={file_id}", event_type="reparse_succeeded")
        return _ok(payload)

    @app.post("/api/files/<file_id>/extract-regions")
    def api_file_extract_regions(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "local")
        SERVICE.log_bus.emit(
            "-",
            "EXTRACT",
            f"extract_region_requested file_id={file_id} mode={mode}",
            event_type="extract_region_requested",
        )
        payload = SERVICE.trigger_extract_regions(file_id, mode=mode)
        if not payload.get("success"):
            return _bad("extract_region_failed", 500, detail=payload)
        return _ok(payload)

    @app.post("/api/files/<file_id>/extract-circuits")
    def api_file_extract_circuits(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "local")
        SERVICE.log_bus.emit(
            "-",
            "EXTRACT",
            f"extract_circuit_requested file_id={file_id} mode={mode}",
            event_type="extract_circuit_requested",
        )
        payload = SERVICE.trigger_extract_circuits(file_id, mode=mode)
        if not payload.get("success"):
            return _bad("extract_circuit_failed", 500, detail=payload)
        return _ok(payload)

    @app.post("/api/files/<file_id>/extract-connections")
    def api_file_extract_connections(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "local")
        SERVICE.log_bus.emit(
            "-",
            "EXTRACT",
            f"extract_connection_requested file_id={file_id} mode={mode}",
            event_type="extract_connection_requested",
        )
        payload = SERVICE.trigger_extract_connections(file_id, mode=mode)
        if not payload.get("success"):
            return _bad("extract_connection_failed", 500, detail=payload)
        return _ok(payload)

    @app.get("/api/runs/list")
    def api_runs_list() -> Any:
        return _ok({"runs": SERVICE.store.list_tasks()})

    @app.get("/api/runs/<run_id>")
    def api_run_detail(run_id: str) -> Any:
        run = SERVICE.store.get_task(run_id)
        if not run:
            return _bad("run_not_found", 404)
        return _ok({"run": run, "logs": SERVICE.store.list_task_logs(run_id=run_id, limit=1000)})

    @app.get("/api/files/<file_id>/region-candidates")
    def api_file_region_candidates(file_id: str) -> Any:
        return _ok({"items": SERVICE.list_region_candidates(file_id)})

    @app.get("/api/files/<file_id>/circuit-candidates")
    def api_file_circuit_candidates(file_id: str) -> Any:
        return _ok({"items": SERVICE.list_circuit_candidates(file_id)})

    @app.get("/api/files/<file_id>/connection-candidates")
    def api_file_connection_candidates(file_id: str) -> Any:
        return _ok({"items": SERVICE.list_connection_candidates(file_id)})

    @app.post("/api/candidates/<candidate_id>")
    def api_candidate_update(candidate_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        patch = body.get("patch", {})
        result = SERVICE.update_region_candidate(candidate_id, patch, reviewer=reviewer)
        if not result.get("success"):
            return _bad(result.get("error", "candidate_update_failed"), 404)
        return _ok(result)

    @app.post("/api/candidates/<candidate_id>/review")
    def api_candidate_review(candidate_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        action = body.get("action", "")
        reviewer = body.get("reviewer", "user")
        note = body.get("note", "")
        result = SERVICE.review_region_candidate(candidate_id, action=action, reviewer=reviewer, note=note)
        if not result.get("success"):
            return _bad(result.get("error", "candidate_review_failed"), 400)
        return _ok(result)

    @app.post("/api/circuit-candidates/<circuit_id>")
    def api_circuit_candidate_update(circuit_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        patch = body.get("patch", {})
        result = SERVICE.update_circuit_candidate(circuit_id, patch, reviewer=reviewer)
        if not result.get("success"):
            return _bad(result.get("error", "candidate_circuit_update_failed"), 404)
        return _ok(result)

    @app.post("/api/circuit-candidates/<circuit_id>/review")
    def api_circuit_candidate_review(circuit_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        action = body.get("action", "")
        reviewer = body.get("reviewer", "user")
        note = body.get("note", "")
        result = SERVICE.review_circuit_candidate(circuit_id, action=action, reviewer=reviewer, note=note)
        if not result.get("success"):
            return _bad(result.get("error", "candidate_circuit_review_failed"), 400)
        return _ok(result)

    @app.post("/api/connection-candidates/<connection_id>")
    def api_connection_candidate_update(connection_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        patch = body.get("patch", {})
        result = SERVICE.update_connection_candidate(connection_id, patch, reviewer=reviewer)
        if not result.get("success"):
            return _bad(result.get("error", "candidate_connection_update_failed"), 404)
        return _ok(result)

    @app.post("/api/connection-candidates/<connection_id>/review")
    def api_connection_candidate_review(connection_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        action = body.get("action", "")
        reviewer = body.get("reviewer", "user")
        note = body.get("note", "")
        result = SERVICE.review_connection_candidate(connection_id, action=action, reviewer=reviewer, note=note)
        if not result.get("success"):
            return _bad(result.get("error", "candidate_connection_review_failed"), 400)
        return _ok(result)

    @app.post("/api/files/<file_id>/commit-regions")
    def api_file_commit_regions(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.commit_regions(file_id=file_id, reviewer=reviewer)
        if not result.get("success"):
            return _bad(result.get("error", "commit_failed"), 400, detail=result)
        return _ok(result)

    @app.post("/api/files/<file_id>/commit-circuits")
    def api_file_commit_circuits(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.commit_circuits(file_id=file_id, reviewer=reviewer)
        if not result.get("success"):
            return _bad(result.get("error", "commit_circuit_failed"), 400, detail=result)
        return _ok(result)

    @app.post("/api/files/<file_id>/commit-connections")
    def api_file_commit_connections(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.commit_connections(file_id=file_id, reviewer=reviewer)
        if not result.get("success"):
            return _bad(result.get("error", "commit_connection_failed"), 400, detail=result)
        return _ok(result)

    @app.get("/api/unverified/regions")
    def api_unverified_regions() -> Any:
        file_id = request.args.get("file_id", "").strip()
        items = SERVICE.list_unverified_regions(file_id=file_id)
        return _ok({"items": items})

    @app.post("/api/unverified/<unverified_region_id>/validate")
    def api_unverified_validate(unverified_region_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.validate_unverified_region(unverified_region_id=unverified_region_id, reviewer=reviewer)
        return _ok(result)

    @app.post("/api/unverified/<unverified_region_id>/promote")
    def api_unverified_promote(unverified_region_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.promote_unverified_region(unverified_region_id=unverified_region_id, reviewer=reviewer)
        return _ok(result)

    @app.get("/api/unverified/circuits")
    def api_unverified_circuits() -> Any:
        file_id = request.args.get("file_id", "").strip()
        items = SERVICE.list_unverified_circuits(file_id=file_id)
        return _ok({"items": items})

    @app.get("/api/unverified/connections")
    def api_unverified_connections() -> Any:
        file_id = request.args.get("file_id", "").strip()
        items = SERVICE.list_unverified_connections(file_id=file_id)
        return _ok({"items": items})

    @app.post("/api/unverified-circuits/<unverified_circuit_id>/validate")
    def api_unverified_circuit_validate(unverified_circuit_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.validate_unverified_circuit(unverified_circuit_id=unverified_circuit_id, reviewer=reviewer)
        return _ok(result)

    @app.post("/api/unverified-circuits/<unverified_circuit_id>/promote")
    def api_unverified_circuit_promote(unverified_circuit_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.promote_unverified_circuit(unverified_circuit_id=unverified_circuit_id, reviewer=reviewer)
        return _ok(result)

    @app.post("/api/unverified-circuits/batch-validate")
    def api_unverified_circuit_batch_validate() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_validate_unverified_circuits(reviewer=reviewer, file_id=file_id, ids=ids)
        return _ok(result)

    @app.post("/api/unverified-circuits/batch-promote")
    def api_unverified_circuit_batch_promote() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_promote_unverified_circuits(reviewer=reviewer, file_id=file_id, ids=ids)
        return _ok(result)

    @app.post("/api/unverified-connections/<unverified_connection_id>/validate")
    def api_unverified_connection_validate(unverified_connection_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.validate_unverified_connection(unverified_connection_id=unverified_connection_id, reviewer=reviewer)
        return _ok(result)

    @app.post("/api/unverified-connections/<unverified_connection_id>/promote")
    def api_unverified_connection_promote(unverified_connection_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        result = SERVICE.promote_unverified_connection(unverified_connection_id=unverified_connection_id, reviewer=reviewer)
        return _ok(result)

    @app.post("/api/unverified-connections/batch-validate")
    def api_unverified_connection_batch_validate() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_validate_unverified_connections(reviewer=reviewer, file_id=file_id, ids=ids)
        return _ok(result)

    @app.post("/api/unverified-connections/batch-promote")
    def api_unverified_connection_batch_promote() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_promote_unverified_connections(reviewer=reviewer, file_id=file_id, ids=ids)
        return _ok(result)

    @app.get("/api/workbench/snapshot")
    def api_snapshot_get() -> Any:
        return _ok({"snapshot": SERVICE.store.get_workspace_snapshot()})

    @app.post("/api/workbench/snapshot")
    def api_snapshot_set() -> Any:
        body = request.get_json(silent=True) or {}
        SERVICE.store.put_workspace_snapshot(body)
        return _ok({"snapshot": body})

    return app
