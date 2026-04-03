from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from flask import Flask, Response, jsonify, render_template, request, send_file

from scripts.pipeline.major_workflow import run_major_load, run_major_preview
from scripts.services.job_manager import JobManager
from scripts.services.file_validation_center import (
    apply_auto_fix as center_apply_auto_fix,
    blocking_files_for_load,
    get_file_content,
    get_file_preview,
    get_file_report,
    list_files,
    remove_file as center_remove_file,
    register_uploaded_file,
    validate_file,
)
from scripts.services.preview_reader import load_preview_bundle
from scripts.services.runtime_config import (
    apply_runtime_env,
    load_runtime_config,
    redact_runtime_config,
    resolve_runtime_deepseek,
    runtime_config_path,
    save_runtime_config,
)
from scripts.services.schema_service import rebuild_schema, schema_stats
from scripts.utils.deepseek_client import DeepSeekClient
from scripts.utils.db import cursor
from scripts.utils.excel_reader import read_xlsx_rows
from scripts.utils.io_utils import ensure_dir
from scripts.utils.runtime import resolve_run_id


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "webapp" / "templates"
STATIC_DIR = ROOT / "webapp" / "static"
UI_RUNS_DIR = ROOT / "artifacts" / "ui_runs"
FILE_CENTER_DIR = ROOT / "artifacts" / "ui_file_center"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
jobs = JobManager()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _pipeline_config(runtime: dict[str, Any], path: Path) -> Path:
    use_deepseek = bool(runtime.get("pipeline", {}).get("use_deepseek", True))
    if use_deepseek and not str(runtime.get("deepseek", {}).get("api_key", "")).strip():
        use_deepseek = False
    payload = {
        "excel": runtime.get("excel", {}),
        "llm": {
            "use_deepseek": use_deepseek,
            "batch_size": int(runtime.get("pipeline", {}).get("batch_size", 60)),
        },
        "pipeline": {
            "load_scope": runtime.get("pipeline", {}).get("load_scope", "all_mappable"),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _db_ready() -> dict[str, Any]:
    info = {"connected": False, "error": "", "stats": {}}
    try:
        with cursor() as (_, cur):
            cur.execute("select 1")
        info["connected"] = True
        info["stats"] = schema_stats()
    except Exception as exc:
        info["error"] = str(exc)
    return info


def _preview_root(run_id: str) -> Path:
    root = ensure_dir(UI_RUNS_DIR / run_id)
    return root


def _apply_runtime_for_uploaded(record: dict[str, Any]) -> dict[str, Any]:
    runtime = load_runtime_config()
    file_type = str(record.get("file_type") or "").lower()
    original_path = str(record.get("original_path") or "")
    changed = False

    if file_type == "xlsx":
        runtime["excel"] = runtime.get("excel", {})
        runtime["excel"]["path"] = original_path
        changed = True
    if file_type in {"rdf", "owl", "xml"}:
        runtime["ontology"] = runtime.get("ontology", {})
        runtime["ontology"]["path"] = original_path
        changed = True

    if changed:
        save_runtime_config(runtime)
    return runtime


def _find_file_id_by_original_path(path: str) -> str:
    listed = list_files(FILE_CENTER_DIR).get("files", [])
    target = str(Path(path).resolve()) if path else ""
    for item in listed:
        current = str(Path(str(item.get("original_path") or "")).resolve())
        if current == target:
            return str(item.get("file_id") or "")
    return ""


def _validate_excel_with_deepseek(
    rows: list[dict[str, str]],
    headers: list[str],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    resolved_runtime, resolved_meta = resolve_runtime_deepseek(runtime, None)
    requested_use_deepseek = bool(resolved_runtime.get("pipeline", {}).get("use_deepseek", True))
    deepseek_cfg = resolved_runtime.get("deepseek", {}) if isinstance(resolved_runtime.get("deepseek"), dict) else {}
    has_deepseek_key = bool(str(deepseek_cfg.get("api_key", "")).strip())
    effective_use_deepseek = requested_use_deepseek and has_deepseek_key

    base = {
        "requested_use_deepseek": requested_use_deepseek,
        "effective_use_deepseek": effective_use_deepseek,
        "status": "skipped",
        "reason": "",
        "report": {},
        "source": resolved_meta.get("source", "global"),
    }

    if not requested_use_deepseek:
        base["reason"] = "pipeline.use_deepseek=false"
        return base
    if not has_deepseek_key:
        base["reason"] = "DEEPSEEK_API_KEY is empty"
        return base
    print(
        f"[CHECK] deepseek config source={resolved_meta.get('source', 'global')} "
        f"model={deepseek_cfg.get('model', '')} baseUrl={deepseek_cfg.get('base_url', '')}"
    )

    # Keep the prompt bounded while preserving whole-table preview for UI.
    sample_rows = rows[: min(len(rows), 300)]
    payload = {
        "table_name": "major_brain_region_excel",
        "total_rows": len(rows),
        "headers": headers,
        "sample_rows": sample_rows,
    }
    system_prompt = (
        "You are a strict data quality reviewer for a brain-region Excel table. "
        "Return JSON only."
    )
    user_prompt = (
        "Validate the table quality and consistency for downstream extraction.\n"
        "Check: required columns, duplicate rows, possible invalid hemisphere naming, "
        "mixed language anomalies, suspicious empty values, and obvious typo risks.\n"
        "Return strict JSON with keys:\n"
        "- status: one of pass|warning|fail\n"
        "- score: number 0..100\n"
        "- summary_cn: short Chinese summary\n"
        "- required_columns_missing: string[]\n"
        "- duplicate_candidates: object[]\n"
        "- warnings: object[]\n"
        "- must_fix: object[]\n"
        "- suggested_mapping: object\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        client = DeepSeekClient(
            base_url=str(deepseek_cfg.get("base_url", "")).strip() or None,
            model=str(deepseek_cfg.get("model", "")).strip() or None,
            api_key=str(deepseek_cfg.get("api_key", "")).strip() or None,
        )
        report = client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1, max_tokens=2200)
    except Exception as exc:
        base["status"] = "error"
        base["reason"] = str(exc)
        return base

    base["status"] = "ok"
    base["report"] = report if isinstance(report, (dict, list)) else {"raw": report}
    return base


def _is_structured_input(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {".xlsx", ".csv", ".tsv", ".json", ".jsonl"}


def _is_major_extract_supported(path: str) -> bool:
    return Path(path).suffix.lower() == ".xlsx"


def _is_ontology_type(file_type: str) -> bool:
    return str(file_type or "").lower() in {"owl", "rdf", "ttl", "jsonld", "xml"}


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.after_request
def disable_cache(response: Response) -> Response:
    # Local workbench should always show the newest frontend changes after restart.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/api/status")
def api_status() -> Any:
    runtime = load_runtime_config()
    apply_runtime_env(runtime)
    excel_path = Path(str(runtime.get("excel", {}).get("path", "")))
    ontology_path = Path(str(runtime.get("ontology", {}).get("path", "")))
    return jsonify(
        {
            "runtime_config_path": str(runtime_config_path()),
            "config": redact_runtime_config(runtime),
            "excel_exists": excel_path.exists(),
            "ontology_exists": ontology_path.exists(),
            "database": _db_ready(),
            "file_center": list_files(FILE_CENTER_DIR).get("stats", {}),
        }
    )


@app.post("/api/config")
def api_save_config() -> Any:
    payload = request.get_json(silent=True) or {}
    current = load_runtime_config()
    merged = _deep_merge(current, payload)
    target = save_runtime_config(merged)
    return jsonify({"saved": True, "path": str(target), "config": redact_runtime_config(merged)})


@app.post("/api/files/preview-excel")
def api_preview_excel() -> Any:
    payload = request.get_json(silent=True) or {}
    runtime = load_runtime_config()
    excel_cfg = _deep_merge(runtime.get("excel", {}), payload.get("excel", {}))
    path = Path(str(excel_cfg.get("path", "")))
    rows = read_xlsx_rows(path, sheet_index=int(excel_cfg.get("sheet_index", 1)), header_row=int(excel_cfg.get("header_row", 1)))
    headers = list(rows[0].keys()) if rows else []
    return jsonify({"path": str(path), "headers": headers, "total_rows": len(rows), "rows": rows})


@app.post("/api/files/validate-excel")
def api_validate_excel() -> Any:
    payload = request.get_json(silent=True) or {}
    runtime = load_runtime_config()
    runtime = _deep_merge(runtime, payload.get("runtime_overrides", {}))
    apply_runtime_env(runtime)

    excel_cfg = _deep_merge(runtime.get("excel", {}), payload.get("excel", {}))
    path = Path(str(excel_cfg.get("path", "")))
    matched_file_id = _find_file_id_by_original_path(str(path))
    if matched_file_id:
        report = validate_file(matched_file_id, runtime, FILE_CENTER_DIR)
        return jsonify(
            {
                "path": str(path),
                "headers": [],
                "total_rows": int(report.get("normalized_stats", {}).get("output_rows", 0)),
                "validation": {
                    "status": "ok",
                    "report": report,
                    "requested_use_deepseek": report.get("validation_trace", {}).get("llm_initial", {}).get("requested_use_deepseek", False),
                    "effective_use_deepseek": report.get("validation_trace", {}).get("llm_initial", {}).get("effective_use_deepseek", False),
                },
            }
        )

    rows = read_xlsx_rows(
        path,
        sheet_index=int(excel_cfg.get("sheet_index", 1)),
        header_row=int(excel_cfg.get("header_row", 1)),
    )
    headers = list(rows[0].keys()) if rows else []
    validation = _validate_excel_with_deepseek(rows=rows, headers=headers, runtime=runtime)
    return jsonify(
        {
            "path": str(path),
            "headers": headers,
            "total_rows": len(rows),
            "validation": validation,
        }
    )


@app.post("/api/files/upload-excel")
def api_upload_excel() -> Any:
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "file_missing"}), 400
    record = register_uploaded_file(file, FILE_CENTER_DIR)
    _apply_runtime_for_uploaded(record)
    return jsonify({"saved": True, "path": record.get("original_path"), "file": record})


@app.post("/api/files/upload-ontology")
def api_upload_ontology() -> Any:
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "file_missing"}), 400
    record = register_uploaded_file(file, FILE_CENTER_DIR)
    _apply_runtime_for_uploaded(record)
    return jsonify({"saved": True, "path": record.get("original_path"), "file": record})


@app.post("/api/files/upload")
def api_files_upload() -> Any:
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "file_missing"}), 400
    try:
        record = register_uploaded_file(file, FILE_CENTER_DIR)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    runtime = _apply_runtime_for_uploaded(record)
    apply_runtime_env(runtime)
    auto_validation: dict[str, Any] = {"triggered": False, "status": "skipped", "reason": ""}
    if not _is_ontology_type(str(record.get("file_type") or "")):
        auto_validation["triggered"] = True
        try:
            report = validate_file(str(record.get("file_id") or ""), runtime, FILE_CENTER_DIR)
            auto_validation.update(
                {
                    "status": "ok",
                    "label": report.get("overall_label"),
                    "score": report.get("score"),
                    "effective_use_deepseek": report.get("validation_trace", {}).get("llm_initial", {}).get("effective_use_deepseek", False),
                    "source": report.get("validation_trace", {}).get("llm_initial", {}).get("config_source", "global"),
                    "request_sent": report.get("validation_trace", {}).get("llm_initial", {}).get("request_sent", False),
                    "response_received": report.get("validation_trace", {}).get("llm_initial", {}).get("response_received", False),
                    "http_status": report.get("validation_trace", {}).get("llm_initial", {}).get("http_status"),
                    "elapsed_ms": report.get("validation_trace", {}).get("llm_initial", {}).get("elapsed_ms", 0),
                }
            )
        except Exception as exc:
            auto_validation.update({"status": "error", "reason": str(exc)})

    listed = list_files(FILE_CENTER_DIR)
    file_id = str(record.get("file_id") or "")
    latest = next((item for item in listed.get("files", []) if str(item.get("file_id") or "") == file_id), record)
    return jsonify({"saved": True, "file": latest, "stats": listed.get("stats", {}), "auto_validation": auto_validation})


@app.get("/api/files/list")
def api_files_list() -> Any:
    return jsonify(list_files(FILE_CENTER_DIR))


def _remove_file_and_list(file_id: str) -> Any:
    try:
        removed = center_remove_file(file_id, FILE_CENTER_DIR)
    except KeyError:
        return jsonify({"error": "file_not_found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    listed = list_files(FILE_CENTER_DIR)
    return jsonify({"removed": removed, "stats": listed.get("stats", {}), "files": listed.get("files", [])})


@app.route("/api/files/<file_id>", methods=["DELETE"])
def api_files_remove(file_id: str) -> Any:
    return _remove_file_and_list(file_id)


@app.post("/api/files/validate")
def api_files_validate() -> Any:
    payload = request.get_json(silent=True) or {}
    file_id = str(payload.get("file_id") or "").strip()
    if not file_id:
        return jsonify({"error": "file_id_missing"}), 400

    runtime = load_runtime_config()
    runtime = _deep_merge(runtime, payload.get("runtime_overrides", {}))
    deepseek_override = payload.get("deepseek_override")
    runtime, resolved_meta = resolve_runtime_deepseek(runtime, deepseek_override if isinstance(deepseek_override, dict) else None)
    if isinstance(deepseek_override, dict):
        runtime["_task_deepseek_override"] = deepseek_override
    apply_runtime_env(runtime)
    print(
        f"[CHECK] deepseek config source={resolved_meta.get('source', 'global')} "
        f"model={resolved_meta.get('model', '')} baseUrl={resolved_meta.get('base_url', '')}"
    )
    try:
        report = validate_file(file_id, runtime, FILE_CENTER_DIR)
    except KeyError:
        return jsonify({"error": "file_not_found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(
        {
            "file_id": file_id,
            "validation_report": report,
            "deepseek_config": {
                "source": resolved_meta.get("source", "global"),
                "enabled": bool(resolved_meta.get("enabled", False)),
                "model": resolved_meta.get("model", ""),
                "base_url": resolved_meta.get("base_url", ""),
            },
        }
    )


@app.post("/api/files/apply-auto-fix")
def api_files_apply_auto_fix() -> Any:
    payload = request.get_json(silent=True) or {}
    file_id = str(payload.get("file_id") or "").strip()
    if not file_id:
        return jsonify({"error": "file_id_missing"}), 400
    try:
        result = center_apply_auto_fix(file_id, FILE_CENTER_DIR)
    except KeyError:
        return jsonify({"error": "file_not_found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"file_id": file_id, **result})


@app.get("/api/files/<file_id>/report")
def api_files_report(file_id: str) -> Any:
    try:
        result = get_file_report(file_id, FILE_CENTER_DIR)
    except KeyError:
        return jsonify({"error": "file_not_found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.get("/api/files/<file_id>/preview")
def api_files_preview(file_id: str) -> Any:
    try:
        page = int(request.args.get("page", 1))
    except Exception:
        page = 1
    try:
        page_size = int(request.args.get("page_size", 120))
    except Exception:
        page_size = 120
    view = str(request.args.get("view", "auto"))
    try:
        result = get_file_preview(
            file_id=file_id,
            root=FILE_CENTER_DIR,
            page=page,
            page_size=page_size,
            view=view,
        )
    except KeyError:
        return jsonify({"error": "file_not_found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.get("/api/files/<file_id>/content")
def api_files_content(file_id: str) -> Any:
    try:
        content = get_file_content(file_id=file_id, root=FILE_CENTER_DIR)
    except KeyError:
        return jsonify({"error": "file_not_found"}), 404
    path = Path(str(content.get("path") or ""))
    if not content.get("exists") or not path.exists():
        return jsonify({"error": "file_missing"}), 404
    return send_file(
        path,
        mimetype=str(content.get("mime_type") or "application/octet-stream"),
        as_attachment=False,
        download_name=str(content.get("filename") or path.name),
    )


@app.post("/api/schema/rebuild")
def api_schema_rebuild() -> Any:
    job_id = jobs.create_job("schema_rebuild")

    def worker() -> dict[str, Any]:
        runtime = load_runtime_config()
        apply_runtime_env(runtime)
        jobs.add_log(job_id, "schema rebuild started")
        result = rebuild_schema(callback=lambda ev: jobs.on_progress(job_id, ev))
        jobs.add_log(job_id, f"schema rebuild completed: {result}")
        return result

    jobs.run_async(job_id, worker)
    return jsonify({"job_id": job_id})


def _start_major_preview(payload: dict[str, Any], endpoint: str) -> Any:
    runtime = load_runtime_config()
    runtime = _deep_merge(runtime, payload.get("runtime_overrides", {}))
    deepseek_override = payload.get("deepseek_override")
    runtime, resolved_meta = resolve_runtime_deepseek(runtime, deepseek_override if isinstance(deepseek_override, dict) else None)
    if isinstance(deepseek_override, dict):
        runtime["_task_deepseek_override"] = deepseek_override
    if payload.get("save_runtime_overrides"):
        save_runtime_config(runtime)
    apply_runtime_env(runtime)
    print(
        f"[CHECK] deepseek config source={resolved_meta.get('source', 'global')} "
        f"model={resolved_meta.get('model', '')} baseUrl={resolved_meta.get('base_url', '')}"
    )

    requested_run_id = str(payload.get("run_id") or "").strip()
    run_id = resolve_run_id(requested_run_id if requested_run_id else "")
    excel_path = str(payload.get("excel_path") or runtime.get("excel", {}).get("path", "")).strip()
    if not _is_structured_input(excel_path):
        return (
            jsonify(
                {
                    "error": "unstructured_input_not_supported_for_extract",
                    "message": "Start Extraction only supports structured file input (xlsx/csv/tsv/json/jsonl).",
                    "excel_path": excel_path,
                }
            ),
            400,
        )
    if not _is_major_extract_supported(excel_path):
        return (
            jsonify(
                {
                    "error": "structured_input_not_supported_yet",
                    "message": "Current major extraction runtime supports .xlsx only; other structured files can be previewed and validated.",
                    "excel_path": excel_path,
                }
            ),
            400,
        )
    requested_use_deepseek = bool(runtime.get("pipeline", {}).get("use_deepseek", True))
    has_deepseek_key = bool(str(runtime.get("deepseek", {}).get("api_key", "")).strip())
    effective_use_deepseek = requested_use_deepseek and has_deepseek_key
    preview_root = _preview_root(run_id)
    pipeline_config_path = _pipeline_config(runtime, preview_root / "runtime_pipeline.yaml")
    job_id = jobs.create_job("major_preview", meta={"run_id": run_id, "preview_root": str(preview_root)})

    def worker() -> dict[str, Any]:
        apply_runtime_env(runtime)
        if requested_use_deepseek and not has_deepseek_key:
            jobs.add_log(job_id, "DEEPSEEK_API_KEY is empty; fallback to use_deepseek=false for this run.")
        jobs.add_log(job_id, f"preview started run_id={run_id}")
        summary = run_major_preview(
            input_path=excel_path,
            output_path=preview_root,
            config_path=str(pipeline_config_path),
            run_id=run_id,
            callback=lambda ev: jobs.on_progress(job_id, ev),
        )
        jobs.add_log(job_id, "preview completed")
        return {"summary": summary, "preview_root": str(preview_root)}

    jobs.run_async(job_id, worker)
    return jsonify(
        {
            "job_id": job_id,
            "run_id": run_id,
            "preview_root": str(preview_root),
            "endpoint": endpoint,
            "use_deepseek_requested": requested_use_deepseek,
            "use_deepseek_effective": effective_use_deepseek,
            "deepseek_config_source": resolved_meta.get("source", "global"),
        }
    )


@app.post("/api/preview/major")
def api_preview_major() -> Any:
    payload = request.get_json(silent=True) or {}
    return _start_major_preview(payload, "/api/preview/major")


@app.post("/api/extract/major/start")
def api_extract_major_start() -> Any:
    payload = request.get_json(silent=True) or {}
    return _start_major_preview(payload, "/api/extract/major/start")


@app.post("/api/jobs/<job_id>/load")
def api_load_from_preview(job_id: str) -> Any:
    blocked_files = blocking_files_for_load(FILE_CENTER_DIR)
    if blocked_files:
        return (
            jsonify(
                {
                    "error": "load_blocked_by_validation",
                    "block_reason": "There are FAIL-labeled files in validation center.",
                    "blocked_files": blocked_files,
                }
            ),
            400,
        )

    preview_job = jobs.get_job(job_id)
    if preview_job.get("job_type") != "major_preview":
        return jsonify({"error": "job_type_not_supported"}), 400
    if preview_job.get("status") != "succeeded":
        return jsonify({"error": "preview_not_ready"}), 400

    result = preview_job.get("result") or {}
    preview_root = (
        result.get("preview_root")
        or preview_job.get("meta", {}).get("preview_root")
        or str(_preview_root(preview_job.get("meta", {}).get("run_id", "")))
    )
    run_id = f"{preview_job.get('meta', {}).get('run_id', 'run')}_load"
    runtime = load_runtime_config()
    apply_runtime_env(runtime)
    pipeline_config_path = _pipeline_config(runtime, Path(preview_root) / "runtime_pipeline.yaml")

    load_job_id = jobs.create_job("major_load", meta={"preview_job_id": job_id, "preview_root": str(preview_root)})

    def worker() -> dict[str, Any]:
        apply_runtime_env(runtime)
        jobs.add_log(load_job_id, f"load started preview_root={preview_root}")
        summary = run_major_load(
            preview_root=preview_root,
            config_path=str(pipeline_config_path),
            run_id=run_id,
            callback=lambda ev: jobs.on_progress(load_job_id, ev),
        )
        jobs.add_log(load_job_id, "load completed")
        return {"summary": summary, "preview_root": str(preview_root)}

    jobs.run_async(load_job_id, worker)
    return jsonify({"job_id": load_job_id, "preview_root": str(preview_root)})


@app.get("/api/jobs/<job_id>")
def api_get_job(job_id: str) -> Any:
    try:
        job = jobs.get_job(job_id)
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(job)


@app.get("/api/jobs/<job_id>/preview")
def api_job_preview(job_id: str) -> Any:
    try:
        job = jobs.get_job(job_id)
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404

    result = job.get("result") or {}
    preview_root = (
        result.get("preview_root")
        or job.get("meta", {}).get("preview_root")
        or ""
    )
    if not preview_root:
        return jsonify({"error": "preview_root_not_found"}), 400
    root = Path(preview_root)
    if not root.exists():
        return jsonify({"error": "preview_root_missing"}), 404

    bundle = load_preview_bundle(root)
    return jsonify(bundle)


@app.post("/api/crawler/jobs")
def api_crawler_job_create() -> Any:
    payload = request.get_json(silent=True) or {}
    return jsonify(
        {
            "status": "deferred",
            "module": "crawler",
            "message": "Crawler is deferred in V2.1 and is not executed in current pipeline.",
            "request": payload,
        }
    )


@app.get("/api/crawler/jobs/<job_id>")
def api_crawler_job_get(job_id: str) -> Any:
    return jsonify(
        {
            "job_id": job_id,
            "status": "deferred",
            "module": "crawler",
            "message": "Crawler is deferred in V2.1 and has no runtime job state.",
        }
    )


def run_dashboard(host: str = "127.0.0.1", port: int = 8899) -> None:
    ensure_dir(UI_RUNS_DIR)
    ensure_dir(runtime_config_path().parent)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_dashboard()
