"""Import Batch / Task business logic.

Does NOT run parsers, create candidates, or write final_* / kg_*.
Full audit_log is deferred to Logging & Audit module; batch events stored in import_batch_events.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_batch import ImportBatch, ImportBatchEvent, ImportBatchFile
from app.models.resource import AtlasResource
from app.models.resource_file import ResourceFile
from app.models.workspace_file import WorkspaceFile
from app.schemas.import_batch import (
    BatchEventType,
    BatchType,
    FileRoleInBatch,
    ImportBatchCreate,
    ImportBatchFileBinding,
    ImportBatchFileEnrichedRead,
    ImportBatchStatus,
    ImportBatchUpdate,
    InvalidBatchTransitionError,
    validate_import_batch_transition,
)
from app.services import file_normalization_service, raw_parsing_service, resource_file_service, resource_service
from app.utils.import_batch_parser_compat import ParserFileBindingError, validate_parser_file_binding

logger = logging.getLogger(__name__)


class BatchNotFoundError(Exception):
    pass


class BatchCodeConflictError(Exception):
    pass


class ResourceNotEligibleError(Exception):
    pass


class FileBindingError(Exception):
    pass


class BatchEditNotAllowedError(Exception):
    pass


class InvalidTransitionError(Exception):
    def __init__(self, from_status: str, to_status: str, reason: str):
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(reason)


def _log_action(
    *,
    event_type: str,
    action: str,
    result: str,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    error: str | None = None,
) -> None:
    logger.info(
        "event_type=%s action=%s result=%s batch_id=%s resource_id=%s error=%s",
        event_type,
        action,
        result,
        batch_id,
        resource_id,
        error,
    )


async def _ensure_resource_eligible(session: AsyncSession, resource_id: uuid.UUID) -> AtlasResource:
    row = await resource_service.get_resource(session, resource_id)
    if row.status == "archived":
        raise ResourceNotEligibleError("resource is archived")
    return row


async def _ensure_file_eligible(
    session: AsyncSession, file_id: uuid.UUID, resource_id: uuid.UUID
) -> ResourceFile:
    ws = await session.get(WorkspaceFile, file_id)
    if ws is not None:
        raise FileBindingError(
            f"workspace file cannot be bound directly; attach to resource first: {file_id}"
        )
    try:
        row = await resource_file_service.get_file(session, file_id)
    except resource_file_service.FileNotFoundError as exc:
        raise FileBindingError(f"file not found or deleted: {file_id}") from exc
    if row.status != "active":
        raise FileBindingError(f"file is not active: {file_id} (status={row.status})")
    if row.resource_id != resource_id:
        raise FileBindingError(
            f"file {file_id} belongs to resource {row.resource_id}, expected {resource_id}"
        )
    return row


def _generate_batch_code(resource: AtlasResource) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ").lower()
    suffix = secrets.token_hex(4)
    return f"{resource.resource_code}_import_{stamp}_{suffix}"


async def _append_event(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
    message: str | None = None,
    payload_json: dict[str, Any] | None = None,
) -> ImportBatchEvent:
    event = ImportBatchEvent(
        batch_id=batch_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        message=message,
        payload_json=payload_json,
    )
    session.add(event)
    return event


async def create_batch(session: AsyncSession, payload: ImportBatchCreate) -> ImportBatch:
    resource = await _ensure_resource_eligible(session, payload.resource_id)
    batch_code = payload.batch_code or _generate_batch_code(resource)

    seen_files: set[uuid.UUID] = set()
    for binding in payload.files:
        if binding.file_id in seen_files:
            raise FileBindingError(f"duplicate file_id in request: {binding.file_id}")
        seen_files.add(binding.file_id)
        await _ensure_file_eligible(session, binding.file_id, payload.resource_id)
        rf = await resource_file_service.get_file(session, binding.file_id)
        try:
            validate_parser_file_binding(
                payload.parser_key, binding.file_role_in_batch.value, rf
            )
        except ParserFileBindingError as exc:
            raise FileBindingError(str(exc)) from exc

    batch = ImportBatch(
        batch_code=batch_code,
        resource_id=payload.resource_id,
        batch_type=payload.batch_type.value,
        parser_key=payload.parser_key,
        status=ImportBatchStatus.created.value,
        description=payload.description,
        remark=payload.remark,
    )
    session.add(batch)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        _log_action(
            event_type="import_batch",
            action="create",
            result="error",
            resource_id=payload.resource_id,
            error=str(exc.orig),
        )
        raise BatchCodeConflictError(batch_code) from exc

    await _append_event(
        session,
        batch_id=batch.id,
        event_type=BatchEventType.created.value,
        to_status=ImportBatchStatus.created.value,
        message="import batch created",
        payload_json={"batch_code": batch_code, "resource_id": str(payload.resource_id)},
    )

    for idx, binding in enumerate(payload.files):
        sort_order = binding.sort_order if binding.sort_order is not None else idx
        bf = ImportBatchFile(
            batch_id=batch.id,
            file_id=binding.file_id,
            resource_id=payload.resource_id,
            file_role_in_batch=binding.file_role_in_batch.value,
            sort_order=sort_order,
        )
        session.add(bf)
        await _append_event(
            session,
            batch_id=batch.id,
            event_type=BatchEventType.file_attached.value,
            message=f"file attached: {binding.file_id}",
            payload_json={
                "file_id": str(binding.file_id),
                "file_role_in_batch": binding.file_role_in_batch.value,
                "sort_order": sort_order,
            },
        )

    await session.commit()
    await session.refresh(batch)

    _log_action(
        event_type="import_batch",
        action="create",
        result="success",
        batch_id=batch.id,
        resource_id=batch.resource_id,
    )
    return batch


async def list_batches(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    resource_id: uuid.UUID | None = None,
    batch_type: str | None = None,
    status: str | None = None,
    parser_key: str | None = None,
    granularity_level: str | None = None,
) -> tuple[list[ImportBatch], int]:
    base = select(ImportBatch)
    count_q = select(func.count()).select_from(ImportBatch)

    if resource_id:
        base = base.where(ImportBatch.resource_id == resource_id)
        count_q = count_q.where(ImportBatch.resource_id == resource_id)
    if batch_type:
        base = base.where(ImportBatch.batch_type == batch_type)
        count_q = count_q.where(ImportBatch.batch_type == batch_type)
    if status:
        base = base.where(ImportBatch.status == status)
        count_q = count_q.where(ImportBatch.status == status)
    if parser_key:
        base = base.where(ImportBatch.parser_key == parser_key)
        count_q = count_q.where(ImportBatch.parser_key == parser_key)
    if granularity_level:
        base = base.join(AtlasResource, ImportBatch.resource_id == AtlasResource.id).where(
            AtlasResource.granularity_level == granularity_level
        )
        count_q = count_q.join(AtlasResource, ImportBatch.resource_id == AtlasResource.id).where(
            AtlasResource.granularity_level == granularity_level
        )

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(ImportBatch.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_batch(session: AsyncSession, batch_id: uuid.UUID) -> ImportBatch:
    row = await session.get(ImportBatch, batch_id)
    if row is None:
        raise BatchNotFoundError(str(batch_id))
    return row


async def get_batch_detail(
    session: AsyncSession, batch_id: uuid.UUID, *, recent_events_limit: int = 20
) -> tuple[ImportBatch, list[ImportBatchFile], list[ImportBatchEvent]]:
    batch = await get_batch(session, batch_id)

    files_q = (
        select(ImportBatchFile)
        .where(ImportBatchFile.batch_id == batch_id)
        .order_by(ImportBatchFile.sort_order, ImportBatchFile.created_at)
    )
    files = list((await session.execute(files_q)).scalars().all())

    events_q = (
        select(ImportBatchEvent)
        .where(ImportBatchEvent.batch_id == batch_id)
        .order_by(ImportBatchEvent.created_at.desc())
        .limit(recent_events_limit)
    )
    events = list((await session.execute(events_q)).scalars().all())
    return batch, files, events


async def list_batch_files(session: AsyncSession, batch_id: uuid.UUID) -> list[ImportBatchFile]:
    await get_batch(session, batch_id)
    q = (
        select(ImportBatchFile)
        .where(ImportBatchFile.batch_id == batch_id)
        .order_by(ImportBatchFile.sort_order, ImportBatchFile.created_at)
    )
    return list((await session.execute(q)).scalars().all())


async def list_batch_events(
    session: AsyncSession,
    batch_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ImportBatchEvent], int]:
    await get_batch(session, batch_id)
    base = select(ImportBatchEvent).where(ImportBatchEvent.batch_id == batch_id)
    count_q = (
        select(func.count())
        .select_from(ImportBatchEvent)
        .where(ImportBatchEvent.batch_id == batch_id)
    )
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(ImportBatchEvent.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def _transition_batch(
    session: AsyncSession,
    batch_id: uuid.UUID,
    to_status: ImportBatchStatus,
    *,
    message: str | None = None,
    error_message: str | None = None,
    event_type: str = BatchEventType.status_changed.value,
) -> ImportBatch:
    batch = await get_batch(session, batch_id)
    from_status = ImportBatchStatus(batch.status)

    try:
        validate_import_batch_transition(from_status, to_status)
    except InvalidBatchTransitionError as exc:
        _log_action(
            event_type="import_batch",
            action="transition",
            result="invalid",
            batch_id=batch_id,
            error=str(exc),
        )
        raise InvalidTransitionError(exc.from_status, exc.to_status, exc.reason) from exc

    now = datetime.now(timezone.utc)
    batch.status = to_status.value

    if to_status == ImportBatchStatus.running and batch.started_at is None:
        batch.started_at = now
    if to_status == ImportBatchStatus.completed:
        batch.finished_at = now
    if to_status == ImportBatchStatus.failed:
        batch.failed_at = now
        if error_message:
            batch.error_message = error_message
    if to_status == ImportBatchStatus.cancelled:
        batch.cancelled_at = now

    await _append_event(
        session,
        batch_id=batch.id,
        event_type=event_type,
        from_status=from_status.value,
        to_status=to_status.value,
        message=message or f"status changed to {to_status.value}",
        payload_json={"error_message": error_message} if error_message else None,
    )

    await session.commit()
    await session.refresh(batch)

    _log_action(
        event_type="import_batch",
        action="transition",
        result="success",
        batch_id=batch.id,
        resource_id=batch.resource_id,
    )
    return batch


async def queue_batch(session: AsyncSession, batch_id: uuid.UUID) -> ImportBatch:
    return await _transition_batch(
        session, batch_id, ImportBatchStatus.queued, message="batch queued"
    )


async def start_batch(session: AsyncSession, batch_id: uuid.UUID) -> ImportBatch:
    return await _transition_batch(
        session, batch_id, ImportBatchStatus.running, message="batch started"
    )


async def complete_batch(session: AsyncSession, batch_id: uuid.UUID) -> ImportBatch:
    return await _transition_batch(
        session,
        batch_id,
        ImportBatchStatus.completed,
        event_type=BatchEventType.completed.value,
        message="batch completed",
    )


async def fail_batch(
    session: AsyncSession,
    batch_id: uuid.UUID,
    *,
    error_message: str | None = None,
    message: str | None = None,
) -> ImportBatch:
    return await _transition_batch(
        session,
        batch_id,
        ImportBatchStatus.failed,
        event_type=BatchEventType.failed.value,
        message=message or "batch failed",
        error_message=error_message or "batch marked as failed",
    )


async def cancel_batch(
    session: AsyncSession, batch_id: uuid.UUID, *, message: str | None = None
) -> ImportBatch:
    return await _transition_batch(
        session,
        batch_id,
        ImportBatchStatus.cancelled,
        event_type=BatchEventType.cancelled.value,
        message=message or "batch cancelled",
    )


async def update_batch_status(
    session: AsyncSession,
    batch_id: uuid.UUID,
    to_status: ImportBatchStatus,
    *,
    message: str | None = None,
    error_message: str | None = None,
) -> ImportBatch:
    event_type = BatchEventType.status_changed.value
    if to_status == ImportBatchStatus.cancelled:
        event_type = BatchEventType.cancelled.value
    elif to_status == ImportBatchStatus.failed:
        event_type = BatchEventType.failed.value
    elif to_status == ImportBatchStatus.completed:
        event_type = BatchEventType.completed.value
    return await _transition_batch(
        session,
        batch_id,
        to_status,
        message=message,
        error_message=error_message,
        event_type=event_type,
    )


async def apply_batch_status_in_session(
    session: AsyncSession,
    batch: ImportBatch,
    to_status: ImportBatchStatus,
    *,
    message: str | None = None,
    error_message: str | None = None,
    event_type: str = BatchEventType.status_changed.value,
) -> None:
    """Apply batch status change within caller's transaction (no commit)."""
    from_status = ImportBatchStatus(batch.status)
    validate_import_batch_transition(from_status, to_status)

    now = datetime.now(timezone.utc)
    batch.status = to_status.value

    if to_status == ImportBatchStatus.running and batch.started_at is None:
        batch.started_at = now
    if to_status == ImportBatchStatus.completed:
        batch.finished_at = now
    if to_status == ImportBatchStatus.failed:
        batch.failed_at = now
        if error_message:
            batch.error_message = error_message
    if to_status == ImportBatchStatus.cancelled:
        batch.cancelled_at = now

    await _append_event(
        session,
        batch_id=batch.id,
        event_type=event_type,
        from_status=from_status.value,
        to_status=to_status.value,
        message=message or f"status changed to {to_status.value}",
        payload_json={"error_message": error_message} if error_message else None,
    )


async def record_batch_event(
    session: AsyncSession,
    batch_id: uuid.UUID,
    event_type: str,
    *,
    message: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    payload_json: dict[str, Any] | None = None,
) -> ImportBatchEvent:
    """Append batch event within caller's transaction (no commit)."""
    return await _append_event(
        session,
        batch_id=batch_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        message=message,
        payload_json=payload_json,
    )


async def load_resource_files_for_bindings(
    session: AsyncSession, bindings: list[ImportBatchFile]
) -> dict[uuid.UUID, ResourceFile]:
    if not bindings:
        return {}
    file_ids = [b.file_id for b in bindings]
    q = select(ResourceFile).where(ResourceFile.id.in_(file_ids))
    rows = (await session.execute(q)).scalars().all()
    return {r.id: r for r in rows}


def compute_batch_next_actions(status: str) -> list[str]:
    """Advisory action keys for batch management UI (not pipeline execution)."""
    mapping: dict[str, list[str]] = {
        ImportBatchStatus.created.value: ["queue", "cancel"],
        ImportBatchStatus.queued.value: ["start", "cancel"],
        ImportBatchStatus.running.value: ["go_pipeline"],
        ImportBatchStatus.parsed.value: ["go_pipeline"],
        ImportBatchStatus.candidate_generated.value: ["go_pipeline"],
        ImportBatchStatus.validation_dispatched.value: ["go_pipeline"],
        ImportBatchStatus.completed.value: [],
        ImportBatchStatus.failed.value: [],
        ImportBatchStatus.cancelled.value: [],
    }
    return mapping.get(status, [])


async def build_enriched_file_reads(
    session: AsyncSession,
    bindings: list[ImportBatchFile],
    file_map: dict[uuid.UUID, ResourceFile] | None = None,
) -> tuple[list[ImportBatchFileEnrichedRead], list[str]]:
    """Build enriched binding rows with file status and intermediate summary."""
    if file_map is None:
        file_map = await load_resource_files_for_bindings(session, bindings)

    items: list[ImportBatchFileEnrichedRead] = []
    warnings: list[str] = []

    for binding in bindings:
        resource_file = file_map.get(binding.file_id)
        intermediate_summary: dict = {}
        if resource_file is not None:
            intermediate_summary = await file_normalization_service.get_intermediate_summary_for_file(
                session, resource_file.id
            )

        parse_status = raw_parsing_service.assess_bound_file_parse_status(
            resource_file,
            binding.file_role_in_batch,
        )

        warning: str | None = None
        if resource_file is not None and not parse_status["is_active"]:
            warning = (
                f"Bound file {resource_file.id} is not active "
                f"({parse_status.get('inactive_reason', 'unknown')})"
            )
            warnings.append(warning)
        elif (
            resource_file is not None
            and intermediate_summary.get("intermediate_status") == "missing"
        ):
            warning = f"file {resource_file.id} has no intermediate artifact"
            warnings.append(warning)

        from app.schemas.resource_file import ResourceFileRead

        items.append(
            ImportBatchFileEnrichedRead(
                id=binding.id,
                batch_id=binding.batch_id,
                file_id=binding.file_id,
                resource_id=binding.resource_id,
                file_role_in_batch=FileRoleInBatch(binding.file_role_in_batch),
                sort_order=binding.sort_order,
                created_at=binding.created_at,
                original_filename=resource_file.original_filename if resource_file else None,
                file_type=resource_file.file_type if resource_file else None,
                file_role=resource_file.file_role if resource_file else None,
                file_status=(
                    "deleted"
                    if resource_file is not None and resource_file.deleted_at is not None
                    else (resource_file.status if resource_file else None)
                ),
                sha256=resource_file.sha256 if resource_file else None,
                file_size=resource_file.file_size if resource_file else None,
                intermediate_status=intermediate_summary.get("intermediate_status"),
                latest_intermediate_artifact_id=intermediate_summary.get(
                    "latest_intermediate_artifact_id"
                ),
                is_active=bool(parse_status["is_active"]),
                can_parse=bool(parse_status["can_parse"]),
                inactive_reason=parse_status.get("inactive_reason"),  # type: ignore[arg-type]
                warning=warning,
                file=ResourceFileRead.model_validate(resource_file)
                if resource_file is not None
                else None,
            )
        )

    return items, warnings


async def _assert_batch_editable_for_metadata(batch: ImportBatch) -> ImportBatchStatus:
    status = ImportBatchStatus(batch.status)
    if status not in (ImportBatchStatus.created, ImportBatchStatus.queued):
        raise BatchEditNotAllowedError(
            f"batch status {status.value} does not allow metadata edit"
        )
    return status


async def _assert_batch_editable_for_files(batch: ImportBatch) -> ImportBatchStatus:
    status = ImportBatchStatus(batch.status)
    if status not in (ImportBatchStatus.created, ImportBatchStatus.queued):
        raise BatchEditNotAllowedError(
            f"files can only be updated when batch status is created or queued"
        )
    return status


async def _validate_binding_parser_compat(
    batch: ImportBatch,
    binding: ImportBatchFileBinding,
    resource_file: ResourceFile,
) -> None:
    try:
        validate_parser_file_binding(
            batch.parser_key, binding.file_role_in_batch.value, resource_file
        )
    except ParserFileBindingError as exc:
        raise FileBindingError(str(exc)) from exc


async def update_batch(
    session: AsyncSession,
    batch_id: uuid.UUID,
    payload: ImportBatchUpdate,
) -> ImportBatch:
    batch = await get_batch(session, batch_id)
    status = await _assert_batch_editable_for_metadata(batch)

    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return batch

    if status == ImportBatchStatus.queued:
        forbidden = {"batch_code", "batch_type", "parser_key"} & patch.keys()
        if forbidden:
            raise BatchEditNotAllowedError(
                "queued batch: only description and remark can be edited"
            )

    if "batch_code" in patch and patch["batch_code"] is not None:
        batch.batch_code = patch["batch_code"]
    if "batch_type" in patch and patch["batch_type"] is not None:
        batch.batch_type = patch["batch_type"].value
    if "parser_key" in patch:
        batch.parser_key = patch["parser_key"]
    if "description" in patch:
        batch.description = patch["description"]
    if "remark" in patch:
        batch.remark = patch["remark"]

    await _append_event(
        session,
        batch_id=batch.id,
        event_type=BatchEventType.note.value,
        message="batch metadata updated",
        payload_json={k: str(v) if isinstance(v, uuid.UUID) else v for k, v in patch.items()},
    )

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "batch_code" in patch:
            raise BatchCodeConflictError(patch["batch_code"]) from exc
        raise

    await session.refresh(batch)
    _log_action(
        event_type="import_batch",
        action="update",
        result="success",
        batch_id=batch.id,
        resource_id=batch.resource_id,
    )
    return batch


async def replace_batch_files(
    session: AsyncSession,
    batch_id: uuid.UUID,
    files: list[ImportBatchFileBinding],
) -> tuple[list[ImportBatchFile], list[str]]:
    batch = await get_batch(session, batch_id)
    status = await _assert_batch_editable_for_files(batch)
    reset_to_created = status == ImportBatchStatus.queued

    seen_files: set[uuid.UUID] = set()
    warnings: list[str] = []
    for binding in files:
        if binding.file_id in seen_files:
            raise FileBindingError(f"duplicate file_id in request: {binding.file_id}")
        seen_files.add(binding.file_id)
        rf = await _ensure_file_eligible(session, binding.file_id, batch.resource_id)
        await _validate_binding_parser_compat(batch, binding, rf)
        summary = await file_normalization_service.get_intermediate_summary_for_file(
            session, binding.file_id
        )
        if summary.get("intermediate_status") == "missing":
            warnings.append(f"file {binding.file_id} has no intermediate artifact")

    existing = await list_batch_files(session, batch_id)
    for bf in existing:
        await session.delete(bf)
    await session.flush()

    new_bindings: list[ImportBatchFile] = []
    for idx, binding in enumerate(files):
        sort_order = binding.sort_order if binding.sort_order is not None else idx
        bf = ImportBatchFile(
            batch_id=batch.id,
            file_id=binding.file_id,
            resource_id=batch.resource_id,
            file_role_in_batch=binding.file_role_in_batch.value,
            sort_order=sort_order,
        )
        session.add(bf)
        new_bindings.append(bf)
        await _append_event(
            session,
            batch_id=batch.id,
            event_type=BatchEventType.file_attached.value,
            message=f"file attached: {binding.file_id}",
            payload_json={
                "file_id": str(binding.file_id),
                "file_role_in_batch": binding.file_role_in_batch.value,
                "sort_order": sort_order,
                "action": "replace_files",
            },
        )

    if reset_to_created:
        from_status = batch.status
        batch.status = ImportBatchStatus.created.value
        await _append_event(
            session,
            batch_id=batch.id,
            event_type=BatchEventType.status_changed.value,
            from_status=from_status,
            to_status=ImportBatchStatus.created.value,
            message="batch reset to created after file binding change",
        )

    await session.commit()
    for bf in new_bindings:
        await session.refresh(bf)

    _log_action(
        event_type="import_batch",
        action="replace_files",
        result="success",
        batch_id=batch.id,
        resource_id=batch.resource_id,
    )
    return new_bindings, warnings


async def _maybe_reset_queued_to_created(
    session: AsyncSession, batch: ImportBatch
) -> None:
    if batch.status != ImportBatchStatus.queued.value:
        return
    from_status = batch.status
    batch.status = ImportBatchStatus.created.value
    await _append_event(
        session,
        batch_id=batch.id,
        event_type=BatchEventType.status_changed.value,
        from_status=from_status,
        to_status=ImportBatchStatus.created.value,
        message="batch reset to created after file binding change",
    )


async def attach_batch_file(
    session: AsyncSession,
    batch_id: uuid.UUID,
    binding: ImportBatchFileBinding,
) -> list[ImportBatchFile]:
    batch = await get_batch(session, batch_id)
    await _assert_batch_editable_for_files(batch)

    existing = await list_batch_files(session, batch_id)
    if any(b.file_id == binding.file_id for b in existing):
        raise FileBindingError(f"file already bound to batch: {binding.file_id}")

    rf = await _ensure_file_eligible(session, binding.file_id, batch.resource_id)
    await _validate_binding_parser_compat(batch, binding, rf)

    sort_order = binding.sort_order if binding.sort_order is not None else len(existing)
    bf = ImportBatchFile(
        batch_id=batch.id,
        file_id=binding.file_id,
        resource_id=batch.resource_id,
        file_role_in_batch=binding.file_role_in_batch.value,
        sort_order=sort_order,
    )
    session.add(bf)
    await _append_event(
        session,
        batch_id=batch.id,
        event_type=BatchEventType.file_attached.value,
        message=f"file attached: {binding.file_id}",
        payload_json={
            "file_id": str(binding.file_id),
            "file_role_in_batch": binding.file_role_in_batch.value,
            "sort_order": sort_order,
            "action": "attach",
        },
    )
    await _maybe_reset_queued_to_created(session, batch)
    await session.commit()
    await session.refresh(bf)
    return await list_batch_files(session, batch_id)


async def update_batch_file_binding(
    session: AsyncSession,
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    *,
    file_role_in_batch: FileRoleInBatch | None = None,
    sort_order: int | None = None,
) -> list[ImportBatchFile]:
    batch = await get_batch(session, batch_id)
    await _assert_batch_editable_for_files(batch)

    bindings = await list_batch_files(session, batch_id)
    target = next((b for b in bindings if b.file_id == file_id), None)
    if target is None:
        raise FileBindingError(f"file not bound to batch: {file_id}")

    if file_role_in_batch is not None:
        target.file_role_in_batch = file_role_in_batch.value
    if sort_order is not None:
        target.sort_order = sort_order

    rf = await _ensure_file_eligible(session, file_id, batch.resource_id)
    role = FileRoleInBatch(target.file_role_in_batch)
    await _validate_binding_parser_compat(
        batch,
        ImportBatchFileBinding(
            file_id=file_id, file_role_in_batch=role, sort_order=target.sort_order
        ),
        rf,
    )

    await _append_event(
        session,
        batch_id=batch.id,
        event_type=BatchEventType.file_attached.value,
        message=f"file binding updated: {file_id}",
        payload_json={
            "file_id": str(file_id),
            "file_role_in_batch": target.file_role_in_batch,
            "sort_order": target.sort_order,
            "action": "update_binding",
        },
    )
    await _maybe_reset_queued_to_created(session, batch)
    await session.commit()
    return await list_batch_files(session, batch_id)


async def detach_batch_file(
    session: AsyncSession,
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
) -> list[ImportBatchFile]:
    batch = await get_batch(session, batch_id)
    await _assert_batch_editable_for_files(batch)

    bindings = await list_batch_files(session, batch_id)
    target = next((b for b in bindings if b.file_id == file_id), None)
    if target is None:
        raise FileBindingError(f"file not bound to batch: {file_id}")

    await session.delete(target)
    await _append_event(
        session,
        batch_id=batch.id,
        event_type=BatchEventType.file_attached.value,
        message=f"file detached: {file_id}",
        payload_json={"file_id": str(file_id), "action": "detach"},
    )
    await _maybe_reset_queued_to_created(session, batch)
    await session.commit()
    return await list_batch_files(session, batch_id)


async def clone_batch(session: AsyncSession, batch_id: uuid.UUID) -> ImportBatch:
    """Copy batch configuration (not downstream parse/candidate/validation data)."""
    source = await get_batch(session, batch_id)
    source_files = await list_batch_files(session, batch_id)
    await _ensure_resource_eligible(session, source.resource_id)

    desc = source.description
    if desc:
        desc = f"copy of {source.batch_code}: {desc}"
    else:
        desc = f"copy of {source.batch_code}"

    payload = ImportBatchCreate(
        resource_id=source.resource_id,
        batch_type=BatchType(source.batch_type),
        parser_key=source.parser_key,
        description=desc,
        remark=source.remark,
        files=[
            ImportBatchFileBinding(
                file_id=bf.file_id,
                file_role_in_batch=FileRoleInBatch(bf.file_role_in_batch),
                sort_order=bf.sort_order,
            )
            for bf in source_files
        ],
    )
    new_batch = await create_batch(session, payload)
    await _append_event(
        session,
        batch_id=new_batch.id,
        event_type=BatchEventType.note.value,
        message=f"batch cloned from {source.batch_code}",
        payload_json={"cloned_from_batch_id": str(source.id)},
    )
    await session.commit()
    await session.refresh(new_batch)
    _log_action(
        event_type="import_batch",
        action="clone",
        result="success",
        batch_id=new_batch.id,
        resource_id=new_batch.resource_id,
    )
    return new_batch
