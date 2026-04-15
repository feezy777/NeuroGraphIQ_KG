from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from scripts.modules.workbench.workbench_service import WorkbenchService


# 作用：定位项目根目录，并在 Flask 启动时创建一个全局服务对象。
# 步骤：先解析 ROOT_DIR -> 再把根目录传给 WorkbenchService。
# 注意：这个 SERVICE 是整个后端 API 的统一业务入口。
ROOT_DIR = Path(__file__).resolve().parents[2]
SERVICE = WorkbenchService(str(ROOT_DIR))


# 作用：统一成功响应格式，前端会依赖 ok=True 判断请求成功。
# 步骤：把业务 payload 包一层 {"ok": True, ...}。
# 注意：前端 api() 工具函数就是按这个格式做解析的。
def _ok(payload: Dict[str, Any]) -> Any:
    return jsonify({"ok": True, **payload})


# 作用：统一失败响应格式，避免每个接口单独拼错误 JSON。
# 步骤：返回 {"ok": False, "error": ...} 并附带 HTTP 状态码。
# 注意：前端收到这里的错误后，会在 api() 中抛出 Error。
def _bad(message: str, code: int = 400, **extra: Any) -> Any:
    return jsonify({"ok": False, "error": message, **extra}), code


# 作用：创建 Flask 应用，并在这里集中注册所有页面和 API 路由。
# 步骤：初始化模板/静态目录 -> 定义页面路由 -> 定义各类业务接口。
# 注意：这个文件主要做“HTTP 转发”，真正业务逻辑大多在 WorkbenchService。
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
        payload["effective_deepseek"] = SERVICE.config_service.get_public_effective_deepseek()
        return _ok(payload)

    @app.get("/api/config/effective-deepseek")
    def api_effective_deepseek() -> Any:
        profile_key = request.args.get("profile_key", "").strip() or None
        eff = SERVICE.config_service.get_public_effective_deepseek(profile_key=profile_key)
        return _ok({"effective": eff})

    @app.post("/api/config")
    def api_update_config() -> Any:
        payload = request.get_json(silent=True) or {}
        updated = SERVICE.config_service.update_runtime(payload)
        SERVICE.refresh_ontology_rules()
        SERVICE.log_bus.emit("-", "CONFIG", "runtime_config_updated")
        eff = SERVICE.config_service.get_public_effective_deepseek()
        return _ok({"runtime": updated, "effective_deepseek": eff})

    @app.get("/api/ontology/rules/status")
    def api_ontology_rules_status() -> Any:
        return _ok({"ontology_rules": SERVICE.ontology_rules_status()})

    @app.get("/api/ontology/rules/bundle")
    def api_ontology_rules_bundle() -> Any:
        """Full ruleset JSON + meta for the rules center UI."""
        return _ok(SERVICE.get_ontology_rules_bundle())

    @app.post("/api/ontology/rules/reload")
    def api_ontology_rules_reload() -> Any:
        return _ok({"ontology_rules": SERVICE.refresh_ontology_rules()})

    @app.post("/api/ontology/rules/import")
    def api_ontology_rules_import() -> Any:
        """Upload OWL/RDF/Turtle; compile to ruleset JSON at configured path and reload."""
        incoming = request.files.get("file")
        if not incoming:
            return _bad("file_missing")
        name = incoming.filename or "ontology.owl"
        SERVICE.log_bus.emit(
            "-",
            "CONFIG",
            f"ontology_import_start file={name}",
            event_type="ontology_rules_import_started",
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix or ".owl") as tmp:
            incoming.save(tmp.name)
            temp_path = tmp.name
        try:
            result = SERVICE.import_ontology_rules_from_upload(temp_path, name)
            if not result.get("success"):
                SERVICE.log_bus.emit(
                    "-",
                    "CONFIG",
                    f"ontology_import_failed error={result.get('error', '')}",
                    level="error",
                    event_type="ontology_rules_import_failed",
                )
                return _bad(result.get("error", "import_failed"), 400, detail=result)
            return _ok(result)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    @app.post("/api/files/<file_id>/ontology-validate")
    def api_file_ontology_validate(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "local")
        return _ok(SERVICE.run_file_ontology_validation(file_id, mode=str(mode)))

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

    @app.post("/api/files/<file_id>/renormalize")
    def api_file_renormalize(file_id: str) -> Any:
        """Trigger normalization for an already-parsed file (idempotent)."""
        file_payload = SERVICE.file_service.get_file(file_id)
        if not file_payload:
            return _bad("file_not_found", 404)
        SERVICE.log_bus.emit("-", "NORMALIZE", f"renormalize_requested file_id={file_id}", event_type="renormalize_started")
        result = SERVICE.trigger_normalize(file_id)
        if not result.get("success"):
            return _bad("renormalize_failed", 500, detail=result)
        return _ok(result)

    # 作用：接收前端的“脑区抽取”请求，并转交给 WorkbenchService。
    # 步骤：读取 body 参数 -> 记录日志 -> 调 SERVICE.trigger_extract_regions -> 返回结果。
    # 注意：这里只是 HTTP 入口，真正的抽取逻辑不写在这里。
    @app.post("/api/files/<file_id>/extract-regions")
    def api_file_extract_regions(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "local")
        profile_key = body.get("profile_key", "").strip()
        inline_override = body.get("deepseek_override") or None
        SERVICE.log_bus.emit(
            "-",
            "EXTRACT",
            f"extract_region_requested file_id={file_id} mode={mode}",
            event_type="extract_region_requested",
        )
        payload = SERVICE.trigger_extract_regions(file_id, mode=mode, profile_key=profile_key, inline_deepseek_override=inline_override)
        if not payload.get("success"):
            return _bad("extract_region_failed", 500, detail=payload)
        return _ok(payload)

    # 作用：接收回路抽取请求，流程与脑区抽取相同。
    # 步骤：解析参数 -> 写日志 -> 调用 SERVICE.trigger_extract_circuits。
    # 注意：这个函数负责“接线”，不负责实际抽取算法。
    @app.post("/api/files/<file_id>/extract-circuits")
    def api_file_extract_circuits(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "local")
        profile_key = body.get("profile_key", "").strip()
        inline_override = body.get("deepseek_override") or None
        SERVICE.log_bus.emit(
            "-",
            "EXTRACT",
            f"extract_circuit_requested file_id={file_id} mode={mode}",
            event_type="extract_circuit_requested",
        )
        payload = SERVICE.trigger_extract_circuits(file_id, mode=mode, profile_key=profile_key, inline_deepseek_override=inline_override)
        if not payload.get("success"):
            return _bad("extract_circuit_failed", 500, detail=payload)
        return _ok(payload)

    # 作用：接收连接抽取请求，流程与前两个实体保持一致。
    # 步骤：读取 mode / DeepSeek 参数 -> 调用 SERVICE.trigger_extract_connections。
    # 注意：三个 extract API 的结构非常类似，适合初学者对照学习。
    @app.post("/api/files/<file_id>/extract-connections")
    def api_file_extract_connections(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "local")
        profile_key = body.get("profile_key", "").strip()
        inline_override = body.get("deepseek_override") or None
        SERVICE.log_bus.emit(
            "-",
            "EXTRACT",
            f"extract_connection_requested file_id={file_id} mode={mode}",
            event_type="extract_connection_requested",
        )
        payload = SERVICE.trigger_extract_connections(file_id, mode=mode, profile_key=profile_key, inline_deepseek_override=inline_override)
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
        lane_q = request.args.get("lane", "local").strip()
        lane = None if lane_q.lower() in ("all", "*") else lane_q
        return _ok({"items": SERVICE.list_region_candidates(file_id, lane=lane)})

    @app.get("/api/files/<file_id>/circuit-candidates")
    def api_file_circuit_candidates(file_id: str) -> Any:
        lane_q = request.args.get("lane", "local").strip()
        lane = None if lane_q.lower() in ("all", "*") else lane_q
        return _ok({"items": SERVICE.list_circuit_candidates(file_id, lane=lane)})

    @app.get("/api/files/<file_id>/connection-candidates")
    def api_file_connection_candidates(file_id: str) -> Any:
        lane_q = request.args.get("lane", "local").strip()
        lane = None if lane_q.lower() in ("all", "*") else lane_q
        return _ok({"items": SERVICE.list_connection_candidates(file_id, lane=lane)})

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

    @app.post("/api/candidates/batch-review")
    def api_candidates_batch_review() -> Any:
        body = request.get_json(silent=True) or {}
        candidate_ids = body.get("candidate_ids") or []
        action = body.get("action", "")
        reviewer = body.get("reviewer", "user")
        note = body.get("note", "")
        if not isinstance(candidate_ids, list):
            return _bad("invalid_candidate_ids", 400)
        result = SERVICE.batch_review_region_candidates(candidate_ids, action=action, reviewer=reviewer, note=note)
        return _ok(result)

    @app.post("/api/files/<file_id>/region-candidates/from-version")
    def api_region_candidates_from_version(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        version_id = (body.get("version_id") or "").strip()
        if not version_id:
            return _bad("version_id_required", 400)
        result = SERVICE.apply_region_result_version_to_candidates(file_id, version_id)
        if not result.get("success"):
            return _bad(result.get("error", "apply_version_failed"), 400, detail=result)
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
        candidate_ids = body.get("candidate_ids")
        if candidate_ids is not None and not isinstance(candidate_ids, list):
            return _bad("invalid_candidate_ids", 400)
        result = SERVICE.commit_regions(file_id=file_id, reviewer=reviewer, candidate_ids=candidate_ids)
        if not result.get("success"):
            return _bad(result.get("error", "commit_failed"), 400, detail=result)
        return _ok(result)

    @app.post("/api/files/<file_id>/commit-circuits")
    def api_file_commit_circuits(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        lane = body.get("lane", "local") or "local"
        result = SERVICE.commit_circuits(file_id=file_id, reviewer=reviewer, lane=lane)
        if not result.get("success"):
            return _bad(result.get("error", "commit_circuit_failed"), 400, detail=result)
        return _ok(result)

    @app.post("/api/files/<file_id>/commit-connections")
    def api_file_commit_connections(file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        lane = body.get("lane", "local") or "local"
        result = SERVICE.commit_connections(file_id=file_id, reviewer=reviewer, lane=lane)
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

    @app.post("/api/unverified/batch-validate")
    def api_unverified_batch_validate() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_validate_unverified_regions(reviewer=reviewer, file_id=file_id, ids=ids)
        return _ok(result)

    @app.post("/api/unverified/batch-promote")
    def api_unverified_batch_promote() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_promote_unverified_regions(reviewer=reviewer, file_id=file_id, ids=ids)
        return _ok(result)

    @app.post("/api/unverified/batch-retry")
    def api_unverified_batch_retry() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        action = body.get("action", "").strip().lower()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_retry_unverified(
            entity="region",
            action=action,
            reviewer=reviewer,
            file_id=file_id,
            ids=ids,
        )
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

    @app.post("/api/unverified-circuits/batch-retry")
    def api_unverified_circuit_batch_retry() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        action = body.get("action", "").strip().lower()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_retry_unverified(
            entity="circuit",
            action=action,
            reviewer=reviewer,
            file_id=file_id,
            ids=ids,
        )
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

    @app.post("/api/unverified-connections/batch-retry")
    def api_unverified_connection_batch_retry() -> Any:
        body = request.get_json(silent=True) or {}
        reviewer = body.get("reviewer", "user")
        file_id = body.get("file_id", "").strip()
        action = body.get("action", "").strip().lower()
        ids = body.get("ids", []) or []
        result = SERVICE.batch_retry_unverified(
            entity="connection",
            action=action,
            reviewer=reviewer,
            file_id=file_id,
            ids=ids,
        )
        return _ok(result)

    @app.get("/api/workbench/snapshot")
    def api_snapshot_get() -> Any:
        return _ok({"snapshot": SERVICE.store.get_workspace_snapshot()})

    @app.post("/api/workbench/snapshot")
    def api_snapshot_set() -> Any:
        body = request.get_json(silent=True) or {}
        SERVICE.store.put_workspace_snapshot(body)
        return _ok({"snapshot": body})

    # ---- text-generate endpoints (preview only, not persisted) ----

    @app.post("/api/generate/regions")
    def api_generate_regions() -> Any:
        body = request.get_json(silent=True) or {}
        text = body.get("text", "").strip()
        mode = body.get("mode", "local")
        file_id = body.get("file_id", "").strip()
        profile_key = body.get("profile_key", "").strip()
        inline_override = body.get("deepseek_override") or None
        if not text:
            return _bad("text_required")
        try:
            result = SERVICE.generate_regions_from_text(text=text, mode=mode, file_id=file_id, profile_key=profile_key, inline_deepseek_override=inline_override)
            if not result.get("success"):
                return _bad(result.get("error", "generate_regions_failed"), 400, detail=result)
            return _ok(result)
        except Exception as exc:
            SERVICE.log_bus.emit("-", "GENERATE", f"generate_regions_failed reason={exc}", level="error")
            return _bad("generate_regions_failed", 500, detail=str(exc))

    @app.post("/api/generate/regions-direct")
    def api_generate_regions_direct() -> Any:
        body = request.get_json(silent=True) or {}
        params = body.get("params", {})
        file_id = body.get("file_id", "").strip()
        profile_key = body.get("profile_key", "").strip()
        inline_override = body.get("deepseek_override") or None
        if not params.get("topic"):
            params["topic"] = "脑区"
        try:
            result = SERVICE.generate_regions_direct(params=params, profile_key=profile_key, inline_deepseek_override=inline_override, file_id=file_id)
            if not result.get("success"):
                return _bad(result.get("error", "generate_regions_direct_failed"), 400, detail=result)
            return _ok(result)
        except Exception as exc:
            SERVICE.log_bus.emit("-", "GENERATE", f"generate_regions_direct_failed reason={exc}", level="error")
            return _bad("generate_regions_direct_failed", 500, detail=str(exc))

    @app.post("/api/generate/region-prompt")
    def api_generate_region_prompt() -> Any:
        body = request.get_json(silent=True) or {}
        mode = body.get("mode", "direct_generate")
        params = body.get("params", {})
        from scripts.modules.workbench.extraction.extraction_service import ExtractionService as _ES
        prompt = _ES.build_region_prompt(mode, params)
        return _ok({"prompt": prompt})

    @app.get("/api/region-result-versions")
    def api_list_region_result_versions() -> Any:
        file_id = request.args.get("file_id", "").strip()
        versions = SERVICE.list_region_result_versions(file_id=file_id)
        return _ok({"versions": versions})

    @app.get("/api/region-result-versions/<version_id>")
    def api_get_region_result_version(version_id: str) -> Any:
        ver = SERVICE.get_region_result_version(version_id)
        if not ver:
            return _bad("version_not_found", 404)
        return _ok({"version": ver})

    @app.delete("/api/region-result-versions/<version_id>")
    def api_delete_region_result_version(version_id: str) -> Any:
        ok = SERVICE.delete_region_result_version(version_id)
        if not ok:
            return _bad("version_not_found", 404)
        return _ok({"deleted": version_id})

    @app.post("/api/generate/circuits")
    def api_generate_circuits() -> Any:
        body = request.get_json(silent=True) or {}
        text = body.get("text", "").strip()
        mode = body.get("mode", "local")
        file_id = body.get("file_id", "").strip()
        profile_key = body.get("profile_key", "").strip()
        inline_override = body.get("deepseek_override") or None
        if not text:
            return _bad("text_required")
        try:
            result = SERVICE.generate_circuits_from_text(text=text, mode=mode, file_id=file_id, profile_key=profile_key, inline_deepseek_override=inline_override)
            return _ok(result)
        except Exception as exc:
            SERVICE.log_bus.emit("-", "GENERATE", f"generate_circuits_failed reason={exc}", level="error")
            return _bad("generate_circuits_failed", 500, detail=str(exc))

    @app.post("/api/generate/connections")
    def api_generate_connections() -> Any:
        body = request.get_json(silent=True) or {}
        text = body.get("text", "").strip()
        mode = body.get("mode", "local")
        file_id = body.get("file_id", "").strip()
        profile_key = body.get("profile_key", "").strip()
        inline_override = body.get("deepseek_override") or None
        if not text:
            return _bad("text_required")
        try:
            result = SERVICE.generate_connections_from_text(text=text, mode=mode, file_id=file_id, profile_key=profile_key, inline_deepseek_override=inline_override)
            return _ok(result)
        except Exception as exc:
            SERVICE.log_bus.emit("-", "GENERATE", f"generate_connections_failed reason={exc}", level="error")
            return _bad("generate_connections_failed", 500, detail=str(exc))

    @app.post("/api/generate/save-candidates")
    def api_generate_save_candidates() -> Any:
        body = request.get_json(silent=True) or {}
        entity_type = body.get("type", "").strip().lower()
        file_id = body.get("file_id", "").strip()
        candidates = body.get("candidates", [])
        if entity_type not in ("region", "circuit", "connection"):
            return _bad("invalid_type")
        if not file_id:
            return _bad("file_id_required")
        if not isinstance(candidates, list):
            return _bad("candidates_must_be_list")
        try:
            lane = (body.get("lane") or "local").strip() or "local"
            result = SERVICE.save_generated_candidates(
                entity_type=entity_type, file_id=file_id, candidates=candidates, lane=lane
            )
            return _ok(result)
        except Exception as exc:
            SERVICE.log_bus.emit("-", "GENERATE", f"save_candidates_failed type={entity_type} reason={exc}", level="error")
            return _bad("save_candidates_failed", 500, detail=str(exc))

    # ---- DeepSeek profile management endpoints ----

    @app.get("/api/config/deepseek-profiles")
    def api_deepseek_profiles_list() -> Any:
        try:
            profiles = SERVICE.config_service.list_deepseek_profiles()
            runtime = SERVICE.config_service.get_runtime()
            global_cfg = runtime.get("deepseek", {})
            safe_global = {k: (v if k != "api_key" else ("***" if v else "")) for k, v in global_cfg.items()}
            return _ok({"profiles": profiles, "global": safe_global})
        except Exception as exc:
            return _bad("list_profiles_failed", 500, detail=str(exc))

    @app.post("/api/config/deepseek-profiles")
    def api_deepseek_profiles_save() -> Any:
        body = request.get_json(silent=True) or {}
        profile_key = body.get("profile_key", "").strip()
        profile_cfg = body.get("profile", {})
        if not profile_key:
            return _bad("profile_key_required")
        if not isinstance(profile_cfg, dict):
            return _bad("profile_must_be_object")
        try:
            SERVICE.config_service.save_deepseek_profile(profile_key, profile_cfg)
            return _ok({"saved": profile_key})
        except Exception as exc:
            return _bad("save_profile_failed", 500, detail=str(exc))

    @app.delete("/api/config/deepseek-profiles/<profile_key>")
    def api_deepseek_profiles_delete(profile_key: str) -> Any:
        try:
            SERVICE.config_service.delete_deepseek_profile(profile_key)
            return _ok({"deleted": profile_key})
        except Exception as exc:
            return _bad("delete_profile_failed", 500, detail=str(exc))

    return app
