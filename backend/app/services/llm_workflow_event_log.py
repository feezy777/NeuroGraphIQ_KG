"""Structured workflow event log stored in composite workflow summary JSON (no new DB tables)."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.llm_composite_workflow import LlmCompositeWorkflowRun, LlmCompositeWorkflowStep

logger = logging.getLogger(__name__)

MAX_STORED_EVENTS = 200
MAX_RECENT_EVENTS = 50
RAW_PREVIEW_MAX = 2000
PROMPT_PREVIEW_MAX = 1000

_SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|authorization|password|secret|token)", re.I)
_SK_RE = re.compile(r"sk-[a-zA-Z0-9]{8,}")


def _truncate(value: Any, limit: int) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
        if len(text) > limit:
            return text[:limit] + f"…[truncated {len(text) - limit} chars]"
        return text
    return value


def _sanitize_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    out: dict[str, Any] = {}
    for key, val in data.items():
        if _SENSITIVE_KEY_RE.search(str(key)):
            continue
        if isinstance(val, str):
            if _SK_RE.search(val):
                val = _SK_RE.sub("sk-***", val)
            if key in {"raw_response_preview", "response_preview"}:
                val = _truncate(val, RAW_PREVIEW_MAX)
            elif key in {"prompt_preview", "user_prompt_preview"}:
                val = _truncate(val, PROMPT_PREVIEW_MAX)
        out[key] = val
    return out


def get_recent_events(summary: dict[str, Any] | None, *, limit: int = MAX_RECENT_EVENTS) -> list[dict[str, Any]]:
    events = list((summary or {}).get("events") or [])
    return events[-limit:]


async def append_workflow_event(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    *,
    step_key: str | None = None,
    level: str = "info",
    event: str,
    message: str,
    data: dict[str, Any] | None = None,
    step: LlmCompositeWorkflowStep | None = None,
    commit: bool = True,
) -> dict[str, Any] | None:
    """Append a structured event to workflow run summary (and optionally step response_json)."""
    run = await session.get(LlmCompositeWorkflowRun, workflow_run_id)
    if run is None:
        return None

    ts = datetime.now(timezone.utc).isoformat()
    sanitized = _sanitize_data(data)
    pack_id = sanitized.get("pack_id", "")
    pack_index = sanitized.get("pack_index", "")
    entry: dict[str, Any] = {
        "event_id": f"{ts}:{step_key or ''}:{event}:{pack_id}:{pack_index}",
        "ts": ts,
        "level": level,
        "step_key": step_key,
        "event": event,
        "message": message,
        "data": sanitized,
    }

    summary = dict(run.result_summary_json or {})
    events = list(summary.get("events") or [])
    events.append(entry)
    if len(events) > MAX_STORED_EVENTS:
        events = events[-MAX_STORED_EVENTS:]
    summary["events"] = events
    run.result_summary_json = summary
    flag_modified(run, "result_summary_json")

    if step is not None:
        resp = dict(step.response_json or {})
        step_events = list(resp.get("events") or [])
        step_events.append(entry)
        if len(step_events) > MAX_STORED_EVENTS:
            step_events = step_events[-MAX_STORED_EVENTS:]
        resp["events"] = step_events
        step.response_json = resp
        flag_modified(step, "response_json")

    if commit:
        await session.flush()
        await session.commit()
    return entry


async def safe_append_workflow_event(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    *,
    step_key: str | None = None,
    level: str = "info",
    event: str,
    message: str,
    data: dict[str, Any] | None = None,
    step: LlmCompositeWorkflowStep | None = None,
    commit: bool = True,
) -> dict[str, Any] | None:
    """Append workflow event; log warning and continue on failure (never raises)."""
    try:
        return await append_workflow_event(
            session,
            workflow_run_id,
            step_key=step_key,
            level=level,
            event=event,
            message=message,
            data=data,
            step=step,
            commit=commit,
        )
    except Exception as exc:
        logger.warning(
            "Failed to append workflow event %s: %s",
            event,
            exc,
            exc_info=True,
        )
        return None
