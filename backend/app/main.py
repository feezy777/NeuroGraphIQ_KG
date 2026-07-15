"""Minimal API shell — workbench routes removed; rebuild per docs/NEUROGRAPHIQ_VIBE_CODING_GUIDE.md."""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.routers import (
    candidate,
    candidate_pool,
    connection_pool,
    database_admin,
    file_normalization,
    final_db_query,
    human_review,
    import_batches,
    llm_extraction,
    llm_field_completion,
    llm_circuit_connection_extraction,
    llm_circuit_extraction,
    llm_composite_workflow,
    kg_graph,
    final_kg,
    final_macro_clinical_browser,
    final_macro_clinical_promotion,
    final_kg_export,
    mirror_kg,
    mirror_cross_validation,
    mirror_dual_model_verification,
    mirror_macro_clinical,
    mirror_promotion,
    mirror_review,
    mirror_validation,
    promotion,
    raw_parsing,
    resource_files,
    resources,
    rule_validation,
    settings,
    symptom_query,
    system_admin,
    workbench_pipeline,
    workspace_files,
)

_settings = get_settings()
_log = logging.getLogger(__name__)

BACKEND_VERSION = "4.7.0-mvp2-composite-workflow-stabilization"

app = FastAPI(
    title="NeuroGraphIQ KG V3",
    description="脑图谱知识图谱 — 旧工作台已清理，按架构文档重建中",
    version=BACKEND_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db_error_detail(exc: BaseException) -> dict[str, str]:
    message = str(exc) or exc.__class__.__name__
    hint = "Check PostgreSQL is running and DATABASE_URL is correct."
    if sys.platform == "win32" and "ProactorEventLoop" in message:
        hint = (
            "On Windows, start the backend with "
            "`backend/.venv/Scripts/python.exe run_server.py` (not raw uvicorn)."
        )
    return {
        "code": "DATABASE_UNAVAILABLE",
        "message": "Database connection failed.",
        "hint": hint,
        "error": message[:500],
    }


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    _log.exception("[api][database]")
    return JSONResponse(status_code=503, content={"detail": _db_error_detail(exc)})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_landing_page():
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"/>
<title>NeuroGraphIQ KG V3</title>
<style>
body{font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;line-height:1.55}
code{background:#eee;padding:.1rem .35rem;border-radius:4px}
a{color:#1677ff}
</style></head><body>
<h1>NeuroGraphIQ KG V3 · 后端占位</h1>
<p>MVP 1：Resource Registry + File Upload + Import Batch + AAL3 Raw Parsing + Candidate DB + Rule Validation + Human Review + Promotion + Final DB Query 已上线。</p>
<ul>
<li><strong>健康检查</strong>：<a href="/api/health">/api/health</a></li>
<li><strong>导入批次</strong>：<a href="/api/import-batches">/api/import-batches</a></li>
<li><strong>Raw Parsing</strong>：<a href="/api/raw-parsing/options">/api/raw-parsing/options</a></li>
<li><strong>Candidate DB</strong>：<a href="/api/candidates/options">/api/candidates/options</a></li>
<li><strong>Rule Validation</strong>：<a href="/api/rule-validation/options">/api/rule-validation/options</a></li>
<li><strong>Human Review</strong>：<a href="/api/human-review/options">/api/human-review/options</a></li>
<li><strong>Promotion</strong>：<a href="/api/promotion/options">/api/promotion/options</a></li>
<li><strong>Final DB Query</strong>：<a href="/api/final-regions/options">/api/final-regions/options</a></li>
<li><strong>LLM Extraction</strong>：<a href="/api/llm-extraction/options">/api/llm-extraction/options</a></li>
<li><strong>Swagger</strong>：<a href="/api/docs">/api/docs</a></li>
</ul>
</body></html>"""


@app.on_event("startup")
async def log_startup_version() -> None:
    import logging

    log = logging.getLogger("uvicorn.error")
    log.info("[startup] NeuroGraphIQ backend version=%s", BACKEND_VERSION)
    log.info(
        "[startup] registered llm_field_completion router prefix=/api/llm-extraction/field-completion"
    )


@app.get("/api/health", tags=["Health"])
async def health_check():
    from app.services import database_admin_service

    db_info = await database_admin_service.get_connection_status()
    return {
        "status": "ok" if db_info["connected"] else "degraded",
        "version": BACKEND_VERSION,
        "database": {
            "name": db_info["current_database"],
            "connected": db_info["connected"],
            "schema_status": db_info["schema_status"].value,
            "host": db_info["host"],
            "port": db_info["port"],
        },
        "modules": {
            "resource_registry": "active",
            "file_upload": "active",
            "import_batch": "active",
            "raw_parsing_aal3": "active",
            "candidate_db": "active",
            "rule_validation": "active",
            "human_review": "active",
            "promotion": "active",
            "final_db_query": "active",
            "llm_extraction": "active",
            "mirror_kg": "active",
            "mirror_macro_clinical": "active",
            "settings": "active",
            "database_admin": "active",
        },
    }


app.include_router(file_normalization.router)
app.include_router(workspace_files.router)
app.include_router(resources.router, prefix="/api/resources", tags=["Resource Registry"])
app.include_router(
    resource_files.resource_router, prefix="/api/resources", tags=["Resource Files"]
)
app.include_router(resource_files.files_router, prefix="/api/files", tags=["Files"])
app.include_router(
    import_batches.router, prefix="/api/import-batches", tags=["Import Batches"]
)
app.include_router(raw_parsing.router, prefix="/api/raw-parsing", tags=["Raw Parsing"])
app.include_router(
    raw_parsing.batch_router, prefix="/api/import-batches", tags=["Import Batch Parsing"]
)
app.include_router(
    raw_parsing.parse_run_router, prefix="/api/raw-parse-runs", tags=["Raw Parse Runs"]
)
app.include_router(candidate.router, prefix="/api/candidates", tags=["Candidate DB"])
app.include_router(
    candidate.batch_router, prefix="/api/import-batches", tags=["Import Batch Candidates"]
)
app.include_router(
    candidate.gen_run_router, prefix="/api/candidate-runs", tags=["Candidate Generation Runs"]
)
app.include_router(
    rule_validation.router, prefix="/api/rule-validation", tags=["Rule Validation"]
)
app.include_router(
    rule_validation.candidate_router, prefix="/api/candidates", tags=["Candidate Rule Validation"]
)
app.include_router(human_review.router, prefix="/api/human-review", tags=["Human Review"])
app.include_router(
    human_review.candidate_router, prefix="/api/candidates", tags=["Candidate Human Review"]
)
app.include_router(promotion.router, prefix="/api/promotion", tags=["Promotion"])
app.include_router(
    promotion.candidate_router, prefix="/api/candidates", tags=["Candidate Promotion"]
)
app.include_router(
    candidate_pool.router, prefix="/api/candidates", tags=["Candidate Pools"]
)
app.include_router(
    connection_pool.router, prefix="/api/connection-pools", tags=["Connection Pools"]
)
app.include_router(final_db_query.router, prefix="/api/final-regions", tags=["Final DB Query"])
app.include_router(
    llm_extraction.router, prefix="/api/llm-extraction", tags=["LLM Extraction"]
)
app.include_router(
    llm_field_completion.router,
    prefix="/api/llm-extraction/field-completion",
    tags=["Field Completion"],
)
app.include_router(
    llm_circuit_extraction.router,
    prefix="/api/llm-extraction/circuit-extraction",
    tags=["Circuit Extraction"],
)
app.include_router(
    llm_circuit_connection_extraction.router,
    prefix="/api/llm-extraction/circuit-connection-extraction",
    tags=["Circuit Connection Extraction"],
)
app.include_router(
    llm_composite_workflow.router, prefix="/api/llm-extraction", tags=["LLM Composite Workflow"]
)
app.include_router(
    kg_graph.router, prefix="/api/kg/graph", tags=["Knowledge Graph"]
)
app.include_router(
    llm_extraction.candidate_router, prefix="/api/candidates", tags=["Candidate LLM Extraction"]
)
app.include_router(mirror_kg.router, prefix="/api/mirror-kg", tags=["Mirror KG"])
app.include_router(
    mirror_dual_model_verification.router,
    prefix="/api/mirror-kg/dual-model-verification",
    tags=["Mirror KG Dual Model Verification"],
)
app.include_router(
    mirror_cross_validation.router,
    prefix="/api/mirror-kg/circuit-projection-cross-validation",
    tags=["Mirror KG Cross Validation"],
)
app.include_router(
    mirror_macro_clinical.router, prefix="/api/mirror-kg", tags=["Mirror KG Macro Clinical"]
)
app.include_router(
    mirror_validation.router, prefix="/api/mirror-kg/validation", tags=["Mirror KG Validation"]
)
app.include_router(
    mirror_review.router, prefix="/api/mirror-kg/review", tags=["Mirror KG Review"]
)
app.include_router(
    mirror_promotion.router, prefix="/api/mirror-kg/promotion", tags=["Mirror KG Promotion"]
)
app.include_router(final_kg.router, prefix="/api/final-kg", tags=["Final KG"])
app.include_router(
    final_macro_clinical_promotion.router,
    prefix="/api/final-macro-clinical",
    tags=["Final Macro Clinical Promotion"],
)
app.include_router(
    final_macro_clinical_browser.router,
    prefix="/api/final-macro-clinical",
    tags=["Final Macro Clinical Browser"],
)
app.include_router(
    final_kg_export.router,
    prefix="/api/final-macro-clinical",
    tags=["Final KG Export"],
)
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(database_admin.router, prefix="/api/database", tags=["Database Admin"])
app.include_router(
    workbench_pipeline.router, prefix="/api/workbench", tags=["Workbench Pipeline"]
)
app.include_router(
    symptom_query.router, prefix="/api/symptom-query", tags=["Symptom Query"]
)
app.include_router(
    system_admin.router, prefix="/api/system", tags=["System Admin"]
)
