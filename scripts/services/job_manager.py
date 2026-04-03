from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


Worker = Callable[[], dict[str, Any]]


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_job(self, job_type: str, meta: dict[str, Any] | None = None) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "job_type": job_type,
                "status": "queued",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "current_stage": "queued",
                "completed_steps": 0,
                "total_steps": 0,
                "stage_counts": {},
                "error_message": "",
                "logs": [],
                "meta": meta or {},
                "result": None,
            }
        return job_id

    def add_log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["logs"].append(f"{datetime.now(timezone.utc).isoformat()} {message}")
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(fields)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    def on_progress(self, job_id: str, event: dict[str, Any]) -> None:
        updates = {
            "status": event.get("status", "running"),
            "current_stage": event.get("current_stage", ""),
            "completed_steps": int(event.get("completed_steps", 0)),
            "total_steps": int(event.get("total_steps", 0)),
            "stage_counts": event.get("stage_counts", {}),
        }
        if event.get("artifact_paths"):
            updates["artifact_paths"] = event["artifact_paths"]
        if event.get("error_message"):
            updates["error_message"] = event["error_message"]
        self.update(job_id, **updates)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(f"Job not found: {job_id}")
            return dict(job)

    def run_async(self, job_id: str, worker: Worker) -> None:
        def runner() -> None:
            self.update(job_id, status="running", current_stage="starting")
            try:
                result = worker()
                self.update(job_id, status="succeeded", current_stage="done", result=result)
            except Exception as exc:
                self.update(job_id, status="failed", error_message=str(exc), current_stage="failed")
                self.add_log(job_id, f"ERROR: {type(exc).__name__}: {exc}")

        thread = threading.Thread(target=runner, name=job_id, daemon=True)
        thread.start()

