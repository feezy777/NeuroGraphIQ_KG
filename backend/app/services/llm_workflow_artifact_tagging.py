"""Helpers to tag mirror / payload records with composite workflow run id."""

from __future__ import annotations

import uuid
from typing import Any


def merge_workflow_attributes(
    payload: dict[str, Any] | None,
    *,
    workflow_run_id: uuid.UUID,
    step_key: str | None = None,
) -> dict[str, Any]:
    merged = dict(payload or {})
    attrs = dict(merged.get("attributes") or {})
    attrs["composite_workflow_run_id"] = str(workflow_run_id)
    if step_key:
        attrs["created_by_workflow_step"] = step_key
    merged["attributes"] = attrs
    return merged


def tag_raw_payload(
    raw_payload: dict[str, Any] | None,
    *,
    workflow_run_id: uuid.UUID,
    step_key: str | None = None,
) -> dict[str, Any]:
    return merge_workflow_attributes(raw_payload, workflow_run_id=workflow_run_id, step_key=step_key)


def tag_attributes_column(
    attributes: dict[str, Any] | None,
    *,
    workflow_run_id: uuid.UUID,
    step_key: str | None = None,
) -> dict[str, Any]:
    return merge_workflow_attributes(
        {"attributes": attributes or {}},
        workflow_run_id=workflow_run_id,
        step_key=step_key,
    )["attributes"]
