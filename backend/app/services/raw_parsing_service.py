"""Raw Parsing for AAL3 and Macro96 — extract source data to raw tables only.

Does NOT create candidates, write final_* / kg_*, call LLM, or parse NIfTI voxels.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_batch import ImportBatch
from app.models.raw_macro96 import RawMacro96RegionRow
from app.models.raw_parsing import RawAal3RegionLabel, RawParseRun
from app.models.resource_file import ResourceFile
from app.parsers.aal3_xml import parse_aal3_xml
from app.parsers.macro96_xlsx import (
    PARSER_KEY as PARSER_KEY_MACRO96_XLSX,
    PARSER_VERSION as PARSER_VERSION_MACRO96,
    Macro96IntermediateInvalidError,
    Macro96ParseError,
    parse_macro96_table_from_intermediate,
)
from app.schemas.import_batch import BatchEventType, ImportBatchStatus
from app.schemas.macro96_raw_parsing import ParseMacro96Response
from app.services import file_normalization_service, import_batch_service, resource_file_service, resource_service
from app.utils.aal3_raw_adapter import (
    DEFAULT_PARSER_VERSION,
    PARSER_KEY_AAL3_XML,
    xml_regions_to_raw_labels,
)
from app.utils.file_meta import normalize_extension

logger = logging.getLogger(__name__)

_LABEL_EXTENSIONS = frozenset({".xml"})
_NON_PARSABLE_EXTENSIONS = frozenset({".nii", ".nii.gz"})

_AAL3_INCOMPATIBLE_EXTENSIONS = frozenset({
    ".xlsx", ".xls", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".nii", ".nii.gz",
})
_AAL3_INCOMPATIBLE_FILE_TYPES = frozenset({
    "spreadsheet", "pdf", "binary_metadata", "image",
})
_AAL3_INCOMPATIBLE_INTERMEDIATE_KINDS = frozenset({
    "macro_region_table", "spreadsheet_workbook", "pdf_metadata", "tabular_data",
    "text_document", "image_metadata", "nifti_metadata", "binary_metadata",
    "ontology_document", "json_document",
})


class BatchNotRunnableError(Exception):
    pass


class BoundFileNotActiveError(BatchNotRunnableError):
    """Raised when a bound label file exists but is not active."""

    def __init__(
        self,
        file_id: uuid.UUID,
        file_status: str,
        batch_id: uuid.UUID,
    ) -> None:
        self.file_id = file_id
        self.file_status = file_status
        self.batch_id = batch_id
        super().__init__(
            "Bound file is not active. "
            f"file_id={file_id}, status={file_status}, batch_id={batch_id}. "
            "Reactivate the file in File Center or create a new batch with an active AAL3 XML file."
        )


def bound_file_not_active_detail(exc: BoundFileNotActiveError) -> dict[str, str]:
    return {
        "code": "BOUND_FILE_NOT_ACTIVE",
        "message": "Bound file is not active and cannot be parsed.",
        "file_id": str(exc.file_id),
        "file_status": exc.file_status,
        "batch_id": str(exc.batch_id),
        "suggestion": (
            "Reactivate the file in File Center or create a new batch with an active AAL3 XML file."
        ),
    }


class NoLabelFileError(Exception):
    pass


class NoAal3XmlLabelDictionaryError(Exception):
    """Raised when batch has no file that can produce AAL3 XML label dictionary output."""

    def __init__(
        self,
        batch_id: uuid.UUID,
        parser_key: str,
        bound_files: list[dict[str, object]],
        *,
        message: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        self.batch_id = batch_id
        self.parser_key = parser_key
        self.bound_files = bound_files
        self.message = message or (
            "No active AAL3 XML label dictionary in this batch produced parse output."
        )
        self.suggestion = suggestion or (
            "Create a new batch with an active AAL3 XML label dictionary file, "
            "or use the correct parser for this file type."
        )
        super().__init__(self.message)


def no_aal3_xml_label_dictionary_detail(exc: NoAal3XmlLabelDictionaryError) -> dict[str, object]:
    return {
        "code": "NO_AAL3_XML_LABEL_DICTIONARY",
        "message": exc.message,
        "batch_id": str(exc.batch_id),
        "parser_key": exc.parser_key,
        "bound_files": exc.bound_files,
        "suggestion": exc.suggestion,
    }


class DuplicateParseError(Exception):
    def __init__(self, batch_id: uuid.UUID, parser_key: str, existing_run_id: uuid.UUID):
        self.batch_id = batch_id
        self.parser_key = parser_key
        self.existing_run_id = existing_run_id
        super().__init__(str(existing_run_id))


class ParseRunNotFoundError(Exception):
    pass


def _log_action(
    *,
    action: str,
    result: str,
    batch_id: uuid.UUID | None = None,
    parse_run_id: uuid.UUID | None = None,
    error: str | None = None,
) -> None:
    logger.info(
        "event_type=raw_parsing action=%s result=%s batch_id=%s parse_run_id=%s error=%s",
        action,
        result,
        batch_id,
        parse_run_id,
        error,
    )


def _file_extension(file_row: ResourceFile) -> str:
    name = file_row.original_filename.lower()
    if name.endswith(".nii.gz"):
        return ".nii.gz"
    ext = normalize_extension(file_row.original_filename)
    file_ext = getattr(file_row, "file_ext", None)
    if file_ext:
        fe = file_ext.lower()
        if fe == ".nii.gz" or name.endswith(".nii.gz"):
            return ".nii.gz"
        if fe:
            return fe if fe.startswith(".") else f".{fe}"
    return ext


def _intermediate_schema(artifact) -> str | None:
    if artifact is None:
        return None
    content = getattr(artifact, "content_jsonb", None) or {}
    if isinstance(content, dict):
        schema = content.get("schema")
        return str(schema) if schema is not None else None
    return None


def assess_aal3_xml_parser_compatibility(
    file_row: ResourceFile,
    binding_role: str,
    *,
    intermediate_artifact=None,
) -> tuple[bool, str | None]:
    """Return (compatible, reason) for parser_key=aal3_xml."""
    ext = _file_extension(file_row)

    if ext in _AAL3_INCOMPATIBLE_EXTENSIONS:
        if ext in {".xlsx", ".xls"}:
            return False, "xlsx file cannot be parsed by aal3_xml parser"
        if ext == ".pdf":
            return False, "pdf file cannot be parsed by aal3_xml parser"
        return False, f"{ext} file cannot be parsed by aal3_xml parser"

    if file_row.file_type in _AAL3_INCOMPATIBLE_FILE_TYPES:
        if file_row.file_type == "spreadsheet":
            return False, "spreadsheet file cannot be parsed by aal3_xml parser"
        if file_row.file_type == "pdf":
            return False, "pdf file cannot be parsed by aal3_xml parser"
        return False, f"file_type={file_row.file_type} is not compatible with aal3_xml parser"

    if intermediate_artifact is not None:
        kind = intermediate_artifact.artifact_kind
        if kind in _AAL3_INCOMPATIBLE_INTERMEDIATE_KINDS:
            return False, f"intermediate artifact_kind={kind} is not compatible with aal3_xml parser"
        if kind == "label_table":
            content = intermediate_artifact.content_jsonb or {}
            schema = content.get("schema")
            source_format = getattr(intermediate_artifact, "source_format", None)
            rows = content.get("rows") or []
            if schema == "label_table_v1" and source_format == "xml" and rows:
                return True, None
            if schema == "label_table_v1" and source_format == "xml" and not rows:
                return False, "label_table intermediate exists but rows are empty"
            if kind == "label_table" and rows and ext == ".xml":
                return True, None

    if ext == ".xml":
        if (
            file_row.file_type == "label_table"
            or binding_role == "label_dictionary"
            or file_row.file_role == "label_dictionary"
        ):
            return True, None
        return False, "xml file is not configured as label_table / label_dictionary"

    if ext in {".txt", ".csv", ".tsv"}:
        return False, f"{ext} file cannot be parsed by aal3_xml parser; use AAL3 XML label dictionary"

    return False, "no AAL3 XML label dictionary source found for this file"


def _bound_file_diagnostic(
    file_row: ResourceFile,
    binding_role: str,
    *,
    intermediate_artifact=None,
    reason: str | None = None,
) -> dict[str, object]:
    compatible, auto_reason = assess_aal3_xml_parser_compatibility(
        file_row,
        binding_role,
        intermediate_artifact=intermediate_artifact,
    )
    kind = getattr(intermediate_artifact, "artifact_kind", None) if intermediate_artifact else None
    return {
        "file_id": str(file_row.id),
        "original_filename": file_row.original_filename,
        "file_type": file_row.file_type,
        "file_role": file_row.file_role,
        "file_role_in_batch": binding_role,
        "file_status": file_row.status,
        "latest_intermediate_kind": kind,
        "latest_intermediate_schema": _intermediate_schema(intermediate_artifact),
        "parser_compatible_for_aal3_xml": compatible,
        "reason": reason or auto_reason or "compatible with aal3_xml parser",
    }


def _is_label_eligible(file_row: ResourceFile, binding_role: str) -> bool:
    """Legacy eligibility — kept for advisory paths; aal3_xml uses assess_aal3_xml_parser_compatibility."""
    compatible, _ = assess_aal3_xml_parser_compatibility(file_row, binding_role)
    return compatible


def _score_label_file(file_row: ResourceFile, binding_role: str) -> int:
    if binding_role == "label_dictionary":
        return 100
    if file_row.file_type == "label_table":
        return 80
    ext = normalize_extension(file_row.original_filename)
    if ext == ".xml":
        return 70
    if ext in {".txt", ".csv", ".tsv"}:
        return 50
    return 0


async def _count_raw_rows_for_parse_run(
    session: AsyncSession, parse_run_id: uuid.UUID, parser_key: str
) -> int:
    if parser_key == PARSER_KEY_MACRO96_XLSX:
        q = (
            select(func.count())
            .select_from(RawMacro96RegionRow)
            .where(RawMacro96RegionRow.parse_run_id == parse_run_id)
        )
    else:
        q = (
            select(func.count())
            .select_from(RawAal3RegionLabel)
            .where(RawAal3RegionLabel.parse_run_id == parse_run_id)
        )
    return int((await session.execute(q)).scalar_one())


async def _get_succeeded_run(
    session: AsyncSession, batch_id: uuid.UUID, parser_key: str
) -> RawParseRun | None:
    q = select(RawParseRun).where(
        RawParseRun.batch_id == batch_id,
        RawParseRun.parser_key == parser_key,
        RawParseRun.status == "succeeded",
    )
    return (await session.execute(q)).scalar_one_or_none()


async def _validate_batch_for_parse(session: AsyncSession, batch_id: uuid.UUID) -> ImportBatch:
    batch = await import_batch_service.get_batch(session, batch_id)
    if batch.status != ImportBatchStatus.running.value:
        raise BatchNotRunnableError(
            f"batch status must be running, got {batch.status}"
        )
    resource = await resource_service.get_resource(session, batch.resource_id)
    if resource.status == "archived":
        raise BatchNotRunnableError("resource is archived")
    return batch


async def _select_label_files(
    session: AsyncSession, batch: ImportBatch
) -> list[tuple[ResourceFile, str]]:
    bindings = await import_batch_service.list_batch_files(session, batch.id)
    file_map = await import_batch_service.load_resource_files_for_bindings(session, bindings)

    diagnostics: list[dict[str, object]] = []
    candidates: list[tuple[int, ResourceFile, str]] = []

    for binding in bindings:
        file_row = file_map.get(binding.file_id)
        if file_row is None:
            continue
        if file_row.status != "active" or file_row.deleted_at is not None:
            status = "deleted" if file_row.deleted_at is not None else file_row.status
            raise BoundFileNotActiveError(file_row.id, status, batch.id)
        if file_row.resource_id != batch.resource_id:
            raise BatchNotRunnableError(
                f"file {file_row.id} belongs to another resource"
            )
        intermediate = await file_normalization_service.get_latest_active_artifact(
            session, file_row.id
        )
        compatible, reason = assess_aal3_xml_parser_compatibility(
            file_row,
            binding.file_role_in_batch,
            intermediate_artifact=intermediate,
        )
        diagnostics.append(
            _bound_file_diagnostic(
                file_row,
                binding.file_role_in_batch,
                intermediate_artifact=intermediate,
                reason=reason,
            )
        )
        if compatible:
            score = _score_label_file(file_row, binding.file_role_in_batch)
            candidates.append((score, file_row, binding.file_role_in_batch))

    if not candidates:
        _log_action(
            action="select_label_files",
            result="none_compatible",
            batch_id=batch.id,
            error=f"bound_files={len(diagnostics)}",
        )
        if not diagnostics:
            raise NoLabelFileError("no files bound to batch")
        raise NoAal3XmlLabelDictionaryError(
            batch.id,
            PARSER_KEY_AAL3_XML,
            diagnostics,
        )

    candidates.sort(key=lambda x: (-x[0], x[1].original_filename))
    best_score = candidates[0][0]
    selected = [(f, role) for score, f, role in candidates if score == best_score]
    return selected


def evaluate_batch_parse_readiness(
    bindings,
    file_map: dict[uuid.UUID, ResourceFile],
    *,
    intermediate_by_file_id: dict[uuid.UUID, object] | None = None,
) -> tuple[bool, str | None]:
    """Advisory check for pipeline UI — mirrors aal3_xml compatibility without raising."""
    intermediate_by_file_id = intermediate_by_file_id or {}
    compatible_count = 0

    for binding in bindings:
        file_row = file_map.get(binding.file_id)
        if file_row is None:
            continue
        if file_row.status != "active" or file_row.deleted_at is not None:
            status = "deleted" if file_row.deleted_at is not None else file_row.status
            return (
                False,
                f"Bound label file is not active: {file_row.id} (status={status})",
            )
        art = intermediate_by_file_id.get(binding.file_id)
        ok, _reason = assess_aal3_xml_parser_compatibility(
            file_row,
            binding.file_role_in_batch,
            intermediate_artifact=art,
        )
        if ok:
            compatible_count += 1

    if compatible_count == 0:
        if not bindings:
            return False, "No files bound to this batch"
        return False, "No active AAL3 XML label dictionary file is bound to this batch."

    return True, None


def evaluate_macro96_parse_readiness(
    bindings,
    file_map: dict[uuid.UUID, ResourceFile],
    *,
    intermediate_by_file_id: dict[uuid.UUID, object] | None = None,
) -> tuple[bool, str | None]:
    """Advisory check for macro96_xlsx parser — used by pipeline overview UI.

    Returns (enabled, disable_reason). Does not raise; does not write.
    """
    intermediate_by_file_id = intermediate_by_file_id or {}

    if not bindings:
        return False, "No files bound to this batch"

    for binding in bindings:
        file_row = file_map.get(binding.file_id)
        if file_row is None:
            continue

        if file_row.status != "active" or file_row.deleted_at is not None:
            status = "deleted" if file_row.deleted_at is not None else file_row.status
            return False, f"Bound file is not active: {file_row.id} (status={status})"

        if binding.file_role_in_batch != "macro_region_pool_source":
            continue

        art = intermediate_by_file_id.get(binding.file_id)
        if art is None:
            return (
                False,
                "macro_region_table intermediate not found. "
                "Please normalize the file in File Center first.",
            )
        if getattr(art, "artifact_kind", None) != "macro_region_table":
            return (
                False,
                f"Bound file intermediate artifact_kind={getattr(art, 'artifact_kind', None)!r} "
                "is not macro_region_table. Please normalize in File Center first.",
            )
        content = getattr(art, "content_jsonb", None) or {}
        if isinstance(content, dict) and content.get("schema") != "macro_region_table_v1":
            return (
                False,
                "Intermediate schema is not macro_region_table_v1. Re-normalize in File Center.",
            )
        return True, None

    return (
        False,
        "No macro_region_pool_source file bound to this batch.",
    )


def assess_bound_file_parse_status(
    file_row: ResourceFile | None,
    binding_role: str,
    *,
    intermediate_artifact=None,
) -> dict[str, object]:
    """Per-file parse eligibility for pipeline overview."""
    if file_row is None:
        return {
            "is_active": False,
            "can_parse": False,
            "inactive_reason": "file record not found",
            "parser_compatible_for_aal3_xml": False,
            "parser_incompatible_reason": "file record not found",
            "latest_intermediate_kind": None,
            "latest_intermediate_schema": None,
        }

    is_active = file_row.status == "active" and file_row.deleted_at is None
    compatible, compat_reason = assess_aal3_xml_parser_compatibility(
        file_row,
        binding_role,
        intermediate_artifact=intermediate_artifact,
    )
    kind = getattr(intermediate_artifact, "artifact_kind", None) if intermediate_artifact else None
    schema = _intermediate_schema(intermediate_artifact)

    if not is_active:
        status = "deleted" if file_row.deleted_at is not None else file_row.status
        return {
            "is_active": False,
            "can_parse": False,
            "inactive_reason": f"file is {status}",
            "parser_compatible_for_aal3_xml": False,
            "parser_incompatible_reason": f"file is {status}",
            "latest_intermediate_kind": kind,
            "latest_intermediate_schema": schema,
        }

    if not compatible:
        return {
            "is_active": True,
            "can_parse": False,
            "inactive_reason": compat_reason,
            "parser_compatible_for_aal3_xml": False,
            "parser_incompatible_reason": compat_reason,
            "latest_intermediate_kind": kind,
            "latest_intermediate_schema": schema,
        }

    return {
        "is_active": True,
        "can_parse": True,
        "inactive_reason": None,
        "parser_compatible_for_aal3_xml": True,
        "parser_incompatible_reason": None,
        "latest_intermediate_kind": kind,
        "latest_intermediate_schema": schema,
    }


async def parse_aal3_for_batch(
    session: AsyncSession,
    batch_id: uuid.UUID,
    *,
    parser_key: str = PARSER_KEY_AAL3_XML,
) -> RawParseRun:
    batch = await _validate_batch_for_parse(session, batch_id)

    existing = await _get_succeeded_run(session, batch_id, parser_key)
    if existing is not None:
        raw_count = await _count_raw_rows_for_parse_run(session, existing.id, parser_key)
        if raw_count > 0:
            _log_action(
                action="parse_aal3",
                result="duplicate_rejected",
                batch_id=batch_id,
                parse_run_id=existing.id,
            )
            raise DuplicateParseError(batch_id, parser_key, existing.id)

    label_files = await _select_label_files(session, batch)
    resource = await resource_service.get_resource(session, batch.resource_id)

    now = datetime.now(timezone.utc)
    input_ids = [str(f.id) for f, _ in label_files]

    parse_run = RawParseRun(
        batch_id=batch_id,
        resource_id=batch.resource_id,
        parser_key=parser_key,
        parser_version=DEFAULT_PARSER_VERSION,
        status="running",
        input_file_ids=input_ids,
        started_at=now,
    )
    session.add(parse_run)
    await session.flush()

    await import_batch_service.record_batch_event(
        session,
        batch_id,
        BatchEventType.parse_started.value,
        message="AAL3 raw parsing started",
        from_status=batch.status,
        payload_json={"parse_run_id": str(parse_run.id), "input_file_ids": input_ids},
    )

    _log_action(
        action="parse_started",
        result="success",
        batch_id=batch_id,
        parse_run_id=parse_run.id,
    )

    warning_count = 0
    all_label_rows: list[RawAal3RegionLabel] = []

    try:
        for file_row, _role in label_files:
            intermediate = await file_normalization_service.get_latest_active_artifact(
                session, file_row.id
            )
            compatible, _ = assess_aal3_xml_parser_compatibility(
                file_row, _role, intermediate_artifact=intermediate
            )
            if not compatible:
                continue

            # Prefer intermediate label_table artifact; fall back to raw XML parse.
            if (
                intermediate is not None
                and intermediate.artifact_kind == "label_table"
                and intermediate.content_jsonb
            ):
                _log_action(
                    action="parse_from_intermediate",
                    result="info",
                    batch_id=batch_id,
                    parse_run_id=parse_run.id,
                    error=str(file_row.id),
                )
                content = intermediate.content_jsonb
                raw_rows = content.get("rows", [])
                regions = [
                    {
                        "label_index": r.get("label_value"),
                        "original_name": r.get("raw_name", ""),
                        "abbr": r.get("raw_name", ""),
                        "full_name": r.get("en_name") or r.get("raw_name", ""),
                        "hemisphere": r.get("laterality"),
                        "parent_region": None,
                        "granularity": "macro",
                        "source_id": r.get("source_label_id", ""),
                        "coordinates_mni": None,
                        "bounding_box": None,
                        "extra_attrs": {},
                    }
                    for r in raw_rows
                ]
            else:
                ext = _file_extension(file_row)
                if ext != ".xml":
                    raise NoAal3XmlLabelDictionaryError(
                        batch_id,
                        parser_key,
                        [
                            _bound_file_diagnostic(
                                file_row,
                                _role,
                                intermediate_artifact=intermediate,
                                reason=f"{ext} file cannot be parsed by aal3_xml parser",
                            )
                        ],
                    )
                _log_action(
                    action="parse_from_raw_xml",
                    result="info",
                    batch_id=batch_id,
                    parse_run_id=parse_run.id,
                    error=str(file_row.id),
                )
                path = resource_file_service.resolve_download_path(file_row)
                if not path.is_file():
                    raise NoAal3XmlLabelDictionaryError(
                        batch_id,
                        parser_key,
                        [
                            _bound_file_diagnostic(
                                file_row,
                                _role,
                                intermediate_artifact=intermediate,
                                reason="physical file path does not exist",
                            )
                        ],
                    )
                regions = parse_aal3_xml(path)

            row_dicts = xml_regions_to_raw_labels(
                regions=regions,
                parse_run_id=parse_run.id,
                batch_id=batch_id,
                resource_id=batch.resource_id,
                source_file_id=file_row.id,
                source_atlas=resource.source_atlas,
                source_version=resource.source_version,
            )
            for rd in row_dicts:
                all_label_rows.append(RawAal3RegionLabel(**rd))

        if not all_label_rows:
            bindings = await import_batch_service.list_batch_files(session, batch_id)
            file_map = await import_batch_service.load_resource_files_for_bindings(
                session, bindings
            )
            diagnostics: list[dict[str, object]] = []
            for binding in bindings:
                file_row = file_map.get(binding.file_id)
                if file_row is None:
                    continue
                intermediate = await file_normalization_service.get_latest_active_artifact(
                    session, file_row.id
                )
                _, reason = assess_aal3_xml_parser_compatibility(
                    file_row,
                    binding.file_role_in_batch,
                    intermediate_artifact=intermediate,
                )
                diagnostics.append(
                    _bound_file_diagnostic(
                        file_row,
                        binding.file_role_in_batch,
                        intermediate_artifact=intermediate,
                        reason=reason or "XML parser returned empty rows",
                    )
                )
            raise NoAal3XmlLabelDictionaryError(
                batch_id,
                parser_key,
                diagnostics,
                message="No active AAL3 XML label dictionary in this batch produced parse output.",
            )

        session.add_all(all_label_rows)

        finished = datetime.now(timezone.utc)
        parse_run.status = "succeeded"
        parse_run.output_count = len(all_label_rows)
        parse_run.warning_count = warning_count
        parse_run.finished_at = finished

        await import_batch_service.record_batch_event(
            session,
            batch_id,
            BatchEventType.parse_succeeded.value,
            message=f"AAL3 raw parsing succeeded, output_count={len(all_label_rows)}",
            from_status=ImportBatchStatus.running.value,
            to_status=ImportBatchStatus.parsed.value,
            payload_json={
                "parse_run_id": str(parse_run.id),
                "output_count": len(all_label_rows),
                "warning_count": warning_count,
            },
        )

        await import_batch_service.apply_batch_status_in_session(
            session,
            batch,
            ImportBatchStatus.parsed,
            message="batch parsed after AAL3 raw parsing",
            event_type=BatchEventType.status_changed.value,
        )

        await session.commit()
        await session.refresh(parse_run)

        _log_action(
            action="parse_succeeded",
            result="success",
            batch_id=batch_id,
            parse_run_id=parse_run.id,
        )
        return parse_run

    except Exception as exc:
        await session.rollback()
        _log_action(
            action="parse_failed",
            result="error",
            batch_id=batch_id,
            error=str(exc),
        )

        try:
            failed_run = RawParseRun(
                batch_id=batch_id,
                resource_id=batch.resource_id,
                parser_key=parser_key,
                parser_version=DEFAULT_PARSER_VERSION,
                status="failed",
                input_file_ids=input_ids,
                error_message=str(exc),
                started_at=now,
                finished_at=datetime.now(timezone.utc),
            )
            session.add(failed_run)
            await session.flush()

            batch_ref = await import_batch_service.get_batch(session, batch_id)
            await import_batch_service.record_batch_event(
                session,
                batch_id,
                BatchEventType.parse_failed.value,
                message=f"AAL3 raw parsing failed: {exc}",
                from_status=ImportBatchStatus.running.value,
                to_status=ImportBatchStatus.failed.value,
                payload_json={"error": str(exc), "parse_run_id": str(failed_run.id)},
            )
            await import_batch_service.apply_batch_status_in_session(
                session,
                batch_ref,
                ImportBatchStatus.failed,
                message="batch failed during AAL3 raw parsing",
                error_message=str(exc),
                event_type=BatchEventType.failed.value,
            )
            await session.commit()
        except Exception as inner:
            await session.rollback()
            _log_action(
                action="parse_failure_record",
                result="error",
                batch_id=batch_id,
                error=str(inner),
            )
        raise


async def list_parse_runs_for_batch(
    session: AsyncSession, batch_id: uuid.UUID
) -> list[RawParseRun]:
    await import_batch_service.get_batch(session, batch_id)
    q = (
        select(RawParseRun)
        .where(RawParseRun.batch_id == batch_id)
        .order_by(RawParseRun.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


async def get_parse_run(session: AsyncSession, parse_run_id: uuid.UUID) -> RawParseRun:
    row = await session.get(RawParseRun, parse_run_id)
    if row is None:
        raise ParseRunNotFoundError(str(parse_run_id))
    return row


async def list_aal3_labels(
    session: AsyncSession,
    *,
    parse_run_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    laterality: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[RawAal3RegionLabel], int]:
    base = select(RawAal3RegionLabel)
    count_q = select(func.count()).select_from(RawAal3RegionLabel)

    if parse_run_id:
        base = base.where(RawAal3RegionLabel.parse_run_id == parse_run_id)
        count_q = count_q.where(RawAal3RegionLabel.parse_run_id == parse_run_id)
    if batch_id:
        base = base.where(RawAal3RegionLabel.batch_id == batch_id)
        count_q = count_q.where(RawAal3RegionLabel.batch_id == batch_id)
    if resource_id:
        base = base.where(RawAal3RegionLabel.resource_id == resource_id)
        count_q = count_q.where(RawAal3RegionLabel.resource_id == resource_id)
    if laterality:
        base = base.where(RawAal3RegionLabel.laterality == laterality)
        count_q = count_q.where(RawAal3RegionLabel.laterality == laterality)
    if granularity_level:
        base = base.where(RawAal3RegionLabel.granularity_level == granularity_level)
        count_q = count_q.where(RawAal3RegionLabel.granularity_level == granularity_level)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(RawAal3RegionLabel.row_index).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


def parse_run_to_read(run: RawParseRun) -> dict:
    ids = run.input_file_ids or []
    return {
        **{c.name: getattr(run, c.name) for c in run.__table__.columns},
        "input_file_ids": [str(i) for i in ids],
    }


# ─── Macro96 parsing ─────────────────────────────────────────────────────────


class NoMacro96PoolSourceError(Exception):
    """Raised when batch has no macro_region_pool_source file."""

    def __init__(self, batch_id: uuid.UUID, bound_count: int):
        self.batch_id = batch_id
        self.bound_count = bound_count
        super().__init__(
            f"No active macro_region_pool_source file bound to batch {batch_id} "
            f"(total bound files: {bound_count})"
        )


class NoMacro96IntermediateError(Exception):
    """Raised when bound pool source file has no macro_region_table intermediate."""

    def __init__(self, file_id: uuid.UUID, batch_id: uuid.UUID):
        self.file_id = file_id
        self.batch_id = batch_id
        super().__init__(
            f"File {file_id} has no macro_region_table intermediate artifact. "
            "Please normalize the file in File Center first."
        )


class WrongParserKeyError(Exception):
    """Raised when batch.parser_key does not match the requested parser."""

    def __init__(self, batch_id: uuid.UUID, expected: str, actual: str):
        self.batch_id = batch_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"batch {batch_id} parser_key={actual!r} does not match expected {expected!r}"
        )


async def parse_macro96_for_batch(
    session: AsyncSession,
    batch_id: uuid.UUID,
) -> ParseMacro96Response:
    """Parse Macro96 Excel pool source for a running import batch.

    Reads macro_region_table_v1 intermediate → writes raw_macro96_region_rows.
    Sets batch.status running → parsed on success.

    Boundaries: does NOT generate candidates, write final_* / kg_*, or call LLM.
    Idempotent: returns 409 (DuplicateParseError) if already succeeded.
    """
    batch = await _validate_batch_for_parse(session, batch_id)

    if batch.parser_key != PARSER_KEY_MACRO96_XLSX:
        raise WrongParserKeyError(batch_id, PARSER_KEY_MACRO96_XLSX, batch.parser_key or "")

    existing = await _get_succeeded_run(session, batch_id, PARSER_KEY_MACRO96_XLSX)
    if existing is not None:
        raw_count = await _count_raw_rows_for_parse_run(
            session, existing.id, PARSER_KEY_MACRO96_XLSX
        )
        if raw_count > 0:
            _log_action(
                action="parse_macro96",
                result="duplicate_rejected",
                batch_id=batch_id,
                parse_run_id=existing.id,
            )
            raise DuplicateParseError(batch_id, PARSER_KEY_MACRO96_XLSX, existing.id)

    # ── Find bound pool source file ──────────────────────────────────────────
    bindings = await import_batch_service.list_batch_files(session, batch_id)
    file_map = await import_batch_service.load_resource_files_for_bindings(session, bindings)

    pool_file: ResourceFile | None = None
    pool_binding_role: str = ""

    for binding in bindings:
        file_row = file_map.get(binding.file_id)
        if file_row is None:
            continue
        if file_row.status != "active" or file_row.deleted_at is not None:
            status = "deleted" if file_row.deleted_at is not None else file_row.status
            raise BoundFileNotActiveError(file_row.id, status, batch_id)
        if binding.file_role_in_batch == "macro_region_pool_source":
            pool_file = file_row
            pool_binding_role = binding.file_role_in_batch
            break

    if pool_file is None:
        raise NoMacro96PoolSourceError(batch_id, len(bindings))

    # ── Find macro_region_table intermediate ─────────────────────────────────
    intermediate = await file_normalization_service.get_latest_active_artifact(
        session, pool_file.id
    )

    artifact_id: uuid.UUID | None = None
    if (
        intermediate is None
        or intermediate.artifact_kind != "macro_region_table"
        or not intermediate.content_jsonb
    ):
        raise NoMacro96IntermediateError(pool_file.id, batch_id)

    artifact_id = intermediate.id
    content_jsonb = intermediate.content_jsonb

    # ── Create parse_run ─────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    input_ids = [str(pool_file.id)]

    parse_run = RawParseRun(
        batch_id=batch_id,
        resource_id=batch.resource_id,
        parser_key=PARSER_KEY_MACRO96_XLSX,
        parser_version=PARSER_VERSION_MACRO96,
        status="running",
        input_file_ids=input_ids,
        started_at=now,
    )
    session.add(parse_run)
    await session.flush()

    await import_batch_service.record_batch_event(
        session,
        batch_id,
        "parse_macro96_started",
        message="Macro96 raw parsing started",
        from_status=batch.status,
        payload_json={"parse_run_id": str(parse_run.id), "input_file_ids": input_ids},
    )

    _log_action(
        action="parse_macro96_started",
        result="success",
        batch_id=batch_id,
        parse_run_id=parse_run.id,
    )

    try:
        # ── Parse intermediate ────────────────────────────────────────────────
        row_dicts = parse_macro96_table_from_intermediate(content_jsonb)

        # ── Write raw_macro96_region_rows ────────────────────────────────────
        raw_rows: list[RawMacro96RegionRow] = [
            RawMacro96RegionRow(
                parse_run_id=parse_run.id,
                resource_id=batch.resource_id,
                batch_id=batch_id,
                source_file_id=pool_file.id,
                intermediate_artifact_id=artifact_id,
                row_index=rd["row_index"],
                region_index=rd["region_index"],
                en_name=rd["en_name"],
                cn_name=rd["cn_name"],
                raw_brain_structure=rd["raw_brain_structure"],
                raw_cn_name=rd["raw_cn_name"],
                source_sheet=rd["source_sheet"],
                parser_key=PARSER_KEY_MACRO96_XLSX,
                parser_version=PARSER_VERSION_MACRO96,
                raw_payload=rd["raw_payload"],
            )
            for rd in row_dicts
        ]
        session.add_all(raw_rows)

        # ── Update parse_run ──────────────────────────────────────────────────
        finished = datetime.now(timezone.utc)
        parse_run.status = "succeeded"
        parse_run.output_count = len(raw_rows)
        parse_run.warning_count = 0
        parse_run.finished_at = finished

        await import_batch_service.record_batch_event(
            session,
            batch_id,
            "parse_macro96_succeeded",
            message=f"Macro96 raw parsing succeeded, row_count={len(raw_rows)}",
            from_status=ImportBatchStatus.running.value,
            to_status=ImportBatchStatus.parsed.value,
            payload_json={
                "parse_run_id": str(parse_run.id),
                "output_count": len(raw_rows),
                "intermediate_artifact_id": str(artifact_id),
            },
        )

        await import_batch_service.apply_batch_status_in_session(
            session,
            batch,
            ImportBatchStatus.parsed,
            message="batch parsed after Macro96 raw parsing",
            event_type=BatchEventType.status_changed.value,
        )

        await session.commit()
        await session.refresh(parse_run)

        _log_action(
            action="parse_macro96_succeeded",
            result="success",
            batch_id=batch_id,
            parse_run_id=parse_run.id,
        )

        return ParseMacro96Response(
            parse_run_id=parse_run.id,
            batch_id=batch_id,
            resource_id=batch.resource_id,
            source_file_id=pool_file.id,
            intermediate_artifact_id=artifact_id,
            parser_key=PARSER_KEY_MACRO96_XLSX,
            parser_version=PARSER_VERSION_MACRO96,
            row_count=len(raw_rows),
            warning_count=0,
            status="succeeded",
        )

    except Exception as exc:
        await session.rollback()
        _log_action(
            action="parse_macro96_failed",
            result="error",
            batch_id=batch_id,
            error=str(exc),
        )

        try:
            failed_run = RawParseRun(
                batch_id=batch_id,
                resource_id=batch.resource_id,
                parser_key=PARSER_KEY_MACRO96_XLSX,
                parser_version=PARSER_VERSION_MACRO96,
                status="failed",
                input_file_ids=input_ids,
                error_message=str(exc),
                started_at=now,
                finished_at=datetime.now(timezone.utc),
            )
            session.add(failed_run)
            await session.flush()

            batch_ref = await import_batch_service.get_batch(session, batch_id)
            await import_batch_service.record_batch_event(
                session,
                batch_id,
                "parse_macro96_failed",
                message=f"Macro96 raw parsing failed: {exc}",
                from_status=ImportBatchStatus.running.value,
                to_status=ImportBatchStatus.failed.value,
                payload_json={"error": str(exc), "parse_run_id": str(failed_run.id)},
            )
            await import_batch_service.apply_batch_status_in_session(
                session,
                batch_ref,
                ImportBatchStatus.failed,
                message="batch failed during Macro96 raw parsing",
                error_message=str(exc),
                event_type=BatchEventType.failed.value,
            )
            await session.commit()
        except Exception as inner:
            await session.rollback()
            _log_action(
                action="parse_macro96_failure_record",
                result="error",
                batch_id=batch_id,
                error=str(inner),
            )
        raise


async def list_macro96_rows(
    session: AsyncSession,
    *,
    parse_run_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    source_file_id: uuid.UUID | None = None,
    granularity_level: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[RawMacro96RegionRow], int]:
    base = select(RawMacro96RegionRow)
    count_q = select(func.count()).select_from(RawMacro96RegionRow)

    if parse_run_id:
        base = base.where(RawMacro96RegionRow.parse_run_id == parse_run_id)
        count_q = count_q.where(RawMacro96RegionRow.parse_run_id == parse_run_id)
    if batch_id:
        base = base.where(RawMacro96RegionRow.batch_id == batch_id)
        count_q = count_q.where(RawMacro96RegionRow.batch_id == batch_id)
    if resource_id:
        base = base.where(RawMacro96RegionRow.resource_id == resource_id)
        count_q = count_q.where(RawMacro96RegionRow.resource_id == resource_id)
    if source_file_id:
        base = base.where(RawMacro96RegionRow.source_file_id == source_file_id)
        count_q = count_q.where(RawMacro96RegionRow.source_file_id == source_file_id)
    if granularity_level:
        base = base.where(RawMacro96RegionRow.granularity_level == granularity_level)
        count_q = count_q.where(RawMacro96RegionRow.granularity_level == granularity_level)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(RawMacro96RegionRow.row_index).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total
