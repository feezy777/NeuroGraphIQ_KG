from __future__ import annotations

import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.desktop.models import GateDecision
from scripts.services.file_validation_center import apply_auto_fix, validate_file
from scripts.services.runtime_config import apply_runtime_env


RuntimeProvider = Callable[[], dict[str, Any]]
GateProvider = Callable[[], GateDecision]
LogHandler = Callable[[str], None]


class PreprocessService:
    def __init__(
        self,
        *,
        file_center_root: str | Path,
        runtime_provider: RuntimeProvider,
        gate_provider: GateProvider,
        log_handler: LogHandler | None = None,
    ):
        self._root = Path(file_center_root)
        self._runtime_provider = runtime_provider
        self._gate_provider = gate_provider
        self._log = log_handler or (lambda _msg: None)
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._run_loop, name="desktop_preprocess_worker", daemon=True)
        self._worker.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        self._queue.put("__STOP__")
        self._worker.join(timeout=3.0)

    def enqueue(self, file_id: str, trigger: str = "auto") -> dict[str, Any]:
        file_id = str(file_id or "").strip()
        if not file_id:
            raise ValueError("file_id_missing")
        gate = self._gate_provider()
        task = self._create_task(file_id=file_id, trigger=trigger)
        if not gate.allow_preprocess:
            task["status"] = "blocked"
            task["current_stage"] = "blocked"
            task["error_message"] = gate.block_reason or "preprocess_blocked_by_gate"
            self._update_task(task)
            self._log(f"preprocess blocked file={file_id} reason={task['error_message']}")
            return task
        self._update_task(task)
        self._queue.put(task["task_id"])
        self._log(f"preprocess queued file={file_id} task={task['task_id']}")
        return task

    def enqueue_many(self, file_ids: list[str], trigger: str = "auto") -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for file_id in file_ids:
            out.append(self.enqueue(file_id=file_id, trigger=trigger))
        return out

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(self._tasks[task_id]) for task_id in self._order]

    def _create_task(self, *, file_id: str, trigger: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        task_id = f"pt_{uuid.uuid4().hex[:12]}"
        return {
            "task_id": task_id,
            "file_id": file_id,
            "trigger": trigger,
            "status": "queued",
            "current_stage": "queued",
            "created_at": now,
            "updated_at": now,
            "started_at": "",
            "finished_at": "",
            "error_message": "",
            "overall_label": "",
            "score": None,
            "auto_applied_count": 0,
            "manual_required_count": 0,
            "blocked_on_load": False,
        }

    def _update_task(self, task: dict[str, Any]) -> None:
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        task_id = str(task["task_id"])
        with self._lock:
            if task_id not in self._tasks:
                self._order.insert(0, task_id)
            self._tasks[task_id] = dict(task)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                task_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if task_id == "__STOP__":
                self._queue.task_done()
                return
            try:
                self._run_task(task_id)
            finally:
                self._queue.task_done()

    def _run_task(self, task_id: str) -> None:
        with self._lock:
            task = dict(self._tasks.get(task_id, {}))
        if not task:
            return

        gate = self._gate_provider()
        if not gate.allow_preprocess:
            task["status"] = "blocked"
            task["current_stage"] = "blocked"
            task["error_message"] = gate.block_reason or "preprocess_blocked_by_gate"
            task["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._update_task(task)
            self._log(f"preprocess blocked at run file={task['file_id']} reason={task['error_message']}")
            return

        task["status"] = "running"
        task["current_stage"] = "validate"
        task["started_at"] = datetime.now(timezone.utc).isoformat()
        self._update_task(task)
        self._log(f"preprocess start file={task['file_id']} task={task_id}")

        try:
            runtime = self._runtime_provider()
            apply_runtime_env(runtime)
            report = validate_file(file_id=str(task["file_id"]), runtime=runtime, root=self._root)
            task["current_stage"] = "auto_fix"
            self._update_task(task)
            fixed = apply_auto_fix(file_id=str(task["file_id"]), root=self._root)

            task["status"] = "succeeded"
            task["current_stage"] = "done"
            task["finished_at"] = datetime.now(timezone.utc).isoformat()
            task["overall_label"] = str(report.get("overall_label") or "")
            task["score"] = report.get("score")
            task["manual_required_count"] = int(report.get("manual_required_count", 0))
            task["blocked_on_load"] = bool(report.get("blocked_on_load", False))
            task["auto_applied_count"] = int(fixed.get("auto_applied_count", 0))
            self._update_task(task)
            self._log(
                "preprocess done "
                f"file={task['file_id']} label={task['overall_label']} score={task['score']} "
                f"auto={task['auto_applied_count']}"
            )
        except Exception as exc:
            task["status"] = "failed"
            task["current_stage"] = "failed"
            task["finished_at"] = datetime.now(timezone.utc).isoformat()
            task["error_message"] = str(exc)
            self._update_task(task)
            self._log(f"preprocess failed file={task['file_id']} error={exc}")
            time.sleep(0.05)
