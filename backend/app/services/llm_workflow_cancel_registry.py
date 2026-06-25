"""In-process cancel registry for composite LLM extraction workflows."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

_lock = asyncio.Lock()
_cancelling: set[uuid.UUID] = set()
_registered_tasks: dict[uuid.UUID, list[asyncio.Task[Any]]] = {}


async def mark_cancelling(workflow_run_id: uuid.UUID) -> None:
    async with _lock:
        _cancelling.add(workflow_run_id)


def is_cancelling(workflow_run_id: uuid.UUID | None) -> bool:
    if workflow_run_id is None:
        return False
    return workflow_run_id in _cancelling


async def clear(workflow_run_id: uuid.UUID) -> None:
    async with _lock:
        _cancelling.discard(workflow_run_id)
        _registered_tasks.pop(workflow_run_id, None)


async def register_task(workflow_run_id: uuid.UUID, task: asyncio.Task[Any]) -> None:
    async with _lock:
        _registered_tasks.setdefault(workflow_run_id, []).append(task)


async def cancel_tasks(workflow_run_id: uuid.UUID) -> int:
    async with _lock:
        tasks = list(_registered_tasks.get(workflow_run_id, []))
    cancelled = 0
    for task in tasks:
        if not task.done():
            task.cancel()
            cancelled += 1
    return cancelled
