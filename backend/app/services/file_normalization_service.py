"""File normalization service — generates unified intermediate artifacts.

Architectural boundaries (strictly enforced):
- Reads only resource_files, atlas_resources.
- Writes only file_normalization_runs, file_intermediate_artifacts.
- Does NOT write raw_aal3_region_labels, candidate_brain_regions, final_*, kg_*.
- Does NOT call any LLM.
- Does NOT trigger Raw Parsing, Candidate Generation, or Batch creation.
- NIfTI: metadata only, no voxel loading.
- PDF: metadata only, no OCR.
- Image: metadata only, no content analysis.
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file_normalization import FileIntermediateArtifact, FileNormalizationRun
from app.models.resource_file import ResourceFile
from app.parsers.aal3_xml import parse_aal3_xml
from app.services import resource_file_service
from app.utils.aal3_laterality import extract_region_base_name, infer_laterality
from app.utils.file_meta import normalize_extension
from app.utils.intermediate_normalizers import (
    NORMALIZER_KEY_MACRO_REGION,
    NORMALIZER_KEY_PDF,
    NORMALIZER_KEY_SPREADSHEET,
    ARTIFACT_KIND_PRIORITY,
    normalize_pdf_metadata,
    normalize_spreadsheet_workbook,
)

logger = logging.getLogger(__name__)

NORMALIZER_KEY_AUTO = "auto_v1"
NORMALIZER_KEY_AAL3_XML = "aal3_xml_label_table_v1"
NORMALIZER_KEY_GENERIC = "generic_metadata_v1"
NORMALIZER_VERSION = "v1"

_MAX_PREVIEW_ROWS = 20
_MAX_TEXT_PREVIEW_CHARS = 2000


class FileNormalizationError(Exception):
    pass


class FileNotFoundForNormalization(Exception):
    pass


class FileArchivedForNormalization(Exception):
    pass


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_run_code(file_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    fid_short = str(file_id)[:8]
    return f"fnorm-{fid_short}-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _ext_to_source_format(ext: str) -> str:
    mapping = {
        ".xml": "xml",
        ".json": "json",
        ".csv": "csv",
        ".tsv": "tsv",
        ".txt": "txt",
        ".nii": "nifti",
        ".gz": "nifti",
        ".pdf": "pdf",
        ".xlsx": "xlsx",
        ".xls": "xls",
        ".owl": "ontology",
        ".rdf": "ontology",
        ".ttl": "ontology",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".gif": "image",
        ".bmp": "image",
        ".tiff": "image",
        ".tif": "image",
    }
    return mapping.get(ext.lower(), "unknown")


# ─── per-format normalizers ───────────────────────────────────────────────────

def _normalize_aal3_xml(path: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    """Parse AAL3/FSL-style XML to label_table intermediate."""
    regions = parse_aal3_xml(path)
    rows: list[dict[str, Any]] = []
    for r in regions:
        raw_name = r.get("abbr") or r.get("original_name") or r.get("full_name") or ""
        label_value = r.get("label_index")
        laterality = infer_laterality(raw_name, r.get("hemisphere"))
        rows.append({
            "source_label_id": str(label_value) if label_value is not None else raw_name,
            "label_value": label_value,
            "raw_name": raw_name,
            "en_name": r.get("full_name") or raw_name,
            "cn_name": None,
            "laterality": laterality,
            "region_base_name": extract_region_base_name(raw_name),
            "raw_payload": r,
        })

    content = {
        "schema": "label_table_v1",
        "source_format": "xml",
        "columns": [
            "source_label_id", "label_value", "raw_name",
            "en_name", "cn_name", "laterality", "region_base_name",
        ],
        "provenance": provenance,
        "rows": rows,
    }
    preview = {
        "preview_limit": _MAX_PREVIEW_ROWS,
        "total_rows": len(rows),
        "rows_preview": rows[:_MAX_PREVIEW_ROWS],
        "preview_rows": rows[:_MAX_PREVIEW_ROWS],
    }
    return {
        "artifact_kind": "label_table",
        "source_format": "xml",
        "row_count": len(rows),
        "content_jsonb": content,
        "preview_jsonb": preview,
        "metadata_jsonb": {
            "normalizer": NORMALIZER_KEY_AAL3_XML,
            "parser_hint": "aal3_xml",
            **provenance,
        },
        "warnings_jsonb": [],
    }


def _normalize_json(path: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    """Load JSON and store as json_document intermediate."""
    raw_bytes = path.read_bytes()
    size = len(raw_bytes)
    try:
        parsed = json.loads(raw_bytes)
    except Exception as exc:
        return {
            "artifact_kind": "json_document",
            "source_format": "json",
            "row_count": None,
            "content_jsonb": None,
            "preview_jsonb": None,
            "metadata_jsonb": {"parse_error": str(exc), "file_size_bytes": size, **provenance},
            "warnings_jsonb": [f"JSON parse error: {exc}"],
        }

    is_list = isinstance(parsed, list)
    row_count = len(parsed) if is_list else None
    preview_data = parsed[:_MAX_PREVIEW_ROWS] if is_list else parsed

    return {
        "artifact_kind": "json_document",
        "source_format": "json",
        "row_count": row_count,
        "content_jsonb": {"schema": "json_document_v1", "provenance": provenance, "data": parsed},
        "preview_jsonb": {"total_rows": row_count, "preview_data": preview_data},
        "metadata_jsonb": {"file_size_bytes": size, "is_list": is_list, **provenance},
        "warnings_jsonb": [],
    }


def _normalize_csv_tsv(path: Path, ext: str, provenance: dict[str, Any]) -> dict[str, Any]:
    """Parse CSV/TSV to tabular_data intermediate."""
    delimiter = "\t" if ext == ".tsv" else ","
    source_format = "tsv" if ext == ".tsv" else "csv"
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
        rows = list(reader)
        headers = reader.fieldnames or []
    except Exception as exc:
        warnings.append(f"CSV parse error: {exc}")
        rows, headers = [], []

    content = {
        "schema": "tabular_data_v1",
        "source_format": source_format,
        "columns": list(headers),
        "provenance": provenance,
        "rows": rows,
    }
    preview = {
        "total_rows": len(rows),
        "columns": list(headers),
        "preview_rows": rows[:_MAX_PREVIEW_ROWS],
    }
    return {
        "artifact_kind": "tabular_data",
        "source_format": source_format,
        "row_count": len(rows),
        "content_jsonb": content,
        "preview_jsonb": preview,
        "metadata_jsonb": {"columns": list(headers), "file_size_bytes": path.stat().st_size, **provenance},
        "warnings_jsonb": warnings,
    }


def _normalize_text(path: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    """Read plain text to text_document intermediate."""
    size = path.stat().st_size
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    truncated = len(text) > _MAX_TEXT_PREVIEW_CHARS
    preview_text = text[:_MAX_TEXT_PREVIEW_CHARS] if truncated else text

    return {
        "artifact_kind": "text_document",
        "source_format": "txt",
        "row_count": len(lines),
        "content_jsonb": {
            "schema": "text_document_v1",
            "provenance": provenance,
            "text": text,
            "line_count": len(lines),
        },
        "preview_jsonb": {
            "preview_text": preview_text,
            "is_truncated": truncated,
            "total_chars": len(text),
            "line_count": len(lines),
        },
        "metadata_jsonb": {"file_size_bytes": size, "line_count": len(lines), **provenance},
        "warnings_jsonb": [],
    }


def _normalize_image(path: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    """Extract image file metadata only — no pixel analysis."""
    size = path.stat().st_size
    metadata: dict[str, Any] = {
        "file_size_bytes": size,
        "suffix": path.suffix.lower(),
        **provenance,
    }
    try:
        from PIL import Image  # optional; graceful fallback
        with Image.open(path) as img:
            metadata["width"] = img.width
            metadata["height"] = img.height
            metadata["mode"] = img.mode
            metadata["format"] = img.format
    except Exception:
        metadata["pil_available"] = False

    return {
        "artifact_kind": "image_metadata",
        "source_format": "image",
        "row_count": None,
        "content_jsonb": None,
        "preview_jsonb": None,
        "metadata_jsonb": metadata,
        "warnings_jsonb": [],
    }


def _normalize_nifti(path: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    """Extract NIfTI header metadata only — no voxel loading."""
    size = path.stat().st_size
    metadata: dict[str, Any] = {"file_size_bytes": size, **provenance}
    warnings: list[str] = []
    try:
        import nibabel as nib  # optional; graceful fallback
        header = nib.load(str(path)).header
        metadata["shape"] = list(header.get_data_shape())
        metadata["zooms"] = [float(z) for z in header.get_zooms()]
        metadata["datatype"] = str(header.get_data_dtype())
    except Exception as exc:
        warnings.append(f"NIfTI header read error: {exc}")
        metadata["nibabel_available"] = False

    return {
        "artifact_kind": "nifti_metadata",
        "source_format": "nifti",
        "row_count": None,
        "content_jsonb": None,
        "preview_jsonb": None,
        "metadata_jsonb": metadata,
        "warnings_jsonb": warnings,
    }


def _normalize_binary_or_unsupported(path: Path, ext: str, provenance: dict[str, Any]) -> dict[str, Any]:
    """Fallback — record file metadata for unsupported binary formats."""
    size = path.stat().st_size
    return {
        "artifact_kind": "binary_metadata",
        "source_format": "binary",
        "row_count": None,
        "content_jsonb": None,
        "preview_jsonb": None,
        "metadata_jsonb": {"file_size_bytes": size, "extension": ext, **provenance},
        "warnings_jsonb": [f"No content normalization available for extension '{ext}'"],
    }


def _dispatch_normalizer(
    path: Path,
    ext: str,
    file_type: str | None,
    provenance: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    """Choose normalizer(s) and return (primary_normalizer_key, artifact_dicts)."""
    if ext == ".xml":
        return NORMALIZER_KEY_AAL3_XML, [_normalize_aal3_xml(path, provenance)]
    if ext in {".xlsx", ".xls"}:
        wb_art, macro_art = normalize_spreadsheet_workbook(path, ext, provenance)
        arts = [wb_art]
        key = NORMALIZER_KEY_SPREADSHEET
        if macro_art is not None:
            arts.append(macro_art)
            key = NORMALIZER_KEY_MACRO_REGION
        return key, arts
    if ext == ".pdf":
        return NORMALIZER_KEY_PDF, [normalize_pdf_metadata(path, provenance)]
    if ext == ".json" or file_type == "json":
        return NORMALIZER_KEY_GENERIC, [_normalize_json(path, provenance)]
    if ext in {".csv", ".tsv"}:
        return NORMALIZER_KEY_GENERIC, [_normalize_csv_tsv(path, ext, provenance)]
    if ext == ".txt" or file_type == "text":
        return NORMALIZER_KEY_GENERIC, [_normalize_text(path, provenance)]
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"} or file_type == "image":
        return NORMALIZER_KEY_GENERIC, [_normalize_image(path, provenance)]
    if ext in {".nii", ".nii.gz"} or file_type == "nifti":
        return NORMALIZER_KEY_GENERIC, [_normalize_nifti(path, provenance)]
    if ext in {".owl", ".rdf", ".ttl"} or file_type == "ontology":
        art = _normalize_binary_or_unsupported(path, ext, provenance)
        art["artifact_kind"] = "ontology_document"
        art["source_format"] = "ontology"
        return NORMALIZER_KEY_GENERIC, [art]
    return NORMALIZER_KEY_GENERIC, [_normalize_binary_or_unsupported(path, ext, provenance)]


def _pick_primary_artifact(artifacts: list[FileIntermediateArtifact]) -> FileIntermediateArtifact | None:
    if not artifacts:
        return None
    kind_to_art = {a.artifact_kind: a for a in artifacts}
    for kind in ARTIFACT_KIND_PRIORITY:
        if kind in kind_to_art:
            return kind_to_art[kind]
    return artifacts[0]


# ─── public API ───────────────────────────────────────────────────────────────

async def _get_file_row(session: AsyncSession, file_id: uuid.UUID) -> ResourceFile:
    file_row = await session.get(ResourceFile, file_id)
    if file_row is None or file_row.deleted_at is not None:
        raise FileNotFoundForNormalization(f"file_id={file_id}")
    if file_row.status != "active":
        raise FileArchivedForNormalization(f"file_id={file_id} is not active")
    return file_row


async def normalize_file(
    session: AsyncSession,
    file_id: uuid.UUID,
    *,
    normalizer_key: str = NORMALIZER_KEY_AUTO,
    force: bool = False,
) -> FileNormalizationRun:
    """Trigger normalization for a file. Creates run + artifact records.

    Does NOT write raw_aal3_region_labels, candidate_brain_regions, final_*, kg_*.
    Does NOT call LLM.
    """
    file_row = await _get_file_row(session, file_id)

    if not force:
        existing_art = await get_latest_active_artifact(session, file_id)
        if existing_art is not None:
            run = await session.get(FileNormalizationRun, existing_art.run_id)
            if run is not None and run.status == "succeeded":
                return run

    path = resource_file_service.resolve_download_path(file_row)
    if not path.is_file():
        raise FileNotFoundForNormalization(f"physical file missing for file_id={file_id}")

    ext = normalize_extension(file_row.original_filename)
    source_format = _ext_to_source_format(ext)

    # Capture scalars before flush — safe to use in exception handler after rollback.
    snap_resource_id = file_row.resource_id
    snap_sha256 = file_row.sha256
    snap_original_filename = file_row.original_filename
    snap_file_type = file_row.file_type
    snap_file_role = file_row.file_role

    provenance = {
        "resource_id": str(snap_resource_id),
        "file_id": str(file_id),
        "original_filename": snap_original_filename,
        "sha256": snap_sha256,
        "file_type": snap_file_type,
        "file_role": snap_file_role,
    }

    now = datetime.now(timezone.utc)
    run_code = _make_run_code(file_id)

    run = FileNormalizationRun(
        run_code=run_code,
        resource_id=snap_resource_id,
        file_id=file_id,
        file_sha256=snap_sha256,
        original_filename=snap_original_filename,
        file_type=snap_file_type,
        file_role=snap_file_role,
        normalizer_key=normalizer_key,
        normalizer_version=NORMALIZER_VERSION,
        status="running",
        started_at=now,
    )
    session.add(run)
    await session.flush()

    try:
        dispatch_key, art_dicts = _dispatch_normalizer(
            path=path, ext=ext, file_type=snap_file_type, provenance=provenance
        )
        if normalizer_key == NORMALIZER_KEY_AUTO:
            run.normalizer_key = dispatch_key
        else:
            run.normalizer_key = normalizer_key

        total_warnings = 0
        for art_dict in art_dicts:
            kind = art_dict["artifact_kind"]
            artifact = FileIntermediateArtifact(
                run_id=run.id,
                resource_id=snap_resource_id,
                file_id=file_id,
                artifact_key=f"{file_id!s}-{kind}",
                artifact_kind=kind,
                schema_version="intermediate_v1",
                source_format=art_dict.get("source_format"),
                row_count=art_dict.get("row_count"),
                content_jsonb=art_dict.get("content_jsonb"),
                preview_jsonb=art_dict.get("preview_jsonb"),
                metadata_jsonb=art_dict.get("metadata_jsonb"),
                warnings_jsonb=art_dict.get("warnings_jsonb") or [],
                status="active",
            )
            session.add(artifact)
            total_warnings += len(art_dict.get("warnings_jsonb") or [])

        run.status = "succeeded"
        run.artifact_count = len(art_dicts)
        run.warning_count = total_warnings
        run.finished_at = datetime.now(timezone.utc)

        await session.commit()
        await session.refresh(run)
        return run

    except Exception as exc:
        logger.exception("file normalization failed file_id=%s error=%s", file_id, exc)
        run.status = "failed"
        run.error_message = str(exc)
        run.artifact_count = 0
        run.warning_count = 0
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(run)
        raise FileNormalizationError(str(exc)) from exc


async def auto_normalize_after_upload(
    session: AsyncSession,
    file_id: uuid.UUID,
) -> dict[str, Any]:
    """Best-effort auto-normalization after upload. Never raises; returns summary."""
    try:
        run = await normalize_file(session, file_id, normalizer_key=NORMALIZER_KEY_AUTO, force=False)
        art = await get_latest_active_artifact(session, file_id)
        return {
            "intermediate_status": "ready" if run.status == "succeeded" and art else "failed",
            "latest_normalization_run_id": run.id,
            "latest_intermediate_artifact_id": art.id if art else None,
            "latest_intermediate_kind": art.artifact_kind if art else None,
            "latest_intermediate_row_count": art.row_count if art else None,
            "latest_intermediate_error": run.error_message,
        }
    except FileNotFoundForNormalization as exc:
        return {
            "intermediate_status": "unknown",
            "latest_normalization_run_id": None,
            "latest_intermediate_artifact_id": None,
            "latest_intermediate_kind": None,
            "latest_intermediate_row_count": None,
            "latest_intermediate_error": str(exc),
        }
    except FileArchivedForNormalization as exc:
        return {
            "intermediate_status": "archived",
            "latest_normalization_run_id": None,
            "latest_intermediate_artifact_id": None,
            "latest_intermediate_kind": None,
            "latest_intermediate_row_count": None,
            "latest_intermediate_error": str(exc),
        }
    except FileNormalizationError as exc:
        failed_run_q = (
            select(FileNormalizationRun)
            .where(FileNormalizationRun.file_id == file_id)
            .order_by(desc(FileNormalizationRun.created_at))
            .limit(1)
        )
        failed_run = (await session.execute(failed_run_q)).scalar_one_or_none()
        return {
            "intermediate_status": "failed",
            "latest_normalization_run_id": failed_run.id if failed_run else None,
            "latest_intermediate_artifact_id": None,
            "latest_intermediate_kind": None,
            "latest_intermediate_row_count": None,
            "latest_intermediate_error": str(exc),
        }
    except Exception as exc:
        logger.exception("auto_normalize_after_upload unexpected error file_id=%s", file_id)
        return {
            "intermediate_status": "failed",
            "latest_normalization_run_id": None,
            "latest_intermediate_artifact_id": None,
            "latest_intermediate_kind": None,
            "latest_intermediate_row_count": None,
            "latest_intermediate_error": str(exc),
        }


async def get_intermediate_summary_for_file(
    session: AsyncSession,
    file_id: uuid.UUID,
) -> dict[str, Any]:
    """Lightweight summary fields for ResourceFileRead responses."""
    data = await get_file_intermediate_status(session, file_id)
    status = data.get("status", "missing")
    if status == "ready":
        intermediate_status = "ready"
    elif status == "failed":
        intermediate_status = "failed"
    else:
        intermediate_status = "missing"
    return {
        "intermediate_status": intermediate_status,
        "latest_intermediate_artifact_id": data.get("latest_artifact_id"),
        "latest_normalization_run_id": data.get("latest_run_id"),
        "latest_intermediate_kind": data.get("latest_artifact_kind"),
        "latest_intermediate_row_count": data.get("latest_artifact_row_count"),
        "latest_intermediate_error": data.get("latest_run_error"),
    }


async def get_file_intermediate_status(
    session: AsyncSession,
    file_id: uuid.UUID,
) -> dict:
    """Return intermediate status for a file — safe when no runs/artifacts exist."""
    runs = await list_normalization_runs(session, file_id, limit=20, offset=0)
    latest_run = runs[0] if runs else None

    if latest_run is None:
        return {
            "file_id": str(file_id),
            "status": "missing",
            "has_active_intermediate": False,
            "latest_run_id": None,
            "latest_run_status": None,
            "latest_artifact_kind": None,
            "latest_artifact_id": None,
            "latest_artifact_row_count": None,
            "latest_run_created_at": None,
            "latest_run_error": None,
            "artifact_count": 0,
            "artifacts": [],
            "runs": runs,
        }

    artifacts: list[FileIntermediateArtifact] = []
    latest_art: FileIntermediateArtifact | None = None
    if latest_run.status == "succeeded":
        aq = (
            select(FileIntermediateArtifact)
            .where(
                FileIntermediateArtifact.file_id == file_id,
                FileIntermediateArtifact.status == "active",
            )
            .order_by(desc(FileIntermediateArtifact.created_at))
        )
        artifacts = list((await session.execute(aq)).scalars().all())
        latest_art = _pick_primary_artifact(artifacts)

    has_active = latest_art is not None
    if has_active:
        status = "ready"
    elif latest_run.status == "failed":
        status = "failed"
    else:
        status = "missing"

    return {
        "file_id": str(file_id),
        "status": status,
        "has_active_intermediate": has_active,
        "latest_run_id": latest_run.id,
        "latest_run_status": latest_run.status,
        "latest_artifact_kind": latest_art.artifact_kind if latest_art else None,
        "latest_artifact_id": latest_art.id if latest_art else None,
        "latest_artifact_row_count": latest_art.row_count if latest_art else None,
        "latest_run_created_at": latest_run.created_at,
        "latest_run_error": latest_run.error_message,
        "artifact_count": len(artifacts) if artifacts else latest_run.artifact_count,
        "artifacts": artifacts,
        "runs": runs,
    }


async def list_normalization_runs(
    session: AsyncSession,
    file_id: uuid.UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[FileNormalizationRun]:
    q = (
        select(FileNormalizationRun)
        .where(FileNormalizationRun.file_id == file_id)
        .order_by(desc(FileNormalizationRun.created_at))
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(q)).scalars().all())


async def get_latest_active_artifact(
    session: AsyncSession,
    file_id: uuid.UUID,
) -> FileIntermediateArtifact | None:
    """Return the latest active artifact for a file — used by Raw Parsing fallback logic."""
    run_q = (
        select(FileNormalizationRun)
        .where(
            FileNormalizationRun.file_id == file_id,
            FileNormalizationRun.status == "succeeded",
        )
        .order_by(desc(FileNormalizationRun.created_at))
        .limit(1)
    )
    run = (await session.execute(run_q)).scalar_one_or_none()
    if run is None:
        return None

    art_q = (
        select(FileIntermediateArtifact)
        .where(
            FileIntermediateArtifact.run_id == run.id,
            FileIntermediateArtifact.status == "active",
        )
    )
    arts = list((await session.execute(art_q)).scalars().all())
    return _pick_primary_artifact(arts)
