from __future__ import annotations

from typing import Any, Dict

from ..common.id_utils import make_id
from ..common.log_bus import LogBus
from ..common.models import TaskRun, TaskStatus, TaskType, utc_now_iso
from ..common.state_store import StateStore


class TaskService:
    def __init__(self, store: StateStore, log_bus: LogBus) -> None:
        self.store = store
        self.log_bus = log_bus

    def create_task(
        self,
        task_type: TaskType,
        initiator: str,
        input_objects: Dict[str, Any],
        parameters: Dict[str, Any],
        model_or_rule_version: str = "skeleton-v1",
        trigger_source: str = "ui",
        model_name: str = "",
    ) -> Dict[str, Any]:
        task = TaskRun(
            task_id=make_id("task"),
            task_type=task_type.value,
            initiator=initiator,
            input_objects=input_objects,
            model_or_rule_version=model_or_rule_version,
            parameters=parameters,
            trigger_source=trigger_source,
            model_name=model_name,
            status=TaskStatus.QUEUED.value,
        )
        self.store.put_task(task)
        self.log_bus.emit(
            task.task_id,
            "TASK",
            f"created task_type={task.task_type} initiator={initiator}",
            event_type="task_created",
        )
        return self.store.get_task(task.task_id)

    def start_task(self, task_id: str) -> Dict[str, Any]:
        payload = self.store.update_task(
            task_id,
            status=TaskStatus.RUNNING.value,
            started_at=utc_now_iso(),
            error_reason="",
        )
        self.log_bus.emit(task_id, "TASK", f"start task_type={payload.get('task_type')}", event_type="task_started")
        return payload

    def finish_task(self, task_id: str, output_summary: Dict[str, Any]) -> Dict[str, Any]:
        payload = self.store.update_task(
            task_id,
            status=TaskStatus.SUCCESS.value,
            ended_at=utc_now_iso(),
            output_summary=output_summary,
        )
        self.log_bus.emit(task_id, "TASK", f"finish summary={output_summary}", event_type="task_finished")
        return payload

    def fail_task(self, task_id: str, reason: str) -> Dict[str, Any]:
        payload = self.store.update_task(
            task_id,
            status=TaskStatus.FAILED.value,
            ended_at=utc_now_iso(),
            error_reason=reason,
        )
        self.log_bus.emit(task_id, "TASK", f"failed reason={reason}", level="error", event_type="task_failed")
        return payload

    def block_task(self, task_id: str, reason: str) -> Dict[str, Any]:
        payload = self.store.update_task(
            task_id,
            status=TaskStatus.BLOCKED.value,
            ended_at=utc_now_iso(),
            error_reason=reason,
        )
        self.log_bus.emit(task_id, "TASK", f"blocked reason={reason}", level="warning", event_type="task_blocked")
        return payload

    # 作用：在长任务执行中途更新进度信息，供前端进度条展示。
    # 步骤：把 percent/stage/message 写入 store（存在 parameters_json JSONB，无 DB 迁移）。
    # 注意：不要替换 status，只更新进度三字段。
    def set_progress(self, task_id: str, percent: int, stage: str, message: str = "") -> None:
        self.store.update_task(
            task_id,
            progress_percent=percent,
            progress_stage=stage,
            progress_message=message,
        )
